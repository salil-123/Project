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
airflow/dags/        template Airflow DAG that drives the app's API (optional batch/STACD runs)
Dockerfile           the serving image  ·  docker-compose*.yml  ·  .dockerignore
master_document.md   the full week-by-week build narrative (deep-dive)
```

## Deploying into STACD / CoreStack
See `deploy/DEPLOYMENT.md` (Docker/nginx/Airflow + EE auth) and `deploy/stacd/` (the draft
DAG / algorithm / dataset onboarding YAMLs + submission notes).
</content>
