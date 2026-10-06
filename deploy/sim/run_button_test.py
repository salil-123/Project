"""Press the real Run button against the simulated tower and time it (Playwright, from the host).

    python deploy/sim/run_button_test.py [--base http://localhost:8080/act4dws5/diy-lulc]

Needs the sim up with --local-login. Signs in by name, makes a small project, presses Run, and checks
the run is saved and drawn while Airflow is still exporting in the background. Deletes the project after.
"""
import argparse
import sys
import time

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://localhost:8080/act4dws5/diy-lulc")
B = ap.parse_args().base.rstrip("/")
fails = []


def check(ok, what, extra=""):
    print(("  ok   " if ok else "  FAIL ") + what + (f"  ({extra})" if extra else ""))
    if not ok:
        fails.append(what)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1400, "height": 860})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(B + "/")
    pg.fill("#devName", "Run Button")
    pg.click("#devGo")
    pg.wait_for_selector("#start:not(.hidden)", timeout=60_000)
    check(pg.evaluate("window.CORESTACK_CFG.airflow"), "the page knows Airflow is wired")
    pg.fill("#npName", "run button test")
    pg.click("#npCreate")
    pg.wait_for_selector("#projHead:not(.hidden)", timeout=60_000)
    t0 = time.time()
    pg.click("#run")
    pg.wait_for_function("document.querySelectorAll('.run-item').length > 0", timeout=300_000)
    took = time.time() - t0
    check(took < 120, "Run saves the run without waiting for the export", f"{took:.0f} s")
    pg.wait_for_selector(".map-legend", timeout=120_000)
    check(True, "and the map draws with its legend")
    dag_id = pg.evaluate("(PROJECT.runs || [])[0]") and pg.evaluate(
        "fetch(api(`/api/projects/${PROJECT.id}/runs/1`)).then(r => r.json()).then(d => d.run.dag_run_id)")
    check(bool(dag_id), "the run remembers its Airflow run", dag_id)
    status = pg.evaluate("document.querySelector('#toast')?.textContent || ''")
    check("saved" in status.lower(), "the page says it's saved", status[:80])
    pg.evaluate("fetch(api(`/api/projects/${PROJECT.id}`), {method: 'DELETE'})")
    check(not errors, "no page errors", "; ".join(errors)[:120])
    b.close()

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
