#!/usr/bin/env bash
# Install CicadaApp as a real ~/Applications/Cicada.app — the "run it like an
# installed app, not two terminals" half of G88.
#
# Builds via bundle.sh (never `swift run` — see bundle.sh's own header for
# why). The install is non-destructive: the new build is staged into a
# hidden sibling dir, ad-hoc signed, and *verified* there — nothing about
# the currently-installed app is touched while any of that can still fail.
# Only once the staged build passes `codesign --verify --deep --strict` do
# we quit a running instance and swap it into place, moving the previous
# app to a backup path first so a failed or interrupted swap can restore it
# (and the next run restores it after a hard kill) rather than leave
# ~/Applications with no working Cicada at all. Uses `ditto`, not
# `cp -r` (ditto preserves the bundle correctly; cp -r can mangle it).
# Ad-hoc code-signing (`codesign --force --deep --sign -`) also keeps one
# stable Launch Services app identity across reinstalls instead of a new,
# unsigned binary each time — a prerequisite for G91's future share
# extension, which needs a signed, installed host app.
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

# CICADA_APP_DIR exists so the swap below can be exercised against a scratch
# directory; nothing in the app or the Makefile sets it.
APP_DIR="${CICADA_APP_DIR:-$HOME/Applications}"
DEST="$APP_DIR/Cicada.app"
STAGING="$APP_DIR/.Cicada.app.staging"
BACKUP="$APP_DIR/.Cicada.app.previous"
QUIT_TIMEOUT="${QUIT_TIMEOUT:-10}"

# --- Recover from an interrupted earlier run BEFORE doing anything else ---
# The swap at the bottom is two moves: $DEST -> $BACKUP, then $STAGING ->
# $DEST. A run killed hard between them (kill -9, a crashed terminal — the
# trap below can't catch those) leaves $BACKUP as the only installed copy, so
# it goes back to $DEST here, before this run can fail or be interrupted
# again. A leftover $STAGING is never the only copy of anything and is simply
# cleared.
mkdir -p "$APP_DIR"
if [ -d "$BACKUP" ] && [ ! -d "$DEST" ]; then
  warn "An earlier run was interrupted mid-install — restoring the previous Cicada.app first"
  mv "$BACKUP" "$DEST"
fi
rm -rf "$STAGING"

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

# --- Stage + sign + verify BEFORE touching anything installed ---
# Nothing below this point can delete a working Cicada.app: the new build
# lands in a hidden sibling dir first, and only a build that passes
# `codesign --verify` ever gets anywhere near $DEST. A failure here (it has
# happened twice for real while building this: a bad Unicode-adjacent var
# expansion, then codesign choking on an unsigned nested resource bundle)
# leaves the previously installed app completely untouched.
step "Staging to ${STAGING}…"
ditto "$SRC" "$STAGING"
ok "Staged ($CONFIG build)"

step "Ad-hoc code-signing the staged build…"
if ! codesign --force --deep --sign - "$STAGING"; then
  err "Code-signing failed on the staged build."
  err "The previously installed Cicada.app at $DEST was never touched."
  rm -rf "$STAGING"
  exit 1
fi

step "Verifying the staged signature before touching the installed app…"
if ! codesign --verify --deep --strict "$STAGING" >/dev/null 2>&1; then
  err "Signature verification failed on the staged build."
  err "The previously installed Cicada.app at $DEST was never touched."
  rm -rf "$STAGING"
  exit 1
fi
ok "Signed and verified (ad-hoc — stabilizes the Launch Services identity across reinstalls; not a Gatekeeper-trusted signature)"

# --- Replace-while-running, handled deterministically ---
# Only now — with a verified build ready to install — do we quit a live
# instance. The osascript quit request is backgrounded (never `wait`ed on)
# so a permission prompt it might trigger can never hang this script — the
# poll loop below is what actually decides when to move on.
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
    err "(the verified staged build is left at $STAGING; nothing installed was changed)"
    err "Quit it manually (Cmd-Q, or Activity Monitor) and re-run."
    exit 1
  fi
  ok "Previous instance quit"
fi

# --- Atomic-ish swap: move the old app aside, move the new one in, and if
# the second move fails for any reason — or this shell is interrupted
# between the two moves — put the old one straight back. The trap is armed
# only for the window in which $DEST is missing, and $BACKUP is only ever
# cleared while $DEST exists, so no exit path leaves ~/Applications with no
# Cicada.app at all. ---
restore_previous() {
  if [ ! -d "$DEST" ] && [ -d "$BACKUP" ]; then
    mv "$BACKUP" "$DEST"
    err "Interrupted mid-install — restored the previously installed Cicada.app at $DEST."
  fi
}
step "Installing to ${DEST}…"
if [ -d "$DEST" ]; then
  rm -rf "$BACKUP"
  trap 'restore_previous' EXIT
  trap 'restore_previous; exit 1' INT TERM
  mv "$DEST" "$BACKUP"
fi
if mv "$STAGING" "$DEST"; then
  trap - EXIT INT TERM
  rm -rf "$BACKUP"
  ok "Installed ($CONFIG build)"
else
  trap - EXIT INT TERM
  err "Failed to move the verified build into place at $DEST."
  if [ -d "$BACKUP" ]; then
    mv "$BACKUP" "$DEST"
    err "Restored the previously installed Cicada.app — nothing was lost."
  else
    err "No previous install existed to restore."
  fi
  exit 1
fi

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
