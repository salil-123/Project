# Week 11: demonstration walkthrough

A hands-on click-through of what week 11 added and changed. Two kinds of thing this round: a few
interactive changes in the app (any-node models, the spurious-water filter, biomass gone, pan-AEZ
training), and a set of pan-India evaluation experiments that run from the command line, outside the
framework, because that is where the review said the high-quality classifiers should be judged.

Run the app from the repo root:

```
.venv\Scripts\uvicorn backend:app --reload --app-dir src
```

Open `http://127.0.0.1:8000/` and hard-refresh once (Ctrl-F5) so the `?v=26` assets load. The
experiments need live Earth Engine and are run with the project's Python:

```
.venv\Scripts\python week11\<script>.py --help
```

Keep the render distinction from before in mind: the base map, the linear splits, the rule splits, the
water tiles, and the lab's Earth-Engine models render as crisp tiles; a local Random Forest or Tessera
renders on the coarse point grid. The interface tells you which.

---

## 1. Biomass is gone from the tool (7)

Confirm the decoupling first, since it is the simplest change.

1. Look under the classify controls on the left. There is no "Map biomass" button any more; the water
   and segment rows remain.
2. If you call the old endpoint directly, `\/api\/biomass`, it returns not-found. The training scripts
   still exist under `scripts\`, standalone, but they no longer register anything in the zoo.
3. Open the Model Zoo and browse: there is no biomass card. Everything else, including the Random Forest
   on Alpha Earth path it used to share, still works.

## 2. Attach a lab model to any node, not just greenery (5)

This is the main interactive change. The two IndiaSAT models used to always refine greenery; now they
attach to whatever class you have selected.

1. Make sure the base scheme is IndiaSAT (greenery, water, built-up, barren). Pick a vegetated area, for
   example the Jalpaiguri preset.
2. The straightforward case first: select greenery in the hierarchy, open the Model Zoo, open the card
   "Tree vs crop (IndiaSAT SAR RF)". The detail pane now reads "Apply to greenery" and, under suggested
   placement, "Normally refines Greenery, but you can apply it to any node." Press it and Run: greenery
   becomes cropland and tree, the rest of the base map stays.
3. The any-node case, which the review asked for. Reset to base. Select greenery and use "Split by rule"
   to divide it by an NDVI threshold into, say, dense and sparse. Now select the child dense in the
   hierarchy, open the same tree-vs-crop card, and note the button now reads "Apply to dense". Press it
   and Run: only the dense pixels become cropland and tree; sparse, and everything outside greenery, is
   untouched. The model refined a rule-split child, a node that is not a base class.
4. The guard: try to apply the same tree-vs-crop model to a second node while it is already applied
   somewhere. It refuses cleanly, telling you the classes are already in the tree, rather than crashing.

## 3. The lab's farm/shrub model now trains pan-region (1)

No new button; this is a correctness change you can see in the logs.

1. Over a farmland box, for example a Punjab preset, open the zoo and apply
   "Farm / plantation / scrubland (IndiaSAT AEZ RF)". It refines greenery into farm, plantation, and
   scrubland as before.
2. What changed is underneath: it now trains on the whole agro-ecological region the box falls in, not
   just ground truth within forty kilometres of the box, with a balanced cap per class. So a small box
   gets the same model the lab ships, not a thinner one. Over a city box it still refuses with a clear
   message, because it is a rural model.

## 4. Water frequency (13) — and the spurious-water correction in the code

There are two related things here. One is a visual (point 10): the fortnight-count gradient. The other,
the spurious-water threshold (point 13), is deliberately **not** a UI feature — it's a correction on the
water output, so there's nothing to click for it; you verify it in the code and the ground-truth eval.

1. Visual: pick a box with a real water body, e.g. the Man Sagar Lake area near Jaipur, and press
   "💧× Water frequency". You get the blue-gradient count of how many fortnights each pixel was water,
   darker where water persisted. (This is the point-10 visualization.)
2. The correction: the "hold water only over ≥ N fortnights" filter sir asked for (point 13) lives in
   `infer.annual_water_mask`, with the threshold in `config.WATER_MIN_FORTNIGHTS` (default 2). It's the
   rule that will de-spurious the annual water layer when the fortnight water model is folded into the
   LULC (the deferred water step) — a code-level correction, not a button. To see it work, run the
   ground-truth eval in step 7 (`water_gt_eval.py`), which sweeps the threshold and shows the 2-fortnight
   hold cutting spurious water from 15% to 2%.

## 5. STACD provenance, now clean to send (14)

1. Build any classification, then press "Provenance (STACD)" under Save / resume.
2. In the downloaded record, the class scheme now sits under `alg_inputs.input_set`, with three parts:
   the hierarchy tree, the effective `op_sequence`, and the classifier references. The old confusing
   doubly-nested name is gone.
3. The `op_sequence` holds only the steps that produced the current map: if you had reset the tree
   earlier, or made and then undid a merge, those do not appear. The legend lists the real leaf classes,
   with greenery in green and no junk class.
4. This is the record we cross-check with the other STACD teams; the offline check
   `python src\stacd.py` still passes.

## 6. Checking the oversampling / undersampling (retrain balance)

When you train your own split (right panel → ⑤ Retrain this split), the **Class balance** dropdown has
three modes: *balanced* (keep the counts, weight the classes at fit time), *undersample the majority*,
and *oversample the minority*. Two ways to confirm they actually do what they say.

**A. The quick, unambiguous check (no Earth Engine).** This feeds a deliberately skewed toy set
(200 of one class vs 20 of the other) through the exact function the app uses and prints the class
counts after each mode:

```
python week11\check_balance.py
```

Expected output — undersample shrinks the majority to the minority, oversample grows the minority to
the majority, balanced leaves the raw counts (the classifier weights them at fit time):

```
raw counts: {'barren_other': 200, 'mining': 20}
balanced     -> {'barren_other': 200, 'mining': 20}   (rows: 220)
undersample  -> {'mining': 20, 'barren_other': 20}    (rows: 40)
oversample   -> {'mining': 200, 'barren_other': 200}  (rows: 400)
```

**B. End-to-end in the UI.** Make a deliberately skewed split — e.g. select `barren`, Split into
`mining, non_mining`, and mark only a *few* `non_mining` polygons against the 300 shipped `mining`
ones. Then retrain the split three times, once per balance mode, and watch the held-out report in the
metrics box: with *undersample* / *oversample* the minority class's **recall** rises versus an
unbalanced fit (fewer pixels are sacrificed to the majority), which is the whole point of the option.
The "data so far" distribution under ① also shows the skew you set up.

---

## The pan-India experiments (command line)

These do not live in the interface; they are the honest measurements the review asked for. Each prints
precision, recall, and F1, never bare accuracy, and writes a short summary onto the relevant zoo card.

## 6. Mining: is pixel-to-polygon good enough, and how good is the classifier? (9, 12)

```
.venv\Scripts\python week11\mining_eval.py --n-sites 25 --buffer-m 400
.venv\Scripts\python week11\mining_pan_india.py --n-poly 50 --write-card
```

- `mining_eval.py` traces the mining pixels into polygons over buffered ground-truth mine sites and
  matches them against the true mine polygons at the object level. It comes back around 0.07 F1: the
  traced shapes over-fragment and do not line up with real mines, so this is not a delineator.
- `mining_pan_india.py` trains the mining classifier the usual way, with the hard trick of sampling the
  barren ring right around each mine as the negatives, holds out whole polygons, and compares linear
  against a Random Forest with a tuned decision cut. Linear scores about 0.55 F1; the forest with a
  lowered cut reaches about 0.59 and lifts precision from 0.45 to 0.61. The verdict prints, and the
  numbers land on the mining card in the zoo under About, Evidence.

## 7. Water: small against large, and the persistence filter on ground truth (10, 13)

```
.venv\Scripts\python week11\water_eval.py --max-dates 50 --write-card
.venv\Scripts\python week11\water_gt_eval.py --n-dates 10 --write-card
```

- `water_eval.py` scores the deployed model on our local water polygons, split by body size: large
  bodies near 0.99 F1, small bodies about 0.75 with recall 0.67, and a dry-land false-positive rate
  around two percent. So the gap is missed small water, not invented water.
- `water_gt_eval.py` uses the lab's three Earth-Engine ground-truth assets directly, all readable from
  our project, and sweeps the persistence threshold. At two fortnights the spurious rate falls from
  fifteen to two percent and water precision reaches 0.96, while small-water recall drops, which is the
  quantified case for the two-classifier design. It also works out, from the data, which class code is
  water.

## 8. Acacia: counts, a fair filter, and the improvement (11)

```
.venv\Scripts\python week11\acacia_eval.py --years 2022 2023 2024 --n-pix 4
```

- It reports the crown counts, 336 acacia and 576 non-acacia, and applies a gentle noise filter that
  drops only slivers under fifteen square metres, keeping 296 and 498, rather than the ten-by-ten rule
  that would drop ninety-eight percent because every crown is a single sub-pixel tree.
- Then it compares configurations: a linear single-year baseline against pooling several years and a
  Random Forest. F1 rises from about 0.68 to 0.71 and accuracy from 0.72 to 0.78, mostly by raising
  precision. The printed ceiling note is the honest part: the input is still a mixed pixel, so the real
  lift needs higher-resolution features, Tessera or drone imagery with DINO.

---

## What to take away

The interactive changes are small and safe: biomass removed, models attach anywhere with a suggestion,
the water filter added, the provenance record cleaned. The weight of the round is in the experiments,
which measure the two high-quality classifiers honestly, pan-India, on real ground truth, and say plainly
where each one's ceiling is and what would raise it.
