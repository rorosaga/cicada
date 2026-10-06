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
# A release app (G182) runs the copy of this script inside the app with
# CICADA_BACKEND_PROGRAM set to its stable launcher, $CICADA_HOME/bin/cicada-backend:
# the plist then runs that launcher (which the app re-points at itself each time
# it opens, so moving or updating the app never leaves launchd on a dead path),
# with its working directory and logs under $CICADA_HOME — never inside the app.
#
# Usage: scripts/install-backend-agent.sh [--dry-run]
# Env (defaults are the real locations):
#   CICADA_REPO             repo root         (default: this script's parent dir)
#   CICADA_MEMORY_PATH      memory dir        (default: api/.env's CICADA_MEMORY_PATH, else ~/cicada/memory)
#   LAUNCH_AGENTS_DIR       LaunchAgents dir  (default: ~/Library/LaunchAgents)
#   CICADA_PORT             port              (default: 8000)
#   CICADA_BACKEND_PROGRAM  release: the launcher the plist runs instead of the venv's uvicorn
#   CICADA_LOG_DIR          where launchd writes the backend's output (default: <repo>/logs, release: $CICADA_HOME/logs)
#   PLIST_LABEL             the agent's label (default: com.cicada.backend; tests use their own)
# Exit: 0 installed · 2 bad flag · 3 no Python environment · 4 launchd refused
set -euo pipefail

REPO="${CICADA_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# The plist's own CICADA_MEMORY_PATH wins over api/.env at runtime, so an unset
# variable must fall back to what api/.env says before the default: the app's
# Install runs this with no environment, and a person whose memory lives
# elsewhere got an empty ~/cicada/memory served instead of their bank.
env_file_memory() {
  local line
  [ -f "$REPO/api/.env" ] || return 0
  line=$(grep -E '^CICADA_MEMORY_PATH=' "$REPO/api/.env" | tail -n1 || true)
  line="${line#CICADA_MEMORY_PATH=}"
  line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
  case "$line" in "~") line="$HOME" ;; "~/"*) line="$HOME/${line#\~/}" ;; esac
  printf '%s' "$line"
}
MEMORY_PATH="${CICADA_MEMORY_PATH:-$(env_file_memory)}"
MEMORY_PATH="${MEMORY_PATH:-$HOME/cicada/memory}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
PORT="${CICADA_PORT:-8000}"
VENV_PY="$REPO/api/.venv/bin/python"
PROGRAM="${CICADA_BACKEND_PROGRAM:-}"
CICADA_HOME_DIR="${CICADA_HOME:-$HOME/.cicada}"
if [ -n "$PROGRAM" ]; then
  LOG_DIR="${CICADA_LOG_DIR:-$CICADA_HOME_DIR/logs}"
  WORK_DIR="$CICADA_HOME_DIR"
else
  LOG_DIR="${CICADA_LOG_DIR:-$REPO/logs}"
  WORK_DIR="$REPO"
fi
PLIST_LABEL="${PLIST_LABEL:-com.cicada.backend}"
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
  if [ -n "$PROGRAM" ]; then
    echo "\$ write $PLIST_PATH (RunAtLoad+KeepAlive, $PROGRAM :$PORT)"
  else
    echo "\$ write $PLIST_PATH (RunAtLoad+KeepAlive, $VENV_PY -m uvicorn :$PORT)"
  fi
  echo "\$ launchctl bootout $DOMAIN/$PLIST_LABEL"
  echo "\$ launchctl bootstrap $DOMAIN $PLIST_PATH"
  exit 0
fi

if [ -n "$PROGRAM" ]; then
  if [ ! -x "$PROGRAM" ]; then
    echo "Cicada's backend launcher is missing at $PROGRAM — open Cicada once to write it." >&2
    exit 3
  fi
elif [ ! -x "$VENV_PY" ]; then
  echo "Cicada's Python environment is missing at $VENV_PY — run ./install.sh first." >&2
  exit 3
fi

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"
if [ -n "$PROGRAM" ]; then
  # Release: the launcher sets up its own Python and code; only the bank, the port
  # and a non-default home travel in the plist.
  PROGRAM_XML="    <string>$(xml "$PROGRAM")</string>"
  EXTRA_ENV="    <key>CICADA_PORT</key><string>$(xml "$PORT")</string>"
  if [ -n "${CICADA_HOME:-}" ]; then
    EXTRA_ENV="$EXTRA_ENV
    <key>CICADA_HOME</key><string>$(xml "$CICADA_HOME")</string>"
  fi
else
  PROGRAM_XML="    <string>$(xml "$VENV_PY")</string>
    <string>-m</string><string>uvicorn</string>
    <string>api.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$PORT</string>"
  EXTRA_ENV="    <key>PYTHONPATH</key><string>$(xml "$REPO")</string>"
fi
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
$PROGRAM_XML
  </array>
  <key>WorkingDirectory</key><string>$(xml "$WORK_DIR")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CICADA_MEMORY_PATH</key><string>$(xml "$MEMORY_PATH")</string>
    <key>PATH</key><string>$(xml "$HOME")/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>CICADA_ALLOW_FEED_FETCH</key><string>1</string>
$EXTRA_ENV
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$(xml "$LOG_DIR")/backend.out.log</string>
  <key>StandardErrorPath</key><string>$(xml "$LOG_DIR")/backend.err.log</string>
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
echo "launchd would not start $PLIST_LABEL — see $LOG_DIR/backend.err.log" >&2
exit 4
