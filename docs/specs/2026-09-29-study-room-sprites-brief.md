# Study room sprites: a new bookworm, a room that shows what's waiting, and real animation

**Status:** brief for a fresh session, 2026-09-29. Design first (sprites, sheets, previews, the room's rules), then
build (a native sprite player and the room composed from real counts), each as its own PR to `dev`.

## 1. The owner's ask (his words)

> "can you design the brand new sprites with animations and keep them saved in some directory? maybe the amount of
> books in the library can represent the amount of episodes and things to consolidate. Maybe a computer with a crt like
> box tv on a desk turns on when websites have to be consolidated. A phone turns on for social media and stuff, books
> appear for blogs or whatever, stuff like this would be cool to see in the environment, and have them all be
> interactive."

Earlier the same day: the first mock pass "looks super simple"; "the book worm mascot itself and the queue of stuff, i
want to do a better design for the queue of things"; "the character animations i think you can improve them".

## 2. What exists (read before designing; verify every line in code)

- **The worm** is pixel art drawn from data in Swift, not image files: `app/CicadaApp/Sources/CicadaApp/MenuBar/`
  (`BookwormSprites.swift`, `BookwormState.swift`, `BookwormPose.swift`, `BookwormRenderer.swift`,
  `PixelRenderer.swift`), shown in the menu bar and on the Sleep page (`Views/Common/BookwormView.swift`). States and
  response beats, and the matrix that allows them, are in CLAUDE.md, "Mascot states (G107)".
- **The study room** is the Sleep page's art: `Views/Sleep/StudyRoom.swift`, `DeskScene.swift`,
  `DeskSceneSprites.swift`, `DeskPalette.swift`, `RoomModel.swift`, `WindowWeather.swift` (the window's weather is a
  total function of the mood), `LampPopover.swift` (the lamp = the schedule), `BookPile.swift` (`fitPile`: at most eight
  spines, the order and every count kept), `DeskHotspots.swift` (interaction is a hotspot layer derived from the pure
  layout), `RoomSentence.swift` / `WormAnswers.swift` (the one sentence and the worm's answers).
- **Rules that bind the room** (CLAUDE.md, Sleep page paragraph and Track Z; `docs/design/DESIGN_RULES.md`;
  `docs/design/ART_DIRECTION.md`):
  - R-Z1: *state art* (mood frames, lamp, pile, weather) is a total function of real state; *response art* (gaze, perk,
    talk, cheer) is transient and never contradicts state.
  - **No click on art changes what the machine does.** Hotspots open popovers and links; Consolidate stays the one
    trigger (G125 R10). A prop may *show* and *link*, never *start* work.
  - Every fact on the art has a text twin (R-A3): the sentence, `.help`, VoiceOver.
  - No estimates (G107): counts are measured.
  - Worm motion lints today: no `.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(` on the worm except its lattice
    placement; a beat is at most 3 frames × 0.12 s; a hop is a whole-cell shift; renderer keys ≤ 256 per size.
- **The queues whose counts the room can show:** unprocessed episodes by origin (`GET /sleep/episodes`,
  `/sleep/status`); the agent reading queue with `needs_login` (in flight on `feat/agent-reading`, the G164–G168 rows,
  `docs/specs/2026-09-29-reading-the-web-design.md`); the video watch queue (designed, not built: G162,
  `…-video-understanding-design.md`); the inbox (`GET /inbox`); saved-content connectors (Pinterest, Reddit, X) and
  browser bookmarks (`/sources/channels`); calendar events. Consolidate now reads everything waiting, batch by batch
  (in flight on `feat/consolidate-reads-everything`), and the Sleep page v5 spec (`…-sleep-page-v5-design.md`) has the
  drain's progress model.
- **Design work already done today:** the canvas https://claude.ai/artifact/FDqb1tSiqsWdFQEDGYm3JF (read it with the
  Artifact tool's `read` action) holds the Sleep/video/web mocks and, once published, an Opus redesign of the worm
  (a sprite sheet at room and menu-bar scale, old vs new) and of the queue (a pile that reads by kind, a shelf that fills
  as batches file, a full-window queue view). Build on those boards; do not start from zero.

## 3. The room as a picture of what's waiting (proposal; the owner decides the final set)

Each prop is **state art**: its look is a pure function of a real count, bucketed so it never implies precision it
does not have, and it has a text twin. Proposed mapping, extending the owner's ideas:

| Prop | Shows | Off / on / busy |
|---|---|---|
| **Library shelf + reading pile** | Episodes waiting to consolidate (conversations, notes, imported chats), and what got filed | the pile grows with the waiting count (buckets, e.g. 0 · 1–5 · 6–25 · 26–100 · 100+); books move from pile to shelf as batches file during a drain |
| **Books by kind** | Blogs/articles and saved pages become books too, with a spine style per kind | a new spine style appears when that kind has items |
| **CRT computer on the desk** | Web pages waiting to be read (the reading queue) | dark → boots (scanline) → a scrolling page while a read is running; a small padlock on screen when any link **needs login** |
| **Phone** | Social saves waiting (X, Reddit, Instagram, LinkedIn, Pinterest, TikTok) | dark → lit with a dot count bucket → buzz beat when new ones arrive |
| **Small TV / film reel** | Videos in the watch queue (G162, once built) | dark → glow; "picked up by an agent" = a play glyph |
| **Letter tray** | Inbox questions (Needs you) | empty → a letter → a stack |
| **Wall calendar** | Calendar events captured | pages flip on a new day's events |
| **Lamp** (exists) | The schedule | unchanged meaning |
| **Window weather** (exists) | The mood | unchanged meaning |

Open questions for the owner: the final prop set (keep it a closed set, about six); bucket thresholds; whether the
shelf shows *filed* (a growing library of what is known) or only the pile shows *waiting*; where video lives before
G162 ships (probably hidden); whether props appear at all on a fresh, empty bank (a quiet room is the honest answer).

**Interaction, within the rules:** hover highlights the prop and shows its real count (`.help`); a click opens a small
popover with the counts in words and one link to where the thing lives (Sources, Reading the web, the Feed's Videos,
the Inbox); nothing starts from art. The worm reacts (response art: gaze toward the hovered prop, perk on a click). Every
prop has a keyboard focus stop and a VoiceOver label with the count.

## 4. The worm, redesigned, with real animation

Keep Cicada's identity (a green bookworm with orange glasses) and redraw it: a clearer silhouette, a readable face at
menu-bar size (16–22 px tall), personality. Animation sets as named tags with per-frame durations, all on the pixel
lattice:

- **States:** idle (breathing, random blink), sleeping (slow breath, drifting Z's), reading (page turns, eyes tracking
  lines), digesting / consolidating (chewing, a book shrinking into it), happy / cheer (a real hop, sparkle), hungry,
  curious, error (red eyes stay fixed, per the matrix), plus the menu-bar set.
- **Responses:** perk, talk, gulp, shake, attentive / expectant gaze (toward a prop or a hovering file).
- **Props:** CRT boot, scanline and scroll; phone light and buzz; book slide from pile to shelf; TV flicker; letter
  drop; calendar page flip.

This needs a dated amendment to the worm lints (Track Z): frame-based animation with per-frame durations and loops
beyond three frames, still whole-pixel, still no interpolated transforms. Say so in the design PR; the owner rules on it.

## 5. How to make the sprites (no Aseprite MCP needed)

- **Tool:** the owner's self-built Aseprite at `/Applications/Aseprite.app`, driven headless:
  `/Applications/Aseprite.app/Contents/MacOS/aseprite -b --script <file>.lua` (plus `--script-param` for inputs). Lua
  scripts create the sprite, layers, frames, per-frame durations and tags pixel by pixel, save a layered `.aseprite`
  source, and export a packed PNG sheet plus JSON (`--sheet`, `--data`, `--format json-array`, `--list-tags`). The owner
  can open and hand-tweak any `.aseprite` file in the app. Computer use in the GUI is not needed and is worse.
- **Fallback:** Python + Pillow generating the same sheets from pixel grids, if a Lua API gap bites.
- **Where things live (in the repo, so they travel):**
  - sources and generators: `app/CicadaApp/Art/sprites/` (`*.aseprite`, `*.lua`, a README naming the palette and the
    grid);
  - exported sheets the app loads: `app/CicadaApp/Sources/CicadaApp/Resources/sprites/` (`*.png` + `*.json`) with a
    `sprites.manifest.json` in the style of `art.manifest.json` (generator, script, date, licence = own work, sha256),
    and a test that verifies every sheet's sha256 and that each JSON's tags match what the app asks for;
  - a preview page, `app/CicadaApp/Art/sprites/preview.html`, that plays every tag at its real timings (open it
    locally), and the same animations published as boards on the canvas for the owner's review.
- Palette: derive from the current `BookwormSprites`/`DeskPalette` colours, extended deliberately; one palette file both
  the Lua scripts and the app read.

## 6. Phases

1. **Design (no app change):** the prop set, the buckets, the worm and prop animation lists, the sprites and sheets, the
   preview page and canvas boards, the Track Z lint amendment written out. PR to `dev` with the art and the spec; the
   owner reviews the motion before anything is wired.
2. **Build:** a native `SpriteSheetPlayer` (SwiftUI `TimelineView`, nearest-neighbour sampling, per-frame durations,
   paused when the window cannot be seen and gentler under Reduce Motion / Low Power, like Home's band), the worm moved
   onto it behind the existing state × response matrix, the room composed from real counts (`RoomModel` /
   `SleepPageModel` gain the counts; the props' looks are pure functions, unit-tested), hotspots and popovers per §3,
   text twins, lints updated per the ruling. PR to `dev`.

## 7. How to work

Read `CLAUDE.md` and `docs/goals/working-method.md` first. Use workflows (Opus for design and the pixel art, Sonnet for
the Swift/Python implementation), a critic before building, a review per task, the full Python and Swift suites before
every PR, PRs to `dev` (never `main`), and never merge without the owner's word on the design phase. Privacy rule: no
names or content from the owner's banks anywhere; counts in mocks are placeholders. Record the prop set and the lint
amendment as dated rulings in `docs/goals/TODO.md` once the owner decides, and add a backlog row (or edit G125/G107)
in `docs/goals/memory-evolution.md`.
