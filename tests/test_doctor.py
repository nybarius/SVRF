"""`svrf doctor`: read-only checks, each exercised with a fake subprocess runner or a fake
GitHub object so nothing here needs a real token or the network."""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fakes import ROOT

from svrf import cli, doctor
from svrf.config import from_dict
from svrf.errors import ReadFailed

MINIMAL = {"repo": "owner/name", "gate": {"commands": ["true"]}}


def fake_run(script: dict):
    """`script`: argv-prefix (tuple) -> CompletedProcess-ish result, matched by prefix."""

    def run(argv, timeout=20):
        for prefix, result in script.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return result
        raise AssertionError(f"unscripted call: {argv}")

    return run


def cp(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, out, err)


class GitAndGh(unittest.TestCase):
    def test_git_ok(self):
        check = doctor.check_git(fake_run({("git", "-C", ".", "--version"): cp([], 0, "git version 2.40.0\n")}))
        self.assertTrue(check.ok)
        self.assertIn("2.40.0", check.detail)

    def test_git_missing(self):
        check = doctor.check_git(fake_run({("git", "-C", ".", "--version"): cp([], 127, "", "not found")}))
        self.assertFalse(check.ok)
        self.assertTrue(check.fix)

    def test_gh_ok(self):
        check = doctor.check_gh(fake_run({("gh", "--version"): cp([], 0, "gh version 2.50.0\n")}))
        self.assertTrue(check.ok)

    def test_gh_missing(self):
        check = doctor.check_gh(fake_run({("gh", "--version"): cp([], 127, "", "not found")}))
        self.assertFalse(check.ok)


class GateCommand(unittest.TestCase):
    def test_ok_when_the_command_is_on_path(self):
        config = from_dict({**MINIMAL, "gate": {"commands": ["true"]}})
        check = doctor.check_gate_command(config)
        self.assertTrue(check.ok)

    def test_fails_when_missing_from_path(self):
        config = from_dict({**MINIMAL, "gate": {"commands": ["this-tool-does-not-exist-anywhere"]}})
        check = doctor.check_gate_command(config)
        self.assertFalse(check.ok)
        self.assertIn("this-tool-does-not-exist-anywhere", check.detail)

    def test_fails_with_no_commands_configured(self):
        config = from_dict(MINIMAL)
        config.gate.commands = []
        check = doctor.check_gate_command(config)
        self.assertFalse(check.ok)


class Token(unittest.TestCase):
    def test_ok_with_classic_scopes_including_repo(self):
        headers = "HTTP/2.0 200\r\nx-oauth-scopes: repo, read:org\r\n\r\n{}"
        check = doctor.check_token("owner/name", fake_run({("gh", "api", "repos/owner/name", "-i"): cp([], 0, headers)}))
        self.assertTrue(check.ok)

    def test_fails_missing_repo_scope(self):
        headers = "HTTP/2.0 200\r\nx-oauth-scopes: read:org\r\n\r\n{}"
        check = doctor.check_token("owner/name", fake_run({("gh", "api", "repos/owner/name", "-i"): cp([], 0, headers)}))
        self.assertFalse(check.ok)

    def test_ok_with_a_fine_grained_token_reporting_no_scopes_header(self):
        headers = "HTTP/2.0 200\r\n\r\n{}"
        check = doctor.check_token("owner/name", fake_run({("gh", "api", "repos/owner/name", "-i"): cp([], 0, headers)}))
        self.assertTrue(check.ok)

    def test_fails_when_the_repository_cannot_be_reached(self):
        check = doctor.check_token("owner/name", fake_run(
            {("gh", "api", "repos/owner/name", "-i"): cp([], 1, "", "HTTP 404: Not Found")}))
        self.assertFalse(check.ok)
        self.assertTrue(check.fix)


class BranchProtection(unittest.TestCase):
    def test_ok_with_no_protection(self):
        check = doctor.check_branch_protection("owner/name", "main", fake_run(
            {("gh", "api", "repos/owner/name/branches/main/protection"): cp([], 1, "", "HTTP 404: Branch not protected")}))
        self.assertTrue(check.ok)

    def test_ok_when_protection_has_no_required_status_checks(self):
        check = doctor.check_branch_protection("owner/name", "main", fake_run(
            {("gh", "api", "repos/owner/name/branches/main/protection"): cp([], 0, "{}")}))
        self.assertTrue(check.ok)

    def test_fails_when_required_status_checks_would_block_svrf(self):
        body = '{"required_status_checks": {"contexts": ["ci/build"]}}'
        check = doctor.check_branch_protection("owner/name", "main", fake_run(
            {("gh", "api", "repos/owner/name/branches/main/protection"): cp([], 0, body)}))
        self.assertFalse(check.ok)
        self.assertIn("ci/build", check.detail)


class RateBudget(unittest.TestCase):
    def test_ok_with_remaining_budget(self):
        class GH:
            def rate_limit(self):
                return {"graphql": {"remaining": 100}, "core": {"remaining": 4999}}

        check = doctor.check_rate_budget(GH())
        self.assertTrue(check.ok)
        self.assertIn("4999", check.detail)

    def test_fails_when_the_read_itself_fails(self):
        class GH:
            def rate_limit(self):
                raise ReadFailed("GH_FAILED:1:no network")

        check = doctor.check_rate_budget(GH())
        self.assertFalse(check.ok)

    def test_fails_on_exhausted_budget(self):
        class GH:
            def rate_limit(self):
                return {"core": {"remaining": 0}}

        check = doctor.check_rate_budget(GH())
        self.assertFalse(check.ok)


class RenderAndRun(unittest.TestCase):
    def test_render_marks_ok_and_failed_checks_and_includes_fixes(self):
        text = doctor.render([doctor.Check("a", True, "fine"), doctor.Check("b", False, "broken", fix="do x")])
        self.assertIn("✓ a: fine", text)
        self.assertIn("✗ b: broken", text)
        self.assertIn("fix: do x", text)

    def test_run_calls_every_check_with_the_injected_collaborators(self):
        config = from_dict(MINIMAL)

        class GH:
            def rate_limit(self):
                return {"core": {"remaining": 10}}

        script = {
            ("git", "-C", ".", "--version"): cp([], 0, "git 2\n"),
            ("gh", "--version"): cp([], 0, "gh 2\n"),
            ("gh", "api", "repos/owner/name", "-i"): cp([], 0, "\r\n{}"),
            ("gh", "api", "repos/owner/name/branches/main/protection"): cp([], 1, "", "404"),
        }
        checks = doctor.run(config, github=GH(), subprocess_run=fake_run(script))
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(isinstance(c, doctor.Check) for c in checks))


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_svrf_doctor_prints_a_check_per_line_and_exits_nonzero_on_failure(self):
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir = tmp / "bin"
            bindir.mkdir()
            fake_gh = bindir / "gh"
            fake_gh.write_text("#!/usr/bin/env bash\necho 'HTTP 404: Not Found' >&2\nexit 1\n")
            fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
            path = tmp / "svrf.toml"
            path.write_text(f'repo = "owner/name"\nclone = "{tmp / "clone"}"\nstate_dir = "{tmp / "state"}"\n'
                            '[gate]\ncommands = ["true"]\n')
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{bindir}:{old_path}"
            try:
                code, out = self.run_cli("--config", str(path), "doctor")
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(code, 1)
            self.assertIn("token access", out)
            self.assertIn("fix:", out)


if __name__ == "__main__":
    unittest.main()
