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

**Packaging model (important — how the two pieces fit):**
- The **Docker image = the dependencies only** (Python + geospatial libraries). You get it with
  `docker pull`. It contains **no application code**.
- The **application code = a folder on the host** (from the code package or a git clone).
- At **run time** (`docker run` / `docker compose up`), that code folder is **bind-mounted** onto the image
  at the path **`/app`** (via `-v <code-folder>:/app` — the compose files do this for you). This mount is a
  *run-time step, not part of `docker pull`.*

So the mental model is: **`docker pull` the deps once → mount your code onto it at `/app` each run.**
Consequences:
- Update the app = swap the code folder (`git pull`, or drop in a new package) + restart. **No image rebuild.**
- Rebuild + re-push the image **only** if `deploy/requirements-docker.txt` (the dependency list) changes.

- **Code:** a git clone of `https://github.com/salil-123/Project.git`, **or** the `corestack-lulc-deploy.zip`
  package (no GitHub needed).
- **Image:** `salil2003/corestack-lulc:latest` (public on Docker Hub, dependencies-only, ~1.5 GB).
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

## 5. Earth Engine setup (required)

The service classifies with Earth Engine, so it needs EE credentials and a GEE project + folder to write
the output asset into. Without this the app still starts and `/api/health` works, but `/api/export-asset`
fails. Two options — **Option A is the simplest** (we hand you everything).

### Option A — use our project with the key we provide *(recommended)*
We give you a service-account key file (`ee-key.json`) for our project `modern-mystery-398416`. The service
account and the `corestack_lulc` output folder are **already set up on our side**, so there's nothing for
you to create in Google Cloud. On the deploy machine:
1. Put the `ee-key.json` we gave you at `./deploy/ee-key.json` (inside the project folder).
2. In `.env` set:
   ```
   EE_PROJECT=modern-mystery-398416
   EE_ASSET_ROOT=projects/modern-mystery-398416/assets/corestack_lulc
   EE_SERVICE_ACCOUNT_KEY=/app/deploy/ee-key.json
   ```
3. In `docker-compose.hub.yml`, uncomment the key-mount line:
   ```yaml
   - ./deploy/ee-key.json:/app/deploy/ee-key.json:ro
   ```
4. `docker compose -f docker-compose.hub.yml up -d`, then run the §6 test — a `status: success` with an
   asset id means EE is wired correctly. Outputs land in our project's `corestack_lulc` folder.

That's the entire EE setup for this option.

### Option B — use your own GEE project *(only if you'd rather not use ours)*
1. **Have a GEE-enabled project.** Create a Google Cloud project and register it for Earth Engine by
   signing in once at <https://code.earthengine.google.com>. Note its **project id** → this is `EE_PROJECT`.
2. **Create a service-account key.** Cloud Console → **IAM & Admin → Service Accounts → Create service
   account** (e.g. `lulc-runner`). Grant it **BOTH** roles (both are required — Resource Writer lets it
   read/write assets, Service Usage Consumer lets it *call* the EE API on the project):
   - **Earth Engine Resource Writer** (`roles/earthengine.writer`)
   - **Service Usage Consumer** (`roles/serviceusage.serviceUsageConsumer`)

   Then **Keys → Add key → JSON**, rename the download `ee-key.json`. gcloud equivalent:
   ```bash
   gcloud config set project <your-project>
   gcloud iam service-accounts create lulc-runner --display-name="LULC runner"
   gcloud projects add-iam-policy-binding <your-project> \
     --member="serviceAccount:lulc-runner@<your-project>.iam.gserviceaccount.com" \
     --role="roles/earthengine.writer"
   gcloud projects add-iam-policy-binding <your-project> \
     --member="serviceAccount:lulc-runner@<your-project>.iam.gserviceaccount.com" \
     --role="roles/serviceusage.serviceUsageConsumer"
   gcloud iam service-accounts keys create ee-key.json \
     --iam-account=lulc-runner@<your-project>.iam.gserviceaccount.com
   ```
3. **Create the output folder.** <https://code.earthengine.google.com> → **Assets** tab → (add your project
   if it has no asset root) → **NEW → Folder** → name it `corestack_lulc`. Full id:
   `projects/<your-project>/assets/corestack_lulc` → this is `EE_ASSET_ROOT`.
4. **Wire it in** — same as Option A steps 1–4, but with your project id / paths.

> Local-test-only alternative (no service account): run `earthengine authenticate` on the host and mount
> `~/.config/earthengine:/root/.config/earthengine:ro` instead of a key.

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
| EE error `... does not have required permission to use project ... serviceusage` | the service account is missing the **Service Usage Consumer** role — grant it `roles/serviceusage.serviceUsageConsumer` (§5, both roles are required). |
| Long export times out behind a proxy | raise `proxy_read_timeout` (nginx, §7), or use the async pattern (`wait=false` + `/api/export-status`). |

Logs: `docker compose -f docker-compose.hub.yml logs -f` (or `docker logs <container>`).

---

### Quick summary
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
