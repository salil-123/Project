"""Validate the worked example cards against the JSON Schemas.

Proof that the schema fits real artifacts. Run from repo root:
  python week4/schema/validate.py
"""
import glob
import json
import os

import jsonschema
from jsonschema import Draft7Validator, RefResolver

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "notes", "examples")

ds_schema = json.load(open(os.path.join(HERE, "dataset_card.schema.json")))
mc_schema = json.load(open(os.path.join(HERE, "model_card.schema.json")))

# the model schema $refs the dataset schema by filename + by $id; register both
store = {
    "dataset_card.schema.json": ds_schema,
    ds_schema["$id"]: ds_schema,
    mc_schema["$id"]: mc_schema,
}
resolver = RefResolver(base_uri="", referrer=mc_schema, store=store)


def validate(path, schema):
    card = json.load(open(path))
    Draft7Validator(schema, resolver=resolver).validate(card)


ok = True
for path in sorted(glob.glob(os.path.join(EXAMPLES, "*.json"))):
    name = os.path.basename(path)
    schema = mc_schema if name.startswith("mc_") else ds_schema
    try:
        validate(path, schema)
        print(f"PASS  {name}")
    except jsonschema.ValidationError as e:
        ok = False
        print(f"FAIL  {name}: {e.message} (at {'/'.join(map(str, e.path))})")

print("\nall cards valid" if ok else "\nSOME CARDS FAILED")
