#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PREFERRED_PYTHON="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
PYTHON_BIN="${REVIEW_STATUS_PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$PREFERRED_PYTHON" ]]; then
    PYTHON_BIN="$PREFERRED_PYTHON"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

export REVIEW_STATUS_SCHEDULED_RETRY=1
exec "$PYTHON_BIN" "$SCRIPT_DIR/run_review_status_sync.py" --mode retry
