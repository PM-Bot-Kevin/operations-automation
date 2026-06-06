#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import json
import re
import subprocess
import sys
import time
from collections import deque
from ctypes import byref, c_char_p, c_double, c_int32, c_uint32, c_void_p
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from xhs_qianfan_overlay_guard import (
    OVERLAY_HINT_TEXTS,
    SAFE_DISMISS_BUTTON_TEXTS,
    UNSAFE_CONFIRM_BUTTON_TEXTS,
    build_dismiss_front_window_obstructions_script,
    dismiss_window_obstructions_via_ax as shared_dismiss_window_obstructions_via_ax,
    normalize_action_label as shared_normalize_action_label,
    snapshot_text_pool as shared_snapshot_text_pool,
)


DEFAULT_LOCAL_STATE_PATH = Path.home() / "Library/Application Support/Google/Chrome/Local State"
CHROME_APP_NAME = "Google Chrome"
CHROME_BINARY_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PAGE_URLS = {
    "orders": "https://ark.xiaohongshu.com/app-order/order/query",
    "aftersale": "https://ark.xiaohongshu.com/app-order/aftersale/list",
    "comments": "https://ark.xiaohongshu.com/app-item/comment/analysis",
}
CORE_FOUNDATION_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
APPLICATION_SERVICES_PATH = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
CF_STRING_ENCODING_UTF8 = 0x08000100
AX_POSITION_VALUE_TYPE = 1
AX_SIZE_VALUE_TYPE = 2
AX_CHILDREN_LIMIT = 80
AX_MAX_DEPTH = 26
AX_MAX_NODES = 1800
AX_INTERESTING_ROLES = {
    "AXButton",
    "AXGroup",
    "AXHeading",
    "AXLink",
    "AXPopUpButton",
    "AXRadioButton",
    "AXStaticText",
    "AXTextField",
    "AXWebArea",
}
AX_SKIP_SUBTREE_ROLES = {"AXImage"}
_PREFERRED_WINDOW_PID: int | None = None
_PREFERRED_WINDOW_POINTER: int | None = None

CFTypeRef = c_void_p
CFStringRef = c_void_p
AXUIElementRef = c_void_p

_CORE_FOUNDATION = ctypes.cdll.LoadLibrary(CORE_FOUNDATION_PATH)
_APPLICATION_SERVICES = ctypes.cdll.LoadLibrary(APPLICATION_SERVICES_PATH)

_CORE_FOUNDATION.CFStringCreateWithCString.restype = CFStringRef
_CORE_FOUNDATION.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
_CORE_FOUNDATION.CFGetTypeID.argtypes = [CFTypeRef]
_CORE_FOUNDATION.CFGetTypeID.restype = c_uint32
_CORE_FOUNDATION.CFStringGetTypeID.restype = c_uint32
_CORE_FOUNDATION.CFArrayGetCount.argtypes = [CFTypeRef]
_CORE_FOUNDATION.CFArrayGetCount.restype = c_int32
_CORE_FOUNDATION.CFArrayGetValueAtIndex.argtypes = [CFTypeRef, c_int32]
_CORE_FOUNDATION.CFArrayGetValueAtIndex.restype = c_void_p
_CORE_FOUNDATION.CFStringGetLength.argtypes = [CFStringRef]
_CORE_FOUNDATION.CFStringGetLength.restype = c_int32
_CORE_FOUNDATION.CFStringGetMaximumSizeForEncoding.argtypes = [c_int32, c_uint32]
_CORE_FOUNDATION.CFStringGetMaximumSizeForEncoding.restype = c_int32
_CORE_FOUNDATION.CFStringGetCString.argtypes = [CFStringRef, c_char_p, c_int32, c_uint32]
_CORE_FOUNDATION.CFStringGetCString.restype = ctypes.c_bool

_APPLICATION_SERVICES.AXUIElementCreateApplication.argtypes = [c_int32]
_APPLICATION_SERVICES.AXUIElementCreateApplication.restype = AXUIElementRef
_APPLICATION_SERVICES.AXUIElementCopyAttributeValue.argtypes = [AXUIElementRef, CFStringRef, ctypes.POINTER(CFTypeRef)]
_APPLICATION_SERVICES.AXUIElementCopyAttributeValue.restype = c_int32
_APPLICATION_SERVICES.AXUIElementPerformAction.argtypes = [AXUIElementRef, CFStringRef]
_APPLICATION_SERVICES.AXUIElementPerformAction.restype = c_int32
_APPLICATION_SERVICES.AXUIElementSetAttributeValue.argtypes = [AXUIElementRef, CFStringRef, CFTypeRef]
_APPLICATION_SERVICES.AXUIElementSetAttributeValue.restype = c_int32
_APPLICATION_SERVICES.AXValueGetType.argtypes = [CFTypeRef]
_APPLICATION_SERVICES.AXValueGetType.restype = c_uint32
_APPLICATION_SERVICES.AXValueGetValue.argtypes = [CFTypeRef, c_uint32, c_void_p]
_APPLICATION_SERVICES.AXValueGetValue.restype = ctypes.c_bool


class CGPoint(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class QianfanAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    name: str
    user_name: str
    is_last_used: bool


@dataclass(frozen=True)
class ChromeUiElement:
    index: int
    role: str
    title: str
    description: str
    value: str
    position: tuple[int, int] | None
    size: tuple[int, int] | None


@dataclass
class ChromeTaskSession:
    target_url_contains: str
    previous_window_ids: set[int] | None
    app_name: str = CHROME_APP_NAME
    binding: dict[str, Any] | None = None


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
        CHROME_BINARY_PATH,
        f"--profile-directory={profile.directory}",
        "--new-window",
        target_url,
    ]
    if dry_run:
        return " ".join(command)

    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return target_url


def _run_osascript(lines: list[str], args: list[str] | None = None) -> str:
    command = ["osascript", "-l", "AppleScript"]
    for line in lines:
        command.extend(["-e", line])
    if args:
        command.extend(args)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "osascript 执行失败"
        raise QianfanAccessError(message)
    return completed.stdout.rstrip("\n")


def run_front_window_javascript(script: str, app_name: str = CHROME_APP_NAME) -> str:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持 {CHROME_APP_NAME} 前台页内执行，不支持：{app_name}")
    return _run_osascript(
        [
            "on run argv",
            "set jsCode to item 1 of argv",
            f'tell application "{CHROME_APP_NAME}"',
            'if (count of windows) is 0 then error "应用没有可见窗口"',
            "return execute active tab of front window javascript jsCode",
            "end tell",
            "end run",
        ],
        [script],
    )


def dismiss_front_window_obstructions(app_name: str = CHROME_APP_NAME) -> dict[str, Any]:
    raw_output = run_front_window_javascript(build_dismiss_front_window_obstructions_script(), app_name=app_name)
    try:
        payload = json.loads(raw_output or "{}")
    except json.JSONDecodeError as exc:
        raise QianfanAccessError(f"无法解析前台页面蒙层处理结果：{raw_output[:200]}") from exc
    if not payload.get("ok", False):
        detail = str(payload.get("error", "")).strip() or "未知错误"
        raise QianfanAccessError(f"处理前台页面蒙层失败：{detail}")
    return payload


def _normalize_action_label(value: str) -> str:
    return shared_normalize_action_label(value)


def _window_snapshot_text_pool(snapshot: dict[str, Any]) -> str:
    return shared_snapshot_text_pool(snapshot)


def dismiss_window_obstructions_via_ax(snapshot: dict[str, Any]) -> dict[str, Any]:
    return shared_dismiss_window_obstructions_via_ax(
        snapshot,
        raise_window=raise_window,
        press_front_window_element=press_front_window_element,
    )


def close_front_window(app_name: str = CHROME_APP_NAME) -> None:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持关闭 {CHROME_APP_NAME} 前台窗口，不支持：{app_name}")
    _run_osascript(
        [
            f'tell application "{CHROME_APP_NAME}"',
            'if (count of windows) is 0 then error "应用没有可见窗口"',
            "close front window",
            "end tell",
        ],
    )


def list_window_descriptors(app_name: str = CHROME_APP_NAME) -> list[dict[str, Any]]:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持读取 {CHROME_APP_NAME} 窗口，不支持：{app_name}")
    raw_output = _run_osascript(
        [
            f'tell application "{CHROME_APP_NAME}"',
            "set outputLines to {}",
            "repeat with windowIndex from 1 to count of windows",
            "set currentWindow to window windowIndex",
            'set currentUrl to ""',
            'set currentTitle to ""',
            "try",
            "set currentUrl to URL of active tab of currentWindow",
            "end try",
            "try",
            "set currentTitle to title of active tab of currentWindow",
            "end try",
            'set end of outputLines to ((id of currentWindow as text) & (ASCII character 9) & currentUrl & (ASCII character 9) & currentTitle)',
            "end repeat",
            "set previousDelimiters to AppleScript's text item delimiters",
            "set AppleScript's text item delimiters to linefeed",
            "set outputText to outputLines as text",
            "set AppleScript's text item delimiters to previousDelimiters",
            "return outputText",
            "end tell",
        ],
    )
    descriptors: list[dict[str, Any]] = []
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        window_id_text, _, active_url = line.partition("\t")
        active_url, _, window_title = active_url.partition("\t")
        window_id_text = window_id_text.strip()
        if not window_id_text.isdigit():
            continue
        descriptors.append(
            {
                "window_id": int(window_id_text),
                "active_url": active_url.strip(),
                "window_title": window_title.strip(),
            }
        )
    return descriptors


def close_window_by_id(window_id: int, app_name: str = CHROME_APP_NAME) -> int:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持关闭 {CHROME_APP_NAME} 窗口，不支持：{app_name}")
    if window_id <= 0:
        raise QianfanAccessError("关闭窗口时 window_id 必须是正整数。")
    return int(
        _run_osascript(
            [
                "on run argv",
                "set targetWindowId to (item 1 of argv) as integer",
                f'tell application "{CHROME_APP_NAME}"',
                "close (first window whose id is targetWindowId)",
                "return targetWindowId as text",
                "end tell",
                "end run",
            ],
            [str(window_id)],
        )
    )


def close_window_by_url(url_contains: str, app_name: str = CHROME_APP_NAME, prefer_last: bool = True) -> str:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持关闭 {CHROME_APP_NAME} 窗口，不支持：{app_name}")
    if not url_contains:
        raise QianfanAccessError("关闭窗口时 url_contains 不能为空。")
    return _run_osascript(
        [
            "on run argv",
            "set targetUrl to item 1 of argv",
            "set preferLast to (item 2 of argv) is \"1\"",
            f'tell application "{CHROME_APP_NAME}"',
            "if preferLast then",
            "repeat with windowIndex from (count of windows) to 1 by -1",
            "set currentWindow to window windowIndex",
            "repeat with tabIndex from 1 to count of tabs of currentWindow",
            "set currentTab to tab tabIndex of currentWindow",
            "set currentUrl to URL of currentTab",
            "if currentUrl contains targetUrl then",
            "close currentWindow",
            "return currentUrl",
            "end if",
            "end repeat",
            "end repeat",
            "else",
            "repeat with windowIndex from 1 to count of windows",
            "set currentWindow to window windowIndex",
            "repeat with tabIndex from 1 to count of tabs of currentWindow",
            "set currentTab to tab tabIndex of currentWindow",
            "set currentUrl to URL of currentTab",
            "if currentUrl contains targetUrl then",
            "close currentWindow",
            "return currentUrl",
            "end if",
            "end repeat",
            "end repeat",
            "end if",
            'error "没有找到匹配目标地址的 Chrome 窗口"',
            "end tell",
            "end run",
        ],
        [url_contains, "1" if prefer_last else "0"],
    )


def snapshot_window_ids_optional(app_name: str = CHROME_APP_NAME) -> set[int] | None:
    try:
        descriptors = list_window_descriptors(app_name)
    except Exception:
        return None
    return {int(item["window_id"]) for item in descriptors}


def _snapshot_key(snapshot: dict[str, Any]) -> tuple[int, int]:
    return (
        int(snapshot.get("pid", 0) or 0),
        int(snapshot.get("window_pointer", 0) or 0),
    )


def _snapshot_identity(snapshot: dict[str, Any]) -> str:
    pid, pointer = _snapshot_key(snapshot)
    return f"{pid}:{pointer}"


def _snapshot_signature(snapshot: dict[str, Any]) -> tuple[str, str]:
    return (
        str(snapshot.get("window_title", "") or "").strip(),
        str(snapshot.get("active_url", "") or "").strip(),
    )


def snapshot_window_keys_optional(app_name: str = CHROME_APP_NAME) -> set[tuple[str, str]] | None:
    try:
        snapshots = list_window_snapshots(app_name)
    except Exception:
        return None
    return {_snapshot_signature(snapshot) for snapshot in snapshots if any(_snapshot_signature(snapshot))}


def start_chrome_task_session(
    target_url_contains: str,
    *,
    app_name: str = CHROME_APP_NAME,
) -> ChromeTaskSession:
    return ChromeTaskSession(
        target_url_contains=target_url_contains,
        previous_window_ids=snapshot_window_keys_optional(app_name),
        app_name=app_name,
    )


def bind_chrome_task_session(
    session: ChromeTaskSession,
    snapshot: dict[str, Any],
    *,
    title_hint: str = "",
    log_step: Callable[[str], None] | None = None,
) -> ChromeTaskSession:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    previous_window_ids = session.previous_window_ids
    if previous_window_ids is None:
        emit("任务前窗口快照缺失，无法稳定绑定本轮新开窗口，收尾时将回退到窗口差异兜底")
        return session

    try:
        snapshots = list_window_snapshots(session.app_name)
    except Exception as exc:
        emit(f"读取窗口快照失败，暂不绑定本轮窗口：{exc}")
        return session

    candidates = [
        item
        for item in snapshots
        if _snapshot_signature(item) not in previous_window_ids
        and session.target_url_contains in str(item.get("active_url", ""))
    ]
    snapshot_title = str(snapshot.get("window_title", "") or "").strip()
    direct_match = next(
        (
            item
            for item in candidates
            if _snapshot_signature(item) == _snapshot_signature(snapshot)
        ),
        None,
    )
    if direct_match is not None:
        candidates = [direct_match]
    elif snapshot_title:
        titled = [item for item in candidates if str(item.get("window_title", "")).strip() == snapshot_title]
        if len(titled) == 1:
            candidates = titled
    if len(candidates) != 1:
        emit("未能唯一绑定本轮新开窗口，收尾时将回退到窗口差异兜底")
        return session

    candidate = candidates[0]
    session.binding = {
        "window_id": None,
        "pid": int(candidate.get("pid", 0) or 0),
        "window_pointer": int(candidate.get("window_pointer", 0) or 0),
        "window_title": str(candidate.get("window_title", "") or ""),
        "active_url": str(candidate.get("active_url", "") or ""),
        "target_url_contains": session.target_url_contains,
        "title_hint": title_hint.strip(),
        "signature": _snapshot_signature(candidate),
        "binding_target": _snapshot_identity(candidate),
    }
    emit(f"已绑定本轮任务窗口：{session.binding['binding_target']}")
    return session


def _binding_matches_snapshot(binding: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    current_url = str(snapshot.get("active_url", "") or "")
    if str(binding.get("target_url_contains", "")).strip() not in current_url:
        return False
    title_hint = str(binding.get("title_hint", "") or "").strip()
    if not title_hint:
        return True
    text_pool = _window_snapshot_text_pool(snapshot)
    window_title = str(snapshot.get("window_title", "") or "")
    return title_hint in window_title or title_hint in text_pool


def _find_snapshot_for_binding(binding: dict[str, Any], app_name: str = CHROME_APP_NAME) -> dict[str, Any] | None:
    target_signature = binding.get("signature")
    for snapshot in list_window_snapshots(app_name):
        if _snapshot_signature(snapshot) == target_signature:
            return snapshot
    return None


def close_chrome_task_session(
    session: ChromeTaskSession,
    *,
    log_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    binding = session.binding
    if binding is not None:
        try:
            snapshot = _find_snapshot_for_binding(binding, session.app_name)
            if snapshot is None:
                emit("本轮绑定窗口已不存在，视为已收尾")
                return {
                    "ok": True,
                    "skipped": False,
                    "reason": "binding_missing",
                    "strategy": "binding",
                    "closed_window_ids": [],
                    "remaining_window_ids": [],
                    "closed_targets": [],
                    "remaining_targets": [],
                    "binding_window_id": binding.get("window_id"),
                }
            if not _binding_matches_snapshot(binding, snapshot):
                emit("本轮绑定窗口已偏离目标页或疑似被用户接管，本轮不强关")
                return {
                    "ok": False,
                    "skipped": True,
                    "reason": "ownership_lost",
                    "strategy": "binding",
                    "closed_window_ids": [],
                    "remaining_window_ids": [],
                    "closed_targets": [],
                    "remaining_targets": [_snapshot_identity(snapshot)],
                    "binding_window_id": binding.get("window_id"),
                }
            raise_window(snapshot)
            close_front_window_via_ax(session.app_name)
            emit(f"已关闭本轮绑定窗口：{binding.get('binding_target') or _snapshot_identity(snapshot)}")
            return {
                "ok": True,
                "skipped": False,
                "reason": "",
                "strategy": "binding",
                "closed_window_ids": [],
                "remaining_window_ids": [],
                "closed_targets": [binding.get("binding_target") or _snapshot_identity(snapshot)],
                "remaining_targets": [],
                "binding_window_id": binding.get("window_id"),
            }
        except Exception as exc:
            emit(f"本轮绑定窗口关闭失败，回退到窗口差异兜底：{exc}")
            fallback = close_new_windows_for_url_ax(
                session.previous_window_ids,
                target_url_contains=session.target_url_contains,
                log_step=log_step,
                app_name=session.app_name,
            )
            fallback["strategy"] = "window_diff_fallback"
            fallback["binding_window_id"] = binding.get("window_id")
            return fallback

    fallback = close_new_windows_for_url_ax(
        session.previous_window_ids,
        target_url_contains=session.target_url_contains,
        log_step=log_step,
        app_name=session.app_name,
    )
    fallback["strategy"] = "window_diff"
    fallback["binding_window_id"] = None
    return fallback


def close_new_windows_for_url_ax(
    previous_window_keys: set[tuple[str, str]] | None,
    *,
    target_url_contains: str,
    log_step: Callable[[str], None] | None = None,
    app_name: str = CHROME_APP_NAME,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    if previous_window_keys is None:
        emit("任务前窗口快照缺失，本轮不做盲关，避免误关用户原窗口")
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing_previous_snapshot",
            "closed_window_ids": [],
            "remaining_window_ids": [],
            "closed_targets": [],
            "remaining_targets": [],
        }

    last_error: Exception | None = None
    closed_targets: list[str] = []
    remaining_targets: list[str] = []
    try:
        current_snapshots = list_window_snapshots(app_name)
        candidates = [
            snapshot
            for snapshot in current_snapshots
            if _snapshot_signature(snapshot) not in previous_window_keys
            and target_url_contains in str(snapshot.get("active_url", ""))
        ]
        for snapshot in reversed(candidates):
            raise_window(snapshot)
            close_front_window_via_ax(app_name)
            closed_targets.append(_snapshot_identity(snapshot))
            emit(f"已关闭本轮任务窗口：{_snapshot_identity(snapshot)}")

        current_snapshots = list_window_snapshots(app_name)
        remaining_targets = [
            _snapshot_identity(snapshot)
            for snapshot in current_snapshots
            if _snapshot_signature(snapshot) not in previous_window_keys
            and target_url_contains in str(snapshot.get("active_url", ""))
        ]
        if not remaining_targets:
            return {
                "ok": True,
                "skipped": False,
                "reason": "",
                "closed_window_ids": [],
                "remaining_window_ids": [],
                "closed_targets": closed_targets,
                "remaining_targets": [],
            }
    except Exception as exc:
        last_error = exc
        current_snapshots = []
        try:
            current_snapshots = list_window_snapshots(app_name)
        except Exception:
            current_snapshots = []
        remaining_targets = [
            _snapshot_identity(snapshot)
            for snapshot in current_snapshots
            if _snapshot_signature(snapshot) not in previous_window_keys
            and target_url_contains in str(snapshot.get("active_url", ""))
        ]

    detail = ""
    if remaining_targets:
        detail = f"，仍残留窗口: {remaining_targets}"
    emit(f"任务窗口收尾关闭失败，忽略：{last_error}{detail}")
    return {
        "ok": False,
        "skipped": False,
        "reason": "close_failed",
        "closed_window_ids": [],
        "remaining_window_ids": [],
        "closed_targets": closed_targets,
        "remaining_targets": remaining_targets,
        "error": str(last_error) if last_error else "",
    }


def close_new_windows_for_url(
    previous_window_ids: set[int] | None,
    *,
    target_url_contains: str,
    log_step: Callable[[str], None] | None = None,
    app_name: str = CHROME_APP_NAME,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    if previous_window_ids is None:
        emit("任务前窗口快照缺失，本轮不做盲关，避免误关用户原窗口")
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing_previous_snapshot",
            "closed_window_ids": [],
            "remaining_window_ids": [],
        }

    last_error: Exception | None = None
    closed_window_ids: list[int] = []
    remaining_window_ids: list[int] = []
    try:
        current_descriptors = list_window_descriptors(app_name)
        candidate_ids = [
            int(item["window_id"])
            for item in current_descriptors
            if int(item["window_id"]) not in previous_window_ids
            and target_url_contains in str(item.get("active_url", ""))
        ]
        for window_id in sorted(candidate_ids, reverse=True):
            close_window_by_id(window_id, app_name=app_name)
            closed_window_ids.append(window_id)
            emit(f"已关闭本轮任务窗口：{window_id}")

        current_descriptors = list_window_descriptors(app_name)
        remaining_window_ids = [
            int(item["window_id"])
            for item in current_descriptors
            if int(item["window_id"]) not in previous_window_ids
            and target_url_contains in str(item.get("active_url", ""))
        ]
        if not remaining_window_ids:
            return {
                "ok": True,
                "skipped": False,
                "reason": "",
                "closed_window_ids": closed_window_ids,
                "remaining_window_ids": [],
            }
    except Exception as exc:
        last_error = exc
        current_descriptors = []
        try:
            current_descriptors = list_window_descriptors(app_name)
        except Exception:
            current_descriptors = []
        remaining_window_ids = [
            int(item["window_id"])
            for item in current_descriptors
            if int(item["window_id"]) not in previous_window_ids
            and target_url_contains in str(item.get("active_url", ""))
        ]

    detail = ""
    if remaining_window_ids:
        detail = f"，仍残留窗口: {sorted(remaining_window_ids)}"
    emit(f"任务窗口收尾关闭失败，忽略：{last_error}{detail}")
    return {
        "ok": False,
        "skipped": False,
        "reason": "close_failed",
        "closed_window_ids": closed_window_ids,
        "remaining_window_ids": sorted(remaining_window_ids),
        "error": str(last_error) if last_error else "",
    }


def focus_window_by_url(url_contains: str, app_name: str = CHROME_APP_NAME) -> str:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持聚焦 {CHROME_APP_NAME} 窗口，不支持：{app_name}")
    if not url_contains:
        raise QianfanAccessError("聚焦窗口时 url_contains 不能为空。")
    return _run_osascript(
        [
            "on run argv",
            "set targetUrl to item 1 of argv",
            f'tell application "{CHROME_APP_NAME}"',
            "activate",
            "repeat with windowIndex from 1 to count of windows",
            "set currentWindow to window windowIndex",
            "repeat with tabIndex from 1 to count of tabs of currentWindow",
            "set currentTab to tab tabIndex of currentWindow",
            "set currentUrl to URL of currentTab",
            "if currentUrl contains targetUrl then",
            "set active tab index of currentWindow to tabIndex",
            "set index of currentWindow to 1",
            "return currentUrl",
            "end if",
            "end repeat",
            "end repeat",
            'error "没有找到匹配目标地址的 Chrome 窗口"',
            "end tell",
            "end run",
        ],
        [url_contains],
    )


def focus_window_by_url_ax(url_contains: str, app_name: str = CHROME_APP_NAME) -> dict[str, Any]:
    if not url_contains:
        raise QianfanAccessError("聚焦窗口时 url_contains 不能为空。")
    normalized_expected_url = url_contains.replace("https://", "").replace("http://", "")
    for snapshot in list_window_snapshots(app_name):
        elements: list[ChromeUiElement] = snapshot["elements"]
        address_bars = [
            element
            for element in elements
            if element.role == "AXTextField" and element.description == "地址和搜索栏"
        ]
        current_url = address_bars[0].value if address_bars else ""
        normalized_current_url = current_url.replace("https://", "").replace("http://", "")
        if normalized_expected_url and normalized_expected_url not in normalized_current_url:
            continue
        raise_window(snapshot)
        return snapshot
    raise QianfanAccessError("没有找到匹配目标地址的 Chrome 窗口")


def _cf_string(text: str) -> CFStringRef:
    return _CORE_FOUNDATION.CFStringCreateWithCString(None, text.encode("utf-8"), CF_STRING_ENCODING_UTF8)


def _cf_string_to_text(value: CFTypeRef | None) -> str:
    if not value:
        return ""
    if _CORE_FOUNDATION.CFGetTypeID(value) != _CORE_FOUNDATION.CFStringGetTypeID():
        return ""
    length = _CORE_FOUNDATION.CFStringGetLength(value)
    size = _CORE_FOUNDATION.CFStringGetMaximumSizeForEncoding(length, CF_STRING_ENCODING_UTF8) + 1
    buffer = ctypes.create_string_buffer(size)
    if not _CORE_FOUNDATION.CFStringGetCString(value, buffer, size, CF_STRING_ENCODING_UTF8):
        return ""
    return buffer.value.decode("utf-8", errors="ignore")


def _copy_attribute(element: AXUIElementRef, attribute_name: str) -> CFTypeRef | None:
    attribute = _cf_string(attribute_name)
    output = CFTypeRef()
    error_code = _APPLICATION_SERVICES.AXUIElementCopyAttributeValue(element, attribute, byref(output))
    if error_code != 0 or not output:
        return None
    return output


def _copy_children(element: AXUIElementRef) -> list[AXUIElementRef]:
    raw_children = _copy_attribute(element, "AXChildren")
    if not raw_children:
        return []
    child_count = _CORE_FOUNDATION.CFArrayGetCount(raw_children)
    return [
        c_void_p(_CORE_FOUNDATION.CFArrayGetValueAtIndex(raw_children, index))
        for index in range(min(child_count, AX_CHILDREN_LIMIT))
    ]


def _copy_text_attribute(element: AXUIElementRef, attribute_name: str) -> str:
    return _cf_string_to_text(_copy_attribute(element, attribute_name))


def _copy_point_like_attribute(element: AXUIElementRef, attribute_name: str) -> tuple[int, int] | None:
    raw_value = _copy_attribute(element, attribute_name)
    if not raw_value:
        return None

    value_type = _APPLICATION_SERVICES.AXValueGetType(raw_value)
    if attribute_name == "AXPosition" and value_type == AX_POSITION_VALUE_TYPE:
        point = CGPoint()
        if _APPLICATION_SERVICES.AXValueGetValue(raw_value, value_type, byref(point)):
            return round(point.x), round(point.y)
    if attribute_name == "AXSize" and value_type == AX_SIZE_VALUE_TYPE:
        size = CGSize()
        if _APPLICATION_SERVICES.AXValueGetValue(raw_value, value_type, byref(size)):
            return round(size.width), round(size.height)
    return None


def _window_pointer(window_ref: AXUIElementRef | None) -> int:
    if not window_ref:
        return 0
    return int(window_ref.value or 0)


def _set_preferred_window(pid: int | None, window_pointer: int | None) -> None:
    global _PREFERRED_WINDOW_PID, _PREFERRED_WINDOW_POINTER
    _PREFERRED_WINDOW_PID = pid if pid and pid > 0 else None
    _PREFERRED_WINDOW_POINTER = window_pointer if window_pointer and window_pointer > 0 else None


def _find_chrome_pids(app_name: str) -> list[int]:
    completed = subprocess.run(
        ["pgrep", "-x", app_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise QianfanAccessError(f"找不到应用：{app_name}")
    pids: list[int] = []
    for raw_line in completed.stdout.splitlines():
        candidate = raw_line.strip()
        if candidate.isdigit():
            pids.append(int(candidate))
    if pids:
        return pids
    raise QianfanAccessError(f"找不到应用进程号：{app_name}")


def _window_refs_for_pid(pid: int) -> list[AXUIElementRef]:
    app_ref = _APPLICATION_SERVICES.AXUIElementCreateApplication(pid)
    if not app_ref:
        return []

    windows: list[AXUIElementRef] = []
    seen_pointers: set[int] = set()

    focused_window = _copy_attribute(app_ref, "AXFocusedWindow")
    focused_pointer = _window_pointer(focused_window)
    if focused_pointer:
        windows.append(focused_window)
        seen_pointers.add(focused_pointer)

    raw_windows = _copy_attribute(app_ref, "AXWindows")
    if raw_windows and _CORE_FOUNDATION.CFArrayGetCount(raw_windows) > 0:
        for index in range(_CORE_FOUNDATION.CFArrayGetCount(raw_windows)):
            window_ref = c_void_p(_CORE_FOUNDATION.CFArrayGetValueAtIndex(raw_windows, index))
            pointer = _window_pointer(window_ref)
            if not pointer or pointer in seen_pointers:
                continue
            windows.append(window_ref)
            seen_pointers.add(pointer)
    return windows


def _front_window_reference(app_name: str) -> AXUIElementRef:
    pids = _find_chrome_pids(app_name)

    preferred_pid = _PREFERRED_WINDOW_PID
    preferred_pointer = _PREFERRED_WINDOW_POINTER
    ordered_pids = list(pids)
    if preferred_pid in ordered_pids:
        ordered_pids.remove(preferred_pid)
        ordered_pids.insert(0, preferred_pid)

    first_available_window: AXUIElementRef | None = None
    for pid in ordered_pids:
        window_refs = _window_refs_for_pid(pid)
        if not window_refs:
            continue
        if first_available_window is None:
            first_available_window = window_refs[0]
        if preferred_pid == pid and preferred_pointer:
            for window_ref in window_refs:
                if _window_pointer(window_ref) == preferred_pointer:
                    return window_ref
        if preferred_pid == pid and preferred_pointer is None:
            return window_refs[0]

    if first_available_window is not None:
        return first_available_window
    raise QianfanAccessError(f"应用没有可见窗口：{app_name}")


def _window_snapshot_from_ref(pid: int, window_ref: AXUIElementRef, app_name: str = CHROME_APP_NAME) -> dict[str, Any]:
    window_title = _copy_text_attribute(window_ref, "AXTitle")
    elements = _collect_window_elements(window_ref)
    address_bars = [
        element
        for element in elements
        if element.role == "AXTextField" and element.description == "地址和搜索栏"
    ]
    active_url = address_bars[0].value if address_bars else ""
    return {
        "app_name": app_name,
        "pid": pid,
        "window_pointer": _window_pointer(window_ref),
        "window_title": window_title,
        "active_url": active_url,
        "elements": elements,
    }


def list_window_snapshots(app_name: str = CHROME_APP_NAME) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    preferred_pid = _PREFERRED_WINDOW_PID
    pids = _find_chrome_pids(app_name)
    ordered_pids = list(pids)
    if preferred_pid in ordered_pids:
        ordered_pids.remove(preferred_pid)
        ordered_pids.insert(0, preferred_pid)

    for pid in ordered_pids:
        for window_ref in _window_refs_for_pid(pid):
            snapshots.append(_window_snapshot_from_ref(pid, window_ref, app_name))
    return snapshots


def raise_window(snapshot: dict[str, Any]) -> None:
    pid = int(snapshot.get("pid", 0) or 0)
    pointer = int(snapshot.get("window_pointer", 0) or 0)
    window_title = str(snapshot.get("window_title", "") or "")
    active_url = str(snapshot.get("active_url", "") or "")
    if pid <= 0 or pointer <= 0:
        raise QianfanAccessError("缺少窗口定位信息，无法聚焦目标窗口。")
    fallback_ref: AXUIElementRef | None = None
    for window_ref in _window_refs_for_pid(pid):
        if _window_pointer(window_ref) != pointer:
            if fallback_ref is None:
                candidate_snapshot = _window_snapshot_from_ref(pid, window_ref)
                if candidate_snapshot["window_title"] == window_title and candidate_snapshot["active_url"] == active_url:
                    fallback_ref = window_ref
            continue
        action = _cf_string("AXRaise")
        error_code = _APPLICATION_SERVICES.AXUIElementPerformAction(window_ref, action)
        if error_code != 0:
            raise QianfanAccessError(f"聚焦目标窗口失败，错误码：{error_code}")
        _set_preferred_window(pid, _window_pointer(window_ref))
        return
    if fallback_ref is not None:
        action = _cf_string("AXRaise")
        error_code = _APPLICATION_SERVICES.AXUIElementPerformAction(fallback_ref, action)
        if error_code != 0:
            raise QianfanAccessError(f"聚焦目标窗口失败，错误码：{error_code}")
        _set_preferred_window(pid, _window_pointer(fallback_ref))
        return
    raise QianfanAccessError("目标窗口已不存在，无法聚焦。")


def _iter_interesting_window_elements(window_ref: AXUIElementRef):
    queue: deque[tuple[AXUIElementRef, int]] = deque([(window_ref, 0)])
    seen: set[int] = set()
    current_index = 0

    while queue and len(seen) < AX_MAX_NODES:
        element_ref, depth = queue.popleft()
        pointer = int(element_ref.value or 0)
        if not pointer or pointer in seen:
            continue
        seen.add(pointer)

        role = _copy_text_attribute(element_ref, "AXRole")
        yield element_ref, role, depth, current_index if role in AX_INTERESTING_ROLES else None

        if role in AX_INTERESTING_ROLES:
            current_index += 1

        if depth >= AX_MAX_DEPTH or role in AX_SKIP_SUBTREE_ROLES:
            continue
        for child_ref in _copy_children(element_ref):
            queue.append((child_ref, depth + 1))


def _collect_window_elements(window_ref: AXUIElementRef) -> list[ChromeUiElement]:
    elements: list[ChromeUiElement] = []
    for element_ref, role, depth, element_index in _iter_interesting_window_elements(window_ref):
        title = _copy_text_attribute(element_ref, "AXTitle")
        description = _copy_text_attribute(element_ref, "AXDescription")
        value = _copy_text_attribute(element_ref, "AXValue")
        position = _copy_point_like_attribute(element_ref, "AXPosition")
        size = _copy_point_like_attribute(element_ref, "AXSize")

        if role in AX_INTERESTING_ROLES and element_index is not None:
            elements.append(
                ChromeUiElement(
                    index=element_index,
                    role=role,
                    title=title[:120],
                    description=description[:120],
                    value=value[:120],
                    position=position,
                    size=size,
                )
            )
    return elements


def capture_front_window_ui(app_name: str = CHROME_APP_NAME) -> dict[str, Any]:
    window_ref = _front_window_reference(app_name)
    target_pointer = _window_pointer(window_ref)
    for pid in _find_chrome_pids(app_name):
        for candidate_ref in _window_refs_for_pid(pid):
            if _window_pointer(candidate_ref) == target_pointer:
                return _window_snapshot_from_ref(pid, candidate_ref, app_name)
    raise QianfanAccessError(f"应用没有可见窗口：{app_name}")


def front_window_active_url(app_name: str = CHROME_APP_NAME) -> str:
    snapshot = capture_front_window_ui(app_name)
    elements: list[ChromeUiElement] = snapshot["elements"]
    address_bars = [
        element
        for element in elements
        if element.role == "AXTextField" and element.description == "地址和搜索栏"
    ]
    return address_bars[0].value if address_bars else ""


def close_front_window_via_ax(app_name: str = CHROME_APP_NAME) -> None:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持关闭 {CHROME_APP_NAME} 前台窗口，不支持：{app_name}")
    window_ref = _front_window_reference(app_name)
    close_button = _copy_attribute(window_ref, "AXCloseButton")
    if not close_button:
        raise QianfanAccessError("当前前台窗口没有可访问的关闭按钮。")
    action = _cf_string("AXPress")
    error_code = _APPLICATION_SERVICES.AXUIElementPerformAction(close_button, action)
    if error_code != 0:
        raise QianfanAccessError(f"关闭前台窗口失败，错误码：{error_code}")


def wait_for_front_window(
    *,
    title_contains: str,
    url_contains: str,
    required_texts: tuple[str, ...] = (),
    timeout_seconds: int = 30,
    poll_seconds: float = 1.5,
    auto_dismiss_obstructions: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + max(timeout_seconds, 5)
    last_error: Exception | None = None
    normalized_expected_url = url_contains.replace("https://", "").replace("http://", "")
    while time.time() < deadline:
        try:
            snapshots = list_window_snapshots(CHROME_APP_NAME)
            if not snapshots:
                raise QianfanAccessError(f"应用没有可见窗口：{app_name}")

            best_url_mismatch = ""
            best_store_mismatch = ""
            best_missing = ""

            for snapshot in snapshots:
                elements: list[ChromeUiElement] = snapshot["elements"]
                address_bars = [
                    element
                    for element in elements
                    if element.role == "AXTextField" and element.description == "地址和搜索栏"
                ]
                current_url = address_bars[0].value if address_bars else ""
                normalized_current_url = current_url.replace("https://", "").replace("http://", "")
                if normalized_expected_url and normalized_expected_url not in normalized_current_url:
                    if current_url:
                        best_url_mismatch = current_url
                    continue

                text_pool = _window_snapshot_text_pool(snapshot)
                window_title = snapshot["window_title"]
                if title_contains and title_contains not in window_title and title_contains not in text_pool:
                    best_store_mismatch = window_title
                    continue

                raise_window(snapshot)
                if auto_dismiss_obstructions:
                    dismissed = False
                    try:
                        dismissal = dismiss_front_window_obstructions()
                        dismissed = dismissal.get("dismissed", False)
                    except QianfanAccessError:
                        dismissed = False
                    if not dismissed:
                        dismissal = dismiss_window_obstructions_via_ax(snapshot)
                        dismissed = dismissal.get("dismissed", False)
                    if dismissed:
                        time.sleep(min(max(poll_seconds / 2, 0.3), 1.0))
                        break

                missing = [text for text in required_texts if text not in text_pool]
                if missing:
                    best_missing = ", ".join(missing)
                    continue
                _set_preferred_window(int(snapshot["pid"]), int(snapshot["window_pointer"]))
                return snapshot
            else:
                if best_missing:
                    raise QianfanAccessError(f"页面关键控件还没出现：{best_missing}")
                if best_store_mismatch:
                    raise QianfanAccessError(f"当前前台窗口不是目标店铺：{best_store_mismatch}")
                raise QianfanAccessError(f"当前前台窗口不是目标页面：{best_url_mismatch}")
        except Exception as exc:
            last_error = exc
            time.sleep(poll_seconds)
    raise QianfanAccessError("等待目标 Chrome 页面就绪超时。") from last_error


def element_center(element: ChromeUiElement) -> tuple[int, int]:
    if element.position is None:
        raise QianfanAccessError(f"元素缺少位置：{element.role} {element.title}")
    x, y = element.position
    if element.size is None:
        return x, y
    width, height = element.size
    return x + max(width // 2, 1), y + max(height // 2, 1)


def press_front_window_element(element_index: int, app_name: str = CHROME_APP_NAME) -> None:
    window_ref = _front_window_reference(app_name)
    for element_ref, role, depth, current_index in _iter_interesting_window_elements(window_ref):
        if role in AX_INTERESTING_ROLES and current_index is not None:
            if current_index == element_index:
                action = _cf_string("AXPress")
                error_code = _APPLICATION_SERVICES.AXUIElementPerformAction(element_ref, action)
                if error_code != 0:
                    raise QianfanAccessError(f"点击元素失败，错误码：{error_code}")
                return
    raise QianfanAccessError(f"元素索引越界：{element_index}")


def set_front_window_element_value(element_index: int, value: str, app_name: str = CHROME_APP_NAME) -> None:
    if app_name != CHROME_APP_NAME:
        raise QianfanAccessError(f"当前只支持设置 {CHROME_APP_NAME} 前台窗口元素，不支持：{app_name}")
    window_ref = _front_window_reference(app_name)
    target_value = _cf_string(value)
    for element_ref, role, depth, current_index in _iter_interesting_window_elements(window_ref):
        if role in AX_INTERESTING_ROLES and current_index is not None and current_index == element_index:
            error_code = _APPLICATION_SERVICES.AXUIElementSetAttributeValue(
                element_ref,
                _cf_string("AXValue"),
                target_value,
            )
            if error_code != 0:
                raise QianfanAccessError(f"设置元素值失败，错误码：{error_code}")
            return
    raise QianfanAccessError(f"元素索引越界：{element_index}")


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
