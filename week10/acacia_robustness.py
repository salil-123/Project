"""Acacia / non-acacia: spatial AND temporal robustness (#8 wk10).

Sir's ask: don't just hold out years (temporal), also hold out whole *regions* (spatial) — train on
some regions in some years, test on a different region in different years — and aggregate accuracy
across the test years so a fluke year shows up.

Our acacia crowns carry a source region in their `area` property (persisted by
prep_acacia_examples.py). The confident acacia positives live almost entirely in the four Sanjay Van
strips (SV_S1..SV_S4), so the region holdout runs across those: train on SV_S1/S2/S3 (+ all the other
regions' non-acacia), test on the held-out SV_S4 — which still has both classes. Years are Alpha
Earth's; we pool a few for training and test on ones the model never saw.

Four numbers, from the same LinearSVC (StandardScaler + balanced), so they're comparable:
  - temporal-only  : random polygon holdout, train years vs unseen eval years (the wk7 check)
  - spatial-only   : hold out region SV_S4, same year (train other regions, test SV_S4)
  - spatial+temporal: hold out region SV_S4 AND the year (the hardest, most honest number)
  - per-eval-year  : the combined model's accuracy on SV_S4 each eval year -> spot a fluke year

Run (from repo root, needs EE):
  python week10/acacia_robustness.py --train-years 2019 2021 2023 --eval-years 2020 2024 --n-pix 6
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import examples

AE_COLS = [f"ae_{i:03d}" for i in range(64)]
NODES = ["acacia", "non_acacia"]
TEST_REGION = "SV_S4"          # the held-out Sanjay Van strip (has both classes)


def frame(year, n_pix):
    """Both classes sampled at one Alpha Earth year -> label, poly, area, ae_000.. . `area` rides
    through build_training_frame now (#8), so we can split by region."""
    parts = [examples.build_training_frame(node, n_pix=n_pix, year=year) for node in NODES]
    df = pd.concat(parts, ignore_index=True)
    if "area" not in df.columns:
        raise SystemExit("examples carry no `area` — re-run scripts/prep_acacia_examples.py first")
    return df


def _fit(df):
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced"))
    m.fit(df[AE_COLS].values, df.label.values)
    return m


def _acc(m, df):
    return accuracy_score(df.label.values, m.predict(df[AE_COLS].values)) if len(df) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-years", nargs="+", type=int, default=[2019, 2021, 2023])
    ap.add_argument("--eval-years", nargs="+", type=int, default=[2020, 2024])
    ap.add_argument("--n-pix", type=int, default=6)
    ap.add_argument("--test-size", type=float, default=0.25)
    args = ap.parse_args()

    years = sorted(set(args.train_years) | set(args.eval_years))
    print(f"sampling {NODES} at years {years} (n_pix={args.n_pix}) — this hits EE per year…")
    frames = {y: frame(y, args.n_pix) for y in years}
    for y in years:
        f = frames[y]
        n_reg = f[f.area == TEST_REGION]
        print(f"  {y}: {len(f)} px, held-out region {TEST_REGION} has {len(n_reg)} px "
              f"({dict(n_reg.label.value_counts())})")

    base = frames[args.train_years[0]]
    in_test_region = lambda d: d[d.area == TEST_REGION]
    not_test_region = lambda d: d[d.area != TEST_REGION]

    # 1) temporal-only: random polygon holdout, pooled train years vs unseen eval years
    tr_poly, te_poly = next(GroupShuffleSplit(1, test_size=args.test_size, random_state=0)
                            .split(base, base.label, base.poly))
    train_polys, test_polys = set(base.poly.iloc[tr_poly]), set(base.poly.iloc[te_poly])
    m_t = _fit(pd.concat([frames[y][frames[y].poly.isin(train_polys)] for y in args.train_years]))
    temporal = np.mean([_acc(m_t, frames[y][frames[y].poly.isin(test_polys)]) for y in args.eval_years])

    # 2) spatial-only: hold out region SV_S4, same (newest train) year
    yr = args.train_years[-1]
    m_s = _fit(not_test_region(frames[yr]))
    spatial = _acc(m_s, in_test_region(frames[yr]))

    # 3) spatial + temporal: hold out region AND year (the honest worst case)
    m_st = _fit(pd.concat([not_test_region(frames[y]) for y in args.train_years]))
    combined = np.mean([_acc(m_st, in_test_region(frames[y])) for y in args.eval_years])

    # 4) per-eval-year accuracy of the combined model on the held-out region -> fluke-year check
    per_year = {y: _acc(m_st, in_test_region(frames[y])) for y in args.eval_years}

    print("\n=== acacia / non-acacia robustness ===")
    print(f"  temporal-only (random region, unseen years) : {temporal:.3f}")
    print(f"  spatial-only  (held-out {TEST_REGION}, year {yr})     : {spatial:.3f}")
    print(f"  spatial+temporal (held-out region & year)    : {combined:.3f}")
    print(f"  per eval-year on {TEST_REGION}: " +
          ", ".join(f"{y}={a:.3f}" for y, a in per_year.items()))
    spread = np.nanmax(list(per_year.values())) - np.nanmin(list(per_year.values()))
    print(f"  year-to-year spread on held-out region       : {spread:.3f} "
          f"({'stable' if spread < 0.1 else 'watch for a fluke year'})")


if __name__ == "__main__":
    main()
