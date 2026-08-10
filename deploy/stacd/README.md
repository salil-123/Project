# Submission package — onboarding the LULC model into STACD

Everything Saharsh needs to deploy our model into the STACD / CoreStack Airflow framework, plus the
one open integration decision.

## Links (both ready + public)
- **Docker image:** `docker pull salil2003/corestack-lulc:latest` — public, 1.52 GB, boots healthy
  (`/api/health` → `{"ok": true}`).
- **Source (Dockerfile + deploy + code):** https://github.com/salil-123/Project (branch `week10-lulc-models`).
- **STACD provenance:** the app already emits a STAC 1.1.0 Item + DAG at `GET /api/stacd` (cross-checked
  with Susmit's tree-crown item — `week11/notes/stacd_crosscheck.md`).

## The 3 onboarding YAMLs (drafts in this folder)
Following `STACD_framework/dev` (`airflow/stacd/yaml_configs/`, `sample_yaml/`):
- `lulc_dag.yaml` — `!DAG` + `!Algorithm_Type` + `!Dataset_Type`
- `lulc_algorithm.yaml` — `!Algorithm_Instance` (API-mode primary, Docker-mode fallback)
- `lulc_dataset.yaml` — `!Dataset_Instance` (the AOI input)

## Our API surface (for API-mode)
Base URL of the running container, e.g. `http://lulc:8000`:
| Method | Path | Does |
|--------|------|------|
| GET | `/api/health` | liveness (`{"ok": true}`) |
| GET | `/api/classify?west&south&east&north&year` | server-side EE classify → tile URLs + class counts |
| GET | `/api/classify.tif?…` | classified GeoTIFF (size-capped) |
| GET | `/api/stacd?…&year=&archive=true` | STAC Item + STACD DAG for the run |
| GET | `/api/water?date=YYYY-MM-DD` · `/api/segment?cls=` · `/api/treecrop` · `/api/farmshrub` | the other layers |

Params: an AOI as a bbox (`west/south/east/north`) today; a CoreStack boundary (state/district/block)
can be resolved to a bbox on our side if that's how the DAG passes AOIs.

## The one open piece (needs Saharsh's answer + a small addition on our side)
Your STAC ingestion expects the algorithm's success response to be:
```json
{ "asset_id": "projects/…/assets/output", "version": "1", "hosting_platform": "GEE" }
```
i.e. the algorithm **exports its output to a GEE asset and returns the asset_id**. Our endpoints
currently return *tiles + counts + STACD metadata*, not a persisted GEE asset. So to close the loop we'd
add **`GET/POST /api/export-asset`** that runs `ee.batch.Export.image.toAsset(...)` on the classified
image and returns exactly that descriptor. Small, well-scoped — I'll build it once we agree on:
1. **API-mode vs Docker-mode** as the primary (API fits, since we're a running service; Docker-mode
   would need a `runner.run()` CLI wrapper printing the `RESULT_JSON` markers — also doable).
2. The **exact success JSON** and where the output asset should live (which GEE project/path, naming).
3. Whether AOIs arrive as **admin boundaries** (state/district/block) or **bbox** params.
4. The **EE credential** the DAG uses (`gee_account_id`) — we need a service-account key for headless EE.

## EE auth in the container
Headless EE needs a **service-account key** (not `earthengine authenticate`): mount it read-only and set
`GOOGLE_APPLICATION_CREDENTIALS`; `config.ee_init()` gets wired to use it. (Commented volume in
`docker-compose.hub.yml`.)
</content>
