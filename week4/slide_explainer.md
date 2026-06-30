# Slide-by-slide explainer (so you actually understand it, not just recite it)

This is the "understand every word" companion to the deck. `presentation_guide.md` is the
short script; this file explains the concepts behind each slide so you can answer follow-ups.
Read the "Foundations" section once, then the per-slide sections.

---

## Foundations: 8 things to know cold before you walk in

1. **LULC** = Land Use / Land Cover. Classifying each patch of ground as greenery, water,
   built-up, barren, etc. That's the whole product.
2. **Alpha Earth (AE)** = Google's satellite **embedding**. For every 10 m pixel on Earth,
   it gives a vector of 64 numbers that summarizes what that pixel looks like over a year.
   We never touch raw satellite bands; we work on these 64-number vectors. Think of it as
   "Google already did the hard feature-extraction; we just classify the features."
3. **10 m** = the pixel size. One pixel covers 10 m x 10 m on the ground. That's the
   resolution of our map.
4. **The classifier** = a simple linear model, `StandardScaler -> LinearSVC`. `StandardScaler`
   normalizes the 64 numbers (so none dominates by scale); `LinearSVC` (linear support vector
   classifier) draws straight boundaries between classes in that 64-D space. The `->` means
   "scale first, then classify." It's deliberately simple. Once trained, the model is saved to
   disk as a **`.joblib`** file (joblib is the Python library for serializing scikit-learn
   models); inference just loads that file instead of retraining.
5. **Why linear matters (the trick):** a linear model can be rewritten as plain arithmetic on
   the 64 bands ("band-math"). Earth Engine (Google's cloud) can run that arithmetic on the
   whole image server-side and hand back one finished picture. That's how we get a 10 m map
   instantly without downloading anything. Remember this phrase: **"the linear model is
   replayed as band-math in Earth Engine."**
6. **The hierarchy (from weeks 2-3)** = the classes live in a tree. Root ("All land") splits
   into the 4 base classes; each of those can be split further (greenery -> crops/trees/shrubs).
   The tree is **editable at every level**: you can split a class, add a class under a node, or
   even add a new base class under root (that last one retrains the base map). The 4 classes are
   the starting point, not a fixed ceiling. The tree is stored in one file, `hierarchy.json`.
7. **Per-node classifier** = each node that has children owns its own little model that only
   decides among its own children. The greenery model only chooses crops vs trees vs shrubs;
   it never worries about water. Inference walks the tree root to leaf.
8. **What this week is:** a **design week**. We did not build new features; we designed the
   **schema** (the data structure) for turning the single tool into a *library* of models and
   datasets. The deliverable is the design itself, presented for sign-off.

The two new objects the whole talk is about:
- **Model Card** = a small JSON file describing one trained classifier (what it predicts,
  what it learned from, where it works, how good it is).
- **Dataset Card** = a small JSON file describing one labelled data source (what it labels,
  where/when it's valid, who made it, how trustworthy).
The name "card" comes from "**model cards**", a standard ML idea: a short fact-sheet that
travels with a model. Sir explicitly asked for this (instruction #9).

---

## Slide 1 — Title
**Shown:** "A schema for the LULC model & dataset zoo", your name.
**Meaning:** "zoo" is just the informal word for a collection of models people can browse and
reuse (like a "model zoo" in ML). The talk is about the *schema*, the agreed structure for
the models and datasets in that collection.
**Say in one breath:** "This week was a design week; I worked out the structure for turning
our one tool into a reusable library of models and datasets."

---

## Slide 2 — Where we are, and the direction
**Shown:** two columns. Left "Done so far", right "The direction (what was advised)".

**Left column, plain meaning:**
- "4-class base map from Alpha Earth at 10 m" = recap of foundations 1-5. We already classify
  any area into greenery/water/built-up/barren at 10 m.
- "living hierarchy: split / add a class at any level, retrain on the fly" = recap of the
  week-3 work. The user can carve an existing class into sub-classes (**split**) or introduce
  a new class (**add**), give a few example polygons, and the model retrains immediately and
  the map updates. "with metrics" = it also reports how accurate that retrain was.

**Right column, plain meaning (this is sir's ask):**
- "model zoo + dataset catalogue" = don't keep just one model; keep many, each good for some
  place, in a browsable collection, plus a matching collection of datasets.
- "Each model tagged with where it's valid, what it emits, what it trained on, how classes
  were annotated" = the four things a Model Card must record. "emits" = which classes it
  outputs. "annotated" = how the training polygons were labelled.
- "model cards" = the name for those tags (foundations).
- "browse, pick one for their area, keep refining" = the user journey: find a suitable model,
  then improve it.

**The point of the slide:** frame the gap. We have a good tool; sir wants it to become a
shareable library; the missing piece is the *metadata structure*, which is this week's work.

---

## Slide 3 — The structure: two record types (+ a spine)
**Shown:** four bullets.
**Meaning of each:**
- **Dataset Card**: "a labelled source." Three possible kinds: **polygons** (shapes a user
  drew/uploaded), an **EE asset** (a slice of an existing Earth Engine dataset, e.g. the
  cropland class of WorldCover), or a **pixel table** (a CSV of already-sampled rows). Plus
  metadata: a description, its extent (where/when valid), provenance (who made it, evidence),
  and a quality score.
- **Model Card**: "a classifier at one node." It records the classes it produces, the datasets
  it trained on, where it's valid, its metrics, and how it deploys.
- **Canonical taxonomy**: "the 4 base classes the cards hang off." This is the **spine**: the
  fixed reference tree everything attaches to. ("Canonical" = the official, agreed version.)
- **Catalogue**: "a flat JSON registry of cards plus an index." A folder of JSON files (one
  per card) plus a small lookup table so queries are fast. "flat" = no database, just files.

**The point:** the entire design is just *two kinds of JSON record* + a spine + a folder to
hold them. Keep it simple is the message.

---

## Slide 4 — The class tree the cards hang off (DIAGRAM)
**Shown:** the hierarchy. "All land" at top with two filled chips on it: a blue **LinearSVC**
(model card) and a teal **AlphaEarth & WorldCover** (data card). The 4 base classes below.
Greenery and Barren each have two empty dashed chips: **model card** and **data card**.
Greenery splits to Crops/Trees/Shrubs; Barren splits to Barren*/Mining.

**Meaning element by element:**
- **The two chips on a node = "this node has a model, and here's the data it used."** Blue is
  always the model card; teal is always the data card.
- **Filled on All land** = the base map's model is already chosen and trained: a LinearSVC,
  trained on Alpha Earth pixels plus WorldCover. That pair is "set".
- **Empty dashed on Greenery / Barren** = these are *slots*. They show *where* a user attaches
  or trains a model and supplies its data. (In our actual demo these are filled, but on this
  slide we draw them empty to show the affordance, i.e. where the option lives.)
- **Water / Built-up have no chips** = nobody has refined them, so no model sits there yet.
- **Barren\*** = the asterisk means the "residual": when you add Mining under Barren, the
  leftover barren-that-is-still-barren becomes "Barren\*". (Explained more on slide 13.)
- **Arrows** = parent-to-child structure of the tree.

**The point:** make concrete *where* models and datasets attach. Every place a model can live
is a place that carries a model card + a data card.

**If asked "can the model be something other than LinearSVC?":** "Yes, within limits. Linear
models and Earth-Engine-native ones like random forest can run server-side for the fast 10 m
map; arbitrary models would lose that fast path. But on Alpha Earth embeddings the data is the
bigger lever, so linear is the sensible default."

---

## Slide 5 — Our own taxonomy, growable at any level
**Shown:** three bullets + a small table.
**Meaning:**
- "the tree grows at **any** level" = you can split a class, add a class under a node, or even
  **add a new base class** under root. Adding a base class retrains the base map (a heavier
  operation); deeper adds/splits train just that one node. The 4 base classes are the starting
  point, not a fixed ceiling.
- "New classes usually map **into** our taxonomy where they fit" = the common, recommended case
  is to attach a new class under an existing one (a seasonal/perennial water-body under water),
  because that keeps everyone's models comparable. But it's a judgement call, not a hard rule:
  if a class genuinely doesn't fit any base class, making it a new base class is allowed. This
  is the #13 question (does your class map into a standard class, or is it genuinely new?).
- "Standard taxonomies (WorldCover / USDA / IUCN) ... only at retraining time, as an optional
  cross-reference" = we do **not** adopt those external standards as our tree. A user *may*,
  when retraining, tag their class with "this corresponds to WorldCover cropland" for
  interoperability, but it's never required.

**The table (the crosswalk):** shows our class, which base class it sits under, and its
optional mapping to external standards.
- **WorldCover** = ESA's free global 10 m land-cover product; its classes have number codes
  (cropland = 40, tree cover = 10, bare/sparse = 60).
- **USDA** = the classic US land-use/land-cover class names (Cropland, Forest land, etc.).
- **IUCN** = a habitat/ecosystem classification (more ecology-flavoured); mentioned as another
  optional target.
- **The mining note:** WorldCover has no "mining" class. That's the whole reason a user adds
  it locally, and we just record that mining "rolls up to" barren for anyone comparing to a
  global product.

**The point:** our taxonomy stays small and stable; external standards are optional labels,
not the foundation.

---

## Slide 6 — Anatomy of the two cards (DIAGRAM)
**Shown:** Model Card (green) and Dataset Card (tan) drawn as cards listing their fields, with
an arrow "trains on" pointing from the Model Card to the Dataset Card.
**Meaning:** this is the overview before the raw JSON. Read the field groups aloud:
- Model Card holds: node/parent (where in the tree), produces (its classes), training.datasets
  (what it learned from), extent (where valid), metrics, deployment, lineage, about+zoo (the
  prose + publish flag).
- Dataset Card holds: kind+definition, classes, extent, embedding, provenance, quality,
  description, version.
- **The arrow direction is deliberate:** a *model* "trains on" a *dataset*, so it points model
  to dataset. That's the one relationship linking the two record types.

**The point:** a friendly map of the two cards before the detailed JSON, so the JSON slides
aren't a shock.

---

## Slide 7 — Dataset Card: two ways to define a dataset (JSON)
**Shown:** a real Dataset Card in JSON. Field by field:
- `"id": "ds_farmforest_crops_v1"` = unique name. Convention: `ds_` prefix, a name, `_v1`
  version. Bumped to `_v2` if the dataset is redefined.
- `"kind": "polygons"` = the headline type (polygons / ee_asset / embedding_table).
- `"description"` = one human sentence about what it is (sir's "describe the class" ask).
- `"classes": [ {"class":"crops","name":"Crops","count":110} ]` = what it labels and how many
  polygons (110 cropland shapes).
- `"definition"` = **the machine recipe to fetch the rows.** This is the important field.
  - For polygons: `"type":"polygons","path":"data/examples/crops.geojson"` (read shapes from
    this file).
  - The commented alternative: `"type":"ee_asset","asset":"ESA/WorldCover/v200","band":"Map",
    "code":20` = "take WorldCover, the Map band, pixels where the value is 40" (those are the
    two ways from the slide title: your polygons, or a slice of a standard asset).
- `"extent"` = where/when valid (explained on slide 9).
- `"provenance"` = who annotated it, how, and what evidence backs it. Here: a FarmForest
  expert, by hand, backed by drone imagery. This is sir's "how did you annotate / any
  evidence" ask.
- `"quality": {"n_polygons":110, "spatial_diversity":0.889}` = counts plus the diversity score
  (slide 12). 0.889 is a *real measured* number for this dataset.

**Footnote meaning:** "definition.type is the machine recipe; a loader dispatches on it like
the code already does on a node's source" = we already have code that branches on a data
"source" type (examples / worldcover / residual). The Dataset Card just makes that branching
a proper named record. **This is your strongest feasibility line:** it's formalizing existing
behaviour, not new capability.

---

## Slide 8 — Model Card: a classifier at one node (JSON)
**Shown:** a real Model Card (the greenery split). Field by field:
- `"id": "mc_greenery_split_v1"` = `mc_` prefix, name, version.
- `"node":"greenery", "parent_class":"greenery"` = it lives on the greenery node; its results
  attach under greenery in the spine.
- `"topology":"per_node_split"` = what *kind* of model it is. Three values:
  - `per_node_split` = the default, one small model that splits a node's children (foundation 7).
  - `base_pooled` = the root base map (the big 4-class model).
  - `flat_multiclass` = a single model over all leaf classes at once (an alternative we tested).
- `"produces": [ {"class":"crops","std_mapping":{"worldcover":40}}, {"class":"trees"},
  {"class":"shrubs"} ]` = the classes it outputs (its legend), each with an optional mapping to
  a standard. "map-out" = that optional external mapping.
- `"training"` = the lineage of *data*:
  - `"datasets":[...]` = the Dataset Card ids it trained on (here crops + trees + shrubs
    sources). This is the link drawn on slide 6.
  - `"algo":"StandardScaler->LinearSVC"` = the algorithm.
  - `"balancing":{"method":"class_weight_balanced","residual_cap":8000}` = how class imbalance
    was handled (slide 12). `class_weight_balanced` = tell the model to weight rare classes
    more; `residual_cap` = don't let the "leftover" class exceed 8000 rows.
- `"extent"` = where/when valid (slide 9).
- `"metrics":{"accuracy":0.963,"macro_f1":0.884,"eval":"polygon-holdout"}` = how good it is.
  - `accuracy` = fraction correct.
  - `macro_f1` = the average F1 across classes (F1 balances precision and recall; "macro"
    means each class counts equally, so rare classes aren't hidden).
  - `eval":"polygon-holdout"` = the honest test method: whole polygons are held out of
    training, so the model is tested on shapes it never saw (no cheating by memorizing a
    polygon's pixels).
- `"deployment":{"ee_asset":null,"tile_url":null,"expressible_as_bandmath":true}` = how it
  runs. `expressible_as_bandmath:true` = it's linear, so it can run server-side in Earth Engine
  (foundation 5). `ee_asset` / `tile_url` = filled in once it's pushed to Earth Engine for
  sharing (null for now).
- `"lineage":{"base_model":"mc_base_pooled_v1","derived_from":null}` = its family tree. It sits
  on top of the base map; it wasn't derived from another refinement.
- `"about":{"description","intended_use","limitations"}` = the human prose: what it's for and
  what it's bad at (here "shrubs weak"). (Named `about`, not `card`, since the whole file is
  already the model card.)

**The point:** everything you'd want to know about a model is one readable JSON file.

---

## Slide 9 — The typed extent object (validity) (JSON)
**Shown:** the `extent` object and three bullets. This is the "where/when is it valid" field
shared by both cards.
**Meaning:**
- `"spatial"` can take three shapes:
  - `{"type":"region","value":"India"}` = a named region from a controlled list (world, India,
    `AEZ-13`, `district:...`). **AEZ** = Agro-Ecological Zone, a standard way India is divided
    into farming-climate regions. So "valid over AEZ-13" is a human-readable validity area.
  - `{"type":"polygon","geojson":{...}}` = an exact drawn/uploaded boundary.
  - `{"type":"ee_asset","asset":"users/.../aez_13"}` = a boundary stored in Earth Engine.
- `"temporal"` = the time it's valid: a single year, or a range.

**Bullets:**
- "Is this area inside the model's extent?" = the core query the catalogue runs. For a named
  region, look up its geometry and test containment; for a polygon/asset, test the geometry
  directly. ("Containment" = is my area of interest inside this boundary.)
- "A dataset is valid somewhere; a model is valid somewhere; same object" = both card types
  reuse this one structure.
- "Space and time aren't the only axes ... bound to the embedding it was trained on" = a model
  is also only valid where the Alpha Earth embedding exists and matches. We left the object
  **open** (extensible) so we can add such an axis later, but we "start with the ones we can
  actually check." This is the answer to "have you thought beyond space and time?": yes, and
  the design doesn't lock us in.

**The point:** one flexible, future-proof way to say where and when something can be trusted.

---

## Slide 10 — Choosing the training data: the dataset panel
**Shown:** two columns: what the user picks from, and the preferences applied.
**Meaning:**
- **Left (what they pick from):**
  - their own polygons (drawn/uploaded),
  - a **curated standard library**: pre-written Dataset Cards for things like WorldCover
    slices and USDA/IUCN reference classes. "Offered, not web-searched" = a *decision*: we keep
    a vetted set rather than crawling the internet, so provenance and reproducibility stay
    controlled. (This answers your earlier "do we search datasets online" question: no.)
  - tag each as **positive** (examples *of* the class) or **negative** (examples that are *not*
    the class), and freely select/unselect.
- **Right (preferences):**
  - **Spatial**: "only sample inside my area of interest" (clip data to the AOI = Area Of
    Interest).
  - **Temporal**: "only year X" (sets which year's imagery/embedding to sample).
- **Footnote:** these choices are saved on the model (`training.datasets` + a `selection`
  block recording the AOI and year), so the exact retrain can be reproduced later.

**The point:** this is the user-facing control panel for assembling training data, and it maps
directly to fields on the cards.

---

## Slide 11 — Pick, refine, publish (DIAGRAM)
**Shown:** a left-to-right flow of 7 boxes: Area of interest -> Filter the catalogue -> Pick a
base model -> Dataset panel (area + year) -> Retrain -> New Model Card -> Publish to the zoo.
**Meaning:** the end-to-end user journey in one line. Pick where you care about, find matching
models, pick one, choose data, retrain, you get a new Model Card, and you may publish it back.
**Important nuance to say out loud:** publishing is the **user's choice**; nothing flows back
into the shared zoo automatically (this was a deliberate design choice about consent).

**The point:** show that all the pieces (catalogue, cards, dataset panel, retrain) connect into
one coherent loop.

---

## Slide 12 — Quality & imbalance: guidelines baked in
**Shown:** two ideas.
- **Spatial diversity index:** "Shannon entropy of sample locations over a coarse grid,
  normalized to [0,1]."
  - In plain words: chop the map into a grid, count how many of a dataset's polygons fall in
    each cell, and measure how *spread out* they are. **Entropy** is just a number that is high
    when things are evenly spread and low when they're piled up. 1 = well spread, 0 = all in
    one spot.
  - Why it matters: a dataset can have 100 polygons that are all from one district. The count
    looks fine, but the model won't generalize. This score flags that.
  - The real numbers: crops 0.889, mining 0.867, trees 0.840, all high, so our demo datasets
    are genuinely well spread across India. (You computed these, they're not made up.)
- **Imbalance guidelines** (before a split/add trains):
  - check the class ratios; if one class hugely outnumbers another (e.g. more than 5 to 1),
    warn the user;
  - offer fixes: **undersample** the big class (use fewer of its rows), **oversample** the small
    class (repeat/synthesize rows), cap the leftover "residual" class (already capped at 8000),
    or **re-weight** (tell the model to care more about the rare class);
  - record the choice on the card, and always show per-class metrics, because a class can be
    present but still unlearnable (shrubs sit at F1 0.695 even though they're "there").
- **Footnote:** "diversity, not raw volume, moves accuracy on unseen regions" = our own earlier
  finding (the 94% to 71% generalization drop was fixed by more *varied* data, not more data).

**The point:** quality and balance aren't afterthoughts; they're fields and checks built into
the schema.

---

## Slide 13 — Worked examples (real numbers, today's models)
**Shown:** a table of 3 real models + 3 closing bullets.
**The table:**
- `mc_base_pooled_v1`, node root, topology base_pooled, accuracy "0.80 / 0.89". The two numbers:
  0.80 on random real India (the honest, hard test where greenery dominates), 0.89 on a
  balanced expert test (classes evened out). The dagger footnote explains those two settings.
- `mc_greenery_split_v1`, node greenery, per_node_split, accuracy 0.963.
- `mc_barren_mining_v1`, node barren, per_node_split, accuracy 0.867.

**The bullets:**
- greenery split per-class: crops F1 0.965, trees 0.991, shrubs 0.695 (shrubs weak because
  they're WorldCover-labelled, not expert-labelled).
- "mining (ADD = split + residual)" = adding the Mining class works internally as a split of
  Barren into "still barren" (the residual) + Mining. Mining scores F1 0.810 on 100 real
  polygons.
- **The closing claim (most important):** "every field filled from something that already
  exists; nothing invented. All 7 cards validate against the JSON Schema." = we filled the
  schema with our actual models and datasets, with real metrics, and ran them through a formal
  validator (`week4/schema/validate.py`) that confirms they're well-formed. That's the proof
  the schema is real and fits, not a paper design.

**Term notes:**
- **F1** = a single score (0 to 1) combining precision (of what it called X, how much was
  really X) and recall (of all real X, how much it found). Higher is better.
- **residual** = the "everything else that stayed the same" class created during an ADD.

**The point:** this is the evidence slide. The schema isn't hypothetical; it already holds our
real work.

---

## Slide 14 — Thank you
Close with the next step: "If the schema looks right, next week I turn these artifacts into
actual cards and stand up a basic browsable catalogue." Then invite questions.

---

## The 5 questions sir is most likely to ask, with grounded answers
1. **"Is this just design, or did you build anything?"** "It's design, deliberately. You asked
   to finalize the model-card schema (point 9); that's what I did, and I validated it against
   our real models and datasets so it's not hypothetical. Implementation is next week."
2. **"Can users choose different algorithms?"** "Yes within limits: linear and Earth-Engine
   native models keep the fast 10 m path; arbitrary ones don't. On Alpha Earth embeddings the
   data matters more than the algorithm, so linear is the default."
3. **"Why not use USDA/IUCN as the base classes?"** "To keep the taxonomy small and stable and
   stop the model count exploding. We map *out* to those standards optionally, at retrain time."
4. **"What does the diversity number actually mean?"** "How spread out a dataset's samples are,
   0 to 1. It flags datasets that look big but are all from one place. Ours score ~0.85-0.89."
5. **"How is the map 10 m and instant?"** "The model is linear, so it's replayed as arithmetic
   on the bands inside Earth Engine; the whole image is classified server-side and we get one
   picture, no downloads."

## One honest caveat to keep in your back pocket
If sir pushes on timelines: the cards, catalogue, crosswalk, and quality/balance checks are
realistic to build next week because they mostly formalize what already works. The harder,
less-certain pieces are region validity by AEZ/district (needs boundary data), the polished
dataset-selection UI, and pushing models to Earth Engine for sharing. Propose to stub those.
