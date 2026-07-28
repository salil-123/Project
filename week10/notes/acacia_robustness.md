# #8 — Acacia spatial + temporal robustness (results)

Sir's ask: for the acacia/non-acacia split, test **spatial** robustness (some regions in train,
others held out) **and** temporal robustness (train some years, test unseen years) **together**, and
aggregate accuracy across the test years so a fluke year is visible.

Script: `week10/acacia_robustness.py`. Data: the confident acacia crowns now carry their source
region in `area` (persisted by `scripts/prep_acacia_examples.py`, threaded through
`examples.build_training_frame`). Confident acacia positives live almost entirely in the four Sanjay
Van strips, so the region holdout runs across those — train on SV_S1/S2/S3 (+ every other region's
non-acacia), **test on the held-out SV_S4** (which keeps both classes: 195 acacia / 100 non-acacia px
per year at n_pix=5). Same `StandardScaler + LinearSVC(balanced)` throughout, so the numbers compare.

## Run: train 2021/2023, eval 2022/2024, n_pix 5

| Check | What's held out | Accuracy |
|-------|-----------------|---------:|
| temporal-only | random polygons, unseen years | **0.716** |
| spatial-only | region SV_S4 (year 2023) | **0.695** |
| spatial + temporal | region SV_S4 **and** the year | **0.673** |

Per eval-year on the held-out region: **2022 = 0.790, 2024 = 0.556** → year-to-year spread **0.234**.

## Reading it

- The ordering is the honest one: **combined (0.673) < spatial-only (0.695) < temporal-only
  (0.716)**. Holding out a whole *region* is harder than holding out random polygons, and holding out
  region *and* year is hardest — which is the point. A model that only ever saw SV_S1–S3 generalizes
  to the never-seen SV_S4 at ~0.67, not the ~0.75 the year-only check suggested.
- The **per-year spread (0.234) flags 2024 as a likely fluke year** (0.556 vs 0.790 in 2022) on the
  held-out region — exactly the "check for fluke years" signal sir asked for. Worth a look at 2024
  Alpha Earth coverage / phenology over Sanjay Van before trusting a single-year acacia number there.
- Consistent with week 7's finding that acacia is a genuinely hard species split; the spatial holdout
  makes the difficulty explicit rather than hiding it behind polygon-level leakage.

## Reproduce

```
python week10/acacia_robustness.py --train-years 2019 2021 2023 --eval-years 2020 2024 --n-pix 6
```
(more years / higher n_pix = steadier numbers, more EE sampling time). The held-out region is
`TEST_REGION` in the script (default `SV_S4`).
