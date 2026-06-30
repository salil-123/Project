"""Sample Alpha Earth at the (now-readable) seasonal + perennial water polygons and
write data/water_extra.csv, so the base trainer can pool them in for extra water
diversity. Mirrors scripts/ingest_farmforest.py. Run from repo root.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (week3/scripts -> root)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

import config
import sampling

ASSETS = ["projects/ee-mtpictd/assets/GTSeasonal", "projects/ee-mtpictd/assets/GTPerennial"]
OUT = "data/water_extra.csv"


def main():
    ee = config.ee_init()
    geoms = []
    for a in ASSETS:
        feats = ee.FeatureCollection(a).getInfo()["features"]
        geoms += [shape(f["geometry"]) for f in feats]
    gdf = gpd.GeoDataFrame({"core_class": ["water"] * len(geoms)}, geometry=geoms, crs=4326)
    print(f"{len(gdf)} water polygons")

    pts = sampling.interior_points(gdf, n_pix=100)
    ae = sampling.sample_alpha(pts).reset_index(drop=True)
    out = pd.concat([pts[["core_class", "lat", "lon"]].reset_index(drop=True), ae], axis=1)
    out = out.dropna(subset=[f"ae_{i:03d}" for i in range(64)]).reset_index(drop=True)
    out.to_csv(OUT, index=False)
    print(f"wrote {len(out)} water pixels -> {OUT}")


if __name__ == "__main__":
    main()
