#!/bin/zsh

set -euo pipefail

TARGET_FILE="${SECRET_RECOVERY_PASSPHRASE_FILE:-$HOME/Library/Application Support/ai-copy-factory-secrets/secret-recovery-passphrase.txt}"
SOURCE_FILE=""

usage() {
  cat <<'EOF'
Usage:
  zsh scripts/maintenance/install_secret_recovery_passphrase.sh \
    --passphrase-file /path/to/passphrase.txt
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --passphrase-file)
      SOURCE_FILE="${2:-}"
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

if [[ -z "$SOURCE_FILE" || ! -f "$SOURCE_FILE" ]]; then
  echo "缺少有效的 --passphrase-file。" >&2
  exit 1
fi

/bin/mkdir -p "$(dirname "$TARGET_FILE")"
/bin/cp "$SOURCE_FILE" "$TARGET_FILE"
/bin/chmod 600 "$TARGET_FILE"

echo "Installed secret recovery passphrase: $TARGET_FILE"
