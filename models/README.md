# models/

Trained weights live here — the `models/` mount from the cluster checklist (§1: `code/` → `/app`,
`models/` → `/app/models`, `data/` → `/app/data`). Keeping weights out of `data/` means outputs can
be rotated or wiped without taking the models with them, and out of the image means updating the app
is still just `git pull` + restart.

Layout mirrors the old one, minus the `data/` prefix:

```
models/
├─ model_pooled.joblib              the base classifier (the 4-class spine)
├─ model_worldcover_base.joblib     the alternate WorldCover base scheme
├─ model_softvote*.joblib           AE + Tessera soft-vote variants
└─ refine/
   ├─ <node>.joblib                 one per split classifier (greenery, barren, …)
   ├─ water_fortnight*.joblib       the raw Sentinel fortnight water models
   └─ archive/                      superseded models a zoo card still points at
```

**Weights may still be under `data/`.** They used to live there, and every zoo card's
`artifact.path` records that spelling — which is data, not code, so we don't rewrite it. The app
resolves weights through `config.model_path()`, which looks in `models/` first and falls back to the
old `data/` location, so both layouts work. To do the move:

```bash
python scripts/migrate_models.py --dry-run   # see what would move
python scripts/migrate_models.py             # move it (weights only; *_train.csv stay in data/)
```

Nothing breaks before or after — that's the point of the fallback.
