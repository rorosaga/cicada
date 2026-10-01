# The owner's bookworm as animated sprite sheets, the study room around it, and the app on a sprite player

**Spec, 2026-10-01. Backlog G176 (with G107, G125, G127). Branch `feat/study-room-sprites`, PR to `dev`.**
This is the binding brief for three Codex runs (gpt-6.1-sol, extra-high effort): **A** draws the worm, **B** draws the
room and builds the export pipeline, **C** wires both into the app. Each run reads this whole file before starting.
Where this spec and an older doc disagree, this spec wins, and §8 records the amendment. Where it gives a number,
use that number. Where it gives a default for an open question (§11), build the default.

**Path prefixes used everywhere below.** All paths are relative to the worktree root, `<worktree>`: the
`feat/study-room-sprites` worktree at `.worktrees/study-room-sprites` under the main checkout. The orchestrating prompt
gives its absolute path; no path on the owner's machine is written into this repo (the #118 rule):

| Prefix | Means |
|---|---|
| `S/` | `app/CicadaApp/Sources/CicadaApp/` |
| `T/` | `app/CicadaApp/Tests/CicadaAppTests/` |
| `ART/` | `app/CicadaApp/Art/sprites/bookworm-2026-10-01/` (sources: never bundled, `app/CicadaApp/Package.swift:10` copies only `Resources/`) |
| `RES/` | `app/CicadaApp/Sources/CicadaApp/Resources/sprites/` (exported sheets the app loads) |
| `D3` | `docs/specs/2026-09-23-round3-design-mascot-page.md` (Track Z) |
| `BRIEF` | `docs/specs/2026-09-29-study-room-sprites-brief.md` |

**Rails for every run.**
- Work only inside `<worktree>`. Never edit, check out, stash or commit in the main checkout (`<worktree>/../..`),
  which feeds the owner's auto-updater.
- Never read `memory/`, `~/.cicada` or `~/.claude/projects` (the owner's private bank).
- Never run `make dev` or `app/CicadaApp/install_app.sh`. They install over `~/Applications/Cicada.app`, the owner's
  installed app.
- Never point a running Cicada at a bank to take a screenshot. Screenshots are of Aseprite, the preview page and the
  test composites only.
- The privacy rule (`CLAUDE.md`, "Privacy rule"): no bank names, titles or content in any file, commit or PR body.
  Counts in previews are placeholders.
- Commit only if the orchestrating prompt for your run says to. If it does, commit on `feat/study-room-sprites` with
  messages that cite `G176`, and end them with the attribution lines that prompt gives you.

---

## §0. The owner's words and the scope

**The ask, verbatim (Rodrigo, 2026-10-01):**

> "I've already done here the base model of the bookworm i want. Can you iterate with codex sol 6.1 extra high effort
> all the sprites with the animations? and generate the assets like the lamp, extra books, window, environment behind
> window animated too. Little fly (pixel size almost), moving around turned on lamp. Have environemnts for sunny, night,
> windy, rainy... all animated. You will find the bookworm png and 5 emotion states here app/assets/. Make sure to
> generate everything, have codex implement it using computer use in aseprite and add it to the app."

The reference art has been copied into the worktree at `ART/reference/`:
- `bookworm.png` is the base model.
- `bookworm_all_states.png` and `bookworm_{happy,mad,sad,tired,worried}.png` are the five emotions.
- `bookworm_menu_bar.png` is the owner's own menu-bar worm: the source of the 18 × 18 set (§1.7). It was added to the
  folder after the others (13:37 against 13:04).
- `glasses.png` is the authority for the glasses' frame ramp and specular; `cicada.png` is a brand reference (§1.1).

It is untracked today (`git status`: `?? app/CicadaApp/Art/sprites/bookworm-2026-10-01/`). Run A adds it to the branch.
It supersedes the round-1 "worm directions" on `feat/worm-directions`. Take lessons from that round's scripts (§10.5),
never its art.

**In scope (build all of it):**

1. **The worm, room scale.** Every `BookwormState` (`S/MenuBar/BookwormState.swift:6-33`) as an animated loop:
   - idle breathing with irregular blinks;
   - reading, with the eyes tracking lines, real page flips, and picking up the next book (a new cover);
   - sleeping, with slow breath and z → zz → zzz rising, growing and fading;
   - digesting (chew and gulp), happy, hungry, curious and error;
   - awake (the cold-start state).

   Also every response the code already has: `perk`, `talk`, `gulp`, `shake`, `cheer` (`S/MenuBar/BookwormPose.swift:65-70`)
   and the `attentive`/`expectant`/`eager` poses with left/centre/right gaze (`:15-41`). Plus two cheap transitions: a
   yawn into sleep and a stretch on waking.
2. **The worm, menu-bar scale.** An 18×18 set redrawn from the owner's own menu-bar design (`bookworm_menu_bar.png`:
   head, glasses and neck in two colours, no book).
3. **The room:**
   - wall and floor with texture and one light direction;
   - the window frame;
   - **seven animated weather backdrops** behind the glass, one per `WindowWeather` case
     (`S/Views/Sleep/WindowWeather.swift:9-15`);
   - the lamp, dark and lit with a warm glow;
   - a **1–2 px fly** that circles the lamp only while it is lit;
   - the bean bag the worm sits and sleeps on (it replaces the cushion), the plant and the mug, all redrawn in the new style;
   - **extra books**: three reading-book covers for the worm, plus per-kind pixel spine textures for the REAL pile (the
     default reading of the owner's words; §11 Q16 offers a shelf instead);
   - static lived-in details in the backdrop: a rug, the lamp's cord and a baseboard bevel (BRIEF `:158`).
4. **The app.**
   - A native Aseprite-sheet loader and a `SpriteLayerView` player: per-frame durations, nearest-neighbour, paused when
     the window cannot be seen, the key frame under Reduce Motion, half speed under Low Power.
   - The worm on that player, behind the unchanged state machine and response matrix, and the room composed from
     sheets on one lattice.
   - Hotspots, popovers, accessibility and text twins preserved, and the menu bar updated.
   - Tests, a sha256 manifest, and the lints amended.

**Out of scope (record as next steps in §8.1–§8.2; do not build):**
- The count-driven props of BRIEF §9: CRT computer, phone, globe, TV, letter tray and calendar.
- The queue as a room: cart, crate, bookcase and finished-books shelf.
- Pixel brand marks (G175).
- Time-of-day room palettes and the night light.
- Any decorative book pile (P10 holds; see R-BW9).
- Mug steam and plant sway: they are motion with no fact behind them (R-BW4).

**Orchestrator decisions this spec is built on (binding):**
- The base character is the owner's reference: blue book, charcoal glasses, green body, no antennae. It is redrawn as
  clean pixel art on a whole-pixel grid, faithful to the reference silhouette. The five emotions are the sources for
  the expressions, and the 18×18 menu-bar worm follows the owner's own menu-bar design (§1.7).
- The owner's request is his decision to amend "idle is still", "no `TimelineView` in the room", the refused drift and
  the "≤ 3 frames × 0.12 s" beat rule for the sprite world. §8 holds the dated texts.
- These still bind:
  - state art is a total function of real state;
  - response art never contradicts state;
  - no click on art starts work;
  - every fact has a text twin;
  - Reduce Motion is honoured;
  - the privacy rule.

**Deliberate deferral (Q1).** The owner's 2026-09-29 words, "be reading books when consolidating"
(`docs/goals/memory-evolution.md:754`; BRIEF `:151`, `:173-174`), conflict with today's state machine, where `.sleeping`
*is* a running cycle (`S/MenuBar/BookwormState.swift:10-12`). This PR keeps the machine, and Q1 is the first line of the
PR body. No sheet bakes the mapping in: the reading sheet carries no stage cue and the sleeping sheet no reading cue, so
a swap is a mapping change, not new art.

---

## §1. The reference, analysed

### 1.1 The files (measured)

| File | Size | Format | sha256 (prefix) |
|---|---|---|---|
| `ART/reference/bookworm.png` | 1536×1024 | RGBA | `b73184a49473e8b377756a0b9c31f3aae2f75db0e1eed639df3abc248cd43049` |
| `ART/reference/bookworm_all_states.png` | 1536×1024 | RGB, no alpha (cream `#FEFAEF` ground) | `dfbfe2d79235f4a1e79090b958d8cc80393bd3654018a3c9d6bccfacd3964edb` |
| `ART/reference/bookworm_happy.png` | 1536×1024 | RGBA | `5578b61a…` |
| `ART/reference/bookworm_mad.png` | 1536×1024 | RGBA | `bd66a4ce…` |
| `ART/reference/bookworm_sad.png` | 1536×1024 | RGBA | `28de0b4b…` |
| `ART/reference/bookworm_tired.png` | 1536×1024 | RGBA | `b7837762…` |
| `ART/reference/bookworm_worried.png` | 1536×1024 | RGBA | `543088ce…` |
| `ART/reference/bookworm_menu_bar.png` | 1254×1254 | RGBA | `10475da8405e9ca99bf92cfa31236f284fdf07675896c2aa52c1deba8d3f1ac4` (the owner's menu-bar design: the 18 × 18 set's source, §1.7) |
| `ART/reference/glasses.png` | 1604×981 | RGBA | `7f245bf1…` (the glasses' frame ramp and specular) |
| `ART/reference/cicada.png` | 1254×1254 | RGBA | `23516c5c…` (brand reference; not part of the worm) |

**What the two extra references are for.**
- `glasses.png` is the authority for the frame's ramp: a `K` outline, a `D` body and an `L` light along the top rim and
  the top of the arms, plus the stepped 3-cell specular. Match the room worm's glasses to it.
- `cicada.png` is not drawn in this PR (§11 Q17).

**What the figure is.** A horizontal green worm.
- **Head:** a big head at the upper left with oversized charcoal glasses. The left lens is smaller (farther away), the
  right lens bigger, and a temple arm hooks back to the right.
- **Eyes:** no eye-whites. The eye is body green seen through the lens. The left pupil is a black sliver against the
  inner rim; the right pupil is a rounded 4×4. Each eye has a white specular.
- **Book:** a closed blue hardcover held upright in front of the lower body on the left. It has white or cream pages
  at its top-left corner and a two-stripe spine.
- **Body:** an S-curve. A hump behind the head, then the tail tip turning up at the right.
- **Light and outline:** light comes from the upper left (the shadow green runs along the underside and the tail's right
  edge), with a near-black 1-cell outline everywhere.
- **What is absent:** no mouth in any file, and no antennae.

### 1.2 Grid (measured; a fitted approximation, not a lattice)

The reference is an AI render in a pixel-art *style*, not pixel-native.
- It has 39,549 colours and soft alpha. About 1% of pixels sit at alpha 1–127, and the "glow" is dim colour stored
  under alpha 0. Treat alpha ≥ 128 as opaque.
- Its cells are uneven, 12–22 px wide. Fourier peaks are 16.98 px in x and an unstable 14.68 px in y. The best uniform
  grid is 17 px (4.70 % reconstruction error), and fitted variable grid lines reach 3.18 %.
- The opaque figure spans x 218–1357, y 142–912. On the fitted grid the base worm is **70 × 47 cells**, outline
  included.

Do not resample the PNG into the app. **Redraw it** on a native grid.

**A spec-writing reader produced these grids** in the spec session's scratch directory (`…/scratchpad/spec/reference/`,
outside the repo; it may no longer exist): (`bookworm_grid.txt`, the `*_grid.txt` emotion grids, `room56_autodownsample.txt`, `menubar_candidate.txt`,
`palette.gpl`, `analysis.json`, `emotion_overlays/`). The grids are inlined below. **Run A must re-derive them itself**
from `ART/reference/` with `H.loadReference` and a fitted downsample (§10.2), and treat the inlined text as a cross-check.
Neither the inlined grids nor the scratch files are art: every one is a noisy starting point for a hand cleanup.

### 1.3 Palette (median of each colour's interior in `bookworm.png`; the emotion files drift brighter, so snap to these)

| Key | Role | Hex | Used for |
|---|---|---|---|
| `K` | outline | `#090707` | outline, pupils, brows, the inner lens rings |
| `G` | body light | `#9CC460` | body; also the eye seen through the lens (no lens tint, no eye-white) |
| `g` | body shadow | `#679144` | underside, neck under the glasses, tail edge |
| `D` | glasses dark | `#4A4647` | frame, temple arm, the core of the mad brows |
| `L` | glasses light | `#858182` | rim highlights (top and bottom), bridge, top of the arm |
| `B` | book mid | `#097FFD` | cover and spine face |
| `b` | book dark | `#0055B9` | spine shadow stripe, the cover's right edge |
| `H` | book light | `#2890FD` | highlight column on the cover's left edge |
| `W` | white | `#FDFDFD` | eye speculars; highlight in the sweat drop |
| `C` | page cream | `#FEF7EC` | lit side of the pages |
| `P` | page grey | `#BCB8B4` | shaded side of the pages |
| `S` | sweat | `#5FC8FB` | sweat drop (worried only) |

None of these is a reserved state hue. The banned list, `0x22C55E, 0xEF4444, 0xF59E0B, 0x3B82F6, 0x4A9EFF, 0x8B5CF6,
0x3BD97A, 0x6B7280, 0x999999`, comes from `T/DeskPaletteTests.swift:40-47` and `T/ThemeTokenTests.swift:71-82`. The
book blue is `#097FFD`, never `#3B82F6`.

### 1.4 The base grid, 70 × 47 (fitted; legend in 1.3; `.` is transparent)

Anatomy, as (row, col) in this grid:
- **Head dome:** rows 0–4, cols 17–34.
- **Left lens:** cols 5–16, rows 3–16. Pupil sliver at cols 13–15, rows 10–13; highlight at (8, 9–10) and (9, 9).
- **Bridge:** cols 17–18.
- **Right lens:** cols 19–37, rows 4–17. A 2-4-4-2 pupil at cols 26–29, rows 10–13; highlight stair at (8,25),
  (9,23–25) and (10,23–24).
- **Temple arm:** cols 36–45, rows 9–15.
- **Neck:** rows 15–19.
- **Book:** spine cols 1–5 and a crease at col 6; cover cols 7–22; pages at the top left.
- **Tail:** cols 60–69, rows 26–46.

```
......................KKKKKKKK........................................
....................KKGGGGGGGGKK......................................
..................KKGGGGGGGGGGGKKK....................................
........KKKKKKK..KGGGGGGGGGGGGGGGKK...................................
.......KLLLLLKKKKKGGGGGKKKKKKKKKKGK...................................
......KKLDDDDLLLKGGGGKKLLLLLLLLLKKKK..................................
.....KLLDKKKKDDDKKGGKLLDDDDDDDDDLLLKKK................................
.....KDDDKGGKKKDLKGKLDDDKKKKKKKDDDDLKK................................
.....KDDKWWGGGKKDKKKDDDKGWGGGGKKKDDDKKK...............................
.....KDDKWGGGGKKDLLKDKKWWWGGGGGGGKDDKLLKKK............................
......KDKGGGGKKKDDDKDKKWWGGKKGGGGKDDKLLLLLKK..........................
......KDKGGGGKKKDKKKDKKGGGKKKKGGGKDDKDDDDDLKK.........................
......KDKGGGGKKKDKGKDKKGGGKKKKGGGKDDKKKKKDDLKK........................
......KDLKGGGGKKDKGKDKKGGGGKKGGGGKDDKK..KKDDLK........................
.......KDLKKKKDDKGGKDKKGGGGGGGGGGKDDKK...KKDDK........................
........KDLLLDKKKGGKKLLKKGGGGGGKKDDKKK....KKK.........................
.........KKKKKK.KKgGKDDDDKKKKKKDDDDKg.................................
.................KgggKKKDLLLLLLDDKKgK.................................
........KKK.......KKgggKKKKKKKKKKKggK.................................
......KKCPKK........KKKgGGGGGGGGGggK..................................
....KKKCPPPK.....KKKKbKgGGGGGGGGgggK..................................
...KKCCCCPPKK..KKKKHbbKGGGGGGGGGggK...................................
..KKCCCCPPPKKKKKHHHBbbKGGGGGGGGGggK......KKKKK........................
.KCCCCPPPPKKKHHHBBBBbbKGGGGGGGGGGgKK...KKKGGGKKK......................
KKKKCCPPKKKHHBBBBBBBbbKGGGGGGGGGGGgKKKKKGGGGGGGKK.....................
KBBKKKKKHHHBBBBBBBBBbbbKGGGGGGGGGGGGGGGGGGGGGGGGKK....................
.KBBbbKHHBBBBBBBBBBBBbbKGGGGGGGGGGGGGGGGGGGGGGGGGKK...................
.KBBbbKBBBBBBBBBBBBBBbbKGGGGGGGGGGGGGGGGGGGGGGGGGKK.............KKK...
.KBBbbKBBBBBBBBBBBBBBbbKGGGGGGGGGGGGGGGGGGGGGGGGGGKK...........KKGGK..
.KBBbbKHBBBBBBBBBBBBBbbKGGGGGGGGGGGGGGGGGGGGGGGGGGGKK.........KKGGGGK.
..KBBbKHBBBBBBBBBBBBBbbKgGGGGGGGGGGGGGGGGGGGGGGGGGGKK........KGGGGGGgK
..KBBbKHBBBBBBBBBBBBBbbKgGGGGGGGGGGGGGGGGGGGGGGGGGGGKK......KKGGGGGGgK
..KBBbKHBBBBBBBBBBBBBBbKggGGGGGGGGGGGGGGGGGGGGGGGGGGGKKK...KGGGGGGGGgK
..KBBbKHBBBBBBBBBBBBBBbbKgGGGGGGGGGGGGGGGGGGGGGGGGGGGGGKKKKKGGGGGGGggK
..KBBbKHBBBBBBBBBBBBBBbbKggGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGgggK
...KBBbKHBBBBBBBBBBBBBbbKggGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGggK.
...KBBbKHBBBBBBBBBBBBBbbKgggGGGGGGGGGGGGggggGGGGGGGGGGGGGGGGGGGGGGggK.
...KBBbKHBBBBBBBBBBBBBbbKgggggGGGGGGGGggggggggGGGGGGGGGGGGGGGGGGGggKK.
...KBBbKHBBBBBBBBBBBBBbbKggggggGGGGGgggggggggggGGGGGGGGGGGGGGGGGgggK..
...KBBbKHBBBBBBBBBBBBbbKKggggggggggggggggggggggggGGGGGGGGGGGGGggggKK..
....KBBbKHBBBBBBBBBBBbKKKgggggggggggggggKKKKgggggggGGGGGGGGGGgggggK...
....KBBbKHBBBBBBBBBBbKKKKKggggggggggggKKK..KKKgggggggGGGGGGggggggK....
....KBBbKHBBBBBBBBKKK....KKKggggggggKKK......KKgggggggggggggggggKK....
....KBBbKHBBBBBBKKK........KKgggggKKK..........KKgggggggggggggKKK.....
....KKBbKHBBBKKKK............KKKKKK..............KKggggggggggKK.......
.....KBbKHKKKK....................................KKKggggggKKK........
......KKKKK..........................................KKKKKKK..........
```

### 1.5 The room-scale starting point, 56 × 38 (automatic 4/5 downsample; needs a full hand cleanup)

At room scale the worm is authored at 56 × 38 cells (§2). A reader measured what survives at that size:
- the glasses' black / grey / black frame;
- a 3×3 pupil and a 3–4-cell highlight;
- the left pupil sliver;
- the 2-column spine plus its highlight column;
- brows 1–2 rows thick.

At 48 cells or narrower the left lens collapses into a black blob, so about 54 cells is the floor for this figure.

```
.................KKKKKKK................................
................KKGGGGGGKK..............................
.......KKKK...KKGGGGGGGGGKK.............................
.....KKKKKKKKKGGGGKKKKKKKKKK............................
....KKLLLLLKKGGGGKKLLLLLLKKKK...........................
...KLLDDDDDLKKGGKLDDDDDDDLLKKK..........................
...KDDDKKKKDDKGKLDKKKKKKKDDDLK..........................
...KDDKWWGGKDKKKDDKWGGGGKKDDKKK.........................
...KDDKWGGGKDLLKDKWWGGGGGGKDDKKKKK......................
....KDKGGGKKDDDKDKWGGKKGGGKDDKLLLLK.....................
....KDKGGGKKDKKKDKGGKKKKGGKDDKKKDDLK....................
....KDKGGGGKDKGKDKGGKKKKGGKDDKKKKDDKK...................
.....KDKGGGKDKGKDKGGGKKGGGKDDK...KDDK...................
.....KKDLLKDKGGKDLKGGGGGGKDDKK...KKK....................
......KKKKKKKGGGKDDKKKKKKDDDK...........................
.......KKKK..KgggKKLLLLLDDKKK...........................
......KKK.....KKggKKKKKKKKKgK...........................
....KKCCK......KKKgGGGGGGGggK...........................
...KKCPPK....KKKKKgGGGGGGggK............................
..KCCCCPKK.KKKHBbKGGGGGGGggK.....KKK....................
.KCCCPPPKKKKHHBBbKGGGGGGGGgK...KKKGGKKK.................
KKCCPPKKHHHBBBBBbKGGGGGGGGGKKKKKGGGGGGKK................
KBKKKKHHBBBBBBBBbbKGGGGGGGGGGGGGGGGGGGGK................
KKBbKHBBBBBBBBBBBbKGGGGGGGGGGGGGGGGGGGGGK..........KKK..
KKBbKBBBBBBBBBBBBbKGGGGGGGGGGGGGGGGGGGGGKK........KKGGK.
.KBbKHBBBBBBBBBBBbKGGGGGGGGGGGGGGGGGGGGGGKK......KKGGGKK
.KBbKHBBBBBBBBBBBbKgGGGGGGGGGGGGGGGGGGGGGGK.....KKGGGGgK
.KBbKHBBBBBBBBBBBbKgGGGGGGGGGGGGGGGGGGGGGGKKK..KKGGGGGgK
.KBbKHBBBBBBBBBBBbKggGGGGGGGGGGGGGGGGGGGGGGGKKKGGGGGGggK
..KBbKHBBBBBBBBBBbKggGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGgKK
..KBbKHBBBBBBBBBBbKgggGGGGGGGGGGgggGGGGGGGGGGGGGGGGGggK.
..KBbKHBBBBBBBBBBbKgggggGGGGGGgggggggGGGGGGGGGGGGGGgggK.
..KBbKHBBBBBBBBBBbKggggggggggggggggggggGGGGGGGGGGGgggK..
..KKBbKBBBBBBBBBKKKKggggggggggKKKKKKKggggGGGGGGGGgggK...
..KKBbKBBBBBBBKKK..KKKggggggKKK.....KKgggggggggggggKK...
..KKBbKBBBBKKKK......KKKKKKKK.........KKggggggggggK.....
...KBbKKKKK............KKKK.............KKKgggggKK......
....KKKK..................................KKKKKK........
```

**Known defects for the cleanup:**
- the left lens's inner ring breaks at rows 9–12;
- the right pupil touches the inner rim;
- the temple arm is a stub;
- there are doubled outline corners at rows 3, 22 and 33;
- the book's spine stripes lose their rhythm below row 31.

Fix all of them.

### 1.6 The five emotions: what differs

Every emotion keeps the same eyes (pupils and highlights), posture, book and tail. **No file has a mouth.** The only
differences are the **brows** (black strokes above the lenses) and, for worried, a **sweat drop**. Each file is a
separate AI render, so their bodies drift: whole-figure agreement after alignment is 75–86%. **Author every emotion as a
brow (and drop) overlay on the one base body; never trace each file's body.** Registration offsets from each emotion
grid to the base, as `base(r − dy, c − dx)`:

| Emotion | dy | dx |
|---|---|---|
| happy | 2 | −1 |
| mad | 1 | 0 |
| sad | 1 | −1 |
| tired | 0 | 0 |
| worried | 2 | −1 |

Overlay stamps on the **70 × 47 base**. Each is `(row, col, cells)`; a negative row is headroom above row 0, and `.`
leaves the base cell unchanged. Scale them to 56 × 38 by hand. Do not resample.

| Emotion | Shape | Stamps |
|---|---|---|
| happy | Two raised ∩ arcs, 8 cols × 4 rows. The crown is 2 rows thick, the legs 1 cell; the right arc's right leg is 1 row longer. | `(-2,11,"KKKK"),(-1,10,"KKKKKK"),(0,9,"KK....KK"),(1,9,"K......K"),(-2,30,"KKKK"),(-1,29,"KKKKKK"),(0,28,"KK....KK"),(1,28,"K......K"),(2,35,"K")` |
| mad | Two thick slanted bars in a V (inner ends low), a `K` outline around a `D` core. The left bar is 6 rows long and runs into the head beside the bridge. | `(-2,10,"KKK"),(-1,10,"KDDK"),(0,11,"KKDDK"),(1,13,"KKDDK"),(2,15,"KKDK"),(3,17,"KK"),(-2,33,"KKK"),(-1,32,"KDDK"),(0,30,"KDDKK"),(1,28,"KDKK")` |
| sad | "/ \" with the inner ends raised: black staircases 2 cells thick, floating above the head. | `(-2,19,"KK"),(-1,17,"KKKK"),(0,15,"KKKK"),(1,14,"KKK"),(-3,29,"KK"),(-2,29,"KKKK"),(-1,31,"KKKK"),(0,33,"KKK")` |
| tired | Low, flat, heavy brows. The left is a 2-row bar just above the left lens; the right droops toward its outer end. No lids in the source. | `(0,10,"KKKKKKK"),(1,8,"KKKKKKKK"),(-1,31,"KKKKK"),(0,34,"KKKK"),(1,37,"KK")` |
| worried | A "/" left brow (inner end raised) above the left lens and a 1-row furrow on the forehead, plus a 5×6 sweat drop right of the head above the temple arm (pointed top, a `W` cell at its left middle, `K` outline). | `(-2,18,"KK"),(-1,17,"KKK"),(0,15,"KKKK"),(1,14,"KKK"),(2,25,"KKKK"),(0,37,"..K.."),(1,37,".KSK."),(2,37,"KSSSK"),(3,37,"KWSSK"),(4,37,"KSSSK"),(5,37,".KKK.")` |

`bookworm_all_states.png` shows a more compact C-curl pose, about 42–50 cells per figure. Its brows and drop match the
individual files. **Use the individual files for the pose**; the sheet is only a cross-check of the expressions.

### 1.7 The 18 × 18 set: from the owner's `bookworm_menu_bar.png` (redraw it)

The owner drew the menu-bar worm himself. Measured on `ART/reference/bookworm_menu_bar.png`:
- **Grid.** Cells are about 38.9 × 39.1 px. The ink spans x 238–1015 and y 328–953, so the figure is **20 × 16 cells**.
  The fit is noisy: 6.8 % of sampled pixels disagree with their cell's majority, because the bridge and the temple arm
  are drawn thinner than one cell.
- **Two colours.** Near-black ≈ `#191616` (snap it to `K`) and lime ≈ `#ACEC62` (its own key `m`, §3.2; §11 Q14).
- **What it is.** A head and glasses only:
  - two round lenses ringed in `K` with lime interiors, each with a 3 × 3 plus-shaped `K` pupil;
  - a `K` bridge between the lenses and the head dome rising behind them (rows 0–3);
  - a temple arm running right from the right lens and hooking down;
  - an S-neck curling down and right to a tail tip.
- **What it is not.** No book, no grey `D`/`L` frame, no `W` specular, no `g` shadow.

The fitted grid (20 × 16; `m` is the lime; noisy, a cross-check only):

```
........KKKKKK......
.......KmmmmmmK.....
......KmmmmmmmmK....
..KKKKmmmmKKKKKK....
.KmmmmKmmKmmmmmK....
KmmmmmmmKmmmmmmmK...
KmmKKmmKKmmmKmmmK...
KmmKKmmmKmmKKKmmKKKK
KmmKKmmmKmmmKmmmK...
.KmmmmKmmKmmmmmK....
..KKKK.KmmKKKKK.....
........KmmmmK......
.........KmmmK......
.........KmmmmK.....
..........KmmmmK....
...........KKKK.....
```

**Fitting it to 18 × 18.**
- Shorten the temple arm to cols 16–17, with its hook at (8, 17) as (row, col).
- The figure sits on rows 0–15. Rows 16–17 are transparent in every tag: the stage dots use row 17, and the curious badge
  uses rows 11–17 at the right (§7.3).
- A hop or bob never lifts the figure off row 0. It is a 1-px squash of the neck (head and glasses down 1 px), then back.
- Redraw both pupils as the reference's 3 × 3 plus (the fit shows the left one as 2 × 3).
- Colours: `K` and `m`, plus each state's own mark (§3.7). Never downsample the room worm into this set.

The starting grid (18 × 18; redraw it by hand):

```
........KKKKKK....
.......KmmmmmmK...
......KmmmmmmmmK..
..KKKKmmmmKKKKKK..
.KmmmmKmmKmmmmmK..
KmmmmmmmKmmmmmmmK.
KmmKKmmKKmmmKmmmK.
KmmKKmmmKmmKKKmmKK
KmmKKmmmKmmmKmmmKK
.KmmmmKmmKmmmmmK..
..KKKK.KmmKKKKK...
........KmmmmK....
.........KmmmK....
.........KmmmmK...
..........KmmmmK..
...........KKKK...
..................
..................
```

**On a dark menu bar** (`#1E1E1E`) the `K` rings vanish. The lime lenses with their dark pupil holes and the lime neck
must still read as glasses and a worm (§3.7's gate).

The earlier candidate grid (a blue book at cols 0–5 and grey `L`/`D` rims) is withdrawn: it contradicts the owner's
design.

---

## §2. Grids and scales

### 2.1 One room lattice (P12 holds: one pixel scale per picture)

**One art pixel is one cell, and a cell is a whole number of points:**

```
RoomLattice.cell(s) = max(2, (3 · s).rounded())        // s = CicadaTheme.uiScale, 0.8…1.4 in 0.1 steps
```

- **The cell at uiScale 1 is 3 pt** (6 device pixels on Retina).
- The lattice is **160 cols × 64 rows**.
- At 1.0 the room is **480 × 192 pt**. Today's room is 450 × 140: 90 × 28 cells at 5 pt
  (`S/Views/Sleep/DeskScene.swift:47-49`, `:111-127`).

**Why it fits.** The Sleep page column is `SleepLayout.contentWidth = 760` and is not scaled
(`S/Views/Sleep/SleepView.swift:9-11`).
- It is applied as `.padding(spacingXL).frame(maxWidth: 760)` (`:269`). The room card adds `.padding(spacingLG)`,
  `.frame(maxWidth: .infinity)` and `.glassCard()` (`:705-707`).
- So the width the room gets is **760 − 2·24s − 2·16s = 760 − 80s** (spacings scale with `uiScale`).
- The zoom range is 0.8…1.4 (`S/Theme/CicadaTheme.swift:48-51`).

| uiScale | cell (pt) | room (pt) | width available | slack |
|---|---|---|---|---|
| 0.8 | 2 | 320 × 128 | 696 | 376 |
| 0.9 | 3 | 480 × 192 | 688 | 208 |
| 1.0 | 3 | 480 × 192 | 680 | 200 |
| 1.1 | 3 | 480 × 192 | 672 | 192 |
| 1.2 | 4 | 640 × 256 | 664 | 24 |
| 1.3 | 4 | 640 × 256 | 656 | 16 |
| 1.4 | 4 | 640 × 256 | 648 | **8** |

- **160 is the widest lattice that fits.** At 4 pt the hard maximum is ⌊648/4⌋ = 162 cols at 1.4. A wider room needs
  `SleepLayout.contentWidth` amended (R-Z6 / Z-P23). `T/SleepLayoutTests.swift:17-24` keeps passing. Only its call at
  `:20` (now `deskSceneLayout(uiScale:)`) and its doc comment's sum at `:15-16` change: at 1.4× it becomes
  640 + 44.8 + 67.2 = 752 pt.
- **Height.** R-A2 fixes the room's height per zoom step (`S/Views/Sleep/SleepView.swift:632-634`), so the card is
  52 pt taller at 1.0 than today. The page is a `ScrollView`, and about 280–330 pt of vertical room is left at 1.0 in
  the default 800-high window. 192 pt fits.

**Why 3, not 2 or 4, at 1.0.**
- At 2 pt the 56-cell worm is 112 pt wide, smaller than today's ~100 pt of ink by height, and the glasses' 1-cell rings
  turn to hairlines.
- At 4 pt a 160-col room is 640 wide at 1.0, which still fits, but a 160 × 64 room at 4 pt is 256 tall at 1.0, and the
  card would be ~40% taller than today.
- 3 pt keeps the worm as the hero (192 × 144 pt canvas) and the room close to today's footprint.

The lattice no longer derives from the worm's renderer. Today the cell is `snappedPointSize(120·s)/24`
(`S/Views/Sleep/DeskScene.swift:113-116`). From this PR, `RoomLattice.cell` is the one place `uiScale` becomes geometry.

### 2.2 The floor plan, in cells (bottom-leading origin; a layer's (x, y) is its canvas's bottom-left cell)

This is the single source of truth. Run B writes it to `ART/room-plan.json`, and Run C copies it into
`DeskScene.plan` with a test that the two agree (§7.6).

**`room-plan.json` shape** (Run B writes it with `json.encode`; key order is irrelevant):

```json
{"cols":160,"rows":64,"origin":"bottom-left",
 "layers":[{"prop":"backdrop","sheet":"room-backdrop","x":0,"y":0,"w":110,"h":64,"z":0}, …],
 "worm":{"x":36,"y":9,"w":64,"h":48},
 "pile":{"x":110,"y":0,"w":50,"h":52}}
```

- `layers` holds the eight rows of the table below with z, in z order. `prop` is `DeskProp.rawValue`.
- The Swift test compares `layers` with `DeskScene.plan` (`cellX` = `x`, `cellY` = `y`, `w`, `h`, `z`), `worm` with
  `DeskScene.wormCell` and `pile` with `DeskScene.pileCell`.

| Layer | Sheet | x | y | canvas w × h | z | Scene cells covered |
|---|---|---|---|---|---|---|
| backdrop (wall, floor) | `room-backdrop` | 0 | 0 | 110 × 64 | 0 | cols 0–109, rows 0–63 |
| weather pane | `room-weather` | 20 | 27 | 36 × 32 | 1 | cols 20–55, rows 27–58 (= the window's glass) |
| window frame | `room-window` | 18 | 23 | 40 × 38 | 2 | cols 18–57, rows 23–60 |
| plant | `room-plant` | 21 | 0 | 12 × 22 | 3 | cols 21–32, rows 0–21 (under the sill, never in front of glass) |
| lamp (floor lamp) | `room-lamp` | 0 | 0 | 18 × 50 | 4 | cols 0–17, rows 0–49 |
| fly (lit only) | `room-fly` | 0 | 32 | 20 × 26 | 5 | cols 0–19, rows 32–57 (left of the glass; the shade spans scene rows 38–49, so ≥ 8 rows above it) |
| bean bag | `room-beanbag` | 36 | 0 | 62 × 12 | 6 | cols 36–97, rows 0–11 |
| mug | `room-mug` | 100 | 0 | 8 × 9 | 7 | cols 100–107, rows 0–8 |
| **worm** (`WormStage`, above every prop) | `bookworm-<state>` | 36 | 9 | 64 × 48 | — | cols 36–99, rows 9–56 |
| **pile column** (`BookPileView`, never painted) | — | 110 | 0 | 50 × 52 | — | cols 110–159, rows 0–51 (150 × 156 pt at 1.0) |

**Invariants (tested in §7.6):**
- **Bounds.** Every layer lies inside 160 × 64. No prop ink, and no backdrop pixel, reaches col 110 or beyond (P10,
  DR-13: no paint behind the chart).
- **Draw order.** z is strictly ascending.
- **Baseline.** The worm's bottom canvas row (scene row 9) equals the bean bag's `seat` slice row.
- **Pane.** The pane's canvas equals the window's `glass` slice, at the same scene cells.
- **Fly.** The fly's ink stays outside the glass rect and the pile column in every frame.
- **Ruling 9.** The worm's union ink never covers a celestial pixel (§5.3).
- **Coordinates.** Aseprite canvas coordinates are top-left. A canvas pixel row `r` of a layer at `y` with height `h`
  sits at scene row `y + h − 1 − r`.

**Composition, read left to right:**
- a floor lamp with its shade at the top left;
- the window on the wall, with its upper-left pane (sun or moon) clear of the worm;
- the plant under the sill;
- the bean bag, with the worm sitting on it facing out, its book on its left and its head rising in front of the window's
  lower-right pane;
- the mug on the floor;
- then the real pile.

**Light comes from the upper left** (the window), matching the reference's shading. A 2-cell vertical wall-corner trim at
backdrop cols 108–109 ends the room cleanly before the pile column.

### 2.3 The worm canvas, room scale: 64 × 48 px

- **Figure.** 56 × 38 px with 4 px margins left and right and the figure's baseline on the bottom row (row 47,
  top-left coordinates). That leaves 10 rows of headroom (rows 0–9) for brows (3 rows), hops (+3) and the z's.
- **The z's** rise in the canvas's upper right (cols 40–63, rows 0–14), which is empty in the reference silhouette.
  §3.5 gives every glyph's path; all z ink stays inside that box on every frame (tested).
- **On the lattice** the canvas is 192 × 144 pt at 1.0. The figure is about 168 × 114 pt; today's worm ink is about
  100 × 120 pt (`S/Views/Sleep/DeskScene.swift:86-91`).
- **One frame size for every room-scale worm sheet** (tested), so the hotspot, gaze and placement never move with the
  mood (R-A2).

### 2.4 The small set: 18 × 18 px

- **Menu bar.** `spritePointSize = 18` (`S/MenuBarManager.swift:27`), so 1 pt per art pixel and 2 device px on Retina.
  Today's 24-cell grid lands at 0.75 pt per cell, i.e. 1.5 device px, which is uneven.
- **Small in-app sites.** The same set is used wherever a call site asks for under 48 pt: Home and Getting started at
  24 (`S/Views/Home/HomeSections.swift:166`, `S/Views/Home/GettingStartedCard.swift:314`), and the Contributors avatar
  (`S/Views/Contributors/ContributorsView.swift:335-339`).
- **Overlays stay code-drawn** on the same 18-cell lattice: the curious count badge and the five stage dots. This keeps
  G107 R2 (the frame already carries count and stage), and 99 per-count frames would not be viable.

### 2.5 Every call site's size (whole points per art pixel; G107 R3 kept: "multiples keep cells integer")

| Call site | Requested | Art set | Pixel scale k (pt/px) | Drawn size at 1.0 | Rule |
|---|---|---|---|---|---|
| Sleep room (`WormStage`, `S/Views/Sleep/StudyRoom.swift:113`) | lattice | room | `RoomLattice.cell(s)` | 192 × 144 | on the room lattice (P12) |
| Empty states (`S/Views/Common/EmptyStateView.swift:46`, `EmptyStateLayout.wormPointSize = 96` at `:113`) | 96 (height) | room | `max(1, round(96·s/48))` = 2 | 128 × 96 | nominal height |
| Intake panel (`S/Views/Intake/IntakePanel.swift:108,117`) | 48 | room | `max(1, round(48·s/48))` = 1 | 64 × 48 | nominal height |
| Home, Getting started | 24 | small | `max(1, round(24·s/18))` = 1 | 18 × 18 (2 at s ≥ 1.2: 36 × 36) | under 48 → small |
| Contributors avatar | static frame 0 | small | 1, then `.resizable()` to its circle | 22 × 22 clipped | as today |
| Menu bar | 18 | small | 1 | 18 × 18 | `spritePointSize` |

`EmptyStateViewTests.testTheBookwormStaysTheFocalPoint` (`T/EmptyStateViewTests.swift:19-29`) keeps passing:
`wormPointSize` stays 96 and now means the worm's height. The intake panel's worm grows 16 pt wider (64 × 48); Run C
checks its header row still fits (§9 C).

---

## §3. The asset catalog

### 3.1 Files

**Sources (`ART/`):**

| Path | What |
|---|---|
| `README.md` | Palette, grids, the plan, how to rebuild (the exact commands of §6.1), what is hand-drawn and where, and "never hand-edit `src/`" |
| `palette.json` | The one palette every script and test reads (§3.2) |
| `room-plan.json` | §2.2's table as data (shape in §2.2) |
| `room-motion.json` | Written by `build_weather.lua`: per weather tag and moving element, its (x, y) on every frame, plus the per-frame step and the wrap (§5.2); read by `verify.py` and `T/RoomSpriteTests.swift` |
| `reference/` | The owner's art (read-only) |
| `tracing/ref_70x47.aseprite`, `tracing/ref_56x38.aseprite` | Palette-locked tracing bases on a hidden layer; never exported |
| `parts/worm-parts.aseprite` | **Hand-drawn parts**, one tag per part variant (§3.4); seeded once by `seed_parts.lua`, then edited in the GUI under computer use |
| `parts/worm-small-parts.aseprite` | The 18 × 18 parts (seeded from §1.7's starting grid) |
| `parts/room-parts.aseprite` | Room parts: lamp, plant, mug, bean bag, frame, cloud and tree shapes, spine masks; each drawn on its sheet's canvas (§2.2, §3.3) |
| `lua/ase_helpers.lua` | §10.2's library, verbatim, plus §10.3's additions |
| `lua/test_helpers.lua` | Asserts for every helper (§10.3) |
| `lua/seed_parts.lua` | Creates the three part files with every §3.4 tag (seeded from `tracing/ref_56x38`, §1.6's stamps and §1.7's starting grid, or left empty to draw), **only if the file does not exist**: when `app.fs.isFile(path)` it prints `exists, not reseeded` and exits 0. After seeding, the part files are hand-edited sources and no script ever writes them |
| `lua/worm_scripts.lua` | The worm's frame scripts as data (§3.5–§3.7), one table per tag |
| `lua/build_worm.lua`, `lua/build_worm_small.lua`, `lua/build_room.lua`, `lua/build_weather.lua`, `lua/build_spines.lua` | Compose parts and scripts into `src/*.aseprite`, add tags and slices, and assert |
| `lua/dev_loop.lua` | §10.4 (headless only) |
| `tools/export_all.sh` | Build, then export, then verify, manifest and preview (§6.1) |
| `tools/verify.py` | §6.2 |
| `tools/manifest.py` | §6.3 |
| `tools/make_preview.py` | §6.4 |
| `src/*.aseprite` | **Build outputs** (layered, tagged, sliced); committed so the owner can open them; never hand-edited |
| `preview.html` | Generated by `make_preview.py` |
| `qa/` | Gitignored (add `ART/qa/.gitignore` containing `*` and `!.gitignore`): @6x/@8x PNGs, GIFs, contact sheets, `registry.json` (every tag's frames as part lists, offsets and ms, written by the builds) |

Every build script starts with `local ART = app.params.art or app.fs.joinPath(H.scriptDir(), '..')`, so it runs from
`export_all.sh` (which passes `art=`) and from `dev_loop.lua` (which does not).

**Exports (`RES/`, flat; `cicadaResources(ext:in:)` does not recurse, `S/Utilities/ResourceBundle.swift:67-69`):**
- `bookworm-awake`, `bookworm-reading`, `bookworm-sleeping`, `bookworm-digesting`, `bookworm-happy`, `bookworm-hungry`,
  `bookworm-error`, `bookworm-curious` (`.png` + `.json`)
- `bookworm-small` (`.png` + `.json`)
- `room-backdrop`, `room-window`, `room-weather`, `room-lamp`, `room-fly`, `room-beanbag`, `room-plant`, `room-mug`,
  `room-spines` (`.png` + `.json`)
- `sprites.manifest.json`

That is 18 sheets, 36 files and the manifest. Nothing goes in `Resources/art/`: `T/ArtAssetTests.swift:82-85` fails on
any png there without an art-manifest entry.

### 3.2 `palette.json`

**Shape.**

```json
{
  "version": "2026-10-01",
  "note": "One palette for every Cicada sprite. Keys are unique across the file. Binary alpha only.",
  "colors": [
    {"key": "K", "hex": "#090707", "group": "worm", "role": "worm.outline"},
    ...
  ]
}
```

**Rules.**
- **Keys.** Single characters, unique across the whole file. Legal keys are `A–Z`, `a–z`, `0–9` and the 25 characters
  `! # $ % & ( ) * + , - / : ; < = > ? @ [ ] ^ { } ~`: 87 in all, and the file holds at most 87 (tested). Never `.`,
  space or `_` (they mean transparent and erase in `H.stamp`), and never a quote, backslash, backtick or `|` (they break
  Lua strings, JSON or the README's tables). Run A's seed uses 27 keys; Run B's 40–55 fit in the remaining 60.
- **Hexes are unique across the file too**, so a pixel's RGB maps back to exactly one key and one role.
- **Roles.** `role` is a dotted name. Tests read the prefixes `celestial.` (sun, moon, star), `cloud.`, `book.`
  (`book.cover…`, `book.page…`), `worm.lid`, `worm.pupilError` and `fx.sweat` (§4.4, §5.3), so a colour in one of those
  roles is used for nothing else.

**Seed values (Run A owns the `worm`, `fx` and `book` groups; Run B appends `room`, `weather`, `spine` and `fly`):**

| Key | Group | Role | Hex |
|---|---|---|---|
| `K` | worm | `worm.outline` | `#090707` |
| `G` `g` | worm | `worm.body.light`, `worm.body.shadow` | `#9CC460` `#679144` |
| `D` `L` | worm | `worm.glasses.dark`, `worm.glasses.light` | `#4A4647` `#858182` |
| `W` | worm | `worm.white` (speculars, glints, the sweat highlight, the `?` core; nothing else) | `#FDFDFD` |
| `S` | fx | `fx.sweat` | `#5FC8FB` |
| `m` | worm | `worm.small.body` (the owner's menu-bar lime; the 18 × 18 set only, §1.7, §11 Q14) | `#ACEC62` |
| `B` `b` `H` | book | `book.cover1.mid/dark/light` | `#097FFD` `#0055B9` `#2890FD` |
| `C` `P` | book | `book.page.cream/grey` | `#FEF7EC` `#BCB8B4` |
| `1` `2` `3` | book | `book.cover2.mid/dark/light` (crimson) | `#B8433A` `#7E2620` `#D5675B` |
| `4` `5` `6` | book | `book.cover3.mid/dark/light` (ochre) | `#C98A2B` `#8F5A12` `#E3AE52` |
| `j` | worm | `worm.lid` (closed-eye curve, heavy lids; between `g` and `K`) | `#46672F` |
| `e` | worm | `worm.pupilError` (red pupils, the error mark) | `#E5484D` (today's `e`, `S/MenuBar/BookwormSprites.swift:20-33`) |
| `r` | worm | `worm.mouth` (open-mouth interior) | `#5A2230` |
| `Z` `Y` `X` | fx | `fx.z.bright/mid/pale` (sleep z fades) | `#8896FF` `#B3BBFF` `#DADFFF` |
| `q` `Q` | fx | `fx.sparkle/fx.sparkleCore` | `#FFCB57` `#FFF1B8` |

- Run B appends roughly 40–55 room, weather, spine and fly colours with roles.
- **Props use coloured dark outlines** (the darkest step of their own ramp), never `K`. Only the worm has the
  near-black outline, so the character pops. This is standard sprite-on-background practice and keeps the room behind
  him.
- **Wall.** A warm, mid-value neutral that reads behind both the green worm and the night window.

### 3.3 Sheet table (frame size is the canvas; every tag is `forward`, `repeat` 0; durations are per frame in ms)

**General rules for every tag:**
- **Key frame.** Frame 0 of every tag is its key frame. It carries every state mark (§4.4); it is what Reduce Motion
  shows, and what a legend thumbnail shows. The two transitions (`sleeping/intro`, `sleeping/outro`) are exempt: they
  are the falling asleep and the waking, they never play under Reduce Motion, and frame 0 is never held for them.
- **No ping-pong or reverse.** A ping-pong motion is written out as frames; the sheet's de-duplication makes repeats free.
- **Fixed caps** (tested, §7.6–§7.7; the tokens are in §7.3):
  - every frame is 40–4000 ms;
  - a looping tag totals 400 ms–30 s;
  - a beat totals ≤ 800 ms, and `perk` ≤ 400 ms;
  - a transition totals ≤ 1600 ms.
  - The caps apply to animated tags (≥ 2 frames). Every one-frame tag and every `room-spines` frame is authored at
    1000 ms and is exempt from the loop-total cap. `room-spines` tags are mask sets and are never played.
- **The hidden `ref` layer** holds only palette-locked pixels (`H.loadReference(…, pal)`), because `H.assertPalette`
  checks hidden cels too (verified).

| File | Canvas | Layers (back → front; hidden layers are never exported) | Tags (exact set) | Used by |
|---|---|---|---|---|
| `bookworm-awake` | 64×48 | `ref` (hidden), `book-back`, `body`, `book`, `face`, `brows`, `mouth`, `fx` | the 18 "common looks" (§4.1) | `.awake` (Sleep page before status; cold start) |
| `bookworm-reading` | 64×48 | same | the 18 common looks × covers: `<look>`, `<look>@2`, `<look>@3` (54 tags) | `.reading`; intake panel |
| `bookworm-happy` | 64×48 | same | the 18 common looks + `cheer.center` (19) | `.happy`; empty states |
| `bookworm-hungry` | 64×48 | same | the 18 common looks | `.hungry` |
| `bookworm-digesting` | 64×48 | same | `idle`, `expectant.center`, `eager`, `talk.center`, `gulp.center`, `shake.center`, `cheer.center` (7) | `.digesting` |
| `bookworm-sleeping` | 64×48 | same | `idle`, `talk.center`, `intro`, `outro` (4) | `.sleeping(stage:)`, all stages; the yawn and the stretch |
| `bookworm-error` | 64×48 | same | `idle` (1) | `.error` |
| `bookworm-curious` | 64×48 | same | `idle` (1) | `.curious` (totality; the Sleep page never shows it) |
| `bookworm-small` | 18×18 | `ref` (hidden), `body`, `book`, `face`, `fx` | `awake`, `sleeping`, `digesting`, `happy`, `curious`, `hungry`, `reading`, `error` (8) | menu bar; Home; Getting started; Contributors |
| `room-backdrop` | 110×64 | `wall`, `floor`, `trim`, `glow` | `dark`, `lit` (1 frame each) | always; `lit` iff `lampLit` |
| `room-window` | 40×38 | `frame`, `sill` | `idle` (1 frame) | always |
| `room-weather` | 36×32 | `sky`, `far`, `near`, `fx`, `glass` | `night`, `dawn`, `clear`, `fair`, `overcast`, `storm`, `curtains` | the pane; the legend thumbnails (frame 0) |
| `room-lamp` | 18×50 | `lamp`, `light` | `dark`, `lit` (1 frame each) | always |
| `room-fly` | 20×26 | `fly` | `buzz` | only while `lampLit` |
| `room-beanbag` | 62×12 | `bag` | `idle` (1 frame) | always |
| `room-plant` | 12×22 | `plant` | `idle` (1 frame) | always |
| `room-mug` | 8×9 | `mug` | `idle` (1 frame) | always |
| `room-spines` | 24×12 | `mask` | `chat`, `page`, `note`, `video`, `other` (3 frames each: body, light, shade masks) | `SpineButton` texture (§5.6) |

**Required slices** (created by the build scripts with `H.addSlice`; a single key on frame 0; bounds in canvas pixels,
top-left):

| Sheet | Slice | Meaning |
|---|---|---|
| every `bookworm-*` (room) | `ink` | union of opaque pixels over every frame of every tag in that sheet |
| every `bookworm-*` (room) | `eye` | the right lens's pupil centre of the `body.sit` + `eyes.center` composition, 2 × 2; the same rect on every room sheet (tested equal), so the sleeping sheet's closed eyes do not matter |
| every `bookworm-*` (room) | `lensL`, `lensR` | the left and right lens interiors (inside the inner `K` ring) of that same composition; the same rects on every room sheet (tested equal) |
| `bookworm-small` | `lensL`, `lensR` | the two lens interiors (inside the `K` rings) of the rest pose |
| `room-window` | `glass` | exactly the pane's canvas: `(2, 2, 36, 32)` |
| `room-beanbag` | `seat` | a 1-row rect, cols under the worm; its row maps to scene row 9 |
| `room-lamp` | `ink` | union of `dark` ∪ `lit` |
| `room-lamp` | `shade` | the smallest rect containing every pixel where `dark` and `lit` differ |
| `room-backdrop` | `glow` | the smallest rect containing every pixel where `dark` and `lit` differ |
| `room-fly` | `ink` | union over `buzz` |
| `room-plant`, `room-mug`, `room-beanbag` | `ink` | union |

### 3.4 The worm's parts (`parts/worm-parts.aseprite`; one tag per variant, each on the full 64 × 48 canvas)

**How hand corrections stay reproducible.** The build composes frames from these parts, so a hand correction made in the
GUI survives every rebuild. `seed_parts.lua` creates the file once (§3.1); after that only hand edits change it.

**Registration, not anchors.** Every variant is drawn at figure scale on the full 64 × 48 canvas, registered so that the
`body.sit` figure sits at cols 4–59, rows 10–47. Composing a frame is a paste of each part at (0, 0) plus that frame's
offset. There are no anchor slices.

| Family | Variants (tag names) | Notes |
|---|---|---|
| `body.*` | `sit` (the reference pose), `sit.in1` (torso hump +1 px), `sit.in2` (torso +1, head +1), `sit.tail1` (tail tip +1), `slump` (sleeping: head −2, body relaxed onto the bag), `slump.in1`, `slump.in2`, `crouch` (−1, 1 px wider), `stretch1`, `stretch2` (waking: +1, +2 tall, tail up) | Each body variant is **three tags**, `body.<v>/head`, `body.<v>/torso` and `body.<v>/tail`, so an offset applies per sub-part and breathing can lead with the torso and follow with the head one frame later (follow-through). Sub-parts overlap by ≥ 1 px at their seams, so a 1-px offset never opens a gap |
| `eyes.*` | `center`, `left`, `right` (pupils −2/+2 px in the right lens, −1/+1 in the left), `up`, `up.left`, `up.right`, `down.l0`…`down.l3` (reading: pupils 1–2 px down, stepping right along a line), `down.l0b`…`down.l3b`, `down.l0c`…`down.l3c` (the next two line rows), `half` (heavy lid: upper third of the lens interior `j`), `blink.half`, `closed` (a 1-px `j` curve "‿", no `W`), `happy` (^ ^ arcs in `K`, no `W`), `wide` (pupil +1 px, extra `W`), `error` (pupils in `e`, otherwise `center`), `error.left`, `error.right` | The glasses' frame never moves relative to the head; only lens interiors change |
| `brows.*` | `none` (reference), `happy`, `sad`, `tired`, `worried`, `mad`, `curious` (left `happy` arc + right `tired` bar), each also at `+1` (raised one row) | From §1.6; `mad` is authored but no shipped tag uses it (§11 Q3) |
| `mouth.*` | `none` (reference: no mouth), `talk1` (3×2 `r` opening just under the right lens's bottom rim), `talk2` (4×3), `chew1`, `chew2`, `gulpOpen` (5×4), `yawn` (6×5 oval), `smile` (1-px `K` curve), `mumble1`, `mumble2` (1–2 px, eyes-shut talk) | Hidden at rest, exactly as the reference |
| `book.*` | `closed` (the reference), `closed.low` (for `gulp` while reading: the book drops 3 px and moves to `book-back`, so the body's lower outline covers its bottom rows; nothing is cut by the canvas edge), `open` (lying open in front of the lower body on the lap: two pages with 1-px grey line marks, the cover showing as a 1-px rim and spine), `flip1`…`flip5` (the right page lifts, curls, stands over the spine, falls, lands), `close1`…`close3`, `down1`…`down3` (the finished book is lowered and tucked behind the body on the `book-back` layer, so the body occludes it inside the same sprite; never off the canvas), `up1`…`up3` (the next book rises from behind the body on `book-back`, then moves to `book` for `open1`/`open2`), `open1`, `open2` (the cover opening), `rest.sleep` (closed, lying against the body) | Cover colours by palette remap: cover1 = `B b H`, cover2 = `1 2 3`, cover3 = `4 5 6` (`H.recolor`, §10.3). Every swap frame keeps ≥ 20 `book.` px visible |
| `fx.*` | `z.s` (3×3), `z.m` (4×4), `z.l` (5×5), each in `Z`, `Y`, `X`; `sparkle1`…`sparkle4` (`q`/`Q` bursts, 3×3 to 7×7); `glint1`…`glint4` (a 2-px `W` glint crossing the right lens's top rim); `sweat.d1`…`sweat.d8` (forming 1 px → 2×2 → the 3×4 drop, sliding, dripping); `q.mark` (a 5×7 "?" in `K` with a `W` core); `paper` (a 3×3 page scrap) | |

### 3.5 The worm's idle loops (room scale)

**Notation.** `parts @ offsets, ms`. Offsets are whole pixels; `+` is up, `−` is down, `x` marks a horizontal shift.
**The base row never moves, except in a lift.** In every loop and transition the figure's lowest outline stays on canvas
row 47, so a `crouch`, `dip` or `squash` is a 1-px squash (the head and torso drop while the base widens), never a
translation off the canvas, and a `head −1` moves the head down inside the figure. Only the beats `perk.*`, `eager` and
`cheer.center` lift: a `+n` frame translates the whole figure, book included, up n px (n ≤ 3), so its base row is
47 − n. A lift is always preceded by a crouch frame, and `eager` and `cheer.center` land on a squash frame on row 47.

Unlisted families are the state's rest face:

| State | Brows | Eyes | Book | Mouth |
|---|---|---|---|---|
| awake | `none` | `center` | `closed` | `none` |
| reading | `none` | `down.*` | `open` (cover k) | `none` |
| happy | `happy` | `center` | `closed` | `none` |
| hungry | `tired` | `half` | `closed` | `none` |
| digesting | `happy` | `happy` | `closed` | `chew*` |
| sleeping | `none` | `closed` | `rest.sleep` | `none` |
| error | `worried` | `error` | `closed` | `none` |
| curious | `curious` | `center` | `closed` | `none` |

**`awake/idle`.** 34 frames, 13,200 ms: three breaths, and blinks starting at 3,040, 6,830 (a double blink) and
8,700 ms, so the gaps between them are uneven (3.8, 1.9 and 7.5 s; BRIEF `:82` asks for "random blink").

| # | Frame | ms |
|---|---|---|
| 1 | `sit` | 700 |
| 2 | `sit.in1` | 180 |
| 3 | `sit.in2` | 220 |
| 4 | hold `sit.in2` | 600 |
| 5 | exhale: torso 0, head +1 | 180 |
| 6 | `sit` | 260 |
| 7 | `sit` | 900 |
| 8 | `blink.half` | 60 |
| 9 | `closed` | 90 |
| 10 | `blink.half` | 60 |
| 11 | `sit` | 500 |
| 12 | `sit.in1` | 180 |
| 13 | `sit.in2` | 220 |
| 14 | hold | 700 |
| 15 | exhale (as frame 5) | 180 |
| 16 | `sit` | 260 |
| 17 | `sit` | 600 |
| 18 | `sit.tail1` | 120 |
| 19 | `sit.tail1` + tip back halfway (sub-pixel colour step) | 120 |
| 20 | `sit` | 700 |
| 21 | `closed` | 90 |
| 22 | `center` | 120 |
| 23 | `closed` (double blink) | 90 |
| 24 | `sit` | 1570 |
| 25 | `blink.half` | 60 |
| 26 | `closed` | 90 |
| 27 | `blink.half` | 60 |
| 28 | `sit` | 1400 |
| 29 | `sit.in1` | 180 |
| 30 | `sit.in2` | 220 |
| 31 | hold `sit.in2` | 600 |
| 32 | exhale (as frame 5) | 180 |
| 33 | `sit` | 260 |
| 34 | `sit` | 1450 |

**`happy/idle`.** 27 frames, 7,170 ms. The `awake` breath with `happy` brows, a glint crossing the right lens, two
blinks at uneven gaps (starting at 2,340 and 3,720 ms: gaps of 1.4 and 5.8 s) and a head sway before the last rest.
The table is exact.

| Frames | Content | ms |
|---|---|---|
| 1–6 | rest and breath | 700, 180, 220, 600, 180, 260 |
| 7 | rest | 200 |
| 8–10 | blink (`blink.half`, `closed`, `blink.half`) | 60, 90, 60 |
| 11 | rest | 290 |
| 12–15 | `glint1`–`glint4` | 70 each |
| 16 | rest | 600 |
| 17–19 | blink | 60, 90, 60 |
| 20 | rest | 500 |
| 21–25 | breath | 180, 220, 700, 180, 260 |
| 26 | sway (head +1 px x) | 300 |
| 27 | rest | 900 |

**`hungry/idle` (tired).** 17 frames, 8,800 ms, slower: the worm nods off and jolts awake.

| # | Frame | ms |
|---|---|---|
| 1 | rest (`half`) | 900 |
| 2 | in1 | 260 |
| 3 | in2 | 300 |
| 4 | hold | 800 |
| 5 | out1 | 260 |
| 6 | out2 | 360 |
| 7 | rest | 700 |
| 8 | head −1 | 400 |
| 9 | head −1 + `closed` | 1200 |
| 10 | jolt: head 0, `half`, brows `tired+1` | 120 |
| 11 | rest | 800 |
| 12 | `closed` (slow blink) | 300 |
| 13 | rest | 600 |
| 14 | `yawn`-small (`talk1`) | 200 |
| 15 | `yawn` + `closed` + head +1 | 500 |
| 16 | `talk1` | 200 |
| 17 | rest | 900 |

**`error/idle` (worried, red pupils).** 13 frames, 2,400 ms. **No blink** (the red pupils are the tested mark), and a drop
is visible in every frame: frames 9–13 keep `sweat.d3`, so the seam back to frame 1 (`d3`) is continuous.

| # | Frame | ms |
|---|---|---|
| 1 | `sweat.d3` | 300 |
| 2 | `d4` | 150 |
| 3 | `d5` | 150 |
| 4 | `d6` | 150 |
| 5 | `d7` | 150 |
| 6 | `d8` + `d1` | 120 |
| 7 | `d2` | 200 |
| 8 | `d3` | 300 |
| 9 | tremble −1 x | 80 |
| 10 | +1 x | 80 |
| 11 | −1 x | 80 |
| 12 | rest | 300 |
| 13 | `error.left` (glance) | 340 |

**`curious/idle`.** 8 frames, 3,600 ms, with two blinks at uneven gaps (starting at 600 and 3,400 ms).

| # | Frame | ms |
|---|---|---|
| 1 | rest + `q.mark` | 600 |
| 2 | `closed` + `q.mark` | 90 |
| 3 | rest + `q.mark` | 210 |
| 4 | `q.mark` −1 y | 300 |
| 5 | tilt (head +1 x, +1 down) + `q.mark` −1 | 600 |
| 6 | tilt + `q.mark` | 300 |
| 7 | rest + `q.mark` | 1300 |
| 8 | `closed` + `q.mark` | 200 |

**`digesting/idle`.** 6 frames, 1,060 ms.

| # | Frame | ms |
|---|---|---|
| 1 | `chew1` | 140 |
| 2 | `chew2` + head −1 | 140 |
| 3 | `chew1` | 140 |
| 4 | `chew2` −1 | 140 |
| 5 | swallow (mouth `none`, a 1-px `g` bulge high on the neck) | 200 |
| 6 | `smile` | 300 |

**`sleeping/idle`.** 32 frames × 250 ms = 8,000 ms, two breaths and one z → zz → zzz cycle.
- **Breath (body offsets).** Frames 1–2 `slump`; 3–6 inhale (torso +1 from frame 4, head +1 from frame 5); 7–8 hold;
  9–12 exhale (head 0 at 10, torso 0 at 11); 13–16 `slump`. Frames 17–32 repeat it.
- **The z's.** Positions are each glyph's top-left (x, y) in canvas pixels; f is the frame number (1–32). Every glyph
  stays inside cols 40–63 × rows 0–14 on every frame (tested), clear of the figure, the brows and the drop.

  | Glyph | Frames | Position | Colour |
  |---|---|---|---|
  | "z": one `z.s` (3 × 3) | 1–10 | (40 + ⌊(f − 1)/2⌋, 12 − (f − 1)): from (40, 12) to (44, 3), rising 1 px per frame and drifting +1 px x every 2nd frame | `Z` 1–6, `Y` 7–8, `X` 9–10; gone from 11 |
  | "zz": `z.m` A (4 × 4) and `z.m` B | 9–20, with t = f − 9 | A = (43 + ⌊t/2⌋, 11 − ⌊t/2⌋), from (43, 11) to (48, 6); B = A + (5, −5), from (48, 6) to (53, 1) | `Z` 9–15, `Y` 16–18, `X` 19–20 |
  | "zzz": `z.s` S, `z.m` M, `z.l` L (5 × 5) | 19–32, with t = f − 19 | S = (42 + ⌊t/3⌋, 11); M = S + (4, −5), shown from t = 2; L = M + (5, −6), shown from t = 4; the group drifts +1 px x every 3rd frame and does not rise (the stack already fills the box), ending at S (46, 11), M (50, 6), L (55, 0) | `Z` 19–26, `Y` 27–29, `X` 30–32 |

  No two glyphs overlap on any frame: at frames 9–10 the "z" covers cols 44–46 × rows 3–6 while the "zz" covers
  cols 43–46 × rows 11–14 and cols 48–51 × rows 6–9; at frames 19–20 only the "zzz"'s S is up, at rows 11–13.
  `sleeping/talk.center`'s `z.s` puff sits at (40, 12).
- **Fading** is palette steps and shrinking, never alpha. Frame 1 (the key frame) shows a bright "z".

**`reading/idle` (cover 1), `idle@2` (cover 2), `idle@3` (cover 3).** 85 frames each, 21,840 ms each, identical
durations (tested). Each tag starts with its own cover open (the key frame) and **ends by picking up the NEXT cover**:
`idle` ends with cover 2 rising, `@2` with cover 3, `@3` with cover 1. That is why the app's cover cycle (§4.3) is seamless.

**Building blocks:**
- **One line, `L`.** `down.l0` 420 · `down.l1` 380 · `down.l2` 380 · `down.l3` 420 · line return (pupils back to
  `l0` one row lower, head bob −1) 140. That is 5 frames, 1,740 ms. Lines alternate rows `l*`, `l*b`, `l*c`.
- **A page flip, `F`.** `flip1` 90 · `flip2` 90 · `flip3` 100 · `flip4` 90 · `flip5` 120 · settle 200. That is
  6 frames, 690 ms; the pupils follow the page from right to left, then jump to the top of the right-hand page.
- **Closing, `C`.** `close1` 100 · `close2` 120 · `close3` 140.
- **The swap, `Sw`.** `down1` 140 · `down2` 140 · `down3` 140: the finished book is lowered and tucked behind the body
  on `book-back`, with the next book's top showing beside it in `down2`–`down3`; then `up1` 140 · `up2` 140 · `up3` 140:
  the next book rises from behind the body. That is 6 frames, 840 ms. Nothing leaves through the canvas bottom (the worm
  draws above the bean bag, so the bag can never hide it), and at least 20 `book.` pixels are visible in every frame.
- **Opening, `O`.** `open1` 140 · `open2` 160.
- **A blink, `Bk`.** `closed` 90 · `down.l0` 200.

**The script:** `L L L` · `Bk` · `F` · `L` · `Bk` · `L` · `F` · `L L L` · `F` · `L` · `Bk` · `L` · `C` · `Sw` · `O`.
That is 85 frames and 21,840 ms. Page flips come after 3, 2, 3 and 2 lines, never in lockstep (BRIEF §10). The blinks
start at 5,220, 7,940 and 18,310 ms, so the gaps are 2.7, 10.4 and 8.8 s.

**Covers by a cyclic remap.** `@2` is the cover-1 tag recoloured in one simultaneous pass with the cyclic map
{`B`→`1`, `b`→`2`, `H`→`3`, `1`→`4`, `2`→`5`, `3`→`6`, `4`→`B`, `5`→`b`, `6`→`H`}, and `@3` applies the map twice. A
one-way map would paint both books in the swap frames the same colour; the cycle turns "cover 1 down, cover 2 up" into
"cover 2 down, cover 3 up" and "cover 3 down, cover 1 up". `H.recolor` maps every pixel once from the original image, so
the cycle never chains (§10.3).

### 3.6 Poses and beats (room scale; generated per state from §3.4 parts)

**Rules for every pose and beat:**
- It uses the state's rest face, shifted as noted, and **keeps every state mark** (§4.4).
- `<g>` ∈ {`left`, `center`, `right`}. For left and right the head turns 1 px toward g and the pupils use `eyes.<g>`;
  for center, `eyes.center` (or `wide` where marked).
- For **reading** the book stays `open` in its cover, and the attentive eyes use `up.<g>` (the worm looks up from the page).
- For **hungry** the base eyes are `half`, and a blink lasts 160 ms instead of 80.

| Tag | Loop or once | Frames · ms | Total |
|---|---|---|---|
| `attentive.<g>` | loop | look 1400 · `blink.half` 50 · `closed` 80 · `blink.half` 50 · look 1250 · glance (pupils 1 px further toward g; center: 1 px up) 300 · look 300 · `blink.half` 50 · `closed` 80 · `blink.half` 50 · look 2300 (blinks start at 1,400 and 3,430 ms: gaps 2.0 and 3.9 s) | 5,910 ms (hungry 6,070) |
| `expectant.<g>` | loop | ready (`talk2`, brows +1, eyes g) 240 · dip (`crouch` −1) 140 · rise (back to the rest height, no lift) 140 · ready 200 | 720 ms |
| `eager` | loop | crouch −1 + `gulpOpen` + brows +1 100 · hop +2 120 · hop +1 100 · land: squash −1 140 | 460 ms |
| `perk.<g>` | once | crouch −1 60 · up +2, brows +1, `wide` 80 · +1 120 · 0 100 | 360 ms |
| `talk.<g>` | once | `talk1` 80 · `none` 70 · `talk2` + head +1 90 · `talk1` 70 · `talk2` + head +1 90 · `none` 100 | 500 ms |
| `gulp.center` | once | `gulpOpen` 90 · + `paper` at the mouth 90 · closing on it 80 · closed + bulge high 90 · bulge mid 90 · bulge low 90 · `smile` 120 (reading: `book.closed.low`, i.e. lowered but visible, in frames 1–6) | 650 ms |
| `shake.<g>` | once | `sad` brows on every frame; head −1 x 70 · +1 70 · −1 70 · +1 70 · rest 150 | 430 ms |
| `cheer.center` | once | crouch −1 100 · +2 & `sparkle1` & `happy` eyes 100 · +3 & `sparkle2` 120 · +2 & `sparkle3` 100 · 0 & `sparkle4` 100 · squash −1 80 · settle 120 | 720 ms |
| `sleeping/talk.center` | once | eyes `closed` throughout; `mumble1` 90 · `none` 90 · `mumble2` 90 · `none` 90 · `mumble1` + a `z.s` puff in `Y` 90 · `none` 90 | 540 ms |
| `sleeping/intro` (the yawn) | once | from `sit`: `half` + `book.close3` 140 (whatever the previous mood, the worm shuts its book; coming from reading this follows the open book) · `talk1` + `book.closed` 120 · `yawn` + head +1 260 · `yawn` 200 · `talk1` 120 · `closed` 120 · `slump`+1 120 · `slump`+1 & `rest.sleep` 120 · `slump` 120 · `slump` 100 | 1,420 ms |
| `sleeping/outro` (the stretch) | once | from `slump`: `stretch1` 120 · `stretch2` + `blink.half` 160 · `stretch2` + `talk1` 160 · `stretch2` + `yawn` 240 · `stretch1` + `half` 140 · `sit` + `blink.half` 100 · `sit` + `closed` 80 · `sit` + `center` 120 · `sit` 120 | 1,240 ms |

**Gaze variants share durations frame for frame** (tested), so a beat's length never depends on the gaze. Each
`<look>@k` of reading is the cover-1 tag recoloured with §3.5's cyclic map (`H.recolor`), with identical durations.

### 3.7 The small set (18 × 18; the owner's menu-bar design, §1.7)

Every tag is the owner's head, glasses and neck in `K` and `m` on rows 0–15, with rows 16–17 transparent (§1.7). A bob
or droop is a 1-px squash of the neck (head and glasses down 1 px), never a lift off row 0.

| Tag | Frames · ms | Notes |
|---|---|---|
| `awake` | rest 1800 · blink (each pupil a 1-row `K` lid line) 100 · rest 1400 · bob 300 · rest 600 | 4,200 ms |
| `sleeping` | z dot 2 × 2 at cols 16–17, rows 3–4, in `Z` 700 · rises 1 700 · rises 1, in `Y` 700 · breath (a 1-px bulge in the neck; the head stays still) 700 | both pupils are 1-row `K` lid lines in every frame: no plus pupil, ≥ 2 lid px per lens |
| `digesting` | chew1 250 · chew2 250 | the owner's design has no mouth: chewing is a 1-px bulge stepping down the neck |
| `happy` | rest 1600 · bob 160 · rest 160 · 1-px `q` sparkle 400 · rest 1200 | |
| `curious` | rest 1200 · brow up (a 1-px `K` brow on the dome over the right lens lifts 1 px) 300 · rest 900 · tilt 400 | **cols 9–17 × rows 11–17 carry no glasses ink** (the badge is drawn there; only the neck is) |
| `hungry` | rest (half lids: the top row of each lens interior is `K`) 2000 · closed 400 · rest 1600 · droop 800 | |
| `reading` | pupils left 600 · right 600 · page line moves 150 · left 600 | adds an open book (pages `C`/`P`, cover rim `B`/`b`) at cols 0–6, rows 11–15, below the left lens, which the owner's design leaves empty; ≥ 8 px whose role starts `book.` in every frame (§4.4) |
| `error` | rest 600 · tremble −1 x 100 · rest 400 · drop 1 px lower 400 | pupils in `e` and ≥ 1 `S` pixel (the drop) in every frame |

**Legibility gate** (record each look in the run's report):
- **Light bar:** every frame passes a person's look on `#F6F6F6`.
- **Dark bar:** on `#1E1E1E` the `K` rings vanish. The lime lenses with their dark pupil holes and the lime neck must
  still read as glasses and a worm.
- **No halo:** do not add one (§11 Q8).

---

## §4. State → tag, response → tag, precedence

### 4.1 Tag names are derived from the code, never typed twice

```
sheet(state, set)  = set == .small ? "bookworm-small" : "bookworm-\(state.caseName)"
tag(look)          = look.keySegment ?? "idle"                          // BookwormPose.swift:34-41, :90-95
tag(look, cover k) = k == 1 ? tag(look) : "\(tag(look))@\(k)"           // reading only, k ∈ 1…3
small tag(state)   = state.caseName                                      // BookwormState.swift:66-77
```

**The "18 common looks"** are exactly what `BookwormLook.reachable(for:)` (`S/MenuBar/BookwormPose.swift:99-111`) returns
for `.awake`, `.reading` and `.hungry`, in this order:

`idle`, `attentive.left`, `attentive.center`, `attentive.right`, `expectant.left`, `expectant.center`,
`expectant.right`, `eager`, `perk.left`, `perk.center`, `perk.right`, `talk.left`, `talk.center`, `talk.right`,
`gulp.center`, `shake.left`, `shake.center`, `shake.right`.

The rest of `reachable(for:)`:
- `.happy` adds `cheer.center` (19 tags).
- `.digesting` has 7, `.sleeping` 2, `.error` 1 and `.curious` 1.

That totals 84 (state, look) pairs. `requiredTags(for: state)` in Run C is `reachable(for: state).map(tag)`, plus the
`@2` and `@3` copies for reading and `intro`/`outro` for sleeping. A test asserts that each sheet's JSON tag set
**equals** it (§7.6, `T/BookwormSpriteTests.swift`).

**The matrix is unchanged** (`S/MenuBar/BookwormPose.swift:124-154`). No state gains or loses a response.

| State | gaze | drop poses | perk | talk | gulp | shake | cheer |
|---|---|---|---|---|---|---|---|
| awake, reading, hungry | Y | Y | Y | Y | Y | Y | – |
| happy | Y | Y | Y | Y | Y | Y | Y |
| digesting | – | Y (centre) | – | Y | Y | Y | Y |
| sleeping | – | – | – | Y (sleep-talk) | – | – | – |
| error, curious | – | – | – | – | – | – | – |

### 4.2 Which clip plays (precedence, highest first)

1. **Reduce Motion.** No beat and no transition plays. The pose is `pose.effective(for: state, reduceMotion: true)`,
   which folds `attentive` to `idle` but keeps `expectant(<gaze>)` (its gaze kept where the state accepts gaze,
   `.center` otherwise; pinned at `T/BookwormLookRendererTests.swift:105`) and `eager`, because the armed drop is a cue
   (`S/MenuBar/BookwormPose.swift:43-59`). That pose's tag is held on frame 0, cover 1 for reading. This keeps
   `BookwormView`'s rule that Reduce Motion holds frame 0 (`S/Views/Common/BookwormView.swift:47-48`) and the beat
   suppression at `:71-72`; `RoomModel.beatAllowed` already refuses beats (`S/Views/Sleep/RoomModel.swift:354-356`).
2. **A beat** (`room.reaction`) that `BookwormLook.beat(_:for:gaze:)` allows (`S/MenuBar/BookwormPose.swift:118-121`).
   It plays once and holds its last frame until `settleReaction` clears it.
3. **A transition** (`room.transition`, set only by `RoomModel.moodChanged`, §7.3): `sleeping/intro` once the mood has
   become `.sleeping`, or `sleeping/outro` once it has left `.sleeping` for `.digesting`, `.happy`, `.reading` or
   `.hungry` (never `.error`, whose marks must show at once, and never from or to `.awake`). It is **always drawn from
   `bookworm-sleeping`** (`BookwormArt.transitionClip`, §7.2), whatever the current state, because the outro plays after
   the mood has left `.sleeping`. It plays once and holds its last frame until cleared. A beat that starts clears it
   (`play` sets `transition = nil`), so a transition never resumes half-played behind a beat.
4. **The pose loop**: `pose.effective(for:reduceMotion:)` (`S/MenuBar/BookwormPose.swift:47-59`), chosen by
   `WormStage.pose` (`S/Views/Sleep/StudyRoom.swift:244-246`), unchanged.
5. **`idle`.**

**Missing art never crashes.** If a tag is missing, the fallback chain is `<look>@k` → `<look>` → `idle` → frame 0 of the
sheet. If the sheet is missing, the view draws nothing at the same frame size, so layout never moves, and logs once.
Tests make sure none of this happens in a shipped build.

### 4.3 The reading cover cycle (pure; tested)

```
T            = total of reading/idle (21,840 ms; every @k has the same total — tested)
coverIndex(t) = profile == .still ? 1 : 1 + (⌊(t − origin) / (T · slowdown)⌋ mod 3)
```

- **Origin.** `origin = SpriteClock.origin = Date(timeIntervalSinceReferenceDate: 0)`, today's `timelineOrigin`
  (`S/Views/Common/BookwormView.swift:41`), so two worms tick in step.
- **Loop position.** Within the cycle, the position is `(t − origin) mod (T · slowdown)` in the tag `idle@k`. Every
  reading pose and beat uses the same `k` at the time it is drawn.
- **Known edge.** A pose that spans a cover boundary (once every ~22 s) switches the book's colour while the worm looks
  at the pointer. That is accepted (§11 Q6).

### 4.4 State marks (R-Z1; "no response may hide a state mark"; frame 0 always carries them)

| State | Mark | How a test sees it |
|---|---|---|
| sleeping | eyes shut, and a z on the key frame | Every frame of `idle` and `talk.center` in `bookworm-sleeping` (the `intro` and `outro` transitions excepted) has ≥ 4 `j` px and 0 `W` px anywhere in the frame. `j` is used only for lids; `W` only for speculars, glints, the sweat highlight and the `?` core, and sleeping uses none of them. Frame 0 of `idle` has ≥ 3 `Z` px. In the small set, inside each of the `lensL`/`lensR` slices, every `sleeping` frame's `K` pixels lie in one row and number ≥ 2 (a lid line, never the plus pupil). |
| error | red pupils and the sweat drop | Every frame of `bookworm-error` has ≥ 4 `e` px and ≥ 1 `S` px. In the small set, every `error` frame has ≥ 1 `e` and ≥ 1 `S`. |
| reading | the book | Every frame of every `bookworm-reading` tag has ≥ 20 px whose colour role starts `book.`. Every frame of the small set's `reading` has ≥ 8. |
| every room state | the held book (R-Z1 as amended by ruling 18) | Every frame of every tag of every room `bookworm-*` sheet, transitions included, has ≥ 20 px whose role starts `book.`. |
| every state | the glasses | Every frame of every room tag has ≥ 30 `D` px and ≥ 6 `L` px (the glasses never leave). |
| happy, digesting, hungry, awake, curious | (no tested mark) | covered by the art review |

The room worm drops the **stage dots** and the **nightcap**. The stage is told by the stage strip, which shows only while
running (`docs/architecture/app.md:378-414`), by the sentence and by VoiceOver. The small set keeps the dots as a code
overlay. This is R-BW1 in §8.1.

### 4.5 Emotions → states (R-BW7; once, never random, never the clock)

| Reference emotion | Shown by | Why |
|---|---|---|
| base model (no brows) | `.awake`, `.reading` | neutral and focused |
| happy | `.happy`, `.digesting` (with chewing), `cheer` | caught up / a cycle just finished |
| tired | `.hungry` | overdue; G107: "hungry maps directly onto sleep-deprived" (`docs/goals/memory-evolution.md:686`) |
| worried (+ sweat drop) | `.error`, with red pupils kept as the second cue | BRIEF §10: "worry on an error" |
| sad | the `shake` beat (a drop the intake did not take: `FeedResult` ≠ `.handedOver`, `S/Views/Sleep/RoomModel.swift:168-171`) | |
| mad | authored as `brows.mad`; **no shipped tag uses it**. Run A writes `ART/demo/bookworm-mad-demo@6x.gif` (awake `idle` with `brows.mad`; committed, never bundled), and `preview.html` shows it under "Drawn, not yet used" so Q3 can be answered by eye | §11 Q3 |
| curious (left arc + right bar, from the happy and tired brows) | `.curious` | menu bar and Home |

---

## §5. The room: window weather, lamp, fly, backdrop, props, books

### 5.1 Weather → backdrop (R-Z11 kept as a total function of the mood; titles, motion and palette change)

`windowWeather(for:)` (`S/Views/Sleep/WindowWeather.swift:43-53`) is **unchanged**:

| Mood | Weather |
|---|---|
| sleeping | night |
| digesting | dawn |
| happy | clear |
| reading, curious | fair |
| hungry | overcast |
| error | storm |
| awake | curtains |

The enum cases and their raw values stay, because they are cache and tag keys. `meaning` strings stay. Only `title`
changes, to the owner's words:

| Case | Old title (`:17-27`) | New title | `meaning` (unchanged, `:29-39`) | Tag `room-weather/<case>` |
|---|---|---|---|---|
| `night` | Night | **Night** | A cycle is running. | moon + twinkling stars |
| `dawn` | Dawn | **Dawn** | A cycle just finished. | sunrise glow |
| `clear` | Clear | **Sunny** | Caught up. Nothing waiting. | sun + slow clouds |
| `fair` | Fair | **Partly cloudy** | Things are waiting to be read. | clouds at two speeds over a half-hidden sun |
| `overcast` | Overcast | **Windy** | Overdue: it's been a while. | grey sky, a swaying tree, blowing leaves |
| `storm` | Storm | **Rainy** | The last cycle failed. | rain streaks + drops on the glass, **no lightning, no flash** |
| `curtains` | Curtains drawn | **Curtains drawn** | Waiting to hear how Sleep is doing. | curtains closed, hems swaying |

The legend header stays `Copy.windowLegendHeader` = "The window shows how Sleep is doing, not the time of day."
(`S/Theme/Copy.swift:115`). Nothing in the window reads a clock (`T/WindowSpritesTests`, `T/WindowWeatherTests.swift:29-34`).

### 5.2 The seven loops (canvas 36 × 32 = the glass; frame 0 = key frame = legend thumbnail)

**Glass geometry.** The window's cross mullion is a vertical at glass x 17–18 and a transom at glass rows 15–16
(top-left). That leaves four panes. The **upper-left pane (glass x 0–16, rows 0–14) is always clear of the worm**, so
the sun and the moon live there.

| Tag | Frames × ms | Total | What moves (whole pixels; seamless at the loop seam) | Key frame (frame 0) must show |
|---|---|---|---|---|
| `night` | 24 × 200 | 4,800 | A deep-navy sky in 3 stepped bands and a static crescent moon in the upper-left pane. 8–10 stars, each on its own 4-step cycle (bright cross → bright dot → dim dot → bright dot), phases staggered so never more than 3 change on one frame. | moon + ≥ 4 bright stars |
| `dawn` | 36 × 300 | 10,800 | Stepped warm horizon bands (rose / peach / gold) and the sun's upper half at the horizon in the left half. Rays alternate between 2 poses every 3 frames. 2 thin clouds drift +1 px per frame and wrap once across 36 px (the cloud leaves the right edge and re-enters the left behind the jamb). | half sun + glow bands |
| `clear` (Sunny) | 36 × 500 | 18,000 | A blue sky in 3 bands, a full sun in the upper-left pane with rays rotating through 3 poses every 4 frames, 2 small white clouds drifting +1 px per frame (wrapping once), and a static far treeline along the bottom 4 rows. | full sun + 2 clouds |
| `fair` (Partly cloudy) | 72 × 200 | 14,400 | A lighter sky and the sun in the upper-left pane. A big near cloud moves +1 px per frame (2 wraps per loop) and two far clouds +1 px every 2 frames (1 wrap), so the sun is half-hidden part of the time. | sun partly behind a cloud |
| `overcast` (Windy) | 36 × 120 | 4,320 | Grey sky. Low cloud streaks move +1 px per frame (wrap once). A small tree in the lower-left pane (glass x 1–12, rows 18–31) leans through lean0 → lean1 → lean2 → lean1, each held 3 frames (3 sways per loop). 3 leaves blow +1 px x per frame, −1 px y every 3 frames, each on a periodic path that resets off-glass. | grey sky + leaning tree + ≥ 2 leaves |
| `storm` (Rainy) | 48 × 80 | 3,840 | Dark slate sky with heavy static clouds in the top 6 rows. Rain: 30+ 2-px diagonal streaks. A streak is the pixels (x, y) and (x − 1, y + 1); on frame i (0-based) it moves (−1, +4) when i mod 4 ≠ 3 and (0, +4) otherwise, with x wrapping mod 36 and y mod 32, so over the 48 frames x shifts −36 (one wrap) and y +192 (six wraps) and the loop is exact. Drops on the glass (`glass` layer): 4 drops, each forms (1 px), grows (2 px), then slides 1 px every 2 frames, period 48. **No lightning, no bolt, no brightness change on any frame** (tested: the mean Rec. 709 luminance of each frame's opaque pixels stays within 2 % of the tag's mean). | streaks + ≥ 2 glass drops |
| `curtains` | 8 frames | 3,600 | Two curtain panels with vertical folds closing the glass and a static 1-px light leak at the centre gap. The hems sway: hem0 600 · hem1 300 · hem2 600 · hem1 300 · hem0 600 · hem−1 300 · hem−2 600 · hem−1 300. | curtains closed |

**Seamless by construction.** Every moving element's position is an integer function of the frame number.
`build_weather.lua` writes each element's (x, y) on every frame, its per-frame step and its wrap to `ART/room-motion.json`,
and the tests check, for every element, that `pos[n − 1] + step ≡ pos[0]` modulo the wrap, exactly like any other step.

**Magnitude never scales the art** (R-Z3). Rain is the same however many cycles failed, and wind is the same however
overdue.

### 5.3 Ruling 9, per frame (the test Run B self-checks and Run C ships)

**Masks.**
- **The worm mask** for a weather is the union, in scene cells, of every opaque pixel of every frame of every reachable
  tag (all covers) of every page mood that maps to that weather: `.awake`, `.happy`, `.reading`, `.hungry`,
  `.digesting`, `.error` and `.sleeping`, never `.curious` (as `T/WindowSpritesTests.swift:29` does today). Add
  `bookworm-sleeping/intro` for `night`, and `bookworm-sleeping/outro` for `dawn`, `clear`, `fair` and `overcast` (the
  moods a stretch can end in, §4.2). Everything is placed at worm (36, 9).
- **The frame mask** is the opaque pixels of `room-window/idle` at (18, 23).

**Rules, for every frame of the weather's tag at pane (20, 27):**
- Every pixel whose palette role starts `celestial.` is 100% visible: it lies under neither mask.
- At least 50% of pixels whose role starts `cloud.` are visible.

This replaces `T/WindowSpritesTests.swift:28-42,81-93` (TODO ruling 9, `docs/goals/TODO.md:583-586`: "Any new art near
the worm gets the same test").

### 5.4 Lamp and fly (R-A3 and P11 kept: lit iff `ScheduleConfig.mode != manual`; the art never previews)

**The lamp.**
- **Input.** Lit is still `SleepPageModel.lampLit = schedule.enabled` (`S/Views/Sleep/SleepPageModel.swift:157`).
- **Drawing.** A floor lamp: a weighted round base about 10 px wide, a 1–2 px pole, and a cone shade at rows 0–11 tilted
  toward the room.
  - `dark`: steel shade, dark bulb.
  - `lit`: a warm shade interior, a bulb in a bright warm white, and 1-px warm rim light on the shade edges.
- **Static.** No flicker, no shimmer.
- **Twin.** The whisper line and the lamp popover are unchanged (`S/Views/Sleep/StudyRoom.swift:121-137`,
  `S/Views/Sleep/LampPopover.swift:41-121`).

**The backdrop.** `lit` adds the light: a stepped warm pool on the wall around the shade (3 rings) and a floor pool under
the lamp. `dark` and `lit` differ only inside the `glow` slice (tested).

**The fly (`room-fly/buzz`).** 40 frames, about 4.5 s.

| Frames | Content | ms |
|---|---|---|
| 1 | landed on top of the shade (the key frame, and the Reduce Motion pose) | 1200 |
| 2 | takeoff +1 px | 80 |
| 3–30 | flight around the shade, 1 px per frame on an irregular path (a loop around the shade, a dart, a figure-8); the wing glint shows as a second light pixel on even frames | 60–90 each |
| 31 | lands on the rim | 600 |
| 32–39 | short hops around the bulb | 70 each |
| 40 | approach back to the rest spot | 120 |

- **Behind the shade.** When the fly passes behind the shade, draw no fly pixel.
- **Colours.** Body in `fly.body` (a near-black distinct from `K`), glint in `fly.wing`.
- **Placement.** Inert, with no hotspot of its own: the lamp's hotspot and twin cover it. Its ink never enters the
  glass rect or the pile column (tested). It is drawn only while `lampLit`.
- **"Pixel size almost"** (the owner): one pixel, a second on wing-glint frames. Tested: every `room-fly` frame has 0–2
  opaque pixels (0 only behind the shade), and frame 0 has ≥ 1.
- **Room to fly.** The canvas covers scene rows 32–57 (§2.2) and the shade scene rows 38–49, so the path has ≥ 8 rows
  above the shade and the rest of the canvas around it. The path is a data table of (x, y, ms, glint) in
  `build_room.lua` (Run B step 4).

### 5.5 Props and backdrop (static, one frame)

- **Wall (110 × 64).** Low-contrast texture: an ordered 1-px stripe or plaster pattern. No random noise and no dither
  fades; the round-1 dithers "read as noise" (§10.5). The wall is 1–2 steps lighter in a broad band near the window
  (one light direction).
- **Floor.** Planks in scene rows 0–7 (backdrop canvas rows 56–63) with 1-px seams, and a 2-px baseboard at scene rows
  8–9 (canvas rows 54–55) with a 1-px bevel on its top edge.
- **Lived-in details** (static and inert, in the backdrop sheet; BRIEF `:158` asked for them):
  - a rug under the bean bag, scene rows 0–2, cols 34–100 (mostly hidden by the bag; its ends show);
  - the lamp's 1-px cord from its base along the floor to a wall outlet on the baseboard, cols 2–12.
  - Nothing that reads as a clock or a book. Keep the wall behind the z's (scene cols 76–99, rows 42–56) plain, so the
    z's read.
- **Wall-corner trim.** Cols 108–109.
- **The bean bag (62 × 12).** Soft fabric in 3–4 shades with a dent where the worm sits. The `seat` slice row maps to
  scene row 9; the bag's edges may puff 1–2 rows above it, beside the worm.
- **The plant (12 × 22).** A terracotta pot with leaves, under the sill, never in front of the glass ("Nothing thin
  stands in front of a PANE", `S/Views/Sleep/DeskScene.swift:61-68`).
- **The mug (8 × 9).** No steam.
- **The window frame (40 × 38).** Wood, a 2-px border, the cross mullion, and a sill at the bottom 4 rows, protruding
  full width. The glass is transparent in this sheet.
- **R-Z2 holds.** The plant, mug, bean bag, wall, rug, cord, window scenery and the fly never react, not even to hover
  (`T/SleepMeadowTests.swift:62-69`).

### 5.6 Books

**Reading covers.** Three covers (§3.2 palette), the worm's own book (R-BW9): cover 1 is the owner's blue, cover 2
crimson, cover 3 ochre. They appear only in the worm's reading tags.

**No decorative stack.** P10 holds (`docs/goals/memory-evolution.md:703`; `S/Views/Sleep/DeskSceneSprites.swift:3-9`).
No finished-books pile is drawn, because no real count drives one in this PR. The bookcase and cart are the out-of-scope
"queue as a room".

**Spine textures for the real pile.** `room-spines` has 5 kinds × 3 masks (body, light, shade), each 24 × 12 px with
binary alpha and a single colour.

| Mask | What it is |
|---|---|
| **body** | the spine silhouette: 1-px stepped corners at the left end only; the right end is square, because the mark lives there |
| **light** | 1-px top edge and 1-px highlight column on the left end, plus the kind mark's light pixels |
| **shade** | 1-px bottom edge, plus the kind mark's shade pixels |

**Built to be drawn at any spine size without smearing** (§7.4):
- In every mask, columns 0–19 are constant along rows 1–10, and columns 4–19 are identical to each other, so the left
  20 columns can be stretched both ways and stay crisp.
- The kind mark is light and shade pixels in the right 4 columns, rows 1–10 only. Each kind must still read when cropped
  to its middle 3 rows: rows 4–6 of the right 4 columns of light ∪ shade differ for every pair of kinds (tested).

**The kind mark sits in the RIGHT 4 px only.** The label (`OriginMark` and the count) is leading-aligned at
`spacingXS` (`S/Views/Sleep/BookPile.swift:322-332`) and must sit on plain colour: DR-50, "Text never sits directly on
paint".

| Kind | Right-end mark | Origins (`OriginIconography.allKnownOrigins`, `S/Views/Capture/OriginIconography.swift:31-55`) |
|---|---|---|
| `chat` | two 1-px gilt bands (light mask) | mcp, claude-code, claude-desktop, cursor, codex, gemini-cli, claude-export, chatgpt-export, gemini-export, claude-web, chatgpt, perplexity, claude-code-remote, codex-remote, vscode, remote-app, grok, opencode, hermes, openclaw, telegram |
| `page` | a ragged paper edge (alternating 1-px light pixels down the last column) + a tie line | chrome-bookmark, safari-bookmark, safari-tab, bookmark, saved-link, share-sheet, brave-bookmark, vivaldi-bookmark, comet-bookmark, dia-bookmark, chrome-tab-group, rss, instagram-saved, pinterest, reddit-saved, reddit, x-bookmarks, x, linkedin-saved |
| `note` | a dotted spiral column | apple-notes, wispr-flow, folder |
| `video` | a 2-px cassette window with two hub dots | youtube-playlist, tiktok-saved, tiktok-history |
| `other` | a plain title plate outline | calendar, calendar-local, contacts-local, unknown, every unlisted origin, and the `+more` remainder spine |

The kind is a function of the origin, which is already encoded by colour and mark, so the texture is a redundant second
cue ("hue is never the only signal", G176). It adds no fact and changes no `fitPile` number.

---

## §6. Export, manifest, preview, verification

### 6.1 `ART/tools/export_all.sh` (the only way sheets are made; reproducible)

```bash
#!/bin/bash
# Rebuild Cicada's sprites from parts + scripts, export the sheets the app loads, verify, and (STAGE=all) write the
# manifest and the preview. Run from anywhere. Exit non-zero on any failure.
#   Run A:  BUILDS="build_worm build_worm_small" STAGE=worm tools/export_all.sh
#   Run B+: tools/export_all.sh            (every build, STAGE=all)
set -euo pipefail
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"   # measured: "Aseprite 1.3.18.6-dev"
BUILDS="${BUILDS:-build_worm build_worm_small build_room build_weather build_spines}"
STAGE="${STAGE:-all}"                                                   # all | worm
ART="$(cd "$(dirname "$0")/.." && pwd)"
RES="$(cd "$ART/../../../Sources/CicadaApp/Resources" && pwd)/sprites"
mkdir -p "$RES" "$ART/src" "$ART/qa"
for build in $BUILDS; do
  # --script-param MUST precede --script (params after it are dropped — verified)
  "$ASE" -b --script-param art="$ART" --script "$ART/lua/$build.lua"
done
for src in "$ART"/src/*.aseprite; do
  name="$(basename "$src" .aseprite)"
  rm -f "$RES/$name.png" "$RES/$name.json"
  # Full sheet, never --tag (meta.frameTags would keep whole-sprite indices) and never --split-tags (broken) — verified.
  "$ASE" -b "$src" --sheet "$RES/$name.png" --data "$RES/$name.json" \
         --format json-array --sheet-pack --list-tags --list-slices
  # A missing input exits 0 and prints "File not found" (verified), so check the outputs.
  [[ -s "$RES/$name.png" && -s "$RES/$name.json" ]] || { echo "export failed: $name" >&2; exit 1; }
done
if [[ "$STAGE" == "all" ]]; then
  python3 "$ART/tools/verify.py"          # §6.2 (python3 has Pillow 12.3.0 here — measured)
  python3 "$ART/tools/manifest.py"        # §6.3
  python3 "$ART/tools/make_preview.py"    # §6.4
else
  python3 "$ART/tools/verify.py" --worm-only   # skips the room, ruling-9 and fly checks (no room sheets yet)
fi
echo "sprites: OK ($STAGE)"
```

**Conventions** (each verified against this build unless marked):
- **Format.** RGB sprites export `RGBA8888` PNGs. Use no `--trim`: it collapses frames that differ only by position.
  `--sheet-pack` always de-duplicates identical frames, so several `frames[]` entries share one rect, and the player
  indexes rects by frame position.
- **Durations.** Integer ms in `frames[].duration`. They are set in Lua as `(ms + 0.5) / 1000` (`H.setDuration`):
  plain `ms/1000` loses 1 ms on 48 values between 1001 and 4095.
- **Tags.** Created after all frames: appending a frame after a tag that ends on the last frame grows that tag.
- **Alpha.** Binary alpha only.
- **No machine paths.** No absolute path appears in any JSON: `meta.image` is the basename, and `frames[].filename` is
  `"<sprite title> <n>.aseprite"`. Never put a path in the sprite title (tested: no `/Users/` or `/private/`).
- **Determinism.** `verify.py` exports every source a second time into a temp directory and compares bytes. If the
  bytes differ, the run fails and the cause is fixed before any sha256 is recorded.
- **Side effect.** Each headless `app.open`/save writes `~/Library/Application Support/Aseprite/files/<mangled>.ini`.
  It is harmless; leave it.

### 6.2 `ART/tools/verify.py` (Pillow; fails loudly)

`--worm-only` (Run A) checks only the `bookworm-*` sheets and skips every room, ruling-9, fly and weather check. For
every `RES/*.json` + `.png` in scope:
1. **Size.** The PNG size equals `meta.size`, and every `frames[].frame` lies inside it. All frames of a sheet share one
   `sourceSize`, equal to the §3.3 canvas.
2. **Tags.** The tag set equals the registry in `ART/lua/worm_scripts.lua` and §3.3 (exported by the build as
   `ART/qa/registry.json`). Every tag is `forward`, with `from ≤ to`.
3. **Durations.** Inside §3.3's caps (animated tags only; one-frame tags and `room-spines` are 1000 ms per frame). Each
   reading `@k` matches its cover-1 tag frame for frame. Each gaze family (`.left/.center/.right`) matches frame for
   frame.
4. **Pixels.** Every pixel is alpha 0 or alpha 255, and every opaque pixel's RGB is in `palette.json`. No palette hex is
   a reserved state hex (§1.3).
5. **Slices.** Every §3.3 slice exists, and `ink` equals the recomputed union of opaque pixels.
6. **Marks and geometry.**
   - §4.4's marks hold, the book row included.
   - **Blinks are irregular.** A blink frame is one whose `W` count is at least 2 lower than its tag's frame 0; a blink
     is a maximal run of blink frames. In `idle` of `bookworm-awake`, `-happy`, `-curious` and every reading cover, and
     in `attentive.*` of `bookworm-awake`, `-happy` and `-reading`: ≥ 3 runs in awake and reading `idle`, ≥ 2 in the
     others, and the cyclic gaps between run starts have max/min ≥ 1.6. (`hungry` is exempt: its heavy lids may hide the
     speculars on every frame.)
   - **The z's stay in their box.** Every `Z`, `Y` and `X` pixel of every room worm frame lies inside canvas cols 40–63 ×
     rows 0–14.
   - **The eyes track lines.** Using `qa/registry.json` to find them, in each reading line (`down.l0`…`down.l3`, and the
     `b`/`c` rows) the x of the centroid of the `K` pixels inside `lensR` never decreases.
   - **Lifts.** Outside `perk.*`, `eager` and `cheer.center`, the lowest opaque row of every room worm frame is 47; in
     those beats it is 44–47.
   - §5.3's ruling-9 check holds.
   - The fly's ink stays out of the glass and out of cols ≥ 110 (after placement); every fly frame has 0–2 opaque px
     and frame 0 has ≥ 1.
   - The `storm` tag's per-frame mean luminance stays within 2 % of its mean.
   - Every element in `ART/room-motion.json` steps from its last frame to its first like any other step (§5.2).
   - Backdrop `dark`/`lit` and lamp `dark`/`lit` differ only inside `glow`/`shade`.
   - The bean bag's `seat` row maps to scene row 9.
   - Every layer of `ART/room-plan.json` stays inside 160 × 64, and nothing reaches col 110.
7. **QA renders.** For every tag of every sheet, write `ART/qa/<sheet>/<tag>@6x.gif` (and `@8x` for the 18 × 18 set)
   with `aseprite -b <src> --tag <tag> --scale 6 --save-as …`. GIF export ignores direction, which is fine because all
   tags are forward, and its delays are centiseconds. Also write a contact sheet `ART/qa/<sheet>-contact@6x.png`, and
   `ART/qa/menubar-{light,dark}@8x.png` showing all 8 small tags' frame 0 on `#F6F6F6` and `#1E1E1E`.
   - Check each GIF's frames against the sheet's frames, upscaled with Pillow `NEAREST`.
   - Read GIF durations inside a `gif.seek(k)` loop: `ImageSequence.Iterator` reports stale `info['duration']`
     (verified gotcha).

### 6.3 `RES/sprites.manifest.json` (mirrors `Resources/art/art.manifest.json`'s provenance; one entry per sheet)

Written by `tools/manifest.py` as `json.dumps(d, indent=1, ensure_ascii=False) + "\n"`, the art manifest's exact
serialization.

```json
{
 "note": "Cicada's sprite sheets (G176, TODO ruling 18). Regenerating a sheet means a new entry in the same commit. Sources and scripts: app/CicadaApp/Art/sprites/bookworm-2026-10-01/.",
 "assets": [
  {
   "id": "bookworm-awake",
   "png": "bookworm-awake.png",
   "json": "bookworm-awake.json",
   "role": "worm",
   "generator": "Aseprite 1.3.18.6-dev, headless (-b), from Lua",
   "script": "lua/build_worm.lua",
   "source": "src/bookworm-awake.aseprite",
   "reference": "reference/bookworm.png b73184a49473e8b377756a0b9c31f3aae2f75db0e1eed639df3abc248cd43049",
   "authoring": "Codex CLI 0.159.3 (gpt-6.1-sol, extra-high effort) with computer use in Aseprite, from the owner's reference",
   "date": "2026-10-01",
   "licence": "MIT, as this repository (see LICENSE). Own work for Cicada, drawn from the owner's reference; no third-party artwork or brand marks.",
   "processing": "export_all.sh: --sheet-pack --format json-array --list-tags --list-slices; no trim; RGBA8888; binary alpha; palette-locked to palette.json",
   "pngSha256": "<64 lowercase hex>",
   "jsonSha256": "<64 lowercase hex>"
  }
 ]
}
```

- **Roles.** `worm`, `worm-small`, `room`, `weather`, `fly`, `spines`.
- **References.** Room worm sheets cite `reference/bookworm.png <sha256>`; `bookworm-small` cites
  `reference/bookworm_menu_bar.png 10475da8405e9ca99bf92cfa31236f284fdf07675896c2aa52c1deba8d3f1ac4`. Room sheets have
  no `reference` field.
- **Paths.** Every path is repo-relative to `ART/`. No field contains `/Users/` or `/private/` (the privacy assertion
  of `T/ArtAssetTests.swift:112-115`, copied).
- **Hashes.** sha256 of the raw file bytes, lowercase hex, exactly as `T/ArtAssetTests.swift:87-92` computes it.
- **Authoring.** Write the Codex CLI version the run actually used (`codex --version`; measured 0.159.3 on 2026-10-01).

### 6.4 `ART/preview.html` (generated; a local file, no network)

`tools/make_preview.py` (stdlib only) writes one self-contained HTML file. It inlines every sheet's JSON plus
`palette.json` and `room-plan.json`, and references the PNGs relatively as
`../../../Sources/CicadaApp/Resources/sprites/<name>.png`. `<img>` loads work from `file://`; `fetch()` does not, which
is why the JSON is inlined.

**What the page shows:**
- **Every sheet** as a grid of every tag. Each cell plays the tag at its real per-frame durations with
  `imageSmoothingEnabled = false` on a `<canvas>`, labelled with the tag name, frame count and total ms.
- **Controls:**
  - scale 4× / 6× / 8×;
  - ground: light `#F6F6F6`, dark `#1E1E1E`, or the room wall colour;
  - **Reduce Motion**, which shows frame 0 only;
  - **Low Power**, which doubles every duration;
  - pause/step;
  - "show key frames" (frame 0 of every tag on one board).
- **The room view.**
  - It composes the layers at `room-plan.json` cells, at 3× (the 1.0 lattice in points) and 4×.
  - A mood picker (the 7 page moods) drives the weather tag and the worm's state sheet.
  - A lamp toggle switches backdrop and lamp `dark`/`lit` and the fly.
  - A pose/beat picker plays any reachable tag once over the idle.
  - A cover readout shows the reading cycle.
  - The real pile appears as grey placeholder spines with the five textures.
- **The menu-bar strip.** All 8 small tags at 1× and 2× on a light and a dark bar mock-up, with the badge and dots
  drawn the way the app draws them (two digits, five dots), beside `reference/bookworm_menu_bar.png` at the same height.
- **"Drawn, not yet used."** `ART/demo/bookworm-mad-demo@6x.gif` (§4.5), referenced relatively, so the owner can answer
  Q3 by eye.
- **No external resources.** No font, script or stylesheet from the network. System fonts only.

Player logic (the same rules as the app, §7.2):

```js
function expand(json, tag) {               // tag: meta.frameTags entry; all ours are "forward"
  const order = [];
  for (let i = tag.from; i <= tag.to; i++) order.push(i);
  if (tag.direction === "reverse") order.reverse();
  if (tag.direction === "pingpong" && order.length > 2) order.push(...order.slice(1, -1).reverse());
  return { order, ms: order.map(i => json.frames[i].duration) };
}
function frameAt(clip, tMs, slowdown) {    // looping
  const total = clip.ms.reduce((a, b) => a + b, 0) * slowdown;
  let p = ((tMs % total) + total) % total;
  for (let k = 0; k < clip.ms.length; k++) { p -= clip.ms[k] * slowdown; if (p < 0) return clip.order[k]; }
  return clip.order[clip.order.length - 1];
}
```

---

## §7. App integration (Run C)

### 7.1 What stays exactly as it is

Behaviour that does not change:
- `BookwormState` and its derivations: `deriveBookwormState` (`S/MenuBar/BookwormState.swift:200-219`) and
  `deriveSleepPageMood` (`S/Views/Sleep/SleepMood.swift:130-174`).
- `BookwormPose`, `BookwormReaction` and `BookwormLook`, with `effective`, `reachable`, `beat`, the matrix
  (`S/MenuBar/BookwormPose.swift`). The one edit to that file is `ActiveReaction.length` (§7.3).
- `RoomModel`'s scheduling: perk on the hotspot edge with a 2 s cooldown, poke → talk, fed → gulp/shake, and cheer on a
  real completion (`S/Views/Sleep/RoomModel.swift:88-171`, `S/Views/Sleep/SleepView.swift:553-556`).
- `WormStage.pose` (`S/Views/Sleep/StudyRoom.swift:244-246`).
- `windowWeather(for:)` and `WindowWeather.all`.

Text twins that do not change:
- `BookwormView`'s accessibility label (`S/Views/Common/BookwormView.swift:108`);
- `WormHotspot`'s label, value, hint and actions (`S/Views/Sleep/StudyRoom.swift:283-303`);
- the lamp's and window's help, labels, hints and popovers (`:121-152`);
- `RoomA11yOrder` (`:22-33`);
- the menu header (`S/MenuBarManager.swift:219`);
- the cheer announcement (`S/Views/Sleep/SleepView.swift:555`).

Structure that does not change:
- The art layer stays inert: `.allowsHitTesting(false)` and `.accessibilityHidden(true)`
  (`S/Views/Sleep/DeskScene.swift:182-183`).
- The hover surface stays `.contentShape(Rectangle())` → `.onContinuousHover`, only in `StudyRoom.swift`
  (`:172-180`; `T/SleepNumbersLintTests.swift:117-145`).
- The drop target stays on `StudyRoom` (`T/RoomFeedTests.swift:241-258`).
- `BookPileView`, `fitPile` and `SpineButton`'s behaviour are unchanged, apart from §7.4's texture and `referenceCell`.

### 7.2 New files (all outside `S/Views/Sleep/` unless named, so the no-`duration:` lint without an escape hatch at `T/SleepNumbersLintTests.swift:196-207` never sees the Aseprite field)

**`S/Sprites/AsepriteSheetData.swift`** is the decoder. The JSON field is literally `duration`, so map it through
`CodingKeys`. A Swift line containing `duration:` fails `T/MotionLiteralLintTests.swift:15-28`.

```swift
import CoreGraphics

/// Aseprite's `--format json-array` export (verified against 1.3.18.6-dev): frames in sheet order, per-frame
/// milliseconds, tags with inclusive 0-based ranges, slices with per-frame keys. Pure data; decoding never throws
/// past `SpriteSheets` (a bad file is a missing sheet, never a crash).
struct AsepriteSheetData: Decodable, Equatable {
    struct Rect: Decodable, Equatable { let x, y, w, h: Int
        var cgRect: CGRect { CGRect(x: x, y: y, width: w, height: h) } }
    struct Size: Decodable, Equatable { let w, h: Int }
    struct Frame: Decodable, Equatable {
        let frame: Rect
        let sourceSize: Size
        let frameMs: Int
        enum CodingKeys: String, CodingKey { case frame, sourceSize, frameMs = "duration" }
    }
    struct Tag: Decodable, Equatable {
        let name: String
        let from: Int
        let to: Int
        let direction: String          // forward | reverse | pingpong | pingpong_reverse
    }
    struct SliceKey: Decodable, Equatable { let frame: Int; let bounds: Rect }
    struct Slice: Decodable, Equatable { let name: String; let keys: [SliceKey] }
    struct Meta: Decodable, Equatable {
        let image: String
        let size: Size
        let frameTags: [Tag]
        let slices: [Slice]
    }
    let frames: [Frame]
    let meta: Meta
}
```

**`S/Sprites/SpriteSheet.swift`** holds `final class SpriteSheet` and `enum SpriteSheets`.
- **`SpriteSheet` properties:** `name`, `image: CGImage`, `frameRects: [CGRect]`, `rectIndex: [Int]`, `frameSeconds: [TimeInterval]`
  (= `frameMs / 1000`), `frameSize: CGSize` (the shared `sourceSize`), `tags: [String: SpriteClip]`, and
  `slices: [String: CGRect]` (frame-0 key).
- **`SpriteSheet` methods:**
  - `func frameImage(_ index: Int) -> CGImage?`: `image.cropping(to: frameRects[index])`, cached per distinct rect
    (`rectIndex[index]`, the index of the frame's rect in the sheet's list of distinct rects, built when the sheet is
    decoded; de-duplicated frames share a rect). The crop cache is guarded by the sheet's own `NSLock`. A crop shares the
    decoded backing store, so the cache is cheap.
  - `func clip(_ tag: String) -> SpriteClip?`
- **`SpriteSheets.sheet(named:in:) -> SpriteSheet?`** is lock-guarded (`NSLock`, `nonisolated(unsafe)` dictionary: the
  pattern of `S/MenuBar/BookwormRenderer.swift:78-79`) and decoded once.
  - It reads through `Bundle.cicadaResources.cicadaResource(name, ext: "json"|"png", in: "sprites")`
    (`S/Utilities/ResourceBundle.swift:59-62`). Use the bare directory, never a `Resources/` prefix (`:31-52`).
  - It decodes the PNG with `CGImageSourceCreateWithURL` / `CGImageSourceCreateImageAtIndex` and
    `kCGImageSourceShouldCache: true`.
  - On any failure it returns nil and logs one line. It caches the failed name too, so a missing sheet logs once per
    name, never once per frame.
  - **Never write the string `Bundle.module` in new Swift, comments included:** `T/ResourceBundleTests.swift:13-24`
    greps the raw text of every source file except `ResourceBundle.swift`.
- **Coordinates.** Aseprite's `frame.x/y` are top-left, and `CGImage.cropping(to:)` is also top-left in image space.
  Pin that with a test that crops a known pixel.

**`S/Sprites/SpriteClip.swift`:**

```swift
/// One tag, expanded into play order (forward / reverse / ping-pong without repeating the ends), with each step's
/// seconds. Pure, Equatable, tested; the one place a frame is chosen from a clock.
struct SpriteClip: Equatable {
    let sheet: String
    let tag: String
    let order: [Int]                 // frame indices into the sheet, in play order
    let seconds: [TimeInterval]      // one per step of `order`
    var total: TimeInterval { seconds.reduce(0, +) }

    /// Looping clip: the step showing at `date`. `.still` → 0. Negative or degenerate inputs clamp to 0.
    func loopStep(at date: Date, origin: Date = SpriteClock.origin, profile: SpritePlaybackProfile) -> Int
    /// Once-clip (beat, transition): the step at `date`, or nil once it has played (the caller holds the last).
    func onceStep(at date: Date, startedAt: Date, profile: SpritePlaybackProfile) -> Int?
}
enum SpriteClock { static let origin = Date(timeIntervalSinceReferenceDate: 0) }
```

**`S/Sprites/SpritePlayback.swift`:**

```swift
enum SpritePlaybackProfile: Equatable, Sendable {
    case full, gentle, still
    /// Reduce Motion wins (G107 R7: the key frame); Low Power plays every frame at half speed (R-HO7's spirit).
    static func of(reduceMotion: Bool, lowPower: Bool) -> Self { reduceMotion ? .still : (lowPower ? .gentle : .full) }
    var slowdown: Double { self == .gentle ? CicadaMotion.spriteGentleSlowdown : 1 }
}

/// Fires only at frame boundaries of the clips a view shows — never a fixed fps — so an idle room redraws a few
/// times a second, not 30. Each entry is the boundary + 0.5 ms so `loopStep(at:)` lands inside the new frame.
struct SpriteFrameSchedule: TimelineSchedule {
    struct Track: Equatable { let origin: Date; let seconds: [TimeInterval]; let loops: Bool }
    let tracks: [Track]
    func entries(from startDate: Date, mode: TimelineScheduleMode) -> AnyIterator<Date>
    static func nextBoundary(after date: Date, track: Track) -> Date?    // pure; tested
}
```

`nextBoundary` works as follows:
- With `total ≤ 0` it returns nil.
- For a loop: `k = ⌊(date − origin) / total⌋`, `phase = elapsed − k·total`, then the first cumulative `c_i > phase + 1e-4`
  gives `origin + k·total + c_i + 0.0005`.
- For a once-clip: the first `c_i > elapsed + 1e-4`, else nil.
- `entries` yields `startDate` first, then repeatedly the minimum next boundary across tracks, advancing every track that
  shares it (within 1 ms).

**`S/Sprites/SpriteLayerView.swift`** is one inert leaf per animated layer.

```swift
/// One sprite layer: a static Image for a one-frame tag, the key frame under `.still`, nothing ticking while the window
/// cannot be seen; otherwise a TimelineView on `SpriteFrameSchedule`. Nearest-neighbour, whole points per pixel.
struct SpriteLayerView: View {
    let clip: SpriteClip?
    let sheet: SpriteSheet?
    let pixelScale: CGFloat                    // points per art pixel (RoomLattice.cell, or k)
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePaused) private var hostPaused           // PaintedScene.swift:105-114
    @State private var windowVisible = true
    var body: some View {
        let profile = SpritePlaybackProfile.of(reduceMotion: reduceMotion, lowPower: SceneStore.shared.lowPower)
        let paused = SceneRunPolicy.isPaused(windowVisible: windowVisible, hostPaused: hostPaused)   // SceneMotion.swift:19-26
        Group {
            if let clip, clip.order.count > 1, profile != .still, !paused {
                TimelineView(SpriteFrameSchedule(tracks: [.init(origin: SpriteClock.origin,
                        seconds: clip.seconds.map { $0 * profile.slowdown }, loops: true)])) { context in
                    frame(clip.order[clip.loopStep(at: context.date, profile: profile)])
                }
            } else if let clip {
                frame(clip.order.first ?? 0)
            } else {
                Color.clear.frame(width: (sheet?.frameSize.width ?? 0) * pixelScale,
                                  height: (sheet?.frameSize.height ?? 0) * pixelScale)   // no clip: draw nothing
            }
        }
        .background(WindowVisibilityReader { windowVisible = $0 })   // Views/Meadow/WindowVisibilityReader.swift:7-40
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
    private func frame(_ index: Int) -> some View {
        let size = (sheet?.frameSize ?? .zero)
        return Group {
            if let cg = sheet?.frameImage(index) {
                Image(decorative: cg, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        }
        .frame(width: size.width * pixelScale, height: size.height * pixelScale)   // never moves layout
    }
}
```

These reuse `SceneRunPolicy`, `WindowVisibilityReader`, `SceneStore.shared.lowPower` (`S/Theme/SceneStore.swift:20`) and
`\.scenePaused`. They are not on `T/MeadowPlacementLintTests.swift:10-15`'s banned list. Never call `PaintedScene(`,
`MeadowArt.image(` or `ArtImage(` from the sprite code.

**`S/Sprites/BookwormArt.swift`** holds the registry and sizing. All of it is pure and tested.

```swift
enum BookwormArtSet: Equatable { case room, small }
enum BookwormArt {
    static let roomFrame = CGSize(width: 64, height: 48)
    static let smallFrame = CGSize(width: 18, height: 18)
    static let covers = 3
    static func sheetName(_ state: BookwormState, _ set: BookwormArtSet) -> String
    static func tag(_ look: BookwormLook, cover: Int = 1) -> String                   // §4.1
    static func requiredTags(_ state: BookwormState) -> Set<String>                   // §4.1
    static func smallRequiredTags() -> Set<String>                                    // the 8 caseNames
    static func clip(_ state: BookwormState, look: BookwormLook, cover: Int = 1,
                     set: BookwormArtSet = .room) -> (SpriteSheet, SpriteClip)?        // with §4.2's fallback chain
    static func coverIndex(at date: Date, profile: SpritePlaybackProfile) -> Int       // §4.3
    static func beatLength(_ kind: BookwormReaction, state: BookwormState) -> TimeInterval   // centre variant's total; spriteBeatMax if missing
    static func transitionLength(_ t: BookwormTransition) -> TimeInterval
    /// Always `bookworm-sleeping`'s `t.rawValue` tag, whatever the current state (the outro plays after the mood has
    /// left `.sleeping`, so `clip(state:look:)` would fall back to the new state's idle).
    static func transitionClip(_ t: BookwormTransition) -> (SpriteSheet, SpriteClip)?
    /// Union of the `ink` slices of every page-state sheet (they share one canvas), in canvas pixels, top-left.
    static var wormInk: CGRect { get }
    static var eyePixel: CGPoint { get }
}
struct BookwormSize: Equatable {
    let set: BookwormArtSet; let pixelScale: CGFloat; let size: CGSize
    /// §2.5: lattice → room at `cell`; nominal ≥ 48 → room at max(1, round(pt·s/48)); else small at max(1, round(pt·s/18)).
    static func resolve(pointSize: CGFloat, uiScale: CGFloat, latticeCell: CGFloat?) -> BookwormSize
}
enum BookwormTransition: String, Equatable { case yawn = "intro", stretch = "outro" }   // tags in bookworm-sleeping
struct ActiveTransition: Equatable { let kind: BookwormTransition; let startedAt: Date; let id: UUID; let length: TimeInterval }
```

**`S/Views/Sleep/RoomLattice.swift`:**

```swift
/// The one room lattice (P12): 160 × 64 cells; a cell is a whole number of points (§2.1 of the 2026-10-01 spec).
enum RoomLattice {
    static let cols = 160
    static let rows = 64
    static func cell(uiScale: Double) -> CGFloat { max(2, (3 * uiScale).rounded()) }
}
```

**`S/Views/Sleep/SpineTexture.swift`** is §7.4's spine view, kept out of `BookPile.swift` so `.white` stays out of it
(`T/SpineAndLampTests.swift:55-58`).

### 7.3 Changed files

**`S/Theme/CicadaMotion.swift`.** Add a `// MARK: - Sprites (TODO ruling 18)` extension next to the living-painting
tokens (`:160-209`). This file is exempt from both duration lints.

```swift
static let spriteFrameMin: TimeInterval = 0.04       // no frame shorter (≤ 25 redraws/s per layer)
static let spriteFrameMax: TimeInterval = 4.0
static let spriteLoopMin: TimeInterval = 0.4
static let spriteLoopMax: TimeInterval = 30
static let spritePerkMax: TimeInterval = 0.4         // the pointer-edge beat stays as quick as before
static let spriteBeatMax: TimeInterval = 0.8         // R-Z12 amended: a response settles within 800 ms
static let spriteTransitionMax: TimeInterval = 1.6   // the yawn / the stretch
static let spriteGentleSlowdown: Double = 2          // Low Power plays every frame at half speed
static let spriteTimerTolerance: Double = 0.2        // menu bar: tolerance as a fraction of the frame
```

**`S/Views/Sleep/SleepMotion.swift`.**
- Delete `beatFrameInterval` and `maxBeatFrames` (`:48-52`); their one reader, `settleReaction`, moves to the clip's
  length.
- Keep `weatherDuration` 0.4 and `weather(reduceMotion:)` (`:74`, `:97-99`). The crossfade between moods stays the same.
- Update the doc comment (`:3-26`) to point at ruling 18.

**`S/Views/Common/BookwormView.swift`** is rewritten on the sprite clock.
- **Parameters.** `state`, `pointSize: CGFloat = 96` (nominal height), `latticeCell: CGFloat? = nil`, `caption…`,
  `alignment`, `pose`, `reaction: ActiveReaction?`, `transition: ActiveTransition? = nil`.
- **Size.** It resolves `BookwormSize`.
- **Clip.** It picks the clip by §4.2's precedence.
  - A transition always draws `BookwormArt.transitionClip(_:)`, never the current state's sheet.
  - For `.reading`, it computes `k = BookwormArt.coverIndex(at: context.date, profile: profile)` **inside the
    `TimelineView` content closure** and picks the `@k` clip there. A `TimelineView` re-runs only its content closure,
    not `body`, so a cover picked in `body` would never advance at the 21.84 s boundary and the loop would jump back to
    cover 1 at the seam. All three covers share durations, so one schedule serves them. Never compute the cover in
    `body`.
- **Timing.** It drives a `TimelineView(SpriteFrameSchedule)`: a looping track for the pose loop, or a once track from
  `startedAt` for a beat or transition.
- **Pausing.** It rests with `WindowVisibilityReader` and `\.scenePaused`, like `SpriteLayerView`.
- **Drawing.** It draws `Image(decorative:scale:).resizable().interpolation(.none)` at `size`.
- **Small set.** It composites the overlays (§7.3, `BookwormRenderer`) through `BookwormRenderer.smallImage`.
- **Label.** The accessibility label is unchanged.
- **Removed.** Delete `frameIndex(at:interval:count:reduceMotion:)` and `reactionFrameIndex` and their tests, or keep
  them as thin forwarders to `SpriteClip`. Either way the new tests in §7.7 cover the behaviour.

**`S/MenuBar/BookwormRenderer.swift`** becomes the mascot's own cache over sheets (P13: never `PixelRenderer.sceneCache`).
- **`smallImage(state:frameStep:pointSize:)`.** Returns an `NSImage` of `pointSize` square, drawn
  `NSImage(size:flipped:drawingHandler:)`. It draws the `bookworm-small` frame with `interpolationQuality = .none` and
  `setShouldAntialias(false)`, then the overlay grid (`BookwormOverlays`) through `PixelRenderer`'s drawing at
  `pointSize / 18` per cell. `isTemplate = false` (`S/MenuBar/PixelRenderer.swift:57-84`'s rules).
- **Cache.** Keyed `"small|\(state.spriteKey)|\(rectIndex)|\(Int(pointSize))"`, where `rectIndex` is the index of the
  frame's rect in the sheet's list of distinct rects (`SpriteSheet.rectIndex[frame]`, built when the sheet is decoded),
  so de-duplicated frames share keys. `frameStep` wraps modulo the clip's step count. It keeps the `maxCacheEntries = 1024` wholesale wipe (`:84`). The
  menu bar's `curious(1…99)` keys are 99 × at most 4 frames = 396 at 18 pt.
- **Room frames.** They need no `NSImage` cache: `SpriteSheet.frameImage` crops are cached per sheet.
- **Removed.** Delete `gridSize`, `snappedPointSize`, `image(grid:)` and `keyIndex`. `PixelRenderer.snappedPointSize`
  stays for the stage icons.

**`S/MenuBar/BookwormSprites.swift`** is reduced to `S/MenuBar/BookwormOverlays.swift`.
- **Keep:** `BookwormPalette` (9 keys, unchanged values, so `T/DeskPaletteTests.swift`'s equalities `d==o`, `n==a`,
  `s==q` still hold), the 3 × 5 `digits`, and the badge pill and stage dots, redrawn for an **18-cell** grid.
- **Keep and move:** `typealias PixelGrid = [String]` (`S/MenuBar/BookwormSprites.swift:7`) moves to
  `S/MenuBar/PixelRenderer.swift`. `PixelRenderer.swift`, the stage icons (`S/Views/Sleep/SleepStages.swift:212-316`) and
  `T/PixelRendererTests.swift:50` still use it.
- **Badge.** A `q` pill with `o` digits (today's colours, `T/BookwormSpriteTests.swift:81-91`; a white-on-gold pill
  would be about 2:1 contrast), cols 9–17 × rows 11–17 for two digits and cols 13–17 for one.
- **Stage dots.** Five 1-cell dots on row 17 at cols 1, 5, 9, 13, 17: `a` filled up to the stage, `o` empty.
- **Delete** every worm grid, `frames(for:)`, `frames(for:look:)` and the frame memo.

**`S/MenuBarManager.swift`.**
- `animates(_:reduceMotion:)` reads the small clip's step count (`:32-34`).
- Replace the repeating `Timer` (`:171-188`) with a chained one-shot timer: each fire advances `frameStep` modulo the
  clip and schedules the next with `seconds[step] * profile.slowdown`, `tolerance = that * spriteTimerTolerance`, in
  `RunLoop.main` `.common` mode. Restart only on a `caseName` change, as today (`:106-112`).
- `renderCurrentFrame` sets `button.image = BookwormRenderer.smallImage(...)` (`:197-210`).
- **VoiceOver.** The status item is image-only and has no accessibility label today (`:78`, `:197-210`). On every render,
  set `button.setAccessibilityLabel("Cicada — \(state.title), \(state.detail)")`, and give the `NSImage` the same
  `accessibilityDescription`.
- **Resting.** The chained timer schedules nothing while `!isVisible` (`:17-21`) or between
  `NSWorkspace.screensDidSleepNotification` and `NSWorkspace.screensDidWakeNotification` (both on
  `NSWorkspace.shared.notificationCenter`, like the Reduce Motion observer at `:89-94`). `setVisible(true)` and the wake
  notification re-render and restart it.
- Low Power: read `SceneStore.shared.lowPower` at each schedule.
- The DEBUG harness (`:399-406`) renders the small frame 0 of each state.
- `spritePointSize` stays 18.

**`S/Views/Sleep/DeskScene.swift`.**
- **Types.** Move `enum DeskProp: String, CaseIterable, Hashable` from `S/Views/Sleep/DeskSceneSprites.swift:10-12` into
  `DeskScene.swift` before that file is deleted. `DeskProp` becomes `backdrop, pane, window, plant, lamp, fly, beanbag,
  mug`; `cushion` is renamed `beanbag`. `DeskLayer` keeps `prop`, `cellX`, `cellY` and `z` (`:7-15`) and gains `w` and `h`
  (canvas cells).
- **Lattice and plan.** `DeskScene.cols/rows` come from `RoomLattice`, and `plan` is §2.2's table. `wormCell` is
  `(36, 9)`; `pileCell` is `(110, 0, 50, 52)`.
- **Layout.** `deskSceneLayout(uiScale:)` drops `pointSize`. Its cell is `RoomLattice.cell(uiScale:)`; update the
  callers in `S/Views/Sleep/StudyRoom.swift:104`, `T/SleepLayoutTests.swift:20` and the tests.
- **`RoomArt.tag(prop, lampLit:, weather:) -> (sheet: String, tag: String)?`** maps each prop:
  - backdrop and lamp → `lit`/`dark`;
  - pane → `weather.rawValue`;
  - fly → `buzz` only when lit, else nil;
  - the others → `idle`.
- **`DeskSceneView`** is a `ZStack(alignment: .bottomLeading)` of `SpriteLayerView`s, each offset by whole cells
  (`.offset(x: CGFloat(layer.cellX) * layout.cell, y: -CGFloat(layer.cellY) * layout.cell)`).
  - It drops its `pointSize` parameter; update its call at `S/Views/Sleep/StudyRoom.swift:111` (and `WormStage`'s at
    `:113`, below).
  - A layer whose `RoomArt.tag` is nil (the fly while the lamp is dark) is left out of the `ZStack`.
  - **The pane** keeps its crossfade: `ZStack { SpriteLayerView(...).id(weather).transition(.opacity) }
    .animation(SleepMotion.weather(reduceMotion:), value: weather)` (today `:162-174`).
  - **Inert and hidden:** keep `.allowsHitTesting(false)` and `.accessibilityHidden(true)`.
  - **No clock in `StudyRoom`.** `StudyRoom`'s body never reads the clock; only the leaves tick.
- **Docstrings.** Rewrite them (`:3-6`, `:34-46`, `:51-76`, `:86-110`, `:129-138`, `:198-212`) to say what is true now.

**`S/Views/Sleep/DeskHotspots.swift`** derives from the sheets' slices; its output keys and shape are unchanged.
- **Worm.** `wormCols` and `wormRows` come from `BookwormArt.wormInk` mapped into scene cells at `wormCell`. `eyeCell`
  comes from `BookwormArt.eyePixel`.
- **Lamp.** From `room-lamp`'s `ink` slice at its plan cell.
- **Window.** From `room-window`'s `glass` slice, clipped at `wormCols.lowerBound − 1` (as `:41-47`).
- **Unchanged rules.** Hotspots stay whole cells and disjoint (R-Z8); `gazeFor` is unchanged (`:62-74`).

**`S/Views/Sleep/StudyRoom.swift`.**
- **The worm.** `WormStage(mood:room:cell: scene.cell)` with `.offset(x: scene.wormOrigin.x, y: -scene.wormOrigin.y)`
  (unchanged form; the lint needs `wormOrigin`). `WormStage` passes `latticeCell: cell` and
  `transition: room.transition`.
- **Settling.** It adds `.task(id: room.transition?.id) { await room.settleTransition() }` beside the reaction's task
  (`:239`).
- **Mood changes.** It adds `.onChange(of: page.mood.caseName) { old, _ in room.moodChanged(from: old, to: page.mood,
  reduceMotion: reduceMotion) }` (StudyRoom reads `page.mood`, `:85`, `:113`). `onChange` does not fire on the initial
  value, so nothing animates on mount (DR-65).
- **Everything else** stays as it is: the pile frame, the hotspots, labels, popovers, hover and drop.

**`S/Views/Sleep/RoomModel.swift`.**
- **Beat length.** `ActiveReaction` (`S/MenuBar/BookwormPose.swift:74-78`, the one edit to that file) gains
  `let length: TimeInterval`. Name it that, never `duration`, because of the lint. `play` fills it from
  `BookwormArt.beatLength(kind, state:)`.
- **Settling.** `settleReaction` sleeps `playing.length` (today a fixed 0.36 s at `:330-334`).
- **Transitions.** Add `var transition: ActiveTransition?`, `func moodChanged(from old: String, to new: BookwormState,
  now: Date = Date(), reduceMotion: Bool)` and `func settleTransition() async`.
  - **It does nothing** under Reduce Motion, when `old == "awake"` (the cold-start mood: `deriveSleepPageMood` returns
    `.awake` until status and debt arrive, `S/Views/Sleep/SleepMood.swift:138`, `:157`, so a first load or a page
    opened mid-run never yawns, R-BW4, DR-65), or when `new` is `.awake`.
  - **Beats first.** It clears `reaction` only when `!Self.beatAllowed(reaction.kind, state: new, reduceMotion:)`, so a
    cheer started on the same edge survives. SwiftUI does not order SleepView's status `onChange` (`SleepView.swift:313-329`,
    which calls `celebrateCompletion`, `:553-556`) against StudyRoom's mood `onChange`.
  - **Then the transition**, only if no reaction is active after that: `new.caseName == "sleeping"` (and `old` is not)
    sets `.yawn`; `old == "sleeping"` sets `.stretch` only when `new` is `.digesting`, `.happy`, `.reading` or `.hungry`,
    never `.error` (its red pupils and drop show at once, R-Z1).
  - **`play(...)`**, when it starts a beat, sets `transition = nil`. So either call order gives the same result: a real
    completion plays the cheer and no stretch, a cancelled cycle plays the stretch, and a failed one plays neither.
  - The transitions are state art, not responses, so the matrix does not gate them; a beat outranks a transition (§4.2).

**`S/Views/Sleep/WindowWeather.swift`.**
- **Titles.** Change them to §5.1's.
- **Thumbnails.** Draw `room-weather` frame 0 of the weather's tag, at `max(1, uiScale.rounded())` pt per pixel
  (36 × 32 pt at 1.0) with `.interpolation(.none)`, through `SpriteSheets`. This replaces `:91-101`.
- **Docstring.** Update it (`:3-8`): "animated, the loop shows the mood that is already true; still refused: a flash,
  a clock, a count".

**`S/Views/Sleep/BookPile.swift`.** `PileFitting.referenceCell` 5 → **3** (`:79`), so spines stay 8–40 pt at 1.0 and
`unit = cell/referenceCell` (`:113`) stays 1 at 1.0. Update the `PileFitting` comments (`:73-90`) in the same edit:
`referenceCell` is "`RoomLattice.cell(uiScale: 1.0)`", and the `maxSpines` note becomes "8 × (floor + gap) is 100.3 of
104 pt at 0.8× and 139.2 of 156 pt at 1.1×; nine would need 112.8 and 156.6" (spine gap 2 × unit, `:114`, `:233`;
re-measure in `PileFitTests` before committing the numbers). `SpineButton.shape` draws `SpineTexture` instead of
`RoundedRectangle(cornerRadius: 3)` (`:317-341`). Everything else, `fitPile` included, is untouched.

**Other call sites.**
- `S/Views/Sleep/SleepView.swift`: delete `wormPointSize` (`:497`), and update the motion-budget comment (`:136-155`) to
  ruling 18.
- `S/Views/Contributors/ContributorsView.swift:335`: `BookwormRenderer.smallImage(state: .happy, frameStep: 0,
  pointSize: 18)`, still `.resizable()` and circle-clipped.
- `S/Views/Common/EmptyStateView.swift` and `S/Views/Intake/IntakePanel.swift`: no API change. Check the new widths
  (§2.5).

**Delete `S/Views/Sleep/DeskSceneSprites.swift`.** All of its grids are retired. Keep `S/Views/Sleep/DeskPalette.swift`:
the stage icons still use it (`S/Views/Sleep/SleepStages.swift:191-207`, `T/SleepStageStripTests.swift:225-255`).

### 7.4 Spine texture view (§5.6)

```swift
/// G176 — a pixel spine over the origin's colour: body mask filled with the colour, then the light and shade masks,
/// at the room lattice (one pixel = `cell` points, P12). The left 20 columns are a 9-slice (crisp: they are constant
/// along the stretched axes, §5.6); the right 4 columns carry the kind mark, drawn unstretched and cropped to the
/// spine's height. The label sits on the plain centre (DR-50).
struct SpineTexture: View {
    let kind: SpineKind          // spineKind(for: origin) — total; tested against OriginIconography.allKnownOrigins
    let color: Color
    let cell: CGFloat
    let size: CGSize
}
enum SpineKind: String, CaseIterable { case chat, page, note, video, other }
func spineKind(for origin: String) -> SpineKind
```

A spine's width is `fit.maxWidth * spec.widthFraction` (`S/Views/Sleep/BookPile.swift:245`), and `widthFraction` is
remaining ÷ count (`:55`), so a spine can be far narrower than the mask. Its height is 8–40 pt at 1.0, i.e. 2.7–13.3
art pixels at every zoom step, against a 12-px mask.

- **Too small for a texture.** Below `9 · cell` pt wide or `5 · cell` pt tall, draw a plain `Rectangle` in `color`.
- **The body of the spine.** For each mask, crop its left 20 columns (`cropping(to: CGRect(x: 0, y: 0, width: 20,
  height: 12))`) and draw it with `Image(decorative: crop, scale: 1 / cell)`, `.resizable(capInsets: EdgeInsets(top:
  cell, leading: 4 * cell, bottom: cell, trailing: 0), resizingMode: .stretch)`, `.renderingMode(.template)` and
  `.interpolation(.none)`, at the full `size`. Only uniform rows and columns stretch, so nothing smears.
- **The mark.** For the light and shade masks, crop the right 4 columns, rows `1 + ⌊(10 − r)/2⌋` for `r` rows, where
  `r = min(10, ⌊size.height / cell⌋ − 2)`. Draw it unstretched at `cell` pt per pixel (`4 · cell × r · cell`),
  trailing-aligned, at a whole-point y that centres it vertically, over the stretched body.
- **Tints.** The body takes `color`, the light mask `CicadaTheme.onFill.opacity(0.30)`, and the shade mask a new token
  `CicadaTheme.spineShade`: black at 0.25, mode-independent like the origin colours, added in `S/Theme/CicadaTheme.swift`.
- **Caching.** Crops are cached per kind and mask (15 images) on first use; nothing is cached per spine size.

### 7.5 Lints: what changes, by file

| Lint | Change |
|---|---|
| `T/SleepNumbersLintTests.swift:77-94` | Replace the `beatFrameInterval × maxBeatFrames` and `== reactionInterval` lines (`:85-88`) with: every beat tag total ≤ `CicadaMotion.spriteBeatMax` (perk ≤ `spritePerkMax`), read from the sheets. Keep every other line. |
| `T/SleepNumbersLintTests.swift:100-113` | Keep, and add: `SpritePlaybackProfile.of(reduceMotion: true, lowPower: _) == .still`, and `RoomModel.moodChanged` under Reduce Motion sets no transition. |
| `T/SleepNumbersLintTests.swift:152-189` | Keep as is (the worm is still never transformed). Add `testRoomSpritesAreNeverTransformed`, the same chain scan over `SpriteLayerView(` under `Views/Sleep/`: no `.scaleEffect(`, `.rotationEffect(` or `.spring(`, and every `.offset(` contains `cell`. |
| `T/SleepNumbersLintTests.swift:196-207` | Unchanged. The decoder lives in `S/Sprites/` and uses `frameMs`. |
| `T/MotionLiteralLintTests.swift:15-28` | Unchanged. No `duration:` in new Swift (`frameMs`, `seconds`, `length`). |
| `T/ThemeTokenTests.swift:71-82` | Unchanged. No palette hex is written in Swift; colours live in the PNGs and `palette.json`. |
| `T/MeadowPlacementLintTests.swift:10-15` | Unchanged. |
| `T/SleepMeadowTests.swift:62-69` | Unchanged. Props stay inert. |

### 7.6 Tests that change (by file)

| File | Change |
|---|---|
| `T/BookwormSpriteTests.swift` | Rewrite as sheet-contract tests: for each state, the JSON tag set **equals** `BookwormArt.requiredTags`; the small set equals the 8 `caseName`s; every frame equals the canvas (64×48 / 18×18); every idle tag has ≥ 2 distinct frame rects; durations are inside the §7.3 caps; the reading `@k` totals are equal. Keep the badge and stage-dot tests, re-pinned to the 18-grid strings. Delete the nightcap, glasses-row and `awakeBase` pins (`:65-77`, `:132-190`); §4.4's mark tests replace them. `:24-28`: keep the 9-key `BookwormPalette` assertion and drop `BookwormSprites.size == 24`. `:99-108` (curious frames carry the count) and the `frames(for: .sleeping)` loop at `:114-116`: rewrite against `BookwormOverlays`' 18-cell badge and dot grids. `:194-204` (`shift`/`merge` keep dimensions): delete unless those helpers survive in `BookwormOverlays`. |
| `T/BookwormPoseSpriteTests.swift` | Keep `test_theMatrix` (`:130-143`) and the "suppressed states ignore the pointer" test (`:120-127`). Replace the grid tests (`:25-117`) with §4.4's sheet mark tests over every reachable tag. Replace `test_everyBeatFitsTheMotionBudget` (`:147-156`) with the caps over the sheets, and `test_theLoopsKeepTheirIntervals` (`:160-168`) with §6.2's irregular-blink check (blink frames have ≥ 2 fewer `W` px than frame 0; run counts and gap ratio ≥ 1.6) and: gaze variants share durations. Add the lift check (base row 47 outside `perk.*`, `eager`, `cheer.center`; 44–47 inside) and the z-box check. |
| `T/BookwormStateTests.swift` | Keep the derivation and copy tests (`:24-66`). `:68-75` becomes: the `bookworm-error` idle has ≥ 2 distinct frames, `e` in every frame, and ≥ 1 `S`. Keep `:81-87`, reading the small clip. |
| `T/BookwormRendererTests.swift` | Sample `smallImage`: 18 × 18, not a template, the lime `m` body present, transparent corners. Key strings become `small|awake|0|18`, `small|curious|47|<rect>|18`. Keep identity cache hits, curious counts differing, and the menu bar at 18 × 18 (`:36-83` re-pinned). `:68-72` (`testCachedImageWrapsFrameIndex`) becomes: `smallImage` wraps `frameStep` modulo the clip's step count. Add: the status button's accessibility label names the state (MenuBarManager, §7.3). |
| `T/BookwormLookRendererTests.swift` | Retire the `cacheKey` tests (`:12-23`), the `cachedImage(look:)` test (`:83-89`) with the look cache, and the ≤ 256-key bound and the `keyIndex` tests (`:27-57`). Keep the Reduce Motion pose test (`:103-108`) unchanged. Replace them with: the unique frame rects per room sheet ≤ 1024, and the decoded pixels of all `RES/` sheets ≤ 8,388,608 (8 M px ≈ 32 MB). Keep every-beat-is-reachable (`:65-81`). The beat clock (`:91-99`) becomes `SpriteClip.onceStep` over the real `perk.center` durations. |
| `T/BookwormViewTests.swift` | Retire the uniform `frameIndex` tests (`:11-27`) and the multiple-of-24 tests (`:31-45`) for `SpriteClipTests` and the `BookwormSize` cases of `BookwormArtTests` (§7.7). |
| `T/BookwormFramesBenchmarkTests.swift` | Becomes a `measure` of `BookwormArt.clip` + `frameImage` over every reachable look × 20 iterations, with the sheets warm. |
| `T/WindowSpritesTests.swift` | Rewrite on sheets: §5.3's ruling-9 check per frame of every weather tag, seven distinct key frames, and the composite writer (`CICADA_WRITE_COMPOSITES=1`) writing frame-0 room composites for every mood × lamp lit/dark at 1.0 and 1.4 to `$TMPDIR` (`:131-156`'s pattern). |
| `T/DeskSceneLayoutTests.swift` | The cell table (2/3/3/3/4/4/4) and size 160·cell × 64·cell at every step; the plan equals `ART/room-plan.json` (read via `#filePath`); z strictly ascending; every layer inside the scene; no ink at col ≥ 110; the worm's baseline equals the bean bag's `seat` row; the pane equals the window's `glass`; and the pile column is ≥ 150 pt at 1.0 (`:131-134` kept). |
| `T/DeskSceneSpritesTests.swift` | **Delete.** Replaced by `T/RoomSpriteTests.swift` (§7.7). |
| `T/DeskHotspotTests.swift` | Keep the invariants (`:11-54`): whole cells, disjoint, inside the scene, out of the pile, the eye inside the worm. Re-pin the literal rects at 3 pt (`:57-62`) from the finished art: measure, then write the numbers. `:64-68` (`test_sceneBottomLeadingFlipsY`) re-pins to the 192-pt room: `deskSceneLayout(uiScale: 1.0)`, `(200, 70)` → `(200, 122)` and `(10, 0)` → `(10, 192)`. |
| `T/GazeTests.swift` | Derive x positions, edges and hysteresis from `layout.cell` and `DeskHotspots.wormCols` instead of 100/150/250/… (`:9-45`). |
| `T/RoomModelTests.swift`, `T/RoomFeedTests.swift` | `overWorm` and `overLamp` become the midpoints of `deskHotspots(layout)`, flipped to top-left (`T/RoomModelTests.swift:14-15`, `T/RoomFeedTests.swift:15-16`). Add: `settleReaction` clears after the beat's `length` (inject a short length). `moodChanged`: reading → sleeping yawns; sleeping → digesting/happy/reading/hungry stretches; sleeping → error and anything from or to `awake` set nothing; nothing under Reduce Motion; a beat the new state forbids is cleared and one it allows is kept. Both orders of `play(.cheer, state: .digesting)` and `moodChanged(from: "sleeping", to: .digesting)` end with `reaction?.kind == .cheer` and `transition == nil`. |
| `T/PileFitTests.swift` | `referenceCell == 3`, `room(1.0).cell == referenceCell`. 1.2× pins 14·4/3 (the old 1.1× case). "Nine would not fit at 1.0" (`:68-80`) becomes "nine fails at some step" (0.8 and 1.1 measured). Re-run and re-pin; never copy a number from this spec. |
| `T/WindowWeatherTests.swift` | The new titles; still seven distinct; the mood map unchanged (`:8-17`); no clock (`:29-34`). |
| `T/PixelRendererTests.swift` | Delete the whole `testBookwormSnapIsTheTwentyFourCellCase` (`:72-78`): `BookwormRenderer.snappedPointSize` and `gridSize` are gone. `:128-136`: the isolation test floods 600 scene keys and asserts `BookwormRenderer.smallImage(.happy, 0, 18)` is still identical. |
| `T/SleepLayoutTests.swift` | `:20` calls `deskSceneLayout(uiScale:)`, and the doc comment's sum (`:15-16`) becomes 640 + 44.8 + 67.2 = 752 pt. The assertion is unchanged and passes (640 ≤ 648 at 1.4). |
| `T/SkyBandTests.swift`, `T/SleepStageStripTests.swift`, `T/DeskPaletteTests.swift`, `T/EmptyStateViewTests.swift`, `T/SpineAndLampTests.swift`, `T/BookPileTests.swift` | Expected unchanged. If one fails, fix the code, not the test, unless this spec says otherwise. |

### 7.7 New tests

| File | Asserts |
|---|---|
| `T/SpriteAssetTests.swift` | Modelled on `T/ArtAssetTests.swift`. (1) The manifest's png ∪ json equals the bundled `sprites/` png and json minus `sprites.manifest.json`. (2) Every `pngSha256`/`jsonSha256` matches the raw bytes. (3) The required fields are `id`, `png`, `json`, `role`, `generator`, `script`, `source`, `authoring`, `date`, `licence`, `processing`, `pngSha256` and `jsonSha256` (`reference` is optional: room sheets have none); each is non-empty, the date matches `^\d{4}-\d{2}-\d{2}$`, the sha256 values match `^[0-9a-f]{64}$`, the role is in the set, and no field contains `/Users/` or `/private/`. (4) Sprites resolve in both bundle layouts, built from bytes (`:225-245`'s pattern with directory `"sprites"`). (5) Every opaque pixel's RGB is in `ART/palette.json` (read via `#filePath`), alpha is binary, and no colour is a reserved state hex. (6) Total bytes ≤ 6 MiB and every sheet's longest side ≤ 2048. **Do not copy the Lanczos > 256-colour check (`:181-205`); it is for paintings.** |
| `T/SpriteSheetTests.swift` | The decoder reads `duration` into `frameMs` and reads `frameTags`, `slices` and `sourceSize`. Direction expansion: forward, reverse, and pingpong `[0,1,2]` → `[0,1,2,1]`. A `repeat` string is tolerated. Cropping is top-left (a known pixel). A missing sheet returns nil without crashing. |
| `T/SpriteClipTests.swift` | `loopStep`: cumulative, modulo, boundary-inclusive, negative dates, `.still` → 0, `.gentle` doubles every step. `onceStep`: nil after the total, 0 before the start. `SpriteFrameSchedule.nextBoundary` for loop and once tracks, and the merge across two tracks. **The redraw budget (R-BW11):** for each page mood × lamp lit/dark, the merged schedule of every layer the room draws (pane, fly, worm idle) yields ≤ 1,800 boundaries per minute; the worst case is Rainy + lit + error. |
| `T/BookwormArtTests.swift` | `tag(look)` equals `keySegment ?? "idle"` for every reachable look. `requiredTags` counts are awake 18, hungry 18, happy 19, reading 54, digesting 7, sleeping 4, error 1, curious 1. The fallback chain. `coverIndex` cycles 1→2→3 at multiples of T and is 1 under `.still`. `BookwormSize.resolve`: lattice 3 → room 192×144; 96@1.0 → room k2 128×96; 48@1.0 → room k1 64×48; 24@1.0 → small k1 18×18; 24@1.2 → small k2. `transitionClip(.stretch)` and `(.yawn)` come from `bookworm-sleeping` whatever the state. The `eye`, `lensL` and `lensR` slices are equal on every room sheet. |
| `T/RoomSpriteTests.swift` | Each room sheet has its exact tags, canvas size and slices. Lamp `dark`/`lit` differ only in `shade`; backdrop only in `glow`. The fly's ink is outside the glass and the pile in every frame, and frame 0 lies on the lamp's shade (fly ink adjacent to lamp ink). Weather loops are seamless: every element of `ART/room-motion.json` (read via `#filePath`) steps from its last frame to its first like any other step (`pos[n − 1] + step ≡ pos[0]` modulo its wrap). Every fly frame has 0–2 opaque px, and frame 0 has ≥ 1. The storm tag's per-frame mean luminance stays within 2 % of its mean. |
| `T/SpineTextureTests.swift` | `spineKind` is total over `OriginIconography.allKnownOrigins`, with the §5.6 table pinned. The three masks of every kind exist and are binary. The kind mark lies in the right 4 px, rows 1–10. Columns 0–19 are constant along rows 1–10 and columns 4–19 are identical. Rows 4–6 of the right 4 columns of light ∪ shade differ for every pair of kinds. Spines below `9 · cell` × `5 · cell` draw the plain rectangle. |

### 7.8 Docs that change in the same PR

See §8: `docs/architecture/app.md` (Sleep page, Mascot states, Graphite and Meadow, Settings → General), `TODO.md`,
`memory-evolution.md`, `DESIGN_RULES.md` §9, a one-clause `CLAUDE.md` rail edit, `ART_DIRECTION.md`, and BRIEF plus
handoff.

---

## §8. Amendments and docs (exact texts; dated 2026-10-01)

### 8.1 `docs/goals/TODO.md` — insert after ruling 17 and before `## How work is run here` (`:854`)

Use the next free number at merge time; it is **18** in this tree. If another branch merged an 18 first, renumber this
ruling and every "ruling 18" reference in the same commit.

```markdown
18. **The study room is animated pixel art on the owner's own bookworm — state art may move, and it still shows only
    real state (owner, 2026-10-01; G176, G107, G125).** The owner: "I've already done here the base model of the
    bookworm i want. Can you iterate with codex sol 6.1 extra high effort all the sprites with the animations? and
    generate the assets like the lamp, extra books, window, environment behind window animated too. Little fly (pixel
    size almost), moving around turned on lamp. Have environemnts for sunny, night, windy, rainy... all animated. You
    will find the bookworm png and 5 emotion states here app/assets/. Make sure to generate everything, have codex
    implement it using computer use in aseprite and add it to the app." The binding spec is
    [`2026-10-01-bookworm-sprites-spec.md`](../specs/2026-10-01-bookworm-sprites-spec.md). This amends Track Z's R-Z1
    (its persist list: the held book at room scale in every state, shut eyes when sleeping, red pupils and the drop on
    error; the nightcap retires; the stage dots persist only in the 18 × 18 set), R-Z4, R-Z11 (titles, motion and
    palette: `palette.json`, not `DeskPalette`) and R-Z12, G125 v3's R-A13 and P14, the 2026-09-02 mascot plan's R1
    (nine colours), R3 (the 24-cell grid) and R8 (250–800 ms), and the sprites brief's §4, §5 and §9 where named below.
    R-Z2, R-Z3, R-Z5, R-Z7, R-Z8, R-Z9, R-Z10, R-Z13, R-Z14, P10, P11, P12, P13 and rulings 8–10 and 12 are untouched.
    - **R-BW1 — the worm is the owner's reference.** `app/CicadaApp/Art/sprites/bookworm-2026-10-01/reference/` (the
      base model, five emotions and the menu-bar design) is the approved design: a green bookworm, charcoal-grey
      glasses, a blue book, no antennae. It closes G176 Step 1 (the round-1 directions are superseded) and replaces
      "orange glasses" (brief §4, §9). The book is the character's own in every room-scale state; P10 is about props,
      not the worm. The 18 × 18 set follows the owner's menu-bar design (head, glasses and neck in two colours) and
      shows a book only in `reading`. The nightcap retires (P14), and the room worm drops the stage dots: the stage
      strip, the sentence and VoiceOver carry the stage; the 18 × 18 set keeps them.
    - **R-BW2 — sprites are sheets, not strings.** Sources and Lua generators live in
      `app/CicadaApp/Art/sprites/bookworm-2026-10-01/`; exported PNG sheets + Aseprite JSON (tags, per-frame
      durations, slices) live in `Resources/sprites/` with `sprites.manifest.json` (generator, script, source, date,
      licence, sha256) and a test that checks every hash and that each JSON's tags are exactly the ones the app asks
      for. Sheets load only through `Bundle.cicadaResource`. One `palette.json` is read by the scripts and the tests.
      G127's seam stands: a character is a set of sheets with the same tags.
    - **R-BW3 — frame animation (the Track Z lint amendment brief §4 asked for).** Motion is sprite frames with
      per-frame durations from the sheet, on whole pixels of the one lattice, drawn nearest-neighbour. R-Z4's
      no-transform lint stays for the worm and widens to every room sprite. "≤ 3 frames × 0.12 s" becomes: a beat
      settles within 800 ms (the perk within 400 ms); a transition within 1.6 s; no frame is shorter than 40 ms or
      longer than 4 s; a loop runs 0.4–30 s — `CicadaMotion`'s sprite caps, checked against every sheet. The renderer
      key bound (≤ 256 per size) becomes a bound on frame rects and decoded pixels.
    - **R-BW4 — state art may move (R-Z12 and R-A13 amended).** A state's art may loop — breathing, blinks, page
      flips, z → zz → zzz, the weather's own loop, the fly — because the loop shows a state that is already true. It
      never adds a fact and never speeds up, densifies or brightens with a count, an age or a stage (R-Z3). A mood
      change may play one transition (a yawn into sleep, a stretch out of it) besides the cheer and the weather
      crossfade; a hydrate or a refresh never does (DR-65). Glances, sways, tail flicks and nod-offs inside a state's
      idle loop, and cloud drift inside a weather's loop, are state art (R-Z12's "no glance, no drift" is amended for
      them). Still refused: any flash or strobe (the storm flash), weather driven by a count or the clock, motion with
      no state behind it (mug steam, plant sway), and duration estimates.
    - **R-BW5 — the window: the owner's four weathers, still a total function of the mood (R-Z11).**
      `windowWeather(for:)` and `WindowWeather.all` are unchanged; the titles become Night, Dawn, Sunny (`clear`),
      Partly cloudy (`fair`), Windy (`overcast`), Rainy (`storm`, rain without lightning) and Curtains drawn. The legend
      stays the twin, keeps its header, and shows each weather's key frame. Pixels on the lattice only, never the Meadow
      paintings (DR-13). Ruling 9's occlusion test runs on every frame of every weather.
    - **R-BW6 — no clock.** Nothing in the room, the window or the worm reads the time of day; the room's interior
      palette and the night light stay out of scope (the brief §9 palettes and night light are a later ruling).
    - **R-BW7 — the five emotions map to states, once.** happy → `.happy`, `.digesting` and the cheer; tired →
      `.hungry`; worried (sweat drop, red pupils kept) → `.error`; sad → the shake beat; the base model → `.awake` and
      `.reading`; mad is drawn but unused. Never random, never the clock. The menu bar gets an 18 × 18 set drawn from
      the owner's menu-bar design, with the count badge and stage dots drawn on it in code (G107 R2), and its own
      precedence unchanged.
    - **R-BW8 — the lamp and its fly.** The lamp is redrawn and still means exactly the schedule (R-A3, P11; it never
      previews). The fly is the lit lamp's art: present only while lit, inert, never in the glass or the pile column,
      resting on the shade under Reduce Motion.
    - **R-BW9 — books (P10 holds).** The worm's own book has three covers that change as he picks up the next one;
      the real pile's spines gain a pixel texture by kind (a second cue beside colour; `fitPile` unchanged). No other
      book is drawn: a shelf, cart or bookcase needs a real count and its own design round.
    - **R-BW10 — interaction is unchanged.** The hotspots stay the worm, the lamp and the window; the plant, mug, bean
      bag, wall, rug, cord, scenery and fly stay inert (R-Z2). No click on art starts, cancels or schedules work (R-Z9).
    - **R-BW11 — Reduce Motion, Low Power, unseen.** Under Reduce Motion every sprite shows its key frame (G107 R7)
      and the yawn and stretch do not play; under Low Power every frame plays at half speed; a sprite rests while its
      window cannot be seen or a host pauses it (R-HO7's reader and policy). Each animated layer redraws only at its
      own frame boundaries. **Budget:** the room's summed sprite redraws stay ≤ 30 per second in its worst steady
      state (Rainy + lamp lit + error worm), computed from the sheets (≤ 1,800 `SpriteFrameSchedule` boundaries per
      minute, tested in `SpriteClipTests`); mean CPU with the room frontmost stays ≤ 3 % of one core and within 2
      points of `dev`, measured by the owner on the demo bank before merge.
    - **R-BW12 — how it was made, and the gate.** The owner chose the tool and the model for this job: Codex
      (gpt-6.1-sol, extra-high effort) with computer use in Aseprite. This overrides brief §5's "Computer use in the GUI
      is not needed and is worse" and the handoff's model split for this job only; the small-models rule is otherwise
      unchanged. Parts are hand-correctable in the GUI; every sheet is rebuilt and exported headless so the manifest's
      hashes are reproducible. PR to `dev`; no merge until the owner has reviewed `preview.html` and the composites.
    Revisit R-BW4 or R-BW11 if either half of R-BW11's budget is exceeded or a viewer reports motion discomfort;
    R-BW5–R-BW9 on the owner's word.
```

**Also in `TODO.md`:**

Append a dated note to `:524-526` (the round-2 note):

> "(2026-10-01, ruling 18: the nightcap retired with the owner's own worm; the time-of-day sky stays out.)"

Add a "Where things stand" block after the section header at `:7`, in the style of `:21-41`:

```markdown
**Study room sprites v2 (G176) — built on `feat/study-room-sprites`, 2026-10-xx (PR #n to `dev`; not merged; ruling 18).**
The owner: "Make sure to generate everything, have codex implement it using computer use in aseprite and add it to the
app." Landed: the owner's bookworm as Aseprite sheets (8 room states with every pose and beat, three book covers, the yawn
and the stretch; an 18 × 18 menu-bar set), the room on a 160 × 64 lattice (wall and floor, the window with seven animated
weathers, the lamp and its fly, the bean bag, plant and mug, spine textures), `SpriteLayerView` (frame-boundary
schedule, key frame under Reduce Motion, half speed under Low Power, resting unseen), `sprites.manifest.json` + hash test,
`preview.html`. **Not yet seen live:** the owner's pass on the demo bank, light and dark, 0.8×–1.4×; idle CPU with the
room on screen, measured against `dev`. *Pick up here:* the owner reviews `preview.html` and the composites, then merge;
then the count props and the queue as a room (design rounds).
```

### 8.2 `docs/goals/memory-evolution.md` — edit rows in place; never open a new one

**G176** (`:754`). Append this to its reasoning cell:

> **Step 1 closed by the owner's own design (Rodrigo 2026-10-01: "I've already done here the base model of the bookworm i
> want … Make sure to generate everything, have codex implement it using computer use in aseprite and add it to the
> app").** The reference set (`app/CicadaApp/Art/sprites/bookworm-2026-10-01/reference/`: the base model, five
> emotions and the owner's own menu-bar design) supersedes the round-1 directions. The ask adds per-frame animation for every sprite, a redrawn lamp with a
> pixel-size fly while it is lit, extra books, and the window's environment animated in four named weathers (sunny, night,
> windy, rainy). Rulings: TODO ruling 18 (R-BW1…R-BW12); spec `docs/specs/2026-10-01-bookworm-sprites-spec.md`.
> **Built 2026-10-xx (`feat/study-room-sprites`, PR #n):** sheets + `sprites.manifest.json` + hash test;
> `SpriteLayerView`; the worm's states, poses, beats, covers and transitions; the seven weathers animated; the lamp and
> its fly; spine textures; Reduce Motion / Low Power; `preview.html`. **Not yet seen live:** the owner's pass on the demo
> bank, light and dark, 0.8×–1.4×; idle CPU against `dev`. **Open:** the count props of brief §9, the queue as a room,
> time-of-day palettes and the night light, G175 marks.

Change its status cell to:

> 🛠️ worm, window, lamp built (2026-10-xx, PR #n; ruling 18) · 🔲 count props, the queue as a room (design rounds)

**One dated line on each related row** (same privacy rules):
- **G107** (`:686`): "2026-10-01 (TODO ruling 18): the worm moves from code-defined 24 × 24 grids to the owner's design
  as Aseprite sheets played per frame (room 64 × 48, menu bar 18 × 18); R-Z4's no-transform rule stays and widens to
  every sprite; the beat and interval caps become ruling 18's sprite caps; the nightcap retires; the estimate deferral
  and the state × response matrix stand."
- **G125** (`:703`): "v6 (2026-10-01, ruling 18): the room is a 160 × 64 lattice at 3 pt per cell at 1.0; the window
  keeps R-Z11's total mood function with the owner's names (Sunny, Windy, Rainy) and animated loops; state art may loop
  (R-Z12 amended); the lamp keeps its meaning and gains its fly; P10 holds; no clock."
- **G127** (`:706`): "2026-10-01: a character is now a set of Aseprite sheets with the tags `BookwormArt.requiredTags`
  names — a skin is a new set of sheets, never new code."
- **G175** (`:753`): unchanged. Marks did not ship.

### 8.3 `docs/design/DESIGN_RULES.md` §9 — append (the log is append-only)

```markdown
- **2026-10-01: The study room's sprites play per frame from their sheets (owner: "all the sprites with the animations"; TODO ruling 18 — R-BW3, R-BW4, R-BW11; DR-61, DR-66, DR-13).** Frame timings are data in each sheet's JSON, read by one `SpriteLayerView` / `BookwormView` clock that fires only at frame boundaries; `CicadaMotion` spells the caps (shortest and longest frame, loop range, beat ≤ 800 ms, perk ≤ 400 ms, transition ≤ 1.6 s, the Low Power slowdown). The weather crossfade stays 0.4 s. Reduce Motion holds each sprite's key frame — the worm's R7, kept for the room rather than DR-66's gentler profile, because a sprite's key frame already carries its state — and the sprites rest while their window cannot be seen, like Home's band (R-HO7). Nothing painted enters the room (DR-13): the environment behind the window is pixel art on the lattice.
```

### 8.4 `docs/architecture/app.md`

- **Sleep page — the study room (`:378-414`).**
  - Replace "**Two kinds of art (R-Z1):** *state art* — the mood's frames, the lamp (= the schedule), the pile, and the
    window's **weather** …" so it names the sprite sheets, the 160 × 64 lattice (3 pt per cell at 1.0), the window's
    seven animated weathers with the new titles, the lamp's fly, and the bean bag.
  - Replace the closing "Refused: autonomous beats with no fact behind them, cloud drift, a storm flash, duration
    estimates, …" with: "Refused: motion with no state behind it (mug steam, plant sway), a flash or strobe in any
    weather, a count or the clock driving the window, duration estimates, and any price or plan figure outside Details
    and the engine menu (TODO ruling 12). State art loops (ruling 18)."
- **Mascot states (G107) (`:459-474`).**
  - Replace "every beat is ≤ 3 frames × 0.12 s; a hop is a whole-cell shift (a capped state crouches instead — the
    nightcap owns the grid's headroom)" and "the page's reachable set is ≤ 256 keys per size and the wipe bound is 1024"
    with: "the worm is the owner's design as Aseprite sheets (`Resources/sprites/bookworm-<state>`, 64 × 48; the menu
    bar's `bookworm-small`, 18 × 18, with the badge and stage dots drawn in code); a beat settles within 800 ms, a perk
    within 400 ms, and the yawn and stretch within 1.6 s (ruling 18); tags are derived from `BookwormLook.keySegment`
    and tested to match each sheet exactly; reading cycles three book covers on its own loop."
  - Keep the matrix sentence.
- **Settings → General (`:70-82`).** At `:74` only (the *Show in menu bar* sentence), "hides the menu-bar bookworm"
  becomes "hides the 18 × 18 menu-bar bookworm (ruling 18)". Leave `:82` (the Sleep-button note) as it is.
- **Graphite and Meadow (`:561-565`).** After the painted-art provenance sentence, add: "Pixel sprites carry the same
  provenance in `Resources/sprites/sprites.manifest.json` (script, source, sha256), checked by `SpriteAssetTests`."
- **Motion sentence (`:569-571`).** Add: "Sprites play per frame from their sheets within `CicadaMotion`'s sprite caps
  (ruling 18)."

### 8.5 One-clause rail edit, `CLAUDE.md:248`

Change "every duration is spelled in `CicadaMotion`." to:

> "every duration is spelled in `CicadaMotion` (a sprite's frame timings are data in its sheet, inside `CicadaMotion`'s
> sprite caps — TODO ruling 18)."

Then run `api/tests/test_claude_md_size.py`; the file is ~22.5 KB against the 60,000-character cap.

### 8.6 `docs/design/ART_DIRECTION.md`, BRIEF and handoff

- **`ART_DIRECTION.md`.** Add one dated line under its scope note (`:3-8`): "2026-10-01: pixel sprites
  (`Resources/sprites/`) are out of this document's scope; their direction lives in
  `app/CicadaApp/Art/sprites/bookworm-2026-10-01/README.md` and ruling 18. The painted-meadow negatives (no animals,
  no weather event) do not apply to them."
- **BRIEF.** Add "## 11. The owner's own worm (2026-10-01) — wins over §4, §5, §9 and §10 where they differ". Quote
  §0's words; point to this spec and ruling 18. Note "orange glasses" → charcoal, headless-only → computer use plus
  headless export, Step 1 → closed.
- **Handoff prompt** (`docs/specs/2026-09-29-study-room-sprites-handoff-prompt.md`). Edit it in the same commit, dated
  2026-10-01: STEP 1 (`:13-36`) becomes "the worm is approved: the reference set; see the 2026-10-01 spec", and "Author
  everything headless" (`:85`) becomes R-BW12's rule.

---

## §9. The three Codex run briefs

**Every run's preamble.**
- Read `CLAUDE.md`, `docs/goals/working-method.md` and this spec in full.
- Confirm the toolchain: `"${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}" --version` prints
  `Aseprite 1.3.18.6-dev`.
- Confirm the baseline: `cd app/CicadaApp && swift test` passes before you start. Record the numbers; never copy a
  remembered count.
- Use computer use for Aseprite only, under §10.6's protocol, and confirm it works before you rely on it (§10.6 step 0).
  **Every pixel that ships must be reproducible** from `ART/parts/*.aseprite` + `ART/lua/*` by `ART/tools/export_all.sh`.
- End with a report: what was built, every self-check box with its evidence (paths of the QA images you looked at), the
  numbers you measured, and anything deferred.

### Run A — the worm (room scale and 18 × 18)

**Inputs.** `ART/reference/*`, §1–§4, §10. **Outputs:**
- `ART/palette.json` (worm, fx and book groups), `ART/README.md` (first draft);
- `ART/lua/{ase_helpers,test_helpers,seed_parts,worm_scripts,build_worm,build_worm_small,dev_loop}.lua`;
- `ART/tracing/*`, `ART/parts/worm-parts.aseprite`, `ART/parts/worm-small-parts.aseprite`;
- `ART/demo/bookworm-mad-demo@6x.gif` (§4.5);
- `ART/src/bookworm-*.aseprite` (9 files);
- `ART/tools/{export_all.sh,verify.py}` (worm sheets only for now; Run B extends both);
- `RES/bookworm-*.{png,json}` (9 sheets).

**Steps:**

1. **Helpers.**
   - Write `lua/ase_helpers.lua`: §10.2 verbatim, plus §10.3's additions.
   - Write `lua/test_helpers.lua` covering every helper, including the additions.
   - Run it headless until it exits 0.
2. **Tracing bases.**
   - Run `H.loadReference(ref, 70, 47, pal)` and a 56 × 38 variant into `tracing/` on a hidden `ref` layer.
   - Compare them with §1.4/§1.5. Where they disagree, the reference image decides; look at it at 100% in the GUI.
   - Run `lua/seed_parts.lua` once (headless) to create the part files with every §3.4 tag (§3.1). From here on, only
     hand edits change them.
3. **The base figure at 56 × 38.** Hand-clean it in `parts/worm-parts.aseprite` (tag `body.sit` + `eyes.center` +
   `book.closed` + `brows.none` + `mouth.none`), driving the Aseprite GUI under computer use (pencil at 1 px, the
   palette locked to `palette.json`). Fix §1.5's known defects. **Craft bar:**
   - 1-px outlines with clean 1:1 or 2:1 steps and no doubled corners or jaggies;
   - no orphan pixels, no pillow shading, no banding;
   - light from the upper left, consistent everywhere;
   - the reference's proportions: big head and glasses, book on the left, the tail up at the right;
   - the glasses' K / D-L / K ring read at 1×.
4. **Every part family** of §3.4. Draw the brows from §1.6's stamps, rescaled by hand.
   - Breathing leads with the torso and the head follows one frame later.
   - Hops use a crouch (anticipation) and a squash on landing.
   - Use colour steps (sub-pixel) where 1 px is too much.
5. **`lua/worm_scripts.lua`.** §3.5–§3.7 as data, one table per tag (frames as part lists, offsets and ms).
   `build_worm.lua` composes every state sheet from it:
   - layers per §3.3;
   - tags last;
   - slices `ink`, `eye`, `lensL` and `lensR`;
   - reading covers 2 and 3 by `H.recolor` with §3.5's cyclic map;
   - `H.assertPalette` on every sprite;
   - asserts for §4.4's marks and §3.3's caps;
   - write `qa/registry.json`.
6. **The 18 × 18 set.** Redraw `bookworm-small` by hand from `reference/bookworm_menu_bar.png`, per §1.7 and §3.7. Never
   downsample. Render `ART/demo/bookworm-mad-demo@6x.gif` (awake `idle` with `brows.mad`).
7. **Export and verify.** Run `BUILDS="build_worm build_worm_small" STAGE=worm tools/export_all.sh`; it ends with
   `verify.py --worm-only`.
8. **GUI review loop (§10.6).** For each `src/bookworm-*.aseprite`:
   - open it, play every tag (Enter), and step the transitions frame by frame at zoom 4 (800%);
   - fix what reads wrong in the parts, rebuild headless, and reopen.
9. **QA renders.** Look at every `qa/<sheet>/<tag>@6x.gif` and the 18 × 18 `@8x` light/dark boards yourself.

**Acceptance (A):**
- [ ] The 9 worm sheets exist in `RES/` with exactly §3.3's tags (verify.py green), 64 × 48 / 18 × 18 frames, binary
  alpha and palette-locked pixels.
- [ ] Every duration is inside the caps. Gaze families and reading covers share durations frame for frame.
- [ ] Every frame 0 carries its marks (§4.4). Sleeping's `idle` and `talk.center` never show open eyes; error always
  shows red pupils and the drop; every room frame shows ≥ 20 book px (transitions included). No frame outside a lift
  (`perk.*`, `eager`, `cheer.center`) moves the base row off canvas row 47, and no lift exceeds +3.
- [ ] Reading: the eyes track lines left to right with a line return (verify.py's centroid check); three page flips at
  uneven spacing; three blinks at uneven gaps; a real close; the cover-k book is tucked behind the body while cover k+1
  rises from behind it (never cut by the canvas edge); the next tag starts with k+1 open.
- [ ] Blinks are irregular in awake, happy, curious and reading (verify.py's blink check).
- [ ] Sleeping: slow breath (4 s per breath); z → zz → zzz rising, growing and fading by palette steps, every glyph on
  §3.5's path and inside the z box; no alpha.
- [ ] Yawn and stretch read as a yawn and a stretch at 1×. Cheer has anticipation, a peak and a squash. The gulp shows
  the scrap going down the neck.
- [ ] The 18 × 18 set is the owner's menu-bar design (compare it side by side with `reference/bookworm_menu_bar.png`)
  and is legible at 1× on light and dark (the human look recorded in the report). Rows 16–17 are clear in every tag,
  and the curious badge corner carries no glasses ink.
- [ ] `BUILDS="build_worm build_worm_small" STAGE=worm tools/export_all.sh` run twice gives identical bytes.
- [ ] No file outside the worktree was written, except Aseprite's own `files/*.ini` side effect.

**Self-check (A):**
- [ ] View every export at @6x and the 18 × 18 set at @8x (Read tool on the PNG/GIF, or the GUI at 800%).
- [ ] Play every GIF; watch the reading loop end to end twice (≈ 44 s).
- [ ] Compare the base `sit` frame side by side with `reference/bookworm.png` at matching size: same silhouette, same
  glasses, same book.
- [ ] Compare each emotion's brows with its reference file.
- [ ] Look at the 18 × 18 on `#F6F6F6` and `#1E1E1E` at 1× and 2×.
- [ ] Run `swift test` (unchanged code), still green.

### Run B — the room, the weather, the fly, the spines, and the pipeline end to end

**Inputs.** Run A's outputs, §2, §3, §5, §6, §10. **Outputs:**
- `ART/palette.json` (room, weather, fly and spine groups added), `ART/room-plan.json` (shape in §2.2),
  `ART/room-motion.json` (§5.2);
- `ART/parts/room-parts.aseprite`;
- `ART/lua/{build_room,build_weather,build_spines}.lua`;
- `ART/src/room-*.aseprite` (9 files);
- `RES/room-*.{png,json}` (9 sheets);
- `ART/tools/{manifest.py,make_preview.py}` and the finished `verify.py`/`export_all.sh`;
- `RES/sprites.manifest.json`, `ART/preview.html`, `ART/README.md` (final).

**Steps:**

1. **Palettes.**
   - Add the room ramps: wall, floor, trim, lamp (dark and lit), bean bag, plant, pot, mug, window wood.
   - Add one ramp per weather sky, plus clouds (`cloud.*`), celestial (`celestial.sun/moon/star`), rain, glass drops,
     tree, leaves, curtains, fly (`fly.body`, `fly.wing`) and spine masks.
   - Props use coloured dark outlines, never `K`.
2. **Backdrop and props.** Draw the backdrop (with §5.5's rug, cord and baseboard bevel) and every prop in
   `parts/room-parts.aseprite` under computer use. Build them with `build_room.lua` at §2.2's canvases, with the `glow`,
   `shade`, `seat`, `glass` and `ink` slices.
3. **Weather.** Build the seven tags per §5.2, with frame-exact periodic motion (positions as integer functions of the
   frame number, so every loop is seamless), and write `ART/room-motion.json`.
4. **Fly.** Build it per §5.4, with the path as a data table of (x, y, ms, glint) checked against the glass rect.
5. **Spines.** Build them per §5.6.
6. **Finish the pipeline.**
   - Finish `verify.py`: §6.2 in full, including the ruling-9 check against Run A's worm sheets.
   - Write `manifest.py` (§6.3) and `make_preview.py` (§6.4).
   - Run the default `tools/export_all.sh` (every build, `STAGE=all`) end to end, twice, and confirm the bytes are
     identical.
7. **GUI review loop** (§10.6) for every room sheet. Then open `preview.html` in a browser by file path, with no
   server. Play the room view for every mood × lamp state at 3× and 4×.

**Acceptance (B):**
- [ ] All 18 sheets and the manifest exist; verify.py is green, including ruling 9 per frame, the fly checks, the storm
  luminance check and the `room-motion.json` seam check.
- [ ] The seven weathers read at 1× as night, dawn, sunny, partly cloudy, windy, rainy and curtains drawn, each from
  its key frame alone.
- [ ] Rain has no flash (the luminance check, and by eye). No loop shows a seam jump (the seam check, and three loops
  of each watched).
- [ ] The lit room glows warm around the lamp. The fly is 0–2 px on every frame (≥ 1 on frame 0), circles above and
  around the shade and lands, and never enters the glass or the pile column.
- [ ] The backdrop ends at col 109 with the trim, and nothing is painted at col ≥ 110.
- [ ] The worm sits on the bean bag (baseline equals `seat`), with no gap and no overlap artefacts. The plant is under
  the sill.
- [ ] `preview.html` works offline from `file://` and shows every tag at real timings, Reduce Motion (key frames), Low
  Power (×2) and the room composite.
- [ ] Manifest hashes match the files, no path in any JSON names `/Users/` or `/private/`, and total sprite bytes are
  ≤ 6 MiB.
- [ ] The default `tools/export_all.sh` run twice gives identical bytes.

**Self-check (B):**
- [ ] View every room export at @6x and each weather's GIF at @6x.
- [ ] View the room composite at 3× and 4× for all 7 moods × lit/dark: 28 images. Look at each one.
- [ ] Watch the fly loop at 8× once, frame by frame.
- [ ] Recount the palette: every pixel is in `palette.json` and no reserved hex is used.
- [ ] Run `swift test` (unchanged code), still green.

### Run C — app integration

**Inputs.** Runs A and B outputs, §2, §3, §4, §5, §7, §8. **Outputs:** the Swift changes of §7, the tests of
§7.6–§7.7, and the docs of §8.

**Steps** (each followed by `swift test --filter` on the files it touches):

1. `S/Sprites/*` (decoder, sheet, clip, playback, layer view) and their tests.
2. `BookwormArt`, `BookwormSize` and `BookwormOverlays`; `BookwormRenderer` on the small sheet; the menu bar's chained
   timer. Tests.
3. `BookwormView` on the sprite clock, with the transitions plumbing in `RoomModel` and `WormStage`. Tests.
4. `RoomLattice`, `DeskScene` (plan, `RoomArt`, `DeskSceneView` on `SpriteLayerView`s), `DeskHotspots` from slices,
   `WindowWeather` titles and thumbnails, `BookPile` `referenceCell` + `SpineTexture`. Delete `DeskSceneSprites.swift`
   and the worm grids. Tests and lints per §7.5–§7.6.
5. **Measure and pin.** Write the hotspot rects at 3 pt and the gaze edges into the tests.
6. **Full suite.** `cd app/CicadaApp && swift test` → 0 failures. Then
   `PYTHONDONTWRITEBYTECODE=1 <worktree>/../../api/.venv/bin/python -m pytest api/tests/test_claude_md_size.py -q -p no:cacheprovider`
   (the main checkout's venv, run from `<worktree>`; with no `.pyc` and no cache it reads, never writes, the main
   checkout), after §8.5.
7. **Composites.** `CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests` writes the room composites for
   every mood × lamp state at 1.0 and 1.4 into `$TMPDIR`. Look at every one.
8. **Size checks.**
   - Build the app with `make app` (`app/CicadaApp/bundle.sh`; it builds in the worktree and installs nothing). Do not
     launch it against the owner's backend.
   - Confirm `Cicada.app/Contents/MacOS/CicadaApp_CicadaApp.bundle/Contents/Resources/sprites/` holds the 36 sheet
     files plus `sprites.manifest.json` (`app/CicadaApp/bundle.sh:32`, `:43-58`):
     `find "$(cd app/CicadaApp && swift build --show-bin-path)/Cicada.app" -path '*sprites/*'`.
   - Check the intake panel's and the empty state's new worm sizes in the view code, and with an Xcode preview or a
     snapshot test if one exists.
9. **Docs.** Write every §8 text, with the PR number left as `#n` for the orchestrator. Draft the PR body: its first
   line is Q1 (§0's deferral, §11), and it cites DR-13, DR-50, DR-61, DR-65, DR-66 and ruling 18 (`CLAUDE.md`: a UI PR
   cites the DR ids it applies).

**Acceptance (C):**
- [ ] `swift test`: 0 failures. Every §7.6 test is changed as specified and every §7.7 test exists. No test was deleted
  without the replacement §7.6 names.
- [ ] The state machine, matrix, `RoomModel` scheduling, hotspot keys, labels, popovers, VoiceOver order and drop
  target are byte-for-byte the same, except where §7 says.
- [ ] Reduce Motion: every sprite shows its key frame; no beats, yawn or stretch; the weather jumps.
- [ ] Low Power: ×2 durations. Window occluded or minimised: no ticks (the `SceneRunPolicy` test extended to sprites).
- [ ] The menu bar animates per frame on a chained timer, is 18 × 18 and not a template, and shows the badge and dots.
- [ ] The status item carries a VoiceOver label naming the state, and its timer schedules nothing while the item is
  hidden or the displays sleep (§7.3).
- [ ] A cycle that completes plays the cheer and no stretch in both `onChange` orders; a page opened mid-run never
  yawns (`RoomModelTests`).
- [ ] No `duration:` in new Swift, no `Bundle.module`, and no banned hex. The lints are amended exactly per §7.5.
- [ ] The docs of §8 are written; `CLAUDE.md` stays under the cap.
- [ ] The built `.app` contains the sprites.

**Self-check (C):**
- [ ] Look at every composite at 2× (28 images at 1.0 + 1.4 per lamp state).
- [ ] Read the diff of `StudyRoom.swift`, `RoomModel.swift` and `MenuBarManager.swift` line by line against §7.3.
- [ ] Run `swift test` twice (no flakes from timing tests; inject dates, never sleep in tests).
- [ ] Grep `Sources/` for `DeskSceneSprites`, `BookwormSprites.frames` and `reactionInterval`: zero hits.

---

## §10. Aseprite: the verified cheat sheet, the helper library, and the GUI protocol

**Verified 2026-10-01** against this Mac's build (headless): `Aseprite 1.3.18.6-dev`, `app.apiVersion` 41, Lua 5.4,
`app.isUIAvailable == false` under `-b`. A headless run takes about 0.05 s, and 1.7 M `drawPixel` calls take 0.12 s.
GUI facts (§10.6) come from the app's bundled `data/gui.xml` and `data/strings/en.ini` and are **unverified in the
running GUI**: check them on your first screenshot.

### 10.1 CLI and API facts that bite

**CLI:**
- `aseprite -b --script-param k=v --script x.lua`: **params must come before `--script`** (after it they are dropped).
  The script reads `app.params.k`.
- **Exit codes.** `error()`/`assert` exits 255; `return n` exits with n; a missing script exits 255. **A missing input
  file for a CLI export exits 0** and only prints `File not found`, so check that outputs exist.
- `--sheet s.png --data s.json --format json-array --sheet-pack --list-tags --list-slices` works. **`--sheet-pack`
  always de-duplicates identical frames**, so several `frames[]` share one rect.
- **`--tag X` before the filename filters a sheet, but `meta.frameTags` still lists every tag with whole-sprite indices**,
  so never use `--tag` for an app sheet. After the filename it is ignored for `--sheet`; for `--save-as` it still filters
  (verified: 2 of 5 frames, with their own delays), which §6.2's GIF command relies on. `--split-tags` with `--sheet` is
  broken.
- `--trim` changes `frame.w/h` and collapses position-only differences. Do not use it.
- `--scale 6 --save-as x.gif` with `--tag t` gives real delays (centiseconds, so 1001 ms becomes 1000), `loop=0` and
  nearest-neighbour scaling. **GIFs ignore tag direction** (all our tags are forward).
- `--scale 6 --save-as x.png` on a multi-frame sprite writes `x1.png`, `x2.png`, …, numbered from 1.
- Hidden layers are left out of sheets, GIFs and `meta.layers`.

**API:**
- `Sprite(w,h,ColorMode.RGB)` starts with 1 layer, 1 frame and 1 empty cel.
- **Frames.** `spr:newEmptyFrame()` appends. `spr:newFrame()` appends a copy (cels and duration included).
  `spr:deleteFrame(n)` works.
- **Durations** are whole ms, truncated, clamped 1..65535. Set them as `(ms + 0.5)/1000`.
- **Appending a frame after a tag that ends on the last frame grows the tag.** Create tags last.
- **Cels.** `spr:newCel(layer, frame, image, Point)` copies the image (never linked) and replaces the existing cel.
- **Images.**
  - `drawPixel`/`putPixel` **replace** the pixel, with no blending.
  - `img:drawImage(src, Point)` **blends**, and transparent source pixels leave the destination unchanged. `putImage`
    also skips transparent pixels in this build. Erase with `drawPixel(x,y,0)` or `img:clear(rect)`.
  - `img:resize{width=,height=,method='nearest'}` is nearest by default.
  - Also available: `img:clone()`, `img:saveAs()`, `img:pixels()`, `img:isEmpty()`, `img:shrinkBounds()`,
    `img:drawSprite(spr, frame)` (flattens) and `Image{fromFile=path}`.
- **Layers.** `layer.isReference` is **read-only** (setting it raises); use a hidden layer. **Reading a field an object
  lacks raises** ("Field frames does not exist").
- **Tags.** `spr:newTag(from,to)` has `.name`, `.aniDir` (`AniDir.FORWARD` and others), `.repeats`, `.color` and `.data`.
- **Slices.** `spr:newSlice(Rectangle(...))` exports under `--list-slices` as
  `{"name","keys":[{"frame","bounds":{x,y,w,h}}]}`.
- **App.** `app.open(path)` works, and so do `app.sprite = spr` / `app.frame = spr.frames[n]`. **`app.command.*` acts on
  the active sprite**, so set `app.sprite` first. `app.transaction('name', fn)` works in batch.
- **Exports from Lua.** `app.command.ExportSpriteSheet{ui=false, …}` produces the same output as the CLI;
  `app.command.SaveFileCopyAs{ui=false, filename='x.gif', tag='t', scale=6}`.
- **Built-ins.** `json.encode`/`json.decode` are built in (numbers decode as floats). `io` and `os` are available. **The
  running script's folder is first on `package.path`**, so `require('ase_helpers')` works from any working directory.
- **Shell.** `aseprite --shell` with piped stdin works headless, one chunk per line (use globals, not `local`).

**JSON shape (real export):**
- `frames[]`: `{filename, frame{x,y,w,h}, rotated, trimmed, spriteSourceSize, sourceSize{w,h}, duration}`.
- `meta`: `{app, version, image, format:"RGBA8888", size{w,h}, scale, frameTags:[{name, from, to, direction, color,
  data?, repeat?}], layers?, slices:[…]}`.
- `from`/`to` are 0-based and inclusive. `repeat` is a **string** and appears only when > 0.

### 10.2 `ART/lua/ase_helpers.lua` (verified library; copy verbatim)

```lua
-- ase_helpers.lua — small, verified helper library for authoring pixel-art sprites in Aseprite Lua.
-- Verified 2026-10-01 against Aseprite 1.3.18.6-dev (app.apiVersion 41), headless:
--   /Applications/Aseprite.app/Contents/MacOS/aseprite -b [--script-param k=v ...] --script build.lua
-- Load it from a script in the same folder with:  local H = require('ase_helpers')
-- (Aseprite puts the running script's folder first on package.path.)
--
-- Conventions
--   * Sprites are RGB. Index 0 of the sprite palette is transparent; palette keys are 1-char strings.
--   * Every opaque pixel is alpha 255 and a palette colour (H.assertPalette checks it).
--   * Durations are integer milliseconds at this API; Aseprite stores whole ms (1..65535).
--   * Tags are created only AFTER all frames exist: appending a frame after a tag that ends on the
--     last frame silently grows that tag (verified). Use H.recorder, or call H.tag at the very end.

local H = {}
H.VERSION = '2026-10-01'

local pc = app.pixelColor

----------------------------------------------------------------------------------------------- colours
-- '#RRGGBB', 'RRGGBB' or '#RRGGBBAA' -> r, g, b, a
function H.hex(h)
  h = h:gsub('^#', '')
  assert(#h == 6 or #h == 8, 'bad hex colour: ' .. h)
  local r, g, b = tonumber(h:sub(1, 2), 16), tonumber(h:sub(3, 4), 16), tonumber(h:sub(5, 6), 16)
  local a = #h == 8 and tonumber(h:sub(7, 8), 16) or 255
  return r, g, b, a
end

-- Palette from a table. Accepts either an ordered list
--   { {'g', '#6FCF6A', 'body'}, {'o', '#2B2423', 'outline'}, ... }
-- or a map { g = {'#6FCF6A', 'body'}, ... } (keys then sorted for a stable order).
-- Returns pal = { keys = {...}, px = {key -> pixel u32}, color = {key -> Color}, index = {key -> 1..n},
--                 hex = {key -> '#RRGGBB'}, role = {key -> string} }
function H.palette(entries)
  local list = {}
  if entries[1] ~= nil then
    for _, e in ipairs(entries) do list[#list + 1] = { e[1], e[2], e[3] or '' } end
  else
    for k, v in pairs(entries) do list[#list + 1] = { k, v[1], v[2] or '' } end
    table.sort(list, function(a, b) return a[1] < b[1] end)
  end
  local pal = { keys = {}, px = {}, color = {}, index = {}, hex = {}, role = {} }
  for i, e in ipairs(list) do
    local k = e[1]
    assert(type(k) == 'string' and #k == 1 and k ~= '.' and k ~= ' ', 'palette key must be 1 char, not . or space: ' .. tostring(k))
    assert(pal.px[k] == nil, 'duplicate palette key ' .. k)
    local r, g, b, a = H.hex(e[2])
    pal.keys[i] = k
    pal.px[k] = pc.rgba(r, g, b, a)
    pal.color[k] = Color { r = r, g = g, b = b, a = a }
    pal.index[k] = i
    pal.hex[k] = string.format('#%02X%02X%02X', r, g, b)
    pal.role[k] = e[3]
  end
  return pal
end

-- Read { "colors": [ {"key": "g", "hex": "#6FCF6A", "role": "body"}, ... ] } (the shared palette file).
function H.paletteFromJson(path)
  local t = H.readJson(path)
  local entries = {}
  for _, c in ipairs(t.colors) do entries[#entries + 1] = { c.key, c.hex, c.role } end
  return H.palette(entries)
end

-- Install pal as the sprite palette: index 0 transparent, then the keys in order.
function H.applyPalette(spr, pal)
  local p = Palette(#pal.keys + 1)
  p:setColor(0, Color { r = 0, g = 0, b = 0, a = 0 })
  for i, k in ipairs(pal.keys) do p:setColor(i, pal.color[k]) end
  spr:setPalette(p)
end

function H.writePaletteJson(path, pal, extra)
  local t = extra or {}
  t.colors = {}
  for _, k in ipairs(pal.keys) do t.colors[#t.colors + 1] = { key = k, hex = pal.hex[k], role = pal.role[k] } end
  H.writeJson(path, t)
end

----------------------------------------------------------------------------------------------- images
function H.image(w, h)
  local im = Image(w, h, ColorMode.RGB)
  im:clear() -- fully transparent
  return im
end

-- One pixel, bounds-checked. `key` is a palette key, or a raw pixel value (number).
function H.px(im, x, y, pal, key)
  if x < 0 or y < 0 or x >= im.width or y >= im.height then return end
  local v = type(key) == 'number' and key or pal.px[key]
  assert(v ~= nil, 'unknown palette key ' .. tostring(key))
  im:drawPixel(x, y, v) -- drawPixel REPLACES (no blending), so alpha stays exact
end

function H.erase(im, x, y)
  if x >= 0 and y >= 0 and x < im.width and y < im.height then im:drawPixel(x, y, 0) end
end

function H.rect(im, x, y, w, h, pal, key)
  for yy = y, y + h - 1 do for xx = x, x + w - 1 do H.px(im, xx, yy, pal, key) end end
end

-- Bresenham line, whole pixels, inclusive ends.
function H.line(im, x0, y0, x1, y1, pal, key)
  local dx, dy = math.abs(x1 - x0), -math.abs(y1 - y0)
  local sx, sy = x0 < x1 and 1 or -1, y0 < y1 and 1 or -1
  local err = dx + dy
  while true do
    H.px(im, x0, y0, pal, key)
    if x0 == x1 and y0 == y1 then break end
    local e2 = 2 * err
    if e2 >= dy then err = err + dy; x0 = x0 + sx end
    if e2 <= dx then err = err + dx; y0 = y0 + sy end
  end
end

-- Stamp a grid of strings (one char = one pixel = one palette key). '.' and ' ' are transparent
-- (left untouched); '_' ERASES (writes transparent). opts.map = {char -> key} remaps chars;
-- opts.flipX = true mirrors horizontally. Unknown chars raise an error (catches typos).
function H.stamp(im, rows, x, y, pal, opts)
  opts = opts or {}
  local w = 0
  for _, r in ipairs(rows) do if #r > w then w = #r end end
  for j, row in ipairs(rows) do
    for i = 1, #row do
      local ch = row:sub(i, i)
      local tx = opts.flipX and (x + w - i) or (x + i - 1)
      if ch == '_' then
        H.erase(im, tx, y + j - 1)
      elseif ch ~= '.' and ch ~= ' ' then
        local key = (opts.map and opts.map[ch]) or ch
        assert(pal.px[key] ~= nil, string.format('unknown char %q at row %d col %d', ch, j, i))
        H.px(im, tx, y + j - 1, pal, key)
      end
    end
  end
  return im
end

-- A new image sized to the grid (width = longest row).
function H.grid(rows, pal, opts)
  local w = 0
  for _, r in ipairs(rows) do if #r > w then w = #r end end
  return H.stamp(H.image(w, #rows), rows, 0, 0, pal, opts)
end

-- Composite src over dst at (x, y). Transparent src pixels leave dst untouched (verified);
-- semi-transparent ones blend, so keep art binary-alpha.
function H.paste(dst, src, x, y)
  dst:drawImage(src, Point(x or 0, y or 0))
  return dst
end

-- Nearest-neighbour enlargement (Image:resize defaults to nearest; verified pixel-exact vs Pillow NEAREST).
function H.scaled(im, n)
  if n == nil or n == 1 then return im:clone() end
  local out = im:clone()
  out:resize { width = im.width * n, height = im.height * n, method = 'nearest' }
  return out
end

-- Snap an image to the palette: alpha < alphaCut (default 128) -> transparent, else the nearest
-- palette colour (squared RGB distance) at alpha 255. Use it to turn a painted/AI reference that was
-- nearest-downsampled to the grid into a palette-locked tracing base (then clean it by hand).
function H.quantize(im, pal, alphaCut)
  alphaCut = alphaCut or 128
  local out = H.image(im.width, im.height)
  local cache = {}
  for it in im:pixels() do
    local v = it()
    if pc.rgbaA(v) >= alphaCut then
      local rgb = v & 0x00FFFFFF
      local best = cache[rgb]
      if not best then
        local r, g, b = pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v)
        local bestD = math.huge
        for _, k in ipairs(pal.keys) do
          local q = pal.px[k]
          local dr, dg, db = r - pc.rgbaR(q), g - pc.rgbaG(q), b - pc.rgbaB(q)
          local d = dr * dr + dg * dg + db * db
          if d < bestD then bestD, best = d, q end
        end
        cache[rgb] = best
      end
      out:drawPixel(it.x, it.y, best)
    end
  end
  return out
end

-- Load a PNG as a grid-sized tracing image: nearest-downsample to (w, h), then H.quantize when pal given.
function H.loadReference(path, w, h, pal)
  local im = Image { fromFile = path }
  im:resize { width = w, height = h, method = 'nearest' }
  if pal then return H.quantize(im, pal) end
  return im
end

-- Flattened render of one frame (all visible layers), as a new Image.
function H.flatten(spr, frameNumber)
  local im = Image(spr.width, spr.height, spr.colorMode)
  im:clear()
  im:drawSprite(spr, frameNumber)
  return im
end

----------------------------------------------------------------------------------------------- sprites
local fresh = setmetatable({}, { __mode = 'k' }) -- sprites whose frame 1 is still unused

-- New RGB sprite with pal installed and the layer stack created back to front
-- (layerNames default {'base'}). Returns spr, layersByName.
function H.newSprite(w, h, pal, layerNames)
  local spr = Sprite(w, h, ColorMode.RGB)
  if pal then H.applyPalette(spr, pal) end
  local layers = H.layers(spr, layerNames or { 'base' })
  fresh[spr] = true
  return spr, layers
end

-- Top-level layer by name, or nil.
function H.findLayer(spr, name)
  for _, l in ipairs(spr.layers) do if l.name == name then return l end end
  return nil
end

-- Create the layer stack once, BACK TO FRONT: H.layers(spr, {'room', 'worm', 'book', 'fx'}).
-- The first name renames the sprite's existing bottom layer. Do this before adding frames: layers are
-- never created implicitly, because a Lua table's pairs() order is arbitrary and would scramble the
-- stack (verified: an implicit-create version produced glow/fly/lamp instead of lamp/fly/glow).
function H.layers(spr, names)
  local out = {}
  for i, name in ipairs(names) do
    local l = H.findLayer(spr, name)
    if not l then
      if i == 1 and #spr.layers == 1 then l = spr.layers[1] else l = spr:newLayer() end
      l.name = name
    end
    out[name] = l
  end
  return out
end

-- Existing top-level layer by name; raises if missing (create it with H.layers first).
function H.layer(spr, name)
  local l = H.findLayer(spr, name)
  assert(l, 'no layer named ' .. tostring(name) .. ' (create the stack with H.layers first)')
  return l
end

local function setDuration(frame, ms)
  assert(ms >= 1 and ms <= 65535, 'duration out of range (1..65535 ms): ' .. tostring(ms))
  -- +0.5 ms: Aseprite truncates seconds->ms through a float; plain ms/1000 loses 1 ms on 48 values
  -- between 1001 and 4095 (e.g. 1001 -> 1000). Verified 0 mismatches for 1..5000 with +0.5.
  frame.duration = (ms + 0.5) / 1000
end
H.setDuration = setDuration

function H.ms(frame) return math.floor(frame.duration * 1000 + 0.5) end

-- Put an image in a cel (replaces any existing cel). Image is copied by Aseprite (cels are never linked).
function H.setCel(spr, layerOrName, frameNumber, im, x, y)
  local layer = type(layerOrName) == 'string' and H.layer(spr, layerOrName) or layerOrName
  return spr:newCel(layer, frameNumber, im, Point(x or 0, y or 0))
end

-- Append a frame with a duration and optional cels { layerName = Image | {image=Image, x=, y=} }.
-- The first call on a sprite from H.newSprite reuses frame 1. Returns the frame number.
function H.addFrame(spr, ms, cels)
  local frame
  if fresh[spr] then
    fresh[spr] = nil
    frame = spr.frames[1]
  else
    frame = spr:newEmptyFrame() -- appends at the end (no cels)
  end
  setDuration(frame, ms)
  local n = frame.frameNumber
  for name, c in pairs(cels or {}) do
    if type(c) == 'table' and c.image then H.setCel(spr, name, n, c.image, c.x, c.y)
    else H.setCel(spr, name, n, c, 0, 0) end
  end
  return n
end

-- Append a copy of frame `src` (every layer's cel image cloned; not linked). ms defaults to src's.
function H.copyFrame(spr, src, ms)
  local srcFrame = spr.frames[src]
  assert(srcFrame, 'no frame ' .. tostring(src))
  local dur = ms or H.ms(srcFrame)
  fresh[spr] = nil
  local frame = spr:newEmptyFrame()
  setDuration(frame, dur)
  local function walk(layers)
    for _, l in ipairs(layers) do
      if l.isGroup then walk(l.layers)
      else
        local cel = l:cel(src)
        if cel then spr:newCel(l, frame.frameNumber, cel.image:clone(), cel.position) end
      end
    end
  end
  walk(spr.layers)
  return frame.frameNumber
end

local DIRS = { forward = AniDir.FORWARD, reverse = AniDir.REVERSE, pingpong = AniDir.PING_PONG,
               pingpong_reverse = AniDir.PING_PONG_REVERSE }

-- Create a tag over [from, to] (1-based, inclusive). opts: dir ('forward'|'reverse'|'pingpong'|
-- 'pingpong_reverse'), repeats (0 = infinite), color ('#RRGGBB'), data (string; exported as "data").
-- Call only after ALL frames are appended (see the header note).
function H.tag(spr, name, from, to, opts)
  opts = opts or {}
  assert(from >= 1 and to >= from and to <= #spr.frames, string.format('tag %s range %d..%d outside 1..%d', name, from, to, #spr.frames))
  local t = spr:newTag(from, to)
  t.name = name
  t.aniDir = DIRS[opts.dir or 'forward']
  if opts.repeats then t.repeats = opts.repeats end
  if opts.color then local r, g, b = H.hex(opts.color); t.color = Color { r = r, g = g, b = b } end
  if opts.data then t.data = opts.data end
  return t
end

-- Recorder: append frames under named tags, then create every tag at the end in one go.
--   local rec = H.recorder(spr)
--   rec:start('idle'); rec:frame(780, {body=img}); rec:copy(1, 90); rec:stop()
--   rec:apply()  -- creates the tags
function H.recorder(spr)
  local r = { spr = spr, ranges = {}, open = nil }
  function r:start(name, opts)
    assert(self.open == nil, 'tag ' .. tostring(self.open and self.open.name) .. ' still open')
    self.open = { name = name, opts = opts, from = nil }
  end
  local function note(self, n)
    if self.open then self.open.from = self.open.from or n; self.open.to = n end
    return n
  end
  function r:frame(ms, cels) return note(self, H.addFrame(self.spr, ms, cels)) end
  function r:copy(src, ms) return note(self, H.copyFrame(self.spr, src, ms)) end
  function r:stop()
    assert(self.open and self.open.from, 'stop() with no open tag or no frames')
    self.ranges[#self.ranges + 1] = self.open
    self.open = nil
  end
  function r:apply()
    assert(self.open == nil, 'apply() with an open tag')
    for _, t in ipairs(self.ranges) do H.tag(self.spr, t.name, t.from, t.to, t.opts) end
    return self.ranges
  end
  return r
end

----------------------------------------------------------------------------------------------- checks
-- Every cel pixel is alpha 0, or alpha 255 and a palette colour. Returns true or raises with the first offender.
function H.assertPalette(spr, pal)
  local allowed = {}
  for _, k in ipairs(pal.keys) do allowed[pal.px[k]] = true end
  for _, cel in ipairs(spr.cels) do
    local im = cel.image
    for it in im:pixels() do
      local v = it()
      local a = pc.rgbaA(v)
      if a ~= 0 and (a ~= 255 or not allowed[v]) then
        error(string.format('off-palette pixel #%02X%02X%02X a=%d on layer %q frame %d at %d,%d',
          pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v), a, cel.layer.name, cel.frameNumber,
          it.x + cel.position.x, it.y + cel.position.y))
      end
    end
  end
  return true
end

----------------------------------------------------------------------------------------------- files
function H.writeJson(path, t)
  local f = assert(io.open(path, 'w'))
  f:write(json.encode(t)); f:write('\n'); f:close()
end

function H.readJson(path)
  local f = assert(io.open(path, 'r'))
  local s = f:read('a'); f:close()
  return json.decode(s) -- note: numbers come back as floats (100 -> 100.0)
end

-- Folder of the calling script (for paths next to it).
function H.scriptDir()
  local src = debug.getinfo(2, 'S').source
  return app.fs.filePath(src:sub(1, 1) == '@' and src:sub(2) or src)
end

function H.ensureDir(dir) app.fs.makeAllDirectories(dir) end

-- Save the layered source. saveAs changes spr.filename; use spr:saveCopyAs to keep it.
function H.save(spr, path)
  H.ensureDir(app.fs.filePath(path))
  spr:saveAs(path)
end

-- Packed sheet PNG + JSON array (frames + meta.frameTags/layers/slices) for the whole sprite.
-- opts: type ('packed'|'rows'|'columns'|'horizontal'|'vertical'), columns, trim (default false),
-- shapePadding, borderPadding, filenameFormat (e.g. '{tag}/{tagframe}').
-- Never pass a tag here if the JSON is consumed: meta.frameTags still lists every tag with
-- whole-sprite indices (verified), so the indices would not match the frames array.
function H.exportSheet(spr, pngPath, jsonPath, opts)
  opts = opts or {}
  local types = { packed = SpriteSheetType.PACKED, rows = SpriteSheetType.ROWS, columns = SpriteSheetType.COLUMNS,
                  horizontal = SpriteSheetType.HORIZONTAL, vertical = SpriteSheetType.VERTICAL }
  H.ensureDir(app.fs.filePath(pngPath))
  app.sprite = spr -- app.command.* acts on the active sprite
  app.command.ExportSpriteSheet {
    ui = false, askOverwrite = false,
    type = types[opts.type or 'packed'],
    columns = opts.columns or 0,
    textureFilename = pngPath,
    dataFilename = jsonPath,
    dataFormat = SpriteSheetDataFormat.JSON_ARRAY,
    filenameFormat = opts.filenameFormat,
    borderPadding = opts.borderPadding or 0, shapePadding = opts.shapePadding or 0, innerPadding = 0,
    trim = opts.trim or false, trimSprite = false, mergeDuplicates = opts.mergeDuplicates or false,
    ignoreEmpty = false, splitLayers = false, splitTags = false,
    listLayers = true, listTags = true, listSlices = true,
  }
end

-- Animated GIF of one tag (or the whole sprite when tag is nil) at an integer nearest-neighbour scale,
-- with the real per-frame durations, looping forever. Plays frames in timeline order: a tag's
-- direction/repeats are NOT applied (that needs --play-subtags on the CLI).
function H.exportGif(spr, path, tag, scale)
  H.ensureDir(app.fs.filePath(path))
  app.sprite = spr
  local p = { ui = false, filename = path, scale = scale or 1 }
  if tag then p.tag = tag end
  app.command.SaveFileCopyAs(p)
end

-- PNG of an Image at an integer nearest-neighbour scale (alpha kept).
-- (Two functions, not one: reading a field an object lacks, e.g. image.frames, RAISES
-- "Field frames does not exist" instead of returning nil — verified.)
function H.exportPng(im, path, scale)
  H.ensureDir(app.fs.filePath(path))
  H.scaled(im, scale or 1):saveAs(path)
end

-- PNG of one flattened sprite frame at an integer nearest-neighbour scale.
function H.exportFramePng(spr, frameNumber, path, scale)
  H.exportPng(H.flatten(spr, frameNumber), path, scale)
end

-- Summary table for a timings/ledger JSON: { tags = { {name, from, to (0-based like the sheet JSON),
-- durations_ms = {...}} }, frames = n }.
function H.ledger(spr)
  local out = { frames = #spr.frames, tags = {} }
  for _, t in ipairs(spr.tags) do
    local d = {}
    for f = t.fromFrame.frameNumber, t.toFrame.frameNumber do d[#d + 1] = H.ms(spr.frames[f]) end
    out.tags[#out.tags + 1] = { name = t.name, from = t.fromFrame.frameNumber - 1, to = t.toFrame.frameNumber - 1, durations_ms = d }
  end
  return out
end

return H
```

The exports in this spec run through the CLI in `export_all.sh`. `H.exportSheet` is kept for experiments, and its output
is identical (verified).

### 10.3 Additions (verified headless 2026-10-01 on 1.3.18.6-dev; still add each to `lua/test_helpers.lua`)

Verified: `it(v)` sets a pixel; `spr.slices`, `s.name` and `s.bounds` are readable and `s.name` is settable;
`H.loadPart` returns a tag's first frame; `H.inkBounds` honours cel offsets; `H.flatten` leaves hidden layers out, while
`H.assertPalette` also checks hidden cels.

Append these before `return H`:

```lua
------------------------------------------------------------------------------- additions (2026-10-01 spec)
-- Load one variant (tag) of a hand-drawn part file: the flattened Image of the tag's first frame. Parts are
-- registered on the full canvas (§3.4), so there is no anchor. Cached; opening a sprite per frame would be slow.
H._parts = {}
function H.loadPart(path, tagName)
  local key = path .. '#' .. tostring(tagName)
  local hit = H._parts[key]
  if hit then return hit end
  local spr = app.open(path)
  assert(spr, 'cannot open part file ' .. path)
  local frameNumber, found = 1, (tagName == nil)
  for _, t in ipairs(spr.tags) do
    if t.name == tagName then frameNumber = t.fromFrame.frameNumber; found = true end
  end
  assert(found, 'no tag ' .. tostring(tagName) .. ' in ' .. path)
  local im = H.flatten(spr, frameNumber)
  spr:close()
  H._parts[key] = im
  return im
end

-- Bounding box of opaque pixels as {x, y, w, h}, or nil.
function H.inkBounds(im)
  local x0, y0, x1, y1
  for it in im:pixels() do
    if pc.rgbaA(it()) > 0 then
      x0 = x0 and math.min(x0, it.x) or it.x; y0 = y0 and math.min(y0, it.y) or it.y
      x1 = x1 and math.max(x1, it.x) or it.x; y1 = y1 and math.max(y1, it.y) or it.y
    end
  end
  if not x0 then return nil end
  return { x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
end

function H.unionRect(a, b)
  if not a then return b end
  if not b then return a end
  local x0, y0 = math.min(a.x, b.x), math.min(a.y, b.y)
  local x1, y1 = math.max(a.x + a.w, b.x + b.w), math.max(a.y + a.h, b.y + b.h)
  return { x = x0, y = y0, w = x1 - x0, h = y1 - y0 }
end

-- Union ink over every frame of a sprite (flattened).
function H.spriteInk(spr)
  local u
  for f = 1, #spr.frames do u = H.unionRect(u, H.inkBounds(H.flatten(spr, f))) end
  return u
end

-- Recolour: map is {fromKey -> toKey} in pal, applied in ONE pass from the original pixels, so a cyclic map
-- (cover1 -> cover2 -> cover3 -> cover1) never chains. Returns a new image. Verified: it(v) sets the pixel.
function H.recolor(im, pal, map)
  local px = {}
  for from, to in pairs(map) do px[pal.px[from]] = pal.px[to] end
  local out = im:clone()
  for it in out:pixels() do local to = px[it()]; if to then it(to) end end
  return out
end

-- A named slice on the whole sprite (one key). Verified: slice.name is settable and readable back.
function H.addSlice(spr, name, r)
  local s = spr:newSlice(Rectangle(r.x, r.y, r.w, r.h))
  s.name = name
  return s
end
```

**If a later Aseprite build breaks one of these:** for `it(v)`, write `out:drawPixel(it.x, it.y, to)`; for
`slice.name`, check `spr:newSlice` for a name argument in the API docs (Context7 `/aseprite/aseprite`) before working
around it.

### 10.4 `ART/lua/dev_loop.lua` (rebuild and report, headless only; logic verified in batch)

Run it only with `-b`. Then open the result in the GUI with `open -a Aseprite <file>` (§10.6). Never run `--script`
without `-b`: a script in the GUI raises the "Give full trust" dialog that §10.6 step 1 avoids. The build script it
`dofile`s finds `ART` from its own folder (§3.1), because `app.params.art` is not passed here.

```lua
-- dev_loop.lua — rebuild one sprite from its Lua source and report it, for the GUI review loop.
-- CLI:  aseprite -b --script-param build=<build.lua> --script-param result=<file.aseprite> \
--                  --script-param tag=idle --script dev_loop.lua
-- Then: open -a Aseprite <file.aseprite>     (never --script without -b)
local build = app.params.build or DEV_LOOP_BUILD
local result = app.params.result or DEV_LOOP_RESULT
local tagName = app.params.tag or DEV_LOOP_TAG
assert(build and result, 'dev_loop: need build= and result= (params or DEV_LOOP_* globals)')
for _, s in ipairs(app.sprites) do if s.filename == result then s:close() end end
dofile(build)
local spr = app.open(result)
assert(spr, 'dev_loop: could not open ' .. result)
local frameNumber = 1
if tagName then
  for _, t in ipairs(spr.tags) do if t.name == tagName then frameNumber = t.fromFrame.frameNumber end end
end
app.frame = spr.frames[frameNumber]
print(string.format('dev_loop: %s  frames=%d tags=%d  tag %s starts at frame %d', result, #spr.frames, #spr.tags,
  tostring(tagName), frameNumber))
```

### 10.5 Lessons from round 1 (`feat/worm-directions`; scripts only, never its art)

**Keep:**
- palette-keyed string grids for small parts;
- frame tables with explicit ms;
- one layer per part;
- tags created last;
- irregular 80–90 ms blinks;
- an 18 × 18 drawn separately, not downsampled;
- real verification: the `.aseprite` header's durations, GIF frames against the sheet at NEAREST, binary alpha and the
  palette;
- a page flip anchored at a hinge;
- z's that grow and drift in palette steps;
- a palette remap for variants (our covers).

**Avoid:**
- per-pixel blit or scale loops where `drawImage`/`resize` exist;
- one new sprite per exported PNG;
- JSON built by string concatenation (use `json.encode`);
- output paths that default to `.`;
- `ms/1000`;
- copy-pasted fonts and monolithic files;
- **pose-swapping on a static body** with a 1-px breath and no anticipation, follow-through or squash;
- a turning page drawn over the face;
- z's jumping in big steps;
- dither fades, which read as noise.

### 10.6 Driving the Aseprite GUI under computer use (the review and hand-correction loop)

0. **Confirm computer use works first.** Before relying on it, take one screenshot and check that it shows the screen
   (computer use needs Screen Recording and Accessibility access). If it does not work, stop and report. Never fall
   back to headless-only drawing silently: the owner asked for computer use.
1. **Build headless, review in the GUI.** Every write to `src/` happens from the terminal (`aseprite -b`), so the GUI
   never needs a script and the "Give full trust" security dialog never appears (`data/strings/en.ini:1798-1810`).
   Do not create files in `~/Library/Application Support/Aseprite/scripts/`, and do not change Aseprite's preferences.
2. **Open a file.** `open -a Aseprite ART/src/<name>.aseprite` reuses the running instance; an Aseprite window may
   already be open. On the first screenshot, find the menus: the owner's `aseprite.ini` has `show_menu_bar = false`, so
   expect them in the macOS menu bar.
3. **Play and inspect** (keys from `data/gui.xml`; confirm them on screen):
   - Enter plays/stops inside the tag holding the current frame.
   - Click a tag label to jump to it; Left/Right step frames; Home/End jump to the ends.
   - P opens frame properties (check a duration). F3 toggles onion skin, F7 the preview window.
   - Zoom keys: 4 = 800%, 5 = 1600%, Cmd+0 fits. Review at 800% and compare with the @6x export.
4. **Hand-correct only parts.** Open `ART/parts/<file>.aseprite`, select the variant's tag, and correct with the pencil
   (B) at 1 px, the eraser (E) and the eyedropper (Alt-click), using palette colours only. Save with Cmd+S.
   **Never edit `src/`**: it is rebuilt.
5. **Rebuild and reload.** Run `tools/export_all.sh` (or the one build script, or `dev_loop.lua` with `-b`). In the GUI
   close the stale tab (Cmd+W), then `open -a Aseprite …` again. Aseprite does not watch files.
6. **Exports stay on the CLI**, never File > Export, so the bytes are reproducible.
7. **Screenshots of Aseprite only.** Bring Aseprite frontmost and zoom it before every screenshot. If another app's
   content (or any bank) is visible, discard that image and never quote what it shows. Delete every screenshot from
   your scratch space when the run ends.
8. **Never touch the owner's documents.** Close, save or edit only documents you opened, all under `ART/`. If a "save
   changes?" dialog names a file outside `ART/`, press Cancel and report it. Do not create files in Aseprite's
   `scripts/` folder and do not change its preferences (step 1).

---

## §11. Open questions for the owner (the default is built; each takes one word to change)

| # | Question | Default built | Alternative |
|---|---|---|---|
| Q1 | When does the worm sleep? The 09-29 brief said "reading books when consolidating" (BRIEF §9, `:173-175`); today `.sleeping` *is* a running cycle (Cicada's Sleep metaphor; `S/MenuBar/BookwormState.swift:10-12`). | Keep the state machine: asleep on the bean bag while a cycle runs (night window), reading while things wait or a run is paused. This contradicts your 09-29 words, so it is the first line of the PR body (§0). No sheet bakes the mapping in. | Swap: read while consolidating, sleep when caught up (a state-machine change; its own ruling; no new art). |
| Q2 | Weather titles. | Night, Dawn, Sunny, Partly cloudy, Windy, Rainy, Curtains drawn (§5.1). | Keep Clear, Fair, Overcast, Storm with the new animation. |
| Q3 | Where does "mad" go? | Drawn as a part, used by no shipped tag. | Shake for a refused drop (sad then goes unused), or a new reaction kind (a matrix change). |
| Q4 | Error pupils. | Red pupils kept beside the worried brows and drop (a second cue; R-Z1's tested mark). | Drop the red; key the test to the brow and drop. |
| Q5 | Book covers. | Three: your blue, crimson, ochre. | More covers, or different colours. |
| Q6 | A pose spanning a cover change swaps the book's colour mid-gaze (every ~22 s at most). | Accepted. | Freeze the cover while the pointer is in the room (a few more lines in `WormStage`). |
| Q7 | Reduce Motion. | Key frame only (G107 R7), no yawn or stretch. | DR-66's gentler profile (slow loops), like Home's painting. |
| Q8 | Your menu-bar worm's near-black rings vanish on a dark bar. | No halo; the lime lenses, pupil holes and neck carry it. | A 1-px light rim on dark appearance only (a second small set). |
| Q9 | Home and Getting started's worm drops from 24 pt to 18 pt at 1.0 (whole points per pixel). | 18 pt (36 at ≥ 1.2). | 36 pt always. |
| Q10 | The wall ends at the pile column with a corner trim. | As built. | Extend only the floor under the pile (DR-13 says no paint behind data; needs a ruling). |
| Q11 | Mug steam and plant sway. | None (motion with no fact). | Allow ambient decoration (R-BW4 amended again). |
| Q12 | The count props, the queue as a room, the night light and time-of-day palettes. | Not built; next design rounds. | — |
| Q13 | Merge gate. | No merge until you have reviewed `preview.html` and the composites. | — |
| Q14 | The menu-bar worm's green. | Your menu-bar file's lime `#ACEC62` (key `m`, used by the 18 × 18 set only): it is the colour you drew, and it is brighter on a dark bar. | Snap it to the room worm's `G`/`g`, so both scales share one green. |
| Q15 | On a completed cycle, stretch first, then cheer? | No: the cheer plays and the stretch is dropped (one beat per edge). | Play the stretch, then the cheer (≈ 2 s of motion on the edge). |
| Q16 | What "extra books" means. | The worm's three reading covers + per-kind pixel spine textures on the real pile (P10 holds: no book is drawn without a real count). | A static shelf or stack in the room (needs a P10 amendment). |
| Q17 | `cicada.png`. | Not drawn in this PR. | A small pixel cicada somewhere in the room (inert, R-Z2), drawn from it. |
