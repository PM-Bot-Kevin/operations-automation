#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFEST_PATH="${SECRET_RECOVERY_MANIFEST_PATH:-$SCRIPT_DIR/secret_recovery_manifest.txt}"
OUTPUT_DIR="${SECRET_RECOVERY_OUTPUT_DIR:-$REPO_ROOT/recovery/secret-bundles}"
OPENSSL_BIN="${SECRET_RECOVERY_OPENSSL_BIN:-/usr/bin/openssl}"
SHASUM_BIN="${SECRET_RECOVERY_SHASUM_BIN:-/usr/bin/shasum}"
PASSPHRASE_FILE="${SECRET_RECOVERY_PASSPHRASE_FILE:-$HOME/Library/Application Support/ai-copy-factory-secrets/secret-recovery-passphrase.txt}"
BUNDLE_NAME=""

usage() {
  cat <<'EOF'
Usage:
  zsh scripts/maintenance/build_secret_recovery_bundle.sh \
    --passphrase-file /path/to/passphrase.txt

Options:
  --manifest PATH         Override manifest file.
  --output-dir PATH       Override bundle output directory.
  --bundle-name NAME      Override output bundle basename.
  --passphrase-file PATH  Plain-text file containing the decryption passphrase.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      MANIFEST_PATH="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --bundle-name)
      BUNDLE_NAME="${2:-}"
      shift 2
      ;;
    --passphrase-file)
      PASSPHRASE_FILE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "Manifest 不存在：$MANIFEST_PATH" >&2
  exit 1
fi

if [[ -z "$PASSPHRASE_FILE" || ! -f "$PASSPHRASE_FILE" ]]; then
  echo "缺少有效的 --passphrase-file。" >&2
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

copy_entry() {
  local requirement="$1"
  local logical_name="$2"
  local source_path="$3"
  local payload_root="$4"
  local restore_manifest="$5"
  local resolved_path
  resolved_path="$(expand_path "$source_path")"

  if [[ ! -e "$resolved_path" ]]; then
    if [[ "$requirement" == "required" ]]; then
      echo "缺少必需文件：$logical_name -> $resolved_path" >&2
      return 1
    fi
    printf 'optional\t%s\t%s\tmissing\t-\n' "$logical_name" "$resolved_path" >> "$restore_manifest"
    return 0
  fi

  local payload_rel="payload/$logical_name"
  local payload_path="$payload_root/$logical_name"
  if [[ -d "$resolved_path" ]]; then
    /bin/mkdir -p "$payload_path"
    /bin/cp -R "$resolved_path"/. "$payload_path"/
    printf '%s\t%s\t%s\tdirectory\t%s\n' "$requirement" "$logical_name" "$resolved_path" "$payload_rel" >> "$restore_manifest"
    return 0
  fi

  /bin/mkdir -p "$(dirname "$payload_path")"
  /bin/cp -p "$resolved_path" "$payload_path"
  printf '%s\t%s\t%s\tfile\t%s\n' "$requirement" "$logical_name" "$resolved_path" "$payload_rel" >> "$restore_manifest"
}

tmp_root="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/secret-recovery.XXXXXX")"
cleanup() {
  /bin/rm -rf "$tmp_root"
}
trap cleanup EXIT

payload_root="$tmp_root/payload"
restore_manifest="$tmp_root/restore_manifest.tsv"
/bin/mkdir -p "$payload_root"
printf 'requirement\tlogical_name\trestore_path\tentry_type\tpayload_path\n' > "$restore_manifest"

while IFS='|' read -r requirement logical_name source_path; do
  [[ -z "${requirement:-}" ]] && continue
  [[ "${requirement:0:1}" == "#" ]] && continue

  if [[ -z "${logical_name:-}" || -z "${source_path:-}" ]]; then
    echo "Manifest 行格式错误：$requirement|$logical_name|$source_path" >&2
    exit 1
  fi

  copy_entry "$requirement" "$logical_name" "$source_path" "$payload_root" "$restore_manifest"
done < "$MANIFEST_PATH"

cat > "$tmp_root/README.txt" <<'EOF'
This archive stores machine-level secret material needed to recover production use.

1. Decrypt the bundle with the offline passphrase.
2. Extract the archive.
3. Inspect restore_manifest.tsv to place each file back to its original path.
4. After restoring secrets, clone/pull the code repos and continue normal setup.
EOF

/bin/mkdir -p "$OUTPUT_DIR"
timestamp="$(/bin/date '+%Y%m%d-%H%M%S')"
if [[ -z "$BUNDLE_NAME" ]]; then
  BUNDLE_NAME="secret-recovery-bundle-$timestamp"
fi

plaintext_archive="$tmp_root/${BUNDLE_NAME}.tar.gz"
encrypted_archive="$OUTPUT_DIR/${BUNDLE_NAME}.tar.gz.enc"
checksum_file="$encrypted_archive.sha256"

/usr/bin/tar -C "$tmp_root" -czf "$plaintext_archive" payload restore_manifest.tsv README.txt
"$OPENSSL_BIN" enc -aes-256-cbc -salt -pbkdf2 -iter 600000 \
  -in "$plaintext_archive" \
  -out "$encrypted_archive" \
  -pass "file:$PASSPHRASE_FILE"
"$SHASUM_BIN" -a 256 "$encrypted_archive" > "$checksum_file"

echo "Encrypted secret bundle: $encrypted_archive"
echo "Checksum: $checksum_file"
