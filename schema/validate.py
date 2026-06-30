"""Validate the live catalogue cards against the canonical JSON Schemas.

The week-4 worked examples are validated separately by week4/schema/validate.py against
the week-4 schemas (they predate the type/inference fields). This one is the real gate:
it checks everything the tool actually mints into data/catalogue/.

Run from repo root:  python schema/validate.py [card_dir]
"""
import glob
import json
import os
import sys

import jsonschema
from jsonschema import Draft7Validator, RefResolver

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ds_schema = json.load(open(os.path.join(HERE, "dataset_card.schema.json")))
mc_schema = json.load(open(os.path.join(HERE, "model_card.schema.json")))

# model schema $refs the dataset schema by filename and by $id; register both spellings
store = {
    "dataset_card.schema.json": ds_schema,
    ds_schema["$id"]: ds_schema,
    mc_schema["$id"]: mc_schema,
}
resolver = RefResolver(base_uri="", referrer=mc_schema, store=store)


def validate(path, schema):
    Draft7Validator(schema, resolver=resolver).validate(json.load(open(path)))


def main(card_dir):
    paths = sorted(glob.glob(os.path.join(card_dir, "**", "*.json"), recursive=True))
    paths = [p for p in paths if os.path.basename(p) != "index.json"]
    if not paths:
        print(f"no cards under {card_dir} (run a backfill first)")
        return True
    ok = True
    for path in paths:
        name = os.path.basename(path)
        schema = mc_schema if name.startswith("mc_") else ds_schema
        try:
            validate(path, schema)
            print(f"PASS  {name}")
        except jsonschema.ValidationError as e:
            ok = False
            print(f"FAIL  {name}: {e.message} (at {'/'.join(map(str, e.path))})")
    print("\nall cards valid" if ok else "\nSOME CARDS FAILED")
    return ok


if __name__ == "__main__":
    card_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "catalogue")
    sys.exit(0 if main(card_dir) else 1)
