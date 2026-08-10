"""Example Airflow DAG — drive the Core Stack LULC app over its REST API.

TEMPLATE, not wired to a live Airflow yet (Susmit's point 4: "Airflow for computation if required").
Our classify path already runs server-side in Earth Engine on each request, so Airflow is only worth it
for *batch* work — e.g. classify a list of AOIs on a schedule and emit a STACD provenance record for each,
the way drone_docker's DAGs call back to `DRONE_API_BASE`.

It calls the running container's API (no in-process imports), so the DAG box needs nothing but `requests`.
Set the base URL to wherever the app is reachable from the Airflow worker:

    export CORESTACK_API_BASE=http://<host>:8000        # or an Airflow Variable of the same name
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

# where the LULC app is reachable from the Airflow worker (NOT localhost unless same box)
API_BASE = os.getenv("CORESTACK_API_BASE", "http://lulc:8000")

# the AOIs to process each run — swap for a real source (a Variable, a table, a file)
AOIS = [
    {"name": "iit_sanjayvan", "west": 77.16, "south": 28.53, "east": 77.22, "north": 28.57},
]
YEAR = 2024


def classify_aoi(aoi: dict, **_):
    """Kick a server-side classification for one AOI (the app renders EE tiles, nothing downloads)."""
    r = requests.get(f"{API_BASE}/api/classify", params={**_bbox(aoi), "year": YEAR}, timeout=600)
    r.raise_for_status()
    return r.json().get("counts", {})


def emit_stacd(aoi: dict, **_):
    """Ask the app for the STACD provenance record for that AOI+year, marked for retention."""
    r = requests.get(f"{API_BASE}/api/stacd",
                     params={**_bbox(aoi), "year": YEAR, "archive": "true"}, timeout=600)
    r.raise_for_status()
    return r.json().get("stack", {}).get("id")


def _bbox(aoi: dict) -> dict:
    return {k: aoi[k] for k in ("west", "south", "east", "north")}


default_args = {"retries": 1, "retry_delay": timedelta(minutes=2)}

with DAG(
    dag_id="corestack_lulc_batch",
    description="Batch classify AOIs + emit STACD provenance via the LULC API",
    start_date=datetime(2026, 1, 1),
    schedule=None,                 # trigger manually; set a cron when you want it periodic
    catchup=False,
    default_args=default_args,
    tags=["corestack", "lulc"],
) as dag:
    for aoi in AOIS:
        c = PythonOperator(task_id=f"classify_{aoi['name']}", python_callable=classify_aoi,
                           op_kwargs={"aoi": aoi})
        s = PythonOperator(task_id=f"stacd_{aoi['name']}", python_callable=emit_stacd,
                           op_kwargs={"aoi": aoi})
        c >> s
