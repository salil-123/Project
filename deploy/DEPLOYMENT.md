# Deployment guide — Core Stack LULC

How this project deploys on sir's workstation (Docker → optional nginx/Airflow), and how it maps to
Susmit's plan and the `drone_docker` reference structure.

## Susmit's plan → status
| # | Advice | Status |
|---|--------|--------|
| 1 | Make all paths relative | **Done.** Anchored to the project root via `config.project_path` (env-overridable `CORESTACK_ROOT`/`CORESTACK_DATA_DIR`); runs from any CWD. Frontend uses relative `/api/...`; STACD emits relative hrefs — nothing points at `localhost`. |
| 2 | Model weights → Drive | **Not needed right now.** Every deployed LULC model is a *linear* `.joblib` (largest tracked = **36 KB**; they replay as EE band math), so none approach GitHub's 100 MB limit — they ship in git + the image. The only >100 MB model (biomass RF, 528 MB) was decoupled in wk11 and is gitignored. The Drive hook is ready for a large *future* model: upload it, register its Drive file-id in `deploy/fetch_models.sh`, and run it on a fresh box. |
| 3 | Reset path from localhost | **Done.** No hardcoded host anywhere in the frontend or STACD output (all relative). Behind nginx at a sub-path, see the nginx note below. |
| 4 | Airflow for heavy compute | Optional. Our classify path is server-side Earth Engine (light), so Airflow isn't required to run. Scaffold + hook in `airflow/dags/` for when a batch/STACD pipeline is wanted. |
| 5 | Dockerise → push to hub.docker.com, pull from there | **Done.** Image published: `salil2003/corestack-lulc:latest`. Pull-and-run with `docker-compose.hub.yml`. |

Second list: **(1) dockerise** ✓ · **(2) GitHub** ✓ (`origin/week10-lulc-models`) · **(3) nginx path/name
fixes** — see below.

## Structure vs the `drone_docker` reference
| drone_docker | ours | note |
|--------------|------|------|
| `Dockerfile` + `Dockerfile.frontend` (two images) | single `Dockerfile` | FastAPI serves the API **and** the static Leaflet UI from one image — no separate frontend container needed. |
| `docker-compose.hub.yml` (pull) / `docker-compose.yml` (build) | same two files | `.hub.yml` pulls the published image; the plain one builds locally. |
| `.env.example` | `deploy/.env.example` | EE + zoo + AOI caps + (build-only) Docker Hub creds. |
| `frontend/config.js` with `API_BASE` | not needed | same-origin relative `/api/...`, so there's no base URL to reset. |
| `models/*.pth` bind-mounted | code + `data/` bind-mounted | image is deps-only; the whole checkout is mounted at `/app` (same pattern). |
| `airflow/dags/*` | `airflow/dags/corestack_lulc_dag.py` | example DAG that drives our API (template — set the base URL). |
| `publish.sh` | `deploy/build_and_push.{sh,ps1}` | build + push using creds from `.env`. |

## Run it on the workstation (deps image + mounted code)
The image is **dependencies-only**; the code comes from this git checkout, bind-mounted at `/app`. So
updates are `git pull` + restart, never an image rebuild. (The compose files do the mount for you.)
```bash
git clone https://github.com/salil-123/Project.git && cd Project
cp deploy/.env.example .env         # fill EE_PROJECT / EE_ASSET_ROOT / STAC_ASSET_BASE (+ EE key if headless)
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
curl http://localhost:8000/api/health      # -> {"ok": true}
# update later:  git pull && docker compose -f docker-compose.hub.yml restart
```

## Build + push a new image (dev machine)
```bash
bash deploy/build_and_push.sh        # or: powershell -File deploy\build_and_push.ps1
# reads docker_username / docker_pat from .env, builds, pushes salil2003/corestack-lulc:latest
```

## Earth Engine auth on a headless server
The app calls `ee.Initialize(project=...)`. Interactive `earthengine authenticate` won't work in a
container, so use a **service-account key**: mount it read-only (see the commented volume in the compose
files), set `GOOGLE_APPLICATION_CREDENTIALS=/app/ee-key.json`, and have `config.ee_init()` init with it.

## nginx (Susmit's point 3 — "you'll get a path / name / variable to fix")
Simplest and recommended: proxy the app at the **root** of a host/subdomain so the frontend's relative
`/api/...` calls resolve unchanged:
```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```
If you must mount it under a **sub-path** (e.g. `/lulc/`), the relative `/api/...` calls would miss —
either rewrite in nginx (`location /lulc/ { proxy_pass http://127.0.0.1:8000/; }` and strip the prefix)
or introduce an `API_BASE` in the frontend. Root-mount avoids this entirely.

## Airflow (point 4 — only if heavy/batch compute is added)
`airflow/dags/corestack_lulc_dag.py` is a template DAG that calls this app's REST API (classify → STACD
emit) over a configurable base URL, mirroring drone_docker's `DRONE_API_BASE` callback. Point it at the
running container (`CORESTACK_API_BASE=http://<host>:8000`) and enable it in Airflow when needed; the app
otherwise runs everything in-process on request.

## What's in the image vs mounted
- **In the image (baked):** only the Python dependencies (the serving stack). Rebuild the image *only*
  when `deploy/requirements-docker.txt` changes.
- **Mounted from the host checkout at `/app`:** all the code (`src/`, `config.py`, `schema/`) + `data/`
  (models, hierarchy, examples). So a code change is `git pull` + `docker restart` — no rebuild.
- **Supplied at runtime, never in git/image:** `.env` (config), the EE service-account key (mounted
  read-only). Runtime writes land back in the mounted `data/` on the host.
</content>
