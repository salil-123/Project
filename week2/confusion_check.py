"""Where do the errors actually live, and does Tessera fix them?

Region-held-out (disjoint 1-deg blocks), averaged over a few seeds for stability.
Prints a row-normalized confusion matrix per feature set so we can see the exact
greenery<->barren (and water<->greenery) leakage, and whether Tessera moves it.
"""
import argparse, warnings
import numpy as np, pandas as pd
from sklearn.svm import LinearSVC
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix, f1_score

warnings.filterwarnings("ignore")
CLASSES = ["barren", "built_up", "greenery", "water"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()

    df = pd.read_csv("data/master_tessera.csv")
    df = df[df.core_class.isin(CLASSES)].copy()
    df["block"] = (np.floor(df.lon).astype(int).astype(str) + "_" +
                   np.floor(df.lat).astype(int).astype(str))
    AE = [c for c in df.columns if c.startswith("ae_")]
    TE = [c for c in df.columns if c.startswith("te_")]
    sets = {"Alpha Earth": AE, "Tessera": TE, "AE + Tessera": AE + TE}
    blocks = df.block.unique()

    for name, cols in sets.items():
        cms, f1s = [], []
        for s in range(args.seeds):
            rng = np.random.default_rng(s)
            bl = blocks.copy(); rng.shuffle(bl)
            test_b = set(bl[: max(1, int(len(bl) * 0.30))])
            tr, te = df[~df.block.isin(test_b)], df[df.block.isin(test_b)]
            m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000))
            m.fit(tr[cols].values, tr.core_class.values)
            p = m.predict(te[cols].values)
            cm = confusion_matrix(te.core_class.values, p, labels=CLASSES, normalize="true")
            cms.append(cm)
            f1s.append(f1_score(te.core_class.values, p, average="macro"))
        cm = np.mean(cms, axis=0)
        print(f"\n=== {name}  (macro-F1 {np.mean(f1s):.3f}) ===")
        print("rows=true, cols=pred (fraction of each true class)")
        print(f"{'':10s} " + " ".join(f"{c:>9s}" for c in CLASSES))
        for i, c in enumerate(CLASSES):
            print(f"{c:10s} " + " ".join(f"{cm[i,j]:9.2f}" for j in range(len(CLASSES))))


if __name__ == "__main__":
    main()
