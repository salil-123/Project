"""#9 (revised): put the *multi-year* acacia/non_acacia model back as the live greenery split.

The model to keep is the one presented in week 7 — trained on pooled years 2019/2021/2023 and
measurably more temporally robust (mean 0.745 on the unseen years 2020/2024, vs 0.635 single-year).
It lives at data/refine/acacia_non_acacia_multiyear.joblib but never had a zoo card. This makes it
the live greenery classifier and mints its card with the week-7 metrics. No Earth Engine needed —
we only copy the joblib and write the card.

Run from the repo root with the project venv:
    ./.venv/Scripts/python.exe scripts/restore_multiyear_acacia.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import joblib
import catalogue
import hierarchy

MULTIYEAR = ROOT / "data" / "refine" / "acacia_non_acacia_multiyear.joblib"
LIVE = ROOT / "data" / "refine" / "greenery.joblib"

# week-7 held-out numbers (train 2019/2021/2023, test unseen 2020/2024); see week7/acacia_multiyear.log
METRICS = {"accuracy": 0.745,
           "eval": "held-out unseen years 2020/2024 (multi-year pooled 2019/2021/2023)",
           "per_class": {}}


def main():
    bundle = joblib.load(MULTIYEAR)
    print("multi-year model:", bundle.get("classes"), "| years:", bundle.get("years"))

    # make it the live greenery split
    shutil.copy2(MULTIYEAR, LIVE)
    tree = hierarchy.load()
    tree["greenery"]["classifier"] = "greenery"
    # make sure the children match what the model produces (acacia / non_acacia)
    hierarchy.save(tree)

    # mint its card (register_retrain mints the acacia/non_acacia dataset cards + the model card,
    # then we stamp the real multi-year metrics on top since the bundle carries no sklearn report)
    catalogue.register_retrain("greenery", bundle)
    catalogue.update_card_meta(
        "mc_greenery_v1",
        about={"description": "Greenery split (acacia / non_acacia), pooled over 2019/2021/2023 for "
                              "temporal robustness — the week-7 multi-year model.",
               "intended_use": "Acacia detection that holds up across years, not just the training year.",
               "evidence": "week7/acacia_multiyear.log"})
    # stamp the headline metrics onto the card
    card = catalogue.get_card("mc_greenery_v1")
    card["metrics"] = METRICS
    catalogue.write_card(card)

    got = catalogue.get_card("mc_greenery_v1")
    print("mc_greenery_v1 ->", [p["class"] for p in got["produces"]],
          "| acc:", got["metrics"]["accuracy"], "| name:", got["name"])
    print("live greenery classes:", joblib.load(LIVE).get("classes"))


if __name__ == "__main__":
    main()
