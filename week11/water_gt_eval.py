"""#13 wk11 — validate the water model on sir's EE ground-truth + show the spurious-water filter.

Three EE assets (all readable from our project):
  - GTSeasonal  (16 polys)  — seasonal water bodies (all water)
  - GTPerennial (13 polys)  — perennial water bodies (all water)
  - GT_BINARY_LATEST (288)  — differently-sized water / non-water markings (`class` 1/2, `area_sqm`)

For each we sample interior points, run the deployed per-fortnight water model over `--n-dates` dates
across the year, and count how many fortnights each point read water. Then we sweep the **persistence
threshold** (hold a pixel as water only if it read water in >= t fortnights, #13): a higher t cuts
spurious detections (non-water called water) at some cost to seasonal-water recall — exactly the
trade-off sir described. We always report precision / recall / F1, never bare accuracy.

Run (needs EE):
  python week11/water_gt_eval.py --n-dates 12 --n-pix 6
  python week11/water_gt_eval.py --n-dates 12 --write-card
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import joblib
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config       # noqa: E402
import sampling     # noqa: E402
import sentinel     # noqa: E402

WATER_MODEL = ROOT / "data" / "refine" / "water_fortnight.joblib"
WATER_CARDS = ["mc_water_fortnight_augmented_v1", "mc_water_fortnight_v1"]
ASSETS = {
    "GTSeasonal": "projects/ee-mtpictd/assets/GTSeasonal",
    "GTPerennial": "projects/ee-mtpictd/assets/GTPerennial",
    "GT_BINARY": "projects/ee-vatsal/assets/GT_BINARY_LATEST",
}
EQ_AREA = "EPSG:6933"


def load_ee_polys(ee, asset):
    """An EE FeatureCollection -> a 4326 GeoDataFrame (small assets, so getInfo is fine)."""
    fc = ee.FeatureCollection(asset).getInfo()
    feats = fc.get("features", [])
    return gpd.GeoDataFrame([f.get("properties", {}) for f in feats],
                            geometry=[shape(f["geometry"]) for f in feats], crs="EPSG:4326")


def points_for(gdf, source, n_pix):
    """Interior points for one asset, carrying source + a per-polygon area (ha) + the raw class."""
    gdf = gdf.reset_index(drop=True).copy()
    gdf["poly"] = [f"{source}:{i}" for i in range(len(gdf))]
    gdf["source"] = source
    gdf["area_ha"] = (gdf.to_crs(EQ_AREA).geometry.area / 1e4) if len(gdf) else []
    gdf["cls"] = gdf["class"] if "class" in gdf.columns else -1
    pts = sampling.interior_points(gdf[["poly", "source", "area_ha", "cls", "geometry"]], n_pix=n_pix)
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-dates", type=int, default=12, help="fortnight dates sampled across the year")
    ap.add_argument("--n-pix", type=int, default=6)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--thresholds", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--write-card", action="store_true")
    args = ap.parse_args()

    ee = config.ee_init()
    model = joblib.load(WATER_MODEL)["model"]
    print(f"deployed water model: {WATER_MODEL.name} | features (S1+S2): {sentinel.FEATURE_BANDS}")

    # gather interior points from all three assets
    parts = []
    for src, asset in ASSETS.items():
        gdf = load_ee_polys(ee, asset)
        pts = points_for(gdf, src, args.n_pix)
        print(f"  {src}: {len(gdf)} polys -> {len(pts)} interior points")
        parts.append(pts)
    pts = pd.concat(parts, ignore_index=True)
    N = len(pts)

    # count water-votes per point across the year's dates
    dates = [f"{args.year}-{m:02d}-15" for m in np.linspace(1, 12, args.n_dates).astype(int)]
    counts = np.zeros(N, dtype=int)
    valid = np.zeros(N, dtype=bool)
    for k, d in enumerate(dates, 1):
        feats = sentinel.sample_points(pts, d)
        X = feats.values
        ok = ~np.isnan(X).any(axis=1)
        if ok.any():
            pred = model.predict(X[ok])
            idx = np.where(ok)[0]
            counts[idx[pred == "water"]] += 1
            valid[ok] = True
        print(f"  [{k}/{len(dates)}] {d}: {int(ok.sum())} valid samples")
    pts = pts[valid].copy()
    counts = counts[valid]
    print(f"\n{len(pts)} points with >=1 valid observation over {len(dates)} dates\n")

    # which GT_BINARY class is water? the class detected as water more often (at t>=1) is water.
    bin_mask = pts.source.values == "GT_BINARY"
    if bin_mask.any():
        det1 = counts >= 1
        rates = {c: det1[bin_mask & (pts.cls.values == c)].mean()
                 for c in sorted(set(pts.cls.values[bin_mask]))}
        water_cls = max(rates, key=rates.get)
        print(f"GT_BINARY class water-detection @t>=1: {{{', '.join(f'{c}:{r:.2f}' for c,r in rates.items())}}}"
              f" -> class {water_cls} = water")
    else:
        water_cls = None

    # per-source, per-threshold report
    def det(sel, t):
        return (counts[sel] >= t).mean() if sel.any() else float("nan")

    print("\n=== water-body recall by persistence threshold t (fraction held as water) ===")
    for src in ["GTSeasonal", "GTPerennial"]:
        sel = pts.source.values == src
        row = "  ".join(f"t>={t}: {det(sel, t):.2f}" for t in args.thresholds)
        print(f"  {src:12s} (all water, {int(sel.sum()):3d} px): {row}")

    # GT_BINARY: precision/recall/F1 for water + spurious (non-water FP), with a small/large split
    print("\n=== GT_BINARY water precision/recall/F1 + spurious (non-water called water) ===")
    is_water = bin_mask & (pts.cls.values == water_cls)
    is_nonwater = bin_mask & (pts.cls.values != water_cls)
    thr_med = float(np.median(pts.area_ha.values[bin_mask])) if bin_mask.any() else 0.0
    small = bin_mask & (pts.area_ha.values <= thr_med)
    large = bin_mask & (pts.area_ha.values > thr_med)
    print(f"  small/large split at {thr_med:.3f} ha")
    summ = {}
    for t in args.thresholds:
        tp = (counts[is_water] >= t).sum()
        fn = is_water.sum() - tp
        fp = (counts[is_nonwater] >= t).sum()
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        spur = (counts[is_nonwater] >= t).mean() if is_nonwater.any() else float("nan")
        rec_s = det(small & (pts.cls.values == water_cls), t)
        rec_l = det(large & (pts.cls.values == water_cls), t)
        summ[t] = (prec, rec, f1, spur, rec_s, rec_l)
        print(f"  t>={t}: water P {prec:.2f} R {rec:.2f} F1 {f1:.2f} | spurious(non-water) {spur:.2f} "
              f"| small-water R {rec_s:.2f}  large-water R {rec_l:.2f}")

    t2 = summ.get(2, summ[args.thresholds[0]])
    summary = (f"EE GT (week11/water_gt_eval.py, {args.year}): with a 2-fortnight persistence filter, "
               f"GT_BINARY water P {t2[0]:.2f}/R {t2[1]:.2f}/F1 {t2[2]:.2f}, spurious (non-water called "
               f"water) {t2[3]:.2f}; small-water recall {t2[4]:.2f} vs large {t2[5]:.2f}. Raising the "
               f"threshold cuts spurious detections at some cost to small/seasonal recall.")
    print("\n" + summary)
    if args.write_card:
        import catalogue
        for cid in WATER_CARDS:
            if catalogue.get_card(cid):
                prev = (catalogue.get_card(cid).get("about") or {}).get("evidence", "")
                catalogue.update_card_meta(cid, about={"evidence": (prev + " | " + summary).strip(" |")})
                print(f"appended summary onto {cid} (About > Evidence).")
                break


if __name__ == "__main__":
    main()
