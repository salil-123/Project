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
import joblib
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
TE_INFERENCE_ID = "ds_tessera_annual_v1"          # Tessera feature-source card (#16)
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
    all_cards = list_cards()
    # model->dataset links, inverted once, so each dataset row can carry a cheap "used by N models"
    # count without re-scanning every card per dataset (#15).
    used_count = {}
    for c in all_cards:
        if c["id"].startswith("mc_"):
            for d in set(((c.get("training") or {}).get("datasets") or [])
                         + [(c.get("inference") or {}).get("dataset")]):
                if d:
                    used_count[d] = used_count.get(d, 0) + 1
    rows = []
    for card in all_cards:
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
            # standard-vocab names per produced class when mapped, so the tile can show them (#14)
            "std_classes": std_classes_for_card(card) if is_model else None,
            "used_by_count": None if is_model else used_count.get(card["id"], 0),   # #15
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


def std_classes_for_card(card):
    """Each produced class resolved to its standard-LULC name, if the uploader mapped it (#14).

    Returns a list aligned to `produces`: [{class, std, scheme}] where `std` is the standard class
    name (WorldCover preferred, else USDA) or None when unmapped. Lets the small zoo tile show what
    a class *is* in a shared vocabulary instead of the uploader's private label — degrades to None
    everywhere until someone annotates, so callers just fall back to the user classes."""
    wc = {c["code"]: c["name"] for c in STANDARDS["worldcover"]["classes"]}
    usda = {c["code"]: c["name"] for c in STANDARDS["usda"]["classes"]}
    out = []
    for p in card.get("produces", []):
        m = p.get("std_mapping") or {}
        if m.get("worldcover") is not None:
            out.append({"class": p["class"], "std": wc.get(m["worldcover"], str(m["worldcover"])),
                        "scheme": "worldcover"})
        elif m.get("usda"):
            out.append({"class": p["class"], "std": usda.get(m["usda"], str(m["usda"])),
                        "scheme": "usda"})
        else:
            out.append({"class": p["class"], "std": None, "scheme": None})
    return out


def models_using_dataset(ds_id):
    """Which model cards consume this dataset (#15): a dataset can feed several models, so we scan
    every model card's training datasets + its inference feature source. Returns [{id, name}].
    This is the reverse of the model->dataset link, surfaced on the dataset card so provenance runs
    both ways."""
    hits = []
    for card in list_cards(kind="model"):
        train = (card.get("training") or {}).get("datasets") or []
        infer = (card.get("inference") or {}).get("dataset")
        if ds_id in train or ds_id == infer:
            hits.append({"id": card["id"], "name": card.get("name")})
    return hits


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
    # an ee_rf model's `node` is the model id (treecrop/farmshrub), not a hierarchy class, so key the
    # hint off its suggested parent_class instead. It's a *suggestion* only — the user can attach it to
    # any node (#5 wk11); we just say where it normally goes.
    if card.get("topology") == "ee_rf":
        parent = card.get("parent_class") or "greenery"
        tree = hierarchy.load()
        pname = tree[parent]["name"] if parent in tree else parent
        return {"apply_after": parent, "apply_after_name": pname,
                "worldcover": _worldcover_for_class(parent),
                "note": f"Normally refines {pname}, but you can apply it to any node."}
    node = card.get("node")
    tree = hierarchy.load()
    node_name = tree[node]["name"] if node in tree else node
    return {"apply_after": node, "apply_after_name": node_name,
            "worldcover": _worldcover_for_class(node)}


def check_apply_compatible(card, target_node, tree):
    """Guard for #11: is it sensible to apply this model under `target_node`?

    A per-node split learned to divide the pixels of one base class (its `parent_class`) — a
    crop/tree model only knows greenery pixels, so dropping it on water is meaningless. We call it
    compatible when the target is the model's own node, the class the model refines lies on the
    path to the target, the target's own class is that refined class, or both sides carry the same
    WorldCover mapping. Otherwise we return a human reason so the UI can ask 'proceed anyway?'."""
    if not card:
        return {"ok": True, "reason": ""}
    # the class a per-node split operates on is its own node (a greenery split runs on greenery
    # pixels), so that's what the target must be — or sit under, or share a WorldCover class with.
    expects = card.get("node")
    if target_node == expects:
        return {"ok": True, "reason": ""}
    on_path = expects in hierarchy.path_to(tree, target_node) if target_node in tree else False
    home_wc = (_worldcover_for_class(expects) or {}).get("code")
    same_wc = home_wc is not None and home_wc == (_worldcover_for_class(target_node) or {}).get("code")
    if on_path or same_wc:
        return {"ok": True, "reason": ""}
    tname = tree[target_node]["name"] if target_node in tree else target_node
    ename = tree[expects]["name"] if expects in tree else expects
    produces = " / ".join(p["class"] for p in card.get("produces", [])) or "sub-classes"
    return {"ok": False,
            "reason": f"This model splits '{ename}' into {produces}; you're applying it under "
                      f"'{tname}', which it was never trained on."}


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


def named_regions(card_id, max_points=400):
    """Name the districts / states a card's polygons fall in (#7 wk11), by intersecting their
    centroids with FAO GAUL level-2 boundaries in Earth Engine. For a model card this uses its
    polygon *training* data — i.e. where the model is strongest. Returns
    {available, states[], districts[]} or {available: False} for a card with no polygon footprint."""
    card = get_card(card_id)
    if not card:
        return {"available": False}
    paths = _polygon_paths_for(card)
    if not paths:
        return {"available": False}
    import geopandas as gpd
    cents = []
    for p in paths:
        fp = ROOT / p
        if not fp.exists():
            continue
        g = gpd.read_file(fp).to_crs(4326)
        if "role" in g.columns:
            g = g[g["role"].fillna("positive") == "positive"]
        c4326 = g.to_crs(32643).geometry.centroid.to_crs(4326)   # centroid in metric CRS, then back
        cents += [(float(c.x), float(c.y)) for c in c4326]
    if not cents:
        return {"available": False}
    import random                                    # cap the points fed to EE so the lookup is quick
    if len(cents) > max_points:
        random.Random(0).shuffle(cents)
        cents = cents[:max_points]
    import config
    ee = config.ee_init()
    pts = ee.FeatureCollection([ee.Feature(ee.Geometry.Point(list(c))) for c in cents])
    gaul = ee.FeatureCollection("FAO/GAUL/2015/level2")   # districts (ADM2) with their state (ADM1)
    joined = ee.Join.saveFirst(matchKey="g").apply(
        pts, gaul, ee.Filter.intersects(leftField=".geo", rightField=".geo"))
    tagged = joined.map(lambda f: f.set("st", ee.Feature(f.get("g")).get("ADM1_NAME"))
                                   .set("di", ee.Feature(f.get("g")).get("ADM2_NAME")))
    junk = {"administrative unit not available", "name unknown", "water body", ""}
    def clean(names):
        return sorted({n for n in (names or []) if n and n.strip().lower() not in junk})
    states = clean(tagged.aggregate_array("st").distinct().getInfo())
    districts = clean(tagged.aggregate_array("di").distinct().getInfo())
    return {"available": True, "states": states, "districts": districts, "n_points": len(cents)}


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
    """The shared feature-source card a model points to as its inference dataset. `source` picks
    which one: Alpha Earth (the EE band-math default) or Tessera (the 128-d local embedding, #16).

    type=inference: it describes the *inputs* a model consumes, not labels. Idempotent — written
    once per source, reused by every model card that runs on it. Returns the card id."""
    if source == "tessera":
        return _ensure_tessera_inference_card(year)
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
        "embedding": {"source": "alphaearth", "dim": 64, "year": year},
        "provenance": {"annotator": "Google DeepMind / Alpha Earth", "method": "learned embedding",
                       "evidence": ["GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"], "license": None},
        "version": 1, "created": _now(),
    })
    return AE_INFERENCE_ID


def _ensure_tessera_inference_card(year=2024):
    """The Tessera feature-source card (#16). Tessera is a downloaded 128-d embedding, only usable
    for 2024 over India, so it is a distinct inference dataset from Alpha Earth. A Tessera-trained
    split points at this card, so the zoo shows Tessera as a first-class feature source."""
    if get_card(TE_INFERENCE_ID):
        return TE_INFERENCE_ID
    write_card({
        "id": TE_INFERENCE_ID,
        "name": "Tessera annual embeddings (128-d) — model input features",
        "description": "The 128-d Tessera embedding, downloaded as 0.1 degree tiles and sampled at "
                       "10 m. Usable for 2024 over India; a local feature source, not served in EE. "
                       "No labels — this is an inference input.",
        "type": "inference",
        "kind": "embedding_table",
        "definition": {"type": "embedding_table", "source": "geotessera",
                       "note": "0.1 degree tiles downloaded on demand; 2024 over India"},
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2024}},
        "embedding": {"source": "tessera", "dim": 128, "year": 2024},
        "provenance": {"annotator": "Tessera (geotessera)", "method": "learned embedding",
                       "evidence": ["geotessera"], "license": None},
        "version": 1, "created": _now(),
    })
    return TE_INFERENCE_ID


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
    years = bundle.get("years") or []
    name = ("Core Stack base map — 4-class LULC (India)" if is_root
            else f"{tree[node]['name']} split ({' / '.join(classes)})")
    # a multi-year split (#3) gets its training years in the name so it's distinct from the
    # single-year model at the same node (both produce the same classes)
    if not is_root and sorted(years) not in ([], [2024]):
        name += f" [years {', '.join(str(y) for y in sorted(years))}]"
    # a Tessera split stores features == "tessera"; it points at the Tessera feature-source card so
    # the zoo lists Tessera as a real inference dataset, and it can't replay as EE band math.
    is_te = bundle.get("features") == "tessera"
    inf_id = ensure_inference_dataset_card("tessera") if is_te else ensure_inference_dataset_card()
    card = {
        "id": f"mc_{node}_v1",
        "name": name,
        "node": node,
        "parent_class": None if is_root else (tree[node].get("parent") or node),
        "topology": "base_pooled" if is_root else "per_node_split",
        "produces": [{"class": c} for c in classes],
        "training": {
            "datasets": [d for d in training_ds_ids if d],
            # the actual embedding + winning estimator this split used (#16/#17); base stays AE/SVC
            "embedding": ({"source": "tessera", "dim": 128} if is_te
                          else {"source": "alphaearth", "dim": 64}),
            "algo": f"StandardScaler->{bundle.get('algo', 'linearsvc')}" if not is_root
                    else "StandardScaler->LinearSVC",
            "class_weight": None if is_root else "balanced",
            "balancing": ({"method": "worldcover_upweight", "wc_weight": bundle.get("wc_weight", 2)}
                          if is_root else {"method": _BALANCE_METHOD.get(bundle.get("balance"),
                                           "class_weight_balanced"), "residual_cap": 8000}),
        },
        "inference": {"dataset": inf_id,
                      "embedding": ({"source": "tessera", "dim": 128, "year": 2024} if is_te
                                    else {"source": "alphaearth", "dim": 64, "year": 2024})},
        "extent": {"spatial": {"type": "bbox", "value": extent_bbox or INDIA_BBOX},
                   "temporal": {"year": 2024}},
        "metrics": metrics or _metrics_from_report(bundle.get("report"), bundle.get("n_test")),
        "artifact": {"path": _artifact_path(node), "format": "sklearn-joblib"},
        # a Tessera split can't replay as EE band math (point-grid only), so it won't ride the tile map
        "deployment": {"ee_asset": None, "tile_url": None,
                       "expressible_as_bandmath": not is_te},
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
        "name": "WorldCover base — 7-class LULC (India)",
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
        "about": {"description": "WorldCover base: the well-supported India classes "
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


def mint_rule_card(node, rule):
    """Mint a local Model Card for a rule split (#12). Like a merge, a rule isn't a trained
    classifier — it's an interpretable expression over index variables (NDVI, slope, ...) — so it
    carries no joblib. But it's still a model the user built and can share, and it renders as EE
    band math, so it earns a card. `produces` the rule's classes; records the expression and the
    registry variables it reads, so the zoo shows *why* each pixel goes where it does."""
    import rules
    classes = rules.rule_classes(rule)
    used = sorted({v for c in rule.get("clauses", []) for v in rules.vars_in(c["when"])})
    ae_id = ensure_inference_dataset_card()
    card_id = f"mc_{node}_rule_v1"
    human = " ; ".join(f"if {c['when']} → {c['class']}" for c in rule.get("clauses", []))
    human = (human + f" ; else → {rule.get('default')}") if human else ""
    write_card({
        "id": card_id,
        "name": f"Rule split: {node} ({' / '.join(classes)})",
        "node": node,
        "parent_class": (hierarchy.load().get(node) or {}).get("parent") or hierarchy.ROOT,
        "topology": "rule_split",
        "produces": [{"class": c} for c in classes],
        # no labelled training data — the split is defined by a threshold rule, not learned
        "training": {"datasets": [], "algo": "index rule (no training)",
                     "balancing": {"method": "none"}},
        "inference": {"dataset": ae_id, "embedding": {"source": "sentinel2+srtm indices", "dim": len(used)}},
        "extent": {"spatial": {"type": "bbox", "value": INDIA_BBOX}, "temporal": {"year": 2024}},
        "metrics": {"note": "rule-based split; no held-out metric — behaviour is the expression itself"},
        "artifact": {"path": "data/hierarchy.json", "format": "rule-expression"},
        "deployment": {"ee_asset": None, "tile_url": None, "expressible_as_bandmath": True},
        "lineage": {"base_model": None, "derived_from": None},
        "rule": {"clauses": rule.get("clauses"), "default": rule.get("default"),
                 "variables": used, "expression": human},
        "about": {"description": f"Splits {node} by rule — {human}.",
                  "intended_use": "An interpretable, training-free split over vegetation/water/"
                                  "terrain indices, evaluated live in Earth Engine.",
                  "limitations": "Only as good as the chosen thresholds; no learned calibration.",
                  "evidence": ""},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": ""},
        "version": 1, "created": _now(),
    })
    return card_id


def mint_water_card(bundle, extent_bbox=None, metrics=None, card_id="mc_water_fortnight_v1",
                    name="Seasonal water (per-fortnight, Sentinel-1/2)"):
    """Mint the Model Card for the per-fortnight water classifier (#5/#7): a flat binary model
    trained on raw Sentinel-1/2 features (not Alpha Earth), served as EE band math for a chosen
    date. Its training data is the shared seasonal-water polygons (ds_seasonal_water_v1). A distinct
    `card_id`/`name` cards the augmented variant separately (#11 wk10)."""
    classes = list(bundle.get("classes", ["non_water", "water"]))
    bands = bundle.get("feature_bands", [])
    ds = "ds_seasonal_water_v1"
    write_card({
        "id": card_id,
        "name": name,
        "node": "water_fortnight",
        "parent_class": "water",
        "topology": "flat_multiclass",
        "produces": [{"class": c} for c in classes],
        "training": {"datasets": [ds] if get_card(ds) else [],
                     "embedding": {"source": "sentinel1+2 fortnight", "dim": len(bands)},
                     "algo": bundle.get("algo", "linearsvc"), "balancing": {"method": "balanced"}},
        "inference": {"dataset": ds if get_card(ds) else None,
                      "embedding": {"source": "sentinel1+2 fortnight", "dim": len(bands),
                                    "bands": bands}},
        "extent": {"spatial": {"type": "bbox", "value": extent_bbox or INDIA_BBOX},
                   "temporal": {"note": "any fortnight with Sentinel coverage; date is a run param"}},
        "metrics": metrics or {"note": "held-out water/non_water accuracy printed by the trainer"},
        "artifact": {"path": ("data/refine/water_fortnight_augmented.joblib"
                              if "augmented" in card_id else "data/refine/water_fortnight.joblib"),
                     "format": "sklearn-joblib"},
        "deployment": {"ee_asset": None, "tile_url": None, "expressible_as_bandmath": True},
        "lineage": {"base_model": None, "derived_from": ds if get_card(ds) else None},
        "about": {"description": "Water vs non-water for a single fortnight, from raw Sentinel-1 SAR "
                                 "+ Sentinel-2 optical composited around a target date.",
                  "intended_use": "Which pixels held water on a given fortnight (e.g. 14 Jul) — the "
                                  "intra-annual water-seasonality signal the annual embedding can't give.",
                  "limitations": "One fortnight at a time; needs a cloud-lite S2 scene in the window; "
                                 "linear model, so it trades some accuracy for band-math serving.",
                  "evidence": ""},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": ""},
        "version": 1, "created": _now(),
    })
    return card_id


def mint_ee_rf_card(card_id, name, node, parent_class, classes, training_asset, feature_kind,
                    extent=None):
    """Mint a Model Card for an EE-native Random Forest ported from IndiaSAT (#13 wk10). Unlike our
    sklearn models these train + classify inside Earth Engine (server-side tiles), and they're
    re-trained on the fly from a stable training asset, so the card stores the *recipe* (asset +
    feature source + RF params + class map) rather than a joblib. `feature_kind` is 'sar_ts' (tree
    vs crop) or 'alphaearth' (farm/shrub/plantation)."""
    src = "Sentinel-1 SAR 16-day time series" if feature_kind == "sar_ts" else "Alpha Earth embedding"
    write_card({
        "id": card_id,
        "name": name,
        "node": node,
        "parent_class": parent_class,
        "topology": "ee_rf",
        "produces": [{"class": c} for c in classes],
        "training": {"datasets": [], "embedding": {"source": feature_kind},
                     "algo": "smileRandomForest(100)", "training_asset": training_asset},
        "inference": {"dataset": None, "embedding": {"source": feature_kind}},
        "extent": {"spatial": {"type": "bbox", "value": extent or INDIA_BBOX},
                   "temporal": {"note": "trained on the fly per request; year/date is a run param"}},
        "metrics": {"note": "server-side EE Random Forest (IndiaSAT production model); "
                            "trained in Earth Engine, not held out here"},
        "artifact": {"path": f"ee://{training_asset}",
                     "format": "ee-smileRandomForest (recipe, re-trained on demand from the asset)"},
        "deployment": {"ee_asset": training_asset, "tile_url": None, "expressible_as_bandmath": False},
        "lineage": {"base_model": None, "derived_from": training_asset},
        "about": {"description": f"IndiaSAT/CoRE-stack {name}. An Earth-Engine Random Forest on the "
                                 f"{src}, trained + classified server-side and served as map tiles.",
                  "intended_use": "Split a vegetation class using the lab's production classifier "
                                  "instead of a locally-trained one.",
                  "limitations": "Re-trained per request in EE; renders as its own overlay (full "
                                 "hierarchy compositing is a follow-up); needs read access to the "
                                 "training asset.",
                  "evidence": ""},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": "IndiaSAT (Raman)"},
        "version": 1, "created": _now(),
    })
    return card_id


def sync_ee_rf_cards():
    """Ensure the two ported IndiaSAT EE-RF models are carded in the zoo (#13 wk10)."""
    import ee_rf
    specs = [
        ("mc_treecrop_ee_v1", "Tree vs crop (IndiaSAT SAR RF)", "treecrop", "greenery",
         ["cropland", "tree"], ee_rf.TREECROP_ASSET, "sar_ts"),
        ("mc_farmshrub_ee_v1", "Farm / plantation / scrubland (IndiaSAT AEZ RF)", "farmshrub",
         "greenery", list(ee_rf.FARMSHRUB_MAP.values()), ee_rf.FARMSHRUB_SAMPLES, "alphaearth"),
    ]
    for cid, name, node, parent, classes, asset, kind in specs:
        if get_card(cid):
            continue
        try:
            mint_ee_rf_card(cid, name, node, parent, classes, asset, kind)
        except Exception:
            pass


def delete_card(card_id, purge_artifacts=False):
    """Remove a card file and refresh the index (used when a merge is undone, or a user drops a
    superseded/dummy model from the zoo #9). Idempotent.

    With `purge_artifacts`, also unlink the card's joblib copies — but only the *archived* snapshot
    (data/refine/archive/) and the *published* copy (data/catalogue/artifacts/), never a live model
    at data/refine/<node>.joblib or data/model_*.joblib that another card still points at."""
    card = get_card(card_id)
    if purge_artifacts and card:
        for p in [(card.get("artifact") or {}).get("path"),
                  (card.get("artifact") or {}).get("published_path")]:
            if not p:
                continue
            # normalize; a published_path is relative to the catalogue dir, others to the repo root
            fp = (CATALOGUE_DIR / p) if not str(p).startswith("data/") else (ROOT / p)
            safe = ("refine/archive/" in str(p).replace("\\", "/")
                    or "/artifacts/" in str(fp).replace("\\", "/"))
            if safe and fp.exists():
                try:
                    fp.unlink()
                except OSError:
                    pass
    path = _dir_for(card_id) / f"{card_id}.json"
    if path.exists():
        path.unlink()
        rebuild_index()
    return card_id


# ----------------------------- archive a replaced split model (so nothing vanishes) -----------------------------
# A node holds ONE classifier (one joblib, one mc_<node>_v1 card). Re-splitting the node — e.g.
# turning greenery from tea/non_tea into acacia/non_acacia — used to silently overwrite both, so the
# old model disappeared from the zoo. These keep the superseded model as its own archived card.

def snapshot_model(node):
    """Copy a node's current classifier joblib aside so a retrain can't destroy it. Returns the
    archived repo-relative path, or None if the node has no live joblib to snapshot."""
    import shutil, time
    src = ROOT / _artifact_path(node)
    if node == hierarchy.ROOT or not src.exists():
        return None
    arch = ROOT / "data" / "refine" / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    dst = arch / f"{node}__{int(time.time())}.joblib"
    shutil.copy2(src, dst)
    return str(dst.relative_to(ROOT)).replace("\\", "/")


def discard_snapshot(path):
    """Drop a snapshot we decided not to keep (the retrain didn't actually change the split)."""
    if path:
        try:
            (ROOT / path).unlink()
        except OSError:
            pass


def archive_prev_card(node, prev_card, archived_path):
    """Keep a superseded split model in the zoo as a distinct, archived card pointing at the
    snapshotted joblib, so re-splitting a node doesn't make its old model vanish. `prev_card` is the
    node's model card as it was *before* the retrain (correct old classes/metrics/extent)."""
    import copy
    if not prev_card or not archived_path:
        return None
    k = 1
    while (MODELS_DIR / f"mc_{node}_prev{k}_v1.json").exists():
        k += 1
    old_classes = [p["class"] for p in prev_card.get("produces", [])]
    base_name = (prev_card.get("name") or f"{node} split").split(" split")[0]
    card = copy.deepcopy(prev_card)
    card["id"] = f"mc_{node}_prev{k}_v1"
    card["name"] = f"{base_name} split ({' / '.join(old_classes)}) — superseded"
    card["artifact"] = {"path": archived_path, "format": "sklearn-joblib"}
    card["about"] = {**(prev_card.get("about") or {}),
                     "description": f"A previous {node} split, kept after a newer model replaced it so it isn't lost.",
                     "limitations": "Archived reference model, not the live classifier for this node."}
    card["zoo"] = {**(prev_card.get("zoo") or {}), "published": False}
    card["lineage"] = {**(prev_card.get("lineage") or {}), "derived_from": f"mc_{node}_v1"}
    card.pop("created", None)          # write_card stamps a fresh created/version
    write_card(card)
    return card["id"]


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


def sync_node_model_cards():
    """Ensure every live split node has a model card, so nothing we trained silently misses the
    zoo (#9). Only mints for nodes whose card is *absent* — never overwrites an existing card, so
    user annotations (description / std mapping) are safe. Idempotent; called at startup."""
    import joblib
    tree = hierarchy.load()
    for node, n in tree.items():
        if node == hierarchy.ROOT or not n.get("classifier"):
            continue
        if get_card(f"mc_{node}_v1"):
            continue
        jb = ROOT / "data" / "refine" / f"{node}.joblib"
        if jb.exists():
            try:
                register_retrain(node, joblib.load(jb))
            except Exception:
                pass


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
    ensure_inference_dataset_card("tessera")     # Tessera shows as a feature-source card too (#16)

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
    # all polygons in one cell (occ==1) is fully clustered -> diversity 0. Guard it explicitly so we
    # don't return a stray -0.0 from -(1*log 1), which rendered as a broken-looking "-0.0" on the card.
    if n <= 1 or occ <= 1:
        return bbox, 0.0, occ
    if occ <= 1:
        return bbox, 0.0, occ                 # everything in one cell: zero spread (avoid -0.0)
    p = counts / counts.sum()
    entropy = -(p * np.log(p)).sum()
    return bbox, round(abs(float(entropy / np.log(n))), 3), occ


def _coverage(gdf, aoi_bbox):
    """Fraction of the AOI's area that sits inside a labelled polygon (#4).

    Sir's 'percentage of pixels for which training data is available', made contingent on the
    size of the area — the same crowns cover a big AOI thinly and a small one densely. We union
    the polygons, clip to the AOI, and divide areas in an equal-area CRS (EPSG:6933, meters), so
    it stays honest at any AOI scale. (A grid-cell count would collapse to 100% whenever the AOI
    is smaller than one cell, which is exactly the case for our small stress-test strips.)
    Returns a float in [0,1], or None when no AOI is supplied."""
    if not aoi_bbox:
        return None
    from shapely.geometry import box
    from shapely.ops import unary_union
    import geopandas as gpd
    w, s, e, n = aoi_bbox
    aoi = gpd.GeoSeries([box(w, s, e, n)], crs=4326).to_crs(6933).iloc[0]
    if aoi.area <= 0:
        return None
    # buffer(0) repairs self-intersecting/invalid crowns so the union doesn't blow up
    geoms = [g.buffer(0) for g in gdf.to_crs(6933).geometry if not g.is_empty]
    labelled = unary_union(geoms).intersection(aoi)
    return round(min(1.0, labelled.area / aoi.area), 4)


def recompute_spread(card_id, cell=0.25, aoi=None):
    """Re-run the spatial-diversity stat for a polygon-backed card at a user-chosen grid cell (#1),
    and (when an AOI bbox is given) how much of that AOI the labels actually cover (#4).

    The card's stored `quality.spatial_diversity` was computed at a fixed 0.25-degree grid; this
    lets the UI ask 'how spread is this at, say, 0.1 degrees?' without re-minting. Reads the card's
    actual polygons (all positives, not just the prominent few) via the same paths card_geometry uses,
    then reuses _geojson_stats with the requested cell. `aoi` is (w,s,e,n) — the box about to be
    classified — used to report coverage relative to it. Returns None if the card has no polygons."""
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
        # the card points at polygon files that aren't on disk (e.g. archived by a "start fresh").
        # Say so, instead of a bare None that reads as a hard error on the card.
        return {"cell": cell, "spatial_diversity": None, "occupied_cells": 0,
                "n_polygons": 0, "coverage": None, "missing": True}
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    feats = [{"type": "Feature", "properties": {}, "geometry": geom.__geo_interface__}
             for geom in gdf.geometry]
    _bbox, div, occ = _geojson_stats(feats, cell=cell)
    return {"cell": cell, "spatial_diversity": div, "occupied_cells": occ,
            "n_polygons": len(feats), "coverage": _coverage(gdf, aoi)}


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
