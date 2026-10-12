# Do It Yourself LULC: updating the ws5 deployment

Repo: <https://github.com/salil-123/Project> (this file:
[`deploy/Deployment_guide.md`](https://github.com/salil-123/Project/blob/main/deploy/Deployment_guide.md))

For the deployment at `https://www.cse.iitd.ernet.in/act4dws5/diy-lulc/`. The Earth Engine key, `.env`
and the DAG stay as they are. Every step is safe to repeat and ends with a check. About 20 minutes.

## What changes

- **New image `1.0.1`** (adds Tessera embeddings), so this update needs an image `pull`, not just
  `git pull`. Tessera tiles download on first use into `data/tessera/` (~150 MB each) and stay there.
- **New name**, Do It Yourself LULC, and the CoRE stack description on the front page.
- **Two demo public projects**, Sanjay Van acacia and Jharia mining. On the first start they replace
  the existing public projects of the same names, so their links change. This happens once.
- **Visitors only read**: signed out, the model zoo shows no publish, annotate, delete or use buttons.
- **Model zoo cleaned up**: one water model instead of three; the farm / plantation / scrubland model
  is out until it runs within Earth Engine's time limit. Every remaining model was tested.
- **Training runs in the background**, so long trainings no longer end in a 504.

## 1. Note where you are

```bash
cd <the corestack-lulc folder>
git rev-parse --short HEAD          # the way back
cp .env .env.backup
git status --short
```

Files listed under `src/static/` are the earlier relative-path edit; the repo does the same now, so
`git checkout -- src/static/`. Modified `data/*.json` files are the app's own state: `git stash`.

## 2. Pull the code

```bash
git pull
```

Check: `git log --oneline -1` matches the latest commit on GitHub, and `cat VERSION` says `1.0.1`.

## 3. `.env`

If there's no `SESSION_SECRET` line yet, add one:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"    # SESSION_SECRET=<this>
```

Leave `GOOGLE_CLIENT_ID` out; it's built in.

## 4. Pull the image and recreate

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

`up -d` picks up the new image and any `.env` change; `restart` picks up neither.

If the box starts the app with gunicorn instead of the image's default, the command needs
`-k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 1500`. Without `-b` it only listens inside the
container (nginx gives 502), and a shorter timeout kills long exports.

Check:

```bash
curl -s localhost:8000/api/health                                       # "status": "ok"
curl -s 'localhost:8000/api/health?deep=1'                              # every host under "reach" says ok
curl -s localhost:8000/api/tessera-sites | grep -o '"available":[a-z]*' # "available":true
docker compose -f docker-compose.hub.yml exec lulc python config.py    # EE init OK
```

`dl2.geotessera.org` unreachable only stops Tessera training; everything else works. For the Google
hosts it stops sign-in and maps. The message says which fix applies:

- **`DNS lookup failed`**: Docker gives the container a DNS server the campus network blocks. Put the
  host's DNS servers (from `/etc/resolv.conf`) in `/etc/docker/daemon.json` as
  `{ "dns": ["<dns 1>", "<dns 2>"] }`, then `sudo systemctl restart docker` and `up -d`.
- **`lookup ok, no connection`**: traffic has to go through the campus proxy. Add to `.env`, then `up -d`:

  ```bash
  HTTPS_PROXY=http://<proxy host>:<port>
  HTTP_PROXY=http://<proxy host>:<port>
  NO_PROXY=localhost,127.0.0.1,<airflow host>
  ```

## 5. nginx

The existing block keeps working. Make sure it has these two lines; if you add either,
`nginx -t && nginx -s reload`.

```nginx
proxy_set_header X-Forwarded-Proto $scheme;   # sign-in cookie marked Secure under https
client_max_body_size 50m;                     # polygon uploads and project zips
```

## 6. Airflow

Nothing to change on Airflow for this update. If its admin password changes, put the new one in `.env`
as `AIRFLOW_PASSWORD=` and `up -d`. `AIRFLOW_API_BASE` should be the box's own address
(`http://<ws5 address>:8080/api/v1`), so the app keeps working if the public Airflow path goes away.

## 7. Check it end to end

1. Open the site, Ctrl+Shift+R. The header says **Do It Yourself LULC**. Public projects lists
   **Sanjay Van acacia (sample)** and **Jharia coalfield (sample)** once each; Jharia has one run and
   **By operations** shows every step. Signed out, the model zoo has no Publish or Use buttons.
2. **Sign in with Google**: "What are you working on?" within a couple of seconds.
3. New project on the IIT Delhi preset, **Run classification**: the map paints with a legend.
4. In that project, split Greenery with the zoo's acacia model and **Run** again: acacia shows up.

Logs: `data/logs/corestack-lulc/app.log`, or `docker compose -f docker-compose.hub.yml logs --tail 50 lulc`.

## If something's off

| What you see | Fix |
|---|---|
| Sign-in can't reach Google, or the map never paints | step 4 deep check |
| `ModuleNotFoundError` in the logs, container restarting | still on the old image: step 4 `pull`, `up -d` |
| `disk I/O error` in the logs | keep `data/` on the tower's own disk, not a network share |
| `git pull` refuses: local changes | step 1, then pull |
| Run stays queued | `airflow dags unpause corestack_lulc` |
| Run fails with 401 from Airflow | step 6: `.env` has an old Airflow password |
| Run can't reach Airflow | step 6: `AIRFLOW_API_BASE` should be the box's own address |
| 502 from nginx | gunicorn without `-b 0.0.0.0:8000` (step 4) |
| Tessera option missing for a prepared site | image still `1.0.0`: step 4 |
| `.env` edits have no effect | `up -d`, not `restart` |
| Page looks old | Ctrl+Shift+R |

## Going back

```bash
git checkout <the commit from step 1>
cp .env.backup .env
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

The old commit pins the old image, so `pull` brings it back. `data/tessera/` can be deleted afterwards.
