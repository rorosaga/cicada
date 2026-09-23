# Track Z, final: the mascot page (Sleep v4), the judge's synthesis

Owner brief (Rodrigo 2026-09-23): *"Change the mascot page, make it better and have it be more
interactive, keeping the minimal vibes."* Round-3 spec decision 5 keeps the bookworm, allows hover
and click on the worm, a clickable pile and lamp, and "feeding = dropping a file on the worm imports
it". Art still encodes state and never quantity, and every art bit keeps a text twin.

Inputs judged: `mascot-companion.md` (C), `mascot-instrument.md` (I), `mascot-meadow.md` (M).
Code read on `dev` at `f2d31ef`. Paths are relative to `app/CicadaApp/Sources/CicadaApp/` unless
they start with `api/`, `docs/` or `app/`.

---

## 0. The verdict

**The winner is the Companion's frame.** It has the best answer to the owner's first two words: the
worm notices you, answers when you poke it, eats the file you hand it and cheers when a night's
filing is done. Its contract (*state art* vs *response art*; "every interaction says something true
or does something real") is the right law for an interactive status surface.

**Its weak side is the third phrase, "minimal vibes".** It keeps v3's whole density: two columns, a
hero with a meter and three tiles, a strip, five banners and a sparkline card. On top of that it adds
seven beats, two of them autonomous. The final design fixes this with three grafts:

- **From the Instrument (the page and the honesty).**
  - The default view becomes *the room, one sentence, one button and one whisper line*, with
    everything else in a single **Details** disclosure.
  - The worm speaks in one fixed slot under the room: a serif headline over an italic line, the
    brief's own reference. The floating bubble is retired.
  - The stage strip appears only when it has news.
  - The hotspot layer is derived from the pure layout.
  - The lamp popover shows the scheduled engine *before* the schedule can be flipped.
  - The Instrument's two real defects are fixed: the stage off-by-one and two stage lines that
    assert unmeasured facts.
- **From the Meadow (the "better").**
  - The window shows **weather**, and the weather is Sleep state. It is a total function of the
    mood, drawn in pixels on the room's one lattice, with a legend popover as its twin. Pressing
    Consolidate turns the room to night.
  - The simpler gaze: three horizontal poses, with the worm's own ink span as the dead zone.
  - The rule that a click on art never changes what the machine does unless the words are on screen
    first.
- **Refused from all three.**
  - The hello and glance beats: autonomous motion with no action or new fact behind it.
  - A fallback copy of the upload pipeline.
  - Inline sniff counts that duplicate Track I's preview.
  - Cloud drift and the storm flash.
  - The Instrument's flat night wall, which cannot coexist with a day window.

---

## 1. Scores

Each criterion is scored from 1 to 5. The weighted column follows the owner's words:

- delight ×2 ("better", "more interactive");
- minimalism ×1.5 ("keeping the minimal vibes");
- honesty, feasibility/perf and accessibility ×1 each (the rails).

| Proposal | Delight | Minimalism | Honesty (state, never quantity) | Feasibility / perf | Accessibility | Raw /25 | Weighted /30.5 |
|---|---|---|---|---|---|---|---|
| **Companion** | **5** | 2.5 | 4 | 3 | **5** | 19.5 | **25.75** |
| **Instrument** | 2 | **5** | **5** | 3.5 | **5** | **20.5** | 25.0 |
| **Meadow** | 4 | 3.5 | 4 | 3 | 4 | 18.5 | 24.25 |

### Companion
- **Delight 5.**
  - Gaze across the card, and a perk when the pointer reaches the worm.
  - A poke that steps through true lines.
  - Feeding with expectant and eager poses, and a cheer that links to "What changed ›".
  - The lamp and the spines are real controls.
  - This is the only entry where the worm feels alive.
- **Minimalism 2.5.**
  - Leaves every v3 surface in place (`SleepView.swift:421-444`) and adds a hint line.
  - Seven reaction kinds; `hello` and `glance` are autonomous beats. `hello` has no state behind it
    at all. `glance` restates the pile restack that `SleepMotion.pile` already animates
    (`BookPile.swift:123`).
- **Honesty 4.**
  - R-Z1 (response art vs state art) is the key conceptual contribution.
  - Found the real cancel defect: `SleepView.swift:299-303` stamps `justFinishedAt` on any
    running→idle edge, and `SleepMood.swift:108-110` then shows `.digesting` after a cancel.
  - Magnitude never scales the art.
  - But:
    - it kept the invented stage lines (`SleepBubble.swift:36-37`);
    - it missed the stage off-by-one;
    - its inline "374 new, 38 I already have" duplicates Track I's preview card.
- **Feasibility 3.**
  - The largest sprite surface: 6 gazes × 4 frames plus 7 reactions plus 2 poses.
  - `FallbackIntake` is a temporary second upload pipeline beside `UploadOverlay.swift:342-450`.
  - Whole-card `onContinuousHover`, although its write-on-change plus leaf-observation plan is
    sound.
- **Accessibility 5.**
  - One worm element with named actions and announcements.
  - A keyboard path for feeding.
  - The guard refusals are spoken in the worm's voice.

### Instrument
- **Delight 2.**
  - The worm only perks (`attend`), talks and gapes (`expect`).
  - The bubble, the page's one bit of character voice, is deleted.
  - Its interactivity is mostly popovers.
- **Minimalism 5.**
  - The default view is room + sentence + button + whisper, one column, and Details.
  - The strip shows only with news.
  - Memory sources leaves a page where it duplicated Sources v2
    (`Views/Sources/SourceCardGrid.swift:178-181` already calls the same `sparklinePoints` and
    `weekDots`).
- **Honesty 5.** Verified in code:
  - The stage off-by-one. `sleep_cycle.py:978` sets `_state.stage = 1` only *after* Stage 1
    returns, and `:1027` sets 2 after Stage 2. Yet `SleepMood.swift:103` renders
    `.sleeping(stage: max(1, min(5, status.stage)))`, so while Sort runs the worm, bubble and
    VoiceOver bracket say stage 1 while the strip lights Sort (`SleepStages.swift:124-145`). The
    menu bar has the same clamp (`MenuBar/BookwormState.swift:159`).
  - The invented stage-3/4 lines.
  - "No figure twice on the default view".
  - Ruling 4 is shown at the moment of choice.
- **Feasibility 3.5.**
  - The best runtime profile: a collapsed Details builds nothing.
  - The largest structural blast radius: layout, hero split, card deletion, and moving the series
    functions.
  - Plus a DECIDE (the night wall).
- **Accessibility 5.**
  - An explicit focus order.
  - "What are you doing?" announces every rung at once.
  - Hover-only information is refused.

### Meadow
- **Delight 4.**
  - The weather window is the most on-brief "better": nature through the room's one opening, and
    Sleep literally turns the room to night.
  - Gaze, a hop and a legend.
- **Minimalism 3.5.**
  - Adds no chrome inside the room.
  - But it adds a page wash, a cloud-drift DECIDE and a storm flash, and keeps v3's density.
- **Honesty 4.**
  - `windowWeather(for:)` reads the mood and nothing else, has a legend twin, and its wash opacity
    is contrast-tested.
  - It is a second encoding of the mood and amends P11.
- **Feasibility 3.**
  - Seven hand-authored pane grids.
  - `DeskPalette` grows from 13 to 20 keys.
  - A frame/pane split, occlusion tests and a contrast table.
  - `backgroundExtensionEffect` inside a `ScrollView` is unverified.
- **Accessibility 4.**
  - Good actions and a legend.
  - No pointer cue on macOS 14.
  - The lamp only deep-links to Settings.

---

## 2. Graft ledger

| Element | Source | In the final design |
|---|---|---|
| State art vs response art; every interaction true or real; magnitude never scales art | C R-Z1/R-Z3/R-Z5 | **Kept** as R-Z1…R-Z3 |
| All worm motion is sprite frames on the lattice; no `.offset`/`.scaleEffect` on the worm | C R-Z6 | **Kept** (R-Z4) |
| Gaze | C (6 poses, whole card) vs M (3 poses, room box) | **M's 3 horizontal poses over the room box**, with C's blinking attentive loop |
| Perk on reaching the worm | C I2 / I `attend` | **Kept** (2-frame beat, 2 s cooldown) |
| Poke | C boop + deck / I talk + ladder / M hop + lines | **I's answer ladder, spoken with a `talk` beat**; C's lamp line folded into the ladder |
| Voice location | C fixed bubble / I sentence slot | **I's sentence slot** under the room (this also dissolves C's defects 2 and 3) |
| Feeding | C FeedController + fallback / I and M router-only | **Router-only (Track I)**, with C's poses, guard list and the worm's refusal lines |
| Cheer + "What changed ›" | C I9 | **Kept**, opening Details › Past nights |
| Hello, glance | C I8/I10 | **Refused** |
| Spines | C row reveal / I popover / M row reveal | **I's popover**, plus C's row↔spine hover link inside Details |
| Lamp | C mode radio / I toggle + engine-first / M deep link | **I's toggle**, with the scheduled engine shown before flipping, plus a link to Settings for rhythm and time |
| Page reduction, one column, Details, conditional strip, Memory sources off the page | I | **Kept** |
| Window weather + legend | M | **Kept** (without drift or flash) |
| Sky wash band | M §6 | **Optional slice**, screenshot-gated |
| Night wall | I R-Z13 | **Refused**: a day window cannot sit in a night wall |
| Cancel defect; stage off-by-one; invented stage lines; per-tick frame recompute | C, I, I, C and I | **Fixed in Z0 / Z3** |

---

## 3. The contract (Track Z rulings R-Z1 … R-Z14)

- **R-Z1 Two kinds of art.**
  - *State art* encodes a fact and has a text twin: mood frames, the lamp, the window weather and
    the pile.
  - *Response art* acknowledges the person's own gesture (gaze, perk, talk, gulp, shake). It is
    transient, carries no fact, and **never contradicts state art**:
    - a sleeping worm's eyes stay shut;
    - error pupils stay red;
    - the nightcap, the held book and the stage dots persist through every response.
- **R-Z2 Every interaction says something true or does something real.**
  - Hotspots: worm (ask, feed), spines (that source's queue), lamp and whisper line (schedule),
    window (legend), room (drop).
  - The plant, mug, cushion and wall never react, not even to hover.
- **R-Z3 Magnitude never scales the art.** One file and a thousand get the same gulp. A 3-entity
  cycle and a 300-entity cycle get the same cheer. Quantities live in the pile, the sentence and
  Details.
- **R-Z4 All worm motion is sprite frames on the one lattice.**
  - A hop is `BookwormSprites.shift(dy: -1)`.
  - Nothing applies `.offset`, `.scaleEffect`, `.rotationEffect` or a spring to the worm (a lint
    enforces this).
- **R-Z5 The worm speaks in one place.**
  - That place is the sentence slot directly under the room: the status by default, answers on a
    poke, prompts during a drag.
  - The slot has a fixed reserved height, so nothing below it reflows.
  - No floating bubble.
- **R-Z6 The default view is the room, the sentence, one button and one whisper line.**
  - Everything else sits in one collapsed **Details** disclosure, or on Sources.
  - One column at every width.
  - The stage strip appears only while running, or frozen after a cancel or failure.
- **R-Z7 No figure twice on the default view.** Details is a second surface opened on purpose.
  Answers *replace* the sentence rather than sitting beside it.
- **R-Z8 The art layer stays inert.**
  - `DeskSceneView` keeps `.allowsHitTesting(false)` and `.accessibilityHidden(true)`
    (`DeskScene.swift:162-163`).
  - Interaction lives in a hotspot layer whose rectangles come from the pure
    `deskHotspots(layout)`: whole cells, disjoint, and tested.
- **R-Z9 A click on art never changes what the machine does.**
  - No hotspot starts, cancels or schedules a cycle.
  - The schedule changes only through a labelled `Toggle` inside the lamp popover, which shows the
    scheduled engine and its reason *before* it can be flipped.
  - Consolidate stays the one trigger (R-A7).
- **R-Z10 Feeding is import, and only import.**
  - A drop, or "Feed a file…", goes to Track I's `IntakeRouter` (its sheet, its preview, its
    `intakeInFlight`).
  - There is no second upload path, no hunger mechanic, no nag and no reward loop.
  - Feeding never "cures" the page's `.hungry`; only a cycle does.
  - Harness transcript roots and `~/.cicada` are refused at the door.
- **R-Z11 The window is weather, and the weather is state.**
  - `windowWeather(for: BookwormState)` is total and reads nothing else: no count, no clock, no
    stage number.
  - Seven weathers, listed once in `WindowWeather.all`.
  - Drawn in `DeskPalette` pixels on the one lattice.
  - The legend is its text twin.
  - The room now has two data-driven bits: the lamp and the window.
- **R-Z12 Autonomous motion is limited to state.**
  - Idle is still unless the person is pointing at, clicking or dropping on the room. Every
    response settles within 400 ms of the last input.
  - The only beats not caused by input:
    - `cheer`, on a real completed cycle;
    - the weather crossfade, on a mood change.
  - No hello, no glance, no drift and no flash.
- **R-Z13 Sentences and answers are pure `SentenceLine` values** over values the page already
  resolved.
  - Lead ≤ 40 characters and tail ≤ 80.
  - No "!", no bare `%`, and no "est", "~", "cluster" or "insight".
  - A missing fact omits its rung, never shows "—" and never guesses.
  - Clock-free (R8).
- **R-Z14 One stage translation.** The running page shows the **active** stage,
  `activeStage(completed:) = max(1, min(5, completed + 1))`. It is shared by the page mood, the
  menu-bar state, the sentence, the answers and the strip.

---

## 4. The page

### 4.1 Layout

- One column at every width: `maxWidth = SleepLayout.stackedContentWidth` (760 pt,
  `SleepView.swift:25`), centred.
- The two-column branch of `sleepLayout(width:)` (`:42-51`) is retired.
- The room is 450 × 140 pt at zoom 1.0 and 630 × 196 pt at 1.4 (`deskSceneLayout`,
  `DeskScene.swift:105-121`), so it fits at every zoom step.
- The worm stays at 120 pt (`SleepView.swift:500`).

**A. Idle, with a queue, lamp lit, window `fair`**

```
 Sleep Cycle  (as of 14:02 — only when stale)                                  (?)
┌ room card, fixed height (R-A2) ─────────────────────────────────────────────────┐
│  ▄▄▄                 ┌──┬──┐                                                   │
│ ▐███▌  ✿             │☀☁│☁ │  (worm · cap · book, eyes follow the pointer)     │
│  ▐▌   ✿✿✿            ├──┼──┤                                   ▬▬▬▬▬▬ 35 ▣    │
│  ▐▌   ▀▀▀            │✿~~│~~│    ▄▄cushion▄▄        ☕           ▬▬▬ 9 ▣       │
│ ▄██▄                 └──┴──┘                                   ▬ 3           │
│ ^lamp        ^window (weather)   ^worm                          ^spines        │
│ (whole room = drop target once Track I lands)                                  │
└────────────────────────────────────────────────────────────────────────────────┘
                              47 to read.          ← Instrument Serif 30, numeral in SF
                  The Claude Code pile is the big one.   ← italic 22, textSecondary
            ( ☾ Consolidate now )   Runs on Claude Code (your plan)
              ☾ Every day at 03:00 · Next run Sep 24, 3:00 AM   ← whisper line (a button)
 ›  Details
```

**B. Running, Stage 2** (window `night`, worm `sleeping` with the cap and zZ, strip visible)

```
                                Sorting…
          New mentions are matched against what you already have.
      [▣ Read ✓] → [▣ Sort ◉] → [▣ Decide] → [▣ Notice] → [▣ File]
            ( ✕ Cancel )   Stops at the next safe point — nothing is lost.
```

**C. The last cycle failed** (window `storm`, idle, `status.error` set)

```
                         The last cycle failed.                  ← danger
       claude exited 1: rate limited — the queue is where you left it…   ← danger, link → Details
      [▣ Read ✓] → [▣ Sort ✗] → [▣ Decide ·] → …                 ← frozen strip (P15)
```

**D. Answering** (after one click on the worm; the worm plays `talk`)

```
                        Waiting for a night.
                  The oldest has waited 3 days.
```

**E. A file dragged over the room** (dashed 2 pt inset outline; the worm is `expectant`, or `eager`
over the worm itself)

```
                          Is that for me?
            Chat exports, bookmarks, feeds and notes.
```

**F. Details open** (per-viewer `@AppStorage("cicada.sleep.detailsOpen")`, default closed; closed
means not built)

```
 ⌄ Details
   LAST CYCLE      only with an error / cancel / cap / warning: today's banners verbatim, full contrast
   WHAT'S WAITING  StudyListCard rows (mark · source · oldest · waiting / read of total)  ← pile's twin
   READOUT         Rested 38% ▮▮▮▮▮▮▮▮▮▯▯▯…   1,866 entities · 7 sources · Last cycle 4 m 12 s
                   Engine Claude Code (your plan) · <detail>
   PAST NIGHTS     ConsolidationHistoryCard, unchanged behaviour (expand, entity chips)
```

**Header.** It is unchanged in structure (`SleepView.swift:551`): the title, the staleness chip
(R-A12) and `?` (*How Cicada sleeps*). `Copy.sleepSubtitle` stops rendering and becomes the page's
`accessibilityHint`. Its wording rule stays pinned by `CopyConstantsTests`.

### 4.2 What moves where

| v3 element (today) | Final home |
|---|---|
| `SpeechBubbleView` (`SleepView.swift:646`; `SleepBubble.swift:57-122`) | **Deleted.** `sleepBubbleText` stays as a shared pure function (other round-3 designs reuse it for Home's footer); it feeds tail T12. |
| Hero count + qualifier chip (`SleepHero.swift:270-298`) | The sentence lead. The qualifier becomes a coloured *word* ("— overdue"), never colour alone. |
| Meter, three tiles, engine line (`SleepHero.swift:311-360`; `SleepView.swift:851`) | Details › Readout. They stay in `SleepHero.swift`, so the "Rested" spelling lint holds. |
| Consolidate/Cancel + caption (`SleepHero.swift:383-467`) | Stays on the default view as `SleepControlRow`, in `SleepHero.swift` (the `FixWaveTests.swift:53-68` lint holds). While running, the one control *is* Cancel, and the disabled twin pill goes. |
| Stage strip (`SleepView.swift:694-704`) | Conditional (R-Z6). |
| Caught-up worm at the strip's end (`SleepStages.swift:152`; `SleepStageStrip.swift:31,76`) | **Deleted**: the room's worm is already `.happy`. |
| Banners (`SleepView.swift:773-892`) | A one-line sentence tail (T3–T6), with the full text in Details › Last cycle. |
| *In the queue* rows (`StudyListCard.swift:123-203`) | Details › What's waiting. |
| Schedule row + next run (`StudyListCard.swift:311-340`) | The whisper line, plus the lamp popover. |
| `MemorySourcesCard` (`SleepView.swift:437-446`) | **Leaves the page** (Sources v2 draws the same projection). Its series functions move to `Views/Sources/ActivitySeries.swift`. |
| `ConsolidationHistoryCard` | Details › Past nights. |

---

## 5. The sentence (`Views/Sleep/RoomSentence.swift`, pure)

```swift
struct SentenceLine: Equatable {
    var numeral: String?        // pre-formatted, drawn in SF .rounded .monospacedDigit — never serif digits
    var lead: String
    var qualifier: String?      // "overdue" — a word, tinted by sleepDebtBracketColor (SleepMood.swift:167)
    var tone: SentenceTone      // .plain | .warning | .danger
    var tail: String?
    var tailTone: SentenceTone
    var action: SentenceAction? // .retry | .openInbox | .openDetails(Section) | .openLamp | .whatChanged
}
func roomSentence(_ ctx: RoomContext) -> SentenceLine      // status sentence
func wormAnswers(_ ctx: RoomContext) -> [SentenceLine]     // the poke ladder (§6.3)
func feedLine(_ phase: FeedPhase, _ ctx: RoomContext) -> SentenceLine
```

**Typography.**
- Lead: `displayFont(size: 30)`. Tail: `displayFont(size: 22, italic: true)` in `textSecondary`.
  Both come from M1's R-M3.
- Until M1 lands, both use New York via `CicadaTheme.font(size:design: .serif)`.
- The tail uses `.lineLimit(2, reservesSpace: true)`, so the slot never reflows.
- The text is centred. A tail action renders its last words as a `.cicadaPlain` accent link.

**The lead.** The first matching row wins.

| # | Condition | Lead |
|---|---|---|
| L1 | status domain failed (`StudyListCard.loadState == .failed`, `StudyListCard.swift:114-121`) | "I can't see the queue." |
| L2 | status loading | "Checking what's waiting…" |
| L3 | running, active stage 1, `total > 0` | numeral "138 of 203" · "Reading 138 of 203." |
| L4 | running, active stage 1, `total == 0` | "Reading…" |
| L5 | running, active stage 2–5 | "Sorting…" / "Deciding…" / "Noticing…" / "Filing…" (one map over `SleepStages.all[n-1].shortLabel`, `SleepStages.swift:38-54`) |
| L6 | idle, `status.error` non-empty | "The last cycle failed." (danger) |
| L7 | `.digesting` | "Filed." |
| L8 | `.reading` or `.hungry`, `heroCount > 0` | numeral `heroCount` · "to read." + `.hungry` → qualifier "overdue" (warning) |
| L9 | `.hungry`, count 0 | "Nothing new to read." |
| L10 | `.happy` | "All caught up." |
| L11 | `.awake` | "Listening." |

**The tail.** The first matching row wins, so news outranks everything else.

| # | Condition | Tail | Action |
|---|---|---|---|
| T1 | L1 | the domain error, one line | `.retry` |
| T2 | running | `SleepStages.all[active-1].detail` (P16) | – |
| T3 | L6 | first clause of `status.error`, cut on a word at ≤ 80 characters, "…" | `.openDetails(.lastCycle)` |
| T4 | `status.cancelled` | "Stopped early — nothing was lost." | `.openDetails(.lastCycle)` |
| T5 | `episodesQueued > episodesTotal` | "The rest wait for the next cycle." | `.openDetails(.lastCycle)` |
| T6 | `indexWarning` non-empty | "Finished with a warning — it's in Details." (warning) | `.openDetails(.lastCycle)` |
| T7 | `room.recentCycleCommit != nil` (§6.5) | "See what changed ›" | `.whatChanged` |
| T8 | `!hasRunBefore`, count > 0 (P9) | "My first night — nothing's been filed yet." | – |
| T9 | `!hasRunBefore`, count 0 | "Nothing's been filed in this memory yet." | – |
| T10 | `.hungry`, `hoursSinceLastCycle ≥ 48` | "It's been {h/24} days." | – |
| T11 | count > 0, `schedule.mode == "manual"` | "The lamp is off — I read when you ask." | `.openLamp` |
| T12 | `.reading`, top origin known | "The {label} pile is the big one." (today's `sleepBubbleText` rung, `SleepBubble.swift:28`) | – |
| T13 | `.happy`, **feeding shipped** | "Drop a file on me to add it to the pile." | – |
| T14 | otherwise | nil (the height stays reserved) | – |

**VoiceOver.** The slot is one static text element that reads the visible words. P8's bracket line
(`sleepDebtBracketText`, `SleepMood.swift:154-160`) moves to the worm's `accessibilityValue`.

---

## 6. The worm

### 6.1 Sprite API (`MenuBar/BookwormPose.swift`, new; character-agnostic for G127)

```swift
enum Gaze: Hashable { case left, center, right }
enum BookwormPose: Hashable { case idle, attentive(Gaze), expectant(Gaze), eager }
enum BookwormReaction: String, Hashable, CaseIterable { case perk, talk, gulp, shake, cheer }
struct ActiveReaction: Equatable { let kind: BookwormReaction; let startedAt: Date; let id: UUID }
```

`BookwormSprites` gains the following:

- **`eyes(pupil:lid:gaze:)`.** It extends `eyes` (`BookwormSprites.swift:138-153`). Each lens
  interior is 4 cells: `ooww` is left, `woow` is centre (today) and `wwoo` is right.
  Only rows 7–8 change. Row 5, the rim pinned by `BookwormSpriteTests`, never changes. `.half` lid
  moves the one pupil row it has. `pupil: "e"` (error) ignores gaze.
- **`frames(for:pose: .idle)`** is byte-identical to today's `frames(for:)`
  (`BookwormSprites.swift:329-407`), so every existing test passes unchanged.
- **The attentive loop** for `.awake`, `.happy`, `.reading` and `.hungry` is
  `[a(g), a(g), a(g), blink(g)]` at the state's own interval, so it costs no more ticks than idle.
  - For `.reading`: `capped(merge(compose(eyes(gaze: g), mouthSmile), bookOpen))`. The cap and book
    persist, and the eye-track shift is suspended while attentive.
  - For `.happy`: `happyBase` without sparkles.
  - For `.hungry`: the half lid and the frown.
- **`.expectant(g)`** is `[compose(eyes(gaze: g), mouthOpen), shift(same, dy: -1)]` at 0.4 s.
  `mouthOpen` exists (`:175-179`). The cap is kept where the state wears one.
- **`.eager`** is `[shift(expectant(.center) + blush, dy: -1), expectant(.center) + blush]` at 0.4 s.

**Reactions** come from `reactionFrames(_:for:gaze:) -> [PixelGrid]`. Every reaction has at most 3
frames at `SleepMotion.beatFrameInterval` (0.12 s), so a beat lasts at most 0.36 s.

| Reaction | Frames (reuse first) | States allowed |
|---|---|---|
| `perk` | `shift(a(g), dy:-1)` + blush, `a(g)` | awake, happy, reading, hungry |
| `talk` | `compose(eyes(gaze:g), mouthOpen)`, `compose(eyes(gaze:g), mouthSmile)`, `mouthOpen` again. **Sleeping** uses closed eyes + `mouthOpen`/`mouthNeutral` + cap + `stageDots` (it talks in its sleep and never wakes) | all but error |
| `gulp` | digesting frames 0, 1, 2 (`:348-352`, existing); `.reading` lowers the held book for these frames only | awake, happy, reading, hungry |
| `shake` | `shiftRows(a, 2..<13, dx:-1)`, `dx:+1`, `a` (the `curiousTilt` idiom, `:318`) | awake, happy, reading, hungry, digesting |
| `cheer` | happy frames 1, 2, `happyBase` (`:356-360`, existing) | on the completion edge only |

**Authoring rules.** A new `BookwormPoseSpriteTests` checks each one:
- 24 × 24 and the nine palette keys only.
- Head and glasses rows equal the base frame's, apart from pupil cells.
- **A reaction never hides a state mark:**
  - `capped` on every `.sleeping`/`.reading` frame;
  - `stageDots` row 23 on every `.sleeping` frame;
  - red pupils on every `.error` frame.
- `.sleeping`, `.error` and `.digesting` have no gaze variants.
- `reactionFrames.count × beatFrameInterval ≤ SleepMotion.maxDuration` for every reaction.

**Renderer** (`MenuBar/BookwormRenderer.swift:46-85`).
- The key becomes `spriteKey|pose|reaction|frame|size`.
- The pose and reaction segments are **omitted for `.idle` with no reaction**, so every existing
  key stays byte-identical (`BookwormRendererTests` unmodified).
- The page's own key set is at most about 200 per size. A test pins it at ≤ 256.
- The wholesale-wipe bound (`:79`) goes from 512 to 1024 in the same commit. The menu bar's
  `curious(1…99)` keys alone can reach 297, and a wipe is exactly the collateral damage P13 exists
  to avoid.

**Frame memo.** `frames(for:)` is recomposed twice per tick:
- in `BookwormView.body` (`Views/Common/BookwormView.swift:44`);
- in `cachedImage` before its lookup (`BookwormRenderer.swift:67`).

Poses multiply these calls. Add a lock-guarded memo keyed `spriteKey|pose`, **gated on an XCTest
`measure` benchmark written first**, and ship it only if the benchmark moves.

**`BookwormView`** gains `pose: BookwormPose = .idle` and `reaction: ActiveReaction? = nil`.

- The defaults keep every other call site unchanged: `EmptyStateView`, `UploadOverlay`, onboarding,
  `ConnectView`, and the menu bar, which never sees poses.
- **With a reaction and Reduce Motion off:** `TimelineView(.periodic(from: r.startedAt, by: 0.12))`
  with the frame index clamped to the last frame, then back.
- **Reduce Motion:**
  - `reaction` is ignored;
  - `attentive` falls back to `.idle`;
  - `expectant`/`eager` keep frame 0, because that is the armed-drop cue, a state and not a motion.
- The fixed `.frame(width:height:)` stays, so no tick causes layout.

### 6.2 Hotspots (`Views/Sleep/DeskHotspots.swift`, pure)

`deskHotspots(_ layout: DeskSceneLayout) -> [DeskHotspot: CGRect]` returns rectangles in points,
with a bottom-leading origin, derived from **cells** through `DeskSceneSprites.inkBounds`
(`DeskSceneSprites.swift:72`), never from typed points.

| Hotspot | Cells | Source |
|---|---|---|
| `.worm` | cols 30–49 × rows 4–27 | worm ink span (`DeskScene.swift:80-85`) |
| `.lamp` | the lamp's ink bounds | `lampTemplate` (`DeskSceneSprites.swift:134`) |
| `.window` | the window's first glass column (scene col 20) up to col 29, over the glass rows | window at `cellX: 18` (`DeskScene.swift:73`), clipped to stop where `.worm` starts, so the two are disjoint |
| spines | each spine's own rect **plus the 2 pt gap above it** | `BookPileView` (`BookPile.swift:115-121`) |

`DeskHotspotTests` checks these invariants at every `uiScale` step from 0.8 to 1.4:
- whole cells;
- inside the scene;
- pairwise disjoint;
- the lamp and window never enter the pile column (`DeskScene.pileCell`);
- the eye centre lies inside `.worm`.

**`gaze(pointerX:layout:previous:state:) -> Gaze`**, also pure:
- nil pointer → `.center`;
- left of scene col 30 → `.left`, right of col 49 → `.right`, otherwise centre;
- a 1-cell hysteresis on both edges, so a sweep back and forth across a boundary changes the gaze at
  most once;
- `.sleeping`, `.error` and `.digesting` always return `.center`.

### 6.3 The answer ladder (`Views/Sleep/WormAnswers.swift`, pure)

A click steps through the rungs, and one click past the last rung returns to the status sentence.

| State | Rung 1 · what | Rung 2 · when | Rung 3 · last time | Rung 4 · you |
|---|---|---|---|---|
| `.reading`, `.hungry` | "Waiting for a night." / *"The oldest has waited {max oldestAge}."* | lamp on: "Next: {nextRunSentence date}." / *"Scheduled runs use {engine}."* (the tail only when it differs from manual). Lamp off: "The lamp is off — I read when you ask." / *"Press Consolidate now, or light the lamp."* (`.openLamp`) | "Last time I read {e} episodes." / *"+{c} new · {u} updated, in {duration}."* (duration clause dropped when nil; `.openDetails(.pastNights)`) | "{n} questions wait for you." / *"They're in the Inbox."* (`.openInbox`; only when `inbox.total > 0`) |
| `.happy` | "Nothing to read." / *"Everything captured has been filed."* | as above | as above | as above |
| `.sleeping` | "{Stage n · Title}." / *stage detail* | "Running on {lastEngine label}." / *{engineDetail}* | – | – |
| `.digesting` | "Just filed that cycle." / *"+{entitiesCreated} new · {entitiesUpdated} updated."* | as `.happy` | – | – |
| `.error` | "The last cycle failed." / *first clause* (`.openDetails(.lastCycle)`) | "It ran on {lastEngine}." / *{engineDetail}* | the last *successful* cycle | – |
| `.awake` | "I haven't heard from Cicada yet." / *"This fills in as soon as it answers."* | – | – | – |

**Rules.**
- A rung whose facts are nil is **omitted**.
- No rung repeats the status sentence's numeral.
- Relative ages come from `studyRows`' `ageLabel` (`SleepQueueModel.swift:90,121`), already
  resolved by the page. Dates come from the hoisted `nextRunSentence`. The function never calls
  `Date()`.
- The ladder index resets when:
  - the mood's `caseName` changes;
  - the person presses Esc;
  - `SleepMotion.answerDwell` (12 s) has passed with the pointer outside the room and the sentence
    (paused while the pointer is inside).

### 6.4 State × response matrix

"✓" means the response runs. "—" means it is suppressed so it never contradicts state art (R-Z1).

| Mood | Gaze | Perk | Poke (`talk`) | Expectant / eager | Gulp | Shake | Cheer |
|---|---|---|---|---|---|---|---|
| awake | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| happy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | edge |
| reading (cap + book) | ✓ (book held) | ✓ | ✓ | ✓ | ✓ (book lowered) | ✓ | — |
| hungry (half lid) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| digesting | — | — | ✓ | ✓ | ✓ | ✓ | entry |
| sleeping (cap, dots) | — | — | sleep-talk | — (the drop still imports) | — | — | — |
| error (red pupils) | — | — | words only | — | — | — | — |

### 6.5 The completion edge and the cancel fix

- **The pure fix, in `deriveSleepPageMood`** (`SleepMood.swift:108`): `.digesting` requires
  `status.cancelled != true`. Result: a cancel never chews and never says "Filed."
- **`SleepView`'s edge** (`SleepView.swift:299-303`) sets `room.recentCycleCommit` and posts a
  `cheer` only when all of these hold:
  - the edge is running → idle;
  - `cancelled == false`;
  - `error` is empty;
  - `sleepVM.history.first { $0.kind != "decay" }` has loaded.
- **The link** is cleared when it is clicked, when the page disappears, or when the next cycle
  starts.
- **`.whatChanged`** does four things:
  1. opens Details;
  2. sets `sleepVM.expanded` to that commit through `toggleHistory` (`SleepView.swift:539`);
  3. calls `loadDetail`;
  4. runs `proxy.scrollTo("details.pastNights")`.

---

## 7. The room's controls

### 7.1 Spines (`BookPile.swift`, new `SpinePopover.swift`)

- Each spine becomes a `SpineButton` with its own hover `@State`.
- The container's accessibility changes from `.ignore` "N books on the pile"
  (`BookPile.swift:124-125`) to `.contain` "The pile, {k} sources". No total is read there, because
  the sentence already says it.
- **The popover** is 360 pt wide:
  1. **Header:** `OriginMark` · label · `queueRowState` words (`StudyListCard.swift:29-34`), with
     "oldest {age}" beneath.
  2. **Rows:** up to 6 `EpisodeRow`s, newest first, from `episodesForOrigin`. That function is
     hoisted from `StudyListCard.swift:342-349` into `SleepQueueModel.swift`.
  3. **Footer:** "+N more in Details" (opens Details, then scrolls to What's waiting) and "Open in
     Sources ›".
- **"Open in Sources ›"** needs two new pieces:
  - `AppRouter.pendingSourceDetail: String?`, consumed by `SourcesPageView` the way `FeedView`
    consumes `pendingAddSource`;
  - `SourceOverview.owning(origin:in:)`, the inverse of `ownedQueue(from:)`, including the
    `mcp` → `claude-code` rule, with a round-trip test.

  The link is hidden when no source owns the origin, never guessed.
- **Row ↔ spine linking.** Hovering a Details › What's waiting row lifts its spine, and hovering a
  spine tints its row with `surfaceHover` (C I11/I13). Both go through `room.hoveredOrigin`, which
  only the spine and the row read.

### 7.2 The lamp and the whisper line (new `LampPopover.swift`, `ScheduleToggle.swift`)

```
 ┌ When I read ─────────────────────────────────────────┐
 │ ● The lamp is on.                      [ Read on a schedule ●━ ] │
 │ Every day at 03:00 · Next run Sep 24, 3:00 AM         │
 │ Scheduled runs use Ollama. <preview.scheduled.why>    │   ← shown BEFORE any flip
 │ Rhythm and time: Settings → Sleep ›                   │
 └───────────────────────────────────────────────────────┘
 off: "○ The lamp is off." / "I read only when you press Consolidate now."
      "If you light it, scheduled runs would use {engine}. {why}"
```

**The toggle.**
- It writes through `ScheduleToggle.toggled(on:current:)`, hoisted from
  `OnboardingSchedule.toggled` (`Views/Onboarding/OnboardingSleepStep.swift:30-37`):
  - on → daily at 03:00, unless an interval or after-import rhythm already exists (it never
    downgrades one);
  - off → manual, keeping the hour and minute.
- Then `sleepVM.updateSchedule` (`ViewModels/SleepViewModel.swift:329`).
- It is disabled while the write is in flight.
- On failure: an inline danger caption, and the toggle snaps back to `schedule.enabled`.

**The engine line.**
- It is `Copy.scheduledRunsOn(engine: preview.scheduled.engine)` + " " + `preview.scheduled.why`
  (`Models/SleepEngine.swift:25-38`).
- Unlike the old footer, it shows **always**, not only on a difference, because this is the moment
  of choice (ruling 4).
- It is absent when `enginePreview` is nil.

**The Settings link** is `SettingsSectionLink(section: .sleep …)` (`SettingsSectionLink.swift:27-39`).
If Track O ships row anchors, it becomes `row: .sleepRuns`.

**The whisper line** is `moon.zzz` + `scheduleSentence` (`StudyListCard.swift:44-55`), then
" · " + `nextRunSentence` when not manual, else " — the lamp is off". The whole line is a `Button`
that opens the same popover: it is the lamp's twin and its keyboard path.

**The lamp art never previews.** It flips only when `sleepVM.schedule` changes (P11).

### 7.3 The window (new `WindowWeather.swift`; `DeskSceneSprites.swift`, `DeskPalette.swift`, `DeskScene.swift`)

```swift
enum WindowWeather: String, CaseIterable { case night, dawn, clear, fair, overcast, storm, curtains
    static let all: [WindowWeather] = [.night, .dawn, .clear, .fair, .overcast, .storm, .curtains] }
func windowWeather(for mood: BookwormState) -> WindowWeather   // total; reads nothing else
```

| Mood | Weather | Legend sentence (twin) | Art (on the lattice, `DeskPalette`) |
|---|---|---|---|
| `.sleeping(any stage)` | night | "A cycle is running." | today's crescent + 4 static stars, moved off the cells the worm covers |
| `.digesting` | dawn | "A cycle just finished." | `c` over `t`, a half sun behind the right slope |
| `.happy` | clear | "Caught up. Nothing waiting." | day sky `y`, haze `v`, meadow bowl `g`/`h`, dandelions `s` |
| `.reading` (and `.curious`, for totality) | fair | "Things are waiting to be read." | clear + two clouds `j`/`x`, the sun half behind one |
| `.hungry` | overcast | "Overdue: it's been a while." | `x` sky, `N`-underside clouds, **dandelions closed** |
| `.error` | storm | "The last cycle failed." | `K` sky, `N`/`x` clouds, `U` rain, a static bolt `s`, the meadow as a `d` silhouette |
| `.awake` | curtains | "No reading yet." | `c` fabric with a `p` fold every third column |

**Implementation** (from M §3.1 and §5):
- The window prop splits into `window` (frame, mullions and sill: today's grid,
  `DeskSceneSprites.swift:96-121`, with every glass cell transparent) and `pane` (a 16 × 16 ink
  grid authored flush to column 0). The pane sits at `cellX: 20, cellY: 4`, z below the frame, so
  the mullions occlude it for free.
- `DeskPalette` goes from 13 to 20 keys (`y v j x K N U`, M §5.1), still disjoint from the worm's
  nine and free of reserved state hexes.
- Panes go through `PixelRenderer.sceneCache` with the key `desk.pane|<weather>|<pt>` (P13).
- The worked grids are in M §5.2. The panel's script is at
  `session scratchpad/round3/design/mascot-meadow-work/panes.py`.
- **Occlusion rule (test):** the sun, moon, stars and bolt are 100 % visible beside the worm's
  union ink over every page-state frame, pose and reaction, and never under a mullion. Every cloud
  is ≥ 50 % visible.
- **A mood change** crossfades two stacked pane images over `SleepMotion.weatherDuration` (0.4 s).
  Under Reduce Motion it jumps.
- **Refused:** drift, the storm flash, and any weather driven by a count or the clock.

**The legend popover** (window click) lists the seven rows of `WindowWeather.all`, each with its pane
thumbnail rendered from the same cache, and highlights the current one. Its header reads: *"The
window shows how Cicada is doing, not the time of day."* `HowSleepWorksContent` gains one pointer
line to it and does not copy the list (P16).

### 7.4 Feeding (new `RoomFeed.swift`; ships after Track I)

- **The drop target** is the whole room: `.onDrop(of: [.fileURL], delegate: RoomDropDelegate)`.
  - The innermost target wins over Track I's window-level veil.
  - `dropUpdated` feeds the same pure `gaze(pointerX:…)` to aim the `expectant` pose at the drag
    point, writing only on change.
- **The guard** `feedGuard(urls:home:env:) -> FeedRefusal?` is pure and lives in (or is contributed
  to) `IntakeRouter`, so every door enforces it. URLs are normalised with
  `resolvingSymlinksInPath().standardizedFileURL`, then checked in this order:

  | Resolves under, or is | Refusal line |
  |---|---|
  | `~/.claude/` or `$CLAUDE_CONFIG_DIR` | "Claude Code sessions reach me on their own." |
  | `~/.codex/` | "Codex sessions reach me on their own." |
  | `~/.cicada/` | "That's my own folder — I can't eat that." |
  | a type the router rejects | "I can't read that yet." / *"Chat exports, bookmarks, feeds and notes work."* |

- **Accepted:** `IntakeRouter.present(urls:from: .sleepRoom)`. The name follows Track I's final API.
  The Z-side adapter needs three outcomes: `accepted`, `refused(reason)` and `unreachable`.
  - The router owns the preview sheet, the counts, the bank choice and `store.intakeInFlight`
    (`Sync/Store.swift:90`).
  - The mood becomes `.reading` by the existing rule (`SleepMood.swift:111-113`). The window turns
    `fair` and the pile restacks.
- **No numbers in feed lines.** The sheet has them (R-Z3, R-A5).

---

## 8. Interaction catalogue

Every duration below is a `SleepMotion` constant (§10). "RM" means Reduce Motion.

| # | Trigger | Response | Constant | RM fallback | Text twin | Accessibility |
|---|---|---|---|---|---|---|
| I1 Gaze | `onContinuousHover` on the **room box** only | `room.gaze = gaze(…)` **only when it changes**; the worm shows `.attentive(g)`; exit → `.idle` | none (pose swap on the next state tick) | no gaze; frame 0 held | none (response art) | none |
| I2 Perk | pointer enters `.worm`; cooldown `perkCooldown` 2 s | `perk` beat, then attentive(center) while inside; pointing-hand cursor | `beatFrameInterval` × 2 = 0.24 s | no beat; cursor still changes | `.help(current sentence)` | – |
| I3 Poke | click on `.worm`; Space/Return with focus (`.focusable()` + `.onKeyPress`, macOS 14); VO default action; context menu "What are you doing?" | `talk` beat (sleep-talk while `.sleeping`, none while `.error`); the slot cross-fades to the next rung (§6.3) | beat 0.36 s; `sentenceDuration` 0.18 s | no beat; instant swap | the sentence is the text | `AccessibilityNotification.Announcement(rung).post()` |
| I4 Dismiss | click past the last rung, Esc, mood change, or `answerDwell` 12 s outside room + sentence | back to the status sentence | `sentenceDuration` | instant | – | announce only on Esc |
| I5 Hover spine | `onHover` on a `SpineButton` | lift 2 pt (`.offset` on a SwiftUI shape, not pixel art) + opacity 0.85 → 1.0; matching row gets `surfaceHover` | `hoverDuration` 0.15 s | opacity only | `.help("{label} · {n} waiting · oldest {age}")`, or "{a} of {b} read" while running | Button "{label}, {n} waiting, oldest {age}" (`StudyListCard.rowAccessibilityLabel`, `:246`) |
| I6 Click spine | tap / Space | `SpinePopover` (§7.1) | system | system | the popover text; Details › What's waiting | focus into the popover; Esc closes |
| I7 Hover row | `onHover` on a What's-waiting row | its spine lifts (I5 in reverse) | `hoverDuration` | opacity only | the row | – |
| I8 Hover lamp | `onHover` on `.lamp` | cursor; **the art never changes** | – | – | `.help(scheduleSentence · next run)` | Button "Lamp, on. Every day at 03:00. Next run …" / "Lamp, off. Sleep runs only when you ask." Hint "Opens the schedule". |
| I9 Click lamp or whisper line | tap / Space | `LampPopover` | system | system | the whisper line | as I8 |
| I10 Toggle | `Toggle("Read on a schedule")` | `ScheduleToggle` → `updateSchedule`; lamp and whisper line flip on the response | none (a state change of art, P11) | same | whisper line, popover sentence | real `Toggle` label |
| I11 Hover / click window | `onHover` / tap on `.window` | cursor + `.help("{title}: {meaning}")`; click opens the legend | system | system | legend | Button "Window, {title}: {meaning}", hint "Shows what the sky means" |
| I12 Drag enters room | `dropEntered`, `hasItemsConforming(to: [.fileURL])` | `.expectant(gaze toward drag x)`; dashed 2 pt `accent` inset outline (chrome); sentence "Is that for me?" / *"Chat exports, bookmarks, feeds and notes."* (while running: *"I'll read it next cycle."*) | outline `hoverDuration` | outline instant; expectant frame 0 held | the sentence | drag is pointer-only; see I16 |
| I13 Drag over worm | drag point in `.worm` | `.eager`; "Drop it on me." | pose loop 0.4 s (G107 R8 band) | eager frame 0 | sentence | – |
| I14 Drag exits | `dropExited` | pose → idle/attentive; outline clears; sentence → status | `hoverDuration` | instant | – | – |
| I15 Drop | `performDrop` | guard → refused: `shake` + refusal line. Accepted: `gulp` + router sheet. Unreachable (`liveness == .stale`): "I can't reach Cicada right now." / *"Try again once the page is live."* Asleep: no beat, "Got it. I'll read it after this nap." | beat 0.36 s | no beats; lines still show | the sentence; the pile/queue (quantity) | announcement of the line |
| I16 Feed without a pointer | worm action "Feed a file…" or its context menu | `NSOpenPanel` (multiple, folders allowed) → I15 | – | – | the action name | named action on the worm |
| I17 Real completion | running → idle, `!cancelled`, no error | `cheer` beat, then the existing 6 s `.digesting`; tail T7 "See what changed ›"; the window goes night → dawn → clear/fair | beat 0.36 s; `weatherDuration` 0.4 s | no beat; the window jumps | tail + Details › Past nights | announcement "Sleep finished." + worm action "What changed" while the link lives |
| I18 Cancel / failure | the same edge with `cancelled` or `error` | no cheer, no digesting; T4 or L6/T3; strip frozen (P15); window storm on error | – | – | Details › Last cycle | announcement of the lead |
| I19 Weather change | `windowWeather(mood)` changes | two-pane crossfade | `weatherDuration` 0.4 s | jump | qualifier word / sentence + legend | none (the sentence already carries it) |
| I20 Details | click the disclosure row | expand/collapse; `if open {}` (not opacity) | `disclosureDuration` 0.15 s | instant | – | `accessibilityValue("expanded"/"collapsed")` |
| I21 Sentence action | click the tail link | Retry / Inbox tab / Details section + `scrollTo` / lamp popover / What changed | `disclosureDuration` | instant | the link text | plain `Button` |
| I22 Consolidate / Cancel | unchanged (`SleepHero.swift:409-467`) | on macOS 26, the page's one `.glassProminent` (R-M5); otherwise today's capsule | – | – | caption `Copy.runsOn` | unchanged |

**Pointer style.** On macOS 15+, `.pointerStyle(.link)`. On macOS 14, `NSCursor.pointingHand`
push/pop inside each leaf's `onHover`. Inert props get no cursor change.

---

## 9. Data sources: every number and state on the default view

`SleepView` resolves everything once per body into a pure `SleepPageModel`. That also removes the
duplicated `studyListRows` evaluation (`SleepView.swift:244-252`, read twice). No new endpoint and
no new fetch are needed. The backend is untouched.

| On screen | Swift source | Wire origin | When unknown |
|---|---|---|---|
| Mood (worm, window, sentence rows) | `deriveSleepPageMood` (`SleepMood.swift:94-131`), with the cancel and active-stage fixes | `/sleep/status` + SSE `sleep` + `Store.intakeInFlight` (`Sync/Store.swift:90`) | `.awake` → curtains, "Listening." |
| Lead numeral `{n}` | `heroCount(mood, debt)` (`SleepHero.swift:17`) ← `resolveSleepDebt` (`SleepMood.swift:27-47`) | SSE `unprocessedCount` or `/sleep/status.debt` | L2 / L11 (no numeral) |
| "Reading {a} of {b}" | sums of `resolveOriginCounts` (`SleepMood.swift:63-70`) | `queue_by_origin` / `read_by_origin` | L4 "Reading…" |
| Active stage (L5, T2, strip, sleep-talk dots) | **new** `activeStage(completed: status.stage)` | `SleepStatusResponse.stage` = completed stages (`api/services/sleep_cycle.py:978,1027`) | – |
| Qualifier word / tone | `heroQualifier` (`SleepHero.swift:42`), `sleepDebtBracketColor` (`SleepMood.swift:167-177`) | derived | plain |
| Tail news | `status.error`, `.cancelled`, `.episodesQueued > .episodesTotal`, `.indexWarning` | `/sleep/status` | row skipped |
| "It's been {d} days" | `debt.hoursSinceLastCycle / 24` | debt | row skipped |
| Spines (origin, count, height) | `bookPileLayout(originVolumes(…))` (`BookPile.swift:43-98`) | `sleepVM.queuedEpisodes` + origin dicts | no spines |
| Lamp lit | `sleepVM.schedule.enabled` (`SleepView.swift:653`) | `GET /sleep/schedule` | unlit |
| Whisper line | `scheduleSentence` (`StudyListCard.swift:44-55`) + hoisted `nextRunSentence` (from `:357-367`, reading `status.nextSleepAt`) | schedule + `/status` | "Next run —" with a hover reason (R-A14) |
| Button caption | `sleepVM.enginePreview?.manual` (`SleepHero.swift:395-399`) | `GET /sleep/engine` | caption absent |
| Button enabled | `queuedEpisodes.count > 0`, `!isCancelling`, status loaded | – | disabled, never hidden |
| Staleness chip | `liveness` (`SleepView.swift:389-396`) | `Snapshot.refreshedAt` | no chip |
| Window weather | `windowWeather(for: mood)` | – | curtains |

**Answers, popovers and feed only:**

| Figure | Source |
|---|---|
| Oldest age | `studyRows(…).oldestAge` (`SleepQueueModel.swift:103-131`) |
| Last cycle | `sleepVM.history.first { $0.kind != "decay" }` (`SleepHero.swift:378`), plus `SleepHistoryPresentation.durationText` |
| Digesting counts | `status.entitiesCreated` / `entitiesUpdated` |
| Engine | `status.lastEngine` / `engineDetail` |
| Scheduled engine | `enginePreview.scheduled` |
| Inbox | `store.status.value?.inbox.total` |
| Spine popover rows | `episodesForOrigin` |
| Feed | `IntakeRouter` outcome (no digits on this page) |

**Numbers budget (R-A15), default view.**
- The lead numeral, the per-source spine counts, the whisper line's times, and the chip's time.
- Nothing else.
- Every other figure is on a second surface (Details, a popover, an answer), opened on purpose.

---

## 10. Motion and performance

**`SleepMotion` additions** (`Views/Sleep/SleepMotion.swift`; they stay there for the folder lint,
and their names mirror M1's `CicadaMotion`):

```swift
static let beatFrameInterval: TimeInterval = 0.12   // sprite interval for reactions; pinned == BookwormSprites.reactionInterval
static let maxBeatFrames = 3                         // ⇒ every beat ≤ 0.36 s ≤ maxDuration
static let hoverDuration: TimeInterval = 0.15        // spine lift, drop outline
static let sentenceDuration: TimeInterval = 0.18     // status ⇄ answer cross-fade (opacity only)
static let weatherDuration: TimeInterval = 0.4       // pane crossfade on a mood change (== maxDuration)
static let perkCooldown: TimeInterval = 2            // a rate limit, not an animation
static let answerDwell: Duration = .seconds(12)      // a dwell, not an animation; paused while hovered
static func hover(reduceMotion: Bool) -> Animation?    { reduceMotion ? nil : .easeOut(duration: hoverDuration) }
static func sentence(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeInOut(duration: sentenceDuration) }
static func weather(reduceMotion: Bool) -> Animation?  { reduceMotion ? nil : .easeInOut(duration: weatherDuration) }
```

**Budget.**

| Situation | Cost |
|---|---|
| Idle, pointer away | identical to v3: one worm `TimelineView` at the state interval (`BookwormView.swift:50`); the strip's timeline runs only while a pip is active; **collapsed Details builds nothing** (no queue `LazyVStack`, no history, no tiles, and no sparklines at all), so the page is strictly cheaper than v3 |
| Pointer moving over the room | `onContinuousHover` closure = arithmetic + compare; `room.gaze` written **only on change**, at most about 2 writes per sweep; only `WormStage` reads it (`@Observable` scoping), so `SleepView.body` never re-evaluates |
| Beat | one `TimelineView` at 8.3 Hz for ≤ 3 ticks, cleared by `.task(id: reaction.id)` |
| Hover (spine, lamp, window) | leaf `@State`; one shape's opacity/offset |
| Weather change | two stacked cached `Image`s, opacity, 0.4 s, on a mood change only |
| Off the page | torn down (`ContentView` switch); nothing ticks |

**Lints** (extend `SleepNumbersLintTests`):
- no literal `duration:` under `Views/Sleep/` (existing, `:103`);
- the new constants are ≤ `maxDuration` and `beatFrameInterval × maxBeatFrames ≤ maxDuration`;
- `hover`, `sentence` and `weather` return nil under Reduce Motion;
- **`onContinuousHover` appears in exactly one file under `Views/Sleep/` (`StudyRoom.swift`)**;
- **no line that mentions `BookwormView(` or `WormStage` under `Views/Sleep/` carries `.offset(`,
  `.scaleEffect(`, `.rotationEffect(` or `.spring(`**. The worm's lattice placement moves into
  `WormStage` in an allow-listed form (R-Z4).

**Acceptance (the engineer measures).** On the demo bank at `uiScale` 1.0, record Activity Monitor
CPU in the PR:
- idle for 60 s: no higher than v3;
- a 10 s pointer sweep over the room: within +3 points of idle.

---

## 11. Accessibility

- **Order** (`accessibilitySortPriority`):
  1. the sentence;
  2. the worm;
  3. the window;
  4. the lamp;
  5. the spines, largest first;
  6. Consolidate/Cancel;
  7. the whisper line;
  8. Details.

  Full Keyboard Access reaches every hotspot, because each is a `Button`.
- **The worm:**
  - label "Bookworm, {state.title}";
  - **value = `sleepDebtBracketText`** (P8; the twelve asserted strings keep their reader);
  - hint "Click to ask what it's doing. Drop a file to import it.";
  - default action: poke, which announces the rung;
  - named actions:
    - "What are you doing?" announces **all** rungs joined;
    - "Feed a file…" (once Track I lands);
    - "What changed" while T7 lives.
- **Announcements** fire only for things the person caused (a poke, Esc, a drop result, a
  completion) and never for passive state changes: a running cycle would chatter.
- **Colour is never the only carrier:** "overdue" and "failed" are words; the evidence of weather is
  the legend.
- **Reduce Motion:** no gaze, no beats, no crossfades. Expectant/eager frame 0 is kept as the armed
  drop cue.
- **Increase Contrast:** the drop outline uses `textPrimary`; the optional sky band (Z9) is hidden.
- **Reduce Transparency:** M1's `liquidGlass` fallback makes Consolidate opaque.
- **Hover-only information is refused.** Every tooltip is reachable by click, focus or VoiceOver.

---

## 12. Rulings: kept, amended, new

| Ruling | Source | Verdict | Why |
|---|---|---|---|
| Mascot is a status surface; ≥ 2 frames per *state*; intervals 250–800 ms | G107 (`memory-evolution.md:669`); mascot plan R8 | **Keep** | Reactions are not states. State loops keep their intervals; beats have their own ≤ 0.36 s cap. |
| Frames baked, consumers never merge (R2); whole cells (R3); colour never tinted (R4) | G107 / mascot plan | **Keep, extended** by R-Z4 | Poses and reactions are composed inside `BookwormSprites`, and a hop is a cell shift. |
| One mascot cache (R5) | mascot plan; `BookwormRenderer.swift:46-85` | **Keep**, key extended, wipe bound 512 → 1024 | Idle keys are byte-identical. |
| Precedence (R6) | `SleepMood.swift:94-131`; `BookwormState.swift:153-172` | **Keep**, plus two correctness fixes | Cancelled ⇒ no digesting. `activeStage` (R-Z14) in both derivations. No precedence change. |
| Reduce Motion holds frame 0 (R7) | G107 | **Keep, extended** | It also removes gaze, beats and crossfades. The armed-drop pose stays as a static cue. |
| "Not built: sound, **drag, feeding mechanics**, any toggle beyond Reduce Motion" | G107 | **Amend** (spec decision 5) | Feeding = a drop that imports through `IntakeRouter` (R-Z10). The worm is never draggable. No sound. No new toggle. |
| Per-cycle estimates deferred | G107 | **Keep** | Answers use measured `durationMs` or omit the clause. The ban on "est"/"~" extends to answers. |
| `.curious` never on the Sleep page; menu-bar derivation unchanged | G125 R2 | **Keep** | `windowWeather` maps `.curious` only for totality. The menu bar gets only the stage-number fix. |
| Prose is clock-free | G125 R8; `SleepBubble.swift:17-20` | **Keep, extended** to the sentence, answers and feed lines | `answerDwell` is a UI timeout, not text chosen by the clock. |
| R-A1 two columns ≥ 1000 pt | round-2 spec `:46` | **Amend → one 760 pt column** | Room + sentence + button is the minimal page. The right column was a Sources duplicate plus history, now in Details. |
| R-A2 fixed-height scene, one lattice; scene inert and hidden | round-2 `:50-61`; `DeskScene.swift:162-163` | **Keep the art rule; add a hotspot layer** (R-Z8) | Interaction is a separate, tested layer derived from the same layout. |
| R-A3 / P11 lamp = schedule, *the one* data-driven bit | round-2 `:62-64` | **Amend** | Two data bits (lamp = schedule, window = mood weather), both with twins. The lamp is also a control, behind the words (R-Z9). |
| R-A4 hero count + chip; bubble above the worm | round-2 `:66-69` | **Amend** | The count and qualifier become the sentence lead. The bubble is retired (R-Z5). `heroCount`/`heroQualifier`/`bracketTail`/`sleepDebtBracketText` stay. |
| R-A5 meter never without its noun; "Rested" spelled only in `SleepHero.swift` | round-2 `:70-73`; `SleepNumbersLintTests.swift:57` | **Keep** | The meter lives in Details, still drawn by `SleepHero.swift`. |
| R-A6 three measured tiles | round-2 `:74-77` | **Keep, relocated** to Details › Readout | – |
| R-A7 / G125 R10 one Consolidate control | round-2 `:78-81`; `FixWaveTests.swift:53-68` | **Keep** | No hotspot calls `triggerManually` or `cancel`. While running, the one control is Cancel. |
| R-A8 strip always shown; caught-up worm at its end | round-2 `:82-91` | **Amend** (R-Z6) | News only. The duplicate worm is deleted. |
| R-A9 queue card with schedule row and footer | round-2 `:92-97` | **Amend** | The rows go to Details. The schedule row and next run become the whisper line. The scheduled engine moves to the lamp popover, shown always there. |
| R-A10 Memory sources on Sleep | round-2 `:98-102` | **Retire from Sleep** | Sources v2 draws the same `sourcesOverview` projection. The series functions move to `Views/Sources/`. |
| R-A11 recent consolidations | round-2 `:103-106` | **Keep, relocated** (Past nights) | The "What changed ›" link lands there. |
| R-A12 liveness; errors at full contrast | round-2 `:107-109` | **Keep** | Applied to the room, the sentence and the Details cards, never to the chip or Last cycle. |
| R-A13 rule 1 "Idle is still" | round-2 `:110-112`; `SleepView.swift:176-183` | **Amend** (R-Z12) | Input-driven response art plus exactly two state beats (cheer, weather crossfade). |
| R-A13 rules 2–4 (≤ 400 ms, named constants, Reduce Motion terminal frame, no spinner) | same | **Keep** | §10. |
| R-A14 `—` is a value; R-A15 numbers budget; R-A16 backend additive | round-2 `:113-124` | **Keep** | §9. The backend is not touched at all. |
| P10 no painted books | G125 v3 | **Keep** | No pane contains a book shape; the pile column stays reserved. |
| P12 one lattice | G125 v3 | **Keep** | The pane is on the lattice; hops are sprite shifts. |
| P13 separate caches | G125 v3 | **Keep** | Panes go through `sceneCache`, poses and reactions through the mascot cache. |
| P14 nightcap baked | G125 v3 | **Keep, extended** | A reaction never hides the cap, stage dots or red pupils. |
| P15 strip freezes on cancel/failure | G125 v3 | **Keep** | The frozen strip is the news that makes it visible. |
| P16 one prose source | G125 v3 | **Keep, extended** | `SleepStages.all` feeds L5/T2; `WindowWeather.all` is the only legend. |
| P17 no figure twice | G125 v3 | **Refine** (R-Z7) | "…on the default view". |
| G125 v3 "no time-of-day sky; state outranks the clock" | G125 row | **Keep** | The weather is state, never the clock. The legend says so. |
| G125 (4) schedule frequency lives in Settings → Sleep | G125 row | **Amend, narrowly** | The lamp toggles on/off through the shared rule; rhythm and time stay in Settings. |
| G126 one-shot import behind the Feed `+` | CLAUDE.md | **Amend** (with Track I) | The worm is a door onto the one `IntakeRouter`, not a second pipeline. |
| Onboarding-found: schedule "never a one-tap toggle" | `onboarding-found.md:301` | **Consistent** | Two steps, with the scheduled engine and its reason on screen before the flip. |
| `DeskPalette` exactly 13 keys; static four-star window | `DeskPaletteTests.swift:19`; `DeskSceneSpritesTests` | **Amend** | 20 keys, still disjoint from the worm's nine; window = frame + pane; night keeps four stars on visible cells. |
| Capture rail: `~/.claude` transcripts never read elsewhere | CLAUDE.md "Awake" | **Keep, enforced at the door** | The `feedGuard` refusals. |
| Ruling 4: scheduled cycles never spend plan quota, shown not hidden | TODO; spec decision 3 | **Keep, strengthened** | The lamp popover shows `preview.scheduled` before the toggle. |
| No prices or tokens | 2026-09-03 | **Keep** | – |
| R-M3 display font ≥ 22 pt; R-M4 motion constants; R-M5 one `.glassProminent` per page; R-M6 no painted art in the pixel room | round-3 spec | **Apply** | 30/22 pt serif sentence; `SleepMotion` constants; Consolidate is the glass action; nothing painted enters the room. |
| `SettingsSectionLink` single writer | `SettingsSectionLink.swift:17-39` | **Keep** | The lamp popover uses it (and `row:` if Track O adds one). |
| G127 mascot identity | `memory-evolution.md:689` | **Out of scope** | The pose and reaction API is character-agnostic, and the window, weather and hotspots are character-independent. |
| **R-Z1 … R-Z14** | §3 | **New** | To be recorded in the round-3 spec under Track Z, in G125's row as "v4", in G107's row (the feeding amendment) and in CLAUDE.md's Sleep-page and Mascot-states paragraphs. |

**Decisions taken without the owner (reversible on the trigger named).**
1. **One column, with the breakdowns in Details.** Trigger: the owner says the page feels empty, or
   misses the history at a glance. Revert R-A1 for Past nights only.
2. **The bubble is retired for the sentence.** Trigger: the live check shows the voice no longer
   reads as the worm's. Fallback: a 6 pt tail on the sentence slot pointing at the worm's head
   column.
3. **The lamp toggles.** Trigger: any report of a schedule turned on by accident.
4. **The window weather.** Trigger: the day panes glare in dark mode. The fix is art (a softer
   `y`), never a mode switch.

---

## 13. Defects fixed inside the track

1. **The stage off-by-one** (Instrument), verified: `sleep_cycle.py:978,1027`,
   `SleepMood.swift:103`, `BookwormState.swift:159`. The fix is `activeStage(completed:)`.
   `SleepMoodTests` and `BookwormStateTests` update their *inputs*; the asserted strings survive.
2. **A cancel "digests"** (Companion), verified: `SleepView.swift:299-303` and
   `SleepMood.swift:108-110`. The fix is in the pure function (§6.5). The menu-bar edge
   (`Sync/Store.swift:424`) is noted for its owner, not changed here.
3. **Invented stage lines** (Instrument): `SleepBubble.swift:36-37` asserts a contradiction and a
   habit on every cycle.
   - Stage 3 becomes "Checking for contradictions."
   - Stage 4 becomes "Looking for habits."
   - No test pins the old strings.
4. **Per-tick sprite recomposition:** `BookwormView.swift:44` and `BookwormRenderer.swift:67`.
   Benchmark first (§6.1).
5. **`studyListRows` computed twice per body** (`SleepView.swift:244`): `SleepPageModel` fixes it.
6. **The bubble reflows the room, and its tail misses the worm** (`SleepBubble.swift:77-78,119`).
   Dissolved by R-Z5.
7. **Spine count text is literal `.white`** (`BookPile.swift:149`). It moves to a theme token when
   `SpineButton` is written (and M2's sweep would catch it anyway).
8. **Two of the night window's four stars are hidden behind the worm** (Meadow's script). The night
   pane moves them.

---

## 14. Task outline (Workflow track Z)

Rules for every task:
- one commit per task with its tests, on a `dev` worktree;
- per-task implement plus review, as in `working-method.md`;
- baselines: Swift 1012 passing, backend 2225 (untouched);
- green throughout: `FixWaveTests`, `SleepNumbersLintTests`, `SleepHeroTests` (the twelve bracket
  strings), `BookwormRendererTests`, `BookwormSpriteTests`, `DeskSceneLayoutTests`,
  `FontLiteralLintTests` and `ThemeTokenTests`.

| # | Task | Files | Tests | Depends on |
|---|---|---|---|---|
| **Z0** | **Honesty fixes, no visible layout change:** `activeStage` in both derivations; cancelled ⇒ no digesting; honest stage lines; hoist `episodesForOrigin` → `SleepQueueModel`, `nextRunText` → pure `nextRunSentence`, `OnboardingSchedule.toggled` → `Views/Sleep/ScheduleToggle.swift` (onboarding re-pointed, so Track I may delete its step without deleting the rule); `SourceOverview.owning(origin:in:)` | `SleepMood.swift`, `MenuBar/BookwormState.swift`, `SleepBubble.swift`, `SleepQueueModel.swift`, `StudyListCard.swift`, `OnboardingSleepStep.swift`, `Models/SourceOverview.swift` | `SleepMoodTests` / `BookwormStateTests` inputs; `test_mood_isNotDigesting_afterACancelledCycle`; `ScheduleToggleTests`; `SourceOwningTests` round-trip | – |
| **Z1** | **`SleepPageModel`**: one resolve per body | `SleepView.swift` | `SleepPageModelTests` (every §9 row from fixtures; SSE-over-REST precedence) | Z0 |
| **Z2** | **The sentence + control row + whisper line:** `RoomSentence.swift` (`SentenceLine`, `roomSentence`) and its view (New York fallback until M1); `SleepControlRow` in `SleepHero.swift`; the bubble deleted from the page | `RoomSentence.swift` (new), `SleepHero.swift`, `SleepView.swift`, `SleepBubble.swift` | `RoomSentenceTests`: L1–L11 × T1–T14 precedence, lengths, no "!"/`%`/estimate words, numeral parity with `heroCount`, determinism; `FixWaveTests` unchanged | Z1 |
| **Z3** | **One column + Details + conditional strip:** retire the two-column `SleepLayout`; `SleepDetails.swift` (Last cycle, What's waiting, Readout, Past nights; `@AppStorage`; `ScrollViewReader` ids); `StudyListCard` loses its schedule row and footer; strip visibility predicate; delete the caught-up worm; `MemorySourcesCard` off the page, series functions → `Views/Sources/ActivitySeries.swift` | `SleepView.swift`, `SleepDetails.swift` (new), `StudyListCard.swift`, `SleepStageStrip.swift`, `SleepStages.swift`, `MemorySourcesCard.swift` → `ActivitySeries.swift` | `SleepLayoutTests` rewritten (liveness half unchanged); `MemorySourcesTests` → `ActivitySeriesTests`; `StudyListCardTests` / `SleepQueueCardV3Tests` updated; strip predicate test | Z2 |
| **Z4** | **Sprite poses + reactions:** `BookwormPose.swift`; `eyes(gaze:)`, attentive / expectant / eager, `reactionFrames`; renderer key + 1024 bound; `BookwormView` params; frame-memo benchmark (ship only if it moves) | `MenuBar/BookwormPose.swift` (new), `BookwormSprites.swift`, `BookwormRenderer.swift`, `Views/Common/BookwormView.swift` | `BookwormPoseSpriteTests` (§6.1 rules); `frames(for:pose:.idle) == frames(for:)` for every state; idle keys unchanged; page key set ≤ 256 per size | – (parallel with Z1–Z3) |
| **Z5** | **The room responds:** extract `StudyRoom.swift` from `deskCard` (`SleepView.swift:648-673`); `RoomModel` (`@Observable`); `DeskHotspots.swift`; `WormStage` leaf (gaze, perk, poke → `talk` + `WormAnswers`, dwell, Esc, focus, keys, a11y element, actions, announcements, pointer style); the two new lints | `StudyRoom.swift`, `RoomModel.swift`, `DeskHotspots.swift`, `WormAnswers.swift` (new), `SleepView.swift`, `SleepMotion.swift`, `Theme/Copy.swift` | `DeskHotspotTests`; `GazeTests` (3 poses, hysteresis ≤ 1 change per boundary sweep, suppressed states); `WormAnswersTests` (ladders, omission, no repeated numeral, clock-free); lint tests | Z2, Z4 |
| **Z6** | **Props as controls:** `SpineButton` + `SpinePopover` + `AppRouter.pendingSourceDetail` consumer; row ↔ spine hover; `LampPopover` (toggle, engine line always, Settings link); the whisper line opens it | `BookPile.swift`, `SpinePopover.swift`, `LampPopover.swift` (new), `Support/AppRouter.swift`, `Views/Sources/SourcesPageView.swift`, `StudyListCard.swift` | `BookPileTests` a11y labels; `AppRouterTests` (stage + consume once); lamp popover engine-line composition (pure) | Z3, Z5 |
| **Z7** | **Completion edge:** `cheer` + `recentCycleCommit` + T7 + `.whatChanged` (Details open, history expand, scroll) | `SleepView.swift`, `RoomModel.swift`, `RoomSentence.swift` | edge tests: completed ⇒ cheer + link; cancelled / failed ⇒ neither; link cleared on click, disappear, next run | Z5, Z3 |
| **Z8** | **Window weather:** `WindowWeather.swift`; `DeskPalette` +7; window → frame + pane; seven panes; crossfade; `.window` hotspot + legend popover; `HowSleepWorks` pointer line | `WindowWeather.swift` (new), `DeskSceneSprites.swift`, `DeskPalette.swift`, `DeskScene.swift`, `HowSleepWorks.swift`, `StudyRoom.swift` | `WindowWeatherTests` (total; quantity never changes it; no `Date(`); `WindowSpritesTests` (frame identity, pane bounds, occlusion over the union ink incl. poses, four night stars; opt-in `CICADA_WRITE_COMPOSITES=1` PNGs for the art check); `DeskPaletteTests` → 20; `DeskSceneLayoutTests` z-order | Z5 (hotspot); the art can start after Z0 |
| **Z9** | **Feeding** (after Track I's `IntakeRouter`): `RoomDropDelegate`, `feedGuard` (into the router if Track I has not), the adapter, poses, gulp/shake, feed lines, "Feed a file…" action + context menu, T13 enabled | `RoomFeed.swift` (new), `StudyRoom.swift`, `RoomSentence.swift` | `FeedGuardTests` (each root incl. via symlink; `~/Downloads/conversations.json` accepted); outcome → line/beat table with a router fake; asleep drop keeps `.sleeping` | Z5, **Track I** |
| **Z10** | **Meadow pass on the page** (after M1): `displayFont` in the sentence; `.glassProminent` Consolidate; **optional** sky band (M §6: `SkyBand`, `CicadaTheme.skyBandOpacity`, `SkyBandContrastTests`), shipped only if the screenshots say calm | `RoomSentence.swift`, `SleepHero.swift`, `SleepView.swift`, `Theme/CicadaTheme.swift` | the font lint (`.custom(` only in the theme); `SkyBandContrastTests` if the band ships | **M1** |
| **Z11** | **Live verification + screenshots** (§15); retake the README Sleep screenshot from the demo bank (G90 practice) | – | – | all |
| **Z12** | **Docs:** CLAUDE.md "Sleep page" (v4) and "Mascot states" paragraphs; G125 row "v4"; G107 amendment; TODO rulings; round-3 spec Track Z rulings (R-Z1…R-Z14) | `CLAUDE.md`, `docs/goals/*`, spec | – | all |

Z0–Z8 do not depend on M1 or Track I, so the track ships "more interactive" before either lands.
Z9 and Z10 are the only gated tasks.

---

## 15. Live verification (Z11; `make dev`, demo bank)

1. **Widths and zooms:**
   - widths 760 / 1200 / 1560; zoom 0.8 / 1.0 / 1.4; light and dark;
   - the room fits at 1.4;
   - nothing reflows when the sentence changes, when an answer appears or when the strip appears.
2. **Drive every weather:**
   - curtains: cold launch;
   - fair: a queued import;
   - night: Consolidate;
   - dawn: the 6 s after a cycle;
   - clear: an empty queue;
   - overcast: fixture `hours_since_last_cycle > 48`;
   - storm: a failing engine.

   Check the sentence and the legend at each step.
3. **Pointer:**
   - sweep over the room: the pupils follow with no boundary flicker;
   - perk once on entry;
   - poke through every rung, then Esc; wait 12 s outside;
   - the plant, mug and cushion do nothing, not even the cursor.
4. **Spines:** the popover counts match Details › What's waiting; "Open in Sources" lands on that
   source; row hover lifts the spine.
5. **Lamp:**
   - the scheduled engine line is visible *before* flipping;
   - toggling flips the lamp and the whisper line together;
   - with the backend stopped, the toggle snaps back with a caption.
6. **A cycle:**
   - run one: sentence L3/L5 + T2, strip, Cancel caption, window night → dawn, cheer, "See what
     changed ›" opens and scrolls to the right row;
   - cancel mid-cycle: no cheer, no digesting, the T4 line, the strip frozen;
   - force a failure: L6/T3 in danger, the storm window, Last cycle at full contrast while the page
     is desaturated.
7. **Drops** (after Z9):
   - a ChatGPT export: expectant, eager, gulp, the router sheet, `.reading`, the pile restacks;
   - a `.png`, a file from `~/.claude/projects/` and a file from `~/.cicada/`: refused in the
     worm's voice, with **nothing sent** (check the backend log).
8. **Accessibility settings:**
   - Reduce Motion: no gaze, beats or fades; the static armed pose on drag;
   - Increase Contrast: the outline and the band;
   - VoiceOver: the §11 order, the rungs announced, "What are you doing?" reads all;
   - Full Keyboard Access: tabs through every hotspot.
9. **CPU:** record idle and sweep figures against v3 in the PR (§10).
10. **Screenshots for the owner:** light and dark, fair and night windows, with and without the band
    (Z10).

---

## 16. Owner questions (only three) and what is not verified

1. **The sky band (Z10).** Ship the state-following wash above the page, or keep the page plain and
   let only the window carry weather? Recommendation: decide from the Z11 screenshots, and keep it
   only if a light-mode night band reads as tint rather than dirt.
2. **Details by default.** Closed (recommended, and remembered per viewer), or open on the first
   visit so the history is discovered?
3. **Answer rung 4 points off the page** to the Inbox. Recommendation: yes. It is the one cross-page
   question a status surface should answer.

**Not verified:**
- Instrument Serif metrics at 30/22 pt inside the column, and the 80-character tail budget on two
  lines.
- How system popovers look on macOS 26 glass over pixel art.
- Hit comfort on 8 pt spines, mitigated by the gap-inclusive rectangle.
- The real cost of per-tick `frames(for:)` (a benchmark comes first).
- VoiceOver's reading of `AccessibilityNotification.Announcement` on macOS 14 (the API is verified in
  the SDK; the behaviour is not).
- Track I's final `IntakeRouter` signature (Z9 names the three outcomes it needs, not the call).
- `backgroundExtensionEffect` inside a `ScrollView` (Z10 only).
- The Meadow pane grids were composed and occlusion-checked by the panel's script, not yet rendered
  in the app.
