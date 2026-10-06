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
# 4. The draft is created through the REST API and owned by the id in that response — never rediscovered through the
#    releases list, which lags. Each asset is uploaded to that id, and the draft is read back by id (tag, target,
#    every asset's name and size) before anything is advertised.
# 5. Publication is a PATCH of that id spelling out tag_name and target_commitish (a PATCH that omits tag_name drops
#    the tag), draft=false and make_latest. GitHub creates the tag then. Afterwards the release must read back public
#    under vX.Y.Z, and the remote's real tag must point at <commit-sha>; anything else fails loudly — a public release
#    is never deleted, retagged or re-uploaded to; the log says what a human must check.
# Any failure before publication deletes the id this run created and nothing else; a draft has no tag, so no tag is
# ever deleted here. The releases list is read once, for drafts an earlier failed run of this same commit left behind.
set -euo pipefail

VERSION="${1:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
SHA="${2:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
DIST="${3:?usage: publish.sh X.Y.Z <commit-sha> <dist-dir>}"
: "${GH_REPO:?set GH_REPO to owner/repo}"
REMOTE="${CICADA_RELEASE_REMOTE:-origin}"
POLL_DELAY="${CICADA_PUBLISH_POLL_DELAY:-3}"
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
ID=""            # the release this run created, from the create response; the only one it may delete
PUBLISHED=0

# A field of a JSON file: json FILE KEY.
json() { python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(json.dumps(v) if isinstance(v,bool) else v)' "$1" "$2"; }

# True when main has moved past this run's commit; SUPERSEDED_BY names the tip.
SUPERSEDED_BY=""
superseded() {
  local tip
  tip="$(git ls-remote "$REMOTE" refs/heads/main | cut -f1)" || die "couldn't read main on $REMOTE"
  [ -n "$tip" ] || die "couldn't read main on $REMOTE"
  SUPERSEDED_BY="$tip"
  [ "$tip" != "$SHA" ]
}

# Delete release $1 only while it is still a draft.
delete_draft() {
  gh api "$API/$1" > "$WORK/check.json" || { echo "! couldn't read release $1 — check it by hand" >&2; return 1; }
  if [ "$(json "$WORK/check.json" draft)" = true ]; then
    gh api -X DELETE "$API/$1" > /dev/null
  else
    echo "! release $1 is public — not touched; check it by hand on the Releases page" >&2
  fi
}

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ] && [ -n "$ID" ] && [ "$PUBLISHED" = 0 ]; then
    echo "✗ publishing $TAG failed — deleting the draft this run created (id $ID) so nothing is advertised" >&2
    delete_draft "$ID" || true
  fi
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

# The list, once: a published vX.Y.Z, and drafts an earlier failed run of this commit left. Any error stops the run.
gh api --paginate --slurp "$API?per_page=100" > "$WORK/releases.json" || die "couldn't list $GH_REPO's releases"
python3 - "$TAG" "$SHA" "$WORK/releases.json" > "$WORK/listing.txt" <<'PY'
import json, sys
tag, sha, path = sys.argv[1:]
named = [r for page in json.load(open(path)) for r in page if r.get("tag_name") == tag]
print("published=" + ("yes" if any(not r["draft"] for r in named) else "no"))
print("leftovers=" + " ".join(str(r["id"]) for r in named if r["draft"] and r.get("target_commitish") == sha))
PY
[ "$(sed -n 's/^published=//p' "$WORK/listing.txt")" = yes ] && { echo "$TAG is already released — nothing to publish"; exit 0; }
leftovers="$(sed -n 's/^leftovers=//p' "$WORK/listing.txt")"

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

for id in $leftovers; do
  echo "! a draft $TAG for this commit (id $id) was left by an earlier failed run; it was never published — replacing it"
  delete_draft "$id"
done

# Notes: the fixed header, then GitHub's notes for the PRs merged since the previous tag.
notes_args=(-f tag_name="$TAG" -f target_commitish="$SHA")
[ -n "$PREVIOUS" ] && notes_args+=(-f previous_tag_name="$PREVIOUS")
gh api -X POST "$API/generate-notes" "${notes_args[@]}" > "$WORK/notes.json"
python3 - "$TAG" "$SHA" "Cicada $VERSION" "$HERE/release-notes-header.md" "$WORK/notes.json" > "$WORK/create.json" <<'PY'
import json, sys
tag, sha, name, header, notes = sys.argv[1:]
body = open(header, encoding="utf-8").read().rstrip() + "\n\n" + json.load(open(notes))["body"]
json.dump({"tag_name": tag, "target_commitish": sha, "name": name, "body": body, "draft": True}, sys.stdout)
PY

gh api -X POST "$API" --input "$WORK/create.json" > "$WORK/created.json"
ID="$(json "$WORK/created.json" id)"
[[ "$ID" =~ ^[0-9]+$ ]] || die "the create response carried no release id"
upload_url="$(json "$WORK/created.json" upload_url)"
upload_url="${upload_url%%\{*}"
[[ "$upload_url" == https://*"/releases/$ID/assets" ]] || die "release $ID's upload URL isn't its own: $upload_url"

for f in "${FILES[@]}"; do
  gh api -X POST "$upload_url?name=$(basename "$f")" -H "Content-Type: application/octet-stream" --input "$f" \
    > /dev/null
done

# The draft, read back by id, before anything is advertised: its tag, its target, every asset at its exact size.
gh api "$API/$ID" > "$WORK/draft.json"
python3 - "$TAG" "$SHA" "$WORK/draft.json" "${FILES[@]}" <<'PY'
import json, os, sys
tag, sha, path, files = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
r = json.load(open(path))
problems = []
if r.get("tag_name") != tag: problems.append(f"tag {r.get('tag_name')!r}, expected {tag}")
if r.get("target_commitish") != sha: problems.append(f"target {r.get('target_commitish')!r}, expected {sha}")
if r.get("draft") is not True: problems.append("not a draft")
have = {a["name"]: a["size"] for a in r.get("assets", [])}
for p in files:
    name, size = os.path.basename(p), os.path.getsize(p)
    if have.get(name) != size:
        problems.append(f"{name} is {have.get(name, 'missing')} bytes, expected {size}")
if problems:
    sys.exit("the draft is wrong: " + "; ".join(problems))
PY

if superseded; then
  echo "$TAG: ${SHA:0:12} was superseded by ${SUPERSEDED_BY:0:12} on main while drafting — that run releases main;" \
       "deleting this run's draft (id $ID), nothing published here"
  delete_draft "$ID"
  ID=""
  exit 0
fi

# Publish. From here the release may be public: nothing below deletes, retags or re-uploads.
gh api -X PATCH "$API/$ID" -f tag_name="$TAG" -f target_commitish="$SHA" -F draft=false -f make_latest="$LATEST" \
  > /dev/null
PUBLISHED=1

gh api "$API/$ID" > "$WORK/published.json"
got_tag="$(json "$WORK/published.json" tag_name)"
got_draft="$(json "$WORK/published.json" draft)"
if [ "$got_tag" != "$TAG" ] || [ "$got_draft" != false ]; then
  die "release $ID reads back as tag '$got_tag', draft=$got_draft — expected $TAG, public. Nothing was retagged or" \
      "overwritten. By hand: open the release, and if it is public under the wrong tag, unpublish it (mark it draft)" \
      "and re-run the Release workflow on main."
fi

# The remote's real tag, peeled, must be this commit (an existing tag would have won over target_commitish).
tag_sha=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  git ls-remote "$REMOTE" "refs/tags/$TAG" "refs/tags/$TAG^{}" > "$WORK/tag.txt"
  tag_sha="$(awk -v t="refs/tags/$TAG" '$2==t"^{}"{p=$1} $2==t{l=$1} END{print (p!="" ? p : l)}' "$WORK/tag.txt")"
  [ -n "$tag_sha" ] && break
  sleep "$POLL_DELAY"
done
[ -n "$tag_sha" ] || die "release $ID is public but $TAG did not appear on $REMOTE. Nothing was retagged. By hand:" \
  "check the release's tag on GitHub before telling anyone about $TAG."
[ "$tag_sha" = "$SHA" ] || die "$TAG points at ${tag_sha:0:12}, not this run's ${SHA:0:12}. The release is public;" \
  "nothing was retagged or overwritten. By hand: decide which commit $TAG should name; if it is wrong, unpublish the" \
  "release, fix the tag, and re-run the Release workflow on main."

echo "✓ published $TAG at ${SHA:0:12} (release $ID, latest=$LATEST)"
