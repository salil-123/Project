# #4 — STACD provenance mapping

Source paper: **STACD — STAC Extension with DAGs** (Laud, Joshi, Mangla, Jindal, Seth; PROPL'25),
from this same CoRE-stack lab. It extends STAC (which only has a shallow `derived_from`) with five
classes so an output records the *algorithm that made it*, its version, and its inputs/params.
Reference impl (YAML on Airflow): https://github.com/SaharshLaud/STACD-Airflow. We emit **JSON**
(STAC itself is JSON, and our card DB is JSON); the shapes are otherwise identical.

## What we emit (`src/stacd.py`, `GET /api/stacd`)

For a classified bbox we return `{stack, stacd}`:
- **stack** — a STAC **Item** for the LULC raster (`build_stack_item`): `bbox`, `geometry`,
  `properties.datetime` (the year), `properties.classes` (the code→name→colour legend), and
  `assets` pointing at our own producers (`/api/classify.tif`, `/api/classify`).
- **stacd** — the DAG + type/instance records (`build_stacd`).

## Our objects ↔ STACD classes

| STACD class | We build it from |
|-------------|------------------|
| **Dataset_Instance** (extends STAC Item) | the output raster item + STACD fields (`version`, `dataset_type`, `params`, `alg_name`, `alg_inputs`) |
| **Dataset_Type** | Alpha Earth inference card (`ds_alphaearth_annual_v1`), each training dataset card (`ds_*`) any live model used, and the output `CoreStack_LULC_Raster` |
| **Algorithm_Type** | one `CoreStack_LULC` node — params `region, year, base_scheme, hierarchy`; `input_datasets` = the datasets above; output = the LULC raster |
| **Algorithm_Instance** | one per live resolver: the base model (`mc_root_v1`), each per-node split (`mc_<node>_v1`), each **rule split** (`mc_<node>_rule_v1`, #12), each **merge** (`mc_merge_<t>_v1`, #9). `assets.code`/`artifact` = the zoo card's published/local path |
| **DAG** | `corestack_lulc_workflow` — its `alg_type_nodes` / `dataset_type_nodes` list the above |

## "The input set used to produce this"

Sir's framing: *the JSON we produce is a property inside STACD saying this is the input set used to
produce the output.* We put exactly that at `stacd.dataset_instances[0].alg_inputs.hierarchy` — the
**same envelope the project export ships**: `{hierarchy, op_log, classifier_refs}` (the class tree,
the ordered ops that built it, and each node's artifact/card pointer). So the provenance record
carries the full recipe, and `session`-scoping (`since=`) keeps it to the current run's ops.

## Fidelity + open items

- We faithfully implement the paper's five classes and the "record the producing algorithm + its
  inputs" intent. Because both card schemas are `additionalProperties: true`, a `rule`/`merge`/`stacd`
  key rides along without a schema break.
- **Not** implemented (out of scope this phase, and the paper frames them as the Airflow runtime,
  not the metadata): the selective-recomputation primitives (`update_alg`, `update_dataset`,
  `resume_exec`) and the SQLite instance store. Our emitter is the *metadata* half; wiring it to an
  Airflow scheduler would be the next step if we adopt the runtime.
- First-cut to reconcile with the authors (same lab): confirm the exact `Algorithm_Instance.type`
  naming and whether vectorization outputs (their `%-area` products) should be modelled as
  downstream algorithm nodes when we add area stats.
