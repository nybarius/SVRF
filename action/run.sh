#!/usr/bin/env bash
# The GitHub Action's entry script: wire the token into git the same way
# docker/entrypoint.sh does, write a config by auto-detection when none exists yet (the
# zero-config path: the Action works even before anyone has run `svrf init`), then run
# one SVRF round. Kept as its own file (rather than inline in action.yml) so it can be
# tested directly, without a runner.
#
#   GH_TOKEN=... SVRF_CONFIG=svrf.toml action/run.sh
set -euo pipefail

: "${GH_TOKEN:?the github-token input is required}"
: "${SVRF_CONFIG:?the config input is required}"

if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git >/dev/null 2>&1 || true
fi
git config --global --get user.name >/dev/null 2>&1 || git config --global user.name svrf
git config --global --get user.email >/dev/null 2>&1 || git config --global user.email svrf@localhost

if [ ! -f "$SVRF_CONFIG" ]; then
  init_args=(init --yes --config "$SVRF_CONFIG")
  if [ -n "${GITHUB_REPOSITORY:-}" ]; then
    init_args+=(--repo "$GITHUB_REPOSITORY")
  fi
  svrf "${init_args[@]}"
fi

exec svrf --config "$SVRF_CONFIG" run --once
