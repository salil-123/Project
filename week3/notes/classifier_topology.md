# Classifier topology — one per node, not one big multiclass

**Decision (week 3, plan item 1.4):** each tree node that has children owns *its own*
classifier, which only decides among those children. We do **not** train a single
global model over every leaf class.

So when the base map calls a pixel `greenery`, the `greenery` node's classifier (and
only that one) decides whether it's `crops`, `trees`, or `shrubs`. Refinement composes
down the tree, one node at a time.

## Why per-node

- **Natural fit for SPLIT.** Splitting `d` into `d1/d2/d3` means training a model that
  runs only on pixels already labeled `d` (instruction #22). That *is* a per-node
  classifier — no reshaping needed.
- **Cheap, local retrains.** Adding/splitting one class refits one small model on a
  handful of example polygons, not the whole taxonomy. Fast enough for the on-the-fly
  loop the UI needs.
- **Errors stay contained.** A bad split of `greenery` can't disturb `water` vs
  `built_up`. The base map keeps doing the coarse job it's already good at.
- **The hierarchy is the routing.** `node.classifier` + `path_to()` already say which
  model to run and when, so inference is just "walk the tree, apply each node's model."

## Cost / when to revisit

The flip side: many tiny models, and a parent's mistake cascades to its children (a
pixel wrongly called `greenery` never gets a chance to be `water`). For ADD operations
that pull one class out of several parents (instruction #23), a single multiclass model
*might* do better since it sees all classes at once.

## Bake-off result (2026-06-11, greenery case)

`refine.bakeoff("greenery")` / `scripts/bakeoff_greenery.py` — both topologies on one
shared, polygon-held-out test (15,573 px over the 6 leaves barren / built_up / water /
crops / trees / shrubs):

| | accuracy | macro-F1 | crops F1 | trees F1 | shrubs F1 |
|--|--|--|--|--|--|
| **Flat** (one 6-way LinearSVC) | **0.885** | **0.777** | 0.842 | 0.938 | 0.158 |
| **Hierarchical** (base 4-way -> greenery 3-way) | 0.862 | 0.750 | 0.779 | 0.912 | 0.133 |

So flat is ~2 points better in aggregate offline — mostly because the hierarchical path
pays for base-model errors cascading (a pixel must be called greenery before the split
can refine it) and slightly muddier crops precision. Shrubs is weak in **both** (it's a
WorldCover-labelled, 113-px class) — a data problem, not a topology one.

## Verdict: keep per-node as the default

The flat model's small accuracy edge doesn't outweigh what per-node buys the *interactive*
tool:
- **Incremental, cheap retrains.** Adding/splitting a class refits one small model on that
  node's data (the mining ADD refit ~17k rows in seconds). Flat must refit every leaf, and
  needs labelled data for *all* classes each time one changes.
- **Error isolation + a stable base.** A bad greenery split can't disturb water vs built_up.
- **The hierarchy already routes inference** (`node.classifier` + the EE composite).

Flat is worth offering later as a periodic "consolidation" retrain when labels are rich and
the taxonomy has settled — but per-node stays the default for live, additive editing.
