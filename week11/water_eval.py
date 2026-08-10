"""#10 wk11 — validate the deployed water model on small vs large water bodies + spurious water.

Context correction: the water model is NOT Sentinel-1-only. It uses **Sentinel-1 + Sentinel-2**
(`sentinel.FEATURE_BANDS` = VV, VH, VV_VH_ratio, NDWI, MNDWI, BSI, B3, B8, B11), so the S1-only
road/water confusion sir worried about is already mitigated by the optical indices.

What sir still wants: how well does it do on **small vs large** water bodies (small/seasonal bodies
are the hard case), and does it flag **spurious** water on dry land? This reuses the week10 robustness
harness (`build_frame`/`fit`) and the augmentation sampler, scoring the *deployed* model per size
bucket, plus a dryland false-positive probe.

Run (needs EE):
  python week11/water_eval.py --max-dates 80 --n-pix 8
  python week11/water_eval.py --max-dates 80 --write-card      # also write onto the water card
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import geopandas as gpd
import joblib
from sklearn.metrics import precision_recall_fscore_support, accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "week10"))
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel                       # noqa: E402
import water_robustness as wr        # noqa: E402  (reuse build_frame)
import train_water_fortnight as twf  # noqa: E402  (reuse augment_negatives)

WATER_MODEL = ROOT / "data" / "refine" / "water_fortnight.joblib"   # the deployed (augmented) model
GEOJSON = ROOT / "data" / "inputs" / "seasonal_water.geojson"
EQ_AREA = "EPSG:6933"               # equal-area, so polygon area (ha) is honest
WATER_CARDS = ["mc_water_fortnight_augmented_v1", "mc_water_fortnight_v1"]


def water_body_areas():
    """Each water body's footprint area in hectares (its largest marked polygon)."""
    gdf = gpd.read_file(GEOJSON).to_crs(4326)
    gdf = gdf[gdf.waterbody.notna()].copy()
    gdf["area_ha"] = gdf.to_crs(EQ_AREA).geometry.area / 1e4
    return gdf.groupby("waterbody")["area_ha"].max()


def score(model, df, label="water"):
    """(precision, recall, f1, accuracy) of `model` on frame `df` for the water class."""
    if not len(df):
        return (float("nan"),) * 4
    yt = df.label.values
    yp = model.predict(df[sentinel.FEATURE_BANDS].values)
    p, r, f, _ = precision_recall_fscore_support(yt, yp, labels=[label], average=None, zero_division=0)
    return p[0], r[0], f[0], accuracy_score(yt, yp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dates", type=int, default=80)
    ap.add_argument("--n-pix", type=int, default=8)
    ap.add_argument("--small-max-ha", type=float, default=0.0,
                    help="water bodies at/under this area are 'small' (0 = use the median)")
    ap.add_argument("--write-card", action="store_true", help="write the summary onto the water card")
    args = ap.parse_args()

    model = joblib.load(WATER_MODEL)["model"]
    print(f"deployed water model: {WATER_MODEL.name}  |  features (S1+S2): {sentinel.FEATURE_BANDS}\n")

    df = wr.build_frame(args.max_dates, args.n_pix)
    areas = water_body_areas()
    thr = args.small_max_ha or float(np.median(areas.values))
    df = df.copy()
    df["area_ha"] = df.waterbody.map(areas)
    df = df.dropna(subset=["area_ha"])
    df["bucket"] = np.where(df.area_ha <= thr, "small", "large")

    print(f"\n{len(df)} usable pixels; small/large threshold = {thr:.2f} ha "
          f"({(areas <= thr).sum()} small vs {(areas > thr).sum()} large water bodies)\n")

    print("=== water class precision/recall on the DEPLOYED model, by water-body size ===")
    rows = {}
    for bucket in ["small", "large", "all"]:
        sub = df if bucket == "all" else df[df.bucket == bucket]
        p, r, f, a = score(model, sub)
        nb = sub.waterbody.nunique()
        rows[bucket] = (p, r, f, a, len(sub), nb)
        print(f"  {bucket:5s}: bodies {nb:3d}  px {len(sub):4d}  "
              f"water P {p:.3f}  R {r:.3f}  F1 {f:.3f}  acc {a:.3f}")

    # spurious-water probe: dryland (barren/built/greenery) negatives -> how many get called water?
    print("\n=== spurious-water probe (dryland negatives) ===")
    neg = twf.augment_negatives(args.n_pix)
    yp = model.predict(neg[sentinel.FEATURE_BANDS].values)
    fp_rate = float((yp == "water").mean()) if len(neg) else float("nan")
    print(f"  dryland pixels: {len(neg)}  |  called water (false positive): {fp_rate:.3f}")

    sp, sr, sf = rows["small"][:3]
    lp, lr, lf = rows["large"][:3]
    summary = (f"Small vs large water bodies (deployed S1+S2 model, week11/water_eval.py, "
               f"threshold {thr:.1f} ha): small water P {sp:.2f}/R {sr:.2f}/F1 {sf:.2f}, "
               f"large P {lp:.2f}/R {lr:.2f}/F1 {lf:.2f}; dryland false-positive (spurious water) "
               f"rate {fp_rate:.2f}.")
    print("\n" + summary)
    if args.write_card:
        import catalogue
        for cid in WATER_CARDS:
            if catalogue.get_card(cid):
                catalogue.update_card_meta(cid, about={"evidence": summary})
                print(f"wrote summary onto {cid} (About > Evidence).")
                break


if __name__ == "__main__":
    main()
