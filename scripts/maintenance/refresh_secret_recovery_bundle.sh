#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_SCRIPT="${SECRET_RECOVERY_BUILD_SCRIPT:-$SCRIPT_DIR/build_secret_recovery_bundle.sh}"
OUTPUT_DIR="${SECRET_RECOVERY_OUTPUT_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)/recovery/secret-bundles}"
BUNDLE_NAME="${SECRET_RECOVERY_BUNDLE_NAME:-secret-recovery-bundle-latest}"
MANIFEST_PATH="${SECRET_RECOVERY_MANIFEST_PATH:-$SCRIPT_DIR/secret_recovery_manifest.txt}"
STATE_ROOT="${SECRET_RECOVERY_STATE_ROOT:-$HOME/Library/Application Support/repo-backup-monitor}"
INPUT_HASH_FILE="${SECRET_RECOVERY_INPUT_HASH_FILE:-$STATE_ROOT/operations-automation.secret-recovery-bundle.input.sha256}"

if [[ ! -x "$BUILD_SCRIPT" ]]; then
  echo "Secret bundle build script 不可执行：$BUILD_SCRIPT" >&2
  exit 1
fi

expand_path() {
  local raw="$1"
  if [[ "$raw" == \$HOME/* ]]; then
    printf '%s\n' "$HOME/${raw#\$HOME/}"
    return 0
  fi
  printf '%s\n' "$raw"
}

hash_manifest_entry() {
  local requirement="$1"
  local logical_name="$2"
  local source_path="$3"
  local resolved_path
  resolved_path="$(expand_path "$source_path")"

  if [[ ! -e "$resolved_path" ]]; then
    printf '%s|%s|%s|missing\n' "$requirement" "$logical_name" "$resolved_path"
    return 0
  fi

  if [[ -d "$resolved_path" ]]; then
    printf '%s|%s|%s|directory\n' "$requirement" "$logical_name" "$resolved_path"
    while IFS= read -r file_path; do
      local file_hash
      file_hash="$(/usr/bin/shasum -a 256 "$file_path" | /usr/bin/awk '{print $1}')"
      printf '%s|%s|%s|%s\n' "$logical_name" "${file_path#$resolved_path/}" "$file_hash" "$(/usr/bin/stat -f '%z' "$file_path")"
    done < <(/usr/bin/find "$resolved_path" -type f | /usr/bin/sort)
    return 0
  fi

  local file_hash
  file_hash="$(/usr/bin/shasum -a 256 "$resolved_path" | /usr/bin/awk '{print $1}')"
  printf '%s|%s|%s|file|%s|%s\n' "$requirement" "$logical_name" "$resolved_path" "$file_hash" "$(/usr/bin/stat -f '%z' "$resolved_path")"
}

current_input_hash="$(
  while IFS='|' read -r requirement logical_name source_path; do
    [[ -z "${requirement:-}" ]] && continue
    [[ "${requirement:0:1}" == "#" ]] && continue
    hash_manifest_entry "$requirement" "$logical_name" "$source_path"
  done < "$MANIFEST_PATH" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}'
)"

/bin/mkdir -p "$STATE_ROOT"
if [[ -f "$INPUT_HASH_FILE" ]]; then
  last_input_hash="$(<"$INPUT_HASH_FILE")"
  if [[ "$last_input_hash" == "$current_input_hash" && -f "$OUTPUT_DIR/${BUNDLE_NAME}.tar.gz.enc" && -f "$OUTPUT_DIR/${BUNDLE_NAME}.tar.gz.enc.sha256" ]]; then
    echo "Secret bundle inputs unchanged."
    exit 0
  fi
fi

zsh "$BUILD_SCRIPT" \
  --output-dir "$OUTPUT_DIR" \
  --bundle-name "$BUNDLE_NAME" \
  "$@"

printf '%s\n' "$current_input_hash" > "$INPUT_HASH_FILE"
