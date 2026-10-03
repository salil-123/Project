"""A project on disk: its workspace folder and its runs.

Layout (under the data/ mount, so it survives the container; see week18/app_design.md section 4):

    data/projects/<id>/
      hierarchy.json  op_log.json  merge_rules.json  active_base.json   the scheme, as in data/
      examples/  refine/  weights/                                       the user's data + models
      runs/run_<n>/                                                      one per Run classification

A run folder is laid out like a workspace too: it keeps a copy of the scheme files and the weights
as they were when it ran. So redrawing an old run is just "classify with that folder as the
workspace", and a later retrain can't quietly change what an old run shows. Weights are tiny linear
joblibs (KBs), so the copy costs nothing.

Susmit's version of the same idea: work/run_<n>/ per run, inputs shared across runs (storage.py).
"""
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import config

SCHEME_FILES = ("hierarchy.json", "op_log.json", "merge_rules.json", "active_base.json")


def folder(pid: str) -> Path:
    return config.PROJECTS_DIR / pid


def run_dir(pid: str, n: int) -> Path:
    return folder(pid) / "runs" / f"run_{n}"


def create_folder(pid: str) -> Path:
    d = folder(pid)
    for sub in ("examples", "weights", "runs"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def delete_folder(pid: str) -> None:
    shutil.rmtree(folder(pid), ignore_errors=True)


def _copy_scheme(src: Path, dst: Path) -> None:
    """The scheme files + weights, which is everything a classification needs."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in SCHEME_FILES:
        if (src / f).exists():
            shutil.copy2(src / f, dst / f)
    if (src / "weights").is_dir():
        shutil.copytree(src / "weights", dst / "weights", dirs_exist_ok=True)


def snapshot_run(pid: str, n: int, meta: dict) -> dict:
    """Freeze the project's current scheme into runs/run_<n>/ and write run.json beside it."""
    d = run_dir(pid, n)
    if d.exists():
        shutil.rmtree(d)
    _copy_scheme(folder(pid), d)
    meta = {"run": n, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **meta}
    (d / "run.json").write_text(json.dumps(meta, indent=2))
    return meta


def read_run(pid: str, n: int) -> dict | None:
    f = run_dir(pid, n) / "run.json"
    return json.loads(f.read_text()) if f.exists() else None


def update_run(pid: str, n: int, **fields) -> dict:
    meta = read_run(pid, n) or {"run": n}
    meta.update(fields)
    (run_dir(pid, n) / "run.json").write_text(json.dumps(meta, indent=2))
    return meta


def tif_path(pid: str, n: int) -> Path:
    return run_dir(pid, n) / "classified.tif"


def copy_project(src_pid: str, dst_pid: str) -> None:
    """Someone else's public project into a fresh one of mine: scheme, examples, weights. Not the
    runs, those belong to the original; the copy starts with nothing run yet."""
    src, dst = folder(src_pid), create_folder(dst_pid)
    _copy_scheme(src, dst)
    if (src / "examples").is_dir():
        shutil.copytree(src / "examples", dst / "examples", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("archive"))


def zip_project(pid: str, meta: dict) -> Path:
    """The whole folder as one zip (the training-table cache left out, it's regenerable), with the
    project's DB row as project.json on top so the zip explains itself."""
    src = folder(pid)
    out = src / f"{pid}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(meta, indent=2))
        for p in src.rglob("*"):
            rel = p.relative_to(src)
            if p.is_dir() or p == out or rel.parts[0] == "refine" or "archive" in rel.parts:
                continue
            z.write(p, str(rel))
    return out
