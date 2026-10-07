#!/usr/bin/env bash
# Install the latest Cicada release on this Mac (G182):
#
#   curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-release.sh | bash
#
# Downloads the newest release's zip with curl (which sets no quarantine flag,
# so Gatekeeper does not block the not-yet-notarized app), checks its sha256
# against the release's latest.json, installs Cicada.app into ~/Applications
# (or /Applications when ~/Applications can't be used), and opens it once.
# An existing Cicada.app is moved to the Trash first, never deleted.
#
# Env: CICADA_INSTALL_DIR   where to put Cicada.app (default ~/Applications)
#      CICADA_RELEASE_REPO  owner/repo to install from (default rorosaga/cicada)
#      CICADA_NO_OPEN=1     install without opening the app
#      CICADA_RELEASE_API   the "latest release" URL (default GitHub's API for the repo; tests serve their own)
#      CICADA_LAUNCH_AGENTS_DIR  where the background service plist is looked for (default ~/Library/LaunchAgents)
set -euo pipefail

REPO="${CICADA_RELEASE_REPO:-rorosaga/cicada}"
API="${CICADA_RELEASE_API:-https://api.github.com/repos/$REPO/releases/latest}"

say()  { printf '\033[36m→\033[0m %s\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "Cicada runs on macOS."
[ "$(uname -m)" = "arm64" ] || die "This build of Cicada is for Apple silicon Macs (M1 or later)."
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 14 ] || die "Cicada needs macOS 14 Sonoma or later (this Mac runs $(sw_vers -productVersion))."

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say "Finding the latest release of ${REPO}…"
curl -fsSL -H "Accept: application/vnd.github+json" "$API" -o "$WORK/release.json" \
  || die "Couldn't reach GitHub. Check your connection and try again."
latest_url="$(/usr/bin/python3 -c 'import json,sys
assets=json.load(open(sys.argv[1])).get("assets",[])
print(next((a["browser_download_url"] for a in assets if a["name"]=="latest.json"),""))' "$WORK/release.json")"
[ -n "$latest_url" ] || die "The latest release has no latest.json — try again in a few minutes."
curl -fsSL "$latest_url" -o "$WORK/latest.json" || die "Couldn't download latest.json."
read -r version url sha <<<"$(/usr/bin/python3 -c 'import json,sys
d=json.load(open(sys.argv[1])); print(d["version"], d["url"], d["sha256"])' "$WORK/latest.json")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "The release names an odd version ($version) — nothing was installed."
[[ "$url" == https://* ]] || [ -n "${CICADA_RELEASE_API:-}" ] || die "The release's download isn't https — nothing was installed."

say "Downloading Cicada ${version}…"
curl -fL --progress-bar --url "$url" -o "$WORK/Cicada.zip" || die "The download failed."
got="$(shasum -a 256 "$WORK/Cicada.zip" | cut -d' ' -f1)"
[ "$got" = "$sha" ] || die "The download doesn't match the release's checksum — nothing was installed."
ok "Checksum matches"

ditto -x -k "$WORK/Cicada.zip" "$WORK/unzipped"
[ -d "$WORK/unzipped/Cicada.app" ] || die "The archive holds no Cicada.app."
codesign --verify --strict --deep "$WORK/unzipped/Cicada.app" 2>/dev/null \
  || die "The app's signature doesn't verify — nothing was installed."
plist="$WORK/unzipped/Cicada.app/Contents/Info.plist"
got_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist" 2>/dev/null || true)"
[ "$got_version" = "$version" ] || die "The app inside is version ${got_version:-unknown}, not $version — nothing was installed."

DEST_DIR="${CICADA_INSTALL_DIR:-$HOME/Applications}"
if ! mkdir -p "$DEST_DIR" 2>/dev/null || [ ! -w "$DEST_DIR" ]; then
  DEST_DIR="/Applications"
  [ -w "$DEST_DIR" ] || die "Neither ~/Applications nor /Applications can be written."
fi
DEST="$DEST_DIR/Cicada.app"

# Stage the new copy beside the old one first (same folder, so the swap below is two renames), so a failed copy
# never leaves this Mac without Cicada.
STAGED="$DEST_DIR/.Cicada.app.new"
rm -rf "$STAGED"
ditto "$WORK/unzipped/Cicada.app" "$STAGED" || { rm -rf "$STAGED"; die "Couldn't copy Cicada into $DEST_DIR."; }

# An update the app itself staged would race this install on quit; drop it first.
rm -rf "$DEST_DIR/.Cicada.app.update" "$DEST_DIR/.Cicada.app.update.json"
# Only the copy being replaced is asked to quit (SIGTERM is the app's own ⌘Q); a Cicada running from anywhere else
# is left alone.
RUNNING="$DEST/Contents/MacOS/CicadaApp"
if pgrep -f "^$RUNNING" >/dev/null 2>&1; then
  say "Quitting the running Cicada…"
  pkill -TERM -f "^$RUNNING" 2>/dev/null || true
  for _ in $(seq 1 10); do pgrep -f "^$RUNNING" >/dev/null 2>&1 || break; sleep 1; done
fi

# The background service runs from the installed copy: stop it for the swap and start it again on the new one.
PLIST="${CICADA_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}/com.cicada.backend.plist"
SERVICE="gui/$(id -u)/com.cicada.backend"
stopped=0
if [ -f "$PLIST" ] && launchctl bootout "$SERVICE" 2>/dev/null; then
  stopped=1
fi
restart_service() {
  [ "$stopped" = 1 ] || return 0
  for _ in 1 2 3; do launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null && return 0; sleep 1; done
  printf '\033[33m!\033[0m %s\n' "The background service didn't start again; open Cicada and turn it on in Settings → General."
}

if [ -d "$DEST" ]; then
  say "Moving the previous Cicada.app to the Trash…"
  mkdir -p "$HOME/.Trash"
  mv "$DEST" "$HOME/.Trash/Cicada $(date '+%Y-%m-%d %H.%M.%S').app" || { restart_service; die "Couldn't move the old Cicada aside."; }
fi
mv "$STAGED" "$DEST" || { restart_service; die "Couldn't move the new Cicada into place (it is at $STAGED)."; }
restart_service
# curl sets no quarantine flag; clear one in case the zip came another way.
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
ok "Installed Cicada $version at $DEST"

if [ "${CICADA_NO_OPEN:-0}" != "1" ]; then
  open "$DEST"
  ok "Opened Cicada — it will walk you through setup."
fi
