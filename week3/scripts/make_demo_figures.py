"""Generate the before/after demo figures + confirm metrics for the week-3 slides.

For each demo we render the same area twice with the live 10 m raster classifier:
  before = base map only (refinements={})  -> greenery / barren as one class
  after  = with the trained split          -> crops/trees/shrubs, or mining/barren
Both come straight from infer.classify_bbox_raster, so the figures match the tool.

Run from repo root:  python scripts/make_demo_figures.py
"""
import os
import sys
import json
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (week3/scripts -> root)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report

import infer
import refine

# figures live next to the slides, in week3/, not at repo root
FIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "figures")
HALF = 0.015  # ~3.3 km box: small enough for true 10 m, big enough to read


def _bbox_around(geom):
    c = geom.centroid
    return (c.x - HALF, c.y - HALF, c.x + HALF, c.y + HALF)


def _save(url, name):
    path = os.path.join(FIG, name)
    data = urllib.request.urlopen(url, timeout=120).read()
    with open(path, "wb") as f:
        f.write(data)
    print(f"  saved {name} ({len(data)} bytes)")


def figures_for(name, geom):
    """Render + save before (base) and after (refined) PNGs for one demo area."""
    bbox = _bbox_around(geom)
    print(f"{name}: bbox {tuple(round(v, 3) for v in bbox)}")
    before, c0 = infer.classify_bbox_raster(bbox, refinements={}, colors=infer.CLASS_COLORS)
    after, c1 = infer.classify_bbox_raster(bbox)
    _save(before, f"{name}_before.png")
    _save(after, f"{name}_after.png")
    print(f"  before counts: {c0}")
    print(f"  after  counts: {c1}")


def metrics_from_cache(parent):
    """Recompute the held-out per-class report from the cached training table (no GEE)."""
    df = pd.read_csv(os.path.join("data/refine", f"{parent}_train.csv"))
    X, y, g = df[refine.AE_COLS].values, df.label.values, df.poly.values
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=0).split(X, y, g))
    model = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced")).fit(X[tr], y[tr])
    print(f"\n{parent} split — held-out ({len(te)} px):")
    print(classification_report(y[te], model.predict(X[te]), digits=3, zero_division=0))


def main():
    os.makedirs(FIG, exist_ok=True)

    crops = json.load(open("data/examples/crops.geojson"))["features"]
    figures_for("greenery", shape(crops[3]["geometry"]))

    mining = gpd.read_file("data/inputs/mining_polygons_india.gpkg").to_crs(4326)
    figures_for("mining", mining.geometry.iloc[0])

    print("\n=== metrics (confirm against the slide tables) ===")
    metrics_from_cache("greenery")
    metrics_from_cache("barren")


if __name__ == "__main__":
    main()
