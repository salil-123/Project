# Core Stack LULC: service readiness report

Service: **corestack-lulc**
Repo: `salil-123/Project` @ `eec34e1` + week 18 work (staged, not yet pushed) · Zoo: `salil-123/zoo_database` @ `8916fb6`
Image: `salil2003/corestack-lulc` · First written 24 September 2026 · **Updated 3 October 2026** (after week 18)

Two things this report covers: where the five assigned tasks stand, and a full pass over the
[CoRE Stack Cluster Service Checklist](https://docs.core-stack.org/server/cluster-service-checklist/),
which has grown to **eleven** items since our first audit.

| | Count (24 Sep) | Count (3 Oct) |
|---|---|---|
| Complete | 7 | 8 (§9 now done) |
| Built, needs a step on the tower | 0 | 2 (§4 needs our OAuth client id; §11 needs the video) |
| Partial | 1 (§3) | 1 (§3, version tag not pushed) |
| Parked on instruction | 1 (§4) | 0 |
| Not started | 1 (§11) | 0 |
| Not applicable | 1 (§9) | 0 |

**What changed since 24 Sep, in one paragraph.** Week 18 built the two parked items and the new one:
Google sign-in verified on the server (§4), users and projects in a database via `DATABASE_URL` (§9),
and a front page at `/` with a slot for the video (§11). scikit-learn is pinned to 1.8.0. The Airflow
callbacks carry a service token so sign-in doesn't lock the DAG out. None of it is on the tower yet:
the code is staged, the image needs one rebuild, and the tower needs our own Google OAuth client id.
The current to-do list is §4 below.

---

## 1. The five assigned tasks

### 1.1 Google SSO, with a database behind it (BUILT in week 18; needs our client id on the tower)

*24 Sep: parked on instruction.* Built in week 18:

* **Sign-in.** The browser uses Google Identity Services (the same library as Susmit's drone app) and
  hands the server a signed ID token. `POST /api/auth/google` checks signature, audience (our client
  id), expiry and verified email with `google-auth`, then sets a signed, HttpOnly session cookie
  (`src/auth.py`). Unlike drone_docker, which trusts an `X-User-Email` header, nothing here takes the
  browser's word for who the user is; the checklist asks for SSO *validated on the backend*.
* **Gate.** One ASGI middleware (`Gate` in `src/backend.py`): every write or compute call without a
  session gets 401, someone else's project 403, a public project is read only.
* **Database.** `users` and `projects` tables via SQLAlchemy (`src/db.py`); `DATABASE_URL` picks
  Postgres on the tower, SQLite only when it's unset, on a laptop. Each project's files live under
  `data/projects/<id>/`.
* **The Airflow constraint, handled.** The DAG calls back into `/api/export-asset` and
  `/api/jobs/{id}/result` with no browser session. Those calls carry `X-Service-Token`, checked
  against `SERVICE_TOKEN`; the backend warns at startup if sign-in is on and the token isn't set.
* **Local login** for laptops: when no client id is set, the front page offers a type-your-name
  login. It switches itself off the moment `GOOGLE_CLIENT_ID` is set.

**Still to do: our own OAuth client.** Susmit's advice (3 Oct): each service registers **its own**
Google OAuth client and uses its own client id; we don't borrow his. Steps in §4 below and in
`deploy/DEPLOY_GUIDE.md` §12.2.

### 1.2 Audit against the tower-services guidelines (DONE)

The [tower-services page](https://docs.core-stack.org/infra/tower-services/) is an overview; the
operative document is the Cluster Service Checklist it links to, which is a numbered spec with an
explicit acceptance criterion per item. Section 2 below is the full pass. A filled sign-off table
lives at `docs/cluster_checklist.md`.

### 1.3 Better logging, with real detail on debug (DONE)

See §2.5.

### 1.4 Remove the water and mining buttons; route retraining through the export path (DONE)

Buttons: removed from `src/static/index.html` (markup), `src/static/app.js` (88 lines of handlers
plus dead layer state) and `src/static/style.css` (the `.water-row` rules). The backend endpoints
`/api/water`, `/api/water-frequency` and `/api/segment` were **kept**: STACD and the week
experiments reference them, and an unused route costs nothing.

Retraining: see §3.2. No second DAG was needed.

### 1.5 Model zoo showing only four models; make all paths relative (DONE)

Both fixed. The zoo turned out to be a more serious problem than a display bug (§3.1), and the
relative-path issue was the specific fault that left a blank page in the image handed over (§3.3).

---

## 2. The checklist, item by item

### §1 Three mounts: `code/`, `models/`, `data/` (DONE, with one tension)

**Requirement.** Bind-mount three host folders separately. Weights under `models/`, all compute
output under `data/`, nothing baked into the image.

**What was done.**

* `config.MODELS_DIR` (env `CORESTACK_MODELS_DIR`, default `<root>/models`), and `project_path()`
  now understands a leading `models/` the same way it understands `data/`.
* `config.model_path(rel)` is the compat seam. It resolves a weight under `models/` if present,
  falls back to the historical `data/` location if not, and returns the `models/` path when neither
  exists so new writes land in the new home. Resolution is **per file**, so a half-migrated box
  works. This matters because every zoo card's `artifact.path` records the old `data/refine/...`
  spelling, and those cards are data we would rather not rewrite.
* All load sites repointed: `infer` (base, softvote, per-node classifiers, fortnight water),
  `refine` (base, worldcover, weight writes), `catalogue` (base cards, per-node joblibs, archive).
* `data/refine/` was doing two jobs. It is split now: `REFINE_DIR` is weights only, and
  `TRAIN_CACHE_DIR` keeps the regenerable `*_train.csv` tables under `data/`, which is where the
  checklist wants data. That is 326 MB of tables that correctly stay out of `models/`.
* `scripts/migrate_models.py` (`--dry-run`, `--keep`) performs the move. Weights only.
* Both compose files mount three dirs separately, defaulting to the checkout so a laptop needs no
  setup and overridable per host:

  ```yaml
  - ${CORESTACK_CODE_HOST:-.}:/app
  - ${CORESTACK_MODELS_HOST:-./models}:/app/models
  - ${CORESTACK_DATA_HOST:-./data}:/app/data
  ```

* The migration has been run locally: 15 weights moved, verified inside the container.

**A bug the migration exposed.** `infer.load_model()` reads the path stored in
`data/active_base.json` and passed it through `project_path()`, not `model_path()`. A stored
`data/model_pooled.joblib` therefore pointed at a file that no longer existed, and startup died with
`FileNotFoundError`. Fixed to go through `model_path()`, which accepts either spelling. Worth
noting because on the live box this would have been a boot failure rather than a warning, and it
only surfaced because the migration was done locally first.

**The tension to decide.** The acceptance criterion reads:

> *"Restarting the container keeps models and compute results; `git pull` updates code without
> touching `data/` or `models/`."*

Our weights are **tracked in git**, so a `git pull` does touch `models/`. That is a deliberate
convenience: it is how a deploy box gets its models with no separate fetch step, and the linear
models are a few KB each. But it reads against the item's intent, which treats `models/` as host
state rather than repo content. The alternative is moving weights out to `deploy/fetch_models.sh`
and making deployment two steps. **This needs a decision, not a silent default.**

Also worth noting: `.gitignore` gained `models/refine/biomass_*.joblib` **before** the migration ran.
The old rule only matched `data/`, so without it the 553 MB biomass file would have been staged
under its new path. That is the same file that jammed the zoo for two months (§3.1).

### §2 `AIRFLOW_API_BASE` set → Airflow, empty → local (DONE, already was)

This item was already implemented exactly as specified before this work started, including the
same-origin proxy (`/api/dag/run`, `/api/dag/status`) that keeps Airflow credentials out of the
browser and sidesteps CORS. No `COMPUTE_MODE` flag anywhere. Nothing needed doing.

### §3 Image pushed to GHCR or Docker Hub (PARTIAL)

The image is deps-only, lives on Docker Hub, and the README carries the exact `docker pull` line.

What is missing is one line of the requirement: *"Image tagged with version (optionally `latest`)"*.
We publish only `:latest`; `VERSION` says 0.9.0 but no matching tag has been pushed.

**Update 3 Oct.** Week 18 added dependencies (sqlalchemy, psycopg 3, google-auth, itsdangerous) and
pinned scikit-learn, so the image has to be rebuilt anyway. Do it with a version tag and §3 closes in
the same step: bump `VERSION` (to 1.0.0, the first build with sign-in), then
`deploy/DEPLOY_GUIDE.md` §12.1 builds and pushes both `:latest` and `:$(cat VERSION)`.

### §4 Google SSO (BUILT, needs our client id)

See §1.1. What stands between this and done is registering our own OAuth client and putting its id
on the tower (§4 below).

### §5 `LOG_LEVEL`; logs under `data/logs/<app>/` (DONE)

`src/logging_setup.py` configures the whole service once:

* `LOG_LEVEL` selects `debug` / `info` / `error`, read from `.env`, no code change to switch.
* Output goes to stdout **and** a rotating file at `data/logs/corestack-lulc/app.log`
  (10 MB x 5), which is the exact path the checklist mandates. Honours a relocated
  `CORESTACK_DATA_DIR`.
* File logging is best-effort: an unwritable data dir degrades to stdout with a warning rather than
  killing startup.
* **Redaction lives in the formatter**, not at call sites. A credential cannot leak through an
  argument, an exception message or a dict repr, and nobody has to remember the rule when adding a
  log line later. Verified: `token=...` and `password=...` come out as `***`.
* A request middleware logs one line per request with status and duration; at `debug` it adds the
  query string. Exceptions are logged with a traceback instead of only reaching stderr.
* uvicorn's loggers are re-pointed at the same handlers so its startup and error lines land in the
  file. `uvicorn.access` is muted, because our own line is strictly richer and two lines per request
  is noise.

**Scope note.** Converting prints was smaller than first estimated. Only `refine.py` is on the
service path, and its 28 prints became `log.debug` (per-child and per-year detail), `log.info`
(outcomes) or `log.warning` (the missing-residual-child caveat). `train_base.py`, `eval_base.py` and
`temporal_eval.py` turned out to be standalone offline scripts that nothing imports and that carry
their own `__main__`, so they keep `print()`, like `scripts/` and `week*/`. The original "~84
prints" figure counted CLI self-tests that were never service output.

### §6 Backend and frontend in one container (DONE, already was)

One compose service, one port. The backend serves `src/static/` directly. No separate frontend
service anywhere. Nothing needed doing.

### §7 Frontend API base from `.env`, relative default (DONE)

See §3.3 for the fault this fixed. Implementation:

* `config.API_BASE_URL` (empty = relative).
* `GET /config.js` emits `window.CORESTACK_CFG`, declared **before** the static mount so the route
  wins over any file of the same name, with `Cache-Control: no-store` so it tracks the `.env`.
* `app.js` has a single `api(path)` helper, the one place a path becomes a URL. **51 call sites**
  routed through it; zero bare `/api/` literals remain.
* The default is **relative**, which is what the checklist asks for: *"Default is relative base
  (`/` or `/api`) for same-container deploy."*

`/config.js` also reports `airflow: true|false`, so the page knows whether to take the DAG path
without needing a probe request.

### §8 Architecture diagram (DONE)

`docs/architecture.md` carries the required mermaid diagram and shows every element the checklist
lists: browser to frontend Docker; `AIRFLOW_API_BASE` set to Airflow-STACD, empty to local compute;
output to `data/`; FileBrowser over `data/`; the three mounts; `data/logs/corestack-lulc/`; the
(currently absent) central Postgres; retention modes; and GEE as the external system.

It also documents how a retrain rides the export conf, since that is the part a new operator would
otherwise get wrong.

### §9 Postgres on the central server (DONE in week 18)

*24 Sep: N/A, no database.* Week 18 added `users` and `projects`, so it applies now and is built:
`DATABASE_URL=postgresql://...` on the tower (`src/db.py` maps it to the psycopg 3 driver explicitly,
since SQLAlchemy 2.1 changed the default). Checked against a throwaway Postgres with the rebuilt image:
tables created, sign-in rules enforced. On the tower it needs the central server's connection string.

### §10 `outputs.yaml` (DONE)

At repo root, validated: every mode legal, every `delete` carries `ttl_days >= 1`.

The framing matters and is stated in the file itself. **A run's actual product is a GEE asset plus a
STAC Item**, governed in Earth Engine, not a file under `data/`. So `outputs.yaml` covers the state
that produced it:

| Path | Mode | Why |
|---|---|---|
| `data/catalogue/` | `public` | the model zoo, meant to be shared; its own git repo |
| `data/examples/` | `private_persistent` | the user's own training polygons |
| `data/hierarchy.json` | `private_persistent` | the live class tree |
| `data/op_log.json` | `private_persistent` | feeds provenance and the STAC op_sequence |
| `data/active_base.json` | `private_persistent` | which base scheme is live |
| `data/merge_rules.json` | `private_persistent` | merge/relabel rules applied at inference |
| `data/refine/` | `private_persistent` | cached training tables, expensive to rebuild |
| `data/logs/` | `private_persistent` | rotating, so self-capping |
| `data/jobs/` | `delete`, 7 days | job bookkeeping, worthless once read |
| `data/inputs/` | `private_persistent` | ground-truth inputs for offline scripts |
| `data/projects/` | `private_persistent` | **added week 18**: each user's projects, runs and GeoTIFFs; a public one is served read only |

### §11 Front page and demo video (FRONT PAGE BUILT; video pending sir's review)

**Update 3 Oct.** The front page exists: `/` is `src/static/landing.html` (the project story, how it
works in three steps, sign-in, public projects) and the tool moved to `/app`. The video slot reads
`INTRO_VIDEO_URL` (a YouTube link or an mp4) and shows a placeholder until it's set. The walkthrough
flow for the video is written (`week19/walkthrough_flow.md`, 14 chapters, about 6 to 7 minutes) and
goes to sir for review before recording, as he asked; the manual deck that pairs with it is in Canva.
What's left: sir's review, the recording, `INTRO_VIDEO_URL` on the tower, and the review date and notes
in the README, which the checklist asks for.

*The 24 Sep text, kept for the record:*

**This item is new.** It did not exist when we audited the checklist, and it is the only thing here
that nobody has begun. It asks for two things:

1. **A landing page at `/`** carrying the project story, then sign-in or enter-app. Ours drops the
   visitor straight into the map tool, which the checklist explicitly rules out
   (*"not a bare form"*).
2. **One demo video**, serving as both brief manual and tutorial, embedded or prominently linked on
   that front page, and **reviewed and approved**, with the date and notes recorded in the issue or
   README.

The acceptance criterion is:

> *"A new visitor opens the service URL, understands the project from the front page and the video,
> then can follow the same steps in the UI. The demo video has been reviewed and approved."*

**Sequencing note.** The landing page is specified as "project story, then sign-in", so it assumes
§4 exists. Building it before the SSO shape is known means building it twice. The **video is
independent** and can be recorded against the app as it stands today, so that half need not wait.

---

## 3. Deep dives

### 3.1 The model zoo: why the live site showed four models

The first diagnosis was that `data/catalogue` is gitignored (the zoo is its own git repo), so a
fresh deploy clone starts with no cards and `catalogue.backfill()` regenerates only the handful it
can rebuild from local artifacts. That was a plausible mechanism that happens to produce the same
number. **It was not the real cause.**

The real chain:

1. On **29 July 2026**, a publish committed `artifacts/mc_biomass_aez8_v1.joblib` (**553 MB**) into
   the zoo repository.
2. GitHub hard-rejects any push containing a file over 100 MB, so **every publish since then
   failed**. Eight commits sat stranded locally.
3. The remote froze at exactly **four model cards**: `mc_barren_v1`, `mc_greenery_v1`, `mc_root_v1`,
   `mc_worldcover_base_v1`. That is the number on the live site.

The artifact turned out to be an **orphan with no card referencing it**, and byte-identical
(SHA-256 verified) to a copy already on disk at `data/refine/biomass_aez8.joblib`. Pure liability.

Purged with `git filter-repo` from all fourteen commits:

| Measure | Before | After |
|---|---|---|
| Zoo working tree | 666 MB | 395 KB |
| `.git` | 138 MB | 199 KB |
| Largest blob in history | 528 MB | 17 KB |
| Model cards on the remote | 4 | 11 |
| Commits | 14 | 14 (all preserved) |

Two backups were taken before the rewrite, both with full pre-rewrite history:
`C:\Users\mrsal\Downloads\zoo_backup_20260923\catalogue` and a session scratchpad copy.

Publishing works again. The zoo is now small enough that a deploy box can simply clone it into its
`data/` mount, which is the approach sir advised and which **needs no code change**, because
`CATALOGUE_DIR` already resolves through `config.project_path("data/catalogue")` and therefore
honours `CORESTACK_DATA_DIR`. Verified against a simulated host data dir: 11 models, 15 datasets.

```bash
# on the deploy host
rm -rf /srv/corestack-lulc/data/catalogue
git clone https://github.com/salil-123/zoo_database.git /srv/corestack-lulc/data/catalogue
docker compose -f docker-compose.hub.yml restart lulc
```

**Belt and braces.** Independently of the above, `data/catalogue_seed/` (35 files, 160 KB) is now
committed to the app repo and `catalogue.seed_from_bundled()` copies anything missing into the live
catalogue on startup, never clobbering a card edited on that box. So a plain `git pull` already
gets a deployment to 11 models even before the zoo is cloned.
`scripts/sync_catalogue_seed.py` refreshes the seed so it cannot drift: byte-compares to avoid git
churn, prunes deleted cards, skips artifacts over 50 MB.

**Still missing: a guard.** The zoo's own `.gitignore` carries `!artifacts/*.joblib`, which is what
let a 553 MB file in. Nothing currently stops it happening again on the next publish of a large
model. A size check at publish time would close it.

### 3.2 Retraining through the export path

The instruction was explicit: no second DAG to set up. It did not need one.

The deployed DAG's `op="export"` branch is a thin HTTP call. It POSTs the run conf to
`/api/export-asset`, and that handler already filters the body through `_EXPORT_KEYS`. Adding two
keys to that set was enough:

```jsonc
{ "retrain": { "node": "greenery", "algo": "logreg" },
  "export":  false }          // false = train and stop
                              // omit  = train, then classify + export
```

Implementation detail:

* `_do_retrain(node, ...)` was factored out of `/api/retrain`, so the direct endpoint and the export
  path share **one** implementation. `/api/retrain` is unchanged for any existing caller.
* `_run_export` trains first when `retrain` is present, then classifies and exports with the fresh
  model unless `export` is false.
* Tolerant of what the pipeline actually sends: `retrain` as a dict **or** a JSON string, `export`
  as `false` / `"false"` / `"0"` / `"no"` (`_truthy`). A bad spec returns a readable 400, not a 500.
* The response carries both blocks: `{"retrain": {...}, "export": {...} | null}`.
* Frontend: the Retrain button uses `triggerDagAndPoll({retrain, export: false})` when Airflow is
  wired, else posts `/api/retrain` inline. The DAG reply carries only run state, so it reads metrics
  back off the model card the retrain just minted, and refreshes the tree. `formatReport` accepts
  both shapes (sklearn's `f1-score`, the card's `f1`).

Why this is safe: the training always runs **inside the service container**. The DAG only drives it
over HTTP. So the weights, the class hierarchy and the zoo cards cannot drift apart.

Verified against the real `_EXPORT_KEYS` filter with a stubbed trainer across four cases:
retrain-only; a fully stringified conf; retrain-then-export in one job; and a plain export, which
must **not** trigger training. All four pass against the **unmodified** DAG file.

### 3.3 The blank page in the handed-over image

`src/static/index.html` loaded `/style.css` and `/app.js`. Root-absolute. Served behind a
reverse-proxy subpath, the browser asks the **host root** for them, gets 404s, and renders nothing.
The same fault ran through 55 `fetch("/api/...")` calls.

Fixed as described in §2.7. One related hazard was fixed at the same time: **Leaflet and
leaflet-draw were loading from the unpkg CDN**, which the IIT Delhi campus proxy can block. That
would leave a dead map on the deploy host for a different reason but with the same symptom. Both
libraries plus their eight sprite images are vendored under `src/static/vendor/`, so the page now
has **no external asset dependency at all**. The Esri basemap necessarily stays remote, since it is
a tile service rather than a static asset.

### 3.4 The DAG was firing on almost everything

Found while working on the above. `runClassify()` had **twelve call sites and eleven were
automatic**: after drawing a box, changing the preset, finishing base onboarding, resetting,
applying a model or a card, rule-splitting, retraining, merging, un-merging, resuming a project, and
changing the inference year.

Every one of those triggered a full DAG run that **exported a GEE asset**. That is where the
accumulated junk under `EE_ASSET_ROOT` came from.

Now the Run button is the only path to the DAG. The eleven spots call `markStale()` instead: the map
is left exactly as it was, and the status line names the change and asks for a Run. A retrain is
also **one** DAG run now instead of two, since it no longer chains into a classify.

### 3.5 Smaller changes

* **Marker draw tool off.** It *was* wired end to end: `sampling.interior_points()` has an explicit
  branch where a Point "passes straight through as a single sample". But it contributes one pixel
  against a polygon's ~30, so it never earned its toolbar slot. One-line revert if wanted
  (`marker: true` in the `L.Control.Draw` config). Side benefit: the "Polygon captured" status line
  is now always accurate.
* **Map attribution removed** on request. The basemap is Esri World Imagery, whose terms ask for
  attribution, so there is a comment at the call site: if this goes public-facing, credit them in
  the page chrome instead.
* **`contributions.py` deleted.** Phase-5 interface stubs where every function raised
  `NotImplementedError`. What it sketched is done differently now (markings through `examples.py`,
  publishing through `zoo_git.py`), so it only misled.
* **Zoo git identity.** A fresh container has no git identity, so the first publish died with an
  uncaught 500 from `git commit`. `zoo_git.init_local()` now sets a repo-scoped identity when none
  exists, leaving the host's global config alone.
* **`/api/publish` error handling.** Returns clean JSON on failure instead of a plain-text 500 the
  frontend cannot parse.
* **`WATER_MIN_FORTNIGHTS` removed.** Week 15 showed a single global persistence threshold cuts
  spurious water 15% to 2% but takes F1 0.65 to 0.58 and small-water recall 0.30 to 0.11 with it,
  trading away exactly the water we care about.
* **Path anchoring.** `catalogue.py`'s `CATALOGUE_DIR`, `SEED_DIR`, `EXAMPLES_DIR` and `SCHEMA_DIR`
  used a raw `ROOT / "data"`, so a relocated `CORESTACK_DATA_DIR` was silently ignored. They go
  through `config.project_path()` now. The same latent issue still sits in `backend._ROOT` and
  `validate_ops._REFINE`; harmless today, worth a sweep later.

---

## 4. Outstanding

*Rewritten 3 Oct. The 24 Sep decisions on SSO and the front page were settled by building them.*

### To get week 18 onto the tower, in order

| # | Step | Who | Notes |
|---|---|---|---|
| 1 | Push the staged week 18 code | us | committed locally, not on GitHub yet |
| 2 | Register **our own** Google OAuth client | us | **done 3 Oct**: web client in `modern-mystery-398416`, origins `https://www.cse.iitd.ernet.in` + `http://localhost:8000`; id in the laptop `.env`, Google mode checked locally |
| 3 | Bump `VERSION`, rebuild the image, push `:latest` and the version tag | us | closes §3 too; `DEPLOY_GUIDE.md` §12.1 |
| 4 | Tower `.env`: `GOOGLE_CLIENT_ID`, `SESSION_SECRET`, `DATABASE_URL`, `SERVICE_TOKEN` | us + tower admin | the Postgres connection string comes from the central server |
| 5 | Airflow side: `CORESTACK_SERVICE_TOKEN` (same value), and the STACD pipeline forwards `X-Service-Token` and `project_id` | Saharsh | without `project_id` a DAG run classifies the global scheme, not the project's |
| 6 | `git pull`, `docker compose -f docker-compose.hub.yml pull && up -d`, then the two `curl` checks in DEPLOY_GUIDE §12.2 | us | `/api/auth/me` shows the client id; a write without a cookie gets 401 |
| 7 | Video: sir reviews the flow, we record, set `INTRO_VIDEO_URL`, note the review in the README | us + sir | §11 |

### Registering our own OAuth client (step 2)

1. In **our** Google Cloud project (not Susmit's): *APIs & Services → OAuth consent screen*. User type
   **Internal** if the project sits in the IIT Delhi Workspace (sign-in is then limited to institute
   accounts); otherwise **External**. App name "Core Stack LULC", support email, scopes: only the basic
   `openid`, `email`, `profile`. An External app stays in "Testing" (only listed test users can sign
   in) until it's published; basic scopes don't need Google's sensitive-scope review.
2. *Credentials → Create credentials → OAuth client ID → Web application*.
3. **Authorized JavaScript origins**: the exact origin users open, scheme + host (+ port), no path.
   If the app sits under `https://www.cse.iitd.ernet.in/<path>/` like Susmit's drone app, the origin is
   `https://www.cse.iitd.ernet.in`. Add `http://localhost:8000` for testing. No redirect URI is needed.
4. Copy the client id into the tower's `.env` as `GOOGLE_CLIENT_ID`. It is public by design (it ships to
   the browser); there is no client secret in this flow, so nothing secret goes in git.

### Smaller items, still open

| Item | Effort |
|---|---|
| Size guard on zoo publish (the 553 MB lesson, §3.1) | small |
| Delete one stray GEE asset from a test run | one command |
| Sweep the last raw paths: `backend._ROOT`, `validate_ops._REFINE` | small |
| Weights in git (§1): keep the convenience, or move to `fetch_models.sh`? | needs a decision |
| `docs/architecture.md` still says SSO and Postgres are "not used yet"; `docs/cluster_checklist.md` has no row for §11 | doc touch-up |

**Done since 24 Sep:** scikit-learn pinned to 1.8.0 in both requirements files (no more unpickling 1.8
models with 1.9); GeoTIFF size cap lowered to 250 km² after a measured Earth Engine memory failure at
368 km² (week 19).

---

## 5. How each claim was checked

Verification actually run, not asserted:

* **Fresh-clone test.** Cloned the committed tree into an empty directory with no `data/catalogue`,
  no logs and no weights in place, and started it: **11 models, 15 datasets**, page and every asset
  200, only the pre-existing `favicon.ico` 404.
* **In the container.** Brought the stack up under Docker: `/app/models` and `/app/data` mounted
  separately, base model resolved to `/app/models/model_pooled.joblib` and loaded, `/app/data/refine`
  holding only the `*_train.csv` tables, zoo 11/15, page and all eight assets 200.
* **Logging.** `LOG_LEVEL=debug` showed query strings where `info` did not, with no code change, and
  the log file survived a `--force-recreate`. That is §5's acceptance test verbatim.
* **Redaction.** Confirmed `token=` and `password=` render as `***`.
* **Retraining.** Four routing cases against the real `_EXPORT_KEYS` filter with a stubbed trainer,
  including the negative case.
* **Mount resolution.** Confirmed per-file: `models/` wins where present, `data/` still serves
  anything not yet migrated, so a half-migrated box works.
* **Compose.** `docker compose config` validates; all three mounts resolve with the defaults.
* **Dependencies.** Every third-party import across `src/` and `config.py` checked against what is
  already installed. **Nothing new**, so the deps-only image needs no rebuild.
* **Zoo.** Remote verified after the push: 11 model cards, 15 datasets, 9 artifacts, largest blob
  17 KB.

**One caveat on the container runs.** The local Docker container kept restarting every ~20 seconds
during testing. That is not a service fault: exit code 0, `RestartCount: 0`, no OOM. Docker Desktop
was not running, so each `wsl docker` command briefly woke the WSL distro, which then shut down and
took the container with it. Readings above were taken in the healthy windows and are consistent with
the host-run results. Starting Docker Desktop fixes it.

---

## 6. Commits

*As of 24 Sep.* Since then: five docs commits up to `eec34e1` (pushed), and the week 18 + 19 work, staged
for one commit that still has to be pushed (§4, step 1). The six on `main` at the time, all pushed:

```
ee7f6ad  UI: the DAG only fires on Run; drop the marker tool and the map attribution
4038441  Move trained weights onto the models/ mount
13493f6  Deploy: three mounts, outputs.yaml, architecture diagram, checklist sign-off
ca393e5  Frontend: relative paths, vendored Leaflet, drop the water/mining buttons
b46c863  Backend: logging, retrain via the export path, models/ anchor
25db536  Ship the model zoo with the repo; drop the contributions.py stubs
```

Zoo repo: history rewritten to remove the 553 MB blob, force-pushed, now at `8916fb6`.

---

## 7. Updating the deployment

**3 Oct: this time an image rebuild is needed**, because week 18 added dependencies. Follow
`deploy/DEPLOY_GUIDE.md` §12 (rebuild, sign-in, database, Airflow token). The `git pull` routine below
holds again for every later code-only update. *The 24 Sep routine:*

```bash
cd /path/to/corestack-lulc
git pull
docker compose -f docker-compose.hub.yml restart lulc
curl http://<host>:8000/api/health
```

Hard-refresh the browser the first time (Ctrl+Shift+R). The `?v=` cache-busters were bumped, but a
stale cached `index.html` can still hold the old references.

Verify the fix landed: the Model Zoo should list **11** models, and the Run panel should have no
water or mining buttons.

Optional `.env` additions this work introduced:

```bash
LOG_LEVEL=info          # debug | info | error
API_BASE_URL=           # empty = relative; only set to point the UI at another backend
# CORESTACK_CODE_HOST=/srv/corestack-lulc/code
# CORESTACK_MODELS_HOST=/srv/corestack-lulc/models
# CORESTACK_DATA_HOST=/srv/corestack-lulc/data
```

---

## 8. Related documents

| File | What it holds |
|---|---|
| `docs/cluster_checklist.md` | the sign-off table, per-item notes |
| `docs/cluster_readiness_tasks.md` | the working breakdown, phase by phase, with what was verified |
| `docs/architecture.md` | the §8 mermaid diagram and the compute-trigger explanation |
| `outputs.yaml` | §10 retention policy |
| `models/README.md` | the weights layout and how to migrate |
| `master_document.md` | the full week-by-week build narrative |
