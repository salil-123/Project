"""Package the water model as a 26 class zoo model (week 22, sir's point 1).

Reads the shipped model json (week16/models/water_linear_nbhd.json, the one the methodology doc scores)
and writes
  models/refine/water_fortnights.joblib                 the bundle infer reads (features="water_fortnights")
  data/catalogue_seed/models/mc_water_fortnights_v1.json  its zoo card (an ordinary per node split)
  data/catalogue_seed/artifacts/mc_water_fortnights_v1.joblib
and retires the old one-fortnight-at-a-time card (mc_water_fortnight_augmented_v1), so the zoo keeps a
single water model. The app picks all of it up on its next start (catalogue.seed_from_bundled).

    python scripts/build_water_fortnights.py
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import water_fortnights as wf     # noqa: E402

SRC = ROOT / "week16" / "models" / "water_linear_nbhd.json"
BUNDLE = ROOT / "models" / "refine" / "water_fortnights.joblib"
SEED = ROOT / "data" / "catalogue_seed"
CARD_ID = "mc_water_fortnights_v1"
OLD = "mc_water_fortnight_augmented_v1"
INDIA = [68.0, 6.0, 97.5, 37.5]
# blues only, from the palest to near-black navy: the later water lasts, the darker the class. The ends
# are pushed as far as blue goes so neighbouring fortnights stay apart
RAMP = ["#eef6ff", "#d4e6f7", "#b3d3ee", "#85bce3", "#5aa0d6", "#3482c4", "#1765ad", "#0b4a8f",
        "#08306b", "#041a40"]


def ramp(n):
    """`n` colours evenly along RAMP."""
    rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in RAMP]
    out = []
    for k in range(n):
        x = k / (n - 1) * (len(rgb) - 1)
        i = min(int(x), len(rgb) - 2)
        f = x - i
        out.append("#%02x%02x%02x" % tuple(round(a + (b - a) * f) for a, b in zip(rgb[i], rgb[i + 1])))
    return out


def main():
    spec = json.loads(SRC.read_text())
    bundle = {"features": "water_fortnights", "classes": list(wf.CLASSES), "spec": spec, "label": "last",
              "algo": "linearsvc", "start_month": wf.START_MONTH}
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, BUNDLE)

    card = {
        "id": CARD_ID,
        "name": "Water by fortnight (26 classes, Sentinel-1/2)",
        "node": "water",
        "parent_class": "root",
        "topology": "per_node_split",
        "produces": [{"class": c, "color": col} for c, col in zip(wf.CLASSES, ramp(len(wf.CLASSES)))],
        "training": {"datasets": ["ds_seasonal_water_v1"],
                     "embedding": {"source": "sentinel1+2 fortnight", "dim": len(spec["fusion"]["neighbourhood"]["bands"])},
                     "algo": "linearsvc, pixel + neighbourhood model per sensor case",
                     "class_weight": "balanced"},
        "inference": {"dataset": None,
                      "embedding": {"source": "sentinel1+2 fortnight",
                                    "bands": spec["fusion"]["neighbourhood"]["bands"]}},
        "extent": {"spatial": {"type": "bbox", "value": INDIA},
                   "temporal": {"note": "the June to May water year starting in the project's year"}},
        "metrics": {"eval": "independent ground truth, June 2023 to May 2024, per pixel water / not water",
                    "precision": 0.87, "recall": 0.79, "f1": 0.83, "false_water_on_land": 0.116,
                    "per_class": {"water": {"precision": 0.87, "recall": 0.79, "f1": 0.83}}},
        "artifact": {"path": "data/refine/water_fortnights.joblib", "format": "sklearn-joblib",
                     "published_path": f"artifacts/{CARD_ID}.joblib"},
        "deployment": {"ee_asset": None, "tile_url": None, "expressible_as_bandmath": True},
        "lineage": {"base_model": None, "derived_from": "ds_seasonal_water_v1"},
        "about": {
            "description": "Splits water into 26 classes, one per fortnight of the June to May year: the "
                           "last fortnight a pixel held water, so fortnight26 is water all year and an early "
                           "number is water that dried up early. Rename the classes, or give several the "
                           "same name to merge them, e.g. kharif / rabi / zaid.",
            "intended_use": "Use it on Water (or any water-like class) to see how long into the year water "
                            "lasted, per pixel.",
            "limitations": "Water pixels that never held water that year stay unlabelled. Every run builds "
                           "26 fortnights of Sentinel-1/2, so it is slower than an Alpha Earth split. "
                           "Ponds under about 500 m2 and spells under a fortnight are below what it resolves.",
            "evidence": "week21/deliverable/water_methodology.md, section 2"},
        "zoo": {"published": False, "valid_region_label": "India", "contributor": ""},
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (SEED / "models" / f"{CARD_ID}.json").write_text(json.dumps(card, indent=2))
    shutil.copy2(BUNDLE, SEED / "artifacts" / f"{CARD_ID}.joblib")

    # one water model in the zoo: the old card leaves the seed and every box's live zoo
    for f in (SEED / "models" / f"{OLD}.json", SEED / "artifacts" / f"{OLD}.joblib"):
        f.unlink(missing_ok=True)
    retired = json.loads((SEED / "retired.json").read_text())
    if OLD not in retired["models"]:
        retired["models"].append(OLD)
    (SEED / "retired.json").write_text(json.dumps(retired, indent=2))
    print(f"wrote {BUNDLE.relative_to(ROOT)} and {CARD_ID}; retired {OLD}")


if __name__ == "__main__":
    main()
