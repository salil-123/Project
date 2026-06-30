# Week 3 — archive

Self-contained record of week-3 work, segregated out of the repo root the same way
`week2/` was, so root stays clean for week 4. The **living tool** week 3 produced
(`src/`, `data/`, `config.py`, `tessera_fast.py`) stays at root — week 4 builds on it.

## What week 3 did, in one line
Turned the static 4-class base map (greenery / water / built_up / barren) into a
**living class hierarchy the user grows**: SPLIT an existing class or ADD a new one at
*any* level by handing us example polygons (drawn or uploaded), train per-node
refinement classifiers on the fly, and lay the result over the base map at a real
**10 m** resolution — served by the FastAPI tool in `src/`.

## What's in here
- `plan.md` — the full week-3 phase plan (P0–P6, all done).
- `instructions_week3.txt` — the raw asks this week answered.
- `week3_greenery_split.md` — the demo task: greenery → crops / trees / shrubs.
- `week3_any_level.md` — making SPLIT/ADD recursive (works at every depth, incl. root).
- `demo_instructions.md` — the presentation script.
- `TESTING.md` — how to exercise every week-3 feature (web + headless).
- `slides_week3.{tex,pdf}` + `figures/` — the deck and its before/after maps.
- `notes/` — `classifier_topology.md` (per-node vs multiclass decision),
  `base_model_improvements.md` (data-side base-model notes).
- `scripts/` — the one-off ingest / demo / bake-off scripts. They import from the
  root `src/` + `config.py` and read root `data/`, so **run them from the repo root**,
  e.g. `python week3/scripts/add_mining.py`. (Their `ROOT` was repointed up one level
  after the move so the imports still resolve to root.)

## Where the live pieces landed (still at root, not here)
- `src/{backend,infer,refine,examples,hierarchy,sampling,contributions,...}.py` + `src/static/`
- `data/hierarchy.json`, `data/examples/`, `data/refine/`, the model `.joblib`s, training CSVs.
- `test_data/` (upload/retrain fixtures + `demo_backup/` reset snapshot) and
  `mining_polygons_india.gpkg` (the ADD-mining input) — data inputs, kept at root.
