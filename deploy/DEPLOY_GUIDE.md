# Core Stack LULC — Deployment Guide

A self-contained guide to deploy the **Core Stack LULC** service and (optionally) plug it into the
**STACD / Airflow** pipeline. No prior familiarity with the codebase is assumed.

---

## 1. What you are deploying

A **FastAPI** web service that classifies land-use / land-cover (LULC) over any region of India at 10 m,
**on the fly**, using Google **Earth Engine**. The service is **stateless — it does not store the
classification, and it does not save any model** (the classifier is replayed as Earth-Engine band math
each call). It exposes:

- `GET /` — an interactive web UI (Leaflet) for painting/refining LULC; returns **live map tiles**,
  nothing is written anywhere. *(optional, for humans)*
- `POST /api/export-asset` — the pipeline endpoint. It classifies the region and, **only because STACD
  needs a persistent reference to ingest**, materializes the output **in Google Earth Engine's own asset
  store** (under `EE_ASSET_ROOT`) and returns the STAC record. The asset lives in GEE — **our backend
  keeps nothing**. *(this is what Airflow calls)*
- `GET /api/health` — liveness check.

**Packaging model (important):** the Docker image contains **only the dependencies**. The application
**code is bind-mounted from a git checkout** at run time. So:
- Deploy = clone the repo + pull the image + run (the run mounts the code).
- Update the app = `git pull` + restart the container. **No image rebuild.**
- Rebuild the image **only** if `deploy/requirements-docker.txt` (the dependency list) changes.

- **Repo:** `https://github.com/salil-123/Project.git`
- **Image:** `salil2003/corestack-lulc:latest` (public, dependencies-only, ~1.5 GB)
- **Port:** `8000`

---

## 2. Prerequisites on the deploy machine

| Need | Notes |
|------|-------|
| **Docker** (+ `docker compose`) | Linux host recommended. `docker --version` should work. |
| **git** | to clone the repo (the code is mounted from it). |
| **A Google Earth Engine project** | either **ours** (we hand you a service-account key) or **your own** (you provide EE credentials). See §5. |
| **A GEE asset location you can write to** | the exported rasters land here (see `EE_ASSET_ROOT`, §4). |
| **Network reachability** (for Airflow only) | Airflow must be able to reach this service's URL — same LAN, a reverse proxy, or an ngrok tunnel (§7). |

Outbound internet is required (Earth Engine + Docker Hub).

---

## 3. Deploy — step by step

```bash
# 1. get the code (the container mounts this)
#    Option 1 — from git:
git clone https://github.com/salil-123/Project.git corestack-lulc
cd corestack-lulc
#    Option 2 — NO GitHub: unzip the code package we hand you (same result):
#    unzip corestack-lulc-deploy.zip -d corestack-lulc && cd corestack-lulc

# 2. create the runtime config
cp deploy/.env.example .env
#    then edit .env  (see §4 for each variable)

# 3. pull the dependencies image
docker compose -f docker-compose.hub.yml pull

# 4. start it (this bind-mounts the code + data at /app)
docker compose -f docker-compose.hub.yml up -d

# 5. verify
curl http://localhost:8000/api/health          # -> {"ok": true, ...}
```

Open `http://<host>:8000/` for the web UI. The service is now up.

**To update the app later:**
```bash
git pull                                            # or: replace the folder with a new package we send
docker compose -f docker-compose.hub.yml restart    # no image rebuild
```

---

## 4. Configuration — the `.env` file

All configuration is environment variables (nothing is hardcoded). Edit `.env`:

| Variable | Required? | What it is |
|----------|-----------|------------|
| `EE_PROJECT` | yes | The Google Earth Engine / Cloud project to run in (e.g. `modern-mystery-398416`). |
| `EE_ASSET_ROOT` | yes | Where exported rasters are written, e.g. `projects/<EE_PROJECT>/assets/corestack_lulc`. Must be **writable** by the EE identity, and the folder must exist (§5). |
| `EE_SERVICE_ACCOUNT_KEY` | for headless | Path (inside the container) to the EE service-account JSON, e.g. `/app/deploy/ee-key.json`. Omit if using a mounted interactive token instead. |
| `STAC_ASSET_BASE` | recommended | Public base URL of this service, so STAC links come out absolute, e.g. `http://<host>:8000` (or the nginx/ngrok URL). A STAC browser can't open relative links. |
| `EE_USER_ID` | optional | EE user id (legacy); harmless to leave default. |
| `ZOO_REMOTE` | optional | Git remote for the model-zoo cards. Only needed if you use the "publish" feature. |
| `AOI_TILE_CAP_KM2`, `AOI_GEOTIFF_CAP_KM2`, `AOI_TESSERA_MAX_TILES` | optional | Size guardrails; defaults are fine. |
| `CORESTACK_DATA_DIR`, `CORESTACK_ROOT` | optional | Relocate the data/code roots; leave unset for the mounted `/app`. |

> `.env` also contains `docker_username` / `docker_pat` in the example — those are **build-time only**
> (for pushing a new image) and are **not needed to run**. Leave them blank on the deploy machine.

---

## 5. Earth Engine authentication (the one real setup step)

The container has no EE credentials baked in. **Recommended: use your own GEE project** (Option A). Using
our project (Option B) is possible but requires us to issue and securely hand over a key — not done yet.

### Option A — run against **your own** GEE project *(recommended)*
1. In **your** GCP project, create a service account with the **Earth Engine Resource Writer** role and
   download its JSON key. *(Quick alternative for testing: `earthengine authenticate` on the host, then
   mount `~/.config/earthengine` into the container instead of a key.)*
2. Ensure the output asset folder exists: EE Code Editor → **Assets** → create
   `projects/<your-project>/assets/corestack_lulc` (or the app auto-creates it under an existing asset root).
3. Put the key on the host at `./deploy/ee-key.json` (gitignored — never commit it), set `.env`:
   ```
   EE_PROJECT=<your-project>
   EE_ASSET_ROOT=projects/<your-project>/assets/corestack_lulc
   EE_SERVICE_ACCOUNT_KEY=/app/deploy/ee-key.json
   ```
   and uncomment the key mount in `docker-compose.hub.yml`:
   ```yaml
   - ./deploy/ee-key.json:/app/deploy/ee-key.json:ro
   ```

### Option B — run against **our** GEE project *(only if arranged with us)*
We would issue a service-account key on our project `modern-mystery-398416` so outputs land there.
**We have not shared such a key** — if you want this path, ask us and we'll create one and send it over a
**secure channel** (never committed to git, never over plain chat/email). Then use the same `.env` as
Option A but with our project/paths.

> A service-account key is an access credential — keep it private, share it only securely, and revoke/rotate
> it in GCP if it is ever exposed.

---

## 6. Verify it works end-to-end

```bash
# liveness
curl http://localhost:8000/api/health

# a real classification + export (small area; blocks ~30-60s while Earth Engine runs)
curl -X POST http://localhost:8000/api/export-asset \
  -H "Content-Type: application/json" \
  -d '{"region":[77.16,28.53,77.20,28.57],"year":2024,"base_scheme":"indiasat"}'
```
A success looks like:
```json
{ "status": "success",
  "asset_id": "projects/<EE_PROJECT>/assets/corestack_lulc/..._2024",
  "version": "1", "hosting_platform": "GEE",
  "stac_items": [ { "type": "Feature", "id": "lulc_...", "...": "..." } ] }
```
If you get `status: success` and the asset appears in your GEE project, the deployment is good.

---

## 7. Make it reachable by Airflow

Airflow (the STACD pipeline) calls this service over HTTP, so it needs a URL it can reach:

- **Same machine / LAN:** `http://<host-ip>:8000`. The service binds `0.0.0.0`, so it's reachable on the
  network; open port `8000` in the host firewall.
- **Public / across networks:** put it behind **nginx** (reverse proxy at a domain) or use an **ngrok**
  tunnel (`ngrok http 8000` → a public `https://…` URL). This is the pattern the drone/bioacoustic
  backends use.

Whatever the reachable URL is, it goes into the STACD algorithm config (§8) and into `STAC_ASSET_BASE`.

**nginx (root path) example:**
```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_read_timeout 600s;   # exports can take a while (synchronous call)
}
```

---

## 8. Register it in STACD / Airflow (optional — pipeline integration)

The three onboarding YAMLs are in `deploy/stacd/`:
- `corestack_lulc_dag.yaml` — the workflow (params `region`, `year`, `base_scheme`).
- `corestack_lulc_algorithm_repo.yaml` — **set the `url:` to this service's reachable URL** (from §7),
  e.g. `http://<host>:8000/api/export-asset`.
- `corestack_lulc_dataset_repo.yaml` — empty (no root dataset; the region is a parameter).

Register them via the STACD Airflow plugin (**Initialize Workflow** → upload the three YAMLs). It appears
as the algorithm **`CoreStack_LULC`** in the `corestack` group. Trigger a run with:
```json
{ "region": [77.16, 28.53, 77.20, 28.57], "year": 2024, "base_scheme": "indiasat" }
```
The DAG calls `/api/export-asset`, our service produces the GEE asset and returns `{status, asset_id,
stac_items}`, and Airflow records it in the STACD catalog.

---

## 9. API reference (what the service exposes)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | liveness → `{"ok": true}` |
| POST/GET | `/api/export-asset` | classify a region, export a GEE asset, return `{status, asset_id, version, hosting_platform, stac_items}` |
| GET | `/api/export-status?task_id=…` | poll an async export (`wait=false`) — `{state, done, success}` |
| GET | `/` | the interactive web UI |

`/api/export-asset` parameters (JSON body or query args):
- `region: [west,south,east,north]` **or** `west,south,east,north` **or** `roi_asset: <FeatureCollection id>` — the area.
- `year` (default 2024), optional `base_scheme` (`indiasat` default, or `worldcover`).
- `wait` (default `true` = block until done), `overwrite` (default `true`), `asset_id`/`name` (override output path).

---

## 10. Data, persistence, updates

- The whole checkout is mounted at `/app`, so the app reads its models from `data/` in the repo and
  **writes runtime state back to the host** (`data/hierarchy.json`, examples, etc.). Nothing is lost on
  restart.
- **Updating the app:** `git pull` in the checkout, then `docker compose … restart`. No rebuild.
- **Updating dependencies:** rare — if `deploy/requirements-docker.txt` changes, rebuild + repush the
  image (see `deploy/build_and_push.sh`), then `docker compose … pull && up -d` on the deploy host.

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `curl /api/health` fails locally | container not running (`docker ps`), or code not mounted — check the `-v .:/app` mount / compose `volumes`. |
| Health works locally but **not from another machine** | firewall (open port 8000) and confirm the service binds `0.0.0.0` (it does by default). |
| `export failed: ... asset ... does not exist` | `EE_ASSET_ROOT` points at a project/folder that doesn't exist or isn't writable — create the asset folder (§5) or fix the path. |
| `export failed: Cannot overwrite asset` | the target asset already exists and `overwrite=false` — omit it (default overwrites) or change `name`. |
| `region must be [west, south, east, north]` | the `region` value isn't a valid bbox; pass `[w,s,e,n]` (string or array both accepted). |
| STAC links show as `/api/...` (relative) in a browser | set `STAC_ASSET_BASE` to the public URL (§4/§7). |
| EE errors about credentials | the service-account key isn't mounted or `EE_SERVICE_ACCOUNT_KEY` path is wrong; confirm the mount and path inside the container. |
| Long export times out behind a proxy | raise `proxy_read_timeout` (nginx, §7), or use the async pattern (`wait=false` + `/api/export-status`). |

Logs: `docker compose -f docker-compose.hub.yml logs -f` (or `docker logs <container>`).

---

## 12. Security notes
- **Never commit** `.env` or the EE key (`deploy/ee-key.json`) — both are gitignored. Share the key
  privately; it can be revoked in GCP.
- If the endpoint is exposed publicly (ngrok/nginx), consider putting it behind an auth token or IP
  allow-list — by default it is open to anyone who can reach the URL.

---

### Quick summary for the impatient
```bash
git clone https://github.com/salil-123/Project.git corestack-lulc && cd corestack-lulc
cp deploy/.env.example .env            # set EE_PROJECT, EE_ASSET_ROOT, EE_SERVICE_ACCOUNT_KEY, STAC_ASSET_BASE
# put the EE key at deploy/ee-key.json and uncomment its mount in docker-compose.hub.yml
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
curl http://localhost:8000/api/health
```
Then set the algorithm URL in `deploy/stacd/corestack_lulc_algorithm_repo.yaml` and register the three
YAMLs in STACD.
</content>
