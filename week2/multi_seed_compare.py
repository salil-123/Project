"""Stable region-held-out comparison: average over many random block-holdouts so
we judge on the trend, not one lucky split.

For each seed we hold out 30% of the 1-deg blocks (disjoint regions), train on the
rest, and score acc / macro-F1 / water-recall / greenery-precision. We sweep feature
sets (AE, Tessera, both) and two linear models, then report mean +/- std.

    python multi_seed_compare.py --seeds 8
"""
import argparse
import warnings
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score, recall_score, precision_score

warnings.filterwarnings("ignore")


def make_model(kind):
    if kind == "LogReg":
        return make_pipeline(StandardScaler(),
                             LogisticRegression(max_iter=2000, class_weight="balanced"))
    return make_pipeline(StandardScaler(),
                         LinearSVC(class_weight="balanced", max_iter=5000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--holdout", type=float, default=0.30)
    args = ap.parse_args()

    df = pd.read_csv("data/master_tessera.csv")
    df = df[df.core_class != "non_water"].copy()
    df["block"] = (np.floor(df.lon).astype(int).astype(str) + "_" +
                   np.floor(df.lat).astype(int).astype(str))
    AE = [c for c in df.columns if c.startswith("ae_")]
    TE = [c for c in df.columns if c.startswith("te_")]
    sets = {"Alpha Earth (64)": AE, "Tessera (128)": TE, "AE + Tessera (192)": AE + TE}
    blocks = df.block.unique()
    print(f"{len(df)} px | {len(blocks)} blocks | {args.seeds} seeds, "
          f"hold out {args.holdout:.0%} blocks each\n")

    # collect per-(model, featureset) lists of metric tuples across seeds
    rows = []
    for kind in ["LogReg", "LinearSVC"]:
        for name, cols in sets.items():
            scores = []  # acc, mF1, water-rec, green-prec
            for s in range(args.seeds):
                rng = np.random.default_rng(s)
                bl = blocks.copy(); rng.shuffle(bl)
                test_b = set(bl[: max(1, int(len(bl) * args.holdout))])
                tr = df[~df.block.isin(test_b)]; te = df[df.block.isin(test_b)]
                m = make_model(kind)
                m.fit(tr[cols].values, tr.core_class.values)
                p = m.predict(te[cols].values)
                y = te.core_class.values
                scores.append([
                    accuracy_score(y, p),
                    f1_score(y, p, average="macro"),
                    recall_score(y, p, labels=["water"], average="macro"),
                    precision_score(y, p, labels=["greenery"], average="macro", zero_division=0),
                ])
            arr = np.array(scores)
            rows.append((kind, name, arr.mean(0), arr.std(0)))

    hdr = ["acc", "macroF1", "water-rec", "green-prec"]
    print(f"{'model':10s} {'feature set':20s} | " + " | ".join(f"{h:^15s}" for h in hdr))
    print("-" * 90)
    for kind, name, mean, std in rows:
        cells = " | ".join(f"{m:.3f} +/-{s:.3f}" for m, s in zip(mean, std))
        print(f"{kind:10s} {name:20s} | {cells}")


if __name__ == "__main__":
    main()