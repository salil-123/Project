# Running the Custom LULC service (for Saharsh)

The LULC model ships as a public Docker image. Pull it, give it Earth Engine credentials, point it at a
GEE project you can write to, and it exposes one endpoint your STACD DAG calls. Registers in STACD as the
algorithm **`Custom_LULC`** (separate from CoreStack's `lulc_v3`).

## 1. Pull the image
```bash
docker pull salil2003/corestack-lulc:latest
```

## 2. Earth Engine auth (the only real setup step)
The container has no EE credentials baked in. Easiest path: authenticate once on the host, then mount
that credential into the container.
```bash
earthengine authenticate          # one-time, on the host; opens a browser, stores a token
ls ~/.config/earthengine/credentials   # confirm it's there
```
(For a headless server later we can switch to a service-account key; mounting the token is fine to start.)

## 3. Run it
Point `EE_PROJECT` and `EE_ASSET_ROOT` at a GEE project **your EE identity can write assets to** (a
CoreStack project, or your own). The output rasters land under `EE_ASSET_ROOT`.
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
{ "asset_id": "projects/<proj>/assets/custom_lulc/smoke_2024",
  "version": "1", "hosting_platform": "GEE",
  "classes": ["barren","built_up","greenery","other","water"], "state": "COMPLETED" }
```

## 5. The endpoint your DAG calls
`GET /api/export-asset` — synchronous (blocks until the GEE export completes), returns the STACD shape
`{asset_id, version, hosting_platform: "GEE"}`. Input, either:
- `roi_asset=<FeatureCollection asset id>` — reads geometry from it (e.g. the filtered MWS boundaries), or
- `west,south,east,north` — a plain bbox.
Plus `year` (or `start_year`/`end_year`), and optional `asset_id` / `name` to control the output path.
This is the `url:` in `lulc_algorithm.yaml` (set the host to wherever Airflow reaches the container).

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
