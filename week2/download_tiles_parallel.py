"""EXPERIMENT (separate from download_tiles.py): can we speed up a SINGLE tile by
downloading it in parallel byte-range chunks?

download_tiles.py parallelizes across tiles (one connection per tile). Here we test
within-tile parallelism: split one ~156 MB tile into N byte ranges and fetch them
concurrently, then stitch. This only helps if the server throttles per-connection
rather than per-IP -- the benchmark tells us which.

  python download_tiles_parallel.py --benchmark           # auto-pick an un-cached tile
  python download_tiles_parallel.py --benchmark --workers 8
  python download_tiles_parallel.py --benchmark --lon 75.95 --lat 12.35

Nothing here touches download_tiles.py or the real cache; it downloads to temp and
cleans up. To revert: just delete this file.
"""
import argparse, json, math, os, tempfile, time, warnings
import urllib.request
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")
import geotessera.registry as R
from geotessera import GeoTessera
from geotessera.registry import tile_to_embedding_paths


def tile_url(lon, lat, year):
    emb, _ = tile_to_embedding_paths(lon, lat, year)
    gt = GeoTessera()
    return f"{R.TESSERA_BASE_URL}/{gt.registry.version}/{R.EMBEDDINGS_DIR_NAME}/{emb.as_posix()}"


def head(url):
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
        return int(r.headers.get("Content-Length", 0)), r.headers.get("Accept-Ranges")


def download_single(url, dest):
    """Baseline: one connection, streamed to disk (what geotessera effectively does)."""
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        while True:
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)


def download_chunked(url, dest, workers, size):
    """Split [0, size) into `workers` ranges, fetch each concurrently, stitch in order."""
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


def pick_uncached_tile():
    """An asset tile we have NOT downloaded yet, so the test is a genuine cold pull."""
    import geopandas as gpd
    g = gpd.read_file("data/raw_polygons/all_polygons.geojson")
    c = gpd.GeoSeries(g.to_crs(3857).geometry.centroid, crs=3857).to_crs(4326)
    snap = lambda lo, la: (round(math.floor(lo / 0.1) * 0.1 + 0.05, 2),
                           round(math.floor(la / 0.1) * 0.1 + 0.05, 2))
    tiles = {snap(x, y) for x, y in zip(c.x, c.y)}
    from pathlib import Path
    for lon, lat in sorted(tiles):
        d = Path("global_0.1_degree_representation") / "2024" / f"grid_{lon:.2f}_{lat:.2f}"
        if not (d / f"grid_{lon:.2f}_{lat:.2f}.npy").exists():
            return lon, lat
    return sorted(tiles)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--lat", type=float)
    args = ap.parse_args()

    lon, lat = (args.lon, args.lat) if args.lon is not None else pick_uncached_tile()
    url = tile_url(lon, lat, 2024)
    size, ranges_ok = head(url)
    print(f"tile ({lon:.2f},{lat:.2f})  {size/1e6:.1f} MB  Accept-Ranges={ranges_ok}")
    if ranges_ok != "bytes":
        print("server does not advertise byte ranges; within-tile parallelism won't work.")
        return

    tmp = tempfile.mkdtemp()
    try:
        # baseline: single connection
        d1 = os.path.join(tmp, "single.npy")
        t = time.time(); download_single(url, d1); t1 = time.time() - t
        print(f"  single-stream : {t1:6.1f}s  ({size/1e6/t1:5.2f} MB/s)")

        # within-tile parallel
        d2 = os.path.join(tmp, "chunked.npy")
        t = time.time(); download_chunked(url, d2, args.workers, size); t2 = time.time() - t
        print(f"  {args.workers}-way chunked: {t2:6.1f}s  ({size/1e6/t2:5.2f} MB/s)")

        ok = os.path.getsize(d1) == os.path.getsize(d2) == size
        print(f"  sizes match: {ok}  |  speedup: {t1/t2:.2f}x")
    finally:
        for f in os.listdir(tmp):
            os.remove(os.path.join(tmp, f))
        os.rmdir(tmp)


if __name__ == "__main__":
    main()
