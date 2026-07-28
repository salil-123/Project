"""Central config + Earth Engine initialization for the Core Stack project."""
import os
from dotenv import load_dotenv

load_dotenv()

EE_PROJECT = os.getenv("EE_PROJECT", "modern-mystery-398416")
EE_USER_ID = os.getenv("EE_USER_ID", "salilsandeshgujar")

# ----------------------------- AOI size caps (#3) -----------------------------
# Guardrails so a user can't draw a huge box and blow up compute/download time. All
# admin-tunable via .env (a server admin sizing the deployment can loosen/tighten these;
# see week9/benchmarks.md). The three paths cost very differently:
#   - AE tiles: EE renders on demand, nothing downloaded -> generous cap (reduceRegion is
#     the only real cost, and it's bestEffort).
#   - GeoTIFF: getDownloadURL is synchronous + size-capped by EE -> a much smaller cap.
#   - Tessera: each 0.1 deg tile is ~150 MB downloaded locally -> cap the tile *count*.
AOI_TILE_CAP_KM2 = float(os.getenv("AOI_TILE_CAP_KM2", "40000"))     # ~200x200 km
AOI_GEOTIFF_CAP_KM2 = float(os.getenv("AOI_GEOTIFF_CAP_KM2", "600"))  # ~25x25 km
AOI_TESSERA_MAX_TILES = int(os.getenv("AOI_TESSERA_MAX_TILES", "6"))  # ~6 x 150 MB

# minimum polygon area (hectares) when vectorizing a class into segments (#4 wk10). Below this a
# blob is treated as speckle and dropped, so mining "objects" come out clean, not as pixel confetti.
SEGMENT_MIN_AREA_HA = float(os.getenv("SEGMENT_MIN_AREA_HA", "0.5"))

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


def ee_init():
    """Initialize Earth Engine with the project. Returns the ee module."""
    import ee
    ee.Initialize(project=EE_PROJECT)
    return ee


if __name__ == "__main__":
    ee = ee_init()
    print("EE init OK, project =", EE_PROJECT, "| test =", ee.Number(1).getInfo())
