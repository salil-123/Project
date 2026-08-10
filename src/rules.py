"""Rule-based splits (#12): resolve a node's children by an *expression over indices*, not a
trained model.

Sir's ask: instead of always training a classifier to split a class, let the user write a rule
like ``ndvi_annual > 0.3`` -> dense_veg, else sparse_veg. We give them a small **registry** of
interpretable indices (NDVI seasonal/annual, NDWI, slope, ...), each of which computes live in
Earth Engine over the AOI. Because the indices are EE images, a rule split renders through the
exact same crisp server-side tile path as a linear split — no download, no point grid.

A rule is stored on the hierarchy node (so it travels with the saved scheme) as::

    {"clauses": [{"when": "<expr>", "class": "<child_id>"}, ...], "default": "<child_id>"}

Evaluation is first-clause-wins: a pixel takes the class of the first clause whose expression is
true, else the default. Expressions are checked against a whitelist (registry var ids + a fixed
set of operators) before they ever reach EE — no arbitrary code, no surprise bands.

This module is framework-agnostic: callers pass in the initialised ``ee`` module and an EE
region/year, so it needs no GEE credentials of its own and stays unit-testable offline (the
registry + parser below run without EE).
"""
import ast
import re

# ----------------------------- the variable registry -----------------------------
# Each var: label + one-line description + an EE builder (ee, region, year) -> single-band image.
# Kharif = monsoon crop season (Jun-Oct); Rabi = winter crop season (Nov-Mar). These windows and
# the index maths mirror the CoRE-stack flood pipeline (water_dataset_builder/ee_logic.py) and the
# "Beyond Flat Classifiers" paper (NDVI peaks for cropping, SAR/NDWI for water, slope for terrain).

def _s2(ee, region, year, start_md, end_md, add_year=0):
    """A cloud-lite Sentinel-2 median composite over a date window, clipped to the region.
    start_md/end_md are 'MM-DD'; add_year shifts the end into the next year (for Rabi)."""
    start = f"{year}-{start_md}"
    end = f"{year + add_year}-{end_md}"
    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region).filterDate(start, end)
            .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 40))
            .median())


def _nd(img, a, b):
    """Normalised difference (a-b)/(a+b) of two S2 bands, as a plain named-band image."""
    return img.normalizedDifference([a, b])


def _ndvi(ee, region, year, s, e, ay=0):
    return _nd(_s2(ee, region, year, s, e, ay), "B8", "B4").rename("v")


REGISTRY = {
    # vegetation — the "dense vs sparse", crop-vs-tree signal
    "ndvi_annual": {"label": "NDVI (annual median)", "range": [-1, 1],
                    "describe": "Yearly greenness; high = dense vegetation.",
                    "build": lambda ee, r, y: _ndvi(ee, r, y, "01-01", "12-31")},
    "ndvi_kharif": {"label": "NDVI (Kharif / monsoon)", "range": [-1, 1],
                    "describe": "Monsoon-season greenness (Jun-Oct) — the Kharif crop peak.",
                    "build": lambda ee, r, y: _ndvi(ee, r, y, "06-01", "10-31")},
    "ndvi_rabi": {"label": "NDVI (Rabi / winter)", "range": [-1, 1],
                  "describe": "Winter-season greenness (Nov-Mar) — the Rabi crop peak.",
                  "build": lambda ee, r, y: _ndvi(ee, r, y, "11-01", "03-31", ay=1)},
    # water
    "ndwi": {"label": "NDWI (water)", "range": [-1, 1],
             "describe": "Green-NIR water index; high = open water.",
             "build": lambda ee, r, y: _nd(_s2(ee, r, y, "01-01", "12-31"), "B3", "B8").rename("v")},
    "mndwi": {"label": "MNDWI (modified water)", "range": [-1, 1],
              "describe": "Green-SWIR water index; better over built-up.",
              "build": lambda ee, r, y: _nd(_s2(ee, r, y, "01-01", "12-31"), "B3", "B11").rename("v")},
    # built / soil
    "ndbi": {"label": "NDBI (built-up)", "range": [-1, 1],
             "describe": "SWIR-NIR built-up index; high = impervious.",
             "build": lambda ee, r, y: _nd(_s2(ee, r, y, "01-01", "12-31"), "B11", "B8").rename("v")},
    "bsi": {"label": "BSI (bare soil)", "range": [-1, 1],
            "describe": "Bare-soil index; high = exposed ground.",
            "build": lambda ee, r, y: _bsi(ee, r, y)},
    # terrain (SRTM) — enables the crop->shrub reassignment (#13)
    "slope": {"label": "Slope (degrees)", "range": [0, 90],
              "describe": "Terrain steepness from SRTM; steep crop pixels are likely shrub.",
              "build": lambda ee, r, y: ee.Terrain.slope(
                  ee.Image("USGS/SRTMGL1_003")).rename("v")},
    "elevation": {"label": "Elevation (m)", "range": [-100, 9000],
                  "describe": "SRTM elevation above sea level.",
                  "build": lambda ee, r, y: ee.Image("USGS/SRTMGL1_003").rename("v")},
}


def _bsi(ee, region, year):
    img = _s2(ee, region, year, "01-01", "12-31")
    b11, b4, b8, b2 = img.select("B11"), img.select("B4"), img.select("B8"), img.select("B2")
    num = b11.add(b4).subtract(b8.add(b2))
    den = b11.add(b4).add(b8.add(b2)).add(1e-6)
    return num.divide(den).rename("v")


def registry_summary():
    """The pick-list the UI shows: id + label + description + typical range (no EE)."""
    return {vid: {"label": v["label"], "describe": v["describe"], "range": v["range"]}
            for vid, v in REGISTRY.items()}


# ----------------------------- rule shape + validation -----------------------------
# We validate an expression by translating the EE operators (&&, ||, !) to Python and parsing it
# with `ast`, then walking the tree against a fixed node whitelist. This catches both illegal
# content (function calls, attribute access, unknown names) AND malformed syntax (a dangling
# operator), which a pure token scan misses. The string is only handed to ee.Image.expression
# once it's proven to be a clean boolean over known registry vars.
_ALLOWED_NODES = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
                  ast.UAdd, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Compare, ast.Lt,
                  ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq, ast.Name, ast.Load, ast.Constant)
_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _to_python(expr):
    """EE boolean operators -> Python, so we can parse with ast. `!=` is left intact (only a bare
    `!` becomes `not`)."""
    expr = expr.replace("&&", " and ").replace("||", " or ")
    # a leading `!` -> " not " would put a space at column 0, which ast.parse reads as an indent and
    # (wrongly) calls malformed; strip so a leading negation like `!(ndvi_annual > 0.3)` parses.
    return re.sub(r"!(?!=)", " not ", expr).strip()


def vars_in(expr):
    """The registry var ids referenced by an expression (in first-seen order)."""
    py_kw = {"and", "or", "not"}
    out = []
    for name in _NAME_RE.findall(_to_python(expr or "")):
        if name in REGISTRY and name not in out:
            out.append(name)
    return out


def _is_boolean(node):
    """Does this AST node evaluate to a genuine true/false condition? A rule clause must — it feeds
    `.where(mask, ...)`, and a non-boolean (a bare index value, a constant, an arithmetic result)
    would be truthy almost everywhere and paint the whole map. So we require the expression to bottom
    out in comparisons: a single-operator Compare, a Not of one, or And/Or of booleans."""
    if isinstance(node, ast.Compare):
        return len(node.ops) == 1          # reject chained compares (a > b > c): EE reads them differently
    if isinstance(node, ast.BoolOp):
        return all(_is_boolean(v) for v in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _is_boolean(node.operand)
    return False


def check_expr(expr):
    """Raise ValueError if `expr` isn't a clean, well-formed boolean over known registry vars.
    Returns the var ids it uses."""
    if not (expr or "").strip():
        raise ValueError("empty rule expression")
    try:
        tree = ast.parse(_to_python(expr), mode="eval")
    except SyntaxError:
        raise ValueError(f"malformed rule expression: {expr!r}")
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"illegal construct in rule expression: {type(node).__name__}")
        if isinstance(node, ast.Name):
            names.append(node.id)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise ValueError(f"unknown rule variable(s): {', '.join(unknown)}. "
                         f"Pick from: {', '.join(REGISTRY)}")
    # the expression must be an actual condition, not a bare value/constant — a clause paints where it
    # holds, so `ndvi_annual` or `0.3` (truthy everywhere) or a chained compare are silent map-wreckers.
    if not _is_boolean(tree.body):
        raise ValueError(f"rule expression must be a comparison (e.g. 'ndvi_annual > 0.3'), not {expr!r}")
    return [n for n in dict.fromkeys(names)]


def rule_classes(rule):
    """The children a rule produces, in child order: each clause's class, then the default last
    (if it isn't already a clause class)."""
    out = []
    for c in rule.get("clauses", []):
        if c["class"] not in out:
            out.append(c["class"])
    d = rule.get("default")
    if d and d not in out:
        out.append(d)
    return out


def validate_rule(rule):
    """Check a whole rule before it's stored: shape, expressions, at least two resulting classes.
    Returns the sorted set of registry vars it uses (handy for the card)."""
    if not isinstance(rule, dict) or not rule.get("clauses") or not rule.get("default"):
        raise ValueError("a rule needs at least one clause and a default class")
    used = set()
    for c in rule["clauses"]:
        if "when" not in c or "class" not in c:
            raise ValueError("each clause needs a 'when' expression and a 'class'")
        used.update(check_expr(c["when"]))
    if len(rule_classes(rule)) < 2:
        raise ValueError("a rule split must produce at least two distinct classes")
    return sorted(used)


# ----------------------------- EE evaluation -----------------------------
def rule_label_ee(ee, region, year, rule):
    """Class-index image (0..K-1, in `rule_classes` order) for a rule, evaluated in Earth Engine.

    Builds only the index images the rule references, then composites first-clause-wins: start
    from the default code and paint each clause's class where its expression holds, applying the
    clauses in reverse so the *first* matching clause has the final say. Returns
    (index_image, classes) mirroring infer._ee_label's contract so the tile renderer can descend
    into it exactly like a linear split."""
    classes = rule_classes(rule)
    code = {c: i for i, c in enumerate(classes)}

    used = sorted({v for c in rule["clauses"] for v in vars_in(c["when"])})
    imgs = {vid: REGISTRY[vid]["build"](ee, region, year) for vid in used}

    label = ee.Image.constant(code[rule["default"]]).rename("v").toInt()
    for clause in reversed(rule["clauses"]):
        mask = _s2_expr(ee, clause["when"], imgs)       # 1 where the clause holds
        label = label.where(mask, code[clause["class"]])
    return label.rename("v"), classes


def _s2_expr(ee, expr, imgs):
    """Evaluate a boolean rule expression to a 0/1 EE image over the prepared var images.
    The expression only names registry vars (already validated), which map to single-band images."""
    return ee.Image().expression(expr, {vid: img for vid, img in imgs.items()})


if __name__ == "__main__":
    # offline checks — parser + rule shape, no EE needed.
    assert vars_in("ndvi_annual > 0.3 && slope < 5") == ["ndvi_annual", "slope"]
    assert check_expr("ndvi_annual > 0.3") == ["ndvi_annual"]
    assert check_expr("ndvi_annual > 0.3 && slope < 5") == ["ndvi_annual", "slope"]
    assert check_expr("!(ndvi_annual > 0.3)") == ["ndvi_annual"]
    # non-boolean / chained expressions must be refused (they'd paint the whole map)
    for bad in ["", "ndvi_annual >", "os.system('x')", "ndvi_annual $ 1", "foobar > 1",
                "ndvi_annual", "0.3", "ndvi_annual + 0.1", "ndvi_annual > 0.3 && ndbi",
                "ndvi_annual > 0.3 > 0.1"]:
        try:
            check_expr(bad); print("BUG: accepted", repr(bad))
        except ValueError:
            pass
    r = {"clauses": [{"when": "ndvi_annual > 0.3", "class": "dense_veg"}], "default": "sparse_veg"}
    assert rule_classes(r) == ["dense_veg", "sparse_veg"]
    assert validate_rule(r) == ["ndvi_annual"]
    print("rules.py smoke test OK")
