#!/usr/bin/env bash
# Publish a built release on GitHub (G182, TODO ruling 19) — the only step that advertises anything.
#
#   publish.sh X.Y.Z <commit-sha> <dist-dir>        env: GH_TOKEN, GH_REPO; run from a checkout whose origin is the repo
#
# dist-dir holds Cicada-X.Y.Z.zip, its .sig, latest.json and Cicada-macos-arm64.zip (the same bytes under a name that
# never changes, so .../releases/latest/download/Cicada-macos-arm64.zip always resolves).
#
# The version is judged again here against the remote's live tags (check_version.py plan), not taken from the plan
# job: "Re-run failed jobs" reuses that job's outputs, and a newer release may have been published since. Already
# tagged → nothing to do, exit 0; not greater than the latest tag → fail. Then the release is made as a draft at
# <commit-sha> — GitHub creates the tag only when a draft is published — every asset is checked by name and size, and
# only then is it published and marked latest. Any failure deletes the draft this run made, so a failed run
# advertises nothing (a draft has no tag, so no tag is ever deleted here). A published release is never edited,
# deleted or re-uploaded to.
set -euo pipefail

VERSION="${1:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
SHA="${2:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
DIST="${3:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
REMOTE="${CICADA_RELEASE_REMOTE:-origin}"
TAG="v$VERSION"
HERE="$(cd "$(dirname "$0")" && pwd)"
STABLE="Cicada-macos-arm64.zip"
FILES=("$DIST/Cicada-$VERSION.zip" "$DIST/Cicada-$VERSION.zip.sig" "$DIST/latest.json" "$DIST/$STABLE")

die() { echo "✗ $*" >&2; exit 1; }

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "not a release version: $VERSION"
for f in "${FILES[@]}"; do [ -s "$f" ] || die "missing or empty: $f"; done
cmp -s "$DIST/Cicada-$VERSION.zip" "$DIST/$STABLE" || die "$STABLE is not the same bytes as Cicada-$VERSION.zip"

# "absent", "draft" or "published". Only GitHub's "release not found" means absent; any other error stops the run, so
# a failed lookup is never mistaken for no release.
release_state() {
  local json err
  err="$(mktemp)"
  if ! json="$(gh release view "$TAG" --json isDraft,assets,tagName 2>"$err")"; then
    if grep -qi "not found" "$err"; then rm -f "$err"; echo absent; return 0; fi
    cat "$err" >&2; rm -f "$err"; return 1
  fi
  rm -f "$err"
  python3 -c 'import json,sys; print("draft" if json.loads(sys.argv[1])["isDraft"] else "published")' "$json"
}

state="$(release_state)"
[ "$state" = published ] && { echo "$TAG is already released — nothing to publish"; exit 0; }

# The version against the live tags, now.
TMP="$(mktemp -d)"
printf '%s\n' "$VERSION" > "$TMP/VERSION"
git ls-remote --tags --refs "$REMOTE" 'refs/tags/v*' > "$TMP/tags.txt"
python3 "$HERE/check_version.py" plan --root "$TMP" < "$TMP/tags.txt" > "$TMP/plan.txt"
status="$(sed -n 's/^status=//p' "$TMP/plan.txt")"
LATEST="$(sed -n 's/^latest=//p' "$TMP/plan.txt")"
PREVIOUS="$(sed -n 's/^previous=//p' "$TMP/plan.txt")"
rm -rf "$TMP"
[ "$status" = released ] && { echo "$TAG is already released — nothing to publish"; exit 0; }
[ "$status" = new ] || die "unexpected plan for $TAG: $status"

if [ "$state" = draft ]; then
  echo "! a draft $TAG was left by an earlier failed run; it was never published — replacing it"
  gh release delete "$TAG" --yes
fi

CREATED=0
cleanup() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$CREATED" = 1 ] && [ "$(release_state || echo unknown)" = draft ]; then
    echo "✗ publishing $TAG failed — deleting the draft so nothing is advertised" >&2
    gh release delete "$TAG" --yes || true
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
