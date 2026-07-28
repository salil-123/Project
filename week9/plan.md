# Week 9 — plan & task breakdown

Source: `week9_instructions.txt` (13 asks). This file is the working breakdown so the whole
picture stays tracked. Status legend: ☐ todo · ◑ in progress · ☑ done · ⤺ deferred · ✎ answer/doc.

## The 13 asks, grouped

### A. Buildable features (the meat of the week)
- **#12 — Rule-based split.** Instead of training a model to split a class, let the user write an
  *expression* over a **variable registry** of interpretable indices (NDVI seasonal avg, NDVI
  annual avg, NDWI, …): `if ndvi > 0.3 → dense_veg else sparse_veg`. Class 1 / class 2 / … .
  - Fits the existing tree: a rule becomes a node's "classifier", but of kind `rule` not a joblib.
  - Renders server-side: indices are computed in EE (Sentinel-2/1 band math), the threshold picks
    the child. Slots into `infer._final_label` / `_ee_label` beside the linear-model path.
  - New: `rules.py` (registry + expression parse/eval → EE image), a `rule` classifier kind in the
    tree, `/api/rule` endpoint, right-panel "Split by rule" UI.
- **#13 — Decision tree via rules.** The crop/shrub reassignment: crop_shrub → (rule split on crop:
  slope/ndvi) → crop', shrub' → **merge shrub' back into shrub**. Shows a rule split + existing
  merge machinery composes into an arbitrary decision tree. Mostly falls out of #12 + `merges.py`.
- **#1 — Link models to datasets/inference source.** When the user trains, ask (a) what inference
  data (Alpha Earth on EE / Tessera local / raw Sentinel) then (b) which model *family* valid for
  that data (EE → linear list: LinearSVC/LogReg/Ridge; Tessera local → +RF/XGB/object-detection).
  A small compatibility registry + the retrain UI gated on the choice.
- **#3 — Bounding-box size cap.** Guard the download/compute paths so a huge AOI can't explode
  Tessera download / EE export time. Warn + hard cap by area (km²), different caps per render path.
- **#8 — Training-time estimation / benchmarking.** A profiling script + a server-admin config:
  "for a 10 km bbox at 10% training data this box trains an RF in ~N s". EE-context benchmark table.
- **#11 — Improve acacia/non-acacia.** Experiment: more/better data diversity, multi-year pooling
  already helps (0.635→0.745); try band/index features, class balance, thresholding.

### B. Analysis / answers / docs
- **#2 — Can we do LULC on Tessera embeddings (2024-only)?** → written answer (see notes/tessera_lulc.md).
- **#4 — STAC-D / stack-spec.** Read the STAC-D paper; every hierarchy output should emit a
  **stack-spec** (the raster output, STAC-style) + a **stacd spec** listing models + their
  locations. Our hierarchy JSON becomes an input property inside the stacd record. First-cut spec.
- **#9 — Deployment structure review.** Is the code structured for deployment? (service account,
  Dockerfile, config, env). Review + gaps list.
- **#10 — Ship the MVP.** Pull the above into a runnable, documented MVP.

### C. External / research / deferred
- **#5 — Water fortnight classifier (research).** Segment water/non-water per fortnight on raw
  Sentinel-1/2 (not annual embeddings); reconstruct interpretable indices (NDWI/NDVI) from
  embeddings — the standing research problem. For now: pool water/non-water pixels at a fortnight,
  train a simple classifier; offer raw-Sentinel as a feature option. ⤺ scope with sir.
- **#7 — Sentinel-1/2 embedding training on EE.** Ties to #5; the S1/S2 feature path should train
  server-side on EE. ⤺ after #5 direction is set.
- **#6 — Mail Ratinder again.** External user action. ⤺ (not code)

## Status (this session: 3,4,5,7,8,12,13 — approved subset)
- ☑ **#3** bbox cap — `src/aoi.py`, `config.py` caps, backend guards, Tessera fan-out guard, UI banner.
- ☑ **#12** rule split — `src/rules.py` (registry + ast-checked expr → EE label), infer wiring
  (rule bundles on the tile path), `/api/split/rule` + `/api/rules/registry`, `mint_rule_card`,
  `rule_split` topology + op. Verified live: greenery→dense/sparse by NDVI renders as tiles.
- ☑ **#13** decision tree — rule-split child proven as a merge source (crop→shrub mechanic);
  `week9/notes/decision_tree.md`.
- ☑ **#5/#7** Sentinel water — `src/sentinel.py`, `scripts/train_water_fortnight.py`,
  `_linear_label` refactor, `infer.classify_water_tiles`, `/api/water`, `mint_water_card`.
  Verified live (fortnight render). Full-dataset retrain running to rebalance.
- ☑ **#4** STACD — `src/stacd.py` (stack item + DAG/instances, hierarchy embedded as input set),
  `/api/stacd`, UI export button, `week9/notes/stacd_mapping.md` (read the actual paper).
- ☑ **#8** benchmark — `scripts/benchmark_training.py` → `data/benchmark_profile.json` +
  `week9/benchmarks.md`; `/api/estimate`.
- ☑ **#2** answer (Tessera LULC) delivered inline earlier.
- ☑ **#1** model↔data linkage — `/api/model-families`, non-linear (RF/XGB) for Tessera only,
  AE stays linear; UI algo list follows the embedding pick.
- ☑ **#11** acacia — enabled RF-on-Tessera lever; ranked recipe in `week9/notes/acacia_improvement.md`.
- ☑ **#9/#10** answered (deployment gaps + MVP status); on the deck (slide 13).
- ☑ Deliverables: `slides_week9.{tex,pdf}` (14 frames), `slide_explainer.md`, `demo.md`, notes.
- ⤺ Deferred: #6 (external), object-detection family (reserved, not built).

## Proposed build order for this session
1. #3 bbox cap (small, unblocks safe demos)
2. #12 rule-based split + registry  ← headline
3. #13 decision-tree composition (rule split + merge) — demo on crop/shrub
4. #1 model↔data linkage picker
5. #8 benchmark script + admin config
6. Answers: #2, #4 (stac-d first cut), #9 deployment review
7. #11 acacia experiment if time

## Open questions for the user
- Which subset to build this session (all of 1–5, or headline #12/#13 first)?
- STAC-D paper: do you have a link/PDF, or should I design the spec from the STAC spec + the
  airflow "dataset+algorithm management" description in the instructions?
- Rule indices: Sentinel-2 derived (NDVI/NDWI) computed live in EE per the AOI/year — confirm the
  index set to seed the registry (NDVI annual/seasonal, NDWI, NDBI, bare-soil, slope from SRTM?).
