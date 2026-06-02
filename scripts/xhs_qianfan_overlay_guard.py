from __future__ import annotations

import json
import re
from typing import Any, Callable


SAFE_DISMISS_BUTTON_TEXTS = (
    "关闭",
    "取消",
    "知道了",
    "我知道了",
    "稍后",
    "暂不",
    "跳过",
    "以后再说",
    "下次再说",
    "继续浏览",
    "继续逛逛",
    "以后再参与",
    "以后再看",
    "暂时不要",
    "不用了",
    "不了",
)
UNSAFE_CONFIRM_BUTTON_TEXTS = (
    "去参与",
    "立即参与",
    "马上参与",
    "去开通",
    "立即开通",
    "去设置",
    "确定",
    "确认",
    "提交",
    "保存",
    "领取",
    "报名",
    "参加",
    "参与",
    "开通",
    "下一步",
)
OVERLAY_HINT_TEXTS = (
    "活动",
    "计划",
    "奖励",
    "流量",
    "弹窗",
    "公告",
    "提示",
    "值得更多",
    "引导",
)


def normalize_action_label(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def is_safe_dismiss_label(label: str) -> bool:
    normalized = normalize_action_label(label)
    if not normalized:
        return False
    if any(token in normalized for token in UNSAFE_CONFIRM_BUTTON_TEXTS):
        return False
    return any(token in normalized for token in SAFE_DISMISS_BUTTON_TEXTS)


def build_dismiss_front_window_obstructions_script() -> str:
    safe_texts = json.dumps(list(SAFE_DISMISS_BUTTON_TEXTS), ensure_ascii=False)
    unsafe_texts = json.dumps(list(UNSAFE_CONFIRM_BUTTON_TEXTS), ensure_ascii=False)
    return f"""
(() => {{
  const safeTexts = new Set({safe_texts}.map((item) => String(item || '').replace(/\\s+/g, '')));
  const unsafeTexts = new Set({unsafe_texts}.map((item) => String(item || '').replace(/\\s+/g, '')));
  function normalize(text) {{
    return String(text || '').replace(/\\s+/g, '');
  }}
  function visible(node) {{
    if (!node) {{
      return false;
    }}
    const style = window.getComputedStyle(node);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none') {{
      return false;
    }}
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }}
  function isSafeLabel(text) {{
    const normalized = normalize(text);
    if (!normalized || unsafeTexts.has(normalized)) {{
      return false;
    }}
    if (safeTexts.has(normalized)) {{
      return true;
    }}
    for (const item of safeTexts) {{
      if (item && normalized.includes(item)) {{
        return true;
      }}
    }}
    return false;
  }}
  function clickNode(node) {{
    if (!node || typeof node.click !== 'function') {{
      return false;
    }}
    node.dispatchEvent(new MouseEvent('mouseover', {{ bubbles: true, cancelable: true, view: window }}));
    node.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
    node.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
    node.click();
    return true;
  }}
  function collectRoots() {{
    const selectors = [
      '[role="dialog"]',
      '[aria-modal="true"]',
      '.d-modal-mask',
      '.d-modal',
      '.ant-modal-root',
      '.ant-modal-wrap',
      '.ant-modal',
      '.semi-modal',
      '.semi-portal',
      '[class*="modal"]',
      '[class*="dialog"]',
      '[class*="popup"]',
      '[class*="mask"]'
    ];
    const seen = new Set();
    return Array.from(document.querySelectorAll(selectors.join(',')))
      .filter((node) => node && node !== document.body && node !== document.documentElement && visible(node))
      .filter((node) => {{
        const key = node.outerHTML ? node.outerHTML.slice(0, 120) : String(node);
        if (seen.has(key)) {{
          return false;
        }}
        seen.add(key);
        return true;
      }})
      .sort((left, right) => {{
        const leftZ = Number(window.getComputedStyle(left).zIndex || 0) || 0;
        const rightZ = Number(window.getComputedStyle(right).zIndex || 0) || 0;
        return rightZ - leftZ;
      }});
  }}

  const roots = collectRoots();
  for (const root of roots) {{
    const closeIcon = root.querySelector(
      '.d-modal-close, .ant-modal-close, [aria-label*="关闭"], [title*="关闭"], [class*="close"]'
    );
    if (visible(closeIcon) && clickNode(closeIcon)) {{
      return JSON.stringify({{ ok: true, dismissed: true, strategy: 'close_icon' }});
    }}

    const actions = Array.from(root.querySelectorAll('button, [role="button"], .d-clickable, [class*="close"]'));
    for (const action of actions) {{
      if (!visible(action)) {{
        continue;
      }}
      const label = normalize(
        action.innerText ||
        action.textContent ||
        action.getAttribute('aria-label') ||
        action.getAttribute('title') ||
        ''
      );
      if (isSafeLabel(label) && clickNode(action)) {{
        return JSON.stringify({{ ok: true, dismissed: true, strategy: 'safe_button', label }});
      }}
    }}
  }}
  return JSON.stringify({{ ok: true, dismissed: false, checked_root_count: roots.length }});
}})()
""".strip()


def snapshot_text_pool(snapshot: dict[str, Any]) -> str:
    elements = snapshot.get("elements", [])
    return "\n".join(
        part
        for element in elements
        for part in (
            getattr(element, "title", ""),
            getattr(element, "description", ""),
            getattr(element, "value", ""),
        )
        if part
    )


def dismiss_window_obstructions_via_ax(
    snapshot: dict[str, Any],
    *,
    raise_window: Callable[[dict[str, Any]], None],
    press_front_window_element: Callable[[int], None],
) -> dict[str, Any]:
    text_pool = snapshot_text_pool(snapshot)
    has_overlay_hint = any(keyword in text_pool for keyword in OVERLAY_HINT_TEXTS)
    safe_buttons = []
    unsafe_buttons = []

    for element in snapshot.get("elements", []):
        if getattr(element, "role", "") != "AXButton":
            continue
        label = normalize_action_label(getattr(element, "title", "") or getattr(element, "value", ""))
        if not label:
            continue
        if is_safe_dismiss_label(label):
            safe_buttons.append(element)
        if any(token in label for token in UNSAFE_CONFIRM_BUTTON_TEXTS):
            unsafe_buttons.append(element)

    if not safe_buttons:
        return {"ok": True, "dismissed": False, "strategy": "ax_no_safe_button"}
    if not has_overlay_hint and not unsafe_buttons:
        return {"ok": True, "dismissed": False, "strategy": "ax_not_overlay_like"}

    target = safe_buttons[0]
    raise_window(snapshot)
    press_front_window_element(target.index)
    return {
        "ok": True,
        "dismissed": True,
        "strategy": "ax_safe_button",
        "label": getattr(target, "title", "") or getattr(target, "value", ""),
    }
