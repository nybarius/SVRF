"""Keeping the GitHub token out of anything written to disk.

`svrf.toml` has no field for the token on purpose (see docs/GITHUB_SETUP.md): the `gh`
CLI and git's own credential helper read it straight from `GH_TOKEN` or `GITHUB_TOKEN`
in the environment, and SVRF itself never stores it. This module is the second line of
defence: subprocess output (a failed git or `gh` call's stderr, a gate's or the admission
command's captured output) can still echo an inherited environment variable back, so
every place that turns such output into a log file, a held reason or a receipt field
redacts it first.
"""

from __future__ import annotations

import os

SECRET_ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")
MASK = "***REDACTED***"
_MIN_LEN = 8  # shorter values are too likely to be "" or a placeholder; nothing to hide


def secret_values(env: dict | None = None) -> list[str]:
    """The distinct token values worth redacting, longest first so a value that is a
    prefix of another is not left partially unmasked."""
    source = env if env is not None else os.environ
    values = {str(source[name]) for name in SECRET_ENV_NAMES if source.get(name)}
    return sorted((v for v in values if len(v) >= _MIN_LEN), key=len, reverse=True)


def redact(text: str, env: dict | None = None) -> str:
    """`text` with every occurrence of a configured token value replaced by `MASK`."""
    if not text:
        return text
    for value in secret_values(env):
        text = text.replace(value, MASK)
    return text
