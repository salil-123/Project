# #11 — Acacia/non-acacia: counts, a gentle noise filter, and improving the result

`week11/acacia_eval.py`. Always precision + recall + F1 (sir's rule).

## 1. How many crowns?

| class | crowns | median crown area |
|-------|-------:|------------------:|
| acacia | **336** | 27 m² |
| non_acacia | **576** | 33 m² |

## 2. The noise filter — gently

Every crown is a **single tree**: median ~27 m², max ~205 m² — all **smaller than one 10 m Alpha
Earth pixel (100 m²)**. So the literal "drop < 10×10 m" cutoff throws away 98% of the data, which is
wrong. We instead drop only the **degenerate slivers** (< 15 m², plausibly digitisation noise) and keep
the rest:

| class | crowns | dropped (< 15 m²) | kept |
|-------|-------:|------------------:|-----:|
| acacia | 336 | 40 | **296** |
| non_acacia | 576 | 78 | **498** |

**Why it's near-random on Alpha Earth (the real diagnosis):** a ~27 m² crown occupies a fraction of a
10 m pixel, so its embedding is a *mixed* pixel — the acacia tree blended with surrounding ground /
other vegetation. A per-pixel classifier is fighting that dilution; that's the ceiling, not a bug in
the model.

## 3. Improving it — the proven levers (week9 recipe): multi-year + non-linear

Same whole-crown holdout, test on the newest year's held-out crowns. Sampled AE at 2022/2023/2024.

| config | acacia P | acacia R | F1 | acc |
|--------|---------:|---------:|---:|----:|
| linear · 1yr (baseline) | 0.578 | 0.823 | 0.679 | 0.719 |
| linear · multi-year | 0.589 | 0.837 | 0.692 | 0.730 |
| **RF · multi-year** | **0.678** | 0.740 | **0.708** | **0.779** |
| RF · multi-year · tuned threshold | 0.603 | 0.802 | 0.689 | 0.737 |

**Best: Random Forest + multi-year — F1 0.679 → 0.708 (+0.029), accuracy 0.72 → 0.78.** The biggest
move is **precision 0.58 → 0.68**: the non-linear model + more years stops over-calling acacia on the
confusable trees. Threshold tuning traded precision back for recall (F1 slightly lower), so the untuned
RF is the pick. This matches the week9 note (multi-year and non-linear are the runnable levers; single
linear year is the weak floor).

## 4. The ceiling and the real fix

RF + multi-year is a genuine but bounded gain (F1 ~0.71) because the input is still a **mixed 10 m
pixel**. Past this you need features that resolve the crown:
- **Tessera** (128-d) — richer than AE, ~0.73 in prior tests; a one-line `embedding="tessera"` swap.
- **Drone-RGB DINO embeddings** (sir's route, Gaurav's data) — patch embeddings that encode branch/
  canopy structure at sub-metre resolution; the real ceiling-raiser, external and not built here.
- **Object/crown detection** on high-res imagery — the research step, not a quick win.

## Summary
- Crowns: acacia 336, non_acacia 576; gentle < 15 m² filter keeps 296 / 498 (not the 8 a 100 m² cutoff
  would leave).
- Near-random on 10 m AE = mixed (sub-pixel) crowns.
- **RF + multi-year lifts F1 0.68 → 0.71 (acc 0.72 → 0.78), precision +0.10** — the runnable win.
- Real ceiling-raiser: higher-res features (Tessera / drone-RGB DINO).
