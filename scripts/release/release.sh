#!/usr/bin/env bash
# Open the two pull requests a Cicada release takes (G182, TODO ruling 19). Merging the second is the release:
# CI on main tags vX.Y.Z at the merge, builds, verifies and publishes the GitHub Release. This script only opens PRs —
# it never pushes main, never tags and never force-pushes.
#
#   release.sh bump X.Y.Z [--dry-run] [--yes]   (make release VERSION=X.Y.Z)
#       Bumps VERSION, api/pyproject.toml and uv.lock's project line on a `release/vX.Y.Z` branch off the remote's
#       dev, pushes that branch and opens a PR to dev titled `chore(release): X.Y.Z`. Refuses a version that is
#       already tagged or not greater than the latest tag. When dev already says X.Y.Z there is nothing to bump.
#   release.sh pr [--dry-run] [--yes]           (make release-pr)
#       Opens the dev → main PR titled `Release vX.Y.Z` for the version dev says, refusing one that is already
#       released. An open dev → main PR is reported, not duplicated.
#
#   --dry-run   check everything and show what would be pushed and opened; push and open nothing
#   --yes       don't ask before pushing or opening
#
# Work happens in a temporary worktree, so the checkout this runs from is never switched, stashed or touched.
set -euo pipefail

CMD="${1:-}"
shift || true
VERSION=""
if [ "$CMD" = "bump" ]; then VERSION="${1:-}"; shift || true; fi
DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done
usage() { echo "usage: release.sh bump X.Y.Z [--dry-run] [--yes] | release.sh pr [--dry-run] [--yes]" >&2; exit 2; }
case "$CMD" in
  bump) [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage ;;
  pr) ;;
  *) usage ;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
REMOTE="${CICADA_RELEASE_REMOTE:-origin}"
CHECK="$HERE/check_version.py"
TMP="$(mktemp -d)"
WORK=""
cleanup() {
  [ -n "$WORK" ] && git -C "$REPO" worktree remove --force "$WORK" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

die() { echo "✗ $*" >&2; exit 1; }
confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  read -r -p "$1 [y/N] " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "nothing pushed or opened"; exit 1; }
}

git -C "$REPO" fetch -q "$REMOTE" dev
git -C "$REPO" ls-remote --tags --refs "$REMOTE" 'refs/tags/v*' > "$TMP/tags.txt"

# What CI would decide for a version: prints the plan's status, or dies with check_version.py's reason.
judge() {
  mkdir -p "$TMP/judge"
  printf '%s\n' "$1" > "$TMP/judge/VERSION"
  python3 "$CHECK" plan --root "$TMP/judge" < "$TMP/tags.txt" > "$TMP/plan.txt" || exit 1
  sed -n 's/^status=//p' "$TMP/plan.txt"
}

# dev's own version files, checked to agree.
mkdir -p "$TMP/dev"
git -C "$REPO" archive "$REMOTE/dev" VERSION api/pyproject.toml api/uv.lock | tar -x -C "$TMP/dev"
python3 "$CHECK" agree --root "$TMP/dev"
DEV_VERSION="$(tr -d '[:space:]' < "$TMP/dev/VERSION")"

if [ "$CMD" = "bump" ]; then
  TAG="v$VERSION"
  [ "$(judge "$VERSION")" = "released" ] && die "$TAG is already released — pick the next version"
  if [ "$VERSION" = "$DEV_VERSION" ]; then
    echo "dev already says $VERSION — nothing to bump."
    echo "Next: make release-pr   (opens dev → main; merging it releases $TAG)"
    exit 0
  fi
  newest="$(printf '%s\n%s\n' "$DEV_VERSION" "$VERSION" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
  [ "$newest" = "$VERSION" ] || die "$VERSION is older than dev's $DEV_VERSION"
  BRANCH="release/$TAG"
  [ -z "$(git -C "$REPO" ls-remote --heads "$REMOTE" "$BRANCH")" ] \
    || die "$BRANCH already exists on $REMOTE — merge or close its PR first"

  WORK="$TMP/worktree"
  git -C "$REPO" worktree add -q --detach "$WORK" "$REMOTE/dev"
  # VERSION, pyproject's [project] version and uv.lock's cicada-api entry move together.
  python3 - "$WORK" "$VERSION" <<'PY'
import re, sys
from pathlib import Path
root, version = Path(sys.argv[1]), sys.argv[2]
(root / "VERSION").write_text(version + "\n", encoding="utf-8")
for rel, pattern in (("api/pyproject.toml", r'(\[project\][^\[]*?^version = ")[^"]+(")'),
                     ("api/uv.lock", r'(^name = "cicada-api"\nversion = ")[^"]+(")')):
    path = root / rel
    text, n = re.subn(pattern, rf"\g<1>{version}\g<2>", path.read_text(encoding="utf-8"), count=1, flags=re.M | re.S)
    assert n == 1, f"{rel}: the version line was not found"
    path.write_text(text, encoding="utf-8")
PY
  python3 "$CHECK" agree --root "$WORK"
  git -C "$WORK" add VERSION api/pyproject.toml api/uv.lock
  git -C "$WORK" commit -q -m "chore(release): $VERSION"
  echo "Release $TAG — step 1 of 2"
  echo "  branch $BRANCH → $(git -C "$WORK" rev-parse --short HEAD)  ($DEV_VERSION → $VERSION, off $REMOTE/dev)"
  echo "  PR     $BRANCH → dev, \"chore(release): $VERSION\""
  if [ "$DRY_RUN" = "1" ]; then
    git -C "$WORK" push --dry-run "$REMOTE" "HEAD:refs/heads/$BRANCH"
    echo "(dry run: nothing pushed or opened)"
    exit 0
  fi
  confirm "Push $BRANCH and open its PR to dev?"
  git -C "$WORK" push -q "$REMOTE" "HEAD:refs/heads/$BRANCH"
  (cd "$REPO" && gh pr create --base dev --head "$BRANCH" --title "chore(release): $VERSION" \
    --body "Bumps VERSION, api/pyproject.toml and api/uv.lock to $VERSION (G182). After it merges, \`make release-pr\` opens the dev → main release PR.")
  echo "✓ Next: merge that PR into dev, then run make release-pr"
  exit 0
fi

# pr: dev → main for the version dev says.
TAG="v$DEV_VERSION"
status="$(judge "$DEV_VERSION")"
[ "$status" = "released" ] && die "$TAG is already released — bump first: make release VERSION=x.y.z"
open_pr="$(cd "$REPO" && gh pr list --base main --head dev --state open --json url --jq '.[0].url // ""')"
if [ -n "$open_pr" ]; then
  echo "A dev → main PR is already open: $open_pr"
  echo "Merging it releases $TAG."
  exit 0
fi
BODY="Merging this PR releases Cicada $DEV_VERSION (G182, TODO ruling 19): CI on main tags $TAG at the merge commit, builds, verifies and publishes the GitHub Release.

Merge it with **Create a merge commit** — a squash or rebase would give main commits dev does not have."
echo "Release $TAG — step 2 of 2"
echo "  PR dev → main, \"Release $TAG\""
if [ "$DRY_RUN" = "1" ]; then
  echo "(dry run: nothing opened)"
  exit 0
fi
confirm "Open the dev → main PR for $TAG?"
(cd "$REPO" && gh pr create --base main --head dev --title "Release $TAG" --body "$BODY")
echo "✓ Merging it releases $TAG. Then: gh run watch \$(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')"
