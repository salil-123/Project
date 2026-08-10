# Week 11 — build log

Approved plan: `~/.claude/plans/plan-optimally-and-cleanly-delightful-stallman.md`.
Points delivered this block: STACD send-ready fixes + **#1, #5, #7, #9, #10**.

## STACD send-ready + #14 (op-log naming)
- `src/stacd.py`: renamed `alg_inputs.hierarchy` wrapper → `alg_inputs.input_set`; embedded op-log
  field `op_log` → `op_sequence`, filtered by new `_effective_ops()` (drop everything up to the last
  `reset`, drop `merge_remove` + any `merge` no longer live). Legend drops the junk `other` class and
  falls back to the hierarchy node's colour so greenery paints green, not grey.
- Docs synced: `week10/notes/stacd_audit.md`, `week9/notes/stacd_mapping.md`, `master_document.md`.
- Verified: `python src/stacd.py` passes; `/api/stacd` 200; op_sequence trimmed 32→effective.

## #7 — biomass decoupled from LULC  (`data/catalogue` reindexed to 25 cards)
- `backend.py`: removed `catalogue.sync_biomass_cards()` startup call + the `/api/biomass` endpoint.
- `infer.py`: removed `BIOMASS_GLOB`, `biomass_models`, `load_biomass`, `_sample_ae_slope`,
  `classify_biomass_grid`. Kept shared `_grid` / `_sample_alpha` (RF-on-AE #7 path).
- `catalogue.py`: removed `mint_biomass_card`, `sync_biomass_cards`.
- `schema/model_card.schema.json`: dropped `"regression"` from the topology enum (sole user removed).
- `static/{index.html,app.js,style.css}`: removed the 🌲 run-row, `runBiomass`/`biomassColor`, the
  ramp CSS. Bumped assets to `?v=25`.
- `data/`: deleted `mc_biomass_aez8_v1.json`, rebuilt `index.json`. Large joblibs left on disk
  (gitignored, unreferenced).
- `scripts/train_biomass.py`: dropped the `mint_biomass_card` call — biomass no longer reaches into
  the LULC zoo.
- Verified: no `biomass` in `src/*.py`; backend imports; `/api/biomass` → 404.

## #1 — farm/shrub pan-AEZ sampling  (`src/ee_rf.py`)
- `_farmshrub_classified`: dropped the 40 km `region.buffer` + `filterBounds`; now filters GT by
  `aez_no` only (full AEZ), balanced per-class cap `FARMSHRUB_CAP_PER_CLASS = 3000` (seed 42), AE
  mosaic over the sample points' bounds. `SAMPLE_CAP`/`SAMPLE_BUFFER_M` retired.
- Treecrop unchanged (already pan-India).
- Note `week11/notes/eerf_sampling.md` (parity table + the "why not stored/local" answer).
- Verified: `ee_rf.py` offline checks pass.

## #5 — attach an EE-RF model to any node
- `catalogue.recommend_placement`: added an `ee_rf` branch keyed off `parent_class` ("normally refines
  greenery, but any node") — fixes the old bogus `node`-based hint.
- `backend.apply_eerf`: kept the generic `parent`; added a name-collision guard (clean 400 if the
  model's classes already exist elsewhere) and `pop("rule")` so a node can't hold a rule + an ee_rf.
- `static/app.js`: `useEeRfModel(cardId, targetNode)` posts `{card_id, parent: selected||default}`;
  detail button now reads "Apply to <selected class>" with a "select a class first" hint; placement
  suggestion rendered.
- Verified live: reset → apply treecrop to **barren** (non-greenery) → 200, barren marked, classify
  paints cropland/tree in the barren branch; collision guard returns 400; tree restored after.

## #9 — mining pixel+vectorize evaluation  (`week11/mining_eval.py`)
- Buffers sampled GT mining polygons into eval boxes, runs `segment_class`, greedy IoU-matches
  predicted↔GT (equal-area EPSG:6933), reports precision/recall/F1/mean-IoU/area-IoU. `--write-card`
  writes onto `mc_barren_v1` (About → Evidence).
- Result (25 sites): P 0.04 / R 0.16 / F1 0.07 / mean IoU 0.52 / area IoU 0.18 → **not good enough for
  object delineation**; verdict + caveats in `week11/notes/mining_eval.md` (+ `mining_eval_run.log`).

## #10 — water small-vs-large validation  (`week11/water_eval.py`)
- Reuses `week10/water_robustness.build_frame` + `scripts/train_water_fortnight.augment_negatives`;
  buckets water bodies by area, scores the deployed model per bucket + a dryland FP probe.
- Truth established: model is **S1+S2** (`sentinel.FEATURE_BANDS`), not S1-only.
- Result: large F1 0.99, small F1 0.75 (recall 0.67 — the gap), dryland FP 2.5 %. Written to
  `mc_water_fortnight_augmented_v1`; `week11/notes/water_eval.md`.

## Files (block 1)
- Edited: `src/{stacd,ee_rf,infer,backend,catalogue}.py`, `schema/model_card.schema.json`,
  `src/static/{index.html,app.js,style.css}`, `scripts/train_biomass.py`, docs.
- New: `week11/{mining_eval,water_eval}.py`, `week11/notes/{eerf_sampling,mining_eval,water_eval}.md`,
  `week11/notes/mining_eval_run.log`.
- Data: `data/catalogue/index.json` rebuilt (25 cards), `mc_biomass_aez8_v1.json` removed; card
  evidence written on `mc_barren_v1` + `mc_water_fortnight_augmented_v1`.

---

# Block 2 — points 11, 12, 13

Track B (high-quality pan-India classifiers as experiments) + one real feature. Working plan:
`week11/notes/plan_11_12_13.md`.

## #13 — spurious-water correction (code, not a feature) + EE GT eval
- `infer._water_count_image` refactored out of `water_frequency_tiles`; the ≥N-fortnight hold is a
  **code-level correction on the water output**: `infer.annual_water_mask(ee, region, year,
  min_fortnights=config.WATER_MIN_FORTNIGHTS)` → annual water mask where count ≥ N. **No endpoint/button**
  — it's applied when the fortnight model feeds the LULC (deferred water step). `config.WATER_MIN_FORTNIGHTS=2`.
  (Originally shipped as a UI button + `/api/water-persistent`; removed after sir's point 13 clarified it
  is a correction, not a feature.)
- `week11/water_gt_eval.py`: all three EE GT assets readable; samples points, sweeps the threshold.
  **2-fortnight hold: spurious 15%→2%, water P 0.80→0.96**; small-water recall 0.30→0.11. Water class in
  GT_BINARY determined empirically (class 2). Appended to the water card.
- Verified: GT eval over 317 polygons; `annual_water_mask` thresholds the fortnight count.

## #12 — mining pan-India classifier (+ improvement)
- `week11/mining_pan_india.py`: positives (mining) + **buffer-ring hard negatives**
  (`buffer(d)∖all_mines`, cleaned with `buffer(0)`) + generic negatives; whole-polygon holdout; buffer
  sweep, then a linear-vs-RF-vs-RF+tuned-threshold shootout at the best buffer.
- Linear F1 0.55 (P 0.45, R 0.70). **RF + tuned threshold (0.20) → F1 0.59, precision 0.45→0.61**
  (recall give-back). Buffer width ~irrelevant. Card evidence on `mc_barren_v1` rewritten cleanly
  (#9 + #12).

## #11 — acacia counts + gentle filter + improvement
- `week11/acacia_eval.py`: counts (336 / 576). Corrected the filter — crowns are all single trees
  (median 27 m², sub-pixel), so a 100 m² cutoff nukes 98%; a **gentle < 15 m²** filter keeps 296/498.
- Improvement (week9 levers): **RF + multi-year (2022–24) lifts F1 0.68→0.71, acc 0.72→0.78,
  precision +0.10**; threshold tuning didn't beat the untuned RF. Ceiling = mixed pixel; real fix is
  Tessera / drone-RGB DINO (external).

## Files (block 2)
- Edited: `src/{infer,backend}.py`, `src/static/{index.html,app.js}` (persistence feature, `?v=26`).
- New: `week11/{water_gt_eval,mining_pan_india,acacia_eval}.py`,
  `week11/notes/{water_gt_eval,mining_pan_india,acacia_eval,plan_11_12_13}.md`,
  `week11/notes/mining_pan_india_run.log`.
- Data: card evidence appended on `mc_barren_v1` (#12) + `mc_water_fortnight_augmented_v1` (#13).
- Note: a `/api/session/reset` in a #5 test archived the example canvas; `data/examples/{acacia,
  non_acacia,mining,barren}.geojson` were restored from `data/examples/archive/`.
