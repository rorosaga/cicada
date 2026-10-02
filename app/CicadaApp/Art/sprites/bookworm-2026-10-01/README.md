# Bookworm sprites — sources and delivery

**Preview: open [preview.html](preview.html) in a browser, straight from disk.** It plays every worm state, beat and
transition, the seven weathers, the lamp and its fly, the room by mood with the lamp lit or dark, and the menu-bar strips
on light and dark bars at their real timings. `tools/export_all.sh` regenerates it with the sheets.

Current delivery: **18 sheet pairs** in `Sources/CicadaApp/Resources/sprites/` — nine worm sheets (eight room-scale
states and the 18 × 18 menu-bar head; owner 2026-10-01: black X error eyes, one dark-outline menu sheet on both bars) and
nine room sheets. The saved Aseprite parts are the pixel authority; `tools/export_all.sh` rebuilds and verifies every
sheet. [RUN_B_REPORT.md](RUN_B_REPORT.md) and [ROOM_TAG_TIMINGS.md](ROOM_TAG_TIMINGS.md) cover the room;
[WORM_FIX_REPORT.md](WORM_FIX_REPORT.md) and [TAG_TIMINGS.md](TAG_TIMINGS.md) the worm. The run records below are kept as
history.

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

## Review evidence

`qa/` is regenerable and intentionally gitignored apart from its ignore file. It contains one actual Aseprite GIF per tag, full-frame filmstrips, key-frame boards, independent timing/pixel verification and the unchanged Swift test logs. [FILE_INVENTORY.txt](FILE_INVENTORY.txt) lists every Run A file written, including these local QA outputs and the twenty bundled PNG/JSON files. Original reference files are untouched and excluded from that inventory.

The visual comparisons inspected include:

- `qa/compare-base@6x.png` and `qa/compare-{happy,tired,sad,worried,mad}@6x.png`: matching-size base silhouette, glasses, book and all reference brows.
- `qa/keys-<state>-<page>@6x.png`, with every room tag's first pose; the small and dark-small equivalents at 8×.
- `qa/filmstrips/bookworm-reading/idle-{1..8}@6x.png`: all line, flip, close, tuck, rise and open frames; the cover versions use identical geometry and timing.
- `qa/filmstrips/bookworm-sleeping/idle-{1..3}@6x.png`, `intro-1@6x.png`, `outro-1@6x.png`: all z positions and breath/yawn/stretch poses.
- `qa/filmstrips/bookworm-happy/cheer.center-1@6x.png` and `qa/filmstrips/bookworm-awake/gulp.center-1@6x.png`: complete anticipation, landing and swallowing beats.
- `demo/menubar-comparison@{1,2,8}x.png`: normal art on `#ECECEC`, normal art on `#1E1E1E`, and the corrected dark variant on `#1E1E1E`. The 1× and 2× human look found the normal black silhouette clear on light, but its rim weak on dark; the light-rim variant restores the contour and keeps pupils black.
- `qa/menubar-{light,dark}@8x.png`: the spec's additional light (`#F6F6F6`) and dark comparisons. `reference/menubar-pixel@8x.png` sits beside the owner's menu reference for direct comparison.

`lua/gui_review.lua` opens the saved sources and plays every tag with Aseprite's native timeline command. It also supports `CicadaReviewMode = 'gif'` for actual exported GIF playback and `'step'` for native next-frame inspection at 800%. `CicadaReviewStart` resumes at a plan index and `CicadaReviewEnd` bounds a partial pass; clear the latter for a full pass. While running, the status shows the plan index. Its completion count and `CicadaReview.completed` describe only clips completed in that invocation. Playback completion is recorded only after each clip's full duration. Acquire the shared GUI lock before running it; stop it and close its documents before releasing the lock. Run headless exports separately from GUI computer use, since batch processes register the same macOS app identifier.

## Run A handoff and limits (recorded before Run B)

Run B can append palette groups without changing the 27 worm/fx/book keys; 60 single-character keys remain under the spec's 87-key limit. The shared helper API and its tests are ready. Extend `verify.py` with the room/ruling-9/fly/weather checks, add the three room builders, and supply `manifest.py` and `make_preview.py` for `STAGE=all`. `--worm-only` must stay independently usable. The extra dark sheet needs a manifest entry too.

Run C should preserve all tag, slice and canvas contracts and choose the small appearance variant. There are no Swift source changes in this run. App playback, scene placement, and actual menu-bar rendering belong to Run C's integration checks; asset review alone does not verify those behaviors.

The brow and pupil stamps deliberately simplify the softly rendered reference into whole-pixel shapes, and the temple/tail are shortened in the menu head before changing the lenses or cross pupils. The tiny first z uses asymmetric short ends within the spec's 3 × 3 box; its silhouette is necessarily spare at 1×. The larger diagonal z's carry the clearer letter shape. No unfinished art placeholder remains in the Run A sheets. Final aesthetic approval remains with the owner.

## Final verification

The final pipeline completed twice after the last z correction and the combined reading demo were added. Both invocations ended with `verify.py --worm-only` passing. `qa/final-cycle-export-{1,2}.log` records the runs, and `qa/final-rebuild-{1,2}-sha256.json` matches for all **22** checked outputs: twenty bundled PNG/JSON files and two demo GIFs. `qa/verification.json` records the final sheet hashes and measured blink gaps. The verifier also re-exports every saved animation source, compares the resulting PNG/JSON bytes, and checks all **138** tag GIFs against their sheet frames and durations. The 255-frame reading demo is independently compared with the three idle tags.

`lua/test_helpers.lua` passes every public helper and the additions, including the unknown-colour failure case (`qa/final-helpers.log`). The Swift baseline passed **2,720 tests / 0 failures**, 81.545 seconds (`qa/baseline-swift.log`); the final unchanged-code run passed **2,720 tests / 0 failures**, 79.553 seconds (`qa/final-swift.log`). No Swift source was changed.

### Run A acceptance

- [x] All nine fixed sheets have exactly the required tags and 64 × 48 / 18 × 18 frames, binary alpha and palette-locked pixels; the optional dark small sheet passes the same checks. Evidence: `qa/verification.json` and both final export logs.
- [x] Duration caps pass, with identical frame durations across gaze families and reading covers. Evidence: `TAG_TIMINGS.md` and the independent verifier.
- [x] State marks pass; sleeping idle/mumble keep closed eyes; error retains red pupils and sweat; all room frames have at least 20 book pixels; base row is 47 except the permitted lifts, bounded to three pixels. Evidence: both final export logs.
- [x] Reading centroids track lines with returns; three page flips and blinks use uneven spacing; the book closes, tucks behind the body, and the next cover rises and opens fully within the canvas. Cover seams match exactly. Evidence: `qa/filmstrips/bookworm-reading/idle-{1..8}@6x.png`, matching cover filmstrips, the native source review and verifier.
- [x] Awake, happy, curious and reading blinks have unequal gaps. Evidence: measured `blinkGapsMs` in `qa/verification.json`.
- [x] Sleep breath lasts four seconds, with the complete z → zz → zzz size/path sequence and palette-step fades. Evidence: `qa/filmstrips/bookworm-sleeping/idle-{1..3}@6x.png`, final 800% onion-skin review and verifier.
- [x] Yawn and stretch were inspected in the 1× preview and high-zoom source; cheer has crouch, peak and landing squash; gulp has entering paper and a descending neck bulge. Evidence: sleeping intro/outro, happy cheer and awake gulp filmstrips listed above, plus native playback/frame stepping.
- [x] The menu head preserves the owner's large lime lenses, cross pupils, crown, right temple and curled neck. Light/dark inspection at 1× and 2× selected the separate light-rim variant on dark. Rows 16–17 and the curious badge corner pass. Evidence: `demo/menubar-comparison@{1,2,8}x.png`, `qa/menubar-{light,dark}@{1,2,8}x.png`, `reference/menubar-pixel@8x.png` and verifier.
- [x] Two complete final exports produce identical bytes. Evidence: the two final hash manifests, 22 entries each.
- [x] Deliverable writes are inside this worktree. The only task-directed external write was the owner's explicitly required shared GUI-lock directory; Aseprite also maintains its own application state. No scripts were installed into its user scripts folder, no bank was touched, and no git mutation was performed.

### Run A self-check

- [x] Every room tag was inspected at 6×/800% and every small tag at 8×/800%, with full-frame filmstrips, key boards and exported GIFs. Evidence: `qa/keys-*`, `qa/filmstrips/*` and the native review.
- [x] All 138 final tag GIFs completed native playback; the mad demo completed its loop; the continuous three-cover reading demo ran for more than two full 65.520-second cycles. Evidence: `qa/native-review.md`, the inspected `COMPLETE: 138 clips` dialog and sequential native playback screenshots.
- [x] Base sit compared with the original at matching size: silhouette, glasses and left book. Evidence: `qa/compare-base@6x.png`.
- [x] All five emotion references compared at matching size. Evidence: `qa/compare-{happy,tired,sad,worried,mad}@6x.png` and the mad demo.
- [x] Small art inspected on `#F6F6F6` and `#1E1E1E` at 1× and 2×, plus the owner's requested `#ECECEC`. Evidence: menu boards and comparison strips above.
- [x] Final `swift test` remains green. Evidence: `qa/final-swift.log`, 2,720 tests and zero failures.

## Run B — the room, weather, fly and spine textures

The room occupies a 160 × 64 lattice with bottom-left coordinates in [room-plan.json](room-plan.json). Columns 0–109 contain the art; columns 110–159 are reserved for the real pile. The window pane is 36 × 32 at (20, 27), the worm is at (36, 9), and the bean bag's seat maps to row 9. All props remain inert. The lamp and fly show the schedule's lit state; weather still follows the page mood, never a clock or count.

| Sheet | Canvas | Tags | Frames | Contents |
|---|---|---:|---:|---|
| `room-backdrop` | 110 × 64 | 2 | 2 | Textured wall and planks, baseboard bevel, rug, cord, right trim; dark and warm-lit variants |
| `room-window` | 40 × 38 | 1 | 1 | Wood frame, crossbars and sill |
| `room-weather` | 36 × 32 | 7 | 260 | Night, dawn, sunny, partly cloudy, windy, rainy, curtains drawn |
| `room-lamp` | 18 × 50 | 2 | 2 | Unlit shade and warm-lit rim, pole and foot |
| `room-fly` | 20 × 26 | 1 | 40 | Tiny erratic route, two landings, wing glints and shade occlusion |
| `room-beanbag` | 62 × 12 | 1 | 1 | Folded lobes and a dented seat |
| `room-plant` | 12 × 22 | 1 | 1 | Connected leaf clusters and terracotta pot |
| `room-mug` | 8 × 9 | 1 | 1 | Coffee, handle and upper-left highlight |
| `room-spines` | 24 × 12 | 5 | 15 | `chat`, `page`, `note`, `video`, `other`; body/light/shade masks, not animation |

The room adds 55 colours to the original 27, for **82 unique palette entries**. Each painted pixel is a palette RGB with alpha 255; all other pixels have alpha 0. Props use coloured outlines. Light comes from the upper left, with a separate warm lamp contribution. No smoothing, gradient, alpha fade, flash, mug steam, plant sway or decorative book pile was added.

### Saved parts and rebuild

`parts/room-parts.aseprite` holds the reusable room parts on a 110 × 64 master canvas. Each named tag is registered at its own local top-left origin. `seed_room_parts.lua` creates this file only when missing. **Keep the saved file:** it contains the native GUI corrections. The builders read its named parts, crop to the fixed prop canvases, assemble layers and slices, and save the nine `src/room-*.aseprite` sources. Exports come from those sources.

From this directory:

```sh
tools/export_all.sh
python3 tools/make_room_review.py
node tools/check_preview.mjs
```

The default pipeline rebuilds the three room builders, exports all 19 saved sources, writes the manifest, verifies all sheets and GIFs, and generates the offline HTML. **During the orchestrator's Run A freeze it deliberately skips the two worm builders.** Their sources, parts, scripts and exported bytes are unchanged. `STAGE=worm` retains Run A's explicit rebuild workflow, for its separate fix pass. No worm helper was edited. `run_checked.lua` requires a completion marker from every builder and the part checker before the shell can export; a missing marker stops the pipeline even if the authoring process returns zero.

`room-motion.json` contains the seven weather tags and integer positions/steps in play order, including the last-to-first step. Positive wraps describe periodic motion; zero means no wrap. A `.phase` element records a pose phase rather than a physical point; tree lean and curtain hem tracks record their integer offsets. Clouds and rain record physical coordinates. Leaf height resets occur behind the jamb, with both endpoint frames hidden.

### Native Aseprite authoring and review

Computer use opened the saved room parts and sources, used Aseprite's native 1-pixel Pencil/Eraser through `gui_room_tune.lua`, enabled onion skin, and inspected at displayed 800% zoom. The saved corrections include leaf clusters; lamp highlights and warm rim; bean-bag folds; staircase corners of the glow; sill and mug highlights; and the round cloud's top and outer corners. The final extreme tree lean was tightened by four native outline strokes in `gui_room_final.lua`, keeping its canopy inside glass columns 1–12. Both scripts record corrections; neither runs during rebuilding.

`gui_room_build.lua` ran all three builders **inside Aseprite's Developer Console**, then the same builders ran headless. This keeps scripts inside the worktree rather than installing them in Aseprite's user scripts directory. GUI authoring and review held the shared lock; documents were closed before releasing it. The source and exported-GIF review plans each visibly completed 21 clips. Each weather played three full loops in each plan; fly stepping used 800% and onion skin. The final 40-step fly was replayed frame by frame in Aseprite. The timing/path refinements, separated moon/star pixel and final tree outline were also checked in the regenerated filmstrips.

The rain and fly each received multiple refinement passes: rain gained irregularly placed streaks, glass drops that leave through the bottom, and hidden leaf resets; the fly gained two uneven loops, short changes of pace, two explicit landing holds and a continuous hidden return. The fly's final loop is 4,590 ms, with 1,200 ms on the top and 600 ms on the right rim. Every step moves at most one pixel on each axis; zero-ink frames are intentional occlusion behind the shade. It is present only with the lit lamp, and its first frame rests on the top for Reduce Motion.

### Verification and remaining review

Two final default exports produced identical bytes for **52 files**: all 38 sheet files, the manifest, HTML, plan and motion JSON, nine room sources and the room parts file. The independent verifier also compares re-exports with the bundled files and checks every tag GIF against the sheet pixels and delays. The final bundle is **588,486 bytes**, with **1,958,256 decoded pixels** and a longest sheet side of **1,024 px**. Ruling 9 passes for every weather frame against all reachable worm art; the lowest visible-cloud ratio is 53.97%. The storm's largest luminance deviation is 0.2102%, below 2%.

All 28 mood × lamp × 3×/4× composites were inspected in `qa/composites/`. All room-frame filmstrips, the seven weather GIFs, 40 fly frames at 8× and all 15 spine masks at 6× were reviewed. The final Swift run passed **2,720 tests / 0 failures**, 78.620 seconds. Earlier full and focused runs hit the existing three-second polling assertion; those logs are retained and the final full rerun passed without changing Swift.

The browser tool rejected `file://` under its URL policy. **Actual offline browser playback is unverified.** The preview includes all 19 sheets and 159 tags, uses relative images and inline JSON without network dependencies, and its JavaScript/control wiring passes `check_preview.mjs`; that check uses a mock Canvas and does not verify browser rendering. Open `preview.html` manually for this remaining acceptance item. [RUN_B_FILES.txt](RUN_B_FILES.txt) lists every authored, exported and local QA file written by Run B. App integration and the owner's CPU/visual approval remain Run C/orchestrator gates.

The integration run must adopt room slices **`lensL=(11,17,4,6)`, `lensR=(23,18,8,7)`**, with **`eye=(27,21,2,2)`** unchanged, use the same dark-outline menu sheet on both appearances, refresh image expectations and play the reading opening beat at a sleeping→reading handoff if it needs to avoid the standing-book/open-book transition. The error-only `errorLensL=(10,17,5,6)` slice records the one-pixel inner-rim adjustment; the outside glasses contour stays unchanged. `lua/gui_owner_error.lua` records the native 1 px Pencil X corrections; `error_eyes.lua` contains their integer palette strokes and also updates the initial seed. The small `error` tremble remains a neck-only move, as Run A documented; translating the whole head would clip the fixed canvas.
