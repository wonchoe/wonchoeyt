#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_REPO_DIR="${YTDL_APP_REPO_DIR:-$ROOT_DIR}"
GITOPS_REPO_DIR="${YTDL_GITOPS_REPO_DIR:-/home/ubuntu/k3s-cursor.style}"
STATE_DIR="${YTDL_STATE_DIR:-/home/ubuntu/.deploy-state/ytdl-bot}"
LOG_ROOT="${YTDL_LOG_ROOT:-/home/ubuntu/deploy-logs/ytdl-bot}"
LOCK_FILE="$STATE_DIR/ytdl-bot-auto-update.lock"
LAST_SUCCESS_FILE="$STATE_DIR/last-success.env"
IMAGE_REPO="${YTDL_IMAGE_REPO:-wonchoe/ytdl-bot}"
ARGO_APP_NAME="${YTDL_ARGO_APP_NAME:-ytdl-bot}"
ARGO_NAMESPACE="${YTDL_ARGO_NAMESPACE:-argocd}"
KUBE_NAMESPACE="${YTDL_KUBE_NAMESPACE:-wonchoeyoutubebot}"
DEPLOYMENT_NAME="${YTDL_DEPLOYMENT_NAME:-ytdl-bot}"
LOG_RETENTION_DAYS="${YTDL_LOG_RETENTION_DAYS:-14}"
IMAGE_RETENTION_COUNT="${YTDL_IMAGE_RETENTION_COUNT:-3}"
DRY_RUN=0
CURRENT_BUILD_TAG=""
TARGET_DIGEST=""
TARGET_VERSION=""
LAST_IMAGE_TAG=""

usage() {
  cat <<'EOF'
Usage:
  scripts/ytdl-bot-auto-update.sh [--dry-run]

What it does:
  1. Pulls the wonchoeyt source repo on production.
  2. Checks PyPI for the latest yt-dlp version.
  3. Rebuilds and pushes the image only when code or yt-dlp changed.
  4. Updates the GitOps manifests and pushes them.
  5. Forces an Argo refresh and verifies rollout.
  6. Prunes old local images, build cache, and stale logs.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

mkdir -p "$STATE_DIR" "$LOG_ROOT"
touch "$LOCK_FILE"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another ytdl-bot auto-update run is already in progress, skipping."
  exit 0
fi

timestamp="$(date +%Y%m%d%H%M%S)"
run_dir="$LOG_ROOT/$timestamp"
mkdir -p "$run_dir"
log_file="$run_dir/run.log"
exec > >(tee -a "$log_file") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

run() {
  log "+ $*"
  if [[ $DRY_RUN -eq 0 ]]; then
    "$@"
  fi
}

kube() {
  if [[ $DRY_RUN -eq 0 ]]; then
    sudo kubectl "$@"
  else
    log "+ sudo kubectl $*"
  fi
}

cleanup_old_logs() {
  find "$LOG_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$LOG_RETENTION_DAYS" -exec rm -rf {} + 2>/dev/null || true
}

stash_if_dirty() {
  local repo_dir="$1"
  if [[ -n "$(git -C "$repo_dir" status --porcelain --untracked-files=all)" ]]; then
    log "Dirty working tree detected in $repo_dir, stashing before pull."
    run git -C "$repo_dir" stash push -u -m "pre-ytdl-auto-update-$timestamp"
  fi
}

current_branch() {
  git -C "$1" symbolic-ref --quiet --short HEAD
}

update_repo() {
  local repo_dir="$1"
  local branch="$2"
  stash_if_dirty "$repo_dir"
  run git -C "$repo_dir" fetch origin "$branch"
  local before after
  before="$(git -C "$repo_dir" rev-parse HEAD)"
  run git -C "$repo_dir" pull --ff-only origin "$branch"
  after="$(git -C "$repo_dir" rev-parse HEAD)"
  if [[ "$before" != "$after" ]]; then
    REPO_CHANGED=1
  fi
}

normalize_version() {
  python3 - "$1" <<'PY'
import re
import sys

value = sys.argv[1].strip()
parts = [str(int(part)) for part in re.findall(r'\d+', value)]
print('.'.join(parts))
PY
}

normalize_image_ref() {
  local ref="$1"
  ref="${ref#docker.io/}"
  printf '%s\n' "$ref"
}

get_latest_pypi_version() {
  python3 <<'PY'
import json
from urllib.request import urlopen

with urlopen('https://pypi.org/pypi/yt-dlp/json', timeout=20) as response:
    payload = json.load(response)
print(payload['info']['version'])
PY
}

get_deployed_version() {
  sudo kubectl -n "$KUBE_NAMESPACE" exec deploy/"$DEPLOYMENT_NAME" -- yt-dlp --version 2>/dev/null || true
}

get_remote_latest_digest() {
  docker buildx imagetools inspect "$IMAGE_REPO:latest" | awk '/Digest:/ {print $2; exit}'
}

get_image_version() {
  docker run --rm --entrypoint yt-dlp "$1" --version
}

build_and_push_image() {
  CURRENT_BUILD_TAG="auto-$timestamp"
  log "Building and pushing $IMAGE_REPO:$CURRENT_BUILD_TAG"
  if [[ $DRY_RUN -eq 0 ]]; then
    run docker buildx build --platform linux/arm64 -t "$IMAGE_REPO:latest" -t "$IMAGE_REPO:$CURRENT_BUILD_TAG" --push "$APP_REPO_DIR"
    run docker pull "$IMAGE_REPO:latest"
    run docker pull "$IMAGE_REPO:$CURRENT_BUILD_TAG"
  fi
}

gitops_commit_and_push() {
  if git -C "$GITOPS_REPO_DIR" diff --quiet -- ytld/base/dep.yaml ytld/base/cookie-refresher-cronjob.yaml; then
    log "GitOps manifests already point at $TARGET_DIGEST"
    return 0
  fi

  run git -C "$GITOPS_REPO_DIR" add ytld/base/dep.yaml ytld/base/cookie-refresher-cronjob.yaml
  run git -C "$GITOPS_REPO_DIR" commit -m "chore: update ytdl-bot image to ${TARGET_DIGEST:7:12}"
  run git -C "$GITOPS_REPO_DIR" push origin "$GITOPS_BRANCH"
}

trigger_sync() {
  kube annotate application "$ARGO_APP_NAME" -n "$ARGO_NAMESPACE" argocd.argoproj.io/refresh=hard --overwrite
  kube patch application "$ARGO_APP_NAME" -n "$ARGO_NAMESPACE" --type merge -p '{"operation":{"sync":{"prune":true}}}'
}

wait_for_rollout() {
  local attempt sync_status health_status deployed_image deployed_version expected_image
  for attempt in {1..36}; do
    sync_status="$(sudo kubectl -n "$ARGO_NAMESPACE" get application "$ARGO_APP_NAME" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
    health_status="$(sudo kubectl -n "$ARGO_NAMESPACE" get application "$ARGO_APP_NAME" -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
    if [[ "$sync_status" == "Synced" && "$health_status" == "Healthy" ]]; then
      break
    fi
    log "Waiting for Argo sync: sync=$sync_status health=$health_status"
    sleep 10
  done

  run sudo kubectl -n "$KUBE_NAMESPACE" rollout status deployment/"$DEPLOYMENT_NAME" --timeout=300s

  deployed_image="$(sudo kubectl -n "$KUBE_NAMESPACE" get deployment "$DEPLOYMENT_NAME" -o jsonpath='{.spec.template.spec.containers[0].image}')"
  expected_image="$(normalize_image_ref "$IMAGE_REPO@$TARGET_DIGEST")"
  if [[ "$(normalize_image_ref "$deployed_image")" != "$expected_image" ]]; then
    log "Expected image $expected_image but deployment has $deployed_image"
    exit 1
  fi

  deployed_version="$(get_deployed_version)"
  if [[ -n "$TARGET_VERSION" && "$(normalize_version "$deployed_version")" != "$(normalize_version "$TARGET_VERSION")" ]]; then
    log "Expected yt-dlp $TARGET_VERSION but deployment reports $deployed_version"
    exit 1
  fi

  log "Verified deployment image and yt-dlp version."
}

collect_keep_tags() {
  local keep=()
  keep+=("latest")
  if [[ -n "$CURRENT_BUILD_TAG" ]]; then
    keep+=("$CURRENT_BUILD_TAG")
  fi
  if [[ -n "$LAST_IMAGE_TAG" ]]; then
    keep+=("$LAST_IMAGE_TAG")
  fi

  while IFS= read -r tag; do
    [[ -n "$tag" ]] && keep+=("$tag")
  done < <(docker image ls "$IMAGE_REPO" --format '{{.Tag}}' | grep '^auto-' | sort -r | head -n "$IMAGE_RETENTION_COUNT")

  printf '%s\n' "${keep[@]}" | awk 'NF && !seen[$0]++'
}

cleanup_old_images() {
  mapfile -t keep_tags < <(collect_keep_tags)
  while IFS= read -r tag; do
    [[ -z "$tag" || "$tag" == "<none>" ]] && continue
    if printf '%s\n' "${keep_tags[@]}" | grep -Fxq "$tag"; then
      continue
    fi
    run docker image rm "$IMAGE_REPO:$tag" || true
  done < <(docker image ls "$IMAGE_REPO" --format '{{.Tag}}' | sort -u)

  run docker image prune -f --filter until=168h || true
  run docker builder prune -f --filter until=168h || true
}

write_state() {
  if [[ $DRY_RUN -eq 1 ]]; then
    return 0
  fi

  {
    echo "last_success_at=$(date -Is)"
    echo "app_commit=$APP_HEAD"
    echo "gitops_commit=$(git -C "$GITOPS_REPO_DIR" rev-parse HEAD)"
    echo "image_digest=$TARGET_DIGEST"
    echo "image_tag=${CURRENT_BUILD_TAG:-$LAST_IMAGE_TAG}"
    echo "yt_dlp_version=$TARGET_VERSION"
  } > "$LAST_SUCCESS_FILE"
}

if [[ -f "$LAST_SUCCESS_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$LAST_SUCCESS_FILE"
fi

LAST_IMAGE_TAG="${image_tag:-}"
REPO_CHANGED=0

log "ytdl-bot auto-update started"
log "mode: $([[ $DRY_RUN -eq 1 ]] && echo dry-run || echo apply)"

for required_dir in "$APP_REPO_DIR" "$GITOPS_REPO_DIR"; do
  if [[ ! -d "$required_dir/.git" ]]; then
    log "Missing git repo: $required_dir"
    exit 1
  fi
done

APP_BRANCH="$(current_branch "$APP_REPO_DIR")"
GITOPS_BRANCH="$(current_branch "$GITOPS_REPO_DIR")"

update_repo "$APP_REPO_DIR" "$APP_BRANCH"
APP_HEAD="$(git -C "$APP_REPO_DIR" rev-parse HEAD)"
LATEST_PYPI_VERSION="$(get_latest_pypi_version)"
DEPLOYED_VERSION="$(get_deployed_version)"

log "App repo head: $APP_HEAD"
log "Latest yt-dlp on PyPI: $LATEST_PYPI_VERSION"
log "Deployed yt-dlp version: ${DEPLOYED_VERSION:-unknown}"

if [[ "$(normalize_version "${DEPLOYED_VERSION:-0}")" != "$(normalize_version "$LATEST_PYPI_VERSION")" ]]; then
  NEED_BUILD=1
elif [[ "$APP_HEAD" != "${app_commit:-}" ]]; then
  NEED_BUILD=1
else
  NEED_BUILD=0
fi

if [[ $NEED_BUILD -eq 1 ]]; then
  build_and_push_image
else
  log "No code or yt-dlp version change detected, skipping build."
fi

TARGET_DIGEST="$(get_remote_latest_digest)"
TARGET_VERSION="$(get_image_version "$IMAGE_REPO@$TARGET_DIGEST")"
log "Target image digest: $TARGET_DIGEST"
log "Target yt-dlp version: $TARGET_VERSION"

update_repo "$GITOPS_REPO_DIR" "$GITOPS_BRANCH"
if [[ $DRY_RUN -eq 0 ]]; then
  run bash "$APP_REPO_DIR/scripts/update-gitops-digest.sh" "$GITOPS_REPO_DIR" "$IMAGE_REPO@$TARGET_DIGEST"
fi
gitops_commit_and_push

if [[ $DRY_RUN -eq 0 ]]; then
  trigger_sync
  wait_for_rollout
fi

cleanup_old_images
cleanup_old_logs
write_state

log "ytdl-bot auto-update completed successfully"