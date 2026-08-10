"""#9 wk11 — is the mining pixel->vectorize good enough to skip a GPU segmentation route?

We already turn the linear mining prediction into polygon *objects* (`infer.segment_class`: focal-mode
de-speckle -> reduceToVectors -> min-area filter). Sir's question: compare those output polygons with
the original ground-truth mining polygons and get object-detection metrics (precision / recall / IoU) —
if the cheap pixel+vectorize does well enough, we don't need a learned CV segmentation net (GPU, etc.).

This is a **pan-India experiment**, run outside the live framework (like week7/site_tests.py). For a
sample of GT mining polygons we buffer each into an eval box (sir's "the buffer becomes the testing
ground"), run `segment_class` there, and greedily match predicted vs GT polygons by IoU.

Run:  python week11/mining_eval.py --n-sites 20 --buffer-m 300 --iou 0.3
      python week11/mining_eval.py --n-sites 20 --write-card      # also write onto mc_barren_v1

Needs Earth Engine auth (config.ee_init) and geopandas (already a dep).
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import infer  # noqa: E402

GT_PATH = ROOT / "data" / "examples" / "mining.geojson"
EQ_AREA = "EPSG:6933"          # equal-area, so .area and IoU are honest
METRIC = "EPSG:3857"           # for buffering in metres


def _iou(a, b):
    """Jaccard of two shapely polygons (already in an equal-area CRS)."""
    if not a.intersects(b):
        return 0.0
    inter = a.intersection(b).area
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _greedy_match(pred, gt, thr):
    """Greedy one-to-one IoU matching. `pred`/`gt` are lists of equal-area shapely polygons.
    Returns (tp, fp, fn, matched_ious)."""
    pairs = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gt):
            v = _iou(p, g)
            if v >= thr:
                pairs.append((v, i, j))
    pairs.sort(reverse=True)
    used_p, used_g, ious = set(), set(), []
    for v, i, j in pairs:
        if i in used_p or j in used_g:
            continue
        used_p.add(i); used_g.add(j); ious.append(v)
    tp = len(ious)
    return tp, len(pred) - tp, len(gt) - tp, ious


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sites", type=int, default=20, help="GT mining polygons to sample as eval sites")
    ap.add_argument("--buffer-m", type=float, default=300, help="buffer around each GT poly -> eval box")
    ap.add_argument("--min-area-ha", type=float, default=0.5, help="segment min area (matches the app)")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--iou", type=float, default=0.3, help="IoU threshold for a match (a TP)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write-card", action="store_true", help="write the summary onto mc_barren_v1")
    args = ap.parse_args()

    gt_all = gpd.read_file(GT_PATH)
    if gt_all.crs is None:
        gt_all = gt_all.set_crs("EPSG:4326")
    gt_all = gt_all.to_crs("EPSG:4326")
    sites = gt_all.sample(min(args.n_sites, len(gt_all)), random_state=args.seed).reset_index(drop=True)
    print(f"GT mining polygons: {len(gt_all)} total; sampling {len(sites)} eval sites "
          f"(buffer {args.buffer_m:.0f} m, IoU>={args.iou}, min {args.min_area_ha} ha)\n")

    TP = FP = FN = 0
    all_ious, inter_area, union_area, ok_sites = [], 0.0, 0.0, 0
    for k, seed_geom in enumerate(sites.geometry):
        # eval box = the seed polygon buffered, in lon/lat
        box_geom = (gpd.GeoSeries([seed_geom], crs="EPSG:4326").to_crs(METRIC)
                    .buffer(args.buffer_m).to_crs("EPSG:4326").iloc[0])
        w, s, e, n = box_geom.bounds
        try:
            fc, summ = infer.segment_class((w, s, e, n), year=args.year, cls="mining",
                                           min_area_ha=args.min_area_ha)
        except Exception as ex:
            print(f"  site {k+1:2d}: skipped ({ex})")
            continue
        # predicted polygons (may be empty), and every GT poly overlapping this box, both clipped to it
        box_series = gpd.GeoSeries([box_geom], crs="EPSG:4326")
        pred = gpd.GeoDataFrame(geometry=[shape(f["geometry"]) for f in fc["features"]], crs="EPSG:4326")
        gt_in = gt_all[gt_all.intersects(box_geom)].copy()
        gt_in["geometry"] = gt_in.geometry.intersection(box_geom)
        pred_ea = [g for g in pred.to_crs(EQ_AREA).geometry if not g.is_empty] if len(pred) else []
        gt_ea = [g for g in gt_in.to_crs(EQ_AREA).geometry if not g.is_empty]
        tp, fp, fn, ious = _greedy_match(pred_ea, gt_ea, args.iou)
        TP += tp; FP += fp; FN += fn; all_ious += ious; ok_sites += 1
        # area-level overlap for this box (union of preds vs union of GT)
        pu = unary_union(pred_ea) if pred_ea else None
        gu = unary_union(gt_ea) if gt_ea else None
        if pu is not None and gu is not None:
            inter_area += pu.intersection(gu).area
            union_area += pu.union(gu).area
        print(f"  site {k+1:2d}: pred {len(pred_ea):2d}  gt {len(gt_ea):2d}  "
              f"TP {tp} FP {fp} FN {fn}  meanIoU {sum(ious)/len(ious):.2f}" if ious
              else f"  site {k+1:2d}: pred {len(pred_ea):2d}  gt {len(gt_ea):2d}  TP {tp} FP {fp} FN {fn}")

    prec = TP / (TP + FP) if TP + FP else 0.0
    rec = TP / (TP + FN) if TP + FN else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    mean_iou = sum(all_ious) / len(all_ious) if all_ious else 0.0
    area_iou = inter_area / union_area if union_area else 0.0

    print(f"\n=== Mining pixel+vectorize vs GT polygons ({ok_sites} sites, IoU>={args.iou}) ===")
    print(f"objects: TP {TP}  FP {FP}  FN {FN}")
    print(f"precision {prec:.3f}  recall {rec:.3f}  F1 {f1:.3f}  mean matched IoU {mean_iou:.3f}")
    print(f"area IoU (union pred vs union GT) {area_iou:.3f}")

    summary = (f"Pixel+vectorize vs GT mining polygons ({ok_sites} sites, IoU>={args.iou}): "
               f"precision {prec:.2f}, recall {rec:.2f}, F1 {f1:.2f}, mean IoU {mean_iou:.2f}, "
               f"area IoU {area_iou:.2f} (week11/mining_eval.py).")
    if args.write_card:
        import catalogue
        catalogue.update_card_meta("mc_barren_v1", about={"evidence": summary})
        print("\nwrote summary onto mc_barren_v1 (About > Evidence).")


if __name__ == "__main__":
    main()
