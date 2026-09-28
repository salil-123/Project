# Demonstrating §5 (logging)

Checklist item 5, and how to show it satisfied.
Reference: <https://docs.core-stack.org/server/cluster-service-checklist/>

Two tracks, each runnable start to finish. Pick one:

* **Track A — local, no Docker.** Runs on the laptop with `uvicorn`. Proves the `LOG_LEVEL` half of
  the criterion completely. Use it to rehearse, or when Docker is not cooperating.
* **Track B — container.** The same demo under `docker compose`. Proves **both** halves, so this is
  the one for sign-off.

Read "What has to be shown" first either way, because the difference between the tracks is exactly
which claim you can make at the end.

---

## What has to be shown

The acceptance criterion is two claims:

> *"After a container recreate, logs remain under `data/logs/<application_name>/`.
> Changing `LOG_LEVEL` switches granularity without a code change."*

Claim 1 is about the **bind mount**: the log survives the container being destroyed, because the
file lives on the host rather than in the container filesystem. **Only Track B shows this.** Track A
shows a file surviving a process restart, which is a weaker and different statement. Say which one
you are showing; do not let a process restart stand in for a container recreate.

Claim 2 is about **`LOG_LEVEL`**: granularity changes from config alone. Both tracks show it fully.

The sub-bullets, satisfied by either track: logs land under `data/logs/corestack-lulc/`,
`.env.example` lists `LOG_LEVEL=info` with its allowed values, no secrets appear at any level, and
the README documents the host path and how to tail it.

Airflow is not needed. Leave `AIRFLOW_API_BASE` empty and everything runs inline, which is
checklist §2's specified laptop mode, so either track demonstrates §2 as a side effect.

## What each level should produce

The table the checklist publishes, against what we emit for it:

| Level | Checklist says | What you will see |
|---|---|---|
| `debug` | request traces, job params, Airflow poll, paths | request lines **with query strings**, job + export params, resolved root/data/models/catalogue paths |
| `info` | startup, auth, compute trigger, job complete, DAG/run IDs | startup lines, one line per request with duration, `job <run_id> created op=...`, `export: classify + export...`, job outcome |
| `error` | failures only | nothing at all on successful traffic; one line per failure |

(`auth` stays empty until §4 Google SSO lands.)

---

# Track A — local, no Docker

Four steps, about three minutes. Everything runs from the repo root:

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
```

## A0. Two windows

**Window 1** runs the app. **Window 2** watches the log:

```powershell
cd C:\Users\mrsal\Downloads\summer_attempt2
Get-Content data\logs\corestack-lulc\app.log -Wait -Tail 20 -Encoding UTF8
```

`-Encoding UTF8` is not optional. The log is UTF-8, Windows PowerShell 5.1 reads ANSI by default,
and without it a non-ASCII character renders as `â€"` mid-demo. If the file does not exist yet,
start the app first (A1), then run this.

### Clearing the log first

Two ways, and the difference matters because the running app holds `app.log` open.

**While the app is running** — truncate in place. The app keeps writing to the same handle, so
nothing needs restarting:

```powershell
Clear-Content data\logs\corestack-lulc\app.log
```

**With the app stopped** — delete the whole directory for a true zero state:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Recurse -Force data\logs -ErrorAction SilentlyContinue
```

`Remove-Item` on its own **fails while the app is running** with *"The process cannot access the
file 'app.log' because it is being used by another process."* That is the rotating file handler
holding it open, and it is an easy thing to trip over in front of an audience. Use `Clear-Content`
if the app is up, or stop it first.

The app recreates the directory on startup, so deleting it is safe.

## A1. Start at `info`

**Window 1:**

```powershell
$env:LOG_LEVEL = "info"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

Takes 30–60 seconds: it loads the models and initialises Earth Engine before it serves.

`$env:LOG_LEVEL` overrides the value in `.env` (`load_dotenv` runs with `override=False`, so the
shell wins). That keeps the demo to one variable and leaves no file edits to undo afterwards.

Worth showing before moving on:

```powershell
Select-String -Path deploy\.env.example -Pattern "LOG_LEVEL"
```

`LOG_LEVEL=info` with its allowed values documented, which is one of §5's sub-bullets. And
`APP_NAME = "corestack-lulc"` in `src/logging_setup.py` is what makes the path
`data/logs/corestack-lulc/`, which is the naming the checklist asks for.

## A2. `info`: requests, then a job lifecycle

**Window 3** (or just click around <http://localhost:8000/>):

```powershell
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/hierarchy/export?since=0" | Out-Null
```

Use `curl.exe`, never bare `curl`: in Windows PowerShell `curl` is an alias for `Invoke-WebRequest`
and takes different arguments.

Window 2 shows one line per request with a duration, and **no query strings**:

```
INFO  corestack.request | GET /api/hierarchy/export -> 200 (3 ms)
```

Now a job, which is the more interesting half of the `info` row:

```powershell
curl.exe -s -X POST "http://localhost:8000/api/jobs" -H "Content-Type: application/json" -d '{\"op\":\"export\",\"params\":{\"retrain\":{\"node\":\"greenery\"},\"export\":false}}' | Out-Null
```

```
INFO  corestack.backend | job lulc__c379a33b... created op=export
INFO  corestack.backend | export: classify + export to a GEE asset
INFO  corestack.backend | retrain node=greenery algo=linearsvc embedding=ae balance=balanced
ERROR corestack.backend | job lulc__c379a33b... failed: 'greenery' has no sub-classes to train
```

That is §5's `info` row on one screen: compute trigger, run id, job outcome. The failure is real and
fine to show. `greenery` has no children in the current hierarchy, so there is nothing to train, and
it demonstrates that a failure stays legible without switching levels.

## A3. Switch to `debug`, touching no code

**Window 1:** `Ctrl+C`, then:

```powershell
$env:LOG_LEVEL = "debug"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

Re-run both commands from A2. The same requests now carry their query strings:

```
DEBUG corestack.request | GET /api/hierarchy/export?since=0 -> 200 (3 ms)
```

And two things that exist only at `debug`:

```
DEBUG corestack.backend | paths root=... data=...\data models=...\models catalogue=...\data\catalogue
DEBUG corestack.backend | job lulc__eb44c652... params={'retrain': {'node': 'greenery'}, 'export': False}
```

The `paths` line is the one worth pointing at: on a cluster deploy it tells you exactly where that
process reads and writes, which is the first question when a deploy misbehaves.

Then the secrets check, at the most verbose level:

```powershell
curl.exe -s "http://localhost:8000/api/health?token=supersecret123&password=hunter2" | Out-Null
```

```
DEBUG corestack.request | GET /api/health?token=***&password=*** -> 200 (1 ms)
```

Worth one sentence of why: redaction is implemented in the **log formatter**, not at the call sites,
so it covers every line any module ever writes, including exception text and dict reprs. Nobody has
to remember the rule when adding a log line later.

## A4. `error`: failures only

**Window 1:** `Ctrl+C`, then:

```powershell
$env:LOG_LEVEL = "error"
.venv\Scripts\python.exe -m uvicorn backend:app --app-dir src --port 8000
```

```powershell
curl.exe -s "http://localhost:8000/api/health" | Out-Null
curl.exe -s "http://localhost:8000/api/tree" | Out-Null
```

Window 2 stays completely still. Two successful requests, zero lines. Then repeat the job command
from A2 and exactly one line appears:

```
ERROR corestack.backend | job lulc__... failed: 'greenery' has no sub-classes to train
```

## What Track A has shown

Claim 2 in full: three levels, each matching the published table, switched by one environment
variable with no code change. Plus the mandated path, and redaction at the level where a leak would
actually happen.

Claim 1 is **not** shown. The file did persist across three process restarts, which is worth
saying, but it is not the container-recreate claim. Track B closes it.

---

# Track B — container, for sign-off

The same demo under Docker, which is what the acceptance line is actually about. **Start Docker
Desktop first**, otherwise WSL shuts down between commands and takes the container with it.

One structural difference: the recreate that switches you to `debug` **is** the container recreate
that proves persistence. One action, two claims.

## B1. Show the mount, then start at `info`

```powershell
docker compose -f docker-compose.yml config | Select-String "logs"
```

Shows `./data/logs/corestack-lulc` mounted to the container's log path by name, which is §5's mount
sub-bullet.

```powershell
$env:LOG_LEVEL = "info"
docker compose -f docker-compose.yml up -d
```

Allow about a minute. Watch it from Window 2 exactly as in A0, or with:

```powershell
docker compose -f docker-compose.yml logs -f lulc
```

## B2. Same traffic as A2

Run A2's three commands unchanged. Same output.

## B3. Switch to `debug`, which also recreates the container

```powershell
$env:LOG_LEVEL = "debug"
docker compose -f docker-compose.yml up -d --force-recreate
```

Re-run A2's commands plus the secrets check from A3. Same output as Track A.

## B4. Prove persistence

The container from B1 no longer exists.

```powershell
Select-String -Path data\logs\corestack-lulc\app.log -Pattern "INFO  corestack.request" -Encoding UTF8 | Measure-Object | Select-Object -ExpandProperty Count
```

Non-zero. Those lines were written by a destroyed container, into a file on the **host**, under the
mandated path. That is claim 1; with B3 it is the whole acceptance criterion.

## B5. Tidy up

```powershell
docker compose -f docker-compose.yml down
```

---

## PowerShell equivalents

| Unix | PowerShell |
|---|---|
| `tail -f file` | `Get-Content file -Wait -Tail 20 -Encoding UTF8` |
| `tail -20 file` | `Get-Content file -Tail 20 -Encoding UTF8` |
| `grep X file` | `Select-String -Path file -Pattern X -Encoding UTF8` |
| `grep -c X file` | `(Select-String -Path file -Pattern X -Encoding UTF8).Count` |
| `curl url` | `curl.exe url` |
| `rm -rf dir` | `Remove-Item -Recurse -Force dir` |
