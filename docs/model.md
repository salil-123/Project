# Model

What the Core Stack LULC classifier is, what it was trained on, and how the
training dataframe was built. (For full metrics + methodology see `report.tex`;
for the end-to-end flow see `pipeline.md`.)

Classes are the IndiaSAT Level-1 scheme: **greenery, water, built_up, barren**
(plus `non_water` from the binary water asset, kept as a water-negative and dropped
at train time).

The web tool ships **two models** behind a mode switch. They are different models
trained on different data, so keep them straight.

---

## 1. Realistic mode (default): pooled Alpha Earth + WorldCover  (`data/model_pooled.joblib`)

The main model (`/api/classify?mode=realistic`, the UI default).

- **One `LinearSVC`** (`StandardScaler -> LinearSVC`) on the **64 Alpha Earth dims**.
- **Trained on a pool of two label sources:**
  - polygon pixels (`data/master_alpha_full.csv`, the pan-India Alpha-Earth set),
  - **ESA WorldCover** random-India points (`data/worldcover_train.csv`, ~9000 pts),
    which carry India's real ~92%-greenery class prior.
  - WorldCover rows get a per-sample weight of **`wc_weight = 2`** so the prior
    pulls predictions toward realistic greenery (suppressing false water) without
    drowning the expert polygon labels. WorldCover is scaffolding: lower `wc_weight`
    as user-contributed polygons grow.
- **No Tessera. Server-side only, no downloads** -> works instantly on any area.

**Accuracy:** ~83% on truly-random India (vs WorldCover reference) / ~83% on the
expert polygon holdout. Best all-around model.

---

## 2. Detailed mode: prior-aware Alpha Earth soft-voted with Tessera  (`data/model_softvote_reconciled.joblib`)

The secondary mode (`/api/classify?mode=detailed`). Leans toward rare-class
(water/barren) detail; needs Tessera at inference, so it downloads the area's tiles
on demand.

- **Two calibrated LinearSVC models**, probabilities averaged:
  - `ae_model`: prior-aware AE (calibrated LinearSVC on the same polygon + WorldCover
    pool as the Realistic model), **weight 0.7**.
  - `te_model`: calibrated LinearSVC on the **128 Tessera dims**, **weight 0.3**.
  - Predict = `0.7 * proba_ae + 0.3 * proba_te`, then argmax.

**Why prior-aware, and why only 0.3 on Tessera?** A naive balanced AE+Tessera
soft-vote (no prior) collapses to ~0.43 on random India because it ignores the
greenery prior. Putting the prior back on the AE side and down-weighting Tessera
recovers most of it (~0.77), but it still trails the Realistic model on real
locations -- Tessera's greenery--water edge only shows up on class-balanced tests.

---

## 3. How the training dataframe was built

The dual-embedding master `data/master_tessera.csv` (what the Tessera side trains
on). One row per ground-truth pixel:

```
polygon_id | core_class | lat | lon | ae_000..ae_063 | te_000..te_127
```
67,900 rows, 679 polygons, 196 columns.

Steps:

1. **Ground-truth polygons** from three GEE assets (`phase1_polygons.py`), each
   mapped into the common `core_class` scheme:
   | Asset | Path | Gives |
   |-------|------|-------|
   | IndiaSAT | `projects/ee-indiasat/assets/IndiaSat` | greenery / water / built_up / barren |
   | FarmForest GT | `projects/ee-indiasat/assets/Polygon_Groundtruth/FarmForest_Groundtruth` | greenery (crop=5, forest=6) |
   | GT_BINARY | `projects/ee-vatsal/assets/GT_BINARY_LATEST` | water (class 2) / non_water (class 1) |

   Combined to `data/raw_polygons/all_polygons.geojson` (2,416 polygons).

2. **Diverse polygon selection** (`select_diverse_tiles.py`): a weighted greedy
   set-cover over (1-degree block x class) pairs picks 200 Tessera tiles spread
   across India and balanced by class -> **679 polygons over 161 blocks**. This
   diversity is what fixed the earlier region-generalization gap.

3. **Tessera tiles downloaded** for those areas (`download_tiles.py`), year 2024.

4. **Embedding extraction** (`phase2_embeddings.py`):
   - up to **100 random interior pixels per polygon** (uniform in UTM 43N),
   - **Alpha Earth** (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`, 2024, 64-d): mosaic
     over the region, `sampleRegions` at 10 m, server-side,
   - **Tessera** (`geotessera`, 2024, 128-d): `sample_embeddings_at_points` at the
     same lat/lon, so the two embeddings join cleanly with no resampling.
   - Year 2024 for both (Tessera only has usable India coverage in 2024).

The Realistic model's `master_alpha_full.csv` is built the same way but
Alpha-Earth-only (`build_full_ae.py`) over more polygons (1,137, capped 300/class),
since Alpha Earth is free/server-side and needs no tile download.

---

## Data sources at a glance

| Source | Role | Used by |
|--------|------|---------|
| IndiaSAT, FarmForest, GT_BINARY (3 GEE assets) | class labels (polygons) | both models |
| Alpha Earth embeddings (64-d) | features | both models |
| Tessera embeddings (128-d) | features | Detailed model only |
| ESA WorldCover v200 | extra labels + real class prior | Realistic model + evaluation |