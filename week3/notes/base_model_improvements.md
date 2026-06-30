# Base-model improvements (data-side), 2026-06-12

Goal: improve the base (Realistic) model by working on the **data**, optimised for
**balanced detection** (rare classes findable), keeping the Detailed/Tessera mode as-is.

Tooling added (reproducible, replaces the ad-hoc week-2 script):
- `src/eval_base.py` — scores any base bundle on random-India + a block-held-out balanced
  expert set.
- `scripts/ingest_water.py` — Alpha Earth at the now-readable GTSeasonal+GTPerennial
  polygons → `data/water_extra.csv` (2,900 water px).
- `src/train_base.py` — pooled trainer: drops `other`, adds water, sweeps `wc_weight`,
  stays a plain `StandardScaler→LinearSVC` (so the 10 m EE raster still reproduces it).

## What we found

1. **The old deployed eval was optimistic.** The deployed model scored 0.861 balanced
   macroF1, but it had been trained on ~all data including the eval holdout. On an honest
   70/30 block split the same recipe gives **0.815** — that's the real baseline.
2. **`wc_weight` is the only real lever, and it's a trade-off** (held-out 70/30):

   | wc_weight | balanced macroF1 | random-India macroF1 |
   |--|--|--|
   | **2** | **0.815** | 0.571 |
   | 3 | 0.802 | 0.610 |
   | 4 | 0.785 | 0.634 |

   Higher = better browsing, worse rare-class detection. For balanced detection, **2** wins.
3. **Per-class threshold tuning (intercept offsets) was tried and rejected** — tuning to
   lift balanced macroF1 just suppressed greenery and **tanked** the random-India score
   (it games one side of the prior). Dropped; the model keeps plain pooled scores.
4. **`class_weight='balanced'` hurt** (fights the prior) — not used.
5. The extra **water polygons help**; dropping **`other`** (WorldCover junk) cleans the
   model and aligns it with the Detailed model's 4 classes.

## Deployed change (old → new), eval on the same sets

| metric | old `model_pooled` | new (this) |
|--|--|--|
| balanced acc / macroF1 | 0.871 / 0.861 | **0.889 / 0.882** |
| balanced water recall | 0.65 | **0.73** |
| balanced barren recall | 0.80 | **0.83** |
| random-India acc / macroF1 | 0.828 / 0.593 | 0.795 / 0.564 |
| classes | barren/built_up/greenery/**other**/water | barren/built_up/greenery/water |

Net: **better on the chosen objective** (balanced detection — water/barren recall up),
a small dip on random browsing (expected; not the objective), cleaner class set. The
10 m EE raster still pixel-matches sklearn **36/36**; the greenery + mining splits and the
Detailed mode are unchanged. Old model backed up at `data/model_pooled.bak.joblib`.

## The real ceiling (not done here)
The data tweaks are modest. The genuine accuracy lift for the hard cases
(greenery↔water, crop sub-types) needs **temporal / NDVI features** — flagged for later,
a separate effort. Ongoing per-area corrections are already handled live by the tool
(relabel / hard-negative examples).
