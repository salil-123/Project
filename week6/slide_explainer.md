# Week 6 — slide-by-slide explainer

The "understand every word" companion to `slides_week6.tex` (deck title: *Extending the LULC
classifier: user control, merging, and sharing*). `demo.md` is the click-through; this file explains
the idea behind each point so you can field follow-ups. Read **Foundations** once, then go slide by
slide. Where the live app has since moved past what a slide says, a **› Now** note flags it.

---

## Foundations: things to know cold

1. **LULC** = Land Use / Land Cover — labelling each patch of ground (greenery, water, built-up,
   barren, …). That's the product.
2. **Alpha Earth (AE)** = Google's satellite **embedding**: for every 10 m pixel, a 64-number
   vector summarising a year of imagery. We classify these vectors, never raw bands. "Google did
   the feature extraction; we just classify."
3. **Tessera** = a second embedding (128-d), only usable for **2024 over India**, and costly to
   download. Used only in the optional "Detailed" mode.
4. **The classifier** = `StandardScaler → LinearSVC` (scale the 64 numbers, then draw straight
   class boundaries). Deliberately simple. Saved as a small `.joblib`.
5. **Why linear matters:** a linear model is just arithmetic on the 64 numbers, so Earth Engine can
   replay it on the whole image server-side and hand back a finished 10 m map as tiles — nothing
   downloaded. The phrase: *"the linear model is replayed as band-math in Earth Engine."*
6. **The hierarchy** = classes live in a tree (`hierarchy.json`). Root → 4 base classes; any node
   can be split or have classes added. Each node with children owns a small classifier that only
   decides among *its* children; inference walks root→leaf.
7. **The model zoo** = a git-backed catalogue of **cards** (`data/catalogue/`). A **Model Card** is
   a classifier at one node; a **Dataset Card** is either labelled training data or a feature
   source. Publishing = committing cards (and small model files) to a shared repo.
8. **What week 6 is about:** turning the tool from "a classifier you use" into "a scheme you **own
   and share**" — choose your base, choose your year, merge across models, save/reload, and publish
   with provenance.

---

## Slide 1 — Where we are, and what was advised

Two columns: what's done vs. what sir asked for.

- **Done so far.** (a) The 4-class base map at 10 m + the *living hierarchy* (split/add a class,
  give a few example polygons, retrain that one node on the fly). (b) The running git-backed zoo:
  browse cards, apply a model to the map, publish to a shared repo, each card carrying metrics.
- **What was advised.** Four threads, which the rest of the deck answers one by one:
  - let users **own and share** their scheme — choose base classes, choose inference data,
    save/reload;
  - add a **merge** operation (relabel classes across models);
  - **recommend** where a model applies;
  - on **publish**, store the model, record the contributor, link the data.

Why it matters: it frames everything after as *responses to specific asks*, not features invented in
a vacuum.

## Slide 2 — Choosing the starting base classes

- **The point:** the user isn't locked to one starting vocabulary. On arrival they pick a scheme.
  - **IndiaSAT**: greenery / water / built-up / barren — the calibrated default.
  - **WorldCover base** (7 classes): tree, shrubland, grassland, cropland, built-up, bare, water.
- **How the WorldCover base is built:** train a LinearSVC on Alpha Earth points *labelled by ESA
  WorldCover*, keeping only the classes with real India support; the very rare ones (snow, wetland,
  moss, mangrove — a handful of points) are dropped for lack of data.
- **Honesty:** WorldCover labels are **weak** (an automated product), so this base **trails**
  IndiaSAT. It's an alternate *starting point*, not a more accurate one, and is presented that way.
- **Why it's clean:** both bases are **cards in the zoo**, so "switch base" is the same kind of
  action as "apply a model" — selecting a base is first-class, not a special case.
- **Caveat:** switching base is deliberately **destructive** — it reseeds the tree to the new
  classes and clears your splits/merges (old tree backed up to `hierarchy.prev.json`).
- **› Now:** this is the very first thing the app does — a focused *"Choose your base classes"*
  modal appears on a fresh visit (reads `GET /api/base`), so the choice is made before anything
  else. Picking the current scheme just proceeds; a different one reseeds after a confirm.

## Slide 3 — Choosing the inference data

- **The point:** the *same* trained model can classify a *different year*. Alpha Earth's embeddings
  are temporally consistent, so we reuse the model and just sample the features at the chosen year —
  **no retraining**.
- **Coverage:** Realistic mode offers any year **2017–2024** (Alpha Earth). Detailed mode is pinned
  to **2024** (the only year Tessera covers over India).
- **Reproducibility:** the chosen year is recorded with the result.
- **Evidence it's real:** the same area in 2022 vs 2024 gives a genuinely different class mix (not a
  cosmetic toggle).
- **› Now:** the year control was moved **into the zoo** — it lives on the Alpha Earth
  inference-dataset card. A client-side `inferYear` drives Run classification; the map status line
  no longer prints the year.

## Slide 4 — Merging classes across models

- **The core idea:** a merge is **relabelling**. Take a class produced at one node and a class
  produced at another — possibly from *different models* — and declare them one new class.
- **It's a correction layer, not training.** It runs *after* the per-node classifiers, on the
  labels they produced.
- **Worked example:** relabel `tea` (from the greenery split) together with `mining` (from the
  barren split) into one `extractive` class — the map and the per-class counts reflect it at once.
- **Reproducible + reversible:** merges are stored as **rules** (`merge_rules.json`), so a result
  replays and a merge can be removed (the original classes come back).
- **› Now:** sir's follow-up — *a merge should also produce a local model.* It now mints a local
  **Model Card** (`mc_merge_<target>_v1`, topology `merge_relabel`) that `produces` the merged
  class and records its sources; it carries no `.joblib` because a relabel isn't a trained model.
  The merge also shows **on the hierarchy tree** (source leaves tagged `→ target`; the target as a
  virtual node), and you pick sources by ticking leaves in the tree.

## Slide 5 — Saving and reloading a scheme

- **The need:** people combine models in different ways to reach *their* classifier; that work
  shouldn't be lost.
- **The mechanism:** download the hierarchy **plus the ordered steps that built it** as one JSON
  file, and load it back later.
- **No accounts, no sessions:** the **JSON file is the save**. Keeps the tool light while letting
  anyone resume exactly where they left off (or share the file).
- **On reload:** the tree is validated, each split is **rebound** to its trained model on disk, and
  any split whose model is missing is **reported** so the user knows to retrain it (its structure is
  still restored).

## Slide 6 — Recording the order of operations

- **Why structure isn't enough:** the final tree shape doesn't say *how* you got there, and order
  matters — a later split or merge depends on what came before.
- **The fix:** every tree-changing action — split, add, retrain, apply, merge, base switch — is
  appended to an **ordered operation log** (`op_log.json`).
- **Payoff:** the log travels *inside* the saved scheme, so a shared or restored hierarchy
  reproduces the same output, and the exact workflow that produced a unique classifier is preserved.

## Slide 7 — Recommending where a model applies

- **The feature:** each Model Card suggests where it fits — *"apply after `<class>`"* — derived from
  the model's node in the hierarchy plus any WorldCover mapping its classes carry (e.g. "apply after
  Greenery (WorldCover: Tree cover)").
- **Area-aware:** the suggestion also notes whether the model is valid for the region currently on
  screen (a bbox-overlap check).
- **Why it stays correct:** it's **computed from existing card metadata**, not hand-curated, so it
  keeps making sense as the zoo grows.

## Slide 8 — Measuring data spread at a chosen scale

- **The problem:** training data clustered in one area **skews** a model (this ties back to week 2's
  generalization-gap finding — *spread*, not sheer volume, is what generalizes).
- **The measure:** a **spatial-diversity** score = Shannon entropy of where the labelled polygons
  fall, binned to a grid and normalized to [0,1]. ~1 = well spread, ~0 = all clustered.
- **The new control:** the **grid cell** the spread is measured on is now **user-adjustable**, so
  you can read the diversity at the scale that matters for a given dataset.
- **Behaviour:** a finer grid reveals more occupied cells and usually a higher spread; the value
  updates live on the dataset card.

## Slide 9 — Publishing: storing the model

- **What gets stored:** on publish, the trained **model file** is committed into the shared zoo
  repo. The models are tiny, so a published model is **usable** by anyone who pulls it, not just
  described by metadata.
- **What stays out:** the repo holds only **cards + these small model files**; large training tables
  and tiles are kept out (a `.gitignore` in the zoo enforces this).
- **Who shared it:** publishing records the **contributor** (a GitHub handle or email) on the card.
- **› Now:** the contributor is captured via the card's **Annotate** field (remembered locally) and
  sent silently — the publish-time popup was removed.

## Slide 10 — Publishing: the data and the contract

- **The provenance ask:** for each training dataset, capture a **public link** to where the data
  came from, and show it on the card.
- **The contract:** a **private upload with no link is never shared** — it stays local and is used
  only to train the model. *The labelled data remains the user's own.* We carry the metadata and a
  link if it's public; if not, we train on it and keep nothing.
- **Why both:** the published catalogue stays rich in provenance *and* honours the agreement that
  the data belongs to whoever uploaded it.
- **› Now:** the public link is set on the **dataset card's detail pane** (one place per dataset),
  not asked at publish time — so publishing many models doesn't fire a prompt per dataset.

## Slide 11 — Thank you

Closing slide. If asked "what's next": the deferred thought experiment (#10) — *can split + merge
express any decision tree?* — and standalone artifacts for merge cards (today a merge card points at
its source models rather than baking its own binary).

---

## Deep-dives (review questions, answered in full)

### Q1 — Why is the WorldCover base *weaker* than IndiaSAT?

It comes down to **what each one was trained on**, i.e. the quality of the *labels*, not the model.

- **IndiaSAT base** learns from **expert ground-truth polygons** — the IndiaSAT, FarmForest and
  GT_BINARY assets, which are human-verified for India. Strong, trusted labels.
- **WorldCover base** learns from **ESA WorldCover**, which is itself an *automated, global*
  land-cover product (a machine classifier run worldwide). So we're training a model on **another
  model's guesses**, not on verified truth. That's what "weak labels" means: the label noise of the
  automated product flows into ours. We even say so on its card — *"weak ESA WorldCover labels."*
- Two follow-on costs: (a) WorldCover's classes are global, and several barely occur over India
  (snow, wetland, moss, mangrove — a handful of points), so we **drop** them for lack of support,
  keeping only the 7 well-supported ones; (b) global label conventions don't always match India's
  on-the-ground reality as cleanly as the expert assets do.
- **Bottom line:** it's offered as an *alternate starting vocabulary* (7 classes vs 4), not a better
  one. "Weaker" = trained on noisier labels and a thinner India signal, so it trails IndiaSAT in
  accuracy. (This is also why the slide drops the word "effective" next to it — see the naming
  note at the end.)

### Q2 — What does the saved scheme JSON contain, and how is it structured?

The "download your scheme" file (`GET /api/hierarchy/export`) is **one JSON object with three
top-level keys**:

```jsonc
{
  "hierarchy":   { ... the class tree ... },     // the SHAPE
  "op_log":      [ ... ordered operations ... ],  // the RECIPE (how it was built)
  "classifier_refs": { ... per-node pointers ...} // where each trained model lives
}
```

- **`hierarchy`** — a flat dict keyed by canonical class id. Each node looks like:
  ```jsonc
  "greenery": {
    "class": "greenery",   // canonical id (== the key)
    "name":  "Greenery",   // display label
    "parent": "root",      // null only for the root
    "color": "#2e8b2e",    // display colour
    "classifier": "greenery", // the model that resolves its children (null if a leaf)
    "children": ["tea", "non_tea"],
    "source": null         // where this class's training samples come from (examples/worldcover/residual)
  }
  ```
  Root is `"root"` with `parent: null`. The whole tree is just these nodes; "where to add" is
  inserting a key.
- **`op_log`** — the ordered list of every tree-changing step (see Q3): each entry is
  `{seq, ts, op, args, result}`, e.g. `{"seq": 6, "op": "merge", "args": {"target": "extractive",
  "sources": ["tea","mining"]}}`.
- **`classifier_refs`** — for each node that carries a trained classifier, a pointer to its artifact
  and zoo card: `{"greenery": {"artifact": "data/refine/greenery.joblib", "card": "mc_greenery_v1"}}`.
  The file stays **light** — it references the trained models, it doesn't embed the binaries.

On **import**, the tree is validated and installed, classifiers are **rebound** to whatever
artifacts are present on disk, and any split whose model is missing is reported so you can retrain
it. Note: **merges live in their own file** (`merge_rules.json`) on the server, but they're captured
in the `op_log` of the export, so they travel with the scheme.

### Q3 — What's the "log" for, why not just the JSON, and was it even asked?

First, the honest answer to "was it asked": **yes** — instruction **#11** asks for exactly this:
*"the sequence … of operations … the workflow/ordering in which we need to apply … we need to store
that so we can get their unique output … and that sequence needs to be persistent."* So persisting
the order was a direct requirement, not invented scope.

Second, "why not just let the user have one JSON file?" — **they do.** The op-log isn't a separate
file the user juggles; it's **one section inside the single exported JSON** (the `op_log` key from
Q2). On the server it's kept as its own append-only file (`op_log.json`) only so every mutating
endpoint can cheaply add one line; at export time it's folded into the same file the user downloads.

Third, "why is the order needed when the tree already describes the result?" Because the **tree is
the shape, the log is the recipe**, and some things aren't reconstructable from shape alone:

- **Merges are not in the tree.** A merge is a post-inference relabel layer (tea+mining→extractive);
  the tree still shows tea and non_tea. Only the log/rules record that relabel.
- **Order changes the output.** Which base you picked, an `apply` of a zoo model, a split, then a
  merge over its leaves — run in a different order and you can get a different final map. To
  reproduce a user's *unique* output you replay the steps **in order**.
- **Provenance / audit.** It's a readable history of how a classifier was built — valuable when
  sharing a scheme so a reviewer can see (and trust) how it was reached.

Honest scope note: today's *restore* rebuilds state from the tree + classifier rebind; it doesn't
yet *replay* the log step-by-step. The log's present job is (a) satisfying #11's "sequence is
persistent", (b) carrying the merge/apply history the tree can't, and (c) being the substrate for
exact replay later. It's a few KB of plain data, so the cost is negligible and the reproducibility
guarantee is real.

### Q4 — "Recommend where a model applies": metadata-driven, not hand-curated — what does that mean?

Your reading is right: **it's plain constraint-checking over the cards' own metadata — no model is
run, no probabilistic "will this work here" score is computed.** Concretely, `recommend_placement`
does three cheap lookups:

1. **Attach point ("apply after X").** A per-node split, by construction, only runs on pixels the
   base map already called `X` (its parent node). So the recommendation *reads the card's `node`
   field* and says "apply after that node." It's not inferred by analysis — it's literally where the
   model attaches in the hierarchy. (Base models say "the starting point"; merge cards say
   "cross-model relabel, applied after inference.")
2. **Standard-class hint (optional).** If *any* card in the zoo has mapped that class to a WorldCover
   code (via the Annotate → std_mapping crosswalk), we name it: "apply after Greenery
   (WorldCover: Tree cover)." Pure lookup over existing card metadata.
3. **Area awareness.** A plain **rectangle-overlap** test between the card's validity `extent` (a
   bbox) and the map's current view, labelling "outside current view" when they don't overlap. No
   distance model, no "is the labelled region close" geometry beyond bbox overlap.

So "not hand-curated" means: **nobody types "this model goes after greenery" by hand** — it's
derived from each card's own fields (`node`, `std_mapping`, `extent`), so it stays correct
automatically as the zoo grows. The trade-off is honesty: it's a *suggestion from metadata*, not a
guarantee the model will perform well on your pixels.

### Naming note (why we dropped "effective")

We stopped writing *"WorldCover (effective)"* next to the scheme. The bracketed "effective" reads as
if WorldCover is *the effective one of the two* — the opposite of the truth (IndiaSAT is the
stronger base). It now reads **"WorldCover (7 classes)"**, parallel to **"IndiaSAT (4 classes)"** —
informative, and no implied ranking. ("Effective subset" still appears in internal code comments to
mean *the well-supported 7 classes*, but never in viewer-facing labels.)

---

## Likely follow-up questions (and crisp answers)

- **"Is a merge a model?"** Conceptually it's a *relabel layer*, so it has no trained weights — but
  it's still something the user built, so it earns a local card (no `.joblib`) that records what it
  produces and from which sources. In Earth Engine it's just a `remap` of the label image.
- **"Why down-weight Tessera / why is Detailed not the default?"** A naive balanced AE+Tessera
  soft-vote ignores the greenery prior and collapses to ~0.43 on random India; Realistic (AE +
  WorldCover prior) is ~0.83. Tessera is also 2024-only and costly to fetch.
- **"Does switching base lose my work?"** Yes, by design — it reseeds to the new classes and clears
  splits/merges (old tree saved to `hierarchy.prev.json`). That's why the base choice is the first
  step, before you've built anything.
- **"How is a year change not retraining?"** The model is linear on temporally-consistent AE
  embeddings, so the same weights apply; we only sample the chosen year's features.

---

## Q5 — If the labelled data is sparse, is a user-chosen grid cell (1° vs 0.25°) even useful?

Fair pushback — and the honest answer is: the slider isn't there to squeeze a precise number out of
sparse data, it's there because **"spread" only means something *at a scale*, and the useful scale
depends on the question you're asking.** The spread score bins each polygon's centroid into
`cell`-degree squares and measures how evenly they fall (normalized Shannon entropy). Change the
cell and you change what counts as "the same place."

- **The same sparse data reads differently at different cells.** At a **coarse** grid (1° ≈ 111 km),
  polygons that are genuinely tens of km apart land in the *same* cell, so they look *clustered*
  (low diversity, few occupied cells). At a **finer** grid (0.25° ≈ 28 km) those same polygons split
  into *different* cells and look *spread*. Nothing about the data changed — only the ruler.
- **Which ruler is "right" depends on intent:**
  - *"Does this model see enough of India to generalize?"* → read it **coarse** (1°). You want
    polygons scattered across the country, not clumped in one state.
  - *"Within this district, is my data varied or all from one village?"* → read it **fine**
    (0.1–0.25°). Micro-clustering that a 1° grid hides shows up here.
- **Sparsity is the reason the knob helps, not the reason it's pointless.** With few polygons a
  single fixed grid can flat-out mislead. The **occupied-cell count** is the real tell: *30 polygons
  in 2 cells* vs *30 in 20 cells* is a huge difference in generalization risk — and you only see it
  by moving the cell. Sliding it tells you whether your sparse data is **concentrated** (all one
  area — risky) or **distributed** (about as good as sparse data gets).
- **So how much does 1° vs 0.25° actually change?** It can *flip the verdict.* A dataset spread
  across, say, Pune district sits in **one** cell at 1° (diversity ≈ 0, "clustered") but several
  cells at 0.25° ("spread"). That flip is exactly the call a user makes — "do I trust this to
  generalize, or go collect data elsewhere?" — so the difference is decision-level, not cosmetic.

**The honest caveats** (say these if pressed): it's a **diagnostic slider, not a precise metric**.
At the extremes it saturates — a grid finer than your polygon spacing puts every polygon in its own
cell (diversity → 1, meaningless), and a grid coarser than the whole dataset collapses to one cell
(diversity → 0). And with very few polygons the absolute entropy is noisy regardless. Its value is
letting the user find the scale where the spread question is meaningful *for their use*, and exposing
whether sparse data is concentrated or distributed — which, per week 2's finding that **spread (not
volume) is what generalizes**, is the thing that actually predicts whether the model will hold up
elsewhere.
