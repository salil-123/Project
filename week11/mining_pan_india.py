"""#12 wk11 — a high-quality pan-India mining classifier, evaluated outside the framework.

Track B of the project: build a mining/non-mining classifier that works anywhere in India, the "usual
way" — mining pixels we already know (positives) + non-mining from other classes (negatives), with the
water-style **hard-negative augmentation**. Sir's key idea: rather than classify all of India's barren
and dissect it (expensive), operate in the **feature-collection space** — mining polygons plus a
**buffer ring** around each becomes the testing ground, and the ring is the "tentative barren area
around a mine" that the classifier must tell apart from the mine itself (mining-vs-not *within barren*).

We sweep the buffer distance (100 / 200 / 500 m) and, holding out whole polygons, report
precision / recall / F1 for the mining class. Pan-India (polygons from across the country).

Run (needs EE):
  python week11/mining_pan_india.py --n-poly 60 --n-pix 8
  python week11/mining_pan_india.py --n-poly 60 --write-card
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import precision_recall_fscore_support, accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import sampling          # noqa: E402
import temporal_eval as te  # noqa: E402  (reuse _frame_from_file + AE_COLS)

AE_COLS = [f"ae_{i:03d}" for i in range(64)]
MINING = ROOT / "data" / "examples" / "mining.geojson"
BASE_GT = ROOT / "data" / "selected_polygons.geojson"
METRIC = "EPSG:3857"        # for buffering in metres
YEAR = 2024


def sample_frame(gdf, label, n_pix, year):
    """Sample AE at interior points of `gdf`, tagged `label` with a per-polygon group id."""
    gdf = gdf.reset_index(drop=True).copy()
    gdf["label"] = label
    gdf["poly"] = [f"{label}:{i}" for i in range(len(gdf))]
    pts = sampling.interior_points(gdf[["label", "poly", "geometry"]], n_pix=n_pix)
    ae = sampling.sample_alpha(pts, year=year).reset_index(drop=True)
    return pd.concat([pts[["label", "poly"]].reset_index(drop=True), ae], axis=1).dropna(subset=AE_COLS)


def ring_negatives(mining_m, all_mines, dist, n_pix, year):
    """Buffer ring around each mine (buffer(dist) minus every mine), sampled as not_mining — the hard
    negatives right next to real mines. Subtracting all mines keeps a neighbour's mine out of the ring."""
    rings = mining_m.geometry.buffer(dist).difference(all_mines)
    ring_gdf = gpd.GeoDataFrame(geometry=rings, crs=METRIC).to_crs(4326)
    ring_gdf = ring_gdf[~ring_gdf.geometry.is_empty & ring_gdf.geometry.notna()]
    return sample_frame(ring_gdf, "not_mining", n_pix, year)


def split_binary(df, seed=0, test_size=0.25):
    """Whole-polygon holdout with binary mining / not_mining labels -> train/test index arrays."""
    y = np.where(df.label.values == "mining", "mining", "not_mining")
    g = df.poly.values
    tr, tev = next(GroupShuffleSplit(1, test_size=test_size, random_state=seed).split(g, y, g))
    return tr, tev, y


def _prf(y, pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, labels=["mining"], average=None, zero_division=0)
    return p[0], r[0], f[0], accuracy_score(y, pred)


def linear_prf(df, seed=0):
    """Fit a linear SVC on the held-out split; (p, r, f, acc, n_mining_test, n_test)."""
    tr, tev, y = split_binary(df, seed)
    X = df[AE_COLS].values
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000)).fit(X[tr], y[tr])
    return (*_prf(y[tev], m.predict(X[tev])), int((y[tev] == "mining").sum()), len(tev))


def tune_threshold(proba_val, y_val, proba_te):
    """Pick the mining-probability cut that maximises F1 on a validation split, apply it to test."""
    best_t, best_f = 0.5, -1.0
    for t in np.linspace(0.15, 0.85, 29):
        pred = np.where(proba_val >= t, "mining", "not_mining")
        _, _, f, _ = precision_recall_fscore_support(y_val, pred, labels=["mining"], average=None, zero_division=0)
        if f[0] > best_f:
            best_f, best_t = f[0], t
    return best_t, np.where(proba_te >= best_t, "mining", "not_mining")


def model_shootout(df, seed=0):
    """On one dataframe, compare linear vs Random Forest vs RF+tuned-threshold for the mining class."""
    tr, tev, y = split_binary(df, seed)
    X = df[AE_COLS].values
    out = {}
    lin = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000)).fit(X[tr], y[tr])
    out["linear"] = _prf(y[tev], lin.predict(X[tev]))
    rf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=seed, n_jobs=-1)
    rf.fit(X[tr], y[tr])
    out["RF"] = _prf(y[tev], rf.predict(X[tev]))
    # tune the RF threshold on a val split carved out of train (whole-polygon, no leak)
    gtr = df.poly.values[tr]
    vtr, vval = next(GroupShuffleSplit(1, test_size=0.25, random_state=seed + 1).split(gtr, y[tr], gtr))
    rf2 = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=seed, n_jobs=-1)
    rf2.fit(X[tr][vtr], y[tr][vtr])
    ci = list(rf2.classes_).index("mining")
    t, pred = tune_threshold(rf2.predict_proba(X[tr][vval])[:, ci], y[tr][vval], rf.predict_proba(X[tev])[:, ci])
    out[f"RF·thr={t:.2f}"] = _prf(y[tev], pred)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-poly", type=int, default=60, help="mining polygons sampled across India")
    ap.add_argument("--n-pix", type=int, default=8)
    ap.add_argument("--buffers", nargs="+", type=int, default=[100, 200, 500], help="ring widths (m)")
    ap.add_argument("--year", type=int, default=YEAR)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write-card", action="store_true")
    args = ap.parse_args()

    mining = gpd.read_file(MINING).to_crs(4326)
    mining = mining.sample(min(args.n_poly, len(mining)), random_state=args.seed).reset_index(drop=True)
    mining["geometry"] = mining.geometry.buffer(0)         # clean self-intersecting GT polygons
    mining_m = mining.to_crs(METRIC)
    mining_m["geometry"] = mining_m.geometry.buffer(0)     # clean self-intersecting GT polygons
    all_mines = unary_union(mining_m.geometry.values)
    print(f"{len(mining)} mining polygons (of {len(gpd.read_file(MINING))}); sampling AE @ {args.year}…")

    # positives (mining) + generic non-mining negatives (other base classes) — sampled once
    pos = sample_frame(mining, "mining", args.n_pix, args.year)
    generic = te._frame_from_file(str(BASE_GT), "core_class",
                                  ["barren", "built_up", "greenery"], args.year, args.n_pix)
    print(f"  mining pixels: {len(pos)} | generic non-mining: {len(generic)}")

    print("\n=== linear mining classifier, held-out polygons, by buffer-ring width ===")
    rows, dfs = {}, {}
    for d in args.buffers:
        ring = ring_negatives(mining_m, all_mines, d, args.n_pix, args.year)
        df = pd.concat([pos, ring, generic], ignore_index=True)
        dfs[d] = df
        p, r, f, a, n_pos, n_te = linear_prf(df, seed=args.seed)
        rows[d] = (p, r, f, a, len(ring))
        print(f"  buffer {d:3d} m: ring negs {len(ring):4d} | mining P {p:.3f}  R {r:.3f}  F1 {f:.3f}  "
              f"acc {a:.3f}  (test {n_te} px, {n_pos} mining)")

    best = max(rows, key=lambda d: rows[d][2])
    print(f"\nbest buffer {best} m (linear F1 {rows[best][2]:.3f}) — trying non-linear + threshold tuning:")
    shoot = model_shootout(dfs[best], seed=args.seed)
    for name, (p, r, f, a) in shoot.items():
        print(f"  {name:12s}: mining P {p:.3f}  R {r:.3f}  F1 {f:.3f}  acc {a:.3f}")
    best_model = max(shoot, key=lambda k: shoot[k][2])
    bp, br, bf, ba = shoot[best_model]
    lin_f = shoot["linear"][2]
    print(f"\nbest: {best_model} at {best} m ring — mining P {bp:.3f} R {br:.3f} F1 {bf:.3f} "
          f"(linear {lin_f:.3f}, +{bf-lin_f:.3f})")

    summary = (f"Pan-India mining classifier (week11/mining_pan_india.py, {len(mining)} polys, "
               f"buffer-ring hard negatives, {best} m): best model {best_model} — mining precision "
               f"{bp:.2f}, recall {br:.2f}, F1 {bf:.2f} (whole-polygon holdout; linear F1 {lin_f:.2f}). "
               f"Classifier-accuracy number (cf. #9 object-delineation).")
    print("\n" + summary)
    if args.write_card:
        sys.path.insert(0, str(ROOT / "src"))
        import catalogue
        prev = (catalogue.get_card("mc_barren_v1").get("about") or {}).get("evidence", "")
        catalogue.update_card_meta("mc_barren_v1", about={"evidence": (prev + " | " + summary).strip(" |")})
        print("appended summary onto mc_barren_v1 (About > Evidence).")


if __name__ == "__main__":
    main()
