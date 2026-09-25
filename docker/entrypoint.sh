#!/bin/sh
# Wire the token into git (for pushes) and hand over to the svrf CLI.
set -e
if [ -n "${GH_TOKEN:-}" ] || [ -n "${GITHUB_TOKEN:-}" ]; then
  gh auth setup-git >/dev/null 2>&1 || true
fi
git config --global --get user.name >/dev/null 2>&1 || git config --global user.name svrf
git config --global --get user.email >/dev/null 2>&1 || git config --global user.email svrf@localhost
exec svrf "$@"
