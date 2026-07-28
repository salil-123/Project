# Week 6 — demonstration & verification walkthrough

A hands-on script to **demo** the week-6 work and **verify** every piece yourself. Each
feature has: what to click, what you should see, and (where useful) a one-line check you can
run in a terminal. Slides: `week6/slides_week6.pdf` (point-by-point: `week6/slide_explainer.md`).
Full build log: `week6/plan.md`.

> The features map to `week6_instructions.txt`: base picker (#5), inference-year (#7),
> merge (#9), save/reload (#4), recommendations (#2), spread grid (#1), publish storage +
> contributor + data link (#8, #6), operation log (#11), UI sweep (#3).
>
> **Updated for the current UI** (post-week-6 refinements, see `master_document.md` §5): the base
> picker and the inference year now live in the **Model Zoo** (not the sidebar); merge sources are
> **ticked in the Hierarchy tree**; and publishing no longer pops up prompts (contributor + dataset
> link are set on the cards). The backend/API checks below are unchanged.

---

## 0. Start the tool

```
uvicorn backend:app --reload --app-dir src
```
Open http://127.0.0.1:8000/. On a fresh browser you're greeted by a **"Choose your base classes"**
modal (section 1). Behind it: the map and the left sidebar (Area, Hierarchy, Examples, Operations,
Merge, Save/load, Model Zoo) — no console errors.

> Tip: the base modal appears on **every launch** (a session starts by choosing a base). The current
> scheme is tagged — pick it (or *Keep the current scheme*) to carry on without reseeding. If you
> don't see fresh changes after an edit, hard-refresh (Ctrl+Shift+R) — assets are cache-busted `?v=N`.

Quick API health check (optional):
```
curl -s http://127.0.0.1:8000/api/health
```
Expect `{"status":"ok", "classes":[...], ...}`.

---

## 1. Pick your base classes (#5)

**Do:** on first load the **"Choose your base classes"** modal offers *IndiaSAT (4 classes)* and
*WorldCover (7 classes)*, with the current scheme tagged. Click **WorldCover** and confirm. (Later,
you can switch any time from the **Model Zoo** → Models tab → a base card's *Use … base* button —
see section 6.)

**See:** the Hierarchy panel reseeds to 7 classes (tree, shrubland, grassland, cropland,
built-up, bare, water), then the map auto-classifies as a 7-class WorldCover map. Re-open the base
choice (or the zoo) and pick **IndiaSAT** to restore greenery/water/built-up/barren.

**Note:** switching to a *different* base is deliberately destructive (it clears your splits/merges
and backs the old tree up to `data/hierarchy.prev.json`); picking the current scheme just proceeds.
The WorldCover base uses weak labels, so it is an alternate starting point, not a more accurate one.

**Check:**
```
curl -s http://127.0.0.1:8000/api/base        # active scheme + the two options
```

---

## 2. Pick the inference data / year (#7)

**Do:** open the **Model Zoo** → **Datasets** tab → the *Alpha Earth annual embeddings* card. Its
detail pane has an **Inference year** dropdown — set it to **2024** and close the zoo. In **Area**,
choose a preset (e.g. *Pune (mixed)*), Mode = *Realistic*, click **Run classification**. Then
re-open that card, set the year to **2022**, and run again.

**See:** both runs paint the map; the status line reads `Done: {...}` and the class counts
**differ** between the years (same model, different temporal slice). The picked year is remembered
(`localStorage.inferYear`). In **Detailed** mode the year is ignored and pinned to 2024 (Tessera
coverage).

**Check (counts differ by year):**
```
B="west=73.84&south=18.50&east=73.88&north=18.54"
curl -s "http://127.0.0.1:8000/api/classify?$B&mode=realistic&year=2024" | python -c "import sys,json;print('2024',json.load(sys.stdin)['counts'])"
curl -s "http://127.0.0.1:8000/api/classify?$B&mode=realistic&year=2022" | python -c "import sys,json;print('2022',json.load(sys.stdin)['counts'])"
```

---

## 3. Merge classes across models (#9)

**Setup:** make sure you are on the IndiaSAT base with the demo splits (greenery to tea/non-tea,
barren to mining). If not, the *Assam tea belt* preset and the existing splits are the easiest.

**Do:** in the **Hierarchy** tree, tick the checkbox on two leaves from **different** splits, e.g.
`tea` and `mining`. Then in **Merge classes** type a name (e.g. `extractive`), pick a colour, and
click **Create merge**.

**See:** the map re-renders; the merged class appears in the counts with its colour, and the
source classes disappear (they were relabelled). On the **Hierarchy tree** the two source leaves
now show a coloured `→ extractive` tag, and a **Merges (cross-model)** virtual node appears with an
`✕` to undo it (which brings the originals back). The merge also mints a **local model card**
`mc_merge_extractive_v1` — open the **Model Zoo** → Models tab to see it (topology `merge_relabel`,
no trained artifact), and the badge shows `1 unpublished`.

**Check (the merge is exact: tea + mining counts collapse into the target):**
```
curl -s -X POST http://127.0.0.1:8000/api/merge -H "Content-Type: application/json" \
  -d '{"name":"extractive","sources":["tea","mining"],"color":"#8e44ad"}' >/dev/null
curl -s "http://127.0.0.1:8000/api/classify?$B&mode=realistic&year=2024" | python -c "import sys,json;c=json.load(sys.stdin)['counts'];print('extractive=',c.get('extractive'),'| tea/mining gone:', 'tea' not in c and 'mining' not in c)"
# the merge produced a local model card:
curl -s http://127.0.0.1:8000/api/cards/mc_merge_extractive_v1 | python -c "import sys,json;d=json.load(sys.stdin);print('card topology:',d['topology'],'| produces:',[p['class'] for p in d['produces']])"
curl -s -X DELETE http://127.0.0.1:8000/api/merge/extractive >/dev/null   # clean up (also deletes the card)
```

---

## 4. Save and reload your scheme (#4)

**Do:** in **Save / load scheme**, click **Download hierarchy (JSON)** (saves `hierarchy.json`
to your downloads). Now change the tree (e.g. switch base, or add a class). Then use **load a
saved hierarchy** to upload the file you saved.

**See:** the tree returns to exactly what you saved; the map re-classifies. If any split's
trained model is missing, the status line names it so you know to retrain. The file is
self-describing JSON (the tree + the ordered operations) and needs no login.

**Check (round-trips identically):**
```
curl -s http://127.0.0.1:8000/api/hierarchy/export > /tmp/h.json
python -c "import json;print('keys',list(json.load(open('/tmp/h.json')).keys()))"
curl -s -X POST http://127.0.0.1:8000/api/hierarchy/import -H "Content-Type: application/json" --data @/tmp/h.json | python -c "import sys,json;d=json.load(sys.stdin);print('imported, missing splits:',d['missing_classifiers'])"
```

---

## 5. Recommendations + adjustable spread grid (#2, #1)

**Do (recommendations):** open the **Model Zoo**, click a split model (e.g. the greenery
split). In the detail pane, look at **Suggested placement**.

**See:** something like *Apply after Greenery* (and a WorldCover hint if that class was mapped
to a WorldCover class via Annotate). Base models read *Base map: the starting point*. Model
tiles also show a compact `after <node>` hint.

**Do (spread grid):** in the Zoo, open the **Datasets** tab, click a polygon dataset (e.g.
crops). Find **Spread (spatial diversity)** and change the **grid cell** dropdown.

**See:** the diversity number and the occupied-cell count recompute for the chosen grid size
(finer grid, more cells, usually higher spread).

**Check:**
```
curl -s http://127.0.0.1:8000/api/cards/mc_greenery_v1 | python -c "import sys,json;print('rec',json.load(sys.stdin)['recommendation'])"
curl -s "http://127.0.0.1:8000/api/cards/ds_crops_polygons_v1/spread?cell=0.1" 
curl -s "http://127.0.0.1:8000/api/cards/ds_crops_polygons_v1/spread?cell=1.0"
```

---

## 6. Base options visible in the zoo (#5 + zoo)

**Do:** open the **Model Zoo**, **Models** tab.

**See:** four model cards, including the **WorldCover base** and the **Core Stack base
map** (IndiaSAT). Opening the WorldCover card shows a *Use WorldCover base (7 classes)* button;
the IndiaSAT card shows *Use IndiaSAT base (4 classes)*. Either one switches the live base.

**Check:**
```
curl -s http://127.0.0.1:8000/api/catalogue | python -c "import sys,json;print([c['id'] for c in json.load(sys.stdin)['cards'] if c['kind']=='model'])"
```
Expect `mc_barren_v1, mc_greenery_v1, mc_root_v1, mc_worldcover_base_v1` (plus any `mc_merge_*`
card if a merge from section 3 is currently active).

---

## 7. Publish: model stored, contributor, data link (#8, #6)

> Publishing pushes to the shared GitHub zoo. Demo this only when you actually intend to share.

**No popups anymore** — the contributor and the dataset link are set on the cards beforehand:

- **Contributor (#6):** open a model card → **Annotate / evidence / class mapping** → fill the
  **Contributor** field (GitHub handle / email) → **Save annotation**. It's remembered
  (`localStorage.contributor`) and used silently on every later publish.
- **Dataset link (#8b):** open a training **dataset** card → in **Public source link**, paste the
  URL it came from (leave blank to keep it private) → **Save link**. It shows as **Public source**
  on the card.

**Do:** open a model card in the Zoo, click **Publish to zoo** (it just publishes — no prompts).

**See:** the card shows as *published*, with your saved handle as the contributor. Behind the
scenes the model's `.joblib` is committed into the zoo's `artifacts/` folder, while raw private
uploads (datasets with no link) are never pushed.

**Verify the storage choices (no push needed to read these):**
- `data/catalogue/.gitignore` keeps `artifacts/*.joblib` but drops `*.csv` / `*.npy`.
- after a publish, `data/catalogue/artifacts/<card_id>.joblib` exists and the card carries
  `artifact.published_path`.

---

## 8. Operation log + UI sweep (#11, #3)

**Operation log:** every tree-mutating action (split, add, retrain, apply, merge, base switch)
is appended in order to `data/op_log.json`, and travels inside the saved hierarchy so a result
is reproducible.
```
python -c "import json;[print(e['seq'],e['op'],e['args']) for e in json.load(open('data/op_log.json'))]"
```

**UI sweep:** click through every panel; the zoo shows all models in both tabs, the detail-pane
buttons (Use, Publish, Annotate, Show on map) all respond, and the relocated controls work — the
base modal / base cards, the inference-year on the Alpha Earth card, and tree-based merge selection.
The zoo badge now counts actual **cards** (a dirty `index.json` no longer misreads as
"1 unpublished"). A merge card hides the *Use* button (it's already live as a relabel layer).

---

## 9. One-shot sanity (no browser)

```
python schema/validate.py        # all cards valid
python src/oplog.py              # op-log smoke test
python src/merges.py             # merge-rules smoke test
python src/catalogue.py          # catalogue backfill + AOI query
```
All should print OK / PASS.

---

## What is deliberately not built
- **#10** (can split+merge express any decision tree?) is a thought experiment, noted for later.
- A deeper, separate code-optimization pass beyond this week's dedup is left for an explicit round.
