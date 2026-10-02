# G176 final integration — 2026-10-02

Integrated on `feat/study-room-sprites`; no commit, push, install, app launch, bank read or computer use in this pass.
Owner acceptance and merge to dev remain pending. The binding scenery contract and TODO ruling 18 apply.

## Fixes and causes

- The Swift acceptance palette decoded only `colors`, rejecting valid derived pixels. It now follows exactly
  `tools/night_palette.py:allowed_colors`: authoring colours, night ramps/question glyph, scenery ramps/overlay
  colours and clock colours. **81 authoring keys / 87 budget; 699 distinct allowed RGBs.** Every packed pixel still
  undergoes binary-alpha, palette and reserved-hue checks; provenance still forbids machine paths. A sheet emits
  only its first defect, with sheet/frame/local cell/hex/alpha, including a padding location when applicable.
  Dusk/night sky tints retain authoring roles so shape visibility checks inspect their actual pixels too.
- The clock's app box was copied as (93,37); the verified art plan is **(94,34)**. The app table now matches that
  plan, with the equality test and all-frame clearance tests unchanged.
- Independent leaves, rather than a merged room clock, cost **1,908 boundaries/minute** for rainy-night +
  digesting + lamp lit: rain **749**, fly **520**, worm **340**, shooting star **239**, clock **60**.
  Rain's holds change **80 → 100 ms** in all three times. Its 48 frames/pixels and every wrap/motion step remain
  unchanged. New rain cost **599**; measured maximum across **240** environment/mood/lamp combinations:
  **1,758/minute**. Ruling 18's **1,800 cap stays unchanged**. The verifier pins 100 ms exactly and normalizes only
  the strictly checked amended day holds back to 80 ms before comparing the untouched historical pixel hash.
- Settings already stopped the reader/clock but did not propagate its pause to the sprite leaves.
  `StudyRoom` now supplies `scenePaused = !onScreen` to the shared art layer, covering worm, sky/fx and fly.
  Reduce Motion key frames/no second hand, Low Power ×2 and hidden/Settings pauses are tested.
- ImageRenderer showed native-view warning placeholders in the first pane render. The test hook now freezes
  sprites, omits native visibility probes and renders the source menu's current text twin. The production native
  menu remains unchanged; these snapshots verify pane layout/art, not menu interaction or live app playback.

## Measured layout

Bottom-left room coordinates; rectangles are (x,y,width,height). All hotspot pins were checked against actual PNG
union ink/slices and kept whole-cell/disjoint/outside the real pile.

| Element | Cells | Points at 1.0 (3 pt/cell) |
|---|---|---|
| Worm hotspot | (40,9,56,48) | **(120,27,168,144)** |
| Lamp hotspot | (2,0,14,50) | **(6,0,42,150)** |
| Window hotspot, clipped at worm | (20,27,20,32) | **(60,81,60,96)** |
| Wall clock canvas, inert/no hotspot | (94,34,15,15) | **(282,102,45,45)** |

Eye cell = **(64,34)**; eye centre = **(193.5,103.5) pt**. Gaze edges = **120 / 288 pt**, centre **204 pt**,
hysteresis **3 pt**: leave left at 123, retain right at 285 and leave below it. At 1.4, cell = 4 pt; all geometry
uses that same lattice. The hotspot keys remain worm/lamp/window; the clock is a text-twin leaf only.

## Renders actually inspected

The app test writer produced **552 room PNGs**: **480** (five bases × three times × eight moods × two lamps ×
two zooms), **48** overlay samples (all six time-specific tags over sunny/rainy, two lamps/two zooms), and
**24** clocks (12:00, 3:15, 10:09:55 × day/night × two lamps × two zooms). Overlays use a maximum-ink active
frame so the shooting star's intentionally empty key frame does not hide it in a static review.
All 552 were inspected in the 24 labelled boards below. The six Settings panes were inspected individually.
Every original PNG path is listed under its containing board in [qa/integration/render-index.json](qa/integration/render-index.json);
the copied PNGs retain their original bytes. Boards use nearest-neighbour display thumbnails; original room renders
are 480 × 192 at 1.0 and 640 × 256 at 1.4. No live app/browser motion acceptance is implied.

| Path, relative to this art directory | Observation |
|---|---|
| `qa/integration/boards/room-sunny-day.png` | Bright room; sun, open book, z and X eyes remain distinct; lamp adds its rim without moving the seat. |
| `qa/integration/boards/room-sunny-dusk.png` | Warm rose sky with day-lit interior; both lamp states retain the same room geometry. |
| `qa/integration/boards/room-sunny-night.png` | Cool dark room; moon/star pane remains visible; lamp warms the left wall and near seat while the tail stays cool. |
| `qa/integration/boards/room-cloudy-day.png` | Clouds and sun remain visible above every mood; book and lamp stay separate from the window. |
| `qa/integration/boards/room-cloudy-dusk.png` | Muted rose cloud sky, day-lit room; no clipping at either zoom. |
| `qa/integration/boards/room-cloudy-night.png` | Dense dark cloud deck retains stars and readable worm marks; lit lamp gives a local warm pool. |
| `qa/integration/boards/room-windy-day.png` | Streak clouds/tree identify wind without a flash; the open book and closed sleeping eyes remain legible. |
| `qa/integration/boards/room-windy-dusk.png` | Dusk wind keeps the same tree/window registration and day-lit interior. |
| `qa/integration/boards/room-windy-night.png` | Dark tree and celestial shapes survive; near light and far shadow remain separate. |
| `qa/integration/boards/room-rainy-day.png` | Rain makes the room dark even by day; rain/glass tracks, sleeping z and X/drop remain readable. |
| `qa/integration/boards/room-rainy-dusk.png` | Rose rain sky with cool dark room; the scheduled lamp warms only the near side. |
| `qa/integration/boards/room-rainy-night.png` | Dark blue rain retains its streaks; the worm's closed eyes/book and subdued clock stay visible. |
| `qa/integration/boards/room-curtains-day.png` | Closed folds remain recognizable; mist/celebration layers are still drawn over this chosen base. |
| `qa/integration/boards/room-curtains-dusk.png` | Warm folds and day-lit interior; consistent worm/seat baseline at both zooms. |
| `qa/integration/boards/room-curtains-night.png` | Nearly dark folds, cool room and local lamp pool; no silhouette or clock collision. |
| `qa/integration/boards/overlay-mist-day.png` | Sparse pale wisps leave the sun/rain visible and do not hide sleeping eyes or z. |
| `qa/integration/boards/overlay-mist-dusk.png` | Warm mist stays sparse above dusk sun/rain; the room lighting follows the base. |
| `qa/integration/boards/overlay-mist-night.png` | Thin cool wisps remain visible on both clear and rainy skies without whitening the pane. |
| `qa/integration/boards/overlay-rainbow-day.png` | Five-band arc reads behind mullions; rain remains visible below it. |
| `qa/integration/boards/overlay-rainbow-dusk.png` | Muted dusk arc remains recognizable over sunny/rainy bases; no full-pane cover. |
| `qa/integration/boards/overlay-shootingstar-night.png` | Tiny three-pixel trail is visible in its active-frame sample; it is deliberately subtle beside the moon/stars and needs motion for its shooting cue. |
| `qa/integration/boards/clock-12-00-00.png` | All hands point to twelve; dial is isolated on the wall and darker in the night room. |
| `qa/integration/boards/clock-03-15-00.png` | Quarter-past-three hands point right, with distinct lengths; dial clears the worm in both lighting variants. |
| `qa/integration/boards/clock-10-09-55.png` | Hour/minute split toward ten/two and red seconds toward eleven; thin hand remains legible on the dark dial. |
| `qa/integration/settings/localWeather-light.png` | Privacy disclosure fits; missing forecast explicitly names How Sleep is doing fallback; room preview stays readable. light appearance. |
| `qa/integration/settings/localWeather-dark.png` | Privacy disclosure fits; missing forecast explicitly names How Sleep is doing fallback; room preview stays readable. dark appearance. |
| `qa/integration/settings/sleep-light.png` | State source and current cloudy/read-waiting text agree with the preview; Choose-only rows are absent. light appearance. |
| `qa/integration/settings/sleep-dark.png` | State source and current cloudy/read-waiting text agree with the preview; Choose-only rows are absent. dark appearance. |
| `qa/integration/settings/choose-light.png` | Night and Rainy selected with a neutral ring/ground; all eight thumbnail labels and dark lit preview fit. light appearance. |
| `qa/integration/settings/choose-dark.png` | Night and Rainy selected with a neutral ring/ground; all eight thumbnail labels and dark lit preview fit. dark appearance. |

Additional original-size files inspected individually:

- `qa/integration/composites/sunny-day-reading-lit-1.0.png`: open cream book, clean bean-bag contact, isolated clock.
- `qa/integration/composites/rainy-night-sleeping-dark-1.4.png`: cool light from the window; z and closed eyes remain
  readable with the lamp off; no overlap with the dark clock.
- `qa/integration/composites/clock-10-09-55-night-lit-1.4.png`: black hand lengths and thin red seconds are distinct.
- `qa/integration/composites/overlay-sunny-shootingstar-night-lit-1.4.png`: tiny active trail stays in the upper pane;
  the near lamp pool and far cool wall stay separate.

The first rejected Settings image was `$TMPDIR/cicada-sprite-composites/settings/choose-light.png`; it contained
ImageRenderer's native-view warning patches. The hook correction regenerated the same path and all six copied panes;
those warning patches are absent in the final inspected renders. No saved art pixels needed a visual correction.

## Verification record

Two full `swift test` runs after the Mascot addition and final exports pass **2,775 tests each, zero failures**:
**128.977 s** and **128.185 s** (`qa/mascot-swift-{1,2}.log`). No polling test flaked; no isolated polling rerun was
needed. This adds nine tests to the earlier 2,766-test sprite/scenery checks, whose logs remain in `qa/`.
The requested `PYTHONDONTWRITEBYTECODE=1` CLAUDE.md size/link pytest command passes **2 tests in 1.08 s**
(`qa/mascot-claude-size.log`).
`make app` builds only this worktree's debug bundle; it installs and launches nothing. The built
`.build/arm64-apple-macosx/debug/Cicada.app` contains **36 PNG/JSON pairs plus the manifest (73 files)**,
with every PNG/JSON SHA-256 matching its manifest entry and no extra sprite files. The bundle's sprite bytes total
**1,834,301** (`qa/mascot-build.log`, `qa/mascot-bundle.json`). `git diff --check` is clean.
The Run C call-site size check reads `IntakePanel`'s reading/importing `pointSize: 48` and
`EmptyStateLayout.wormPointSize = 96`; `BookwormArtTests.testSizesAtTheCallSites` verifies their integer-scaled
room-sheet results (**64 × 48** and **128 × 96 pt** at unit UI scale). This is code/test verification, not another
live UI inspection.
The first full suite overlapped the exporter and SwiftPM copied a transient resource set missing
`bookworm-reading-night-dark.png`; all 12 resulting failures traced to that missing file.
The failed attempt is retained as `qa/integration-swift-overlap.log`; it is not counted as a green pass.
Two completed full exports pass all art verifiers and match **119 files byte for byte**.
`qa/mascot-export-{1,2}.log`, `qa/mascot-export-compare.log` and `qa/scenery-rebuild.json` record them. The Mascot
addition changes no art source, PNG/JSON, palette, sidecar, manifest or preview bytes.
The offline script smoke check passes **36 sheets / 429 tags / 480 combinations**; it is a Canvas stub, not a browser.
Resources measure **1,834,301 bytes** (cap 6 MiB), **6,151,414 decoded pixels** (cap 8,388,608).

## Open work and review gate

Q1 stays first: running Sleep still sleeps while queued/paused work reads; the owner's earlier brief requested
reading while consolidating. The state machine and matrix remain unchanged. Count props (computer, phone, globe,
TV, letter tray, calendar), the queue as a room (cart/crate/bookcase), G175 pixel marks and a second G127 character's own base
are separate design rounds. Time-of-day lighting, local/manual scenery and the clock are complete.
B12's narrower menu lens needs the owner's decision. The sleeping-outro to reading key frame can still change a
standing closed book to an open book in one frame; the sheets have no named opening beat. This limitation is
documented rather than inventing a state transition.

Owner motion review in [preview.html](preview.html) and the Sleep page, demo-bank light/dark review at
0.8×–1.4× and idle CPU (≤ 3% of one core and within 2 points of dev) remain required before merge.
No PR was opened and no commit was made by this integration run.


## Mascot selector addition — owner 2026-10-02

The selector beside The scenery names the current character **Bookworm**. `MascotRegistry` is pure and holds
exactly one entry: `bookworm`, Bookworm, room prefix `bookworm-`, menu sheet `bookworm-small` and this art folder.
The per-viewer `cicada.mascot` AppStorage preference defaults to Bookworm; unknown stored ids resolve to Bookworm
without reading or changing a bank. `BookwormArt` routes state/night/transition sheets, reading covers and geometry
through that entry. Shared `BookwormView` observes the choice on room/empty/intake and all other call sites. The
menu renderer separates image-cache entries by mascot id, and a choice change restarts its timer at the key frame.
Existing Bookworm types, state precedence and response matrix retain their names and meaning.

The tile follows Settings' existing list/scenery grammar, uses the awake room key frame and the 18 × 18 menu head
at 2×, and marks selection with a checkmark plus neutral ground/ring. It has native keyboard focus and the VoiceOver
label **“Bookworm, selected”**, with no future-character teaser. A new character supplies its own base, shared
canvases/tags/slices, day and dark/lit night sheets, a menu sheet, manifest entries and one registry entry.

Registry tests verify unique ids, all 25 mascot sheet pairs in the manifest, exact existing Bookworm names for all
32 state/lighting/lamp combinations, transition resolution, isolated persisted preferences and fallback. A synthetic
nonregistered skin verifies that explicitly requested sheets do not silently fall back to Bookworm; another cache
test verifies identity separation even when pixels happen to be the same. Tile tests cover labels/search/focus/marks
and actual key-frame pixels. Targeted validation passes **43 tests / zero failures**.

Four additional ImageRenderer panes were inspected individually; paths relative to this art directory:

| Path | Observation |
|---|---|
| `qa/integration/settings/mascot-bookworm-light.png` | Compact left tile; room worm and menu head are crisp, with Bookworm, checkmark and dark selection ring clearly visible. |
| `qa/integration/settings/mascot-bookworm-dark.png` | Both green designs remain readable on the neutral ground; white ring/checkmark clearly mark selection. |
| `qa/integration/settings/mascot-missing-character-light.png` | Unknown stored id shows the identical selected Bookworm tile without an empty or placeholder option. |
| `qa/integration/settings/mascot-missing-character-dark.png` | Same fallback and selection in dark appearance; no missing-image or native-view warning patch. |

The review index now contains **552 room renders / 24 boards / ten Settings panes** (six scenery and four Mascot).
Unlike the scenery source menu, the Mascot button/key-frame views render directly in ImageRenderer. No live keyboard
or VoiceOver session was driven; focus/labels are checked in the view/tests. The selector foundation is complete;
a second character's base and G127's room shortcut remain open. Final full-suite/export/build checks are in the
verification record above.
