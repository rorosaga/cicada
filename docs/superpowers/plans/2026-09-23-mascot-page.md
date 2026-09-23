# The mascot page, Sleep v4 (Track Z, part a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rodrigo 2026-09-23: *"Change the mascot page, make it better and have it be more
interactive, keeping the minimal vibes."* The Sleep page becomes **the room, one serif sentence,
one button and one whisper line**, with everything else under one **Details** disclosure. The worm
notices the pointer (three gaze poses), answers a click with true lines, perks when you reach it and
cheers when a real cycle completes; the lamp and the pile's spines are real controls behind words;
the window shows **weather that is Sleep state** on the room's one pixel lattice, with a legend as
its text twin. Three honesty defects are fixed first: the stage off-by-one, a cancel that "digests",
and two stage lines that assert things no cycle measured.

**Architecture:** Every decision is a **pure function with a table test** — the page model
(`SleepPageModel.resolve`), the sentence (`roomSentence`), the answer ladder (`wormAnswers`), the
hotspots (`deskHotspots`), the gaze (`gazeFor`), the weather (`windowWeather(for:)`), the pose and
reaction frames (`BookwormSprites.frames(for:look:)`) — and the views are thin renderers over them.
The art layer stays inert (`DeskSceneView` keeps `.allowsHitTesting(false)`); interaction lives in
a separate hotspot layer whose rectangles come from the same pure layout. No backend change, no new
endpoint, no new fetch, no new Store domain, no ETag touched.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, macOS 14 floor, SDK 26). Python only in the
design panel's scratch scripts (not committed).

**Spec (binding):**
- `docs/superpowers/specs/2026-09-23-round3-design-mascot-page.md` — **the design**: rulings
  **R-Z1 … R-Z14** (§3), the page (§4–§11), kept/amended rulings (§12), defects (§13), task outline
  (§14). This plan builds **Z0–Z8** and the docs slice of **Z12**.
- `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` — decision **5**
  (the bookworm stays; the page becomes interactive) and decision **16** (Details closed by default
  and remembered; the worm's last answer rung may point to the Inbox).
- Backlog rows **G125** (the study room; this is its **v4**) and **G107** (the mascot; feeding
  amendment). **G127** (mascot identity) is out of scope — the pose and reaction API is
  character-agnostic.
- Standing rulings: no prices or tokens in the app (2026-09-03); ruling 4 (scheduled cycles never
  spend plan quota — shown, not hidden); privacy in docs; portability (no owner name or
  author-machine path in shipped code, plans, commits or PR bodies — write `<worktree>`).

---

## What the code actually does today (verified against `feat/mascot-page` @ `bef2e55`)

Paths are relative to `app/CicadaApp/Sources/CicadaApp/` unless they start with `api/`, `docs/` or
`app/`. Line numbers drift as tasks land — re-read before editing.

**The stage off-by-one (design §13.1).** `api/services/sleep_cycle.py:978` sets `_state.stage = 1`
only after Stage 1 returns, `:1027` sets 2 after Stage 2, `:1042` 3, `:1061` 4, `:1323` 5 — the
wire's `stage` counts **completed** stages. Three places clamp it without adding one:
`Views/Sleep/SleepMood.swift:103` (`.sleeping(stage: max(1, min(5, status.stage)))`),
`MenuBar/BookwormState.swift:159` (same, menu bar) and — found while writing this plan, not named
by the design — `Views/Onboarding/OnboardingSleepStep.swift:128`. So while Sort runs, the worm's
stage dots, the bracket line (`bracketTail`, `Views/Sleep/SleepHero.swift:83`) and VoiceOver say
stage 1 while the strip lights Sort. `stageStripState` (`Views/Sleep/SleepStages.swift:124-145`)
is the one place that already translates correctly (`index == done`).

**The cancel that digests (§13.2).** `Views/Sleep/SleepView.swift:299-303` stamps `justFinishedAt`
on ANY running→idle edge; `SleepMood.swift:108-110` then returns `.digesting` for 6 s — after a
cancel too.

**Invented stage lines (§13.3).** `Views/Sleep/SleepBubble.swift:36-37`: stage 3 says "Two of
these disagree. Noting it." and stage 4 "I think I see a habit here." on every cycle. No test pins
either string (`Tests/CicadaAppTests/SleepBubbleTests.swift`).

**The page.** `SleepView.swift` (893 lines): `SleepLayout`/`sleepLayout(width:)` two columns
≥ 1000 pt (`:16-51`); `studyListRows` evaluated twice per body (`:244-252`, read at `:428` and
`:626`); `deskCard` (`:619-734`) = `SpeechBubbleView` (`:646`), the room `ZStack` (`:648-673`,
worm placed with `.offset(x: scene.wormOrigin.x, …)` at `:661-662`), `SleepHeroView` (`:681-687`),
`SleepStageStrip` with the caught-up worm (`:694-704`), `moodDetailLine` (`:706`, `:756-767`), the
engine line (`:708-710`, `:851-868`) and three banners (`:717-729`, `:769-844`); `errorBanner`
(`:872-892`) sits between the cards in `leftColumn` (`:420-431`); `rightColumn` (`:437-449`) holds
`MemorySourcesCard` and `ConsolidationHistoryCard`. The header (`:551-573`) renders
`Copy.sleepSubtitle`.

**The hero.** `SleepHero.swift`: `heroCount` (`:17`), `heroQualifier` (`:42`), `bracketTail`
(`:78`), `HeroMeter` (`:119`), `heroTiles` (`:203`); `SleepHeroView` = `countRow` (`:270-288`) +
chip (`:290-298`) + meter (`:311-335`) + tiles (`:339-360`) + `controlRow` (`:383-407`) with
`consolidateButton` (`:409-435`, the page's one `sleepVM.triggerManually()`) and `cancelButton`
(`:444-467`); `lastMeasuredCycleMs` reads `history.first { $0.kind != "decay" }` (`:377-379`).

**The queue card.** `Views/Sleep/StudyListCard.swift`: `queueRowState` (`:29-34`),
`scheduleSentence` (`:44-55`), `scheduledEngineLine` (`:65-68`), header "IN THE QUEUE" (`:125`),
`loadState` (`:114-121`), `rowAccessibilityLabel` (`:246-253`, says "queued"), `scheduleRow` with
`SettingsSectionLink(.sleep, "Change…")` (`:311-323`), `footer` (`:328-340`), private
`episodesForOrigin` (`:342-349`), private `nextRunText` (`:357-367`).
`Views/Sleep/SleepQueueModel.swift`: `ageLabel` (`:90-94`), `studyRows` (`:103-131`).

**The room.** `Views/Sleep/DeskScene.swift`: `DeskScene.plan` (`:72-78`: window `cellX 18,
cellY 4`, lamp 0, plant 11, cushion 30, mug 52), `wormCell (28, 4)` (`:85`), `pileCell (60, 0, 30,
26)` (`:90`), `deskSceneLayout` (`:105-121`), `DeskSceneView` (`:130-164`, inert at `:162-163`),
`cacheKey` (`:170-173`). `Views/Sleep/DeskSceneSprites.swift`: `DeskProp` (`:9-11`), `rowBand`
(`:40-46`), `grid(_:lampLit:)` (`:57-65`), `inkBounds` (`:72-82`), the window's worked grid
(`:96-121`: glass rows 4–19, cols 2–8 and 11–17; mullions cols 9–10, rows 11–12; four stars at
(6,14) (9,16) (15,5) (17,14)), `lampTemplate` (`:134-159`, ink rows 4–23 cols 0–9).
`Views/Sleep/DeskPalette.swift` (`:17-37`, 13 keys). `Views/Sleep/BookPile.swift`: `BookPileView`
(`:108-155`) — spines are shapes, the container is `.ignore` "N books on the pile" (`:124-125`), the
count text is literal `.white` (`:149`).

**The worm.** `MenuBar/BookwormSprites.swift`: `eyes(pupil:lid:)` (`:138-153`, lens interior
`woow`), mouths (`:155-184`, all `private`), `compose` (`:212-219`), glyphs (`:223-231`),
`nightcap` rows 0–3 (`:286-291`), `stageDots` row 23 (`:300-307`), `frames(for:)` (`:329-407`; the
reading book glyphs are local `let`s at `:389-390`). `MenuBar/BookwormRenderer.swift`: key
`spriteKey|frame|size` (`:46-48`), `cachedImage` recomposes `frames(for:)` then looks up (`:66-85`),
wipes past 512 (`:79`). `Views/Common/BookwormView.swift` (`:17-64`): no pose, no gesture, no
accessibility action; recomposes `frames(for:)` in `body` (`:44`).

**Motion.** `Views/Sleep/SleepMotion.swift` (`:22-52`): `maxDuration 0.4`, settle/pile/disclosure.
`Tests/CicadaAppTests/SleepNumbersLintTests.swift` fails on a literal `duration:` under
`Views/Sleep/` outside `SleepMotion.swift` (`:103-114`), on a `Text(` + `%` with no noun
(`:32-46`), and on "Rested" spelled outside `SleepHero.swift` (`:57-69`).
`Tests/CicadaAppTests/FixWaveTests.swift:53-68` requires `sleepVM.triggerManually()` in exactly one
`Views/Sleep/` file, `SleepHero.swift`, and `:30-36` bans `Copy.consolidateNow` /
`triggerManually()` in `SleepView.swift`.

**Elsewhere.** `Views/Onboarding/OnboardingSleepStep.swift:9-38` owns `OnboardingSchedule.isOn` /
`.toggled` (tests: `OnboardingScheduleTests.swift:31-53`, `CopyConstantsTests.swift:81`).
`Models/SourceOverview.swift:81-87` — `ownedQueue(from:)` (the `mcp` → `claude-code` rule).
`Support/AppRouter.swift` — `pendingTab`, `pendingAddSource` + `consumeAddSource()` (`:14-87`);
`ContentView.swift:109-113` consumes `pendingTab`. `Views/Sources/SourcesPageView.swift:25` —
`@State route`. `ViewModels/SleepViewModel.swift:329-335` — `updateSchedule` swallows its error
into `errorMessage` and returns nothing; `init` injects every fetch but the schedule PUT
(`:122-145`). `Views/Sleep/MemorySourcesCard.swift` — `ActivityWindow` (`:11-33`),
`sparklinePoints` (`:44-51`), `weekDots` (`:56-62`), `sparklinePath` (`:150-161`); the Sources
grid calls all three (`Views/Sources/SourceCardGrid.swift:178,181,348`,
`Views/Sources/SourceHeaderCard.swift:126`, `Views/Sources/SourceDetailView.swift:47`).
`/sleep/history` returns `kind` ∈ `sleep | decay | inbox` (`api/services/git_service.py:975-981`) —
an inbox-resolution commit is **not** a cycle.

**Checked in the SDK (`MacOSX.sdk` 26.1), typechecked at `-target arm64-apple-macos14`:**
`onContinuousHover(coordinateSpace:perform:)`, `onKeyPress(_:action:)`, `focusable()`,
`lineLimit(_:reservesSpace:)`, `accessibilityActions { }`, `AccessibilityNotification
.Announcement(_:).post()` (macOS 14, reachable with `import SwiftUI` alone), `Font.italic()`,
`Text.foregroundStyle(_:) -> Text` (macOS 14, which lets the sentence concatenate tinted `Text`
runs) and `Text.monospacedDigit() -> Text`;
`pointerStyle(.link)` is **macOS 15+** (guarded with `#available`, `NSCursor` push/pop below).
No Meadow token (`displayFont`, `quoteFont`, `CicadaMotion`, `hoverLift`, `iconHover`,
`liquidGlass`) exists on this branch — `grep` finds none — so the sentence uses New York through
`CicadaTheme.font(size:design: .serif)` (the design's own fallback).

**Baselines on this base:** Swift **1012 executed, 0 failures**; backend **2225 passed** (untouched
by this track); graph node tests green.

---

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/mascot-page`, based on `dev` @ `bef2e55`). Every shell
  command is `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks relative `cd`; ignore
  its stderr warning). Never an unquoted `--include=*.ext` (zsh globs it) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Fixtures are synthetic: origins `claude-code` / `safari-bookmark` / `saved-link` / `rss`, labels
  like `alpha-project`, commits `c0ffee`, `example.com`.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures** (1012 executed on this base; the count
  grows task by task). Graph JS (untouched, run once at the end):
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`. SourceKit diagnostics naming
  OTHER worktrees are noise. **Working directories:** unless a step says otherwise, every
  `swift build` / `swift test` in this plan runs as `cd <worktree>/app/CicadaApp && …`, and every
  `grep` / `git` runs as `cd <worktree> && …`. The paths a step prints are relative to that
  directory.
- NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app or the
  launchd backend — the owner's installed app is live; the orchestrator installs and live-checks at
  the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv` or `*-report.md`. No push, no new branches or worktrees, no
  subagents. Ignore Devin/PR comments. End every commit message with the session's attribution
  trailer.
- **Green throughout, edited only where this plan says why:** `FixWaveTests`,
  `SleepNumbersLintTests`, `SleepHeroTests` (the twelve bracket strings), `BookwormRendererTests`,
  `BookwormSpriteTests`, `DeskSceneLayoutTests`, `FontLiteralLintTests`, `ThemeTokenTests`,
  `CountLiteralLintTests`, `CopyConstantsTests`.
- **Fonts** only through `CicadaTheme.font(size:weight:design:)`; **durations** only as named
  `SleepMotion` constants (the lint); **colours** only theme tokens or the two art palettes.
- **Art rails (R-Z1…R-Z4, R-Z11, R-Z12):** art encodes state, never quantity; every art bit has a
  text twin; response art never contradicts state art; all worm motion is sprite frames on the one
  lattice (no `.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(` on the worm — a lint); no
  autonomous beat without a fact (only `cheer` on a real completion and the weather crossfade on a
  mood change); Reduce Motion reaches the terminal frame.
- **Copy:** plain and friendly, no jargon, no prices or token counts, no "!", no bare `%`, no
  "est"/"~"/"cluster"/"insight" (R-Z13). Every service named in the UI shows its real mark
  (`OriginMark` / `LogoImage`).
- Docstrings explain **why**, citing the ruling (`R-Z…`, `P…`, this plan's `Z-P…`) or the defect
  that motivated the rule. Match the density of the files touched.

---

## Rulings (binding)

The design's **R-Z1 … R-Z14** hold as written. Below are the decisions this plan takes where the
design left a choice or contradicted the code, each with its reason, so no task re-opens it.

- **Z-P1 — the stage fix reaches three sites, not two, and the strip.** `activeStage(completed:)`
  (`max(1, min(5, completed + 1))`) lives beside the menu-bar derivation in
  `MenuBar/BookwormState.swift` (the lower layer — `Views/` may call `MenuBar/`, not the reverse)
  and is called by `deriveBookwormState`, `deriveSleepPageMood`, the onboarding step's own
  derivation (`OnboardingSleepStep.swift:128`, the site the design missed) and `stageStripState`
  (whose `index == done` was already right; it now says so through the one function — R-Z14's
  "one translation" is literal).
- **Z-P2 — `SleepPageModel` gets its own file** (`Views/Sleep/SleepPageModel.swift`), not a struct
  inside the 893-line `SleepView.swift` the design lists: it is pure, its test must not stand up a
  view, and later tasks grow it. Its stored properties are named so they never shadow the global
  functions they are computed from (`scheduleText`, `nextRunText`, `nextRunAt`,
  `scheduledEngineNote`, `runningStage`) — an instance member named `scheduleSentence` would make
  the unqualified call `scheduleSentence(_:)` inside `resolve` a compile error.
- **Z-P3 — "the last cycle" is `kind == "sleep"`, everywhere on the page.** The design writes
  `history.first { $0.kind != "decay" }` (§6.5, §9), but `/sleep/history` also returns
  `kind: "inbox"` resolution commits (`git_service.py:980`), so `!= "decay"` would call the
  person's own inbox answer "the last cycle" — and "See what changed ›" could open it. One pure
  `lastCycleEntry(_:)` answers for the Readout tile, the answer ladder and the completion link.
- **Z-P4 — the whisper line lands in Z2 and takes the schedule row with it.** The design moves the
  schedule row out of `StudyListCard` in Z3, one commit after the whisper line appears, which would
  state the schedule twice for a commit. Z2 moves both at once; the "Scheduled runs use …"
  difference line rides under the whisper line (exactly today's footer rule) until Z6's lamp
  popover shows the scheduled engine always and deletes it — ruling 4 is never off the page.
- **Z-P5 — a tail link renders only when its destination exists.** `RoomSentenceView` takes
  `canPerform: (SentenceAction) -> Bool`; an action a commit cannot perform yet renders as plain
  words (Z2: `.retry`; Z3 adds `.openDetails`; Z5 `.openInbox`; Z6 `.openLamp`; Z7 `.whatChanged`,
  and Z7 deletes the seam because all five then exist). A link that does nothing would break R-Z2.
  Between Z2 and Z3 the T6 tail says "it's in Details" one commit before Details exists — the
  banners are still on the page then, and the branch is never released between the two.
- **Z-P6 — the lead table is made total.** §5's lead table has no row for `.reading` with a count
  of 0 — exactly the `intakeInFlight` case (`SleepMood.swift:111-113`). It reads **"Something new
  just arrived."** (L8b). `.curious` never reaches this page (G125 R2) and is read like `.reading`
  for totality.
- **Z-P7 — the lead carries its whole visible text.** `SentenceLine.lead` is the full string
  ("47 to read — overdue."), and `numeral` / `qualifier` name *substrings* of it that the view draws
  in SF rounded digits / the tone's colour (`sentenceRuns`). So the ≤ 40 rule, the "!" ban and
  VoiceOver all read one string, and a numeral can sit mid-sentence ("Reading 138 of 203.").
- **Z-P8 — "renders its last words as a link", defined.** The link is the text after the tail's
  last " — ", else the whole tail (`tailLink(_:)`): "Stopped early — **nothing was lost.**",
  "**See what changed ›**". The tail is one `.cicadaPlain` `Button` whose label is one `Text` with
  the link run in `accent`, so it wraps across two lines and Full Keyboard Access reaches it.
- **Z-P9 — the stage strip sits at the bottom of the room card, under the whisper line.** Sketch B
  draws it between the sentence and Cancel, but §15.1 requires that nothing reflows when the strip
  appears — and the control the person just pressed must not jump away from the pointer. Under the
  whisper line only Details moves.
- **Z-P10 — one renderer key segment, measured.** The key is `spriteKey|<look>|frame|size`, the
  `<look>` segment omitted for idle (every pre-Z4 key byte-identical). A reaction replaces the
  pose's frames, so it is keyed by the **gaze** it plays at, not by the pose; and a pose loop that
  repeats a frame (`[a, a, a, blink]`, talk's `[open, rest, open]`) keys the repeat by its first
  occurrence (`BookwormRenderer.keyIndex`). Measured with a port of the sprite code: **216 keys per
  size** for every page state × reachable look (design bound ≤ 256); keyed by pose × reaction it
  would be well past 256.
- **Z-P11 — a capped state crouches instead of hopping.** The nightcap owns rows 0–3 and the
  grid's only headroom is rows 0–1, so `shift(dy: -1)` would clip the cap's crown. In `.reading`
  (and any capped state) the "hop" frame is `shift(dy: +1)` — the whole frame, cap included, one
  cell down; every other state hops up as designed. A reaction's shake moves the head under a
  fixed cap.
- **Z-P12 — the reaction matrix follows §6.4 where §6.1 disagrees.** §6.1 lists gulp for
  awake/happy/reading/hungry; §6.4's matrix also allows it in `.digesting` (it is that state's own
  chew). The matrix wins — it is the "never contradicts state art" table. In `.reading`, gulp
  lowers the held book to row 17 for its three frames (the book persists, lowered).
- **Z-P13 — the pane art is re-checked against the REAL worm union, per weather.** The Meadow
  script masked a hand-approximated worm; ported to the real `BookwormSprites` frames plus every Z4
  pose and reaction, **overcast's second cloud (5/15 visible) and storm's second cloud (8/17)
  fail** the ≥ 50 % rule — the head's shake uncovers column 13. Both become 3×3 glyphs in the right
  pane's free corner (overcast 6/8, storm 8/8 visible). The mask is **per weather** (the moods that
  map to it), because a window only ever shows one weather with its own moods; masking with every
  page state would let happy's sparkles veto the fair sky's cloud. Everything else is the Meadow
  grids cell for cell, shifted two cells left (ink flush to column 0). The plan critic re-ran this
  check with a port of the final sprite and pose code. Every weather passes, but **fair's second
  cloud is exactly 5/10 visible**, right on the threshold: reading's left-gaze and shake frames
  reach pane column 11. Any edit to that cloud or to the reading frames must re-run
  `WindowSpritesTests` first.
- **Z-P14 — no hotspot ships without the thing it opens.** `deskHotspots` returns worm, lamp and
  window rectangles from Z5 (tested), but the lamp button lands with its popover (Z6) and the window
  button with its legend (Z8). Spines are their own `Button`s inside `BookPileView` (their frames
  are SwiftUI layout, not lattice cells); the 2 pt gap above each spine is inside its hit target.
- **Z-P15 — Esc works where the worm has keyboard focus.** `.onKeyPress(.escape)` needs focus; a
  pointer user dismisses by clicking past the last rung or by the 12 s dwell (I4). VoiceOver users
  get the named action.
- **Z-P16 — hints and actions say only what is true today.** The worm's hint is "Click to ask what
  it's doing." — the design's "Drop a file to import it." clause, the "Feed a file…" action and the
  T13 tail all land with Z9 (feeding), not before.
- **Z-P17 — the completion edge resolves when the commit arrives.** `SleepViewModel`'s poll sets
  `status` to idle *before* `load()` refetches history (`SleepViewModel.swift:355` sets it, `:388` reloads), so the edge
  records a `PendingCompletion` (the newest sleep commit before the cycle) and the link + cheer
  resolve on the history change that brings a different newest sleep commit. The cheer plays only
  if the mood's matrix allows it then (`.digesting` / `.happy`); a history that arrives after the
  6 s digest still sets the link, silently. A next cycle clears it. SwiftUI tears the page's
  `@State` down on a tab switch, so "cleared when the page disappears" holds by construction.
- **Z-P18 — `updateSchedule` reports its outcome.** It becomes `@discardableResult … -> Bool`
  over an injectable `putSchedule`, so the lamp toggle can snap back with a caption on failure
  (§7.2) and the rule is testable without a network; `SettingsSleepView` and onboarding ignore the
  result as today.
- **Z-P19 — text on a spine is `CicadaTheme.onFill`.** A new mode-independent token (`.white`,
  declared once beside `pendingPulse`) for text drawn on an identity-hue fill — design defect 7.
  `BookPile.swift` is linted free of `.white`.
- **Z-P20 — the "+more" remainder spine opens Details › What's waiting directly.** It folds several
  sources, so it has no single queue for a popover to show.
- **Z-P21 — relative ages in sentences are words.** `agePhrase(hours:)` sits beside `ageLabel`
  with the same thresholds ("under an hour", "5 hours", "3 days"); the design's example ("The oldest
  has waited 3 days.") is not what `ageLabel`'s "3d" would print.
- **Z-P22 — the gaze function is `gazeFor(pointerX:layout:previous:state:)`.** The design's
  `gaze(…)` would be shadowed inside `RoomModel` by its own `gaze` property.
- **Z-P23 — the one column is 760 pt unscaled**, as today's stacked page; the room fits at every
  zoom step (at 1.4×: 630 pt of room + 112 pt of scaled padding = 742 pt) and a test pins it.
- **Z-P24 — the frame memo is benchmark-gated** (design §6.1): the benchmark ships; the memo ships
  only if it at least halves the measured time per call, and the commit message records both
  numbers either way.
- **Z-P25 — one lamp popover, two anchors.** `RoomModel.lampPopover: LampAnchor?` (`.lamp` |
  `.whisper`) — the lamp and the whisper line each present the same `LampPopover` from where they
  are; the sentence's `.openLamp` anchors at the lamp it names.
- **Z-P26 — engine marks.** Wherever the page names an engine it draws `EngineMark` (`claude-cli`
  → `OriginMark(origin: "claude-code")`, `ollama` → `LogoImage(name: "ollama")`, a key otherwise).
  That covers the control caption, the readout, the lamp popover and the temporary "Scheduled runs
  use …" note. The sentence and the answers name services too: T12's pile, the engine rungs and
  the when-rung's scheduled engine. Each of those lines carries a `SentenceMark` (`.origin` /
  `.engine`) that the slot draws beside its tail. It is a value on the line so a test pins it,
  never inferred from the words (the round-3 rule: a service named in the UI shows its real mark).
  The backend's `why` strings are shown sentence-cased (`sentenceCase`), never rewritten.
- **Z-P27 — the ScheduleToggle hoist takes `isOn` with it**, so `OnboardingSchedule` keeps only
  its sentence (`line`) and Track I can delete the onboarding step without deleting the rule.

---

## File map

| File | Responsibility |
|---|---|
| `…/MenuBar/BookwormState.swift` | `activeStage(completed:)`; `deriveBookwormState` uses it (Z0) |
| `…/MenuBar/BookwormPose.swift` (new) | `Gaze`, `BookwormPose`, `BookwormReaction`, `ActiveReaction`, `BookwormLook`, the §6.4 matrix (Z4) |
| `…/MenuBar/BookwormSprites.swift` | `eyes(…gaze:)`, `frames(for:pose:)`, `reactionFrames`, `frames(for:look:)`, `reactionInterval` (Z4) |
| `…/MenuBar/BookwormRenderer.swift` | `cacheKey(state:look:…)`, `keyIndex`, `cachedImage(state:look:…)`, bound 1024 (Z4) |
| `…/Views/Common/BookwormView.swift` | `pose`, `reaction`, `reactionFrameIndex` (Z4) |
| `…/Views/Sleep/SleepMood.swift` | cancelled ⇒ no digesting; `activeStage` (Z0) |
| `…/Views/Sleep/SleepStages.swift` | `activeStage` in the strip (Z0); `progressive` (Z2); `stageStripIsVisible`, caught-up worm deleted (Z3) |
| `…/Views/Sleep/SleepBubble.swift` | honest stage lines (Z0); `SpeechBubbleView` deleted (Z2) |
| `…/Views/Sleep/SleepQueueModel.swift` | `episodesForOrigin` (Z0); `agePhrase`, `oldestQueuedHours` (Z1) |
| `…/Views/Sleep/StudyListCard.swift` | `nextRunWhen`/`nextRunSentence` (Z0); schedule row + footer out (Z2); header, `queueLoad` (Z1/Z3); hover link, labels, `queueRowWords` (Z6) |
| `…/Views/Sleep/ScheduleToggle.swift` (new) | `ScheduleToggle.isOn` / `.toggled` (Z0) |
| `…/Views/Onboarding/OnboardingSleepStep.swift` | re-pointed at `ScheduleToggle`; `activeStage` (Z0) |
| `…/Models/SourceOverview.swift` | `ownsQueuedOrigin`, `owning(origin:in:)` (Z0) |
| `…/Views/Sleep/SleepPageModel.swift` (new) | `SleepPageModel.resolve`, `lastCycleEntry`, `roomContext` (Z1→Z5) |
| `…/Views/Sleep/RoomSentence.swift` (new) | `SentenceLine`, `RoomContext`, `roomSentence`, runs/links/clauses, `whisperLine`, `RoomSentenceView` (Z2→Z7) |
| `…/Views/Sleep/SleepHero.swift` | `SleepControlRow`, `controlCaption`, `EngineMark` (Z2); `SleepReadoutView` (Z3) |
| `…/Views/Sleep/SleepDetails.swift` (new) | `SleepDetails`, `LastCycleSection`, `lastCycleSectionIsVisible` (Z3) |
| `…/Views/Sources/ActivitySeries.swift` (new, moved) | `ActivityWindow`, `sparklinePoints`, `weekDots`, `sparklinePath` (Z3) |
| `…/Views/Sleep/MemorySourcesCard.swift` | **deleted** (Z3) |
| `…/Views/Sleep/SleepStageStrip.swift` | caught-up worm deleted (Z3) |
| `…/Views/Sleep/SleepView.swift` | page model (Z1); sentence/control/whisper (Z2); one column + Details (Z3); `StudyRoom`, answers (Z5); lamp/whisper (Z6); completion edge (Z7) |
| `…/Views/Sleep/SleepMotion.swift` | beat/sentence/perk/dwell (Z5), hover (Z6), weather (Z8) |
| `…/Views/Sleep/StudyRoom.swift` (new) | `StudyRoom`, `WormStage`, `WormHotspot`, `RoomA11yOrder`, `roomLinkCursor` (Z5→Z8) |
| `…/Views/Sleep/RoomModel.swift` (new) | `RoomModel` (Z5→Z8) |
| `…/Views/Sleep/DeskHotspots.swift` (new) | `DeskHotspot`, `deskHotspots`, `gazeFor`, `sceneBottomLeading` (Z5) |
| `…/Views/Sleep/WormAnswers.swift` (new) | `LastCycleFacts`, `wormAnswers` (Z5) |
| `…/Views/Sleep/BookPile.swift` | `SpineButton`, labels, `onFill` (Z6) |
| `…/Views/Sleep/SpinePopover.swift` (new) | `SpinePopover`, `spinePopoverRows` (Z6) |
| `…/Views/Sleep/LampPopover.swift` (new) | `LampPopover`, `lampEngineLine`, `lampAccessibilityLabel` (Z6) |
| `…/Support/AppRouter.swift` | `pendingSourceDetail`, `routeToSourceDetail`, `consumeSourceDetail` (Z6) |
| `…/Views/Sources/SourcesPageView.swift` | consumes `pendingSourceDetail` (Z6) |
| `…/ViewModels/SleepViewModel.swift` | `updateSchedule -> Bool`, injectable `putSchedule` (Z6) |
| `…/Theme/CicadaTheme.swift` | `onFill` (Z6) |
| `…/Theme/Copy.swift` | the strings each task names |
| `…/Views/Sleep/WindowWeather.swift` (new) | `WindowWeather`, `windowWeather(for:)`, `WindowLegend` (Z8) |
| `…/Views/Sleep/DeskSceneSprites.swift` | `windowGlass` (Z5); window → frame + seven panes (Z8) |
| `…/Views/Sleep/DeskPalette.swift` | 13 → 20 keys (Z8) |
| `…/Views/Sleep/DeskScene.swift` | pane layer, weather crossfade, cache key (Z8) |
| `…/Views/Sleep/HowSleepWorks.swift` | one pointer line to the legend (Z8) |
| Tests (new) | `SleepHonestyTests`, `ScheduleToggleTests`, `SourceOwningTests`, `SleepPageModelTests`, `RoomSentenceTests`, `SleepDetailsTests`, `ActivitySeriesTests` (moved), `BookwormPoseSpriteTests`, `BookwormLookRendererTests`, `BookwormFramesBenchmarkTests`, `DeskHotspotTests`, `GazeTests`, `WormAnswersTests`, `RoomModelTests`, `SpineAndLampTests`, `CompletionEdgeTests`, `WindowWeatherTests`, `WindowSpritesTests` |
| Tests (edited, reason given in the task) | `SleepMoodTests`, `BookwormStateTests`, `OnboardingScheduleTests`, `CopyConstantsTests`, `SleepLayoutTests`, `SleepStageStripTests`, `SleepNumbersLintTests`, `BookPileTests`, `AppRouterTests`, `SleepViewModelTests`, `DeskPaletteTests`, `DeskSceneSpritesTests`, `DeskSceneLayoutTests`; `MemorySourcesTests` → `ActivitySeriesTests` |
| Docs | `CLAUDE.md`, `docs/goals/memory-evolution.md` (G125, G107), `docs/goals/TODO.md`, the round-3 spec |

**Files other round-3 tracks also touch (merge care for the orchestrator):** `OnboardingSleepStep.swift`
(Track I), `CicadaTheme.swift` and `Copy.swift` (M1, everyone), `SourcesPageView.swift` (Track S
is merged; Track I's Home may route to it), `AppRouter.swift` (Track I). Every edit here is a small,
separate hunk.

---

### Task 1 (Z0): The honesty fixes and the hoists — no visible layout change

The three defects are fixed in the pure functions, and four helpers later tasks need are hoisted out
of views into testable functions. Nothing on screen moves except what was wrong.

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift:148-172` — add `activeStage(completed:)`; `:159` uses it
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift:102-110` — `activeStage`; cancelled ⇒ no digesting
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepStages.swift:13-15` (doc), `:138-139` (the strip calls `activeStage`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Onboarding/OnboardingSleepStep.swift:9-38` (hoist out), `:84-86` (re-point), `:128` (`activeStage`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepBubble.swift:36-37`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepQueueModel.swift` — append `episodesForOrigin`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift` — `nextRunWhen`/`nextRunSentence` beside `scheduleSentence` (`:44-68`); delete the private `episodesForOrigin` (`:342-349`) and `nextRunText` (`:351-367`); their two call sites (`:193`, `:330`) use the hoists
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/ScheduleToggle.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift:81-87`
- Test (new): `SleepHonestyTests.swift`, `ScheduleToggleTests.swift`, `SourceOwningTests.swift`
- Test (edit — inputs only, the asserted values survive, design §13.1): `SleepMoodTests.swift:93` (`stage: 3` → `2`), `:200` (`4` → `3`), `:286` (`2` → `1`); `BookwormStateTests.swift:31` (`2` → `1`). The clamp tests (`SleepMoodTests.swift:100-103`, `BookwormStateTests.swift:41`) pass unchanged (`activeStage(0) == 1`, `activeStage(9) == 5`).
- Test (edit — the rule moved, Z-P27): `OnboardingScheduleTests.swift:31-36` (`OnboardingSchedule.isOn` → `ScheduleToggle.isOn`), `:41-53` moves to `ScheduleToggleTests`; `CopyConstantsTests.swift:81` (`OnboardingSchedule.toggled` → `ScheduleToggle.toggled`).

**Interfaces:**
- Produces: `activeStage(completed:) -> Int`; `episodesForOrigin(_:in:)`; `nextRunWhen(_:nextSleepAt:locale:timeZone:) -> String?`; `nextRunSentence(_:nextSleepAt:locale:timeZone:) -> String`; `ScheduleToggle.isOn(_:)`, `ScheduleToggle.toggled(on:current:)`; `SourceOverview.ownsQueuedOrigin(_:)`, `SourceOverview.owning(origin:in:)`.
- Consumes: `SleepStatusResponse.stage` / `.cancelled`, `StatusSnapshot.Sleep.stage`, `parseEpisodeTimestamp`, `Copy.nextRunManual`.

- [ ] **Step 1: Failing tests.** `Tests/CicadaAppTests/SleepHonestyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z, Z0 — the honesty fixes (design §13.1–§13.3) and the hoists later
/// tasks read. Every case asserts an exact value.
final class SleepHonestyTests: XCTestCase {

    private func status(_ json: String) throws -> SleepStatusResponse {
        try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
    }

    // MARK: R-Z14 — one stage translation

    /// `SleepStatusResponse.stage` counts COMPLETED stages (`sleep_cycle.py`
    /// sets 1 only after Stage 1 returns), so a running cycle is in
    /// `completed + 1`, clamped to the five.
    func test_activeStage_isOneAheadOfTheCompletedCount() {
        XCTAssertEqual(activeStage(completed: 0), 1, "Read runs before anything has completed")
        XCTAssertEqual(activeStage(completed: 1), 2, "Sort runs once Read has returned")
        XCTAssertEqual(activeStage(completed: 4), 5)
        XCTAssertEqual(activeStage(completed: 5), 5, "the tail after File still reads as File")
        XCTAssertEqual(activeStage(completed: -3), 1)
        XCTAssertEqual(activeStage(completed: 9), 5)
    }

    /// The page mood, the menu bar, onboarding and the strip must name the
    /// SAME stage for one reading — the defect was that three of them said
    /// "stage 1" while the strip lit Sort.
    func test_theMoodTheMenuBarAndTheStripAgreeWhileSortRuns() throws {
        let running = try status(#"{"status":"running","stage":1}"#)
        XCTAssertEqual(deriveSleepPageMood(status: running, debt: nil, justFinishedAt: nil), .sleeping(stage: 2))
        let snapshot = StatusSnapshot(
            sleep: .init(status: "running", stage: 1, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)
        XCTAssertEqual(deriveBookwormState(snapshot, justFinishedAt: nil), .sleeping(stage: 2))
        let pips = stageStripState(stage: 1, isRunning: true, cancelled: false, error: false, read: 0, total: 0)
        XCTAssertEqual(pips, [.done, .active(fill: nil), .pending, .pending, .pending])
        XCTAssertEqual(pips.firstIndex(of: .active(fill: nil)), activeStage(completed: 1) - 1)
    }

    // MARK: §13.3 — honest stage lines

    /// Stage 3 used to announce a contradiction and stage 4 a habit on EVERY
    /// cycle, whether or not one existed. The lines now say what the stage
    /// does, not what it found.
    func test_theBubbleNeverAssertsAFindingItHasNotMeasured() {
        XCTAssertEqual(sleepBubbleText(.sleeping(stage: 3), BubbleContext()), "Checking for contradictions.")
        XCTAssertEqual(sleepBubbleText(.sleeping(stage: 4), BubbleContext()), "Looking for habits.")
    }

    // MARK: Hoist — the next run (was StudyListCard.nextRunText)

    private let utc = TimeZone(identifier: "UTC")!
    private let posix = Locale(identifier: "en_US_POSIX")

    func test_nextRunSentence_namesTheDateTheBackendReported() {
        let daily = ScheduleConfig(mode: "daily", hour: 3, minute: 0)
        XCTAssertEqual(nextRunWhen(daily, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc),
                       "Sep 24, 3:00 AM")
        XCTAssertEqual(nextRunSentence(daily, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc),
                       "Next run Sep 24, 3:00 AM")
    }

    /// A manual bank has no next run, whatever the snapshot carries — the
    /// schedule is the truth (`ScheduleConfig.mode`).
    func test_nextRunSentence_manualNeverNamesADate() {
        let manual = ScheduleConfig(mode: "manual", hour: 3, minute: 0)
        XCTAssertEqual(nextRunSentence(manual, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc),
                       Copy.nextRunManual)
        XCTAssertNil(nextRunWhen(manual, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc))
    }

    /// Unknown is a dash (R-A14) — except after-import, whose rule is a sentence.
    func test_nextRunSentence_unknownDateIsADashOrTheImportRule() {
        XCTAssertEqual(nextRunSentence(ScheduleConfig(mode: "interval", hour: 3, minute: 0), nextSleepAt: nil,
                                       locale: posix, timeZone: utc), "Next run —")
        XCTAssertEqual(nextRunSentence(ScheduleConfig(mode: "after_import", hour: 3, minute: 0), nextSleepAt: nil,
                                       locale: posix, timeZone: utc), "Next run after the next import")
    }

    // MARK: Hoist — one source's queue (was StudyListCard.episodesForOrigin)

    private func episode(_ id: String, origin: String, at timestamp: String) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: Data("""
        {"id":"\(id)","timestamp":"\(timestamp)","source":"mcp","origin":"\(origin)","preview":"","processed":false}
        """.utf8))
    }

    func test_episodesForOrigin_isThatOriginNewestFirstWithUnparseableLast() throws {
        let all = [try episode("old", origin: "claude-code", at: "2026-09-01T00:00:00Z"),
                   try episode("other", origin: "rss", at: "2026-09-05T00:00:00Z"),
                   try episode("bad", origin: "claude-code", at: "not a date"),
                   try episode("new", origin: "claude-code", at: "2026-09-03T00:00:00Z")]
        XCTAssertEqual(episodesForOrigin("claude-code", in: all).map(\.id), ["new", "old", "bad"])
        XCTAssertTrue(episodesForOrigin("telegram", in: all).isEmpty)
    }
}
```

`SleepMoodTests.swift` — add beside `test_mood_isDigesting_within6sOfJustFinished`:

```swift
    /// Track Z §6.5 / design §13.2: `SleepView` stamps `justFinishedAt` on
    /// ANY running→idle edge, so a CANCELLED cycle used to chew for six
    /// seconds and read "digesting". A cancel files nothing; it never chews.
    func test_mood_isNotDigesting_afterACancelledCycle() throws {
        let now = Date()
        let cancelled = try JSONDecoder().decode(SleepStatusResponse.self,
                                                 from: Data(#"{"status":"idle","cancelled":true}"#.utf8))
        XCTAssertEqual(deriveSleepPageMood(status: cancelled, debt: debtView(unprocessedCount: 0),
                                           justFinishedAt: now.addingTimeInterval(-1), now: now), .happy)
        let completed = try status(status: "idle")
        XCTAssertEqual(deriveSleepPageMood(status: completed, debt: debtView(unprocessedCount: 0),
                                           justFinishedAt: now.addingTimeInterval(-1), now: now), .digesting,
                       "a completed cycle still chews")
    }
```

`Tests/CicadaAppTests/ScheduleToggleTests.swift` (the body of `OnboardingScheduleTests
.testTogglingWritesOnlyManualOrDailyAtThree` moves here verbatim, renamed, re-pointed):

```swift
import XCTest
@testable import CicadaApp

/// Track Z, Z0 (Z-P27) — the schedule toggle's rule, hoisted out of the
/// onboarding step so the Sleep page's lamp (Z6) and onboarding share ONE
/// definition, and Track I can delete its step without deleting the rule.
final class ScheduleToggleTests: XCTestCase {

    func test_isOn_isEveryModeButManual() {
        XCTAssertFalse(ScheduleToggle.isOn(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
        for mode in ["daily", "interval", "after_import"] {
            XCTAssertTrue(ScheduleToggle.isOn(ScheduleConfig(mode: mode, hour: 3, minute: 0)), mode)
        }
    }

    /// ON from manual writes exactly `daily 03:00`; OFF from any mode writes
    /// `manual` and keeps hour/minute; ON when already scheduled never
    /// downgrades a rhythm chosen in Settings (Track P R4).
    func test_toggled_writesOnlyManualOrDailyAtThree_andNeverDowngrades() {
        let on = ScheduleToggle.toggled(on: true, current: ScheduleConfig(mode: "manual", hour: 9, minute: 15))
        XCTAssertEqual(on.mode, "daily"); XCTAssertEqual(on.hour, 3); XCTAssertEqual(on.minute, 0)
        let off = ScheduleToggle.toggled(on: false, current: ScheduleConfig(mode: "interval", hour: 9, minute: 15, intervalHours: 4))
        XCTAssertEqual(off.mode, "manual"); XCTAssertEqual(off.hour, 9); XCTAssertEqual(off.minute, 15)
        XCTAssertEqual(off.intervalHours, 4)
        let keep = ScheduleToggle.toggled(on: true, current: ScheduleConfig(mode: "after_import", hour: 3, minute: 0))
        XCTAssertEqual(keep.mode, "after_import")
    }
}
```

`Tests/CicadaAppTests/SourceOwningTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z §7.1 — `SourceOverview.owning(origin:in:)` is the inverse of
/// `ownedQueue(from:)`: a spine's "Open in Sources ›" lands on the source
/// whose queue strip shows the same episodes, or the link is hidden.
final class SourceOwningTests: XCTestCase {

    private func item(_ id: String, _ origin: String) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: Data(
            #"{"id":"\#(id)","timestamp":"2026-09-01T00:00:00Z","source":"x","origin":"\#(origin)","preview":"","processed":false}"#.utf8))
    }

    private let rows = [
        SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, harness: "claude-code"),
        SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, harness: "cursor"),
        SourceOverview(id: "safari-bookmarks", label: "Safari bookmarks", kind: .browser, origins: ["safari-bookmark"]),
        SourceOverview(id: "files", label: "Files & links", kind: .import, origins: ["saved-link"]),
    ]

    func test_owning_roundTripsEveryQueuedEpisodeToTheRowThatOwnsIt() throws {
        let all = try [item("1", "claude-code"), item("2", "mcp"), item("3", "cursor"),
                       item("4", "safari-bookmark"), item("5", "saved-link"), item("6", "unknown")]
        var checked = 0
        for row in rows {
            for episode in row.ownedQueue(from: all) {
                XCTAssertEqual(SourceOverview.owning(origin: episode.origin, in: rows)?.id, row.id, episode.id)
                checked += 1
            }
        }
        XCTAssertEqual(checked, 5, "every stamped episode has an owner; `unknown` has none")
    }

    func test_owning_givesTheLegacyMcpOriginToClaudeCodeOnly() {
        XCTAssertEqual(SourceOverview.owning(origin: "mcp", in: rows)?.id, "harness:claude-code")
        XCTAssertNil(SourceOverview.owning(origin: "mcp", in: Array(rows.dropFirst())), "cursor never adopts mcp")
    }

    func test_owning_isNilWhenNoRowOwnsTheOrigin_neverAGuess() {
        XCTAssertNil(SourceOverview.owning(origin: "unknown", in: rows))
        XCTAssertNil(SourceOverview.owning(origin: "telegram", in: rows))
    }
}
```

Run `cd <worktree>/app/CicadaApp && swift test --filter 'SleepHonestyTests|ScheduleToggleTests|SourceOwningTests|SleepMoodTests' 2>&1 | tail -20` — expect compile failures (the functions do not exist).

- [ ] **Step 2: Implement.**

`MenuBar/BookwormState.swift`, above `deriveBookwormState`:

```swift
/// The stage a RUNNING cycle is in (Track Z R-Z14, design §13.1).
///
/// The wire's `stage` counts COMPLETED stages — `sleep_cycle.py` sets it to 1
/// only after Stage 1 returns — so the stage in flight is one ahead. Three
/// derivations used to clamp the raw number instead (the menu bar here, the
/// Sleep page's `deriveSleepPageMood`, onboarding), so while Sort ran the
/// worm's dots, the bracket line and VoiceOver all said "stage 1" while the
/// strip lit Sort. One translation, read by all four (the strip included).
func activeStage(completed: Int) -> Int {
    max(1, min(5, completed + 1))
}
```

and `:159` becomes `return .sleeping(stage: activeStage(completed: s.sleep.stage))`.
Update `BookwormState.sleeping`'s case doc (`:10`) to "`stage` is the ACTIVE stage, 1…5 —
`activeStage(completed:)`".

`Views/Sleep/SleepMood.swift:102-110`:

```swift
    if status.status == "running" {
        return .sleeping(stage: activeStage(completed: status.stage))
    }
    if let err = status.error, !err.isEmpty {
        return .error   // R6: the failure is the news, not the six-second chew
    }
    // Track Z §6.5: a CANCELLED cycle filed nothing, so it never chews. The
    // caller stamps `justFinishedAt` on any running→idle edge (SleepView), and
    // this is the one place that edge becomes a mood.
    if !status.cancelled, let f = justFinishedAt, now.timeIntervalSince(f) < 6 {
        return .digesting
    }
```

Add one line to `deriveSleepPageMood`'s docstring bullet list: "- a cancelled cycle never reads as
`.digesting` (Track Z §6.5)".

`Views/Sleep/SleepStages.swift` — the `number` doc (`:13-15`) now reads "…so a running cycle's
active stage is `activeStage(completed:)` — the one translation (R-Z14)", and in `stageStripState`
replace `guard index == done else { return .pending }` with
`guard index == activeStage(completed: stage) - 1 else { return .pending }` (identical for every
`stage` in 0…4; for 5 the `index < done` branch has already returned `.done`).

`Views/Onboarding/OnboardingSleepStep.swift:128`:
`return .sleeping(stage: activeStage(completed: sleepVM.status?.stage ?? 0))`.

`Views/Sleep/SleepBubble.swift:36-37`:

```swift
        case 3: return "Checking for contradictions."   // design §13.3 — what the stage DOES, not a finding
        case 4: return "Looking for habits."
```

`Views/Sleep/SleepQueueModel.swift` — append:

```swift
// MARK: - One source's queue (hoisted from StudyListCard, Track Z Z0)

/// The queued episodes from one `origin`, newest first; a timestamp that
/// fails every parse sorts last rather than being coerced to "now". Hoisted
/// so the study list's disclosure and a spine's popover (Z6) show the same
/// episodes in the same order.
func episodesForOrigin(_ origin: String, in episodes: [EpisodeQueueItem]) -> [EpisodeQueueItem] {
    episodes
        .filter { $0.origin == origin }
        .sorted {
            (parseEpisodeTimestamp($0.timestamp) ?? .distantPast)
                > (parseEpisodeTimestamp($1.timestamp) ?? .distantPast)
        }
}
```

`Views/Sleep/StudyListCard.swift` — after `scheduledEngineLine` (`:68`):

```swift
/// The date half of the next-run line — `nil` when there is none to state:
/// a manual bank, or a snapshot with no `nextSleepAt`. Hoisted from the queue
/// card's footer (Track Z Z0) because the whisper line (Z2) and the worm's
/// "when" answer (Z5) both need it; `locale`/`timeZone` are injected so a
/// test never depends on the runner's.
func nextRunWhen(_ schedule: ScheduleConfig, nextSleepAt: String?,
                 locale: Locale = .current, timeZone: TimeZone = .current) -> String? {
    guard schedule.mode != "manual", let date = StatusSnapshot.parseDate(nextSleepAt) else { return nil }
    let f = DateFormatter()
    f.dateFormat = "MMM d, h:mm a"
    f.locale = locale
    f.timeZone = timeZone
    return f.string(from: date)
}

/// "Manual only" / "Next run Sep 24, 3:00 AM" / "Next run after the next
/// import" / "Next run —" (R-A14: an unknown is a dash, never a guess).
func nextRunSentence(_ schedule: ScheduleConfig, nextSleepAt: String?,
                     locale: Locale = .current, timeZone: TimeZone = .current) -> String {
    if schedule.mode == "manual" { return Copy.nextRunManual }
    if let when = nextRunWhen(schedule, nextSleepAt: nextSleepAt, locale: locale, timeZone: timeZone) {
        return "Next run \(when)"
    }
    return schedule.mode == "after_import" ? "Next run after the next import" : "Next run —"
}
```

Delete the private `episodesForOrigin` and `nextRunText`; `:193` becomes
`ForEach(episodesForOrigin(row.origin, in: episodes)) { ep in`, `:330` becomes
`Text(nextRunSentence(sleepVM.schedule, nextSleepAt: status?.nextSleepAt))`.

`Views/Sleep/ScheduleToggle.swift`:

```swift
import Foundation

/// The one rule behind every "Read on a schedule" switch in the app (Track Z
/// Z0, Z-P27) — hoisted from `OnboardingSchedule` so the Sleep page's lamp
/// popover (Z6) and onboarding share it, and a later onboarding redesign
/// (Track I) can delete its step without deleting the rule.
///
/// The toggle moves between exactly two states (Track P R4): ON from manual
/// writes `daily` at 03:00 (`sleep_scheduler._DEFAULT`'s hour), and never
/// downgrades an `interval` or `after_import` rhythm chosen in Settings → Sleep;
/// OFF writes `manual` and keeps hour and minute, so re-enabling restores them.
enum ScheduleToggle {
    static func isOn(_ schedule: ScheduleConfig) -> Bool { schedule.mode != "manual" }

    static func toggled(on: Bool, current: ScheduleConfig) -> ScheduleConfig {
        if !on {
            var next = current; next.mode = "manual"; return next
        }
        if isOn(current) { return current }
        var next = current; next.mode = "daily"; next.hour = 3; next.minute = 0
        return next
    }
}
```

`OnboardingSleepStep.swift`: `OnboardingSchedule` keeps only `line(_:)` (its docstring gains
"the toggle's rule moved to `ScheduleToggle` (Track Z Z0)"); `:84-86` reads
`get: { ScheduleToggle.isOn(sleepVM.schedule) }` and
`Task { await sleepVM.updateSchedule(ScheduleToggle.toggled(on: on, current: sleepVM.schedule)) }`.

`Models/SourceOverview.swift:81-87`:

```swift
    func ownedQueue(from all: [EpisodeQueueItem]) -> [EpisodeQueueItem] {
        all.filter { ownsQueuedOrigin($0.origin) }
    }

    /// Whether an episode stamped `origin` is in this row's queue — the ONE
    /// rule `ownedQueue(from:)` and `owning(origin:in:)` share, so a Sleep
    /// spine's "Open in Sources ›" (Track Z §7.1) and this source's queue strip
    /// can never disagree about whose episode it is.
    func ownsQueuedOrigin(_ origin: String) -> Bool {
        if let harness {
            return origin == harness || (harness == "claude-code" && origin == "mcp")
        }
        return origins.contains(origin)
    }

    /// The inverse of `ownedQueue` — the row whose queue `origin` lands in, or
    /// `nil` when none owns it, in which case the caller hides its link rather
    /// than guessing (R-A14). First match in the order given; the catalog never
    /// gives two rows one origin.
    static func owning(origin: String, in rows: [SourceOverview]) -> SourceOverview? {
        rows.first { $0.ownsQueuedOrigin(origin) }
    }
```

(The existing `ownedQueue` docstring above `:81` stays; it describes the rule both now share.)

Then the test edits listed under **Files**.

- [ ] **Step 3: Verify.** `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5`, then
  `swift test 2>&1 | tail -20` → 0 failures. Also `cd <worktree> && grep -rn "max(1, min(5" app/CicadaApp/Sources` must print
  nothing (every clamp now goes through `activeStage`).
- [ ] **Step 4: Commit.** Stage the nine source files (`BookwormState`, `SleepMood`, `SleepStages`,
  `OnboardingSleepStep`, `SleepBubble`, `SleepQueueModel`, `StudyListCard`, `ScheduleToggle`,
  `SourceOverview`) and the seven test files (`SleepHonestyTests`, `ScheduleToggleTests`,
  `SourceOwningTests` new; `SleepMoodTests`, `BookwormStateTests`, `OnboardingScheduleTests`,
  `CopyConstantsTests` edited) by name;
  `fix(sleep v4): the active stage, a cancel that never chews, honest stage lines + the Z0 hoists (G125 v4, R-Z14)`.

---

### Task 2 (Z1): `SleepPageModel` — one resolve per body

Everything the page draws (design §9) is resolved once, as a value, from the inputs the view
already holds. The view keeps today's layout; only its reads move. This removes the duplicated
`studyListRows` evaluation (defect 5) and gives every later task one place to read from.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepPageModel.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepQueueModel.swift` — append `agePhrase(hours:)`, `oldestQueuedHours(_:now:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — `resolvePage()`; `body` resolves once and hands the value down; delete `liveOriginCounts` (`:240-242`) and `studyListRows` (`:244-252`); `deskCard` takes the page
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift` — takes `queueLoad` instead of re-deriving it from the Store (`:100-121` keeps the static `loadState`, which `resolvePage` now calls)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepHero.swift:374-379` — `SleepHeroView` takes `lastDurationMs` (from `page.lastCycle`, Z-P3) instead of reading `sleepVM.history`
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/SleepPageModelTests.swift`

**Interfaces:**
- Produces: `SleepPageModel` (fields below) and `SleepPageModel.resolve(status:sse:queued:schedule:enginePreview:history:storeStatus:queueLoad:justFinishedAt:intakeInFlight:now:locale:timeZone:)`; `lastCycleEntry(_:)`; `agePhrase(hours:)`; `oldestQueuedHours(_:now:)`.
- Consumes: `resolveSleepDebt`, `resolveOriginCounts`, `deriveSleepPageMood`, `activeStage`, `studyRows`, `originVolumes`, `bookPileLayout`, `stageStripState`, `scheduleSentence`, `nextRunWhen`, `nextRunSentence`, `scheduledEngineLine`, `StudyListCard.LoadState`.

- [ ] **Step 1: Failing tests.** `Tests/CicadaAppTests/SleepPageModelTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z, Z1 — every number and state the Sleep page draws (design §9),
/// resolved once from fixtures. The SSE-over-REST precedence the Store has
/// always had is asserted here for the page as a whole, so a later task
/// cannot quietly read one half from SSE and the other from REST.
final class SleepPageModelTests: XCTestCase {

    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private let utc = TimeZone(identifier: "UTC")!
    private let posix = Locale(identifier: "en_US_POSIX")

    private func status(_ json: String) throws -> SleepStatusResponse {
        try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
    }

    private func episode(_ id: String, _ origin: String, hoursAgo: Double, chars: Int = 100) throws -> EpisodeQueueItem {
        let stamp = ISO8601DateFormatter().string(from: now.addingTimeInterval(-hoursAgo * 3600))
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: Data("""
        {"id":"\(id)","timestamp":"\(stamp)","source":"mcp","origin":"\(origin)","preview":"","chars":\(chars),"processed":false}
        """.utf8))
    }

    private func entry(_ hash: String, kind: String, episodes: Int = 3, durationMs: Int? = nil) throws -> SleepHistoryEntry {
        let duration = durationMs.map(String.init) ?? "null"
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: Data("""
        {"commitHash":"\(hash)","date":"2026-09-20T03:00:00+00:00","message":"x","kind":"\(kind)",
         "episodes":\(episodes),"entitiesCreated":2,"entitiesUpdated":1,"durationMs":\(duration)}
        """.utf8))
    }

    private func snapshot(inbox: Int = 0, nextSleepAt: String? = nil) -> StatusSnapshot {
        StatusSnapshot(sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
                       inbox: .init(total: inbox, byKind: [:]),
                       episodes: .init(unprocessed: 0, lastIngestedAt: nil),
                       lastSleepAt: nil, nextSleepAt: nextSleepAt)
    }

    private func resolve(status: SleepStatusResponse?, sse: SleepEventPayload? = nil,
                         queued: [EpisodeQueueItem] = [], schedule: ScheduleConfig = ScheduleConfig(mode: "manual", hour: 3, minute: 0),
                         preview: SleepEnginePreviews? = nil, history: [SleepHistoryEntry] = [],
                         storeStatus: StatusSnapshot? = nil,
                         queueLoad: StudyListCard.LoadState = .loaded(count: 0),
                         justFinishedAt: Date? = nil, intakeInFlight: Bool = false) -> SleepPageModel {
        SleepPageModel.resolve(status: status, sse: sse, queued: queued, schedule: schedule,
                               enginePreview: preview, history: history, storeStatus: storeStatus,
                               queueLoad: queueLoad, justFinishedAt: justFinishedAt,
                               intakeInFlight: intakeInFlight, now: now, locale: posix, timeZone: utc)
    }

    private let idleJSON = #"{"status":"idle","debt":{"unprocessedCount":2,"oldestUnprocessedAgeHours":null,"hoursSinceLastCycle":5,"hasRunBefore":true,"volumePct":10,"agePct":10,"restedPct":80}}"#

    func test_mood_andTheRunningStageComeFromTheOneDerivation() throws {
        let running = resolve(status: try status(#"{"status":"running","stage":1}"#))
        XCTAssertEqual(running.mood, .sleeping(stage: 2))
        XCTAssertEqual(running.runningStage, 2, "the active stage, R-Z14")
        XCTAssertTrue(running.isRunning)
        let idle = resolve(status: try status(idleJSON), queued: [try episode("1", "claude-code", hoursAgo: 2)])
        XCTAssertNil(idle.runningStage)
        XCTAssertEqual(idle.mood, .reading)
    }

    /// SSE wins whole-reading, never a hybrid (`resolveSleepDebt` /
    /// `resolveOriginCounts`) — asserted for the page, not only the helpers.
    func test_sseOutranksRest_forTheDebtAndTheOriginCounts() throws {
        let rest = try status(#"{"status":"running","stage":0,"queueByOrigin":{"rss":9},"readByOrigin":{"rss":1},"debt":{"unprocessedCount":99,"oldestUnprocessedAgeHours":null,"hoursSinceLastCycle":1,"hasRunBefore":true,"volumePct":0,"agePct":0,"restedPct":1}}"#)
        let sse = SleepEventPayload(status: "running", restedPct: 40, volumePct: 0, agePct: 0, unprocessedCount: 7,
                                    hasRunBefore: true, hoursSinceLastCycle: 2,
                                    queueByOrigin: ["claude-code": 10], readByOrigin: ["claude-code": 4])
        let page = resolve(status: rest, sse: sse)
        XCTAssertEqual(page.debt?.unprocessedCount, 7)
        XCTAssertEqual(page.read, 4)
        XCTAssertEqual(page.total, 10)
    }

    func test_theQueueIsGroupedOnce_andThePileAndTheOldestWaitReadTheSameRows() throws {
        let queued = [try episode("1", "claude-code", hoursAgo: 72, chars: 5000),
                      try episode("2", "claude-code", hoursAgo: 1),
                      try episode("3", "rss", hoursAgo: 5)]
        let page = resolve(status: try status(idleJSON), queued: queued)
        XCTAssertEqual(page.rows.map(\.origin), ["claude-code", "rss"])
        XCTAssertEqual(page.books.map(\.origin), ["claude-code", "rss"])
        XCTAssertEqual(page.queuedCount, 3)
        XCTAssertEqual(page.oldestWait, "3 days")
        XCTAssertEqual(page.topOriginLabel, OriginIconography.label(for: "claude-code"))
        XCTAssertEqual(page.topOrigin, "claude-code", "the label's mark rides with it")
    }

    func test_theScheduleTheLampAndTheNextRunAreOneReading() throws {
        let daily = ScheduleConfig(mode: "daily", hour: 3, minute: 0)
        let page = resolve(status: try status(idleJSON), schedule: daily,
                           storeStatus: snapshot(nextSleepAt: "2026-09-24T03:00:00Z"))
        XCTAssertTrue(page.lampLit)
        XCTAssertEqual(page.scheduleText, "Every day at 03:00")
        XCTAssertEqual(page.nextRunAt, "Sep 24, 3:00 AM")
        XCTAssertEqual(page.nextRunText, "Next run Sep 24, 3:00 AM")
        let manual = resolve(status: try status(idleJSON))
        XCTAssertFalse(manual.lampLit)
        XCTAssertEqual(manual.nextRunText, Copy.nextRunManual)
    }

    func test_enginesAreNamedOnlyOnceLoaded() throws {
        XCTAssertNil(resolve(status: try status(idleJSON)).manualEngine, "a guessed engine is worse than silence")
        let previews = SleepEnginePreviews(
            manual: SleepEnginePreview(engine: "claude-cli", model: "m", why: "your plan"),
            scheduled: SleepEnginePreview(engine: "ollama", model: "m", why: "a scheduled cycle never spends plan quota"))
        let page = resolve(status: try status(idleJSON), preview: previews)
        XCTAssertEqual(page.manualEngine, "claude-cli")
        XCTAssertEqual(page.scheduledEngineNote, Copy.scheduledRunsOn(engine: "ollama"))
        XCTAssertEqual(page.scheduledEngine, "ollama")
        let same = SleepEnginePreviews(manual: SleepEnginePreview(engine: "ollama", model: "m", why: "w"),
                                       scheduled: SleepEnginePreview(engine: "ollama", model: "m", why: "w"))
        XCTAssertNil(resolve(status: try status(idleJSON), preview: same).scheduledEngine,
                     "named only when it differs, like the note")
    }

    /// Enabled only when the status has loaded, nothing is running and the
    /// queue is non-empty — the button is disabled, never hidden.
    func test_consolidateIsEnabledOnlyWithSomethingToReadAndNothingRunning() throws {
        let one = [try episode("1", "rss", hoursAgo: 1)]
        XCTAssertTrue(resolve(status: try status(idleJSON), queued: one).consolidateEnabled)
        XCTAssertFalse(resolve(status: try status(idleJSON)).consolidateEnabled)
        XCTAssertFalse(resolve(status: nil, queued: one).consolidateEnabled)
        XCTAssertFalse(resolve(status: try status(#"{"status":"running"}"#), queued: one).consolidateEnabled)
    }

    /// The news flags — an empty error or warning string is not news.
    func test_theNewsFlagsIgnoreEmptyStrings() throws {
        let quiet = resolve(status: try status(#"{"status":"idle","error":"","indexWarning":""}"#))
        XCTAssertNil(quiet.cycleError); XCTAssertNil(quiet.indexWarning)
        XCTAssertFalse(quiet.cancelled); XCTAssertFalse(quiet.capped)
        let loud = resolve(status: try status(#"{"status":"idle","error":"boom","indexWarning":"w","cancelled":true,"episodesQueued":9,"episodesTotal":4}"#))
        XCTAssertEqual(loud.cycleError, "boom"); XCTAssertEqual(loud.indexWarning, "w")
        XCTAssertTrue(loud.cancelled); XCTAssertTrue(loud.capped)
        XCTAssertEqual(loud.pips.first, .failed, "the strip freezes where the failure happened (P15)")
    }

    /// Z-P3 — an inbox resolution commit is not a cycle, and neither is a
    /// decay-only one.
    func test_theLastCycleIsTheNewestSleepCommit() throws {
        let history = [try entry("inbox1", kind: "inbox"), try entry("decay1", kind: "decay"),
                       try entry("c0ffee", kind: "sleep", durationMs: 252_000), try entry("older", kind: "sleep")]
        XCTAssertEqual(lastCycleEntry(history)?.commitHash, "c0ffee")
        XCTAssertEqual(resolve(status: try status(idleJSON), history: history).lastCycle?.durationMs, 252_000)
        XCTAssertNil(lastCycleEntry([try entry("inbox1", kind: "inbox")]))
    }

    func test_theInboxCountAndTheQueueLoadPassThrough() throws {
        let page = resolve(status: try status(idleJSON), storeStatus: snapshot(inbox: 4), queueLoad: .loading)
        XCTAssertEqual(page.inboxTotal, 4)
        XCTAssertEqual(page.queueLoad, .loading)
        XCTAssertNil(resolve(status: try status(idleJSON)).inboxTotal, "no snapshot = unknown, not zero")
    }

    // MARK: agePhrase (Z-P21) — ageLabel's thresholds, in words

    func test_agePhrase_isTheLongFormOfAgeLabel() {
        XCTAssertEqual(agePhrase(hours: 0.4), "under an hour")
        XCTAssertEqual(agePhrase(hours: 1.2), "1 hour")
        XCTAssertEqual(agePhrase(hours: 47.9), "47 hours")
        XCTAssertEqual(agePhrase(hours: 72), "3 days")
        XCTAssertEqual(ageLabel(hours: 72), "3d", "the list keeps its compact label")
    }
}
```

- [ ] **Step 2: Implement.** `Views/Sleep/SleepQueueModel.swift` — after `ageLabel`:

```swift
/// `ageLabel`'s long form, for sentences (Track Z Z-P21) — the same thresholds
/// in whole words, so "The oldest has waited 3 days." and the list's "3d" can
/// never disagree about the age, only about how much room they have.
func agePhrase(hours: Double) -> String {
    if hours < 1 { return "under an hour" }
    if hours < 48 {
        let h = Int(hours)
        return h == 1 ? "1 hour" : "\(h) hours"
    }
    return "\(Int(hours / 24)) days"
}

/// How long the oldest queued episode has waited, in hours — `nil` for an
/// empty queue or one whose timestamps all fail to parse (never a guess).
func oldestQueuedHours(_ queued: [EpisodeQueueItem], now: Date = .now) -> Double? {
    queued.compactMap { parseEpisodeTimestamp($0.timestamp) }.min().map { now.timeIntervalSince($0) / 3600 }
}
```

`Views/Sleep/SleepPageModel.swift`:

```swift
import Foundation

/// Everything the Sleep page draws, resolved ONCE per body evaluation (Track Z
/// §9, Z1).
///
/// The H1 rule — the room, the queue and the controls must never disagree
/// about which reading they show — used to be kept by hand: `SleepView`
/// resolved the SSE-vs-REST precedence in three computed properties and
/// evaluated `studyRows` twice per body. A value computed once makes the rule
/// structural, and it is pure, so every row of the design's data table is a
/// unit test instead of a screenshot.
///
/// Stored names never shadow the global functions they come from
/// (`scheduleText` ← `scheduleSentence`, `nextRunText` ← `nextRunSentence`,
/// `runningStage` ← `activeStage`) — Z-P2: an instance member with a
/// function's name makes the unqualified call inside `resolve` a compile error.
struct SleepPageModel: Equatable {
    var mood: BookwormState
    var debt: SleepDebtView?
    var isRunning: Bool
    /// The ACTIVE stage (R-Z14) while running; `nil` idle.
    var runningStage: Int?
    /// Sums of `resolveOriginCounts` — `Read a of b`, the strip's Read fill.
    var read: Int
    var total: Int
    var rows: [StudyRow]
    var books: [BookSpec]
    var pips: [StagePip]
    var schedule: ScheduleConfig
    /// R-A3 — the lamp and the schedule sentence read the same field.
    var lampLit: Bool
    var scheduleText: String
    var nextRunAt: String?
    var nextRunText: String
    /// `preview.manual.engine` — what the one control would run on; `nil`
    /// until loaded, never guessed.
    var manualEngine: String?
    /// "Scheduled runs use …" only when it differs from the manual engine
    /// (ruling 4, shown rather than applied).
    var scheduledEngineNote: String?
    /// The scheduled engine's id, under the same condition as
    /// `scheduledEngineNote`. It is kept as an id so every line that names
    /// the engine can draw its mark (Z-P26).
    var scheduledEngine: String?
    var queuedCount: Int
    var consolidateEnabled: Bool
    /// `status.error`, `nil` when empty — the failure is news, an empty string is not.
    var cycleError: String?
    var cancelled: Bool
    var capped: Bool
    var indexWarning: String?
    var queueLoad: StudyListCard.LoadState
    /// Z-P3 — the newest `kind == "sleep"` commit.
    var lastCycle: SleepHistoryEntry?
    var inboxTotal: Int?
    var oldestWait: String?
    var topOriginLabel: String?
    /// The top row's origin id: T12 names `topOriginLabel` and draws this
    /// origin's mark.
    var topOrigin: String?

    static func resolve(
        status: SleepStatusResponse?,
        sse: SleepEventPayload?,
        queued: [EpisodeQueueItem],
        schedule: ScheduleConfig,
        enginePreview: SleepEnginePreviews?,
        history: [SleepHistoryEntry],
        storeStatus: StatusSnapshot?,
        queueLoad: StudyListCard.LoadState,
        justFinishedAt: Date?,
        intakeInFlight: Bool,
        now: Date = .now,
        locale: Locale = .current,
        timeZone: TimeZone = .current
    ) -> SleepPageModel {
        let debt = resolveSleepDebt(sse: sse, status: status)
        let mood = deriveSleepPageMood(status: status, debt: debt, justFinishedAt: justFinishedAt,
                                       intakeInFlight: intakeInFlight, now: now)
        let origins = resolveOriginCounts(sse: sse, status: status)
        let isRunning = status?.status == "running"
        let read = origins.readByOrigin.values.reduce(0, +)
        let total = origins.queueByOrigin.values.reduce(0, +)
        let rows = studyRows(queued: queued, queueByOrigin: origins.queueByOrigin,
                             readByOrigin: origins.readByOrigin, running: isRunning, now: now)
        let error = status?.error.flatMap { $0.isEmpty ? nil : $0 }
        let cancelled = status?.cancelled == true
        let nextSleepAt = storeStatus?.nextSleepAt
        return SleepPageModel(
            mood: mood,
            debt: debt,
            isRunning: isRunning,
            runningStage: isRunning ? activeStage(completed: status?.stage ?? 0) : nil,
            read: read,
            total: total,
            rows: rows,
            books: bookPileLayout(originVolumes(queued: queued, queueByOrigin: origins.queueByOrigin,
                                                readByOrigin: origins.readByOrigin, running: isRunning)),
            pips: stageStripState(stage: status?.stage ?? 0, isRunning: isRunning, cancelled: cancelled,
                                  error: error != nil, read: read, total: total),
            schedule: schedule,
            lampLit: schedule.enabled,
            scheduleText: scheduleSentence(schedule),
            nextRunAt: nextRunWhen(schedule, nextSleepAt: nextSleepAt, locale: locale, timeZone: timeZone),
            nextRunText: nextRunSentence(schedule, nextSleepAt: nextSleepAt, locale: locale, timeZone: timeZone),
            manualEngine: enginePreview?.manual.engine,
            scheduledEngineNote: scheduledEngineLine(preview: enginePreview),
            scheduledEngine: enginePreview.flatMap { $0.manual.engine != $0.scheduled.engine ? $0.scheduled.engine : nil },
            queuedCount: queued.count,
            consolidateEnabled: status != nil && !isRunning && !queued.isEmpty,
            cycleError: error,
            cancelled: cancelled,
            capped: (status?.episodesQueued ?? 0) > (status?.episodesTotal ?? 0),
            indexWarning: status?.indexWarning.flatMap { $0.isEmpty ? nil : $0 },
            queueLoad: queueLoad,
            lastCycle: lastCycleEntry(history),
            inboxTotal: storeStatus?.inbox.total,
            oldestWait: oldestQueuedHours(queued, now: now).map(agePhrase(hours:)),
            topOriginLabel: rows.first?.label,
            topOrigin: rows.first?.origin
        )
    }
}

/// The newest real consolidation in `history` (Z-P3). `/sleep/history` also
/// lists the G85 `(decay)` commit and inbox-resolution commits; neither is a
/// cycle, and "See what changed ›" must never open the person's own inbox
/// answer as if Sleep had written it.
func lastCycleEntry(_ history: [SleepHistoryEntry]) -> SleepHistoryEntry? {
    history.first { $0.kind == "sleep" }
}
```

`SleepView.swift`:
- Add, beside `pageError`:

```swift
    /// Track Z Z1 — the page, resolved once per body (§9). Every reader below
    /// takes its numbers from this value, so the room, the queue and the
    /// controls cannot disagree about which reading they show (H1, now
    /// structural). `now` is the body's own clock read — `studyRows` ages and
    /// the 6 s digest window already depended on it.
    private func resolvePage(now: Date = .now) -> SleepPageModel {
        SleepPageModel.resolve(
            status: sleepVM.status, sse: store.sleepEvent, queued: sleepVM.queuedEpisodes,
            schedule: sleepVM.schedule, enginePreview: sleepVM.enginePreview, history: sleepVM.history,
            storeStatus: store.status.value,
            queueLoad: StudyListCard.loadState(status: store.status.value,
                                               isLoading: store.status.isEmpty && store.status.isRefreshing,
                                               error: store.domainErrors[.status]),
            justFinishedAt: justFinishedAt, intakeInFlight: store.intakeInFlight, now: now)
    }
```

- `body`: `let page = resolvePage()` as its first line; `scrollContent(width:layout:)` gains a
  `page` parameter and passes it to `leftColumn(page)` / `deskCard(page)`.
- `deskCard(_ page: SleepPageModel)`: `mood` → `page.mood`, `debt` → `page.debt`, `books` →
  `page.books`, `BubbleContext` → `unprocessed: page.debt?.unprocessedCount ?? 0, topOriginLabel:
  page.rows.first?.label, topOriginCount: page.rows.first?.count ?? 0, stage: sleepVM.status?.stage
  ?? 0, read: page.read, total: page.total, hoursSinceLastCycle: page.debt?.hoursSinceLastCycle`
  (the bubble and its context are deleted in Task 3), `lampLit: page.lampLit`,
  `SleepHeroView(mood: page.mood, debt: page.debt, read: page.read, total: page.total, queuedCount:
  page.queuedCount, lastDurationMs: page.lastCycle?.durationMs)`, the strip reads `page.pips`, the
  banners' `if` conditions read `page.cancelled` / `page.capped` / `page.indexWarning` (their text
  keeps reading `sleepVM.status` for the cap numbers — Details content, Task 4).
- `StudyListCard(rows: page.rows, episodes: sleepVM.queuedEpisodes, queueLoad: page.queueLoad,
  onSelectEntity: onSelectEntity)`.

`StudyListCard`: add `let queueLoad: LoadState` after `episodes`; `content`'s `switch` reads
`queueLoad`; delete the now-unused `status`/`isLoading` computed properties only if nothing else in
the file reads them (`footer` reads `status?.nextSleepAt` until Task 3 moves it — keep `status`).

`SleepHeroView`: replace `lastMeasuredCycleMs` with `let lastDurationMs: Int?` and pass it to
`heroTiles(...lastDurationMs:)`; the tile's docstring (`:192-202`) says "the newest `kind ==
"sleep"` commit (Z-P3)".

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures.
  `grep -n "studyListRows\|liveOriginCounts" app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift`
  prints nothing.
- [ ] **Step 4: Commit** — `refactor(sleep v4): SleepPageModel — the page resolved once per body (G125 v4, §9)`.

---

### Task 3 (Z2): The sentence, the control row and the whisper line — the bubble retires

The worm speaks in one fixed slot directly under the room (R-Z5): a 30 pt serif lead over a 22 pt
italic tail with its height reserved, so nothing below reflows. The hero's count row becomes the
lead; the one Consolidate/Cancel control becomes `SleepControlRow`; the schedule row and next-run
footer become the whisper line (Z-P4). The meter, tiles, strip and banners stay where they are
until Task 4.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomSentence.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepStages.swift:11-54` — `SleepStage.progressive` ("Reading" … "Filing"), set on the five entries
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepPageModel.swift` — `roomContext(locale:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepHero.swift` — delete `countRow`, `qualifierChip`, `controlRow`, `consolidateButton`, `cancelButton`, `isIdleAndEmpty` from `SleepHeroView` (`:258-298`, `:381-467`); add `SleepControlRow`, `controlCaption`, `EngineMark` (the two buttons move into `SleepControlRow` verbatim apart from the `disabled`/`help` inputs)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — `deskCard`: the bubble goes; sentence, control row and whisper line go under the room; the card centres
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepBubble.swift:52-122` — delete `SpeechBubbleView` (`BubbleContext` and `sleepBubbleText` stay: shared, R-A4 amended)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift` — delete `scheduleRow` (`:306-323`) and `footer` (`:325-340`) and the `Divider` above them (`:132`); update the type docstring
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — `cancelCaption`, `nextRunUnknownReason`
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/RoomSentenceTests.swift`

**Interfaces:**
- Produces: `SentenceTone`, `DetailsSection` (+ `anchorID`), `SentenceAction`, `SentenceMark`, `SentenceLine` (+ `mark`, `spoken`, `maxLead`, `maxTail`), `SentenceRun`, `sentenceRuns(_:)`, `tailLink(_:)`, `sentenceClause(_:limit:)`, `sentenceCase(_:)`, `RoomContext`, `roomSentence(_:)`, `whisperLine(scheduleText:nextRunText:lampLit:)`, `RoomSentenceView(line:canPerform:perform:)`; `SleepControlRow`, `controlCaption(isRunning:manualEngine:)`, `EngineMark`; `SleepStage.progressive`; `SleepPageModel.roomContext(locale:)`.
- Consumes: `heroCount`, `heroQualifier` (parity by construction), `SleepStages.all`, `UsageFormat.count(_:locale:)`, `StudyListCard.LoadState`, `Copy.runsOn(engine:)`, `Copy.cancelSleepExplainer`.

- [ ] **Step 1: Failing tests.** `Tests/CicadaAppTests/RoomSentenceTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z, Z2 — the sentence slot (R-Z5, R-Z13, design §5). Every row of the
/// lead table (L1–L11, plus this plan's L8b) and the tail table (T1–T6,
/// T8–T12, T14; T7 lands with the completion edge in Task 8, T13 with feeding)
/// is a case, then the rules that cut across all of them.
final class RoomSentenceTests: XCTestCase {

    private let en = Locale(identifier: "en_US")

    private func debt(_ unprocessed: Int, hasRunBefore: Bool = true, hours: Double? = 2,
                      rested: Int? = 60) -> SleepDebtView {
        SleepDebtView(restedPct: rested, volumePct: 0, agePct: 0, unprocessedCount: unprocessed,
                      hasRunBefore: hasRunBefore, hoursSinceLastCycle: hours)
    }

    private func ctx(_ mood: BookwormState, debt: SleepDebtView? = nil,
                     _ edit: (inout RoomContext) -> Void = { _ in }) -> RoomContext {
        var c = RoomContext(mood: mood, debt: debt, scheduleMode: "daily", locale: en)
        edit(&c)
        return c
    }

    // MARK: The lead (§5, first matching row wins)

    func test_L1_theQueueCouldNotLoad() {
        let line = roomSentence(ctx(.happy) { $0.queueLoad = .failed("Couldn't load status") })
        XCTAssertEqual(line.lead, "I can't see the queue.")
        XCTAssertEqual(line.tone, .danger)
        XCTAssertEqual(line.tail, "Couldn't load status")
        XCTAssertEqual(line.action, .retry, "T1")
    }

    func test_L2_theQueueIsLoading() {
        let line = roomSentence(ctx(.happy) { $0.queueLoad = .loading })
        XCTAssertEqual(line.lead, "Checking what's waiting…")
        XCTAssertNil(line.tail)
    }

    func test_L3_L4_readingNamesItsTwoNumbersOnlyWhenItHasThem() {
        let counted = roomSentence(ctx(.sleeping(stage: 1)) { $0.activeStage = 1; $0.read = 138; $0.total = 203 })
        XCTAssertEqual(counted.lead, "Reading 138 of 203.")
        XCTAssertEqual(counted.numeral, "138 of 203")
        XCTAssertEqual(counted.tail, SleepStages.all[0].detail, "T2 — the stage's own detail (P16)")
        XCTAssertEqual(roomSentence(ctx(.sleeping(stage: 1)) { $0.activeStage = 1 }).lead, "Reading…")
    }

    func test_L5_laterStagesSayWhatTheyAreDoing() {
        for (stage, lead) in [(2, "Sorting…"), (3, "Deciding…"), (4, "Noticing…"), (5, "Filing…")] {
            let line = roomSentence(ctx(.sleeping(stage: stage)) { $0.activeStage = stage })
            XCTAssertEqual(line.lead, lead)
            XCTAssertEqual(line.tail, SleepStages.all[stage - 1].detail)
        }
        XCTAssertEqual(SleepStages.all.map(\.progressive), ["Reading", "Sorting", "Deciding", "Noticing", "Filing"])
    }

    func test_L6_T3_aFailureLeadsWithItsFirstClause() {
        let line = roomSentence(ctx(.error) { $0.cycleError = "claude exited 1: rate limited\nTraceback (most recent call last)" })
        XCTAssertEqual(line.lead, "The last cycle failed.")
        XCTAssertEqual(line.tone, .danger)
        XCTAssertEqual(line.tail, "claude exited 1: rate limited")
        XCTAssertEqual(line.tailTone, .danger)
        XCTAssertEqual(line.action, .openDetails(.lastCycle))
    }

    func test_L7_digesting() {
        XCTAssertEqual(roomSentence(ctx(.digesting)).lead, "Filed.")
    }

    func test_L8_theCountIsTheNumeral_andOverdueIsAWord() {
        let reading = roomSentence(ctx(.reading, debt: debt(47)))
        XCTAssertEqual(reading.lead, "47 to read.")
        XCTAssertEqual(reading.numeral, "47")
        XCTAssertNil(reading.qualifier)
        let hungry = roomSentence(ctx(.hungry, debt: debt(1234, rested: 10)))
        XCTAssertEqual(hungry.lead, "1,234 to read — overdue.")
        XCTAssertEqual(hungry.numeral, "1,234")
        XCTAssertEqual(hungry.qualifier, "overdue")
        XCTAssertEqual(hungry.tone, .warning)
        // P9: a bank that has never consolidated is not "overdue" — T8 says why.
        let firstNight = roomSentence(ctx(.hungry, debt: debt(12, hasRunBefore: false, rested: 10)))
        XCTAssertEqual(firstNight.lead, "12 to read.")
        XCTAssertEqual(firstNight.tail, "My first night — nothing's been filed yet.")
    }

    /// Z-P6 — the design's table has no row for `.reading` with nothing
    /// counted yet, which is exactly an import landing (`intakeInFlight`).
    func test_L8b_somethingJustArrived() {
        XCTAssertEqual(roomSentence(ctx(.reading, debt: debt(0))).lead, "Something new just arrived.")
    }

    func test_L9_L10_L11() {
        XCTAssertEqual(roomSentence(ctx(.hungry, debt: debt(0, hours: 80))).lead, "Nothing new to read.")
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0))).lead, "All caught up.")
        XCTAssertEqual(roomSentence(ctx(.awake)).lead, "Listening.")
    }

    // MARK: The tail (§5, first matching row wins — news outranks everything)

    func test_T4_T5_T6_theNewsTails() {
        let cancelled = roomSentence(ctx(.happy, debt: debt(0)) { $0.cancelled = true })
        XCTAssertEqual(cancelled.tail, "Stopped early — nothing was lost.")
        XCTAssertEqual(cancelled.action, .openDetails(.lastCycle))
        let capped = roomSentence(ctx(.reading, debt: debt(40)) { $0.capped = true })
        XCTAssertEqual(capped.tail, "The rest wait for the next cycle.")
        let warned = roomSentence(ctx(.happy, debt: debt(0)) { $0.indexWarning = "index rebuild failed" })
        XCTAssertEqual(warned.tail, "Finished with a warning — it's in Details.")
        XCTAssertEqual(warned.tailTone, .warning)
    }

    func test_newsOutranksTheStateTails() {
        let failedAndCancelled = roomSentence(ctx(.error) { $0.cycleError = "boom"; $0.cancelled = true })
        XCTAssertEqual(failedAndCancelled.tail, "boom", "T3 before T4")
        let runningAndCancelled = roomSentence(ctx(.sleeping(stage: 2)) { $0.activeStage = 2; $0.cancelled = true })
        XCTAssertEqual(runningAndCancelled.tail, SleepStages.all[1].detail, "T2 before T4")
        let cancelledFirstNight = roomSentence(ctx(.reading, debt: debt(3, hasRunBefore: false)) { $0.cancelled = true })
        XCTAssertEqual(cancelledFirstNight.tail, "Stopped early — nothing was lost.", "T4 before T8")
    }

    func test_T8_T9_theFirstNight() {
        XCTAssertEqual(roomSentence(ctx(.reading, debt: debt(3, hasRunBefore: false))).tail,
                       "My first night — nothing's been filed yet.")
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0, hasRunBefore: false))).tail,
                       "Nothing's been filed in this memory yet.")
        XCTAssertNil(roomSentence(ctx(.happy, debt: nil)).tail, "an unloaded debt is never reported as a first night")
    }

    func test_T10_theDaysOnlyWhenTheGapIsLong() {
        XCTAssertEqual(roomSentence(ctx(.hungry, debt: debt(9, hours: 72, rested: 10))).tail, "It's been 3 days.")
        XCTAssertNil(roomSentence(ctx(.hungry, debt: debt(9, hours: 47, rested: 10))).tail, "under two days, no day count")
    }

    func test_T11_theLampIsOffOnlyWhenSomethingWaits() {
        let off = roomSentence(ctx(.reading, debt: debt(5)) { $0.scheduleMode = "manual" })
        XCTAssertEqual(off.tail, "The lamp is off — I read when you ask.")
        XCTAssertEqual(off.action, .openLamp)
        XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0)) { $0.scheduleMode = "manual" }).tail)
    }

    func test_T12_theBigPile_orNothingWhenItWouldNotFit() {
        let line = roomSentence(ctx(.reading, debt: debt(5)) { $0.topOriginLabel = "Claude Code"; $0.topOrigin = "claude-code" })
        XCTAssertEqual(line.tail, "The Claude Code pile is the big one.")
        XCTAssertEqual(line.mark, .origin("claude-code"), "a named source wears its mark (Z-P26)")
        let long = String(repeating: "x", count: 70)
        XCTAssertNil(roomSentence(ctx(.reading, debt: debt(5)) { $0.topOriginLabel = long }).tail)
    }

    func test_T14_nothingToAdd() {
        XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0))).tail)
        XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0))).mark, "no service named, no mark")
    }

    // MARK: The rules across every row (R-Z13)

    private var matrix: [RoomContext] {
        var out: [RoomContext] = []
        let moods: [BookwormState] = [.awake, .happy, .reading, .hungry, .digesting, .error,
                                      .sleeping(stage: 1), .sleeping(stage: 3), .sleeping(stage: 5)]
        for mood in moods {
            for count in [0, 1, 47, 1_234_567] {
                for firstRun in [false, true] {
                    out.append(ctx(mood, debt: debt(count, hasRunBefore: !firstRun, hours: 96, rested: 5)) {
                        $0.activeStage = mood.stageNumber == 0 ? nil : mood.stageNumber
                        $0.read = count / 2; $0.total = count
                        $0.cycleError = mood == .error ? String(repeating: "error text ", count: 20) : nil
                        $0.scheduleMode = firstRun ? "manual" : "daily"
                        $0.topOriginLabel = "Safari bookmarks"
                    })
                }
            }
        }
        return out
    }

    func test_everyLineFitsItsBudget_andSaysNothingItMayNot() {
        let banned = ["est", "cluster", "insight"]
        for c in matrix {
            let line = roomSentence(c)
            XCTAssertFalse(line.lead.isEmpty, "\(c.mood.caseName) has no lead")
            XCTAssertLessThanOrEqual(line.lead.count, SentenceLine.maxLead, line.lead)
            XCTAssertLessThanOrEqual(line.tail?.count ?? 0, SentenceLine.maxTail, line.tail ?? "")
            for text in [line.lead, line.tail ?? ""] {
                XCTAssertFalse(text.contains("!"), text)
                XCTAssertFalse(text.contains("%"), text)
                XCTAssertFalse(text.contains("~"), text)
                let words = text.lowercased().split { !$0.isLetter }.map(String.init)
                for word in banned { XCTAssertFalse(words.contains(word), "'\(word)' in \(text)") }
            }
        }
    }

    /// The numeral is `heroCount`, formatted — the hero and the sentence can
    /// never disagree because the sentence asks the same function.
    func test_theNumeralIsHeroCount() {
        for mood in [BookwormState.reading, .hungry] {
            for count in [1, 47, 1234] {
                let d = debt(count, rested: 10)
                XCTAssertEqual(roomSentence(ctx(mood, debt: d)).numeral,
                               heroCount(mood, debt: d).map { UsageFormat.count($0, locale: en) })
            }
        }
    }

    func test_isDeterministic_R8() {
        for c in matrix { XCTAssertEqual(roomSentence(c), roomSentence(c)) }
    }

    // MARK: Rendering helpers

    func test_sentenceRuns_splitTheLeadIntoWhatTheViewDrawsDifferently() {
        let line = SentenceLine(lead: "47 to read — overdue.", numeral: "47", qualifier: "overdue", tone: .warning)
        XCTAssertEqual(sentenceRuns(line), [SentenceRun(text: "47", kind: .numeral),
                                            SentenceRun(text: " to read — ", kind: .plain),
                                            SentenceRun(text: "overdue", kind: .qualifier),
                                            SentenceRun(text: ".", kind: .plain)])
        XCTAssertEqual(sentenceRuns(line).map(\.text).joined(), line.lead)
        XCTAssertEqual(sentenceRuns(SentenceLine(lead: "Filed.")), [SentenceRun(text: "Filed.", kind: .plain)])
    }

    /// Z-P8 — the link is the words after the tail's last " — ", else the whole tail.
    func test_tailLink_isTheLastWords() {
        XCTAssertEqual(tailLink("Stopped early — nothing was lost."), "nothing was lost.")
        XCTAssertEqual(tailLink("See what changed ›"), "See what changed ›")
    }

    func test_sentenceClause_isOneLineCutOnAWord() {
        XCTAssertEqual(sentenceClause("a\nb"), "a")
        XCTAssertNil(sentenceClause("  \n"))
        let long = sentenceClause(String(repeating: "word ", count: 40))!
        XCTAssertLessThanOrEqual(long.count, SentenceLine.maxTail)
        XCTAssertTrue(long.hasSuffix("word…"), long)
    }

    func test_sentenceCase_capitalisesAndCloses() {
        XCTAssertEqual(sentenceCase("scheduled cycle — using the configured API model"),
                       "Scheduled cycle — using the configured API model.")
        XCTAssertEqual(sentenceCase("Already a sentence."), "Already a sentence.")
        XCTAssertNil(sentenceCase(" "))
    }

    // MARK: The control row and the whisper line

    func test_whisperLine_isTheLampsTwinInWords() {
        XCTAssertEqual(whisperLine(scheduleText: "Every day at 03:00", nextRunText: "Next run Sep 24, 3:00 AM", lampLit: true),
                       "Every day at 03:00 · Next run Sep 24, 3:00 AM")
        XCTAssertEqual(whisperLine(scheduleText: Copy.nextRunManual, nextRunText: Copy.nextRunManual, lampLit: false),
                       "Manual only — the lamp is off")
    }

    /// The caption names what THIS click would run on (ruling 4 at the moment
    /// of choice), or what Cancel does while running; nothing when unloaded.
    func test_controlCaption() {
        XCTAssertEqual(controlCaption(isRunning: false, manualEngine: "claude-cli"), Copy.runsOn(engine: "claude-cli"))
        XCTAssertNil(controlCaption(isRunning: false, manualEngine: nil))
        XCTAssertEqual(controlCaption(isRunning: true, manualEngine: "claude-cli"), Copy.cancelCaption)
    }

    /// R-Z5 — the bubble is retired from the page.
    func test_theSpeechBubbleIsGone() throws {
        for file in try SleepNumbersLintTests.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("SpeechBubbleView"), file.lastPathComponent)
        }
    }
}
```

(`SleepNumbersLintTests.sleepSources()` is `static`, internal — reused, never a second enumerator.)

- [ ] **Step 2: Implement.**

`Views/Sleep/SleepStages.swift` — `SleepStage` gains, after `shortLabel`:

```swift
    /// The sentence's word for this stage while it runs ("Sorting…", Track Z
    /// L5) — stored beside `shortLabel` so the strip and the sentence read one
    /// array (P16) instead of a second map that could drift.
    let progressive: String
```

and the five entries gain `progressive: "Reading"`, `"Sorting"`, `"Deciding"`, `"Noticing"`,
`"Filing"` (after `shortLabel:`).

`Views/Sleep/RoomSentence.swift`:

```swift
import SwiftUI

// MARK: - The sentence slot's value (Track Z R-Z5, R-Z13, design §5)

/// How a line is tinted. With a `qualifier`, only that word takes the tone;
/// without one, the whole lead does. Colour is never the only carrier (§11):
/// the qualifier IS a word ("overdue") and every danger lead says "failed" or
/// "can't" in words.
enum SentenceTone: Hashable { case plain, warning, danger }

/// Details' four sections, and the scroll anchor each one carries (Task 4).
enum DetailsSection: String, CaseIterable, Hashable {
    case lastCycle, waiting, readout, pastNights
    var anchorID: String { "details.\(rawValue)" }
}

/// Where a tail link goes. Every case is a destination that exists on the page
/// or one tab away — Z-P5: a link a commit cannot follow yet renders as words.
enum SentenceAction: Hashable {
    case retry
    case openInbox
    case openDetails(DetailsSection)
    case openLamp
    case whatChanged
}

/// A service a line names. The round-3 rule is that a service named in the UI
/// shows its real mark (Z-P26). The slot draws this mark beside the tail:
/// `.origin` through `OriginMark` and `.engine` through `EngineMark`. It is a
/// value on the line so a test can read it; the view never guesses one from
/// the words.
enum SentenceMark: Hashable {
    case origin(String)
    case engine(String)
}

/// One line in the slot — the status sentence, or one rung of the worm's
/// answers (Task 6).
///
/// `lead` is the WHOLE visible lead (Z-P7): `numeral` and `qualifier` name
/// substrings of it that the view draws in SF rounded digits and in the
/// tone's colour. So the ≤ 40 rule, the "!" ban and VoiceOver all read one
/// string, and a number can sit mid-sentence ("Reading 138 of 203.").
/// `Hashable` so the slot can key its cross-fade on the line shown (Task 6).
struct SentenceLine: Hashable {
    var lead: String
    var numeral: String? = nil
    var qualifier: String? = nil
    var tone: SentenceTone = .plain
    var tail: String? = nil
    var tailTone: SentenceTone = .plain
    var action: SentenceAction? = nil
    /// The service the tail names, if any, drawn beside it as its mark.
    var mark: SentenceMark? = nil

    /// R-Z13's two budgets: one line of 30 pt serif, two of 22 pt italic.
    static let maxLead = 40
    static let maxTail = 80

    /// What VoiceOver reads — the visible words, in order (§5).
    var spoken: String { [lead, tail].compactMap { $0 }.joined(separator: " ") }
}

enum SentenceRunKind: Equatable { case plain, numeral, qualifier }

struct SentenceRun: Equatable {
    let text: String
    let kind: SentenceRunKind
}

/// The lead cut into the runs the view draws differently — the numeral in SF
/// rounded digits (never serif digits), the qualifier in the tone's colour,
/// everything else in the serif. The runs always concatenate back to `lead`.
func sentenceRuns(_ line: SentenceLine) -> [SentenceRun] {
    var runs = [SentenceRun(text: line.lead, kind: .plain)]
    func carve(_ needle: String?, as kind: SentenceRunKind) {
        guard let needle, !needle.isEmpty else { return }
        var out: [SentenceRun] = []
        var carved = false
        for run in runs {
            guard !carved, run.kind == .plain, let range = run.text.range(of: needle) else {
                out.append(run)
                continue
            }
            let before = String(run.text[..<range.lowerBound])
            let after = String(run.text[range.upperBound...])
            if !before.isEmpty { out.append(SentenceRun(text: before, kind: .plain)) }
            out.append(SentenceRun(text: needle, kind: kind))
            if !after.isEmpty { out.append(SentenceRun(text: after, kind: .plain)) }
            carved = true
        }
        runs = out
    }
    carve(line.numeral, as: .numeral)
    carve(line.qualifier, as: .qualifier)
    return runs
}

/// Z-P8 — "a tail action renders its last words as a link", defined: the text
/// after the tail's last " — ", else the whole tail.
func tailLink(_ tail: String) -> String {
    guard let range = tail.range(of: " — ", options: .backwards) else { return tail }
    return String(tail[range.upperBound...])
}

/// The first line of `text`, cut on a word at `limit` with "…" — a tail is a
/// line, not a log. `nil` when there is nothing to say.
func sentenceClause(_ text: String?, limit: Int = SentenceLine.maxTail) -> String? {
    guard let first = text?.split(whereSeparator: \.isNewline).first
            .map({ String($0).trimmingCharacters(in: .whitespaces) }),
          !first.isEmpty else { return nil }
    guard first.count > limit else { return first }
    let cut = first.prefix(limit - 1)
    let onWord = cut.lastIndex(of: " ").map { cut[..<$0] } ?? cut
    return onWord.trimmingCharacters(in: CharacterSet(charactersIn: " ,;:—-")) + "…"
}

/// A backend sentence shown as the page's own (Z-P26): first letter up, a
/// closing stop if it has none — never reworded.
func sentenceCase(_ text: String?) -> String? {
    guard let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines),
          let first = trimmed.first else { return nil }
    let cased = first.uppercased() + trimmed.dropFirst()
    return ".?…".contains(cased.last!) ? cased : cased + "."
}

// MARK: - What the sentence reads

/// Every fact the sentence and the answers read, resolved by the page
/// (`SleepPageModel.roomContext`). Nothing here reaches for a clock (R8).
struct RoomContext: Equatable {
    var mood: BookwormState = .awake
    var debt: SleepDebtView? = nil
    var queueLoad: StudyListCard.LoadState = .loaded(count: 0)
    /// 1…5 while running (R-Z14).
    var activeStage: Int? = nil
    var read: Int = 0
    var total: Int = 0
    var cycleError: String? = nil
    var cancelled: Bool = false
    var capped: Bool = false
    var indexWarning: String? = nil
    var scheduleMode: String = "manual"
    var topOriginLabel: String? = nil
    /// The top row's origin id, for T12's mark.
    var topOrigin: String? = nil
    var locale: Locale = .autoupdatingCurrent
}

/// The status sentence (design §5): the first matching lead row, then the
/// first matching tail row, so news always outranks state.
func roomSentence(_ ctx: RoomContext) -> SentenceLine {
    var line = sentenceLead(ctx)
    if let tail = sentenceTail(ctx) {
        line.tail = tail.text
        line.tailTone = tail.tone
        line.action = tail.action
        line.mark = tail.mark
    }
    return line
}

private struct SentenceTail {
    let text: String
    var tone: SentenceTone = .plain
    var action: SentenceAction? = nil
    var mark: SentenceMark? = nil
}

private func stage(_ ctx: RoomContext) -> SleepStage {
    SleepStages.all[max(1, min(SleepStages.all.count, ctx.activeStage ?? 1)) - 1]
}

private func sentenceLead(_ ctx: RoomContext) -> SentenceLine {
    switch ctx.queueLoad {
    case .failed: return SentenceLine(lead: "I can't see the queue.", tone: .danger)          // L1
    case .loading: return SentenceLine(lead: "Checking what's waiting…")                        // L2
    case .loaded: break
    }
    let count = { (n: Int) in UsageFormat.count(n, locale: ctx.locale) }
    switch ctx.mood {
    case .sleeping:
        let running = stage(ctx)
        guard running.number == 1 else { return SentenceLine(lead: "\(running.progressive)…") }  // L5
        guard ctx.total > 0 else { return SentenceLine(lead: "Reading…") }                       // L4
        let numeral = "\(count(ctx.read)) of \(count(ctx.total))"
        return SentenceLine(lead: "Reading \(numeral).", numeral: numeral)                      // L3
    case .error:
        return SentenceLine(lead: "The last cycle failed.", tone: .danger)                      // L6
    case .digesting:
        return SentenceLine(lead: "Filed.")                                                     // L7
    case .reading, .hungry, .curious:
        if let n = heroCount(ctx.mood, debt: ctx.debt), n > 0 {                                  // L8
            let numeral = count(n)
            // `heroQualifier` is asked, not re-derived: "first run" (P9) outranks
            // "overdue", and the tail says it in words (T8).
            guard heroQualifier(ctx.mood, debt: ctx.debt) == "overdue" else {
                return SentenceLine(lead: "\(numeral) to read.", numeral: numeral)
            }
            return SentenceLine(lead: "\(numeral) to read — overdue.", numeral: numeral,
                                qualifier: "overdue", tone: .warning)
        }
        if case .hungry = ctx.mood { return SentenceLine(lead: "Nothing new to read.") }        // L9
        return SentenceLine(lead: "Something new just arrived.")                                // L8b, Z-P6
    case .happy:
        return SentenceLine(lead: "All caught up.")                                             // L10
    case .awake:
        return SentenceLine(lead: "Listening.")                                                 // L11
    }
}

private func sentenceTail(_ ctx: RoomContext) -> SentenceTail? {
    if case .failed(let message) = ctx.queueLoad {                                               // T1
        return SentenceTail(text: sentenceClause(message) ?? "Try again.", tone: .danger, action: .retry)
    }
    if case .sleeping = ctx.mood { return SentenceTail(text: stage(ctx).detail) }                // T2 (P16)
    if case .error = ctx.mood, let clause = sentenceClause(ctx.cycleError) {                     // T3
        return SentenceTail(text: clause, tone: .danger, action: .openDetails(.lastCycle))
    }
    if ctx.cancelled {                                                                           // T4
        return SentenceTail(text: "Stopped early — nothing was lost.", action: .openDetails(.lastCycle))
    }
    if ctx.capped {                                                                              // T5
        return SentenceTail(text: "The rest wait for the next cycle.", action: .openDetails(.lastCycle))
    }
    if let warning = ctx.indexWarning, !warning.isEmpty {                                        // T6
        return SentenceTail(text: "Finished with a warning — it's in Details.", tone: .warning,
                            action: .openDetails(.lastCycle))
    }
    // T7 ("See what changed ›") lands with the completion edge (Task 8).
    let count = ctx.debt?.unprocessedCount ?? 0
    if ctx.debt?.hasRunBefore == false {                                                         // T8 / T9
        return SentenceTail(text: count > 0 ? "My first night — nothing's been filed yet."
                                            : "Nothing's been filed in this memory yet.")
    }
    if case .hungry = ctx.mood, let hours = ctx.debt?.hoursSinceLastCycle, hours >= 48 {         // T10
        return SentenceTail(text: "It's been \(Int(hours / 24)) days.")
    }
    if count > 0, ctx.scheduleMode == "manual" {                                                 // T11
        return SentenceTail(text: "The lamp is off — I read when you ask.", action: .openLamp)
    }
    if case .reading = ctx.mood, let label = ctx.topOriginLabel {                                // T12
        let text = "The \(label) pile is the big one."
        if text.count <= SentenceLine.maxTail {
            return SentenceTail(text: text, mark: ctx.topOrigin.map { SentenceMark.origin($0) })
        }
    }
    return nil                                                                                   // T14
}

/// The lamp's twin in words (§7.2): the schedule, then when the next run is —
/// or that the lamp is off.
func whisperLine(scheduleText: String, nextRunText: String, lampLit: Bool) -> String {
    lampLit ? "\(scheduleText) · \(nextRunText)" : "\(scheduleText) — the lamp is off"
}

// MARK: - The slot

/// The one place the worm speaks (R-Z5), directly under the room. Its height
/// is reserved — one lead line, two tail lines (`lineLimit(2, reservesSpace:)`)
/// — so a longer tail, an answer or no tail at all never reflows what sits
/// below it.
///
/// New York through `CicadaTheme.font(size:design: .serif)` until Meadow's
/// `displayFont` exists (design §5; Z10 swaps these two calls and nothing else).
struct RoomSentenceView: View {
    let line: SentenceLine
    /// Z-P5 — an action the page cannot perform yet renders as plain words.
    var canPerform: (SentenceAction) -> Bool = { _ in false }
    var perform: (SentenceAction) -> Void = { _ in }

    var body: some View {
        VStack(spacing: CicadaTheme.spacingXS) {
            leadText
                .font(CicadaTheme.font(size: 30, design: .serif))
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            tailView
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(line.spoken)
        .accessibilityActions {
            if let action = line.action, let tail = line.tail, canPerform(action) {
                Button(tailLink(tail)) { perform(action) }
            }
        }
    }

    private func color(_ tone: SentenceTone, plain: Color) -> Color {
        switch tone {
        case .plain: plain
        case .warning: CicadaTheme.warning
        case .danger: CicadaTheme.danger
        }
    }

    private var leadText: Text {
        let plainColor = line.qualifier == nil ? color(line.tone, plain: CicadaTheme.textPrimary) : CicadaTheme.textPrimary
        return sentenceRuns(line).reduce(Text(verbatim: "")) { text, run in
            switch run.kind {
            case .plain:
                return text + Text(verbatim: run.text).foregroundStyle(plainColor)
            case .numeral:
                return text + Text(verbatim: run.text)
                    .font(CicadaTheme.font(size: 30, weight: .medium, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(plainColor)
            case .qualifier:
                return text + Text(verbatim: run.text).foregroundStyle(color(line.tone, plain: CicadaTheme.textPrimary))
            }
        }
    }

    /// The tail, with the mark of the service it names beside it (Z-P26). The
    /// slot is one ignored-children element, so the mark adds nothing to what
    /// VoiceOver reads. The words already name the service.
    private var tailView: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
            if let mark = line.mark {
                SentenceMarkView(mark: mark)
                    .padding(.top, CicadaTheme.spacingXS)
            }
            tailText
        }
    }

    @ViewBuilder
    private var tailText: some View {
        let tail = line.tail ?? " "
        let tailFont = CicadaTheme.font(size: 22, design: .serif).italic()
        let tailColor = color(line.tailTone, plain: CicadaTheme.textSecondary)
        if let action = line.action, line.tail != nil, canPerform(action) {
            let link = tailLink(tail)
            let prefix = String(tail.dropLast(link.count))
            Button { perform(action) } label: {
                (Text(verbatim: prefix).foregroundStyle(tailColor)
                 + Text(verbatim: link).foregroundStyle(CicadaTheme.accent))
                    .font(tailFont)
                    .lineLimit(2, reservesSpace: true)
            }
            .buttonStyle(.cicadaPlain)
        } else {
            Text(verbatim: tail)
                .font(tailFont)
                .foregroundStyle(tailColor)
                .lineLimit(2, reservesSpace: true)
        }
    }
}

/// A `SentenceMark`, drawn. At 18 pt it sits beside the 22 pt italic tail
/// without out-weighing it.
private struct SentenceMarkView: View {
    let mark: SentenceMark

    var body: some View {
        switch mark {
        case .origin(let origin): OriginMark(origin: origin, size: 18)
        case .engine(let engine): EngineMark(engine: engine, size: 18)
        }
    }
}
```

`SleepPageModel.swift` — append:

```swift
extension SleepPageModel {
    /// The sentence's inputs (Track Z §5), from this one reading.
    func roomContext(locale: Locale = .autoupdatingCurrent) -> RoomContext {
        RoomContext(mood: mood, debt: debt, queueLoad: queueLoad, activeStage: runningStage,
                    read: read, total: total, cycleError: cycleError, cancelled: cancelled,
                    capped: capped, indexWarning: indexWarning, scheduleMode: schedule.mode,
                    topOriginLabel: topOriginLabel, topOrigin: topOrigin, locale: locale)
    }
}
```

`Theme/Copy.swift` — beside `cancelSleepExplainer`:

```swift
    /// The control row's one-line caption while a cycle runs (Track Z §4.1
    /// sketch B); the long explainer stays the button's tooltip.
    static let cancelCaption = "Stops at the next safe point — nothing is lost."
    /// The whisper line's hover reason when the next run is "—" (R-A14: a dash
    /// is a value with a reason).
    static let nextRunUnknownReason = "The backend hasn't said when the next run is."
```

`Views/Sleep/SleepHero.swift`:
- `SleepHeroView`'s body becomes the meter (when `heroMeter` returns one) and the tiles only; its
  docstring says so and names Task 4, which moves it into Details. `queuedCount` is deleted from it.
- Add:

```swift
// MARK: - The one control (R-A7, Track Z §4.2)

/// What the caption under the one control says: the engine THIS click would
/// run on (ruling 4, at the moment of choice), or what Cancel does while a
/// cycle runs; `nil` until the preview loads — a guessed engine is worse than
/// silence.
func controlCaption(isRunning: Bool, manualEngine: String?) -> String? {
    if isRunning { return Copy.cancelCaption }
    return manualEngine.map { Copy.runsOn(engine: $0) }
}

/// The page's ONE Consolidate/Cancel control (R-A7, G125 R10). While a cycle
/// runs the one control IS Cancel — the disabled "Consolidating…" twin pill is
/// gone (design §4.2). `FixWaveTests` pins `sleepVM.triggerManually()` to this
/// file.
struct SleepControlRow: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    let consolidateEnabled: Bool
    let queuedCount: Int
    let manualEngine: String?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if sleepVM.isRunning { cancelButton } else { consolidateButton }
            if let caption = controlCaption(isRunning: sleepVM.isRunning, manualEngine: manualEngine) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if !sleepVM.isRunning, let engine = manualEngine { EngineMark(engine: engine) }
                    Text(caption)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }
    // consolidateButton: moved from SleepHeroView verbatim, except
    //   `.disabled(!consolidateEnabled)`, the tertiary/elevated styling keyed on
    //   `!consolidateEnabled`, and `.help(queuedCount == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")`.
    // cancelButton: moved verbatim.
}

/// The engine a caption names, with its real mark (round-3 brief: "use logos
/// whenever possible"; Z-P26). `claude-cli` IS Claude Code, so it borrows that
/// origin's mark; an API key has no vendor to show.
struct EngineMark: View {
    let engine: String
    var size: CGFloat = 14

    var body: some View {
        switch engine {
        case "claude-cli":
            OriginMark(origin: "claude-code", size: size)
        case "ollama":
            LogoImage(name: "ollama", size: size)
        default:
            Image(systemName: "key")
                .font(CicadaTheme.font(size: size * 0.8, weight: .medium))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: size, height: size)
        }
    }
}
```

(Write the two moved buttons out in full in the file — the comment above is this plan's
instruction, not code to paste.)

`Views/Sleep/SleepView.swift` — `deskCard(_ page:)`:
- Delete `SpeechBubbleView(...)` and the `BubbleContext` construction.
- The card's `VStack` becomes `VStack(alignment: .center, spacing: CicadaTheme.spacingMD)`; the
  room `ZStack` is unchanged (its `.accessibilityLabel(sleepDebtBracketText(...))` stays until
  Task 6 moves the bracket line to the worm's value).
- Directly under the room:

```swift
            RoomSentenceView(line: roomSentence(page.roomContext()),
                             canPerform: { $0 == .retry },
                             perform: { action in
                                 if action == .retry { Task { await store.refresh([.status]) } }
                             })
            SleepControlRow(consolidateEnabled: page.consolidateEnabled,
                            queuedCount: page.queuedCount, manualEngine: page.manualEngine)
            whisperRow(page)
```

- then `SleepHeroView(...)` (meter + tiles), the strip, `moodDetailLine`, the engine line and the
  banners, unchanged, until Task 4.
- Add:

```swift
    /// The schedule in one quiet line (§7.2) — the lamp's text twin (R-A3),
    /// replacing the queue card's schedule row and footer (Z-P4). The
    /// "Scheduled runs use …" difference line stays under it until the lamp's
    /// popover (Task 7) shows the scheduled engine always.
    private func whisperRow(_ page: SleepPageModel) -> some View {
        VStack(spacing: 2) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "moon.zzz")
                    .font(CicadaTheme.font(size: 11))
                Text(whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText,
                                 lampLit: page.lampLit))
                    .font(CicadaTheme.captionFont)
                SettingsSectionLink(section: .sleep, label: Copy.changeEllipsis)
                    .font(CicadaTheme.captionFont)
            }
            .foregroundStyle(CicadaTheme.textTertiary)
            .help(page.nextRunText.hasSuffix("—") ? Copy.nextRunUnknownReason : "")
            if let note = page.scheduledEngineNote, let engine = page.scheduledEngine {
                HStack(spacing: CicadaTheme.spacingXS) {
                    EngineMark(engine: engine, size: 12)   // Z-P26 — a named engine wears its mark
                    Text(note)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }
```

`StudyListCard`: delete `scheduleRow`, `footer` and the `Divider` before them; `status` and the
`scheduledEngineLine` call leave with them (the free function `scheduledEngineLine` stays — the page
model and, later, the worm's answers read it). The docstring's last paragraph now says the card
states **what is waiting**; the schedule moved to the page's whisper line (Z-P4).

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures
  (`FixWaveTests` unchanged and green: `sleepVM.triggerManually()` is still in `SleepHero.swift`
  only, and `SleepView.swift` spells neither `Copy.consolidateNow` nor `triggerManually()`).
- [ ] **Step 4: Commit** — `feat(sleep v4): the worm speaks in one slot — sentence, one control, whisper line (G125 v4, R-Z5, R-Z13)`.

---

### Task 4 (Z3): One column, Details, and a strip that shows only with news

The default view becomes the room card (room · sentence · control · whisper · the strip when it has
news) and one **Details** row (R-Z6). Details holds Last cycle (the four banners, verbatim, full
contrast), What's waiting (the queue card), Readout (meter, tiles, engine line) and Past nights (the
history card) — closed by default, remembered per viewer, and **not built while closed**. The
two-column layout, the caught-up worm and Memory sources leave the page.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepDetails.swift` — `SleepDetails`, `LastCycleSection` (the four banners moved from `SleepView.swift:769-892`, unchanged), `lastCycleSectionIsVisible`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ActivitySeries.swift` — `ActivityWindow`, `sparklinePoints`, `weekDots`, `sparklinePath` moved verbatim from `Views/Sleep/MemorySourcesCard.swift:1-62, 137-161`
- Delete: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/MemorySourcesCard.swift` (with `MemorySourceRow`, `memorySourceRows`, its two private views — used by the Sleep page only)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — `SleepLayout` becomes one constant; the body is one column in a `ScrollViewReader`; `roomCard`, `detailsDisclosure`, `openDetails`, `pendingScroll`; delete `sleepLayout(width:)`, `scrollContent`, `leftColumn`, `rightColumn`, `memoryRows`, `moodDetailLine`, `engineLine`, the four banner functions; the header stops rendering the subtitle, which becomes the `accessibilityHint` of the page title (the "Sleep Cycle" `Text`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepHero.swift` — `SleepHeroView` → `SleepReadoutView` (meter, tiles, the no-baseline line and the engine line with `EngineMark`, in a "READOUT" card)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepStages.swift` — add `stageStripIsVisible`; delete `stageStripShowsCaughtUpWorm` (`:147-155`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepStageStrip.swift` — delete `showsCaughtUpWorm`, `wormPointSize`, `caughtUpWorm` (`:30-31`, `:49-50`, `:76-78`, `:192-209`); docstring
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift:125` — "IN THE QUEUE" → "WHAT'S WAITING"
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/ConsolidationHistoryCard.swift:184` — "RECENT CONSOLIDATIONS" → "PAST NIGHTS"
- Modify: comments only — `Sync/SnapshotCache.swift:15` (names `memorySourceRows`), `Views/Sources/SourceCardMetrics.swift:20-21` and `Views/Sources/SourceCardGrid.swift:62,360` (name `MemorySourcesCard`) → point at `ActivitySeries.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — `sleepDetails = "Details"`
- Test (rewrite, design §14 Z3): `SleepLayoutTests.swift:1-78` — the two-column cases go (the layout they tested is retired, R-A1 amended); `SleepLivenessTests` (`:80-214`) unchanged
- Test (move): `MemorySourcesTests.swift` → `ActivitySeriesTests.swift` — the `sparklinePoints` / `weekDots` / `sparklinePath` cases verbatim (`:22-69`, `:136-151`); the `memorySourceRows` cases (`:71-134`) are deleted with the function
- Test (edit): `SleepStageStripTests.swift:175-188` — the caught-up-worm test is deleted with the worm (R-A8 amended: the room's worm is already `.happy`)
- Test (new): `SleepDetailsTests.swift`

**Interfaces:**
- Produces: `SleepLayout.contentWidth`; `SleepDetails(page:liveness:pageError:status:episodes:history:details:expanded:onToggleHistory:onSelectEntity:)` + `SleepDetails.openKey` / `.defaultOpen`; `lastCycleSectionIsVisible(pageError:cancelled:capped:indexWarning:)`; `stageStripIsVisible(isRunning:cancelled:failed:)`; `SleepReadoutView`.
- Consumes: Task 3's `RoomSentenceView` (`.openDetails` becomes performable), `DetailsSection.anchorID`.

- [ ] **Step 1: Failing tests.** `SleepLayoutTests.swift`, first class, replaced by:

```swift
/// Track Z §4.1 (R-A1 amended) — the page is ONE 760 pt column at every width.
/// The room is the widest thing in it, so the column's one real constraint is
/// that the room fits at every zoom step (Z-P23).
final class SleepLayoutTests: XCTestCase {

    func test_theColumnIsSevenSixty() {
        XCTAssertEqual(SleepLayout.contentWidth, 760)
    }

    /// Room + the card's padding (`spacingLG`) + the page's (`spacingXL`), both
    /// scaled, must fit the unscaled column at every View-menu step. At 1.4×
    /// that is 630 + 44.8 + 67.2 = 742 pt.
    func test_theRoomFitsTheColumnAtEveryZoomStep() {
        for step in 8...14 {
            let scale = Double(step) / 10
            let room = deskSceneLayout(pointSize: SleepView.wormPointSize, uiScale: scale).size.width
            let padding = 2 * 16 * CGFloat(scale) + 2 * 24 * CGFloat(scale)
            XCTAssertLessThanOrEqual(room + padding, SleepLayout.contentWidth, "uiScale \(scale)")
        }
    }
}
```

`Tests/CicadaAppTests/SleepDetailsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z, Z3 — the page's second surface (R-Z6, spec decision 16) and the
/// strip's news-only rule.
final class SleepDetailsTests: XCTestCase {

    /// Decision 16: closed by default, remembered per viewer.
    func test_detailsIsClosedByDefaultAndRememberedUnderOneKey() {
        XCTAssertEqual(SleepDetails.openKey, "cicada.sleep.detailsOpen")
        XCTAssertFalse(SleepDetails.defaultOpen)
    }

    /// Last cycle appears only when there is something to say about it.
    func test_lastCycleShowsOnlyWithNews() {
        XCTAssertFalse(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: "boom", cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: true, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: true, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: "w"))
    }

    /// R-Z6 — the strip is the running instrument and the frozen record of a
    /// cancel or failure (P15); an idle, successful page has nothing for it to say.
    func test_theStripShowsOnlyWhileRunningOrFrozen() {
        XCTAssertFalse(stageStripIsVisible(isRunning: false, cancelled: false, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: true, cancelled: false, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: false, cancelled: true, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: false, cancelled: false, failed: true))
    }

    func test_everySectionHasItsOwnAnchor() {
        let ids = DetailsSection.allCases.map(\.anchorID)
        XCTAssertEqual(ids, ["details.lastCycle", "details.waiting", "details.readout", "details.pastNights"])
        XCTAssertEqual(Set(ids).count, ids.count)
    }

    /// What left the page stays gone: the second column, the duplicate worm
    /// at the strip's end, and the Memory sources card (Sources v2 draws the
    /// same projection).
    func test_whatLeftThePageStaysGone() throws {
        var text = ""
        for file in try SleepNumbersLintTests.sleepSources() {
            text += try String(contentsOf: file, encoding: .utf8)
        }
        XCTAssertFalse(text.contains("MemorySourcesCard("))
        XCTAssertFalse(text.contains("sleepLayout(width:"))
        XCTAssertFalse(text.contains("caughtUpWorm"))
        XCTAssertFalse(try SleepNumbersLintTests.sleepSources().contains { $0.lastPathComponent == "MemorySourcesCard.swift" })
    }
}
```

Delete `test_theCaughtUpWorm_showsOnlyWhenHappyAndCountless` from `SleepStageStripTests.swift`.
Create `ActivitySeriesTests.swift` by moving `MemorySourcesTests`' series cases (and its `utcDay`
helper) under a new class docstring naming the move; delete `MemorySourcesTests.swift`.

- [ ] **Step 2: Implement.**

`Views/Sources/ActivitySeries.swift` — the moved code, with one new header docstring:

```swift
import SwiftUI

// MARK: - The activity window (moved from Views/Sleep/MemorySourcesCard.swift, Track Z Z3)
//
// Track A wrote these for the Sleep page's Memory sources card; Sources v2
// (R-S8) has called them from the grid, the header card and the detail page
// ever since. The card has left the Sleep page (design §4.2 — Sources v2 draws
// the same projection), so the series live beside their only callers now.
// The functions and their tests moved verbatim; nothing about the window
// (UTC days, dense, oldest first) changed.
```

followed by `ActivityWindow`, `sparklinePoints`, `weekDots` and `sparklinePath` exactly as they
were (`ActivityWindow` stays `private`).

`Views/Sleep/SleepStages.swift` — replace `stageStripShowsCaughtUpWorm` with:

```swift
/// R-Z6 — whether the strip is on the page at all. It is the live instrument
/// while a cycle runs and the frozen record after a cancel or failure (P15);
/// an idle page after a clean cycle has no news for it, and the design's
/// default view is the room, one sentence, one button and one whisper line.
func stageStripIsVisible(isRunning: Bool, cancelled: Bool, failed: Bool) -> Bool {
    isRunning || cancelled || failed
}
```

`SleepStageStrip.swift` — delete the worm (property, constant, view, the `if` in `strip`); the
type docstring's third rule becomes "**One `TimelineView`, and only while something is actually
active.**" without the caught-up-worm sentence, and gains: "The caught-up worm that ended the strip
is gone (Track Z, R-A8 amended): the room's own worm is already `.happy`, and a second one was a
figure drawn twice."

`Views/Sleep/SleepHero.swift` — `SleepHeroView` becomes `SleepReadoutView`:

```swift
/// Details › Readout (Track Z §4.2): the meter that never renders without its
/// noun (R-A5), the three measured tiles (R-A6), the no-baseline line, and the
/// engine the last cycle ran on. It stays in THIS file so "Rested" is still
/// spelled by exactly one file (`SleepNumbersLintTests`).
struct SleepReadoutView: View {
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let mood: BookwormState
    let debt: SleepDebtView?
    let read: Int
    let total: Int
    /// Z-P3 — `page.lastCycle?.durationMs`.
    let lastDurationMs: Int?
    let lastEngine: String?
    let engineDetail: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("READOUT")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            if let meter = heroMeter(mood: mood, debt: debt, read: read, total: total) {
                meterView(meter)
            } else {
                noBaselineLine
            }
            tilesRow
            if let engine = lastEngine {
                engineLine(engine, detail: engineDetail)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    /// Moved from `SleepView.moodDetailLine` with its docstring (the one thing
    /// the meter cannot say: that there is no baseline at all).
    @ViewBuilder
    private var noBaselineLine: some View {
        if case .sleeping = mood {
            EmptyView()
        } else if let debt, debt.restedPct == nil {
            Text("No baseline yet — Sleep hasn't run in this bank.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// Moved from `SleepView.engineLine` with its docstring; the engine now
    /// wears its real mark (Z-P26).
    private func engineLine(_ engine: String, detail: String?) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("ENGINE")
                .font(CicadaTheme.font(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.1)
            EngineMark(engine: engine, size: 12)
            Text(Copy.engineLabel(engine))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            if let detail, !detail.isEmpty {
                Text("· \(detail)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
            }
            Spacer()
        }
    }

    // meterView(_:), tilesRow, activeBankEntityCount and feedingSourceCount
    // stay exactly as they are in SleepHeroView today; tilesRow passes
    // `lastDurationMs` (Task 2) to heroTiles.
}
```

(The last comment names code that already exists in the struct being renamed; keep it, don't
retype it.)

`Views/Sleep/SleepDetails.swift`:

```swift
import SwiftUI

/// Whether Details › Last cycle has anything to say (Track Z §4.1 F).
func lastCycleSectionIsVisible(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?) -> Bool {
    pageError != nil || cancelled || capped || !(indexWarning ?? "").isEmpty
}

/// The page's one second surface (R-Z6, R-Z7): opened on purpose, remembered
/// per viewer (spec decision 16), and **not built while closed** — `SleepView`
/// wraps it in `if detailsOpen {}`, so a closed Details costs no queue
/// `LazyVStack`, no history and no tiles (design §10's budget).
///
/// Each section carries its `DetailsSection.anchorID`, which is how a sentence
/// tail ("it's in Details") and "See what changed ›" land on the right card.
/// R-A12: every section takes the liveness desaturation except Last cycle —
/// news stays at full contrast.
struct SleepDetails: View {
    static let openKey = "cicada.sleep.detailsOpen"
    static let defaultOpen = false

    let page: SleepPageModel
    let liveness: SleepLiveness
    let pageError: String?
    let status: SleepStatusResponse?
    let episodes: [EpisodeQueueItem]
    let history: [SleepHistoryEntry]
    let details: [String: SleepCycleDetail]
    let expanded: String?
    let onToggleHistory: (String) -> Void
    var onSelectEntity: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if lastCycleSectionIsVisible(pageError: pageError, cancelled: page.cancelled,
                                         capped: page.capped, indexWarning: page.indexWarning) {
                LastCycleSection(pageError: pageError, status: status)
                    .id(DetailsSection.lastCycle.anchorID)
            }
            StudyListCard(rows: page.rows, episodes: episodes, queueLoad: page.queueLoad,
                          onSelectEntity: onSelectEntity)
                .id(DetailsSection.waiting.anchorID)
                .saturation(liveness.saturation)
            SleepReadoutView(mood: page.mood, debt: page.debt, read: page.read, total: page.total,
                             lastDurationMs: page.lastCycle?.durationMs,
                             lastEngine: status?.lastEngine, engineDetail: status?.engineDetail)
                .id(DetailsSection.readout.anchorID)
                .saturation(liveness.saturation)
            ConsolidationHistoryCard(entries: history, details: details, expanded: expanded,
                                     onToggle: onToggleHistory, onSelectEntity: onSelectEntity)
                .id(DetailsSection.pastNights.anchorID)
                .saturation(liveness.saturation)
        }
    }
}

/// Details › Last cycle — today's four banners, moved verbatim from
/// `SleepView` (Track Z §4.2): the error (`pageError`), the cancel, the episode
/// cap and the index warning, at full contrast (R-A12).
struct LastCycleSection: View {
    let pageError: String?
    let status: SleepStatusResponse?
    // body: a "LAST CYCLE" header, then errorBanner / cancelledBanner /
    // capBanner / warningBanner exactly as they were, each behind the same
    // condition it had in SleepView.
}
```

(`LastCycleSection`'s body and the four banner functions are the moved code — write them out in
full; they are not reworded.)

`Views/Sleep/SleepView.swift`:
- `SleepLayout`:

```swift
/// The Sleep page's one column (Track Z R-Z6 / §4.1 — R-A1's two columns are
/// retired). 760 pt is the width the stacked page always had; it is not
/// scaled because the room is the widest thing in it and fits at every zoom
/// step (`SleepLayoutTests`, Z-P23).
enum SleepLayout {
    static let contentWidth: CGFloat = 760
}
```

- New state: `@AppStorage(SleepDetails.openKey) private var detailsOpen = SleepDetails.defaultOpen`
  and `@State private var pendingScroll: DetailsSection?`.
- `body`:

```swift
    var body: some View {
        let page = resolvePage()
        ZStack {
            CicadaTheme.background
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                        headerRow
                        roomCard(page)
                            .saturation(liveness.saturation)
                        detailsDisclosure
                        if detailsOpen {
                            SleepDetails(page: page, liveness: liveness, pageError: pageError,
                                         status: sleepVM.status, episodes: sleepVM.queuedEpisodes,
                                         history: sleepVM.history, details: sleepVM.details,
                                         expanded: sleepVM.expanded, onToggleHistory: toggleHistory,
                                         onSelectEntity: onSelectEntity)
                        }
                    }
                    .padding(CicadaTheme.spacingXL)
                    .frame(maxWidth: SleepLayout.contentWidth)
                    .frame(maxWidth: .infinity, alignment: .top)
                }
                // Details is built only while open, so an anchor inside it
                // exists one update after `detailsOpen` flips: scroll then.
                .onChange(of: pendingScroll) { _, section in
                    guard let section else { return }
                    DispatchQueue.main.async {
                        withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) {
                            proxy.scrollTo(section.anchorID, anchor: .top)
                        }
                        pendingScroll = nil
                    }
                }
            }
            // the existing top-right `?` VStack, unchanged
        }
        // the existing .task / .onChange modifiers, unchanged
    }
```

- `roomCard(_ page:)` — Task 3's `deskCard` minus `SleepHeroView`, `moodDetailLine`, the engine line
  and the banners; the strip moves to the card's last row, below the whisper line (Z-P9):

```swift
            if stageStripIsVisible(isRunning: page.isRunning, cancelled: page.cancelled,
                                   failed: page.cycleError != nil) {
                SleepStageStrip(pips: page.pips)
            }
```

  The sentence's `canPerform` becomes `{ switch $0 { case .retry, .openDetails: true; default: false } }`
  and its `perform` handles
  `.openDetails(let section)` with `openDetails(section)`.
- Add:

```swift
    /// Open Details and land on one section — a tail link's destination
    /// (Z-P5). The scroll waits for `pendingScroll`'s `onChange`, because a
    /// closed Details has no anchors to scroll to yet.
    private func openDetails(_ section: DetailsSection) {
        withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { detailsOpen = true }
        pendingScroll = section
    }

    /// The one row that opens the second surface (R-Z6). `if detailsOpen {}`
    /// in `body`, not an opacity, is what keeps a closed Details free.
    private var detailsDisclosure: some View {
        Button {
            withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { detailsOpen.toggle() }
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: detailsOpen ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .frame(width: 12)
                Text(Copy.sleepDetails)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                Spacer(minLength: 0)
            }
            .foregroundStyle(CicadaTheme.textSecondary)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(Copy.sleepDetails)
        .accessibilityValue(detailsOpen ? "expanded" : "collapsed")
    }
```

- `headerRow`: delete the `Text(Copy.sleepSubtitle)` line (the wording stays pinned by
  `CopyConstantsTests`). It becomes the page's hint by going on the title element:
  `Text("Sleep Cycle")` gains `.accessibilityHint(Copy.sleepSubtitle)`. The hint goes on that one
  `Text` and **not** on the page's `ZStack`, because an accessibility modifier on a container that
  is not itself an element spreads to every element inside it (the double reading
  `stalenessChip`'s comment describes). On the `ZStack`, every button on the page would carry the
  subtitle as its hint.
- The `stalenessChip` comment (`SleepView.swift:592-596`) lists `MemorySourcesCard` and
  `SleepBubble` as examples of the collapse-then-label pattern. Both are gone from the page after
  this task, so change the list to `SleepHero`, `BookPile` and `SleepStageStrip`.
- Delete the code the **Files** list names. The `leftColumn` docstring's R-A12 reasoning (why
  `.saturation` is unconditional) moves onto `roomCard`'s call site in one sentence.

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures.
  `SleepNumbersLintTests.testTheRestedPercentageIsSpelledByExactlyOneFile` still passes
  (`SleepDetails.swift` never spells it); `CountLiteralLintTests` scans the new
  `Views/Sources/ActivitySeries.swift` and passes (no `Text("…\(…)")` in it).
- [ ] **Step 4: Commit** — `feat(sleep v4): one column, one Details, a strip only with news (G125 v4, R-Z6, R-Z7)`.

---

### Task 5 (Z4): Sprite poses and reactions — the worm can look, perk, talk and cheer

The worm's response art (R-Z1) is authored as frames inside `BookwormSprites`, gated by the
design's state × response matrix (§6.4), and drawn by the one mascot renderer under a key that
leaves every existing key byte-identical. No view uses a pose yet; Task 6 does. This task depends on
nothing and could run beside Tasks 2–4.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormPose.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift` — `eyes(pupil:lid:gaze:)` (`:138-153`); hoist `bookOpen`/`bookFlick` from `frames(for:)`'s locals (`:389-390`) to private statics (output unchanged); add the pose/reaction extension
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift` — `maxCacheEntries = 1024`, `cacheKey(state:look:frameIndex:pointSize:)`, `keyIndex(frames:look:frameIndex:)`, `cachedImage(state:look:frameIndex:pointSize:)`; the existing two entry points forward with `.idle`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift` — `pose`, `reaction`, `reactionFrameIndex`
- Test (new): `BookwormPoseSpriteTests.swift`, `BookwormLookRendererTests.swift`, `BookwormFramesBenchmarkTests.swift`
- Tests this task must NOT touch, and that must stay green (the proof the idle path is untouched): `BookwormSpriteTests`, `BookwormRendererTests`, `BookwormViewTests`, `BookwormStateTests` (Task 1's input edit to the last one is the only change it ever gets)

**Interfaces:**
- Produces: `Gaze`; `BookwormPose` (`gaze`, `keySegment`, `effective(for:reduceMotion:)`); `BookwormReaction` (`followsGaze`); `ActiveReaction`; `BookwormLook` (`idle`, `keySegment`, `reachable(for:)`, `beat(_:for:gaze:)`); `BookwormState.acceptsGaze` / `.acceptsDropPose` / `.allows(_:)`; `BookwormSprites.reactionInterval`, `.posePulseInterval`, `frames(for:pose:)`, `reactionFrames(_:for:gaze:)`, `frames(for:look:)`; `BookwormRenderer.maxCacheEntries`, `cacheKey(state:look:frameIndex:pointSize:)`, `keyIndex(frames:look:frameIndex:)`, `cachedImage(state:look:frameIndex:pointSize:)`; `BookwormView(… pose:reaction:)`, `BookwormView.reactionFrameIndex(at:startedAt:count:)`.
- Consumes: the existing private fragments (`compose`, mouths, `capped`, `stageDots`, glyphs) — same file.

- [ ] **Step 1: Failing tests.** `Tests/CicadaAppTests/BookwormPoseSpriteTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z §6.1 — the worm's poses and reactions, checked the way
/// `BookwormSpriteTests` checks its states: dimensions and palette, the
/// signature rows, and — the rule response art lives under — **a reaction
/// never hides a state mark** (R-Z1): the nightcap, the stage dots and the
/// red pupils persist through every response.
final class BookwormPoseSpriteTests: XCTestCase {

    /// Every state the Sleep page can show.
    static let pageStates: [BookwormState] =
        [.awake, .happy, .reading, .hungry, .digesting, .error] + (1...5).map { .sleeping(stage: $0) }

    private var allowed: Set<Character> { Set(BookwormPalette.colors.keys).union(["."]) }

    private func everyFrame(_ state: BookwormState) -> [(String, PixelGrid)] {
        BookwormLook.reachable(for: state).flatMap { look in
            BookwormSprites.frames(for: state, look: look).frames.enumerated().map {
                ("\(state.spriteKey) \(look.keySegment ?? "idle") #\($0.offset)", $0.element)
            }
        }
    }

    func test_everyLookFrameIs24x24AndInThePalette() {
        for state in Self.pageStates {
            for (name, frame) in everyFrame(state) {
                XCTAssertEqual(frame.count, 24, name)
                for row in frame {
                    XCTAssertEqual(row.count, 24, name)
                    for ch in row where !allowed.contains(ch) { XCTFail("\(name): '\(ch)'") }
                }
            }
        }
    }

    /// R-Z4 / design §6.1: `.idle` is byte-identical to today's frames.
    func test_theIdleLookIsTodaysFrames() {
        for state in Self.pageStates + [.curious(count: 3)] {
            XCTAssertEqual(BookwormSprites.frames(for: state, pose: .idle).frames,
                           BookwormSprites.frames(for: state).frames, state.spriteKey)
            XCTAssertEqual(BookwormSprites.frames(for: state, look: .idle).interval,
                           BookwormSprites.frames(for: state).interval)
        }
        XCTAssertEqual(BookwormSprites.eyes(), BookwormSprites.eyes(gaze: .center))
    }

    /// Three gazes change only the pupil rows (7–8 open, 7 half-lidded); the
    /// rim rows, which `BookwormSpriteTests` pins, never move.
    func test_gazeMovesOnlyThePupils() {
        let left = BookwormSprites.eyes(gaze: .left), right = BookwormSprites.eyes(gaze: .right)
        let center = BookwormSprites.eyes()
        XCTAssertEqual(left[2], "....obaoowwabaoowwabo...")
        XCTAssertEqual(right[2], "....obawwooabawwooabo...")
        XCTAssertEqual(center[2], "....obawoowabawoowabo...")
        for i in [0, 1, 4] { XCTAssertEqual(left[i], center[i]); XCTAssertEqual(right[i], center[i]) }
        XCTAssertEqual(BookwormSprites.eyes(pupil: "e", gaze: .left), BookwormSprites.eyes(pupil: "e"),
                       "red eyes are state art and never look away")
    }

    /// The glasses rims (rows 5 and 9) are the character's signature. Every
    /// frame this task AUTHORS keeps them, after undoing at most the one-cell
    /// hop/crouch or the head's one-cell shake. The idle frames and cheer's
    /// borrowed happy frames (whose big sparkle crosses the rim on frame 1)
    /// are existing art, pinned by `BookwormSpriteTests`.
    func test_theGlassesRimsSurviveEveryNewFrame() {
        let top = String(BookwormSprites.awakeBase[5].prefix(21))
        let bottom = String(BookwormSprites.awakeBase[9].prefix(21))
        for state in Self.pageStates {
            let authored = BookwormLook.reachable(for: state).filter { look in
                if look == .idle { return false }
                if case .reaction(.cheer, _) = look { return false }
                return true
            }
            let frames = authored.flatMap { look in
                BookwormSprites.frames(for: state, look: look).frames.map { ("\(state.spriteKey) \(look.keySegment ?? "")", $0) }
            }
            for (name, frame) in frames {
                let found = [-1, 0, 1].contains { dy in [-1, 0, 1].contains { dx in
                    let f = BookwormSprites.shiftRows(BookwormSprites.shift(frame, dy: -dy), 0..<24, dx: -dx)
                    return String(f[5].prefix(21)) == top && String(f[9].prefix(21)) == bottom
                } }
                XCTAssertTrue(found, name)
            }
        }
    }

    /// R-Z1 — the cap on every `.sleeping`/`.reading` frame (a capped state's
    /// hop is a one-cell crouch, Z-P11, so the cap may sit one row lower).
    func test_theNightcapSurvivesEveryLook() {
        let cap: [(Int, Int, Character)] = [(0, 10, "z"), (2, 5, "w"), (2, 16, "w"), (3, 3, "w")]
        for state in [BookwormState.reading] + (1...5).map({ .sleeping(stage: $0) }) {
            for (name, frame) in everyFrame(state) {
                let capped = [0, 1].contains { dy in cap.allSatisfy { Array(frame[$0.0 + dy])[$0.1] == $0.2 } }
                XCTAssertTrue(capped, name)
            }
        }
    }

    func test_theStageDotsAndTheRedPupilsSurviveEveryLook() {
        for stage in 1...5 {
            for (name, frame) in everyFrame(.sleeping(stage: stage)) {
                XCTAssertEqual(frame[23], BookwormSprites.stageDots(stage)[23], name)
            }
        }
        for (name, frame) in everyFrame(.error) {
            XCTAssertTrue(frame.joined().contains("e"), name)
            XCTAssertFalse(frame[7].contains("oo"), "\(name): no dark pupils on an error frame")
        }
    }

    /// Reading keeps its book on every frame — gulp lowers it (Z-P12).
    func test_theReadingBookSurvivesEveryLook() {
        for (name, frame) in everyFrame(.reading) {
            XCTAssertTrue((14...21).contains { r in String(Array(frame[r])[8...16]) == "aaaaaaaaa" }, name)
        }
    }

    /// §6.4 — `.sleeping`, `.error` and `.digesting` have no gaze variants.
    func test_suppressedStatesIgnoreThePointer() {
        for state in [BookwormState.sleeping(stage: 2), .error, .digesting] {
            for gaze in Gaze.allCases {
                XCTAssertEqual(BookwormSprites.frames(for: state, pose: .attentive(gaze)).frames,
                               BookwormSprites.frames(for: state).frames, state.spriteKey)
            }
        }
    }

    /// The state × response matrix (§6.4), including the Z-P12 reconciliation.
    func test_theMatrix() {
        XCTAssertEqual(Self.pageStates.filter(\.acceptsGaze).map(\.caseName), ["awake", "happy", "reading", "hungry"])
        XCTAssertTrue(BookwormState.digesting.acceptsDropPose)
        XCTAssertFalse(BookwormState.sleeping(stage: 1).acceptsDropPose)
        XCTAssertTrue(BookwormState.sleeping(stage: 3).allows(.talk), "it talks in its sleep")
        XCTAssertFalse(BookwormState.error.allows(.talk), "words only")
        XCTAssertTrue(BookwormState.digesting.allows(.gulp))
        XCTAssertTrue(BookwormState.digesting.allows(.cheer))
        XCTAssertTrue(BookwormState.happy.allows(.cheer))
        XCTAssertFalse(BookwormState.reading.allows(.cheer))
        XCTAssertFalse(BookwormState.digesting.allows(.perk))
        XCTAssertTrue(BookwormSprites.reactionFrames(.talk, for: .error, gaze: .center).isEmpty)
        XCTAssertFalse(BookwormState.curious(count: 3).acceptsGaze, "the menu bar never gets a pose")
    }

    /// Every beat is at most three frames at 0.12 s — ≤ 0.36 s, inside the
    /// page's 400 ms budget (R-Z12).
    func test_everyBeatFitsTheMotionBudget() {
        XCTAssertEqual(BookwormSprites.reactionInterval, 0.12)
        for state in Self.pageStates {
            for reaction in BookwormReaction.allCases where state.allows(reaction) {
                let n = BookwormSprites.reactionFrames(reaction, for: state, gaze: .left).count
                XCTAssertTrue((2...3).contains(n), "\(reaction) on \(state.spriteKey)")
                XCTAssertLessThanOrEqual(Double(n) * BookwormSprites.reactionInterval, SleepMotion.maxDuration)
            }
        }
    }

    /// The attentive loop costs no more ticks than idle: the state's own
    /// interval, a blink on the fourth frame; the drop poses loop at 0.4 s.
    func test_theLoopsKeepTheirIntervals() {
        let attentive = BookwormSprites.frames(for: .hungry, pose: .attentive(.left))
        XCTAssertEqual(attentive.interval, BookwormSprites.frames(for: .hungry).interval)
        XCTAssertEqual(attentive.frames.count, 4)
        XCTAssertEqual(attentive.frames[0], attentive.frames[2])
        XCTAssertNotEqual(attentive.frames[0], attentive.frames[3])
        XCTAssertEqual(BookwormSprites.frames(for: .awake, pose: .expectant(.right)).interval, 0.4)
        XCTAssertEqual(BookwormSprites.frames(for: .awake, pose: .eager).frames.count, 2)
    }
}
```

(In `test_gazeMovesOnlyThePupils` the indices are the fragment's own: `eyes()` returns grid rows
5–9, so index 2 is grid row 7.)

`Tests/CicadaAppTests/BookwormLookRendererTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z §6.1 renderer + Z-P10 — the key gains one `look` segment that is
/// omitted for idle, so every pre-Z4 key is byte-identical
/// (`BookwormRendererTests` passes unmodified), and the page's reachable key
/// set stays under the design's bound so the menu bar's frames are never
/// collateral damage of a wipe (P13).
@MainActor
final class BookwormLookRendererTests: XCTestCase {

    func test_idleKeysAreByteIdentical() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .reading, look: .idle, frameIndex: 2, pointSize: 120), "reading|2|120")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .sleeping(stage: 3), look: .idle, frameIndex: 1, pointSize: 18),
                       BookwormRenderer.cacheKey(state: .sleeping(stage: 3), frameIndex: 1, pointSize: 18))
    }

    func test_lookKeysNameTheLook() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .happy, look: .pose(.attentive(.left)), frameIndex: 0, pointSize: 120),
                       "happy|attentive.left|0|120")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .happy, look: .reaction(.cheer, .center), frameIndex: 2, pointSize: 120),
                       "happy|cheer.center|2|120")
    }

    /// A loop that repeats a frame keys the repeat by its first occurrence;
    /// idle never does (its keys must not move).
    func test_repeatedFramesShareAKey_exceptOnTheIdlePath() {
        let attentive = BookwormSprites.frames(for: .awake, look: .pose(.attentive(.center))).frames
        XCTAssertEqual(BookwormRenderer.keyIndex(frames: attentive, look: .pose(.attentive(.center)), frameIndex: 2), 0)
        let idle = BookwormSprites.frames(for: .awake).frames
        XCTAssertEqual(BookwormRenderer.keyIndex(frames: idle, look: .idle, frameIndex: 2), 2)
    }

    /// Design §6.1: "the page's own key set is at most about 200 per size. A
    /// test pins it at ≤ 256." Measured at 216 when this plan was written.
    func test_thePagesKeySetStaysUnderTheBound() {
        var keys = Set<String>()
        for state in BookwormPoseSpriteTests.pageStates {
            for look in BookwormLook.reachable(for: state) {
                let frames = BookwormSprites.frames(for: state, look: look).frames
                for i in frames.indices {
                    keys.insert(BookwormRenderer.cacheKey(
                        state: state, look: look,
                        frameIndex: BookwormRenderer.keyIndex(frames: frames, look: look, frameIndex: i),
                        pointSize: 120))
                }
            }
        }
        XCTAssertLessThanOrEqual(keys.count, 256)
        XCTAssertGreaterThan(keys.count, 100, "the enumeration is not vacuous")
    }

    /// The menu bar's `curious(1…99)` keys alone can reach 297, so the wipe
    /// bound doubles in the same commit the page's poses arrive (design §6.1).
    func test_theWipeBoundDoubled() {
        XCTAssertEqual(BookwormRenderer.maxCacheEntries, 1024)
    }

    /// Z-P10: a beat plays under a key the bound above counted. The gaze folds
    /// to `.center` wherever the frames ignore it (a reaction that does not
    /// follow the eyes, or a state whose eyes must not move), and a beat the
    /// matrix forbids has no look at all. Without the fold, a cheer played
    /// while the pointer sits left of the worm would key as `cheer.left`,
    /// a key the ≤ 256 measurement never saw.
    func test_aBeatPlaysAsAReachableLook() {
        for state in BookwormPoseSpriteTests.pageStates {
            for reaction in BookwormReaction.allCases {
                for gaze in Gaze.allCases {
                    guard let look = BookwormLook.beat(reaction, for: state, gaze: gaze) else {
                        XCTAssertFalse(state.allows(reaction), "\(reaction) on \(state.spriteKey)")
                        continue
                    }
                    XCTAssertTrue(BookwormLook.reachable(for: state).contains(look),
                                  "\(reaction) \(gaze) on \(state.spriteKey)")
                }
            }
        }
        XCTAssertEqual(BookwormLook.beat(.cheer, for: .happy, gaze: .left), .reaction(.cheer, .center))
        XCTAssertEqual(BookwormLook.beat(.talk, for: .digesting, gaze: .right), .reaction(.talk, .center))
        XCTAssertNil(BookwormLook.beat(.talk, for: .error, gaze: .center))
    }

    func test_aLookImageIsCachedLikeAnyOther() {
        let a = BookwormRenderer.cachedImage(state: .awake, look: .pose(.attentive(.left)), frameIndex: 0, pointSize: 96)
        let b = BookwormRenderer.cachedImage(state: .awake, look: .pose(.attentive(.left)), frameIndex: 2, pointSize: 96)
        XCTAssertTrue(a === b, "frame 2 repeats frame 0 and shares its image")
    }

    // MARK: BookwormView's beat clock

    func test_reactionFrameIndex_playsOnceThenEnds() {
        let start = Date(timeIntervalSinceReferenceDate: 100)
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start, startedAt: start, count: 3), 0)
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(0.13), startedAt: start, count: 3), 1)
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(0.25), startedAt: start, count: 3), 2)
        XCTAssertNil(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(0.37), startedAt: start, count: 3))
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(-1), startedAt: start, count: 3), 0)
        XCTAssertNil(BookwormView.reactionFrameIndex(at: start, startedAt: start, count: 0))
    }

    /// Reduce Motion (§6.1): no gaze; the drop poses keep their frame 0
    /// because the armed-drop cue is a state, not a motion.
    func test_reduceMotionDropsTheGazeButKeepsTheArmedPose() {
        XCTAssertEqual(BookwormPose.attentive(.left).effective(for: .awake, reduceMotion: true), .idle)
        XCTAssertEqual(BookwormPose.expectant(.left).effective(for: .awake, reduceMotion: true), .expectant(.left))
        XCTAssertEqual(BookwormPose.expectant(.left).effective(for: .digesting, reduceMotion: false), .expectant(.center))
        XCTAssertEqual(BookwormPose.eager.effective(for: .sleeping(stage: 2), reduceMotion: false), .idle)
    }
}
```

`Tests/CicadaAppTests/BookwormFramesBenchmarkTests.swift` (design §6.1: benchmark first):

```swift
import XCTest
@testable import CicadaApp

/// Design §6.1 / Z-P24 — `frames(for:)` is recomposed twice per tick
/// (`BookwormView.body` and `BookwormRenderer.cachedImage`), and poses
/// multiply those calls. A memo ships only if this benchmark moves.
final class BookwormFramesBenchmarkTests: XCTestCase {
    func test_benchmark_framesForEveryReachableLook() {
        let pairs = BookwormPoseSpriteTests.pageStates.flatMap { state in
            BookwormLook.reachable(for: state).map { (state, $0) }
        }
        measure {
            for _ in 0..<20 {
                for (state, look) in pairs { _ = BookwormSprites.frames(for: state, look: look) }
            }
        }
    }
}
```

- [ ] **Step 2: Implement.**

`MenuBar/BookwormPose.swift`:

```swift
import Foundation

/// Where the worm looks (Track Z §6.1). Three horizontal poses, not six:
/// the room is a wide, short box and the worm's own ink span is the dead
/// zone (`gazeFor`, `DeskHotspots.swift`), so left / centre / right is all
/// the pointer can honestly mean.
enum Gaze: String, Hashable, CaseIterable {
    case left, center, right
}

/// A pose the worm's frames can take — RESPONSE art (R-Z1): it acknowledges
/// the person's own gesture, carries no fact, and never contradicts the state
/// it is drawn over (§6.4). Character-agnostic on purpose (G127 would draw
/// the same four poses for another mascot).
enum BookwormPose: Hashable {
    /// Today's frames.
    case idle
    /// The pointer is in the room: the eyes follow it, with a blink.
    case attentive(Gaze)
    /// A file is being dragged over the room (Track Z §7.4 — feeding, Z9).
    case expectant(Gaze)
    /// …and over the worm itself.
    case eager

    var gaze: Gaze {
        switch self {
        case .idle, .eager: .center
        case .attentive(let gaze), .expectant(let gaze): gaze
        }
    }

    /// The renderer key's look segment; `nil` for `.idle`, which is what keeps
    /// every pre-Z4 key byte-identical.
    var keySegment: String? {
        switch self {
        case .idle: nil
        case .attentive(let gaze): "attentive.\(gaze.rawValue)"
        case .expectant(let gaze): "expectant.\(gaze.rawValue)"
        case .eager: "eager"
        }
    }

    /// What this pose becomes for `state` (§6.4) and under Reduce Motion
    /// (§6.1): the gaze is dropped — a following eye is motion — but the drop
    /// poses stay, because the armed-drop cue is a state (frame 0 is held by
    /// `BookwormView.frameIndex` anyway). A state with no gaze looks ahead.
    func effective(for state: BookwormState, reduceMotion: Bool) -> BookwormPose {
        switch self {
        case .idle:
            return .idle
        case .attentive(let gaze):
            return state.acceptsGaze && !reduceMotion ? .attentive(gaze) : .idle
        case .expectant(let gaze):
            guard state.acceptsDropPose else { return .idle }
            return .expectant(state.acceptsGaze ? gaze : .center)
        case .eager:
            return state.acceptsDropPose ? .eager : .idle
        }
    }
}

/// A short beat — at most three frames at `BookwormSprites.reactionInterval`
/// (≤ 0.36 s, R-Z12). `gulp` and `shake` are feeding's (Z9); `perk`, `talk`
/// and `cheer` are used from Task 6 on.
enum BookwormReaction: String, Hashable, CaseIterable {
    case perk, talk, gulp, shake, cheer

    /// Whether the frames depend on where the worm is looking.
    var followsGaze: Bool { self == .perk || self == .talk || self == .shake }
}

/// A beat in flight. `id` is what `WormStage`'s `.task(id:)` settles on, so a
/// second beat started mid-beat restarts the clock rather than being cut short.
struct ActiveReaction: Equatable {
    let kind: BookwormReaction
    let startedAt: Date
    let id: UUID
}

/// One thing the renderer can draw for a state: a pose loop or a beat.
/// Z-P10: a beat replaces the pose's frames, so it is keyed by the gaze it
/// plays at — never by pose × reaction, which would multiply the key set for
/// no visible difference.
enum BookwormLook: Hashable {
    case pose(BookwormPose)
    case reaction(BookwormReaction, Gaze)

    static let idle = BookwormLook.pose(.idle)

    var keySegment: String? {
        switch self {
        case .pose(let pose): pose.keySegment
        case .reaction(let reaction, let gaze): "\(reaction.rawValue).\(gaze.rawValue)"
        }
    }

    /// Every look §6.4 lets `state` show — the renderer's reachable key set,
    /// and the union the window's occlusion test masks with (Task 9).
    static func reachable(for state: BookwormState) -> [BookwormLook] {
        let gazes: [Gaze] = state.acceptsGaze ? Gaze.allCases : [.center]
        var looks: [BookwormLook] = [.idle]
        if state.acceptsGaze { looks += Gaze.allCases.map { .pose(.attentive($0)) } }
        if state.acceptsDropPose {
            looks += gazes.map { .pose(.expectant($0)) }
            looks.append(.pose(.eager))
        }
        for reaction in BookwormReaction.allCases where state.allows(reaction) {
            looks += (reaction.followsGaze ? gazes : [.center]).map { .reaction(reaction, $0) }
        }
        return looks
    }

    /// The look a beat plays as, or `nil` when §6.4 forbids it for `state`.
    /// The gaze folds to `.center` wherever the frames ignore it, which is
    /// exactly the rule `reachable(for:)` enumerates. So a beat's renderer key
    /// is always one the Z-P10 bound counted, whatever the pointer last did.
    /// `BookwormView` asks this and never builds a `.reaction` look itself.
    static func beat(_ reaction: BookwormReaction, for state: BookwormState, gaze: Gaze) -> BookwormLook? {
        guard state.allows(reaction) else { return nil }
        return .reaction(reaction, reaction.followsGaze && state.acceptsGaze ? gaze : .center)
    }
}

/// The state × response matrix (design §6.4). "—" means suppressed so a
/// response never contradicts state art: a sleeping worm's eyes stay shut,
/// error pupils stay red. `.curious` is the menu bar's and takes nothing.
extension BookwormState {
    var acceptsGaze: Bool {
        switch self {
        case .awake, .happy, .reading, .hungry: true
        default: false
        }
    }

    var acceptsDropPose: Bool {
        switch self {
        case .awake, .happy, .reading, .hungry, .digesting: true
        default: false
        }
    }

    /// Z-P12: gulp is allowed while digesting (§6.4's matrix; §6.1's list
    /// omitted it — the matrix is the no-contradiction table).
    func allows(_ reaction: BookwormReaction) -> Bool {
        switch (reaction, self) {
        case (.perk, .awake), (.perk, .happy), (.perk, .reading), (.perk, .hungry): true
        case (.talk, .error), (.talk, .curious): false
        case (.talk, _): true
        case (.gulp, .awake), (.gulp, .happy), (.gulp, .reading), (.gulp, .hungry), (.gulp, .digesting): true
        case (.shake, .awake), (.shake, .happy), (.shake, .reading), (.shake, .hungry), (.shake, .digesting): true
        case (.cheer, .happy), (.cheer, .digesting): true
        default: false
        }
    }
}
```

`MenuBar/BookwormSprites.swift`:
- `eyes` gains `gaze: Gaze = .center` (default = today's output):

```swift
    static func eyes(pupil: Character = "o", lid: Lid = .open, gaze: Gaze = .center) -> PixelGrid {
        func lens(_ inside: String) -> String { "a" + inside + "a" }
        func row(_ l: String, _ r: String) -> String { "....ob" + l + "b" + r + "bo..." }
        let white = lens("wwww")
        let shut = lens("oooo")
        let p = String(pupil)
        // Track Z §6.1: each lens interior is four cells — `ooww` left, `woow`
        // centre (today), `wwoo` right. Red pupils are state art and never
        // look away (R-Z1).
        let seen: Gaze = pupil == "e" ? .center : gaze
        let look: String
        switch seen {
        case .left: look = lens(p + p + "ww")
        case .center: look = lens("w" + p + p + "w")
        case .right: look = lens("ww" + p + p)
        }
        let rimTop = "....ob" + "aaaaaa" + "a" + "aaaaaa" + "bo..."     // 5 — the bridge joins the rims
        let rimBottom = "....ob" + "aaaaaa" + "b" + "aaaaaa" + "bo..."  // 9
        let middle: [String]
        switch lid {
        case .open:   middle = [row(white, white), row(look, look), row(look, look)]
        case .closed: middle = [row(white, white), row(white, white), row(shut, shut)]
        case .half:   middle = [row(shut, shut), row(look, look), row(white, white)]
        }
        return [rimTop] + middle + [rimBottom]
    }
```

(The rim rows and the `lid` switch are today's lines, unchanged. They are shown so the function
can be pasted whole. Keep the existing docstring and add one line: "`gaze` moves only the pupils;
the default `.center` is today's output, byte for byte.")

- Hoist `bookOpen` and `bookFlick` to `private static let` beside `book` (same literals), delete
  the two local `let`s in `frames(for: .reading)`.
- Append:

```swift
// MARK: - Poses and reactions (Track Z §6.1)

extension BookwormSprites {
    /// One beat frame; pinned equal to `SleepMotion.beatFrameInterval`.
    static let reactionInterval: TimeInterval = 0.12
    /// The drop poses' two-frame loop (G107 R8's 250–800 ms band).
    static let posePulseInterval: TimeInterval = 0.4

    /// "Noticed you" — the cheeks the smile rows carry, drawn over any mouth.
    private static let blush: PixelGrid = glyph(["rr........rr"], top: 10, left: 7)

    private static func restingLid(_ state: BookwormState) -> Lid {
        if case .hungry = state { return .half }
        return .open
    }

    private static func restingMouth(_ state: BookwormState) -> PixelGrid {
        switch state {
        case .happy: mouthGrin
        case .hungry: mouthFrown
        case .digesting: mouthChew
        case .sleeping, .error, .curious: mouthNeutral
        default: mouthSmile
        }
    }

    private static func wearsCap(_ state: BookwormState) -> Bool {
        switch state {
        case .sleeping, .reading: true
        default: false
        }
    }

    /// What a state wears that no response may take off (R-Z1): the reading
    /// cap and book, the sleeping cap and stage dots, the digesting book.
    private static func marked(_ state: BookwormState, _ frame: PixelGrid) -> PixelGrid {
        switch state {
        case .reading: capped(merge(frame, glyph(bookOpen, top: 15, left: 8)))
        case .sleeping(let stage): capped(merge(frame, stageDots(stage)))
        case .digesting: merge(frame, glyph(book, top: 10, left: 17))
        default: frame
        }
    }

    private static func face(_ state: BookwormState, gaze: Gaze, mouth: PixelGrid? = nil, lid: Lid? = nil) -> PixelGrid {
        compose(eyes(lid: lid ?? restingLid(state), gaze: gaze), mouth ?? restingMouth(state))
    }

    /// R-Z4 — a hop is a whole-cell shift. Z-P11: a capped state crouches one
    /// cell instead, because its cap owns the grid's only headroom.
    private static func hop(_ state: BookwormState, _ frame: PixelGrid) -> PixelGrid {
        shift(frame, dy: wearsCap(state) ? 1 : -1)
    }

    private static func attentive(_ state: BookwormState, gaze: Gaze) -> PixelGrid {
        marked(state, face(state, gaze: gaze))
    }

    /// The pose's frames for `state`. `.idle` returns `frames(for:)` itself,
    /// which is how "idle is byte-identical" holds by construction.
    static func frames(for state: BookwormState, pose: BookwormPose) -> (frames: [PixelGrid], interval: TimeInterval) {
        let idle = frames(for: state)
        switch pose.effective(for: state, reduceMotion: false) {
        case .idle:
            return idle
        case .attentive(let gaze):
            let a = attentive(state, gaze: gaze)
            let blink = marked(state, face(state, gaze: .center, lid: .closed))
            return ([a, a, a, blink], idle.interval)
        case .expectant(let gaze):
            let e = marked(state, face(state, gaze: gaze, mouth: mouthOpen))
            return ([e, hop(state, e)], posePulseInterval)
        case .eager:
            let e = merge(marked(state, face(state, gaze: .center, mouth: mouthOpen)), blush)
            return ([hop(state, e), e], posePulseInterval)
        }
    }

    /// A beat's frames (≤ 3), or `[]` when §6.4 forbids it for `state`.
    static func reactionFrames(_ reaction: BookwormReaction, for state: BookwormState, gaze: Gaze) -> [PixelGrid] {
        guard state.allows(reaction) else { return [] }
        let g: Gaze = reaction.followsGaze && state.acceptsGaze ? gaze : .center
        switch reaction {
        case .perk:
            let a = attentive(state, gaze: g)
            return [hop(state, merge(a, blush)), a]
        case .talk:
            if case .sleeping(let stage) = state {
                // It talks in its sleep and never wakes (§6.1): eyes shut, cap and dots on.
                func sleepTalk(_ mouth: PixelGrid) -> PixelGrid {
                    capped(merge(merge(compose(eyes(lid: .closed), mouth), glyph(zSmall, top: 2, left: 21)),
                                 stageDots(stage)))
                }
                return [sleepTalk(mouthOpen), sleepTalk(mouthNeutral), sleepTalk(mouthOpen)]
            }
            let open = marked(state, face(state, gaze: g, mouth: mouthOpen))
            return [open, marked(state, face(state, gaze: g)), open]
        case .gulp:
            let chew = Array(frames(for: .digesting).frames.prefix(3))
            // Z-P12: reading lowers its held book for the gulp only.
            if case .reading = state { return chew.map { capped(merge($0, glyph(bookOpen, top: 17, left: 8))) } }
            return chew
        case .shake:
            let f = face(state, gaze: g)
            return [marked(state, shiftRows(f, 2..<13, dx: -1)),
                    marked(state, shiftRows(f, 2..<13, dx: 1)),
                    marked(state, f)]
        case .cheer:
            let happy = frames(for: .happy).frames
            return [happy[1], happy[2], happyBase]
        }
    }

    /// The renderer's one entry point for a look.
    static func frames(for state: BookwormState, look: BookwormLook) -> (frames: [PixelGrid], interval: TimeInterval) {
        switch look {
        case .pose(let pose): frames(for: state, pose: pose)
        case .reaction(let reaction, let gaze): (reactionFrames(reaction, for: state, gaze: gaze), reactionInterval)
        }
    }
}
```

(`private` members of `BookwormSprites` are visible to this extension because it is in the same
file — Swift 4+ scoping.)

`MenuBar/BookwormRenderer.swift`:

```swift
    /// Design §6.1 — the wholesale-wipe bound. The menu bar's `curious(1…99)`
    /// keys alone reach 297 and the Sleep page adds ≤ 256 per size, so 512
    /// would wipe the always-animating worm on a zoom step (P13's damage).
    static let maxCacheEntries = 1024

    static func cacheKey(state: BookwormState, look: BookwormLook, frameIndex: Int, pointSize: CGFloat) -> String {
        guard let segment = look.keySegment else {
            return cacheKey(state: state, frameIndex: frameIndex, pointSize: pointSize)
        }
        return "\(state.spriteKey)|\(segment)|\(frameIndex)|\(Int(pointSize))"
    }

    /// Z-P10 — a pose loop that repeats a frame keys the repeat by its first
    /// occurrence, so `[a, a, a, blink]` costs two images, not four. Idle
    /// never canonicalises: its keys are pinned byte-for-byte.
    static func keyIndex(frames: [PixelGrid], look: BookwormLook, frameIndex: Int) -> Int {
        guard look != .idle, frames.indices.contains(frameIndex) else { return frameIndex }
        return frames.firstIndex(of: frames[frameIndex]) ?? frameIndex
    }

    static func cachedImage(state: BookwormState, frameIndex: Int, pointSize: CGFloat) -> NSImage {
        cachedImage(state: state, look: .idle, frameIndex: frameIndex, pointSize: pointSize)
    }

    static func cachedImage(state: BookwormState, look: BookwormLook, frameIndex: Int, pointSize: CGFloat) -> NSImage {
        let (frames, _) = BookwormSprites.frames(for: state, look: look)
        let idx = frames.isEmpty ? 0 : ((frameIndex % frames.count) + frames.count) % frames.count
        let key = cacheKey(state: state, look: look,
                           frameIndex: keyIndex(frames: frames, look: look, frameIndex: idx), pointSize: pointSize)
        lock.lock()
        let hit = cache[key]
        lock.unlock()
        if let hit { return hit }
        let grid = frames.isEmpty ? BookwormSprites.awakeBase : frames[idx]
        let img = image(grid: grid, pointSize: pointSize)
        lock.lock()
        if cache.count > maxCacheEntries { cache.removeAll() }
        cache[key] = img
        lock.unlock()
        return img
    }
```

(This is today's body with the look threaded through and `512` replaced by `maxCacheEntries`. Keep
today's two inline comments, the one on the bound and the one on the racing second render, and
update the bound comment's arithmetic to the design §6.1 figures.)

`Views/Common/BookwormView.swift` — add `var pose: BookwormPose = .idle` and
`var reaction: ActiveReaction? = nil` after `alignment` (every existing call site keeps compiling
unchanged), and:

```swift
    /// Which beat frame to show — `nil` once the beat has played (the view
    /// falls back to its loop, and `WormStage` clears the reaction). Before
    /// the start it holds frame 0 rather than trapping.
    nonisolated static func reactionFrameIndex(at date: Date, startedAt: Date, count: Int) -> Int? {
        guard count > 0 else { return nil }
        let elapsed = date.timeIntervalSince(startedAt)
        guard elapsed >= 0 else { return 0 }
        let index = Int((elapsed / BookwormSprites.reactionInterval).rounded(.down))
        return index < count ? index : nil
    }
```

`body` becomes the following. The caption block is today's lines, unchanged:

```swift
    var body: some View {
        // Track Z §6.1: the pose as this state and Reduce Motion allow it.
        let effective = pose.effective(for: state, reduceMotion: reduceMotion)
        let look = BookwormLook.pose(effective)
        let (frames, interval) = BookwormSprites.frames(for: state, look: look)
        // A beat plays only with Reduce Motion off and only where §6.4 allows
        // it; `BookwormLook.beat` folds the gaze so its key is a counted one.
        let beat: BookwormLook? = reduceMotion ? nil
            : reaction.flatMap { BookwormLook.beat($0.kind, for: state, gaze: effective.gaze) }
        // G130 R6: scale the mascot with the rest of the chrome, but snap
        // back onto a multiple of 24 so a cell never lands on a fractional
        // point and the renderer's cache key — an `Int` — stays stable.
        let scaledSize = BookwormRenderer.snappedPointSize(pointSize * CicadaTheme.uiScale)
        VStack(alignment: alignment, spacing: CicadaTheme.spacingSM) {
            if let r = reaction, let beat {
                let count = BookwormSprites.frames(for: state, look: beat).frames.count
                TimelineView(.periodic(from: r.startedAt, by: BookwormSprites.reactionInterval)) { context in
                    // Held on the last frame once the beat has played (§6.1);
                    // `WormStage` clears the reaction right after.
                    let idx = Self.reactionFrameIndex(at: context.date, startedAt: r.startedAt, count: count)
                        ?? max(0, count - 1)
                    sprite(beat, frameIndex: idx, size: scaledSize)
                }
            } else {
                TimelineView(.periodic(from: Self.timelineOrigin, by: interval)) { context in
                    let idx = Self.frameIndex(at: context.date, interval: interval, count: frames.count,
                                              reduceMotion: reduceMotion)
                    sprite(look, frameIndex: idx, size: scaledSize)
                }
            }
            if let caption {
                Text(caption)
                    .font(captionFont)
                    .foregroundStyle(captionColor)
            }
        }
    }

    /// One frame through the one mascot cache. The fixed frame means a tick
    /// never causes layout.
    private func sprite(_ look: BookwormLook, frameIndex: Int, size: CGFloat) -> some View {
        Image(nsImage: BookwormRenderer.cachedImage(state: state, look: look, frameIndex: frameIndex, pointSize: size))
            .interpolation(.none)
            .frame(width: size, height: size)
            .accessibilityLabel("\(state.title) — \(state.detail)")
    }
```

The type docstring gains one sentence: "`pose` and `reaction` are response art (Track Z R-Z1). They
are `.idle`/`nil` everywhere except the Sleep room, so the menu bar, empty states, onboarding and
the upload overlay are unchanged." With `.idle` and no reaction, `look` is `.idle` and every key
and frame is today's. That is what `BookwormViewTests` and `BookwormRendererTests` passing
unmodified proves.

- [ ] **Step 3: Verify.** `swift test --filter 'Bookworm' 2>&1 | tail -20` → 0 failures, with
  `BookwormSpriteTests`, `BookwormRendererTests` and `BookwormViewTests` unmodified on the whole
  branch (`git diff --stat dev -- app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift
  app/CicadaApp/Tests/CicadaAppTests/BookwormRendererTests.swift app/CicadaApp/Tests/CicadaAppTests/BookwormViewTests.swift`
  prints nothing). Then the full `swift test`.
- [ ] **Step 4: The memo gate (Z-P24).** Run
  `swift test --filter BookwormFramesBenchmarkTests 2>&1 | grep -E "average|measured"` and note the
  average. Then add, in `BookwormSprites`, a lock-guarded memo keyed
  `"\(state.spriteKey)|\(look.keySegment ?? "idle")"` inside `frames(for:look:)` (an `NSLock` and a
  `nonisolated(unsafe) static var` dictionary, the renderer's own pattern), and re-run. **Keep the
  memo only if the new average is at most half the old one**; otherwise remove it. Either way the
  commit message records both averages.
- [ ] **Step 5: Commit** — `feat(sleep v4): poses and reactions as sprite frames, one look key (G107, R-Z1, R-Z4, Z-P10)` (+ `— frames memo: <before> → <after>`).

---

### Task 6 (Z5): The room responds — gaze, perk, and a worm that answers

The room becomes its own view (`StudyRoom`) with an inert art layer and a hotspot layer derived
from the pure layout (R-Z8). The worm's eyes follow the pointer across the room (three poses, a
one-cell hysteresis), it perks when the pointer reaches it (2 s cooldown), and a click steps
through true answers that **replace** the status sentence in its slot (R-Z5, R-Z7), with a talk
beat. Keyboard, VoiceOver and a context menu reach the same answers. Two lints land with it.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskHotspots.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomModel.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/WormAnswers.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyRoom.swift` — `StudyRoom`, `WormStage`, `WormHotspot`, `RoomA11yOrder`, `roomLinkCursor()`; the room `ZStack` moves here from `SleepView.roomCard`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskSceneSprites.swift` — `windowGlass` (the worked grid's glass rectangle, named once)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomSentence.swift` — `RoomContext` gains the answer facts; `RoomSentenceView` shows an answer when one is up, cross-fades, reports `pointerInSentence` and runs the dwell
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepPageModel.swift` — `roomContext` fills the answer facts; the page keeps `lastEngine`, `engineDetail`, `cycleCreated`, `cycleUpdated`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — `@State private var room = RoomModel()`; `roomCard` uses `StudyRoom`; the ladder resets on a mood change; `.openInbox` becomes performable
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMotion.swift` — `beatFrameInterval`, `maxBeatFrames`, `sentenceDuration`, `perkCooldown`, `answerDwell`, `sentence(reduceMotion:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — `wormHint`, `wormWhatAreYouDoing`
- Test (new): `DeskHotspotTests.swift`, `GazeTests.swift`, `WormAnswersTests.swift`, `RoomModelTests.swift`
- Test (extend): `SleepNumbersLintTests.swift` — the new budget numbers and the two lints (design §10); `SleepPageModelTests.swift` — the answer facts pass through `roomContext`

**Interfaces:**
- Produces: `DeskHotspot`, `DeskHotspots.wormCols`/`.wormRows`/`.eyeCell`, `deskHotspots(_:)`, `gazeFor(pointerX:layout:previous:state:)`, `sceneBottomLeading(_:in:)`; `DeskSceneSprites.windowGlass`; `RoomModel` (`gaze`, `pointerInRoom`, `reaction`, `answerIndex`, `pointerInSentence`, `pointer(at:scene:spots:state:now:reduceMotion:)`, `poke(answerCount:state:now:reduceMotion:)`, `dismissAnswers()`, `play(_:state:now:reduceMotion:)`, `settleReaction()`, statics `nextAnswerIndex(after:count:)`, `shouldPerk(lastPerkAt:now:)`, `beatAllowed(_:state:reduceMotion:)`); `LastCycleFacts`, `wormAnswers(_:)`; `StudyRoom`, `WormStage`, `WormHotspot`, `RoomA11yOrder`, `View.roomLinkCursor()`.
- Consumes: Task 5's `BookwormView(pose:reaction:)`, `BookwormState.allows`/`.acceptsGaze`; Task 3's `SentenceLine`, `RoomSentenceView`; `DeskScene.plan`/`.wormCell`/`.pileCell`, `DeskSceneSprites.inkBounds`/`.lampLit`.

- [ ] **Step 1: Failing tests.**

`Tests/CicadaAppTests/DeskHotspotTests.swift`:

```swift
import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §6.2 / R-Z8 — the hotspot layer is derived from the pure layout, in
/// whole cells, so it can never drift from the art it sits on.
final class DeskHotspotTests: XCTestCase {

    private var scales: [Double] { (8...14).map { Double($0) / 10 } }

    func test_everyHotspotIsWholeCellsInsideTheScene() {
        for scale in scales {
            let layout = deskSceneLayout(pointSize: 120, uiScale: scale)
            let spots = deskHotspots(layout)
            XCTAssertEqual(Set(spots.keys), Set(DeskHotspot.allCases))
            for (spot, rect) in spots {
                for v in [rect.minX, rect.minY, rect.width, rect.height] {
                    XCTAssertEqual(v.truncatingRemainder(dividingBy: layout.cell), 0, "\(spot) @\(scale)")
                }
                XCTAssertTrue(CGRect(origin: .zero, size: layout.size).contains(rect), "\(spot) @\(scale)")
            }
        }
    }

    /// Pairwise disjoint — a pointer is over one thing or none; the window
    /// stops where the worm starts.
    func test_hotspotsNeverOverlap() {
        for scale in scales {
            let spots = Array(deskHotspots(deskSceneLayout(pointSize: 120, uiScale: scale)).values)
            for i in spots.indices { for j in spots.indices where j > i {
                XCTAssertTrue(spots[i].intersection(spots[j]).isEmpty, "@\(scale)")
            } }
        }
    }

    /// P10 — the lamp and the window never reach into the real pile's column.
    func test_theLampAndTheWindowStayOutOfThePileColumn() {
        for scale in scales {
            let layout = deskSceneLayout(pointSize: 120, uiScale: scale)
            let spots = deskHotspots(layout)
            for spot in [DeskHotspot.lamp, .window] {
                XCTAssertTrue(spots[spot]!.intersection(layout.pileFrame).isEmpty, "\(spot) @\(scale)")
            }
        }
    }

    func test_theEyesAreInsideTheWorm() {
        for scale in scales {
            let layout = deskSceneLayout(pointSize: 120, uiScale: scale)
            let eye = CGPoint(x: (CGFloat(DeskHotspots.eyeCell.col) + 0.5) * layout.cell,
                              y: (CGFloat(DeskHotspots.eyeCell.row) + 0.5) * layout.cell)
            XCTAssertTrue(deskHotspots(layout)[.worm]!.contains(eye), "@\(scale)")
        }
    }

    /// The numbers the design names, at 5 pt per cell.
    func test_theCellsTheDesignNames() {
        let spots = deskHotspots(deskSceneLayout(pointSize: 120, uiScale: 1.0))
        XCTAssertEqual(spots[.worm], CGRect(x: 150, y: 20, width: 100, height: 120), "cols 30–49 × rows 4–27")
        XCTAssertEqual(spots[.lamp], CGRect(x: 0, y: 0, width: 50, height: 100), "the lamp's ink")
        XCTAssertEqual(spots[.window], CGRect(x: 100, y: 40, width: 50, height: 80), "glass cols 20–29 × rows 8–23")
    }

    /// The window's glass rectangle is named once, and today's worked grid
    /// agrees with it: every non-frame cell lies inside it.
    func test_theGlassRectangleMatchesTheWorkedGrid() {
        let glass = DeskSceneSprites.windowGlass
        for (r, row) in DeskSceneSprites.window.enumerated() {
            for (c, ch) in row.enumerated() where ch != "." && ch != "f" && ch != "d" {
                XCTAssertTrue(glass.rows.contains(r) && glass.cols.contains(c), "(\(r),\(c)) '\(ch)'")
            }
        }
    }

    func test_sceneBottomLeadingFlipsY() {
        let layout = deskSceneLayout(pointSize: 120, uiScale: 1.0)
        XCTAssertEqual(sceneBottomLeading(CGPoint(x: 200, y: 70), in: layout), CGPoint(x: 200, y: 70))
        XCTAssertEqual(sceneBottomLeading(CGPoint(x: 10, y: 0), in: layout), CGPoint(x: 10, y: 140))
    }
}
```

`Tests/CicadaAppTests/GazeTests.swift`:

```swift
import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §6.2 — three horizontal poses over the room, the worm's own ink
/// span as the dead zone, one cell of hysteresis on both edges.
final class GazeTests: XCTestCase {

    private let layout = deskSceneLayout(pointSize: 120, uiScale: 1.0)   // 5 pt cells: worm 150…250

    func test_threePosesAcrossTheRoom() {
        XCTAssertEqual(gazeFor(pointerX: nil, layout: layout, previous: .left, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: 100, layout: layout, previous: .center, state: .awake), .left)
        XCTAssertEqual(gazeFor(pointerX: 200, layout: layout, previous: .center, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: 300, layout: layout, previous: .center, state: .awake), .right)
    }

    /// §6.4 — sleeping eyes stay shut, red pupils and a chewing worm look ahead.
    func test_suppressedStatesAlwaysLookAhead() {
        for state in [BookwormState.sleeping(stage: 2), .error, .digesting] {
            XCTAssertEqual(gazeFor(pointerX: 10, layout: layout, previous: .left, state: state), .center)
        }
    }

    /// A sweep back and forth across a boundary changes the gaze at most once.
    func test_aBoundarySweepChangesTheGazeOnce() {
        for (edge, outward) in [(CGFloat(150), CGFloat(-1)), (250, 1)] {
            var gaze = gazeFor(pointerX: 200, layout: layout, previous: .center, state: .reading)
            var changes = 0
            for step in 0..<20 {
                let x = edge + (step.isMultiple(of: 2) ? outward : -outward) * 2   // ±2 pt around the edge
                let next = gazeFor(pointerX: x, layout: layout, previous: gaze, state: .reading)
                if next != gaze { changes += 1 }
                gaze = next
            }
            XCTAssertEqual(changes, 1, "edge \(edge)")
        }
    }

    func test_leavingASideTakesAWholeCell() {
        XCTAssertEqual(gazeFor(pointerX: 153, layout: layout, previous: .left, state: .awake), .left)
        XCTAssertEqual(gazeFor(pointerX: 156, layout: layout, previous: .left, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: 246, layout: layout, previous: .right, state: .awake), .right)
        XCTAssertEqual(gazeFor(pointerX: 244, layout: layout, previous: .right, state: .awake), .center)
    }
}
```

`Tests/CicadaAppTests/WormAnswersTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z §6.3 — the answer ladder. A click steps through true lines; a rung
/// whose facts are unknown is omitted; no rung repeats the status sentence's
/// numeral; nothing reads a clock (R8).
final class WormAnswersTests: XCTestCase {

    private let en = Locale(identifier: "en_US")
    private let last = LastCycleFacts(episodes: 12, created: 3, updated: 5, durationText: "4 m 12 s")

    private func ctx(_ mood: BookwormState, _ edit: (inout RoomContext) -> Void = { _ in }) -> RoomContext {
        var c = RoomContext(mood: mood,
                            debt: SleepDebtView(restedPct: 60, volumePct: 0, agePct: 0, unprocessedCount: 47,
                                                hasRunBefore: true, hoursSinceLastCycle: 30),
                            scheduleMode: "daily", locale: en)
        c.oldestWait = "3 days"; c.lampLit = true; c.nextRunWhen = "Sep 24, 3:00 AM"
        c.lastCycle = last; c.inboxTotal = 2
        edit(&c)
        return c
    }

    func test_readingAsksWhatWhenLastTimeAndYou() {
        let rungs = wormAnswers(ctx(.reading))
        XCTAssertEqual(rungs.map(\.lead), ["Waiting for a night.", "Next: Sep 24, 3:00 AM.",
                                           "Last time I read 12 episodes.", "2 questions wait for you."])
        XCTAssertEqual(rungs[0].tail, "The oldest has waited 3 days.")
        XCTAssertEqual(rungs[2].tail, "+3 new · 5 updated, in 4 m 12 s.")
        XCTAssertEqual(rungs[2].action, .openDetails(.pastNights))
        XCTAssertEqual(rungs[3].tail, "They're in the Inbox.")
        XCTAssertEqual(rungs[3].action, .openInbox, "spec decision 16 — the last rung may point to the Inbox")
    }

    func test_theWhenRung_namesTheScheduledEngineOnlyWhenItDiffers() {
        XCTAssertNil(wormAnswers(ctx(.happy))[1].tail)
        XCTAssertNil(wormAnswers(ctx(.happy))[1].mark)
        let differs = wormAnswers(ctx(.happy) { $0.scheduledEngine = "ollama" })
        XCTAssertEqual(differs[1].tail, "Scheduled runs use Ollama (on this Mac).")
        XCTAssertEqual(differs[1].mark, .engine("ollama"), "a named engine wears its mark (Z-P26)")
    }

    func test_theLampOffRungPointsAtTheLamp() {
        let rung = wormAnswers(ctx(.reading) { $0.lampLit = false; $0.nextRunWhen = nil })[1]
        XCTAssertEqual(rung.lead, "The lamp is off — I read when you ask.")
        XCTAssertEqual(rung.action, .openLamp)
    }

    func test_unknownFactsOmitTheirRung() {
        let sparse = wormAnswers(ctx(.happy) { $0.nextRunWhen = nil; $0.lastCycle = nil; $0.inboxTotal = 0 })
        XCTAssertEqual(sparse.map(\.lead), ["Nothing to read."])
        let noEpisodes = wormAnswers(ctx(.happy) {
            $0.lastCycle = LastCycleFacts(episodes: 0, created: 0, updated: 0, durationText: nil)
        })
        XCTAssertFalse(noEpisodes.contains { $0.lead.hasPrefix("Last time") }, "0 is an older backend's unknown")
        let noDuration = wormAnswers(ctx(.happy) { $0.lastCycle = LastCycleFacts(episodes: 1, created: 0, updated: 2, durationText: nil) })
        XCTAssertEqual(noDuration[2].lead, "Last time I read 1 episode.")
        XCTAssertEqual(noDuration[2].tail, "+0 new · 2 updated.")
        XCTAssertEqual(wormAnswers(ctx(.happy) { $0.inboxTotal = 1 }).last?.lead, "1 question waits for you.")
    }

    func test_whileSleepingItNamesTheStageAndTheEngine() {
        let rungs = wormAnswers(ctx(.sleeping(stage: 2)) {
            $0.activeStage = 2; $0.lastEngine = "claude-cli"; $0.engineDetail = "your plan is connected"
        })
        XCTAssertEqual(rungs.map(\.lead), ["Stage 2 · Sort.", "Running on Claude Code (your plan)."])
        XCTAssertEqual(rungs[0].tail, SleepStages.all[1].detail)
        XCTAssertEqual(rungs[1].tail, "Your plan is connected.")
        XCTAssertEqual(rungs[1].mark, .engine("claude-cli"))
    }

    func test_digestingErrorAndAwake() {
        let digesting = wormAnswers(ctx(.digesting) { $0.cycleCreated = 4; $0.cycleUpdated = 9 })
        XCTAssertEqual(digesting.first?.lead, "Just filed that cycle.")
        XCTAssertEqual(digesting.first?.tail, "+4 new · 9 updated.")
        XCTAssertEqual(digesting.count, 2)
        let error = wormAnswers(ctx(.error) { $0.cycleError = "claude exited 1"; $0.lastEngine = "ollama" })
        XCTAssertEqual(error.map(\.lead), ["The last cycle failed.", "It ran on Ollama (on this Mac).",
                                           "Last time I read 12 episodes."])
        XCTAssertEqual(error[0].action, .openDetails(.lastCycle))
        XCTAssertEqual(wormAnswers(ctx(.awake)).map(\.lead), ["I haven't heard from Cicada yet."])
    }

    /// R-Z7 — answers never restate the figure the status sentence shows.
    func test_noRungRepeatsTheStatusNumeral() {
        let c = ctx(.reading)
        let numeral = roomSentence(c).numeral!
        for rung in wormAnswers(c) { XCTAssertFalse(rung.spoken.contains(numeral), rung.spoken) }
    }

    func test_everyRungFitsAndSaysNothingItMayNot() {
        for mood in [BookwormState.awake, .happy, .reading, .hungry, .digesting, .error, .sleeping(stage: 4)] {
            for rung in wormAnswers(ctx(mood) { $0.activeStage = 4; $0.lastEngine = "litellm"; $0.cycleError = "boom" }) {
                XCTAssertLessThanOrEqual(rung.lead.count, SentenceLine.maxLead, rung.lead)
                XCTAssertLessThanOrEqual(rung.tail?.count ?? 0, SentenceLine.maxTail)
                XCTAssertFalse(rung.spoken.contains("!") || rung.spoken.contains("%") || rung.spoken.contains("~"))
            }
        }
    }

    /// R8 — clock-free, by construction and by grep.
    func test_isDeterministicAndClockFree() throws {
        XCTAssertEqual(wormAnswers(ctx(.reading)), wormAnswers(ctx(.reading)))
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "WormAnswers.swift" }!
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("Date("))
        XCTAssertFalse(text.contains(".now"))
    }
}
```

`Tests/CicadaAppTests/RoomModelTests.swift`:

```swift
import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §8 — the room's interaction state: the ladder's stepping, the
/// perk's rate limit, beats gated by the matrix and by Reduce Motion, and a
/// pointer that writes only what changed.
@MainActor
final class RoomModelTests: XCTestCase {

    private let scene = deskSceneLayout(pointSize: 120, uiScale: 1.0)
    private var spots: [DeskHotspot: CGRect] { deskHotspots(scene) }
    /// Top-left points (what `onContinuousHover` reports) at 5 pt cells.
    private let overWorm = CGPoint(x: 200, y: 70)
    private let overLamp = CGPoint(x: 20, y: 100)

    func test_theLadderStepsThroughThenReturnsToTheStatus() {
        XCTAssertEqual(RoomModel.nextAnswerIndex(after: nil, count: 3), 0)
        XCTAssertEqual(RoomModel.nextAnswerIndex(after: 1, count: 3), 2)
        XCTAssertNil(RoomModel.nextAnswerIndex(after: 2, count: 3), "one click past the last rung")
        XCTAssertNil(RoomModel.nextAnswerIndex(after: nil, count: 0))
    }

    func test_aPokeTalks_exceptInWordsOnlyStates() {
        let room = RoomModel()
        XCTAssertEqual(room.poke(answerCount: 2, state: .happy, reduceMotion: false), 0)
        XCTAssertEqual(room.reaction?.kind, .talk)
        let quiet = RoomModel()
        _ = quiet.poke(answerCount: 2, state: .error, reduceMotion: false)
        XCTAssertNil(quiet.reaction, "error answers in words only (§6.4)")
        let still = RoomModel()
        _ = still.poke(answerCount: 2, state: .happy, reduceMotion: true)
        XCTAssertNil(still.reaction, "Reduce Motion: no beats")
        XCTAssertEqual(still.answerIndex, 0, "…but the answer still shows")
    }

    func test_thePerkIsRateLimited() {
        let t0 = Date(timeIntervalSinceReferenceDate: 1_000)
        XCTAssertTrue(RoomModel.shouldPerk(lastPerkAt: nil, now: t0))
        XCTAssertFalse(RoomModel.shouldPerk(lastPerkAt: t0, now: t0.addingTimeInterval(1.9)))
        XCTAssertTrue(RoomModel.shouldPerk(lastPerkAt: t0, now: t0.addingTimeInterval(SleepMotion.perkCooldown)))
    }

    func test_reachingTheWormPerksOnce_andTheGazeFollows() {
        let room = RoomModel()
        let t0 = Date(timeIntervalSinceReferenceDate: 1_000)
        room.pointer(at: overLamp, scene: scene, spots: spots, state: .awake, now: t0, reduceMotion: false)
        XCTAssertTrue(room.pointerInRoom)
        XCTAssertEqual(room.gaze, .left)
        XCTAssertNil(room.reaction)
        room.pointer(at: overWorm, scene: scene, spots: spots, state: .awake, now: t0, reduceMotion: false)
        XCTAssertEqual(room.gaze, .center)
        XCTAssertEqual(room.reaction?.kind, .perk)
        let first = room.reaction?.id
        room.pointer(at: overLamp, scene: scene, spots: spots, state: .awake, now: t0.addingTimeInterval(0.5), reduceMotion: false)
        room.pointer(at: overWorm, scene: scene, spots: spots, state: .awake, now: t0.addingTimeInterval(1), reduceMotion: false)
        XCTAssertEqual(room.reaction?.id, first, "within the cooldown, no second perk")
        room.pointer(at: nil, scene: scene, spots: spots, state: .awake, now: t0, reduceMotion: false)
        XCTAssertFalse(room.pointerInRoom)
        XCTAssertEqual(room.gaze, .center)
    }

    func test_aSleepingWormNeverPerks() {
        let room = RoomModel()
        room.pointer(at: overWorm, scene: scene, spots: spots, state: .sleeping(stage: 2), now: .now, reduceMotion: false)
        XCTAssertNil(room.reaction)
    }

    func test_dismissReturnsToTheStatus() {
        let room = RoomModel()
        _ = room.poke(answerCount: 3, state: .happy, reduceMotion: true)
        room.dismissAnswers()
        XCTAssertNil(room.answerIndex)
    }
}
```

`SleepNumbersLintTests.swift` — extend `testEveryNamedDurationIsInsideTheBudget` and
`testReduceMotionRemovesEveryTransition`, and add the two lints:

```swift
    // in testEveryNamedDurationIsInsideTheBudget:
        XCTAssertLessThanOrEqual(SleepMotion.sentenceDuration, SleepMotion.maxDuration)
        XCTAssertLessThanOrEqual(SleepMotion.beatFrameInterval * Double(SleepMotion.maxBeatFrames),
                                 SleepMotion.maxDuration)
        XCTAssertEqual(SleepMotion.beatFrameInterval, BookwormSprites.reactionInterval,
                       "one beat clock — the sprite's and the page's")
        XCTAssertEqual(SleepMotion.answerDwell, .seconds(12))

    // in testReduceMotionRemovesEveryTransition:
        XCTAssertNil(SleepMotion.sentence(reduceMotion: true))
        XCTAssertNotNil(SleepMotion.sentence(reduceMotion: false))

    /// Design §10 — the pointer is read in ONE place under `Views/Sleep/`, the
    /// room box (`StudyRoom.swift`); every other leaf observes the model.
    func testOnlyTheRoomReadsTheContinuousPointer() throws {
        var readers: [String] = []
        for file in try Self.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let hit = text.components(separatedBy: .newlines).contains {
                let code = $0.trimmingCharacters(in: .whitespaces)
                return !code.hasPrefix("//") && code.contains("onContinuousHover")
            }
            if hit { readers.append(file.lastPathComponent) }
        }
        XCTAssertEqual(readers, ["StudyRoom.swift"])
    }

    /// R-Z4 — all worm motion is sprite frames on the one lattice: no
    /// `.offset`, `.scaleEffect`, `.rotationEffect` or `.spring(` hangs off a
    /// `BookwormView(` or `WormStage(` under `Views/Sleep/`. The one allowed
    /// form is the lattice placement itself — an `.offset(` built from
    /// `wormOrigin`, which is a whole number of cells by construction.
    func testTheWormIsNeverTransformed() throws {
        var chains = 0
        for file in try Self.sleepSources() {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            var i = 0
            while i < lines.count {
                let code = lines[i].trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains("BookwormView(") || code.contains("WormStage(") else {
                    i += 1; continue
                }
                // The call itself (to its closing paren), then every following
                // line that is a modifier (starts with ".") or a comment.
                var chain = [lines[i]]
                var depth = lines[i].filter { $0 == "(" }.count - lines[i].filter { $0 == ")" }.count
                i += 1
                while i < lines.count, depth > 0 {
                    chain.append(lines[i])
                    depth += lines[i].filter { $0 == "(" }.count - lines[i].filter { $0 == ")" }.count
                    i += 1
                }
                while i < lines.count {
                    let next = lines[i].trimmingCharacters(in: .whitespaces)
                    guard next.hasPrefix(".") || next.hasPrefix("//") else { break }
                    chain.append(lines[i]); i += 1
                }
                chains += 1
                for line in chain where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                    for needle in [".scaleEffect(", ".rotationEffect(", ".spring("] {
                        XCTAssertFalse(line.contains(needle), "\(file.lastPathComponent): \(line)")
                    }
                    if line.contains(".offset(") {
                        XCTAssertTrue(line.contains("wormOrigin"), "\(file.lastPathComponent): \(line)")
                    }
                }
            }
        }
        XCTAssertGreaterThan(chains, 0, "found no worm — the lint would pass vacuously")
    }
```

- [ ] **Step 2: Implement.**

`Views/Sleep/SleepMotion.swift` — add (their names mirror M1's `CicadaMotion`):

```swift
    /// One beat frame (R-Z12) — pinned equal to `BookwormSprites.reactionInterval`.
    static let beatFrameInterval: TimeInterval = 0.12
    /// Every beat is at most three frames, so ≤ 0.36 s ≤ `maxDuration`.
    static let maxBeatFrames = 3
    /// The status ⇄ answer cross-fade in the sentence slot (opacity only).
    static let sentenceDuration: TimeInterval = 0.18
    /// A rate limit, not an animation: one perk per two seconds however the
    /// pointer wanders in and out of the worm.
    static let perkCooldown: TimeInterval = 2
    /// A dwell, not an animation: an answer returns to the status sentence
    /// after this long with the pointer outside the room and the sentence.
    static let answerDwell: Duration = .seconds(12)

    static func sentence(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: sentenceDuration)
    }
```

`Views/Sleep/DeskSceneSprites.swift` — beside `rowBand`:

```swift
    /// The window's glass, in its own grid (rows 4…19, cols 2…17 — jambs and
    /// mullions included, the frame occludes them). Named once: the window
    /// hotspot (Track Z §6.2) and the weather pane (§7.3) both sit on it.
    static let windowGlass = (rows: 4...19, cols: 2...17)
```

`Views/Sleep/DeskHotspots.swift`:

```swift
import CoreGraphics

/// The room's three hotspots (Track Z §6.2). Spines are their own buttons
/// inside `BookPileView` — their frames are SwiftUI layout, not lattice cells
/// (Z-P14).
enum DeskHotspot: Hashable, CaseIterable {
    case worm, lamp, window
}

enum DeskHotspots {
    /// The worm's ink span on the scene lattice: the 20 columns `DeskScene`
    /// lines up with the cushion (scene cols 30…49), and the worm box's full
    /// height (rows 4…27), cap and hop included.
    static let wormCols = (DeskScene.wormCell.x + 2)...(DeskScene.wormCell.x + 21)
    static let wormRows = DeskScene.wormCell.y...(DeskScene.wormCell.y + BookwormSprites.size - 1)
    /// The glasses' bridge (grid row 7, col 12) in scene cells — the invariant
    /// test's anchor for "the eyes are inside the worm".
    static let eyeCell = (col: DeskScene.wormCell.x + 12, row: DeskScene.wormCell.y + BookwormSprites.size - 1 - 7)
}

/// Whole-cell rectangles in points, bottom-leading origin — the same space
/// `DeskSceneLayout` uses — derived from cells, never from typed points, so
/// the hotspot layer cannot drift from the art (R-Z8).
func deskHotspots(_ layout: DeskSceneLayout) -> [DeskHotspot: CGRect] {
    let last = BookwormSprites.size - 1
    func rect(cols: ClosedRange<Int>, rows: ClosedRange<Int>) -> CGRect {
        CGRect(x: CGFloat(cols.lowerBound) * layout.cell, y: CGFloat(rows.lowerBound) * layout.cell,
               width: CGFloat(cols.count) * layout.cell, height: CGFloat(rows.count) * layout.cell)
    }
    var spots: [DeskHotspot: CGRect] = [.worm: rect(cols: DeskHotspots.wormCols, rows: DeskHotspots.wormRows)]
    if let lamp = layout.layers.first(where: { $0.prop == .lamp }),
       let ink = DeskSceneSprites.inkBounds(DeskSceneSprites.lampLit) {
        spots[.lamp] = rect(cols: (lamp.cellX + ink.cols.lowerBound)...(lamp.cellX + ink.cols.upperBound),
                            rows: (lamp.cellY + last - ink.rows.upperBound)...(lamp.cellY + last - ink.rows.lowerBound))
    }
    if let window = layout.layers.first(where: { $0.prop == .window }) {
        let glass = DeskSceneSprites.windowGlass
        // Clipped where the worm starts, so the two never overlap (§6.2).
        let lastCol = min(window.cellX + glass.cols.upperBound, DeskHotspots.wormCols.lowerBound - 1)
        spots[.window] = rect(cols: (window.cellX + glass.cols.lowerBound)...lastCol,
                              rows: (window.cellY + last - glass.rows.upperBound)...(window.cellY + last - glass.rows.lowerBound))
    }
    return spots
}

/// `onContinuousHover` reports top-left points; the scene is bottom-leading.
func sceneBottomLeading(_ point: CGPoint, in layout: DeskSceneLayout) -> CGPoint {
    CGPoint(x: point.x, y: layout.size.height - point.y)
}

/// Where the worm looks for a pointer at `pointerX` (Track Z §6.2). Left of
/// the worm's ink → `.left`, right of it → `.right`, over it → `.center`,
/// with one cell of hysteresis: leaving a side takes a whole cell, so a sweep
/// back and forth across an edge changes the gaze at most once. States whose
/// eyes must not move (§6.4) always look ahead. Named `gazeFor`, not `gaze`,
/// because `RoomModel.gaze` would shadow it (Z-P22).
func gazeFor(pointerX: CGFloat?, layout: DeskSceneLayout, previous: Gaze, state: BookwormState) -> Gaze {
    guard state.acceptsGaze, let x = pointerX else { return .center }
    let left = CGFloat(DeskHotspots.wormCols.lowerBound) * layout.cell
    let right = CGFloat(DeskHotspots.wormCols.upperBound + 1) * layout.cell
    switch previous {
    case .left where x < left + layout.cell: return .left
    case .right where x >= right - layout.cell: return .right
    default: break
    }
    if x < left { return .left }
    if x >= right { return .right }
    return .center
}
```

`Views/Sleep/RoomModel.swift`:

```swift
import CoreGraphics
import Foundation
import Observation

/// The room's own interaction state (Track Z §6, §8).
///
/// Observation scoping is the performance budget (§10): `gaze` and
/// `pointerInRoom` are written only when they CHANGE (about two writes per
/// sweep), and only `WormStage` and the sentence slot read them, so the
/// page's body never re-evaluates for a moving pointer. The perk's
/// bookkeeping is `@ObservationIgnored` — nothing draws it.
@Observable
@MainActor
final class RoomModel {
    var gaze: Gaze = .center
    var pointerInRoom = false
    var reaction: ActiveReaction?
    /// `nil` = the status sentence; otherwise the answer rung on show (§6.3).
    var answerIndex: Int?
    var pointerInSentence = false

    @ObservationIgnored private var pointerInWorm = false
    @ObservationIgnored private var lastPerkAt: Date?

    /// I1 + I2 — one call per hover event from `StudyRoom`'s one
    /// `onContinuousHover`. `location` is top-left, in the room's space.
    func pointer(at location: CGPoint?, scene: DeskSceneLayout, spots: [DeskHotspot: CGRect],
                 state: BookwormState, now: Date = Date(), reduceMotion: Bool) {
        let inRoom = location != nil
        if pointerInRoom != inRoom { pointerInRoom = inRoom }
        let next = gazeFor(pointerX: location?.x, layout: scene, previous: gaze, state: state)
        if next != gaze { gaze = next }
        let inWorm = location.map { point in
            spots[.worm]?.contains(sceneBottomLeading(point, in: scene)) ?? false
        } ?? false
        guard inWorm != pointerInWorm else { return }
        pointerInWorm = inWorm
        guard inWorm, Self.shouldPerk(lastPerkAt: lastPerkAt, now: now),
              play(.perk, state: state, now: now, reduceMotion: reduceMotion) else { return }
        lastPerkAt = now
    }

    /// I3 — steps the ladder and plays the talk beat (sleep-talk while
    /// sleeping, none in words-only states). Returns the rung now showing, or
    /// `nil` when the click went past the last one (back to the status).
    @discardableResult
    func poke(answerCount: Int, state: BookwormState, now: Date = Date(), reduceMotion: Bool) -> Int? {
        answerIndex = Self.nextAnswerIndex(after: answerIndex, count: answerCount)
        if answerIndex != nil { play(.talk, state: state, now: now, reduceMotion: reduceMotion) }
        return answerIndex
    }

    /// I4 — Esc, a mood change, the dwell.
    func dismissAnswers() {
        if answerIndex != nil { answerIndex = nil }
    }

    /// Starts a beat if §6.4 allows it for `state` and Reduce Motion is off.
    @discardableResult
    func play(_ kind: BookwormReaction, state: BookwormState, now: Date = Date(), reduceMotion: Bool) -> Bool {
        guard Self.beatAllowed(kind, state: state, reduceMotion: reduceMotion) else { return false }
        reaction = ActiveReaction(kind: kind, startedAt: now, id: UUID())
        return true
    }

    /// Clears a beat once its frames have played (≤ 0.36 s, R-Z12) — unless a
    /// newer beat replaced it meanwhile.
    func settleReaction() async {
        guard let playing = reaction else { return }
        try? await Task.sleep(for: .seconds(SleepMotion.beatFrameInterval * Double(SleepMotion.maxBeatFrames)))
        if reaction?.id == playing.id { reaction = nil }
    }

    static func nextAnswerIndex(after current: Int?, count: Int) -> Int? {
        guard count > 0 else { return nil }
        guard let current else { return 0 }
        return current + 1 < count ? current + 1 : nil
    }

    static func shouldPerk(lastPerkAt: Date?, now: Date) -> Bool {
        guard let lastPerkAt else { return true }
        return now.timeIntervalSince(lastPerkAt) >= SleepMotion.perkCooldown
    }

    static func beatAllowed(_ kind: BookwormReaction, state: BookwormState, reduceMotion: Bool) -> Bool {
        !reduceMotion && state.allows(kind)
    }
}
```

`Views/Sleep/RoomSentence.swift` — `RoomContext` gains, after `locale`:

```swift
    // Task 6 — facts only the answer ladder reads (§6.3). Each is nil when
    // unknown, and a rung whose fact is nil is omitted.
    var oldestWait: String? = nil
    var lampLit: Bool = false
    /// "Sep 24, 3:00 AM", or "after the next import settles"; nil when unknown.
    var nextRunWhen: String? = nil
    /// The scheduled engine's id, only when it differs from manual (ruling 4).
    /// An id rather than the sentence, so the rung can draw its mark.
    var scheduledEngine: String? = nil
    var lastCycle: LastCycleFacts? = nil
    var cycleCreated: Int = 0
    var cycleUpdated: Int = 0
    var lastEngine: String? = nil
    var engineDetail: String? = nil
    var inboxTotal: Int? = nil
```

`Views/Sleep/WormAnswers.swift`:

```swift
import Foundation

/// The facts of one past cycle an answer names (from `lastCycleEntry`, Z-P3).
struct LastCycleFacts: Equatable {
    let episodes: Int
    let created: Int
    let updated: Int
    /// `SleepHistoryPresentation.durationText`, or `nil` when no measured
    /// duration joined — the clause is dropped, never estimated (G107).
    let durationText: String?

    init(episodes: Int, created: Int, updated: Int, durationText: String?) {
        self.episodes = episodes; self.created = created; self.updated = updated
        self.durationText = durationText
    }

    init(_ entry: SleepHistoryEntry) {
        self.init(episodes: entry.episodes, created: entry.entitiesCreated, updated: entry.entitiesUpdated,
                  durationText: entry.durationMs.map { SleepHistoryPresentation.durationText(ms: $0) })
    }
}

/// The answer ladder (Track Z §6.3): what the worm says when clicked, one rung
/// per click, back to the status sentence after the last. Pure and clock-free
/// (R8): ages and dates arrive already resolved by the page. A rung whose
/// facts are unknown is omitted; no rung restates the status numeral (R-Z7);
/// every rung obeys R-Z13's budgets.
func wormAnswers(_ ctx: RoomContext) -> [SentenceLine] {
    let rungs: [SentenceLine?]
    switch ctx.mood {
    case .reading, .hungry, .curious:
        rungs = [SentenceLine(lead: "Waiting for a night.", tail: ctx.oldestWait.map { "The oldest has waited \($0)." }),
                 whenRung(ctx), lastTimeRung(ctx), inboxRung(ctx)]
    case .happy:
        rungs = [SentenceLine(lead: "Nothing to read.", tail: "Everything captured has been filed."),
                 whenRung(ctx), lastTimeRung(ctx), inboxRung(ctx)]
    case .sleeping:
        let stage = SleepStages.all[max(1, min(SleepStages.all.count, ctx.activeStage ?? 1)) - 1]
        rungs = [SentenceLine(lead: "\(stage.title).", numeral: "\(stage.number)", tail: stage.detail),
                 engineRung(ctx, verb: "Running on")]
    case .digesting:
        rungs = [SentenceLine(lead: "Just filed that cycle.",
                              tail: "+\(count(ctx.cycleCreated, ctx)) new · \(count(ctx.cycleUpdated, ctx)) updated."),
                 whenRung(ctx)]
    case .error:
        let clause = sentenceClause(ctx.cycleError)
        rungs = [SentenceLine(lead: "The last cycle failed.", tone: .danger, tail: clause, tailTone: .danger,
                              action: clause == nil ? nil : .openDetails(.lastCycle)),
                 engineRung(ctx, verb: "It ran on"), lastTimeRung(ctx)]
    case .awake:
        rungs = [SentenceLine(lead: "I haven't heard from Cicada yet.", tail: "This fills in as soon as it answers.")]
    }
    return rungs.compactMap { $0 }.filter {
        $0.lead.count <= SentenceLine.maxLead && ($0.tail?.count ?? 0) <= SentenceLine.maxTail
    }
}

private func count(_ n: Int, _ ctx: RoomContext) -> String { UsageFormat.count(n, locale: ctx.locale) }

/// Rung 2 — when. Lamp off: say so and point at the lamp.
private func whenRung(_ ctx: RoomContext) -> SentenceLine? {
    guard ctx.lampLit else {
        return SentenceLine(lead: "The lamp is off — I read when you ask.",
                            tail: "Press Consolidate now, or light the lamp.", action: .openLamp)
    }
    guard let when = ctx.nextRunWhen else { return nil }
    return SentenceLine(lead: "Next: \(when).", numeral: when,
                        tail: ctx.scheduledEngine.map { "\(Copy.scheduledRunsOn(engine: $0))." },
                        mark: ctx.scheduledEngine.map { SentenceMark.engine($0) })
}

/// Rung 3 — last time. `episodes == 0` is an older backend's default, an
/// unknown rather than a fact, so the rung is omitted.
private func lastTimeRung(_ ctx: RoomContext) -> SentenceLine? {
    guard let last = ctx.lastCycle, last.episodes > 0 else { return nil }
    let n = count(last.episodes, ctx)
    let tail = "+\(count(last.created, ctx)) new · \(count(last.updated, ctx)) updated"
        + (last.durationText.map { ", in \($0)" } ?? "") + "."
    return SentenceLine(lead: "Last time I read \(n) \(last.episodes == 1 ? "episode" : "episodes").",
                        numeral: n, tail: tail, action: .openDetails(.pastNights))
}

/// Rung 4 — you (spec decision 16: the last rung may point to the Inbox).
private func inboxRung(_ ctx: RoomContext) -> SentenceLine? {
    guard let n = ctx.inboxTotal, n > 0 else { return nil }
    if n == 1 {
        return SentenceLine(lead: "1 question waits for you.", numeral: "1", tail: "It's in the Inbox.", action: .openInbox)
    }
    let numeral = count(n, ctx)
    return SentenceLine(lead: "\(numeral) questions wait for you.", numeral: numeral,
                        tail: "They're in the Inbox.", action: .openInbox)
}

private func engineRung(_ ctx: RoomContext, verb: String) -> SentenceLine? {
    guard let engine = ctx.lastEngine else { return nil }
    return SentenceLine(lead: "\(verb) \(Copy.engineLabel(engine)).",
                        tail: sentenceCase(sentenceClause(ctx.engineDetail)),
                        mark: .engine(engine))
}
```

`SleepPageModel.swift` — append four stored properties after `topOrigin`: `lastEngine: String?`,
`engineDetail: String?`, `cycleCreated: Int`, `cycleUpdated: Int`. `resolve` passes
`status?.lastEngine`, `status?.engineDetail`, `status?.entitiesCreated ?? 0` and
`status?.entitiesUpdated ?? 0` as the last four memberwise arguments, in that order. Then
`roomContext` becomes:

```swift
extension SleepPageModel {
    /// The sentence's and the answers' inputs (Track Z §5, §6.3), from this one reading.
    func roomContext(locale: Locale = .autoupdatingCurrent) -> RoomContext {
        var context = RoomContext(mood: mood, debt: debt, queueLoad: queueLoad, activeStage: runningStage,
                                  read: read, total: total, cycleError: cycleError, cancelled: cancelled,
                                  capped: capped, indexWarning: indexWarning, scheduleMode: schedule.mode,
                                  topOriginLabel: topOriginLabel, topOrigin: topOrigin, locale: locale)
        context.oldestWait = oldestWait
        context.lampLit = lampLit
        context.nextRunWhen = nextRunAt ?? (schedule.mode == "after_import" ? "after the next import settles" : nil)
        context.scheduledEngine = scheduledEngine
        context.lastCycle = lastCycle.map { LastCycleFacts($0) }
        context.cycleCreated = cycleCreated
        context.cycleUpdated = cycleUpdated
        context.lastEngine = lastEngine
        context.engineDetail = engineDetail
        context.inboxTotal = inboxTotal
        return context
    }
}
```

(This replaces Task 3's `roomContext` whole. The first statement is Task 3's call.)

`SleepPageModelTests` gains:

```swift
    /// Task 6 — the answer ladder's facts come from the same one reading.
    func test_theRoomContextCarriesTheAnswerFacts() throws {
        let json = #"{"status":"idle","lastEngine":"ollama","engineDetail":"running locally","entitiesCreated":4,"entitiesUpdated":9,"debt":{"unprocessedCount":2,"hasRunBefore":true,"volumePct":0,"agePct":0,"restedPct":80}}"#
        let context = resolve(status: try status(json)).roomContext()
        XCTAssertEqual(context.lastEngine, "ollama")
        XCTAssertEqual(context.engineDetail, "running locally")
        XCTAssertEqual(context.cycleCreated, 4)
        XCTAssertEqual(context.cycleUpdated, 9)
        let afterImport = resolve(status: try status(idleJSON),
                                  schedule: ScheduleConfig(mode: "after_import", hour: 3, minute: 0))
        XCTAssertEqual(afterImport.roomContext().nextRunWhen, "after the next import settles",
                       "after-import with no date still has a when")
        XCTAssertTrue(afterImport.roomContext().lampLit)
        XCTAssertNil(resolve(status: try status(idleJSON)).roomContext().nextRunWhen, "manual has no when")
        let previews = SleepEnginePreviews(manual: SleepEnginePreview(engine: "claude-cli", model: "m", why: "w"),
                                           scheduled: SleepEnginePreview(engine: "ollama", model: "m", why: "w"))
        XCTAssertEqual(resolve(status: try status(idleJSON), preview: previews).roomContext().scheduledEngine, "ollama")
    }
```

`Views/Sleep/StudyRoom.swift`:

```swift
import SwiftUI

/// VoiceOver's order through the default view (Track Z §11): the sentence,
/// the worm, the window, the lamp, the spines (largest first), the control,
/// the whisper line, then Details. One table, read by every element that
/// sets a priority, so the order can be reviewed in one place.
///
/// **Two levels, because a sort priority only orders siblings inside one
/// accessibility container.** The room card is a `.contain` container
/// (sentence → room → control → whisper; the strip, when shown, keeps the
/// default 0 and reads last). The room is its own `.contain` container inside
/// it (worm → window → lamp → the pile's container, whose spines order
/// themselves largest first). Details sits **outside** the card and carries
/// no priority, so it follows in document order. A priority of 1 on it would
/// sort it ahead of the page title and the whole card, because the page's
/// `VStack` is not a container.
enum RoomA11yOrder {
    // Inside the room card.
    static let sentence: Double = 4
    static let room: Double = 3
    static let control: Double = 2
    static let whisper: Double = 1
    // Inside the room.
    static let worm: Double = 4
    static let window: Double = 3
    static let lamp: Double = 2
    static let spines: Double = 1
}

extension View {
    /// The room's one pointer cue (§8): a link cursor over things that do
    /// something — `pointerStyle(.link)` on macOS 15+, the pointing hand
    /// pushed and popped on macOS 14. Inert props never get it (R-Z2).
    @ViewBuilder
    func roomLinkCursor() -> some View {
        if #available(macOS 15, *) {
            self.pointerStyle(.link)
        } else {
            self.onHover { inside in
                if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
            }
        }
    }
}

/// The study room (G125 v3 → Track Z v4): the inert art (`DeskSceneView`),
/// the worm on its lattice, the real pile, and — separately — the hotspot
/// layer derived from the same pure layout (R-Z8). The ONE reader of the
/// continuous pointer under `Views/Sleep/` (`SleepNumbersLintTests`); it
/// writes the model and reads nothing from it, so its own body never
/// re-evaluates for a moving pointer.
struct StudyRoom: View {
    let page: SleepPageModel
    let statusLine: SentenceLine
    let answers: [SentenceLine]
    let room: RoomModel

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let scene = deskSceneLayout(pointSize: SleepView.wormPointSize)
        let spots = deskHotspots(scene)
        ZStack(alignment: .bottomLeading) {
            DeskSceneView(pointSize: SleepView.wormPointSize, lampLit: page.lampLit)
            WormStage(mood: page.mood, room: room, pointSize: SleepView.wormPointSize)
                .offset(x: scene.wormOrigin.x, y: -scene.wormOrigin.y)   // R-Z4: the lattice placement, whole cells
            BookPileView(books: page.books)
                .frame(width: scene.pileFrame.width, height: scene.pileFrame.height, alignment: .bottomLeading)
                .offset(x: scene.pileFrame.minX, y: -scene.pileFrame.minY)
            if let worm = spots[.worm] {
                WormHotspot(mood: page.mood, bracket: sleepDebtBracketText(page.mood, debt: page.debt),
                            help: statusLine.spoken, answers: answers, room: room)
                    .frame(width: worm.width, height: worm.height)
                    .offset(x: worm.minX, y: -worm.minY)
            }
        }
        .frame(width: scene.size.width, height: scene.size.height, alignment: .bottomLeading)
        .onContinuousHover(coordinateSpace: .local) { phase in
            switch phase {
            case .active(let location):
                room.pointer(at: location, scene: scene, spots: spots, state: page.mood, reduceMotion: reduceMotion)
            case .ended:
                room.pointer(at: nil, scene: scene, spots: spots, state: page.mood, reduceMotion: reduceMotion)
            }
        }
        .accessibilityElement(children: .contain)
    }
}

/// The worm and nothing else — the one leaf that reads the pointer's gaze
/// and the beat (§10), so a moving pointer redraws only this. Inert: the
/// hotspot above it takes the clicks.
struct WormStage: View {
    let mood: BookwormState
    let room: RoomModel
    let pointSize: CGFloat

    var body: some View {
        BookwormView(state: mood, pointSize: pointSize, caption: nil,
                     pose: room.pointerInRoom ? .attentive(room.gaze) : .idle,
                     reaction: room.reaction)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
            .task(id: room.reaction?.id) { await room.settleReaction() }
    }
}

/// The worm's hotspot (I2, I3; §11): click, Space or Return pokes; Esc
/// dismisses while it has focus (Z-P15); VoiceOver's default action pokes and
/// "What are you doing?" reads every rung at once. The bracket line (P8)
/// lives on as this element's VALUE.
struct WormHotspot: View {
    let mood: BookwormState
    let bracket: String
    let help: String
    let answers: [SentenceLine]
    let room: RoomModel

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Color.clear
            .contentShape(Rectangle())
            .onTapGesture { poke() }
            .focusable()
            .onKeyPress(.space) { poke(); return .handled }
            .onKeyPress(.return) { poke(); return .handled }
            .onKeyPress(.escape) {
                guard room.answerIndex != nil else { return .ignored }
                room.dismissAnswers()
                // I4 — Esc is the one dismissal the person caused, so it is
                // the one that announces: the status sentence is back.
                AccessibilityNotification.Announcement(help).post()
                return .handled
            }
            .roomLinkCursor()
            .help(help)
            .contextMenu { Button(Copy.wormWhatAreYouDoing) { announceAll() } }
            .accessibilityElement()
            .accessibilityLabel("Bookworm, \(mood.title)")
            .accessibilityValue(bracket)
            .accessibilityHint(Copy.wormHint)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { poke() }
            .accessibilityAction(named: Copy.wormWhatAreYouDoing) { announceAll() }
            .accessibilitySortPriority(RoomA11yOrder.worm)
    }

    /// Announcements fire only for what the person caused (§11).
    private func poke() {
        if let index = room.poke(answerCount: answers.count, state: mood, reduceMotion: reduceMotion) {
            AccessibilityNotification.Announcement(answers[index].spoken).post()
        }
    }

    private func announceAll() {
        AccessibilityNotification.Announcement(answers.map(\.spoken).joined(separator: " ")).post()
    }
}
```

`RoomSentenceView` (Task 3's view) gains, declared right after `line` (so the memberwise order is
`line, answers, room, canPerform, perform`), `var answers: [SentenceLine] = []` and
`var room: RoomModel? = nil`, plus `@Environment(\.accessibilityReduceMotion) private var reduceMotion`;
its `body` shows `room?.answerIndex.flatMap { answers.indices.contains($0)
? answers[$0] : nil } ?? line` as `shown`. **Every read of `line` inside the view switches to
`shown`**: the runs in `leadText`, the tail and its link in `tailView`, `.accessibilityLabel`, and
the `.accessibilityActions` action. Otherwise VoiceOver would keep reading the status while an
answer is on screen, and the action would follow the wrong link. The view keys the text on `shown` with `.id(shown)` +
`.transition(.opacity)` inside a container animated by
`.animation(SleepMotion.sentence(reduceMotion: reduceMotion), value: shown)`, sets
`.onHover { room?.pointerInSentence = $0 }` and `.accessibilitySortPriority(RoomA11yOrder.sentence)`,
and runs the dwell:

```swift
        .task(id: DwellKey(index: room?.answerIndex,
                           inside: (room?.pointerInRoom ?? false) || (room?.pointerInSentence ?? false))) {
            // I4 — an answer returns to the status after `answerDwell` with
            // the pointer outside the room and the sentence; any re-entry
            // restarts this task, which is what "paused while hovered" means.
            guard let room, room.answerIndex != nil,
                  !room.pointerInRoom, !room.pointerInSentence else { return }
            try? await Task.sleep(for: SleepMotion.answerDwell)
            guard !Task.isCancelled else { return }
            room.dismissAnswers()
        }
```

with `private struct DwellKey: Equatable { let index: Int?; let inside: Bool }` in the same file.

`Views/Sleep/SleepView.swift`:
- `@State private var room = RoomModel()`.
- `roomCard(_ page:)`: compute `let context = page.roomContext()`, `let status = roomSentence(context)`,
  `let answers = wormAnswers(context)`; the room `ZStack` is replaced by
  `StudyRoom(page: page, statusLine: status, answers: answers, room: room)` (the old ZStack's
  scene-group `.accessibilityLabel(sleepDebtBracketText(...))` is deleted — the bracket line is the
  worm's value now); `RoomSentenceView(line: status, answers: answers, room: room, canPerform:
  …, perform: …)`.
- `canPerform` adds `.openInbox`; `perform` handles it with `selectedTab = .inbox`.
- The room card's `VStack` gains `.accessibilityElement(children: .contain)`. Inside it,
  `StudyRoom(...)` gets `.accessibilitySortPriority(RoomA11yOrder.room)`, `SleepControlRow(...)`
  gets `RoomA11yOrder.control` and the whisper row gets `RoomA11yOrder.whisper`. The sentence
  sets its own priority. `detailsDisclosure` gets **no** priority (see `RoomA11yOrder`'s
  docstring for why).
- `.onChange(of: page.mood.caseName) { _, _ in room.dismissAnswers() }` — I4: a mood change resets
  the ladder. (Place it on the `ScrollViewReader`'s content, where `page` is in scope.)

`Theme/Copy.swift`:

```swift
    /// The worm's accessibility hint (Track Z §11). The design's second clause
    /// ("Drop a file to import it.") lands with feeding — a hint must be true
    /// the day it ships (Z-P16).
    static let wormHint = "Click to ask what it's doing."
    /// The worm's named action and context-menu item: every answer at once.
    static let wormWhatAreYouDoing = "What are you doing?"
```

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures.
  Then prove both new lints can fail: add `.scaleEffect(1.01)` on the line after `WormStage(…)` in
  `StudyRoom.swift` → `swift test --filter SleepNumbersLintTests` must FAIL; revert. Add a stray
  `.onContinuousHover { _ in }` to `SleepView.swift` → must FAIL; revert. Re-run green.
- [ ] **Step 4: Commit** — `feat(sleep v4): the room responds — gaze, perk, and a worm that answers (G125 v4, R-Z4, R-Z8, R-Z12)`.

---

### Task 7 (Z6): The props become controls — spines, the lamp, the whisper line

Each spine becomes a button that opens its source's queue (a popover of up to six episodes, "+N
more in Details", "Open in Sources ›"); hovering a spine tints its Details row and hovering a row
lifts its spine. The lamp and the whisper line open one popover that shows the scheduled engine and
its reason **before** a labelled toggle can flip the schedule (R-Z9, ruling 4). No click on art
starts, cancels or schedules a cycle by itself.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SpinePopover.swift` — `SpinePopover`, `spinePopoverRows`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/LampPopover.swift` — `LampPopover`, `LampEngineLine`, `lampEngineLine`, `lampAccessibilityLabel`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/BookPile.swift` — `SpineButton`; `BookPileView(books:rows:episodes:room:onOpenDetails:)`; `.contain` "The pile, N sources"; `pileAccessibilityLabel`, `spineAccessibilityLabel`, `spineHelp`; `CicadaTheme.onFill` replaces `.white` (`:149`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift` — `queueRowWords`; `rowAccessibilityLabel`'s `.waiting` case says "waiting" and names the oldest age; rows hover-link through `room.hoveredOrigin`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyRoom.swift` — the lamp hotspot button + popover; `BookPileView` gets its rows, episodes, room and `onOpenDetails`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomModel.swift` — `hoveredOrigin`, `hover(origin:inside:)`, `lampPopover: LampAnchor?`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — the whisper row becomes a button that opens the popover (its "Change…" link and the scheduled-engine note leave — the popover carries both); `.openLamp` becomes performable; `StudyRoom` gets `episodes` and `onOpenDetails`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepDetails.swift` — passes `room` to `StudyListCard`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMotion.swift` — `hoverDuration`, `hover(reduceMotion:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/SleepViewModel.swift` — injectable `putSchedule`; `updateSchedule` returns `Bool` (Z-P18)
- Modify: `app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift` — `pendingSourceDetail`, `routeToSourceDetail(_:)`, `consumeSourceDetail()`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourcesPageView.swift` — consumes `pendingSourceDetail`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift` — `onFill` (Z-P19), one accessor beside `pendingPulse` (`:155`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — the lamp and spine strings below
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/SpineAndLampTests.swift`
- Test (extend): `AppRouterTests.swift` (stage + consume once), `SleepViewModelTests.swift` (the schedule write's outcome), `SleepNumbersLintTests.swift` (`hoverDuration` in budget, `hover` nil under Reduce Motion), `RoomModelTests.swift` (an out-of-order hover exit)

**Interfaces:**
- Produces: `SpineButton`; `pileAccessibilityLabel(sourceCount:)`, `spineAccessibilityLabel(spec:row:)`, `spineHelp(spec:row:)`, `queueRowWords(_:locale:)`, `spinePopoverRows(origin:in:limit:)`; `LampAnchor`, `LampEngineLine`, `lampEngineLine(preview:lampLit:)`, `lampAccessibilityLabel(lampLit:scheduleText:nextRunText:)`, `LampPopover(page:)`; `RoomModel.hoveredOrigin` / `.hover(origin:inside:)` / `.lampPopover`; `AppRouter.pendingSourceDetail` / `routeToSourceDetail(_:)` / `consumeSourceDetail()`; `SleepViewModel.updateSchedule(_:) -> Bool` (`@discardableResult`), `init(…putSchedule:)`; `CicadaTheme.onFill`; `SleepMotion.hoverDuration` / `hover(reduceMotion:)`.
- Consumes: Task 1's `ScheduleToggle`, `episodesForOrigin`, `SourceOverview.owning`; Task 5's `roomLinkCursor`; `SettingsSectionLink`; `EngineMark`.

- [ ] **Step 1: Failing tests.** `Tests/CicadaAppTests/SpineAndLampTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z §7 — the room's props as controls. Every label, help string and
/// popover line is a pure function, so what a spine or the lamp SAYS can be
/// read against what it does.
final class SpineAndLampTests: XCTestCase {

    private let en = Locale(identifier: "en_US")
    private let idleRow = StudyRow(origin: "claude-code", label: "Claude Code", count: 12, oldestAge: "3d", read: nil, total: nil)
    private let runningRow = StudyRow(origin: "claude-code", label: "Claude Code", count: 12, oldestAge: "3d", read: 4, total: 12)
    private let spine = BookSpec(origin: "claude-code", count: 12, height: 20, widthFraction: 1, isRemainder: false)
    private let remainder = BookSpec(origin: "+more", count: 4, height: 10, widthFraction: 1, isRemainder: true)

    // MARK: Spines (§7.1, I5)

    func test_thePileNamesHowManySources_notHowManyBooks() {
        XCTAssertEqual(pileAccessibilityLabel(sourceCount: 1), "The pile, 1 source")
        XCTAssertEqual(pileAccessibilityLabel(sourceCount: 3), "The pile, 3 sources")
    }

    func test_aSpineSaysWhatItsRowSays() {
        XCTAssertEqual(StudyListCard.rowAccessibilityLabel(idleRow), "Claude Code, 12 waiting, oldest 3d")
        XCTAssertEqual(spineAccessibilityLabel(spec: spine, row: idleRow), StudyListCard.rowAccessibilityLabel(idleRow))
        XCTAssertEqual(spineAccessibilityLabel(spec: remainder, row: nil), "4 more on the pile, in Details")
    }

    func test_aSpinesHelpIsItsNumbersWithTheirNouns() {
        XCTAssertEqual(spineHelp(spec: spine, row: idleRow, locale: en), "Claude Code · 12 waiting · oldest 3d")
        XCTAssertEqual(spineHelp(spec: spine, row: runningRow, locale: en), "Claude Code · 4 of 12 read")
        XCTAssertEqual(spineHelp(spec: remainder, row: nil, locale: en), "4 more on the pile, in Details")
    }

    func test_queueRowWords() {
        XCTAssertEqual(queueRowWords(.waiting(1234), locale: en), "1,234 waiting")
        XCTAssertEqual(queueRowWords(.reading(read: 4, total: 12, fill: 0.33), locale: en), "4 of 12 read")
        XCTAssertEqual(queueRowWords(.done, locale: en), "all read")
        XCTAssertEqual(queueRowWords(.nextCycle, locale: en), "next cycle")
    }

    private func episode(_ id: String, _ origin: String, day: Int) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: Data(
            #"{"id":"\#(id)","timestamp":"2026-09-\#(String(format: "%02d", day))T00:00:00Z","source":"x","origin":"\#(origin)","preview":"","processed":false}"#.utf8))
    }

    func test_thePopoverShowsSixNewestAndCountsTheRest() throws {
        let all = try (1...9).map { try episode("e\($0)", "claude-code", day: $0) } + [try episode("r", "rss", day: 20)]
        let shown = spinePopoverRows(origin: "claude-code", in: all)
        XCTAssertEqual(shown.rows.map(\.id), ["e9", "e8", "e7", "e6", "e5", "e4"])
        XCTAssertEqual(shown.more, 3)
        XCTAssertEqual(spinePopoverRows(origin: "rss", in: all).more, 0)
    }

    /// Design defect 7 / Z-P19 — spine text is a theme token, never `.white`.
    func test_thePileSpellsNoLiteralWhite() throws {
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "BookPile.swift" }!
        XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains(".white"))
    }

    // MARK: The lamp (§7.2, I8–I10)

    private func previews(scheduled: String, why: String) -> SleepEnginePreviews {
        SleepEnginePreviews(manual: SleepEnginePreview(engine: "claude-cli", model: "m", why: "your plan"),
                            scheduled: SleepEnginePreview(engine: scheduled, model: "m", why: why))
    }

    /// Ruling 4 at the moment of choice: the scheduled engine and its reason
    /// are ALWAYS on screen in the popover — before any flip, lit or not.
    func test_theEngineLineIsShownBeforeTheToggleCanFlip() {
        let lit = lampEngineLine(preview: previews(scheduled: "ollama", why: "Ollama is running — using the local engine"), lampLit: true)
        XCTAssertEqual(lit?.engine, "ollama")
        XCTAssertEqual(lit?.text, "Scheduled runs use Ollama (on this Mac). Ollama is running — using the local engine.")
        let dark = lampEngineLine(preview: previews(scheduled: "litellm", why: "scheduled cycle — Sleep engine selection is user-triggered only"), lampLit: false)
        XCTAssertEqual(dark?.text, "If you light it, scheduled runs would use API key. Scheduled cycle — Sleep engine selection is user-triggered only.")
        XCTAssertNil(lampEngineLine(preview: nil, lampLit: true), "absent until the preview loads — never guessed")
    }

    func test_theLampSaysItsStateInWords() {
        XCTAssertEqual(lampAccessibilityLabel(lampLit: true, scheduleText: "Every day at 03:00", nextRunText: "Next run Sep 24, 3:00 AM"),
                       "Lamp, on. Every day at 03:00. Next run Sep 24, 3:00 AM.")
        XCTAssertEqual(lampAccessibilityLabel(lampLit: false, scheduleText: Copy.nextRunManual, nextRunText: Copy.nextRunManual),
                       "Lamp, off. Sleep runs only when you ask.")
    }
}
```

`AppRouterTests.swift` — add:

```swift
    /// Track Z §7.1 — a spine's "Open in Sources ›" stages the tab AND the
    /// source together, and the Sources page consumes it exactly once.
    func testRouteToSourceDetailStagesTheTabAndTheSourceOnce() {
        let router = AppRouter()
        router.routeToSourceDetail("harness:claude-code")
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertEqual(router.consumeSourceDetail(), "harness:claude-code")
        XCTAssertNil(router.pendingSourceDetail)
        XCTAssertNil(router.consumeSourceDetail())
    }
```

`SleepViewModelTests.swift` — add:

```swift
    /// Z-P18 — the lamp's toggle snaps back on a failed write, so the write
    /// must say whether it landed. A failure leaves the schedule untouched.
    func test_updateSchedule_reportsItsOutcome() async throws {
        struct Boom: Error {}
        let store = idleStore()
        let failing = SleepViewModel(store: store, putSchedule: { _ in throw Boom() })
        let before = failing.schedule
        let failed = await failing.updateSchedule(ScheduleConfig(mode: "daily", hour: 3, minute: 0))
        XCTAssertFalse(failed)
        XCTAssertEqual(failing.schedule, before)
        XCTAssertNotNil(failing.errorMessage)
        let working = SleepViewModel(store: store, putSchedule: { $0 })
        let landed = await working.updateSchedule(ScheduleConfig(mode: "daily", hour: 3, minute: 0))
        XCTAssertTrue(landed)
        XCTAssertEqual(working.schedule.mode, "daily")
    }
```

`SleepNumbersLintTests.swift`: add `XCTAssertLessThanOrEqual(SleepMotion.hoverDuration,
SleepMotion.maxDuration)` and the `hover(reduceMotion:)` nil / non-nil pair.

- [ ] **Step 2: Implement.**

`Theme/CicadaTheme.swift` — beside `pendingPulse`:

```swift
    /// Text drawn ON an identity-hue fill (a Sleep book spine, Track Z Z-P19).
    /// Mode-independent on purpose: the fill is an origin's own colour, not a
    /// theme surface, so the text on it does not flip with the theme.
    static var onFill: Color { .white }
```

`ViewModels/SleepViewModel.swift`:

```swift
    private let putSchedule: (ScheduleConfig) async throws -> ScheduleConfig
    // init gains, last:
    //   putSchedule: @escaping (ScheduleConfig) async throws -> ScheduleConfig = {
    //       try await APIClient.shared.updateSchedule($0)
    //   }

    /// Writes the schedule and says whether it landed (Track Z Z-P18): the Sleep
    /// lamp's toggle snaps back with a caption on `false`. Settings and
    /// onboarding ignore the result, as before.
    @discardableResult
    func updateSchedule(_ new: ScheduleConfig) async -> Bool {
        do {
            schedule = try await putSchedule(new)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
```

`Support/AppRouter.swift` — beside `pendingAddSource`:

```swift
    /// Track Z §7.1 — a Sleep spine's "Open in Sources ›". The source id rides
    /// with the tab switch, like the Feed hand-off, and `SourcesPageView`
    /// consumes it once it is on screen.
    var pendingSourceDetail: String?

    func routeToSourceDetail(_ sourceID: String) {
        pendingTab = .sources
        pendingSourceDetail = sourceID
        activateMainWindow()
    }

    /// Read-then-clear, for the same double-firing reason as `consumeAddSource`.
    @discardableResult
    func consumeSourceDetail() -> String? {
        defer { pendingSourceDetail = nil }
        return pendingSourceDetail
    }
```

`Views/Sources/SourcesPageView.swift`: `@Environment(AppRouter.self) private var router`; on the
outer `VStack`, `.onAppear { openPendingSource() }` and
`.onChange(of: router.pendingSourceDetail) { _, _ in openPendingSource() }`, with:

```swift
    /// Track Z §7.1 — land on the source a Sleep spine named. A source id that
    /// no longer resolves (the overview changed underneath) leaves the grid
    /// showing rather than guessing a neighbour.
    private func openPendingSource() {
        guard let id = router.consumeSourceDetail(), let source = rows.first(where: { $0.id == id }) else { return }
        route = .detail(source)
    }
```

`Views/Sleep/StudyListCard.swift`:

```swift
/// A queue row's state in words (Track Z §7.1) — the spine popover's header,
/// and the same nouns the row prints: `waiting` idle, `read` while running.
func queueRowWords(_ state: QueueRowState, locale: Locale = .autoupdatingCurrent) -> String {
    switch state {
    case .waiting(let n): "\(UsageFormat.count(n, locale: locale)) waiting"
    case .reading(let read, let total, _):
        "\(UsageFormat.count(read, locale: locale)) of \(UsageFormat.count(total, locale: locale)) read"
    case .done: "all read"
    case .nextCycle: "next cycle"
    }
}
```

`rowAccessibilityLabel`'s `.waiting` case becomes
`[ "\(row.label), \(count) waiting", row.oldestAge.map { "oldest \($0)" } ].compactMap { $0 }.joined(separator: ", ")`
(design I5 — the spine and the row speak one sentence). `StudyListCard` gains
`var room: RoomModel? = nil`; each `rowView` gets
`.onHover { inside in room?.hover(origin: row.origin, inside: inside) }` and
`.background(room?.hoveredOrigin == row.origin ? CicadaTheme.surfaceHover : Color.clear,
in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))` (I7).

`Views/Sleep/BookPile.swift`:

```swift
/// "The pile, 3 sources" — the container names SOURCES, not a book total: the
/// sentence already says how many are waiting (R-Z7).
func pileAccessibilityLabel(sourceCount: Int) -> String {
    "The pile, \(sourceCount) \(sourceCount == 1 ? "source" : "sources")"
}

/// A spine speaks its row's sentence (I5); the folded remainder says where
/// its books are.
func spineAccessibilityLabel(spec: BookSpec, row: StudyRow?) -> String {
    guard let row, !spec.isRemainder else { return "\(spec.count) more on the pile, in Details" }
    return StudyListCard.rowAccessibilityLabel(row)
}

/// The spine's tooltip — its numbers with their nouns (I5). Also reachable by
/// click (the popover) and VoiceOver, so it is never hover-only (§11).
func spineHelp(spec: BookSpec, row: StudyRow?, locale: Locale = .autoupdatingCurrent) -> String {
    guard let row, !spec.isRemainder else { return spineAccessibilityLabel(spec: spec, row: row) }
    switch queueRowState(row) {
    case .waiting:
        return ([row.label, queueRowWords(queueRowState(row), locale: locale)]
                + (row.oldestAge.map { ["oldest \($0)"] } ?? [])).joined(separator: " · ")
    default:
        return "\(row.label) · \(queueRowWords(queueRowState(row), locale: locale))"
    }
}
```

`BookPileView` becomes:

```swift
struct BookPileView: View {
    let books: [BookSpec]
    var rows: [StudyRow] = []
    var episodes: [EpisodeQueueItem] = []
    var room: RoomModel? = nil
    var onOpenDetails: (DetailsSection) -> Void = { _ in }

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// The gap above each spine — part of that spine's hit target (§6.2), so
    /// an 8 pt spine is still comfortable to click (Z-P14).
    static let spineGap: CGFloat = 2
    static let maxSpineWidth: CGFloat = 150

    var body: some View {
        let byOrigin = Dictionary(rows.map { ($0.origin, $0) }, uniquingKeysWith: { first, _ in first })
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Self.stacked(books)) { spec in
                if spec.widthFraction > 0 {
                    SpineButton(spec: spec, row: byOrigin[spec.origin], episodes: episodes, room: room,
                                onOpenDetails: onOpenDetails)
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

    static func stacked(_ books: [BookSpec]) -> [BookSpec] { Array(books.reversed()) }
}

/// One spine as a control (Track Z §7.1): a click opens its source's queue —
/// the folded remainder opens Details › What's waiting instead (Z-P20).
/// Hover lifts it 2 pt (a SwiftUI shape, not pixel art — R-Z4 is about the
/// worm) and tints its Details row through `room.hoveredOrigin` (I5, I7).
struct SpineButton: View {
    let spec: BookSpec
    let row: StudyRow?
    let episodes: [EpisodeQueueItem]
    let room: RoomModel?
    let onOpenDetails: (DetailsSection) -> Void

    @State private var hovering = false
    @State private var showPopover = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let lifted = hovering || room?.hoveredOrigin == spec.origin
        Button {
            if spec.isRemainder || row == nil { onOpenDetails(.waiting) } else { showPopover = true }
        } label: {
            shape(lifted: lifted)
                .padding(.top, BookPileView.spineGap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { inside in
            hovering = inside
            room?.hover(origin: spec.origin, inside: inside)
        }
        .roomLinkCursor()
        .help(spineHelp(spec: spec, row: row))
        .accessibilityLabel(spineAccessibilityLabel(spec: spec, row: row))
        .popover(isPresented: $showPopover, arrowEdge: .trailing) {
            if let row {
                SpinePopover(row: row, episodes: episodes) {
                    showPopover = false
                    onOpenDetails(.waiting)
                }
            }
        }
    }

    private func shape(lifted: Bool) -> some View {
        let color = spec.isRemainder ? CicadaTheme.textTertiary.opacity(0.4) : OriginIconography.color(for: spec.origin)
        return ZStack(alignment: .leading) {
            RoundedRectangle(cornerRadius: 3)
                .fill(color)
                .frame(width: BookPileView.maxSpineWidth * spec.widthFraction, height: spec.height)
            if spec.height >= 14 {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if !spec.isRemainder { OriginMark(origin: spec.origin, size: 12) }
                    Text("\(spec.count)")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.onFill)
                }
                .padding(.horizontal, CicadaTheme.spacingXS)
            }
        }
        // Resting at 0.85 is today's look (the colour used to carry the
        // opacity); a lift is full strength, and 2 pt up unless Reduce Motion.
        .opacity(spec.isRemainder || lifted ? 1 : 0.85)
        .offset(y: lifted && !reduceMotion ? -2 : 0)
        .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: lifted)
    }
}
```

`Views/Sleep/SpinePopover.swift`:

```swift
import SwiftUI

/// Up to `limit` of an origin's queued episodes, newest first, and how many
/// more there are (Track Z §7.1) — the same order `episodesForOrigin` gives
/// the Details row, so the two can never disagree.
func spinePopoverRows(origin: String, in episodes: [EpisodeQueueItem], limit: Int = 6)
    -> (rows: [EpisodeQueueItem], more: Int) {
    let all = episodesForOrigin(origin, in: episodes)
    return (Array(all.prefix(limit)), max(0, all.count - limit))
}

/// A spine's popover (§7.1): the source's mark, name and state in words, the
/// oldest age, its newest episodes, then the two ways further — Details for
/// the rest, Sources for the source's own page (hidden when no source owns
/// the origin, never guessed).
struct SpinePopover: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    let row: StudyRow
    let episodes: [EpisodeQueueItem]
    let onOpenDetails: () -> Void

    var body: some View {
        let shown = spinePopoverRows(origin: row.origin, in: episodes)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: row.origin, size: 18)
                Text(row.label)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: 0)
                Text(queueRowWords(queueRowState(row)))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if let age = row.oldestAge {
                Text("oldest \(age)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(shown.rows) { EpisodeRow(item: $0) }
            HStack {
                if shown.more > 0 {
                    Button(Copy.moreInDetails(shown.more), action: onOpenDetails)
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                }
                Spacer(minLength: 0)
                if let source = SourceOverview.owning(origin: row.origin, in: store.sourcesOverview.value ?? []) {
                    Button(Copy.openInSources) { router.routeToSourceDetail(source.id) }
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                }
            }
            .font(CicadaTheme.captionFont)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 360)
        .background(CicadaTheme.surface)
    }
}
```

`Views/Sleep/LampPopover.swift`:

```swift
import SwiftUI

/// Which control presented the lamp's popover (Z-P25) — one popover, two
/// anchors: the lamp art and its text twin, the whisper line.
enum LampAnchor: Equatable { case lamp, whisper }

struct LampEngineLine: Equatable {
    let engine: String
    let text: String
}

/// The engine a scheduled run uses, and why — shown ALWAYS in the popover,
/// lit or not, before the toggle can flip (ruling 4 at the moment of choice,
/// §7.2). `nil` until the preview loads; never guessed.
func lampEngineLine(preview: SleepEnginePreviews?, lampLit: Bool) -> LampEngineLine? {
    guard let scheduled = preview?.scheduled else { return nil }
    let lead = lampLit ? Copy.scheduledRunsOn(engine: scheduled.engine)
                       : Copy.scheduledRunsWouldUse(engine: scheduled.engine)
    let why = sentenceCase(scheduled.why).map { " \($0)" } ?? ""
    return LampEngineLine(engine: scheduled.engine, text: "\(lead).\(why)")
}

/// I8 — the lamp's VoiceOver label: its state, in words.
func lampAccessibilityLabel(lampLit: Bool, scheduleText: String, nextRunText: String) -> String {
    lampLit ? "Lamp, on. \(scheduleText). \(nextRunText)." : "Lamp, off. Sleep runs only when you ask."
}

/// "When I read" (§7.2). The lamp art never previews: it flips only when
/// `sleepVM.schedule` changes (P11). The toggle writes through the ONE rule
/// (`ScheduleToggle`), is disabled while its write is in flight, and on a
/// failed write snaps back to the schedule the backend still has, with a
/// caption (Z-P18). Rhythm and time stay in Settings → Sleep (G125 (4)).
struct LampPopover: View {
    @Environment(SleepViewModel.self) private var sleepVM
    let page: SleepPageModel

    /// The value in flight, or `nil`.
    @State private var writing: Bool?
    @State private var failed = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.whenIRead.uppercased())
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: page.lampLit ? "circle.fill" : "circle")
                    .font(CicadaTheme.font(size: 9))
                    .foregroundStyle(page.lampLit ? CicadaTheme.accent : CicadaTheme.textTertiary)
                Text(page.lampLit ? Copy.lampOn : Copy.lampOff)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                Spacer(minLength: CicadaTheme.spacingMD)
                Toggle(Copy.readOnSchedule, isOn: Binding(
                    get: { writing ?? ScheduleToggle.isOn(sleepVM.schedule) },
                    set: { write($0) }))
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .disabled(writing != nil)
            }
            Text(page.lampLit ? whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText, lampLit: true)
                              : Copy.lampOffExplainer)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            if let line = lampEngineLine(preview: sleepVM.enginePreview, lampLit: page.lampLit) {
                HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
                    EngineMark(engine: line.engine, size: 12)
                    Text(line.text)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if failed {
                Text(Copy.scheduleWriteFailed)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
            }
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.rhythmAndTime)
                    .foregroundStyle(CicadaTheme.textTertiary)
                SettingsSectionLink(section: .sleep, label: "\(Copy.settingsSleep) ›")
            }
            .font(CicadaTheme.captionFont)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 360, alignment: .leading)
        .background(CicadaTheme.surface)
    }

    private func write(_ on: Bool) {
        writing = on
        failed = false
        Task { @MainActor in
            let landed = await sleepVM.updateSchedule(ScheduleToggle.toggled(on: on, current: sleepVM.schedule))
            failed = !landed
            writing = nil
        }
    }
}
```

`Views/Sleep/RoomModel.swift` — add `var hoveredOrigin: String?`, `var lampPopover: LampAnchor?`
and:

```swift
    /// I5 / I7 — one spine or row reports the pointer. An exit clears the
    /// highlight only if it still names this origin: moving from row A to
    /// row B can deliver B's enter BEFORE A's exit, and a plain
    /// `inside ? origin : nil` would then wipe B's highlight.
    func hover(origin: String, inside: Bool) {
        if inside {
            if hoveredOrigin != origin { hoveredOrigin = origin }
        } else if hoveredOrigin == origin {
            hoveredOrigin = nil
        }
    }
```

`RoomModelTests` gains:

```swift
    /// I5 / I7 — an out-of-order exit never clears the neighbour's highlight.
    func test_hoverSurvivesAnOutOfOrderExit() {
        let room = RoomModel()
        room.hover(origin: "claude-code", inside: true)
        room.hover(origin: "rss", inside: true)
        room.hover(origin: "claude-code", inside: false)
        XCTAssertEqual(room.hoveredOrigin, "rss")
        room.hover(origin: "rss", inside: false)
        XCTAssertNil(room.hoveredOrigin)
    }
```

`Views/Sleep/StudyRoom.swift` — `StudyRoom` gains `let episodes: [EpisodeQueueItem]` and
`let onOpenDetails: (DetailsSection) -> Void`; the pile becomes
`BookPileView(books: page.books, rows: page.rows, episodes: episodes, room: room, onOpenDetails: onOpenDetails)`;
and the lamp hotspot joins the `ZStack` (after the pile, before the worm's hotspot):

```swift
            if let lamp = spots[.lamp] {
                // I8/I9 — the lamp opens the schedule; the art never previews (P11).
                Button { room.lampPopover = .lamp } label: { Color.clear.contentShape(Rectangle()) }
                    .buttonStyle(.cicadaPlain)
                    .frame(width: lamp.width, height: lamp.height)
                    .roomLinkCursor()
                    .help(page.lampLit ? "\(page.scheduleText) · \(page.nextRunText)" : Copy.lampOffExplainer)
                    .accessibilityLabel(lampAccessibilityLabel(lampLit: page.lampLit, scheduleText: page.scheduleText,
                                                               nextRunText: page.nextRunText))
                    .accessibilityHint(Copy.lampHint)
                    .accessibilitySortPriority(RoomA11yOrder.lamp)
                    .popover(isPresented: Binding(get: { room.lampPopover == .lamp },
                                                  set: { if !$0 { room.lampPopover = nil } }),
                             arrowEdge: .top) { LampPopover(page: page) }
                    .offset(x: lamp.minX, y: -lamp.minY)
            }
```

`Views/Sleep/SleepView.swift`:
- `StudyRoom(page:statusLine:answers:room:episodes: sleepVM.queuedEpisodes, onOpenDetails: openDetails)`.
- `whisperRow` becomes one `Button { room.lampPopover = .whisper }` whose label is the `moon.zzz`
  image + the `whisperLine(...)` text; `.buttonStyle(.cicadaPlain)`, the same `.help`, the popover
  bound to `room.lampPopover == .whisper` presenting `LampPopover(page: page)`,
  `.accessibilitySortPriority(RoomA11yOrder.whisper)`. Delete its `SettingsSectionLink` and the
  `scheduledEngineNote` line — the popover carries both, and the engine line there shows always
  (Z-P4's temporary note ends here).
- `canPerform` adds `.openLamp`; `perform` handles it with `room.lampPopover = .lamp` (the sentence
  names the lamp, so the popover points at it — Z-P25).
- `SleepDetails` passes `room: room` into `StudyListCard` (add `var room: RoomModel? = nil` to
  `SleepDetails` and the call).

`Views/Sleep/SleepMotion.swift`:

```swift
    /// A spine lifting under the pointer, and (with feeding) the drop outline.
    static let hoverDuration: TimeInterval = 0.15

    static func hover(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: hoverDuration)
    }
```

`Theme/Copy.swift` (Sleep section):

```swift
    // Track Z §7 — the room's props
    static let whenIRead = "When I read"
    static let lampOn = "The lamp is on."
    static let lampOff = "The lamp is off."
    static let lampOffExplainer = "I read only when you press Consolidate now."
    static let lampHint = "Opens the schedule"
    static let readOnSchedule = "Read on a schedule"
    static let rhythmAndTime = "Rhythm and time:"
    static let scheduleWriteFailed = "Couldn't change the schedule — nothing changed."
    static let openInSources = "Open in Sources ›"
    static func moreInDetails(_ n: Int) -> String { "+\(UsageFormat.count(n)) more in Details" }
    /// The lamp popover's line while the lamp is off (§7.2): what a scheduled
    /// run WOULD use, before the person lights it.
    static func scheduledRunsWouldUse(engine: String) -> String {
        "If you light it, scheduled runs would use \(engineLabel(engine))"
    }
```

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures.
  `grep -rn "sleepVM.triggerManually()\|sleepVM.cancel()" app/CicadaApp/Sources/CicadaApp/Views/Sleep`
  lists `SleepHero.swift` only (R-Z9 — no hotspot starts or cancels a cycle).
- [ ] **Step 4: Commit** — `feat(sleep v4): spines, the lamp and the whisper line become controls (G125 v4, R-Z2, R-Z9)`.

---

### Task 8 (Z7): The completion edge — a cheer and "See what changed ›"

When a real cycle completes (running → idle, not cancelled, no error) the worm cheers once and the
sentence offers **"See what changed ›"**, which opens Details, expands that cycle's history row and
scrolls to it. A cancel or a failure gets neither (I18). The cheer is one of the page's only two
beats not caused by input (R-Z12), and it has a fact behind it: the new commit.

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomModel.swift` — `PendingCompletion`, `recentCycleCommit`, `pendingCompletion`, `cycleStarted()`, `recordCompletion(baseline:at:)`, `resolveCompletion(history:)`, `followWhatChanged()`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepPageModel.swift` — `isRealCompletion(old:new:cancelled:error:)`, `completedCommit(baseline:history:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomSentence.swift` — `RoomContext.recentCycleCommit`; the T7 row; `RoomSentenceView` drops `canPerform` (every action now has a destination — Z-P5's seam ends)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyRoom.swift` — `WormHotspot`'s "What changed" named action while the link lives
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — the edge (`:299-303`), the history observer, `.whatChanged`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — `sleepFinished`, `whatChanged`
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/CompletionEdgeTests.swift`; `RoomSentenceTests` gains the T7 case

**Interfaces:**
- Produces: `isRealCompletion(old:new:cancelled:error:)`, `completedCommit(baseline:history:)`, `PendingCompletion`, `RoomModel.recentCycleCommit` / `.pendingCompletion` / `cycleStarted()` / `recordCompletion(baseline:at:)` / `resolveCompletion(history:) -> String?` / `followWhatChanged() -> String?`; `RoomContext.recentCycleCommit`.
- Consumes: Z-P3's `lastCycleEntry`; `SleepViewModel.expanded` / `loadDetail`; Task 4's `openDetails`.

- [ ] **Step 1: Failing tests.** `Tests/CicadaAppTests/CompletionEdgeTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z §6.5 / I17 / I18 — a real completion cheers once and links to what
/// it changed; a cancel or a failure does neither. The edge and its commit
/// arrive apart (Z-P17): `SleepViewModel`'s poll sets `status` idle BEFORE
/// `load()` refetches history, so the edge records a baseline and the history
/// change that brings a new sleep commit resolves it.
@MainActor
final class CompletionEdgeTests: XCTestCase {

    private func entry(_ hash: String, kind: String = "sleep") throws -> SleepHistoryEntry {
        try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(
            #"{"commitHash":"\#(hash)","date":"2026-09-20","message":"x","kind":"\#(kind)"}"#.utf8))
    }

    func test_onlyARealCompletionCounts() {
        XCTAssertTrue(isRealCompletion(old: "running", new: "idle", cancelled: false, error: nil))
        XCTAssertTrue(isRealCompletion(old: "running", new: "idle", cancelled: false, error: ""))
        XCTAssertFalse(isRealCompletion(old: "running", new: "idle", cancelled: true, error: nil), "a cancel files nothing")
        XCTAssertFalse(isRealCompletion(old: "running", new: "idle", cancelled: false, error: "boom"), "a failure is news, not a cheer")
        XCTAssertFalse(isRealCompletion(old: "idle", new: "idle", cancelled: false, error: nil))
        XCTAssertFalse(isRealCompletion(old: nil, new: "idle", cancelled: false, error: nil), "a first load is not an edge")
    }

    func test_theCommitIsTheNewestSleepCommitThatWasNotThereBefore() throws {
        let before = [try entry("old")]
        let after = [try entry("inbox9", kind: "inbox"), try entry("decay9", kind: "decay"), try entry("c0ffee"), try entry("old")]
        XCTAssertEqual(completedCommit(baseline: "old", history: after), "c0ffee")
        XCTAssertNil(completedCommit(baseline: "old", history: before), "history has not caught up yet")
        XCTAssertEqual(completedCommit(baseline: nil, history: [try entry("first")]), "first", "the bank's first cycle")
    }

    func test_theLinkLivesFromTheCommitToTheClick() throws {
        let room = RoomModel()
        room.recordCompletion(baseline: "old", at: Date())
        XCTAssertNil(room.resolveCompletion(history: [try entry("old")]))
        XCTAssertNotNil(room.pendingCompletion, "still waiting for the commit")
        XCTAssertEqual(room.resolveCompletion(history: [try entry("c0ffee"), try entry("old")]), "c0ffee")
        XCTAssertEqual(room.recentCycleCommit, "c0ffee")
        XCTAssertNil(room.pendingCompletion)
        XCTAssertNil(room.resolveCompletion(history: [try entry("c0ffee")]), "resolves once")
        XCTAssertEqual(room.followWhatChanged(), "c0ffee")
        XCTAssertNil(room.recentCycleCommit, "cleared when clicked")
    }

    func test_theNextCycleClearsTheLinkAndAnyPendingEdge() {
        let room = RoomModel()
        room.recentCycleCommit = "c0ffee"
        room.recordCompletion(baseline: "c0ffee", at: Date())
        room.cycleStarted()
        XCTAssertNil(room.recentCycleCommit)
        XCTAssertNil(room.pendingCompletion)
    }
}
```

`RoomSentenceTests.swift` — add:

```swift
    /// T7 — below the news (T3–T6), above the first-night and state tails.
    func test_T7_seeWhatChanged() {
        let line = roomSentence(ctx(.digesting, debt: debt(0)) { $0.recentCycleCommit = "c0ffee" })
        XCTAssertEqual(line.tail, "See what changed ›")
        XCTAssertEqual(line.action, .whatChanged)
        let warned = roomSentence(ctx(.happy, debt: debt(0)) { $0.recentCycleCommit = "c0ffee"; $0.indexWarning = "w" })
        XCTAssertEqual(warned.tail, "Finished with a warning — it's in Details.", "T6 before T7")
        let firstNight = roomSentence(ctx(.happy, debt: debt(0, hasRunBefore: false)) { $0.recentCycleCommit = "c0ffee" })
        XCTAssertEqual(firstNight.tail, "See what changed ›", "T7 before T9")
    }
```

- [ ] **Step 2: Implement.**

`SleepPageModel.swift` — append:

```swift
/// I17 vs I18 — the one running → idle edge that earns a cheer: not a cancel
/// (it filed nothing) and not a failure (that is news, told in danger). A
/// first observation (`old == nil`) is a page load, not an edge.
func isRealCompletion(old: String?, new: String?, cancelled: Bool, error: String?) -> Bool {
    old == "running" && new == "idle" && !cancelled && (error ?? "").isEmpty
}

/// The commit a completion produced, once history has it: the newest sleep
/// commit that was not the newest before the cycle finished (Z-P17). `nil`
/// while history has not caught up.
func completedCommit(baseline: String?, history: [SleepHistoryEntry]) -> String? {
    guard let newest = lastCycleEntry(history)?.commitHash, newest != baseline else { return nil }
    return newest
}
```

`RoomModel.swift` — add:

```swift
/// A completion seen at the status edge, waiting for its commit (Z-P17).
struct PendingCompletion: Equatable {
    let baseline: String?
    let at: Date
}

    // inside RoomModel:

    /// T7's link target — the commit the last real completion produced.
    /// Cleared on click, when the next cycle starts, and (by construction —
    /// `SleepView` owns this model as `@State`) when the page goes away.
    var recentCycleCommit: String?
    @ObservationIgnored var pendingCompletion: PendingCompletion?

    func recordCompletion(baseline: String?, at date: Date) {
        pendingCompletion = PendingCompletion(baseline: baseline, at: date)
    }

    /// Returns the commit the first time history brings it, else `nil`.
    func resolveCompletion(history: [SleepHistoryEntry]) -> String? {
        guard let pending = pendingCompletion,
              let commit = completedCommit(baseline: pending.baseline, history: history) else { return nil }
        pendingCompletion = nil
        recentCycleCommit = commit
        return commit
    }

    func cycleStarted() {
        pendingCompletion = nil
        if recentCycleCommit != nil { recentCycleCommit = nil }
    }

    /// The link was followed: hand back its commit and clear it.
    func followWhatChanged() -> String? {
        defer { recentCycleCommit = nil }
        return recentCycleCommit
    }
```

`RoomSentence.swift`:
- `RoomContext` gains `var recentCycleCommit: String? = nil` (after `inboxTotal`).
- In `sentenceTail`, replace the "T7 lands with…" comment with:

```swift
    if ctx.recentCycleCommit != nil {                                                             // T7
        return SentenceTail(text: "See what changed ›", action: .whatChanged)
    }
```

- `RoomSentenceView`: delete `canPerform` and every use of it (the tail link and the accessibility
  action render whenever `line.action` is set) — the seam existed only while some destinations did
  not (Z-P5).

`SleepPageModel.roomContext` gains a `recentCycleCommit: String? = nil` parameter and sets it on the
context.

`Views/Sleep/StudyRoom.swift` — `WormHotspot` gains `let whatChanged: (() -> Void)?` (from
`StudyRoom`, which gains `let onWhatChanged: (() -> Void)?`) and:

```swift
            .accessibilityActions {
                if let whatChanged {
                    Button(Copy.whatChanged, action: whatChanged)   // §11 — while T7's link lives
                }
            }
```

`Views/Sleep/SleepView.swift`:
- The edge (`:299-303`) becomes:

```swift
        // G106 amendment + Track Z §6.5 / Z-P17. `justFinishedAt` is stamped on
        // every running → idle edge as before — `deriveSleepPageMood` alone
        // decides that a cancel never chews. A REAL completion additionally
        // records the newest sleep commit it will be compared against, and
        // the history observer below resolves the cheer and the link.
        .onChange(of: sleepVM.status?.status) { oldValue, newValue in
            if oldValue == "running" && newValue == "idle" { justFinishedAt = Date() }
            if newValue == "running" && oldValue != "running" { room.cycleStarted() }
            if isRealCompletion(old: oldValue, new: newValue, cancelled: sleepVM.status?.cancelled == true,
                                error: sleepVM.status?.error) {
                room.recordCompletion(baseline: lastCycleEntry(sleepVM.history)?.commitHash, at: Date())
            }
        }
        .onChange(of: sleepVM.history) { _, history in
            guard room.resolveCompletion(history: history) != nil else { return }
            // R-Z12 — one of the page's two beats not caused by input, and it
            // has a fact behind it. The matrix decides if the mood may cheer
            // now (`.digesting` / `.happy`); the announcement is the twin.
            room.play(.cheer, state: resolvePage().mood, reduceMotion: reduceMotion)
            AccessibilityNotification.Announcement(Copy.sleepFinished).post()
        }
```

- `roomCard`: `page.roomContext(recentCycleCommit: room.recentCycleCommit)`; `StudyRoom(…,
  onWhatChanged: room.recentCycleCommit == nil ? nil : { showWhatChanged() })`; the sentence's
  `perform` handles `.whatChanged` with `showWhatChanged()`.
- Add:

```swift
    /// T7 / I17 — open Details, expand the cycle's history row (its detail
    /// loads through the one cached path), and land on Past nights.
    private func showWhatChanged() {
        guard let commit = room.followWhatChanged() else { return }
        if sleepVM.expanded != commit { toggleHistory(commit) }
        openDetails(.pastNights)
    }
```

`Theme/Copy.swift`: `static let sleepFinished = "Sleep finished."` and
`static let whatChanged = "What changed"`.

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 4: Commit** — `feat(sleep v4): a real completion cheers and links to what it changed (G125 v4, R-Z12, §6.5)`.

---

### Task 9 (Z8): The window shows weather, and the weather is Sleep state

The window splits into a **frame** (today's grid with every glass cell transparent) and a
**pane** behind it that shows one of seven weathers — a total function of the mood and nothing
else (R-Z11): no count, no clock, no stage number. A mood change crossfades the pane (0.4 s, a jump
under Reduce Motion). Clicking the window opens the legend, its text twin. The room now has two
data-driven bits: the lamp (the schedule) and the window (the mood).

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/WindowWeather.swift` — `WindowWeather` (+ `all`, `title`, `meaning`), `windowWeather(for:)`, `WindowLegend`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskSceneSprites.swift` — `DeskProp.pane`; `rowBand[.pane]`; `window` becomes the frame; `pane(_:)` over seven grids; `paneThumbnail(_:)`; `all` and `grid(_:lampLit:weather:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskPalette.swift` — 13 → 20 keys
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskScene.swift` — the pane layer in `plan` (z below the frame); `DeskSceneView(pointSize:lampLit:weather:)` with the crossfade; `cacheKey(_:lampLit:weather:pointSize:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyRoom.swift` — the window hotspot + legend; `DeskSceneView` gets the weather
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/RoomModel.swift` — `legendShown`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMotion.swift` — `weatherDuration`, `weather(reduceMotion:)`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/HowSleepWorks.swift:31-35` — one pointer line to the legend
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` — `windowLegendHeader`, `windowLegendPointer`, `windowHint`
- Test (new): `WindowWeatherTests.swift`, `WindowSpritesTests.swift`
- Test (edit, design §14 Z8): `DeskPaletteTests.swift:19-25` (13 → 20 keys), `DeskSceneSpritesTests.swift:92-102` (the window is a frame now; the moon and the four stars live in the night pane), `DeskSceneLayoutTests.swift` (one new case: the pane sits in the glass, behind the frame); `SleepNumbersLintTests` (`weatherDuration`, `weather(reduceMotion:)`); `DeskHotspotTests.test_theGlassRectangleMatchesTheWorkedGrid` is **deleted** — with the glass gone from the frame it would pass vacuously, and `WindowSpritesTests.test_everyPaneIsGlassOnly_flushToColumnZero_inTheDeskPalette` now proves the same rectangle against the panes

**Interfaces:**
- Produces: `WindowWeather`, `windowWeather(for:)`, `WindowLegend(current:)`; `DeskProp.pane`, `DeskSceneSprites.pane(_:)`, `.paneThumbnail(_:)`; `DeskSceneView(pointSize:lampLit:weather:)`; `SleepMotion.weatherDuration` / `weather(reduceMotion:)`; `RoomModel.legendShown`.
- Consumes: Task 5's `BookwormLook.reachable(for:)` (the occlusion mask); Task 6's `deskHotspots` (`.window`), `windowGlass`, `RoomA11yOrder.window`, `roomLinkCursor`.

- [ ] **Step 1: Failing tests.**

`Tests/CicadaAppTests/WindowWeatherTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track Z R-Z11 — the window is weather, and the weather is state: total
/// over the mood, reading nothing else, listed once, with a legend twin.
final class WindowWeatherTests: XCTestCase {

    func test_everyMoodHasOneWeather_andNoQuantityMovesIt() {
        XCTAssertEqual(windowWeather(for: .awake), .curtains)
        XCTAssertEqual(windowWeather(for: .digesting), .dawn)
        XCTAssertEqual(windowWeather(for: .happy), .clear)
        XCTAssertEqual(windowWeather(for: .reading), .fair)
        XCTAssertEqual(windowWeather(for: .hungry), .overcast)
        XCTAssertEqual(windowWeather(for: .error), .storm)
        for stage in 1...5 { XCTAssertEqual(windowWeather(for: .sleeping(stage: stage)), .night, "the moon never travels") }
        XCTAssertEqual(windowWeather(for: .curious(count: 1)), windowWeather(for: .curious(count: 99)))
    }

    func test_theWeathersAreListedOnce_withDistinctWords() {
        XCTAssertEqual(WindowWeather.all, WindowWeather.allCases)
        XCTAssertEqual(Set(WindowWeather.all.map(\.title)).count, 7)
        XCTAssertEqual(Set(WindowWeather.all.map(\.meaning)).count, 7)
        for weather in WindowWeather.all {
            XCTAssertFalse(weather.meaning.contains("!") || weather.meaning.contains("%"), weather.meaning)
        }
    }

    /// "No weather driven by a count or the clock" (§7.3) — by grep.
    func test_theWeatherReadsNoClock() throws {
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "WindowWeather.swift" }!
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("Date("))
        XCTAssertFalse(text.contains("Calendar"))
    }

    /// P16 — the legend is the ONE list of meanings; the `?` popover points at
    /// it and copies none of it.
    func test_howSleepWorksPointsAtTheLegendWithoutCopyingIt() throws {
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "HowSleepWorks.swift" }!
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("Copy.windowLegendPointer"))
        for weather in WindowWeather.all { XCTAssertFalse(text.contains(weather.meaning), weather.meaning) }
    }
}
```

`Tests/CicadaAppTests/WindowSpritesTests.swift`:

```swift
import AppKit
import XCTest
@testable import CicadaApp

/// Track Z §7.3 / Z-P13 — the window as frame + pane, checked against the REAL
/// worm: the sun, moon, stars and bolt are fully visible beside the worm's
/// union ink over every frame, pose and reaction of the moods that show that
/// weather, and never under a mullion; every cloud is at least half visible.
final class WindowSpritesTests: XCTestCase {

    private struct Cell: Hashable { let r: Int; let c: Int }

    private var paneLayer: DeskLayer { DeskScene.plan.first { $0.prop == .pane }! }
    private var frameLayer: DeskLayer { DeskScene.plan.first { $0.prop == .window }! }

    /// Pane cells the frame paints over (jambs, mullions, sill), in pane space.
    private var frameCells: Set<Cell> {
        let dx = frameLayer.cellX - paneLayer.cellX, dy = paneLayer.cellY - frameLayer.cellY
        var out = Set<Cell>()
        for (r, row) in DeskSceneSprites.window.enumerated() {
            for (c, ch) in row.enumerated() where ch != "." { out.insert(Cell(r: r + dy, c: c + dx)) }
        }
        return out
    }

    /// The worm's union ink, in pane space, over every look of every page mood
    /// that shows `weather` (per weather — Z-P13).
    private func wormMask(for weather: WindowWeather) -> Set<Cell> {
        let moods: [BookwormState] = [.awake, .happy, .reading, .hungry, .digesting, .error] + (1...5).map { .sleeping(stage: $0) }
        let dx = DeskScene.wormCell.x - paneLayer.cellX, dy = paneLayer.cellY - DeskScene.wormCell.y
        var mask = Set<Cell>()
        for mood in moods where windowWeather(for: mood) == weather {
            for look in BookwormLook.reachable(for: mood) {
                for frame in BookwormSprites.frames(for: mood, look: look).frames {
                    for (r, row) in frame.enumerated() {
                        for (c, ch) in row.enumerated() where ch != "." { mask.insert(Cell(r: r + dy, c: c + dx)) }
                    }
                }
            }
        }
        return mask
    }

    /// What must be fully visible, and which characters make a cloud (§7.3).
    private func classes(_ weather: WindowWeather) -> (full: Set<Character>, cloud: Set<Character>) {
        switch weather {
        case .night: (["m", "n", "s"], [])
        case .dawn, .clear: (["m", "n"], [])
        case .fair: (["m", "n"], ["j", "x"])
        case .overcast: ([], ["j", "N"])
        case .storm: (["s"], ["N", "x"])
        case .curtains: ([], [])
        }
    }

    private func cells(_ weather: WindowWeather, _ chars: Set<Character>) -> Set<Cell> {
        var out = Set<Cell>()
        for (r, row) in DeskSceneSprites.pane(weather).enumerated() {
            for (c, ch) in row.enumerated() where chars.contains(ch) { out.insert(Cell(r: r, c: c)) }
        }
        return out
    }

    /// 4-connected groups — one per cloud.
    private func clouds(_ all: Set<Cell>) -> [Set<Cell>] {
        var left = all, groups: [Set<Cell>] = []
        while let seed = left.first {
            left.remove(seed)
            var group: Set<Cell> = [seed], frontier = [seed]
            while let cell = frontier.popLast() {
                for next in [Cell(r: cell.r + 1, c: cell.c), Cell(r: cell.r - 1, c: cell.c),
                             Cell(r: cell.r, c: cell.c + 1), Cell(r: cell.r, c: cell.c - 1)] where left.contains(next) {
                    left.remove(next); group.insert(next); frontier.append(next)
                }
            }
            groups.append(group)
        }
        return groups
    }

    func test_theFeaturesAreFullyVisible_andEveryCloudAtLeastHalf() {
        for weather in WindowWeather.all {
            let hidden = wormMask(for: weather).union(frameCells)
            let (full, cloud) = classes(weather)
            for cell in cells(weather, full) {
                XCTAssertFalse(hidden.contains(cell), "\(weather) \(cell) is hidden")
            }
            for group in clouds(cells(weather, cloud)) {
                let visible = group.subtracting(hidden).count
                XCTAssertGreaterThanOrEqual(visible * 2, group.count, "\(weather) cloud \(visible)/\(group.count)")
            }
        }
    }

    /// Design defect 8: two of the old window's four stars sat behind the worm.
    func test_theNightKeepsFourStars() {
        XCTAssertEqual(cells(.night, ["s"]).count, 4)
    }

    func test_everyPaneIsGlassOnly_flushToColumnZero_inTheDeskPalette() {
        let glass = DeskSceneSprites.windowGlass
        let allowed = Set(DeskPalette.colors.keys).union(["."])
        for weather in WindowWeather.all {
            let pane = DeskSceneSprites.pane(weather)
            XCTAssertEqual(pane.count, 24)
            XCTAssertEqual(DeskSceneSprites.inkBounds(pane)?.rows, glass.rows, "\(weather)")
            XCTAssertEqual(DeskSceneSprites.inkBounds(pane)?.cols, 0...(glass.cols.count - 1), "\(weather)")
            for row in pane {
                XCTAssertEqual(row.count, 24)
                for ch in row where !allowed.contains(ch) { XCTFail("\(weather): '\(ch)'") }
            }
        }
        XCTAssertEqual(Set(WindowWeather.all.map { DeskSceneSprites.pane($0) }).count, 7, "seven different skies")
    }

    /// The frame is today's window with the glass taken out: jambs and
    /// mullions in `f`, the sill in `d`, nothing else.
    func test_theFrameHasNoGlass() {
        let frame = DeskSceneSprites.window
        let glass = DeskSceneSprites.windowGlass
        for r in glass.rows {
            for c in glass.cols {
                let mullion = (9...10).contains(c) || (11...12).contains(r)
                XCTAssertEqual(Array(frame[r])[c], mullion ? "f" : ".", "(\(r),\(c))")
            }
        }
        XCTAssertEqual(frame[22], String(repeating: "d", count: 20) + "....")
    }

    /// Opt-in art check (design §14 Z8):
    /// `CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests`
    /// writes one PNG per weather — frame over pane, with the first frame of
    /// that weather's mood at its real offset — for a person to look at.
    func test_writeCompositesWhenAsked() throws {
        guard ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1" else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-composites")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let moodFor: [WindowWeather: BookwormState] = [.night: .sleeping(stage: 2), .dawn: .digesting, .clear: .happy,
                                                        .fair: .reading, .overcast: .hungry, .storm: .error, .curtains: .awake]
        let palette = DeskPalette.ns.merging(PixelRenderer.nsColors(BookwormPalette.colors)) { desk, _ in desk }
        for weather in WindowWeather.all {
            var grid = Array(repeating: Array(repeating: Character("."), count: 36), count: 36)
            func paint(_ layer: PixelGrid, at dx: Int) {
                for (r, row) in layer.enumerated() {
                    for (c, ch) in row.enumerated() where ch != "." && c + dx < 36 { grid[r][c + dx] = ch }
                }
            }
            paint(DeskSceneSprites.pane(weather), at: 2)
            paint(DeskSceneSprites.window, at: 0)
            paint(BookwormSprites.frames(for: moodFor[weather]!).frames[0], at: 10)
            let image = PixelRenderer.image(grid: grid.map { String($0) }, gridSize: 36, pointSize: 360, palette: palette)
            let rep = NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation))
            try XCTUnwrap(rep?.representation(using: .png, properties: [:]))
                .write(to: dir.appendingPathComponent("\(weather.rawValue).png"))
        }
    }
}
```

`DeskPaletteTests.swift:19-25` becomes `testKeySetIsExactlyTheDocumentedTwenty` with
`["d", "f", "k", "m", "n", "s", "c", "p", "t", "g", "h", "i", "u", "y", "v", "j", "x", "K", "N", "U"]`.
`DeskSceneSpritesTests.swift:92-102` becomes:

```swift
    /// Track Z §7.3 — the window is a frame; the night sky, the hand-drawn
    /// crescent and the four static stars live in the night pane behind it.
    func testTheNightPaneCarriesGlassAMoonAndFourStars() {
        let night = DeskSceneSprites.pane(.night)
        XCTAssertTrue(night.contains { $0.contains("k") }, "night glass")
        XCTAssertTrue(night.contains { $0.contains("m") }, "moonlight")
        XCTAssertTrue(night.contains { $0.contains("n") }, "moon terminator")
        XCTAssertEqual(night.joined().filter { $0 == "s" }.count, 4, "four static stars")
        XCTAssertEqual(DeskSceneSprites.window[22], String(repeating: "d", count: 20) + "....", "the sill")
    }
```

`DeskSceneLayoutTests.swift` — add:

```swift
    /// Track Z §7.3 — the pane sits exactly in the window's glass and BEHIND
    /// the frame, so the mullions occlude it for free (occlusion is the only
    /// depth cue a pixel window has).
    func testThePaneSitsInTheGlassBehindTheFrame() {
        let pane = DeskScene.plan.first { $0.prop == .pane }!
        let window = DeskScene.plan.first { $0.prop == .window }!
        XCTAssertLessThan(pane.z, window.z)
        XCTAssertEqual(pane.cellX, window.cellX + DeskSceneSprites.windowGlass.cols.lowerBound)
        XCTAssertEqual(pane.cellY, window.cellY)
    }
```

- [ ] **Step 2: Implement.**

`Views/Sleep/DeskPalette.swift` — the seven new keys (Meadow §5.1; disjoint from the worm's nine,
none a reserved state hex — `DeskPaletteTests` checks both):

```swift
        "y": 0x8EC3F0,  // day sky (Track Z §7.3)
        "v": 0xD7E8F5,  // horizon haze
        "j": 0xFFFFFF,  // lit cloud — the worm's lens `w` value, a different key
        "x": 0xC9D3DE,  // cloud shade / overcast sky
        "K": 0x2E3440,  // storm sky
        "N": 0x4C566A,  // storm cloud / overcast underside
        "U": 0x7FA7C9,  // rain
```

and the docstring's "13" becomes "20", noting the window's weather pane (R-Z11).

`Views/Sleep/DeskSceneSprites.swift`:
- `enum DeskProp: String, CaseIterable, Hashable { case pane, window, lamp, plant, cushion, mug }`
  (docstring: "…and the window's weather pane, which sits behind the frame (Track Z §7.3)").
- `rowBand` gains `.pane: 4...19`.
- `all` gains `.pane: pane(.night)`; `grid(_:lampLit:)` becomes
  `grid(_ prop: DeskProp, lampLit isLit: Bool, weather: WindowWeather = .night)` with
  `case .pane: return pane(weather)`.
- `window` becomes the frame (its docstring: "the frame, mullions and sill — every glass cell
  transparent; the sky is the pane behind it, Track Z §7.3"):

```swift
    static let window: PixelGrid = [
        "........................",
        "........................",
        "ffffffffffffffffffff....",   // 2  top frame
        "ffffffffffffffffffff....",   // 3
        "ff.......ff.......ff....",   // 4
        "ff.......ff.......ff....",   // 5
        "ff.......ff.......ff....",   // 6
        "ff.......ff.......ff....",   // 7
        "ff.......ff.......ff....",   // 8
        "ff.......ff.......ff....",   // 9
        "ff.......ff.......ff....",   // 10
        "ffffffffffffffffffff....",   // 11 horizontal mullion
        "ffffffffffffffffffff....",   // 12
        "ff.......ff.......ff....",   // 13
        "ff.......ff.......ff....",   // 14
        "ff.......ff.......ff....",   // 15
        "ff.......ff.......ff....",   // 16
        "ff.......ff.......ff....",   // 17
        "ff.......ff.......ff....",   // 18
        "ff.......ff.......ff....",   // 19
        "ffffffffffffffffffff....",   // 20 bottom frame
        "ffffffffffffffffffff....",   // 21
        "dddddddddddddddddddd....",   // 22 sill
        "........................",
    ]
```

- Append the panes. The grids are the Meadow design's (§5.2), shifted two cells left so the ink
  starts at column 0, except overcast's and storm's second clouds (Z-P13 — re-checked against the
  real worm union: 3×3 glyphs in the right pane's free corner):

```swift
    // MARK: - The weather pane (Track Z §7.3, R-Z11)

    /// The sky behind the frame: 16×16 of ink (the window's glass rows 4…19,
    /// cols 2…17), authored flush to column 0 and placed at `cellX: 20`, so the
    /// frame's jambs and mullions occlude it for free. One grid per weather;
    /// the weather is a function of the mood alone. `WindowSpritesTests` proves
    /// the sun, moon, stars and bolt clear the worm's union ink over every
    /// frame, pose and reaction of the moods that show them, and every cloud is
    /// at least half visible.
    static func pane(_ weather: WindowWeather) -> PixelGrid {
        switch weather {
        case .night: nightPane
        case .dawn: dawnPane
        case .clear: clearPane
        case .fair: fairPane
        case .overcast: overcastPane
        case .storm: stormPane
        case .curtains: curtainsPane
        }
    }

    /// The legend's thumbnail: the pane's 16×16 of glass, as its own grid.
    static func paneThumbnail(_ weather: WindowWeather) -> PixelGrid {
        pane(weather)[windowGlass.rows].map { String($0.prefix(windowGlass.cols.count)) }
    }

    /// Today's crescent, cell for cell, on night glass; four static stars moved
    /// off the cells the worm covers (design defect 8); the meadow a silhouette.
    private static let nightPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "kkkmmnkkkkkkkkkk........",   // 4  the crescent begins
        "kkmmnkkkkkskkkkk........",   // 5  star
        "kmmnkkkkkkkkkkkk........",   // 6
        "kmmnkkkkkkkkkkkk........",   // 7
        "kmmnkskkkkkkkkkk........",   // 8  star
        "kkmmnkkkkkkkkkkk........",   // 9
        "kkkmmnkkkkkkkkkk........",   // 10 the crescent ends
        "kkkkkkkkkkkkkkkk........",   // 11 (behind the mullion)
        "kkkkkkkkkkkkkkkk........",   // 12 (behind the mullion)
        "kkkskkkkkkkkkkkk........",   // 13 star
        "kkkkkkkkkkskkkkk........",   // 14 star
        "dkkkkkkkkkkkkkkd........",   // 15 the meadow, a silhouette
        "dddkkkkkkkkkkddd........",   // 16
        "dddddkkkkkkddddd........",   // 17
        "dddddddddddddddd........",   // 18
        "dddddddddddddddd........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// A cycle just finished: cushion-plum over terracotta, a half sun rising
    /// behind the right slope.
    private static let dawnPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "cccccccccccccccc........",   // 4
        "cccccccccccccccc........",   // 5
        "cccccccccccccccc........",   // 6
        "cccccccccccccccc........",   // 7
        "cccccccccccccccc........",   // 8
        "cccccccccccccccc........",   // 9
        "cccccccccccccccc........",   // 10
        "cccccccccccccccc........",   // 11
        "cccccccccccccccc........",   // 12
        "ttttttttttnntttt........",   // 13 the sun's rim
        "tttttttttnmmnttt........",   // 14
        "gttttttttttttttg........",   // 15
        "gggttttttttttggg........",   // 16
        "pggggttttttggggp........",   // 17
        "ppggggggggggggpp........",   // 18
        "ppppggppppggpppp........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// Caught up: day sky, haze, the meadow bowl with three dandelions and one seed clock.
    private static let clearPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "yyyyyyyyyyyyyyyy........",   // 4
        "yymmyyyyyyyyyyyy........",   // 5  the sun (the moon's cream, a gold rim)
        "ymmmnyyyyyyyyyyy........",   // 6
        "ymmmnyyyyyyyyyyy........",   // 7
        "yynnyyyyyyyyyyyy........",   // 8
        "yyyyyyyyyyyyyyyy........",   // 9
        "yyyyyyyyyyyyyyyy........",   // 10
        "yyyyyyyyyyyyyyyy........",   // 11
        "yyyyyyyyyyyyyyyy........",   // 12
        "vvvvvvvvvvvvvvvv........",   // 13 haze
        "vvvvvvvvvvvvvvvv........",   // 14
        "hvsvvvvvvvvvvvuh........",   // 15 dandelion, seed clock
        "hhhvsvvvvvvvshhh........",   // 16
        "ghhhhvvvvvvhhhhg........",   // 17
        "gghhhhhhhhhhhhgg........",   // 18
        "gggghhgggghhgggg........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// Things are waiting: the clear sky with two clouds, the sun half behind one.
    private static let fairPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "yyyyyyyyyyyyyyyy........",   // 4
        "yymmyyyyyyjjyyyy........",   // 5  sun; the second cloud peeks out
        "ymmmnyyyyjjjjyyy........",   // 6
        "ymmmjjjyyxxxxyyy........",   // 7  the first cloud crosses the sun
        "yynjjjjjjyyyyyyy........",   // 8
        "yyjjjjjjjyyyyyyy........",   // 9
        "yyyxxxxxyyyyyyyy........",   // 10 its shaded underside
        "yyyyyyyyyyyyyyyy........",   // 11
        "yyyyyyyyyyyyyyyy........",   // 12
        "vvvvvvvvvvvvvvvv........",   // 13
        "vvvvvvvvvvvvvvvv........",   // 14
        "hvsvvvvvvvvvvvuh........",   // 15
        "hhhvsvvvvvvvshhh........",   // 16
        "ghhhhvvvvvvhhhhg........",   // 17
        "gghhhhhhhhhhhhgg........",   // 18
        "gggghhgggghhgggg........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// Overdue: a grey sky, two clouds, and the dandelions closed — they close
    /// in bad weather (a small true thing, not an encoding).
    private static let overcastPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "xxxxxxxxxxjjxxxx........",   // 4
        "xjjjxxxxxjjjxxxx........",   // 5
        "jjjjjjxxxNNNxxxx........",   // 6
        "NNNNNNxxxxxxxxxx........",   // 7
        "xxxxxxxxxxxxxxxx........",   // 8
        "xxxxxxxxxxxxxxxx........",   // 9
        "xxxxxxxxxxxxxxxx........",   // 10
        "xxxxxxxxxxxxxxxx........",   // 11
        "xxxxxxxxxxxxxxxx........",   // 12
        "vvvvvvvvvvvvvvvv........",   // 13
        "vvvvvvvvvvvvvvvv........",   // 14
        "hvvvvvvvvvvvvvvh........",   // 15
        "hhhvvvvvvvvvvhhh........",   // 16
        "ghhhhvvvvvvhhhhg........",   // 17
        "gghhhhhhhhhhhhgg........",   // 18
        "gggghhgggghhgggg........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// The last cycle failed: a dark sky, two clouds, rain in both panes, a
    /// static bolt (no flash — refused, §7.3), the meadow a silhouette.
    private static let stormPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "KNNNKKKKKKNNKKKK........",   // 4
        "NxxxNNKKKNxNKKKK........",   // 5
        "NNNNsNNKKNNNKKKK........",   // 6  the bolt starts
        "KKKKsKKKKKKKKKKK........",   // 7
        "UKKsUKKKUKKKUKKK........",   // 8  rain
        "KUsKKUKKKUKKKUKK........",   // 9
        "KKsKKKUKKKUKKKUK........",   // 10 the bolt ends above the mullion
        "KKKKKKKKKKKKKKKK........",   // 11
        "KKKKKKKKKKKKKKKK........",   // 12
        "UKKKUKKKUKKKUKKK........",   // 13
        "KUKKKUKKKUKKKUKK........",   // 14
        "dKUKKKUKKKUKKKUd........",   // 15
        "dddKKKKKKKKKKddd........",   // 16
        "dddddKKKKKKddddd........",   // 17
        "dddddddddddddddd........",   // 18
        "dddddddddddddddd........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// No reading yet: the curtains are drawn, a fold every third column.
    private static let curtainsPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
    ] + Array(repeating: "ccpccpccpccpccpc........", count: 16) + [
        "........................",
        "........................",
        "........................",
        "........................",
    ]
```

`Views/Sleep/WindowWeather.swift`:

```swift
import SwiftUI

/// The window's sky (Track Z R-Z11): STATE art. A total function of the mood
/// and nothing else — no count, no clock, no stage number — so the window can
/// never say something the sentence does not. The seven are listed once, in
/// `all`, and the legend (its text twin) is the only place their meanings are
/// written (P16). Refused: drift, a storm flash, and any weather driven by the
/// time of day (G125: state outranks the clock).
enum WindowWeather: String, CaseIterable, Identifiable, Equatable {
    case night, dawn, clear, fair, overcast, storm, curtains

    var id: String { rawValue }

    /// The legend's order.
    static let all: [WindowWeather] = [.night, .dawn, .clear, .fair, .overcast, .storm, .curtains]

    var title: String {
        switch self {
        case .night: "Night"
        case .dawn: "Dawn"
        case .clear: "Clear"
        case .fair: "Fair"
        case .overcast: "Overcast"
        case .storm: "Storm"
        case .curtains: "Curtains drawn"
        }
    }

    var meaning: String {
        switch self {
        case .night: "A cycle is running."
        case .dawn: "A cycle just finished."
        case .clear: "Caught up. Nothing waiting."
        case .fair: "Things are waiting to be read."
        case .overcast: "Overdue: it's been a while."
        case .storm: "The last cycle failed."
        case .curtains: "No reading yet."
        }
    }
}

/// `.curious` never reaches the Sleep page (G125 R2); it maps for totality.
func windowWeather(for mood: BookwormState) -> WindowWeather {
    switch mood {
    case .sleeping: .night
    case .digesting: .dawn
    case .happy: .clear
    case .reading, .curious: .fair
    case .hungry: .overcast
    case .error: .storm
    case .awake: .curtains
    }
}

/// The window's legend (I11): the seven skies with their thumbnails, the
/// current one marked in words for VoiceOver and by a ground for the eye.
struct WindowLegend: View {
    let current: WindowWeather

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.windowLegendHeader)
                .font(CicadaTheme.captionFont.italic())
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(WindowWeather.all) { weather in
                HStack(spacing: CicadaTheme.spacingSM) {
                    thumbnail(weather)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(weather.title)
                            .font(CicadaTheme.font(size: 12, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Text(weather.meaning)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    Spacer(minLength: 0)
                }
                .padding(CicadaTheme.spacingXS)
                .background(weather == current ? CicadaTheme.surfaceHover : Color.clear,
                            in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(weather == current ? .isSelected : [])
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 320, alignment: .leading)
        .background(CicadaTheme.surface)
    }

    /// Drawn from the same scene cache as the room (P13), on its own 16-cell
    /// grid so it is a smaller GRID, never a smaller rendering (P12's rule).
    private func thumbnail(_ weather: WindowWeather) -> some View {
        let pt = PixelRenderer.snappedPointSize(32 * CicadaTheme.uiScale, gridSize: 16)
        return Image(nsImage: PixelRenderer.cachedImage(
            key: "desk.paneThumb|\(weather.rawValue)|\(Int(pt))",
            grid: DeskSceneSprites.paneThumbnail(weather), gridSize: 16, pointSize: pt, palette: DeskPalette.ns))
            .interpolation(.none)
            .frame(width: pt, height: pt)
            .accessibilityHidden(true)
    }
}
```

`Views/Sleep/DeskScene.swift`:
- `DeskScene.plan` (its docstring gains one line on the pane):

```swift
    static let plan: [DeskLayer] = [
        DeskLayer(prop: .pane, cellX: 20, cellY: 4, z: 0),      // the sky, behind the frame (Track Z §7.3)
        DeskLayer(prop: .window, cellX: 18, cellY: 4, z: 1),
        DeskLayer(prop: .lamp, cellX: 0, cellY: 0, z: 2),
        DeskLayer(prop: .plant, cellX: 11, cellY: 0, z: 3),
        DeskLayer(prop: .cushion, cellX: 30, cellY: 0, z: 4),
        DeskLayer(prop: .mug, cellX: 52, cellY: 0, z: 5),
    ]
```

- `DeskSceneView` gains `var weather: WindowWeather = .night` and
  `@Environment(\.accessibilityReduceMotion) private var reduceMotion`. In the `ForEach`, the
  `.pane` layer draws its image inside a crossfade — the second (and last) beat not caused by
  input (R-Z12), a jump under Reduce Motion:

```swift
                if layer.prop == .pane {
                    ZStack {
                        sprite(layer, pointSize: spritePt)
                            .id(weather)
                            .transition(.opacity)
                    }
                    .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: weather)
                    .offset(x: CGFloat(layer.cellX) * layout.cell, y: -CGFloat(layer.cellY) * layout.cell)
                } else {
                    sprite(layer, pointSize: spritePt)
                        .offset(x: CGFloat(layer.cellX) * layout.cell, y: -CGFloat(layer.cellY) * layout.cell)
                }
```

  with `sprite(_:pointSize:)` the existing `Image(nsImage: PixelRenderer.cachedImage(key:
  Self.cacheKey(layer.prop, lampLit: lampLit, weather: weather, pointSize:), grid:
  DeskSceneSprites.grid(layer.prop, lampLit: lampLit, weather: weather), …)).interpolation(.none)
  .frame(width:height:)` extracted into a private func. The type docstring: the scene stays static
  — no `TimelineView` — and changes only when the SCHEDULE (lamp) or the MOOD (window) changes.
- `cacheKey(_ prop: DeskProp, lampLit: Bool, weather: WindowWeather = .night, pointSize: CGFloat)`:
  the variant is `lit`/`dark` for the lamp, `weather.rawValue` for the pane (`desk.pane|fair|120`,
  design §7.3), `-` otherwise.

`Views/Sleep/SleepMotion.swift`:

```swift
    /// The window's pane crossfading on a mood change (R-Z12's one state beat
    /// besides the cheer) — at the ceiling, never above it.
    static let weatherDuration: TimeInterval = 0.4

    static func weather(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: weatherDuration)
    }
```

`Views/Sleep/RoomModel.swift` — `var legendShown = false`.

`Views/Sleep/StudyRoom.swift` — `DeskSceneView(pointSize:lampLit: page.lampLit, weather:
windowWeather(for: page.mood))`, and the window hotspot (after the lamp's):

```swift
            if let window = spots[.window] {
                let weather = windowWeather(for: page.mood)
                // I11 — the window opens its legend: the weather's text twin.
                Button { room.legendShown = true } label: { Color.clear.contentShape(Rectangle()) }
                    .buttonStyle(.cicadaPlain)
                    .frame(width: window.width, height: window.height)
                    .roomLinkCursor()
                    .help("\(weather.title): \(weather.meaning)")
                    .accessibilityLabel("Window, \(weather.title): \(weather.meaning)")
                    .accessibilityHint(Copy.windowHint)
                    .accessibilitySortPriority(RoomA11yOrder.window)
                    .popover(isPresented: Binding(get: { room.legendShown }, set: { room.legendShown = $0 }),
                             arrowEdge: .top) { WindowLegend(current: weather) }
                    .offset(x: window.minX, y: -window.minY)
            }
```

`Views/Sleep/HowSleepWorks.swift` — after the `ForEach` of stages:

```swift
            // Track Z §7.3 (P16) — a pointer to the window's legend, never a
            // copy of it: `WindowWeather.all` is the one list of skies.
            Text(Copy.windowLegendPointer)
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
```

`Theme/Copy.swift`:

```swift
    static let windowLegendHeader = "The window shows how Cicada is doing, not the time of day."
    static let windowLegendPointer = "The window in the room shows how Sleep is doing — click it to see what each sky means."
    static let windowHint = "Shows what the sky means"
```

`SleepNumbersLintTests`: `XCTAssertLessThanOrEqual(SleepMotion.weatherDuration, SleepMotion.maxDuration)`
and the `weather(reduceMotion:)` nil / non-nil pair.

- [ ] **Step 3: Verify.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures.
  Then the art check: `CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests 2>&1 | tail -5`
  and open the seven PNGs under `$TMPDIR/cicada-composites/` with the Read tool — each sky reads as
  its weather, the stars and the sun sit clear of the worm, nothing looks like a book (P10).
- [ ] **Step 4: Commit** — `feat(sleep v4): the window shows weather, and the weather is Sleep state (G125 v4, R-Z11)`.

---

### Task 10 (Z12, this part's slice): The docs — the rulings where the next reader will look

**Files:**
- Modify: `CLAUDE.md:484-495` (the "Sleep page — the study room (G125 v3)" paragraph) and `:497-502` ("Mascot states (G107)")
- Modify: `docs/goals/memory-evolution.md:686` (G125 — a **v4** paragraph appended) and `:669` (G107 — the feeding amendment and the poses)
- Modify: `docs/goals/TODO.md:99-125` (two rulings appended after ruling 7)
- Modify: `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` — a "Track Z rulings" subsection after "Wave 2 designs" (`:226-273`)

Privacy (standing rule): no bank contents, no names, no counts read from a bank — placeholders only.
The owner's own words are quoted with his name and date, the house voice.

- [ ] **Step 1.** `CLAUDE.md` — replace the v3 paragraph with (same length class, the Companion
  App section's voice):

  > **Sleep page — the study room (G125 v4, Track Z).** One 760 pt column at every width: the room,
  > one serif sentence under it, one Consolidate/Cancel control, one whisper line for the schedule,
  > and everything else under a single **Details** disclosure (Last cycle · What's waiting · Readout
  > · Past nights), closed by default, remembered per viewer (`cicada.sleep.detailsOpen`) and not
  > built while closed. The worm speaks in that one fixed slot — `roomSentence` / `wormAnswers`, pure
  > `SentenceLine` values over `SleepPageModel` (lead ≤ 40, tail ≤ 80, clock-free; a missing fact
  > omits its rung, never shows a guess); the floating bubble is retired. **Two kinds of art
  > (R-Z1):** *state art* — the mood's frames, the lamp (= the schedule), the pile, and the window's
  > **weather**, a total function of the mood with a legend popover as its twin — and *response
  > art* (gaze, perk, talk, cheer), transient and never contradicting state. The art layer stays
  > inert; interaction is a hotspot layer derived from the pure layout (`deskHotspots`), and **no
  > click on art changes what the machine does**: the lamp's popover shows the scheduled engine and
  > its reason *before* its labelled toggle can flip, and Consolidate stays the one trigger. The
  > strip appears only while running or frozen after a cancel or failure; the running stage is
  > `activeStage(completed:)` = completed + 1 everywhere (page, menu bar, onboarding, strip). A
  > real completion cheers once and offers "See what changed ›"; a cancel neither chews nor cheers.
  > Memory sources left the page (Sources v2 draws it; the series live in
  > `Views/Sources/ActivitySeries.swift`). Refused: autonomous beats with no fact behind them, cloud
  > drift, a storm flash, estimates, prices.

  and append to the "Mascot states (G107)" paragraph:

  > Track Z adds **response art** inside `BookwormSprites`: `BookwormPose` (idle · attentive(gaze)
  > · expectant(gaze) · eager) and `BookwormReaction` (perk · talk · gulp · shake · cheer), gated by
  > one state × response matrix (`BookwormState.allows`, `acceptsGaze`) so a sleeping worm's eyes
  > stay shut and red pupils never look away; every beat is ≤ 3 frames × 0.12 s; a hop is a
  > whole-cell shift (a capped state crouches instead — the nightcap owns the grid's headroom); and
  > a lint bans `.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(` on the worm except its
  > lattice placement. The renderer key gains one `look` segment, omitted for idle (every older key
  > byte-identical); the page's reachable set is ≤ 256 keys per size and the wipe bound is 1024.
  > **Feeding** — a file dropped on the worm imports through the one intake — is ruled (R-Z10) and
  > lands with Track I's `IntakeRouter`.

- [ ] **Step 2.** `memory-evolution.md` — G125: append **"v4 (2026-09-23) — the mascot page
  (Track Z, part a)."** in the row's own density: the owner's brief quoted ("Change the mascot page,
  make it better and have it be more interactive, keeping the minimal vibes."), what shipped
  (R-Z1…R-Z14 by id, not restated; this plan's Z-P1…Z-P27 where they bind later work — the active
  stage, `kind == "sleep"` as the last cycle, the whisper line taking the schedule row, the pane art
  re-checked against the real worm union with the two clouds moved, the 216-key measurement), the
  three defects fixed (stage off-by-one at three sites, the cancel that digested, the invented
  stage lines), and what is deliberately **not** in v4 yet: feeding (Z9, after Track I), the Meadow
  pass and the optional sky band (Z10, after M1), live verification and screenshots (Z11). G107:
  append **"Amended 2026-09-23 (round-3 decision 5, Track Z)"** — "Not built: … drag, feeding
  mechanics" becomes "the worm is never draggable; feeding is import and only import (R-Z10), lands
  with Track I"; the poses and reactions and the matrix, one sentence each; G127 stays DECIDE and
  the pose API is character-agnostic.
- [ ] **Step 3.** `TODO.md` — append after ruling 7:

  > 8. **The Sleep page shows the ACTIVE stage, and there is one translation** (Track Z R-Z14). The
  >    wire's `stage` counts completed stages (`sleep_cycle.py` sets 1 only after Stage 1 returns);
  >    three derivations clamped it without adding one, so the worm, the bracket line and VoiceOver
  >    said "stage 1" while Sort ran. `activeStage(completed:)` is the only way any view turns the
  >    wire number into a stage. Revisit only if the backend starts reporting the stage in flight.
  > 9. **Pixel art beside the worm is checked against the real worm, per weather** (Track Z
  >    Z-P13). A hand-approximated worm passed two window clouds the real frames hide (the head's
  >    shake uncovers a column); `WindowSpritesTests` masks with every look of every mood that shows
  >    that weather. Any new art near the worm gets the same test.

- [ ] **Step 4.** Round-3 spec — after the "Their owner questions, answered by default" list, add
  `### Track Z (wave 2): the mascot page` with one line per ruling R-Z1…R-Z14 (the ids and their
  one-sentence rule, pointing at the design doc for the reasoning) and one line naming this plan and
  its part-a scope (Z0–Z8; Z9 after Track I, Z10 after M1, Z11 the orchestrator's).
- [ ] **Step 5: Commit** — `docs: Sleep v4 — the mascot page's rulings (G125 v4, G107 amendment, R-Z1…R-Z14)`.

---

## Seams left for the rest of Track Z (not built here)

- **Z9 — feeding (after Track I's `IntakeRouter`).** Everything feeding needs from this part exists
  and is tested: `BookwormPose.expectant(_:)` / `.eager` and the `gulp` / `shake` reactions
  (Task 5), `RoomModel.play` and the beat clock (Task 6), `gazeFor` for aiming at a drag point,
  `SleepMotion.hoverDuration` for the drop outline, `StudyRoom` as the whole-room drop target.
  Z9 adds `RoomFeed.swift` (`RoomDropDelegate`, the adapter's three outcomes), `feedGuard` (into
  the router), the feed lines, the T13 row in `sentenceTail`, the worm's "Feed a file…" action and
  context-menu item, and the hint's "Drop a file to import it." clause (Z-P16). Nothing in this part
  mentions dropping.
- **Z10 — the Meadow pass (after M1).** `RoomSentenceView`'s two `CicadaTheme.font(size:design:
  .serif)` calls become `displayFont(size:)` / `displayFont(size:italic:)`; `SleepControlRow`'s
  Consolidate capsule becomes the page's one `.glassProminent` on macOS 26; the optional sky band
  ships only if the Z11 screenshots say calm.
- **Z11 — live verification and screenshots** are the orchestrator's (below).

## Not in scope

Named so a reviewer does not read an absence as an oversight.

- **Feeding (Z9)**, **the Meadow pass and sky band (Z10)**, **live verification and the README
  screenshot retake (Z11)** — see Seams.
- **The menu bar's own completion edge** (`Sync/Store.swift:424` stamps `justFinishedAt` on any
  running→idle edge, so the menu-bar worm still chews after a cancel): noted for its owner, as the
  design says (§13.2); only the menu bar's stage number is fixed here (Task 1).
- **The backend.** No endpoint, field, ETag or Store domain changes; `api/` is untouched.
- **Mascot identity (G127).** The pose/reaction API and the hotspots are character-agnostic; the
  nightcap stays the one character-specific piece of art.
- **A frame memo without a measurement** (Z-P24).
- **Sound, a hunger mechanic, a nag, a reward loop, a draggable worm, the hello and glance beats,
  cloud drift, the storm flash, a time-of-day sky, the night wall** — refused by the design (§0,
  R-Z10, R-Z12).
- **Rehoming `ConsolidationHistoryCard`'s engine pill onto real marks** — it keeps its SF symbols;
  the marks this part adds are on the lines that *name* an engine in words.

---

## Verification the orchestrator runs at the end

1. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success; `swift test 2>&1 | tail -20`
   → **0 failures** (≥ 1012 executed plus this plan's new tests). Backend untouched — confirm with
   `git diff --stat dev -- api/` (empty) and, for the baseline, `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
   → 2225 passed. Graph: `node --test app/CicadaApp/Tests/graph/*.test.js` green.
2. **Lints that must be able to fail** (a lint that never failed is not known to work): add
   `.scaleEffect(1.01)` after `WormStage(…)` in `StudyRoom.swift` → `SleepNumbersLintTests` FAILS;
   add `.onContinuousHover { _ in }` in `SleepView.swift` → FAILS; add `.white` in `BookPile.swift`
   → `SpineAndLampTests` FAILS; revert each and re-run green.
3. `CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests` and look at the seven PNGs.
4. **Live (design §15, minus the drops of item 7):** `make install-app` and on the **demo** bank —
   widths 760 / 1200 / 1560, zoom 0.8 / 1.0 / 1.4, light and dark; the room fits at 1.4; nothing
   reflows when the sentence changes, an answer appears or the strip appears (it appears under the
   whisper line, Z-P9). Drive every weather (curtains on a cold launch, fair with a queue, night on
   Consolidate, dawn in the 6 s after, clear on an empty queue, overcast from a > 48 h fixture,
   storm from a failing engine) and read the sentence and the legend at each. Pointer: the pupils
   follow with no flicker at the edges — also while over a spine, the lamp or the worm's own hotspot
   (the room's `onContinuousHover` must keep reporting over its child buttons; if it does not, the
   perk moves into `WormHotspot`'s own `.onHover`, a one-function change); one perk on reaching the worm; poke through every rung,
   Esc with keyboard focus, wait 12 s outside; the plant, mug and cushion do nothing, not even the
   cursor. Spines: popover counts match Details › What's waiting; "Open in Sources ›" lands on that
   source; hovering a row lifts its spine. Lamp: the scheduled engine line is visible *before*
   flipping; the lamp and the whisper line flip together; with the backend stopped, the toggle
   snaps back with its caption. A cycle: L3/L5 + T2, the strip, the Cancel caption, night → dawn,
   the cheer, "See what changed ›" opens Details and lands on the expanded row; cancel mid-cycle:
   no cheer, no chew, T4, the strip frozen; a forced failure: L6/T3 in danger, the storm, Last
   cycle at full contrast. Reduce Motion: no gaze, no beats, no crossfades. VoiceOver: the §11 order,
   rungs announced, "What are you doing?" reads all. Full Keyboard Access reaches the worm, the lamp,
   the window, every spine, the control, the whisper line and Details.
5. **CPU (design §10):** Activity Monitor on the demo bank at 1.0×, idle 60 s — no higher than v3;
   a 10 s pointer sweep over the room — within +3 points of idle. Both numbers go in the PR body.
6. **PR body must state:** no backend, endpoint, ETag or Store-domain change; no price or token
   anywhere; `FixWaveTests`, `SleepHeroTests`, `BookwormRendererTests`, `BookwormSpriteTests` and
   `BookwormViewTests` pass unmodified; which test files were edited and why (this plan's **Files**
   lists); the frame-memo benchmark numbers (Z-P24); screenshots from the **demo** bank only (G90).
