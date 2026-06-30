"""Best-with-what-we-have: can we keep AE's built_up strength AND Tessera's
greenery strength at the same time, using only the two embeddings we already have?

Compares, on region-held-out splits (several seeds):
  - AE only, TE only, concat(AE+TE)            -- the baselines we already saw
  - SOFT-VOTE: average the probabilities of an AE model and a TE model
  - TWO-STAGE: AE decides built_up/barren vs "green-or-wet", then a TE model
    resolves greenery vs water inside the green-or-wet group (TE's strong suit)

Reports macro-F1 + the cells we care about: greenery recall, greenery->water leak,
built_up recall.
"""
import argparse, warnings
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, recall_score, confusion_matrix

warnings.filterwarnings("ignore")
CLASSES = ["barren", "built_up", "greenery", "water"]


def lr():
    return make_pipeline(StandardScaler(),
                         LogisticRegression(max_iter=3000, class_weight="balanced"))


def green_to_water(y, p):
    cm = confusion_matrix(y, p, labels=CLASSES, normalize="true")
    gi, wi = CLASSES.index("greenery"), CLASSES.index("water")
    return cm[gi, wi]


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

    methods = ["AE only", "TE only", "concat AE+TE", "soft-vote AE+TE", "two-stage AE>TE"]
    agg = {m: {"f1": [], "g_rec": [], "g2w": [], "bu_rec": []} for m in methods}

    for s in range(args.seeds):
        rng = np.random.default_rng(s)
        bl = blocks.copy(); rng.shuffle(bl)
        test_b = set(bl[: max(1, int(len(bl) * 0.30))])
        tr, te = df[~df.block.isin(test_b)], df[df.block.isin(test_b)]
        ytr, yte = tr.core_class.values, te.core_class.values

        preds = {}
        # plain single-feature models
        for name, cols in [("AE only", AE), ("TE only", TE), ("concat AE+TE", AE + TE)]:
            m = lr().fit(tr[cols].values, ytr)
            preds[name] = m.predict(te[cols].values)

        # soft-vote: average class probabilities of an AE model and a TE model
        mae = lr().fit(tr[AE].values, ytr)
        mte = lr().fit(tr[TE].values, ytr)
        classes_ = mae.classes_
        proba = (mae.predict_proba(te[AE].values) + mte.predict_proba(te[TE].values)) / 2
        preds["soft-vote AE+TE"] = classes_[proba.argmax(1)]

        # two-stage: stage1 on AE collapses greenery+water into one "wet_green" bucket
        # (AE nails built_up/barren); stage2 (TE) splits greenery vs water there
        s1_tr = np.where(np.isin(ytr, ["greenery", "water"]), "wet_green", ytr)
        s1 = lr().fit(tr[AE].values, s1_tr)
        gw_tr = tr[np.isin(ytr, ["greenery", "water"])]
        s2 = lr().fit(gw_tr[TE].values, gw_tr.core_class.values)
        p1 = s1.predict(te[AE].values)
        out = p1.copy().astype(object)
        wg = p1 == "wet_green"
        if wg.any():
            out[wg] = s2.predict(te[wg][TE].values)
        preds["two-stage AE>TE"] = out

        for m in methods:
            p = preds[m]
            agg[m]["f1"].append(f1_score(yte, p, average="macro"))
            agg[m]["g_rec"].append(recall_score(yte, p, labels=["greenery"], average="macro"))
            agg[m]["g2w"].append(green_to_water(yte, p))
            agg[m]["bu_rec"].append(recall_score(yte, p, labels=["built_up"], average="macro"))

    print(f"{'method':18s} | macroF1 | green-rec | green->water | built_up-rec")
    print("-" * 70)
    for m in methods:
        a = agg[m]
        print(f"{m:18s} |  {np.mean(a['f1']):.3f}  |   {np.mean(a['g_rec']):.3f}   "
              f"|    {np.mean(a['g2w']):.3f}     |    {np.mean(a['bu_rec']):.3f}")


if __name__ == "__main__":
    main()
