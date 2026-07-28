"""Training-time benchmark + server-admin profile (#8).

Sir's ask: give a server admin a config that answers "for a ~10 km bbox at 10% training data, how
long does this box take to train a model?" — with real profiling, in the Earth-Engine context.

Two costs dominate, and they scale differently, so we time them separately:
  - **EE sampling** (network-bound): pulling Alpha Earth vectors at N points. This is usually the
    big one — our models are linear, so the fit is cheap.
  - **fit** (CPU-bound): fitting the classifier on M rows. We time each linear estimator we serve,
    plus RandomForest as a local-only reference (RF can't be replayed as band math, but it's the
    natural "what if we trained something heavier locally" comparison).

We fit a simple linear model to each cost (time ~= a + b*n) from a few sample sizes, write the
coefficients to data/benchmark_profile.json, and render week9/benchmarks.md — a table of estimated
train times by bbox size at 10% pixel density. /api/estimate reads the same profile live.

Run from repo root:  python scripts/benchmark_training.py [--max-sample 2000]
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.ensemble import RandomForestClassifier

import sampling

PROFILE = ROOT / "data" / "benchmark_profile.json"
DOC = ROOT / "week9" / "benchmarks.md"

# 1 km^2 at 10 m = 10,000 px; "10% training data" -> 1,000 points per km^2.
PTS_PER_KM2 = 1000
BBOX_KM2 = [1, 4, 25, 100]          # ~1x1, 2x2, 5x5, 10x10 km
SAMPLE_BATCH = 3000                  # sampling.sample_alpha's getInfo batch size — the real unit of cost
ALGOS = {
    "linearsvc": lambda: make_pipeline(StandardScaler(), LinearSVC(max_iter=5000)),
    "logreg":    lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
    "ridge":     lambda: make_pipeline(StandardScaler(), RidgeClassifier()),
    "randomforest": lambda: RandomForestClassifier(n_estimators=300, n_jobs=-1),  # RF on AE/Tessera (#7)
}
# XGBoost is optional; profile it only when installed so /api/estimate can cover a Tessera XGB run.
try:
    from xgboost import XGBClassifier
    ALGOS["xgboost"] = lambda: XGBClassifier(n_estimators=300, max_depth=6, n_jobs=-1,
                                             tree_method="hist")
except Exception:
    pass


def _fit_line(ns, ts):
    """Least-squares a + b*n through (ns, ts). Returns (a, b)."""
    b, a = np.polyfit(ns, ts, 1)[0], np.polyfit(ns, ts, 1)[1]
    return float(a), float(b)


def _grid_points(center, k):
    """k points on a small lat/lon grid around a center — a stand-in AOI to time EE sampling."""
    side = int(np.ceil(np.sqrt(k)))
    lon0, lat0 = center
    xs = np.linspace(lon0 - 0.02, lon0 + 0.02, side)
    ys = np.linspace(lat0 - 0.02, lat0 + 0.02, side)
    pts = [Point(x, y) for y in ys for x in xs][:k]
    gdf = gpd.GeoDataFrame(geometry=pts, crs=4326)
    gdf["lon"] = gdf.geometry.x
    gdf["lat"] = gdf.geometry.y
    return gdf


def bench_sampling(max_sample):
    """Profile Alpha Earth sampling. The cost isn't smoothly per-point — `sample_alpha` batches
    getInfo at SAMPLE_BATCH points/call, so the real unit is the per-call round-trip latency. We
    warm EE up first (the very first call carries init overhead and would skew everything), then
    time a couple of sizes and take the median seconds *per batch call*. Returns
    ({per_call_s, batch}, raw)."""
    _grid_points((77.185, 28.540), 25).pipe(sampling.sample_alpha)   # warm-up, discarded
    sizes = [n for n in (400, max_sample) if n <= max_sample] or [max_sample]
    raw, per_call = {}, []
    for n in sizes:
        gdf = _grid_points((77.185, 28.540), n)
        t0 = time.perf_counter()
        sampling.sample_alpha(gdf)
        dt = time.perf_counter() - t0
        calls = int(np.ceil(n / SAMPLE_BATCH))
        raw[n] = dt
        per_call.append(dt / calls)
        print(f"  sample {n:5d} pts ({calls} call(s)): {dt:6.2f}s  -> {dt/calls:5.2f}s/call")
    return {"per_call_s": float(np.median(per_call)), "batch": SAMPLE_BATCH}, raw


def bench_fit():
    """Time each estimator over a few row counts -> {algo: (a, b)} for seconds ~= a + b*n_rows."""
    rng = np.random.default_rng(0)
    sizes = [1000, 5000, 20000]
    out = {}
    for name, mk in ALGOS.items():
        ns, ts = [], []
        for m in sizes:
            X = rng.standard_normal((m, 64)).astype(np.float32)
            y = rng.integers(0, 4, m)
            t0 = time.perf_counter()
            mk().fit(X, y)
            dt = time.perf_counter() - t0
            ns.append(m); ts.append(dt)
        out[name] = _fit_line(ns, ts)
        print(f"  fit {name:12s}: {dict(zip(ns, [round(t,3) for t in ts]))}")
    return out


def estimate(area_km2, algo, profile):
    """Estimated seconds to train on `area_km2` at 10% density with `algo`, from a saved profile.
    Sampling = per-call latency x number of getInfo batches; fit = a + b*rows (clamped >= 0)."""
    import math
    n = area_km2 * PTS_PER_KM2
    s = profile["sampling"]
    sample_s = s["per_call_s"] * math.ceil(n / s["batch"])
    fa, fb = profile["fit"].get(algo, profile["fit"]["linearsvc"])
    fit_s = max(0.0, fa + fb * n)
    return {"n_points": n, "sample_s": sample_s, "fit_s": fit_s, "total_s": sample_s + fit_s}


def write_doc(profile):
    lines = ["# Training-time benchmark (server-admin config) — #8", "",
             f"Profiled on **{profile['hardware']}** at {profile['generated']}.", "",
             "Estimated wall-clock to train one model at **10% pixel density** (1,000 pts/km²), by",
             "AOI size. Sampling is Alpha Earth over Earth Engine (network-bound, usually dominant);",
             "the linear fits are cheap. RandomForest is a **local-only** reference — it can't be",
             "served as EE band math like the linear models, so it's the 'heavier local option' cost.",
             "", "| AOI (km²) | ~pts | sample (s) | linearsvc fit (s) | randomforest fit (s) | total linearsvc (s) |",
             "|-----------|------|-----------|-------------------|----------------------|---------------------|"]
    for km2 in BBOX_KM2:
        lin = estimate(km2, "linearsvc", profile)
        rf = estimate(km2, "randomforest", profile)
        lines.append(f"| {km2} | {lin['n_points']:,} | {lin['sample_s']:.1f} | {lin['fit_s']:.2f} "
                     f"| {rf['fit_s']:.2f} | {lin['total_s']:.1f} |")
    s = profile["sampling"]
    lines += ["", "Model:",
              f"- sampling ≈ {s['per_call_s']:.2f}s per getInfo call of {s['batch']:,} points "
              f"(so ⌈n/{s['batch']:,}⌉ calls)",
              *[f"- fit/{k} ≈ {v[0]:.3f} + {v[1]:.7f}·rows seconds" for k, v in profile["fit"].items()],
              "", "Tune the AOI caps in `config.py` (`AOI_*`) against these numbers so a drawn box",
              "can't ask for more than the server should take on. `GET /api/estimate` returns a live",
              "estimate from this same profile."]
    DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {DOC}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-sample", type=int, default=2000, help="largest EE sample size to time")
    args = ap.parse_args()

    print("timing EE sampling…")
    sampling_prof, sample_raw = bench_sampling(args.max_sample)
    print("timing fits…")
    fit = bench_fit()

    profile = {"generated": time.strftime("%Y-%m-%d %H:%M"),
               "hardware": f"{platform.system()} {platform.machine()}, py{platform.python_version()}",
               "pts_per_km2": PTS_PER_KM2, "sampling": sampling_prof, "fit": fit,
               "sample_raw": sample_raw}
    PROFILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"wrote {PROFILE}")
    write_doc(profile)
    for km2 in BBOX_KM2:
        e = estimate(km2, "linearsvc", profile)
        print(f"  {km2:4d} km^2 -> ~{e['total_s']:.0f}s ({e['n_points']:,} pts, linearsvc)")


if __name__ == "__main__":
    main()
