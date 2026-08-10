# #9 — Is the mining pixel→vectorize good enough to skip a GPU segmentation route?

Sir's question: we vectorize the linear mining prediction into polygon objects
(`infer.segment_class`: focal-mode de-speckle → `reduceToVectors` → min-area filter). Compare those
output polygons with the original ground-truth mining polygons and get object-detection metrics
(precision / recall / IoU). If the cheap pixel+vectorize is good enough, we avoid a learned CV
segmentation net (GPU, training data, the works).

## Method — `week11/mining_eval.py`

A pan-India experiment, outside the live framework. For a random sample of GT mining polygons
(`data/examples/mining.geojson`, 300 total) we buffer each into an eval box (sir's "the buffer
becomes the testing ground"), run `segment_class` there, and greedily match predicted vs GT polygons
by IoU (equal-area EPSG:6933). Precision/recall/F1 at IoU ≥ 0.3, plus mean matched IoU and a
union-area IoU.

Run: `python week11/mining_eval.py --n-sites 25 --buffer-m 400 --iou 0.3` (full log:
`week11/notes/mining_eval_run.log`).

## Result (25 sites)

| metric | value |
|--------|------:|
| objects TP / FP / FN | 6 / 130 / 32 |
| **precision** | **0.04** |
| **recall** | **0.16** |
| **F1** | **0.07** |
| mean matched IoU | 0.52 |
| area IoU (union pred vs union GT) | 0.18 |

The dominant failure is **over-fragmentation and over-detection**: around a real mine the classifier
lights up many extra barren/mine-like patches, so a single GT polygon spawns a swarm of predicted
fragments (e.g. site 22: 43 predicted vs 1 GT; site 6: 16 vs 2). Recall is also low — the vectorized
blobs rarely align with a GT polygon's boundary at IoU ≥ 0.3. Where a match does happen, overlap is
only moderate (mean IoU 0.52).

## Verdict

**Pixel+vectorize is not good enough for object-level mining delineation.** The false-positive and
fragmentation rates are far too high to hand these polygons to a downstream consumer as mine objects,
and the boundary IoU is weak. So for the *delineation* goal a learned segmentation / object-detection
route **is** warranted — this experiment is the evidence that justifies that cost, rather than
assuming it.

Two honest caveats on the metric (they explain the low numbers but don't change the verdict):
- GT polygons are often lease/extent boundaries, while the pixel model detects *exposed* mining
  pixels — different granularity, so object-IoU is a harsh test.
- The 400 m buffer box is dominated by one mine plus surrounding barren, which inflates false
  positives (the model's known ~14 % barren-like FP tendency, week7 Asola).

What the pixel model **is** good for: a **detector / screen**. It genuinely lights up real mines
(week7 held-out pixel accuracy 0.86, recall 0.85), so it's a fine first-pass "where to look" layer —
just not a polygon delineator.

Surfaced on the mining model card `mc_barren_v1` (About → Evidence).
