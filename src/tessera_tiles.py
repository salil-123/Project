"""Tessera tiles: one place for where they live and how they get fetched.

geotessera pulls a ~150 MB tile over a single connection, and the server throttles per connection, so
splitting a tile into parallel byte ranges roughly doubles the speed. prefetch() does that into
geotessera's own folder layout, then geotessera finds the tile there and only fetches the small
scales/landmask files itself. Anything that fails here is left to geotessera, so it can only help.
Downloads go through urllib, which follows HTTPS_PROXY like everything else on the tower.
"""
import functools
import math
import os
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor

import config

warnings.filterwarnings("ignore", module="geotessera")
_version = None


# geotessera's own index of tiles covers the world (4.4M rows, 2.4 GB in memory and a 350 MB download).
# We only ever read India for 2024, so the repo carries that slice (60k rows, 15 MB), cut from the full
# one with the same columns. A fixed local index also means no "is it still current?" call to the server.
INDEX_DIR = config.PROJECT_ROOT / "tessera_index"     # beside the code, not on the data mount


@functools.lru_cache(maxsize=1)
def client():
    """A GeoTessera that reads our India index and keeps tiles under config.TESSERA_DIR. Hash checks are
    off so it trusts the tiles prefetch() placed (same server, exact byte ranges)."""
    from geotessera import GeoTessera
    config.TESSERA_DIR.mkdir(parents=True, exist_ok=True)
    return GeoTessera(embeddings_dir=config.TESSERA_DIR, registry_dir=INDEX_DIR, verify_hashes=False)


def _snap(lon, lat):
    return (round(math.floor(lon / 0.1) * 0.1 + 0.05, 2),
            round(math.floor(lat / 0.1) * 0.1 + 0.05, 2))


def _url(lon, lat, year):
    global _version
    import geotessera.registry as R
    if _version is None:
        _version = client().registry.version
    emb, _ = R.tile_to_embedding_paths(lon, lat, year)
    return f"{R.TESSERA_BASE_URL}/{_version}/{R.EMBEDDINGS_DIR_NAME}/{emb.as_posix()}"


def _path(lon, lat, year):
    grid = f"grid_{lon:.2f}_{lat:.2f}"
    return config.TESSERA_DIR / "global_0.1_degree_representation" / str(year) / grid / f"{grid}.npy"


def _fetch(url, dest, workers):
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
        size, ranges = int(r.headers.get("Content-Length", 0)), r.headers.get("Accept-Ranges")
    if ranges != "bytes" or not size:
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
            while buf := r.read(1 << 20):
                f.write(buf)
        return
    step = math.ceil(size / workers)
    spans = [(i * step, min((i + 1) * step, size) - 1) for i in range(workers)]

    def grab(span):
        req = urllib.request.Request(url, headers={"Range": f"bytes={span[0]}-{span[1]}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(grab, spans))
    with open(dest, "wb") as f:
        for p in parts:
            f.write(p)


def prefetch(points, year=2024, workers=8):
    """Fetch every tile the (lon, lat) points fall in that isn't here yet. Returns how many it got."""
    got = 0
    for lon, lat in {_snap(lon, lat) for lon, lat in points}:
        dest = _path(lon, lat, year)
        if dest.exists():
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            _fetch(_url(lon, lat, year), tmp, workers)
            os.replace(tmp, dest)            # only ever appears whole
            got += 1
        except Exception:
            pass                             # geotessera fetches it the slow way
    return got
