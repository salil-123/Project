"""Pick a DIVERSE set of Tessera tiles to fix the generalization gap.

The old select_tiles.py grabs the densest tiles, which clusters geographically
and is swamped by built_up. Here we instead do a weighted greedy set-cover over
(1-deg block, class) pairs: each pick is the tile that adds the most *new*
region+class coverage, with minority classes (water/barren/greenery) weighted up.
That spreads tiles across India and balances classes, within a tile budget.

    python select_diverse_tiles.py --budget 120

Writes data/selected_tiles.json + data/selected_polygons.geojson (same names the
download + phase2 scripts already read), so the rest of the pipeline is unchanged.
"""
import argparse
import json
import math
import os
import warnings
import geopandas as gpd
import numpy as np

warnings.filterwarnings("ignore")
DATA = os.path.join(os.path.dirname(__file__), "data")
FORCED = ["water", "barren", "greenery", "built_up"]  # non_water tags along, not forced
# scattered classes drive both diversity and the tile count; built_up is everywhere
# so it fills trivially and shouldn't burn the diversity budget
SCARCE = ["water", "barren", "greenery"]


def snap_tile_center(lon, lat):
    cx = math.floor(lon / 0.1) * 0.1 + 0.05
    cy = math.floor(lat / 0.1) * 0.1 + 0.05
    return (round(cx, 2), round(cy, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=150, help="max tiles to select")
    ap.add_argument("--per-class", type=int, default=150,
                    help="aim for at least this many polygons per forced class")
    args = ap.parse_args()

    g = gpd.read_file(os.path.join(DATA, "raw_polygons", "all_polygons.geojson"))
    c = gpd.GeoSeries(g.to_crs(3857).geometry.centroid, crs=3857).to_crs(4326)
    g["lon"], g["lat"] = c.x.values, c.y.values
    g["tile"] = [snap_tile_center(lo, la) for lo, la in zip(g["lon"], g["lat"])]
    g["block"] = (np.floor(g.lon).astype(int).astype(str) + "_" +
                  np.floor(g.lat).astype(int).astype(str))

    # weight each class inversely to how common it is, so rare classes pull harder
    freq = g.core_class.value_counts()
    w = {cls: float(len(g) / freq.get(cls, 1)) for cls in FORCED}

    # what each tile offers: its block, the (block,class) pairs it covers, and
    # how many polygons of each forced class sit inside it
    tiles = {}
    for tile, sub in g.groupby("tile"):
        block = sub.block.iloc[0]
        pairs = {(block, cls) for cls in sub.core_class.unique() if cls in SCARCE}
        per = {cls: int((sub.core_class == cls).sum()) for cls in FORCED}
        tiles[tile] = {"pairs": pairs, "n": len(sub), "per": per}

    chosen = []
    # phase A — diversity: greedy set-cover of (block,class) pairs so we touch as
    # many distinct regions as possible, rare classes weighted up
    covered = set()
    while len(chosen) < args.budget:
        best, best_gain = None, 0.0
        for tile, info in tiles.items():
            if tile in chosen:
                continue
            new = info["pairs"] - covered
            gain = sum(w[cls] for _, cls in new) + 1e-4 * info["n"]
            if gain > best_gain:
                best, best_gain = tile, gain
        if best is None or best_gain == 0:
            break
        chosen.append(best)
        covered |= tiles[best]["pairs"]

    # phase B — balance fill: keep adding tiles that supply the most of whichever
    # classes are still under target, until every class is covered or budget runs out
    counts = {cls: 0 for cls in FORCED}
    for t in chosen:
        for cls in FORCED:
            counts[cls] += tiles[t]["per"][cls]
    while len(chosen) < args.budget and any(counts[c] < args.per_class for c in FORCED):
        best, best_gain = None, 0.0
        for tile, info in tiles.items():
            if tile in chosen:
                continue
            # value polygons only for classes still short, weighted by rarity
            gain = sum(w[cls] * info["per"][cls]
                       for cls in FORCED if counts[cls] < args.per_class)
            if gain > best_gain:
                best, best_gain = tile, gain
        if best is None or best_gain == 0:
            break
        chosen.append(best)
        for cls in FORCED:
            counts[cls] += tiles[best]["per"][cls]

    sel = g[g.tile.isin(chosen)].copy()
    print(f"selected {len(chosen)} tiles  |  polygons covered: {len(sel)}")
    print("per-class polygons:", sel.core_class.value_counts().to_dict())
    print(f"distinct 1-deg blocks spanned: {sel.block.nunique()} (of {g.block.nunique()})")
    print(f"approx download: ~{len(chosen) * 0.15:.1f} GB at ~150 MB/tile")

    json.dump({"year": 2024, "tiles": [list(t) for t in chosen],
               "budget": args.budget,
               "blocks_spanned": int(sel.block.nunique()),
               "per_class": {k: int(v) for k, v in sel.core_class.value_counts().items()}},
              open(os.path.join(DATA, "selected_tiles.json"), "w"), indent=2)
    sel.drop(columns=["tile"]).to_file(
        os.path.join(DATA, "selected_polygons.geojson"), driver="GeoJSON")
    print("saved -> data/selected_tiles.json, data/selected_polygons.geojson")


if __name__ == "__main__":
    main()
