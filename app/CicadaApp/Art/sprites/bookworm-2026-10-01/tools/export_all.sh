#!/bin/bash
# Run B extends the builders and verifier; the worm stage is independently usable.
set -euo pipefail
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"
BUILDS="${BUILDS:-build_worm build_worm_small build_room build_weather build_spines}"
STAGE="${STAGE:-all}"
ART="$(cd "$(dirname "$0")/.." && pwd)"
RES="$(cd "$ART/../../../Sources/CicadaApp/Resources" && pwd)/sprites"
mkdir -p "$RES" "$ART/src" "$ART/qa"
for build in $BUILDS; do
  "$ASE" -b --script-param art="$ART" --script "$ART/lua/$build.lua"
done
for src in "$ART"/src/*.aseprite; do
  name="$(basename "$src" .aseprite)"
  [[ "$STAGE" != worm || "$name" == bookworm-* ]] || continue
  rm -f "$RES/$name.png" "$RES/$name.json"
  "$ASE" -b "$src" --sheet "$RES/$name.png" --data "$RES/$name.json" \
    --format json-array --sheet-pack --list-tags --list-slices
  [[ -s "$RES/$name.png" && -s "$RES/$name.json" ]] || { echo "export failed: $name" >&2; exit 1; }
done
if [[ "$STAGE" == all ]]; then
  python3 "$ART/tools/verify.py"
  python3 "$ART/tools/manifest.py"
  python3 "$ART/tools/make_preview.py"
else
  python3 "$ART/tools/verify.py" --worm-only
fi
echo "sprites: OK ($STAGE)"
