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
