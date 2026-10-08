#!/usr/bin/env bash
# Fetch Cicada's on-device embedding model: the release app's own pinned files
# (scripts/release/inputs.env), each checked against its sha256, laid out as a
# model folder api/services/onnx_embedder.py reads. The one writer of that layout:
# the release build calls it for the app bundle, and a developer checkout runs it
# (`make embedding-model`, install.sh) so it embeds the way a release does — the
# same small model on onnxruntime, no torch, no account, no key.
#
# Usage: scripts/fetch-embedding-model.sh [MODELS_DIR]
#   MODELS_DIR   default: ${CICADA_HOME:-~/.cicada}/models (where a checkout looks)
# Env:
#   CICADA_RELEASE_CACHE    download cache (default ~/Library/Caches/cicada-release)
#   CICADA_RELEASE_INPUTS   the pins file (default scripts/release/inputs.env)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
INPUTS="${CICADA_RELEASE_INPUTS:-$HERE/release/inputs.env}"
CACHE="${CICADA_RELEASE_CACHE:-$HOME/Library/Caches/cicada-release}"
MODELS="${1:-${CICADA_HOME:-$HOME/.cicada}/models}"

# shellcheck source=release/inputs.env
. "$INPUTS"

die() { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }
sha_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

# fetch URL SHA256 NAME -> prints the cached path; a hash mismatch is fatal and the file is dropped.
fetch() {
  local url="$1" sha="$2" name="$3" path
  path="$CACHE/$name"
  mkdir -p "$CACHE"
  if [ ! -f "$path" ] || [ "$(sha_of "$path")" != "$sha" ]; then
    curl -fsSL --retry 3 -o "$path.part" "$url" || die "download failed: $url"
    mv "$path.part" "$path"
  fi
  if [ "$(sha_of "$path")" != "$sha" ]; then
    rm -f "$path"
    die "sha256 mismatch for $name — refusing to install it"
  fi
  printf '%s' "$path"
}

# Both feed an `rm -rf` below: an unset or empty value, or a name that is a path, stops here — before anything is deleted.
: "${MODELS:?the models folder is empty}" "${MODEL_DIR_NAME:?MODEL_DIR_NAME is unset in $INPUTS}"
case "$MODEL_DIR_NAME" in
  */*|.|..|.*) die "MODEL_DIR_NAME must be a plain folder name, not '$MODEL_DIR_NAME'" ;;
esac
OUT="$MODELS/$MODEL_DIR_NAME"
# Staged beside the destination and swapped in whole, so a stopped run never leaves a half model the embedder finds.
STAGE="$MODELS/.$MODEL_DIR_NAME.partial"
rm -rf "$STAGE"
mkdir -p "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
while IFS=: read -r src dest sha; do
  [ -n "$src" ] || continue
  cp "$(fetch "$MODEL_BASE_URL/$src" "$sha" "model-$MODEL_DIR_NAME-$MODEL_REVISION-$dest")" "$STAGE/$dest"
done <<< "$MODEL_FILES"
cat > "$STAGE/cicada-model.json" <<JSON
{
  "id": "$MODEL_ID",
  "dimensions": $MODEL_DIMENSIONS,
  "pooling": "$MODEL_POOLING",
  "normalize": true,
  "max_tokens": $MODEL_MAX_TOKENS,
  "query_prefix": "$MODEL_QUERY_PREFIX",
  "document_prefix": "$MODEL_DOCUMENT_PREFIX",
  "source": "$MODEL_SOURCE",
  "license": "$MODEL_LICENSE"
}
JSON
rm -rf "$OUT"
mv "$STAGE" "$OUT"
trap - EXIT
printf '%s\n' "$OUT"
