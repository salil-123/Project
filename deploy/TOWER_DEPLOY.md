# Deploying Core Stack LULC on the tower

The one runbook to follow, top to bottom. Every step ends with a check, so if a check fails you stop
there instead of finding out three steps later. The last section lists what went wrong on earlier
deploys and which step here keeps it from happening again.

The short version for the tower admin is `deploy/Deployment_guide.md`.
`deploy/DEPLOY_GUIDE.md` is still the long reference (every endpoint, Earth Engine options, STACD
YAMLs). This file is the order of operations.

---

## 0. What you need before starting

| Thing | From whom | Goes where |
|---|---|---|
| A shell on the tower with `docker`, `docker compose` and `git` | tower admin | |
| The sub-path the app will live under (planned: `/act4dws5/diy-lulc/`) | tower admin | nginx, `STAC_ASSET_BASE` |
| Postgres connection string (on hold: this deploy runs on SQLite, Postgres comes next time) | tower admin | `DATABASE_URL` |
| Earth Engine service-account key `ee-key.json` for `modern-mystery-398416` | us | `deploy/ee-key.json` on the tower |
| The Airflow REST URL and its creds | Saharsh | `AIRFLOW_*` |

Don't start without the key: the app boots without it but can't reach Earth Engine, so the setup
looks finished when it isn't.

---

## 1. Get the code

```bash
git clone https://github.com/salil-123/Project.git /srv/corestack-lulc
cd /srv/corestack-lulc
git log --oneline -1
```

**Check:** the commit matches the latest one on GitHub, and these files exist:

```bash
ls src/static/media/diy_lulc_acacia.mp4 data/hierarchy.json data/active_base.json models/model_pooled.joblib
```

The video, the starting class tree and the weights all come with the clone. Nothing is fetched separately.

## 2. Keep the three mounts on the checkout

`docker-compose.hub.yml` mounts `code/`, `models/` and `data/` separately (checklist #1). By default
all three point inside this checkout, and that's what we want on the tower too.

If the admin wants `data/` or `models/` somewhere else (`CORESTACK_DATA_HOST`, `CORESTACK_MODELS_HOST`),
**copy the folder there first**. An empty data dir has no `hierarchy.json` and no `active_base.json`,
so the app would start with nothing to classify with:

```bash
# only if data/models live outside the checkout
cp -a data/.   /srv/corestack-lulc-data/
cp -a models/. /srv/corestack-lulc-models/
```

## 3. Write `.env`

```bash
cp deploy/.env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # SESSION_SECRET (and SERVICE_TOKEN, once step 9 happens)
```

Fill in exactly these and leave the rest as they are:

```bash
EE_PROJECT=modern-mystery-398416
EE_ASSET_ROOT=projects/modern-mystery-398416/assets/corestack_lulc
EE_SERVICE_ACCOUNT_KEY=/app/deploy/ee-key.json   # the checkout is /app, so no extra mount needed
STAC_ASSET_BASE=https://<host>/act4dws5/diy-lulc # public URL, no trailing slash

SESSION_SECRET=<first random string>
# SERVICE_TOKEN=                                 # optional for now, see step 9
# DATABASE_URL=postgresql://USER:PASSWORD@POSTGRES_HOST:5432/DBNAME   # on hold; unset = data/corestack.db

AIRFLOW_API_BASE=http://<airflow-host>:8080/api/v1
AIRFLOW_USERNAME=<user>
AIRFLOW_PASSWORD=<password>
CORESTACK_API_BASE=http://<tower LAN host>:8000   # how Airflow reaches us; never localhost

LOG_LEVEL=info
API_BASE_URL=          # leave empty: relative paths are what make the sub-path work
INTRO_VIDEO_URL=       # leave empty: the bundled walkthrough plays. Set only for a YouTube link
docker_username=       # leave empty on the tower, build box only
docker_pat=
```

Then place the key:

```bash
cp /path/to/ee-key.json deploy/ee-key.json   # gitignored, never commit it
```

**Check:** `grep -n '<' .env` prints nothing (no placeholders left), and `git status` lists neither `.env` nor the key.

## 4. Pull the pinned image and start

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
docker compose -f docker-compose.hub.yml logs --tail 40 lulc
```

The compose file pins `salil2003/corestack-lulc:1.0.0`, the build that has the sign-in and Postgres
drivers and scikit-learn 1.8.0.

**Check** (on the tower):

```bash
curl -s localhost:8000/api/health                    # {"ok": true ...}
curl -s localhost:8000/api/auth/me                   # google_client_id is ours, dev_login false
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/projects \
  -H 'Content-Type: application/json' -d '{"name":"x","bbox":[77.17,28.53,77.19,28.55]}'   # 401
curl -s localhost:8000/config.js                     # introVideo: "media/diy_lulc_acacia.mp4"
```

Once Postgres is switched on (next deploy), make sure the app is actually using it:

```bash
docker compose -f docker-compose.hub.yml exec lulc python -c "import config; print(config.DATABASE_URL.split(':')[0])"
# postgresql   (sqlite here means DATABASE_URL didn't load)
```

## 5. Put it behind nginx at the sub-path

```nginx
location /act4dws5/diy-lulc/ {
    proxy_pass http://127.0.0.1:8000/;          # trailing slash strips the prefix
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme; # makes the session cookie Secure under https
    proxy_read_timeout 600s;                    # exports block while Earth Engine works
    client_max_body_size 50m;                   # polygon uploads and project zips; nginx default is 1 MB
}
```

Mind the trailing slashes. The app uses only relative paths, so it just needs the prefix stripped.

**Check** in a browser at `https://<host>/act4dws5/diy-lulc/`:
- the front page renders with styling (no blank page),
- the walkthrough plays and you can skip ahead,
- **Sign in with Google** works,
- `/app` shows a working map (Leaflet is vendored, no CDN).

If Google refuses the sign-in with an origin error, the origin `https://<host>` (scheme + host, no path)
is missing from the OAuth client's *Authorized JavaScript origins*. Add it in the Cloud console and try again.

## 6. The model zoo

A fresh checkout already gets all 11 model cards from `data/catalogue_seed/` on first start. To let
users **publish** to the zoo, clone the zoo repo into the data mount and set `ZOO_REMOTE`:

```bash
git clone https://github.com/salil-123/zoo_database.git data/catalogue
docker compose -f docker-compose.hub.yml restart lulc
```

**Check:** the Model Zoo panel lists 11 models, not 4.

## 7. One real run, end to end

Signed in, create a small project (well under 250 km²), press **Run classification**, then download
the GeoTIFF. Then from the tower:

```bash
curl -s -X POST localhost:8000/api/export-asset \
  -H 'Content-Type: application/json' -d '{"region":[77.16,28.53,77.20,28.57],"year":2024}'
```

**Check:** `"status": "success"` with an `asset_id` under `corestack_lulc/`, and a line for each call
in `data/logs/corestack-lulc/app.log`.

Name test assets clearly and delete them after. Last time 11 strays piled up.

## 8. STACD registration

In `deploy/stacd/corestack_lulc_algorithm_repo.yaml` set `url:` to the public export URL
(`https://<host>/act4dws5/diy-lulc/api/export-asset`), then upload the three YAMLs through the STACD
plugin (**Initialize Workflow**).

## 9. Airflow side

The live DAG stays as it is: with `SERVICE_TOKEN` unset, its callbacks (export-asset, jobs,
classify) are accepted without a session, which is exactly as open as before sign-in. Everything
else needs sign-in. The DAG has to pass the run conf through untouched, since the app puts
`project_id` in it.

To lock the callbacks down later (checklist #4 in full): set `SERVICE_TOKEN` here,
`CORESTACK_SERVICE_TOKEN=<same value>` on the Airflow worker, and swap in the repo's DAG file, which
sends it as `X-Service-Token`. All three on the same day, or Run gets 401s.

**Check:** press Run in the app with Airflow on, and the run shows up in Airflow and finishes green.

## 10. Hand-off

- Tick #4 and #11 in `docs/cluster_checklist.md`, with the date.
- Tell users to hard refresh once (Ctrl+Shift+R).
- Rotate the Docker Hub PAT if it ever sat in a working tree.

---

## Updating later

Code only (the usual case):

```bash
cd /srv/corestack-lulc
git pull
docker compose -f docker-compose.hub.yml restart lulc
curl -s localhost:8000/api/health
```

Dependencies changed (`deploy/requirements-docker.txt` touched). On the build box:

```bash
# bump VERSION first, then
deploy/build_and_push.sh          # pushes :latest AND :$(cat VERSION)
```

Then on the tower, change the tag in `docker-compose.hub.yml` to the new version, commit it, and
`git pull && docker compose -f docker-compose.hub.yml pull && docker compose -f docker-compose.hub.yml up -d`.
`restart` alone keeps the old image.

**Rollback:** `git checkout <previous commit>` plus the previous tag in the compose file, then `up -d`.
Users and projects live in Postgres and `data/projects/`, which a rollback doesn't touch.

---

## What went wrong before, and which step covers it

| What happened | Why | Covered by |
|---|---|---|
| Blank page on the tower | `index.html` and the API calls used root paths (`/app.js`, `/api/...`), which miss a sub-path | everything is relative now; leave `API_BASE_URL` empty (3), strip the prefix in nginx (5) |
| Dead map on campus | Leaflet loaded from unpkg, which the campus proxy can block | vendored under `src/static/vendor/`; check in 5 |
| Live zoo stuck at 4 models | a 553 MB file in the zoo repo made GitHub refuse every later push | publish refuses files over 50 MB; seed ships 11 cards; check in 6 |
| A pile of junk GEE assets | the DAG fired on almost every click, each run exporting an asset | only the Run button triggers it; test assets named and deleted (7) |
| Boot crash after moving weights | a stored `data/...joblib` path no longer existed | `model_path()` takes both spellings; keep the mounts on the checkout or copy first (2) |
| Models unpickled with the wrong scikit-learn | the image floated to a newer sklearn | pinned 1.8.0 in the 1.0.0 image (4) |
| No one could tell which build was live | only `:latest` was ever pushed | `VERSION` tag pushed, and compose pins it (4, Updating) |
| The DAG would be locked out by sign-in | callbacks have no browser cookie | callback paths stay open until `SERVICE_TOKEN` is set on both sides (9) |
| A DAG run ignored the user's classes | the pipeline didn't pass `project_id` | Airflow checklist (9) |
| Sessions clashing with other apps on the host | every app shares one cookie jar at `path=/` | cookie named `corestack_lulc_session` |
| Trusting an `X-User-Email` header, like the drone app | anyone can send that header | the Google token is verified on the server; check 401 in 4 |
| Users and projects silently in SQLite | `DATABASE_URL` unset falls back to a laptop file | the `postgresql` check in 4 |
| GeoTIFF download failed on big areas | Earth Engine ran out of memory at 368 km² | cap is 250 km²; don't raise `AOI_GEOTIFF_CAP_KM2` |
| EE key "not found" in the container | docs and compose disagreed on where the key is mounted | key sits in the checkout at `/app/deploy/ee-key.json`, no extra mount (3) |
| Docs said `psycopg2-binary` | the image actually ships psycopg 3; `db.py` rewrites the URL for it | use the plain `postgresql://` string (3) |
| Docker PAT sitting in the working tree | `.env` doubles as the build config | `docker_*` left empty on the tower, rotate the PAT (3, 10) |
| Stale page after an update | browser cache | `?v=` bumped on every change; hard refresh once (10) |
| Container restarting every ~20 s on the build box | WSL shut down with Docker Desktop off | build box only: keep Docker Desktop or the WSL distro running while you test |
| `wsl` paths mangled to `C:/Git/mnt/...` | Git Bash rewrites `/mnt/c/...` arguments | build box only: prefix with `MSYS_NO_PATHCONV=1` |
