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
            self.assertIn("--profile-directory=Profile 36", module.open_page(resolved, "orders", dry_run=True))
            self.assertIn("app-item/comment/analysis", module.open_page(resolved, "comments", dry_run=True))

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
            self.assertEqual(payload["stores"][0]["store_name"], "抱树的koala小姐")
            self.assertEqual(payload["stores"][0]["profile"]["directory"], "Profile 32")
            self.assertEqual(payload["stores"][0]["suggested_rounds"], [["P1001", "P1002"]])
            self.assertEqual(payload["records"][0]["order_no"], "P1001")
            self.assertTrue(any("P3001" in warning for warning in payload["warnings"]))

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
        self.assertEqual(guardrails["execution_defaults"]["max_orders_per_round"], 5)
        self.assertTrue(guardrails["execution_defaults"]["single_store_only"])
        self.assertTrue(guardrails["execution_defaults"]["fixed_interval_forbidden"])

        for path, fragment in [
            (REPO_ROOT / "README.md", "GitHub 是代码备份，不是真实业务数据备份"),
            (REPO_ROOT / "README.md", "不允许默认连接仓库镜像、临时副本、worktree、历史目录、手工复制目录"),
            (REPO_ROOT / "README.md", "直接对助手说你的自然语言需求即可"),
            (REPO_ROOT / "README.md", "涉及店铺后台时默认只读"),
            (REPO_ROOT / "README.md", "按最小操作原则执行"),
            (REPO_ROOT / "README.md", "搜索之间不能使用固定时间间隔"),
            (REPO_ROOT / "README.md", "真实完整规格"),
            (REPO_ROOT / "README.md", "默认一轮不超过 5 单"),
            (REPO_ROOT / "README.md", "已上评"),
            (REPO_ROOT / "README.md", "14:00"),
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
            (REPO_ROOT / "AGENTS.md", "sync_feishu_review_status.py"),
            (REPO_ROOT / "AGENTS.md", "14:00 主跑"),
            (REPO_ROOT / "AGENTS.md", "xhs_qianfan_guardrails.json"),
            (REPO_ROOT / "HANDOVER.md", "回滚只切代码版本，不碰 `runtime/`"),
            (REPO_ROOT / "HANDOVER.md", "触发口径是自然语言"),
            (REPO_ROOT / "HANDOVER.md", "默认优先复用用户现有的 Chrome 店铺资料"),
            (REPO_ROOT / "HANDOVER.md", "只做最小操作"),
            (REPO_ROOT / "HANDOVER.md", "真实完整规格"),
            (REPO_ROOT / "HANDOVER.md", "不能用固定时间间隔"),
            (REPO_ROOT / "HANDOVER.md", "默认一轮不超过 5 单"),
            (REPO_ROOT / "HANDOVER.md", "14:00 主跑"),
            (REPO_ROOT / "HANDOVER.md", "补跑"),
            (REPO_ROOT / "HANDOVER.md", "docs/xhs_qianfan_safety.md"),
            (REPO_ROOT / "docs/workspace_maintenance.md", "xhs_qianfan_guardrails.json"),
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
