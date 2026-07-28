# Week 7 — implementation tracker

Approved plan: `~/.claude/plans/these-are-the-words-declarative-mango.md`. Source asks:
`week7_instructions.txt`. This file is the live build log.

## Scope (locked with the user)
Core-3 engineering (#3 temporal, #4 adequacy, #5 validation) + stress-test **sites as presets**
(#7/#9/#11) + **WorldCover-direct** analysis (#2) + a light **Tessera-as-choice** note (#6).
Deferred by sir: mining segmentation (#8), biomass/GEDI (#1, the user's own). Live model demos
are file-driven (GT already on disk) and executed in a follow-up live-GEE session.

## Checklist
- [x] **Sites (#7/#9/#11)** — 3 presets added to `backend.PRESETS`: IIT Delhi + Sanjay Van
  (acacia), Jalpaiguri (base-scheme demo), Asola Bhatti (mining/acacia). Verified `/api/presets`.
- [x] **Acacia ingestion** — `scripts/prep_acacia_examples.py` turns the raw
  `acacia_clean_confident_labels.geojson` (912 confident crowns) into
  `data/examples/acacia.geojson` (336) + `data/examples/non_acacia.geojson` (576) in the
  node/role format, and relocated the raw file to `data/inputs/`. Ran, verified counts.
- [x] **Adequacy coverage (#4)** — `catalogue._coverage` (labelled area ÷ AOI area, equal-area
  EPSG:6933, buffer(0)-repaired) + `recompute_spread(..., aoi=)`; `GET /api/cards/{id}/spread`
  takes `w,s,e,n`; UI shows "covers X% of the current AOI" via `currentBbox()`. Verified: tea
  polygons cover 0.59% of the Assam box, ~0% of all-India (AOI-size-contingent, as intended).
  Note: chose **area coverage** over the plan's grid-cell ratio — the latter collapses to 100%
  when the AOI is smaller than one grid cell (all our stress strips), so it was unusable.
- [x] **JSON pre-flight validator (#5)** — `src/validate_ops.py` (`validate_envelope`,
  `missing_classifiers`). Single flow: **one upload** that validates then applies — `POST
  /api/hierarchy/import` checks the whole envelope first and rejects a bad file with 400
  `{errors,warnings}` before mutating; nothing else to click. Verified on good + doctored envelopes
  (unknown op, missing arg, broken tree, missing classifier warning).
- [x] **Temporal robustness (#3)** — `refine.build_split_dataset`/`train` now take **`years=[...]`**
  and pool multiple years into one split (same polygon across years shares its group id, so holdout
  stays leak-free); `year` also threaded through `_child_frame`/`_residual_rows`/`_negatives_frame`
  (cache keyed by the year set). `src/temporal_eval.py` trains a single-year baseline vs a multi-year
  pooled model, holds out whole polygons **and** whole eval years, and saves the pooled model;
  `--matrix` gives the finer single-year grid. `valid_years`/Tessera notes on `/api/inference-options`
  shown in the year picker (#6). **Live multi-year acacia run** (train 2019/2021/2023, test unseen
  2020/2024): single-year baseline 0.635 → **multi-year 0.745 (+0.110)** on the unseen years — the
  pooled model is measurably more temporally robust. Model saved to
  `data/refine/acacia_non_acacia_multiyear.joblib`; log in `week7/acacia_multiyear.log`.
  **Base classes** (greenery/water/built_up/barren from `selected_polygons.geojson`, same protocol):
  single 0.888 → multi 0.891 (+0.003) — already temporally stable, so multi-year barely moves them.
  The honest finding: multi-year robustness pays off on **fine** splits (acacia), not on the coarse
  base classes. `temporal_eval.py` gained a `--from-file` mode to sample any labelled polygon set;
  log in `week7/base_multiyear.log`, model `data/refine/base_multiyear.joblib`.
- [x] **WorldCover-direct (#2)** — `week7/notes/worldcover_direct.md` (analysis, no code).
- [x] **Tessera-as-choice (#6)** — note wired into `/api/inference-options` + year picker.
- [x] **Docs** — this tracker, `week7/demo.md`, `master_document.md` updated.

## Site test results (`week7/site_tests.py`, live GEE)
- **Tea vs non-tea:** 0.957 held-out accuracy.
- **Acacia vs non-acacia:** 0.745 on unseen years (multi-year) — a genuinely hard species split.
- **Mining detector:** 0.859 accuracy, 0.854 recall on real mines (positive control), 0.139
  false-positive rate on non-mining ground truth.
- **Mining false-positive, active vs reclaimed (same detector):** **Jharia active coalfield 71.2%**
  flagged vs **Asola reclaimed 17.1%** — a 4× gap. The active site is the positive control proving the
  model finds real mines; Asola's 17% is a real false-positive tendency on reclaimed mine-like ground,
  as sir predicted (also 0.854 recall on held-out mines, 0.139 clean false-positive rate).
- Log: `week7/site_tests.log`. Numbers are on the "Testing on the sites" slide.

## Deferred to the live session (yours)
- The Jalpaiguri base-scheme + operations demo (split/add from a base), which sir will ask for live.
- On-map click-through of the acacia/tea/mining sites.

## Fixes during week 7
- **Zoo model "vanished" on retrain.** A node holds one classifier (one `data/refine/{node}.joblib`,
  one `mc_{node}_v1` card), so re-splitting a node into a *different* split (greenery: tea/non_tea →
  acacia/non_acacia) overwrote both and the old model disappeared. Fix: `catalogue.snapshot_model` +
  `archive_prev_card`, wired into `/api/retrain` — when a retrain genuinely changes the split, the old
  model is kept as an archived card `mc_{node}_prev{k}_v1` pointing at a snapshotted joblib; a plain
  retrain (same classes) archives nothing. ("Only 4 models" was correct for the tree: root + WorldCover
  base + greenery + barren.) Note: a node still holds one *live* split at a time; the archived card is
  history/reference, not simultaneously live.
- **UI "area doesn't load".** Edited `app.js`/`index.html` without bumping the cache-bust version, so a
  stale cached `app.js` ran against fresh HTML and threw on a removed element. Bumped `?v=5 → ?v=6`.

## Notes / decisions
- Acacia label column: `label_acacia_clean_confident` (1=acacia 336, 0=non-acacia 576, -1 skip).
- Coverage uses EPSG:6933 (equal-area) so areas are in m²; crowns must be `buffer(0)`-repaired
  or `unary_union` throws a TopologyException on the raw (self-intersecting) polygons.
- The base model can't be made multi-year cheaply (its CSVs have no year column, Tessera is
  2024-only), so temporal robustness lives on the example/split path — the same axis inference
  already sweeps.
