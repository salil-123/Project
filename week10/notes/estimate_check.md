# #6 — does the training-time estimate work, and does it show while training?

Two parts to sir's ask: (a) does `/api/estimate` work, and (b) does it show properly on the
notification while the run is happening in the background.

## (a) The estimate works and now covers every algo

`/api/estimate` reads `data/benchmark_profile.json` (regenerated this week) and returns
`sample_s + fit_s = total_s`. Sampling is modelled as *per-getInfo-call latency × number of
batches* (`per_call_s ≈ 8.17 s`, `batch = 3000`), fit as `a + b·rows` per algo. The profile now
carries **randomforest** and **xgboost** alongside the linear models, so an RF/XGBoost estimate is
real instead of silently falling back to the linear coefficients.

Sample estimates over the IIT box (17.4 km², 10 % density → 17,418 pts):

| algo | sample_s | fit_s | total_s |
|------|---------:|------:|--------:|
| linearsvc | 49.1 | 0.23 | 49.3 |
| ridge | 49.1 | 0.02 | 49.1 |
| randomforest | 49.1 | 6.0 | 55.1 |
| xgboost | 49.1 | 5.47 | 54.5 |

The estimate correctly (i) scales with AOI area, (ii) is sampling-dominated (GEE round-trips, not the
fit), and (iii) now ranks the non-linear learners above the linear ones.

## Accuracy vs a real run

One timed retrain (barren split, linearsvc, IIT box):

- **estimate:** 49.3 s (sample 49.1 + fit 0.2)
- **actual:** 91.9 s → ratio **1.86×**

The gap is honest and explainable: the estimate priced 17,418 grid points at 10 % density, but the
real train sampled **23,000 rows** (300 mining polygons × 50 interior pixels + 8,000 residual rows),
and per-polygon interior sampling + CSV assembly carry fixed overhead the profile's flat grid model
doesn't see. Recomputing at the true row count closes some of it (8 sampling calls ≈ 65 s), the rest
is real per-op overhead.

**Verdict:** the estimate is an order-of-magnitude planning tool (right within ~2×, correct scaling
and ranking), not a stopwatch — which is exactly what the week-9 benchmark was built for. Good enough
to set expectations before a run; not a wall-clock guarantee.

## (b) It now shows while the run is in the background

Previously nothing in the UI called `/api/estimate`, and a retrain just printed a static
"can take a minute" toast. Now `doRetrain` (static/app.js):

1. fetches `/api/estimate` for the current AOI + selected algo before the POST, and
2. starts a **live timer** on the amber "work" toast that ticks every second:
   `Retraining "barren" — 34s elapsed / ~49s expected…`.

The work runs in FastAPI's threadpool (other requests aren't blocked), so this toast is the
"working in the background" notification; the elapsed-vs-expected counter gives it a real progress
signal instead of a frozen message. The timer is stopped the instant the POST returns, before the
success/error status is shown.
