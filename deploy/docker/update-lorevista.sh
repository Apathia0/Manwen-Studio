#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/lorevista}"
COMPOSE_FILE="${COMPOSE_FILE:-${APP_DIR}/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"
LOCK_FILE="${LOCK_FILE:-/var/lock/lorevista-update.lock}"
LOG_FILE="${LOG_FILE:-/var/log/lorevista-update.log}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${WEB_PORT:-8080}/api/health}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-$HEALTH_URL}"
WEB_HEALTH_URL="${WEB_HEALTH_URL:-$HEALTH_URL}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
WEB_SERVICE="${WEB_SERVICE:-web}"
MIGRATION_TIMEOUT_SECONDS="${MIGRATION_TIMEOUT_SECONDS:-180}"
MIGRATION_COMMAND="${MIGRATION_COMMAND:-python -c \"from database import init_db; init_db(run_migrations=True, raise_errors=True)\"}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-90}"
BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:-}"
WEB_IMAGE_REF="${WEB_IMAGE_REF:-}"

mkdir -p "$(dirname "$LOG_FILE")"
LOCK_DIR="${LOCK_FILE}.d"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "$(date -Is) update already running" >>"$LOG_FILE"
    exit 0
  fi
else
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$(date -Is) update already running" >>"$LOG_FILE"
    exit 0
  fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
fi

log() {
  echo "$(date -Is) $*" | tee -a "$LOG_FILE"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose_with_timeout() {
  timeout "$1" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "${@:2}"
}

image_id_for() {
  local service="$1"
  compose images -q "$service" 2>/dev/null | head -n1 || true
}

image_ref_for() {
  local service="$1"
  compose config --images "$service" 2>/dev/null | head -n1 || true
}

running_image_id_for() {
  local service="$1"
  local cid
  cid="$(compose ps -q "$service" 2>/dev/null || true)"
  if [[ -z "$cid" ]]; then
    return 0
  fi
  docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true
}

wait_for_health() {
  local url="$1"
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if curl -fsS "$url" >/dev/null; then
      return 0
    fi
    sleep 3
  done
  return 1
}

rollback() {
  log "rollback: restoring previous compose state"
  if [[ -n "${BACKEND_PREVIOUS_IMAGE_ID:-}" && -n "${BACKEND_IMAGE_REF:-}" ]]; then
    docker tag "$BACKEND_PREVIOUS_IMAGE_ID" "$BACKEND_IMAGE_REF" || true
  fi
  if [[ -n "${WEB_PREVIOUS_IMAGE_ID:-}" && -n "${WEB_IMAGE_REF:-}" ]]; then
    docker tag "$WEB_PREVIOUS_IMAGE_ID" "$WEB_IMAGE_REF" || true
  fi
  compose up -d "$BACKEND_SERVICE" "$WEB_SERVICE" || true
}

main() {
  cd "$APP_DIR"
  log "checking for image updates"

  local backend_before web_before backend_pulled web_pulled
  backend_before="$(running_image_id_for "$BACKEND_SERVICE")"
  web_before="$(running_image_id_for "$WEB_SERVICE")"
  BACKEND_PREVIOUS_IMAGE_ID="$backend_before"
  WEB_PREVIOUS_IMAGE_ID="$web_before"
  BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:-$(image_ref_for "$BACKEND_SERVICE")}"
  WEB_IMAGE_REF="${WEB_IMAGE_REF:-$(image_ref_for "$WEB_SERVICE")}"

  compose pull "$BACKEND_SERVICE" "$WEB_SERVICE"

  backend_pulled="$(image_id_for "$BACKEND_SERVICE")"
  web_pulled="$(image_id_for "$WEB_SERVICE")"

  if [[ "$backend_before" == "$backend_pulled" && "$web_before" == "$web_pulled" ]]; then
    log "no image changes detected"
    exit 0
  fi

  log "new image detected; running migrations before service replacement"
  compose_with_timeout "$MIGRATION_TIMEOUT_SECONDS" run --rm \
    -e RUN_STARTUP_MIGRATIONS=true \
    "$BACKEND_SERVICE" \
    sh -lc "$MIGRATION_COMMAND"

  log "starting backend with new image"
  compose up -d --no-deps "$BACKEND_SERVICE"
  if ! wait_for_health "$BACKEND_HEALTH_URL"; then
    log "backend health check failed"
    rollback
    exit 1
  fi

  log "starting web with new image"
  compose up -d --no-deps "$WEB_SERVICE"
  if ! wait_for_health "$WEB_HEALTH_URL"; then
    log "web health check failed"
    rollback
    exit 1
  fi

  if [[ "${SKIP_IMAGE_PRUNE:-false}" == "true" ]]; then
    log "skipping image prune"
  else
    docker image prune -f --filter "until=168h" >/dev/null || true
  fi
  log "update completed"
}

trap 'log "update failed at line $LINENO"; rollback' ERR
main "$@"
