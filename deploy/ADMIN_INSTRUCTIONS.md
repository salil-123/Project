# Core Stack LULC: updating the tower deployment

Repo: <https://github.com/salil-123/Project> (this file:
[`deploy/ADMIN_INSTRUCTIONS.md`](https://github.com/salil-123/Project/blob/main/deploy/ADMIN_INSTRUCTIONS.md))

For the existing deployment at `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/`. Your Earth Engine
key, `.env`, nginx, Airflow and the DAG all stay as they are; this adds one line to `.env` and two to
nginx. About 15 minutes, and every step ends with a check.

## What changes

- **Google sign-in.** It's built in and turns on by itself with this update. Visitors land on a
  front page with the walkthrough video, sign in, and work inside their own projects.
- **Airflow and the DAG don't change.** The DAG's calls back into the app keep working without a session.
- **New image `1.0.0`.** It carries the sign-in libraries. The old image can't run the new code, so
  this time you need a pull and a recreate, not a restart.
- **Data.** Users and projects go in a small SQLite file, `data/corestack.db`. Postgres is on hold.

---

## 1. Note where you are, and drop the local frontend edit

```bash
cd <the corestack-lulc folder>
git rev-parse --short HEAD          # write this down, it's the way back
cp .env .env.backup
git status --short
```

The frontend paths you made relative on the box are relative in the repo now too, so your edit isn't
needed. Discard it so the pull goes through cleanly:

```bash
git checkout -- src/static/
```

If `git status` still lists modified `data/*.json` files, that's the app's own saved state from the
old version. Clear it with `git stash`.

## 2. Pull the code

```bash
git pull
```

Check: `ls src/static/media/walkthrough.mp4 models/model_pooled.joblib` finds both.

## 3. One line in `.env`

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Add the output as:

```bash
SESSION_SECRET=<that string>
```

It signs the sign-in cookie. Leave everything else as it is, and don't add `GOOGLE_CLIENT_ID`: it's
built in, and an empty value switches sign-in off.

## 4. Pull the image and recreate

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

(Use `docker-compose` if that's what this box has been using.) `up -d` recreates the container, which
is how it picks up both the new image and the new `.env` line. A plain `restart` does neither.

Check, on the tower:

```bash
curl -s localhost:8000/api/health        # {"ok": true ...}
curl -s localhost:8000/api/auth/me       # google_client_id filled in, dev_login false
docker compose -f docker-compose.hub.yml exec lulc python config.py     # EE init OK
```

## 5. nginx

The existing block keeps working. Please check it has these two lines and add them if not:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;   # marks the sign-in cookie Secure under https
client_max_body_size 50m;                     # uploaded polygons and project zips; the default is 1 MB
```

Then `nginx -s reload`.

## 6. Check it end to end

1. Open the site and hard refresh once (Ctrl+Shift+R). The front page shows with the video playing.
2. **Sign in with Google**, create a small project and press **Run classification**. The run
   goes through Airflow as before and the map paints.

Logs are in `data/logs/corestack-lulc/app.log`.

---

## If something's off

| What you see | What it means | Fix |
|---|---|---|
| Container keeps restarting, `ModuleNotFoundError` in the logs | still on the old image | step 4: `pull`, then `up -d` |
| `git pull` refuses: local changes would be overwritten | a file edited on the box | step 1: `git checkout -- <that file>` or `git stash`, then pull |
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
