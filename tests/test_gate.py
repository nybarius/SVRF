"""The command gate on a real clone: slots, environment, setup lock, red, retry."""

from __future__ import annotations

import fcntl
import tempfile
import unittest
from pathlib import Path

import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from unittest.mock import patch

import test_admission_process as process_tests
import test_admission_cancellation as cancellation_tests

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


    @contextmanager
    def held_gate_descendant(self, *, leader_exits):
        ready, release, finished = (self.tmp / name for name in ("ready.json", "release", "finished.json"))
        os.mkfifo(release)
        release_fd = os.open(release, os.O_RDWR | os.O_NONBLOCK)
        slot = self.tmp / "wt" / "slot-0"
        log = self.tmp / "logs" / f"family-{self.commit[:12]}" / "00-gate.log"
        child_source = (
            "import json,os,pathlib,subprocess,sys\n"
            "first=pathlib.Path('a.txt').read_bytes()\n"
            "head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()\n"
            "sys.stdout.buffer.write(b'child before:'+first); sys.stdout.buffer.flush()\n"
            f"pathlib.Path({str(ready)!r}).write_text(json.dumps({{"
            "'parent':os.getppid(),'child':os.getpid(),'before':first.hex(),'head':head}))\n"
            "os.write(int(sys.argv[1]),b'x'); os.close(int(sys.argv[1]))\n"
            f"with open({str(release)!r},'rb',buffering=0) as wait:\n"
            " if wait.read(1)!=b'x': raise SystemExit('release unavailable')\n"
            "last=pathlib.Path('a.txt').read_bytes()\n"
            "head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()\n"
            "sys.stdout.buffer.write(b'child after:'+last); sys.stdout.buffer.flush()\n"
            f"pathlib.Path({str(finished)!r}).write_text(json.dumps({{'after':last.hex(),'head':head}}))\n")
        source = (
            "import os,subprocess,sys\n"
            "reader,writer=os.pipe()\n"
            f"child=subprocess.Popen([sys.executable,'-c',{child_source!r},str(writer)],"
            "start_new_session=True,pass_fds=(writer,))\n"
            "os.close(writer)\n"
            "if os.read(reader,1)!=b'x': raise SystemExit('child readiness unavailable')\n"
            "os.close(reader)\n"
            "print('original leader',flush=True)\n"
            + ("raise SystemExit(23)\n" if leader_exits else "raise SystemExit(child.wait())\n"))
        gate = self.gate([process_tests.python_command(source)],
                         **({} if leader_exits else {"timeout_minutes": 0.01}))
        owner = {}
        original_popen = subprocess.Popen

        def observe(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            output = kwargs.get("stdout")
            name = getattr(output, "name", None)
            cwd = kwargs.get("cwd")
            if cwd is not None and Path(cwd) == slot and isinstance(name, (str, os.PathLike)) and Path(name) == log:
                owner["process"] = proc
            return proc

        try:
            with ThreadPoolExecutor(max_workers=1) as workers, patch("svrf.gate.subprocess.Popen", side_effect=observe):
                future = workers.submit(gate.run, self.base, self.commit, "family")
                try:
                    pids = process_tests.until(lambda: process_tests.read_json(ready))
                    proc = process_tests.until(lambda: owner.get("process"))
                    yield {"future": future, "process": proc, "pids": pids, "slot": slot, "log": log,
                           "finished": finished, "release": lambda: os.write(release_fd, b"x")}
                finally:
                    os.write(release_fd, b"x")
                    try:
                        try:
                            future.result(timeout=10)
                        except FutureTimeout:
                            proc = owner.get("process")
                            if proc is not None:
                                process_tests.AdmissionProcess.stop(proc)
                            future.result(timeout=10)
                    finally:
                        pids = process_tests.read_json(ready)
                        if pids is not None:
                            process_tests.until(lambda: not cancellation_tests.live(pids["child"]))
        finally:
            os.close(release_fd)

    def test_a_departed_leader_keeps_its_reading_descendant_and_slot(self):
        other = SlotPool(self.tmp / "wt", 1)
        acquired = None
        try:
            with self.held_gate_descendant(leader_exits=True) as held:
                pids, proc = held["pids"], held["process"]
                original = (self.clone / "a.txt").read_bytes()
                self.assertEqual(bytes.fromhex(pids["before"]), original)
                self.assertEqual(pids["head"], self.commit)
                process_tests.until(lambda: process_tests.gone(pids["parent"]))
                self.assertTrue(cancellation_tests.live(pids["child"]))
                self.assertIsNone(proc.poll(), "the command owner returned while its child still reads the slot")
                process_tests.until(lambda: process_tests.parent_of(pids["child"]) == proc.pid)
                acquired = other.acquire(block=False)
                self.assertIsNone(acquired, "another pool acquired a slot still read by the original child")
                held["release"]()
                result = held["future"].result(timeout=10)
                self.assertFalse(result["green"], result)
                self.assertIsNone(result["read_failure"], result)
                self.assertEqual(result["steps"][0]["rc"], 23)
                returned = process_tests.read_json(held["finished"])
                self.assertEqual(returned, {"after": original.hex(), "head": self.commit})
                log = held["log"].read_bytes()
                self.assertIn(b"child before:" + original, log)
                self.assertIn(b"original leader\n", log)
                self.assertIn(b"child after:" + original, log)
                self.assertTrue(all(process_tests.gone(pid) for pid in (pids["parent"], pids["child"])))
                acquired = other.acquire(block=False)
                self.assertEqual(acquired, held["slot"])
        finally:
            if acquired is not None:
                other.release(acquired)

    def test_a_gate_timeout_reaps_its_reading_descendant_before_releasing_the_slot(self):
        other = SlotPool(self.tmp / "wt", 1)
        acquired = None
        try:
            with self.held_gate_descendant(leader_exits=False) as held:
                pids = held["pids"]
                original = (self.clone / "a.txt").read_bytes()
                self.assertEqual(bytes.fromhex(pids["before"]), original)
                self.assertEqual(pids["head"], self.commit)
                result = held["future"].result(timeout=10)
                self.assertFalse(result["green"], result)
                self.assertTrue(result["read_failure"].startswith("GATE_TIMEOUT:"), result)
                self.assertIsNone(result["steps"][0]["rc"])
                self.assertIn(b"child before:" + original, held["log"].read_bytes())
                self.assertTrue(all(process_tests.gone(pid) for pid in (pids["parent"], pids["child"])),
                                "a timed-out gate released a live member of its original process family")
                acquired = other.acquire(block=False)
                self.assertEqual(acquired, held["slot"])
        finally:
            if acquired is not None:
                other.release(acquired)

    def test_process_custody_refusal_is_unobserved_without_reclassifying_an_ordinary_exit(self):
        marker = "INTAKE_OUTPUT_UNOBSERVED:ADMISSION_PROCESS_ARGUMENT"
        unavailable = "exec " + shlex.join([sys.executable, "-I", str(process_tests.HELPER)])
        for command, reason in ((unavailable, "GATE_INFRA:" + marker), ("echo 'FAIL ordinary'; exit 126", None)):
            with self.subTest(command=command):
                result = self.gate([command]).run(self.base, self.commit)
                self.assertFalse(result["green"], result)
                self.assertEqual(result["steps"][0]["rc"], 126)
                self.assertEqual(result["read_failure"], reason, result)
                self.assertEqual(result["failing"], [marker if reason else "FAIL ordinary"])



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
