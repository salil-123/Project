"""Random-location eval set that has BOTH embeddings.

Truly-random points anywhere in India can't be tested with Tessera (their tiles
aren't downloaded). So we sample random points INSIDE the 200 tiles we already
have, label them with ESA WorldCover, and grab Alpha Earth (GEE) + Tessera (cached)
at each. Not a perfect stand-in for pan-India random (our tiles lean class-diverse,
not greenery-heavy), but it lets us check the prior behavior with both embeddings
present. We later reweight per-class recall by India's true prior for a fair number.

Out: data/random_te_eval.csv  (lon, lat, wc, true_class, ae_000.., te_000..)
"""
import json, warnings
import numpy as np, pandas as pd
import ee, config
warnings.filterwarnings("ignore")
config.ee_init()

PER_TILE = 12
SEED = 7
WC_MAP = {10: "greenery", 20: "greenery", 30: "greenery", 40: "greenery",
          50: "built_up", 60: "barren", 70: "other", 80: "water",
          90: "other", 95: "other", 100: "other"}


def main():
    tiles = [tuple(t) for t in json.load(open("data/selected_tiles.json"))["tiles"]]
    rng = np.random.default_rng(SEED)
    # uniform points inside each 0.1-deg tile bbox
    pts = []
    for lon, lat in tiles:
        xs = rng.uniform(lon - 0.05, lon + 0.05, PER_TILE)
        ys = rng.uniform(lat - 0.05, lat + 0.05, PER_TILE)
        pts += list(zip(xs, ys))
    print(f"{len(pts)} random points across {len(tiles)} cached tiles")

    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").rename("wc")
    ae = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
          .filterDate("2024-01-01", "2025-01-01").mosaic())
    stack = wc.addBands(ae)

    bands = [f"A{n:02d}" for n in range(64)]
    rows = [None] * len(pts)
    BATCH = 500
    for s in range(0, len(pts), BATCH):
        chunk = pts[s:s + BATCH]
        feats = [ee.Feature(ee.Geometry.Point([x, y]), {"i": s + j})
                 for j, (x, y) in enumerate(chunk)]
        samp = stack.sampleRegions(collection=ee.FeatureCollection(feats),
                                   scale=10).getInfo()["features"]
        for f in samp:
            p = f["properties"]
            if "wc" not in p or p.get("A00") is None:
                continue
            i = p["i"]
            rows[i] = {"lon": pts[i][0], "lat": pts[i][1], "wc": int(p["wc"]),
                       **{f"ae_{k:03d}": p[bands[k]] for k in range(64)}}
        print(f"  AE/WC batch {s//BATCH+1}/{(len(pts)-1)//BATCH+1}", flush=True)

    keep = [r for r in rows if r is not None]
    df = pd.DataFrame(keep)
    df["true_class"] = df.wc.map(WC_MAP)

    # Tessera at the same points (tiles already cached -> fast)
    from geotessera import GeoTessera
    gt = GeoTessera()
    te = np.asarray(gt.sample_embeddings_at_points(
        list(zip(df.lon.values, df.lat.values)), year=2024), dtype=np.float32)
    for k in range(128):
        df[f"te_{k:03d}"] = te[:, k]
    df = df.dropna(subset=[f"te_{k:03d}" for k in range(128)])

    df.to_csv("data/random_te_eval.csv", index=False)
    print(f"\nwrote {len(df)} points -> data/random_te_eval.csv")
    print("class dist (within our tiles):", df.true_class.value_counts(normalize=True).round(3).to_dict())


if __name__ == "__main__":
    main()