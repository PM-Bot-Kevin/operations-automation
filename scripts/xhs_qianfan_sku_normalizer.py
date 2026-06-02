from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def normalize_spec_key(value: str) -> str:
    text = str(value or "").strip().replace("\u3000", " ")
    return re.sub(r"\s+", " ", text)


@dataclass(frozen=True)
class SkuNormalizationResult:
    raw_spec_text: str
    normalized_key: str
    sku_value: str
    matched: bool


def build_exact_mapping(config: dict[str, Any]) -> dict[str, str]:
    block = config.get("sku_normalization", {})
    mappings = block.get("exact_mappings", {}) if isinstance(block, dict) else {}
    if not isinstance(mappings, dict):
        raise ValueError("sku_normalization.exact_mappings 必须是对象。")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in mappings.items():
        key = normalize_spec_key(str(raw_key or ""))
        value = str(raw_value or "").strip()
        if not key or not value:
            continue
        normalized[key] = value
    return normalized


def normalize_sku_value(spec_text: str, exact_mapping: dict[str, str]) -> SkuNormalizationResult:
    normalized_key = normalize_spec_key(spec_text)
    mapped = exact_mapping.get(normalized_key, "")
    if mapped:
        return SkuNormalizationResult(
            raw_spec_text=str(spec_text or "").strip(),
            normalized_key=normalized_key,
            sku_value=mapped,
            matched=True,
        )
    return SkuNormalizationResult(
        raw_spec_text=str(spec_text or "").strip(),
        normalized_key=normalized_key,
        sku_value=str(spec_text or "").strip(),
        matched=False,
    )
