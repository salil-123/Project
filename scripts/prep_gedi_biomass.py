"""Collect a biomass training frame over an AOI: GEDI L4A above-ground biomass paired with the
Alpha Earth embedding at each shot (#3, wk10).

This is Ratinder's GEDI collection (cod892_biomass/.../get_gedi_csvs.ipynb) reduced to our
sampling.py shape and scoped to a bbox + year. GEDI L4A monthly `agbd` is quality/error/slope
masked exactly as he does it, stacked with the same Alpha Earth annual embedding every model here
uses (A00..A63 -> emb_0..63) plus slope, reduced onto a ~100 m grid, then sampled to points. The
output CSV (emb_0..63, slope, agbd, lat, lon) feeds scripts/train_biomass.py — biomass is a
regression target on the exact feature space we already classify on.

Run:
  python scripts/prep_gedi_biomass.py --bbox 77.0 28.4 77.4 28.7 --year 2022 \
      --out data/inputs/gedi_biomass_iit_2022.csv
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import config


def collect(bbox, year, max_points=8000):
    """Sample GEDI agbd + Alpha Earth emb + slope over the bbox for one year -> a DataFrame."""
    ee = config.ee_init()
    w, s, e, n = bbox
    region = ee.Geometry.Rectangle([w, s, e, n])

    # Alpha Earth annual embedding, mosaicked over the region (same source as sampling.sample_alpha)
    emb = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
           .filterDate(f"{year}-01-01", f"{year+1}-01-01").filterBounds(region).mosaic())
    native = [f"A{i:02d}" for i in range(64)]
    names = [f"emb_{i}" for i in range(64)]
    emb = emb.select(native, names)

    # terrain slope (GLO30), used both as a mask and a feature (Ratinder keeps it)
    dem = ee.ImageCollection("COPERNICUS/DEM/GLO30").filterBounds(region).select("DEM").mosaic()
    slope = ee.Terrain.slope(dem.setDefaultProjection("EPSG:3857")).rename("slope")

    # GEDI L4A monthly AGBD, quality/error/slope masked (the notebook's three masks)
    gedi = (ee.ImageCollection("LARSE/GEDI/GEDI04_A_002_MONTHLY")
            .filterBounds(region).filterDate(f"{year}-01-01", f"{year+1}-01-01"))

    def mask(img):
        good = img.select("l4_quality_flag").eq(1).And(img.select("degrade_flag").eq(0))
        rel = img.select("agbd_se").divide(img.select("agbd")).lte(0.5)
        return img.updateMask(good).updateMask(rel).updateMask(slope.lt(30))

    agbd = gedi.map(mask).select("agbd").mosaic()

    # stratified-sample only the pixels that carry a valid shot (class 1 = agbd present). A plain
    # sample() over a sparse masked mosaic hits mostly empty pixels; stratifiedSample targets the
    # present class directly, so it finds the handful of shots in an AOI. scale 100 m ~= one grid
    # cell per shot. (Ratinder's India-scale reduceResolution densification isn't needed here.)
    stacked = emb.addBands(slope).addBands(agbd).updateMask(agbd.mask())
    cls = agbd.mask().toInt().rename("class")
    samp = stacked.addBands(cls).stratifiedSample(
        numPoints=max_points, classBand="class", region=region, scale=100,
        classValues=[1], classPoints=[max_points], dropNulls=True,
        tileScale=16, geometries=True)
    feats = samp.getInfo()["features"]
    rows = []
    for f in feats:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        row = {"agbd": p.get("agbd"), "slope": p.get("slope"), "lat": lat, "lon": lon}
        for i in range(64):
            row[f"emb_{i}"] = p.get(f"emb_{i}")
        rows.append(row)
    return pd.DataFrame(rows).dropna()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    ap.add_argument("--year", type=int, default=2022)
    ap.add_argument("--max-points", type=int, default=8000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = collect(tuple(args.bbox), args.year, args.max_points)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"collected {len(df)} GEDI shots -> {out}")
    if len(df):
        print(f"  agbd {df.agbd.min():.1f}..{df.agbd.max():.1f} Mg/ha (mean {df.agbd.mean():.1f})")


if __name__ == "__main__":
    main()
