"""The `svrf` command line.

    svrf run --once          one round: discover, admit, gate, land (the timer's mode)
    svrf watch               a round every train.interval_seconds
    svrf plan --dry-run      one round that gates and reports but pushes, merges and remembers nothing
    svrf land --prs 12,15    one batched run over the named pull requests
    svrf status              held pull requests and the last round
    svrf forget 12,15        drop pull requests from the held memory
    svrf config              print the parsed configuration

Every command reads `--config` (default: $SVRF_CONFIG, else ./svrf.toml).
Exit codes: 0 ok, 1 a landed tree did not match its gated tree, 2 bad configuration,
3 another train owns the lock.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, replay as replayer
from .app import build, ensure_clone
from .config import ConfigError, load
from .errors import ReadFailed
from .git import RealGit
from .github import RealGitHub
from .locks import owner_lock
from .train import Train


def _numbers(text: str) -> list[int]:
    return [int(n) for n in text.replace(" ", ",").split(",") if n.strip()]


def _print(value) -> None:
    print(json.dumps(value, indent=1, sort_keys=True, default=str), flush=True)


def status(config) -> dict:
    state_dir = Path(config.state_dir)
    out: dict = {"repo": config.repo, "base": config.base, "state_dir": str(state_dir)}
    try:
        state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
        out["last_tick"] = state.get("last_tick")
        out["held"] = [{"number": int(n), "reason": e.get("reason"), "head": (e.get("head") or "")[:12],
                        "failing": e.get("failing", [])[:3]} for n, e in sorted(state.get("held", {}).items(),
                                                                               key=lambda kv: int(kv[0]))]
    except (OSError, ValueError):
        out["last_tick"], out["held"] = None, []
    receipts = sorted(Path(config.receipts).glob("train-*.json"))
    if receipts:
        last = json.loads(receipts[-1].read_text(encoding="utf-8"))
        out["last_receipt"] = {"path": str(receipts[-1]), "started": last.get("started"),
                               "finished": last.get("finished"),
                               "merged": [m["number"] for m in last.get("merges", []) if m.get("identity")],
                               "gates": len([g for g in last.get("gates", []) if "reused" not in g]),
                               "held": [h["number"] for h in last.get("holds", [])],
                               "alerts": [a["alert"] for a in last.get("alerts", [])]}
    return out


def main(argv: list[str] | None = None, *, github=None) -> int:
    ap = argparse.ArgumentParser(prog="svrf", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"svrf {__version__}")
    ap.add_argument("--config", default=os.environ.get("SVRF_CONFIG") or "svrf.toml")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="one round")
    run.add_argument("--once", action="store_true", help="one round, then exit (the default)")
    run.add_argument("--dry-run", action="store_true")
    watch = sub.add_parser("watch", help="a round every interval")
    watch.add_argument("--interval", type=float, default=None)
    watch.add_argument("--dry-run", action="store_true")
    plan = sub.add_parser("plan", help="one round without effects")
    plan.add_argument("--dry-run", action="store_true", default=True, help="always on for plan")
    land = sub.add_parser("land", help="one batched run over named pull requests")
    land.add_argument("--prs", required=True)
    land.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="held pull requests and the last round")
    forget = sub.add_parser("forget", help="drop pull requests from the held memory")
    forget.add_argument("numbers")
    sub.add_parser("config", help="print the parsed configuration")
    replay_cmd = sub.add_parser("replay", help="admission and planning against an already-merged snapshot")
    replay_cmd.add_argument("--merged", required=True, help="already-merged pull request numbers, e.g. 101,102")
    replay_cmd.add_argument("--base", default=None,
                            help="the shared round base (a sha); default: every listed pull request's own "
                                 "reconstructed base, which must then be identical")
    replay_cmd.add_argument("--gate", action="store_true", help="also run the configured gate on each family")
    args = ap.parse_args(argv)

    try:
        config = load(args.config)
    except (OSError, ConfigError, ValueError) as error:
        print(f"svrf: configuration {args.config}: {error}", file=sys.stderr)
        return 2

    if args.command == "config":
        value = dataclasses.asdict(config)
        _print(value)
        return 0
    if args.command == "status":
        _print(status(config))
        return 0
    if args.command == "replay":
        try:
            ensure_clone(config)
        except ReadFailed as failure:
            _print({"tick": "RETRY", "reason": failure.reason})
            return 0
        hub = github or RealGitHub(config.repo)
        git = RealGit(config.clone, base=config.base)
        numbers = _numbers(args.merged)
        found, problems = replayer.reconstruct(git, hub.merge_commit, numbers)
        report = {"requested": numbers, "problems": problems}
        if found:
            try:
                report.update(replayer.run(config, found, base=args.base, gate=args.gate))
            except replayer.ReplayError as error:
                report["error"] = str(error)
                _print(report)
                return 2
        _print(report)
        return 0

    dry_run = bool(getattr(args, "dry_run", False)) or args.command == "plan"
    try:
        ensure_clone(config)
    except ReadFailed as failure:
        _print({"tick": "RETRY", "reason": failure.reason})
        return 0
    daemon = build(config, dry_run=dry_run)

    if args.command == "forget":
        _print(daemon.forget(_numbers(args.numbers)))
        return 0
    if args.command == "land":
        with owner_lock(config.lock) as owned:
            if not owned:
                _print({"tick": "LOCKED", "lock": str(config.lock)})
                return 3
            train = Train(daemon.git, daemon.gh, daemon.gate, receipts=config.receipts, dry_run=dry_run,
                          is_union=config.union_paths, **daemon.train_options)
            receipt = train.run(_numbers(args.prs))
        _print({"receipt": str(train.path), "merged": [m["number"] for m in receipt["merges"] if m["identity"]],
                "held": [h["number"] for h in receipt["holds"]], "out": sorted(int(n) for n in receipt["out"]),
                "retry_later": [u["number"] for u in receipt["retry_later"]], "alerts": receipt["alerts"],
                "gates": len(receipt["gates"])})
        return 1 if any(a["alert"] == "TREE_MISMATCH" for a in receipt["alerts"]) else 0
    interval = getattr(args, "interval", None) or config.train.interval_seconds
    while True:
        summary = daemon.tick()
        _print(summary)
        if summary.get("tick") == "LOCKED" and args.command != "watch":
            return 3
        if args.command != "watch":
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
