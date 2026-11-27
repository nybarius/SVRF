"""Only complete original no-work failures defer another occupied slot."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fakes import Clock, DaemonGitHub, DaemonRepo, FakeGate
from test_admission_progress_projection import beginning, encode_events
from test_daemon import daemon
from svrf.admission import Admission
from svrf.admission_attempt import command_environment
from svrf.daemon import Daemon
from svrf.git import RealGit
from svrf.errors import ReadFailed


class FailingRead:
    def __init__(self, clock):
        self.clock = clock
        self.command = "original-command-v1"
        self.calls = 0
        self.work = []
        self.events = "complete"
        self.reason = "IO_POOL_CAPACITY"
        self.held = False

    def __call__(self, head, base, pr=None):
        self.calls += 1
        if self.held:
            return {"verdict": "HELD", "residuals": ["check:original-failure"]}
        if self.events != "absent":
            path = Path(command_environment()["SVRF_ADMISSION_PROGRESS_FILE"])
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [beginning(pr=pr or 1, head=head, base=base)]
            rows += [{"kind": "progress", "work_id": key, "obligation": "tests/check.py",
                      "outcome": 0, "provenance": "COMPUTED"} for key in self.work]
            if self.events != "incomplete":
                rows.append({"kind": "terminal", "disposition": "UNOBSERVED", "exit": 126})
            if self.events == "mixed":
                rows[0]["head"] = "different-source"
            now = time.monotonic()
            for index, row in enumerate(rows):
                row.update(wall=self.clock(), monotonic=now + index / 1000000)
            data = encode_events(rows)
            path.write_bytes(data[:-1] if self.events == "corrupt" else data)
        raise ReadFailed(self.reason)


class SourceBindings(unittest.TestCase):
    def identity(self, kind):
        from svrf.admission import Admission
        from svrf.admission_retry import source_identity
        repo = DaemonRepo([1])
        repo.root = Path("/tmp/source-binding")
        return source_identity(Admission(repo, order="tests-first", kind=kind,
                                         command="original-command"), 1, "h1", "c0")

    def test_configured_path_sets_are_part_of_the_actual_source_occurrence(self):
        from svrf.app import kind_of
        from svrf.config import Config, HistoryConfig
        kinds = [kind_of(Config(repo="owner/repo", history=HistoryConfig(tests=tests, docs=[])))
                 for tests in (["src/**"], [])]
        self.assertEqual([kind("src/f.py") for kind in kinds], ["test", "code"])
        before, after = map(self.identity, kinds)
        self.assertEqual([before["source_status"], after["source_status"]], ["OBSERVED", "OBSERVED"])
        self.assertNotEqual(before["command_fingerprint"], after["command_fingerprint"])
        self.assertNotEqual(before["occurrence_key"], after["occurrence_key"])
        self.assertEqual(before, self.identity(kinds[0]))

    def test_defaults_and_supported_closure_values_are_consumed_configuration(self):
        def configured(value):
            return lambda path: value
        def defaulted(value):
            return lambda path, chosen=value: chosen
        def keyword_defaulted(value):
            return lambda path, *, chosen=value: chosen
        for kinds in ((configured("test"), configured("code")),
                      (defaulted("test"), defaulted("code")),
                      (keyword_defaulted("test"), keyword_defaulted("code"))):
            with self.subTest(kind=kinds[0]):
                before, after = map(self.identity, kinds)
                self.assertNotEqual(before["command_fingerprint"], after["command_fingerprint"])
                self.assertNotEqual(before["occurrence_key"], after["occurrence_key"])

    def test_an_unsupported_closure_cannot_authorize_a_same_source_delay(self):
        import threading
        resource = threading.Event()
        kind = lambda path: "test" if resource.is_set() else "code"
        self.assertEqual(self.identity(kind)["source_status"], "UNOBSERVED")

    def test_compiled_matcher_changes_are_bound_even_if_the_display_patterns_do_not_change(self):
        import re
        from svrf.globs import PathSet
        from svrf.history import path_kind
        paths = PathSet(["src/**"])
        kind = path_kind(paths, PathSet())
        before = self.identity(kind)
        self.assertEqual(kind("src/f.py"), "test")
        paths._regex = re.compile("never-match")
        self.assertEqual(kind("src/f.py"), "code")
        self.assertNotEqual(before["occurrence_key"], self.identity(kind)["occurrence_key"])


class ReadBackoff(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = DaemonRepo([1])
        self.gh = DaemonGitHub(self.repo)
        self.clock = Clock()
        self.read = FailingRead(self.clock)
        self.owner = self.make_owner()
        self.addCleanup(self.close_owner)

    def make_owner(self):
        return daemon(self.repo, self.gh, FakeGate(self.repo), self.read, self.root, clock=self.clock)

    def close_owner(self):
        if self.owner is not None:
            self.owner.close()

    def row(self):
        rows = self.owner.load_state().get("admission_retries", {})
        self.assertIn("1", rows, "actual failed attempts have no original retry ledger")
        return rows["1"]

    def fail_three(self):
        for _ in range(3):
            tick = self.owner.tick()
            self.assertEqual(tick["retry_later"], [1])
            self.assertEqual(tick["held"], [])
        row = self.row()
        self.assertEqual(row.get("no_progress_failures"), 3)
        self.assertEqual(row.get("retry_at"), self.clock() + 30)
        return row

    def test_python_reference_lifetimes_do_not_change_the_consumed_code_identity(self):
        from svrf.admission_retry import source_identity
        before = source_identity(self.read, 1, "h1", "c0")
        constants = self.read.__call__.__code__.co_consts
        after = source_identity(self.read, 1, "h1", "c0")
        self.assertTrue(constants)
        self.assertEqual(before["command_fingerprint"], after["command_fingerprint"],
                         "a live reference was confused with a new command")

    def test_three_observed_failures_defer_before_a_slot_and_observation_does_not_slide(self):
        previous = self.fail_three()
        history = self.owner.load_state()["admission_history"]
        before = self.repo.fetches
        self.clock.sleep(10)
        tick = self.owner.tick()
        self.assertEqual(self.read.calls, 3, "a deferred read occupied an executor again")
        self.assertEqual(tick["inflight"], [])
        self.assertEqual(tick["held"], [])
        self.assertEqual(tick.get("admission_backoff", {}).get("1", {}).get("retry_at"), 1030)
        self.assertGreater(self.repo.fetches, before, "the current base was not reobserved")
        self.assertEqual(self.row(), previous, "observing a deadline changed its failure count or time")
        self.assertEqual(self.owner.load_state()["admission_history"], history)
        self.clock.now = 1030
        self.owner.tick()
        self.assertEqual(self.read.calls, 4)
        self.assertEqual(self.row()["retry_at"], 1090)
        self.assertEqual(self.row()["no_progress_failures"], 4)

    def test_new_unique_work_resets_the_count_but_repeated_receipt_does_not(self):
        self.fail_three()
        self.clock.now = self.row()["retry_at"]
        self.read.work = ["original-receipt-a"]
        self.owner.tick()
        self.assertEqual(self.row()["no_progress_failures"], 0)
        self.assertIsNone(self.row()["retry_at"])
        for _ in range(3):
            self.owner.tick()
        row = self.row()
        self.assertEqual(row["no_progress_failures"], 3)
        self.assertEqual(row["completed_work_ids"], ["original-receipt-a"])
        self.assertEqual(row["retry_at"], self.clock() + 30)

    def test_repeated_unknown_read_failures_defer_without_claiming_zero_work(self):
        for mode in ("absent", "mixed", "incomplete", "corrupt"):
            with self.subTest(mode=mode):
                self.read.events = mode
                self.read.command = "read-" + mode
                before = self.read.calls
                for _ in range(3):
                    self.owner.tick()
                row = self.row()
                self.assertEqual(row["coverage_status"], "UNOBSERVED")
                self.assertIsNone(row["no_progress_failures"])
                self.assertEqual(row.get("unobserved_failures"), 3)
                self.assertEqual(row.get("backoff_kind"), "REPEATED_UNOBSERVED")
                self.assertEqual(row["retry_at"], self.clock() + 30)
                self.clock.sleep(5)
                tick = self.owner.tick()
                self.assertEqual(self.read.calls, before + 3, "identical unread work occupied a fourth slot")
                self.assertEqual(self.row(), row, "a diagnostic observation changed the original deadline")
                self.assertEqual(tick["inflight"], [])
                self.assertEqual(tick["held"], [])

    def test_different_unknown_observation_reasons_do_not_accumulate_one_cooldown(self):
        for mode in ("absent", "mixed", "corrupt"):
            self.read.events = mode
            self.owner.tick()
            row = self.row()
            self.assertEqual(row.get("unobserved_failures"), 1)
            self.assertIsNone(row["retry_at"])
            self.assertIsNone(row["no_progress_failures"])

    def test_actual_head_base_command_and_environment_changes_clear_a_deadline(self):
        changes = [
            lambda: setattr(self.read, "command", "original-command-v2"),
            lambda: setattr(self.repo, "main", self.repo._new({0, 70}, ("c0",))),
            lambda: self.repo.heads.update({1: self.repo._new({0, 1, 80}, ("h1",))}),
        ]
        for change in changes:
            with self.subTest(change=change):
                for _ in range(3):
                    if self.row_if_present().get("no_progress_failures", 0) == 3:
                        break
                    self.owner.tick()
                self.assertEqual(self.row()["no_progress_failures"], 3)
                original = self.row()["occurrence_key"]
                before = self.read.calls
                change()
                self.owner.tick()
                self.assertEqual(self.read.calls, before + 1)
                self.assertNotEqual(self.row()["occurrence_key"], original)
                self.assertEqual(self.row()["no_progress_failures"], 1)
                self.assertIsNone(self.row()["retry_at"])
        for _ in range(2):
            self.owner.tick()
        before = self.read.calls
        with patch.dict(os.environ, {"SVRF_TEST_RESOURCE_ID": "changed"}):
            self.owner.tick()
            self.assertEqual(self.read.calls, before + 1)
            self.assertEqual(self.row()["no_progress_failures"], 1)
            self.assertIsNone(self.row()["retry_at"])

    def row_if_present(self):
        return self.owner.load_state().get("admission_retries", {}).get("1", {})

    def test_a_new_owner_retains_the_original_deadline_without_a_second_failure(self):
        original = self.fail_three()
        self.owner.close()
        self.owner = self.make_owner()
        self.owner.tick()
        self.assertEqual(self.read.calls, 3)
        self.assertEqual(self.row(), original)
        self.assertEqual(len(self.owner.load_state()["admission_history"]), 3)

    def test_exponential_delay_is_bounded_and_different_failure_resets_it(self):
        self.fail_three()
        for expected in (60, 120, 240, 480, 900, 900):
            self.clock.now = self.row()["retry_at"]
            self.owner.tick()
            self.assertEqual(self.row()["retry_at"] - self.clock(), expected)
        self.clock.now = self.row()["retry_at"]
        self.read.reason = "DIFFERENT_SOURCE_READ_FAILURE"
        self.owner.tick()
        self.assertEqual(self.row()["no_progress_failures"], 1)
        self.assertIsNone(self.row()["retry_at"])

    def test_a_real_failed_check_stays_held_and_has_no_read_failure_cooldown(self):
        self.fail_three()
        self.read.command = "check-current-source"
        self.read.held = True
        tick = self.owner.tick()
        self.assertEqual(tick["held"], [1])
        self.assertEqual(tick["retry_later"], [])
        self.assertNotIn("1", self.owner.load_state().get("admission_retries", {}))
        self.assertEqual(self.owner.load_state()["held"]["1"]["reason"], "ADMISSION_HELD")


class CountedCommand(Admission):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    def _run_command(self, *args, **kwargs):
        self.calls += 1
        return super()._run_command(*args, **kwargs)


class ReadBasisBackoff(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@localhost")
        (self.source / "read").mkdir()
        (self.source / "read/one").write_text("original dependency\n")
        (self.source / "unread").write_text("original other file\n")
        self.commit()
        self.git("checkout", "-qb", "candidate")
        (self.source / "candidate").write_text("candidate change\n")
        self.head = self.commit()
        self.git("checkout", "-q", "main")
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "origin", "main", "candidate:refs/pull/1/head")
        self.repo = RealGit(self.source)
        self.repo.heads = {1: self.head}
        self.repo.branches = {"pr-1": self.head}
        self.gh = DaemonGitHub(self.repo)
        self.clock = Clock()
        self.read = CountedCommand(self.repo, command=self.command())
        self.owner = self.make_owner()
        self.addCleanup(lambda: self.owner.close())

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "source occurrence")
        return self.git("rev-parse", "HEAD")

    def make_owner(self):
        return Daemon(self.repo, self.gh, FakeGate(self.repo), self.read,
                      state_dir=self.root / "state", receipts=self.root / "receipts",
                      clock=self.clock, sleep=self.clock.sleep, repair=False, reland=False,
                      train_options={"poll_seconds": 0})

    def command(self):
        project = Path(__file__).resolve().parents[1]
        code = f"""
import json, os, subprocess, sys, time
from pathlib import Path
sys.path[:0] = {[str(project / "src"), str(project / "tests")]!r}
from test_admission_progress_projection import beginning, encode_events
selected = subprocess.check_output(["git", "show", os.environ["SVRF_BASE"] + ":read/one"])
print(selected.decode(), end="")
value = {{"schema": "svrf.admission-reads/1",
          "head": os.environ["SVRF_HEAD"], "base": os.environ["SVRF_BASE"],
          "consumed": [{{"kind": "PATH", "id": "read/one"}}]}}
Path(os.environ["SVRF_ADMISSION_READS"]).write_text(json.dumps(value))
rows = [beginning(pr=int(os.environ["SVRF_PR"]), head=os.environ["SVRF_HEAD"],
                  base=os.environ["SVRF_BASE"]),
        {{"kind": "terminal", "disposition": "UNOBSERVED", "exit": 126}}]
for row in rows:
    row.update(wall=time.time(), monotonic=time.monotonic())
progress = Path(os.environ["SVRF_ADMISSION_PROGRESS_FILE"])
progress.parent.mkdir(parents=True, exist_ok=True)
progress.write_bytes(encode_events(rows))
print("IO_POOL_CAPACITY")
raise SystemExit(126)
"""
        return shlex.quote(sys.executable) + " -c " + shlex.quote(code)

    def test_only_a_changed_received_dependency_reopens_a_failed_command(self):
        for _ in range(3):
            tick = self.owner.tick()
            self.assertEqual(tick["retry_later"], [1],
                             json.dumps({"tick": tick, "state": self.owner.load_state()}, sort_keys=True))
            self.assertEqual(tick["held"], [])
        original = self.owner.load_state()
        failure = original["admission_retries"]["1"]
        self.assertEqual(failure["no_progress_failures"], 3)
        self.assertIsNotNone(failure["retry_at"])
        self.assertEqual(self.read.calls, 3)
        base = self.repo.main_sha()
        before = self.repo.watch_digest(base, ["read/one"])

        (self.source / "unread").write_text("unrelated change\n")
        changed = self.commit()
        self.git("push", "-q", "origin", "main")
        self.assertNotEqual(changed, base)
        self.assertEqual(self.repo.watch_digest(changed, ["read/one"]), before)
        tick = self.owner.tick()
        self.assertEqual(self.read.calls, 3, "an unread base move paid the same failed command again")
        retained = self.owner.load_state()
        self.assertEqual(retained["admission_retries"]["1"], failure)
        self.assertEqual(retained["admission_history"], original["admission_history"])
        self.assertEqual(tick["deferred"], [1])

        self.owner.close()
        self.owner = self.make_owner()
        self.owner.tick()
        self.assertEqual(self.read.calls, 3)
        self.assertEqual(self.owner.load_state()["admission_retries"]["1"], failure)

        (self.source / "read/one").write_text("changed dependency\n")
        changed = self.commit()
        self.git("push", "-q", "origin", "main")
        self.assertNotEqual(self.repo.watch_digest(changed, ["read/one"]), before)
        self.owner.tick()
        self.assertEqual(self.read.calls, 4)
        current = self.owner.load_state()
        self.assertEqual(current["admission_retries"]["1"]["no_progress_failures"], 1)
        self.assertIsNone(current["admission_retries"]["1"]["retry_at"])
        self.assertEqual(len(current["admission_history"]), len(original["admission_history"]) + 1)
        for identity, occurrence in original["admission_history"].items():
            self.assertEqual(current["admission_history"][identity], occurrence)


if __name__ == "__main__":
    unittest.main()
