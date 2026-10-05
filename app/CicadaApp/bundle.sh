#!/usr/bin/env bash
# Build CicadaApp as a proper .app bundle.
#
# Why this exists: `swift run` produces a bare executable with no Info.plist.
# macOS treats such a process as a command-line tool, so its window never
# becomes a normal *key* window — which silently breaks mouse-click delivery to
# the embedded WKWebView graph (you can hover a node but clicking it does
# nothing) and keyboard focus in text fields. Wrapping the binary in a real
# .app bundle gives it proper activation/key-window behaviour.
#
# Usage:
#   ./bundle.sh           # build (debug) + assemble Cicada.app, print its path
#   ./bundle.sh --release # optimized build
#   ./bundle.sh --run     # build, assemble, and launch
#   ./bundle.sh --release --with-backend
#                         # the installable app (G182): carries its own Python, code, git and
#                         # embedding model (scripts/release/build-backend.sh), is stamped
#                         # CicadaDistribution=release instead of a checkout path, and is signed
#                         # inside out (scripts/release/sign-app.sh — ad hoc unless
#                         # CICADA_SIGN_IDENTITY names a Developer ID). Never used by make dev,
#                         # install_app.sh or the dev auto-updater, whose builds are unchanged.
#   CICADA_PREBUILT_BACKEND=<dir> reuses an already assembled backend instead of building one.
set -euo pipefail

cd "$(dirname "$0")"

CONFIG="debug"
RUN=0
WITH_BACKEND=0
for arg in "$@"; do
  case "$arg" in
    --release) CONFIG="release" ;;
    --run) RUN=1 ;;
    --with-backend) WITH_BACKEND=1 ;;
  esac
done
if [ "$WITH_BACKEND" = "1" ] && [ "$CONFIG" != "release" ]; then
  echo "✗ --with-backend builds the installable app; pass --release too" >&2
  exit 2
fi

echo "→ swift build ($CONFIG)…"
swift build -c "$CONFIG"

BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"
APP="$BIN_DIR/Cicada.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$BIN_DIR/CicadaApp" "$APP/Contents/MacOS/CicadaApp"
# The app icon: the book and glasses on a graphite plate, built by Art/AppIcon/make-icon.swift from the Aseprite art in
# docs/design/cicada-icon/v4/ (rerun that script after editing the art; the .icns is committed so a build needs no tools).
# Info.plist names it (CFBundleIconFile).
cp Art/AppIcon/Cicada.icns "$APP/Contents/Resources/Cicada.icns"
# Bundle.cicadaResources (Utilities/ResourceBundle.swift) resolves the SwiftPM resource bundle relative to the executable —
# SwiftPM's own Bundle.module would probe the build dir under ~/Documents first and trip a TCC prompt —
# so it must sit next to the binary inside Contents/MacOS.
if [ -d "$BIN_DIR/CicadaApp_CicadaApp.bundle" ]; then
  RESBUNDLE="$APP/Contents/MacOS/CicadaApp_CicadaApp.bundle"
  cp -R "$BIN_DIR/CicadaApp_CicadaApp.bundle" "$APP/Contents/MacOS/"
  # SwiftPM emits this as a FLAT bundle (Resources/ at its root, no
  # Contents/Info.plist). That's fine for Bundle.module's own lookup, but
  # `codesign` walks the whole app tree for anything *shaped* like a bundle
  # (any `.bundle` dir) and refuses to sign the app at all — deep or not —
  # once it finds one with no Info.plist ("bundle format unrecognized,
  # invalid, or unsuitable"). Re-nest it as a minimal real bundle
  # (Contents/Info.plist + Contents/Resources) purely so codesign accepts
  # it; Foundation's Bundle(path:) reads both the flat and Contents/ layouts
  # so this doesn't change what Bundle.module resolves at runtime.
  if [ -d "$RESBUNDLE/Resources" ] && [ ! -f "$RESBUNDLE/Contents/Info.plist" ]; then
    mkdir -p "$RESBUNDLE/Contents"
    mv "$RESBUNDLE/Resources" "$RESBUNDLE/Contents/Resources"
    cat > "$RESBUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.rorosaga.cicada.resources</string>
  <key>CFBundlePackageType</key><string>BNDL</string>
</dict>
</plist>
PLIST
  fi
fi

# LSMinimumSystemVersion matches Package.swift's .macOS(.v14) floor (G137 R-M7; PlatformFloorTests holds the pair).
# Track I T5 (R-IA25): offered in Open With and as a Dock drop
# target, never the default opener (LSHandlerRank Alternate).
# Round-4 D2 (R-FA11): the calendar prompt's words. macOS 14+ asks with the full-access key; the legacy key covers an
# older system and is harmless. Nothing is asked until the person clicks Connect in Settings → Integrations.
# G154: the contacts prompt's words; nothing is asked until the person clicks Connect in Settings → Integrations.
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>CicadaApp</string>
  <key>CFBundleIdentifier</key><string>com.rorosaga.cicada</string>
  <key>CFBundleName</key><string>Cicada</string>
  <key>CFBundleDisplayName</key><string>Cicada</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>Cicada</string>
  <key>CFBundleShortVersionString</key><string>0.0.0</string>
  <key>CFBundleVersion</key><string>0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>Cicada reads your calendar events so your meetings and plans become part of your memory, kept in plain files on this Mac.</string>
  <key>NSCalendarsUsageDescription</key><string>Cicada reads your calendar events so your meetings and plans become part of your memory, kept in plain files on this Mac.</string>
  <key>NSContactsUsageDescription</key><string>Cicada reads your contacts to recognise the people you already talk about — where to look up their details, and their photo. It never adds anyone new, and it stays on this Mac.</string>
  <key>NSAppleEventsUsageDescription</key><string>Cicada reads your notes in Apple Notes when you sync them, so what you write there becomes part of your memory, kept in plain files on this Mac. It never changes a note.</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>Chat export</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>public.zip-archive</string>
        <string>public.json</string>
        <string>public.html</string>
        <string>public.folder</string>
      </array>
    </dict>
  </array>
</dict>
</plist>
PLIST

# G182 — the version is the repo's one VERSION file (the API and the MCP server read the same file); the build number
# is distinct and only ever grows: CI passes CICADA_BUILD_NUMBER (its run number), a local build counts commits.
VERSION_FILE="$(cd ../.. && pwd)/VERSION"
APP_VERSION="$(head -n1 "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]')"
[ -n "$APP_VERSION" ] || { echo "✗ no version in $VERSION_FILE" >&2; exit 1; }
BUILD_NUMBER="${CICADA_BUILD_NUMBER:-$(git rev-list --count HEAD 2>/dev/null || echo 0)}"
plutil -replace CFBundleShortVersionString -string "$APP_VERSION" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$BUILD_NUMBER" "$APP/Contents/Info.plist"

if [ "$WITH_BACKEND" = "1" ]; then
  # G182 — the installable app. No checkout path is stamped: the app finds its backend inside itself
  # (CicadaRuntime), and its memory lives in ~/cicada/memory, never in the bundle.
  REPO_ROOT_DIR="$(cd ../.. && pwd)"
  # Not CICADA_BACKEND_DIR: the installed app's launchers export that name, so a build started from anything the
  # backend spawned would silently reuse the installed backend.
  BACKEND_DIR="${CICADA_PREBUILT_BACKEND:-$PWD/.build/release-backend/backend}"
  if [ -z "${CICADA_PREBUILT_BACKEND:-}" ]; then
    "$REPO_ROOT_DIR/scripts/release/build-backend.sh" "$BACKEND_DIR"
  fi
  [ -x "$BACKEND_DIR/bin/cicada-backend" ] || { echo "✗ no assembled backend at $BACKEND_DIR" >&2; exit 1; }
  ditto "$BACKEND_DIR" "$APP/Contents/Resources/backend"
  plutil -replace CicadaDistribution -string release "$APP/Contents/Info.plist"
  # Symbols are 60% of the binary and nothing on a tester's Mac reads them.
  strip -x "$APP/Contents/MacOS/CicadaApp"
  "$REPO_ROOT_DIR/scripts/release/sign-app.sh" "$APP"
  echo "✓ built $APP ($APP_VERSION, build $BUILD_NUMBER, release with backend, $(du -sh "$APP" | cut -f1))"
  exit 0
fi

# Stamp the checkout path that produced this bundle (G88). BackendProcess's
# installRoot() prefers this over its .build/DerivedData path heuristic, so
# an installed ~/Applications/Cicada.app resolves the memory dir + Connect
# page's copy-pasteable MCP commands against the repo that built it instead
# of guessing ~/cicada (which can exist and resolve plausibly-but-wrongly).
# Computed fresh on every build, so moving the repo just means "rebuild" —
# nothing here hardcodes today's path.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ]; then
  plutil -replace CicadaRepoRoot -string "$REPO_ROOT" "$APP/Contents/Info.plist"
fi

echo "✓ built $APP ($APP_VERSION, build $BUILD_NUMBER)"
if [ "$RUN" = "1" ]; then
  echo "→ launching…"
  open "$APP"
fi
