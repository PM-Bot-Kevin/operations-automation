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


def resolve_workspace_root(code_root: Path) -> Path:
    if code_root.parent.name == "releases":
        return code_root.parents[1]
    return code_root


CODE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = resolve_workspace_root(CODE_ROOT)
FILL_SCRIPT = CODE_ROOT / "scripts" / "fill_feishu_order_skus.py"
RUNTIME_DIR = (WORKSPACE_ROOT / "runtime" / "sku_fill_auto").resolve()
PLAN_FILE = RUNTIME_DIR / "plan_latest.json"
LATEST_STATUS_FILE = RUNTIME_DIR / "status_latest.json"
LATEST_MAIN_STATUS_FILE = RUNTIME_DIR / "status_latest_main.json"
LATEST_RETRY_STATUS_FILE = RUNTIME_DIR / "status_latest_retry.json"
PYTHON_BIN = os.environ.get("REVIEW_STATUS_PYTHON_BIN") or sys.executable or "python3"
NOTIFY_TITLE = "好评sku填写_自动任务"


class SkuAutoRunError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="飞书好评表 SKU 自动补齐正式驱动脚本")
    parser.add_argument("--mode", choices=("main", "retry"), default="main")
    return parser.parse_args()


def irregular_pause(min_seconds: float, max_seconds: float) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=CODE_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stderr.strip():
        print(completed.stderr.rstrip(), file=sys.stderr, flush=True)
    return completed


def run_json_command(args: list[str]) -> dict[str, Any]:
    completed = run_command(args)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "命令执行失败"
        raise SkuAutoRunError(message)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SkuAutoRunError(f"无法解析脚本输出：{completed.stdout[:400]}") from exc


def run_apply_command(args: list[str]) -> str:
    completed = run_command(args)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "命令执行失败"
        raise SkuAutoRunError(message)
    return completed.stdout.strip()


def notify(title: str, message: str) -> None:
    if os.environ.get("SKU_FILL_SUPPRESS_NOTIFY") == "1":
        return
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


def retryable_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return issues


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


def sanitize_store_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return safe.strip("_") or "store"


def summarize_cleanup_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    ok_count = 0
    for item in results:
        query_payload = item.get("query") or {}
        cleanup = query_payload.get("cleanup")
        if not isinstance(cleanup, dict):
            continue
        if cleanup.get("ok"):
            ok_count += 1
            continue
        warnings.append(
            {
                "store_name": item.get("store_name", ""),
                "reason": str(cleanup.get("reason", "")).strip(),
                "strategy": str(cleanup.get("strategy", "")).strip(),
                "remaining_window_ids": list(cleanup.get("remaining_window_ids", [])),
                "remaining_targets": list(cleanup.get("remaining_targets", [])),
                "binding_window_id": cleanup.get("binding_window_id"),
                "closed_targets": list(cleanup.get("closed_targets", [])),
                "skipped": bool(cleanup.get("skipped", False)),
            }
        )
    return {
        "ok_count": ok_count,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def cleanup_status_from_summary(summary: dict[str, Any], *, default_status: str = "not_needed") -> str:
    if int(summary.get("warning_count", 0) or 0) > 0:
        return "warning"
    if int(summary.get("ok_count", 0) or 0) > 0:
        return "closed"
    return default_status


def summarize_failed_issues(mode: str, issues: list[dict[str, Any]]) -> str:
    failed = retryable_issues(issues)
    if not failed:
        return ""
    prefix = "SKU补跑失败" if mode == "retry" else "SKU填写失败"
    if any(issue["type"] == "plan_failed" for issue in failed):
        return f"{prefix}。今天这轮没跑出来。"
    total_failed = sum(int(issue.get("failed_count", 0)) for issue in failed)
    store_parts = [f"{issue['store_name']}{int(issue.get('failed_count', 0))}条" for issue in failed]
    return f"{prefix}{total_failed}条。{'；'.join(store_parts[:4])}。"


def build_notification_message(mode: str, issues: list[dict[str, Any]]) -> str:
    return summarize_failed_issues(mode, issues)


def build_store_query_output_path(today: str, mode: str, store_name: str) -> Path:
    filename = f"{today}_{mode}_{sanitize_store_name(store_name)}_updates.json"
    return RUNTIME_DIR / "queries" / filename


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
                str(FILL_SCRIPT),
                "plan",
                "帮我把好评表里的订单SKU补齐",
                "--format",
                "json",
                "--output",
                str(PLAN_FILE),
            ]
        )
    except SkuAutoRunError as exc:
        status = {
            "today": today,
            "mode": args.mode,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "failed",
            "business_status": "failed",
            "cleanup_status": "not_needed",
            "summary": {"missing_sku_orders": 0, "stores_involved": 0, "updated_orders": 0, "failed_orders": 0},
            "cleanup": {"ok_count": 0, "warning_count": 0, "warnings": []},
            "issues": [{"type": "plan_failed", "store_name": "整体", "failed_count": 0, "message": str(exc)}],
            "results": [],
        }
        save_status(status)
        notify(NOTIFY_TITLE, build_notification_message(args.mode, status["issues"]))
        return 1

    stores = plan.get("stores", [])
    summary = plan.get("summary", {})
    pending_orders = int(summary.get("missing_sku_orders", 0))
    if pending_orders == 0 or not stores:
        status = {
            "today": today,
            "mode": args.mode,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "business_status": "success",
            "cleanup_status": "not_needed",
            "summary": {
                "missing_sku_orders": pending_orders,
                "stores_involved": int(summary.get("stores_involved", 0)),
                "updated_orders": 0,
                "failed_orders": 0,
            },
            "cleanup": {"ok_count": 0, "warning_count": 0, "warnings": []},
            "issues": [],
            "results": [],
        }
        save_status(status)
        return 0

    results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    updated_orders = 0

    for index, store in enumerate(stores):
        store_name = str(store.get("store_name", "")).strip()
        planned_orders = [str(item) for item in store.get("orders", [])]
        planned_count = int(store.get("order_count", len(planned_orders)))
        if index > 0:
            irregular_pause(35, 90)

        query_payload: dict[str, Any] | None = None
        query_output_path = build_store_query_output_path(today, args.mode, store_name)
        try:
            query_payload = run_json_command(
                [
                    PYTHON_BIN,
                    str(FILL_SCRIPT),
                    "query",
                    "--plan-file",
                    str(PLAN_FILE),
                    "--store",
                    store_name,
                    "--output",
                    str(query_output_path),
                ]
            )
            updates = list(query_payload.get("updates", []))
            updated_count = len(updates)
            if updated_count <= 0:
                issues.append(
                    {
                        "type": "store_failed",
                        "stage": "query",
                        "store_name": store_name,
                        "failed_count": planned_count,
                        "failed_orders": planned_orders,
                        "message": "没有生成可回写的 SKU 结果。",
                    }
                )
                results.append(
                    {
                        "store_name": store_name,
                        "planned_count": planned_count,
                        "query_output_file": str(query_output_path),
                        "query": query_payload,
                        "apply": None,
                    }
                )
                continue

            irregular_pause(2, 5)
            run_apply_command(
                [
                    PYTHON_BIN,
                    str(FILL_SCRIPT),
                    "apply",
                    "--input-file",
                    str(query_output_path),
                ]
            )
            updated_orders += updated_count
            results.append(
                {
                    "store_name": store_name,
                    "planned_count": planned_count,
                    "updated_count": updated_count,
                    "query_output_file": str(query_output_path),
                    "query": query_payload,
                    "apply": {
                        "status": "success",
                        "updated_count": updated_count,
                    },
                }
            )
        except SkuAutoRunError as exc:
            failed_orders = planned_orders
            failed_count = planned_count
            stage = "query"
            if query_payload is not None:
                updates = list(query_payload.get("updates", []))
                failed_orders = [str(item.get("order_no", "")).strip() for item in updates if item.get("order_no")]
                failed_count = len(failed_orders) or planned_count
                stage = "apply"
            issues.append(
                {
                    "type": "store_failed",
                    "stage": stage,
                    "store_name": store_name,
                    "failed_count": failed_count,
                    "failed_orders": failed_orders,
                    "message": str(exc),
                }
            )
            results.append(
                {
                    "store_name": store_name,
                    "planned_count": planned_count,
                    "query_output_file": str(query_output_path),
                    "query": query_payload,
                    "apply": {
                        "status": "failed",
                        "message": str(exc),
                    }
                    if query_payload is not None
                    else None,
                }
            )

    failed_issues = retryable_issues(issues)
    cleanup_summary = summarize_cleanup_results(results)
    failed_orders_total = sum(int(issue.get("failed_count", 0)) for issue in failed_issues)
    business_status = "failed" if failed_issues else "success"
    status = {
        "today": today,
        "mode": args.mode,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": business_status,
        "business_status": business_status,
        "cleanup_status": cleanup_status_from_summary(cleanup_summary),
        "summary": {
            "missing_sku_orders": pending_orders,
            "stores_involved": int(summary.get("stores_involved", len(stores))),
            "updated_orders": updated_orders,
            "failed_orders": failed_orders_total,
        },
        "cleanup": cleanup_summary,
        "issues": issues,
        "results": results,
    }
    save_status(status)

    if failed_issues:
        notify(NOTIFY_TITLE, build_notification_message(args.mode, failed_issues))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
