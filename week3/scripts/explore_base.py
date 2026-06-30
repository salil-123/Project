"""Quick honest exploration: does a heavier model or a different data mix beat the current
linear base on BOTH random-India and the balanced expert hold-out? Honest 70/30 block split
(no optimism). Run from repo root."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (week3/scripts -> root)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import numpy as np, pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, f1_score
import eval_base
AE, C4 = eval_base.AE, eval_base.C4

poly = pd.read_csv("data/master_alpha_full.csv", usecols=["block", "core_class"] + AE).dropna(subset=AE).rename(columns={"core_class": "y"})
wc = pd.read_csv("data/worldcover_train.csv").dropna(subset=AE).rename(columns={"true_class": "y"})
wc = wc[wc.y != "other"]
water = pd.read_csv("data/water_extra.csv").dropna(subset=AE).rename(columns={"core_class": "y"})

b = np.array(sorted(poly.block.unique())); np.random.default_rng(2024).shuffle(b)
test = set(b[: int(len(b) * 0.30)])
ptr = poly[~poly.block.isin(test)]
pte = poly[poly.block.isin(test) & poly.y.isin(C4)]
Xte, yte = pte[AE].values, pte.y.values
Xr, yr = eval_base.random_india()


def run(make_model, wcw, use_water, tag):
    parts = [ptr[["y"] + AE].assign(w=1.0)]
    if use_water:
        parts.append(water[["y"] + AE].assign(w=1.0))
    parts.append(wc[["y"] + AE].assign(w=float(wcw)))
    d = pd.concat(parts, ignore_index=True)
    model = make_model()
    step = type(model).__name__.lower()
    pipe = make_pipeline(StandardScaler(), model)
    pipe.fit(d[AE].values, d.y.values, **{f"{step}__sample_weight": d.w.values})
    pb, pr = pipe.predict(Xte), pipe.predict(Xr)
    bf = f1_score(yte, pb, labels=C4, average="macro"); ba = accuracy_score(yte, pb)
    rf = f1_score(yr, pr, labels=C4, average="macro"); ra = accuracy_score(yr, pr)
    print(f"  {tag:38s} balanced {ba:.3f}/{bf:.3f}   random {ra:.3f}/{rf:.3f}")


print("config (acc/macroF1)                      balanced            random")
run(lambda: LinearSVC(max_iter=5000), 2, True,  "LinearSVC  wc2  +water  (deployed)")
run(lambda: LinearSVC(max_iter=5000), 2, False, "LinearSVC  wc2  no-water")
run(lambda: LinearSVC(max_iter=5000), 3, False, "LinearSVC  wc3  no-water")
run(lambda: LogisticRegression(max_iter=2000), 2, True, "LogReg     wc2  +water")
run(lambda: HistGradientBoostingClassifier(), 2, True,  "HistGB     wc2  +water")
run(lambda: HistGradientBoostingClassifier(), 2, False, "HistGB     wc2  no-water")
run(lambda: HistGradientBoostingClassifier(), 3, False, "HistGB     wc3  no-water")
