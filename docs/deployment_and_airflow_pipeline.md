# Core Stack LULC — Dockerisation & Airflow Integration (project-specific)

How this project is packaged (code vs data), how the backend triggers and polls Airflow, how the
Airflow REST API is invoked, and the exact end-to-end pipeline from a click in the UI to a raster
exported by the DAG. Written so another team can copy the same pattern for their own algorithm.

Concrete coordinates for this project:
- Repo: `github.com/salil-123/Project` · image: `salil2003/corestack-lulc:latest` · port `8000`
- Backend: FastAPI in `src/backend.py` (served by `uvicorn`), frontend in `src/static/`
- Airflow DAG id: `corestack_lulc` · backend↔Airflow glue: `src/airflow_client.py`
- The one endpoint the DAG calls back into: `POST /api/export-asset`

---

## 1. Dockerisation — how code and data are kept separate from the image

The single most important decision: **the Docker image carries dependencies only. It contains no
application code and no data.** Code and data are **bind-mounted from the host checkout at run time.**

### The three layers
| Layer | Where it lives | How it gets there |
|-------|----------------|-------------------|
| **Dependencies** | the image `salil2003/corestack-lulc:latest` | `docker pull` (built from `deploy/requirements-docker.txt`) |
| **Code** | `src/`, `config.py` on the host checkout | `git clone` / `git pull`, mounted at `/app` |
| **Data** | `data/` on the host checkout (models `.joblib`, `hierarchy.json`, op-log, examples) | ships in the repo + written back at runtime, mounted at `/app/data` |

### The Dockerfile (`Dockerfile`) — deps only
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY deploy/requirements-docker.txt /tmp/requirements.txt      # <-- the ONLY thing baked in
RUN pip install --no-cache-dir -r /tmp/requirements.txt
EXPOSE 8000
CMD ["uvicorn", "backend:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
```
Note `--host 0.0.0.0` (reachable from other machines/containers, not just localhost) and `--app-dir src`
(so `backend:app` resolves to `src/backend.py`). With nothing mounted at `/app`, the container starts but
has no code to serve — that's intentional.

### The run recipe (`docker-compose.hub.yml`) — mounts code + data
```yaml
services:
  lulc:
    image: salil2003/corestack-lulc:latest   # deps only, pulled from Docker Hub
    pull_policy: always
    ports: ["8000:8000"]
    env_file: [.env]                          # all host-specific config (see §2)
    volumes:
      - .:/app                                # <-- CODE + DATA mounted from this checkout
      # - ./deploy/ee-key.json:/app/deploy/ee-key.json:ro   # EE service-account key (see §2)
    restart: unless-stopped
```

### Why this split matters (and the update path)
- **Update the app = `git pull` + restart.** No image rebuild. Because the code is mounted, a pull
  changes the files on disk; the frontend is served fresh on the next load, the backend picks up changes
  on `docker compose … restart`.
- **Rebuild the image only when `deploy/requirements-docker.txt` changes** (a new Python dependency).
- **Path anchoring makes this work from any CWD.** `config.py` computes the repo root from its own
  location and exposes `project_path()`; `data/...` paths honour `CORESTACK_DATA_DIR` and everything else
  `CORESTACK_ROOT`, so the same code runs under `docker run`, `docker compose`, or a bare `uvicorn`.

### Deploy in four commands
```bash
git clone https://github.com/salil-123/Project.git corestack-lulc && cd corestack-lulc
cp deploy/.env.example .env          # fill it in (see §2)
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
# health: curl http://localhost:8000/api/health
```

---

## 2. Configuration & credentials (all env, nothing hardcoded)

Everything host-specific is an environment variable read in `config.py`, supplied via `.env`
(gitignored; `deploy/.env.example` is the committed template). Nothing host-specific lives in code.

The two groups that matter for this doc:

**Earth Engine (the external compute service).** The backend classifies with Earth Engine, so it needs
EE credentials + a project/folder to write outputs to:
```
EE_PROJECT=<gee-project>
EE_ASSET_ROOT=projects/<gee-project>/assets/<folder>     # export target; folder must exist + be writable
EE_SERVICE_ACCOUNT_KEY=/app/deploy/ee-key.json           # path INSIDE the container
```
The key is a **file**, so two things must both be true: the var points at a path, and the file is
actually at that path inside the container (it is, if placed at `deploy/ee-key.json` since the whole repo
is mounted at `/app`). A one-command self-check ships in the repo: `python config.py` prints
`EE init OK …` or the exact provider error. (Full EE setup with roles: `deploy/DEPLOY_GUIDE.md §5`.)

**Airflow (the orchestrator).** Empty `AIRFLOW_API_BASE` turns the DAG path off cleanly:
```
AIRFLOW_API_BASE=http://<airflow-host>:8080/api/v1   # Airflow 2.x stable REST API root
AIRFLOW_USERNAME=<user>                               # basic auth …
AIRFLOW_PASSWORD=<pass>                               # … or set AIRFLOW_TOKEN for bearer auth
AIRFLOW_DAG_ID=corestack_lulc                         # the DAG the backend triggers
CORESTACK_API_BASE=http://<this-backend-host>:8000    # where the Airflow worker reaches THIS backend
```

---

## 3. The pipeline, end to end

```
 UI "Run"                     backend (FastAPI)                 Airflow                     the DAG
    │  POST /api/dag/run ────►  airflow_client.trigger_conf ──►  create dagRun ─┐
    │  ◄── { dag_run_id } ◄──── return the run id  ◄──────────── dag_run_id     │
    │                                                                           ▼
    │  GET /api/dag/status ──►  airflow_client.run_state ──────►  run state    DAG task calls back:
    │  ◄── { state, done }                                        POST /api/export-asset
    └─ poll until success/failed                                  (classify in EE + export raster to a
                                                                   GEE asset, return STAC record)
```

Two things are worth stating plainly:
1. **The browser never talks to Airflow directly.** It calls the backend (same origin), and the backend
   talks to Airflow server-side. This avoids browser CORS (Airflow sends no `Access-Control-Allow-Origin`,
   so a cross-origin browser call is blocked even though `curl` works) and keeps the Airflow credentials
   off the page.
2. **It stays "synchronous by feel."** The UI triggers a run, gets an id, and polls until the run is
   `success`/`failed`. The DAG isn't done until the work it kicked off (`/api/export-asset`) returns
   success. Each link waits on the next.

---

## 4. How the backend triggers + polls Airflow

All the Airflow glue is one small module, `src/airflow_client.py` — a thin wrapper over two REST calls.

**Auth** (basic or bearer, chosen by which env vars are set):
```python
def _auth():
    if config.AIRFLOW_TOKEN:
        return None, {"Authorization": f"Bearer {config.AIRFLOW_TOKEN}"}
    if config.AIRFLOW_USERNAME:
        return (config.AIRFLOW_USERNAME, config.AIRFLOW_PASSWORD), {}
    return None, {}
```

**Trigger a run** — POST the run `conf`, let Airflow mint the `dag_run_id`:
```python
def trigger_conf(conf: dict) -> dict:
    auth, headers = _auth()
    url = f"{config.AIRFLOW_API_BASE}/dags/{config.AIRFLOW_DAG_ID}/dagRuns"
    r = requests.post(url, json={"conf": conf}, auth=auth, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()          # -> { "dag_run_id": "...", "state": "queued", ... }
```

**Poll a run** — GET the run, read `state`:
```python
def run_state(run_id: str) -> str | None:
    auth, headers = _auth()
    url = f"{config.AIRFLOW_API_BASE}/dags/{config.AIRFLOW_DAG_ID}/dagRuns/{run_id}"
    r = requests.get(url, auth=auth, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json().get("state")   # queued | running | success | failed
```

The backend exposes these to the frontend as a **same-origin proxy** (`src/backend.py`):
```python
@app.post("/api/dag/run")            # body: {"conf": {...}}  ->  {"dag_run_id", "state"}
async def dag_run(request: Request):
    body = await request.json()
    conf = body.get("conf", body)
    resp = airflow_client.trigger_conf(conf)
    return {"dag_run_id": resp.get("dag_run_id"), "state": resp.get("state")}

@app.get("/api/dag/status")          # ?run_id=...   ->  {"state","done","success"}
def dag_status(run_id: str):
    st = airflow_client.run_state(run_id)
    return {"dag_run_id": run_id, "state": st,
            "done": st in ("success", "failed"), "success": st == "success"}
```

And the frontend (`src/static/app.js`) triggers then polls:
```js
const r = await postJSON("/api/dag/run", { conf });        // -> dag_run_id
const runId = (await r.json()).dag_run_id;
while (true) {                                              // poll until terminal
  await sleep(3000);
  const s = await (await fetch(`/api/dag/status?run_id=${encodeURIComponent(runId)}`)).json();
  if (s.success) return s;
  if (s.state === "failed") throw new Error("DAG run failed");
}
```

### The raw Airflow REST calls (what the wrapper sends)
```bash
# trigger
curl -u <user>:<pass> -H "Content-Type: application/json" \
  -X POST "http://<airflow-host>:8080/api/v1/dags/corestack_lulc/dagRuns" \
  -d '{"conf":{"region":[77.16,28.53,77.20,28.57],"year":"2024","base_scheme":"indiasat","execution_type":"fullexec"}}'
#   -> { "dag_run_id": "manual__2026-...", "state": "queued", ... }

# poll
curl -u <user>:<pass> "http://<airflow-host>:8080/api/v1/dags/corestack_lulc/dagRuns/<dag_run_id>"
#   -> { "state": "running" | "success" | "failed", ... }
```
> Airflow's stable REST API needs `basic_auth` enabled on the webserver. If a call returns 401, add it:
> in `airflow.cfg`, `[api] auth_backends = airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session`, then restart the webserver.

---

## 5. The DAG side — calling back into the backend

The DAG's job is to run our algorithm by calling back into the backend's **`POST /api/export-asset`**,
which classifies the region in Earth Engine and **exports the raster to a GEE asset**, returning a STAC
record. In CoreStack this DAG is registered via STACD from three YAMLs in `deploy/stacd/`:

- `corestack_lulc_dag.yaml` — the workflow: params `region`, `year`, `base_scheme`.
- `corestack_lulc_algorithm_repo.yaml` — **api execution mode**, whose `url:` points at this backend:
  ```yaml
  execution_modes:
    api:
      enabled: true
      url: "http://<backend-host>:8000/api/export-asset"   # set to CORESTACK_API_BASE + /api/export-asset
  ```
- `corestack_lulc_dataset_repo.yaml` — output dataset type (no root input; the region is a param).

### The `/api/export-asset` contract (what the DAG posts and gets back)
The endpoint is written to tolerate exactly what a DAG forwards:
- params may sit at the **top level or under a `conf` key** (the DAG's run conf), and
- **extra keys the pipeline sends are ignored** (`job_id`, `state`, `district`, … — filtered by
  `_EXPORT_KEYS`), and stringified params (`year="2024"`, `region="[...]"`) are coerced.

Request:
```bash
curl -X POST http://<backend-host>:8000/api/export-asset -H "Content-Type: application/json" \
  -d '{"region":[77.16,28.53,77.20,28.57],"year":"2024","base_scheme":"indiasat"}'
```
Response (the shape the STACD generator reads):
```json
{ "status": "success",
  "asset_id": "projects/<proj>/assets/<folder>/..._2024",
  "version": "1", "hosting_platform": "GEE",
  "stac_items": [ { "type": "Feature", "stac_version": "1.1.0", "id": "lulc_...", "...": "..." } ] }
```
Async variant for long exports: call with `?wait=false` to get a `task_id` immediately, then poll
`GET /api/export-status?task_id=...` until `done`.

---

## 6. What we changed to make an existing app work with Airflow

Starting from a plain FastAPI app, these were the concrete additions (the whole integration is small and
self-contained — a template for another team):

1. **`src/airflow_client.py`** (new) — the two REST calls above, config-driven, with basic/bearer auth.
2. **`src/backend.py`** — added the same-origin proxy endpoints `POST /api/dag/run` and
   `GET /api/dag/status`, and made `POST /api/export-asset` tolerant of the DAG's conf envelope + return
   the `{status, asset_id, stac_items}` shape STACD reads.
3. **`config.py`** — added `AIRFLOW_API_BASE`, `AIRFLOW_USERNAME`/`PASSWORD`/`TOKEN`, `AIRFLOW_DAG_ID`,
   `CORESTACK_API_BASE`, all env-driven with safe empty defaults (empty base = Airflow off).
4. **`src/static/app.js`** — the "Run" action calls the proxy and polls the run id.
5. **`deploy/stacd/*.yaml`** — the STACD onboarding (DAG + algorithm-with-`url` + dataset) so CoreStack's
   Airflow can register and trigger the algorithm.
6. **Dockerfile / compose** — already deps-only + code/data mount (§1); no change needed to add Airflow,
   since the glue is just code + env.

---

## 7. Replication checklist for another team

To wire your own containerised algorithm into Airflow the same way:
1. **Package deps-only + mount code/data** (§1): image from a `requirements` file, code+data bind-mounted
   at `/app`, `--host 0.0.0.0`. Update = `git pull` + restart.
2. **Put all config in `.env`** (§2), with a committed `.env.example`. Credential *files* must be both
   referenced by a var **and** mounted into the container. Ship a one-command auth self-check.
3. **Expose one "do the work" endpoint** the DAG can POST to (our `/api/export-asset`), tolerant of a
   `conf` envelope + extra keys, returning a small JSON result (status + output id + provenance).
4. **Add the Airflow glue** (`airflow_client.py` equivalent): `trigger_conf` + `run_state` over the REST
   API, driven by env (`*_API_BASE`, auth, `*_DAG_ID`).
5. **Expose a same-origin proxy** (`/api/dag/run`, `/api/dag/status`) so the browser never calls Airflow
   directly (CORS + credential exposure).
6. **Register the DAG** (STACD YAMLs or your own DAG file) with its api `url:` pointing at your backend,
   reachable from the Airflow worker (`CORESTACK_API_BASE`, a LAN/host address, not `localhost`).
7. **Verify inside-out:** `curl /api/health` → `python config.py` (auth) → `curl /api/export-asset`
   (real work) → trigger via Airflow REST → run reaches `success`.
