#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_qianfan_window_guard import detect_guard
from xhs_qianfan_access import open_url_in_profile


DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "xhs_order_query_profiles.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为已配置的千帆店铺 profile 打开 Qianfan Window Guard 扩展详情页。")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="店铺 profile 配置路径，默认读取 config/xhs_order_query_profiles.json",
    )
    parser.add_argument(
        "--profile-directory",
        action="append",
        dest="profile_directories",
        default=[],
        help="只打开指定 profile，可重复传入，例如 Profile 32",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.8,
        help="依次打开多个 profile 时的间隔秒数，默认 0.8",
    )
    parser.add_argument("--dry-run", action="store_true", help="只输出将要打开的页面，不真正打开 Chrome")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser.parse_args()


def load_profile_directories(config_path: Path) -> list[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    stores = payload.get("stores", [])
    directories: list[str] = []
    seen: set[str] = set()
    for item in stores:
        if not isinstance(item, dict):
            continue
        directory = str(item.get("profile_directory", "") or "").strip()
        if not directory or directory in seen:
            continue
        directories.append(directory)
        seen.add(directory)
    return directories


def build_guard_page_url(profile_directory: str) -> tuple[str, dict[str, Any]]:
    guard = detect_guard(profile_directory)
    matches = [item for item in guard.get("matches", []) if item.get("enabled")]
    if matches:
        extension_id = str(matches[0].get("extension_id", "") or "").strip()
        if extension_id:
            return f"chrome://extensions/?id={extension_id}", guard
    return "chrome://extensions/", guard


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    if args.profile_directories:
        profile_directories = args.profile_directories
    else:
        if not config_path.exists():
            raise FileNotFoundError(f"找不到店铺 profile 配置：{config_path}")
        profile_directories = load_profile_directories(config_path)
    results: list[dict[str, Any]] = []
    for index, profile_directory in enumerate(profile_directories):
        page_url, guard = build_guard_page_url(profile_directory)
        opened = open_url_in_profile(profile_directory, page_url, dry_run=args.dry_run)
        result = {
            "profile_directory": profile_directory,
            "profile_name": guard.get("profile_name", ""),
            "guard_enabled": bool(guard.get("enabled")),
            "page_url": page_url,
            "opened": opened,
        }
        results.append(result)
        if not args.dry_run and index < len(profile_directories) - 1:
            time.sleep(max(0.0, float(args.sleep_seconds)))
    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        for item in results:
            status = "已启用" if item["guard_enabled"] else "未启用"
            print(f"{item['profile_directory']}\t{item['profile_name']}\t{status}\t{item['page_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
