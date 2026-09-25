#!/usr/bin/env bash
#
# Install (or re-install) Cicada's background service: the launchd agent
# com.cicada.backend that keeps the backend alive whether or not the app is
# open (round-4 D3, G143).
#
# The one source of the plist. install.sh step 6 calls this after its own
# "a backend already answers /healthz -> skip" guard; the app runs it only
# after the person clicks Install in Settings -> General, as exactly
# ["/bin/bash", "<its checkout>/scripts/install-backend-agent.sh"]
# (BackendAgentPolicy), with CICADA_CAPTURE=off. Idempotent: the plist is
# rewritten from the same inputs, then the agent is booted out and in.
#
# The plist runs `$VENV_PY -m uvicorn`, never $VENV/bin/uvicorn: a venv console
# script hardcodes its interpreter in the shebang, so moving the repo breaks it
# (launchd then fails with EX_CONFIG and an empty log).
#
# Usage: scripts/install-backend-agent.sh [--dry-run]
# Env (defaults are the real locations):
#   CICADA_REPO          repo root         (default: this script's parent dir)
#   CICADA_MEMORY_PATH   memory dir        (default: ~/cicada/memory)
#   LAUNCH_AGENTS_DIR    LaunchAgents dir  (default: ~/Library/LaunchAgents)
#   CICADA_PORT          port              (default: 8000)
# Exit: 0 installed · 2 bad flag · 3 no Python environment · 4 launchd refused
set -euo pipefail

REPO="${CICADA_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MEMORY_PATH="${CICADA_MEMORY_PATH:-$HOME/cicada/memory}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
PORT="${CICADA_PORT:-8000}"
VENV_PY="$REPO/api/.venv/bin/python"
PLIST_LABEL="com.cicada.backend"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_LABEL.plist"
DOMAIN="gui/$(id -u)"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# A path with & < > must not break the XML.
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

if [ "$DRY_RUN" -eq 1 ]; then
  echo "\$ write $PLIST_PATH (RunAtLoad+KeepAlive, $VENV_PY -m uvicorn :$PORT)"
  echo "\$ launchctl bootout $DOMAIN/$PLIST_LABEL"
  echo "\$ launchctl bootstrap $DOMAIN $PLIST_PATH"
  exit 0
fi

if [ ! -x "$VENV_PY" ]; then
  echo "Cicada's Python environment is missing at $VENV_PY — run ./install.sh first." >&2
  exit 3
fi

mkdir -p "$LAUNCH_AGENTS_DIR" "$REPO/logs"
# CICADA_ALLOW_FEED_FETCH=1 is the opt-in for the nightly RSS-feed + ICS-calendar
# refresh at the tail of every Sleep cycle (G114 R5); the user-initiated
# POST /sources/poll-feeds and POST /sources/poll-calendars are gated by the same
# var. Without it an installed backend's subscriptions would never refresh.
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$VENV_PY")</string>
    <string>-m</string><string>uvicorn</string>
    <string>api.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$REPO")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CICADA_MEMORY_PATH</key><string>$(xml "$MEMORY_PATH")</string>
    <key>PATH</key><string>$(xml "$HOME")/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>CICADA_ALLOW_FEED_FETCH</key><string>1</string>
    <key>PYTHONPATH</key><string>$(xml "$REPO")</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$(xml "$REPO")/logs/backend.out.log</string>
  <key>StandardErrorPath</key><string>$(xml "$REPO")/logs/backend.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "$DOMAIN/$PLIST_LABEL" 2>/dev/null || true
# launchd can refuse a bootstrap that races its own bootout; three tries, a second apart.
for attempt in 1 2 3; do
  if launchctl bootstrap "$DOMAIN" "$PLIST_PATH" 2>/dev/null; then
    echo "Installed $PLIST_LABEL ($PLIST_PATH)"
    exit 0
  fi
  if [ "$attempt" -lt 3 ]; then sleep 1; fi
done
echo "launchd would not start $PLIST_LABEL — see $REPO/logs/backend.err.log" >&2
exit 4
