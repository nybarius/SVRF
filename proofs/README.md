# What the proofs cover

This directory is a Lean 4 model of the merge train's decision rules: which trees may be
folded together, when a batched landing is sound, when a held pull request is read again,
and when re-landing a history in a different commit order is safe. It is not a proof about
git, and it does not run inside the train. The code checks the one thing the proofs assume
and cannot check on their own: that the tree the base branch actually holds after a merge
is the tree the model says a merge step produces. Every landing compares the observed tree
with the gated tree and refuses to proceed on a mismatch; that comparison is what makes the
model's hypotheses true of the real repository, round after round.

## What is modelled, what is abstracted

- **Git trees are modelled as an opaque type `Tree`** (or, in the commutation lemmas, as a
  function from a `Path` to a `Val`, i.e. a set of file contents keyed by path). The proofs
  never inspect a tree's structure; they only ever ask whether two trees are equal.
- **A merge is modelled as a partial function `step : Tree → Head → Option Tree`**, `none`
  standing for a conflict. That git's merge of a prepared branch behaves like `step` is
  *not* a theorem here — it is the modelling boundary stated in
  `proofs/BraidedTrain/Landing.lean` and `proofs/BraidedTrain/Braid.lean`. The code does
  not trust it either: after every merge it reads the tree the base branch now holds and
  checks it against the tree the model predicted (`checkLanding` / `Replays`). A mismatch
  stops the family instead of being explained away.
- **A union merge on configured paths is modelled as independent writes** (`write`,
  `apply`) that commute when their paths are disjoint. This is what backs treating two
  pull requests as compatible when their only overlap is a union-merged file such as a
  changelog.
- **A gate is modelled as a predicate, or a function of the tree's content restricted to
  the paths it reads.** The proofs never open the gate command; they only ask whether its
  verdict is a function of what it read (used by the retry and history-reorder results).
- **Held memory and retry are modelled as a key (`RetryKey`: a head sha plus the watched
  content) and a verdict that is a pure function of that key.** The code computes the same
  key (`svrf.rules.retry_due`, `held_retry`) and reuses a held verdict exactly when the key
  has not changed.

## Rule map

Every decision rule the code enforces (`svrf.rules.RULES`) names the Lean theorem that
states it and the function or method that enforces it in the running train.

| Rule | Theorem | Enforced by |
| --- | --- | --- |
| `family-fold` | `fold` | `Train.plan` |
| `gate-green` | `landed_passes` | `Train.gate_family` |
| `tree-identity` | `checkLanding_iff` | `Train.land_family` |
| `outside-move-refused` | `checkLanding_refuses_moved` | `Train.land_family` |
| `bisect-lands-gated` | `segments_land_last_gated` | `Train.settle_red` |
| `prefix-ungated` | `prefix_is_fold` | `Train.land_family` |
| `one-gate-per-merge-commit` | `all_gated_iff_each_prefix` | `Train.land_family` |
| `land` | `landed_eq_gated` | `Train.land_family` |
| `hold` | `landed_passes` | `Train.settle_red` |
| `admit` | `admitted_iff` | `admission_decision` |
| `opt-out` | `admitted_iff` | `admission` |
| `already-merged` | `admitted_iff` | `admission` |
| `held-retry` | `retry_iff` | `retry_due` |
| `held-verdict-reuse` | `held_verdict_stands` | `held_retry` |
| `no-reopen-outside-watched-paths` | `no_reopen_outside_reads` | `held_retry` |
| `read-failure-never-holds` | `read_failure_never_holds` | `admission_decision` |
| `compatible-families` | `strands_comm` | `choose_families` |
| `interleaved-owners` | `interleaved_landing` | `choose_families` |
| `repair-mechanical` | `retry_iff` | `repair_class` |
| `ordered-reland` | `reland_tree` | `reland_class` |

`tests/test_proof_map.py` checks this table against `svrf.rules.RULES` directly: every
rule name and theorem name in the code must also appear in this file, every named theorem
or definition must exist in `proofs/BraidedTrain/*.lean`, and every named check must be a
real callable. If you add or rename a rule, update the table above and the code together;
the test fails otherwise.

## Files

| File | Contents |
| --- | --- |
| `BraidedTrain/Landing.lean` | `fold`, `Replays`, `landed`, `checkLanding`; landing a family lands the gated tree; admission and read-failure memory. |
| `BraidedTrain/Braid.lean` | The ungated-window invariant (`AllGated`, `mains`); retry as a function of a read key; commutation of disjoint writes (`strands_comm`). |
| `BraidedTrain/Interleaving.lean` | Two owners landing path-disjoint families interleaved still land one tree (`interleaved_landing`); when a gate's own read paths miss the other owner's writes, no joint gate is needed (`two_owners_end_gated`). |
| `BraidedTrain/Reland.lean` | Re-landing a history as tests-then-code-then-docs commits lands the identical tree (`reland_tree`), so any tree-reading gate's verdict is unchanged (`reland_gate`). |
| `BraidedTrain/Examples.lean` | Concrete instances that exercise the general lemmas against small, fully-written-out cases. |
| `CheckAxioms.lean` | Prints the axioms each main theorem depends on; `make proofs` fails if any line mentions `sorryAx` or `Classical.choice`. |

## How to build

```sh
cd proofs && lake build
```

The toolchain is pinned in `proofs/lean-toolchain` (`leanprover/lean4:v4.33.0`); `elan`
picks it up automatically. `lake build` compiles the whole `BraidedTrain` library.

## Axiom check

```sh
cd proofs && lake env lean CheckAxioms.lean
```

This prints, for every theorem an invariant in the table above depends on, the axioms Lean
used to prove it. `make proofs` runs this and fails the build if any printed line contains
`sorryAx` (an unfinished proof) or `Classical.choice` (a nonconstructive step none of these
proofs need — they are finite-list inductions throughout). `tests/test_proof_map.py`
separately checks the source text of `proofs/BraidedTrain/*.lean` for `sorry` and
`axiom` declarations, so neither can slip back in unnoticed.

## TODO

Further modelling work this directory does not yet cover:

- **Union merge as a model step.** State the configured union-merge (`svrf.rules.union_lines`)
  as its own step function and show it commutes with `unionStep` on disjoint line additions,
  the way `apply_comm_of_disjoint` already does for path-level writes — this would extend the
  commutation result down to line-level changelog entries instead of treating a union-merged
  file as an all-or-nothing path.
- **Speculative stacking across a list of families.** Model a stack of more than two families
  gated in sequence (the current results cover one family, or two interleaved owners) and
  state what a red family in the middle of the stack voids: every family gated on top of it,
  none gated underneath it.
- **Termination and gate count of bisection.** `Train.settle_red` halves a red family and
  regates each half; show this process terminates (family size strictly decreases) and bound
  the number of gates it costs in terms of the number of red pull requests.
- **Maximality of the chosen family.** `svrf.rules.choose_families` picks the largest
  pairwise-compatible set the enumeration finds; state and prove that no strictly larger
  pairwise-compatible set of the same candidate pull requests exists (maximum, not just
  maximal, independent set of the conflict graph).
- **Stacked retarget leaves the head tree unchanged.** When a stacked pull request's base is
  moved to its parent's former base after the parent merges (`retarget`), show the retarget
  itself does not change the tree the head branch would land — only which branch it is read
  against.
