# STACD conformance audit — Core Stack LULC (#1, wk10)

**What this is:** a class-by-class check of our STACD emitter (`src/stacd.py`, endpoint
`/api/stacd`) against the STACD paper (*STAC Extension with DAGs for Geospatial Data and Algorithm
Management*, Laud, Joshi, Mangla, Jindal, Seth — PROPL '25, `stacd_paper.pdf`) and its Appendix-A
reference YAML. This is the "we did it like this — is this correct?" file to share with the authors
(Saharsh / Saurabh) and with Anunay / Susmit who generate STAC/STACD for the drone + bioacoustics
pipelines.

Reference impl the paper points to: <https://github.com/SaharshLaud/STACD-Airflow>.

## TL;DR

The emitter produces all five STACD classes (Dataset_Type, Algorithm_Type, DAG, Algorithm_Instance,
Dataset_Instance) and matches the reference YAML's flattened shape. This week we fixed the two real
deviations (Algorithm_Instance had no `id`; the output's `alg_name` pointed at an Algorithm_*Type*
instead of an *Instance*). What remains different is **intentional**: (a) one extra field —
`alg_inputs.input_set` — that embeds our whole class scheme as "the input set used to produce this",
exactly as sir framed it; and (b) we emit only the **metadata half**, not the Airflow runtime +
SQLite instance store. Open question for the authors is in the last section.

## Class-by-class

| STACD class (paper) | Paper fields | Our emission (`stacd.py`) | Status |
|---|---|---|---|
| **Dataset_Type** | id, name | `dataset_types: [{id, name}]` | ✅ match |
| **Algorithm_Type** | id, name, inputs{params, input_datasets}, outputs | `algorithm_types: [{id, name, params, input_datasets, outputs}]` — flattened | ✅ matches the reference **YAML** (Listing 3), which also flattens `params`/`input_datasets`/`outputs` to top level (the prose nests them under `inputs`) |
| **DAG** | id, name, version, description, params, alg_type_nodes, dataset_type_nodes | `dag: {id, name, version, description, params, alg_type_nodes, dataset_type_nodes}` | ✅ match |
| **Algorithm_Instance** | version, type (→Algorithm_Type), assets | `{id, version, type, role, assets}` | ✅ fixed this week — added a unique `id`; `type` now correctly references the Algorithm_Type (`CoreStack_LULC`), with our kind+node detail kept in `role`. `assets` links code (STACD repo) + the joblib + the zoo card |
| **Dataset_Instance** *(extends Item)* | inherits Item; + version, type (→Dataset_Type), params, alg_name (→Algorithm_Instance), alg_inputs{params, input_datasets} | full STAC Item + `{version, dataset_type, params, alg_name, alg_inputs{params, input_datasets, input_set}}` | ⚠️ two notes below |
| **STAC Item** (stack-spec) | stac_version, extensions, type=Feature, id, bbox, geometry, properties, assets, links, derived_from | all present; `properties.classes` = the code→name→colour legend; `assets` = our GeoTIFF + tile endpoints | ✅ match |

### The two Dataset_Instance notes

1. **`type` overload.** The paper's Dataset_Instance both *extends Item* (so `type` must be
   `"Feature"`) **and** lists `type: Dataset_Type` — the reference YAML shows `type: DEM`. That's an
   internal conflation in the spec. We resolve it by keeping STAC-valid `type: "Feature"` and putting
   the Dataset_Type reference in a sibling **`dataset_type`** field (`"CoreStack_LULC_Raster"`).
   *Question for the authors: should the Dataset_Type ref live in a renamed field like this, or do
   you intend `type` to be overloaded and STAC-validity waived?*
2. **`alg_name`** now references a real Algorithm_Instance **id** (`"base::root"`, the root LULC
   producer) instead of the Algorithm_Type id it used before. The full multi-model hierarchy that
   actually produced the raster is carried in `alg_inputs.input_set` (see below), since a single
   `alg_name` can't express a composite of per-node models.

## Intentional extensions / simplifications

- **`alg_inputs.input_set` (our addition).** Beyond the paper's `alg_inputs.{params,
  input_datasets}`, we embed the entire scheme — the hierarchy tree, the effective op *sequence*
  (`op_sequence`), and each node's classifier/artifact refs — as the literal "input set used to
  produce this output". This is the whole point for us: an LULC raster is only reproducible if you
  also ship the class tree and the sequence of split/rule/merge ops that built it. `op_sequence` is
  the trimmed recipe — the raw click log's dead ends (a `reset` that reseeds the tree, a
  `merge_remove` that undoes a merge) are dropped, so it's the sequence, not the full history.
- **`alg_inputs.input_datasets` are Dataset_Type ids**, not per-run Dataset_Instance references. At
  our scale (one AE inference source + a few training polygon sets) instance-level input tracking
  adds noise without new information; the types + the embedded scheme already pin down the run. Easy
  to promote to instance refs if the authors want strict conformance.
- **One Algorithm_Type (`CoreStack_LULC`).** Every per-node model/rule/merge is an *instance* of the
  single LULC algorithm type, distinguished by instance `id` + `role`. The paper's example has
  several algorithm types (Terrain, LULC, Vectorization) because it's a multi-stage pipeline; ours is
  one classification algorithm applied compositionally down a hierarchy.

## The acknowledged gap: metadata half only

We emit the **STACD specs** (the DAG + type/instance JSON, the stack-spec Item). We do **not** run
the paper's §4 reference architecture: the Airflow scheduler, the SQLite `algorithm_records` /
`dataset_records` / `execution_logs` tables, and the execution primitives (`full_exec`,
`update_alg`, `update_dataset`, `resume_exec`, `update_dag`) that give selective recomputation and
persisted instance history. For LULC today the outputs are produced by our FastAPI/EE path and
*described* in STACD; wiring them to the Airflow runtime is the next step if the lab adopts STACD as
the execution substrate (this matches Aaditeshwar sir's note that not every run needs archiving —
that lives in the data-management service, not the emitter).

## How to reproduce / verify

- `python src/stacd.py` — offline smoke test (asserts every Algorithm_Instance has an `id` and
  `type == "CoreStack_LULC"`, and that the output's `alg_name` resolves to one of those instance
  ids).
- `GET /api/stacd?west=..&south=..&east=..&north=..&year=2024` — the live record for a classified
  box; `dataset_instances[0].alg_inputs.input_set` carries the scheme (`{hierarchy, op_sequence,
  classifier_refs}`).
