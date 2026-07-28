# Why not use WorldCover labels directly for India? (#2)

Sir's question: we take IndiaSAT's many classes and merge them down to a few base classes.
WorldCover also has many classes — could we use them directly, or is mapping them down to
fewer base classes better? Short answer: **you already can use WorldCover directly (it's a
selectable base scheme), but in India mapping its classes down is usually the better move —
and for the same reason we merge IndiaSAT: the extra classes aren't well enough supported to
learn.**

## Does our deployed model show WorldCover labels directly? — No.

Concretely, in `data/worldcover_train.csv` every WorldCover code is already mapped down to a base
class before training: 10/20/30/40 (tree/shrub/grass/crop) -> `greenery`, 50 -> `built_up`,
60 -> `barren`, 80 -> `water` (70/90/95/100 -> dropped `other`). The deployed Realistic model
(`model_pooled.joblib`) therefore **outputs only `[barren, built_up, greenery, water]`** — WorldCover
is used purely as extra *training signal* (and as India's class prior), not as the label you see.
WorldCover's own classes (`tree/shrub/grass/crop/bare/built/water`) surface **only** if you switch to
the WorldCover-7 base (`model_worldcover_base.joblib`). So by default: mapped down, not shown.

## What WorldCover is

ESA WorldCover v200 is a global 10 m land-cover product with ~11 classes: tree cover,
shrubland, grassland, cropland, built-up, bare/sparse, snow/ice, permanent water, herbaceous
wetland, mangrove, moss/lichen. It's a *weak label* — auto-derived from Sentinel, not expert-
drawn — so it's convenient and India-wide but noisier than the IndiaSAT/FarmForest polygons.

## The framework already offers both readings

- **Direct-ish:** the WorldCover base scheme (`mc_worldcover_base_v1`) is a real, pickable base
  in the zoo. Choosing it seeds the tree with WorldCover classes and classifies against them.
- **Mapped down:** the base-class picker (IndiaSAT-4), the cross-model **merge** layer, and
  split/add all let you collapse or grow classes on top of any base.

So "use WorldCover directly" isn't a missing feature — it's one of two bases the user can pick.
The real question is *when* each is right.

## Why "direct" WorldCover quietly becomes "mapped down" in India

Our WorldCover base already **drops four classes** — snow, wetland, moss, mangrove — because
`worldcover_train.csv` has almost no India support for them:

| class | India points | usable? |
|-------|-------------:|---------|
| cropland | 4522 | yes |
| tree cover | 2324 | yes |
| grassland | 997 | yes |
| shrubland | 430 | yes |
| bare / sparse | 307 | yes |
| built-up | 217 | yes |
| water | 145 | yes |
| snow/ice | 29 | no |
| herbaceous wetland | 12 | no |
| moss/lichen | 10 | no |
| mangrove | 7 | no |

You cannot learn a class from 7–29 points. So "use all of WorldCover directly" over India
**already collapses to ~7 classes** whether you like it or not — which is itself a
mapping-down. The choice isn't "all classes vs fewer"; it's "which of the supportable classes
do you actually want."

## When to use raw classes vs map them down

- **Use the raw (finer) classes** when they're well-supported for your AOI *and* your task
  needs the distinction — e.g. cropland vs tree cover vs built-up in a mixed landscape.
- **Map them down to base classes** when a fine class is unreliable or irrelevant for the task
  (e.g. shrubland/grassland bleeding into each other), or when you want a **stable spine** to
  then grow with your own examples. This is exactly what the merge layer is for: relabel
  chosen leaves into one class, no retraining.
- **Prefer expert labels (IndiaSAT) over WorldCover** when accuracy matters: WorldCover is
  weak-label and trails the expert polygons, so we ship it as a *starting* scheme, not a better
  one (see `master_document.md` caveats). WorldCover's value is its India-wide class **prior**
  (it keeps the Realistic model calibrated to India's ~92%-greenery mix), not its fine classes.

## Recommended workflow (demonstrated on Jalpaiguri)

1. Pick the base whose classes you trust for the AOI (IndiaSAT-4, or WorldCover-7 if you want
   crop/tree/grass/shrub/bare/built/water to start from).
2. **Merge** where the model is unreliable — collapse shrubland+grassland, say, into one
   "open vegetation" if the split isn't earning its keep.
3. **Split/Add** where you need finer classes, giving the tool your own example polygons
   (this is how tea/non-tea and acacia/non-acacia are built — distinctions WorldCover never had).

The point: WorldCover *directly* and WorldCover *mapped down* aren't a fork in the road — they're
the two ends of the same dial (base-scheme + merge + split), and India's thin support for the
rare classes pushes you toward the mapped-down end by default.
