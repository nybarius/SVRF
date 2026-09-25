"""The admission check: the read that decides whether a pull request enters the train.

It returns a verdict dict:

    {"verdict": "MERGEABLE" | "HELD" | "LANDED", "residuals": [...], "changed": [...]}

Residual lines name why a head is held:

    merge:CONFLICT:<path>       git cannot merge it onto the base branch
    history:REFUSED:<class>     the history-order check refused it (if enabled)
    check:<line>                the configured admission command failed

A read that cannot be made raises `ReadFailed`; the train retries it next round and
never holds the pull request for it.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable

from . import history
from .errors import ReadFailed

UNAVAILABLE_EXITS = (126, 127)


class Admission:
    def __init__(self, git, *, order: str = "off", kind: Callable[[str], str] | None = None,
                 refactor_prefixes: tuple[str, ...] = ("refactor", "perf"), command: str = "",
                 timeout: float = 600):
        self.git, self.order, self.kind = git, order, kind
        self.refactor_prefixes, self.command, self.timeout = refactor_prefixes, command, timeout

    def __call__(self, head: str, base: str) -> dict:
        if self.git.is_ancestor(head, base):
            return {"verdict": "LANDED", "residuals": [], "changed": []}
        residuals: list[str] = []
        merge = self.git.merge_preview(base, head)
        if merge["status"] == "FAILED":
            raise ReadFailed(merge.get("reason") or "MERGE_PREVIEW_FAILED")
        residuals += [f"merge:CONFLICT:{p}" for p in merge["conflicts"]]
        changed = self.git.changed_paths(base, head)
        if self.order == "tests-first" and self.kind is not None:
            result = history.verdict(self.git, base, head, self.kind, self.refactor_prefixes)
            if result != "CLEAN":
                residuals.append(f"history:{result}")
        if self.command:
            residuals += self._command(head, base)
        return {"verdict": "HELD" if residuals else "MERGEABLE", "residuals": residuals, "changed": changed}

    def _command(self, head: str, base: str) -> list[str]:
        env = {**os.environ, "SVRF_HEAD": head, "SVRF_BASE": base, "SVRF_CLONE": str(self.git.root)}
        try:
            done = subprocess.run(["bash", "-c", self.command], cwd=str(self.git.root), env=env,
                                  capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise ReadFailed("ADMISSION_COMMAND_TIMEOUT")
        if done.returncode in UNAVAILABLE_EXITS:
            raise ReadFailed(f"ADMISSION_COMMAND_UNAVAILABLE:{done.returncode}")
        if done.returncode == 0:
            return []
        lines = [line.strip() for line in (done.stdout + done.stderr).splitlines() if line.strip()]
        return [f"check:{line[:200]}" for line in lines[-5:]] or [f"check:exit={done.returncode}"]
