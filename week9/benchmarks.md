# Training-time benchmark (server-admin config) — #8

Profiled on **Windows AMD64, py3.13.5** at 2026-07-27 23:20.

Estimated wall-clock to train one model at **10% pixel density** (1,000 pts/km²), by
AOI size. Sampling is Alpha Earth over Earth Engine (network-bound, usually dominant);
the linear fits are cheap. RandomForest is a **local-only** reference — it can't be
served as EE band math like the linear models, so it's the 'heavier local option' cost.

| AOI (km²) | ~pts | sample (s) | linearsvc fit (s) | randomforest fit (s) | total linearsvc (s) |
|-----------|------|-----------|-------------------|----------------------|---------------------|
| 1 | 1,000 | 8.2 | 0.00 | 0.32 | 8.2 |
| 4 | 4,000 | 16.4 | 0.04 | 1.36 | 16.4 |
| 25 | 25,000 | 73.6 | 0.34 | 8.63 | 74.0 |
| 100 | 100,000 | 278.1 | 1.41 | 34.58 | 279.5 |

Model:
- sampling ≈ 8.18s per getInfo call of 3,000 points (so ⌈n/3,000⌉ calls)
- fit/linearsvc ≈ -0.016 + 0.0000142·rows seconds
- fit/logreg ≈ 0.010 + 0.0000012·rows seconds
- fit/ridge ≈ 0.008 + 0.0000009·rows seconds
- fit/randomforest ≈ -0.025 + 0.0003460·rows seconds
- fit/xgboost ≈ 1.741 + 0.0002139·rows seconds

Tune the AOI caps in `config.py` (`AOI_*`) against these numbers so a drawn box
can't ask for more than the server should take on. `GET /api/estimate` returns a live
estimate from this same profile.