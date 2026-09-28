# Sample logs, one per level

Three real log files, captured from a running service. The **same four requests** were sent in each
case; the only thing that changed between them was `LOG_LEVEL`. So every difference you see between
these files is the level doing its job, not different traffic.

| File | `LOG_LEVEL` | Lines |
|---|---|---|
| [`app.debug.log`](app.debug.log) | `debug` | 17 |
| [`app.info.log`](app.info.log) | `info` | 14 |
| [`app.error.log`](app.error.log) | `error` | 1 |

This is checklist §5 evidence: *"Changing `LOG_LEVEL` switches granularity without a code change."*
No code differs between the three runs. Reproduce them with `scripts/capture_log_samples.ps1`.

## The four requests

1. `GET /api/health` — a plain request
2. `GET /api/hierarchy/export?since=0` — a request **carrying a query string**
3. `POST /api/jobs` with `{"op":"export","params":{"retrain":{"node":"greenery"},"export":false}}` —
   a **compute job**, through trigger to outcome
4. `GET /api/health?token=supersecret123&password=hunter2` — a request with **credentials** in the
   query string

The job fails on purpose. `greenery` has no child classes in the current hierarchy, so there is
nothing to train. A real failure is more useful here than a synthetic one: it shows what an operator
actually sees when something goes wrong, at each level.

## What the checklist asks for, and where it appears

The checklist publishes a table of what each level should contain. Mapping it to these files:

| Level | Checklist says | Where it is |
|---|---|---|
| `debug` | request traces | `GET /api/hierarchy/export?since=0` — with the query string |
| | job params | `job lulc__2a7b... params={'retrain': {'node': 'greenery'}, ...}` |
| | paths | `paths root=... data=... models=... catalogue=...` |
| | Airflow poll | absent here; only appears when `AIRFLOW_API_BASE` is set |
| `info` | startup | `logging at INFO`, `Application startup complete`, `Uvicorn running on ...` |
| | compute trigger | `export: classify + export to a GEE asset` |
| | DAG/run IDs | `job lulc__07ae9fad... created op=export` |
| | job complete | `job lulc__07ae9fad... failed: ...` |
| | auth | empty until §4 Google SSO lands |
| `error` | failures only | the single line in `app.error.log` |

## Reading the three side by side

**`app.info.log` (14 lines)** is the default, and what a deployment runs on. One line per request
with a duration, plus the job lifecycle. Note request 2: it was sent as
`/api/hierarchy/export?since=0`, and the log says only

```
INFO  corestack.request | GET /api/hierarchy/export -> 200 (3 ms)
```

The query string is deliberately not recorded at this level. Request 4 is the same story: it carried
a token and a password, and `info` logs it as a bare `GET /api/health`.

**`app.debug.log` (17 lines)** is the same run with three extra kinds of line:

* the **query string** on request lines, so you can see exactly what was asked for
* **job and export params**, so you can see what a job was actually given
* a **`paths`** line at startup, listing the resolved root, data, models and catalogue directories

That last one is the most useful on a cluster. When a deployment behaves oddly, the first question
is usually "which directories is this container actually reading?", and `debug` answers it in one
line without anyone shelling into the container.

**`app.error.log` (1 line)** is the whole file. Four requests, three of them successful, and nothing
was written for any of them. Only the failure survives:

```
ERROR corestack.backend | job lulc__2e1ea310... failed: 'greenery' has no sub-classes to train — split it or add classes first.
```

Worth knowing: at `error` the startup banner is suppressed too, because it is emitted at info level.
So the console stays completely silent on boot and the log file sits at 0 bytes until something
fails. That looks like a hang and is not one — confirm the service is up with a request to
`/api/health` rather than by watching the console.

## Secrets are scrubbed at every level

Request 4 sent `?token=supersecret123&password=hunter2`. At `debug`, the level where a leak would
actually happen:

```
DEBUG corestack.request | GET /api/health?token=***&password=*** -> 200 (1 ms)
```

Neither value appears anywhere in any of the three files. This is implemented in the **log
formatter** (`src/logging_setup.py`), not at the call sites — it scrubs the finished line, so it
covers every message any module ever writes, including exception text and dict reprs. Nobody has to
remember the rule when adding a log line later, which is the point: a convention that depends on
being remembered eventually is not.

## Where these come from in the running service

* `corestack.request` — the FastAPI middleware in `src/backend.py`, one line per request with its
  duration.
* `corestack.backend` — jobs, the export path, and retraining.
* `uvicorn.error` — uvicorn's own startup and error lines, re-pointed at our handlers so they land
  in the same file. `uvicorn.access` is muted, because our request line already carries everything
  its line would, plus a duration and redaction.
* `corestack` — the startup banner naming the level and the log path.

In a live deployment the file lives at `data/logs/corestack-lulc/app.log`, rotating at 10 MB with 5
backups, written to the `data/` bind mount so it survives the container being recreated.

See [`../logging_demo.md`](../logging_demo.md) for the step-by-step demo that produces these.
