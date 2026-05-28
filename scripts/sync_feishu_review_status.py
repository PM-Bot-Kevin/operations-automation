#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from xhs_qianfan_access import DEFAULT_LOCAL_STATE_PATH, ChromeProfile, load_profiles, resolve_profile


DEFAULT_BASE_TOKEN = "W0XvbodVPaE854sF42IcnHkIn1d"
DEFAULT_TABLE_ID = "tblUM8AqYDNWvg7z"
DEFAULT_VIEW_ID = "vewbrIBKXE"
DEFAULT_STORE_FIELD = "店铺"
DEFAULT_ORDER_FIELD = "订单号"
DEFAULT_DATE_FIELD = "上评日期"
DEFAULT_CHECKED_FIELD = "已上评"
DEFAULT_DESKTOP_DIR = Path.home() / "Desktop"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads"
DEFAULT_EXPORT_DIR = REPO_ROOT / "runtime" / "review_status_exports"
DEFAULT_GUARDRAILS_PATH = REPO_ROOT / "config" / "xhs_qianfan_guardrails.json"
KNOWN_LARK_CLI_PATHS = [
    Path.home() / ".codex/skills/fill-product-db/node_modules/@larksuite/cli/bin/lark-cli",
]
ORDER_COLUMN_CANDIDATES = ("订单id", "订单ID", "订单号")


class ReviewSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingReviewRecord:
    record_id: str
    store_name: str
    order_no: str
    review_date: str
    profile_directory: str | None
    profile_name: str | None
    profile_user_name: str | None


def load_guardrails() -> dict[str, Any]:
    if not DEFAULT_GUARDRAILS_PATH.exists():
        raise ReviewSyncError(f"缺少千帆风控配置：{DEFAULT_GUARDRAILS_PATH}")
    return json.loads(DEFAULT_GUARDRAILS_PATH.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="整理飞书里待同步的已上评记录，并支持接住千帆评价导出结果回写飞书。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="拉取飞书里上评日期早于今天且未勾选已上评的记录")
    plan_parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN)
    plan_parser.add_argument("--table-id", default=DEFAULT_TABLE_ID)
    plan_parser.add_argument("--view-id", default=DEFAULT_VIEW_ID)
    plan_parser.add_argument("--store-field", default=DEFAULT_STORE_FIELD)
    plan_parser.add_argument("--order-field", default=DEFAULT_ORDER_FIELD)
    plan_parser.add_argument("--date-field", default=DEFAULT_DATE_FIELD)
    plan_parser.add_argument("--checked-field", default=DEFAULT_CHECKED_FIELD)
    plan_parser.add_argument("--limit", type=int, default=100)
    plan_parser.add_argument("--max-records", type=int, default=0)
    plan_parser.add_argument("--today", default="", help="仅用于测试，覆盖今天日期，格式 YYYY-MM-DD")
    plan_parser.add_argument("--store", default="", help="只整理某个店铺")
    plan_parser.add_argument("--format", choices=("text", "json"), default="text")
    plan_parser.add_argument("--output", default="")
    plan_parser.add_argument("--local-state-path", default=str(DEFAULT_LOCAL_STATE_PATH))
    plan_parser.add_argument("--lark-cli-bin", default=os.environ.get("LARK_CLI_BIN", ""))

    capture_parser = subparsers.add_parser("capture-export", help="从桌面优先接住最新的评价导出文件，并另存为稳定文件名")
    capture_parser.add_argument("--store", required=True)
    capture_parser.add_argument("--after", required=True, help="只接受这个时间之后生成的导出文件，格式 YYYY-MM-DDTHH:MM:SS")
    capture_parser.add_argument("--desktop-dir", default=str(DEFAULT_DESKTOP_DIR))
    capture_parser.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR))
    capture_parser.add_argument("--output-dir", default=str(DEFAULT_EXPORT_DIR))
    capture_parser.add_argument("--format", choices=("text", "json"), default="text")

    reconcile_parser = subparsers.add_parser("reconcile", help="读取评价导出 CSV，对照订单号后回写飞书已上评")
    reconcile_parser.add_argument("--plan-file", required=True)
    reconcile_parser.add_argument("--export-file", required=True)
    reconcile_parser.add_argument("--store", default="")
    reconcile_parser.add_argument("--checked-field", default=DEFAULT_CHECKED_FIELD)
    reconcile_parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN)
    reconcile_parser.add_argument("--table-id", default=DEFAULT_TABLE_ID)
    reconcile_parser.add_argument("--apply", action="store_true")
    reconcile_parser.add_argument("--format", choices=("text", "json"), default="text")
    reconcile_parser.add_argument("--output", default="")
    reconcile_parser.add_argument("--lark-cli-bin", default=os.environ.get("LARK_CLI_BIN", ""))
    return parser.parse_args()


def resolve_lark_cli(explicit_path: str) -> str:
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if candidate.exists():
            return str(candidate)
        raise ReviewSyncError(f"指定的 lark-cli 不存在: {candidate}")

    from_path = shutil.which("lark-cli")
    if from_path:
        return from_path

    for candidate in KNOWN_LARK_CLI_PATHS:
        if candidate.exists():
            return str(candidate)

    raise ReviewSyncError("未找到 lark-cli。请先安装，或通过 --lark-cli-bin / LARK_CLI_BIN 指定路径。")


def run_lark_cli(lark_cli_bin: str, args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        [lark_cli_bin, *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ReviewSyncError(completed.stderr.strip() or completed.stdout.strip() or "lark-cli 执行失败")

    output = completed.stdout.strip()
    start = output.find("{")
    if start == -1:
        raise ReviewSyncError(f"无法解析 lark-cli 输出: {output[:200]}")
    data = json.loads(output[start:])
    if not data.get("ok", True) and data.get("code", 0) != 0:
        raise ReviewSyncError(json.dumps(data, ensure_ascii=False))
    return data


def parse_today(value: str) -> date:
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_record_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def pick_first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            nested = pick_first_text(item)
            if nested:
                return nested
        return ""
    return str(value).strip()


def is_checked(value: Any) -> bool:
    if value is True:
        return True
    if value in (None, False, ""):
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "checked"}
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, list):
        return any(is_checked(item) for item in value)
    return False


def fetch_records(
    lark_cli_bin: str,
    *,
    base_token: str,
    table_id: str,
    view_id: str,
    store_field: str,
    order_field: str,
    date_field: str,
    checked_field: str,
    limit: int,
    max_records: int,
) -> list[dict[str, Any]]:
    offset = 0
    records: list[dict[str, Any]] = []
    selected_fields = [store_field, order_field, date_field, checked_field]

    while True:
        command = [
            "base",
            "+record-list",
            "--as",
            "bot",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--view-id",
            view_id,
            "--limit",
            str(limit),
            "--offset",
            str(offset),
            "--format",
            "json",
        ]
        for field_name in selected_fields:
            command.extend(["--field-id", field_name])

        result = run_lark_cli(lark_cli_bin, command)
        payload = result["data"]
        field_names = payload["fields"]
        rows = payload["data"]
        record_ids = payload["record_id_list"]

        for index, row in enumerate(rows):
            row_map = {field_names[i]: row[i] for i in range(min(len(field_names), len(row)))}
            row_map["_record_id"] = record_ids[index]
            records.append(row_map)
            if max_records > 0 and len(records) >= max_records:
                return records

        if not payload.get("has_more"):
            break
        offset += limit
    return records


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    lark_cli_bin = resolve_lark_cli(args.lark_cli_bin)
    guardrails = load_guardrails()
    execution_defaults = guardrails.get("execution_defaults", {})
    today = parse_today(args.today)
    local_state_path = Path(args.local_state_path).expanduser().resolve()
    warnings: list[str] = []

    try:
        profiles = load_profiles(local_state_path)
    except Exception as exc:
        profiles = []
        warnings.append(f"未能读取 Chrome 资料映射：{exc}")

    records = fetch_records(
        lark_cli_bin,
        base_token=args.base_token,
        table_id=args.table_id,
        view_id=args.view_id,
        store_field=args.store_field,
        order_field=args.order_field,
        date_field=args.date_field,
        checked_field=args.checked_field,
        limit=args.limit,
        max_records=args.max_records,
    )

    store_profiles: dict[str, ChromeProfile | None] = {}
    pending_records: list[PendingReviewRecord] = []
    scanned_with_dates = 0

    for record in records:
        order_no = pick_first_text(record.get(args.order_field))
        if not order_no:
            continue

        review_date = parse_record_date(record.get(args.date_field))
        if review_date is None:
            continue
        scanned_with_dates += 1
        if review_date >= today:
            continue
        if is_checked(record.get(args.checked_field)):
            continue

        store_name = pick_first_text(record.get(args.store_field))
        if args.store and store_name != args.store:
            continue

        profile: ChromeProfile | None = None
        if store_name and profiles:
            if store_name not in store_profiles:
                try:
                    store_profiles[store_name] = resolve_profile(profiles, store_name)
                except Exception as exc:
                    store_profiles[store_name] = None
                    warnings.append(f"店铺“{store_name}”没有匹配到唯一的 Chrome 资料：{exc}")
            profile = store_profiles[store_name]
        elif not store_name:
            warnings.append(f"订单 {order_no} 缺少店铺字段，无法自动判断该进哪个店铺后台。")

        pending_records.append(
            PendingReviewRecord(
                record_id=str(record["_record_id"]),
                store_name=store_name,
                order_no=order_no,
                review_date=review_date.isoformat(),
                profile_directory=profile.directory if profile else None,
                profile_name=profile.name if profile else None,
                profile_user_name=profile.user_name if profile else None,
            )
        )

    grouped: dict[str, list[PendingReviewRecord]] = {}
    for item in pending_records:
        grouped.setdefault(item.store_name or "未填写店铺", []).append(item)

    stores: list[dict[str, Any]] = []
    for store_name in sorted(grouped):
        batch = sorted(grouped[store_name], key=lambda item: (item.review_date, item.order_no))
        earliest_date = batch[0].review_date
        latest_date = batch[-1].review_date
        stores.append(
            {
                "store_name": store_name,
                "order_count": len(batch),
                "earliest_review_date": earliest_date,
                "latest_review_date": latest_date,
                "orders": [item.order_no for item in batch],
                "records": [asdict(item) for item in batch],
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "guardrails": {
            "policy_name": guardrails.get("policy_name", ""),
            "single_store_only": bool(execution_defaults.get("single_store_only", True)),
            "fixed_interval_forbidden": bool(execution_defaults.get("fixed_interval_forbidden", True)),
            "prefer_irregular_pauses": bool(execution_defaults.get("prefer_irregular_pauses", True)),
            "page_refresh_forbidden": bool(execution_defaults.get("page_refresh_forbidden", True)),
        },
        "summary": {
            "records_scanned": len(records),
            "records_with_review_date": scanned_with_dates,
            "pending_orders": len(pending_records),
            "stores_involved": len(stores),
        },
        "stores": stores,
        "warnings": warnings,
    }


def render_plan_text(plan: dict[str, Any]) -> str:
    lines = [
        f"已整理出 {plan['summary']['pending_orders']} 条待同步已上评订单",
        f"涉及 {plan['summary']['stores_involved']} 个店铺",
        f"口径：只处理上评日期早于 {plan['today']} 且“已上评”未勾选的记录",
    ]
    for store in plan["stores"]:
        lines.append(
            f"- {store['store_name']}：{store['order_count']} 条，最早 {store['earliest_review_date']}，最晚 {store['latest_review_date']}"
        )
    if plan["warnings"]:
        lines.append("注意：")
        for warning in plan["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def parse_after_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReviewSyncError(f"--after 时间格式不对：{value}") from exc


def sanitize_store_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return safe.strip("_") or "store"


def find_export_file(desktop_dir: Path, downloads_dir: Path, after_time: datetime) -> Path:
    after_ts = after_time.timestamp()
    search_roots = [desktop_dir, downloads_dir]
    for root in search_roots:
        if not root.exists():
            continue
        candidates = [
            path
            for path in root.iterdir()
            if path.is_file() and "评价导出" in path.name and path.stat().st_mtime >= after_ts
        ]
        if candidates:
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            return candidates[0]
    raise ReviewSyncError("没有找到新的评价导出文件。会先查桌面，桌面没有再查 Downloads。")


def capture_export(args: argparse.Namespace) -> dict[str, Any]:
    desktop_dir = Path(args.desktop_dir).expanduser().resolve()
    downloads_dir = Path(args.downloads_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    after_time = parse_after_timestamp(args.after)
    source = find_export_file(desktop_dir, downloads_dir, after_time)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"{stamp}_{sanitize_store_name(args.store)}.csv"
    shutil.copy2(source, target)
    return {
        "store_name": args.store,
        "source_file": str(source),
        "saved_file": str(target),
        "saved_at": stamp,
    }


def load_plan(plan_path: Path) -> dict[str, Any]:
    if not plan_path.exists():
        raise ReviewSyncError(f"找不到计划文件：{plan_path}")
    return json.loads(plan_path.read_text(encoding="utf-8"))


def pick_store(plan: dict[str, Any], store_name: str) -> dict[str, Any]:
    stores = plan.get("stores", [])
    if not stores:
        raise ReviewSyncError("计划里没有待处理店铺。")
    if store_name:
        for store in stores:
            if store.get("store_name") == store_name:
                return store
        raise ReviewSyncError(f"计划里找不到店铺：{store_name}")
    if len(stores) != 1:
        names = " / ".join(store.get("store_name", "") for store in stores)
        raise ReviewSyncError(f"计划里有多个店铺，请明确传 --store。当前店铺：{names}")
    return stores[0]


def read_csv_rows(export_file: Path) -> list[dict[str, str]]:
    if not export_file.exists():
        raise ReviewSyncError(f"找不到导出文件：{export_file}")

    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with export_file.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return list(reader)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise ReviewSyncError(f"无法读取导出文件编码：{export_file}") from last_error


def find_order_column(rows: list[dict[str, str]]) -> str:
    if not rows:
        raise ReviewSyncError("导出文件里没有数据行。")
    field_names = rows[0].keys()
    for candidate in ORDER_COLUMN_CANDIDATES:
        if candidate in field_names:
            return candidate
    raise ReviewSyncError(f"导出文件里没有订单号列。期望列名之一：{', '.join(ORDER_COLUMN_CANDIDATES)}")


def apply_updates(
    lark_cli_bin: str,
    *,
    base_token: str,
    table_id: str,
    checked_field: str,
    updates: list[dict[str, Any]],
) -> None:
    for item in updates:
        command = [
            "base",
            "+record-upsert",
            "--as",
            "bot",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--record-id",
            item["record_id"],
            "--json",
            json.dumps({checked_field: True}, ensure_ascii=False),
        ]
        run_lark_cli(lark_cli_bin, command)


def reconcile_export(args: argparse.Namespace) -> dict[str, Any]:
    plan = load_plan(Path(args.plan_file).expanduser().resolve())
    store = pick_store(plan, args.store)
    export_file = Path(args.export_file).expanduser().resolve()
    rows = read_csv_rows(export_file)
    order_column = find_order_column(rows)
    exported_orders = {str(row.get(order_column, "")).strip() for row in rows if str(row.get(order_column, "")).strip()}

    matched_records = [record for record in store["records"] if record["order_no"] in exported_orders]
    missing_records = [record for record in store["records"] if record["order_no"] not in exported_orders]
    updates = [{"record_id": record["record_id"], "order_no": record["order_no"]} for record in matched_records]

    if args.apply and updates:
        lark_cli_bin = resolve_lark_cli(args.lark_cli_bin)
        apply_updates(
            lark_cli_bin,
            base_token=args.base_token,
            table_id=args.table_id,
            checked_field=args.checked_field,
            updates=updates,
        )

    return {
        "store_name": store["store_name"],
        "export_file": str(export_file),
        "order_column": order_column,
        "exported_order_count": len(exported_orders),
        "matched_count": len(matched_records),
        "missing_count": len(missing_records),
        "applied": bool(args.apply and updates),
        "matched_orders": [record["order_no"] for record in matched_records],
        "missing_orders": [record["order_no"] for record in missing_records],
        "updates": updates,
    }


def render_capture_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"已接住 {payload['store_name']} 的评价导出文件",
            f"来源：{payload['source_file']}",
            f"保存为：{payload['saved_file']}",
        ]
    )


def render_reconcile_text(payload: dict[str, Any]) -> str:
    lines = [
        f"{payload['store_name']}：命中 {payload['matched_count']} 条，未命中 {payload['missing_count']} 条",
        f"导出文件：{payload['export_file']}",
    ]
    if payload["missing_orders"]:
        lines.append("未命中订单：")
        for order_no in payload["missing_orders"]:
            lines.append(f"- {order_no}")
    if payload["applied"]:
        lines.append("已按导出结果回写飞书勾选。")
    return "\n".join(lines)


def maybe_write_output(path_text: str, payload: dict[str, Any]) -> Path | None:
    if not path_text:
        return None
    output_path = Path(path_text).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    args = parse_args()
    try:
        if args.command == "plan":
            payload = build_plan(args)
            output_path = maybe_write_output(args.output, payload)
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(render_plan_text(payload))
                if output_path:
                    print(f"计划文件：{output_path}")
            return 0

        if args.command == "capture-export":
            payload = capture_export(args)
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(render_capture_text(payload))
            return 0

        payload = reconcile_export(args)
        output_path = maybe_write_output(args.output, payload)
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_reconcile_text(payload))
            if output_path:
                print(f"结果文件：{output_path}")
        return 0
    except ReviewSyncError as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
