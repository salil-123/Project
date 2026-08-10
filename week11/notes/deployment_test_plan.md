# Week 11 — feature test matrix + deployment-readiness pass

Two questions this answers: (1) what can actually be shown *live* in the demo, and (2) an exhaustive
test plan for every feature — how and where to test each — ahead of next week's deployment. Live UI
tests were run in a real Chrome via the browser automation; heavy compute paths were also checked
directly against the API where clicking through Earth Engine latency was impractical.

## Is it "only the water thing" that's live? — No.

Almost the whole tool is live and clickable. What's *not* live is the pan-India **evaluation
experiments** (`week11/*.py`) — those are command-line, run outside the framework by design (sir's
"pan-India experiment, not in the framework"). Everything in the web app is demoable:

**Live in the browser (demoable):**
- Area: presets, Custom lat/lon + half-size slider, draw a rectangle/polygon on the map.
- Run classification (base map as crisp EE tiles), eye-toggle overlay, GeoTIFF download.
- Water: Map water (one fortnight), Water frequency (blue gradient). (The #13 spurious-water threshold is
  a code-level correction — `infer.annual_water_mask` / `config.WATER_MIN_FORTNIGHTS` — not a UI control.)
- Segment mining (vectorized polygons + GeoJSON download).
- Hierarchy: select a class, Split (mark data / from zoo), Add, **Split by rule**, Merge, Retrain,
  Mark example data (draw or upload), Reset to base.
- Model Zoo: browse, "for this area", card detail, **apply a model to any node (#5, new)**, publish,
  delete, year change.
- Save / resume project (JSON), **Provenance (STACD) export (#14/#15)**, base-scheme switch, the
  first-run base-class modal, By-hierarchy / By-operations views.

**Command-line only (not clickable, show the terminal or the numbers/notes):**
- `mining_eval.py`, `mining_pan_india.py`, `water_eval.py`, `water_gt_eval.py`, `acacia_eval.py`.

So for a live demo you can show the base map, the two IndiaSAT models plugging into any node, the whole
hierarchy-editing loop, the water tools (Map water + Water frequency), mining segments, the zoo, and the
provenance download — not just water.

---

## Live-test results (this pass, real Chrome + Earth Engine)

| # | Feature | How tested | Result |
|---|---------|-----------|--------|
| 1 | App load + first-run base modal | open `/`, dismiss modal | PASS — modal renders, "Keep current scheme" works, `?v=26` assets load |
| 2 | Base classify (crisp tiles) | Run classification, IIT box | PASS — renders tiles; **but ~60 s** because the default tree has greenery→treecrop (SAR) composited (see findings) |
| 3 | Preset switch + auto-classify | pick Man Sagar Lake | PASS — auto-classifies; lake cleanly shown as water (blue), city built-up (red) |
| 4 | Map water (raw Sentinel, one fortnight) | Map water, 2024-07-14 | PASS — `/api/water` 200; lake painted blue, non-water tan |
| 5 | Spurious-water correction (#13) | `infer.annual_water_mask` (code), + `water_gt_eval.py` GT sweep | PASS — code-level threshold (not a UI feature); GT eval shows ≥2-fortnight hold cuts spurious 15%→2% |
| 6 | Segment mining | (API-verified earlier: 9 clean polygons over Asola) | PASS (backend) — UI button wired to `/api/segment` |
| 7 | Provenance STACD (#14/#15) | export + `python src/stacd.py` | PASS — emits `input_set`/`op_sequence`, STAC 1.1.0, collection + links |
| 8 | Attach ee_rf to any node (#5) | (API-verified: treecrop→barren renders cropland/tree) | PASS (backend); UI button reads "Apply to <selected>" |

(#6, #8 were exercised against the API in earlier steps because driving them through the UI adds a full
EE round-trip each; the browser wiring for both is present and was inspected.)

**Backend route smoke (TestClient, all green):** `/api/{tree,catalogue,base,inference-options,
rules/registry,model-families,oplog,merge}` → 200; `/api/stacd` → 200 (aligned 1.1.0 item); `/api/biomass`
→ 404 (removed); oversized `classify` and `water-frequency` → 400 (guards fire); the `mc_treecrop_ee_v1`
card returns the "apply to any node" placement suggestion (#5).

## Findings / deployment gaps surfaced

1. **Default classify is slow (~60 s).** The shipped tree carries the greenery→treecrop IndiaSAT SAR
   model, whose 46-band Sentinel-1 time-series feature image is heavy to build interactively. For a
   snappy demo, either reset to the plain base first, or ship the default tree *without* an ee_rf model
   applied. For deployment: cache/precompute the SAR feature image, or gate ee_rf behind a "this is
   slow" notice. (The plain 4-class base and farm/shrub are much faster.)
2. **Switching areas can wipe the example canvas (important).** `/api/session/reset` archives
   `data/examples/*.geojson` into `data/examples/archive/<ts>/`. It fires not only from the manual
   "Start fresh" button but from **`onAreaSelect` on every preset/area change when `hasUserEdits()` is
   true** — and the shipped default tree already carries edits (greenery→treecrop, barren split), so
   `hasUserEdits()` is true out of the box. Net effect: **the very common demo action of switching
   presets prompts "start fresh?", and confirming archives the demo's acacia/mining example data.** It
   bit this test run twice. Recoverable from `archive/`, but a real hazard. Fixes, in order of value:
   (a) **ship the plain 4-class base as the default** (no edits → no reset prompt on area switch, and it
   also fixes the slow-classify finding #1); (b) scope reset to the tree and *keep* the example files;
   (c) make examples per-area so a switch doesn't touch them.
3. **No favicon** (`GET /favicon.ico` 404). Cosmetic; add one before deploy.
4. **Heavy tile renders can freeze the renderer briefly** (a screenshot timed out mid tile-load on the
   Man Sagar composite). Not a server error — the browser catching up — but it argues again for lighter
   default renders.
5. **Reproducibility:** the app needs live Earth Engine auth (`config.ee_init`), so deployment must ship
   a service-account key (the deferred #2/#9 packaging item), not the interactive `earthengine
   authenticate` used in dev.

---

## Exhaustive test matrix (every feature) — how and where to test

Run the app: `.venv\Scripts\uvicorn backend:app --app-dir src --port 8000`, open
`http://127.0.0.1:8000/`, hard-refresh (Ctrl-F5). "Where" = the UI control or the API route; each has a
quick check and the expected result.

### A. Area & base map
| feature | how to test | expected |
|---------|-------------|----------|
| Preset area | pick each preset in the Area dropdown | map recentres; box redraws; auto-classifies |
| Custom bbox | Area → Custom, set lat/lon, move Half-size slider | box resizes live; area (km²) updates |
| Draw rectangle/polygon | use the ▭ / polygon tool on the map | box set to the drawn shape |
| Run classification | click Run | crisp EE tiles; status "Done: {counts}" |
| Eye toggle | click 👁 | overlay hides/shows without reclassifying |
| GeoTIFF | click ⬇ GeoTIFF | a valid `.tif` downloads (`/api/classify.tif`) |
| Area cap guard | draw a very large box | Run disabled / 400 with a readable reason (`aoi.check`) |

### B. Water (the model on raw Sentinel)
| feature | how to test | expected |
|---------|-------------|----------|
| Map water | pick a lake box, click Map water | `/api/water` 200; water blue for that fortnight |
| Water frequency | click Water frequency | blue gradient, 0..N fortnights, mean printed |
| **Spurious-water correction (#13)** | code-level: `infer.annual_water_mask`, `config.WATER_MIN_FORTNIGHTS`; verify via `week11/water_gt_eval.py` | not a UI control — the ≥N-fortnight hold de-spuriates the annual water layer (deferred water→LULC step) |

### C. Mining
| feature | how to test | expected |
|---------|-------------|----------|
| Segment mining | Asola/Jharia box, click Segment | clean mining polygons + per-segment area; ⬇ GeoJSON |
| Segment gated to class | select a non-mining class, Segment | segments that class (or a clear error) |

### D. Hierarchy editing
| feature | how to test | expected |
|---------|-------------|----------|
| Select class | click a node in the tree | right panel names it; blocks enable |
| Mark example data | draw a polygon, pick role, Add | count updates; distribution shows |
| Upload examples | Choose File → a GeoJSON/KML | ingested to the node |
| Split (own data) | type child names, Create split | node splits; retrain; map updates |
| Split from zoo | Use a model from the Zoo | zoo opens filtered to compatible models |
| **Split by rule** | pick index (NDVI…), set threshold, apply | rule split renders as crisp tiles (no training) |
| Add class | Add flow on a node | new child added |
| Merge | tick leaves, merge into a name | leaves fold into the merged class; undo ✕ works |
| Retrain | Retrain block, choose algo/years | model retrains; card minted |
| Reset to base | ↺ Start fresh (confirm) | tree reseeds (note: archives examples — finding #2) |

### E. Model Zoo
| feature | how to test | expected |
|---------|-------------|----------|
| Browse | Open Model Zoo | cards list; badges; counts |
| For this area | open with a bbox | only models valid for the area |
| Card detail | open a card | metrics, about/evidence, suggested placement |
| **Apply ee_rf to any node (#5)** | select a node, open a treecrop/farmshrub card, "Apply to \<node\>" | that node refined into the model's classes; suggestion shown; collision → clean 400 |
| Apply ordinary model | "Apply to selected class" | applied; 409 + confirm on mismatch |
| Publish / Delete | publish a card / delete an unpublished one | git commit+push / card removed (published guard) |
| Year change | change AE year in the zoo | map re-runs at that year |

### F. Project & provenance
| feature | how to test | expected |
|---------|-------------|----------|
| Save project | Download project (JSON) | scheme + op-sequence + aoi/year/base |
| Resume project | upload a saved JSON | validates, rebinds, reports missing |
| **Provenance STACD (#14/#15)** | Provenance (STACD) | STAC 1.1.0 item + DAG; `alg_inputs.input_set.op_sequence`; collection + links |
| Base-scheme switch | first-run modal or zoo | IndiaSAT-4 ↔ WorldCover-7 reseed |
| Views | By hierarchy / By operations | tree vs ordered step list |

### G. Backend / API smoke (curl or TestClient)
| route | check |
|-------|-------|
| `/api/classify` | 200, `render:tiles`, counts |
| `/api/water`, `/api/water-frequency` | 200 with tiles |
| `/api/segment` | 200 FeatureCollection |
| `/api/stacd` | 200, `stack` + `stacd`, aligned item |
| `/api/apply-eerf` (parent=any node) | 200; collision → 400 |
| `/api/biomass` | 404 (removed, #7) |
| oversized bbox on classify/geotiff/water-frequency | 400 with reason |

### H. Regression / offline (run before every deploy)
- `python src/stacd.py` — provenance smoke.
- `python src/ee_rf.py`, `python src/oplog.py`, `python src/sentinel.py` — offline smokes.
- `node --check src/static/app.js` — the frontend parses.
- grep `biomass` in `src/*.py` → none.
- The five eval scripts `--help` parse.

## Recommended pre-deploy checklist (from the findings)
1. Ship a service-account EE key + `ee_init` from it (not interactive auth).
2. Decide the default tree: plain 4-class base (fast) vs pre-applied treecrop (slow) — recommend plain.
3. Fix / confirm the reset-archives-examples behaviour.
4. Add a favicon; pin deps; set the AOI caps in `config.py` for the deploy host.
5. Add a request timeout + a "this is heavy" hint on the SAR/persistence paths.
