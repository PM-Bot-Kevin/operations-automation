from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_SCRIPT = REPO_ROOT / "scripts" / "validate_workspace_governance.py"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release_workspace.sh"
ROLLBACK_SCRIPT = REPO_ROOT / "scripts" / "rollback_workspace.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "github_backup.sh"
EXPORT_IMAGES_SCRIPT = REPO_ROOT / "scripts" / "export_feishu_order_images.py"
QIANFAN_ACCESS_SCRIPT = REPO_ROOT / "scripts" / "xhs_qianfan_access.py"
FILL_SKUS_SCRIPT = REPO_ROOT / "scripts" / "fill_feishu_order_skus.py"
SYNC_REVIEW_STATUS_SCRIPT = REPO_ROOT / "scripts" / "sync_feishu_review_status.py"
CONFIG_PATH = REPO_ROOT / "config" / "workspace_governance.json"
QIANFAN_GUARDRAILS_PATH = REPO_ROOT / "config" / "xhs_qianfan_guardrails.json"
ORDER_PAGE_SCRIPT = REPO_ROOT / "scripts" / "xhs_qianfan_order_page.py"
SKU_NORMALIZER_SCRIPT = REPO_ROOT / "scripts" / "xhs_qianfan_sku_normalizer.py"


class WorkspaceGovernanceTests(unittest.TestCase):
    def test_qianfan_access_prefers_existing_chrome_profiles(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="chrome-local-state-") as temp_dir:
            local_state = Path(temp_dir) / "Local State"
            local_state.write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 36",
                            "info_cache": {
                                "Profile 32": {"name": "抱树的koala小姐", "user_name": ""},
                                "Profile 36": {"name": "考拉小姐慢慢来", "user_name": ""},
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            profiles = module.load_profiles(local_state)
            self.assertEqual([profile.directory for profile in profiles], ["Profile 32", "Profile 36"])
            resolved = module.resolve_profile(profiles, "考拉小姐慢慢来的店")
            self.assertEqual(resolved.directory, "Profile 36")
            self.assertIn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", module.open_page(resolved, "orders", dry_run=True))
            self.assertIn("--profile-directory=Profile 36", module.open_page(resolved, "orders", dry_run=True))
            self.assertIn("--new-window", module.open_page(resolved, "orders", dry_run=True))
            self.assertIn("app-item/comment/analysis", module.open_page(resolved, "comments", dry_run=True))

    def test_qianfan_access_element_center_uses_position_and_size(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        element = module.ChromeUiElement(
            index=1,
            role="AXButton",
            title="搜索",
            description="",
            value="",
            position=(100, 200),
            size=(60, 20),
        )
        self.assertEqual(module.element_center(element), (130, 210))

    def test_qianfan_access_runs_front_window_javascript_via_osascript(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with mock.patch.object(module.subprocess, "run") as mocked_run:
            mocked_run.return_value = subprocess.CompletedProcess(
                args=["osascript"],
                returncode=0,
                stdout='{"ok":true}\n',
                stderr="",
            )
            result = module.run_front_window_javascript("JSON.stringify({ok:true})")

        self.assertEqual(result, '{"ok":true}')
        command = mocked_run.call_args.args[0]
        self.assertEqual(command[:3], ["osascript", "-l", "AppleScript"])
        self.assertTrue(any("Google Chrome" in part for part in command))
        self.assertIn("JSON.stringify({ok:true})", command)

    def test_qianfan_access_focuses_window_by_url_via_osascript(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with mock.patch.object(module.subprocess, "run") as mocked_run:
            mocked_run.return_value = subprocess.CompletedProcess(
                args=["osascript"],
                returncode=0,
                stdout='https://ark.xiaohongshu.com/app-item/comment/analysis\n',
                stderr="",
            )
            result = module.focus_window_by_url("app-item/comment/analysis")

        self.assertEqual(result, "https://ark.xiaohongshu.com/app-item/comment/analysis")
        command = mocked_run.call_args.args[0]
        self.assertEqual(command[:3], ["osascript", "-l", "AppleScript"])
        self.assertTrue(any("set index of currentWindow to 1" in part for part in command))
        self.assertIn("app-item/comment/analysis", command)

    def test_qianfan_access_dismiss_script_prefers_safe_close_actions(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        script = module.build_dismiss_front_window_obstructions_script()
        self.assertIn(".d-modal-close", script)
        self.assertIn("取消", script)
        self.assertIn("关闭", script)
        self.assertIn("去参与", script)

    def test_qianfan_access_wait_for_front_window_dismisses_overlay_and_allows_store_text_pool(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        snapshot = {
            "pid": 52662,
            "window_pointer": 12345,
            "window_title": "商品-评价管理",
            "active_url": module.PAGE_URLS["comments"],
            "elements": [
                module.ChromeUiElement(1, "AXTextField", "", "地址和搜索栏", module.PAGE_URLS["comments"], None, None),
                module.ChromeUiElement(2, "AXStaticText", "", "", "抱树的koala小姐的店", None, None),
                module.ChromeUiElement(3, "AXStaticText", "", "", "评价时间", None, None),
                module.ChromeUiElement(4, "AXButton", "搜索", "", "", None, None),
                module.ChromeUiElement(5, "AXButton", "全部导出", "", "", None, None),
            ],
        }

        with (
            mock.patch.object(module, "list_window_snapshots", side_effect=lambda *_args, **_kwargs: [snapshot]),
            mock.patch.object(module, "raise_window"),
            mock.patch.object(
                module,
                "dismiss_front_window_obstructions",
                side_effect=lambda: (
                    {"ok": True, "dismissed": True, "strategy": "close_icon"}
                    if not hasattr(module, "_dismiss_called_once")
                    else {"ok": True, "dismissed": False, "checked_root_count": 0}
                ),
            ) as dismiss_mock,
            mock.patch.object(
                module,
                "dismiss_window_obstructions_via_ax",
                return_value={"ok": True, "dismissed": False, "strategy": "ax_not_overlay_like"},
            ),
            mock.patch.object(module.time, "sleep"),
        ):
            if hasattr(module, "_dismiss_called_once"):
                delattr(module, "_dismiss_called_once")
            def wrapped_dismiss():
                if not hasattr(module, "_dismiss_called_once"):
                    module._dismiss_called_once = True
                    return {"ok": True, "dismissed": True, "strategy": "close_icon"}
                return {"ok": True, "dismissed": False, "checked_root_count": 0}
            dismiss_mock.side_effect = wrapped_dismiss
            result = module.wait_for_front_window(
                title_contains="抱树的koala小姐",
                url_contains=module.PAGE_URLS["comments"],
                required_texts=("评价时间", "搜索", "全部导出"),
                timeout_seconds=5,
                poll_seconds=0.5,
            )

        self.assertEqual(result["window_title"], "商品-评价管理")
        self.assertEqual(dismiss_mock.call_count, 2)

    def test_qianfan_access_focus_window_by_url_ax_uses_matching_snapshot(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        target = {
            "pid": 52662,
            "window_pointer": 12345,
            "window_title": "商品-评价管理",
            "elements": [
                module.ChromeUiElement(1, "AXTextField", "", "地址和搜索栏", module.PAGE_URLS["comments"], None, None),
            ],
        }
        other = {
            "pid": 42491,
            "window_pointer": 67890,
            "window_title": "localhost",
            "elements": [
                module.ChromeUiElement(2, "AXTextField", "", "地址和搜索栏", "http://localhost:3000/", None, None),
            ],
        }

        with (
            mock.patch.object(module, "list_window_snapshots", return_value=[other, target]),
            mock.patch.object(module, "raise_window") as raise_mock,
        ):
            result = module.focus_window_by_url_ax(module.PAGE_URLS["comments"])

        self.assertEqual(result["pid"], 52662)
        raise_mock.assert_called_once_with(target)

    def test_qianfan_access_wait_for_front_window_falls_back_to_ax_dismiss_when_js_unavailable(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        snapshot = {
            "pid": 52662,
            "window_pointer": 12345,
            "window_title": "商品-评价管理",
            "active_url": module.PAGE_URLS["comments"],
            "elements": [
                module.ChromeUiElement(1, "AXTextField", "", "地址和搜索栏", module.PAGE_URLS["comments"], None, None),
                module.ChromeUiElement(2, "AXStaticText", "", "", "抱树的koala小姐的店", None, None),
                module.ChromeUiElement(3, "AXStaticText", "", "", "评价时间", None, None),
                module.ChromeUiElement(4, "AXButton", "搜索", "", "", None, None),
                module.ChromeUiElement(5, "AXButton", "全部导出", "", "", None, None),
            ],
        }

        with (
            mock.patch.object(module, "list_window_snapshots", return_value=[snapshot]),
            mock.patch.object(module, "raise_window"),
            mock.patch.object(
                module,
                "dismiss_front_window_obstructions",
                side_effect=module.QianfanAccessError("AppleScript JS unavailable"),
            ),
            mock.patch.object(
                module,
                "dismiss_window_obstructions_via_ax",
                return_value={"ok": True, "dismissed": False, "strategy": "ax_not_overlay_like"},
            ) as ax_dismiss_mock,
        ):
            result = module.wait_for_front_window(
                title_contains="抱树的koala小姐",
                url_contains=module.PAGE_URLS["comments"],
                required_texts=("评价时间", "搜索", "全部导出"),
                timeout_seconds=5,
                poll_seconds=0.5,
            )

        self.assertEqual(result["pid"], 52662)
        ax_dismiss_mock.assert_called_once()

    def test_qianfan_access_lists_and_closes_windows_safely(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_access", QIANFAN_ACCESS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with mock.patch.object(module.subprocess, "run") as mocked_run:
            mocked_run.side_effect = [
                subprocess.CompletedProcess(
                    args=["osascript"],
                    returncode=0,
                    stdout="101\thttps://example.com\n202\thttps://ark.xiaohongshu.com/app-item/comment/analysis\n",
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=["osascript"],
                    returncode=0,
                    stdout="202\n",
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=["osascript"],
                    returncode=0,
                    stdout="https://ark.xiaohongshu.com/app-item/comment/analysis\n",
                    stderr="",
                ),
            ]

            descriptors = module.list_window_descriptors()
            closed_id = module.close_window_by_id(202)
            closed_url = module.close_window_by_url("app-item/comment/analysis", prefer_last=True)

        self.assertEqual(
            descriptors,
            [
                {"window_id": 101, "active_url": "https://example.com"},
                {"window_id": 202, "active_url": "https://ark.xiaohongshu.com/app-item/comment/analysis"},
            ],
        )
        self.assertEqual(closed_id, 202)
        self.assertEqual(closed_url, "https://ark.xiaohongshu.com/app-item/comment/analysis")
        close_id_command = " ".join(mocked_run.call_args_list[1].args[0])
        self.assertIn("targetWindowId", close_id_command)
        self.assertIn("202", close_id_command)
        close_url_command = " ".join(mocked_run.call_args_list[2].args[0])
        self.assertIn("preferLast", close_url_command)
        self.assertIn("app-item/comment/analysis", close_url_command)

    def test_export_feishu_order_images_supports_natural_language_dates(self) -> None:
        spec = importlib.util.spec_from_file_location("export_feishu_order_images", EXPORT_IMAGES_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        today = module.date(2026, 5, 28)
        self.assertEqual(
            module.parse_date_window("帮我导出今天要上的好评", today),
            module.DateWindow(module.date(2026, 5, 28), module.date(2026, 5, 28)),
        )
        self.assertEqual(
            module.parse_date_window("帮我导出明天要上的好评", today),
            module.DateWindow(module.date(2026, 5, 29), module.date(2026, 5, 29)),
        )
        self.assertEqual(
            module.parse_date_window("帮我导出昨天的好评", today),
            module.DateWindow(module.date(2026, 5, 27), module.date(2026, 5, 27)),
        )
        self.assertEqual(
            module.parse_date_window("帮我导出近三天要上的好评", today),
            module.DateWindow(module.date(2026, 5, 28), module.date(2026, 5, 30)),
        )
        self.assertEqual(
            module.parse_date_window("帮我导出5月29号要上的好评", today),
            module.DateWindow(module.date(2026, 5, 29), module.date(2026, 5, 29)),
        )
        self.assertEqual(
            module.parse_date_window("把昨天的好评图片导出来", today),
            module.DateWindow(module.date(2026, 5, 27), module.date(2026, 5, 27)),
        )
        self.assertEqual(
            module.parse_date_window("导出最近5天的图片", today),
            module.DateWindow(module.date(2026, 5, 28), module.date(2026, 6, 1)),
        )

    def test_export_feishu_order_images_downloads_to_desktop_with_order_suffixes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="feishu-export-") as temp_dir:
            root = Path(temp_dir)
            fake_cli = root / "fake-lark-cli.py"
            fake_cli.write_text(
                """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
if args[:2] == ["base", "+record-list"]:
    offset = int(args[args.index("--offset") + 1])
    payload = {
        0: {
            "ok": True,
            "data": {
                "fields": ["订单号", "上评日期", "配图"],
                "data": [[
                    "P1001",
                    "2026-05-28 00:00:00",
                    [{"file_token": "file_a", "name": "A 1.png"}]
                ]],
                "record_id_list": ["rec1"],
                "has_more": True
            }
        },
        1: {
            "ok": True,
            "data": {
                "fields": ["订单号", "上评日期", "配图"],
                "data": [
                    [
                        "P1001",
                        "2026-05-28 00:00:00",
                        [{"file_token": "file_b", "name": "B.jpg"}]
                    ],
                    [
                        "P2001",
                        "2026-05-29 00:00:00",
                        [{"file_token": "file_c", "name": "C.png"}]
                    ]
                ],
                "record_id_list": ["rec2", "rec3"],
                "has_more": False
            }
        }
    }[offset]
    print(json.dumps(payload, ensure_ascii=False))
elif args[:2] == ["docs", "+media-download"]:
    output = args[args.index("--output") + 1]
    target = Path.cwd() / output[2:]
    target.write_bytes(b"test-image")
    print(json.dumps({"ok": True, "data": {"saved_path": str(target)}}, ensure_ascii=False))
else:
    raise SystemExit(f"unexpected args: {args}")
""",
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)
            desktop_dir = root / "desktop"

            completed = subprocess.run(
                [
                    "python3",
                    str(EXPORT_IMAGES_SCRIPT),
                    "帮我导出今天要上的好评",
                    "--lark-cli-bin",
                    str(fake_cli),
                    "--desktop-dir",
                    str(desktop_dir),
                    "--today",
                    "2026-05-28",
                    "--limit",
                    "1",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("已导出 2 张图片", completed.stdout)
            export_dir = desktop_dir / "好评图片_2026-05-28"
            self.assertTrue((export_dir / "P1001_1.png").exists())
            self.assertTrue((export_dir / "P1001_2.jpg").exists())
            self.assertFalse((export_dir / "P2001_1.png").exists())

    def test_fill_feishu_order_skus_supports_natural_language_intent(self) -> None:
        spec = importlib.util.spec_from_file_location("fill_feishu_order_skus", FILL_SKUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        module.ensure_fill_intent("帮我把好评表里的订单SKU补齐")
        module.ensure_fill_intent("把缺的规格补上")
        module.ensure_fill_intent("查一下缺的sku")
        with self.assertRaises(module.FillSkuError):
            module.ensure_fill_intent("帮我导出今天要上的好评")

    def test_fill_feishu_order_skus_plan_groups_missing_orders_by_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="feishu-sku-plan-") as temp_dir:
            root = Path(temp_dir)
            fake_cli = root / "fake-lark-cli.py"
            fake_cli.write_text(
                """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] != ["base", "+record-list"]:
    raise SystemExit(f"unexpected args: {args}")
payload = {
    "ok": True,
    "data": {
        "fields": ["店铺", "订单号", "SKU"],
        "data": [
            [["抱树的koala小姐"], "P1001", None],
            [["抱树的koala小姐"], "P1002", ""],
            [["考拉小姐慢慢来"], "P2001", "已存在规格"],
            [None, "P3001", None]
        ],
        "record_id_list": ["rec1", "rec2", "rec3", "rec4"],
        "has_more": False
    }
}
print(json.dumps(payload, ensure_ascii=False))
""",
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            local_state = root / "Local State"
            store_profile_config = root / "xhs_order_query_profiles.json"
            local_state.write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 32",
                            "info_cache": {
                                "Profile 32": {"name": "抱树的koala小姐", "user_name": ""},
                                "Profile 36": {"name": "考拉小姐慢慢来", "user_name": ""},
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store_profile_config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "order_query_page_url": "https://ark.xiaohongshu.com/app-order/order/query",
                        "primary_interaction_mode": "ax",
                        "fallback_interaction_modes": ["browser_js", "mouse"],
                        "sku_normalization": {
                            "exact_mappings": {
                                "藏青色 常规 (165cm以下) M 100-120斤": "藏青-常规;M"
                            }
                        },
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "profile_directory": "Profile 32",
                                "profile_name": "抱树的koala小姐",
                                "enabled": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(FILL_SKUS_SCRIPT),
                    "plan",
                    "帮我把好评表里的订单SKU补齐",
                    "--lark-cli-bin",
                    str(fake_cli),
                    "--local-state-path",
                    str(local_state),
                    "--store-profile-config",
                    str(store_profile_config),
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["summary"]["missing_sku_orders"], 3)
            self.assertEqual(payload["summary"]["stores_involved"], 2)
            self.assertEqual(payload["guardrails"]["max_orders_per_round"], 5)
            self.assertEqual(
                payload["order_query"]["page_url"],
                "https://ark.xiaohongshu.com/app-order/order/query",
            )
            self.assertEqual(
                payload["order_query"]["sku_normalization"]["strategy"],
                "exact_mapping_then_fallback_raw_spec",
            )
            self.assertEqual(payload["order_query"]["sku_normalization"]["exact_mapping_count"], 1)
            self.assertEqual(payload["execution_strategy"]["interaction_modes"], ["ax", "browser_js", "mouse"])
            self.assertEqual(payload["stores"][0]["store_name"], "抱树的koala小姐")
            self.assertEqual(payload["stores"][0]["profile"]["directory"], "Profile 32")
            self.assertEqual(payload["stores"][0]["profile_match_source"], "config")
            self.assertEqual(payload["stores"][0]["suggested_rounds"], [["P1001", "P1002"]])
            self.assertEqual(payload["records"][0]["order_no"], "P1001")
            self.assertEqual(payload["records"][0]["profile_match_source"], "config")
            self.assertTrue(any("P3001" in warning for warning in payload["warnings"]))

    def test_fill_feishu_order_skus_query_normalizes_spec_and_keeps_raw(self) -> None:
        fill_spec = importlib.util.spec_from_file_location("fill_feishu_order_skus", FILL_SKUS_SCRIPT)
        assert fill_spec and fill_spec.loader
        fill_module = importlib.util.module_from_spec(fill_spec)
        sys.modules[fill_spec.name] = fill_module
        fill_spec.loader.exec_module(fill_module)

        with tempfile.TemporaryDirectory(prefix="feishu-sku-query-") as temp_dir:
            root = Path(temp_dir)
            plan_file = root / "plan.json"
            local_state = root / "Local State"
            store_profile_config = root / "xhs_order_query_profiles.json"
            runtime_dir = root / "runtime"

            local_state.write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 32",
                            "info_cache": {
                                "Profile 32": {"name": "抱树的koala小姐", "user_name": ""},
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store_profile_config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "order_query_page_url": "https://ark.xiaohongshu.com/app-order/order/query",
                        "primary_interaction_mode": "ax",
                        "fallback_interaction_modes": ["browser_js", "mouse"],
                        "sku_normalization": {
                            "exact_mappings": {
                                "藏青色 常规 (165cm以下) M 100-120斤": "藏青-常规;M"
                            }
                        },
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "profile_directory": "Profile 32",
                                "profile_name": "抱树的koala小姐",
                                "enabled": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_file.write_text(
                json.dumps(
                    {
                        "order_query": {
                            "store_profile_config_path": str(store_profile_config),
                        },
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "suggested_rounds": [["P1001"]],
                            }
                        ],
                        "records": [
                            {
                                "record_id": "rec1",
                                "store_name": "抱树的koala小姐",
                                "order_no": "P1001",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            args = SimpleNamespace(
                plan_file=str(plan_file),
                store="抱树的koala小姐",
                interaction_mode="ax",
                local_state_path=str(local_state),
                runtime_dir=str(runtime_dir),
                output="",
                max_rounds=0,
                max_orders=0,
            )

            with (
                mock.patch.object(fill_module, "open_page"),
                mock.patch.object(fill_module, "irregular_pause"),
                mock.patch.object(fill_module, "focus_order_window_if_possible"),
                mock.patch.object(fill_module, "wait_for_order_page"),
                mock.patch.object(
                    fill_module,
                    "query_order_spec",
                    return_value=("藏青色 常规 (165cm以下) M 100-120斤", "ax"),
                ),
            ):
                payload = fill_module.query_store_orders(args)

            self.assertEqual(payload["profile_directory"], "Profile 32")
            self.assertEqual(payload["sku_normalization"]["exact_mapping_count"], 1)
            self.assertEqual(len(payload["updates"]), 1)
            self.assertEqual(payload["updates"][0]["sku_value"], "藏青-常规;M")
            self.assertEqual(payload["updates"][0]["raw_spec_text"], "藏青色 常规 (165cm以下) M 100-120斤")
            self.assertEqual(payload["updates"][0]["normalized_spec_key"], "藏青色 常规 (165cm以下) M 100-120斤")
            self.assertTrue(payload["updates"][0]["normalization_matched"])

    def test_fill_feishu_order_skus_apply_writes_real_values_per_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="feishu-sku-apply-") as temp_dir:
            root = Path(temp_dir)
            fake_cli = root / "fake-lark-cli.py"
            log_file = root / "upserts.jsonl"
            fake_cli.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log_path = Path(os.environ["FAKE_LARK_LOG"]).resolve()
if args[:2] != ["base", "+record-upsert"]:
    raise SystemExit(f"unexpected args: {args}")
record_id = args[args.index("--record-id") + 1]
payload = args[args.index("--json") + 1]
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"record_id": record_id, "payload": json.loads(payload)}, ensure_ascii=False) + "\\n")
print(json.dumps({"ok": True, "data": {"record_id": record_id}}, ensure_ascii=False))
""",
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            updates_file = root / "updates.json"
            updates_file.write_text(
                json.dumps(
                    {
                        "updates": [
                            {"record_id": "rec1", "sku_value": "米白【常规】 S"},
                            {"record_id": "rec2", "sku_value": "藏青色 加长 L"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(FILL_SKUS_SCRIPT),
                    "apply",
                    "--input-file",
                    str(updates_file),
                    "--lark-cli-bin",
                    str(fake_cli),
                    "--base-token",
                    "base-token",
                    "--table-id",
                    "table-id",
                ],
                cwd=REPO_ROOT,
                env={**os.environ, "PYTHONUTF8": "1", "FAKE_LARK_LOG": str(log_file)},
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("已回写 2 条 SKU 到飞书。", completed.stdout)
            log_lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                log_lines,
                [
                    {"record_id": "rec1", "payload": {"SKU": "米白【常规】 S"}},
                    {"record_id": "rec2", "payload": {"SKU": "藏青色 加长 L"}},
                ],
            )

    def test_xhs_qianfan_order_page_locates_controls_and_extracts_matches(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_order_page", ORDER_PAGE_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        snapshot = {
            "elements": [
                SimpleNamespace(index=10, role="AXStaticText", title="快捷筛选", description="", value="", position=(390, 504), size=(56, 17)),
                SimpleNamespace(index=11, role="AXTextField", title="", description="", value="", position=(426, 549), size=(796, 20)),
                SimpleNamespace(index=12, role="AXButton", title="重置", description="", value="", position=(1536, 639), size=(60, 32)),
                SimpleNamespace(index=13, role="AXButton", title="查询", description="", value="", position=(1604, 639), size=(60, 32)),
                SimpleNamespace(index=14, role="AXStaticText", title="查询到 1 项", description="", value="", position=(390, 727), size=(72, 16)),
                SimpleNamespace(index=15, role="AXStaticText", title="编号：", description="", value="", position=(442, 830), size=(36, 18)),
                SimpleNamespace(index=16, role="AXStaticText", title="P795916966135128451", description="", value="", position=(478, 830), size=(128, 18)),
                SimpleNamespace(index=17, role="AXStaticText", title="已发货未签收", description="", value="", position=(1074, 831), size=(73, 16)),
                SimpleNamespace(index=18, role="AXStaticText", title="规格：藏青色 常规 (165cm以下) M 100-120斤", description="", value="", position=(724, 871), size=(238, 36)),
            ]
        }

        controls = module.locate_order_page_controls(snapshot)
        self.assertEqual(controls.search_field_index, 11)
        self.assertEqual(controls.query_button_index, 13)
        self.assertEqual(controls.reset_button_index, 12)
        self.assertEqual(module.extract_result_count(snapshot), 1)
        self.assertEqual(module.find_order_spec(snapshot, "P795916966135128451"), "藏青色 常规 (165cm以下) M 100-120斤")
        matches = module.extract_order_page_matches(snapshot)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].status_text, "已发货未签收")

    def test_xhs_qianfan_sku_normalizer_uses_exact_mapping_then_fallback(self) -> None:
        spec = importlib.util.spec_from_file_location("xhs_qianfan_sku_normalizer", SKU_NORMALIZER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        exact_mapping = module.build_exact_mapping(
            {
                "sku_normalization": {
                    "exact_mappings": {
                        "藏青色 常规 (165cm以下) M 100-120斤": "藏青-常规;M",
                    }
                }
            }
        )
        matched = module.normalize_sku_value("藏青色  常规 (165cm以下) M 100-120斤", exact_mapping)
        fallback = module.normalize_sku_value("未知规格", exact_mapping)

        self.assertEqual(exact_mapping["藏青色 常规 (165cm以下) M 100-120斤"], "藏青-常规;M")
        self.assertEqual(matched.sku_value, "藏青-常规;M")
        self.assertTrue(matched.matched)
        self.assertEqual(fallback.sku_value, "未知规格")
        self.assertFalse(fallback.matched)

    def test_sync_review_status_plan_groups_overdue_unchecked_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="review-status-plan-") as temp_dir:
            root = Path(temp_dir)
            fake_cli = root / "fake-lark-cli.py"
            fake_cli.write_text(
                """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] != ["base", "+record-list"]:
    raise SystemExit(f"unexpected args: {args}")
payload = {
    "ok": True,
    "data": {
        "fields": ["店铺", "订单号", "上评日期", "已上评"],
        "data": [
            [["抱树的koala小姐"], "P1001", "2026-05-27 00:00:00", None],
            [["抱树的koala小姐"], "P1002", "2026-05-28 00:00:00", None],
            [["考拉小姐慢慢来"], "P2001", "2026-05-26 00:00:00", True],
            [["考拉小姐慢慢来"], "P2002", "2026-05-26 00:00:00", None],
            [["考拉小姐慢慢来"], "P2003", None, None]
        ],
        "record_id_list": ["rec1", "rec2", "rec3", "rec4", "rec5"],
        "has_more": False
    }
}
print(json.dumps(payload, ensure_ascii=False))
""",
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            local_state = root / "Local State"
            local_state.write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 36",
                            "info_cache": {
                                "Profile 32": {"name": "抱树的koala小姐", "user_name": ""},
                                "Profile 36": {"name": "考拉小姐慢慢来", "user_name": ""},
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SYNC_REVIEW_STATUS_SCRIPT),
                    "plan",
                    "--lark-cli-bin",
                    str(fake_cli),
                    "--local-state-path",
                    str(local_state),
                    "--today",
                    "2026-05-28",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["summary"]["pending_orders"], 2)
            self.assertEqual(payload["summary"]["stores_involved"], 2)
            self.assertEqual(payload["stores"][0]["store_name"], "抱树的koala小姐")
            self.assertEqual(payload["stores"][0]["orders"], ["P1001"])
            self.assertEqual(payload["stores"][1]["orders"], ["P2002"])

    def test_sync_review_status_capture_export_prefers_desktop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="review-status-export-") as temp_dir:
            root = Path(temp_dir)
            desktop_dir = root / "Desktop"
            downloads_dir = root / "Downloads"
            output_dir = root / "saved"
            desktop_dir.mkdir()
            downloads_dir.mkdir()

            desktop_file = desktop_dir / "「评价导出-wps打开文件」"
            desktop_file.write_text("desktop", encoding="utf-8")
            downloads_file = downloads_dir / "评价导出.csv"
            downloads_file.write_text("downloads", encoding="utf-8")

            after = datetime(2026, 5, 28, 14, 0, 0).timestamp()
            os.utime(desktop_file, (after + 10, after + 10))
            os.utime(downloads_file, (after + 20, after + 20))

            completed = subprocess.run(
                [
                    "python3",
                    str(SYNC_REVIEW_STATUS_SCRIPT),
                    "capture-export",
                    "--store",
                    "抱树的koala小姐",
                    "--after",
                    "2026-05-28T14:00:00",
                    "--desktop-dir",
                    str(desktop_dir),
                    "--downloads-dir",
                    str(downloads_dir),
                    "--output-dir",
                    str(output_dir),
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(Path(payload["source_file"]).resolve(), desktop_file.resolve())
            self.assertTrue(Path(payload["saved_file"]).exists())
            self.assertEqual(Path(payload["saved_file"]).read_text(encoding="utf-8"), "desktop")

    def test_sync_review_status_locates_comment_controls_and_waits_for_stable_export(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        snapshot = {
            "elements": [
                module.ChromeUiElement(10, "AXStaticText", "", "", "评价时间", (100, 200), (40, 20)),
                module.ChromeUiElement(11, "AXTextField", "", "", "", (200, 200), (80, 20)),
                module.ChromeUiElement(12, "AXTextField", "", "", "", (300, 200), (80, 20)),
                module.ChromeUiElement(13, "AXButton", "搜索", "", "", (420, 200), (60, 24)),
                module.ChromeUiElement(14, "AXButton", "全部导出", "", "", (520, 200), (80, 24)),
            ]
        }
        controls = module.locate_comment_page_controls(snapshot)
        self.assertEqual(controls["start_date_field"].index, 11)
        self.assertEqual(controls["end_date_field"].index, 12)
        self.assertEqual(controls["search_button"].title, "搜索")
        self.assertEqual(controls["export_button"].title, "全部导出")

        with tempfile.TemporaryDirectory(prefix="review-status-stable-file-") as temp_dir:
            export_file = Path(temp_dir) / "评价导出.csv"
            export_file.write_text("订单id\nP1001\n", encoding="utf-8")
            self.assertTrue(module.file_is_stable(export_file, stable_seconds=0.05))

            export_file.write_text("", encoding="utf-8")
            self.assertFalse(module.file_is_stable(export_file, stable_seconds=0.05))

    def test_sync_review_status_wait_for_export_start_distinguishes_no_download_start(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with (
            mock.patch.object(module, "find_export_file", side_effect=module.ReviewSyncError("not found")),
            mock.patch.object(module.time, "sleep"),
        ):
            with self.assertRaises(module.ExportStartTimeoutError):
                module.wait_for_export_start(
                    after_time=datetime(2026, 6, 1, 14, 0, 0),
                    desktop_dir=Path("/tmp/Desktop"),
                    downloads_dir=Path("/tmp/Downloads"),
                    timeout_seconds=1,
                )

    def test_sync_review_status_export_store_prefers_ax(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="review-status-mode-") as temp_dir:
            root = Path(temp_dir)
            plan_file = root / "plan.json"
            plan_file.write_text(
                json.dumps(
                    {
                        "today": "2026-05-31",
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "earliest_review_date": "2026-05-27",
                                "records": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = mock.Mock()
            args.plan_file = str(plan_file)
            args.store = "抱树的koala小姐"
            args.desktop_dir = str(root / "Desktop")
            args.downloads_dir = str(root / "Downloads")
            args.output_dir = str(root / "saved")
            args.local_state_path = str(root / "Local State")
            args.export_timeout_seconds = 120
            args.interaction_mode = "auto"

            profile = mock.Mock(directory="Profile 32", name="抱树的koala小姐")
            expected = {"interaction_mode": "ax", "saved_file": "/tmp/export.csv"}
            with (
                mock.patch.object(module, "load_profiles", return_value=[profile]),
                mock.patch.object(module, "resolve_profile", return_value=profile),
                mock.patch.object(module, "export_store_via_ax", return_value=expected) as ax_mock,
                mock.patch.object(module, "export_store_via_mouse") as mouse_mock,
            ):
                payload = module.export_store(args)

        self.assertEqual(payload["interaction_mode"], "ax")
        ax_mock.assert_called_once()
        mouse_mock.assert_not_called()

    def test_sync_review_status_export_store_retries_ax_before_mouse_after_no_download_start(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="review-status-retry-ax-") as temp_dir:
            root = Path(temp_dir)
            plan_file = root / "plan.json"
            plan_file.write_text(
                json.dumps(
                    {
                        "today": "2026-05-31",
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "earliest_review_date": "2026-05-27",
                                "records": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = mock.Mock()
            args.plan_file = str(plan_file)
            args.store = "抱树的koala小姐"
            args.desktop_dir = str(root / "Desktop")
            args.downloads_dir = str(root / "Downloads")
            args.output_dir = str(root / "saved")
            args.local_state_path = str(root / "Local State")
            args.export_start_timeout_seconds = 60
            args.export_timeout_seconds = 120
            args.interaction_mode = "auto"

            profile = mock.Mock(directory="Profile 32", name="抱树的koala小姐")
            expected = {"interaction_mode": "ax", "saved_file": "/tmp/export.csv"}
            with (
                mock.patch.object(module, "load_profiles", return_value=[profile]),
                mock.patch.object(module, "resolve_profile", return_value=profile),
                mock.patch.object(
                    module,
                    "export_store_via_ax",
                    side_effect=[module.ExportStartTimeoutError("start timeout"), expected],
                ) as ax_mock,
                mock.patch.object(module, "export_store_via_mouse") as mouse_mock,
            ):
                payload = module.export_store(args)

        self.assertEqual(payload["interaction_mode"], "ax")
        self.assertEqual(ax_mock.call_count, 2)
        mouse_mock.assert_not_called()

    def test_sync_review_status_export_store_falls_back_to_mouse(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="review-status-fallback-") as temp_dir:
            root = Path(temp_dir)
            plan_file = root / "plan.json"
            plan_file.write_text(
                json.dumps(
                    {
                        "today": "2026-05-31",
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "earliest_review_date": "2026-05-27",
                                "records": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = mock.Mock()
            args.plan_file = str(plan_file)
            args.store = "抱树的koala小姐"
            args.desktop_dir = str(root / "Desktop")
            args.downloads_dir = str(root / "Downloads")
            args.output_dir = str(root / "saved")
            args.local_state_path = str(root / "Local State")
            args.export_timeout_seconds = 120
            args.interaction_mode = "auto"

            profile = mock.Mock(directory="Profile 32", name="抱树的koala小姐")
            expected = {"interaction_mode": "mouse", "saved_file": "/tmp/export.csv"}
            with (
                mock.patch.object(module, "load_profiles", return_value=[profile]),
                mock.patch.object(module, "resolve_profile", return_value=profile),
                mock.patch.object(
                    module,
                    "export_store_via_ax",
                    side_effect=module.ReviewSyncError("ax failed"),
                ) as ax_mock,
                mock.patch.object(module, "export_store_via_mouse", return_value=expected) as mouse_mock,
            ):
                payload = module.export_store(args)

        self.assertEqual(payload["interaction_mode"], "mouse")
        ax_mock.assert_called_once()
        mouse_mock.assert_called_once()

    def test_sync_review_status_export_store_supports_explicit_browser_js(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="review-status-browser-js-") as temp_dir:
            root = Path(temp_dir)
            plan_file = root / "plan.json"
            plan_file.write_text(
                json.dumps(
                    {
                        "today": "2026-05-31",
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "earliest_review_date": "2026-05-27",
                                "records": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = mock.Mock()
            args.plan_file = str(plan_file)
            args.store = "抱树的koala小姐"
            args.desktop_dir = str(root / "Desktop")
            args.downloads_dir = str(root / "Downloads")
            args.output_dir = str(root / "saved")
            args.local_state_path = str(root / "Local State")
            args.export_timeout_seconds = 120
            args.interaction_mode = "browser_js"

            profile = mock.Mock(directory="Profile 32", name="抱树的koala小姐")
            expected = {"interaction_mode": "browser_js", "saved_file": "/tmp/export.csv"}
            with (
                mock.patch.object(module, "load_profiles", return_value=[profile]),
                mock.patch.object(module, "resolve_profile", return_value=profile),
                mock.patch.object(module, "export_store_via_browser_js", return_value=expected) as browser_mock,
                mock.patch.object(module, "export_store_via_ax") as ax_mock,
                mock.patch.object(module, "export_store_via_mouse") as mouse_mock,
            ):
                payload = module.export_store(args)

        self.assertEqual(payload["interaction_mode"], "browser_js")
        browser_mock.assert_called_once()
        ax_mock.assert_not_called()
        mouse_mock.assert_not_called()

    def test_sync_review_status_ax_flow_attempts_safe_window_close(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        controls = {
            "start_date_field": module.ChromeUiElement(11, "AXTextField", "", "", "", (0, 0), (10, 10)),
            "end_date_field": module.ChromeUiElement(12, "AXTextField", "", "", "", (0, 0), (10, 10)),
            "search_button": module.ChromeUiElement(13, "AXButton", "搜索", "", "", (0, 0), (10, 10)),
            "export_button": module.ChromeUiElement(14, "AXButton", "全部导出", "", "", (0, 0), (10, 10)),
        }
        capture = {
            "source_file": "/tmp/source.csv",
            "saved_file": "/tmp/export.csv",
            "saved_at": "20260531-170000",
        }
        profile = mock.Mock(directory="Profile 32", name="抱树的koala小姐")
        with (
            mock.patch.object(module, "snapshot_window_ids_optional", return_value={1, 2}),
            mock.patch.object(module, "open_page"),
            mock.patch.object(module, "irregular_pause"),
            mock.patch.object(module, "focus_comment_window_if_possible"),
            mock.patch.object(module, "wait_for_front_window", side_effect=[{"elements": []}, {"elements": []}]),
            mock.patch.object(module, "locate_comment_page_controls", return_value=controls),
            mock.patch.object(module, "set_front_window_element_value"),
            mock.patch.object(module, "press_front_window_element"),
            mock.patch.object(module, "wait_for_export_capture", return_value=capture),
            mock.patch.object(module, "close_opened_comment_window") as close_mock,
        ):
            payload = module.export_store_via_ax(
                store_name="抱树的koala小姐",
                profile=profile,
                start_date="2026-05-27",
                end_date="2026-05-31",
                desktop_dir=Path("/tmp/Desktop"),
                downloads_dir=Path("/tmp/Downloads"),
                output_dir=Path("/tmp/saved"),
                export_start_timeout_seconds=60,
                export_timeout_seconds=120,
            )

        self.assertEqual(payload["interaction_mode"], "ax")
        self.assertEqual(payload["saved_file"], "/tmp/export.csv")
        close_mock.assert_called_once_with({1, 2})

    def test_sync_review_status_safe_window_close_never_breaks_main_flow(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with (
            mock.patch.object(module, "snapshot_window_ids_optional", return_value={88}),
            mock.patch.object(module, "close_window_by_id", side_effect=module.ReviewSyncError("close failed")),
            mock.patch.object(module, "log_step") as log_mock,
        ):
            module.close_opened_comment_window(set())

        log_mock.assert_called()
        self.assertIn("收尾关闭失败", log_mock.call_args.args[0])
        self.assertIn("仍残留窗口", log_mock.call_args.args[0])

    def test_sync_review_status_safe_window_close_skips_blind_close_without_snapshot(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with (
            mock.patch.object(module, "close_window_by_id") as close_id_mock,
            mock.patch.object(module, "log_step") as log_mock,
        ):
            module.close_opened_comment_window(None)

        close_id_mock.assert_not_called()
        self.assertTrue(any("不做盲关" in call.args[0] for call in log_mock.call_args_list))

    def test_sync_review_status_safe_window_close_closes_only_new_comment_windows(self) -> None:
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", SYNC_REVIEW_STATUS_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with (
            mock.patch.object(module, "snapshot_window_ids_optional", side_effect=[{1, 2, 9}, {1, 2}]),
            mock.patch.object(module, "close_window_by_id") as close_id_mock,
            mock.patch.object(module, "log_step") as log_mock,
        ):
            module.close_opened_comment_window({1, 2})

        close_id_mock.assert_called_once_with(9)
        self.assertTrue(any("已关闭本轮任务窗口：9" in call.args[0] for call in log_mock.call_args_list))

    def test_review_status_launch_scripts_pin_python_path(self) -> None:
        main_script = (REPO_ROOT / "scripts" / "review_status_sync_auto.sh").read_text(encoding="utf-8")
        check_script = (REPO_ROOT / "scripts" / "check_review_status_sync.sh").read_text(encoding="utf-8")
        install_script = (REPO_ROOT / "scripts" / "install_review_status_launchagent.sh").read_text(encoding="utf-8")
        for content in (main_script, check_script):
            self.assertIn("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3", content)
            self.assertIn("REVIEW_STATUS_PYTHON_BIN", content)
            self.assertIn('exec "$PYTHON_BIN"', content)
        self.assertIn("REVIEW_STATUS_SCHEDULED_RETRY=1", check_script)

        run_script = (REPO_ROOT / "scripts" / "run_review_status_sync.py").read_text(encoding="utf-8")
        self.assertIn('PYTHON_BIN = os.environ.get("REVIEW_STATUS_PYTHON_BIN") or sys.executable or "python3"', run_script)
        self.assertNotIn('[\n                "python3",', run_script)
        self.assertIn("<key>EnvironmentVariables</key>", install_script)
        self.assertIn("<key>REVIEW_STATUS_PYTHON_BIN</key>", install_script)
        self.assertIn("<key>PATH</key>", install_script)
        self.assertIn("<integer>20</integer>", install_script)
        self.assertIn('launchctl bootout "$LAUNCH_DOMAIN" "$CHECK_PLIST"', install_script)
        self.assertIn('launchctl bootstrap "$LAUNCH_DOMAIN" "$CHECK_PLIST"', install_script)

    def test_run_review_status_notification_messages_and_retry_gate(self) -> None:
        script = REPO_ROOT / "scripts" / "run_review_status_sync.py"
        spec = importlib.util.spec_from_file_location("run_review_status_sync", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        self.assertEqual(
            module.build_notification_message(
                "main",
                [{"type": "missing_orders", "store_name": "抱树的koala小姐", "missing_count": 2}],
            ),
            "漏上评2条。抱树的koala小姐2条。",
        )
        self.assertEqual(
            module.build_notification_message(
                "main",
                [{"type": "store_failed", "store_name": "抱树的koala小姐", "message": "error"}],
            ),
            "检查失败。抱树的koala小姐失败。",
        )
        self.assertEqual(
            module.build_notification_message(
                "retry",
                [{"type": "store_failed", "store_name": "抱树的koala小姐", "message": "error"}],
            ),
            "补查失败。抱树的koala小姐失败。",
        )

        with tempfile.TemporaryDirectory(prefix="review-status-gate-") as temp_dir:
            status_file = Path(temp_dir) / "status_latest.json"
            original = module.LATEST_STATUS_FILE
            module.LATEST_STATUS_FILE = status_file
            try:
                status_file.write_text(
                    json.dumps(
                        {
                            "today": "2026-05-30",
                            "mode": "main",
                            "issues": [{"type": "missing_orders", "store_name": "抱树的koala小姐", "missing_count": 1}],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                self.assertFalse(module.should_run_scheduled_retry("2026-05-30"))

                status_file.write_text(
                    json.dumps(
                        {
                            "today": "2026-05-30",
                            "mode": "main",
                            "issues": [{"type": "store_failed", "store_name": "抱树的koala小姐", "message": "error"}],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                self.assertTrue(module.should_run_scheduled_retry("2026-05-30"))
            finally:
                module.LATEST_STATUS_FILE = original

    def test_run_review_status_save_status_separates_main_and_retry_files(self) -> None:
        script = REPO_ROOT / "scripts" / "run_review_status_sync.py"
        spec = importlib.util.spec_from_file_location("run_review_status_sync", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="review-status-save-") as temp_dir:
            runtime_dir = Path(temp_dir)
            original_runtime_dir = module.RUNTIME_DIR
            original_latest_status = module.LATEST_STATUS_FILE
            original_latest_main_status = module.LATEST_MAIN_STATUS_FILE
            original_latest_retry_status = module.LATEST_RETRY_STATUS_FILE
            module.RUNTIME_DIR = runtime_dir
            module.LATEST_STATUS_FILE = runtime_dir / "status_latest.json"
            module.LATEST_MAIN_STATUS_FILE = runtime_dir / "status_latest_main.json"
            module.LATEST_RETRY_STATUS_FILE = runtime_dir / "status_latest_retry.json"
            try:
                main_status = {
                    "today": "2026-05-31",
                    "mode": "main",
                    "issues": [{"type": "store_failed", "store_name": "抱树的koala小姐", "message": "error"}],
                }
                retry_status = {
                    "today": "2026-05-31",
                    "mode": "retry",
                    "issues": [{"type": "store_failed", "store_name": "抱树的koala小姐", "message": "retry error"}],
                }

                module.save_status(main_status)
                module.save_status(retry_status)

                self.assertTrue((runtime_dir / "status_2026-05-31_main.json").exists())
                self.assertTrue((runtime_dir / "status_2026-05-31_retry.json").exists())
                self.assertEqual(
                    json.loads((runtime_dir / "status_latest_main.json").read_text(encoding="utf-8"))["mode"],
                    "main",
                )
                self.assertEqual(
                    json.loads((runtime_dir / "status_latest_retry.json").read_text(encoding="utf-8"))["mode"],
                    "retry",
                )
                self.assertEqual(
                    json.loads((runtime_dir / "status_latest.json").read_text(encoding="utf-8"))["mode"],
                    "retry",
                )
            finally:
                module.RUNTIME_DIR = original_runtime_dir
                module.LATEST_STATUS_FILE = original_latest_status
                module.LATEST_MAIN_STATUS_FILE = original_latest_main_status
                module.LATEST_RETRY_STATUS_FILE = original_latest_retry_status

    def test_run_review_status_resolves_workspace_root_from_release_copy(self) -> None:
        script = REPO_ROOT / "scripts" / "run_review_status_sync.py"
        spec = importlib.util.spec_from_file_location("run_review_status_sync", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        workspace_root = Path("/tmp/ops-workspace")
        release_code_root = workspace_root / "releases" / "20260531-170153-cb714d1"
        self.assertEqual(module.resolve_workspace_root(release_code_root), workspace_root)
        self.assertEqual(module.resolve_workspace_root(workspace_root), workspace_root)

    def test_sync_review_status_resolves_workspace_root_from_release_copy(self) -> None:
        script = REPO_ROOT / "scripts" / "sync_feishu_review_status.py"
        spec = importlib.util.spec_from_file_location("sync_feishu_review_status", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        workspace_root = Path("/tmp/ops-workspace")
        release_code_root = workspace_root / "releases" / "20260531-170153-cb714d1"
        self.assertEqual(module.resolve_workspace_root(release_code_root), workspace_root)
        self.assertEqual(module.resolve_workspace_root(workspace_root), workspace_root)

    def test_sync_review_status_reconcile_updates_checkbox(self) -> None:
        with tempfile.TemporaryDirectory(prefix="review-status-reconcile-") as temp_dir:
            root = Path(temp_dir)
            fake_cli = root / "fake-lark-cli.py"
            log_file = root / "upserts.jsonl"
            fake_cli.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log_path = Path(os.environ["FAKE_LARK_LOG"]).resolve()
if args[:2] != ["base", "+record-upsert"]:
    raise SystemExit(f"unexpected args: {args}")
record_id = args[args.index("--record-id") + 1]
payload = args[args.index("--json") + 1]
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"record_id": record_id, "payload": json.loads(payload)}, ensure_ascii=False) + "\\n")
print(json.dumps({"ok": True, "data": {"record_id": record_id}}, ensure_ascii=False))
""",
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            plan_file = root / "plan.json"
            plan_file.write_text(
                json.dumps(
                    {
                        "stores": [
                            {
                                "store_name": "抱树的koala小姐",
                                "records": [
                                    {"record_id": "rec1", "order_no": "P1001"},
                                    {"record_id": "rec2", "order_no": "P1002"},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            export_file = root / "评价导出.csv"
            export_file.write_text(
                "订单id,商品名称\nP1002,测试商品\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SYNC_REVIEW_STATUS_SCRIPT),
                    "reconcile",
                    "--plan-file",
                    str(plan_file),
                    "--export-file",
                    str(export_file),
                    "--apply",
                    "--lark-cli-bin",
                    str(fake_cli),
                    "--base-token",
                    "base-token",
                    "--table-id",
                    "table-id",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                env={**os.environ, "PYTHONUTF8": "1", "FAKE_LARK_LOG": str(log_file)},
                capture_output=True,
                text=True,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["matched_orders"], ["P1002"])
            self.assertEqual(payload["missing_orders"], ["P1001"])
            log_lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(log_lines, [{"record_id": "rec2", "payload": {"已上评": True}}])

    def test_validate_script_passes_for_current_repo(self) -> None:
        completed = subprocess.run(
            ["python3", str(VALIDATE_SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("工作区治理校验通过", completed.stdout)

    def test_release_script_wires_governance_validation(self) -> None:
        content = RELEASE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('python3 "$REPO_ROOT/scripts/validate_workspace_governance.py"', content)

    def test_governance_config_and_docs_record_required_policies(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["workspace"]["name"], "运营自动化")
        self.assertEqual(config["workspace"]["absolute_path"], str(REPO_ROOT))
        self.assertEqual(
            config["workspace"]["github_repository_ssh"],
            "git@github.com:PM-Bot-Kevin/operations-automation.git",
        )
        self.assertEqual(config["workspace"]["long_lived_branch"], "main")
        self.assertEqual(
            config["release_layout"]["required_entries"],
            ["releases", "current", "runtime", "release-log"],
        )
        self.assertEqual(config["cross_workspace"]["dependencies"], [])
        guardrails = json.loads(QIANFAN_GUARDRAILS_PATH.read_text(encoding="utf-8"))
        store_profile_config = json.loads((REPO_ROOT / "config" / "xhs_order_query_profiles.json").read_text(encoding="utf-8"))
        self.assertEqual(guardrails["execution_defaults"]["max_orders_per_round"], 5)
        self.assertTrue(guardrails["execution_defaults"]["single_store_only"])
        self.assertTrue(guardrails["execution_defaults"]["fixed_interval_forbidden"])
        self.assertEqual(store_profile_config["primary_interaction_mode"], "ax")
        self.assertEqual(store_profile_config["fallback_interaction_modes"], ["browser_js", "mouse"])
        self.assertEqual(
            store_profile_config["order_query_page_url"],
            "https://ark.xiaohongshu.com/app-order/order/query",
        )

        for path, fragment in [
            (REPO_ROOT / "README.md", "GitHub 是代码备份，不是真实业务数据备份"),
            (REPO_ROOT / "README.md", "不允许默认连接仓库镜像、临时副本、worktree、历史目录、手工复制目录"),
            (REPO_ROOT / "README.md", "直接对助手说你的自然语言需求即可"),
            (REPO_ROOT / "README.md", "涉及店铺后台时默认只读"),
            (REPO_ROOT / "README.md", "按最小操作原则执行"),
            (REPO_ROOT / "README.md", "搜索之间不能使用固定时间间隔"),
            (REPO_ROOT / "README.md", "真实完整规格"),
            (REPO_ROOT / "README.md", "默认一轮不超过 5 单"),
            (REPO_ROOT / "README.md", "xhs_order_query_profiles.json"),
            (REPO_ROOT / "README.md", "AX -> browser_js -> mouse"),
            (REPO_ROOT / "README.md", "app-order/order/query"),
            (REPO_ROOT / "README.md", "已上评"),
            (REPO_ROOT / "README.md", "14:00"),
            (REPO_ROOT / "README.md", "14:20"),
            (REPO_ROOT / "README.md", "install_review_status_launchagent.sh"),
            (REPO_ROOT / "README.md", "自动删除"),
            (REPO_ROOT / "README.md", "xhs_qianfan_guardrails.json"),
            (REPO_ROOT / "AGENTS.md", "只允许连接对方正式入口"),
            (REPO_ROOT / "AGENTS.md", "飞书好评图片导出"),
            (REPO_ROOT / "AGENTS.md", "不要要求用户提供命令行"),
            (REPO_ROOT / "AGENTS.md", "优先复用用户现有的 Chrome 个人资料"),
            (REPO_ROOT / "AGENTS.md", "默认行为必须是只读"),
            (REPO_ROOT / "AGENTS.md", "最小操作"),
            (REPO_ROOT / "AGENTS.md", "fill_feishu_order_skus.py"),
            (REPO_ROOT / "AGENTS.md", "不能使用固定时间间隔"),
            (REPO_ROOT / "AGENTS.md", "默认一轮不超过 5 单"),
            (REPO_ROOT / "AGENTS.md", "xhs_order_query_profiles.json"),
            (REPO_ROOT / "AGENTS.md", "AX -> browser_js -> mouse"),
            (REPO_ROOT / "AGENTS.md", "app-order/order/query"),
            (REPO_ROOT / "AGENTS.md", "sync_feishu_review_status.py"),
            (REPO_ROOT / "AGENTS.md", "14:00 主跑"),
            (REPO_ROOT / "AGENTS.md", "14:20"),
            (REPO_ROOT / "AGENTS.md", "install_review_status_launchagent.sh"),
            (REPO_ROOT / "AGENTS.md", "删掉本轮评价导出临时文件"),
            (REPO_ROOT / "AGENTS.md", "xhs_qianfan_guardrails.json"),
            (REPO_ROOT / "HANDOVER.md", "回滚只切代码版本，不碰 `runtime/`"),
            (REPO_ROOT / "HANDOVER.md", "触发口径是自然语言"),
            (REPO_ROOT / "HANDOVER.md", "默认优先复用用户现有的 Chrome 店铺资料"),
            (REPO_ROOT / "HANDOVER.md", "只做最小操作"),
            (REPO_ROOT / "HANDOVER.md", "真实完整规格"),
            (REPO_ROOT / "HANDOVER.md", "不能用固定时间间隔"),
            (REPO_ROOT / "HANDOVER.md", "默认一轮不超过 5 单"),
            (REPO_ROOT / "HANDOVER.md", "xhs_order_query_profiles.json"),
            (REPO_ROOT / "HANDOVER.md", "AX -> browser_js -> mouse"),
            (REPO_ROOT / "HANDOVER.md", "app-order/order/query"),
            (REPO_ROOT / "HANDOVER.md", "14:00 主跑"),
            (REPO_ROOT / "HANDOVER.md", "14:20"),
            (REPO_ROOT / "HANDOVER.md", "补跑"),
            (REPO_ROOT / "HANDOVER.md", "run_review_status_sync.py"),
            (REPO_ROOT / "HANDOVER.md", "自动删除本轮评价导出临时文件"),
            (REPO_ROOT / "HANDOVER.md", "docs/xhs_qianfan_safety.md"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "xhs_qianfan_guardrails.json"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "xhs_order_query_profiles.json"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "AX -> browser_js -> mouse"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "app-order/order/query"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "install_review_status_launchagent.sh"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "14:20"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "自动删除本轮评价导出临时文件"),
            (REPO_ROOT / "docs/xhs_qianfan_safety.md", "默认每轮不超过 5 单"),
            (REPO_ROOT / "docs/xhs_qianfan_safety.md", "固定节奏连续查询"),
            (REPO_ROOT / "docs/xhs_qianfan_safety.md", "先在飞书或别的外部表里把目标订单缩小到最少"),
            (REPO_ROOT / "BACKUP.md", "只负责代码、文档、脚本、测试和配置模板"),
            (REPO_ROOT / "HANDOVER.md", "operations-automation"),
            (BACKUP_SCRIPT, 'EXPECTED_BRANCH="${BACKUP_EXPECTED_BRANCH:-main}"'),
            (BACKUP_SCRIPT, 'com.luogic.operations-automation.github-backup'),
        ]:
            self.assertIn(fragment, path.read_text(encoding="utf-8"))

    def test_release_and_rollback_manage_current_without_touching_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workspace-governance-") as temp_dir:
            root = Path(temp_dir)
            repo_dir = root / "repo"
            shutil.copytree(
                REPO_ROOT,
                repo_dir,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "releases", "current", "runtime", "release-log", ".github_backup_logs"),
            )

            subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Governance Test"], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "governance-test@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)
            config = json.loads((repo_dir / "config" / "workspace_governance.json").read_text(encoding="utf-8"))
            config["workspace"]["absolute_path"] = str(repo_dir)
            (repo_dir / "config" / "workspace_governance.json").write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "remote", "add", "origin", config["workspace"]["github_repository_ssh"]],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "bootstrap"], cwd=repo_dir, check=True, capture_output=True, text=True)

            runtime_file = repo_dir / "runtime" / "state.json"
            runtime_file.parent.mkdir(parents=True, exist_ok=True)
            runtime_file.write_text('{"version": 1}\n', encoding="utf-8")

            first_release = subprocess.run(
                ["/bin/bash", str(repo_dir / "scripts" / "release_workspace.sh"), "--summary", "测试发布一"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("正式发布完成", first_release.stdout)

            second_release = subprocess.run(
                ["/bin/bash", str(repo_dir / "scripts" / "release_workspace.sh"), "--summary", "测试发布二", "--release-id", "20990101-000001-test"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("20990101-000001-test", second_release.stdout)

            subprocess.run(
                ["/bin/bash", str(repo_dir / "scripts" / "rollback_workspace.sh")],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )

            current_target = os.path.realpath(repo_dir / "current")
            self.assertNotEqual(Path(current_target).name, "20990101-000001-test")
            self.assertEqual(runtime_file.read_text(encoding="utf-8"), '{"version": 1}\n')
            log_rows = [
                json.loads(line)
                for line in (repo_dir / "release-log" / "releases.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(log_rows[-1]["action"], "rollback")


if __name__ == "__main__":
    unittest.main()
