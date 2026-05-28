#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_BASE_TOKEN = "W0XvbodVPaE854sF42IcnHkIn1d"
DEFAULT_TABLE_ID = "tblUM8AqYDNWvg7z"
DEFAULT_VIEW_ID = "vewbrIBKXE"
DEFAULT_ORDER_FIELD = "订单号"
DEFAULT_DATE_FIELD = "上评日期"
DEFAULT_IMAGE_FIELDS = ["配图"]
DEFAULT_DESKTOP_DIR = Path.home() / "Desktop"
KNOWN_LARK_CLI_PATHS = [
    Path.home() / ".codex/skills/fill-product-db/node_modules/@larksuite/cli/bin/lark-cli",
]


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date

    @property
    def label(self) -> str:
        if self.start == self.end:
            return self.start.isoformat()
        return f"{self.start.isoformat()}_到_{self.end.isoformat()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按自然语言日期条件，从飞书下载好评图片到桌面。")
    parser.add_argument("query", nargs="*", help="例如：帮我导出今天要上的好评")
    parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN, help="飞书多维表格 base token")
    parser.add_argument("--table-id", default=DEFAULT_TABLE_ID, help="飞书数据表 table id")
    parser.add_argument("--view-id", default=DEFAULT_VIEW_ID, help="飞书视图 id")
    parser.add_argument("--order-field", default=DEFAULT_ORDER_FIELD, help="订单号字段名")
    parser.add_argument("--date-field", default=DEFAULT_DATE_FIELD, help="上评日期字段名")
    parser.add_argument(
        "--image-field",
        dest="image_fields",
        action="append",
        default=None,
        help="图片字段名，可重复传入。默认只下载“配图”。",
    )
    parser.add_argument("--desktop-dir", default=str(DEFAULT_DESKTOP_DIR), help="桌面目录，默认 ~/Desktop")
    parser.add_argument("--limit", type=int, default=100, help="每次读取飞书记录数，默认 100")
    parser.add_argument("--max-records", type=int, default=0, help="最多处理多少条飞书记录，默认 0 表示不限制")
    parser.add_argument("--today", default="", help="仅用于测试，覆盖今天日期，格式 YYYY-MM-DD")
    parser.add_argument(
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
        raise ExportError(f"指定的 lark-cli 不存在: {candidate}")

    from_path = shutil.which("lark-cli")
    if from_path:
        return from_path

    for candidate in KNOWN_LARK_CLI_PATHS:
        if candidate.exists():
            return str(candidate)

    raise ExportError("未找到 lark-cli。请先安装，或通过 --lark-cli-bin / LARK_CLI_BIN 指定路径。")


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
        raise ExportError(completed.stderr.strip() or completed.stdout.strip() or "lark-cli 执行失败")

    output = completed.stdout.strip()
    start = output.find("{")
    if start == -1:
        raise ExportError(f"无法解析 lark-cli 输出: {output[:200]}")
    data = json.loads(output[start:])
    if not data.get("ok", True) and data.get("code", 0) != 0:
        raise ExportError(json.dumps(data, ensure_ascii=False))
    return data


def parse_chinese_number(text: str) -> int:
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + digits[text[1:]]
    if text.endswith("十"):
        return digits[text[0]] * 10
    if "十" in text:
        left, right = text.split("十", 1)
        return digits[left] * 10 + digits[right]
    if text in digits:
        return digits[text]
    raise ExportError(f"无法识别天数：{text}")


def extract_explicit_dates(query: str, today: date) -> list[date]:
    matches = re.finditer(r"(?:(\d{4})[年/-])?\s*(\d{1,2})[月/-](\d{1,2})[日号]?", query)
    dates: list[date] = []
    for match in matches:
        year = int(match.group(1)) if match.group(1) else today.year
        month = int(match.group(2))
        day = int(match.group(3))
        dates.append(date(year, month, day))
    return dates


def parse_date_window(query: str, today: date) -> DateWindow:
    query = query.strip()
    if not query:
        return DateWindow(today, today)

    explicit_dates = extract_explicit_dates(query, today)
    if len(explicit_dates) >= 2 and any(token in query for token in ("到", "至")):
        return DateWindow(explicit_dates[0], explicit_dates[1])

    near_match = re.search(r"(近|最近)([零一二两三四五六七八九十\d]+)天", query)
    if near_match:
        days = parse_chinese_number(near_match.group(2))
        return DateWindow(today, today + timedelta(days=days - 1))

    mapping = {
        "今天": 0,
        "明天": 1,
        "后天": 2,
        "昨天": -1,
        "前天": -2,
    }
    for keyword, delta in mapping.items():
        if keyword in query:
            target = today + timedelta(days=delta)
            return DateWindow(target, target)

    if explicit_dates:
        return DateWindow(explicit_dates[0], explicit_dates[0])

    raise ExportError(
        "没看懂你要导出哪天。请直接说“今天 / 明天 / 昨天 / 近三天 / 5月29号 / 2026年5月29号”。"
    )


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


def fetch_records(
    lark_cli_bin: str,
    *,
    base_token: str,
    table_id: str,
    view_id: str,
    order_field: str,
    date_field: str,
    image_fields: list[str],
    limit: int,
    max_records: int,
) -> list[dict[str, Any]]:
    offset = 0
    records: list[dict[str, Any]] = []
    selected_fields = [order_field, date_field, *image_fields]

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


def ensure_attachment_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict) and item.get("file_token")]
    return []


def sanitize_file_stem(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or "unnamed"


def build_output_dir(desktop_dir: Path, window: DateWindow) -> Path:
    base_dir = desktop_dir / f"好评图片_{window.label}"
    if not base_dir.exists():
        return base_dir
    index = 2
    while True:
        candidate = desktop_dir / f"好评图片_{window.label}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def download_image(
    lark_cli_bin: str,
    *,
    file_token: str,
    output_dir: Path,
    filename: str,
) -> None:
    run_lark_cli(
        lark_cli_bin,
        [
            "docs",
            "+media-download",
            "--as",
            "bot",
            "--token",
            file_token,
            "--type",
            "media",
            "--output",
            f"./{filename}",
            "--overwrite",
        ],
        cwd=output_dir,
    )


def export_images(args: argparse.Namespace) -> tuple[Path | None, int, DateWindow]:
    lark_cli_bin = resolve_lark_cli(args.lark_cli_bin)
    image_fields = args.image_fields or list(DEFAULT_IMAGE_FIELDS)
    today = date.fromisoformat(args.today) if args.today else date.today()
    window = parse_date_window(" ".join(args.query), today)
    desktop_dir = Path(args.desktop_dir).expanduser().resolve()
    desktop_dir.mkdir(parents=True, exist_ok=True)

    records = fetch_records(
        lark_cli_bin,
        base_token=args.base_token,
        table_id=args.table_id,
        view_id=args.view_id,
        order_field=args.order_field,
        date_field=args.date_field,
        image_fields=image_fields,
        limit=args.limit,
        max_records=args.max_records,
    )

    matched_records = [
        record
        for record in records
        if (record_date := parse_record_date(record.get(args.date_field)))
        and window.start <= record_date <= window.end
    ]

    if not matched_records:
        return None, 0, window

    output_dir = build_output_dir(desktop_dir, window)
    output_dir.mkdir(parents=True, exist_ok=False)
    order_counters: dict[str, int] = defaultdict(int)
    image_count = 0

    for record in matched_records:
        order_no = str(record.get(args.order_field) or "").strip()
        if not order_no:
            continue
        safe_order_no = sanitize_file_stem(order_no)
        for image_field in image_fields:
            for attachment in ensure_attachment_list(record.get(image_field)):
                order_counters[safe_order_no] += 1
                image_count += 1
                suffix = Path(str(attachment.get("name") or "")).suffix
                filename = f"{safe_order_no}_{order_counters[safe_order_no]}{suffix}"
                download_image(
                    lark_cli_bin,
                    file_token=attachment["file_token"],
                    output_dir=output_dir,
                    filename=filename,
                )

    return output_dir, image_count, window


def main() -> int:
    args = parse_args()
    try:
        output_dir, image_count, window = export_images(args)
    except ExportError as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1

    if output_dir is None:
        print(f"没有找到 {window.label} 这段时间内的好评图片。")
        return 0

    print(f"已导出 {image_count} 张图片")
    print(f"桌面目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
