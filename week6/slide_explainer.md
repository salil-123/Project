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
  - **WorldCover (effective)**: tree, shrubland, grassland, cropland, built-up, bare, water.
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
  labels they produced. This mirrors the **pixel-level error-correction layers** in the
  regionally-accurate LULC work (the Chahat / IIT-Delhi line of work).
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
