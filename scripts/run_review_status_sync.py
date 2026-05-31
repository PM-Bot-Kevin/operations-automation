#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_feishu_review_status.py"
RUNTIME_DIR = REPO_ROOT / "runtime" / "review_status_sync"
PLAN_FILE = RUNTIME_DIR / "plan_latest.json"
LATEST_STATUS_FILE = RUNTIME_DIR / "status_latest.json"
LATEST_MAIN_STATUS_FILE = RUNTIME_DIR / "status_latest_main.json"
LATEST_RETRY_STATUS_FILE = RUNTIME_DIR / "status_latest_retry.json"
PYTHON_BIN = os.environ.get("REVIEW_STATUS_PYTHON_BIN") or sys.executable or "python3"
NOTIFY_TITLE = "好评漏上评检查_自动任务"


class ReviewStatusRunError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="飞书好评表已上评同步正式驱动脚本")
    parser.add_argument("--mode", choices=("main", "retry"), default="main")
    return parser.parse_args()


def irregular_pause(min_seconds: float, max_seconds: float) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


def run_json_command(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "命令执行失败"
        raise ReviewStatusRunError(message)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewStatusRunError(f"无法解析脚本输出：{completed.stdout[:400]}") from exc


def sanitize_store_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return safe.strip("_") or "store"


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


def load_latest_status() -> dict[str, Any] | None:
    if not LATEST_STATUS_FILE.exists():
        return None
    try:
        return json.loads(LATEST_STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def mode_latest_status_file(mode: str) -> Path:
    if mode == "main":
        return LATEST_MAIN_STATUS_FILE
    if mode == "retry":
        return LATEST_RETRY_STATUS_FILE
    return RUNTIME_DIR / f"status_latest_{mode}.json"


def save_status(status: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    mode = str(status.get("mode", "unknown"))
    dated_file = RUNTIME_DIR / f"status_{status['today']}_{mode}.json"
    payload = json.dumps(status, ensure_ascii=False, indent=2) + "\n"
    dated_file.write_text(payload, encoding="utf-8")
    mode_latest_status_file(mode).write_text(payload, encoding="utf-8")
    LATEST_STATUS_FILE.write_text(payload, encoding="utf-8")


def cleanup_export_files(export_payload: dict[str, Any] | None) -> None:
    if not export_payload:
        return
    for key in ("saved_file", "source_file"):
        raw_path = export_payload.get(key)
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            continue
        try:
            if path.exists():
                path.unlink()
        except OSError:
            continue


def retryable_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [issue for issue in issues if issue["type"] != "missing_orders"]


def should_run_scheduled_retry(today: str) -> bool:
    latest_status = load_latest_status()
    if not latest_status:
        return False
    if latest_status.get("today") != today:
        return False
    if latest_status.get("mode") != "main":
        return False
    issues = latest_status.get("issues", [])
    if not isinstance(issues, list):
        return False
    return bool(retryable_issues(issues))


def summarize_missing_issues(issues: list[dict[str, Any]]) -> str:
    missing = [issue for issue in issues if issue["type"] == "missing_orders"]
    total_missing = sum(int(issue.get("missing_count", 0)) for issue in missing)
    store_parts = [f"{issue['store_name']}{issue['missing_count']}条" for issue in missing]
    if not store_parts:
        return ""
    return f"漏上评{total_missing}条。{'；'.join(store_parts[:4])}。"


def summarize_failed_issues(issues: list[dict[str, Any]]) -> str:
    failed = retryable_issues(issues)
    if not failed:
        return ""
    if any(issue["type"] == "plan_failed" for issue in failed):
        return "检查失败。今天这轮没跑出来。"
    store_parts = [f"{issue['store_name']}失败" for issue in failed]
    return f"检查失败。{'；'.join(store_parts[:4])}。"


def build_notification_message(mode: str, issues: list[dict[str, Any]]) -> str:
    failed = retryable_issues(issues)
    missing = [issue for issue in issues if issue["type"] == "missing_orders"]
    if failed:
        if mode == "retry":
            return summarize_failed_issues(failed).replace("检查失败。", "补查失败。", 1)
        return summarize_failed_issues(failed)
    if missing:
        return summarize_missing_issues(missing)
    return ""


def main() -> int:
    args = parse_args()
    today = date.today().isoformat()
    started_at = datetime.now().isoformat(timespec="seconds")

    if args.mode == "retry" and os.environ.get("REVIEW_STATUS_SCHEDULED_RETRY") == "1":
        if not should_run_scheduled_retry(today):
            return 0

    try:
        plan = run_json_command(
            [
                PYTHON_BIN,
                str(SYNC_SCRIPT),
                "plan",
                "--format",
                "json",
                "--output",
                str(PLAN_FILE),
            ]
        )
    except ReviewStatusRunError as exc:
        status = {
            "today": today,
            "mode": args.mode,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "failed",
            "summary": {"pending_orders": 0, "stores_involved": 0},
            "issues": [{"type": "plan_failed", "store_name": "整体", "message": str(exc)}],
            "results": [],
        }
        save_status(status)
        notify(NOTIFY_TITLE, "检查失败。今天这轮没跑出来。")
        return 1

    pending_orders = int(plan["summary"]["pending_orders"])
    stores = plan.get("stores", [])
    if pending_orders == 0 or not stores:
        status = {
            "today": today,
            "mode": args.mode,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "summary": plan["summary"],
            "issues": [],
            "results": [],
        }
        save_status(status)
        return 0

    results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for index, store in enumerate(stores):
        store_name = store["store_name"]
        if index > 0:
            irregular_pause(35, 90)

        export_payload: dict[str, Any] | None = None
        try:
            export_payload = run_json_command(
                [
                    PYTHON_BIN,
                    str(SYNC_SCRIPT),
                    "export-store",
                    "--plan-file",
                    str(PLAN_FILE),
                    "--store",
                    store_name,
                    "--format",
                    "json",
                ]
            )
            irregular_pause(2, 5)
            reconcile_payload = run_json_command(
                [
                    PYTHON_BIN,
                    str(SYNC_SCRIPT),
                    "reconcile",
                    "--plan-file",
                    str(PLAN_FILE),
                    "--store",
                    store_name,
                    "--export-file",
                    export_payload["saved_file"],
                    "--apply",
                    "--format",
                    "json",
                ]
            )
            results.append(
                {
                    "store_name": store_name,
                    "export": export_payload,
                    "reconcile": reconcile_payload,
                }
            )
            if reconcile_payload["missing_count"] > 0:
                issues.append(
                    {
                        "type": "missing_orders",
                        "store_name": store_name,
                        "missing_count": reconcile_payload["missing_count"],
                        "missing_orders": reconcile_payload["missing_orders"],
                    }
                )
        except ReviewStatusRunError as exc:
            issues.append(
                {
                    "type": "store_failed",
                    "store_name": store_name,
                    "message": str(exc),
                }
            )
        finally:
            cleanup_export_files(export_payload)

    failed_issues = retryable_issues(issues)
    status = {
        "today": today,
        "mode": args.mode,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": "failed" if failed_issues else "success",
        "summary": plan["summary"],
        "issues": issues,
        "results": results,
    }
    save_status(status)

    if issues:
        message = build_notification_message(args.mode, issues)
        if message:
            notify(NOTIFY_TITLE, message)
        return 1 if failed_issues else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
