"""Central config + Earth Engine initialization for the Core Stack project."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

EE_PROJECT = os.getenv("EE_PROJECT", "modern-mystery-398416")
EE_USER_ID = os.getenv("EE_USER_ID", "salilsandeshgujar")

# ----------------------------- Filesystem anchors (deploy) -----------------------------
# The app must run the same no matter the current working directory, so it can be driven by
# Docker / Airflow / systemd / nginx rather than only `cd repo && uvicorn ...`. Everything is
# anchored off the repo root computed from this file's location (config.py lives at the root).
# Both anchors are env-overridable: CORESTACK_ROOT relocates the code, CORESTACK_DATA_DIR lets a
# container mount the writable data/ as a volume somewhere else entirely.
PROJECT_ROOT = Path(os.getenv("CORESTACK_ROOT") or Path(__file__).resolve().parent)
DATA_DIR = Path(os.getenv("CORESTACK_DATA_DIR") or (PROJECT_ROOT / "data"))
SCHEMA_DIR = PROJECT_ROOT / "schema"


def project_path(rel) -> str:
    """Resolve a repo-relative path (e.g. 'data/refine/x.joblib' or 'schema/foo.json') against the
    project root, so it opens from any working directory. The 'data/...' family honors DATA_DIR (for
    a relocated volume); everything else anchors to PROJECT_ROOT. Absolute inputs pass through.
    Returns a str for drop-in use with open/joblib/os.path."""
    p = Path(rel)
    if p.is_absolute():
        return str(p)
    parts = p.parts
    if parts and parts[0] == "data":
        return str(DATA_DIR.joinpath(*parts[1:]))
    return str(PROJECT_ROOT / p)

# ----------------------------- AOI size caps (#3) -----------------------------
# Guardrails so a user can't draw a huge box and blow up compute/download time. All
# admin-tunable via .env (a server admin sizing the deployment can loosen/tighten these;
# see week9/benchmarks.md). The three paths cost very differently:
#   - AE tiles: EE renders on demand, nothing downloaded -> generous cap (reduceRegion is
#     the only real cost, and it's bestEffort).
#   - GeoTIFF: getDownloadURL is synchronous + size-capped by EE -> a much smaller cap.
#   - Tessera: each 0.1 deg tile is ~150 MB downloaded locally -> cap the tile *count*.
# Where classified rasters get exported as GEE assets (the STACD output). Defaults to this project's
# asset root; override to a project/path you can actually write to, or the one Saharsh's pipeline gives
# us (e.g. their CoreStack project). The /api/export-asset caller can also pass an explicit asset_id.
EE_ASSET_ROOT = os.getenv("EE_ASSET_ROOT", f"projects/{EE_PROJECT}/assets/corestack_lulc")

# Public base URL for STAC asset/link hrefs so they come out ABSOLUTE — a STAC browser can't render a
# relative '/api/...'. Set to wherever the backend is reachable (e.g. http://act4dws5/corestack-lulc, or
# an ngrok URL). Empty -> hrefs stay relative. The /api/export-asset call can also pass `asset_base`.
STAC_ASSET_BASE = os.getenv("STAC_ASSET_BASE", "")

AOI_TILE_CAP_KM2 = float(os.getenv("AOI_TILE_CAP_KM2", "40000"))     # ~200x200 km
AOI_GEOTIFF_CAP_KM2 = float(os.getenv("AOI_GEOTIFF_CAP_KM2", "600"))  # ~25x25 km
AOI_TESSERA_MAX_TILES = int(os.getenv("AOI_TESSERA_MAX_TILES", "6"))  # ~6 x 150 MB

# minimum polygon area (hectares) when vectorizing a class into segments (#4 wk10). Below this a
# blob is treated as speckle and dropped, so mining "objects" come out clean, not as pixel confetti.
SEGMENT_MIN_AREA_HA = float(os.getenv("SEGMENT_MIN_AREA_HA", "0.5"))

# spurious-water de-spuriing threshold (#13 wk11): the annual water layer holds a pixel as water only
# if the fortnight model called it water in at least this many fortnights, so a road water-logged for
# one fortnight (or S1 speckle) doesn't survive. A correction in infer.annual_water_mask, not a UI knob.
WATER_MIN_FORTNIGHTS = int(os.getenv("WATER_MIN_FORTNIGHTS", "2"))

# Ground-truth assets (per instructions.txt). Marked with access status as of
# last check on 2026-05-23 against project modern-mystery-398416.
GT_ASSETS = {
    # core_class : list of (asset_path, access_ok)
    "indiasat_4class":   "projects/ee-indiasat/assets/IndiaSat",                                 # OK
    "farmforest":        "projects/ee-indiasat/assets/Polygon_Groundtruth/FarmForest_Groundtruth",  # OK
    "binary_water":      "projects/ee-vatsal/assets/GT_BINARY_LATEST",                           # OK
    # "chahat_*": path TBD — confirm exact asset path with Chahat (PRIMARY source)
}

# OPTIONAL / FUTURE — only needed to sub-split water into seasonal vs perennial.
# Not required for the base greenery/water/built-up classifier. Need sharing.
OPTIONAL_ASSETS = {
    "water_seasonal":    "projects/ee-mtpictd/assets/GTSeasonal",
    "water_perennial":   "projects/ee-mtpictd/assets/GTPerennial",
}


# optional service-account key (a JSON file) for headless / shared use: point EE_SERVICE_ACCOUNT_KEY at
# it and the app authenticates AS that robot identity on EE_PROJECT, instead of a personal
# `earthengine authenticate` token. This is how someone else (e.g. Saharsh) runs the container against
# OUR project without our personal login. Falls back to the normal token flow when unset.
EE_SERVICE_ACCOUNT_KEY = os.getenv("EE_SERVICE_ACCOUNT_KEY", "")


def ee_init():
    """Initialize Earth Engine on EE_PROJECT and return the ee module. Uses a service-account key if
    EE_SERVICE_ACCOUNT_KEY points at one, otherwise the local `earthengine authenticate` credentials."""
    import ee
    if EE_SERVICE_ACCOUNT_KEY and os.path.exists(EE_SERVICE_ACCOUNT_KEY):
        import json
        email = json.load(open(EE_SERVICE_ACCOUNT_KEY)).get("client_email")
        creds = ee.ServiceAccountCredentials(email, EE_SERVICE_ACCOUNT_KEY)
        ee.Initialize(creds, project=EE_PROJECT)
    else:
        ee.Initialize(project=EE_PROJECT)
    return ee


if __name__ == "__main__":
    ee = ee_init()
    print("EE init OK, project =", EE_PROJECT, "| test =", ee.Number(1).getInfo())
