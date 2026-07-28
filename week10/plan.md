# Week 10 — build log / running checklist

Asks in scope: #1 (STACD audit), #3 (biomass), #4 (mining segmentation), #6 (estimate + notify),
#7 (RF on EE / XGBoost on Tessera), #8 (acacia spatial+temporal). Order: 7 → 3 → 4 → 6 → 8 → 1.

Approved plan: `~/.claude/plans/plan-to-implement-1-3-4-6-7-8-soft-treehouse.md`.

## #7 — RF for Alpha Earth, XGBoost for Tessera  ✅ (benchmark regen pending)
- [x] add `xgboost` to requirements.txt + install into .venv (xgboost 3.3.0)
- [x] `refine.model_families`: offer randomforest on alphaearth (point-grid note)
- [x] `refine.train`: allow randomforest on ae; keep others linear-only on ae
- [x] `infer`: `_is_nonlinear` + `NONLINEAR_ALGOS`; drop non-linear AE from band-math path
- [x] `backend.classify`: `grid_live = tessera OR (ae & non-linear)` -> force point grid
- [x] frontend: RF shows for AE via /api/model-families + point-grid tooltip
- [~] benchmark profile: added xgboost to ALGOS; regenerating profile
- [x] verify LIVE: RF greenery split dropped from tiles (no crash), applied on point grid

## #3 — Biomass (GEDI collection + app/zoo)  ✅
- [x] `scripts/prep_gedi_biomass.py` — LIVE: 158 shots over Jalpaiguri box (agbd+slope+emb_0..63)
- [x] `scripts/train_biomass.py` — RF regressor; AEZ-8 spatial R2 0.22 / random-split 0.33; mints card
- [x] `infer.classify_biomass_grid` + `biomass_models`/`load_biomass`/`_sample_ae_slope`
- [x] `GET /api/biomass` — LIVE 200, graded AGBD grid
- [x] `regression` topology in schema + `catalogue.mint_biomass_card` + `sync_biomass_cards` at startup
- [x] frontend 🌲 Map biomass button + green ramp legend (v=17)
- [x] verify: graded AGBD grid live; card validates; random-split R2 in Ratinder's raw ballpark

## #7 benchmark  ✅
- [x] regenerated data/benchmark_profile.json — fit algos now linearsvc/logreg/ridge/randomforest/xgboost

## #4 — Mining segmentation (vectorize)  ✅
- [x] `infer.segment_class` (EE focalMode clean + reduceToVectors + min-area filter)
- [x] `GET /api/segment` (bad class -> 400)
- [x] frontend ⛏ Segment mining overlay + ⬇ GeoJSON download
- [x] `config.SEGMENT_MIN_AREA_HA`
- [x] verify LIVE: 9 clean mining segments on Asola Bhatti (0.51–1.5 ha), speckle filtered

## #6 — Estimate + notification  ✅
- [x] `fetchEstimate` + `startWorkTimer` wired into doRetrain
- [x] live elapsed-vs-expected timer on the work toast
- [x] estimate covers RF/XGBoost (profile regenerated); accuracy note written
- [x] verify: estimate within ~2x of a real retrain (49s est vs 92s actual), ranks algos

## #8 — Acacia spatial + temporal  ✅
- [x] persist `area`/`crown_uid` in prep_acacia_examples (re-ran: 336 acacia / 576 non_acacia)
- [x] carry `area` through examples.build_training_frame (non-breaking, only when present)
- [x] `week10/acacia_robustness.py`: region x year holdout + per-year aggregate
- [x] verify LIVE: temporal 0.716 / spatial 0.695 / combined 0.673; 2024 flagged as fluke (spread 0.234)

## #1 — STACD audit  ✅
- [x] fix alg_name -> instance ref (base::root); Algorithm_Instance gets `id`; Dataset_Instance type note
- [x] `week10/notes/stacd_audit.md` (class-by-class table, shareable)
- [x] verify: stacd smoke test passes with instance ids

## Docs
- [x] add §9 Week 10 to master_document.md
- [x] final full-app smoke: health/model-families/estimate/stacd/biomass/segment/classify all pass at v=17

ALL SIX ITEMS (#1,#3,#4,#6,#7,#8) IMPLEMENTED + VERIFIED LIVE.

---

# BATCH 2 — points #5, #10, #11, #12, #13, #14
Plan: `~/.claude/plans/silly-orbiting-pelican.md`. Order: 13 → 11 → 12 → 5 → 10 → 14.
Access confirmed readable: L2 SAR tree/crop asset, gee_samples_all (farm/shrub), agro_eco_regions, CoreStack LULC v3.

## #13 — IndiaSAT EE-RF models (tree/crop SAR + farm/shrub AE), runnable + carded  ✅
- [x] `src/ee_rf.py`: ported SAR TS helpers; classify_treecrop_tiles + classify_farmshrub_tiles
- [x] backend `/api/treecrop` + `/api/farmshrub`
- [x] schema `ee_rf` topology + `catalogue.mint_ee_rf_card` + `sync_ee_rf_cards`
- [x] frontend 🌾/🌱 overlays + legends (v=19)
- [x] verify LIVE: tree/crop tiles (10s), farm/shrub Punjab tiles (43s), urban gives clean error

## #11 — Water step 1 (eval + augment + fortnight-count)  ✅
- [x] `week10/water_robustness.py`: LIVE temporal 0.913 / spatial 0.993 / combined 0.979, spread 0.042
- [x] `train_water_fortnight.py --augment` (greenery/barren/built negatives) — code done, run pending
- [x] `infer.water_frequency_tiles` + `/api/water-frequency` + 💧× overlay; LIVE mean 3.9 fortnights
- [x] `sentinel._s1/_s2` band-guarantee fix (empty fortnight no longer crashes the year sweep)

## #12 — dense/sparse vs CoreStack canopy  ✅
- [x] LULC v3 legend pinned by NDVI (6=tree dense, 12=scrub sparse); `week10/canopy_compare.py`
- [x] LIVE: dense↔tree ~99%, but single NDVI threshold under-detects scrub (Central India 83%); note written

## #5 — Tessera vs AE timing (real)  ✅
- [x] `scripts/benchmark_tessera_vs_ae.py` + note: AE total 12s vs Tessera 72s (sample 31s, classify 40s); download timing pending

## #10 — UI QA  ✅
- [x] segment gated to selected class; muted-block input gating; dlTif double-fire guard
- [x] export busy-toasts; zooYear auto-refresh; annotate/publish try-catch guards

## #14 — STACD archive flag + answer note  ✅
- [x] `archive` flag on stack item + `/api/stacd?archive=true`; `week10/notes/stacd_archiving.md`
