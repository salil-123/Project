"""Push the AE+Tessera fusion as high as it'll go with only what we have.

Tries, on region-held-out splits (several seeds), reporting BOTH overall accuracy
and macro-F1:
  - soft-vote LogReg, 50/50                 (the baseline fusion)
  - soft-vote LogReg, swept AE:TE weights   (maybe TE deserves more say)
  - soft-vote calibrated-LinearSVC          (LinearSVC was our best single model)
  - stacking: meta LogReg on the two models' stacked probabilities
"""
import argparse, warnings
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, accuracy_score

warnings.filterwarnings("ignore")
CLASSES = ["barren", "built_up", "greenery", "water"]


def lr():
    return make_pipeline(StandardScaler(),
                         LogisticRegression(max_iter=3000, class_weight="balanced"))


def cal_svc():
    # LinearSVC has no proba; calibrate it so we can soft-vote
    return make_pipeline(StandardScaler(),
                         CalibratedClassifierCV(LinearSVC(class_weight="balanced", max_iter=5000), cv=3))


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
    blocks = df.block.unique()

    results = {}  # name -> list of (acc, f1)

    def record(name, y, p):
        results.setdefault(name, []).append((accuracy_score(y, p), f1_score(y, p, average="macro")))

    for s in range(args.seeds):
        rng = np.random.default_rng(s)
        bl = blocks.copy(); rng.shuffle(bl)
        test_b = set(bl[: max(1, int(len(bl) * 0.30))])
        tr, te = df[~df.block.isin(test_b)], df[df.block.isin(test_b)]
        # pandas 3.0 gives arrow-backed strings; coerce so CalibratedClassifierCV's
        # internal CV can index the labels
        ytr = tr.core_class.to_numpy(dtype=object)
        yte = te.core_class.to_numpy(dtype=object)

        # --- LogReg bases ---
        mae, mte = lr().fit(tr[AE].values, ytr), lr().fit(tr[TE].values, ytr)
        cl = mae.classes_
        pae, pte = mae.predict_proba(te[AE].values), mte.predict_proba(te[TE].values)
        for wte in [0.4, 0.5, 0.6, 0.7]:
            p = cl[((1 - wte) * pae + wte * pte).argmax(1)]
            record(f"softvote LogReg te={wte}", yte, p)

        # --- stacking: meta-LogReg on stacked probabilities (train via CV-free holdout) ---
        # split train again so the meta-model sees out-of-fold base preds
        rng2 = np.random.default_rng(100 + s)
        bb = tr.block.unique(); rng2.shuffle(bb)
        inner = set(bb[: max(1, int(len(bb) * 0.30))])
        f1_tr, f2_tr = tr[~tr.block.isin(inner)], tr[tr.block.isin(inner)]
        b_ae = lr().fit(f1_tr[AE].values, f1_tr.core_class.values)
        b_te = lr().fit(f1_tr[TE].values, f1_tr.core_class.values)
        meta_X = np.hstack([b_ae.predict_proba(f2_tr[AE].values), b_te.predict_proba(f2_tr[TE].values)])
        meta = LogisticRegression(max_iter=3000, class_weight="balanced").fit(meta_X, f2_tr.core_class.values)
        test_X = np.hstack([mae.predict_proba(te[AE].values), mte.predict_proba(te[TE].values)])
        record("stacking LogReg-meta", yte, meta.predict(test_X))

        # --- calibrated LinearSVC soft-vote 50/50 ---
        cae, cte = cal_svc().fit(tr[AE].values, ytr), cal_svc().fit(tr[TE].values, ytr)
        cc = cae.classes_
        p = cc[((cae.predict_proba(te[AE].values) + cte.predict_proba(te[TE].values)) / 2).argmax(1)]
        record("softvote calSVC 50/50", yte, p)

    print(f"{'method':28s} | accuracy | macro-F1")
    print("-" * 52)
    for name, vals in results.items():
        acc = np.mean([v[0] for v in vals]); f1 = np.mean([v[1] for v in vals])
        flag = "  <-- >=0.80 F1" if f1 >= 0.80 else ""
        print(f"{name:28s} |  {acc:.3f}  |  {f1:.3f}{flag}")


if __name__ == "__main__":
    main()