#!/usr/bin/env bash
# Install CicadaApp as a real ~/Applications/Cicada.app — the "run it like an
# installed app, not two terminals" half of G88.
#
# Builds via bundle.sh (never `swift run` — see bundle.sh's own header for
# why), then handles replace-while-running deterministically: a running
# instance is quit FIRST, and the install aborts rather than proceeding if it
# won't quit — never ditto a bundle out from under its own live process and
# never leave a half-copied Cicada.app in ~/Applications. Uses `ditto`, not
# `cp -r` (ditto preserves the bundle correctly; cp -r can mangle it). Ad-hoc
# code-signs the result (`codesign --force --deep --sign -`) so Launch
# Services keeps one stable app identity across reinstalls instead of seeing
# a new, unsigned binary each time — also a prerequisite for G91's future
# share extension, which needs a signed, installed host app.
#
# Usage:
#   ./install_app.sh                 release build, install, don't launch
#   ./install_app.sh --debug         debug build (faster) — used by `make dev`
#   ./install_app.sh --relaunch      open the installed app when done
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="release"
RELAUNCH=0
for arg in "$@"; do
  case "$arg" in
    --debug)    CONFIG="debug" ;;
    --release)  CONFIG="release" ;;
    --relaunch) RELAUNCH=1 ;;
    *) echo "Unknown flag: $arg (expected --debug/--release/--relaunch)" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
step() { printf '  \033[36m→\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; }

DEST="$HOME/Applications/Cicada.app"
QUIT_TIMEOUT="${QUIT_TIMEOUT:-10}"

step "Building ($CONFIG)…"
if [ "$CONFIG" = "release" ]; then
  ./bundle.sh --release
else
  ./bundle.sh
fi
BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"
SRC="$BIN_DIR/Cicada.app"
if [ ! -d "$SRC" ]; then
  err "Build did not produce $SRC"
  exit 1
fi

# --- Replace-while-running, handled deterministically ---
# Quit any live instance first. The osascript quit request is backgrounded
# (never `wait`ed on) so a permission prompt it might trigger can never hang
# this script — the poll loop below is what actually decides when to move on.
if pgrep -x CicadaApp >/dev/null 2>&1; then
  step "Quitting the running Cicada instance…"
  ( osascript -e 'tell application "Cicada" to quit' >/dev/null 2>&1 & ) 2>/dev/null || true
  waited=0
  while pgrep -x CicadaApp >/dev/null 2>&1; do
    if [ "$waited" -ge "$QUIT_TIMEOUT" ]; then
      warn "Cicada didn't quit within ${QUIT_TIMEOUT}s — sending SIGTERM"
      pkill -x CicadaApp 2>/dev/null || true
      sleep 1
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  if pgrep -x CicadaApp >/dev/null 2>&1; then
    err "Cicada is still running and would not quit — aborting before touching $DEST"
    err "(never installing over a live bundle: that produces a half-copied app)"
    err "Quit it manually (Cmd-Q, or Activity Monitor) and re-run."
    exit 1
  fi
  ok "Previous instance quit"
fi

step "Installing to ${DEST}…"
mkdir -p "$HOME/Applications"
rm -rf "$DEST"
ditto "$SRC" "$DEST"
ok "Copied ($CONFIG build)"

step "Ad-hoc code-signing…"
codesign --force --deep --sign - "$DEST"
ok "Signed (ad-hoc — stabilizes the Launch Services identity across reinstalls; not a Gatekeeper-trusted signature)"

VERSION="$(defaults read "$DEST/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo '?')"
echo
echo "  Cicada.app ($VERSION, $CONFIG build) → $DEST"

if [ "$RELAUNCH" -eq 1 ]; then
  step "Launching…"
  open "$DEST"
  ok "Relaunched"
else
  echo
  warn "Gatekeeper trade-off: this build is local (not downloaded), so it normally carries no"
  warn "quarantine flag and opens without a prompt. If macOS ever blocks it as 'unidentified"
  warn "developer' (e.g. after it's been zipped/AirDropped/downloaded), right-click Cicada.app"
  warn "in Finder -> Open -> Open, once — that one-time click is the whole trade-off of shipping"
  warn "unsigned/ad-hoc rather than through notarization."
  echo "  Launch it: open \"$DEST\"  (or find Cicada in ~/Applications / Spotlight)"
fi
