"""Clustered split (week 24): split one class of the tree into k unnamed clusters, then name them.

Two paths, one result:
  Alpha Earth  everything in Earth Engine: the class's pixels on the current map, a 3 x 3 mean, PCA from
               Earth Engine's own covariance, a seeded sample, wekaKMeans. Only the mean, the components
               and the k centres come back, a few thousand numbers.
  Tessera      everything offline on the downloaded tiles: the class's pixels off the 10 m map, a 3 x 3
               mean, scikit-learn PCA and KMeans.

Either way PCA keeps the fewest components that explain 90% of the variance, and the centres get stored
as an ordinary linear split. Nearest centre is the largest c.z - |c|^2/2 with z = P(x - mean), which is
linear in x, so PCA folds into the weights: the AE split replays as band math like any other, the
Tessera split predicts like any other, and naming / merging is the usual relabel. Week 24's experiment
(week24/notes/clustered_split_results.md) is why: fitting on the class beats the whole box, PCA doesn't
calm the grain but the 3 x 3 mean does, and refits reshuffle clusters so the centres must be stored.
"""
import numpy as np

import logging_setup

log = logging_setup.get(__name__)

VARIANCE = 0.90       # PCA keeps the fewest components reaching this share of the variance
SMOOTH = 1            # neighbourhood radius in pixels: 1 = a 3 x 3 mean
EE_FIT_PIXELS = 5000  # Earth Engine's k-means: 20,000 ran out of memory in week 24
TE_FIT_PIXELS = 20000


def names(k):
    return [f"cluster{i + 1}" for i in range(k)]


def _bundle(mu, P, C, sizes, parent, features, meta):
    """The centres as a linear split: scaler subtracts the mean, one score per cluster.
    Clusters are numbered biggest first, so cluster1 is always the commonest kind of pixel."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    order = np.argsort(-np.asarray(sizes))
    C = np.asarray(C, float)[order]
    mu, P = np.asarray(mu, float), np.asarray(P, float)
    labels = names(len(C))
    sc = StandardScaler()
    sc.mean_, sc.scale_, sc.var_ = mu, np.ones_like(mu), np.ones_like(mu)
    sc.n_features_in_, sc.n_samples_seen_ = mu.size, 1
    nearest = LogisticRegression()          # just a linear scorer here, never fitted
    nearest.coef_ = C @ P                   # c.P(x - mean) ...
    nearest.intercept_ = -0.5 * (C ** 2).sum(1)   # ... - |c|^2 / 2
    nearest.classes_, nearest.n_features_in_ = np.array(labels), mu.size
    return {"model": Pipeline([("centre", sc), ("nearest", nearest)]), "classes": labels,
            "features": features, "algo": "kmeans", "parent": parent, "smooth": SMOOTH,
            "cluster": {**meta, "k": len(C), "dims": int(P.shape[0]),
                        "sizes": [int(s) for s in np.asarray(sizes)[order]]}}


def _dims(eigenvalues):
    v = np.clip(np.asarray(eigenvalues, float), 0, None)
    return int(np.searchsorted(np.cumsum(v) / v.sum(), VARIANCE) + 1)


def smooth_ee(img):
    """3 x 3 mean in Earth Engine. In metres so a 10 m request gets 3 x 3; coarse map zooms barely smooth."""
    return img.focalMean(10 * SMOOTH + 5, "square", "meters")


def fit_ae(parent, bbox, year, k=8, seed=7):
    """Cluster `parent`'s pixels in Earth Engine and return the split bundle."""
    import infer
    ee, final, classes, region, _ = infer._labelled_bbox(bbox, year, None, None, None)
    if parent not in classes:
        raise ValueError(f"{parent} isn't drawn in Earth Engine here (it sits under a Tessera or Random "
                         "Forest split); use the Tessera path for it")
    bands, _ = infer._alpha_image(ee, bbox, year)
    feats = smooth_ee(bands).updateMask(final.eq(classes.index(parent)))
    stats = dict(geometry=region, scale=20, maxPixels=int(1e9), tileScale=4)
    mean = feats.reduceRegion(ee.Reducer.mean(), **stats)
    mu = ee.Array(mean.values(infer.BANDS))
    centred = feats.toArray().subtract(ee.Image(mu))
    cov = centred.reduceRegion(ee.Reducer.centeredCovariance(), **stats).values().get(0)
    share = final.eq(classes.index(parent)).reduceRegion(ee.Reducer.mean(), **stats).values().get(0)
    pca = ee.Dictionary({"mu": mu, "eig": ee.Array(cov).eigen(), "share": share}).getInfo()
    eig = np.array(pca["eig"])
    d = _dims(eig[:, 0])
    P = eig[:d, 1:]
    pcs = [f"pc{i}" for i in range(d)]
    proj = (ee.Image(ee.Array(P.tolist())).matrixMultiply(centred.toArray(1))
            .arrayProject([0]).arrayFlatten([pcs]))
    # sample() counts pixels over the whole box and then drops the masked ones, so ask for more when the
    # class is a small part of the box, else a 3% class would be clustered on 150 pixels
    ask = int(min(EE_FIT_PIXELS / max(pca["share"] or 0, 0.05), 20 * EE_FIT_PIXELS))
    sample = proj.sample(region=region, scale=10, numPixels=ask, seed=seed,
                         geometries=False, tileScale=4)
    km = ee.Clusterer.wekaKMeans(nClusters=k, seed=seed).train(sample, pcs)
    done = sample.cluster(km)
    centres = done.reduceColumns(ee.Reducer.mean().repeat(d).group(groupField=d, groupName="cluster"),
                                 pcs + ["cluster"])
    got = ee.Dictionary({"groups": centres.get("groups"),
                         "sizes": done.aggregate_histogram("cluster")}).getInfo()
    groups = sorted(got["groups"], key=lambda g: g["cluster"])
    if len(groups) < 2:
        raise ValueError(f"too few {parent} pixels in this box to cluster")
    C = [g["mean"] for g in groups]
    sizes = [got["sizes"].get(str(g["cluster"]), 0) for g in groups]
    log.info("AE clusters for %s: k=%d dims=%d fitted on %d px", parent, len(C), d, sum(sizes))
    return _bundle(pca["mu"], P, C, sizes, parent, "ae",
                   {"embedding": "alphaearth", "fitted_in": "earth engine", "bbox": list(bbox),
                    "year": int(year), "seed": seed, "pixels": int(sum(sizes))})


def fit_te(parent, bbox, year, k=8, seed=7):
    """Cluster `parent`'s pixels on the Tessera tiles, offline, and return the split bundle."""
    import infer
    import tessera_tiles
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    r = infer.classify_bbox_te_raster(bbox, year)     # the 10 m map with every split, Tessera ones too
    classes, codes = r["classes"], r["codes"].reshape(-1)
    if parent not in classes:
        raise ValueError(f"no {parent} pixels on the map in this box")
    idx = np.flatnonzero(codes == classes.index(parent))
    if idx.size < 10 * k:
        raise ValueError(f"too few {parent} pixels in this box to cluster")
    idx = np.random.default_rng(seed).choice(idx, min(TE_FIT_PIXELS, idx.size), replace=False)
    width, _, dx, dy = infer._te_grid(bbox)
    w, _, _, n = bbox
    row, col = np.divmod(idx, width)
    tessera_tiles.prefetch(tessera_tiles.box_points(bbox), year)
    X = tessera_tiles.sample_mean(w + (col + 0.5) * dx, n - (row + 0.5) * dy, dx, dy, year, SMOOTH)
    X = X[~np.isnan(X).any(1)]
    pca = PCA(VARIANCE, svd_solver="full").fit(X)
    km = KMeans(k, n_init=3, random_state=seed).fit(pca.transform(X))
    return _bundle(pca.mean_, pca.components_, km.cluster_centers_, np.bincount(km.labels_, minlength=k),
                   parent, "tessera", {"embedding": "tessera", "fitted_in": "offline", "bbox": list(bbox),
                                       "year": int(year), "seed": seed, "pixels": int(len(X))})
