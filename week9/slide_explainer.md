# Week 9: slide-by-slide explainer

The companion to `slides_week9.tex` / `slides_week9.pdf`. It walks every slide line by line, in plain
language, adds the intuition where it helps, and ends with the questions likely to come up, with
answers. For the hands-on click-through, see `demo.md`.

Week 9 delivered a chosen subset of the instruction points: 3, 4, 5, 7, 8, 12, and 13, plus the
model-to-data linkage (1) and options for improving acacia (11). The build log is `week9/plan.md`;
the running record is `master_document.md`; supporting notes are in `week9/notes/`.

---

## Foundations: terms to know cold

These recur across the slides, so it helps to fix them first.

1. Embedding. Every point on the map is turned into a vector of numbers that summarises what the
   satellite sees there, instead of using the raw image. Alpha Earth is a 64-number embedding served
   inside Earth Engine over all of India. Tessera is a 128-number embedding you download as tiles. We
   always classify the embedding, never the raw pixels.

2. Band math, and why it gives a crisp map. A linear model is just weights times features plus a
   bias. Because Alpha Earth lives inside Earth Engine as a 64-band image, that multiply-and-add can
   be replayed inside Earth Engine directly on the image. The whole area is then classified on
   Google's servers and comes back as map tiles, with nothing downloaded to us. This is why a linear
   model gives a crisp tile map at any zoom. Anything that is not linear, or that uses a downloaded
   embedding, cannot be replayed this way and has to run on a coarse grid of sampled points instead.

3. Rule split versus model split. A model split learns the boundary between sub-classes from example
   polygons. A rule split sets the boundary by hand, as a threshold on an index, with no training and
   no data to mark. Intuition: sometimes you already know the rule, for example water is where the
   water index is high, so training a model to rediscover it is wasted effort.

4. Index. A simple formula on satellite bands that has a known meaning. NDVI is greenness, high for
   dense vegetation. NDWI is a water index, high for open water. Slope is steepness from a terrain
   model. Kharif is the Indian monsoon crop season, Rabi is the winter crop season, so seasonal NDVI
   separates crops that grow in one season from another.

5. STAC and STACD. STAC is the common standard for describing a geospatial file: an identifier, a
   bounding box, a geometry, a time, and links to the data. Its record of how the file was made is
   thin: one field naming a parent, without the algorithm or the settings. STACD is an extension that
   adds a dependency graph and records the algorithm that produced an output, its version, and its
   inputs. A dependency graph with no cycles is called a directed acyclic graph, or DAG.

6. Raw Sentinel. Sentinel-1 is radar, which sees through cloud. Sentinel-2 is an optical camera. The
   annual embedding blends a whole year, so it cannot answer a single-fortnight question. For that we
   go back to these raw satellites and composite a short window around the date.

7. Why the data source decides the model. Only a linear model becomes band math, so anything served
   from Earth Engine must be linear. Tessera is downloaded and classified locally on a grid, so it is
   not restricted to linear and can use a Random Forest. That is the whole reason the valid model list
   depends on which inference data the user picks.

---

## Slide by slide

### Title slide
The title names the four themes of the week: interpretable rule splits, a proposal for provenance in
the STACD format, per-fortnight water, and safe defaults. The short running title at the foot is
"Rules, provenance, and raw-Sentinel water".

### Slide 2, where we are, and what week 9 tackled
Two columns. The left is the state before this week, the right is what this week added.

Left, first line: the product is a 4-class base map of India at 10 m resolution, with a living
hierarchy, meaning you can split or add a class, mark a few example polygons, and retrain just that
node without touching the rest.

Left, second line: everything trained is stored as a card in a git-backed zoo, and the zoo already
supports save and resume, merge, choosing the base classes and the year, exporting a GeoTIFF, and it
has been tested on acacia, tea, and mining sites.

Right, the five bullets are the week's themes, one per major slide to come: rule splits; reading the
STACD paper and proposing a provenance record; water seasonality on raw Sentinel; safe defaults,
being the size cap and the benchmark; and linking the valid model families to the chosen data. The
phrase a chosen subset is deliberate, since these are the instruction points we picked, not all of
them.

### Slide 3, splitting a class by a rule, not a model
Bullet one: until now, dividing a class always meant marking data and training a classifier, but
sometimes the boundary is just a threshold on a known index, for example dense against sparse
vegetation by annual NDVI. Intuition: this is the motivation, that training is overkill when you
already know the rule.

Bullet two: a rule split lets the user write that threshold directly, so if the expression holds the
pixel takes one class, otherwise it takes the default class, with no data to mark and no training.

Bullet three: the indices come from a fixed registry, so expressions stay interpretable, and every
expression is checked against a whitelist of allowed variables and operators before it reaches Earth
Engine. Intuition: this keeps a rule safe and readable, since a user cannot invent a variable or slip
in arbitrary code.

Bullet four: because the indices are computed inside Earth Engine, a rule split renders as the same
crisp 10 m tile map as a linear model, it is stored on the node so it travels with the saved project,
and it gets a card in the zoo like any other model. Intuition: a rule is a first-class part of the
tree, not a throwaway calculation.

### Slide 4, the rule variable registry
Opening line: the indices a rule can use, all computed live from Sentinel and SRTM over the chosen
area and year. SRTM is the terrain elevation model.

The table lists the nine indices in four groups. Vegetation has annual NDVI plus the two seasonal
NDVIs, Kharif and Rabi. Water has NDWI and MNDWI, two water indices. Built and soil has NDBI, a
built-up index, and BSI, a bare-soil index. Terrain has slope and elevation from SRTM.

Where the indices come from, if asked. They are not invented for this tool. Each is a standard
remote-sensing formula on satellite bands with a settled meaning: NDVI is the normalised difference
of the near-infrared and red bands, NDWI and MNDWI are the analogous water indices on the green band
against the near-infrared and the short-wave infrared, NDBI and BSI are the usual built-up and
bare-soil formulas, and slope and elevation come straight from the SRTM terrain model. We reuse the
exact band formulas already used in the CoRE-stack flood pipeline, so our indices line up with the
rest of the stack. The one design choice is the two seasonal windows: Kharif is the monsoon crop
season and Rabi is the winter crop season, so those NDVIs follow the Indian crop calendar used in the
reference LULC work, which is what makes a rule like a monsoon-only NDVI peak meaningful for
separating single-season from two-season crops.

### Slide 5, STACD, what I understood from the paper
Opening line says plainly that this is my reading of the paper, put up so we can confirm it together.
Framing it this way is deliberate, so the slide does not overclaim.

Bullet one: STAC describes a single asset well, but its record of lineage is shallow, being a
derived-from field that names a parent without saying which algorithm, which version, or which
settings produced it.

Bullet two: STACD extends STAC with a directed acyclic graph and five classes. A DAG for the workflow
shape. A Dataset Type and an Algorithm Type as the two kinds of node. An Algorithm Instance that
records a specific version and its code. And a Dataset Instance that extends a normal STAC Item with
the producing algorithm and its inputs. Intuition: STAC says what a file is, STACD adds how it was
made.

Bullet three: the payoff is provenance and selective recomputation, meaning if a model or an input
dataset changes you can see exactly which downstream outputs need rebuilding, and leave the rest
alone.

Bullet four: the paper gives a reference implementation on Apache Airflow, a workflow scheduler.

### Slide 6, how our output could map onto STACD
Opening line: something like this could work for us, and a classified output would carry two things.
This is phrased as an option, not as delivered work, and every bullet stays in the conditional.

Bullet one: a stack specification, which is a STAC Item for the LULC raster, carrying the bounding
box, the geometry, the class legend with colours, and asset links to the GeoTIFF and the tile
endpoint.

Bullet two: a STACD specification, which is the DAG plus the dataset and algorithm nodes, with one
algorithm instance for every live model, rule split, and merge, each pointing at where its artifact
lives in the zoo.

Bullet three: the input set, which is the class hierarchy, the ordered operations that built it, and
the pointers to the artifacts, carried as the inputs of the producing algorithm. This is the JSON we
already keep, which would sit inside the STACD record as the input set that produced the output. This
is the exact phrasing that was put to us, that our JSON becomes a property inside STACD describing the
input set.

Bullet four: the appeal is that it reuses the cards we already have, so it needs no new source of
truth, and it stays a cheap metadata step with no extra Earth Engine work.

### Slide 7, water seasonality, one fortnight at a time
Bullet one: the annual embedding is a whole-year signal, so it cannot say which pixels held water on
a given fortnight, and for that we go back to raw Sentinel, being Sentinel-1 radar and Sentinel-2
optical, composited around a target date, with the standard water indices.

Bullet two: we train a linear water against non-water model offline on the shared seasonal-water
polygons, sampled at each polygon's own date, then replay it as Earth-Engine band math for any chosen
fortnight. This keeps it interactive, using the same trick as the base map, and it avoids the memory
limit that pushed the earlier flood pipeline to a slower batch export. Intuition: the linear-becomes-
band-math trick is what lets a single-date water map run live instead of as an overnight job.

Bullet three keeps the results deliberately vague: early results are good enough to work with for
now, and we can tighten them as we add more polygons and dates. The actual numbers are on record if
sir asks: on 2046 held-out pixels the model reached about 0.918 overall accuracy, with water
precision and recall near 0.98 and 0.92 and non-water near 0.72 and 0.92, trained on 8147 pixels
across 459 dates. Reading those: the model almost never calls dry land water and catches most real
water; the softer number is non-water precision, meaning a little true water near a boundary is
occasionally called non-water, which is expected since non-water is the smaller class. We keep the
table off the slide because the model is new and the numbers will move as the dataset grows.

### Slide 8, a size cap on the drawn area
Bullet one: a user can draw any rectangle, and a large one can quietly become a very slow request or
a large download, so we now check the area before running.

Bullet two: the three paths cost differently, so the caps differ. The Earth-Engine tile map is
generous, because tiles render on demand. The GeoTIFF export is smaller, because that download is
size limited by Earth Engine. The Tessera path is capped by tile count, because each tile is a large
local download. Intuition: cap each path by what actually hurts it, rather than one blanket number.

Bullet three: the caps are plain environment settings, so a server administrator can tune them for
the hardware, and the interface reports the area and refuses to run past the hard limit with a
readable reason instead of hanging.

### Slide 9, how long does training take
Opening lines: a benchmark separates the two costs so an administrator can size the server. Sampling
the embeddings over Earth Engine is network bound and usually the larger cost; the linear fit is
cheap. Random Forest is shown as a local reference only, since it does not render as tiles.

The table gives the estimated wall-clock time by area, at 10 percent pixel density, from 1 to 100
square kilometres, splitting sampling time from the linear total. Reading it: a small box trains in a
few seconds, and even a 100 square kilometre box is a few minutes, almost all of it sampling.

Closing note: the numbers were measured on a Windows laptop, they feed a saved profile and a live
estimate endpoint, and they are the reference for setting the area caps on the previous slide.
Intuition: the caps and the benchmark are two sides of the same coin, since you cap where the time
gets uncomfortable.

### Slide 10, linking models to the inference data
Bullet one: when a user trains, the valid model families now follow the data they picked, and Earth
Engine can only run linear models because only a linear model replays as band math, so the Alpha
Earth list is linear only.

Bullet two: a Tessera run is a local computation, so it is not limited to linear, and it adds Random
Forest, XGBoost when that package is installed, and reserves a slot for an object-detection family we
have not built yet.

Bullet three: the training panel reads this list, so the user is only offered models that fit their
data, and a non-linear model on Alpha Earth is refused with a clear reason.

Bullet four: this is the linkage that was advised, that the dataset a user works with determines the
models available for it, and the set is easy to extend. Intuition: the interface stops you from
picking a model that could never render, before you waste a training run on it.

### Slide 11, improving the acacia split
Opening line: acacia against non-acacia is our hardest split, a species distinction between similar
trees, and the slide lists only the options we have actually measured on it.

Bullet one: more labelled crowns across sites and years, because data spread is the proven lever, and
pooling several years already moved this split from 0.635 to 0.745 on years the model had never seen.
Intuition: a species split fails mostly from seeing too few places and seasons, not from a weak model.

Bullet two: Tessera as the feature source, tested at about 0.73 on the same split, and with the
linkage from the previous slide it can now also carry a non-linear model such as Random Forest, which
the 64-dimensional Alpha Earth path cannot.

Bullet three: the automatic bake-off, already run on this split, where Ridge came out ahead at 0.731.
Other untested ideas are kept off the slide and live in the notes.

### Slide 12, where the product stands
Bullet one: the full loop works, being paint a map, grow a scheme with splits, rule splits, adds and
merges, retrain, browse and publish the zoo, save and resume a project, and export a GeoTIFF, so this
is a demo-ready product.

Bullet two: what stands between a demo and a hosted service is mostly packaging, being a service-
account key for headless Earth Engine, a container, pinned dependencies, and a basic access limit so
the compute is not open to anyone, and since the code is modular these are additions rather than
rewrites. Intuition: the hard part, the structure, is done, and what remains is wrapping.

Bullet three: the water model is new and is only lightly wired into the interface so far.

### Slide 13, thank you
Closing slide.

---

## Questions that are likely to come up

1. If a rule split needs no training, why call it a model and give it a card?
   Because it is still a decision the user authored that produces a class on the map, and the zoo is
   the record of every such decision. The card carries the expression and the variables it reads, so
   the split is reproducible and shareable. It carries no learned file, because there is nothing
   learned.

2. How is a rule split different from just computing NDVI and thresholding it yourself?
   It is the same arithmetic, but it is wired into the hierarchy, so the result composites with the
   base map and with other splits and merges, renders as the same tile map, and travels with the
   saved project. It is a thresholding step that is a first-class part of the classification tree,
   not a one-off calculation.

3. Can a rule combine several indices?
   Yes. The simple picker writes one condition, but the advanced box accepts a full expression such
   as annual NDVI above 0.3 and slope below 5. We validate it against the registry and the allowed
   operators before use.

4. What happens if clauses overlap, or a pixel matches nothing?
   Clauses are first-match wins, evaluated in order, and any pixel that matches no clause takes the
   default class, so every pixel gets exactly one label.

5. Does the rule split also work in the Tessera point-grid path?
   Yes. On the crisp path it is evaluated directly in Earth Engine. On the point grid we sample the
   rule's class at each grid point, so a rule under a Tessera run still resolves.

6. For STACD, how much of it are you proposing to take on?
   The proposal is the metadata half, being the STAC Item and the DAG with algorithm and dataset
   instances that carry the embedded input set. The runtime half from the paper, an Airflow scheduler
   with selective recomputation and an instance database, is a separate decision. The mapping note
   also lists a couple of naming details worth confirming with the authors.

7. Why not present the second paper, the hierarchical classifier one?
   Because that paper is the hierarchical decision-tree idea, and our splits, rule splits, adds, and
   merges are the implementation of it, so showing the implementation shows the idea in action. The
   full mapping, including the crop-to-shrub reassignment where a rule moves pixels across branches,
   is written up in `week9/notes/decision_tree.md` if it comes up, so it does not need its own slide.

8. The water model is linear. Would a Random Forest do better?
   Probably, on raw features. We chose linear on purpose, so the model replays as band math and stays
   interactive for any date. The earlier flood pipeline used a heavier model and had to run as a batch
   export because the interactive path ran out of memory. If we accept a slower, point-grid water map,
   a non-linear model is a reasonable future option.

9. Why is non-water precision lower than water precision?
   Non-water is the minority class in the training data, 156 polygons against 720, and the ring around
   a water body can look wet after rain. The recall on non-water is still high, so we rarely miss real
   non-water; the lower precision means some true water near a boundary is occasionally called
   non-water. More non-water polygons and boundary examples would tighten this.

10. Are the training-time numbers portable to a server?
    The shape is portable, the constants are not. Sampling cost is dominated by the Earth-Engine round
    trip and the fixed batch size, so it scales with the number of batches; the fit is small for
    linear models. On a different machine or network the constants change, so the benchmark should be
    re-run on the target server, which is what the script and the profile are for.

11. Why cap the bounding box instead of letting Earth Engine handle it?
    The tile map can handle a large area, but the GeoTIFF export is size limited by Earth Engine and
    the Tessera path downloads large tiles per grid cell, so an unbounded box turns into a failed
    export or a very large download. The cap gives a clear early refusal instead of a slow failure,
    and the administrator can raise it for a stronger server.

12. Why is Earth Engine restricted to linear at all?
    Because the efficiency of the base map is that a linear model becomes band math and runs on
    Google's servers with no download. A non-linear model cannot be expressed that way, so it would
    force a point-grid render and lose the crisp map. Tessera already renders on the point grid, so
    there the restriction does not apply and we allow the richer models.

13. Is object detection built?
    No. It is listed for the Tessera source as planned, so the interface reserves the slot, but the
    model itself is future work. It is the natural approach for discrete objects such as tree crowns.

14. How far is the product from being deployable?
    The code is modular and the loop is complete, so it is demo ready now. A hosted service needs a
    service-account key for headless Earth Engine, a container, pinned dependencies, and a basic
    access limit so the compute is not open. These are additions on top of the existing structure,
    not rewrites.