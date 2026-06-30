"""Phase 2 — extract dual embeddings (Alpha Earth 64-d + Tessera 128-d) at
ground-truth pixels and build the master dataframe.

Decisions (confirmed with user):
  - YEAR = 2024 for BOTH sources (Tessera only has usable India coverage in 2024).
  - Tessera values: dequantized float32 (sample_embeddings_at_points default).
  - <= ~100 random interior pixels per polygon.
  - Sample BOTH sources at the SAME polygon-interior lat/lon points (clean join).

Output schema (one row per pixel):
  polygon_id, source, core_class, lat, lon,
  ae_000..ae_063   (Alpha Earth, 64-d),
  te_000..te_127   (Tessera, 128-d)
"""
import argparse
import os
import numpy as np
import geopandas as gpd
import pandas as pd

YEAR = 2024
N_PIX = 100
ALPHA_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
DATA = os.path.join(os.path.dirname(__file__), "data")


# ---------------------------------------------------------------- points
def sample_interior_points(gdf, n_pix=N_PIX, seed=42):
    """Return a GeoDataFrame of up to n_pix random points inside each polygon.
    Sampling is done in a metric CRS (UTM 43N) for spatial uniformity."""
    rng = np.random.default_rng(seed)
    gdf_m = gdf.to_crs(32643)
    rows = []
    for _, poly in gdf_m.iterrows():
        geom = poly.geometry
        minx, miny, maxx, maxy = geom.bounds
        pts, attempts = [], 0
        while len(pts) < n_pix and attempts < n_pix * 50:
            xs = rng.uniform(minx, maxx, n_pix)
            ys = rng.uniform(miny, maxy, n_pix)
            for x, y in zip(xs, ys):
                if len(pts) >= n_pix:
                    break
                from shapely.geometry import Point
                p = Point(x, y)
                if geom.contains(p):
                    pts.append(p)
            attempts += n_pix
        for p in pts:
            rows.append({"polygon_id": poly.polygon_id,
                         "core_class": poly.core_class,
                         "geometry": p})
    pts_gdf = gpd.GeoDataFrame(rows, crs=32643).to_crs(4326)
    pts_gdf["lon"] = pts_gdf.geometry.x
    pts_gdf["lat"] = pts_gdf.geometry.y
    return pts_gdf


# ---------------------------------------------------------------- Alpha Earth
def sample_alpha_earth(pts_gdf, year=YEAR):
    """Sample Alpha Earth 64-d embedding at each point via GEE (server-side)."""
    import ee, config
    config.ee_init()
    # mosaic the year's tiles so the image actually covers our points
    # (.first() would grab one arbitrary global tile -> all NaN)
    lons, lats = pts_gdf.lon, pts_gdf.lat
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
        print(f"  alpha batch {start//BATCH + 1}/{(len(rows)-1)//BATCH + 1} done", flush=True)
    cols = [f"ae_{n:03d}" for n in range(64)]
    return pd.DataFrame(arr, columns=cols, index=pts_gdf.index)


# ---------------------------------------------------------------- Tessera
def sample_tessera(pts_gdf, year=YEAR):
    """Sample Tessera 128-d embedding (float32) at each point."""
    from geotessera import GeoTessera
    gt = GeoTessera()
    pts = list(zip(pts_gdf.lon.values, pts_gdf.lat.values))
    emb = np.asarray(gt.sample_embeddings_at_points(pts, year=year,
                                                    include_metadata=False),
                     dtype=np.float32)
    cols = [f"te_{n:03d}" for n in range(128)]
    return pd.DataFrame(emb, columns=cols, index=pts_gdf.index)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--polygons", default=os.path.join(DATA, "raw_polygons", "all_polygons.geojson"))
    ap.add_argument("--dev-only", action="store_true",
                    help="restrict to the N. Karnataka dev bbox")
    ap.add_argument("--n-pix", type=int, default=N_PIX)
    ap.add_argument("--alpha-only", action="store_true")
    ap.add_argument("--out", default=os.path.join(DATA, "embeddings.csv"))
    args = ap.parse_args()

    gdf = gpd.read_file(args.polygons)
    if args.dev_only:
        import json
        bbox = json.load(open(os.path.join(DATA, "dev_area.json")))["bbox_WSEN"]
        gdf = gdf.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
    print(f"polygons: {len(gdf)}  classes: {gdf.core_class.value_counts().to_dict()}")

    pts = sample_interior_points(gdf, n_pix=args.n_pix)
    print(f"sampled {len(pts)} interior points")

    ae = sample_alpha_earth(pts)
    print(f"Alpha Earth: {(~ae.isna().all(axis=1)).sum()}/{len(ae)} points have data")

    parts = [pts[["polygon_id", "core_class", "lat", "lon"]].reset_index(drop=True),
             ae.reset_index(drop=True)]
    if not args.alpha_only:
        te = sample_tessera(pts)
        print(f"Tessera: {(~te.isna().all(axis=1)).sum()}/{len(te)} points have data")
        parts.append(te.reset_index(drop=True))

    df = pd.concat(parts, axis=1)
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df)} rows x {df.shape[1]} cols -> {args.out}")


if __name__ == "__main__":
    main()