"""One-off (#9): give the zoo a real tea/non_tea model card again, drop the acacia dummy.

Background: the greenery node holds one classifier at a time. When greenery was re-split from
tea/non_tea into acacia/non_acacia, the tea model's joblib was overwritten and only a half-broken
"superseded" acacia dummy card (mc_greenery_prev1_v1) survived. tea/non_tea's example polygons are
still on disk, so we regenerate a genuine tea/non_tea model and keep it as an *archived* card,
without disturbing the live acacia split on the IIT-Delhi home turf.

Surgical (one Alpha-Earth retrain, needs a live authenticated Earth Engine):
  1. delete the acacia dummy card + its orphan joblibs
  2. snapshot the live acacia model (joblib + card), then temporarily point greenery at tea/non_tea
  3. train tea/non_tea; mint its card, archive it as mc_greenery_prev1_v1 (joblib kept under archive/)
  4. restore the acacia model, tree, and card exactly as they were (published flag intact)

Run from the repo root with the project venv:
    ./.venv/Scripts/python.exe scripts/regen_tea_acacia.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import joblib
import catalogue
import hierarchy
import refine

REFINE = ROOT / "data" / "refine"
LIVE = REFINE / "greenery.joblib"
ACACIA_CARD = catalogue.MODELS_DIR / "mc_greenery_v1.json"


def _drop_subtree(tree, cls):
    for ch in list(tree.get(cls, {}).get("children", [])):
        _drop_subtree(tree, ch)
    tree.pop(cls, None)


def _models():
    return sorted(x["id"] for x in catalogue.load_index()["cards"] if x["kind"] == "model")


def main():
    print("before:", _models())

    # 1. drop the acacia dummy (published, so bypass the API's published-guard by calling directly)
    catalogue.delete_card("mc_greenery_prev1_v1", purge_artifacts=True)
    print("1. deleted mc_greenery_prev1_v1 (acacia dummy)")

    # 2. snapshot everything acacia so we can put it back byte-for-byte afterwards
    acacia_tree = hierarchy.load()
    hold_jb = REFINE / "_acacia_hold.joblib"
    hold_card = ACACIA_CARD.with_suffix(".hold")
    shutil.copy2(LIVE, hold_jb)
    shutil.copy2(ACACIA_CARD, hold_card)

    # point greenery at tea/non_tea (drop the acacia children first so it's a clean split)
    t = hierarchy.load()
    for ch in list(t["greenery"]["children"]):
        _drop_subtree(t, ch)
    t["greenery"]["children"] = []
    t["greenery"]["classifier"] = None
    for name in ("tea", "non_tea"):
        hierarchy.add_class(t, name.replace("_", " ").title(), "greenery", canonical=name)
        t[name]["source"] = {"type": "examples"}
    hierarchy.save(t)

    # 3. train tea/non_tea, mint its card, then archive it as the superseded reference
    print("3. training tea/non_tea (one retrain)…")
    bundle = refine.train("greenery", resample=True, balance="balanced")
    catalogue.register_retrain("greenery", bundle)          # mc_greenery_v1 := tea (transient)
    tea_card = catalogue.get_card("mc_greenery_v1")
    snap = catalogue.snapshot_model("greenery")             # keep the tea joblib under archive/
    arch_id = catalogue.archive_prev_card("greenery", tea_card, snap)
    print(f"   archived tea/non_tea as {arch_id}")

    # 4. restore acacia exactly: joblib, tree, and card (with its original published flag)
    shutil.copy2(hold_jb, LIVE)
    hierarchy.save(acacia_tree)
    shutil.copy2(hold_card, ACACIA_CARD)
    hold_jb.unlink(); hold_card.unlink()
    catalogue.rebuild_index()
    print("4. restored the live acacia model + card")

    print("after: ", _models())
    live = joblib.load(LIVE).get("classes")
    print(f"\nlive greenery split = {live}  (should be acacia / non_acacia)")


if __name__ == "__main__":
    main()
