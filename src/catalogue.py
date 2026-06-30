"""The model-zoo database: Model Cards + Dataset Cards on disk, minted from live artifacts.

Week 4 designed the cards (see week4/notes/model_data_schema.md); this is the running
version. Two record types live as JSON under data/catalogue/:

  data/catalogue/
    datasets/<id>.json   training (labeled polygons/pixels) + inference (feature source) cards
    models/<id>.json     a classifier at one hierarchy node
    index.json           denormalized lookup for fast browsing / "models for my area"

Every card validates against schema/*.json on write. The catalogue dir is also a git
working tree (see zoo_git.py) — that's how "publish to the zoo" works — but this module
only touches files; git is a separate, explicit step so minting never blocks on a network.

Cards keep a stable id (`mc_greenery_v1`) and bump the integer `version` field in place on
rewrite, so lineage/index references stay valid instead of spawning a new file each retrain.
"""
import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
from jsonschema import Draft7Validator, RefResolver

import hierarchy

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE_DIR = ROOT / "data" / "catalogue"
DATASETS_DIR = CATALOGUE_DIR / "datasets"
MODELS_DIR = CATALOGUE_DIR / "models"
INDEX_PATH = CATALOGUE_DIR / "index.json"
SCHEMA_DIR = ROOT / "schema"
EXAMPLES_DIR = ROOT / "data" / "examples"

# the one feature source every Alpha-Earth model runs on (the "inference dataset")
AE_INFERENCE_ID = "ds_alphaearth_annual_v1"
INDIA_BBOX = [68.0, 6.5, 97.5, 37.5]  # rough national extent; the base model's validity
# how a retrain's chosen balance policy reads on the model card (#6)
_BALANCE_METHOD = {"balanced": "class_weight_balanced", "undersample": "undersample",
                   "oversample": "oversample"}

# the standard LULC vocabularies a user can map a class to (#13-15). Offered as a pick-list so
# nobody has to memorize codes; mapping is optional and any subset is fine.
STANDARDS = {
    "worldcover": {"label": "ESA WorldCover", "classes": [
        {"code": 10, "name": "Tree cover"}, {"code": 20, "name": "Shrubland"},
        {"code": 30, "name": "Grassland"}, {"code": 40, "name": "Cropland"},
        {"code": 50, "name": "Built-up"}, {"code": 60, "name": "Bare / sparse vegetation"},
        {"code": 70, "name": "Snow and ice"}, {"code": 80, "name": "Permanent water bodies"},
        {"code": 90, "name": "Herbaceous wetland"}, {"code": 95, "name": "Mangroves"},
        {"code": 100, "name": "Moss and lichen"}]},
    "usda": {"label": "USDA / Anderson Level I", "classes": [
        {"code": "Urban or Built-up", "name": "Urban or Built-up"},
        {"code": "Agricultural", "name": "Agricultural land"},
        {"code": "Rangeland", "name": "Rangeland"}, {"code": "Forest", "name": "Forest land"},
        {"code": "Water", "name": "Water"}, {"code": "Wetland", "name": "Wetland"},
        {"code": "Barren", "name": "Barren land"}, {"code": "Tundra", "name": "Tundra"},
        {"code": "Snow or Ice", "name": "Perennial snow or ice"}]},
}


# ----------------------------- schema / validation -----------------------------
def _schemas():
    """Load the two card schemas + a resolver that knows the cross-ref between them."""
    ds = json.load(open(SCHEMA_DIR / "dataset_card.schema.json"))
    mc = json.load(open(SCHEMA_DIR / "model_card.schema.json"))
    store = {"dataset_card.schema.json": ds, ds["$id"]: ds, mc["$id"]: mc}
    return ds, mc, RefResolver(base_uri="", referrer=mc, store=store)


_DS_SCHEMA, _MC_SCHEMA, _RESOLVER = _schemas()


def validate_card(card):
    """Raise jsonschema.ValidationError if the card doesn't fit its schema."""
    schema = _MC_SCHEMA if card["id"].startswith("mc_") else _DS_SCHEMA
    Draft7Validator(schema, resolver=_RESOLVER).validate(card)


# ----------------------------- low-level store -----------------------------
def _dir_for(card_id):
    return MODELS_DIR if card_id.startswith("mc_") else DATASETS_DIR


def write_card(card):
    """Validate, stamp version/timestamps, write <id>.json, refresh the index."""
    validate_card(card)
    d = _dir_for(card["id"])
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{card['id']}.json"
    if path.exists():                      # rewrite: bump version, keep original created
        prev = json.load(open(path))
        card.setdefault("created", prev.get("created"))
        card["version"] = int(prev.get("version", 1)) + 1
        card["updated"] = _now()
    json.dump(card, open(path, "w"), indent=2)
    rebuild_index()
    return card["id"]


def get_card(card_id):
    path = _dir_for(card_id) / f"{card_id}.json"
    return json.load(open(path)) if path.exists() else None


def update_card_meta(card_id, about=None, contributor=None, std_mapping=None, source_url=None):
    """User-supplied metadata for a card (#8, #13--15): a description / intended use /
    limitations / evidence (the 'annotate it' ask), the contributor, and an optional mapping of
    each produced class to a standard LULC class (WorldCover / USDA / IUCN). For a dataset card,
    `source_url` is the public link to where the data came from (#8b) — set on the card itself so
    the user attaches it once, not once-per-publish. Merges, re-validates, rewrites (bumps version)."""
    card = get_card(card_id)
    if not card:
        raise KeyError(card_id)
    if about:
        card.setdefault("about", {}).update({k: v for k, v in about.items() if v is not None})
    if contributor is not None:
        card.setdefault("zoo", {})["contributor"] = contributor
    if source_url is not None:                             # "" clears it; a value sets the link
        url = source_url.strip()
        card["source_url"] = url
        card.setdefault("provenance", {})["source_url"] = url
    for prod in card.get("produces", []):                  # attach the crosswalk per class
        m = (std_mapping or {}).get(prod["class"])
        if m:
            prod["std_mapping"] = {k: v for k, v in m.items() if v not in (None, "")}
    write_card(card)
    return card


def list_cards(kind=None, ds_type=None):
    """All cards, optionally filtered. kind in {'model','dataset'}; ds_type in {'training','inference'}."""
    out = []
    dirs = []
    if kind in (None, "model"):
        dirs.append(MODELS_DIR)
    if kind in (None, "dataset"):
        dirs.append(DATASETS_DIR)
    for d in dirs:
        for p in sorted(glob.glob(str(d / "*.json"))):
            card = json.load(open(p))
            if ds_type and card.get("type") != ds_type:
                continue
            out.append(card)
    return out


# ----------------------------- index + spatial query -----------------------------
def rebuild_index():
    """Denormalized lookup so browsing / AOI filtering doesn't open every card."""
    rows = []
    for card in list_cards():
        is_model = card["id"].startswith("mc_")
        rows.append({
            "id": card["id"],
            "name": card.get("name"),
            "kind": "model" if is_model else "dataset",
            "type": card.get("type"),                          # dataset: training|inference
            "node": card.get("node"),
            "topology": card.get("topology"),
            "classes": ([p["class"] for p in card.get("produces", [])] if is_model
                        else [c["class"] for c in card.get("classes", [])]),
            "extent_bbox": _extent_bbox(card),
            "year": ((card.get("extent") or {}).get("temporal") or {}).get("year"),
            "accuracy": (card.get("metrics") or {}).get("accuracy") if is_model else None,
            "published": (card.get("zoo") or {}).get("published") if is_model else None,
            "created": card.get("created"),
        })
    CATALOGUE_DIR.mkdir(parents=True, exist_ok=True)
    json.dump({"cards": rows, "generated": _now()}, open(INDEX_PATH, "w"), indent=2)
    return rows


def load_index():
    if INDEX_PATH.exists():
        return json.load(open(INDEX_PATH))
    return {"cards": rebuild_index(), "generated": _now()}


def _worldcover_for_class(cls):
    """The WorldCover class a hierarchy class has been mapped to, if any user mapped it (#2).

    Scans model cards' produces[].std_mapping for `cls` -> a worldcover code, and names it via
    STANDARDS. Returns {code, name} or None. This is how 'apply after WorldCover class XYZ' gets
    derived from metadata instead of being hand-curated."""
    wc_names = {c["code"]: c["name"] for c in STANDARDS["worldcover"]["classes"]}
    for card in list_cards(kind="model"):
        for p in card.get("produces", []):
            if p.get("class") == cls:
                code = (p.get("std_mapping") or {}).get("worldcover")
                if code is not None:
                    return {"code": code, "name": wc_names.get(code, str(code))}
    return None


def recommend_placement(card):
    """'Where does this model slot in' hint (#2), auto-derived from card metadata — no curation.

    A per-node split runs on pixels the base map already called `node`, so the natural advice is
    'apply after <node>'. If that base class was mapped to a WorldCover class anywhere in the
    catalogue, we name it too (sir's 'apply after WorldCover class XYZ'). The base model is the
    starting point, so it has none. Returns None for non-model cards."""
    if not card or not str(card.get("id", "")).startswith("mc_"):
        return None
    if card.get("topology") == "merge_relabel":
        srcs = (card.get("merge") or {}).get("sources") or []
        return {"apply_after": None,
                "note": f"Cross-model relabel: applied after inference, over {', '.join(srcs) or 'its sources'}."}
    if card.get("topology") == "base_pooled" or card.get("node") == hierarchy.ROOT:
        return {"apply_after": None, "note": "Base map: the starting point."}
    node = card.get("node")
    tree = hierarchy.load()
    node_name = tree[node]["name"] if node in tree else node
    return {"apply_after": node, "apply_after_name": node_name,
            "worldcover": _worldcover_for_class(node)}


def models_for_aoi(bbox, interest=None):
    """Model cards whose extent overlaps `bbox` (and emit `interest`, if given).

    Extent is a bbox now (week-5 decision), so 'is there a model for my area' is a plain
    rectangle overlap — no region/AEZ lookup. Ranked by accuracy.
    """
    hits = []
    for row in load_index()["cards"]:
        if row["kind"] != "model":
            continue
        ext = row.get("extent_bbox")
        if ext and not _bbox_overlap(ext, bbox):
            continue
        if interest and interest not in (row.get("classes") or []) and row.get("node") != interest:
            continue
        hits.append(row)
    hits.sort(key=lambda r: r.get("accuracy") or 0, reverse=True)
    return hits


def card_geometry(card_id, max_features=8):
    """The drawable footprint of a card. For a polygon dataset (and for a model, its polygon
    training data) we return the actual polygons --- the few largest, so the map isn't swamped
    --- because *that's* the real extent. Feature sources (Alpha Earth / Tessera / pixel tables)
    have nothing point-like to draw, so `drawable` is False and the UI falls back to a label."""
    card = get_card(card_id)
    if not card:
        return {"drawable": False}
    paths = _polygon_paths_for(card)
    if not paths:
        return {"drawable": False, "reason": "feature source — not polygon-based"}

    import geopandas as gpd
    import pandas as pd
    frames = []
    for p in paths:
        fp = ROOT / p
        if not fp.exists():
            continue
        g = gpd.read_file(fp).to_crs(4326)
        if "role" in g.columns:                       # only the positives define the extent
            g = g[g["role"].fillna("positive") == "positive"]
        frames.append(g[["geometry"]])
    if not frames:
        return {"drawable": False}

    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    total = len(gdf)
    # "prominent" = largest by area (visible on the map); project for a fair area, keep 4326 geom
    gdf = gdf.assign(_a=gdf.to_crs(32643).area).sort_values("_a", ascending=False).head(max_features)
    feats = [{"type": "Feature", "properties": {}, "geometry": geom.__geo_interface__}
             for geom in gdf.geometry]
    return {"drawable": True, "total": total, "shown": len(feats),
            "type": "FeatureCollection", "features": feats}


def _polygon_paths_for(card):
    """On-disk polygon GeoJSONs backing a card: a polygon dataset's own path, or a model's
    polygon training datasets (skipping its ee_asset / pixel-table sources)."""
    if card["id"].startswith("ds_"):
        d = card.get("definition") or {}
        return [d["path"]] if card.get("kind") == "polygons" and d.get("path") else []
    paths = []
    for ds_id in (card.get("training") or {}).get("datasets") or []:
        ds = get_card(ds_id)
        if ds and ds.get("kind") == "polygons" and (ds.get("definition") or {}).get("path"):
            paths.append(ds["definition"]["path"])
    return paths


# ----------------------------- minting from live artifacts -----------------------------
def ensure_inference_dataset_card(source="alphaearth", dim=64, year=2024):
    """The shared feature-source card every AE model points to as its inference dataset.

    type=inference: it describes the *inputs* a model consumes (Alpha Earth 64-d annual),
    not labels. Idempotent — written once, reused by every model card."""
    if get_card(AE_INFERENCE_ID):
        return AE_INFERENCE_ID
    write_card({
        "id": AE_INFERENCE_ID,
        "name": "Alpha Earth annual embeddings (64-d) — model input features",
        "description": "The feature space LULC models run on: Google Satellite Embedding V1 "
                       "annual, sampled server-side at 10 m. No labels — this is the inference input.",
        "type": "inference",
        "kind": "ee_asset",
        "definition": {"type": "ee_asset", "asset": "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL",
                       "scale": 10},
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": year}},
        "embedding": {"source": source, "dim": dim, "year": year},
        "provenance": {"annotator": "Google DeepMind / Alpha Earth", "method": "learned embedding",
                       "evidence": ["GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"], "license": None},
        "version": 1, "created": _now(),
    })
    return AE_INFERENCE_ID


def mint_training_dataset_card(node, year=2024):
    """A training Dataset Card from a node's own example polygons (kind=polygons).

    Pulls classes/counts from the example store, computes the bbox extent + spatial-diversity
    quality, and lifts provenance (annotator/timestamps) from the feature properties.
    Returns the card id, or None if the node has no example polygons (e.g. worldcover/residual
    sources, which get their own cards via _dataset_card_for_child)."""
    import examples
    fc = examples.load_examples(node)
    feats = [f for f in fc["features"] if f["properties"].get("role", "positive") == "positive"]
    if not feats:
        return None
    tree = hierarchy.load()
    name = tree[node]["name"] if node in tree else node
    bbox, div, occ = _geojson_stats(feats)
    card_id = f"ds_{node}_polygons_v1"
    write_card({
        "id": card_id,
        "name": f"{name} expert polygons",
        "description": f"User-marked example polygons for the '{name}' class.",
        "type": "training",
        "kind": "polygons",
        "classes": [{"class": node, "name": name, "count": len(feats)}],
        "definition": {"type": "polygons", "path": f"data/examples/{node}.geojson"},
        "extent": {"spatial": {"type": "bbox", "value": bbox}, "temporal": {"year": year}},
        "provenance": {"annotator": "user contribution", "method": "drawn/uploaded polygons",
                       "evidence": [], "license": None,
                       "notes": f"marked between {feats[0]['properties'].get('ts')} "
                                f"and {feats[-1]['properties'].get('ts')}"},
        "quality": {"n_polygons": len(feats), "occupied_cells": occ, "spatial_diversity": div,
                    "class_balance": {node: 1.0}},
        "version": 1, "created": _now(),
    })
    return card_id


def _dataset_card_for_child(child):
    """Mint/return the training dataset card a child trains on, dispatched on its `source`
    (mirrors refine._child_frame): examples -> polygons card; worldcover -> ee_asset card;
    residual -> the master expert embedding-table slice."""
    tree = hierarchy.load()
    src = (tree[child].get("source") or {"type": "examples"})
    kind = src["type"]
    if kind == "worldcover":
        cid = f"ds_worldcover_{child}_v1"
        if not get_card(cid):
            write_card({
                "id": cid, "name": f"ESA WorldCover slice ({child})", "type": "training",
                "kind": "ee_asset", "classes": [{"class": child, "name": tree[child]["name"]}],
                "definition": {"type": "ee_asset", "asset": "ESA/WorldCover/v200",
                               "band": "Map", "code": src.get("code")},
                "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2021}},
                "embedding": {"source": "alphaearth", "dim": 64, "year": 2024},
                "provenance": {"annotator": "ESA WorldCover v200",
                               "method": "global automated classification (10 m)",
                               "evidence": ["ESA WorldCover product"], "license": "CC-BY-4.0",
                               "notes": "weak labels vs expert polygons; cached in worldcover_train.csv"},
                "version": 1, "created": _now(),
            })
        return cid
    if kind == "residual":
        return "ds_master_alpha_full_v1"     # seeded in backfill
    return mint_training_dataset_card(child)


def mint_model_card(node, bundle, training_ds_ids, extent_bbox=None, metrics=None):
    """A Model Card for the classifier that resolves `node`, from its retrain bundle.

    Lifts metrics from the bundle's sklearn `report` (split models) or the passed `metrics`
    (the base model carries none). produces = the classes it emits; inference.dataset = the
    shared Alpha-Earth feature source; extent = bbox of its training data (India for the base)."""
    tree = hierarchy.load()
    is_root = node == hierarchy.ROOT
    classes = bundle.get("classes") or []
    name = ("Core Stack base map — 4-class LULC (India)" if is_root
            else f"{tree[node]['name']} split ({' / '.join(classes)})")
    ae_id = ensure_inference_dataset_card()
    card = {
        "id": f"mc_{node}_v1",
        "name": name,
        "node": node,
        "parent_class": None if is_root else (tree[node].get("parent") or node),
        "topology": "base_pooled" if is_root else "per_node_split",
        "produces": [{"class": c} for c in classes],
        "training": {
            "datasets": [d for d in training_ds_ids if d],
            "embedding": {"source": "alphaearth", "dim": 64},
            "algo": "StandardScaler->LinearSVC",
            "class_weight": None if is_root else "balanced",
            "balancing": ({"method": "worldcover_upweight", "wc_weight": bundle.get("wc_weight", 2)}
                          if is_root else {"method": _BALANCE_METHOD.get(bundle.get("balance"),
                                           "class_weight_balanced"), "residual_cap": 8000}),
        },
        "inference": {"dataset": ae_id, "embedding": {"source": "alphaearth", "dim": 64, "year": 2024}},
        "extent": {"spatial": {"type": "bbox", "value": extent_bbox or INDIA_BBOX},
                   "temporal": {"year": 2024}},
        "metrics": metrics or _metrics_from_report(bundle.get("report"), bundle.get("n_test")),
        "artifact": {"path": _artifact_path(node), "format": "sklearn-joblib"},
        "deployment": {"ee_asset": None, "tile_url": None, "expressible_as_bandmath": True},
        "lineage": {"base_model": None if is_root else "mc_root_v1", "derived_from": None},
        "about": {"description": name,
                  "intended_use": "Layered on the India base map." if not is_root
                                  else "Coarse 4-class LULC across India at 10 m.",
                  "limitations": "Linear model; rare-class recall limited.", "evidence": ""},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": ""},
        "version": 1, "created": _now(),
    }
    if is_root:
        card["base_scheme"] = "indiasat"     # tags this as the default base scheme (#5)
    write_card(card)
    return card["id"]


def mint_worldcover_base_card():
    """Mint the card for the effective WorldCover base model (#5), so it shows up in the zoo as a
    *selectable* base scheme alongside the IndiaSAT base. Distinct id (no collision with the root
    card); carries base_scheme='worldcover' so the backend routes 'apply' to a base switch.
    Returns the card id, or None if the WorldCover base hasn't been trained yet."""
    import joblib
    path = ROOT / "data" / "model_worldcover_base.joblib"
    if not path.exists():
        return None
    bundle = joblib.load(path)
    classes = bundle.get("classes", [])
    ae_id = ensure_inference_dataset_card()
    write_card({
        "id": "mc_worldcover_base_v1",
        "name": "WorldCover effective base — 7-class LULC (India)",
        "node": hierarchy.ROOT,
        "parent_class": None,
        "topology": "base_pooled",
        "base_scheme": "worldcover",
        "produces": [{"class": c} for c in classes],
        "training": {"datasets": ["ds_worldcover_train_v1"],
                     "embedding": {"source": "alphaearth", "dim": 64},
                     "algo": "StandardScaler->LinearSVC", "class_weight": "balanced",
                     "balancing": {"method": "class_weight_balanced"}},
        "inference": {"dataset": ae_id, "embedding": {"source": "alphaearth", "dim": 64, "year": 2024}},
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2024}},
        "metrics": {"note": "weak ESA WorldCover labels; trails the IndiaSAT base. An alternate "
                            "starting scheme, not a more accurate one."},
        "artifact": {"path": "data/model_worldcover_base.joblib", "format": "sklearn-joblib"},
        "deployment": {"ee_asset": None, "tile_url": None, "expressible_as_bandmath": True},
        "lineage": {"base_model": None, "derived_from": None},
        "about": {"description": "Effective WorldCover base: the well-supported India classes "
                                 "(tree, shrubland, grassland, cropland, built-up, bare, water) "
                                 "learned from Alpha Earth embeddings.",
                  "intended_use": "An alternate starting scheme to IndiaSAT's four classes.",
                  "limitations": "Weak ESA WorldCover labels; rare classes dropped for lack of "
                                 "India support.", "evidence": ""},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": ""},
        "version": 1, "created": _now(),
    })
    return "mc_worldcover_base_v1"


def mint_merge_card(rule):
    """Mint a local Model Card for a merge (#9). A merge is a post-inference relabel layer, not a
    trained classifier, so it carries no joblib — but it's still a *model the user built*, so it
    earns a card like any other and shows up in the zoo as a local model they can track and publish.
    `produces` the merged class; records the source leaves and which model produced each (lineage)."""
    target = rule["target"]
    sources = rule.get("sources", [])
    tree = hierarchy.load()

    def _producer(leaf):                  # the model that emitted this source leaf, for lineage
        parent = (tree.get(leaf) or {}).get("parent")
        if parent and parent != hierarchy.ROOT and tree.get(parent, {}).get("classifier"):
            return f"mc_{parent}_v1"
        return "mc_root_v1"

    ae_id = ensure_inference_dataset_card()
    card_id = f"mc_merge_{target}_v1"
    write_card({
        "id": card_id,
        "name": f"Merge: {rule.get('name', target)} (← {', '.join(sources) or '?'})",
        "node": target,
        "parent_class": hierarchy.ROOT,
        "topology": "merge_relabel",
        "produces": [{"class": target}],
        # no labelled training data — it's a relabel, so the datasets list is empty by design
        "training": {"datasets": [], "algo": "relabel (no training)",
                     "balancing": {"method": "none"}},
        "inference": {"dataset": ae_id, "embedding": {"source": "alphaearth", "dim": 64, "year": 2024}},
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2024}},
        "metrics": {"note": "post-inference relabel layer; accuracy follows its source models"},
        "artifact": {"path": "data/merge_rules.json", "format": "merge-rule"},
        "deployment": {"ee_asset": None, "tile_url": None, "expressible_as_bandmath": True},
        "lineage": {"base_model": None,
                    "derived_from": ", ".join(sorted({_producer(s) for s in sources})) or None},
        "merge": {"sources": sources, "color": rule.get("color"),
                  "source_models": sorted({_producer(s) for s in sources})},
        "about": {"description": f"Relabels {', '.join(sources) or 'chosen leaves'} into "
                                 f"'{rule.get('name', target)}'.",
                  "intended_use": "A cross-model correction layer applied after inference.",
                  "limitations": "Pure relabel; no retraining, so it inherits its sources' errors.",
                  "evidence": ""},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": ""},
        "version": 1, "created": _now(),
    })
    return card_id


def delete_card(card_id):
    """Remove a card file and refresh the index (used when a merge is undone). Idempotent."""
    path = _dir_for(card_id) / f"{card_id}.json"
    if path.exists():
        path.unlink()
        rebuild_index()
    return card_id


def sync_merge_cards():
    """Reconcile merge cards with the live merge rules (#9). Mints a card for any active rule that
    lacks one (covers merges made before merge-carding existed) and drops cards whose rule is gone.
    Idempotent; called at startup so the zoo always mirrors the active merges."""
    import merges
    rules = merges.load()
    targets = {r["target"] for r in rules}
    for r in rules:
        if not get_card(f"mc_merge_{r['target']}_v1"):
            try:
                mint_merge_card(r)
            except Exception:
                pass
    for p in glob.glob(str(MODELS_DIR / "mc_merge_*_v1.json")):
        tid = Path(p).stem[len("mc_merge_"):-len("_v1")]
        if tid not in targets:
            delete_card(Path(p).stem)


def register_retrain(node, bundle):
    """Called by the backend right after refine.retrain: mint the dataset cards the node
    trained on + its model card, so the catalogue tracks every trained model. Returns the
    minted card ids."""
    ensure_inference_dataset_card()
    tree = hierarchy.load()
    children = (tree[hierarchy.ROOT]["children"] if node == hierarchy.ROOT
                else tree[node]["children"])
    ds_ids = [d for d in (_dataset_card_for_child(c) for c in children) if d]
    extent = _training_extent(ds_ids)
    metrics = None if node != hierarchy.ROOT else _base_metrics(bundle)
    mc_id = mint_model_card(node, bundle, ds_ids, extent_bbox=extent, metrics=metrics)
    return {"model": mc_id, "datasets": ds_ids}


# ----------------------------- backfill (seed from what's already on disk) -----------------------------
def backfill():
    """Seed cards for everything already trained: the base model + its datasets, plus any
    live split (greenery, barren, ...). Idempotent-ish — safe to run when the catalogue is
    empty. Reconciles the week-4 design's seed values to the week-5 schema (type, bbox)."""
    import joblib
    ensure_inference_dataset_card()

    # the base model's three training datasets (fixed, expert + WorldCover tables)
    _seed_master_alpha_full()
    _seed_simple_training_card("ds_worldcover_train_v1", "ESA WorldCover random-India points",
                               "ee_asset", "data/worldcover_train.csv")
    _seed_simple_training_card("ds_water_extra_v1", "Extra water polygons",
                               "embedding_table", "data/water_extra.csv")

    # base model card (no held-out report in its bundle -> known headline metrics)
    base_path = ROOT / "data" / "model_pooled.joblib"
    if base_path.exists():
        base = joblib.load(base_path)
        mint_model_card(
            hierarchy.ROOT, base,
            ["ds_master_alpha_full_v1", "ds_worldcover_train_v1", "ds_water_extra_v1"],
            extent_bbox=INDIA_BBOX, metrics=_base_metrics(base))

    # the alternate WorldCover base, if it's been trained (so it shows as a selectable scheme #5)
    mint_worldcover_base_card()

    # every live split classifier (data/refine/<node>.joblib registered on a tree node)
    tree = hierarchy.load()
    for node, n in tree.items():
        if node == hierarchy.ROOT or not n.get("classifier"):
            continue
        jb = ROOT / "data" / "refine" / f"{node}.joblib"
        if jb.exists():
            register_retrain(node, joblib.load(jb))
    return load_index()


def _seed_master_alpha_full():
    if get_card("ds_master_alpha_full_v1"):
        return
    write_card({
        "id": "ds_master_alpha_full_v1",
        "name": "Master Alpha Earth expert pixel table (4 base classes)",
        "description": "Expert-labelled Alpha Earth pixels over ~200 diverse India tiles; "
                       "the base map's primary training table.",
        "type": "training", "kind": "embedding_table",
        "classes": [{"class": c, "name": c.replace("_", " ").title()}
                    for c in ("greenery", "water", "built_up", "barren")],
        "definition": {"type": "embedding_table", "path": "data/master_alpha_full.csv",
                       "label_col": "core_class"},
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2024}},
        "embedding": {"source": "alphaearth", "dim": 64, "year": 2024},
        "provenance": {"annotator": "Core Stack (week-2 build)",
                       "method": "expert polygons over ~200 diverse India tiles -> interior pixels",
                       "evidence": [], "license": None},
        "version": 1, "created": _now(),
    })


def _seed_simple_training_card(card_id, name, kind, path):
    if get_card(card_id):
        return
    defn = {"type": kind}
    defn["asset" if kind == "ee_asset" else "path"] = path
    write_card({
        "id": card_id, "name": name, "type": "training", "kind": kind,
        "classes": [{"class": "mixed", "name": "Mixed land-cover labels"}],
        "definition": defn,
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2024}},
        "embedding": {"source": "alphaearth", "dim": 64, "year": 2024},
        "provenance": {"annotator": "Core Stack", "method": "Core Stack build", "evidence": []},
        "version": 1, "created": _now(),
    })


# ----------------------------- helpers -----------------------------
def _now():
    return datetime.now(timezone.utc).isoformat()


def _artifact_path(node):
    return "data/model_pooled.joblib" if node == hierarchy.ROOT else f"data/refine/{node}.joblib"


def _metrics_from_report(report, n_test):
    """Lift sklearn classification_report dict -> the card's metrics block."""
    if not report:
        return {}
    per = {}
    for label, v in report.items():
        if label in ("accuracy", "macro avg", "weighted avg") or not isinstance(v, dict):
            continue
        per[label] = {"precision": round(v["precision"], 3), "recall": round(v["recall"], 3),
                      "f1": round(v["f1-score"], 3), "support": int(v.get("support", 0))}
    return {"accuracy": round(report.get("accuracy", 0), 3),
            "macro_f1": round(report.get("macro avg", {}).get("f1-score", 0), 3),
            "eval": "polygon-holdout", "n_test": n_test, "per_class": per}


def _base_metrics(_bundle):
    """The base model carries no held-out report; use its validated headline numbers."""
    return {"accuracy": 0.80, "eval": "random India (real-world mix)",
            "secondary": {"accuracy": 0.89, "eval": "balanced expert hold-out"},
            "note": "greenery near-perfect; rare classes are the hard part"}


def _geojson_stats(features, cell=0.25):
    """bbox + spatial-diversity index + occupied-cell count for a set of GeoJSON features.

    Diversity = Shannon entropy of polygon centroids binned to a `cell`-degree grid,
    normalized to [0,1]. ~1 = well spread, ~0 = all clustered (ties to the generalization
    -gap finding: spread, not volume, is what generalizes). See week4/notes/spatial_diversity.py."""
    import numpy as np
    import geopandas as gpd
    gdf = gpd.GeoDataFrame.from_features(features, crs=4326)
    minx, miny, maxx, maxy = gdf.total_bounds
    bbox = [round(float(v), 5) for v in (minx, miny, maxx, maxy)]
    pts = gdf.geometry.representative_point()
    keys = list(zip((pts.x // cell).astype(int), (pts.y // cell).astype(int)))
    counts = np.array(list(__import__("collections").Counter(keys).values()), dtype=float)
    n, occ = len(keys), len(counts)
    if n <= 1:
        return bbox, 0.0, occ
    p = counts / counts.sum()
    entropy = -(p * np.log(p)).sum()
    return bbox, round(float(entropy / np.log(n)), 3), occ


def recompute_spread(card_id, cell=0.25):
    """Re-run the spatial-diversity stat for a polygon-backed card at a user-chosen grid cell (#1).

    The card's stored `quality.spatial_diversity` was computed at a fixed 0.25-degree grid; this
    lets the UI ask 'how spread is this at, say, 0.1 degrees?' without re-minting. Reads the card's
    actual polygons (all positives, not just the prominent few) via the same paths card_geometry uses,
    then reuses _geojson_stats with the requested cell. Returns None if the card has no polygons."""
    import geopandas as gpd
    import pandas as pd
    card = get_card(card_id)
    if not card:
        return None
    paths = _polygon_paths_for(card)
    if not paths:
        return None
    frames = []
    for p in paths:
        fp = ROOT / p
        if not fp.exists():
            continue
        g = gpd.read_file(fp).to_crs(4326)
        if "role" in g.columns:                       # only the positives define the spread
            g = g[g["role"].fillna("positive") == "positive"]
        frames.append(g[["geometry"]])
    if not frames:
        return None
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    feats = [{"type": "Feature", "properties": {}, "geometry": geom.__geo_interface__}
             for geom in gdf.geometry]
    _bbox, div, occ = _geojson_stats(feats, cell=cell)
    return {"cell": cell, "spatial_diversity": div, "occupied_cells": occ,
            "n_polygons": len(feats)}


def _extent_bbox(card):
    """Pull a [w,s,e,n] bbox out of a card's extent, if it has one."""
    sp = (card.get("extent") or {}).get("spatial") or {}
    return sp.get("value") if sp.get("type") == "bbox" else None


def _bbox_union(bboxes):
    bboxes = [b for b in bboxes if b]
    if not bboxes:
        return None
    return [min(b[0] for b in bboxes), min(b[1] for b in bboxes),
            max(b[2] for b in bboxes), max(b[3] for b in bboxes)]


def _training_extent(ds_ids):
    return _bbox_union([_extent_bbox(get_card(d) or {}) for d in ds_ids]) or INDIA_BBOX


def _bbox_overlap(a, b):
    """Do two [w,s,e,n] rectangles overlap at all?"""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


if __name__ == "__main__":
    # offline smoke test (no GEE): backfill from whatever's on disk, then validate + query.
    rows = backfill()["cards"]
    print(f"catalogue has {len(rows)} cards:")
    for r in rows:
        print(f"  {r['kind']:7} {r['id']:32} {r.get('type') or r.get('topology') or ''}")
    aoi = [72.8, 18.4, 73.0, 18.6]   # Pune-ish
    print("\nmodels for a Pune bbox:", [m["id"] for m in models_for_aoi(aoi)])
