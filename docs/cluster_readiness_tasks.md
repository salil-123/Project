# Cluster readiness — plan

Goal: pass the CoRE Stack **Cluster Service Checklist**
(https://docs.core-stack.org/server/cluster-service-checklist/, linked from `/infra/tower-services/`)
and fix what's visibly broken on the live site. Week-15 water stays as experiments; untouched.

## Decisions taken
- **No new DAG, no new op.** Retrain routes through the *existing* `op="export"` →
  `POST /api/export-asset` path. Retrain-only is that same call with `export: false`.
- **Google SSO (checklist #4) is parked** pending further advice. Postgres (#9) parks with it —
  its only consumers are the users/audit tables that auth creates, and #9 reads
  *"N/A if service has no database"*. We leave the seams (env var documented, checklist row marked
  pending) so it drops in later without rework.

## Scoreboard — **8 of 10 done, 2 parked**

| # | Item | Status | Phase |
|---|------|--------|-------|
| 1 | Separate `code/` `models/` `data/` mounts | **done** (the file move is yours to trigger) | P4 |
| 2 | `AIRFLOW_API_BASE` set → Airflow, empty → local | **pass** — already correct | — |
| 3 | Deps-only image in a registry | **done** — `VERSION` added | P5 |
| 4 | Google SSO | **parked** pending advice | — |
| 5 | `LOG_LEVEL` + logs at `data/logs/<app>/` | **done** | P2 |
| 6 | One container, backend serves the UI | **pass** — already correct | — |
| 7 | Frontend API base from env, relative default | **done** — fixed the blank page | P1 |
| 8 | Architecture diagram | **done** | P5 |
| 9 | Central Postgres | **N/A** until #4 lands | — |
| 10 | `outputs.yaml` | **done** | P5 |

Plus, outside the checklist: the **model-zoo bug** (only 4 models live) — P0 — and removing the
**water + mining buttons** and routing **retrain through the existing DAG** — P1 and P3.

Ordering logic: P0 first (visibly broken today, ~20 min); then each file edited in exactly one phase
— P1 sweeps the frontend, P2 sweeps `src/*.py`, P3 is backend-only, P4 moves paths, P5 documents the
settled result.

---

## P1 — Frontend: relative paths + UI trim  — **DONE, verified in-browser**

**The blank-page bug sir hit.** `index.html` loaded `/style.css` and `/app.js` — root-absolute, so
behind a reverse-proxy subpath the browser asked the *host root*, got 404, and rendered nothing.

- [x] `index.html`: every href/src now relative (`style.css`, `app.js`, `vendor/…`); `?v=` bumped.
- [x] `app.js`: one `API_BASE` + `api(path)` helper — the single place a path becomes a URL. Default
      is **relative**; `config.js` (served from `API_BASE_URL` in `.env`) can override it.
      **51 call sites** routed through it; zero bare `/api/` literals left.
- [x] `config.py`: `API_BASE_URL` (empty = relative). `backend.py`: `GET /config.js` emits
      `window.CORESTACK_CFG`, declared *before* the static mount so the route wins, `no-store` so it
      tracks the `.env`.
- [x] **Vendored** Leaflet 1.9.4 + leaflet-draw 1.0.4 (js/css + 8 sprite images) into
      `src/static/vendor/` — they came from unpkg, which the campus proxy can block, leaving a dead
      map on the deploy host. No CDN dependency remains. (The Esri basemap is a tile *service*, not a
      static asset, so it necessarily stays remote.)
- [x] Removed the water row (`waterDate`, `runWater`, `runWaterFreq`) and mining row (`runSegment`,
      `dlSegment`): markup, **88 lines** of handlers, and the `.water-row` CSS. No dangling refs.
      Backend `/api/water`, `/api/water-frequency`, `/api/segment` kept — STACD and the experiments
      use them, and unused routes cost nothing.
- [x] **Verified** by running the app and loading it in a browser: map renders from vendored Leaflet,
      all 51 API calls and every asset return 200, console clean, no water/mining buttons. The only
      404 is the pre-existing `favicon.ico`.

## P2 — Logging  — **DONE, verified**

- [x] `src/logging_setup.py` — one `configure()` reading `LOG_LEVEL` (`debug|info|error`), writing to
      stdout **and** a rotating file at `data/logs/corestack-lulc/app.log` (10 MB x 5), the exact path
      the checklist mandates. Honours a relocated `CORESTACK_DATA_DIR`. File logging is best-effort:
      an unwritable data dir degrades to stdout with a warning instead of killing startup.
- [x] **Redaction** built into the formatter, so a credential can't leak through an arg, an exception
      message or a dict repr — one funnel, not per-call discipline. Verified: `token=…`/`password=…`
      come out as `***`.
- [x] Request middleware in `backend.py`: one line per request with status + duration; at **debug**
      the query string too. Exceptions logged with a traceback rather than only hitting stderr.
- [x] uvicorn's loggers re-pointed at the same handlers so its startup/error lines land in the file;
      `uvicorn.access` muted because our middleware line is strictly richer (duration + redaction)
      and two lines per request is noise.
- [x] `config.LOG_LEVEL`; `.env.example` documents the three levels and the tail commands.
      `data/logs/` gitignored — host state, not source.
- [x] **Scope call:** only `refine.py` is on the service path, so its **28 prints** became
      `log.debug` (per-child/per-year detail) / `log.info` (outcomes) / `log.warning` (the missing
      residual-child caveat). `train_base.py`, `eval_base.py`, `temporal_eval.py` turned out to be
      standalone offline scripts — nothing imports them, they have their own `__main__` — so they
      keep `print()`, like `scripts/` and `week*/`. That's 28 converted, not the ~84 first estimated;
      the rest were always CLI self-tests.
- [x] **Verified** end to end: `LOG_LEVEL=info` hides debug lines, `LOG_LEVEL=debug` shows query
      strings, the file lands at the mandated path, no code change between the two.
- Note: no extra compose mount for logs — the existing `.:/app` bind already puts `data/logs` on the
  host. **P4** restructures volumes into the three checklist mounts, which covers it properly.

## P3 — Retrain through the existing export path  — **DONE, verified**

Why it works with zero DAG change: the deployed DAG's `op="export"` branch is a thin
`POST {api_base}/api/export-asset` with the run conf as the JSON body, and that handler already
filters the body through `_EXPORT_KEYS`. Training still runs inside our container, so the model,
hierarchy and zoo cards stay consistent — the DAG is only an HTTP driver.

- [x] `_do_retrain(node, ...)` factored out of `/api/retrain` — one implementation, two entrypoints.
      `/api/retrain` now delegates to it, so the direct call is unchanged for any existing caller.
- [x] `_EXPORT_KEYS` gains `retrain` + `export`. `_run_export` trains first when `retrain` is present,
      then classifies + exports with the fresh model; `export: false` makes it **retrain-only** —
      still `op="export"`, still the same DAG.
- [x] Tolerates how the pipeline actually sends things: `retrain` as a dict **or** a JSON string,
      `export` as `false` / `"false"` / `"0"` / `"no"` (`_truthy`). Bad specs give a 400 with a
      readable reason instead of a 500.
- [x] `/config.js` now also reports `airflow: true|false`, so the page knows which path to take
      without a probe request.
- [x] Frontend Retrain button: rides `triggerDagAndPoll({retrain, export:false})` when Airflow is
      wired, else posts `/api/retrain` inline. The DAG reply carries only run state, so it reads the
      metrics back off the model card the retrain just minted and refreshes the tree.
      `formatReport` now accepts both shapes (sklearn's `f1-score`, the card's `f1`).
- [x] **Verified** with the real `_EXPORT_KEYS` filter and a stubbed trainer, covering: retrain-only,
      a fully stringified conf, retrain+export in one job, and a plain export (which must *not*
      trigger training). All four pass against the **unmodified** DAG file.

## P4 — Mounts / `models/`  — **DONE (migration step left to you)**

The wrinkle I hadn't seen when planning: `data/refine/` mixed **weights** with **326 MB of sampled
`*_train.csv` tables**, and every zoo card's `artifact.path` hard-codes the `data/refine/...`
spelling. Those card paths are *data*, so rewriting them is a migration of the zoo itself. Hence a
resolver rather than a rename.

- [x] `config.MODELS_DIR` (`CORESTACK_MODELS_DIR`, default `<root>/models`), and `project_path`
      now understands a leading `models/` the same way it understands `data/`.
- [x] **`config.model_path(rel)`** — the compat seam: resolves a weight under `models/` if it's
      there, else the legacy `data/` home, else the `models/` path so *new* writes land in the new
      home. Per-file, so a half-migrated box works. Cards keep saying `data/refine/...` and keep
      resolving.
- [x] Every load site repointed: `infer` (base, softvote, per-node classifiers, fortnight water),
      `refine` (base, worldcover, weight writes), `catalogue` (base cards, per-node joblibs, archive).
- [x] **Split the two jobs that shared `data/refine/`**: `REFINE_DIR` is now weights only, and
      `TRAIN_CACHE_DIR` keeps the regenerable `*_train.csv` tables under `data/` where the checklist
      wants data.
- [x] `catalogue.py` anchored through `config.project_path` — `CATALOGUE_DIR`, `SEED_DIR`,
      `EXAMPLES_DIR`, `SCHEMA_DIR` used raw `ROOT / "data"`, so a relocated `CORESTACK_DATA_DIR`
      was silently ignored. (Same latent bug still sits in `backend._ROOT` and
      `validate_ops._REFINE` — harmless today, worth a sweep later.)
- [x] `scripts/migrate_models.py` (`--dry-run` / `--keep`) — moves **weights only**, 15 files.
- [x] Both compose files mount three dirs separately, defaulting to this checkout so a laptop needs
      no setup: `${CORESTACK_CODE_HOST:-.}:/app`, `${CORESTACK_MODELS_HOST:-./models}:/app/models`,
      `${CORESTACK_DATA_HOST:-./data}:/app/data`. `.env.example` documents both the host dirs and
      the in-container anchors. `models/README.md` explains the layout.
- [x] **Verified**: with nothing migrated the app boots and loads the real base model from `data/`;
      with a populated `CORESTACK_MODELS_DIR` it reads from there per file while unmigrated weights
      still fall back. Zoo still lists 11 models, `/api/health` clean.
- [ ] **Not run: the actual move.** `data/refine/*.joblib` and `data/model_*.joblib` are **tracked in
      git**, so moving them restructures the repo and changes what a deploy clones — your call, not
      mine. The code works either way; when you want it: `python scripts/migrate_models.py`
      (then `git add models/ && git rm --cached` the old paths).

## P5 — Docs & policy  — **DONE**

- [x] **`outputs.yaml`** at repo root — every path under `data/` tagged `public` /
      `private_persistent` / `delete` (+ `ttl_days`), validated. The framing matters: a run's actual
      product is a **GEE asset + STAC Item**, governed in Earth Engine, *not* a file under `data/`.
      So the file covers the state that produced it: zoo `public`, user examples + scheme state
      `private_persistent`, job bookkeeping `delete` after 7 days.
- [x] **`docs/architecture.md`** — the required mermaid diagram (browser → frontend Docker →
      Airflow-STACD when `AIRFLOW_API_BASE` is set, else inline → GEE asset + STAC → `data/` →
      FileBrowser), with the three mounts, the logs dir, the parked Postgres, and a section on how
      retrain rides the export conf.
- [x] **`VERSION`** (0.9.0) so the published image can carry a pinned tag instead of only `latest`.
- [x] **`docs/cluster_checklist.md`** — the sign-off table with per-item notes. **8 done, 2 parked.**
- [x] README: a *Cluster deployment* section (mounts, logging, API base, outputs) and the
      retrain-rides-the-same-DAG note; structure block updated for `models/`, `outputs.yaml`,
      `logging_setup.py`.

## P0 — Model zoo: only 4 models live  — **DONE, verified**

Root cause confirmed: `.gitignore:25` excludes `data/catalogue/` (the zoo is its own git repo), so a
fresh deploy clone had **zero** cards and `catalogue.backfill()` regenerated only the ~4 it could
rebuild from local artifacts.

- [x] **`git add data/catalogue_seed/`** (35 files, 160 KB) — it was *untracked*, so the already-written
      `catalogue.seed_from_bundled()` shipped nothing. That was the actual fix.
- [x] `scripts/sync_catalogue_seed.py` — refreshes the seed from the live zoo, skips artifacts over
      50 MB, prunes deleted cards, byte-compares so git sees no churn on a no-op run.
- [x] **Verified** against a simulated fresh checkout (no `data/catalogue`): seeds 35 files →
      **11 model cards, 15 dataset cards**, index rebuilt.
- Note: the seed is *complete* — 11/11 models, 15/15 datasets. The only live artifact it omits is
  `mc_biomass_aez8_v1.joblib` (553 MB), which turns out to be an **orphan with no card** left over
  from an earlier run, so nothing is missing from the zoo. (Earlier draft of this plan claimed the
  biomass card ships without weights; that was wrong.)
- `index.json` is deliberately not seeded — `seed_from_bundled()` rebuilds it after copying, so it
  describes what actually landed on that box.
