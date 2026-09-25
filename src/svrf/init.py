"""`svrf init`: look at the project svrf is being installed into, guess its type and a
sensible gate command, and write `svrf.toml` plus a scheduled workflow that runs the
published Action. Idempotent (never overwrites either file without `--force`) and asks
at most three questions, each with a detected default, so `--yes` never needs a prompt.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "svrf.toml"
WORKFLOW_PATH = Path(".github/workflows/svrf.yml")
FALLBACK_GATE = "make test"

WORKFLOW_TEMPLATE = """name: svrf
on:
  schedule:
    - cron: "*/5 * * * *"
  pull_request:
    types: [ready_for_review]
  workflow_dispatch: {{}}

jobs:
  round:
    runs-on: ubuntu-latest
    concurrency:
      group: svrf-round
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          sparse-checkout: |
            {config}
          sparse-checkout-cone-mode: false
      - uses: {action_repo}@v0.1.0
        with:
          github-token: ${{{{ secrets.SVRF_TOKEN }}}}
          config: {config}
"""

CONFIG_TEMPLATE = """# {config} written by `svrf init`. Full reference: presets/ and README.md#configuration.
repo = "{repo}"       # owner/name on GitHub
base = "{base}"       # the branch pull requests land on

[gate]
commands = ["{gate}"]
"""


@dataclass
class Detected:
    project_kind: str
    gate_command: str


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    """Every git call names its repository explicitly (`-C`), the same invariant the rest
    of the package holds to (`test_daemon.ExplicitRepository`)."""
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(["git", "-C", str(root), *args], 1, "", str(error))


def slug_from_url(url: str) -> str | None:
    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@github.com:"):
        return url.split(":", 1)[1] or None
    for prefix in ("https://github.com/", "http://github.com/", "ssh://git@github.com/"):
        if url.startswith(prefix):
            return url[len(prefix):] or None
    return None


def detect_repo(root: Path) -> str | None:
    """`owner/name`, read from the `origin` remote; `None` if there is no git remote or it
    is not a GitHub URL."""
    done = _git(["remote", "get-url", "origin"], root)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return slug_from_url(done.stdout.strip())


def detect_base(root: Path) -> str:
    """The branch pull requests target: the remote's default branch if it can be read,
    else whichever of `main`/`master` exists locally, else `main`."""
    done = _git(["symbolic-ref", "refs/remotes/origin/HEAD"], root)
    if done.returncode == 0 and done.stdout.strip():
        return done.stdout.strip().rsplit("/", 1)[-1]
    for candidate in ("main", "master"):
        if _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}"], root).returncode == 0:
            return candidate
    return "main"


def _node_gate(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm test"
    if (root / "yarn.lock").is_file():
        return "yarn test"
    return "npm test"


def detect_gate(root: Path) -> Detected | None:
    """A project type and a sensible gate command, or `None` when nothing recognized."""
    if (root / "lakefile.toml").is_file() or (root / "lakefile.lean").is_file():
        return Detected("lean", "lake build")
    if (root / "Cargo.toml").is_file():
        return Detected("rust", "cargo test")
    if (root / "go.mod").is_file():
        return Detected("go", "go test ./...")
    if (root / "package.json").is_file():
        return Detected("node", _node_gate(root))
    if (root / "tox.ini").is_file():
        return Detected("python", "tox")
    if any((root / name).is_file() for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")):
        return Detected("python", "python3 -m pytest -q")
    if (root / "Makefile").is_file():
        text = (root / "Makefile").read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^test:", text, re.MULTILINE):
            return Detected("make", "make test")
    return None


def _ask(prompt: str, default: str, *, yes: bool) -> str:
    if yes or not sys.stdin.isatty():
        return default
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


@dataclass
class Plan:
    repo: str
    base: str
    gate: str
    project_kind: str
    questions_asked: int


def plan(root: Path, *, repo: str | None, base: str | None, gate: str | None, yes: bool) -> Plan:
    """Detect what init can, ask for whatever it could not detect and `--yes` did not
    already answer (at most three questions), and return what will be written."""
    asked = 0
    detected = detect_gate(root)

    resolved_repo = repo or detect_repo(root)
    if not resolved_repo:
        resolved_repo = _ask("GitHub repository (owner/name)", "", yes=yes)
        asked += 1
    if not resolved_repo:
        raise ValueError("no repository given: pass --repo owner/name or run inside a clone with a GitHub remote")

    resolved_base = base or detect_base(root)
    if base is None and not yes and sys.stdin.isatty():
        resolved_base = _ask("Base branch", resolved_base, yes=yes)
        asked += 1

    if gate:
        resolved_gate = gate
    elif detected:
        resolved_gate = detected.gate_command
    else:
        resolved_gate = _ask("No test command detected. Gate command to run", FALLBACK_GATE, yes=yes)
        asked += 1

    return Plan(repo=resolved_repo, base=resolved_base, gate=resolved_gate,
                project_kind=(detected.project_kind if detected else "unknown"), questions_asked=asked)


def render_config(chosen: Plan, config_name: str) -> str:
    return CONFIG_TEMPLATE.format(config=config_name, repo=chosen.repo, base=chosen.base, gate=chosen.gate)


def render_workflow(config_name: str, action_repo: str) -> str:
    return WORKFLOW_TEMPLATE.format(config=config_name, action_repo=action_repo)


@dataclass
class Result:
    config_path: Path
    workflow_path: Path
    config_written: bool
    workflow_written: bool
    plan: Plan


def run(root: Path, *, config_name: str = CONFIG_NAME, repo: str | None = None, base: str | None = None,
        gate: str | None = None, yes: bool = False, force: bool = False,
        action_repo: str = "nybarius/SVRF") -> Result:
    root = Path(root)
    chosen = plan(root, repo=repo, base=base, gate=gate, yes=yes)
    config_path = root / config_name
    workflow_path = root / WORKFLOW_PATH

    config_written = False
    if force or not config_path.exists():
        config_path.write_text(render_config(chosen, config_name), encoding="utf-8")
        config_written = True

    workflow_written = False
    if force or not workflow_path.exists():
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(render_workflow(config_name, action_repo), encoding="utf-8")
        workflow_written = True

    return Result(config_path=config_path, workflow_path=workflow_path, config_written=config_written,
                  workflow_written=workflow_written, plan=chosen)


def describe(result: Result) -> str:
    lines = []
    lines.append(f"detected project type: {result.plan.project_kind}")
    lines.append(f"{'wrote' if result.config_written else 'kept existing'} {result.config_path}")
    lines.append(f"{'wrote' if result.workflow_written else 'kept existing'} {result.workflow_path}")
    if not result.config_written:
        lines.append(f"  ({result.config_path.name} already existed; rerun with --force to overwrite)")
    if not result.workflow_written:
        lines.append(f"  ({result.workflow_path} already existed; rerun with --force to overwrite)")
    lines.append("")
    lines.append(f"next step: add a repository secret SVRF_TOKEN with the token svrf needs "
                 f"(see docs/GITHUB_SETUP.md), then push {result.workflow_path} to {result.plan.base}.")
    lines.append(f"or, without GitHub Actions: pip install svrf && svrf --config {result.config_path.name} run --once")
    return "\n".join(lines)
