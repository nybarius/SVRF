"""A command-bound failed admission reopens only when its consumed checker changes."""
import json
import tempfile
import unittest
from pathlib import Path

from fakes import Admission, DaemonGitHub, DaemonRepo, FakeGate
from test_daemon import daemon


class CommandAdmission(Admission):
    def __init__(self, command, verdicts=None):
        super().__init__(verdicts)
        self.command = command


class CheckerCommandReopening(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = DaemonRepo([31])
        self.gh = DaemonGitHub(self.repo)
        self.gate = FakeGate(self.repo)

    def owner(self, admission):
        return daemon(self.repo, self.gh, self.gate, admission, self.root)

    def first_failure(self):
        first = CommandAdmission("CHECKER=old original-admission", {
            "h31": {"verdict": "HELD", "residuals": ["check:original-failure"],
                    "consumed": [{"kind": "CODE", "id": "lane:31"}]}})
        self.owner(first).tick()
        held = json.loads((self.root / "state.json").read_text())["held"]["31"]
        self.assertEqual(held["failing"], ["check:original-failure"])
        self.assertEqual(first.calls, [("h31", self.repo.main)])
        return held

    def test_changed_command_reopens_same_head_and_base_after_restart(self):
        original = self.first_failure()
        successor = CommandAdmission("CHECKER=new original-admission")
        self.owner(successor).tick()
        self.assertEqual(len(successor.calls), 1,
                         "a changed consumed checker cannot inherit the old hold")
        self.assertEqual(self.gh.merged, [31])
        self.assertEqual(original["failing"], ["check:original-failure"])

    def test_unchanged_command_keeps_the_same_failed_read(self):
        original = self.first_failure()
        unchanged = CommandAdmission("CHECKER=old original-admission")
        self.owner(unchanged).tick()
        self.assertEqual(unchanged.calls, [])
        self.assertEqual(self.gh.merged, [])
        self.assertEqual(json.loads((self.root / "state.json").read_text())["held"]["31"], original)

    def test_changed_admission_command_does_not_reopen_an_original_gate_failure(self):
        self.gate = FakeGate(self.repo, bad={31})
        self.owner(CommandAdmission("CHECKER=old original-admission")).tick()
        original = json.loads((self.root / "state.json").read_text())["held"]["31"]
        self.assertEqual(original["reason"], "GATE_RED")
        successor = CommandAdmission("CHECKER=new original-admission")
        before = len(self.gate.trees)
        self.owner(successor).tick()
        self.assertEqual(successor.calls, [])
        self.assertEqual(len(self.gate.trees), before)
        self.assertEqual(self.gh.merged, [])


if __name__ == "__main__":
    unittest.main()
