#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/release_common.sh"

TARGET_RELEASE=""
SUMMARY="回滚只切代码版本，不碰 runtime/"
GIT_BIN="${GIT_BIN:-$(command -v git || echo /usr/bin/git)}"

usage() {
  cat <<'EOF'
用法:
  bash scripts/rollback_workspace.sh
  bash scripts/rollback_workspace.sh --to <release-id>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --to)
      TARGET_RELEASE="${2:-}"
      shift 2
      ;;
    --summary)
      SUMMARY="${2:-}"
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

cd "$REPO_ROOT"
ensure_release_layout

current_release="$(current_release_id 2>/dev/null || true)"
if [[ -z "$current_release" ]]; then
  echo "当前没有正式版本，无法回滚。" >&2
  exit 1
fi

release_ids=()
while IFS= read -r release_path; do
  [[ -n "$release_path" ]] || continue
  release_ids+=("$(basename "$release_path")")
done < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d | sort)

if [[ -z "$TARGET_RELEASE" ]]; then
  for (( idx=${#release_ids[@]}-1; idx>=0; idx-- )); do
    candidate="${release_ids[$idx]}"
    if [[ "$candidate" != "$current_release" ]]; then
      TARGET_RELEASE="$candidate"
      break
    fi
  done
fi

if [[ -z "$TARGET_RELEASE" ]]; then
  echo "没有找到可回滚的上一版。" >&2
  exit 1
fi

target_dir="$RELEASES_DIR/$TARGET_RELEASE"
if [[ ! -d "$target_dir" ]]; then
  echo "目标版本不存在: $TARGET_RELEASE" >&2
  exit 1
fi

switch_current_release "$target_dir"

append_release_log \
  "rollback" \
  "$TARGET_RELEASE" \
  "$current_release" \
  "$TARGET_RELEASE" \
  "$("$GIT_BIN" rev-parse HEAD)" \
  "$("$GIT_BIN" log -1 --pretty=%s)" \
  "$SUMMARY" \
  "${USER:-unknown}" \
  "success"

echo "代码版本已回滚: ${current_release} -> ${TARGET_RELEASE}"
