# Core Stack — Week 3 Plan

**Source:** `instructions_week3.txt`. **Builds on:** the week-2 base tool (4 classes —
greenery / water / built_up / barren — served by `src/{backend,infer,contributions}.py`
+ `src/static/`, models in `data/`). Week-2 plan archived at `week2/plan.md`.

## Goal of the week, in one line

Turn the static 4-class map into a **living hierarchy the user grows**: let them
**ADD** a new class or **SPLIT** an existing one by handing us example polygons, train
refinement classifier(s) on the fly, and lay the result over the base map — at a
real **10 m** resolution, with honest logging throughout.

## The two operations everything orbits around (instruction #11)

- **SPLIT** a class `d` into `d1, d2, d3`: user gives example polygons for *each*
  child. No negatives needed. The classifier only ever runs on pixels the base map
  already calls `d` (#22, #14).
- **ADD** a new class `e` somewhere in the tree: user gives positive example
  polygons + optional negatives + where it attaches. `e` may steal pixels from
  several existing classes (some `a`→`e`, some `b`→`e`, the rest stay) (#12, #23).
- **Key simplification (#24):** once ADD examples are overlaid on the raster, "which
  parent did this `e` come from" is known, so ADD decomposes into one SPLIT per
  affected parent. Both paths then share the same training core (#25 asks us to also
  try a single multiclass model and compare — see Phase 4).

---

## Build order / critical path

```
P0 provenance+logging ─► P1 hierarchy model ─► P2 example ingestion ─► P4 refine engine
                                    │                    │                     │
                                    └───────► P5 UI ◄─────┴──────────► P3 10m output
                                                                              │
                                                              P6 demos validate it all
```
P1 and P3 are independent and can go in parallel. P4 needs P1+P2. P5 ties them to the UI.

---

## Phase 0 — Provenance & hygiene (answer the questions, lay foundations)

Small, fast, unblocks trust in everything downstream.

- [ ] **0.1 — Write down how the week-2 data was selected** (instruction #1). Trace
  `week2/select_diverse_tiles.py` + `week2/phase2_embeddings.py` and answer in prose:
  which polygons, how the ~200 tiles were chosen, when/how class balancing happens,
  whether any pixels are dropped (e.g. `non_water`, NaN embeddings, the 100-px/poly
  cap). → `notes/data_provenance.md`.
- [ ] **0.2 — Logging.** Add a tiny `src/logsetup.py` (stdlib `logging`, one
  `get_logger(name)`), and thread INFO/DEBUG lines through `infer.py` and the new
  modules: bbox + grid size, #points sampled, #NaN dropped, model used, timings
  (instruction #2). No new deps.
- [ ] **0.3 — Decide the storage layout** for the new artifacts and create the dirs:
  - `data/hierarchy.json` — the class tree (Phase 1).
  - `data/examples/<node>.geojson` — user example polygons per node (Phase 2).
  - `data/refine/<op_id>.joblib` — trained refinement models (Phase 4).

## Phase 1 — The class hierarchy as data (the spine) — `src/hierarchy.py`

Everything else reads/writes this. Get the schema right first.

- [ ] **1.1 — Node schema** (instructions #16, #18, #20). One JSON node:
  ```json
  { "class": "greenery",            // canonical id, unique in the tree
    "name": "Greenery",             // human label
    "parent": "root",               // null for the root
    "classifier": null,             // op_id of the model that resolves its children
    "children": ["crops", "trees", "shrubs"] }
  ```
  Whole tree = `{ "root": {...}, "greenery": {...}, ... }` flat map keyed by `class`,
  so "where to add" is just inserting/patching a key (#20).
- [ ] **1.2 — Operations on the tree** (pure functions, no side effects beyond the
  file): `load()`, `save()`, `add_class(name, parent, canonical)`,
  `split_class(parent, [children])`, `validate()` (unique canonical names #16, no
  cycles, parent exists), `leaves()`, `path_to(class)`.
- [ ] **1.3 — Seed** the tree with the 4 base classes under `root` (instruction #9:
  base classes, improve from there). Ship `data/hierarchy.json` with that seed.
- [ ] **1.4 — Decision: one classifier per node vs one global multiclass** (#19).
  *Plan:* default to **per-node** (a node's `classifier` resolves only its own
  children — natural for SPLIT, cheap to retrain, isolates errors). Build the
  multiclass variant too in Phase 4 and let the bake-off (4.5) pick per case. Record
  the call in `notes/classifier_topology.md`.

## Phase 2 — Example ingestion → embeddings — `src/examples.py`

Turn user markings (drawn or uploaded) into labeled, embedded training rows.

- [ ] **2.1 — Normalize inputs** to one schema regardless of source:
  `{geometry, node, role: positive|negative, name}`. Accept **GeoJSON** and **KML**
  upload (#7, #15) and on-map **draw** (#17) — both land here. Volume of asked-for
  input scales with #new classes (#13).
- [ ] **2.2 — Sample embeddings at example polygons.** Reuse the week-2 approach
  (`week2/phase2_embeddings.py`): up to N interior pixels/polygon, Alpha Earth 64-d
  via GEE (and Tessera 128-d only if Detailed is in play). Factor the sampling out so
  both the archive and this share it.
- [ ] **2.3 — Mine the "stayed" + negative pixels for ADD** (#23, #24). For each
  parent the new class touches, pull base-map pixels of that parent *not* covered by
  the user's positives → they become the negative / "remained-`b`" class. This is the
  step that makes ADD look like SPLIT.
- [ ] **2.4 — Persist** examples to `data/examples/<node>.geojson` with their `class`
  field + canonical `name` (#15), linked to the tree node.

## Phase 3 — 10 m × 10 m output (instructions #3, #21) — DONE (Realistic mode)

Done by classifying the Alpha Earth image **server-side in Earth Engine** (the linear
models reproduced as band math) at native 10 m and returning one PNG overlay, instead
of point-sampling a coarse grid. Realistic mode only; Detailed (Tessera + calibration,
not EE-expressible) keeps the cell grid. See `infer.classify_bbox_raster`.

- [x] **3.1 — Native 10 m.** No more n×n grid: the whole AE image is classified at
  scale 10 server-side; `getThumbURL` sizes the PNG to ~10 m/px (capped at max_dim for
  very large boxes). A pixel is a real 10 m pixel.
- [x] **3.2 — Payload strategy.** One classified PNG per run (`L.imageOverlay`), not
  thousands of cells — bounded regardless of area. Class counts come from a server-side
  `frequencyHistogram`.
- [x] **3.3 — Correctness check.** Pixel-match test: the EE label image agreed with the
  sklearn pipeline 36/36 at sampled points (base + greenery split).

## Phase 4 — Refinement engine (the brains) — DONE — `src/refine.py`

Per-node split classifiers layered on the base map. Each child declares a data `source`
(examples / worldcover / residual); SPLIT and ADD share one trainer; inference composites
via `infer._final_label` (one EE band-math classifier per node).

- [x] **4.1 — SPLIT trainer** (#22, #14): `refine.train(parent)` trains a
  `StandardScaler → LinearSVC` on the parent's children, saves `data/refine/<parent>.joblib`,
  registers it on the node. (greenery → crops/trees/shrubs, macro-F1 0.88.)
- [x] **4.2 — ADD trainer** (#23): `refine.add_class_op` = SPLIT with an auto residual
  that keeps the parent's identity. Demo `scripts/add_mining.py`: barren → "Barren" +
  Mining (mining F1 0.87). Composites on the 10 m raster with no inference change.
- [x] **4.3 — Relabel / hard-negatives** (#4, #5): `refine.relabel` (positives of the
  true class) + `refine.add_hard_negatives` (negatives routed to the residual sibling).
  Refinement-layer only; base-class corrections need a base refit (noted).
- [x] **4.4 — Layering / apply.** `infer._apply_refinements` (point path) +
  `infer._final_label` (raster): base → each node's split where its parent was predicted.
- [x] **4.5 — Bake-off: per-node vs flat multiclass** (#19, #25). `refine.bakeoff`:
  flat 0.885 acc / 0.777 macro-F1 vs hierarchical 0.862 / 0.750 — flat ~2 pts better
  offline, but per-node kept as default for cheap incremental retrains + error isolation.
  Verdict in `notes/classifier_topology.md`.

NOTE: fixed an EE bug found here — binary LinearSVC has `coef_` shape `(1,64)`, so the
raster path now uses sign-of-score for 2-class splits (argmax only for ≥3). Pixel-match
EE-vs-sklearn 36/36 with both greenery + mining splits active.

## Phase 5 — Wire it into the live tool — DONE — `src/backend.py` + `src/static/`

Real hierarchy-aware endpoints + UI replace the week-2 stubs and the generic
`contributions.py` flow. Operations run synchronously (FastAPI threadpool) with a
"working…" UI state; `find_similar` deferred. Insight: relabel + hard-negatives are just
`POST /api/examples` (positive = relabel, negative = hard-negative), so no extra endpoint.

- [x] **5.1 — Hierarchy API:** `GET /api/tree`, `POST /api/split`, `POST /api/add`
  (any level) over `hierarchy.py` + `refine.py`; mutating calls reload the cached models.
- [x] **5.2 — Examples API:** `POST /api/examples` (drawn geometry) + `POST
  /api/examples/upload` (multipart GeoJSON/KML, both verified) → `examples.py`.
- [x] **5.3 — Retrain endpoint:** `POST /api/retrain {node}` → `refine.retrain` (root →
  base model, else the node's split), returns held-out metrics; live greenery retrain
  via the API gave acc 0.963 and the map re-rendered crops/trees/shrubs.
- [~] **5.4 — `find_similar`** — deferred (per decision), to a follow-up.
- [x] **5.5 — UI:** clickable hierarchy tree, per-class example draw/upload (positive/
  negative), Split / Add / Retrain panels with metrics; the 10 m raster updates after
  each op. Stub buttons + generic contribute removed.

Fixed in passing: `read_geometries` raised on uploads whose geometry column was already
named "geometry"; now builds a clean geometry-only frame (GeoJSON + KML both load).

## Phase 6 — Demos that prove it works — DONE (Beamer slides + figures)

Deliverable: `slides_week3.tex` → `slides_week3.pdf` (10 frames), with before/after map
figures generated by `scripts/make_demo_figures.py` into `figures/`.

- [x] **6.1 — SPLIT greenery → crops / trees / shrubs** (#26): metrics (acc 0.963) +
  before/after figure on a farm scene.
- [x] **6.2 — ADD mining under barren** (#27): metrics (acc 0.856) + before/after figure
  on a mining scene.
- [~] **6.3 — Acacia vs non-acacia trees** (#28): still **parked** (polygons not shared);
  the slides note the trees→acacia split is ready to drop in.
- [x] **6.4 — Report**: per-class P/R/F1 tables + before/after maps for both demos, plus
  the bake-off, any-level recursion (36/36 pixel-match), and the interactive loop.

Figures come from `infer.classify_bbox_raster` with `refinements={}` (before) vs the live
splits (after); new optional `colors=` param renders greenery/barren in base colours for
the "before" image.

---

## Deliverables this week
1. `src/hierarchy.py` + seeded `data/hierarchy.json` — the editable class tree.
2. `src/examples.py` — draw/upload → embedded labeled rows.
3. `src/refine.py` — SPLIT/ADD/relabel trainers + the per-node-vs-multiclass bake-off.
4. 10 m output in `src/infer.py`.
5. Real retrain/suggest endpoints + hierarchy UI in `src/backend.py`/`src/static/`.
6. Demo 6.1 (greenery split) working end-to-end, with metrics.
7. `notes/data_provenance.md` + `notes/classifier_topology.md`.

## Open questions to resolve while executing
- **One classifier per node vs one multiclass?** (1.4 / 4.5 — decide by measurement,
  not assumption — #19.)
- **10 m payload:** per-cell GeoJSON vs raster array vs vector tiles? (3.2)
- **ADD negatives:** when the user only marks the new class, do we always auto-mine
  the "stayed" pixels from the base map, or require explicit negatives? (2.3 / #23)
- **Probabilities for refinement:** the base `LinearSVC` has no `predict_proba`; swap
  to a calibrated/LogReg model where uncertainty drives the UI? (carryover from
  week-2 plan 5.5)
- **Canonical-name collisions** across a deep tree (1.2 validate).

## Reuse map (don't rebuild what week 2 already has — see `week2/`)
- Embedding sampling: `phase2_embeddings.py`. Honest eval: `multi_seed_compare.py`.
- Base models + provenance: `model.md`, `pipeline.md`. Tessera fast fetch:
  `tessera_fast.py` (root). EE init: `config.py` (root).