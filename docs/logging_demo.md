# Showing the logs locally (checklist §5)

A copy-paste run-through of the logging, on the laptop, no Docker. Every step below carries its full
commands, including restarts, so nothing has to be scrolled back for or improvised. All of it was
run verbatim in Windows PowerShell 5.1 before it was written down.

Reference: <https://docs.core-stack.org/server/cluster-service-checklist/>

Docker is only needed for the container-recreate half of the acceptance criterion; that version is
at the bottom under "For sign-off". Airflow is not needed at all: `AIRFLOW_API_BASE` is empty, so
everything runs inline, which is checklist §2's laptop mode.

Three PowerShell windows. Each one starts with `cd C:\Users\mrsal\Downloads\summer_attempt2`.

| Window | Job |
|---|---|
| 1 | runs the app |
| 2 | watches the log |
| 3 | sends requests |

---

## 0. Clean slate

**Window 1** — stop anything already running, wipe the log directory:

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Recurse -Force data\logs -ErrorAction SilentlyContinue
```

If you would rather keep the app running and just empty the file:

```powershell
Clear-Content data\logs\corestack-lulc\app.log
```

`Remove-Item` **fails while the app is up** — *"the process cannot access the file 'app.log' because
it is being used by another process"* — because the rotating file handler holds it open. Use
`Clear-Content` then, or stop the app first. The app recreates the directory on startup.

---

## 1. Start at `info`

**Window 1:**

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
$env:LOG_LEVEL = "info"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

Wait 30–60 seconds; it loads the models and initialises Earth Engine before serving. It is ready
when the console prints `Application startup complete.`

`$env:LOG_LEVEL` beats the value in `.env` (`load_dotenv` runs with `override=False`), so the whole
demo is one variable and there are no file edits to undo.

**Window 2** — PowerShell's `tail -f`:

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
Get-Content data\logs\corestack-lulc\app.log -Wait -Tail 20 -Encoding UTF8
```

`-Encoding UTF8` is not optional. The log is UTF-8 and PowerShell 5.1 reads ANSI by default, so
without it an em-dash in a message renders as `â€"`.

---

## 2. `info`: one line per request, no query strings

**Window 3:**

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/hierarchy/export?since=0" | Out-Null
```

Use `curl.exe`, never bare `curl`: in PowerShell `curl` is an alias for `Invoke-WebRequest` and
takes different arguments.

Window 2 shows:

```
INFO  corestack.request | GET /api/health -> 200 (1 ms)
INFO  corestack.request | GET /api/hierarchy/export -> 200 (3 ms)
```

The second request carried `?since=0`. At `info` the query string is not logged.

---

## 3. `info`: a job from trigger to outcome

**Window 3:**

```powershell
curl.exe -s -X POST "http://localhost:8000/api/jobs" -H "Content-Type: application/json" -d '{\"op\":\"export\",\"params\":{\"retrain\":{\"node\":\"greenery\"},\"export\":false}}' | Out-Null
```

```
INFO  corestack.backend | job lulc__e59ed801... created op=export
INFO  corestack.backend | export: classify + export to a GEE asset
INFO  corestack.backend | retrain node=greenery algo=linearsvc embedding=ae balance=balanced years=None
ERROR corestack.backend | job lulc__e59ed801... failed: 'greenery' has no sub-classes to train — split it or add classes first.
INFO  corestack.request | POST /api/jobs -> 200 (17 ms)
```

That is §5's whole `info` row on one screen: compute trigger, run id, job outcome.

The failure is real and fine to show. `greenery` has no children in the current hierarchy, so there
is nothing to train. It makes the point that a failure stays readable without changing level.

---

## 4. Switch to `debug`

**Window 1** — stop the app and start it again at the new level:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$env:LOG_LEVEL = "debug"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

(`Ctrl+C` in Window 1 does the same as the stop block, if the app is in the foreground there.)

No file was edited. Two lines appear at startup that `info` never showed:

```
INFO  corestack | logging at DEBUG -> C:\...\data\logs\corestack-lulc\app.log
DEBUG corestack.backend | paths root=C:\...\summer_attempt2 data=C:\...\data models=C:\...\models catalogue=C:\...\data\catalogue
```

The `paths` line is the one worth pointing at: on a cluster deploy it says exactly where that
process reads and writes, which is the first question when a deploy misbehaves.

**Window 3** — the same three requests as before:

```powershell
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/hierarchy/export?since=0" | Out-Null
curl.exe -s -X POST "http://localhost:8000/api/jobs" -H "Content-Type: application/json" -d '{\"op\":\"export\",\"params\":{\"retrain\":{\"node\":\"greenery\"},\"export\":false}}' | Out-Null
```

Same requests, more detail:

```
DEBUG corestack.request | GET /api/hierarchy/export?since=0 -> 200 (3 ms)
DEBUG corestack.backend | job lulc__8ad92448... params={'retrain': {'node': 'greenery'}, 'export': False}
DEBUG corestack.backend | export params year=2024 bbox=(None, None, None, None) roi_asset=None asset_id=None base_scheme=None
```

The query string is there now, and so are the job and export parameters.

---

## 5. Secrets stay scrubbed at the most verbose level

**Window 3:**

```powershell
curl.exe -s "http://localhost:8000/api/health?token=supersecret123&password=hunter2" | Out-Null
```

```
DEBUG corestack.request | GET /api/health?token=***&password=*** -> 200 (1 ms)
```

Worth a sentence of why: redaction runs in the **log formatter**, not at the call sites. It covers
every line any module ever writes, including exception text and dict reprs, so nobody has to
remember the rule when adding a log line later.

---

## 6. `error`: failures only

**Window 1** — stop and restart once more:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$env:LOG_LEVEL = "error"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

**Window 3** — two requests that succeed:

```powershell
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/tree" | Out-Null
```

Window 2 does not move. **Zero lines** (measured, not estimated). Count it if you like:

```powershell
(Get-Content data\logs\corestack-lulc\app.log -Encoding UTF8 | Measure-Object -Line).Lines
```

Now one request that fails:

```powershell
curl.exe -s -X POST "http://localhost:8000/api/jobs" -H "Content-Type: application/json" -d '{\"op\":\"export\",\"params\":{\"retrain\":{\"node\":\"greenery\"},\"export\":false}}' | Out-Null
```

Exactly **one** line appears:

```
ERROR corestack.backend | job lulc__... failed: 'greenery' has no sub-classes to train — split it or add classes first.
```

---

## 7. The supporting evidence

**Window 3:**

```powershell
Select-String -Path deploy\.env.example -Pattern "LOG_LEVEL"
```

```
LOG_LEVEL=info
```

Documented with its allowed values, which is one of §5's sub-bullets. And
`APP_NAME = "corestack-lulc"` in `src/logging_setup.py` is what puts the file at
`data/logs/corestack-lulc/`, the naming the checklist asks for:

```powershell
Select-String -Path src\logging_setup.py -Pattern "APP_NAME"
```

The `info` lines written before two restarts are still in the file:

```powershell
Select-String -Path data\logs\corestack-lulc\app.log -Pattern "INFO  corestack.request" -Encoding UTF8 | Measure-Object | Select-Object -ExpandProperty Count
```

---

## 8. Stop when finished

**Window 1:** `Ctrl+C`, or from anywhere:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

**Window 2:** `Ctrl+C` to stop tailing.

---

## What this run proves, and what it does not

The acceptance criterion is two claims:

> *"After a container recreate, logs remain under `data/logs/<application_name>/`.
> Changing `LOG_LEVEL` switches granularity without a code change."*

**Claim 2 is fully shown.** Three levels, each matching the table the checklist publishes, switched
by one environment variable, no code change. Plus the mandated path and redaction at the level where
a leak would actually happen.

**Claim 1 is not.** The file survived process restarts here, but the criterion is about a *container
recreate* — the log outliving the container because it lives on a host bind mount. A process restart
is a different and weaker statement. Say so rather than letting the two blur; the container version
below is what closes it.

---

# For sign-off: the same demo in a container

Start **Docker Desktop** first, otherwise WSL shuts down between commands and takes the container
with it.

The structural difference: the recreate that switches you to `debug` **is** the container recreate
that proves persistence. One action, two claims.

**Window 1** — show the mount the checklist asks for, by name, then start at `info`:

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
docker compose -f docker-compose.yml config | Select-String "logs"
$env:LOG_LEVEL = "info"
docker compose -f docker-compose.yml up -d
```

Allow about a minute. **Window 2** tails exactly as in step 1, or:

```powershell
docker compose -f docker-compose.yml logs -f lulc
```

**Window 3** — run steps 2 and 3 unchanged, then switch level and destroy the old container in one
action:

```powershell
$env:LOG_LEVEL = "debug"
docker compose -f docker-compose.yml up -d --force-recreate
```

Run steps 4 and 5 unchanged. Then the proof:

```powershell
Select-String -Path data\logs\corestack-lulc\app.log -Pattern "INFO  corestack.request" -Encoding UTF8 | Measure-Object | Select-Object -ExpandProperty Count
```

Non-zero. Those lines were written by a container that no longer exists, into a file on the **host**,
under the mandated path. That is claim 1; with the level switch it is the whole criterion.

```powershell
docker compose -f docker-compose.yml down
```

---

## What each level should contain

The table the checklist publishes, against what we emit:

| Level | Checklist says | What you saw |
|---|---|---|
| `debug` | request traces, job params, Airflow poll, paths | query strings on request lines, job + export params, resolved root/data/models/catalogue paths |
| `info` | startup, auth, compute trigger, job complete, DAG/run IDs | startup lines, one line per request with duration, job created with run id, export trigger, job outcome |
| `error` | failures only | nothing on successful traffic; one line per failure |

`auth` stays empty until §4 Google SSO lands. `Airflow poll` only appears when `AIRFLOW_API_BASE`
is set.

## PowerShell equivalents

| Unix | PowerShell |
|---|---|
| `tail -f file` | `Get-Content file -Wait -Tail 20 -Encoding UTF8` |
| `tail -20 file` | `Get-Content file -Tail 20 -Encoding UTF8` |
| `grep X file` | `Select-String -Path file -Pattern X -Encoding UTF8` |
| `grep -c X file` | `(Select-String -Path file -Pattern X -Encoding UTF8).Count` |
| `curl url` | `curl.exe url` |
| `rm -rf dir` | `Remove-Item -Recurse -Force dir` |
