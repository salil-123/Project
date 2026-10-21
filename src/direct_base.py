"""Direct base maps: a base scheme drawn straight from its published Earth Engine map.

The classifier bases (IndiaSAT-4, WorldCover-7) are our own LinearSVC models on Alpha Earth, trained
on those labels. That is a lossy copy of the product, and it only exists to reach every year Alpha
Earth covers. Where the published map itself exists for the project's year, nothing needs to be
learned: the base is the published label, relabelled onto the scheme's class list. Splits, merges and
rules then work on it exactly as they do on a classifier base, because they only need "which base
class is this pixel".

  scheme         source                                              years (project year Y)
  dynamicworld   GOOGLE/DYNAMICWORLD/V1, label mode over Jan-Dec Y    2016 and later (no classifier at all)
  worldcover     ESA/WorldCover v100 / v200                           2020, 2021; other years use the classifier
  indiasat       CoRE Stack LULC v3, the map ending in June of Y      2018 to 2025; other years use the classifier

IndiaSAT's maps run July to June, so a project year Y shows the map `Y-1 -> Y` (a 2023 project shows
2022-23). That is also the year the acacia pipeline reads. Set `"direct": false` in active_base.json to
force the classifier everywhere.
"""
import numpy as np

SCHEMES = ("indiasat", "worldcover", "dynamicworld")

# ----------------------------------------------------------------------------- Dynamic World
# label band values 0..8, in this order
DW_CLASSES = [
    ("water",              "Water",              "#419bdf"),
    ("trees",              "Trees",              "#397d49"),
    ("grass",              "Grass",              "#88b053"),
    ("flooded_vegetation", "Flooded vegetation", "#7a87c6"),
    ("crops",              "Crops",              "#e49635"),
    ("shrub_and_scrub",    "Shrub and scrub",    "#dfc35a"),
    ("built",              "Built area",         "#c4281b"),
    ("bare",               "Bare ground",        "#a59b8f"),
    ("snow_and_ice",       "Snow and ice",       "#b39fe1"),
]
DW_ASSET = "GOOGLE/DYNAMICWORLD/V1"
DW_FIRST_YEAR = 2016                       # the archive starts mid-2015, so 2016 is its first full year

# ----------------------------------------------------------------------------- WorldCover
WC_YEARS = {2020: "ESA/WorldCover/v100", 2021: "ESA/WorldCover/v200"}
# WorldCover code -> the 7 classes of the WorldCover base (refine.WC_BASE). The four rare codes have
# no class of their own there, so they fold into the nearest one; the project's class list must not
# change with the year, or its splits would stop lining up.
WC_TO_CANON = {10: "tree", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built_up",
               60: "bare", 80: "water",
               70: "bare",          # snow and ice
               90: "grassland",     # herbaceous wetland
               95: "tree",          # mangroves
               100: "bare"}         # moss and lichen

# ----------------------------------------------------------------------------- IndiaSAT
INDIASAT_V3 = "projects/corestack-datasets/assets/datasets/LULC_v3_river_basin/pan_india_lulc_v3_{}_{}"
INDIASAT_MAP_YEARS = range(2017, 2025)     # first year of each hydrological year: 2017-18 .. 2024-25
# predicted_label -> the four Level-1 classes of the IndiaSAT base. 0 (no data) is left out and so
# comes back masked. Codes read off the published maps: 1 built-up, 2/3/4 water by season, 7 barren;
# 5, 6, 8-12 (and 13 in v4) are all vegetation.
INDIASAT_TO_L1 = {1: "built_up", 2: "water", 3: "water", 4: "water", 7: "barren",
                  5: "greenery", 6: "greenery", 8: "greenery", 9: "greenery", 10: "greenery",
                  11: "greenery", 12: "greenery", 13: "greenery"}


def available(scheme, year):
    """True when `scheme` can be drawn straight from its published map for this project year."""
    year = int(year)
    if scheme == "dynamicworld":
        return year >= DW_FIRST_YEAR
    if scheme == "worldcover":
        return year in WC_YEARS
    if scheme == "indiasat":
        return (year - 1) in INDIASAT_MAP_YEARS
    return False


def source_label(scheme, year):
    """A short line saying which map the base is, for the UI and the run record. None = classifier."""
    year = int(year)
    if not available(scheme, year):
        return None
    if scheme == "dynamicworld":
        return f"Dynamic World {year}"
    if scheme == "worldcover":
        return f"ESA WorldCover {year}"
    return f"IndiaSAT {year - 1}-{str(year)[2:]}"


def source_ref(scheme, year):
    """The Earth Engine asset behind that map (for provenance)."""
    year = int(year)
    if scheme == "dynamicworld":
        return DW_ASSET
    if scheme == "worldcover":
        return WC_YEARS[year]
    return INDIASAT_V3.format(year - 1, year)


def scheme_classes(scheme):
    """(id, display name, colour) per class for a scheme with no classifier behind it."""
    if scheme == "dynamicworld":
        return list(DW_CLASSES)
    raise ValueError(f"{scheme} has a classifier; its classes come from the model")


def _raw_image(ee, scheme, region, year):
    """(single-band image of the published codes, {code: class id}) for the project year."""
    year = int(year)
    if scheme == "dynamicworld":
        img = (ee.ImageCollection(DW_ASSET).filterDate(f"{year}-01-01", f"{year + 1}-01-01")
               .filterBounds(region).select("label").mode())
        return img, {i: c for i, (c, _, _) in enumerate(DW_CLASSES)}
    if scheme == "worldcover":
        return ee.ImageCollection(WC_YEARS[year]).first().select("Map"), WC_TO_CANON
    return ee.Image(INDIASAT_V3.format(year - 1, year)).select("predicted_label"), INDIASAT_TO_L1


def index_image(ee, scheme, region, year, classes):
    """The published map as a class-index image, indices into `classes` (the base's class order, so
    it drops in where the classifier's label image went). Codes with no class stay masked."""
    img, code_to_class = _raw_image(ee, scheme, region, year)
    pos = {c: i for i, c in enumerate(classes)}
    keep = [(code, pos[cls]) for code, cls in code_to_class.items() if cls in pos]
    return img.remap([k for k, _ in keep], [v for _, v in keep]).rename("idx")


def sample_labels(ee, pts, bbox, scheme, year, classes):
    """The published class at each (lon, lat) point, as strings ('nodata' where the map has none).
    The point-grid renders (Tessera, non-linear splits) call this where the tiles path would use
    `index_image`."""
    w, s, e, n = bbox
    region = ee.Geometry.Rectangle([w, s, e, n])
    idx = index_image(ee, scheme, region, year, classes)
    feats = [ee.Feature(ee.Geometry.Point([x, y]), {"i": i}) for i, (x, y) in enumerate(pts)]
    got = idx.sampleRegions(collection=ee.FeatureCollection(feats), scale=10).getInfo()["features"]
    out = np.array(["nodata"] * len(pts), dtype=object)
    for f in got:
        p = f["properties"]
        k = p.get("idx")
        if k is not None and 0 <= int(k) < len(classes):
            out[p["i"]] = classes[int(k)]
    return out


# ----------------------------------------------------------------------------- bundle stand-in
class _Step:
    pass


class DirectModel:
    """What a base 'model' is when there is no classifier (Dynamic World). It carries only the class
    list, in the shape infer._svc_steps expects, so everything that asks the base for its classes
    works. Asking it to predict is a bug: the base is the published map, never a prediction."""

    def __init__(self, classes):
        sc, clf = _Step(), _Step()
        sc.mean_, sc.scale_ = np.zeros(1), np.ones(1)
        clf.classes_ = np.array(list(classes), dtype=object)
        clf.coef_ = np.zeros((len(classes), 1))
        clf.intercept_ = np.zeros(len(classes))
        self.named_steps = {"scale": sc, "clf": clf}

    def predict(self, X):
        raise RuntimeError("this base is a published map, not a classifier; sample it instead")


def stub_bundle(scheme):
    classes = [c for c, _, _ in scheme_classes(scheme)]
    return {"model": DirectModel(classes), "classes": classes, "features": "direct", "scheme": scheme}
