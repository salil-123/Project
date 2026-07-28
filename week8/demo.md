# Week 8: demonstration walkthrough

A hands-on click-through of everything week 8 added. Run the app from the repo root:

```
.venv\Scripts\uvicorn backend:app --reload --app-dir src
```

Open `http://127.0.0.1:8000/` and hard-refresh once (Ctrl-F5) so the `?v=13` assets load. The default
area is the IIT Delhi and Sanjay Van strip (a Tessera site), with greenery split into acacia and
non-acacia (the multi-year model, 0.745).

Handy fact: the crisp map is Alpha-Earth band math; Tessera and any non-linear model run on a
point-grid, so they are evaluated and carded but not painted as tiles. That distinction shows up below.

---

## 1. The two-panel workbench and contextual actions (8, 12, 6, 7)
1. Click greenery in the Hierarchy (left). The right panel retitles to "Selected: Greenery" with a
   one-line explainer, and the actions appear in order: mark data, split, add, merge, retrain. Because
   greenery is a trained split, the advanced training controls (Algorithm, Class balance, Train-years)
   are visible.
2. Click a bare base leaf like built_up. Now the Retrain block shows only the button; the balancing
   knobs are hidden, because you are not training your own split (12).

## 2. Two views of the scheme: hierarchy vs sequence (13, 18)
1. In the Hierarchy section click "By operations". You get the ordered sequence of steps that built the
   current scheme (base, split, retrain).
2. Click a `retrain greenery` row: the right panel opens on greenery, ready to act. Same panel, reached
   from the schema view. Switch back with "By hierarchy".

## 3. Draw the area, clip the overlay, toggle it (3, 21)
1. Use the rectangle tool on the map to draw a box: it becomes the AOI and reclassifies; the
   classification stops exactly at the box (no spill).
2. Click the eye button next to Run: the overlay hides; click again to bring it back. No reclassify.
3. Pick Custom in Area, click the map to drop a centre, drag Half-size: the yellow AOI box grows and
   shrinks live.

## 4. Auto model bake-off, keep the best linear model (17)
1. Select greenery, in the Retrain block set Algorithm to "Auto, best linear model", then Retrain and
   apply.
2. Watch the status and metrics: it bakes off LinearSVC, LogReg, and Ridge and keeps the most accurate
   (Ridge won at 0.731 on our run). The map still renders as crisp tiles, because the winner is linear.
   The model card records the winning estimator.

```
# confirm from the card:
curl -s http://127.0.0.1:8000/api/cards/mc_greenery_v1 | python -c "import sys,json;print(json.load(sys.stdin)['training']['algo'])"
```
(Re-apply the multi-year model afterward with `python scripts/restore_multiyear_acacia.py` if you want
0.745 back as the live greenery split.)

## 5. Train a split on Tessera, for the four sites (16)
1. Stay on a site AOI (the default Delhi box). Select greenery. In the Retrain block a Feature-embedding
   dropdown is now visible (it only appears on the four requested sites).
2. Set embedding to Tessera, then Retrain and apply. It downloads Delhi Tessera tiles, trains on the
   128-d Tessera features, and scores (about 0.73). The status notes it is carded but not on the tile
   map.
3. Open the Model Zoo: the greenery model card's embedding reads tessera / 128-d and it is flagged
   not-expressible-as-band-math. Move the AOI far away (a non-site) and the Tessera option disappears.

## 6. Download the classified output as a GeoTIFF (24)
1. With a bounded area on screen, click the GeoTIFF button. The browser opens or downloads a `.tif`.
2. Drop it into QGIS: one band of integer class codes at 10 m; the status line prints the legend so you
   know which code is which class.

```
# verify it is a real GeoTIFF:
curl -s "http://127.0.0.1:8000/api/classify.tif?west=77.19&south=28.55&east=77.205&north=28.56&year=2024"
```

## 7. Model zoo: standard classes, dataset cross-refs, selective publish (14, 15, 25)
1. Open the Model Zoo, Models tab. Open the greenery card, Annotate, map acacia to Tree cover
   (WorldCover), Save. Its small tile now shows "Tree cover" instead of "acacia"; the detail pane shows
   acacia mapped to Tree cover (14).
2. Open Datasets, open `ds_acacia_polygons_v1`: the "Used in models" section lists `mc_greenery_v1` as a
   clickable chip that jumps to the model (15).
3. Back on the grid, tick two cards (the corner checkbox): the header shows "Publish selected (2)", click
   it to publish just those (25). "Publish all" still works.

## 8. Seasonal-water dataset (27)
```
python scripts/prep_seasonal_water.py
```
Then in the zoo, Datasets, `ds_seasonal_water_v1`: 720 water and 156 non-water polygons, spread 0.61
across India. This is the downloaded ground truth folded into the zoo.

## 9. Save and resume a project (18, 23)
1. Draw a Custom area, set a year (Model Zoo, Alpha Earth card), do a split. Click "Download project
   (JSON)": you get `project.json` holding the scheme, the sequence, and the area, year, and base.
2. Refresh the page, then resume the saved project by loading that file: the tree, area, year, and base
   all come back and the map reclassifies. Datasets and models rode as links.

## 10. Water colour
The water class now renders blue on the map and in the swatches. Any polygon dataset card also shows a
clean spread number.

---

Every step above was exercised while building week 8 (TestClient, live Earth Engine, and a real
`uvicorn` boot). The only Tessera and Earth-Engine-heavy step is 5; keep its AOI small.
