"""Path globs for configuration: `*` and `?` stay inside one directory, `**` spans any
number of directories, and a pattern with no `/` matches the file name at any depth
(the way `.gitignore` reads it)."""

from __future__ import annotations

import re
from typing import Iterable


def glob_regex(pattern: str) -> str:
    anchored = "/" in pattern.rstrip("/")
    body = pattern.lstrip("/")
    out, i = [], 0
    while i < len(body):
        if body.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif body.startswith("**", i):
            out.append(".*")
            i += 2
        elif body[i] == "*":
            out.append("[^/]*")
            i += 1
        elif body[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(body[i]))
            i += 1
    prefix = "^" if anchored else "^(?:.*/)?"
    return prefix + "".join(out) + "$"


class PathSet:
    """A set of paths given by globs; callable on a repository-relative path."""

    def __init__(self, patterns: Iterable[str] = ()):
        self.patterns = [p for p in patterns if p]
        self._regex = re.compile("|".join(f"(?:{glob_regex(p)})" for p in self.patterns)) if self.patterns else None

    def __call__(self, path: str) -> bool:
        return bool(self._regex and self._regex.match(path))

    def __bool__(self) -> bool:
        return bool(self.patterns)

    def __repr__(self) -> str:
        return f"PathSet({self.patterns!r})"
