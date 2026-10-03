# CoRE Stack Cluster Service Checklist — sign-off

Service: **corestack-lulc** · against
<https://docs.core-stack.org/server/cluster-service-checklist/>

| # | Item | Status | Where |
|---|------|--------|-------|
| 1 | Mount `code/`, `models/`, `data/`; output in `data/` | **done** | `docker-compose*.yml`, `models/README.md`, `config.MODELS_DIR` |
| 2 | `AIRFLOW_API_BASE` set → Airflow, empty → local | **done** (was already) | `config.py`, `src/airflow_client.py`, `/api/dag/*` |
| 3 | Image pushed to GHCR or Docker Hub, version-tagged | **done** | `salil2003/corestack-lulc:1.0.0` (+ `:latest`) on Docker Hub, `VERSION` |
| 4 | Google SSO | **built** (week 18); our own OAuth client made 3 Oct, needs its id on the tower | `src/auth.py`, the `Gate` middleware in `src/backend.py`, `GOOGLE_CLIENT_ID` |
| 5 | Logs under `data/logs/<app>/`; `LOG_LEVEL` | **done** | `src/logging_setup.py` |
| 6 | Frontend + backend in one Docker | **done** (was already) | one compose service, backend serves `src/static/` |
| 7 | Frontend API base from `.env` | **done** | `/config.js` + `api()` in `app.js`, `API_BASE_URL` |
| 8 | Architecture diagram | **done** | [`docs/architecture.md`](architecture.md) |
| 9 | Postgres via `DATABASE_URL` | **done** (week 18) | `src/db.py` (users, projects); SQLite only when unset, on a laptop |
| 10 | `outputs.yaml` retention policy | **done** | [`../outputs.yaml`](../outputs.yaml) |
| 11 | Front page + reviewed demo video | front page **done**; video drafted, awaiting sir's review | `src/static/landing.html` at `/`, `INTRO_VIDEO_URL`, `week19/walkthrough_flow.md` |

**9 done, #4 and #11 nearly there** (updated 3 Oct). #4 and #9 landed together in week 18: the only tables are the ones sign-in
brings (users) plus the projects they own. #4 has our own OAuth client now (Susmit's advice: every service registers its own); its id goes into the tower's `.env`.
A real Google sign-in has run end to end on a laptop (3 Oct); on the tower, not yet.

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

**4 — SSO.** Google's sign-in button hands the page a signed ID token; `POST /api/auth/google`
verifies its signature, audience (`GOOGLE_CLIENT_ID`) and expiry with `google-auth`, then sets a
signed HttpOnly session cookie. One middleware (`Gate`) enforces the rule for every request:
no session, no compute and no writes (401); someone else's project, 403; a public project, read-only.
The Airflow DAG calls back with `X-Service-Token` (`SERVICE_TOKEN`). Without a client id the app
offers a local login for laptops, which refuses to run once one is set. This differs from the drone
service on purpose: it trusts an `X-User-Email` header, which does not meet "validated on the backend".

**9 — Postgres.** `DATABASE_URL` → the central Postgres; tables are created on start (`db.init`).
Unset, it falls back to `data/corestack.db`, which is for a laptop only.

**10 — outputs.** Note that a run's actual product is a **GEE asset + STAC Item**, governed in Earth
Engine, not a file under `data/`. `outputs.yaml` therefore covers the state that produced it — zoo
(`public`), user examples and scheme state (`private_persistent`), job bookkeeping (`delete`, 7 days).

---

Signed off: ______________  Date: ______________  Reviewer: ______________
