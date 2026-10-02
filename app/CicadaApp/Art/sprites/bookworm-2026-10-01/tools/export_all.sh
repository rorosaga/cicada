#!/bin/bash
# Saved Aseprite sources own the pixels; every builder reads them and every sheet is re-exported.
set -euo pipefail
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"
BUILDS="${BUILDS:-build_worm build_worm_small build_room build_weather build_spines}"
STAGE="${STAGE:-all}"
ART="$(cd "$(dirname "$0")/.." && pwd)"
RES="$(cd "$ART/../../../Sources/CicadaApp/Resources" && pwd)/sprites"
mkdir -p "$RES" "$ART/src" "$ART/qa"
run_lua() {
  local script="$1" status="$ART/qa/.lua-completed"
  rm -f "$status"
  "$ASE" -b --script-param art="$ART" --script-param run="$script" \
    --script-param status="$status" --script "$ART/lua/run_checked.lua"
  if [[ ! -f "$status" || "$(cat "$status")" != completed ]]; then
    echo "Lua did not complete: $script" >&2
    exit 1
  fi
  rm -f "$status"
}
for build in $BUILDS; do
  run_lua "$build"
done
if [[ "$STAGE" == all ]]; then
  run_lua check_room_parts
fi
for src in "$ART"/src/*.aseprite; do
  name="$(basename "$src" .aseprite)"
  [[ "$STAGE" != worm || "$name" == bookworm-* ]] || continue
  rm -f "$RES/$name.png" "$RES/$name.json"
  "$ASE" -b "$src" --sheet "$RES/$name.png" --data "$RES/$name.json" \
    --format json-array --sheet-pack --list-tags --list-slices
  [[ -s "$RES/$name.png" && -s "$RES/$name.json" ]] || { echo "export failed: $name" >&2; exit 1; }
done
if [[ "$STAGE" == all ]]; then
  python3 "$ART/tools/manifest.py"
  python3 "$ART/tools/verify.py"
  python3 "$ART/tools/make_preview.py"
else
  python3 "$ART/tools/verify.py" --worm-only
fi
echo "sprites: OK ($STAGE)"
