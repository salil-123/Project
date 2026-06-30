"""Shared embedding sampling: pixels inside polygons -> Alpha Earth / Tessera vectors.

This is the live, single-source version of what week-2's phase2_embeddings.py did
for the big offline dataframe. It's generalized so any caller (examples.py now, the
refinement trainer later) can feed it a GeoDataFrame of geometries plus whatever
label columns they carry, and get embeddings back at the same interior points.

Sampling happens at polygon-interior pixels; a Point geometry (a dropped marker)
just becomes one sample. Alpha Earth is fetched server-side via GEE; Tessera via
geotessera. Year is fixed to 2024 (the only year with usable India coverage).
"""
import sys
from pathlib import Path

# repo root holds config.py (EE init); put it on the path so `import config` works
# whether we're launched by the backend or run standalone from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

YEAR = 2024
N_PIX = 100
ALPHA_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"


def interior_points(gdf, n_pix=N_PIX, seed=42):
    """Up to n_pix random points inside each geometry, carrying its other columns.

    Polygons are sampled uniformly in a metric CRS (UTM 43N) so points aren't bunched
    by lat/lon distortion. A Point geometry passes straight through as a single sample.
    Every non-geometry column rides along onto each point, so labels like node/role/name
    stay attached. Output is EPSG:4326 with added lat/lon columns.
    """
    attr_cols = [c for c in gdf.columns if c != gdf.geometry.name]
    gdf_m = gdf.to_crs(32643)
    rng = np.random.default_rng(seed)
    rows = []
    for _, row in gdf_m.iterrows():
        geom = row.geometry
        attrs = {c: row[c] for c in attr_cols}
        if geom.geom_type == "Point":
            rows.append({**attrs, "geometry": geom})
            continue
        minx, miny, maxx, maxy = geom.bounds
        pts, attempts = [], 0
        # rejection-sample inside the polygon; cap attempts so slivers can't loop forever
        while len(pts) < n_pix and attempts < n_pix * 50:
            xs = rng.uniform(minx, maxx, n_pix)
            ys = rng.uniform(miny, maxy, n_pix)
            for x, y in zip(xs, ys):
                if len(pts) >= n_pix:
                    break
                p = Point(x, y)
                if geom.contains(p):
                    pts.append(p)
            attempts += n_pix
        rows.extend({**attrs, "geometry": p} for p in pts)

    pts_gdf = gpd.GeoDataFrame(rows, crs=32643).to_crs(4326)
    pts_gdf["lon"] = pts_gdf.geometry.x
    pts_gdf["lat"] = pts_gdf.geometry.y
    return pts_gdf


def sample_alpha(pts_gdf, year=YEAR):
    """Alpha Earth 64-d at each point, sampled server-side in GEE. NaN where missing."""
    import ee, config
    config.ee_init()
    lons, lats = pts_gdf.lon, pts_gdf.lat
    # mosaic the year's tiles so the image actually covers our points
    # (.first() would grab one arbitrary global tile -> all NaN)
    region = ee.Geometry.Rectangle([lons.min(), lats.min(), lons.max(), lats.max()])
    img = (ee.ImageCollection(ALPHA_COLLECTION)
           .filterDate(f"{year}-01-01", f"{year+1}-01-01")
           .filterBounds(region)
           .mosaic())
    bands = [f"A{n:02d}" for n in range(64)]
    arr = np.full((len(pts_gdf), 64), np.nan, dtype=np.float32)
    rows = list(pts_gdf.itertuples())
    BATCH = 3000  # GEE getInfo() feature-count limit
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        feats = [ee.Feature(ee.Geometry.Point([r.lon, r.lat]), {"idx": start + j})
                 for j, r in enumerate(chunk)]
        sampled = img.sampleRegions(collection=ee.FeatureCollection(feats),
                                    scale=10, geometries=False)
        for f in sampled.getInfo()["features"]:
            p = f["properties"]
            arr[p["idx"]] = [p.get(b, np.nan) for b in bands]
    cols = [f"ae_{n:03d}" for n in range(64)]
    return pd.DataFrame(arr, columns=cols, index=pts_gdf.index)


def sample_tessera(pts_gdf, year=YEAR):
    """Tessera 128-d (dequantized float32) at each point. Downloads tiles on demand."""
    from geotessera import GeoTessera
    gt = GeoTessera()
    pts = list(zip(pts_gdf.lon.values, pts_gdf.lat.values))
    emb = np.asarray(gt.sample_embeddings_at_points(pts, year=year, include_metadata=False),
                     dtype=np.float32)
    cols = [f"te_{n:03d}" for n in range(128)]
    return pd.DataFrame(emb, columns=cols, index=pts_gdf.index)


if __name__ == "__main__":
    # offline smoke test: points must land inside the polygon they came from. No GEE.
    from shapely.geometry import Polygon
    sq = Polygon([(77.0, 28.0), (77.02, 28.0), (77.02, 28.02), (77.0, 28.02)])
    gdf = gpd.GeoDataFrame({"node": ["greenery"], "role": ["positive"]},
                           geometry=[sq], crs=4326)
    pts = interior_points(gdf, n_pix=25)
    inside = pts.to_crs(4326).geometry.within(sq).all()
    print(f"sampled {len(pts)} points, all inside polygon: {inside}")
    print("columns carried through:", [c for c in pts.columns if c != "geometry"])
    assert inside and len(pts) == 25 and set(pts.node) == {"greenery"}
    print("sampling.py smoke test OK")
