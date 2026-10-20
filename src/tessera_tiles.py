"""Tessera tiles: one place for where they live and how they get fetched.

Tessera's data moved to Source Cooperative (data.source.coop/tessera/tessera); the dl2.geotessera.org
server that geotessera 0.8 downloads from is gone. So we fetch each tile's three files ourselves (into
geotessera's folder layout, so tiles cached before still count) and read them ourselves too:
  npy/v1/<year>/<grid>/<grid>.npy           the embedding, ~150 MB
  npy/v1/<year>/<grid>/<grid>_scales.npy    its dequantising scales
  landmasks/v1/<grid>.tiff                  the tile's land mask and projection
The big file comes down as parallel byte ranges, about twice as fast as one stream. Downloads go through
urllib, which follows HTTPS_PROXY like everything else on the tower.
"""
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import config

SOURCE = os.getenv("TESSERA_SOURCE", "https://data.source.coop/tessera/tessera").rstrip("/")
# Source Cooperative turns away urllib's default "Python-urllib" user agent with a 403, so name ourselves
_UA = {"User-Agent": "corestack-lulc (Tessera tiles)"}


def _snap(lon, lat):
    return (round(math.floor(lon / 0.1) * 0.1 + 0.05, 2),
            round(math.floor(lat / 0.1) * 0.1 + 0.05, 2))


def _files(lon, lat, year):
    """(url, local path) for each file one tile needs, in geotessera's layout under TESSERA_DIR."""
    grid = f"grid_{lon:.2f}_{lat:.2f}"
    here = config.TESSERA_DIR / "global_0.1_degree_representation" / str(year) / grid
    return [(f"{SOURCE}/npy/v1/{year}/{grid}/{grid}.npy", here / f"{grid}.npy"),
            (f"{SOURCE}/npy/v1/{year}/{grid}/{grid}_scales.npy", here / f"{grid}_scales.npy"),
            (f"{SOURCE}/landmasks/v1/{grid}.tiff",
             config.TESSERA_DIR / "global_0.1_degree_tiff_all" / f"{grid}.tiff")]


def _fetch(url, dest, workers):
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=_UA), timeout=30) as r:
        size, ranges = int(r.headers.get("Content-Length", 0)), r.headers.get("Accept-Ranges")
    if ranges != "bytes" or size < (8 << 20):          # small files: one plain request
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=120) as r,                 open(dest, "wb") as f:
            while buf := r.read(1 << 20):
                f.write(buf)
        return
    step = math.ceil(size / workers)
    spans = [(i * step, min((i + 1) * step, size) - 1) for i in range(workers)]

    def grab(span):
        req = urllib.request.Request(url, headers={**_UA, "Range": f"bytes={span[0]}-{span[1]}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(grab, spans))
    with open(dest, "wb") as f:
        for p in parts:
            f.write(p)


def prefetch(points, year=2024, workers=8):
    """Fetch whatever the tiles under these (lon, lat) points are missing. Returns how many files it
    got; raises with the reason if one can't be fetched, since geotessera has nowhere else to get it."""
    got, needed = 0, set()
    for lon, lat in {_snap(lon, lat) for lon, lat in points}:
        for url, dest in _files(lon, lat, year):
            needed.add(dest)
            if dest.exists():
                os.utime(dest)                   # used now: the cache cap evicts by this
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            try:
                _fetch(url, tmp, workers)
            except Exception as e:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"couldn't fetch Tessera tile data from {SOURCE} ({e})") from e
            os.replace(tmp, dest)                # only ever appears whole
            got += 1
    if got:
        _evict(keep=needed)
    return got


def _evict(keep=()):
    """Keep the cache under TESSERA_CACHE_GB: the files used longest ago go first, never the ones the
    current request needs. Leftover .part files from a killed download go too."""
    files = [f for f in config.TESSERA_DIR.rglob("*") if f.is_file() and f.suffix in (".npy", ".tiff", ".part")]
    files.sort(key=lambda f: f.stat().st_mtime)
    total, cap = sum(f.stat().st_size for f in files), config.TESSERA_CACHE_GB * (1 << 30)
    for f in files:
        if total <= cap:
            break
        if f in keep:
            continue
        total -= f.stat().st_size
        f.unlink(missing_ok=True)


def sample(points, year=2024):
    """Tessera 128-d at each (lon, lat), fetching any missing tile data first."""
    prefetch(points, year)
    lons, lats = zip(*points) if points else ((), ())
    return sample_many(lons, lats, year)


def sample_many(lons, lats, year=2024):
    """Tessera 128-d for any number of pixels at once, a whole 10 m map included (geotessera's own
    sampler loops per point in Python and loads each tile whole, ~600 MB once dequantised). The tiles are memory-mapped and only the pixels asked for get dequantised, so a 150 MB tile never
    sits in memory whole. Assumes prefetch() already ran; a missing tile leaves its pixels NaN."""
    import rasterio
    from pyproj import Transformer
    lons, lats = np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)
    out = np.full((len(lons), 128), np.nan, dtype=np.float32)
    # same snapping as _snap, done on the whole array
    tlon = np.round(np.floor(lons / 0.1) * 0.1 + 0.05, 2)
    tlat = np.round(np.floor(lats / 0.1) * 0.1 + 0.05, 2)
    for lon, lat in set(zip(tlon.tolist(), tlat.tolist())):
        (_, npy), (_, scl), (_, tif) = _files(lon, lat, year)
        if not (npy.exists() and scl.exists() and tif.exists()):
            continue
        sel = np.flatnonzero((tlon == lon) & (tlat == lat))
        with rasterio.open(tif) as src:
            crs, tf = src.crs, src.transform
        x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lons[sel], lats[sel])
        col, row = ~tf * (x, y)
        row, col = np.floor(row).astype(int), np.floor(col).astype(int)
        emb, sc = np.load(npy, mmap_mode="r"), np.load(scl, mmap_mode="r")
        ok = (row >= 0) & (row < emb.shape[0]) & (col >= 0) & (col < emb.shape[1])
        r, c = row[ok], col[ok]
        scale = sc[r, c]
        out[sel[ok]] = emb[r, c].astype(np.float32) * (scale[:, None] if scale.ndim == 1 else scale)
    return out
