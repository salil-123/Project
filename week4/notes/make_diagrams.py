"""Render the week-4 schema diagrams as clean PNGs (no LaTeX line-art).

Four figures into week4/figures/:
  1. hierarchy_tree.png   - the class tree, colour-coded, clf badges
  2. card_anatomy.png     - Model Card + Dataset Card as real cards, field groups
  3. catalogue.png        - the zoo: datasets <-> models <-> crosswalk + "pick for area"
  4. lineage.png          - the lineage DAG (base -> splits -> future acacia)
  5. loop.png             - the end-to-end refine/publish loop

Pure matplotlib so it runs anywhere the project venv runs.
  python week4/notes/make_diagrams.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "figures")   # week4/figures
os.makedirs(OUT, exist_ok=True)

# the real hierarchy palette (from data/hierarchy.json)
C = {
    "root": "#5b6770", "greenery": "#2e8b2e", "water": "#2b6cff", "built_up": "#d7301f",
    "barren": "#c2a05a", "crops": "#e2b007", "trees": "#16a085", "shrubs": "#e67e22",
    "barren_other": "#c2a05a", "mining": "#8e44ad",
}
INK = "#1b1f24"        # near-black text / lines
MUTE = "#8a939b"       # muted grey
PANEL = "#eef1f4"      # light panel fill
ACCENT = "#1f6feb"     # blue accent
MODEL_C = "#1f6feb"    # model card  (blue)
DATA_C = "#0e7490"     # data card   (teal)


def _contrast(color):
    """black or white text, whichever reads on the fill (accepts hex or named)."""
    r, g, b = (c * 255 for c in matplotlib.colors.to_rgb(color))
    return INK if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "white"


def box(ax, x, y, w, h, text, fill="white", edge=INK, tc=None, fs=11, bold=False,
        rounding=0.06, lw=1.4, dashed=False, align="center"):
    """A rounded box with centred (or left) text. x,y is the lower-left corner."""
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.02,rounding_size={rounding}",
                       linewidth=lw, edgecolor=edge, facecolor=fill,
                       linestyle="--" if dashed else "-", mutation_aspect=1)
    ax.add_patch(p)
    tc = tc or _contrast(fill)
    if align == "center":
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=tc,
                fontsize=fs, fontweight="bold" if bold else "normal", zorder=5)
    else:
        ax.text(x + 0.12, y + h / 2, text, ha="left", va="center", color=tc,
                fontsize=fs, fontweight="bold" if bold else "normal", zorder=5)
    return (x + w / 2, y + h / 2)


def arrow(ax, p1, p2, color=INK, lw=1.6, style="-|>", dashed=False, rad=0.0):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=14,
                                 linewidth=lw, color=color,
                                 linestyle="--" if dashed else "-",
                                 connectionstyle=f"arc3,rad={rad}", zorder=1))


def _canvas(w=12, h=7):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100 * h / w)
    ax.axis("off")
    return fig, ax


def _save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    plt.close(fig)
    print("wrote", path)


# ---------------------------------------------------------------- 1. hierarchy
def _card_row(ax, cx, node_top, model_text, data_text, filled, W, gap=1.0, h=4.4, voff=0.6):
    """A model-card + data-card chip side by side (50/50) just above a node. Filled =
    the base map's chosen cards; dashed = empty slots the user fills. Returns the row's
    top y (where an incoming arrow should land)."""
    y = node_top + voff
    cw = (W - gap) / 2
    for cxx, text, color in ((cx - W / 2 + cw / 2, model_text, MODEL_C),
                             (cx + W / 2 - cw / 2, data_text, DATA_C)):
        if filled:
            box(ax, cxx - cw / 2, y, cw, h, text, color, tc="white", fs=7.8, bold=True,
                rounding=0.3, lw=1.1)
        else:
            box(ax, cxx - cw / 2, y, cw, h, text, "white", edge=color, tc=color, fs=7.6,
                bold=True, rounding=0.3, lw=1.3, dashed=True)
    return y + h


def hierarchy_tree():
    fig, ax = _canvas(12, 7)
    H = ax.get_ylim()[1]                     # ~58.3, isotropic units
    bw, bh = 17, 8
    y_root, y_base, y_leaf = H - 14, H - 34, H - 48
    centers = {"greenery": 20.5, "water": 42.5, "built_up": 64.5, "barren": 86.5}
    xs = {"greenery": 12, "water": 34, "built_up": 56, "barren": 78}
    labels = {"greenery": "Greenery", "water": "Water", "built_up": "Built-up", "barren": "Barren"}

    box(ax, 50 - bw / 2, y_root, bw, bh, "All land", C["root"], bold=True, fs=12)
    # the base map's cards are pre-selected (filled), side by side above the root
    _card_row(ax, 50, y_root + bh, "LinearSVC", "AlphaEarth & WorldCover", filled=True, W=56)

    for k in ("greenery", "water", "built_up", "barren"):
        box(ax, xs[k], y_base, bw, bh, labels[k], C[k], bold=True, fs=11)
    # greenery + barren show empty model-card / data-card slots the user fills
    row_top = {k: _card_row(ax, centers[k], y_base + bh, "model card", "data card",
                            filled=False, W=26) for k in ("greenery", "barren")}

    for k in ("greenery", "water", "built_up", "barren"):
        arrow(ax, (50, y_root), (centers[k], row_top.get(k, y_base + bh)))

    leaves = {"greenery": [("crops", "Crops"), ("trees", "Trees"), ("shrubs", "Shrubs")],
              "barren": [("barren_other", "Barren*"), ("mining", "Mining")]}
    for parent, kids in leaves.items():
        px = centers[parent]
        step, w = 12, 11
        lx = [px + (i - (len(kids) - 1) / 2) * step for i in range(len(kids))]
        for x, (k, lbl) in zip(lx, kids):
            box(ax, x - w / 2, y_leaf, w, bh - 1, lbl, C[k], fs=9.5, bold=True)
            arrow(ax, (px, y_base), (x, y_leaf + bh - 1), color=MUTE, lw=1.2)
    ax.text(50, 2.5, "each model-bearing node has a model card + the data card it trained on; "
            "the base map's are filled, greenery / barren are slots      *residual",
            ha="center", va="bottom", color=MUTE, fontsize=8.3, style="italic")
    _save(fig, "hierarchy_tree.png")


# ---------------------------------------------------------------- 2. card anatomy
def _card(ax, x, y, w, h, title, tcolor, rows):
    box(ax, x, y, w, h, "", "white", edge=INK, lw=1.6, rounding=0.04)          # body
    box(ax, x, y + h - 9, w, 9, title, tcolor, tc="white", fs=12.5, bold=True,  # title bar
        rounding=0.04)
    ry = y + h - 9
    for label, val in rows:
        ry -= (h - 11) / len(rows)
        ax.text(x + 2.5, ry + (h - 11) / len(rows) / 2, label, ha="left", va="center",
                color=ACCENT, fontsize=9.5, fontweight="bold")
        ax.text(x + w - 2.5, ry + (h - 11) / len(rows) / 2, val, ha="right", va="center",
                color=INK, fontsize=9)
        ax.plot([x + 2, x + w - 2], [ry, ry], color=PANEL, lw=1)


def card_anatomy():
    fig, ax = _canvas(12, 6.4)
    H = ax.get_ylim()[1]
    _card(ax, 4, 6, 42, H - 12, "Model Card", C["greenery"], [
        ("node / parent", "where it sits in the tree"),
        ("produces", "the classes (legend) it emits"),
        ("training.datasets", "which datasets it learned from"),
        ("extent", "where + when it's valid"),
        ("metrics", "held-out accuracy, per-class F1"),
        ("deployment", "joblib / EE asset / tile URL"),
        ("lineage", "base model it descends from"),
        ("about + zoo", "description, evidence, published?"),
    ])
    _card(ax, 54, 6, 42, H - 12, "Dataset Card", C["barren"], [
        ("kind + definition", "polygons | EE asset | table"),
        ("classes", "what it labels (+ counts)"),
        ("extent", "spatial region/poly + year"),
        ("embedding", "Alpha Earth, 64-d, year"),
        ("provenance", "annotator, method, evidence"),
        ("quality", "n, spatial-diversity index"),
        ("description", "what this is, in words"),
        ("version", "stable id, bumped on edit"),
    ])
    arrow(ax, (46, H / 2), (54, H / 2), color=ACCENT, lw=2)   # model trains on dataset
    ax.text(50, H / 2 + 2.5, "trains\non", ha="center", va="center", color=ACCENT,
            fontsize=8.5, fontweight="bold")
    _save(fig, "card_anatomy.png")


# ---------------------------------------------------------------- 3. catalogue
def catalogue():
    fig, ax = _canvas(12, 5.6)
    H = ax.get_ylim()[1]                      # ~46.7
    # registry panel (left)
    box(ax, 4, 6, 52, H - 10, "", PANEL, edge=MUTE, lw=1.4, rounding=0.03)
    ax.text(30, H - 8, "data/catalogue/", ha="center", color=INK, fontsize=12.5, fontweight="bold")
    ds = box(ax, 10, H - 22, 18, 8, "datasets/", C["barren"], tc="white", fs=10.5, bold=True)
    md = box(ax, 34, H - 22, 18, 8, "models/", C["greenery"], tc="white", fs=10.5, bold=True)
    box(ax, 10, 11, 18, 7.5, "std_crosswalk", "white", edge=ACCENT, tc=ACCENT, fs=9, bold=True)
    box(ax, 34, 11, 18, 7.5, "index.json", "white", edge=MUTE, tc=INK, fs=9, bold=True)
    # a model references its datasets (short straight arrow in the gap between them)
    arrow(ax, (md[0] - 9, md[1]), (ds[0] + 9, ds[1]), color=INK, lw=1.6)
    ax.text(31, md[1] + 6, "references", ha="center", color=MUTE, fontsize=8.5, style="italic")
    ax.text(30, 2.0, "one JSON file per card", ha="center", color=MUTE, fontsize=8.5, style="italic")

    # query panel (right)
    box(ax, 62, 6, 33, H - 10, "", "white", edge=INK, lw=1.4, rounding=0.03)
    ax.text(78.5, H - 8, "Pick a model for my area", ha="center", color=INK, fontsize=11.5,
            fontweight="bold")
    for i, t in enumerate(["1.  extent contains my AOI",
                           "2.  produces / parent_class fits",
                           "3.  rank by metrics x spatial fit"]):
        ax.text(65, H - 18 - i * 7, t, ha="left", va="center", color=INK, fontsize=9.5)
    arrow(ax, (56, H / 2 + 1), (62, H / 2 + 1), color=ACCENT, lw=2)
    ax.text(59, H / 2 + 4, "query", ha="center", color=ACCENT, fontsize=8.5, fontweight="bold")
    _save(fig, "catalogue.png")


# ---------------------------------------------------------------- 4. lineage DAG
def lineage():
    fig, ax = _canvas(12, 4.6)
    H = ax.get_ylim()[1]
    bw, bh = 26, 9
    base = box(ax, 6, H / 2 - bh / 2, bw, bh, "base map\n(4 classes)", C["root"],
               tc="white", fs=10.5, bold=True)
    g = box(ax, 40, H - 16, bw, bh, "greenery split\ncrops/trees/shrubs", C["greenery"],
            tc="white", fs=9.5, bold=True)
    b = box(ax, 40, 6, bw, bh, "barren + mining\n(ADD)", C["barren"], tc="white",
            fs=9.5, bold=True)
    ac = box(ax, 74, H - 16, bw, bh, "trees -> acacia\n(future)", C["trees"], tc="white",
             fs=9.5, bold=True, dashed=True)
    arrow(ax, (6 + bw, H / 2 + 1), (40, H - 16 + bh / 2))
    arrow(ax, (6 + bw, H / 2 - 1), (40, 6 + bh / 2))
    arrow(ax, (40 + bw, H - 16 + bh / 2), (74, H - 16 + bh / 2), dashed=True, color=MUTE)
    ax.text(50, 1.5, "each refinement is a new Model Card with lineage.derived_from set",
            ha="center", color=MUTE, fontsize=8.5, style="italic")
    _save(fig, "lineage.png")


# ---------------------------------------------------------------- 5. end-to-end loop
def loop():
    fig, ax = _canvas(12, 5.4)
    H = ax.get_ylim()[1]
    steps = [
        ("Area of\ninterest", ACCENT),
        ("Filter the\ncatalogue", C["root"]),
        ("Pick a\nbase model", C["greenery"]),
        ("Dataset panel\n(area + year)", C["barren"]),
        ("Retrain", C["mining"]),
        ("New Model\nCard", C["trees"]),
        ("Publish\nto the zoo", "#444c56"),
    ]
    n = len(steps)
    bw, bh, gap = 11.5, 11, (100 - 6 - n * 11.5) / (n - 1)
    y = H - 26
    centers = []
    for i, (t, c) in enumerate(steps):
        x = 3 + i * (bw + gap)
        centers.append(box(ax, x, y, bw, bh, t, c, tc="white", fs=8.8, bold=True))
        if i:
            arrow(ax, (centers[i - 1][0] + bw / 2, y + bh / 2),
                  (x, y + bh / 2), color=INK, lw=1.6)
    _save(fig, "loop.png")


if __name__ == "__main__":
    hierarchy_tree()
    card_anatomy()
    loop()
    print("\nall diagrams ->", OUT)
