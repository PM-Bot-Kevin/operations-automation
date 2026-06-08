#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LOCAL_STATE_PATH = Path.home() / "Library/Application Support/Google/Chrome/Local State"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = (WORKSPACE_ROOT / "chrome_extensions" / "qianfan_window_guard").resolve()
EXTENSION_NAME = "Qianfan Window Guard"


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    name: str
    user_name: str
    is_last_used: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查各个 Chrome profile 是否已加载 Qianfan Window Guard 扩展。")
    parser.add_argument("--local-state-path", default=str(DEFAULT_LOCAL_STATE_PATH))
    parser.add_argument("--profile-directory", help="只检查指定 profile 目录，例如 Default / Profile 32")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser.parse_args()


def load_profiles(local_state_path: Path) -> list[ChromeProfile]:
    if not local_state_path.exists():
        raise FileNotFoundError(f"找不到 Chrome Local State: {local_state_path}")
    payload = json.loads(local_state_path.read_text(encoding="utf-8"))
    profile_state = payload.get("profile", {})
    info_cache = profile_state.get("info_cache", {})
    last_used = profile_state.get("last_used")
    profiles: list[ChromeProfile] = []
    for directory, raw in sorted(info_cache.items()):
        profiles.append(
            ChromeProfile(
                directory=directory,
                name=str(raw.get("name", "")),
                user_name=str(raw.get("user_name", "")),
                is_last_used=(directory == last_used),
            )
        )
    return profiles


def load_profile_extensions(preferences_path: Path) -> list[dict[str, Any]]:
    if not preferences_path.exists():
        return []
    payload = json.loads(preferences_path.read_text(encoding="utf-8"))
    settings = payload.get("extensions", {}).get("settings", {})
    items: list[dict[str, Any]] = []
    for extension_id, raw in settings.items():
        path_value = str(raw.get("path", "") or "")
        manifest = raw.get("manifest") or load_manifest_from_path(path_value)
        items.append(
            {
                "extension_id": extension_id,
                "name": str(manifest.get("name", "") or ""),
                "path": path_value,
                "state": raw.get("state"),
                "location": raw.get("location"),
                "disable_reasons": raw.get("disable_reasons"),
            }
        )
    return items


def load_manifest_from_path(path_value: str) -> dict[str, Any]:
    if not path_value:
        return {}
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        return {}
    manifest_path = candidate / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def normalize_absolute_path(path_value: str) -> str:
    if not path_value:
        return ""
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        return ""
    try:
        return candidate.resolve().as_posix()
    except OSError:
        return candidate.as_posix()


def is_enabled_extension(item: dict[str, Any]) -> bool:
    state = item.get("state")
    if state is not None:
        return state == 1
    disable_reasons = item.get("disable_reasons")
    if isinstance(disable_reasons, list) and disable_reasons:
        return False
    # Chrome often leaves unpacked extensions without an explicit "state" field in
    # Secure Preferences. If the local path still exists and there is no disable
    # reason, treat it as enabled.
    return True


def load_browser_js_allowed(preferences_path: Path) -> bool | None:
    if not preferences_path.exists():
        return None
    payload = json.loads(preferences_path.read_text(encoding="utf-8"))
    browser_value = payload.get("browser", {}).get("allow_javascript_apple_events")
    if isinstance(browser_value, bool):
        return browser_value
    account_browser_value = payload.get("account_values", {}).get("browser", {}).get("allow_javascript_apple_events")
    if isinstance(account_browser_value, bool):
        return account_browser_value
    return None


def detect_guard(profile_directory: str) -> dict[str, Any]:
    profile_root = Path.home() / "Library/Application Support/Google/Chrome" / profile_directory
    preferences_path = profile_root / "Secure Preferences"
    if not preferences_path.exists():
        preferences_path = profile_root / "Preferences"
    browser_preferences_path = profile_root / "Preferences"
    extensions = load_profile_extensions(preferences_path)
    browser_js_allowed = load_browser_js_allowed(browser_preferences_path)
    normalized_extension_dir = EXTENSION_DIR.as_posix()
    matches = []
    for item in extensions:
        item_path = str(item.get("path", "") or "")
        normalized_item_path = normalize_absolute_path(item_path) or item_path
        path_matches = bool(normalized_item_path) and normalized_item_path == normalized_extension_dir
        name_matches = item.get("name") == EXTENSION_NAME
        location = item.get("location")
        real_manifest_name = load_manifest_from_path(item_path).get("name", "") if item_path.startswith("/") else ""
        compatible_unpacked_path = (
            bool(normalize_absolute_path(item_path))
            and Path(normalize_absolute_path(item_path)).exists()
            and location == 4
            and real_manifest_name == EXTENSION_NAME
        )
        if not path_matches and not name_matches and not compatible_unpacked_path:
            continue
        if normalized_item_path and not path_matches and not compatible_unpacked_path and item_path.startswith("/"):
            continue
        matches.append(
            {
                **item,
                "path": normalized_item_path or item_path,
                "enabled": is_enabled_extension(item),
                "path_matches_workspace": path_matches,
                "compatible_unpacked_path": compatible_unpacked_path,
            }
        )
    installed = bool(matches)
    enabled = any(item.get("enabled") for item in matches)
    return {
      "profile_directory": profile_directory,
      "preferences_path": str(preferences_path),
      "extension_dir": normalized_extension_dir,
      "installed": installed,
      "enabled": enabled,
      "browser_js_allowed": browser_js_allowed,
      "matches": matches,
    }


def main() -> int:
    args = parse_args()
    local_state_path = Path(args.local_state_path).expanduser().resolve()
    profiles = load_profiles(local_state_path)
    if args.profile_directory:
        profiles = [profile for profile in profiles if profile.directory == args.profile_directory]
    results = []
    for profile in profiles:
        result = detect_guard(profile.directory)
        result["profile_name"] = profile.name
        results.append(result)
    payload = {
        "extension_name": EXTENSION_NAME,
        "extension_dir": EXTENSION_DIR.as_posix(),
        "profiles": results,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in results:
            status = "已安装并启用" if item["enabled"] else ("已安装未启用" if item["installed"] else "未安装")
            browser_js_status = (
                "已开启 Apple 事件 JS"
                if item["browser_js_allowed"] is True
                else ("未开启 Apple 事件 JS" if item["browser_js_allowed"] is False else "Apple 事件 JS 未知")
            )
            print(f"{item['profile_directory']}\t{item['profile_name']}\t{status}\t{browser_js_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
