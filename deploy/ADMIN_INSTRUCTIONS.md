# Core Stack LULC: updating the tower deployment

For the existing deployment at `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/`. Your Earth Engine
key, `.env`, nginx and Airflow setup all stay as they are. This update adds a few lines on top.
About 20 minutes, and every step ends with a check.

## What changes

- **Google sign-in.** It's built in and turns on by itself with this update. Visitors land on a
  front page with the walkthrough video, sign in, and work inside their own projects.
- **A service token.** With sign-in on, anything without a session gets 401, and that includes
  Airflow's calls back into the app. A shared token lets those through, so it goes in two places:
  our `.env` and the Airflow side (step 4). Without it, Run in the app breaks.
- **New image `1.0.0`.** It carries the sign-in libraries. The old image can't run the new code, so
  this time you need a pull and a recreate, not a restart.
- **Model zoo** shows all 11 models now, without any setup.
- **Data.** Users and projects go in a small SQLite file, `data/corestack.db`. The central Postgres
  comes in the next round.

---

## 1. Note where you are, in case you need to go back

```bash
cd <the corestack-lulc folder>
git rev-parse --short HEAD          # write this down
git status --short
cp .env .env.backup
```

If `git status` lists files you changed in `src/` or `config.py`, please send me the diff
(`git diff > tower_changes.diff`) so the fix goes into the repo. Then set them aside:

```bash
git stash
```

`data/*.json` showing as modified is just the app's saved state, and stashing it is fine.

## 2. Pull the code

```bash
git pull
```

Check: `ls src/static/media/walkthrough.mp4 models/model_pooled.joblib` finds both.

## 3. Add to `.env`

Generate two random strings:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"    # run it twice
```

and add:

```bash
SESSION_SECRET=<first string>
SERVICE_TOKEN=<second string>
```

Leave everything else as it is. Don't add `GOOGLE_CLIENT_ID` (it's built in, and an empty value
switches sign-in off) or `DATABASE_URL` (that's for the Postgres round).

## 4. Airflow: the same token on its side

Whichever DAG calls `/api/export-asset` has to send the header `X-Service-Token: <SERVICE_TOKEN>`.

If it's our `corestack_lulc` DAG, two things:

1. Copy the new `airflow/dags/corestack_lulc_dag.py` from the repo into Airflow's dags folder,
   replacing the old copy. The old one doesn't send the header.
2. Set `CORESTACK_SERVICE_TOKEN=<the same second string>` in the environment of the Airflow
   scheduler and workers, then restart them so they pick it up.

The app now puts `project_id` in the run conf, and the DAG has to pass the conf through as it is
(ours does). If a DAG drops it, runs fall back to the shared default scheme instead of the user's project.

## 5. Pull the image and recreate

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

(Use `docker-compose` if that's what this box has been using.) `up -d` recreates the container, which
is how it picks up both the new image and the new `.env` lines. A plain `restart` does neither.

Check, on the tower:

```bash
curl -s localhost:8000/api/health        # {"ok": true ...}
curl -s localhost:8000/api/auth/me       # google_client_id filled in, dev_login false
docker compose -f docker-compose.hub.yml exec lulc python config.py     # EE init OK
```

## 6. nginx

The existing block keeps working. Please check it has these two lines and add them if not:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;   # marks the sign-in cookie Secure under https
client_max_body_size 50m;                     # uploaded polygons and project zips; the default is 1 MB
```

Then `nginx -s reload`.

## 7. Check it end to end

1. Open the site and hard refresh once (Ctrl+Shift+R). The front page shows with the video playing.
2. **Sign in with Google**, create a small project and press **Run classification**. The run
   goes through Airflow and the map paints.
3. Open the Model Zoo. It lists 11 models.

Logs are in `data/logs/corestack-lulc/app.log`.

---

## If something's off

| What you see | What it means | Fix |
|---|---|---|
| Container keeps restarting, `ModuleNotFoundError` in the logs | still on the old image | step 5: `pull`, then `up -d` |
| `git pull` refuses: local changes would be overwritten | files edited on the box | step 1: `git stash`, then pull |
| Run hangs or the DAG task fails, `401` in our log | Airflow isn't sending the token, or the values differ | step 4: same value on both sides, new DAG file, Airflow restarted |
| Run stays `queued` forever | the DAG is paused, or the scheduler is down | `airflow dags unpause corestack_lulc` |
| Google says the origin isn't allowed | the site moved to another host | send me the URL; I add it on our side |
| `.env` edits have no effect | the container wasn't recreated | `up -d`, not `restart` |
| Page looks like the old version | browser cache | Ctrl+Shift+R |

## Going back

```bash
git checkout <the commit from step 1>
cp .env.backup .env
docker compose -f docker-compose.hub.yml up -d
```

The `1.0.0` image runs the old code too, so the image doesn't need to change for a rollback.
Remove `CORESTACK_SERVICE_TOKEN` on the Airflow side only if you also put the old DAG file back.

## Later updates

Code only: `git pull`, then `docker compose -f docker-compose.hub.yml restart lulc`.
If `.env` or the image tag changed: `pull`, then `up -d`. We'll say which one each time.

Contact: Salil Gujar
