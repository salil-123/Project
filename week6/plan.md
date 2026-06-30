# Week 6 — implementation tracker

Approved plan: `~/.claude/plans/splendid-gliding-puzzle.md`. This file is the live
checklist + notes as we build. Source asks: `week6_instructions.txt`.

## Locked decisions
- **#8** model storage → commit tiny `.joblib` into the zoo git repo.
- **#5** WorldCover base → cheap effective ~7-class base from `worldcover_train.csv`
  (Crop/Tree/Grass/Shrub/Bare/Built/Water; drop the ≤29-pt classes). Skippable.
- **#9** merge → post-inference relabel-rules layer, no retraining.
- **#7** temporal → inference-data picker (AE 2017–2024 + Tessera-2024), reuse same model.
- **#4** save/reload → lightweight JSON (tree + op-log), rebinds artifacts on reload.
- **#2** recommendations → auto-derived from card metadata + AOI.
- **#3** UI → full systematic sweep.
- **#10** decision-tree thought experiment → not built.
- **tip** cleanup/optimize → last.

## Checklist (execution order)
- [x] **A. Op-log (#11)** — `src/oplog.py`, `data/op_log.json`; wired into split/add/retrain/apply. Smoke test passes.
- [x] **B. Adjustable diversity grid (#1)** — `catalogue.recompute_spread`, `GET /api/cards/{id}/spread?cell=`, UI cell `<select>`. Verified finer grid → higher diversity.
- [x] **C. Inference-data picker (#7)** — `year` threaded through `infer`/`backend`/classify; `GET /api/inference-options`; UI year dropdown (AE 2017–2024; Detailed locked 2024). Endpoints smoke-tested. NOTE: skipped per-year card minting (classify is runtime, not a mint); AE inference card still documents 2024 calibration.
- [x] **D. Contributor on publish (#6)** — `zoo_git._mark_published(contributor=)`, `/api/publish` + UI prompt (remembered in localStorage). Live push verified in H to avoid polluting shared repo.
- [x] **E. Recommendations (#2)** — `catalogue.recommend_placement` + `_worldcover_for_class`; attached to `GET /api/cards/{id}`; "Suggested placement" block + tile hint. Verified on real cards.
- [x] **F. Save/reload hierarchy (#4)** — `GET /api/hierarchy/export`, `POST /api/hierarchy/import` (validate/rebind/report missing); UI download+upload. Round-trip verified identical, bad tree → 400.
- [x] **G. Merge / cross-model relabel (#9)** — `src/merges.py`, `data/merge_rules.json`; `infer._apply_merges` (grid) + `_merge_ee` (EE remap) + colors; `GET/POST/DELETE /api/merge`; UI Merge panel. Grid relabel + endpoints verified offline; EE remap to confirm in H with a live classify.
- [x] **H. UI full sweep (#3)** — consolidated detail-pane wiring (removed setTimeout `wireDetail`; `pubBtn` now via `#zoo-detail` delegation). Live server verified end-to-end: static 200s; tree/examples/catalogue/base/inference-options/recommendation/spread all respond; index consistent (3 models, 10 datasets — "not showing" was the already-fixed CSS bug). LIVE GEE: realistic 2024 vs 2022 counts differ (year picker real); merge tea+mining→extractive exact (1690+94=1784), removed cleanly.
- [x] **J. Publish storage (#8)** — (a) model `.joblib` staged into zoo `artifacts/` + committed on publish; `.gitignore` keeps `artifacts/*.joblib` (verified negation in temp repo); `card.artifact.published_path`. (b) per-dataset PUBLIC source link prompted at publish (`zoo_git._apply_dataset_links`, `card.source_url`), shown on dataset card; private uploads stay local/never pushed. Decision: links are public; no deletion (retraining preserved). Tested offline + card restored.
- [x] **I. WorldCover base + picker (#5)** — `refine.train_worldcover_base` (7 classes, n=8942), `hierarchy.seed_from_classes`, `infer.active_base/set_active_base`, `GET/POST /api/base[/select]`, UI picker. Switch round-trip verified. DEFERRED: WC base zoo card (id `mc_root_v1` collides with IndiaSAT base card) — base picker swaps the live model without a distinct card for now. NOTE: base switch is destructive (reseeds tree, clears splits/merges); backs up to `data/hierarchy.prev.json`.
- [x] **Z. Cleanup + optimize (tip)** — master_document.md updated to "week 6 delivered"; EE render path de-duplicated (`infer._labelled_bbox` + `_class_counts` shared by PNG + tiles); re-verified live (counts unchanged).
- [x] **K. WorldCover base card** — `catalogue.mint_worldcover_base_card` (`mc_worldcover_base_v1`, distinct id); `base_scheme` on base cards; `_switch_base` shared by `/api/base/select` + base-card apply; minted at backfill. Apply routes IndiaSAT/WorldCover correctly (verified).
- [x] **L. Optimization pass** — `infer.py` render dedup (see Z). Live classify counts identical to pre-refactor.
- [x] **M. Week-6 slides** — `week6/slides_week6.tex` + `.pdf` (Madrid theme, author details from prior weeks, text-only, no em dashes).
- [x] **N. Demonstration doc** — `week6/demo.md`: click-path + expected result + curl check for every feature; plus a no-browser sanity section.

## Notes / discoveries
- Artifact sizes 4–33 KB → committing into zoo repo is fine.
- `worldcover_train.csv` class support: Crop 4522, Tree 2324, Grass 997, Shrub 430, Bare 307,
  Built 217, Water 145 | unusable: Snow 29, Wetland 12, Moss 10, Mangrove 7.
- EE renderer `infer._ee_label` already handles K≥3 classes (no change for WC base).
- Detail-pane wiring is mixed (setTimeout `wireDetail` vs `#zoo-detail` delegation) → unify.
