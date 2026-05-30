#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_DIR="${HOME}/Library/LaunchAgents"
LAUNCH_DOMAIN="gui/$(id -u)"
LABEL_BASE="${REVIEW_STATUS_LABEL_BASE:-com.luogic.operations-automation.review-status-sync}"
MAIN_LABEL="${LABEL_BASE}"
CHECK_LABEL="${LABEL_BASE}-check"
MAIN_PLIST="${PLIST_DIR}/${MAIN_LABEL}.plist"
CHECK_PLIST="${PLIST_DIR}/${CHECK_LABEL}.plist"
LOG_DIR="${REPO_ROOT}/runtime/review_status_sync_logs"
MAIN_LOG="${LOG_DIR}/main.log"
CHECK_LOG="${LOG_DIR}/check.log"
PREFERRED_PYTHON="${REVIEW_STATUS_PREFERRED_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.11/bin/python3}"
LAUNCH_PATH="${REVIEW_STATUS_LAUNCH_PATH:-/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$MAIN_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${MAIN_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${REPO_ROOT}/scripts/review_status_sync_auto.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${LAUNCH_PATH}</string>
    <key>REVIEW_STATUS_PYTHON_BIN</key>
    <string>${PREFERRED_PYTHON}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>14</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${MAIN_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${MAIN_LOG}</string>
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
    <string>${REPO_ROOT}/scripts/check_review_status_sync.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${LAUNCH_PATH}</string>
    <key>REVIEW_STATUS_PYTHON_BIN</key>
    <string>${PREFERRED_PYTHON}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>14</integer>
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

launchctl bootout "$LAUNCH_DOMAIN" "$MAIN_PLIST" >/dev/null 2>&1 || true
launchctl bootout "$LAUNCH_DOMAIN" "$CHECK_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "$LAUNCH_DOMAIN" "$MAIN_PLIST"
launchctl bootstrap "$LAUNCH_DOMAIN" "$CHECK_PLIST"

cat <<EOF
已安装好评已上评同步定时任务
- main: $MAIN_PLIST
- check: $CHECK_PLIST
- log dir: $LOG_DIR
- python: $PREFERRED_PYTHON
EOF
