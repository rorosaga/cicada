#!/usr/bin/env bash
# Assemble the release app's backend (G182): a relocatable CPython 3.12, the
# release dependency set (no torch), Cicada's own code, a portable git and the
# bundled embedding model, into one directory that bundle.sh --with-backend
# copies to Cicada.app/Contents/Resources/backend.
#
# Nothing here is writable at runtime: the app is signed, so a byte written
# inside it breaks the seal. No bytecode ships (it would be ~60 MB); the
# launchers set PYTHONPYCACHEPREFIX to ~/.cicada/cache/pycache, so Python
# compiles each module once, outside the app. Everything the backend writes
# lives under ~/.cicada and the bank.
#
# Usage: scripts/release/build-backend.sh [OUT_DIR]
#   OUT_DIR   default: app/CicadaApp/.build/release-backend/backend
# Env:
#   CICADA_RELEASE_CACHE   download cache (default ~/Library/Caches/cicada-release)
#   UV                     the uv binary (default: uv on PATH)
# arm64 only (the owner's decision, 2026-10-05).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$REPO/app/CicadaApp/.build/release-backend/backend}"
CACHE="${CICADA_RELEASE_CACHE:-$HOME/Library/Caches/cicada-release}"
UV="${UV:-uv}"
PY_MM="3.12"
# The build's own Python calls must not leave bytecode in the tree either.
export PYTHONDONTWRITEBYTECODE=1

# shellcheck source=inputs.env
. "$HERE/inputs.env"

step() { printf '  \033[36m→\033[0m %s\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

[ "$(uname -m)" = "arm64" ] || die "the release backend is built on Apple silicon (arm64) only"
command -v "$UV" >/dev/null 2>&1 || die "uv is needed to install the dependency set (https://docs.astral.sh/uv/)"

# fetch URL SHA256 NAME -> prints the cached path; a hash mismatch is fatal and the file is dropped.
fetch() {
  local url="$1" sha="$2" name="$3" path
  path="$CACHE/$name"
  mkdir -p "$CACHE"
  if [ ! -f "$path" ] || [ "$(shasum -a 256 "$path" | cut -d' ' -f1)" != "$sha" ]; then
    curl -fsSL --retry 3 -o "$path.part" "$url" || die "download failed: $url"
    mv "$path.part" "$path"
  fi
  if [ "$(shasum -a 256 "$path" | cut -d' ' -f1)" != "$sha" ]; then
    rm -f "$path"
    die "sha256 mismatch for $name — refusing to build with it"
  fi
  printf '%s' "$path"
}

rm -rf "$OUT"
mkdir -p "$OUT"/{app,bin,models}

# --- 1. CPython ---------------------------------------------------------------
step "CPython $PY_MM (python-build-standalone)…"
tar -xzf "$(fetch "$PBS_URL" "$PBS_SHA256" "cpython-$PY_MM-arm64.tar.gz")" -C "$OUT"
PY="$OUT/python/bin/python$PY_MM"
STDLIB="$OUT/python/lib/python$PY_MM"
SITE="$STDLIB/site-packages"
# Nothing Cicada runs needs Tk, IDLE, the test suite, pip or headers.
rm -rf "$OUT/python/include" "$OUT/python/share" "$OUT/python/lib/pkgconfig" \
  "$OUT"/python/lib/tcl* "$OUT"/python/lib/tk* "$OUT"/python/lib/itcl* "$OUT"/python/lib/thread* \
  "$OUT"/python/lib/libtcl* "$OUT"/python/lib/libtk* \
  "$STDLIB"/{idlelib,tkinter,turtledemo,ensurepip,lib2to3,pydoc_data,test,turtle.py} \
  "$STDLIB"/lib-dynload/_tkinter* "$STDLIB"/config-*-darwin
rm -rf "$SITE" && mkdir -p "$SITE"
rm -f "$OUT"/python/bin/{pip*,idle*,pydoc*,2to3*,python*-config}
"$PY" - <<'PYCHECK' || die "the bundled Python cannot load SQLite extensions (sqlite-vec needs them)"
import sqlite3
c = sqlite3.connect(":memory:")
c.enable_load_extension(True)
PYCHECK
ok "CPython $("$PY" -c 'import platform; print(platform.python_version())')"

# --- 2. Dependencies ----------------------------------------------------------
step "Dependencies (requirements.lock, wheels only, hashes checked)…"
"$UV" pip install -q --target "$SITE" --python "$PY" --only-binary :all: --require-hashes --no-deps \
  --python-platform aarch64-apple-darwin -r "$HERE/requirements.lock"
# Never in a release: the developer-only embedder and what it drags in.
for banned in torch sentence_transformers transformers; do
  [ ! -e "$SITE/$banned" ] || die "$banned is in the release set — it must stay out (G182)"
done
# What no code path imports at runtime: test suites, type stubs, litellm's proxy
# web UI, sympy/mpmath (onnxruntime's graph tools, never its inference) and
# hf_xet (huggingface_hub falls back to plain HTTPS without it).
find "$SITE" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +
find "$SITE" -name '*.pyi' -delete
rm -rf "$SITE/litellm/proxy/_experimental/out" "$SITE/litellm/proxy/swagger" \
  "$SITE"/sympy "$SITE"/mpmath "$SITE"/sympy-*.dist-info "$SITE"/mpmath-*.dist-info \
  "$SITE/onnxruntime/transformers" "$SITE/onnxruntime/quantization" "$SITE/onnxruntime/tools" \
  "$SITE"/hf_xet "$SITE"/hf_xet-*.dist-info "$SITE"/bin
cat > "$SITE/sitecustomize.py" <<'PY'
# Cicada (G182): the optional larger search model's packages live in ~/.cicada/extras,
# outside the signed app. Appended after the bundled site-packages, so a shared package
# always resolves to the bundled copy.
import os
import site

_extras = os.environ.get("CICADA_EXTRAS_SITE", "")
if _extras and os.path.isdir(_extras):
    site.addsitedir(_extras)
PY
ok "$(find "$SITE" -maxdepth 1 -name '*.dist-info' | wc -l | tr -d ' ') packages"

# --- 3. Cicada's code -----------------------------------------------------------
# Tracked files only, so an untracked api/.env (a person's keys) can never ride along.
step "Cicada's code…"
(cd "$REPO" && git ls-files -z -- api mcp skills SKILL.md VERSION LICENSE scripts/install-backend-agent.sh \
  | tr '\0' '\n' \
  | grep -Ev '^api/tests/|^api/\.env|^api/uv\.lock$|^api/\.python-version$|^api/\.gitignore$|^api/routers/\.gitignore$|^mcp/mcp_config\.json$' \
  | while IFS= read -r f; do [ -f "$f" ] && printf '%s\0' "$f"; done \
  | xargs -0 tar -cf - ) | tar -xf - -C "$OUT/app"
[ -f "$OUT/app/api/data/predicates-seed.yaml" ] || die "api/data/predicates-seed.yaml missing from the bundle"
[ -f "$OUT/app/VERSION" ] || die "VERSION missing from the bundle"
ok "version $(cat "$OUT/app/VERSION")"

# --- 4. git -------------------------------------------------------------------
step "git $GIT_VERSION (dugite-native)…"
mkdir -p "$OUT/git"
tar -xzf "$(fetch "$GIT_URL" "$GIT_SHA256" "dugite-native-$GIT_VERSION-arm64.tar.gz")" -C "$OUT/git"
# Keep git itself; drop Git Credential Manager (.NET), git-lfs, scalar and the
# server-side programs a personal bank never runs.
(
  cd "$OUT/git/libexec/git-core"
  find . -maxdepth 1 -mindepth 1 ! -name 'git' ! -name 'git-*' ! -name mergetools -exec rm -rf {} +
  rm -rf git-credential-manager* git-lfs git-daemon git-imap-send git-http-backend git-http-push git-shell \
    git-gui git-gui--askpass git-citool
)
rm -rf "$OUT/git/bin/scalar" "$OUT/git/share/bash-completion"
cp "$(fetch "$GIT_COPYING_URL" "$GIT_COPYING_SHA256" "git-$GIT_VERSION-COPYING")" "$OUT/git/COPYING"
cat > "$OUT/git/SOURCE.md" <<EOF
# git $GIT_VERSION, bundled with Cicada

Git is free software under the GNU General Public License, version 2 (see COPYING).
This copy is the macOS arm64 build of dugite-native, unmodified apart from files
removed to save space (Git Credential Manager, git-lfs, scalar, git-daemon,
git-imap-send, git-http-backend, git-http-push, git-shell).

- Binary: $GIT_URL
- Build scripts: https://github.com/desktop/dugite-native
- Git source for this version: https://github.com/git/git/tree/v$GIT_VERSION
  (and https://mirrors.edge.kernel.org/pub/software/scm/git/git-$GIT_VERSION.tar.xz)
EOF
ok "git $(env GIT_EXEC_PATH="$OUT/git/libexec/git-core" "$OUT/git/bin/git" --version | awk '{print $3}')"

# --- 5. The embedding model ------------------------------------------------------
step "Embedding model ($MODEL_ID)…"
MODEL_OUT="$OUT/models/$MODEL_DIR_NAME"
mkdir -p "$MODEL_OUT"
while IFS=: read -r src dest sha; do
  [ -n "$src" ] || continue
  cp "$(fetch "https://huggingface.co/$MODEL_REPO/resolve/$MODEL_REVISION/$src" "$sha" \
    "model-$MODEL_DIR_NAME-$MODEL_REVISION-$dest")" "$MODEL_OUT/$dest"
done <<< "$MODEL_FILES"
cat > "$MODEL_OUT/cicada-model.json" <<EOF
{
  "id": "$MODEL_ID",
  "dimensions": 384,
  "pooling": "cls",
  "normalize": true,
  "max_tokens": 512,
  "query_prefix": "Represent this sentence for searching relevant passages: ",
  "source": "https://huggingface.co/$MODEL_REPO/tree/$MODEL_REVISION",
  "license": "MIT (BAAI/bge-small-en-v1.5)"
}
EOF
ok "$(du -sh "$MODEL_OUT" | cut -f1)"

# --- 6. Launchers ---------------------------------------------------------------
# The app writes ~/.cicada/bin/cicada-{backend,mcp,hook} pointing at these; agents
# and launchd only ever see the stable ~/.cicada/bin paths.
step "Launchers…"
cat > "$OUT/bin/cicada-env" <<'EOF'
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
cat > "$OUT/bin/git" <<'EOF'
#!/bin/sh
# The bundled git, with its helper and template paths set for this call only.
d="$(cd "$(dirname "$0")/.." && pwd -P)/git"
GIT_EXEC_PATH="$d/libexec/git-core" GIT_TEMPLATE_DIR="$d/share/git-core/templates" exec "$d/bin/git" "$@"
EOF
cat > "$OUT/bin/cicada-backend" <<'EOF'
#!/bin/sh
# The backend: uvicorn on 127.0.0.1:$CICADA_PORT (default 8000).
. "$(dirname "$0")/cicada-env"
cd "$CICADA_BACKEND_DIR/app" || exit 1
exec "$CICADA_PYTHON" -m uvicorn api.main:app --host 127.0.0.1 --port "$CICADA_PORT" "$@"
EOF
cat > "$OUT/bin/cicada-mcp" <<'EOF'
#!/bin/sh
# The stdio MCP server every agent registers.
. "$(dirname "$0")/cicada-env"
exec "$CICADA_PYTHON" "$CICADA_BACKEND_DIR/app/mcp/server.py" "$@"
EOF
cat > "$OUT/bin/cicada-hook" <<'EOF'
#!/bin/sh
# cicada-hook capture|recall|registry [args] — the harness hooks (G105, G149) and
# the hook registry the app runs to install them.
. "$(dirname "$0")/cicada-env"
case "$1" in
  capture|recall|registry) name="$1"; shift ;;
  *) echo "usage: cicada-hook capture|recall|registry [args]" >&2; exit 2 ;;
esac
exec "$CICADA_PYTHON" "$CICADA_BACKEND_DIR/app/api/hooks/$name.py" "$@"
EOF
cat > "$OUT/bin/cicada-python" <<'EOF'
#!/bin/sh
# The bundled interpreter with Cicada's environment (diagnostics, the agent install script).
. "$(dirname "$0")/cicada-env"
exec "$CICADA_PYTHON" "$@"
EOF
chmod 755 "$OUT"/bin/{git,cicada-backend,cicada-mcp,cicada-hook,cicada-python}
chmod 644 "$OUT/bin/cicada-env"
ok "bin/: $(ls "$OUT/bin" | tr '\n' ' ')"

# --- 7. Bytecode, manifest, cleanup --------------------------------------------------
step "Checking the assembled backend…"
# A throwaway home and bank: the import check must never touch the builder's own ~/.cicada or memory.
CHECK_HOME="$(mktemp -d)"
CICADA_HOME="$CHECK_HOME/home" CICADA_MEMORY_PATH="$CHECK_HOME/bank" CICADA_CAPTURE=off \
  "$OUT/bin/cicada-python" - <<'PYCHECK' || die "the assembled backend does not import"
import api.main, sqlite_vec, onnxruntime, tokenizers, certifi  # noqa: F401
from api.version import __version__
print(f"    imports ok · version {__version__}")
PYCHECK
rm -rf "$CHECK_HOME"
# No bytecode in the app (see the header); the check above wrote its own under CHECK_HOME.
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +
cat > "$OUT/manifest.json" <<EOF
{
  "version": "$(cat "$OUT/app/VERSION" | tr -d '[:space:]')",
  "python": "$("$PY" -c 'import platform; print(platform.python_version())')",
  "python_source": "$PBS_URL",
  "git": "$GIT_VERSION",
  "git_source": "$GIT_URL",
  "embedding_model": "$MODEL_ID",
  "embedding_model_source": "https://huggingface.co/$MODEL_REPO/tree/$MODEL_REVISION",
  "commit": "$(cd "$REPO" && git rev-parse HEAD 2>/dev/null || echo unknown)"
}
EOF
xattr -cr "$OUT" 2>/dev/null || true
ok "backend assembled at $OUT ($(du -sh "$OUT" | cut -f1))"
