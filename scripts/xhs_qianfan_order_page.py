from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ORDER_NO_PATTERN = re.compile(r"编号：\s*(P\d+)")
SPEC_PATTERN = re.compile(r"规格：\s*(.+)")
RESULT_COUNT_PATTERN = re.compile(r"查询到\s*(\d+)\s*项")
PURE_ORDER_NO_PATTERN = re.compile(r"^P\d+$")
KNOWN_ORDER_STATUS_TEXTS = {"待发货", "已取消", "已发货", "已签收", "部分发货", "已发货未签收"}


@dataclass(frozen=True)
class OrderPageControls:
    search_field_index: int
    query_button_index: int
    reset_button_index: int | None


@dataclass(frozen=True)
class OrderPageMatch:
    order_no: str
    spec_text: str
    status_text: str


@dataclass(frozen=True)
class _TextNode:
    index: int
    role: str
    text: str
    position: tuple[int, int] | None
    size: tuple[int, int] | None


def _element_texts(element: Any) -> list[str]:
    return [part for part in (getattr(element, "title", ""), getattr(element, "description", ""), getattr(element, "value", "")) if part]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _node_x(node: _TextNode) -> int:
    return int(node.position[0]) if node.position else 0


def _node_y(node: _TextNode) -> int:
    return int(node.position[1]) if node.position else 0


def _node_width(node: _TextNode) -> int:
    return int(node.size[0]) if node.size else 0


def _collect_text_nodes(snapshot: dict[str, Any]) -> list[_TextNode]:
    seen: set[tuple[str, str, tuple[int, int] | None]] = set()
    nodes: list[_TextNode] = []
    for element in snapshot.get("elements", []):
        for text in _element_texts(element):
            clean = str(text or "").strip()
            if not clean:
                continue
            key = (getattr(element, "role", ""), clean, getattr(element, "position", None))
            if key in seen:
                continue
            seen.add(key)
            nodes.append(
                _TextNode(
                    index=getattr(element, "index", -1),
                    role=getattr(element, "role", ""),
                    text=clean,
                    position=getattr(element, "position", None),
                    size=getattr(element, "size", None),
                )
            )
    return nodes


def locate_order_page_controls(snapshot: dict[str, Any]) -> OrderPageControls:
    search_field_index: int | None = None
    query_button_index: int | None = None
    reset_button_index: int | None = None
    quick_filter_y: int | None = None

    for node in _collect_text_nodes(snapshot):
        if "快捷筛选" in node.text and node.position is not None:
            quick_filter_y = _node_y(node)
            break

    field_candidates = []
    for element in snapshot.get("elements", []):
        role = getattr(element, "role", "")
        merged = " ".join(_element_texts(element))
        if role != "AXTextField" or "地址和搜索栏" in merged:
            continue
        position = getattr(element, "position", None)
        size = getattr(element, "size", None)
        x = int(position[0]) if position else 0
        y = int(position[1]) if position else 0
        width = int(size[0]) if size else 0
        value = str(getattr(element, "value", "") or "")
        score = 0
        if width >= 600:
            score += 8
        elif width >= 300:
            score += 5
        elif width >= 150:
            score += 2
        if quick_filter_y is not None:
            if quick_filter_y + 20 <= y <= quick_filter_y + 80:
                score += 8
            elif quick_filter_y + 20 <= y <= quick_filter_y + 180:
                score += 3
        if x <= 600:
            score += 2
        if not re.match(r"^\d{4}-\d{2}-\d{2}", value):
            score += 2
        field_candidates.append((score, -width, abs((quick_filter_y or y) - y), getattr(element, "index", -1)))

    if field_candidates:
        field_candidates.sort(reverse=True)
        search_field_index = field_candidates[0][3]

    search_field = next(
        (element for element in snapshot.get("elements", []) if getattr(element, "index", None) == search_field_index),
        None,
    )
    search_y = int(getattr(search_field, "position", (0, 0))[1]) if search_field and getattr(search_field, "position", None) else 0
    search_x = int(getattr(search_field, "position", (0, 0))[0]) if search_field and getattr(search_field, "position", None) else 0

    button_candidates: list[tuple[int, int, int]] = []
    reset_candidates: list[tuple[int, int, int]] = []
    for element in snapshot.get("elements", []):
        if getattr(element, "role", "") != "AXButton":
            continue
        label = _normalize(" ".join(_element_texts(element)))
        position = getattr(element, "position", None)
        x = int(position[0]) if position else 0
        y = int(position[1]) if position else 0
        if label == "查询":
            score = 0
            if search_field_index is not None and x > search_x:
                score += 5
            if search_field_index is not None and abs(y - search_y) <= 12:
                score += 8
            elif search_field_index is not None and abs(y - search_y) <= 50:
                score += 4
            button_candidates.append((score, -x, getattr(element, "index", -1)))
        if label == "重置":
            score = 0
            if search_field_index is not None and x > search_x:
                score += 4
            if search_field_index is not None and abs(y - search_y) <= 12:
                score += 8
            elif search_field_index is not None and abs(y - search_y) <= 50:
                score += 4
            reset_candidates.append((score, -x, getattr(element, "index", -1)))

    if button_candidates:
        button_candidates.sort(reverse=True)
        query_button_index = button_candidates[0][2]
    if reset_candidates:
        reset_candidates.sort(reverse=True)
        reset_button_index = reset_candidates[0][2]

    if search_field_index is None:
        raise ValueError("没有定位到订单查询搜索框。")
    if query_button_index is None:
        raise ValueError("没有定位到订单查询按钮。")
    return OrderPageControls(
        search_field_index=search_field_index,
        query_button_index=query_button_index,
        reset_button_index=reset_button_index,
    )


def extract_order_page_matches(snapshot: dict[str, Any]) -> list[OrderPageMatch]:
    text_nodes = _collect_text_nodes(snapshot)
    order_nodes = [node for node in text_nodes if PURE_ORDER_NO_PATTERN.fullmatch(node.text)]
    spec_nodes = []
    status_nodes = []

    for node in text_nodes:
        spec_match = SPEC_PATTERN.search(node.text)
        if spec_match:
            spec_nodes.append((node, spec_match.group(1).strip()))
            continue
        normalized = _normalize(node.text)
        if normalized in KNOWN_ORDER_STATUS_TEXTS:
            status_nodes.append(node)

    matches: dict[str, OrderPageMatch] = {}
    for order_node in sorted(order_nodes, key=lambda item: (_node_y(item), _node_x(item), item.index)):
        best_spec = ""
        best_spec_score: tuple[int, int, int] | None = None
        order_x = _node_x(order_node)
        order_y = _node_y(order_node)
        for spec_node, spec_text in spec_nodes:
            spec_x = _node_x(spec_node)
            spec_y = _node_y(spec_node)
            if spec_y < order_y + 20 or spec_y > order_y + 90:
                continue
            if spec_x < order_x + 120:
                continue
            score = (-(abs(spec_y - (order_y + 40))), -(spec_x - order_x), -spec_node.index)
            if best_spec_score is None or score > best_spec_score:
                best_spec_score = score
                best_spec = spec_text

        best_status = ""
        best_status_score: tuple[int, int] | None = None
        for status_node in status_nodes:
            status_x = _node_x(status_node)
            status_y = _node_y(status_node)
            if abs(status_y - order_y) > 24:
                continue
            if status_x < order_x + 160:
                continue
            score = (-(abs(status_y - order_y)), -(status_x - order_x))
            if best_status_score is None or score > best_status_score:
                best_status_score = score
                best_status = status_node.text

        if not best_spec:
            continue

        current = matches.get(order_node.text)
        candidate = OrderPageMatch(order_no=order_node.text, spec_text=best_spec, status_text=best_status)
        if current is None:
            matches[order_node.text] = candidate
            continue
        if len(candidate.spec_text) > len(current.spec_text):
            matches[order_node.text] = candidate

    return list(matches.values())


def find_order_spec(snapshot: dict[str, Any], order_no: str) -> str:
    normalized_order_no = order_no.strip()
    for match in extract_order_page_matches(snapshot):
        if match.order_no == normalized_order_no:
            return match.spec_text
    result_count = extract_result_count(snapshot)
    matches = extract_order_page_matches(snapshot)
    if result_count == 1 and len(matches) == 1:
        return matches[0].spec_text
    raise ValueError(f"当前页面没有找到订单 {normalized_order_no} 的规格。")


def extract_result_count(snapshot: dict[str, Any]) -> int | None:
    for element in snapshot.get("elements", []):
        for text in _element_texts(element):
            matched = RESULT_COUNT_PATTERN.search(text)
            if matched:
                return int(matched.group(1))
    return None
