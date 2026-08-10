# Week 12 — every-button UI test matrix (3 use cases each)

Live app driven in Chrome (`?v=33`). Built a hierarchy deeper than the base 4, then exercised every
control with ~3 use cases. **Publish selected / Publish all were deliberately NOT clicked** — they push
to the shared GitHub zoo (outward-facing). One new bug found + fixed (see the ⚠ row).

## Complex hierarchy built (all via the UI)
```
root
├─ greenery → (rule ndvi_annual>0.3)  dense_veg / sparse_veg
├─ water    → (rule ndwi>0)           open_water / other_water
├─ built_up → (split)                 residential / commercial
└─ barren   → (ADD + retrain)         barren_other / mining      [real EE train, acc 1.00 held-out]
merge (cross-model): dense_veg + mining → "disturbed"
also proved: apply the zoo acacia model onto greenery (rewrites it to acacia/non_acacia)
```
13 nodes, 4 split branches, 2 rule splits, 1 trained split, 1 merge. Every op minted the right zoo card.

## Results by control

| Control | Use case 1 | Use case 2 | Use case 3 | Verdict |
|---------|-----------|-----------|-----------|---------|
| **base picker** (onboarding) | Keep current (IndiaSAT) | apply WorldCover base → 7 leaves | apply IndiaSAT base → 4 leaves | ✅ |
| **preset (Area)** | Jharia 368 km² | Assam 454 km² | Man Sagar 4 km² — bbox+area correct | ✅ |
| **map draw rectangle** | dragged a box → custom AOI ≈1 km² set | — | — | ✅ |
| **run (Classify)** | base 4-class | complex composited tree (7 leaves) | after merge/apply reclassify | ✅ |
| **eyeToggle 👁** | hide (🚫) | show (👁) | hide again | ✅ |
| **dlTif (GeoTIFF)** | normal export (complex tree) OK | large box 2,720 km² → clean cap error | (legend in normal) | ✅ |
| **runWater (Map water)** | dry 2024-02-15 (4894 water px) | empty date → "Pick a date" | monsoon 2024-08-15 (4052) — varies | ✅ |
| **runWaterFreq** | 2024: 0–25 fortnights, mean 0.2 | (same guard family) | — | ✅ |
| **runSegment** | mining (merged away) → accurate "not on map" | built_up (non-leaf) → falls back to mining ⚠(minor UX) | other_water leaf → 5 segments, 8.9 ha | ✅ |
| **dlSegment** | downloaded GeoJSON after a segment | — | — | ✅ |
| **viewHier / viewOps** | switch to By operations | back to By hierarchy | — | ✅ |
| **role select** | positive | negative (options present) | — | ✅ |
| **addDrawn** | no polygon → "Draw a polygon first" | (draw+add covered by upload path) | — | ✅ |
| **upload (Choose File)** | geojson → 3 examples + card | ⚠ bad .txt → **froze** (bug, now clean 400 error) | KML → +1 example | ✅ (fixed) |
| **doSplit** | built_up → residential/commercial | one name → "Give at least two" | non-leaf water → "already has sub-classes" | ✅ |
| **doRuleSplit** | greenery ndvi>0.3 | water ndwi>0 | non-leaf / empty-name / bad-threshold errors | ✅ |
| **doAdd** | mining under barren | duplicate → "already exists" | junk '!!!' → "cannot make a canonical id" | ✅ |
| **doRetrain** | barren (real train, acc 1.00) | childless leaf → "no sub-classes to train" | tessera-on-residual → clean error | ✅ |
| **doMerge** | dense_veg+mining → disturbed | one source → "tick at least two" | two sources no name → "name the merged class" | ✅ |
| **merge undo ✕** | removed → sources reappear, reclassified | — | — | ✅ |
| **splitFromZoo** ("Use a model from Zoo") | opens the (filtered) zoo | apply acacia→greenery (compatible) | apply→other_water (incompatible) → 409 confirm | ✅ |
| **openZoo / closeZoo** | opens, cards render | Datasets tab + "only for current view" filter | close | ✅ |
| **card detail** | metrics/P-R-F/balance/training data | Use this model (apply) | Apply-to-selected → incompatible confirm (Cancel/Apply anyway) | ✅ |
| **exportHier** (Download project JSON) | downloaded project.json | — | — | ✅ |
| **exportStacd** (Provenance) | STAC Item + DAG, input_set present | archive flag round-trips | — | ✅ |
| **importHier** | valid project.json → tree restored | malformed JSON → "isn't valid JSON" | broken tree (two roots) → rejected pre-mutation | ✅ |
| **startFresh** | confirm → reset to base 4 | (Cancel path via area-change confirm) | — | ✅ |
| **session reset on area change** | switching area with real work → "New area — start fresh?" confirm; Cancel preserved the tree | ✅ |
| **Publish selected / Publish all** | NOT clicked — outward-facing (pushes to shared GitHub zoo) | — | — | ⏭ skipped |

## ⚠ Bug found + fixed: bad upload froze the "Uploading…" toast
Uploading a corrupt/unsupported file (`.txt`) made pyogrio raise `DataSourceError`, which escaped the
backend's `(KeyError, ValueError)` catch → **HTTP 500 with a plain-text body**. The frontend upload
handler then did `await r.json()` on that non-JSON body **with no try/catch**, so it threw and the
"Uploading…" toast **hung forever**. Fixes:
- **Backend** (`backend.py`): `upload_examples` and `add_example` now also catch the broad case and
  return a clean **400** ("couldn't read … as GeoJSON/KML polygons — check the format").
- **Frontend** (`app.js`): a tolerant `readJson()` (never throws on non-JSON), and try/catch around the
  upload + addDrawn handlers. Verified live: the bad `.txt` now shows a clean error, no freeze.

## Minor UX notes (not bugs)
- **Segment on a non-leaf** silently falls back to `mining` instead of saying "pick a leaf class".
- **Split panel is offered for root / non-leaf** nodes; it only fails after a backend round-trip
  (graceful, but could be dimmed).
- The **area-change reset confirm** is eager — any preset change with real work prompts it.
