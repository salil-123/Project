"""Evaluate a base (Realistic) model on the two views that matter, so every data tweak is
measured the same way:

  - random India  : data/random_te_eval.csv (WorldCover truth, ~89% greenery prior) ->
                    how it behaves on real locations / when browsing.
  - balanced holdout: whole 1-degree blocks held out of master_alpha_full (expert truth,
                    classes ~even) -> how well it finds the rare classes.

Reports accuracy, macro-F1 over the 4 real classes, and per-class precision/recall.

Run from repo root:  python src/eval_base.py [path/to/model.joblib]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support

AE = [f"ae_{i:03d}" for i in range(64)]
C4 = ["barren", "built_up", "greenery", "water"]   # the real classes we score on
FULL_CSV = "data/master_alpha_full.csv"
RANDOM_CSV = "data/random_te_eval.csv"


def random_india():
    df = pd.read_csv(RANDOM_CSV).dropna(subset=AE)
    df = df[df.true_class.isin(C4)]
    return df[AE].values, df.true_class.values


def balanced_holdout(seed=2024, frac=0.30):
    """Expert pixels from 1-degree blocks held out of training (no spatial leakage)."""
    poly = pd.read_csv(FULL_CSV, usecols=["block", "core_class"] + AE).dropna(subset=AE)
    blocks = np.array(sorted(poly.block.unique()))
    rng = np.random.default_rng(seed); rng.shuffle(blocks)
    test = set(blocks[: int(len(blocks) * frac)])
    ho = poly[poly.block.isin(test) & poly.core_class.isin(C4)]
    return ho[AE].values, ho.core_class.values


def score(name, model, X, y):
    pred = model.predict(X)
    acc = accuracy_score(y, pred)
    f1 = f1_score(y, pred, labels=C4, average="macro")
    p, r, _, _ = precision_recall_fscore_support(y, pred, labels=C4, zero_division=0)
    print(f"\n  {name}: acc={acc:.3f}  macroF1(4)={f1:.3f}")
    for c, pc, rc in zip(C4, p, r):
        print(f"     {c:9s} P={pc:.2f} R={rc:.2f}")
    return acc, f1


def evaluate(model_path="data/model_pooled.joblib"):
    model = joblib.load(model_path)["model"]
    print(f"=== {model_path} ===")
    Xr, yr = random_india()
    Xb, yb = balanced_holdout()
    r = score(f"random India  (n={len(yr)})", model, Xr, yr)
    b = score(f"balanced holdout (n={len(yb)})", model, Xb, yb)
    return {"random": r, "balanced": b}


if __name__ == "__main__":
    evaluate(sys.argv[1] if len(sys.argv) > 1 else "data/model_pooled.joblib")
