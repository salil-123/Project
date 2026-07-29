# Week 10: slide-by-slide explainer

The companion to `slides_week10.tex` / `slides_week10.pdf`. It walks every slide line by line, in plain
language, adds the intuition where it helps, and ends with the questions likely to come up, with
answers. For the hands-on click-through, see `demo.md`.

This deck covers the instruction points 1, 3, 4, 5, 7, 8, 11, and 13. A few further points (the
estimate check, the UI pass, the canopy comparison, and the deployment and packaging items) were also
worked on and are recorded in the notes, but are kept out of this deck to keep it focused. The build
log is `week10/plan.md`; the running record is `master_document.md` section 9; supporting notes are in
`week10/notes/`.

---

## Foundations: terms to know cold

These recur across the slides, so it helps to fix them first.

1. Embedding. Every point on the map is turned into a vector of numbers that summarises what the
   satellite sees there, instead of the raw image. Alpha Earth is a 64-number embedding served inside
   Earth Engine over all of India. Tessera is a 128-number embedding you download as tiles. We classify
   the embedding, never the raw pixels.

2. Band math, and why it gives a crisp map. A linear model is weights times features plus a bias.
   Because Alpha Earth lives inside Earth Engine as a 64-band image, that multiply-and-add is replayed
   inside Earth Engine on the image itself, so the whole area is classified on Google's servers and
   comes back as map tiles with nothing downloaded. This is why a linear model gives a crisp tile map
   at any zoom. Anything not linear, or using a downloaded embedding, cannot be replayed this way and
   runs on a coarse grid of sampled points instead.

3. Server-side Random Forest, and why it is different from ours. Earth Engine has its own Random Forest,
   `smileRandomForest`, that both trains and classifies on Google's servers. It is not band math, but
   it still produces a finished image on the server, so it renders as tiles just like the base map. This
   is the key to this week's headline: the lab's models use exactly this, so they slot into our tile
   pipeline without a download and without a re-implementation. Our own scikit-learn Random Forest, by
   contrast, runs on our machine and therefore only on the point grid.

4. SAR time series. Sentinel-1 is radar. Radar sees through cloud and reads surface structure and
   moisture, so a crop and a forest look different, and a crop changes through its season while a forest
   does not. Sampling the radar every sixteen days for a year gives a time series that captures that
   difference. The tree-against-crop model is trained on this series.

5. Agro-ecological region. India is divided into regions of similar climate and soil. A crop model
   trained for one region need not fit another, so the farm-and-scrub model is trained per region: for
   an area, find its region, then train on that region's ground-truth points.

6. Regression versus classification. A classifier assigns a class, water or non-water. A regressor
   predicts a number. Biomass is a number, tonnes per hectare, so it is a regression, and it is drawn as
   a colour ramp rather than as discrete class colours.

7. GEDI. A lidar instrument on the space station that fires laser shots and measures vegetation height
   and above-ground biomass at each shot. It is sparse, a scatter of shots, not a full map, which is why
   we use it to train a regressor that fills in biomass everywhere from the embedding.

8. Spatial versus temporal robustness. Temporal robustness is holding out whole years, to check the
   model works on a year it never saw. Spatial robustness is holding out a whole region or water body,
   to check it works on ground it never saw. Doing both at once, an unseen place in an unseen year, is
   the honest worst case, and the one that matters for trusting a number.

9. STAC and STACD. STAC is the common standard for describing a geospatial file: an identifier, a box, a
   geometry, a time, and links to the data. Its record of how the file was made is thin. STACD extends it
   with a dependency graph and records the algorithm that produced an output, its version, and its
   inputs. A dependency graph with no cycles is a directed acyclic graph, or DAG.

---

## Slide by slide

### Title slide
The title names the week's themes: plugging in the lab's production models, biomass, robust water, and
non-linear learners. The running title at the foot is the short version.

### Slide 2, where we are, and what this tackled
Two columns. The left is the state before this round, the right is what it added.

Left: the product is a 4-class base map at 10 m with a living hierarchy, all rendered as crisp
Earth-Engine tiles, plus a git-backed zoo, save and resume, a GeoTIFF export, and per-fortnight water.

Right, the five themes, one per major slide: plug in the IndiaSAT models; add non-linear learners;
understand the biomass data collection; mining segmentation and robust water; and STACD provenance and
the Tessera measurement.

### Slide 3, plugging in the lab's production models
Why this is the centrepiece of the week. Until now every model in the tool was one trained here from a
handful of example polygons. But the group already has mature LULC classifiers in production, and the
brief was to make those usable inside this framework instead of reinventing them. So the real task on
this slide is not a new model, it is turning two existing IndiaSAT classifiers into things a user can
pick from the zoo and apply, the same way they would apply a model they trained themselves.

The two models answer different questions. One tells tree from crop across all of India. The other,
built separately for each agro-ecological region, tells farm from plantation from scrubland. These are
exactly the fine vegetation distinctions our four-class base map cannot make on its own, which is why
they are worth plugging in.

The part that actually made this feasible, and it was not obvious at the outset, is how these models
are built. Both train a Random Forest and run it end to end on Google's servers, through Earth Engine's
own classifier, rather than in Python on our machine. That one fact is what let them slot in: their
output is a finished image on the server, just like our base map's band-math tiles, so they ride the
same tile path with nothing downloaded to us and no re-coding. Had they instead been a deep network in
PyTorch, none of that would hold and we would have needed a separate serving pipeline first.

The last choice worth explaining is that we reproduce the models rather than lift any weights. The
ground-truth points they train on are readable from our Earth-Engine project, so on each request we
retrain the Random Forest in Earth Engine from that data and classify. That sounds wasteful, but it is
exactly how the lab runs them (they keep no model file either), the training is quick server-side, and
it keeps us faithful to the source: the zoo card stores the recipe, not a frozen binary that could
drift away from the data it came from.

### Slide 4, the two models, and how they plug in
The two models are worth contrasting, because they use different signals for different reasons. Tree
versus crop leans on radar, not the annual embedding, and that is a deliberate choice: a crop field
changes dramatically through its growing season while a forest stays roughly constant, and radar
(Sentinel-1) sees that structural change through cloud. So the feature is a year of radar sampled every
sixteen days, twenty three snapshots of two polarisations. Reading how a pixel moves over the year is
what lets the model separate the two. Farm, plantation, and scrubland, by contrast, is built per
agro-ecological region on the Alpha Earth embedding we already use, because those categories mean
different things in different climates and soils, so one pan-India model would blur them; instead, for a
given area, we find its region and train on that region's own ground truth.

Both are stored as a new kind of card, tagged \texttt{ee\_rf}. The reason it is a new kind is that it
holds no model file. A normal card points at a trained joblib; these point at a recipe, the training
asset plus the feature spec and class map, and the model is rebuilt in Earth Engine when needed. This
is not a shortcut, it is what keeps the card honest to a model that is, by design, never saved.

The fourth point is the real result of the week and the thing the previous version got wrong. Because
these models carry their own class scheme, they cannot simply reuse the base four-class tree; and if you
run one on its own it labels the whole box, calling built-up and water "cropland" too, which is nonsense
over a mixed area. The fix is to treat the model as a refinement of one branch. Applying it rewrites the
hierarchy so greenery gains the model's classes as children and is marked with the model; from then on
every classification runs the base map first, then replaces only the greenery pixels with the model's
output, in Earth Engine, keeping built-up, water, and barren untouched. So the tree in the sidebar and
the map on screen both change to follow the model, and it still renders as crisp tiles. The bare
whole-box version is kept only as a way to inspect the model alone.

### Slide 5, non-linear learners, and where they can run
The tension this slide resolves is between accuracy and the crisp map. Random Forest is often the
stronger classifier, so the request was to allow it; but our whole reason the base map is fast and
sharp is that a linear model can be rewritten as simple arithmetic on the embedding image and run on
Google's servers as tiles. A Random Forest is a tree of thresholds, not a weighted sum, so there is no
way to express it as that arithmetic. It cannot ride the tile map, full stop.

Rather than forbid it, we made the renderer aware of which kind of model each split is. The key change
in thinking: before, the code assumed every Alpha Earth split was linear and tried to replay it as
tiles, which would crash on a Random Forest. Now a non-linear Alpha Earth split is recognised and the
area is drawn on the coarse point grid instead, the same fallback a downloaded-Tessera split already
uses. So the choice is surfaced honestly, use Random Forest and accept a grid, or stay linear and keep
the sharp tiles, and the interface labels the trade in the option itself.

XGBoost on Tessera came nearly for free, because Tessera already runs locally on the grid where a
non-linear model is fine; the genuinely new work was letting a Random Forest live on Alpha Earth at all.
And this same grid path is what the next slide's biomass needs, since a regressor is no more expressible
as band math than a forest is.

### Slide 6, biomass from GEDI: the data collection, and findings
Set expectations first: this is deliberately not a shipped feature. The task was to understand the
biomass scripts we were given, reproduce the data collection, and report what we learned, so that when
the group decides how biomass should sit in the LULC we are ready. So the slide is findings, not a demo.

The mechanism is worth understanding because it is what makes biomass easy for us. GEDI is a lidar on
the space station that fires laser shots and measures how much vegetation, by mass, is under each shot.
It is sparse, a scatter of measured points, not a wall-to-wall map. The scripts take those shots and
pair each one with the very same Alpha Earth embedding we already classify land cover on, plus terrain
slope, then fit a model that predicts biomass from the embedding, which lets you fill in the gaps
between shots everywhere the embedding exists.

That leads to the finding that matters: biomass is not a new pipeline for us at all, it is just a
different question asked of features we already have. Land cover asks "which class", biomass asks "how
much", and both read the same 64-number vector per pixel. So it needs no new data path, only a Random
Forest regressor instead of a classifier, and it rides the same point-grid render as any non-linear
model. We reran the collection over a test region and got numbers in the same range the original work
reports, which is the confirmation we were after. The one caveat to be honest about is that predicting a
continuous biomass value from a once-a-year embedding is inherently noisy, so a strict held-out test
scores modestly; a looser random split looks better but is less trustworthy. None of this is wired into
the interface, and it does not need to be until the group decides how the layer should appear.

### Slide 7, segmenting the mining class
The honest starting point, and the thing to say clearly to sir, is that this is not the segmentation
model that was actually asked for. What was intended is an object-detection or instance-segmentation
model, a network that looks at imagery and outputs mines as discrete objects, distinct in kind from the
per-pixel classifier we have. That model needs image patches, hand-drawn mask labels, GPU training, and
a way to serve results outside Earth Engine, none of which is set up. So rather than claim we built it,
this slide presents a deliberate stand-in and is upfront about it.

The stand-in reasons through what we do have. The mining classifier already marks which pixels are
mining; the gap is only that pixels are scattered, not grouped into objects. So we take that existing
prediction and, inside Earth Engine, tidy it and trace it into shapes: remove lone speckle pixels, close
small holes, follow the connected regions into polygons, and discard anything too small to be a real
site. The two reasons this was worth doing now are that it needs no new infrastructure at all, it reuses
the same tile machinery, and it converts a classifier we already trust into objects with real areas that
someone can actually use, today.

Where it matters to be careful is the choice of demo site, which also doubles as a warning about the
classifier. Over Jharia, a genuinely active coalfield, the polygons are real mines. Over Asola, whose
mines were reclaimed into scrub and built-up years ago, anything flagged mining is a false positive, so
it is the wrong place to show the feature and we use it instead as a probe of the model's error rate.
The real object-detection model remains the next step; this is a bridge to it, not a substitute.

### Slide 8, water step one, robustness
The staging is the important framing, and it was a deliberate call rather than a hedge. The full water
feature is a big build, so instead of shipping something half-trusted, we split it: first prove the
core classifier is reliable, then decide how it enters the LULC. This slide is only the first half,
proving reliability, so a low number here would have stopped the whole thing.

What makes the test honest is that it stresses the two ways a model can secretly overfit. A model can
look good simply because it saw the same water body, or the same year, in training. So we hold out
entire water bodies (has it learned water, or just these lakes?) and entire years (does it survive a
year it never saw?), and then both together, which is the true worst case. We can do this for free
because the polygons already record which water body and which date they came from. The answer is
reassuring: even the both-held-out score is about 0.98, and it barely moves year to year, so there is no
lucky year propping it up. That is what lets us say the within-water-body classifier is solid enough to
build the rest on.

### Slide 9, water step one, works anywhere, and counting fortnights
There is a catch hiding behind that 0.98, and this slide is about facing it. All the non-water training
examples come from in and around water bodies, dry lake beds and their edges, so the model has literally
never been shown a city or a farm. Run it there and it over-calls water, because "not water" to it means
"the dry parts near a lake", not "dry land in general". The fix is to feed it that missing negative: we
add barren, built-up, and greenery pixels, sampled across seasons, as extra non-water examples. The
effect is large and specific, its precision on non-water climbs from about 0.72 to 0.99, meaning it
stops painting ordinary ground as water, and that better model is now the one deployed.

The second idea on this slide is what makes water useful to the LULC rather than just a yes/no layer.
We run the classifier not once but across a whole year of fortnights and count, per pixel, how many of
them held water. A permanent lake scores near the maximum; a pond that only fills in the monsoon scores
low. That single count separates perennial from seasonal water, which is exactly the distinction the
IndiaSAT map is built to make and that a simpler product like Dynamic World tends to miss. Actually
folding this into the class hierarchy, running water first and splitting the rest, is the step-two
decision this groundwork sets up.

### Slide 10, acacia, measuring spatial and temporal robustness
Read this slide as a measurement result, not an accuracy boast, and it stops being disappointing.
Acacia against non-acacia is telling two similar tree species apart from a satellite, which is genuinely
hard, so no honest method will make it a high number. What is new is not the model but the test: because
the tree crowns now carry which region they came from, we can, for the first time, hold out a whole
region and whole years at once and ask whether an acacia model actually travels to unseen ground in an
unseen year.

The three numbers are one model scored three ways. Hold out only the years and it gets 0.749. Hold out
only a region and it drops to 0.695, which already tells you geography matters more than time here. Hold
out both a region and the years, the situation a real deployment faces, and it lands at 0.679. The value
of the slide is precisely that downward staircase: it puts a number on how much a single-site,
single-year acacia result over-promises, roughly seven points from the easy test to the honest one. So
the message to take away is not "acacia scores 0.68", it is "here is how to tell whether an acacia model
will hold up elsewhere, and it says treat a single-site number with caution".

One more thing worth pointing out, because it corrects an earlier draft. A smaller run, with fewer
pixels sampled per crown, appeared to show one bad test year and we nearly reported a fluke year. With
more pixels the two test years sit within 0.002 of each other, so that apparent fluke was just sampling
noise. The real picture is a split that generalises consistently across years, just at a modest level,
which is the honest and more useful conclusion.

### Slide 11, how long does Tessera take, against Alpha Earth
The question behind this slide is practical: we have two embeddings, and someone has to know when to
reach for which. So we timed the whole loop on one small area, and the table exists to make one
structural difference visible rather than to celebrate exact seconds. The numbers, download, sample,
train, classify, come to about 72 seconds for Tessera against about 12 for Alpha Earth.

The reason for the gap is the important part, and it is not that one model is slower to fit; training is
under a second either way. It is where the work happens. Alpha Earth lives inside Earth Engine, so
everything is a server round-trip and nothing lands on our disk. Tessera is a set of downloaded tiles,
about 150 megabytes each, so before any classification can start you pay a large one-time download,
around 29 seconds per tile here, and then sampling and classifying happen locally on a coarse grid. The
practical rule that falls out: for browsing anywhere, Alpha Earth wins because its first touch on a new
area costs nothing extra, whereas Tessera only earns its keep once you genuinely need its richer local
features and have already paid to bring the tiles down.

### Slide 12, STACD provenance for every output
The framing to hold onto is that this is a claim of work done, not a lesson on STACD, which sir already
knows. So the slide should read as "we made our outputs describe themselves in the STACD format", and
the explanation here is about what that self-description actually contains and why building it cost us
almost nothing.

Every classified output now carries two things. The first is an ordinary STAC Item for the raster: its
box, its geometry, the class legend with colours, and links to the actual data. The second is the STACD
part, which is the dependency graph, a node for each input dataset and each algorithm, an instance for
every live model, rule, and merge that took part, and the output itself. The reason this was cheap is
that we invented no new record for it. Everything it needs already exists in the tool: the class list
comes from the trained models, the algorithm instances come from the nodes of the hierarchy, and the
input datasets come from the zoo cards. So emitting the whole thing is pure metadata assembly, with no
extra Earth-Engine run.

The genuinely useful move is what we embed as the producing algorithm's inputs: the entire class
hierarchy and the ordered list of operations that built it. That is the literal answer to "what produced
this map", and it is the same envelope the project's save-and-resume already uses, so a STACD record and
a reproducible project are the same object. Two small details follow the paper precisely, an algorithm
instance carries a unique id and the output points at a producing instance rather than a type, and two
naming choices we were unsure about are flagged for the paper's authors rather than settled quietly.
Finally, to be honest about scope: we emit the description half of STACD, not the paper's Airflow
execution engine, which is the natural next layer; but the description already lines up with the drone
and bioacoustics outputs, so the same provenance can be compared across all three projects.

### Slide 13, thank you
Closing slide.

---

## Questions that are likely to come up

1. The IndiaSAT models are the lab's own. What did you actually build?
   The framework to run them as first-class, carded models inside our tool. Concretely: the Sentinel-1
   time-series feature builder for tree-against-crop, the per-region training-and-classify flow for farm
   and scrub, the tile render for both, a new card topology that stores the recipe, and the endpoints
   and overlays. The classifiers and the ground truth were shared with us; the plumbing that makes them usable
   here, and comparable to our own models, is the work.

2. Why re-train the model on every request instead of saving it?
   Because that is how the lab's pipeline runs, trained on the fly from a stored ground-truth asset with
   no saved binary, and Earth Engine's classifier is a server-side object that does not serialise to a
   file cleanly anyway. So the card stores the recipe, the asset, the features, the parameters, and the
   model is reproduced in Earth Engine when needed. The training is server-side and fast.

3. The tree-against-crop feature is a full year of radar. Is that not slow to build interactively?
   It is the heaviest of the new paths. The paper's exact gap-filling by temporal interpolation is too
   heavy for an interactive tile, so for the on-screen overlay we fill gaps with the year's mean, which
   is much lighter and close enough for the map. The faithful interpolation is kept as an option for an
   offline or batch run.

4. Farm and scrub is per region. What happens over a city, where there is no farm ground truth?
   It returns a clean message that there is no agricultural ground truth near that area, because it is a
   rural model, rather than a confusing failure. Over farmland it trains on the nearby ground truth and
   classifies normally. We train on samples near the area, not the whole region, to keep it fast.

5. Random Forest on Alpha Earth loses the crisp tile map. Is that not a step back?
   It is a trade the user chooses. Linear on Alpha Earth stays crisp; Random Forest is offered for when
   a non-linear boundary genuinely helps, and it renders on the point grid, which the interface states.
   The point is that the render path now follows the model, so a non-linear model no longer either
   crashes the tile path or is silently dropped.

6. Biomass scored modestly. Is the model any good?
   The honest region-held-out number is modest because biomass from an annual embedding is a hard,
   noisy regression, and a strict spatial hold-out does not let neighbouring shots leak into training. A
   plain random split scores higher, which is the number the original config reports. The point this
   week was the data collection and the clean integration on our feature space; squeezing the model,
   filtering to high-biomass shots and tuning, is a further step.

7. Is the mining segmentation a real segmentation model?
   No, and the slide says so. It is a vectorisation of the existing pixel prediction into cleaned
   polygons, which gives discrete mining objects with areas from the classifier we already have. A
   learned instance-segmentation network is the future ceiling; this is the pragmatic version that fits
   the pipeline and is useful now.

8. Why is the augmented water model deployed if the hierarchy integration is step two?
   Because the augmented model is strictly better as an interactive tool: it stops calling ordinary dry
   land water, non-water precision rises from about 0.72 to 0.99. Folding water into the class hierarchy
   is the step-two decision; deploying the better water classifier itself is an improvement we took now.

9. The water robustness number, 0.98, looks too easy compared to acacia.
   Because water against non-water within a water body is an easy, stable distinction, while acacia is a
   hard species split. The 0.98 is honest for what it measures, whole-body and whole-year hold-outs.
   Its real weakness is outside water bodies, which is exactly what the augmentation on the next slide
   addresses, so the two slides belong together.

10. Acacia is a weak result. Why present it, and what is the takeaway?
    The point is the method, not the accuracy. Acacia against non-acacia is a hard species split, so a
    modest number is expected; what is new is being able to hold out a whole region and whole years at
    once, which tells you whether an acacia model will travel. The honest ordering (year-holdout 0.749,
    region-holdout 0.695, both 0.679) shows a single-site, single-year number would over-promise, and
    the two test years are stable, so the split generalises consistently rather than by luck. The
    fluke-year check is built in; with enough pixels per crown it comes back clean here.

11. The Tessera download showed as cached in the benchmark. Is the 29 seconds real?
    Yes. The benchmark run reused a cached tile, so its download row was zero that run; the 29 seconds
    for 151 megabytes is a separately measured fresh pull of one tile. An area spanning several tiles
    multiplies it, which is the point: Tessera's first touch on a new area is dominated by that download.

12. How faithfully does the implementation follow the paper?
    It emits all five STACD classes. Two details follow the paper precisely: an algorithm instance
    carries a unique identifier, and the output references a producing instance rather than a type. Two
    remaining naming choices are noted for the authors rather than settled unilaterally, because the
    paper itself is slightly ambiguous there.

13. How much of STACD are we taking on?
    The metadata half, the STAC Item and the DAG with algorithm and dataset instances carrying the
    embedded input set. The runtime half, an Airflow scheduler with selective recomputation and an
    instance database, is a separate decision for the deployment effort. The emitter is ready for Anunay
    and Susmit to compare against their drone and bioacoustics outputs.

14. What is left before this is deployable?
    Packaging: a container with pinned dependencies, a service-account key for headless Earth Engine,
    the code mounted from a clone with data outside the container, and running it on the workstation.
    The code is modular, so these are additions on top of the existing structure, not rewrites.
