#!/usr/bin/env python3
"""SVRF demo: a fake agent swarm opens pull requests against a toy project, and the train
lands them.

Everything runs locally: a bare git repository plays the GitHub remote, `LocalHub` plays
the GitHub API (pull requests, merges, comments), and the gate is the toy project's own
unit tests run in a worktree slot. The train code is the same code that runs against
GitHub.

    python3 demo/run_demo.py            # summary table
    python3 demo/run_demo.py --verbose  # plus every round's JSON summary
    python3 demo/run_demo.py --keep     # keep the temporary directory to look around

The swarm opens eight pull requests:

    1, 2, 8   ordinary features (tests first, then code), each adding a CHANGELOG line
    3, 4      two agents changing the same setting: they conflict
    5         a feature whose own test fails
    6         a feature committed code-first (out of order)
    7         stacked on top of pull request 2
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from svrf.app import build  # noqa: E402
from svrf.config import from_dict  # noqa: E402
from svrf.localhub import LocalHub  # noqa: E402

IDENT = {"GIT_AUTHOR_NAME": "agent", "GIT_AUTHOR_EMAIL": "agent@localhost",
         "GIT_COMMITTER_NAME": "agent", "GIT_COMMITTER_EMAIL": "agent@localhost"}

CALC = '''"""A toy calculator."""


def add(a, b):
    return a + b
'''

TEST_CALC = '''import unittest

from toy import calc


class Add(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calc.add(2, 3), 5)
'''


def git(cwd: Path, *args: str) -> str:
    import os

    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          env={**os.environ, **IDENT})
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


class Agent:
    """One member of the fake swarm, working in its own clone."""

    def __init__(self, root: Path, origin: Path, name: str):
        self.dir = root / "agents" / name
        self.name = name
        subprocess.run(["git", "-C", str(root), "clone", "-q", str(origin), str(self.dir)], check=True,
                       capture_output=True)

    def branch(self, name: str, start: str = "origin/main") -> str:
        git(self.dir, "fetch", "-q", "origin")
        git(self.dir, "checkout", "-q", "-B", name, start)
        return name

    def write(self, path: str, text: str, append: bool = False) -> None:
        target = self.dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if append:
            text = target.read_text() + text
        target.write_text(text)

    def commit(self, message: str) -> None:
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", message)

    def push(self, branch: str) -> None:
        git(self.dir, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")


def module(name: str, body: str, imports: str = "") -> str:
    return f'''"""{name}, added by an agent."""
{imports}

def {name}(a, b):
    return {body}
'''


def test_for(name: str, call: str, expected: str) -> str:
    return (f"import unittest\n\nfrom toy.{name} import {name}\n\n\n"
            f"class {name.title()}(unittest.TestCase):\n"
            f"    def test_{name}(self):\n        self.assertEqual({call}, {expected})\n")


def feature(agent: Agent, hub: LocalHub, name: str, body: str, call: str, expected: str, *,
            order: str = "tests-first", base_branch: str = "main", start: str = "origin/main",
            imports: str = "") -> int:
    branch = agent.branch(f"{agent.name}/{name}", start)
    steps = [("tests/test_" + name + ".py", test_for(name, call, expected), f"test: {name}"),
             ("toy/" + name + ".py", module(name, body, imports), f"feat: {name}")]
    if order != "tests-first":
        steps.reverse()
    for path, text, message in steps:
        agent.write(path, text)
        agent.commit(message)
    agent.write("CHANGELOG.md", f"- {name}\n", append=True)
    agent.commit(f"docs: changelog for {name}")
    agent.push(branch)
    return hub.open_pr(branch, base_branch, f"Add {name}", f"Opened by {agent.name}.", author=agent.name)


def setting(agent: Agent, hub: LocalHub, value: str) -> int:
    branch = agent.branch(f"{agent.name}/mode-{value}")
    agent.write("tests/test_settings.py", "import unittest\n\nfrom toy import settings\n\n\n"
                "class Mode(unittest.TestCase):\n    def test_mode(self):\n"
                f"        self.assertEqual(settings.MODE, {value!r})\n")
    agent.commit(f"test: mode {value}")
    agent.write("toy/settings.py", f"MODE = {value!r}\n")
    agent.commit(f"feat: mode {value}")
    agent.push(branch)
    return hub.open_pr(branch, "main", f"Set mode to {value}", f"Opened by {agent.name}.", author=agent.name)


def scenario(root: Path) -> tuple[Path, LocalHub, dict[int, str]]:
    """The toy project on a bare origin, and eight pull requests from six agents."""
    origin = root / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = root / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "toy").mkdir()
    (seed / "toy" / "__init__.py").write_text("")
    (seed / "toy" / "calc.py").write_text(CALC)
    (seed / "toy" / "settings.py").write_text("MODE = 'normal'\n")
    (seed / "tests").mkdir()
    (seed / "tests" / "__init__.py").write_text("")
    (seed / "tests" / "test_calc.py").write_text(TEST_CALC)
    (seed / "CHANGELOG.md").write_text("# Changelog\n")
    (seed / ".gitignore").write_text("__pycache__/\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "toy project")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")

    hub = LocalHub(origin)
    agents = {name: Agent(root, origin, name) for name in ("ada", "bo", "cy", "di", "ed", "fay")}
    story: dict[int, str] = {}
    n = feature(agents["ada"], hub, "subtract", "a - b", "subtract(5, 3)", "2")
    story[n] = "ordinary feature"
    n = feature(agents["bo"], hub, "multiply", "a * b", "multiply(4, 3)", "12")
    story[n] = "ordinary feature (parent of a stacked PR)"
    n = setting(agents["cy"], hub, "safe")
    story[n] = "changes MODE"
    n = setting(agents["di"], hub, "turbo")
    story[n] = "changes MODE too: conflicts"
    n = feature(agents["ed"], hub, "divide", "a * b", "divide(6, 3)", "2")
    story[n] = "its own test fails"
    n = feature(agents["fay"], hub, "power", "a ** b", "power(2, 3)", "8", order="code-first")
    story[n] = "code committed before its test"
    parent = hub.prs[2]["head_ref"]
    n = feature(agents["bo"], hub, "square", "multiply(a, a)", "square(3, 0)", "9",
                base_branch=parent, start=f"origin/{parent}", imports="\nfrom toy.multiply import multiply\n")
    story[n] = f"stacked on #2 ({parent})"
    n = feature(agents["ada"], hub, "negate", "-a", "negate(4, 0)", "-4")
    story[n] = "ordinary feature"
    return origin, hub, story


def configure(root: Path, origin: Path):
    clone = root / "train-clone"
    subprocess.run(["git", "-C", str(root), "clone", "-q", str(origin), str(clone)], check=True,
                   capture_output=True)
    return from_dict({
        "repo": "demo/toy", "base": "main", "clone": str(clone), "state_dir": str(root / "state"),
        "gate": {"commands": [f"{sys.executable} -m unittest discover -s tests -q"], "timeout_minutes": 5},
        "train": {"family_size": 8, "jobs": 2, "max_rounds": 3, "rate_floor": 0, "comment": True},
        "repair": {"union_merge": ["CHANGELOG.md"]},
        "history": {"order": "tests-first", "reland": True, "tests": ["tests/**"], "docs": ["*.md"]},
    })


def outcome(hub: LocalHub, state: dict, n: int) -> tuple[str, str]:
    pr = hub.prs[n]
    held = state.get("held", {}).get(str(n))
    relanded = state.get("relanded", {}).get(str(n))
    if pr["merged_at"]:
        return "merged", ""
    superseded = [body for m, body in hub.comments if m == n and body.startswith("Superseded by #")]
    if relanded or superseded:
        new = relanded["new_number"] if relanded else superseded[0].split("#")[1].split()[0]
        return "superseded", f"re-landed in order as #{new}"
    if held:
        detail = held["reason"]
        if held.get("failing"):
            detail += ": " + held["failing"][0][:60]
        elif held.get("paths"):
            detail += ": " + ", ".join(held["paths"])
        return "held", detail
    return pr["state"], ""


def run(root: Path, *, verbose: bool = False, max_ticks: int = 8) -> dict:
    origin, hub, story = scenario(root)
    config = configure(root, origin)
    daemon = build(config, github=hub)
    daemon.train_options["poll_seconds"] = 0
    ticks, started = [], time.monotonic()
    first_round: dict[int, int] = {}
    for tick in range(1, max_ticks + 1):
        summary = daemon.tick()
        ticks.append(summary)
        for n in summary.get("merged", []):
            first_round.setdefault(n, tick)
        if verbose:
            print(json.dumps({k: v for k, v in summary.items() if v not in ([], {}, None)}, indent=1, sort_keys=True))
        if summary["tick"] == "IDLE":
            break
    wall = time.monotonic() - started
    state = json.loads((config.state_dir / "state.json").read_text())
    for m, body in hub.comments:
        if body.startswith("Superseded by #"):
            story[int(body.split("#")[1].split()[0])] = f"opened by the train for #{m}"
    rows = []
    for n in sorted(hub.prs):
        result, detail = outcome(hub, state, n)
        if result == "merged" and n in first_round:
            detail = f"round {first_round[n]}"
        rows.append({"number": n, "author": hub.prs[n]["author"], "title": hub.prs[n]["title"],
                     "story": story.get(n, ""), "result": result, "detail": detail})
    receipts = [json.loads(p.read_text()) for p in sorted(config.receipts.glob("train-*.json"))]
    gates = sum(len([g for g in r["gates"] if "reused" not in g]) for r in receipts)
    merges = [m for r in receipts for m in r["merges"]]
    return {"rows": rows, "rounds": len(ticks), "gates": gates, "merges": len(merges),
            "identity": all(m["identity"] for m in merges), "wall_seconds": round(wall, 1),
            "repaired": sorted({r["number"] for t in ticks for r in t.get("repaired", [])}),
            "retargeted": sorted({n for t in ticks for n in t.get("retargeted", [])}),
            "out": sorted({n for t in ticks for n in t.get("out", [])}),
            "receipts": str(config.receipts)}


def table(result: dict) -> str:
    rows = result["rows"]
    headers = ("PR", "agent", "title", "what the agent did", "result", "detail")
    cells = [(f"#{r['number']}", r["author"], r["title"], r["story"], r["result"], r["detail"]) for r in rows]
    widths = [max(len(h), *(len(c[i]) for c in cells)) for i, h in enumerate(headers)]
    line = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths)).rstrip()  # noqa: E731
    out = [line(headers), line(["-" * w for w in widths])] + [line(c) for c in cells]
    out.append("")
    out.append(f"rounds: {result['rounds']}   gates run: {result['gates']}   merges: {result['merges']}   "
               f"landed tree == gated tree for every merge: {result['identity']}   wall: {result['wall_seconds']} s")
    if result["repaired"]:
        out.append(f"repaired by union merge (CHANGELOG.md): {', '.join('#' + str(n) for n in result['repaired'])}")
    if result["retargeted"]:
        out.append(f"retargeted to main after the parent merged: {', '.join('#' + str(n) for n in result['retargeted'])}")
    if result["out"]:
        out.append(f"left out of a round for a pairwise conflict: {', '.join('#' + str(n) for n in result['out'])}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    root = Path(tempfile.mkdtemp(prefix="svrf-demo-"))
    try:
        result = run(root, verbose=args.verbose)
        print(table(result))
        if args.keep:
            print(f"\nkept: {root} (receipts in {result['receipts']})")
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
