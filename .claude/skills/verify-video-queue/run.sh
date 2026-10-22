#!/usr/bin/env bash
# Model-check the video queue's lease lifecycle. Usage: run.sh [--breaks | --deep | --all | --only NAME]
#   (no flag)    the code, the open findings, the proposed fixes, and every break (~45 s)
#   --breaks     only the breaks that prove each passing property can fail
#   --deep       the larger runs: two videos and two sessions, the restarting ids, the fixes with page churn
#   --only NAME  one check from any of those lists
# Exit 0 when every check ends the way its EXPECT row says: "pass" (with at least the row's distinct states, so a
# model that lost an action fails loudly), the name of the violated property, or "temporal". Exit 3 when the covered
# code changed since the sync commit (coverage.py); ALLOW_DRIFT=1 runs anyway while you bring the model in line.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TLA_VERSION="v1.7.4"
TLA_SHA256="936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TOOLS="${CICADA_TLA_TOOLS:-$HOME/.cache/cicada-tla}/$TLA_VERSION"
JAR="$TOOLS/tla2tools.jar"
JOBS="${JOBS:-2}"
WORKERS="${WORKERS:-2}"

# name|expected|minimum distinct states for a pass (about 90% of the count at the sync commit; empty for a violation)
EXPECT_DEFAULT="
code-safety|pass|62000
code-ids-shared|pass|62000
code-ids-sessionless|pass|62000
code-liveness|pass|82000
F1-release-by-non-holder|ReleaseOnlyByHolder|
F1s-session-compare-shared-ids|ReleaseOnlyByHolder|
F1s-session-compare-sessionless|HolderCanRelease|
F1s-session-compare-restart|HolderCanRelease|
F2-stale-saved-drops-row|NoLostRow|
F3-older-record-closes-row|DoneIsSupported|
F3-older-record-ends-lease|RecordByOtherCorruptsNothing|
F3s-seconds-compare-same-second|DoneIsSupported|
F4-active-session-keeps-lease|temporal|
F5-shared-id-record-ends-lease|RecordByOtherCorruptsNothing|
fixed-safety|pass|62000
fixed-same-second|pass|415000
fixed-ids-shared|pass|62000
fixed-ids-sessionless|pass|62000
fixed-legacy-rows|pass|93000
"
EXPECT_BREAKS="
break-lapse_ignores_lease|NoDoubleClaim|
break-nolock|NoDoubleClaim|
break-no_lapse|temporal|
break-no_fail_expiry|temporal|
break-record_ignores_session|RecordByOtherCorruptsNothing|
break-stays_counts_attempt|Idempotent|
break-settle_ignores_holding|NoBurnWhileHeld|
break-settle_ignores_records|NoBurnWhenSatisfied|
break-claim_takes_failed|FailedReturnsOnlyByPerson|
break-put_restarts_claimed|NoLeaseTakenAway|
break-f2_credit_stale|NoLostRow|
"
EXPECT_DEEP="
code-ids-restart|pass|305000
fixed-ids-restart|pass|305000
fixed-churn|pass|0
deep-safety|pass|0
"

outcome_of() {
  local log="$1"
  if grep -q "No error has been found" "$log"; then echo pass
  elif grep -q "Temporal properties were violated" "$log"; then echo temporal
  elif grep -qE "(Invariant|Action property) [A-Za-z0-9_]+ is violated" "$log"; then
    grep -oE "(Invariant|Action property) [A-Za-z0-9_]+ is violated" "$log" | head -1 | awk '{print $(NF-2)}'
  else echo error
  fi
}

# One check, run by xargs below: writes "$OUT/<name>.result" as "name|expected|got|states|seconds|ok".
if [ "${1:-}" = "--check" ]; then
  name="$2"; expected="$3"; minimum="$4"
  log="$OUT/$name.out"
  start=$(date +%s)
  "$JAVA_BIN" -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers "$WORKERS" -nowarning \
    -config "$HERE/models/$name.cfg" -metadir "$OUT/states/$name" "$HERE/VideoQueue.tla" > "$log" 2>&1 || true
  rm -rf "$OUT/states/$name"
  got="$(outcome_of "$log")"
  states="$(grep -oE '[0-9,]+ distinct states found' "$log" | tail -1 | cut -d' ' -f1 | tr -d ,)"
  if [ "$got" != pass ] && [ "$got" != error ]; then
    python3 -I "$HERE/trace.py" "$log" > "$OUT/$name.trace.txt" 2>&1 || true
  fi
  ok=yes
  [ "$got" = "$expected" ] || ok=no
  if [ "$got" = pass ] && [ "${states:-0}" -lt "$minimum" ]; then ok=small; fi
  echo "$name|$expected|$got|${states:-?}|$(( $(date +%s) - start ))|$ok" > "$OUT/$name.result"
  exit 0
fi

MODE="${1:-}"
case "$MODE" in
  "") EXPECT="$EXPECT_DEFAULT$EXPECT_BREAKS" ;;
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
  local tmp
  tmp="$(mktemp "$TOOLS/tla2tools.jar.XXXXXX")"
  curl -fsSL -o "$tmp" "https://github.com/tlaplus/tlaplus/releases/download/$TLA_VERSION/tla2tools.jar"
  if [ "$(sha256_of "$tmp")" != "$TLA_SHA256" ]; then
    rm -f "$tmp"
    echo "tla2tools.jar $TLA_VERSION does not match its pinned sha256; refusing to run it." >&2
    exit 2
  fi
  mv "$tmp" "$JAR"
}

if ! python3 -I "$HERE/coverage.py"; then
  [ "${ALLOW_DRIFT:-}" = 1 ] || exit 3
  echo "ALLOW_DRIFT=1: checking a model that may not describe the code yet." >&2
fi
JAVA_BIN="$(find_java)"
fetch_tlc
OUT="${OUT:-$(mktemp -d "${TMPDIR:-/tmp}/verify-video-queue.XXXXXX")}"
mkdir -p "$OUT"
export OUT JAVA_BIN JAR WORKERS

printf '%s\n' "$EXPECT" | grep '|' | tr '|' ' ' | awk '{print $1, $2, ($3 == "" ? 0 : $3)}' \
  | xargs -P "$JOBS" -n 3 "$HERE/run.sh" --check

failures=0
printf "%-34s %-30s %-30s %10s %5s\n" check expected got states s
while IFS='|' read -r name expected _; do
  [ -z "$name" ] && continue
  if [ -f "$OUT/$name.result" ]; then
    IFS='|' read -r _ _ got states seconds ok < "$OUT/$name.result"
  else
    got=missing states=? seconds=? ok=no
  fi
  mark=""
  case "$ok" in
    no) mark="  <-- UNEXPECTED"; failures=$((failures + 1)) ;;
    small) mark="  <-- TOO FEW STATES: the model lost behaviour"; failures=$((failures + 1)) ;;
  esac
  printf "%-34s %-30s %-30s %10s %5s%s\n" "$name" "$expected" "$got" "$states" "$seconds" "$mark"
done <<< "$EXPECT"

echo "Logs and counterexample traces: $OUT"
if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) ended differently than expected. Read SKILL.md, 'Reading a result', before changing anything." >&2
  exit 1
fi
