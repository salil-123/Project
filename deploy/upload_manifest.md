# Upload manifest — what to ship to sir's workstation

Target: run the LULC web app (FastAPI + Leaflet + the model zoo) on Aaditeshwar sir's workstation,
driven by Docker / Airflow / nginx. Paths are now CWD-independent (see `path_relativization_plan.md`),
so the app runs from any directory as long as `data/` sits next to `src/` (or `CORESTACK_DATA_DIR`
points at it).

Rule of thumb: **ship the code + the tiny trained models + runtime JSON; regenerate the big CSVs and
never ship secrets.** The full `data/` dir is ~2.5 GB but 99% of that is biomass artifacts and CSV
caches the serving app never touches.

---

## ⚠ Before anything: secrets
`.env` currently contains a **Docker access token and username** (`docker_pat`, `docker_username`) and
the personal `ZOO_REMOTE`. **Do not upload `.env`.** It's already gitignored. Rotate that Docker PAT —
it has been sitting in the working tree. Ship `deploy/.env.example` (below) instead and have the
workstation fill in its own values.

---

## Tier 1 — code + config (REQUIRED, tiny)
| Path | Why |
|------|-----|
| `src/` (all `.py` + `src/static/`) | the app: backend, infer, hierarchy, refine, catalogue, zoo, rules, sentinel, ee_rf, stacd, aoi + the Leaflet frontend |
| `config.py` | central config + the new path anchors (`PROJECT_ROOT`/`DATA_DIR`/`project_path`) + EE init |
| `schema/` | card JSON schemas (`catalogue` validates against these at runtime) |
| `requirements.txt` | pinned deps for the venv / image |
| `README.md` | run instructions |
| `deploy/` | this manifest + the Dockerfile / compose / `.env.example` (to be added) |

## Tier 2 — runtime data the app loads on boot (REQUIRED, small)
| Path | Size | Why |
|------|------|-----|
| `data/model_pooled.joblib` | 8K | the Realistic base model — the app can't classify without it |
| `data/model_worldcover_base.joblib` | 8K | WorldCover base-scheme option |
| `data/model_softvote_reconciled.joblib` | 36K | Detailed softvote (backend path still loads it; unexposed in UI) |
| `data/refine/*.joblib` (barren, greenery, water_fortnight, water_fortnight_augmented, base_multiyear, acacia_non_acacia_multiyear) | <1M total | the trained split / water classifiers on the live tree |
| `data/hierarchy.json`, `active_base.json`, `op_log.json`, `merge_rules.json` | <25K | live scheme + session state (or ship fresh seeds and let the app reseed) |
| `data/benchmark_profile.json` | 4K | feeds `/api/estimate` (the retrain time estimate) |
| `data/examples/*.geojson` (live node files, not `archive/`) | small | the example canvas the split cards point at |
| `data/catalogue/models/*.json`, `data/catalogue/datasets/*.json`, `data/catalogue/index.json` | ~130K | the model-zoo cards. **Skip `data/catalogue/artifacts/`** (528M — a published biomass joblib; the zoo re-stages artifacts on publish) |

## Tier 3 — training tables (ONLY if on-workstation retrain / base-switch is wanted)
The serving app classifies fine without these; they're read only when a user **retrains a split, adds a
class, or switches to the WorldCover base**. Big but not secret:
| Path | Size | Enables |
|------|------|---------|
| `data/worldcover_train.csv` | 12M | WorldCover base + residual-class training |
| `data/master_alpha_full.csv` | 53M | residual sampling for ADD / base-retrain |
| `data/water_extra.csv` | 2.2M | base water augmentation |

Regenerable from Earth Engine, so an alternative is to **not** ship them and pull them on first retrain.

## Tier 4 — DO NOT upload (regenerable, huge, or dev-only)
| Path | Size | Reason |
|------|------|--------|
| `.env` | — | **secrets** (see above) |
| `.venv/`, `__pycache__/`, `*.pyc` | big | rebuilt from `requirements.txt` in the image |
| `.git/`, local editor caches | — | local tooling |
| `data/master_tessera.csv` | 139M | only the (unexposed) Tessera/Detailed path; re-downloadable |
| `data/refine/*_train.csv`, `data/refine/*_te_train.csv` | ~470M | sampling **caches** — regenerate on demand |
| `data/refine/biomass_aez8.joblib`, `data/catalogue/artifacts/` | 528M each | biomass was **decoupled from LULC in wk11**; not part of this app |
| `data/random_eval.csv`, `random_te_eval.csv`, `selected_polygons.geojson`, `raw_polygons/`, `inputs/`, `seasonal_water_ground_truth_polygons/`, `examples/archive/`, `refine/archive/` | ~30M+ | eval/prep leftovers, not loaded by the server |
| `cod892_biomass/`, `global_0.1_degree_*`, `floodMappingPipelines/` | GBs | reference repos / Tessera tiles — not this app |
| `beyond_flat_classifier_paper.pdf`, `stacd_paper.pdf`, `*.ipynb`, root `3_store_embeddings*.py`, `tessera_fast.py` | 70M+ | research/reference, not the serving app |
| `week2/ … week12/`, `docs/`, `master_document.md` | — | dev notes + slides; ship `docs/` + `master_document.md` only if you want the writeups on the box |

---

## New files to ADD under `deploy/` for the container (next step, not yet written)
- `deploy/Dockerfile` — python-slim + GDAL/geo system libs, `pip install -r requirements.txt`, copy
  `src/ config.py schema/ data/`, `EXPOSE 8000`, `CMD uvicorn backend:app --app-dir src --host 0.0.0.0`.
- `deploy/.dockerignore` — mirror Tier 4 so the huge/secret files never enter the build context.
- `deploy/.env.example` — `EE_PROJECT=`, `EE_USER_ID=`, `ZOO_REMOTE=`, optional `CORESTACK_DATA_DIR=`,
  `AOI_*` caps. **No tokens.**
- Earth Engine auth: the app calls `ee.Initialize(project=...)`. On a headless workstation use a
  **service-account key** mounted as a secret (not `earthengine authenticate`) — the one real
  deployment gap called out since wk9. Wire it in `config.ee_init()`.
- `docker-compose.yml` (optional) — the app + an nginx reverse proxy; `data/` as a mounted volume so
  the writable runtime files (hierarchy/op_log/examples) persist across container restarts.

## Airflow note
The path anchors make the modules importable from an Airflow DAG regardless of the worker's CWD. For a
retrain/STACD DAG, set `CORESTACK_ROOT` (and `CORESTACK_DATA_DIR` if data lives on a shared volume) in
the task env, then call `refine.train(...)` / `stacd.build_*` directly. The STACD emitter (`src/stacd.py`)
is the metadata half; the Airflow *runtime* wiring (selective recompute, instance store) is still open
per the wk10/wk11 notes.
</content>
