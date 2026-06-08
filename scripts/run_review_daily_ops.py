#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def resolve_workspace_root(code_root: Path) -> Path:
    if code_root.parent.name == "releases":
        return code_root.parents[1]
    return code_root


CODE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = resolve_workspace_root(CODE_ROOT)
RUNTIME_DIR = (WORKSPACE_ROOT / "runtime" / "review_daily_ops").resolve()
LATEST_STATUS_FILE = RUNTIME_DIR / "status_latest.json"
LATEST_MAIN_STATUS_FILE = RUNTIME_DIR / "status_latest_main.json"
LATEST_RETRY_STATUS_FILE = RUNTIME_DIR / "status_latest_retry.json"
PYTHON_BIN = os.environ.get("REVIEW_STATUS_PYTHON_BIN") or sys.executable or "python3"

REVIEW_TASK = {
    "key": "review_status",
    "script": CODE_ROOT / "scripts" / "run_review_status_sync.py",
    "status_file": (WORKSPACE_ROOT / "runtime" / "review_status_sync").resolve(),
}
SKU_TASK = {
    "key": "sku_fill",
    "script": CODE_ROOT / "scripts" / "run_sku_fill_auto.py",
    "status_file": (WORKSPACE_ROOT / "runtime" / "sku_fill_auto").resolve(),
}
TASKS = [REVIEW_TASK, SKU_TASK]

REVIEW_NOTIFY_TITLE = "好评漏上评检查_自动任务"
SKU_NOTIFY_TITLE = "好评sku填写_自动任务"
MERGED_NOTIFY_TITLE = "好评漏上评&填sku_自动任务"


class DailyOpsError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="好评漏上评与 SKU 自动任务总编排")
    parser.add_argument("--mode", choices=("main", "retry"), default="main")
    return parser.parse_args()


def notify(title: str, message: str) -> None:
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{escaped_message}" with title "{escaped_title}"',
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def mode_latest_status_file(mode: str) -> Path:
    if mode == "main":
        return LATEST_MAIN_STATUS_FILE
    if mode == "retry":
        return LATEST_RETRY_STATUS_FILE
    return RUNTIME_DIR / f"status_latest_{mode}.json"


def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_latest_status() -> dict[str, Any] | None:
    return load_json_file(LATEST_STATUS_FILE)


def save_status(status: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    mode = str(status.get("mode", "unknown"))
    dated_file = RUNTIME_DIR / f"status_{status['today']}_{mode}.json"
    payload = json.dumps(status, ensure_ascii=False, indent=2) + "\n"
    dated_file.write_text(payload, encoding="utf-8")
    mode_latest_status_file(mode).write_text(payload, encoding="utf-8")
    LATEST_STATUS_FILE.write_text(payload, encoding="utf-8")


def review_needs_retry(status: dict[str, Any] | None) -> bool:
    if not status:
        return False
    issues = status.get("issues", [])
    if not isinstance(issues, list):
        return False
    return any(issue.get("type") != "missing_orders" for issue in issues)


def sku_needs_retry(status: dict[str, Any] | None) -> bool:
    if not status:
        return False
    issues = status.get("issues", [])
    return isinstance(issues, list) and bool(issues)


def build_retry_plan_from_statuses(statuses: dict[str, dict[str, Any] | None]) -> dict[str, bool]:
    return {
        "review_status": review_needs_retry(statuses.get("review_status")),
        "sku_fill": sku_needs_retry(statuses.get("sku_fill")),
    }


def should_run_scheduled_retry(today: str) -> bool:
    latest_status = load_latest_status()
    if not latest_status:
        return False
    if latest_status.get("today") != today:
        return False
    if latest_status.get("mode") != "main":
        return False
    retry_plan = latest_status.get("retry_plan", {})
    if not isinstance(retry_plan, dict):
        return False
    return bool(retry_plan.get("review_status") or retry_plan.get("sku_fill"))


def latest_child_status_path(task: dict[str, Any], mode: str) -> Path:
    return task["status_file"] / f"status_latest_{mode}.json"


def load_child_status(path: Path, today: str, mode: str, previous_mtime: float | None) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if previous_mtime is not None and path.stat().st_mtime <= previous_mtime:
        return None
    payload = load_json_file(path)
    if not payload:
        return None
    if payload.get("today") != today or payload.get("mode") != mode:
        return None
    return payload


def build_fallback_child_status(task_key: str, mode: str, today: str, message: str) -> dict[str, Any]:
    issue_type = "store_failed" if task_key == "review_status" else "plan_failed"
    issue: dict[str, Any] = {"type": issue_type, "store_name": "整体", "message": message}
    if task_key == "sku_fill":
        issue["failed_count"] = 0
    return {
        "today": today,
        "mode": mode,
        "status": "failed",
        "summary": {},
        "issues": [issue],
        "results": [],
    }


def run_task(task: dict[str, Any], mode: str, today: str) -> dict[str, Any]:
    status_path = latest_child_status_path(task, mode)
    before_mtime = status_path.stat().st_mtime if status_path.exists() else None
    env = {
        **os.environ,
        "REVIEW_STATUS_SUPPRESS_NOTIFY": "1",
        "SKU_FILL_SUPPRESS_NOTIFY": "1",
        "REVIEW_STATUS_SCHEDULED_RETRY": "0",
    }
    completed = subprocess.run(
        [
            PYTHON_BIN,
            str(task["script"]),
            "--mode",
            mode,
        ],
        cwd=CODE_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.stderr.strip():
        print(completed.stderr.rstrip(), file=sys.stderr, flush=True)
    child_status = load_child_status(status_path, today, mode, before_mtime)
    if child_status:
        child_status["_returncode"] = completed.returncode
        return child_status

    message = completed.stderr.strip() or completed.stdout.strip() or "子任务没有产出状态文件。"
    return build_fallback_child_status(task["key"], mode, today, message)


def summarize_review_message(mode: str, status: dict[str, Any] | None) -> str:
    if not status:
        return ""
    issues = status.get("issues", [])
    if not isinstance(issues, list) or not issues:
        return ""
    failed = [issue for issue in issues if issue.get("type") != "missing_orders"]
    missing = [issue for issue in issues if issue.get("type") == "missing_orders"]
    if failed:
        prefix = "补查失败" if mode == "retry" else "检查失败"
        if any(issue.get("type") == "plan_failed" for issue in failed):
            return f"{prefix}。今天这轮没跑出来。"
        store_parts = [f"{issue.get('store_name', '未知店铺')}失败" for issue in failed]
        return f"{prefix}。{'；'.join(store_parts[:4])}。"
    total_missing = sum(int(issue.get("missing_count", 0)) for issue in missing)
    if total_missing <= 0:
        return ""
    store_parts = [f"{issue.get('store_name', '未知店铺')}{int(issue.get('missing_count', 0))}条" for issue in missing]
    return f"漏上评{total_missing}条。{'；'.join(store_parts[:4])}。"


def summarize_sku_message(mode: str, status: dict[str, Any] | None) -> str:
    if not status:
        return ""
    issues = status.get("issues", [])
    if not isinstance(issues, list) or not issues:
        return ""
    prefix = "SKU补跑失败" if mode == "retry" else "SKU填写失败"
    if any(issue.get("type") == "plan_failed" for issue in issues):
        return f"{prefix}。今天这轮没跑出来。"
    total_failed = sum(int(issue.get("failed_count", 0)) for issue in issues)
    store_parts = [f"{issue.get('store_name', '未知店铺')}{int(issue.get('failed_count', 0))}条" for issue in issues]
    return f"{prefix}{total_failed}条。{'；'.join(store_parts[:4])}。"


def build_notification_payload(mode: str, review_status: dict[str, Any] | None, sku_status: dict[str, Any] | None) -> dict[str, Any]:
    review_message = summarize_review_message(mode, review_status)
    sku_message = summarize_sku_message(mode, sku_status)
    if review_message and sku_message:
        return {
            "title": MERGED_NOTIFY_TITLE,
            "message": f"{review_message}{sku_message}",
        }
    if sku_message:
        return {
            "title": SKU_NOTIFY_TITLE,
            "message": sku_message,
        }
    if review_message:
        return {
            "title": REVIEW_NOTIFY_TITLE,
            "message": review_message,
        }
    return {"title": "", "message": ""}


def aggregate_cleanup(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    ok_count = 0
    for status in statuses:
        cleanup = status.get("cleanup") or {}
        ok_count += int(cleanup.get("ok_count", 0) or 0)
        for warning in cleanup.get("warnings", []):
            if isinstance(warning, dict):
                warnings.append(warning)
    return {
        "ok_count": ok_count,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    today = date.today().isoformat()
    started_at = datetime.now().isoformat(timespec="seconds")

    if args.mode == "retry" and os.environ.get("REVIEW_STATUS_SCHEDULED_RETRY") == "1":
        if not should_run_scheduled_retry(today):
            return 0

    if args.mode == "main":
        tasks_to_run = TASKS
    else:
        main_status = load_json_file(LATEST_MAIN_STATUS_FILE)
        if not main_status or main_status.get("today") != today:
            return 0
        retry_plan = main_status.get("retry_plan", {})
        if not isinstance(retry_plan, dict):
            return 0
        tasks_to_run = [task for task in TASKS if retry_plan.get(task["key"])]
        if not tasks_to_run:
            return 0

    child_statuses: dict[str, dict[str, Any] | None] = {
        "review_status": None,
        "sku_fill": None,
    }
    task_runs: dict[str, dict[str, Any]] = {}
    for task in tasks_to_run:
        child_status = run_task(task, args.mode, today)
        child_statuses[task["key"]] = child_status
        task_runs[task["key"]] = {
            "ran": True,
            "script": str(task["script"]),
            "status_file": str(latest_child_status_path(task, args.mode)),
            "status": child_status.get("status", ""),
        }

    retry_plan = build_retry_plan_from_statuses(child_statuses) if args.mode == "main" else {
        "review_status": False,
        "sku_fill": False,
    }
    notification = build_notification_payload(
        args.mode,
        child_statuses.get("review_status"),
        child_statuses.get("sku_fill"),
    )
    notified = bool(notification["message"])
    if notified:
        notify(notification["title"], notification["message"])

    ran_statuses = [status for status in child_statuses.values() if status]
    overall_failed = any(
        (status.get("business_status") or status.get("status")) == "failed"
        for status in ran_statuses
    )
    cleanup_summary = aggregate_cleanup(ran_statuses)
    overall_status = "failed" if overall_failed else "success"

    status = {
        "today": today,
        "mode": args.mode,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": overall_status,
        "business_status": overall_status,
        "cleanup_status": "warning" if cleanup_summary["warning_count"] > 0 else "not_needed",
        "summary": {
            "tasks_requested": [task["key"] for task in tasks_to_run],
            "tasks_ran": [key for key, item in task_runs.items() if item.get("ran")],
            "notification_sent": notified,
        },
        "cleanup": cleanup_summary,
        "subtasks": {
            "review_status": child_statuses.get("review_status"),
            "sku_fill": child_statuses.get("sku_fill"),
        },
        "task_runs": task_runs,
        "retry_plan": retry_plan,
        "notification": {
            "sent": notified,
            "title": notification["title"],
            "message": notification["message"],
        },
    }
    save_status(status)
    return 1 if overall_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
