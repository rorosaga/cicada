#!/usr/bin/env bash
# Install (or remove, with --uninstall) the launchd job that runs
# scripts/dev/auto-update.sh every 5 minutes for THIS checkout. Developer
# tooling only; a person's install never needs it.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.cicada.dev-autoupdate"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$PLIST"
  echo "Removed $LABEL"
  exit 0
fi

# launchd's PATH is bare: git, swift and codesign live in /usr/bin, uv usually in Homebrew.
UV_DIR="$(dirname "$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)")"
mkdir -p "$(dirname "$PLIST")" "$REPO/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO/scripts/dev/auto-update.sh</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$UV_DIR:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$REPO/logs/auto-update.launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/auto-update.launchd.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $LABEL — checks origin/dev every 5 minutes; log: $REPO/logs/auto-update.log"
