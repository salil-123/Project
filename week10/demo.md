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
1. Pick a rural area with fields and trees. A good one is the Assam tea belt preset, or draw a box over
   farmland. Urban Delhi is a poor choice here.
2. Press the "Tree vs crop" button. After a few seconds the map paints two classes, cropland and tree,
   as crisp tiles with a small colour legend under the buttons and counts in the status line.
3. This is Raman's pan-India model, a Random Forest on a Sentinel-1 radar time series, trained and
   classified entirely inside Earth Engine. Nothing was downloaded and we did not re-implement it; we
   rebuilt the radar feature series and handed it his training asset.
4. Open the Model Zoo: a card `mc_treecrop_ee_v1` is there, topology `ee_rf`, recording the training
   asset, the feature source, and the classes. It carries no file, because the model is re-trained on
   demand in Earth Engine.

## 2. Plug in the per-region farm, plantation, scrubland model (13)
1. Still over farmland, press "Farm/shrub". The tool first works out which agro-ecological region the
   box falls in, trains the lab's Random Forest on that region's ground-truth points, and classifies.
   It paints farm, plantation, and scrubland as tiles.
2. Try it over a city box instead. It refuses with a clear message that there is no agricultural ground
   truth near the area, because this is a rural model, rather than failing opaquely.
3. Its card `mc_farmshrub_ee_v1` is in the zoo, same `ee_rf` topology, on the Alpha Earth feature
   source, the very embedding our base map uses.

## 3. Random Forest on Alpha Earth, and where it renders (7)
1. Select a leaf class, open the Retrain block, and in the Algorithm list you will now see Random Forest
   offered for Alpha Earth, with a note that it renders on the point grid.
2. Mark a little data for a split and retrain with Random Forest selected. When you Run classification,
   the map comes back as a coarse grid of coloured cells, not crisp tiles, and the status line notes the
   Random Forest split is shown on the point grid.
3. Switch the same split's algorithm back to a linear model and retrain: the map is crisp tiles again.
   This is the algorithm-aware render, the model type now decides the path. XGBoost is available on the
   Tessera source, on a Tessera site, since it is installed.

## 4. Biomass as a colour ramp (3)
1. This needs a biomass model at `data/refine/biomass_aez8.joblib`. If it is missing, build one with
   `python scripts/train_biomass.py --csv cod892_biomass/cod892_biomass/biomass_data/gedi_8_2022_merged_final.csv --name aez8`.
2. Press "Map biomass". The map fills with a green ramp of above-ground biomass in tonnes per hectare,
   pale for low, dark for high, with a min-to-max legend under the button.
3. This is a Random Forest regressor on the same Alpha Earth embedding as everything else, plus slope,
   trained on GEDI lidar shots. It rides the same point-grid path as the Random Forest split above,
   because a regressor is not band math either. Its card in the zoo has topology `regression`.

## 5. Segment the mining class into objects (4)
1. Segmentation needs the mining class live. If it is not, add it once with
   `python week3\scripts\add_mining.py`, which splits barren into barren and mining.
2. Go to the Asola Bhatti preset, select the mining leaf in the hierarchy, and press "Segment". The
   scattered mining pixels are traced into a handful of clean orange polygons, each with a hover tooltip
   of its area in hectares, and the status line reports the count and total area.
3. Press the GeoJSON button that appears to download the segments. Note the button segments whichever
   leaf class you have selected, not only mining.

## 6. Water is robust across bodies and years, and works anywhere (11)
1. The robustness check is a script, run once:
   `python week10\water_robustness.py --max-dates 60 --n-pix 6 --test-years 2023 2024`.
   It prints temporal-only, spatial-only, and combined spatial-and-temporal accuracy, plus the per-year
   spread. The combined number is around 0.98 with a small spread, so no fluke year.
2. The augmented, works-anywhere water model is already deployed. Press "Map water" for a date over a
   dry area, and it no longer paints the dry land as water, which the old within-water-body model did.
   Rebuild it if needed with `python scripts\train_water_fortnight.py --augment`.

## 7. Count how many fortnights each pixel held water (11)
1. Pick an area with a water body, for example the Man Sagar Lake preset.
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
