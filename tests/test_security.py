"""Attacker-controlled strings (a pull request's title, branch name or body, on a public
repository, come from whoever opened the pull request or forked the repo) never reach a
shell, and the GitHub token never reaches a log or a receipt.

Every subprocess call in this project is an argv list (`subprocess.run([...])`, never
`shell=True` or `os.system`), so a malicious title or branch name is at worst one literal
argument or one byte string embedded in a git object — it is never parsed as shell syntax.
These tests exercise that with real attacker-shaped strings and a canary file: if any of
them were ever concatenated into a shell command, the canary would appear.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fakes import git

from svrf.admission import Admission
from svrf.errors import ReadFailed, RateLimited, classify_gh_failure
from svrf.gate import CommandGate
from svrf.git import RealGit
from svrf.github import RealGitHub, gh_argv
from svrf.redact import redact, secret_values

# Shell metacharacters a title, branch name or body can legitimately contain on GitHub
# (none of these are rejected by GitHub's API), chosen to break naive shell interpolation.
INJECTION_PAYLOADS = [
    "$(touch {marker})",
    "`touch {marker}`",
    "; touch {marker} ;",
    "&& touch {marker}",
    "| touch {marker}",
    "'; touch {marker}; '",
    '"; touch {marker}; "',
]


class NoShellIsEverUsed(unittest.TestCase):
    """`shell=True` and `os.system` are grep-absent from the whole package: every call a
    malicious value could reach is an argv list."""

    def test_no_source_file_uses_a_shell_string_interpolation_call(self):
        root = Path(__file__).resolve().parents[1] / "src" / "svrf"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text, path)
            self.assertNotIn("os.system(", text, path)
            self.assertNotIn("os.popen(", text, path)


class MaliciousBranchNamesAndTitles(unittest.TestCase):
    """A branch name or a pull-request title is attacker-controlled on a public repo (a
    fork opens the pull request); it must never be interpreted as shell syntax, whether it
    ends up in a commit message, a push refspec, or a re-landed history."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.marker = self.tmp / "pwned"
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        self.work.mkdir()
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "remote", "add", "origin", str(self.origin))
        (self.work / "a.txt").write_text("a\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "base")
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.base = git(self.work, "rev-parse", "HEAD")

    def assertNoCanaryRan(self):
        self.assertFalse(self.marker.exists(), "a shell command embedded in attacker data ran")

    def test_a_commit_message_built_from_a_malicious_branch_name_never_runs_a_shell(self):
        git_repo = RealGit(self.work, identity=IDENT_TUPLE)
        git(self.work, "checkout", "-q", "-b", "acc-side", self.base)
        (self.work / "acc.txt").write_text("acc\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "acc side")
        acc = git(self.work, "rev-parse", "acc-side")
        git(self.work, "checkout", "-q", "-b", "head-side", self.base)
        (self.work / "head.txt").write_text("head\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "head side")
        head = git(self.work, "rev-parse", "head-side")
        for payload in INJECTION_PAYLOADS:
            ref = f"work/{payload.format(marker=self.marker)}"
            # a real, non-fast-forward union merge: this actually reaches `commit-tree -m <message>`
            step = git_repo.union_step(acc, head, f"Merge main into {ref} (repair: STALE_BASE)")
            self.assertEqual(step.status, "CLEAN", step)
            self.assertNoCanaryRan()
            message = git(self.work, "log", "-1", "--format=%B", step.commit)
            self.assertIn(payload.format(marker=self.marker), message)

    def test_a_malicious_title_reaches_commit_tree_as_one_literal_argument(self):
        git_repo = RealGit(self.work, identity=IDENT_TUPLE)
        git(self.work, "checkout", "-q", "-b", "feature", self.base)
        (self.work / "b.txt").write_text("b\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "feature: b")
        head = git(self.work, "rev-parse", "feature")
        for payload in INJECTION_PAYLOADS:
            title = f"Add a feature {payload.format(marker=self.marker)}"
            result = git_repo.reland(self.base, git_repo.tree(head), title, lambda p: "code")
            self.assertIn(result.status, ("CLEAN", "MISMATCH"))
            self.assertNoCanaryRan()
            if result.commits:
                message = git(self.work, "log", "-1", "--format=%B", result.commits[-1])
                # the payload survives byte-for-byte as commit message content, not as executed shell
                self.assertIn(payload.format(marker=self.marker), message)

    def test_push_branch_refuses_to_be_a_flag_and_never_shells_out(self):
        git_repo = RealGit(self.work)
        for payload in INJECTION_PAYLOADS:
            branch = f"work/{payload.format(marker=self.marker)}"
            try:
                git_repo.push_branch(self.base, branch)
            except ReadFailed:
                pass  # git may refuse an odd ref name outright; refusal is fine, execution is not
            self.assertNoCanaryRan()

    def test_gh_argv_is_one_literal_argument_list_never_a_shell_string(self):
        """`gh_argv` only ever builds an argv list; a malicious title cannot smuggle in an
        extra flag or command because it is never concatenated into a string."""
        for payload in INJECTION_PAYLOADS:
            title = f"Add a feature {payload.format(marker=self.marker)}"
            argv = gh_argv(["api", "repos/o/r/pulls", "-f", f"title={title}"], "o/r")
            self.assertEqual(argv[-1], f"title={title}")
            self.assertEqual(len(argv), 5)  # the payload is one argument, not several


IDENT_TUPLE = ("t", "t@t")


class SubprocessCallsAreArgvLists(unittest.TestCase):
    """`RealGitHub` never runs a shell: every call is `subprocess.run(["gh", ...])`, so a
    malicious pull-request title given to `open_pr` or `comment` is one argv element."""

    def test_open_pr_and_comment_pass_the_title_and_body_as_one_argument_each(self):
        seen = []

        def fake_run(argv, **kwargs):
            seen.append(argv)
            self.assertNotIn("shell", kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout='{"number": 1}', stderr="")

        gh = RealGitHub("o/r")
        payload = "$(touch /tmp/svrf-should-never-exist); `also not run`"
        with mock.patch("svrf.github.subprocess.run", side_effect=fake_run):
            gh.open_pr("branch", "main", f"title {payload}", f"body {payload}")
            gh.comment(1, f"comment {payload}")
        for argv in seen:
            self.assertIsInstance(argv, list)
            for arg in argv:
                self.assertIsInstance(arg, str)
            joined_payload_args = [a for a in argv if payload in a]
            for arg in joined_payload_args:
                # the payload is the whole value of one -f key=value argument, never split
                self.assertTrue(arg.endswith(payload) or arg == payload)


class TokenRedaction(unittest.TestCase):
    """`GH_TOKEN`/`GITHUB_TOKEN` never end up in a receipt, a held reason, or a gate log,
    even when a subprocess echoes its own inherited environment back."""

    TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"

    def test_redact_masks_configured_token_values_only(self):
        env = {"GH_TOKEN": self.TOKEN}
        self.assertEqual(secret_values(env), [self.TOKEN])
        text = f"remote: fatal error, token {self.TOKEN} rejected"
        self.assertNotIn(self.TOKEN, redact(text, env))
        self.assertIn("***REDACTED***", redact(text, env))
        # a short, unset, or irrelevant value is left alone
        self.assertEqual(redact("nothing secret here", {}), "nothing secret here")
        self.assertEqual(redact("", env), "")

    def test_a_failed_gh_call_never_carries_the_token_into_its_reason(self):
        env = {"GH_TOKEN": self.TOKEN}
        with self.assertRaises(ReadFailed) as caught:
            classify_gh_failure(1, f"HTTP 401: Bad credentials (token={self.TOKEN})", env=env)
        self.assertNotIn(self.TOKEN, caught.exception.reason)
        with self.assertRaises(RateLimited) as rate:
            classify_gh_failure(1, f"API rate limit exceeded for token {self.TOKEN}", env=env)
        self.assertNotIn(self.TOKEN, rate.exception.reason)

    def test_a_failed_git_call_never_carries_the_token_into_its_reason(self):
        tmp = Path(tempfile.mkdtemp())
        git(tmp, "init", "-q", "-b", "main")
        git_repo = RealGit(tmp)
        git_repo.env = {**git_repo.env, "GH_TOKEN": self.TOKEN}
        # a git alias whose (shell) body really does echo the inherited token to stderr and
        # fails, so this exercises the same redaction call a genuine leaking `git` error would.
        with self.assertRaises(ReadFailed) as caught:
            git_repo._out("-c", "alias.leak=!echo LEAKED $GH_TOKEN 1>&2 && false", "leak")
        self.assertNotIn(self.TOKEN, caught.exception.reason)
        self.assertIn("REDACTED", caught.exception.reason)

    def test_a_gate_command_that_echoes_the_token_never_leaves_it_in_the_log_or_the_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            clone = tmp / "clone"
            clone.mkdir()
            git(clone, "init", "-q", "-b", "main")
            (clone / "a.txt").write_text("a\n")
            git(clone, "add", ".")
            git(clone, "commit", "-qm", "base")
            base = git(clone, "rev-parse", "HEAD")
            gate = CommandGate(clone, tmp / "wt", 1, ['echo "leaking $GH_TOKEN now"'], logs=tmp / "logs",
                               env={"GH_TOKEN": self.TOKEN})
            result = gate.run(base, base, "F1")
            self.assertTrue(result["green"], result)
            for step in result["steps"]:
                self.assertNotIn(self.TOKEN, step["tail"])
            log_files = list((tmp / "logs").rglob("*.log"))
            self.assertTrue(log_files)
            for path in log_files:
                self.assertNotIn(self.TOKEN, path.read_text(encoding="utf-8"))

    def test_the_admission_command_output_is_redacted_before_becoming_a_residual_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            clone = tmp / "clone"
            clone.mkdir()
            git(clone, "init", "-q", "-b", "main")
            (clone / "a.txt").write_text("a\n")
            git(clone, "add", ".")
            git(clone, "commit", "-qm", "base")
            base = git(clone, "rev-parse", "HEAD")
            git(clone, "checkout", "-q", "-b", "feature")
            (clone / "b.txt").write_text("b\n")
            git(clone, "add", ".")
            git(clone, "commit", "-qm", "feature")
            head = git(clone, "rev-parse", "feature")
            git_repo = RealGit(clone)
            token_env_holder = os.environ.copy()
            os.environ["GH_TOKEN"] = self.TOKEN
            try:
                admission = Admission(git_repo, command='echo "check failed, token=$GH_TOKEN"; exit 1')
                value = admission(head, base)
            finally:
                os.environ.clear()
                os.environ.update(token_env_holder)
            self.assertEqual(value["verdict"], "HELD")
            residuals = " ".join(value["residuals"])
            self.assertNotIn(self.TOKEN, residuals)
            self.assertIn("REDACTED", residuals)


if __name__ == "__main__":
    unittest.main()
