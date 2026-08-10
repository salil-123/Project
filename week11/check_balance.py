"""A tiny, EE-free check that the retrain 'Class balance' options actually re-balance the data.

The retrain panel offers three balance modes (refine.train's `balance=`):
  - balanced      : keep the raw counts, let the classifier weight classes inversely (class_weight).
  - undersample   : drop the majority class down to the minority count.
  - oversample    : draw the minority class up (with replacement) to the majority count.

This just feeds a deliberately skewed toy set (200 of one class, 20 of the other) through the exact
function the app uses (`refine._rebalance`) and prints the class counts after each mode, so you can
see undersample shrink the majority and oversample grow the minority. No Earth Engine, no training.

Run:  python week11/check_balance.py
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import refine  # noqa: E402

# a skewed toy split: 200 barren_other vs 20 mining, random 64-d features (values don't matter here)
y = np.array(["barren_other"] * 200 + ["mining"] * 20)
X = np.random.default_rng(0).random((len(y), 64))

def counts(a):
    return {str(k): int(v) for k, v in Counter(a).items()}

print(f"raw counts: {counts(y)}\n")
for how in ["balanced", "undersample", "oversample"]:
    Xb, yb = refine._rebalance(X, y, how)
    print(f"{how:12s} -> {counts(yb)}  (rows: {len(yb)})")

print("\nExpected: balanced keeps 200/20 (the classifier weights it at fit time); "
      "undersample -> 20/20; oversample -> 200/200.")
