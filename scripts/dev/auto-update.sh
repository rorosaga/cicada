#!/usr/bin/env bash
# Keep this Mac on the latest `dev`: when origin/dev moves, fast-forward this
# checkout, refresh the Python env if its lock changed, restart the launchd
# backend, and rebuild + reinstall ~/Applications/Cicada.app (relaunched only
# if it was running). A developer convenience, run every few minutes by the
# launchd job `scripts/dev/install-auto-update.sh` installs — never by the app.
#
# On Linux (a headless server, G181) the same script runs from a systemd user
# timer the same installer writes: it restarts the systemd user unit
# `scripts/install-backend-service.sh` installs (`CICADA_BACKEND_UNIT`, default
# cicada-backend.service) instead of the launchd agent, keeps the venv's shape
# (a server env stays a server env: `scripts/sync-server-env.sh`), and has no
# app to build — the stamp moves once the backend side is done.
#
# It never touches work in progress: it does nothing unless this checkout is ON
# `dev`, has no tracked changes, and can fast-forward. Untracked files are fine.
# It also waits out Sleep, but only what is in flight: while the backend reports a
# running cycle (a paused run's upkeep tail included), a write window or a drain still
# reading, it changes nothing and the next tick retries. A paused run waiting on
# Continue (a top-level `paused` block, its drain idle or null) is NOT in flight: its
# record is a sidecar outside the process (`sleep_paused`, `$CICADA_HOME/sleep/<bank>/
# run.json`) that a restart leaves as it is, an armed continue-after-reset re-arms
# from it, and Continue rebuilds the run from it. Deferring on it held every update
# for a whole day after one failed scheduled run (2026-10-17). CICADA_AUTOUPDATE_FORCE=1
# skips that wait.
#
# A backend that answers NOTHING is not a busy one (2026-11-26: a Sleep run spun on the
# event loop for ~14 hours, every tick deferred, and the fix already on dev never landed).
# Only an ask that TIMED OUT counts as silence (curl exit 28); an answer of any kind (an
# HTTP error status, an unreadable body, "running"), a refused connection, a missing token
# or any other curl failure ends the stretch. The stretch is kept in logs/.auto-update-silent
# as "<first> <last>" (epoch seconds of the first and the latest unanswered tick), because
# every tick is a fresh process. Silence is counted only across ticks that really asked: a
# gap of more than 15 minutes between two unanswered ticks (a closed lid, a timer that did
# not fire, a checkout that failed a guard and asked nothing) starts the stretch over, so
# one unanswered tick before an 8-hour sleep and one after is 0 minutes of silence, not 8
# hours. A stretch that reaches CICADA_AUTOUPDATE_SILENT_MINUTES (default 30) marks the
# backend frozen: the script sends SIGUSR1 to the backend's OWN pid (launchd's `pid =` for
# com.cicada.backend; the systemd unit's MainPID on Linux; never a name match) so it writes
# every thread's Python stack to its error log (api/services/stack_dump.py), waits 2 s, and
# restarts it through the usual door even if no code moved, logging "backend restarted: it
# had been silent for N minutes". The checkout guards still come first (a checkout that
# fails them restarts nothing); fetch, fast-forward, dependency sync and the app build then
# run as for any update. The record is cleared by that restart, so a backend that comes
# back frozen is restarted again only after another full stretch. A "running" answer is never
# interrupted however long the run is, and a single timeout still defers. A run the restart
# cut comes back paused (reason restart) by the backend's own recovery; this script does
# nothing about it. This bound (30 minutes, no read of a drain's run.json) is deliberately
# shorter than the release app's (ruling 66: three looks over two hours, no running record
# touched in them); see docs/goals/TODO.md, ruling 66 amended 2026-11-26.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
OS_NAME="$(uname -s)"
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

# On Linux the backend's port and home are the unit's own (install-backend-service.sh writes
# `--port N` and CICADA_HOME into it): ask that backend, not a default, so a server on
# another port is never restarted under a running Sleep. The job's environment still wins.
if [ "$OS_NAME" = "Linux" ]; then
  unit="${CICADA_BACKEND_UNIT:-cicada-backend.service}"
  unit_text="$(systemctl --user cat "$unit" 2>/dev/null || true)"
  if [ -z "${CICADA_PORT:-}" ]; then
    unit_port="$(printf '%s\n' "$unit_text" | sed -n 's/^ExecStart=.* --port \([0-9][0-9]*\).*/\1/p' | head -n1)"
    [ -n "$unit_port" ] && CICADA_PORT="$unit_port"
  fi
  if [ -z "${CICADA_HOME:-}" ]; then
    unit_home="$(printf '%s\n' "$unit_text" | sed -n 's/^Environment="\{0,1\}CICADA_HOME=\([^"]*\)"\{0,1\}$/\1/p' | head -n1)"
    [ -n "$unit_home" ] && CICADA_HOME="$unit_home"
  fi
fi

# Ask the backend before anything moves: the running process lazily imports modules
# from this checkout, so a fast-forward under it mixes versions, and a restart kills
# the batch in progress. "Nothing is listening" (curl exit 7) or no token means nothing
# to protect. A slow backend (timeout), any other failure, an HTTP error or an
# unreadable answer is a busy one: defer and retry next tick. Return codes: 0 busy,
# 1 nothing to protect, 2 no answer at all (a timeout; `silent_secs` says for how long).
SILENT_FILE="$LOG_DIR/.auto-update-silent"
SILENT_MINUTES="${CICADA_AUTOUPDATE_SILENT_MINUTES:-30}"
case "$SILENT_MINUTES" in ''|*[!0-9]*|0) SILENT_MINUTES=30 ;; esac
SILENT_LIMIT=$((SILENT_MINUTES * 60))
SILENT_MAX_GAP=900   # three ticks: a longer gap between two unanswered asks is not silence we saw
silent_secs=0
frozen=0
silence_clear() { rm -f "$SILENT_FILE" "$SILENT_FILE.tmp"; }
silence_note() {
  local now first last
  now="$(date +%s)"
  read -r first last < "$SILENT_FILE" 2>/dev/null || { first=""; last=""; }
  if ! [[ "$first" =~ ^[0-9]+$ && "$last" =~ ^[0-9]+$ ]] || [ "$first" -gt "$last" ] || [ "$last" -gt "$now" ] \
     || [ $((now - last)) -gt "$SILENT_MAX_GAP" ]; then
    first="$now"
  fi
  printf '%s %s\n' "$first" "$now" > "$SILENT_FILE.tmp" && mv "$SILENT_FILE.tmp" "$SILENT_FILE"
  silent_secs=$((now - first))
}
sleep_busy() {
  local token body port="${CICADA_PORT:-8000}"
  token="$(tr -d '[:space:]' < "${CICADA_HOME:-$HOME/.cicada}/api_token" 2>/dev/null)" || { silence_clear; return 1; }
  [ -n "$token" ] || { silence_clear; return 1; }
  local rc=0
  body="$(curl -sf -m 10 -H "Authorization: Bearer $token" "http://127.0.0.1:$port/sleep/status" 2>/dev/null)" || rc=$?
  [ "$rc" = 7 ] && { silence_clear; return 1; }
  [ "$rc" = 28 ] && { silence_note; return 2; }
  silence_clear   # it answered (an HTTP error too), or failed in a way that is not silence
  [ "$rc" = 0 ] || return 0
  printf '%s' "$body" | /usr/bin/python3 -c '
import json, sys
try:
    b = json.load(sys.stdin)
    d = b.get("drain") if isinstance(b.get("drain"), dict) else {}
    busy = (b.get("status") == "running" or b.get("writing") is True or b.get("inboxTidy") is True
            or (d.get("active") is True and d.get("finished") is not True))
except Exception:
    busy = True
sys.exit(0 if busy else 1)' 2>/dev/null
}

# The backend's own pid, from the service manager (never a process-name match: a scratch or test
# backend must not be signalled). Empty when it cannot be found.
backend_pid() {
  local out pid=""
  if [ "$OS_NAME" = "Linux" ]; then
    out="$(systemctl --user show -p MainPID "$unit" 2>/dev/null)" || out=""
    pid="$(printf '%s\n' "$out" | sed -n 's/^MainPID=\([0-9][0-9]*\)$/\1/p' | head -n1)"
  else
    out="$(launchctl print "gui/$(id -u)/com.cicada.backend" 2>/dev/null)" || out=""
    pid="$(printf '%s\n' "$out" | sed -n 's/^[[:space:]]*pid = \([0-9][0-9]*\)[[:space:]]*$/\1/p' | head -n1)"
  fi
  [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null && printf '%s' "$pid"
  return 0
}
# SIGUSR1: the backend writes every thread's Python stack to its error log. Never fails the tick.
ask_for_stacks() {
  local pid
  pid="$(backend_pid)"
  if [ -n "$pid" ] && kill -USR1 "$pid" 2>/dev/null; then
    log "asked the silent backend (pid $pid) for its stacks (SIGUSR1; they land in its error log)"
    sleep 2
  else
    log "no stack dump: the silent backend's pid was not found"
  fi
  return 0
}
# Restart the backend through the door it is run from. 0 restarted, 1 the restart failed, 2 no such service.
restart_backend() {
  local what="backend restarted"
  [ "$frozen" = 1 ] && what="backend restarted: it had been silent for $((silent_secs / 60)) minutes"
  if [ "$OS_NAME" = "Linux" ]; then
    if [ -z "$unit_text" ]; then
      [ "$frozen" = 1 ] && log "fail: the backend is silent but $unit is not loaded; nothing restarted"
      return 2
    fi
    [ "$frozen" = 1 ] && ask_for_stacks
    if systemctl --user restart "$unit"; then
      log "$what"; [ "$frozen" = 1 ] && silence_clear
      return 0
    fi
    log "fail: restart $unit"
    return 1
  fi
  if ! launchctl print "gui/$(id -u)/com.cicada.backend" >/dev/null 2>&1; then
    [ "$frozen" = 1 ] && log "fail: the backend is silent but com.cicada.backend is not loaded; nothing restarted"
    return 2
  fi
  [ "$frozen" = 1 ] && ask_for_stacks
  if launchctl kickstart -k "gui/$(id -u)/com.cicada.backend"; then
    log "$what"; [ "$frozen" = 1 ] && silence_clear
    return 0
  fi
  log "fail: restart com.cicada.backend"
  return 1
}

if [ "${CICADA_AUTOUPDATE_FORCE:-}" != "1" ]; then
  sleep_busy; busy_rc=$?
  if [ "$busy_rc" = 0 ]; then
    log "deferred: Sleep is running"
    exit 0
  elif [ "$busy_rc" = 2 ]; then
    if [ "$silent_secs" -ge "$SILENT_LIMIT" ]; then
      frozen=1   # the stacks are asked for, and the restart done, only once the checkout guards have passed
    else
      log "deferred: Sleep is running (the backend has not answered for $((silent_secs / 60)) of $SILENT_MINUTES minutes)"
      exit 0
    fi
  fi
fi

if ! git fetch -q origin dev; then
  log "skip: fetch failed"
  [ "$frozen" = 1 ] && restart_backend   # nothing to update, but a frozen backend is restarted all the same
  exit 0
fi
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
if [ "$installed" = "$target" ]; then
  # Nothing to install, but a frozen backend is restarted all the same.
  if [ "$frozen" = 1 ]; then restart_backend; [ "$?" = 1 ] && exit 1; fi
  exit 0
fi
log "update ${installed:0:7} -> ${target:0:7}"

# Rebuild only what moved: a docs-only merge must not cost a release build.
# No usable stamp (first run, or history rewritten) means everything moved.
known=1
{ [ -n "$installed" ] && git cat-file -e "$installed^{commit}" 2>/dev/null; } || known=0
moved() { [ "$known" = 0 ] || ! git diff --quiet "$installed" "$target" -- "$@"; }

if [ "$OS_NAME" = "Linux" ]; then
  # A venv without the larger search model's runtime was made by sync-server-env.sh
  # (install-server.sh, Homebrew); a full `uv sync` would pull torch and CUDA into it.
  # The stamp moves only when the sync and the restart both worked: a failure keeps it, so
  # the next tick (the code already fast-forwarded) tries both again.
  ok=1
  if moved api/pyproject.toml api/uv.lock; then
    if compgen -G "api/.venv/lib/python*/site-packages/sentence_transformers" >/dev/null; then
      log "python deps may have changed: uv sync"
      (cd api && uv sync -q) >> "$LOG_DIR/auto-update.log" 2>&1 || { log "fail: uv sync"; ok=0; }
    else
      log "python deps may have changed: sync-server-env.sh"
      bash scripts/sync-server-env.sh -q >> "$LOG_DIR/auto-update.log" 2>&1 || { log "fail: sync-server-env.sh"; ok=0; }
    fi
  fi
  if [ "$ok" = 1 ] && { [ "$frozen" = 1 ] || { moved api ":(exclude)api/tests" mcp && [ -n "$unit_text" ]; }; }; then
    restart_backend; [ "$?" = 1 ] && ok=0
  fi
  if [ "$ok" = 0 ]; then
    log "installed stamp kept at ${installed:0:7}; the next tick retries"
    exit 1
  fi
  echo "$target" > "$STAMP"
  log "no app on Linux; installed stamp moved to ${target:0:7}"
  exit 0
fi

if moved api/pyproject.toml api/uv.lock; then
  log "python deps may have changed: uv sync"
  (cd api && uv sync -q) >> "$LOG_DIR/auto-update.log" 2>&1 || log "fail: uv sync"
fi

# Only runtime code restarts the backend: a test-only or benchmark-only merge does not (a frozen one always is).
if [ "$frozen" = 1 ] || moved api ":(exclude)api/tests" mcp; then
  restart_backend
fi

if ! moved app; then
  echo "$target" > "$STAMP"
  log "no app changes; installed stamp moved to ${target:0:7}"
  exit 0
fi
flags=(--release)
pgrep -x CicadaApp >/dev/null 2>&1 && flags+=(--relaunch)
# Unattended: install_app.sh bounds codesign, so a key prompt nobody answers skips this update instead of hanging.
if CICADA_UNATTENDED=1 app/CicadaApp/install_app.sh "${flags[@]}" >> "$LOG_DIR/auto-update.log" 2>&1; then
  echo "$target" > "$STAMP"
  log "app installed (${target:0:7})"
else
  log "fail: app build/install — the previous app is still installed"
fi
