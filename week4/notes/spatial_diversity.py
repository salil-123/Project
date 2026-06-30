"""Spatial-diversity index for the dataset cards (week 4, #19).

How spread-out a dataset's samples are, as one number in [0,1]. We bin polygon
centroids into a coarse lat/lon grid, take the Shannon entropy of the per-cell counts,
and normalize by ln(n_points) so:
  ~1 = every polygon in its own cell (well spread),
  ~0 = everything piled into one spot (clustered).

It's the honest counter to "100 polygons, all from one district" — those score low even
though the count looks fine. Run from repo root:  python week4/notes/spatial_diversity.py
"""
import math
import os
import sys

import geopandas as gpd

CELL_DEG = 0.25  # ~28 km cells; coarse enough that nearby polygons share a cell


def diversity(geojson_path, cell=CELL_DEG):
    gdf = gpd.read_file(geojson_path).to_crs(4326)
    # centroid of each polygon; .representative_point() stays inside odd shapes
    pts = gdf.geometry.representative_point()
    n = len(pts)
    if n == 0:
        return {"n": 0, "occupied": 0, "diversity": 0.0}

    # snap each point to a grid cell, count points per cell
    cells = {}
    for p in pts:
        key = (math.floor(p.x / cell), math.floor(p.y / cell))
        cells[key] = cells.get(key, 0) + 1

    # Shannon entropy over occupied cells, normalized by ln(n) -> [0,1]
    H = -sum((c / n) * math.log(c / n) for c in cells.values())
    norm = H / math.log(n) if n > 1 else 0.0
    return {"n": n, "occupied": len(cells), "diversity": round(norm, 3)}


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.chdir(root)
    print(f"spatial-diversity index ({CELL_DEG}-deg cells)\n")
    print(f"{'dataset':<28}{'n':>5}{'cells':>7}{'diversity':>11}")
    for name in ("crops", "trees", "mining"):
        r = diversity(f"data/examples/{name}.geojson")
        print(f"{name:<28}{r['n']:>5}{r['occupied']:>7}{r['diversity']:>11.3f}")
