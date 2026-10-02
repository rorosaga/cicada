# Study-room scenery delivery — 2026-10-02 (G176)

**Historical art-run snapshot, before final integration.** The completed app integration is recorded in
[INTEGRATION_REPORT.md](INTEGRATION_REPORT.md). Its dated rain timing amendment changes the unchanged 48 rain frames
from 80 to 100 ms (4,800 ms loops); final resources total 1,835,725 bytes after the static-provenance metadata update.
The current rebuild comparison includes 120 files; the earlier 119-file comparison below predates that authoring record.
The earlier measurements and timings
below describe this art delivery, not the final integrated timing. All 36 sheet pairs are now integrated with the app.

Art-only delivery against the [binding scenery contract](../../../../../docs/specs/2026-10-02-study-room-scenery.md),
including its committed wall-clock amendment (`aa39cc1a`). That amendment brings the delivery from 35 to **36 sheet
pairs: 429 tags, 4,426 frames**. Swift and test edits from the superseded night-room brief were restored to HEAD;
only sprite resources remain changed under Sources. The app run owns integration, Swift tests, TODO, the backlog and
architecture docs. No GUI, computer use, app launch, bank access or git commit was used for this delivery.

## Art and names

The room is dark when **time == night OR base == rainy**, independently of the worm mood. Dusk otherwise keeps the
existing day-lit interior. The schedule still decides whether the lamp is lit.

- Six room props retain their day tags and gain `night-dark` / `night-lit`: backdrop, window, plant, lamp, bean bag, mug.
- All eight states have parallel `bookworm-<state>-night-dark` and `bookworm-<state>-night-lit` sheets: awake, sleeping,
  digesting, happy, curious, hungry, reading, error. Every tag, frame, duration, slice and alpha mask matches its day
  counterpart; all covers, poses, beats and sleeping transitions are included. Parallel sheets keep the tag vocabulary
  identical and avoid multiplying the reading sheet's 54 tags.
- `room-weather` has `{sunny,cloudy,windy,rainy,curtains}-{day,dusk,night}` (15 tags).
- `room-skyfx` has `mist-day`, `mist-dusk`, `mist-night`, `rainbow-day`, `rainbow-dusk`, `shootingstar-night` (6 tags).
- `room-clock` is 15 × 15: `face`, `face-night` (one frame each), and `hour`, `hour-night`, `minute`, `minute-night`,
  `second`, `second-night` (60 whole-pixel angles each). Hour/minute hands are black; seconds are red. Night versions
  are darker. It is placed at lattice (94, 34), z=1, clear of every worm frame, window, lamp and the reserved pile.
  The angles are data, not animation loops; no clock entries are added to the motion sidecar.
- The menu-bar worm, fly and spine masks are unchanged.

## Palette and light map

`palette.json` retains **81 authoring keys**, below the 87-key budget. Keyless schemas declare every derived colour:
`night.ramps` maps every day colour over seven bands; `scenery.ramps` supplies dusk/night tints, `scenery.colors` supplies
mist/rainbow/star colours, and `clock.colors` supplies dial/rim/red-hand colours. There are **699 distinct declared RGBs**.
Both the Python and Lua palette checkers read these declarations. All outputs have binary alpha.

`room-light-map.json` is a categorical 160 × 64 map in top-left coordinates. Bands are deep cool shadow, two faint cool
window bands, and four warm lamp bands (edge, low, mid, hot). The lamp map applies only when lit; its band wins where
sources overlap. The map stops before the pile column. The warm pool follows the shade, wall, floor, plant, near bean
bag and lamp-facing worm. There is no interpolation, gradient, dithering or fractional alpha. The lamp-shade colours also follow the map;
the mug’s rim shares one of those day colours and stays dim outside the lamp pool.

The worm stays green enough to be the subject. Closed lids and Xs keep strong contrast; the question glyph has a
registered pale ramp; z's and sparkle keep their original glyph colours; sweat and eye glints stay readable. The open
book's grey page lines are darker than its cream paper on every night reading frame.

The day worm/prop pixels remain unchanged. Four day weather loops remain pixel- and timing-identical to the previous
skies. Cloudy preserves its colours, frame counts, durations and horizontal cadence, but lifts the near cloud from y=9
to y=6 and its lower far cloud from y=23 to y=5: the former placement failed ruling 9 once every mood, including curious,
became reachable. Night cloudy has a denser deck; stars sit behind passing clouds. Night wind retains the swaying tree.
Rain never flashes. Curtains are lit behind by day, warm at dusk, nearly dark at night.

Aseprite's GIF quantizer merged two nearby night colours by one RGB level. QA GIFs therefore use an exact indexed
Pillow palette from the independently decoded exported PNG frames, then pass the same pixel/duration comparison.
Aseprite sources and shipped PNG/JSON pairs are still exported and re-exported headlessly. Each derived source also
carries its actual used colours in its Aseprite display palette.

## Loop timings

| Tags | Frames | Per-frame ms | Loop ms |
|---|---:|---|---:|
| sunny-day | 36 | 500 | 18,000 |
| sunny-dusk | 36 | 300 | 10,800 |
| sunny-night | 24 | 200 | 4,800 |
| cloudy-{day,dusk,night} | 72 each | 200 | 14,400 |
| windy-{day,dusk,night} | 36 each | 120 | 4,320 |
| rainy-{day,dusk,night} | 48 each | 80 | 3,840 |
| curtains-{day,dusk,night} | 8 each | alternating 600 / 300 | 3,600 |
| mist-{day,dusk,night} | 36 each | 300 | 10,800 |
| rainbow-{day,dusk} | 12 each | 600 | 7,200 |
| shootingstar-night | 48 | 250 | 12,000 |

Mist is two sparse drifting wisps (maximum 25 of 1,152 pane pixels). The rainbow is a five-band arc behind the frame's
mullions with a quiet moving glint. The shooting star is visible for eight frames, then the sky is empty of the overlay
for forty frames (10 seconds). Integer motion and every wrap/seam are recorded in `room-motion.json`.

## Checks

Both final `tools/export_all.sh` runs pass the complete verifier: **36 sheets, 429 tags, 4,426 frames**.
`tools/check_scenery_rebuild.py compare` confirms **119 files byte-identical**: all 36 Aseprite sources, three saved
part files, 72 PNG/JSON exports, the manifest, palette, day baseline, light-map/plan/motion sidecars, preview and
menu alias. Evidence: `qa/scenery-final-export-1.log`, `qa/scenery-final-export-2.log`, `qa/scenery-rebuild.json`,
`qa/verification.json`. The offline smoke check passes after the second export too.

```sh
tools/export_all.sh
python3 tools/check_scenery_rebuild.py record
tools/export_all.sh
python3 tools/check_scenery_rebuild.py compare
node tools/check_preview.mjs
```

Measured weighted RGB luminance (0–255, `.2126R + .7152G + .0722B`):

| Region | Night lamp dark | Night lamp lit | Day lamp lit |
|---|---:|---:|---:|
| Whole backdrop | 43.39 | 62.26 | 185.63 |
| Lamp wall | 35.32 | 109.45 | 174.43 |
| Plant | 53.14 | 63.36 | 147.86 |
| Near seat | 51.54 | 74.05 | 103.43 |
| Near worm | 47.94 | 57.89 | 111.88 |
| Far wall | 41.93 | 41.93 | 184.18 |
| Far worm | 48.75 | 48.75 | 156.94 |

The dark/lit night backdrop is 23.4% / 33.5% of day luminance. Near-lamp warmth (`R − B`) rises in each tested region;
the far wall and far worm are identical between lamp states and below 40% of day luminance. The dark-lamp sill and
floor spill remain cool.

- **2,126 night frames** checked pixel-for-pixel against the declared relight, with exact frame/tag/timing/slice/alpha
  parity. **1,446 sleep/sparkle glyph pixels** remain unchanged. Minimum closed-lid contrast: **38.58**; minimum open-book
  line contrast: **16.13**. X eyes, sweat and all question frames also pass.
- **15 weather and 6 overlay loops** pass palette/alpha, timing, actual-motion, seamless-step and key-frame checks; every packed night texture also passes palette/alpha, size and rectangle bounds.
  All celestial pixels remain visible against the union of every pose/cover/beat/transition of all eight moods.
  Minimum cloud visibility is **50%** (cloudy-day itself now **63.64%**).
- Rain's maximum luminance deviation is **0.210% day, 0.218% dusk, 0.285% night**, below the 2% no-flash limit.
- Overlay ink visibility: mist **100%**, rainbow **57.59%**, shooting star **100%**; base key shapes are never entirely
  hidden. The shooting-star loop is **83.33% empty**.
- Clock: **360 hand angles**, **2 dials**, and placement against **24 worm sheets** pass. Its night dial has **29.66%**
  of the day dial's luminance.
- **17 original day sheets' pixels/timings** and **11 original PNG/JSON pairs' bytes** remain unchanged. Four day sky
  loops remain unchanged; cloudy's documented placement adaptation is checked against the all-mood visibility rule.
- Resources total **1,834,157 bytes** (limit 6 MiB) and **6,151,414 decoded pixels** (limit 8,388,608).
- Offline preview script smoke: **36 sheets, 429 tags, 480 room combinations**, every overlay choice, all 15 labelled
  scenery thumbnails, mood/lamp selection, Reduce Motion, Low Power, pause, step and one-shot pose controls pass.
  This executes the actual inline script with a Canvas stub; browser rendering is not claimed.

Swift tests are owned by the parallel app run. No Swift/test diff remains here; the new asset contract intentionally
requires that run's updated expectations, so this art delivery does not claim an unchanged-app Swift test result.

## Renders read

All paths are under this art directory; `qa/` is gitignored. Exact generated paths are in
[`qa/scenery/render-paths.json`](qa/scenery/render-paths.json).

- `qa/scenery/room-matrix@3x.png`: all twelve day/dusk/night × sunny/rainy × lamp-dark/lit combinations.
- `qa/scenery/room-{day,dusk,night}-{sunny,rainy}-{dark,lit}@{1,3,6}x.png`: individual rooms. Native night-sunny dark/lit
  and day-sunny lit were also read at 1×; night-sunny lit at 6×.
- `qa/scenery/weather-keys@6x.png`, `weather-keys@1x.png`, and `weather-{base}-{time}@6x.png`: all 15 weather key frames.
- `qa/scenery/overlay-matrix@3x.png` and `overlay-{sunny,rainy}-{mist-day,mist-dusk,mist-night,rainbow-day,rainbow-dusk,shootingstar-night}@3x.png`:
  every overlay variant over two bases.
- `qa/scenery/worm-{awake,sleeping,digesting,happy,curious,hungry,reading,error}-{dark,lit}@6x.png` and
  `worm-states-{dark,lit}@6x.png`: four samples per state and lamp variant (64 samples), including a cheer sparkle.
- `qa/scenery/clock-dials@6x.png`: eight day/night clock composites.

Visual review: night and rain read as a cool dark room. The lamp warms the left side and near seat while the tail and
far wall remain cool. The green worm stays the subject, with readable eyes, z's, question, sparkle, Xs, sweat and book
lines. The clock is separate from all worm ink and subdued at night. Dusk changes the sky while sunny interior light
stays as before. The mist stays sparse, the rainbow remains recognizable behind the mullions, and the shooting-star
hold leaves the base sky readable.

## Files

Exact changed/new paths are listed in `qa/changed-files.txt`.

- Palette/contracts: `palette.json`, `day-art-contract.json`, `room-light-map.json`, `room-plan.json`, `room-motion.json`.
- Lua: modified `ase_helpers.lua`, `build_room.lua`, `build_weather.lua`; added `build_night.lua`, `build_skyfx.lua`,
  `build_clock.lua`, `scenery_common.lua`.
- Tools: modified `export_all.sh`, `verify.py`, `verify_room.py`, `manifest.py`, `make_preview.py`,
  `preview_template.html`, `check_preview.mjs`, `make_room_review.py`; added `night_palette.py`, `verify_night.py`,
  `verify_clock.py`, `make_scenery_review.py`, `check_scenery_rebuild.py`.
- Sources/exports: rebuilt the six static room sources, replaced `room-weather`, added `room-skyfx`, `room-clock` and
  sixteen night worm sources; matching PNG/JSON pairs and `sprites.manifest.json` are in Resources/sprites.
- Delivery/docs: `preview.html`, `README.md`, this report, and the dated amendment in the 2026-10-01 sprite spec §5.

Rebuild commands are in the [README](README.md). App integration, Settings, forecast reads and Swift suite validation
remain with the app run. No art issue remains open. Browser rendering and Swift/app integration validation remain with the app run.
