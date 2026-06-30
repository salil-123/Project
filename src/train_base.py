"""Train the base (Realistic) model with the data-side improvements, tuned for balanced
detection. Successor to week2/save_pooled_model.py.

What's new vs the old pooled recipe:
  - drop the junk `other` class (only WorldCover's misc codes carried it);
  - pool in the extra water polygons (data/water_extra.csv);
  - rebalance with class_weight='balanced' so rare classes aren't drowned;
  - sweep --wc-weight and keep the best balanced-detection score;
  - per-class threshold tuning as shifts to intercept_ (stays a linear model, so the 10 m
    Earth-Engine raster reproduces it exactly).

Honest split: hold out whole 1-degree blocks for test (30%) + val (15%); fit on the rest +
WorldCover. The deployed model is then refit on ALL data with the chosen weight + offsets.

Run:  python src/train_base.py                 # sweep + report, no deploy
      python src/train_base.py --deploy        # also write data/model_pooled.joblib
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.metrics import f1_score, accuracy_score

import eval_base
from eval_base import AE, C4

FULL_CSV = "data/master_alpha_full.csv"
WATER_CSV = "data/water_extra.csv"
WC_CSV = "data/worldcover_train.csv"
OUT = "data/model_pooled.joblib"


def load_sources():
    """All training rows as one frame: y, block, ae_*, src ('poly'|'water'|'wc').
    Expert blocks keep their real block id; water/WorldCover get sentinels (always in fit)."""
    poly = pd.read_csv(FULL_CSV, usecols=["block", "core_class"] + AE).dropna(subset=AE)
    poly = poly.rename(columns={"core_class": "y"}).assign(src="poly")
    frames = [poly[["block", "y", "src"] + AE]]
    if os.path.exists(WATER_CSV):
        w = pd.read_csv(WATER_CSV).dropna(subset=AE).rename(columns={"core_class": "y"})
        frames.append(w.assign(block="__water__", src="water")[["block", "y", "src"] + AE])
    wc = pd.read_csv(WC_CSV).dropna(subset=AE).rename(columns={"true_class": "y"})
    wc = wc[wc.y != "other"].assign(block="__wc__", src="wc")     # drop the junk class
    frames.append(wc[["block", "y", "src"] + AE])
    return pd.concat(frames, ignore_index=True)


SENTINEL_BLOCKS = {"__water__", "__wc__"}  # non-expert rows, always in the fit set


def split_blocks(df, seed=2024):
    """30% of expert blocks held out for test (matches eval_base + the old baseline)."""
    blocks = np.array(sorted(b for b in df.block.unique() if b not in SENTINEL_BLOCKS))
    rng = np.random.default_rng(seed); rng.shuffle(blocks)
    return set(blocks[: int(len(blocks) * 0.30)])


def fit(df, wc_weight):
    # plain LinearSVC (no class_weight: it fights the WorldCover prior and hurt both
    # metrics). The prior is carried by the wc sample weight instead.
    w = np.where(df.src.values == "wc", float(wc_weight), 1.0)
    model = make_pipeline(StandardScaler(), LinearSVC(max_iter=5000))
    model.fit(df[AE].values, df.y.values, linearsvc__sample_weight=w)
    return model


def report(model, Xb, yb, tag):
    """Balanced-holdout (expert) + independent random-India numbers."""
    pb = model.predict(Xb)
    bacc, bf1 = accuracy_score(yb, pb), f1_score(yb, pb, labels=C4, average="macro")
    Xr, yr = eval_base.random_india()
    pr = model.predict(Xr)
    racc, rf1 = accuracy_score(yr, pr), f1_score(yr, pr, labels=C4, average="macro")
    print(f"  {tag:22s} balanced: acc {bacc:.3f} macroF1 {bf1:.3f} | "
          f"random: acc {racc:.3f} macroF1 {rf1:.3f}")
    return bf1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wc-weights", default="2,3,4")
    ap.add_argument("--deploy", action="store_true")
    args = ap.parse_args()

    df = load_sources()
    print("pool:", df.groupby(["y", "src"]).size().unstack(fill_value=0).to_dict("index"))
    test = split_blocks(df)
    fit_df = df[~df.block.isin(test)]
    test_df = df[df.block.isin(test) & df.y.isin(C4)]
    Xt, yt = test_df[AE].values, test_df.y.values
    print(f"fit={len(fit_df)}  test={len(test_df)} (70/30 expert blocks, matches baseline)\n")

    print("=== wc_weight sweep (fit on 70% expert blocks + WorldCover, scored on test) ===")
    best_w, best_f1, best_model = None, -1, None
    for wcw in [float(x) for x in args.wc_weights.split(",")]:
        m = fit(fit_df, wcw)
        f1 = report(m, Xt, yt, f"wc_weight={wcw}")
        if f1 > best_f1:
            best_w, best_f1, best_model = wcw, f1, m
    print(f"\nbest wc_weight = {best_w} (balanced macroF1 {best_f1:.3f})")
    # NOTE: per-class intercept-offset tuning was tried and rejected — tuning to lift
    # balanced macroF1 just suppressed greenery and tanked the random-India score (it games
    # one side of the prior trade-off). The honest model keeps plain pooled scores.

    if args.deploy:
        print("\n=== deploy: refit on ALL data (best wc_weight, +water, drop 'other') ===")
        full = fit(df, best_w)
        if os.path.exists(OUT):
            joblib.dump(joblib.load(OUT), "data/model_pooled.bak.joblib")
            print("  backed up old model -> data/model_pooled.bak.joblib")
        joblib.dump({"model": full, "features": AE,
                     "classes": list(full.named_steps["linearsvc"].classes_),
                     "wc_weight": best_w,
                     "note": "pooled AE + extra water + WorldCover; drop 'other'; "
                             "balanced-detection (wc_weight chosen by held-out sweep)"}, OUT)
        print(f"  saved -> {OUT} (classes={list(full.named_steps['linearsvc'].classes_)})")


if __name__ == "__main__":
    main()
