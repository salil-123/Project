# Core Stack LULC — web app image.
#
#   build:  docker build -t salil2003/corestack-lulc:latest .
#   run:    docker run --rm -p 8000:8000 --env-file .env salil2003/corestack-lulc:latest
#   then:   http://127.0.0.1:8000/
#
# Only the serving app + its small runtime data land in the image; the heavy CSV caches,
# biomass artifacts, zoo artifacts and secrets are kept out by .dockerignore. Paths are
# anchored to the project root (config.project_path), so uvicorn runs fine from /app.
FROM python:3.11-slim

# The geospatial wheels (rasterio/pyproj/shapely/geopandas/pyogrio) bundle their own
# GDAL/GEOS/PROJ, so at OS level we only need git (zoo_git shells out to it on publish)
# and libgomp1 (xgboost's OpenMP runtime).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# deps first so this layer caches across code edits
COPY deploy/requirements-docker.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# the app + its runtime data (heavy/secret files excluded via .dockerignore)
COPY config.py README.md ./
COPY src/ ./src/
COPY schema/ ./schema/
COPY data/ ./data/

# the app writes hierarchy/op_log/examples/merge_rules at runtime — mount a volume here
# to persist that state across container restarts (see docker-compose.yml).
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# backend adds the repo root to sys.path itself; bind all interfaces so the port maps out.
CMD ["uvicorn", "backend:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
