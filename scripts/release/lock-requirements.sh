#!/usr/bin/env bash
# Recompile requirements.lock from requirements.in for the release's one target
# (CPython 3.12, macOS arm64), pinned to the versions the developer lock already
# uses wherever the two sets overlap, with hashes so the build installs exactly
# these files. Run after changing requirements.in or api/uv.lock.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"
constraints="$(mktemp)"
trap 'rm -f "$constraints"' EXIT
uv export --frozen --no-dev --no-hashes --no-emit-project --directory "$REPO/api" -q > "$constraints"
uv pip compile requirements.in -c "$constraints" --python-version 3.12 \
  --python-platform aarch64-apple-darwin --generate-hashes --no-header --no-annotate -q -o requirements.lock
echo "✓ requirements.lock"
