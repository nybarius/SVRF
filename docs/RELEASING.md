# Releasing

Releases are driven by a git tag; nothing publishes on an ordinary push to `main`.

## What happens on a tag

Pushing a tag matching `v*.*.*` (for example `v0.1.0`) triggers
`.github/workflows/release.yml`, which:

1. Builds the container image and pushes it to `ghcr.io/nybarius/svrf` as both
   `:<version>` (the tag with its leading `v` stripped) and `:latest`.
2. Builds the sdist and wheel with `python -m build`, installs the wheel into a fresh
   virtualenv and runs `svrf --version` against it as a smoke test, uploads both as a
   workflow artifact, and hands them to a separate `publish-pypi` job that uploads them
   to PyPI using [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC,
   via `pypa/gh-action-pypi-publish`) — no stored token or secret. That job needs a
   trusted publisher registered on pypi.org first (see below); until then it fails, but
   only that job, so the build and smoke test still run and report clearly.

On every other push and on pull requests, the same workflow builds the image and the
wheel and smoke-tests both, but pushes nothing — so a broken build fails CI before it
ever reaches a tag.

## Cutting a release

```sh
# 1. Update the version and the changelog.
#    - bump `version` in pyproject.toml
#    - move the CHANGELOG.md "Unreleased" section under a new "## [X.Y.Z] - YYYY-MM-DD" heading
git add pyproject.toml CHANGELOG.md
git commit -m "Release vX.Y.Z"
git push origin main

# 2. Tag it and push the tag.
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

Then watch the `release` workflow run on the tag. The container is at
`ghcr.io/nybarius/svrf:X.Y.Z` once it finishes; make it visible to `docker pull` without
authentication by setting the package's visibility to public once (GitHub packages are
private by default the first time they're pushed): repository → Packages → `svrf` →
Package settings → Change visibility.

## Publishing to PyPI

The workflow is ready (build, smoke test, and a `publish-pypi` job using Trusted
Publishing), but PyPI does not yet know about this repository. One-time setup on
pypi.org, done by the account that will own the `svrf` project:

1. Create a PyPI account and turn on two-factor authentication (required to manage
   trusted publishers).
2. The `svrf` project does not exist on PyPI yet, so add a **pending trusted
   publisher** at <https://pypi.org/manage/account/publishing/> with:
   - PyPI project name: `svrf`
   - Owner: `nybarius`
   - Repository name: `SVRF`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. Push a tag matching `v*.*.*`. The `publish-pypi` job's first successful run creates
   the `svrf` project on PyPI from the pending publisher and uploads the sdist and
   wheel; later releases just need the tag push.

No API token is created or stored anywhere; `id-token: write` on the `publish-pypi` job
is what lets `pypa/gh-action-pypi-publish` mint the short-lived OIDC credential PyPI
trusts instead. The `pypi` GitHub Actions environment is created automatically the
first time the job runs against it; add required reviewers there for a manual approval
gate before a publish, if wanted.

## Doing it manually (without waiting on CI)

```sh
make wheel   # builds dist/svrf-*.{whl,tar.gz} and smoke tests the wheel in a throwaway venv

# container
docker build -t ghcr.io/nybarius/svrf:X.Y.Z -t ghcr.io/nybarius/svrf:latest .
docker login ghcr.io -u <your-username>   # a token with write:packages
docker push ghcr.io/nybarius/svrf:X.Y.Z
docker push ghcr.io/nybarius/svrf:latest

# PyPI (manual, if you are not using the trusted-publishing workflow job — needs an
# API token, since a human running this locally has no OIDC identity for PyPI to trust)
python -m pip install twine
twine upload dist/*
```
