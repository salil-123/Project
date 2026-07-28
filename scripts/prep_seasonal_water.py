"""#27 — turn the downloaded seasonal-water ground truth into a zoo dataset card.

Water/non-water polygons for farm ponds and water bodies, downloaded from the floodMappingPipelines
dataset (github.com/kshavv/floodMappingPipelines). They live under
data/seasonal_water_ground_truth_polygons/ as shapefiles; each polygon's `Name` encodes the label
plus date, e.g. `311W20102025` = waterbody 311, Water, 20-10-2025; `200NW13042019` = Non-Water. A
single waterbody recurs at ~10 dates with W vs NW, which is the seasonal signal (water present vs
absent by date). We fold every shapefile into one labelled GeoJSON and mint a training dataset card
`ds_seasonal_water_v1` (classes water / non_water) so it shows in the zoo and can seed a future
seasonal-water split.

Run from the repo root with the venv:
    ./.venv/Scripts/python.exe scripts/prep_seasonal_water.py
"""
import glob
import re
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import pandas as pd

import catalogue

SRC = ROOT / "data" / "seasonal_water_ground_truth_polygons"
OUT = ROOT / "data" / "inputs" / "seasonal_water.geojson"
# 311W20102025 / 200NW13042019 -> (id, W|NW, DDMMYYYY). NW checked before W so it wins the match.
NAME_RE = re.compile(r"^(\d+)(NW|W)(\d{8})$")


def _label(name):
    m = NAME_RE.match(str(name or "").strip())
    if not m:
        return None, None, None
    wid, tok, date = m.groups()
    return ("non_water" if tok == "NW" else "water"), wid, date


def main():
    rows = []
    for shp in sorted(glob.glob(str(SRC / "**" / "*.shp"), recursive=True)):
        g = gpd.read_file(shp).to_crs(4326)
        for _, r in g.iterrows():
            label, wid, date = _label(r.get("Name"))
            if label is None or r.geometry is None or r.geometry.is_empty:
                # negatives.shp names are still NW-coded; anything unparseable is treated as non_water
                label = "non_water"
            rows.append({"label": label, "role": "positive", "waterbody": wid,
                         "date": date, "name": r.get("Name"), "geometry": r.geometry.buffer(0)})
    gdf = gpd.GeoDataFrame(rows, crs=4326)
    counts = gdf.label.value_counts().to_dict()
    print(f"read {len(gdf)} polygons: {counts}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT.relative_to(ROOT)}")

    # dataset card: bbox extent + spread over all polygons, two classes with counts
    feats = [{"type": "Feature", "properties": {"role": "positive"},
              "geometry": geom.__geo_interface__} for geom in gdf.geometry]
    bbox, div, occ = catalogue._geojson_stats(feats)
    rel = str(OUT.relative_to(ROOT)).replace("\\", "/")
    catalogue.write_card({
        "id": "ds_seasonal_water_v1",
        "name": "Seasonal water ground truth (water / non-water by date)",
        "description": "Water-present vs water-absent polygons for farm ponds / water bodies, marked "
                       "across ~10 dates each (2019-2025). Downloaded from "
                       "github.com/kshavv/floodMappingPipelines.",
        "type": "training", "kind": "polygons",
        "classes": [{"class": "water", "name": "Water", "count": int(counts.get("water", 0))},
                    {"class": "non_water", "name": "Non-water", "count": int(counts.get("non_water", 0))}],
        "definition": {"type": "polygons", "path": rel, "label_col": "label"},
        "extent": {"spatial": {"type": "bbox", "value": bbox},
                   "temporal": {"year": 2024, "note": "polygons span 2019-2025"}},
        "provenance": {"annotator": "floodMappingPipelines dataset (downloaded)",
                       "method": "~10 dates per water body; water pixels inside the boundary, "
                                 "non-water from an outer ring",
                       "evidence": ["https://github.com/kshavv/floodMappingPipelines"],
                       "license": None, "notes": "Name = <waterbodyId><W|NW><DDMMYYYY>"},
        "quality": {"n_polygons": len(feats), "occupied_cells": occ, "spatial_diversity": div,
                    "class_balance": counts},
        "version": 1, "created": catalogue._now(),
    })
    print("minted ds_seasonal_water_v1")


if __name__ == "__main__":
    main()
