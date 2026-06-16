#!/usr/bin/env bash
#
# Cicada health check. Each check is independent and prints a ✓/✗ line; the
# script never crashes on a failing check (set -e is intentionally NOT used).
# Exit code = number of failed checks (0 = all healthy).
#
# Override env vars (default to real locations):
#   CICADA_MEMORY_PATH   memory dir          (default: ~/cicada/memory)
#   CICADA_REPO          repo root           (default: parent of scripts/)
#   CLAUDE_CLI           claude binary name  (default: claude)
#   CICADA_PORT          backend port        (default: 8000)

REPO="${CICADA_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MEMORY_PATH="${CICADA_MEMORY_PATH:-$HOME/cicada/memory}"
CLAUDE_CLI="${CLAUDE_CLI:-claude}"
PORT="${CICADA_PORT:-8000}"
VENV_PY="$REPO/api/.venv/bin/python"

FAILURES=0

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
note() { printf '    \033[2m%s\033[0m\n' "$1"; }

printf '\033[1mCicada doctor\033[0m\n'
echo "  repo:   $REPO"
echo "  memory: $MEMORY_PATH"
echo

# 1. Backend /healthz reachable (+ embeddingMode shown).
HEALTH_JSON=$(curl -fsS "http://127.0.0.1:$PORT/healthz" 2>/dev/null || true)
if [ -n "$HEALTH_JSON" ] && printf '%s' "$HEALTH_JSON" | grep -q '"status"'; then
  MODE=$(printf '%s' "$HEALTH_JSON" | sed -n 's/.*"embeddingMode":"\([^"]*\)".*/\1/p')
  pass "Backend /healthz reachable on :$PORT (embeddingMode=${MODE:-unknown})"
else
  fail "Backend /healthz not reachable on :$PORT"
  note "start it: ./install.sh  (or check logs/backend.err.log)"
fi

# 2. Memory dir exists.
if [ -d "$MEMORY_PATH" ]; then
  pass "Memory directory exists"
else
  fail "Memory directory missing: $MEMORY_PATH"
  note "run ./install.sh to create it"
fi

# 3. Memory dir is a git repo.
if git -C "$MEMORY_PATH" rev-parse --git-dir >/dev/null 2>&1; then
  pass "Memory dir is a git repo"
else
  fail "Memory dir is not a git repo"
  note "run ./install.sh to git init it"
fi

# 4. _index.md present (hub-tier entry point).
if [ -f "$MEMORY_PATH/_index.md" ]; then
  pass "_index.md present (hub-tier entry point)"
else
  fail "_index.md missing"
  note "run a sleep cycle (POST /sleep/trigger) to regenerate the hub tier"
fi

# 5. LEANN sidecars present (any *.meta.json under leann/).
if ls "$MEMORY_PATH"/leann/*.meta.json >/dev/null 2>&1; then
  pass "LEANN index sidecars present"
else
  fail "No LEANN index sidecars found"
  note "run a sleep cycle or 'make rebuild-episodes' to build the index"
fi

# 6. MCP registered (tolerate CLI absence).
if command -v "$CLAUDE_CLI" >/dev/null 2>&1; then
  if "$CLAUDE_CLI" mcp list 2>/dev/null | grep -q 'cicada'; then
    pass "MCP server 'cicada' registered"
  else
    fail "MCP server 'cicada' not registered"
    note "run ./install.sh to register it"
  fi
else
  pass "claude CLI absent — skipping MCP check (not a failure)"
fi

# 7. venv imports api.main.
if [ -x "$VENV_PY" ] && "$VENV_PY" -c "import api.main" >/dev/null 2>&1; then
  pass "api venv imports api.main"
else
  fail "api venv cannot import api.main"
  note "run ./install.sh (uv sync) from the repo"
fi

# 8. launchd plist loaded.
if launchctl print "gui/$(id -u)/com.cicada.backend" >/dev/null 2>&1; then
  pass "launchd backend agent loaded"
else
  fail "launchd backend agent not loaded"
  note "run ./install.sh to bootstrap it (or use the dev BackendProcess path)"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32m%s\033[0m\n' "All checks passed."
else
  printf '\033[31m%s\033[0m\n' "$FAILURES check(s) failed."
fi
exit "$FAILURES"
