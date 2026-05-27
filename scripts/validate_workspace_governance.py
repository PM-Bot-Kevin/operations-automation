#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "workspace_governance.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def check_required_files(config: dict, errors: list[str]) -> None:
    for item in config.get("required_files", []):
        target = REPO_ROOT / item["path"]
        if not target.exists():
            errors.append(f"缺少关键入口: {item['label']} -> {item['path']}")


def check_content_rules(config: dict, errors: list[str]) -> None:
    for rule in config.get("content_rules", []):
        target = REPO_ROOT / rule["path"]
        if not target.exists():
            errors.append(f"规则目标不存在: {rule['label']} -> {rule['path']}")
            continue
        content = target.read_text(encoding="utf-8")
        for fragment in rule.get("must_contain", []):
            if fragment not in content:
                errors.append(f"规则未落实: {rule['label']} 缺少片段 {fragment!r}")


def check_cross_workspace_rules(config: dict, errors: list[str]) -> None:
    cross_workspace = config.get("cross_workspace", {})
    allowed_types = set(cross_workspace.get("allowed_entry_types", []))
    forbidden_keywords = [item.lower() for item in cross_workspace.get("forbidden_keywords", [])]
    for dependency in cross_workspace.get("dependencies", []):
        name = dependency.get("workspace_name", "未命名工作区")
        entry_type = dependency.get("entry_type", "")
        entry_value = " ".join(
            str(dependency.get(key, ""))
            for key in ("entry", "entry_path", "notes")
        ).lower()
        if entry_type not in allowed_types:
            errors.append(f"跨工作区依赖未使用正式入口类型: {name} -> {entry_type}")
        for keyword in forbidden_keywords:
            if keyword and keyword in entry_value:
                errors.append(f"跨工作区依赖命中禁止关键词: {name} -> {keyword}")


def check_branch_policy(config: dict, errors: list[str]) -> None:
    expected_branch = config["workspace"]["long_lived_branch"]
    try:
        current_branch = (
            subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
        )
    except subprocess.CalledProcessError as exc:
        errors.append(f"无法读取当前 Git 分支: {exc}")
        return
    if current_branch and current_branch != expected_branch:
        errors.append(f"当前分支不是治理要求的 {expected_branch}: {current_branch}")


def check_workspace_identity(config: dict, errors: list[str]) -> None:
    workspace = config.get("workspace", {})
    configured_path = workspace.get("absolute_path", "")
    actual_path = str(REPO_ROOT.resolve())
    if not configured_path:
        errors.append("治理配置缺少工作区路径。")
    else:
        configured_resolved = str(Path(configured_path).resolve())
        if configured_resolved != actual_path:
            errors.append(f"治理配置里的工作区路径不匹配: {configured_path} != {actual_path}")

    expected_remote = workspace.get("github_repository_ssh", "")
    if expected_remote and not expected_remote.startswith("git@github.com:"):
        errors.append(f"治理配置里的 GitHub SSH 远端不合法: {expected_remote}")
        return

    if not expected_remote:
        errors.append("治理配置缺少 GitHub SSH 远端。")
        return

    try:
        current_remote = (
            subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
        )
    except subprocess.CalledProcessError as exc:
        errors.append(f"无法读取 origin 远端: {exc}")
        return

    if current_remote != expected_remote:
        errors.append(f"origin 远端与治理配置不一致: {current_remote} != {expected_remote}")


def main() -> int:
    errors: list[str] = []
    if not CONFIG_PATH.exists():
        print(f"治理配置不存在: {CONFIG_PATH}", file=sys.stderr)
        return 1

    config = load_config()
    check_required_files(config, errors)
    check_content_rules(config, errors)
    check_cross_workspace_rules(config, errors)
    check_branch_policy(config, errors)
    check_workspace_identity(config, errors)

    if errors:
        print("工作区治理校验失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("工作区治理校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
