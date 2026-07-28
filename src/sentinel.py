"""Raw Sentinel-1/2 features for the per-fortnight water classifier (#5, #7).

The annual Alpha Earth embedding is a *year's* signal, so it can't answer "on the 14-July
fortnight, which pixels were water?". For that we go back to raw Sentinel: a short window of
Sentinel-1 SAR (VV/VH, cloud-proof) plus Sentinel-2 optical (water indices), composited around a
target date. A pixel gets one feature vector for that fortnight.

We keep the exact index maths the CoRE-stack flood pipeline uses
(`floodMappingPipelines/water_dataset_builder/ee_logic.py`) so our labels line up with theirs.
The trick that keeps this interactive (the flood pipeline had to go batch to dodge EE's memory
limit): we train a **linear** model offline on these features, then replay it as band math over
the composite image — same server-side, no-download path Alpha Earth already uses.

`feature_image` builds the EE image (for both training-time sampling and serving-time band math);
`sample_points` pulls feature rows at points for the offline trainer.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py

import numpy as np
import pandas as pd
import config

# the feature vector the water model trains + serves on, in a fixed order (StandardScaler handles
# the wildly different magnitudes: S1 dB vs S2 reflectance vs unitless indices).
FEATURE_BANDS = ["VV", "VH", "VV_VH_ratio", "NDWI", "MNDWI", "BSI", "B3", "B8", "B11"]

S1_WINDOW_DAYS = 7      # ±window around the target date (matches the flood pipeline)
S2_WINDOW_DAYS = 7
S2_MAX_CLOUD = 60


def _empty_with_bands(ee, names):
    """A fully-masked image carrying exactly `names`, so a window with no scene still yields those
    bands (median of it is masked, not band-less). Without this, an empty fortnight crashes the
    downstream .select — which is exactly what a whole-year sweep (#11) hits on cloudy fortnights."""
    return ee.Image.constant([0] * len(names)).rename(names).updateMask(ee.Image(0))


def _s1(ee, region, target):
    """Median Sentinel-1 VV/VH over the window — SAR, so clouds don't matter for water."""
    start = target.advance(-S1_WINDOW_DAYS, "day")
    end = target.advance(S1_WINDOW_DAYS, "day")
    col = (ee.ImageCollection("COPERNICUS/S1_GRD")
           .filterBounds(region).filterDate(start, end)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH")))
    col = col.select(["VV", "VH"]).merge(ee.ImageCollection([_empty_with_bands(ee, ["VV", "VH"])]))
    return col.median()


def _s2(ee, region, target):
    """Median cloud-lite Sentinel-2 over the window (the optical water indices)."""
    start = target.advance(-S2_WINDOW_DAYS, "day")
    end = target.advance(S2_WINDOW_DAYS, "day")
    bands = ["B2", "B3", "B4", "B8", "B11"]
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(region).filterDate(start, end)
           .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", S2_MAX_CLOUD)))
    col = col.select(bands).merge(ee.ImageCollection([_empty_with_bands(ee, bands)]))
    return col.median()


def feature_image(ee, region, date_str):
    """The `FEATURE_BANDS` feature image around `date_str` (YYYY-MM-DD), clipped to region.

    Same image is used two ways: sampled at points for offline training, and fed to the linear
    band-math renderer at serving time — so training and inference see identical features."""
    target = ee.Date(date_str)
    s1 = _s1(ee, region, target)
    s2 = _s2(ee, region, target)
    vv, vh = s1.select("VV"), s1.select("VH")
    b3, b8, b11 = s2.select("B3"), s2.select("B8"), s2.select("B11")
    b2, b4 = s2.select("B2"), s2.select("B4")

    ndwi = b3.subtract(b8).divide(b3.add(b8).add(1e-6)).rename("NDWI")
    mndwi = b3.subtract(b11).divide(b3.add(b11).add(1e-6)).rename("MNDWI")
    bsi_num = b11.add(b4).subtract(b8.add(b2))
    bsi = bsi_num.divide(b11.add(b4).add(b8.add(b2)).add(1e-6)).rename("BSI")
    ratio = vv.subtract(vh).rename("VV_VH_ratio")

    img = (vv.rename("VV").addBands(vh.rename("VH")).addBands(ratio)
           .addBands(ndwi).addBands(mndwi).addBands(bsi)
           .addBands(b3.rename("B3")).addBands(b8.rename("B8")).addBands(b11.rename("B11")))
    return img.select(FEATURE_BANDS).clip(region)


def sample_points(pts_gdf, date_str):
    """Sample the fortnight feature image at points (lon/lat) for one date -> a DataFrame of
    FEATURE_BANDS (NaN where a scene was missing). One EE round-trip per call, so callers batch
    points that share a date."""
    ee = config.ee_init()
    lons, lats = pts_gdf.lon.values, pts_gdf.lat.values
    region = ee.Geometry.Rectangle([float(lons.min()), float(lats.min()),
                                    float(lons.max()), float(lats.max())]).buffer(50)
    img = feature_image(ee, region, date_str)
    feats = [ee.Feature(ee.Geometry.Point([float(x), float(y)]), {"i": i})
             for i, (x, y) in enumerate(zip(lons, lats))]
    samp = img.sampleRegions(collection=ee.FeatureCollection(feats), scale=10,
                             geometries=False).getInfo()["features"]
    arr = np.full((len(pts_gdf), len(FEATURE_BANDS)), np.nan, dtype=np.float32)
    for f in samp:
        p = f["properties"]
        arr[p["i"]] = [p.get(b, np.nan) for b in FEATURE_BANDS]
    return pd.DataFrame(arr, columns=FEATURE_BANDS, index=pts_gdf.index)


def date_from_ddmmyyyy(s):
    """'26022025' -> '2025-02-26' (the seasonal_water.geojson date encoding)."""
    s = str(s)
    return f"{s[4:8]}-{s[2:4]}-{s[0:2]}"


if __name__ == "__main__":
    print("FEATURE_BANDS:", FEATURE_BANDS)
    assert date_from_ddmmyyyy("26022025") == "2025-02-26"
    print("sentinel.py smoke test OK")
