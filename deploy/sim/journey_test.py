"""Drive the whole user journey against a running server, as two users plus a visitor.

Needs the app up locally with the dev login (no GOOGLE_CLIENT_ID) and Earth Engine working, since
training and running are real. Usage:

    uvicorn backend:app --app-dir src --port 8000
    python deploy/sim/journey_test.py [--base http://127.0.0.1:8000] [--keep]   (sim.sh test runs it)

What it checks, in order (the numbers match the printout):
  1  signed out: no writes, no compute, no project list
  2  sign-in (dev) sets a cookie; each user sees only their own projects
  3  Alice builds her own split from an upload in the standard format (acacia crowns), trains it
  4  Alice runs; the run is saved and redraws without re-running
  5  Bob uses a zoo model for the same class with his own class names (the mapping step)
  6  the two projects never see each other's classes or weights; data/ is untouched
  7  Bob can't read or write Alice's project; her run survives her own later reset
  8  Alice makes it public: a visitor can view, Bob can copy, nobody else can write
  9  GeoTIFF + project zip download
Everything it creates is deleted at the end unless --keep.
"""
import argparse
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parents[2]      # repo root (this file sits in deploy/sim/)
IIT = [77.165, 28.520, 77.205, 28.560]     # the IIT Delhi + Sanjay Van preset: the crowns sit inside it
fails = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)


def acacia_upload(per_class=60):
    """The desk/field/species crowns as a standard-format upload: `class` from
    label_acacia_clean_confident (sir's final column), slivers under 15 m2 dropped (week 11's filter)."""
    g = gpd.read_file(ROOT / "data" / "inputs" / "acacia_clean_confident_labels.geojson")
    g = g[g["label_acacia_clean_confident"].isin([0, 1])].copy()
    g = g[g.to_crs(32643).area >= 15]
    g["class"] = g["label_acacia_clean_confident"].map({1: "acacia", 0: "non_acacia"})
    g = gpd.GeoDataFrame(
        __import__("pandas").concat([d.sample(min(per_class, len(d)), random_state=0)
                                     for _, d in g.groupby("class")]), crs=g.crs)
    fc = json.loads(g[["class", "geometry"]].to_json())
    return json.dumps(fc).encode(), g["class"].value_counts().to_dict()


def session(base, name=None):
    s = requests.Session()
    if name:
        r = s.post(f"{base}/api/auth/dev", json={"name": name})
        r.raise_for_status()
    return s


def train(sess, base, headers, timeout=3600, **opts):
    """Train the way the page does: start the job, then poll it. Returns (ok, result or error)."""
    r = sess.post(f"{base}/api/retrain", json=opts, headers=headers, timeout=60)
    if not r.ok:
        return False, r.json().get("detail", r.text) if "json" in r.headers.get("content-type", "") else r.text
    run_id, t0 = r.json()["run_id"], time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        j = sess.get(f"{base}/api/jobs/{run_id}", headers=headers, timeout=60).json()
        if j.get("done"):
            return j["success"], j.get("result") if j["success"] else j.get("error")
    return False, "still training after the timeout"


def weights_hash(pid, node):
    f = ROOT / "data" / "projects" / pid / "weights" / f"{node}.joblib"
    return hashlib.md5(f.read_bytes()).hexdigest() if f.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--keep", action="store_true", help="leave the test projects behind")
    a = ap.parse_args()
    base = a.base
    global_tree = (ROOT / "data" / "hierarchy.json").read_bytes()

    print("1  signed out")
    anon = session(base)
    check(anon.post(f"{base}/api/projects", json={"name": "x", "bbox": IIT}).status_code == 401, "can't create a project")
    check(anon.get(f"{base}/api/projects").status_code == 401, "can't list projects")
    check(anon.post(f"{base}/api/split", json={"parent": "greenery", "children": ["a", "b"]}).status_code == 401,
          "can't change a scheme")

    print("2  sign-in, own projects only")
    alice, bob = session(base, "Journey Alice"), session(base, "Journey Bob")
    check("corestack_lulc_session" in alice.cookies, "dev sign-in sets the session cookie")
    pa = alice.post(f"{base}/api/projects", json={"name": "Sanjay Van acacia", "bbox": IIT, "year": 2024}).json()
    pb = bob.post(f"{base}/api/projects", json={"name": "Sanjay Van tea test", "bbox": IIT, "year": 2024}).json()
    check(pa.get("id") and pb.get("id"), f"both created ({pa.get('id')}, {pb.get('id')})")
    names_a = [p["name"] for p in alice.get(f"{base}/api/projects").json()["projects"]]
    check("Sanjay Van acacia" in names_a and "Sanjay Van tea test" not in names_a, "Alice's list has only hers")
    HA, HB = {"X-Project-Id": pa["id"]}, {"X-Project-Id": pb["id"]}

    print("3  Alice: build your own from an upload")
    raw, counts = acacia_upload()
    r = alice.post(f"{base}/api/examples/labelled", data={"node": "greenery"},
                   files={"file": ("crowns.geojson", raw)}, headers=HA)
    check(r.status_code == 200 and set(r.json()["classes"]) == {"acacia", "non_acacia"},
          f"upload split greenery into acacia / non_acacia ({counts})")
    ok, res = train(alice, base, HA, node="greenery", years=[2024])
    check(ok, "trained the split" + (f", held-out acc {res['report']['accuracy']:.3f} on {res['n_test']} px"
                                      if ok else f": {str(res)[:200]}"))
    check(weights_hash(pa["id"], "greenery") is not None, "weights landed in Alice's own folder")

    print("4  Alice: run, then reopen without re-running")
    r = alice.post(f"{base}/api/projects/{pa['id']}/runs", json={}, timeout=600)
    check(r.status_code == 200 and r.json().get("tile_url"), "run 1 drew tiles")
    run1 = r.json()["run"] if r.ok else {}
    check("acacia" in (run1.get("colors") or {}), "run 1's legend has acacia")
    proj = alice.get(f"{base}/api/projects/{pa['id']}").json()
    check(proj["current_run"] == 1 and len(proj["runs"]) == 1, "project records run 1")
    r = alice.get(f"{base}/api/projects/{pa['id']}/runs/1", timeout=600)
    check(r.status_code == 200 and r.json()["run"]["run"] == 1 and r.json().get("tile_url"),
          "run 1 redraws from its snapshot")
    check(r.json()["run"]["op_seq"] == proj["op_seq"], "and it knows the scheme hasn't moved on since")

    print("5  Bob: a zoo model with his own class names")
    r = bob.post(f"{base}/api/apply", json={"card_id": "mc_greenery_prev1_v1", "target_node": "greenery",
                                            "mapping": {"tea": "tea", "non_tea": "tea"}}, headers=HB)
    check(r.status_code == 400, "a mapping that leaves one class is refused")
    r = bob.post(f"{base}/api/apply", json={"card_id": "mc_greenery_prev1_v1", "target_node": "greenery",
                                            "mapping": {"tea": "Tea garden", "non_tea": "Other greenery"}},
                 headers=HB)
    check(r.status_code == 200 and r.json()["classes"] == ["tea_garden", "other_greenery"] or
          (r.ok and sorted(r.json()["classes"]) == ["other_greenery", "tea_garden"]),
          f"applied tea/non_tea as {r.json().get('classes')}")
    r = bob.post(f"{base}/api/projects/{pb['id']}/runs", json={"name": "tea mapped"}, timeout=600)
    check(r.status_code == 200 and {"tea_garden", "other_greenery"} <= set(r.json().get("colors", {})),
          "Bob's run paints his names, not the model's")

    print("6  isolation")
    ta = alice.get(f"{base}/api/tree", headers=HA).json()["tree"]
    tb = bob.get(f"{base}/api/tree", headers=HB).json()["tree"]
    check("acacia" in ta and "tea_garden" not in ta, "Alice's tree has only her classes")
    check("tea_garden" in tb and "acacia" not in tb, "Bob's tree has only his")
    check(weights_hash(pa["id"], "greenery") != weights_hash(pb["id"], "greenery"),
          "two greenery.joblib files, one per project")
    check((ROOT / "data" / "hierarchy.json").read_bytes() == global_tree, "the shared data/hierarchy.json is untouched")

    print("7  ownership")
    check(bob.get(f"{base}/api/projects/{pa['id']}").status_code == 403, "Bob can't open Alice's private project")
    check(bob.post(f"{base}/api/add", json={"parent": "water", "name": "pond"}, headers=HA).status_code == 403,
          "Bob can't write into it")
    check(alice.post(f"{base}/api/retrain", json={"node": "root"}, headers=HA).status_code == 400,
          "nobody retrains the shared base map from a project")
    alice.post(f"{base}/api/session/reset", json={}, headers=HA)
    check("acacia" not in alice.get(f"{base}/api/tree", headers=HA).json()["tree"], "Alice resets her scheme")
    r = alice.get(f"{base}/api/projects/{pa['id']}/runs/1", timeout=600)
    check(r.ok and "acacia" in r.json().get("colors", {}), "run 1 still shows acacia after the reset")

    print("8  public")
    check(bob.patch(f"{base}/api/projects/{pa['id']}", json={"is_public": True}).status_code == 403,
          "Bob can't make Alice's project public")
    check(alice.patch(f"{base}/api/projects/{pa['id']}", json={"is_public": True}).json()["is_public"],
          "Alice makes it public")
    check(anon.get(f"{base}/api/projects/{pa['id']}").status_code == 200, "a visitor can view it")
    check(anon.get(f"{base}/api/projects/{pa['id']}/runs/1", timeout=600).status_code == 200,
          "and see its run")
    check(anon.post(f"{base}/api/add", json={"parent": "water", "name": "pond"}, headers=HA).status_code == 401,
          "but not write")
    check(any(p["id"] == pa["id"] for p in anon.get(f"{base}/api/projects/public").json()["projects"]),
          "it's on the public list")
    c = bob.post(f"{base}/api/projects/{pa['id']}/copy").json()
    check(c.get("name", "").startswith("Copy of") and c.get("current_run") == 0, "Bob copies it (runs stay behind)")

    print("9  downloads")
    r = alice.get(f"{base}/api/projects/{pa['id']}/runs/1/geotiff", timeout=600)
    check(r.ok and r.content[:4] in (b"II*\x00", b"MM\x00*"), f"GeoTIFF, {len(r.content) // 1024} KB")
    r2 = alice.get(f"{base}/api/projects/{pa['id']}/runs/1/geotiff", timeout=60)
    check(r2.ok and r2.content == r.content, "second download served from the run folder")
    z = zipfile.ZipFile(io.BytesIO(alice.get(f"{base}/api/projects/{pa['id']}/download").content))
    names = z.namelist()
    check({"project.json", "hierarchy.json", "runs/run_1/run.json", "runs/run_1/classified.tif",
           "runs/run_1/weights/greenery.joblib"} <= set(names), f"project zip ({len(names)} files)")

    print("10 import + the per-class upload")
    zbytes = alice.get(f"{base}/api/projects/{pa['id']}/download").content
    r = bob.post(f"{base}/api/projects/import", files={"file": ("alice.zip", zbytes)})
    imp = r.json() if r.ok else {}
    check(r.ok and imp.get("current_run") == 1, "Bob imports Alice's zip: a new project with her run 1")
    if r.ok:
        rr = bob.get(f"{base}/api/projects/{imp['id']}/runs/1", timeout=600)
        check(rr.ok and "acacia" in rr.json().get("colors", {}), "and the imported run redraws")
    old = {"kind": "corestack-lulc-project", "version": 1, "aoi": IIT, "year": 2023, "base_scheme": "indiasat",
           "hierarchy": json.loads((ROOT / "data" / "hierarchy.json").read_text()), "sequence": []}
    r = bob.post(f"{base}/api/projects/import", files={"file": ("old_save.json", json.dumps(old).encode())})
    old_p = r.json() if r.ok else {}
    check(r.ok and old_p.get("year") == 2023, f"an old project.json imports (splits to retrain: "
                                              f"{old_p.get('missing_classifiers')})")
    check(bob.post(f"{base}/api/projects/import", files={"file": ("junk.json", b"{}")}).status_code == 400,
          "a file with no area is refused")
    one_class = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[
            [77.186, 28.545], [77.187, 28.545], [77.187, 28.546], [77.186, 28.546], [77.186, 28.545]]]}}]})
    r = bob.post(f"{base}/api/examples/upload", data={"node": "tea_garden", "role": "positive"},
                 files={"file": ("tea.geojson", one_class.encode())}, headers=HB)
    check(r.ok and r.json().get("total") == 1, "a plain (unlabelled) file lands on the class it's sent to")

    if not a.keep:
        for s, pid in ((bob, imp.get("id")), (bob, old_p.get("id"))):
            if pid:
                s.delete(f"{base}/api/projects/{pid}")
        for s, pid in ((alice, pa["id"]), (bob, pb["id"]), (bob, c.get("id"))):
            if pid:
                s.delete(f"{base}/api/projects/{pid}")
    print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
