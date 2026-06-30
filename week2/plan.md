# Core Stack — Weekly Task Plan

LULC (Land Use / Land Cover) classification from satellite embeddings, with an
interactive human-in-the-loop refinement layer.

**End goal of the week:** build a labeled pixel dataframe combining *Alpha Earth*
and *Tessera* embeddings, train + evaluate a base classifier (greenery / water /
built-up), then let a user inspect predictions, mark errors, introduce new classes
(e.g. orchard, tea plantation), and retrain on the fly.

---

## Phase 0 — Environment & accounts setup

- [ ] **0.1** Create a Python project (recommend `conda`/`venv`, Python 3.10+).
  Pin a `requirements.txt` / `environment.yml`.
- [ ] **0.2** Install core libs:
  - `earthengine-api` + `geemap` (Google Earth Engine access & visualization)
  - `geotessera` (Tessera embeddings)
  - `geopandas`, `shapely`, `rasterio`, `pyproj` (geospatial)
  - `xarray`, `zarr` (Tessera returns a 2D array in zarr)
  - `pandas`, `numpy`, `scikit-learn` (dataframe + classifier)
  - `folium` / `ipyleaflet` (interactive map for the refinement UI)
- [ ] **0.3** Authenticate Earth Engine: `earthengine authenticate`. Confirm
  access to the project assets listed in the task:
  - `projects/ee-indiasat/assets/IndiaSat` (broad 4-class LULC)
  - `projects/ee-indiasat/assets/Polygon_Groundtruth/FarmForest_Groundtruth`
  - `projects/ee-mtpictd/assets/GTSeasonal`, `.../GTPerennial`
  - `projects/ee-vatsal/assets/GT_BINARY_LATEST`
  - `ee_chahat` assets (primary ground truth for this task)
- [ ] **0.4** Open the source spreadsheet and pull the **first four rows** that
  define the core-stack class mapping:
  https://docs.google.com/spreadsheets/d/1xS5d7vgyjyoqqnmmajKDZBx9qS6GqyAdSbNDR62ot2Y/edit?gid=1864114429
  Record the exact class definitions in a `notes/classes.md`.

---

## Phase 1 — Ground-truth polygon acquisition

Target classes (collapse source labels into these 3 to start):

| Core class | Source polygons |
|------------|-----------------|
| **Greenery** | tree polygons + crop/farm polygons (FarmForest_Groundtruth, IndiaSat tree/crop) |
| **Water** | seasonal + perennial water (GTSeasonal, GTPerennial), water from GT_BINARY |
| **Built-up** | built-up class from IndiaSat |

- [x] **1.1** Export the relevant GEE assets to **GeoJSON**. DONE for the 3
  accessible assets (IndiaSat, FarmForest, GT_BINARY) via `phase1_polygons.py` ->
  `data/raw_polygons/`. `ee_chahat` + `ee-mtpictd` water still pending sharing.
- [x] **1.2** Standardize each polygon record to a common schema:
  `polygon_id, source, raw_class, core_class, geometry`. DONE.
- [x] **1.3** Inventory the data (polygon counts per class). DONE:
  built_up 1391, greenery 349, barren 276, water 251, non_water 149.
  NOTE: heavy imbalance (built_up dominant); `non_water` is ambiguous — exclude
  from training or use only as water-negatives.
- [x] **1.4** Dev **bounding box** chosen: N. Karnataka, all 5 classes present.
  bbox [W,S,E,N] = [74.9835, 15.3907, 75.0878, 15.6818], saved to
  `data/dev_area.json` (9 polygons: 2 greenery, 2 water, 2 barren, 2 non_water,
  1 built_up).

---

## Phase 2 — Embedding extraction (the core engineering piece)

For every ground-truth pixel we need **two** embedding vectors.
Implemented in `phase2_embeddings.py`.

**CONFIRMED DECISIONS:**
- **YEAR = 2024 for BOTH sources.** Tessera only has usable India coverage in 2024
  (other years are all-NaN; tile counts: 2024=1.59M vs ~345k others). Alpha Earth
  has 2024 too. ~2yr after GT marking but classes are stable. (Overrode initial 2022.)
- Tessera values: **dequantized float32** (`sample_embeddings_at_points` default).
- **<=100 random interior pixels/polygon** (sampled uniformly in UTM 43N).
- **Both sources sampled at the SAME polygon-interior lat/lon points** -> clean join,
  no resampling. Alpha Earth = 64-d (A00..A63), Tessera = 128-d -> concatenate.

### 2a. Tessera embeddings (geotessera)
- [x] **2.1** API learned: `sample_embeddings_at_points(pts, year)` -> float32 (N,128).
  Tile = (1106,1073,128) float32, EPSG:32643, 10m. NOTE: `check_tiles_present` is
  unreliable (optimistic) — trust actual sampling.
- [x] **2.2** `sample_tessera(pts_gdf, year)` done in `phase2_embeddings.py`.
- [~] **2.3** **Benchmark** IN PROGRESS: dev = 270 pts / 9 polygons span 3 tiles.
  Cold full-tile fetch measured ~23 min/tile earlier. Measuring sampling cost now.
- [ ] **2.4** **Parallelize** by TILE (not point): first point per tile triggers the
  whole-tile download; group points by tile, fetch tiles concurrently. Tune count.

### 2b. Alpha Earth (Google Earth) embeddings
- [x] **2.5** DONE: `sample_alpha_earth()` mosaics the year's collection over the
  region (`.first()` alone grabs an arbitrary global tile -> NaN) then sampleRegions
  at scale=10. Validated 270/270 dev points have data.
- [x] **2.6** Alignment handled by sampling both at identical lat/lon points.

---

## Phase 3 — Build the master dataframe (instruction #6, #9.i)

STATUS: Alpha Earth half DONE (`data/master_alpha.csv`, 68k rows, 0 NaN, 680
polygons across 47 tiles). Tessera half pending tile download (`download_tiles.py`
running). Selection frozen in `select_tiles.py` / `data/selected_*`.

- [ ] **3.1** Construct one row per pixel with columns:
  ```
  polygon | pixel | lat | long | alpha_earth_emb[...] | tessera_emb[...] | class
  ```
- [ ] **3.2** Append incrementally to **CSV** (or parquet) as polygons are
  processed, so long runs are resumable (instruction #13).
- [ ] **3.3** Sanity checks: no NaNs in embeddings, class balance, dedupe pixels,
  verify lat/long fall inside their polygon.

---

## Phase 4 — Base classifier (instruction #9.ii)  — `train_classifier.py`

BASELINE DONE on Alpha Earth: RF acc 93.9%, macro-F1 0.86. built_up & barren
near-perfect (F1 ~0.998); WEAKNESS = water<->greenery confusion (water recall 0.55,
~914/2100 water pixels predicted greenery). Tessera/combined comparison pending.

- [x] **4.1** Split BY POLYGON (GroupShuffleSplit on polygon_id) — avoids pixel
  leakage. class_weight='balanced'. Dropped ambiguous 'non_water'.
- [x] **4.2** LogReg + RandomForest done for Alpha (ae). TODO: te-only + ae+te
  comparison parked (Tessera download too slow) — see RUN_TESSERA_LATER.md.

### PAN-INDIA RETRAIN (the real fix — `build_full_ae.py` + `train_spatial.py`)
- Root cause of poor generalization was DATA diversity, not embeddings. AE is free/
  server-side, so we trained on all-India (1137 polygons, 204 spatial blocks).
- Honest eval = hold out whole 1x1-deg REGIONS. Result: 71% -> **82.9% (LogReg)** /
  81.6% (RF) on unseen regions. barren recall 0.46->0.89, water 0.65->0.87.
- LogReg generalizes better than RF out-of-region. Residual weakness: water<->greenery.
- Artifacts: `data/master_alpha_full.csv`, `data/model_rf_ae_full.joblib`.

### TESSERA — PARKED (retry on fast connection)
- 47-tile set frozen (`data/selected_*`). Download ~42 min/tile (~0.47 Mbps/stream)
  on dev connection => parked. Scripts ready: `download_tiles.py` (parallel, resumable),
  then steps in `RUN_TESSERA_LATER.md`. Only enhancement experiment, not a blocker.
- [x] **4.3** Evaluate: precision, recall, F1 per class on honest splits. DONE.
- [x] **4.4** Persist trained model + metrics. DONE.

### FINAL MODEL DECISION (2026-05-24) — locked, plugged into the web tool
After downloading a DIVERSE 200-tile Tessera set (`select_diverse_tiles.py`,
679 polys / 161 blocks, balanced) and an 8-seed region-held-out comparison
(`multi_seed_compare.py`):
- **Best model type = LinearSVC** (linear beats RF/GBT out-of-region):
  AE-alone LinearSVC = acc 0.825 / macroF1 0.789 / water-rec 0.823.
- **Best data combo = Alpha Earth ONLY** (drop Tessera). AE+Tessera (0.812/0.776/
  0.788) did NOT beat AE-alone on honest, diverse, nationwide-disjoint data —
  yesterday's "Tessera wins" was an artifact of the clustered built_up-heavy test
  set. So Tessera is dropped from the live tool => instant server-side GEE
  inference, no per-area tile download, simpler arch, AND better numbers.
- **Label source = diverse pan-India polygons (master_alpha_full, 1137 polys/204
  blocks) POOLED with WorldCover**, `wc_weight=2` (`save_pooled_model.py`):
  87.4% truly-random India + 83.2%/0.82 expert-polygon holdout. wc_weight is a
  one-line dial to lower as user polygons accumulate (WorldCover = scaffolding).
- Artifact = **`data/model_pooled.joblib`** (64 AE dims, LinearSVC). `infer.py`
  already loads this path, so the web tool serves it on restart. No wiring left.

### BEST-WITH-WHAT-WE-HAVE: soft-vote high-accuracy mode (2026-05-24)
Pushed past 0.80 using ONLY AE+Tessera (no NDVI, reserved for later). The greenery
weakness is greenery<->WATER (AE leak 0.32), not barren. Fusion experiments
(confusion_check.py / fusion_check.py / tune_softvote.py):
- naive concat AE+TE = muddy middle. SOFT-VOTE (average two models' probabilities)
  keeps AE's built_up strength AND Tessera's greenery fix.
- BEST = soft-vote of two CALIBRATED LinearSVC models (AE + TE):
  **acc 0.854 / macro-F1 0.808** region-held-out (5 seeds); greenery recall
  0.485->0.562, greenery->water 0.321->0.246, built_up 0.860->0.876.
- Saved `data/model_softvote.joblib` (save_softvote_model.py). Wired as the tool's
  "accurate" mode (`infer.classify_bbox_softvote`, `/api/classify?mode=accurate`,
  UI dropdown). Needs Tessera at inference -> per-area tile download on demand.
- CAVEAT: soft-vote is balanced-trained (no WorldCover prior; WC points lack TE),
  so on greenery-dominant areas it over-calls barren/water vs the instant pooled
  model. Reconcile later by soft-voting the WC-pooled AE model with the TE model.
- Two-mode tool: instant=AE pooled (browsing), accurate=soft-vote AE+TE (best F1).

---

## Phase 5 — Inference + interactive refinement (instruction #9.iii–iv)

MINIMAL UI BUILT — FastAPI backend + plain HTML/CSS/JS + Leaflet frontend
(`backend.py` + `static/{index.html,style.css,app.js}` + `infer.py` + `contributions.py`).
Run (from repo root): `uvicorn backend:app --reload --app-dir src` then open http://127.0.0.1:8000/.
JSON API (`/api/classify`, `/api/contribute`, stubbed `/api/retrain` etc.) so the
frontend is swappable and easy for anyone to integrate. (Streamlit version scrapped.)

- [x] **5.1** Inference + color-coded map DONE: `infer.classify_bbox()` samples AE
  on a grid over a bbox, predicts with pooled model; `app.py` draws colored cells
  on a folium satellite map (presets + custom lat/lon + grid-resolution slider).
- [~] **5.2** Interactive elements: Draw tool (polygon/marker) + label input +
  GeoJSON uploader present in UI. Markings persist via `contributions.add_contribution`.
  Upload ingestion = stub.
- [~] **5.3** New-class introduction: UI has "NEW class" checkbox; `known_classes()`
  picks up new labels. Capturing embeddings for them = part of retrain stub.
- [ ] **5.4** Similarity suggestion: `contributions.find_similar()` STUB (NotImplemented).
- [ ] **5.5** On-the-fly retraining: `contributions.retrain_with_contributions()` STUB.
  For retraining/uncertainty UI, swap pooled LinearSVC -> calibrated/LogReg (has proba).

---

## Phase 6 — Toward a shared evolving dataset (instruction #10–15) - NO NEED TO DO THIS

- [ ] **6.1** Design the **common repository** schema for contributed pixels/
  polygons (wikipedia-style evolving GT). Decide storage (shared CSV/parquet,
  DB, or GEE asset) and how users "share their pixels publicly".
- [ ] **6.2** Plan the pan-India uniform sampling strategy for a future base
  dataset (diversity of tree/crop/etc appearances).
- [ ] **6.3** Per-class pixel counts → define **targeted contribution asks**
  ("please mark class X here") for under-represented classes.
- [ ] **6.4** (Later, note only) NDVI-over-time crop-health track instead of
  embeddings — out of scope this week, stub it for future.

---

## Deliverables for this week
1. `build_dataframe.py` — GT polygons → dual-embedding pixel dataframe (CSV).
2. The dataframe itself + a per-class pixel-count inventory.
3. `train_classifier.py` — trains & evaluates, outputs precision/recall report.
4. A notebook/app demoing the interactive map + on-the-fly refinement.
5. `notes/` — benchmarks (download time, optimal parallelism), class mapping.

## Open questions to resolve while executing
- Exact pixel resolution to standardize Alpha-Earth vs Tessera grids.
- Whether to split train/test by pixel or by polygon (recommend polygon).
- Optimal parallel-request count for geotessera (measure in 2.4).
- Storage backend for the shared evolving dataset (6.1).
