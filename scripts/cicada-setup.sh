#!/usr/bin/env bash
#
# Finish (or refresh) a Homebrew install of Cicada (G181): `cicada-setup`, which the formula puts on PATH.
#
# Homebrew installs the code and its Python environment; everything that belongs to the person — the memory folder,
# the search model, the agent hooks, the MCP registration and the background service — is the job of ./install.sh,
# the same installer a clone runs. This runs it against the install's stable path (Homebrew's opt prefix, which
# survives `brew upgrade`), so every hook, MCP entry, launchd plist and systemd unit it writes names that path and
# never a versioned Cellar folder.
#
# The background service has one source per platform: scripts/install-backend-agent.sh (the launchd agent
# com.cicada.backend) on a Mac and scripts/install-backend-service.sh (the systemd user unit) on Linux. The formula
# declares no `service do` block, so `brew services` never writes a second plist or unit for the same backend.
#
# After `brew upgrade cicada`, run it again: install.sh skips a backend that already answers, so this restarts that
# service itself — but only a service that already runs THIS install. A launchd agent another Cicada wrote (the
# release app's launcher, a source checkout) is left alone.
#
# Usage: cicada-setup [install.sh flags: --dry-run, --skill, --uninstall]
# Env (set by the formula's wrapper): CICADA_REPO (the opt prefix's libexec), CICADA_LOG_DIR
set -euo pipefail

REPO="${CICADA_REPO:?CICADA_REPO must name the installed Cicada (the formula sets it)}"
[ -f "$REPO/install.sh" ] || { echo "cicada-setup: no install.sh in $REPO" >&2; exit 1; }
export CICADA_REPO="$REPO"
export CICADA_LOG_DIR="${CICADA_LOG_DIR:-${CICADA_HOME:-$HOME/.cicada}/logs}"

# install.sh leaves a backend that already answers alone; only then does this restart it below.
was_up=0
curl -fsS "http://127.0.0.1:8000/healthz" 2>/dev/null | grep -q '"status"' && was_up=1

bash "$REPO/install.sh" "$@"

for arg in "$@"; do
  case "$arg" in --uninstall|--dry-run|-h|--help) exit 0 ;; esac
done

# Restart a service that already runs this install, so an upgraded keg serves its new code.
[ "$was_up" -eq 1 ] || exit 0
if [ "$(uname -s)" = "Linux" ]; then
  unit="${SYSTEMD_USER_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}/cicada-backend.service"
  if [ -f "$unit" ] && grep -qF "$REPO/api/.venv/bin/python" "$unit"; then
    echo "  → Restarting the backend service on this install"
    bash "$REPO/scripts/install-backend-service.sh" || echo "  ! The service didn't restart (above)." >&2
  fi
else
  plist="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}/com.cicada.backend.plist"
  if [ -f "$plist" ] && grep -qF "$REPO/api/.venv/bin/python" "$plist"; then
    echo "  → Restarting the backend service on this install"
    bash "$REPO/scripts/install-backend-agent.sh" || echo "  ! The service didn't restart (above)." >&2
  fi
fi
