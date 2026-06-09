#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping


DEFAULT_SHARED_ENV_PATH = Path.home() / ".ai-copy.env"
FEISHU_BASE_TOKEN_ENV_VARS = (
    "OPERATIONS_AUTOMATION_FEISHU_BASE_TOKEN",
    "AI_COPY_FEISHU_BASE_TOKEN",
)

ENV_ASSIGNMENT_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _strip_wrapping_quotes(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_shared_env_values(env_file: Path | None = None) -> dict[str, str]:
    target = (env_file or DEFAULT_SHARED_ENV_PATH).expanduser()
    if not target.exists():
        return {}

    values: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ENV_ASSIGNMENT_RE.match(stripped)
        if not match:
            continue
        values[match.group(1)] = _strip_wrapping_quotes(match.group(2))
    return values


def resolve_feishu_base_token(
    explicit_token: str,
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> str:
    if explicit_token.strip():
        return explicit_token.strip()

    env_values = os.environ if env is None else env
    for key in FEISHU_BASE_TOKEN_ENV_VARS:
        value = str(env_values.get(key, "")).strip()
        if value:
            return value

    file_values = load_shared_env_values(env_file)
    for key in FEISHU_BASE_TOKEN_ENV_VARS:
        value = str(file_values.get(key, "")).strip()
        if value:
            return value

    env_file_path = str((env_file or DEFAULT_SHARED_ENV_PATH).expanduser())
    raise RuntimeError(
        "缺少飞书 base token。请通过 --base-token、环境变量 "
        f"{FEISHU_BASE_TOKEN_ENV_VARS[0]}，或本机共享环境文件 {env_file_path} 提供。"
    )
