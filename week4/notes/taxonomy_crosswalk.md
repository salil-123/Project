# Canonical taxonomy + crosswalk (week 4)

## The spine is ours, and it starts small on purpose

The canonical taxonomy **starts as the 4 base classes we already have** — `greenery`,
`water`, `built_up`, `barren` (the `root` children in `data/hierarchy.json`). It is **not** a
hard ceiling: the tree is editable at every level. We do **not** adopt USDA or IUCN as our
spine; that would force every user into a foreign taxonomy and (more importantly) let the
model count explode as people invent classes (#14).

How the taxonomy grows:
1. **Add / split at any level (incl. root).** A user can split a class, add a class under any
   node, or **add a new base class** under root. A root-level add retrains the base map
   (`refine.retrain_base`); deeper adds/splits train just that node.
2. **Map *in* (encouraged, not forced).** A new class *usually* fits under an existing class
   (a seasonal/perennial water-body under `water`), which keeps models comparable. If it
   genuinely doesn't fit, a new base class is fine — that's the #13 judgement call.
3. **Map *out* (optional).** A leaf *may* carry `std_mapping` to external standards for
   interoperability and export — but nothing in the system *requires* it (#15).

## The base spine

| canonical | name | color | notes |
|--|--|--|--|
| `greenery` | Greenery | `#2e8b2e` | vegetation; splits into crops/trees/shrubs in the demo |
| `water`    | Water    | `#2b6cff` | |
| `built_up` | Built-up | `#d7301f` | |
| `barren`   | Barren   | `#c2a05a` | splits into barren_other + mining in the demo |

## Optional outward crosswalk (`std_mapping`)

Illustrative — to be confirmed against the real code lists before publishing. ESA WorldCover
uses 10/20/30/… class codes; USDA/Anderson is the classic Level-I LULC; IUCN GET uses biome
codes (T = terrestrial, F = freshwater, etc.). These give `std_mapping` real values on the
slides; the point is the *mechanism*, not pinning every code today.

| our class | parent | WorldCover (code) | USDA / Anderson (Level I–II) | IUCN GET |
|--|--|--|--|--|
| greenery | root | — (umbrella) | Vegetated land | — |
| crops | greenery | Cropland (40) | Agricultural land → Cropland | T7 (intensive land-use) |
| trees | greenery | Tree cover (10) | Forest land | T1–T3 (forest biomes) |
| shrubs | greenery | Shrubland (20) | Rangeland → Shrub | T4/T5 (shrub/heath) |
| water | root | Permanent water (80) | Water | F (freshwater) |
| built_up | root | Built-up (50) | Urban / built-up | T7.4 (urban) |
| barren | root | Bare/sparse (60) | Barren land | T6 / deserts |
| mining | barren | Bare/sparse (60)* | Barren → Extractive | T7.5 (derived anthropogenic) |

\*WorldCover has no "mining" class — which is exactly *why* a user adds it locally and maps
it back to `barren`. The crosswalk records "this fine class rolls up to barren / WorldCover 60"
so global products stay comparable while the local model keeps the extra detail.

## Where this is stored

`data/catalogue/std_crosswalk.json` — `{ canonical_class: {worldcover, usda, iucn} }`, read
when a card is published and when exporting to a standard product. Each Model Card's
`produces[].std_mapping` can override/extend the global table for its own leaves.
