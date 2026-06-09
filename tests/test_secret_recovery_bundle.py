from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "build_secret_recovery_bundle.sh"
REFRESH_SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "refresh_secret_recovery_bundle.sh"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "install_secret_recovery_passphrase.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "github_backup.sh"
HELPER_SCRIPT = REPO_ROOT / "scripts" / "feishu_secret_config.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FeishuSecretConfigTests(unittest.TestCase):
    def test_resolve_base_token_prefers_explicit_then_env_then_file(self) -> None:
        module = load_module("feishu_secret_config", HELPER_SCRIPT)

        with tempfile.TemporaryDirectory(prefix="feishu-secret-config-") as temp_dir:
            env_file = Path(temp_dir) / ".ai-copy.env"
            env_file.write_text(
                "export OPERATIONS_AUTOMATION_FEISHU_BASE_TOKEN='file-token'\n",
                encoding="utf-8",
            )

            self.assertEqual(
                module.resolve_feishu_base_token(
                    "explicit-token",
                    env={"OPERATIONS_AUTOMATION_FEISHU_BASE_TOKEN": "env-token"},
                    env_file=env_file,
                ),
                "explicit-token",
            )
            self.assertEqual(
                module.resolve_feishu_base_token(
                    "",
                    env={"OPERATIONS_AUTOMATION_FEISHU_BASE_TOKEN": "env-token"},
                    env_file=env_file,
                ),
                "env-token",
            )
            self.assertEqual(
                module.resolve_feishu_base_token(
                    "",
                    env={},
                    env_file=env_file,
                ),
                "file-token",
            )

    def test_resolve_base_token_raises_when_missing(self) -> None:
        module = load_module("feishu_secret_config_missing", HELPER_SCRIPT)
        with self.assertRaises(RuntimeError):
            module.resolve_feishu_base_token(
                "",
                env={},
                env_file=Path("/tmp/does-not-exist-ai-copy.env"),
            )


class SecretRecoveryBundleTests(unittest.TestCase):
    def test_build_script_creates_encrypted_bundle_and_restore_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="secret-recovery-build-") as temp_dir:
            root = Path(temp_dir)
            required_file = root / "shared.env"
            required_file.write_text("TOKEN=test\n", encoding="utf-8")
            required_dir = root / "lark-cli"
            required_dir.mkdir()
            (required_dir / "auth.enc").write_text("ciphertext\n", encoding="utf-8")

            manifest = root / "manifest.txt"
            manifest.write_text(
                "\n".join(
                    [
                        f"required|shared_env|{required_file}",
                        f"required|lark_cli_auth|{required_dir}",
                        f"optional|missing_item|{root / 'missing.txt'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            passphrase_file = root / "passphrase.txt"
            passphrase_file.write_text("TEST-PASSPHRASE-12345\n", encoding="utf-8")
            output_dir = root / "output"

            subprocess.run(
                [
                    "zsh",
                    str(BUILD_SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--output-dir",
                    str(output_dir),
                    "--bundle-name",
                    "secret-recovery-bundle-test",
                    "--passphrase-file",
                    str(passphrase_file),
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            encrypted_archive = output_dir / "secret-recovery-bundle-test.tar.gz.enc"
            checksum_file = output_dir / "secret-recovery-bundle-test.tar.gz.enc.sha256"
            self.assertTrue(encrypted_archive.exists())
            self.assertTrue(checksum_file.exists())

            plaintext_archive = root / "bundle.tar.gz"
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-pbkdf2",
                    "-iter",
                    "600000",
                    "-in",
                    str(encrypted_archive),
                    "-out",
                    str(plaintext_archive),
                    "-pass",
                    f"file:{passphrase_file}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            extract_root = root / "extract"
            extract_root.mkdir()
            with tarfile.open(plaintext_archive) as handle:
                handle.extractall(extract_root)

            restore_manifest = (extract_root / "restore_manifest.tsv").read_text(encoding="utf-8")
            self.assertIn("shared_env", restore_manifest)
            self.assertIn("lark_cli_auth", restore_manifest)
            self.assertIn("missing_item", restore_manifest)
            self.assertIn("missing", restore_manifest)

    def test_refresh_script_skips_when_inputs_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="secret-recovery-refresh-") as temp_dir:
            root = Path(temp_dir)
            required_file = root / "shared.env"
            required_file.write_text("TOKEN=test\n", encoding="utf-8")
            manifest = root / "manifest.txt"
            manifest.write_text(f"required|shared_env|{required_file}\n", encoding="utf-8")
            passphrase_file = root / "passphrase.txt"
            passphrase_file.write_text("TEST-PASSPHRASE-12345\n", encoding="utf-8")
            output_dir = root / "output"
            state_root = root / "state"

            env = {
                **os.environ,
                "SECRET_RECOVERY_MANIFEST_PATH": str(manifest),
                "SECRET_RECOVERY_OUTPUT_DIR": str(output_dir),
                "SECRET_RECOVERY_STATE_ROOT": str(state_root),
                "SECRET_RECOVERY_PASSPHRASE_FILE": str(passphrase_file),
                "SECRET_RECOVERY_BUNDLE_NAME": "secret-recovery-bundle-latest",
            }

            subprocess.run(
                ["zsh", str(REFRESH_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run(
                ["zsh", str(REFRESH_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Secret bundle inputs unchanged.", completed.stdout)

    def test_install_passphrase_script_copies_with_600_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="secret-recovery-passphrase-") as temp_dir:
            root = Path(temp_dir)
            source_file = root / "source-passphrase.txt"
            source_file.write_text("shared-passphrase\n", encoding="utf-8")
            target_file = root / "installed" / "secret-recovery-passphrase.txt"

            subprocess.run(
                [
                    "zsh",
                    str(INSTALL_SCRIPT),
                    "--passphrase-file",
                    str(source_file),
                ],
                cwd=REPO_ROOT,
                env={**os.environ, "SECRET_RECOVERY_PASSPHRASE_FILE": str(target_file)},
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(target_file.read_text(encoding="utf-8"), "shared-passphrase\n")
            self.assertEqual(stat.S_IMODE(target_file.stat().st_mode), 0o600)

    def test_backup_script_refreshes_secret_bundle_before_no_change_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="secret-recovery-backup-") as temp_dir:
            root = Path(temp_dir)
            repo_dir = root / "repo"
            shutil.copytree(
                REPO_ROOT,
                repo_dir,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "__pycache__",
                    "releases",
                    "current",
                    "runtime",
                    "release-log",
                    ".github_backup_logs",
                ),
            )

            subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Secret Refresh Test"], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "secret-refresh@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)

            config_path = repo_dir / "config" / "workspace_governance.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["workspace"]["absolute_path"] = str(repo_dir)
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            subprocess.run(
                ["git", "remote", "add", "origin", config["workspace"]["github_repository_ssh"]],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "bootstrap"], cwd=repo_dir, check=True, capture_output=True, text=True)

            marker_file = root / "refresh.called"
            refresh_stub = root / "refresh-secret-bundle.sh"
            refresh_stub.write_text(
                "#!/usr/bin/env bash\n"
                "touch \"$REFRESH_MARKER\"\n"
                "echo \"Secret bundle inputs unchanged.\"\n",
                encoding="utf-8",
            )
            refresh_stub.chmod(0o755)

            completed = subprocess.run(
                ["/bin/bash", str(repo_dir / "scripts" / "github_backup.sh")],
                cwd=repo_dir,
                env={
                    **os.environ,
                    "SECRET_RECOVERY_AUTO_REFRESH": "1",
                    "SECRET_RECOVERY_REFRESH_SCRIPT": str(refresh_stub),
                    "REFRESH_MARKER": str(marker_file),
                },
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertTrue(marker_file.exists())
            self.assertIn("No changes to back up.", completed.stdout)

    def test_backup_script_allows_secret_recovery_artifacts_but_blocks_real_secret_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="secret-recovery-allowlist-") as temp_dir:
            root = Path(temp_dir)
            repo_dir = root / "repo"
            shutil.copytree(
                REPO_ROOT,
                repo_dir,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "__pycache__",
                    "releases",
                    "current",
                    "runtime",
                    "release-log",
                    ".github_backup_logs",
                ),
            )

            subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Secret Allowlist Test"], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "secret-allowlist@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)

            config_path = repo_dir / "config" / "workspace_governance.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["workspace"]["absolute_path"] = str(repo_dir)
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            subprocess.run(
                ["git", "remote", "add", "origin", config["workspace"]["github_repository_ssh"]],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "bootstrap"], cwd=repo_dir, check=True, capture_output=True, text=True)

            bundle_dir = repo_dir / "recovery" / "secret-bundles"
            bundle_dir.mkdir(parents=True, exist_ok=True)
            bundle_file = bundle_dir / "secret-recovery-bundle-latest.tar.gz.enc"
            bundle_file.write_bytes(b"ciphertext")
            checksum_file = bundle_dir / "secret-recovery-bundle-latest.tar.gz.enc.sha256"
            checksum_file.write_text("deadbeef  secret-recovery-bundle-latest.tar.gz.enc\n", encoding="utf-8")
            forbidden_file = repo_dir / "customer_token.txt"
            forbidden_file.write_text("secret-token\n", encoding="utf-8")

            subprocess.run(
                ["git", "add", "-f", str(bundle_file.relative_to(repo_dir)), str(checksum_file.relative_to(repo_dir)), "customer_token.txt"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )

            completed = subprocess.run(
                ["/bin/bash", str(repo_dir / "scripts" / "github_backup.sh")],
                cwd=repo_dir,
                env={**os.environ, "SECRET_RECOVERY_AUTO_REFRESH": "0"},
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("customer_token.txt", completed.stderr)
            self.assertNotIn("secret-recovery-bundle-latest.tar.gz.enc", completed.stderr)


if __name__ == "__main__":
    unittest.main()
