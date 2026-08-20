"""Airflow DAG for the Core Stack LULC job flow.

Triggered over the REST API by the backend (POST /api/jobs) with a run conf carrying the op, its
params, and where to reach the backend. The single task calls the backend's real work endpoint and
BLOCKS on it, then posts the result back to /api/jobs/{run_id}/result. So the chain stays synchronous:
the DAG doesn't finish until the backend returns success, and the frontend polls the backend till the
result lands. See deploy/airflow_job_flow_plan.md.

Needs nothing but `requests` on the worker — it drives the running container over HTTP, no in-process
imports. The DAG box reaches the backend at the `api_base` passed in the conf (fallback env below).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

# fallback backend URL if a run conf doesn't carry api_base (it normally does)
API_BASE = os.getenv("CORESTACK_API_BASE", "http://lulc:8000").rstrip("/")


def run_job(**context):
    """Do one job: read the conf, call the matching backend work endpoint, post the result back."""
    conf = (context["dag_run"].conf or {})
    run_id = conf.get("run_id") or context["dag_run"].run_id
    api_base = (conf.get("api_base") or API_BASE).rstrip("/")
    op = conf.get("op")
    params = conf.get("params", {})

    try:
        if op == "classify":
            r = requests.get(f"{api_base}/api/classify", params=params, timeout=1200)
        elif op == "export":
            r = requests.post(f"{api_base}/api/export-asset", json=params, timeout=3600)
        else:
            raise ValueError(f"unknown op {op!r}")
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        # tell the backend it failed so the frontend stops polling, then fail the task
        requests.post(f"{api_base}/api/jobs/{run_id}/result",
                      json={"ok": False, "error": str(e)}, timeout=60)
        raise

    # success: hand the result back to the backend, which flips the job to done
    resp = requests.post(f"{api_base}/api/jobs/{run_id}/result",
                         json={"ok": True, "result": result}, timeout=60)
    resp.raise_for_status()
    return run_id


default_args = {"retries": 0, "retry_delay": timedelta(minutes=1)}

with DAG(
    dag_id="corestack_lulc_job",
    description="Run one Core Stack LULC op (classify/export) and post the result back to the backend",
    start_date=datetime(2026, 1, 1),
    schedule=None,                 # triggered via the REST API with a run conf
    catchup=False,
    default_args=default_args,
    tags=["corestack", "lulc"],
) as dag:
    PythonOperator(task_id="run_job", python_callable=run_job)
