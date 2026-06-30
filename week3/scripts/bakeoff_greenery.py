"""Bake-off (4.5): hierarchical per-node splits vs one flat multiclass, greenery case.

Thin runner around refine.bakeoff. Prints both held-out reports so we can write the
verdict into notes/classifier_topology.md. Run from repo root:
  python scripts/bakeoff_greenery.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (week3/scripts -> root)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import refine

if __name__ == "__main__":
    refine.bakeoff("greenery")
