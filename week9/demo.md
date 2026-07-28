# Week 9: demonstration walkthrough

A hands-on click-through of what week 9 added. Run the app from the repo root:

```
.venv\Scripts\uvicorn backend:app --reload --app-dir src
```

Open `http://127.0.0.1:8000/` and hard-refresh once (Ctrl-F5) so the `?v=15` assets load. The default
area is the IIT Delhi and Sanjay Van strip.

Handy fact to keep in mind: the crisp map is Alpha-Earth band math. A rule split is also band math
(the indices are computed in Earth Engine), so it rides the crisp tile map too. Tessera and any
non-linear model run on a point grid instead. That distinction shows up below.

---

## 1. Split a class by a rule, no data marking (12)
1. Click greenery in the Hierarchy on the left. On the right, find the block "Split by rule (no
   training)".
2. Pick the variable `ndvi_annual`, operator `>`, threshold `0.3`. Name the true class `dense_veg`
   and the else class `sparse_veg`.
3. Press "Create rule split". The map reclassifies within a second or two and greenery is now dense
   and sparse vegetation, painted as crisp tiles, not a coarse grid.
4. Note the description under the variable: it explains what each index means. The advanced box below
   accepts a raw expression such as `ndvi_annual > 0.3 && slope < 5` for combined conditions.
5. Open the Model Zoo: a new card `mc_greenery_rule_v1` is there, topology "rule split", with the
   expression and the variables it reads recorded. A rule is a model the user built, so it is carded.

## 2. The rule survives save and resume (12, 4)
1. In Save / resume, press "Download project (JSON)". Open the file: the greenery node carries a
   `rule` block. The rule lives in the tree, so it travels with the project.
2. Reload the same file with the file picker. The rule split comes back and reclassifies. Nothing was
   retrained, because a rule has nothing to train.

## 3. A decision tree that reassigns across branches (13)
1. Start fresh (the reset button), then split greenery into `crop` and `shrub` the normal way (mark a
   little data for each and retrain), or use any existing split.
2. Rule-split `crop` on `slope` (for example `slope > 15`), naming the parts `crop_prime` and
   `shrub_prime`.
3. In the Merge block, tick `shrub_prime` and `shrub` in the tree, name the merge `shrub`, and create
   it. The steep crop pixels are now labelled shrub.
4. This is the crop-to-shrub reassignment: split, rule split, then merge, composed into one decision
   tree where a rule moves pixels from one branch to another.

## 4. Water on a single fortnight (5, 7)
1. This uses the water model at `data/refine/water_fortnight.joblib`. If it is missing, train it once
   with `python scripts/train_water_fortnight.py` (it prints a held-out accuracy around 0.92).
2. Call the endpoint directly for the current box and a date, for example in the browser:
   `http://127.0.0.1:8000/api/water?west=77.165&south=28.520&east=77.205&north=28.560&date=2024-07-14`.
   You get a tile URL and water against non-water counts for that fortnight.
3. Change the date to a dry-season fortnight and the counts change: this is the intra-annual water
   signal the annual embedding cannot give. The model is trained on raw Sentinel and served as band
   math, so it stays interactive.

## 5. A size cap on the drawn area (3)
1. Pick Custom in Area and drag Half-size to a large value, or draw a very large rectangle. The area
   line under the box turns red and reports the square kilometres, and the Run button disables past
   the limit.
2. If you force a large request, the server refuses it with a readable reason instead of hanging. The
   GeoTIFF export has a tighter limit than the tile map, because that download is size capped.

## 6. The model list follows the data (1)
1. Select a class inside a Tessera site (for example the default Delhi box) and open the Retrain
   block. The feature embedding option appears because the area is a Tessera site.
2. With embedding set to Alpha Earth, the Algorithm list is linear only: LinearSVC, Logistic
   Regression, Ridge, Auto.
3. Switch embedding to Tessera. The Algorithm list grows: Random Forest appears, XGBoost shows as
   unavailable unless installed, and an object-detection family is listed as planned. Earth Engine
   stays linear because only a linear model renders as tiles; a local Tessera run is not limited that
   way.

## 7. Provenance for the output (4)
1. In Save / resume, press "Provenance (STACD)". A file `output.stacd.json` downloads.
2. Open it. The `stack` is a STAC Item for the raster: bounding box, geometry, the class legend with
   colours, and asset links. The `stacd` is the workflow: the dataset and algorithm nodes, one
   algorithm instance per live model, rule, and merge with where its artifact lives, and the class
   hierarchy embedded as the input set that produced the output.
3. Make a change (a split) and export again: the provenance reflects the new model.

## 8. Training-time estimate (8)
1. The benchmark writes `data/benchmark_profile.json` and `week9/benchmarks.md`. Regenerate with
   `python scripts/benchmark_training.py` if needed.
2. Ask for an estimate on the current box:
   `http://127.0.0.1:8000/api/estimate?west=77.0&south=28.0&east=77.2&north=28.2&algo=linearsvc`.
   You get the point count and the expected sampling and fit seconds, read from the profile.

---

Everything above was verified live against Earth Engine while building it, except where a step says
to train a model first. The rule split and the water fortnight both render on the real map; the
STACD and estimate calls are metadata only and return instantly.
