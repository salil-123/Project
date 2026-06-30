"""Faster on-demand Tessera tile fetch for the live tool's Detailed mode.

geotessera downloads each tile over a single connection. The server throttles
per-connection, so splitting one ~150 MB tile into parallel byte-range chunks
roughly doubles throughput (see download_tiles_parallel.py benchmark, ~2x).

Here we pre-fetch the big embedding .npy for whatever tiles a request needs, using
chunked-parallel range requests, into geotessera's own cache layout. geotessera then
finds it cached and only grabs the small scales/landmask files itself. If anything
fails we just skip it and let geotessera download normally -- so this can only help.
"""
import math, os, urllib.request, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

warnings.filterwarnings("ignore")
import geotessera.registry as R
from geotessera import GeoTessera
from geotessera.registry import tile_to_embedding_paths

_VERSION = None


def _version():
    global _VERSION
    if _VERSION is None:
        _VERSION = GeoTessera().registry.version
    return _VERSION


def _snap(lon, lat):
    return (round(math.floor(lon / 0.1) * 0.1 + 0.05, 2),
            round(math.floor(lat / 0.1) * 0.1 + 0.05, 2))


def _emb_url(lon, lat, year):
    emb, _ = tile_to_embedding_paths(lon, lat, year)
    return f"{R.TESSERA_BASE_URL}/{_version()}/{R.EMBEDDINGS_DIR_NAME}/{emb.as_posix()}"


def _cache_path(lon, lat, year):
    grid = f"grid_{lon:.2f}_{lat:.2f}"
    return Path("global_0.1_degree_representation") / str(year) / grid / f"{grid}.npy"


def _head(url):
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
        return int(r.headers.get("Content-Length", 0)), r.headers.get("Accept-Ranges")


def _download_chunked(url, dest, workers, size):
    step = math.ceil(size / workers)
    ranges = [(i * step, min((i + 1) * step, size) - 1) for i in range(workers)]
    parts = [None] * workers

    def grab(idx, start, end):
        req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            parts[idx] = r.read()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda a: grab(*a), [(i, s, e) for i, (s, e) in enumerate(ranges)]))
    with open(dest, "wb") as f:
        for p in parts:
            f.write(p)


def _download_single(url, dest):
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        while True:
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)


def download_tile_fast(lon, lat, year=2024, workers=8):
    """Fetch one tile's embedding .npy via chunked-parallel ranges. Returns True if
    it actually downloaded, False if already cached. Raises on network failure."""
    dest = _cache_path(lon, lat, year)
    if dest.exists():
        return False
    url = _emb_url(lon, lat, year)
    size, ranges_ok = _head(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    if ranges_ok == "bytes" and size > 0:
        _download_chunked(url, tmp, workers, size)
    else:
        _download_single(url, tmp)
    os.replace(tmp, dest)  # atomic: only appears complete
    return True


def prefetch_for_points(pts, year=2024, workers=8):
    """Pre-download (fast) every tile the points fall in. Best-effort: a tile that
    fails here is left for geotessera to fetch normally at sample time."""
    tiles = {_snap(lon, lat) for lon, lat in pts}
    fetched = 0
    for lon, lat in tiles:
        try:
            if download_tile_fast(lon, lat, year, workers):
                fetched += 1
        except Exception:
            pass  # silent fallback to geotessera's own download
    return fetched