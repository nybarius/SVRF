"""A stand-in for GitHub backed by a local bare repository, for the demo and for tests.

It serves the same calls as `RealGitHub` (list, pull, merge, comment, close, retarget,
open) over a pull-request table kept in memory. Branch heads are read from the bare
repository and merges are real git merge commits made with plumbing, exactly the commit
GitHub's "Create a merge commit" button makes (its message aside).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import ReadFailed


class LocalHub:
    def __init__(self, origin: Path | str, base: str = "main", repo: str = "local/demo"):
        self.origin = Path(origin).resolve()
        self.base, self.repo = base, repo
        self.prs: dict[int, dict] = {}
        self.comments: list[tuple[int, str]] = []
        self.calls = {"graphql": 0, "rest": 0}
        self.next_number = 1
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "hub", "GIT_AUTHOR_EMAIL": "hub@localhost",
                    "GIT_COMMITTER_NAME": "hub", "GIT_COMMITTER_EMAIL": "hub@localhost"}

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        done = subprocess.run(["git", "-C", str(self.origin), *args], capture_output=True, text=True, env=self.env)
        if check and done.returncode != 0:
            raise ReadFailed(f"HUB_GIT_FAILED:{args[0]}:{done.stderr.strip()[:120]}")
        return done

    def _sha(self, ref: str) -> str | None:
        done = self._git("rev-parse", "--verify", "-q", f"refs/heads/{ref}", check=False)
        return done.stdout.strip() or None

    # ---- the author side

    def open_pr(self, head: str, base: str, title: str, body: str = "", *, draft: bool = False,
                labels=(), author: str = "svrf") -> int:
        self.calls["rest"] += 1
        if self._sha(head) is None:
            raise ReadFailed(f"NO_SUCH_BRANCH:{head}")
        number = self.next_number
        self.next_number += 1
        self.prs[number] = {"number": number, "title": title, "body": body, "head_ref": head, "base": base,
                            "draft": draft, "labels": list(labels), "state": "open", "merged_at": None,
                            "author": author}
        self._publish(number)
        return number

    def _publish(self, number: int) -> None:
        """GitHub's refs/pull/<n>/head, so a clone can fetch every pull request's head."""
        sha = self._sha(self.prs[number]["head_ref"])
        if sha:
            self._git("update-ref", f"refs/pull/{number}/head", sha)

    # ---- the API the train calls

    def rate_limit(self) -> dict:
        return {"graphql": {"remaining": 5000, "reset": 0}, "core": {"remaining": 5000, "reset": 0}}

    def snapshot(self) -> list[dict]:
        self.calls["graphql"] += 1
        rows = []
        for n, pr in sorted(self.prs.items()):
            self._settle(pr)
            if pr["state"] != "open":
                continue
            self._publish(n)
            rows.append({"number": n, "title": pr["title"], "body": pr["body"], "isDraft": pr["draft"],
                         "headRefName": pr["head_ref"], "headRefOid": self._sha(pr["head_ref"]),
                         "baseRefName": pr["base"], "labels": [{"name": x} for x in pr["labels"]],
                         "isCrossRepository": False})
        return rows

    def _settle(self, pr: dict) -> None:
        """Like GitHub, record an open pull request merged once its base contains its head."""
        if pr["state"] != "open":
            return
        base, head = self._sha(pr["base"]), self._sha(pr["head_ref"])
        if base and head and self._git("merge-base", "--is-ancestor", head, base, check=False).returncode == 0:
            pr["state"], pr["merged_at"] = "closed", "merged"

    def _mergeable(self, pr: dict) -> bool:
        base, head = self._sha(pr["base"]), self._sha(pr["head_ref"])
        return self._git("merge-tree", "--write-tree", base, head, check=False).returncode == 0

    def pull(self, number: int) -> dict:
        self.calls["rest"] += 1
        pr = self.prs[number]
        self._publish(number)
        return {"number": number, "head_sha": self._sha(pr["head_ref"]), "head_ref": pr["head_ref"],
                "mergeable": self._mergeable(pr) if pr["state"] == "open" else None,
                "state": pr["state"], "draft": pr["draft"]}

    def pulls_with_head(self, branch: str) -> list[dict]:
        self.calls["rest"] += 1
        return [{"number": n, "state": pr["state"], "merged_at": pr["merged_at"]}
                for n, pr in sorted(self.prs.items()) if pr["head_ref"] == branch]

    def retarget(self, number: int, base: str) -> None:
        self.calls["rest"] += 1
        self.prs[number]["base"] = base

    def ready(self, number: int) -> None:
        self.calls["graphql"] += 1
        self.prs[number]["draft"] = False

    def merge(self, number: int, sha: str) -> str:
        self.calls["rest"] += 1
        pr = self.prs[number]
        if pr["state"] != "open":
            raise ReadFailed("MERGE_REFUSED:NOT_OPEN")
        head = self._sha(pr["head_ref"])
        if head != sha:
            raise ReadFailed("MERGE_REFUSED:HEAD_MOVED")
        base = self._sha(pr["base"])
        done = self._git("merge-tree", "--write-tree", base, head, check=False)
        if done.returncode != 0:
            raise ReadFailed("MERGE_REFUSED:CONFLICT")
        tree = done.stdout.split("\n", 1)[0].strip()
        message = f"Merge pull request #{number} from {pr['head_ref']}\n\n{pr['title']}"
        merged = self._git("commit-tree", tree, "-p", base, "-p", head, "-m", message).stdout.strip()
        self._git("update-ref", f"refs/heads/{pr['base']}", merged, base)
        pr["state"], pr["merged_at"] = "closed", "merged"
        return merged

    def comment(self, number: int, body: str) -> None:
        self.calls["rest"] += 1
        self.comments.append((number, body))

    def close(self, number: int) -> None:
        self.calls["rest"] += 1
        self.prs[number]["state"] = "closed"
