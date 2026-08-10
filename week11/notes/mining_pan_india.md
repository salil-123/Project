# #12 — A high-quality pan-India mining classifier (evaluated outside the framework)

Sir's #12: the project has two tracks — (a) the plug-your-own-classifier framework, and (b) building
**high-quality classifiers that work anywhere in India** (mining, water). For track (b) the accuracy
must be checked with a **pan-India experiment**, outside the framework. This is that experiment for
mining. (It complements #9: #9 asked "are the vectorized *polygons* good?"; #12 asks "how good is the
mining *classifier* itself, pan-India?")

## Method — `week11/mining_pan_india.py`

Built "the usual way", with the water-style hard-negative augmentation:
- **Positives**: mining pixels from `data/examples/mining.geojson` (Alpha Earth embeddings).
- **Hard negatives = the buffer ring.** Sir's cost-saving idea: don't classify all of India's barren
  and dissect it — operate in the **feature-collection space**. For each mining polygon, sample the
  ring `buffer(d).difference(all_mines)` as `not_mining` — the "tentative barren area around a mine".
  Subtracting *all* mines keeps a neighbour's mine out of the ring. This teaches mining-vs-not **within
  barren**, matching "let the base map find barren, then split mining/non-mining".
- **Generic negatives**: barren / built-up / greenery from `data/selected_polygons.geojson`.
- Train `StandardScaler + LinearSVC(balanced)`, **hold out whole polygons** (no pixel leakage), sweep
  the ring width. Pan-India (polygons sampled from across the country).

## Result (50 polygons, whole-polygon holdout)

**Linear, by buffer-ring width** — the buffer barely matters (confusion is with barren *texture*, not
distance from the mine):

| ring width | mining precision | mining recall | F1 |
|-----------:|-----------------:|--------------:|---:|
| 100 m | 0.45 | 0.70 | 0.55 |
| 200 m | 0.45 | 0.71 | 0.55 |
| 500 m | 0.45 | 0.69 | 0.54 |

The linear detector has decent recall (~0.70) but **weak precision (~0.45)** — it over-calls mining on
barren-like ground (the week-7 barren confusion: Asola reclaimed 17% FP, Jharia active 71%).

**Improving it at the best buffer (100 m): non-linear + threshold tuning.**

| model | mining P | mining R | F1 | acc |
|-------|---------:|---------:|---:|----:|
| linear | 0.45 | 0.70 | 0.55 | 0.87 |
| Random Forest (default 0.5) | 0.67 | 0.11 | 0.19 | 0.90 |
| **RF · tuned threshold (0.20)** | **0.61** | 0.58 | **0.59** | 0.91 |

**Reading it.** A plain RF at the default cut is too conservative (recall collapses to 0.11). Dropping
its decision threshold to 0.20 (tuned on a held-out validation split, no leak) gives the best model:
**precision 0.45 → 0.61** — fixing the exact weakness (over-calling mining on barren) — for a recall
give-back (0.70 → 0.58), net **F1 0.55 → 0.59**.

## Verdict

As a pan-India **pixel** classifier, mining is **moderate**: the best config (RF + tuned threshold)
reaches **F1 ≈ 0.59, precision ≈ 0.61**, up from the linear 0.55/0.45. The non-linear model + threshold
is the runnable lift; the ceiling is still the barren/mine spectral overlap. Combined with #9 (the
vectorized polygons are far worse at object level, F1 ≈ 0.07), the picture holds:
- The Alpha-Earth mining detector is a usable **screen** but not a precise delineator.
- Further precision needs harder negatives (reclaimed-mine / quarry examples beyond a spatial ring) or
  the learned-segmentation route (#9).
- This is a **pan-India experiment** (feature-collection space around real mines), not a framework
  feature — exactly as sir framed track (b).

Numbers appended to the mining model card `mc_barren_v1` (About → Evidence). Full log:
`week11/notes/mining_pan_india_run.log`.
