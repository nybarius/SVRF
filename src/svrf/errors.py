"""Read failures.

A read that could not be made (a network error, a rate limit, a gate whose machine
fell over) is never a verdict about a pull request. It is retried later and never
turns into a hold.
"""

from __future__ import annotations

import re


class ReadFailed(Exception):
    """A read that could not be made. Never a conflict, never a hold: retry later."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RateLimited(ReadFailed):
    """GitHub refused the call for its rate limit; `reset` is when it said to come back."""

    def __init__(self, message: str, reset: float | None = None):
        first = (message.strip().splitlines() or [""])[0][:160]
        super().__init__(f"RATE_LIMITED:{first}")
        self.reset = reset


RATE_PATTERN = re.compile(r"rate limit|secondary rate|abuse detection|HTTP 429", re.IGNORECASE)


def classify_gh_failure(rc: int, stderr: str) -> None:
    """Raise the read failure a non-zero `gh` exit is: rate limited, or failed."""
    if RATE_PATTERN.search(stderr or ""):
        raise RateLimited(stderr)
    first = ((stderr or "").strip().splitlines() or [""])[0][:160]
    raise ReadFailed(f"GH_FAILED:{rc}:{first}")
