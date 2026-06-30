"""Tea vs non-tea — a standalone test of whether Alpha Earth separates tea plantations.

Sir suggested splitting trees into tea / non-tea. This is *only a measurement*: it does
NOT touch the hierarchy, the base model, or the catalogue. It samples Alpha Earth at the
hand-marked polygons in manual_polygons.geojson (105 tea / 64 non-tea), holds out whole
polygons, fits the same StandardScaler->LinearSVC the refine engine uses, and reports how
well the embedding tells tea from non-tea. If it scores well, a real trees->tea/non-tea
split is worth wiring in later.

Run from repo root:  python week5/tea_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))     # reuse the live sampling code

import geopandas as gpd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score

import sampling

POLYGONS = ROOT / "data" / "inputs" / "manual_polygons.geojson"
N_PIX = 60          # interior pixels per polygon
TEST_SIZE = 0.30


def build_frame():
    """Sample Alpha Earth at interior pixels of each marked polygon. Label = tea / non_tea,
    group = polygon id so train/test never share a polygon's pixels."""
    gdf = gpd.read_file(POLYGONS).to_crs(4326)
    gdf["label"] = gdf["tea"].map(lambda t: "tea" if t else "non_tea")
    gdf["poly"] = [f"p{i}" for i in range(len(gdf))]
    print(f"{len(gdf)} polygons: " + ", ".join(f"{k}={v}" for k, v in gdf.label.value_counts().items()))

    pts = sampling.interior_points(gdf[["label", "poly", "geometry"]], n_pix=N_PIX)
    ae = sampling.sample_alpha(pts)
    df = pts[["label", "poly"]].reset_index(drop=True).join(ae.reset_index(drop=True))
    ae_cols = [c for c in df.columns if c.startswith("ae_")]
    return df.dropna(subset=ae_cols).reset_index(drop=True), ae_cols


def main():
    df, ae_cols = build_frame()
    X, y, groups = df[ae_cols].values, df.label.values, df.poly.values
    print(f"sampled {len(df)} pixels from {len(set(groups))} polygons\n")

    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=0)
                  .split(X, y, groups))
    model = make_pipeline(StandardScaler(), LinearSVC(class_weight="balanced", max_iter=5000))
    model.fit(X[tr], y[tr])
    pred = model.predict(X[te])

    labels = ["tea", "non_tea"]
    acc = accuracy_score(y[te], pred)
    report = classification_report(y[te], pred, labels=labels, digits=3, zero_division=0)
    cm = confusion_matrix(y[te], pred, labels=labels)

    print(f"=== tea / non-tea held-out report ({len(te)} px, {len(set(groups[te]))} polys) ===")
    print(f"accuracy: {acc:.3f}\n")
    print(report)
    print("confusion (rows=true, cols=pred):", labels)
    print(cm)

    out = ROOT / "week5" / "notes" / "tea_eval.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# Tea / non-tea — Alpha Earth separability (test only)\n\n"
        f"Source: `manual_polygons.geojson` ({len(set(groups))} polys, {N_PIX} px each).\n"
        f"Held-out by whole polygon (test_size={TEST_SIZE}). Model = StandardScaler->LinearSVC.\n\n"
        f"**Held-out accuracy: {acc:.3f}** on {len(te)} pixels.\n\n"
        f"```\n{report}\nconfusion {labels}\n{cm}\n```\n\n"
        f"Does NOT modify the hierarchy, base model, or catalogue — pure measurement of whether "
        f"the embedding separates tea from non-tea before committing to a real split.\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
