"""Checks for the simulated tower, run inside the app container by sim.sh (needs only requests).

    python deploy/sim/checks.py visitor  [--base URL]   signed out: public outputs visible, nothing writable
    python deploy/sim/checks.py dag      [--base URL]   a Run through Airflow, as the Run button does it
    python deploy/sim/checks.py towernet [--base URL]   broken DNS: sign-in and the deep check fail fast and say why

The base defaults to nginx at the tower's sub-path. Exit code 1 if anything failed.
"""
import argparse
import sys
import time

import requests

fails = []


def check(ok, what, extra=""):
    print(("  ok   " if ok else "  FAIL ") + what + (f"  ({extra})" if extra else ""))
    if not ok:
        fails.append(what)


def visitor(B):
    s = requests.Session()                       # never signs in
    pub = s.get(f"{B}/api/projects/public").json()["projects"]
    check(bool(pub), "the front page lists public projects", f"{len(pub)}")
    p = next((x for x in pub if "sample" in x["name"]), pub[0])
    pid, H = p["id"], {"X-Project-Id": p["id"]}
    check(s.get(f"{B}/api/projects/{pid}").ok, "a visitor opens the project")
    tree = s.get(f"{B}/api/tree", headers=H)
    check(tree.ok and "root" in tree.json().get("tree", {}), "and sees its class hierarchy")
    check(s.get(f"{B}/api/oplog", headers=H).ok, "and how it was built (operations)")
    for n in range(1, (p.get("current_run") or 0) + 1):
        r = s.get(f"{B}/api/projects/{pid}/runs/{n}", timeout=120)
        check(r.ok and "tile" in r.text, f"and run {n}'s map", r.status_code)
    z = s.get(f"{B}/api/projects/{pid}/download")
    check(z.ok and z.headers.get("content-type") == "application/zip", "and downloads the project zip")
    check(s.get(f"{B}/api/catalogue").ok, "and browses the model zoo")
    for label, r in (("rename it", s.patch(f"{B}/api/projects/{pid}", json={"name": "x"})),
                     ("run it", s.post(f"{B}/api/projects/{pid}/runs", json={})),
                     ("delete it", s.delete(f"{B}/api/projects/{pid}")),
                     ("change its classes", s.post(f"{B}/api/split", headers=H,
                                                   json={"node": "water", "children": ["a", "b"]}))):
        check(r.status_code == 401, f"but can't {label}", r.status_code)


def dag(B):
    s = requests.Session()
    r = s.post(f"{B}/api/auth/dev", json={"name": "Sim Dag"})
    if not r.ok:
        check(False, "local sign-in (start the sim with --local-login)", r.status_code)
        return
    p = s.post(f"{B}/api/projects", json={"name": "sim dag run", "bbox": [77.175, 28.535, 77.19, 28.55]}).json()
    conf = {"region": p["bbox"], "year": str(p["year"]), "base_scheme": p["base_scheme"],
            "project_id": p["id"], "execution_type": "fullexec"}      # what the Run button sends
    r = s.post(f"{B}/api/dag/run", json={"conf": conf})
    check(r.ok, "Airflow takes the run", r.status_code)
    if not r.ok:
        print("   ", r.text[:300])
        return
    run_id, t0 = r.json()["dag_run_id"], time.time()
    # what the Run button does now: save the run at once, let the export finish in Airflow
    r = s.post(f"{B}/api/projects/{p['id']}/runs", json={"dag_run_id": run_id})
    check(r.ok and r.json().get("run", {}).get("run") == 1, "the run is saved without waiting for the export",
          f"{time.time() - t0:.0f} s")
    state = None
    while time.time() - t0 < 30 * 60:          # the DAG must answer inside the tower's ~30 min
        st = s.get(f"{B}/api/dag/status", params={"run_id": run_id}).json()
        if st.get("state") != state:
            state = st.get("state")
            print(f"    {int(time.time() - t0):4d} s  {state}")
        if st.get("done"):
            break
        time.sleep(15)
    check(state == "success", "and Airflow finishes the catalogue export", f"{state}, {int(time.time() - t0)} s")
    s.delete(f"{B}/api/projects/{p['id']}")


def towernet(B):
    t = time.time()
    r = requests.get(f"{B}/api/health", timeout=30)
    check(r.ok, "the site itself still answers", f"{time.time() - t:.1f} s")
    t = time.time()
    r = requests.post(f"{B}/api/auth/google", json={"credential": "not.a.token"}, timeout=90)
    took = time.time() - t
    check(r.status_code == 503 and took < 20, "sign-in gives up quickly and says why",
          f"{r.status_code} in {took:.1f} s: {r.text[:90]}")
    t = time.time()
    r = requests.get(f"{B}/api/health?deep=1", timeout=90)
    took = time.time() - t
    reach = r.json().get("reach", {}) if r.ok else {}
    check(r.ok and took < 30 and all("DNS lookup failed" in v for v in reach.values()),
          "the deep check names DNS", f"{took:.1f} s: {list(reach.values())[:1]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["visitor", "dag", "towernet"])
    ap.add_argument("--base", default="http://nginx:8080/act4dws5/diy-lulc")
    a = ap.parse_args()
    print(a.what)
    {"visitor": visitor, "dag": dag, "towernet": towernet}[a.what](a.base.rstrip("/"))
    print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
    sys.exit(1 if fails else 0)
