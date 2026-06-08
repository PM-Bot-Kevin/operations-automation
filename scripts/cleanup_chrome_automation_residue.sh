#!/usr/bin/env bash
set -euo pipefail

CHROME_ROOT="${HOME}/Library/Application Support/Google/Chrome"
CHROME_MAIN_PATTERN='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
PLAYWRIGHT_PROFILE_PATTERN='playwright_chromiumdev_profile-'
SINGLETON_FILES=("SingletonLock" "SingletonCookie" "SingletonSocket")

usage() {
  cat <<'EOF'
用法：
  bash scripts/cleanup_chrome_automation_residue.sh status
  bash scripts/cleanup_chrome_automation_residue.sh cleanup [--dry-run]

说明：
  - 只处理自动化测试残留的临时 Chrome 进程
  - 只有在“当前没有真实 Chrome 主进程”且锁指向失效 pid 时，才会清理 Singleton* 残留
EOF
}

real_chrome_pids() {
  ps -ax -o pid=,command= \
    | awk -v pattern="${CHROME_MAIN_PATTERN}" -v test_pattern="${PLAYWRIGHT_PROFILE_PATTERN}" '
        index($0, pattern) > 0 && index($0, test_pattern) == 0 {print $1}
      '
}

test_chrome_pids() {
  ps -ax -o pid=,command= \
    | awk -v test_pattern="${PLAYWRIGHT_PROFILE_PATTERN}" '
        index($0, test_pattern) > 0 {print $1}
      '
}

singleton_lock_target() {
  local path="${CHROME_ROOT}/SingletonLock"
  if [[ -L "${path}" ]]; then
    readlink "${path}"
  fi
}

singleton_lock_pid() {
  local target
  target="$(singleton_lock_target)"
  if [[ "${target}" =~ -([0-9]+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
}

is_lock_stale() {
  local pid
  pid="$(singleton_lock_pid || true)"
  if [[ -z "${pid}" ]]; then
    return 0
  fi
  ! ps -p "${pid}" >/dev/null 2>&1
}

print_status() {
  local real_pids test_pids lock_target lock_pid
  real_pids="$(real_chrome_pids | paste -sd ',' - || true)"
  test_pids="$(test_chrome_pids | paste -sd ',' - || true)"
  lock_target="$(singleton_lock_target || true)"
  lock_pid="$(singleton_lock_pid || true)"
  echo "real_chrome_pids=${real_pids:-none}"
  echo "test_chrome_pids=${test_pids:-none}"
  echo "singleton_lock_target=${lock_target:-none}"
  echo "singleton_lock_pid=${lock_pid:-none}"
  if is_lock_stale; then
    echo "singleton_lock_state=stale_or_missing"
  else
    echo "singleton_lock_state=active"
  fi
}

cleanup() {
  local dry_run="${1:-0}"
  local test_pids
  test_pids="$(test_chrome_pids | paste -sd ' ' - || true)"
  if [[ -n "${test_pids}" ]]; then
    if [[ "${dry_run}" == "1" ]]; then
      echo "dry-run: would kill test chrome pids: ${test_pids}"
    else
      echo "kill test chrome pids: ${test_pids}"
      pkill -f "${PLAYWRIGHT_PROFILE_PATTERN}" || true
      sleep 1
    fi
  else
    echo "no test chrome residue processes"
  fi

  if [[ -n "$(real_chrome_pids | head -n 1)" ]]; then
    echo "real chrome is running; skip singleton cleanup"
    return 0
  fi

  if ! is_lock_stale; then
    echo "singleton lock still points to a live pid; skip singleton cleanup"
    return 0
  fi

  local targets=()
  local file
  for file in "${SINGLETON_FILES[@]}"; do
    if [[ -e "${CHROME_ROOT}/${file}" || -L "${CHROME_ROOT}/${file}" ]]; then
      targets+=("${CHROME_ROOT}/${file}")
    fi
  done
  if [[ "${#targets[@]}" -eq 0 ]]; then
    echo "no singleton residue files"
    return 0
  fi

  if [[ "${dry_run}" == "1" ]]; then
    printf 'dry-run: would remove singleton files: %s\n' "${targets[*]}"
  else
    printf 'remove singleton files: %s\n' "${targets[*]}"
    rm -f "${targets[@]}"
  fi
}

main() {
  local mode="${1:-status}"
  local dry_run=0
  if [[ "${mode}" == "--help" || "${mode}" == "-h" ]]; then
    usage
    return 0
  fi
  shift || true
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        dry_run=1
        ;;
      *)
        echo "未知参数：$1" >&2
        usage >&2
        return 1
        ;;
    esac
    shift
  done

  case "${mode}" in
    status)
      print_status
      ;;
    cleanup)
      cleanup "${dry_run}"
      ;;
    *)
      echo "未知模式：${mode}" >&2
      usage >&2
      return 1
      ;;
  esac
}

main "$@"
