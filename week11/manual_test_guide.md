# Manual test guide — every feature, how to test it, with sample data

A hands-on checklist to click through the whole tool yourself. Each item says what to click, which
sample data to use, and what you should see. It ends with the command-line experiments. For the
deployment-readiness assessment and the API-level matrix, see `week11/notes/deployment_test_plan.md`.

## 0. Start the app

```
.venv\Scripts\uvicorn backend:app --app-dir src --port 8000
```

Open `http://127.0.0.1:8000/`, hard-refresh once (Ctrl-F5) so the `?v=27` assets load. On first visit a
"Choose your base classes" modal appears — click "Keep the current scheme" (or pick IndiaSAT-4).

Gotchas to know before you start (see the deployment notes for detail):
- Switching to a different Area preset, when the tree has any edits, prompts "New area — start fresh?".
  Clicking "Start fresh" **archives your marked example polygons** into `data/examples/archive/`. If you
  want to keep them, click Cancel, or restore later by copying them back from that folder.
- A classify with the IndiaSAT tree/crop model applied is slow (~60 s) because of the Sentinel-1 radar
  time series. The plain base and farm/shrub are much faster.

---

## 1. Where the sample data lives

### Built-in Area presets (the Area dropdown) — one per capability
| preset | bbox `[W,S,E,N]` | good for testing |
|--------|------------------|------------------|
| IIT Delhi + Sanjay Van (acacia) | `77.165, 28.52, 77.205, 28.56` | base classify, acacia, greenery split |
| Jharia coalfield (active mining) | `86.23, 23.62, 86.41, 23.80` | mining detection + segmentation (lights up) |
| Asola Bhatti (reclaimed/acacia) | `77.19, 28.42, 77.27, 28.48` | mining false-positive control (should stay quiet) |
| Jalpaiguri (base-scheme demo) | `88.68, 26.48, 88.78, 26.56` | ee_rf tree/crop, rule split, base switch |
| Assam tea belt (tea/non-tea) | `95.75, 27.55, 95.98, 27.73` | tea split, farm/shrub |
| Man Sagar Lake, Jaipur | `75.835, 26.945, 75.857, 26.963` | water: Map water, Water frequency |

### Example polygons — upload these under "Mark example data" (`data/examples/`)
| file | polygons | class |
|------|---------:|-------|
| `data/examples/acacia.geojson` | 336 | acacia crowns |
| `data/examples/non_acacia.geojson` | 576 | non-acacia crowns |
| `data/examples/mining.geojson` | 300 | mining |
| `data/examples/barren.geojson` | 100 | barren |

### Other sample data (`data/inputs/`, `data/`)
- `data/inputs/seasonal_water.geojson` — 205 water bodies, `water`/`non_water`, dated (water GT).
- `data/inputs/mining_polygons_india.gpkg` — full pan-India mining polygons.
- `data/inputs/acacia_clean_confident_labels.geojson` — acacia crown source.
- `data/selected_polygons.geojson` — barren / built-up / greenery (`core_class`), the dryland negatives.

### Earth-Engine ground-truth assets (used by the eval scripts, all readable from our project)
- `projects/ee-mtpictd/assets/GTSeasonal` (16 seasonal water bodies)
- `projects/ee-mtpictd/assets/GTPerennial` (13 perennial water bodies)
- `projects/ee-vatsal/assets/GT_BINARY_LATEST` (288 water/non-water markings, `class` + `area_sqm`)

### Zoo cards worth applying
- `mc_treecrop_ee_v1` — Tree vs crop (IndiaSAT SAR RF), `ee_rf`
- `mc_farmshrub_ee_v1` — Farm / plantation / scrubland (IndiaSAT AEZ RF), `ee_rf`
- `mc_barren_v1` — the mining split (carries the #9/#12 evidence)

---

## 2. Area & base map

1. Base classify — pick a preset, click **Run classification**. Expect crisp coloured tiles and a
   status "Done: {counts}". (Man Sagar shows a clean blue lake.)
2. Custom bbox — Area → **Custom**, set Lat/Lon, drag the **Half-size** slider. The dashed box resizes
   live; the "Area ≈ N km²" line updates.
3. Draw a box — use the ▭ tool on the map. The AOI snaps to your rectangle.
4. Eye toggle — click **👁**. The overlay hides/shows without reclassifying.
5. GeoTIFF — click **⬇ GeoTIFF**. A `.tif` downloads; open it in QGIS to confirm class codes.
6. Area cap — draw a huge box. Run should refuse with a readable "area too large" message.

## 3. Water (raw Sentinel model) — use Man Sagar Lake

1. **Map water** — set the date (2024-07-14), click **💧 Map water**. The lake paints blue (water),
   surroundings tan (non-water) for that fortnight.
2. **Water frequency** — click **💧× Water frequency**. A blue gradient: darker = more fortnights held
   water. Status prints the mean fortnight count. (Slow — runs the model ~24×.)
3. **Spurious-water correction (#13)** — this is *not* a button. The "hold water only over ≥ N
   fortnights" threshold is a code-level correction on the water output (`infer.annual_water_mask`,
   `config.WATER_MIN_FORTNIGHTS`), to be applied when the fortnight water model feeds the LULC. Verify it
   with the ground-truth eval: `python week11\water_gt_eval.py` (sweeps the threshold; the 2-fortnight
   hold cuts spurious water 15% → 2%).

## 4. Mining — use Jharia (active) then Asola (reclaimed)

1. **Segment mining** — on Jharia, Run classification, then click **⛏ Segment mining**. You get clean
   mining polygons drawn as outlines (speckle removed), not scattered pixels.
2. **Download segments** — click **⬇ GeoJSON**; open the file to see per-segment `area_ha`.
3. False-positive control — repeat on Asola Bhatti (reclaimed). It should flag far fewer mining pixels.

## 5. Hierarchy editing (right panel) — use Jalpaiguri or IIT

1. Select a class — click a node in the **Hierarchy**. The right panel names it; blocks light up.
2. **Mark example data** — draw a polygon on the map, pick Role (positive/negative), click **Add**. The
   distribution bar updates. Or **upload** `data/examples/acacia.geojson` (select the `acacia` node first).
3. **Split into finer classes** — select `greenery`, type `dense, sparse`, click **Create split**, mark a
   little data for each child, then Retrain.
4. **Split by rule (no training)** — select `greenery`, pick Index `NDVI (annual median)`, `>`, `0.3`,
   name true `dense_veg` / false `sparse_veg`, click **Create rule split**. Renders as crisp tiles with
   no data to mark.
5. **Add a class** — select a node, type a name, **Add class**.
6. **Merge classes** — tick two leaves in the tree (e.g. `mining` + a greenery leaf), name it
   `extractive`, click **Create merge**. They fold into one class; undo with the ✕ on the tree.
7. **Retrain this split** — with children that have data, choose an Algorithm (try Auto), optionally
   Train across years `2019, 2021, 2023`, click **Retrain & apply**. Metrics print below.
8. **Start fresh** — click **↺** (confirm). Reseeds to base. (Note: this archives example polygons.)

## 6. Model Zoo — the headline: attach a model to any node (#5)

1. **Open Model Zoo** — browse the Models/Datasets tabs; tick "only for current view" to filter.
2. **Card detail** — click a card; see its metrics, About/Evidence, and Suggested placement.
3. **Apply tree/crop to greenery** — select `greenery` in the tree, open **Tree vs crop (IndiaSAT SAR
   RF)**, click **Apply to "greenery"**. Greenery becomes `cropland`/`tree`; the rest of the map stays.
4. **Apply to a non-greenery / deep node (the new bit)** — first rule-split greenery (step 5.4) into
   `dense_veg`/`sparse_veg`. Select `dense_veg`, open the same card — the button now reads **Apply to
   "dense_veg"**. Apply it: only `dense_veg` pixels become cropland/tree. This is the any-node promise.
5. **Collision guard** — with tree/crop already applied somewhere, try applying it to a second node. It
   refuses cleanly ("classes already in the tree").
6. **Farm/shrub** — over a farmland box (Assam/Punjab), apply **Farm / plantation / scrubland**; over a
   city box it refuses (no agri ground truth) — a clear message, not a crash.
7. **Publish / Delete** — publish a card (git commit+push) or delete an unpublished one.

## 7. Project & provenance

1. **Download project (JSON)** — saves the scheme + op-sequence + area/year/base.
2. **Resume** — upload that JSON under "Resume a saved project"; it validates then applies.
3. **Provenance (STACD) (#14/#15)** — click **⬇ Provenance (STACD)**. Open the file: it's a STAC 1.1.0
   item with a `collection`, real `links`, and `alg_inputs.input_set.op_sequence` (the effective steps).
4. **Base-scheme switch** — from the first-run modal or the zoo, switch IndiaSAT-4 ↔ WorldCover-7; the
   tree reseeds to the new classes.

## 8. Command-line experiments (not in the UI — show the terminal / the notes)

These are the pan-India evaluations; they print precision/recall/F1 and write onto the zoo cards.

```
.venv\Scripts\python week11\mining_eval.py --n-sites 25 --buffer-m 400      # object IoU vs GT polygons
.venv\Scripts\python week11\mining_pan_india.py --n-poly 50 --write-card    # classifier P/R/F1 (linear vs RF)
.venv\Scripts\python week11\water_eval.py --max-dates 50 --write-card       # small vs large water bodies
.venv\Scripts\python week11\water_gt_eval.py --n-dates 10 --write-card      # EE GT + persistence sweep
.venv\Scripts\python week11\acacia_eval.py --years 2022 2023 2024           # counts, filter, RF/multi-year
```

Sample data they use: `data/examples/mining.geojson`, `data/inputs/seasonal_water.geojson`,
`data/selected_polygons.geojson`, `data/examples/{acacia,non_acacia}.geojson`, and the three EE GT
assets above.

## 9. Quick offline regressions (run before a demo/deploy)

```
.venv\Scripts\python src\stacd.py          # provenance smoke (input_set / op_sequence / 1.1.0)
.venv\Scripts\python src\ee_rf.py          # ee_rf offline checks
node --check src\static\app.js             # frontend parses
```
