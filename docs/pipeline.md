# Pipeline

End-to-end flow, from raw ground truth to live predictions in the web tool.
Each stage lists its script, what goes in, and what comes out.

```
GEE assets ──► polygons ──► diverse subset ──► Tessera tiles ──► dual-embedding
                                                                  master dataframe
                                                                       │
                                              ┌────────────────────────┴───────────┐
                                              ▼                                     ▼
                                   reconciled soft-vote model           pooled model
                                   (prior-aware AE + Tessera)           (AE + WorldCover)
                                              │                                     │
                                              └──────────────► FastAPI backend ◄─────┘
                                                                   │
                                                              Leaflet web UI
                                                    (Detailed mode / Realistic mode = default)
```

---

## Stage 1 — Ground truth (`phase1_polygons.py`)

- **In:** three GEE FeatureCollections (IndiaSAT, FarmForest, GT_BINARY).
- **Does:** reads each, maps its raw property to the common `core_class`
  (greenery / water / built_up / barren / non_water), tags `polygon_id` + `source`.
- **Out:** `data/raw_polygons/all_polygons.geojson` (2,416 polygons).

## Stage 2 — Diverse selection (`select_diverse_tiles.py`)

- **In:** all polygons.
- **Does:** weighted greedy set-cover over (1-degree block x class) pairs, picking
  tiles that spread geographically and balance classes. Scarce classes
  (water / barren / greenery) drive the spread; built_up fills trivially.
- **Out:** `data/selected_tiles.json` (200 tiles), `data/selected_polygons.geojson`
  (679 polygons over 161 of India's 207 blocks).

## Stage 3 — Tessera download (`download_tiles.py`)

- **In:** the selected tile list.
- **Does:** parallel, resumable download of the 0.1-degree Tessera tiles for 2024.
  Idempotent (skips cached tiles); landmasks auto-fetched at sampling time.
- **Out:** `global_0.1_degree_representation/2024/grid_*/*.npy` on disk.

## Stage 4 — Embedding extraction (`phase2_embeddings.py`)

- **In:** the selected polygons + the downloaded tiles + Earth Engine.
- **Does:**
  - samples up to 100 random interior pixels per polygon (uniform in UTM 43N),
  - Alpha Earth 64-d per point (GEE mosaic of `SATELLITE_EMBEDDING/V1/ANNUAL` 2024,
    `sampleRegions` at 10 m),
  - Tessera 128-d per point (`sample_embeddings_at_points`, 2024) at the same
    lat/lon so the join is exact.
- **Out:** `data/master_tessera.csv` — `polygon_id, core_class, lat, lon,
  ae_000..063, te_000..127` (67,900 rows).

  (Sibling: `build_full_ae.py` makes `data/master_alpha_full.csv`, Alpha-Earth-only
  over 1,137 polygons, for the pooled model. `worldcover_train.csv` is ~9,000
  random-India points labeled by ESA WorldCover, with Alpha Earth embeddings.)

## Stage 5 — Training

Two deployed models, for the two modes:

- **Pooled / Realistic** (`save_pooled_model.py --wc-weight 2`) ->
  `data/model_pooled.joblib`. One LinearSVC on AE, trained on
  `master_alpha_full.csv` pooled with `worldcover_train.csv` (WorldCover rows
  weighted 2x). The WorldCover prior keeps it calibrated to India's real
  land-cover mix, so it's the strongest on random/real locations (~0.83 acc).
- **Reconciled soft-vote / Detailed** (`reconciled_softvote.py`) ->
  `data/model_softvote_reconciled.joblib`. Soft-vote of a *prior-aware* AE model
  (calibrated LinearSVC on the same polygon+WorldCover pool) at weight 0.7 with a
  calibrated Tessera LinearSVC at 0.3. Leans toward rare-class detail; trades a bit
  of real-location accuracy for it.

Why not just one model? Validation showed plain AE+WorldCover is the best
all-around (AE alone ~= AE+Tessera on balanced CV; a naive balanced AE+Tessera
soft-vote collapses to ~0.43 on random India because it ignores the prior). The
reconciled Detailed model adds the prior back so it behaves, but still trails
Realistic on real locations. Validation scripts: `multi_seed_compare.py`,
`confusion_check.py`, `fusion_check.py`, `tune_softvote.py`,
`reconciled_softvote.py` (region-held-out + a random-location test with both
embeddings, `build_random_te_eval.py`).

## Stage 6 — Serving (`backend.py` + `infer.py`)

- **`infer.py`** does the inference:
  - `classify_bbox` (Realistic): grid-samples Alpha Earth over a bbox, predicts with
    the pooled AE+WorldCover model. All server-side, **no Tessera, no downloads** -
    works instantly on any area, seen or unseen.
  - `classify_bbox_softvote` (Detailed): grid-samples *both* Alpha Earth (GEE) and
    Tessera at the same points, soft-votes. Tessera tiles for an unseen area are
    downloaded on demand here (geotessera's own auto-download, ~1-4 tiles per small
    box, roughly sequential - not the parallel `download_tiles.py` used for training).
- **`backend.py`** (FastAPI) loads both models once and exposes:
  - `GET /api/classify?...&mode=realistic|detailed` -> grid of predicted cells
    (`realistic` is the default),
  - `GET /api/health`, `GET /api/presets`,
  - `POST /api/contribute`, `GET /api/contributions` -> user markings store,
  - stubbed `POST /api/retrain`, `/api/suggest-similar`, `/api/publish`.

## Stage 7 — Web UI (`static/index.html`, `style.css`, `app.js`)

- Leaflet satellite map. Pick a preset or custom lat/lon, choose grid resolution
  and **mode** (Realistic default / Detailed), hit Run -> colored class overlay.
- Draw tool + label box to contribute polygons/markers (including new classes);
  markings persist to `data/contributions.geojson`.
- Run (from repo root): `uvicorn backend:app --reload --app-dir src`, open http://127.0.0.1:8000/.

---

## Inference path per mode

| | Realistic (default) | Detailed |
|--|---------------------|----------|
| Model | pooled AE + WorldCover | reconciled soft-vote: prior-aware AE (0.7) + Tessera (0.3) |
| Embeddings fetched | Alpha Earth (server-side) | Alpha Earth + Tessera (tiles on demand) |
| Downloads on unseen area | none | yes (Tessera tiles), then cached |
| Accuracy on random India | ~0.83 | ~0.77 |
| Best for | browsing anywhere, real-world use | leaning into rare-class (water/barren) detail |