"""Validate the dense/sparse greenery NDVI rule split against CoreStack canopy density (#12 wk10).

Sir: the "imaginary" dense/sparse greenery split (our rule `ndvi_annual > t -> dense else sparse`)
can be checked against CoreStack's canopy-density classes — those maps exist, so open them and
compare. This does the quantitative half: over an AOI, it cross-tabs our NDVI split against the
CoreStack LULC v3 tree(dense-canopy) vs scrubland(sparse-canopy) classes and reports agreement.

Legend (derived empirically by ranking LULC v3 codes by mean annual NDVI over vegetated ground):
  code 6 = tree / forest  (mean NDVI ~0.60, the densest canopy)
  code 12 = scrubland      (mean NDVI ~0.31, sparse canopy)
so tree-vs-scrub is exactly the dense-vs-sparse-canopy contrast our rule is trying to draw.

Run (from repo root, needs EE):
  python week10/canopy_compare.py --bbox 88.5 26.4 88.9 26.8 --thr 0.3
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config

LULC_V3 = "projects/corestack-datasets/assets/datasets/LULC_v3_river_basin/pan_india_lulc_v3_2023_2024"
DENSE_CANOPY_CODE = 6      # tree / forest
SPARSE_CANOPY_CODE = 12    # scrubland


def compare(bbox, thr=0.3, year=2023):
    ee = config.ee_init()
    region = ee.Geometry.Rectangle(list(bbox))
    # our annual NDVI (max over the year, the greenest signal — what the rule split reads)
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterDate(f"{year}-01-01", f"{year+1}-01-01").filterBounds(region)
          .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 40)))
    ndvi = s2.map(lambda i: i.normalizedDifference(["B8", "B4"])).max()
    ours_dense = ndvi.gt(thr)                       # our rule: dense where NDVI over the threshold

    lulc = ee.Image(LULC_V3)
    cs_dense = lulc.eq(DENSE_CANOPY_CODE)           # CoreStack tree = dense canopy
    cs_sparse = lulc.eq(SPARSE_CANOPY_CODE)         # CoreStack scrub = sparse canopy
    veg = cs_dense.Or(cs_sparse)                    # compare only where CoreStack sees vegetation

    def area_ha(mask):
        a = mask.selfMask().multiply(ee.Image.pixelArea()).reduceRegion(
            ee.Reducer.sum(), region, 30, maxPixels=int(1e9), bestEffort=True).values().get(0)
        return ee.Number(a).divide(1e4)

    # confusion over vegetated pixels: (our dense/sparse) x (CoreStack dense/sparse)
    dd = area_ha(ours_dense.And(cs_dense)).getInfo()      # both dense -> agree
    ds = area_ha(ours_dense.And(cs_sparse)).getInfo()     # we say dense, CS says scrub
    sd = area_ha(ndvi.lte(thr).And(cs_dense)).getInfo()   # we say sparse, CS says tree
    ss = area_ha(ndvi.lte(thr).And(cs_sparse)).getInfo()  # both sparse -> agree
    total = dd + ds + sd + ss
    agree = (dd + ss) / total * 100 if total else float("nan")
    return {"dense_dense": dd, "dense_sparse": ds, "sparse_dense": sd, "sparse_sparse": ss,
            "agreement_pct": agree, "veg_ha": total, "thr": thr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, default=[88.5, 26.4, 88.9, 26.8],
                    metavar=("W", "S", "E", "N"))
    ap.add_argument("--thr", type=float, default=0.3, help="NDVI threshold for our dense/sparse rule")
    ap.add_argument("--year", type=int, default=2023)
    args = ap.parse_args()
    r = compare(tuple(args.bbox), thr=args.thr, year=args.year)
    print(f"\n=== dense/sparse (NDVI>{r['thr']}) vs CoreStack canopy (tree vs scrub) ===")
    print(f"  vegetated area compared: {r['veg_ha']:.0f} ha")
    print(f"  our dense & CoreStack tree  : {r['dense_dense']:.0f} ha")
    print(f"  our dense & CoreStack scrub : {r['dense_sparse']:.0f} ha")
    print(f"  our sparse & CoreStack tree : {r['sparse_dense']:.0f} ha")
    print(f"  our sparse & CoreStack scrub: {r['sparse_sparse']:.0f} ha")
    print(f"  --> agreement: {r['agreement_pct']:.1f}%")


if __name__ == "__main__":
    main()
