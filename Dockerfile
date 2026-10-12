# Core Stack LULC — DEPENDENCIES-ONLY image.
#
# The application CODE is intentionally NOT baked in. You bind-mount the repo at /app when you run, so
# updating the app is just `git pull` + restart the container — no image rebuild. Only rebuild this image
# when the *dependencies* change (requirements-docker.txt).
#
#   build:  docker build -t salil2003/corestack-lulc:latest .
#   run:    docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)":/app salil2003/corestack-lulc:latest
#   (or:    docker compose -f docker-compose.hub.yml up -d   — it does the mount for you)
# 3.12: geotessera 0.8 needs it
FROM python:3.12-slim

# geospatial wheels bundle their own GDAL/GEOS/PROJ; we only need git (zoo publish) + libgomp1 (a numeric lib)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install only the serving dependencies. This is the only thing baked in; the code arrives via the mount.
COPY deploy/requirements-docker.txt /tmp/requirements.txt
# only the GPU lib's removal may fail quietly; a failed install has to stop the build (a bare "|| true"
# here once let an image with nothing in it build "successfully")
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && (pip uninstall -y nvidia-nccl-cu12 2>/dev/null || true) \
    && find /usr/local/lib/python3.12 -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.12 -name '*.pyc' -delete \
    && python -c "import fastapi, geopandas, ee, sklearn, geotessera"

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# runs the code bind-mounted at /app (expects /app/src/backend.py). With nothing mounted it errors clearly.
CMD ["uvicorn", "backend:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
