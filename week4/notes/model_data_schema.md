# Model & Dataset Card schema — design of record (week 4)

The schema for the LULC **model zoo + dataset catalogue**. Design/research only; this note
is the spec the slides summarize. Everything here extends artifacts we already ship — it
doesn't replace them.

Two first-class objects, plus a thin spine and a registry:
- **Dataset Card** — a labeled *source* (polygons, an EE asset, or an embedding table),
  with spatial/temporal extent, provenance/evidence, and quality stats.
- **Model Card** — a *classifier* at one hierarchy node: the classes it emits, the datasets
  it trained on, where it's valid, its metrics, and how it deploys.
- **Canonical taxonomy** — the existing 4-class spine; cards point into it (see
  `taxonomy_crosswalk.md`).
- **Catalogue** — flat JSON registry of cards + an index, queried to pick a model for an area.

---

## 0. Why these two objects (the asks behind them)

`instructions_week4.txt` repeatedly circles the same need: many small, *localized* models
people can browse and reuse (#3–#5), each carrying enough metadata to say **where it's
valid** (#4, #7), **what it emits** (#1), **what it learned from** (#5, #16), and **how the
classes were annotated / what evidence backs them** (#8 — explicitly "model cards in ML",
#9 — "build a schema for model cards LULC"). Datasets need the same treatment (#16–#18):
defined by a polygon *or* an EE asset, valid over some spatial+temporal extent, with quality
metrics (#19). So: a Model Card and a Dataset Card, linked by lineage.

---

## 1. Grounding — what already exists maps cleanly onto the cards

We are not starting from zero. Today's files already hold most of these fields implicitly:

| Today's artifact | Becomes | Field lift |
|--|--|--|
| `data/hierarchy.json` node (`class,name,parent,color,classifier,children,source`) | the **canonical spine**; cards reference node ids | add optional `std_mapping` per node |
| `data/refine/<node>.joblib` (`model,classes,features,parent,report,n_test`) | a **Model Card** | `report`→`metrics`, `parent`→`parent_class`, path→`artifact.path` |
| `data/model_pooled.joblib` (`+wc_weight,note`) | the **base** Model Card (`mc_base_pooled_v1`) | `wc_weight`→`training.balancing` |
| `data/examples/<node>.geojson` (props `node,role,name,ts`) | a **Dataset Card**, `kind:"polygons"` | provenance already partly there |
| `worldcover_train.csv` (filtered by `wc` code) | a **Dataset Card**, `kind:"ee_asset"` | the WorldCover slice the demo uses for shrubs |
| `master_alpha_full.csv` (filtered by `core_class`) | a **Dataset Card**, `kind:"embedding_table"` | the expert base pixels |
| node `source` field (`examples`/`worldcover`/`residual`) | **proto** dataset reference | generalize into dataset `id`s in `training.datasets` |
| `week3/notes/classifier_topology.md` (per-node) | Model Card `topology` enum | default `per_node_split` |

**Takeaway for the slides:** the cards are a *thin formalization* of metadata we already
generate — migration is mostly "write what we know into JSON," not a rebuild.

---

## 2. Canonical taxonomy + crosswalk (the spine)

- Spine = the 4 base classes and their descendants in `hierarchy.json`
  (greenery / water / built_up / barren). Every model attaches at a base node via
  `parent_class`; the root base map is itself a model (`mc_base_pooled_v1`).
- External standards (WorldCover / USDA / IUCN) are **not** part of the backbone. They surface
  **only at retraining time**, as an optional `std_mapping` a user can attach to a leaf
  (`{"worldcover":40,"usda":"Cropland","iucn":"T7.1"}`) — see `taxonomy_crosswalk.md`.
- The tree is **extensible at every level, including root**: a user can split a class, add a
  class under any node, or **add a new base class** under root (which retrains the base map via
  `refine.retrain_base`). The 4 classes are the *starting* spine, not a hard ceiling.
- This answers the wetland/bamboo question (#13): a new class **usually** maps into our
  taxonomy where it fits (e.g. "wetland in Sanjay Gandhi" under water), which keeps models
  comparable; if it genuinely doesn't fit, it can be a new base class. The external
  `std_mapping` is optional sugar for interoperability, never required up front (#14, #15).

---

## 3. Dataset Card schema

A dataset is a labeled source for one or more classes, plus the metadata that says where and
when it's valid and how trustworthy it is.

```jsonc
{
  "id": "ds_farmforest_crops_v1",          // stable id; v<n> bumped on redefinition
  "name": "FarmForest expert cropland polygons",
  "description": "Expert-delineated cropland parcels used as crop positives.",  // #8 'describe it'
  "kind": "polygons | ee_asset | embedding_table",
  "classes": [ {"class":"crops","name":"Crops","count":110,
                "description":"irrigated + rain-fed agricultural parcels"} ],   // per-class desc (#8)

  "definition": {                          // HOW samples are obtained — the two ways (#17)
    "type": "polygons",  "path": "data/examples/crops.geojson"
    // OR  "type":"ee_asset",       "asset":"ESA/WorldCover/v200","band":"Map","code":20
    // OR  "type":"embedding_table","path":"data/master_alpha_full.csv","filter":{"core_class":"barren"}
  },

  "extent": {                              // typed, multi-form (#18) — see §6
    "spatial":  {"type":"region","value":"India"},
    "temporal": {"year":2024}
  },

  "embedding": {"source":"alphaearth","dim":64,"year":2024},  // embedding space samples live in

  "provenance": {                          // the "data card" evidence (#16, #8)
    "annotator":"FarmForest expert team",
    "method":"expert field delineation",
    "evidence":["drone imagery over IIT plots","ground photos"],
    "license":null, "notes":""
  },

  "quality": {                             // #19
    "n_polygons":110, "occupied_cells":77,
    "spatial_diversity":0.889,             // entropy of sample locations over a grid (§7)
    "class_balance":{"crops":1.0}
  },

  "version":1, "created":"2026-06-13T00:00:00Z"
}
```

**Notes**
- **`description` is first-class** (#8): one line for the dataset, plus an optional line per
  class — "what is this, in words." Together with `provenance` (who annotated it, how, with
  what evidence) this is the *data card* the instructions ask for.
- `kind` + `definition.type` are kept separate on purpose: `kind` is the headline ("these are
  polygons"), `definition` is the machine recipe to fetch rows. A future loader dispatches on
  `definition.type` exactly like `refine._child_frame` already dispatches on `source.type`.
- Negative-example datasets are just a Dataset Card whose rows carry `role:"negative"`; the
  positive/negative panel the instructions want (#17) is two dataset references on a model.

---

## 3b. Standard dataset library — offered, not searched (#15, #17)

The instructions float two ways to get standard data: *"pull in USDA / IUCN"* and *"pick the
barren class of WorldCover."* **Decision: we curate a small library of standard datasets /
assets and offer them in the picker — we do not crawl the web.** Why: provenance and quality
stay controlled, the assets are EE-native (so sampling is reproducible), and a Dataset Card
can be written once and reused. The library is just pre-written Dataset Cards of
`kind:"ee_asset"`, e.g.:

- **ESA WorldCover v200** — per-class slices (cropland 40, tree 10, shrub 20, water 80, …).
- **USDA / IUCN** — primarily *class-reference* tables for the crosswalk (`std_mapping`); any
  that exist as samplable rasters get an `ee_asset` card too.

A user picks "WorldCover → barren (60), my AOI, 2021" and that becomes a dataset reference on
their model. *Live online dataset search is explicitly out of scope (future work).*

## 3c. Dataset selection / preferences panel (#16, #17)

How a user assembles training data for a retrain — the schema-level view of the UI panel:

- **Source rows**: the user's own polygons (drawn/uploaded → a `polygons` card) **and** any
  cards from the standard library (§3b). Each is tagged **positive** or **negative** per class.
- **Select / unselect** datasets freely (the panel lists them with their class + counts).
- **Spatial filter**: "sample only within my area of interest" → intersect the chosen
  datasets' geometries with the AOI before sampling.
- **Temporal filter**: "sample only year X" → set the sampling `year` (drives the embedding
  year too).
- The resulting selection is recorded on the Model Card as `training.datasets` (the ids) plus
  a `training.selection` block capturing the AOI + year filters actually applied, so a retrain
  is reproducible.

```jsonc
"training": {
  "datasets": ["ds_farmforest_crops_v1", "ds_worldcover_shrubs_v1"],   // chosen cards
  "selection": { "aoi": {"type":"polygon","geojson":{}}, "year": 2024,  // panel filters (#16)
                 "roles": {"ds_farmforest_crops_v1":"positive"} }
}
```

---

## 4. Model Card schema

A model is a classifier at one node: what it emits, what it trained on, where it's valid, how
good it is, and how it deploys.

```jsonc
{
  "id": "mc_greenery_split_v1",
  "name": "Greenery → crops / trees / shrubs (India)",

  "node": "greenery", "parent_class": "greenery",   // node it resolves + spine attach (#14)
  "topology": "per_node_split | base_pooled | flat_multiclass",

  "produces": [                                     // the legend it emits (#1) + crosswalk (#13-15)
    {"class":"crops",  "std_mapping":{"worldcover":40}},
    {"class":"trees",  "std_mapping":{"worldcover":10}},
    {"class":"shrubs", "std_mapping":{"worldcover":20}}
  ],

  "training": {                                     // lineage → Dataset Cards (#5, #16)
    "datasets":["ds_farmforest_crops_v1","ds_farmforest_trees_v1","ds_worldcover_shrubs_v1"],
    "embedding":{"source":"alphaearth","dim":64},
    "algo":"StandardScaler→LinearSVC", "class_weight":"balanced",
    "balancing":{"method":"none|undersample|oversample","residual_cap":8000}   // #6
  },

  "extent": {                                       // where the model is VALID (#4, #7)
    "spatial":{"type":"region","value":"India"}, "temporal":{"year":2024}
  },

  "metrics": {                                      // lifted from the joblib `report`
    "accuracy":0.963, "macro_f1":0.884, "eval":"polygon-holdout", "n_test":3014,
    "per_class":{ "crops":{"precision":0.987,"recall":0.943,"f1":0.965},
                  "trees":{"precision":0.997,"recall":0.986,"f1":0.991},
                  "shrubs":{"precision":0.548,"recall":0.947,"f1":0.695} }
  },

  "artifact": {"path":"data/refine/greenery.joblib","format":"sklearn-joblib"},

  "deployment": {                                   // #10-12
    "ee_asset":null, "tile_url":null, "expressible_as_bandmath":true
  },

  "lineage": {"base_model":"mc_base_pooled_v1","derived_from":null},

  "about": {                                        // human-readable prose (#8)
    "description":"Per-node split of the greenery class.",
    "intended_use":"Refine greenery on the India base map.",
    "limitations":"shrubs are WorldCover-labelled (weak, low precision).",
    "evidence":"FarmForest expert crop+tree polygons; WorldCover shrubs."
  },

  "zoo": {"published":false, "valid_region_label":"India / AEZ-?", "contributor":""},  // #7

  "version":1, "created":"2026-06-13T00:00:00Z"
}
```

**Notes**
- `topology` records the per-node-vs-flat decision (`week3/notes/classifier_topology.md`);
  default `per_node_split`. A periodic "consolidation" model would be `flat_multiclass`.
- `expressible_as_bandmath:true` is the hook for the 10 m EE serving path — linear models
  replay as band math, so they can be pushed to EE and served as a `tile_url` (#10–#12).
  Non-linear/Tessera models set it `false` and fall back to the cell grid.
- `lineage` gives the zoo a DAG: base → greenery split → (future) trees→acacia, so "retrain
  this class" and "which base did this come from" are answerable from the cards alone.

---

## 5. Catalogue / registry + model selection

```
data/catalogue/
  datasets/<id>.json      # Dataset Cards
  models/<id>.json        # Model Cards
  std_crosswalk.json      # canonical class -> {worldcover, usda, iucn}
  index.json              # denormalized lookup (id, kind, classes, extent) for fast filtering
```

**"Models good for my area" (#3–#5):** given an AOI + interest (a base class or a target
class), filter cards where `extent.spatial` contains the AOI **and**
`parent_class`/`produces` matches the interest; rank by metrics × spatial fit. The user then
picks one and refines it (split/add → a new Model Card with `lineage.derived_from` set).

---

## 6. The typed `extent` object (shared by both cards)

One shape, three spatial forms + a temporal field, so AEZ labels and precise geometries
coexist (#4, #7, #18):

```jsonc
"spatial": {"type":"region","value":"India"}          // controlled vocab: world|pan-india|AEZ-<n>|district:<id>|...
// OR        {"type":"polygon","geojson":{...}}        // a drawn/uploaded boundary or bbox
// OR        {"type":"ee_asset","asset":"users/.../aez_13"}
"temporal": {"year":2024}                              // OR {"start":"2020","end":2024"}
```

Containment ("is this AOI inside the model's extent?") is: region → look up the region's
geometry and test; polygon/ee_asset → direct geometry test. (Open question: precompute
AOI→region membership vs test live — see plan.)

**Beyond space + time (keep `extent` open).** Spatial + temporal are the two axes we can
check today, but they aren't the only ones a model's validity depends on. The concrete third
axis is the **embedding basis**: the model is a linear map over Alpha Earth vectors, so it's
only valid where that embedding exists and is comparable (source + version + year +
coverage — recall Tessera is 2024/India only). We already carry an `embedding` block on both
cards; treat it as part of validity. Other candidates (season/phenology, sensor/resolution)
mostly fold into temporal or are fixed for us, so we don't hard-code them — but the object is
deliberately an **open set of constraints**, not a fixed pair, so a future axis is an added
key, not a schema break. Rule of thumb: only add an axis we can actually test against an AOI.

---

## 7. Quality & balance (define conceptually — #6, #19)

- **Spatial diversity index** (dataset quality, #19): bin sample locations into a coarse grid
  (0.25° cells), take the Shannon entropy of the per-cell counts, normalize by `ln(n_points)`
  → `[0,1]`. ~1 = every polygon in its own cell (well spread); ~0 = all clustered in one
  spot. Flags "100 polygons but all from one district" datasets. (Ties to the
  generalization-gap finding: diversity, not volume, is what moves accuracy on unseen
  regions.) **Measured** on the demo datasets by `week4/notes/spatial_diversity.py`: crops
  0.889 (77 cells / 110 polys), mining 0.867 (65 / 100), trees 0.840 (81 / 145) — all
  healthily spread across India.
- **Imbalance guidelines** (training, #6) — explicit rules so a split/add doesn't create a
  lopsided model:
  1. Before training, compute the resulting class ratios over the assembled rows.
  2. If the majority:minority ratio passes a threshold (proposal: 5:1), warn and offer a fix:
     **undersample** the majority, **oversample** the minority, or **cap the residual** (we
     already cap at `residual_cap=8000` in `refine.py`) / re-weight (`class_weight="balanced"`,
     today's default).
  3. Record the chosen policy in the Model Card's `training.balancing` so it's auditable, and
     keep showing per-class metrics (a class can be present but unlearnable — e.g. shrubs at
     F1 0.695 — which the ratios alone won't reveal).

---

## 8. Instruction coverage (#1–#19 → where it lands)

| # | Ask | Lands in |
|--|--|--|
| 1 | Dynamic legend, evolves with input | Model Card `produces` (the emitted legend) |
| 2 | Accuracy of on-the-fly model / better GT | `metrics`; dataset `quality` |
| 3 | Model zoo: browse, reuse, see what's best | Catalogue + selection (§5) |
| 4 | Models characterized by extent (AEZ/district/pan-India) | `extent` (§6) |
| 5 | DB of models; classes, training origin; user retrains | Model Card + `training` + lineage |
| 6 | Balance guidelines (under/oversample, thresholds) | `training.balancing` + guidelines (§7) |
| 7 | Contribute to zoo; valid-region metadata | `zoo` + `extent` |
| 8 | Description + evidence / how-annotated for new classes | `description` (per class) + `about` + dataset `provenance` |
| 9 | Build a model-card LULC schema | this whole note (§4) |
| 10 | Push to EE / AlphaEarth, get output | `deployment.ee_asset`, `expressible_as_bandmath` |
| 11 | Tile URL; push model to EE, no PNG download | `deployment.tile_url` |
| 12 | Save/share + EE + JSON metadata for all models | Model Card is that JSON; `artifact`+`deployment` |
| 13 | Map new class into a standard class | mandatory `parent_class` + optional `std_mapping` (§2) |
| 14 | Own standard so model count doesn't blow up | canonical spine = the 4 base classes (§2) |
| 15 | USDA / IUCN standards to map to + pull in standard data | `std_mapping`, `taxonomy_crosswalk.md`; standard library (§3b) |
| 16 | Data cards too; pick GT, per-area/per-year | Dataset Card; selection panel + `training.selection` (§3c) |
| 17 | Two ways to define a dataset (polygon / EE asset); pos/neg panel | `definition.type` (§3); standard library (§3b); panel (§3c) |
| 18 | DB of datasets w/ spatial+temporal validity | Dataset Card + catalogue + `extent` |
| 19 | Quality metrics (spatial diversity / entropy) | `quality.spatial_diversity` (§7) |

No orphan asks — every instruction has a concrete home.

---

## 9. Expressiveness check (proof: real artifacts fill the schema)

Filled cards using the *actual* deployed numbers live in `examples/`:
- `mc_base_pooled_v1.json` — the 4-class base map (acc ~0.89 balanced / ~0.80 random India).
- `mc_greenery_split_v1.json` — acc 0.963; crops F1 0.965, trees 0.991, shrubs 0.695.
- `mc_barren_mining_v1.json` — acc 0.867; mining F1 0.810 (ADD = split + residual).
- `ds_*.json` — crops (110 polys), trees (145 polys), shrubs (WorldCover code 20), mining
  (100 polys), and the expert-barren embedding-table slice.

Every field is filled from something that already exists — none invented — which is the
evidence that the schema fits.
