# Week 10: demonstration walkthrough

A hands-on click-through of what week 10 added. Run the app from the repo root:

```
.venv\Scripts\uvicorn backend:app --reload --app-dir src
```

Open `http://127.0.0.1:8000/` and hard-refresh once (Ctrl-F5) so the `?v=19` assets load. The default
area is the IIT Delhi and Sanjay Van strip. Several new buttons sit under the classify controls on the
left: Tree vs crop, Farm/shrub, Map biomass, Segment, and Water frequency.

Keep one distinction in mind. The base map and the two IndiaSAT models render as crisp Earth-Engine
tiles, because they classify on Google's servers. Random Forest, biomass, and Tessera render on a
coarse point grid, because they run locally or are not band math. The interface tells you which is
which.

---

## 1. Plug in the IndiaSAT tree-against-crop model (13)
The IndiaSAT models are picked from the Model Zoo, like any other model, not from sidebar buttons.
1. Pick a rural area with fields and trees. A good one is the Assam tea belt preset, or draw a box over
   farmland. Urban Delhi is a poor choice here.
2. Open the Model Zoo, find the card `mc_treecrop_ee_v1` (topology `ee_rf`), and press "Use this model
   on the current view". After a few seconds the map paints two classes, cropland and tree, as crisp
   tiles, with counts in the status line.
3. This is Raman's pan-India model, a Random Forest on a Sentinel-1 radar time series, trained and
   classified entirely inside Earth Engine. Nothing was downloaded and we did not re-implement it; we
   rebuilt the radar feature series and handed it his training asset.
4. The card records the training asset, the feature source, and the classes. It carries no file,
   because the model is re-trained on demand in Earth Engine. It runs as its own overlay for now, not
   yet composited into the base hierarchy.

## 2. Plug in the per-region farm, plantation, scrubland model (13)
1. Still over farmland, open the zoo, pick `mc_farmshrub_ee_v1`, and "Use this model on the current
   view". The tool first works out which agro-ecological region the box falls in, trains the lab's
   Random Forest on that region's ground-truth points, and classifies. It paints farm, plantation, and
   scrubland as tiles.
2. Try it over a city box instead. It refuses with a clear message that there is no agricultural ground
   truth near the area, because this is a rural model, rather than failing opaquely.
3. The card is `ee_rf` topology on the Alpha Earth feature source, the very embedding our base map uses.

## 3. Random Forest on Alpha Earth, and where it renders (7)
1. Select a leaf class, open the Retrain block, and in the Algorithm list you will now see Random Forest
   offered for Alpha Earth, with a note that it renders on the point grid.
2. Mark a little data for a split and retrain with Random Forest selected. When you Run classification,
   the map comes back as a coarse grid of coloured cells, not crisp tiles, and the status line notes the
   Random Forest split is shown on the point grid.
3. Switch the same split's algorithm back to a linear model and retrain: the map is crisp tiles again.
   This is the algorithm-aware render, the model type now decides the path. XGBoost is available on the
   Tessera source, on a Tessera site, since it is installed.
4. "Auto — best model" now bakes off Random Forest alongside the linear models on Alpha Earth too, not
   only on Tessera. If Random Forest wins on accuracy the split simply renders on the point grid; if a
   linear model wins it stays on crisp tiles.

## 4. Biomass, understood from the scripts (3)
Biomass is not surfaced in the interface yet, on purpose: this round was about understanding the
scripts and reproducing the data collection, pending a decision on how to fold it into the framework.
1. Collect the data over an area: `python scripts/prep_gedi_biomass.py --bbox 88.5 26.4 88.9 26.8
   --year 2022 --out data/inputs/gedi_biomass.csv`. It samples GEDI above-ground-biomass shots and
   pairs each with the same Alpha Earth embedding we classify on, plus slope.
2. Train the regressor: `python scripts/train_biomass.py --csv <the CSV> --name aez`. It reports a
   spatial-holdout R2 and saves a Random Forest regressor. This is the piece we can wire in once we
   know how biomass should appear in the LULC.

## 5. Segment the mining class into objects (4)
1. Segmentation needs the mining class live. If it is not, add it once with
   `python week3\scripts\add_mining.py`, which splits barren into barren-other and mining. You do not
   need to restart the app: the server now notices the change on disk and reloads the split on the next
   classify or segment (a script-made split used to stay invisible until a restart — that is fixed).
2. Go to the Asola Bhatti preset, select the mining leaf in the hierarchy, and press "Segment". The
   scattered mining pixels are traced into a handful of clean orange polygons, each with a hover tooltip
   of its area in hectares, and the status line reports the count and total area (about nine segments,
   6.8 hectares on that box).
3. Press the GeoJSON button that appears to download the segments. Note the button segments whichever
   leaf class you have selected, not only mining.
   (If you ever see "class 'mining' isn't on the current map", just run a normal classification once —
   that triggers the reload — then segment again.)

## 6. Map water on a fortnight, and check it works anywhere (11)
1. Default water test location: pick the **"Man Sagar Lake, Jaipur"** preset in Area — a clear water
   body, good for seeing the model light up water and nothing else.
2. Pick a date in "Water on a fortnight" (default 2024-07-14) and press "Map water". The lake paints as
   water on crisp tiles; change the date to a dry-season fortnight and the water extent shrinks. This is
   the intra-annual signal the annual embedding cannot give.
3. The augmented, works-anywhere water model is deployed, so it no longer paints ordinary dry land as
   water the way the old within-water-body model did — try "Map water" over a dry box and it stays
   quiet. Rebuild it if needed with `python scripts\train_water_fortnight.py --augment`.
4. The robustness check is a script, run once:
   `python week10\water_robustness.py --max-dates 60 --n-pix 6 --test-years 2023 2024`. It prints
   temporal-only, spatial-only, and combined spatial-and-temporal accuracy, plus the per-year spread.
   The combined number is around 0.98 with a small spread, so no fluke year.

## 7. Count how many fortnights each pixel held water (11)
1. Stay on the **Man Sagar Lake, Jaipur** preset (or any area with a water body).
2. Press "Water frequency". The tool runs the water model over about twenty four fortnights of the year
   and paints, per pixel, how many fortnights it held water, on a blue ramp: deep blue for perennial
   water, pale for water that appeared only briefly.
3. This is the seasonal-water signal that would let the LULC separate perennial from monsoon-only water.
   It takes a little while, since it runs the model two dozen times server-side.

## 8. Acacia, spatial and temporal robustness together (8)
1. Run `python week10\acacia_robustness.py --train-years 2021 2023 --eval-years 2022 2024 --n-pix 5`.
2. It prints three numbers from one model: temporal-only, holding out years; spatial-only, holding out
   the Sanjay Van region; and combined, holding out region and year. Combined is the lowest, the honest
   worst case.
3. It also prints the per-year accuracy on the held-out region, which flags 2024 as a possible fluke
   year. The crowns carry their source region now, set by `scripts\prep_acacia_examples.py`, which is
   what makes the regional hold-out possible.

## 9. Tessera against Alpha Earth, timed (5)
1. Run `python scripts\benchmark_tessera_vs_ae.py --site "IIT Delhi + Sanjay Van (acacia)" --n 20`.
2. It times download, sample, train, and classify for each pipeline and writes
   `week10\notes\tessera_vs_ae.md`. Alpha Earth totals around twelve seconds, all server-side; Tessera
   around seventy, plus a one-time tile download of about a hundred and fifty megabytes.

## 10. Provenance, now a checked STACD record (1)
1. In Save / resume, press "Provenance (STACD)". A file downloads.
2. Open it. The `stack` is the STAC Item for the raster. The `stacd` is the dependency graph, with one
   algorithm instance per live model, rule, and merge, each now carrying a unique identifier, and the
   output referencing a producing instance. The class hierarchy is embedded as the input set.
3. Call the endpoint with an archive flag to mark a run for keeping:
   `http://127.0.0.1:8000/api/stacd?west=77.165&south=28.520&east=77.205&north=28.560&archive=true`.
   The stack item's `properties.archive` reads true. This is the keep-versus-test signal for a future
   cleanup service.

---

Everything above was verified live against Earth Engine while building it, except where a step says to
train or build a model first. The two IndiaSAT models, the water layers, and the biomass ramp all
render on the real map; the robustness and timing scripts print real measured numbers; the STACD call
is metadata only and returns instantly.
