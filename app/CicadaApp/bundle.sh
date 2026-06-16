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
  cp -R "$BIN_DIR/CicadaApp_CicadaApp.bundle" "$APP/Contents/MacOS/"
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

echo "✓ built $APP"
if [ "$RUN" = "1" ]; then
  echo "→ launching…"
  open "$APP"
fi
