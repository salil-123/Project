"""FastAPI backend for the Core Stack LULC web interface.

Serves the 10 m classifier and the hierarchy-editing loop: view the class tree, add
example polygons (drawn or uploaded), grow it with SPLIT/ADD at any level, and retrain
a node on the fly. Plain HTML/CSS/JS frontend in ./static talks to these JSON endpoints.

Operations run synchronously (FastAPI runs sync handlers in a threadpool, so a slow
GEE+train call doesn't block other requests); the UI shows a "working…" state.

Run (from the repo root):  uvicorn backend:app --reload --app-dir src
Then open http://127.0.0.1:8000/
"""
import sys
import tempfile
from pathlib import Path

# repo root holds shared infra (config.py, tessera_fast.py) + the data/ dir; put it
# on the path so infer can import them whichever directory uvicorn is launched from.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import hierarchy
import examples
import infer
import refine
import catalogue
import zoo_git
import oplog
import merges

_STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Core Stack LULC")

# loaded once at startup and refreshed after any mutating op (see _reload)
_model = infer.load_model()
_softvote = infer.load_softvote()
_refinements = infer.load_refinements()

# the zoo is a git-backed card DB; make sure it's a repo and seeded from what's on disk
zoo_git.init_local()
if not catalogue.INDEX_PATH.exists():
    catalogue.backfill()
catalogue.sync_merge_cards()        # any active merge gets a local model card, even older ones (#9)

PRESETS = {
    "IIT Bombay (urban)":      [72.905, 19.123, 72.925, 19.143],
    "Man Sagar Lake, Jaipur":  [75.835, 26.945, 75.857, 26.963],
    "Pune (mixed)":            [73.84, 18.50, 73.88, 18.54],
    "N. Karnataka (dev area)": [74.98, 15.39, 75.09, 15.47],
    # Upper Assam tea belt — has both tea and non-tea ground truth, so a trees->tea/non-tea
    # split shows the distinction on the map without typing coordinates (today's demo).
    "Assam tea belt (tea/non-tea)": [95.75, 27.55, 95.98, 27.73],
}


def _reload():
    """Re-read the base model + splits so the next classify reflects a just-made change."""
    global _model, _refinements
    _model = infer.load_model()
    _refinements = infer.load_refinements()


def _tree_payload():
    tree = hierarchy.load()
    return {"tree": tree, "leaves": hierarchy.leaves(tree), "colors": infer.load_colors()}


@app.get("/api/health")
def health():
    return {"status": "ok", "classes": _model.get("classes"),
            "wc_weight": _model.get("wc_weight")}


@app.get("/api/presets")
def presets():
    return {"presets": PRESETS, "colors": infer.load_colors()}


@app.get("/api/tree")
def get_tree():
    return _tree_payload()


# ----------------------------- save / reload a scheme (#4) -----------------------------
# The user's invented class scheme is just the hierarchy + the ordered steps that built it. We
# let them download it as JSON and load it back later, so they can pick up where they left off
# without us maintaining logins/sessions — the file IS their save. Trained split artifacts live
# on disk / in the zoo; the export references them and import rebinds to whatever's present.
class HierarchyImportIn(BaseModel):
    hierarchy: dict
    op_log: list | None = None
    classifier_refs: dict | None = None


def _classifier_refs(tree):
    """For each node carrying a trained classifier, where its artifact + zoo card live."""
    refs = {}
    for cls, node in tree.items():
        clf = node.get("classifier")
        if clf:
            refs[cls] = {"artifact": f"data/refine/{clf}.joblib", "card": f"mc_{clf}_v1"}
    return refs


@app.get("/api/hierarchy/export")
def export_hierarchy():
    """Download the current scheme: the tree, the op-log that built it, and pointers to each
    node's trained artifact (#4). Lightweight JSON — the artifacts themselves stay in the zoo."""
    tree = hierarchy.load()
    return {"hierarchy": tree, "op_log": oplog.load(), "classifier_refs": _classifier_refs(tree)}


@app.post("/api/hierarchy/import")
def import_hierarchy(body: HierarchyImportIn):
    """Restore a previously-saved scheme (#4): validate + install the tree, restore its op-log,
    and rebind classifiers to artifacts present on disk. Splits whose artifact is missing are
    reported so the user can retrain them (their structure is still there)."""
    tree = body.hierarchy
    try:
        hierarchy.validate(tree)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"invalid hierarchy: {e}")
    hierarchy.save(tree)
    oplog.replace(body.op_log or [])
    _reload()
    missing = [cls for cls, node in tree.items()
               if node.get("classifier") and node["classifier"] != hierarchy.ROOT
               and not (_ROOT / "data" / "refine" / f"{node['classifier']}.joblib").exists()]
    oplog.append("import_hierarchy", {"nodes": len(tree), "missing": missing})
    return {"imported": True, "missing_classifiers": missing, **_tree_payload()}


# the inference feature source's coverage, exposed to the UI as a pick-list (#7). Alpha Earth
# has annual mosaics; Tessera only has usable India coverage in 2024, so Detailed is locked to it.
AE_YEARS = list(range(2017, 2025))
TESSERA_YEARS = [2024]


@app.get("/api/inference-options")
def inference_options():
    """What inference data the user can pick (#7): the feature source + the years it covers.

    The trained models are linear on Alpha Earth's temporally-consistent embeddings, so a model
    fit on 2024 still classifies an earlier year's features — we just sample the chosen year."""
    return {"realistic": {"source": "alphaearth", "years": AE_YEARS, "default": 2024},
            "detailed": {"source": "alphaearth + tessera", "years": TESSERA_YEARS, "default": 2024}}


@app.get("/api/classify")
def classify(west: float, south: float, east: float, north: float,
             n: int = 30, mode: str = "realistic", year: int = 2024):
    """Classify a bbox for the map overlay.

    mode = "realistic" -> AE + WorldCover classified server-side at native 10 m and served as
                          Earth Engine map TILES (an XYZ url). Crisp at any zoom, no download.
    mode = "detailed"  -> prior-aware AE soft-voted with Tessera, drawn as a coarse
                          cell grid. Downloads the area's Tessera tiles on demand.

    `year` picks the inference data's temporal slice (#7): Alpha Earth 2017-2024 for Realistic;
    Detailed is pinned to 2024 (Tessera's only India coverage). Same model either way.
    """
    bbox = (west, south, east, north)
    if mode == "detailed":
        year = 2024                                  # Tessera coverage; ignore any other ask
        n = max(8, min(n, 60))
        df, cw, ch = infer.classify_bbox_softvote(bbox, n=n, year=year, model_bundle=_softvote,
                                                  refinements=_refinements)
        cells = [{"lat": float(r.lat), "lon": float(r.lon), "pred": r.pred}
                 for r in df.itertuples()]
        return {"render": "cells", "cells": cells, "cell_w": cw, "cell_h": ch,
                "mode": mode, "year": year, "counts": df.pred.value_counts().to_dict(),
                "colors": infer.load_colors()}

    year = min(max(year, AE_YEARS[0]), AE_YEARS[-1])  # clamp to Alpha Earth's coverage
    tile_url, counts = infer.classify_bbox_tiles(bbox, year=year, model_bundle=_model,
                                                 refinements=_refinements)
    return {"render": "tiles", "tile_url": tile_url, "bounds": [west, south, east, north],
            "mode": mode, "year": year, "counts": counts, "colors": infer.load_colors()}


# ----------------------------- examples -----------------------------
class ExampleIn(BaseModel):
    node: str
    geometry: dict
    role: str = "positive"


def _mint_dataset(node, role):
    """A positive add defines/updates that class's training Dataset Card right away, so the data
    shows up in the zoo the moment you add it (not only after a retrain). Returns the card id."""
    if role != "positive":
        return None
    try:
        return catalogue.mint_training_dataset_card(node)
    except Exception:
        return None     # never fail an add over its card


@app.get("/api/examples/summary")
def examples_summary():
    """Per-class example counts (positive/negative) — drives the live 'data so far' distribution
    + balance guideline shown right where the user adds data."""
    return examples.summary()


@app.post("/api/examples")
def add_example(ex: ExampleIn):
    """Attach a drawn geometry to a class. positive = 'this is X' (relabel); negative =
    'this is not X' (hard-negative)."""
    try:
        total = examples.add_examples(ex.node, ex.geometry, role=ex.role)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"node": ex.node, "role": ex.role, "total": total,
            "dataset": _mint_dataset(ex.node, ex.role)}


@app.post("/api/examples/upload")
def upload_examples(node: str = Form(...), role: str = Form("positive"),
                    file: UploadFile = File(...)):
    """Same, but from an uploaded GeoJSON/KML of polygons."""
    suffix = Path(file.filename or "upload.geojson").suffix or ".geojson"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        path = tmp.name
    try:
        total = examples.add_examples(node, path, role=role)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"node": node, "role": role, "total": total, "file": file.filename,
            "dataset": _mint_dataset(node, role)}


# ----------------------------- tree operations -----------------------------
class SplitIn(BaseModel):
    parent: str
    children: list  # [{name, color?}] or [name, ...]


class AddIn(BaseModel):
    parent: str
    name: str
    color: str | None = None


class RetrainIn(BaseModel):
    node: str
    balance: str = "balanced"          # balanced (class weight) | undersample | oversample (#6)


@app.post("/api/split")
def split(op: SplitIn):
    """Create the children of a SPLIT (no training yet — add examples, then retrain)."""
    try:
        refine.split_op(op.parent, op.children, do_train=False)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    oplog.append("split", {"parent": op.parent, "children": op.children})
    return _tree_payload()


@app.post("/api/add")
def add(op: AddIn):
    """Add a class under a node (no training yet — add examples, then retrain)."""
    try:
        refine.add_class_op(op.parent, op.name, new_color=op.color, do_train=False)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    oplog.append("add", {"parent": op.parent, "name": op.name, "color": op.color})
    return _tree_payload()


@app.post("/api/retrain")
def retrain(op: RetrainIn):
    """Train (or retrain) the classifier that resolves `node`'s children, then make the
    new model live. Returns the held-out metrics. Slow: samples embeddings + fits."""
    try:
        bundle = refine.retrain(op.node, balance=op.balance)
    except ValueError as e:                  # e.g. a child has no examples yet
        raise HTTPException(400, str(e))
    _reload()
    # mint/refresh the model + dataset cards for this node so the zoo tracks it
    cards = catalogue.register_retrain(op.node, bundle)
    oplog.append("retrain", {"node": op.node, "balance": op.balance}, result=cards)
    return {"node": op.node, "classes": bundle.get("classes"),
            "report": bundle.get("report"), "n_test": bundle.get("n_test"),
            "cards": cards, **_tree_payload()}


# ----------------------------- base-class scheme picker (#5) -----------------------------
class BaseIn(BaseModel):
    scheme: str            # indiasat | worldcover


@app.get("/api/base")
def get_base():
    """Which base scheme is live + the schemes on offer (#5)."""
    return {"active": infer.active_base().get("scheme", "indiasat"),
            "schemes": {
                "indiasat": {"label": "IndiaSAT (4 classes)",
                             "classes": [c for c, _, _ in hierarchy._BASE]},
                "worldcover": {"label": "WorldCover (effective)",
                               "classes": [canon for _, canon, _, _ in refine.WC_BASE]}}}


def _switch_base(scheme):
    """Reseed the tree to a base scheme and make its model live (#5). Shared by the base picker
    and 'apply' of a base card. Destructive by design: backs the current tree up to
    hierarchy.prev.json, then clears splits/merges so the user starts fresh from the new base.
    Raises ValueError on an unknown scheme. The WorldCover model is trained (and carded) on first use."""
    try:
        import shutil
        if Path(hierarchy.HIERARCHY_PATH).exists():
            shutil.copy(hierarchy.HIERARCHY_PATH, str(_ROOT / "data" / "hierarchy.prev.json"))
    except Exception:
        pass

    if scheme == "worldcover":
        if not (_ROOT / refine.WORLDCOVER_BASE_PATH).exists():
            refine.train_worldcover_base()
        catalogue.mint_worldcover_base_card()         # ensure it's a selectable card in the zoo
        bundle = infer.load_model(refine.WORLDCOVER_BASE_PATH)
        names = {canon: name for _, canon, name, _ in refine.WC_BASE}
        colors = {canon: color for _, canon, _, color in refine.WC_BASE}
        tree = hierarchy.seed_from_classes(bundle["classes"], names=names, colors=colors)
        infer.set_active_base("worldcover", refine.WORLDCOVER_BASE_PATH)
    elif scheme == "indiasat":
        tree = hierarchy._seed()
        infer.set_active_base("indiasat", infer.MODEL_PATH)
    else:
        raise ValueError(f"unknown base scheme {scheme!r}")

    hierarchy.save(tree)
    merges.save([])                                   # old merges referenced old leaves
    _reload()
    return scheme


@app.post("/api/base/select")
def select_base(op: BaseIn):
    """Switch the starting base classes (#5): IndiaSAT-4 or the effective WorldCover base."""
    try:
        _switch_base(op.scheme)
    except ValueError as e:
        raise HTTPException(400, str(e))
    oplog.append("base_select", {"scheme": op.scheme})
    return {"scheme": op.scheme, **_tree_payload()}


# ----------------------------- merge / cross-model relabel (#9) -----------------------------
class MergeIn(BaseModel):
    name: str
    sources: list           # leaf class ids to collapse (>=2, ideally from different models)
    color: str | None = None


@app.get("/api/merge")
def list_merges():
    """The active merge rules + the colour map (merge targets included)."""
    return {"rules": merges.load(), "colors": infer.load_colors()}


@app.post("/api/merge")
def add_merge(op: MergeIn):
    """Define a new class by relabelling chosen leaves from different models into it (#9). It's a
    post-inference correction layer — no retraining — so the map reflects it on the next classify.
    A merge is still a model the user built, so it also mints a local model card in the zoo."""
    try:
        rule = merges.add(op.name, op.sources, color=op.color)
    except ValueError as e:
        raise HTTPException(400, str(e))
    card = None
    try:
        card = catalogue.mint_merge_card(rule)     # never fail the merge over its card
    except Exception:
        pass
    oplog.append("merge", {"target": rule["target"], "name": rule["name"],
                           "sources": rule["sources"]}, result={"model": card})
    return {"rule": rule, "card": card, **_tree_payload()}


@app.delete("/api/merge/{target}")
def del_merge(target: str):
    rules = merges.remove(target)
    try:
        catalogue.delete_card(f"mc_merge_{target}_v1")     # drop the merge's local card too
    except Exception:
        pass
    oplog.append("merge_remove", {"target": target})
    return {"rules": rules, **_tree_payload()}


# ----------------------------- use a model from the zoo -----------------------------
def _drop_subtree(tree, cls):
    """Remove a node and everything under it from the live tree (cards/files stay on disk)."""
    for ch in list(tree.get(cls, {}).get("children", [])):
        _drop_subtree(tree, ch)
    tree.pop(cls, None)


class ApplyIn(BaseModel):
    card_id: str


@app.post("/api/apply")
def apply_model(op: ApplyIn):
    """Make a zoo model live on the map. A split model registers its trained classifier on its
    hierarchy node (so inference composites it); the base model resets the map to the 4 classes.
    This is what turns the catalogue into something you can actually *use*."""
    card = catalogue.get_card(op.card_id)
    if not card or not op.card_id.startswith("mc_"):
        raise HTTPException(404, f"no model card {op.card_id!r}")
    node = card["node"]

    if card.get("topology") == "base_pooled" or node == hierarchy.ROOT:
        scheme = card.get("base_scheme", "indiasat")     # which base this card represents (#5)
        _switch_base(scheme)                             # reseed + make its model live
        oplog.append("apply", {"card_id": op.card_id, "node": node, "base_scheme": scheme})
        return {"applied": op.card_id, "node": node, **_tree_payload()}

    artifact = (card.get("artifact") or {}).get("path")
    if not artifact or not (_ROOT / artifact).exists():
        raise HTTPException(400, "this model's trained artifact isn't available locally")

    tree = hierarchy.load()
    if node not in tree:
        raise HTTPException(400, f"node {node!r} is not in the hierarchy")
    # rebuild the node's children to exactly the model's classes, then register its classifier
    for ch in list(tree[node].get("children", [])):
        _drop_subtree(tree, ch)
    tree[node]["children"] = []
    for cls in (p["class"] for p in card.get("produces", [])):
        hierarchy.add_class(tree, cls.replace("_", " ").title(), node, canonical=cls)
    tree[node]["classifier"] = node              # load_refinements -> data/refine/<node>.joblib
    hierarchy.save(tree)
    _reload()
    oplog.append("apply", {"card_id": op.card_id, "node": node})
    return {"applied": op.card_id, "node": node,
            "classes": [p["class"] for p in card.get("produces", [])], **_tree_payload()}


# ----------------------------- catalogue (the model/dataset zoo) -----------------------------
@app.get("/api/catalogue")
def get_catalogue(west: float = None, south: float = None,
                  east: float = None, north: float = None, interest: str = None):
    """The zoo index. With a bbox, returns just the models valid for that area (#3)."""
    if None not in (west, south, east, north):
        return {"models": catalogue.models_for_aoi((west, south, east, north), interest)}
    return catalogue.load_index()


@app.get("/api/cards/{card_id}")
def get_card(card_id: str):
    card = catalogue.get_card(card_id)
    if not card:
        raise HTTPException(404, f"no card {card_id!r}")
    if card_id.startswith("mc_"):                 # attach the placement hint (#2), not persisted
        card = {**card, "recommendation": catalogue.recommend_placement(card)}
    return card


@app.get("/api/standards")
def standards():
    """The standard LULC vocabularies (WorldCover / USDA) offered as a pick-list for class mapping."""
    return catalogue.STANDARDS


@app.get("/api/cards/{card_id}/spread")
def card_spread(card_id: str, cell: float = 0.25):
    """Recompute a polygon dataset's spatial-diversity at a user-chosen grid cell (#1).

    Lets the user dial the grid the spread is measured on (sir's ask) without re-minting the card.
    Returns 404 for a card with no polygons (feature sources have nothing to bin)."""
    cell = max(0.01, min(cell, 5.0))     # keep it sane: 0.01-5 degrees
    out = catalogue.recompute_spread(card_id, cell=cell)
    if out is None:
        raise HTTPException(404, "no polygons to measure spread for this card")
    return out


@app.get("/api/cards/{card_id}/geometry")
def get_card_geometry(card_id: str):
    """The card's actual polygons (for polygon datasets / a model's polygon training data) so the
    map shows the real footprint instead of a country-sized box. Feature sources -> drawable:false."""
    return catalogue.card_geometry(card_id)


class AnnotateIn(BaseModel):
    about: dict | None = None              # description / intended_use / limitations / evidence
    contributor: str | None = None
    std_mapping: dict | None = None        # {class: {worldcover, usda, iucn}}
    source_url: str | None = None          # public link for a dataset card (#8b), set per-card here


@app.post("/api/cards/{card_id}/annotate")
def annotate_card(card_id: str, body: AnnotateIn):
    """Let the user describe a model, give evidence, and map its classes to a standard LULC
    scheme (#8, #13-15). For a dataset card it also carries the public source link (#8b) so the
    user attaches it right here, not in a publish-time prompt. Merges, re-validates, rewrites."""
    try:
        return catalogue.update_card_meta(card_id, about=body.about, contributor=body.contributor,
                                          std_mapping=body.std_mapping, source_url=body.source_url)
    except KeyError:
        raise HTTPException(404, f"no card {card_id!r}")


class PublishIn(BaseModel):
    card_ids: list | None = None
    message: str | None = None
    contributor: str | None = None      # github handle / email of whoever's sharing (#6)
    dataset_links: dict | None = None   # {ds_id: public_url} captured at publish time (#8b)


@app.post("/api/publish")
def publish(op: PublishIn):
    """Commit the cards + index and push to the shared zoo repo (git-backed DB). Records the
    contributor (#6), the published model binaries (#8a), and any public dataset links the user
    gave for the data sources (#8b)."""
    return zoo_git.publish(op.card_ids, message=op.message, contributor=op.contributor,
                           dataset_links=op.dataset_links)


@app.get("/api/zoo/status")
def zoo_status():
    """What's local vs published — drives the 'N local / N published' badge."""
    return zoo_git.status()


# serve the frontend (mount last so /api/* wins)
@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/", StaticFiles(directory=_STATIC), name="static")
