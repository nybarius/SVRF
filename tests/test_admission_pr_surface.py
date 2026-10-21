"""Admission holds use the existing PR surface without pretending a gate ran.

These cases exercise the real owner and the original repository, gate and GitHub
fixtures. The GitHub subclass records effects and supplies ordinary read failures
at that existing port; no admission, hold, train or rendering method is replaced.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from fakes import Admission, Clock, DaemonGitHub, DaemonRepo, FakeGate
from test_daemon import daemon

from svrf import pr_surface
from svrf.errors import RateLimited, ReadFailed


class SurfaceGitHub(DaemonGitHub):
    def __init__(self, repo, **kwargs):
        super().__init__(repo, **kwargs)
        self.fail = set()
        self.status_limits = 0
        self.attempts = {"status": 0, "comment_list": 0, "comment_write": 0}
        self.written_bodies = []

    def _attempt(self, kind):
        self.attempts[kind] += 1
        if kind in self.fail:
            self.calls["rest"] += 1
            raise ReadFailed(f"SURFACE_UNREAD:{kind}")

    def set_status(self, sha, state, description, context="svrf", target_url=None):
        self._attempt("status")
        if self.status_limits:
            self.status_limits -= 1
            self.calls["rest"] += 1
            raise RateLimited("status rate limit", reset=self.clock() + 7)
        return super().set_status(sha, state, description, context, target_url)

    def list_comments(self, number):
        self._attempt("comment_list")
        return super().list_comments(number)

    def comment(self, number, body):
        self._attempt("comment_write")
        result = super().comment(number, body)
        self.written_bodies.append(body)
        return result

    def update_comment(self, comment_id, body):
        self._attempt("comment_write")
        result = super().update_comment(comment_id, body)
        self.written_bodies.append(body)
        return result


class HoldDriver:
    """A supported demand driver calls the owner's actual hold operation."""

    def __init__(self, row, failing, repeats=1):
        self.row, self.failing, self.repeats = row, failing, repeats

    def drain(self, owner):
        state = owner.load_state()
        summary = {"tick": "RAN", "at": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(owner.clock())),
                   "held": [], "held_rows": [], "admitted": [], "merged": [],
                   "receipt": None, "receipts": [], "retry_later": [], "reasons": {}, "stopped": False}
        for _ in range(self.repeats):
            owner.hold(self.row, "ADMISSION_HELD", state, summary, failing=self.failing)
        owner.save(state, summary)
        return summary


class AdmissionPrSurface(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.repo = DaemonRepo([101])
        self.clock = Clock()
        self.gh = SurfaceGitHub(self.repo, clock=self.clock)
        self.gate = FakeGate(self.repo)
        self.failing = ["check:lint failed", "FAILED tests/test_example.py::test_rule"]
        self.admission = Admission({"h101": {"verdict": "HELD", "residuals": self.failing}})

    def owner(self, **kwargs):
        value = daemon(self.repo, self.gh, self.gate, self.admission, self.tmp,
                       clock=self.clock, **kwargs)
        self.addCleanup(value.close)
        return value

    def driver(self, **kwargs):
        return HoldDriver({"number": 101, "headRefOid": self.repo.heads[101],
                           "headRefName": "pr-101", "title": "lane 101"}, self.failing, **kwargs)

    def assert_admission_only(self, summary):
        self.assertEqual(summary["held"], [101])
        self.assertEqual(summary["admitted"], [])
        self.assertEqual(summary["merged"], [])
        self.assertEqual(summary["retry_later"], [])
        self.assertFalse(summary["stopped"])
        self.assertEqual(self.gate.trees, [])
        self.assertEqual(self.repo.pushes, [])
        self.assertEqual(self.gh.merged, [])
        self.assertIsNone(summary["receipt"])
        self.assertEqual(summary["receipts"], [])
        self.assertEqual(list((self.tmp / "receipts").glob("train-*.json")), [])

    def assert_status(self, head="h101", failing=None, target=None):
        first = (self.failing if failing is None else failing)[0]
        expected = pr_surface.status_line({"number": 101, "phase": "HELD", "reason_line": first})
        rows = self.gh.statuses.get(head, [])
        self.assertEqual(len(rows), 1, "the held source head must receive one terminal status")
        self.assertEqual(rows[0], {"state": expected[0], "description": expected[1],
                                   "context": pr_surface.CONTEXT, "target_url": target})

    def test_admission_hold_publishes_on_its_head_with_comments_disabled(self):
        summary = self.owner(train={"pr_comments": False, "status_checks": True}).tick()
        self.assert_admission_only(summary)
        held = json.loads((self.tmp / "held.json").read_text())["held"][0]
        self.assertEqual((held["number"], held["head"], held["reason"], held["failing"]),
                         (101, "h101", "ADMISSION_HELD", self.failing))
        self.assert_status()
        self.assertEqual(self.gh.comment_rows, [])
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 0, "comment_write": 0})

    def test_admission_comment_has_no_queued_or_gate_execution_claim(self):
        summary = self.owner().tick()
        self.assert_admission_only(summary)
        self.assert_status()
        self.assertEqual(len(self.gh.comment_rows), 1)
        body = self.gh.comment_rows[0]["body"]
        self.assertEqual(body, pr_surface.render_comment({
            "number": 101, "phase": "HELD", "history": [], "failing": self.failing,
            "reason_line": self.failing[0]}))
        self.assertIn("○ queued → ○ gating → ✖️ held", body)
        self.assertNotIn("Batch `", body)
        self.assertNotIn("Gate:", body)
        self.assertNotIn("landed tree = gated tree", body)
        self.assertTrue(pr_surface.comment_hash(body))

    def test_comments_can_be_enabled_without_status_checks(self):
        summary = self.owner(train={"status_checks": False, "pr_comments": True}).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(len(self.gh.comment_rows), 1)
        self.assertEqual(self.gh.attempts, {"status": 0, "comment_list": 1, "comment_write": 1})

    def test_both_ui_flags_disabled_make_no_surface_calls(self):
        summary = self.owner(train={"status_checks": False, "pr_comments": False}).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(self.gh.comment_rows, [])
        self.assertEqual(self.gh.attempts, {"status": 0, "comment_list": 0, "comment_write": 0})

    def test_dry_run_does_not_publish_an_admission_hold(self):
        summary = self.owner(dry_run=True).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(self.gh.comment_rows, [])
        self.assertEqual(self.gh.attempts, {"status": 0, "comment_list": 0, "comment_write": 0})
        self.assertFalse((self.tmp / "state.json").exists())

    def test_a_supported_driver_uses_the_same_actual_hold_surface(self):
        summary = self.owner(demand=self.driver()).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.admission.calls, [])
        self.assert_status()
        self.assertEqual(len(self.gh.comment_rows), 1)

    def test_a_hold_without_an_observed_head_publishes_nothing(self):
        driver = self.driver()
        driver.row["headRefOid"] = None
        summary = self.owner(demand=driver).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.attempts, {"status": 0, "comment_list": 0, "comment_write": 0})
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(self.gh.comment_rows, [])

    def test_unchanged_held_heads_are_not_read_or_published_again(self):
        owner = self.owner()
        self.assert_admission_only(owner.tick())
        self.assert_status()
        attempts = dict(self.gh.attempts)
        calls = list(self.admission.calls)
        summary = owner.tick()
        self.assertEqual(summary["tick"], "IDLE")
        self.assertEqual(summary["held_unchanged"], [101])
        self.assertEqual(self.admission.calls, calls)
        self.assertEqual(self.gh.attempts, attempts)
        self.assertEqual(self.gate.trees, [])

    def test_repeated_driver_holds_do_not_repeat_a_successful_publication(self):
        driver = self.driver(repeats=3)
        self.assert_admission_only(self.owner(demand=driver).tick())
        self.assert_status()
        attempts = dict(self.gh.attempts)
        self.clock.sleep(1)
        self.assert_admission_only(self.owner(demand=driver).tick())
        self.assertEqual(self.gh.attempts, attempts)
        self.assertEqual(len(self.gh.comment_rows), 1)

    def test_a_changed_head_gets_its_own_status(self):
        owner = self.owner(train={"pr_comments": False})
        self.assert_admission_only(owner.tick())
        self.assert_status()
        head = self.repo.move_head(101)
        self.admission.verdicts[head] = {"verdict": "HELD", "residuals": self.failing}
        self.assert_admission_only(owner.tick())
        self.assert_status(head)
        self.assertEqual(set(self.gh.statuses), {"h101", head})
        self.assertEqual(len(self.admission.calls), 2)

    def test_a_changed_hold_reason_updates_the_same_comment(self):
        driver = self.driver()
        owner = self.owner(demand=driver)
        self.assert_admission_only(owner.tick())
        self.assert_status()
        self.assertEqual(len(self.gh.comment_rows), 1)
        original_id = self.gh.comment_rows[0]["id"]
        driver.failing = ["check:signature missing"]
        self.assert_admission_only(owner.tick())
        self.assertEqual(len(self.gh.statuses["h101"]), 2)
        self.assertIn("signature missing", self.gh.statuses["h101"][-1]["description"])
        self.assertEqual(len(self.gh.comment_rows), 1)
        self.assertEqual(self.gh.comment_rows[0]["id"], original_id)
        self.assertIn("check:signature missing", self.gh.comment_rows[0]["body"])

    def test_an_existing_identical_surface_comment_keeps_its_hash_and_id(self):
        body = pr_surface.render_comment({"number": 101, "phase": "HELD", "history": [],
                                          "failing": self.failing, "reason_line": self.failing[0]})
        self.gh.comment(101, body)
        original_id = self.gh.comment_rows[0]["id"]
        writes = self.gh.attempts["comment_write"]
        summary = self.owner().tick()
        self.assert_admission_only(summary)
        self.assert_status()
        self.assertEqual(self.gh.attempts["comment_write"], writes)
        self.assertEqual(self.gh.comment_rows, [{"id": original_id, "number": 101, "body": body}])
        self.assertEqual(summary.get("surface"), {"status": 1, "comment_write": 0, "comment_skip": 1})

    def test_new_admission_effect_counts_are_retained_in_the_tick_receipt(self):
        summary = self.owner(train={"pr_comments": False}).tick()
        self.assert_admission_only(summary)
        self.assert_status()
        counts = {"status": 1, "comment_write": 0, "comment_skip": 0}
        self.assertEqual(summary.get("surface"), counts)
        self.assertEqual(summary.get("api_calls"), self.gh.calls)
        receipts = list((self.tmp / "receipts").glob("tick-*.json"))
        self.assertEqual(len(receipts), 1)
        recorded = json.loads(receipts[0].read_text())
        self.assertEqual(recorded.get("surface"), counts)
        self.assertEqual(recorded.get("api_calls"), self.gh.calls)
        self.assertEqual(recorded["receipts"], [])

    def test_dashboard_url_is_used_for_the_exact_admission_head(self):
        target = "https://dash.example/run"
        summary = self.owner(train={"pr_comments": False, "dashboard_url": target}).tick()
        self.assert_admission_only(summary)
        self.assert_status(target=target)
        self.assertNotIn(self.repo.main, self.gh.statuses)

    def test_status_read_failure_keeps_the_hold_and_allows_the_comment(self):
        self.gh.fail.add("status")
        summary = self.owner().tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(len(self.gh.comment_rows), 1)
        self.assertEqual(summary.get("surface"), {"status": 0, "comment_write": 1, "comment_skip": 0})

    def test_comment_read_failure_keeps_the_hold_and_successful_status(self):
        self.gh.fail.add("comment_list")
        summary = self.owner().tick()
        self.assert_admission_only(summary)
        self.assert_status()
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 0})
        self.assertEqual(self.gh.comment_rows, [])
        self.assertEqual(summary.get("surface"), {"status": 1, "comment_write": 0, "comment_skip": 0})

    def test_comment_write_failure_keeps_the_hold_and_reports_no_success(self):
        self.gh.fail.add("comment_write")
        summary = self.owner(train={"status_checks": False}).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.attempts, {"status": 0, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.gh.comment_rows, [])
        self.assertEqual(summary.get("surface"), {"status": 0, "comment_write": 0, "comment_skip": 0})

    def test_a_rate_limit_does_not_wait_or_reclassify_admission(self):
        self.gh.status_limits = 1
        summary = self.owner(train={"pr_comments": False}).tick()
        self.assert_admission_only(summary)
        self.assertEqual(self.gh.attempts["status"], 1)
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(self.clock.slept, [])
        self.assertEqual(summary.get("surface"), {"status": 0, "comment_write": 0, "comment_skip": 0})
        self.assertEqual(summary.get("api_calls"), self.gh.calls)

    def test_a_failed_effect_can_retry_without_repeating_a_successful_effect(self):
        self.gh.status_limits = 1
        owner = self.owner(demand=self.driver())
        self.assert_admission_only(owner.tick())
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(self.clock.slept, [])
        self.assert_admission_only(owner.tick())
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 1})
        self.clock.now += 7
        self.assert_admission_only(owner.tick())
        self.assert_status()
        self.assertEqual(self.gh.attempts, {"status": 2, "comment_list": 1, "comment_write": 1})
        self.assertEqual(len(self.gh.comment_rows), 1)
        attempts = dict(self.gh.attempts)
        self.assert_admission_only(owner.tick())
        self.assertEqual(self.gh.attempts, attempts)
        self.assertEqual(self.clock.slept, [])

    def test_an_unchanged_admission_hold_retries_only_the_failed_effect_after_reset(self):
        self.gh.status_limits = 1
        owner = self.owner()
        self.assert_admission_only(owner.tick())
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 1})
        calls = list(self.admission.calls)
        summary = owner.tick()
        self.assertEqual(summary["tick"], "IDLE")
        self.assertEqual(summary["held_unchanged"], [101])
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.admission.calls, calls)
        self.clock.now += 7
        summary = owner.tick()
        self.assertEqual(summary["tick"], "IDLE")
        self.assertEqual(summary["held_unchanged"], [101])
        self.assert_status()
        self.assertEqual(self.gh.attempts, {"status": 2, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.admission.calls, calls)
        self.assertEqual(self.gate.trees, [])
        self.assertEqual(self.clock.slept, [])
        self.assertEqual(list((self.tmp / "receipts").glob("train-*.json")), [])
        attempts = dict(self.gh.attempts)
        owner.tick()
        self.assertEqual(self.gh.attempts, attempts)
        self.assertEqual(self.admission.calls, calls)

    def test_a_read_failure_is_attempted_only_once_per_owner_tick(self):
        self.gh.fail.add("status")
        owner = self.owner(demand=self.driver(repeats=3))
        self.assert_admission_only(owner.tick())
        self.assertEqual(self.gh.attempts, {"status": 1, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.clock.slept, [])
        self.assert_admission_only(owner.tick())
        self.assertEqual(self.gh.attempts, {"status": 2, "comment_list": 1, "comment_write": 1})
        self.assertEqual(self.clock.slept, [])
        self.assertEqual(self.gate.trees, [])

    def test_failed_admission_reads_are_not_presented_as_holds(self):
        self.admission.failures["h101"] = ReadFailed("admission command unread")
        summary = self.owner().tick()
        self.assertEqual(summary["held"], [])
        self.assertEqual(summary["retry_later"], [101])
        self.assertEqual(self.gh.statuses, {})
        self.assertEqual(self.gh.comment_rows, [])
        self.assertEqual(self.gate.trees, [])

    def test_remembering_an_actual_gate_hold_does_not_publish_it_twice(self):
        self.admission.verdicts.clear()
        self.gate.bad.add(101)
        owner = self.owner()
        summary = owner.tick()
        self.assertEqual(summary["held"], [101])
        failures = [row for rows in self.gh.statuses.values() for row in rows if row["state"] == "failure"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(len([body for body in self.gh.written_bodies if "**SVRF: held**" in body]), 1)
        receipt = json.loads(Path(summary["receipt"]).read_text())
        self.assertEqual(len(receipt["gates"]), 1)
        self.assertEqual(receipt["holds"][0]["reason"], "GATE_RED")
        self.assertEqual(receipt["surface"]["status"], sum(map(len, self.gh.statuses.values())))
        self.assertEqual(receipt["surface"]["comment_write"], len(self.gh.written_bodies))
        attempts = dict(self.gh.attempts)
        self.assertEqual(owner.tick()["tick"], "IDLE")
        self.assertEqual(self.gh.attempts, attempts)

    def test_admission_output_uses_the_original_bounded_literal_renderer(self):
        self.failing[:] = ["check:\x00bad\n```\n<script>x</script>" + "x" * 400] + [f"row-{n}" for n in range(30)]
        summary = self.owner().tick()
        self.assert_admission_only(summary)
        self.assert_status()
        self.assertEqual(len(self.gh.comment_rows), 1)
        body = self.gh.comment_rows[0]["body"]
        self.assertEqual(body, pr_surface.render_comment({
            "number": 101, "phase": "HELD", "history": [], "failing": self.failing[:24],
            "reason_line": pr_surface.one_line(self.failing[0])}))
        self.assertNotIn("\x00", body)
        self.assertNotIn("row-29", body)
        self.assertIn("````", body)
        self.assertLessEqual(len(self.gh.statuses["h101"][0]["description"]), 140)
