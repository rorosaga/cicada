#!/usr/bin/env bash
#
# Cicada plug-and-play installer.
#
# One idempotent script: every step state-checks before acting, so it is safe
# to re-run. It provisions the memory tree, syncs the Python venv, scaffolds
# api/.env (filling only missing keys — never clobbering), registers the MCP
# server, and bootstraps a launchd backend that keeps uvicorn alive.
#
# Usage:
#   ./install.sh                 full install (prompts for optional API keys)
#   ./install.sh --dry-run       print every action without executing
#   ./install.sh --skill         also copy SKILL.md to ~/.claude/skills/cicada/
#   ./install.sh --uninstall     unload+remove launchd + MCP entry (keeps memory)
#
# Test/override env vars (default to real locations):
#   CICADA_MEMORY_PATH   memory dir            (default: ~/cicada/memory)
#   CICADA_REPO          repo root             (default: script dir)
#   LAUNCH_AGENTS_DIR    LaunchAgents dir      (default: ~/Library/LaunchAgents)
#   CLAUDE_SKILLS_DIR    skills dir            (default: ~/.claude/skills)
#   CLAUDE_CLI           claude binary name    (default: claude)
#
set -euo pipefail

# ---------- paths & flags ----------

REPO="${CICADA_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
MEMORY_PATH="${CICADA_MEMORY_PATH:-$HOME/cicada/memory}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
CLAUDE_SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
CLAUDE_CLI="${CLAUDE_CLI:-claude}"

API_DIR="$REPO/api"
VENV="$API_DIR/.venv"
VENV_PY="$VENV/bin/python"
VENV_UVICORN="$VENV/bin/uvicorn"
ENV_FILE="$API_DIR/.env"
ENV_EXAMPLE="$API_DIR/.env.example"
MCP_SERVER="$REPO/mcp/server.py"
PLIST_LABEL="com.cicada.backend"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_LABEL.plist"
PORT=8000

DRY_RUN=0
DO_SKILL=0
DO_UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --skill)     DO_SKILL=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    -h|--help)
      sed -n '3,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# ---------- output helpers ----------

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
step() { printf '  \033[36m→\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

# Run a command, or just print it when --dry-run.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  \033[2m$ %s\033[0m\n' "$*"
  else
    "$@"
  fi
}

# True if a Cicada backend already answers /healthz on $PORT.
backend_healthy() {
  curl -fsS "http://127.0.0.1:$PORT/healthz" 2>/dev/null | grep -q '"status"'
}

# ============================================================
# Uninstall path
# ============================================================
if [ "$DO_UNINSTALL" -eq 1 ]; then
  hdr "Uninstalling Cicada (memory dir is never touched)"

  if [ -f "$PLIST_PATH" ]; then
    step "Unloading launchd agent $PLIST_LABEL"
    run launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || true
    run rm -f "$PLIST_PATH"
    ok "Removed $PLIST_PATH"
  else
    ok "No launchd plist to remove"
  fi

  if command -v "$CLAUDE_CLI" >/dev/null 2>&1; then
    step "Removing MCP registration 'cicada'"
    run "$CLAUDE_CLI" mcp remove cicada 2>/dev/null || true
    ok "MCP entry removed (if it existed)"
  else
    warn "claude CLI not found — remove the 'cicada' MCP entry manually"
  fi

  ok "Memory dir left intact: $MEMORY_PATH"
  hdr "Uninstall complete."
  exit 0
fi

# ============================================================
# Install path
# ============================================================
hdr "Installing Cicada"
[ "$DRY_RUN" -eq 1 ] && warn "DRY RUN — no changes will be made"
echo "  repo:   $REPO"
echo "  memory: $MEMORY_PATH"

# --- 1. Preflight: required tools ---
hdr "1. Preflight"
missing=0
if command -v uv >/dev/null 2>&1; then
  ok "uv present ($(command -v uv))"
else
  err "uv not found — install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  missing=1
fi
if command -v git >/dev/null 2>&1; then
  ok "git present"
else
  err "git not found"
  missing=1
fi
if [ "$missing" -eq 1 ]; then
  err "Missing prerequisites — aborting."
  exit 2
fi

# --- 2. Python venv (uv sync) ---
hdr "2. Python environment"
if [ -x "$VENV_PY" ]; then
  ok "venv present ($VENV)"
else
  step "Creating venv via uv sync"
  run sh -c "cd '$API_DIR' && uv sync"
  if [ "$DRY_RUN" -eq 0 ] && [ ! -x "$VENV_PY" ]; then
    err "uv sync did not produce $VENV_PY"
    exit 1
  fi
  ok "venv ready"
fi

# --- 3. Memory tree + git ---
hdr "3. Memory directory"
for sub in entities nudges clarifications inbox episodes hubs sources leann; do
  d="$MEMORY_PATH/$sub"
  if [ -d "$d" ]; then
    : # already there
  else
    step "mkdir $sub/"
    run mkdir -p "$d"
  fi
done
ok "Subdirs present (entities nudges clarifications inbox episodes hubs sources leann)"

if [ -d "$MEMORY_PATH/.git" ]; then
  ok "memory is already a git repo"
else
  step "git init memory + initial commit"
  run sh -c "cd '$MEMORY_PATH' && git init -q && git add -A && git commit -q -m 'Initial Cicada memory' --allow-empty"
  ok "memory git repo initialized"
fi

# --- 4. Scaffold api/.env (fill missing keys only, never clobber) ---
hdr "4. Configuration (api/.env)"

# Read an existing value for KEY from $ENV_FILE (empty if absent/blank).
env_value() {
  local key="$1"
  [ -f "$ENV_FILE" ] || { echo ""; return; }
  local line
  line=$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 || true)
  echo "${line#${key}=}"
}

# Append KEY=VALUE to $ENV_FILE only if KEY is not already present.
ensure_env() {
  local key="$1" val="$2"
  if [ -f "$ENV_FILE" ] && grep -qE "^${key}=" "$ENV_FILE"; then
    return 0  # never clobber an existing value
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$key" = "OPENAI_API_KEY" ] || [ "$key" = "ANTHROPIC_API_KEY" ]; then
      printf '  \033[2m$ echo "%s=***" >> %s\033[0m\n' "$key" "$ENV_FILE"
    else
      printf '  \033[2m$ echo "%s=%s" >> %s\033[0m\n' "$key" "$val" "$ENV_FILE"
    fi
  else
    umask 077
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

if [ "$DRY_RUN" -eq 0 ]; then
  ( umask 077; touch "$ENV_FILE" )
fi
if [ -f "$ENV_FILE" ]; then
  ok "api/.env exists — filling only missing keys"
else
  step "Creating api/.env (umask 077)"
fi

# Memory path + embedding default always present.
ensure_env CICADA_MEMORY_PATH "$MEMORY_PATH"
ensure_env CICADA_EMBEDDING_MODE "openai"
ensure_env CICADA_EMBEDDING_MODEL "text-embedding-3-small"
# LiteLLM defaults sourced from the example.
ensure_env CICADA_LITELLM_MODEL "gpt-5.4-mini"
ensure_env CICADA_LITELLM_DISAMBIGUATION_MODEL "gpt-5.4-nano"

# Prompt for API keys only if missing AND interactive AND not dry-run.
prompt_key() {
  local key="$1" hint="$2"
  if [ -n "$(env_value "$key")" ]; then
    ok "$key already set"
    return
  fi
  if [ "$DRY_RUN" -eq 1 ] || [ ! -t 0 ]; then
    ensure_env "$key" ""
    warn "$key left blank ($hint)"
    return
  fi
  local entered
  printf '  Enter %s (%s, leave blank to skip): ' "$key" "$hint"
  read -r entered || entered=""
  ensure_env "$key" "$entered"
  if [ -n "$entered" ]; then ok "$key saved"; else warn "$key skipped"; fi
}

prompt_key OPENAI_API_KEY "needed for openai embeddings; blank = local embedding fallback (~250MB)"
prompt_key ANTHROPIC_API_KEY "optional, for an Anthropic sleep-cycle model"
ensure_env GEMINI_API_KEY ""

# If no OpenAI key ended up set, flip the embedding mode to local explicitly.
if [ "$DRY_RUN" -eq 0 ] && [ -z "$(env_value OPENAI_API_KEY)" ]; then
  if grep -qE '^CICADA_EMBEDDING_MODE=openai$' "$ENV_FILE"; then
    warn "No OpenAI key — local embeddings will be used. Install the extra with:"
    warn "  uv sync --extra local --directory api   (~250MB incl. torch, ~90MB model on first build)"
  fi
fi
ok "api/.env ready"

# --- 5. Register MCP server ---
hdr "5. MCP server registration"
if command -v "$CLAUDE_CLI" >/dev/null 2>&1; then
  if "$CLAUDE_CLI" mcp list 2>/dev/null | grep -q '^cicada\b'; then
    ok "MCP server 'cicada' already registered"
  else
    step "Registering 'cicada' via claude mcp add"
    run "$CLAUDE_CLI" mcp add cicada \
      --env "CICADA_MEMORY_PATH=$MEMORY_PATH" \
      -- "$VENV_PY" "$MCP_SERVER"
    ok "MCP server registered"
  fi
else
  warn "claude CLI not found — add this entry to your MCP config manually:"
  cat <<EOF
  {
    "mcpServers": {
      "cicada": {
        "command": "$VENV_PY",
        "args": ["$MCP_SERVER"],
        "env": { "CICADA_MEMORY_PATH": "$MEMORY_PATH" }
      }
    }
  }
EOF
fi

# --- 6. launchd backend ---
hdr "6. Backend service (launchd)"
if backend_healthy; then
  ok "A Cicada backend is already serving /healthz on :$PORT — skipping launchd bootstrap"
else
  step "Writing launchd plist -> $PLIST_PATH"
  run mkdir -p "$LAUNCH_AGENTS_DIR"
  write_plist() {
    cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_UVICORN</string>
    <string>api.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CICADA_MEMORY_PATH</key><string>$MEMORY_PATH</string>
    <key>PYTHONPATH</key><string>$REPO</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$REPO/logs/backend.out.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/backend.err.log</string>
</dict>
</plist>
EOF
  }
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  \033[2m$ write %s (RunAtLoad+KeepAlive, uvicorn :%s, secrets stay in api/.env)\033[0m\n' "$PLIST_PATH" "$PORT"
  else
    mkdir -p "$REPO/logs"
    write_plist
  fi
  step "Bootstrapping launchd agent (bootout-then-bootstrap = idempotent)"
  run launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || true
  run launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  if [ "$DRY_RUN" -eq 0 ]; then
    step "Waiting for backend /healthz ..."
    for _ in $(seq 1 10); do
      backend_healthy && break
      sleep 1
    done
    if backend_healthy; then ok "Backend is up on :$PORT"; else warn "Backend not yet healthy — check $REPO/logs/backend.err.log"; fi
  else
    ok "launchd bootstrap (dry-run)"
  fi
fi

# --- 7. Skill (opt-in) ---
if [ "$DO_SKILL" -eq 1 ]; then
  hdr "7. Claude skill"
  dest="$CLAUDE_SKILLS_DIR/cicada/SKILL.md"
  step "Copying SKILL.md -> $dest"
  run mkdir -p "$CLAUDE_SKILLS_DIR/cicada"
  run cp "$REPO/SKILL.md" "$dest"
  ok "Skill installed"
fi

# --- Summary ---
hdr "Done — what happened"
echo "  memory:        $MEMORY_PATH"
echo "  venv:          $VENV"
echo "  api/.env:      $ENV_FILE (missing keys filled, existing preserved)"
if command -v "$CLAUDE_CLI" >/dev/null 2>&1; then
  echo "  MCP:           registered as 'cicada'"
else
  echo "  MCP:           manual JSON snippet printed above"
fi
echo "  launchd:       $PLIST_PATH"
[ "$DO_SKILL" -eq 1 ] && echo "  skill:         $CLAUDE_SKILLS_DIR/cicada/SKILL.md"
echo
echo "  Next: run 'make doctor' to verify, or 'curl localhost:$PORT/healthz'."
