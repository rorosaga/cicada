#!/usr/bin/env bash
# Cut a Cicada release (G182): bump the version on dev, merge dev into main,
# tag vX.Y.Z and push — the tag starts .github/workflows/release.yml, which
# builds, signs and publishes the GitHub Release. Run by the owner only
# (`make release VERSION=x.y.z`), when dev is ready to become main.
#
# It works in a temporary worktree, so the checkout it is run from (and its
# dev auto-updater) is never switched, stashed or touched; nothing is pushed
# until every step has succeeded, and then dev, main and the tag go up in one
# atomic push.
#
# Usage: scripts/release/release.sh X.Y.Z [--dry-run] [--yes]
#   --dry-run   do everything locally and show what would be pushed; push nothing
#   --yes       don't ask before pushing
set -euo pipefail

VERSION="${1:-}"
DRY_RUN=0
ASSUME_YES=0
for arg in "${@:2}"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: release.sh X.Y.Z [--dry-run] [--yes]" >&2; exit 2; }

REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
REMOTE="${CICADA_RELEASE_REMOTE:-origin}"
TAG="v$VERSION"

git -C "$REPO" fetch -q "$REMOTE" dev main --tags
if git -C "$REPO" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "✗ $TAG already exists" >&2; exit 1
fi
current="$(git -C "$REPO" show "$REMOTE/dev:VERSION" | tr -d '[:space:]')"
newest="$(printf '%s\n%s\n' "$current" "$VERSION" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
if [ "$VERSION" != "$current" ] && [ "$newest" != "$VERSION" ]; then
  echo "✗ $VERSION is older than dev's $current" >&2; exit 1
fi
git -C "$REPO" merge-base --is-ancestor "$REMOTE/main" "$REMOTE/dev" \
  || echo "! main has commits dev does not; the merge below keeps both"

WORK="$(mktemp -d)"
cleanup() { git -C "$REPO" worktree remove --force "$WORK" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
git -C "$REPO" worktree add -q --detach "$WORK" "$REMOTE/dev"
cd "$WORK"

# 1. The version, on dev: VERSION, pyproject and uv.lock's project line move together.
if [ "$VERSION" != "$current" ]; then
  printf '%s\n' "$VERSION" > VERSION
  sed -i '' -E "s/^version = \"[0-9]+\.[0-9]+\.[0-9]+\"$/version = \"$VERSION\"/" api/pyproject.toml
  /usr/bin/python3 - "$VERSION" <<'PY'
import re, sys
p = "api/uv.lock"
s = open(p, encoding="utf-8").read()
s, n = re.subn(r'(name = "cicada-api"\nversion = ")[^"]+(")', rf'\g<1>{sys.argv[1]}\2', s)
assert n == 1, "uv.lock's cicada-api entry not found"
open(p, "w", encoding="utf-8").write(s)
PY
  git add VERSION api/pyproject.toml api/uv.lock
  git commit -q -m "release: $TAG"
fi
DEV_COMMIT="$(git rev-parse HEAD)"

# 2. main takes dev, as a merge (promotion stays a visible, deliberate step).
git checkout -q --detach "$REMOTE/main"
git merge -q --no-ff "$DEV_COMMIT" -m "Release $TAG"
git tag -a "$TAG" -m "Cicada $VERSION"
MAIN_COMMIT="$(git rev-parse HEAD)"

echo "Release $TAG"
echo "  dev  → $(git rev-parse --short "$DEV_COMMIT")  (version $VERSION)"
echo "  main → $(git rev-parse --short "$MAIN_COMMIT")  (merge of dev)"
echo "  tag  → $TAG  (starts the Release workflow)"
if [ "$DRY_RUN" = "1" ]; then
  git push --dry-run --atomic "$REMOTE" "$DEV_COMMIT:refs/heads/dev" "$MAIN_COMMIT:refs/heads/main" "refs/tags/$TAG"
  echo "(dry run: nothing pushed)"
  git tag -d "$TAG" >/dev/null
  exit 0
fi
if [ "$ASSUME_YES" != "1" ]; then
  read -r -p "Push dev, main and $TAG to $REMOTE? [y/N] " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { git tag -d "$TAG" >/dev/null; echo "nothing pushed"; exit 1; }
fi
git push --atomic "$REMOTE" "$DEV_COMMIT:refs/heads/dev" "$MAIN_COMMIT:refs/heads/main" "refs/tags/$TAG"
echo "✓ pushed — watch the build: gh run watch \$(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')"
