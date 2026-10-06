#!/usr/bin/env bash
# Publish a built release on GitHub (G182, TODO ruling 19) — the only step that advertises anything.
#
#   publish.sh X.Y.Z <commit-sha> <dist-dir>        env: GH_TOKEN, GH_REPO=owner/repo; run from a checkout of the repo
#
# dist-dir holds Cicada-X.Y.Z.zip, its .sig, latest.json and Cicada-macos-arm64.zip (the same bytes under a name that
# never changes, so .../releases/latest/download/Cicada-macos-arm64.zip always resolves).
#
# 1. A published release for vX.Y.Z → nothing to do, exit 0.
# 2. The version is judged against the remote's live tags (check_version.py plan), not taken from the plan job:
#    "Re-run failed jobs" reuses that job's outputs, and a newer release may exist by now. Already tagged → exit 0;
#    not greater than the latest tag → fail.
# 3. Only the commit at main's tip may publish — checked before the draft is made and again just before it is
#    published. A superseded run exits 0 ("that run releases main") and deletes only the draft it made. So if two
#    release merges land before the first publishes, only the newer one ships.
# 4. The release is made as a draft at <commit-sha> — GitHub creates the tag only when a draft is published — every
#    asset is checked by name and size, and then it is published and marked latest.
# Releases are addressed by id, never by tag: runs for different commits may overlap, and GitHub lets two drafts
# share a tag name. "This run's draft" is the draft with this tag *and* this commit as its target (runs for one
# commit never overlap). Any failure deletes it, so a failed run advertises nothing; a draft has no tag, so no tag is
# ever deleted here. A published release is never edited, deleted or re-uploaded to.
set -euo pipefail

VERSION="${1:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
SHA="${2:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
DIST="${3:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
: "${GH_REPO:?set GH_REPO to owner/repo}"
REMOTE="${CICADA_RELEASE_REMOTE:-origin}"
TAG="v$VERSION"
API="repos/$GH_REPO/releases"
HERE="$(cd "$(dirname "$0")" && pwd)"
STABLE="Cicada-macos-arm64.zip"
FILES=("$DIST/Cicada-$VERSION.zip" "$DIST/Cicada-$VERSION.zip.sig" "$DIST/latest.json" "$DIST/$STABLE")

die() { echo "✗ $*" >&2; exit 1; }

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "not a release version: $VERSION"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "not a full commit sha: $SHA"
for f in "${FILES[@]}"; do [ -s "$f" ] || die "missing or empty: $f"; done
cmp -s "$DIST/Cicada-$VERSION.zip" "$DIST/$STABLE" || die "$STABLE is not the same bytes as Cicada-$VERSION.zip"

WORK="$(mktemp -d)"
CREATED=0

# Every release, fetched fresh; any error stops the run (a failed lookup is never read as "no release").
fetch_releases() {
  gh api --paginate --slurp "$API?per_page=100" > "$WORK/releases.json" || die "couldn't list $GH_REPO's releases"
}
# From the last fetch: `published` → yes|no for vX.Y.Z; `mine` → the ids of this run's drafts (this tag, this commit).
query() {
  python3 - "$1" "$TAG" "$SHA" "$WORK/releases.json" <<'PY'
import json, sys
mode, tag, sha, path = sys.argv[1:]
named = [r for page in json.load(open(path)) for r in page if r.get("tag_name") == tag]
if mode == "published":
    print("yes" if any(not r["draft"] for r in named) else "no")
else:
    print(" ".join(str(r["id"]) for r in named if r["draft"] and r.get("target_commitish") == sha))
PY
}
delete_mine() {
  local id
  fetch_releases
  for id in $(query mine); do gh api -X DELETE "$API/$id" > /dev/null; done
}
# True when main has moved past this run's commit; SUPERSEDED_BY names the tip.
SUPERSEDED_BY=""
superseded() {
  local tip
  tip="$(git ls-remote "$REMOTE" refs/heads/main | cut -f1)" || die "couldn't read main on $REMOTE"
  [ -n "$tip" ] || die "couldn't read main on $REMOTE"
  SUPERSEDED_BY="$tip"
  [ "$tip" != "$SHA" ]
}
cleanup() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$CREATED" = 1 ]; then
    echo "✗ publishing $TAG failed — deleting this run's draft so nothing is advertised" >&2
    delete_mine || true
  fi
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

fetch_releases
[ "$(query published)" = yes ] && { echo "$TAG is already released — nothing to publish"; exit 0; }

# The version against the live tags, now.
printf '%s\n' "$VERSION" > "$WORK/VERSION"
git ls-remote --tags --refs "$REMOTE" 'refs/tags/v*' > "$WORK/tags.txt"
python3 "$HERE/check_version.py" plan --root "$WORK" < "$WORK/tags.txt" > "$WORK/plan.txt"
status="$(sed -n 's/^status=//p' "$WORK/plan.txt")"
LATEST="$(sed -n 's/^latest=//p' "$WORK/plan.txt")"
PREVIOUS="$(sed -n 's/^previous=//p' "$WORK/plan.txt")"
[ "$status" = released ] && { echo "$TAG is already released — nothing to publish"; exit 0; }
[ "$status" = new ] || die "unexpected plan for $TAG: $status"

if superseded; then
  echo "$TAG: ${SHA:0:12} is superseded by ${SUPERSEDED_BY:0:12} on main — that run releases main; nothing published here"
  exit 0
fi

leftover="$(query mine)"
if [ -n "$leftover" ]; then
  echo "! a draft $TAG for this commit was left by an earlier failed run; it was never published — replacing it"
  for id in $leftover; do gh api -X DELETE "$API/$id" > /dev/null; done
fi

notes=(--notes-file "$HERE/release-notes-header.md" --generate-notes)
[ -n "$PREVIOUS" ] && notes+=(--notes-start-tag "$PREVIOUS")

CREATED=1
gh release create "$TAG" "${FILES[@]}" --draft --target "$SHA" --title "Cicada $VERSION" "${notes[@]}"

fetch_releases
ids="$(query mine)"
[[ "$ids" =~ ^[0-9]+$ ]] || die "expected exactly one draft $TAG at ${SHA:0:12}, found: ${ids:-none}"
ID="$ids"

# Every asset is there, at its exact size, before anything is advertised.
gh api "$API/$ID" > "$WORK/release.json"
python3 - "$WORK/release.json" "${FILES[@]}" <<'PY'
import json, os, sys
release = json.load(open(sys.argv[1]))
have = {a["name"]: a["size"] for a in release["assets"]}
want = {os.path.basename(p): os.path.getsize(p) for p in sys.argv[2:]}
wrong = [f"{name} ({have.get(name, 'missing')} bytes, expected {size})" for name, size in want.items()
         if have.get(name) != size]
if not release["draft"] or wrong:
    sys.exit("the draft's assets are wrong: " + ", ".join(wrong or ["not a draft"]))
PY

if superseded; then
  echo "$TAG: ${SHA:0:12} was superseded by ${SUPERSEDED_BY:0:12} on main while drafting — that run releases main;" \
       "deleting this run's draft, nothing published here"
  delete_mine
  CREATED=0
  exit 0
fi

gh api -X PATCH "$API/$ID" -F draft=false -f make_latest="$LATEST" > /dev/null
gh api "$API/$ID" > "$WORK/release.json"
python3 -c 'import json,sys; sys.exit(0 if not json.load(open(sys.argv[1]))["draft"] else 1)' "$WORK/release.json" \
  || die "$TAG did not publish"
CREATED=0
echo "✓ published $TAG at ${SHA:0:12} (latest=$LATEST)"
