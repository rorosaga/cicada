#!/usr/bin/env bash
# Model-check the video queue's lease lifecycle. Usage: run.sh [--breaks | --deep | --all | --only NAME]
#   (no flag)    the code as it is, the open findings, and the proposed fixes
#   --breaks     the scratch breaks that prove each passing property can fail
#   --deep       the two-video safety run that backs the one-video projection (longer than 25 minutes)
#   --only NAME  one check from any of those lists
# Exit 0 when every check ends the way EXPECT says; traces land in $OUT. Exit 3 when the covered code changed
# since the sync commit (coverage.py); ALLOW_DRIFT=1 runs anyway while you bring the model in line.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TLA_VERSION="v1.7.4"
TLA_SHA256="936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TOOLS="${CICADA_TLA_TOOLS:-$HOME/.cache/cicada-tla}/$TLA_VERSION"
JAR="$TOOLS/tla2tools.jar"
OUT="${OUT:-${TMPDIR:-/tmp}/verify-video-queue}"
WORKERS="${WORKERS:-4}"
MODE="${1:-}"

# name|expected: "pass", the name of the violated property, or "temporal" for a liveness violation.
EXPECT_DEFAULT="
code-safety|pass
code-liveness|pass
fixed-safety|pass
fixed-churn|pass
F1-release-by-non-holder|ReleaseOnlyByHolder
F2-stale-saved-drops-row|NoLostRow
F3-older-record-closes-row|DoneIsSupported
F3-older-record-ends-lease|RecordByOtherCorruptsNothing
F4-active-session-keeps-lease|temporal
"
EXPECT_BREAKS="
break-lapse_ignores_lease|NoDoubleClaim
break-nolock|NoDoubleClaim
break-no_lapse|temporal
break-no_fail_expiry|temporal
break-record_ignores_session|RecordByOtherCorruptsNothing
break-stays_counts_attempt|Idempotent
break-settle_ignores_holding|NoBurnWhileHeld
break-settle_ignores_records|NoBurnWhenSatisfied
break-claim_takes_failed|FailedReturnsOnlyByPerson
break-put_restarts_claimed|NoLeaseTakenAway
"
EXPECT_DEEP="
deep-safety|pass
"

case "$MODE" in
  "") EXPECT="$EXPECT_DEFAULT" ;;
  --breaks) EXPECT="$EXPECT_BREAKS" ;;
  --deep) EXPECT="$EXPECT_DEEP" ;;
  --all) EXPECT="$EXPECT_DEFAULT$EXPECT_BREAKS$EXPECT_DEEP" ;;
  --only) EXPECT="$(printf '%s\n' "$EXPECT_DEFAULT$EXPECT_BREAKS$EXPECT_DEEP" | grep "^${2:-}|" || true)"
          [ -n "$EXPECT" ] || { echo "no check named '${2:-}'" >&2; exit 2; } ;;
  *) echo "usage: run.sh [--breaks | --deep | --all | --only NAME]" >&2; exit 2 ;;
esac

find_java() {
  for candidate in "${JAVA:-}" /opt/homebrew/opt/openjdk@17/bin/java "$(command -v java || true)"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" -version >/dev/null 2>&1 && { echo "$candidate"; return; }
  done
  echo "No Java found. Install a JDK 11 or newer (brew install openjdk@17) or set JAVA=/path/to/java." >&2
  exit 2
}

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi
}

fetch_tlc() {
  if [ -f "$JAR" ] && [ "$(sha256_of "$JAR")" = "$TLA_SHA256" ]; then return; fi
  mkdir -p "$TOOLS"
  local tmp="$TOOLS/tla2tools.jar.download"
  curl -fsSL -o "$tmp" "https://github.com/tlaplus/tlaplus/releases/download/$TLA_VERSION/tla2tools.jar"
  if [ "$(sha256_of "$tmp")" != "$TLA_SHA256" ]; then
    rm -f "$tmp"
    echo "tla2tools.jar $TLA_VERSION does not match its pinned sha256; refusing to run it." >&2
    exit 2
  fi
  mv "$tmp" "$JAR"
}

outcome_of() {
  local log="$1"
  if grep -q "No error has been found" "$log"; then echo pass
  elif grep -q "Temporal properties were violated" "$log"; then echo temporal
  elif grep -qE "(Invariant|Action property) [A-Za-z0-9_]+ is violated" "$log"; then
    grep -oE "(Invariant|Action property) [A-Za-z0-9_]+ is violated" "$log" | head -1 | awk '{print $(NF-2)}'
  else echo error
  fi
}

if ! python3 -I "$HERE/coverage.py"; then
  [ "${ALLOW_DRIFT:-}" = 1 ] || exit 3
  echo "ALLOW_DRIFT=1: checking a model that may not describe the code yet." >&2
fi
JAVA_BIN="$(find_java)"
fetch_tlc
mkdir -p "$OUT"
failures=0
printf "%-32s %-30s %-30s %12s %6s\n" check expected got states seconds
while IFS='|' read -r name expected; do
  [ -z "$name" ] && continue
  log="$OUT/$name.out"
  states_dir="$OUT/states/$name"
  rm -rf "$states_dir"
  start=$(date +%s)
  "$JAVA_BIN" -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers "$WORKERS" -nowarning \
    -config "$HERE/models/$name.cfg" -metadir "$states_dir" "$HERE/VideoQueue.tla" > "$log" 2>&1 || true
  seconds=$(( $(date +%s) - start ))
  rm -rf "$states_dir"
  got="$(outcome_of "$log")"
  states="$(grep -oE '[0-9,]+ distinct states found' "$log" | tail -1 | cut -d' ' -f1)"
  if [ "$got" != pass ] && [ "$got" != error ]; then
    python3 -I "$HERE/trace.py" "$log" > "$OUT/$name.trace.txt" 2>&1 || true
  fi
  mark=""
  if [ "$got" != "$expected" ]; then mark="  <-- UNEXPECTED"; failures=$((failures + 1)); fi
  printf "%-32s %-30s %-30s %12s %6s%s\n" "$name" "$expected" "$got" "${states:-?}" "$seconds" "$mark"
done <<< "$EXPECT"

echo "Logs and counterexample traces: $OUT"
if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) ended differently than expected. Read SKILL.md, 'Reading a result', before changing anything." >&2
  exit 1
fi
