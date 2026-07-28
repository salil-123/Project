# #11 — Improving acacia / non-acacia

Acacia vs non-acacia is our hardest split: a species-level distinction between spectrally similar
trees. The current best is 0.745 on unseen years (multi-year Alpha Earth, from `temporal_eval.py`),
up from 0.635 single-year, and about 0.73 on Tessera. Here are the levers, ranked by expected
payoff, with which ones are runnable today.

## 1. More spatial and temporal diversity (highest payoff, proven)
The generalization gap on this project has always closed with data spread, not features: multi-year
pooling alone moved acacia from 0.635 to 0.745. Adding more labelled crowns across sites and years
is the surest gain. Runnable now with the existing multi-year training path
(`refine.train(..., years=[...])`).

## 2. Non-linear model on Tessera (newly enabled this week, #1)
Tessera gives 128 dimensions and already matches the linear Alpha Earth score. A linear model
leaves signal on the table there. As of this week the training flow offers Random Forest (and
XGBoost if installed) as valid families when the inference source is Tessera, because Tessera
renders on the point grid and does not need to be band-math replayable. So a Random Forest on the
acacia Tessera features is now a one-click experiment: select Tessera, pick Random Forest or Auto,
retrain. This is the most likely single-step accuracy lift available today.

## 3. Hard-negative mining (runnable now)
Acacia gets confused with other tree species. The framework already supports negative examples that
fold into the residual sibling: mark clear non-acacia trees as negatives of acacia, then retrain.
This tightens the boundary where the model actually errs.

## 4. Phenology as a pre-filter or feature (runnable now via rules, #12)
Acacia has a different seasonal greenness profile from many native trees. Two ways to use it:
- A rule pre-gate: split the trees class by an NDVI-season rule first, so the classifier only sees
  the plausible-acacia subset. Uses the new rule registry (`ndvi_kharif`, `ndvi_rabi`).
- Extra features: add seasonal NDVI channels alongside the embedding for the acacia node.

## 5. Object or crown detection (needs the object-detection family, #1 stub)
Acacia crowns are discrete objects, so a per-pixel classifier fights mixed-pixel edges. A
segmentation or object-detection model on Tessera or raw Sentinel is the real ceiling-raiser. The
model-family registry already reserves an object-detection slot for the Tessera source; the model
itself is not built yet. This is the natural next research step, not a quick win.

## 6. Threshold and class balance (cheap tuning, runnable now)
Acacia is the minority class, so precision and recall trade off with the decision threshold and the
class weighting. The retrain panel already exposes balanced class weight, undersample, and
oversample; the Auto bake-off picks the best model by held-out accuracy. Worth a sweep before
reaching for anything heavier.

## What shipped this week toward this
Lever 2 is now available: non-linear learners are valid for the Tessera source, and Alpha Earth
stays linear only so it keeps rendering as tiles. Levers 3, 4, and 6 were already possible with the
existing negative-example, rule, and balancing controls. The recommended first experiment is a
Random Forest (or Auto) acacia split on Tessera, compared against the current linear 0.73, followed
by adding hard negatives for the trees it confuses.
