"""Phase 1 — pull ground-truth polygons from accessible GEE assets,
standardize to a common schema, export to GeoJSON, and build a class inventory.

Standard schema per feature:
    polygon_id | source | raw_class | core_class | geometry

core_class is one of: greenery, water, built_up, barren  (base task: first 3).
"""
import json
import os
import geopandas as gpd
import config

ee = config.ee_init()

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "raw_polygons")
os.makedirs(OUT_DIR, exist_ok=True)

# --- per-asset mapping: how to derive (raw_class, core_class) from properties ---
# Each entry: asset path, the property to read, and a {value: core_class} map.
SOURCES = {
    "indiasat": {
        "path": config.GT_ASSETS["indiasat_4class"],
        "prop": "category",
        "map": {
            "green":       "greenery",
            "water":       "water",
            "built-up":    "built_up",
            "barren_land": "barren",
        },
    },
    "farmforest": {
        "path": config.GT_ASSETS["farmforest"],
        "prop": "class",
        # 5 = crop/farm, 6 = forest/tree  (sample 'forest_101' was class 6)
        "map": {5: "greenery", 6: "greenery"},
    },
    "gt_binary": {
        "path": config.GT_ASSETS["binary_water"],
        "prop": "class",
        # Inferred 2026-05-23 via JRC GlobalSurfaceWater + Sentinel-2 NDWI overlay:
        # class 2 scored higher on every water indicator -> 2=water, 1=non_water.
        "map": {2: "water", 1: "non_water"},
    },
}


def export_source(name, spec):
    fc = ee.FeatureCollection(spec["path"])
    print(f"\n[{name}] downloading {spec['path']} ...")
    geo = fc.getInfo()  # GeoJSON FeatureCollection
    feats = geo.get("features", [])
    out_feats = []
    for i, f in enumerate(feats):
        props = f.get("properties", {})
        raw = props.get(spec["prop"])
        core = spec["map"].get(raw)
        if core is None:
            continue  # unmapped value -> skip
        out_feats.append({
            "type": "Feature",
            "geometry": f.get("geometry"),
            "properties": {
                "polygon_id": f"{name}_{i}",
                "source": name,
                "raw_class": raw,
                "core_class": core,
            },
        })
    out = {"type": "FeatureCollection", "features": out_feats}
    path = os.path.join(OUT_DIR, f"{name}.geojson")
    with open(path, "w") as fh:
        json.dump(out, fh)
    print(f"[{name}] kept {len(out_feats)}/{len(feats)} features -> {path}")
    return path


def main():
    paths = [export_source(n, s) for n, s in SOURCES.items()]

    # --- combine + inventory ---
    gdfs = [gpd.read_file(p) for p in paths]
    combined = gpd.GeoDataFrame(
        __import__("pandas").concat(gdfs, ignore_index=True), crs="EPSG:4326"
    )
    combined_path = os.path.join(OUT_DIR, "all_polygons.geojson")
    combined.to_file(combined_path, driver="GeoJSON")

    print("\n===== INVENTORY (polygon counts) =====")
    print(combined.groupby(["core_class", "source"]).size().to_string())
    print("\nby core_class:")
    print(combined["core_class"].value_counts().to_string())
    print(f"\nCombined -> {combined_path}")


if __name__ == "__main__":
    main()