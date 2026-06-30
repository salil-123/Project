# Core Stack LULC

A web tool to paint a 10 m land-use / land-cover map over any part of India, then **grow your own
class scheme** on top of it — split a class into finer ones, add new classes, merge classes across
models — by handing the tool a few example polygons and retraining on the fly. Every trained model
and dataset is recorded as a **card** in a git-backed **model zoo** so others can find one for
their area and keep refining it.

Project home: https://core-stack.org/

## How it works (one paragraph)

We never touch raw imagery at inference. Each pixel is a pre-learned vector — **Alpha Earth** (64-d,
Google Satellite Embedding, server-side in Earth Engine, free, India-wide) and optionally **Tessera**
(128-d, 2024-only over India). A linear model (`StandardScaler → LinearSVC`) sits on top; because
it's linear, it **replays exactly as band math inside Earth Engine**, so a whole bounding box is
classified server-side and served as map tiles with nothing downloaded.

## Run it

```bash
python -m venv .venv && . .venv/Scripts/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Earth Engine: copy .env.example to .env and set EE_PROJECT / EE_USER_ID (then `earthengine authenticate`)
uvicorn backend:app --reload --app-dir src
```

Open http://127.0.0.1:8000/.

## The full story

`master_document.md` is the single source of truth: what the project is, the live architecture, the
week-by-week history, and the latest refinements. Per-week detail lives in `weekN/plan.md`; deeper
notes in `docs/pipeline.md` and `docs/model.md`.

## What's not in this repo (and why)

To keep the repo lean and within GitHub's limits, a few things are intentionally `.gitignore`d:

- **`.venv/`** — recreate from `requirements.txt`.
- **`.env`** — local config (your Earth Engine project + the zoo remote). Not a secret store, but
  machine-specific.
- **Large training/eval tables (`*.csv`, `*.npy`)** — regenerable from Earth Engine;
  `master_tessera.csv` alone is 138 MB (past GitHub's 100 MB limit). The trained **`.joblib`
  models are kept** (they're tiny), so the app classifies straight from a clone — only *retraining*
  needs the tables rebuilt.
- **`data/catalogue/`** — the model zoo is its own git repository (pushed to `zoo_database.git`),
  so it isn't nested inside this one.
