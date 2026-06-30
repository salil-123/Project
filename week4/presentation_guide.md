# Presentation guide: week-4 schema deck

Per-slide: what's on screen, and what to say. Keep it conversational; the lines below are a
script you can paraphrase, not read verbatim. Whole deck is ~10 minutes if you keep each
slide to under a minute.

---

## Slide 1 (title): A schema for the LULC model & dataset zoo
**On screen:** title, your name.
**Say:** "Last few weeks I built the classifier and made it editable. This week is a design
week: I worked out the schema for turning that one tool into a library of models and
datasets people can reuse. I'll walk through the structure and show it filled with our real
demos."

## Slide 2: Where we are, and the direction
**On screen:** two columns, "Done so far" and "the direction (what was advised)".
**Say:** "On the left is where we are: a 4-class base map at 10 metres, and a living
hierarchy where you can split or add a class and retrain on the fly. On the right is the
direction you pointed me in: don't stop at one map, build a model zoo and a dataset
catalogue, where every model is tagged with where it's valid, what it produces, and how its
classes were annotated, so a user can pick one for their area and keep refining. This week I
nailed down the structure that makes that possible."

## Slide 3: The structure: two record types (+ a spine)
**On screen:** four bullets (Dataset Card, Model Card, Canonical taxonomy, Catalogue).
**Say:** "The whole thing is two kinds of record plus a spine. A Dataset Card describes a
labelled source. A Model Card describes a trained classifier. The canonical taxonomy is just
our 4 base classes, which everything hangs off. And the catalogue is the registry of all
those cards. The word 'card' is deliberate: it's the model-card idea from ML, a record that
travels with the model and says what it is and how it was made."

## Slide 4: The class tree the cards hang off
**On screen:** the hierarchy diagram. All land has a filled blue model card (LinearSVC) and
teal data card (AlphaEarth & WorldCover); greenery and barren have empty model-card /
data-card slots; water and built-up have none.
**Say:** "This is the tree. The 4 base classes are the backbone. The key idea is the little
cards sitting on the nodes: every node that has a model carries a model card and the data
card it trained on. The base map is pre-selected, that's the filled pair on top, our linear
model trained on Alpha Earth plus WorldCover. Greenery and barren show empty slots, which is
where a user attaches or trains their own. Water and built-up have nothing yet because no one
has refined them. So the diagram is really showing where the choices live."
**If asked about the algorithm:** "Today the model is linear, because a linear model can be
run server-side in Earth Engine for the fast 10 m map. The bigger lever in practice is the
data, not the algorithm, since we're classifying powerful Alpha Earth embeddings."

## Slide 5: Our own taxonomy, growable at any level
**On screen:** three bullets + a small crosswalk table (crops/trees/mining to WorldCover/USDA).
**Say:** "We start from 4 base classes, but the tree grows at any level. You can split a class,
add a class under a node, or even add a brand-new base class, which retrains the base map. New
classes usually map into our taxonomy where they fit, say a seasonal or perennial water-body
under water, which keeps models comparable; but if something genuinely doesn't fit, it can be a
new base class. External standards like WorldCover, USDA or IUCN are not our backbone; they come
in only at retraining time as an optional cross-reference, shown in this table. Mining is the
nice example: WorldCover has no mining class, which is exactly why a user adds it locally and we
record that it rolls up to barren."

## Slide 6: Anatomy of the two cards
**On screen:** Model Card and Dataset Card drawn as cards with their field groups; arrow
"trains on" from model to dataset.
**Say:** "Here's what each card actually holds. The Model Card: where it sits in the tree,
the classes it produces, the datasets it trained on, where it's valid, its metrics, how it
deploys, and its lineage. The Dataset Card: how the data is defined, the classes, the extent,
the embedding, the provenance, and a quality score. The arrow is the link: a model trains on
one or more datasets."

## Slide 7: Dataset Card: two ways to define a dataset
**On screen:** an annotated JSON draft.
**Say:** "A dataset can be defined two ways. Either it's polygons the user drew or uploaded,
or it's a slice of a standard Earth Engine asset, like the cropland class of WorldCover. The
'definition' block is the recipe to fetch the rows. Everything else is metadata: the extent,
who annotated it and how, and a quality score. Worth noting we already do exactly this kind
of source-dispatch in the code today; this just makes it a first-class record."

## Slide 8: Model Card: a classifier at one node
**On screen:** an annotated JSON draft.
**Say:** "The Model Card mirrors that. It says which node it resolves, the classes it
produces with their optional standard mappings, the datasets it trained on, where it's valid,
its held-out metrics, and how it deploys. The deployment line is important: 'expressible as
band-math' is what lets a linear model run inside Earth Engine for the 10 m map. Lineage
points back to the model it came from, so the zoo forms a family tree."

## Slide 9: The typed extent object (validity)
**On screen:** JSON for the extent object + bullets.
**Say:** "Both cards share one 'extent' object that says where and when something is valid. It
can be a named region, a polygon, or an Earth Engine asset, plus a time field. That's how we
answer 'is there a model for my area': we test whether the area falls inside the extent. And I
left it deliberately open, because validity isn't only space and time; a model is also tied to
the embedding it was trained on. We start with the axes we can actually check."

## Slide 10: Choosing the training data: the dataset panel
**On screen:** two columns, what the user picks from, and the spatial/temporal preferences.
**Say:** "When a user retrains, this is the panel. They pick from their own polygons and from
a curated library of standard datasets, tagging each as positive or negative. One decision
here: we offer a curated library, we don't search the web, so provenance and reproducibility
stay controlled. Then two filters: only sample inside my area of interest, and only from a
given year. Those filters get recorded on the model so a retrain is reproducible."

## Slide 11: Pick, refine, publish
**On screen:** the left-to-right flow diagram.
**Say:** "End to end it's this flow: pick your area, filter the catalogue, pick a base model,
choose your data, retrain, and you get a new Model Card you can publish. Publishing is always
the user's choice, nothing goes back to the zoo automatically."

## Slide 12: Quality & imbalance: guidelines baked in
**On screen:** spatial-diversity definition with real numbers, and imbalance rules.
**Say:** "Two quality ideas are built into the schema. First, a spatial-diversity score:
entropy of where the samples sit, so a dataset that's 100 polygons all from one district
scores low even though the count looks fine. I computed it on our demo data; crops, mining
and trees all score high, around 0.85 to 0.89, so they're well spread. Second, before a
retrain we check class balance and, if it's skewed, suggest under- or over-sampling. This
ties to our earlier finding that diversity, not raw volume, is what fixed accuracy on unseen
regions."

## Slide 13: Worked examples (real numbers, today's models)
**On screen:** table of three real models with accuracies + a line about schema validation.
**Say:** "To prove the schema isn't hypothetical, I filled it with our three real models: the
base map, the greenery split, and the mining add, with their actual held-out numbers. Every
field is filled from something that already exists, nothing invented, and all seven example
cards validate against the formal JSON Schema. That's the evidence that the design fits the
work we've already done."

## Slide 14: Thank you
**Say:** "That's the schema. Next step, if it looks right, is to turn today's artifacts into
these cards and stand up a basic browsable catalogue. Happy to take questions."

---

## Likely questions, and short answers
- **"Can users pick a different algorithm, not just LinearSVC?"** "Yes, within limits. Linear
  models and Earth-Engine-native ones like random forest run fast server-side; arbitrary
  models would lose the quick 10 m path. But on Alpha Earth embeddings the data matters far
  more than the algorithm, so I'd keep linear as the default and let data be the main lever."
- **"Why our own 4 classes and not USDA/IUCN as the base?"** "To stop the class and model
  count from exploding, and to not force users into a foreign taxonomy. We map out to those
  standards optionally, at retrain time."
- **"What's the spatial-diversity number really measuring?"** "How spread out the samples
  are, on a 0 to 1 scale. It flags datasets that look big but are all clustered in one place."
- **"How does a model get to 10 m so fast?"** "The linear model is replayed as band-math
  inside Earth Engine, so the whole image is classified server-side and we get one PNG, no
  downloads."