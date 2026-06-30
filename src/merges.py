"""Cross-model merge rules: relabel chosen leaf classes into one new class (week-6 #9).

Sir's framing (and the Chahat-paper idea of "pixel-level error-correction layers"): a merge is
just a relabelling. You pick a class produced at one node and a class produced at another —
possibly from different models — and declare them both one new class E. No retraining; it's a
correction layer applied *after* the per-node classifiers have run.

Stored as a flat list in data/merge_rules.json:
  [{"target": "<id>", "name": "...", "color": "#...", "sources": ["leaf_a", "leaf_b", ...]}]
`sources` are leaf class ids, which are canonical and unique across the tree, so matching at
inference is a plain membership test. Mirrors hierarchy.py's data/ + run-from-root conventions.
"""
import json
import os
import re

MERGE_PATH = "data/merge_rules.json"

# fallback colours for merge targets that don't bring their own (kept off the base palette)
_PALETTE = ["#8e44ad", "#16a085", "#e67e22", "#c0392b", "#2980b9", "#d35400"]


def load() -> list:
    if not os.path.exists(MERGE_PATH):
        return []
    with open(MERGE_PATH) as fh:
        return json.load(fh)


def save(rules: list) -> None:
    os.makedirs(os.path.dirname(MERGE_PATH), exist_ok=True)
    with open(MERGE_PATH, "w") as fh:
        json.dump(rules, fh, indent=2)


def _canon(name: str) -> str:
    slug = re.sub(r"\W+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"cannot make a class id from {name!r}")
    return slug


def add(name: str, sources: list, color: str = None, target: str = None) -> dict:
    """Add (or replace, by target id) a merge rule. `sources` = leaf class ids, at least two
    and ideally from different models — that's the whole point. Returns the stored rule."""
    sources = [s for s in dict.fromkeys(sources) if s]      # dedup, keep order
    if len(sources) < 2:
        raise ValueError("a merge needs at least two source classes")
    tid = target or _canon(name)
    if tid in sources:
        raise ValueError("a merge target can't also be one of its sources")
    rules = [r for r in load() if r["target"] != tid]       # replace same-target rule
    rule = {"target": tid, "name": name.strip(), "color": color, "sources": sources}
    rules.append(rule)
    save(rules)
    return rule


def remove(target: str) -> list:
    rules = [r for r in load() if r["target"] != target]
    save(rules)
    return rules


def target_colors() -> dict:
    """target id -> display colour (its own, or a stable fallback). Folded into infer.load_colors."""
    out = {}
    for i, r in enumerate(load()):
        out[r["target"]] = r.get("color") or _PALETTE[i % len(_PALETTE)]
    return out


def source_to_target() -> dict:
    """Flat {source_leaf: target} map for fast relabelling at inference."""
    m = {}
    for r in load():
        for s in r["sources"]:
            m[s] = r["target"]
    return m


if __name__ == "__main__":
    import tempfile
    MERGE_PATH = os.path.join(tempfile.mkdtemp(), "merge_rules.json")
    assert load() == []
    add("Extractive land", ["tea", "mining"], color="#8e44ad")
    assert source_to_target() == {"tea": "extractive_land", "mining": "extractive_land"}
    assert target_colors() == {"extractive_land": "#8e44ad"}
    add("Extractive land", ["mining", "barren_other"])      # replace same target
    assert load()[0]["sources"] == ["mining", "barren_other"] and len(load()) == 1
    try:
        add("oops", ["only_one"]); print("BUG: accepted <2 sources")
    except ValueError: pass
    remove("extractive_land")
    assert load() == []
    print("merges.py smoke test OK")
