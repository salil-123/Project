"""STACD provenance for a classified LULC output (#4).

Per the STACD paper (Laud et al., PROPL'25 — STAC extended with DAGs, from this same CoRE-stack
lab), every geospatial output should be self-describing: not just *what* it is (a STAC Item) but
*how* it was produced — the algorithms, their versions, and the input datasets/params. STAC's
`derived_from` is too shallow for our multi-model hierarchy, so we emit the STACD classes:

  - **stack-spec**  -> a STAC Item / `Dataset_Instance` for the LULC raster (bbox, geometry,
    assets, class legend).
  - **stacd spec**  -> the DAG + `Dataset_Type`/`Algorithm_Type` nodes + `Algorithm_Instance`s
    (each live model/rule/merge with where its artifact lives) + the output `Dataset_Instance`
    whose `alg_inputs` embeds our hierarchy scheme — literally "the input set used to produce
    this", as sir framed it.

Everything here reuses metadata we already keep (hierarchy tree, op-log, zoo cards) — no new
source of truth. All offline: the legend comes from the joblib class lists, not a live EE run, so
this is a cheap metadata call. We emit JSON (STAC is JSON; the paper's Airflow impl uses YAML for
editing convenience). Reference impl: https://github.com/SaharshLaud/STACD-Airflow
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py

import merges
import hierarchy
import infer
import oplog
import catalogue

STAC_VERSION = "1.0.0"
STACD_REF = "https://github.com/SaharshLaud/STACD-Airflow"
AE_DATASET = "ds_alphaearth_annual_v1"
ALG_TYPE_ID = "CoreStack_LULC"      # the one Algorithm_Type every per-node model is an instance of


def _leaf_legend(colors):
    """The classes that survive to the raster (base -> splits/rules -> merges), as a code->name->
    colour legend. Pure joblib/tree read — no EE — so it mirrors what a classify would paint."""
    model = infer.load_model()
    refs = infer.load_refinements()
    leaves = infer._leaf_classes(model, refs)
    s2t = merges.source_to_target()
    display = []
    for c in leaves:                       # fold merge sources into their target, in order
        nc = s2t.get(c, c)
        if nc not in display:
            display.append(nc)
    return [{"code": i, "class": c, "color": colors.get(c, "#999999")}
            for i, c in enumerate(display)]


def _node_resolvers():
    """Every node that resolves its own children -> a small provenance record: kind (model / rule /
    merge-implied), the zoo card id, and where its artifact lives. This is the algorithm side."""
    tree = hierarchy.load()
    out = []
    for cls, node in tree.items():
        if node.get("classifier"):
            cid = f"mc_{node['classifier']}_v1"
            out.append({"node": cls, "kind": "model", "card": cid,
                        "artifact": f"data/refine/{node['classifier']}.joblib"})
        elif node.get("rule"):
            out.append({"node": cls, "kind": "rule", "card": f"mc_{cls}_rule_v1",
                        "artifact": "data/hierarchy.json"})
    for r in merges.load():                # merges are relabel algorithms too
        out.append({"node": r["target"], "kind": "merge", "card": f"mc_merge_{r['target']}_v1",
                    "artifact": "data/merge_rules.json"})
    return out


def _algorithm_instances(resolvers):
    """STACD Algorithm_Instance per resolver, matching the paper's class (id + version + type +
    assets). `type` is the Algorithm_Type this is an instance of (our single CoreStack_LULC), `id`
    uniquely names the instance, and `role` keeps our own kind+node detail (model/rule/merge). We
    read the zoo card for a published code/model location when there is one, else the local path."""
    insts = []
    for r in resolvers:
        card = catalogue.get_card(r["card"]) or {}
        art = card.get("artifact") or {}
        loc = art.get("published_path") or art.get("path") or r["artifact"]
        insts.append({
            "id": f"{r['kind']}::{r['node']}",           # unique Algorithm_Instance id
            "version": card.get("version", 1),
            "type": ALG_TYPE_ID,                          # instance of the one LULC Algorithm_Type
            "role": f"{r['kind']}::{r['node']}",          # our readable detail (kind + node)
            "assets": {"code": STACD_REF, "artifact": loc, "card": r["card"]},
        })
    # the base map is an algorithm instance too — the pooled/base model under root
    base = catalogue.get_card("mc_root_v1") or {}
    insts.insert(0, {"id": "base::root", "version": base.get("version", 1), "type": ALG_TYPE_ID,
                     "role": "base::root",
                     "assets": {"code": STACD_REF,
                                "artifact": (base.get("artifact") or {}).get("path")
                                            or infer.active_base().get("model_path"),
                                "card": "mc_root_v1"}})
    return insts


def _input_datasets(resolvers):
    """The Dataset_Types feeding the LULC algorithm: the Alpha Earth inference source + every
    training dataset any live model consumed (deduped)."""
    dsets = {AE_DATASET}
    for r in resolvers:
        card = catalogue.get_card(r["card"]) or {}
        for ds in (card.get("training") or {}).get("datasets", []):
            dsets.add(ds)
    return sorted(dsets)


def build_stack_item(bbox, year, base_scheme=None, archive=False):
    """The stack-spec: a STAC Item / Dataset_Instance describing the LULC raster over `bbox`.

    Assets point at our own producers (the GeoTIFF + tile endpoints) so the item is actionable
    without us pre-running a slow EE export just to describe it. `properties.classes` is the code
    legend a consumer needs to read the raster's integer bands."""
    w, s, e, n = bbox
    colors = infer.load_colors()
    base_scheme = base_scheme or infer.active_base().get("scheme", "indiasat")
    geom = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    q = f"west={w}&south={s}&east={e}&north={n}"
    return {
        "stac_version": STAC_VERSION,
        "stac_extensions": [STACD_REF],
        "type": "Feature",
        "id": f"lulc_{w:.4f}_{s:.4f}_{e:.4f}_{n:.4f}_{year}",
        "bbox": [w, s, e, n],
        "geometry": geom,
        "properties": {
            "datetime": f"{year}-01-01T00:00:00Z",
            "title": f"Core Stack LULC {year}",
            "description": "10 m land-use / land-cover, Alpha Earth linear models composited over a "
                           "user-grown class hierarchy (with any rule splits + merges).",
            "base_scheme": base_scheme,
            # #14 wk10: a user-set archive/sharable signal. Most runs are test runs; only the ones
            # flagged here are meant to be retained. The data-management service would use this to
            # clean up unflagged (test) STAC items later — sir's "checkbox to archive". Emit-only for
            # now; the retention/cleanup itself is deferred to the deployment week.
            "archive": bool(archive),
            "classes": _leaf_legend(colors),
        },
        "assets": {
            "geotiff": {"href": f"/api/classify.tif?{q}&year={year}", "type": "image/tiff; application=geotiff",
                        "roles": ["data"], "title": "Class-code raster (10 m)"},
            "tiles": {"href": f"/api/classify?{q}&year={year}", "type": "application/json",
                      "roles": ["visual"], "title": "XYZ tile endpoint"},
        },
        "links": [],
    }


def build_stacd(bbox, year, since=0, archive=False):
    """The full STACD record for this output: the DAG, its Dataset/Algorithm types + instances,
    and the output Dataset_Instance whose `alg_inputs` embeds our hierarchy scheme (the input set).

    `since` scopes the embedded op-log to the current session (same anchor the export uses).
    `archive` carries the retain-vs-test signal onto the output item (#14)."""
    resolvers = _node_resolvers()
    input_dsets = _input_datasets(resolvers)
    stack = build_stack_item(bbox, year, archive=archive)
    tree = hierarchy.load()

    # the input set: exactly what the export ships — tree + the ordered ops + artifact pointers.
    classifier_refs = {cls: {"artifact": f"data/refine/{n['classifier']}.joblib",
                             "card": f"mc_{n['classifier']}_v1"}
                       for cls, n in tree.items() if n.get("classifier")}
    input_set = {"hierarchy": tree,
                 "op_log": [op for op in oplog.load() if op.get("seq", 0) > since],
                 "classifier_refs": classifier_refs}

    dataset_types = ([{"id": AE_DATASET, "name": "Alpha Earth (annual embedding)"}]
                     + [{"id": d, "name": (catalogue.get_card(d) or {}).get("name", d)}
                        for d in input_dsets if d != AE_DATASET]
                     + [{"id": "CoreStack_LULC_Raster", "name": "LULC raster @ 10 m"}])

    algorithm_type = {
        "id": "CoreStack_LULC", "name": "Core Stack LULC classification",
        "params": ["region", "year", "base_scheme", "hierarchy"],
        "input_datasets": input_dsets,
        "outputs": ["CoreStack_LULC_Raster"],
    }

    dataset_instance = {                                # the output, STACD-extended (extends Item)
        **stack,
        "version": 1,
        # STAC Item `type` stays "Feature" (from **stack) for validity; `dataset_type` carries the
        # Dataset_Type ref the paper overloads onto `type` (see week10/notes/stacd_audit.md).
        "dataset_type": "CoreStack_LULC_Raster",
        "params": {"region": list(bbox), "year": year,
                   "base_scheme": infer.active_base().get("scheme", "indiasat")},
        "alg_name": "base::root",                      # the producing Algorithm_Instance id (root LULC)
        "alg_inputs": {
            "params": {"region": list(bbox), "year": year},
            "input_datasets": input_dsets,
            "hierarchy": input_set,                    # <- "the input set used to produce this"
        },
    }

    return {
        "dag": {
            "id": "corestack_lulc_workflow", "name": "Core Stack LULC", "version": "1.0",
            "description": "Alpha Earth -> per-node linear/rule splits -> merges -> LULC raster.",
            "params": ["region", "year", "base_scheme", "hierarchy"],
            "alg_type_nodes": ["CoreStack_LULC"],
            "dataset_type_nodes": [d["id"] for d in dataset_types],
        },
        "dataset_types": dataset_types,
        "algorithm_types": [algorithm_type],
        "algorithm_instances": _algorithm_instances(resolvers),
        "dataset_instances": [dataset_instance],
    }


if __name__ == "__main__":
    # offline: build a stacd record for the IIT box and sanity-check its shape (no EE).
    box = (77.165, 28.520, 77.205, 28.560)
    item = build_stack_item(box, 2024)
    doc = build_stacd(box, 2024)
    assert item["type"] == "Feature" and item["properties"]["classes"]
    assert doc["dag"]["id"] and doc["algorithm_instances"]
    assert all(a["id"] and a["type"] == "CoreStack_LULC" for a in doc["algorithm_instances"])
    assert doc["dataset_instances"][0]["alg_name"] in {a["id"] for a in doc["algorithm_instances"]}
    assert doc["dataset_instances"][0]["alg_inputs"]["hierarchy"]["hierarchy"]
    print("stack classes:", [c["class"] for c in item["properties"]["classes"]])
    print("algorithm instances:", [a["id"] for a in doc["algorithm_instances"]])
    print("input datasets:", doc["algorithm_types"][0]["input_datasets"])
    print("stacd.py smoke test OK")
