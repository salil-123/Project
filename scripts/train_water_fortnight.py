"""Train the per-fortnight water classifier (#5/#7) — offline, so serving stays band-math.

Reads the shared seasonal-water polygons (data/inputs/seasonal_water.geojson, built by
prep_seasonal_water.py; each polygon carries its own date). For each polygon we sample interior
pixels on the raw Sentinel-1/2 feature composite *at that polygon's date*, pool all
water/non_water pixels, and fit a LINEAR model. Linear is the whole point: infer.classify_water_tiles
replays it as Earth-Engine band math for any fortnight, no download, dodging the memory wall that
forced the flood pipeline to go batch.

Whole polygons are held out for the test split (grouped by polygon) so the accuracy is honest.
Saves data/refine/water_fortnight.joblib and mints mc_water_fortnight_v1 in the zoo.

Run from repo root:  python scripts/train_water_fortnight.py [--n-pix 12] [--limit N]
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report, accuracy_score

import sampling
import sentinel
import catalogue

GEOJSON = ROOT / "data" / "inputs" / "seasonal_water.geojson"
OUT = ROOT / "data" / "refine" / "water_fortnight.joblib"
# dryland polygons to augment the non-water class with (#11 wk10): the base ground truth carries
# barren / built-up / greenery, i.e. the terrain the water model has never seen as a negative.
BASE_GT = ROOT / "data" / "selected_polygons.geojson"
AUGMENT_CLASSES = ["barren", "built_up", "greenery"]
AUGMENT_DATES = ["15022024", "15072024", "15112024"]      # dry/mid/monsoon, so negatives span seasons


def augment_negatives(n_pix, dates=AUGMENT_DATES):
    """Sample Sentinel features at barren/built-up/greenery polygons across a few dates, labelled
    non_water (#11). This teaches the classifier what dry land looks like so it stops calling
    everything outside a water body 'water'. Returns a frame (label=non_water, poly, feature bands)."""
    g = gpd.read_file(BASE_GT).to_crs(4326)
    g = g[g.core_class.isin(AUGMENT_CLASSES)].copy()
    g["poly"] = [f"aug:{c}:{i}" for i, c in enumerate(g.core_class)]
    pts = sampling.interior_points(g[["core_class", "poly", "geometry"]], n_pix=n_pix)
    frames = []
    for d in dates:
        try:
            feats = sentinel.sample_points(pts, sentinel.date_from_ddmmyyyy(d))
        except Exception as e:
            print(f"  augment date {d} skipped ({str(e)[:50]})")
            continue
        part = pts[["poly"]].reset_index(drop=True).copy()
        part["label"] = "non_water"
        frames.append(pd.concat([part, feats.reset_index(drop=True)], axis=1))
    out = pd.concat(frames, ignore_index=True).dropna(subset=sentinel.FEATURE_BANDS)
    print(f"augmented with {len(out)} dryland non-water pixels "
          f"({g.core_class.value_counts().to_dict()} polys x {len(dates)} dates)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pix", type=int, default=12, help="interior pixels sampled per polygon")
    ap.add_argument("--limit", type=int, default=0, help="cap polygons (0 = all) for a quick run")
    ap.add_argument("--augment", action="store_true",
                    help="add dryland (barren/built/greenery) non-water negatives (#11); "
                         "saves to water_fortnight_augmented.joblib, doesn't overwrite the deployed model")
    args = ap.parse_args()

    gdf = gpd.read_file(GEOJSON).to_crs(4326)
    if args.limit:
        gdf = gdf.iloc[:args.limit].copy()
    gdf["poly"] = [f"{r.name}:{r.get('name', i)}" for i, r in gdf.iterrows()]
    print(f"{len(gdf)} polygons; labels: {gdf.label.value_counts().to_dict()}")

    # interior points per polygon, carrying label + date + group id through
    pts = sampling.interior_points(gdf[["label", "date", "poly", "geometry"]], n_pix=args.n_pix)
    print(f"{len(pts)} interior points; sampling Sentinel features by date…")

    # one EE round-trip per distinct date (polygons of the same fortnight share a composite)
    frames = []
    dates = sorted(pts.date.unique())
    for k, d in enumerate(dates, 1):
        sub = pts[pts.date == d]
        try:
            feats = sentinel.sample_points(sub, sentinel.date_from_ddmmyyyy(d))
        except Exception as e:                 # a bad date/no-scene shouldn't sink the whole run
            print(f"  [{k}/{len(dates)}] {d}: skipped ({str(e)[:60]})")
            continue
        part = pd.concat([sub[["label", "poly"]].reset_index(drop=True),
                          feats.reset_index(drop=True)], axis=1)
        frames.append(part)
        if k % 20 == 0 or k == len(dates):
            print(f"  [{k}/{len(dates)}] dates sampled, rows so far: {sum(len(f) for f in frames)}")

    data = pd.concat(frames, ignore_index=True).dropna(subset=sentinel.FEATURE_BANDS)
    if args.augment:
        data = pd.concat([data, augment_negatives(args.n_pix)], ignore_index=True)
    print(f"\n{len(data)} usable pixels; class balance: {data.label.value_counts().to_dict()}")

    X = data[sentinel.FEATURE_BANDS].values
    y = data.label.values
    groups = data.poly.values
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=0).split(X, y, groups))

    model = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000))
    model.fit(X[tr], y[tr])
    pred = model.predict(X[te])
    acc = accuracy_score(y[te], pred)
    print(f"\n=== held-out water/non_water report ({len(te)} px) ===")
    print(classification_report(y[te], pred, digits=3))
    report = classification_report(y[te], pred, output_dict=True, zero_division=0)

    model.fit(X, y)                                   # refit on everything for the deployed model
    bundle = {"model": model, "features": "sentinel", "feature_bands": sentinel.FEATURE_BANDS,
              "classes": sorted(set(y)), "algo": "linearsvc",
              "report": report, "n_test": int(len(te)), "accuracy": float(acc),
              "augmented": bool(args.augment)}
    # the augmented model is the "works anywhere" experiment (#11 step-2 direction); keep it beside
    # the deployed within-water-body model, don't clobber it. Deployed = the plain run.
    out = ROOT / "data" / "refine" / ("water_fortnight_augmented.joblib" if args.augment else "water_fortnight.joblib")
    os.makedirs(out.parent, exist_ok=True)
    joblib.dump(bundle, out)
    print(f"\nsaved {out}")

    # extent = the polygons' footprint, so the card's map shows where it was trained
    w, s, e, n = gdf.total_bounds
    metrics = {"accuracy": float(acc), "n_test": int(len(te)),
               "per_class": {k: report[k] for k in bundle["classes"] if k in report}}
    # the augmented model gets its own card so both show in the zoo (only the plain one is served)
    if args.augment:
        card = {**bundle, "id_suffix": "augmented"}
        cid = catalogue.mint_water_card(card, extent_bbox=[float(w), float(s), float(e), float(n)],
                                        metrics=metrics, card_id="mc_water_fortnight_augmented_v1",
                                        name="Seasonal water (per-fortnight, +dryland negatives)")
    else:
        cid = catalogue.mint_water_card(bundle, extent_bbox=[float(w), float(s), float(e), float(n)],
                                        metrics=metrics)
    print(f"minted {cid}")


if __name__ == "__main__":
    main()
