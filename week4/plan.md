# Week 4 — Schema design for the Model & Dataset "zoo" (research/design only)

**Source:** `instructions_week4.txt`. **Builds on:** the week-3 living hierarchy
(`src/{hierarchy,refine,examples,infer}.py`, tree in `data/hierarchy.json`). This week is
**design/research only — no code.** Deliverable = a finalized **Model Card** + **Dataset
Card** schema (plus the canonical-taxonomy crosswalk and the catalogue that ties them
together), grounded in artifacts we already have, presented as TeX slides.

## Goal in one line
Define the data model for a **model zoo + dataset catalogue**: every localized LULC model
tagged with where it's valid, what classes it emits, what it trained on, and how it was
annotated — so a user can pick one for their area and keep refining it (#3–#5, #8, #9, #16, #18).

## Locked decisions (from the user)
1. **Canonical spine starts as the 4 base classes** (greenery / water / built_up / barren), but
   the tree is editable at every level: users can split, add under a node, or add a new base
   class under root (retrains the base map). New classes usually map *into* the spine where they
   fit (for comparability); external standards (WorldCover / USDA / IUCN) are an optional
   *outward* crosswalk only, so the model count can't blow up (#14).
2. **Bespoke, standards-aware** schema — our own minimal JSON fitted to the
   hierarchy/joblib/examples, borrowing field names from HF & Google Model Cards and
   STAC/Croissant for familiarity/exportability.
3. **Typed, multi-form `extent`** — named region (AEZ / district / pan-India / world) *or*
   polygon/bbox *or* EE asset id, with a temporal field alongside (#4, #7, #18).
4. **Slides = concept + concrete drafts** — motivation, catalogue picture, *and* annotated
   JSON drafts of both cards filled with the real greenery-split / mining demos.

## Build order (all writing, no code)
1. Survey existing artifacts → grounding table (done; see `notes/model_data_schema.md`).
2. Survey standard taxonomies → `notes/taxonomy_crosswalk.md`.
3. Finalize the Dataset Card schema (two definition modes #17 + quality block).
4. Finalize the Model Card schema (typed extent, lineage, EE/tile-url deploy, balancing).
5. Catalogue + selection design; imbalance/quality definitions (#6, #19).
6. Worked examples — fill both cards for base pooled / greenery split / mining ADD + one
   hypothetical (trees→acacia, a wetland) to stress the crosswalk → `notes/examples/`.
7. Assemble `slides_week4_schema.tex` → PDF.

## Deliverables (this folder)
- `plan.md` (this) · `notes/model_data_schema.md` (design of record) ·
  `notes/taxonomy_crosswalk.md` · `notes/examples/*.json` (filled cards) ·
  `slides_week4_schema.tex` (+ PDF).

No edits to `src/` or `data/`.

## Open questions for the meeting
- Card `id` / versioning scheme; how a retrain bumps a version.
- Where AEZ / district polygons come from; precompute AOI→region or test containment live.
- Per-dataset embeddings: re-sample each time (today) vs persist a cached table.
- What "contribute to the zoo" gates on (#7).
- Is the base (root) itself a Model Card? (proposed: yes — `mc_base_pooled_v1`.)

## Verification (no-code deliverable)
- Coverage: every instruction #1–#19 points to a concrete field/slide (table in the note).
- Expressiveness: every existing artifact fills the schema with no missing/invented fields
  (the worked examples are the proof).
- Slides compile to a clean PDF with the JSON drafts legible.
