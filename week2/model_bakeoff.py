"""Why LinearSVC? Compare classifiers on the SAME region-held-out splits (Alpha
Earth features), averaged over a few seeds. Reports accuracy + macro-F1.

Good embeddings tend to be linearly separable, so simple linear models often
generalize better out-of-region than trees, which overfit regional quirks. This
script is the evidence for picking LinearSVC as the base model in both modes.

  python model_bakeoff.py --seeds 5
"""
import argparse, warnings
import numpy as np, pandas as pd
from sklearn.svm import LinearSVC
from sklearn.linear_model import LogisticRegression
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score

warnings.filterwarnings("ignore")
C4 = ["barren", "built_up", "greenery", "water"]


def models():
    sc = lambda m: make_pipeline(StandardScaler(), m)
    return {
        "LinearSVC":            sc(LinearSVC(class_weight="balanced", max_iter=5000)),
        "LogReg":               sc(LogisticRegression(max_iter=3000, class_weight="balanced")),
        "LDA":                  sc(LinearDiscriminantAnalysis()),
        "kNN (k=15)":           sc(KNeighborsClassifier(n_neighbors=15)),
        "RandomForest":         RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=0),
        "HistGradientBoosting": HistGradientBoostingClassifier(max_iter=300, random_state=0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()

    df = pd.read_csv("data/master_alpha_full.csv")
    df = df[df.core_class.isin(C4)].copy()
    AE = [c for c in df.columns if c.startswith("ae_")]
    blocks = df.block.unique()
    print(f"{len(df)} px, {len(blocks)} blocks, Alpha Earth features, {args.seeds} seeds\n")

    agg = {name: {"acc": [], "f1": []} for name in models()}
    for s in range(args.seeds):
        rng = np.random.default_rng(s)
        bl = blocks.copy(); rng.shuffle(bl)
        test_b = set(bl[: max(1, int(len(bl) * 0.30))])
        tr, te = df[~df.block.isin(test_b)], df[df.block.isin(test_b)]
        ytr = tr.core_class.to_numpy(dtype=object); yte = te.core_class.to_numpy(dtype=object)
        for name, m in models().items():
            m.fit(tr[AE].values, ytr); p = m.predict(te[AE].values)
            agg[name]["acc"].append(accuracy_score(yte, p))
            agg[name]["f1"].append(f1_score(yte, p, average="macro"))

    print(f"{'classifier':22s} | accuracy | macro-F1 | kind")
    print("-" * 56)
    kinds = {"LinearSVC": "linear", "LogReg": "linear", "LDA": "linear",
             "kNN (k=15)": "instance", "RandomForest": "tree", "HistGradientBoosting": "tree"}
    rows = sorted(agg.items(), key=lambda kv: -np.mean(kv[1]["f1"]))
    for name, v in rows:
        print(f"{name:22s} |  {np.mean(v['acc']):.3f}  |  {np.mean(v['f1']):.3f}   | {kinds[name]}")


if __name__ == "__main__":
    main()