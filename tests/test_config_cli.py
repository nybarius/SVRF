"""Configuration loading, the command line, and the packaging files."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fakes import ROOT

from svrf import cli
from svrf.config import ConfigError, from_dict, load
from svrf.locks import owner_lock

MINIMAL = {"repo": "example/project", "gate": {"commands": ["make test"]}}


class Config(unittest.TestCase):
    def test_minimal_config_has_safe_defaults(self):
        config = from_dict(MINIMAL)
        self.assertEqual((config.base, config.hold_label, config.history.order), ("main", "train:hold", "off"))
        self.assertEqual((config.train.family_size, config.train.jobs), (8, 2))
        self.assertTrue(config.repair)
        self.assertFalse(config.union_paths("package-lock.json"))
        self.assertEqual((config.ui.pr_comments, config.ui.status_checks, config.ui.dashboard_url),
                         (True, True, ""))

    def test_the_ui_section_can_turn_either_surface_off_and_set_a_dashboard_url(self):
        config = from_dict({**MINIMAL, "ui": {"pr_comments": False, "status_checks": False,
                                              "dashboard_url": "https://dash.example/x"}})
        self.assertEqual((config.ui.pr_comments, config.ui.status_checks, config.ui.dashboard_url),
                         (False, False, "https://dash.example/x"))

    def test_an_unknown_ui_key_is_refused(self):
        with self.assertRaises(ConfigError):
            from_dict({**MINIMAL, "ui": {"comments": True}})

    def test_the_admission_timeout_is_configured_in_minutes_and_defaults_to_ten(self):
        """An admission command that reads a large head (the intake runs every suite the head
        touches) needs longer than the class default under a loaded host; the operator sets it
        in [admission] like the gate's timeout, in minutes."""
        self.assertEqual(from_dict(MINIMAL).admission_timeout_minutes, 10)
        c = from_dict({**MINIMAL, "admission": {"command": "true", "timeout_minutes": 45}})
        self.assertEqual(c.admission_timeout_minutes, 45)
        with self.assertRaises(ConfigError):
            from_dict({**MINIMAL, "admission": {"command": "true", "timeout_minutes": "soon"}})

    def test_reland_is_wired_from_the_admission_command_even_with_the_built_in_check_off(self):
        # history.order == "off" (the default) used to force reland_enabled False no
        # matter what history.reland said, on the assumption that a reland-eligible
        # residual could only ever come from the built-in tests-first check. An
        # admission.command can report the same class of refusal too (reland_class
        # reads its `reland:REFUSED:<class>` lines), so the built-in check being off
        # must not silence it.
        from svrf.app import build
        on = from_dict({**MINIMAL, "admission": {"command": "true"}, "history": {"reland": True, "order": "off"}})
        self.assertTrue(build(on, github=object()).reland_enabled)
        off = from_dict({**MINIMAL, "history": {"reland": False, "order": "off"}})
        self.assertFalse(build(off, github=object()).reland_enabled)

    def test_unknown_keys_are_refused(self):
        for bad in ({**MINIMAL, "familysize": 3}, {**MINIMAL, "train": {"family": 3}},
                    {**MINIMAL, "repair": {"union": ["x"]}}, {**MINIMAL, "labels": {"skip": "x"}}):
            with self.assertRaises(ConfigError):
                from_dict(bad)

    def test_required_fields(self):
        with self.assertRaises(ConfigError):
            from_dict({"gate": {"commands": ["x"]}})
        with self.assertRaises(ConfigError):
            from_dict({"repo": "example/project"})
        with self.assertRaises(ConfigError):
            from_dict({**MINIMAL, "history": {"order": "sometimes"}})

    def test_the_example_config_and_every_preset_load(self):
        paths = [ROOT / "svrf.example.toml", *sorted((ROOT / "presets").glob("*.toml"))]
        self.assertGreaterEqual(len(paths), 2)
        for path in paths:
            config = load(path)
            self.assertTrue(config.gate.commands, path)

    def test_relative_paths_resolve_against_the_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "svrf.toml"
            path.write_text('repo = "a/b"\nclone = "clone"\nstate_dir = "state"\n[gate]\ncommands = ["true"]\n'
                            '[repair]\nunion_merge = ["CHANGELOG.md", "**/requirements*.txt"]\n')
            config = load(path)
            self.assertEqual(config.clone, Path(tmp).resolve() / "clone")
            self.assertEqual(config.lock, Path(tmp).resolve() / "state" / "svrf.lock")
            self.assertTrue(config.union_paths("svc/requirements-dev.txt"))


class CommandLine(unittest.TestCase):
    def config_file(self, tmp: Path) -> Path:
        path = tmp / "svrf.toml"
        path.write_text(f'repo = "a/b"\nclone = "{tmp / "clone"}"\nstate_dir = "{tmp / "state"}"\n'
                        '[gate]\ncommands = ["true"]\n')
        (tmp / "clone").mkdir()
        subprocess.run(["git", "-C", str(tmp / "clone"), "init", "-q"], check=True)
        return path

    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_a_second_owner_exits_3_and_reads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = self.config_file(tmp)
            with owner_lock(tmp / "state" / "svrf.lock"):
                code, out = self.run_cli("--config", str(path), "run", "--once")
                self.assertEqual(code, 3)
                self.assertEqual(json.loads(out)["tick"], "LOCKED")
                code, out = self.run_cli("--config", str(path), "land", "--prs", "1")
                self.assertEqual(code, 3)

    def test_status_reads_the_state_without_a_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = self.config_file(tmp)
            (tmp / "state").mkdir()
            (tmp / "state" / "state.json").write_text(json.dumps({
                "schema_version": "svrf.state/1", "last_tick": {"tick": "RAN"},
                "held": {"7": {"reason": "GATE_RED", "head": "abc", "failing": ["FAIL x"]}}}))
            code, out = self.run_cli("--config", str(path), "status")
            self.assertEqual(code, 0)
            value = json.loads(out)
            self.assertEqual(value["held"], [{"number": 7, "reason": "GATE_RED", "head": "abc", "failing": ["FAIL x"]}])

    def test_the_replay_subcommand_reports_admission_and_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            origin = tmp / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
            seed = tmp / "seed"
            seed.mkdir()
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                  "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

            def git(*args):
                subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True, text=True, env=env)

            def out(*args):
                return subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True, text=True,
                                      env=env).stdout.strip()

            git("init", "-q", "-b", "main")
            (seed / "a.txt").write_text("0\n")
            git("add", "-A")
            git("commit", "-qm", "base")
            git("remote", "add", "origin", str(origin))
            git("push", "-q", "origin", "main")
            git("checkout", "-q", "-b", "feature")
            (seed / "b.txt").write_text("1\n")
            git("add", "-A")
            git("commit", "-qm", "feat: b")
            git("checkout", "-q", "main")
            git("merge", "-q", "--no-ff", "--no-edit", "feature")
            merged = out("rev-parse", "HEAD")
            git("push", "-q", "origin", "main")

            clone = tmp / "clone"
            subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
            path = tmp / "svrf.toml"
            path.write_text(f'repo = "a/b"\nclone = "{clone}"\nstate_dir = "{tmp / "state"}"\n'
                            '[gate]\ncommands = ["true"]\n')

            class FakeHub:
                def merge_commit(self, number):
                    return merged if number == 55 else None

            out_json = io.StringIO()
            with redirect_stdout(out_json):
                code = cli.main(["--config", str(path), "replay", "--merged", "55"], github=FakeHub())
            self.assertEqual(code, 0)
            report = json.loads(out_json.getvalue())
            self.assertEqual(report["admission"]["55"]["decision"], "ADMIT")
            self.assertEqual([f["prs"] for f in report["families"]], [[55]])

    def test_a_bad_config_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "svrf.toml"
            path.write_text('repo = "a/b"\n')
            import contextlib

            with contextlib.redirect_stderr(io.StringIO()):
                code, _ = self.run_cli("--config", str(path), "status")
            self.assertEqual(code, 2)

    def test_the_module_entry_point_prints_help(self):
        done = subprocess.run(["python3", "-m", "svrf", "--help"], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.assertEqual(done.returncode, 0)
        for word in ("run", "watch", "plan", "status", "land"):
            self.assertIn(word, done.stdout)


    def test_worktree_lock_keeps_the_original_registration_during_bare_and_linked_adds(self):
        import sys
        from svrf import locks

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.config_file(root)
            seed = root / "clone"
            original = b"the original committed source\n"
            (seed / "source.txt").write_bytes(original)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                   "PYTHONPATH": str(ROOT / "src")}
            subprocess.run(["git", "-C", str(seed), "add", "source.txt"], check=True, env=env)
            subprocess.run(["git", "-C", str(seed), "commit", "-qm", "base"], check=True, env=env)
            head = subprocess.check_output(["git", "-C", str(seed), "rev-parse", "HEAD"]).strip()
            bare, linked = root / "common.git \r\n", root / "linked"
            subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)
            subprocess.run(["git", "-C", str(bare), "worktree", "add", "-q", "--detach",
                            str(linked), head.decode()], check=True)
            before = locks._OWN_FDS.copy()
            with locks.worktree_lock(bare):
                descriptor, = locks._OWN_FDS - before
                physical = os.fstat(descriptor)
                path = os.readlink(f"/proc/self/fd/{descriptor}")
            command = (
                "import fcntl,json,os,subprocess,sys\n"
                "with open(sys.argv[1], 'a+') as observed:\n"
                " physical=os.fstat(observed.fileno())\n"
                " try: fcntl.flock(observed,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
                " except BlockingIOError: held=True\n"
                " else:\n"
                "  held=False\n"
                "  fcntl.flock(observed,fcntl.LOCK_UN)\n"
                " print(json.dumps({'held':held,'identity':[physical.st_dev,physical.st_ino]}),flush=True)\n"
                " done=subprocess.run(['git','worktree','add','-q','-f','--detach',sys.argv[2],sys.argv[3]])\n"
                " raise SystemExit(done.returncode)\n")
            for owner in (bare, linked):
                with self.subTest(owner=owner):
                    checker = root / ("checker " + owner.name)
                    done = subprocess.run(
                        [sys.executable, "-m", "svrf", "--config", str(root / "absent.toml"),
                         "worktree-lock", "--root", str(owner), "--", sys.executable, "-c",
                         command, path, str(checker), head.decode()],
                        cwd=owner, env=env, capture_output=True, text=True)
                    self.assertEqual(done.returncode, 0, (done.stdout, done.stderr))
                    received = json.loads(done.stdout)
                    self.assertTrue(received["held"], received)
                    self.assertEqual(received["identity"], [physical.st_dev, physical.st_ino])
                    self.assertEqual(subprocess.check_output(
                        ["git", "-C", str(checker), "rev-parse", "HEAD"]).strip(), head)
                    self.assertEqual((checker / "source.txt").read_bytes(), original)
                    self.assertEqual(subprocess.check_output(
                        ["git", "-C", str(linked), "rev-parse", "HEAD"]).strip(), head)
                    self.assertEqual((linked / "source.txt").read_bytes(), original)


    def test_worktree_lock_keeps_descendants_until_return_or_termination(self):
        self._check_command_descendants("worktree-lock")

    def test_exec_keeps_descendants_until_return_or_termination_without_git_or_config(self):
        self._check_command_descendants("exec")

    def _check_command_descendants(self, operation):
        import fcntl
        import sys
        import test_admission_process as process_tests
        from svrf import locks

        for terminate in (False, True):
            with self.subTest(terminate=terminate), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                clone = root / "clone"
                prefix = [sys.executable, "-m", "svrf", "--config", str(root / "absent.toml"), operation]
                if operation == "worktree-lock":
                    self.config_file(root)
                    prefix.extend(["--root", str(clone)])
                else:
                    clone.mkdir()
                    git = subprocess.run(["git", "-C", str(clone), "rev-parse", "--git-dir"],
                                         capture_output=True)
                    self.assertNotEqual(git.returncode, 0, (git.stdout, git.stderr))
                self.assertFalse((root / "absent.toml").exists())
                original = b"the source retained by the original child\n"
                source = clone / "source.txt"
                source.write_bytes(original)
                if operation == "worktree-lock":
                    before = locks._OWN_FDS.copy()
                    with locks.worktree_lock(clone):
                        descriptor, = locks._OWN_FDS - before
                        physical = os.fstat(descriptor)
                        path = os.readlink(f"/proc/self/fd/{descriptor}")
                ready, release, finished = (root / name for name in ("ready", "release", "finished"))
                os.mkfifo(release)
                release_fd = os.open(release, os.O_RDWR | os.O_NONBLOCK)
                child = (
                    "import json,os,pathlib,signal,sys\n"
                    "signal.signal(signal.SIGINT,signal.SIG_IGN)\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    f"source=pathlib.Path({str(source)!r})\n"
                    "first=source.read_bytes()\n"
                    f"pathlib.Path({str(ready)!r}).write_text(json.dumps({{"
                    "'parent':os.getppid(),'child':os.getpid(),'source':first.hex()}))\n"
                    "os.write(int(sys.argv[1]),b'x'); os.close(int(sys.argv[1]))\n"
                    f"with open({str(release)!r},'rb',buffering=0) as stream:\n"
                    " if stream.read(1)!=b'x': raise SystemExit('release unavailable')\n"
                    "last=source.read_bytes()\n"
                    f"pathlib.Path({str(finished)!r}).write_bytes(last)\n"
                    "sys.stdout.buffer.write(last); sys.stdout.buffer.flush()\n")
                command = (
                    "import os,subprocess,sys\n"
                    "reader,writer=os.pipe()\n"
                    f"child=subprocess.Popen([sys.executable,'-c',{child!r},str(writer)],"
                    "start_new_session=True,pass_fds=(writer,))\n"
                    "os.close(writer)\n"
                    "if os.read(reader,1)!=b'x': raise SystemExit('child readiness unavailable')\n"
                    "os.close(reader)\n"
                    "print('original leader',flush=True)\n"
                    "raise SystemExit(23)\n")
                proc = subprocess.Popen(
                    [*prefix, "--", sys.executable, "-c", command],
                    cwd=clone, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    observed = process_tests.until(lambda: process_tests.read_json(ready) or proc.poll() is not None)
                    if not isinstance(observed, dict):
                        stdout, stderr = proc.communicate(timeout=10)
                        self.fail(f"the original CLI returned before child receipt: {proc.returncode}, "
                                  f"{stdout!r}, {stderr!r}")
                    process_tests.until(lambda: process_tests.parent_of(observed["child"]) == proc.pid
                                        and process_tests.gone(observed["parent"]))
                    self.assertEqual(bytes.fromhex(observed["source"]), original)
                    self.assertIsNone(proc.poll())
                    if operation == "worktree-lock":
                        with open(path, "a+") as held:
                            current = os.fstat(held.fileno())
                            self.assertEqual((current.st_dev, current.st_ino), (physical.st_dev, physical.st_ino))
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if terminate:
                        proc.terminate()
                    else:
                        os.write(release_fd, b"x")
                    stdout, stderr = proc.communicate(timeout=10)
                    self.assertEqual(proc.returncode, 23, (stdout, stderr))
                    self.assertEqual(stderr, b"")
                    self.assertEqual(stdout, b"original leader\n" + (b"" if terminate else original))
                    if terminate:
                        self.assertFalse(finished.exists())
                    else:
                        self.assertEqual(finished.read_bytes(), original)
                    self.assertTrue(all(process_tests.gone(observed[name]) for name in ("parent", "child")))
                    if operation == "worktree-lock":
                        with open(path, "a+") as released:
                            fcntl.flock(released, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.write(release_fd, b"x")
                    try:
                        process_tests.AdmissionProcess.stop(proc)
                    finally:
                        os.close(release_fd)

    def test_worktree_lock_preserves_literal_argv_status_and_unavailable_root(self):
        self._check_command_argv("worktree-lock")

    def test_exec_preserves_literal_argv_and_status_without_git_or_config(self):
        self._check_command_argv("exec")

    def _check_command_argv(self, operation):
        import signal
        import sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clone, bindir = root / "clone", root / "bin"
            prefix = [sys.executable, "-m", "svrf", "--config", str(root / "absent.toml"), operation]
            if operation == "worktree-lock":
                self.config_file(root)
                prefix.extend(["--root", str(clone)])
            else:
                clone.mkdir()
                git = subprocess.run(["git", "-C", str(clone), "rev-parse", "--git-dir"],
                                     capture_output=True)
                self.assertNotEqual(git.returncode, 0, (git.stdout, git.stderr))
            self.assertFalse((root / "absent.toml").exists())
            prefix.append("--")
            bindir.mkdir()
            original = b"original stdin\x00and stderr\n"
            arguments = ["", "two words", "line\nbreak", "'\";$()"]
            program = (
                f"#!{sys.executable}\n"
                "import json,os,sys\n"
                "value=sys.stdin.buffer.read()\n"
                "print(json.dumps({'argv':sys.argv[2:],'cwd':os.getcwd(),"
                "'environment':os.environ['SVRF_ORIGINAL_VALUE'],'stdin':value.hex()}),flush=True)\n"
                "sys.stderr.buffer.write(value); sys.stderr.buffer.flush()\n"
                "raise SystemExit(int(sys.argv[1]))\n")
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
                   "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                   "SVRF_ORIGINAL_VALUE": "original environment"}
            for name, status in (("if", 0), ("NAME=value", 17)):
                with self.subTest(command=name):
                    executable = bindir / name
                    executable.write_text(program)
                    executable.chmod(0o755)
                    done = subprocess.run([*prefix, name, str(status), *arguments], cwd=clone, env=env,
                                          input=original, capture_output=True)
                    self.assertEqual(done.returncode, status, (done.stdout, done.stderr))
                    self.assertEqual(json.loads(done.stdout), {
                        "argv": arguments, "cwd": str(clone), "environment": env["SVRF_ORIGINAL_VALUE"],
                        "stdin": original.hex()})
                    self.assertEqual(done.stderr, original)
            signaled = subprocess.run(
                [*prefix, sys.executable, "-c", "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"],
                cwd=clone, env=env, capture_output=True)
            self.assertEqual(signaled.returncode, -signal.SIGTERM, (signaled.stdout, signaled.stderr))
            self.assertEqual((signaled.stdout, signaled.stderr), (b"", b""))
            if operation == "worktree-lock":
                sentinel = root / "retained"
                sentinel.write_bytes(original)
                unavailable = subprocess.run(
                    [sys.executable, "-m", "svrf", "worktree-lock", "--root", str(root), "--",
                     sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).unlink()", str(sentinel)],
                    cwd=clone, env=env, capture_output=True)
                self.assertEqual(unavailable.returncode, 126, (unavailable.stdout, unavailable.stderr))
                self.assertTrue(unavailable.stderr.startswith(b"svrf: worktree-lock:"), unavailable.stderr)
                self.assertEqual(unavailable.stdout, b"")
                self.assertEqual(sentinel.read_bytes(), original)


class Packaging(unittest.TestCase):
    def test_the_systemd_service_runs_one_round_with_explicit_paths(self):
        service = (ROOT / "systemd" / "svrf.service").read_text(encoding="utf-8")
        self.assertIn("Type=oneshot", service)
        exec_line = next(line for line in service.splitlines() if line.startswith("ExecStart="))
        self.assertIn("run --once", exec_line)
        self.assertIn("--config", exec_line)
        self.assertNotIn("WorkingDirectory", service)
        timer = (ROOT / "systemd" / "svrf.timer").read_text(encoding="utf-8")
        self.assertIn("OnUnitInactiveSec=", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_the_install_script_enables_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bindir = home / "bin"
            bindir.mkdir()
            log = home / "systemctl.log"
            (bindir / "systemctl").write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n")
            (bindir / "systemctl").chmod(0o755)
            env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                   "PATH": f"{bindir}:{os.environ['PATH']}"}
            script = ROOT / "systemd" / "install.sh"
            subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True, cwd=tmp)
            units = home / ".config" / "systemd" / "user"
            self.assertTrue((units / "svrf.service").is_file())
            self.assertTrue((units / "svrf.timer").is_file())
            self.assertNotIn("enable", log.read_text())
            subprocess.run(["bash", str(script), "--enable"], env=env, check=True, capture_output=True, cwd=tmp)
            self.assertIn("enable --now svrf.timer", log.read_text())

    def test_the_container_files_exist_and_name_the_cli(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("gh", dockerfile)
        self.assertIn("svrf", dockerfile)
        compose = (ROOT / "docker-compose.example.yml").read_text(encoding="utf-8")
        self.assertIn("GH_TOKEN", compose)

    def test_the_license_is_polyform_shield_with_commercial_terms(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("PolyForm Shield License 1.0.0", license_text)
        self.assertIn("Required Notice: Copyright 2026 Stephen Schweizer", license_text)
        self.assertIn('license = "LicenseRef-PolyForm-Shield-1.0.0"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("Required Notice:", (ROOT / "NOTICE").read_text(encoding="utf-8"))
        self.assertTrue((ROOT / "COMMERCIAL.md").is_file())


if __name__ == "__main__":
    unittest.main()
