#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${BACKUP_REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CONFIG_PATH="${BACKUP_CONFIG_PATH:-$REPO_ROOT/config/workspace_governance.json}"

MODE="manual"
CUSTOM_MESSAGE=""
REMOTE_NAME="${BACKUP_REMOTE_NAME:-origin}"
EXPECTED_BRANCH="${BACKUP_EXPECTED_BRANCH:-main}"
LABEL="${BACKUP_LABEL:-com.luogic.operations-automation.github-backup}"
STATE_DIR="${BACKUP_STATE_DIR:-$HOME/Library/Application Support/repo-backup-monitor}"
STATE_FILE="${BACKUP_STATE_FILE:-$STATE_DIR/${LABEL}.json}"
LOG_DIR="${BACKUP_LOG_DIR:-$REPO_ROOT/.github_backup_logs}"

GIT_BIN="${GIT_BIN:-$(command -v git || echo /usr/bin/git)}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo /usr/bin/python3)}"
OSASCRIPT_BIN="${BACKUP_OSASCRIPT_BIN:-/usr/bin/osascript}"
DATE_BIN="${DATE_BIN:-/bin/date}"

RUN_DATE="$("$DATE_BIN" '+%F')"
STARTED_AT=""
FINISHED_AT=""
RESULT=""
BRANCH=""
REMOTE_URL=""
HEAD_BEFORE=""
HEAD_AFTER=""
PUSHED_HEAD=""
NOTIFICATION_SENT="false"
MESSAGE=""
IN_FAIL="0"
EXPECTED_REMOTE_URL=""

FORBIDDEN_PREFIXES=(
  "runtime/"
  "releases/"
  "release-log/"
  ".github_backup_logs/"
  "__pycache__/"
  ".pytest_cache/"
  ".mypy_cache/"
  ".ruff_cache/"
  ".codex-staging/"
  ".claude-attachments/"
  ".playwright-cli/"
  ".playwright-mcp/"
  ".artifacts/"
  ".tmp/"
  ".tmp-"
  ".next/"
  ".next-"
  ".venv/"
  "venv/"
  "env/"
  "node_modules/"
  "coverage/"
  "htmlcov/"
)

FORBIDDEN_PATHS=(
  "current"
  ".env"
  ".envrc"
)

FORBIDDEN_KEYWORDS=(
  "secret"
  "secrets"
  "token"
  "credential"
  "credentials"
  "private-key"
  "private_key"
  "apikey"
  "api-key"
)

now() {
  "$DATE_BIN" '+%Y-%m-%d %H:%M:%S %z'
}

current_head() {
  "$GIT_BIN" rev-parse HEAD 2>/dev/null || true
}

load_expected_remote_from_config() {
  if [[ -n "$EXPECTED_REMOTE_URL" ]]; then
    return 0
  fi
  if [[ ! -f "$CONFIG_PATH" ]]; then
    fail "治理配置不存在，无法确认正式 GitHub SSH 远端: $CONFIG_PATH" 1
  fi
  EXPECTED_REMOTE_URL="$("$PYTHON_BIN" - <<'PY' "$CONFIG_PATH"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("workspace", {}).get("github_repository_ssh", ""))
PY
)"
  if [[ -z "$EXPECTED_REMOTE_URL" ]]; then
    fail "治理配置缺少正式 GitHub SSH 远端，拒绝继续备份。" 1
  fi
}

write_state() {
  mkdir -p "$STATE_DIR"
  STATE_FILE="$STATE_FILE" \
  REPO_ROOT="$REPO_ROOT" \
  LABEL="$LABEL" \
  MODE="$MODE" \
  RUN_DATE="$RUN_DATE" \
  STARTED_AT="$STARTED_AT" \
  FINISHED_AT="$FINISHED_AT" \
  RESULT="$RESULT" \
  BRANCH="$BRANCH" \
  REMOTE_URL="$REMOTE_URL" \
  HEAD_BEFORE="$HEAD_BEFORE" \
  HEAD_AFTER="$HEAD_AFTER" \
  PUSHED_HEAD="$PUSHED_HEAD" \
  NOTIFICATION_SENT="$NOTIFICATION_SENT" \
  MESSAGE="$MESSAGE" \
  "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

payload = {
    "repoRoot": os.environ["REPO_ROOT"],
    "label": os.environ["LABEL"],
    "mode": os.environ["MODE"],
    "runDate": os.environ["RUN_DATE"],
    "startedAt": os.environ["STARTED_AT"],
    "finishedAt": os.environ["FINISHED_AT"],
    "result": os.environ["RESULT"],
    "branch": os.environ["BRANCH"],
    "remoteUrl": os.environ["REMOTE_URL"],
    "headBefore": os.environ["HEAD_BEFORE"],
    "headAfter": os.environ["HEAD_AFTER"],
    "pushedHead": os.environ["PUSHED_HEAD"],
    "notificationSent": os.environ["NOTIFICATION_SENT"] == "true",
    "message": os.environ["MESSAGE"],
}
Path(os.environ["STATE_FILE"]).write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
}

send_failure_notification() {
  local reason="$1"
  [[ "$MODE" == "auto" ]] || return 1
  "$OSASCRIPT_BIN" -e "display notification \"${reason}\" with title \"运营自动化 GitHub 自动备份失败\" subtitle \"$(now)\" " >/dev/null 2>&1
}

fail() {
  local reason="$1"
  local exit_code="${2:-1}"

  trap - ERR
  IN_FAIL="1"
  HEAD_AFTER="$(current_head)"
  FINISHED_AT="$(now)"
  RESULT="failed"
  MESSAGE="$reason"
  NOTIFICATION_SENT="false"

  if send_failure_notification "$reason"; then
    NOTIFICATION_SENT="true"
  fi

  write_state
  echo "$reason" >&2
  exit "$exit_code"
}

on_error() {
  local exit_code="$1"
  local line="$2"
  if [[ "$IN_FAIL" == "1" ]]; then
    exit "$exit_code"
  fi
  fail "请查看日志，失败位置在脚本第 ${line} 行附近。" "$exit_code"
}

trap 'on_error $? $LINENO' ERR

while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto)
      MODE="auto"
      shift
      ;;
    --message)
      CUSTOM_MESSAGE="${2:-}"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
用法:
  bash scripts/github_backup.sh
  bash scripts/github_backup.sh --message "手动备份说明"
  bash scripts/github_backup.sh --auto
EOF
      exit 0
      ;;
    *)
      fail "未知参数: $1" 1
      ;;
  esac
done

ensure_main_branch() {
  BRANCH="$("$GIT_BIN" branch --show-current)"
  if [[ "$BRANCH" != "$EXPECTED_BRANCH" ]]; then
    fail "Refusing to back up from branch: ${BRANCH:-unknown}" 1
  fi
}

ensure_remote_uses_ssh() {
  load_expected_remote_from_config
  REMOTE_URL="$("$GIT_BIN" remote get-url "$REMOTE_NAME" 2>/dev/null || true)"
  if [[ -z "$REMOTE_URL" ]]; then
    fail "GitHub SSH 远端未配置，请先创建仓库并设置 origin。" 1
  fi
  if [[ "$REMOTE_URL" != git@github.com:* ]]; then
    fail "GitHub 备份只允许使用 SSH 远端，当前是: $REMOTE_URL" 1
  fi
  if [[ "$REMOTE_URL" != "$EXPECTED_REMOTE_URL" ]]; then
    fail "GitHub 备份远端与治理配置不一致，当前是: $REMOTE_URL" 1
  fi
}

stage_changes() {
  "$GIT_BIN" add -A
}

is_forbidden_path() {
  local path="$1"
  local path_lower=""
  local basename_lower=""
  local prefix=""
  local keyword=""

  path_lower="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"
  basename_lower="$(basename "$path_lower")"

  case "$path_lower" in
    *.log|*.pyc|*.pyo|*.pyd|*.sqlite|*.sqlite3|*.db|*.pem|*.key|*.p12|*.pfx|*.crt|*.cer|*.der|*.bak|*.backup|*.tmp|*.temp|*.zip|*.tar|*.tar.gz|*.tgz|.ds_store|.env.*|*/.env|*/.env.*)
      return 0
      ;;
  esac

  if [[ "$path" != */* ]]; then
    case "$path_lower" in
      *.png|*.jpg|*.jpeg|*.gif|*.webp|*.csv|*.tsv|*.zip|*.tar|*.tar.gz|*.tgz|*.tmp)
        return 0
        ;;
    esac
  fi

  for prefix in "${FORBIDDEN_PREFIXES[@]}"; do
    if [[ "$path_lower" == "$prefix"* ]]; then
      return 0
    fi
  done

  for prefix in "${FORBIDDEN_PATHS[@]}"; do
    if [[ "$path_lower" == "$prefix" || "$basename_lower" == "$prefix" ]]; then
      return 0
    fi
  done

  for keyword in "${FORBIDDEN_KEYWORDS[@]}"; do
    if [[ "$path_lower" == *"$keyword"* ]]; then
      return 0
    fi
  done

  return 1
}

ensure_no_forbidden_staged_paths() {
  local staged_path=""
  local forbidden_paths=()
  while IFS= read -r -d '' staged_path; do
    [[ -z "$staged_path" ]] && continue
    if is_forbidden_path "$staged_path"; then
      forbidden_paths+=("$staged_path")
    fi
  done < <("$GIT_BIN" diff --cached --name-only -z)

  if [[ "${#forbidden_paths[@]}" -gt 0 ]]; then
    "$GIT_BIN" reset -q HEAD -- "${forbidden_paths[@]}" >/dev/null 2>&1 || true
    fail "拒绝备份这些内容，请先处理后再试: ${forbidden_paths[*]}" 1
  fi
}

build_commit_message() {
  if [[ -n "$CUSTOM_MESSAGE" ]]; then
    echo "$CUSTOM_MESSAGE"
    return 0
  fi
  if [[ "$MODE" == "auto" ]]; then
    echo "backup(auto): $(now)"
  else
    echo "backup(manual): $(now)"
  fi
}

cd "$REPO_ROOT"
mkdir -p "$LOG_DIR"

BRANCH="$("$GIT_BIN" branch --show-current 2>/dev/null || true)"
REMOTE_URL="$("$GIT_BIN" remote get-url "$REMOTE_NAME" 2>/dev/null || true)"
HEAD_BEFORE="$(current_head)"
STARTED_AT="$(now)"
RESULT="started"
MESSAGE="GitHub 备份任务已启动。"
write_state

ensure_main_branch
ensure_remote_uses_ssh
stage_changes
ensure_no_forbidden_staged_paths

if [[ -z "$("$GIT_BIN" diff --cached --name-only)" ]]; then
  HEAD_AFTER="$(current_head)"
  FINISHED_AT="$(now)"
  RESULT="success-no-change"
  MESSAGE="No changes to back up."
  write_state
  echo "No changes to back up."
  exit 0
fi

commit_message="$(build_commit_message)"
"$GIT_BIN" commit -m "$commit_message" >/dev/null
"$GIT_BIN" push "$REMOTE_NAME" "$EXPECTED_BRANCH" >/dev/null

HEAD_AFTER="$(current_head)"
PUSHED_HEAD="$HEAD_AFTER"
FINISHED_AT="$(now)"
RESULT="success-pushed"
MESSAGE="GitHub 备份已推送。"
write_state

echo "GitHub 备份完成: $PUSHED_HEAD"
