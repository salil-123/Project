# Week 8: slide-by-slide explainer

The companion to `slides_week8.tex` / `slides_week8.pdf`. It explains every slide in plain language,
defines the new terms and concepts, and ends with the questions that are likely to come up (with
answers). For the hands-on click-through, see `demo.md`.

Week 8 delivered the 26 instruction points in three blocks: UX (2 to 11), views and zoo (12 to 15),
and abilities and docs (16 to 27). The build logs are in `week8/plan.md`; the running record is
`master_document.md`.

---

## Foundations: things to know cold

1. Alpha Earth vs Tessera (two embeddings). Every point on the map is turned into a vector of numbers
   (an embedding) that summarises what the satellite sees there. Alpha Earth is a 64-d embedding served
   inside Earth Engine (server-side, free, India-wide, 2017 to 2024). Tessera is a 128-d embedding you
   download as tiles (per 0.1 degree grid cell). We classify the embedding, never the raw imagery.

2. Band math vs point-grid (why the model type matters for the map). A linear model
   (`StandardScaler` then `LinearSVC` / `LogisticRegression` / `RidgeClassifier`) is just
   `weights . features + bias`. Because Alpha Earth lives in Earth Engine as a 64-band image, that
   arithmetic can be replayed inside Earth Engine as band math, so the whole area classifies
   server-side and comes back as crisp map tiles with nothing downloaded. Anything that is not
   linear-on-Alpha-Earth (a tree model, or any Tessera model) cannot be replayed that way; it runs on a
   point-grid instead (sample N by N points, predict each), which is slower and needs downloads.

3. Spatial diversity and coverage. Spatial diversity is the Shannon entropy of where the labelled
   polygons fall on a grid, normalised to the range 0 to 1: 1 is well spread, 0 is all in one place. It
   matters because a model trained on data from one spot generalises badly (our week-2
   generalization-gap finding). Coverage is labelled-area divided by area-to-classify, i.e. how much of
   the current area actually has training data.

4. The bake-off. Instead of hand-picking a classifier, train several and keep the most accurate on
   held-out polygons. We keep the field linear so the winner still rides the crisp tile map.

5. GeoTIFF. A georeferenced raster image (pixels carry real-world coordinates). We export the
   classified area as one band of integer class codes at 10 m, openable in QGIS.

6. Project-as-JSON. Save the whole session (scheme, the sequence of steps, the area, year, base) as a
   single JSON that references datasets and models by link rather than copying them, then reload it to
   resume. This is the QGIS-on-the-web style of a project file that sir suggested.

Facts to have ready:
- The bake-off on acacia / non-acacia: LinearSVC 0.703, LogReg 0.692, Ridge 0.731 (winner). All are
  linear, all render as tiles.
- Tessera acacia / non-acacia on the Delhi site: about 0.73 held-out. The seasonal-water dataset is
  876 polygons (720 water, 156 non-water), spread 0.61.

---

## Slide 1: Title
Framing: week 8 turns a working classifier into a product: a UI that explains itself, a zoo you can
read, and outputs you can carry away.

## Slide 2: Where we are, and what week 8 tackled
The point: 26 points, grouped. Roughly half are UX and explainability ("only show what fits the flow",
"chart the pipeline"), a quarter are zoo honesty (standard classes, cross-references, selective
publish), and the rest are new abilities (Tessera training, bake-off, GeoTIFF, project save) and
operational answers (schemas, deployment, running Tessera with joblib). We shipped them in three
blocks.

## Slide 3: A workbench that explains itself
The point: the single crowded sidebar became two panels. Left is navigation. Right is contextual: it
names the class you clicked and shows only the actions that make sense, in a natural order. The advanced
training knobs (balancing, multi-year) show only when you are training your own split (12). There are
now two views of the same scheme, the class tree and the ordered sequence of steps that built it (13);
clicking a step selects that class. You draw the AOI on the map (rectangle or click-to-centre with a
slider), the overlay is clipped to the box (3), and it can be hidden with an eye toggle (21). Moving to
a new area offers a clean reset (5), confirmed first.

## Slide 4: Model zoo improvements
The point: four honesty fixes. Every trained model is a card; we fixed the old case where re-splitting a
node dropped its old model, so nothing trained goes missing, and any card can be deleted (9). Small
cards show the standard class name when the uploader mapped it, detail shows the uploader's own name and
the standard it maps to (14). Dataset cards list which models use them, so provenance runs both
directions (15). Selective publish lets you tick and publish just the cards you choose (25).

## Slide 5: Auto model bake-off
The point: "Auto" trains LinearSVC, LogisticRegression, and Ridge and keeps the best by held-out
accuracy (17). We deliberately stay linear so the winner still renders as crisp tiles; a non-linear
winner would be more accurate sometimes but could not ride the tile map. The card records which model
won; the band-math renderer was generalised to read the coefficients and intercept from any linear
estimator (Ridge's binary coefficients are 1-D, so we normalise them).

## Slide 6: Tessera as a training embedding
The point: you can train a split on Tessera (128-d) instead of Alpha Earth, the acacia / non-acacia case
the user asked for (16). We scope it to the four requested ROIs, because those are the boxes that were
approved for coverage, so the multi-year Tessera data exists only there. It trains, scores (about 0.73
on Delhi), and cards like any model, but it cannot ride the crisp tile map (Tessera is a point download,
not an Earth-Engine image), so it is evaluated and point-grid-previewed, and the card is flagged not
expressible as band math. The four ROIs were approved for 2017 to 2025, so multi-year Tessera is
available per site.

what does it mean to not be to ride the crisp tile map? I do understand that you would have to download each tessera pixel one by one and then process it locally instead of the earth engine.

## Slide 7: Portable outputs
The point: two ways to take the work with you. GeoTIFF (24): the classified area as an integer-class
raster at 10 m, with a legend, for QGIS. Project save and resume (18, 23): one JSON holding the scheme,
the sequence, and area / year / base, with datasets and models as links; reload to resume.

what is a raster can you remind me? how does this geotiff look fundamentally?

## Slide 8: New ground truth: seasonal water
The point: we downloaded a set of water and non-water polygons (27) and folded them into the zoo as a
dataset card: 876 polygons, water vs non-water by date, spread 0.61. The naming
`<id><W|NW><DDMMYYYY>` encodes the seasonal (present or absent by date) signal. It seeds a future
seasonal-water split.

## Slide 9: Deploying this on a server
The point: the operational answer (26). See the deployment question below for the full version.

give me detailed short explanation on why each of the things is required like why is python required why is uvicorn required so and so forth

## Slide 10: Thank you
Pointers to this explainer and to `demo.md`.

---

## Deep-dives: likely questions

### Q1. (22) For Tessera we need local training and running. How is that handled with joblib files?
Cleanly, because a trained model is always just a scikit-learn pipeline pickled with joblib, independent
of which embedding produced its features. Concretely:
- Sampling. For a Tessera split we sample the 128-d Tessera vector at each training point
  (`sampling.sample_tessera`, columns `te_000` to `te_127`); Tessera tiles download to a local cache
  (`global_0.1_degree_representation/<year>/...npy`, handled by `tessera_fast.py`).
- Training. The same trainer fits `StandardScaler` then a linear model on those 128 columns and dumps a
  bundle: `joblib.dump({"model": pipeline, "classes": [...], "features": "tessera", "algo": ...,
  "report": ...})`. The only difference from an Alpha-Earth model is `features: "tessera"` and the
  128-wide coefficients.
- Running locally. Load the joblib, sample Tessera at your inference points, call
  `bundle["model"].predict(Xte)`. That is the point-grid path; it needs the local `.npy` tiles, not
  Earth Engine.
- Why not on the tile map. The crisp tile map is Earth-Engine band math on the Alpha-Earth image. There
  is no Tessera image in Earth Engine, so a `features: "tessera"` bundle is skipped by the tile renderer
  (its card says not expressible as band math). So: local training and local running for Tessera; the
  joblib is the same kind of file, just tagged with its embedding and carrying 128-d weights.

### Q2. (26) To install this on a server, what config and access is needed? GitHub env? EE auth key?
- Runtime: a Python virtual environment from `requirements.txt`; run `uvicorn backend:app --app-dir
  src`. State is files (hierarchy JSON, cards, joblibs), no database.
- Earth Engine: the app calls `ee.Initialize(project=EE_PROJECT)` and relies on the runtime user's Earth
  Engine credentials, i.e. run `earthengine authenticate` once on the machine (it caches a token). There
  is no service-account key in the code today; for a headless server the clean next step is a
  service-account JSON. `EE_PROJECT` and `EE_USER_ID` come from `.env`.
- GitHub (publishing the zoo): `data/catalogue/` is its own git repo; publishing runs git add, commit,
  push to `ZOO_REMOTE`. Git authentication is delegated to the system, so provision a Personal Access
  Token through a git credential helper (for an HTTPS remote) or an SSH deploy key; the app only
  supplies the URL. If `ZOO_REMOTE` is unset it just commits locally.
- `.env` variables: `EE_PROJECT`, `EE_USER_ID`, `ZOO_REMOTE`. Committed joblibs let a fresh clone
  classify immediately.
- Still open: a Dockerfile and the service-account key for a fully hands-off box.

### Q3. Why keep the bake-off linear? Would not RandomForest or xgboost be more accurate?
Sometimes, yes, but only a linear model replays as Earth-Engine band math, so a non-linear winner would
drop the whole area onto the slow point-grid render and lose the crisp tile map. The ask was to do the
bake-off if feasible with linear models, so we bake off linear candidates only; the winner is
transparent to the map. (xgboost also is not installed; RandomForest and HistGradientBoosting are, but
they are non-linear.)

### Q4. Is the Tessera model as good as Alpha Earth here?
On the Delhi acacia / non-acacia split they are comparable (about 0.73 each held-out). Tessera's promise
is richer detail and multi-year coverage (2017 to 2025) for our sites; the trade-off is download cost
and that it cannot ride the crisp tile map. We scoped it to the four approved sites deliberately.

### Q5. Save "the sequence, not a log". What is the difference?
A log is an ever-growing record of everything ever done; a sequence is the ordered set of steps that
define the current scheme. Export is now session-scoped (only this session's steps) and wrapped as a
project (scheme, sequence, and area / year / base, datasets as links). It is a recipe you can replay and
resume, not an audit log.

### Q6. If two models map their classes to the same standard class, does the zoo know?
The crosswalk is per produced class, so yes: the small card can show "Tree cover" for both an acacia
model and a tree model, while each detail pane keeps the uploader's own name. That is the point of 14:
browse by a shared vocabulary, drill in for the author's intent.

### Q7. Can the seasonal-water data train a model now?
The dataset card is in the zoo (876 polygons, water and non-water). A split is a follow-up: the naming
carries the date, so it can seed a genuinely seasonal (by-date) water model. That is on the roadmap, not
built this week.

### Q8. What happens to a Tessera or non-linear split when I just hit "Run"?
The tile map renders the base and all Alpha-Earth linear splits crisply; a Tessera (or any
non-band-math) split is skipped there and that class shows its parent label. The Tessera split still
exists as a scored card; a point-grid preview render for it is the next step.

### Q9. Is the project file portable across machines?
Yes for the scheme and area / year / base. Trained artifacts ride as links (joblib paths and card ids),
so a machine that has the zoo (or can pull it) rebinds them; anything missing is reported as needing
retraining. The file stays small and shareable.
