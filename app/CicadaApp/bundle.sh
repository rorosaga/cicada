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
set -euo pipefail

cd "$(dirname "$0")"

CONFIG="debug"
RUN=0
for arg in "$@"; do
  case "$arg" in
    --release) CONFIG="release" ;;
    --run) RUN=1 ;;
  esac
done

echo "→ swift build ($CONFIG)…"
swift build -c "$CONFIG"

BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"
APP="$BIN_DIR/Cicada.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$BIN_DIR/CicadaApp" "$APP/Contents/MacOS/CicadaApp"
# Bundle.module resolves the SwiftPM resource bundle relative to the executable,
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
  <key>CFBundleShortVersionString</key><string>0.2</string>
  <key>CFBundleVersion</key><string>0.2</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
PLIST

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

echo "✓ built $APP"
if [ "$RUN" = "1" ]; then
  echo "→ launching…"
  open "$APP"
fi
