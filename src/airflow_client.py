"""Thin wrapper over the Airflow 2.x stable REST API — just the two calls the job flow needs:
trigger a DAG run, and read a run's state. Config-driven; if AIRFLOW_API_BASE is empty the caller
treats Airflow as absent and runs the work inline instead.
"""
import logging

import requests

import config

_TIMEOUT = 30
log = logging.getLogger("corestack.airflow")


def configured() -> bool:
    return bool(config.AIRFLOW_API_BASE)


def _auth():
    # bearer token wins if set, else basic auth; returns (auth, headers) for requests
    if config.AIRFLOW_TOKEN:
        return None, {"Authorization": f"Bearer {config.AIRFLOW_TOKEN}"}
    if config.AIRFLOW_USERNAME:
        return (config.AIRFLOW_USERNAME, config.AIRFLOW_PASSWORD), {}
    return None, {}


def trigger(run_id: str, conf: dict) -> dict:
    """Fire DAG AIRFLOW_DAG_ID with our own run_id (so we can return it before Airflow schedules) and
    the job conf. Raises on a non-2xx so the caller can fall back / report the failure."""
    auth, headers = _auth()
    url = f"{config.AIRFLOW_API_BASE}/dags/{config.AIRFLOW_DAG_ID}/dagRuns"
    r = requests.post(url, json={"dag_run_id": run_id, "conf": conf},
                      auth=auth, headers=headers, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def trigger_conf(conf: dict) -> dict:
    """Trigger the DAG with just a run conf and let Airflow mint the dag_run_id (the STACD-style call).
    Returns Airflow's response json (carries dag_run_id + state). Raises on a non-2xx."""
    auth, headers = _auth()
    url = f"{config.AIRFLOW_API_BASE}/dags/{config.AIRFLOW_DAG_ID}/dagRuns"
    log.info("trigger POST %s conf=%s", url, conf)
    r = requests.post(url, json={"conf": conf}, auth=auth, headers=headers, timeout=_TIMEOUT)
    log.info("trigger <- HTTP %s %s", r.status_code, r.text[:400])
    r.raise_for_status()
    return r.json()


def run_state(run_id: str) -> str | None:
    """The DAG run's state (queued/running/success/failed), or None if we can't read it."""
    auth, headers = _auth()
    url = f"{config.AIRFLOW_API_BASE}/dags/{config.AIRFLOW_DAG_ID}/dagRuns/{run_id}"
    try:
        r = requests.get(url, auth=auth, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        state = r.json().get("state")
        log.info("state %s -> %s", run_id, state)
        return state
    except requests.RequestException as e:
        log.warning("state %s failed: %s", run_id, e)
        return None
