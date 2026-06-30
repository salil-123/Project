"""Train + save the unified POOLED model (one LinearSVC on polygon + WorldCover data).

WorldCover here is SCAFFOLDING for the greenery-diversity gap in the current polygon
set; --wc-weight is the transition dial: keep it high now, lower it as users
contribute diverse polygons until the polygon data can stand alone.

  python save_pooled_model.py                 # raw pool (wc-weight 1.0)
  python save_pooled_model.py --wc-weight 5   # lean harder on WorldCover prior
"""
import argparse, warnings
import numpy as np, pandas as pd, joblib
from sklearn.svm import LinearSVC
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score

warnings.filterwarnings("ignore")
FEATS = [f"ae_{i:03d}" for i in range(64)]
C4 = ["barren", "built_up", "greenery", "water"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wc-weight", type=float, default=1.0,
                    help="per-sample weight on WorldCover rows (1.0 = raw pool)")
    args = ap.parse_args()

    poly = pd.read_csv("data/master_alpha_full.csv").dropna(subset=FEATS).rename(columns={"core_class": "y"})
    wc = pd.read_csv("data/worldcover_train.csv").dropna(subset=FEATS).rename(columns={"true_class": "y"})

    # held-out test views (same splits as the experiments) for a sanity check
    rng = np.random.default_rng(2024); b = poly.block.unique(); rng.shuffle(b)
    test_b = set(b[: int(len(b) * 0.30)])
    poly_tr, poly_te = poly[~poly.block.isin(test_b)], poly[poly.block.isin(test_b)]
    wc_te = pd.read_csv("data/random_eval.csv").dropna(subset=FEATS).rename(columns={"true_class": "y"})

    pool = pd.concat([poly_tr[["y"] + FEATS], wc[["y"] + FEATS]], ignore_index=True)
    w = np.concatenate([np.ones(len(poly_tr)), np.full(len(wc), args.wc_weight)])

    model = make_pipeline(StandardScaler(), LinearSVC(max_iter=5000))
    model.fit(pool[FEATS].values, pool.y.values, linearsvc__sample_weight=w)

    # sanity eval on both
    for name, te in [("random India (WorldCover truth)", wc_te), ("polygon holdout (expert truth)", poly_te)]:
        sub = te[te.y.isin(C4)]
        pred = model.predict(sub[FEATS].values)
        print(f"  {name}: acc={accuracy_score(sub.y, pred):.1%} "
              f"macroF1(4)={f1_score(sub.y, pred, labels=C4, average='macro'):.2f}")

    joblib.dump({"model": model, "features": FEATS,
                 "classes": sorted(pool.y.unique()),
                 "wc_weight": args.wc_weight,
                 "note": "pooled polygon+WorldCover; WC is scaffolding, lower wc_weight as user polygons grow"},
                "data/model_pooled.joblib")
    print(f"\nsaved -> data/model_pooled.joblib (wc_weight={args.wc_weight})")


if __name__ == "__main__":
    main()