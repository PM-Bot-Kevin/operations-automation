#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/release_common.sh"

SUMMARY=""
RELEASE_ID=""
GIT_BIN="${GIT_BIN:-$(command -v git || echo /usr/bin/git)}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo /usr/bin/python3)}"

usage() {
  cat <<'EOF'
用法:
  bash scripts/release_workspace.sh --summary "本次变更说明"
  bash scripts/release_workspace.sh --summary "本次变更说明" --release-id 20260527-100000-abc1234
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --summary)
      SUMMARY="${2:-}"
      shift 2
      ;;
    --release-id)
      RELEASE_ID="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$SUMMARY" ]]; then
  echo "正式发布必须提供 --summary。" >&2
  exit 1
fi

cd "$REPO_ROOT"
python3 "$REPO_ROOT/scripts/validate_workspace_governance.py"

current_branch="$("$GIT_BIN" branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
  echo "正式发布只允许从 main 执行，当前分支: $current_branch" >&2
  exit 1
fi

if [[ -n "$("$GIT_BIN" status --short)" ]]; then
  echo "正式发布只允许发布已提交代码，请先提交或清理工作区。" >&2
  exit 1
fi

ensure_release_layout

git_commit="$("$GIT_BIN" rev-parse HEAD)"
git_short="$("$GIT_BIN" rev-parse --short HEAD)"
git_subject="$("$GIT_BIN" log -1 --pretty=%s)"

if [[ -z "$RELEASE_ID" ]]; then
  RELEASE_ID="$(release_stamp)-${git_short}"
fi

release_dir="$RELEASES_DIR/$RELEASE_ID"
if [[ -e "$release_dir" ]]; then
  echo "正式版本已存在: $RELEASE_ID" >&2
  exit 1
fi

mkdir -p "$release_dir"
"$GIT_BIN" archive --format=tar HEAD | tar -xf - -C "$release_dir"

RELEASE_DIR="$release_dir" \
RELEASE_ID="$RELEASE_ID" \
GIT_COMMIT="$git_commit" \
GIT_SUBJECT="$git_subject" \
SUMMARY="$SUMMARY" \
RUNTIME_DIR="$RUNTIME_DIR" \
"$PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path

release_dir = Path(os.environ["RELEASE_DIR"])
metadata = {
    "releaseId": os.environ["RELEASE_ID"],
    "gitCommit": os.environ["GIT_COMMIT"],
    "gitSubject": os.environ["GIT_SUBJECT"],
    "summary": os.environ["SUMMARY"],
    "runtimeDir": os.environ["RUNTIME_DIR"],
    "createdAt": datetime.now().isoformat(timespec="seconds"),
}
(release_dir / "release-metadata.json").write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

previous_release="$(current_release_id 2>/dev/null || true)"
switch_current_release "$release_dir"

append_release_log \
  "deploy" \
  "$RELEASE_ID" \
  "$previous_release" \
  "$RELEASE_ID" \
  "$git_commit" \
  "$git_subject" \
  "$SUMMARY" \
  "${USER:-unknown}" \
  "success"

prune_old_releases

cat <<EOF
正式发布完成
- release: $RELEASE_ID
- commit: $git_commit
- current: $CURRENT_LINK
- runtime: $RUNTIME_DIR
EOF
