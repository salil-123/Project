"""Train + save the high-accuracy SOFT-VOTE model (AE + Tessera).

Two calibrated LinearSVC models, one on Alpha Earth, one on Tessera; at predict
time we average their class probabilities. This is the best we can do with the two
embeddings we have: acc ~0.85 / macro-F1 ~0.81 on region-held-out CV, keeping AE's
built_up strength AND Tessera's greenery fix. Needs Tessera at inference, so it's
the tool's "high-accuracy" mode (per-area tile download); instant mode stays AE-only.
"""
import warnings
import numpy as np, pandas as pd, joblib
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score, f1_score

warnings.filterwarnings("ignore")
CLASSES = ["barren", "built_up", "greenery", "water"]


def cal_svc():
    return make_pipeline(StandardScaler(),
                         CalibratedClassifierCV(LinearSVC(class_weight="balanced", max_iter=5000), cv=3))


def main():
    df = pd.read_csv("data/master_tessera.csv")
    df = df[df.core_class.isin(CLASSES)].copy()
    AE = [c for c in df.columns if c.startswith("ae_")]
    TE = [c for c in df.columns if c.startswith("te_")]
    y = df.core_class.to_numpy(dtype=object)

    # quick polygon-split sanity check before training the final on everything
    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    tr_i, te_i = next(gss.split(df, y, df.polygon_id))
    a = cal_svc().fit(df[AE].values[tr_i], y[tr_i])
    t = cal_svc().fit(df[TE].values[tr_i], y[tr_i])
    proba = (a.predict_proba(df[AE].values[te_i]) + t.predict_proba(df[TE].values[te_i])) / 2
    p = a.classes_[proba.argmax(1)]
    print(f"sanity (polygon holdout): acc={accuracy_score(y[te_i], p):.3f} "
          f"macroF1={f1_score(y[te_i], p, average='macro'):.3f}")

    # final models on ALL the data
    ae_model = cal_svc().fit(df[AE].values, y)
    te_model = cal_svc().fit(df[TE].values, y)
    joblib.dump({"ae_model": ae_model, "te_model": te_model,
                 "ae_features": AE, "te_features": TE,
                 "classes": list(ae_model.classes_), "weights": [0.5, 0.5],
                 "note": "soft-vote of calibrated LinearSVC (AE) + (TE); high-accuracy mode, needs Tessera"},
                "data/model_softvote.joblib")
    print("saved -> data/model_softvote.joblib")


if __name__ == "__main__":
    main()