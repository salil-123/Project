"""A stand-in for the tower's STACD DAG, for the simulation only.

STACD's API mode (deploy/stacd/corestack_lulc_algorithm_repo.yaml) forwards the run conf, as it is, to
the algorithm's url, our POST /api/export-asset, and waits for the answer. This does the same, so the
app's Run button goes through Airflow here exactly as it does on the tower. It sends no service token,
like the live DAG.
"""
import os
from datetime import datetime

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

API_BASE = os.getenv("CORESTACK_API_BASE", "http://lulc:8000").rstrip("/")


def export(**context):
    conf = context["dag_run"].conf or {}
    r = requests.post(f"{API_BASE}/api/export-asset", json=conf, timeout=3600)
    if not r.ok:                      # a failed export fails the run, so the app sees "failed"
        raise RuntimeError(f"export-asset answered {r.status_code}: {r.text[:500]}")
    out = r.json()
    return {"status": out.get("status"), "asset_id": out.get("asset_id")}


with DAG("corestack_lulc", start_date=datetime(2026, 1, 1), schedule=None, catchup=False,
         tags=["corestack", "sim"]) as dag:
    PythonOperator(task_id="export_asset", python_callable=export)
