#!/usr/bin/env bash
# Install (or remove, with --uninstall) the job that runs
# scripts/dev/auto-update.sh every 5 minutes for THIS checkout: a launchd job on
# a Mac, a systemd user timer on Linux (a headless server, G181). Developer
# tooling only; a person's install never needs it.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

if [ "$(uname -s)" = "Linux" ]; then
  # cicada-dev-autoupdate.timer starts cicada-dev-autoupdate.service (oneshot) on
  # every 5-minute mark; Persistent=true runs a mark the machine was off through
  # once at boot. SYSTEMD_USER_DIR is the test override, as in install-backend-service.sh.
  UNIT_DIR="${SYSTEMD_USER_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
  NAME="cicada-dev-autoupdate"
  systemctl --user disable --now "$NAME.timer" 2>/dev/null || true
  if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$UNIT_DIR/$NAME.timer" "$UNIT_DIR/$NAME.service"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "Removed $NAME.timer"
    exit 0
  fi
  case "$REPO" in
    *'"'*|*$'\n'*|*'\'*|*' '*) echo "Won't write a unit for a path with a space, quote, backslash or newline: $REPO" >&2; exit 2 ;;
  esac
  # The user manager's PATH is bare: uv usually lives in ~/.local/bin, where its installer puts it.
  UV_DIR="$(dirname "$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")")"
  mkdir -p "$UNIT_DIR" "$REPO/logs"
  cat > "$UNIT_DIR/$NAME.service" <<UNIT
# Written by Cicada's scripts/dev/install-auto-update.sh — re-run it rather than editing this file.
[Unit]
Description=Cicada dev auto-update (${REPO//%/%%})

[Service]
Type=oneshot
WorkingDirectory=${REPO//%/%%}
Environment="PATH=$UV_DIR:/usr/local/bin:/usr/bin:/bin"
ExecStart=/bin/bash ${REPO//%/%%}/scripts/dev/auto-update.sh
StandardOutput=append:${REPO//%/%%}/logs/auto-update.systemd.log
StandardError=append:${REPO//%/%%}/logs/auto-update.systemd.log
UNIT
  cat > "$UNIT_DIR/$NAME.timer" <<UNIT
# Written by Cicada's scripts/dev/install-auto-update.sh — re-run it rather than editing this file.
[Unit]
Description=Check origin/dev every 5 minutes (${REPO//%/%%})

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now "$NAME.timer"
  systemctl --user start --no-block "$NAME.service"   # a first run now, like launchd's RunAtLoad
  echo "Installed $NAME.timer — checks origin/dev every 5 minutes; log: $REPO/logs/auto-update.log"
  exit 0
fi

LABEL="com.cicada.dev-autoupdate"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$PLIST"
  echo "Removed $LABEL"
  exit 0
fi

# Started through the checkout's venv Python, not /bin/bash: under launchd a
# process is refused files in a protected folder (a checkout under ~/Documents)
# unless macOS already let it in, and that Python is the one the backend job
# already runs as. bash, git and swift then run as its children.
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
  <array>
    <string>$REPO/api/.venv/bin/python</string><string>-c</string>
    <string>import subprocess, sys; sys.exit(subprocess.call(["/bin/bash", sys.argv[1]]))</string>
    <string>$REPO/scripts/dev/auto-update.sh</string>
  </array>
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
