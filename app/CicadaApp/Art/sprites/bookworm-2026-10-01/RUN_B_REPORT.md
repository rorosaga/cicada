# Run B — room asset delivery, 2026-10-01

Run B supplies the nine room sheet pairs, saved Aseprite sources/parts, seven weather loops, lit/dark lamp and tiny fly, five spine textures, manifest, full verifier and offline preview. The complete bundle contains **19 sheet pairs / 159 tags / 1,450 frames**. Run B contributes **21 tags / 323 frames**. No Swift file was changed, and no commit, push, stash, branch or reset was performed.

The art and pipeline checks pass. Actual `file://` browser playback remains unverified: the computer-use browser's security policy rejected that protocol. This report leaves that acceptance item open rather than claiming the JavaScript smoke check is a browser test.

## Files and tag behavior

[RUN_B_FILES.txt](RUN_B_FILES.txt) is the exhaustive worktree-relative inventory of every authored, exported and local QA file written by this run. Build products and Python bytecode caches are excluded from that deliverable inventory. References were read and left unchanged. Run A's parts, scripts, sources and sheet bytes were left unchanged: `qa/run-b-worm-freeze.json` compares 49 frozen files against HEAD and records no differences; the original 27 palette entries are also identical.

The authored files are:

- `palette.json`, `room-plan.json`, `room-motion.json`, `README.md`, this report, `ROOM_TAG_TIMINGS.md` and `RUN_B_FILES.txt`.
- `parts/room-parts.aseprite`; nine `src/room-{backdrop,window,weather,lamp,fly,beanbag,plant,mug,spines}.aseprite` files.
- `lua/room_common.lua`, `seed_room_parts.lua`, `build_room.lua`, `build_weather.lua`, `build_spines.lua`, `check_room_parts.lua`, `run_checked.lua`, `gui_room_tune.lua`, `gui_room_final.lua`, `gui_room_build.lua`, `gui_room_review.lua`.
- `tools/export_all.sh`, `verify.py`, `verify_room.py`, `manifest.py`, `make_preview.py`, `preview_template.html`, `check_preview.mjs`, `make_room_review.py`, `make_run_b_inventory.py` and generated `preview.html`.
- `Sources/CicadaApp/Resources/sprites/room-{backdrop,window,weather,lamp,fly,beanbag,plant,mug,spines}.{png,json}` and `sprites.manifest.json` (relative to `app/CicadaApp/`).
- Regenerable `qa/` images, GIFs, registries, hash records and logs, listed individually in the inventory.

[ROOM_TAG_TIMINGS.md](ROOM_TAG_TIMINGS.md) lists **every room tag**, its canvas, action, frame count, each frame's milliseconds and total. The unchanged worm tags remain in [TAG_TIMINGS.md](TAG_TIMINGS.md).

| Tag family | Frames × ms | Total | Behavior |
|---|---|---:|---|
| Backdrop `dark`, `lit`; lamp `dark`, `lit`; window, bag, plant and mug `idle` | Each 1 × 1,000 | Each 1,000 ms | Static props; only the saved glow/shade difference changes with the lamp |
| Weather `night` | 24 × 200 | 4,800 ms | Static crescent, navy bands, nine independently phased twinkling stars |
| Weather `dawn` | 36 × 300 | 10,800 ms | Rose/peach/gold sunrise, half sun, thin drifting clouds and alternating rays |
| Weather `clear` | 36 × 500 | 18,000 ms | Full sun, slow round clouds, ray poses and far treeline |
| Weather `fair` | 72 × 200 | 14,400 ms | Near cloud at one pixel/step, far clouds at half that speed, partially covered sun |
| Weather `overcast` | 36 × 120 | 4,320 ms | Grey cloud streaks, three tree sways, three blowing leaves |
| Weather `storm` | 48 × 80 | 3,840 ms | 32 diagonal streaks, four forming/sliding glass drops, no flash |
| Weather `curtains` | 8 × alternating 600, 300 | 3,600 ms | Closed folds, a narrow static leak, gently breathing hems |
| Fly `buzz` | 40 irregular holds, 60–1,200 ms | 4,590 ms | Two uneven loops/darts, top landing, right-rim landing and hidden return |
| Spines `chat`, `page`, `note`, `video`, `other` | Each 3 × 1,000 | Each 3,000 ms | Body/light/shade masks, selected by role; never played as animation |

The fly is one body pixel, with a second wing/glint pixel on selected steps. It holds for 1,200 ms on the top and 600 ms on the right rim. Frames 33–39 are completely hidden behind the opaque shade. Its last and first frames share the landed pixel. The full route, including the seam, moves at most one pixel per axis per step and stays outside the glass and pile.

## GUI work and visual iteration

Computer use was confirmed in Aseprite before authoring. The room's saved parts were opened and corrected with native 1-pixel Pencil/Eraser tools through `gui_room_tune.lua`, in a native transaction. The palette was read from `palette.json`; no external raster editor or generated image was used. The saved parts contain:

- Connected green leaf clusters and upper-left leaf tips, replacing isolated foliage pixels.
- Upper-left shade highlights, a warm three-pixel rim and a right rim accent.
- Bean-bag lobe highlights and quieter fold pixels.
- Erased corners that turn the three square glow bands into short pixel staircases.
- Sill and mug highlights, and cleaned top/outer pixels on the round cloud.
- A final four-row canopy outline correction in the extreme tree lean, keeping every tree pose inside glass columns 1–12 without moving the trunk (`gui_room_final.lua`).

The exact native strokes are recorded in `gui_room_tune.lua` and `gui_room_final.lua`. Saved `.aseprite` parts are authoritative; this script records the corrections and does not run during regeneration. The seed creates only a first version when the parts file is absent. `check_room_parts.lua` confirms all **33 named parts** are palette-locked and their unused master-canvas area is transparent (`qa/run-b-room-parts-check.log`).

All three builders also ran inside Aseprite's Developer Console via `gui_room_build.lua`, followed by matching headless builds. No script was installed into Aseprite's user scripts folder. Focused GUI sessions acquired the shared lock, closed their documents, and released the lock without quitting Aseprite.

The native source review opened every room source, used displayed 800% zoom and timeline playback, and visibly completed **21 clips**. Each weather played three complete loops. The exported-GIF review separately completed **21 clips**, again with three loops per weather. The fly's final 40-step source was inspected at 800% with onion skin and native next-frame stepping; that final invocation visibly completed its one clip. `gui_room_review.lua` records the review plan and real playback intervals; its completion count applies only to that invocation.

The centrepieces received multiple passes. Rain changed from a regular grid to irregular staggered streaks, with longer glass tracks that leave through the bottom. Wind leaves reset height behind the jamb rather than jumping visibly. The fly's route crosses itself, takes two unequal excursions and changes its pace; the later pass adjusted two path points and two frame holds. A star was separated from the moon's edge. Those final small changes were inspected in the regenerated filmstrips; they did not change tags, canvases or slices.

The inspected evidence includes:

- `qa/run-b-references.png`: all supplied references, including the base, five emotions, glasses and menu-bar design.
- `qa/room-{backdrop,window,weather,lamp,fly,beanbag,plant,mug,spines}-contact@6x.png`: every room key frame.
- `qa/room-weather/{night,dawn,clear,fair,overcast,storm,curtains}@6x.gif` and every matching `*-frames-*@6x.png`: all 260 weather steps and seams. The source/GIF timeline reviews supply the three-loop checks.
- `qa/room-weather-keys@1x.png`: seven native-size key frames. Night, sunrise, sunny, partly cloudy, windy, rain and curtains each retain their cue without animation.
- `qa/room-lamp-glow@1x.png`: native-size dark/lit reading rooms. The lit rim and warm pool remain visible at 1×.
- `qa/room-fly/buzz-lamp-frames-{1..4}@8x.png`: all 40 final fly steps in their actual lamp registration, including occlusion and both landings.
- `qa/run-b-tree-final@8x.png`: four final wind sway poses after the native canopy correction.
- `qa/room-spines-masks@6x.png`: all 15 masks on a contrasting ground; all five kind marks are distinct.
- `qa/composites/{awake,reading,sleeping,digesting,happy,hungry,error}-{dark,lit}@{3,4}x.png`: all **28 images**, inspected individually within the seven `*-review.png` boards. The seat meets the worm without a gap; the plant is below the sill; lamp light and frame registration are consistent.

## Measured verification

| Check | Measured result | Evidence |
|---|---|---|
| Aseprite / authoring CLI | 1.3.18.6-dev / 0.159.3 | Manifest; initial toolchain check |
| Sheet coverage | 19 pairs, including `bookworm-small-dark` | Manifest and full verifier |
| Palette | 82 unique entries; original 27 retained; binary alpha; no reserved state RGB | `qa/verification.json`, freeze record |
| Bundle byte count | 588,486 bytes, below 6 MiB | `qa/verification.json` |
| Decoded pixel count | 1,958,256, below 8,388,608 | `qa/verification.json` |
| Largest sheet side | 1,024 px, below 2,048 | PNG inspection and verifier |
| Ruling 9 | Every celestial pixel visible; minimum cloud visibility dawn 89.19%, sunny 53.97%, fair 57.14%, windy 63.16% | `qa/verification.json` |
| Storm brightness | Mean 92.6585; maximum relative deviation **0.2102%**, below 2% | `qa/verification.json`; 48-frame storm filmstrip |
| Fly | 0–2 opaque pixels/step; key frame 1; glass/pile clear; path and shade occlusion checks pass | Full verifier and 8× fly boards |
| Weather motion | Integer positions and steps for all seven tags; every last-to-first step verified; cloud/rain cadence verified independently | `room-motion.json`, full verifier |
| Repeat exports | **52 / 52 files identical** | `qa/run-b-pass{7,8,9}-hashes.json`; `qa/run-b-reproducibility.json` |
| Swift baseline | 2,720 tests / 0 failures, 78.191 seconds | `qa/run-b-baseline-swift.log` |
| Final Swift suite | **2,720 tests / 0 failures, 78.620 seconds** | `qa/run-b-final-swift-retry.log` |
| Offline preview script | 19 sheets, 159 tags, all 28 room combinations; Reduce Motion, Low Power, pause, step and pose control smoke checks pass | `qa/run-b-preview-smoke.log` |

The first final Swift run and a focused retry reported two assertions in `SleepViewModelTests.test_pollLoop_doesNotFireEarly_whenStoreStatusStaysIdleThroughout`. The unchanged test waits three seconds for an async completion; the implementation awaits `load()` before invoking the callback, and that load has default API dependencies. The next full run passed. This is recorded as a timing-sensitive failure, with its cause not proven; it was not hidden or fixed by changing unrelated Swift code. Logs: `qa/run-b-final-swift.log`, `qa/run-b-swift-retry-targeted.log`, and the passing full rerun above.

The pipeline also checks an explicit Lua completion marker before exporting. An intentional builder assertion stopped with exit 255 (`qa/run-b-pipeline-failure-check.log`); a simulated process that returned zero without completing stopped with exit 1 (`qa/run-b-pipeline-zero-exit-check.log`). `qa/run-b-pass9-export.log` records the full successful export using this wrapper.

The preview smoke check runs the shipped inline script with local image-path checks and a mock DOM/Canvas, without a browser or network. It catches runtime/control-wiring errors and confirms cumulative frame selection, key frames and doubled timings. It **does not** prove browser Canvas rendering or native app playback. The HTML has inline JSON, relative PNG paths, system fonts and no external script/font/style dependency.

## Run B acceptance

- [x] All **19** sheets and manifest exist; the full verifier passes contracts, ruling 9 per frame, fly, luminance, seams, hashes and GIF comparisons. Evidence: `qa/verification.json` and final verify/export logs.
- [x] Seven weathers read from their key frame at 1×. Evidence: `qa/room-weather-keys@1x.png`, native source review and 6× contacts.
- [x] Rain has no flash; weather loops have no visible seam jump. Evidence: storm luminance result, every weather filmstrip, and three native loops per weather in source and GIF review plans.
- [x] Warm lamp light reads at 1×; fly has two landings, darts and loops, 0–2 pixels, and stays outside glass/pile. Evidence: `qa/room-lamp-glow@1x.png`, 8× fly boards and independent checks.
- [x] Backdrop ends at column 109; every room layer ends before 110. Evidence: plan and verifier bounds checks.
- [x] Worm baseline meets the bean bag's seat, with the plant under the sill. Evidence: seat row check and all 28 composites.
- [ ] **Offline browser playback remains unverified.** The browser URL policy rejected `file://`; no server or alternate browser workaround was used. The generated file and script smoke checks are ready for manual review.
- [x] Manifest hashes match; no shipped JSON names a machine path; total bytes are below 6 MiB. Evidence: final full verifier.
- [x] Two complete default exports have identical bytes. Evidence: final pass hashes and reproducibility record.

## Run B self-check

- [x] Every room export inspected at 6×; each weather's exported GIF played natively. Evidence: contacts, full filmstrips, native 21-clip GIF review.
- [x] All 28 room composites inspected at 3×/4×. Evidence: `qa/composites/` files listed above.
- [x] Fly inspected frame by frame at 800% with onion skin; every final step inspected at 8× against the lamp. Evidence: native step review and four `buzz-lamp-frames-*@8x.png` boards.
- [x] Palette recounted; every exported RGB belongs to the 82-entry palette and alpha is binary, with no reserved hex. Evidence: independent pixel checks.
- [x] Unchanged Swift suite passed again, with the intervening polling-test failures disclosed. Evidence: final passing full-suite log.

## Run C consumption and remaining gates

Run C should consume the files using the existing spec contracts. No room tag or canvas was renamed. Required adjustments and checks:

1. Expect **19 pairs / 38 sheet files + manifest** throughout bundle coverage and tests, including both 18 × 18 appearance variants. The dark variant uses a light physical rim, with `isTemplate = false`; select by menu-bar appearance.
2. Read the fixed tags exactly: `dark`/`lit` for backdrop and lamp, seven weather raw values, `buzz` for fly, `idle` for static props, and five spine kinds. Use per-frame durations from JSON for playback. Single-frame prop tags are held; weather, fly and worm tags are the animated layers.
3. Match the bottom-left room plan: pane (20,27), window (18,23), plant (21,0), lamp (0,0), fly (0,32), bean bag (36,0), mug (100,0), worm (36,9), pile (110,0). The plan's `pane` raw prop is intentional.
4. Use the provided slices. Window `glass` = (2,2,36,32); bag `seat` = (4,2,54,1), which maps to scene row 9; lamp `ink` = (2,0,14,50), `shade` = (2,1,14,11); backdrop `glow` = (0,10,26,54); fly `ink` = (7,0,12,17). Coordinates in slices are top-left, unlike the plan.
5. Draw the fly only while the lamp is lit. Under Reduce Motion show `buzz` frame 0, which is visibly landed beside the shade. Zero-ink return frames are intentional; do not substitute a fallback image for them. Low Power doubles frame durations.
6. Use the three spine frames as **body, light, shade masks**, tinted by the real spine colour; keep the right four columns as the kind mark and stretch only the permitted plain region. Respect the spec's small-spine fallback. The preview pile uses placeholder values only.
7. Read `room-motion.json` using the supplied `tags → elements → positions/steps/wrap` schema. `.phase` tracks encode cyclic pose states; their values are integers, not screen coordinates. Keep modular seam assertions for every element.
8. After merging the separate worm fix pass, rerun the full export/verifier and refresh the manifest and preview: ruling 9 uses the actual worm pixels, and the hashes must cover the final merged sheets.
9. Open `preview.html` manually by file path and play all mood/lamp states at 3× and 4×. The browser tool could not complete that review. Then run app-rendered composite tests, packaging checks, actual menu-bar light/dark checks, and the owner's demo-bank CPU measurement. Asset verification does not claim any of these app checks passed.

No decorative bookshelf or extra counted books were added: the existing three reading covers and the five textures satisfy the book scope while preserving P10. No unfinished art placeholder remains in the room sheets. The tiny fly and tree are deliberately economical on the fixed grid; aesthetic approval remains with the owner.

## Differences from the written spec

- **19 sheets rather than 18:** the owner's later dark menu-bar variant takes precedence; manifest, verifier and preview include it.
- **The default full export freezes the worm builders:** the user's explicit instruction to preserve Run A takes precedence over “every build.” It rebuilds all room sources and re-exports/verifies all 19 saved sources. Run A's explicit `STAGE=worm` workflow remains available to its separate fix run.
- **GUI builders ran through the Developer Console:** the owner required GUI execution, while §10.6 forbids scripts installed outside the worktree. Console `dofile` executes inside Aseprite and preserves that boundary. Native Pencil/Eraser corrections and source playback used computer use.
- **Browser review could not run:** automatic security review rejected opening the local preview because only `http:` and `https:` URLs are allowed. No policy workaround or server was used. This is a limitation, not a claimed spec disagreement.

No other spec ruling was intentionally reopened. Run A's worm remains frozen for its separate visual fix pass; this run makes no new claim about its art beyond the independent contracts that passed.
