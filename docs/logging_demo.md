# Demonstrating §5 (logging) locally

Checklist item 5, and how to show it satisfied on a laptop.
Reference: <https://docs.core-stack.org/server/cluster-service-checklist/>

## What has to be shown

The acceptance criterion is two claims:

> *"After a container recreate, logs remain under `data/logs/<application_name>/`.
> Changing `LOG_LEVEL` switches granularity without a code change."*

Plus the sub-bullets: logs land on the bind-mounted host dir rather than only in the container
filesystem, `.env.example` lists `LOG_LEVEL=info` with its allowed values, no secrets appear at any
level, and the README shows the host path and how to tail it.

**Run this in Docker, not with a bare `uvicorn`.** The word "container" appears in both the
requirement and the acceptance line. A host-run process demonstrates the `LOG_LEVEL` half and
nothing about the mount, which is the half a reviewer is actually checking. Docker Desktop has to be
running first, otherwise the container will keep stopping (WSL shuts down under it between
commands).

Airflow is not needed. Leave `AIRFLOW_API_BASE` empty and everything runs inline, which is
checklist §2's specified laptop mode, so this demo shows §2 at the same time.

## What each level should produce

This is the table the checklist publishes, and what we emit for it:

| Level | Checklist says | What you will see |
|---|---|---|
| `debug` | request traces, job params, Airflow poll, paths | request lines **with query strings**, job + export params, resolved root/data/models/catalogue paths, DAG poll state |
| `info` | startup, auth, compute trigger, job complete, DAG/run IDs | startup lines, one line per request with duration, `job <run_id> created op=...`, `export: classify + export...`, `export complete: asset=...`, `job <run_id> complete` |
| `error` | failures only | nothing at all on successful traffic; one line per failure |

(`auth` is empty until §4 Google SSO lands.)

## The demo

Six steps, about four minutes.

### 0. Setup

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
```

Confirm local mode, so nothing waits on an unreachable Airflow:

```powershell
Select-String -Path .env -Pattern "^AIRFLOW_API_BASE"
```

Should read `AIRFLOW_API_BASE=` with nothing after it.

Open a second PowerShell window in the same folder to watch the log. This is PowerShell's `tail -f`:

```powershell
Get-Content data\logs\corestack-lulc\app.log -Wait -Tail 20
```

### 1. Show that the level is config, not code

```powershell
Select-String -Path deploy\.env.example -Pattern "LOG_LEVEL"
Select-String -Path docker-compose.yml -Pattern "logs"
```

The first shows `LOG_LEVEL=info` with its allowed values documented. The second shows the compose
file mounting `./data/logs/corestack-lulc` to the container's log path by name.

Worth saying out loud: `APP_NAME = "corestack-lulc"` in `src/logging_setup.py` is what makes the
path `data/logs/corestack-lulc/`, which is the naming the checklist asks for.

### 2. Start at `info`

```powershell
$env:LOG_LEVEL = "info"
docker compose -f docker-compose.yml up -d
```

Allow about a minute: the app loads models and initialises Earth Engine before it serves.

Generate traffic, either by clicking around <http://localhost:8000/> or:

```powershell
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/hierarchy/export?since=0" | Out-Null
```

Use `curl.exe`, not `curl`: bare `curl` in Windows PowerShell is an alias for `Invoke-WebRequest`
and takes different arguments.

The watcher shows one line per request with a duration, and **no query strings**:

```
INFO  corestack.request | GET /api/hierarchy/export -> 200 (3 ms)
```

### 3. Show a job through its lifecycle, still at `info`

```powershell
curl.exe -s -X POST "http://localhost:8000/api/jobs" -H "Content-Type: application/json" -d '{\"op\":\"export\",\"params\":{\"retrain\":{\"node\":\"greenery\"},\"export\":false}}' | Out-Null
```

```
INFO  corestack.backend | job lulc__6a945d39... created op=export
INFO  corestack.backend | export: classify + export to a GEE asset
INFO  corestack.backend | retrain node=greenery algo=linearsvc embedding=ae balance=balanced
ERROR corestack.backend | job lulc__6a945d39... failed: 'greenery' has no sub-classes to train
```

That is §5's info row in one screen: compute trigger, run id, job outcome. The failure is genuine
and fine to show. `greenery` has no children in the current hierarchy, so there is nothing to train,
and it demonstrates that a failure is legible without switching levels.

### 4. Switch to `debug`, touching no code

```powershell
$env:LOG_LEVEL = "debug"
docker compose -f docker-compose.yml up -d --force-recreate
```

Re-run the same two curls from step 2. The same requests now carry their query strings:

```
DEBUG corestack.request | GET /api/hierarchy/export?since=0 -> 200 (3 ms)
```

And two things that only exist at debug:

```
DEBUG corestack.backend | paths root=/app data=/app/data models=/app/models catalogue=/app/data/catalogue
DEBUG corestack.backend | job lulc__eb44c652... params={'retrain': {'node': 'greenery'}, 'export': False}
```

The `paths` line is the one worth pointing at on a cluster deploy: it tells you exactly where that
container is reading and writing, which is the first question when a deploy behaves oddly.

### 5. The container recreate already happened, so prove persistence

Step 4 used `--force-recreate`. The container from step 2 is gone.

```powershell
Select-String -Path data\logs\corestack-lulc\app.log -Pattern "INFO  corestack.request" | Measure-Object | Select-Object -ExpandProperty Count
```

Non-zero. Those lines were written by a container that no longer exists, into a file on the host,
under the mandated path. That is the acceptance criterion.

### 6. Secrets, at the most verbose level

```powershell
curl.exe -s "http://localhost:8000/api/health?token=supersecret123&password=hunter2" | Out-Null
```

```
DEBUG corestack.request | GET /api/health?token=***&password=*** -> 200 (1 ms)
```

Still scrubbed at `debug`, which is the level where a leak would actually happen. The reason is
worth a sentence: redaction is implemented in the **log formatter**, not at the call sites, so it
applies to every line any module ever writes, including exception text and dict reprs. Nobody has to
remember the rule when adding a log line later.

### Optional: `error`

```powershell
$env:LOG_LEVEL = "error"
docker compose -f docker-compose.yml up -d --force-recreate
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/tree" | Out-Null
```

Nothing is written. Repeat the failing job from step 3 and exactly one line appears. Verified: two
successful requests produce zero log lines.

## Afterwards

```powershell
docker compose -f docker-compose.yml down
```

## If Docker will not cooperate

Every step except 5 works against a host-run process:

```powershell
$env:LOG_LEVEL = "debug"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

Restart it between level changes instead of recreating the container. Say plainly that the
persistence half of the criterion is not being shown, rather than letting a restart stand in for a
container recreate. They are not the same claim.

## PowerShell equivalents

| Unix | PowerShell |
|---|---|
| `tail -f file` | `Get-Content file -Wait -Tail 20` |
| `tail -20 file` | `Get-Content file -Tail 20` |
| `grep X file` | `Select-String -Path file -Pattern X` |
| `grep -c X file` | `(Select-String -Path file -Pattern X).Count` |
| `curl url` | `curl.exe url` |
| `rm -rf dir` | `Remove-Item -Recurse -Force dir` |
