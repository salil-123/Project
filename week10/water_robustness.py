"""Per-fortnight water: spatial AND temporal robustness (#11 wk10, step 1).

Sir's ask: test the water/non-water classifier for spatial robustness (some water bodies in train,
others held out) and temporal robustness (train some years, test others), and aggregate accuracy
across the test years so a fluke year shows up.

The seasonal-water polygons carry exactly what we need: `waterbody` (205 ids) for the spatial group
and `date` (DDMMYYYY, 2016-2025) for the year. We sample the same raw Sentinel features the deployed
model uses (sentinel.sample_points, at each polygon's own date), then report four numbers from one
`StandardScaler + LinearSVC(balanced)` so they're comparable:
  - temporal-only : hold out whole years (all water bodies), the wk9 temporal check
  - spatial-only  : hold out whole water bodies (all years)
  - spatial+temporal : hold out water bodies AND years (the honest worst case)
  - per-eval-year : the combined model's accuracy each test year -> fluke-year check

Sampling cost is one EE round-trip per distinct date, so --max-dates caps it for a quick run.

Run (from repo root, needs EE):
  python week10/water_robustness.py --max-dates 80 --n-pix 8 --test-years 2023 2024
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
from sklearn.metrics import accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import sampling
import sentinel

GEOJSON = ROOT / "data" / "inputs" / "seasonal_water.geojson"


def build_frame(max_dates, n_pix):
    """Sample Sentinel water features at the seasonal-water polygons -> a frame with label,
    waterbody, year, poly + the 9 feature bands. One EE call per distinct date (capped)."""
    gdf = gpd.read_file(GEOJSON).to_crs(4326)
    gdf = gdf[gdf.waterbody.notna() & gdf.date.notna()].copy()
    gdf["year"] = gdf.date.astype(str).str[4:8]
    gdf["poly"] = [f"{wb}:{i}" for i, wb in enumerate(gdf.waterbody)]

    pts = sampling.interior_points(gdf[["label", "waterbody", "year", "date", "poly", "geometry"]],
                                   n_pix=n_pix)
    dates = sorted(pts.date.unique())
    if max_dates and len(dates) > max_dates:                 # subsample dates evenly to keep it quick
        dates = list(np.array(dates)[np.linspace(0, len(dates) - 1, max_dates).astype(int)])
    print(f"{len(gdf)} polygons, sampling {len(dates)} dates (n_pix={n_pix})…")

    frames = []
    for k, d in enumerate(dates, 1):
        sub = pts[pts.date == d]
        try:
            feats = sentinel.sample_points(sub, sentinel.date_from_ddmmyyyy(d))
        except Exception as e:
            print(f"  [{k}/{len(dates)}] {d}: skipped ({str(e)[:50]})")
            continue
        frames.append(pd.concat([sub[["label", "waterbody", "year", "poly"]].reset_index(drop=True),
                                 feats.reset_index(drop=True)], axis=1))
        if k % 20 == 0 or k == len(dates):
            print(f"  [{k}/{len(dates)}] rows so far: {sum(len(f) for f in frames)}")
    return pd.concat(frames, ignore_index=True).dropna(subset=sentinel.FEATURE_BANDS)


def fit(df):
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000))
    m.fit(df[sentinel.FEATURE_BANDS].values, df.label.values)
    return m


def acc(m, df):
    return accuracy_score(df.label.values, m.predict(df[sentinel.FEATURE_BANDS].values)) if len(df) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dates", type=int, default=80)
    ap.add_argument("--n-pix", type=int, default=8)
    ap.add_argument("--test-years", nargs="+", default=["2023", "2024"])
    ap.add_argument("--test-frac-wb", type=float, default=0.25, help="fraction of water bodies held out")
    args = ap.parse_args()

    df = build_frame(args.max_dates, args.n_pix)
    print(f"\n{len(df)} usable pixels; labels {df.label.value_counts().to_dict()}; "
          f"years {sorted(df.year.unique())}; water bodies {df.waterbody.nunique()}")

    # deterministic spatial holdout: a fixed fraction of water bodies
    rng = np.random.default_rng(0)
    wbs = np.array(sorted(df.waterbody.unique()))
    test_wb = set(rng.choice(wbs, size=max(1, int(len(wbs) * args.test_frac_wb)), replace=False))
    test_yr = set(args.test_years)
    in_test_wb = df.waterbody.isin(test_wb)
    in_test_yr = df.year.isin(test_yr)

    # 1) temporal-only: hold out years, all water bodies
    m_t = fit(df[~in_test_yr])
    temporal = acc(m_t, df[in_test_yr])
    # 2) spatial-only: hold out water bodies, all years
    m_s = fit(df[~in_test_wb])
    spatial = acc(m_s, df[in_test_wb])
    # 3) spatial + temporal: hold out both
    m_st = fit(df[~in_test_wb & ~in_test_yr])
    combined = acc(m_st, df[in_test_wb & in_test_yr])
    # 4) per eval-year on the held-out water bodies (fluke-year check)
    per_year = {y: acc(m_st, df[in_test_wb & (df.year == y)]) for y in sorted(test_yr)}

    print("\n=== water/non-water robustness ===")
    print(f"  held-out water bodies: {len(test_wb)}/{len(wbs)} | held-out years: {sorted(test_yr)}")
    print(f"  temporal-only (unseen years, all bodies)   : {temporal:.3f}")
    print(f"  spatial-only  (unseen water bodies)        : {spatial:.3f}")
    print(f"  spatial+temporal (unseen bodies & years)   : {combined:.3f}")
    valid = {y: a for y, a in per_year.items() if a == a}
    print(f"  per eval-year on held-out bodies: " + ", ".join(f"{y}={a:.3f}" for y, a in valid.items()))
    if len(valid) > 1:
        spread = max(valid.values()) - min(valid.values())
        print(f"  year-to-year spread: {spread:.3f} "
              f"({'stable' if spread < 0.1 else 'watch for a fluke year'})")


if __name__ == "__main__":
    main()
