# Releasing

Releases are driven by a git tag; nothing publishes on an ordinary push to `main`.

## What happens on a tag

Pushing a tag matching `v*.*.*` (for example `v0.1.0`) triggers
`.github/workflows/release.yml`, which:

1. Builds the container image and pushes it to `ghcr.io/nybarius/svrf` as both
   `:<version>` (the tag with its leading `v` stripped) and `:latest`.
2. Builds the sdist and wheel with `python -m build`, installs the wheel into a fresh
   virtualenv and runs `svrf --version` against it as a smoke test, uploads both as a
   workflow artifact, and — only if the `PYPI_API_TOKEN` repository secret is set —
   publishes them to PyPI with `twine`. Without that secret the step logs that it is
   skipping the publish and exits 0; nothing fails just because PyPI publishing isn't
   configured yet.

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

Not yet done automatically end to end — the workflow step exists and is tested (build +
install + `--version` smoke test), but no `PYPI_API_TOKEN` secret is configured, so it
currently no-ops. To turn it on:

1. Create a PyPI API token scoped to the `svrf` project (or an unscoped token for the
   first publish, then narrow it once the project exists on PyPI).
2. Add it as the repository secret `PYPI_API_TOKEN`.
3. The next tag push will publish.

## Doing it manually (without waiting on CI)

```sh
make wheel   # builds dist/svrf-*.{whl,tar.gz} and smoke tests the wheel in a throwaway venv

# container
docker build -t ghcr.io/nybarius/svrf:X.Y.Z -t ghcr.io/nybarius/svrf:latest .
docker login ghcr.io -u <your-username>   # a token with write:packages
docker push ghcr.io/nybarius/svrf:X.Y.Z
docker push ghcr.io/nybarius/svrf:latest

# PyPI
python -m pip install twine
twine upload dist/*
```
