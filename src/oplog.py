"""The operation log: an append-only, ordered record of every tree-mutating action.

Why this exists (week-6 #11): a user grows their class scheme through a *sequence* of
operations — split greenery, add mining, merge tea+mining into something, retrain, apply a
zoo model. The hierarchy.json captures the final *shape* but not the *order* it was built
in, and order matters: it's what reproduces their unique output and lets them pick up where
they left off. So every mutating endpoint drops a line here.

One entry is pure data (op name + args + a small result), so the log can be shipped inside a
saved hierarchy (#4) and, later, replayed to rebuild state. Mirrors the data/ + run-from-root
conventions of hierarchy.py / examples.py.
"""
import json
import os
from datetime import datetime, timezone

OPLOG_PATH = "data/op_log.json"


def load() -> list:
    """The ordered list of operations (empty if none yet)."""
    if not os.path.exists(OPLOG_PATH):
        return []
    with open(OPLOG_PATH) as fh:
        return json.load(fh)


def _save(entries: list) -> None:
    os.makedirs(os.path.dirname(OPLOG_PATH), exist_ok=True)
    with open(OPLOG_PATH, "w") as fh:
        json.dump(entries, fh, indent=2)


def append(op: str, args: dict, result=None) -> dict:
    """Record one operation at the end of the log. Returns the stored entry.

    `op` is a short verb (split/add/retrain/apply/merge/base_select); `args` is whatever's
    needed to replay it; `result` is an optional small summary (e.g. minted card ids). Never
    raises on a bad write — logging must not break the actual operation."""
    try:
        entries = load()
        entry = {"seq": len(entries) + 1, "ts": datetime.now(timezone.utc).isoformat(),
                 "op": op, "args": args, "result": result}
        entries.append(entry)
        _save(entries)
        return entry
    except Exception:
        return {}     # best-effort: a logging hiccup shouldn't sink the request


def replace(entries: list) -> None:
    """Overwrite the whole log — used when restoring a saved hierarchy (#4)."""
    _save(list(entries or []))


def clear() -> None:
    """Drop the log (e.g. when resetting to a fresh base map)."""
    _save([])


if __name__ == "__main__":
    # offline smoke test in a temp file, so data/ is left untouched
    import tempfile
    OPLOG_PATH = os.path.join(tempfile.mkdtemp(), "op_log.json")
    assert load() == []
    append("split", {"parent": "greenery", "children": ["tea", "non_tea"]})
    append("retrain", {"node": "greenery"}, result={"model": "mc_greenery_v1"})
    log = load()
    assert [e["seq"] for e in log] == [1, 2] and log[0]["op"] == "split"
    replace([{"seq": 1, "op": "add", "args": {"name": "mining"}, "result": None}])
    assert len(load()) == 1 and load()[0]["op"] == "add"
    clear()
    assert load() == []
    print("oplog.py smoke test OK")
