## What this changes and why

## Tests

- [ ] Added or changed a test in `tests/` that fails without this change and passes with
      it (see `CONTRIBUTING.md` — test-first is expected for behavior changes)
- [ ] `make check` passes locally (Python tests including the denylist scan and the demo,
      and the Lean proofs)
- [ ] If this changes a rule in `src/svrf/rules.py`, the corresponding statement in
      `proofs/` still matches (or was updated in the same pull request)

## Anything reviewers should look at closely

Config changes, new subprocess calls or new external commands, anything that touches
`src/svrf/git.py` or `src/svrf/github.py` (these need to stay injection-safe against
attacker-controlled pull-request titles/branches — see `SECURITY.md`).
