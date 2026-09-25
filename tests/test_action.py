"""The GitHub Action's entry script (`action/run.sh`), run directly with a fake `svrf`
and a fake `gh` on `PATH` so this needs no runner and no real token."""

from __future__ import annotations

import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "action" / "run.sh"


def make_fake(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class ActionEntryScript(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls.log"
        make_fake(self.bin / "gh", f'echo "gh $*" >> "{self.calls}"\nexit 0')
        make_fake(self.bin / "svrf", f'echo "svrf $*" >> "{self.calls}"\nexit 0')
        self.config = self.tmp / "svrf.toml"
        self.config.write_text("repo = \"o/r\"\n[gate]\ncommands = [\"true\"]\n", encoding="utf-8")

    def run_script(self, env_overrides: dict) -> subprocess.CompletedProcess:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home)}
        env.update(env_overrides)
        return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)

    def test_it_sets_up_git_identity_and_runs_svrf_with_the_given_config(self):
        done = self.run_script({"GH_TOKEN": "test-token", "SVRF_CONFIG": str(self.config)})
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls.read_text(encoding="utf-8")
        self.assertIn("gh auth setup-git", calls)
        self.assertIn(f"svrf --config {self.config} run --once", calls)
        name = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True,
                              env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"}).stdout.strip()
        self.assertEqual(name, "svrf")

    def test_it_does_not_overwrite_an_existing_git_identity(self):
        subprocess.run(["git", "config", "--global", "user.name", "someone"], check=True,
                       env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"})
        self.run_script({"GH_TOKEN": "test-token", "SVRF_CONFIG": str(self.config)})
        name = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True,
                              env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"}).stdout.strip()
        self.assertEqual(name, "someone")

    def test_it_refuses_to_run_without_a_token(self):
        done = self.run_script({"SVRF_CONFIG": str(self.config)})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("github-token", done.stderr)
        self.assertEqual(self.calls.read_text(encoding="utf-8") if self.calls.exists() else "", "")

    def test_it_refuses_to_run_without_a_config(self):
        done = self.run_script({"GH_TOKEN": "test-token"})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("config", done.stderr)

    def test_it_runs_init_first_when_the_config_file_does_not_exist_yet(self):
        missing = self.tmp / "auto-svrf.toml"
        done = self.run_script({"GH_TOKEN": "test-token", "SVRF_CONFIG": str(missing),
                                "GITHUB_REPOSITORY": "owner/name"})
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls.read_text(encoding="utf-8")
        self.assertIn(f"svrf init --yes --config {missing} --repo owner/name", calls)
        self.assertIn(f"svrf --config {missing} run --once", calls)

    def test_it_does_not_run_init_when_the_config_file_already_exists(self):
        done = self.run_script({"GH_TOKEN": "test-token", "SVRF_CONFIG": str(self.config),
                                "GITHUB_REPOSITORY": "owner/name"})
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls.read_text(encoding="utf-8")
        self.assertNotIn("svrf init", calls)


if __name__ == "__main__":
    unittest.main()
