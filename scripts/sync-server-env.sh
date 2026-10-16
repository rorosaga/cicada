#!/usr/bin/env bash
#
# Sync an installed Cicada's Python environment (api/.venv) from the developer lock, without the larger search
# model's runtime (G181, G182).
#
# api/uv.lock carries sentence-transformers, which pulls torch and, on Linux, the CUDA libraries (~3 GB) — for an
# optional model nobody gets by default. The release app ships without that subtree (scripts/release/requirements.in)
# and the backend runs without it (`embedding_models.sentence_transformers_available()`); this is the same set for a
# server and a Homebrew install: every package the lock pins, at the lock's versions and hashes, minus
# sentence-transformers and what only it needs. A developer checkout keeps running `uv sync` (the full set).
#
# The one source of that set: scripts/install-server.sh and Formula/cicada.rb both run this.
#
# Usage: scripts/sync-server-env.sh [extra `uv sync` flags]   (uv on PATH; UV_* variables pass through)
# Exit: 0 synced · 1 uv failed · 3 no uv
set -euo pipefail

API="$(cd "$(dirname "${BASH_SOURCE[0]}")/../api" && pwd)"
command -v uv >/dev/null 2>&1 || { echo "uv is needed: https://docs.astral.sh/uv/" >&2; exit 3; }

# The names `uv export` writes, one per line, from requirement lines like `torch==2.11.0 ; sys_platform == 'linux'`.
names() { sed -n 's/^\([A-Za-z0-9][A-Za-z0-9._-]*\)==.*/\1/p' | tr '[:upper:]_' '[:lower:]-' | sort -u; }
export_names() { (cd "$API" && uv export --frozen --no-dev --no-emit-project --no-hashes --quiet "$@") | names; }

full="$(export_names)"
kept="$(export_names --prune sentence-transformers)"
[ -n "$full" ] && [ -n "$kept" ] || { echo "uv export listed no packages from $API/uv.lock" >&2; exit 1; }

args=()
while IFS= read -r pkg; do
  [ -n "$pkg" ] && args+=(--no-install-package "$pkg")
done < <(comm -23 <(printf '%s\n' "$full") <(printf '%s\n' "$kept"))

cd "$API"
exec uv sync --frozen --no-dev ${args[@]+"${args[@]}"} "$@"
