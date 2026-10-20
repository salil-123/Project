"""The water model as a 26 class split: the fortnight of the June to May year a pixel last held water.

Sir's week 22 ask: in the zoo the water model is just a 26 class model (fortnight1 ... fortnight26).
Used for a class, the user keeps those names or types their own, and the same name twice merges, so
June to October can become "kharif" and so on. Nothing water specific in the app; this module only
turns the bundle into a class index image, the way a rule or a linear split does in infer._refine_idx.

It's the shipped method (week16/district_raster.py + week21/water_pipeline.py), ported because the week
folders don't travel with the app. Same model json, same steps, same pixels:
  per fortnight   Sentinel-1 median within 7 days of the slot centre + cloud masked Sentinel-2 median
  sensor switch   radar + clear optical -> fusion, radar only -> s1, optical only -> s2, neither -> 255;
                  each case a pixel model and a 3x3/5x5 neighbourhood model, water if either says so
                  (no WorldCover built-up rule since 21 Oct 2026: on the independent ground truth it
                  bought 0.004 F1 for a whole extra input; water methodology doc, section 5.3)
  correction      over the whole year at once with 2 padding fortnights a side: gaps take the last seen
                  state, then a majority of 3
  label           index of the last wet fortnight (0..25); never wet -> masked, so it stays unlabelled
"""
from datetime import date, timedelta

import sentinel

LEN = 14                 # days in a slot
PAD = 2                  # slots built either side of the year, then dropped
WINDOW = 3               # fortnights in the majority vote
NODATA = 255
START_MONTH = 6          # the water year runs June to May
BAD_SCL = [1, 3, 8, 9, 10, 11]                 # saturated, shadow, cloud med/high, cirrus, snow
CLASSES = [f"fortnight{i}" for i in range(1, 27)]


def slots(year):
    """The 26 fourteen-day slots of the water year starting June `year`; the leftover day joins the last."""
    start, stop = date(year, START_MONTH, 1), date(year + 1, START_MONTH, 1)
    out, s = [], start
    while s < stop:
        e = min(s + timedelta(days=LEN), stop)
        if (stop - e).days < 7:                # a sliver under a week goes into this slot
            e = stop
        out.append((s, e))
        s = e
    return out


def _padded(year, pad=PAD):
    asked = slots(year)
    first, last = asked[0][0], asked[-1][1]
    before = [(first - timedelta(days=LEN * k), first - timedelta(days=LEN * (k - 1))) for k in range(pad, 0, -1)]
    after = [(last + timedelta(days=LEN * k), last + timedelta(days=LEN * (k + 1))) for k in range(pad)]
    return [(s, e, s + (e - s) / 2) for s, e in before + asked + after]


def _features(ee, region, start, end, centre):
    """The fortnight's bands, plus where it has a clear optical look and a radar pass."""
    s1 = sentinel._s1(ee, region, ee.Date(str(centre)))
    opt_bands = ["B3", "B4", "B8", "B8A", "B11"]

    def clear(img):
        ok = img.select("SCL").remap(BAD_SCL, [0] * len(BAD_SCL), 1)
        return img.select(opt_bands).updateMask(ok)

    opt = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
           .filterDate(str(start), str(end)).map(clear)
           .merge(ee.ImageCollection([sentinel._empty_with_bands(ee, opt_bands)])).median())
    b3, b4, b8, b11 = (opt.select(b) for b in ("B3", "B4", "B8", "B11"))
    nd = lambda a, b, n: a.subtract(b).divide(a.add(b).add(1e-6)).rename(n)
    vv, vh = s1.select("VV"), s1.select("VH")
    img = (vv.rename("VV").addBands(vh.rename("VH")).addBands(vv.subtract(vh).rename("VV_VH_ratio"))
           .addBands(nd(b3, b8, "NDWI")).addBands(nd(b3, b11, "MNDWI")).addBands(nd(b8, b4, "NDVI"))
           .addBands(opt.select(opt_bands)))
    return img, b3.mask().And(b8.mask()).And(b11.mask()), vv.mask().And(vh.mask())


def _with_means(ee, img, bands):
    """mean3_X / mean5_X: band X averaged over the 3x3 / 5x5 window, taken on the masked image."""
    for k, radius in ((3, 10), (5, 20)):
        src = sorted({b.split("_", 1)[1] for b in bands if b.startswith(f"mean{k}_")})
        if src:
            m = img.select(src).reduceNeighborhood(ee.Reducer.mean(), ee.Kernel.square(radius, "meters"))
            img = img.addBands(m.rename([f"mean{k}_{c}" for c in src]))
    return img


def _twins(m):
    return [m[k] for k in ("pixel", "neighbourhood") if k in m] or [m]


def _water(img, m):
    """Water if the pixel model or the neighbourhood model says so (each is sum(w * band) + b > 0)."""
    out = None
    for t in _twins(m):
        score = None
        for band, w in zip(t["bands"], t["weights"]):
            term = img.select(band).multiply(w)
            score = term if score is None else score.add(term)
        v = score.add(t["intercept"]).gt(0)
        out = v if out is None else out.Or(v)
    return out


def _water_band(ee, region, slot, spec):
    """One fortnight: 1 water, 0 not, 255 nothing to go on."""
    s, e, centre = slot
    img, has_opt, has_sar = _features(ee, region, s, e, centre)
    img = _with_means(ee, img, {b for m in ("fusion", "s1", "s2") for t in _twins(spec[m]) for b in t["bands"]})
    opt, sar = has_opt.unmask(0), has_sar.unmask(0)
    filled = img.unmask(0)
    return (_water(filled, spec["fusion"])
            .where(sar.And(opt.Not()), _water(filled, spec["s1"]))
            .where(opt.And(sar.Not()), _water(filled, spec["s2"]))
            .where(sar.Not().And(opt.Not()), NODATA)).toUint8()


def _correct(bands, window=WINDOW):
    """Gap fill (last seen state, the first one before any sighting), then a `window` majority."""
    seen = [b.neq(NODATA) for b in bands]
    fwd, prev = [], None
    for b, ok in zip(bands, seen):
        prev = b if prev is None else b.where(ok.Not(), prev)
        fwd.append(prev)
    filled, nxt = [None] * len(fwd), None
    for t in range(len(fwd) - 1, -1, -1):
        nxt = fwd[t] if nxt is None else fwd[t].where(fwd[t].eq(NODATA), nxt)
        filled[t] = nxt
    never = filled[0].eq(NODATA)
    wet = [f.eq(1) for f in filled]
    h, out = window // 2, []
    for t in range(len(wet)):
        votes = None
        for k in range(t - h, t + h + 1):
            w = wet[min(max(k, 0), len(wet) - 1)]
            votes = w if votes is None else votes.add(w)
        out.append(votes.gt(h).toUint8().where(never, NODATA))
    return out


def year_stack(ee, region, year, spec):
    """The corrected 26 fortnights of the water year (1 / 0 / 255), as a list of images."""
    raw = [_water_band(ee, region, sl, spec) for sl in _padded(year)]
    return _correct(raw)[PAD:-PAD]


def fortnight_index(ee, region, year, spec, label="last"):
    """Class index 0..25 per pixel: the last (or first) fortnight it held water. Masked if never wet."""
    wet = [b.eq(1) for b in year_stack(ee, region, year, spec)]
    order = range(len(wet)) if label == "last" else range(len(wet) - 1, -1, -1)
    idx = ee.Image(-1)
    for i in order:                            # later wins, so the loop order picks last or first
        idx = idx.where(wet[i], i)
    return idx.updateMask(idx.gte(0)).toInt()
