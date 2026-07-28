"""Pre-flight validation for an uploaded scheme, before we execute any of it (#5).

Import used to apply first and report missing classifiers after — so a broken file had already
mutated the live tree by the time you learned it was broken, and the op-log rode along wholly
unchecked. This is the "validate the json before you execute it" gate sir asked for: given the
export envelope ({hierarchy, op_log, classifier_refs}), it says whether it would apply, what's
outright wrong (errors), and what would import but not be live yet (warnings) — touching nothing.
"""
from pathlib import Path

import hierarchy

_REFINE = Path(__file__).resolve().parent.parent / "data" / "refine"

# op verb -> the args it must carry, mirroring what backend logs to the op-log. An uploaded log
# with an unknown verb or a dropped arg is a tell that the file was hand-edited or came from an
# incompatible version, so we'd rather flag it than replay it blindly.
KNOWN_OPS = {
    "split":            ["parent", "children"],
    "rule_split":       ["parent", "rule"],
    "add":              ["parent", "name"],
    "retrain":          ["node"],
    "base_select":      ["scheme"],
    "reset":            ["scheme"],
    "merge":            ["target"],
    "merge_remove":     ["target"],
    "apply":            ["card_id"],
    "apply_eerf":       ["card_id"],
    "import_hierarchy": [],
}


def missing_classifiers(tree):
    """Nodes whose split artifact isn't on disk — they import structurally but won't classify
    until retrained. One source of truth, shared by import and the pre-flight below."""
    return [cls for cls, node in tree.items()
            if node.get("classifier") and node["classifier"] != hierarchy.ROOT
            and not (_REFINE / f"{node['classifier']}.joblib").exists()]


def validate_envelope(body):
    """Check an import envelope without applying it. Returns {ok, errors, warnings}: errors block
    the import; warnings (missing artifacts) don't. `body` is the export shape — a dict with
    'hierarchy' and optional 'op_log'."""
    errors, warnings = [], []
    tree = body.get("hierarchy")

    # 1) the tree must be a well-formed hierarchy — reuse the live validator, no new tree logic
    if not isinstance(tree, dict):
        return {"ok": False, "errors": ["missing or malformed 'hierarchy' object"], "warnings": []}
    tree_ok = True
    try:
        hierarchy.validate(tree)
    except (ValueError, KeyError) as e:
        errors.append(f"hierarchy: {e}")
        tree_ok = False

    # 2) op-log entries must look like ops we actually know how to apply (the check import lacked)
    op_log = body.get("op_log") or []
    if not isinstance(op_log, list):
        errors.append("'op_log' must be a list")
        op_log = []
    for i, entry in enumerate(op_log):
        if not isinstance(entry, dict) or "op" not in entry:
            errors.append(f"op_log[{i}]: not an op record (needs an 'op' field)")
            continue
        op = entry["op"]
        if op not in KNOWN_OPS:
            errors.append(f"op_log[{i}]: unknown op {op!r}")
            continue
        args = entry.get("args") or {}
        for key in KNOWN_OPS[op]:
            if key not in args:
                errors.append(f"op_log[{i}] ({op}): missing arg {key!r}")

    # 3) classifiers referenced by the tree but absent on disk: imports fine, just not live yet
    if tree_ok:
        for cls in missing_classifiers(tree):
            warnings.append(f"classifier for {cls!r} is missing on disk — retrain it to go live")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
