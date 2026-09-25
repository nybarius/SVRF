"""`svrf dashboard`: a static site built from round receipts.

    svrf dashboard --receipts <state_dir>/receipts --out site/

`summarize` reads the receipts into one plain summary (every number the page shows is
computed here, so it is tested here); `render` writes one self-contained `index.html`
(inline CSS and JS, the summary embedded as JSON, no network requests), which works opened
as a local file and served from GitHub Pages alike.
"""

from __future__ import annotations

import calendar
import json
import time
from pathlib import Path

from . import __version__

LANDED_STATES = ("LANDED",)


def _ts(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y%m%dT%H%M%SZ")))
    except ValueError:
        return None


def _hour(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:00Z", time.gmtime(ts))


def load_receipts(directory: Path) -> tuple[list[dict], int]:
    """Every readable receipt in `directory`, and how many `*.json` files could not be read."""
    receipts, skipped = [], 0
    for path in sorted(Path(directory).expanduser().glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped += 1
            continue
        if isinstance(value, dict) and value.get("started"):
            receipts.append(value)
        else:
            skipped += 1
    return receipts, skipped


def _ratio(a: float, b: float, digits: int = 2) -> float | None:
    return round(a / b, digits) if b else None


def _fresh_gates(receipt: dict) -> list[dict]:
    return [g for g in receipt.get("gates", []) if "reused" not in g]


def _round_row(r: dict) -> dict:
    started, finished = _ts(r.get("started")), _ts(r.get("finished"))
    merged = len(r.get("merges", []))
    gates = len(_fresh_gates(r))
    wall = int(finished - started) if started is not None and finished is not None else None
    families = r.get("families", [])
    return {"started": r.get("started"), "start": started, "finished": r.get("finished"), "wall": wall,
            "merged": merged, "gates": gates, "holds": len(r.get("holds", [])), "families": len(families),
            "bisected": any(f.get("status") == "BISECTED" for f in families),
            "gates_per_pr": _ratio(gates, merged, 3), "wall_per_pr": _ratio(wall or 0, merged, 1) if wall is not None else None}


def _tally(receipts: list[dict]) -> dict:
    out = {"verified": 0, "mismatched": 0, "unread": 0}
    for r in receipts:
        for m in r.get("merges", []):
            if m.get("observed_tree") is None:
                out["unread"] += 1
            elif m.get("observed_tree") == m.get("gated_tree") and m.get("identity") is not False:
                out["verified"] += 1
            else:
                out["mismatched"] += 1
    return out


def _throughput(receipts: list[dict]) -> list[dict]:
    times = [float(m["at"]) for r in receipts for m in r.get("merges", []) if m.get("at") is not None]
    starts = [t for t in (_ts(r.get("started")) for r in receipts) if t is not None]
    if not times and not starts:
        return []
    first = min(times + starts)
    last = max(times + starts)
    counts: dict[str, int] = {}
    for t in times:
        counts[_hour(t)] = counts.get(_hour(t), 0) + 1
    hour = first - first % 3600
    rows = []
    while hour <= last:
        rows.append({"hour": _hour(hour), "merged": counts.get(_hour(hour), 0)})
        hour += 3600
    return rows


def _family_status(family: dict, receipt: dict) -> str | None:
    """A family's status; a TREE_MISMATCH whose landed trees were never read (older
    receipt writers) is the unread case, which is retried and is not a mismatch."""
    status = family.get("status")
    if status == "TREE_MISMATCH":
        mine = [m for m in receipt.get("merges", []) if m.get("family") == family.get("id")]
        if mine and all(m.get("observed_tree") is None or m.get("observed_tree") == m.get("gated_tree")
                        for m in mine):
            return "LANDED_TREE_UNREAD"
    return status


def _trees(receipts: list[dict]) -> list[dict]:
    out = []
    for r in receipts:
        families = r.get("families", [])
        if not any(f.get("status") == "BISECTED" for f in families):
            continue
        gates = r.get("gates", [])
        held = {h.get("number") for h in r.get("holds", [])}
        nodes = {}
        for f in families:
            g = gates[f["gate"]] if isinstance(f.get("gate"), int) and f["gate"] < len(gates) else None
            nodes[f["id"]] = {"id": f["id"], "prs": list(f.get("prs", [])), "status": _family_status(f, r),
                              "green": bool(g and g.get("green")), "seconds": g.get("seconds") if g else None,
                              "reused": bool(g and "reused" in g),
                              "held": [n for n in f.get("prs", []) if n in held] if f.get("status") == "HELD" else [],
                              "children": []}
        roots = []
        for f in families:
            parent = nodes.get(f.get("parent"))
            (parent["children"] if parent else roots).append(nodes[f["id"]])
        roots = [n for n in roots if n["status"] == "BISECTED" or n["children"]]
        out.append({"round": r.get("started"), "roots": roots})
    return out


def _timeline(receipts: list[dict]) -> list[dict]:
    """One bar per gate run: when its batch could first have been gated (the round start;
    for a bisected half, when its parent's result came back; for a batch of a later
    replanning round, the last landing or gate of the rounds before), the gate itself, and
    the last merge of the batch."""
    bars = []
    for r in receipts:
        round_start = _ts(r.get("started"))
        gates = r.get("gates", [])
        round_of = {fid: i for i, x in enumerate(r.get("rounds", [])) for fid in x.get("families", [])}
        landed: dict[str, float] = {}
        for m in r.get("merges", []):
            if m.get("at") is not None:
                landed[m.get("family")] = max(landed.get(m.get("family"), 0.0), float(m["at"]))
        ended: dict[str, float] = {}
        done: list[tuple[int, float]] = []   # (round index, when a batch was finished)
        for f in r.get("families", []):
            g = gates[f["gate"]] if isinstance(f.get("gate"), int) and f["gate"] < len(gates) else None
            fid, parent = f.get("id"), f.get("parent")
            if parent:
                queued = ended.get(parent, round_start)
            else:
                k = round_of.get(fid, 0)
                earlier = [t for i, t in done if i < k]
                queued = max(earlier) if k and earlier else round_start
            if g is None or g.get("started") is None:
                continue
            if "reused" in g:
                # a tree already known red: concluded as soon as the batch existed
                ended[fid] = queued if queued is not None else float(g["started"])
                continue
            start = float(g["started"])
            end = start + float(g.get("seconds") or 0)
            ended[fid] = end
            done.append((_root_round(f, r, round_of), max(end, landed.get(fid) or 0.0)))
            bars.append({"round": r.get("started"), "family": fid, "prs": list(g.get("prs", [])),
                         "status": _family_status(f, r) or ("GREEN" if g.get("green") else "RED"),
                         "green": bool(g.get("green")), "queued": queued, "start": start, "end": end,
                         "landed": landed.get(fid)})
    return bars


def _root_round(family: dict, receipt: dict, round_of: dict) -> int:
    """The replanning round a bisected family belongs to: its root's."""
    by_id = {f["id"]: f for f in receipt.get("families", [])}
    seen = set()
    while family.get("parent") in by_id and family["id"] not in seen:
        seen.add(family["id"])
        family = by_id[family["parent"]]
    return round_of.get(family.get("id"), 0)


def _live(r: dict | None) -> dict | None:
    if r is None:
        return None
    running = r.get("finished") is None
    jobs = int((r.get("config") or {}).get("jobs") or 1)
    merged = {m.get("number") for m in r.get("merges", [])}
    held = {h.get("number"): h.get("reason") for h in r.get("holds", [])}
    retry = {u.get("number"): u.get("reason") for u in r.get("retry_later", [])}
    out = {str(k) for k in r.get("out", {})}
    pending = set(r.get("pending", []))
    latest: dict[int, dict] = {}
    for f in r.get("families", []):
        for n in f.get("prs", []):
            latest[n] = f
    planned = [f["id"] for f in r.get("families", []) if f.get("status") == "PLANNED"]
    gating = set(planned[:jobs]) if running else set()
    merged_family = {m.get("number"): m.get("family") for m in r.get("merges", [])}
    queue = []
    for position, n in enumerate(r.get("requested", []), start=1):
        family = latest.get(n)
        fid = merged_family.get(n) or (family["id"] if family else None)
        if n in merged:
            state = "LANDED"
        elif n in held:
            state = "HELD"
        elif str(n) in out:
            state = "OUT"
        elif n in retry:
            state = "RETRY"
        elif family is None:
            state = "PENDING" if n in pending or not running else "ADMITTED"
        elif family.get("status") == "PLANNED":
            state = "GATING" if family["id"] in gating else "QUEUED"
        elif family.get("status") == "GREEN":
            state = "LANDING"
        elif n in pending:
            state = "PENDING"
        else:
            state = family.get("status") or "QUEUED"
        queue.append({"position": position, "number": n, "family": fid, "state": state,
                      "reason": held.get(n) or retry.get(n)})
    return {"started": r.get("started"), "running": running, "jobs": jobs, "queue": queue}


def summarize(receipts: list[dict]) -> dict:
    receipts = sorted(receipts, key=lambda r: str(r.get("started") or ""))
    rounds = [_round_row(r) for r in receipts]
    merged = sum(x["merged"] for x in rounds)
    gates = sum(x["gates"] for x in rounds)
    wall = sum(x["wall"] for x in rounds if x["wall"] is not None)
    holds = [{"number": h.get("number"), "reason": h.get("reason"),
              "detail": next(iter(list(h.get("failing") or []) + list(h.get("paths") or [])), ""),
              "round": r.get("started")} for r in receipts for h in r.get("holds", [])]
    alerts = [{**a, "round": r.get("started")} for r in receipts for a in r.get("alerts", [])]
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": __version__,
        "totals": {"rounds": len(rounds), "merged": merged, "gates": gates, "holds": len(holds),
                   "gates_per_pr": _ratio(gates, merged), "wall_seconds": wall,
                   "wall_per_pr": _ratio(wall, merged, 1)},
        "rounds": rounds, "throughput": _throughput(receipts), "tally": _tally(receipts),
        "trees": _trees(receipts), "timeline": _timeline(receipts), "holds": holds, "alerts": alerts,
        "live": _live(receipts[-1] if receipts else None), "skipped": 0,
    }


def _embed(value: dict) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render(summary: dict, title: str = "SVRF merge train") -> str:
    page = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return page.replace("{{TITLE}}", safe_title).replace("{{DATA}}", _embed(summary))


def build(receipts: Path, out: Path, title: str = "SVRF merge train") -> Path:
    values, skipped = load_receipts(receipts)
    summary = summarize(values)
    summary["skipped"] = skipped
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    index = out / "index.html"
    tmp = index.with_suffix(".html.tmp")
    tmp.write_text(render(summary, title), encoding="utf-8")
    tmp.replace(index)
    return index
