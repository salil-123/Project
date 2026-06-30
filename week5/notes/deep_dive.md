# Week 5 — deep dive (slide by slide)

The companion to `slides_week5.pdf` and `demo.md`. For each slide: what it says, why it matters, and
the key terms defined. This is about the **ideas**, not the code.

### Terms used throughout
- **LULC** — land use / land cover: the classes we map (greenery, water, built-up, barren, and finer
  splits under them).
- **Alpha Earth embedding** — a 64-number vector that Google produces for every 10 m pixel, once a
  year, summarizing what that pixel looks like across a year of satellite data. Our classifiers are
  simple models over these vectors, so "classifying a pixel" means "labelling its 64-number vector".
- **Base map / living hierarchy** — the 4-class classifier, arranged as an editable tree: you can
  split a class or add one at any level, retrain, and the map updates.
- **Model Card / Dataset Card** — small JSON records that describe one model / one data source (the
  idea borrowed from Hugging Face's "model cards"). The cards are the unit the zoo stores.

---

## Slide 2 — Where we are, and what was advised
**Idea.** A recap plus this week's brief. Weeks 2–3 built the 4-class base map and the editable class
tree; week 4 *designed* the card schema on paper; week 5 turns that design into running code.
**Why it matters.** It frames everything after it: we already had models, we just had no formal,
shareable record of them. **The asks:** a database that stores all the cards; give a dataset a *type*
(training vs inference); have a model card link to both; keep a model's validity area a simple
bounding box for now; and try splitting trees into tea / non-tea.
**Key terms.** *Training dataset* = the labelled examples a model learned from. *Inference dataset* =
the input features the model needs to run. *Bounding box (bbox)* = a rectangle [west, south, east,
north] standing in for "where this is valid".

## Slide 3 — From a design to a running database
**Idea.** The four moving parts now exist as code: the two card schemas (with the new fields), a
**catalogue** that *is* the database, a **git** layer for sharing, and the web app.
**Why it matters.** "Catalogue" is the heart: it validates every card, keeps an index, creates cards
automatically from real training runs, and answers "which models cover my area".
**Key terms.** *Schema* = the fixed shape every card must follow (so cards are comparable and
machine-checkable). *Catalogue / registry* = the collection of all cards plus a quick lookup index.
*Mint a card* = generate it automatically from something that already exists (a trained model, a set
of marked polygons), rather than writing it by hand.

## Slide 4 — The pipeline: retrain → card → git
**Idea.** One left-to-right flow: retrain a class node, automatically mint its Model Card and the
Dataset Cards it used, store them in the catalogue, and *publish* by pushing to GitHub.
**Why it matters.** Cards are a by-product of normal work, not extra paperwork — every field is
lifted from things we already produce (the held-out report, the class list, the marked polygons).
**Key terms.** *Held-out report* = accuracy and per-class scores measured on data the model never saw
during training. *Publish = git push* = sharing is just committing the JSON and pushing it. *Local
and offline* = minting never needs the network; the git step is separate and explicit.

## Slide 5 — The week-5 change: typed datasets + two references
**Idea.** A dataset now carries a **type**. A *training* dataset is the labels a model learned from
(polygons or pixel tables, no embedding needed). An *inference* dataset is the feature space the model
runs on (the Alpha Earth vectors, no labels). A Model Card links to **both**.
**Why it matters.** Separating "what it was taught" from "what it consumes" makes a model **portable
and auditable**: you can supply the inference features anywhere the embedding exists, and you can see
exactly what trained it. The inference dataset is shared — every Alpha-Earth model points at the same
feature source.
**Key terms.** *Feature / input* = the numbers a model reads (the embedding). *Label / ground truth* =
the correct class for a location. *Portable* = the model can run in a new area as long as the same
features are available there.

## Slide 6 — The database is GitHub
**Idea.** The catalogue is a **git working tree** of a shared "zoo" repository — the same pattern
Hugging Face uses for its card hub. Publishing a model is a commit + push; versioning, history, and
sharing come for free.
**Why it matters.** It answers "where does the model zoo *live*". Only the small JSON cards are
committed; the trained model binaries stay local, because a card already carries the metrics and
provenance that make it useful without the binary.
**Key terms.** *Git working tree / commit / push* = save a snapshot locally, then send it to the
shared repo. *Provenance* = the record of where a thing came from (who made it, how, with what
evidence). *Versioning* = every change is tracked, so you can see how a card evolved.

## Slide 7 — Browse, and pick a model for your area
**Idea.** The catalogue answers queries: list everything, or filter to models whose **extent** covers
your area. And the extent display is honest: for polygon-backed data we draw the actual polygons;
for India-wide feature sources we show a label, not a country-sized box.
**Why it matters.** This is the "model zoo" promise — find a model that fits *your* region. Because
extent is a bbox, "is there a model for my area" is a plain rectangle-overlap test, no heavy geometry.
**Key terms.** *Extent* = where (and when) a card is valid: a spatial bbox plus a year. *AOI (area of
interest)* = the region the user is looking at. *Footprint* = the actual polygons of a dataset, the
honest answer to "where is this", versus a coarse bounding box.

## Slide 8 — Serving the map: Earth Engine tiles, not a PNG
**Idea.** The base model is **linear**, so it can be replayed as **band math** inside Earth Engine
and evaluated on the server at native 10 m. The result is served as **map tiles** (an XYZ URL), not a
single fixed image.
**Why it matters.** Tiles stay crisp at any zoom and any area size with nothing downloaded; the old
single-image approach was capped in resolution and pixelated when you zoomed in. This is the "tile
URL" the brief asked for.
**Key terms.** *Linear model* = the prediction is a weighted sum of the input numbers, so it can be
rewritten as arithmetic on the image bands. *Band math* = doing that arithmetic directly on the
satellite image. *Map tiles / XYZ URL* = the map is built from many small 256×256 images served on
demand as you pan and zoom (how web maps work). *10 m* = each pixel is 10 metres on the ground.

## Slide 9 — The full-screen Model Zoo
**Idea.** A dedicated browser for the catalogue: tabs for models and datasets, a grid of cards, and a
detail pane. The key actions are **Use a model** (apply it to the map), Show-on-map for the extent,
and Publish. The map stays the default screen; the zoo opens only when asked.
**Why it matters.** "Use a model" is what makes the zoo a *tool*, not just a list: applying a model
makes it live and the map re-classifies; the base-map card resets to the 4 classes. Cards cross-link,
so you can jump from a model to the datasets it used.
**Key terms.** *Apply / use a model* = make a chosen model the one the map runs. *Lineage* = the links
between a model and the datasets (and base model) it came from. *Legend* = the colour key for the
classes a model emits.

## Slide 10 — Describe it, prove it, map it
**Idea.** A model card is not just numbers. The user annotates it: description, intended use,
limitations, and **evidence** (how the classes were annotated). They can also **map each class to a
standard scheme** (ESA WorldCover / USDA), chosen from a built-in list, optionally.
**Why it matters.** This is the "model cards in ML" ask: a model should explain *what it's for, where
it breaks, and how you know the labels are right*. The standard mapping keeps a local class (say
"mining") interoperable with global schemes without forcing everyone onto a foreign taxonomy.
**Key terms.** *Evidence* = the justification for a class (drone imagery, field photos, expert
delineation) — the "how do you know?". *Standard scheme / crosswalk* = a published class list
(WorldCover, USDA) and the optional mapping of our class to it. *Metadata, not a transform* = the
mapping is recorded and shown; it does **not** change the classification.

## Slide 11 — Quality feedback, and fixing skew
**Idea.** Two guards, shown live on the cards. **Spatial diversity (spread)** measures how spread out
a dataset's polygons are; **class balance** flags whether one class dominates, and lets the user
retrain with **undersampling** or **oversampling**.
**Why it matters.** Both are about not fooling yourself: a dataset of "100 polygons all from one
district" generalizes badly, and a lopsided class mix produces a model that ignores the rare class.
Surfacing them turns a quiet failure mode into visible feedback.
**Key terms.** *Spatial diversity / Shannon entropy* = a 0–1 score for how evenly the data is spread
across the map (≈1 well spread, ≈0 all clustered); entropy is the information-theory measure of
"spread-outness". *Class balance / support ratio* = how many examples each class has, biggest ÷
smallest. *Class weight* = telling the model to pay more attention to the rare class. *Undersample* =
drop majority examples down to the minority's size; *oversample* = duplicate minority examples up to
the majority's size. The trade-off: balancing raises the rare class's **recall** (it catches more)
but can lower **precision** (more false alarms).

## Slide 12 — Tea / non-tea: a separability check
**Idea.** Testing the suggested tea / non-tea idea: can Alpha Earth tell them apart at all? Using
hand-marked tea and non-tea polygons, held out whole polygons, a simple classifier reached **0.934**
held-out accuracy. They separate cleanly, so a real split is a sensible next step.
**Why it matters.** It validates a new class idea cheaply *before* committing to it, and it's an
honest measurement — it never touched the base classes.
**Key terms.** *Held-out accuracy* = score on polygons the model never trained on. *Hold out whole
polygons* = put entire polygons (not random pixels) in the test set, so the model can't "cheat" by
seeing nearby pixels of the same polygon during training. *Separability* = whether the features alone
carry enough signal to distinguish the two classes.

## Slide 13 — What's in the catalogue
**Idea.** A snapshot of what's available: the base map, the greenery and barren splits, and their
datasets (training polygon sets, pixel tables, WorldCover slices, and the shared inference source).
11 cards in all, every one validated and pushed to the shared zoo.
**Why it matters.** It shows the abstract machinery is populated with real, usable artifacts, not just
a schema. Per-class held-out metrics live on each card rather than being claimed on the slide.
**Key terms.** *Model card vs dataset card* = a classifier vs a data source. *Validated* = the card
passed the schema check, so it's well-formed and comparable to every other card.

---

## Beyond the slides (good to know if asked)
- **Persisted tiles.** The live tile URL uses a temporary token (fine for viewing). A permanent,
  shareable tile layer would mean saving the model's output as a hosted asset — a clean next step.
- **Standard schemes.** We offer WorldCover and USDA in the pick-list; others (e.g. IUCN) can be
  added the same way. The mapping is always optional.
- **Dataset assembly.** Choosing positive/negative datasets and filtering by area/year to compose a
  custom training set is designed but not yet a single panel — a natural follow-on.
- **Why "spread, not volume".** A recurring finding: a model generalizes to unseen regions better
  when its training data is geographically spread, more than when it simply has more points — which
  is exactly what the spatial-diversity score measures.
