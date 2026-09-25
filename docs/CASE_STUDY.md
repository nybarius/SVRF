# Case study: an agent swarm on a Lean monorepo

**Live dashboard:** https://nybarius.github.io/SVRF/dashboard/ — regenerated from the
production train's real, anonymized round receipts. **Numbers here are drawn only from
[docs/BENCHMARK.md](BENCHMARK.md) and that live dashboard.**

## The setup

A 17,000-declaration Lean 4 monorepo is fed pull requests by a swarm of coding agents,
around the clock. Before SVRF, a person started one gate run at a time, by hand, waited for
it to finish, and merged or fixed the pull request before starting the next one. Agents do
not wait for a person to be at a keyboard; the queue of ready pull requests grew faster than
that loop could clear it.

## What the team saw

- **Merges per hour: 5.8 → 16.3.** The before figure is a 27.7-hour window of one-at-a-time,
  hand-run gating (162 pull requests merged). The after figure is a 2.3-hour window of SVRF
  running unattended — and that window was arrival-bound: the queue of ready pull requests
  repeatedly ran empty, so the rate is a lower bound on what the same setup does against a
  continuous backlog, not a ceiling.
- **0.79 gate runs per merged pull request**, bisection included. Across 17 live rounds, 39
  pull requests merged used 31 gate runs. A family that gates green in one run charges one
  gate for every pull request inside it; the figure already carries the cost of the rounds
  that had to bisect a red family into smaller ones and gate the pieces again.
- **About 47 seconds of wall time per merged pull request**, averaged over the same 17
  rounds — down from roughly 2.5–3.5 minutes per pull request when gates ran one at a time.
- **Best batch: 13 pull requests landed from 2 gate runs in 4 minutes 46 seconds.** A large,
  mostly non-conflicting batch from the agent swarm is exactly the case batching is for.
- **Landed tree = gated tree, every time.** 0 landed-tree mismatches across the benchmark's
  rounds. The train fetches the actual merge commit after every landing and compares its
  tree against the tree that was gated; a mismatch would stop the family rather than let it
  pass unnoticed.

## How holds were handled

Not every pull request lands on the first pass. A pull request is held — kept out of the
next round entirely — only when it fails the admission check (doesn't merge onto the base,
or fails an extra project-specific check), or when its own gate run comes back red after
bisection has isolated it from the rest of its batch. A held pull request carries its
failing lines and is not re-read until the pull request's head changes or the base changes
a file the hold depended on, so a quiet queue costs nothing: an idle round is one rate-limit
read and one pull-request list.

Two shapes came up often enough to be worth naming:

- **Two pull requests touching the same file.** Batching is conflict-aware: SVRF reads
  which pairs of ready pull requests conflict and keeps the largest set that pairwise does
  not, so genuinely conflicting pull requests simply wait for a later round instead of
  failing a shared gate together. Conflicts confined to union-mergeable files (changelogs,
  requirement lists, import indexes) don't even count — those are merged by line union
  instead of held.
- **A red batch.** Rather than holding every pull request in a batch that failed together,
  a red family is bisected: it's split, each half is replanned on the current base, and each
  half is gated again. Only the pull request(s) that a bisection narrows the failure down to
  are actually held; the rest of the batch still lands.

## Try it yourself

The [demo](../demo/run_demo.py) reproduces the scheduling and landing behavior (conflicting
pull requests, a failing test, an out-of-order commit, a stacked pull request) against a
local repository, with no GitHub token or network access:

```sh
python3 demo/run_demo.py
```

It does not reproduce the timings above — those came from the real repository and real gate
commands described in [docs/BENCHMARK.md](BENCHMARK.md), not the demo's toy tree.

## See it live

The [live dashboard](https://nybarius.github.io/SVRF/dashboard/) is regenerated hourly from
this repository's own production train, straight from its round receipts, and anonymized
before publishing (`demo/anonymize_receipts.py`: renumbered pull requests, stand-in hashes,
titles and paths dropped). It shows the same totals, throughput, gates and wall time per
pull request, batch timeline, bisection trees and holds described in
[docs/DASHBOARD.md](DASHBOARD.md) — live, not a screenshot.
