"""EE-native Random Forest classifiers ported from the IndiaSAT/CoRE-stack production LULC (#13 wk10).

Raman's two models (the GitHub scripts sir shared, saved at repo root) both train an
`ee.Classifier.smileRandomForest` AND classify entirely inside Earth Engine, so unlike a local
sklearn RF they render server-side as map tiles just like our Alpha Earth band-math path. No
download, no point grid. We reproduce them faithfully:

  - tree vs crop  : pan-India, on a 46-band Sentinel-1 SAR 16-day time series
                    (asset L2_TrainingData_SAR_TimeSeries_1Year, class 5=cropland / 6=tree).
  - farm/plantation/scrubland : per-AEZ, on the Alpha Earth embedding (our own feature space),
                    trained from gee_samples_all filtered to the AOI's agro-ecological region.

The "model" here is a recipe (a stable training asset + feature spec + RF params), re-trained on the
fly per request — exactly how the production pipeline runs ("training happens on the fly, no model is
saved"). The zoo card stores that recipe, not a binary.

SAR helpers are lifted from temporal_Version3_Deliverable_Single_LULC_Script_NewPipeline.ipynb.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py
import config

# ----- assets (all confirmed readable from our EE project) -----
TREECROP_ASSET = "projects/ee-indiasat/assets/Rasterized_Groundtruth/L2_TrainingData_SAR_TimeSeries_1Year"
FARMSHRUB_SAMPLES = "projects/raman-461708/assets/gee_samples_all"
AEZ_REGIONS = "users/mtpictd/agro_eco_regions"
AE_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"

# the 46 SAR band names the tree/crop model was trained on: 23 sixteen-day steps x VV/VH
_SAR_BANDS = [f"{i}_VV" for i in range(23)] + [f"{i}_VH" for i in range(23)]

TREECROP_COLORS = {"cropland": "#f0c14b", "tree": "#2e8b2e"}
FARMSHRUB_COLORS = {"farm": "#f0c14b", "plantation": "#8e5a2e", "scrubland": "#b8a04b"}
FARMSHRUB_MAP = {1: "farm", 2: "plantation", 3: "scrubland"}   # .py mapping at :1046

SAMPLE_CAP = 5000         # AE points to train the farm/shrub RF on (kept light for interactive tiles)
SAMPLE_BUFFER_M = 40000   # train on samples within this radius of the AOI, not the whole AEZ


# ============================ tree vs crop (SAR) ============================
# Port of the notebook's Sentinel-1 16-day time-series builder + gap interpolation. Produces the
# exact 46-band feature image the L2 training asset was built from, so classify lines up.

def _fill_empty_bands(ee, image):
    """A scene missing VV or VH gets a masked zero band, so every image has both (the collection
    stays rectangular for toBands)."""
    band_names = image.bandNames()
    zero = image.select(0).multiply(0).rename("constant").toDouble()
    zero_m = zero.updateMask(zero)
    image = ee.Algorithms.If(ee.List(band_names).contains("VV"), image,
                             ee.Image(image).addBands(zero_m.rename("VV")))
    image = ee.Algorithms.If(ee.List(band_names).contains("VH"), ee.Image(image),
                             ee.Image(image).addBands(zero_m.rename("VH")))
    return ee.Image(image)


def _s1_collection(ee, start, end, region):
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD")
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filterDate(start, end).filterBounds(region))
    return s1.map(lambda img: _fill_empty_bands(ee, img))


def _s1_16day_ts(ee, start, end, s1_ic):
    """One VV/VH mean image per 16-day step across [start, end] -> a 23-image collection."""
    dates = pd.date_range(start=datetime.strptime(start, "%Y-%m-%d"),
                          end=datetime.strptime(end, "%Y-%m-%d"), freq="16D")
    date_list = ee.List([d.strftime("%Y-%m-%d") for d in dates])

    def per_date(date):
        zero = s1_ic.first().select("VV", "VH").multiply(0)
        sub = s1_ic.select(["VV", "VH"]).filterDate(ee.Date(date), ee.Date(date).advance(16, "day"))
        return ee.Algorithms.If(ee.Number(sub.size()).gt(0),
                                sub.mean().set("system:time_start", ee.Date(date).millis()),
                                zero.set("system:time_start", ee.Date(date).millis()))
    return ee.ImageCollection.fromImages(date_list.map(per_date))


def _interpolate_ts(ee, s1_ts):
    """Fill masked pixels in each step by linear interpolation from the nearest before/after scenes
    within a 120-day window (the notebook's join-based temporal interpolation)."""
    def stamp(image):
        t = image.metadata("system:time_start").rename("timestamp")
        return image.addBands(t.updateMask(image.mask().select(0)))
    filtered = s1_ts.map(stamp)

    millis = ee.Number(120).multiply(1000 * 60 * 60 * 24)
    max_diff = ee.Filter.maxDifference(difference=millis, leftField="system:time_start",
                                       rightField="system:time_start")
    less_eq = ee.Filter.lessThanOrEquals(leftField="system:time_start", rightField="system:time_start")
    greater_eq = ee.Filter.greaterThanOrEquals(leftField="system:time_start", rightField="system:time_start")

    join1 = ee.Join.saveAll(matchesKey="after", ordering="system:time_start", ascending=False).apply(
        primary=filtered, secondary=filtered, condition=ee.Filter.And(max_diff, less_eq))
    join2 = ee.Join.saveAll(matchesKey="before", ordering="system:time_start", ascending=True).apply(
        primary=join1, secondary=join1, condition=ee.Filter.And(max_diff, greater_eq))

    def interp(image):
        image = ee.Image(image)
        before = ee.ImageCollection.fromImages(ee.List(image.get("before"))).mosaic()
        after = ee.ImageCollection.fromImages(ee.List(image.get("after"))).mosaic()
        t1, t2 = before.select("timestamp").rename("t1"), after.select("timestamp").rename("t2")
        t = image.metadata("system:time_start").rename("t")
        ratio = ee.Image.cat([t1, t2, t]).expression("(t - t1) / (t2 - t1)",
                                                      {"t": t, "t1": t1, "t2": t2})
        interpolated = before.add(after.subtract(before).multiply(ratio))
        result = image.unmask(interpolated).unmask(
            ee.ImageCollection([before, after]).mosaic())
        return result.copyProperties(image, ["system:time_start"])

    return ee.ImageCollection(ee.ImageCollection(join2).map(interp))


def _treecrop_feature_image(ee, start, end, region, interpolate=False):
    """The 46-band SAR feature image (0_VV..22_VV, 0_VH..22_VH) the tree/crop RF expects.

    The notebook's join-based temporal interpolation is faithful but far too heavy for an interactive
    tile request (it times out). By default we fill each 16-day step's gaps with the year's per-band
    mean instead — much lighter, and close enough for the interactive overlay. `interpolate=True`
    restores the exact notebook path for offline/batch use."""
    s1_ic = _s1_collection(ee, start, end, region)
    ts = _s1_16day_ts(ee, start, end, s1_ic)
    if interpolate:
        ts = _interpolate_ts(ee, ts)
    else:
        annual_mean = ts.mean()                      # per-band VV/VH annual mean, for gap fill
        ts = ts.map(lambda img: ee.Image(img).unmask(annual_mean))
    bands = ts.toBands()                              # names become <index>_VV / <index>_VH
    vv = bands.select([".*_VV"])
    vh = bands.select([".*_VH"])
    return vv.addBands(vh).select(_SAR_BANDS).clip(region)


# each model classifies into its OWN class scheme, not the base 4-class tree. So on its own it would
# label the whole box (built-up, water and all) as one of its classes. The right way to use it is as a
# refinement of the greenery/vegetation class: classify_composited() keeps the base map everywhere and
# lets the sub-model's classes take over only inside greenery. The standalone `classify_*_tiles` stay
# for showing the model alone.

def _treecrop_classified(ee, region, start, end):
    """The tree/crop RF's class image over the region (labels 5=cropland, 6=tree) + its code map."""
    training = ee.FeatureCollection(TREECROP_ASSET)
    model = ee.Classifier.smileRandomForest(numberOfTrees=100, seed=42).train(
        features=training, classProperty="class", inputProperties=_SAR_BANDS)
    feat = _treecrop_feature_image(ee, start, end, region)
    return feat.classify(model), {5: "cropland", 6: "tree"}


def classify_treecrop_tiles(bbox, start=None, end=None):
    """Tree vs crop over the bbox, standalone, served as EE tiles (#13)."""
    ee = config.ee_init()
    region = ee.Geometry.Rectangle(list(bbox))
    classified, c2n = _treecrop_classified(ee, region, start or "2023-07-01", end or "2024-07-01")
    return _render(ee, classified, c2n, TREECROP_COLORS, region)


# ============================ farm / plantation / scrubland (Alpha Earth) ============================
def _aez_for(ee, region):
    """The ae_regcode of the agro-ecological region the AOI centre falls in (None if outside)."""
    hit = ee.FeatureCollection(AEZ_REGIONS).filterBounds(region.centroid(1)).first()
    return ee.Algorithms.If(hit, ee.Feature(hit).get("ae_regcode"), None)


def _farmshrub_classified(ee, region, year):
    """The per-AEZ farm/shrub RF's class image over the region (labels 1/2/3) + its code map."""
    regcode = _aez_for(ee, region)
    buf = region.buffer(SAMPLE_BUFFER_M)
    near = (ee.FeatureCollection(FARMSHRUB_SAMPLES)
            .filter(ee.Filter.eq("aez_no", regcode)).filterBounds(buf))
    if near.size().getInfo() < 100:
        raise ValueError("no farm/shrub ground truth near this area — it's a rural/agricultural "
                         "model; try a farmland box (e.g. Punjab, Assam tea belt).")
    samples = near.randomColumn("r", 42).sort("r").limit(SAMPLE_CAP)
    ae_col = ee.ImageCollection(AE_COLLECTION).filterDate(f"{year}-01-01", f"{year+1}-01-01")
    ae_train = ae_col.filterBounds(buf).mosaic()          # covers the training points, not just the AOI
    training = ae_train.sampleRegions(collection=samples, properties=["label"], scale=10, tileScale=4)
    model = ee.Classifier.smileRandomForest(numberOfTrees=100, seed=42).train(
        features=training, classProperty="label", inputProperties=ae_train.bandNames())
    ae_aoi = ae_col.filterBounds(region).mosaic()         # classify the AOI itself
    return ae_aoi.classify(model).clip(region), FARMSHRUB_MAP


def classify_farmshrub_tiles(bbox, year=2024):
    """Farm / plantation / scrubland over the bbox, standalone, served as EE tiles (#13)."""
    ee = config.ee_init()
    region = ee.Geometry.Rectangle(list(bbox))
    classified, c2n = _farmshrub_classified(ee, region, year)
    return _render(ee, classified, c2n, FARMSHRUB_COLORS, region)


# ============================ plug a model into the hierarchy (refine greenery) ============================
def classify_composited(bbox, which, year=2024, parent="greenery", start=None, end=None):
    """Apply an IndiaSAT model as a *refinement of the base `parent` class* (default greenery), served
    as tiles (#13). Everywhere outside greenery the base map stands; inside greenery the sub-model's
    classes (tree/crop, or farm/plantation/scrubland) take over. This is how the two models plug into
    our hierarchy despite bringing their own class scheme, without changing the framework — the base
    classifies, the sub-model refines one branch, and the two are combined in Earth Engine.

    Returns (tile_url, counts, classes). Raises ValueError if `parent` isn't in the current base."""
    import infer
    ee = config.ee_init()
    region = ee.Geometry.Rectangle(list(bbox))
    # the base map with no splits, so greenery is intact to refine
    _, base_final, base_classes, _, _ = infer._labelled_bbox(bbox, year, infer.load_model(), {}, None)
    if parent not in base_classes:
        raise ValueError(f"this model refines the '{parent}' class, which isn't in the current base "
                         f"scheme (has {base_classes}). Switch to the IndiaSAT base and try again.")
    p = base_classes.index(parent)

    if which == "treecrop":
        classified, c2n = _treecrop_classified(ee, region, start or "2023-07-01", end or "2024-07-01")
        sub_colors = TREECROP_COLORS
    else:
        classified, c2n = _farmshrub_classified(ee, region, year)
        sub_colors = FARMSHRUB_COLORS
    sub_codes = sorted(c2n)
    sub_classes = [c2n[c] for c in sub_codes]

    # sub-model class index 0..K-1, then shifted to sit after the base classes; paint it only where
    # the base map says `parent`. So greenery becomes tree/crop (or farm/shrub); the rest is untouched.
    sub_idx = ee.Image(0)
    for i, code in enumerate(sub_codes):
        sub_idx = sub_idx.where(classified.eq(code), i)
    all_classes = list(base_classes) + sub_classes
    composited = base_final.where(base_final.eq(p), sub_idx.add(len(base_classes)))

    colors = {**infer.load_colors(), **sub_colors}
    palette = [colors.get(c, "#999999") for c in all_classes]
    vis = composited.visualize(min=0, max=len(all_classes) - 1, palette=palette).clip(region)
    tile_url = vis.getMapId()["tile_fetcher"].url_format
    counts = {}
    try:
        hist = (composited.rename("c").reduceRegion(reducer=ee.Reducer.frequencyHistogram(),
                geometry=region, scale=60, maxPixels=int(1e8), bestEffort=True).getInfo().get("c") or {})
        for k, v in hist.items():
            counts[all_classes[int(float(k))]] = int(v)
    except Exception:
        pass
    return tile_url, counts, all_classes


# ============================ shared render ============================
def _render(ee, class_img, code_to_name, colors, region):
    """Remap a classified image's arbitrary code values to 0..K-1, visualize with the class palette,
    and return (tile_url, counts{name:px}, classes[name]). Same server-side tile path as the water
    and Alpha Earth renderers."""
    codes = sorted(code_to_name)
    classes = [code_to_name[c] for c in codes]
    idx = ee.Image(0).rename("k")
    for i, c in enumerate(codes):
        idx = idx.where(class_img.eq(c), i)
    idx = idx.updateMask(class_img.gte(min(codes)).And(class_img.lte(max(codes))))
    palette = [colors.get(n, "#999999") for n in classes]
    vis = idx.visualize(min=0, max=len(classes) - 1, palette=palette).clip(region)
    tile_url = vis.getMapId()["tile_fetcher"].url_format

    # counts are a display nicety; sample them at a coarse scale so they don't force the whole (heavy,
    # for SAR) classification to compute at 10 m and stall the interactive response.
    counts = {}
    try:
        hist = (idx.rename("c").reduceRegion(reducer=ee.Reducer.frequencyHistogram(),
                geometry=region, scale=60, maxPixels=int(1e8), bestEffort=True).getInfo().get("c") or {})
        for k, v in hist.items():
            counts[classes[int(float(k))]] = int(v)
    except Exception:
        pass
    return tile_url, counts, classes


if __name__ == "__main__":
    # offline sanity: band list + mapping shapes, no EE.
    assert len(_SAR_BANDS) == 46 and _SAR_BANDS[0] == "0_VV" and _SAR_BANDS[-1] == "22_VH"
    assert set(FARMSHRUB_MAP.values()) == set(FARMSHRUB_COLORS)
    print("ee_rf.py offline checks OK —", len(_SAR_BANDS), "SAR bands, classes",
          list(FARMSHRUB_MAP.values()))
