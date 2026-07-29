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
This is the headline: use the IndiaSAT models shared with us, train and store them, and list them in the zoo so a
user can plug one in to split a class.

Bullet one: two models were shared, a pan-India tree-against-crop classifier, and a per-region farm,
plantation, scrubland classifier.

Bullet two: we found that both train a Random Forest and classify entirely inside Earth
Engine, so, like our base map, they render server-side as crisp tiles with nothing downloaded and no
re-implementation. This is the point from foundation 3.

Bullet three: their training data is readable from our Earth-Engine project, so we reproduce the models
faithfully rather than copying weights. That matches how the lab runs them, trained on the fly from a
stored ground-truth asset with no saved binary.

Bullet four: each is now a card in the zoo, applied from there (the next slide covers how it plugs into
the hierarchy).

### Slide 4, the two models, and how they plug in
Bullet one, tree vs crop, pan-India. Its features are a Sentinel-1 radar time series, foundation 4,
twenty three sixteen-day steps of two polarisations. We build that series in Earth Engine and classify
it with the model's Random Forest, trained on about seventy thousand labelled points.

Bullet two, farm, plantation, scrubland, per region, foundation 5. The features are the same Alpha Earth
embedding we already use. For an area we find its region, train the Random Forest on that region's
points, and classify. About one and a half million labelled points across nineteen regions back it.

Bullet three: both are cards with a new topology, ee\_rf. The card stores the recipe, the training
asset, the feature source, and the class mapping, not a file, because the model is re-trained in Earth
Engine on demand. This is faithful to how the lab runs them, with no saved model.

Bullet four, the integration, which is the real result here: these models bring their own class scheme,
so they cannot reuse the base tree. Applying one rewrites the hierarchy — greenery gains the model's
classes as children and is marked with the model — and every Run classification then refines only the
greenery pixels with the model in Earth Engine, keeping the rest of the base map (built-up, water,
barren). So the tree and the map both follow the model, rendered as crisp tiles. A bare, standalone
version that labels the whole box also exists, but that mislabels non-vegetation, which is why the
greenery refinement is the default.

### Slide 5, non-linear learners, and where they can run
Bullet one: the aim was Random Forest on Earth Engine, since it is the model that usually works, and
XGBoost on Tessera. XGBoost on Tessera was almost free because Tessera already runs locally; Random
Forest on Alpha Earth was the real work.

Bullet two: a Random Forest is not linear, so it cannot be replayed as band math and cannot ride the
crisp tile map. The fix was to make inference algorithm-aware. A non-linear split on Alpha Earth is
dropped from the tile path, and the whole area falls back to the point-grid render, the same path a
Tessera split already uses. Intuition: the render path is now chosen by the model type, not assumed.

Bullet three: so the user can choose Random Forest on Alpha Earth; it renders on the coarser point grid
instead of tiles, and the interface says so in the option's note. Linear models still give the crisp
map.

Bullet four: this same non-linear point-grid path is what biomass would use, which is the next slide.

### Slide 6, biomass from GEDI: the data collection, and findings
The framing: this slide is a study of the biomass scripts we were given, to understand them and see how they
would fit, not a feature surfaced in the interface.

Bullet one, what the scripts do: they sample GEDI, foundation 7, pair each shot with the exact Alpha
Earth embedding we already classify on plus slope, and fit a Random Forest that predicts biomass
everywhere from that embedding.

Bullet two, the key finding: biomass is not a new pipeline for us, it is a regression target,
foundation 6, on our own feature space, which is why it slots in naturally, the same features, a
Random Forest regressor, and the same point-grid render a non-linear model uses.

Bullet three: we reproduced the data collection over an area and year, with the same quality, error, and
slope masks, and confirmed it reaches the expected ballpark on the AEZ-8 frame. Biomass from an annual embedding
is inherently noisy, so a strict region-held-out test scores modestly, which is the honest number; a
plain random split flatters it.

Bullet four: it is kept out of the interface for now, and a biomass layer can be enabled later once we
know how it should appear in the LULC.

### Slide 7, segmenting the mining class (an interim)
Bullet one: mining is a per-pixel class, so it shows as scattered pixels. The ask was mining as discrete
objects.

Bullet two, said plainly: this is not the object-detection model intended for this. A real one needs
imagery, mask labels, and GPU we have not wired up, and a render path outside Earth Engine. We did the
interim for two concrete reasons: it reuses the existing tile path with no new infrastructure, and it
turns the classifier we already have into usable objects today. So we vectorise the mining prediction
inside Earth Engine: clean the speckle, close pin-holes, trace connected regions into polygons, and
drop anything below a minimum area.

Bullet three: the result is clean mining polygons, each with an area, downloadable as GeoJSON, instead
of pixel confetti. Over a real active coalfield (Jharia) it returns genuine mining objects; over a
reclaimed site (Asola) the few polygons are false positives, so we demo on Jharia. The learned
object-detection model is the real next step, not this.

### Slide 8, water step one, robustness
The framing first: the plan is two steps. First get water against non-water working and see the
accuracy, then decide how to fold it into the LULC. This slide is step one.

Bullet one: we hold out whole water bodies for a spatial test, whole years for a temporal test, and the
combination for the honest worst case, foundation 8. The seasonal-water polygons already carry a
water-body identity and a date, so this needs no new data.

Bullet two: the within-water-body task is strong and stable. The combined spatial-and-temporal hold-out
scores about 0.98, and the year-to-year spread is small, so there is no fluke year.

Bullet three: this answers the step-one question, the classifier is solid enough within water bodies to
build on.

### Slide 9, water step one, works anywhere, and counting fortnights
Bullet one: the catch is that the non-water examples all come from in and around water bodies, so the
model has never seen ordinary dry land and over-calls water there. We augment the non-water class with
barren, built-up, and greenery pixels sampled across seasons.

Bullet two: the effect is exactly as hoped, non-water precision rises from about 0.72 to 0.99, so the
model stops painting dry land as water. This augmented, works-anywhere model is now the deployed one.

Bullet three: we also run the classifier over a whole year of fortnights and count, per pixel, how many
fortnights it held water. A perennial body scores high, a monsoon-only pond scores low. This is the
layer that would let the LULC tell perennial from seasonal water, the kind of seasonal water the
IndiaSAT map is specifically built to catch and Dynamic World misses.

Bullet four: folding water into the hierarchy, running it first and splitting the non-water, is the
step-two decision this first step sets up.

### Slide 10, acacia, measuring spatial and temporal robustness
The framing to lead with: this slide is about the measurement method, not a headline accuracy. Acacia
against non-acacia is a genuinely hard split, telling two similar tree species apart, so the absolute
numbers are modest by nature. What is new and useful is that the crowns now carry their source region,
so for the first time we can hold out a whole region and whole years at the same time.

The table (pooling three train years, testing two unseen years, with ten pixels per crown): unseen
years only gives 0.749; an unseen region only gives 0.695; an unseen region and unseen years together
gives 0.679.

The reading: the ordering is exactly what an honest test should show — a whole region is harder than
random polygons, and region and year together is hardest. That gap is the point of the slide: it
quantifies how much a single-site, single-year acacia number would over-promise. So the takeaway is not
"acacia is 0.68", it is "here is a way to measure whether an acacia model will travel". And across the
two test years the accuracy is stable (spread about 0.002), so there is no fluke year — the split
generalises consistently, just at a modest level because it is a hard species distinction. (An earlier,
smaller run with fewer pixels per crown looked like it had a fluke year; more pixels showed that was
sampling noise, not a real one.)

### Slide 11, how long does Tessera take, against Alpha Earth
Measured live over one small site, four stages each. Download: Tessera pulls about a hundred and fifty
megabytes per tile, around twenty nine seconds; Alpha Earth downloads nothing. Sample: 31 seconds
against 4. Train: under a second either way once features are in hand. Classify: 40 seconds on the
Tessera point grid against 8 for Alpha Earth tiles. Totals, about 72 seconds against about 12.

The reading: Alpha Earth is server-side round-trips only. Tessera pays a large per-tile download before
anything starts, then samples and classifies locally on a grid. So Alpha Earth wins on first touch
anywhere; Tessera is worth it only when you need its local features and have already paid the download.

### Slide 12, STACD provenance for every output
The framing: this is a claim of work done, not a re-explanation of STACD. STACD provenance was
implemented for every classified output, following the paper's five classes. (The two STACD slides
from the earlier draft are merged into this one.)

Bullet one: every classified output emits two things — a stack specification, a STAC Item for the
raster with its box, geometry, class legend, and asset links; and a STACD specification, the dependency
graph with a dataset and algorithm node per input, one algorithm instance for each live model, rule,
and merge, and the output dataset instance. Everything is read from metadata we already keep (the
trained models' class lists, the zoo cards), so there is no new source of truth and no Earth-Engine run.

Bullet two: the class hierarchy and the ordered operations that built it are embedded as the producing
algorithm's input set — the literal record of what produced this output. Concretely: the legend comes
from the model class lists folded through the merges; each resolving node (model, rule, merge) becomes
an algorithm instance with a version and a pointer to its artifact, code, and card; the input datasets
are the Alpha Earth source plus every training dataset any live model consumed.

Bullet three, following the paper closely: each algorithm instance carries a unique identifier, and the
output points at a producing instance rather than a type. Two naming choices are noted for the paper's
authors, Saharsh and Saurabh, to confirm.

Bullet four: we emit the metadata half of STACD. The paper's Airflow runtime, with selective
recomputation and an instance database, is the natural next layer. The record lines up with the drone
and bioacoustics outputs the group already produces, so it can be compared across the projects.

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
