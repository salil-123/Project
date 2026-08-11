# Running the Custom LULC service (for Saharsh)

The LULC model ships as a public Docker image. Pull it, give it Earth Engine credentials, point it at a
GEE project you can write to, and it exposes one endpoint your STACD DAG calls. Registers in STACD as the
algorithm **`Custom_LULC`** (separate from CoreStack's `lulc_v3`).

## 1. Pull the image
```bash
docker pull salil2003/corestack-lulc:latest
```

## 2. Earth Engine auth (the only real setup step)
The container has no EE credentials baked in. Two options:

**Option A — use OUR project via a service-account key (recommended).** We give you a JSON key for a
service account on our project (`modern-mystery-398416`); the container authenticates as it, and outputs
land in our project (already set up). Nothing to configure on your GEE side. Mount the key and set
`EE_SERVICE_ACCOUNT_KEY` (see the run command below). Keep the key file private.

**Option B — use your own EE identity.** Authenticate once on the host and mount the token:
```bash
earthengine authenticate          # one-time, on the host; opens a browser, stores a token
ls ~/.config/earthengine/credentials   # confirm it's there
```
Then set `EE_PROJECT` / `EE_ASSET_ROOT` to a project you can write to.

## 3. Run it

**Option A — our project, service-account key** (outputs land in our already-set-up project):
```bash
docker run -d --name custom_lulc -p 8000:8000 \
  -e EE_PROJECT=modern-mystery-398416 \
  -e EE_ASSET_ROOT=projects/modern-mystery-398416/assets/custom_lulc \
  -e EE_SERVICE_ACCOUNT_KEY=/app/ee-key.json \
  -v /path/to/ee-key.json:/app/ee-key.json:ro \
  salil2003/corestack-lulc:latest
```

**Option B — your own project + token:**
```bash
docker run -d --name custom_lulc -p 8000:8000 \
  -e EE_PROJECT=<your-gee-project> \
  -e EE_ASSET_ROOT=projects/<your-gee-project>/assets/custom_lulc \
  -v ~/.config/earthengine:/root/.config/earthengine:ro \
  salil2003/corestack-lulc:latest
```
First time only: make sure the asset folder exists (Code Editor -> Assets, or the app auto-creates it
under an existing project root).

## 4. Verify it's up
```bash
curl http://127.0.0.1:8000/api/health            # -> {"ok": true}
# one real export end to end (small AOI): returns the asset descriptor once the GEE task finishes
curl "http://127.0.0.1:8000/api/export-asset?west=77.16&south=28.53&east=77.20&north=28.57&year=2024&name=smoke"
```
A healthy response looks like:
```json
{ "status": "success",
  "asset_id": ["projects/<proj>/assets/custom_lulc/smoke_2024"],
  "version": "1", "hosting_platform": "GEE",
  "stac_items": [ { "type": "Feature", "stac_version": "1.1.0", "id": "lulc_...", "bbox": [...],
                    "geometry": {...}, "properties": {...}, "assets": {...}, "links": [...] } ] }
```

## 5. The endpoint your DAG calls
`POST /api/export-asset` (GET with query args also works). The DAG forwards its run `conf` here; params can
sit at the top level or under a `conf` key, and extra keys are ignored. Input, any of:
- `region: [west, south, east, north]` — the bbox (the DAG param), or
- `roi_asset=<FeatureCollection asset id>` — reads geometry from it (e.g. MWS boundaries), or
- `west,south,east,north` — a plain bbox.
Plus `year` (or `start_year`/`end_year`), `base_scheme`, optional `asset_id`/`name`, and `asset_base` (or
the `STAC_ASSET_BASE` env) to make the STAC hrefs absolute. This is the `url:` in
`corestack_lulc_algorithm_repo.yaml`.

```bash
curl -X POST http://HOST:8000/api/export-asset -H "Content-Type: application/json" \
  -d '{"region":[77.16,28.53,77.20,28.57],"year":2024,"base_scheme":"indiasat"}'
```

**Response shape** (what the STACD DAG generator reads): `status`, `asset_id` (list), `version`,
`hosting_platform`, and `stac_items` (an array of STAC Feature objects). There is **no `stacd` block** —
the pipeline builds provenance from the registered YAMLs and only reads `stac_items`. Re-running the same
region+year overwrites the existing asset (idempotent); pass `overwrite=false` to keep it.

**Two ways to run it:**
- **Synchronous (default, `wait=true`):** the call blocks until the GEE export finishes, then returns the
  descriptor. Matches the other CoreStack APIs; simplest for a plain DAG task.
- **Async + poll (for long exports / to avoid HTTP timeouts):** call with `wait=false` — it submits and
  returns immediately with a `task_id`. Then poll `GET /api/export-status?task_id=<id>` until
  `"done": true`; `"success": true` is the isSuccess() check (an Airflow sensor fits here). You can also
  poll `GET /api/export-status?asset_id=<id>` to check whether the asset exists yet.
  ```bash
  # submit
  curl "http://HOST:8000/api/export-asset?...&wait=false"     # -> {task_id, asset_id, state:"SUBMITTED"}
  # poll
  curl "http://HOST:8000/api/export-status?task_id=<id>"      # -> {state, done, success, error}
  ```

## Handy
```bash
docker logs -f custom_lulc        # watch requests during a run
docker stop custom_lulc && docker rm custom_lulc   # tear down
docker run ... -v custom_lulc_data:/app/data ...   # add to persist the tree/op-log across restarts
```

## Notes
- The algorithm registers as **`Custom_LULC`** (see `lulc_dag.yaml` / `lulc_algorithm.yaml`), so it sits
  alongside `lulc_v3` rather than clashing.
- Exports go to `EE_ASSET_ROOT`; the DAG doesn't need to pass an output path (the endpoint returns the
  `asset_id` it created), though it can via `asset_id=`.
- Image is ~1.5 GB, CPU-only, no GPU needed.
</content>
