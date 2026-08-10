# #10 — Water validation: small vs large water bodies + spurious water

## First, the truth correction

Sir's point 10 was prefaced with "I may have presumptuously claimed we're only using Sentinel-1."
**We're not.** The deployed water model uses **Sentinel-1 + Sentinel-2** —
`sentinel.FEATURE_BANDS = [VV, VH, VV_VH_ratio, NDWI, MNDWI, BSI, B3, B8, B11]` (3 SAR + 6 optical,
same image at train and inference time). So the S1-only **road↔water confusion** sir worried about is
already mitigated by the optical water indices (NDWI/MNDWI) and the built-up/bare index (BSI). That
changes #10 from a re-architecture into a validation task.

## Method — `week11/water_eval.py`

Reuses the week10 robustness harness (`build_frame` samples the S1+S2 features at each seasonal-water
polygon's own date) and the augmentation sampler. We bucket each water **body** by footprint area
(equal-area EPSG:6933), score the **deployed** model per bucket, and probe dryland false positives.

Run: `python week11/water_eval.py --max-dates 50 --n-pix 8` (small/large split at the median body area).

## Result (696 pixels, 67 water bodies, threshold 1.45 ha)

| water bodies | bodies | pixels | water precision | water recall | F1 | accuracy |
|--------------|-------:|-------:|----------------:|-------------:|---:|---------:|
| **small** (≤1.45 ha) | 31 | 304 | 0.85 | **0.67** | 0.75 | 0.69 |
| **large** (>1.45 ha) | 36 | 392 | 1.00 | 0.97 | **0.99** | 0.97 |
| all | 67 | 696 | 0.95 | 0.86 | 0.90 | 0.85 |

**Spurious-water probe** (8 032 dryland pixels — barren/built-up/greenery across 3 seasons): only
**2.5 %** get called water. So the model does **not** over-call water on dry land — the augmentation
(#11 wk10) did its job.

## Reading it

- **Large water bodies: essentially solved** (F1 0.99). Perennial/large bodies are easy for S1+S2.
- **Small water bodies: the real gap** — recall drops to **0.67**, i.e. it misses a third of small
  water. Precision stays high (0.85), so when it says water on a small body it's usually right, but it
  under-detects. This is exactly the **small/seasonal water** risk sir raised: a classifier trained
  where non-water dominates learns to be conservative, and small/thin/turbid water is where that
  bites. It's a recall problem, not a spurious-water problem.
- **Not spurious** (2.5 % dryland FP) — the road/water and dryland-water fears don't show up in the
  numbers, consistent with using S1+S2 rather than S1 alone.

## Where this points (step 2, per sir's staging)

The small-body recall gap is the argument for sir's **two-classifier** design: a lenient level-1 that
lets seasonal/small water through (SAR in monsoon + optical/Dynamic-World off-monsoon + NDVI
correction), then a within-water-body classifier for the fortnight count. Our current single model is
already strong on large bodies and clean on dryland; the next lever is small-body **recall**, not
precision or spurious control. Numbers surfaced on the deployed water card
`mc_water_fortnight_augmented_v1` (About → Evidence).

## GT assets note

The shared EE assets sir listed (`GTSeasonal`, `GTPerennial`, `GT_BINARY_LATEST`) are marked
optional/unshared in `config.py`; this eval uses the local `data/inputs/seasonal_water.geojson`
(205 water bodies, the set the deployed model was built on). If those assets get shared, the same
harness can bucket them by size the same way.
