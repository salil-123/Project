# Core Stack LULC

A web tool to paint a **land-use / land-cover map** over any part of India at **10 m**, then *grow your
own class scheme* on top of it — split a class into finer ones, add a new class, merge/relabel across
models — by drawing a few example polygons and retraining on the fly. Every trained model and dataset is
recorded as a **card** in a git-backed **model zoo**. Project home: https://core-stack.org/

## How it works (two ideas)
- **A canonical class spine** (`data/hierarchy.json`) seeded from 4 base classes — *greenery, water,
  built_up, barren* — editable at every level.
- **Embeddings as features, never raw imagery.** Each pixel is a pre-learned vector (Google **Alpha
  Earth**, 64-d, in Earth Engine, India-wide). A **linear** model on top replays *exactly as band math
  inside Earth Engine*, so a whole bounding box classifies server-side and comes back as map tiles with
  **nothing downloaded**. Non-linear models (RF) and Tessera embeddings are available for fine splits.

## Run it
```bash
# pull the published image and start it
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
curl http://localhost:8000/api/health          # -> {"ok": true}
# open http://localhost:8000/
```
Image: `docker pull salil2003/corestack-lulc:1.0.0` (pinned; `:latest` points at the same build). Local dev without Docker:
```bash
pip install -r requirements.txt
uvicorn backend:app --reload --app-dir src      # http://127.0.0.1:8000/
```
Earth Engine config goes in `.env` (see `deploy/.env.example`); headless servers use a service-account key.
Deploying on the tower: follow [`deploy/TOWER_DEPLOY.md`](deploy/TOWER_DEPLOY.md) step by step.

`/` is the front page (what the tool is, the walkthrough video, public projects, sign in); `/app` is
the tool. Google sign-in is on by default (our client id is in `config.py`); set `GOOGLE_CLIENT_ID=` empty in
`.env` to sign in by typing any name on a laptop.

## Users, projects, runs
Everything happens inside a **project**: one area, one year, one base scheme, the classes grown on
it, the example polygons, the models trained for it, and its **runs**. A user sees only their own
projects (and any someone made public, read-only, copyable). Running classification is the only thing
that draws a map; each run is kept with a frozen copy of the scheme that made it, so reopening a
project shows its last map without re-running, and a later retrain never changes an old run.

- Sign-in: Google, verified on the server (`src/auth.py`), then a signed session cookie. No session,
  no compute and no writes.
- State: users + projects in the database (`DATABASE_URL`, Postgres on the cluster; SQLite file on a
  laptop), everything else in `data/projects/<id>/` on the data mount.
- Splitting a class: use a zoo model and map its classes onto yours, or upload labelled polygons in
  the standard format (a GeoJSON with a `class` on every polygon; the app serves an example at
  `/api/upload-format/example.geojson`) and train.
- Design and reasoning: `week18/app_design.md` (kept locally, with the other week folders).

## Repository structure
```
src/                 the application (FastAPI backend + Leaflet frontend)
├─ backend.py        FastAPI app: classify, hierarchy ops, zoo, water, segment, STACD endpoints
├─ infer.py          inference — linear→EE band-math tiles, point-grid fallback, compositing
├─ hierarchy.py      the class tree (split/add/validate)
├─ refine.py         the training engine (per-node split classifiers, bake-off)
├─ examples.py       user example polygons → embedded training frames
├─ sampling.py       shared Alpha Earth / Tessera sampling
├─ catalogue.py      the model-zoo card database (+ zoo_git.py for git-backed publish)
├─ db.py / auth.py   users + projects tables; Google sign-in verified server side, session cookie
├─ projects.py       a project's folder under data/projects/, its runs, copy and zip
├─ rules.py          interpretable index-based splits (NDVI/NDWI/…) that ride the tile map
├─ ee_rf.py          IndiaSAT EE-native RandomForest models (tree/crop, farm/shrub)
├─ sentinel.py       raw Sentinel-1/2 per-fortnight water model
├─ stacd.py          STACD provenance emitter (STAC 1.1.0 Item + DAG)
├─ aoi.py            bounding-box guardrails
├─ logging_setup.py  LOG_LEVEL -> stdout + data/logs/corestack-lulc/app.log
└─ static/           the front page (landing.html) + the Leaflet tool (index.html, app.js, style.css)

config.py            central config + Earth Engine init + path anchors (runs from any CWD)
models/              trained weights, on their own mount (see models/README.md)
outputs.yaml         retention policy for everything written under data/ (public/keep/delete)
schema/              JSON schemas for the zoo's dataset/model cards
scripts/             offline data-prep + training scripts (GEDI biomass, acacia, water, …)
data/                runtime state (hierarchy, op-log), trained .joblib models, zoo cards, examples
deploy/              Dockerize + deployment: requirements, .env.example, build/push scripts,
                     DEPLOYMENT.md, and stacd/ (onboarding YAMLs for the STACD framework)
airflow/dags/        week 12 template DAG for the /api/jobs flow (see deploy/AIRFLOW_API.md)
deploy/sim/dags/     simulation only: a stand-in for the tower's STACD DAG, used by deploy/sim/
Dockerfile           the serving image  ·  docker-compose*.yml  ·  .dockerignore
master_document.md   the full week-by-week build narrative (deep-dive)
```

## Deploying
Full step-by-step guide: **[`deploy/DEPLOY_GUIDE.md`](deploy/DEPLOY_GUIDE.md)** (prereqs → run → Earth
Engine auth → verify → Airflow). Copy **[`deploy/.env.example`](deploy/.env.example)** → `.env` and fill
it in — §4/§5 explain every variable. The image is **dependencies-only**: the code is bind-mounted, so
updating the app is just `git pull` + restart, no rebuild. For STACD onboarding see `deploy/stacd/` (the
DAG / algorithm / dataset YAMLs).

## Cluster deployment (CoRE Stack tower)

Built against the [Cluster Service Checklist](https://docs.core-stack.org/server/cluster-service-checklist/);
status per item is in **[`docs/cluster_checklist.md`](docs/cluster_checklist.md)**, and the required
architecture diagram (what triggers compute, and from where) is in
**[`docs/architecture.md`](docs/architecture.md)**.

**Three mounts.** `code/` → `/app`, `models/` → `/app/models`, `data/` → `/app/data`. They default to
this checkout, so a laptop needs no setup; point them at the host's real dirs with
`CORESTACK_CODE_HOST` / `CORESTACK_MODELS_HOST` / `CORESTACK_DATA_HOST` in `.env`. Trained weights
resolve through `config.model_path()` — `models/` first, the historical `data/` location as a
fallback — so `python scripts/migrate_models.py` can move them whenever you like, with nothing
breaking before or after.

**Logging.** `LOG_LEVEL=debug|info|error` in `.env`; output goes to stdout *and*
`data/logs/corestack-lulc/app.log` (rotating, 10 MB x 5), so it survives the container:

```bash
docker compose -f docker-compose.hub.yml logs -f lulc   # stdout
tail -f data/logs/corestack-lulc/app.log                # on the host
```

`debug` adds request query strings, job params and Airflow polling. Credentials are scrubbed at every
level. **Outputs**: retention for each path under `data/` is declared in
[`outputs.yaml`](outputs.yaml) for the host data service to act on.

**Frontend API base.** The page takes its API base from `/config.js`, which the backend generates
from `API_BASE_URL`. Leave it empty (the default) and the UI uses paths relative to itself, so it
works at the domain root *and* behind a reverse-proxy subpath. Set it only to point the UI at a
different backend. Leaflet is vendored under `src/static/vendor/` rather than loaded from a CDN,
which a campus proxy may block.

**Sign-in and database (#4, #9):** see *Users, projects, runs* above; env in `deploy/.env.example`.

## Airflow DAG orchestration
The long ops (classify/export) can run through an **Airflow DAG** instead of inline. A browser can't call
Airflow directly (CORS blocks it, and the creds shouldn't live in the page), so the frontend hits a
**same-origin backend proxy** and the backend triggers + polls Airflow server-side:

```
Run → POST /api/dag/run  {conf}       backend triggers the DAG → returns dag_run_id
    → GET  /api/dag/status?run_id      backend polls Airflow state → success / failed
       (the DAG calls back into POST /api/export-asset to classify + export the raster to a GEE asset)
```

Set these in `.env` (all host-specific; leave `AIRFLOW_API_BASE` empty to turn the DAG path off — the app
still runs, `/api/dag/*` just returns 503):

| Var | What it is |
|-----|------------|
| `AIRFLOW_API_BASE` | Airflow REST API root incl. `/api/v1`, e.g. `http://<airflow-host>:8080/api/v1` |
| `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD` | Basic-auth creds (or `AIRFLOW_TOKEN` for bearer auth) |
| `AIRFLOW_DAG_ID` | DAG to trigger (default `corestack_lulc`) |
| `CORESTACK_API_BASE` | Where the Airflow worker reaches **this** backend (a LAN IP/host, not `localhost`) |

**Retraining rides the same DAG.** A retrain isn't a second DAG — it travels in the *same*
`op="export"` conf, and the backend trains before it classifies:

```jsonc
{ "retrain": { "node": "greenery", "algo": "logreg" },
  "export": false }        // false = train and stop; omit to train, then classify + export
```

So there's one DAG and one STACD algorithm registration to maintain. Training always runs inside this
container (the DAG just drives it over HTTP), so weights, hierarchy and zoo cards stay consistent.

Full env + API reference (proxy API, raw Airflow API, CORS notes): **[`deploy/AIRFLOW_API.md`](deploy/AIRFLOW_API.md)**.
</content>
