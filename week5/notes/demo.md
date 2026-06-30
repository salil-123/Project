# Week 5 — presentation & demo script

A talk track for tomorrow. Slides are `week5/slides_week5.pdf`. Times are rough (≈10 min talk
+ 5 min live demo). Deep explanations of every point are in `deep_dive.md`.

---

## The one-line story
> Week 4 we *designed* model & dataset cards on paper. Week 5 we **converted the design into code**:
> a git-backed database the tool writes to on every retrain, and you can browse, apply, publish, and
> pick a model for your area, all from the UI.

---

## Slide-by-slide talk track

1. **Title.**

2. **Where we are / what was advised.** "We had the base map and the living hierarchy, and last
   week a *paper* schema. The asks this week: convert the design into code — a database of all the
   cards; give datasets a *type* (training vs inference); have the model card point to both; keep
   extent a simple bounding box; and try splitting trees into tea/non-tea." (Week-4-style framing.)

3. **From design to a running database.** "Four pieces: the schemas, a catalogue module that *is*
   the database, a git layer, and the backend+UI. Nothing is invented — every card field comes from
   something we already produce."

4. **The pipeline.** "When you retrain a node, we mint its cards, write them under `data/catalogue/`,
   and publishing pushes them to GitHub. Minting is local and offline; git is a separate step; only
   the JSON cards are tracked — the .joblib models stay local."

5. **The week-5 change.** "A *training* dataset is the labels a model learned from. An *inference*
   dataset is the feature space it runs on — Alpha Earth, 64-d. A model links to both, so it's clear
   what it was taught and what inputs it needs. The inference dataset is shared across all models."

6. **The database is GitHub.** "The catalogue folder is a git repo of a shared zoo — same idea as
   Hugging Face. Publish = commit + push. Only the JSON cards are committed; the model binaries stay
   local. It's live — cards push to a real repo."

7. **Browse + pick for your area.** "The catalogue answers queries: list everything, or just the
   models that cover your bounding box. And the extent fix: a country-wide model shows a *label*, not
   a giant box — the box is drawn only for genuinely localized models."

8. **Serving = Earth Engine tiles.** "Realistic mode is served as EE map tiles, not a PNG — the
   linear model replays as band math in EE, so we classify at 10 m on the server and hand Leaflet a
   tile URL. Crisp at any zoom, any area, nothing downloaded. That's the 'tile URL' ask."

9. **The full-screen Model Zoo.** "A dedicated browser: tabs for models/datasets, a card grid, a
   detail pane with metrics + the linked training/inference datasets as clickable chips, and a
   publish button. The map stays the default screen; the zoo opens only when asked."

10. **Describe it, prove it, map it.** "A model card isn't just metrics — the user adds a
    description, intended use, limitations, and *evidence* (how the classes were annotated), and can
    map each class to a standard scheme (WorldCover/USDA). That's the 'model cards in ML' ask."

11. **Quality feedback & balancing.** "Two guards: the spatial-diversity *spread* (entropy) flags a
    clustered dataset before it skews a model; the *class-balance* ratio flags skew and lets the user
    retrain with under/oversampling. The chosen policy is recorded on the card."

12. **Tea / non-tea: a separability check.** "Tried the suggested tea/non-tea split — first, does
    Alpha Earth even separate them? Sampled 169 hand-marked polygons, held out whole polygons: 0.934
    held-out accuracy. It separates cleanly, so a real split with its own cards is a natural next step."

13. **What's in the catalogue.** "What's available: the base map + greenery and barren splits, and
    their datasets (training polygon sets, pixel tables, WorldCover slices, and the shared inference
    source). 11 cards, all validating, pushed to GitHub."  **Thank you.**

---

## Live demo (every feature, in order)

Start the server: `.venv/Scripts/python -m uvicorn backend:app --reload --app-dir src`, open
http://127.0.0.1:8000/ and hard-refresh (`Ctrl+F5`). The base map is the 4 classes
(greenery / water / built-up / barren).

### A. Classify on the map, served as Earth Engine tiles
1. **Area** = "Pune (mixed)" (or IIT Bombay) → **Run classification** (Realistic) → colored overlay.
2. **Zoom in.** It stays crisp because it's EE *map tiles* (band-math on the server), not a capped
   PNG. Nothing is downloaded. This is the tile-URL path.
3. *(Optional)* switch **Mode = Detailed** → AE + Tessera cell grid, then switch back to Realistic.

### B. Browse the Model Zoo (the catalogue)
4. **Open Model Zoo** → full-screen browser. Flip the **Models / Datasets** tabs.
5. Click **Barren + mining** (a model card) → its detail shows: the classes it **produces** (colored
   chips), a **per-class metrics** table, the **class-balance** flag, and the linked **training data**
   + **inference features** as chips. Click a training-dataset chip → it jumps to that dataset card
   (the lineage link).
6. Open a **training dataset** (e.g. mining polygons) → the **Spread (spatial diversity)** readout,
   e.g. "0.87 — well spread": the Shannon-entropy feedback that flags a clustered, skew-prone dataset.
7. **Show on map** on that polygon dataset → it draws the actual labelled polygons with **red bubbles**
   so you can see where they are; on the **base map** card it just says "India-wide feature source"
   (nothing meaningful to draw). Close the zoo (`Esc`).
8. Reopen the zoo, pick an **Area** first, then tick **"only for current view"** → the list narrows to
   cards whose extent covers it (datasets too, since polygon datasets have real local extents).
9. **Use a model from the zoo.** On the **Barren + mining** card → **Use this model (apply to map)**.
   It registers on the tree and the map re-classifies to show barren split into barren/mining. To go
   back, open the base map card → **Use base map (reset to 4 classes)**. (This is what makes the zoo
   usable, not just browsable.)

### C. Describe it, prove it, map it
10. On the **Barren + mining** card → **Annotate / evidence / class mapping**:
    - Description: "barren split that carves mining out of bare ground."
    - Evidence: "100 hand-marked mining polygons; drone + field check."
    - Contributor: your name.
    - For **mining**, pick from the dropdowns: WorldCover = "Bare / sparse vegetation (60)"; leave
      USDA as "none" (mapping is **optional** — any subset is fine, you don't have to fill both).
    - **Save** → the prose and a `mining -> worldcover:60` chip appear on the card.
    - *Note for the panel:* the standard mapping is **metadata** — it's stored on the card, shown, and
      published for interoperability. It does **not** change the classification; it's the optional
      crosswalk so localized classes line up with WorldCover / USDA. The classes come from a built-in
      pick-list, so nobody has to memorize codes.

### D. Publish to the GitHub zoo
11. **Publish to zoo** on that card (or **Publish all**) → it commits and pushes. Show it landed:
    `git -C data/catalogue log --oneline` (a new commit on the real `zoo_database` repo). The
    "unpublished" badge clears.

### E. The headline: tea / non-tea split, balancing, and the Assam preset
12. Select **greenery** → Operations → "Split selected leaf into" = `tea, non_tea` → **Create split**
    (tea estates classify as greenery, so we refine greenery here).
13. Select **tea** → upload `week5/sample/tea.geojson` (role positive). Select **non_tea** → upload
    `week5/sample/non_tea.geojson` (role positive).
    - Each upload *immediately* mints/updates that class's **training dataset card** (the status line
      says "dataset card ds_tea_polygons_v1 updated"). Open the **Datasets** tab to see
      `ds_tea_polygons_v1` / `ds_non_tea_polygons_v1` (count, bbox extent, spread) *before* you even
      retrain — adding data builds the dataset catalogue.
14. **Class balance = balanced** → **Retrain selected & apply**. Read the held-out report and the
    class-balance flag on the new card.
15. **Show the balancing remedy:** change only the **Class balance** dropdown and retrain again —
    **oversample the minority** (and/or **undersample the majority**). Compare the per-class recall;
    the card records the chosen policy in `training.balancing`. *(Each retrain samples Earth Engine,
    ~1 min; show balanced vs one oversample run if time is tight.)*
16. Select the **"Assam tea belt (tea/non-tea)"** preset → **Run classification** → the map shows
    **tea vs non-tea** over the belt (15 tea / 9 non-tea ground-truth polygons sit in that box).
17. Reopen the zoo → the greenery card now produces **tea / non_tea**, shows the recorded balancing
    policy, and **Show on map** draws the tea/non-tea polygons (bubbles) in Assam.

### F. The isolated evaluation (optional, CLI)
18. `.venv/Scripts/python week5/tea_eval.py` → **0.934** held-out, writes `week5/notes/tea_eval.md`,
    and changes nothing (it never touches the hierarchy / base / catalogue).

> **Reset after the demo:** the tea split edited the live tree. To go back to the 4-class default:
> `PYTHONPATH=src .venv/Scripts/python -c "import hierarchy; hierarchy.save(hierarchy._seed())"`,
> then restart the server.

---

## Likely questions (one-liners)
- *Why GitHub as the DB?* Cards are small JSON → versioned, diffable, PR-able; publish/share/history
  for free; same as HF's hub. A real DB is a later swap, the card files stay the source of truth.
- *Why two dataset types?* A model is portable: separate what it was *taught* (labels) from what it
  *consumes* (features). You can supply the inference features anywhere the embedding exists.
- *Why is the extent India for everything?* It isn't — for polygon data we draw the actual polygons
  (the real footprint). Only the feature sources (Alpha Earth / Tessera), which genuinely are
  India-wide, show a label instead of a box.
- *Did tea change the base classes?* No — pure measurement, verified `hierarchy.json` byte-identical.
- *PNG or tile URL?* Tiles — Realistic is served as EE map tiles via `getMapId` (the linear model
  replays as band math), so it stays crisp at any zoom with no download. Persisted (non-expiring) EE
  assets are the next step.
- *How does a user "prove" a class?* The annotate editor: description, intended use, limitations, and
  evidence, plus an optional map to a standard scheme (WorldCover/USDA) — saved on the card.
- *What if a split is imbalanced?* The card flags the support ratio; the user can retrain with
  undersampling/oversampling instead of class-weighting, and the choice is recorded on the card.
- *Does the standard-class mapping do anything?* It's **metadata, not a transform** — it's saved on
  the card, shown as a chip, and published, so a localized class (e.g. mining) can be tied to a
  standard code (WorldCover 60). It documents interoperability; it doesn't change classification.
- *Can I actually use a model from the zoo?* Yes — **Use this model (apply to map)** registers it on
  the tree so inference composites it and the map re-classifies; the base map card resets to the 4
  classes. (A split model needs its trained artifact present locally.)

---

## Appendix: oversampling on a real minority (shrubs)

The tea/non-tea split is only mildly skewed, so for a clearer balancing story use **shrubs**, a
genuinely small class (430 labelled points vs crops ~4500, trees ~2300). This runs off
`data/worldcover_train.csv` (the stable WorldCover-labelled table), so there's **no setup, no Earth
Engine, and no change to the live tree** — it just reproduces what the Class-balance dropdown does:

```bash
PYTHONPATH=src .venv/Scripts/python - <<'PY'
import pandas as pd, refine
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
names = {10: "trees", 20: "shrubs", 30: "grass", 40: "crops"}
d = pd.read_csv("data/worldcover_train.csv").dropna(subset=refine.AE_COLS)
d = d[d.wc.isin(names)].copy(); d["label"] = d.wc.map(names)
X = d[refine.AE_COLS].to_numpy(dtype="float64"); y = d["label"].to_numpy()
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=0)
for how in ["balanced", "oversample", "undersample"]:
    cw = None if how in ("oversample", "undersample") else "balanced"
    Xb, yb = refine._rebalance(Xtr, ytr, how)
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight=cw, max_iter=5000)).fit(Xb, yb)
    s = classification_report(yte, m.predict(Xte), output_dict=True, zero_division=0)["shrubs"]
    print(f"{how:11} shrubs  P={s['precision']:.2f}  R={s['recall']:.2f}  F={s['f1-score']:.2f}")
PY
```

Expected (shrubs):

| policy | precision | recall | F1 |
|--|--|--|--|
| balanced (class weight) | 0.47 | 0.77 | **0.58** |
| oversample minority | 0.40 | 0.84 | 0.54 |
| undersample majority | 0.38 | 0.82 | 0.52 |

**Takeaway:** the remedy genuinely moves the minority class. Oversampling/undersampling push shrubs
**recall up** (catch more shrubs) at the cost of **precision** (more false positives), so here
`class_weight=balanced` keeps the best F1, and oversample is the lever when catching every shrub
matters more than precision.

*This is the same effect the **Class balance** dropdown applies during a retrain — the snippet just
shows it on shrubs without needing a live greenery split or Earth Engine.*
