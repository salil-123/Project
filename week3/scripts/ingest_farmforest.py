"""One-off: pull FarmForest crop/tree polygons from GEE into the examples store.

FarmForest_Groundtruth uses class 5 = cropland, class 6 = forest (tree). We export
each class's geometries as a GeoJSON FeatureCollection and hand them to
examples.add_examples under the matching hierarchy node (crops / trees). Idempotent:
clears each node's store first so re-runs don't pile up duplicates.

Run from repo root:  python scripts/ingest_farmforest.py
"""
import os
import sys

# make src/ (examples, hierarchy) and the repo root (config) importable
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (week3/scripts -> root)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import config
import examples

FARMFOREST = "projects/ee-indiasat/assets/Polygon_Groundtruth/FarmForest_Groundtruth"
CLASS_TO_NODE = {5: "crops", 6: "trees"}  # FarmForest class -> our hierarchy node


def featurecollection_for(ee, cls):
    """All FarmForest geometries with the given class, as a GeoJSON FeatureCollection."""
    fc = ee.FeatureCollection(FARMFOREST).filter(ee.Filter.eq("class", cls))
    feats = fc.getInfo()["features"]
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": f["geometry"], "properties": {}}
                         for f in feats]}


def main():
    ee = config.ee_init()
    for cls, node in CLASS_TO_NODE.items():
        # fresh start for this node so the script is idempotent
        path = examples._path(node)
        if os.path.exists(path):
            os.remove(path)
        coll = featurecollection_for(ee, cls)
        total = examples.add_examples(node, coll, role="positive")
        print(f"FarmForest class {cls} -> {node}: {len(coll['features'])} polygons, "
              f"store now has {total}")


if __name__ == "__main__":
    main()
