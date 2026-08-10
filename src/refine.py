"""Phase 4 — the refinement engine: train per-node split classifiers, and the two
operations that grow the tree (SPLIT and ADD), plus relabelling and a bake-off.

A node's classifier only decides among that node's children (see
week3/notes/classifier_topology.md). It runs only on pixels the base map already assigned to
that node, so inference reuses the same 64-d Alpha Earth vectors (infer.py composites it).

Each child says where its training samples come from via its `source` field:
  - examples            -> expert polygons the user marked (sampled via examples.py)
  - {worldcover, code}  -> ESA WorldCover rows already embedded in worldcover_train.csv
  - {residual, core_class} -> the parent's own base pixels ("stayed b"), from master_alpha_full

SPLIT and ADD share one trainer; ADD is just a SPLIT where one child is an auto residual
that keeps the parent's identity (barren -> "Barren" residual + "Mining").

Run from repo root:  python src/refine.py [--resample]
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root (config)

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score

# the bake-off candidates (#17). All LINEAR — each exposes coef_/intercept_, so the winner still
# replays as Earth-Engine band math and rides the crisp tile map. class_weight is set at fit time.
_LINEAR_ALGOS = {
    "linearsvc":  lambda cw: LinearSVC(class_weight=cw),
    "logreg":     lambda cw: LogisticRegression(class_weight=cw, max_iter=2000),
    "ridge":      lambda cw: RidgeClassifier(class_weight=cw),
}

# non-linear learners (#1): richer, but they DON'T replay as band math, so they only make sense on
# a feature source we render on the point grid anyway — i.e. Tessera (local), not Alpha Earth. This
# is the "if you go local you're not limited to linear models" branch. XGBoost is optional (used
# only if the package is installed), so the registry can offer it without a hard dependency.
def _has_xgb():
    try:
        import xgboost  # noqa: F401
        return True
    except Exception:
        return False


def _xgb(cw):
    from xgboost import XGBClassifier
    return XGBClassifier(n_estimators=300, max_depth=6, n_jobs=-1, tree_method="hist")


_NONLINEAR_ALGOS = {
    "randomforest": lambda cw: RandomForestClassifier(n_estimators=300, n_jobs=-1, class_weight=cw),
}
if _has_xgb():
    _NONLINEAR_ALGOS["xgboost"] = _xgb

_ALL_ALGOS = {**_LINEAR_ALGOS, **_NONLINEAR_ALGOS}

# which model families are valid for which inference data (#1). Earth Engine can only run linear
# models (band math), so the EE list is linear-only; a Tessera-local run can additionally use the
# non-linear pixel learners, and leaves room for an object-detection family we haven't built yet.
# `available` reflects what's actually installed/implemented, so the UI can grey out the rest.
def model_families(source="alphaearth"):
    """The model families a user can train for a given inference source (#1): id, label, kind
    (pixel / object), and whether it's available right now. EE -> linear only; Tessera -> +non-linear."""
    linear = [
        {"id": "linearsvc", "label": "Linear SVC", "kind": "pixel", "available": True},
        {"id": "logreg", "label": "Logistic Regression", "kind": "pixel", "available": True},
        {"id": "ridge", "label": "Ridge", "kind": "pixel", "available": True},
        {"id": "auto", "label": "Auto (best model)", "kind": "pixel", "available": True},
    ]
    if source == "tessera":
        return linear + [
            {"id": "randomforest", "label": "Random Forest", "kind": "pixel", "available": True},
            {"id": "xgboost", "label": "XGBoost", "kind": "pixel", "available": _has_xgb(),
             "note": None if _has_xgb() else "install xgboost to enable"},
            {"id": "objectdetection", "label": "Object detection (crowns)", "kind": "object",
             "available": False, "note": "planned — for discrete objects like tree crowns"},
        ]
    # Alpha Earth / EE: linear models replay as band math (crisp tiles). Random Forest is offered
    # too since sir asked for it (#7, wk10) — it just renders on the point grid instead of tiles.
    # XGBoost stays Tessera-only.
    return linear + [
        {"id": "randomforest", "label": "Random Forest", "kind": "pixel", "available": True,
         "note": "runs on Alpha Earth but renders on the point grid, not crisp tiles"},
    ]

import config
import hierarchy
import examples
import sampling                    # YEAR default + interior-point/alpha sampling

# all anchored to the project root so training/loading works from any CWD (Docker/Airflow)
REFINE_DIR = config.project_path("data/refine")
WC_CSV = config.project_path("data/worldcover_train.csv")
FULL_CSV = config.project_path("data/master_alpha_full.csv")
BASE_MODEL_PATH = config.project_path("data/model_pooled.joblib")
WORLDCOVER_BASE_PATH = config.project_path("data/model_worldcover_base.joblib")
AE_COLS = [f"ae_{i:03d}" for i in range(64)]
TE_COLS = [f"te_{i:03d}" for i in range(128)]      # Tessera embedding columns (#16)
RESIDUAL_CAP = 8000              # max residual rows, so a split stays roughly balanced
BASE_CORE = {"greenery", "water", "built_up", "barren"}  # classes living in master_alpha_full

# the 'effective' WorldCover base scheme (#5): only the classes with real India support in
# worldcover_train.csv. (code, canonical id, display name, colour). The rare WorldCover classes
# (snow 29 / wetland 12 / moss 10 / mangrove 7 pts) are dropped — too few to learn.
WC_BASE = [
    (10, "tree",     "Tree cover",    "#2e8b2e"),
    (20, "shrubland", "Shrubland",    "#b8860b"),
    (30, "grassland", "Grassland",    "#a3c585"),
    (40, "cropland", "Cropland",      "#f0c14b"),
    (50, "built_up", "Built-up",      "#d7301f"),
    (60, "bare",     "Bare / sparse", "#c2a05a"),
    (80, "water",    "Water",         "#1e88e5"),
]


# ----------------------------- data sources -----------------------------
def _wc_rows(wc_code, label):
    """WorldCover rows for one class as [label, poly, ae_*]; each point its own group."""
    df = pd.read_csv(WC_CSV)
    df = df[df.wc == wc_code].reset_index(drop=True)
    out = df[AE_COLS].copy()
    out["label"] = label
    out["poly"] = [f"{label}:{i}" for i in range(len(out))]  # points are independent
    return out[["label", "poly"] + AE_COLS]


def _residual_rows(of_node, label, n_pix=30, cap=RESIDUAL_CAP, year=sampling.YEAR):
    """The parent's own pixels ('stayed b'), labelled as the residual child. For a base
    class they come from master_alpha_full (baked at 2024); for a deeper leaf, from its own
    examples re-sampled at `year`. The group id (polygon) rides along so splits stay leak-free."""
    if of_node in BASE_CORE:
        df = pd.read_csv(FULL_CSV, usecols=["polygon_id", "core_class"] + AE_COLS)
        df = df[df.core_class == of_node].reset_index(drop=True)
        if len(df) > cap:
            df = df.sample(cap, random_state=0).reset_index(drop=True)
        out = df[AE_COLS].copy()
        out["label"] = label
        out["poly"] = df.polygon_id.values
        return out[["label", "poly"] + AE_COLS]
    # deeper leaf: re-sample the node's own example polygons at the chosen year
    df = examples.build_training_frame(of_node, n_pix=n_pix, year=year)[["poly"] + AE_COLS].copy()
    df["label"] = label
    return df[["label", "poly"] + AE_COLS]


def _child_frame(tree, child, n_pix, year=sampling.YEAR, embedding="ae"):
    """Training rows for one child, dispatched on its `source`, sampled at `year`. Also folds in
    any hard-negatives stored against its *siblings* that should count as this child (only the
    residual child of an ADD split absorbs siblings' negatives).

    `embedding` = "ae" (Alpha Earth) or "tessera" (#16). Tessera is only wired for the *examples*
    source — the worldcover/residual sources are the base-class tables, which are Alpha-Earth-only."""
    cols = TE_COLS if embedding == "tessera" else AE_COLS
    node = tree[child]
    src = node.get("source") or {"type": "examples"}
    kind = src["type"]
    if kind in ("worldcover", "residual") and embedding == "tessera":
        raise ValueError(f"Tessera training isn't supported for '{child}' ({kind} source); "
                         "Tessera splits train from example polygons only.")
    if kind == "worldcover":
        df = _wc_rows(src["code"], child)
        print(f"  {child}: {len(df)} WorldCover rows")
    elif kind == "residual":
        of = src.get("of", src.get("core_class"))
        df = _residual_rows(of, child, n_pix=n_pix, year=year)
        print(f"  {child}: {len(df)} residual rows (of {of})")
        df = pd.concat([df, _sibling_negatives(tree, child, n_pix, year=year)], ignore_index=True)
    else:  # examples — sample the chosen embedding
        te = embedding == "tessera"
        df = examples.build_training_frame(child, with_tessera=te, n_pix=n_pix, year=year)
        df = df[["label", "poly"] + cols]
        print(f"  {child}: {len(df)} expert pixels ({embedding}) from {df.poly.nunique()} polygons")
    return df


def _sibling_negatives(tree, residual_child, n_pix, year=sampling.YEAR):
    """Hard-negatives marked against the residual's siblings ('not mining') become
    evidence for the residual ('barren'). Returns rows labelled as the residual child."""
    parent = tree[residual_child]["parent"]
    frames = []
    for sib in tree[parent]["children"]:
        if sib == residual_child:
            continue
        neg = _negatives_frame(sib, n_pix, year=year)
        if neg is not None:
            neg["label"] = residual_child
            neg["poly"] = [f"hardneg:{sib}:{i}" for i in range(len(neg))]
            frames.append(neg[["label", "poly"] + AE_COLS])
    if frames:
        out = pd.concat(frames, ignore_index=True)
        print(f"  {residual_child}: +{len(out)} hard-negative rows from siblings")
        return out
    return pd.DataFrame(columns=["label", "poly"] + AE_COLS)


def _negatives_frame(child, n_pix, year=sampling.YEAR):
    """Sample embeddings at a child's role='negative' example polygons at `year`, or None."""
    fc = examples.load_examples(child)
    negs = [f for f in fc["features"] if f["properties"].get("role") == "negative"]
    if not negs:
        return None
    import geopandas as gpd
    gdf = gpd.GeoDataFrame.from_features(negs, crs=4326)
    gdf["poly"] = [f"{child}-neg:{i}" for i in range(len(gdf))]
    pts = sampling.interior_points(gdf[["poly", "geometry"]], n_pix=n_pix)
    ae = sampling.sample_alpha(pts, year=year).reset_index(drop=True)
    df = pd.concat([pts[["poly"]].reset_index(drop=True), ae], axis=1)
    return df.dropna(subset=AE_COLS).reset_index(drop=True)


# ----------------------------- training -----------------------------
def _year_list(years):
    """Normalize a year arg (None / int / iterable) to a sorted list; None means the default year."""
    if years is None:
        return [sampling.YEAR]
    if isinstance(years, int):
        return [years]
    return sorted(years)


def build_split_dataset(parent="greenery", n_pix=50, resample=False, years=None, embedding="ae"):
    """Assemble the parent's training table from its children's sources, sampled at one or more
    `years`. Pooling several years teaches the split what each class looks like across time, which
    is what makes it temporally robust (#3): the same polygon sampled at 2019 and 2023 is two rows
    but shares its group id, so a whole polygon is still held out together (no leakage) — the extra
    years are time-augmentation, not new polygons. Cached as a build artifact (pass resample=True to
    rebuild); the cache is keyed by the year set, with the single default year keeping the bare name
    for back-compat with existing caches."""
    years = _year_list(years)
    stem = parent if years == [sampling.YEAR] else f"{parent}_" + "_".join(str(y) for y in years)
    if embedding == "tessera":                       # keep te caches separate from the ae ones (#16)
        stem += "_te"
    cache = os.path.join(REFINE_DIR, f"{stem}_train.csv")
    if os.path.exists(cache) and not resample:
        print(f"using cached training data {cache}")
        return pd.read_csv(cache)

    tree = hierarchy.load()
    if not tree.get(parent, {}).get("children"):
        raise ValueError(f"'{parent}' has no sub-classes to train — split it or add classes first.")
    frames = []
    for y in years:
        if len(years) > 1:
            print(f"sampling year {y}…")
        frames += [_child_frame(tree, child, n_pix, year=y, embedding=embedding)
                   for child in tree[parent]["children"]]
    data = pd.concat(frames, ignore_index=True)
    os.makedirs(REFINE_DIR, exist_ok=True)
    data.to_csv(cache, index=False)
    print(f"assembled {len(data)} rows ({len(years)} year(s)) -> {cache}")
    return data


def _rebalance(X, y, how, seed=0):
    """Even out class counts before fitting (#6). 'undersample' drops the majority down to the
    minority count; 'oversample' draws the minority up (with replacement) to the majority count;
    anything else is a no-op (we lean on class_weight instead). Only the *training* rows are
    touched — the held-out test stays untouched so the metrics stay honest."""
    if how not in ("undersample", "oversample"):
        return X, y
    rng = np.random.default_rng(seed)
    classes, counts = np.unique(y, return_counts=True)
    target = counts.min() if how == "undersample" else counts.max()
    idx = np.concatenate([rng.choice(np.where(y == c)[0], size=target,
                                     replace=(np.sum(y == c) < target)) for c in classes])
    rng.shuffle(idx)
    return X[idx], y[idx]


def train(parent="greenery", n_pix=50, test_size=0.25, resample=False, balance="balanced",
          years=None, algo="linearsvc", embedding="ae"):
    """Train the parent's split classifier.

    `years=[...]` pools multiple years for temporal robustness (#3). `embedding` picks the feature
    source: "ae" (Alpha Earth, 64-d, the default — rides the crisp tile map) or "tessera" (128-d,
    #16, point-grid only). `algo` picks the estimator: a specific linear model, or "auto" to bake
    off all the linear candidates and keep the best by held-out accuracy (#17) — the winner stays
    linear, so it still replays as band math."""
    years = _year_list(years)
    # non-linear learners can't replay as EE band math. Random Forest is still allowed on Alpha
    # Earth (#7, wk10) — it just renders on the point grid instead of the crisp tile map — but the
    # rest (XGBoost) stay Tessera-only, where we render on the point grid anyway.
    if algo in _NONLINEAR_ALGOS and embedding != "tessera" and algo != "randomforest":
        raise ValueError(f"'{algo}' is a non-linear model that runs on Tessera (local) features only. "
                         "On Alpha Earth only linear models and Random Forest are supported.")
    cols = TE_COLS if embedding == "tessera" else AE_COLS
    data = build_split_dataset(parent, n_pix=n_pix, resample=resample, years=years, embedding=embedding)
    X, y, groups = data[cols].values, data.label.values, data.poly.values

    # hold out whole polygons so train/test never share a polygon's pixels
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=0)
                  .split(X, y, groups))
    # under/oversample balances the data itself, so drop class_weight then; else lean on it
    cw = None if balance in ("undersample", "oversample") else "balanced"
    Xtr, ytr = _rebalance(X[tr], y[tr], balance)
    labels = sorted(set(y))

    # bake-off (#17): fit each candidate, score on the held-out polygons, keep the best by accuracy.
    # "auto" always tries the linear models, plus Random Forest — on Alpha Earth too now (wk10
    # follow-up): if RF wins it just renders on the point grid instead of tiles, which the
    # algorithm-aware inference already handles. Tessera additionally throws in XGBoost.
    if algo == "auto":
        extra = list(_NONLINEAR_ALGOS) if embedding == "tessera" else ["randomforest"]
        candidates = list(_LINEAR_ALGOS) + extra
    else:
        candidates = [algo if algo in _ALL_ALGOS else "linearsvc"]
    scored = []
    for name in candidates:
        m = make_pipeline(StandardScaler(), _ALL_ALGOS[name](cw))
        m.fit(Xtr, ytr)
        acc = accuracy_score(y[te], m.predict(X[te]))
        scored.append((acc, name, m))
        if algo == "auto":
            print(f"  bake-off {name:10} held-out acc {acc:.3f}")
    scored.sort(key=lambda t: t[0], reverse=True)
    best_acc, best_algo, model = scored[0]
    if algo == "auto":
        print(f"  -> best linear model: {best_algo} ({best_acc:.3f})")

    pred = model.predict(X[te])
    print(f"\n=== {parent} split ({balance}, {best_algo}, {embedding}): held-out report ({len(te)} px) ===")
    print(classification_report(y[te], pred, digits=3))
    print("confusion (rows=true, cols=pred):", labels)
    print(confusion_matrix(y[te], pred, labels=labels))
    report = classification_report(y[te], pred, output_dict=True, zero_division=0)

    Xall, yall = _rebalance(X, y, balance)
    model.fit(Xall, yall)  # refit on everything (balanced) for the deployed model
    bundle = {"model": model, "classes": labels, "features": embedding, "parent": parent,
              "report": report, "n_test": int(len(te)), "balance": balance, "years": years,
              "algo": best_algo}
    os.makedirs(REFINE_DIR, exist_ok=True)
    out = os.path.join(REFINE_DIR, f"{parent}.joblib")
    joblib.dump(bundle, out)

    tree = hierarchy.load()
    tree[parent]["classifier"] = parent  # so inference knows to apply it
    hierarchy.save(tree)
    print(f"\nsaved {out}; registered classifier on node {parent!r}")
    return bundle


# ----------------------------- ADD operation (any level) -----------------------------
def add_class_op(parent, new_name, examples_src=None, new_color=None, new_canonical=None,
                 n_pix=30, do_train=True):
    """ADD a class under `parent`, at any level of the tree:

      - parent is the ROOT -> a new base class; retrains the base model (retrain_base).
      - parent already has children -> just add the new child and retrain its classifier.
      - parent is a leaf -> split it into a residual (keeps the parent's identity) + the
        new class; the residual inherits the parent's own data source.

    Reuses the split trainer + recursive inference, so the map picks it up unchanged.
    Returns the new class's canonical id.
    """
    tree = hierarchy.load()
    if parent not in tree:
        raise KeyError(f"unknown parent {parent!r}")
    new_id = new_canonical or hierarchy.canonicalize(new_name)

    if parent == hierarchy.ROOT:                       # new base class under root
        if new_id not in tree:
            hierarchy.add_class(tree, new_name, hierarchy.ROOT, canonical=new_id, color=new_color)
            hierarchy.save(tree)
        if examples_src is not None:
            examples.add_examples(new_id, examples_src, role="positive")
        if do_train:
            retrain_base()        # pools all user-added base classes, incl. this one
        return new_id

    if tree[parent]["children"]:                      # already a parent: add a sibling
        hierarchy.add_class(tree, new_name, parent, canonical=new_id, color=new_color)
        tree[new_id]["source"] = {"type": "examples"}
    else:                                             # leaf -> parent: residual + new
        residual_id = f"{parent}_other"
        hierarchy.split_class(tree, parent, [
            {"name": tree[parent]["name"], "canonical": residual_id, "color": tree[parent]["color"]},
            {"name": new_name, "canonical": new_id, "color": new_color},
        ])
        tree[residual_id]["source"] = {"type": "residual", "of": parent}
        tree[new_id]["source"] = {"type": "examples"}
    hierarchy.save(tree)
    print(f"added {new_id!r} under {parent!r}")

    if examples_src is not None:
        examples.add_examples(new_id, examples_src, role="positive")
    if do_train:
        train(parent, n_pix=n_pix, resample=True)
    return new_id


# ----------------------------- SPLIT operation (any level) -----------------------------
def split_op(parent, children, examples_srcs=None, n_pix=30, do_train=True):
    """SPLIT a leaf `parent` into the given children, then train its classifier.

    children: list of names or {name, canonical?, color?}. examples_srcs: optional
    {canonical_id: geometry_source} of positives to ingest per child. Works at any depth
    (e.g. trees -> acacia/non-acacia); inference recurses into it automatically.
    """
    tree = hierarchy.load()
    # guard the same way rule_split_op does: a split makes a leaf into a >=2-way choice. Splitting a
    # node that already has children would just append to them, silently desyncing the class set from
    # the trained classifier; a 0/1-child "split" is a no-op that still logs an op. Refuse both.
    if parent not in tree:
        raise KeyError(f"unknown parent {parent!r}")
    if tree[parent].get("children"):
        raise ValueError(f"'{parent}' already has sub-classes; split a leaf (or retrain/apply to change it).")
    if len(children) < 2:
        raise ValueError("a split needs at least two children.")
    hierarchy.split_class(tree, parent, children)
    for cid in tree[parent]["children"]:
        if tree[cid].get("source") is None:
            tree[cid]["source"] = {"type": "examples"}
    hierarchy.save(tree)
    print(f"split {parent!r} -> {tree[parent]['children']}")

    for cid, src in (examples_srcs or {}).items():
        examples.add_examples(cid, src, role="positive")
    if do_train:
        train(parent, n_pix=n_pix, resample=True)


# ----------------------------- RULE SPLIT (any level) -----------------------------
def rule_split_op(parent, rule, colors=None):
    """Split a leaf `parent` by an interpretable *rule* (#12) instead of a trained model.

    A rule is `{clauses: [{when, class}], default}` over the index registry (rules.py). This just
    creates the child leaves the rule produces and stashes the rule on the parent node — no
    training, no examples. Inference evaluates the rule live in Earth Engine (infer._refine_idx),
    so the split renders as crisp tiles like any linear split. Returns the child class list."""
    import rules
    rules.validate_rule(rule)                    # shape + expressions, before we touch the tree
    classes = rules.rule_classes(rule)
    tree = hierarchy.load()
    if parent not in tree:
        raise KeyError(f"unknown parent {parent!r}")
    if tree[parent].get("children"):
        raise ValueError(f"'{parent}' already has sub-classes; rule-split a leaf.")
    colors = colors or {}
    children = [{"name": c.replace("_", " ").title(), "canonical": c, "color": colors.get(c)}
                for c in classes]
    hierarchy.split_class(tree, parent, children)
    tree[parent]["rule"] = rule                  # the resolver for this node is a rule, not a joblib
    tree[parent]["classifier"] = None
    hierarchy.save(tree)
    print(f"rule-split {parent!r} -> {classes} via {len(rule['clauses'])} clause(s)")
    return classes


# ----------------------------- ROOT level: retrain the base model -----------------------------
def retrain_base(new_id=None, new_name=None, examples_src=None, new_color=None, n_pix=30,
                 out_path=BASE_MODEL_PATH):
    """Retrain the pooled base map model (master_alpha_full + WorldCover at wc_weight),
    optionally adding one new base class from user examples. Mirrors the week-2 recipe so
    the base keeps its calibration; saves to out_path and registers the class under root.
    """
    base = joblib.load(BASE_MODEL_PATH)
    wc_weight = base.get("wc_weight", 2)

    # register the new base class under root first, so example ingestion + inference
    # (which reads root's children from the base model's classes) both know about it.
    if new_id:
        tree = hierarchy.load()
        if new_id not in tree:
            hierarchy.add_class(tree, new_name or new_id, hierarchy.ROOT,
                                canonical=new_id, color=new_color)
            hierarchy.save(tree)

    if new_id and examples_src is not None:
        examples.add_examples(new_id, examples_src, role="positive")

    poly = pd.read_csv(FULL_CSV).dropna(subset=AE_COLS).rename(columns={"core_class": "y"})
    wc = pd.read_csv(WC_CSV).dropna(subset=AE_COLS).rename(columns={"true_class": "y"})
    frames = [poly[["y"] + AE_COLS], wc[["y"] + AE_COLS]]
    weights = [np.ones(len(poly)), np.full(len(wc), wc_weight)]

    # pool examples for every user-added base class (root children beyond the original 4)
    tree = hierarchy.load()
    for cls in (c for c in tree[hierarchy.ROOT]["children"] if c not in BASE_CORE):
        try:
            nf = examples.build_training_frame(cls, n_pix=n_pix).rename(columns={"label": "y"})
        except ValueError:
            print(f"  (skip {cls!r}: no examples yet)")
            continue
        frames.append(nf[["y"] + AE_COLS])
        weights.append(np.ones(len(nf)))
        print(f"  +{len(nf)} pixels for base class {cls!r}")

    pool = pd.concat(frames, ignore_index=True)
    w = np.concatenate(weights)
    model = make_pipeline(StandardScaler(), LinearSVC(max_iter=5000))
    model.fit(pool[AE_COLS].values, pool.y.values, linearsvc__sample_weight=w)

    bundle = {"model": model, "features": AE_COLS, "classes": sorted(pool.y.unique()),
              "wc_weight": wc_weight, "note": "pooled polygon+WorldCover (+ user base classes)"}
    joblib.dump(bundle, out_path)
    print(f"saved base model -> {out_path} (classes={bundle['classes']})")
    return bundle


def train_worldcover_base(out_path=WORLDCOVER_BASE_PATH, min_support=50):
    """Train the 'effective' WorldCover base map (#5): a LinearSVC over the 64 Alpha Earth dims,
    labelled by ESA WorldCover code, restricted to the WC_BASE classes that clear `min_support`.

    These are weak labels (WorldCover is itself an automated product), so this base trails the
    IndiaSAT one — it's offered as an alternate *starting* scheme, not a replacement. Stays linear,
    so the EE band-math renderer reproduces it unchanged for any number of classes."""
    code2canon = {code: canon for code, canon, _, _ in WC_BASE}
    df = pd.read_csv(WC_CSV).dropna(subset=AE_COLS)
    df["wc"] = df.wc.astype(int)
    df = df[df.wc.isin(code2canon)].copy()
    df["y"] = df.wc.map(code2canon)
    keep = [c for c, n in df.y.value_counts().items() if n >= min_support]
    df = df[df.y.isin(keep)].reset_index(drop=True)

    model = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000))
    model.fit(df[AE_COLS].values, df.y.values)
    bundle = {"model": model, "features": AE_COLS, "classes": sorted(df.y.unique()),
              "scheme": "worldcover",
              "note": "effective WorldCover base — well-supported India classes only"}
    joblib.dump(bundle, out_path)
    print(f"saved WorldCover base -> {out_path} (classes={bundle['classes']}, n={len(df)})")
    return bundle


def retrain(node, balance="balanced", years=None, algo="linearsvc", embedding="ae"):
    """Retrain whichever classifier owns `node`: the root -> the base model (pooling all
    user-added base classes); any other node -> its split (resampling its examples). `balance`
    picks the imbalance remedy for a split: balanced (class weight) | undersample | oversample.
    `years` pools several years of Alpha Earth into the split for temporal robustness (#3); the
    base can't do this (its CSVs have no year column), so years is ignored at the root. `algo`
    picks the estimator or "auto" bake-off (#17); `embedding` picks ae vs tessera features (#16)."""
    if node == hierarchy.ROOT:
        return retrain_base()
    return train(node, resample=True, balance=balance, years=years, algo=algo, embedding=embedding)


# ----------------------------- relabel / hard-negatives -----------------------------
def relabel(src, true_class, retrain=True, n_pix=30):
    """'This polygon is Y, not X.' Add it as positive examples of the true class and
    retrain that class's parent. Within one split, a positive-Y is already a negative of
    its siblings. (Corrections to a *base* class would need a base refit; out of scope.)"""
    tree = hierarchy.load()
    parent = tree[true_class]["parent"]
    examples.add_examples(true_class, src, role="positive")
    print(f"relabelled -> positive examples of {true_class!r}")
    if retrain:
        train(parent, n_pix=n_pix, resample=True)


def add_hard_negatives(src, not_class, retrain=True, n_pix=30):
    """'These pixels are NOT X.' Stored as negative examples of `not_class`; the trainer
    folds them into the residual sibling when the parent has one (an ADD split). Without
    a residual sibling they can't be placed, so we warn and skip them in training."""
    tree = hierarchy.load()
    parent = tree[not_class]["parent"]
    examples.add_examples(not_class, src, role="negative")
    has_residual = any(sib == f"{parent}_other" for sib in tree[parent]["children"])
    if not has_residual:
        print(f"note: {parent!r} has no residual child; these negatives won't be used "
              f"until one exists (e.g. via an ADD).")
    print(f"stored hard-negatives against {not_class!r}")
    if retrain:
        train(parent, n_pix=n_pix, resample=True)


# ----------------------------- bake-off (4.5) -----------------------------
def bakeoff(parent="greenery", test_size=0.25):
    """Per-node (hierarchical) vs one flat multiclass, on the same honest split.

    Hierarchical = the deployed base 4-way model -> this parent's split, mapped to leaves.
    Flat = a single LinearSVC over all leaf classes. Reports both on a shared held-out set.
    """
    import infer
    split_data = build_split_dataset(parent, resample=False)        # parent's children
    base_cls = ["barren", "built_up", "water"]                       # base leaves we keep
    base = pd.read_csv(FULL_CSV, usecols=["polygon_id", "core_class"] + AE_COLS)
    base = base[base.core_class.isin(base_cls)].rename(columns={"core_class": "label"})
    base["poly"] = base.polygon_id.values
    base = base[["label", "poly"] + AE_COLS]

    data = pd.concat([base, split_data], ignore_index=True)
    X, y, groups = data[AE_COLS].values, data.label.values, data.poly.values
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=0)
                  .split(X, y, groups))

    # flat: one model over all leaves
    flat = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced")).fit(X[tr], y[tr])
    flat_pred = flat.predict(X[te])

    # hierarchical: deployed base model, then the parent's split where base says parent
    base_model = infer.load_model()["model"]
    split_model = joblib.load(os.path.join(REFINE_DIR, f"{parent}.joblib"))["model"]
    hier = base_model.predict(X[te]).astype(object)
    sel = hier == parent
    if sel.any():
        hier[sel] = split_model.predict(X[te][sel])

    labels = sorted(set(y))
    print(f"\n=== bake-off on {parent}'s leaves, shared test ({len(te)} px) ===")
    print("\n--- FLAT multiclass ---")
    print(classification_report(y[te], flat_pred, labels=labels, digits=3, zero_division=0))
    print("--- HIERARCHICAL (base -> split) ---")
    print(classification_report(y[te], hier, labels=labels, digits=3, zero_division=0))
    return labels


if __name__ == "__main__":
    train(resample="--resample" in sys.argv)
