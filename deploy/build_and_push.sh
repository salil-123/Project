#!/usr/bin/env bash
# Build the LULC image and push it to Docker Hub, using the creds in ../.env.
# Run from anywhere:  bash deploy/build_and_push.sh
set -euo pipefail
cd "$(dirname "$0")/.."           # repo root (build context)

# pull docker_username / docker_pat from .env without echoing them
set -a; source .env; set +a
: "${docker_username:?set docker_username in .env}"
: "${docker_pat:?set docker_pat in .env}"

IMAGE="${docker_username}/corestack-lulc:latest"
# checklist #3 wants a version tag too, so a host can pin what it pulls
VERSIONED="${docker_username}/corestack-lulc:$(tr -d '[:space:]' < VERSION)"

echo "==> docker login as ${docker_username}"
echo "${docker_pat}" | docker login -u "${docker_username}" --password-stdin

echo "==> building ${IMAGE}"
docker build -t "${IMAGE}" -t "${VERSIONED}" .

echo "==> pushing ${IMAGE}"
docker push "${IMAGE}"
docker push "${VERSIONED}"

docker logout >/dev/null 2>&1 || true
echo "==> done: ${IMAGE} and ${VERSIONED}"
