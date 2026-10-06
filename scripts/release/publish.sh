#!/usr/bin/env bash
# Publish a built release on GitHub (G182, TODO ruling 19) — the only step that advertises anything.
#
#   publish.sh X.Y.Z <commit-sha> <dist-dir>        env: GH_TOKEN, LATEST=true|false, PREVIOUS=vA.B.C|""
#
# dist-dir holds Cicada-X.Y.Z.zip, its .sig, latest.json and Cicada-macos-arm64.zip (the same bytes under a name that
# never changes, so .../releases/latest/download/Cicada-macos-arm64.zip always resolves). The release is made as a
# draft at <commit-sha> — GitHub creates the tag only when a draft is published — every asset is checked by name and
# size, and only then is it published, marked "latest" only when LATEST=true. Any failure deletes the draft this run
# made (and its tag, should one exist), so a failed run advertises nothing. A published release is never edited,
# deleted or re-uploaded to: a run that finds one says so and exits 0.
set -euo pipefail

VERSION="${1:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
SHA="${2:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
DIST="${3:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
LATEST="${LATEST:-false}"
PREVIOUS="${PREVIOUS:-}"
TAG="v$VERSION"
HERE="$(cd "$(dirname "$0")" && pwd)"
STABLE="Cicada-macos-arm64.zip"
FILES=("$DIST/Cicada-$VERSION.zip" "$DIST/Cicada-$VERSION.zip.sig" "$DIST/latest.json" "$DIST/$STABLE")

die() { echo "✗ $*" >&2; exit 1; }

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "not a release version: $VERSION"
[[ "$LATEST" == true || "$LATEST" == false ]] || die "LATEST must be true or false"
for f in "${FILES[@]}"; do [ -s "$f" ] || die "missing or empty: $f"; done
cmp -s "$DIST/Cicada-$VERSION.zip" "$DIST/$STABLE" || die "$STABLE is not the same bytes as Cicada-$VERSION.zip"

# `gh release view` as JSON → "absent", "draft" or "published".
release_state() {
  local json
  json="$(gh release view "$TAG" --json isDraft,assets,tagName 2>/dev/null)" || { echo absent; return; }
  python3 -c 'import json,sys; print("draft" if json.loads(sys.argv[1])["isDraft"] else "published")' "$json"
}

case "$(release_state)" in
  published) echo "$TAG is already released — nothing to publish"; exit 0 ;;
  draft) echo "! a draft $TAG was left by an earlier failed run; it was never published — replacing it"
         gh release delete "$TAG" --yes ;;
esac

CREATED=0
cleanup() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$CREATED" = 1 ] && [ "$(release_state)" = draft ]; then
    echo "✗ publishing $TAG failed — deleting the draft so nothing is advertised" >&2
    gh release delete "$TAG" --yes --cleanup-tag || gh release delete "$TAG" --yes || true
  fi
  exit "$status"
}
trap cleanup EXIT

notes=(--notes-file "$HERE/release-notes-header.md" --generate-notes)
[ -n "$PREVIOUS" ] && notes+=(--notes-start-tag "$PREVIOUS")

CREATED=1
gh release create "$TAG" "${FILES[@]}" --draft --target "$SHA" --title "Cicada $VERSION" "${notes[@]}"

# Every asset is there, at its exact size, before anything is advertised.
gh release view "$TAG" --json isDraft,assets,tagName > "$DIST/.release.json"
python3 - "$DIST/.release.json" "${FILES[@]}" <<'PY'
import json, os, sys
release = json.load(open(sys.argv[1]))
have = {a["name"]: a["size"] for a in release["assets"]}
want = {os.path.basename(p): os.path.getsize(p) for p in sys.argv[2:]}
wrong = [f"{name} ({have.get(name, 'missing')} bytes, expected {size})" for name, size in want.items()
         if have.get(name) != size]
if not release["isDraft"] or wrong:
    sys.exit("the draft's assets are wrong: " + ", ".join(wrong or ["not a draft"]))
PY
rm -f "$DIST/.release.json"

gh release edit "$TAG" --draft=false "--latest=$LATEST"
[ "$(release_state)" = published ] || die "$TAG did not publish"
echo "✓ published $TAG at ${SHA:0:12} (latest=$LATEST)"
