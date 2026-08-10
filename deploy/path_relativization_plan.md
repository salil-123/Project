# Deployment prep — relativize paths + upload manifest

Goal: the app must run identically no matter what the current working directory is, so it can be
driven by Docker / Airflow / a service manager (gunicorn under systemd) / nginx on sir's
workstation. Today it only works because we happen to launch it from the repo root.

## The actual problem (narrow)
Most of the code is already CWD-independent — it anchors to a repo root computed from `__file__`
(`backend._ROOT`, `catalogue.ROOT`, `aoi`, `ee_rf`, `sentinel`, `sampling`, `stacd`, `validate_ops`).
The fragile bit is a handful of modules that define bare `"data/..."` strings and open/load them
**directly**, which resolves against the current working directory:

| Module | Constant(s) | Used for |
|--------|-------------|----------|
| `hierarchy.py` | `HIERARCHY_PATH` | open/save the class tree |
| `examples.py` | `EXAMPLES_DIR` | per-node example geojson |
| `oplog.py` | `OPLOG_PATH` | op log |
| `merges.py` | `MERGE_PATH` | merge rules |
| `contributions.py` | `CONTRIB_PATH` | contribution store |
| `infer.py` | `MODEL_PATH`, `SOFTVOTE_PATH`, `REFINE_DIR`, `ACTIVE_BASE_PATH`, `WATER_FORTNIGHT_PATH` | model + refinement loads |
| `refine.py` | `REFINE_DIR`, `WC_CSV`, `FULL_CSV`, `BASE_MODEL_PATH`, `WORLDCOVER_BASE_PATH` | train/load |
| offline: `train_base.py`, `eval_base.py`, `temporal_eval.py` | CSV/model paths | run-from-root scripts |

**Leave alone** (relative *on purpose* — stored in JSON cards / provenance and re-joined to `ROOT`
at read time, so they must stay portable): all `card.artifact.path` / `definition.path` strings in
`catalogue.py`, the refs in `backend.py:163`, and the artifact refs in `stacd.py`.

## The fix (one anchor, env-overridable)
Add to `config.py`:
- `PROJECT_ROOT` — repo root from `__file__`, overridable by `CORESTACK_ROOT`.
- `DATA_DIR` — `PROJECT_ROOT/data`, overridable by `CORESTACK_DATA_DIR` (so Docker can mount the
  writable data as a volume anywhere).
- `project_path(rel)` — join a repo-relative path to the right anchor; `data/...` honors `DATA_DIR`,
  everything else anchors to `PROJECT_ROOT`; absolute inputs pass through.

Then each fragile module resolves its constant through `config.project_path(...)`. The dependency-light
modules (hierarchy/examples/oplog/merges/contributions) get the standard 2-line `sys.path` insert +
`import config` already used across the codebase, so their `python src/<mod>.py` smoke tests still work.

`infer.load_model` / active-base read also resolves through `project_path`, so a *relative* model path
stored in `active_base.json` still loads from any CWD.

## Checklist
- [x] `config.py` — PROJECT_ROOT / DATA_DIR / project_path()
- [x] hierarchy.py, examples.py, oplog.py, merges.py, contributions.py
- [x] infer.py (constants + load_model resolve)
- [x] refine.py
- [x] train_base.py, eval_base.py, temporal_eval.py (offline, for completeness)
- [x] Verify: module smoke tests + boot backend from a *different* CWD; data files byte-identical

## Upload manifest — see `deploy/upload_manifest.md`
</content>
</invoke>
