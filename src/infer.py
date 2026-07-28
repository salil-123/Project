"""Inference for the Phase 5 UI: classify a bounding box with the trained model.

Samples Alpha Earth (server-side in GEE) on a grid over the bbox, predicts each
cell with the saved pooled model, and returns a tidy dataframe the UI can draw.
"""
import math
import os
import joblib
import numpy as np
import pandas as pd
import config
import hierarchy
import merges
import rules

# Alpha Earth band names, in the model's feature order (A00 == ae_000, ... A63)
BANDS = [f"A{k:02d}" for k in range(64)]

# fallback colours for classes that don't live in the hierarchy tree
CLASS_COLORS = {
    "greenery": "#2e8b2e",
    "water":    "#1e88e5",
    "built_up": "#d7301f",
    "barren":   "#c2a05a",
    "other":    "#8e44ad",
    "nodata":   "#999999",
}

MODEL_PATH = "data/model_pooled.joblib"                     # realistic mode: AE + WorldCover
SOFTVOTE_PATH = "data/model_softvote_reconciled.joblib"     # detailed mode: prior-aware AE + Tessera
REFINE_DIR = "data/refine"
ACTIVE_BASE_PATH = "data/active_base.json"                  # which base scheme is live (#5)


def active_base():
    """The live base scheme + its model path (#5). Defaults to the IndiaSAT pooled model."""
    import json
    if os.path.exists(ACTIVE_BASE_PATH):
        try:
            return json.load(open(ACTIVE_BASE_PATH))
        except Exception:
            pass
    return {"scheme": "indiasat", "model_path": MODEL_PATH}


def set_active_base(scheme, model_path):
    import json
    json.dump({"scheme": scheme, "model_path": model_path}, open(ACTIVE_BASE_PATH, "w"), indent=2)


def load_model(path: str = None):
    """Load the live base model. With no path, follows the active base scheme (#5)."""
    return joblib.load(path or active_base().get("model_path", MODEL_PATH))


def load_softvote(path: str = SOFTVOTE_PATH):
    return joblib.load(path)


def load_colors():
    """Display colours for the classes actually predicted: the tree's leaves (which the
    refinement step relabels down to) plus the always-present 'other'/'nodata'."""
    colors = {"other": CLASS_COLORS["other"], "nodata": CLASS_COLORS["nodata"]}
    try:
        tree = hierarchy.load()
        for cls in hierarchy.leaves(tree):
            colors[cls] = tree[cls].get("color") or CLASS_COLORS.get(cls, "#999999")
    except Exception:
        colors.update(CLASS_COLORS)  # tree missing -> fall back to the flat base colours
    colors.update(merges.target_colors())   # merge targets (#9) get their own colour too
    return colors


def load_refinements():
    """parent class -> split bundle, for each tree node that resolves its own children.

    Two kinds of resolver relabel a base prediction into its children (e.g. greenery ->
    crops/trees/shrubs): a trained classifier (`classifier` -> a joblib) or a *rule* (#12,
    a `rule` block on the node -> an expression over index images). Trained AE splits reuse the
    AE matrix already sampled; a rule is evaluated live in EE. Both carry a `classes` list so the
    rest of the pipeline treats them uniformly (see `_bundle_classes`)."""
    out = {}
    try:
        tree = hierarchy.load()
    except Exception:
        return out
    for cls, node in tree.items():
        if node.get("classifier"):
            path = os.path.join(REFINE_DIR, f"{node['classifier']}.joblib")
            if os.path.exists(path):
                out[cls] = joblib.load(path)
        elif node.get("rule"):                          # a rule split (#12): no joblib, evaluated in EE
            out[cls] = {"features": "rule", "rule": node["rule"],
                        "classes": rules.rule_classes(node["rule"])}
    return out


def _bundle_classes(bundle):
    """The child classes a refinement bundle resolves into, in order. Every bundle carries a
    `classes` list (rule, linear, or a non-linear Tessera model #1), so we read that — it means the
    compositing code never has to crack open the estimator, and a Random Forest (no coef_) works
    the same as a LinearSVC. Falls back to the estimator's classes_ for any old bundle without it."""
    if bundle.get("classes") is not None:
        return list(bundle["classes"])
    return list(_svc_steps(bundle)[1].classes_)


def _refine_order(refinements):
    """Refinement parents shallow-first, so one pass cascades down the tree: greenery
    relabels to crops, then crops (if split) relabels further, and so on."""
    try:
        tree = hierarchy.load()
        return sorted(refinements, key=lambda c: len(hierarchy.path_to(tree, c)) if c in tree else 0)
    except Exception:
        return list(refinements)


def _apply_refinements(preds, Xae, valid, refinements, Xte=None, te_valid=None, rule_labels=None):
    """In-place: walk the tree of resolvers root->leaf, each node refining its own label into a
    child. Depth ordering makes a single pass recurse to any depth.

    Each split resolves on its own signal: Alpha Earth (`Xae`) normally, Tessera (`Xte`) for a
    `features=='tessera'` split (#16), or — for a rule split (#12) — a per-point class already
    sampled from the rule's EE index image into `rule_labels[parent]`. A Tessera split is skipped
    when Tessera wasn't sampled here (`Xte is None`); a rule split when its labels aren't present."""
    for parent in _refine_order(refinements):
        bundle = refinements[parent]
        kind = bundle.get("features")
        if kind == "rule":
            if not rule_labels or parent not in rule_labels:
                continue
            sel = (preds == parent)
            if sel.any():
                preds[sel] = rule_labels[parent][sel]
            continue
        is_te = kind == "tessera"
        if is_te and Xte is None:
            continue                                   # can't apply a Tessera split without te features
        ok = te_valid if is_te else valid
        sel = (preds == parent) if ok is None else (ok & (preds == parent))
        if sel.any():
            preds[sel] = bundle["model"].predict((Xte if is_te else Xae)[sel])
    return preds


def _sample_rule_labels(pts, bbox, year, refinements):
    """For each rule refinement (#12), evaluate its EE index rule and sample the resulting class
    at every grid point -> {parent: array of class strings per point}. This is how a rule split
    shows up on the point-grid render (detailed / Tessera mode); the crisp tile path evaluates the
    same rule directly in EE instead."""
    rule_parents = [p for p, b in refinements.items() if b.get("features") == "rule"]
    if not rule_parents:
        return {}
    ee = config.ee_init()
    w, s, e, nth = bbox
    region = ee.Geometry.Rectangle([w, s, e, nth])
    feats = [ee.Feature(ee.Geometry.Point([x, y]), {"i": i}) for i, (x, y) in enumerate(pts)]
    fc = ee.FeatureCollection(feats)
    out = {}
    for parent in rule_parents:
        idx_img, classes = rules.rule_label_ee(ee, region, year, refinements[parent]["rule"])
        samp = idx_img.rename("k").sampleRegions(collection=fc, scale=10).getInfo()["features"]
        arr = np.array([classes[0]] * len(pts), dtype=object)
        for f in samp:
            p = f["properties"]
            ci = int(p.get("k", 0))
            if 0 <= ci < len(classes):
                arr[p["i"]] = classes[ci]
        out[parent] = arr
    return out


def _apply_merges(preds):
    """In-place relabel of the final per-cell labels per the merge rules (#9). Runs after the
    refinements, so it sees the leaf each pixel landed on and collapses chosen leaves into a new
    class. Pure membership test — merge is just relabelling."""
    s2t = merges.source_to_target()
    if s2t:
        for i, p in enumerate(preds):
            if p in s2t:
                preds[i] = s2t[p]
    return preds


# ----------------- server-side 10 m raster classification (Realistic mode) -----------------
# Both deployed models are StandardScaler -> LinearSVC, i.e. linear, so we reproduce them
# exactly as band math on the Alpha Earth image inside Earth Engine and classify at native
# 10 m. No per-point getInfo, no payload blow-up: the whole area is one PNG.

def _alpha_image(ee, bbox, year):
    """The year's Alpha Earth mosaic over the bbox, as a 64-band (A00..A63) image."""
    w, s, e, nth = bbox
    region = ee.Geometry.Rectangle([w, s, e, nth])
    img = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
           .filterDate(f"{year}-01-01", f"{year+1}-01-01")
           .filterBounds(region).mosaic())
    return img.select(BANDS), region


def _svc_steps(bundle):
    """The scaler + the linear estimator from a bundle's pipeline, found by attribute rather than
    by step name — so the band-math path works for any linear winner of the bake-off (#17):
    LinearSVC / LogisticRegression / RidgeClassifier all expose coef_ / intercept_."""
    pipe = bundle["model"]
    steps = list(pipe.named_steps.values())
    sc = next(s for s in steps if hasattr(s, "mean_") and hasattr(s, "scale_"))
    clf = next(s for s in steps if hasattr(s, "coef_") and hasattr(s, "intercept_"))
    return sc, clf


# estimators that can't be written as EE band math, so their splits ride the point grid, not tiles.
NONLINEAR_ALGOS = {"randomforest", "xgboost"}


def _is_ae(bundle):
    """A bundle that runs on the 64-d Alpha Earth features (so it can be expressed as band math on
    the AE image). Split bundles tag features "ae"/"te"; base bundles carry the AE column list."""
    feat = bundle.get("features")
    return feat == "ae" or isinstance(feat, list)


def _is_nonlinear(bundle):
    """A split whose estimator has no coef_/intercept_ (Random Forest / XGBoost, #7 wk10), so it
    can't be replayed as band math. Trust the stored algo tag when present; fall back to a coef_
    probe only for older AE bundles that predate the tag. Rule bundles have no estimator."""
    algo = bundle.get("algo")
    if algo:
        return algo in NONLINEAR_ALGOS
    if bundle.get("features") != "ae":
        return False
    try:
        _svc_steps(bundle)          # linear if it exposes coef_/intercept_
        return False
    except Exception:
        return True


def _linear_label(ee, feat_img, bundle, band_names):
    """Class-index image (0..K-1, order = svc.classes_) for a linear bundle over any feature image.

    score_k = ((x - mean)/scale) . coef_k + intercept_k. For >=3 classes it's one-vs-rest ->
    argmax; for 2 classes a single hyperplane (coef_ is (1,d)) -> classes_[1] when the score is
    positive, else classes_[0]. `band_names` are the feature bands in the model's fitted order —
    Alpha Earth's A00..A63 for a base/split model, or the Sentinel feature bands for the water
    model (#5). Same maths either way, since every deployed model is linear."""
    sc, svc = _svc_steps(bundle)
    mean = ee.Image.constant(sc.mean_.tolist()).rename(band_names)
    scale = ee.Image.constant(sc.scale_.tolist()).rename(band_names)
    z = feat_img.subtract(mean).divide(scale)

    # normalise to 2-D coef / 1-D intercept — RidgeClassifier's binary coef_ is 1-D, while
    # LinearSVC/LogReg give (1,d); atleast_2d makes the branching below work for any linear winner (#17).
    coefs = np.atleast_2d(svc.coef_)
    inters = np.atleast_1d(svc.intercept_)

    def score(k):
        coef = ee.Image.constant(coefs[k].tolist()).rename(band_names)
        return z.multiply(coef).reduce(ee.Reducer.sum()).add(float(inters[k]))

    if coefs.shape[0] == 1:            # binary: one score, sign picks the class
        return score(0).gt(0)
    scores = ee.Image.cat([score(k).rename(f"c{k}") for k in range(coefs.shape[0])])
    return scores.toArray().arrayArgmax().arrayGet([0])


def _ee_label(ee, bands_img, bundle):
    """Alpha Earth linear split as a class-index image — the AE-band caller of `_linear_label`."""
    return _linear_label(ee, bands_img, bundle, BANDS)


def _leaf_classes(model_bundle, refinements):
    """The classes that actually survive to the map: walk base classes down through every
    split to the leaves (depth-first). A class is a leaf unless it has a classifier."""
    def leaves_of(cls):
        if cls in refinements:
            out = []
            for ch in _bundle_classes(refinements[cls]):
                out.extend(leaves_of(ch))
            return out
        return [cls]
    out = []
    for c in _svc_steps(model_bundle)[1].classes_:
        out.extend(leaves_of(c))
    return out


def _refine_idx(ee, bands_img, region, year, bundle):
    """The child-index image for one refinement bundle, whichever kind it is: a linear split
    replays as AE band math (`_ee_label`), a rule split evaluates its index expressions in EE
    (`rules.rule_label_ee`). Both return an image whose values index into `_bundle_classes`."""
    if bundle.get("features") == "rule":
        return rules.rule_label_ee(ee, region, year, bundle["rule"])[0]
    return _ee_label(ee, bands_img, bundle)


def _final_label(ee, bands_img, region, year, model_bundle, refinements):
    """Recursive label image: pixel values index into the returned leaf_classes list.

    Mirrors _apply_refinements but in EE. Each node classifies among its children; where a child
    has its own resolver (a trained split or a rule) we descend into it, all the way to a leaf.
    Same logic whether the split is one level deep (greenery) or many (greenery->crops->...), and
    whether it's a model or a rule (#12). `region`/`year` are threaded through for the rule index
    images."""
    leaf_classes = _leaf_classes(model_bundle, refinements)
    code = {c: i for i, c in enumerate(leaf_classes)}

    def sub(cls):
        """Leaf-code image for the subtree under class `cls`."""
        if cls not in refinements:
            return ee.Image.constant(code[cls])
        idx = _refine_idx(ee, bands_img, region, year, refinements[cls])
        children = _bundle_classes(refinements[cls])
        img = sub(children[0])
        for i, ch in enumerate(children[1:], start=1):
            img = img.where(idx.eq(i), sub(ch))
        return img

    base_idx = _ee_label(ee, bands_img, model_bundle)
    base_children = list(_svc_steps(model_bundle)[1].classes_)
    final = sub(base_children[0])
    for i, ch in enumerate(base_children[1:], start=1):
        final = final.where(base_idx.eq(i), sub(ch))
    return final.updateMask(base_idx.mask()), leaf_classes


def _merge_ee(ee, final, leaf_classes):
    """Apply the merge rules (#9) to the EE label image: collapse each rule's source leaves into
    its target. The label image holds leaf-code indices, so this is a code `remap` plus a new
    display-class list (sources replaced by their target). No-op when there are no rules."""
    s2t = merges.source_to_target()
    if not s2t:
        return final, leaf_classes
    display = []
    for c in leaf_classes:                       # sources fold into their target, deduped, in order
        nc = s2t.get(c, c)
        if nc not in display:
            display.append(nc)
    code = {c: i for i, c in enumerate(display)}
    from_codes = list(range(len(leaf_classes)))
    to_codes = [code[s2t.get(c, c)] for c in leaf_classes]
    return final.remap(from_codes, to_codes), display


# The Realistic-mode raster path: both renderers (a capped PNG and live EE tiles) build the
# exact same coloured label image and class histogram — only the final "how do we serve it"
# step differs. These helpers hold that shared body so the two stay in lockstep.

def _apply_ee_rf(ee, final, final_classes, region, year):
    """Composite any hierarchy node marked with an IndiaSAT ee_rf model into the label image (#13):
    that class becomes the model's classes, server-side. Lazy import of ee_rf avoids a module cycle.
    Returns (final, classes, extra_colors)."""
    try:
        tree = hierarchy.load()
        nodes = [(cls, n["ee_rf"]) for cls, n in tree.items() if n.get("ee_rf")]
    except Exception:
        nodes = []
    if not nodes:
        return final, final_classes, {}
    import ee_rf as _eerf
    extra = {}
    for cls, which in nodes:
        final, final_classes = _eerf.composite_into(ee, final, final_classes, region, cls, which, year)
        extra.update(_eerf.model_colors(which))
    return final, final_classes, extra


def _labelled_bbox(bbox, year, model_bundle, refinements, colors):
    """The coloured label image for a bbox: base map + composited splits + merge relabels,
    visualized with the leaf palette. Returns (ee, final_code_img, final_classes, region, vis)."""
    ee = config.ee_init()
    if model_bundle is None:
        model_bundle = load_model()
    if refinements is None:
        refinements = load_refinements()
    # the crisp tile/PNG path runs in Earth Engine, so it can carry LINEAR AE band-math splits AND
    # rule splits (#12, evaluated as EE index math). A Tessera split (#16) can't ride it (its
    # features live in downloaded tiles), and neither can a non-linear AE split (Random Forest, #7)
    # since it isn't band math. Drop both; those classes show their parent label here — the backend
    # renders them on the point grid instead.
    refinements = {k: v for k, v in refinements.items()
                   if (_is_ae(v) and not _is_nonlinear(v)) or v.get("features") == "rule"}

    bands_img, region = _alpha_image(ee, bbox, year)
    final, final_classes = _final_label(ee, bands_img, region, year, model_bundle, refinements)
    final, final_classes = _merge_ee(ee, final, final_classes)
    final, final_classes, ee_rf_colors = _apply_ee_rf(ee, final, final_classes, region, year)

    colors = {**(colors or load_colors()), **ee_rf_colors}
    palette = [colors.get(c, "#999999") for c in final_classes]
    # clip to the AOI so edge tiles don't paint classification outside the box the user drew (#3);
    # pixels beyond `region` come back masked -> transparent in both the tile and PNG renderers.
    vis = final.visualize(min=0, max=len(final_classes) - 1, palette=palette).clip(region)
    return ee, final, final_classes, region, vis


def _class_counts(ee, final, region, final_classes):
    """Per-class pixel histogram over the region (a display nicety; never fails the classify)."""
    counts = {}
    try:
        hist = (final.rename("c").reduceRegion(
            reducer=ee.Reducer.frequencyHistogram(), geometry=region, scale=10,
            maxPixels=int(1e9), bestEffort=True).getInfo().get("c") or {})
        for k, v in hist.items():
            ci = int(float(k))
            if 0 <= ci < len(final_classes):
                counts[final_classes[ci]] = int(v)
    except Exception:
        pass
    return counts


def classify_bbox_raster(bbox, year: int = 2024, model_bundle=None, refinements=None,
                         max_dim: int = 2048, colors=None):
    """Classify the whole bbox server-side at 10 m; return (png_url, counts).

    A single label image (base map + composited splits + merge relabels), coloured and served as
    a getThumbURL PNG plus a class histogram. Masked (no-coverage) pixels stay transparent.
    `colors` overrides the class->hex palette (defaults to the tree's leaf colours)."""
    ee, final, final_classes, region, vis = _labelled_bbox(bbox, year, model_bundle, refinements, colors)

    # dimensions sized for ~10 m/px until the box is large, then capped (payload bound)
    w, s, e, nth = bbox
    width_m = (e - w) * 111320 * math.cos(math.radians((s + nth) / 2))
    height_m = (nth - s) * 111320
    dim = int(min(max_dim, max(1, round(max(width_m, height_m) / 10))))
    url = vis.getThumbURL({"region": region, "dimensions": dim, "format": "png"})
    return url, _class_counts(ee, final, region, final_classes)


def classify_bbox_tiles(bbox, year: int = 2024, model_bundle=None, refinements=None, colors=None):
    """Same server-side 10 m classification, but served as Earth Engine map TILES (an XYZ url
    template) instead of a capped PNG (#11). EE renders each 256x256 tile on demand, so the
    overlay stays crisp at any zoom and any area size, with nothing downloaded to us. The model
    is linear -> it replays as band math in EE, so this is just `getMapId` on the same label
    image. Returns (tile_url_template, counts)."""
    ee, final, final_classes, region, vis = _labelled_bbox(bbox, year, model_bundle, refinements, colors)
    tile_url = vis.getMapId()["tile_fetcher"].url_format    # EE serves the tiles; we hand Leaflet the url
    return tile_url, _class_counts(ee, final, region, final_classes)


def classify_bbox_geotiff(bbox, year: int = 2024, model_bundle=None, refinements=None, colors=None):
    """A downloadable GeoTIFF of the classified bbox (#24): the *integer* label image at 10 m.

    We export `final` (the class-code raster, not the RGB `vis`) so the .tif carries one band of
    class indices — the `classes` list is the code->name legend. EE builds it server-side and hands
    back a short-lived URL the browser fetches. `getDownloadURL` is synchronous and size-capped, so
    this is meant for a bounded AOI (the box on screen), matching the interactive 'download the
    output at the end' use. Returns (url, classes)."""
    ee, final, final_classes, region, _vis = _labelled_bbox(bbox, year, model_bundle, refinements, colors)
    url = final.toInt().getDownloadURL({"region": region, "scale": 10,
                                        "format": "GEO_TIFF", "crs": "EPSG:4326"})
    return url, final_classes


# ----------------- vectorize a class into cleaned segments (#4 wk10) -----------------
def segment_class(bbox, year: int = 2024, cls: str = "mining", min_area_ha: float = 0.5,
                  model_bundle=None, refinements=None):
    """Turn one class of the classified map into discrete, cleaned polygon segments (#4 wk10).

    Runs the same Earth-Engine label image the tile map uses, isolates `cls`, cleans it (a focal
    mode drops lone speckle pixels and closes pin-holes), then reduceToVectors -> polygons and drops
    anything under `min_area_ha`. This gives mining *objects* (segments) from the existing pixel
    classifier — a pragmatic segmentation that rides the EE path, no separate model needed. Returns
    (GeoJSON FeatureCollection, summary). Raises ValueError if `cls` isn't on the current map."""
    ee, final, final_classes, region, _vis = _labelled_bbox(bbox, year, model_bundle,
                                                            refinements, None)
    if cls not in final_classes:
        raise ValueError(f"class {cls!r} isn't on the current map (has: {final_classes}). "
                         "Add/train the split that produces it first.")
    code = final_classes.index(cls)
    # 1 where this class, 0 elsewhere; a 3x3 focal mode removes single-pixel specks and fills holes
    binary = final.eq(code).unmask(0)
    cleaned = binary.focalMode(radius=1, kernelType="square", units="pixels").selfMask()
    vectors = cleaned.reduceToVectors(geometry=region, scale=10, geometryType="polygon",
                                      eightConnected=True, labelProperty="v",
                                      maxPixels=int(1e9), bestEffort=True)
    vectors = vectors.map(lambda f: f.set("area_ha", f.geometry().area(maxError=1).divide(1e4)))
    vectors = vectors.filter(ee.Filter.gte("area_ha", min_area_ha))
    fc = vectors.getInfo()
    feats = fc.get("features", [])
    for f in feats:
        f["properties"] = {"class": cls, "area_ha": round(f["properties"].get("area_ha", 0.0), 3)}
    total = sum(f["properties"]["area_ha"] for f in feats)
    summary = {"class": cls, "n_segments": len(feats), "total_area_ha": round(total, 2),
               "min_area_ha": min_area_ha}
    return {"type": "FeatureCollection", "features": feats}, summary


# ----------------- per-fortnight water (raw Sentinel, linear -> band math) (#5, #7) -----------------
WATER_FORTNIGHT_PATH = "data/refine/water_fortnight.joblib"
_WATER_COLORS = {"water": "#1e88e5", "non_water": "#c2a05a"}


def classify_water_tiles(bbox, date, model_bundle=None):
    """Water vs non-water for one fortnight, served as EE map tiles (#5/#7).

    Builds the raw Sentinel-1/2 feature composite around `date` (YYYY-MM-DD) and replays the
    offline-trained *linear* water model as band math over it — the same interactive, no-download
    path Alpha Earth uses, which is what keeps this inside EE's memory budget (the flood pipeline
    had to go batch precisely because it sampled interactively). Returns (tile_url, counts)."""
    import sentinel
    ee = config.ee_init()
    if model_bundle is None:
        model_bundle = joblib.load(WATER_FORTNIGHT_PATH)
    w, s, e, nth = bbox
    region = ee.Geometry.Rectangle([w, s, e, nth])
    feat = sentinel.feature_image(ee, region, date)
    bands = model_bundle["feature_bands"]
    classes = list(_svc_steps(model_bundle)[1].classes_)
    idx = _linear_label(ee, feat, model_bundle, bands)
    palette = [_WATER_COLORS.get(c, "#999999") for c in classes]
    vis = idx.visualize(min=0, max=len(classes) - 1, palette=palette).clip(region)
    tile_url = vis.getMapId()["tile_fetcher"].url_format
    return tile_url, _class_counts(ee, idx.rename("c"), region, classes)


def water_frequency_tiles(bbox, year=2024, n=24, model_bundle=None):
    """How many fortnights each pixel held water over a year (#11 wk10), served as EE tiles.

    Runs the linear water band-math on ~`n` evenly-spaced fortnight composites across `year` and sums
    the water masks into a per-pixel count (0..n). This is the layer that makes water seasonality
    legible for LULC integration: a perennial water body scores near n, a monsoon-only pond scores
    low. All server-side, no download. Returns (tile_url, stats)."""
    import sentinel
    ee = config.ee_init()
    if model_bundle is None:
        model_bundle = joblib.load(WATER_FORTNIGHT_PATH)
    w, s, e, nth = bbox
    region = ee.Geometry.Rectangle([w, s, e, nth])
    bands = model_bundle["feature_bands"]
    classes = list(_svc_steps(model_bundle)[1].classes_)
    water_code = classes.index("water") if "water" in classes else 1

    # evenly spaced fortnight centres across the year
    step = max(1, 365 // n)
    masks = []
    for d in range(0, 365, step):
        date = ee.Date(f"{year}-01-01").advance(d, "day")
        feat = sentinel.feature_image(ee, region, date.format("YYYY-MM-dd"))
        idx = _linear_label(ee, feat, model_bundle, bands)     # 0/1 per the water model
        masks.append(idx.eq(water_code).unmask(0).rename("w"))
    count = ee.ImageCollection(masks).sum().rename("count").clip(region)

    n_used = len(masks)
    # pale -> deep blue, a touch more contrast: lighter low end, darker high end, punchier mids
    palette = ["eff6ff", "9ecae1", "3182bd", "08519c", "05224f"]
    vis = count.visualize(min=0, max=n_used, palette=palette).clip(region)
    tile_url = vis.getMapId()["tile_fetcher"].url_format
    mean = None
    try:
        mean = count.reduceRegion(ee.Reducer.mean(), region, 30, maxPixels=int(1e9),
                                  bestEffort=True).get("count").getInfo()
    except Exception:
        pass
    return tile_url, {"n_fortnights": n_used, "year": year, "max": n_used,
                      "mean": round(mean, 1) if mean is not None else None}


# ----------------- biomass (GEDI AGBD regression on Alpha Earth) (#3 wk10) -----------------
# Biomass is a Random Forest *regressor* on the same 64-d Alpha Earth features every classifier
# here uses (+ slope), so it can't be band math — it rides the point grid, like #7's RF split. The
# output is a continuous AGBD value per cell (Mg/ha), drawn with a ramp instead of class colours.
BIOMASS_GLOB = "data/refine/biomass_*.joblib"


def biomass_models():
    """The trained biomass models on disk -> {name: path}. Empty until one is trained."""
    import glob
    out = {}
    for p in sorted(glob.glob(BIOMASS_GLOB)):
        out[os.path.basename(p)[len("biomass_"):-len(".joblib")]] = p
    return out


def load_biomass(name=None):
    """Load a biomass regressor bundle by short name (else the first one on disk). None if none."""
    models = biomass_models()
    if not models:
        return None
    path = models.get(name) or next(iter(models.values()))
    return joblib.load(path)


def _sample_ae_slope(pts, bbox, year, use_slope=True):
    """Alpha Earth 64-d (+ slope) at each grid point, in the biomass model's feature order. Returns
    (X, valid_mask). Same server-side sampling as _sample_alpha, one extra band for slope."""
    ee = config.ee_init()
    w, s, e, nth = bbox
    region = ee.Geometry.Rectangle([w, s, e, nth])
    ae = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
          .filterDate(f"{year}-01-01", f"{year+1}-01-01").filterBounds(region).mosaic()).select(BANDS)
    img, cols = ae, list(BANDS)
    if use_slope:
        dem = ee.ImageCollection("COPERNICUS/DEM/GLO30").filterBounds(region).select("DEM").mosaic()
        slope = ee.Terrain.slope(dem.setDefaultProjection("EPSG:3857")).rename("slope")
        img, cols = ae.addBands(slope), list(BANDS) + ["slope"]
    feats = [ee.Feature(ee.Geometry.Point([x, y]), {"i": i}) for i, (x, y) in enumerate(pts)]
    samp = img.sampleRegions(collection=ee.FeatureCollection(feats), scale=10).getInfo()["features"]
    X = np.full((len(pts), len(cols)), np.nan, dtype=np.float32)
    for f in samp:
        p = f["properties"]
        X[p["i"]] = [p.get(c, np.nan) for c in cols]
    return X, ~np.isnan(X).any(axis=1)


def classify_biomass_grid(bbox, year: int = 2022, n: int = 30, bundle=None):
    """Predict above-ground biomass (AGBD, Mg/ha) over the bbox on a point grid (#3 wk10).

    Samples Alpha Earth (+ slope) at each cell and runs the biomass regressor. Returns
    (df[lat, lon, val], cell_w, cell_h, ramp) where `ramp` is the {min,max,mean} used to colour the
    overlay. A cell with no embedding comes back NaN (drawn transparent)."""
    if bundle is None:
        bundle = load_biomass()
    if bundle is None:
        raise ValueError("no biomass model trained yet — run scripts/train_biomass.py")
    w, s, e, nth = bbox
    pts = _grid(bbox, n)
    X, valid = _sample_ae_slope(pts, bbox, year, use_slope=bundle.get("use_slope", True))
    vals = np.full(len(pts), np.nan, dtype=np.float32)
    if valid.any():
        vals[valid] = bundle["model"].predict(X[valid])
    df = pd.DataFrame({"lat": [p[1] for p in pts], "lon": [p[0] for p in pts], "val": vals})
    good = df.val.dropna()
    ramp = {"min": float(good.min()) if len(good) else 0.0,
            "max": float(good.max()) if len(good) else 1.0,
            "mean": float(good.mean()) if len(good) else 0.0,
            "units": bundle.get("units", "Mg/ha")}
    return df, (e - w) / (n - 1), (nth - s) / (n - 1), ramp


def _grid(bbox, n):
    """Even n*n grid of (lon, lat) cell centers over the bbox."""
    w, s, e, nth = bbox
    lons, lats = np.linspace(w, e, n), np.linspace(s, nth, n)
    return [(float(x), float(y)) for y in lats for x in lons]


def _sample_alpha(pts, bbox, year):
    """Alpha Earth 64-d at each point, sampled server-side in GEE."""
    ee = config.ee_init()
    w, s, e, nth = bbox
    region = ee.Geometry.Rectangle([w, s, e, nth])
    img = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
           .filterDate(f"{year}-01-01", f"{year+1}-01-01")
           .filterBounds(region).mosaic())
    feats = [ee.Feature(ee.Geometry.Point([x, y]), {"i": i}) for i, (x, y) in enumerate(pts)]
    samp = img.sampleRegions(collection=ee.FeatureCollection(feats), scale=10).getInfo()["features"]
    bands = [f"A{k:02d}" for k in range(64)]
    X = np.full((len(pts), 64), np.nan, dtype=np.float32)
    for f in samp:
        p = f["properties"]
        X[p["i"]] = [p.get(b, np.nan) for b in bands]
    return X


def _sample_tessera(pts, year):
    """Tessera 128-d at each point; downloads the area's tiles on demand (cached).

    We pre-fetch the missing tiles with chunked-parallel range requests (~2x faster
    than a single stream); geotessera then finds them cached and only grabs the small
    scales/landmask files. verify_hashes=False so it trusts our pre-placed tiles.
    """
    import tessera_fast
    import aoi
    # #3: guard the download fan-out — each 0.1 deg tile is ~150 MB. Derive the covering bbox
    # from the points and refuse if it needs more tiles than the admin cap allows.
    lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
    box = (min(lons), min(lats), max(lons), max(lats))
    g = aoi.check(box, "tessera")
    if not g["ok"]:
        raise ValueError(g["reason"])
    tessera_fast.prefetch_for_points(pts, year)  # best-effort fast download
    from geotessera import GeoTessera
    gt = GeoTessera(verify_hashes=False)
    emb = np.asarray(gt.sample_embeddings_at_points(pts, year=year), dtype=np.float32)
    return emb


def classify_bbox(bbox, n: int = 35, year: int = 2024, model_bundle=None, refinements=None):
    """Instant mode: AE-only. bbox = (west, south, east, north).

    Returns (df[lat, lon, pred], cell_w, cell_h), one row per grid cell center.
    Any base class with a trained split (e.g. greenery) is relabeled to its children.
    """
    if model_bundle is None:
        model_bundle = load_model()
    if refinements is None:
        refinements = load_refinements()
    w, s, e, nth = bbox
    pts = _grid(bbox, n)
    X = _sample_alpha(pts, bbox, year)

    mask = ~np.isnan(X).any(axis=1)
    preds = np.array(["nodata"] * len(pts), dtype=object)
    if mask.any():
        preds[mask] = model_bundle["model"].predict(X[mask])
    # a Tessera split (#16) can't ride the AE tile map, so it's rendered here on the point grid — sample
    # Tessera only when some live split actually needs it (it downloads tiles), then dispatch per split.
    te_needed = any(b.get("features") == "tessera" for b in refinements.values())
    Xte = _sample_tessera(pts, year) if te_needed else None
    te_valid = ~np.isnan(Xte).any(axis=1) if Xte is not None else None
    rule_labels = _sample_rule_labels(pts, bbox, year, refinements)   # rule splits on the point grid (#12)
    _apply_refinements(preds, X, mask, refinements, Xte=Xte, te_valid=te_valid, rule_labels=rule_labels)
    _apply_merges(preds)

    df = pd.DataFrame({"lat": [p[1] for p in pts], "lon": [p[0] for p in pts], "pred": preds})
    return df, (e - w) / (n - 1), (nth - s) / (n - 1)


def classify_bbox_softvote(bbox, n: int = 35, year: int = 2024, model_bundle=None,
                           refinements=None):
    """High-accuracy mode: soft-vote of AE + Tessera calibrated models.

    Same return shape as classify_bbox. Samples both embeddings at the same grid
    points and averages their class probabilities. A cell is 'nodata' only if BOTH
    sources are missing; if just one is, we fall back to the available model.
    Splits (e.g. greenery) are applied afterwards using the AE matrix.
    """
    if model_bundle is None:
        model_bundle = load_softvote()
    if refinements is None:
        refinements = load_refinements()
    w, s, e, nth = bbox
    pts = _grid(bbox, n)
    Xae = _sample_alpha(pts, bbox, year)
    Xte = _sample_tessera(pts, year)

    ae_m, te_m = model_bundle["ae_model"], model_bundle["te_model"]
    classes = np.array(model_bundle["classes"], dtype=object)
    wa, wt = model_bundle.get("weights", [0.5, 0.5])

    ae_ok = ~np.isnan(Xae).any(axis=1)
    te_ok = ~np.isnan(Xte).any(axis=1)
    preds = np.array(["nodata"] * len(pts), dtype=object)

    # both present -> soft-vote; only one present -> use that one
    both = ae_ok & te_ok
    if both.any():
        proba = wa * ae_m.predict_proba(Xae[both]) + wt * te_m.predict_proba(Xte[both])
        preds[both] = classes[proba.argmax(1)]
    only_ae = ae_ok & ~te_ok
    if only_ae.any():
        preds[only_ae] = ae_m.predict(Xae[only_ae])
    only_te = te_ok & ~ae_ok
    if only_te.any():
        preds[only_te] = te_m.predict(Xte[only_te])

    # splits refine on their own signal: AE splits use Xae, a Tessera split uses the Xte already
    # sampled above (#16), a rule split uses its EE-sampled per-point labels (#12). All are on the
    # same grid points, so selection masks line up.
    rule_labels = _sample_rule_labels(pts, bbox, year, refinements)
    _apply_refinements(preds, Xae, ae_ok, refinements, Xte=Xte, te_valid=te_ok, rule_labels=rule_labels)
    _apply_merges(preds)

    df = pd.DataFrame({"lat": [p[1] for p in pts], "lon": [p[0] for p in pts], "pred": preds})
    return df, (e - w) / (n - 1), (nth - s) / (n - 1)
