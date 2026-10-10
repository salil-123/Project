# Do It Yourself LULC: updating the ws5 deployment

Repo: <https://github.com/salil-123/Project> (this file:
[`deploy/Deployment_guide.md`](https://github.com/salil-123/Project/blob/main/deploy/Deployment_guide.md))

For the existing deployment at `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/`. Your Earth Engine
key, `.env` and the DAG stay as they are. Every step is safe to repeat, so it works whether or not the
previous update went in. About 20 minutes, and every step ends with a check.

## What this update brings

- **The new name, Do It Yourself LULC**, on every page and in the STAC titles, and the CoRE stack
  description on the front page.
- **Two demo public projects**: Sanjay Van acacia / non-acacia and the Jharia coalfield mining split.
  Each is added once on start; one that's already there (Jharia on this box) isn't added twice, and
  deleting one in the app keeps it deleted.
- **File Browser with no login.** A second container shows every project's folder (runs, schemes,
  GeoTIFFs) read-only, at `/act4dws5/diy-lulc/files/`, and each project links to its own folder.
- **Airflow off the public site, with a new admin password.** It stays reachable from inside the
  IITD network.
- No image change: the code is mounted, so `git pull` plus `up -d` is the whole update.

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
`ls src/static/media/diy_lulc_acacia.mp4` finds the video.

## 3. `.env`

Add this line, so each project links to its files:

```bash
FILEBROWSER_URL=files
```

If there's no `SESSION_SECRET` line yet (it came with the last update), make one:

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
picks up the image and any `.env` change. A plain `restart` picks up neither. It also starts the new
`files` container (File Browser) on port 8081.

Check, on the tower:

```bash
curl -s localhost:8000/api/health                  # "status": "ok"
curl -s localhost:8000/api/auth/me                 # google_client_id filled in, dev_login false
curl -s 'localhost:8000/api/health?deep=1'         # every host under "reach" says ok
curl -s -o /dev/null -w '%{http_code}
' localhost:8081/act4dws5/diy-lulc/files/health   # 200
docker compose -f docker-compose.hub.yml exec lulc python config.py    # EE init OK
```

**If any host under `reach` says `unreachable`**, the container can't get out to Google. That's what
freezes sign-in and stops the maps. The message says which of two things it is.

*`DNS lookup failed`*: the container can't turn names into addresses. Compare the host with the container:

```bash
getent hosts www.googleapis.com                                              # on the host
docker compose -f docker-compose.hub.yml exec lulc getent hosts www.googleapis.com   # in the container
cat /etc/resolv.conf                                                          # the host's DNS servers
```

If the host resolves and the container doesn't, Docker is handing the container a DNS server the campus
network blocks (it falls back to 8.8.8.8 when the host uses a local resolver). Give Docker the host's
real DNS servers in `/etc/docker/daemon.json`, then restart Docker and recreate:

```json
{ "dns": ["<campus DNS 1>", "<campus DNS 2>"] }
```

```bash
sudo systemctl restart docker
docker compose -f docker-compose.hub.yml up -d
```

*`lookup ok, no connection`*: names resolve but traffic has to go through the campus proxy. Add it to
`.env` and recreate:

```bash
HTTPS_PROXY=http://<proxy host>:<port>
HTTP_PROXY=http://<proxy host>:<port>
NO_PROXY=localhost,127.0.0.1,<airflow host>    # Airflow and local calls skip the proxy
```

```bash
docker compose -f docker-compose.hub.yml up -d
```

Either way, finish with `curl -s 'localhost:8000/api/health?deep=1'`: every host should now say `ok`.

## 5. nginx: File Browser

The existing block keeps working. Check it has these two lines, and add them if not:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;   # marks the sign-in cookie Secure under https
client_max_body_size 50m;                     # uploaded polygons and project zips; the default is 1 MB
```

Then add File Browser next to it. The path has to stay exactly this, since File Browser is set up for it:

```nginx
location /act4dws5/diy-lulc/files/ {
    proxy_pass http://127.0.0.1:8081;          # no trailing slash: File Browser wants the full path
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

`nginx -t && nginx -s reload`.

Check: `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/files/` opens a file list with no login. It is
read-only for everyone: no upload, rename or delete.

## 6. Airflow: new password, off the public site

Today `https://www.cse.iitd.ernet.in/act4dws5/airflow/` opens the Airflow login from anywhere. Two
changes: a new admin password, and no public path at all.

**a. Where do the apps reach Airflow?** Both this app and the drone app call Airflow's API. Check that
they use the box's own address, not the public URL:

```bash
grep AIRFLOW_API_BASE .env     # e.g. http://<ws5 address>:8080/api/v1 is fine; .../act4dws5/airflow/... is not
```

If it's the public URL, change it to `http://<ws5 address>:8080/api/v1` first (the drone app's `.env`
too), then `up -d`. Otherwise the next steps cut the apps off from Airflow.

**b. New admin password**, inside the Airflow webserver container:

```bash
airflow users reset-password -u admin -p '<new password>'
```

(On an Airflow without `reset-password`: `airflow users delete -u admin`, then
`airflow users create -u admin -p '<new password>' -r Admin -f Admin -l User -e <email>`.)
Then put the same password in `.env` as `AIRFLOW_PASSWORD=<new password>`, and in the drone app's,
and `up -d` both.

**c. Take it off the public site.** Delete (or comment out) the `location /act4dws5/airflow/` block
in nginx and `nginx -t && nginx -s reload`. Don't use an `allow 10.0.0.0/8; deny all;` list for this:
visitors come through the CSE front proxy, which has a campus address itself, so that list would let
everyone in. With the block gone, Airflow is still at `http://<ws5 address>:8080/` for anyone on the
IITD network, and nowhere else.

Check: from a phone on mobile data, `https://www.cse.iitd.ernet.in/act4dws5/airflow/` is a 404. From a
campus machine, `http://<ws5 address>:8080/` asks for the login and takes the new password.

## 7. Check it end to end

1. Open the site and hard refresh once (Ctrl+Shift+R). The header says **Do It Yourself LULC**, the
   CoRE stack description is at the bottom, and Public projects has **Sanjay Van acacia (sample)** and
   **Jharia coalfield (sample)**; each opens with its two runs.
2. **Sign in with Google.** You land on "What are you working on?" within a couple of seconds.
3. Create a small project (the IIT Delhi preset is quick) and press **Run classification**. The run
   goes through Airflow as before (with the new password) and the map paints with a legend.
4. Under the runs, **Browse this project's files** opens its folder in File Browser.

Logs are in `data/logs/corestack-lulc/app.log`.

---

## If something's off

| What you see | What it means | Fix |
|---|---|---|
| Sign-in says "the server can't reach www.googleapis.com", or the map never paints | the container can't reach Google | step 4: the deep check says whether it's DNS or the proxy, and the fix for each |
| Container keeps restarting, `ModuleNotFoundError` in the logs | still on the old image | step 4: `pull`, then `up -d` |
| Container keeps restarting, `disk I/O error` in the logs | `data/` is on a network share; the database needs a local disk | keep `data/` on the tower's own disk |
| `git pull` refuses: local changes would be overwritten | a file edited on the box | step 1: `git checkout -- <that file>` or `git stash`, then pull |
| Run stays `queued` forever | the DAG is paused, or the scheduler is down | `airflow dags unpause corestack_lulc` |
| Run fails with 401 from Airflow | `.env` still has the old Airflow password | step 6b, then `up -d` |
| Run can't reach Airflow at all | `AIRFLOW_API_BASE` was the public URL that's now gone | step 6a |
| `files/` page is blank or 404 | nginx path differs from `/act4dws5/diy-lulc/files/` | step 5, exactly that path |
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
