# Core Stack LULC: setting it up on the tower

For the tower admin. About 30 minutes once the pieces below are in hand. Each step ends with a quick
check, so if something is off it shows up right there.

**What it is.** A web app for land-use / land-cover maps over India. One Docker container serves both
the page and the API on port 8000. The heavy compute runs in Google Earth Engine, so it needs no GPU
and very little CPU or RAM on the tower.

**How it's packaged.** The Docker image `salil2003/corestack-lulc:1.0.0` holds only the
dependencies. The code comes from a git checkout that is mounted into the container. Updating later
means `git pull` and a restart, with no rebuild.

---

## What we send you (privately, not in git)

- `ee-key.json`, the Earth Engine service-account key
- the Google sign-in client id

## What we need back from you

- **The public URL** the app will sit at, e.g. `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/`.
  If the host isn't `https://www.cse.iitd.ernet.in`, tell us so we can allow it for Google sign-in.
- **A Postgres database** on the central server, plus its connection string.
- **The service token** you generate in step 2. Please pass it to Saharsh for the Airflow side.

---

## 1. Get the code

```bash
git clone https://github.com/salil-123/Project.git /srv/corestack-lulc
cd /srv/corestack-lulc
cp /path/to/ee-key.json deploy/ee-key.json
```

Check: `ls src/static/media/walkthrough.mp4 data/hierarchy.json models/` shows all three.

Please keep `data/` and `models/` inside this folder. They already hold the starting files the app
needs. If they have to live elsewhere, copy them over first; an empty folder won't work.

## 2. Fill in `.env`

```bash
cp deploy/.env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"    # run it twice
```

Set these in `.env`:

```bash
EE_PROJECT=modern-mystery-398416
EE_ASSET_ROOT=projects/modern-mystery-398416/assets/corestack_lulc
EE_SERVICE_ACCOUNT_KEY=/app/deploy/ee-key.json
STAC_ASSET_BASE=<public URL, no trailing slash>

GOOGLE_CLIENT_ID=<the id we sent>
SESSION_SECRET=<first random string>
SERVICE_TOKEN=<second random string>
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME

AIRFLOW_API_BASE=http://<airflow host>:8080/api/v1
AIRFLOW_USERNAME=<user>
AIRFLOW_PASSWORD=<password>
CORESTACK_API_BASE=http://<this machine's LAN address>:8000
```

Leave everything else as it is. In particular, leave `API_BASE_URL` and `INTRO_VIDEO_URL` empty.

Check: `grep -n '<' .env` prints nothing.

## 3. Start it

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

Check:

```bash
curl -s localhost:8000/api/health        # {"ok": true ...}
docker compose -f docker-compose.hub.yml exec lulc python -c "import config; print(config.DATABASE_URL.split(':')[0])"
# should print postgresql; sqlite means DATABASE_URL didn't load
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
**Sign in with Google** works.

## 5. Model zoo (one line)

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
| Back up | the Postgres database together with `data/projects/` (the rows point at those folders) |

If we ever change dependencies, we'll send a new image tag and the one-line compose change that goes with it.

Contact: Salil Gujar
