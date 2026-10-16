#!/usr/bin/env bash
#
# Install (or re-install) Cicada's background service on Linux: a systemd *user* unit, cicada-backend.service, that
# keeps the backend alive with no app (G181, headless server mode, phase 1). The Linux twin of
# scripts/install-backend-agent.sh (launchd), with the same inputs and the same rules:
#
# - it runs `$VENV_PY -m uvicorn`, never $VENV/bin/uvicorn (a console script's shebang breaks when the repo moves);
# - it binds 127.0.0.1 only. Nothing here opens a port beyond this machine. Reaching the backend from another
#   machine goes through an overlay network the person runs (for example `tailscale serve`, which proxies the
#   tailnet to this loopback port); this script never runs it, never configures it, and never binds 0.0.0.0;
# - it creates no credential. The backend writes its own $CICADA_HOME/api_token on first start; a metered key for
#   scheduled Sleep (ruling 4) goes in $CICADA_HOME/secrets.env, written by the person.
#
# A user unit stops when the person logs out unless lingering is on. This script only checks and says so: turning
# it on needs root (`sudo loginctl enable-linger <user>`), and that is the person's step.
#
# Usage: scripts/install-backend-service.sh [--dry-run] [--no-start] [--uninstall]
# Env (defaults are the real locations):
#   CICADA_REPO          repo root          (default: this script's parent dir)
#   CICADA_MEMORY_PATH   memory dir         (default: api/.env's CICADA_MEMORY_PATH, else ~/cicada/memory)
#   CICADA_HOME          Cicada's home      (default: ~/.cicada)
#   CICADA_PORT          port               (default: 8000)
#   CICADA_LOG_DIR       the backend's logs (default: <repo>/logs, like the launchd agent)
#   SYSTEMD_USER_DIR     unit dir           (default: ${XDG_CONFIG_HOME:-~/.config}/systemd/user)
#   UNIT_NAME            the unit's name    (default: cicada-backend.service; tests use their own)
# Exit: 0 done · 2 bad flag · 3 no Python environment · 4 systemd refused · 5 not Linux
set -euo pipefail

REPO="${CICADA_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# Same fallback as the launchd agent: the unit's own CICADA_MEMORY_PATH wins over api/.env at runtime, so an unset
# variable falls back to what api/.env says before the default.
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
CICADA_HOME_DIR="${CICADA_HOME:-$HOME/.cicada}"
PORT="${CICADA_PORT:-8000}"
LOG_DIR="${CICADA_LOG_DIR:-$REPO/logs}"
UNIT_DIR="${SYSTEMD_USER_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
UNIT_NAME="${UNIT_NAME:-cicada-backend.service}"
UNIT_PATH="$UNIT_DIR/$UNIT_NAME"
VENV_PY="$REPO/api/.venv/bin/python"

DRY_RUN=0
START=1
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-start) START=0 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(uname -s)" != "Linux" ] && [ -z "${CICADA_SERVICE_ANY_OS:-}" ]; then
  echo "This installs a systemd service, which is Linux only. On a Mac, scripts/install-backend-agent.sh installs the launchd agent." >&2
  exit 5
fi

case "$PORT" in
  ''|*[!0-9]*) echo "CICADA_PORT must be a number, not '$PORT'." >&2; exit 2 ;;
esac

if [ "$UNINSTALL" -eq 1 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "\$ systemctl --user disable --now $UNIT_NAME"
    echo "\$ rm $UNIT_PATH"
    echo "\$ systemctl --user daemon-reload"
    exit 0
  fi
  systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload 2>/dev/null || true
  echo "Removed $UNIT_NAME (the memory directory and $CICADA_HOME_DIR are untouched)"
  exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "\$ write $UNIT_PATH (Restart=always, $VENV_PY -m uvicorn 127.0.0.1:$PORT)"
  echo "\$ systemctl --user daemon-reload"
  if [ "$START" -eq 1 ]; then
    echo "\$ systemctl --user enable $UNIT_NAME"
    echo "\$ systemctl --user restart $UNIT_NAME"
  fi
  exit 0
fi

if [ ! -x "$VENV_PY" ]; then
  echo "Cicada's Python environment is missing at $VENV_PY — run ./install.sh first." >&2
  exit 3
fi

# systemd unit files take a path with a space as-is in WorkingDirectory=, but Environment= and ExecStart= need quoting;
# a % starts a specifier, so it is doubled. A path with a double quote or a newline is refused, not escaped.
for p in "$REPO" "$MEMORY_PATH" "$CICADA_HOME_DIR" "$LOG_DIR"; do
  case "$p" in
    *'"'*|*$'\n'*|*'\'*) echo "Cicada won't write a service for a path with a quote, backslash or newline: $p" >&2; exit 2 ;;
  esac
done
unit_q() { printf '"%s"' "${1//%/%%}"; }

mkdir -p "$UNIT_DIR" "$LOG_DIR"
# ~/.cicada is the same layout as on a Mac: the backend fills it (api_token 0600, remote/, sleep/, models/ ...).
mkdir -p "$CICADA_HOME_DIR"
chmod 700 "$CICADA_HOME_DIR"

# CICADA_ALLOW_FEED_FETCH=1 matches the launchd agent: the nightly RSS/ICS refresh is part of an installed backend.
# UMask=0077: every file the backend creates (the token, secrets it is handed, the bank) is the person's alone.
TMP_UNIT="$(mktemp "$UNIT_DIR/.$UNIT_NAME.XXXXXX")"
cat > "$TMP_UNIT" <<EOF
# Written by Cicada's scripts/install-backend-service.sh — re-run it rather than editing this file.
[Unit]
Description=Cicada backend (headless)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${REPO//%/%%}
ExecStart=$(unit_q "$VENV_PY") -m uvicorn api.main:app --host 127.0.0.1 --port $PORT
Environment=$(unit_q "CICADA_MEMORY_PATH=$MEMORY_PATH")
Environment=$(unit_q "CICADA_HOME=$CICADA_HOME_DIR")
Environment=$(unit_q "PYTHONPATH=$REPO")
Environment=$(unit_q "PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin")
Environment=CICADA_ALLOW_FEED_FETCH=1
UMask=0077
Restart=always
RestartSec=2
StandardOutput=append:${LOG_DIR//%/%%}/backend.out.log
StandardError=append:${LOG_DIR//%/%%}/backend.err.log

[Install]
WantedBy=default.target
EOF
mv "$TMP_UNIT" "$UNIT_PATH"
echo "Wrote $UNIT_PATH"

if ! systemctl --user daemon-reload; then
  echo "systemd would not reload the user units — is a user session running? (try: loginctl enable-linger)" >&2
  exit 4
fi
if [ "$START" -eq 1 ]; then
  systemctl --user enable "$UNIT_NAME" >/dev/null
  if ! systemctl --user restart "$UNIT_NAME"; then
    echo "systemd would not start $UNIT_NAME — see $LOG_DIR/backend.err.log or: journalctl --user -u $UNIT_NAME" >&2
    exit 4
  fi
  echo "Started $UNIT_NAME on 127.0.0.1:$PORT"
fi

# Lingering keeps a user service running with no one logged in — what a server needs. Checked, never changed.
if command -v loginctl >/dev/null 2>&1; then
  linger="$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null || true)"
  if [ "$linger" != "yes" ]; then
    echo "Note: this service stops when you log out. To keep it running on a server, run once: sudo loginctl enable-linger $(id -un)"
  fi
fi
exit 0
