#!/usr/bin/env python3
"""Record `python3 demo/run_demo.py` as an asciinema v2 `.cast` file, with real timing,
without needing asciinema installed.

    python3 demo/record_cast.py docs/demo.cast

It runs the demo under a pseudo-terminal (so it gets the same line-buffered output a real
terminal would see) and writes one asciinema "o" (output) event per chunk read, each
timestamped relative to the start. The result plays back with `asciinema play
docs/demo.cast` or on asciinema.org/docs' embeddable player, and is what
`docs/demo.cast` in this repository was produced with.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import struct
import sys
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLUMNS, ROWS = 100, 32


def record(command: list[str], cwd: Path) -> list[tuple[float, str]]:
    """Run `command` under a pty; return (relative_seconds, text) for each output chunk."""
    pid, master = pty.fork()
    if pid == 0:  # child
        os.chdir(cwd)
        env = {**os.environ, "TERM": "xterm-256color", "PYTHONUNBUFFERED": "1", "COLUMNS": str(COLUMNS),
               "LINES": str(ROWS)}
        os.execvpe(command[0], command, env)
        os._exit(127)  # pragma: no cover - only reached if exec fails
    # parent: set the pty's window size so the child's terminal-width-aware output (if any) matches
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))
    events: list[tuple[float, str]] = []
    started = time.monotonic()
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        events.append((time.monotonic() - started, chunk.decode("utf-8", errors="replace")))
    os.waitpid(pid, 0)
    return events


def write_cast(path: Path, events: list[tuple[float, str]], *, title: str) -> None:
    header = {"version": 2, "width": COLUMNS, "height": ROWS, "timestamp": int(time.time()),
              "title": title, "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"}}
    with open(path, "w", encoding="utf-8") as out:
        out.write(json.dumps(header) + "\n")
        for when, text in events:
            out.write(json.dumps([round(when, 6), "o", text]) + "\n")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: record_cast.py <output.cast>", file=sys.stderr)
        return 2
    out_path = Path(argv[0])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = "$ python3 demo/run_demo.py\r\n"
    events = [(0.0, prompt)]
    # the pty's line discipline already turns the child's "\n" into "\r\n" (ONLCR), so the
    # captured chunks need no further translation.
    started_events = record([sys.executable, "-u", str(ROOT / "demo" / "run_demo.py")], cwd=ROOT)
    offset = events[-1][0] + 0.3
    events += [(offset + when, text) for when, text in started_events]
    write_cast(out_path, events, title="SVRF demo: a braided train landing eight pull requests")
    print(f"wrote {out_path} ({len(events)} events, {events[-1][0]:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
