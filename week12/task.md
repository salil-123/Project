# Week 12 — task breakdown

Source: `week12_instructions.txt` (9 points). Two workstreams.

## A. Answer the questions (→ `week12/notes/answers.md`)  — DONE
Investigated the code, wrote proper answers in `week12/notes/answers.md`.

- [x] 1. Outputs in slides — which live renders to screenshot
- [x] 2. Water body at different fortnights — /api/water + /api/water-frequency, small-multiples
- [x] 3. Google Earth web KML — segment/tif → ogr2ogr → earth.google.com import; upload path takes KML
- [x] 4. Tuned cut = F1-max probability threshold on a val split (acacia_eval/mining_pan_india :tune_threshold)
- [x] 5. Spurious water = temporal ≥N-fortnight persistence (annual_water_mask); object smooth = 3×3 focalMode
- [x] 6. Fixed 3×3 window + N=2 threshold, both read-only on output; only augment = offline dryland negatives
- [x] 7. Crowns 336/336; median 27 m² (sub-pixel); ≥70 m² pixel-purity filter = proposed experiment (not built)
- [x] 8. Semi-supervised self-training = proposed feature (not built); sketch + guardrails given

## B. Break the framework (robustness) — point 9  — DONE
Probed isolated (temp-dir data paths, no EE) + confirmed via TestClient. Full report:
`week12/notes/robustness.md`. Real data files verified byte-identical after the pass.

Fixed (3 real "acts-out" classes + 1 latent):
- [x] AOI: degenerate/inverted/zero-area boxes passed → 400 before EE (`aoi.valid_bbox`)
- [x] split_op: 0/1-child + re-split of non-leaf → now guarded like rule_split_op
- [x] rules: non-boolean / chained expressions accepted → `_is_boolean` gate
- [x] rules: leading `!` negation wrongly "malformed" → `_to_python` strip

Left as-is (documented, not bugs): merge over ghost leaves (by-design no-op), rule child
colliding with base class (already 400), adversarial imports (already rejected pre-mutation).
