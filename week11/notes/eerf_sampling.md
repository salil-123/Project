# #1 — EE-RF sampling parity with Raman's production models

Sir's concern: Raman's IndiaSAT models are **pan-AEZ** production models; if our port trains on a
smaller sample than his, we hand the user a weaker model than the one that actually ships. Two
questions — is the sampling the same, and why isn't the model trained/stored locally?

## Are we sampling the same as the production notebooks?

| model | features | training scope (production) | our port — before | our port — now |
|-------|----------|------------------------------|-------------------|----------------|
| **tree vs crop** | 46-band Sentinel-1 SAR 16-day time series | pan-India (full `L2_TrainingData_SAR_TimeSeries_1Year` asset) | pan-India — the whole asset fed to `.train()`, only the *classified image* clipped to the box | **unchanged** (already correct) |
| **farm / plantation / scrubland** | Alpha Earth annual embedding | **pan-AEZ** — all `gee_samples_all` in the AOI's agro-ecological zone | **AEZ ∩ 40 km buffer of the box** — a regression: a small box saw only nearby ground truth | **pan-AEZ** — full AEZ, balanced per-class cap |

So **treecrop was already faithful**; only **farmshrub** was degraded, by a `region.buffer(40 km)` +
`filterBounds` that restricted training to samples near the user's box. That's exactly the failure
sir named ("it shouldn't be that we are just training it on that ACZ or the bounding box the user is
interested — we can use a better trained model").

### The fix (`src/ee_rf.py::_farmshrub_classified`)
- Drop the 40 km buffer. Filter `gee_samples_all` by `aez_no == <AOI's AEZ>` only — the AEZ **is** the
  model's scope in production.
- Keep it interactive with a **balanced per-class cap** (`FARMSHRUB_CAP_PER_CLASS = 3000`, deterministic
  seed 42): sample up to 3 000 of each label (farm/plantation/scrubland) across the whole AEZ and merge,
  so a big AEZ doesn't drown the rare scrubland class. Up to ~9 000 training points, pan-AEZ.
- Train the AE mosaic over the **sample points' bounds** (not the box, not a full-AEZ mosaic) — covers
  every training point while staying lazy at `sampleRegions`.

Net effect: the farm/shrub model the user gets is now the pan-AEZ model regardless of box size —
correctness parity with production, no per-box degradation.

## Why isn't the model trained locally / stored?

Because both are **Earth-Engine-native `ee.Classifier.smileRandomForest`** classifiers that train *and*
classify **server-side inside EE** — that's what lets them render as crisp map tiles with no download,
exactly like our Alpha-Earth band-math path. There is no sklearn estimator and no `.joblib` to pickle:
an EE classifier is a server-side object, not a local binary. So the faithful pattern (and Raman's own)
is **retrain-on-the-fly from a fixed ground-truth asset** — the "model" is a recipe (asset + feature
spec + RF params), which is what the zoo card stores.

With the buffer removed, on-the-fly training is now **pan-AEZ and deterministic** (fixed seed, fixed
AEZ sample set), so each run reproduces the same model — the on-the-fly model *equals* the production
model; there's nothing lost by not caching a binary.

**If training time becomes a problem** (pan-AEZ `sampleRegions` is heavier than the old box-local sample),
the clean speed-up is to **materialise each AEZ's training table once** (sample the AE embeddings at the
GT points, store as a small EE asset or local table) and load it per request instead of re-sampling.
That keeps correctness (same pan-AEZ data) while making training near-instant. Noted as a future
optimisation; not built this week (the user chose correctness-only for #1).
