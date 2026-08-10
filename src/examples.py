"""User example markings: ingest geometries, tag them to a hierarchy node, persist.

When a user splits or adds a class, they hand us example polygons ("these are crops",
"this is a tea plantation") drawn on the map or uploaded as GeoJSON/KML. This module
normalizes those into per-node stores and can sample them into a labeled, embedded
training frame for Phase 4.

An example attaches to the class it *exemplifies* (the child, e.g. `crops`), so a
SPLIT trainer later just gathers a parent's children. Storage mirrors contributions.py:
one GeoJSON FeatureCollection per node at data/examples/<node>.geojson.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py
import config
import hierarchy
import sampling

EXAMPLES_DIR = config.project_path("data/examples")  # anchored to root, CWD-independent
ROLES = ("positive", "negative")


def _path(node):
    return os.path.join(EXAMPLES_DIR, f"{node}.geojson")


def _empty_fc():
    return {"type": "FeatureCollection", "features": []}


def read_geometries(src):
    """Normalize a source into a 4326 GeoDataFrame of geometries.

    `src` is either a file path (.geojson / .json / .kml) or a raw GeoJSON dict —
    a bare geometry, a Feature, or a FeatureCollection (what Leaflet draw / uploads
    hand over). We only keep geometries here; labels are attached by add_examples.
    """
    if isinstance(src, (str, os.PathLike)):
        gdf = gpd.read_file(src).to_crs(4326)  # pyogrio infers the driver, incl. KML
        return gpd.GeoDataFrame(geometry=list(gdf.geometry), crs=4326)  # geometries only

    if isinstance(src, dict):
        t = src.get("type")
        if t == "FeatureCollection":
            geoms = [shape(f["geometry"]) for f in src["features"]]
        elif t == "Feature":
            geoms = [shape(src["geometry"])]
        else:  # assume it's a bare geometry
            geoms = [shape(src)]
        return gpd.GeoDataFrame(geometry=geoms, crs=4326)

    raise TypeError(f"unsupported example source: {type(src)}")


def add_examples(node, src, role="positive", name=None):
    """Tag geometries in `src` as examples of `node` and append to its store.

    Validates the node exists in the hierarchy first (you split/add a class before
    you give it examples). Returns the node's new total example count.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    tree = hierarchy.load()
    if node not in tree:
        raise KeyError(f"{node!r} is not in the hierarchy yet; add or split it first")
    name = name or tree[node]["name"]

    geoms = read_geometries(src)
    fc = load_examples(node)
    for geom in geoms.geometry:
        fc["features"].append({
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": {"node": node, "role": role, "name": name,
                           "ts": datetime.now(timezone.utc).isoformat()},
        })
    os.makedirs(EXAMPLES_DIR, exist_ok=True)
    with open(_path(node), "w") as fh:
        json.dump(fc, fh)
    return len(fc["features"])


def load_examples(node):
    """The node's FeatureCollection (empty if it has none yet)."""
    if not os.path.exists(_path(node)):
        return _empty_fc()
    with open(_path(node)) as fh:
        return json.load(fh)


def archive_all():
    """Move every marked example file aside so a fresh start begins with an empty canvas (#4).

    A new area is a new problem, and leftover example polygons from a past demo make a fresh split
    look pre-filled. This tucks the current markings into data/examples/archive/<timestamp>/ — it's
    a move, not a delete, so nothing's lost and trained models (which live as joblibs/zoo cards) are
    untouched. Returns the list of nodes whose examples were cleared."""
    import shutil
    if not os.path.isdir(EXAMPLES_DIR):
        return []
    files = [fn for fn in os.listdir(EXAMPLES_DIR) if fn.endswith(".geojson")]
    if not files:
        return []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(EXAMPLES_DIR, "archive", stamp)
    os.makedirs(dest, exist_ok=True)
    for fn in files:
        shutil.move(os.path.join(EXAMPLES_DIR, fn), os.path.join(dest, fn))
    return [fn[: -len(".geojson")] for fn in files]


def summary():
    """Per-node example counts broken down by role — handy for the UI/debugging."""
    out = {}
    if not os.path.isdir(EXAMPLES_DIR):
        return out
    for fn in os.listdir(EXAMPLES_DIR):
        if not fn.endswith(".geojson"):
            continue
        node = fn[:-len(".geojson")]
        counts = {r: 0 for r in ROLES}
        for f in load_examples(node)["features"]:
            counts[f["properties"]["role"]] += 1
        out[node] = counts
    return out


def build_training_frame(node, with_tessera=False, n_pix=sampling.N_PIX, year=sampling.YEAR):
    """Sample a node's example polygons into a labeled, embedded pixel frame.

    Returns columns: label (== node), role, lat, lon, ae_000.. (+ te_000.. if asked).
    Re-samples from GEE on every call (no cache, by design). Rows whose embeddings
    came back NaN (no coverage) are dropped.
    """
    fc = load_examples(node)
    if not fc["features"]:
        raise ValueError(f"no examples stored for {node!r}")

    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=4326)
    gdf["label"] = node
    gdf["poly"] = [f"{node}:{i}" for i in range(len(gdf))]  # group id for leak-free splits

    # carry `area` (the crown's source region) through when the examples have it, so a spatial
    # region-held-out split is possible (#8 wk10). Absent for most nodes -> just the usual columns.
    carry = ["label", "role", "poly"] + (["area"] if "area" in gdf.columns else [])
    pts = sampling.interior_points(gdf[carry + ["geometry"]], n_pix=n_pix)

    ae = sampling.sample_alpha(pts, year=year)
    parts = [pts[carry + ["lat", "lon"]].reset_index(drop=True),
             ae.reset_index(drop=True)]
    if with_tessera:
        parts.append(sampling.sample_tessera(pts, year=year).reset_index(drop=True))

    df = pd.concat(parts, axis=1)
    emb_cols = [c for c in df.columns if c.startswith(("ae_", "te_"))]
    return df.dropna(subset=emb_cols).reset_index(drop=True)


if __name__ == "__main__":
    # offline smoke test: ingest -> persist -> load -> sample points, all in a temp
    # store so data/ is left untouched. No GEE.
    import tempfile

    EXAMPLES_DIR = tempfile.mkdtemp()
    square = {"type": "Polygon", "coordinates":
              [[[77.0, 28.0], [77.02, 28.0], [77.02, 28.02], [77.0, 28.02], [77.0, 28.0]]]}

    total = add_examples("greenery", square, role="positive")
    print("stored examples for greenery:", total)

    fc = load_examples("greenery")
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["node"] == "greenery"

    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=4326)
    gdf["label"] = "greenery"
    pts = sampling.interior_points(gdf[["label", "geometry"]], n_pix=20)
    print(f"sampled {len(pts)} interior points, labels: {set(pts.label)}")
    print("summary():", summary())

    # a class not in the hierarchy should be refused
    try:
        add_examples("crops", square)
        print("BUG: accepted examples for a non-existent class")
    except KeyError as e:
        print("correctly refused unknown node:", e)

    print("examples.py smoke test OK")
