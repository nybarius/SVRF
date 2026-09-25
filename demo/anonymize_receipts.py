"""Turn real train receipts into shareable sample receipts.

    python3 demo/anonymize_receipts.py SRC_DIR OUT_DIR

Only numbers and timings survive: pull-request numbers are renumbered from 101 in first-seen
order, every commit and tree sha is replaced by a stable stand-in (so a landed tree still
equals its gated tree), titles and branch names become placeholders, failing lines become
`FAILED case-N`, and every other string (paths, log locations, gate output) is dropped.
Fields are copied by an allow list, so a field this script does not know is never copied.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# reason codes of older receipt writers, spelled the way `svrf` spells them now
RENAMED = {"ALREADY_CARRIED": "ALREADY_MERGED"}


class Anonymizer:
    def __init__(self) -> None:
        self.numbers: dict[int, int] = {}
        self.cases: dict[str, str] = {}

    def number(self, n) -> int | None:
        if n is None:
            return None
        n = int(n)
        if n not in self.numbers:
            self.numbers[n] = 101 + len(self.numbers)
        return self.numbers[n]

    @staticmethod
    def sha(value):
        if isinstance(value, str) and SHA.match(value):
            return hashlib.sha1(b"svrf-sample:" + value.encode()).hexdigest()
        return None

    def case(self, line: str) -> str:
        if line not in self.cases:
            self.cases[line] = f"FAILED case-{len(self.cases) + 1}"
        return self.cases[line]

    @staticmethod
    def reason(text) -> str | None:
        """The leading upper-case codes of a reason (`LANDED_TREE_UNREAD:GIT_FAILED:...`)."""
        if text is None:
            return None
        codes = []
        for part in str(text).split(":"):
            if not CODE.match(part):
                break
            codes.append(RENAMED.get(part, part))
        return ":".join(codes) or "UNREAD"

    def receipt(self, r: dict) -> dict:
        n, sha = self.number, self.sha
        prs = sorted(int(k) for k in r.get("prs", {}))
        for k in list(r.get("requested", [])) + prs:
            n(k)
        out = {
            "schema_version": "svrf.receipt/1",
            "started": r.get("started"), "finished": r.get("finished"), "stopped": bool(r.get("stopped")),
            "config": {k: r.get("config", {}).get(k) for k in ("jobs", "family_size", "dry_run", "rate_floor",
                                                                "max_rounds", "memory")},
            "requested": [n(k) for k in r.get("requested", [])],
            "prs": {str(n(k)): {"number": n(k), "head_sha": sha(v.get("head_sha")), "head_ref": f"agent/pr-{n(k)}",
                                "draft": bool(v.get("draft")), "title": f"Change {n(k)}"}
                    for k, v in sorted(r.get("prs", {}).items(), key=lambda kv: int(kv[0]))},
            "pairs": None, "out": {}, "api_calls": dict(r.get("api_calls") or {}),
            "rounds": [{"base": sha(x.get("base")), "queue": [n(k) for k in x.get("queue", [])],
                        "families": list(x.get("families", []))} for x in r.get("rounds", [])],
            "families": [], "gates": [], "merges": [], "holds": [], "retry_later": [], "pending": [],
            "alerts": [], "rate_waits": [{"reason": self.reason(w.get("reason")), "at": w.get("at"),
                                          "until": w.get("until")} for w in r.get("rate_waits", [])],
        }
        pairs = r.get("pairs")
        if isinstance(pairs, dict):
            out["pairs"] = {"read": pairs.get("read", 0),
                            "conflicts": [{"a": n(c.get("a")), "b": n(c.get("b")), "paths": []}
                                          for c in pairs.get("conflicts", []) if isinstance(c, dict)],
                            "unreadable": []}
        out["out"] = {str(n(k)): {"reason": "CONFLICT"} for k in (r.get("out") or {})}
        for f in r.get("families", []):
            row = {"id": f.get("id"), "parent": f.get("parent"), "prs": [n(k) for k in f.get("prs", [])],
                   "base": sha(f.get("base")), "commit": sha(f.get("commit")), "tree": sha(f.get("tree")),
                   "status": f.get("status"), "gate": f.get("gate"),
                   "steps": [{"number": n(s.get("number")), "commit": sha(s.get("commit")), "tree": sha(s.get("tree"))}
                             for s in f.get("steps", [])]}
            if f.get("landed"):
                row["landed"] = sha(f.get("landed"))
            out["families"].append(row)
        for g in r.get("gates", []):
            row = {"family": g.get("family"), "prs": [n(k) for k in g.get("prs", [])], "base": sha(g.get("base")),
                   "commit": sha(g.get("commit")), "tree": sha(g.get("tree")), "started": g.get("started"),
                   "seconds": g.get("seconds"), "green": bool(g.get("green")),
                   "failing": [self.case(x) for x in g.get("failing") or []][:12]}
            if "reused" in g:
                row["reused"] = g["reused"]
            failure = g.get("read_failure") or g.get("unobserved")
            if failure:
                row["read_failure"] = self.reason(failure)
            if g.get("slot"):
                row["slot"] = "slot-" + str(g["slot"]).rsplit("-", 1)[-1]
            out["gates"].append(row)
        for m in r.get("merges", []):
            out["merges"].append({"number": n(m.get("number")), "family": m.get("family"), "head": sha(m.get("head")),
                                  "merge": sha(m.get("merge")), "parents": [sha(p) for p in m.get("parents", [])],
                                  "gated_tree": sha(m.get("gated_tree")), "observed_tree": sha(m.get("observed_tree")),
                                  "identity": m.get("identity"), "at": m.get("at")})
        for h in r.get("holds", []):
            out["holds"].append({"number": n(h.get("number")), "reason": self.reason(h.get("reason")),
                                 "paths": [f"path-{i + 1}" for i, _ in enumerate(h.get("paths") or [])],
                                 "failing": [self.case(x) for x in h.get("failing") or []]})
        for u in list(r.get("retry_later", [])) + list(r.get("unobserved", [])):
            out["retry_later"].append({"number": n(u.get("number")),
                                       "reason": self.reason(u.get("reason") or u.get("read_failure"))})
        out["pending"] = [n(k) for k in r.get("pending", [])]
        for a in r.get("alerts", []):
            row = {"alert": self.reason(a.get("alert"))}
            for key in ("family", "number", "before", "expected", "observed", "planned", "prepared", "merge",
                        "snapshot"):
                if key in a:
                    value = a[key]
                    row[key] = (n(value) if key in ("number", "before") else
                                value if key == "family" else sha(value))
            out["alerts"].append(row)
        return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(argv[0]), Path(argv[1])
    dst.mkdir(parents=True, exist_ok=True)
    anonymizer = Anonymizer()
    for index, path in enumerate(sorted(src.glob("*.json"))):
        receipt = anonymizer.receipt(json.loads(path.read_text(encoding="utf-8")))
        name = f"train-{receipt['started']}-{index:04d}.json"
        (dst / name).write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
