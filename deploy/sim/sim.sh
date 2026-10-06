#!/bin/bash
# The tower on this laptop. Run from WSL (or any Linux with Docker), from anywhere:
#
#   deploy/sim/sim.sh up [--tower-net] [--local-login]   start (recreates, so code and .env changes land)
#   deploy/sim/sim.sh test       journey + visitor + a Run through Airflow  (needs --local-login)
#   deploy/sim/sim.sh towernet   sign-in and the deep check under broken DNS (needs --tower-net)
#   deploy/sim/sim.sh status     what's running, RAM per container, the deep check
#   deploy/sim/sim.sh down
set -e
cd "$(dirname "$0")"

# Earth Engine through your own login: on WSL that's the Windows user's folder
EE_CREDS_DIR=${EE_CREDS_DIR:-$(ls -d /mnt/c/Users/*/.config/earthengine 2>/dev/null | head -1)}
export EE_CREDS_DIR=${EE_CREDS_DIR:-$HOME/.config/earthengine}

files=(-f docker-compose.sim.yml)
for a in "$@"; do
  case $a in
    --tower-net)   files+=(-f tower-network.yml) ;;
    --local-login) files+=(-f local-login.yml) ;;
  esac
done
dc() { docker compose "${files[@]}" "$@"; }
B=http://localhost:8080/act4dws5/diy-lulc
IN="dc exec -T lulc python"

wait_for() {   # url, what
  for _ in $(seq 1 120); do curl -sf -o /dev/null "$1" && return 0; sleep 2; done
  echo "$2 didn't come up"; return 1
}

case "$1" in
  up)
    dc up -d --force-recreate --remove-orphans
    wait_for "$B/api/health" "the app" || { dc logs --tail 40 lulc; exit 1; }
    wait_for "http://localhost:8081/api/v1/health" "Airflow" || { dc logs --tail 40 airflow; exit 1; }
    # the sim's own Earth Engine folder, made once, so test exports never mix with real ones
    $IN -c "import config; ee = config.ee_init(); r = config.EE_ASSET_ROOT
try: ee.data.getAsset(r)
except Exception: ee.data.createAsset({'type': 'FOLDER'}, r); print('made', r)" 2>/dev/null       || echo "(couldn't reach Earth Engine to check the sim folder; expected with --tower-net)"
    echo
    echo "app via nginx:   $B/"
    echo "app direct:      http://localhost:8000/"
    echo "Airflow:         http://localhost:8081/  (admin / admin)"
    ;;
  test)
    $IN deploy/sim/journey_test.py --base http://nginx:8080/act4dws5/diy-lulc
    $IN deploy/sim/checks.py visitor
    $IN deploy/sim/checks.py dag
    ;;
  towernet)
    $IN deploy/sim/checks.py towernet
    ;;
  status)
    dc ps --format 'table {{.Service}}\t{{.Status}}'
    docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' $(dc ps -q)
    curl -s -m 40 "$B/api/health?deep=1"; echo
    ;;
  down)
    docker compose -f docker-compose.sim.yml down --remove-orphans
    ;;
  *)
    sed -n 2,9p "$0"; exit 1 ;;
esac
