#!/usr/bin/env bash
# Sign a release Cicada.app inside out (G182): every Mach-O file first, deepest
# path first, then each nested bundle, then the app. Never `codesign --deep`:
# Apple's own guidance is to sign each piece of nested code explicitly, and
# that is what makes adding a Developer ID and notarization later a change to
# the identity and two flags rather than a rewrite.
#
# Usage: scripts/release/sign-app.sh <path/to/Cicada.app>
# Env:
#   CICADA_SIGN_IDENTITY   "-" (ad hoc, the default) or a Developer ID Application identity.
#                          With a real identity the signature gets the hardened runtime
#                          (--options runtime), a secure timestamp and the entitlements in
#                          Cicada.entitlements — see docs/RELEASING.md.
set -euo pipefail

APP="${1:?usage: sign-app.sh <Cicada.app>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
IDENTITY="${CICADA_SIGN_IDENTITY:--}"
[ -d "$APP/Contents/MacOS" ] || { echo "not an app bundle: $APP" >&2; exit 2; }

args=(--force --sign "$IDENTITY")
app_args=()
if [ "$IDENTITY" != "-" ]; then
  args+=(--options runtime --timestamp)
  app_args+=(--entitlements "$HERE/Cicada.entitlements")
fi

# Extended attributes (com.apple.provenance, FinderInfo) make codesign refuse.
xattr -cr "$APP" 2>/dev/null || true

# Every Mach-O file by its magic number (thin 64-bit either endianness, or fat),
# deepest first so a library is signed before anything that contains it.
list_macho() {
  /usr/bin/env python3 - "$1" <<'PY'
import os, sys
MAGIC = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
root = sys.argv[1]
found = []
for dirpath, _dirs, files in os.walk(root):
    for name in files:
        path = os.path.join(dirpath, name)
        if os.path.islink(path):
            continue
        try:
            with open(path, "rb") as fh:
                head = fh.read(8)
        except OSError:
            continue
        if head[:4] in MAGIC:
            # A Java class file shares 0xcafebabe; a fat Mach-O's arch count is small.
            if head[:4] == b"\xca\xfe\xba\xbe" and int.from_bytes(head[4:8], "big") > 30:
                continue
            found.append(path)
found.sort(key=lambda p: (-p.count(os.sep), p))
sys.stdout.write("\0".join(found))
PY
}

MAIN="$APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist")"
count=0
while IFS= read -r -d '' f; do
  [ "$f" = "$MAIN" ] && continue
  codesign "${args[@]}" "$f" 2>&1 | { grep -v ': replacing existing signature$' || true; }
  count=$((count + 1))
done < <(list_macho "$APP/Contents"; printf '\0')
echo "  signed $count nested Mach-O files ($([ "$IDENTITY" = "-" ] && echo "ad hoc" || echo "$IDENTITY"))"

# Nested bundles (the SwiftPM resource bundle), deepest first, then the app.
while IFS= read -r b; do
  [ -n "$b" ] && codesign "${args[@]}" "$b"
done < <(find "$APP/Contents" -type d -name '*.bundle' -o -type d -name '*.framework' | awk '{print gsub("/","/"), $0}' | sort -rn | cut -d' ' -f2-)
codesign "${args[@]}" ${app_args[@]+"${app_args[@]}"} "$APP"

# Verification may walk everything; only signing must not.
codesign --verify --strict --deep "$APP"
echo "  ✓ $APP verifies (codesign --verify --strict --deep)"
