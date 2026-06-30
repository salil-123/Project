# Week 5 — Implement the model & dataset card database (zoo backend)

## STATUS — shipped (2026-06-23)
Approved plan: `~/.claude/plans/properly-plan-an-optimal-zesty-aurora.md`.
- `schema/` — canonical card schemas + `validate.py`. Dataset cards now carry `type:
  training|inference`; model cards carry both a training-data ref and an inference feature-source ref.
  `extent` is a bbox. All 11 live cards validate.
- `src/catalogue.py` — the card DB: validate/write/read/index, `models_for_aoi` (bbox overlap),
  mint-from-live-artifacts, and `backfill()` (base + greenery + barren + their datasets + the shared
  Alpha-Earth inference card).
- `src/zoo_git.py` — `data/catalogue/` is a git repo; `publish()` commits cards + index and pushes
  (direct push); artifacts (.joblib/.csv) git-ignored. Configure `ZOO_REMOTE` in `.env`.
- `src/backend.py` — startup backfill + git init; `/api/retrain` mints a card; new `GET /api/catalogue`,
  `GET /api/cards/{id}`, `POST /api/publish`, `GET /api/zoo/status`.
- Frontend — Model Zoo panel (browse, "for this area", card detail with metrics + extent drawn on the
  map, publish button + unpublished badge); grid control widened for arbitrary sizing.
- `week5/tea_eval.py` — tea/non-tea is **test-only**: Alpha Earth held-out accuracy **0.934**
  (tea F1 0.950 / non-tea 0.904). Does NOT touch hierarchy/base/catalogue (verified). See
  `week5/notes/tea_eval.md`.

Trimmed per the user: full USDA/IUCN crosswalk file, named-region (AEZ/district) extent lookup,
EE-push/tile-url deployment, zoo governance workflow.

### Follow-ups shipped (2026-06-23, later)
- Zoo UI: full-screen overlay (was sidebar); fixed the `#id`-beats-`.hidden` bug so the map is the
  default screen and the overlay opens/closes properly; widened the detail pane to 40% (min 440px);
  uniform card tiles; smart extent (label for India-wide, box only for localized models).
- GitHub zoo is LIVE: `ZOO_REMOTE=https://github.com/salil-123/zoo_database.git`, push verified.
- Presentation: `slides_week5.pdf` (+ `.tex`, text-only — no images, no recap slide),
  `notes/demo.md` (talk track), `notes/deep_dive.md` (full explanation).
- Root cleanup: `docs/` (model.md, pipeline.md), `data/inputs/` (manual_polygons.geojson,
  mining_polygons_india.gpkg); instruction files in their week folders. Code refs updated
  (tea_eval, week3 scripts, catalogue provenance). Left at root: config.py, requirements.txt,
  CLAUDE.md, tessera_fast.py, the global_0.1_degree_* tile caches (relative-path infra).

### Follow-ups shipped (2026-06-24)
- Polygon extent on the map: "Show on map" draws the card's actual polygons (top-N by area) with
  red bubbles + zoom cap; "only for current view" now filters datasets too. Removed the legend
  (hierarchy already shows colours) and the grid-resolution slider.
- Spread (spatial-diversity / entropy) shown as banded feedback on dataset cards; clarified it's the
  grid sir meant (dataset skew), distinct from the classification grid.
- EE tile-URL serving (#10--12): Realistic served as EE map tiles via `getMapId`
  (`infer.classify_bbox_tiles`), not a capped PNG — crisp at any zoom, no download.
- Annotate editor (#8, #13--15): description / intended-use / limitations / evidence / contributor +
  per-class standard mapping (`POST /api/cards/{id}/annotate`, `catalogue.update_card_meta`).
- Class-balance feedback + remedy (#6): support-ratio flag + retrain `balance` =
  balanced|undersample|oversample (`refine._rebalance`), recorded on the card. Temporal year surfaced.
- Slides now 16 pages (added Serving-as-tiles, Describe/prove/map, Quality+balancing); demo.md and
  deep_dive.md updated to match.

### Follow-ups shipped (2026-06-24, later)
- Slides trimmed to text-only, no em dashes, no recap; removed the two JSON-card slides and the
  mixed-accuracy table (last slide is now a "what's available" list). Now 14 pages.
- Hierarchy reset to the 4 base classes by default (week-4 demo splits backed up to
  `data/hierarchy.demo_backup.json`).
- Added an "Assam tea belt (tea/non-tea)" preset (bbox over Upper Assam; 15 tea / 9 non-tea GT).
- **Use a model from the zoo:** `POST /api/apply` + a "Use this model (apply to map)" button —
  applies a split model (registers classifier on the node) or resets to the base 4 classes.
- Removed the `pipeline.md` wording from card provenance (code + the 3 seed cards).
- demo.md rewritten as a full A--F walkthrough (EE tiles, zoo browse, apply, annotate + standard
  mapping, publish, tea split with under/oversample run, Assam preset, CLI eval).

---
## Original notes (kept for context)

**Source:** `week5_instructions.txt`. **Builds on:** week-4 *design* (`week4/schema/*.json`,
`week4/notes/model_data_schema.md`, worked example cards) and the live week-3 hierarchy/refine
loop (`src/{hierarchy,refine,examples,infer,backend}.py`). Week 4 was design-only; **week 5 turns
the schema into running code** — a real catalogue on disk, wired into the backend/frontend, plus
the training-vs-inference dataset distinction the user added this week.

## The week-5 asks, decoded (from `week5_instructions.txt`)

1. **Inference datasets need a descriptor** — features, input data, what it works on. So a
   Dataset Card grows a **`type` field: `training` | `inference`**.
   - `training` dataset → just the **polygons** (labels/geometry), *no embedding needed*.
   - `inference` dataset → the converse: just the **features/inputs** (the embedding table the
     model consumes), no labels.
2. **Model Card gets two dataset fields**: one for its **training** dataset(s), one for its
   **inference** dataset (the feature source it runs on).
3. **`extent` = a bounding box for now** (keep it simple; the typed multi-form extent stays in the
   schema but we populate/use bbox). Evolve later.
4. **Arbitrary grid size** — bbox size is flexible, user picks the grid resolution for their AOI.
   (Frontend already has `n` slider + `half` size; make sure it's truly arbitrary.)
5. **Keep working on the frontend.**
6. **Finish model cards + data cards, and a database that stores them all.** ← the core deliverable.
7. **Tea / non-tea**: sir suggested splitting trees → tea / non-tea. Good demo of the
   split→retrain→card flow on a real new class. (`mining_polygons_india.gpkg` is on root.)

## Locked decisions carried from week 4 (don't relitigate)
- Two first-class objects: **Dataset Card** + **Model Card**, linked by lineage, pointing into the
  canonical 4-class spine (`hierarchy.json`).
- Catalogue layout already specified in `model_data_schema.md` §5:
  ```
  data/catalogue/
    datasets/<id>.json     models/<id>.json
    std_crosswalk.json     index.json   (denormalized lookup)
  ```
- Schemas already exist and validate against worked examples
  (`week4/schema/{dataset,model}_card.schema.json`, `validate.py`).

## Build order
1. **Schema update** — add `type: training|inference` to the dataset card schema; make
   `embedding`/`classes` conditional on type (training=polygons no-embedding; inference=features
   no-labels). Add `training`+`inference` dataset refs to the model card (`training.datasets`
   already there; add `inference.dataset` / feature-source field).
2. **Catalogue module** (`src/catalogue.py`) — CRUD over `data/catalogue/`: write/read/list cards,
   (re)build `index.json`, validate on write against the schemas. This is "the database."
3. **Auto-mint cards from live artifacts** — on retrain/split/add, emit a Model Card (lift
   `report`→metrics, hierarchy node→node/parent, joblib path→artifact) and the Dataset Cards for
   the sources used. Backfill cards for what's already on disk (base pooled, greenery split, barren
   mining) — reuse the week-4 example JSON as seeds.
4. **Backend endpoints** — `GET /api/catalogue` (list + filter by AOI/class), `GET /api/cards/{id}`,
   and have `/api/retrain` register a card. Wire the bbox `extent` (#3) on minted cards.
5. **Frontend** (#4, #5) — a catalogue/zoo panel: browse cards, see metrics + extent + provenance,
   "models good for my AOI". Show the card for the currently active model.
6. **Tea/non-tea demo** (#7) — drive trees → tea/non-tea via the existing split/retrain, confirm a
   Model Card + Dataset Cards get minted end-to-end. Pull tea polygons from the gpkg if usable.
7. Validate everything with `week4/schema/validate.py` (extend it to the live catalogue).

## Current state (verified)
- No `data/catalogue/` yet. Live: `data/refine/{greenery,barren}.joblib`, base
  `data/model_pooled.joblib`, examples `crops/mining/trees.geojson`.
- Hierarchy already has greenery→{crops,trees,shrubs} and barren→{barren_other,mining}.
- Worked example cards (week4/notes/examples) are valid seeds for the backfill.

## Open questions to confirm before/while coding
- Priority order: cards-DB backend first, or frontend-visible zoo first? (Proposal: backend+mint,
  then frontend panel, then tea/non-tea as the integration test.)
- For the inference dataset card: is its "feature source" just the embedding table the model
  samples (alphaearth/tessera over the extent), recorded as a card — or an actual persisted table?
- Tea polygons: is the gpkg the source, or will the user mark tea areas in the UI?