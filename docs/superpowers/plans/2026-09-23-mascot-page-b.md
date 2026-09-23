# The mascot page, part b: feeding, the Meadow pass, two live-check fixes (Track Z, Z9/Z10) — Implementation Plan

> **For agentic workers:** implement this plan task-by-task in this session (superpowers:executing-plans) — this track dispatches no subagents (see *Global Constraints*). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rodrigo 2026-09-23: *"Change the mascot page, make it better and have it be more
interactive, keeping the minimal vibes."* Part a (PR #76) gave the page its room, its one serif
sentence, its one button and its whisper line; the one intake (PR #79) gave the app
`IntakeRouter.accept(urls:from:)` with a `.sleepRoom` door nobody calls yet. Part b finishes Track Z:

1. **Two defects the orchestrator's live check found**, fixed first: on a bank with hundreds of
   items across four sources the **book pile overflows the room** (its top spine is cut by the
   card's edge and the pile towers over the lamp and the window), and the page title **"Sleep
   Cycle" is still SF 20 semibold** while every other page's title is the display serif.
2. **Feeding (Z9, design §7.4).** A file, several files or a folder dropped on the room — or *Feed a
   file…* from the worm's context menu or VoiceOver actions — goes through the one intake and
   nowhere else. The worm opens its mouth while a file hovers the room, gulps when the router takes
   it, shakes when it does not, and the sentence says what happened in plain words, driven by the
   router's own phase. A sleeping worm takes the drop and stays asleep.
3. **The Meadow pass on this page (Z10).** The sentence speaks in Instrument Serif over a New York
   italic tail, Consolidate becomes the page's one prominent action, hover affordances use Meadow's
   motion, and the **optional sky band** is built behind one constant and switched on only if the
   composites of both themes read as a calm tint — the decision recorded as a ruling.
4. **The docs**: G125's v4 row, G107, CLAUDE.md's Sleep-page and intake paragraphs, TODO's
   rulings, and the design's three owner questions marked answered (spec decision 16).

**Architecture:** As in part a, every decision is a **pure function with a table test** — the pile's
fit (`fitPile`), the door's guard (`IntakeRouter.feedGuard`), the feed lines (`feedLine`), which line
the slot shows (`RoomModel.feedPhase`), the worm's pose (`WormStage.pose`), the band's sky
(`SkyBand.phase`) — and the views are thin renderers over them. Feeding adds **no second upload
path**: the room is a door onto `IntakeRouter`, whose guard every door now shares. No backend
change, no new endpoint, no new fetch, no new Store domain, no ETag touched.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, macOS 14 floor, SDK 26.1). `ImageRenderer` for
the band's composites (opt-in, never on CI's default path).

**Spec (binding):**
- `docs/superpowers/specs/2026-09-23-round3-design-mascot-page.md` — the design: rulings
  **R-Z1…R-Z14** (§3), feeding (§7.4), poses and reactions (§6), the interaction catalogue (§8:
  I12–I16 are this plan's), motion and accessibility (§10–§11), tasks **Z9** and **Z10** (§14), the
  owner questions (§16).
- `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` — decisions **5**
  (feeding = a drop on the worm imports it), **6** (Meadow: display ≥ 22 pt, New York italic for
  quotes, one prominent action per page, art never on data), **13** (one intake everywhere) and
  **16** (the sky band ships only if the screenshots say calm).
- `docs/superpowers/plans/2026-09-23-mascot-page.md` (part a) — its rulings **Z-P1…Z-P27** hold;
  its *Seams left for the rest of Track Z* section is this plan's starting point.
- `docs/superpowers/plans/2026-09-23-intake-onboarding-a.md` (Track I part a) — the router API
  (`accept(urls:from:)`, `IntakeOrigin.sleepRoom`, `IntakePhase`, `IntakeOutcome`).
- Backlog rows **G125** (this is v4, part b), **G107** (the feeding amendment ships), **G137**
  (Meadow). **G127** stays out of scope.
- Standing rulings: no prices or tokens in the app (2026-09-03); ruling 4 (scheduled cycles never
  spend plan quota); the capture rail (transcripts under `~/.claude/` are read by the Stop hook's
  endpoint and nowhere else); privacy in docs; portability (no owner name or author-machine path in
  code, plans, commits or PR bodies — this plan writes `<worktree>` for the track's worktree, whose
  absolute path the orchestrator's environment block gives).

---

## What the code actually does today (verified against `feat/mascot-page-b` @ `7162c1c`)

Paths are relative to `app/CicadaApp/Sources/CicadaApp/` unless they start with `app/`, `docs/` or
`CLAUDE.md`. Line numbers drift as tasks land — re-read before editing.

**The pile overflows (live-check defect a).** `Views/Sleep/BookPile.swift:43-60` sizes each spine
`8 + 6·log2(1 + chars/2000)` clamped to **8…40 unscaled points**, largest first, up to `maxBooks = 8`
books **plus** a remainder spine — nine spines. `BookPileView` (`:141-181`) stacks them with a
2 pt unscaled `spineGap` (`:153`) and draws each at `spec.height` (`:232`) and at most a fixed
`maxSpineWidth = 150` (`:154`); nothing bounds the stack's sum. The column it stands in is
`DeskScene.pileCell` = 30 × 26 cells (`Views/Sleep/DeskScene.swift:96`), and a cell is the worm's
snapped size ÷ 24 (`deskSceneLayout`, `:111-127`): **4, 5, 5, 6, 6, 7, 7 pt at uiScale 0.8…1.4**, so
the column is 104…182 pt tall and 120…210 pt wide. `StudyRoom` frames the pile to that column,
bottom-aligned (`Views/Sleep/StudyRoom.swift:112-115`), so an over-tall pile grows **upward**, out
of the room, until `GlassCard`'s `.clipShape` (`Theme/CicadaTheme.swift:660-680`) cuts it at the
card's top edge. The live bank's shape — four sources, hundreds of items each — is four 40 pt spines:
4 × (40 + 2) = **168 pt in a 130 pt column at 1.0×**. Two more faults ride along: at 0.8× a
full-width spine (150 pt) is wider than its 120 pt column, and at 1.4× the spines stay 8…40 pt while
the room around them grows 40 % (a second scale in one picture — P12). The count label shows only
when `spec.height >= 14` (`:233`), in unscaled points against a scaled font.

**The title is still SF (live-check defect b).** `Views/Sleep/SleepView.swift:549-552` draws
`Text("Sleep Cycle").font(CicadaTheme.titleFont)` — `titleFont` is SF 20 semibold
(`Theme/CicadaTheme.swift:310`). Every other page goes through `PageHeader`
(`Views/Common/PageHeader.swift:29-31`), whose title became `displayFont(size: 28)` in G137 R-M16.
The comment above the Sleep header (`SleepView.swift:538-540`) says it "reuses [PageHeader's] title
typography for visual parity" — true before R-M16, false since: the header copied the font instead
of sharing it.

**The intake has no guard and no answer.** `Support/IntakeRouter.swift:228-247` —
`accept(urls:from:)` returns `Void`; a drop while importing toasts `Copy.intakeBusy` (`:231-234`);
an empty expansion becomes `.failed(Copy.intakeNothingReadable)` (`:241-245`). **Nothing refuses a
harness transcript root or Cicada's own home**: `expand` (`:437-458`) walks any folder it is handed
(a dropped `~/.claude/projects` would be enumerated and every `.json` in it sniffed — bytes posted to
the backend), and no file under `Support/` or `Views/Intake/` names `.claude`, `.codex` or
`.cicada` for the intake (grepped). `commit(urls:from:)` (`:374-393`) has the same gap.
`IntakeOrigin.sleepRoom` exists (`:9`) with no caller. The file picker is private to the panel
(`Views/Intake/IntakePanel.swift:98-106`). The window's drop target and veil are
`ContentView.swift:80-85` and `IntakeLayer` (`Views/Intake/IntakeOverlay.swift:41-55`); the veil
shows whenever the window-level `isTargeted` is true, and nothing tells it a nearer target has the
drag.

**The worm is ready to eat; the room is not.** `MenuBar/BookwormPose.swift` already has
`.expectant(Gaze)` and `.eager`, `gulp` and `shake`, and the §6.4 matrix (`acceptsDropPose`,
`allows`) — a sleeping or failed worm folds both drop poses to `.idle` and plays neither beat.
`WormStage` (`StudyRoom.swift:181-194`) only ever asks for `.attentive`/`.idle` (`:188`).
`RoomModel` (`Views/Sleep/RoomModel.swift`) has `play` (`:190-195`), `poke` (`:95-100`) and
`dismissAnswers` (`:104-106`) but no drag or feed state. `Copy.wormHint` (`Theme/Copy.swift:64-67`)
holds back its "Drop a file to import it." clause (Z-P16). The sentence's tail table stops at T12
(`Views/Sleep/RoomSentence.swift:264-270`) — T13 waited for feeding. `store.intakeInFlight` forces
`.reading` but never ahead of `.sleeping` (`Views/Sleep/SleepMood.swift:95-117`), so an import
landing mid-cycle already leaves the worm asleep.

**Meadow is on the branch but not on this page.** `CicadaTheme.displayFont(size:italic:)`
(`CicadaTheme.swift:327-330`, ≥ 22 pt floor `displayMinimumSize`), `quoteFont(size:)` (`:335-336`),
`skyGradient(_:)` (`:182-188`), `CicadaMotion` (`Theme/CicadaMotion.swift:30-95`), `hoverLift()` /
`iconHover()` (`:279-287`), `PrimaryActionButton` and `primaryActionStyle()` (`Theme/LiquidGlass.swift:141,244`)
all exist. `RoomSentenceView` still speaks New York through `CicadaTheme.font(size: 30, design:
.serif)` (`RoomSentence.swift:325`) and `…size: 22, design: .serif).italic()` (`:404`); Consolidate
is a hand-drawn accent capsule with a literal `.white` label (`Views/Sleep/SleepHero.swift:465-491`,
`:481`); `SleepMotion` (`Views/Sleep/SleepMotion.swift:22-95`) spells its own `0.4`, `0.35` and `0.15`
beside `CicadaMotion`'s identical numbers. The one composite helper in the test suite is
`WindowSpritesTests`' opt-in `CICADA_WRITE_COMPOSITES=1` writer
(`app/CicadaApp/Tests/CicadaAppTests/WindowSpritesTests.swift:131-156`) — pixel grids only;
`ImageRenderer` (`nsImage`, macOS 13+) is in the SDK for a SwiftUI composite.

**Checked in the SDK (`MacOSX26.1.sdk`):** `DropDelegate` is `@MainActor` with `validateDrop`,
`dropEntered`, `dropUpdated -> DropProposal?`, `dropExited`, `performDrop`; `DropInfo.location`,
`hasItemsConforming(to:)`, `itemProviders(for:)` (macOS 11+); `onDrop(of:delegate:)`;
`ImageRenderer.nsImage`.

**Baselines on this base (measured for this plan, re-measured by the plan critic):** `swift build`
clean; `swift test` **1426 executed, 0 failures** (if a brief quotes a lower count, 1426 is what
`7162c1c` runs); backend untouched by this track; graph node tests green.

---

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/mascot-page-b`, based on `dev` @ `7162c1c`). Every shell
  command is `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks relative `cd`; ignore its
  stderr warning). No unquoted `--include=*.ext` (zsh globs it). NEVER read `<repo>/memory` (any
  bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects` — every new guard and router test
  passes a temporary `home` and an empty `env`; the router's defaults (the real home) are only
  reached by the pre-existing router tests, where the guard resolves the three root *paths* (an
  `lstat` of `~/.claude`, `~/.codex`, `~/.cicada` — nothing inside them is listed or opened). **No new
  test attaches a bare `Store()`**: its defaults are the live backend (`APIClient.shared`, which reads
  `~/.cicada/api_token`) and the real app cache, and a router that finishes an import calls
  `store.refresh`. Use `Store(cache: SnapshotCache(root: <temp>), api: FakeSyncAPI())`.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures** (1426 executed on this base; the count
  grows task by task). Graph JS (untouched): `cd <worktree> && node --test
  app/CicadaApp/Tests/graph/*.test.js`. SourceKit diagnostics naming OTHER worktrees are noise.
  Unless a step says otherwise, `swift build` / `swift test` run as `cd <worktree>/app/CicadaApp &&
  …`, and `grep` / `git` as `cd <worktree> && …`.
- NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app or the
  launchd backend — the owner's installed app is live; the orchestrator installs and live-checks.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv` or `*-report.md`. No push, no new branches or worktrees, no
  subagents. Ignore Devin/PR comments. End every commit message with the session's attribution
  trailer.
- **Green throughout, edited only where a task says why:** `FixWaveTests`, `SleepNumbersLintTests`,
  `SleepHeroTests`, `BookwormRendererTests`, `BookwormSpriteTests`, `BookwormPoseSpriteTests`,
  `DeskSceneLayoutTests`, `DeskHotspotTests`, `RoomModelTests`, `WormAnswersTests`,
  `IntakeRouterTests`, `FontLiteralLintTests`, `MotionLiteralLintTests`, `LiquidGlassLintTests`,
  `MeadowPlacementLintTests`, `ThemeTokenTests`, `CountLiteralLintTests`, `CopyConstantsTests`.
- **Fonts** only through `CicadaTheme.font(size:…)`, `displayFont(size:italic:)` (≥ 22 pt) or
  `quoteFont(size:)`; **durations** only as named `SleepMotion` / `CicadaMotion` constants (two lints);
  **colours** only theme tokens or the two art palettes (no `.white`, no `Color(hex:` outside the
  theme); **glass** only through `Theme/LiquidGlass.swift`.
- **Art rails (R-Z1…R-Z4, R-Z10…R-Z12):** art encodes state, never quantity — a pile compressed to
  fit still says its counts in words; every art bit has a text twin; response art never contradicts
  state art (the §6.4 matrix decides every beat); all worm motion is sprite frames on the one
  lattice (the `testTheWormIsNeverTransformed` lint); painted Meadow art never enters the pixel room;
  Reduce Motion reaches the terminal frame.
- **Copy:** plain and friendly, first person in the worm's voice, no jargon, no prices or token
  counts, no "!", no bare `%`, no "est"/"~"/"cluster"/"insight" (R-Z13), **no digit in any feed line**
  (R-Z3 — the panel has the counts). Every service a line names shows its real mark (`SentenceMark`).
- Docstrings explain **why**, citing the ruling (`R-Z…`, `Z-P…`, this plan's `Z-B…`) or the defect
  that motivated the rule, at the density of the files touched.

---

## Rulings (binding)

The design's **R-Z1…R-Z14** and part a's **Z-P1…Z-P27** hold. These are the choices the brief and the
design left open, decided here so no task re-opens them.

- **Z-B1 — The pile is compressed to its column, never cut, and never more than eight spines.**
  `fitPile` keeps every spine's natural (authored) height when the stack fits; when it does not, it
  compresses only what sits above a **label floor** (the height a spine needs to carry its count),
  all spines by one factor, so the order — the pile's one comparison — survives and every spine that
  carried a count still does. The fold moves from 8 books + remainder to **7 + remainder = 8
  spines**, because that is what fits with every count readable **at every zoom step**, measured:
  8 × (label floor + gap) is 102.4 of 104 pt at 0.8× and 153.6 of 156 pt at 1.2× (the two tightest),
  while nine spines need 144 pt of the 130 pt column at 1.0×. `PileFitTests` recomputes all seven
  steps. No `.clipped()`: a clip would hide exactly the quantity the pile exists to show.
- **Z-B2 — The pile scales with the lattice; its label floor scales with the font.** Heights and the
  gap are multiplied by `cell ÷ 5` (5 pt is the cell at 1.0×, pinned), so at 1.1× — where the room
  snaps to 6 pt cells — the pile grows with the room rather than by 1.1 (P12: one scale per picture).
  The label floor is `14 × uiScale`, because the count is drawn in `captionFont`, which scales by
  uiScale — and so the mark beside the count is drawn at `CicadaTheme.scaled(12)`, not a fixed 12 pt
  that would overhang the 11.2 pt floor at 0.8×. The fit takes `uiScale` as a parameter (pure), and the view reads
  `CicadaTheme.uiScale` so a zoom step refits the pile in the frame the room re-snaps.
- **Z-B3 — A full-width spine is exactly the column's width, at every zoom.** `maxSpineWidth = 150`
  is deleted; `PileFit.maxWidth` is `pileFrame.width` (150 pt at 1.0×, so nothing moves there).
- **Z-B4 — One title view, shared, not `PageHeader` itself.** `PageTitle` (in `PageHeader.swift`)
  draws `displayFont(size: 28)` in `textPrimary`; `PageHeader` draws its title through it and the
  Sleep header does too. The Sleep header does not become a `PageHeader` because its title sits
  inside the centred 760 pt column (R-Z6) with the staleness chip *beside* it (R-A12), and
  `PageHeader` pads itself and puts its accessory on the far right, under the page's `?`. The text
  stays "Sleep Cycle", now `Copy.sleepPageTitle`; a lint pins that neither file spells the title
  font itself again.
- **Z-B5 — The guard lives in the router and every door passes it.** `IntakeRouter.feedGuard`
  (the design's name, for the worm that asked for it) runs in `accept` and in `commit`. It refuses,
  in this order: a dropped URL under `~/.claude` or `$CLAUDE_CONFIG_DIR` (Claude Code's sessions),
  `~/.codex` or `$CODEX_HOME` (Codex's), `~/.cicada` or `$CICADA_HOME` (Cicada's own: the api token,
  `secrets.env`, the remote connectors' database) — **before `expand` walks it**, because listing the
  names in `~/.claude/projects` is already more than the capture rail allows; then, during the walk
  of an innocent folder, any entry that resolves under one of them — a folder there is **never
  descended into** (`expand`'s `prune`, which calls `skipDescendants()`: a dropped `~` whose
  `$CLAUDE_CONFIG_DIR` is a visible folder inside it would otherwise be listed; the default roots
  are dot-folders the walk already skips) and a file there (a symlink) refuses the drop; then a drop
  with nothing export-shaped in it. Both sides are compared resolved (`resolvingSymlinksInPath()
  .standardizedFileURL`) and **component by component**, so `~/.claudette/x.json` is not
  `~/.claude`. Nothing is ever opened. `home` and `env` are injected so tests use a temporary home,
  and the walk is injected (`walk:`) so a test can prove a refused root is never walked.
- **Z-B6 — `accept` answers, and the room speaks for itself.** `accept` returns an
  `IntakeAcceptance` (`accepted` · `refused(FeedRefusal)` · `busy`), `@discardableResult` so no
  existing door changes. `IntakeOrigin.answersInPlace` is true for `.sleepRoom` only: a refusal or a
  busy router there raises no overlay and posts no toast — the worm's line says it, once. Every other
  door shows a refusal in the panel (`.failed(refusal.panelText)`), in Cicada's third-person voice.
  An **accepted** room drop raises the router's overlay like every other door (R-Z10: "its sheet, its
  preview").
- **Z-B7 — The guard decides at the drop, not during the hover.** During a drag the worm is
  expectant for any file URL (`validateDrop` = `hasItemsConforming(to: [.fileURL])`, design I12); the
  verdict — gulp or shake — comes at `performDrop` (I15). `DropInfo`'s item providers load
  asynchronously, so a hover-time verdict would arrive after the pose it was meant to choose and load
  every file twice.
- **Z-B8 — The window's veil yields to the room by an explicit claim.** The room's drop delegate
  calls `intake.claimDrop(.sleepRoom)` on entry and `releaseDrop` on exit or drop; `IntakeLayer`
  shows the veil only while `showsVeil(windowTargeted:nearerDrop:)`. Whether SwiftUI clears an
  enclosing `onDrop`'s `isTargeted` when a nested target takes the drag is not verified here, and the
  veil's scrim over the room would hide the worm's open mouth and the outline; the claim makes the
  result the same either way. (The empty states' nested targets are Track I's and are not changed —
  see *Not in scope*.)
- **Z-B9 — "The router's own outcome drives the line", made exact.** While the room's drop is live
  (`FeedResult.handedOver`) the slot tells `IntakePhase` in words: reading → *Let me see what's in
  it.*, preview → *Have a look first.*, importing → *Adding it to the pile…*, done → the landing,
  failed → *I couldn't take that.* / *The panel says why.* When the done card closes, the landing
  stays as a `.landed` line until it dwells away, so the person reads what happened after the panel
  is gone. **No feed line carries a digit** — one file and a thousand get the same gulp and the same
  words (R-Z3); even `.failed` points at the panel instead of echoing a reason that may hold a
  number. A page that is stale (`SleepLiveness.stale`, R-A12) answers *I'm offline right now.* /
  *Nothing was sent. Try again in a moment.* **without asking the router**.
- **Z-B10 — One gesture for yes, one for no.** `gulp` when the router took the drop; `shake` for
  every drop it did not take (refused, busy, offline). The §6.4 matrix still gates both: a sleeping
  worm plays neither and stays asleep (its line says *I'll read it after this nap.*), an erroring worm
  answers in words only, and Reduce Motion plays no beat at all.
- **Z-B11 — What ends a feed line.** A new drag, a poke, Esc on the worm, the 12 s dwell outside the
  room and the sentence (the answer ladder's own rule, I4), and a mood change — everything the room
  said about a moment that has passed. A live intake's line is the exception: it is still true.
- **Z-B12 — The sentence's faces (the brief overrides design §5 here).** The lead is
  `displayFont(size: 30)` (Instrument Serif; the numeral run stays SF rounded) and may shrink to fit
  one line only down to the display floor: `minimumScaleFactor = displayMinimumSize ÷ 30` (the old
  0.7 would have reached 21 pt, under the face's own 22 pt limit). The italic tail is
  **`quoteFont(size: 22)`** — New York italic, as the brief asks, rather than the design's Instrument
  Serif italic: a two-line, 80-character tail is text, which is what New York is optically sized for
  (R-M3's own reason for the quote face).
- **Z-B13 — `SleepMotion` stops re-spelling Meadow's numbers.** Where a name mirrors
  `CicadaMotion`'s (`maxDuration`, `settleDuration`/`settle`, `hoverDuration`/`hover`), `SleepMotion`
  now forwards to it; the Sleep-only constants (beat, sentence, pile, disclosure, weather, dwell,
  perk) stay. A test pins the equalities, so "one budget, app-wide" is a fact, not a comment. (The
  hover curve moves from easeOut to Meadow's easeInOut, both 0.15 s.)
- **Z-B14 — Consolidate is the page's one prominent action; Cancel stays quiet.** Consolidate is a
  `PrimaryActionButton` (`.glassProminent` accent-tinted on macOS 26, `.borderedProminent` before,
  its ink through the key-window rule), at `.controlSize(.large)`, with `hoverLift()` because it is
  the one thing on the page that starts something. Cancel keeps its muted capsule — a stop is not
  the page's prominent action. A lint holds one `PrimaryActionButton(` under `Views/Sleep/`.
- **Z-B15 — Hover affordances only on things that are controls, never on art.** The Details row's
  chevron acknowledges the pointer once (`iconHover`) and its words brighten; the whisper line's
  moon glyph does the same. The lamp, window and worm hotspots keep their cursor and nothing else —
  I8: *the art never changes* on hover (R-Z2).
- **Z-B16 — The sky band: built behind one constant, decided by composites.** `SkyBand.ships` is the
  single switch. The band is a procedural wash of Meadow's sky gradients (theme tokens, zero bytes —
  a wash, not painted art, so `MeadowPlacementLintTests`' allowlist is untouched), fixed across the
  top of the page behind the title, `SkyBand.height` 64 pt fading to clear before the room card
  starts (the card sits below 24 pt of padding, the 28 pt title's line and a 16 pt gap — at least
  68 pt, all scaled like the band, pinned by `SkyBandTests`), at `CicadaTheme.skyBandOpacity` 0.12. It shows **only a sky the window agrees with** — night while a
  cycle runs, dusk at dawn, day for clear and fair — and nothing for overcast, storm or curtains (a
  grey band would be the "dirt" the owner's §16 question names, and the window and sentence already
  say those states). It crossfades with the weather (`SleepMotion.weather`, nil under Reduce Motion)
  and is hidden under Increase Contrast (§11). Two gates run in the build (`SkyBandTests`): the
  band's top composited over the page stays within **1.35:1** of it in both modes (a tint, not a
  block), and `textPrimary` on it keeps **≥ 7:1**. Then Task 4 renders the day/dusk/night bands in
  both themes with a no-band control and **looks at them**: the band ships ON only if every one reads
  as a calm tint that fades into the page — in particular the light-mode night and dusk bands must
  not read as a grey smudge; otherwise it ships OFF. The outcome and its reason become TODO ruling 10
  and the G125 row, and `SkyBand.ships`' docstring states them.
- **Z-B17 — One picker for every door.** `IntakePicker` (hoisted from `IntakePanel.chooseFile`) is
  what the panel and the worm's *Feed a file…* both open — the same types, multiple selection,
  folders allowed. A lint holds `NSOpenPanel()` to one file across `Views/Intake/` and `Views/Sleep/`.
- **Z-B18 — Two voices for one refusal.** The worm says it in the first person with the service's
  mark (*I don't eat those.* / *Claude Code sessions come to me once it's connected.*); the panel
  says it about Cicada (*Claude Code sessions come in on their own once it's connected, so there's
  nothing to import here.*). Neither promises a capture that may not be wired — "once it's
  connected" is the condition — and neither says Cicada "never reads" these files: the Stop hook's
  endpoint does read a session's transcript (G105), and in this app "read" is also a Sleep read
  (Track I final review, finding 7). **The design's "…feeds and notes" becomes "…feeds and saved
  links"** (I12's armed tail and the `.unreadable` refusal): a note is not something the intake
  reads — `media_ingestor.parse_upload` reads a `.txt` or `.csv` as a list of links and a `.md` is not
  export-shaped at all — so the worm would refuse a dropped note and then say notes work. Notes
  arrive through Integrations (Apple Notes, a watched folder), a standing connection, not a drop.
- **Z-B19 — T13 is the happy worm's tail.** *Drop a file on me to add it to the pile.* claims
  `.happy`'s tail below T12 (it could not ship before feeding, Z-P16), **once the queue has loaded**
  (`case .loaded = ctx.queueLoad`): "Checking what's waiting…" never carries an invitation, and
  part a's `test_L2_theQueueIsLoading` — a `.happy` context with a loading queue — keeps pinning no
  tail. Three part-a assertions that pinned "no tail" on a happy, loaded page are re-pointed, each
  with its reason in the task.

---

## File map

| File | Responsibility |
|---|---|
| `…/Views/Sleep/BookPile.swift` | `PileFitting`, `PileFit`, `fitPile`; `bookPileLayout` folds at 7; `BookPileView.layout`; `SpineButton` draws the fitted spine (T1) |
| `…/Views/Sleep/StudyRoom.swift` | passes `layout: scene` (T1); the drop target, `DropOutline`, `feed(_:)`, *Feed a file…*, `WormStage.pose` (T3) |
| `…/Views/Common/PageHeader.swift` | `PageTitle`; `PageHeader` draws its title through it (T1) |
| `…/Views/Sleep/SleepView.swift` | the header through `PageTitle` (T1); `reachable`, `feedAsleep`, `dismissSlot` (T3); the sky band, `DetailsDisclosureRow`, the whisper glyph's hover (T4) |
| `…/Theme/Copy.swift` | `sleepPageTitle` (T1); `wormHint`, `feedAFile` (T3) |
| `…/Support/IntakeRouter.swift` | `FeedRefusal`, `IntakeAcceptance`, `IntakeAdmission`, `IntakeOrigin.answersInPlace`, `feedGuard` (with its `walk` seam), `expand`'s `prune`, `accept` answers, `commit` guarded, `nearerDrop` claim (T2) |
| `…/Theme/Copy+Intake.swift` | the panel's refusal sentences (T2) |
| `…/Views/Intake/IntakeOverlay.swift` | `IntakePicker`; `IntakeLayer.showsVeil` (T2) |
| `…/Views/Intake/IntakePanel.swift` | `chooseFile` → `IntakePicker` (T2) |
| `…/Views/Sleep/RoomFeed.swift` (new) | `RoomDrag`, `FeedLanding`, `FeedResult`, `FeedPhase`, `feedLine`, `feedIsAsleep`, `roomFeedResult`, `RoomDropDelegate` (T3) |
| `…/Views/Sleep/RoomModel.swift` | `drag`, `feedResult`, `dragMoved`, `dragEnded`, `fed`, `intakeChanged`, `dismissSlot`, `feedPhase` (T3) |
| `…/Views/Sleep/RoomSentence.swift` | T13; the slot shows a feed line first, keys and dwells on it (T3); Meadow faces (T4) |
| `…/Views/Sleep/SleepHero.swift` | Consolidate → `PrimaryActionButton` (T4) |
| `…/Views/Sleep/SleepMotion.swift` | forwards the shared names to `CicadaMotion` (T4) |
| `…/Views/Sleep/SleepSkyBand.swift` (new) | `SkyBand`, `SleepSkyBand` (T4) |
| `…/Theme/CicadaTheme.swift` | `skyBandOpacity` (T4) |
| Tests (new) | `PileFitTests`, `PageTitleTests` (T1); `FeedGuardTests` (T2); `RoomFeedTests` (T3); `SleepMeadowTests`, `SkyBandTests` (T4) |
| Tests (edited, reason in the task) | `DeskSceneLayoutTests` (T1); `IntakeRouterTests` (T2); `RoomSentenceTests` (T3) |
| Docs (T5) | `CLAUDE.md`, `docs/goals/memory-evolution.md` (G125, G107), `docs/goals/TODO.md`, the mascot design §16, the round-3 spec's Track Z note |

**Files other round-3 tracks also touch (merge care for the orchestrator):** `IntakeRouter.swift`,
`IntakeOverlay.swift`, `IntakePanel.swift`, `Copy+Intake.swift` (Track I part b), `PageHeader.swift`
and `CicadaTheme.swift` (M2's app-wide Meadow pass), `Copy.swift` (everyone). Every edit here is a
small, separate hunk.

---

### Task 1: The two live-check fixes — the pile fits the room, the title is the page title

Nothing else on the page changes. The pile keeps its authored heights whenever it fits; only a pile
that overflowed is compressed.

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/BookPile.swift` — `bookPileLayout`'s default fold (`:43`) and the `BookSpec.height` docstring (`:29`); add `PileFitting` / `PileFit` / `fitPile` after `:60`; `BookPileView` (`:141-181`: `layout`, the fit, `maxSpineWidth` deleted); `SpineButton` (`:189-250`: fitted height, gap, width, label)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyRoom.swift:112-113` — `layout: scene`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/PageHeader.swift` — add `PageTitle`; `:29-31` uses it
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:537-563` — the header
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — `sleepPageTitle`, beside `sleepSubtitle` (`:327`)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/PileFitTests.swift`, `app/CicadaApp/Tests/CicadaAppTests/PageTitleTests.swift`
- Test (edit — docstring only; the assertion stands): `DeskSceneLayoutTests.swift:125-129` (the docstring of `testThePileColumnFitsAFullWidthSpine`, `:130-133`) names `BookPileView.maxSpineWidth`, which this task deletes

**Interfaces:**
- Produces: `PileFitting.referenceCell` / `.labelMinPoints` / `.maxSpines` / `.maxBooks`; `PileFit` (`heights`, `gap`, `maxWidth`, `labelMinHeight`, `height(_:)`, `showsLabel(_:)`, `totalHeight`); `fitPile(_:in:uiScale:) -> PileFit`; `BookPileView(… layout:)`; `PageTitle(_:)` / `PageTitle.size`; `Copy.sleepPageTitle`.
- Consumes: `deskSceneLayout(pointSize:uiScale:)`, `DeskSceneLayout.cell` / `.pileFrame`, `CicadaTheme.uiScale`, `CicadaTheme.displayFont(size:)`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/PileFitTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Live check 2026-09-23 (Z-B1…Z-B3) — on a bank with hundreds of items across
/// four sources, four 40 pt spines and their gaps needed 168 pt of a 130 pt
/// column, so the pile grew out of the room and the card's clip cut its top
/// spine. The pile is the page's one volume encoding (R1/R9): it may be
/// COMPRESSED to fit, never cut, and every count it carried stays readable.
final class PileFitTests: XCTestCase {

    /// Every View-menu step (G130: 0.8…1.4 in 0.1).
    private let steps: [Double] = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]

    private func room(_ scale: Double) -> DeskSceneLayout {
        deskSceneLayout(pointSize: SleepView.wormPointSize, uiScale: scale)
    }

    private func sources(_ n: Int, chars: Int, count: Int = 300) -> [OriginVolume] {
        (0..<n).map { OriginVolume(origin: "origin-\($0)", count: count, chars: chars - $0, remaining: count) }
    }

    /// The queues the live check could not draw, and the extremes around them.
    private var queues: [(name: String, volumes: [OriginVolume])] {
        [("empty", []),
         ("one tiny book", sources(1, chars: 1, count: 1)),
         ("four sources, hundreds each (the live check)", sources(4, chars: 4_000_000)),
         ("eight sources at the ceiling", sources(8, chars: 50_000_000)),
         ("thirty sources, folded", sources(30, chars: 1_000_000_000, count: 50)),
         ("mixed", [OriginVolume(origin: "claude-code", count: 400, chars: 90_000_000, remaining: 400),
                    OriginVolume(origin: "safari-bookmark", count: 300, chars: 3_000_000, remaining: 300),
                    OriginVolume(origin: "rss", count: 200, chars: 400_000, remaining: 200),
                    OriginVolume(origin: "saved-link", count: 1, chars: 0, remaining: 1)])]
    }

    func test_theTallestPileFitsTheColumnAtEveryZoomStep() {
        for scale in steps {
            let layout = room(scale)
            XCTAssertLessThanOrEqual(layout.pileFrame.maxY, layout.size.height, "the column is inside the room")
            for queue in queues {
                let books = bookPileLayout(queue.volumes)
                let fit = fitPile(books, in: layout, uiScale: scale)
                XCTAssertLessThanOrEqual(books.count, PileFitting.maxSpines, queue.name)
                XCTAssertLessThanOrEqual(fit.totalHeight, layout.pileFrame.height + 0.001,
                                         "\(queue.name) at \(scale)× overflows its \(layout.pileFrame.height) pt column")
                XCTAssertEqual(fit.maxWidth, layout.pileFrame.width, "Z-B3: a full spine is the column's width")
            }
        }
    }

    /// Z-B1 — quantity is still said where it is true: every spine tall enough
    /// to carry its count as authored still carries it once compressed.
    func test_everySpineThatCarriedACountStillCarriesIt() {
        for scale in steps {
            let layout = room(scale)
            let unit = layout.cell / PileFitting.referenceCell
            for queue in queues {
                let books = bookPileLayout(queue.volumes)
                let fit = fitPile(books, in: layout, uiScale: scale)
                for spec in books where spec.height * unit >= fit.labelMinHeight {
                    XCTAssertTrue(fit.showsLabel(spec), "\(queue.name) at \(scale)×: \(spec.origin) lost its count")
                }
            }
        }
    }

    /// The cap is measured, not a round number: eight spines at the label floor
    /// fit every step; a ninth does not fit at 1.0×.
    func test_eightSpinesAtTheLabelFloorFitEveryStep_nineWouldNot() {
        for scale in steps {
            let layout = room(scale)
            let unit = layout.cell / PileFitting.referenceCell
            let perSpine = PileFitting.labelMinPoints * CGFloat(scale) + BookPileView.spineGap * unit
            XCTAssertLessThanOrEqual(CGFloat(PileFitting.maxSpines) * perSpine, layout.pileFrame.height, "\(scale)×")
        }
        let one = room(1.0)
        XCTAssertGreaterThan(CGFloat(PileFitting.maxSpines + 1) * (PileFitting.labelMinPoints + BookPileView.spineGap),
                             one.pileFrame.height)
        XCTAssertEqual(PileFitting.maxBooks, PileFitting.maxSpines - 1, "the eighth spine is the remainder")
        XCTAssertEqual(bookPileLayout(sources(30, chars: 1_000_000_000, count: 50)).count, PileFitting.maxSpines)
    }

    /// Compression keeps the pile's one comparison: largest first stays largest first.
    func test_compressionKeepsThePilesOrder() {
        let layout = room(1.0)
        let books = bookPileLayout(queues.first { $0.name == "mixed" }!.volumes)
        let fit = fitPile(books, in: layout, uiScale: 1.0)
        let heights = books.map { fit.height($0) }
        XCTAssertEqual(heights, heights.sorted(by: >))
        XCTAssertLessThan(heights.last ?? 0, heights.first ?? 0)
    }

    /// A pile that already fits is drawn exactly as authored.
    func test_aPileThatFitsIsDrawnAsAuthored() {
        let books = bookPileLayout([OriginVolume(origin: "claude-code", count: 3, chars: 2000, remaining: 3)])
        let fit = fitPile(books, in: room(1.0), uiScale: 1.0)
        XCTAssertEqual(fit.height(books[0]), 14, accuracy: 0.001)
        XCTAssertEqual(fit.gap, 2, accuracy: 0.001)
        XCTAssertTrue(fit.showsLabel(books[0]))
    }

    /// Z-B2 — the pile scales with the lattice it stands on.
    func test_thePileScalesWithTheLattice() {
        XCTAssertEqual(room(1.0).cell, PileFitting.referenceCell, "the heights were authored at 1.0×")
        let books = bookPileLayout([OriginVolume(origin: "rss", count: 3, chars: 2000, remaining: 3)])
        XCTAssertEqual(fitPile(books, in: room(1.1), uiScale: 1.1).height(books[0]), 14 * 6 / 5, accuracy: 0.001,
                       "1.1× snaps to 6 pt cells: the spine grows with the room, not by 1.1")
    }

    /// A source read through this cycle draws no spine, so it takes no height.
    func test_aSpineReadThroughTakesNoRoom() {
        let books = [BookSpec(origin: "rss", count: 4, height: 40, widthFraction: 0, isRemainder: false)]
        let fit = fitPile(books, in: room(1.0), uiScale: 1.0)
        XCTAssertEqual(fit.totalHeight, 0)
        XCTAssertEqual(fit.height(books[0]), 0)
    }
}
```

  `app/CicadaApp/Tests/CicadaAppTests/PageTitleTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Live check 2026-09-23 (Z-B4) — the Sleep page's title was still SF 20
/// semibold after G137 R-M16 moved every page title to the display serif,
/// because it spelled its own `Text(…).font(titleFont)` instead of sharing
/// `PageHeader`'s. One title view now, and both draw through it.
final class PageTitleTests: XCTestCase {

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) })
        return try String(contentsOf: file, encoding: .utf8)
    }

    func test_theSleepPageTitleIsThePageTitle() throws {
        let text = try source("Views/Sleep/SleepView.swift")
        XCTAssertTrue(text.contains("PageTitle(Copy.sleepPageTitle)"))
        XCTAssertFalse(text.contains("CicadaTheme.titleFont"), "the SF 20 semibold title G137 retired")
        XCTAssertFalse(text.contains("Text(\"Sleep Cycle\")"))
    }

    func test_pageHeaderDrawsItsTitleThroughTheSameView() throws {
        let text = try source("Views/Common/PageHeader.swift")
        XCTAssertTrue(text.contains("PageTitle(title)"))
        XCTAssertEqual(text.components(separatedBy: "displayFont(").count - 1, 1,
                       "the title face is spelled once, inside PageTitle")
    }

    func test_theTitleIsTheDisplayFaceAtItsSize() {
        XCTAssertEqual(PageTitle.size, 28)
        XCTAssertGreaterThanOrEqual(PageTitle.size, CicadaTheme.displayMinimumSize)
        XCTAssertEqual(Copy.sleepPageTitle, "Sleep Cycle")
    }
}
```

  Run: `swift test --filter "PileFitTests|PageTitleTests" 2>&1 | tail -20` → compile failure (the names do not exist yet).

- [ ] **Step 2: Implement the fit.** In `BookPile.swift`, change `bookPileLayout`'s signature (`:43`) to
  `func bookPileLayout(_ buckets: [OriginVolume], maxBooks: Int = PileFitting.maxBooks) -> [BookSpec]`
  and add to its docstring: *"`maxBooks` defaults to `PileFitting.maxBooks` (7): the eighth spine is
  the remainder, and eight is what the room's column holds with every count readable (Z-B1)."* Change
  `BookSpec.height`'s role in its docstring (`:26-33`) to *"the spine's natural height in points at the
  reference cell (uiScale 1.0) — `fitPile` turns it into what is drawn."* Then, after `bookPileLayout`
  (`:60`), add:

```swift
/// How the pile fits the room's column (live check 2026-09-23, Z-B1…Z-B3). On
/// a bank with hundreds of items across four sources, four 40 pt spines and
/// their gaps stood 168 pt in a 130 pt column: the pile grew out of the room
/// and the card's clip cut its top spine. The pile is the page's one volume
/// encoding (R1/R9), so its art may be COMPRESSED to fit — never cut, never
/// spilled — while the quantity stays readable where it is true: the count on
/// each spine, its tooltip, its popover and Details › What's waiting.
enum PileFitting {
    /// The cell `bookPileLayout`'s 8–40 pt heights were authored at
    /// (`deskSceneLayout(pointSize: 120, uiScale: 1.0).cell`, pinned by
    /// `PileFitTests`). The pile scales with the lattice it stands on, not with
    /// the font: at 1.1× the room snaps to 6 pt cells, and a pile sized by
    /// uiScale alone would be a second scale in one picture (P12, Z-B2).
    static let referenceCell: CGFloat = 5
    /// The shortest spine that carries its count in `captionFont` — the old
    /// `spec.height >= 14` rule, now scaled with the font it guards (Z-B2).
    static let labelMinPoints: CGFloat = 14
    /// The most spines the column holds with every spine that deserves a count
    /// still tall enough to show it, at EVERY zoom step: 8 × (floor + gap) is
    /// 102.4 of 104 pt at 0.8× and 153.6 of 156 pt at 1.2×; nine would need
    /// 144 pt of the 130 pt column at 1.0×. Measured per step by `PileFitTests`.
    static let maxSpines = 8
    /// Real books before the fold — the "+more" remainder is the eighth spine.
    static let maxBooks = maxSpines - 1
}

/// What `fitPile` decided: each drawn spine's height, by `BookSpec.id`, and
/// the gap, width and label floor it was decided with.
struct PileFit: Equatable {
    var heights: [String: CGFloat]
    var gap: CGFloat
    var maxWidth: CGFloat
    var labelMinHeight: CGFloat

    func height(_ spec: BookSpec) -> CGFloat { heights[spec.id] ?? 0 }
    /// A spine carries its count only when it is tall enough to hold it.
    func showsLabel(_ spec: BookSpec) -> Bool { height(spec) + 0.001 >= labelMinHeight }
    /// The stack as `BookPileView` draws it: every drawn spine plus the gap above it.
    var totalHeight: CGFloat { heights.values.reduce(0) { $0 + $1 + gap } }
}

/// Pure (Z-B1): natural heights when the stack fits the column; otherwise only
/// what sits above the label floor is compressed, every spine by one factor,
/// so the order survives and every spine that carried a count still does. A
/// spine read through this cycle (`widthFraction == 0`) is not drawn and
/// takes no height.
func fitPile(_ books: [BookSpec], in layout: DeskSceneLayout, uiScale: Double) -> PileFit {
    let unit = layout.cell / PileFitting.referenceCell
    let gap = BookPileView.spineGap * unit
    let labelMin = PileFitting.labelMinPoints * CGFloat(uiScale)
    let drawn = books.filter { $0.widthFraction > 0 }
    let natural = drawn.map { $0.height * unit }
    let column = layout.pileFrame.height
    let gaps = CGFloat(drawn.count) * gap
    var heights = natural
    if natural.reduce(0, +) + gaps > column {
        let floors = natural.map { min($0, labelMin) }
        let excess = zip(natural, floors).reduce(CGFloat(0)) { $0 + ($1.0 - $1.1) }
        let room = column - gaps - floors.reduce(0, +)
        let k = excess > 0 ? max(0, min(1, room / excess)) : 0
        heights = zip(natural, floors).map { $0.1 + ($0.0 - $0.1) * k }
        // Unreachable within `maxSpines` (tested at every step); kept so a
        // future fold change degrades to smaller spines, never to a cut pile.
        let total = heights.reduce(0, +)
        if total + gaps > column, total > 0 {
            let shrink = max(0, column - gaps) / total
            heights = heights.map { $0 * shrink }
        }
    }
    return PileFit(heights: Dictionary(zip(drawn.map(\.id), heights), uniquingKeysWith: { first, _ in first }),
                   gap: gap, maxWidth: layout.pileFrame.width, labelMinHeight: labelMin)
}
```

- [ ] **Step 3: Draw the fitted pile.** `BookPileView` (`:141-181`): add, after `onOpenDetails`, the
  stored property (no default — the pile must know the room it stands in; `StudyRoom` is its only
  caller, grepped)

```swift
    /// The room the pile stands in, whose reserved column it must fit (Z-B1).
    let layout: DeskSceneLayout
```

  delete `static let maxSpineWidth: CGFloat = 150` (`:154`), change `spineGap`'s docstring to add
  *"…at the reference cell; `fitPile` scales it with the lattice (Z-B2)."*, and make `body`:

```swift
    var body: some View {
        let byOrigin = Dictionary(rows.map { ($0.origin, $0) }, uniquingKeysWith: { first, _ in first })
        // Z-B1 — compressed to the column, never cut. `uiScale` is read here so
        // a zoom step refits the pile in the frame the room re-snaps.
        let fit = fitPile(books, in: layout, uiScale: CicadaTheme.uiScale)
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Self.stacked(books)) { spec in
                if spec.widthFraction > 0 {
                    SpineButton(spec: spec, row: byOrigin[spec.origin], episodes: episodes, room: room,
                                onOpenDetails: onOpenDetails, height: fit.height(spec), gap: fit.gap,
                                width: fit.maxWidth * spec.widthFraction, showsLabel: fit.showsLabel(spec))
                        // Inside the pile's own container: largest first (§11),
                        // whatever the bottom-up display order.
                        .accessibilitySortPriority(-Double(books.firstIndex(of: spec) ?? 0))
                }
            }
        }
        .frame(maxHeight: .infinity, alignment: .bottom)
        .animation(SleepMotion.pile(reduceMotion: reduceMotion), value: books)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(pileAccessibilityLabel(sourceCount: rows.count))
        .accessibilitySortPriority(RoomA11yOrder.spines)
    }
```

  `SpineButton` (`:189-250`): add after `onOpenDetails`

```swift
    /// What `fitPile` gave this spine (Z-B1): its drawn height, the gap above
    /// it (inside its hit target, Z-P14), its width, and whether it is tall
    /// enough to carry its count.
    let height: CGFloat
    let gap: CGFloat
    let width: CGFloat
    let showsLabel: Bool
```

  then `.padding(.top, BookPileView.spineGap)` (`:206`) → `.padding(.top, gap)`, the fill's
  `.frame(width: BookPileView.maxSpineWidth * spec.widthFraction, height: spec.height)` (`:232`) →
  `.frame(width: width, height: height)`, `if spec.height >= 14 {` (`:233`) → `if showsLabel {`, and
  the label's `OriginMark(origin: spec.origin, size: 12)` (`:235`) → `OriginMark(origin: spec.origin,
  size: CicadaTheme.scaled(12))` with the comment `// Z-B2 — scales with the floor it sits in: a
  fixed 12 pt mark would overhang the 11.2 pt label floor at 0.8×.` (`OriginMark` draws exactly the
  size it is given; `scaled(12)` is 12 at 1.0×, so nothing moves there.)
  In `StudyRoom.swift` (`:112-113`) pass the room's own layout:

```swift
            BookPileView(books: page.books, rows: page.rows, episodes: episodes, room: room,
                         onOpenDetails: onOpenDetails, layout: scene)
```

  In `DeskSceneLayoutTests.swift:125-126` replace the docstring's "whose widest spine is
  `BookPileView.maxSpineWidth`" with "whose widest spine is the column itself (`fitPile`, Z-B3) — at
  1.0× the 150 pt the pile was authored for"; the assertion is unchanged. (`DeskScene.swift:40-46`
  and `:93-95` still say a full-width spine is 150 pt — true at 1.0×, where Z-B3 changes nothing;
  leave them.)

- [ ] **Step 4: One title view.** In `PageHeader.swift`, above `PageHeader`:

```swift
/// A page's title in its one face (G137 R-M16): Instrument Serif at 28 pt in
/// `textPrimary`. `PageHeader` draws its title through this, and so does the
/// Sleep page's header, which sits inside its centred column with the
/// staleness chip beside it (Z-B4) — the live check found that header still
/// in SF 20 semibold because it had copied the old font instead of sharing it.
struct PageTitle: View {
    static let size: CGFloat = 28
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(CicadaTheme.displayFont(size: Self.size))
            .foregroundStyle(CicadaTheme.textPrimary)
    }
}
```

  and replace `PageHeader`'s three title lines (`:29-31`) with `PageTitle(title)`. Update the
  `PageHeader` docstring's "a display-serif title in `textPrimary`" to "a display-serif title in
  `textPrimary` (`PageTitle`, shared with the Sleep page's header)". In `Copy.swift`, beside
  `sleepSubtitle` (`:327`):

```swift
    /// The Sleep page's title, drawn by `PageTitle` like every page's (Z-B4).
    static let sleepPageTitle = "Sleep Cycle"
```

  In `SleepView.swift` replace the header's comment (`:538-540`) and its `HStack` (`:542-560`) with:

```swift
        // The title is `PageTitle`, the same view `PageHeader` draws (Z-B4):
        // the page keeps its own row because the title sits inside the centred
        // column (R-Z6) with the staleness chip beside it (R-A12).
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                // The subtitle stopped rendering (Track Z §4.1); it survives as
                // the title's VoiceOver hint — on this one element, not the
                // page's `ZStack`, where it would spread to every button.
                PageTitle(Copy.sleepPageTitle)
                    .accessibilityHint(Copy.sleepSubtitle)
                // R-A12: the chip explains the dimming below it, so it stays at
                // full contrast and sits outside every desaturated group.
                if let asOf = liveness.asOf {
                    stalenessChip(asOf)
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
```

- [ ] **Step 5: Verify.** `swift test --filter "PileFitTests|PageTitleTests|BookPileTests|DeskSceneLayoutTests|SpineAndLampTests|SleepPageModelTests|FontLiteralLintTests" 2>&1 | tail -20` → 0 failures; then `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 6: Commit** — stage the five sources (`BookPile.swift`, `StudyRoom.swift`,
  `PageHeader.swift`, `SleepView.swift`, `Copy.swift`) and three test files (`PileFitTests.swift`,
  `PageTitleTests.swift`, `DeskSceneLayoutTests.swift`) by name:
  `fix(sleep): the pile fits the room at every zoom and queue; the title is the page title (live check, Z-B1..Z-B4)`.

---

### Task 2: One door, guarded — `feedGuard`, an answer from `accept`, one picker, a veil that yields

Router-level only; no Sleep-page change yet. Every door gains the guard (a drop from a harness
session folder now fails in the panel with a sentence instead of being walked and sniffed), and the
room gets the seams Task 3 needs.

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Support/IntakeRouter.swift` — new types before `IntakeRouter` (`:155`); `IntakeOrigin.answersInPlace` (extension after `:22`); stored `home`/`env`/`nearerDrop` and `init` (`:189-210`); `claimDrop`/`releaseDrop`; `accept` (`:228-247`); `commit` (`:374-393`); `feedGuard`, `refusedRoots`, `resolved` beside `expand` (`:437`); `expand` (`:439-458`) gains a `prune` parameter
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Intake.swift` — three refusal sentences after `:38`; `intakeSentences` (`:131-135`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Intake/IntakeOverlay.swift` — `import UniformTypeIdentifiers`; `IntakePicker` after `IntakeDrop` (`:20`); `IntakeLayer` (`:41-55`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Intake/IntakePanel.swift:98-106` — `chooseFile` through `IntakePicker`
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/FeedGuardTests.swift`
- Test (edit): `IntakeRouterTests.swift:4-31` — `FakeIntakeAPI` records the names it was asked to sniff (`sniffed`), so a test can prove a refused drop sent nothing; new router tests appended to the class

**Interfaces:**
- Produces: `FeedRefusal` (`.claudeSessions`, `.codexSessions`, `.cicadaHome`, `.unreadable`; `panelText`); `IntakeAcceptance`; `IntakeAdmission`; `IntakeOrigin.answersInPlace`; `IntakeRouter.init(api:sleep:home:env:)`; `@discardableResult accept(urls:from:) -> IntakeAcceptance`; `IntakeRouter.feedGuard(urls:home:env:walk:) -> IntakeAdmission`; `IntakeRouter.expand(_:fileManager:prune:)` (the new `prune` defaults to "never", so every existing caller is unchanged); `nearerDrop`, `claimDrop(_:)`, `releaseDrop(_:)`; `IntakePicker.allowedContentTypes` / `.choose() -> [URL]`; `IntakeLayer.showsVeil(windowTargeted:nearerDrop:)`; `Copy.intakeRefusedClaude` / `…Codex` / `…Cicada`.
- Consumes: `IntakeRouter.expand`, `Copy.intakeNothingReadable`, `Copy.intakeBusy`, `Store.toast`; in tests, `FakeSyncAPI` (`StoreTests.swift:49`, `@MainActor`) and `SnapshotCache(root:)`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/FeedGuardTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z R-Z10 / design §7.4 (Z-B5) — the door every intake passes. Built on
/// a temporary home: no test here reads, lists or resolves the person's own
/// `~/.claude`, `~/.codex` or `~/.cicada`.
final class FeedGuardTests: XCTestCase {
    private var home: URL!

    override func setUpWithError() throws {
        home = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("feedguard-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: home) }

    @discardableResult
    private func file(_ path: String, _ body: String = "{}") throws -> URL {
        let url = home.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(body.utf8).write(to: url)
        return url
    }

    private func link(_ path: String, to target: URL) throws -> URL {
        let url = home.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: url, withDestinationURL: target)
        return url
    }

    private func verdict(_ urls: [URL], env: [String: String] = [:]) -> IntakeAdmission {
        IntakeRouter.feedGuard(urls: urls, home: home, env: env)
    }

    private func refusal(_ urls: [URL], env: [String: String] = [:]) -> FeedRefusal? {
        if case .refused(let why) = verdict(urls, env: env) { return why }
        return nil
    }

    func test_aChatGPTExportInDownloadsIsAdmitted() throws {
        let export = try file("Downloads/conversations.json")
        XCTAssertEqual(verdict([export]), .admitted(files: [export], capped: false))
    }

    func test_eachRefusedRootIsRefused_theFolderBeforeItIsWalked() throws {
        let transcript = try file(".claude/projects/alpha-project/session.json")
        XCTAssertEqual(refusal([transcript]), .claudeSessions)
        XCTAssertEqual(refusal([home.appendingPathComponent(".claude")]), .claudeSessions)
        XCTAssertEqual(refusal([try file(".codex/sessions/rollout.json")]), .codexSessions)
        XCTAssertEqual(refusal([try file(".cicada/remote/settings.json")]), .cicadaHome)
        let export = try file("Downloads/conversations.json")
        XCTAssertEqual(refusal([export, transcript]), .claudeSessions, "one refused URL refuses the drop")
    }

    func test_theEnvironmentsOwnHomesAreRefusedToo() throws {
        let claude = try file("elsewhere/claude-config/x.json")
        XCTAssertEqual(refusal([claude], env: ["CLAUDE_CONFIG_DIR": claude.deletingLastPathComponent().path]),
                       .claudeSessions)
        let codex = try file("elsewhere/codex-home/x.json")
        XCTAssertEqual(refusal([codex], env: ["CODEX_HOME": codex.deletingLastPathComponent().path]), .codexSessions)
        let cicada = try file("elsewhere/cicada-home/x.json")
        XCTAssertEqual(refusal([cicada], env: ["CICADA_HOME": cicada.deletingLastPathComponent().path]), .cicadaHome)
        XCTAssertNil(refusal([claude], env: ["CLAUDE_CONFIG_DIR": ""]), "an empty variable names no root")
    }

    func test_aSymlinkIsJudgedByWhereItPoints() throws {
        let transcripts = try file(".claude/projects/alpha-project/a.json").deletingLastPathComponent()
        XCTAssertEqual(refusal([try link("Downloads/looks-harmless", to: transcripts)]), .claudeSessions)
        try file("Downloads/export/conversations.json")
        _ = try link("Downloads/export/extra.json", to: try file(".cicada/secrets.json"))
        XCTAssertEqual(refusal([home.appendingPathComponent("Downloads/export")]), .cicadaHome,
                       "a link inside an innocent folder")
    }

    /// Z-B5 — "refused before it is walked", observed through the walk seam: a
    /// dropped session folder is never handed to the walk, and a refused root
    /// met INSIDE a dropped folder (a visible `$CLAUDE_CONFIG_DIR`) is pruned —
    /// nothing under it is listed — and refuses the drop.
    func test_aRefusedRootIsNeverWalked() throws {
        var walked: [[String]] = []
        var pruned: [String] = []
        func guardWalking(_ urls: [URL], env: [String: String] = [:]) -> IntakeAdmission {
            IntakeRouter.feedGuard(urls: urls, home: home, env: env) { urls, prune in
                walked.append(urls.map(\.lastPathComponent))
                return IntakeRouter.expand(urls) { url in
                    let skip = prune(url)
                    if skip { pruned.append(url.lastPathComponent) }
                    return skip
                }
            }
        }
        let transcripts = try file(".claude/projects/alpha-project/a.json").deletingLastPathComponent()
        XCTAssertEqual(guardWalking([transcripts]), .refused(.claudeSessions))
        XCTAssertEqual(walked, [], "a dropped session folder is refused before any walk")
        try file("Documents/claude-config/projects/alpha-project/b.json")
        try file("Documents/notes.json")
        let config = home.appendingPathComponent("Documents/claude-config")
        XCTAssertEqual(guardWalking([home.appendingPathComponent("Documents")], env: ["CLAUDE_CONFIG_DIR": config.path]),
                       .refused(.claudeSessions))
        XCTAssertEqual(walked, [["Documents"]])
        XCTAssertEqual(pruned, ["claude-config"], "the root itself is pruned; nothing under it is listed")
    }

    func test_aSiblingNameIsNotTheRoot() throws {
        let near = try file(".claudette/notes.json")
        XCTAssertEqual(verdict([near]), .admitted(files: [near], capped: false))
    }

    func test_nothingExportShapedIsUnreadable() throws {
        XCTAssertEqual(refusal([try file("Downloads/cat.png", "png")]), .unreadable)
        try file("Downloads/photos/a.png", "png")
        XCTAssertEqual(refusal([home.appendingPathComponent("Downloads/photos")]), .unreadable)
    }

    func test_everyRefusalHasPanelWords() {
        for why in FeedRefusal.allCases { XCTAssertFalse(why.panelText.isEmpty, "\(why)") }
        XCTAssertEqual(FeedRefusal.unreadable.panelText, Copy.intakeNothingReadable, "the old empty-drop words")
    }
}
```

  In `IntakeRouterTests.swift`, give `FakeIntakeAPI` a record (`:5` and `:12-16`):

```swift
    var sniffed: [String] = []

    func sniffIntake(fileURL: URL, bank: String?) async throws -> IntakeSniff {
        let name = fileURL.lastPathComponent
        sniffed.append(name)
        if let delay = sniffDelay[name] { try await Task.sleep(for: delay) }
        return sniffs[name] ?? IntakeSniff(reason: "unknown")
    }
```

  add `import UniformTypeIdentifiers` at the top, and append to `IntakeRouterTests`:

```swift
    // MARK: Track Z — the room's door (Z-B5 … Z-B8, Z-B17)

    func testTheRoomsRefusalIsTheRoomsToTell_everyOtherDoorShowsIt() throws {
        let api = FakeIntakeAPI()
        let router = IntakeRouter(api: api, home: dir.appendingPathComponent("home"), env: [:])
        let transcript = try file("home/.claude/projects/alpha-project/session.json")
        XCTAssertEqual(router.accept(urls: [transcript], from: .sleepRoom), .refused(.claudeSessions))
        XCTAssertEqual(router.phase, .idle)
        XCTAssertFalse(router.isOverlayPresented, "the worm says it (Z-B6)")
        XCTAssertEqual(router.accept(urls: [transcript], from: .windowDrop), .refused(.claudeSessions))
        XCTAssertTrue(router.isOverlayPresented)
        XCTAssertEqual(router.phase, .failed(Copy.intakeRefusedClaude))
        XCTAssertEqual(api.sniffed, [], "nothing under a refused root is ever sent")
    }

    func testAnAdmittedRoomDropRaisesTheRoutersOwnSheet() throws {
        let router = IntakeRouter(api: FakeIntakeAPI(), home: dir.appendingPathComponent("home"), env: [:])
        XCTAssertEqual(router.accept(urls: [try file("Downloads/conversations.json")], from: .sleepRoom), .accepted)
        XCTAssertTrue(router.isOverlayPresented)
        XCTAssertEqual(router.phase, .reading(["conversations.json"]))
    }

    func testABusyRouterIsTheRoomsToTell() async throws {
        // Never a bare `Store()`: the import below ends in `store.refresh`, and
        // the defaults are the live backend and the real app cache.
        let store = Store(cache: SnapshotCache(root: dir.appendingPathComponent("cache")), api: FakeSyncAPI())
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        api.imports["c.json"] = IntakeImportResponse(job: IntakeJobRef(id: "j", total: 1))
        api.jobPolls = [IntakeJobStatus(id: "j", total: 1, staged: 1, created: 1, done: true)]
        let gate = AsyncStream<Void>.makeStream()
        let router = IntakeRouter(api: api, sleep: { _ in for await _ in gate.stream { break } },
                                  home: dir.appendingPathComponent("home"), env: [:])
        router.attach(store: store)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        try await eventually("importing") { if case .importing = router.phase { true } else { false } }
        XCTAssertEqual(router.accept(urls: [try file("d.json")], from: .sleepRoom), .busy)
        XCTAssertNil(store.toast, "the worm says it; a toast would say it twice")
        XCTAssertEqual(router.accept(urls: [try file("d.json")], from: .windowDrop), .busy)
        XCTAssertEqual(store.toast, Copy.intakeBusy)
        gate.continuation.yield()
        try await eventually("done") { self.isDone(router) }
    }

    func testTheWelcomePathRefusesTheSameRoots() async throws {
        let api = FakeIntakeAPI()
        let router = IntakeRouter(api: api, home: dir.appendingPathComponent("home"), env: [:])
        let outcome = await router.commit(urls: [try file("home/.cicada/api_token.json")], from: .welcome)
        XCTAssertEqual(outcome.failures, [Copy.intakeRefusedCicada])
        XCTAssertEqual(api.importedBanks.count, 0)
    }

    func testTheVeilYieldsToANearerTarget() {
        let router = IntakeRouter(api: FakeIntakeAPI(), home: dir.appendingPathComponent("home"), env: [:])
        router.claimDrop(.sleepRoom)
        XCTAssertEqual(router.nearerDrop, .sleepRoom)
        router.releaseDrop(.windowDrop)
        XCTAssertEqual(router.nearerDrop, .sleepRoom, "only the claimant releases")
        router.releaseDrop(.sleepRoom)
        XCTAssertNil(router.nearerDrop)
        XCTAssertTrue(IntakeLayer.showsVeil(windowTargeted: true, nearerDrop: nil))
        XCTAssertFalse(IntakeLayer.showsVeil(windowTargeted: true, nearerDrop: .sleepRoom))
        XCTAssertFalse(IntakeLayer.showsVeil(windowTargeted: false, nearerDrop: nil))
    }

    /// Z-B17 — one picker, one list of types, for every door.
    func testOneFilePickerForEveryIntakeDoor() throws {
        XCTAssertEqual(IntakePicker.allowedContentTypes,
                       [.zip, .json, .html, .folder, .commaSeparatedText, .plainText, .xml, .propertyList])
        var panels: [String] = []
        for file in try ThemeTokenTests.swiftSources()
        where file.path.contains("/Views/Intake/") || file.path.contains("/Views/Sleep/") {
            let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.hasPrefix("//") }
            if code.contains(where: { $0.contains("NSOpenPanel()") }) { panels.append(file.lastPathComponent) }
        }
        XCTAssertEqual(panels, ["IntakeOverlay.swift"])
    }
```

  Run: `swift test --filter "FeedGuardTests|IntakeRouterTests" 2>&1 | tail -20` → compile failure.

- [ ] **Step 2: The types and the guard.** In `IntakeRouter.swift`, after `IntakeOrigin` (`:22`):

```swift
extension IntakeOrigin {
    /// A door that tells its own outcome — the Sleep room's worm (Track Z
    /// R-Z10, Z-B6). The router neither raises the overlay nor toasts for a
    /// refusal or a busy router there: the worm's line says it, once.
    var answersInPlace: Bool { self == .sleepRoom }
}
```

  and before `protocol IntakeAPI` (`:155`):

```swift
/// What no door may import, whatever the file is (Track Z R-Z10, design §7.4,
/// Z-B5). Named for the worm that asked for it; enforced at every door,
/// because the capture rail is not a Sleep-page rule: transcripts under
/// `~/.claude/` are read by the Stop hook's endpoint and nowhere else, Codex's
/// home is Codex's, and `~/.cicada` holds the api token, `secrets.env` and the
/// remote connectors' database — none of it an export, all of it sniffable.
enum FeedRefusal: String, Equatable, CaseIterable {
    case claudeSessions, codexSessions, cicadaHome, unreadable

    /// The panel's words — every door but the room, which speaks for itself
    /// in the worm's voice (Z-B18).
    var panelText: String {
        switch self {
        case .claudeSessions: Copy.intakeRefusedClaude
        case .codexSessions: Copy.intakeRefusedCodex
        case .cicadaHome: Copy.intakeRefusedCicada
        case .unreadable: Copy.intakeNothingReadable
        }
    }
}

/// `accept`'s answer (Z-B6), so a door that speaks for itself can.
enum IntakeAcceptance: Equatable {
    case accepted
    case refused(FeedRefusal)
    /// An import is still landing; nothing about this drop was read.
    case busy
}

/// The guard's verdict: refused, or the files `expand` found — walked once,
/// and only after every dropped URL cleared the refused roots.
enum IntakeAdmission: Equatable {
    case refused(FeedRefusal)
    case admitted(files: [URL], capped: Bool)
}
```

  In `IntakeRouter`, after `private(set) var inFlight = 0` (`:193`):

```swift
    /// A drop target nearer the pointer than the window has the drag (the
    /// Sleep room, Z-B8): the window's veil steps aside so that target's own
    /// cue — the worm's open mouth, its outline — is not under the scrim.
    private(set) var nearerDrop: IntakeOrigin?
```

  after `@ObservationIgnored private let sleep` (`:196`):

```swift
    /// Where the refused roots are resolved from (Z-B5) — injected so
    /// `FeedGuardTests` runs on a temporary home, never the person's.
    @ObservationIgnored private let home: URL
    @ObservationIgnored private let env: [String: String]
```

  and the `init` (`:206-210`):

```swift
    init(api: any IntakeAPI = APIClient.shared,
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
         home: URL = FileManager.default.homeDirectoryForCurrentUser,
         env: [String: String] = ProcessInfo.processInfo.environment) {
        self.api = api
        self.sleep = sleep
        self.home = home
        self.env = env
    }
```

  Replace `accept` (`:228-247`) with:

```swift
    /// Files arrived. Public on purpose: Track Z's Sleep-room worm calls this
    /// with `.sleepRoom` (design §12 cross-track seam). Every door passes the
    /// same guard (Z-B5); the answer lets a door that speaks for itself do so
    /// (Z-B6) and is discardable everywhere else.
    @discardableResult
    func accept(urls: [URL], from origin: IntakeOrigin) -> IntakeAcceptance {
        guard !isImporting else {
            if !origin.answersInPlace { store?.toast = Copy.intakeBusy }
            return .busy
        }
        switch Self.feedGuard(urls: urls, home: home, env: env) {
        case .refused(let refusal):
            guard !origin.answersInPlace else { return .refused(refusal) }
            host = origin.host
            if host == .overlay { isOverlayPresented = true }
            // As the old empty-drop path did: a refused drop resets the Into
            // picker too (final review, finding 3 — no "New memory" outlives
            // the drop it was chosen for).
            target = .active
            generation &+= 1
            phase = .failed(refusal.panelText)
            return .refused(refusal)
        case .admitted(let found, let wasCapped):
            host = origin.host
            if host == .overlay { isOverlayPresented = true }
            files = found
            capped = wasCapped
            target = .active
            sniff()
            return .accepted
        }
    }

    /// Z-B8 — the room has the drag; the veil yields until it lets go.
    func claimDrop(_ origin: IntakeOrigin) {
        if nearerDrop != origin { nearerDrop = origin }
    }

    /// Only the claimant releases, so a late exit from one target never
    /// clears another's claim.
    func releaseDrop(_ origin: IntakeOrigin) {
        if nearerDrop == origin { nearerDrop = nil }
    }
```

  In `commit` (`:376-378`) replace `var outcome = IntakeOutcome()` / `for url in Self.expand(urls).files {` with:

```swift
        var outcome = IntakeOutcome()
        // The same door as `accept` (Z-B5): a refused root is never walked.
        let files: [URL]
        switch Self.feedGuard(urls: urls, home: home, env: env) {
        case .refused(let refusal):
            outcome.failures.append(refusal.panelText)
            return outcome
        case .admitted(let found, _):
            files = found
        }
        for url in files {
```

  Before `expand` (`:437`), add:

```swift
    /// The door (design §7.4, Z-B5). Order matters: a dropped URL under a
    /// refused root is refused BEFORE `expand` walks it — listing the names in
    /// `~/.claude/projects` is already more than the capture rail allows. The
    /// walk of an innocent folder asks about every entry it meets: a folder
    /// under a refused root is pruned, never descended into (a visible
    /// `$CLAUDE_CONFIG_DIR` inside a dropped `~`), and a file under one (a
    /// symlink can point anywhere) is caught the same way; either refuses the
    /// whole drop. Then a drop with nothing export-shaped in it is refused by
    /// name. Both sides are compared resolved and component by component
    /// (`~/.claudette` is not `~/.claude`). Nothing is opened. `walk` is the
    /// test seam that lets `FeedGuardTests` prove a refused root is never
    /// walked; production always uses `expand`.
    nonisolated static func feedGuard(
        urls: [URL], home: URL, env: [String: String],
        walk: (_ urls: [URL], _ prune: (URL) -> Bool) -> (files: [URL], capped: Bool)
            = { IntakeRouter.expand($0, prune: $1) }
    ) -> IntakeAdmission {
        let roots = refusedRoots(home: home, env: env)
        func refusal(_ url: URL) -> FeedRefusal? {
            let path = resolved(url).pathComponents
            return roots.first { path.starts(with: $0.components) }?.refusal
        }
        if let why = urls.lazy.compactMap(refusal).first { return .refused(why) }
        var inner: FeedRefusal?
        let walked = walk(urls) { url in
            guard let why = refusal(url) else { return false }
            if inner == nil { inner = why }
            return true
        }
        // `inner` covers everything the walk met; the second look covers a
        // custom `walk` that ignores `prune` (defence in depth, zero cost).
        if let why = inner ?? walked.files.lazy.compactMap(refusal).first { return .refused(why) }
        guard !walked.files.isEmpty else { return .refused(.unreadable) }
        return .admitted(files: walked.files, capped: walked.capped)
    }

    /// The three homes and their environment overrides, resolved once per call.
    nonisolated static func refusedRoots(home: URL, env: [String: String])
        -> [(components: [String], refusal: FeedRefusal)] {
        var roots: [(URL, FeedRefusal)] = [
            (home.appendingPathComponent(".claude"), .claudeSessions),
            (home.appendingPathComponent(".codex"), .codexSessions),
            (home.appendingPathComponent(".cicada"), .cicadaHome),
        ]
        let overrides: [(String, FeedRefusal)] = [("CLAUDE_CONFIG_DIR", .claudeSessions),
                                                  ("CODEX_HOME", .codexSessions),
                                                  ("CICADA_HOME", .cicadaHome)]
        for (key, refusal) in overrides {
            guard let value = env[key], !value.isEmpty else { continue }
            roots.append((URL(fileURLWithPath: (value as NSString).expandingTildeInPath), refusal))
        }
        return roots.map { (components: resolved($0.0).pathComponents, refusal: $0.1) }
    }

    nonisolated static func resolved(_ url: URL) -> URL { url.resolvingSymlinksInPath().standardizedFileURL }
```

  and give `expand` (`:437-458`) its `prune` — the signature and the walk loop change, nothing else:

```swift
    /// Folders walked, hidden files and `__MACOSX` skipped, export-shaped
    /// extensions kept, capped at `maxFiles` with a stated warning. `prune`
    /// (Z-B5) is asked about every entry the walk meets; `true` skips it and,
    /// for a folder, everything under it — so a refused root inside a dropped
    /// folder is never listed. It defaults to "never", which is today's walk.
    nonisolated static func expand(_ urls: [URL], fileManager fm: FileManager = .default,
                                   prune: (URL) -> Bool = { _ in false }) -> (files: [URL], capped: Bool) {
```

  and inside it `while let next = walker?.nextObject() as? URL, out.count <= maxFiles { consider(next) }`
  becomes

```swift
                while let next = walker?.nextObject() as? URL, out.count <= maxFiles {
                    if prune(next) { walker?.skipDescendants(); continue }
                    consider(next)
                }
```

  (The seam was prototyped against the SDK: `FileManager.enumerator(at:…)` is `@nonobjc` in the
  Swift overlay, so a recording `FileManager` subclass cannot override it — which is why the test
  seam is the `walk` closure, not a fake file manager.)

  In `Copy+Intake.swift`, after `intakeUnreadable` (`:38`):

```swift
    /// Track Z Z-B5/Z-B18 — the panel's words when a door refuses a folder that
    /// is not an export (the Sleep room's worm says the same in its own voice).
    /// "Once it's connected" is the condition, not a promise: capture needs
    /// the agent wired (the Stop hook, G105). Never "Cicada never reads these":
    /// the hook's endpoint does read a session's transcript, and "read" here
    /// is also a Sleep read (Track I final review, finding 7).
    static let intakeRefusedClaude = "Claude Code sessions come in on their own once it's connected, so there's nothing to import here."
    static let intakeRefusedCodex = "Codex sessions come in on their own once it's connected, so there's nothing to import here."
    static let intakeRefusedCicada = "That's Cicada's own folder, so it can't be imported."
```

  and add the three to `intakeSentences` (`:131-135`) — `CopyConstantsTests.testIntakeLabelsAreShortAndNeverSayClaim` then holds them to its vocabulary rule.

- [ ] **Step 3: One picker, a veil that yields.** In `IntakeOverlay.swift` add `import
  UniformTypeIdentifiers` and, after `IntakeDrop` (`:20`):

```swift
/// The one file picker every intake door opens (Z-B17) — the panel's *Choose a
/// file…* and the Sleep room's *Feed a file…* (Track Z I16) — so no door can
/// drift to a narrower list of types than the panel reads.
enum IntakePicker {
    static let allowedContentTypes: [UTType] = [.zip, .json, .html, .folder, .commaSeparatedText, .plainText,
                                                .xml, .propertyList]

    /// Runs the open panel. An empty list means the person cancelled.
    @MainActor
    static func choose() -> [URL] {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = allowedContentTypes
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = Copy.intakeDropTitle
        return panel.runModal() == .OK ? panel.urls : []
    }
}
```

  `IntakeLayer` (`:41-55`) becomes:

```swift
struct IntakeLayer: View {
    let dropTargeted: Bool
    @Environment(IntakeRouter.self) private var intake
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// Z-B8 — the veil yields to a nearer target that has the drag (the Sleep
    /// room): its own cue would sit under the scrim otherwise. Pure; tested.
    static func showsVeil(windowTargeted: Bool, nearerDrop: IntakeOrigin?) -> Bool {
        windowTargeted && nearerDrop == nil
    }

    var body: some View {
        let veil = Self.showsVeil(windowTargeted: dropTargeted, nearerDrop: intake.nearerDrop)
        ZStack {
            if intake.isOverlayPresented { IntakeOverlay().transition(.opacity) }
            if veil { IntakeDropVeil().transition(.opacity) }
        }
        .animation(CicadaMotion.dropVeil(reduceMotion: reduceMotion), value: veil)
        .animation(CicadaMotion.panel(reduceMotion: reduceMotion), value: intake.isOverlayPresented)
    }
}
```

  In `IntakePanel.swift` (`:98-106`):

```swift
    private func chooseFile() {
        let urls = IntakePicker.choose()
        guard !urls.isEmpty else { return }
        intake.accept(urls: urls, from: origin)
    }
```

- [ ] **Step 4: Verify.** `swift test --filter "FeedGuardTests|IntakeRouterTests|IntakePreviewTests|IntakeSummaryTests|CopyConstantsTests" 2>&1 | tail -20` → 0 failures (every pre-existing `IntakeRouterTests` case passes unmodified: their files sit under the temp dir, which is under no refused root); then `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 5: Commit** — stage `IntakeRouter.swift`, `Copy+Intake.swift`, `IntakeOverlay.swift`, `IntakePanel.swift`, `FeedGuardTests.swift`, `IntakeRouterTests.swift`:
  `feat(intake): one guarded door — feedGuard refuses harness and Cicada homes at every door; accept answers; one picker; the veil yields (Track Z Z9 seams, Z-B5..Z-B8, Z-B17)`.

---

### Task 3 (Z9): Feeding — the worm eats a file through the one intake

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomFeed.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomModel.swift` — drag and feed state after `recentCycleCommit` (`:61`); `poke` (`:95-100`); the feed methods after `hover` (`:112-118`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyRoom.swift` — imports; `reachable` + the intake environment (`:84-96`); `DropOutline`, the drop target (`:156-175`); `WormStage.pose` (`:181-194`); `WormHotspot`'s `onFeed`, Esc, context menu and actions (`:201-256`); `feed(_:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomSentence.swift` — T13 after T12 (`:264-269`); `RoomSentenceView` (`:288-431`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — `:241` (mood change → `dismissSlot`), `:629-649` (`reachable`, `feedAsleep`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift:64-67` — `wormHint`, `feedAFile`
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/RoomFeedTests.swift`
- Test (edit — T13 now claims `.happy`'s tail on a loaded queue, Z-B19): `RoomSentenceTests.swift:137` (`test_T8_T9`: the unloaded-debt check becomes "not the first-night line"), `:149` (`test_T11`: a happy page with nothing waiting now says T13), `:160-163` (`test_T14`: the no-tail case moves to `.digesting`), the class docstring (`:4-6`: "T1–T12, T14; T13 lands with feeding" → "T1–T14"); add `test_T13_aHappyWormInvitesAFile`. `test_L2_theQueueIsLoading` (`:35-39`, a `.happy` context with a loading queue) is NOT edited — T13's loaded-queue gate is what keeps it green.

**Interfaces:**
- Produces: `RoomDrag` (`pose`); `FeedLanding(_ outcome:)`; `FeedResult` (`init(_ acceptance:)`, `isTerminal`); `FeedPhase` (`init?(_ phase: IntakePhase)`); `feedLine(_:asleep:) -> SentenceLine`; `feedIsAsleep(_:)`; `roomFeedResult(reachable:accept:)`; `RoomDropDelegate`; `RoomModel.drag` / `.feedResult` / `dragMoved(to:scene:spots:state:)` / `dragEnded()` / `fed(_:state:now:reduceMotion:)` / `intakeChanged(from:to:) -> FeedLanding?` / `dismissSlot()` / `feedPhase(drag:result:intakePhase:)` / `beat(for:)`; `WormStage.pose(drag:pointerInRoom:gaze:)`; `StudyRoom(… reachable:)`; `RoomSentenceView(… feedAsleep:)`; `Copy.feedAFile`.
- Consumes: `IntakeRouter.accept` / `.phase` / `.claimDrop` / `.releaseDrop`, `IntakePicker.choose()`, `IntakeDrop.load`, `IntakeAcceptance`, `FeedRefusal`, `IntakePhase`, `IntakeOutcome`, `gazeFor`, `sceneBottomLeading`, `deskHotspots`, `BookwormPose.effective`, `RoomModel.play`, `SleepMotion.hover` / `.answerDwell`, `SleepLiveness`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/RoomFeedTests.swift`:

```swift
import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z Z9 (design §7.4, I12–I16; Z-B6 … Z-B11) — feeding is import, and
/// only import (R-Z10): the room is a door onto the one intake, its lines tell
/// the router's own outcome in words with no number (R-Z3), and every beat is
/// one the §6.4 matrix allows.
@MainActor
final class RoomFeedTests: XCTestCase {

    private let scene = deskSceneLayout(pointSize: 120, uiScale: 1.0)
    private var spots: [DeskHotspot: CGRect] { deskHotspots(scene) }
    /// Top-left points (what `DropInfo.location` reports) at 5 pt cells.
    private let overWorm = CGPoint(x: 200, y: 70)
    private let overLamp = CGPoint(x: 20, y: 100)

    private var everyPhase: [FeedPhase] {
        let refusals: [FeedPhase] = FeedRefusal.allCases.map(FeedPhase.refused)
        let rest: [FeedPhase] = [.busy, .unreachable, .reading, .preview, .importing,
                                 .landed(.added), .landed(.nothingNew), .landed(.elsewhere), .failed]
        return [.armed(overWorm: false), .armed(overWorm: true)] + refusals + rest
    }

    // MARK: The lines (R-Z13, R-Z3)

    func test_everyFeedLineFitsTheSlot_andCarriesNoNumber() {
        for phase in everyPhase {
            for asleep in [false, true] {
                let line = feedLine(phase, asleep: asleep)
                XCTAssertFalse(line.lead.isEmpty)
                XCTAssertLessThanOrEqual(line.lead.count, SentenceLine.maxLead, line.lead)
                XCTAssertLessThanOrEqual(line.tail?.count ?? 0, SentenceLine.maxTail, line.tail ?? "")
                XCTAssertFalse(line.spoken.contains("!"), line.spoken)
                XCTAssertFalse(line.spoken.contains("%"), line.spoken)
                XCTAssertFalse(line.spoken.contains("~"), line.spoken)
                // R-Z13's banned words, split the way `RoomSentenceTests` splits them.
                let words = line.spoken.lowercased().split { !$0.isLetter }.map(String.init)
                for word in ["est", "cluster", "insight"] { XCTAssertFalse(words.contains(word), line.spoken) }
                XCTAssertFalse(line.spoken.contains(where: \.isNumber), "R-Z3 — the panel has the counts: \(line.spoken)")
                XCTAssertNil(line.action, "a feed line never links: the next step is in the panel")
            }
        }
    }

    /// Z-B18 — "saved links", not the design's "notes": a note is not an
    /// export the intake reads, so the worm must never refuse one and then
    /// say notes work.
    func test_theArmedLines() {
        XCTAssertEqual(feedLine(.armed(overWorm: false), asleep: false),
                       SentenceLine(lead: "Is that for me?", tail: "Chat exports, bookmarks, feeds and saved links."))
        XCTAssertEqual(feedLine(.armed(overWorm: true), asleep: false).lead, "Drop it on me.")
        XCTAssertEqual(feedLine(.armed(overWorm: false), asleep: true).tail, "I'll read it next cycle.")
    }

    /// Z-B18 — the worm's voice, and a named service wears its mark (Z-P26).
    func test_theRefusalsSpeakInTheWormsVoice() {
        XCTAssertEqual(feedLine(.refused(.claudeSessions), asleep: false),
                       SentenceLine(lead: "I don't eat those.",
                                    tail: "Claude Code sessions come to me once it's connected.",
                                    mark: .origin("claude-code")))
        XCTAssertEqual(feedLine(.refused(.codexSessions), asleep: false).mark, .origin("codex"))
        XCTAssertEqual(feedLine(.refused(.cicadaHome), asleep: false).lead, "That's my own folder.")
        XCTAssertNil(feedLine(.refused(.cicadaHome), asleep: false).mark)
        XCTAssertEqual(feedLine(.refused(.unreadable), asleep: false),
                       SentenceLine(lead: "I can't read that yet.", tail: "Chat exports, bookmarks, feeds and saved links work."))
        XCTAssertEqual(feedLine(.busy, asleep: false).lead, "I'm still eating the last one.")
        XCTAssertEqual(feedLine(.unreachable, asleep: false).tail, "Nothing was sent. Try again in a moment.")
    }

    /// A sleeping worm takes the drop and says when it will read it (I15).
    func test_asleep_theWormSaysWhenItWillRead() {
        for phase in [FeedPhase.reading, .importing, .landed(.added)] {
            XCTAssertEqual(feedLine(phase, asleep: true).tail, "I'll read it after this nap.", "\(phase)")
        }
        XCTAssertEqual(feedLine(.landed(.added), asleep: false), SentenceLine(lead: "Got it.", tail: "It's on the pile now."))
    }

    /// Z-B9 — the router's own phase drives the line.
    func test_theRoutersPhaseIsTheLine() {
        XCTAssertNil(FeedPhase(.idle))
        XCTAssertEqual(FeedPhase(.reading(["conversations.json"])), .reading)
        XCTAssertEqual(FeedPhase(.preview(IntakePreview())), .preview)
        XCTAssertEqual(FeedPhase(.importing(IntakeProgress(total: 3, staged: 1))), .importing)
        XCTAssertEqual(FeedPhase(.done(IntakeOutcome(created: 2))), .landed(.added))
        XCTAssertEqual(FeedPhase(.done(IntakeOutcome(unchanged: 4))), .landed(.nothingNew))
        XCTAssertEqual(FeedPhase(.done(IntakeOutcome(created: 2, bank: "alpha-project", bankIsActive: false))),
                       .landed(.elsewhere))
        XCTAssertEqual(FeedPhase(.failed("Nothing here is an export Cicada can read.")), .failed)
    }

    // MARK: The room (I12–I16)

    func test_aDragArmsTheWormTowardIt_andEagerOverIt() {
        let room = RoomModel()
        room.dragMoved(to: overLamp, scene: scene, spots: spots, state: .happy)
        XCTAssertEqual(room.drag, .overRoom(.left))
        XCTAssertEqual(WormStage.pose(drag: room.drag, pointerInRoom: false, gaze: .center), .expectant(.left))
        room.dragMoved(to: overWorm, scene: scene, spots: spots, state: .happy)
        XCTAssertEqual(room.drag, .overWorm)
        XCTAssertEqual(WormStage.pose(drag: room.drag, pointerInRoom: true, gaze: .right), .eager,
                       "a drag outranks the pointer")
        room.dragEnded()
        XCTAssertNil(room.drag)
        XCTAssertEqual(WormStage.pose(drag: nil, pointerInRoom: true, gaze: .right), .attentive(.right))
    }

    /// Z-B10 — a gulp for what the router took, a shake for anything it did not.
    func test_yesGulps_noShakes() {
        let took = RoomModel()
        XCTAssertTrue(took.fed(.handedOver, state: .happy, reduceMotion: false))
        XCTAssertEqual(took.reaction?.kind, .gulp)
        for no in [FeedResult.refused(.unreadable), .busy, .unreachable] {
            let room = RoomModel()
            room.fed(no, state: .reading, reduceMotion: false)
            XCTAssertEqual(room.reaction?.kind, .shake, "\(no)")
        }
        let still = RoomModel()
        still.fed(.handedOver, state: .happy, reduceMotion: true)
        XCTAssertNil(still.reaction, "Reduce Motion: the line, no beat")
        XCTAssertEqual(still.feedResult, .handedOver)
        let failed = RoomModel()
        failed.fed(.refused(.unreadable), state: .error, reduceMotion: false)
        XCTAssertNil(failed.reaction, "an erroring worm answers in words only (§6.4)")
    }

    /// I15 — a drop while asleep still goes through; the worm stays asleep.
    func test_aSleepingWormTakesTheDropAndStaysAsleep() throws {
        let room = RoomModel()
        room.dragMoved(to: overWorm, scene: scene, spots: spots, state: .sleeping(stage: 2))
        XCTAssertEqual(BookwormPose.eager.effective(for: .sleeping(stage: 2), reduceMotion: false), .idle,
                       "no open mouth under the nightcap")
        room.fed(.handedOver, state: .sleeping(stage: 2), reduceMotion: false)
        XCTAssertNil(room.reaction, "no gulp — the nightcap stays on")
        XCTAssertEqual(room.feedResult, .handedOver, "…but the drop went through")
        let running = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(#"{"status":"running","stage":0}"#.utf8))
        XCTAssertEqual(deriveSleepPageMood(status: running, debt: nil, justFinishedAt: nil, intakeInFlight: true),
                       .sleeping(stage: 1), "an intake landing mid-cycle never wakes the page")
    }

    /// Z-B9 / Z-B11 — which line the slot shows, and when it ends.
    func test_theSlotsFeedLine_andWhatEndsIt() {
        XCTAssertEqual(RoomModel.feedPhase(drag: .overWorm, result: .refused(.unreadable), intakePhase: .idle),
                       .armed(overWorm: true), "a new drag outranks the last drop")
        XCTAssertNil(RoomModel.feedPhase(drag: nil, result: .handedOver, intakePhase: .idle))
        XCTAssertEqual(RoomModel.feedPhase(drag: nil, result: .handedOver, intakePhase: .reading(["a.json"])), .reading)
        let room = RoomModel()
        room.fed(.handedOver, state: .happy, reduceMotion: false)
        let outcome = IntakeOutcome(created: 3)
        XCTAssertNil(room.intakeChanged(from: .reading(["a.json"]), to: .preview(IntakePreview())))
        XCTAssertEqual(room.intakeChanged(from: .done(outcome), to: .idle), .added)
        XCTAssertEqual(room.feedResult, .landed(.added), "the landing outlives the done card")
        room.dismissSlot()
        XCTAssertNil(room.feedResult)
        let cancelled = RoomModel()
        cancelled.fed(.handedOver, state: .happy, reduceMotion: false)
        XCTAssertNil(cancelled.intakeChanged(from: .preview(IntakePreview()), to: .idle))
        XCTAssertNil(cancelled.feedResult, "a cancel goes back to the status")
        let live = RoomModel()
        live.fed(.handedOver, state: .happy, reduceMotion: false)
        live.dismissSlot()
        XCTAssertEqual(live.feedResult, .handedOver, "a live intake's line is still true")
        let poked = RoomModel()
        poked.fed(.busy, state: .happy, reduceMotion: false)
        poked.poke(answerCount: 2, state: .happy, reduceMotion: false)
        XCTAssertNil(poked.feedResult)
        XCTAssertEqual(poked.answerIndex, 0)
    }

    /// I15 — a stale page never asks the router, so nothing is sent.
    func test_anOfflinePageSendsNothing() {
        XCTAssertEqual(roomFeedResult(reachable: false) { XCTFail("the router was asked"); return .accepted },
                       .unreachable)
        XCTAssertEqual(roomFeedResult(reachable: true) { .busy }, .busy)
        XCTAssertEqual(roomFeedResult(reachable: true) { .refused(.cicadaHome) }, .refused(.cicadaHome))
        XCTAssertEqual(roomFeedResult(reachable: true) { .accepted }, .handedOver)
    }

    // MARK: Lints — R-Z10: a door, never a second pipeline

    private func code(_ file: URL) throws -> [String] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.hasPrefix("//") }
    }

    func test_theRoomIsADoorOntoTheOneIntake() throws {
        var accepting: [String] = []
        var dropping: [String] = []
        for file in try SleepNumbersLintTests.sleepSources() {
            let lines = try code(file)
            for needle in ["sniffIntake(", "importIntake(", "uploadSaved(", "NSOpenPanel", "APIClient.shared"] {
                XCTAssertFalse(lines.contains { $0.contains(needle) }, "\(file.lastPathComponent) reaches past the router: \(needle)")
            }
            if lines.contains(where: { $0.contains(".accept(urls:") }) { accepting.append(file.lastPathComponent) }
            if lines.contains(where: { $0.contains(".onDrop(") }) { dropping.append(file.lastPathComponent) }
        }
        XCTAssertEqual(accepting, ["StudyRoom.swift"])
        XCTAssertEqual(dropping, ["StudyRoom.swift"])
        let room = try code(try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "StudyRoom.swift" }!)
        XCTAssertTrue(room.contains { $0.contains("from: .sleepRoom") })
        XCTAssertTrue(room.contains { $0.contains("RoomDropDelegate(") })
    }

    func test_theHintIsTrueNowThatFeedingShipped() {
        XCTAssertEqual(Copy.wormHint, "Click to ask what it's doing. Drop a file to import it.")
        XCTAssertEqual(Copy.feedAFile, "Feed a file…")
    }
}
```

  In `RoomSentenceTests.swift` add

```swift
    /// T13 (Z-B19) — feeding shipped, so a happy worm invites a file.
    func test_T13_aHappyWormInvitesAFile() {
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0))).tail, "Drop a file on me to add it to the pile.")
        XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0))).mark)
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0, hasRunBefore: false))).tail,
                       "Nothing's been filed in this memory yet.", "T9 before T13")
    }
```

  and re-point the three assertions that pinned "no tail" on a happy, loaded page (Z-B19):
  `:137` → `XCTAssertNotEqual(roomSentence(ctx(.happy, debt: nil)).tail, "Nothing's been filed in this
  memory yet.", "an unloaded debt is never reported as a first night")`; `:149` →
  `XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0)) { $0.scheduleMode = "manual" }).tail, "Drop a
  file on me to add it to the pile.", "nothing waits, so no lamp line — T13 speaks instead")`;
  `test_T14_nothingToAdd` (`:160-163`) → both assertions on `ctx(.digesting, debt: debt(0))`. Add to
  `test_T13_aHappyWormInvitesAFile` the gate:
  `XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0)) { $0.queueLoad = .loading }).tail, "no invitation while the queue is still loading")`.
  The class docstring (`:4-6`) now reads "…and the tail table (T1–T14) is a case…".
  Run: `swift test --filter "RoomFeedTests|RoomSentenceTests" 2>&1 | tail -20` → compile failure.

- [ ] **Step 2: `RoomFeed.swift`.** Create `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomFeed.swift`:

```swift
import SwiftUI
import UniformTypeIdentifiers

// MARK: - Feeding (Track Z Z9, design §7.4, R-Z10)
//
// Feeding is import, and only import: a drop on the room — or "Feed a file…"
// — goes to the one `IntakeRouter` (its guard, its sheet, its
// `intakeInFlight`) and to nothing else. This file is the room's side of that
// door: where a drag is, what a drop came to, and the words the worm says
// about it. There is no hunger mechanic, no nag and no reward loop, and
// feeding never "cures" `.hungry` — only a cycle does.

/// Where a drag is over the room (I12, I13) — response art's input, never a fact.
enum RoomDrag: Equatable {
    case overRoom(Gaze)
    case overWorm

    /// Expectant toward the drag, eager over the worm (§6.1). `BookwormPose
    /// .effective` folds both away where they would contradict state art (a
    /// sleeping worm keeps its nightcap and its shut eyes).
    var pose: BookwormPose {
        switch self {
        case .overRoom(let gaze): .expectant(gaze)
        case .overWorm: .eager
        }
    }
}

/// What an intake the room handed over came to, with no number in it (R-Z3:
/// one file and a thousand get the same line — the panel has the counts).
enum FeedLanding: Hashable {
    case added, nothingNew, elsewhere

    init(_ outcome: IntakeOutcome) {
        if outcome.total == 0 {
            self = .nothingNew
        } else if outcome.inactiveBank != nil {
            self = .elsewhere
        } else {
            self = .added
        }
    }
}

/// The room's record of its last drop (I15, Z-B9).
enum FeedResult: Equatable {
    /// The router took it; the router's own phase now drives the line.
    case handedOver
    /// The done card closed on a finished import — said once, then it dwells away.
    case landed(FeedLanding)
    case refused(FeedRefusal)
    case busy
    /// The page is stale (R-A12): nothing was sent.
    case unreachable

    /// Everything but a live intake ends with the moment it described (Z-B11).
    var isTerminal: Bool { self != .handedOver }

    init(_ acceptance: IntakeAcceptance) {
        switch acceptance {
        case .accepted: self = .handedOver
        case .refused(let refusal): self = .refused(refusal)
        case .busy: self = .busy
        }
    }
}

/// The line the slot shows while feeding is under way. `Hashable`: the slot
/// cross-fades on it.
enum FeedPhase: Hashable {
    case armed(overWorm: Bool)
    case refused(FeedRefusal)
    case busy
    case unreachable
    case reading
    case preview
    case importing
    case landed(FeedLanding)
    case failed

    /// The router's own phase, as the room tells it (Z-B9). `.idle` is no line.
    init?(_ phase: IntakePhase) {
        switch phase {
        case .idle: return nil
        case .reading: self = .reading
        case .preview: self = .preview
        case .importing: self = .importing
        case .done(let outcome): self = .landed(FeedLanding(outcome))
        case .failed: self = .failed
        }
    }
}

/// A sleeping worm stays asleep through a drop (§6.4) and says when it will read.
func feedIsAsleep(_ mood: BookwormState) -> Bool {
    if case .sleeping = mood { return true }
    return false
}

/// The feed lines (§7.4, I12–I15): pure `SentenceLine`s under R-Z13 (lead ≤ 40,
/// tail ≤ 80, no "!", no guess) with no digit at all (R-Z3), in the worm's own
/// first person (Z-B18). A line that names a service wears its mark (Z-P26).
func feedLine(_ phase: FeedPhase, asleep: Bool) -> SentenceLine {
    let afterTheNap = "I'll read it after this nap."
    switch phase {
    case .armed(let overWorm):
        // "saved links", not "notes" (Z-B18): a note is not an export the intake reads.
        return SentenceLine(lead: overWorm ? "Drop it on me." : "Is that for me?",
                            tail: asleep ? "I'll read it next cycle." : "Chat exports, bookmarks, feeds and saved links.")
    case .refused(.claudeSessions):
        return SentenceLine(lead: "I don't eat those.", tail: "Claude Code sessions come to me once it's connected.",
                            mark: .origin("claude-code"))
    case .refused(.codexSessions):
        return SentenceLine(lead: "I don't eat those.", tail: "Codex sessions come to me once it's connected.",
                            mark: .origin("codex"))
    case .refused(.cicadaHome):
        return SentenceLine(lead: "That's my own folder.", tail: "I keep my things there, so I can't eat it.")
    case .refused(.unreadable):
        return SentenceLine(lead: "I can't read that yet.", tail: "Chat exports, bookmarks, feeds and saved links work.")
    case .busy:
        return SentenceLine(lead: "I'm still eating the last one.", tail: "Drop it again when that's done.")
    case .unreachable:
        return SentenceLine(lead: "I'm offline right now.", tail: "Nothing was sent. Try again in a moment.")
    case .reading:
        return SentenceLine(lead: "Let me see what's in it.", tail: asleep ? afterTheNap : nil)
    case .preview:
        return SentenceLine(lead: "Have a look first.", tail: "Import it when it looks right.")
    case .importing:
        return SentenceLine(lead: "Adding it to the pile…", tail: asleep ? afterTheNap : nil)
    case .landed(.added):
        return SentenceLine(lead: "Got it.", tail: asleep ? afterTheNap : "It's on the pile now.")
    case .landed(.nothingNew):
        return SentenceLine(lead: "I already had all of that.")
    case .landed(.elsewhere):
        return SentenceLine(lead: "That went to another memory.", tail: "It waits there, not on this pile.")
    case .failed:
        return SentenceLine(lead: "I couldn't take that.", tail: "The panel says why.")
    }
}

/// I15 — a stale page answers without asking the router, so nothing is sent
/// (Z-B9); otherwise the router's answer — its guard, its busy state — is the room's.
@MainActor
func roomFeedResult(reachable: Bool, accept: () -> IntakeAcceptance) -> FeedResult {
    reachable ? FeedResult(accept()) : .unreachable
}

/// The whole room is the drop target (§7.4). The innermost target wins the
/// drop, and it claims the drag so the window's veil steps aside (Z-B8). The
/// guard runs at the drop, not during the hover (Z-B7): while a file hovers,
/// the worm is expectant for any file URL.
@MainActor
struct RoomDropDelegate: DropDelegate {
    let room: RoomModel
    let intake: IntakeRouter
    let scene: DeskSceneLayout
    let spots: [DeskHotspot: CGRect]
    let mood: BookwormState
    let onDrop: @MainActor ([URL]) -> Void

    func validateDrop(info: DropInfo) -> Bool { info.hasItemsConforming(to: [.fileURL]) }

    func dropEntered(info: DropInfo) {
        intake.claimDrop(.sleepRoom)
        room.dragMoved(to: info.location, scene: scene, spots: spots, state: mood)
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        room.dragMoved(to: info.location, scene: scene, spots: spots, state: mood)
        return DropProposal(operation: .copy)
    }

    func dropExited(info: DropInfo) {
        room.dragEnded()
        intake.releaseDrop(.sleepRoom)
    }

    /// The armed pose holds until the URLs have loaded and the router has
    /// answered — `fed` ends the drag — so the slot never flashes back to the
    /// status between the drop and its line.
    func performDrop(info: DropInfo) -> Bool {
        intake.releaseDrop(.sleepRoom)
        IntakeDrop.load(info.itemProviders(for: [.fileURL])) { urls in onDrop(urls) }
        return true
    }
}
```

- [ ] **Step 3: `RoomModel`.** After `recentCycleCommit` (`:61`):

```swift
    /// Track Z Z9 (I12–I14) — where a drag is over the room; nil when none.
    /// Written only on a change, and read only by `WormStage`, the outline and
    /// the slot (§10: a drag redraws the leaves, never the page).
    var drag: RoomDrag?
    /// I15 — what the last drop came to, while the slot still tells it (Z-B9).
    var feedResult: FeedResult?
```

  In `poke` (`:95-100`), first line: `if feedResult?.isTerminal == true { feedResult = nil }` (Z-B11: a
  poke asks a new question). After `hover(origin:inside:)` (`:112-118`):

```swift
    // MARK: Feeding (Track Z Z9, §7.4)

    /// I12/I13 — `DropInfo.location` is top-left in the room's space. Over the
    /// worm's hotspot the worm is eager; elsewhere it looks toward the drag
    /// with the pointer's own hysteresis (`gazeFor`). A new drag replaces
    /// whatever the last drop said (Z-B11).
    func dragMoved(to location: CGPoint, scene: DeskSceneLayout, spots: [DeskHotspot: CGRect], state: BookwormState) {
        let inWorm = spots[.worm]?.contains(sceneBottomLeading(location, in: scene)) ?? false
        var previous = Gaze.center
        if case .overRoom(let gaze) = drag { previous = gaze }
        let next: RoomDrag = inWorm ? .overWorm
            : .overRoom(gazeFor(pointerX: location.x, layout: scene, previous: previous, state: state))
        if drag != next { drag = next }
        if feedResult?.isTerminal == true { feedResult = nil }
    }

    /// I14 — the drag left the room, or dropped.
    func dragEnded() {
        if drag != nil { drag = nil }
    }

    /// I15 — the drop's result: the line, and the beat §6.4 allows (Z-B10).
    /// A sleeping or erroring worm plays nothing and stays as it is; Reduce
    /// Motion plays nothing. Returns whether a beat started.
    @discardableResult
    func fed(_ result: FeedResult, state: BookwormState, now: Date = Date(), reduceMotion: Bool) -> Bool {
        dragEnded()
        dismissAnswers()
        feedResult = result
        return play(Self.beat(for: result), state: state, now: now, reduceMotion: reduceMotion)
    }

    /// Z-B10 — one gesture for yes, one for no.
    static func beat(for result: FeedResult) -> BookwormReaction {
        result == .handedOver ? .gulp : .shake
    }

    /// Follows the router's phase (the slot's `onChange`). A drop the room
    /// handed over lands as a `.landed` line when the done card closes; a
    /// cancel or a failure closes back to the status. Returns the landing so
    /// the slot can announce it — the person pressed Done (§11).
    @discardableResult
    func intakeChanged(from old: IntakePhase, to new: IntakePhase) -> FeedLanding? {
        guard feedResult == .handedOver, new == .idle else { return nil }
        guard case .done(let outcome) = old else {
            feedResult = nil
            return nil
        }
        let landing = FeedLanding(outcome)
        feedResult = .landed(landing)
        return landing
    }

    /// Esc, the dwell, a mood change (Z-B11): back to the status — the answer
    /// on show and any feed line about a moment that has passed. A live
    /// intake's line stays, because it is still true.
    func dismissSlot() {
        dismissAnswers()
        if feedResult?.isTerminal == true { feedResult = nil }
    }

    /// Which feed line the slot shows, if any (§7.4, Z-B9). A drag in
    /// progress outranks the last drop; a handed-over drop follows the
    /// router's own phase until the panel closes.
    static func feedPhase(drag: RoomDrag?, result: FeedResult?, intakePhase: IntakePhase) -> FeedPhase? {
        if let drag { return .armed(overWorm: drag == .overWorm) }
        guard let result else { return nil }
        switch result {
        case .handedOver: return FeedPhase(intakePhase)
        case .landed(let landing): return .landed(landing)
        case .refused(let refusal): return .refused(refusal)
        case .busy: return .busy
        case .unreachable: return .unreachable
        }
    }
```

- [ ] **Step 4: The room takes the drop.** `StudyRoom.swift`: add `import UniformTypeIdentifiers`;
  in `StudyRoom` after `onWhatChanged` (`:94`):

```swift
    /// Track Z Z9 (I15) — false while the page is stale (R-A12): a drop is
    /// declined in the worm's words and nothing is sent (Z-B9).
    var reachable: Bool = true

    @Environment(IntakeRouter.self) private var intake
```

  the worm hotspot's call (`:149-151`) gains a last argument after `whatChanged: onWhatChanged` (the
  memberwise order — `onFeed` is declared after `whatChanged`):
  `whatChanged: onWhatChanged, onFeed: { feed(IntakePicker.choose()) })`; and the tail of `body`
  (`:156-175`) becomes (the hover comment block is today's, unchanged — `.contentShape` must stay
  the last code line before `.onContinuousHover`, `testTheWholeRoomIsTheHoverSurface`):

```swift
        .frame(width: scene.size.width, height: scene.size.height, alignment: .bottomLeading)
        // I12 — the drop cue is chrome (a stroke), and a leaf: a drag redraws it alone.
        .overlay { DropOutline(room: room) }
        // The whole room is the hover surface (Task 6 review r1). Hover only
        // reaches the parts of a view that hit-test, and the art and the worm
        // are `.allowsHitTesting(false)` (and a `.frame` adds no hit area), so
        // without this the pointer registered only over the hotspot and the
        // pile: the gaze never turned left over the lamp or the window (I1),
        // and the dwell counted a pointer resting there as gone. Children with
        // their own gestures sit above this shape and keep their clicks — the
        // same pattern as the sidebar rows.
        .contentShape(Rectangle())
        .onContinuousHover(coordinateSpace: .local) { phase in
            switch phase {
            case .active(let location):
                room.pointer(at: location, scene: scene, spots: spots, state: page.mood, reduceMotion: reduceMotion)
            case .ended:
                room.pointer(at: nil, scene: scene, spots: spots, state: page.mood, reduceMotion: reduceMotion)
            }
        }
        // Track Z Z9 (§7.4) — the whole room is the drop target; the one intake decides.
        .onDrop(of: [.fileURL], delegate: RoomDropDelegate(room: room, intake: intake, scene: scene, spots: spots,
                                                           mood: page.mood, onDrop: { feed($0) }))
        // Z-B8 — a claim never outlives the room: a page torn down mid-drag
        // (a tab switch) would otherwise keep the window's veil hidden.
        .onDisappear { intake.releaseDrop(.sleepRoom) }
        .accessibilityElement(children: .contain)
    }

    /// I15 / I16 — one path for a drop and for the picker (Z-B17): the router
    /// decides (its guard is every door's, Z-B5), and the room tells what it
    /// decided — a beat the matrix allows, a line, an announcement (§11: the
    /// person caused it).
    private func feed(_ urls: [URL]) {
        // A drop whose providers held no file URL (or a cancelled picker)
        // still ends the drag, so the worm never stays armed.
        guard !urls.isEmpty else { return room.dragEnded() }
        let result = roomFeedResult(reachable: reachable) { intake.accept(urls: urls, from: .sleepRoom) }
        room.fed(result, state: page.mood, reduceMotion: reduceMotion)
        if let phase = RoomModel.feedPhase(drag: nil, result: result, intakePhase: intake.phase) {
            AccessibilityNotification.Announcement(feedLine(phase, asleep: feedIsAsleep(page.mood)).spoken).post()
        }
    }
}

/// I12 — the dashed inset outline while a file is over the room: chrome, not
/// art (a SwiftUI stroke, never pixels in the room), `textPrimary` under
/// Increase Contrast (§11), instant under Reduce Motion.
private struct DropOutline: View {
    let room: RoomModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous)
            .strokeBorder(contrast == .increased ? CicadaTheme.textPrimary : CicadaTheme.accent,
                          style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
            .opacity(room.drag == nil ? 0 : 1)
            .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: room.drag == nil)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}
```

  `WormStage` (`:186-193`): `pose: room.pointerInRoom ? .attentive(room.gaze) : .idle,` →
  `pose: Self.pose(drag: room.drag, pointerInRoom: room.pointerInRoom, gaze: room.gaze),` and add

```swift
    /// A drag outranks the pointer (§6.1): the armed pose is the drop cue.
    /// Pure; tested.
    static func pose(drag: RoomDrag?, pointerInRoom: Bool, gaze: Gaze) -> BookwormPose {
        drag?.pose ?? (pointerInRoom ? .attentive(gaze) : .idle)
    }
```

  `WormHotspot` (`:201-256`): add `var onFeed: (() -> Void)? = nil` after `whatChanged`; the Esc
  handler's guard becomes `guard room.answerIndex != nil || room.feedResult?.isTerminal == true else {
  return .ignored }` and its `room.dismissAnswers()` becomes `room.dismissSlot()`; the context menu
  and actions become:

```swift
            .contextMenu {
                Button(Copy.wormWhatAreYouDoing) { announceAll() }
                // I16 — the keyboard's and the trackpad's way to feed: the intake's own picker.
                if let onFeed { Button(Copy.feedAFile, action: onFeed) }
            }
            // (`.accessibilityElement()` … `.accessibilityAction(named:)`, `:230-236`, unchanged)
            .accessibilityActions {
                if let onFeed { Button(Copy.feedAFile, action: onFeed) }   // I16, §11
                if let whatChanged {
                    Button(Copy.whatChanged, action: whatChanged)   // §11 — while T7's link lives
                }
            }
```

  In `Copy.swift` (`:64-67`):

```swift
    /// The worm's accessibility hint (Track Z §11) — both clauses now that
    /// feeding shipped (Z9; Z-P16 held the second back until it was true).
    static let wormHint = "Click to ask what it's doing. Drop a file to import it."
    /// Z9 (I16) — the worm's named action and context-menu item: the intake's
    /// own picker, for anyone without a file to drag.
    static let feedAFile = "Feed a file…"
```

- [ ] **Step 5: The slot tells the feed; T13.** In `RoomSentence.swift`, after T12 (`:269`):

```swift
    // T13 (Z9, Z-B19) — only once the queue has loaded: "Checking what's
    // waiting…" never carries an invitation.
    if case .happy = ctx.mood, case .loaded = ctx.queueLoad {                                    // T13
        return SentenceTail(text: "Drop a file on me to add it to the pile.")
    }
```

  `RoomSentenceView` (`:288-423`): add after `room`:

```swift
    /// Track Z Z9 — whether the worm is asleep: all a feed line needs besides
    /// the router's phase (a sleeping worm reads it "after this nap").
    var feedAsleep = false
```

  add `@Environment(IntakeRouter.self) private var intake` beside `reduceMotion`, and replace
  `shown` / `shownRung`'s use in `body` with:

```swift
    /// Z9 — a feed line outranks an answer and the status (§7.4): during a
    /// drag the slot asks "Is that for me?", after a drop it tells what
    /// happened, driven by the router's own phase (Z-B9).
    private var feedShown: FeedPhase? {
        room.flatMap { RoomModel.feedPhase(drag: $0.drag, result: $0.feedResult, intakePhase: intake.phase) }
    }

    private var shown: SentenceLine {
        if let feed = feedShown { return feedLine(feed, asleep: feedAsleep) }
        return shownRung.map { answers[$0] } ?? line
    }

    /// What the cross-fade keys on: the kind of line, never its words, so a
    /// status tick ("Read a of b") updates in place (Task 6 review r1).
    private var slot: SlotKey {
        if let feed = feedShown { return .feed(feed) }
        return shownRung.map { .rung($0) } ?? .status
    }
```

  In `body`: `let slot = slot` beside `let shown = shown`; `.id(shownRung)` → `.id(slot)`;
  `.animation(…, value: shownRung)` → `value: slot`; the dwell becomes

```swift
        .task(id: DwellKey(slot: slot,
                           inside: (room?.pointerInRoom ?? false) || (room?.pointerInSentence ?? false))) {
            // I4 / Z-B11 — an answer or a finished feed line returns to the
            // status after `answerDwell` with the pointer outside the room and
            // the sentence; any re-entry restarts this task.
            guard let room, room.answerIndex != nil || room.feedResult?.isTerminal == true,
                  !room.pointerInRoom, !room.pointerInSentence else { return }
            try? await Task.sleep(for: SleepMotion.answerDwell)
            guard !Task.isCancelled else { return }
            room.dismissSlot()
        }
        // Z-B9 — the room's drop follows the router's phase; a landing is
        // announced because the person pressed Done (§11).
        .onChange(of: intake.phase) { old, new in
            guard let landing = room?.intakeChanged(from: old, to: new) else { return }
            AccessibilityNotification.Announcement(feedLine(.landed(landing), asleep: feedAsleep).spoken).post()
        }
```

  and replace `DwellKey` (`:428-431`) with:

```swift
/// What the slot shows: the status, an answer rung, or a feed line (Z9).
private enum SlotKey: Hashable {
    case status
    case rung(Int)
    case feed(FeedPhase)
}

/// What the dwell task restarts on: the line on show, and whether the pointer
/// is inside the room or the sentence.
private struct DwellKey: Equatable {
    let slot: SlotKey
    let inside: Bool
}
```

  In `SleepView.swift`: `:241` → `.onChange(of: page.mood.caseName) { _, _ in room.dismissSlot() }`
  (with its comment extended: *"…and any feed line about a moment that has passed (Z-B11)."*); the
  `StudyRoom(…)` call (`:629-631`) gains `reachable: liveness == .live` as its last argument, after
  `onWhatChanged: …` (`reachable` is declared after `onWhatChanged`; `SleepLiveness` is `Equatable`,
  `SleepView.swift:24`); the `RoomSentenceView(…)` call (`:638`) gains
  `feedAsleep: feedIsAsleep(page.mood),` after `room: room,`.

- [ ] **Step 6: Verify.** `swift test --filter "RoomFeedTests|RoomSentenceTests|RoomModelTests|SleepNumbersLintTests|BookwormPoseSpriteTests|IntakeRouterTests|WormAnswersTests" 2>&1 | tail -20` → 0 failures (`testTheWormIsNeverTransformed` and `testTheWholeRoomIsTheHoverSurface` pass unmodified: the worm's chain and the `.contentShape` → `.onContinuousHover` pair are unchanged); then `swift build 2>&1 | tail -5`, `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 7: Commit** — stage `RoomFeed.swift`, `RoomModel.swift`, `StudyRoom.swift`, `RoomSentence.swift`, `SleepView.swift`, `Copy.swift`, `RoomFeedTests.swift`, `RoomSentenceTests.swift`:
  `feat(sleep): feeding — a file dropped on the room imports through the one intake; the worm gulps, shakes and says what happened (Track Z Z9, R-Z10, Z-B7..Z-B11, Z-B19)`.

---

### Task 4 (Z10): The Meadow pass on this page, and the sky band decided by its composites

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomSentence.swift` — `RoomSentenceView`'s docstring (`:286-287`), lead (`:325-327`), numeral run (`:379`), tail font (`:404`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepHero.swift:465-491` — Consolidate
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMotion.swift` — `maxDuration` (`:25`), `settleDuration` (`:30`), `hoverDuration` (`:64`), `settle` (`:72-74`), `hover` (`:88-90`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — the band (`:209-213`), `DetailsDisclosureRow` replacing `detailsDisclosure` (`:405-425`), the whisper glyph (`:679-680`)
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepSkyBand.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift` — `skyBandOpacity` after `skyGradient` (`:188`)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/SleepMeadowTests.swift`, `app/CicadaApp/Tests/CicadaAppTests/SkyBandTests.swift`

**Interfaces:**
- Produces: `RoomSentenceView.leadSize` / `.tailSize` / `.leadMinimumScale`; `SkyBand.ships` / `.height` / `.maxTintRatio` / `.minTitleContrast` / `phase(for:)` / `top(_:)` / `isDrawn(ships:contrast:)`; `SleepSkyBand(weather:)`; `CicadaTheme.skyBandOpacity`.
- Consumes: `CicadaTheme.displayFont` / `.quoteFont` / `.displayMinimumSize` / `.skyGradient`, `PrimaryActionButton`, `hoverLift()`, `iconHover(hovering:)`, `CicadaMotion.maxDuration` / `.settleDuration` / `.hoverDuration` / `.settle` / `.hover`, `windowWeather(for:)`, `PageTitle`, `ThemeTokenTests.contrast` / `.blend`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/SleepMeadowTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z Z10 — the Meadow pass on the Sleep page (spec decision 6; Z-B12 …
/// Z-B15): the sentence in Meadow's faces, one prominent action, one motion
/// budget, hover only where there is a control.
final class SleepMeadowTests: XCTestCase {

    private func sleepFile(_ name: String) throws -> [String] {
        let file = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == name })
        return try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.hasPrefix("//") }
    }

    /// Z-B12 — Instrument Serif for the lead, New York italic for the tail.
    func test_theSentenceSpeaksInMeadowsFaces() throws {
        let code = try sleepFile("RoomSentence.swift")
        XCTAssertTrue(code.contains { $0.contains("CicadaTheme.displayFont(size: Self.leadSize)") })
        XCTAssertTrue(code.contains { $0.contains("CicadaTheme.quoteFont(size: Self.tailSize)") })
        XCTAssertFalse(code.contains { $0.contains("design: .serif") }, "the New York stand-in part a used until M1")
        XCTAssertGreaterThanOrEqual(RoomSentenceView.leadSize, CicadaTheme.displayMinimumSize)
    }

    /// The lead may shrink to one line only as far as the display face's floor.
    func test_theLeadNeverShrinksBelowTheDisplayFloor() {
        XCTAssertEqual(RoomSentenceView.leadSize * RoomSentenceView.leadMinimumScale,
                       CicadaTheme.displayMinimumSize, accuracy: 0.001)
    }

    /// Z-B14 / R-M5 — one prominent action per page, and it is Consolidate.
    func test_consolidateIsThePagesOneProminentAction() throws {
        var prominent: [String] = []
        for file in try SleepNumbersLintTests.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let count = text.components(separatedBy: "PrimaryActionButton(").count - 1
            if count > 0 { prominent.append("\(file.lastPathComponent)×\(count)") }
            for other in ["primaryActionStyle()", "meadowPillStyle()", "MeadowPill("] {
                XCTAssertFalse(text.contains(other), "\(file.lastPathComponent): \(other)")
            }
        }
        XCTAssertEqual(prominent, ["SleepHero.swift×1"])
        XCTAssertFalse(try sleepFile("SleepHero.swift").contains { $0.contains(".white") }, "the capsule's literal ink is gone")
    }

    /// Z-B13 — one motion budget, app-wide: where a name mirrors Meadow's, it IS Meadow's.
    func test_sleepMotionIsCicadaMotionWhereTheNamesMatch() {
        XCTAssertEqual(SleepMotion.maxDuration, CicadaMotion.maxDuration)
        XCTAssertEqual(SleepMotion.settleDuration, CicadaMotion.settleDuration)
        XCTAssertEqual(SleepMotion.hoverDuration, CicadaMotion.hoverDuration)
    }

    /// Z-B15 — hover acknowledges controls, never art.
    func test_hoverLivesOnControls() throws {
        let page = try sleepFile("SleepView.swift")
        XCTAssertGreaterThanOrEqual(page.filter { $0.contains(".iconHover(") }.count, 2, "the Details chevron and the whisper glyph")
        let room = try sleepFile("StudyRoom.swift")
        XCTAssertFalse(room.contains { $0.contains(".iconHover(") || $0.contains(".hoverLift(") },
                       "I8: the art never changes on hover")
    }
}
```

  `app/CicadaApp/Tests/CicadaAppTests/SkyBandTests.swift`:

```swift
import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Track Z Z10 — the optional sky band (spec decision 16, Z-B16). It shows only
/// a sky the window agrees with, it is a tint and never a block, text over it
/// stays legible, and whether it ships is one constant decided by looking at
/// the composites this file writes on request. `@MainActor` for `ImageRenderer`.
@MainActor
final class SkyBandTests: XCTestCase {

    func test_theBandShowsOnlyASkyTheWindowAgreesWith() {
        XCTAssertEqual(SkyBand.phase(for: .night), .night)
        XCTAssertEqual(SkyBand.phase(for: .dawn), .dusk)
        XCTAssertEqual(SkyBand.phase(for: .clear), .day)
        XCTAssertEqual(SkyBand.phase(for: .fair), .day)
        for grey in [WindowWeather.overcast, .storm, .curtains] {
            XCTAssertNil(SkyBand.phase(for: grey), "\(grey): no grey band — the window and the sentence say it")
        }
    }

    func test_oneSwitch_andIncreaseContrastHidesIt() {
        XCTAssertFalse(SkyBand.isDrawn(ships: false, contrast: .standard))
        XCTAssertFalse(SkyBand.isDrawn(ships: true, contrast: .increased), "§11")
        XCTAssertTrue(SkyBand.isDrawn(ships: true, contrast: .standard))
    }

    /// Z-B16 — the wash is clear before the room card starts, so it never sits
    /// behind a number. The card is below `spacingXL` (24) of padding, the
    /// title's line (at least its 28 pt size) and a `spacingLG` (16) gap, all
    /// at uiScale 1 — and the band scales with them.
    func test_theBandEndsAboveTheRoomCard() {
        XCTAssertLessThanOrEqual(SkyBand.height, 24 + PageTitle.size + 16)
    }

    /// The build's two gates, both modes, every sky the band can show.
    func test_aTintNotABlock_andTheTitleStaysLegible() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for phase in CicadaTheme.SkyPhase.allCases {
                let band = ThemeTokenTests.blend(SkyBand.top(phase), over: CicadaTheme.background,
                                                 alpha: CicadaTheme.skyBandOpacity)
                let tint = ThemeTokenTests.contrast(band, CicadaTheme.background)
                let title = ThemeTokenTests.contrast(CicadaTheme.textPrimary, band)
                XCTAssertLessThanOrEqual(tint, SkyBand.maxTintRatio, "\(phase) in \(mode): \(tint)")
                XCTAssertGreaterThanOrEqual(title, SkyBand.minTitleContrast, "\(phase) in \(mode): \(title)")
            }
        }
    }

    /// Opt-in art check (the `WindowSpritesTests` convention):
    /// `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests` writes the
    /// page's top 320 pt — band, title, a card — for every sky the band shows,
    /// in both themes, plus a no-band control per theme, for a person to look
    /// at, and prints each sky's measured tint and title ratios for the record.
    func test_writeCompositesWhenAsked() throws {
        guard ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1" else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-composites")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for phase in CicadaTheme.SkyPhase.allCases {
                let band = ThemeTokenTests.blend(SkyBand.top(phase), over: CicadaTheme.background,
                                                 alpha: CicadaTheme.skyBandOpacity)
                let tint = ThemeTokenTests.contrast(band, CicadaTheme.background)
                let title = ThemeTokenTests.contrast(CicadaTheme.textPrimary, band)
                print("sky band ratio: \(mode.rawValue) \(phase) tint \(String(format: "%.2f", tint)):1 "
                      + "title \(String(format: "%.1f", title)):1")
            }
            let weathers: [WindowWeather?] = [nil]
                + WindowWeather.all.filter { SkyBand.phase(for: $0) != nil }.map(Optional.some)
            for weather in weathers {
                let page = ZStack(alignment: .top) {
                    CicadaTheme.background
                    if let weather { SleepSkyBand(weather: weather) }
                    VStack(alignment: .leading, spacing: 16) {
                        PageTitle(Copy.sleepPageTitle)
                        RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius).fill(CicadaTheme.surface)
                            .frame(height: 180)
                    }
                    .padding(24)
                }
                .frame(width: 760, height: 320)
                let renderer = ImageRenderer(content: page)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.nsImage)
                let rep = NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation))
                try XCTUnwrap(rep?.representation(using: .png, properties: [:]))
                    .write(to: dir.appendingPathComponent("sky-band-\(weather?.rawValue ?? "none")-\(mode.rawValue).png"))
            }
        }
        print("sky band composites: \(dir.path)")
    }
}
```

  Run: `swift test --filter "SleepMeadowTests|SkyBandTests" 2>&1 | tail -20` → compile failure.

- [ ] **Step 2: The sentence's faces (Z-B12).** In `RoomSentenceView`, replace the docstring lines
  (`:286-287`) with *"Meadow's faces (Z10, Z-B12): the lead in Instrument Serif at 30 pt, shrinking
  only to the display floor; the tail in New York italic at 22 pt — two lines of text, which is what
  the quote face is optically sized for."*, add

```swift
    static let leadSize: CGFloat = 30
    static let tailSize: CGFloat = 22
    /// The lead fits one line by shrinking no further than the display
    /// face's own floor (R-M3) — the old 0.7 would have reached 21 pt.
    static var leadMinimumScale: CGFloat { CicadaTheme.displayMinimumSize / leadSize }
```

  and change `.font(CicadaTheme.font(size: 30, design: .serif))` / `.minimumScaleFactor(0.7)`
  (`:325-327`) to `.font(CicadaTheme.displayFont(size: Self.leadSize))` /
  `.minimumScaleFactor(Self.leadMinimumScale)`; the numeral run (`:379`) to
  `.font(CicadaTheme.font(size: Self.leadSize, weight: .medium, design: .rounded))`; and
  `let tailFont = CicadaTheme.font(size: 22, design: .serif).italic()` (`:404`) to
  `let tailFont = CicadaTheme.quoteFont(size: Self.tailSize)`.

- [ ] **Step 3: One prominent action (Z-B14).** `SleepHero.swift`'s `consolidateButton`
  (`:465-491`) becomes:

```swift
    /// The page's one prominent action (R-M5, Z-B14): `.glassProminent`,
    /// accent-tinted, on macOS 26 and `.borderedProminent` before, through the
    /// shared `PrimaryActionButton` so its ink follows the key-window rule. It
    /// lifts on hover because it is the one thing on the page that starts
    /// something; Cancel beside it stays quiet.
    private var consolidateButton: some View {
        PrimaryActionButton(title: Copy.consolidateNow, systemImage: "moon.fill") {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        }
        .font(CicadaTheme.font(size: 12, weight: .semibold))
        .controlSize(.large)
        .disabled(!consolidateEnabled)
        .hoverLift()
        .help(queuedCount == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }
```

  (`FixWaveTests` still finds `sleepVM.triggerManually()` in exactly `SleepHero.swift`.)

- [ ] **Step 4: One motion budget, hover on controls (Z-B13, Z-B15).** `SleepMotion.swift`:
  `static let maxDuration: TimeInterval = 0.4` → `= CicadaMotion.maxDuration`,
  `settleDuration … = 0.35` → `= CicadaMotion.settleDuration`, `hoverDuration … = 0.15` →
  `= CicadaMotion.hoverDuration`, `settle(reduceMotion:)`'s body →
  `CicadaMotion.settle(reduceMotion: reduceMotion)`, `hover(reduceMotion:)`'s body →
  `CicadaMotion.hover(reduceMotion: reduceMotion)`; add to the type's docstring: *"Z10 (Z-B13):
  where a name mirrors `CicadaMotion`'s it forwards to it — one budget, app-wide — and the
  Sleep-only constants below stay here."* In `SleepView.swift` replace `detailsDisclosure`
  (`:405-425`) and its one use (`:227`) with a `DetailsDisclosureRow(open: detailsOpen) { withAnimation(
  SleepMotion.disclosure(reduceMotion: reduceMotion)) { detailsOpen.toggle() } }`, declared at the end
  of the file:

```swift
/// The one row that opens Details (R-Z6), with Meadow's hover (Z-B15): the
/// chevron acknowledges the pointer once (`iconHover`) and the words brighten
/// — a fill change, never a lift, because a row is not a card (R-M14). Its
/// own `@State`, so a hover never re-evaluates the page.
private struct DetailsDisclosureRow: View {
    let open: Bool
    let toggle: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: open ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .frame(width: 12)
                    .iconHover(hovering: hovering)
                Text(Copy.sleepDetails)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                Spacer(minLength: 0)
            }
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(Copy.sleepDetails)
        .accessibilityValue(open ? "expanded" : "collapsed")
    }
}
```

  and in `whisperRow` (`:679-680`) give the glyph `.iconHover()` after its `.font(…)`.

- [ ] **Step 5: The sky band, built behind one constant (Z-B16).** In `CicadaTheme.swift`, after
  `skyGradient` (`:188`):

```swift
    /// Track Z Z10 — the Sleep page's optional sky band, at this strength over
    /// the page in both modes. `SkyBandTests` holds it to a tint (≤ 1.35:1
    /// against the page) that keeps text ≥ 7:1 over it, for every sky.
    static let skyBandOpacity: Double = 0.12
```

  Create `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepSkyBand.swift`:

```swift
import SwiftUI

/// Track Z Z10 (spec decision 16, Z-B16) — the optional wash across the top of
/// the Sleep page that follows the window's weather. State, never quantity
/// (R-Z1): its only input is the weather, which is the mood alone (R-Z11), and
/// its text twin is the window's legend. It is a procedural wash of Meadow's
/// sky tokens — not painted art — fading to clear before the room card, so
/// it never sits behind a number, and nothing in it moves but the crossfade.
enum SkyBand {
    /// THE switch (the brief: "behind a single constant"). Decided in Task 4
    /// Step 6 from the composites — see TODO ruling 10 and the G125 row.
    static let ships = false
    /// Points at uiScale 1: the title's band, clear before the room card
    /// starts (≥ 24 + 28 + 16 = 68 pt down, pinned by `SkyBandTests`).
    static let height: CGFloat = 64
    /// "A tint, not a block": the band's top, composited, against the page.
    static let maxTintRatio: Double = 1.35
    /// Text over the band (the page title) stays comfortably legible.
    static let minTitleContrast: Double = 7

    /// Only a sky the window agrees with: night while a cycle runs, dusk at
    /// dawn, day for clear and fair. Overcast, storm and curtains draw no band
    /// — a grey wash would be the "dirt" the owner's §16 question names, and
    /// the window and the sentence already say those states.
    static func phase(for weather: WindowWeather) -> CicadaTheme.SkyPhase? {
        switch weather {
        case .night: .night
        case .dawn: .dusk
        case .clear, .fair: .day
        case .overcast, .storm, .curtains: nil
        }
    }

    /// The sky's top stop at full strength; the view fades it to clear.
    static func top(_ phase: CicadaTheme.SkyPhase) -> Color { CicadaTheme.skyGradient(phase)[0] }

    /// Hidden under Increase Contrast (§11) and whenever the switch is off.
    static func isDrawn(ships: Bool = SkyBand.ships, contrast: ColorSchemeContrast) -> Bool {
        ships && contrast != .increased
    }
}

/// The band itself: the weather's sky at `skyBandOpacity`, fading to clear,
/// crossfading when the weather changes (a jump under Reduce Motion).
struct SleepSkyBand: View {
    let weather: WindowWeather

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let phase = SkyBand.phase(for: weather)
        ZStack {
            if let phase {
                LinearGradient(colors: [SkyBand.top(phase).opacity(CicadaTheme.skyBandOpacity), .clear],
                               startPoint: .top, endPoint: .bottom)
                    .id(phase)
                    .transition(.opacity)
            }
        }
        .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: phase)
        .frame(height: CicadaTheme.scaled(SkyBand.height))
        .frame(maxWidth: .infinity)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
```

  In `SleepView.swift` add `@Environment(\.colorSchemeContrast) private var contrast` beside
  `reduceMotion` (`:176`), and after `CicadaTheme.background` (`:213`):

```swift
            // Track Z Z10 (spec decision 16) — the optional sky band: behind
            // everything, fixed across the top, following the window's weather.
            // `SkyBand.ships` is the one switch (Z-B16).
            if SkyBand.isDrawn(contrast: contrast) {
                VStack(spacing: 0) {
                    SleepSkyBand(weather: windowWeather(for: page.mood))
                    Spacer(minLength: 0)
                }
            }
```

- [ ] **Step 6: Look, decide, record (Z-B16).** Run
  `cd <worktree>/app/CicadaApp && CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests 2>&1 | grep "sky band"`
  and open every `sky-band-*.png` in the printed folder with the Read tool (day, dusk and night in
  light and dark, and the two `none` controls — the title may render in SF because the test process
  registers no bundled font; judge the band, not the face). The same run prints six
  `sky band ratio:` lines — record them (`… | grep "sky band"` shows both the folder and the
  ratios). Computed by the plan critic from the hex tokens at opacity 0.12, so a different number
  means a token moved: light day 1.04 / 14.8, light dusk 1.26 / 12.2, light night 1.29 / 11.9, dark
  day 1.29 / 12.4, dark dusk 1.02 / 15.7, dark night 1.00 / 16.0 (tint : 1 / title : 1) — every
  pair inside the 1.35 and 7 gates, so the gates alone cannot decide; the eye does. **Decide:** the band ships
  ON only if every one of the six band composites reads as a calm tint that fades into the page next
  to its `none` control, the title reads at a glance, and the light-mode night and dusk bands do not
  read as a grey smudge; otherwise it ships OFF. Set `static let ships` accordingly and replace its
  docstring's second sentence with the ruling: *"Decided 2026-09-23 from the composites: {ON|OFF} —
  {one sentence: what the light and dark night/dusk/day bands looked like against the control, and
  the measured tint / title ratios}. Revisit by flipping this and re-running `CICADA_WRITE_COMPOSITES=1
  swift test --filter SkyBandTests`."* If the images cannot be viewed, the band ships OFF and the
  docstring says so.
- [ ] **Step 7: Verify.** `swift test --filter "SleepMeadowTests|SkyBandTests|RoomSentenceTests|FixWaveTests|SleepNumbersLintTests|FontLiteralLintTests|MotionLiteralLintTests|LiquidGlassLintTests|MeadowPlacementLintTests|ThemeTokenTests|SleepHeroTests" 2>&1 | tail -20` → 0 failures; then `swift build 2>&1 | tail -5`, `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 8: Commit** — stage `RoomSentence.swift`, `SleepHero.swift`, `SleepMotion.swift`, `SleepView.swift`, `SleepSkyBand.swift`, `CicadaTheme.swift`, `SleepMeadowTests.swift`, `SkyBandTests.swift`:
  `feat(sleep): the Meadow pass — display and quote faces, Consolidate as the one prominent action, one motion budget, hover on controls; sky band {on|off} by its composites (Track Z Z10, Z-B12..Z-B16)` — the commit body states the band decision and the six measured ratio pairs.

---

### Task 5 (Z12, part b): The docs — where the next reader will look

Privacy (standing rule): no bank contents, no names, no counts read from a bank — placeholders only;
the owner's own words quoted with his name and date. Task 4's band decision is known by now: write
it as decided.

**Files:**
- Modify: `CLAUDE.md:528-538` ("One intake"), `:581-599` ("Sleep page — the study room (G125 v4, Track Z)"), `:600-617` ("Mascot states (G107)", its last sentence)
- Modify: `docs/goals/memory-evolution.md:686` (G125 — a "v4 part b" paragraph appended; the part-a paragraph's "Deliberately not in v4 yet" sentence re-pointed) and `:669` (G107 — the feeding amendment's "lands with Track I" becomes shipped)
- Modify: `docs/goals/TODO.md:167-170` — ruling 10 appended after ruling 9 (which ends at `:170`, before `## How work is run here`)
- Modify: `docs/superpowers/specs/2026-09-23-round3-design-mascot-page.md:1024-1032` — the three owner questions marked answered
- Modify: `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md:304-306` — one sentence naming this plan

- [ ] **Step 1: `CLAUDE.md`.** In "One intake", after "each `+` chat tile" insert ", the Sleep room's
  worm", and append: *"**Every door refuses the same roots** (`IntakeRouter.feedGuard`, Track Z): a
  drop that resolves under `~/.claude`, `~/.codex` or `~/.cicada` (or `$CLAUDE_CONFIG_DIR`,
  `$CODEX_HOME`, `$CICADA_HOME`) is refused before any folder is walked, a refused root met inside
  a dropped folder is never descended into and refuses the drop, a drop with nothing
  export-shaped in it is refused by name, and nothing is sent; `accept` answers
  (`IntakeAcceptance`) so the Sleep room tells a refusal in its worm's words while every other door
  shows it in the panel."* In "Sleep page", before its closing "Refused: …" sentence, insert:
  *"**Feeding (Z9).** A file, files or a folder dropped on the room — or *Feed a file…* from the
  worm's context menu and VoiceOver actions, which open the intake's own `IntakePicker` — go to
  `IntakeRouter.accept(urls:from: .sleepRoom)` and nowhere else. While a file hovers, the worm is
  expectant toward it and eager over itself behind a dashed chrome outline, and the window's veil
  steps aside (`nearerDrop`); it gulps when the router takes the drop and shakes when it does not,
  and the sentence tells the router's own phase in words with no number — the panel has the counts.
  A sleeping worm takes the drop and stays asleep; a stale page sends nothing. **Meadow (Z10).** The
  sentence is Instrument Serif 30 over a New York italic tail, Consolidate is the page's one
  `PrimaryActionButton`, `SleepMotion` forwards its shared names to `CicadaMotion`, and the sky band
  above the page is {ON|OFF} (TODO ruling 10). The pile is compressed to its column at every zoom and
  queue size — at most eight spines, the order and every count kept, never cut (`fitPile`) — and the
  title is `PageTitle`, the view `PageHeader` draws."* In "Mascot states", replace "**Feeding** — a
  file dropped on the worm imports through the one intake — is ruled (R-Z10) and lands with Track
  I's `IntakeRouter`." with "**Feeding** — a file dropped on the worm imports through the one intake
  (R-Z10) — shipped in Z9; the matrix decides its gulp and shake like every other beat."
- [ ] **Step 2: `memory-evolution.md`.** G125: in the part-a paragraph change "**Deliberately not in v4
  yet:** feeding (Z9, …), the Meadow pass and the optional sky band (Z10, after M1), and live
  verification …" to name them as landed in part b (below), keeping "live verification with
  screenshots from the demo bank (Z11, the orchestrator's)" as the open item; then append **"v4 part b
  (2026-09-23) — feeding, the Meadow pass, two live-check fixes (Track Z Z9/Z10;
  `docs/superpowers/plans/2026-09-23-mascot-page-b.md`, rulings Z-B1…Z-B19)."** in the row's density:
  the two live-check defects and their measured cause (spine heights authored in unscaled points
  with no bound on their sum — four 40 pt spines need 168 pt of a 130 pt column at 1.0×, the card's
  clip cut the top one, and at 0.8× a 150 pt spine was wider than its 120 pt column; the title copied
  SF 20 semibold instead of sharing `PageHeader`'s face); the fix's rule (compressed above a label
  floor, one factor, order and counts kept, never cut; eight spines because 8 × (floor + gap) fits
  every zoom step and nine does not fit at 1.0×; scaled with the lattice, the floor with the font;
  `PageTitle`); feeding by id (R-Z10, Z-B5…Z-B11 — the guard at every door, refused roots never
  walked, the room answering in place, the veil yielding, the router's phase as the line, no digits,
  yes/no beats through the matrix, asleep stays asleep, offline sends nothing); the Meadow pass
  (Z-B12…Z-B15) and the band's decision with its reason (Z-B16). G107: replace "…and it lands with
  Track I." with "…shipped 2026-09-23 with Track Z Z9: the one intake's guard refuses harness session
  folders and Cicada's own home at every door, and a sleeping worm takes a drop without waking."
- [ ] **Step 3: `TODO.md`** — append after ruling 9:

  > 10. **The Sleep page's sky band is {on|off}** (Track Z Z-B16, spec decision 16). Built behind one
  >     constant, `SkyBand.ships`; gated in the build by `SkyBandTests` (a band's top composited over
  >     the page stays within 1.35:1 of it and keeps text ≥ 7:1, both modes, every sky) and decided
  >     by eye from the day/dusk/night × light/dark composites against a no-band control: {the
  >     reason, with the measured ratios}. Revisit only with new composites — flip the constant and
  >     re-run `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests`.

- [ ] **Step 4: The design's owner questions (spec decision 16).** In §16 of
  `2026-09-23-round3-design-mascot-page.md`, append to each question: 1 — *"**Answered (spec
  decision 16, 2026-09-23):** ships only if the screenshots say calm. Decided from the composites:
  {ON|OFF} (plan Z-B16, TODO ruling 10)."*; 2 — *"**Answered (spec decision 16):** closed by default,
  remembered per viewer (`cicada.sleep.detailsOpen`) — shipped in part a."*; 3 — *"**Answered (spec
  decision 16):** yes — the last rung may point to the Inbox; shipped in part a."* In the round-3
  spec, after "Built by `docs/superpowers/plans/2026-09-23-mascot-page.md`, part a: …" add: *"Part b
  — Z9 feeding, the Z10 Meadow pass and two live-check fixes (the pile's fit, the page title) — is
  `docs/superpowers/plans/2026-09-23-mascot-page-b.md`."*
- [ ] **Step 5: Verify** — `cd <worktree> && git diff --stat` shows only the five docs; `grep -n "Z-B16\|ruling 10" docs/goals/TODO.md CLAUDE.md docs/goals/memory-evolution.md` finds the band decision in all three and no `{ON|OFF}` placeholder survives (`grep -n "{ON|OFF}\|{on|off}" CLAUDE.md docs/goals/*.md docs/superpowers/specs/2026-09-23-round3-design-mascot-page.md` → nothing).
- [ ] **Step 6: Commit** — stage the five docs by name (`CLAUDE.md`, `docs/goals/memory-evolution.md`,
  `docs/goals/TODO.md`, `docs/superpowers/specs/2026-09-23-round3-design-mascot-page.md`,
  `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`) — and this plan,
  `docs/superpowers/plans/2026-09-23-mascot-page-b.md`, if it is not yet committed:
  `docs: Sleep v4 part b — feeding, the Meadow pass, the pile's fit and the band's decision (G125 v4, G107, TODO ruling 10, design §16 answered)`.

---

## Not in scope

Named so a reviewer does not read an absence as an oversight.

- **Live verification and the README screenshot retake (Z11)** — the orchestrator's (below).
- **The backend.** No endpoint, field, ETag or Store domain; `api/` is untouched.
- **The empty states' nested drop targets** (`EmptyStateDrop`, `Views/Common/EmptyStateView.swift:90-105`)
  claiming the drag the way the room does (Z-B8). They are Track I's; `claimDrop` is there for them
  if the live check shows the veil over an empty state.
- **A verdict during the hover** (Z-B7): the worm does not preview a refusal before the drop.
- **Naming the export's vendor in a feed line** — the panel names it with its mark; the worm's lines
  stay vendor-free and number-free.
- **The menu bar's completion edge** (`Sync/Store.swift:424` still stamps `justFinishedAt` on any
  running → idle edge) — noted for its owner in part a, unchanged here.
- **The app-wide Meadow pass (M2)**: other pages' hover, marks and backdrops. `PageTitle` and
  `PageHeader` change only by sharing one view.
- **Painted Meadow art on this page** (clouds, grass): never inside the pixel room, and the band is a
  procedural wash, not paint.
- **Refused by the design and kept refused:** sound, a hunger mechanic, a nag, a reward loop, a
  draggable worm, the hello and glance beats, cloud drift, a storm flash, a time-of-day sky, the
  night wall (§0, R-Z10, R-Z12). **Mascot identity (G127).**

---

## Verification the orchestrator runs at the end

1. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success; `swift test 2>&1 | tail -20`
   → **0 failures** (≥ 1426 executed plus this plan's new tests). `cd <worktree> && git diff --stat
   dev -- api/` → empty. `node --test app/CicadaApp/Tests/graph/*.test.js` → green.
2. **Lints that must be able to fail** (revert each and re-run green): set `PileFitting.maxSpines = 9`
   → `PileFitTests` FAILS; restore `Text("Sleep Cycle").font(CicadaTheme.titleFont)` in `SleepView.swift`
   → `PageTitleTests` FAILS; add `let _ = NSOpenPanel()` in `StudyRoom.swift` → `RoomFeedTests` and
   `IntakeRouterTests` FAIL; add a second `PrimaryActionButton(` in `SleepView.swift` →
   `SleepMeadowTests` FAILS; add `.onDrop(of: [.fileURL], isTargeted: nil) { _ in false }` in
   `SleepView.swift` → `RoomFeedTests` FAILS.
3. `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests` and look at the `sky-band-*.png`
   files the test prints the folder of; confirm the recorded decision (TODO ruling 10) matches.
4. **Live, on the demo bank only** (`make install-app`), light and dark, zoom 0.8 / 1.0 / 1.4:
   - **The pile:** with a large queue across four or more synthetic sources, the pile stays inside
     the room at every zoom, no spine is cut by the card, the counts show on the big spines, and a
     remainder spine appears past seven sources. The title reads in Instrument Serif like every
     other page's.
   - **Feeding:** drag a synthetic ChatGPT export (a `conversations.json` in a temporary folder under
     `~/Downloads`) over the room — the window's veil does not cover the room; the dashed outline
     appears; the worm's mouth opens and its eyes follow the drag, eager over the worm; the sentence
     reads *Is that for me?* / *Drop it on me.* Drop — a gulp, the router's overlay, and the
     sentence follows reading → preview → importing; press Done — *Got it.* / *It's on the pile
     now.*, the pile restacks, the line dwells away after 12 s outside the room. Drop a `.png` —
     a shake, *I can't read that yet.*, no overlay, and no `/intake/sniff` in the backend log. The
     harness-root and `~/.cicada` refusals are proven by `FeedGuardTests` on a temporary home; the
     live check does not touch `~/.claude`, `~/.codex` or `~/.cicada`. The worm's context menu and
     VoiceOver actions offer *Feed a file…*, which opens the same picker as the panel. Drop while a
     cycle runs — the worm stays asleep, *I'll read it after this nap.* Drop while an import is
     landing (overlay closed) — *I'm still eating the last one.*, no toast. With the backend stopped
     for over a minute — *I'm offline right now.* and nothing sent.
   - **Accessibility:** Reduce Motion — no gaze, no beats, the armed pose held still during a drag,
     the outline appears instantly; Increase Contrast — the outline in `textPrimary`, no band;
     VoiceOver — the drop result and the landing are announced; Full Keyboard Access reaches the
     worm's *Feed a file…*.
   - **Meadow:** the sentence lead in Instrument Serif never shrinks below the display floor at
     1.4×; Consolidate is glass-prominent on macOS 26 (bordered-prominent before), lifts on hover,
     and its label stays readable with the window in the background; the Details chevron and the
     whisper glyph acknowledge the pointer; the lamp, window and worm art never change on hover;
     the band (if ON) follows the weather — night on Consolidate, dusk at dawn, day when caught up —
     and reads as a tint.
5. **PR body must state:** no backend, endpoint, ETag or Store-domain change; no price or token
   anywhere; which test files were edited and why (this plan's **Files** lists); the sky band's
   decision with its composites' reason; screenshots from the **demo** bank only (G90).
