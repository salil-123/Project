# Architecture — how compute is triggered, and from where

Cluster checklist #8. The short version: **one container serves both the UI and the API**, and a
single environment variable decides whether the long jobs run inside it or go out to Airflow.

```mermaid
flowchart TB
    subgraph browser["Browser"]
        UI["Front page / + Leaflet tool /app<br/>src/static/, served by the backend itself<br/>API base from /config.js (relative by default)"]
    end

    subgraph host["Tower host"]
        subgraph svc["Frontend Docker — the single app container"]
            API["FastAPI backend (src/backend.py)<br/>sign-in gate · projects + runs<br/>classify · retrain · export-asset · zoo"]
        end
        FB["FileBrowser<br/>(browses data/)"]
        subgraph mounts["Three bind-mounts"]
            CODE["code/ → /app<br/>git pull + restart"]
            MODELS["models/ → /app/models<br/>trained weights"]
            DATA["data/ → /app/data<br/>inputs · caches · outputs<br/>data/logs/corestack-lulc/"]
        end
        PG[("Central Postgres<br/>DATABASE_URL: users + projects")]
    end

    AF["Airflow–STACD Docker<br/>shared orchestrator"]
    GEE["Google Earth Engine<br/>Alpha Earth embeddings +<br/>exported LULC assets"]
    GOOG["Google sign-in<br/>(our own OAuth client)"]

    UI -->|"same-origin /api/*<br/>session cookie"| API
    UI -->|"Sign in with Google:<br/>ID token"| GOOG
    API -->|"verifies the token<br/>(google-auth)"| GOOG

    API -->|"AIRFLOW_API_BASE set:<br/>POST /api/dag/run → trigger + poll"| AF
    AF -->|"calls back over HTTP<br/>POST /api/export-asset<br/>X-Service-Token, conf carries<br/>region, year, project_id,<br/>optionally retrain"| API
    API -->|"AIRFLOW_API_BASE empty:<br/>run inline, same code path"| API

    API <--> MODELS
    API <--> DATA
    API -->|"classify + export raster"| GEE
    GEE -->|"asset id + STAC Item"| API
    DATA --> FB
    API <-->|"users, projects"| PG

    classDef off stroke-dasharray: 4 3
    class PG off
```

## The switch

`AIRFLOW_API_BASE` is the only thing that decides where compute runs — there is no `COMPUTE_MODE`
flag (checklist #2 forbids one).

| `AIRFLOW_API_BASE` | What happens |
|---|---|
| **set** | The browser calls our same-origin proxy `POST /api/dag/run`; the backend triggers the DAG server-side and the page polls `GET /api/dag/status`. The DAG calls back into `POST /api/export-asset` to do the work. The browser never talks to Airflow (CORS would block it, and the creds shouldn't be in the page). |
| **empty** | The same handler runs inline in the request. No Airflow host needed — this is the laptop case. |

The same image covers both; only `.env` changes.

## Retrain rides the export path

Training is *not* a second DAG. A retrain is sent as part of the **same `op="export"` conf** the
classify/export path already uses:

```jsonc
{ "retrain": { "node": "greenery", "algo": "logreg" },
  "export": false }        // false = train and stop; omit it to train, then classify + export
```

`/api/export-asset` picks the `retrain` key out of the conf, trains first, and only then classifies
with the fresh model. So there's one DAG and one STACD algorithm registration to maintain, not two.
The training itself always runs *inside this container* — the DAG only drives us over HTTP — so the
weights, the hierarchy and the zoo cards can't drift apart.

## Where things land

- **The product of a run** is a **GEE asset** (under `EE_ASSET_ROOT`) plus a **STAC Item** describing
  it — not a file on disk. That's the deliverable the pipeline registers.
- **`data/`** holds the state that produced it: the class tree, the op-log, user example polygons,
  the model zoo, cached training tables, job bookkeeping, and logs. Retention for each path is
  declared in [`outputs.yaml`](../outputs.yaml); a host data service reads that file.
- **`models/`** holds trained weights, on their own mount so outputs can be rotated without them.
- **Logs** go to `data/logs/corestack-lulc/app.log` (rotating, 10 MB x 5) and stdout, at whatever
  `LOG_LEVEL` says.

## Sign-in and the database (week 18)

**Google SSO (#4) and central Postgres (#9)** landed together. The browser gets an ID token from
Google (our own OAuth client, `GOOGLE_CLIENT_ID`) and posts it to `/api/auth/google`; the backend
verifies it and sets a signed, HttpOnly session cookie. One middleware gates every write and compute
call on that cookie and on project ownership. `users` and `projects` live in the central Postgres
(`DATABASE_URL`); each project's files sit under `data/projects/<id>/`. Airflow's callbacks have no
browser session, so they carry `X-Service-Token` (`SERVICE_TOKEN` here, `CORESTACK_SERVICE_TOKEN` on
the DAG side). Without a client id (a laptop) the app falls back to a name-only local login and a
SQLite file.
