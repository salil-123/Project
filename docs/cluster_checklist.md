# CoRE Stack Cluster Service Checklist — sign-off

Service: **corestack-lulc** · against
<https://docs.core-stack.org/server/cluster-service-checklist/>

| # | Item | Status | Where |
|---|------|--------|-------|
| 1 | Mount `code/`, `models/`, `data/`; output in `data/` | **done** | `docker-compose*.yml`, `models/README.md`, `config.MODELS_DIR` |
| 2 | `AIRFLOW_API_BASE` set → Airflow, empty → local | **done** (was already) | `config.py`, `src/airflow_client.py`, `/api/dag/*` |
| 3 | Image pushed to GHCR or Docker Hub | **done** | `salil2003/corestack-lulc` on Docker Hub, `VERSION` |
| 4 | Google SSO | **parked** — awaiting advice | env names reserved in `deploy/.env.example` |
| 5 | Logs under `data/logs/<app>/`; `LOG_LEVEL` | **done** | `src/logging_setup.py` |
| 6 | Frontend + backend in one Docker | **done** (was already) | one compose service, backend serves `src/static/` |
| 7 | Frontend API base from `.env` | **done** | `/config.js` + `api()` in `app.js`, `API_BASE_URL` |
| 8 | Architecture diagram | **done** | [`docs/architecture.md`](architecture.md) |
| 9 | Postgres via `DATABASE_URL` | **N/A for now** | no database until #4 lands |
| 10 | `outputs.yaml` retention policy | **done** | [`../outputs.yaml`](../outputs.yaml) |

**8 done, 2 parked together.** #4 and #9 are one piece of work: the checklist marks #9 *"N/A if the
service has no database"*, and the only tables we'd create (users, auth audit) are the ones SSO
brings. Building them before the auth decision would be speculative.

## Item-by-item notes

**1 — mounts.** Three separate bind-mounts, defaulting to this checkout so a laptop needs no setup
and overridable per host (`CORESTACK_CODE_HOST` / `_MODELS_HOST` / `_DATA_HOST`). Weights resolve
through `config.model_path()`, which prefers `models/` and falls back to the historical `data/` home
— so the move is a script (`scripts/migrate_models.py`), not a flag day. *The move itself hasn't
been run:* the weights are git-tracked, so restructuring them is the maintainer's call.
Regenerable `*_train.csv` tables stay under `data/`, which is where the checklist wants data.

**2 — compute switch.** Already exactly as specified before this pass, including the same-origin
proxy that keeps Airflow creds out of the browser. Retrain now rides the **same** `op="export"` conf
(`{"retrain": {...}, "export": false}`) rather than needing a DAG of its own.

**3 — registry.** Deps-only image; code arrives by mount. `VERSION` added; pin the published tag to
it rather than relying on `latest`. The docs also accept GHCR if the project would rather move there.

**5 — logging.** `LOG_LEVEL` = `debug` | `info` | `error`, to stdout **and**
`data/logs/corestack-lulc/app.log` (rotating, 10 MB x 5). Secrets are scrubbed in the formatter, so
redaction can't be forgotten at a call site. One request line each, with duration; query strings only
at debug.

**7 — API base.** `app.js` has a single `api()` helper; the base comes from `/config.js`, which the
backend generates from `API_BASE_URL`. **Default is relative**, which is what fixed the blank page
under a reverse-proxy subpath. Leaflet is vendored rather than loaded from unpkg, since the campus
proxy can block the CDN.

**10 — outputs.** Note that a run's actual product is a **GEE asset + STAC Item**, governed in Earth
Engine, not a file under `data/`. `outputs.yaml` therefore covers the state that produced it — zoo
(`public`), user examples and scheme state (`private_persistent`), job bookkeeping (`delete`, 7 days).

---

Signed off: ______________  Date: ______________  Reviewer: ______________
