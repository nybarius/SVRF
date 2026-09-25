# Benchmark

Measured on a 17,000-declaration Lean 4 monorepo fed by a swarm of coding agents opening
pull requests, on a self-hosted runner, on 2026-09-25. All numbers below are taken from
the run receipts of that day; nothing here is a synthetic or simulated benchmark.

## Before: one pull request per gate, hand-run

- 5.8 merged pull requests per hour, over a 27.7-hour window: 162 pull requests merged.
- About 2.5-3.5 minutes of wall time per pull request (one gate run, one pull request,
  started by hand).

## After: SVRF

- 16.3 merged pull requests per hour, over a 2.3-hour window. This run was arrival-bound:
  the queue of ready pull requests repeatedly ran empty, so the train spent part of that
  window waiting for new pull requests rather than gating a backlog. The rate is a lower
  bound on what the same setup does against a continuous backlog, not a ceiling.
- Across 17 live rounds: 39 pull requests merged using 31 gate runs, i.e. 0.79 gates per
  merged pull request, bisection included. A family that gates green in one run charges
  one gate for every pull request in it; the 0.79 figure already carries the cost of the
  rounds that had to bisect a red family into smaller ones and gate the pieces again.
- About 47 seconds of wall time per merged pull request, averaged over the same 17 rounds.
- Best batch: 13 pull requests landed from 2 gate runs in 4 minutes 46 seconds.
- 0 landed-tree mismatches (`checkLanding_iff` / `tree-identity` in
  [proofs/README.md](../proofs/README.md) holding in practice, not only in the model). One
  early alert during development looked like a mismatch but was an unread tree: the merge
  commit had not yet been fetched into the train's clone when it was compared. That has
  since been fixed so an unreadable tree is retried on the next round, never reported as a
  mismatch.

## Reproducing this with the demo

```sh
python3 demo/run_demo.py
```

The demo builds a bare git repository, has a fake agent swarm open eight pull requests
against it (two that conflict with each other, one that fails its own test, one committed
with its code ahead of its tests, one stacked on another pull request that has not merged
yet), and runs the real train code — the same `svrf.train.Train` used in production —
against a local stand-in for the GitHub API instead of a real repository. It prints a
summary table of what got admitted, families, gates, and what landed or was held, so you
can see the scheduling and landing behaviour described in the README without a GitHub
token, a runner, or network access. It does not reproduce the timings above: those came
from a real 17,000-declaration repository and real gate commands, not the demo's toy tree.

## Caveats

- One repository, one day. These are the only production numbers collected so far; they
  are not an average over many repositories, gate shapes, or pull-request arrival
  patterns.
- The "after" window was arrival-bound: the train was frequently waiting for pull requests
  rather than gating continuously, so 16.3 merges/hour reflects that day's arrival rate as
  much as the train's own throughput. A backlog-bound run (a large queue of ready pull
  requests) would measure a different, and likely higher, ceiling.
- The gate command, its runtime, and the shape of the changes (a Lean monorepo with many
  small, mostly non-conflicting pull requests from coding agents) all affect these numbers.
  A slower gate, or a workload with more genuine conflicts, will change both the "before"
  and "after" figures and the ratio between them.
- "0 landed-tree mismatches" is a count over this benchmark's rounds, not a proof that no
  mismatch can occur; it is exactly the check `tree-identity` performs every time,
  described in [proofs/README.md](../proofs/README.md), and it is designed to stop a
  family rather than let a mismatch go unnoticed.
