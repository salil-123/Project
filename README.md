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
Image: `docker pull salil2003/corestack-lulc:latest`. Local dev without Docker:
```bash
pip install -r requirements.txt
uvicorn backend:app --reload --app-dir src      # http://127.0.0.1:8000/
```
Earth Engine config goes in `.env` (see `deploy/.env.example`); headless servers use a service-account key.

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
├─ rules.py          interpretable index-based splits (NDVI/NDWI/…) that ride the tile map
├─ ee_rf.py          IndiaSAT EE-native RandomForest models (tree/crop, farm/shrub)
├─ sentinel.py       raw Sentinel-1/2 per-fortnight water model
├─ stacd.py          STACD provenance emitter (STAC 1.1.0 Item + DAG)
├─ aoi.py            bounding-box guardrails
└─ static/           the Leaflet web UI (index.html, app.js, style.css)

config.py            central config + Earth Engine init + path anchors (runs from any CWD)
schema/              JSON schemas for the zoo's dataset/model cards
scripts/             offline data-prep + training scripts (GEDI biomass, acacia, water, …)
data/                runtime state (hierarchy, op-log), trained .joblib models, zoo cards, examples
deploy/              Dockerize + deployment: requirements, .env.example, build/push scripts,
                     DEPLOYMENT.md, and stacd/ (onboarding YAMLs for the STACD framework)
airflow/dags/        the Airflow DAG the backend triggers (see deploy/AIRFLOW_API.md)
Dockerfile           the serving image  ·  docker-compose*.yml  ·  .dockerignore
master_document.md   the full week-by-week build narrative (deep-dive)
```

## Deploying
Full step-by-step guide: **[`deploy/DEPLOY_GUIDE.md`](deploy/DEPLOY_GUIDE.md)** (prereqs → run → Earth
Engine auth → verify → Airflow). Copy **[`deploy/.env.example`](deploy/.env.example)** → `.env` and fill
it in — §4/§5 explain every variable. The image is **dependencies-only**: the code is bind-mounted, so
updating the app is just `git pull` + restart, no rebuild. For STACD onboarding see `deploy/stacd/` (the
DAG / algorithm / dataset YAMLs).

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

Full env + API reference (proxy API, raw Airflow API, CORS notes): **[`deploy/AIRFLOW_API.md`](deploy/AIRFLOW_API.md)**.
</content>
