# #15 — STACD cross-verification with Susmit's item (and Saharsh's Airflow format)

Susmit replied to the STACD spec mail: some parameters in our `stack_item` differ from theirs, he
attached a sample (`week11/susmit_stac.json`, their tree-crown pipeline item), and he's unsure which
differences are optional vs mandatory — he asks us to cross-check against Saharsh's Airflow-expected
STACD format. This note is the field-by-field comparison, the verdict on each, and what we changed.

## What Susmit sent

A single **STAC Item** (not the STACD graph) for their Detectree2 + DINOv2 tree-crown run. Key shape:
`type=Feature`, `stac_version=1.1.0`, a `collection`, `geometry`+`bbox`, `properties` with a
datetime *range* + `keywords` + their run config (`input_parameters`, model names) + `table:columns` +
explicit min/max/center lon-lat, an `assets` map (geojson / kmz / csv / qml style), and proper catalog
`links` (root/collection/parent/self).

## Field-by-field: ours vs theirs, and the verdict

| field | theirs | ours (before) | mandatory in STAC? | what we did |
|-------|--------|---------------|--------------------|-------------|
| `type` | `Feature` | `Feature` | yes | already matched |
| `stac_version` | `1.1.0` | `1.0.0` | yes | **bumped to 1.1.0** (uniformity) |
| `id`, `geometry`, `bbox` | present | present | yes | already matched |
| `properties.datetime` | present | present | yes (nullable) | already matched |
| `assets`, `links` | present | assets ✓, links `[]` | yes (both required arrays) | **added real links** (self/root/collection/parent) |
| `collection` | `tree_crown_runs` | — | optional (needed if a collection link exists) | **added** `corestack_lulc_runs` + the link |
| `start/end_datetime` | present | — | optional (common) | **added** a year range |
| `keywords` | present | — | optional | **added** LULC keywords |
| `input_parameters` | their run config | we had `params` on the dataset_instance | optional | **added** to the item too (region/year/base) |
| min/max/center lon-lat | present | — | optional (convenience) | **added** for parity |
| `table:columns` | present (table ext) | — | only if you use the table extension | **N/A** — their output is a per-crown *table*; ours is a *raster* (we carry a class legend instead) |
| `stac_extensions` | official schema URL (`table/v1.2.0`) | the STACD repo URL | optional | **left as-is, flagged below** |

## The verdict on "optional vs mandatory"

The genuinely **mandatory** STAC-Item fields (type, stac_version, id, geometry, bbox, properties.datetime,
assets, links) were all present on both sides — the item was already valid. Every difference Susmit saw
is one of:
- **optional-but-common** metadata we should adopt for uniformity (datetime range, keywords, collection,
  real links, input_parameters, min/max lon-lat) — **done**;
- **their-pipeline-specific** fields that don't apply to us (`table:columns`, `detector_model`,
  `feature_extractor`, `chosen_k`, DINOv2 names) — a table item vs our raster item, so not adopted.

So nothing was *wrong*; we were just a thinner, STAC-1.0 item. It's now a STAC-1.1 item with the same
envelope shape as theirs.

## The two things that still need Saharsh / Airflow confirmation

1. **`stac_extensions`.** Theirs points at a published JSON-schema URL (the official table extension);
   ours points at the STACD repo, which is a marker, not a validatable schema. STACD has no published
   extension schema. Question for Saharsh: does the Airflow catalog validate `stac_extensions` against
   real schemas (in which case we should drop the repo URL or publish a STACD schema), or is the repo
   URL an accepted convention?
2. **Collection / catalog wiring.** We now emit `collection` + root/collection/parent links, but we don't
   yet *write* a `collection.json` / `catalog.json` — Susmit's `href`s assume a catalog on disk. The
   Airflow runtime is what materialises that catalog. So the item is catalog-*ready* but the catalog
   itself is the deployment step (same gap noted in the week-10 audit: we emit the metadata half, not the
   Airflow runtime). Question: what collection id / catalog layout does their Airflow expect so ours drops
   into the same catalog?

## What has to be done (summary)

- Done now: align the shared STAC-Item fields (version, collection, links, datetime range, keywords,
  input_parameters, bbox corners) so our item is uniform with theirs — `src/stacd.py::build_stack_item`.
- Needs Saharsh: confirm the `stac_extensions` convention, and the collection/catalog id + layout the
  Airflow ingester expects, then wire our items into that catalog (a deployment-week task).
- Then re-send the updated sample to Susmit/Anunay for a second cross-check.
