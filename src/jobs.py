"""File-backed job store for the Airflow-orchestrated ops.

One JSON file per job under DATA_DIR/jobs/, keyed by the Airflow run_id. Deliberately on disk, not
in memory: the DAG's result-post can land on a different uvicorn worker than the one that created the
job, and the store should survive a restart. Jobs are small, so a file each is fine.

State machine: running -> success (result stored) | failed (error stored).
"""
import json
import time
import uuid
from pathlib import Path

import config

_DIR = Path(config.project_path("data/jobs"))


def _path(run_id: str) -> Path:
    # run_ids we mint are safe, but a caller-supplied one shouldn't escape the dir
    safe = run_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return _DIR / f"{safe}.json"


def new_run_id() -> str:
    """A run_id we control, so we can hand it to the frontend before Airflow schedules anything and
    the DAG can reuse the same id from its context."""
    return f"lulc__{uuid.uuid4().hex}"


def create(run_id: str, op: str, params: dict) -> dict:
    _DIR.mkdir(parents=True, exist_ok=True)
    job = {"run_id": run_id, "op": op, "params": params, "state": "running",
           "result": None, "error": None, "created": time.time(), "updated": time.time()}
    _write(job)
    return job


def get(run_id: str) -> dict | None:
    p = _path(run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def set_result(run_id: str, result: dict) -> dict | None:
    """Mark a job done with its work result (what the DAG posts back on success)."""
    job = get(run_id)
    if job is None:
        return None
    job.update(state="success", result=result, updated=time.time())
    _write(job)
    return job


def set_failed(run_id: str, error: str) -> dict | None:
    job = get(run_id)
    if job is None:
        return None
    job.update(state="failed", error=error, updated=time.time())
    _write(job)
    return job


def live(op: str, ws: str, fresh_s: float) -> str | None:
    """A running job of this op in this workspace that beat within fresh_s, or None. On disk, so
    every worker process sees the same answer."""
    for p in _DIR.glob("*.json") if _DIR.exists() else []:
        try:
            j = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if (j.get("op") == op and j.get("state") == "running" and j.get("params", {}).get("ws") == ws
                and time.time() - j.get("updated", 0) < fresh_s):
            return j["run_id"]
    return None


def touch(run_id: str):
    """A heartbeat: the job is still being worked on."""
    job = get(run_id)
    if job and job["state"] == "running":
        job["updated"] = time.time()
        _write(job)


def _write(job: dict):
    # write-then-rename so a reader never sees a half-written file
    p = _path(job["run_id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(job))
    tmp.replace(p)
