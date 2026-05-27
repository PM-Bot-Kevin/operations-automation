#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_DIR="${HOME}/Library/LaunchAgents"
LABEL_BASE="${BACKUP_LABEL_BASE:-com.luogic.operations-automation.github-backup}"
BACKUP_LABEL="${LABEL_BASE}"
CHECK_LABEL="${LABEL_BASE}-check"
BACKUP_PLIST="${PLIST_DIR}/${BACKUP_LABEL}.plist"
CHECK_PLIST="${PLIST_DIR}/${CHECK_LABEL}.plist"
LOG_DIR="${REPO_ROOT}/.github_backup_logs"
BACKUP_LOG="${LOG_DIR}/github-backup.log"
CHECK_LOG="${LOG_DIR}/github-backup-check.log"
GIT_BIN="${GIT_BIN:-$(command -v git || echo /usr/bin/git)}"

remote_url="$("$GIT_BIN" remote get-url origin 2>/dev/null || true)"
if [[ -z "$remote_url" ]]; then
  echo "还没有配置 origin，请先创建 GitHub 仓库并设置 SSH 远端。" >&2
  exit 1
fi
if [[ "$remote_url" != git@github.com:* ]]; then
  echo "GitHub 自动备份只允许 SSH 远端，当前是: $remote_url" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$BACKUP_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${BACKUP_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${REPO_ROOT}/scripts/github_backup_auto.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${BACKUP_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${BACKUP_LOG}</string>
</dict>
</plist>
EOF

cat > "$CHECK_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${CHECK_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${REPO_ROOT}/scripts/check_github_backup.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>20</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${CHECK_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${CHECK_LOG}</string>
</dict>
</plist>
EOF

launchctl unload "$BACKUP_PLIST" >/dev/null 2>&1 || true
launchctl unload "$CHECK_PLIST" >/dev/null 2>&1 || true
launchctl load "$BACKUP_PLIST"
launchctl load "$CHECK_PLIST"

cat <<EOF
自动备份任务已安装
- backup: $BACKUP_PLIST
- check: $CHECK_PLIST
- log dir: $LOG_DIR
EOF
