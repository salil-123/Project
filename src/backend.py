"""FastAPI backend for the Do It Yourself LULC web interface (CoRE stack).

Serves the 10 m classifier and the hierarchy-editing loop: view the class tree, add
example polygons (drawn or uploaded), grow it with SPLIT/ADD at any level, and retrain
a node on the fly. Plain HTML/CSS/JS frontend in ./static talks to these JSON endpoints.

Operations run synchronously (FastAPI runs sync handlers in a threadpool, so a slow
GEE+train call doesn't block other requests); the UI shows a "working…" state.

Run (from the repo root):  uvicorn backend:app --reload --app-dir src
Then open http://127.0.0.1:8000/
"""
import os
import sys
import json
import time
import logging
import tempfile
import threading
import contextvars
from pathlib import Path

log = logging.getLogger("corestack.backend")   # jobs, export, DAG proxy, retrain

# repo root holds shared infra (config.py, tessera_fast.py) + the data/ dir; put it
# on the path so infer can import them whichever directory uvicorn is launched from.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
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
import config
import jobs
import airflow_client
import logging_setup
import db
import auth
import projects

_STATIC = Path(__file__).resolve().parent / "static"

# set up logging before anything else runs, so startup work (EE init, zoo seeding, model loads) is
# captured too rather than logging into the void.
logging_setup.configure(config.LOG_LEVEL)
_req_log = logging_setup.get("request")
# "paths" is one of the things the checklist puts at debug: where this process reads and writes
log.debug("paths root=%s data=%s models=%s catalogue=%s",
          config.PROJECT_ROOT, config.DATA_DIR, config.MODELS_DIR, catalogue.CATALOGUE_DIR)

app = FastAPI(title="Do It Yourself LULC")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One line per request at info; at debug also the query string and how long it took to a
    millisecond, which is what you actually want when a classify call is mysteriously slow."""
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # log the failure here too — otherwise a 500 raised deep in a handler only shows in stderr
        _req_log.exception("%s %s failed after %.0f ms", request.method, request.url.path,
                           (time.perf_counter() - t0) * 1000)
        raise
    ms = (time.perf_counter() - t0) * 1000
    if _req_log.isEnabledFor(logging.DEBUG) and request.url.query:
        _req_log.debug("%s %s?%s -> %s (%.0f ms)", request.method, request.url.path,
                       request.url.query, response.status_code, ms)
    else:
        _req_log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                      response.status_code, ms)
    return response

# the detailed-mode soft-vote is one shared model; the base model + splits depend on the workspace
_softvote = infer.load_softvote()

db.init()          # users + projects tables (Postgres via DATABASE_URL, SQLite on a laptop)
if config.GOOGLE_CLIENT_ID and not config.SERVICE_TOKEN:
    log.warning("Google sign-in is on but SERVICE_TOKEN is unset: the Airflow DAG's callbacks will be "
                "refused. Set SERVICE_TOKEN here and CORESTACK_SERVICE_TOKEN on the DAG side.")

# the zoo is a git-backed card DB; make sure it's a repo and seeded from what's on disk
zoo_git.init_local()
# a fresh clone/deploy has no cards (data/catalogue is gitignored) — pull them in from the repo's
# shipped seed so the zoo shows the full set, not just what backfill can regenerate locally.
catalogue.seed_from_bundled()
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


# The base model + splits are loaded per workspace (a project, or data/ for scripts and the DAG) and
# cached on the scheme files' mtimes. So one project's split never leaks into another's map, and a
# change made on disk by a script still gets picked up, which is what _maybe_reload used to do.
_cache = {}


def _stamp():
    ws = config.workspace_dir()
    out = []
    for f in ("hierarchy.json", "active_base.json"):
        try:
            out.append((ws / f).stat().st_mtime)
        except OSError:
            out.append(0.0)
    return tuple(out)


def _loaded():
    key, stamp = str(config.workspace_dir()), _stamp()
    hit = _cache.get(key)
    if not hit or hit[0] != stamp:
        hit = (stamp, infer.load_model(), infer.load_refinements())
        _cache[key] = hit
    return hit


def _base_model():
    return _loaded()[1]


def _refs():
    return _loaded()[2]


def _reload():
    """Drop this workspace's cached models so the next classify reads the fresh ones."""
    _cache.pop(str(config.workspace_dir()), None)


def _tree_payload():
    tree = hierarchy.load()
    # op_seq = the current head of the op-log, so the client can anchor a "session" to it and
    # export only the ops that happened since (#4).
    return {"tree": tree, "leaves": hierarchy.leaves(tree), "colors": infer.load_colors(),
            "op_seq": len(oplog.load())}


@app.get("/api/health")
def health(deep: bool = False):
    out = {"status": "ok", "classes": _base_model().get("classes"), "wc_weight": _base_model().get("wc_weight")}
    if deep:   # ?deep=1: can this box look up and reach the Google hosts sign-in and Earth Engine need?
        import socket
        import requests
        reach = {}
        for host in ("www.googleapis.com", "oauth2.googleapis.com", "earthengine.googleapis.com"):
            # the lookup on its own first: a hung DNS is the usual culprit and requests can't time it out
            try:
                auth.with_deadline(socket.getaddrinfo, 5, host, 443)
            except (OSError, TimeoutError) as e:
                reach[host] = f"unreachable: DNS lookup failed ({type(e).__name__})"
                continue
            try:
                code = auth.with_deadline(requests.head, 6, f"https://{host}", timeout=5).status_code
                reach[host] = f"ok ({code})"
            except (requests.RequestException, TimeoutError) as e:
                reach[host] = f"unreachable: lookup ok, no connection ({type(e).__name__})"
        out["reach"] = reach
        out["proxy"] = {k: bool(os.getenv(k) or os.getenv(k.lower())) for k in ("HTTPS_PROXY", "HTTP_PROXY")}
    return out


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


def _has_tessera():
    # the slim Docker image leaves geotessera out, so there Tessera isn't on offer at all
    import importlib.util
    return importlib.util.find_spec("geotessera") is not None


@app.get("/api/tessera-sites")
def tessera_sites():
    """The bboxes Tessera training is available for (#16) — the 4 sites we requested GeoTessera
    coverage for. The UI shows the Tessera embedding option only when the AOI sits in one of these,
    and not at all when this server has no geotessera installed."""
    return {"sites": TESSERA_SITES if _has_tessera() else {}, "available": _has_tessera()}


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
    bbox = (west, south, east, north)
    # some live splits can't render as AE band-math tiles, so the whole area falls back to the
    # point-grid render: a Tessera split (#16, features in downloaded tiles) or a non-linear AE
    # split (Random Forest, #7 wk10, not band math). Either forces the grid.
    tessera_live = any((b or {}).get("features") == "tessera" for b in _refs().values())
    nonlinear_ae_live = any((b or {}).get("features") == "ae"
                            and (b or {}).get("algo") in infer.NONLINEAR_ALGOS
                            for b in _refs().values())
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
                                                      refinements=_refs())
        else:
            # a Tessera split is 2024-only; a non-linear AE split can use any Alpha Earth year
            year = 2024 if tessera_live else min(max(year, AE_YEARS[0]), AE_YEARS[-1])
            df, cw, ch = infer.classify_bbox(bbox, n=n, year=year, model_bundle=_base_model(),
                                             refinements=_refs())
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
    tile_url, counts = infer.classify_bbox_tiles(bbox, year=year, model_bundle=_base_model(),
                                                 refinements=_refs())
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
                                                   model_bundle=_base_model(), refinements=_refs())
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


# ----------------------------- export to a GEE asset (STACD onboarding) -----------------------------
def _truthy(v) -> bool:
    """Airflow/STACD stringify conf values, so `export` can arrive as "false" or "0". Treat those as
    false rather than as a non-empty (and therefore truthy) string."""
    if isinstance(v, str):
        return v.strip().strip('"').strip("'").lower() not in ("false", "0", "no", "")
    return bool(v)


def _watch_export(task_id, asset_id):
    """Follow an export we've already answered for, and log how it ends: a late failure shows in the log."""
    import threading

    def watch():
        ee = config.ee_init()
        while True:
            try:
                st = ee.data.getTaskStatus(task_id)[0]
            except Exception as e:
                log.warning("export %s: can't read its status (%s)", task_id, e)
                return
            if st.get("state") == "COMPLETED":
                log.info("export %s finished late: %s is in place", task_id, asset_id)
                return
            if st.get("state") in ("FAILED", "CANCELLED"):
                log.error("export %s %s after we answered: %s", task_id, st["state"], st.get("error_message", ""))
                return
            time.sleep(60)

    if task_id:
        threading.Thread(target=watch, daemon=True, name=f"export-{task_id}").start()


def _run_export(project_id=None, **kw):
    """The DAG's export, run against a project's scheme when its conf names one (week 18), else the
    shared data/ workspace exactly as before. The DAG calls back without a browser cookie, so the
    workspace is set here rather than by the request middleware."""
    if not project_id:
        return _run_export_ws(**kw)
    pid = str(project_id).strip().strip('"')
    if not projects.folder(pid).is_dir():
        raise HTTPException(404, f"no project {pid!r}")
    tok = config.use_workspace(projects.folder(pid))
    try:
        return _run_export_ws(**kw)
    finally:
        config.reset_workspace(tok)


def _run_export_ws(west=None, south=None, east=None, north=None, roi_asset=None, region=None,
                year=2024, start_year=None, end_year=None, asset_id=None, name=None,
                base_scheme=None, asset_base=None, wait=True, overwrite=True, include_stac=True,
                retrain=None, export=True, **_ignored):
    """Shared logic for the GET + POST export endpoints. Classifies the AOI, exports the raster to a GEE
    asset, and returns the shape the STACD DAG generator reads: status + asset_id (list) + stac_items
    (array). We deliberately DON'T return a `stacd` block — the pipeline builds provenance itself from the
    registered YAML configs and only reads `stac_items` from us. `**_ignored` swallows extra DAG params
    (state/district/block/gee_account_id/hierarchy/job_id/…) so a forwarded DAG conf never errors.

    `retrain` lets a training run ride in on THIS path instead of needing a DAG of its own: pass the
    /api/retrain params as a dict and the node is retrained first, so the export classifies with the
    fresh model. `export=False` makes it a retrain-only job — still the same op, the same DAG, one
    less thing to register with STACD."""

    # train first when asked, so whatever we export below uses the model the user just built. The
    # DAG only drives us over HTTP, so the training happens in this process and the model, hierarchy
    # and zoo cards all stay consistent with each other.
    log.info("export: classify + export to a GEE asset")
    log.debug("export params year=%s bbox=%s roi_asset=%s asset_id=%s base_scheme=%s",
              year, (west, south, east, north), roi_asset, asset_id, base_scheme)
    retrain_result = None
    if retrain:
        if isinstance(retrain, str):          # the pipeline stringifies params; accept JSON text too
            try:
                retrain = json.loads(retrain)
            except ValueError:
                raise HTTPException(400, "retrain must be an object of /api/retrain params")
        if not isinstance(retrain, dict) or not retrain.get("node"):
            raise HTTPException(400, "retrain needs at least {'node': '<class>'}")
        retrain_result = _do_retrain(**retrain)

    if not _truthy(export):
        # retrain-only job: nothing to classify, so report the training and stop here
        return {"status": "success", "retrain": retrain_result, "export": None}
    # the pipeline stringifies params, so coerce: year may arrive as "2024", base_scheme as '"indiasat"'
    try:
        yr = int(str(end_year or start_year or year).strip().strip('"').strip("'"))
    except Exception:
        yr = 2024
    yr = min(max(yr, AE_YEARS[0]), AE_YEARS[-1])
    if isinstance(base_scheme, str):
        base_scheme = base_scheme.strip().strip('"').strip("'") or None

    # `region` (a DAG param) is an alias for the bbox. The pipeline may send it as a real array OR as a
    # string like "[77.16,28.53,77.20,28.57]", so accept both.
    if region is not None and None in (west, south, east, north) and not roi_asset:
        if isinstance(region, str):
            import json as _json
            try:
                region = _json.loads(region)                     # "[77.16, ...]" -> list
            except Exception:
                region = region.strip().strip("[]").split(",")   # bare "77.16,28.53,..." fallback
        try:
            west, south, east, north = [float(str(x).strip()) for x in region]
        except Exception:
            raise HTTPException(400, "region must be [west, south, east, north]")

    region_geom = None
    if roi_asset:
        ee = config.ee_init()
        region_geom = ee.FeatureCollection(roi_asset).geometry()
        try:                                          # bounds -> a plain bbox for the AE image build
            ring = region_geom.bounds().coordinates().get(0).getInfo()
        except Exception as e:
            raise HTTPException(400, f"couldn't read geometry from roi_asset {roi_asset!r}: {e}")
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        default_name = roi_asset.rstrip("/").split("/")[-1]
    elif None not in (west, south, east, north):
        bbox = (west, south, east, north)
        default_name = f"{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}"
    else:
        raise HTTPException(400, "provide region [w,s,e,n], roi_asset, or west/south/east/north")

    # a GEE batch export handles large areas fine (unlike the size-capped getDownloadURL), so the
    # generous tile cap is the right guard here.
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])

    if not asset_id:
        import re as _re
        base = _re.sub(r"[^A-Za-z0-9_]", "_", (name or default_name))[:80] or "aoi"
        asset_id = f"{config.EE_ASSET_ROOT.rstrip('/')}/{base}_{yr}"

    try:
        out = infer.classify_to_asset(bbox, asset_id, year=yr, region_geom=region_geom,
                                      model_bundle=_base_model(), refinements=_refs(),
                                      wait=wait, overwrite=overwrite, timeout_s=config.EXPORT_WAIT_S)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"export failed: {e}")

    # response shaped for the STACD DAG generator: `status` + `asset_id` (a STRING — their register task
    # wraps it into a list itself, and a list from us ends up double-nested and breaks the DB bind) +
    # `stac_items` (array). No `stacd` block — the pipeline builds that from the registered YAMLs.
    state = out.get("state")
    stac_items = []
    if include_stac:
        try:
            stac_items = [stacd.build_stack_item(bbox, yr, base_scheme=base_scheme,
                                                 base_url=(asset_base or config.STAC_ASSET_BASE),
                                                 asset_id=out["asset_id"])]
        except Exception as ex:
            stac_items = []                        # never fail the export over the stac add-on
            _stac_err = str(ex)
    # a sync call whose asset is still being written: the export is accepted and its id is final, so it's
    # a success for the caller; the asset appears there when Earth Engine is done (watched below)
    pending = bool(wait) and state in ("READY", "RUNNING")
    if pending:
        _watch_export(out.get("task_id"), out["asset_id"])
    resp = {"status": "success" if state == "COMPLETED" or pending else (state or "unknown").lower(),
            "asset_id": out["asset_id"],           # single string; the pipeline lists it itself
            "version": out.get("version", "1"),
            "hosting_platform": out.get("hosting_platform", "GEE"),
            "stac_items": stac_items,
            # extras the generator ignores; our async poll / debugging use them
            "state": state, "task_id": out.get("task_id"), "classes": out.get("classes")}
    if pending:
        resp["note"] = (f"Earth Engine is still writing the asset after {config.EXPORT_WAIT_S // 60} min; "
                        "it appears at asset_id when done. /api/export-status?task_id=... follows it.")
    if retrain_result is not None:
        resp["retrain"] = retrain_result       # so one job can report "trained, then exported"
    log.info("export complete: asset=%s state=%s", out["asset_id"], state)
    return resp


# the body keys /api/export-asset understands; anything else in the DAG conf (job_id, execution_type,
# spots, …) is simply ignored, so the endpoint accepts whatever the pipeline forwards.
_EXPORT_KEYS = {"west", "south", "east", "north", "roi_asset", "region", "year", "start_year",
                "end_year", "asset_id", "name", "base_scheme", "asset_base", "wait", "overwrite",
                "include_stac", "state", "district", "block", "gee_account_id", "hierarchy",
                "retrain", "export", "project_id"}


@app.get("/api/export-asset")
def export_asset(west: float = None, south: float = None, east: float = None, north: float = None,
                 roi_asset: str = None, year: int = 2024, start_year: int = None, end_year: int = None,
                 asset_id: str = None, name: str = None, base_scheme: str = None, asset_base: str = None,
                 wait: bool = True, overwrite: bool = True, include_stac: bool = True):
    """Export a classified LULC raster to a Google Earth Engine asset. Returns the shape the STACD DAG
    generator reads: {status, asset_id: [...], version, hosting_platform, stac_items: [STAC Feature]}.
    No `stacd` block — the pipeline builds provenance from the registered YAMLs.

    AOI: `region=[w,s,e,n]`, or `roi_asset` (a FeatureCollection asset id, e.g. the MWS boundaries), or a
    plain `west/south/east/north` bbox. `year` (or `start_year`/`end_year`) picks the Alpha Earth slice;
    no `asset_id` -> auto under EE_ASSET_ROOT. `asset_base` (or config.STAC_ASSET_BASE) makes the STAC
    hrefs absolute. Synchronous by default (wait=false returns the task immediately). Params can also be
    POSTed as a JSON body to this same path (what the DAG forwards)."""
    return _run_export(west=west, south=south, east=east, north=north, roi_asset=roi_asset,
                       year=year, start_year=start_year, end_year=end_year, asset_id=asset_id,
                       name=name, base_scheme=base_scheme, asset_base=asset_base, wait=wait,
                       overwrite=overwrite, include_stac=include_stac)


@app.post("/api/export-asset")
async def export_asset_post(request: Request):
    """Same as GET /api/export-asset, but parameters come in a JSON body — the shape a STACD/Airflow
    algorithm call posts (the DAG forwards its run `conf` here). Tolerant of the exact envelope: params
    may sit at the top level or under a `conf` key, and any extra keys the pipeline sends (job_id,
    execution_type, …) are ignored. Returns the asset descriptor + STACD spec."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    if isinstance(body.get("conf"), dict):
        body = body["conf"]                       # Airflow DAG-conf envelope
    kwargs = {k: v for k, v in body.items() if k in _EXPORT_KEYS}
    # off the event loop: an export blocks for minutes, and inline it would freeze the site for everyone
    return await run_in_threadpool(_run_export, **kwargs)


@app.get("/api/export-status")
def export_status(task_id: str = None, asset_id: str = None):
    """Poll an export that was started async (`/api/export-asset?wait=false`) — the isSuccess() check
    an Airflow sensor polls instead of blocking one long HTTP call. Pass `task_id` (returned by
    export-asset) for the EE task state, or `asset_id` to just check whether the asset exists yet.
    Returns {state, done, success, asset_id, error}."""
    if not task_id and not asset_id:
        raise HTTPException(400, "provide task_id or asset_id")
    ee = config.ee_init()

    if task_id:
        try:
            st = ee.data.getTaskStatus(task_id)
            st = st[0] if isinstance(st, list) else st
        except Exception as e:
            raise HTTPException(404, f"no task {task_id}: {e}")
        state = st.get("state", "UNKNOWN")
        done = state in ("COMPLETED", "FAILED", "CANCELLED", "CANCEL_REQUESTED")
        dest = st.get("destination_uris") or []
        return {"task_id": task_id, "state": state, "done": done,
                "success": state == "COMPLETED", "error": st.get("error_message"),
                "asset_id": asset_id, "destination": dest}

    # asset_id only: does the produced asset exist yet?
    try:
        info = ee.data.getAsset(asset_id)
        return {"asset_id": asset_id, "state": "COMPLETED", "done": True,
                "success": True, "type": info.get("type")}
    except Exception:
        return {"asset_id": asset_id, "state": "PENDING", "done": False, "success": False}


# ----------------------------- Airflow-orchestrated jobs -----------------------------
# The long ops can run through an Airflow DAG instead of inline: the frontend triggers a job, the DAG
# calls back into these endpoints to do the work, the frontend polls till it's done. Everything stays
# synchronous — each link blocks on the next. With no Airflow configured the job runs inline, so the
# same trigger+poll flow works locally too. See deploy/airflow_job_flow_plan.md.
class JobIn(BaseModel):
    op: str                 # "classify" | "export"
    params: dict = {}


def _run_op(op: str, params: dict) -> dict:
    """Do the actual work for a job op. Reuses the same handlers the direct endpoints use, so the DAG
    path and the inline path produce identical results."""
    if op == "classify":
        return classify(**params)
    if op == "export":
        return _run_export(**{k: v for k, v in params.items() if k in _EXPORT_KEYS})
    raise HTTPException(400, f"unknown job op {op!r} (expected 'classify' or 'export')")


@app.post("/api/jobs")
def create_job(body: JobIn):
    """Kick off a job. If Airflow is configured we trigger the DAG (which calls back to do the work and
    posts the result to /api/jobs/{run_id}/result); otherwise we run it inline right here. Either way
    the frontend gets a run_id and polls GET /api/jobs/{run_id}. `done` is set when it finished inline."""
    run_id = jobs.new_run_id()
    jobs.create(run_id, body.op, body.params)
    log.info("job %s created op=%s", run_id, body.op)
    log.debug("job %s params=%s", run_id, body.params)

    if not airflow_client.configured():
        # no Airflow: do the work now so the poll flow still resolves
        try:
            result = _run_op(body.op, body.params)
        except HTTPException as e:
            jobs.set_failed(run_id, str(e.detail))
            log.error("job %s failed: %s", run_id, e.detail)
            return {"run_id": run_id, "done": True, "success": False, "error": e.detail}
        except Exception as e:
            jobs.set_failed(run_id, str(e))
            log.exception("job %s failed", run_id)
            return {"run_id": run_id, "done": True, "success": False, "error": str(e)}
        jobs.set_result(run_id, result)
        log.info("job %s complete (inline)", run_id)
        return {"run_id": run_id, "done": True, "success": True, "result": result}

    conf = {"op": body.op, "params": body.params, "run_id": run_id,
            "api_base": config.CORESTACK_API_BASE}
    try:
        airflow_client.trigger(run_id, conf)
    except Exception as e:
        jobs.set_failed(run_id, f"couldn't trigger Airflow DAG: {e}")
        raise HTTPException(502, f"couldn't trigger Airflow DAG: {e}")
    log.info("job %s dispatched to Airflow DAG %s", run_id, config.AIRFLOW_DAG_ID)
    return {"run_id": run_id, "done": False, "state": "running"}


@app.get("/api/jobs/{run_id}")
def get_job(run_id: str):
    """Poll a job. Returns the stored result once the DAG (or the inline run) has posted it. Also asks
    Airflow for the run state so a DAG failure surfaces here instead of the frontend polling forever."""
    job = jobs.get(run_id)
    if job is None:
        raise HTTPException(404, f"no job {run_id!r}")

    if job["state"] == "success":
        return {"run_id": run_id, "done": True, "success": True, "result": job["result"]}
    if job["state"] == "failed":
        return {"run_id": run_id, "done": True, "success": False, "error": job["error"]}

    if job.get("op") == "retrain" and time.time() - job.get("updated", 0) > _DEAD_S:
        msg = "the training stopped (the server restarted while it ran); train again"
        jobs.set_failed(run_id, msg)
        return {"run_id": run_id, "done": True, "success": False, "error": msg}

    # still running — if Airflow says the run failed but no result came back, mark it failed
    # (a retrain runs right here in the app, Airflow never hears of it)
    if airflow_client.configured() and job.get("op") != "retrain":
        st = airflow_client.run_state(run_id)
        if st == "failed":
            jobs.set_failed(run_id, "the Airflow DAG run failed (see Airflow logs)")
            return {"run_id": run_id, "done": True, "success": False,
                    "error": "the Airflow DAG run failed (see Airflow logs)"}
    return {"run_id": run_id, "done": False, "state": "running"}


@app.post("/api/jobs/{run_id}/result")
async def store_job_result(run_id: str, request: Request):
    """The DAG's callback: once the work endpoint returned success, the DAG posts the result here and
    the job flips to done. Body is either the raw result dict, or {ok, result|error} to report a failure."""
    if jobs.get(run_id) is None:
        raise HTTPException(404, f"no job {run_id!r}")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "body must be JSON")
    if isinstance(body, dict) and body.get("ok") is False:
        jobs.set_failed(run_id, str(body.get("error", "job failed")))
        log.error("job %s failed (reported by the DAG): %s", run_id, body.get("error"))
        return {"stored": True, "state": "failed"}
    result = body.get("result", body) if isinstance(body, dict) else body
    jobs.set_result(run_id, result)
    log.info("job %s complete (result posted by the DAG)", run_id)
    return {"stored": True, "state": "success"}


# ----------------------------- DAG proxy (same-origin, no browser CORS) -----------------------------
# The frontend can't hit Airflow directly — a browser blocks the cross-origin call (CORS) and the creds
# would be exposed anyway. So the frontend calls US (same origin as the page), and we trigger + poll
# Airflow server-side. Logged so the uvicorn console shows every trigger/state call.
@app.post("/api/dag/run")
async def dag_run(request: Request):
    """Trigger the Airflow DAG with a run conf; return the dag_run_id the frontend polls on."""
    if not airflow_client.configured():
        raise HTTPException(503, "Airflow isn't configured (set AIRFLOW_API_BASE)")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "body must be JSON")
    conf = body.get("conf", body) if isinstance(body, dict) else {}
    log.info("dag_run trigger conf=%s", conf)
    try:
        resp = await run_in_threadpool(airflow_client.trigger_conf, conf)   # a blocking HTTP call
    except Exception as e:
        log.exception("dag_run trigger failed")
        raise HTTPException(502, f"couldn't trigger the DAG: {e}")
    return {"dag_run_id": resp.get("dag_run_id"), "state": resp.get("state")}


@app.get("/api/dag/status")
def dag_status(run_id: str):
    """Poll one DAG run's state from Airflow (proxied so the browser stays same-origin)."""
    if not airflow_client.configured():
        raise HTTPException(503, "Airflow isn't configured (set AIRFLOW_API_BASE)")
    st = airflow_client.run_state(run_id)
    if st is None:
        raise HTTPException(502, f"couldn't read run {run_id!r} state from Airflow")
    return {"dag_run_id": run_id, "state": st,
            "done": st in ("success", "failed"), "success": st == "success"}


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
    bbox = (west, south, east, north)
    guard = aoi.check(bbox, "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])
    year = min(max(year, AE_YEARS[0]), AE_YEARS[-1])
    min_area = config.SEGMENT_MIN_AREA_HA if min_area_ha is None else max(0.0, min_area_ha)
    try:
        fc, summary = infer.segment_class(bbox, year=year, cls=cls, min_area_ha=min_area,
                                          model_bundle=_base_model(), refinements=_refs())
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


# NB: an earlier >=N-fortnight persistence filter (the "spurious-water" correction, wk11 #13) was
# removed — a single global threshold that de-spuriates the annual layer also crushes small/seasonal
# recall (spurious 15->2% but F1 0.65->0.58, small-water recall 0.30->0.11), so it traded away exactly
# the water we care about. The proper replacement is the two-classifier design (lenient level-1 that
# lets seasonal water through, then a within-body classifier), not one blunt threshold.


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
    if role != "positive" or config.in_project():
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
    if not config.in_project():     # zoo cards are keyed by class; a project shares to the zoo explicitly
        try:
            card = catalogue.mint_rule_card(op.parent, op.rule)     # never fail the split over its card
        except Exception:
            pass
    oplog.append("rule_split", {"parent": op.parent, "rule": op.rule, "classes": classes},
                 result={"model": card})
    return {"parent": op.parent, "classes": classes, "card": card, **_tree_payload()}


def _shared_base_guard(node):
    """The base map (root) is one model everybody shares; retraining it from inside a project would
    change every other project's map. So inside a project the root is off limits."""
    if config.in_project() and node == hierarchy.ROOT:
        raise HTTPException(400, "the base map is shared by every project; add or split under one of "
                                 "the base classes instead")


@app.post("/api/add")
def add(op: AddIn):
    """Add a class under a node (no training yet — add examples, then retrain)."""
    _shared_base_guard(op.parent)
    try:
        refine.add_class_op(op.parent, op.name, new_color=op.color, do_train=False)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    oplog.append("add", {"parent": op.parent, "name": op.name, "color": op.color})
    return _tree_payload()


def _do_retrain(node: str, balance: str = "balanced", years=None,
                algo: str = "linearsvc", embedding: str = "ae", **_ignored) -> dict:
    """Train (or retrain) the classifier that resolves `node`'s children and make it live.

    The one implementation behind both entrypoints: the direct POST /api/retrain, and a retrain
    ridden in on the export path (so an Airflow job can do it without its own DAG). Slow: samples
    embeddings + fits. `**_ignored` lets a forwarded DAG conf carry extra keys harmlessly."""
    log.info("retrain node=%s algo=%s embedding=%s balance=%s years=%s",
             node, algo, embedding, balance, years)
    _shared_base_guard(node)
    if config.in_project():
        # a project owns its models: they land in its weights/ and stay out of the shared zoo until
        # the user shares one on purpose (card ids are per class, so auto-minting would clash)
        try:
            bundle = refine.retrain(node, balance=balance, years=years, algo=algo, embedding=embedding)
        except ValueError as e:
            raise HTTPException(400, str(e))
        _reload()
        oplog.append("retrain", {"node": node, "balance": balance, "years": years,
                                 "algo": bundle.get("algo"), "embedding": embedding})
        return {"node": node, "classes": bundle.get("classes"), "report": bundle.get("report"),
                "n_test": bundle.get("n_test"), "cards": None, **_tree_payload()}
    # snapshot the node's current model before we overwrite it, so re-splitting a node into a
    # different set of children keeps the old model in the zoo instead of making it vanish
    prev_card = catalogue.get_card(f"mc_{node}_v1")
    snapshot = catalogue.snapshot_model(node)
    try:
        bundle = refine.retrain(node, balance=balance, years=years, algo=algo, embedding=embedding)
    except ValueError as e:                  # e.g. a child has no examples yet / Tessera on a base source
        catalogue.discard_snapshot(snapshot)
        raise HTTPException(400, str(e))
    _reload()
    # mint/refresh the model + dataset cards for this node so the zoo tracks it
    cards = catalogue.register_retrain(node, bundle)
    # keep the superseded model only when the split actually changed (else it was a plain retrain)
    old_classes = sorted(p["class"] for p in (prev_card or {}).get("produces", []))
    if old_classes and old_classes != sorted(bundle.get("classes") or []):
        arch = catalogue.archive_prev_card(node, prev_card, snapshot)
        if arch:
            cards["archived"] = arch
    else:
        catalogue.discard_snapshot(snapshot)
    oplog.append("retrain", {"node": node, "balance": balance, "years": years,
                             "algo": bundle.get("algo"), "embedding": embedding}, result=cards)
    log.info("retrain done node=%s classes=%s n_test=%s",
             node, bundle.get("classes"), bundle.get("n_test"))
    return {"node": node, "classes": bundle.get("classes"),
            "report": bundle.get("report"), "n_test": bundle.get("n_test"),
            "cards": cards, **_tree_payload()}


def _check_train_options(op: RetrainIn, project=None):
    """Refuse a training that can't work in a blink, instead of letting it sample for minutes and
    die somewhere unhelpful. Mirrors what the data actually has: Alpha Earth is 2017 to 2024, Tessera
    is 2024 only and only at the prepared sites."""
    if op.embedding not in ("ae", "tessera"):
        raise HTTPException(400, f"unknown feature embedding {op.embedding!r}")
    if op.balance not in ("balanced", "undersample", "oversample"):
        raise HTTPException(400, f"unknown class balance {op.balance!r}")
    if op.algo != "auto" and op.algo not in refine._ALL_ALGOS:
        raise HTTPException(400, f"unknown algorithm {op.algo!r}")
    if op.algo in refine._NONLINEAR_ALGOS and op.algo != "randomforest" and op.embedding != "tessera":
        raise HTTPException(400, f"{op.algo} runs on Tessera features only; pick a linear model or "
                                 "Random Forest for Alpha Earth")
    years = op.years or []
    bad = [y for y in years if y not in AE_YEARS]
    if bad:
        raise HTTPException(400, f"no embeddings for {', '.join(map(str, bad))}: Alpha Earth covers "
                                 f"{AE_YEARS[0]} to {AE_YEARS[-1]}")
    if op.embedding == "tessera":
        if not _has_tessera():
            raise HTTPException(400, "Tessera isn't installed on this server; use Alpha Earth")
        if any(y != 2024 for y in years):
            raise HTTPException(400, "Tessera only exists for 2024; leave the years empty or put 2024, "
                                     "or switch to Alpha Earth to train across years")
        bbox = (project or {}).get("bbox")
        if bbox and not any(_overlaps(s, bbox) for s in TESSERA_SITES.values()):
            raise HTTPException(400, "Tessera isn't prepared for this area; use Alpha Earth")


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# a training can take minutes (sampling every polygon per year, then fitting), far past the 60 s a
# proxy gives one request. So the POST only starts it and the page polls /api/jobs/<id>.
# One training per workspace at a time; two at once would trample the same hierarchy. Checked on
# the job files, since gunicorn may run several worker processes. The lock only closes the gap
# between the check and the job file landing.
_training_lock = threading.Lock()


_BEAT_S, _DEAD_S = 15, 120      # training heartbeat, and how long without one means it died


def _retrain_job(run_id, op: RetrainIn):
    # beat while we work, so a poll can tell a slow training from one whose worker was killed
    # (gunicorn restarts workers on a timeout or after N requests, taking the thread with it)
    done = threading.Event()

    def beat():
        while not done.wait(_BEAT_S):
            jobs.touch(run_id)
    beater = threading.Thread(target=beat, daemon=True)
    beater.start()
    try:
        result, error = _do_retrain(op.node, balance=op.balance, years=op.years,
                                    algo=op.algo, embedding=op.embedding), None
    except HTTPException as e:
        result, error = None, str(e.detail)
    except Exception as e:
        log.exception("retrain job %s failed", run_id)
        result, error = None, f"training failed: {e}"
    # stop beating before the outcome lands, or a late beat could write "running" back over it
    done.set()
    beater.join()
    if error:
        jobs.set_failed(run_id, error)
    else:
        jobs.set_result(run_id, json.loads(json.dumps(result, default=str)))


@app.post("/api/retrain")
def retrain(op: RetrainIn, request: Request, wait: bool = False):
    """Train (or retrain) the classifier that resolves `node`'s children, then make the new model
    live. Checks the options straight away, then trains in the background and returns a job id to
    poll. `?wait=1` trains inline and returns the result, for scripts that don't sit behind a proxy."""
    _check_train_options(op, getattr(request.state, "project", None))
    _shared_base_guard(op.node)
    if wait:
        return _do_retrain(op.node, balance=op.balance, years=op.years,
                           algo=op.algo, embedding=op.embedding)
    ws = str(config.workspace_dir())
    with _training_lock:
        if jobs.live("retrain", ws, _DEAD_S):
            raise HTTPException(409, "a training is already running in this project; wait for it")
        run_id = jobs.new_run_id()
        jobs.create(run_id, "retrain", {**op.dict(), "ws": ws})
    # copy the context so the thread keeps this request's project workspace
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(_retrain_job, run_id, op), daemon=True,
                     name=f"retrain-{op.node}").start()
    return {"run_id": run_id, "done": False}


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
        if Path(hierarchy._file()).exists():
            shutil.copy(hierarchy._file(), config.ws_path("hierarchy.prev.json"))
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
    if not config.in_project():
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
    if not config.in_project():
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
    # week 18: what each model class means in the user's scheme, {model_class: your_class}. Two
    # model classes may share one name ("x and y are both acacia"). Missing -> the model's names.
    mapping: dict | None = None


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
    art_path = Path(config.model_path(artifact)) if artifact else None
    if not art_path or not art_path.exists():
        raise HTTPException(400, "this model's trained artifact isn't available locally")

    import joblib
    model_classes = [p["class"] for p in card.get("produces", [])]
    mapping = {k: hierarchy.canonicalize(v) for k, v in (op.mapping or {}).items()
               if k in model_classes and str(v).strip()}
    yours = list(dict.fromkeys(mapping.get(c, c) for c in model_classes))   # unique, in model order
    if len(yours) < 2:
        raise HTTPException(400, "after your mapping there's only one class left; a split needs two")
    clash = [c for c in yours if c in tree and not _under(tree, c, node)]
    if clash:
        raise HTTPException(400, f"{clash} already name a class elsewhere in your scheme; map them "
                                 "to a different name.")

    # rebuild the node's children as the user's classes, then register the classifier
    for ch in list(tree[node].get("children", [])):
        _drop_subtree(tree, ch)
    tree[node]["children"] = []
    tree[node].pop("rule", None)
    tree[node].pop("ee_rf", None)
    for cls in yours:
        hierarchy.add_class(tree, cls.replace("_", " ").title(), node, canonical=cls)
    if config.in_project():
        # the project keeps its own copy, renamed to the user's classes, so the zoo can move on
        # without changing this project's map
        bundle = infer.relabel_bundle(joblib.load(art_path), mapping)
        joblib.dump(bundle, config.weights_write_path(node))
        tree[node]["classifier"] = node
    else:
        # point at the artifact's own stem (data/refine/<card.node>.joblib), so applying a model under
        # a *different* node still loads the right joblib (its stem, not the target node's name).
        tree[node]["classifier"] = card["node"]
    # remember where the split came from, so the panel says "ready, run it" instead of asking for examples
    tree[node]["from_model"] = {"card_id": op.card_id, "name": card.get("name") or op.card_id}
    hierarchy.save(tree)
    _reload()
    oplog.append("apply", {"card_id": op.card_id, "node": node, "mapping": mapping or None})
    return {"applied": op.card_id, "node": node, "classes": yours, "mapping": mapping,
            **_tree_payload()}


def _under(tree, cls, node):
    """Is `cls` somewhere below `node`? (a class being replaced by the apply, so its name is free)"""
    cur = tree.get(cls, {}).get("parent")
    while cur:
        if cur == node:
            return True
        cur = tree.get(cur, {}).get("parent")
    return False


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
    tree[op.parent].pop("from_model", None)       # the panel already names the IndiaSAT model
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
    try:
        return zoo_git.publish(op.card_ids, message=op.message, contributor=op.contributor,
                               dataset_links=op.dataset_links)
    except ValueError as e:                  # the size guard: the user's call to fix, not a crash
        raise HTTPException(400, str(e))
    except Exception as e:
        # never leak a raw 500 ("Internal Server Error" text the frontend can't parse) — a failed
        # git commit/push comes back as clean JSON so the UI can show the reason.
        raise HTTPException(500, f"publish failed: {e}")


@app.get("/api/zoo/status")
def zoo_status():
    """What's local vs published — drives the 'N local / N published' badge."""
    return zoo_git.status()


# ============================== week 18: users, projects, runs ==============================
# Design + reasoning: week18/app_design.md. Pattern follows Susmit's drone_docker (projects owned by
# a user, runs versioned into their own folders); sign-in is verified here rather than trusted.

def _state(request: Request) -> dict:
    return request.scope.setdefault("state", {})


def _need_user(request: Request) -> str:
    user = _state(request).get("user")
    if not user:
        raise HTTPException(401, "sign in first")
    return user


# ----------------------------- sign-in -----------------------------
class GoogleIn(BaseModel):
    credential: str             # the ID token Google's button hands the page


class DevIn(BaseModel):
    name: str


def _sign_in(ident: dict, request: Request, response: Response) -> dict:
    with db.Session() as s:
        u = s.get(db.User, ident["email"]) or db.User(email=ident["email"])
        u.name, u.picture, u.last_login = ident["name"], ident.get("picture"), db._now()
        s.add(u)
        s.commit()
    response.set_cookie(auth.COOKIE, auth.make_cookie(ident["email"]),
                        max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        # behind the tower's TLS proxy the app itself sees http; trust the proxy's word
                        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
                        path="/")
    log.info("sign-in %s", ident["email"])
    return {"email": ident["email"], "name": ident["name"], "picture": ident.get("picture")}


@app.get("/api/auth/me")
def auth_me(request: Request):
    """Who's signed in (null if nobody) + which sign-in the page should offer."""
    email = auth.read_cookie(request.cookies.get(auth.COOKIE))
    user = None
    if email:
        with db.Session() as s:
            u = s.get(db.User, email)
            if u:
                user = {"email": u.email, "name": u.name, "picture": u.picture}
    return {"user": user, "google_client_id": config.GOOGLE_CLIENT_ID or None,
            "dev_login": auth.dev_login_allowed()}


@app.post("/api/auth/google")
def auth_google(body: GoogleIn, request: Request, response: Response):
    try:
        ident = auth.verify_google(body.credential)
    except auth.GoogleUnreachable as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(401, f"Google sign-in failed: {e}")
    return _sign_in(ident, request, response)


@app.post("/api/auth/dev")
def auth_dev(body: DevIn, request: Request, response: Response):
    """Laptop-only login. Refused once GOOGLE_CLIENT_ID is set (see auth.dev_login_allowed)."""
    try:
        ident = auth.dev_identity(body.name)
    except ValueError as e:
        raise HTTPException(403, str(e))
    return _sign_in(ident, request, response)


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"signed_out": True}


# ----------------------------- projects -----------------------------
class ProjectIn(BaseModel):
    name: str
    bbox: list[float]
    year: int = 2024
    base_scheme: str = "indiasat"


class ProjectPatch(BaseModel):
    name: str | None = None
    is_public: bool | None = None
    year: int | None = None
    bbox: list[float] | None = None


def _check_bbox(bbox):
    if len(bbox) != 4:
        raise HTTPException(400, "the area must be [west, south, east, north]")
    guard = aoi.check(tuple(bbox), "tiles")
    if not guard["ok"]:
        raise HTTPException(400, guard["reason"])


def _project_out(p: db.Project, user: str | None) -> dict:
    out = db.project_dict(p)
    out["mine"] = user == p.owner
    return out


@app.get("/api/projects")
def my_projects(request: Request):
    """The signed-in user's projects, newest first. Only theirs, never anyone else's (point 9)."""
    user = _need_user(request)
    with db.Session() as s:
        rows = (s.query(db.Project).filter_by(owner=user)
                .order_by(db.Project.updated_at.desc()).all())
        return {"projects": [_project_out(p, user) for p in rows]}


@app.get("/api/projects/public")
def public_projects(request: Request):
    """Projects their owners made public (point 11): view-only for everyone, copyable when signed in."""
    user = _state(request).get("user")
    with db.Session() as s:
        rows = (s.query(db.Project, db.User.name).join(db.User, db.User.email == db.Project.owner)
                .filter(db.Project.is_public.is_(True))
                .order_by(db.Project.updated_at.desc()).limit(100).all())
        return {"projects": [{**_project_out(p, user), "owner_name": name} for p, name in rows]}


@app.post("/api/projects")
def create_project(body: ProjectIn, request: Request):
    """New project: a row, a folder, and a fresh scheme seeded from the chosen base classes."""
    user = _need_user(request)
    _check_bbox(body.bbox)
    if body.base_scheme not in ("indiasat", "worldcover"):
        raise HTTPException(400, "base must be indiasat or worldcover")
    year = min(max(int(body.year), AE_YEARS[0]), AE_YEARS[-1])
    name = body.name.strip() or "Untitled project"
    with db.Session() as s:
        p = db.Project(owner=user, name=name, bbox=list(body.bbox), year=year,
                       base_scheme=body.base_scheme)
        s.add(p)
        s.commit()
    projects.create_folder(p.id)
    tok = config.use_workspace(projects.folder(p.id))
    try:
        _switch_base(body.base_scheme)             # seeds hierarchy + active base in the new folder
        oplog.append("create", {"name": name, "bbox": list(body.bbox), "year": year,
                                "base_scheme": body.base_scheme})
    except Exception as e:
        with db.Session() as s:
            s.delete(s.get(db.Project, p.id))
            s.commit()
        projects.delete_folder(p.id)
        raise HTTPException(500, f"couldn't set up the project: {e}")
    finally:
        config.reset_workspace(tok)
    log.info("project %s created by %s", p.id, user)
    return _project_out(p, user)


@app.get("/api/projects/{pid}")
def get_project(pid: str, request: Request):
    """One project (the middleware already checked it's yours or public, and opened its workspace)."""
    st = _state(request)
    return {**st["project"], "mine": st.get("owner", False), **_tree_payload()}


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch, request: Request):
    user = _need_user(request)
    with db.Session() as s:
        p = s.get(db.Project, pid)
        if body.name is not None and body.name.strip():
            p.name = body.name.strip()
        if body.is_public is not None:
            p.is_public = body.is_public
        if body.year is not None:
            p.year = min(max(int(body.year), AE_YEARS[0]), AE_YEARS[-1])
        if body.bbox is not None:
            # Susmit's dataset lock: once a project has run, its area is part of what the runs mean;
            # a different area is a different project
            if p.current_run:
                raise HTTPException(409, "the area is fixed once a project has a run; start a new "
                                         "project for a different area")
            _check_bbox(body.bbox)
            p.bbox = list(body.bbox)
        s.commit()
        return _project_out(p, user)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str, request: Request):
    _need_user(request)
    with db.Session() as s:
        s.delete(s.get(db.Project, pid))
        s.commit()
    projects.delete_folder(pid)
    _cache.pop(str(projects.folder(pid)), None)
    return {"deleted": pid}


@app.post("/api/projects/{pid}/copy")
def copy_project(pid: str, request: Request):
    """Copy a public project (or one of your own) into a new project of yours: scheme, examples and
    weights come along, runs don't."""
    user = _need_user(request)
    src = _state(request)["project"]
    with db.Session() as s:
        p = db.Project(owner=user, name=f"Copy of {src['name']}", bbox=src["bbox"], year=src["year"],
                       base_scheme=src["base_scheme"])
        s.add(p)
        s.commit()
    projects.copy_project(pid, p.id)
    return _project_out(p, user)


def _new_project_row(user, name, bbox, year, base):
    _check_bbox(bbox)
    if base not in ("indiasat", "worldcover"):
        raise HTTPException(400, f"unknown base scheme {base!r}")
    with db.Session() as s:
        p = db.Project(owner=user, name=(name or "Imported project")[:120], bbox=list(bbox),
                       year=min(max(int(year or 2024), AE_YEARS[0]), AE_YEARS[-1]), base_scheme=base)
        s.add(p)
        s.commit()
    projects.create_folder(p.id)
    return p


def _drop_project(pid):
    with db.Session() as s:
        row = s.get(db.Project, pid)
        if row:
            s.delete(row)
            s.commit()
    projects.delete_folder(pid)


@app.post("/api/projects/import")
def import_project(request: Request, file: UploadFile = File(...)):
    """Resume a saved project as a new one of yours. Takes the zip "Download project" makes (scheme,
    examples, weights and runs all come back), or the project.json the pre-week-18 UI saved (scheme
    and steps; its splits reuse the shared models only where their classes still match, else they're
    listed for retraining). Replaces the old "Resume a saved project" file picker."""
    import io
    import zipfile
    user = _need_user(request)
    raw = file.file.read()
    stem = Path(file.filename or "project").stem
    if zipfile.is_zipfile(io.BytesIO(raw)):
        p, missing = _import_zip(user, raw, stem)
    else:
        p, missing = _import_json(user, raw, stem)
    return {**_project_out(p, user), "missing_classifiers": missing}


def _import_zip(user, raw, stem):
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(raw))
    try:
        meta = json.loads(z.read("project.json"))
    except KeyError:
        raise HTTPException(400, "this zip has no project.json; it isn't a Do It Yourself LULC project download")
    p = _new_project_row(user, meta.get("name") or stem, meta.get("bbox") or [], meta.get("year"),
                         meta.get("base_scheme", "indiasat"))
    dest = projects.folder(p.id)
    ok_top = set(projects.SCHEME_FILES) | {"examples", "weights", "runs"}
    try:
        for name in z.namelist():
            parts = Path(name).parts
            # only the layout we write ourselves; nothing absolute, nothing climbing out
            if (not parts or parts[0] not in ok_top or ".." in parts or Path(name).is_absolute()
                    or name.endswith("/")):
                continue
            out = dest.joinpath(*parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(name))
        tok = config.use_workspace(dest)
        try:
            report = validate_ops.validate_envelope({"hierarchy": hierarchy.load(), "op_log": oplog.load()})
            if not report["ok"]:
                raise HTTPException(400, {"message": "the saved scheme doesn't validate", **report})
            missing = validate_ops.missing_classifiers(hierarchy.load())
        finally:
            config.reset_workspace(tok)
    except Exception:
        _drop_project(p.id)
        raise
    runs = [r for r in (meta.get("runs") or []) if projects.read_run(p.id, r.get("run", 0))]
    with db.Session() as s:
        row = s.get(db.Project, p.id)
        row.runs, row.current_run = runs, max((r["run"] for r in runs), default=0)
        s.commit()
        return row, missing


def _import_json(user, raw, stem):
    try:
        f = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(400, "that isn't a project zip or a project .json")
    if not isinstance(f, dict):
        raise HTTPException(400, "that isn't a project zip or a project .json")
    tree = f.get("hierarchy") if "hierarchy" in f else f
    ops = f.get("sequence") or f.get("op_log") or []
    bbox = f.get("aoi")
    if not bbox:
        raise HTTPException(400, "this file has no area (aoi), so there's nothing to fix the project "
                                 "to; start a new project and import the classes into it instead")
    report = validate_ops.validate_envelope({"hierarchy": tree, "op_log": ops})
    if not report["ok"]:
        raise HTTPException(400, {"message": "the saved scheme doesn't validate", **report})
    p = _new_project_row(user, stem, bbox, f.get("year"), f.get("base_scheme", "indiasat"))
    tok = config.use_workspace(projects.folder(p.id))
    try:
        _switch_base(p.base_scheme)
        import joblib
        for cls, node in tree.items():
            clf = node.get("classifier")
            shared = Path(config.model_path(f"refine/{clf}.joblib")) if clf else None
            # an old save points at the shared weights of the day; reuse them only if they still
            # split into the same classes, otherwise that split waits for a retrain
            if shared and shared.exists():
                bundle = joblib.load(shared)
                if sorted(bundle.get("classes") or []) == sorted(node.get("children") or []):
                    joblib.dump(bundle, config.weights_write_path(clf))
        hierarchy.save(tree)
        oplog.replace(ops)
        oplog.append("import_hierarchy", {"file": stem})
        missing = validate_ops.missing_classifiers(tree)
    except Exception:
        config.reset_workspace(tok)
        tok = None
        _drop_project(p.id)
        raise
    finally:
        if tok:
            config.reset_workspace(tok)
    return p, missing


# ----------------------------- runs -----------------------------
class RunIn(BaseModel):
    name: str | None = None
    dag_run_id: str | None = None      # set when the run went through Airflow first


def _render_bbox(bbox, year):
    w, s_, e, n = bbox
    return classify(west=w, south=s_, east=e, north=n, mode="realistic", year=year)


@app.post("/api/projects/{pid}/runs")
def create_run(pid: str, body: RunIn, request: Request):
    """Run classification for the project and keep it as run_<n>: the map it drew, plus a frozen copy
    of the scheme that drew it. This is the only thing that computes a map (point 7)."""
    _need_user(request)
    proj = _state(request)["project"]
    out = _render_bbox(proj["bbox"], proj["year"])
    n = (proj["current_run"] or 0) + 1
    meta = projects.snapshot_run(pid, n, {
        "name": (body.name or "").strip() or f"Run {n}", "year": out.get("year", proj["year"]),
        "bbox": proj["bbox"], "base_scheme": proj["base_scheme"], "counts": out.get("counts"),
        "colors": out.get("colors"), "render": out.get("render"), "dag_run_id": body.dag_run_id,
        "op_seq": len(oplog.load())})
    with db.Session() as s:
        p = s.get(db.Project, pid)
        p.current_run = n
        p.runs = [*(p.runs or []), {k: meta[k] for k in ("run", "name", "created_at", "year")}]
        s.commit()
    return {"run": meta, **out}


@app.get("/api/projects/{pid}/runs/{n}")
def get_run(pid: str, n: int, request: Request):
    """Redraw a saved run from its own frozen scheme, so opening a project needs no re-run (point 9)."""
    meta = projects.read_run(pid, n)
    if not meta:
        raise HTTPException(404, f"no run {n} in this project")
    tok = config.use_workspace(projects.run_dir(pid, n))
    try:
        out = _render_bbox(meta["bbox"], meta["year"])
        run_tree = hierarchy.load()          # the classes as they were for this run, for visitors
    finally:
        config.reset_workspace(tok)
    return {"run": meta, "run_tree": run_tree, **out}


@app.get("/api/projects/{pid}/runs/{n}/geotiff")
def run_geotiff(pid: str, n: int, request: Request):
    """The run's GeoTIFF, saved into the run folder the first time it's asked for, then served from
    disk. One band of integer class codes; the code -> class legend goes into run.json."""
    meta = projects.read_run(pid, n)
    if not meta:
        raise HTTPException(404, f"no run {n} in this project")
    tif = projects.tif_path(pid, n)
    if not tif.exists():
        w, s_, e, nth = meta["bbox"]
        tok = config.use_workspace(projects.run_dir(pid, n))
        try:
            d = classify_geotiff(west=w, south=s_, east=e, north=nth, year=meta["year"])
        finally:
            config.reset_workspace(tok)
        import requests
        r = requests.get(d["url"], timeout=600)
        if r.status_code != 200:
            raise HTTPException(502, f"Earth Engine didn't hand the GeoTIFF over (HTTP {r.status_code})")
        tif.write_bytes(r.content)
        projects.update_run(pid, n, legend={str(i): c for i, c in enumerate(d["classes"])})
    safe = "".join(ch if ch.isalnum() else "_" for ch in _state(request)["project"]["name"])[:40]
    return FileResponse(tif, media_type="image/tiff", filename=f"{safe}_run{n}.tif")


@app.get("/api/projects/{pid}/download")
def download_project(pid: str, request: Request):
    """The whole project as a zip: scheme, op log, examples, weights, every run's record and GeoTIFF."""
    proj = _state(request)["project"]
    z = projects.zip_project(pid, proj)
    safe = "".join(ch if ch.isalnum() else "_" for ch in proj["name"])[:40]
    return FileResponse(z, media_type="application/zip", filename=f"{safe}.zip")


# ----------------------------- the standard upload format (point 9) -----------------------------
# One FeatureCollection, EPSG:4326, polygons, and exactly one required property: `class`. Optional
# `role` (positive / negative) and `note`. The classes are read off the file, so one upload can
# create a whole split and fill every child in one go. Full spec: week18/app_design.md section 3.4.
EXAMPLE_FORMAT = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"class": "acacia", "note": "desk-labelled crown"},
         "geometry": {"type": "Polygon", "coordinates": [[[77.1795, 28.5402], [77.1799, 28.5402],
                      [77.1799, 28.5406], [77.1795, 28.5406], [77.1795, 28.5402]]]}},
        {"type": "Feature", "properties": {"class": "non_acacia", "note": "neem"},
         "geometry": {"type": "Polygon", "coordinates": [[[77.1861, 28.5448], [77.1865, 28.5448],
                      [77.1865, 28.5452], [77.1861, 28.5452], [77.1861, 28.5448]]]}},
        {"type": "Feature", "properties": {"class": "acacia", "role": "negative",
                                           "note": "looks like acacia, isn't"},
         "geometry": {"type": "Polygon", "coordinates": [[[77.1830, 28.5420], [77.1834, 28.5420],
                      [77.1834, 28.5424], [77.1830, 28.5424], [77.1830, 28.5420]]]}},
    ],
}


@app.get("/api/upload-format/example.geojson")
def upload_example():
    return Response(json.dumps(EXAMPLE_FORMAT, indent=2), media_type="application/geo+json",
                    headers={"Content-Disposition": 'attachment; filename="example_labels.geojson"'})


def _parse_labelled(raw: bytes, bbox=None) -> dict:
    """Check an upload against the standard format and group it by class: {class: {role: [features]}}.
    Every problem found is reported together, so a user fixes the file once, not once per error."""
    from shapely.geometry import box, shape
    try:
        fc = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(400, "that file isn't valid JSON; the format is a GeoJSON FeatureCollection")
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection" or not fc.get("features"):
        raise HTTPException(400, "expected a GeoJSON FeatureCollection with at least one feature")
    errs, groups, inside = [], {}, 0
    area = box(*bbox) if bbox else None
    for i, f in enumerate(fc["features"], start=1):
        props, geom = (f.get("properties") or {}), f.get("geometry") or {}
        cls = str(props.get("class") or "").strip()
        role = str(props.get("role") or "positive").strip().lower()
        if not cls:
            errs.append(f"feature {i}: no 'class' property")
        if role not in examples.ROLES:
            errs.append(f"feature {i}: role must be positive or negative, not {role!r}")
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            errs.append(f"feature {i}: geometry must be a Polygon or MultiPolygon, not {geom.get('type')}")
            continue
        try:
            g = shape(geom)
        except Exception:
            errs.append(f"feature {i}: the polygon can't be read")
            continue
        x0, y0, x1, y1 = g.bounds
        if not (-180 <= x0 <= x1 <= 180 and -90 <= y0 <= y1 <= 90):
            errs.append(f"feature {i}: coordinates aren't lon/lat in EPSG:4326")
            continue
        if area is not None and g.intersects(area):
            inside += 1
        if cls and role in examples.ROLES:
            groups.setdefault(hierarchy.canonicalize(cls), {}).setdefault(role, []).append(
                {"type": "Feature", "geometry": geom, "properties": {}})
    if errs:
        more = f" (+{len(errs) - 8} more)" if len(errs) > 8 else ""
        raise HTTPException(400, "fix these and upload again: " + "; ".join(errs[:8]) + more)
    if area is not None and inside == 0:
        raise HTTPException(400, "none of these polygons fall inside the project's area")
    return groups


@app.post("/api/examples/labelled")
def upload_labelled(request: Request, node: str = Form(...), file: UploadFile = File(...)):
    """Build-your-own in one step: the file's classes become `node`'s children (a leaf gets split,
    a split node gains any class it's missing), and each polygon lands on its class."""
    _shared_base_guard(node)
    proj = _state(request).get("project")
    groups = _parse_labelled(file.file.read(), bbox=proj["bbox"] if proj else None)
    tree = hierarchy.load()
    if node not in tree:
        raise HTTPException(400, f"{node!r} isn't in your scheme")
    clash = [c for c in groups if c in tree and tree[c].get("parent") != node]
    if clash:
        raise HTTPException(400, f"{clash} already name a class elsewhere in your scheme; rename them "
                                 "in the file")
    children = tree[node].get("children") or []
    created = [c for c in groups if c not in children]
    if not children:
        if len(groups) < 2:
            raise HTTPException(400, "a split needs at least two classes in the file")
        refine.split_op(node, [{"name": c} for c in groups], do_train=False)
        oplog.append("split", {"parent": node, "children": list(groups), "from": "upload"})
    else:
        for c in created:
            refine.add_class_op(node, c, do_train=False)
            oplog.append("add", {"parent": node, "name": c, "from": "upload"})
    counts = {}
    for cls, by_role in groups.items():
        for role, feats in by_role.items():
            counts[cls] = examples.add_examples(cls, {"type": "FeatureCollection", "features": feats},
                                                role=role)
    oplog.append("upload", {"node": node, "file": file.filename, "classes": counts})
    return {"node": node, "classes": counts, "created": created, **_tree_payload()}


# ----------------------------- the gate: who you are, which project, what you may do -----------------------------
# One pure ASGI middleware (not @app.middleware: a ContextVar set there wouldn't reach the thread
# the handler runs on). Per request it reads the session cookie, finds the project the request is
# about (a /api/projects/<id>/ path, an X-Project-Id header, or ?project= on plain links), checks
# the caller may touch it, and opens that project's folder as the workspace. The rules are the
# cluster checklist's #4: no session, no compute and no writes.
import re
from starlette.responses import JSONResponse

_PROJECT_ROUTE = re.compile(r"^/api/projects/([0-9a-f]{12})(?:/|$)")
_PUBLIC_COPY = re.compile(r"^/api/projects/[0-9a-f]{12}/copy$")
_OPEN = ("/api/auth/", "/api/health", "/api/upload-format/")
# the DAG calls these back without a browser; SERVICE_TOKEN (like Susmit's X-Service-Token) vouches
_SERVICE = ("/api/export-asset", "/api/jobs", "/api/classify")
# reads that make Earth Engine work
_COMPUTE_READS = ("/api/classify", "/api/water", "/api/treecrop", "/api/farmshrub", "/api/segment",
                  "/api/water-frequency", "/api/export-asset", "/api/export-status", "/api/stacd")
# writes that change a scheme belong in a project, never in the shared data/ workspace
_SCHEME_WRITES = ("/api/split", "/api/add", "/api/retrain", "/api/examples", "/api/merge",
                  "/api/apply", "/api/base/select", "/api/session/reset", "/api/hierarchy/import")


class Gate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path.startswith(_OPEN):
            return await self.app(scope, receive, send)
        req = Request(scope)
        user = auth.read_cookie(req.cookies.get(auth.COOKIE))
        token = req.headers.get("x-service-token")
        # no SERVICE_TOKEN: the three DAG callback paths stay open without a session, so the tower's
        # current DAG (which sends no token) keeps working. Everything else still needs sign-in, and
        # setting SERVICE_TOKEN on both sides closes these too (checklist #4 in full)
        service = (token == config.SERVICE_TOKEN if config.SERVICE_TOKEN
                   else path.startswith(_SERVICE) and not user)
        write = scope["method"] not in ("GET", "HEAD", "OPTIONS")
        state = scope.setdefault("state", {})
        state["user"] = user

        async def deny(code, msg):
            await JSONResponse({"detail": msg}, status_code=code)(scope, receive, send)

        m = _PROJECT_ROUTE.match(path)
        pid = (m.group(1) if m else None) or req.headers.get("x-project-id") or req.query_params.get("project")
        if pid:
            with db.Session() as s:
                p = s.get(db.Project, pid)
            if not p:
                return await deny(404, "no such project")
            owner = user is not None and user == p.owner
            if not (owner or service or (p.is_public and (not write or _PUBLIC_COPY.match(path)))):
                return await deny(401 if not user else 403,
                                  "sign in first" if not user else "that project isn't yours")
            state["project"], state["owner"] = db.project_dict(p), owner
            tok = config.use_workspace(projects.folder(pid))
            try:
                return await self.app(scope, receive, send)
            finally:
                config.reset_workspace(tok)

        if (write or path.startswith(_COMPUTE_READS)) and not (user or service):
            return await deny(401, "sign in first")
        if write and path.startswith(_SCHEME_WRITES) and not service:
            return await deny(400, "open a project first; scheme changes happen inside a project")
        return await self.app(scope, receive, send)


app.add_middleware(Gate)


# serve the frontend (mount last so /api/* wins)
# Google's sign-in opens a popup that hands the result back with postMessage; this is the opener
# policy Google asks for on pages that do that, so no proxy default can block the hand-off
_PAGE_HEADERS = {"Cross-Origin-Opener-Policy": "same-origin-allow-popups"}


@app.get("/")
def front_page():
    """The front page (point 8): what this is, the video, public outputs, sign in."""
    return FileResponse(_STATIC / "landing.html", headers=_PAGE_HEADERS)


@app.get("/app")
def app_page():
    """The tool itself. Signed-out visitors get bounced to the front page by the page's own script."""
    return FileResponse(_STATIC / "index.html", headers=_PAGE_HEADERS)


@app.get("/config.js")
def frontend_config():
    """The page's runtime config, generated rather than baked into app.js: where to send /api calls
    (empty = relative, what the single-container deploy wants) and whether Airflow is wired, which
    decides if the long ops go through the DAG or run inline. Declared before the static mount so
    this route wins over any file of the same name."""
    cfg = json.dumps({"apiBase": config.API_BASE_URL, "airflow": airflow_client.configured(),
                      "googleClientId": config.GOOGLE_CLIENT_ID or None,
                      "devLogin": auth.dev_login_allowed(), "introVideo": config.INTRO_VIDEO_URL or None,
                      "filesUrl": config.FILEBROWSER_URL or None})
    return Response(f"window.CORESTACK_CFG = {cfg};\n", media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})   # no-store: it changes with the .env


app.mount("/", StaticFiles(directory=_STATIC), name="static")


# ----------------------------- the sample projects -----------------------------
# A fresh deploy shows the demo public projects on the front page: Sanjay Van acacia / non-acacia and
# the Jharia coalfield mining split. Each is a "Download project" zip under samples/ (code, not data/, so
# a relocated data mount still has them), imported once. The marker lists what's been seeded, so deleting
# one on the box sticks; a public project already carrying the same name (added by hand) counts as seeded.
SAMPLES_DIR = _ROOT / "samples"
SAMPLE_OWNER = ("sample@local.dev", "CoRE stack sample")


def _seed_samples():
    import io
    import zipfile
    marker = config.DATA_DIR / ".samples_seeded"
    done = set(marker.read_text().split()) if marker.exists() else set()
    if (config.DATA_DIR / ".sample_seeded").exists():
        done.add("jharia_sample.zip")             # the one-sample marker from before
    email, owner = SAMPLE_OWNER
    for z in sorted(SAMPLES_DIR.glob("*.zip")):
        if z.name in done:
            continue
        try:
            raw = z.read_bytes()
            title = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read("project.json")).get("name")
            with db.Session() as s:
                u = s.get(db.User, email)
                if not u:
                    s.add(db.User(email=email, name=owner))
                else:
                    u.name = owner                # older deploys named it "Core Stack sample"
                s.commit()
                taken = s.query(db.Project).filter_by(name=title, is_public=True).first()
            if not taken:
                p, _ = _import_zip(email, raw, z.stem)
                with db.Session() as s:
                    s.get(db.Project, p.id).is_public = True
                    s.commit()
                log.info("seeded the sample project %s from %s", p.id, z.name)
            done.add(z.name)
            marker.write_text(" ".join(sorted(done)))
        except Exception:
            log.exception("couldn't seed %s; carrying on without it", z.name)   # never blocks boot


_seed_samples()
