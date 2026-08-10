"""AOI size checks (#3): keep a drawn bounding box from exploding compute/download.

A user can draw any rectangle on the map. The AE tile path is cheap (EE renders tiles on
demand), but the GeoTIFF export is size-capped by EE and the Tessera path downloads ~150 MB
per 0.1 degree tile — so an over-large box silently turns into a very slow (or failing)
request. These helpers turn a bbox into an honest area, and `check()` gates each render path
against the admin-tunable caps in config.py. Pure math; no EE, no I/O.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py
import config

# rough metres-per-degree of latitude; longitude shrinks by cos(lat)
_M_PER_DEG = 111_320.0
_TESSERA_CELL = 0.1          # geotessera tile size in degrees (see tessera_fast._snap)


def area_km2(bbox):
    """Equal-area size of a (west, south, east, north) box in km^2. Uses the mean latitude
    to shrink the east-west span, so it stays honest away from the equator."""
    w, s, e, n = bbox
    mid = math.radians((s + n) / 2)
    width_m = abs(e - w) * _M_PER_DEG * math.cos(mid)
    height_m = abs(n - s) * _M_PER_DEG
    return (width_m * height_m) / 1e6


def tessera_tiles(bbox):
    """How many 0.1 deg Tessera tiles a bbox touches — the count that drives download size."""
    w, s, e, n = bbox
    cols = math.floor(e / _TESSERA_CELL) - math.floor(w / _TESSERA_CELL) + 1
    rows = math.floor(n / _TESSERA_CELL) - math.floor(s / _TESSERA_CELL) + 1
    return max(1, cols) * max(1, rows)


def valid_bbox(bbox):
    """Is the box a real, non-degenerate rectangle? A user can POST raw west/south/east/north, so
    an inverted (west>east) or zero-area (west==east) box can slip in and reach Earth Engine as a
    null-dimension geometry — which errors opaquely or paints nonsense. Catch it here, where every
    render path already gates. Returns (ok, reason)."""
    w, s, e, n = bbox
    if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0 and -90.0 <= s <= 90.0 and -90.0 <= n <= 90.0):
        return False, "Coordinates are out of range (longitude -180..180, latitude -90..90)."
    if e <= w or n <= s:
        return False, ("This box is degenerate: west must be below east and south below north "
                       "(you may have drawn it backwards, or as a line/point).")
    return True, ""


def check(bbox, path="tiles"):
    """Is this bbox within the cap for the given render `path` (tiles | geotiff | tessera)?

    Returns {ok, area, cap, reason}. `reason` is a ready-to-show message when ok is False."""
    ok_box, why = valid_bbox(bbox)
    if not ok_box:
        return {"ok": False, "area": round(area_km2(bbox), 1), "cap": None, "reason": why}
    area = area_km2(bbox)
    if path == "tessera":
        tiles = tessera_tiles(bbox)
        cap = config.AOI_TESSERA_MAX_TILES
        ok = tiles <= cap
        reason = "" if ok else (f"This area needs {tiles} Tessera tiles (~{tiles*150} MB to "
                                f"download); the limit is {cap}. Zoom in or use the Realistic tiles.")
        return {"ok": ok, "area": round(area, 1), "cap": cap, "tiles": tiles, "reason": reason}

    cap = config.AOI_GEOTIFF_CAP_KM2 if path == "geotiff" else config.AOI_TILE_CAP_KM2
    ok = area <= cap
    what = "GeoTIFF export" if path == "geotiff" else "classification"
    reason = "" if ok else (f"This area is ~{area:,.0f} km^2; the {what} limit is "
                            f"{cap:,.0f} km^2. Draw a smaller box.")
    return {"ok": ok, "area": round(area, 1), "cap": cap, "reason": reason}


if __name__ == "__main__":
    # a ~4x4 km IIT box is tiny; an all-India box is way over the tile cap
    small = (77.165, 28.520, 77.205, 28.560)
    india = (68.0, 6.5, 97.5, 37.5)
    print("small:", check(small), "tessera:", check(small, "tessera"))
    print("india tiles:", check(india), "geotiff:", check(india, "geotiff"))
    assert check(small)["ok"] and check(small, "geotiff")["ok"]
    assert not check(india)["ok"] and not check(india, "geotiff")["ok"]
    # degenerate / inverted boxes must be refused before they reach EE
    for bad in [(77.2, 28.5, 77.2, 28.56), (77.16, 28.55, 77.2, 28.55),
                (77.205, 28.52, 77.165, 28.56), (77.165, 28.56, 77.205, 28.52)]:
        assert not check(bad)["ok"], f"BUG: accepted degenerate box {bad}"
    print("aoi.py smoke test OK")
