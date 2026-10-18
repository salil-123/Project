#!/usr/bin/env bash
# Build the LULC image and push it to Docker Hub, using the creds in ../.env.
# Run from anywhere:  bash deploy/build_and_push.sh
set -euo pipefail
cd "$(dirname "$0")/.."           # repo root (build context)

# pull docker_username / docker_pat from .env without echoing them. A .env saved on Windows ends each
# line in a carriage return, which would ride along into every value, so strip those first
set -a; source <(tr -d '\r' < .env); set +a
: "${docker_username:?set docker_username in .env}"
: "${docker_pat:?set docker_pat in .env}"

# one tag, the VERSION (checklist #3): no :latest, so a host always pins exactly what it pulls
IMAGE="${docker_username}/corestack-lulc:$(tr -d '[:space:]' < VERSION)"

echo "==> docker login as ${docker_username}"
echo "${docker_pat}" | docker login -u "${docker_username}" --password-stdin

echo "==> building ${IMAGE}"
docker build -t "${IMAGE}" .

echo "==> pushing ${IMAGE}"
docker push "${IMAGE}"

docker logout >/dev/null 2>&1 || true
echo "==> done: ${IMAGE}"
