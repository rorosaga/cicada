# Bookworm sprites — worm fix pass, 2026-10-01

The saved Aseprite parts are the pixel authority. This pass repairs Run A’s worm art; Run B supplies the room and the integration run connects the player to the app. The nine PNG/JSON pairs are already in the app’s flat `Resources/sprites/` directory. No Swift code changed here.

The room worm has broad green eyes, a solid right pupil, a left sliver and floating expression brows. The independent 18 × 18 menu icon keeps the owner’s normal plus pupils. **Owner 2026-10-01:** error uses centered black diagonal Xs in both eyes, with the worried brows and sweat drop. The same coloured `bookworm-small` sheet (`isTemplate = false`) keeps its dark outlines on light and dark bars. The dark variant and unused `e` / `worm.pupilError` and `R` / `worm.small.rimDark` palette entries are removed; `W` remains for room highlights. The menu lens widths and right reading gaze are preserved; review B12 awaits an owner decision.

## Sources and regeneration

`parts/worm-parts.aseprite` and `parts/worm-small-parts.aseprite` hold the finished components. **Do not delete them to regenerate the finished art.** `seed_parts.lua` only creates the original first version. `src/bookworm-*.aseprite` are the assembled animation sources; all exports are regenerated from their saved files. `build_worm_small.lua` also saves the editable normal-menu alias `menubar.aseprite` at this directory’s root.

From this directory:

```sh
BUILDS="build_worm build_worm_small" STAGE=worm tools/export_all.sh
python3 tools/make_review.py
python3 tools/make_wormfix_review.py
python3 tools/make_report.py
```

For a byte comparison, run `tools/check_wormfix_rebuild.py record` after a successful build, rebuild with the same command, then run `tools/check_wormfix_rebuild.py compare`. It compares 162 files: 12 saved sources/parts/alias, 18 sheet files, two demos and all 130 tag GIFs. The build uses Aseprite 1.3.18.6-dev, packed full-canvas frames, forward tags, binary alpha, palette colours and nearest-neighbour scaling.

The dated notes in [the spec](../../../../../docs/specs/2026-10-01-bookworm-sprites-spec.md) record the new lens slices, −2/+1 gaze clamp, structural-glass exception to the skin-outline rule, 5 × 6 sweat, pre-flip gaze hold, readable z size floor, visible cover overlap, connected landing squash and the owner’s black-X / single dark-outline menu decisions. Tags and all timing arrays stay unchanged.

## Animations

| Sheet | Canvas | Tags | Frames | Behavior |
|---|---|---:|---:|---|
| `bookworm-awake` | 64 × 48 | 18 | 135 | Breath, blink, tail overlap; gaze and reaction beats |
| `bookworm-reading` | 64 × 48 | 54 | 558 | Three cover cycles; ten lines, page turns and two-cover exchange |
| `bookworm-sleeping` | 64 × 48 | 4 | 57 | Rising z/zz/zzz, breathing, mumble, yawn and stretch |
| `bookworm-digesting` | 64 × 48 | 7 | 39 | Chewing, moving neck bulge, gulp and satisfaction |
| `bookworm-happy` | 64 × 48 | 19 | 135 | Floating brows, glint, gaze beats and cheer with a landing squash |
| `bookworm-hungry` | 64 × 48 | 18 | 118 | Curved heavy lids, gaze, delayed exhale and yawn |
| `bookworm-error` | 64 × 48 | 1 | 13 | Centered black diagonal X eyes, worried brows, sweat formation/slide/drip and tremble |
| `bookworm-curious` | 64 × 48 | 1 | 8 | Uneven brows, question mark, head turn and blink |
| `bookworm-small` | 18 × 18 | 8 | 32 | Owner’s cross-pupil menu head in eight states |

Total: **130 tags / 1,095 frames**. [TAG_TIMINGS.md](TAG_TIMINGS.md) describes every tag and lists its exact frame holds in milliseconds. The reading idle tags each have **85 frames / 21,840 ms**. [The continuous reading demo](demo/bookworm-reading-cycle@6x.gif) joins all three covers: **255 source frames / 65,520 ms**. A single-cover tag GIF resets to its own cover; the app must advance `idle` → `idle@2` → `idle@3` to preserve the cover seam. [The mad demo](demo/bookworm-mad-demo@6x.gif) is unbundled: **34 source frames / 13,200 ms**. GIF encoders merge identical held frames without changing playback time.

## GUI work and reproducible records

The shared GUI lock was acquired before each Aseprite computer-use session and released after closing this run’s documents. `lua/gui_wormfix_face.lua` records the native **1 px Pencil** corrections in exact palette colours: wider inner lens rings on all body-head variants; solid/sliver pupils and highlight stairs; gaze, downward reading and lid families; floating happy/tired/sad/worried/curious/mad brows; mouth sizes and lower lips; eight sweat poses; torso seam repairs and tail-cap outline pixels. It was executed in the Aseprite GUI, saved, rebuilt inside the GUI and reproduced headless. These are native-tool strokes at chosen coordinates, not an external raster repaint. Onion skin was used while inspecting the page flip at 800%.

`lua/gui_owner_error.lua` records the later native Pencil corrections: clear the old error pupils, widen only the room error’s inner left box by one pixel, and place centered black diagonal Xs at both scales. It saves both parts with the 26-colour palette. `gui_owner_build.lua` runs that correction and both builders inside Aseprite. Its pending GUI save resumed after the network interruption on 2026-10-02. Both error loops were inspected at 800%, with onion skin and playback; the final source and exported-GIF playback records cover all 130 surviving tags.

`lua/fix_parts.lua` is a **one-time migration** from Run A’s saved parts. `lua/refine_wormfix_parts.lua` records the second book/tail refinement. Do not rerun the first migration on finished parts. `lua/gui_wormfix_build.lua` runs the face correction and both builders inside the GUI. `gui_wormfix_inspect.lua` opens a page-turn close-up; `gui_wormfix_review.lua` and `gui_wormfix_gifs.lua` play all source tags and exported GIFs respectively. `gui_wormfix_close.lua` closes only this art directory’s documents before releasing the lock. Earlier `gui_*.lua` files are historical Run A correction records and are not the current build pipeline.

## Evidence and handoff

[WORM_FIX_REPORT.md](WORM_FIX_REPORT.md) accounts for every A/B/C review item, the exact frame evidence, checks, limits and decisions. [WORM_FIX_FILES.txt](WORM_FIX_FILES.txt) lists this pass’s changed/new public files and local QA artifacts. `FILE_INVENTORY.txt` is the complete asset-directory inventory; it includes inherited pipeline and correction records.

`qa/` is regenerable and gitignored. The owner’s original files in `reference/` are read-only. All generated comparisons now live in `qa/`, including the owner’s error comparison `compare/error-owner@6x-8x.png`, `menubar-pixel@8x.png`, `menubar-comparison@{1,2,8}x.png`, `compare/emotions@6x.png`, `compare/menubar@8x.png`, all-frame filmstrips and every tag GIF.

The integration run must adopt room slices **`lensL=(11,17,4,6)`, `lensR=(23,18,8,7)`**, with **`eye=(27,21,2,2)`** unchanged, use the same dark-outline menu sheet on both appearances, refresh image expectations and play the reading opening beat at a sleeping→reading handoff if it needs to avoid the standing-book/open-book transition. The error-only `errorLensL=(10,17,5,6)` slice records the one-pixel inner-rim adjustment; the outside glasses contour stays unchanged. `lua/gui_owner_error.lua` records the native 1 px Pencil X corrections; `error_eyes.lua` contains their integer palette strokes and also updates the initial seed. The small `error` tremble remains a neck-only move, as Run A documented; translating the whole head would clip the fixed canvas.
