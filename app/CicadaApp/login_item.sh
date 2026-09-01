#!/usr/bin/env bash
# Toggle "Open Cicada at login" via macOS's own Login Items list (System
# Events), NOT a hand-rolled LaunchAgent plist for the GUI app itself.
#
# Why not a LaunchAgent, which is what G88 asked to consider first: the
# backend already has one (com.cicada.backend) because it's a headless
# service with nothing to show in a "Login Items" UI. A full Cocoa app is
# different — launchd-launching a GUI app via a LaunchAgent plist is the OLD
# way of doing login items, and modern macOS (13+) surfaces it in
# System Settings > General > Login Items under a separate "Allow in the
# Background" section rather than the normal per-app toggle every user
# already knows. That's a second, unfamiliar mechanism sitting next to the
# one macOS itself provides — the "fights the native UI" case G88 flagged.
#
# `make login-item` instead adds Cicada to the SAME list System Events
# exposes — exactly what dragging Cicada.app into that pane by hand does.
# One normal entry, one normal toggle, already visible and already removable
# in the standard Login Items UI.
#
# First use of System Events login items from a given terminal/app usually
# prompts a one-time macOS "wants to control System Events" Automation
# permission dialog — approve it once, same as any other AppleScript
# automation.
#
# Usage: ./login_item.sh add | remove
set -euo pipefail

APP="$HOME/Applications/Cicada.app"
ACTION="${1:-}"

case "$ACTION" in
  add)
    if [ ! -d "$APP" ]; then
      echo "Cicada.app is not installed at $APP — run 'make install-app' first." >&2
      exit 1
    fi
    osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP\", hidden:false, name:\"Cicada\"}"
    echo "Added Cicada to Login Items (System Settings > General > Login Items)."
    echo "First run may prompt for Automation access to System Events — approve it once."
    ;;
  remove)
    osascript -e 'tell application "System Events" to delete login item "Cicada"' 2>/dev/null || true
    echo "Removed Cicada from Login Items (if it was there)."
    ;;
  *)
    echo "Usage: $0 add|remove" >&2
    exit 2
    ;;
esac
