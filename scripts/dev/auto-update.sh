#!/usr/bin/env bash
# Keep this Mac on the latest `dev`: when origin/dev moves, fast-forward this
# checkout, refresh the Python env if its lock changed, restart the launchd
# backend, and rebuild + reinstall ~/Applications/Cicada.app (relaunched only
# if it was running). A developer convenience, run every few minutes by the
# launchd job `scripts/dev/install-auto-update.sh` installs — never by the app.
#
# It never touches work in progress: it does nothing unless this checkout is ON
# `dev`, has no tracked changes, and can fast-forward. Untracked files are fine.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_DIR/auto-update.log"; }

# One run at a time: a release build can outlast the interval.
LOCK="$LOG_DIR/.auto-update.lock"
find "$LOCK" -maxdepth 0 -mmin +90 -exec rmdir {} \; 2>/dev/null   # a run killed hard leaves it behind
if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
[ "$branch" = "dev" ] || exit 0
git diff --quiet && git diff --cached --quiet || { log "skip: tracked changes on dev"; exit 0; }
git fetch -q origin dev || { log "skip: fetch failed"; exit 0; }
head="$(git rev-parse HEAD)"
target="$(git rev-parse origin/dev)"
if [ "$head" != "$target" ]; then
  git merge-base --is-ancestor "$head" "$target" || { log "skip: dev has diverged from origin/dev"; exit 0; }
  git merge -q --ff-only "$target" || { log "fail: fast-forward refused"; exit 1; }
fi

# What was last INSTALLED, not what was checked out: a hand `git pull` on dev
# must still end in a rebuild.
STAMP="$LOG_DIR/.auto-update-installed"
installed="$(cat "$STAMP" 2>/dev/null || true)"
[ "$installed" = "$target" ] && exit 0
log "update ${installed:0:7} -> ${target:0:7}"

# Rebuild only what moved: a docs-only merge must not cost a release build.
# No usable stamp (first run, or history rewritten) means everything moved.
known=1
{ [ -n "$installed" ] && git cat-file -e "$installed^{commit}" 2>/dev/null; } || known=0
moved() { [ "$known" = 0 ] || ! git diff --quiet "$installed" "$target" -- "$@"; }

if moved api/pyproject.toml api/uv.lock; then
  log "python deps may have changed: uv sync"
  (cd api && uv sync -q) >> "$LOG_DIR/auto-update.log" 2>&1 || log "fail: uv sync"
fi

if moved api mcp && launchctl print "gui/$(id -u)/com.cicada.backend" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/com.cicada.backend" && log "backend restarted"
fi

if ! moved app; then
  echo "$target" > "$STAMP"
  log "no app changes; installed stamp moved to ${target:0:7}"
  exit 0
fi
flags=(--release)
pgrep -x CicadaApp >/dev/null 2>&1 && flags+=(--relaunch)
if app/CicadaApp/install_app.sh "${flags[@]}" >> "$LOG_DIR/auto-update.log" 2>&1; then
  echo "$target" > "$STAMP"
  log "app installed (${target:0:7})"
else
  log "fail: app build/install — the previous app is still installed"
fi
