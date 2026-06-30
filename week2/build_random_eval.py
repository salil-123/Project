"""Truly-random India evaluation using ESA WorldCover (10m) as reference truth.

Samples uniformly-random points across India, labels each from WorldCover, samples
Alpha Earth at the same point, maps WorldCover -> our 4 classes (+ 'other'), and
saves a CSV. This lets us measure real-world accuracy on random locations and see
WHERE we fail. WorldCover itself is ~75-85% accurate, so it's an imperfect-but-
independent yardstick.
"""
import os, warnings
import numpy as np, pandas as pd
import ee, config
warnings.filterwarnings("ignore")
config.ee_init()

N = 3000
SEED = 11
# WorldCover code -> our scheme
WC_MAP = {
    10: "greenery",  # tree cover
    20: "greenery",  # shrubland
    30: "greenery",  # grassland
    40: "greenery",  # cropland
    50: "built_up",  # built-up
    60: "barren",    # bare / sparse vegetation
    70: "other",     # snow & ice
    80: "water",     # permanent water
    90: "other",     # herbaceous wetland
    95: "other",     # mangroves
    100: "other",    # moss & lichen
}


def main():
    india = (ee.FeatureCollection("FAO/GAUL/2015/level0")
             .filter(ee.Filter.eq("ADM0_NAME", "India")).geometry())
    pts = ee.FeatureCollection.randomPoints(region=india, points=N, seed=SEED)

    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").rename("wc")
    ae = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
          .filterDate("2024-01-01", "2025-01-01").mosaic())
    stack = wc.addBands(ae)

    rows, bands = [], [f"A{n:02d}" for n in range(64)]
    plist = pts.toList(N)
    BATCH = 500
    for s in range(0, N, BATCH):
        chunk = ee.FeatureCollection(plist.slice(s, s + BATCH))
        samp = stack.sampleRegions(collection=chunk, scale=10, geometries=True).getInfo()
        for f in samp["features"]:
            p = f["properties"]
            if "wc" not in p or p.get("A00") is None:
                continue
            lon, lat = f["geometry"]["coordinates"]
            rows.append({"lon": lon, "lat": lat, "wc": int(p["wc"]),
                         **{f"ae_{i:03d}": p[bands[i]] for i in range(64)}})
        print(f"  batch {s//BATCH+1}/{(N-1)//BATCH+1}: {len(rows)} pts so far", flush=True)

    df = pd.DataFrame(rows)
    df["true_class"] = df.wc.map(WC_MAP)
    df.to_csv("data/random_eval.csv", index=False)
    print(f"\nwrote {len(df)} random points -> data/random_eval.csv")
    print("WorldCover-derived class distribution (India's real prior):")
    print(df.true_class.value_counts(normalize=True).round(3).to_dict())


if __name__ == "__main__":
    main()
