# The tower, simulated on one laptop

Before an update goes to the tower, run it here first. It's the same image the tower runs
(`salil2003/corestack-lulc:1.0.0`) with this checkout mounted, nginx in front at the same sub-path, and
Airflow driving a DAG that calls the app the way the tower's STACD DAG does. No domain or paid service
is needed.

| Piece | Here | On the tower |
|---|---|---|
| App | image `1.0.0`, code mounted, `.env` from the repo root | the same |
| Front proxy | nginx at `/act4dws5/diy-lulc/`, 60 s timeout | nginx behind the CSE proxy |
| Airflow | Airflow 2.10 with `dags/corestack_lulc_stacd.py`, which forwards the run conf to `/api/export-asset` | the STACD DAG, same call |
| Earth Engine | your own login (`~/.config/earthengine`), exports go to `corestack_lulc_sim` | Kapil sir's key |
| Network | normal, or `--tower-net`: the container's DNS never answers, as found on 6 Oct | the campus network |

## Use

From WSL (Docker runs there on this laptop):

```bash
deploy/sim/sim.sh up --local-login      # app + nginx + Airflow; the type-a-name login for the tests
deploy/sim/sim.sh test                  # journey (two users, upload, train, zoo, public, downloads,
                                        # import), visitor view, and a Run through Airflow
deploy/sim/sim.sh up --tower-net        # same, with the tower's broken DNS
deploy/sim/sim.sh towernet              # sign-in and the deep check must fail fast and name DNS
deploy/sim/sim.sh status                # what runs, RAM per container, the deep check
deploy/sim/sim.sh down
```

`up` always recreates the containers, so code and `.env` changes are picked up.

The real Run button, pressed in a browser through nginx (from Windows, with Playwright):

```bash
python deploy/sim/run_button_test.py
```

A note on timing: Airflow's export of a run to a GEE asset waits in Earth Engine's queue, 10 to 20
minutes even for a small box. The Run button doesn't wait for it: the run is saved and drawn in seconds,
and the page only speaks up if the export later fails. `sim.sh test` waits for the export to finish,
so it takes a while.

Then open:

- the app through nginx: <http://localhost:8080/act4dws5/diy-lulc/>
- the app directly: <http://localhost:8000/>
- Airflow: <http://localhost:8081/> (admin / admin)

**Real Google sign-in** works once `http://localhost:8080` is in the OAuth client's *Authorized
JavaScript origins* (Google Cloud console, project `modern-mystery-398416`). Start without
`--local-login` for that. `http://localhost:8000` is already allowed.

## Don't

- Run the app from Windows (`uvicorn` on the laptop) while the sim is up. Both would open
  `data/corestack.db`, and SQLite can't share it between Windows and Linux ("disk I/O error").
- Expect it to catch the campus specifics: the real proxy address, the CSE front proxy, Kapil sir's
  `.env`. `/api/health?deep=1` on the tower reads those.

## What it costs

Running: about 1.75 GB of RAM (Airflow 1.5 GB, the app 250 MB, nginx 4 MB). Disk: the Airflow image
(2.1 GB) on top of the app image (1.3 GB) that's there anyway. `down` frees the RAM; the images stay
until `docker image rm apache/airflow:2.10.5-python3.11`.
