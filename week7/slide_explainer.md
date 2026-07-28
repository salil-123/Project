# Week 7 — slide-by-slide explainer

The "understand every word" companion to `slides_week7.tex` (deck title: *Applying the LULC
classifier on real sites: robustness, data adequacy, and validation*). `demo.md` is the
click-through; this file explains the idea, the numbers, and the honest caveats behind each point so
you can field follow-ups. Read **Foundations** once, then go slide by slide. All numbers here are the
live results from `week7/site_tests.py`, `temporal_eval.py`, and the two run logs in `week7/`.

---

## Foundations: things to know cold (week-7 additions)

Everything from the week-6 foundations still holds (Alpha Earth embeddings, the linear
`StandardScaler → LinearSVC`, the hierarchy tree, the model zoo). Four new things this week:

1. **A "split" trains from example polygons.** For a node like *greenery → acacia / non-acacia*,
   each child has a few labelled polygons; we sample ~N interior pixels per polygon, turn each into
   its 64-number Alpha Earth vector, and fit the small linear classifier. Tea/non-tea, mining,
   acacia/non-acacia are all this same machine.
2. **Alpha Earth is per-year.** There's a separate annual mosaic for each year 2017–2024. The same
   polygon sampled in 2019 vs 2023 gives *different* vectors, because the ground (and the imagery)
   changed. That is the entire basis of the temporal work.
3. **Leak-free evaluation = hold out whole polygons.** We never let a polygon's pixels sit in both
   train and test — we split by polygon (a "group"), so accuracy isn't inflated by memorising a
   polygon. In the multi-year work we *also* hold out whole years.
4. **What week 7 is about:** stop building, start *applying and stress-testing* — real sites (acacia,
   tea, mining), robustness across years, an honest measure of whether there's enough data, and a
   safety check on uploaded schemes.

Two facts to have ready because they explain a lot of choices:

- **The base model can't be trained on multiple years cheaply.** Its training tables
  (`master_alpha_full.csv`, `worldcover_train.csv`) are baked at 2024 and have **no year column**;
  Tessera is 2024-only. So multi-year work lives on the **split path** (which samples Alpha Earth
  live and already takes a year), not the base.
- **The mining number is from a purpose-built binary detector**, not the exact live-tree path — it's
  an honest *indicator* of false-positive tendency, not a production metric (see Slide 4 caveat).

---

## Slide 1 — Where we are, and what was advised

Two columns: what's done vs. what sir asked for this week.

- **Done so far.** The 4-class base map + the living hierarchy (split/add, retrain a node on the
  fly), and the git-backed zoo with save/reload, merging, base and year selection, and publishing.
- **What was advised** — the four threads the rest of the deck answers:
  - **apply on real sites** — acacia vs non-acacia, tea vs non-tea, mining;
  - **make models robust across years** by training on more than one year;
  - **judge data by coverage and spread**, not a raw count;
  - **validate an uploaded scheme before running it**, and revisit WorldCover and Tessera as data
    choices.

Why it matters: it frames everything after as *responses to specific asks*, not invented features.

## Slide 2 — Standard testing sites

- **The point:** we now have fixed, named places to test on, chosen from a menu instead of typing
  coordinates. Four default areas: **IIT Delhi + Sanjay Van** (acacia), **Asola Bhatti** (mining
  false-positive probe), **Jalpaiguri** (base-scheme demo), and the **Assam tea belt** (tea/non-tea).
- **Why the IIT strip is the home site:** in one small box it has all the ingredients — IIT's
  built-up, Sanjay Van's tree cover and a small water body — *and* the labelled acacia crowns sit
  inside it, so you can show base classes and a species split on the same screen.
- **The acacia data:** 912 confidently-labelled tree crowns (336 acacia, 576 non-acacia), turned
  into ready training-example files by `scripts/prep_acacia_examples.py`. Acacia here means the
  invasive *Prosopis juliflora* ("vilayati kikar"), a real problem in Delhi's ridge forest.
- **Why Asola Bhatti is a *probe*:** its old mines were reclaimed into built-up and scrub, so there's
  little active mining left. That makes it a natural test of *false positives* — a good mining model
  should stay mostly quiet there.

## Slide 3 — Robustness across years

**Plain-language version of the whole slide.** Every pixel is turned into 64 numbers by Alpha Earth,
and Alpha Earth makes a *fresh* set of those numbers each year. The same acacia tree produces
slightly different numbers in 2020 than in 2023 — because the rainfall, the sun angle, the sensor,
and the tree itself all changed a little. A classifier trained only on 2023 learned "these 2023
numbers mean acacia"; hand it 2020's numbers and it gets a bit more wrong. That accuracy drop, from
applying a model to a *year it never trained on*, is what we mean by **"drift."** The fix is to train
on several years at once, so the model has seen the year-to-year wobble and doesn't rely on any one
year's exact numbers.

**› What "can drift on another" means, precisely.** Train on year A, then run on year B (B ≠ A). If
accuracy on B is noticeably lower than on A, the model has *drifted* on B — it's over-fitted to A's
particular conditions. A robust model keeps roughly the same accuracy across years. Our whole test is
built to measure exactly this gap.

- **The mechanism:** a split can now be trained on **several years at once**
  (`refine.train(parent, years=[2019,2021,2023])`). The same polygon sampled in different years
  becomes *more* training examples; because a whole polygon is still held out together, the extra
  years are honest time-augmentation, not leakage.
- **The check (sir's exact protocol):** train on some years, then test on years the model **never
  saw**. `temporal_eval.py` does this and compares a single-year baseline to the multi-year model.
- **Acacia result:** train on 2019/2021/2023, test on the unseen 2020 and 2024 → accuracy rises from
  **0.635 (single-year) to 0.745 (multi-year), about +11 points.** Multi-year training genuinely buys
  temporal robustness on this split.
- **Base-class result (the honest contrast):** the same protocol on greenery/water/built-up/barren
  gives **0.888 → 0.891 (+0.003)** — essentially flat, both near 0.89 on unseen years. Coarse classes
  look alike year to year, so a single year already generalises; the payoff from multiple years shows
  up on the **finer, year-sensitive** splits. (This also reassures us the base map itself is
  temporally stable.)

**› Side note — the concepts in one line each (say these if asked):**
- **Embedding** — the 64-number fingerprint Alpha Earth gives each 10 m pixel, summarising a year of
  satellite imagery. We classify these, never raw images.
- **Annual mosaic** — one embedding image per calendar year; picking a year picks which one we sample.
- **Drift (temporal drift)** — accuracy lost when a model is applied to a different year than it
  trained on.
- **Decision boundary** — the line the linear classifier draws between classes in the 64-number
  space; drift happens when next year's points sit slightly on the wrong side of last year's line.
- **Generalise** — perform well on data the model did *not* train on (a different year, or a
  different place).
- **Held-out year** — a year deliberately kept out of training and used only for testing, so the
  score is honest.
- **Time-augmentation** — feeding the *same* polygons at several years as extra training rows, so the
  model learns the class despite year-to-year wobble.

## Slide 4 — Testing on the sites: what we found

The results table, with two interpretive bullets. All from `week7/site_tests.py` (live GEE):

| Test | Result | Read it as |
|------|--------|-----------|
| Tea vs non-tea | **0.957** held-out accuracy | plantations are spectrally/texturally distinct → easy |
| Acacia vs non-acacia | **0.745** on unseen years (multi-year) | a species distinction → genuinely hard, but robust after multi-year |
| Mining detection | **0.859** accuracy, **0.854** recall on real mines | the positive control: it *does* detect actual mines |
| Mining false-positive rate | **0.139** on non-mining ground truth | ~14% of clean non-mining is wrongly flagged |
| Asola Bhatti (reclaimed mines) | **17.1%** of the area flagged mining | yes, we get false positives there — as predicted |

- **The takeaway on mining:** the model isn't broken — an active coalfield (Jharia) reads **71%**
  mining and it catches 85% of held-out mines — but on reclaimed, mine-like ground it *does* produce
  false positives (reclaimed Asola reads **17%**), exactly the concern raised for Asola. The
  active-vs-reclaimed contrast on the same detector is the clean way to show that.
- **Honest caveat (say this if pressed):** the mining number is from a **binary mining-vs-not
  detector built for measurement** (positives = real mines from across India, negatives =
  barren/built-up/greenery), not the exact barren→mining split wired in the live tree, and Asola has
  **no ground truth** — so 17.1% is a *false-positive-tendency indicator*, not a production metric.

**› Why we get each number, and how it compares to before.** These aren't arbitrary — each follows
from *how separable the classes are in the embedding* and, where we have one, an earlier measurement.

| Test | This week | Earlier | Why this number |
|------|-----------|---------|-----------------|
| Tea vs non-tea | **0.957** | 0.934 (week 5, AE held-out) | Tea gardens are planted in dense, uniform rows with a distinct canopy — very unlike surrounding forest/crop — so Alpha Earth separates them easily. It was already strong in week 5; this week confirms it (a touch higher, just a different random split). |
| Acacia vs non-acacia | **0.745** (multi-year) | new this week; single-year **0.635** | This is a *species* distinction *inside* tree cover: two tree canopies look almost the same from 10 m, so it sits near the information limit of the embedding — hence modest. There's no older number (acacia is new), so the honest "before" is the single-year 0.635; the change is the **+0.11 multi-year gain**. |
| Mining detection | **0.859** accuracy, **0.854** recall | first proper measurement (week 3 mining was a qualitative ADD demo, never scored) | Mining scars are spectrally/texturally distinct from vegetation, so detection is fairly strong. **Recall 0.854** = of real mines, 85% are caught — the positive control proving the model genuinely finds mining. |
| Mining false-positive rate | **0.139** | — | Of genuinely non-mining ground (barren/built-up/greenery), 14% is wrongly called mining. Bare, disturbed, or built surfaces can resemble mine texture, which is where the errors come from. |
| Jharia (active coalfield) | **71.2%** flagged | positive-control site | Run the *same* detector over a known active coalfield: ~71% of the area reads mining. This is the control that proves the model genuinely finds mines — without it, a low Asola number could just mean "the model never says mining." |
| Asola Bhatti (reclaimed) | **17.1%** flagged | reclaimed site | Same detector over the reclaimed area. Since little active mining remains, most of that 17% is **false positive**. The contrast is the story: **71% at an active mine vs 17% at reclaimed Asola** — a 4× gap. It sits *above* the 14% clean false-positive rate, consistent with Asola's mine-scarred ground looking mine-like, but far below a real mine, so the model isn't just firing everywhere. |

**The one-line pattern:** the embedding separates **spectrally/texturally distinct** classes well
(tea, mine-vs-vegetation) and struggles on **subtle within-class** distinctions (tree species). That
single fact explains why tea is 0.96, acacia is 0.75, and mining detection is 0.86 with a real but
non-trivial false-positive tail.

## Slide 5 — Judging whether there is enough training data

**What was bad before.** The tool judged training data with **absolute numbers** — "N polygons," a
per-class count, and a spread score computed at a *fixed* 0.25° grid. Two problems with that:
1. **An absolute count can't tell you if it's enough.** "500 labelled points" is plenty over a single
   village but negligible over a whole district. The number never referenced the *size of the area
   you actually want to classify*, so you couldn't tell whether you had enough for *this* job.
2. **Spread told you evenness, not quantity.** The old spread score said how *evenly* the labels were
   scattered, but not how *much* of your target area they covered. Two datasets could have identical
   spread while one blankets the region and the other barely touches it.

**How we improved it — coverage.** We added **coverage = labelled area ÷ AOI area**, computed against
the *exact box you are about to classify*. Now the answer is a fraction of the real target: it
**rises** as the area shrinks and **falls** as it grows. Concretely, the tea polygons cover **0.59%**
of the Assam tea box but **~0%** of all-India — the same polygons, judged against the area in
question, exactly as sir asked ("percentage of pixels, contingent on the size of the area").

- **Spread (kept):** we still show the spatial evenness (a normalised Shannon entropy over a grid),
  because data clustered in one place skews a model (week-2's generalization finding). Sir's
  "skew/spread" is *spatial*, so we did **not** add a class-balance term.
- **Together** they answer, before running, both *"enough for this area?"* (coverage — how **much**)
  and *"well spread across it?"* (spread — how **evenly**). Quantity and distribution, side by side.

**› Why area coverage and not "occupied cells ÷ total cells" (the design choice to defend).** The
first idea was to count grid cells that contain a label over the total cells in the AOI. That
**breaks for small areas**: our stress-test strips (the IIT box is ~0.04°) are *smaller than one
0.25° grid cell*, so the ratio collapses to 100% and tells you nothing. **Area coverage** (union the
labelled polygons, clip to the AOI, divide the two areas in an equal-area projection) stays honest at
*any* scale — tiny for crown polygons over a big box, larger as the box shrinks. Same intent as the
plan, correct formula.

## Slide 6 — Validating a scheme before it runs

- **The setup:** a user can upload a saved scheme — the class hierarchy plus the ordered steps that
  built it. Until now it was **applied first and problems noticed afterwards**, so a broken file had
  already changed the live tree by the time you learned it was broken.
- **The fix (one flow, not two):** there's a single **Load a saved scheme** action. On upload the
  server **validates first and only applies if it's sound**; a broken file is **rejected with the
  exact reasons and nothing changes**. The user never has to run a separate "validate" step.
- **What it checks:** (a) the hierarchy is well formed (reuses the existing tree validator); (b)
  every recorded operation is one the tool knows — split/add/retrain/merge/apply/base_select — with
  its required fields (this op-log check didn't exist before); (c) each classifier the scheme refers
  to is present on disk (else a warning: it loads, but that split won't be live until retrained).
- **Verified:** a doctored file returns HTTP 400 with the error list and the live tree is unchanged;
  a sound file loads and re-classifies.

## Slide 7 — Choosing the data: years and Tessera

- **Years (#3 tie-in):** the inference-year picker now carries a note on how far a ground truth stays
  reliable across years, so the user knows what a chosen year buys.
- **Tessera (#6):** it remains the second feature source in Detailed mode. It has usable India
  coverage **only for 2024**, and the note now states plainly that **other years can be requested**.

## Slide 8 — Thank you

Closing. If asked "what's next": run the acacia/tea/mining demos live on the map and the Jalpaiguri
base-scheme operations demo; the mining **segmentation** model is the larger future step; and the
biomass/GEDI pipeline is to be understood and written up separately.

---

## Deep-dives — likely questions from sir (answered in full)

### Q1 — Are our models actually trained on multiple years now?

Yes, on the **split path**, and it's demonstrated. `refine.train(parent, years=[...])` pools several
years into one classifier, and `temporal_eval.py` trains on a set of years and tests on years the
model never saw. On acacia this lifts unseen-year accuracy from 0.635 to 0.745. The **base model** is
still single-year (2024) because its training CSVs have no year dimension and Tessera is 2024-only —
but the base classes are already temporally stable (+0.003 from multi-year), so there's little to
gain there. So: multi-year where it matters (fine splits), single-year where it doesn't (the coarse
base).

### Q2 — Did we get false positives on the mining test, and how many?

Yes. At **Asola Bhatti** — where the old mines were reclaimed into built-up and scrub — the detector
flags **17.1% of the area as mining**, which is largely false positive since there's little active
mining left. The clean way to see it's false positive and not the model working: run the **same
detector over a known active coalfield (Jharia)**, which reads **71.2%** mining. So it's **71% at a
real mine vs 17% at reclaimed Asola** — the model genuinely detects mining (also 85.4% recall on
held-out mines, 13.9% false-positive rate on clean non-mining ground), and Asola's 17% is a real
false-positive *tendency on mine-like reclaimed ground*, well below a working mine. Caveat: it's a
binary mining-vs-not detector built for measurement, and neither AOI has pixel ground truth, so treat
the percentages as comparable indicators, not exact production metrics.

### Q3 — Why is acacia (0.745) so much worse than tea (0.957)?

Different kinds of distinction. Tea is a **plantation** — a distinct planting texture and canopy that
Alpha Earth's embedding separates cleanly from other greenery. Acacia vs non-acacia is a **species
distinction *within* tree cover**, where two trees can look almost identical from space; that's near
the limit of what a 64-number annual embedding carries. So the *absolute* acacia number is modest by
nature. The reproducible, defensible story there is the **multi-year gain (+11 points)**, which is
exactly the kind of subtle, year-sensitive class where robustness matters most.

### Q4 — How do you avoid leakage when the same polygon appears in several years?

We split by **polygon group**, not by pixel. Each polygon carries a stable id
(`{class}:{index}`) that's the same across years, so `GroupShuffleSplit` puts *all* of a polygon's
rows — every year — entirely in train or entirely in test. A polygon never straddles the split, so
the extra years add temporal variety to the training set without letting the model peek at a test
polygon. In the multi-year check we additionally hold out whole *eval years* the model never trained
on, so it's a double (spatial + temporal) hold-out.

### Q5 — Why measure coverage as *area*, and why not the simpler "% of grid cells with a label"?

Because the plan's first idea — occupied grid cells ÷ total cells in the AOI — **breaks for small
areas**. Our stress-test strips (the IIT box is ~0.04°) are *smaller than one 0.25° grid cell*, so
that ratio collapses to 100% and tells you nothing. **Area coverage** (union the labelled polygons,
clip to the AOI, divide areas in an equal-area projection) stays honest at any scale — it's tiny for
crown polygons over a big box (that's the point: it says "you've labelled very little of this area")
and rises as the area shrinks. Same spirit as sir's ask ("percentage of pixels, contingent on the
size of the area"), correct formula.

### Q6 — Didn't we already validate uploaded schemes? What's new?

We had two pieces: a tree-shape validator and a "missing classifier" report. But they ran **as part
of applying** — the tree was saved and the op-log replaced *before* the missing-classifier report,
so a broken file had already mutated live state; and the **op-log was swallowed unchecked**. What's
new is a **non-mutating pre-flight** (`POST /api/hierarchy/validate`) that runs the checks *before*
anything changes, plus the op-log well-formedness check that didn't exist. Import now runs it first
and refuses a bad file with a 400. So: not new validation from scratch — the missing piece was
"check *before* you execute," which is exactly what sir asked.

### Q7 — Is the model showing WorldCover labels directly, and would that help?

No, and no. By default the model outputs the 4 IndiaSAT base classes; WorldCover is mapped down to
those and used only as training signal + prior. Showing WorldCover's 7 classes directly is a one-click
option (the WorldCover base), but it wouldn't raise accuracy — weak labels and thin India support make
it a harder, noisier task, more *detail* not more *accuracy*. The useful part of WorldCover (its India
class prior) is already baked into the default model.

### Q8 — How many years should a split be trained on, and which ones?

We used three spread across the range (2019, 2021, 2023) and tested on the gaps (2020, 2024). The
principle: **spread the train years across the interval** so the model sees the range of conditions,
and keep some years fully held out to prove robustness. More years is generally safer but costs more
Earth Engine sampling; three well-spread years already closed most of the single-year gap on acacia.

### Q9 — Are these numbers reproducible?

Yes. `week7/site_tests.py` regenerates the tea/mining/Asola numbers and `src/temporal_eval.py` the
multi-year ones, both against live Earth Engine; the raw run logs are in `week7/`. They'll wobble a
little run-to-run (random polygon hold-out, a modest pixels-per-polygon for speed), but the ordering
and the size of the effects are stable.

### Q10 — What's deliberately left for the live session?

The **Jalpaiguri** demo — start from a base scheme (IndiaSAT or WorldCover) and show split/add
operations growing new classes — is left for you to run live, since it's an interactive walkthrough
rather than a number. The on-map click-through of the acacia/tea/mining sites is likewise a live
demonstration; the sites, the labelled data, and the trained models are all staged for it.