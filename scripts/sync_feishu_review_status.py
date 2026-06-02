#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


def resolve_workspace_root(code_root: Path) -> Path:
    if code_root.parent.name == "releases":
        return code_root.parents[1]
    return code_root


CODE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = resolve_workspace_root(CODE_ROOT)
SCRIPTS_DIR = CODE_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from xhs_qianfan_access import (
    DEFAULT_LOCAL_STATE_PATH,
    ChromeUiElement,
    PAGE_URLS,
    close_window_by_id,
    element_center,
    focus_window_by_url_ax,
    list_window_descriptors,
    load_profiles,
    open_page,
    press_front_window_element,
    resolve_profile,
    run_front_window_javascript,
    set_front_window_element_value,
    wait_for_front_window,
)


DEFAULT_BASE_TOKEN = "W0XvbodVPaE854sF42IcnHkIn1d"
DEFAULT_TABLE_ID = "tblUM8AqYDNWvg7z"
DEFAULT_VIEW_ID = "vewbrIBKXE"
DEFAULT_STORE_FIELD = "店铺"
DEFAULT_ORDER_FIELD = "订单号"
DEFAULT_DATE_FIELD = "上评日期"
DEFAULT_CHECKED_FIELD = "已上评"
DEFAULT_DESKTOP_DIR = Path.home() / "Desktop"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads"
DEFAULT_EXPORT_DIR = (WORKSPACE_ROOT / "runtime" / "review_status_exports").resolve()
DEFAULT_GUARDRAILS_PATH = CODE_ROOT / "config" / "xhs_qianfan_guardrails.json"
KNOWN_LARK_CLI_PATHS = [
    Path.home() / ".codex/skills/fill-product-db/node_modules/@larksuite/cli/bin/lark-cli",
]
ORDER_COLUMN_CANDIDATES = ("订单id", "订单ID", "订单号")
DATE_TEXTFIELD_COMMIT_KEY = "tab"
DEFAULT_EXPORT_INTERACTION_MODE = "auto"
DEFAULT_EXPORT_START_TIMEOUT_SECONDS = 60


class ReviewSyncError(RuntimeError):
    pass


class ExportStartTimeoutError(ReviewSyncError):
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

    export_parser = subparsers.add_parser("export-store", help="打开指定店铺评价管理页，按计划日期范围搜索并导出评价 CSV")
    export_parser.add_argument("--plan-file", required=True)
    export_parser.add_argument("--store", required=True)
    export_parser.add_argument("--desktop-dir", default=str(DEFAULT_DESKTOP_DIR))
    export_parser.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR))
    export_parser.add_argument("--output-dir", default=str(DEFAULT_EXPORT_DIR))
    export_parser.add_argument("--local-state-path", default=str(DEFAULT_LOCAL_STATE_PATH))
    export_parser.add_argument("--export-start-timeout-seconds", type=int, default=DEFAULT_EXPORT_START_TIMEOUT_SECONDS)
    export_parser.add_argument("--export-timeout-seconds", type=int, default=420)
    export_parser.add_argument(
        "--interaction-mode",
        choices=("auto", "browser_js", "ax", "mouse"),
        default=DEFAULT_EXPORT_INTERACTION_MODE,
        help="评价导出交互方式。默认先走 ax，不行再降级到 mouse；browser_js 仅用于显式验证。",
    )
    export_parser.add_argument("--format", choices=("text", "json"), default="text")
    export_parser.add_argument("--output", default="")
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
    if not file_is_stable(source):
        raise ReviewSyncError(f"导出文件还没写完：{source.name}")
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


def log_step(message: str) -> None:
    print(f"[review-sync] {message}", file=sys.stderr, flush=True)


def irregular_pause(min_seconds: float, max_seconds: float) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


def build_store_export_window(plan: dict[str, Any], store_name: str) -> tuple[dict[str, Any], str, str]:
    store = pick_store(plan, store_name)
    start_date = store["earliest_review_date"]
    end_date = plan.get("today") or date.today().isoformat()
    return store, start_date, end_date


def snapshot_window_ids() -> set[int]:
    try:
        return {int(item["window_id"]) for item in list_window_descriptors()}
    except Exception:
        return set()


def snapshot_window_ids_optional() -> set[int] | None:
    try:
        descriptors = list_window_descriptors()
    except Exception:
        return None
    return {int(item["window_id"]) for item in descriptors}


def close_opened_comment_window(previous_window_ids: set[int] | None) -> None:
    last_error: Exception | None = None
    remaining_new_ids: set[int] | None = None
    if previous_window_ids is not None:
        try:
            current_window_ids = snapshot_window_ids_optional()
            if current_window_ids is not None:
                remaining_new_ids = current_window_ids - previous_window_ids
                for window_id in sorted(remaining_new_ids, reverse=True):
                    close_window_by_id(window_id)
                    log_step(f"已关闭本轮任务窗口：{window_id}")
                current_window_ids = snapshot_window_ids_optional()
                if current_window_ids is not None:
                    remaining_new_ids = current_window_ids - previous_window_ids
                    if not remaining_new_ids:
                        return
        except Exception as exc:
            last_error = exc

    if previous_window_ids is None:
        log_step("任务前窗口快照缺失，本轮不做盲关，避免误关用户原窗口")
        return

    detail = ""
    if remaining_new_ids:
        detail = f"，仍残留窗口: {sorted(remaining_new_ids)}"
    log_step(f"任务窗口收尾关闭失败，忽略：{last_error}{detail}")


def locate_comment_page_controls(snapshot: dict[str, Any]) -> dict[str, ChromeUiElement]:
    elements: list[ChromeUiElement] = snapshot["elements"]
    date_label_index = -1
    date_fields: list[ChromeUiElement] = []
    search_button: ChromeUiElement | None = None
    export_button: ChromeUiElement | None = None

    for element in elements:
        if element.role == "AXStaticText" and element.value == "评价时间":
            date_label_index = element.index
            continue
        if date_label_index >= 0 and element.index > date_label_index and element.role == "AXTextField":
            date_fields.append(element)
            if len(date_fields) == 2:
                continue
        if search_button is None and element.role == "AXButton" and element.title == "搜索":
            search_button = element
        if export_button is None and element.role == "AXButton" and element.title == "全部导出":
            export_button = element

    if len(date_fields) < 2:
        raise ReviewSyncError("没有定位到评价时间的开始/结束日期输入框。")
    if search_button is None:
        raise ReviewSyncError("没有定位到“搜索”按钮。")
    if export_button is None:
        raise ReviewSyncError("没有定位到“全部导出”按钮。")
    return {
        "start_date_field": date_fields[0],
        "end_date_field": date_fields[1],
        "search_button": search_button,
        "export_button": export_button,
    }


def _load_pyautogui() -> Any:
    try:
        import pyautogui  # type: ignore
    except Exception as exc:
        raise ReviewSyncError(f"当前环境缺少 pyautogui，无法执行本机低频 Chrome 操作：{exc}") from exc
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = True
    return pyautogui


def move_and_click(pyautogui: Any, point: tuple[int, int]) -> None:
    x, y = point
    jitter_x = random.randint(-2, 2)
    jitter_y = random.randint(-2, 2)
    pyautogui.moveTo(x + jitter_x, y + jitter_y, duration=random.uniform(0.18, 0.55))
    irregular_pause(0.15, 0.45)
    pyautogui.click()


def type_text_humanized(pyautogui: Any, text: str) -> None:
    for char in text:
        pyautogui.write(char)
        time.sleep(random.uniform(0.04, 0.14))


def replace_text(pyautogui: Any, point: tuple[int, int], text: str) -> None:
    move_and_click(pyautogui, point)
    irregular_pause(0.25, 0.55)
    pyautogui.hotkey("command", "a")
    irregular_pause(0.12, 0.25)
    pyautogui.press("backspace")
    irregular_pause(0.12, 0.28)
    type_text_humanized(pyautogui, text)
    irregular_pause(0.18, 0.35)
    pyautogui.press(DATE_TEXTFIELD_COMMIT_KEY)


def close_comment_window(pyautogui: Any) -> None:
    irregular_pause(0.4, 0.9)
    pyautogui.press("esc")
    irregular_pause(0.5, 1.0)
    pyautogui.hotkey("command", "w")


def file_is_stable(path: Path, *, stable_seconds: float = 2.5) -> bool:
    if not path.exists() or not path.is_file():
        return False
    first = path.stat()
    if first.st_size <= 0:
        return False
    time.sleep(stable_seconds)
    second = path.stat()
    return second.st_size > 0 and first.st_size == second.st_size and int(first.st_mtime) == int(second.st_mtime)


def wait_for_export_start(
    *,
    after_time: datetime,
    desktop_dir: Path,
    downloads_dir: Path,
    timeout_seconds: int,
) -> Path:
    deadline = time.time() + max(timeout_seconds, 5)
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return find_export_file(desktop_dir, downloads_dir, after_time)
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise ExportStartTimeoutError(f"等待评价导出文件开始生成超时（{timeout_seconds} 秒）") from last_error


def build_comment_page_poll_script() -> str:
    return """
(function () {
  function visible(node) {
    if (!node) return false;
    var style = window.getComputedStyle(node);
    var rect = node.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }
  function normalize(text) {
    return String(text || '').replace(/\\s+/g, '');
  }
  var bodyText = String((document.body && document.body.innerText) || '').replace(/\\s+/g, ' ');
  var buttons = document.querySelectorAll('button, [role="button"], .ant-btn');
  var exportButton = null;
  var index = 0;
  for (index = 0; index < buttons.length; index += 1) {
    if (visible(buttons[index]) && normalize(buttons[index].innerText || buttons[index].textContent) === '全部导出') {
      exportButton = buttons[index];
      break;
    }
  }
  var loadingNode = document.querySelector('.ant-spin-spinning, .ant-skeleton-active, [aria-busy="true"], .loading, .is-loading');
  return JSON.stringify({
    ok: true,
    ready: Boolean(exportButton) && !loadingNode,
    hasExportButton: Boolean(exportButton),
    hasSearchText: bodyText.indexOf('搜索') >= 0,
    loading: Boolean(loadingNode)
  });
})()
""".strip()


def build_comment_page_fill_and_search_script(start_date: str, end_date: str) -> str:
    start_json = json.dumps(start_date, ensure_ascii=False)
    end_json = json.dumps(end_date, ensure_ascii=False)
    return f"""
((function () {{
  function visible(node) {{
    if (!node) return false;
    var style = window.getComputedStyle(node);
    var rect = node.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }}
  function normalize(text) {{
    return String(text || '').replace(/\\s+/g, '');
  }}
  var inputValueDescriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  var nativeSetter = inputValueDescriptor && inputValueDescriptor.set;
  function setValue(input, value) {{
    input.focus();
    if (nativeSetter) {{
      nativeSetter.call(input, value);
    }} else {{
      input.value = value;
    }}
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Tab', bubbles: true }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Tab', bubbles: true }}));
    input.blur();
  }}
  var rawInputs = document.querySelectorAll('input');
  var inputs = [];
  var index = 0;
  for (index = 0; index < rawInputs.length; index += 1) {{
    if (visible(rawInputs[index]) && normalize(rawInputs[index].placeholder).indexOf('请选择日期') >= 0) {{
      inputs.push(rawInputs[index]);
      if (inputs.length === 2) {{
        break;
      }}
    }}
  }}
  if (inputs.length < 2) {{
    return JSON.stringify({{ ok: false, error: '找不到日期输入框，当前只找到 ' + inputs.length + ' 个' }});
  }}
  setValue(inputs[0], {start_json});
  setValue(inputs[1], {end_json});
  var buttons = document.querySelectorAll('button, [role="button"], .ant-btn');
  var searchButton = null;
  for (index = 0; index < buttons.length; index += 1) {{
    if (visible(buttons[index]) && normalize(buttons[index].innerText || buttons[index].textContent) === '搜索') {{
      searchButton = buttons[index];
      break;
    }}
  }}
  if (!searchButton) {{
    return JSON.stringify({{ ok: false, error: '找不到搜索按钮' }});
  }}
  searchButton.click();
  return JSON.stringify({{
    ok: true,
    action: 'search',
    startDate: inputs[0].value,
    endDate: inputs[1].value
  }});
}})())
""".strip()


def build_comment_page_export_script() -> str:
    return """
(function () {
  function visible(node) {
    if (!node) return false;
    var style = window.getComputedStyle(node);
    var rect = node.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }
  function normalize(text) {
    return String(text || '').replace(/\\s+/g, '');
  }
  var buttons = document.querySelectorAll('button, [role="button"], .ant-btn');
  var exportButton = null;
  var index = 0;
  for (index = 0; index < buttons.length; index += 1) {
    if (visible(buttons[index]) && normalize(buttons[index].innerText || buttons[index].textContent) === '全部导出') {
      exportButton = buttons[index];
      break;
    }
  }
  if (!exportButton) {
    return JSON.stringify({ ok: false, error: '找不到全部导出按钮' });
  }
  exportButton.click();
  return JSON.stringify({ ok: true, action: 'export' });
})()
""".strip()


def run_front_window_json(script: str) -> dict[str, Any]:
    try:
        raw = run_front_window_javascript(script)
    except Exception as exc:
        raise ReviewSyncError(f"Chrome 页内执行失败：{exc}") from exc
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ReviewSyncError(f"无法解析 Chrome 页内返回：{raw[:200]}") from exc


def ensure_browser_js_ok(result: dict[str, Any], *, action: str) -> dict[str, Any]:
    if result.get("ok"):
        return result
    detail = str(result.get("error", "")).strip() or "未知错误"
    raise ReviewSyncError(f"{action}失败：{detail}")


def wait_for_comment_page_ready_via_browser_js(timeout_seconds: int = 30, poll_seconds: float = 1.5) -> None:
    deadline = time.time() + max(timeout_seconds, 5)
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            result = run_front_window_json(build_comment_page_poll_script())
            ensure_browser_js_ok(result, action="检查评价页状态")
            if result.get("ready"):
                return
            last_error = ReviewSyncError("页面结果仍在加载，暂不执行导出。")
        except Exception as exc:
            last_error = exc
        time.sleep(poll_seconds)
    raise ReviewSyncError("等待评价页搜索结果稳定超时。") from last_error


def focus_comment_window_if_possible() -> None:
    try:
        focus_window_by_url_ax(PAGE_URLS["comments"])
    except Exception as exc:
        log_step(f"评价页聚焦未命中，继续等待页面就绪：{exc}")


def export_store_via_browser_js(
    *,
    store_name: str,
    profile: Any,
    start_date: str,
    end_date: str,
    desktop_dir: Path,
    downloads_dir: Path,
    output_dir: Path,
    export_start_timeout_seconds: int,
    export_timeout_seconds: int,
) -> dict[str, Any]:
    after_time = datetime.now()
    previous_window_ids = snapshot_window_ids_optional()
    try:
        log_step(f"打开店铺评价页：{store_name} ({profile.directory})")
        open_page(profile, "comments", dry_run=False)
        irregular_pause(3.0, 6.0)
        focus_comment_window_if_possible()
        wait_for_front_window(
            title_contains=store_name,
            url_contains=PAGE_URLS["comments"],
            required_texts=("评价时间", "搜索", "全部导出"),
            timeout_seconds=35,
        )
        log_step("评价页就绪，开始页内写入日期并搜索")
        fill_result = ensure_browser_js_ok(
            run_front_window_json(build_comment_page_fill_and_search_script(start_date, end_date)),
            action="填写日期并搜索",
        )
        log_step(f"已写入日期范围：{fill_result.get('startDate', start_date)} ~ {fill_result.get('endDate', end_date)}")
        wait_for_comment_page_ready_via_browser_js(timeout_seconds=35, poll_seconds=1.8)
        log_step("搜索结果已稳定，开始页内点击全部导出")
        ensure_browser_js_ok(
            run_front_window_json(build_comment_page_export_script()),
            action="点击全部导出",
        )
        irregular_pause(1.8, 3.2)
        log_step("开始接住桌面导出文件")
        capture = wait_for_export_capture(
            store_name=store_name,
            after_time=after_time,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            start_timeout_seconds=export_start_timeout_seconds,
            timeout_seconds=export_timeout_seconds,
        )
        log_step(f"已保存导出文件：{capture['saved_file']}")
        return {
            "interaction_mode": "browser_js",
            "store_name": store_name,
            "profile_name": profile.name or profile.directory,
            "profile_directory": profile.directory,
            "start_date": start_date,
            "end_date": end_date,
            "source_file": capture["source_file"],
            "saved_file": capture["saved_file"],
            "saved_at": capture["saved_at"],
        }
    finally:
        close_opened_comment_window(previous_window_ids)


def export_store_via_mouse(
    *,
    store_name: str,
    profile: Any,
    start_date: str,
    end_date: str,
    desktop_dir: Path,
    downloads_dir: Path,
    output_dir: Path,
    export_start_timeout_seconds: int,
    export_timeout_seconds: int,
) -> dict[str, Any]:
    after_time = datetime.now()
    previous_window_ids = snapshot_window_ids_optional()
    pyautogui = _load_pyautogui()
    try:
        log_step(f"打开店铺评价页：{store_name} ({profile.directory})")
        open_page(profile, "comments", dry_run=False)
        irregular_pause(3.0, 6.0)
        focus_comment_window_if_possible()
        snapshot = wait_for_front_window(
            title_contains=store_name,
            url_contains=PAGE_URLS["comments"],
            required_texts=("评价时间", "搜索", "全部导出"),
            timeout_seconds=35,
        )
        controls = locate_comment_page_controls(snapshot)
        log_step("定位评价页成功，开始低频填写日期")

        replace_text(pyautogui, element_center(controls["start_date_field"]), start_date)
        irregular_pause(0.8, 1.8)
        replace_text(pyautogui, element_center(controls["end_date_field"]), end_date)
        irregular_pause(1.0, 2.0)
        log_step(f"已写入日期范围：{start_date} ~ {end_date}")

        move_and_click(pyautogui, element_center(controls["search_button"]))
        log_step("已点击搜索，等待页面整理结果")
        irregular_pause(4.0, 8.0)

        snapshot = wait_for_front_window(
            title_contains=store_name,
            url_contains=PAGE_URLS["comments"],
            required_texts=("全部导出",),
            timeout_seconds=25,
        )
        controls = locate_comment_page_controls(snapshot)
        move_and_click(pyautogui, element_center(controls["export_button"]))
        log_step("已点击全部导出，等待桌面文件稳定落地")
        irregular_pause(2.5, 4.5)

        log_step("开始接住桌面导出文件")
        capture = wait_for_export_capture(
            store_name=store_name,
            after_time=after_time,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            start_timeout_seconds=export_start_timeout_seconds,
            timeout_seconds=export_timeout_seconds,
        )
        log_step(f"已保存导出文件：{capture['saved_file']}")
        return {
            "interaction_mode": "mouse",
            "store_name": store_name,
            "profile_name": profile.name or profile.directory,
            "profile_directory": profile.directory,
            "start_date": start_date,
            "end_date": end_date,
            "source_file": capture["source_file"],
            "saved_file": capture["saved_file"],
            "saved_at": capture["saved_at"],
        }
    finally:
        close_opened_comment_window(previous_window_ids)


def export_store_via_ax(
    *,
    store_name: str,
    profile: Any,
    start_date: str,
    end_date: str,
    desktop_dir: Path,
    downloads_dir: Path,
    output_dir: Path,
    export_start_timeout_seconds: int,
    export_timeout_seconds: int,
) -> dict[str, Any]:
    after_time = datetime.now()
    previous_window_ids = snapshot_window_ids_optional()
    try:
        log_step(f"打开店铺评价页：{store_name} ({profile.directory})")
        open_page(profile, "comments", dry_run=False)
        irregular_pause(3.0, 6.0)
        focus_comment_window_if_possible()
        snapshot = wait_for_front_window(
            title_contains=store_name,
            url_contains=PAGE_URLS["comments"],
            required_texts=("评价时间", "搜索", "全部导出"),
            timeout_seconds=35,
        )
        controls = locate_comment_page_controls(snapshot)
        log_step("定位评价页成功，开始 AX 填写日期")
        set_front_window_element_value(controls["start_date_field"].index, start_date)
        irregular_pause(0.5, 1.2)
        set_front_window_element_value(controls["end_date_field"].index, end_date)
        irregular_pause(0.8, 1.5)
        log_step(f"已写入日期范围：{start_date} ~ {end_date}")
        press_front_window_element(controls["search_button"].index)
        log_step("已触发搜索，等待页面整理结果")
        irregular_pause(4.0, 8.0)
        snapshot = wait_for_front_window(
            title_contains=store_name,
            url_contains=PAGE_URLS["comments"],
            required_texts=("全部导出",),
            timeout_seconds=25,
        )
        controls = locate_comment_page_controls(snapshot)
        press_front_window_element(controls["export_button"].index)
        log_step("已触发全部导出，等待桌面文件稳定落地")
        irregular_pause(2.5, 4.5)
        log_step("开始接住桌面导出文件")
        capture = wait_for_export_capture(
            store_name=store_name,
            after_time=after_time,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            start_timeout_seconds=export_start_timeout_seconds,
            timeout_seconds=export_timeout_seconds,
        )
        log_step(f"已保存导出文件：{capture['saved_file']}")
        return {
            "interaction_mode": "ax",
            "store_name": store_name,
            "profile_name": profile.name or profile.directory,
            "profile_directory": profile.directory,
            "start_date": start_date,
            "end_date": end_date,
            "source_file": capture["source_file"],
            "saved_file": capture["saved_file"],
            "saved_at": capture["saved_at"],
        }
    finally:
        close_opened_comment_window(previous_window_ids)


def wait_for_export_capture(
    *,
    store_name: str,
    after_time: datetime,
    desktop_dir: Path,
    downloads_dir: Path,
    output_dir: Path,
    start_timeout_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    wait_for_export_start(
        after_time=after_time,
        desktop_dir=desktop_dir,
        downloads_dir=downloads_dir,
        timeout_seconds=start_timeout_seconds,
    )
    deadline = time.time() + max(timeout_seconds, 10)
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            source = find_export_file(desktop_dir, downloads_dir, after_time)
            if not file_is_stable(source):
                raise ReviewSyncError(f"导出文件还没写完：{source.name}")
            output_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
            target = output_dir / f"{stamp}_{sanitize_store_name(store_name)}.csv"
            shutil.copy2(source, target)
            return {
                "store_name": store_name,
                "source_file": str(source),
                "saved_file": str(target),
                "saved_at": stamp,
            }
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise ReviewSyncError(f"等待评价导出文件写完超时（{timeout_seconds} 秒）") from last_error


def export_store(args: argparse.Namespace) -> dict[str, Any]:
    plan = load_plan(Path(args.plan_file).expanduser().resolve())
    store, start_date, end_date = build_store_export_window(plan, args.store)
    local_state_path = Path(args.local_state_path).expanduser().resolve()
    desktop_dir = Path(args.desktop_dir).expanduser().resolve()
    downloads_dir = Path(args.downloads_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    profiles = load_profiles(local_state_path)
    profile = resolve_profile(profiles, store["store_name"])
    interaction_mode = getattr(args, "interaction_mode", DEFAULT_EXPORT_INTERACTION_MODE)
    export_start_timeout_seconds = getattr(
        args,
        "export_start_timeout_seconds",
        DEFAULT_EXPORT_START_TIMEOUT_SECONDS,
    )

    if interaction_mode == "ax":
        return export_store_via_ax(
            store_name=store["store_name"],
            profile=profile,
            start_date=start_date,
            end_date=end_date,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            export_start_timeout_seconds=export_start_timeout_seconds,
            export_timeout_seconds=args.export_timeout_seconds,
        )

    if interaction_mode == "mouse":
        return export_store_via_mouse(
            store_name=store["store_name"],
            profile=profile,
            start_date=start_date,
            end_date=end_date,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            export_start_timeout_seconds=export_start_timeout_seconds,
            export_timeout_seconds=args.export_timeout_seconds,
        )

    if interaction_mode == "auto":
        try:
            return export_store_via_ax(
                store_name=store["store_name"],
                profile=profile,
                start_date=start_date,
                end_date=end_date,
                desktop_dir=desktop_dir,
                downloads_dir=downloads_dir,
                output_dir=output_dir,
                export_start_timeout_seconds=export_start_timeout_seconds,
                export_timeout_seconds=args.export_timeout_seconds,
            )
        except ExportStartTimeoutError as ax_exc:
            log_step(f"AX 首轮未看到导出开始，重开页面后重试：{ax_exc}")
            try:
                return export_store_via_ax(
                    store_name=store["store_name"],
                    profile=profile,
                    start_date=start_date,
                    end_date=end_date,
                    desktop_dir=desktop_dir,
                    downloads_dir=downloads_dir,
                    output_dir=output_dir,
                    export_start_timeout_seconds=export_start_timeout_seconds,
                    export_timeout_seconds=args.export_timeout_seconds,
                )
            except Exception as retry_exc:
                log_step(f"AX 重开重试失败，切换鼠标兜底：{retry_exc}")
        except Exception as ax_exc:
            log_step(f"AX 失败，切换鼠标兜底：{ax_exc}")
        return export_store_via_mouse(
            store_name=store["store_name"],
            profile=profile,
            start_date=start_date,
            end_date=end_date,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            export_start_timeout_seconds=export_start_timeout_seconds,
            export_timeout_seconds=args.export_timeout_seconds,
        )

    if interaction_mode != "browser_js":
        raise ReviewSyncError(f"不支持的导出交互方式：{interaction_mode}")

    return export_store_via_browser_js(
        store_name=store["store_name"],
        profile=profile,
        start_date=start_date,
        end_date=end_date,
        desktop_dir=desktop_dir,
        downloads_dir=downloads_dir,
        output_dir=output_dir,
        export_start_timeout_seconds=export_start_timeout_seconds,
        export_timeout_seconds=args.export_timeout_seconds,
    )


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


def render_export_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"已为 {payload['store_name']} 导出评价 CSV",
            f"执行方式：{payload.get('interaction_mode', 'unknown')}",
            f"日期范围：{payload['start_date']} ~ {payload['end_date']}",
            f"来源文件：{payload['source_file']}",
            f"保存为：{payload['saved_file']}",
        ]
    )


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

        if args.command == "export-store":
            payload = export_store(args)
            output_path = maybe_write_output(args.output, payload)
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(render_export_text(payload))
                if output_path:
                    print(f"结果文件：{output_path}")
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
