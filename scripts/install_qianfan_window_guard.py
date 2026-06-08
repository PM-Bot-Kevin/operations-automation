#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOCAL_STATE_PATH = Path.home() / "Library/Application Support/Google/Chrome/Local State"
CHROME_ROOT = Path.home() / "Library/Application Support/Google/Chrome"
CHROME_MAIN_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PLAYWRIGHT_PROFILE_FRAGMENT = "playwright_chromiumdev_profile-"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = (WORKSPACE_ROOT / "chrome_extensions" / "qianfan_window_guard").resolve()
EXTENSION_NAME = "Qianfan Window Guard"
EXTENSION_ID = "ecajdjejakmjipbojjnnnlgjdlbhegei"
FALLBACK_TEMPLATE = {
    "account_extension_type": 0,
    "active_permissions": {
        "api": ["alarms", "storage", "tabs"],
        "explicit_host": [],
        "manifest_permissions": [],
        "scriptable_host": [],
    },
    "commands": {"_execute_action": {"was_assigned": True}},
    "content_settings": [],
    "creation_flags": 38,
    "disable_reasons": [],
    "filtered_service_worker_events": {"windows.onRemoved": [{}]},
    "first_install_time": "13425386371478474",
    "from_webstore": False,
    "granted_permissions": {
        "api": ["alarms", "storage", "tabs"],
        "explicit_host": [],
        "manifest_permissions": [],
        "scriptable_host": [],
    },
    "has_started_service_worker": True,
    "incognito_content_settings": [],
    "incognito_preferences": {},
    "last_update_time": "13425386371478474",
    "location": 4,
    "newAllowFileAccess": True,
    "path": EXTENSION_DIR.as_posix(),
    "preferences": {},
    "regular_only_preferences": {},
    "service_worker_registration_info": {"version": "0.1.0"},
    "serviceworkerevents": ["alarms.onAlarm", "runtime.onInstalled"],
    "was_installed_by_default": False,
    "was_installed_by_oem": False,
    "withholding_permissions": False,
}


class InstallGuardError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把 Qianfan Window Guard 扩展登记到指定 Chrome profile。")
    parser.add_argument(
        "--profile-directory",
        action="append",
        required=True,
        help="目标 profile 目录，可重复传入，例如 Default / Profile 32",
    )
    parser.add_argument("--local-state-path", default=str(DEFAULT_LOCAL_STATE_PATH))
    parser.add_argument("--dry-run", action="store_true", help="只检查并输出，不真正写入")
    return parser.parse_args()


def load_local_state(local_state_path: Path) -> dict[str, Any]:
    if not local_state_path.exists():
        raise InstallGuardError(f"找不到 Chrome Local State：{local_state_path}")
    return json.loads(local_state_path.read_text(encoding="utf-8"))


def profile_name_map(local_state_path: Path) -> dict[str, str]:
    payload = load_local_state(local_state_path)
    info_cache = payload.get("profile", {}).get("info_cache", {})
    return {directory: str(raw.get("name", "")) for directory, raw in info_cache.items()}


def real_chrome_main_pids() -> list[int]:
    completed = subprocess.run(
        ["ps", "-ax", "-o", "pid=,command="],
        capture_output=True,
        text=True,
        check=True,
    )
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        if CHROME_MAIN_PATH not in line:
            continue
        if PLAYWRIGHT_PROFILE_FRAGMENT in line:
            continue
        pid_text = line.strip().split(maxsplit=1)[0]
        if pid_text.isdigit():
            pids.append(int(pid_text))
    return pids


def ensure_chrome_closed() -> None:
    pids = real_chrome_main_pids()
    if pids:
        joined = ", ".join(str(pid) for pid in pids)
        raise InstallGuardError(f"检测到真实 Chrome 仍在运行（pid: {joined}）。请先完全退出 Chrome 再安装。")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def resolve_preferences_path(profile_directory: str) -> Path:
    profile_root = CHROME_ROOT / profile_directory
    secure_path = profile_root / "Secure Preferences"
    if secure_path.exists():
        return secure_path
    preferences_path = profile_root / "Preferences"
    if preferences_path.exists():
        return preferences_path
    raise InstallGuardError(f"找不到 profile 配置文件：{profile_root}")


def find_template_entry(local_state_path: Path) -> dict[str, Any]:
    names = profile_name_map(local_state_path)
    for profile_directory in sorted(names):
        preferences_path = resolve_preferences_path(profile_directory)
        payload = load_json(preferences_path)
        settings = payload.get("extensions", {}).get("settings", {})
        for extension_id, raw in settings.items():
            path_value = str(raw.get("path", "") or "")
            manifest_name = str((raw.get("manifest") or {}).get("name", "") or "")
            if extension_id == EXTENSION_ID or path_value == EXTENSION_DIR.as_posix() or manifest_name == EXTENSION_NAME:
                template = copy.deepcopy(raw)
                template["path"] = EXTENSION_DIR.as_posix()
                template.setdefault("disable_reasons", [])
                return template
    return copy.deepcopy(FALLBACK_TEMPLATE)


def backup_preferences(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak.qianfan_window_guard.{timestamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def install_into_profile(profile_directory: str, template: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    preferences_path = resolve_preferences_path(profile_directory)
    payload = load_json(preferences_path)
    settings = payload.setdefault("extensions", {}).setdefault("settings", {})
    existing = settings.get(EXTENSION_ID)
    already_installed = isinstance(existing, dict) and str(existing.get("path", "") or "") == EXTENSION_DIR.as_posix()
    if already_installed:
        return {
            "profile_directory": profile_directory,
            "preferences_path": str(preferences_path),
            "changed": False,
            "backup_path": None,
            "reason": "already_installed",
        }

    if dry_run:
        return {
            "profile_directory": profile_directory,
            "preferences_path": str(preferences_path),
            "changed": True,
            "backup_path": None,
            "reason": "dry_run",
        }

    backup_path = backup_preferences(preferences_path)
    settings[EXTENSION_ID] = copy.deepcopy(template)
    settings[EXTENSION_ID]["path"] = EXTENSION_DIR.as_posix()
    save_json(preferences_path, payload)
    return {
        "profile_directory": profile_directory,
        "preferences_path": str(preferences_path),
        "changed": True,
        "backup_path": str(backup_path),
        "reason": "installed",
    }


def main() -> int:
    args = parse_args()
    local_state_path = Path(args.local_state_path).expanduser().resolve()
    if not EXTENSION_DIR.exists():
        raise InstallGuardError(f"找不到扩展目录：{EXTENSION_DIR}")
    ensure_chrome_closed()
    names = profile_name_map(local_state_path)
    template = find_template_entry(local_state_path)
    results = []
    for profile_directory in args.profile_directory:
        if profile_directory not in names:
            raise InstallGuardError(f"Chrome Local State 里找不到 profile：{profile_directory}")
        result = install_into_profile(profile_directory, template, args.dry_run)
        result["profile_name"] = names.get(profile_directory, "")
        results.append(result)
    print(json.dumps({"extension_id": EXTENSION_ID, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallGuardError as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
