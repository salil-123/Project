# #12 — dense/sparse NDVI rule split vs CoreStack canopy density

Sir: the "imaginary" dense/sparse greenery split (our rule `ndvi_annual > t → dense else sparse`)
can be sanity-checked against CoreStack's canopy-density maps — open them and compare. This is the
quantitative half; the visual half is on corestack.org.

## Method
`week10/canopy_compare.py`. Over an AOI it builds our annual-max NDVI, thresholds it into dense/sparse,
and cross-tabs against **CoreStack LULC v3** (`pan_india_lulc_v3_2023_2024`, band `predicted_label`).
The canopy-relevant codes were identified empirically by ranking LULC v3 classes by mean annual NDVI:

  - **code 6 = tree / forest**, mean NDVI ≈ 0.60 → the dense-canopy class
  - **code 12 = scrubland**, mean NDVI ≈ 0.31 → the sparse-canopy class
  - (barren 7 ≈ 0.12, seasonal water 2/3/4 ≈ 0.07..−0.06 sit below, as expected)

So tree-vs-scrub is exactly the dense-vs-sparse-canopy contrast the rule is trying to draw. Agreement
= area where (our dense & CoreStack tree) + (our sparse & CoreStack scrub), over all vegetated area.

## Results (area, hectares)

| AOI | thr | veg ha | dense&tree | dense&scrub | sparse&tree | sparse&scrub | agreement |
|-----|----:|-------:|-----------:|------------:|------------:|-------------:|----------:|
| Jalpaiguri (forest) | 0.3 | 90,148 | 89,638 | 482 | 13 | 16 | **99.5%** |
| Asola ridge (Delhi) | 0.3 | 4,170 | 4,120 | 50 | 1 | 0 | **98.8%** |
| Central India | 0.3 | 82,496 | 68,554 | 13,913 | 6 | 22 | **83.1%** |
| Central India | 0.5 | 82,496 | 68,153 | 12,981 | 407 | 954 | 83.8% |

## Reading it (the honest answer)

- **On the dense/tree side the rule is excellent.** Where CoreStack says *tree*, our NDVI says *dense*
  ~99–100% of the time across all three AOIs. So high annual NDVI ≙ dense canopy holds up well — the
  rule is validated for detecting dense/high-canopy greenery.
- **A single annual-NDVI threshold does NOT cleanly isolate sparse canopy.** In Central India,
  CoreStack maps ~14,000 ha of *scrubland*, but our rule calls nearly all of it **dense** (13,913 ha
  dense vs 22 ha sparse at thr 0.3). Scrubland there is green enough to clear the threshold. Raising
  the cut to 0.5 recovers only ~950 ha as correctly sparse — most scrub still reads dense.
- **Takeaway for the rule split.** "Dense vs sparse greenery by annual NDVI" is really a *tree vs
  non-tree* detector, not a full canopy-density gauge: it nails dense canopy but under-detects the
  sparse/scrub end, because scrub keeps a moderate annual NDVI. To match CoreStack's canopy-density
  boundary you'd need more than one annual index — dry-season (Rabi) NDVI, or a SAR/texture signal, or
  the rule registry's `ndvi_rabi` instead of `ndvi_annual`. The framework already supports swapping
  the index (rule split is editable), so the fix is a better rule, not new code.

Where the AOI is forest-dominant (Jalpaiguri, Asola) agreement looks near-perfect, but that's because
there's almost no scrub to get wrong — the Central India box is the discriminating test.
