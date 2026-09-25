"""`svrf init`: detecting a project's type and writing `svrf.toml` plus a scheduled
workflow, without ever overwriting either file unless asked to."""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fakes import ROOT

from svrf import cli, init
from svrf.config import load


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class Detection(unittest.TestCase):
    def test_detects_a_python_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n")
            detected = init.detect_gate(root)
            self.assertEqual(detected.project_kind, "python")
            self.assertIn("pytest", detected.gate_command)

    def test_detects_a_node_project_and_its_package_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            self.assertEqual(init.detect_gate(root).gate_command, "npm test")
            (root / "pnpm-lock.yaml").write_text("")
            self.assertEqual(init.detect_gate(root).gate_command, "pnpm test")

    def test_detects_rust_go_and_lean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text("")
            self.assertEqual(init.detect_gate(root).gate_command, "cargo test")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "go.mod").write_text("")
            self.assertEqual(init.detect_gate(root).gate_command, "go test ./...")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lakefile.toml").write_text("")
            self.assertEqual(init.detect_gate(root).gate_command, "lake build")

    def test_falls_back_to_a_makefile_test_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Makefile").write_text("test:\n\techo ok\n")
            self.assertEqual(init.detect_gate(root).gate_command, "make test")

    def test_detects_nothing_in_an_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(init.detect_gate(Path(tmp)))

    def test_slug_from_url_reads_ssh_and_https_remotes(self):
        self.assertEqual(init.slug_from_url("git@github.com:owner/name.git"), "owner/name")
        self.assertEqual(init.slug_from_url("https://github.com/owner/name.git"), "owner/name")
        self.assertEqual(init.slug_from_url("https://github.com/owner/name"), "owner/name")
        self.assertIsNone(init.slug_from_url("https://gitlab.com/owner/name"))

    def test_detect_repo_reads_the_origin_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            git(root, "remote", "add", "origin", "git@github.com:owner/name.git")
            self.assertEqual(init.detect_repo(root), "owner/name")

    def test_detect_repo_is_none_without_a_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            self.assertIsNone(init.detect_repo(root))


class Run(unittest.TestCase):
    def test_writes_config_and_workflow_from_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            git(root, "init", "-q")
            git(root, "remote", "add", "origin", "git@github.com:owner/name.git")
            result = init.run(root, yes=True)
            self.assertTrue(result.config_written)
            self.assertTrue(result.workflow_written)
            config = load(result.config_path)
            self.assertEqual(config.repo, "owner/name")
            self.assertEqual(config.gate.commands, ["npm test"])
            workflow = result.workflow_path.read_text(encoding="utf-8")
            self.assertIn("nybarius/SVRF@v0.1.0", workflow)
            self.assertIn("schedule", workflow)
            self.assertIn("ready_for_review", workflow)

    def test_is_idempotent_and_never_overwrites_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            first = init.run(root, repo="owner/name", yes=True)
            self.assertTrue(first.config_written)
            (first.config_path).write_text("repo = \"owner/name\"\ncustom = true\n[gate]\ncommands=[\"true\"]\n")
            second = init.run(root, repo="owner/name", yes=True)
            self.assertFalse(second.config_written)
            self.assertFalse(second.workflow_written)
            self.assertIn("custom", first.config_path.read_text(encoding="utf-8"))

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            init.run(root, repo="owner/name", yes=True)
            result = init.run(root, repo="owner/name", yes=True, force=True)
            self.assertTrue(result.config_written)
            self.assertTrue(result.workflow_written)

    def test_refuses_with_no_detectable_repo_and_no_tty_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                init.run(root, yes=True)

    def test_explicit_overrides_win_over_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            result = init.run(root, repo="owner/name", base="develop", gate="npm run ci", yes=True)
            config = load(result.config_path)
            self.assertEqual((config.repo, config.base, config.gate.commands), ("owner/name", "develop", ["npm run ci"]))


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_svrf_init_from_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            code, out = self.run_cli("init", "--dir", str(root), "--repo", "owner/name", "--yes")
            self.assertEqual(code, 0)
            self.assertIn("wrote", out)
            self.assertTrue((root / "svrf.toml").is_file())
            self.assertTrue((root / ".github" / "workflows" / "svrf.yml").is_file())

    def test_svrf_init_does_not_require_an_existing_svrf_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out = self.run_cli("init", "--dir", str(root), "--repo", "owner/name", "--gate", "make test",
                                     "--yes")
            self.assertEqual(code, 0)

    def test_svrf_init_reports_a_missing_repo_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            import contextlib

            with contextlib.redirect_stderr(io.StringIO()) as err:
                code, _ = self.run_cli("init", "--dir", str(root), "--yes")
            self.assertEqual(code, 2)
            self.assertIn("repo", err.getvalue())


if __name__ == "__main__":
    unittest.main()
