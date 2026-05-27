#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_RELEASE_ROOT="${WORKSPACE_RELEASE_ROOT:-$REPO_ROOT}"
RELEASES_DIR="${WORKSPACE_RELEASES_DIR:-$WORKSPACE_RELEASE_ROOT/releases}"
CURRENT_LINK="${WORKSPACE_CURRENT_LINK:-$WORKSPACE_RELEASE_ROOT/current}"
RUNTIME_DIR="${WORKSPACE_RUNTIME_DIR:-$WORKSPACE_RELEASE_ROOT/runtime}"
RELEASE_LOG_DIR="${WORKSPACE_RELEASE_LOG_DIR:-$WORKSPACE_RELEASE_ROOT/release-log}"
RELEASE_KEEP_COUNT="${WORKSPACE_RELEASE_KEEP_COUNT:-5}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo /usr/bin/python3)}"

release_now() {
  date '+%Y-%m-%d %H:%M:%S %z'
}

release_stamp() {
  date '+%Y%m%d-%H%M%S'
}

ensure_release_layout() {
  mkdir -p "$RELEASES_DIR" "$RUNTIME_DIR" "$RELEASE_LOG_DIR"
}

current_release_path() {
  if [[ -L "$CURRENT_LINK" ]]; then
    "$PYTHON_BIN" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$CURRENT_LINK"
    return 0
  fi
  return 1
}

current_release_id() {
  local release_path=""
  release_path="$(current_release_path 2>/dev/null || true)"
  [[ -n "$release_path" ]] || return 1
  basename "$release_path"
}

switch_current_release() {
  local target_dir="$1"
  local temp_link="${CURRENT_LINK}.next"
  ln -sfn "$target_dir" "$temp_link"
  rm -f "$CURRENT_LINK"
  mv -f "$temp_link" "$CURRENT_LINK"
}

append_release_log() {
  local action="$1"
  local release_id="$2"
  local from_release="$3"
  local to_release="$4"
  local git_commit="$5"
  local git_subject="$6"
  local summary="$7"
  local operator_name="$8"
  local result_status="$9"
  local log_path="${RELEASE_LOG_DIR}/releases.jsonl"

  LOG_PATH="$log_path" \
  ACTION="$action" \
  RELEASE_ID="$release_id" \
  FROM_RELEASE="$from_release" \
  TO_RELEASE="$to_release" \
  GIT_COMMIT="$git_commit" \
  GIT_SUBJECT="$git_subject" \
  SUMMARY="$summary" \
  OPERATOR_NAME="$operator_name" \
  RESULT_STATUS="$result_status" \
  "$PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path

log_path = Path(os.environ["LOG_PATH"])
entry = {
    "time": datetime.now().isoformat(timespec="seconds"),
    "action": os.environ.get("ACTION", ""),
    "releaseId": os.environ.get("RELEASE_ID", ""),
    "fromRelease": os.environ.get("FROM_RELEASE", ""),
    "toRelease": os.environ.get("TO_RELEASE", ""),
    "gitCommit": os.environ.get("GIT_COMMIT", ""),
    "gitSubject": os.environ.get("GIT_SUBJECT", ""),
    "summary": os.environ.get("SUMMARY", ""),
    "operator": os.environ.get("OPERATOR_NAME", ""),
    "result": os.environ.get("RESULT_STATUS", ""),
}
log_path.parent.mkdir(parents=True, exist_ok=True)
with log_path.open("a", encoding="utf-8") as fh:
    json.dump(entry, fh, ensure_ascii=False)
    fh.write("\n")
PY
}

prune_old_releases() {
  local current_target=""
  current_target="$(current_release_path 2>/dev/null || true)"

  local release_paths=()
  local discovered_path=""
  while IFS= read -r discovered_path; do
    [[ -n "$discovered_path" ]] && release_paths+=("$discovered_path")
  done < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d | sort)

  if (( ${#release_paths[@]} <= RELEASE_KEEP_COUNT )); then
    return 0
  fi

  local delete_count=$(( ${#release_paths[@]} - RELEASE_KEEP_COUNT ))
  local deleted=0
  local release_path=""
  for release_path in "${release_paths[@]}"; do
    if [[ -n "$current_target" && "$release_path" == "$current_target" ]]; then
      continue
    fi
    rm -rf "$release_path"
    deleted=$((deleted + 1))
    if (( deleted >= delete_count )); then
      break
    fi
  done
}
