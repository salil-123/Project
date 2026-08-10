"""The class hierarchy: a tree of LULC classes the user can grow.

This is the spine of the week-3 work. The base map has 4 flat classes
(greenery / water / built_up / barren); from here a user can ADD a new class
anywhere in the tree or SPLIT an existing one into children. Every later phase
(example ingestion, refinement training, the UI editor) reads and writes this
one structure.

Shape: a flat dict keyed by canonical class id, so "where to add" is just
inserting/patching a key. One node looks like:

    "greenery": {
        "class": "greenery",   # canonical id, == its map key
        "name":  "Greenery",   # human label
        "parent": "root",      # null only for the root
        "color": "#2e8b2e",    # display color (the tree owns it)
        "classifier": null,    # op_id of the model resolving its children (Phase 4)
        "children": [],        # canonical ids of child nodes
    }

Pure functions take a tree and return the modified tree; only load/save touch disk.
Mirrors the conventions in contributions.py (relative data/ path, run from repo root).
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root holds config.py
import config

HIERARCHY_PATH = config.project_path("data/hierarchy.json")  # anchored to root, CWD-independent

ROOT = "root"

# base classes + colors. Kept literal on purpose: these mirror infer.CLASS_COLORS,
# but importing infer would load the joblib models at module top, which we don't want.
_BASE = [
    ("greenery", "Greenery", "#2e8b2e"),
    ("water",    "Water",    "#1e88e5"),
    ("built_up", "Built-up", "#d7301f"),
    ("barren",   "Barren",   "#c2a05a"),
]

# fallback palette for user-added classes that don't bring their own color
_PALETTE = ["#8e44ad", "#16a085", "#e67e22", "#2c3e50", "#c0392b",
            "#27ae60", "#2980b9", "#f39c12", "#7f8c8d", "#d35400"]


def _node(cls, name, parent, color, classifier=None, children=None, source=None):
    # source tells the trainer where this class's samples come from (examples /
    # worldcover / residual); None = expert examples. See refine.py.
    return {"class": cls, "name": name, "parent": parent, "color": color,
            "classifier": classifier, "children": children or [], "source": source}


def _seed() -> dict:
    """The starting tree: a root with the 4 base classes as leaves."""
    tree = {ROOT: _node(ROOT, "All land", None, None, children=[c for c, _, _ in _BASE])}
    for cls, name, color in _BASE:
        tree[cls] = _node(cls, name, ROOT, color)
    return tree


def seed_from_classes(classes: list, names: dict = None, colors: dict = None) -> dict:
    """A fresh tree whose leaves are exactly `classes` (used to start an alternate base scheme,
    e.g. the WorldCover base #5). Leaves match the base model's classes so colours/inference line
    up. names/colors are optional per-class overrides; anything missing gets a title-cased name
    and a palette colour."""
    names, colors = names or {}, colors or {}
    tree = {ROOT: _node(ROOT, "All land", None, None, children=list(classes))}
    for i, cls in enumerate(classes):
        tree[cls] = _node(cls, names.get(cls, cls.replace("_", " ").title()), ROOT,
                          colors.get(cls) or _PALETTE[i % len(_PALETTE)])
    return tree


def canonicalize(name: str) -> str:
    """Turn a display name into a canonical id: lowercase, non-words -> underscore."""
    slug = re.sub(r"\W+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"cannot make a canonical id from {name!r}")
    return slug


def _pick_color(tree: dict) -> str:
    """First palette color not already used in the tree (cycles if we run out)."""
    used = {n["color"] for n in tree.values() if n["color"]}
    for c in _PALETTE:
        if c not in used:
            return c
    return _PALETTE[len(tree) % len(_PALETTE)]


# ----------------------------- persistence -----------------------------
def load() -> dict:
    """Read the tree from disk; fall back to a fresh seed if there's no file yet."""
    if not os.path.exists(HIERARCHY_PATH):
        return _seed()
    with open(HIERARCHY_PATH) as fh:
        return json.load(fh)


def save(tree: dict) -> None:
    """Validate then write. Refuses to persist a broken tree."""
    validate(tree)
    os.makedirs(os.path.dirname(HIERARCHY_PATH), exist_ok=True)
    with open(HIERARCHY_PATH, "w") as fh:
        json.dump(tree, fh, indent=2)


# ----------------------------- mutations -----------------------------
def add_class(tree: dict, name: str, parent: str, canonical: str = None,
              color: str = None) -> dict:
    """Insert one new leaf under `parent`. Auto-derives id and color if omitted.

    Mutates and returns the same tree (callers can chain). The new node starts as a
    leaf; whatever classifier resolves it into the parent comes later (Phase 4).
    """
    if parent not in tree:
        raise KeyError(f"parent {parent!r} is not in the tree")
    cls = canonical or canonicalize(name)
    if cls in tree:
        raise ValueError(f"class {cls!r} already exists")
    tree[cls] = _node(cls, name, parent, color or _pick_color(tree))
    tree[parent]["children"].append(cls)
    return tree


def split_class(tree: dict, parent: str, children: list) -> dict:
    """Split `parent` into several children in one go.

    `children` items are either a plain name string or a dict
    {name, canonical?, color?}. Semantically a split; the parent's `classifier`
    (the model that decides which child a parent-pixel becomes) is filled in Phase 4.
    """
    for child in children:
        if isinstance(child, str):
            add_class(tree, child, parent)
        else:
            add_class(tree, child["name"], parent,
                      canonical=child.get("canonical"), color=child.get("color"))
    return tree


# ----------------------------- queries -----------------------------
def leaves(tree: dict) -> list:
    """Canonical ids of every node with no children (the live, predictable classes)."""
    return [c for c, n in tree.items() if not n["children"]]


def path_to(tree: dict, cls: str) -> list:
    """Chain of ids from the root down to `cls`. Used later when applying refinements."""
    if cls not in tree:
        raise KeyError(f"{cls!r} is not in the tree")
    chain = [cls]
    while tree[chain[-1]]["parent"] is not None:
        chain.append(tree[chain[-1]]["parent"])
    return chain[::-1]


# ----------------------------- validation -----------------------------
def validate(tree: dict) -> None:
    """Raise if the tree is malformed. Canonical uniqueness is free (keys are the ids)."""
    roots = [c for c, n in tree.items() if n["parent"] is None]
    if len(roots) != 1:
        raise ValueError(f"expected exactly one root, found {roots}")

    for cls, n in tree.items():
        if n["class"] != cls:
            raise ValueError(f"node {cls!r} disagrees with its 'class' field {n['class']!r}")
        parent = n["parent"]
        if parent is not None and parent not in tree:
            raise ValueError(f"{cls!r} points at missing parent {parent!r}")
        for child in n["children"]:
            if child not in tree:
                raise ValueError(f"{cls!r} lists missing child {child!r}")
            if tree[child]["parent"] != cls:
                raise ValueError(f"{child!r}'s parent should be {cls!r}")

    # every node must reach the root by walking parents (catches cycles)
    for cls in tree:
        seen, cur = set(), cls
        while tree[cur]["parent"] is not None:
            if cur in seen:
                raise ValueError(f"cycle detected at {cls!r}")
            seen.add(cur)
            cur = tree[cur]["parent"]


if __name__ == "__main__":
    # smoke test: seed, split greenery, validate, and show the result. No deps.
    t = _seed()
    split_class(t, "greenery", ["Crops", "Trees", "Shrubs"])
    validate(t)
    print("tree:")
    print(json.dumps(t, indent=2))
    print("\nleaves:", leaves(t))
    print("path to crops:", path_to(t, "crops"))

    # negative check: a dangling parent must blow up
    broken = _seed()
    broken["greenery"]["parent"] = "ghost"
    try:
        validate(broken)
        print("BUG: broken tree passed validation")
    except ValueError as e:
        print("validate() correctly rejected a broken tree:", e)