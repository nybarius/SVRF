"""The command gate on a real clone: slots, environment, setup lock, red, retry."""

from __future__ import annotations

import fcntl
import tempfile
import unittest
from pathlib import Path

from fakes import git

from svrf.gate import CommandGate
from svrf.locks import SlotPool


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clone = self.tmp / "clone"
        self.clone.mkdir()
        git(self.clone, "init", "-q", "-b", "main")
        (self.clone / "a.txt").write_text("a\n")
        (self.clone / ".gitignore").write_text(".cache/\n")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-qm", "base")
        self.base = git(self.clone, "rev-parse", "HEAD")
        (self.clone / "b.txt").write_text("b\n")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-qm", "b")
        self.commit = git(self.clone, "rev-parse", "HEAD")

    def gate(self, commands, **kw):
        return CommandGate(self.clone, self.tmp / "wt", 1, commands, logs=self.tmp / "logs", **kw)

    def test_a_green_gate_sees_its_commit_and_changed_files(self):
        result = self.gate(['test "$(git rev-parse HEAD)" = "$SVRF_COMMIT"',
                            'grep -qx b.txt "$SVRF_CHANGED_FILES"', 'test -f b.txt',
                            'test "$SVRF_LABEL" = F1']).run(self.base, self.commit, "F1")
        self.assertTrue(result["green"], result)
        self.assertEqual(result["tree"], git(self.clone, "rev-parse", f"{self.commit}^{{tree}}"))
        self.assertEqual([s["rc"] for s in result["steps"]], [0, 0, 0, 0])

    def test_a_red_gate_stops_at_the_first_failure_with_its_failing_lines(self):
        result = self.gate(["echo 'FAIL: test_b (b.txt)'; exit 1", "echo never"]).run(self.base, self.commit, "F1")
        self.assertFalse(result["green"])
        self.assertIsNone(result["read_failure"])
        self.assertEqual(result["failing"], ["FAIL: test_b (b.txt)"])
        self.assertEqual(len(result["steps"]), 1)

    def test_a_gate_that_could_not_run_is_a_read_failure(self):
        result = self.gate(["echo 'fatal: Could not resolve host: example.com'; exit 1"]).run(self.base, self.commit)
        self.assertFalse(result["green"])
        self.assertTrue(result["read_failure"].startswith("GATE_INFRA:"))
        slow = self.gate(["sleep 5"], timeout_minutes=0.01).run(self.base, self.commit)
        self.assertTrue(slow["read_failure"].startswith("GATE_TIMEOUT:"))

    def test_setup_runs_first_under_the_shared_lock(self):
        probe = (f"python3 -c \"import fcntl,sys; h=open('{self.tmp / 'wt' / 'setup.lock'}','a+');\n"
                 "try:\n  fcntl.flock(h, fcntl.LOCK_EX|fcntl.LOCK_NB); sys.exit(1)\n"
                 "except BlockingIOError:\n  sys.exit(0)\"")
        result = self.gate(["true"], setup=[probe]).run(self.base, self.commit)
        self.assertTrue(result["green"], result)
        self.assertEqual([s["phase"] for s in result["steps"]], ["setup", "gate"])

    def test_untracked_build_caches_survive_between_gates(self):
        gate = self.gate(["mkdir -p .cache && touch .cache/x"])
        gate.run(self.base, self.commit)
        result = self.gate(["test -f .cache/x"]).run(self.base, self.commit)
        self.assertTrue(result["green"], result)


class Slots(unittest.TestCase):
    def test_gate_slots_are_exclusive_across_pools(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = SlotPool(Path(tmp), 2), SlotPool(Path(tmp), 2)
            a = one.acquire()
            b = two.acquire()
            self.assertNotEqual(a, b)
            self.assertIsNone(two.acquire(block=False))
            one.release(a)
            self.assertEqual(two.acquire(block=False), a)
            two.release(a)
            two.release(b)

    def test_a_slot_lock_is_a_real_flock(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = SlotPool(Path(tmp), 1)
            slot = pool.acquire()
            with open(slot.with_name(slot.name + ".lock"), "a+") as handle:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pool.release(slot)


if __name__ == "__main__":
    unittest.main()
