#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
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
DEFAULT_SKU_FIELD = "SKU"
KNOWN_LARK_CLI_PATHS = [
    Path.home() / ".codex/skills/fill-product-db/node_modules/@larksuite/cli/bin/lark-cli",
]
FILL_INTENT_KEYWORDS = ("sku", "规格")
FILL_ACTION_KEYWORDS = ("补", "填", "回写", "更新", "同步", "查", "查询")


class FillSkuError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissingSkuRecord:
    record_id: str
    store_name: str
    order_no: str
    profile_directory: str | None
    profile_name: str | None
    profile_user_name: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="整理飞书里缺失 SKU 的订单，并支持把已确认的真实规格写回飞书。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="拉取飞书里缺 SKU 的订单，按店铺整理查询计划")
    plan_parser.add_argument("query", nargs="*", help="例如：帮我把好评表里的订单SKU补齐")
    plan_parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN, help="飞书多维表格 base token")
    plan_parser.add_argument("--table-id", default=DEFAULT_TABLE_ID, help="飞书数据表 table id")
    plan_parser.add_argument("--view-id", default=DEFAULT_VIEW_ID, help="飞书视图 id")
    plan_parser.add_argument("--store-field", default=DEFAULT_STORE_FIELD, help="店铺字段名")
    plan_parser.add_argument("--order-field", default=DEFAULT_ORDER_FIELD, help="订单号字段名")
    plan_parser.add_argument("--sku-field", default=DEFAULT_SKU_FIELD, help="SKU 字段名")
    plan_parser.add_argument("--limit", type=int, default=100, help="每次读取飞书记录数，默认 100")
    plan_parser.add_argument("--max-records", type=int, default=0, help="最多处理多少条飞书记录，默认 0 表示不限制")
    plan_parser.add_argument(
        "--local-state-path",
        default=str(DEFAULT_LOCAL_STATE_PATH),
        help="Chrome Local State 路径，默认读取本机 Google Chrome 配置",
    )
    plan_parser.add_argument("--store", default="", help="只看某个店铺，便于单店低频执行")
    plan_parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式，默认 text")
    plan_parser.add_argument("--output", default="", help="可选，把计划 JSON 另存到文件")
    plan_parser.add_argument(
        "--lark-cli-bin",
        default=os.environ.get("LARK_CLI_BIN", ""),
        help="可选，显式指定 lark-cli 路径。",
    )

    apply_parser = subparsers.add_parser("apply", help="把已经确认好的真实 SKU 写回飞书")
    apply_parser.add_argument("--input-file", required=True, help="JSON 文件，必须包含 record_id 和 sku_value")
    apply_parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN, help="飞书多维表格 base token")
    apply_parser.add_argument("--table-id", default=DEFAULT_TABLE_ID, help="飞书数据表 table id")
    apply_parser.add_argument("--sku-field", default=DEFAULT_SKU_FIELD, help="SKU 字段名")
    apply_parser.add_argument("--dry-run", action="store_true", help="只打印将要回写的内容，不真正执行")
    apply_parser.add_argument(
        "--lark-cli-bin",
        default=os.environ.get("LARK_CLI_BIN", ""),
        help="可选，显式指定 lark-cli 路径。",
    )
    return parser.parse_args()


def resolve_lark_cli(explicit_path: str) -> str:
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if candidate.exists():
            return str(candidate)
        raise FillSkuError(f"指定的 lark-cli 不存在: {candidate}")

    from_path = shutil.which("lark-cli")
    if from_path:
        return from_path

    for candidate in KNOWN_LARK_CLI_PATHS:
        if candidate.exists():
            return str(candidate)

    raise FillSkuError("未找到 lark-cli。请先安装，或通过 --lark-cli-bin / LARK_CLI_BIN 指定路径。")


def run_lark_cli(
    lark_cli_bin: str,
    args: list[str],
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        [lark_cli_bin, *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FillSkuError(completed.stderr.strip() or completed.stdout.strip() or "lark-cli 执行失败")

    output = completed.stdout.strip()
    start = output.find("{")
    if start == -1:
        raise FillSkuError(f"无法解析 lark-cli 输出: {output[:200]}")
    data = json.loads(output[start:])
    if not data.get("ok", True) and data.get("code", 0) != 0:
        raise FillSkuError(json.dumps(data, ensure_ascii=False))
    return data


def ensure_fill_intent(query: str) -> None:
    normalized = query.strip().lower()
    if not normalized:
        return
    if any(keyword in normalized for keyword in FILL_INTENT_KEYWORDS) and any(
        keyword in normalized for keyword in FILL_ACTION_KEYWORDS
    ):
        return
    raise FillSkuError("没看懂你的意思。请直接说“补齐 SKU / 补上规格 / 查一下缺的 SKU”这类意思即可。")


def is_blank_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def pick_first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            nested = pick_first_text(item)
            if nested:
                return nested
        return ""
    return str(value).strip()


def fetch_records(
    lark_cli_bin: str,
    *,
    base_token: str,
    table_id: str,
    view_id: str,
    store_field: str,
    order_field: str,
    sku_field: str,
    limit: int,
    max_records: int,
) -> list[dict[str, Any]]:
    offset = 0
    records: list[dict[str, Any]] = []
    selected_fields = [store_field, order_field, sku_field]

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


def profile_to_dict(profile: ChromeProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return asdict(profile)


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    ensure_fill_intent(" ".join(args.query))
    lark_cli_bin = resolve_lark_cli(args.lark_cli_bin)
    local_state_path = Path(args.local_state_path).expanduser().resolve()
    profiles = load_profiles(local_state_path)
    records = fetch_records(
        lark_cli_bin,
        base_token=args.base_token,
        table_id=args.table_id,
        view_id=args.view_id,
        store_field=args.store_field,
        order_field=args.order_field,
        sku_field=args.sku_field,
        limit=args.limit,
        max_records=args.max_records,
    )

    warnings: list[str] = []
    missing_records: list[MissingSkuRecord] = []
    store_profiles: dict[str, ChromeProfile | None] = {}

    for record in records:
        order_no = pick_first_text(record.get(args.order_field))
        if not order_no:
            continue
        if not is_blank_cell(record.get(args.sku_field)):
            continue

        store_name = pick_first_text(record.get(args.store_field))
        if args.store and store_name != args.store:
            continue

        profile: ChromeProfile | None = None
        if store_name:
            if store_name not in store_profiles:
                try:
                    store_profiles[store_name] = resolve_profile(profiles, store_name)
                except Exception as exc:
                    store_profiles[store_name] = None
                    warnings.append(f"店铺“{store_name}”没有匹配到唯一的 Chrome 资料：{exc}")
            profile = store_profiles[store_name]
        else:
            warnings.append(f"订单 {order_no} 缺少店铺字段，后续需要人工判断使用哪个店铺后台。")

        missing_records.append(
            MissingSkuRecord(
                record_id=str(record["_record_id"]),
                store_name=store_name,
                order_no=order_no,
                profile_directory=profile.directory if profile else None,
                profile_name=profile.name if profile else None,
                profile_user_name=profile.user_name if profile else None,
            )
        )

    grouped: dict[str, list[MissingSkuRecord]] = {}
    for item in missing_records:
        key = item.store_name or "未填写店铺"
        grouped.setdefault(key, []).append(item)

    stores = []
    for store_name in sorted(grouped):
        batch = grouped[store_name]
        profile = store_profiles.get(batch[0].store_name, None) if batch[0].store_name else None
        stores.append(
            {
                "store_name": store_name,
                "order_count": len(batch),
                "profile": profile_to_dict(profile),
                "orders": [record.order_no for record in batch],
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "records_scanned": len(records),
            "missing_sku_orders": len(missing_records),
            "stores_involved": len(stores),
            "matched_store_profiles": sum(1 for store in stores if store["profile"]),
        },
        "stores": stores,
        "records": [asdict(record) for record in missing_records],
        "warnings": warnings,
    }


def render_plan_text(plan: dict[str, Any]) -> str:
    lines = [
        f"已整理出 {plan['summary']['missing_sku_orders']} 条缺 SKU 订单",
        f"涉及 {plan['summary']['stores_involved']} 个店铺",
    ]
    for store in plan["stores"]:
        profile = store["profile"]
        if profile:
            profile_text = f"{profile['name']} / {profile['directory']}"
        else:
            profile_text = "未匹配到 Chrome 资料"
        lines.append(f"- {store['store_name']}：{store['order_count']} 条，资料 {profile_text}")
    if plan["warnings"]:
        lines.append("注意：")
        for warning in plan["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def load_updates(input_path: Path) -> list[dict[str, str]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw_updates = payload["updates"] if isinstance(payload, dict) and "updates" in payload else payload
    if not isinstance(raw_updates, list):
        raise FillSkuError("回写文件格式不对，必须是数组，或对象里的 updates 数组。")

    updates: list[dict[str, str]] = []
    for index, item in enumerate(raw_updates, start=1):
        if not isinstance(item, dict):
            raise FillSkuError(f"第 {index} 条更新不是对象。")
        record_id = str(item.get("record_id") or "").strip()
        sku_value = str(item.get("sku_value") or item.get("sku") or "").strip()
        if not record_id or not sku_value:
            raise FillSkuError(f"第 {index} 条更新缺少 record_id 或 sku_value。")
        updates.append({"record_id": record_id, "sku_value": sku_value})
    return updates


def apply_updates(args: argparse.Namespace) -> tuple[int, bool]:
    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.exists():
        raise FillSkuError(f"找不到回写文件：{input_path}")

    lark_cli_bin = resolve_lark_cli(args.lark_cli_bin)
    updates = load_updates(input_path)
    for item in updates:
        command = [
            "base",
            "+record-upsert",
            "--as",
            "bot",
            "--base-token",
            args.base_token,
            "--table-id",
            args.table_id,
            "--record-id",
            item["record_id"],
            "--json",
            json.dumps({args.sku_field: item["sku_value"]}, ensure_ascii=False),
        ]
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "record_id": item["record_id"],
                        "patch": {args.sku_field: item["sku_value"]},
                    },
                    ensure_ascii=False,
                )
            )
            continue
        run_lark_cli(lark_cli_bin, command)
    return len(updates), args.dry_run


def main() -> int:
    args = parse_args()
    try:
        if args.command == "plan":
            plan = build_plan(args)
            if args.output:
                output_path = Path(args.output).expanduser().resolve()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if args.format == "json":
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print(render_plan_text(plan))
                if args.output:
                    print(f"计划文件：{output_path}")
            return 0

        updated_count, is_dry_run = apply_updates(args)
    except FillSkuError as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1

    if is_dry_run:
        print(f"已生成 {updated_count} 条待回写记录，尚未真正写入飞书。")
    else:
        print(f"已回写 {updated_count} 条 SKU 到飞书。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
