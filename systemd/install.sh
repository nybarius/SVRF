#!/usr/bin/env bash
# Install the SVRF systemd user units. Nothing is enabled unless asked:
#
#   bash systemd/install.sh            # install and reload only
#   bash systemd/install.sh --enable   # also start the timer
#
# The service reads ~/.config/svrf/svrf.toml and runs ~/.local/bin/svrf
# (`pipx install .` or `pip install --user .` puts it there).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$units"
install -m 0644 "$here/svrf.service" "$units/svrf.service"
install -m 0644 "$here/svrf.timer" "$units/svrf.timer"
systemctl --user daemon-reload
if [[ "${1:-}" == "--enable" ]]; then
  systemctl --user enable --now svrf.timer
fi
echo "installed: $units/svrf.service $units/svrf.timer"
