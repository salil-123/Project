"""Train a biomass (AGBD) Random Forest regressor on Alpha Earth embeddings (#3, wk10).

Biomass rides the exact 64-d Alpha Earth feature space our classifiers already use, so a regressor
slots into the framework as a non-linear AE model — it renders on the point grid, the same path
#7's Random Forest split uses. This fits Ratinder's GEDI frame (emb_0..63 [+ slope] -> agbd) and
saves a bundle that `infer.classify_biomass_grid` can serve and the zoo can card.

Honest generalization: GEDI shots are grouped into coarse lat/lon cells and whole cells are held
out, so train and test never share a neighbourhood (a spatial holdout, like our polygon holdout for
classifiers — random row splits would leak adjacent shots and flatter the score).

Run (validate on Ratinder's AEZ-8 frame):
  python scripts/train_biomass.py \
    --csv cod892_biomass/cod892_biomass/biomass_data/gedi_8_2022_merged_final.csv \
    --out data/refine/biomass_aez8.joblib --name aez8
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

ROOT = Path(__file__).resolve().parent.parent


def _emb_cols(df):
    """The 64 embedding columns in band order, whatever they're named (emb_0.. or ae_000..)."""
    hits = [(int(re.search(r"(\d+)$", c).group(1)), c)
            for c in df.columns if re.fullmatch(r"(emb_|ae_)\d+", c)]
    hits.sort()
    return [c for _, c in hits]


def load_frame(csv):
    """Read a GEDI biomass CSV -> (X, y, groups, use_slope, feature_order). X is 64 emb (+ slope);
    y is agbd; groups are coarse 0.1-degree cells for the spatial holdout."""
    df = pd.read_csv(csv)
    emb = _emb_cols(df)
    if len(emb) != 64 or "agbd" not in df.columns:
        raise ValueError(f"{csv}: need 64 emb columns + 'agbd' (got {len(emb)} emb)")
    use_slope = "slope" in df.columns
    cols = emb + (["slope"] if use_slope else [])
    keep = df[cols + ["agbd", "lat", "lon"]].dropna()
    X = keep[cols].values.astype(np.float32)
    y = keep["agbd"].values.astype(np.float32)
    # 0.1-degree cells as spatial groups (GEDI monthly is ~1 km, so this holds out neighbourhoods)
    groups = (np.round(keep.lat.values, 1) * 1000 + np.round(keep.lon.values, 1)).astype(str)
    return X, y, groups, use_slope, cols, (float(keep.lon.min()), float(keep.lat.min()),
                                           float(keep.lon.max()), float(keep.lat.max()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="GEDI biomass frame (emb_* + agbd [+ slope])")
    ap.add_argument("--out", default=None, help="joblib path (default data/refine/biomass_<name>.joblib)")
    ap.add_argument("--name", default="aez", help="short region tag for the card/id")
    ap.add_argument("--n-estimators", type=int, default=300)
    ap.add_argument("--max-depth", type=int, default=None)
    ap.add_argument("--test-size", type=float, default=0.2)
    args = ap.parse_args()

    X, y, groups, use_slope, feat_cols, bbox = load_frame(args.csv)
    print(f"loaded {len(y)} shots, {X.shape[1]} features (slope={use_slope}), "
          f"agbd {y.min():.1f}..{y.max():.1f} Mg/ha (mean {y.mean():.1f})")

    tr, te = next(GroupShuffleSplit(1, test_size=args.test_size, random_state=0).split(X, y, groups))
    rf = RandomForestRegressor(n_estimators=args.n_estimators, max_depth=args.max_depth,
                               n_jobs=-1, random_state=0)
    rf.fit(X[tr], y[tr])
    pred = rf.predict(X[te])
    r2 = r2_score(y[te], pred)
    rmse = float(np.sqrt(mean_squared_error(y[te], pred)))
    mae = float(mean_absolute_error(y[te], pred))
    print(f"\n=== biomass RF ({args.name}): spatial holdout ({len(te)} shots) ===")
    print(f"  R2 {r2:.3f} | RMSE {rmse:.2f} Mg/ha | MAE {mae:.2f} Mg/ha")

    # a plain random split for reference (leaks neighbouring shots -> optimistic; this is the number
    # Ratinder's config reports). We save the honest spatial metric above, print both.
    from sklearn.model_selection import train_test_split
    Xtr2, Xte2, ytr2, yte2 = train_test_split(X, y, test_size=args.test_size, random_state=42)
    rf2 = RandomForestRegressor(n_estimators=args.n_estimators, max_depth=args.max_depth,
                                n_jobs=-1, random_state=0).fit(Xtr2, ytr2)
    r2_rand = r2_score(yte2, rf2.predict(Xte2))
    print(f"  (reference) random-split R2 {r2_rand:.3f}")

    rf.fit(X, y)                                  # refit on everything for the deployed model
    out = Path(args.out) if args.out else ROOT / "data" / "refine" / f"biomass_{args.name}.joblib"
    out.parent.mkdir(parents=True, exist_ok=True)
    bundle = {"model": rf, "kind": "regression", "target": "agbd", "units": "Mg/ha",
              "features": "ae+slope" if use_slope else "ae", "use_slope": use_slope,
              "n_features": X.shape[1], "algo": "randomforest", "name": args.name,
              "extent": list(bbox),
              "metrics": {"r2": round(r2, 3), "rmse": round(rmse, 2), "mae": round(mae, 2),
                          "n_test": int(len(te)), "n_train": int(len(tr))}}
    joblib.dump(bundle, out)
    print(f"saved {out}")
    # biomass is a separate mini-project now (week11 #7) — it no longer cards itself into the LULC
    # zoo. The bundle stands on its own; wire it into a dedicated biomass tool if/when that's built.


if __name__ == "__main__":
    main()
