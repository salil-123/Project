"""How long does Tessera take to download, train and classify vs the Alpha Earth pipeline (#5 wk10).

Real end-to-end wall-clock on one small Tessera site, four stages each:

  download  : Tessera pulls ~150 MB per 0.1-degree tile to disk (cached after); Alpha Earth is
              server-side in Earth Engine, nothing downloaded -> N/A.
  sample    : embeddings at the grid points (Tessera = local tile read; AE = one getInfo round-trip).
  train     : fit a classifier on synthetic labels at the sampled points (RF on Tessera's 128-d,
              LinearSVC on AE's 64-d) -- isolates fit cost from sampling.
  classify  : end-to-end map render (Tessera = soft-vote point grid; AE = band-math tiles).

Everything reuses the live functions so the numbers reflect the real pipelines. Writes
week10/notes/tessera_vs_ae.md.

Run (from repo root, needs EE + Tessera; downloads ~150 MB the first time):
  python scripts/benchmark_tessera_vs_ae.py --site "IIT Delhi + Sanjay Van (acacia)" --n 24
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import LinearSVC
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import infer
import tessera_fast

SITES = {
    "IIT Delhi + Sanjay Van (acacia)": [77.165, 28.520, 77.205, 28.560],
    "Asola Bhatti (mining/acacia)": [77.19, 28.42, 77.27, 28.48],
    "Assam tea belt (tea/non-tea)": [95.75, 27.55, 95.98, 27.73],
}
TILE_MB = 150.0        # ~size of one 0.1-degree Tessera embedding tile (tessera_fast docstring)


def _timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="IIT Delhi + Sanjay Van (acacia)", choices=list(SITES))
    ap.add_argument("--n", type=int, default=24, help="grid size (n x n points)")
    ap.add_argument("--year", type=int, default=2024)
    args = ap.parse_args()
    bbox = SITES[args.site]
    pts = infer._grid(bbox, args.n)
    print(f"site {args.site} | {args.n}x{args.n} = {len(pts)} points | year {args.year}\n")

    r = {}

    # ---- Tessera ----
    (tiles_fetched, r["te_download"]) = _timed(lambda: tessera_fast.prefetch_for_points(pts, args.year))
    (Xte, r["te_sample"]) = _timed(lambda: infer._sample_tessera(pts, args.year))
    yte = np.random.default_rng(0).integers(0, 3, size=len(Xte))          # synthetic labels, fit-cost only
    ok = ~np.isnan(Xte).any(axis=1)
    (_, r["te_train"]) = _timed(lambda: RandomForestClassifier(n_estimators=300, n_jobs=-1)
                                .fit(Xte[ok], yte[ok]))
    (_, r["te_classify"]) = _timed(lambda: infer.classify_bbox_softvote(bbox, n=args.n, year=args.year))

    # ---- Alpha Earth ----
    (Xae, r["ae_sample"]) = _timed(lambda: infer._sample_alpha(pts, bbox, args.year))
    ok2 = ~np.isnan(Xae).any(axis=1)
    (_, r["ae_train"]) = _timed(lambda: make_pipeline(StandardScaler(), LinearSVC(max_iter=5000))
                                .fit(Xae[ok2], yte[ok2]))
    (_, r["ae_classify"]) = _timed(lambda: infer.classify_bbox_tiles(bbox, year=args.year))

    dl_mb = tiles_fetched * TILE_MB
    lines = [
        f"# Tessera vs Alpha Earth timing (#5) — {args.site}",
        "",
        f"Measured live: {args.n}x{args.n} = {len(pts)} points, year {args.year}. Tessera tiles fetched "
        f"this run: {tiles_fetched} (~{dl_mb:.0f} MB).",
        "",
        "| stage | Tessera | Alpha Earth |",
        "|-------|--------:|------------:|",
        f"| download | {r['te_download']:.1f} s (~{dl_mb:.0f} MB){' (cached)' if tiles_fetched == 0 else ''} | n/a (server-side) |",
        f"| sample   | {r['te_sample']:.1f} s | {r['ae_sample']:.1f} s |",
        f"| train    | {r['te_train']:.2f} s (RF 128-d) | {r['ae_train']:.2f} s (LinearSVC 64-d) |",
        f"| classify | {r['te_classify']:.1f} s (soft-vote grid) | {r['ae_classify']:.1f} s (band-math tiles) |",
        f"| **total** | **{r['te_download']+r['te_sample']+r['te_train']+r['te_classify']:.1f} s** | "
        f"**{r['ae_sample']+r['ae_train']+r['ae_classify']:.1f} s** |",
        "",
        "**Takeaway.** Tessera's cost is dominated by the ~150 MB/tile local download (a one-time hit, "
        "then cached) plus local sampling; Alpha Earth downloads nothing and both sampling and the "
        "classify render happen server-side in Earth Engine (the classify is band-math tiles, not a "
        "point grid). Training is comparable once features are in hand. So for browsing anywhere, AE "
        "wins on first-touch latency; Tessera only pays off when you need its 128-d local features and "
        "have already paid the download.",
    ]
    out = ROOT / "week10" / "notes" / "tessera_vs_ae.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
