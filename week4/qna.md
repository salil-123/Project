# Anticipated questions & answers (week-4 schema deck)

Logical, somewhat in-depth questions a reviewer might ask, grouped by theme, with answers you
can give. Grounded in the actual deck and the real numbers from our models.

---

## A. Design & architecture

**Q1. Why two separate card types (Model Card and Dataset Card) instead of one combined record?**
Separation of concerns. A dataset has a life of its own: one dataset (say expert cropland
polygons) can train many models, and many models can share it. If we fused them, we'd
duplicate the dataset's provenance and quality info on every model. Keeping them separate lets
a model just *reference* dataset ids in `training.datasets`, and lets us build a dataset
catalogue independently of the model catalogue.

**Q2. Why per-node classifiers instead of one big multiclass model over all leaves?**
We tested both (the week-3 bake-off): a single flat model scored about 2 points higher offline
(0.885 vs 0.862 accuracy). But per-node wins for an *interactive* tool: splitting or adding one
class retrains one small model on a handful of polygons in seconds, errors stay contained (a
bad greenery split can't disturb water vs built-up), and the tree itself already routes
inference. The flat model would need labelled data for every class each time one changes. So
per-node is the default; the flat model stays as an optional periodic "consolidation" retrain.

**Q3. Why keep our own 4-class taxonomy as the base instead of adopting USDA or IUCN?**
Two reasons. First, forcing every user onto a foreign taxonomy is friction. Second, and more
important, it stops the model count from exploding: if everyone invents top-level classes you
get thousands of incompatible models. By anchoring on 4 classes and letting people map *out*
to USDA/IUCN optionally, models stay comparable. The taxonomy is still editable at every level,
so it isn't a straitjacket; it's a common reference point.

**Q4. Why a flat folder of JSON files instead of a proper database?**
It's the simplest thing that works for the catalogue, and it's git-friendly and human-readable.
Each card is one JSON file; a small `index.json` makes lookups fast. If the zoo grows large we
can move to a database later without changing the card schema itself.

---

## B. The model & algorithm

**Q5. Why LinearSVC, not a random forest or a neural net?**
Two reasons. The practical one: a linear model can be rewritten as plain arithmetic on the 64
Alpha Earth bands, so Earth Engine runs it server-side and returns the whole 10 m map as one
image, no downloads. A random forest can't be expressed that way. The deeper one: we're
classifying Alpha Earth embeddings, which are already powerful learned features, so a linear
head sits near the accuracy ceiling. Our evidence says the data, not the algorithm, is the
lever that actually moves accuracy.

**Q6. So can the zoo ever hold non-linear models?**
Yes, with a caveat. Earth-Engine-native classifiers (its random forest, gradient boosting,
SVM) train and run *inside* EE, so they'd also keep the fast tile path. Arbitrary sklearn or
deep models would lose that and fall back to slow point-sampling. So the realistic menu is
linear models plus EE-native ones; the `topology` and `algo` fields already leave room for it.

**Q7. LinearSVC gives no probabilities. Doesn't that limit the UI (uncertainty, soft thresholds)?**
It does. LinearSVC outputs a hard label, not a confidence. If we want calibrated probabilities
(for an uncertainty overlay, or "show me pixels the model is unsure about"), we'd swap to
logistic regression, which is still linear and still band-math friendly. It's noted as a
follow-up, not a blocker.

---

## C. Data, datasets & validity

**Q8. How does the system decide a model is "valid" for my area?**
Every card carries an `extent` (a region name, a polygon, or an Earth Engine asset, plus a
time). To answer "is there a model for here?", we test whether your area of interest falls
inside that extent. For a polygon or asset it's a direct geometry test; for a named region we
look up the region's boundary and test containment.

**Q9. Is validity really only about space and time?**
No, and we left the `extent` object open for that reason. The concrete third axis is the
embedding: a model is a function of Alpha Earth vectors, so it's only valid where that
embedding exists and is comparable (its version, year, coverage). We start with the axes we can
actually check (space, time) and can add more without breaking the schema.

**Q10. Where do the AEZ / district boundaries for named regions come from?**
That's one of the genuinely harder pieces. Polygon and bounding-box extents work immediately.
Named regions like "AEZ-13" or a district need a boundary dataset loaded in, plus the
containment lookup. I'd flag region-by-name as a follow-on rather than week-one.

**Q11. A user trains only in one district. What stops their model being presented as pan-India?**
The extent is set from where the training data came from, not from the user's optimism. When
they publish, the card records the valid region (an AEZ or the district), and the catalogue
only surfaces it for areas inside that extent. That's the whole point of putting validity on
the card.

---

## D. Quality, metrics & trust

**Q12. What does the spatial-diversity index actually protect against?**
A dataset that looks big but is all from one place. You can have 100 polygons that are all in
one district; the count looks healthy, but a model trained on it won't generalize. The index is
the entropy of where the samples sit, normalized to 0 to 1, so clustered data scores low. It
ties directly to our earlier finding that diversity, not raw volume, fixed accuracy on unseen
regions (a model dropped from 94% to 71% off its training region; more *varied* data, not more
data, closed the gap).

**Q13. Why is shrubs F1 only 0.695 when crops and trees are above 0.96?**
Honest answer: data, not model. Crops and trees came from expert-delineated polygons; shrubs
came from ESA WorldCover, which is noisier, and we only had 114 shrub pixels. So shrubs is a
label-quality and volume problem. It's exactly the kind of weakness the quality fields are meant
to surface rather than hide.

**Q14. The base map shows 0.80 and 0.89. Which is the real accuracy?**
Both, measured two ways. 0.80 is on random real India, where greenery dominates the landscape,
so it's the honest "in the wild" number, held back mostly by the rare classes (barren, water).
0.89 is on a balanced test where the classes are evened out, which shows the model's per-class
skill. We report both deliberately; quoting only the higher one would be misleading.

**Q15. How is the held-out evaluation done, and how do you avoid leakage?**
We use polygon-holdout: whole polygons are kept out of training, and the model is tested only on
those unseen polygons. If we split pixels randomly instead, pixels from the same polygon would
land in both train and test and the model could "cheat" by memorizing a polygon. Holding out
whole polygons gives an honest number.

**Q16. The imbalance threshold is roughly 5:1. Why that, and is over/undersampling safe?**
The 5:1 is a heuristic trigger, not a law; it just decides when to warn. The safer default is
re-weighting (tell the model to care more about the rare class) rather than throwing data away
or duplicating it. Whatever is chosen is recorded on the card, and we always show per-class
metrics, because a class can be present in the data yet still unlearnable (shrubs is the live
example).

---

## E. Operations: split, add, residual

**Q17. What is the "residual", and why cap it at 8000?**
When you ADD a class, say Mining under Barren, the pixels that stay barren become a residual
class ("still barren"). Barren has a huge pixel count, so without a cap the residual would
outnumber Mining maybe 50 to 1 and the model would just predict barren everywhere. Capping the
residual at 8000 rows keeps the two sides comparable so the model can actually learn Mining.

**Q18. Why is ADD treated as a SPLIT plus a residual, rather than its own operation?**
Because once you overlay the user's new-class examples on the existing map, each affected
barren pixel either becomes Mining or stays barren. That is exactly a two-way split of barren
into "Mining" and "still barren". Modelling ADD as split + auto-residual means both operations
share one trainer and one inference path, which keeps the system simple.

**Q19. What if a user's new class looks identical to an existing class in the embedding?**
Then the model can't separate them and keeps predicting the existing class. That's a feature,
not a bug: it tells the user their distinction isn't visible in the data. Mining worked because
it's genuinely distinct in the Alpha Earth embedding; a class that looks like ordinary barren
would just collapse back into the residual.

**Q20. Adding a new base class retrains the whole base map. Isn't that expensive and risky?**
It's the one heavy operation, yes, so it's used rarely and deliberately. In development it's run
against a temporary model path so the deployed base map is never disturbed until we're happy.
Splits and adds at deeper nodes are cheap; only a root-level add triggers the base retrain.

---

## F. Catalogue, lineage & sharing

**Q21. What is lineage for, practically?**
It records which model each model was derived from, forming a family tree with the base map at
the root. It gives us reproducibility ("this model = base map + these datasets + this split"),
a clean "retrain this class" path, and the ability to trace any model back to what it was built
on. It's also how the zoo avoids treating every refinement as an unrelated one-off.

**Q22. If two models cover my area, how do I choose between them?**
The cards expose what you need: each has its metrics and its extent. The catalogue ranks
candidates by accuracy and by how tightly their extent fits your area, so a district-specific
model can be preferred over a pan-India one where it applies. The final pick is the user's.

**Q23. Anyone can publish a model. How do you keep quality up in the zoo?**
Publishing is opt-in, and every published model carries its metrics, its training datasets, its
valid region, and the evidence behind its classes, so a consumer can judge it. The richer
quality controls (a review step, a spatial-diversity score on the catalogue, flagging thin or
clustered training data) are the natural next layer; the schema already has the fields for them.

**Q24. Deployment shows ee_asset and tile_url as null. What's the actual sharing plan?**
For linear models we can push the band-math version into Earth Engine and expose it as a tile
URL, so others run it without downloading anything. That EE-publish step is one of the
less-certain pieces to build, so the fields exist in the schema now and get filled once that
path is wired up.

---

## G. Standards, scope & feasibility

**Q25. Why is mapping to USDA/IUCN optional rather than required?**
Interoperability without coercion. A user who wants their class comparable to a global product
can attach the mapping; a user with a genuinely local class (mining, which WorldCover doesn't
even have) shouldn't be forced to. The crosswalk records "mining rolls up to barren" so global
comparisons still work, without pretending mining is a standard class.

**Q26. Is any of this built, or is it all on paper?**
This was a design week, by intent. The deliverable was the schema sir asked to finalize, and
it's validated locally against our existing models and datasets, so it isn't hypothetical: the
real base map, greenery split, and mining add all fit it with their actual numbers.
Implementation comes next.

**Q27. What is realistically buildable next, and what isn't?**
The cards, the catalogue, the crosswalk, and the quality/balance checks are close, because they
mostly formalize behaviour the tool already has (the data-source dispatch, the 10 m serving, the
diversity metric all exist). The three pieces that need more time are named-region validity
(needs boundary data), the polished dataset-selection UI, and pushing models to Earth Engine for
sharing.

**Q28. How is the 10 m map produced so fast, technically?**
The linear model is replayed as band-math on the Alpha Earth image inside Earth Engine. The
whole scene is classified server-side and returned as a single image, so there's no per-pixel
download and no client-side model run. That speed is the reason we keep the models linear.
