# Week 7 — demonstration walkthrough

Hands-on paths for the stress-test sites and the new engineering features. Run the app from the
repo root:

```
uvicorn backend:app --reload --app-dir src      # then open http://127.0.0.1:8000/
```

One-time prep (turns the raw acacia crowns into example files the trainer reads):

```
python scripts/prep_acacia_examples.py
# -> data/examples/acacia.geojson (336), data/examples/non_acacia.geojson (576)
```

A handy fact used throughout: a SPLIT whose children are named `acacia` / `non_acacia` /
`tea` / `mining` **auto-picks-up** `data/examples/<child>.geojson` at train time — no
re-uploading, because `examples.build_training_frame(child)` reads that file by node name.

---

## 1. IIT Delhi + Sanjay Van — acacia vs non-acacia (#7)

Our home strip: IIT built-up, Sanjay Van trees + a small water body, and the 912 labelled tree
crowns all sit inside the preset box.

1. Start from the IndiaSAT-4 base (first-run chooser, or the zoo base card).
2. **Split** `greenery` into `acacia` + `non_acacia` (Operations panel → Split). Leave the
   example source blank — the ingested files are already at `data/examples/acacia.geojson` /
   `non_acacia.geojson`, so retrain reads them directly.
3. **Retrain** the split. The held-out report prints in the server log.
4. Preset → **"IIT Delhi + Sanjay Van (acacia)"** → **Run**. Acacia and non-acacia paint
   separately over the strip.
5. Open the acacia dataset card in the zoo → the spread block now shows **coverage vs this AOI**
   (#4): what fraction of the strip the crowns actually label.

## 2. Asola Bhatti — mining / acacia false positives (#9)

Old mines here were reclaimed into built-up + acacia, so it's a false-positive probe: a mining
model *shouldn't* light up, and an acacia model might.

1. With the acacia split live (from §1), Preset → **"Asola Bhatti (mining/acacia)"** → **Run**.
   Look for acacia predictions where the ground is really reclaimed scrub/built-up.
2. Add mining: **Add** `mining` under `barren` (its examples are at `data/examples/mining.geojson`),
   retrain, Run again. Check whether the reclaimed mines register as mining (expected: few/none —
   that's the point of the probe).

## 3. Assam tea belt — tea vs non-tea (#10)

1. Base scheme, **Split** `greenery` into `tea` + `non_tea` (files already under `data/examples/`).
2. Retrain, Preset → **"Assam tea belt (tea/non-tea)"** → **Run**.

## 4. Jalpaiguri — base-scheme + WorldCover-direct demo (#2)

1. Zoo → base card → switch to the **WorldCover-7** base. Preset → **"Jalpaiguri (base-scheme
   demo)"** → **Run** (classifies against WorldCover classes directly).
2. **Merge** two WorldCover leaves into one base class (e.g. shrubland+grassland) to show
   "mapping many classes down to fewer" — the point of `week7/notes/worldcover_direct.md`.
3. **Split/Add** to grow a finer class from your own examples.

---

## 5. Temporal robustness — train on multiple years (#3)

Alpha Earth has a mosaic per year 2017-2024, so we can pool several years into one split model
and check it still handles years it never trained on. Run from the **repo root**:

```
python src/temporal_eval.py --children acacia non_acacia \
    --train-years 2019 2021 2023 --eval-years 2020 2024
```

It trains a single-year baseline (newest train year) and a **multi-year pooled** model on the
same held-out-polygon set, then scores both on held-out polygons at each *unseen* eval year, and
saves the pooled model to `data/refine/acacia_non_acacia_multiyear.joblib`. The multi-year model
should beat the single-year baseline on the unseen years — that's the temporal robustness.

Add `--matrix` for the finer single-year × single-year accuracy grid. To deploy multi-year in
the live tree, `refine.train(parent, years=[2019,2021,2023])` pools the years into the node's
classifier directly.

**Results.** Acacia/non-acacia (n_pix=20): on unseen years the pooled multi-year model beats the
single-year baseline by ~11 points — 2020: 0.637 → 0.756, 2024: 0.634 → 0.734 (mean 0.635 →
0.745). The **four base classes** run the same way from the ground-truth polygons:

```
python src/temporal_eval.py --from-file data/selected_polygons.geojson \
    --classes greenery water built_up barren --train-years 2019 2021 2023 --eval-years 2020 2024
```

give single 0.888 → multi 0.891 (+0.003): the coarse classes are already stable across years, so
multi-year robustness earns its keep on the *fine* splits (acacia), not the base classes.

In the app: open the **Alpha Earth** inference card in the zoo — the **Inference year**
dropdown now carries a note on how far a ground truth is trusted across years, and that Tessera
is 2024-only but other years can be requested (#6). Changing the year re-samples the same model
at that year on the next Run.

## 6. Loading a scheme is validated first (#5)

One upload, checked before it's applied — no separate "validate" step.

1. Download your scheme: **Save / load scheme → Download hierarchy (JSON)**.
2. Hand-break it (rename a `split`'s op to something unknown, or point a node's `classifier` at
   a missing file).
3. **Save / load scheme → load a saved scheme** → pick the broken file. It's **rejected with the
   exact reasons** and **nothing changes** — the server validates before it mutates.
4. Load a sound file → it applies and re-classifies; any split whose model is missing on disk is
   reported so you can retrain it.

Endpoint check (import validates then applies; a bad file returns 400 and mutates nothing):

```
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/hierarchy/import \
  -H 'content-type: application/json' -d @broken_scheme.json
# -> 400   (body: {"detail": {"message": "invalid scheme", "errors": [...], "warnings": [...]}})
```
