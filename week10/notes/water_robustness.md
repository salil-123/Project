# #11 — Water step 1: robustness, augmentation, fortnight-count

Sir framed the water work as two steps: **get water/non-water within water bodies working and see
the accuracy first**, then decide how to integrate it into the LULC. This is step 1.

## Spatial + temporal robustness

`week10/water_robustness.py`. The seasonal-water polygons carry `waterbody` (spatial group) and a
`date` (year for the temporal split), so we hold out whole water bodies and whole years, same
`StandardScaler + LinearSVC(balanced)` as the deployed model, features sampled with
`sentinel.sample_points`.

Run: `--max-dates 60 --n-pix 6 --test-years 2023 2024` → 696 usable pixels, 71 water bodies, years
2018–2025 (water 600 / non_water 96 — negatives are water-body-tied, see below).

| check | held out | accuracy |
|-------|----------|---------:|
| temporal-only | unseen years, all water bodies | **0.913** |
| spatial-only | unseen water bodies (17/71) | **0.993** |
| spatial + temporal | unseen water bodies **and** years | **0.979** |

Per eval-year on the held-out water bodies: **2023 = 1.000, 2024 = 0.958** → year-to-year spread
**0.042 (stable, no fluke year)**.

**Reading it.** Unlike acacia (a hard species split), water-vs-non-water *within water bodies* is
easy and **very robust**: the combined spatial+temporal holdout barely dents accuracy (0.979), and
there's no fluke year. That directly answers sir's step-1 question — the within-water-body classifier
is solid enough to build on. (The numbers are high partly because the negatives here are all
water-body-tied; the honest weakness is *outside* water bodies, which the augmentation below targets.)

## Non-water augmentation (the "works anywhere" problem)

The deployed model's non_water pixels come only from dry dates / outer rings of water bodies, so it
has never seen generic dryland — its non_water precision is ~0.72 and it over-calls water on built-up
/ barren / vegetation. `scripts/train_water_fortnight.py --augment` adds barren/built-up/greenery
negatives (from `data/selected_polygons.geojson`) sampled with the same Sentinel features across
three seasons, labelled non_water.

**Result (live):** augmenting with 6,024 dryland non-water pixels lifts **non_water precision from
~0.72 to 0.994** (water recall 0.94, overall 0.974 on the held-out split). So the model stops calling
dryland water — exactly the fix sir described for running it anywhere. Because that's strictly better
for an interactive tool (fewer false-positive water pixels on built-up/barren/vegetation), the
**augmented model is now the deployed water model** (`water_fortnight.joblib`, also kept as
`water_fortnight_augmented.joblib` + carded `mc_water_fortnight_augmented_v1`). This is the
works-anywhere classifier that step 2 would put at the top of the hierarchy (water/non-water first,
then split non-water). Retrain from scratch with `scripts/train_water_fortnight.py [--augment]`.

## Per-pixel fortnight-count (integration hook)

`infer.water_frequency_tiles` / `GET /api/water-frequency` runs the linear water model over ~24
fortnights of a year and sums the water masks into a per-pixel count (0..24), served as a blue-ramp
tile layer (UI: 💧× Water frequency). A perennial water body scores near 24; a monsoon-only pond
scores low. Verified live over Man Sagar Lake: mean ≈ 3.9 fortnights across the box. This is the
"attach to each pixel how many fortnights it held water" layer sir wants so seasonal water becomes
legible for the LULC — it's what would let the hierarchy tell perennial from seasonal water, or catch
kharif-only water the annual map misses (the IndiaSAT seasonal-water point).

To make `feature_image` survive a whole-year sweep, `sentinel._s1/_s2` now guarantee their bands even
on a cloudy fortnight with no scene (merge a masked zero image), instead of crashing on `.select`.

## Deferred to step 2 (per sir)
Wiring water into the hierarchy — run water/non-water first then split non-water (needs the augmented,
run-anywhere model), or keep it as a water sub-signal with the fortnight-count + an NDWI mask for
seasonal water. "Let's get the accuracy first, then decide" — done; the decision is the next step.
