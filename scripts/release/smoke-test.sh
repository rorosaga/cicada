#!/usr/bin/env bash
# Smoke-test a built release Cicada.app without touching this Mac's own Cicada (G182).
#
# Copies the app to a temp folder and runs its backend, MCP server and hooks
# through launchers like the ones the app writes, with a temporary CICADA_HOME,
# bank and port, capture off and every network gate off. It never opens the
# app, never loads a launch agent, and never reads ~/.cicada or a real bank.
#
# Checks: the signature verifies; /healthz reports the VERSION; the bank is
# initialised by the bundled git; an episode saves through MCP; the bundled
# embedding model indexes and finds it (sqlite-vec loads); the MCP server lists
# its tools; a hook runs.
#
# Usage: scripts/release/smoke-test.sh <path/to/Cicada.app> [port]   (default port 18000)
set -euo pipefail

SRC="${1:?usage: smoke-test.sh <Cicada.app> [port]}"
SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
PORT="${2:-18000}"
WORK="$(mktemp -d)"
BACKEND_PID=""
cleanup() {
  local status=$?
  set +e
  if [ -n "$BACKEND_PID" ]; then kill "$BACKEND_PID" 2>/dev/null; wait "$BACKEND_PID" 2>/dev/null; fi
  rm -rf "$WORK"
  exit "$status"   # the run's own result, never the SIGTERM status of the backend it stopped
}
trap cleanup EXIT
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; [ -f "$WORK/backend.log" ] && tail -20 "$WORK/backend.log" >&2; exit 1; }

if curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  fail "something already answers on port $PORT — pick another: smoke-test.sh <app> <port>"
fi

APP="$WORK/Cicada.app"
# Never from inside a checkout: `python -` puts the working directory first on sys.path, and the repo's own
# api/ would stand in for the app's (the bug this test once missed).
cd "$WORK"
ditto "$SRC" "$APP"
codesign --verify --strict --deep "$APP" || fail "the copied app's signature does not verify"
pass "signature verifies ($(codesign -dv "$APP" 2>&1 | sed -n 's/^Signature=//p' | head -1))"
[ "$(/usr/libexec/PlistBuddy -c 'Print :CicadaDistribution' "$APP/Contents/Info.plist")" = "release" ] \
  || fail "Info.plist is not stamped CicadaDistribution=release"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
pass "Cicada $VERSION (build $(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist")), $(du -sh "$APP" | cut -f1)"

# A clean environment: no developer PATH, no keys, no real home state.
export CICADA_HOME="$WORK/home" CICADA_MEMORY_PATH="$WORK/bank" CICADA_PORT="$PORT"
mkdir -p "$CICADA_HOME/bin"
# The same launchers LauncherInstaller.launcherScript writes, pointed at the copy (keep the two in step).
for name in cicada-backend cicada-mcp cicada-hook cicada-python; do
  cat > "$CICADA_HOME/bin/$name" <<EOF
#!/bin/sh
target='$APP/Contents/Resources/backend/bin/$name'
if [ ! -x "\$target" ]; then
  echo 'Cicada isn'\''t at $APP any more. Open Cicada again and it will repair this launcher.' >&2
  exit 127
fi
: "\${CICADA_PORT:=$PORT}"; export CICADA_PORT
: "\${CICADA_HOME:=$CICADA_HOME}"; export CICADA_HOME
exec "\$target" "\$@"
EOF
  chmod 755 "$CICADA_HOME/bin/$name"
done
CLEAN_ENV=(env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=en_US.UTF-8
  CICADA_HOME="$CICADA_HOME" CICADA_MEMORY_PATH="$CICADA_MEMORY_PATH" CICADA_PORT="$CICADA_PORT"
  CICADA_CAPTURE=off CICADA_TELEMETRY=off CICADA_ALLOW_CONNECTOR_FETCH=off CICADA_ALLOW_FEED_FETCH=off
  CICADA_ALLOW_LOGO_FETCH=off LITELLM_LOCAL_MODEL_COST_MAP=True)
run() { "${CLEAN_ENV[@]}" "$@"; }

# Started directly (not through the function), so $! is the backend itself: every
# launcher execs, and the cleanup's kill reaches uvicorn.
"${CLEAN_ENV[@]}" "$CICADA_HOME/bin/cicada-backend" > "$WORK/backend.log" 2>&1 &
BACKEND_PID=$!
for _ in $(seq 1 90); do
  curl -fs "http://127.0.0.1:$PORT/healthz" > "$WORK/health.json" 2>/dev/null && break
  kill -0 "$BACKEND_PID" 2>/dev/null || fail "the backend exited"
  sleep 1
done
[ -s "$WORK/health.json" ] || fail "no /healthz answer on port $PORT within 90 s"
got="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$WORK/health.json")"
[ "$got" = "$VERSION" ] || fail "/healthz reports $got, the app is $VERSION"
pass "/healthz on :$PORT reports $got"

GIT="$APP/Contents/Resources/backend/bin/git"
[ -d "$CICADA_MEMORY_PATH/.git" ] || fail "the bank was not initialised"
commits="$("$GIT" -C "$CICADA_MEMORY_PATH" rev-list --count HEAD)"
pass "bank initialised by the bundled git ($("$GIT" --version | awk '{print $3}'), $commits commit(s))"

# MCP: initialize, list the tools, save an episode.
cat > "$WORK/mcp.in" <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke-test","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"cicada_save_episode","arguments":{"title":"Smoke test","content":"The release smoke test saved this note about planting tomatoes in the community garden."}}}
EOF
run "$CICADA_HOME/bin/cicada-mcp" < "$WORK/mcp.in" > "$WORK/mcp.out" 2> "$WORK/mcp.err" || true
/usr/bin/python3 - "$WORK/mcp.out" "$VERSION" <<'PY' || fail "the MCP server did not answer as expected (see above)"
import json, sys
replies = {}
for line in open(sys.argv[1]):
    line = line.strip()
    if line.startswith("{"):
        msg = json.loads(line)
        if "id" in msg:
            replies[msg["id"]] = msg
init, tools, saved = replies.get(1), replies.get(2), replies.get(3)
assert init and init["result"]["serverInfo"]["version"] == sys.argv[2], init
names = [t["name"] for t in tools["result"]["tools"]]
assert "cicada_recall" in names and "cicada_save_episode" in names, names
assert saved and not saved["result"].get("isError"), saved
print(f"    {len(names)} tools; serverInfo {init['result']['serverInfo']['version']}")
PY
ls "$CICADA_MEMORY_PATH/episodes/"*.md >/dev/null 2>&1 || fail "no episode file was written"
pass "MCP server answers, lists its tools and saved an episode"

# Embeddings with the bundled model: index the bank, then find the episode by meaning.
run "$CICADA_HOME/bin/cicada-python" -P - "$CICADA_MEMORY_PATH" <<'PY' > "$WORK/embed.out" 2>&1 || { cat "$WORK/embed.out" >&2; fail "embedding with the bundled model failed"; }
import sys
from pathlib import Path
import api
from api.config import get_settings
from api.services import providers
from api.services.vector_index import SqliteVecIndexer
bank = Path(sys.argv[1])
assert "/Contents/Resources/backend/app/" in api.__file__, f"imported {api.__file__}, not the app's code"
assert "sentence_transformers" not in sys.modules
model = get_settings().resolved_embedding_model
assert model == "intfloat/multilingual-e5-small", model
idx = SqliteVecIndexer(bank)
idx.index_episodes()
info = idx.index_info()
hits = SqliteVecIndexer(bank).search_episodes("growing vegetables", top_k=3)  # a fresh indexer: the query path
assert hits, "no episode found"
fn, mid = providers.cached_embed_fn_for_model(model)  # the cached query embedder the API and MCP use
assert fn(["a question"], is_query=True).shape == (1, 384) and mid == model
assert "sentence_transformers" not in sys.modules, "the bundled model must never import sentence-transformers"
top = hits[0]
print(f"    model {info.get('model')} ({info.get('dim') or info.get('dimensions')} dims), "
      f"top hit {top.get('id') or top.get('path') or sorted(top)} at distance {top.get('distance', top.get('score'))}")
PY
cat "$WORK/embed.out" | tail -1
pass "the bundled model indexed and found the episode (sqlite-vec loaded)"

# EmbeddingGemma 2's runtime is in the bundle (it is downloaded, never bundled): coremltools imports — it needs
# sympy and mpmath, which build-backend.sh therefore keeps — and loads compiled models.
run "$CICADA_HOME/bin/cicada-python" -c "from api.services import coreml_embedder as c; ct = c.import_coremltools(); assert ct.models.CompiledMLModel" \
  > "$WORK/coreml.out" 2>&1 || { cat "$WORK/coreml.out" >&2; fail "the Neural Engine model's runtime does not import"; }
pass "coremltools imports in the bundle (the Neural Engine search model can run once downloaded)"

# A hook runs through its launcher (the registry reports an absent hook as exit 1).
set +e
run "$CICADA_HOME/bin/cicada-hook" registry status --settings "$WORK/settings.json" --event Stop \
  --command "\"$CICADA_HOME/bin/cicada-hook\" capture --harness claude-code" >/dev/null 2>&1
status=$?
set -e
[ "$status" = "1" ] || fail "cicada-hook registry status answered $status (expected 1, absent)"
pass "cicada-hook runs (registry status: absent)"

# A launcher whose app is gone fails loudly instead of silently.
mv "$APP" "$WORK/Moved.app"
set +e
run "$CICADA_HOME/bin/cicada-mcp" </dev/null >/dev/null 2>"$WORK/gone.err"
status=$?
set -e
mv "$WORK/Moved.app" "$APP"
[ "$status" = "127" ] && grep -q "Open Cicada again" "$WORK/gone.err" || fail "a launcher for a moved app did not fail loudly"
pass "a launcher whose app moved says so (exit 127)"

echo "  all checks passed"
