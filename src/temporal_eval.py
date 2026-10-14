"""Temporal robustness for a classifier (#3): train on some years, test on others.

Vegetation (and everything else) shifts year to year, and Alpha Earth has a fresh annual mosaic
for each. Sir's ask: train on multiple years and check the model still handles years it never
saw. This tool does exactly that. It pools several *train* years, holds out both whole polygons
(spatial) and whole *eval* years (temporal), and compares a single-year baseline against the
multi-year model. The multi-year model should hold up better on the unseen years; that's the
temporal robustness. It also saves the pooled model as a deployable artifact.

Works on two label sources:
  - a split's example files      (--children acacia non_acacia)
  - any labelled polygon file    (--from-file data/selected_polygons.geojson --classes greenery water built_up barren)
so the same check runs on a fine split or on the four base classes.

(Alpha-Earth-only, since Tessera is 2024-only over India, and the base CSVs have no year column.)

Run from the repo root (so data/ paths resolve), needs live Earth Engine:
    python src/temporal_eval.py --children acacia non_acacia
    python src/temporal_eval.py --from-file data/selected_polygons.geojson \
        --classes greenery water built_up barren
"""
import argparse
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py
import config
import examples
import hierarchy
import sampling

AE_COLS = [f"ae_{i:03d}" for i in range(64)]
AE_YEARS = list(range(2017, 2025))            # Alpha Earth annual coverage
REFINE_DIR = config.project_path("data/refine")


# ---- two ways to get a labelled, embedded frame for a given year ----

def _frame_from_examples(children, year, n_pix):
    """Each child's example pixels sampled at one year, concatenated. build_training_frame tags
    label=child and a year-stable poly id ('{child}:{i}'), so polygons line up across years."""
    parts = [examples.build_training_frame(c, n_pix=n_pix, year=year) for c in children]
    return pd.concat(parts, ignore_index=True)


def _frame_from_file(path, class_col, classes, year, n_pix):
    """Same shape, but from any labelled polygon file (e.g. the base-class ground truth). Keeps a
    year-stable poly id per polygon so the held-out set is fixed across years."""
    import geopandas as gpd
    g = gpd.read_file(path).to_crs(4326)
    g = g[g[class_col].isin(classes)].reset_index(drop=True)
    g["label"] = g[class_col].values
    g["poly"] = [f"{c}:{i}" for i, c in enumerate(g["label"])]
    pts = sampling.interior_points(g[["label", "poly", "geometry"]], n_pix=n_pix)
    ae = sampling.sample_alpha(pts, year=year).reset_index(drop=True)
    df = pd.concat([pts[["label", "poly"]].reset_index(drop=True), ae], axis=1)
    return df.dropna(subset=AE_COLS).reset_index(drop=True)


# ---- the temporal checks (source-agnostic: they take a sample_fn(year) -> frame) ----

def _partition(ref, test_size, seed):
    """One train/test split of whole polygons, reused across years (poly ids are year-stable)."""
    tr, te = next(GroupShuffleSplit(1, test_size=test_size, random_state=seed)
                  .split(ref, ref.label, ref.poly))
    return set(ref.poly.iloc[tr]), set(ref.poly.iloc[te])


def _fit(frames, year_list, polys):
    """Fit on the given polys pooled over year_list."""
    d = pd.concat([frames[y][frames[y].poly.isin(polys)] for y in year_list], ignore_index=True)
    m = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced"))
    m.fit(d[AE_COLS].values, d.label.values)
    return m


def multiyear_eval(sample_fn, train_years, eval_years, test_size=0.25, seed=0, save_to=None):
    """Single-year baseline (newest train year) vs multi-year pooled model, both on the same
    held-out-polygon TRAIN set, scored on held-out polygons at each EVAL year (unseen years).
    Returns rows of (year, single_acc, multi_acc) and saves the multi-year model."""
    years = sorted(set(train_years) | set(eval_years))
    frames = {y: sample_fn(y) for y in years}
    train_polys, test_polys = _partition(frames[train_years[0]], test_size, seed)

    single = _fit(frames, [train_years[-1]], train_polys)   # newest single year
    multi = _fit(frames, train_years, train_polys)          # pooled multi-year

    rows = []
    for y in eval_years:
        te = frames[y][frames[y].poly.isin(test_polys)]
        Xte, yte = te[AE_COLS].values, te.label.values
        rows.append((y, accuracy_score(yte, single.predict(Xte)),
                        accuracy_score(yte, multi.predict(Xte))))
    if save_to:
        labels = sorted(frames[train_years[0]].label.unique())
        joblib.dump({"model": multi, "classes": labels, "features": "ae",
                     "years": train_years}, save_to)
    return rows


def temporal_matrix(sample_fn, years=AE_YEARS, test_size=0.25, seed=0):
    """Finer view: accuracy[a][b] for a model trained at single year a, tested at single year b."""
    frames = {y: sample_fn(y) for y in years}
    train_polys, test_polys = _partition(frames[years[0]], test_size, seed)
    acc = {a: {} for a in years}
    for a in years:
        m = _fit(frames, [a], train_polys)
        for b in years:
            te = frames[b][frames[b].poly.isin(test_polys)]
            acc[a][b] = accuracy_score(te.label.values, m.predict(te[AE_COLS].values))
    return years, acc


# ---- printing ----

def _print_multiyear(rows, train_years):
    print(f"\ntrained on {train_years} (pooled) vs newest single year {train_years[-1]}")
    print("held-out year | single-year | multi-year | gain")
    for y, s, m in rows:
        print(f"    {y}      |    {s:.3f}    |   {m:.3f}   | {m - s:+.3f}")
    avg_s = sum(s for _, s, _ in rows) / len(rows)
    avg_m = sum(m for _, _, m in rows) / len(rows)
    print(f"  mean over unseen years: single {avg_s:.3f}  multi {avg_m:.3f}  ({avg_m - avg_s:+.3f})")


def _print_matrix(years, acc):
    print("\naccuracy — rows = train year, cols = test year")
    print("       " + " ".join(f"{y}" for y in years))
    for a in years:
        print(f"  {a} " + " ".join(f"{acc[a][b]:.2f}" for b in years))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--children", nargs="+", help="split nodes with example polygons (e.g. acacia non_acacia)")
    ap.add_argument("--parent", help="read the children from this hierarchy node instead")
    ap.add_argument("--from-file", help="a labelled polygon file to sample instead of example files")
    ap.add_argument("--class-col", default="core_class", help="the class column in --from-file")
    ap.add_argument("--classes", nargs="+", help="which classes to keep from --from-file")
    ap.add_argument("--train-years", nargs="+", type=int, default=[2019, 2021, 2023])
    ap.add_argument("--eval-years", nargs="+", type=int, default=[2020, 2024])
    ap.add_argument("--n-pix", type=int, default=40)
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--matrix", action="store_true", help="also print the full single-year year×year grid")
    ap.add_argument("--save", help="path for the pooled multi-year model")
    args = ap.parse_args()

    if args.from_file:
        classes = args.classes or ["greenery", "water", "built_up", "barren"]
        sample_fn = lambda y: _frame_from_file(args.from_file, args.class_col, classes, y, args.n_pix)
        name, what = "base", f"{classes} from {args.from_file}"
    else:
        children = hierarchy.load()[args.parent]["children"] if args.parent else args.children
        if not children:
            ap.error("pass --children, --parent, or --from-file")
        sample_fn = lambda y: _frame_from_examples(children, y, args.n_pix)
        name, what = "_".join(children), str(children)

    save_to = args.save or f"{REFINE_DIR}/{name}_multiyear.joblib"
    print(f"temporal robustness for {what}")
    rows = multiyear_eval(sample_fn, args.train_years, args.eval_years,
                          test_size=args.test_size, save_to=save_to)
    _print_multiyear(rows, args.train_years)
    print(f"\nsaved pooled multi-year model -> {save_to}")

    if args.matrix:
        years, acc = temporal_matrix(sample_fn, test_size=args.test_size)
        _print_matrix(years, acc)


if __name__ == "__main__":
    main()
