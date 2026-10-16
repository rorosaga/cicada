#!/usr/bin/env bash
# Put the `cicada` command on PATH for a source checkout (G180, TODO ruling 21): one link,
# ~/.local/bin/cicada -> <this checkout>/scripts/cicada, no admin. `make cli` and `./install.sh --cli`
# run this; a release app does the same from Settings -> General, linking its own launcher.
#
# The same rules as the app's button: a missing path or a dangling link is (re)written; an existing
# link that already works, or anything that is not a link, is left alone and named.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
TARGET="$HERE/cicada"
DIR="$HOME/.local/bin"
LINK="$DIR/cicada"

[ -x "$TARGET" ] || { echo "cicada: $TARGET is missing or not executable" >&2; exit 1; }
mkdir -p "$DIR"

if [ -L "$LINK" ]; then
  if [ "$LINK" -ef "$TARGET" ]; then
    echo "cicada: already installed ($LINK -> $TARGET)"
    exit 0
  elif [ -e "$LINK" ]; then
    echo "cicada: $LINK already points at $(readlink "$LINK"); left it alone." >&2
    exit 1
  fi
  rm "$LINK"   # dangling: nothing works through it, so it is replaced
elif [ -e "$LINK" ]; then
  echo "cicada: $LINK exists and is not a link; left it alone." >&2
  exit 1
fi

ln -s "$TARGET" "$LINK"
echo "cicada: linked $LINK -> $TARGET"
case ":${PATH}:" in
  *":$DIR:"*) ;;
  *) echo "cicada: $DIR is not on this shell's PATH; add to your shell profile:"
     echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
