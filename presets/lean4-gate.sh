#!/usr/bin/env bash
# Gate script for the Lean 4 preset: build the root target and every changed module.
# Copy it into your repository (the gate runs from the repository root) and set ROOT_LIB.
set -euo pipefail
ROOT_LIB="${ROOT_LIB:-MyProject}"
modules=()
while IFS= read -r path; do
  case "$path" in
    *.lean) [ -f "$path" ] && modules+=("$(printf '%s' "${path%.lean}" | tr '/' '.')") ;;
  esac
done < "${SVRF_CHANGED_FILES:-/dev/null}"
lake build "$ROOT_LIB" "${modules[@]}"
