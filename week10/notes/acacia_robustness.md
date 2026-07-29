# #8 — Acacia spatial + temporal robustness (results)

Sir's ask: for the acacia/non-acacia split, test **spatial** robustness (some regions in train,
others held out) **and** temporal robustness (train some years, test unseen years) **together**, and
aggregate accuracy across the test years so a fluke year is visible.

Script: `week10/acacia_robustness.py`. Data: the confident acacia crowns now carry their source
region in `area` (persisted by `scripts/prep_acacia_examples.py`, threaded through
`examples.build_training_frame`). Confident acacia positives live almost entirely in the four Sanjay
Van strips, so the region holdout runs across those — train on SV_S1/S2/S3 (+ every other region's
non-acacia), **test on the held-out SV_S4** (which keeps both classes). Same
`StandardScaler + LinearSVC(balanced)` throughout, so the numbers compare.

## Run: train 2019/2021/2023, eval 2020/2024, n_pix 10

| Check | What's held out | Accuracy |
|-------|-----------------|---------:|
| temporal-only | random polygons, unseen years | **0.749** |
| spatial-only | region SV_S4 (year 2023) | **0.695** |
| spatial + temporal | region SV_S4 **and** the year | **0.679** |

Per eval-year on the held-out region: **2020 = 0.678, 2024 = 0.680** → year-to-year spread **0.002**.

## Reading it

- The ordering is the honest one: **combined (0.679) < spatial-only (0.695) < temporal-only
  (0.749)**. Holding out a whole *region* is harder than holding out random polygons, and holding out
  region *and* year is hardest — which is the point. A model that only ever saw SV_S1–S3 generalizes
  to the never-seen SV_S4 at ~0.68, not the ~0.75 the year-only check suggested. The value is that gap:
  it shows how much a single-site, single-year acacia number over-promises.
- The two test years are **stable (spread 0.002)**, so there is no fluke year — the split generalizes
  consistently across years, just at a modest level. (A smaller earlier run at n_pix=5 looked like it
  had a fluke year, 0.79 vs 0.56; more pixels per crown showed that was sampling noise, not real.)
- Consistent with week 7's finding that acacia is a genuinely hard species split; the spatial holdout
  makes the difficulty explicit rather than hiding it behind polygon-level leakage. The point of the
  slide is the measurement method, not the absolute number.

## Reproduce

```
python week10/acacia_robustness.py --train-years 2019 2021 2023 --eval-years 2020 2024 --n-pix 6
```
(more years / higher n_pix = steadier numbers, more EE sampling time). The held-out region is
`TEST_REGION` in the script (default `SV_S4`).
