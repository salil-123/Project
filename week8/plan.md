# Week 8 — build log (features #2–#11)

Source asks: `week8_instructions.txt`. Approved plan:
`~/.claude/plans/plan-optimally-and-cleanly-flickering-lagoon.md`. This is the live build log for
the first block of week-8 work — a UI restructure plus a few backend touches. Everything below is
implemented and verified.

## What shipped

| # | Ask | What shipped | Key files |
|---|-----|--------------|-----------|
| 2 | Drop Realistic/Detailed choice | Removed the Mode dropdown; Run always classifies Realistic (AE → EE 10 m tiles). Backend softvote kept, just unexposed. | `static/index.html`, `static/app.js` |
| 3 | Clickable bbox on the map | A persistent yellow AOI box (`drawAoi`). Draw a rectangle (▭) to set an arbitrary AOI (`customBbox`); in Custom mode click the map to drop a centre and the Half-size slider resizes the box live. | `static/app.js` (draw/click/slider, `currentBbox`) |
| 4 | Export only this session's ops | `/api/tree` now returns `op_seq`; `export?since=` slices the op-log; the client anchors `sessionStartSeq` in `localStorage` (survives refresh, resets on area-reset/import). | `backend.py`, `static/app.js` |
| 5 | Reset the tree on a new area | `POST /api/session/reset` reseeds the *current* base scheme. The UI offers it (confirm-first) only when the tree has real work (`hasUserEdits`). `reset` added to `validate_ops.KNOWN_OPS`. | `backend.py`, `validate_ops.py`, `static/app.js` |
| 6·10 | Explanatory, low clutter | Guidance lives in the right panel: a per-class heading + one-line "what this is / do next", one pithy hint per action block. Left hints tightened. | `static/index.html`, `renderContext` |
| 7 | Split/add/merge before retrain | Right-panel order is Mark data → Split → Add → Merge → Retrain. | `static/index.html` |
| 8 | Contextual right panel | New `#context` aside; Examples/Split/Add/Merge/Retrain moved there (ids kept, handlers unchanged). `renderContext(cls)` names the class and dims the less-relevant blocks. | `static/index.html`, `static/app.js`, `static/style.css` |
| 9 | Zoo shows every model; drop dummy | `DELETE /api/cards/{id}` (+ orphan-joblib purge, published-guard); `catalogue.sync_node_model_cards()` at startup; archived badge + Delete button in the zoo. **tea/non_tea regenerated** as a real archived card (0.963), the acacia dummy removed, acacia kept live. | `backend.py`, `catalogue.py`, `static/*`, `scripts/regen_tea_acacia.py` |
| 11 | Flag incompatible apply | `catalogue.check_apply_compatible`; `/api/apply` takes `target_node`+`force`, returns 409 with a reason on a mismatch; the panel's "Apply to selected class" confirms then forces. | `catalogue.py`, `backend.py`, `static/app.js` |

## The tea/acacia regen (#9)
`scripts/regen_tea_acacia.py` is surgical: it trains tea/non_tea once (live GEE), mints then
**archives** it as `mc_greenery_prev1_v1` (keeping the joblib under `data/refine/archive/`), and
restores the live acacia model + its published card byte-for-byte — so the IIT-Delhi home turf is
unchanged. End state models: `mc_greenery_v1` (acacia, live, published), `mc_greenery_prev1_v1`
(tea/non_tea, archived, acc 0.963), `mc_barren_v1`, `mc_root_v1`, `mc_worldcover_base_v1`. The old
half-broken acacia dummy is gone. (Re-runnable if the split is ever churned again.)

## Verification done
- Backend via TestClient + live GEE: `op_seq`=21; `export?since=huge` → 0 ops (session scoping);
  `apply mc_greenery_v1 → water` → **409** with a human reason; delete of a published card → **400**
  (guard); `session/reset` reseeds root+4 base and bumps `op_seq`, then restored; a live classify of
  the IIT box returns tiles with acacia/non_acacia/built_up/water/barren.
- Real `uvicorn` boots; `/` serves the context panel at `?v=8` with no Mode dropdown.
- `node --check app.js` clean; every static id `app.js` touches exists in `index.html`.

## Round 2 — review fixes (same features, refined)
After a hands-on look, four corrections:
- **#3 (spillover):** classification painted past the AOI on edge tiles. `infer._labelled_bbox` now
  `vis.clip(region)`, so pixels outside the drawn box come back transparent in both the tile and PNG
  renderers. Verified a live classify still returns tiles + counts.
- **#4 (pre-filled examples):** leftover `data/examples/*.geojson` made a fresh split look
  pre-uploaded. `examples.archive_all()` **moves** (not deletes) all markings into
  `data/examples/archive/<ts>/`; `POST /api/session/reset` calls it, and a new **"↺ Start fresh"**
  button (left, under the tree) triggers the same reset on the current area. Trained models are
  untouched (they live as joblibs/zoo cards); `card_geometry` already tolerates the moved files.
- **#9 (wrong model kept):** the model to keep was the **multi-year** acacia/non_acacia (week-7,
  pooled 2019/2021/2023, **0.745** on unseen years), not the single-year one. `scripts/
  restore_multiyear_acacia.py` (no GEE) makes it the live greenery split and mints its card with the
  week-7 metrics. Zoo now: acacia multi-year (live), tea/non_tea (archived, 0.963), barren/mining,
  IndiaSAT base, WorldCover base — all schema-valid; the 0.703 dummy is gone.
- **#11 (ugly popups):** a promise-based `uiConfirm()` modal (styled, Esc/Enter/backdrop, danger
  variant) replaces every native `confirm()` — area reset, start-fresh, apply-anyway (#11), delete,
  and base-switch. Assets bumped to `?v=9`.

## Block 2 — features #12–#15
- **#12 (flow-gate controls):** the balancing (`#balance`) + multi-year (`#trainYears`) fields moved
  into `#retrainAdvanced`, revealed by `renderContext` only for a **trainable user split**
  (`!isLeaf && cls !== "root"`). A bare leaf shows just "Retrain & apply"; root retrains the base
  without balance/years. Split/Add/Merge keep the existing relevance-dimming.
- **#13 (operations / schema view):** new read-only `GET /api/oplog?since=` (session-scoped like
  export). Left panel gains a `By hierarchy | By operations` toggle (`.vtab`); `renderOps` lists the
  session's steps via `opSummary`/`opTargetNode`. Clicking a step `select()`s its class so the right
  panel drives retrain/split/merge — both views feed one panel. The Split block gains a "Use a model
  from the Zoo" button (the "select a model vs bring your own data" fork; applying still runs the #11
  guard). `refreshTree` re-renders the ops list when it's the active view.
- **#14 (standard classes on the tile):** `catalogue.std_classes_for_card` + a `std_classes` field on
  each model index row. `modelTile` → `tileClassChips` shows the **standard** name (WorldCover→USDA
  fallback) when mapped, else the user classes; `produceChips` (detail) now shows the standard *name*
  too (`stdName`). Degrades to user classes until a card is annotated.
- **#15 (dataset → models):** `catalogue.models_using_dataset` scans model cards' `training.datasets`
  + `inference.dataset`; `GET /api/cards/{ds_id}` attaches `used_by`; `datasetDetail` shows a clickable
  **"Used in models"** block, and `datasetTile` a "used in N models" count (index `used_by_count`).
- Assets bumped to `?v=10`. Op-log restored to a clean monotonic state (test churn).
- **Verified** (TestClient + real uvicorn): `/api/oplog?since=` scopes correctly; a dataset's `used_by`
  resolves (ds_mining → mc_barren_v1); annotating acacia→WorldCover 10 makes the index `std_classes`
  read "Tree cover" then reverts cleanly; the page serves the toggle/ops/advanced-wrapper at v10;
  `node --check` clean, all ids present.

## Block 3 — features #16–#27 + two fixes + deliverables
- **Fixes:** entropy `-0.0 → 0.00` (`_geojson_stats` occ≤1 guard) + restored archived example files +
  a "polygons archived" signal (`recompute_spread.missing`); water colour `#2b6cff → #1e88e5` across
  `_BASE`/`CLASS_COLORS`/`WC_BASE` + live tree.
- **#21** overlay eye-toggle (hide/show `rasterLayer`+`predLayer`, no reclassify).
- **#25** selective publish — tile checkboxes + "Publish selected (N)" → existing `/api/publish` card_ids.
- **#24** GeoTIFF — `infer.classify_bbox_geotiff` (`final.toInt().getDownloadURL(GEO_TIFF)`) +
  `GET /api/classify.tif` + ⬇ button. Verified: valid TIFF magic bytes downloaded.
- **#27** `scripts/prep_seasonal_water.py` → `ds_seasonal_water_v1` (876 polys, 720 water/156 non-water,
  spread 0.61). Schema-valid.
- **#17** linear bake-off — `refine.train(algo="auto")` over LinearSVC/LogReg/Ridge, best by held-out
  acc; `_svc_steps` generalised to any linear step; `_ee_label` normalises 1-D coef (Ridge). Verified
  live: Ridge won 0.731 and **renders as tiles**.
- **#16** Tessera training — `TE_COLS`, `embedding` threaded through `train`/`build_split_dataset`/
  `_child_frame` (examples path), bundle `features:"te"`, card flags not-band-math; scoped to
  `TESSERA_SITES` (UI shows the option only on the 4 sites). Verified live: Delhi acacia/non_acacia on
  Tessera ~0.73; tile map skips the te split without crashing. Multi-year acacia restored as live.
- **#18/#23** project save/resume — client wraps the export as `project.json` (scheme + sequence +
  aoi/year/base, datasets as links); import restores the view then applies. "Save / resume project".
- **Deliverables:** `week8/slides_week8.tex` (+ compiled `slides_week8.pdf`, 12 frames, Beamer Madrid),
  `week8/slide_explainer.md` (foundations + slide-by-slide + Q&A incl. **#22 Tessera+joblib** and
  **#26 deployment**), `week8/demo.md`. Assets bumped to `?v=13`.
- **Answered in docs:** #19 (pipeline line + UX narrative), #20 (schemas slide), #22 (explainer Q1),
  #26 (deploy slide + explainer Q2).

## Open / not in this block
Features #1 (biomass/GEDI) and #12–#26 are out of this block. #12 (flow-gated balancing controls)
partially overlaps #8's contextual dimming but isn't fully done.
