"""Download the selected Tessera tiles in parallel. Run on a FAST connection.

Tessera throttles per-connection (~0.5 Mbps/stream observed on a slow link), so we
parallelize tile downloads with a thread pool. Idempotent + resumable: tiles already
on disk are skipped, so you can stop/restart freely.

Usage:
    python download_tiles.py            # default 6 workers
    python download_tiles.py --workers 8
Tiles land in ./global_0.1_degree_representation/<year>/grid_<lon>_<lat>/.
"""
import argparse
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

warnings.filterwarnings("ignore")
from geotessera import GeoTessera

YEAR = 2024
DATA = "data"


def tile_path(lon, lat, year=YEAR):
    d = Path("global_0.1_degree_representation") / str(year) / f"grid_{lon:.2f}_{lat:.2f}"
    return d / f"grid_{lon:.2f}_{lat:.2f}.npy"


def download_one(lon, lat):
    # verify_hashes=False avoids re-downloading already-complete tiles
    gt = GeoTessera(verify_hashes=False)
    t = time.time()
    try:
        gt.download_tile(lon=lon, lat=lat, year=YEAR)
        sz = tile_path(lon, lat).stat().st_size / 1e6 if tile_path(lon, lat).exists() else 0
        return (lon, lat, True, time.time() - t, sz)
    except Exception as e:
        return (lon, lat, False, time.time() - t, repr(e)[:60])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    tiles = [tuple(t) for t in json.load(open(os.path.join(DATA, "selected_tiles.json")))["tiles"]]
    todo = [(lo, la) for lo, la in tiles if not tile_path(lo, la).exists()]
    print(f"{len(tiles)} selected, {len(tiles)-len(todo)} already cached, "
          f"{len(todo)} to download with {args.workers} workers", flush=True)
    if not todo:
        print("all tiles present — nothing to do."); return

    t0, done, mb = time.time(), 0, 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download_one, lo, la): (lo, la) for lo, la in todo}
        for fut in as_completed(futs):
            lo, la, ok, dt, info = fut.result()
            done += 1
            if ok:
                mb += info
                eta = (time.time() - t0) / done * (len(todo) - done) / 60
                print(f"  [{done}/{len(todo)}] OK {lo:.2f},{la:.2f} {dt:5.0f}s {info:4.0f}MB "
                      f"| ETA {eta:.0f} min", flush=True)
            else:
                print(f"  [{done}/{len(todo)}] FAIL {lo:.2f},{la:.2f} -> {info}", flush=True)
    print(f"\nDONE in {(time.time()-t0)/60:.0f} min, {mb/1000:.1f} GB. "
          f"Next: python phase2_embeddings.py --polygons data/selected_polygons.geojson "
          f"--out data/master_tessera.csv", flush=True)


if __name__ == "__main__":
    main()