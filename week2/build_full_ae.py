"""Build a pan-India Alpha Earth dataset across ALL polygons (full diversity).

Unlike Phase 2 (limited to 47 Tessera tiles), Alpha Earth is free/server-side, so
we sample the whole country. We cap the dominant built_up class for balance and
keep all polygons of the minority classes. A 1x1-deg spatial block id is recorded
so training can hold out whole regions (honest generalization eval).

Output: data/master_alpha_full.csv
  polygon_id, core_class, lat, lon, block, ae_000..ae_063
"""
import os
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import phase2_embeddings as p2

DATA = "data"
KNOWN = ["barren", "built_up", "greenery", "water"]
MAX_POLY_PER_CLASS = 300   # cap built_up; minorities have fewer anyway
N_PIX = 60
SEED = 2024


def main():
    g = gpd.read_file(os.path.join(DATA, "raw_polygons", "all_polygons.geojson"))
    g = g[g.core_class.isin(KNOWN)].copy()

    # balanced polygon selection: <= MAX_POLY_PER_CLASS per class, all regions
    rng = np.random.default_rng(SEED)
    picks = []
    for cls, sub in g.groupby("core_class"):
        idx = np.array(sub.index.tolist()); rng.shuffle(idx)
        picks += list(idx[:MAX_POLY_PER_CLASS])
    sel = g.loc[picks].reset_index(drop=True)
    print(f"polygons selected: {len(sel)} {sel.core_class.value_counts().to_dict()}")

    pts = p2.sample_interior_points(sel, n_pix=N_PIX, seed=SEED)
    # 1x1-deg spatial block id from each point
    pts["block"] = (np.floor(pts.lon).astype(int).astype(str) + "_"
                    + np.floor(pts.lat).astype(int).astype(str))
    print(f"sampled {len(pts)} points across {pts.block.nunique()} spatial blocks")

    ae = p2.sample_alpha_earth(pts)
    df = pd.concat([pts[["polygon_id", "core_class", "lat", "lon", "block"]]
                    .reset_index(drop=True),
                    ae.reset_index(drop=True)], axis=1)
    df = df.dropna(subset=[c for c in df.columns if c.startswith("ae_")])
    out = os.path.join(DATA, "master_alpha_full.csv")
    df.to_csv(out, index=False)
    print(f"wrote {len(df)} rows x {df.shape[1]} cols -> {out}")
    print("per-class pixels:", df.core_class.value_counts().to_dict())
    print("per-block polygons:", df.groupby('block').polygon_id.nunique().describe()[['min','50%','max']].to_dict())


if __name__ == "__main__":
    main()