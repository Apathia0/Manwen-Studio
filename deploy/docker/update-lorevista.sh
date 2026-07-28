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
H5_HEALTH_URL="${H5_HEALTH_URL:-http://127.0.0.1:${WEB_PORT:-8080}/h5/}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
WEB_SERVICE="${WEB_SERVICE:-web}"
MIGRATION_TIMEOUT_SECONDS="${MIGRATION_TIMEOUT_SECONDS:-180}"
MIGRATION_COMMAND="${MIGRATION_COMMAND:-python -c \"from database import init_db; init_db(run_migrations=True, raise_errors=True)\"}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-90}"
BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:-}"
WEB_IMAGE_REF="${WEB_IMAGE_REF:-}"
IMAGE_RETENTION_COUNT="${IMAGE_RETENTION_COUNT:-3}"
UPDATER_PREVIOUS_IMAGE_ID=""

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
  local config_json
  config_json="$(compose config --format json 2>/dev/null)" || return 0
  python3 -c 'import json, sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' \
    "$service" <<<"$config_json" 2>/dev/null || true
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

image_repository_for() {
  local image_ref="${1%@*}"
  if [[ "${image_ref##*/}" == *:* ]]; then
    printf '%s\n' "${image_ref%:*}"
  else
    printf '%s\n' "$image_ref"
  fi
}

is_managed_image_tag() {
  [[ "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

running_image_ids() {
  local cid
  while IFS= read -r cid; do
    [[ -n "$cid" ]] || continue
    docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true
  done < <(docker ps -aq 2>/dev/null || true)
}

prune_project_images() {
  if [[ ! "$IMAGE_RETENTION_COUNT" =~ ^([1-9]|1[0-9]|20)$ ]]; then
    log "invalid IMAGE_RETENTION_COUNT=${IMAGE_RETENTION_COUNT}; skipping project image cleanup"
    return 0
  fi

  local protected_ids
  protected_ids="$({
    running_image_ids
    printf '%s\n' \
      "${BACKEND_PREVIOUS_IMAGE_ID:-}" \
      "${WEB_PREVIOUS_IMAGE_ID:-}" \
      "${UPDATER_PREVIOUS_IMAGE_ID:-}"
  } | sed '/^$/d' | sort -u)"

  local -A repository_uses=()
  local -A visited_repositories=()
  local service image_ref repository
  for service in "$BACKEND_SERVICE" "$WEB_SERVICE" updater; do
    image_ref="$(image_ref_for "$service")"
    repository="$(image_repository_for "$image_ref")"
    [[ -n "$repository" ]] || continue
    repository_uses["$repository"]=$(( ${repository_uses["$repository"]:-0} + 1 ))
  done

  for service in "$BACKEND_SERVICE" "$WEB_SERVICE" updater; do
    image_ref="$(image_ref_for "$service")"
    repository="$(image_repository_for "$image_ref")"
    if [[ -z "$repository" || -n "${visited_repositories[$repository]:-}" ]]; then
      continue
    fi
    visited_repositories["$repository"]=1
    if (( ${repository_uses["$repository"]:-0} > 1 )); then
      log "skipping shared image repository ${repository}; cleanup requires one repository per service"
      continue
    fi

    local -a records=()
    local listed_repository tag details
    while IFS='|' read -r listed_repository tag; do
      [[ "$listed_repository" == "$repository" && -n "$tag" && "$tag" != "<none>" ]] || continue
      is_managed_image_tag "$tag" || continue
      details="$(docker image inspect --format '{{.Created}}|{{.Id}}' "${repository}:${tag}" 2>/dev/null || true)"
      [[ -n "$details" ]] && records+=("${details}|${repository}:${tag}")
    done < <(docker image ls "$repository" --format '{{.Repository}}|{{.Tag}}' 2>/dev/null || true)

    local -A retained_ids=()
    local retained_count=0 record created image_id tagged_ref
    while IFS= read -r record; do
      [[ -n "$record" ]] || continue
      IFS='|' read -r created image_id tagged_ref <<<"$record"

      if grep -Fxq "$image_id" <<<"$protected_ids"; then
        if [[ -z "${retained_ids[$image_id]:-}" ]]; then
          retained_ids["$image_id"]=1
          ((retained_count += 1))
        fi
        continue
      fi
      if [[ -n "${retained_ids[$image_id]:-}" ]]; then
        continue
      fi
      if (( retained_count < IMAGE_RETENTION_COUNT )); then
        retained_ids["$image_id"]=1
        ((retained_count += 1))
        continue
      fi

      log "removing old project image tag ${tagged_ref}"
      docker image rm "$tagged_ref" >/dev/null 2>&1 || \
        log "unable to remove project image tag ${tagged_ref}; it may still be referenced"
    done < <(printf '%s\n' "${records[@]}" | sort -r)
  done
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

check_image_exists() {
  local image="$1"
  if docker buildx imagetools inspect "$image" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

validate_version_images() {
  local version="$1"
  local all_exist=true
  for svc in backend web updater; do
    local img
    img="$(image_ref_for "$svc")"
    local repo="${img%:*}"
    local full_image="${repo}:${version}"
    if ! check_image_exists "$full_image"; then
      log "ERROR: 镜像 ${full_image} 在仓库中不存在"
      all_exist=false
    fi
  done
  if ! $all_exist; then
    log "版本 ${version} 存在缺失的镜像，终止更新"
    exit 1
  fi
  log "版本 ${version} 的所有镜像已验证通过"
}

main() {
  cd "$APP_DIR"
  log "checking for image updates"

  # 清理 .env 中版本清单 URL 的占位值，让 Docker 镜像内置的默认值生效
  if grep -qsE '^UPDATE_MANIFEST_URL=https?://example\.com/' "$ENV_FILE" 2>/dev/null; then
    log "removing placeholder UPDATE_MANIFEST_URL from $ENV_FILE"
    sed -i '/^UPDATE_MANIFEST_URL=/s/^/#/' "$ENV_FILE"
  fi

  # 验证目标版本的镜像标签在仓库中存在
  local current_target
  current_target="$(grep -oP '^APP_VERSION=\K.*' "$ENV_FILE" 2>/dev/null || true)"
  if [[ -n "$current_target" ]]; then
    validate_version_images "$current_target"
  fi

  local backend_before web_before updater_before backend_pulled web_pulled updater_pulled
  backend_before="$(running_image_id_for "$BACKEND_SERVICE")"
  web_before="$(running_image_id_for "$WEB_SERVICE")"
  updater_before="$(running_image_id_for updater)"
  BACKEND_PREVIOUS_IMAGE_ID="$backend_before"
  WEB_PREVIOUS_IMAGE_ID="$web_before"
  UPDATER_PREVIOUS_IMAGE_ID="$updater_before"
  BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:-$(image_ref_for "$BACKEND_SERVICE")}"
  WEB_IMAGE_REF="${WEB_IMAGE_REF:-$(image_ref_for "$WEB_SERVICE")}"

  compose pull "$BACKEND_SERVICE" "$WEB_SERVICE" updater

  backend_pulled="$(image_id_for "$BACKEND_SERVICE")"
  web_pulled="$(image_id_for "$WEB_SERVICE")"
  updater_pulled="$(image_id_for updater)"

  if [[ "$backend_before" == "$backend_pulled" && "$web_before" == "$web_pulled" && "$updater_before" == "$updater_pulled" ]]; then
    log "no image changes detected"
    exit 0
  fi

  if [[ "$backend_before" != "$backend_pulled" || "$web_before" != "$web_pulled" ]]; then
    log "application image change detected; running migrations before service replacement"
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
    if ! wait_for_health "$H5_HEALTH_URL"; then
      log "mobile H5 health check failed"
      rollback
      exit 1
    fi
  fi

  local updated_version
  updated_version="$(grep -oP '^APP_VERSION=\K.*' "$ENV_FILE" 2>/dev/null || true)"
  if [[ -n "$updated_version" ]]; then
    local published_at
    published_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cat > "$APP_DIR/update-manifest.json" << EOF
{
  "channel": "stable",
  "latest_version": "${updated_version}",
  "min_supported_version": "v1.0.0",
  "release_notes": "",
  "published_at": "${published_at}"
}
EOF
    log "updated local manifest to ${updated_version}"
  fi

  if [[ "$updater_before" != "$updater_pulled" ]]; then
    log "restarting updater with new image"
    # 使用独立 helper 容器替换 updater，避免当前容器停止时终止 Compose 进程。
    local updater_image helper_name
    updater_image="$(image_ref_for updater)"
    helper_name="lorevista-updater-replacer-$(date +%s)-${RANDOM}"
    docker run --rm -d \
      --name "$helper_name" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$APP_DIR:$APP_DIR" \
      -e ENV_FILE="$ENV_FILE" \
      -e COMPOSE_FILE="$COMPOSE_FILE" \
      -e LOG_FILE="$LOG_FILE" \
      --entrypoint bash \
      "$updater_image" \
      -lc 'sleep 2; docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --no-deps updater >>"$LOG_FILE" 2>&1'
  fi

  if [[ "${SKIP_IMAGE_PRUNE:-false}" == "true" ]]; then
    log "skipping image prune"
  else
    prune_project_images
  fi

  log "update completed"
}

trap 'log "update failed at line $LINENO"; rollback' ERR
main "$@"
