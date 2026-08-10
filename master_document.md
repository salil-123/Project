# Core Stack LULC — Master Document

The single source of truth for this project: what it is, what's been built (week by
week), how the live system fits together, and the week-6 work ahead. Keep this current
as we go — it's the tracking doc.

Project home: https://core-stack.org/

---

## 1. What this project is

A web tool that lets a user paint a **land-use / land-cover (LULC) map** over any area of
India at **10 m**, then **grow their own class scheme** on top of it — split a class into
finer ones, add a brand-new class, merge/relabel across models — by handing the tool a few
example polygons and retraining on the fly. Every trained model and dataset is recorded as a
**card** in a git-backed **model zoo** so others can find one for their area and keep
refining it.

Two ideas hold it together:

- **A canonical class spine** (`hierarchy.json`) starting from 4 base classes — *greenery,
  water, built_up, barren* — editable at every level.
- **Embeddings as features.** We never touch raw imagery at inference. Each point is a
  pre-learned vector: **Alpha Earth** (64-d, Google Satellite Embedding, server-side in
  Earth Engine, free, India-wide) and optionally **Tessera** (128-d, downloaded tiles, only
  usable for 2024 over India). A linear model (`StandardScaler → LinearSVC`) on top is cheap
  to train and — because it's linear — replays exactly as band math inside Earth Engine, so a
  whole bbox classifies server-side as map tiles with nothing downloaded.

---

## 2. The live system (current architecture)

Everything live sits at the repo root: `src/`, `data/`, `config.py`, `tessera_fast.py`.
Run it from the repo root:

```
uvicorn backend:app --reload --app-dir src      # then open http://127.0.0.1:8000/
```

### Data / model flow

```
GEE assets ─► polygons ─► diverse subset ─► Tessera tiles ─► dual-embedding master CSV
                                                                   │
                              ┌────────────────────────────────────┴───────────┐
                              ▼                                                  ▼
                    pooled AE + WorldCover                         reconciled soft-vote
                    (Realistic, default)                          (AE 0.7 + Tessera 0.3, Detailed)
                              │                                                  │
                              └───────────────► FastAPI backend ◄───────────────┘
                                                     │
                                            Leaflet web UI  +  Model Zoo (git-backed cards)
```

### Source modules (`src/`)

| File | Role |
|------|------|
| `backend.py` | FastAPI app. Loads both models, serves `/api/classify` (with `year`), the hierarchy ops (split/add/retrain), examples, save/reload, base-scheme switch, merge, the catalogue/zoo endpoints, and the static frontend. Every tree-mutating handler logs to the op-log. |
| `infer.py` | Inference. `classify_bbox_tiles` (Realistic: linear model → EE band math → map-tile URL, server-side, no download), `classify_bbox_softvote` (Detailed: AE+Tessera grid, on-demand tile download). Composites trained splits recursively, then applies merge relabels (`_apply_merges` / `_merge_ee`). Follows the active base scheme. |
| `hierarchy.py` | The class tree (`data/hierarchy.json`): seed 4 classes, `seed_from_classes` (alternate bases), split/add, validate, queries. Pure functions; only load/save touch disk. |
| `refine.py` | The refinement engine: per-node split trainers, SPLIT/ADD/relabel/hard-negatives, base-model retrain, `train_worldcover_base` (the effective WC base), balance remedies, a hierarchical-vs-flat bake-off. |
| `examples.py` | User example markings: ingest drawn/uploaded polygons, store one GeoJSON per node, sample interior pixels into an embedded training frame. |
| `catalogue.py` | The card database. Validate/write/read cards against `schema/*.json`, build `index.json`, `models_for_aoi`, `recommend_placement` (#2), `recompute_spread` (#1), mint cards from live artifacts, `backfill()`. |
| `zoo_git.py` | `data/catalogue/` as a git working tree. `publish()` commits cards + index and pushes to `ZOO_REMOTE`, stamping the contributor (#6). |
| `oplog.py` | **(wk6)** Append-only ordered log of tree-mutating ops → `data/op_log.json`. Spine for save/reload + reproducibility. |
| `merges.py` | **(wk6)** Cross-model merge rules → `data/merge_rules.json`: relabel chosen leaves into one new class (a post-inference correction layer, no retraining). |
| `sampling.py` | Shared embedding sampling: interior pixels in polygons → AE (server-side) / Tessera vectors. |
| `train_base.py`, `eval_base.py` | Train/eval the base (Realistic) model — drop junk `other`, pool extra water, balance, sweep `wc_weight`, threshold-tune as intercept shifts. Evaluated on random-India + balanced holdout. |
| `contributions.py` | Stubs only — interfaces for an evolving user-contribution store, not yet active. |
| `static/{index.html,app.js,style.css}` | Leaflet frontend: map, base-class picker, hierarchy editor, example drawing, operations panel, year picker, merge panel, save/load, full-screen Model Zoo browser. |

### The two deployed models

| | **Realistic** (default) | **Detailed** |
|--|--------------------------|--------------|
| Artifact | `data/model_pooled.joblib` | `data/model_softvote_reconciled.joblib` |
| Features | Alpha Earth (server-side) | Alpha Earth + Tessera |
| What | one LinearSVC on AE, trained on expert polygons pooled with ESA WorldCover (weighted 2×, for the real class prior) | soft-vote: prior-aware AE (0.7) + calibrated Tessera (0.3) |
| Downloads on unseen area | none (served as EE map tiles) | yes (Tessera tiles, then cached) |
| Accuracy on random India | ~0.83 | ~0.77 |
| Best for | browsing anywhere, real-world use | leaning into rare-class (water/barren) detail |

Why two: plain AE+WorldCover is the best all-around; a naive balanced AE+Tessera soft-vote
collapses to ~0.43 on random India because it ignores the greenery prior. Detailed puts the
prior back and down-weights Tessera to recover ~0.77, but still trails Realistic on real
locations. See `docs/model.md` and `docs/pipeline.md` for the full account.

### The card database (model zoo)

Two record types as JSON under `data/catalogue/` (a git repo):

- **Dataset Card** — `type: training` (labels/polygons, no embedding) or `type: inference`
  (the feature source, no labels). `kind`: polygons / ee_asset / embedding_table.
- **Model Card** — a classifier at one hierarchy node: what it `produces`, its `training`
  datasets + `inference` feature source, metrics (lifted from the held-out report), `extent`
  (a bbox for now), artifact path, lineage, `about` (description/use/limitations/evidence),
  optional per-class standard mapping (WorldCover / USDA), `zoo.published`.
- `index.json` — denormalized lookup for fast browsing / "models for my area".

Cards are minted automatically on retrain (`catalogue.register_retrain`) and seeded for
what's already on disk via `backfill()`. Publishing is an explicit git commit+push.

### Current hierarchy (live, `data/hierarchy.json`)

```
root (All land)
├─ greenery   → [tea, non_tea]        (classifier: greenery)
├─ water
├─ built_up
└─ barren     → [barren_other, mining] (classifier: barren)
```

---

## 3. Week-by-week history

| Week | Focus | Key outputs |
|------|-------|-------------|
| **2** | Build the base classifier + data pipeline. | Ground-truth polygons from 3 GEE assets (IndiaSAT, FarmForest, GT_BINARY) → diverse tile selection → Tessera download → dual-embedding `master_tessera.csv` (67,900 rows). Pooled AE+WorldCover model + reconciled soft-vote. Validation scripts (`multi_seed_compare`, `confusion_check`, `fusion_check`, `tune_softvote`). Found the **generalization gap** (94%→71% on unseen regions) — fixed by spatial diversity, not more features. |
| **3** | Turn the static base map into a **living hierarchy**. | `hierarchy.py` + `refine.py` + `examples.py` + `infer.py` compositing. SPLIT/ADD at any depth, per-node classifiers, on-the-fly retrain, 10 m overlay. Demo: greenery → crops/trees/shrubs; barren → mining (ADD). |
| **4** | **Design only** — the card schema for a model/dataset zoo. | `schema/{dataset,model}_card.schema.json` + `validate.py`, the crosswalk design, worked example cards, slides. No `src/` changes. |
| **5** | **Implement** the zoo backend + wire the frontend. | `catalogue.py` (the card DB), `zoo_git.py` (git-backed publish), backend endpoints, full-screen Zoo UI (browse, "for this area", card detail, publish). Realistic served as EE **map tiles** (crisp at any zoom, no download). Annotate editor + standard mapping. Class-balance feedback + under/oversample. "Use a model from the zoo" (`/api/apply`). Tea/non-tea proven as a test-only split (AE held-out acc **0.934**). GitHub zoo live. |
| **6** | Make it **own-and-shareable**: user control over data + scheme. | Op-log (`oplog.py`); adjustable diversity grid (#1); inference-data picker — AE 2017–2024 + Tessera-2024 (#7); contributor on publish (#6); auto recommendations (#2); save/reload hierarchy JSON (#4); **merge** / cross-model relabel (`merges.py`, #9); UI sweep (#3); effective **WorldCover base** + base-class picker (#5). All verified, incl. live GEE. See `week6/plan.md`. |
| **7** | **Apply + harden** on named stress-test sites. | Temporal robustness (`temporal_eval.py`, `year` threaded through `refine`, #3); **coverage** adequacy metric vs the AOI (`catalogue._coverage`, #4); **pre-execution** JSON validator (`validate_ops.py`, `POST /api/hierarchy/validate`, #5); stress-test sites as presets + acacia ingestion (#7/#9/#11); WorldCover-direct analysis (#2); Tessera-as-choice note (#6). See `week7/plan.md`. |

Per-week detail lives in each `weekN/plan.md` (weeks 5–6 have the fullest changelogs) and the
`docs/` folder (`pipeline.md`, `model.md`).

### Key facts carried in memory (verify before relying on)
- **Tessera** is only usable for **2024 over India**; tile downloads are costly. Don't lean
  on it to fix accuracy.
- The **generalization gap** is closed by **data diversity** (spread), not by adding Tessera.
- EE access: project/user configured in `.env` + `config.py`; some GT assets readable, some
  blocked/missing.

---

## 4. Week 6 — delivered

Source: `week6_instructions.txt` (11 asks + a tip). Each non-deferred ask is built, verified
(including live GEE), and recorded below. Full build log: `week6/plan.md`; approved plan:
`(internal planning notes)`.

| # | Ask | What shipped | Key files / endpoints |
|---|-----|--------------|------------------------|
| 11 | Persist the operation sequence | Append-only op-log of every tree-mutating action | `oplog.py` → `data/op_log.json`; logged in split/add/retrain/apply/merge/base_select |
| 1 | User-adjustable diversity grid | Recompute a dataset's spatial-diversity at a chosen grid cell | `catalogue.recompute_spread`; `GET /api/cards/{id}/spread?cell=`; `spreadCell` control |
| 7 | Pick the inference data | Inference-data picker: Alpha Earth **2017–2024**, Tessera locked 2024; same model re-sampled at the chosen year | `GET /api/inference-options`, `year` on `/api/classify`; UI year dropdown |
| 6 | Contributor on publish | Prompt for GitHub handle / email (remembered), stamped on published cards | `zoo_git._mark_published(contributor=)`; `/api/publish`; `askContributor()` |
| 2 | Placement recommendations | Auto-derived "apply after `<node>` (WorldCover: …)" from card metadata, AOI-aware | `catalogue.recommend_placement` / `_worldcover_for_class`; on `GET /api/cards/{id}` |
| 4 | Save / reload the scheme | Download hierarchy + op-log as JSON; reload validates, rebinds classifiers, reports missing | `GET /api/hierarchy/export`, `POST /api/hierarchy/import`; UI download/upload |
| 9 | Merge / cross-model relabel | Relabel chosen leaves (from different models) into one new class — a post-inference correction layer, no retraining | `merges.py` → `data/merge_rules.json`; `infer._apply_merges` + `_merge_ee`; `GET/POST/DELETE /api/merge`; Merge panel |
| 3 | UI glitch sweep | Consolidated detail-pane wiring to event-delegation; full live click-through; index confirmed consistent | `static/app.js` (removed `wireDetail`) |
| 5 | Base-class picker | IndiaSAT-4 or an **effective WorldCover base** (7 well-supported classes, trained from `worldcover_train.csv`); both are selectable cards in the zoo (`mc_worldcover_base_v1`, routed by `base_scheme`) | `refine.train_worldcover_base`, `hierarchy.seed_from_classes`, `infer.active_base`, `catalogue.mint_worldcover_base_card`; `GET/POST /api/base[/select]`, `_switch_base` |
| 8 | Store published model + dataset link | (a) model `.joblib` copied into the zoo's `artifacts/` and committed on publish; `.gitignore` keeps `artifacts/*.joblib`, drops `.csv/.npy`. (b) per-dataset **public** source link captured at publish, shown on the card; private uploads (no link) stay local, never pushed | `zoo_git._mark_published` (staging) + `_apply_dataset_links`; `card.artifact.published_path`, `card.source_url` |

**Live verification highlights:** classify 2024 vs 2022 gives genuinely different counts (year
picker is real); merge tea+mining → "extractive" is exact (1690+94 = 1784) and removes cleanly;
base switch round-trips IndiaSAT-4 ↔ WorldCover-7.

**Deliverables:** `week6/slides_week6.pdf` (+ `.tex`), `week6/demo.md` (hands-on
verification walkthrough), `week6/plan.md` (build log), this document.

### Deferred / open
- **#10 — can split+merge express any decision tree?** Thought experiment; not built.

### The tip — cleanup + optimize (done)
- This document is the central record. The optimize pass de-duplicated the EE render path
  (`infer._labelled_bbox` + `_class_counts` now shared by the PNG and tiles renderers) and kept
  the new modules small/commented. Behaviour re-verified live (counts unchanged).

### Caveats worth remembering
- **Base switch is destructive:** reseeds the tree to the new scheme and clears splits/merges
  (backs the old tree up to `data/hierarchy.prev.json`). The WorldCover base is **weak-label**
  capped, so it trails IndiaSAT — offered as a starting scheme, not a better one.
- **Publish is outward-facing** (pushes to the shared GitHub zoo); the contributor prompt and
  artifact staging only act when the user actually publishes.

### New data files (week 6)
`data/op_log.json` · `data/merge_rules.json` · `data/active_base.json` ·
`data/model_worldcover_base.joblib` · `data/catalogue/artifacts/*.joblib` (on publish).

---

## 5. Post-week-6 refinements (UI ownership + merge-as-model)

A round of usability fixes plus one conceptual upgrade, all on top of the week-6 build, driven by
hands-on review of the live app. Behaviour re-verified (merge mint/delete, badge, base endpoint).

### UI / UX
- **First-run base-class chooser.** On a fresh visit a focused modal asks which base scheme to
  start from (IndiaSAT-4 or WorldCover-7) before anything else, reading `GET /api/base`. Picking a
  different scheme reseeds (with a confirm); the choice is remembered (`localStorage.onboard_base`).
  The old sidebar base picker and the inline year control were **removed** — base and year now live
  in the zoo.
- **Inference year moved into the zoo.** The Alpha Earth year (2017–2024) is set on the Alpha Earth
  inference-dataset card; a client-side `inferYear` drives Run classification. Detailed stays pinned
  to 2024. The status line no longer prints the year (`Classifying at 10 m…`, `Done: …`).
- **Merges shown on the hierarchy.** Active merges render on the tree itself: each source leaf gets
  a coloured `→ target` tag, and every merge target is a virtual node with an undo ✕. Sources are
  chosen by **ticking leaves in the tree** (the separate pick-list is gone).
- **Dataset link via the detail pane, not a publish prompt.** A dataset's public `source_url` is set
  on its card's detail pane (`catalogue.update_card_meta(source_url=…)`), so publishing several
  models no longer fires one prompt per dataset.
- **No publish popups.** The contributor (GitHub handle / email) comes from the card's Annotate
  field (remembered in `localStorage`) and is sent silently on publish — the `prompt()` is gone.
- **Responsive "data so far".** The split distribution highlights the currently-selected sibling and
  titles itself with the parent split, so switching e.g. tea↔non_tea visibly updates instead of
  looking stuck.
- **Wider sidebar** (320→360 px via a `--sidebar` CSS var) and **cache-busted assets**
  (`app.js?vN` / `style.css?vN`) so a stale cached script can't run against fresh HTML (the one
  failure mode that silently broke the whole UI).

### Merge now produces a local model (#9 deepened)
- Sir's ask: *even a merge should produce a local model.* A merge now mints a **local Model Card**
  `mc_merge_<target>_v1` with a new `merge_relabel` topology (added to the schema). It `produces`
  the merged class, carries **no joblib** (a merge is a relabel layer, not a trained classifier),
  and records its source leaves plus the models that produced them (`merge.source_models`, lineage).
  Minted on `POST /api/merge`, dropped on `DELETE`. `catalogue.sync_merge_cards()` runs at startup
  to reconcile cards with the live rules, so merges made before this existed also get a card.
- **Badge fix:** the zoo's "unpublished" count now counts actual **cards**, excluding the derived
  `index.json` (a dirty index used to misread as "1 unpublished, nothing shown"). Also fixed a
  git-porcelain parse that was clipping a character off filenames.

### Files / endpoints touched
`backend.py` (merge mint/delete, `source_url` on annotate, startup `sync_merge_cards`) ·
`catalogue.py` (`mint_merge_card`, `delete_card`, `sync_merge_cards`, `update_card_meta` source_url,
merge placement) · `zoo_git.py` (status counts cards not index; porcelain parse) ·
`schema/model_card.schema.json` (`merge_relabel`) · `static/{index.html,app.js,style.css}`.
New data file: `data/catalogue/models/mc_merge_*_v1.json` (per active merge). Plan:
`week6/ui_revamp_plan.md`; slide walkthrough: `week6/slide_explainer.md`.

---

## 6. Week 7 — apply + harden on stress-test sites

Source: `week7_instructions.txt` (sir's advice, transcribed). This week is mostly *applying and
strengthening* the framework on named sites, plus three genuine engineering additions. Full log:
`week7/plan.md`; approved plan: `(internal planning notes)`.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 3 | Temporal robustness | Vegetation drifts year to year, so a split is **trained on a pool of years** (`refine.train(parent, years=[...])`) and checked on years it never saw. `temporal_eval.py` compares a single-year baseline vs a multi-year pooled model, holding out whole polygons and whole eval years, and saves the pooled model. Base stays 2024 (its CSVs have no year column; Tessera is 2024-only), so temporal robustness lives on the example/split path. | `refine.py`, `temporal_eval.py` |
| 4 | Data adequacy, not raw counts | Report **coverage** = labelled area ÷ AOI area (equal-area, so it's contingent on the size of the area being classified) alongside the existing spatial-spread entropy. | `catalogue._coverage`/`recompute_spread`, `GET /api/cards/{id}/spread`, `app.js` |
| 5 | Validate a scheme before executing | One upload that **validates then applies**: `POST /api/hierarchy/import` checks the whole envelope first — tree shape (reused `hierarchy.validate`) + op-log well-formedness (new) + missing-classifier scan — and rejects a bad file with 400 before it mutates. No separate validate step. | `validate_ops.py`, `backend.py`, `app.js` |
| 7·9·11 | Stress-test sites as defaults | Three presets (IIT Delhi + Sanjay Van, Jalpaiguri, Asola Bhatti); `prep_acacia_examples.py` turns 912 confident crowns into `data/examples/{acacia,non_acacia}.geojson`. | `backend.PRESETS`, `scripts/prep_acacia_examples.py` |
| 2 | WorldCover direct vs mapped-down | Analysis: you can pick WorldCover as a base directly, but India's thin support for its rare classes pushes you to the mapped-down end (base-scheme + merge + split) by default. | `week7/notes/worldcover_direct.md` |
| 6 | Tessera as a choice | Note on the inference-year picker: Tessera is 2024-only over India; other years can be requested. | `/api/inference-options`, `app.js` |

**Design note (#4):** coverage is **area-based**, not the plan's original grid-cell ratio — that
ratio collapses to 100% whenever the AOI is smaller than one grid cell, which is the case for
every one of our small stress-test strips, so it was unusable. Area coverage stays honest at any
AOI scale.

**Verified:** presets served; acacia prep yields 336+576 example crowns; coverage drops as the AOI
grows (tea = 0.59% of the Assam box, ~0% of all-India); validator flags unknown ops / missing args
/ broken trees / missing classifiers correctly and import rejects a bad file before mutating.
**Multi-year training works and pays off where it should:** a live acacia run (train 2019/2021/2023,
test unseen 2020/2024) lifts accuracy on the unseen years from 0.635 (single-year) to **0.745
(+0.110)**. The same protocol on the four **base classes** gives 0.888 → 0.891 (**+0.003**) — coarse
classes are already temporally stable, so multi-year robustness matters on the *fine* splits, not the
base. (`temporal_eval.py --from-file` samples any labelled polygon set for this.)

### Site test results (`week7/site_tests.py`, live GEE)
- **Tea vs non-tea:** 0.957 held-out accuracy. **Acacia vs non-acacia:** 0.745 on unseen years
  (multi-year) — a hard species split. **Mining detector:** 0.859 accuracy, 0.854 recall on real
  mines (held-out), 0.139 false-positive rate on non-mining ground truth. **Mining false-positive,
  active vs reclaimed (same detector):** **Jharia active coalfield 71.2%** flagged vs **Asola reclaimed
  17.1%** — a 4× gap. The active site is the positive control (the model genuinely finds mines); Asola's
  17% is a real false-positive tendency on reclaimed mine-like ground, as sir predicted.

### Deferred to a live session (yours)
- The **Jalpaiguri** base-scheme + split/add operations demo (sir will ask for this live).
- On-map click-through of the acacia/tea/mining sites.
- **#8** mining segmentation model and **#1** biomass/GEDI stay out of scope (sir's calls).

---

## 7. Week 8 — UI restructure + zoo/inference fixes (features #2–#11)

Source: `week8_instructions.txt` (26 asks). This block delivers **#2–#11**: mostly a front-end
restructure into a self-explanatory two-panel layout, plus targeted backend work. Full log:
`week8/plan.md`; approved plan: `(internal planning notes)`.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 2 | Drop the model-mode choice | Removed the Realistic/Detailed dropdown; Run always classifies Realistic (AE → EE 10 m tiles). The softvote path stays in the backend, just unexposed. | `static/index.html`, `static/app.js` |
| 3 | Clickable bounding box | A persistent AOI box: draw a rectangle to set it, or in Custom mode click the map to drop a centre and size it live with the Half-size slider (`drawAoi`, `customBbox`). | `static/app.js` |
| 4 | Export only this session's ops | `/api/tree` returns `op_seq`; `export?since=` slices the op-log to the session the client anchored in `localStorage` (survives refresh). Fixes the whole-history leak. | `backend.py`, `static/app.js` |
| 5 | Reset the tree on a new area | `POST /api/session/reset` reseeds the current base scheme; the UI offers it **confirm-first**, only when real work exists. `reset` added to the op validator. | `backend.py`, `validate_ops.py`, `static/app.js` |
| 6·10 | Explanatory, uncluttered | Guidance lives in the contextual panel (heading + one-liner + one hint per action); left hints tightened. | `static/index.html` |
| 7 | Structural ops before retrain | Right-panel order: Mark data → Split → Add → Merge → Retrain. | `static/index.html` |
| 8 | Contextual right panel | New `#context` aside holds the actions, driven by `renderContext(cls)` — names the selected class and dims the less-relevant blocks. Left panel keeps Area/Hierarchy/Save/Zoo. | `static/{index.html,app.js,style.css}` |
| 9 | Zoo shows every model; drop dummy | `DELETE /api/cards/{id}` (orphan-joblib purge + published guard), startup `sync_node_model_cards`, archived badge + Delete button. **tea/non_tea regenerated** as a real archived card (0.963); acacia dummy removed, acacia kept live. | `backend.py`, `catalogue.py`, `static/*`, `scripts/regen_tea_acacia.py` |
| 11 | Flag incompatible apply | `catalogue.check_apply_compatible`; `/api/apply` gains `target_node`+`force`, returns **409** with a reason on a mismatch; the panel's "Apply to selected class" confirms then forces. | `catalogue.py`, `backend.py`, `static/app.js` |

**Verified** (TestClient + live GEE + real uvicorn): session-scoped export returns only new ops;
greenery-split→water apply is refused with a readable reason; publishing-guard blocks deleting a
published card; `session/reset` reseeds root+4 base; a live classify of the IIT box returns
acacia/non_acacia/built_up/water/barren tiles; the page serves the context panel at `?v=8` with no
Mode dropdown. The tea/acacia regen leaves the zoo with acacia live + tea archived.

### Block 2 — features #12–#15
| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 12 | Flow-gate controls | Balancing + multi-year fields wrapped in `#retrainAdvanced`, shown only when training your own split (not a bare leaf or the base). | `static/{index.html,app.js}` |
| 13 | Two hierarchy views | `By hierarchy \| By operations` toggle; read-only `GET /api/oplog?since=` feeds an ordered step list; clicking a step selects its class so the right panel drives the action; "Use a model from the Zoo" split path. | `backend.py`, `static/*` |
| 14 | Standard classes on tiles | `catalogue.std_classes_for_card` + `std_classes` on model index rows; the small tile shows the standard name when mapped (else user classes); detail shows uploader-class → standard name. | `catalogue.py`, `static/app.js` |
| 15 | Dataset → models cross-ref | `catalogue.models_using_dataset` + `used_by` attached to dataset cards; a "Used in models" block on the detail + a count on the tile. | `catalogue.py`, `backend.py`, `static/app.js` |

### Block 3 — features #16–#27 (+ entropy/water fixes + presentation)
| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| — | Fixes | entropy `-0.0 → 0.00` + restored archived examples; water `#2b6cff → #1e88e5` (blue). | `catalogue.py`, `hierarchy/infer/refine`, `data/hierarchy.json` |
| 21 | Overlay toggle | 👁 hides/shows the classification without reclassifying. | `static/*` |
| 25 | Selective publish | tile checkboxes + "Publish selected (N)". | `static/*` |
| 24 | GeoTIFF export | `classify_bbox_geotiff` + `GET /api/classify.tif` + ⬇ button. | `infer.py`, `backend.py`, `static/*` |
| 27 | Seasonal-water dataset | `prep_seasonal_water.py` → `ds_seasonal_water_v1` (876 polys). | `scripts/`, `catalogue.py` |
| 17 | Linear bake-off | `train(algo="auto")` LinearSVC/LogReg/Ridge, best by acc; band-math generalised to any linear. | `refine.py`, `infer.py` |
| 16 | Tessera training | `embedding` through `train`; `TE_COLS`; site-scoped; carded (point-grid only). | `refine.py`, `infer.py`, `backend.py`, `static/*` |
| 18·23 | Project save/resume | `project.json` = scheme + sequence + aoi/year/base, datasets as links. | `static/*` |
| 19·20·22·26 | Docs | pipeline/schemas/Tessera-joblib/deployment answered in the deliverables. | `week8/*` |

**Deliverables:** `week8/slides_week8.{tex,pdf}` (Beamer, 12 frames), `week8/slide_explainer.md`
(covers #22 + #26), `week8/demo.md`. **Verified** live (GEE + Tessera): Ridge bake-off winner 0.731
renders as tiles; Tessera acacia ~0.73 carded; GeoTIFF downloads as valid TIFF; seasonal-water card
spread 0.61.

### Not in this block
Biomass/GEDI (#1) remains; multi-year Tessera + a point-grid render for Tessera splits, a
seasonal-water split, and deployment hardening (service-account key, Dockerfile) are the roadmap.

---

## 8. Week 9 — rules, provenance, raw-Sentinel water, guardrails

Source: `week9_instructions.txt` (13 asks). Approved subset this phase: **#3, #4, #5, #7, #8, #12,
#13** (#5/#7 and #12/#13 are paired). Two lab papers drove the design and were read in full:
**STACD** (`stacd_paper.pdf`) for #4, and **"Beyond Flat Classifiers"** (`beyond_flat_classifier_paper.pdf`,
Bansal et al.) for #13. Full log: `week9/plan.md`; approved plan:
`(internal planning notes)`.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 12 | **Rule-based split** | A node's children can be resolved by an *interpretable expression* over an index **registry** (NDVI annual/Kharif/Rabi, NDWI/MNDWI, NDBI/BSI, slope/elevation) instead of a trained model — `if ndvi_annual > 0.3 → dense_veg else sparse_veg`. Indices compute live in EE, so a rule split **rides the crisp tile map**. Expressions are `ast`-checked against a whitelist before touching EE. Stored on the node (travels with the saved scheme), carded as `rule_split`. | `src/rules.py`, `infer.{_refine_idx,_final_label,load_refinements,_sample_rule_labels}`, `backend./api/split/rule` + `/api/rules/registry`, `catalogue.mint_rule_card`, `static/*` "Split by rule" |
| 13 | **Decision tree via rules** | The crop→shrub move: a rule split's child is a first-class **merge** source, so split + rule-split + merge compose into any finite decision tree (answers the deferred wk6 #10). Maps the "Beyond Flat Classifiers" 12-class tree onto our framework. | `week9/notes/decision_tree.md` (mechanic verified live) |
| 5·7 | **Water per fortnight (raw Sentinel)** | "On the 14-Jul fortnight, which pixels held water?" A **linear** water/non-water model trained offline on Sentinel-1 SAR + Sentinel-2 optical features (VV/VH, NDWI/MNDWI/BSI) sampled at each seasonal-water polygon's own date, then **replayed as EE band math** for any date — the same interactive path Alpha Earth uses, dodging the memory wall that forced the flood pipeline to batch. | `src/sentinel.py`, `scripts/train_water_fortnight.py`, `infer.{_linear_label,classify_water_tiles}`, `backend./api/water`, `catalogue.mint_water_card` |
| 4 | **STACD provenance** | Every classified output emits a **stack-spec** (STAC Item: bbox/geometry/assets/class legend) + a **stacd spec** (DAG + Dataset/Algorithm types & instances) per the paper's 5 classes, with the hierarchy+op-log+classifier-refs embedded as the "input set used to produce this". Reuses the zoo cards — no new source of truth. | `src/stacd.py`, `backend./api/stacd`, `static/*` "Provenance (STACD)", `week9/notes/stacd_mapping.md` |
| 3 | **Bounding-box size cap** | Area guardrails so a huge box can't explode compute/download: generous cap on EE tiles, tighter on GeoTIFF (getDownloadURL is size-capped), a tile-count cap on the Tessera fan-out (~150 MB/tile). Admin-tunable in `config.py`; UI shows the area + disables Run past the cap. | `src/aoi.py`, `config.py` (`AOI_*`), `backend` guards, `infer._sample_tessera`, `static/*` |
| 8 | **Training-time benchmark** | Profiles EE sampling (per-getInfo-call latency × batches) vs fit (a+b·rows, per algo incl. an RF reference) → `data/benchmark_profile.json` + a server-admin table `week9/benchmarks.md`; `/api/estimate` gives a live estimate. | `scripts/benchmark_training.py`, `backend./api/estimate` |
| 2 | Answer: LULC on Tessera? | Yes but a poor base — 2024-only (no temporal robustness, the thing that closed our gap), point-grid only, trails AE India-wide. Keep it as an opt-in single-year feature for fine splits. | (answered inline) |

**Verified live (EE):** rule-split greenery by `ndvi_annual > 0.3` renders as crisp tiles with
dense/sparse counts; rule-child + base leaf merge into one class (both sources gone) — the #13
composition; the rule survives export→import (it lives in the tree JSON) and mints a valid
`rule_split` card; `/api/water?date=2024-07-14` returns a fortnight's water tiles; `/api/stacd`
returns a STAC Item + DAG whose `alg_inputs` embeds the scheme; oversized bbox is refused with a
readable reason on classify and GeoTIFF; the benchmark writes a monotonic estimate table
(1 km²≈8 s … 100 km²≈276 s here) and `/api/estimate` reads it. The whole app boots and serves at
`?v=14`.

### New / changed data files (week 9)
`data/refine/water_fortnight.joblib` · `data/benchmark_profile.json` ·
`data/catalogue/models/mc_<node>_rule_v1.json` (per rule split) · `mc_water_fortnight_v1.json`.

### Follow-up block (also this phase): #1, #11, and the answers
| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 1 | Link model families to the inference data | The valid model list now follows the chosen source: Alpha Earth is linear-only (band-math), Tessera adds Random Forest (+ XGBoost if installed) and reserves an object-detection slot. Non-linear on AE is refused with a reason. UI algo list repopulates on the embedding pick. | `refine.model_families` + `_NONLINEAR_ALGOS`, `train` guard, `backend./api/model-families`, `static/*` (`refreshModelFamilies`) |
| 11 | Improve acacia | Enabled lever #2 (non-linear on Tessera). Ranked recipe of runnable levers (data spread, RF on Tessera, hard negatives, NDVI-season rule pre-filter, threshold tuning) + the object-detection ceiling. | `week9/notes/acacia_improvement.md` |
| 9·10 | Deployment / MVP | Answered: structurally clean + demo-ready; gaps are packaging (service-account key, Dockerfile, pinned deps, API rate-limit, binaries out of git). Covered on the week-9 deck. | (answered; slide 13) |
| 2 | LULC on Tessera | Confirmed: already supported for *training a new split* (not a base map) — `embedding="tessera"`, carded, acacia ≈ 0.73. | (answered) |

### Deferred / open (week 9)
- **#6** (mail Ratinder) — external, not code.
- STACD emitter is the *metadata* half; wiring to the Airflow runtime (selective recomputation,
  the SQLite instance store) is the next step if we adopt it.
- Water model: research reconstruction-of-indices-from-embeddings stays out (sir: "not for now").
- Object-detection family (acacia crowns / mining segmentation) is reserved in the registry but
  not built.

### Deliverables (week 9)
`week9/slides_week9.{tex,pdf}` (14 frames, Madrid, same style as prior weeks) ·
`week9/slide_explainer.md` (line-by-line + 14 Q&A) · `week9/demo.md` (hands-on click-through) ·
`week9/notes/{decision_tree,stacd_mapping,acacia_improvement}.md` · `week9/benchmarks.md`.

---

## 9. Week 10 — non-linear models, biomass, mining segments, robustness, STACD audit

Source: `week10_instructions.txt` (14 asks). This phase is testing + hardening plus real engineering
additions. Implemented subset: **#1, #3, #4, #6, #7, #8**. Full log: `week10/plan.md`; approved plan:
`(internal planning notes)`. Two synergies shaped it — RF-on-
Alpha-Earth (#7) is the render path biomass (#3) rides; the benchmark regen serves both #7 and #6.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 7 | RF for EE, XGBoost for Tessera | **Random Forest now trains on Alpha Earth** (sir: "the one that typically works"). RF/XGBoost aren't band math, so inference became **algorithm-aware**: a non-linear AE split is dropped from the crisp tile path (like a Tessera split) and the whole area falls back to the **point-grid** render, which runs `model.predict`. XGBoost-on-Tessera enabled (package added). Bundles already carry `algo`; `model_families` offers RF on AE with a point-grid caveat. | `refine.model_families`/`train` guard, `infer.{NONLINEAR_ALGOS,_is_nonlinear,_labelled_bbox}`, `backend.classify` (`grid_live`), `requirements.txt` |
| 3 | Biomass data collection **+ integrate** | Ratinder's GEDI L4A AGBD collection rebuilt on **our exact Alpha Earth feature space** (+ slope): `prep_gedi_biomass.py` (quality/error/slope masks, stratified-samples present shots over an AOI), `train_biomass.py` (RF **regressor**, spatial cell-holdout). Integrated as a first-class capability: `infer.classify_biomass_grid` → `GET /api/biomass` → a `regression` model card in the zoo → a **🌲 Map biomass** overlay with an AGBD green ramp. Biomass is just a regression target on the same embeddings, so it rides #7's point-grid path. | `scripts/{prep_gedi_biomass,train_biomass}.py`, `infer.{biomass_models,load_biomass,classify_biomass_grid}`, `backend`, `catalogue.mint_biomass_card`, `schema` (`regression`), `static/*` |
| 4 | Mining segmentation | Pragmatic, framework-consistent **segmentation**: vectorize the existing pixel `mining` prediction into cleaned polygon **objects** in EE (`focalMode` de-speckle + `reduceToVectors` + min-area filter), with per-segment area. Not a learned net (that stays the reserved object-detection slot). | `infer.segment_class`, `GET /api/segment`, `config.SEGMENT_MIN_AREA_HA`, `static/*` (⛏ Segment mining + GeoJSON download) |
| 6 | Estimate + background notification | `/api/estimate` was correct but unused, and runs are synchronous. Wired the estimate into the retrain **work toast** with a live **elapsed-vs-expected timer** (`fetchEstimate` + `startWorkTimer`); regenerated the benchmark profile so RF/XGBoost estimates are real. Accuracy: within ~2× of a timed run (sampling-dominated). | `static/app.js`, `scripts/benchmark_training.py`, `week10/notes/estimate_check.md` |
| 8 | Acacia spatial **and** temporal | Crowns now keep their source region (`area`), threaded through `build_training_frame`. `acacia_robustness.py` reports temporal-only / spatial-only (hold out Sanjay-Van strip SV_S4) / **combined region×year** holdout + a per-eval-year aggregate to catch fluke years. | `prep_acacia_examples.py`, `examples.build_training_frame`, `week10/acacia_robustness.py` |
| 1 | STACD proper? | Audited `stacd.py` against the paper's five classes. Fixed the two real deviations (Algorithm_Instance now has a unique `id`; the output's `alg_name` references an **Instance**, not a Type). Documented the intentional extension (`alg_inputs.input_set` = the scheme as the input set) and the metadata-vs-Airflow-runtime gap in a shareable audit. | `src/stacd.py`, `week10/notes/stacd_audit.md` |

**Verified live (EE + TestClient):** RF greenery split is dropped from the tile path (no crash) and
applied on the point grid; XGBoost/RF appear in `model_families` per source; `/api/biomass` returns a
graded AGBD grid (Jalpaiguri box) and the biomass card is browsable (`regression`, R²≈0.22 spatial /
0.33 random on Ratinder's AEZ-8 frame); `/api/segment` returns 9 clean mining polygons over Asola
Bhatti (speckle filtered, bad class → 400); `/api/estimate` covers RF/XGBoost and is ~2× a real
retrain (49 s vs 92 s); acacia **combined spatial+temporal 0.673 < spatial-only 0.695 < temporal-only
0.716**, with 2024 flagged as a possible fluke year (per-year spread 0.234); `stacd.py` smoke test
passes with instance ids and the app boots at `?v=17`.

### Deferred (week 10)
- **#2 / #9 / #14** deployment (Dockerize, service account, STACD archiving policy) — sir deferred to
  next week after end-to-end testing.
- **#10 / #12** hands-on UI shakeout + visual dense/sparse-vs-canopy-density check — live-session work.
- **#11** running the water classifier per-fortnight over *all* pixels with augmented non-water
  samples (greenery/barren) so it works outside water bodies — the bigger water build; step 1
  (per-fortnight water within water bodies) already exists from week 9.
- **#13** Raman/Aman IndiaSAT tree-vs-crop / farm-vs-shrub models into the zoo — needs the shared
  assets; external.
- A learned mining segmentation net and the STACD Airflow runtime remain future work.

### New / changed files (week 10, batch 1)
`scripts/{prep_gedi_biomass,train_biomass}.py` · `week10/acacia_robustness.py` ·
`week10/notes/{stacd_audit,estimate_check,acacia_robustness}.md` · `data/refine/biomass_aez8.joblib`
· `data/catalogue/models/mc_biomass_aez8_v1.json` · `requirements.txt` (+xgboost) ·
`config.SEGMENT_MIN_AREA_HA` · regenerated `data/benchmark_profile.json`.

### Batch 2 — points #5, #10, #11, #12, #13, #14

Second week-10 block. Plan: `(internal planning notes)`. The user downloaded the two
IndiaSAT GitHub scripts sir shared (at repo root), and their training assets turned out to be readable
from our EE project — which reshaped #13 into a real build.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 13 | Plug the IndiaSAT production models into the zoo | **The big win.** Both of Raman's models train an `ee.Classifier.smileRandomForest` **and classify inside Earth Engine**, so they render **server-side as tiles** like our AE band-math path (no download, no sklearn). Ported both: **tree-vs-crop** (pan-India, 46-band Sentinel-1 SAR 16-day time series, `L2_TrainingData_SAR_TimeSeries_1Year`, class 5/6) and **farm/plantation/scrubland** (per-AEZ, Alpha Earth, trained from `gee_samples_all` filtered to the AOI's agro-ecological region). Each is a zoo card (new `ee_rf` topology storing the *recipe*, re-trained on demand — faithful to "trained on the fly, no model saved"), picked from the zoo via "Use this model". Since they carry their own class scheme, applying one (`POST /api/apply-eerf`) **rewrites the hierarchy**: greenery gains the model's classes as children and is marked with the model, so the tree follows the model. On every Run classification `infer._apply_ee_rf` → `ee_rf.composite_into` refines only greenery with the sub-model's classes in Earth Engine, keeping the rest of the base map (built-up/water/barren + any other split), rendered as crisp tiles. | `src/ee_rf.py`, `backend./api/{treecrop,farmshrub,apply-eerf}`, `infer._apply_ee_rf`, `catalogue.mint_ee_rf_card`, `schema` (`ee_rf`), `static/*` |
| 11 | Water step 1 | Spatial (by water-body) + temporal (by year) **robustness** eval with fluke-year aggregate; **non-water augmentation** (barren/built/greenery negatives) to fix the "calls everything water" problem; **per-pixel fortnight-count** raster (run the model over a year, sum water masks) as a blue-ramp overlay. `sentinel._s1/_s2` hardened so an empty fortnight doesn't crash the sweep. Hierarchy integration stays step 2 (sir's staging). | `week10/water_robustness.py`, `scripts/train_water_fortnight.py --augment`, `infer.water_frequency_tiles`, `backend./api/water-frequency`, `sentinel.py`, `static/*` |
| 5 | Tessera vs Alpha Earth timing | Real measured benchmark: **AE total ~12 s vs Tessera ~72 s** (sample 31 s, classify 40 s), plus a separately-timed fresh tile **download 151 MB in 29 s (5.2 MB/s)**. AE is server-side round-trips only; Tessera pays a ~30 s/tile download before anything. | `scripts/benchmark_tessera_vs_ae.py`, `week10/notes/tessera_vs_ae.md` |
| 12 | dense/sparse rule vs CoreStack canopy | Quantitative check vs CoreStack LULC v3 (legend pinned by NDVI: 6=tree dense, 12=scrub sparse). Finding: dense↔tree agrees ~99 %, but a **single annual-NDVI threshold under-detects sparse scrub** (Central India 83 %) — the rule is really tree-vs-non-tree; use `ndvi_rabi`/SAR for true canopy density (editable rule, no code change). | `week10/canopy_compare.py`, `week10/notes/dense_sparse_vs_canopy.md` |
| 10 | Even out the UI | QA pass: **segment gated to the selected class** (was hard-wired mining); **muted context blocks now disable their inputs**; GeoTIFF double-fire guard; export/annotate/publish busy-toasts + try/catch so a network throw can't strand a "working…" toast; **zoo year change auto-refreshes** the map. | `static/{app.js,index.html}` |
| 14 | STACD archiving email | Mostly deferred to the deployment week (sir: "no change for now"). Shipped only the cheap hook: an **`archive` flag** on the STACD emit (`/api/stacd?archive=true` → `properties.archive`) so a run can be marked retain-vs-test; the cleanup service itself is deferred. | `src/stacd.py`, `backend`, `week10/notes/stacd_archiving.md` |

**Verified live (EE):** tree/crop paints crop/tree tiles (~10 s); farm/shrub paints
farm/plantation/scrubland over Punjab (43 s) and gives a clean error on an urban box with no agri
ground truth; both `ee_rf` cards sync + validate in the zoo; water robustness **spatial+temporal
0.979** (stable, no fluke year); water-frequency renders a graded count map (mean ≈ 3.9 fortnights
over a lake box); canopy agreement 99 %/83 % as above; Tessera/AE timings measured; STACD `archive`
flag round-trips; app boots at `?v=19` with every new route registered.

### Deferred / open (batch 2)
- Water → hierarchy integration (step 2), and deployment/dockerize (#2/#9/#14) — the deployment week.
- The EE-RF models now composite as a **greenery refinement** (`classify_composited`), keeping the base
  map; wiring them as fully general split *nodes* under any chosen class (not just greenery) is the
  remaining generalization.
- A canopy-density rule using dry-season NDVI / SAR (the #12 fix is a better rule, not new code).

### New / changed files (week 10, batch 2)
`src/ee_rf.py` · `scripts/benchmark_tessera_vs_ae.py` · `week10/{water_robustness,canopy_compare}.py`
· `week10/notes/{water_robustness,dense_sparse_vs_canopy,tessera_vs_ae,stacd_archiving}.md` ·
`data/catalogue/models/mc_{treecrop,farmshrub}_ee_v1.json` · schema `ee_rf` topology ·
`data/refine/water_fortnight_augmented.joblib` (on `--augment`).

### Deliverables (week 10)
`week10/slides_week10.{tex,pdf}` (Beamer Madrid, 15 frames, same style as prior weeks, covering points
1, 3, 4, 5, 7, 8, 11, 13 with the STACD implementation explained) · `week10/slide_explainer.md`
(foundations + slide-by-slide + 14 Q&A) · `week10/demo.md` (hands-on click-through) ·
`week10/notes/{stacd_audit,estimate_check,acacia_robustness,water_robustness,dense_sparse_vs_canopy,tessera_vs_ae,stacd_archiving}.md`.

---

## 10. Week 11 — review fixes: sampling parity, any-node models, biomass split-out, pan-India eval

Source: `week11_instructions.txt` (sir's review, 14 points). This block delivers the **STACD send-ready
fixes** plus **#1, #5, #7, #9, #10**. Full log: `week11/plan.md`; approved plan:
`(internal planning notes)`.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 14 + STACD | Op-log naming + send-ready spec | The STACD output embeds the input set at `alg_inputs.input_set` (renamed from the confusing `alg_inputs.hierarchy.hierarchy`), and the op-log becomes `op_sequence` — the **effective** sequence, not the raw click log: everything up to the last `reset` and any undone `merge` are dropped (`_effective_ops`). Legend drops the junk `other` class and paints greenery green (tree-color fallback). Now clean to mail Susmit/Anunay. | `src/stacd.py`, `week10/notes/stacd_audit.md` |
| 7 | Biomass isn't LULC | **Decoupled** the GEDI biomass regressor from the LULC app entirely — removed `/api/biomass`, the 🌲 overlay, the `regression` topology + zoo card + startup sync, and cut `train_biomass.py`'s card mint. Biomass stays a standalone mini-project (`scripts/*`, `cod892_biomass/`). Shared `_grid`/`_sample_alpha` (RF-on-AE #7 path) kept. | `backend.py`, `infer.py`, `catalogue.py`, `schema`, `static/*`, `scripts/train_biomass.py` |
| 1 | Sampling parity with Raman | Farm/shrub trained on **AEZ ∩ 40 km of the box** — a regression vs the pan-AEZ production model. Now trains **pan-AEZ** (drop the buffer, balanced per-class cap, deterministic seed), so the user gets the fully-trained model regardless of box size. Treecrop was already pan-India. Answered "why not stored/local": EE-native `smileRandomForest` runs server-side, no joblib to pickle; retrain-on-the-fly from a fixed pan-AEZ set is faithful + deterministic. | `src/ee_rf.py`, `week11/notes/eerf_sampling.md` |
| 5 | Attach a model to **any** node | The two IndiaSAT EE-RF models were hard-wired to refine greenery. Now attachable to **any node** with a *suggested* default: `recommend_placement` gets an `ee_rf` branch ("normally refines greenery, but any node"), the UI applies to the selected class, and a name-collision guard returns a clean 400. Verified live: treecrop composited into **barren** paints cropland/tree there. The compositing machinery already generalized (a rule-split child stays a leaf; `_apply_ee_rf` scans any `ee_rf`-marked node). | `catalogue.py`, `backend.py`, `static/app.js` |
| 9 | Mining pixel+vectorize good enough? | Pan-India experiment: `segment_class` polygons vs GT mining polygons, greedy IoU match. **precision 0.04 / recall 0.16 / F1 0.07 / mean IoU 0.52** (25 sites) — over-fragments and over-detects, so **not good enough for object-level delineation**; a learned segmentation route is warranted. The pixel model stays a good detector/screen. Numbers on `mc_barren_v1`. | `week11/mining_eval.py`, `week11/notes/mining_eval.md` |
| 10 | Water validation + truth | Corrected the premise: the water model is **S1+S2**, not S1-only (so road/water confusion is already mitigated). Small-vs-large body eval on the deployed model: **large F1 0.99, small F1 0.75 (recall 0.67 — the real gap)**, dryland false-positive **2.5 %** (not spurious). Points to sir's two-classifier design for small/seasonal water. Numbers on `mc_water_fortnight_augmented_v1`. | `week11/water_eval.py`, `week11/notes/water_eval.md` |

**Verified:** app boots with no biomass route (404), `stacd.py` smoke passes with `input_set`/`op_sequence`,
`ee_rf.py` offline checks pass; live EE — farm/shrub trains pan-AEZ, treecrop composited on **barren**
renders cropland/tree, mining eval over 25 GT sites, water eval over 67 water bodies with card writes.

### Block 2 — track B (high-quality classifiers) + the spurious-water filter: #11, #12, #13
Plan: `(internal planning notes)` (11/12/13 working plan:
`week11/notes/plan_11_12_13.md`). Track B = building classifiers that work anywhere in India, evaluated
as **pan-India experiments outside the framework**; #13 also ships a real feature. Every eval reports
precision + recall + F1.

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 13 | Road/spurious water: a filter | **Code-level correction (not a UI feature):** the spurious-water threshold holds a pixel as water only if it read water in ≥ N fortnights — `infer.annual_water_mask`, threshold `config.WATER_MIN_FORTNIGHTS` (=2), to de-spurious the annual water layer when the fortnight model feeds the LULC (deferred water step). No endpoint/button. **Eval** on sir's EE GT (all readable): `GTSeasonal`/`GTPerennial` + `GT_BINARY_LATEST`. A **2-fortnight hold cuts spurious water 15%→2%** (precision 0.80→0.96); cost lands on small/seasonal recall (small-water 0.30→0.11), confirming the two-classifier need. | `src/infer.py`, `config.py`, `week11/water_gt_eval.py`, `week11/notes/water_gt_eval.md` |
| 12 | Pan-India mining classifier accuracy | Track-B experiment: mining vs not with **buffer-ring hard negatives** (`buffer(d)∖all_mines` = tentative barren around mines) + generic negatives, whole-polygon holdout. Linear = F1 0.55 (P 0.45, R 0.70 — weak precision, barren confusion). **RF + tuned threshold lifts it to F1 0.59, precision 0.45→0.61** (recall give-back). Ring width ~irrelevant. Complements #9 (object-level 0.07). On `mc_barren_v1`. | `week11/mining_pan_india.py`, `week11/notes/mining_pan_india.md` |
| 11 | Acacia: counts, filter, **improve** | Crowns: **acacia 336, non_acacia 576**, all single trees (median 27 m², sub-pixel on 10 m AE → mixed-pixel = why it's near-random). A *gentle* < 15 m² filter keeps **296/498** (not the 8 a 100 m² cutoff leaves). Real levers (week9 recipe): **RF + multi-year lifts F1 0.68→0.71, acc 0.72→0.78, precision +0.10**. Ceiling is the mixed pixel; the true fix is higher-res features (Tessera / drone-RGB **DINO**, external). P/R/F1 throughout. | `week11/acacia_eval.py`, `week11/notes/acacia_eval.md` |

**Verified (live EE):** the annual-water correction thresholds the fortnight count (`annual_water_mask`);
water GT eval over 317 GT polygons writes the threshold sweep to the card; mining pan-India over 50
polygons (linear vs RF+threshold); acacia counts + gentle filter + RF/multi-year. App boots at `?v=30`.

### STACD cross-verification (#15)
Susmit replied to the spec mail (`week11/susmit_stac.json` = their tree-crown item): some parameters
differ, unsure which are optional/mandatory, asked to cross-check Saharsh's Airflow format. Field-by-field
comparison (`week11/notes/stacd_crosscheck.md`): the mandatory STAC fields already matched; the gaps were
optional-but-common metadata, now adopted in `build_stack_item` — **STAC 1.1.0**, a `collection`, real
`links` (self/root/collection/parent), a `start/end_datetime` range, `keywords`, `input_parameters`, and
bbox-corner fields. Their table-extension/drone-model fields don't apply (our output is a raster with a
class legend). Two items still need Saharsh: whether `stac_extensions` must be a validatable schema URL
(ours is the repo), and the collection/catalog layout the Airflow ingester expects; then re-send. (Note: `/api/session/reset` archives the
example canvas — the acacia/mining/barren example files were restored after a test triggered it.)

### Deferred / open (week 11)
- Water **step 2** (the lenient level-1 + within-body two-classifier for small/seasonal water) — sir's
  staging; #10 and #13 both quantified the small-body recall gap that motivates it.
- A learned mining segmentation net (#9 says it's justified; #12 shows the pixel classifier is a screen,
  not a delineator) — not built.
- Acacia dataset expansion via drone-RGB DINO embeddings (#11) — external (Gaurav's data).
- Remaining review points (#2 store the model / timing, #3 mail STACD) — external/next.

### Deliverables (week 11)
`week11/slides_week11.{tex,pdf}` (Beamer Madrid, 9 content frames, same style as prior weeks, no bold;
covers the STACD cross-check #15, pan-AEZ, any-node, mining, water + spurious-water correction, acacia — biomass
removal #7 and the STACD op-log tidy #14 were kept off the deck) · `week11/slide_explainer.md` (foundations +
slide-by-slide + the **#4/#6/#8 answers** — which sensors each lab model uses, why the RF differs /
coarse grid vs crisp tile, and the existing tile path — plus Q&A) · `week11/manual_test_guide.md` +
`week11/demo.md` (hands-on click-through of every feature + the pan-India experiments) ·
`week11/notes/{eerf_sampling,mining_eval,water_eval,water_gt_eval,mining_pan_india,acacia_eval,stacd_crosscheck,deployment_test_plan,plan_11_12_13}.md`.
**EE GT access:** all three assets sir named are readable from our project — `GTSeasonal` (16),
`GTPerennial` (13), `GT_BINARY_LATEST` (288); used live in `water_gt_eval.py`.
