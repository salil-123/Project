"""Week-7 site tests with numbers for the slides.

Runs the classification tests sir asked for (leaving the Jalpaiguri operations demo aside):
  - tea vs non-tea: held-out accuracy.
  - mining detector: held-out accuracy, recall on real mines (the positive control), and the
    false-positive rate (non-mining polygons wrongly called mining, ground-truthed).
  - Asola Bhatti: the mining false-positive probe sir named. Its old mines were reclaimed into
    built-up and scrub, so we classify the area and report what fraction gets flagged as mining.
    A low number means few false positives there.

Run from the repo root, needs live Earth Engine:
    python week7/site_tests.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score

import examples
import infer
import temporal_eval as te

AE_COLS = [f"ae_{i:03d}" for i in range(64)]
YEAR = 2024
NPIX = 20
# spatial probes for the mining detector: a reclaimed site (should stay quiet -> false positives)
# and a known active coalfield (should light up -> the positive control they can be compared to).
SITES = {
    "Asola Bhatti (reclaimed)": [77.19, 28.42, 77.27, 28.48],
    "Jharia coalfield (active)": [86.23, 23.62, 86.41, 23.80],
}


def _holdout(df, test_size=0.25, seed=0):
    """Fit on held-out-polygon train rows, return (model_refit_on_all, y_true, y_pred) on the test."""
    X, y, g = df[AE_COLS].values, df.label.values, df.poly.values
    tr, tev = next(GroupShuffleSplit(1, test_size=test_size, random_state=seed).split(X, y, g))
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced")).fit(X[tr], y[tr])
    pred = m.predict(X[tev])
    m_all = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced")).fit(X, y)
    return m_all, y[tev], pred


def _examples_frame(nodes):
    return pd.concat([examples.build_training_frame(c, n_pix=NPIX, year=YEAR) for c in nodes],
                     ignore_index=True)


def tea_test():
    df = _examples_frame(["tea", "non_tea"])
    _, yt, pt = _holdout(df)
    print(f"\n[tea vs non-tea]  held-out accuracy: {accuracy_score(yt, pt):.3f}  ({len(yt)} px)")


def mining_test():
    # positives: real mines from across India; negatives: barren/built-up/greenery (not mining)
    pos = _examples_frame(["mining"]); pos["label"] = "mining"
    neg = te._frame_from_file("data/selected_polygons.geojson", "core_class",
                              ["barren", "built_up", "greenery"], YEAR, NPIX)
    neg["label"] = "not_mining"
    df = pd.concat([pos[["label", "poly"] + AE_COLS], neg[["label", "poly"] + AE_COLS]],
                   ignore_index=True)
    m_all, y, p = _holdout(df)

    tp = int(((y == "mining") & (p == "mining")).sum())
    fn = int(((y == "mining") & (p == "not_mining")).sum())
    fp = int(((y == "not_mining") & (p == "mining")).sum())
    tn = int(((y == "not_mining") & (p == "not_mining")).sum())
    print(f"\n[mining detector]  held-out accuracy: {accuracy_score(y, p):.3f}")
    print(f"  recall on real mines (held-out): {tp / (tp + fn):.3f}")
    print(f"  false-positive rate (non-mining called mining): {fp / (fp + tn):.3f}")

    # spatial probes: fraction of each area flagged mining, same detector -> directly comparable.
    # A reclaimed site should read low (false positives only); an active mine should read high.
    print("  spatial probe (% of area flagged mining):")
    for name, bbox in SITES.items():
        pts = infer._grid(bbox, 25)
        X = infer._sample_alpha(pts, bbox, YEAR)
        ok = ~np.isnan(X).any(axis=1)
        pct = 100 * (m_all.predict(X[ok]) == "mining").mean() if ok.any() else float("nan")
        print(f"    {name}: {pct:.1f}%  ({ok.sum()} cells)")


if __name__ == "__main__":
    print("week-7 site tests (live GEE)")
    tea_test()
    mining_test()
