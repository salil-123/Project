"""ADD demo: add a 'Mining' class under barren from mining_polygons_india.gpkg (#27).

barren splits into a residual "Barren" + "Mining"; residual samples come from the
expert barren rows in master_alpha_full, mining positives from the gpkg polygons. The
map picks it up with no inference changes (it composites like the greenery split).

Idempotent: resets any prior mining split first. Run from repo root:
  python scripts/add_mining.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (week3/scripts -> root)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import geopandas as gpd

import hierarchy
import examples
import refine

GPKG = "data/inputs/mining_polygons_india.gpkg"
N_POLYGONS = 300   # cap so GEE sampling stays to a few batches
PARENT = "barren"


def reset(parent=PARENT):
    """Undo a previous mining split so the demo re-runs cleanly."""
    tree = hierarchy.load()
    kids = list(tree[parent]["children"])
    for k in kids:
        tree.pop(k, None)
        p = examples._path(k)
        if os.path.exists(p):
            os.remove(p)
    tree[parent]["children"] = []
    tree[parent]["classifier"] = None
    hierarchy.save(tree)
    for f in (f"{parent}.joblib", f"{parent}_train.csv"):
        fp = os.path.join(refine.REFINE_DIR, f)
        if os.path.exists(fp):
            os.remove(fp)
    if kids:
        print(f"reset prior split of {parent!r}: removed {kids}")


def main():
    reset()
    g = gpd.read_file(GPKG).to_crs(4326)
    if len(g) > N_POLYGONS:
        g = g.sample(N_POLYGONS, random_state=0)
    fc = {"type": "FeatureCollection",
          "features": [{"type": "Feature", "geometry": geom.__geo_interface__, "properties": {}}
                       for geom in g.geometry]}
    print(f"using {len(fc['features'])} mining polygons")

    refine.add_class_op(PARENT, "Mining", examples_src=fc, new_color="#7b3f00", n_pix=30)


if __name__ == "__main__":
    main()
