#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from xhs_qianfan_access import (
    CHROME_APP_NAME,
    PAGE_URLS,
    activate_tab_by_id,
    close_guarded_task_windows,
    close_new_windows_for_url_ax,
    close_tab_by_id,
    front_window_active_tab_descriptor,
    list_tab_descriptors,
    list_window_snapshots,
    open_guarded_page,
    open_page,
    raise_window,
    snapshot_window_signature_counts_optional,
    wait_for_front_window,
)


def resolve_workspace_root(code_root: Path) -> Path:
    if code_root.parent.name == "releases":
        return code_root.parents[1]
    return code_root


CODE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = resolve_workspace_root(CODE_ROOT)
OWNED_TAB_REGISTRY_PATH = (WORKSPACE_ROOT / "runtime" / "qianfan_owned_tabs.json").resolve()


def _snapshot_text_pool(snapshot: dict[str, Any]) -> str:
    parts: list[str] = [str(snapshot.get("window_title", "") or "")]
    for item in snapshot.get("elements", []):
        parts.append(str(getattr(item, "title", "") or ""))
        parts.append(str(getattr(item, "value", "") or ""))
    return " ".join(part for part in parts if part).strip()


def _tab_key(descriptor: dict[str, Any]) -> tuple[int, int]:
    return (
        int(descriptor.get("window_id", 0) or 0),
        int(descriptor.get("tab_id", 0) or 0),
    )


def _tab_matches_target(descriptor: dict[str, Any], target_url_contains: str) -> bool:
    current_url = str(
        descriptor.get("tab_url", "")
        or descriptor.get("active_url", "")
        or descriptor.get("url", "")
        or ""
    )
    return bool(target_url_contains) and target_url_contains in current_url


def _tab_url(descriptor: dict[str, Any]) -> str:
    return str(
        descriptor.get("tab_url", "")
        or descriptor.get("active_url", "")
        or descriptor.get("url", "")
        or ""
    )


def _is_guard_bridge_descriptor(descriptor: dict[str, Any], extension_id: str) -> bool:
    if not extension_id:
        return False
    return _tab_url(descriptor).startswith(f"chrome-extension://{extension_id}/panel.html")


def _is_guard_bridge_snapshot(snapshot: dict[str, Any], extension_id: str) -> bool:
    if not extension_id:
        return False
    active_url = str(snapshot.get("active_url", "") or "")
    return active_url.startswith(f"chrome-extension://{extension_id}/panel.html")


def _find_profile_window_snapshot(title_hint: str) -> dict[str, Any] | None:
    if not title_hint:
        return None
    snapshots = list_window_snapshots(CHROME_APP_NAME)
    matches = [
        snapshot
        for snapshot in snapshots
        if title_hint in str(snapshot.get("window_title", "") or "")
        or title_hint in _snapshot_text_pool(snapshot)
    ]
    if not matches:
        return None
    qianfan_like_matches = [
        snapshot
        for snapshot in matches
        if any(
            fragment in str(snapshot.get("active_url", "") or "")
            for fragment in ("xiaohongshu.com", "ark.xiaohongshu.com", "customer.xiaohongshu.com")
        )
    ]
    if not qianfan_like_matches:
        return None
    qianfan_like_matches.sort(
        key=lambda snapshot: 0 if str(snapshot.get("active_url", "") or "") else 1,
    )
    return qianfan_like_matches[0]


def _load_owned_tab_registry() -> list[dict[str, Any]]:
    if not OWNED_TAB_REGISTRY_PATH.exists():
        return []
    try:
        payload = json.loads(OWNED_TAB_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    records: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        window_id = int(item.get("window_id", 0) or 0)
        tab_id = int(item.get("tab_id", 0) or 0)
        if window_id <= 0 or tab_id <= 0:
            continue
        records.append(
            {
                "session_id": str(item.get("session_id", "") or ""),
                "app_name": str(item.get("app_name", CHROME_APP_NAME) or CHROME_APP_NAME),
                "profile_directory": str(item.get("profile_directory", "") or ""),
                "page_key": str(item.get("page_key", "") or ""),
                "target_url_contains": str(item.get("target_url_contains", "") or ""),
                "window_id": window_id,
                "tab_id": tab_id,
                "tab_url": str(item.get("tab_url", "") or ""),
                "created_at": str(item.get("created_at", "") or ""),
            }
        )
    return records


def _save_owned_tab_registry(records: list[dict[str, Any]]) -> None:
    OWNED_TAB_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    OWNED_TAB_REGISTRY_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _record_owned_tabs(session: "QianfanTaskSession") -> None:
    existing = _load_owned_tab_registry()
    existing_map = {
        (int(item.get("window_id", 0) or 0), int(item.get("tab_id", 0) or 0)): item
        for item in existing
    }
    created_at = datetime.now().isoformat(timespec="seconds")
    for owned_tab in session.owned_tabs:
        key = _tab_key(owned_tab)
        existing_map[key] = {
            "session_id": session.session_id,
            "app_name": session.app_name,
            "profile_directory": session.profile_directory,
            "page_key": session.page_key,
            "target_url_contains": session.target_url_contains,
            "window_id": int(owned_tab["window_id"]),
            "tab_id": int(owned_tab["tab_id"]),
            "tab_url": str(owned_tab.get("tab_url", "") or ""),
            "created_at": created_at,
        }
    ordered_records = sorted(existing_map.values(), key=lambda item: (item["window_id"], item["tab_id"]))
    _save_owned_tab_registry(ordered_records)


def _forget_owned_tab_keys(keys: set[tuple[int, int]]) -> None:
    if not keys:
        return
    remaining = [item for item in _load_owned_tab_registry() if _tab_key(item) not in keys]
    _save_owned_tab_registry(remaining)


def cleanup_orphaned_owned_tabs(
    *,
    app_name: str = CHROME_APP_NAME,
    active_tab_guard: dict[str, Any] | None = None,
    log_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    registry = [item for item in _load_owned_tab_registry() if str(item.get("app_name", CHROME_APP_NAME) or CHROME_APP_NAME) == app_name]
    if not registry:
        return {"closed_targets": [], "remaining_targets": []}

    try:
        current_tabs = list_tab_descriptors(app_name)
    except Exception:
        current_tabs = []
    live_keys = {_tab_key(item) for item in current_tabs}
    active_key = _tab_key(active_tab_guard) if active_tab_guard else None
    closed_targets: list[str] = []
    remaining_targets: list[str] = []
    removed_keys: set[tuple[int, int]] = set()

    for record in registry:
        key = _tab_key(record)
        if key not in live_keys:
            removed_keys.add(key)
            continue
        identity = f"{record['window_id']}#{record['tab_id']}"
        if active_key and key == active_key:
            remaining_targets.append(identity)
            continue
        try:
            close_tab_by_id(
                int(record["tab_id"]),
                window_id=int(record["window_id"]),
                app_name=app_name,
            )
            closed_targets.append(identity)
            removed_keys.add(key)
            emit(f"已清理历史残留任务标签页：{identity}")
        except Exception:
            remaining_targets.append(identity)

    _forget_owned_tab_keys(removed_keys)
    return {"closed_targets": closed_targets, "remaining_targets": remaining_targets}


@dataclass
class QianfanTaskSession:
    session_id: str
    task_id: str
    app_name: str
    profile_directory: str
    page_key: str
    target_url_contains: str
    baseline_tabs: list[dict[str, Any]]
    baseline_window_signatures: dict[tuple[str, str], int] | None = None
    cleanup_scope: str = "owned_tabs_only"
    auto_close_ms: int = 600000
    owned_tabs: list[dict[str, Any]] = field(default_factory=list)
    attached_window: dict[str, Any] | None = None
    title_hint: str = ""
    ownership_registered: bool = False
    launch_strategy: str = "owned_window_per_task"
    guard_managed: bool = False
    guard_extension_id: str = ""


def _detect_new_owned_tabs(session: "QianfanTaskSession") -> list[dict[str, Any]]:
    current_tabs = list_tab_descriptors(session.app_name)
    baseline_keys = {_tab_key(item) for item in session.baseline_tabs}
    new_tabs = [item for item in current_tabs if _tab_key(item) not in baseline_keys]
    owned_tabs = [item for item in new_tabs if _tab_matches_target(item, session.target_url_contains)]
    non_guard_tabs = [
        item
        for item in new_tabs
        if not _is_guard_bridge_descriptor(item, session.guard_extension_id)
    ]
    if not owned_tabs and len(non_guard_tabs) == 1:
        owned_tabs = list(non_guard_tabs)
    return owned_tabs


def _wait_for_new_owned_tabs(
    session: "QianfanTaskSession",
    *,
    timeout_seconds: int = 15,
    poll_seconds: float = 0.5,
    log_step: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    deadline = time.time() + max(timeout_seconds, 3)
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            owned_tabs = _detect_new_owned_tabs(session)
            if owned_tabs:
                return owned_tabs
        except Exception as exc:
            last_error = exc
        time.sleep(poll_seconds)
    if last_error is not None:
        emit(f"等待本轮任务窗口登记超时，稍后按页面就绪再补登记：{last_error}")
    else:
        emit("等待本轮任务窗口登记超时，稍后按页面就绪再补登记")
    return []


def start_qianfan_task_session(
    *,
    target_url_contains: str,
    profile_directory: str,
    page_key: str,
    app_name: str = CHROME_APP_NAME,
    cleanup_scope: str = "owned_tabs_only",
    auto_close_ms: int = 600000,
) -> QianfanTaskSession:
    try:
        baseline_tabs = list_tab_descriptors(app_name)
    except Exception:
        baseline_tabs = []
    baseline_window_signatures = snapshot_window_signature_counts_optional(app_name)
    return QianfanTaskSession(
        session_id=uuid4().hex,
        task_id=f"qianfan-task-{uuid4().hex}",
        app_name=app_name,
        profile_directory=profile_directory,
        page_key=page_key,
        target_url_contains=target_url_contains,
        baseline_tabs=baseline_tabs,
        baseline_window_signatures=baseline_window_signatures,
        cleanup_scope=cleanup_scope,
        auto_close_ms=max(0, int(auto_close_ms)),
    )


def open_page_for_session(
    session: QianfanTaskSession,
    *,
    profile: Any,
    title_hint: str,
    log_step: Callable[[str], None] | None = None,
) -> None:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    app_name = str(getattr(session, "app_name", CHROME_APP_NAME) or CHROME_APP_NAME)
    try:
        active_tab = front_window_active_tab_descriptor(app_name)
    except Exception:
        active_tab = None
    cleanup_orphaned_owned_tabs(app_name=app_name, active_tab_guard=active_tab, log_step=log_step)
    session.title_hint = title_hint.strip()
    try:
        guard_payload = open_guarded_page(
            profile_directory=profile.directory,
            target_url=PAGE_URLS[session.page_key],
            task_id=session.task_id,
            auto_close_ms=session.auto_close_ms,
            dry_run=False,
        )
        session.guard_managed = True
        session.guard_extension_id = str(guard_payload.get("extension_id", "") or "")
        session.launch_strategy = "guard_bridge_owned_window"
        emit(
            f"已通过窗口守卫拉起独立窗口：{profile.directory} / {session.page_key} / "
            f"task={session.task_id}"
        )
    except Exception as exc:
        session.guard_managed = False
        session.guard_extension_id = ""
        session.launch_strategy = "owned_window_per_task"
        emit(f"窗口守卫不可用，回退直接开页：{exc}")
        open_page(profile, session.page_key, dry_run=False)
        emit(f"已为本轮任务拉起独立窗口：{profile.directory} / {session.page_key}")
    owned_tabs = _wait_for_new_owned_tabs(session, log_step=log_step)
    if owned_tabs:
        session.owned_tabs = owned_tabs
        session.ownership_registered = True
        _record_owned_tabs(session)
        emit(
            "已登记本轮任务窗口标签："
            + ", ".join(f"{item['window_id']}#{item['tab_id']}" for item in owned_tabs)
        )


def register_owned_tabs(
    session: QianfanTaskSession,
    *,
    log_step: Callable[[str], None] | None = None,
) -> QianfanTaskSession:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    try:
        current_tabs = list_tab_descriptors(session.app_name)
    except Exception as exc:
        emit(f"读取标签页快照失败，暂时无法确认本轮自建标签页：{exc}")
        session.ownership_registered = True
        session.owned_tabs = []
        return session

    owned_tabs = _detect_new_owned_tabs(session)
    session.owned_tabs = owned_tabs
    session.ownership_registered = True
    if owned_tabs:
        _record_owned_tabs(session)
    if owned_tabs:
        emit(
            "已登记本轮任务标签页："
            + ", ".join(f"{item['window_id']}#{item['tab_id']}" for item in owned_tabs)
        )
    else:
        emit("暂未识别到本轮自建标签页，收尾时会保守处理")
    return session


def bind_qianfan_task_session(
    session: QianfanTaskSession,
    snapshot: dict[str, Any],
    *,
    title_hint: str = "",
    log_step: Callable[[str], None] | None = None,
) -> QianfanTaskSession:
    if title_hint:
        session.title_hint = title_hint.strip()
    if not session.ownership_registered and not session.owned_tabs:
        register_owned_tabs(session, log_step=log_step)
    session.attached_window = snapshot
    return session


def focus_qianfan_task_session(
    session: QianfanTaskSession,
    *,
    log_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    if not session.owned_tabs:
        register_owned_tabs(session, log_step=log_step)
    if not session.owned_tabs:
        raise RuntimeError("本轮没有可聚焦的任务标签页。")
    target = session.owned_tabs[-1]
    result = activate_tab_by_id(
        int(target["tab_id"]),
        window_id=int(target["window_id"]),
        app_name=session.app_name,
    )
    emit(f"已切回本轮任务标签：{result['window_id']}#{result['tab_id']}")
    return result


def wait_for_session_front_window(
    session: QianfanTaskSession,
    *,
    title_contains: str,
    url_contains: str,
    required_texts: tuple[str, ...] = (),
    timeout_seconds: int = 30,
    poll_seconds: float = 1.5,
    auto_dismiss_obstructions: bool = True,
    log_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    deadline = time.time() + max(timeout_seconds, 5)
    last_error: Exception | None = None
    target_keys = {
        _tab_key(item)
        for item in (session.owned_tabs or [])
        if int(item.get("window_id", 0) or 0) > 0 and int(item.get("tab_id", 0) or 0) > 0
    }
    while time.time() < deadline:
        try:
            if target_keys:
                focus_qianfan_task_session(session, log_step=log_step)
            snapshot = wait_for_front_window(
                title_contains=title_contains,
                url_contains=url_contains,
                required_texts=required_texts,
                timeout_seconds=min(timeout_seconds, 10),
                poll_seconds=poll_seconds,
                auto_dismiss_obstructions=auto_dismiss_obstructions,
            )
            if not target_keys:
                session.attached_window = snapshot
                return snapshot
            front_tab = front_window_active_tab_descriptor(session.app_name)
            if _tab_key(front_tab) in target_keys:
                session.attached_window = snapshot
                return snapshot
            last_error = RuntimeError(
                f"当前前台标签不是本轮任务标签：{front_tab['window_id']}#{front_tab['tab_id']}"
            )
        except Exception as exc:
            last_error = exc
        time.sleep(poll_seconds)
    raise RuntimeError("等待本轮任务标签页回到前台超时。") from last_error


def close_qianfan_task_session(
    session: QianfanTaskSession,
    *,
    log_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log_step is not None:
            log_step(message)

    guard_close_attempted = False
    if session.guard_managed and session.task_id:
        try:
            guard_close_attempted = True
            close_guarded_task_windows(
                profile_directory=session.profile_directory,
                task_id=session.task_id,
                dry_run=False,
            )
            emit(f"已请求窗口守卫回收本轮任务窗口：{session.task_id}")
            deadline = time.time() + 5
            while time.time() < deadline:
                current_tabs = list_tab_descriptors(session.app_name)
                current_keys = {_tab_key(item) for item in current_tabs}
                owned_keys = {_tab_key(item) for item in session.owned_tabs}
                bridge_alive = any(
                    _is_guard_bridge_descriptor(item, session.guard_extension_id) for item in current_tabs
                )
                if owned_keys and owned_keys.isdisjoint(current_keys) and not bridge_alive:
                    _forget_owned_tab_keys(owned_keys)
                    return {
                        "ok": True,
                        "skipped": False,
                        "cleanup_status": "closed",
                        "reason": "",
                        "strategy": "guard_bridge",
                        "closed_window_ids": [],
                        "remaining_window_ids": [],
                        "closed_targets": [f"{item['window_id']}#{item['tab_id']}" for item in session.owned_tabs],
                        "remaining_targets": [],
                        "binding_window_id": None,
                    }
                time.sleep(0.25)
            emit("窗口守卫回收后仍检测到残留，改走本地兜底核验")
        except Exception as exc:
            emit(f"窗口守卫回收失败，改走本地兜底：{exc}")

    if not session.ownership_registered and not session.owned_tabs:
        register_owned_tabs(session, log_step=log_step)

    if not session.owned_tabs:
        tab_snapshot_error: Exception | None = None
        try:
            current_tabs = list_tab_descriptors(session.app_name)
        except Exception as exc:
            tab_snapshot_error = exc
            current_tabs = []
            emit(f"读取标签页快照失败，改走窗口差异兜底：{exc}")
        baseline_keys = {_tab_key(item) for item in session.baseline_tabs}
        current_extra_tabs = [item for item in current_tabs if _tab_key(item) not in baseline_keys]
        lingering_targets = [
            f"{item['window_id']}#{item['tab_id']}"
            for item in current_extra_tabs
            if _tab_matches_target(item, session.target_url_contains)
        ]
        if session.baseline_window_signatures is not None:
            fallback = close_new_windows_for_url_ax(
                session.baseline_window_signatures,
                target_url_contains=session.target_url_contains,
                log_step=log_step,
                app_name=session.app_name,
            )
            fallback["strategy"] = "window_diff_fallback"
            fallback["binding_window_id"] = None
            closed_targets = list(fallback.get("closed_targets", []))
            remaining_targets = list(fallback.get("remaining_targets", []))
            if closed_targets:
                fallback["cleanup_status"] = "closed"
                fallback["skipped"] = False
                return fallback
            if remaining_targets:
                fallback["cleanup_status"] = "warning"
                fallback["skipped"] = bool(fallback.get("skipped", False))
                return fallback
            if tab_snapshot_error is not None:
                return {
                    "ok": False,
                    "skipped": True,
                    "cleanup_status": "warning",
                    "reason": "tab_snapshot_failed",
                    "strategy": "window_diff_fallback",
                    "closed_window_ids": [],
                    "remaining_window_ids": [],
                    "closed_targets": [],
                    "remaining_targets": [],
                    "binding_window_id": None,
                    "error": str(tab_snapshot_error),
                }
        if not lingering_targets:
            emit("没有登记到本轮自建标签页，但当前也没有残留新标签页")
            guard_bridge_remaining = []
            if session.guard_extension_id:
                try:
                    guard_bridge_remaining = [
                        str(snapshot.get("window_title", "") or "")
                        for snapshot in list_window_snapshots(session.app_name)
                        if _is_guard_bridge_snapshot(snapshot, session.guard_extension_id)
                    ]
                except Exception:
                    guard_bridge_remaining = []
            if guard_close_attempted and not guard_bridge_remaining:
                return {
                    "ok": True,
                    "skipped": False,
                    "cleanup_status": "closed",
                    "reason": "",
                    "strategy": "guard_bridge",
                    "closed_window_ids": [],
                    "remaining_window_ids": [],
                    "closed_targets": [],
                    "remaining_targets": [],
                    "binding_window_id": None,
                }
            return {
                "ok": not guard_bridge_remaining,
                "skipped": True,
                "cleanup_status": "warning" if guard_bridge_remaining else "not_needed",
                "reason": "guard_bridge_remaining" if guard_bridge_remaining else "owned_tab_unconfirmed_but_no_residue",
                "strategy": session.cleanup_scope,
                "closed_window_ids": [],
                "remaining_window_ids": [],
                "closed_targets": [],
                "remaining_targets": guard_bridge_remaining,
                "binding_window_id": None,
            }
        emit("没有确认到本轮自建标签页，本轮不做盲关")
        return {
            "ok": False,
            "skipped": True,
            "cleanup_status": "warning",
            "reason": "owned_tab_unconfirmed",
            "strategy": session.cleanup_scope,
            "closed_window_ids": [],
            "remaining_window_ids": [],
            "closed_targets": [],
            "remaining_targets": lingering_targets,
            "binding_window_id": None,
        }

    closed_targets: list[str] = []
    remaining_targets: list[str] = []
    removed_keys: set[tuple[int, int]] = set()

    for owned_tab in session.owned_tabs:
        identity = f"{owned_tab['window_id']}#{owned_tab['tab_id']}"
        try:
            close_tab_by_id(
                int(owned_tab["tab_id"]),
                window_id=int(owned_tab["window_id"]),
                app_name=session.app_name,
            )
            closed_targets.append(identity)
            removed_keys.add(_tab_key(owned_tab))
            emit(f"已关闭本轮任务标签页：{identity}")
        except Exception:
            remaining_targets.append(identity)

    try:
        current_tabs = list_tab_descriptors(session.app_name)
    except Exception:
        current_tabs = []
    current_keys = {_tab_key(item) for item in current_tabs}
    for owned_tab in session.owned_tabs:
        key = _tab_key(owned_tab)
        if key in current_keys:
            identity = f"{owned_tab['window_id']}#{owned_tab['tab_id']}"
            if identity not in remaining_targets:
                remaining_targets.append(identity)
        else:
            removed_keys.add(key)

    _forget_owned_tab_keys(removed_keys)

    if remaining_targets:
        emit(f"本轮任务标签页仍有残留：{remaining_targets}")
        return {
            "ok": False,
            "skipped": False,
            "cleanup_status": "warning",
            "reason": "close_failed",
            "strategy": session.cleanup_scope,
            "closed_window_ids": [],
            "remaining_window_ids": [],
            "closed_targets": closed_targets,
            "remaining_targets": remaining_targets,
            "binding_window_id": None,
        }

    return {
        "ok": True,
        "skipped": False,
        "cleanup_status": "closed",
        "reason": "",
        "strategy": session.cleanup_scope,
        "closed_window_ids": [],
        "remaining_window_ids": [],
        "closed_targets": closed_targets,
        "remaining_targets": [],
        "binding_window_id": None,
    }
