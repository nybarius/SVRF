"""Render an asciinema v2 cast as a self-contained animated SVG (CSS keyframes, no script).

    python3 demo/cast_to_svg.py docs/demo.cast docs/img/demo.svg

Lines appear in the order the recording printed them. The recording itself runs in under
two seconds, so the animation is paced for reading (a command is typed, a section heading
pauses, table rows roll in) and then loops.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")

CHAR_W, LINE_H, FONT = 7.83, 19, 13
PAD_X, PAD_TOP, PAD_BOTTOM, BAR = 22, 50, 22, 34


def parse(text: str) -> tuple[dict, list[tuple[float, str]]]:
    """The cast header and every output line as (time the line was finished, plain text)."""
    rows = text.splitlines()
    header = json.loads(rows[0])
    lines: list[tuple[float, str]] = []
    current = ""
    last = 0.0
    for row in rows[1:]:
        if not row.strip():
            continue
        at, kind, data = json.loads(row)
        if kind != "o":
            continue
        last = float(at)
        data = ANSI.sub("", data).replace("\r\n", "\n")
        parts = data.split("\n")
        for part in parts[:-1]:
            current += part.split("\r")[-1] if "\r" in part else part
            lines.append((float(at), current))
            current = ""
        tail = parts[-1]
        current = tail.split("\r")[-1] if "\r" in tail else current + tail
    if current:
        lines.append((last, current))
    return header, lines


def _pace(lines: list[tuple[float, str]]) -> list[float]:
    """Display times: the command is typed, headings pause, everything else rolls in."""
    out, t = [], 0.0
    for index, (_, line) in enumerate(lines):
        if index == 0:
            t = 0.4
        elif line.startswith("=="):
            t += 1.0
        elif line.strip().startswith("tick"):
            t += 0.55
        elif not line.strip():
            t += 0.05
        else:
            t += 0.16
        out.append(round(t, 2))
    return out


def _kind(line: str) -> str:
    stripped = line.strip()
    if line.startswith("$ "):
        return "cmd"
    if line.startswith("=="):
        return "head"
    if re.match(r"#\d+ ", stripped) and ("merged" in line or "held" in line or "superseded" in line):
        return "held" if " held " in line else "row"
    if stripped.startswith("tick") or stripped.startswith("rounds:"):
        return "ok"
    return "out"


def render(text: str, hold: float = 5.0) -> str:
    header, lines = parse(text)
    times = _pace(lines)
    total = (times[-1] if times else 0) + hold
    cols = max([int(header.get("width", 80))] + [len(line) for _, line in lines])
    width = round(PAD_X * 2 + cols * CHAR_W)
    height = PAD_TOP + len(lines) * LINE_H + PAD_BOTTOM
    title = escape(str(header.get("title") or "terminal recording"))
    css = [
        f"text{{font-family:ui-monospace,'SF Mono','Cascadia Mono','JetBrains Mono',Menlo,Consolas,monospace;"
        f"font-size:{FONT}px;white-space:pre;fill:#d6d6d0}}",
        ".cmd{fill:#ffffff;font-weight:600}.prompt{fill:#6bb5ff}.head{fill:#6bb5ff;font-weight:600}"
        ".ok{fill:#7ddc7d}.held{fill:#f0a57c}.row{fill:#e6e6e0}.title{font-family:system-ui,sans-serif;"
        "font-size:12px;fill:#9a9a94}",
        ".l{opacity:0;animation-duration:%ss;animation-iteration-count:infinite;animation-timing-function:linear}"
        % round(total, 2),
        ".caret{animation:blink 1s steps(1) infinite}@keyframes blink{50%{opacity:0}}",
        "@media (prefers-reduced-motion:reduce){.l{animation:none;opacity:1}.caret{animation:none}}",
    ]
    body = []
    for index, ((_, line), t) in enumerate(zip(lines, times)):
        start = 100 * t / total
        shown = min(99.0, start + 0.4)
        end = 100 * (total - 0.4) / total
        css.append(f"@keyframes k{index}{{0%,{start:.2f}%{{opacity:0}}{shown:.2f}%,{end:.2f}%{{opacity:1}}"
                   f"100%{{opacity:0}}}}.n{index}{{animation-name:k{index}}}")
        y = PAD_TOP + (index + 1) * LINE_H - 5
        kind = _kind(line)
        if kind == "cmd":
            content = f'<tspan class="prompt">$</tspan> {escape(line[2:])}'
        else:
            content = escape(line)
        body.append(f'<text class="l n{index} {kind}" x="{PAD_X}" y="{y}" xml:space="preserve">{content}</text>')
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"'
        f' role="img" aria-label="{title}">',
        f"<title>{title}</title>",
        "<style>" + "\n".join(css) + "</style>",
        f'<rect width="{width}" height="{height}" rx="12" fill="#161615"/>',
        f'<rect width="{width}" height="{BAR}" rx="12" fill="#232321"/>'
        f'<rect y="{BAR - 12}" width="{width}" height="12" fill="#232321"/>',
        '<circle cx="22" cy="17" r="6" fill="#ec6a5e"/><circle cx="42" cy="17" r="6" fill="#f4bf4f"/>'
        '<circle cx="62" cy="17" r="6" fill="#61c554"/>',
        f'<text class="title" x="{width / 2:.0f}" y="21" text-anchor="middle">{title}</text>',
        *body,
        "</svg>",
        "",
    ])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    Path(argv[1]).write_text(render(Path(argv[0]).read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
