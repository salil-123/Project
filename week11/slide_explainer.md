# Week 11: slide-by-slide explainer

The companion to `slides_week11.tex` / `slides_week11.pdf`. It walks every slide in plain language,
explains the terms and the numbers, and then answers the three review questions that belong in prose
rather than on a slide: #4 (which sensors the lab's models use), #6 (why the Random Forest is different,
and what a coarse grid and a crisp tile map are), and #8 (what the existing tile path is). For the
hands-on click-through, see `demo.md`.

This deck covers the review points that turned into work this round: the STACD cross-check with the
other teams (#15), training-parity for the lab's model (#1), attaching a model to any node (#5), the
mining evaluation (#9 and #12), the water evaluation and the spurious filter (#10 and #13), and acacia
(#11). Two things were worked on but kept off the slides, biomass removal (#7) and the STACD op-log
tidy (#14), and are covered in the short "kept off the slides" note below and in the notes / master
document. The build log is `week11/plan.md`; the running record is `master_document.md` section 10;
supporting notes are in `week11/notes/`.

---

## Foundations: terms to know cold

These recur across the slides, so it helps to fix them first.

1. Embedding. Every point on the map is turned into a vector of numbers that summarises what the
   satellite sees there, instead of the raw image. Alpha Earth is a 64-number embedding served inside
   Earth Engine over all of India. Tessera is a 128-number embedding you download as tiles. We classify
   the embedding, never the raw pixels.

2. Precision, recall, F1, and why they are not accuracy. Precision is, of the pixels the model called
   the class, how many really were it. Recall is, of the pixels that really were the class, how many the
   model caught. F1 is their harmonic mean, a single number that punishes ignoring either one. Accuracy
   is the fraction of all pixels called correctly, and on an unbalanced problem it flatters: if only a
   tenth of pixels are mining, always saying not-mining scores ninety percent accuracy while catching no
   mine. This week reports precision, recall, and F1, which is why some numbers read lower than the
   accuracies quoted before, for the same models.

3. Held-out group split. To measure honestly we never test on a pixel whose polygon or crown also
   appears in training, or the score leaks. We hold out whole crowns, whole water bodies, or whole mine
   polygons, so a test polygon is genuinely unseen.

4. Persistence, for water. The water model reads one fortnight at a time. Running it across a year of
   fortnights and counting, per pixel, how many came back water gives a persistence count. A perennial
   lake scores near the maximum; a road that flooded once scores one. A threshold on that count is the
   spurious-water filter.

5. Self-training, for acacia. A semi-supervised idea: train on the labelled data, predict on unlabelled
   pixels, fold the most confident predictions back in as new labels, and repeat, to grow a thin
   dataset. We tried it; it barely moved the number, for reasons the acacia slides explain.

6. Two tracks. The project has two aims at once: a framework a user plugs their own classifiers into,
   and a set of high-quality classifiers, mining and water, meant to work anywhere in India. The second
   is judged by pan-India experiments, run outside the framework, not by the interface.

---

## Slide 1: Where we are, and what this tackled

The left column is the standing capability, unchanged. The right column frames the round: this was a
review round, so most items are corrections and honest measurement rather than new surface. Five threads:
make the provenance record sendable, remove biomass, generalise where a model can attach, measure mining
and water against real ground truth, and improve the two weak classifiers.

## Slide 2: STACD, cross-checking with the other teams

This is the follow-up to sending our provenance sample out last week. Susmit checked our item against
theirs (the tree-crown pipeline's) and flagged that some parameters differ, without being sure which are
optional and which are mandatory. We compared field by field. The important finding is that the genuinely
mandatory STAC fields, the type, the version, the id, the geometry and box, a datetime, the assets and the
links, were already present on both sides, so our item was never invalid. The differences were of two
kinds. One kind is optional-but-common metadata that we simply did not carry yet, and now do, for
uniformity: the STAC version bumped to match theirs, a collection name, real catalog links instead of an
empty list, a start-and-end datetime range, keywords, and the run parameters. The other kind is fields
specific to their pipeline, a description of the columns in their per-crown output table, and the names of
their detector and DINO models, which do not apply to us because our output is a raster with a class
legend, not a table. A couple of format details are still open, chiefly whether the extension link must
point at a real validatable schema, and the exact catalog layout, which we are following up with Saharsh
this week before re-sending. The full comparison is in `week11/notes/stacd_crosscheck.md`.

## Done this round, but kept off the slides

Two things were worked on but deliberately not given a slide. **Biomass** was taken out of the
land-cover tool, as the review asked, since it is a separate question, above-ground plant weight rather
than a class: every biomass touch-point was removed from the app while the training scripts stay
standalone and the shared plumbing other features rely on was kept intact. **The STACD op-log tidy (#14)**
was also handled off the deck, since the sample itself was presented last week: the class scheme moved
under a clearly named input-set field instead of a doubly-nested one, only the effective operation
sequence is embedded (steps before a reset, and merges later undone, are dropped, not the whole click
history), and the legend lost a stray junk class with greenery drawn green. Both are recorded in the notes
and the master document.

## Slide 3: Training the lab's model the way they do

This is a correctness check on the farm, plantation, scrubland model we ported from the lab. We had been
training it only on ground-truth points within forty kilometres of the user's drawn box. That means a
user with a small box got a model trained on less data than the one the lab actually ships, which quietly
degrades quality. The lab trains across the whole agro-ecological region, a zone of similar climate and
soil. We now match that: drop the forty-kilometre restriction and sample the whole region, with a
balanced cap per class so a big region does not drown a rare class like scrubland. The tree-against-crop
model already trained on its full pan-India asset, so it needed no change. The last line answers the
natural question, why re-train each time rather than store the model: it is an Earth-Engine model that
trains and classifies on Google's servers, so there is no weights file to keep; with the box restriction
gone the training data and the random seed are fixed, so each run reproduces the same model anyway.

## Slide 4: Any model on any node, with a suggestion

A founding promise of the tool is that a user can refine any class they like. The two lab models,
however, were wired to always refine greenery. Now they attach to whatever node the user has selected.
The card still tells the user where the model normally goes, greenery, as a suggestion, but the choice is
theirs. The worked example is the one the review raised: split greenery into dense and sparse by a rule,
then refine just the dense child with the lab's tree-and-crop model, and only that child changes while
the rest of the map holds. A guard was added so that applying the same model twice, which would collide
on class names, is refused with a clear message rather than crashing. The underlying compositing already
worked for any node, so this was mostly exposing the choice safely.

## Slide 5: Is the mining pixel-to-polygon good enough?

The question: we turn mining pixels into polygons by cleaning and tracing them; is that good enough to
avoid building a heavier, learned segmentation model that needs imagery and a GPU? To answer it we ran a
pan-India experiment, outside the framework, on real mine polygons. Read the table as three lenses on the
same mining detector. The first row matches the traced polygons against the true mine polygons at the
object level, asking whether each predicted shape overlaps a real one; it scores 0.07 F1, because the
tracing over-fragments a mine into many blobs that do not line up with the true outline. The second and
third rows judge the pixel classifier itself: linear scores 0.55 F1 with weak precision, and a Random
Forest with a lowered decision cut reaches 0.59, lifting precision from 0.45 to 0.61, the weak spot,
while giving back some recall. The reading: the traced polygons are not a delineator, so a learned
segmentation model is justified if true objects are the goal; but the pixel classifier is a usable screen
for where mines are.

## Slide 6: Water, small against large

The water model currently runs on Sentinel-1 radar, with Sentinel-2 optical water indices alongside,
nine features in all; the optical indices are what soften the road-against-water confusion that pure
radar suffers. The measurement is on the deployed model, split by the size of the water body. Large
bodies are essentially solved, F1 0.99. Small bodies are the real gap: recall 0.67, so a third of small
water is missed. Crucially this is a recall problem, not a spurious one, since on dry land the model
wrongly calls water only about two percent of the time. So the weakness is missing small water, not
inventing it.

## Slide 7: A correction for spurious water, checked on ground truth

The review (point 13) asked for a threshold that holds water only where it persists over a couple of
fortnights, to kill one-off false detections. Note what this is and isn't: it's a **correction on the
water output**, a rule folded into how annual water is decided, not a separate button the user toggles.
In the code it lives as `infer.annual_water_mask` with the threshold in `config.WATER_MIN_FORTNIGHTS`,
ready for the water-into-LULC integration (the deferred step), so the corrected water layer is what feeds
the map rather than the raw per-fortnight flicker. We validate it on the lab's Earth-Engine water ground
truth. The table shows the trade. At any-fortnight, fifteen percent of dry markings are wrongly called
water. At two-fortnights, that spurious rate drops to two percent and water precision climbs to 0.96. But
the same threshold pushes small-water recall down from 0.30 to 0.11. So a single global threshold is a
blunt instrument: it cleans spurious water at the cost of the seasonal and small water we want. That is
the concrete argument for the two-classifier design the review sketched, a lenient first pass that lets
seasonal water through, then a stricter pass inside water bodies.

## Slide 8: Acacia, how many crowns, and a fair filter

We have 336 acacia crowns and 576 non-acacia. The important finding is that every crown is a single tree,
a median of twenty-seven square metres, which is smaller than one ten-metre Alpha Earth pixel of a hundred
square metres. So sampling the embedding at a crown returns a mixed pixel: the acacia tree blended with
whatever surrounds it. That dilution is why the split is near-random on this embedding, and it is a
property of the data, not a bug. The review's rule, drop crowns under ten by ten metres, taken literally
removes ninety-eight percent of the acacia, which is clearly too much. So we drop only degenerate slivers
under fifteen square metres, keeping 296 and 498 crowns. The filter, on our data, is less a cleaning step
and more a diagnosis: the acacia ground truth is thin and sub-pixel.

## Slide 9: Acacia, improving it, and the ceiling

With the data kept, we applied the two levers the earlier notes ranked highest: pool several years of the
embedding, and use a non-linear model. Pooling years and switching from a linear model to a Random Forest
lifts F1 from 0.68 to 0.71 and accuracy from 0.72 to 0.78, and the biggest move is precision, up ten
points, because the forest stops over-calling acacia on look-alike trees. This is a genuine improvement,
but it is bounded, because the input is still a mixed pixel. The real ceiling-raiser is features that
actually resolve a crown: Tessera, a richer embedding, or high-resolution drone imagery encoded with
DINO, which is a self-supervised way to turn image patches into vectors that capture branch and canopy
structure. That route is external. The honest summary is that acacia is improved, not solved.

---

## The review questions answered here (not on the slides)

### #4: Do the lab's crop/tree models use Sentinel-1 only, or Sentinel-1 and 2? What does the other model use?

There are two lab models, and they use different data.

- Tree against crop, pan-India, uses Sentinel-1 only. Sentinel-1 is radar. The features are a
  radar time series: for a year, the two radar polarisations, called VV and VH, are averaged every
  sixteen days, giving twenty-three steps and forty-six numbers per pixel. There is no optical Sentinel-2
  in this model. Radar is chosen because it sees through cloud and reads surface structure and moisture,
  and because a crop's radar signature changes through its growing season while a tree's does not, which
  is exactly the tree-against-crop distinction.
- Farm, plantation, scrubland, per region, uses the Alpha Earth embedding, the same 64-number
  vector our base map classifies on. It does not use raw Sentinel-1 or 2; it uses the pre-learned
  embedding, trained on that region's ground-truth points.

So: the tree-crop model is radar-only Sentinel-1; the farm-scrub model is the Alpha Earth embedding. For
completeness, our own water model, a different thing entirely, is the one that uses both Sentinel-1 and
Sentinel-2 (nine features, radar plus optical water indices), as slide 7 corrects.

### #6: Why is the Random Forest different from the other EE models? What is a coarse grid? What is the crisp tile map?

Start with what makes the crisp tile map possible. A linear model is weights times features plus a bias,
a single multiply-and-add. Because Alpha Earth lives inside Earth Engine as a 64-band image, that
multiply-and-add can be replayed inside Earth Engine on the image itself, band by band. Earth Engine then
renders the result as map tiles on its own servers, computing each tile on demand as you pan and zoom, so
the whole area is classified server-side and nothing is downloaded. That is the crisp tile map: crisp at
any zoom, because each tile is computed at the resolution you are looking at.

A Random Forest is a different kind of model, a vote across many decision trees. It has no single set of
weights, so it cannot be written as band math, so it cannot be replayed inside Earth Engine the way a
linear model can. When we train our own scikit-learn Random Forest, it lives on our machine. To use it we
therefore fall back to sampling: lay a grid of points over the area, fetch the embedding at each point
from Earth Engine, run the forest on those points on our machine, and colour a cell around each point.
That lattice of sampled cells is the coarse grid. It is coarser than the tile map because it is a finite
set of points, not a per-pixel image, and it does not sharpen as you zoom in.

Now the subtlety the review is pointing at. Earth Engine has its own Random Forest, called
smileRandomForest, that both trains and classifies on Google's servers. It is still not band math, but
because it runs entirely on the server it produces a finished image there, so it renders as tiles just
like the base map. This is the key to how the lab's models plug in: they use this server-side forest, so
they give us a crisp tile map without a download and without us re-implementing anything. So the honest
statement is: a linear model gives tiles by band math; a server-side Earth-Engine forest gives tiles by
running on the server; but a local Random Forest, ours, gives only the coarse point grid. The model's
type and where it runs decide which render you get, and the interface tells you which.

### #8: What is the existing tile path?

The tile path is the sequence that turns a classified area into map tiles with nothing downloaded, and it
is the same path the base map, the linear splits, the rule splits, the water model, and the lab's models
all use. Step by step, in the code:

1. Build the label image inside Earth Engine. The base model is replayed as band math, then each trained
   linear split, each rule split, each merge, and each attached lab model is composited on top, all
   server-side. The result is one integer image where every pixel holds its final class code
   (`infer._labelled_bbox`).
2. Colour it. That code image is turned into a visual image by mapping each class code to its colour
   (`.visualize` with the class palette).
3. Ask Earth Engine for a tile server. Calling `getMapId` on the visual image returns a tile-fetcher with
   a template URL, of the usual x-y-zoom tile form (`infer.classify_bbox_tiles`, the line
   `vis.getMapId()["tile_fetcher"].url_format`).
4. Hand that URL to the browser. The backend returns the URL; the front-end drops it into a Leaflet tile
   layer. From then on the browser requests tiles directly, and Earth Engine computes each one on demand.

So nothing is ever downloaded to our server: we pass a URL, and Google renders the tiles. This is why the
map is crisp at any zoom and why a whole bounding box classifies cheaply. The point-grid path from #6 is
the fallback used only when a model cannot ride this path, that is, a local non-linear model or a
downloaded Tessera embedding; everything else uses this tile path.

---

## Questions likely to come up, with answers

1. Why do mining and acacia look worse than earlier weeks? They do not; the metric changed. Earlier weeks
   led with accuracy, which flatters an unbalanced problem, and mining used easy far-away negatives. This
   week reports precision, recall, and F1, and mining is tested against the barren right next to a mine.
   The accuracies actually match, about 0.86 for mining and 0.72 to 0.78 for acacia.

2. Then is acacia any good? It is a hard species split and it is bounded by the mixed-pixel problem: the
   crowns are smaller than a pixel. The improvement to 0.71 F1 is real, but the honest position is that
   the ceiling needs higher-resolution features, not more tuning.

3. Why not just keep the ten-by-ten filter the review asked for? Because on our data it removes
   ninety-eight percent of the acacia; every crown is a single tree. We keep the intent, remove noise, but
   set the threshold where it removes only degenerate slivers, so the dataset survives.

4. Is the spurious-water filter a button? No. It is a code-level correction on the water output
   (`infer.annual_water_mask`, threshold `config.WATER_MIN_FORTNIGHTS`, default two), applied when the
   fortnight water model feeds the annual map, not a control the user toggles. It is a blunt global
   threshold that costs small-water recall, so the proper fix, the two-classifier design, is the next step.

5. Did you actually reach the lab's Earth-Engine ground-truth assets? Yes. All three named assets are
   readable from our project: the seasonal and perennial water bodies, and the differently-sized
   water and non-water markings. The water evaluation uses all three live.

6. Can a user attach a model to a node that is not a base class, like a rule-split child? Yes. The
   compositing reads whichever node carries the model and refines exactly that node, so a child of a rule
   split works. Only the entry points were hard-wired before; that was the fix.

7. Why remove biomass rather than hide it? Because the review was explicit that it is a separate project,
   and leaving dead wiring in the tool invites confusion. The scripts remain, so nothing is lost.

8. Is the mining classifier deployable as-is? As a screen, yes; as a precise object delineator, no. The
   pan-India numbers say a learned segmentation model is the route if true polygons are needed, which is
   the deliberate takeaway of the mining experiment.

---

## Deeper questions raised on review

These go beyond the slides; they answer specific things asked while reviewing the deck.

### What is this "extension link" business (STACD cross-check)?

Inside a STAC item there is a field called `stac_extensions`. It is a list of web links, and each link
is meant to point at a JSON schema, a machine-readable rulebook that defines any extra, non-standard
fields the item uses. A validator reads those schema links and checks that the extra fields are well
formed. Susmit's item points its `stac_extensions` at a real published schema (the "table" extension on
the STAC extensions site). Ours points at the STACD project's GitHub repository, which is source code,
not a JSON schema, so a strict validator cannot use it to check anything. The open question for Saharsh
is therefore just this: does the Airflow catalogue actually validate `stac_extensions` against real
schemas, in which case we should either drop the repo link or publish a proper STACD schema and point at
that; or is pointing at the repository simply an accepted marker in their setup, in which case ours is
fine as it stands. So the whole "extension link" business is one question: is that link a real rulebook,
or just a label.

### Is the tree-against-crop model already trained and stored locally? Is farm/plantation/scrubland the only one trained on the fly?

Neither lab model is stored locally, and both are trained on the fly, so farm-shrub is not the only one.
This is worth stating plainly, because it is easy to assume tree-against-crop is a saved model. Both the
tree-against-crop and the farm-plantation-scrubland models are Earth Engine Random Forests
(`ee.Classifier.smileRandomForest`). When we run either one, Earth Engine trains the forest on Google's
servers from a stored ground-truth asset and immediately classifies with it, all in the same server-side
call; we keep the recipe (the pointer to the training asset, the feature list, the settings), not the
fitted model. The only difference between the two is the scope of the training data, not where the model
lives: tree-against-crop trains on the whole pan-India SAR asset, while farm-plantation-scrubland trains
on the ground-truth points for the area's agro-ecological region (this week we fixed it to use the whole
region rather than a forty-kilometre box around the user's view).

### What do we mean by "no weights file to keep"?

A scikit-learn model is a set of learned numbers (for a linear model, the weights and the bias; for a
forest, the tree structures) that we can save to a `.joblib` file and reload later. An Earth Engine
`smileRandomForest` is not that. It is a server-side object that exists only inside a running Earth
Engine computation; there is no array of numbers handed back to us to write to disk. So there is nothing
to pickle or store, which is what "no weights file to keep" means. The faithful way to "keep" such a
model is to keep the ingredients (the training asset and the settings, with a fixed random seed) and
re-fit on demand, which reproduces the very same model each time.

### What do we mean by "outside the framework"?

The framework is the interactive web tool, the thing a user opens in a browser to paint a map, split
classes, and plug in models. The high-quality pan-India classifiers, mining and water, are judged by
separate command-line experiments (the week11 python scripts), run over ground truth from across the
country, not through that web tool. Sir asked for this directly: the accuracy of these models is a
pan-India question, so it should be measured over all the ground truth at once in a batch script, rather
than by clicking one small box at a time in the interface. So "outside the framework" just means the
evaluation is a standalone offline experiment, not a feature inside the app.

### On the mining slide, why is the first row so bad, and why are the other two so much better?

The three rows measure different things, which is why they read so differently. The first row is the
hardest test: it takes the polygons we produce by vectorising the mining pixels and matches them, shape
against shape, to the real mine polygons, counting a hit only when a predicted shape overlaps a real one
by at least thirty percent. It scores very low (about 0.07 F1) because the vectorising over-fragments:
one real mine comes out as many small blobs, and those blobs rarely line up with the true outline, so
almost nothing counts as a clean object match. That is an object-delineation test, and it is unforgiving.

The second and third rows drop the shape-matching and ask the easier, pixel-level question instead: of
the pixels that are really mine, how many did the classifier label mine, and of the pixels it called
mine, how many really were. That is a far lower bar than reproducing a polygon's outline, so the numbers
are naturally higher. The second row is the plain linear classifier (about 0.55 F1, good recall but weak
precision). The third row is a Random Forest with its decision threshold lowered, which trades a little
recall for much better precision (0.45 rising to 0.61), giving the best pixel-level result (0.59 F1). In
short, row one grades whole shapes and is brutal; rows two and three grade individual pixels and are
kinder, and the forest with a tuned threshold is the best pixel classifier.

### Why were we reporting much better numbers in the past than now?

Two things changed, and neither is a regression. First, the metric: earlier weeks led with accuracy,
which flatters an unbalanced problem, since a class that is only a tenth of the pixels can be ignored and
still score ninety percent. This round reports precision, recall, and F1 for the class we actually care
about, a stricter and more honest lens, so the same model reads lower. If we quoted accuracy today it
would match the old numbers (about 0.86 for mining). Second, the test itself got harder for mining:
earlier the non-mining examples were taken far away from real mines (easy negatives), whereas now they
are the barren ground right next to each mine (the buffer ring), which is exactly the terrain the model
confuses; testing against that harder negative drops recall from about 0.85 to 0.70. So the fall is a
stricter metric on a harder test, not the model getting worse.

### How is the two-fortnights filter helping us?

The per-fortnight water model looks at one two-week window at a time, and because water and wet or dark
surfaces can look alike, it occasionally calls something water that is not: a road with monsoon
water-logging, a freshly wet field, or radar speckle. Those false calls tend to show up in just one
fortnight and then vanish. The filter runs the model across the whole year and keeps a pixel as water
only if it came back water in at least two fortnights, so the one-off false calls are dropped while a
genuine pond or lake, wet in many fortnights, survives. On the ground-truth check this cut the share of
dry markings wrongly called water from fifteen percent down to two, and lifted water precision from 0.80
to 0.96. The cost is that truly seasonal water, wet for only a single fortnight, also gets filtered,
which is why it is a first-pass correction and not the final answer.

### When we say the acacia "split is hard", do we mean the classification is difficult?

Yes, we mean the classification is difficult; it says nothing about the tool's editing being awkward. In
our vocabulary a "split" is the classifier that divides a class into finer ones, here the decision that
separates acacia from non-acacia. Calling it a hard split means that decision is genuinely difficult to
make well, for two reasons: acacia and the other trees are different species but look almost the same to
the satellite, and each acacia crown is smaller than a single ten-metre pixel, so the pixel we classify
is a blend of the tree and whatever surrounds it. Both push the accuracy down. So "hard split" is just
shorthand for "this is a hard thing to classify".

### Did we access the Earth Engine assets that were shared?

Yes, all of them. The three assets you shared are readable from our Earth Engine project and are used
live in the water evaluation: the seasonal water bodies (sixteen), the perennial water bodies (thirteen),
and the differently-sized water and non-water markings (two hundred and eighty-eight, which also carry a
class label and an area, so we can split them into small and large). The water ground-truth script reads
all three directly, so nothing there was blocked.
