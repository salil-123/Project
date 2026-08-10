"""#11 wk11 — acacia/non-acacia: counts, a *gentle* noise filter, and real accuracy levers.

Two things sir asked, plus the "make it better" follow-up:
  1. how many crowns? (acacia vs non-acacia)
  2. drop noise crowns — but NOT 98% of the data. Our crowns are all single trees (median ~27 m²,
     smaller than one 10 m Alpha Earth pixel), so a 100 m² cutoff nukes everything. We instead drop
     only the degenerate slivers (< --min-area, default 15 m²) and keep the rest.
  3. improve the result. Acacia-vs-non-acacia on 10 m Alpha Earth is near-random because each crown is
     a *mixed* pixel (tree + surrounding ground). The proven levers (week9 note): multi-year pooling
     and a non-linear model. We compare linear-1yr (the weak baseline) vs multi-year + Random Forest +
     a tuned decision threshold, all with whole-crown holdout, reporting precision / recall / F1.

Run (needs EE):
  python week11/acacia_eval.py --years 2022 2023 2024 --n-pix 4
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import precision_recall_fscore_support, accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import sampling      # noqa: E402
import examples      # noqa: E402

AE_COLS = [f"ae_{i:03d}" for i in range(64)]
NODES = ["acacia", "non_acacia"]
EQ_AREA = "EPSG:6933"
POS = "acacia"


def load_and_filter(min_area_m2):
    """Per-node crown GeoDataFrame with a gentle noise filter (drop only sub-`min_area` slivers)."""
    out = {}
    for node in NODES:
        gdf = gpd.GeoDataFrame.from_features(examples.load_examples(node)["features"], crs="EPSG:4326")
        area = gdf.to_crs(EQ_AREA).geometry.area
        keep = area >= min_area_m2
        out[node] = {"gdf": gdf[keep].reset_index(drop=True), "n": len(gdf),
                     "dropped": int((~keep).sum()), "median": float(area.median())}
    return out


def frame_from_gdf(gdf, node, n_pix, year):
    gdf = gdf.reset_index(drop=True).copy()
    gdf["label"] = node
    gdf["poly"] = [f"{node}:{i}" for i in range(len(gdf))]
    pts = sampling.interior_points(gdf[["label", "poly", "geometry"]], n_pix=n_pix)
    ae = sampling.sample_alpha(pts, year=year).reset_index(drop=True)
    return pd.concat([pts[["label", "poly"]].reset_index(drop=True), ae], axis=1).dropna(subset=AE_COLS)


def prf(y, pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, labels=[POS], average=None, zero_division=0)
    return p[0], r[0], f[0], accuracy_score(y, pred)


def tune_threshold(proba_val, y_val, proba_te):
    """Pick the acacia-probability cut that maximises F1 on a validation split, apply it to test."""
    best_t, best_f = 0.5, -1
    for t in np.linspace(0.15, 0.85, 29):
        pred = np.where(proba_val >= t, POS, "non_acacia")
        _, _, f, _ = precision_recall_fscore_support(y_val, pred, labels=[POS], average=None, zero_division=0)
        if f[0] > best_f:
            best_f, best_t = f[0], t
    return best_t, np.where(proba_te >= best_t, POS, "non_acacia")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024])
    ap.add_argument("--n-pix", type=int, default=4)
    ap.add_argument("--min-area", type=float, default=15.0, help="drop crowns under this many m^2 (noise)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    info = load_and_filter(args.min_area)
    print("=== crown counts (gentle noise filter) ===")
    for n in NODES:
        i = info[n]
        print(f"  {n:11s}: {i['n']:4d} crowns (median {i['median']:.0f} m²), "
              f"{i['dropped']:3d} under {args.min_area:.0f} m² dropped -> {len(i['gdf'])} kept")

    # sample every kept crown at each year; poly ids are stable across years so the holdout is fixed
    print(f"\nsampling AE at years {args.years} (n_pix={args.n_pix})… (hits EE per year)")
    frames = {}
    for y in args.years:
        frames[y] = pd.concat([frame_from_gdf(info[n]["gdf"], n, args.n_pix, y) for n in NODES],
                              ignore_index=True)
        print(f"  {y}: {len(frames[y])} pixels")

    # one fixed whole-crown split, reused for every config
    ref = frames[args.years[-1]]
    polys = ref.poly.values
    tr_i, te_i = next(GroupShuffleSplit(1, test_size=0.25, random_state=args.seed)
                      .split(polys, ref.label.values, polys))
    train_polys, test_polys = set(ref.poly.iloc[tr_i]), set(ref.poly.iloc[te_i])

    def rows(df, which):
        keep = df.poly.isin(train_polys if which == "train" else test_polys)
        return df[keep][AE_COLS].values, df[keep].label.values

    pooled_tr = pd.concat([frames[y][frames[y].poly.isin(train_polys)] for y in args.years], ignore_index=True)
    Xtr_pool, ytr_pool = pooled_tr[AE_COLS].values, pooled_tr.label.values
    Xte, yte = rows(frames[args.years[-1]], "test")          # test on the newest year's held-out crowns
    Xtr1, ytr1 = rows(frames[args.years[-1]], "train")       # single-year train

    print(f"\ntest set: {len(yte)} pixels, {int((yte==POS).sum())} acacia (held-out crowns, {args.years[-1]})\n")
    print("=== configurations (acacia class) ===")
    rowsout = {}

    # a) baseline: linear, single year
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000)).fit(Xtr1, ytr1)
    rowsout["linear · 1yr (baseline)"] = prf(yte, m.predict(Xte))

    # b) linear, multi-year pooled
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000)).fit(Xtr_pool, ytr_pool)
    rowsout["linear · multi-year"] = prf(yte, m.predict(Xte))

    # c) Random Forest, multi-year pooled (non-linear lever)
    rf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=args.seed, n_jobs=-1)
    rf.fit(Xtr_pool, ytr_pool)
    rowsout["RF · multi-year"] = prf(yte, rf.predict(Xte))

    # d) RF multi-year + tuned threshold (tune on a val split of the pooled train)
    vtr, vval = next(GroupShuffleSplit(1, test_size=0.25, random_state=args.seed + 1)
                     .split(pooled_tr, pooled_tr.label, pooled_tr.poly))
    rf2 = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=args.seed, n_jobs=-1)
    rf2.fit(pooled_tr.iloc[vtr][AE_COLS].values, pooled_tr.iloc[vtr].label.values)
    ci = list(rf2.classes_).index(POS)
    t, pred_te = tune_threshold(rf2.predict_proba(pooled_tr.iloc[vval][AE_COLS].values)[:, ci],
                                pooled_tr.iloc[vval].label.values, rf.predict_proba(Xte)[:, ci])
    rowsout[f"RF · multi-year · thr={t:.2f}"] = prf(yte, pred_te)

    for name, (p, r, f, a) in rowsout.items():
        print(f"  {name:32s}: P {p:.3f}  R {r:.3f}  F1 {f:.3f}  acc {a:.3f}")

    base_f = rowsout["linear · 1yr (baseline)"][2]
    best_name = max(rowsout, key=lambda k: rowsout[k][2])
    best_f = rowsout[best_name][2]
    print(f"\nbest: {best_name} at F1 {best_f:.3f}  (baseline {base_f:.3f}, +{best_f-base_f:.3f})")
    print("Ceiling note: crowns are sub-pixel on 10 m AE (mixed pixels), so per-pixel tops out here; "
          "the real lift is higher-res features — Tessera / drone-RGB DINO (external).")


if __name__ == "__main__":
    main()
