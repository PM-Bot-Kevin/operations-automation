#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


DEFAULT_LOCAL_STATE_PATH = Path.home() / "Library/Application Support/Google/Chrome/Local State"
CHROME_APP_NAME = "Google Chrome"
PAGE_URLS = {
    "orders": "https://ark.xiaohongshu.com/app-order/order/query",
    "aftersale": "https://ark.xiaohongshu.com/app-order/aftersale/list",
}


class QianfanAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    name: str
    user_name: str
    is_last_used: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="复用本机已有 Chrome 店铺资料，重新打开小红书千帆页面。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profiles_parser = subparsers.add_parser("profiles", help="列出本机可复用的 Chrome 资料")
    profiles_parser.add_argument("--local-state-path", default=str(DEFAULT_LOCAL_STATE_PATH))

    open_parser = subparsers.add_parser("open", help="按店铺资料打开千帆页面")
    open_parser.add_argument("--store", required=True, help="店铺名、资料名或近似关键词")
    open_parser.add_argument(
        "--page",
        choices=sorted(PAGE_URLS),
        default="orders",
        help="要打开的页面，默认 orders",
    )
    open_parser.add_argument("--local-state-path", default=str(DEFAULT_LOCAL_STATE_PATH))
    open_parser.add_argument("--dry-run", action="store_true", help="只显示将要使用的资料，不真正打开浏览器")
    return parser.parse_args()


def normalize_store_text(value: str) -> str:
    text = re.sub(r"\s+", "", value)
    for fragment in ("店铺后台", "店铺", "后台", "的店", "小红书", "千帆", "店"):
        text = text.replace(fragment, "")
    return text.lower()


def load_profiles(local_state_path: Path) -> list[ChromeProfile]:
    if not local_state_path.exists():
        raise QianfanAccessError(f"找不到 Chrome Local State: {local_state_path}")

    data = json.loads(local_state_path.read_text(encoding="utf-8"))
    profile_state = data.get("profile", {})
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


def resolve_profile(profiles: list[ChromeProfile], store_query: str) -> ChromeProfile:
    if not profiles:
        raise QianfanAccessError("本机没有可用的 Chrome 资料。")

    normalized_query = normalize_store_text(store_query)
    if not normalized_query:
        raise QianfanAccessError("店铺关键词不能为空。")

    exact_matches = [
        profile
        for profile in profiles
        if normalized_query in normalize_store_text(profile.name)
        or normalized_query in normalize_store_text(profile.directory)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        names = " / ".join(profile.name or profile.directory for profile in exact_matches)
        raise QianfanAccessError(f"匹配到多个资料，请说得更具体一点：{names}")

    ranked = sorted(
        profiles,
        key=lambda profile: max(
            SequenceMatcher(None, normalized_query, normalize_store_text(profile.name)).ratio(),
            SequenceMatcher(None, normalized_query, normalize_store_text(profile.directory)).ratio(),
        ),
        reverse=True,
    )
    best = ranked[0]
    best_score = max(
        SequenceMatcher(None, normalized_query, normalize_store_text(best.name)).ratio(),
        SequenceMatcher(None, normalized_query, normalize_store_text(best.directory)).ratio(),
    )
    if best_score < 0.45:
        available = " / ".join(profile.name or profile.directory for profile in profiles)
        raise QianfanAccessError(f"没找到合适的店铺资料。当前可用资料：{available}")
    return best


def open_page(profile: ChromeProfile, page: str, dry_run: bool) -> str:
    target_url = PAGE_URLS[page]
    command = [
        "open",
        "-na",
        CHROME_APP_NAME,
        "--args",
        f"--profile-directory={profile.directory}",
        target_url,
    ]
    if dry_run:
        return " ".join(command)

    subprocess.run(command, check=True, capture_output=True, text=True)
    return target_url


def format_profile(profile: ChromeProfile) -> str:
    label = profile.name or profile.directory
    suffix = " [last_used]" if profile.is_last_used else ""
    if profile.user_name:
        return f"{profile.directory}\t{label}\t{profile.user_name}{suffix}"
    return f"{profile.directory}\t{label}{suffix}"


def main() -> int:
    args = parse_args()
    try:
        local_state_path = Path(args.local_state_path).expanduser().resolve()
        profiles = load_profiles(local_state_path)

        if args.command == "profiles":
            for profile in profiles:
                print(format_profile(profile))
            return 0

        profile = resolve_profile(profiles, args.store)
        result = open_page(profile, args.page, args.dry_run)
        print(f"已选择资料：{profile.name or profile.directory} ({profile.directory})")
        print(f"页面类型：{args.page}")
        if args.dry_run:
            print(f"将执行：{result}")
        else:
            print(f"已打开：{result}")
        return 0
    except QianfanAccessError as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"执行失败：无法打开 Chrome，退出码 {exc.returncode}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
