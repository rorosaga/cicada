#!/bin/bash
# Saved Aseprite sources own the pixels; every builder reads them and every sheet is re-exported.
set -euo pipefail
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"
BUILDS="${BUILDS:-build_worm build_worm_small build_room build_clock build_weather build_skyfx build_spines}"
STAGE="${STAGE:-all}"
case "$STAGE" in all|worm) ;; *) echo "Unknown stage: $STAGE" >&2; exit 1 ;; esac
want_clock=false
want_scenery=false
want_spines=false
for build in $BUILDS; do
  case "$build" in
    build_clock) want_clock=true ;;
    build_weather|build_skyfx) want_scenery=true ;;
    build_spines) want_spines=true ;;
    build_worm|build_worm_small|build_room|build_night) ;;
    *) echo "Unknown builder: $build" >&2; exit 1 ;;
  esac
done
# Every delivery includes night art. Its day worm/prop prerequisites always rebuild from saved parts.
# A partial weather/fx request rebuilds both in order: weather owns the base motion records.
BUILDS="build_worm build_worm_small build_room"
[[ "$want_clock" != true ]] || BUILDS="$BUILDS build_clock"
if [[ "$want_scenery" == true ]]; then
  BUILDS="$BUILDS build_weather build_skyfx"
fi
[[ "$want_spines" != true ]] || BUILDS="$BUILDS build_spines"
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
run_lua check_room_parts
run_lua build_night
for src in "$ART"/src/*.aseprite; do
  name="$(basename "$src" .aseprite)"
  rm -f "$RES/$name.png" "$RES/$name.json"
  "$ASE" -b "$src" --sheet "$RES/$name.png" --data "$RES/$name.json" \
    --format json-array --sheet-pack --list-tags --list-slices
  [[ -s "$RES/$name.png" && -s "$RES/$name.json" ]] || { echo "export failed: $name" >&2; exit 1; }
done
# STAGE=worm narrows the requested authoring work, never the delivered-sheet acceptance contract.
python3 "$ART/tools/manifest.py"
python3 "$ART/tools/verify.py"
python3 "$ART/tools/make_preview.py"
echo "sprites: OK ($STAGE)"
