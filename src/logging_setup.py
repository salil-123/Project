"""One place that configures logging for the whole service.

Cluster checklist #5: logs go to a bind-mounted directory so they outlive the container, and
LOG_LEVEL (debug|info|error) changes how much detail comes out without touching code.

    debug  request traces with query params, job params, Airflow polling, resolved paths
    info   startup, compute triggers, DAG/run ids, one line per request
    error  failures only

Everything in the app logs under the "corestack" tree (corestack.backend, corestack.refine, ...), so
one handler set catches the lot. Uvicorn's own loggers are re-pointed at the same handlers, so access
lines land in the same file instead of vanishing to stdout only.
"""
import logging
import logging.handlers
import os
import re
from pathlib import Path

APP_NAME = "corestack-lulc"
_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "error": logging.ERROR,
           "warning": logging.WARNING}   # warning isn't in the checklist but costs nothing to accept
_configured = False

# things that must never reach a log file, however they're spelled. Matches "password=x",
# '"token": "x"', "Authorization: Bearer x" and friends, and keeps the key so the line still reads.
_SECRET = re.compile(
    r'(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|cookie|client[_-]?secret)'
    r'(\s*[=:]\s*)(["\']?)([^\s"\',;&}]+)')


def redact(text: str) -> str:
    """Blank out anything that looks like a credential. Cheap, and it runs on every record."""
    return _SECRET.sub(r'\1\2\3***', str(text))


class _RedactingFormatter(logging.Formatter):
    """A formatter that scrubs the finished line — so a secret can't sneak in through an arg, an
    exception message or a dict repr, only through the one funnel."""

    def format(self, record):
        return redact(super().format(record))


def log_dir() -> Path:
    """data/logs/<application_name>/ — the path the checklist mandates, honouring a relocated
    CORESTACK_DATA_DIR so a container can mount the writable dir elsewhere."""
    import config
    return Path(config.project_path(f"data/logs/{APP_NAME}"))


def configure(level: str | None = None) -> logging.Logger:
    """Wire up handlers once. Safe to call repeatedly (uvicorn's reloader does)."""
    global _configured
    lvl = _LEVELS.get((level or os.getenv("LOG_LEVEL", "info")).strip().lower(), logging.INFO)

    root = logging.getLogger("corestack")
    root.setLevel(lvl)
    if _configured:
        for h in root.handlers:
            h.setLevel(lvl)
        return root

    fmt = _RedactingFormatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    handlers = [stream]

    # the file handler is best-effort: a read-only or unmounted data dir shouldn't stop the app
    # booting, it should just mean stdout-only logging (and say so).
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(d / "app.log", maxBytes=10_000_000,
                                                  backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        handlers.append(fh)
    except OSError as e:
        stream.setLevel(lvl)
        root.addHandler(stream)
        root.propagate = False
        _configured = True
        root.warning("file logging off (%s) — logging to stdout only", e)
        return root

    for h in handlers:
        h.setLevel(lvl)
        root.addHandler(h)
    root.propagate = False        # don't double-print through the root logger

    # uvicorn logs through its own loggers; point them at our handlers so its startup/error lines
    # land in the file too. uvicorn.access is muted: our own middleware already logs every request
    # with a duration and redaction, and two lines per request is just noise.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        u = logging.getLogger(name)
        u.handlers = list(handlers)
        u.propagate = False
        u.setLevel(logging.WARNING if name == "uvicorn.access" else lvl)

    _configured = True
    root.info("logging at %s -> %s", logging.getLevelName(lvl), log_dir() / "app.log")
    return root


def get(name: str) -> logging.Logger:
    """A module logger: get(__name__) in src/foo.py gives 'corestack.foo'."""
    return logging.getLogger(f"corestack.{name.rsplit('.', 1)[-1]}")
