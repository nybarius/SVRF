# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project intends to follow [Semantic Versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Added

- `SECURITY.md` and GitHub private vulnerability reporting.
- `src/svrf/redact.py`: strips the GitHub token out of subprocess output before it
  reaches a log file, a held reason, or a receipt.
- `tests/test_security.py`: attacker-controlled titles and branch names never reach a
  shell; the token never reaches a receipt or a log.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1 by reference), issue
  and pull request templates.
- `action.yml`: a composite GitHub Action that runs one `svrf run --once` round, with a
  scheduled-workflow example in `docs/ACTION.md`.

## [0.1.0] - 2026-09-25

Initial public release: the braided merge train (`svrf.train.Train`), the command gate,
the admission check, the optional history-order check and re-land, the local demo, the
Lean proofs of the landing and scheduling invariants, and Docker/systemd deployment.
