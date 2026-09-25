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
- `.github/workflows/release.yml`: builds and pushes the container image to
  `ghcr.io/nybarius/svrf` on a version tag, and builds/smoke-tests the `pip`-installable
  wheel (optionally publishing it to PyPI once `PYPI_API_TOKEN` is set); see
  `docs/RELEASING.md`. `make wheel` runs the same build-and-install-in-a-fresh-venv check
  locally.
- `docs/demo.cast`: an asciinema v2 recording of `python3 demo/run_demo.py`, linked from
  the README; `demo/record_cast.py` produces it without needing asciinema installed.

### Changed

- `demo/run_demo.py` now prints a short narrated header before each phase (opening pull
  requests, configuring the train, each round, the final table), on by default
  (`run(..., narrate=False)` to silence it).

- `make check` now also builds and smoke tests the container image, matching every job
  `.github/workflows/ci.yml` runs; that CI job now calls `make docker` instead of
  duplicating its two steps.

## [0.1.0] - 2026-09-25

Initial public release: the braided merge train (`svrf.train.Train`), the command gate,
the admission check, the optional history-order check and re-land, the local demo, the
Lean proofs of the landing and scheduling invariants, and Docker/systemd deployment.
