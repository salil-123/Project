"""Tessera tiles: one place for where they live and how they get fetched.

Tessera's data moved to Source Cooperative (data.source.coop/tessera/tessera); the dl2.geotessera.org
server that geotessera 0.8 downloads from is gone. So we fetch each tile's three files ourselves, straight
into geotessera's own folder layout, and geotessera only ever reads them from disk:
  npy/v1/<year>/<grid>/<grid>.npy           the embedding, ~150 MB
  npy/v1/<year>/<grid>/<grid>_scales.npy    its dequantising scales
  landmasks/v1/<grid>.tiff                  the tile's land mask and projection
The big file comes down as parallel byte ranges, about twice as fast as one stream. Downloads go through
urllib, which follows HTTPS_PROXY like everything else on the tower.
"""
import functools
import math
import os
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor

import config

warnings.filterwarnings("ignore", module="geotessera")

SOURCE = os.getenv("TESSERA_SOURCE", "https://data.source.coop/tessera/tessera").rstrip("/")
# Source Cooperative turns away urllib's default "Python-urllib" user agent with a 403, so name ourselves
_UA = {"User-Agent": "corestack-lulc (Tessera tiles)"}

# geotessera's own index of tiles covers the world (4.4M rows, 2.4 GB in memory and a 350 MB download).
# We only ever read India for 2024, so the repo carries that slice (60k rows, 15 MB), cut from the full
# one with the same columns. A fixed local index also means no "is it still current?" call to the server.
INDEX_DIR = config.PROJECT_ROOT / "tessera_index"     # beside the code, not on the data mount


@functools.lru_cache(maxsize=1)
def client():
    """A GeoTessera that reads our India index and the tiles prefetch() placed under config.TESSERA_DIR.
    Hash checks are off: the files come from Tessera's own store, by exact byte ranges."""
    from geotessera import GeoTessera
    config.TESSERA_DIR.mkdir(parents=True, exist_ok=True)
    return GeoTessera(embeddings_dir=config.TESSERA_DIR, registry_dir=INDEX_DIR, verify_hashes=False)


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
    got = 0
    for lon, lat in {_snap(lon, lat) for lon, lat in points}:
        for url, dest in _files(lon, lat, year):
            if dest.exists():
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
    return got


def sample(points, year=2024):
    """Tessera 128-d at each (lon, lat), fetching any missing tile data first. Never downloads through
    geotessera itself (auto_download off), whose old server no longer exists."""
    prefetch(points, year)
    return client().sample_embeddings_at_points(points, year=year, auto_download=False)
