"""Every training option in the class panel, through nginx, the way the page drives it.

Uses the full acacia crown file (336 acacia / 576 not), the same upload that hit a 504 on the tower.
Valid combinations must train (and the long ones must outlive nginx's 60 s); impossible ones must be
refused in a second or two with a reason. Needs the dev login. Usage (sim.sh trainmatrix runs it):

    python deploy/sim/train_matrix.py [--base http://nginx:8080/act4dws5/diy-lulc] [--part quick|slow|all]
"""
import argparse
import json
import sys
import time

import requests

from journey_test import ROOT, IIT, check, fails, session, train

JHARIA = [86.38, 23.72, 86.44, 23.78]      # not a Tessera site


def crowns():
    """The crown file as a standard upload: class aa (acacia) / bb (everything else labelled)."""
    fc = json.loads((ROOT / "data" / "inputs" / "acacia_clean_confident_labels.geojson").read_text())
    keep = []
    for f in fc["features"]:
        v = f["properties"].get("label_acacia_clean_confident")
        if v in (0, 1):
            keep.append({"type": "Feature", "geometry": f["geometry"],
                         "properties": {"class": "aa" if v == 1 else "bb"}})
    return json.dumps({"type": "FeatureCollection", "features": keep}).encode()


def refused(sess, base, h, why, **opts):
    t0 = time.time()
    r = sess.post(f"{base}/api/retrain", json={"node": "greenery", **opts}, headers=h, timeout=60)
    s = time.time() - t0
    check(r.status_code == 400 and s < 5, f"refused in {s:.1f}s: {why}  ({r.status_code} {r.text[:120]})")


def trains(sess, base, h, why, run=False, **opts):
    t0 = time.time()
    ok, res = train(sess, base, h, node="greenery", **opts)
    s = time.time() - t0
    acc = res.get("report", {}).get("accuracy") if ok else None
    check(ok, f"trained in {s:.0f}s: {why}" + (f", acc {acc:.3f}" if acc is not None else "")
          + ("" if ok else f"  ({str(res)[:160]})"))
    if ok and run:
        pid = h["X-Project-Id"]
        r = sess.post(f"{base}/api/projects/{pid}/runs", json={}, timeout=900)
        d = r.json() if r.ok else {}
        check(r.ok and (d.get("tile_url") or d.get("points") or d.get("render")),
              f"  and a run draws it ({r.status_code} {d.get('render') or r.text[:120]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--part", choices=("quick", "slow", "all"), default="all",
                    help="quick: refusals + Alpha Earth 2024; slow: multi-year + Tessera")
    a = ap.parse_args()
    base = a.base
    u = session(base, "Matrix Tester")
    p = u.post(f"{base}/api/projects", json={"name": "train matrix", "bbox": IIT, "year": 2024}).json()
    q = u.post(f"{base}/api/projects", json={"name": "train matrix jharia", "bbox": JHARIA, "year": 2024}).json()
    h, hq = {"X-Project-Id": p["id"]}, {"X-Project-Id": q["id"]}
    try:
        print("upload: greenery -> aa / bb from the whole crown file")
        r = u.post(f"{base}/api/examples/labelled", data={"node": "greenery"},
                   files={"file": ("crowns.geojson", crowns())}, headers=h, timeout=300)
        check(r.ok, f"upload ({r.status_code} {r.text[:120]})")
        u.post(f"{base}/api/split", json={"parent": "greenery", "children": ["aa", "bb"]}, headers=hq)

        if a.part != "slow":
            quick(u, base, h, hq)
        if a.part != "quick":
            slow(u, base, h)
    finally:
        for x in (p, q):
            u.delete(f"{base}/api/projects/{x['id']}")
    print(f"\n{'all passed' if not fails else str(len(fails)) + ' failed'}")
    sys.exit(1 if fails else 0)


def quick(u, base, h, hq):
    print("refused up front")
    refused(u, base, h, "the user's exact case: Tessera across 2019-2025",
            algo="logreg", embedding="tessera", balance="undersample", years=[2019, 2021, 2023, 2025])
    refused(u, base, h, "2025 on Alpha Earth", years=[2023, 2025])
    refused(u, base, h, "2016 on Alpha Earth", years=[2016])
    refused(u, base, h, "Tessera for 2023", embedding="tessera", years=[2023])
    refused(u, base, hq, "Tessera outside the prepared sites", embedding="tessera")
    refused(u, base, h, "XGBoost on Alpha Earth", algo="xgboost")
    refused(u, base, h, "an unknown algorithm", algo="magic")
    refused(u, base, h, "an unknown balance", balance="smote")
    refused(u, base, h, "an unknown embedding", embedding="sentinel")
    r = u.post(f"{base}/api/retrain", json={"node": "root"}, headers=h, timeout=60)
    check(r.status_code == 400, "refused: the shared base map")

    print("one training at a time per project")
    r1 = u.post(f"{base}/api/retrain", json={"node": "greenery"}, headers=h, timeout=60)
    r2 = u.post(f"{base}/api/retrain", json={"node": "greenery"}, headers=h, timeout=60)
    check(r1.ok and r2.status_code == 409, f"second start while one runs -> {r2.status_code}")
    if r1.ok:                                   # let it finish before the matrix starts
        while not u.get(f"{base}/api/jobs/{r1.json()['run_id']}", headers=h).json().get("done"):
            time.sleep(3)

    print("Alpha Earth, 2024")
    for algo in ("linearsvc", "logreg", "ridge"):
        trains(u, base, h, f"{algo}, balanced", algo=algo)
    trains(u, base, h, "logreg, undersample", algo="logreg", balance="undersample")
    trains(u, base, h, "logreg, oversample", algo="logreg", balance="oversample")
    trains(u, base, h, "randomforest (point grid)", algo="randomforest", run=True)
    trains(u, base, h, "auto bake-off", algo="auto")
    trains(u, base, h, "linearsvc, then a run on tiles", algo="linearsvc", run=True)


def slow(u, base, h):
    print("Alpha Earth across years (the long ones, well past 60 s)")
    trains(u, base, h, "logreg, undersample, 2019/2021/2023/2024 (the user's case on AE)",
           algo="logreg", balance="undersample", years=[2019, 2021, 2023, 2024])
    trains(u, base, h, "auto, 2017-2024", algo="auto", years=list(range(2017, 2025)))
    if not u.get(f"{base}/api/tessera-sites").json().get("available"):
        print("Tessera: not installed on this server (the slim image)")
        refused(u, base, h, "Tessera without geotessera", embedding="tessera")
        return
    print("Tessera, 2024, IIT Delhi + Sanjay Van")
    trains(u, base, h, "logreg, undersample (the user's case, fixed years)",
           algo="logreg", embedding="tessera", balance="undersample")
    trains(u, base, h, "linearsvc, years [2024]", embedding="tessera", years=[2024])
    trains(u, base, h, "randomforest", algo="randomforest", embedding="tessera", run=True)
    trains(u, base, h, "auto", algo="auto", embedding="tessera")


if __name__ == "__main__":
    main()
