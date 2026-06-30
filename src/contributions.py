"""STUBS for the evolving, user-contributed dataset (Phase 5 future work).

This module defines the *interfaces* for the contribution + on-the-fly retraining
+ shared-repository features described in the task (#9.iii-iv, #11-15). They are
intentionally minimal so the UI can be wired now and the logic filled in later.

Design intent:
  - Every user marking (point/polygon + class, positive/negative, or a NEW class)
    is appended to a local contributions store (CSV/GeoJSON now; a shared repo later).
  - retrain_with_contributions() will sample embeddings at the new geometries, add
    them to the training pool, and refit a lightweight model layered on the base.
  - Contributions are the mechanism by which the dataset evolves toward being
    polygon/user-driven (lowering reliance on WorldCover scaffolding over time).
"""
import json
import os
from datetime import datetime, timezone

CONTRIB_PATH = "data/contributions.geojson"


def _empty_fc():
    return {"type": "FeatureCollection", "features": []}


def load_contributions() -> dict:
    """Return all user contributions as a GeoJSON FeatureCollection."""
    if not os.path.exists(CONTRIB_PATH):
        return _empty_fc()
    with open(CONTRIB_PATH) as fh:
        return json.load(fh)


def add_contribution(geometry: dict, label: str, kind: str = "polygon",
                     note: str = "", is_new_class: bool = False) -> int:
    """Append one user marking. geometry is GeoJSON geometry.

    label: class name (existing OR a brand-new class like 'tea_plantation').
    kind:  'point' | 'polygon'.  is_new_class: user is introducing a new class.
    Returns the new total contribution count.

    NOTE: this just persists the marking. Embedding sampling + retraining is
    handled separately by retrain_with_contributions().
    """
    fc = load_contributions()
    fc["features"].append({
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "label": label, "kind": kind, "note": note,
            "is_new_class": bool(is_new_class),
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    })
    os.makedirs(os.path.dirname(CONTRIB_PATH), exist_ok=True)
    with open(CONTRIB_PATH, "w") as fh:
        json.dump(fc, fh)
    return len(fc["features"])


def known_classes() -> list:
    """Base classes + any new classes the user has introduced via contributions."""
    base = ["greenery", "water", "built_up", "barren", "other"]
    extra = sorted({f["properties"]["label"] for f in load_contributions()["features"]
                    if f["properties"]["label"] not in base})
    return base + extra


# ----------------------------- STUBS (Phase 5+) -----------------------------
def retrain_with_contributions(base_model_path: str = "data/model_pooled.joblib"):
    """STUB: sample embeddings at contributed geometries, add to the training pool,
    and refit a quick model layered on the base. To be implemented in Phase 5."""
    raise NotImplementedError("on-the-fly retraining — Phase 5 TODO")


def find_similar(geometry: dict, k: int = 50):
    """STUB: given a user's positive example, return embedding-nearest pixels
    ('if this is a plantation, these likely are too'). Phase 5 TODO (#9.iv)."""
    raise NotImplementedError("embedding-similarity suggestion — Phase 5 TODO")


def publish_to_shared_repo():
    """STUB: push local contributions to the shared, wikipedia-style evolving
    dataset (#11-15). Phase 5+ TODO."""
    raise NotImplementedError("shared contribution repository — Phase 5+ TODO")