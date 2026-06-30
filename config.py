"""Central config + Earth Engine initialization for the Core Stack project."""
import os
from dotenv import load_dotenv

load_dotenv()

EE_PROJECT = os.getenv("EE_PROJECT", "modern-mystery-398416")
EE_USER_ID = os.getenv("EE_USER_ID", "salilsandeshgujar")

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
