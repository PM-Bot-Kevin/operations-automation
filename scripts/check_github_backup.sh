#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${BACKUP_REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
LABEL="${BACKUP_LABEL:-com.luogic.operations-automation.github-backup}"
STATE_DIR="${BACKUP_STATE_DIR:-$HOME/Library/Application Support/repo-backup-monitor}"
STATE_FILE="${BACKUP_STATE_FILE:-$STATE_DIR/${LABEL}.json}"
OSASCRIPT_BIN="${BACKUP_OSASCRIPT_BIN:-/usr/bin/osascript}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo /usr/bin/python3)}"
DATE_BIN="${DATE_BIN:-/bin/date}"
TODAY="${BACKUP_TODAY:-$("$DATE_BIN" '+%F')}"

send_notification() {
  local reason="$1"
  "$OSASCRIPT_BIN" -e "display notification \"${reason}\" with title \"运营自动化 GitHub 自动备份巡检提醒\" subtitle \"$("$DATE_BIN" '+%Y-%m-%d %H:%M:%S %z')\" " >/dev/null 2>&1
}

if [[ ! -f "$STATE_FILE" ]]; then
  send_notification "今天没有看到 GitHub 自动备份状态文件，请检查主任务。"
  echo "Missing state file: $STATE_FILE" >&2
  exit 1
fi

CHECK_OUTPUT="$("$PYTHON_BIN" - <<'PY' "$STATE_FILE" "$TODAY"
import json
import sys
from pathlib import Path

state_file = Path(sys.argv[1])
today = sys.argv[2]
payload = json.loads(state_file.read_text(encoding="utf-8"))
result = payload.get("result", "")
run_date = payload.get("runDate", "")
message = payload.get("message", "")
notification_sent = payload.get("notificationSent", False)

if run_date != today:
    print("stale|今天没有看到 GitHub 自动备份完成记录，请检查主任务。")
elif result in {"success-no-change", "success-pushed"}:
    print(f"ok|Backup check passed: {result}")
elif result == "started":
    print("started|GitHub 自动备份未正常结束，请检查主任务是否卡住。")
elif result == "failed" and notification_sent:
    print("already_notified|Backup failed but main task already notified.")
elif result == "failed":
    print(f"failed|GitHub 自动备份失败且主任务未通知：{message or '请查看日志。'}")
else:
    print(f"unknown|GitHub 自动备份状态异常：{result or 'missing'}。")
PY
)"

CHECK_STATUS="${CHECK_OUTPUT%%|*}"
CHECK_MESSAGE="${CHECK_OUTPUT#*|}"

case "$CHECK_STATUS" in
  ok|already_notified)
    echo "$CHECK_MESSAGE"
    exit 0
    ;;
  *)
    send_notification "$CHECK_MESSAGE"
    echo "$CHECK_MESSAGE" >&2
    exit 1
    ;;
esac
