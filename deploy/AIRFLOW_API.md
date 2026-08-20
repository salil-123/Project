# Airflow DAG orchestration — env + API reference

How the app runs a classification/export through an Airflow DAG, what to put in `.env`, and the two
APIs involved (the backend proxy the frontend uses, and the raw Airflow API underneath).

## The flow

```
browser (Run)                     your backend                Airflow                  the DAG
   │  POST /api/dag/run  ───────────►  trigger_conf() ────────►  create run  ─┐
   │  ◄── { dag_run_id } ◄────────────  return run id  ◄────────  run id      │
   │                                                                          ▼
   │  GET /api/dag/status?run_id ──►  run_state() ────────────►  run state    DAG task calls back:
   │  ◄── { state, done, success }                                            POST /api/export-asset
   └─ poll until success/failed                                               (classify + export to GEE)
```

The frontend talks **only to the backend** (same origin as the page), never to Airflow directly — a
browser can't call Airflow cross-origin (CORS blocks it) and shouldn't hold the Airflow credentials.
The backend triggers + polls Airflow server-side. The DAG, when it runs, calls back into the backend's
`/api/export-asset` to do the actual Earth Engine work and export the raster to a GEE asset.

## Environment (.env)

`.env` is gitignored — put host-specific values here, not in committed code. Empty `AIRFLOW_API_BASE`
turns the DAG path off (`/api/dag/*` returns 503) and nothing else is affected.

| Var | What it is | Example |
|---|---|---|
| `AIRFLOW_API_BASE` | Root of the Airflow 2.x stable REST API (include `/api/v1`) | `http://10.125.63.136:8080/api/v1` |
| `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD` | Basic-auth creds for that API | `admin` / `admin` |
| `AIRFLOW_TOKEN` | Bearer token — use *instead of* username/password if your Airflow is token-auth | *(unset)* |
| `AIRFLOW_DAG_ID` | The DAG to trigger | `corestack_lulc` |
| `CORESTACK_API_BASE` | Where the Airflow worker reaches THIS backend to call `/api/export-asset` (a LAN IP / host, **not** `localhost` unless same box) | `http://10.125.63.155:8000` |

Auth precedence: if `AIRFLOW_TOKEN` is set it's used as a bearer token; otherwise username/password Basic.

## Backend proxy API (what the frontend calls)

Same-origin, so no CORS. Both log every call to the uvicorn console.

**Trigger a run**
```
POST /api/dag/run
Content-Type: application/json
{ "conf": { "region": [77.16,28.53,77.20,28.57], "year": "2024",
            "base_scheme": "indiasat", "execution_type": "fullexec" } }
->  200  { "dag_run_id": "manual__2026-…+00:00", "state": "queued" }
->  503  if AIRFLOW_API_BASE is unset;  502  if Airflow rejects the trigger
```

**Poll a run**
```
GET /api/dag/status?run_id=<dag_run_id>
->  200  { "dag_run_id": "…", "state": "running", "done": false, "success": false }
         state is queued|running|success|failed; done=true at success|failed
```

## Raw Airflow API (underneath / for a direct client)

If something hits Airflow directly (curl, a teammate's own client) instead of via the backend:

```
# trigger
POST {AIRFLOW_API_BASE}/dags/{AIRFLOW_DAG_ID}/dagRuns      (Basic admin:admin)
body: { "conf": { … } }        -> returns dag_run_id + state:"queued"

# poll
GET  {AIRFLOW_API_BASE}/dags/{AIRFLOW_DAG_ID}/dagRuns/{dag_run_id}   -> { state, … }

# task logs (debug)
GET  {AIRFLOW_API_BASE}/dags/{AIRFLOW_DAG_ID}/dagRuns/{dag_run_id}/taskInstances
```

curl works but a **browser** will not — Airflow sends no `Access-Control-Allow-Origin`, so a cross-origin
browser call is blocked (that's the whole reason the frontend goes through the backend proxy).

**Enable Basic auth on the Airflow webserver** if a raw call returns 401 — inside the Airflow container:
```
grep "auth_backends" /opt/airflow/airflow.cfg | grep -v "^#"
# if it lists only 'session', add basic_auth and restart:
sed -i 's/auth_backends = airflow.api.auth.backend.session/auth_backends = airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session/' /opt/airflow/airflow.cfg
pkill -f "airflow webserver"; sleep 3; airflow webserver -p 8080 &
```

## Notes

- The DAG exports a **GEE asset** (the pipeline output); it doesn't hand tiles back. The UI, after the run
  succeeds, separately calls `/api/classify` to draw the classification on the map so there's a visible
  result. See `airflow_job_flow_plan.md` for the design and the hardening TODO (return the asset id so the
  UI renders that exact asset instead of re-classifying).
- No Docker rebuild needed to ship changes here — the image is dependencies-only and the code is
  bind-mounted; deploy with `git pull` + restart, and make sure the `.env` above is in place.
