# #13 — Road/spurious water: the persistence filter + EE ground-truth validation

Sir's #13: road pixels (and water-logged roads) get miscalled water; we need a **filter** — "only over
two fortnights those we hold, or some threshold" — and we should look at the output over the shared EE
water-body ground truth.

## The correction (not a feature) — persistence over N fortnights

Sir's point 13 asked for "a filter that only over two fortnights and those we hold, or some kinda
threshold". That's a **correction on the water output**, not a UI control, so it lives in the code, not
as a button: `infer.annual_water_mask(ee, region, year, min_fortnights=config.WATER_MIN_FORTNIGHTS)`
returns an annual water/non-water mask that keeps a pixel as water **only if it read water in ≥ N
fortnights**. A road that flickers wet for one fortnight (monsoon water-logging, S1 speckle) drops out;
a genuine pond/lake stays. It shares `infer._water_count_image` with the frequency map (the point-10
*visual* gradient), so it's the same fortnight count, thresholded. `config.WATER_MIN_FORTNIGHTS` (=2) is
the knob. It's applied when the fortnight water model is folded into the LULC — the deferred water step —
so the corrected water layer feeds the map rather than the raw per-fortnight flicker.

## Validation on sir's EE assets

`week11/water_gt_eval.py` — all three assets are readable from our project:

| asset | what | n |
|-------|------|--:|
| `projects/ee-mtpictd/assets/GTSeasonal` | seasonal water bodies (all water) | 16 |
| `projects/ee-mtpictd/assets/GTPerennial` | perennial water bodies (all water) | 13 |
| `projects/ee-vatsal/assets/GT_BINARY_LATEST` | differently-sized water / non-water (`class`, `area_sqm`) | 288 |

We sample interior points, run the deployed model over 10 dates across 2024, count water-fortnights per
point, and **sweep the persistence threshold t**. (Water class in GT_BINARY is determined empirically —
class 2 reads water 0.55 of the time vs 0.15 for class 1, so class 2 = water.)

### The filter does exactly what sir wanted (GT_BINARY)

| threshold | water P | water R | F1 | **spurious (non-water called water)** | small-water R | large-water R |
|-----------|--------:|--------:|---:|--------------------------------------:|--------------:|--------------:|
| t ≥ 1 (any water ever) | 0.80 | 0.55 | 0.65 | **0.15** | 0.30 | 0.84 |
| **t ≥ 2** (the filter) | **0.96** | 0.41 | 0.58 | **0.02** | 0.11 | 0.77 |
| t ≥ 3 | 0.98 | 0.32 | 0.49 | 0.01 | 0.02 | 0.68 |

**A 2-fortnight persistence filter cuts spurious water from 15% → 2%** and lifts water precision from
0.80 → 0.96. That's the road/spurious-water fix: transient one-off detections are dropped. The cost is
recall on genuinely intermittent water.

### The cost lands on small / seasonal water

- **Large water bodies stay strong** (recall 0.84 → 0.77 across thresholds).
- **Small water bodies are the casualty** — recall 0.30 at t≥1, collapsing to 0.11 at t≥2. Seasonal
  bodies similarly: GTSeasonal recall 0.75 → 0.70 → 0.61; GTPerennial 0.86 → 0.71 → 0.66.

So there's a real tension, exactly as sir framed it: a persistence threshold that kills spurious water
also suppresses the seasonal/small water we want to keep.

## Reading it / recommendation

- **t = 2 is the sweet spot for spurious control** (2% false water, 0.96 precision) and is the sensible
  default for the annual water layer — use it wherever clean water/non-water matters.
- **But small/seasonal water needs more than a global threshold.** The recall collapse on small bodies
  is the quantitative case for sir's **two-classifier** design (#10/#13): a *lenient level-1* that lets
  seasonal water through (SAR in monsoon + optical off-monsoon + NDVI correction), then a within-body
  classifier for the fortnight count — instead of one global persistence cut that trades away the small
  water. The filter shipped here is the pragmatic step-1 knob; the two-classifier build is step-2.

Numbers appended to the deployed water card `mc_water_fortnight_augmented_v1` (About → Evidence).
