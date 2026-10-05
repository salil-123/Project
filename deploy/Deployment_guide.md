# Core Stack LULC: updating the tower deployment

Repo: <https://github.com/salil-123/Project> (this file:
[`deploy/Deployment_guide.md`](https://github.com/salil-123/Project/blob/main/deploy/Deployment_guide.md))

For the existing deployment at `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/`. Your Earth Engine
key, `.env`, nginx, Airflow and the DAG all stay as they are. Every step is safe to repeat, so it works
whether or not the previous update went in. About 15 minutes, and every step ends with a check.

## What this update brings

- **Google sign-in that doesn't freeze.** If the server can't reach Google, sign-in now says so within
  10 seconds instead of hanging.
- **A network check**, `/api/health?deep=1`, that says whether the container can reach Google.
  Sign-in and Earth Engine both need it.
- **The off-white colours** of the drone app.
- **A fix** so one person's run no longer freezes the site for everyone else.
- **Airflow and the DAG don't change.** Users and projects stay in `data/corestack.db`; Postgres is on hold.

---

## 1. Note where you are

```bash
cd <the corestack-lulc folder>
git rev-parse --short HEAD          # write this down, it's the way back
cp .env .env.backup
git status --short
```

If `git status` lists files under `src/static/`, that's the earlier relative-path edit. The repo does
the same now, so discard it: `git checkout -- src/static/`. Modified `data/*.json` files are the app's
own saved state; clear them with `git stash`.

## 2. Pull the code

```bash
git pull
```

Check: `git log --oneline -1` matches the latest commit on GitHub, and
`ls src/static/media/walkthrough.mp4` finds the video.

## 3. `.env`

If `.env` already has a `SESSION_SECRET` line from the last update, skip this step. Otherwise:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

and add the output as `SESSION_SECRET=<that string>`. It signs the sign-in cookie.

Don't add `GOOGLE_CLIENT_ID`: it's built in, and an empty value switches sign-in off.

## 4. Pull the image and recreate

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

(Use `docker-compose` if that's what this box has been using.) `up -d` recreates the container, which
picks up the image and any `.env` change. A plain `restart` picks up neither.

Check, on the tower:

```bash
curl -s localhost:8000/api/health                  # "status": "ok"
curl -s localhost:8000/api/auth/me                 # google_client_id filled in, dev_login false
curl -s 'localhost:8000/api/health?deep=1'         # every host under "reach" says ok
docker compose -f docker-compose.hub.yml exec lulc python config.py    # EE init OK
```

**If any host under `reach` says `unreachable`**, the container can't get out to Google. That's what
freezes sign-in and stops the maps. The box most likely goes out through the campus proxy, so add it
to `.env` and recreate:

```bash
HTTPS_PROXY=http://<proxy host>:<port>
HTTP_PROXY=http://<proxy host>:<port>
NO_PROXY=localhost,127.0.0.1,<airflow host>    # Airflow and local calls skip the proxy
```

```bash
docker compose -f docker-compose.hub.yml up -d
curl -s 'localhost:8000/api/health?deep=1'         # now all ok
```

## 5. nginx

The existing block keeps working. Check it has these two lines, and add them if not:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;   # marks the sign-in cookie Secure under https
client_max_body_size 50m;                     # uploaded polygons and project zips; the default is 1 MB
```

Then `nginx -s reload`.

## 6. Check it end to end

1. Open the site and hard refresh once (Ctrl+Shift+R). The front page is off-white with the video.
2. **Sign in with Google.** You land on "What are you working on?" within a couple of seconds.
3. Create a small project (the IIT Delhi preset is quick) and press **Run classification**. The run
   goes through Airflow as before and the map paints with a legend.

Logs are in `data/logs/corestack-lulc/app.log`.

---

## If something's off

| What you see | What it means | Fix |
|---|---|---|
| Sign-in says "the server can't reach www.googleapis.com", or the map never paints | the container can't reach Google | step 4: the proxy lines in `.env`, then `up -d` |
| Container keeps restarting, `ModuleNotFoundError` in the logs | still on the old image | step 4: `pull`, then `up -d` |
| Container keeps restarting, `disk I/O error` in the logs | `data/` is on a network share; the database needs a local disk | keep `data/` on the tower's own disk |
| `git pull` refuses: local changes would be overwritten | a file edited on the box | step 1: `git checkout -- <that file>` or `git stash`, then pull |
| Run stays `queued` forever | the DAG is paused, or the scheduler is down | `airflow dags unpause corestack_lulc` |
| Google says the origin isn't allowed | the site moved to another host | send me the URL and I'll add it on our side |
| `.env` edits have no effect | the container wasn't recreated | `up -d`, not `restart` |
| Page looks like the old version | browser cache | Ctrl+Shift+R |

Logs for any of these: `docker compose -f docker-compose.hub.yml logs --tail 50 lulc`

## Going back

```bash
git checkout <the commit from step 1>
cp .env.backup .env
docker compose -f docker-compose.hub.yml up -d
```

The `1.0.0` image runs the older code too, so the image doesn't need to change for a rollback.
