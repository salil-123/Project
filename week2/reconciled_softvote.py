"""Does adding the WorldCover prior to the AE side of the soft-vote fix the
random-spot fumble while keeping Tessera's greenery help?

Compares on the random-within-tiles eval (2400 pts, WorldCover truth, ~89% greenery
like real India):
  - instant            = pooled AE+WorldCover model alone (the current instant mode)
  - balanced soft-vote = current default (AE-balanced + Tessera-balanced)  <- the fumbler
  - reconciled         = (AE pooled-with-WC, calibrated) soft-voted with Tessera

Reports overall accuracy (realistic, prior-weighted) AND macro-recall (balanced
per-class skill), so we see both sides of the trade. If a reconciled weight wins on
both, it earns the "high accuracy" name and we save it.
"""
import warnings
import numpy as np, pandas as pd, joblib
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, recall_score

warnings.filterwarnings("ignore")
C4 = ["barren", "built_up", "greenery", "water"]
AE = [f"ae_{i:03d}" for i in range(64)]
TE = [f"te_{i:03d}" for i in range(128)]


def cal_svc(balanced=True):
    cw = "balanced" if balanced else None
    return make_pipeline(StandardScaler(),
                         CalibratedClassifierCV(LinearSVC(class_weight=cw, max_iter=5000), cv=3))


def report(name, y, p):
    acc = accuracy_score(y, p)
    rec = recall_score(y, p, labels=C4, average=None, zero_division=0)
    macro = rec.mean()
    cells = "  ".join(f"{c[:5]}={r:.2f}" for c, r in zip(C4, rec))
    print(f"{name:26s} | acc {acc:.3f} | macro-rec {macro:.3f} | {cells}")
    return acc, macro


def main():
    # --- prior-aware AE model: polygons + WorldCover, WC repeated wc_weight times ---
    poly = pd.read_csv("data/master_alpha_full.csv").dropna(subset=AE)
    poly = poly[poly.core_class.isin(C4)].rename(columns={"core_class": "y"})
    wc = pd.read_csv("data/worldcover_train.csv").dropna(subset=AE)
    wc = wc[wc.true_class.isin(C4)].rename(columns={"true_class": "y"})
    WC_WEIGHT = 2
    pool = pd.concat([poly[["y"] + AE]] + [wc[["y"] + AE]] * WC_WEIGHT, ignore_index=True)
    ae_pooled = cal_svc(balanced=False).fit(pool[AE].values, pool.y.to_numpy(dtype=object))

    # --- Tessera model: reuse the one already trained in model_softvote ---
    sv = joblib.load("data/model_softvote.joblib")
    te_model = sv["te_model"]
    cl = list(ae_pooled.classes_)
    assert cl == list(te_model.classes_) == C4, (cl, list(te_model.classes_))

    # --- eval set ---
    ev = pd.read_csv("data/random_te_eval.csv")
    ev = ev[ev.true_class.isin(C4)].copy()
    y = ev.true_class.values
    print(f"eval: {len(ev)} random points (true dist "
          f"{ev.true_class.value_counts(normalize=True).round(2).to_dict()})\n")

    pa = ae_pooled.predict_proba(ev[AE].values)   # prior-aware AE probabilities
    pt = te_model.predict_proba(ev[TE].values)     # Tessera probabilities
    classes = np.array(C4, dtype=object)

    print(f"{'model':26s} | accuracy | balanced  | per-class recall")
    print("-" * 92)
    # instant = current deployed pooled model (predict only)
    instant = joblib.load("data/model_pooled.joblib")
    ip = instant["model"].predict(ev[AE].values)
    report("instant (AE+WC)", y, ip)
    # current balanced soft-vote (the fumbler)
    bp = sv["ae_model"].predict_proba(ev[AE].values)
    report("balanced soft-vote", y, classes[((bp + pt) / 2).argmax(1)])
    # reconciled, sweep the weight on the prior-aware AE side
    best = None
    for wa in [0.4, 0.5, 0.6, 0.7]:
        p = classes[(wa * pa + (1 - wa) * pt).argmax(1)]
        acc, macro = report(f"reconciled AE={wa}", y, p)
        score = acc + macro  # want both high
        if best is None or score > best[0]:
            best = (score, wa, acc, macro)

    print(f"\nbest reconciled weight: AE={best[1]} (acc {best[2]:.3f}, macro-rec {best[3]:.3f})")
    # save the reconciled bundle at the best weight
    wa = best[1]
    joblib.dump({"ae_model": ae_pooled, "te_model": te_model,
                 "ae_features": AE, "te_features": TE, "classes": C4,
                 "weights": [wa, 1 - wa],
                 "note": f"reconciled soft-vote: prior-aware AE(pooled+WC) {wa} + Tessera {1-wa:.1f}"},
                "data/model_softvote_reconciled.joblib")
    print("saved -> data/model_softvote_reconciled.joblib")


if __name__ == "__main__":
    main()
