#!/usr/bin/env bash
# Write the release backend's inner launchers into BIN_DIR (G182, G180): the scripts inside
# Cicada.app/Contents/Resources/backend/bin that the app's ~/.cicada/bin shims exec by absolute path.
# Called by build-backend.sh; tests call it to run the real launchers in a synthetic bundle.
#
# Usage: scripts/release/write-launchers.sh BIN_DIR
set -euo pipefail
BIN="${1:?usage: write-launchers.sh BIN_DIR}"
mkdir -p "$BIN"

cat > "$BIN/cicada-env" <<'EOF'
# Sourced by the launchers beside it, never run. $0 is the launcher's own path
# inside Cicada.app (the ~/.cicada/bin shims exec it by absolute path).
CICADA_BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
export CICADA_BACKEND_DIR
# An agent's own Python settings must never steer the bundled interpreter.
unset PYTHONHOME PYTHONSTARTUP VIRTUAL_ENV
export CICADA_DISTRIBUTION=release
: "${CICADA_HOME:=$HOME/.cicada}"; export CICADA_HOME
: "${CICADA_PORT:=8000}"; export CICADA_PORT
export CICADA_BUNDLED_MODELS="$CICADA_BACKEND_DIR/models"
CICADA_PYTHON="$CICADA_BACKEND_DIR/python/bin/python3.12"
PYTHONPATH="$CICADA_BACKEND_DIR/app"
# The optional larger search model's runtime, installed from Settings outside the signed app;
# sitecustomize.py appends it AFTER the bundled packages, so it never shadows one of them.
CICADA_EXTRAS_SITE="$CICADA_HOME/extras/site-packages"; export CICADA_EXTRAS_SITE
# Bytecode is cached outside the signed app (nothing may be written inside it).
PYTHONPYCACHEPREFIX="$CICADA_HOME/cache/pycache"
export PYTHONPATH PYTHONPYCACHEPREFIX PYTHONNOUSERSITE=1 PYTHONUTF8=1
: "${SSL_CERT_FILE:=$CICADA_BACKEND_DIR/python/lib/python3.12/site-packages/certifi/cacert.pem}"; export SSL_CERT_FILE
# The bundled git comes first for everything the backend runs (a Mac without the
# developer tools has only Apple's install-prompt shim at /usr/bin/git).
PATH="$CICADA_BACKEND_DIR/bin:$PATH"; export PATH
EOF
cat > "$BIN/git" <<'EOF'
#!/bin/sh
# The bundled git, with its helper and template paths set for this call only.
d="$(cd "$(dirname "$0")/.." && pwd -P)/git"
GIT_EXEC_PATH="$d/libexec/git-core" GIT_TEMPLATE_DIR="$d/share/git-core/templates" exec "$d/bin/git" "$@"
EOF
cat > "$BIN/cicada-backend" <<'EOF'
#!/bin/sh
# The backend: uvicorn on 127.0.0.1:$CICADA_PORT (default 8000).
. "$(dirname "$0")/cicada-env"
cd "$CICADA_BACKEND_DIR/app" || exit 1
exec "$CICADA_PYTHON" -m uvicorn api.main:app --host 127.0.0.1 --port "$CICADA_PORT" "$@"
EOF
cat > "$BIN/cicada-mcp" <<'EOF'
#!/bin/sh
# The stdio MCP server every agent registers.
. "$(dirname "$0")/cicada-env"
exec "$CICADA_PYTHON" "$CICADA_BACKEND_DIR/app/mcp/server.py" "$@"
EOF
cat > "$BIN/cicada-hook" <<'EOF'
#!/bin/sh
# cicada-hook capture|recall|registry|cursor|cursor_registry [args] — local hooks and
# the hook registry the app runs to install them.
. "$(dirname "$0")/cicada-env"
case "$1" in
  capture|recall|registry|cursor|cursor_registry) name="$1"; shift ;;
  *) echo "usage: cicada-hook capture|recall|registry|cursor|cursor_registry [args]" >&2; exit 2 ;;
esac
exec "$CICADA_PYTHON" "$CICADA_BACKEND_DIR/app/api/hooks/$name.py" "$@"
EOF
cat > "$BIN/cicada-python" <<'EOF'
#!/bin/sh
# The bundled interpreter with Cicada's environment (diagnostics, the agent install script).
. "$(dirname "$0")/cicada-env"
exec "$CICADA_PYTHON" "$@"
EOF
cat > "$BIN/cicada" <<'EOF'
#!/bin/sh
# cicada — the command line for agents with a shell (G180): the same memory as the MCP tools.
# No cd: the caller's working folder is what `cicada continue` and a saved note are about.
# -P: that folder is never on sys.path. The CLI's own bootstrap reads no .env from it either.
. "$(dirname "$0")/cicada-env"
exec "$CICADA_PYTHON" -P -m api.cli "$@"
EOF
chmod 755 "$BIN"/{git,cicada-backend,cicada-mcp,cicada-hook,cicada-python,cicada}
chmod 644 "$BIN/cicada-env"
