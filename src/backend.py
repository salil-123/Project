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
import validate_ops
import aoi
import stacd

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
catalogue.sync_node_model_cards()   # every live split node gets a card so nothing trained is hidden (#9)
catalogue.sync_ee_rf_cards()        # the two ported IndiaSAT EE-RF models get cards (#13 wk10)

# The IIT Delhi strip is our home turf and the default area: IIT built-up, Sanjay Van trees + a
# small water body, and the acacia/non-acacia crowns all sit inside this box. Order matters — the
# UI selects the first entry on load, so this is what the map shows on arrival.
PRESETS = {
    "IIT Delhi + Sanjay Van (acacia)": [77.165, 28.520, 77.205, 28.560],
    # Jharia coalfield — a real active coalfield, the positive control for the mining class (so the
    # mining segments here are genuine, unlike Asola which is reclaimed and reads as false positives).
    "Jharia coalfield (active mining)": [86.23, 23.62, 86.41, 23.80],
    # Asola Bhatti — old mines reclaimed into built-up + acacia; a false-positive probe, not real mines.
    "Asola Bhatti (reclaimed/acacia)": [77.19, 28.42, 77.27, 28.48],
    # Jalpaiguri — where we demo starting from an IndiaSAT/WorldCover base then splitting/adding.
    "Jalpaiguri (base-scheme demo)": [88.68, 26.48, 88.78, 26.56],
    # Upper Assam tea belt — has both tea and non-tea ground truth, so a trees->tea/non-tea split
    # shows the distinction on the map without typing coordinates.
    "Assam tea belt (tea/non-tea)": [95.75, 27.55, 95.98, 27.73],
    "Man Sagar Lake, Jaipur":  [75.835, 26.945, 75.857, 26.963],
}


def _reload():
    """Re-read the base model + splits so the next classify reflects a just-made change."""
    global _model, _refinements, _tree_mtime
    _model = infer.load_model()
    _refinements = infer.load_refinements()
    _tree_mtime = _hierarchy_mtime()


def _hierarchy_mtime():
    try:
        return (_ROOT / "data" / "hierarchy.json").stat().st_mtime
    except OSError:
        return 0.0


_tree_mtime = _hierarchy_mtime()


def _maybe_reload():
    """Pick up hierarchy/split changes made on disk while the server is running — e.g. a script like
    week3/scripts/add_mining.py that adds the mining split. Without this the in-memory refinements
    stay stale until a UI op triggers a reload, so a script-made split silently doesn't show. Cheap:
    one mtime stat; reload only when hierarchy.json is newer than our last load."""
    global _tree_mtime
    m = _hierarchy_mtime()
    if m and m > _tree_mtime:
        _reload()   # _reload() also refreshes _tree_mtime


def _tree_payload():
    _maybe_reload()
    tree = hierarchy.load()
    # op_seq = the current head of the op-log, so the client can anchor a "session" to it and
    # export only the ops that happened since (#4).
    return {"tree": tree, "leaves": hierarchy.leaves(tree), "colors": infer.load_colors(),
            "op_seq": len(oplog.load())}


@app.get("/api/health")
def health():
    return {"status": "ok", "classes": _model.get("classes"),
            "wc_weight": _model.get("wc_weight")}


@app.get("/api/presets")
def presets():
    return {"presets": PRESETS, "colors": infer.load_colors()}


# Tessera training is scoped to the sites we requested bboxes for from the GeoTessera (UCam) team —
# those are the areas with prepared coverage. The UI only offers the Tessera embedding for these (#16).
TESSERA_SITES = {
    "IIT Delhi + Sanjay Van (acacia)": [77.165, 28.520, 77.205, 28.560],
    "Asola Bhatti (mining/acacia)":    [77.19, 28.42, 77.27, 28.48],
    "Jalpaiguri (base-scheme demo)":   [88.68, 26.48, 88.78, 26.56],
    "Assam tea belt (tea/non-tea)":    [95.75, 27.55, 95.98, 27.73],
}


@app.get("/api/tessera-sites")
def tessera_sites():
    """The bboxes Tessera training is available for (#16) — the 4 sites we requested GeoTessera
    coverage for. The UI shows the Tessera embedding option only when the AOI sits in one of these."""
    return {"sites": TESSERA_SITES}


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
def export_hierarchy(since: int = 0):
    """Download the current scheme: the tree, the op-log that built it, and pointers to each
    node's trained artifact (#4). Lightweight JSON — the artifacts themselves stay in the zoo.

    `since` scopes the op-log to the current session: the client anchors a session to the op_seq
    it saw at start (or last area reset) and passes it here, so the export carries only the steps
    taken this session — not the whole cross-session history that used to leak in."""
    tree = hierarchy.load()
    ops = [e for e in oplog.load() if e.get("seq", 0) > since]
    return {"hierarchy": tree, "op_log": ops, "classifier_refs": _classifier_refs(tree)}


@app.post("/api/hierarchy/import")
def import_hierarchy(body: HierarchyImportIn):
    """Restore a previously-saved scheme (#4 / #5): one upload that validates *then* applies. The
    whole envelope is checked first (tree well-formed, op-log entries are ops we can apply, each
    classifier resolves); a broken file is rejected with the exact reasons and nothing changes.
    Only if it's sound do we install the tree, restore its op-log, and rebind classifiers to the
    artifacts on disk. Splits whose artifact is missing are reported so the user can retrain them."""
    tree = body.hierarchy
    # validate the whole envelope first, so a broken file is rejected before it mutates anything (#5)
    report = validate_ops.validate_envelope({"hierarchy": tree, "op_log": body.op_log})
    if not report["ok"]:
        raise HTTPException(400, {"message": "invalid scheme", **report})
    hierarchy.save(tree)
    oplog.replace(body.op_log or [])
    _reload()
    missing = validate_ops.missing_classifiers(tree)   # warnings from the same source of truth
    oplog.append("import_hierarchy", {"nodes": len(tree), "missing": missing})
    return {"imported": True, "missing_classifiers": missing, **_tree_payload()}


@app.get("/api/oplog")
def get_oplog(since: int = 0):
    """The ordered operations that built the current scheme (#13) — the 'view by operations' data.

    Scoped like the export: pass the session anchor as `since` to get just this session's steps (the
    sequence that defines the scheme the user is looking at), not the whole cross-session history."""
    return {"ops": [e for e in oplog.load() if e.get("seq", 0) > since]}


@app.post("/api/session/reset")
def reset_session():
    """Start fresh for a new area (#5): reseed the tree back to the *current* base scheme's
    classes, dropping the splits/merges built for the previous area. A new area is a new problem,
    so the user starts from scratch — but on the same base classes they last chose (IndiaSAT or
    WorldCover), not always IndiaSAT. Reuses the base picker's reseed, which backs the old tree up
    to hierarchy.prev.json first, so nothing is truly lost."""
    scheme = infer.active_base().get("scheme", "indiasat")
    _switch_base(scheme)                     # destructive reseed of the same scheme (see _switch_base)
    cleared = examples.archive_all()         # empty the example canvas so a fresh split isn't pre-filled (#4)
    oplog.append("reset", {"scheme": scheme, "cleared": cleared})
    return {"reset": True, "scheme": scheme, "cleared_examples": cleared, **_tree_payload()}


# the inference feature source's coverage, exposed to the UI as a pick-list (#7). Alpha Earth
# has annual mosaics; Tessera only has usable India coverage in 2024, so Detailed is locked to it.
AE_YEARS = list(range(2017, 2025))
TESSERA_YEARS = [2024]


@app.get("/api/model-families")
def model_families(source: str = "alphaearth"):
    """The model families valid for a chosen inference source (#1): Earth Engine / Alpha Earth can
    only run linear models (band math), so it returns linear-only; a Tessera-local run adds the
    non-linear pixel learners (Random Forest, XGBoost if installed) and an object-detection slot we
    haven't built yet. This is what lets the UI show only the models that fit the data."""
    return {"source": source, "families": refine.model_families(source)}


@app.get("/api/inference-options")
def inference_options():
    """What inference data the user can pick (#7): the feature source + the years it covers.

    The trained models are linear on Alpha Earth's temporally-consistent embeddings, so a model
    fit on 2024 still classifies an earlier year's features — we just sample the chosen year.
    The notes tell the user how far a ground truth is trusted across years (#3) and that Tessera
    is 2024-only but other years can be requested (#6)."""
    return {"realistic": {"source": "alphaearth", "years": AE_YEARS, "default": 2024,
                          "note": "Alpha Earth has annual mosaics 2017-2024. A model trained on one "
                                  "year still classifies nearby years; run temporal_eval.py to see "
                                  "how many years a given ground truth stays reliable."},
            "detailed": {"source": "alphaearth + tessera", "years": TESSERA_YEARS, "default": 2024,
                         "note": "Tessera has usable India coverage only for 2024; other years can "
                                 "be requested from the Tessera team."}}


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
    _maybe_reload()                                  # pick up a script-made split (e.g. add_mining.py)
    bbox = (west, south, east, north)
    # some live splits can't render as AE band-math tiles, so the whole area falls back to the
    # point-grid render: a Tessera split (#16, features in downloaded tiles) or a non-linear AE
    # split (Random Forest, #7 wk10, not band math). Either forces the grid.
    tessera_live = any((b or {}).get("features") == "tessera" for b in _refinements.values())
    nonlinear_ae_live = any((b or {}).get("features") == "ae"
                            and (b or {}).get("algo") in infer.NONLINEAR_ALGOS
                            for b in _refinements.values())
    grid_live = tessera_live or nonlinear_ae_live
    needs_tessera = mode == "detailed" or tessera_live
    # #3: refuse an area that would blow up compute/download before we hand it to EE/Tessera.
    guard = aoi.check(bbox, "tessera" if needs_tessera else "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    if mode == "detailed" or grid_live:
        n = max(8, min(n, 60))
        if mode == "detailed":
            year = 2024                              # Tessera coverage; ignore any other ask
            df, cw, ch = infer.classify_bbox_softvote(bbox, n=n, year=year, model_bundle=_softvote,
                                                      refinements=_refinements)
        else:
            # a Tessera split is 2024-only; a non-linear AE split can use any Alpha Earth year
            year = 2024 if tessera_live else min(max(year, AE_YEARS[0]), AE_YEARS[-1])
            df, cw, ch = infer.classify_bbox(bbox, n=n, year=year, model_bundle=_model,
                                             refinements=_refinements)
        cells = [{"lat": float(r.lat), "lon": float(r.lon), "pred": r.pred}
                 for r in df.itertuples()]
        note = ("Tessera split shown on the point grid (it can't ride the crisp tile map)."
                if tessera_live else
                "Random Forest split shown on the point grid (it can't ride the crisp tile map)."
                if nonlinear_ae_live else None)
        return {"render": "cells", "cells": cells, "cell_w": cw, "cell_h": ch,
                "mode": mode, "year": year, "counts": df.pred.value_counts().to_dict(),
                "note": note, "colors": infer.load_colors()}

    year = min(max(year, AE_YEARS[0]), AE_YEARS[-1])  # clamp to Alpha Earth's coverage
    tile_url, counts = infer.classify_bbox_tiles(bbox, year=year, model_bundle=_model,
                                                 refinements=_refinements)
    return {"render": "tiles", "tile_url": tile_url, "bounds": [west, south, east, north],
            "mode": mode, "year": year, "counts": counts, "colors": infer.load_colors()}


@app.get("/api/classify.tif")
def classify_geotiff(west: float, south: float, east: float, north: float, year: int = 2024):
    """A downloadable GeoTIFF of the classified bbox (#24): one band of integer class codes at 10 m,
    with the code->class legend. EE builds it server-side; we return the short-lived download URL.
    Bounded to the on-screen box (getDownloadURL is size-capped)."""
    year = min(max(year, AE_YEARS[0]), AE_YEARS[-1])
    guard = aoi.check((west, south, east, north), "geotiff")   # #3: getDownloadURL is size-capped
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    try:
        url, classes = infer.classify_bbox_geotiff((west, south, east, north), year=year,
                                                   model_bundle=_model, refinements=_refinements)
    except Exception as e:
        # getDownloadURL builds the whole label image at once and is memory-capped by Earth Engine;
        # a composited IndiaSAT SAR model (tree/crop) or a large box blows that limit. Say so plainly.
        if "memory" in str(e).lower():
            raise HTTPException(400, "GeoTIFF export hit Earth Engine's memory limit: the classified "
                                     "image is too heavy to export at 10 m over this area. Draw a "
                                     "smaller box — and note that an applied IndiaSAT tree/crop (SAR) "
                                     "model makes the export especially heavy.")
        raise HTTPException(400, f"GeoTIFF export failed (try a smaller area): {e}")
    return {"url": url, "classes": classes, "year": year}


# ----------------------------- per-fortnight water (#5/#7) -----------------------------
@app.get("/api/water")
def classify_water(west: float, south: float, east: float, north: float, date: str):
    """Water vs non-water for one fortnight (#5/#7): raw Sentinel-1/2 composited around `date`
    (YYYY-MM-DD), classified by the offline-trained linear water model and served as EE tiles.
    Needs the model trained first (scripts/train_water_fortnight.py)."""
    bbox = (west, south, east, north)
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    if not (_ROOT / infer.WATER_FORTNIGHT_PATH).exists():
        raise HTTPException(400, "water model not trained yet — run scripts/train_water_fortnight.py")
    try:
        tile_url, counts = infer.classify_water_tiles(bbox, date)
    except Exception as e:
        raise HTTPException(400, f"water classify failed (try another date/area): {e}")
    return {"render": "tiles", "tile_url": tile_url, "bounds": [west, south, east, north],
            "date": date, "counts": counts, "colors": infer._WATER_COLORS}


# ----------------------------- IndiaSAT EE-RF models (#13 wk10) -----------------------------
@app.get("/api/treecrop")
def classify_treecrop(west: float, south: float, east: float, north: float,
                      start: str = None, end: str = None, composite: bool = True):
    """Tree vs crop over a bbox (#13): the pan-India IndiaSAT model — an EE Random Forest on a
    Sentinel-1 SAR 16-day time series — trained + classified server-side, served as tiles.

    `composite` (default) plugs it into the hierarchy as a refinement of greenery: outside greenery
    the base map stands, inside greenery it becomes tree/crop. `composite=false` shows the model alone
    (labels the whole box), which only makes sense over pure vegetation."""
    import ee_rf
    bbox = (west, south, east, north)
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    try:
        if composite:
            tile_url, counts, classes = ee_rf.classify_composited(bbox, "treecrop", start=start, end=end)
            colors = {**infer.load_colors(), **ee_rf.TREECROP_COLORS}
        else:
            tile_url, counts, classes = ee_rf.classify_treecrop_tiles(bbox, start=start, end=end)
            colors = ee_rf.TREECROP_COLORS
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"tree/crop classify failed (try a smaller area/other dates): {e}")
    return {"render": "tiles", "tile_url": tile_url, "bounds": [west, south, east, north],
            "counts": counts, "colors": colors}


@app.get("/api/farmshrub")
def classify_farmshrub(west: float, south: float, east: float, north: float, year: int = 2024,
                       composite: bool = True):
    """Farm / plantation / scrubland over a bbox (#13): the per-AEZ IndiaSAT model — an EE Random
    Forest on Alpha Earth embeddings, trained on the AOI's agro-ecological-region samples, served
    as tiles. `composite` (default) refines the greenery class; `composite=false` shows it alone."""
    import ee_rf
    bbox = (west, south, east, north)
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    year = min(max(year, AE_YEARS[0]), AE_YEARS[-1])
    try:
        if composite:
            tile_url, counts, classes = ee_rf.classify_composited(bbox, "farmshrub", year=year)
            colors = {**infer.load_colors(), **ee_rf.FARMSHRUB_COLORS}
        else:
            tile_url, counts, classes = ee_rf.classify_farmshrub_tiles(bbox, year=year)
            colors = ee_rf.FARMSHRUB_COLORS
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"farm/shrub classify failed (AOI may be outside a known AEZ): {e}")
    return {"render": "tiles", "tile_url": tile_url, "bounds": [west, south, east, north],
            "year": year, "counts": counts, "colors": colors}


# ----------------------------- vectorize a class into segments (#4 wk10) -----------------------------
@app.get("/api/segment")
def segment(west: float, south: float, east: float, north: float,
            cls: str = "mining", year: int = 2024, min_area_ha: float = None):
    """Vectorize a class of the classified map into cleaned polygon segments (#4). Turns scattered
    mining pixels into discrete objects (speckle dropped, small blobs filtered). Returns GeoJSON +
    a summary (segment count, total area). The class must be live on the map."""
    import config
    _maybe_reload()                                  # pick up a script-made split (e.g. add_mining.py)
    bbox = (west, south, east, north)
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    year = min(max(year, AE_YEARS[0]), AE_YEARS[-1])
    min_area = config.SEGMENT_MIN_AREA_HA if min_area_ha is None else max(0.0, min_area_ha)
    try:
        fc, summary = infer.segment_class(bbox, year=year, cls=cls, min_area_ha=min_area,
                                          model_bundle=_model, refinements=_refinements)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"segmentation failed (try a smaller area): {e}")
    return {"geojson": fc, "summary": summary, "year": year}


# ----------------------------- per-pixel water frequency over a year (#11 wk10) -----------------------------
@app.get("/api/water-frequency")
def water_frequency(west: float, south: float, east: float, north: float,
                    year: int = 2024, n: int = 24):
    """How many fortnights each pixel held water across `year` (#11) — the per-pixel water-count
    raster that makes seasonality legible for LULC. Runs the linear water model over ~n fortnights
    and sums the water masks, served as EE tiles with a blue ramp."""
    bbox = (west, south, east, north)
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    if not (_ROOT / infer.WATER_FORTNIGHT_PATH).exists():
        raise HTTPException(400, "water model not trained yet — run scripts/train_water_fortnight.py")
    n = max(6, min(n, 26))
    try:
        tile_url, stats = infer.water_frequency_tiles(bbox, year=year, n=n)
    except Exception as e:
        raise HTTPException(400, f"water-frequency failed (try a smaller area/year): {e}")
    return {"render": "tiles", "tile_url": tile_url, "bounds": [west, south, east, north],
            "stats": stats, "colors": {"ramp": ["#f7fbff", "#08306b"]}}


# NB: the >=N-fortnight spurious-water filter (#13) is NOT a UI feature — it's a code-level correction
# on the water output (infer.annual_water_mask), to be applied when the fortnight water model produces
# an annual water layer for the LULC (the deferred water->LULC step). So there's no endpoint for it.


# ----------------------------- training-time estimate (#8) -----------------------------
@app.get("/api/estimate")
def estimate_training(west: float, south: float, east: float, north: float,
                      fraction: float = 0.1, algo: str = "linearsvc"):
    """Estimated seconds to train a model over this bbox at `fraction` pixel density (#8), read
    from the benchmark profile (scripts/benchmark_training.py). Sampling = per-getInfo-call latency
    x number of batches; fit = a + b*rows. 404 until the profile has been generated."""
    import json, math
    prof_path = _ROOT / "data" / "benchmark_profile.json"
    if not prof_path.exists():
        raise HTTPException(404, "no benchmark profile — run scripts/benchmark_training.py first")
    p = json.load(open(prof_path))
    area = aoi.area_km2((west, south, east, north))
    n = int(area * 10000 * max(0.0, min(fraction, 1.0)))     # 10,000 px/km^2 at 10 m
    s = p["sampling"]
    sample_s = s["per_call_s"] * math.ceil(max(1, n) / s["batch"])
    fa, fb = p["fit"].get(algo, p["fit"]["linearsvc"])
    fit_s = max(0.0, fa + fb * n)
    return {"area_km2": round(area, 1), "n_points": n, "algo": algo,
            "sample_s": round(sample_s, 1), "fit_s": round(fit_s, 2),
            "total_s": round(sample_s + fit_s, 1)}


# ----------------------------- STACD provenance (#4) -----------------------------
@app.get("/api/stacd")
def stacd_spec(west: float, south: float, east: float, north: float, year: int = 2024,
               since: int = 0, archive: bool = False):
    """Emit the STACD provenance for a classified output (#4): a STAC Item (the stack-spec) plus
    the DAG + algorithm/dataset instances (the stacd spec), with the current hierarchy scheme
    embedded as the input set. All from metadata we already keep — cheap, no EE run.

    `archive=true` marks this output for retention (#14) — the signal a data-management service would
    use to keep it and clean up unflagged test runs. Emit-only for now."""
    bbox = (west, south, east, north)
    return {"stack": stacd.build_stack_item(bbox, year, archive=archive),
            "stacd": stacd.build_stacd(bbox, year, since=since, archive=archive)}


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
    except Exception as e:
        # a malformed geometry dict makes shapely raise its own error type; keep it a clean 400.
        raise HTTPException(400, f"couldn't read that geometry ({type(e).__name__}).")
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
    except Exception as e:
        # a corrupt / unsupported file makes pyogrio raise its own error (not KeyError/ValueError);
        # that's bad user input, not a server fault, so answer 400 with a readable reason instead of a 500.
        raise HTTPException(400, f"couldn't read {file.filename or 'the file'} as GeoJSON/KML "
                                 f"polygons — check the format ({type(e).__name__}).")
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
    years: list[int] | None = None     # pool multiple years for temporal robustness (#3); None = 2024
    algo: str = "linearsvc"            # linearsvc | logreg | ridge | "auto" bake-off (#17)
    embedding: str = "ae"              # ae (Alpha Earth) | tessera — site-scoped (#16)


@app.post("/api/split")
def split(op: SplitIn):
    """Create the children of a SPLIT (no training yet — add examples, then retrain)."""
    try:
        refine.split_op(op.parent, op.children, do_train=False)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    oplog.append("split", {"parent": op.parent, "children": op.children})
    return _tree_payload()


# ----------------------------- rule-based split (#12) -----------------------------
class RuleSplitIn(BaseModel):
    parent: str
    rule: dict                       # {clauses: [{when, class}], default}
    colors: dict | None = None       # optional {class_id: hex}


@app.get("/api/rules/registry")
def rules_registry():
    """The index variables a rule can use (#12): id -> label / description / typical range. Drives
    the 'Split by rule' picker so the user writes expressions over known, interpretable indices."""
    import rules
    return {"variables": rules.registry_summary()}


@app.post("/api/split/rule")
def split_by_rule(op: RuleSplitIn):
    """Split a leaf by an interpretable rule over indices instead of a trained model (#12). Creates
    the child classes the rule produces and stores the rule on the node; inference evaluates it in
    EE so it renders as crisp tiles. Mints a local model card (a rule is a model the user built)."""
    try:
        classes = refine.rule_split_op(op.parent, op.rule, colors=op.colors)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    _reload()
    card = None
    try:
        card = catalogue.mint_rule_card(op.parent, op.rule)     # never fail the split over its card
    except Exception:
        pass
    oplog.append("rule_split", {"parent": op.parent, "rule": op.rule, "classes": classes},
                 result={"model": card})
    return {"parent": op.parent, "classes": classes, "card": card, **_tree_payload()}


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
    # snapshot the node's current model before we overwrite it, so re-splitting a node into a
    # different set of children keeps the old model in the zoo instead of making it vanish
    prev_card = catalogue.get_card(f"mc_{op.node}_v1")
    snapshot = catalogue.snapshot_model(op.node)
    try:
        bundle = refine.retrain(op.node, balance=op.balance, years=op.years,
                                algo=op.algo, embedding=op.embedding)
    except ValueError as e:                  # e.g. a child has no examples yet / Tessera on a base source
        catalogue.discard_snapshot(snapshot)
        raise HTTPException(400, str(e))
    _reload()
    # mint/refresh the model + dataset cards for this node so the zoo tracks it
    cards = catalogue.register_retrain(op.node, bundle)
    # keep the superseded model only when the split actually changed (else it was a plain retrain)
    old_classes = sorted(p["class"] for p in (prev_card or {}).get("produces", []))
    if old_classes and old_classes != sorted(bundle.get("classes") or []):
        arch = catalogue.archive_prev_card(op.node, prev_card, snapshot)
        if arch:
            cards["archived"] = arch
    else:
        catalogue.discard_snapshot(snapshot)
    oplog.append("retrain", {"node": op.node, "balance": op.balance, "years": op.years,
                             "algo": bundle.get("algo"), "embedding": op.embedding}, result=cards)
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
                "worldcover": {"label": "WorldCover (7 classes)",
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
    target_node: str | None = None     # apply under a different node than the card's own (#11)
    force: bool = False                # override the compatibility guard after the user confirms


@app.post("/api/apply")
def apply_model(op: ApplyIn):
    """Make a zoo model live on the map. A split model registers its trained classifier on its
    hierarchy node (so inference composites it); the base model resets the map to the 4 classes.
    This is what turns the catalogue into something you can actually *use*.

    `target_node` lets the contextual panel apply a model under the class the user has selected,
    not just the card's home node. When that target doesn't match what the model was trained to
    split (e.g. a greenery crop/tree model dropped onto water), we refuse with 409 and a reason
    unless `force` — the 'do you really want to proceed?' guard (#11)."""
    card = catalogue.get_card(op.card_id)
    if not card or not op.card_id.startswith("mc_"):
        raise HTTPException(404, f"no model card {op.card_id!r}")

    if card.get("topology") == "base_pooled" or card["node"] == hierarchy.ROOT:
        scheme = card.get("base_scheme", "indiasat")     # which base this card represents (#5)
        _switch_base(scheme)                             # reseed + make its model live
        oplog.append("apply", {"card_id": op.card_id, "node": card["node"], "base_scheme": scheme})
        return {"applied": op.card_id, "node": card["node"], **_tree_payload()}

    tree = hierarchy.load()
    node = op.target_node or card["node"]                # where the user wants it, else its home node
    if node not in tree:
        raise HTTPException(400, f"node {node!r} is not in the hierarchy")
    # guard against applying a model onto an incompatible base class (#11) — but let force through
    if not op.force:
        chk = catalogue.check_apply_compatible(card, node, tree)
        if not chk["ok"]:
            raise HTTPException(409, {"message": chk["reason"], "needs_confirm": True})

    artifact = (card.get("artifact") or {}).get("path")
    if not artifact or not (_ROOT / artifact).exists():
        raise HTTPException(400, "this model's trained artifact isn't available locally")

    # rebuild the node's children to exactly the model's classes, then register its classifier
    for ch in list(tree[node].get("children", [])):
        _drop_subtree(tree, ch)
    tree[node]["children"] = []
    for cls in (p["class"] for p in card.get("produces", [])):
        hierarchy.add_class(tree, cls.replace("_", " ").title(), node, canonical=cls)
    # point at the artifact's own stem (data/refine/<card.node>.joblib), so applying a model under
    # a *different* node still loads the right joblib (its stem, not the target node's name).
    tree[node]["classifier"] = card["node"]
    hierarchy.save(tree)
    _reload()
    oplog.append("apply", {"card_id": op.card_id, "node": node})
    return {"applied": op.card_id, "node": node,
            "classes": [p["class"] for p in card.get("produces", [])], **_tree_payload()}


# ----------------------------- apply an IndiaSAT ee_rf model as a hierarchy refinement (#13) -----------------------------
class ApplyEeRfIn(BaseModel):
    card_id: str
    parent: str = "greenery"      # the base class the model refines


@app.post("/api/apply-eerf")
def apply_eerf(op: ApplyEeRfIn):
    """Plug an IndiaSAT ee_rf model into the hierarchy: the `parent` class (greenery) gains the
    model's classes as children and is marked with the model, so the tree shows the change and every
    Run classification composites it. This is what makes the hierarchy follow the model instead of
    reusing the old scheme."""
    import ee_rf
    card = catalogue.get_card(op.card_id)
    if not card or card.get("topology") != "ee_rf":
        raise HTTPException(404, f"{op.card_id!r} is not an IndiaSAT (ee_rf) model card")
    which = "treecrop" if "treecrop" in card["node"] else "farmshrub"
    tree = hierarchy.load()
    if op.parent not in tree:
        raise HTTPException(400, f"the {op.parent!r} class isn't in the current base scheme — switch "
                                 "to the IndiaSAT base first")
    classes = [p["class"] for p in card.get("produces", [])]
    colmap = ee_rf.model_colors(which)
    # the model's class names must be free (they key the flat tree) — if this model is already applied
    # on another node its classes collide, so refuse cleanly instead of blowing up mid-rewrite (#5)
    clash = [c for c in classes if c in tree and tree[c].get("parent") != op.parent]
    if clash:
        raise HTTPException(400, f"this model's classes {clash} are already in the tree (it's applied "
                                 "elsewhere) — remove that instance first, then apply it here.")
    # rebuild the parent's children as the model's classes, mark it with the model
    for ch in list(tree[op.parent].get("children", [])):
        _drop_subtree(tree, ch)
    tree[op.parent]["children"] = []
    for cls in classes:
        hierarchy.add_class(tree, cls.replace("_", " ").title(), op.parent, canonical=cls)
        if cls in tree:
            tree[cls]["color"] = colmap.get(cls)
    tree[op.parent]["ee_rf"] = which
    tree[op.parent]["classifier"] = None          # not a joblib classifier; composited in EE
    tree[op.parent].pop("rule", None)             # a node can't carry both a rule split and an ee_rf model
    hierarchy.save(tree)
    _reload()
    oplog.append("apply_eerf", {"card_id": op.card_id, "node": op.parent, "model": which,
                                "classes": classes})
    return {"applied": op.card_id, "node": op.parent, "classes": classes, **_tree_payload()}


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
    elif card_id.startswith("ds_"):               # which models consume this dataset (#15), computed
        card = {**card, "used_by": catalogue.models_using_dataset(card_id)}
    return card


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: str):
    """Remove a card from the zoo (#9) — e.g. a superseded/dummy model the user no longer wants.
    Purges the card's archived/published joblib copies too (never a live model's artifact). Refuses
    to delete a *published* card so the shared zoo isn't mutated from here."""
    card = catalogue.get_card(card_id)
    if not card:
        raise HTTPException(404, f"no card {card_id!r}")
    if (card.get("zoo") or {}).get("published"):
        raise HTTPException(400, "this card is published; unpublish it from the zoo repo first")
    catalogue.delete_card(card_id, purge_artifacts=True)
    return {"deleted": card_id}


@app.get("/api/standards")
def standards():
    """The standard LULC vocabularies (WorldCover / USDA) offered as a pick-list for class mapping."""
    return catalogue.STANDARDS


@app.get("/api/cards/{card_id}/spread")
def card_spread(card_id: str, cell: float = 0.25,
                w: float = None, s: float = None, e: float = None, n: float = None):
    """Recompute a polygon dataset's spatial-diversity at a user-chosen grid cell (#1), plus how
    much of the AOI it covers (#4).

    Lets the user dial the grid the spread is measured on (sir's ask) without re-minting the card.
    If a bbox (w,s,e,n) is passed — the area about to be classified — we also report `coverage`:
    the fraction of that AOI that falls inside a labelled polygon, so the count is judged against
    the size of the area, not in the absolute. Returns 404 for a card with no polygons."""
    cell = max(0.01, min(cell, 5.0))     # keep it sane: 0.01-5 degrees
    aoi = [w, s, e, n] if None not in (w, s, e, n) else None
    out = catalogue.recompute_spread(card_id, cell=cell, aoi=aoi)
    if out is None:
        raise HTTPException(404, "no polygons to measure spread for this card")
    return out


@app.get("/api/cards/{card_id}/geometry")
def get_card_geometry(card_id: str):
    """The card's actual polygons (for polygon datasets / a model's polygon training data) so the
    map shows the real footprint instead of a country-sized box. Feature sources -> drawable:false."""
    return catalogue.card_geometry(card_id)


@app.get("/api/cards/{card_id}/regions")
def get_card_regions(card_id: str):
    """The districts / states the card's polygons fall in (#7 wk11) — for a model, where its training
    data (its strong region) is. Names them via FAO GAUL in Earth Engine. {available:false} if the
    card has no polygon footprint (a pure feature-source model)."""
    try:
        return catalogue.named_regions(card_id)
    except Exception as e:
        raise HTTPException(400, f"couldn't resolve regions: {e}")


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
