# Core Stack LULC: setting it up on the tower

For the tower admin. About 20 minutes. Each step ends with a quick check, so if something is off it
shows up right there.

**What it is.** A web app for land-use / land-cover maps over India. One Docker container serves both
the page and the API on port 8000. The heavy compute runs in Google Earth Engine, so it needs no GPU
and very little CPU or RAM on the tower.

**How it's packaged.** The Docker image `salil2003/corestack-lulc:1.0.0` holds only the
dependencies. The code comes from a git checkout that is mounted into the container. Updating later
means `git pull` and a restart, with no rebuild.

---

## 1. Get the code

Already have a checkout from the earlier deploy:

```bash
cd /srv/corestack-lulc        # wherever it lives
git pull
```

If `git pull` complains about local changes in `data/*.json`, that's the app's own saved state from
the old version. Run `git stash`, then `git pull` again.

Fresh machine:

```bash
git clone https://github.com/salil-123/Project.git /srv/corestack-lulc
cd /srv/corestack-lulc
```

Check: `ls src/static/media/walkthrough.mp4 data/hierarchy.json models/` shows all three.

Please keep `data/` and `models/` inside this folder. They already hold the starting files the app
needs. If they have to live elsewhere, copy them over first; an empty folder won't work.

## 2. `.env`

Keep the Earth Engine settings you already have (`EE_PROJECT`, `EE_ASSET_ROOT`,
`EE_SERVICE_ACCOUNT_KEY` pointing at the key) and the Airflow ones. Sign-in is new, so add these
(the Google client id is already built in):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"    # run it twice
```

```bash
SESSION_SECRET=<first random string>
SERVICE_TOKEN=<second random string>      # Saharsh sets the same value on the Airflow side
STAC_ASSET_BASE=<public URL, no trailing slash>
```

Leave `GOOGLE_CLIENT_ID`, `DATABASE_URL`, `API_BASE_URL` and `INTRO_VIDEO_URL` out. For now users and projects sit in
a small SQLite file at `data/corestack.db`; moving to the central Postgres is planned for the next deploy.

Check: `grep -n '<' .env` prints nothing.

## 3. Start it

The new code needs the 1.0.0 image (it carries the sign-in libraries), so pull it. A plain restart
would keep the old image.

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

Check:

```bash
curl -s localhost:8000/api/health        # {"ok": true ...}
curl -s localhost:8000/api/auth/me       # google_client_id is set, dev_login is false
```

## 4. nginx

```nginx
location /act4dws5/diy-lulc/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    client_max_body_size 50m;
}
```

Both trailing slashes matter: they strip the prefix, and the app uses relative paths for the rest.
The timeout covers map exports, and the body size covers uploaded polygons and project files.

Check: the public URL opens a styled front page, the walkthrough video plays, and
**Sign in with Google** works. If Google says the origin isn't allowed, send me the URL and I'll
add it on our side.

## 5. Model zoo (one line)

Skip this if `data/catalogue` already exists from before.

```bash
git clone https://github.com/salil-123/zoo_database.git data/catalogue
docker compose -f docker-compose.hub.yml restart lulc
```

Check: the Model Zoo in the app lists 11 models.

---

## Day to day

| Task | Command |
|---|---|
| Update to new code | `git pull && docker compose -f docker-compose.hub.yml restart lulc` |
| Logs | `tail -f data/logs/corestack-lulc/app.log` |
| More detail in logs | `LOG_LEVEL=debug` in `.env`, then restart |
| Stop | `docker compose -f docker-compose.hub.yml down` |
| Back up | `data/corestack.db` together with `data/projects/` (the rows point at those folders) |

If we ever change dependencies, we'll send a new image tag and the one-line compose change that goes with it.

Contact: Salil Gujar
