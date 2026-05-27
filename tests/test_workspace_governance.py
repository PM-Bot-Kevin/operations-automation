from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_SCRIPT = REPO_ROOT / "scripts" / "validate_workspace_governance.py"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release_workspace.sh"
ROLLBACK_SCRIPT = REPO_ROOT / "scripts" / "rollback_workspace.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "github_backup.sh"
CONFIG_PATH = REPO_ROOT / "config" / "workspace_governance.json"


class WorkspaceGovernanceTests(unittest.TestCase):
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

        for path, fragment in [
            (REPO_ROOT / "README.md", "GitHub 是代码备份，不是真实业务数据备份"),
            (REPO_ROOT / "README.md", "不允许默认连接仓库镜像、临时副本、worktree、历史目录、手工复制目录"),
            (REPO_ROOT / "AGENTS.md", "只允许连接对方正式入口"),
            (REPO_ROOT / "HANDOVER.md", "回滚只切代码版本，不碰 `runtime/`"),
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
