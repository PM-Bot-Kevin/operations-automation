#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from xhs_qianfan_access import (
    DEFAULT_LOCAL_STATE_PATH,
    PAGE_URLS,
    ChromeProfile,
    close_new_windows_for_url,
    element_center,
    focus_window_by_url_ax,
    load_profiles,
    open_page,
    press_front_window_element,
    run_front_window_javascript,
    snapshot_window_ids_optional,
    set_front_window_element_value,
    wait_for_front_window,
)
from xhs_qianfan_order_page import find_order_spec, locate_order_page_controls
from xhs_qianfan_sku_normalizer import build_exact_mapping, normalize_sku_value


DEFAULT_BASE_TOKEN = "W0XvbodVPaE854sF42IcnHkIn1d"
DEFAULT_TABLE_ID = "tblUM8AqYDNWvg7z"
DEFAULT_VIEW_ID = "vewbrIBKXE"
DEFAULT_STORE_FIELD = "店铺"
DEFAULT_ORDER_FIELD = "订单号"
DEFAULT_SKU_FIELD = "SKU"
DEFAULT_GUARDRAILS_PATH = REPO_ROOT / "config" / "xhs_qianfan_guardrails.json"
DEFAULT_STORE_PROFILE_CONFIG_PATH = REPO_ROOT / "config" / "xhs_order_query_profiles.json"
DEFAULT_ORDER_QUERY_PAGE_URL = "https://ark.xiaohongshu.com/app-order/order/query"
DEFAULT_INTERACTION_MODES = ("ax", "browser_js", "mouse")
DEFAULT_RUNTIME_DIR = (REPO_ROOT / "runtime" / "sku_fill").resolve()
KNOWN_LARK_CLI_PATHS = [
    Path.home() / ".codex/skills/fill-product-db/node_modules/@larksuite/cli/bin/lark-cli",
]
FILL_INTENT_KEYWORDS = ("sku", "规格")
FILL_ACTION_KEYWORDS = ("补", "填", "回写", "更新", "同步", "查", "查询")


class FillSkuError(RuntimeError):
    pass


def log_step(message: str) -> None:
    print(f"[fill-sku] {message}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class MissingSkuRecord:
    record_id: str
    store_name: str
    order_no: str
    profile_directory: str | None
    profile_name: str | None
    profile_user_name: str | None
    profile_match_source: str


@dataclass(frozen=True)
class StoreProfileOverride:
    store_name: str
    profile_directory: str
    profile_name: str
    enabled: bool = True


def irregular_pause(min_seconds: float, max_seconds: float) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


def load_guardrails() -> dict[str, Any]:
    if not DEFAULT_GUARDRAILS_PATH.exists():
        raise FillSkuError(f"缺少千帆风控配置：{DEFAULT_GUARDRAILS_PATH}")
    return json.loads(DEFAULT_GUARDRAILS_PATH.read_text(encoding="utf-8"))


def load_store_profile_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FillSkuError(f"缺少店铺 profile 配置：{config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FillSkuError("店铺 profile 配置格式不对，根节点必须是对象。")
    return payload


def load_sku_exact_mapping(config: dict[str, Any]) -> dict[str, str]:
    try:
        return build_exact_mapping(config)
    except ValueError as exc:
        raise FillSkuError(str(exc)) from exc


def build_store_profile_overrides(config: dict[str, Any]) -> dict[str, StoreProfileOverride]:
    stores = config.get("stores", [])
    if not isinstance(stores, list):
        raise FillSkuError("店铺 profile 配置格式不对，stores 必须是数组。")

    overrides: dict[str, StoreProfileOverride] = {}
    for index, item in enumerate(stores, start=1):
        if not isinstance(item, dict):
            raise FillSkuError(f"店铺 profile 配置第 {index} 项不是对象。")
        store_name = str(item.get("store_name", "")).strip()
        profile_directory = str(item.get("profile_directory", "")).strip()
        profile_name = str(item.get("profile_name", "")).strip() or store_name
        enabled = bool(item.get("enabled", True))
        if not store_name:
            raise FillSkuError(f"店铺 profile 配置第 {index} 项缺少 store_name。")
        if enabled and not profile_directory:
            raise FillSkuError(f"店铺 profile 配置第 {index} 项缺少 profile_directory。")
        overrides[store_name] = StoreProfileOverride(
            store_name=store_name,
            profile_directory=profile_directory,
            profile_name=profile_name,
            enabled=enabled,
        )
    return overrides


def resolve_profile_via_override(
    profiles: list[ChromeProfile],
    override: StoreProfileOverride,
) -> ChromeProfile:
    if not override.enabled:
        raise FillSkuError(f"店铺“{override.store_name}”在店铺 profile 配置里被禁用了。")
    for profile in profiles:
        if profile.directory == override.profile_directory:
            return profile
    raise FillSkuError(
        f"店铺“{override.store_name}”指定的 profile_directory 不存在：{override.profile_directory}"
    )


def chunk_orders(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[index:index + size] for index in range(0, len(items), size)]


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
    plan_parser.add_argument(
        "--store-profile-config",
        default=str(DEFAULT_STORE_PROFILE_CONFIG_PATH),
        help="店铺和 Chrome profile 的正式映射配置。",
    )
    plan_parser.add_argument("--store", default="", help="只看某个店铺，便于单店低频执行")
    plan_parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式，默认 text")
    plan_parser.add_argument("--output", default="", help="可选，把计划 JSON 另存到文件")
    plan_parser.add_argument(
        "--lark-cli-bin",
        default=os.environ.get("LARK_CLI_BIN", ""),
        help="可选，显式指定 lark-cli 路径。",
    )

    query_parser = subparsers.add_parser("query", help="按计划去统一订单查询页只读慢查真实规格，生成待回写结果")
    query_parser.add_argument("--plan-file", required=True, help="plan 产生的 JSON 文件")
    query_parser.add_argument("--store", default="", help="只处理某个店铺；如果计划里只有一个店铺，可省略")
    query_parser.add_argument(
        "--interaction-mode",
        choices=("auto", "ax", "browser_js", "mouse"),
        default="auto",
        help="订单查询交互方式。默认先走 ax，再降级 browser_js 和 mouse。",
    )
    query_parser.add_argument(
        "--local-state-path",
        default=str(DEFAULT_LOCAL_STATE_PATH),
        help="Chrome Local State 路径，默认读取本机 Google Chrome 配置",
    )
    query_parser.add_argument(
        "--runtime-dir",
        default=str(DEFAULT_RUNTIME_DIR),
        help="运行时产物目录，默认写入 runtime/sku_fill",
    )
    query_parser.add_argument("--output", default="", help="可选，显式指定待回写 JSON 输出文件")
    query_parser.add_argument("--max-rounds", type=int, default=0, help="最多执行多少轮；默认 0 表示按计划全部执行")
    query_parser.add_argument("--max-orders", type=int, default=0, help="最多查询多少单；默认 0 表示按计划全部执行")

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


def resolve_store_profile(
    *,
    store_name: str,
    profiles: list[ChromeProfile],
    overrides: dict[str, StoreProfileOverride],
    allow_auto_match: bool = False,
) -> tuple[ChromeProfile, str]:
    override = overrides.get(store_name)
    if override is not None:
        return resolve_profile_via_override(profiles, override), "config"
    if not allow_auto_match:
        raise FillSkuError(
            f"店铺“{store_name}”还没有写入正式 profile 配置：{DEFAULT_STORE_PROFILE_CONFIG_PATH}"
        )
    return resolve_profile(profiles, store_name), "auto"


def load_plan_file(plan_path: Path) -> dict[str, Any]:
    if not plan_path.exists():
        raise FillSkuError(f"找不到计划文件：{plan_path}")
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FillSkuError("计划文件格式不对。")
    return payload


def select_store_plan(plan: dict[str, Any], store_name: str) -> dict[str, Any]:
    stores = plan.get("stores", [])
    if not isinstance(stores, list) or not stores:
        raise FillSkuError("计划文件里没有可执行的店铺。")
    if store_name:
        for item in stores:
            if item.get("store_name") == store_name:
                return item
        raise FillSkuError(f"计划文件里没有店铺：{store_name}")
    if len(stores) == 1:
        return stores[0]
    names = " / ".join(str(item.get("store_name", "")) for item in stores)
    raise FillSkuError(f"计划里涉及多个店铺，请显式指定 --store。当前有：{names}")


def select_store_records(plan: dict[str, Any], store_name: str) -> list[dict[str, Any]]:
    records = plan.get("records", [])
    selected = [item for item in records if item.get("store_name") == store_name]
    if not selected:
        raise FillSkuError(f"计划文件里没有店铺“{store_name}”的缺 SKU 订单。")
    return selected


def build_order_query_runtime_paths(runtime_dir: Path, store_name: str) -> tuple[Path, Path]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_store_name = "".join(char if char.isalnum() else "_" for char in store_name).strip("_") or "store"
    return runtime_dir / f"{stamp}_{safe_store_name}_updates.json", runtime_dir / "latest_updates.json"


def focus_order_window_if_possible() -> None:
    try:
        focus_window_by_url_ax(PAGE_URLS["orders"])
    except Exception:
        return


def wait_for_order_page(store_name: str) -> dict[str, Any]:
    return wait_for_front_window(
        title_contains=store_name,
        url_contains=PAGE_URLS["orders"],
        required_texts=("订单管理", "查询"),
        timeout_seconds=35,
    )


def ensure_order_page_window(store_name: str, profile: ChromeProfile) -> dict[str, Any]:
    try:
        return wait_for_front_window(
            title_contains=store_name,
            url_contains=PAGE_URLS["orders"],
            required_texts=("订单管理", "查询"),
            timeout_seconds=5,
            poll_seconds=0.8,
        )
    except Exception:
        open_page(profile, "orders", dry_run=False)
        irregular_pause(3.0, 6.0)
        focus_order_window_if_possible()
        return wait_for_order_page(store_name)


def build_order_query_script(order_no: str) -> str:
    order_json = json.dumps(order_no, ensure_ascii=False)
    return f"""
(() => {{
  function visible(node) {{
    if (!node) return false;
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }}
  function normalize(text) {{
    return String(text || '').replace(/\\s+/g, '');
  }}
  function setValue(input, value) {{
    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (descriptor && descriptor.set) {{
      descriptor.set.call(input, value);
    }} else {{
      input.value = value;
    }}
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }}
  const target = {order_json};
  const input = Array.from(document.querySelectorAll('input')).find((node) => visible(node) && String(node.placeholder || '').includes('支持搜索订单号'));
  if (!input) {{
    return JSON.stringify({{ ok: false, error: '找不到订单查询搜索框' }});
  }}
  const button = Array.from(document.querySelectorAll('button')).find((node) => visible(node) && normalize(node.innerText || node.textContent) === '查询');
  if (!button) {{
    return JSON.stringify({{ ok: false, error: '找不到查询按钮' }});
  }}
  setValue(input, target);
  button.click();
  return JSON.stringify({{ ok: true, orderNo: target }});
}})()
""".strip()


def build_order_extract_script(order_no: str) -> str:
    order_json = json.dumps(order_no, ensure_ascii=False)
    return f"""
(() => {{
  const target = {order_json};
  const bodyText = String((document.body && document.body.innerText) || '');
  const orderIndex = bodyText.indexOf(target);
  if (orderIndex < 0) {{
    return JSON.stringify({{ ok: false, error: '页面没有命中目标订单', orderNo: target }});
  }}
  const slice = bodyText.slice(orderIndex, orderIndex + 800);
  const matched = slice.match(/规格：\\s*([^\\n]+)/);
  if (!matched) {{
    return JSON.stringify({{ ok: false, error: '命中订单后没有找到规格文本', orderNo: target, slice }});
  }}
  return JSON.stringify({{ ok: true, orderNo: target, specText: String(matched[1] || '').trim() }});
}})()
""".strip()


def run_front_window_json(script: str) -> dict[str, Any]:
    try:
        raw = run_front_window_javascript(script)
    except Exception as exc:
        raise FillSkuError(f"Chrome 页内执行失败：{exc}") from exc
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise FillSkuError(f"无法解析 Chrome 页内返回：{raw[:200]}") from exc


def ensure_browser_js_ok(result: dict[str, Any], *, action: str) -> dict[str, Any]:
    if result.get("ok"):
        return result
    detail = str(result.get("error", "")).strip() or "未知错误"
    raise FillSkuError(f"{action}失败：{detail}")


def query_order_spec_via_ax(order_no: str, store_name: str) -> str:
    snapshot = wait_for_order_page(store_name)
    controls = locate_order_page_controls(snapshot)
    set_front_window_element_value(controls.search_field_index, order_no)
    irregular_pause(0.6, 1.2)
    press_front_window_element(controls.query_button_index)
    irregular_pause(4.0, 7.0)
    result_snapshot = wait_for_order_page(store_name)
    return find_order_spec(result_snapshot, order_no)


def query_order_spec_via_browser_js(order_no: str, store_name: str) -> str:
    wait_for_order_page(store_name)
    ensure_browser_js_ok(run_front_window_json(build_order_query_script(order_no)), action="页内搜索订单")
    irregular_pause(4.0, 7.0)
    result = ensure_browser_js_ok(run_front_window_json(build_order_extract_script(order_no)), action="页内提取规格")
    return str(result.get("specText", "")).strip()


def _load_pyautogui() -> Any:
    try:
        import pyautogui  # type: ignore
    except Exception as exc:
        raise FillSkuError(f"当前环境缺少 pyautogui，无法执行鼠标兜底：{exc}") from exc
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = True
    return pyautogui


def move_and_click(pyautogui: Any, point: tuple[int, int]) -> None:
    x, y = point
    pyautogui.moveTo(x + random.randint(-2, 2), y + random.randint(-2, 2), duration=random.uniform(0.18, 0.55))
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


def query_order_spec_via_mouse(order_no: str, store_name: str) -> str:
    pyautogui = _load_pyautogui()
    snapshot = wait_for_order_page(store_name)
    controls = locate_order_page_controls(snapshot)
    search_field = next((element for element in snapshot["elements"] if element.index == controls.search_field_index), None)
    query_button = next((element for element in snapshot["elements"] if element.index == controls.query_button_index), None)
    if search_field is None or query_button is None:
        raise FillSkuError("鼠标兜底没有定位到订单查询控件。")
    replace_text(pyautogui, element_center(search_field), order_no)
    irregular_pause(0.5, 1.0)
    move_and_click(pyautogui, element_center(query_button))
    irregular_pause(4.0, 7.0)
    result_snapshot = wait_for_order_page(store_name)
    return find_order_spec(result_snapshot, order_no)


def query_order_spec(order_no: str, store_name: str, interaction_mode: str) -> tuple[str, str]:
    if interaction_mode == "ax":
        return query_order_spec_via_ax(order_no, store_name), "ax"
    if interaction_mode == "browser_js":
        return query_order_spec_via_browser_js(order_no, store_name), "browser_js"
    if interaction_mode == "mouse":
        return query_order_spec_via_mouse(order_no, store_name), "mouse"

    errors: list[str] = []
    for mode in DEFAULT_INTERACTION_MODES:
        try:
            return query_order_spec(order_no, store_name, mode)
        except Exception as exc:
            errors.append(f"{mode}: {exc}")
    raise FillSkuError(f"订单 {order_no} 三层读取都失败：{' | '.join(errors)}")


def query_store_orders(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = Path(args.plan_file).expanduser().resolve()
    plan = load_plan_file(plan_path)
    store = select_store_plan(plan, args.store)
    store_name = str(store.get("store_name", "")).strip()
    if not store_name:
        raise FillSkuError("计划里的店铺名为空。")

    records = select_store_records(plan, store_name)
    record_by_order = {str(item["order_no"]): item for item in records}
    local_state_path = Path(args.local_state_path).expanduser().resolve()
    profiles = load_profiles(local_state_path)
    profile_config_path = Path(
        str(
            plan.get("order_query", {}).get("store_profile_config_path")
            or DEFAULT_STORE_PROFILE_CONFIG_PATH
        )
    ).expanduser().resolve()
    store_profile_config = load_store_profile_config(profile_config_path)
    store_profile_overrides = build_store_profile_overrides(store_profile_config)
    sku_exact_mapping = load_sku_exact_mapping(store_profile_config)
    profile, _match_source = resolve_store_profile(
        store_name=store_name,
        profiles=profiles,
        overrides=store_profile_overrides,
        allow_auto_match=False,
    )
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    output_path, latest_output_path = build_order_query_runtime_paths(runtime_dir, store_name)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()

    rounds = list(store.get("suggested_rounds", []))
    if args.max_rounds > 0:
        rounds = rounds[: args.max_rounds]
    if not rounds:
        raise FillSkuError("计划里没有可执行轮次。")

    previous_window_ids = snapshot_window_ids_optional()
    try:
        ensure_order_page_window(store_name, profile)

        updates: list[dict[str, str]] = []
        warnings: list[str] = []
        processed_orders = 0
        for round_index, round_orders in enumerate(rounds, start=1):
            if args.max_orders > 0 and processed_orders >= args.max_orders:
                break
            wait_for_order_page(store_name)
            for order_no in round_orders:
                if args.max_orders > 0 and processed_orders >= args.max_orders:
                    break
                record = record_by_order.get(order_no)
                if not record:
                    warnings.append(f"计划里找不到订单 {order_no} 的 record_id，已跳过。")
                    continue
                spec_text, used_mode = query_order_spec(order_no, store_name, args.interaction_mode)
                normalized = normalize_sku_value(spec_text, sku_exact_mapping)
                updates.append(
                    {
                        "record_id": str(record["record_id"]),
                        "order_no": order_no,
                        "store_name": store_name,
                        "sku_value": normalized.sku_value,
                        "raw_spec_text": normalized.raw_spec_text,
                        "normalized_spec_key": normalized.normalized_key,
                        "normalization_matched": normalized.matched,
                        "interaction_mode": used_mode,
                    }
                )
                processed_orders += 1
                irregular_pause(2.5, 5.5)
            if round_index < len(rounds) and (args.max_orders <= 0 or processed_orders < args.max_orders):
                irregular_pause(15.0, 28.0)

        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "plan_file": str(plan_path),
            "store_name": store_name,
            "profile_directory": profile.directory,
            "sku_normalization": {
                "exact_mapping_count": len(sku_exact_mapping),
            },
            "updates": updates,
            "warnings": warnings,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        output_path.write_text(text, encoding="utf-8")
        latest_output_path.write_text(text, encoding="utf-8")
        return payload
    finally:
        close_new_windows_for_url(
            previous_window_ids,
            target_url_contains=PAGE_URLS["orders"],
            log_step=log_step,
        )


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    ensure_fill_intent(" ".join(args.query))
    lark_cli_bin = resolve_lark_cli(args.lark_cli_bin)
    guardrails = load_guardrails()
    profile_config_path = Path(args.store_profile_config).expanduser().resolve()
    store_profile_config = load_store_profile_config(profile_config_path)
    store_profile_overrides = build_store_profile_overrides(store_profile_config)
    execution_defaults = guardrails.get("execution_defaults", {})
    max_orders_per_round = int(execution_defaults.get("max_orders_per_round", 5) or 5)
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
    store_profile_sources: dict[str, str] = {}

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
        profile_match_source = "none"
        if store_name:
            if store_name not in store_profiles:
                try:
                    resolved_profile, match_source = resolve_store_profile(
                        store_name=store_name,
                        profiles=profiles,
                        overrides=store_profile_overrides,
                        allow_auto_match=False,
                    )
                    store_profiles[store_name] = resolved_profile
                    store_profile_sources[store_name] = match_source
                except Exception as exc:
                    store_profiles[store_name] = None
                    store_profile_sources[store_name] = "none"
                    warnings.append(f"店铺“{store_name}”没有匹配到唯一的 Chrome 资料：{exc}")
            profile = store_profiles[store_name]
            profile_match_source = store_profile_sources.get(store_name, "none")
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
                profile_match_source=profile_match_source,
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
        orders = [record.order_no for record in batch]
        stores.append(
            {
                "store_name": store_name,
                "order_count": len(batch),
                "profile": profile_to_dict(profile),
                "profile_match_source": store_profile_sources.get(batch[0].store_name, "none")
                if batch[0].store_name
                else "none",
                "orders": orders,
                "suggested_rounds": chunk_orders(orders, max_orders_per_round),
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "guardrails": {
            "policy_name": guardrails.get("policy_name", ""),
            "max_orders_per_round": max_orders_per_round,
            "single_store_only": bool(execution_defaults.get("single_store_only", True)),
            "require_round_break": bool(execution_defaults.get("require_round_break", True)),
            "fixed_interval_forbidden": bool(execution_defaults.get("fixed_interval_forbidden", True)),
        },
        "order_query": {
            "page_url": str(store_profile_config.get("order_query_page_url", DEFAULT_ORDER_QUERY_PAGE_URL)),
            "primary_interaction_mode": str(
                store_profile_config.get("primary_interaction_mode", DEFAULT_INTERACTION_MODES[0])
            ),
            "fallback_interaction_modes": list(
                store_profile_config.get("fallback_interaction_modes", list(DEFAULT_INTERACTION_MODES[1:]))
            ),
            "store_profile_config_path": str(profile_config_path),
            "sku_normalization": {
                "strategy": "exact_mapping_then_fallback_raw_spec",
                "exact_mapping_count": len(load_sku_exact_mapping(store_profile_config)),
            },
        },
        "execution_strategy": {
            "workflow": ["plan", "query_order_page", "normalize_sku", "apply"],
            "window_binding": "按 profile + 统一订单页 URL 重绑目标窗口，不依赖用户当前 tab",
            "query_scope": "所有店铺统一走订单查询页 URL，只是 Chrome profile 不同",
            "interaction_modes": list(DEFAULT_INTERACTION_MODES),
        },
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
        f"默认每轮最多 {plan['guardrails']['max_orders_per_round']} 单",
        "正式主备：ax -> browser_js -> mouse",
        f"统一订单页：{plan['order_query']['page_url']}",
    ]
    for store in plan["stores"]:
        profile = store["profile"]
        if profile:
            profile_text = (
                f"{profile['name']} / {profile['directory']} / 匹配方式 {store['profile_match_source']}"
            )
        else:
            profile_text = "未匹配到 Chrome 资料"
        lines.append(
            f"- {store['store_name']}：{store['order_count']} 条，资料 {profile_text}，建议拆成 {len(store['suggested_rounds'])} 轮"
        )
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

        if args.command == "query":
            payload = query_store_orders(args)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
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
