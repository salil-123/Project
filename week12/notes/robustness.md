# Week 12 #9 — try to break the framework

Sir's ask: try to make the framework act out / behave un-intuitively (sensible edge cases, not dumb
load tests), find the cases exhaustively, then fix them. Probes run isolated (all data paths
redirected to a temp dir, no EE, real `data/` untouched — `scratchpad/probe.py`), then confirmed
through the HTTP layer with `TestClient`.

## What I probed

Degenerate/inverted AOIs · empty & malformed rule expressions · rule child colliding with a base
class · split into 0/1 children · re-splitting an already-split node · merge self/duplicate/ghost
sources · adversarial import envelopes (two roots, parent cycle).

## Findings

| # | Surface | Un-intuitive behaviour (before) | Severity | Status |
|---|---------|----------------------------------|----------|--------|
| 1 | **AOI check** | A **degenerate or inverted box** (west==east, south==north, a point, west>east, south>north) returned `ok=True` and was handed to Earth Engine, which then errors opaquely (null-dimension geometry) or paints nonsense. A user dragging a box backwards, or the grid math dividing by a zero span, hits this. Every EE endpoint gates on `aoi.check`, so all of them were exposed. | High | **Fixed** |
| 2 | **`refine.split_op`** | Splitting into **0 children** was a silent no-op that still logged a `split` op; **1 child** made a degenerate single-child node; **re-splitting a node that already has children** appended to them, desyncing the class set from the trained classifier (greenery → tea/non_tea/**foo/bar** while the joblib only knows tea/non_tea). `rule_split_op` already guarded leaf-only; `split_op` didn't — an inconsistency. | High | **Fixed** |
| 3 | **Rule expressions** | Despite `rules.py`'s stated "proven to be a clean boolean" contract, `check_expr` accepted **non-boolean** expressions: a bare `ndvi_annual`, a constant `0.3`, a mixed `ndvi_annual > 0.3 && ndbi`, and a **chained** `a > 0.3 > 0.1`. Each is truthy almost everywhere (or read differently by EE than by Python), so the clause paints the whole map — a silent wrong result, not an error. | Medium | **Fixed** |
| 3b | **`rules._to_python`** (found while fixing 3) | A **leading `!`** negation (`!(ndvi_annual > 0.3)`) translated to a space at column 0, which `ast.parse` rejected as an IndentationError — so a valid negation (an operator the module advertises) was wrongly reported "malformed". | Low | **Fixed** |

### Deliberately left as-is
- **Merge with non-existent leaf sources** is accepted. This is by design: a merge is a post-inference
  relabel over *arbitrary* leaf ids (the cross-model intent), and a source that isn't currently on the
  map is simply a no-op relabel. Not a crash, not corrupting; the UI only ever offers real leaves. Left
  lenient, documented here.
- **Rule child colliding with an existing class** (`class: "water"`) already raised cleanly
  (`hierarchy.add_class` → 400). No change needed.
- **Adversarial imports** (two roots, parent cycle) were already rejected by `validate_envelope`
  before mutating anything. No change needed.

## The fixes

1. **`src/aoi.py` — `valid_bbox()` + gate in `check()`.** Refuses coordinates out of
   longitude −180..180 / latitude −90..90, and any box where `east<=west` or `north<=south`, with a
   plain-language reason, before area/cap logic. Since every render path (`classify`, `classify.tif`,
   `water`, `segment`, `treecrop`, `farmshrub`, `water-frequency`) already calls `aoi.check`, one gate
   covers them all. Smoke test extended with the four degenerate boxes.

2. **`src/refine.py` — `split_op` guard.** Now mirrors `rule_split_op`: unknown parent → `KeyError`;
   a parent that already has children → `ValueError` ("split a leaf"); fewer than two children →
   `ValueError`. Backend already maps both to 400. The ADD path builds its residual+new split via
   `hierarchy.split_class` directly (2 children, leaf), so it's unaffected.

3. **`src/rules.py` — `_is_boolean()` in `check_expr`.** After the whitelist/name checks, the parsed
   expression's root must bottom out in comparisons: a **single-operator** `Compare`, a `Not` of one,
   or `And`/`Or` of booleans. Bare values, constants, arithmetic, mixed bool+value, and chained
   compares are refused with a helpful message. Plus the `_to_python` `.strip()` fix (3b). Smoke test
   extended with the new accept/reject cases.

## Verification

- `python src/aoi.py`, `python src/rules.py`, `python src/merges.py`, `python src/hierarchy.py` — all
  four module smoke tests pass.
- Re-ran `scratchpad/probe.py`: every previously-accepted bad case is now **rejected** (AOI degenerate
  ×5, split 0/1-child + non-leaf re-split, rule bare/constant/mixed/chained), while the good cases
  (normal box, `ndvi_annual > 0.3`, negation, `&&` of two compares) still pass.
- `TestClient`: app **boots** (`/api/health` 200); `/api/classify` on inverted / zero-width /
  zero-height / out-of-range boxes returns **400 with the readable reason before any EE call**;
  `/api/split` with one child returns **400**.
- Live `data/` files (`hierarchy.json`, `op_log.json`, `merge_rules.json`, `active_base.json`)
  **byte-identical** before and after the whole pass (probes ran in a temp dir; the only HTTP calls
  that could mutate returned 400 before writing).

## Files touched (backend)
`src/aoi.py` · `src/refine.py` · `src/rules.py`. No data migrations, no API shape changes — purely
tighter input validation, so existing saved schemes and stored rules are unaffected (validation only
runs on *new* creation, never on load/eval).

---

# Part 2 — driving the live web UI (browser)

Ran the app (`uvicorn backend:app --app-dir src`) and drove it in Chrome, hunting for the UI itself
misbehaving (frozen buttons, unhandled throws, stuck toasts), not just backend validation.

## The one real bug: a **UI freeze** on an invalid custom AOI

| Surface | Behaviour (before) | Severity | Status |
|---------|--------------------|----------|--------|
| **Every run handler** (`runClassify`, `runWater`, water-frequency, segment, GeoTIFF) | With **Custom** area selected, clearing a lat/lon field (or any NaN/degenerate box) made `drawAoi()` throw `Invalid LatLng object: (NaN, …)` deep in Leaflet. Crucially `drawAoi()` is called **after** the handler sets the "working…" toast + disables the button but **outside** the `try`, so the throw was unhandled: the UI **froze on "Classifying at 10 m…" with Run stuck disabled** — dead until a page reload. Reproduced live. | High | **Fixed** |

**Fix (`src/static/app.js`, bumped to `?v=32`):**
- `bboxValid(bb)` — finite, in-range, `east>west && north>south` (mirrors the new server `aoi.valid_bbox`).
- `drawAoi()` now bails (and clears any stale outline) on an invalid box, so it can **never throw**.
- `requireValidBbox()` guards the top of all five run handlers: on a bad box it shows *"Set a valid
  area first: enter a lat/lon and size, or draw a box on the map."* and returns **before** setting the
  work state or firing a request.

**Verified live:** after reload (`?v=32`), clearing the custom lat and hitting Run shows the friendly
error with Run re-enabled and **no exception** — the freeze is gone; the happy-path classify still
returns real counts.

## Things that already behaved well (no change)
- **Segment mining** with no `mining` class on the map → clean error toast listing the live classes.
- **Split into finer classes** with one name → client "Give at least two child names"; splitting a
  non-leaf (root) → the new backend guard's message surfaces as an error toast (not a freeze).
- **Rule split** with empty class names → client "Name the class for both the true and the else case."
- **Half-size slider** min is 0.005°, so the slider alone can't make a degenerate box (only the cleared
  text field could — now guarded).
- **Double-click Run** → the button's `disabled` state during a run blocks a second real click.
- No console errors on load; the classification overlay renders correctly (greenery/built/water).

## Files touched (frontend)
`src/static/app.js` (`bboxValid` + `requireValidBbox` + defensive `drawAoi`, guards on the 5 run
handlers) · `src/static/index.html` (`app.js?v=31 → v=32`).

**No server data mutated by the whole browser pass** — the op-log's newest entry predates the session,
and the live hierarchy is the base 4 classes throughout.

---

# Part 3 — every-button pass (built a complex hierarchy, 3 use cases each)

Full matrix: `week12/notes/ui_button_matrix.md`. Built a 13-node tree (greenery→dense/sparse rule,
water→open/other rule, built_up→residential/commercial, barren→barren_other/mining trained split,
a dense_veg+mining→"disturbed" merge, plus applying the zoo acacia model), then exercised every control.

## Bug #2 (from this pass): bad upload froze the "Uploading…" toast
A corrupt/unsupported upload file makes pyogrio raise `DataSourceError`, which escaped the upload
handler's `(KeyError, ValueError)` catch → **HTTP 500, plain-text body**. The frontend then did
`await r.json()` on that non-JSON body **without try/catch** → threw → the "Uploading…" work-toast hung
forever (page reload required). Same shape as bug #1: a fast failure surfacing as a frozen UI.

**Fix (two layers):**
- `src/backend.py` — `upload_examples` + `add_example` catch the broad case and return a clean **400**
  with a readable reason instead of a 500.
- `src/static/app.js` — a tolerant `readJson()` (falls back to `{detail}` instead of throwing on
  non-JSON), and try/catch around the upload + addDrawn handlers.

**Verified live:** the bad `.txt` now shows *"Error: couldn't read … as GeoJSON/KML polygons"* with no
freeze; a valid geojson/KML still upload fine. Cache bumped `app.js?v=32 → v=33`.

## Everything else held up
26 controls exercised (see matrix) — split/add/merge/rule-split/retrain guards, import validation,
segment/water/geotiff caps, zoo browse + apply (incl. the #11 incompatible-apply 409 confirm),
export/STACD, base switch, merge-undo, draw tool, reset-on-new-area confirm — all behaved. Two minor
non-bug UX notes (segment falls back to mining on a non-leaf; split panel offered on non-leaf nodes).
**Publish buttons intentionally not clicked** (outward-facing push to the shared zoo).

## Files touched this pass
`src/backend.py` · `src/static/app.js` · `src/static/index.html` (`v=32→33`).
