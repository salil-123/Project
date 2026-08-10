# Week 12 — answers to sir's questions

Source: `week12_instructions.txt` (9 points). Points 1–3 are presentation/how-to; 4–8 are technical
questions answered from the code; 9 is the robustness pass (see `week12/notes/robustness.md`).

---

## 1. Provide the outputs in the slides

Put the *actual maps* in the deck, not just descriptions. The renders we can screenshot straight
from the running app (`uvicorn backend:app --app-dir src`), each already an EE tile layer:

- **Base LULC** over the IIT Delhi + Sanjay Van box (`/api/classify`, Realistic tiles).
- **A split in action** — greenery → tea/non-tea over the Assam tea belt, or the IndiaSAT
  tree/crop (`/api/treecrop`) and farm/plantation/scrubland (`/api/farmshrub`) composited into
  greenery over Punjab/Jalpaiguri.
- **Mining segments** over Jharia (`/api/segment`) — the cleaned polygon objects with per-segment area.
- **Acacia** over Sanjay Van, and the **biomass-free** LULC (biomass was decoupled in wk11).

Each slide: the map + one line of what it shows + the held-out metric already on its zoo card. This
is the "show the output" ask — the framework produces all of these live, so they're screenshots, not
mock-ups.

## 2. Water body output at different fortnights (as an output in the slides)

This is a real capability, not a description — `GET /api/water?date=YYYY-MM-DD` returns a water /
non-water tile layer for the fortnight around that date (raw Sentinel-1+2, replayed as EE band math).
For the deck, capture the **same water body at three or four dates across a year** — e.g. a monsoon
tank on `2024-02-15` (dry), `2024-07-15` (monsoon full), `2024-11-15` (receding) — laid out as a
small multiple. It reads immediately as seasonality: the body grows and shrinks.

Complement it with the **per-pixel fortnight-count** raster (`GET /api/water-frequency`, blue ramp):
one image where a perennial body is deep blue (~24 fortnights) and a seasonal pond is pale (a handful).
Two slides: (a) the same body across fortnights, (b) the year summed into a persistence map.

## 3. Google Earth Web — upload polygons as KML and compare

The intuition check sir wants: eyeball our classifier against real imagery.

1. Export the class you care about as vectors: `GET /api/segment?cls=mining&...` (or `classify.tif`
   → polygonize) gives GeoJSON. Convert to **KML** (`ogr2ogr out.kml in.geojson`, GDAL is already a
   dep via pyogrio).
2. Open **earth.google.com/web** → *Projects* → *Import KML file* → drop the KML.
3. The polygons overlay on Google's high-res base imagery, so you can see whether a "mining" segment
   really sits on a pit, or an "acacia" crown on a tree. It's the free, visual ground-truth pass that
   the pixel metrics can't give you — especially for the acacia crowns (are they landing on canopy?)
   and mining segments (real pit vs reclaimed ground).

Round-trip also works the other way: draw truth polygons in Earth Web, export KML, and upload them as
examples (`POST /api/examples/upload` already accepts KML — pyogrio reads the driver).

## 4. What is the "tuned cut" (tuned-threshold) technique?

It's how we move a **binary classifier's decision boundary off the default 0.5** to trade precision
against recall, chosen on data the test set never sees. Used for acacia and pan-India mining
(`week11/acacia_eval.py:68`, `week11/mining_pan_india.py:85` — identical `tune_threshold`):

1. Carve a **validation split out of the training polygons** (whole-polygon `GroupShuffleSplit`, so no
   pixel leaks across train/val/test).
2. Get the model's **probability for the positive class** on that validation split.
3. **Sweep the cut** `t` over `np.linspace(0.15, 0.85, 29)`; at each `t`, label positive where
   `proba >= t`, and score **F1 for the positive class**.
4. Keep the `t` that maximises validation F1, then apply that same `t` to the **held-out test** and
   report P/R/F1.

So the "cut" is the probability threshold; "tuned" = picked to maximise F1 on a held-out validation
fold, not left at 0.5. On acacia it traded precision back for recall and slightly *lowered* F1
(0.708 untuned RF → 0.689), so we kept the untuned RF. On mining it *helped*: precision 0.45 → 0.61,
F1 0.55 → 0.59. It only applies to a rare positive class where the default cut is miscalibrated by the
class imbalance; the deployed multi-class LULC models use `argmax`, not a tuned cut.

## 5. Smoothing logic for the spurious(-water) filter

Two distinct things are at work; both are "smoothing" in the loose sense.

**(a) The spurious-water filter = temporal persistence, not a spatial smooth.**
`infer.annual_water_mask` holds a pixel as water **only if the per-fortnight model called it water in
≥ N fortnights** across the year (`config.WATER_MIN_FORTNIGHTS = 2`). It shares the fortnight-count
image with the frequency map and thresholds it: `count.gte(min_fortnights)`. A road that water-logs
for one fortnight, or an S1-speckle flicker, never accumulates 2 hits and drops out; a genuine pond
persists. Measured effect on sir's EE GT: **spurious water 15% → 2%, precision 0.80 → 0.96** at t=2,
at a cost to small/seasonal recall (`week11/notes/water_gt_eval.md`). It's a code-level correction on
the annual water layer (the deferred water→LULC step), not a UI knob.

**(b) The spatial smooth lives in segmentation, not water.** When we vectorize a class into objects
(`infer.segment_class`), a **3×3 focal-mode** (`focalMode(radius=1, kernelType="square")`) drops
single-pixel specks and fills pin-holes before `reduceToVectors`, then a `min_area_ha` filter removes
sub-threshold blobs. That's the morphological smoothing that makes mining "objects" clean instead of
pixel confetti.

So: **water de-spuriing = a temporal ≥N-fortnight persistence threshold; object cleanup = a 3×3
focal-mode + min-area filter.** There is no per-pixel spatial blur on the water raster itself.

## 6. Filter size — are we augmenting the original data as we move the window?

**No — no window is slid over the data to grow the training set, and nothing is augmented in place.**
Clearing up the two "window/filter size" surfaces:

- **Segmentation focal window:** fixed **3×3** (`radius=1`, square). It's a read-only morphological
  clean on the *output* label image — it does not touch or expand the training data. Its size is a
  constant, not swept.
- **Water persistence window:** the "window" is the **set of ~24 fortnights across the year** we run
  the model over; the filter size is the count threshold **N (=2)**. Again read-only on the output —
  we sum existing fortnight predictions, we don't add anything to training.

The only place data is *augmented* is offline and deliberate, and it's **not** a sliding window:
`train_water_fortnight.py --augment` adds **dryland negatives** (barren/built-up/greenery polygons
sampled at 3 seasons) to the non-water class so the model stops calling everything water. That's a
one-shot enrichment of the training set, decided by us, not a window that harvests new labels as it
moves. The moving-window *self-labelling* idea sir is pointing at is exactly **point 8** below, which
we don't do yet.

## 7. Larger acacia crowns — can we train at the pixel level? (the ~70 m² threshold)

The counts (`week11/notes/acacia_eval.md`): **acacia 336, non-acacia 576**, median crown **~27 m²**,
max **~205 m²**. Alpha Earth pixels are **10 m = 100 m²**. So sir's framing is right: *most crowns are
sub-pixel*, which is precisely why AE is near-random on them — each crown's embedding is a **mixed
pixel** (tree blended with surrounding ground).

- **How many crowns are ≥ one pixel (≥100 m²)?** Only a handful — a 100 m² cutoff leaves ~8 crowns,
  far too few to train. That's why the shipped filter is the *gentle* one (< 15 m² slivers dropped,
  296/498 kept), not a hard "one-pixel" cut.
- **Sir's ≥70 m² / "20–30% of a pixel" idea:** keep only crowns big enough to **dominate** their
  10 m pixel (≥70 m² is ~70% of a pixel; even a 20–30% occupant is a purer signal than a 5% one), so
  the pixel's embedding is mostly-acacia and a *pixel-level* classifier has a real signal to learn. The
  trade is sample count: the bigger the retain threshold, the fewer crowns survive. This is a concrete,
  runnable experiment — **filter the crown set by area, sample the dominated pixel, retrain, report
  P/R/F1 vs the retained count** — and it's the honest way to test whether "train at the pixel level on
  larger crowns" beats the current mixed-pixel ceiling. **Not yet run**; it's the natural next
  acacia experiment and pairs with point 8.
- The real ceiling-raiser remains higher-resolution features (Tessera 128-d, or drone-RGB DINO
  embeddings) that resolve a crown below 10 m — but the ≥70 m² pixel-purity filter is the cheap thing
  to try first with what we have.

## 8. Semi-supervised self-training (expand the training set by iterating)

Sir's recipe, restated: for a parent class, **sample many more pixels at random**, run the **current
classifier**, keep the **very-high-confidence predictions** as new labelled data, add them to the
training set, retrain, and **iterate** — the set grows each round (classic self-training /
pseudo-labelling).

**We don't do this yet** — every trainer today learns once from the user's marked example polygons
(`examples.build_training_frame` → `refine.train`), no confidence-gated expansion loop.

How it would slot into our framework cleanly:
1. Over the AOI, sample a large random pixel set on Alpha Earth (`infer._grid` + `_sample_alpha`,
   already exist).
2. `predict_proba` with the node's current split model (RF/logreg give calibrated-ish probabilities;
   LinearSVC would need `CalibratedClassifierCV`).
3. Keep pixels above a **high confidence cut** (e.g. ≥0.9) as pseudo-positives/negatives; **cap per
   class and hold out spatially** so a confident-but-wrong region doesn't dominate.
4. Concatenate with the real examples, retrain, repeat for K rounds or until the held-out (real-label)
   F1 stops improving.

Guardrails that matter: pseudo-labels reinforce the model's own biases, so gate on a **real-label
holdout** (never let F1 on true labels drop), keep the confidence cut strict, and cap how many pseudo
rows can enter per round. For **acacia** specifically this pairs with point 7: start from the pure
(≥70 m²) crowns, self-train outward onto confident nearby pixels to grow past the tiny seed set. It's a
real feature to build (`refine.self_train(node, rounds, conf, cap)`), not a one-liner, and it's the
most promising *data-side* lever left for the hard fine-splits.

---

### Status summary
- **1, 2, 3** — presentation / how-to: captured above; the outputs (water-by-fortnight, frequency map,
  segments) all exist as live endpoints ready to screenshot; KML round-trips through Earth Web and our
  upload path.
- **4, 5, 6** — explanations of existing code (tuned cut, persistence filter, fixed 3×3 window, no
  in-place augmentation): answered from source.
- **7, 8** — the pixel-purity crown filter and semi-supervised self-training are **proposed
  experiments/features, not yet built**; both are concrete and runnable, and they pair up for acacia.
- **9** — robustness pass done, with fixes: see `week12/notes/robustness.md`.
