"""Turn the raw acacia crown labels into example files the refinement engine can train on.

`acacia_clean_confident_labels.geojson` is a research export of tree-crown polygons over the
IIT Delhi / Sanjay Van strip, carrying many label columns. The one we trust is
`label_acacia_clean_confident`: 1 = acacia, 0 = non-acacia, -1 = not confidently labelled.

We keep only the confident crowns and split them into two node/role example files
(`data/examples/acacia.geojson`, `data/examples/non_acacia.geojson`) in the exact shape
examples.add_examples writes, so an acacia/non-acacia split trains straight from them like
tea/non_tea already does. The raw file gets tucked into data/inputs/ afterwards.

Run once from the repo root:  python scripts/prep_acacia_examples.py
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "acacia_clean_confident_labels.geojson"
RAW_DEST = ROOT / "data" / "inputs" / "acacia_clean_confident_labels.geojson"
EXAMPLES = ROOT / "data" / "examples"
LABEL_COL = "label_acacia_clean_confident"
NODE_FOR = {1: "acacia", 0: "non_acacia"}   # confident label -> class node


def _feature(geom, node, props):
    """One example feature in the same shape examples.add_examples produces, but also carrying the
    crown's `area` (its source region/tile) and `crown_uid` so a spatial (region-held-out) split is
    possible later (#8 wk10). These extra properties are ignored by the normal training path."""
    return {"type": "Feature", "geometry": geom,
            "properties": {"node": node, "role": "positive", "name": node,
                           "area": props.get("area"), "crown_uid": props.get("crown_uid"),
                           "ts": datetime.now(timezone.utc).isoformat()}}


def main():
    src = RAW if RAW.exists() else RAW_DEST   # allow re-runs after the raw file has moved
    if not src.exists():
        raise SystemExit(f"raw acacia file not found at {RAW} or {RAW_DEST}")

    crowns = json.loads(src.read_text(encoding="utf-8"))["features"]
    buckets = {node: [] for node in NODE_FOR.values()}
    for f in crowns:
        props = f.get("properties", {})
        node = NODE_FOR.get(props.get(LABEL_COL))
        if node:                              # drop the -1 (unconfident) crowns
            buckets[node].append(_feature(f["geometry"], node, props))

    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for node, feats in buckets.items():
        fc = {"type": "FeatureCollection", "features": feats}
        (EXAMPLES / f"{node}.geojson").write_text(json.dumps(fc), encoding="utf-8")
        print(f"wrote {len(feats):>4} crowns -> data/examples/{node}.geojson")

    # move the bulky raw file out of the repo root to its proper home
    if RAW.exists():
        RAW_DEST.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(RAW), str(RAW_DEST))
        print(f"moved raw labels -> {RAW_DEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
