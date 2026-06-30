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

# Alpha Earth band names, in the model's feature order (A00 == ae_000, ... A63)
BANDS = [f"A{k:02d}" for k in range(64)]

# fallback colours for classes that don't live in the hierarchy tree
CLASS_COLORS = {
    "greenery": "#2e8b2e",
    "water":    "#2b6cff",
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
    """parent class -> trained split bundle, for each tree node carrying a classifier.

    These relabel a base prediction into its children (e.g. greenery -> crops/trees/
    shrubs). All are Alpha-Earth based, so they reuse the AE matrix already sampled.
    """
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
    return out


def _refine_order(refinements):
    """Refinement parents shallow-first, so one pass cascades down the tree: greenery
    relabels to crops, then crops (if split) relabels further, and so on."""
    try:
        tree = hierarchy.load()
        return sorted(refinements, key=lambda c: len(hierarchy.path_to(tree, c)) if c in tree else 0)
    except Exception:
        return list(refinements)


def _apply_refinements(preds, Xae, valid, refinements):
    """In-place: walk the tree of classifiers root->leaf, each node refining its own
    label into a child. Depth ordering makes a single pass recurse to any depth."""
    for parent in _refine_order(refinements):
        sel = valid & (preds == parent)
        if sel.any():
            preds[sel] = refinements[parent]["model"].predict(Xae[sel])
    return preds


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
    pipe = bundle["model"]
    return pipe.named_steps["standardscaler"], pipe.named_steps["linearsvc"]


def _ee_label(ee, bands_img, bundle):
    """Class-index image (0..K-1, order = svc.classes_) for a linear bundle.

    score_k = ((A - mean)/scale) . coef_k + intercept_k. For >=3 classes LinearSVC is
    one-vs-rest -> argmax. For 2 classes it's a single hyperplane (coef_ is (1,64)):
    predict classes_[1] when the score is positive, else classes_[0].
    """
    sc, svc = _svc_steps(bundle)
    mean = ee.Image.constant(sc.mean_.tolist()).rename(BANDS)
    scale = ee.Image.constant(sc.scale_.tolist()).rename(BANDS)
    z = bands_img.subtract(mean).divide(scale)

    def score(k):
        coef = ee.Image.constant(svc.coef_[k].tolist()).rename(BANDS)
        return z.multiply(coef).reduce(ee.Reducer.sum()).add(float(svc.intercept_[k]))

    if svc.coef_.shape[0] == 1:        # binary: one score, sign picks the class
        return score(0).gt(0)
    scores = ee.Image.cat([score(k).rename(f"c{k}") for k in range(svc.coef_.shape[0])])
    return scores.toArray().arrayArgmax().arrayGet([0])


def _leaf_classes(model_bundle, refinements):
    """The classes that actually survive to the map: walk base classes down through every
    split to the leaves (depth-first). A class is a leaf unless it has a classifier."""
    def leaves_of(cls):
        if cls in refinements:
            out = []
            for ch in _svc_steps(refinements[cls])[1].classes_:
                out.extend(leaves_of(ch))
            return out
        return [cls]
    out = []
    for c in _svc_steps(model_bundle)[1].classes_:
        out.extend(leaves_of(c))
    return out


def _final_label(ee, bands_img, model_bundle, refinements):
    """Recursive label image: pixel values index into the returned leaf_classes list.

    Mirrors _apply_refinements but in EE. Each node classifies among its children; where
    a child has its own classifier we descend into it, all the way to a leaf. Same logic
    whether the split is one level deep (greenery) or many (greenery->crops->...)."""
    leaf_classes = _leaf_classes(model_bundle, refinements)
    code = {c: i for i, c in enumerate(leaf_classes)}

    def sub(cls):
        """Leaf-code image for the subtree under class `cls`."""
        if cls not in refinements:
            return ee.Image.constant(code[cls])
        idx = _ee_label(ee, bands_img, refinements[cls])
        children = list(_svc_steps(refinements[cls])[1].classes_)
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

def _labelled_bbox(bbox, year, model_bundle, refinements, colors):
    """The coloured label image for a bbox: base map + composited splits + merge relabels,
    visualized with the leaf palette. Returns (ee, final_code_img, final_classes, region, vis)."""
    ee = config.ee_init()
    if model_bundle is None:
        model_bundle = load_model()
    if refinements is None:
        refinements = load_refinements()

    bands_img, region = _alpha_image(ee, bbox, year)
    final, final_classes = _final_label(ee, bands_img, model_bundle, refinements)
    final, final_classes = _merge_ee(ee, final, final_classes)

    colors = colors or load_colors()
    palette = [colors.get(c, "#999999") for c in final_classes]
    vis = final.visualize(min=0, max=len(final_classes) - 1, palette=palette)
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
    _apply_refinements(preds, X, mask, refinements)
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

    _apply_refinements(preds, Xae, ae_ok, refinements)
    _apply_merges(preds)

    df = pd.DataFrame({"lat": [p[1] for p in pts], "lon": [p[0] for p in pts], "pred": preds})
    return df, (e - w) / (n - 1), (nth - s) / (n - 1)
