# Airflow-orchestrated job flow (async transport, sync experience)

Goal: route the app's long operations through an Airflow DAG instead of doing the work inline in the
request. The user experience stays synchronous — the frontend polls until the DAG finishes, the DAG
doesn't finish until the backend work returns success. Every link blocks on the next, so nothing
races.

## The chain

```
frontend "submit"
   -> POST /api/jobs {op, params}                 (backend)
        backend picks a run_id, triggers the DAG via Airflow REST, returns {run_id}
   -> Airflow runs the DAG (conf = op, params, api_base, run_id)
        DAG task calls the backend's real work endpoint (classify / export-asset) and BLOCKS
        on success it POSTs the result to POST /api/jobs/{run_id}/result   (backend stores it)
   -> frontend polls GET /api/jobs/{run_id} until done, reads result
```

If Airflow isn't configured (local/dev), `POST /api/jobs` runs the work **inline** and stores the
result immediately, so the same poll flow works with or without Airflow — the app never breaks.

## Pieces

- [x] `config.py` — Airflow settings (API base, auth, dag id) + `CORESTACK_API_BASE` (where the DAG
      reaches the backend).
- [x] `src/jobs.py` — file-backed job store keyed by run_id (survives restart + multiple workers; the
      DAG's result-post may land on a different worker than the trigger).
- [x] `src/airflow_client.py` — thin wrapper over the Airflow 2.x stable REST API: `configured()`,
      `trigger(run_id, conf)`, `run_state(run_id)`.
- [x] `backend.py` — three endpoints:
        POST /api/jobs            -> create + trigger (or run inline), return {run_id, done?}
        GET  /api/jobs/{run_id}   -> poll: {state, done, success, result, error}
        POST /api/jobs/{run_id}/result -> the DAG callback that stores the work result
- [x] `airflow/dags/corestack_lulc_dag.py` — rewrite to the job DAG: read conf, call the work
      endpoint, post the result back. run_id comes from the DAG run context.
- [x] frontend `app.js` — a `runJob(op, params)` helper that POSTs /api/jobs then polls; wire the
      classify "Run" button through it. Same path supports the export op.
- [x] `deploy/.env.example` — document the new AIRFLOW_* / CORESTACK_API_BASE vars.

## Ops the DAG can run

- `classify` -> params {west, south, east, north, year, mode} -> the /api/classify result
- `export`   -> params for /api/export-asset (region/bbox, year, base_scheme, ...) -> the asset descriptor

## Notes / watch-outs

- The backend controls the run_id (passes `dag_run_id` in the trigger body), so it can return it to the
  frontend before Airflow schedules anything, and the DAG reuses the same id from its context.
- The store is file-backed under DATA_DIR/jobs/ — no shared-memory assumption across uvicorn workers.
- Poll also asks Airflow for the run state, so a DAG failure surfaces to the frontend instead of hanging.
