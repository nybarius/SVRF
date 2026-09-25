"""The optional history-order check (`history.order = "tests-first"`).

Each commit of a pull request (base..head) gets one disposition from the paths it
touches, classified by the configured globs as test, doc or code:

    TESTS      tests only (opens a demand: tests that the code does not satisfy yet)
    CODE       code, closing the open tests commit
    REFACTOR   code whose subject starts with a refactor prefix (no tests needed)
    DOCS       docs only
    MERGE      a two-parent merge whose tree is git's own merge of its parents, union
               paths resolved by union: it authors nothing
    MIXED      tests and code in one commit                      (refused)
    UNORDERED  code with no open tests commit before it           (refused)

A refused history is a matter of order, not content: the train can re-land the same
final tree as tests -> code -> docs (`RealGit.reland`) and open a pull request that
supersedes the original.
"""

from __future__ import annotations

from typing import Callable

from .globs import PathSet

REFUSED = {"MIXED", "UNORDERED"}


def path_kind(tests: PathSet, docs: PathSet) -> Callable[[str], str]:
    def kind(path: str) -> str:
        if tests(path):
            return "test"
        if docs(path):
            return "doc"
        return "code"
    return kind


def dispositions(git, base: str, head: str, kind: Callable[[str], str],
                 refactor_prefixes: tuple[str, ...] = ("refactor", "perf")) -> list[dict]:
    commits = git.out("rev-list", "--reverse", "--topo-order", f"{base}..{head}").split()
    out: list[dict] = []
    open_tests = False
    for sha in commits:
        message = git.out("log", "-1", "--format=%B", sha)
        subject = message.strip().splitlines()[0] if message.strip() else ""
        parents = git.parents(sha)
        row: dict = {"commit": sha, "subject": subject}
        if len(parents) == 2:
            step = git.union_step(parents[1], parents[0], "probe")
            if step.status == "CLEAN" and step.tree == git.tree(sha):
                row.update(disposition="MERGE", files=[])
                out.append(row)
                continue
            files = [f for f in git.out("diff-tree", "-r", "--cc", "--name-only", "--no-commit-id", sha).split("\n") if f]
        else:
            files = [f for f in git.out("diff-tree", "-r", "--root", "--name-only", "--no-commit-id", sha).split("\n") if f]
        row["files"] = files
        kinds = {kind(f) for f in files}
        if "test" in kinds and "code" in kinds:
            row["disposition"] = "MIXED"
        elif "test" in kinds:
            row["disposition"] = "TESTS"
            open_tests = True
        elif "code" in kinds:
            if subject.lower().startswith(tuple(p.lower() for p in refactor_prefixes)):
                row["disposition"] = "REFACTOR"
            elif open_tests:
                row["disposition"] = "CODE"
                open_tests = False
            else:
                row["disposition"] = "UNORDERED"
        else:
            row["disposition"] = "DOCS"
        out.append(row)
    return out


def verdict(git, base: str, head: str, kind: Callable[[str], str],
            refactor_prefixes: tuple[str, ...] = ("refactor", "perf")) -> str:
    """CLEAN, or REFUSED:<first refused disposition>."""
    for row in dispositions(git, base, head, kind, refactor_prefixes):
        if row["disposition"] in REFUSED:
            return f"REFUSED:{row['disposition']}"
    return "CLEAN"
