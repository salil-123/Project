# Core Stack LULC — DEPENDENCIES-ONLY image.
#
# The application CODE is intentionally NOT baked in. You bind-mount the repo at /app when you run, so
# updating the app is just `git pull` + restart the container — no image rebuild. Only rebuild this image
# when the *dependencies* change (requirements-docker.txt).
#
#   build:  docker build -t salil2003/corestack-lulc:latest .
#   run:    docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)":/app salil2003/corestack-lulc:latest
#   (or:    docker compose -f docker-compose.hub.yml up -d   — it does the mount for you)
FROM python:3.11-slim

# geospatial wheels bundle their own GDAL/GEOS/PROJ; we only need git (zoo publish) + libgomp1 (a numeric lib)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install only the serving dependencies. This is the only thing baked in; the code arrives via the mount.
COPY deploy/requirements-docker.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip uninstall -y nvidia-nccl-cu12 2>/dev/null || true \
    && find /usr/local/lib/python3.11 -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.11 -name '*.pyc' -delete

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# runs the code bind-mounted at /app (expects /app/src/backend.py). With nothing mounted it errors clearly.
CMD ["uvicorn", "backend:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
