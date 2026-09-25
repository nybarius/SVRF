# Security policy

## Reporting a vulnerability

Please report security vulnerabilities through **GitHub's private vulnerability
reporting** on this repository, not through a public issue:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue, how to reproduce it, and its impact.

This opens a private advisory that only the maintainers (and, if you choose, you) can
see, and lets us discuss and fix the issue before any public disclosure. If your GitHub
account cannot see that tab (the repository may still be private), ask the person who
gave you access for an invitation, or open a regular issue asking for a private channel
without describing the vulnerability itself.

We aim to acknowledge a report within 5 business days and to have either a fix or a
mitigation plan within 30 days, depending on severity.

## Supported versions

SVRF is pre-1.0. Security fixes are made against the `main` branch and released in the
next tagged version; there is no separate long-term-support branch yet.

## Scope and threat model

SVRF runs unattended against a GitHub repository whose pull requests can come from
anyone with write access, and — if the repository is public and accepts pull requests
from forks — from untrusted third parties. Treat the following as in scope:

- **Command injection** from anything a pull request author controls: its title, body,
  branch name, labels, or commit messages. Every external command SVRF runs
  (`src/svrf/git.py`, `src/svrf/github.py`) is invoked as an argument list
  (`subprocess.run([...])`), never through a shell string, so this class of value can at
  worst become one literal argument or one byte string inside a git object — see
  `tests/test_security.py` for the cases this is checked against.
- **Token handling**: the GitHub token (`GH_TOKEN`/`GITHUB_TOKEN`) is read by the `gh`
  CLI and by git's credential helper directly from the environment; SVRF's own code never
  reads or stores it, and `svrf.toml` has no field for it (see
  `docs/GITHUB_SETUP.md`). Subprocess output that could echo an inherited token back
  (a failed git or `gh` call, a gate's or the admission command's output) is redacted
  (`src/svrf/redact.py`) before it reaches a log file, a held reason, or a receipt.
- **Least privilege**: `gh_argv` in `src/svrf/github.py` refuses to run any `gh` call
  that does not explicitly name the configured repository, so a token scoped to one
  repository is sufficient and SVRF never asks it to reach another one.

Out of scope, by design, and worth understanding before you rely on SVRF:

- **The gate itself runs your pull requests' code.** `gate.commands` (and, if
  configured, `admission.command`) execute on the folded tree of admitted pull requests,
  with the process's full environment, including any secret you have exported for the
  gate to use. A pull request that changes what the gate runs is, by construction,
  running its own code on your machine before it merges — the same trust boundary as any
  CI system that builds and tests pull requests. Do not export secrets the gate does not
  need into the environment SVRF runs in, and consider running the gate in a container or
  a machine that holds nothing more sensitive than it needs.
- **Branch protection and review requirements** are enforced by GitHub, not by SVRF; see
  "Branch protection interplay" in `docs/GITHUB_SETUP.md`.
