"""STACD provenance for a classified LULC output (#4).

Per the STACD paper (Laud et al., PROPL'25 — STAC extended with DAGs, from this same CoRE-stack
lab), every geospatial output should be self-describing: not just *what* it is (a STAC Item) but
*how* it was produced — the algorithms, their versions, and the input datasets/params. STAC's
`derived_from` is too shallow for our multi-model hierarchy, so we emit the STACD classes:

  - **stack-spec**  -> a STAC Item / `Dataset_Instance` for the LULC raster (bbox, geometry,
    assets, class legend).
  - **stacd spec**  -> the DAG + `Dataset_Type`/`Algorithm_Type` nodes + `Algorithm_Instance`s
    (each live model/rule/merge with where its artifact lives) + the output `Dataset_Instance`
    whose `alg_inputs.input_set` embeds our class scheme — the tree, the effective op *sequence*,
    and the classifier refs — literally "the input set used to produce this", as sir framed it.

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

STAC_VERSION = "1.1.0"               # match the lab's items (Susmit's tree-crown STAC is 1.1.0) — #15
STACD_REF = "https://github.com/SaharshLaud/STACD-Airflow"
COLLECTION = "corestack_lulc_runs"   # our STAC collection id (the run parent), mirrors their tree_crown_runs
AE_DATASET = "ds_alphaearth_annual_v1"
ALG_TYPE_ID = "CoreStack_LULC"      # the one Algorithm_Type every per-node model is an instance of


def _leaf_legend(colors):
    """The classes that survive to the raster (base -> splits/rules -> merges), as a code->name->
    colour legend. Pure joblib/tree read — no EE — so it mirrors what a classify would paint."""
    model = infer.load_model()
    refs = infer.load_refinements()
    leaves = infer._leaf_classes(model, refs)
    s2t = merges.source_to_target()
    # the model's colour map only covers its own leaf classes; intermediate tree classes (e.g.
    # greenery) live on the hierarchy node, so fall back there before the grey default.
    tree_colors = {c: n.get("color") for c, n in hierarchy.load().items() if n.get("color")}
    display = []
    for c in leaves:                       # fold merge sources into their target, in order
        nc = s2t.get(c, c)
        if nc == "other":                  # junk catch-all, dropped from the base model — keep it out
            continue                       # of a legend we hand to another lab
        if nc not in display:
            display.append(nc)
    return [{"code": i, "class": c, "color": colors.get(c) or tree_colors.get(c) or "#999999"}
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


def _effective_ops(ops):
    """Trim the raw op-log down to the *sequence that actually produced the current output* (#14).

    The full log is an audit trail — it keeps every click, including dead ends (a `reset` reseeds the
    tree from scratch, a `merge_remove` undoes an earlier merge). STACD wants the input set, not the
    history, so we:
      - drop everything up to and including the last `reset` (nothing before it survives into the tree);
      - drop `merge_remove` ops and any `merge` whose target isn't a live merge anymore.
    The current active merges (`merges.load`) are the ground truth for what stuck."""
    last_reset = max((i for i, o in enumerate(ops) if o.get("op") == "reset"), default=-1)
    seq = ops[last_reset + 1:]
    active = {r["target"] for r in merges.load()}
    out = []
    for o in seq:
        op = o.get("op")
        if op == "merge_remove":
            continue                                    # an undo, not part of the forward recipe
        if op == "merge" and o.get("args", {}).get("target") not in active:
            continue                                    # this merge was later removed
        out.append(o)
    return out


def build_stack_item(bbox, year, base_scheme=None, archive=False, base_url="", asset_id=None):
    """The stack-spec: a STAC Item / Dataset_Instance describing the LULC raster over `bbox`.

    Assets point at our own producers (the GeoTIFF + tile endpoints) so the item is actionable
    without us pre-running a slow EE export just to describe it. `properties.classes` is the code
    legend a consumer needs to read the raster's integer bands. `base_url` (if set) is prepended to the
    relative '/api/...' hrefs so a STAC browser can resolve them; `asset_id` adds the produced GEE asset."""
    w, s, e, n = bbox
    colors = infer.load_colors()
    base_scheme = base_scheme or infer.active_base().get("scheme", "indiasat")
    geom = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    q = f"west={w}&south={s}&east={e}&north={n}"
    item_id = f"lulc_{w:.4f}_{s:.4f}_{e:.4f}_{n:.4f}_{year}"
    dt = f"{year}-01-01T00:00:00Z"
    _b = base_url.rstrip("/")
    def _abs(href):                                    # make our '/api/...' hrefs absolute if a base is set
        return f"{_b}{href}" if _b and href.startswith("/") else href
    return {
        "stac_version": STAC_VERSION,
        "stac_extensions": [STACD_REF],
        "type": "Feature",
        "id": item_id,
        "collection": COLLECTION,                          # #15: their items carry a collection; ours now too
        "bbox": [w, s, e, n],
        "geometry": geom,
        "properties": {
            # a temporal *range* alongside the point datetime, matching the lab's start/end fields (#15)
            "datetime": dt,
            "start_datetime": dt,
            "end_datetime": f"{year}-12-31T23:59:59Z",
            "title": f"Core Stack LULC {year}",
            "description": "10 m land-use / land-cover, Alpha Earth linear models composited over a "
                           "user-grown class hierarchy (with any rule splits + merges).",
            "keywords": ["lulc", "land-cover", "alpha-earth", "india", "10m"],
            "base_scheme": base_scheme,
            # our run configuration, the analogue of their `input_parameters` (#15)
            "input_parameters": {"region": [w, s, e, n], "year": year, "base_scheme": base_scheme},
            "min_longitude": w, "min_latitude": s, "max_longitude": e, "max_latitude": n,
            "center_longitude": (w + e) / 2, "center_latitude": (s + n) / 2,
            # #14 wk10: a user-set archive/sharable signal. Most runs are test runs; only the ones
            # flagged here are meant to be retained. The data-management service would use this to
            # clean up unflagged (test) STAC items later — sir's "checkbox to archive". Emit-only for
            # now; the retention/cleanup itself is deferred to the deployment week.
            "archive": bool(archive),
            "asset_id": asset_id,
            "classes": _leaf_legend(colors),
        },
        "assets": {
            **({"gee_asset": {"href": f"https://code.earthengine.google.com/?asset={asset_id}",
                             "type": "application/x-ee-image", "roles": ["data"],
                             "title": "Exported GEE asset"}} if asset_id else {}),
            "geotiff": {"href": _abs(f"/api/classify.tif?{q}&year={year}"), "type": "image/tiff; application=geotiff",
                        "roles": ["data"], "title": "Class-code raster (10 m)"},
            "tiles": {"href": _abs(f"/api/classify?{q}&year={year}"), "type": "application/json",
                      "roles": ["visual"], "title": "XYZ tile endpoint"},
        },
        # real STAC catalog links (self / root / collection), matching their item — was an empty list (#15)
        "links": [
            {"rel": "self", "href": _abs(f"/api/stacd?{q}&year={year}"), "type": "application/json"},
            {"rel": "root", "href": _abs("/catalog.json"), "type": "application/json",
             "title": "Core Stack LULC catalog"},
            {"rel": "collection", "href": _abs("/collection.json"), "type": "application/json", "title": COLLECTION},
            {"rel": "parent", "href": _abs("/collection.json"), "type": "application/json", "title": COLLECTION},
        ],
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

    # the input set: the tree + the effective op *sequence* (not the raw click history, #14) + artifact
    # pointers. `since` scopes to the current session first; `_effective_ops` then strips dead ends.
    classifier_refs = {cls: {"artifact": f"data/refine/{n['classifier']}.joblib",
                             "card": f"mc_{n['classifier']}_v1"}
                       for cls, n in tree.items() if n.get("classifier")}
    session_ops = [op for op in oplog.load() if op.get("seq", 0) > since]
    input_set = {"hierarchy": tree,
                 "op_sequence": _effective_ops(session_ops),
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
            "input_set": input_set,                    # <- "the input set used to produce this"
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
    assert doc["dataset_instances"][0]["alg_inputs"]["input_set"]["hierarchy"]
    assert "op_sequence" in doc["dataset_instances"][0]["alg_inputs"]["input_set"]
    print("stack classes:", [c["class"] for c in item["properties"]["classes"]])
    print("algorithm instances:", [a["id"] for a in doc["algorithm_instances"]])
    print("input datasets:", doc["algorithm_types"][0]["input_datasets"])
    print("stacd.py smoke test OK")
