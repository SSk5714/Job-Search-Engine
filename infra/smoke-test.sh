#!/usr/bin/env bash
# Builds and starts the full Docker stack, then checks it end to end:
# sign-in, security headers, health, a search through the worker, scheduler and monitor
# heartbeats, a backup, and a restore drill inside the containers. Used by CI; safe to run locally
# (it uses its own compose project name and removes its volumes at the end).
set -euo pipefail
cd "$(dirname "$0")/.."

P=jobpilot-smoke
ENVF=$(mktemp)
COOKIES=$(mktemp)
ADMIN_PW=$(python3 -c "import secrets;print(secrets.token_urlsafe(18))")
cat > "$ENVF" <<EOF
JOBPILOT_ENV=production
JOBPILOT_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")
JOBPILOT_ADMIN_USERNAME=smoke
JOBPILOT_ADMIN_PASSWORD=$ADMIN_PW
POSTGRES_PASSWORD=$(python3 -c "import secrets;print(secrets.token_hex(16))")
JOBPILOT_SCHEDULER_INTERVAL_S=10
JOBPILOT_MONITOR_INTERVAL_S=10
EOF
cp "$ENVF" .env
DC="docker compose -p $P -f infra/docker-compose.yml --env-file .env"
cleanup() { $DC logs --no-color --tail 80 > smoke-logs.txt 2>&1 || true; $DC down -v >/dev/null 2>&1 || true; rm -f .env "$ENVF" "$COOKIES"; }
trap cleanup EXIT

step() { echo; echo "== $*"; }
api() {  # method path [json]
  curl -sS -f -b "$COOKIES" -c "$COOKIES" -X "$1" "http://127.0.0.1:3000/api/v1$2" \
    -H "X-Requested-With: jobpilot" -H "Content-Type: application/json" -H "Idempotency-Key: $(python3 -c 'import uuid;print(uuid.uuid4())')" \
    ${3:+-d "$3"}
}
wait_for() {  # seconds description command...
  local t=$1 what=$2; shift 2
  for _ in $(seq 1 "$t"); do if "$@" >/dev/null 2>&1; then echo "ok: $what"; return 0; fi; sleep 1; done
  echo "TIMEOUT: $what"; return 1
}

step "build and start"
$DC up -d --build --wait --wait-timeout 300

step "web serves, with security headers"
H=$(curl -sSI http://127.0.0.1:3000/login)
for h in "content-security-policy" "x-frame-options: DENY" "x-content-type-options: nosniff"; do
  echo "$H" | grep -qi "$h" || { echo "missing header: $h"; exit 1; }
done
echo "$H" | grep -qi "x-powered-by" && { echo "x-powered-by leaked"; exit 1; }
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/docs | grep -q 404 && echo "ok: API docs off in production"

step "sign in"
api POST /auth/login "{\"username\":\"smoke\",\"password\":\"$ADMIN_PW\"}" >/dev/null
api GET /auth/me | grep -q smoke && echo "ok: signed in"

step "search through the worker"
CFG=$(api GET /search-configs | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['id'])")
RUN=$(api POST /search-runs "{\"config_id\":\"$CFG\"}" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
wait_for 120 "run completed" sh -c "curl -sS -b $COOKIES http://127.0.0.1:3000/api/v1/search-runs/$RUN | grep -q '\"status\":\"completed\"'"

step "scheduler and monitor alive"
health() { api GET /health/details | python3 -c "import json,sys;c=json.load(sys.stdin)['checks'];sys.exit(0 if all(c[k]['status']=='ok' for k in ('database','queue','scheduler','monitor')) else 1)"; }
wait_for 120 "database, queue, scheduler, monitor ok" health

step "backup, verify, restore drill"
BEFORE=$(api GET "/applications" | python3 -c "import json,sys;print(len(json.load(sys.stdin)))")
NAME=$($DC exec -T api python -m jobpilot.ops backup | python3 -c "import json,sys;print(json.load(sys.stdin)['name'])")
$DC exec -T api python -m jobpilot.ops verify "$NAME"
$DC stop worker beat monitor
$DC exec -T api python -m jobpilot.ops restore "$NAME" --yes
$DC start worker beat monitor
api POST /auth/login "{\"username\":\"smoke\",\"password\":\"$ADMIN_PW\"}" >/dev/null
AFTER=$(api GET "/applications" | python3 -c "import json,sys;print(len(json.load(sys.stdin)))")
[ "$BEFORE" = "$AFTER" ] && echo "ok: $AFTER applications before and after restore" || { echo "restore mismatch $BEFORE vs $AFTER"; exit 1; }

step "sign-in limit"
for _ in 1 2 3 4 5; do curl -sS -o /dev/null -X POST http://127.0.0.1:3000/api/v1/auth/login -H "X-Requested-With: jobpilot" -H "Content-Type: application/json" -d '{"username":"smoke","password":"wrong"}'; done
CODE=$(curl -sS -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:3000/api/v1/auth/login -H "X-Requested-With: jobpilot" -H "Content-Type: application/json" -d "{\"username\":\"smoke\",\"password\":\"$ADMIN_PW\"}")
[ "$CODE" = "429" ] && echo "ok: locked after 5 failures" || { echo "expected 429, got $CODE"; exit 1; }

step "images"
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E "jobpilot|$P" || true
echo; echo "SMOKE TEST PASSED"
