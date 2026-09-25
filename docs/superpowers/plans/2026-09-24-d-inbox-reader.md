# Direction D, part 2 — the Inbox in progressive columns and the Reader as a column (Track DS-2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Inbox becomes the reference screen of Direction D. With nothing selected it is the question list alone at
full width. A click narrows the list to a triage column and opens the question beside it as C's focus card. "Show in
conversation" opens the Reader as a third column. One tap answers, and an inline "Answered — Undo" row keeps the answer
for 5 s as a **send delay**: nothing reaches the server until the window closes, so an undone answer never makes a
commit, a claim or a G113 verdict. The Reader stops being an `.inspector` and becomes a column everywhere. It gets C's
styling: mark, title and meta; Resume; the "1 of N cited here" navigator; cited spans washed and underlined; and the
"Noted from this conversation" rows. It is never pushed off the window again, which is the clipped-text bug. Every
kind and every answer path that ships today still works.

**Architecture:** Every decision the page makes is a pure function with a table test, and the views render them:
- column widths (`ColumnLayout.plan`);
- which question is open, and what happens to it on a swap, an answer, an Undo or an Esc (`InboxColumns`);
- which card variant a kind gets (`FocusCardVariant`);
- how a source is named (`InboxSourceLine`);
- what the Undo row says (`UndoLabel`);
- how the Reader's washes become cited spans (`ReaderText.segments`).

The send delay is state in the `Store`, beside `hiddenInboxIds`, so the rail badge, Home and the palette agree with the
Inbox the moment the person taps. The track makes no backend change: no new endpoint, field or ETag, and no new Store
domain.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, macOS 14 floor, built on the macOS 26 SDK). `ImageRenderer` is used
for the layout-fit tests.

**Binding sources:**

- `docs/design/DESIGN_RULES.md`, which binds for every DR id. This track applies §5.3 (progressive columns), §5.4 (the
  Reader), §6 (DR-40…DR-53, in particular DR-42 and DR-43), §7 (DR-54…DR-59), §8 (DR-60…DR-70) and the §9 rulings.
- The owner-approved mocks `D-Inbox.dc.html`, `D-Question.dc.html` and `D-Reader.dc.html` (session scratchpad, not
  committed). They are one component in three states. Row anatomy, the focus card, the Reader aside and the Undo row are
  translated from their markup and `renderPage()`, never embedded.
- `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`, decisions 18 and 19. The brief overrides
  it where it says so.
- The owner's words (2026-09-23, DESIGN_RULES §9): "if no inbox item is selected, then only the questions should
  appear, and when clicking on one, it opens to the right … I also like from C the design itself, with the highlights,
  the resume button and stuff."
- CLAUDE.md rails:
  - Inbox §2/3: G60, G98, G113, G115, G129, and G141 PJ-6 follow-ups;
  - the Provenance viewer (G118 slice 2): washed when quoted, bold when derived, stale said in words;
  - ETag ship-together (untouched);
  - no prices;
  - portability and privacy.
- Backlog rows G115, G113, G118, G61 (phase 2 S2 `check`) and G141 (PJ-6).

---

## What the code actually does today (verified against `feat/d-inbox-reader` @ `1eb3cf5`)

**The page.** `ContentView.swift:442-443` mounts `InboxListView()`.
- `Views/Inbox/InboxListView.swift:116-154`: the header is a `PageHeader("Inbox", subtitle:)`, then a row of
  `KindChip`s, then a `CicadaSearchField("Search questions…")`.
- `:249-287`: a `KindChip` is a coloured pill with a kind dot, a `color.opacity(0.18)` fill and a coloured stroke (DR-7,
  DR-44 and DR-45 violations).
- `:52-82`: the body is one `LazyVStack` of `InboxCardView`s, each expanding in place. There are no columns and no
  detail pane.
- `:105-112`: `land(_:)` consumes `router.pendingInboxItem` (the palette at `ContentView.swift:348-350`, Home at
  `Views/Home/HomeSections.swift:187-189`) by expanding that card.
- `:18-25`: the sort is priority descending, then `createdDate` descending.
- `:212-244`: the error state's Retry is `.borderedProminent.tint(CicadaTheme.accent)`. DR-40 says the Inbox has no
  primary action.

**The card.** `Views/Inbox/InboxCardView.swift`.
- `:39-63`: a `glassCard()` with a 3 pt kind-coloured rail and `.scaleEffect(isHovered ? 1.008 : 1)` (DR-48, DR-8).
- `:103-109`: the kind label as a tinted capsule.
- `:67-99`: the cause line.
- `:188-214`: the expanded excerpt in `quoteFont(size: 12)` with the mention **bolded** (`ExcerptText.attributed`),
  then "Show in conversation" in `CicadaTheme.accent`.
- `:238-245`: the guess.
- `:250-275`: `actionRow` switches on the variant.
  - informational G98 "Got it": `:280-301`;
  - `QuestionView` for every question object;
  - legacy decay Keep / Archive / Remind later: `:305-319`;
  - legacy free text Answer / Dismiss / Skip: `:323-341`;
  - merge with Answer / Merge / Keep separate / Skip and the survivor picker: `:355-497`;
  - `.none` → Dismiss.
- `:524-534`: `fire(_:)` sends at once.
- `:539-581`: `InboxActionButton` takes a `color` (DR-40: "loses its colour parameter").

**The question.** `Views/Inbox/QuestionView.swift`.
- `:67-140`: keys through the pure `Models/QuestionSelection.swift`: 1–9, ↑/↓, ⏎, `o`, `l` (a 7-day defer), and
  `Esc` (`escape()` at `QuestionSelection.swift:76-84`: close Other first, then `.collapse`).
- `:144-167`: the hint row with an "Open source" arrow when the hint holds a URL (`firstURL`, `:296-301`).
- `:174-216`: option rows prefix `"1. "` into the label and mark `(Recommended)` in the accent.
- `:281-294`: `submitOther` sends `resolve` + `answer` (+ `optionKey: "neither"` when that option exists).

**The model.** `Models/InboxItem.swift`.
- `:50-63`: the kind glyphs include two filled symbols (`exclamationmark.triangle.fill`, `questionmark.circle.fill`),
  against DR-53's outline rule.
- `:91-100`: `ageCapsule` reads "5 d / 3 wk / 6 mo / 2 y".
- `:179-226`: `InboxItem` does **not** decode `check`. The server's own comment says so (`api/models/schemas.py:1672-1676`),
  and `InboxCheck` is a census that "nothing acts on yet" (`:1620-1629`).
- `:310-320`: `InboxCause.readerTarget(subjectId:)` builds the Reader target.
- `Models/InboxPresentation.swift:96-108`: `causeLine()` prints the raw harness slug ("From “…” · claude-code · 10
  days ago", DR-54).
- `followup` (G141 PJ-6) is decoded (`InboxItem.swift:18-21`). The server serves its question and options at read
  (`api/services/inbox_questions.py:385-445`):
  - the options are `done` / `still` / `stopped` / `didnt` (or `missed` / `dropped`) plus `remind_later`, whose label says 30 days;
  - `allow_other` is true and `allow_defer` is false;
  - `inbox_service.py:824-831` clamps any defer to 30 days.

**The write.** `ViewModels/InboxViewModel.swift:69-91`: `resolve(...)` runs `store.perform(InboxResolve)`.
- `Sync/Mutations.swift:50-81`: `InboxResolve` hides the item in `Store.hiddenInboxIds` (`Store.swift:47-57`) and then
  POSTs at once, so every tap is already a commit.
- `api/services/inbox_service.py:882-887`: even a `skip` emits a neutral G113 `resolution` event.
- `Sync/Mutations.swift:424-454` (`ActivateBank`) and `Store.swift:154-158`: a bank switch clears the hides.
- `ChannelSourceView.swift:120-138` renders the same `InboxCardView` for G129 removals and resolves through the same
  view-model call.
- `Support/DockOpenQueue.swift:29` (`CicadaAppDelegate`) has no `applicationShouldTerminate`.

**The Reader.** `ContentView.swift:197-205` hosts `ReaderInspector()` in a trailing `.inspector`, with
`inspectorColumnWidth(min: 360·s, ideal: 440·s, max: 560·s)`. An `.inspector`'s width is not the page's to give.
Nothing in the tree reconciles the Reader's minimum (504 pt at 1.4×) with a page's rigid minimum: for example, the
Inbox's chip row is a non-wrapping `HStack` of up to nine pills (`InboxListView.swift:130-146`). Beside such a page, the
split can run past the window's right edge.

**This is the working diagnosis of the clipped-text bug; nothing here reproduced it.** Task 4 therefore measures both
possible roots:
- a page that will not give way;
- a rigid child inside the Reader.

It removes the first by construction. The orchestrator's live check at 1200 pt and 1.4× confirms the fix.

`Views/Provenance/ReaderInspector.swift`:
- `:81-134`: the header has an accent text "Resume" button (`:111-118`) and a `displayFont(size: 22)` title (DR-16 says
  20).
- `:127-131`: the capture line is a `Label` with `info.circle`.
- `:292-314`: the navigator is plain chevrons in 11 semibold.
- `:336-410`: "Noted from this conversation" is a caption label over a nested `ScrollView` capped at 200 pt, and its rows
  carry a subject logo.
- `:434-477`: turns are `bodyFont` 13 with a `dandelion` margin bar (DR-13 retires it).
- `:479-513`: washes are `dandelionFill` at 35 % / 15 %.
- `:517-551`: banners are filled blocks (DR-37).

Elsewhere:
- `Views/Provenance/QuoteBlock.swift:56` borrows `ReaderText.focusOpacity` and the dandelion.
- `ProvenanceRouter.swift:102-136`: one stack; `open` pushes; `revision` bumps on every `open`. That is the signal the
  palette (`ContentView.swift:146`) and the Belief Timeline sheet (`EntityDetailCard.swift:195`) step aside on.
- `ContentView.swift:83-90`: a bank switch closes the Reader and empties `ProvenanceCache`.

**DS-1 left these for this track.**
- `Views/Common/EyebrowRow.swift` and `TextTabs.swift` are built and adopted by no page.
- `Views/Common/CitedSpan.swift`: "defined once here; the Reader and the Inbox (DS-2) adopt it". Its `Mark` is
  `plain | current | other`. It has no derived-mention mark and no reveal.
- `IconButton` and `KeyHint` exist. `NeutralButton`, `TextButton`, `Tag` and `ProgressiveColumns` do not.
- `HelpContent` (`Views/Shell/TitlebarHelp.swift:9-15`) has two cases: Sleep, and everything else.

**The demo bank** (`api/services/demo_bank.py:217-313`, `:798-810`) writes decay ×2, conflict ×2, clarification
(legacy free text), merge_suggestion and follow-ups. It writes no removal, divergence, normalization or informational
item.

**Baseline on this base:** `swift build` succeeds, and `swift test` executes 1623 with 0 failures. Re-measure before
Task 1; never trust a remembered count.

---

## Global Constraints

**Where you work.**

- Work ONLY in `<worktree>` = `<repo>/.worktrees/ds2`, on branch `feat/d-inbox-reader` (based on `dev` @ `1eb3cf5`).
  `<repo>` is the repository root. The orchestrator's brief gives its absolute path, and every command below spells
  `<worktree>` out in full. The path is not written here, because an author-machine path in a public repo is a
  portability defect (CLAUDE.md).
- Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path, because zoxide hijacks a relative `cd`. Ignore
  its stderr warning.
- Never write `grep --include=*.ext` (zsh globs it). Use `rg`, or `grep -rn` with a path.

**What you never touch.**

- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
- Fixtures are synthetic: `alpha-project`, `bob-example`, `example.com`, `Tool Example A/B`, and the DESIGN_RULES §1
  demo names.
- **No backend change at all.** If a task finds it needs a field the server lacks, **stop and say so**. Do not invent
  one.

**How you verify.**

- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed.
- `swift test 2>&1 | tail -20` must report **0 failures** (≥ 1623 executed plus the new tests).
  - `SleepViewModelTests` poll tests and the search-latency tests can flake under load. Re-run them alone before
    calling one yours.
  - SourceKit diagnostics that name OTHER worktrees are noise.
- Graph JS: `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` (pass the glob). It is untouched and must
  stay green.
- NEVER run `make dev`, `make install-app` or `swift run`, and never launch or kill the Cicada app or the launchd
  backend. The owner's installed app is live, and the orchestrator installs and live-checks at the end.

**Git.**

- Never `git add -A`. Stage named files only, and use `git mv` for every move this plan names, so review sees a rename.
- Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv` or `*-report.md`.
- No push, no new branches or worktrees, no subagents. Ignore Devin and PR comments.
- End every commit message with the attribution lines the session's system reminder names. Each commit's subject or
  body cites the DR ids it applies.

**Tokens, type and motion.**

- Colours come only from `CicadaTheme`. Every size goes through `CicadaTheme.font(size:weight:)` or a named token, and
  every dimension through `CicadaTheme.scaled(_:)`, so uiScale works (DR-70, G130). `FontLiteralLintTests` fails the
  build on a literal `.system(size:)`.
- Every rounded rectangle goes through `CicadaTheme.shape(_:)` (DR-12). `labelFont` is read only by `SectionLabel`
  (`SectionLabelLintTests`).
- Every duration lives in `CicadaMotion` (`MotionLiteralLintTests`), and every non-motion delay in `CicadaTiming`.
  **A keyboard action never animates (DR-60).** Run it through `Instant.run { }` (Task 1).
- Depth is a ring, never a shadow (`ElevationLintTests`). The accent's six uses are DR-5's and no others.

**Copy.**

- Plain, friendly and sentence case, with no "!", no bare "%" and no prices or token counts (DR-59, the 2026-09-03
  ruling).
- A service is named with its real mark through `OriginMark` / `LogoImage` (DR-52), never a generic glyph.
- Ids, harness slugs and paths appear only in `.help`, an accessibility label or a copy action (DR-54).
- New words live in `Theme/Copy+Inbox.swift` (Task 2) or `Theme/Copy+Provenance.swift`.

**Docstrings** explain WHY, citing the DR id, this plan's ruling (R-DI*) or the G row. Match the density of the file you
touch. Line numbers above are from `1eb3cf5` and drift as tasks land, so read the cited code before editing.

**Test snippets.** "Append to `XTests.swift`" means inside that file's existing test class, before its closing brace.
The package is Swift 5 language mode (`swift-tools-version: 5.10`); a test that builds a `Store`, an `InboxResolve`
or an `ImageRenderer` is `@MainActor`, as the snippets below mark.

---

## Rulings (binding)

These are decisions this plan takes where the brief or the rules left a choice, each with its reason, so no task
re-opens them. The ones marked **§9** depart from DESIGN_RULES and get a dated line in its §9 (Task 6).

**The send delay**

- **R-DI1 — No `cicada.design.focus` flag (DR-73).** R-DS1's reasons hold unchanged. Comparison is the orchestrator's
  installed build against this branch on the demo bank.
- **R-DI2 — §9 — The held answer lives in the `Store`, not the view model.** DR-42 sketches `ResolveGrace` as "a
  `Mutation` with a hold"; here it is a plain value the `Store` holds, and the send is the unchanged `InboxResolve`
  mutation, so no second rollback path exists.
  - `ResolveGrace` is one held answer: its `InboxResolve`, the Undo row's words, the bank it was made in and a token.
  - `Store.heldResolve` and `Store.sendingInboxIds` both leave `Store.visibleInbox`, so the rail badge, Home's "Needs
    you" and the palette drop the item the moment it is tapped, exactly as the Inbox does.
  - When the window closes, the send is the ordinary `store.perform(InboxResolve)`. Its optimistic hide, its rollback
    with a toast and its `.inbox` refresh are reused as they are, not re-implemented.
- **R-DI3 — Where a held answer is sent.** The window is `CicadaTiming.undoWindow` (5 s). The answer is sent at the first
  of these:
  - the window ending;
  - the next answer (the previous one is sent at once, without waiting, so the next question paints this frame);
  - `ActivateBank.optimistic`, **before** `store.bank` moves. That covers every bank-switch path, because each one is
    `BanksViewModel.activate` → `ActivateBank`;
  - the main window's `onDisappear`;
  - quit, through `applicationShouldTerminate` → `.terminateLater`, capped at `CicadaTiming.quitFlushLimit` (3 s) so a
    dead backend never holds the app open.

  **A page switch does not send.** The window keeps counting, and the Undo row is still there if the person comes back
  inside it.

  When another client moves the active bank (`Store.refresh` → `hydrate`), a held answer from the old bank is
  **dropped** with a toast rather than posted into the wrong bank. Ids repeat across banks, so `inbox-001` exists in
  every one.

  When the question left the snapshot inside the window (an agent answered it over MCP, or Sleep resolved it
  organically), there is nothing left to answer: the held answer is dropped silently rather than POSTed into a 404
  whose rollback toast would claim the person's answer was "reverted".
- **R-DI4 — Every answer is held, Skip included.** A `skip` emits a neutral G113 row (`inbox_service.py:882-887`), so an
  undone skip must emit nothing either. A skipped question is still pending: it leaves the list for the window and
  comes back after the send.
  - Undo applies to the latest held answer only: there is one Undo row.
  - ⌘Z is the Undo row's button shortcut. It is switched off while a text field on the page has focus, so the field's
    own ⌘Z still undoes typing.
  - A crash inside the window loses the answer. Nothing was sent, so the question is simply asked again. This is
    disclosed, not fixed.
- **R-DI5 — What the Undo row says (`UndoLabel`).** The row's wording depends on the answer:

  | Answer | Row (short form) |
  |---|---|
  | An option | "Answered · <option label>" ("Answered") |
  | Typed words | "Answered · <the words>" ("Answered") |
  | `defer`, or the follow-up's `remind_later` option | "Not now" |
  | Informational `dismiss` | "Got it" |
  | Any other `dismiss` | "Dismissed" |
  | `skip` | "Skipped" |
  | `reject` | "Kept separate" ("Kept") |
  | `merge` | "Merged" |
  | legacy `keep_active` | "Kept" |
  | legacy `archive` | "Archived" |

  With the Reader open, the row shows the short form beside Undo (DR-42).

**Columns and the Reader**

- **R-DI6 — §9 — One Reader view, two hosts. `.inspector` retires (DR-31).** DR-31 names the view
  `ReaderInspector`; it is renamed `ReaderColumn` because it is no longer an inspector. `ReaderColumn` is the Inbox's third
  progressive column. On every other page it is the shell's trailing column (`ShellReaderHost`), until that page adopts
  `ProgressiveColumns`.
  - The host decides the width first (`ColumnLayout`), gives the page the rest with a fixed frame and `.clipped()`, and
    sums to exactly the content width. The Reader can no longer be pushed past the window's edge.
  - The Reader stays open across a page switch, as it does today, so "Show on graph" still lands the entity beside its
    sentence.
- **R-DI7 — Column widths (§5.3, DR-27, DR-70).** `ColumnLayout.plan` works in *units* (points ÷ uiScale), so ⌘+ narrows
  the columns exactly as it grows the type.
  - **Triage list:** 280 at a 1200 window and 328 at 1440, linear between, clamped.
  - **Reader:** 360 at 1200 and 420 at 1440, linear between, clamped.
  - **Titles list:** 260.
  - **The list hides** when the question would drop under 440.
  - **§9 — the overflow regime.** When 440 + 360 cannot fit even without the list, the question and the Reader split
    the width 440 : 360. This is ≥ 1.3× zoom with the labelled sidebar at a 1200 window. Nothing overflows (DR-31 wins
    over DR-27's floor).
  - **Gutter and card padding:** 40 / 28, dropping to 24 / 24 in STATE 2.
- **R-DI8 — §9 — STATE 0 + Reader.** A Reader opened elsewhere while the Inbox shows no question sits beside the
  full-width list (one-line rows). Elsewhere means an evidence chip, the palette's "Conversations", or another page
  before a switch. The page never closes a Reader it did not open, and never waits for a question to show one.
  - Esc closes it (DR-28).
  - Clicking a row applies DR-29. The Reader stays only if the question cites that conversation.
- **R-DI9 — A swap onto the same conversation re-lands in place.** `ProvenanceRouter.refocus(_:)` replaces the top
  target when the episode matches, so the navigator jumps to the new span (DR-29). A Back step is for moving between
  documents, and answering five questions beside one conversation must not build five of them.
- **R-DI10 — Keys and focus (DR-60, DR-68).**
  - A pointer open gives the question keyboard focus, so 1–9 answer at once.
  - ↑/↓ move the selection only while the list has focus, and ⏎ there moves focus into the question.
  - Tab walks list → question → Reader (the default key-view loop, in layout order).
  - Esc: the card first closes its Other…/answer field; `InboxColumns.escape` then closes the Reader, then the question.
  - Keyboard paths run in `Instant.run` (a transaction with `disablesAnimations`), so a pointer path's
    `.animation(_:value:)` cannot catch them.
- **R-DI11 — §9 — The quote tells quoted from found.**
  - An **asserted** span is `CitedSpan.current`: the wash plus the 2 pt accent underline (DR-18).
  - A mention **found by name** (`spanKind: derived`, every G115 cause without a G118 span) is `CitedSpan.mention`:
    semibold, no wash, and "Found by searching the conversation" under the quote. This follows DR-57 ("bold when
    derived") and the CLAUDE.md provenance-viewer rail, which outrank §5.3 item 3's unconditional wash.
  - The Reader follows the same rule. The dandelion wash and margin bar retire (DR-13), and `QuoteBlock`'s wash moves to
    the accent `wash` with them.
- **R-DI12 — A source in a person's words (DR-54, DR-55, DR-58).**
  - **Card:** mark (14) + "Claude Code · <conversation title> · Aug 25". With no title it reads "a Claude Code
    conversation · Aug 25". With no source it reads the literal `[ no source recorded ]`.
  - **Row:** mark (12) + "Claude Code · Aug 25". The row's age is compact ("4w"), with the absolute day in `.help`. With
    no source the age is "—", with its reason in `.help`.
  - **Episode id:** only ever in `.help` ("Episode ep_…").
  - **Compact ages** are shared with option tags ("5d · 3w · 6mo · 2y"). They use `phrase(days:)`'s boundaries and
    half-even rounding, so "3w" and "3 weeks ago" never disagree.
- **R-DI13 — No check line.** The brief says "the check line if present", and none is present.
  - `check` on the wire is G61 S2's read-only census: `state`, `reason`, `locus`, `targets` and `rungs`, where "nothing
    acts on it yet".
  - The mock's "Check now" and "Checked by Cicada · …" line render a check **result** that G61 S3+ will serve.
  - The app does not decode `check`. The hint row keeps "Open source ↗". S3 adds the line beside it, with no redesign.

**The page**

- **R-DI14 — §9 — The Inbox's in-page search field retires (DR-46).** The rule says "never on the Inbox", and the
  approved mock has none.
  - ⌘K's Inbox group is its twin. `QuickIndex.swift:183-186` indexes every question with the same `InboxSearch.fields`,
    and a hit lands in STATE 1.
  - This reverses G136 S5's Inbox field. `InboxSearch` stays, because the palette reads it.
- **R-DI15 — Every variant renders inside the focus card (DR-43).** `FocusCardVariant.of(item)`:
  - `informational`;
  - `options`, for any item with options: conflict, decay, removal, divergence, normalization, follow-up, a G60
    clarification;
  - `merge`, for a merge suggestion with no options;
  - `legacyDecay`, for a cached pre-G115 decay payload;
  - `freeText`, for a clarification with no options;
  - `dismissOnly`, for nothing to pick.

  Two details:
  - The free-text field is open but **not** auto-focused, so L and Esc work at once, and O focuses it.
  - Dismiss and Skip stay exactly where they exist today (the legacy free text; merge's Skip).
- **R-DI16 — The Sources page's Deletions render the same card and the same Undo row.** `ChannelSourceView`'s own
  invariant is "one write path, two views render the identical card". The card is embedded without Close, and Undo
  there does not reopen anything in the Inbox.
- **R-DI17 — The Inbox's `?` answers for the Inbox (DR-25).** `HelpContent.inbox` holds the old subtitle ("Questions
  waiting on you.") and the key map, each key with a `KeyHint` (DR-49).
- **R-DI18 — Kind glyphs are outline symbols (DR-53), and their hues do not move (DR-8).** Conflict becomes
  `exclamationmark.triangle` and clarification becomes `questionmark.circle`. A glyph carries its kind's name as `.help`
  and accessibility label (DR-3's merge rule, applied to every kind).
- **R-DI19 — Selection lives in `InboxViewModel`.** The open question and the tab survive a page switch. A bank switch
  resets them, because ids repeat across banks.
- **R-DI20 — The Reader's words are quoted words.** A turn's text is `quoteFont` (SF 15, `quoteLineSpacing`) — DR-18:
  every word a person or an agent said passes through that one door, and it is the mock's 15/25. The Reader's other
  text (banners, gone, failed, empty) is `detailBodyFont` (14, the DS-1 §9 ruling). Its title is `displayFont(size: 20)`
  (DR-16).
- **R-DI21 — §9 — Demo coverage.** DR-43 has the app reach every variant through the demo bank, but the demo writes no
  removal, divergence, normalization or informational item. Adding them is a `demo_bank.py` change, which is outside
  this track. Until a backend batch adds them, `InboxFocusCardFitTests` renders every variant from the server's own
  shapes, and the orchestrator live-checks the five kinds the demo has.
- **R-DI22 — The excerpt is cleaned per segment (DR-56).** `ExcerptText.clean` runs on each of before / span / after
  **after** the split, so the mention offsets (scalar offsets into the raw excerpt, G97) never move. It strips heading
  hashes, bullets and quote markers at a line's start, and renders `[[a|b]]` as "b" and `[[slug-name]]` as "Slug Name".
  It collapses whitespace but never trims a segment's edges, which would glue "Discussed" to "swapping".
  - Only the first segment's first line starts a real line. The span and the text after it begin mid-line, so their
    first line keeps a leading "- " or "> " (`atLineStart: false`); "5 - 3 more" must not lose its minus.
  - A mention inside a wikilink splits the link across segments (an Obsidian vault a folder watches is full of them),
    so a stray `[[`, `[[target|` or `]]` left at a segment's edge is dropped.
- **R-DI23 — Lints: grow the scopes, add one scoped lint.**
  - `CountLiteralLintTests` gains `/Views/Inbox/` and `/Views/Provenance/ReaderColumn.swift`. From Task 3 on, no line
    in those files spells `Text("…\(…)…")`: compose the words in `Copy.Inbox` / `Copy.Provenance`, or mark a line that
    renders no number `// count-lint:ok — <reason>`.
  - `SelectionTintLintTests` gains `Views/Inbox/InboxQuestionList.swift`.
  - The new `InboxProvenanceIdLintTests` is DR-54 scoped to `Views/Inbox/`.
  - R-DS28's app-wide lints stay deferred to the page tracks.
- **R-DI24 — The controls this track needs are built here and adopted here.**
  - Built: `NeutralButton`, `TextButton`, `Tag` (DR-40, DR-44) and `ProgressiveColumns` (§5.3).
  - Retired: `InboxActionButton`, `KindChip`, `InboxCardView` and `QuestionView`'s view. Its two value types,
    `QuestionResolution` and `MergeReject`, move to `QuestionResolution.swift`.
- **R-DI25 — The Undo row never leaves the screen with the list.** When the list hides (DR-27, STATE 2 at a narrow
  window), the Undo row is drawn at the head of the question column in its short form, so Undo and its ⌘Z stay
  reachable for the whole window (DR-42). Exactly one Undo row is on screen at a time, so ⌘Z has one owner.
- **R-DI26 — A wide row drops its slots before it overflows (DR-31).** STATE 0's one-line row has fixed slots (entity
  180, source 220, age 30). Beside a Reader (R-DI8) or at 1.4× the list can be narrower than they need, and a fixed
  frame in an `HStack` does not shrink: it would draw under the Reader. `InboxRowSlots.of(listUnits:)` drops the
  entity slot under 680 units and the source slot under 480; the question always keeps the rest.

---

## File map

`app/…` = `app/CicadaApp/Sources/CicadaApp`. Tests live in `app/CicadaApp/Tests/CicadaAppTests/`.

| File | Task | Responsibility |
|---|---|---|
| `app/…/Views/Common/ProgressiveColumns.swift` (new) | 1 | `ColumnPlan`, `ColumnLayout`, `ProgressiveColumns` |
| `app/…/Views/Common/NeutralButton.swift`, `TextButton.swift`, `Tag.swift` (new) | 1 | DR-40, DR-44 |
| `app/…/Theme/CicadaMotion.swift` | 1 | `CicadaCurve`, the column motion names, `fade`, `Instant` |
| `app/…/Sync/ResolveGrace.swift` (new) | 2 | `ResolveGrace`, `Store.hold/undoHeld/flushHeld/expire` |
| `app/…/Sync/Store.swift`, `Sync/Mutations.swift` | 2 | held/sending state, `visibleInbox`, the hydrate guard; `ActivateBank` sends first |
| `app/…/Support/QuitFlush.swift` (new), `Support/DockOpenQueue.swift`, `CicadaApp.swift` | 2 | quit sends a held answer |
| `app/…/Theme/CicadaTiming.swift`, `Theme/Copy+Inbox.swift` (new) | 2 | `undoWindow`, `quitFlushLimit`; the Inbox's words |
| `app/…/ViewModels/InboxViewModel.swift` | 2, 5 | `answer`, `undo` (2); columns, rows, eyebrow, tabs (5) |
| `app/…/Models/InboxPresentation.swift` | 2, 3 | `UndoLabel` (2); `InboxAge.compact`, `InboxRowAge`, `InboxSourceLine`, `ExcerptText.clean`, `QuoteSegments`, `InboxGuess`, `HintLink`, `FreeTextSubmit`, `FocusCardVariant` (3) |
| `app/…/Models/InboxItem.swift`, `Models/QuestionSelection.swift` | 3 | compact ages, outline glyphs; `highlight(_:)` |
| `app/…/Views/Common/CitedSpan.swift` | 3 | `.mention`, `reveal` |
| `app/…/Views/Inbox/InboxFocusCard.swift`, `OptionRow.swift`, `FocusCardVariants.swift` (new) | 3 | the focus card |
| `app/…/Views/Provenance/ReaderColumn.swift` (moved from `ReaderInspector.swift`) | 4 | `ReaderColumn`, its header, turns, noted list, banners, `ReaderText.segments`, `ShellReaderHost` |
| `app/…/Views/Provenance/ProvenanceRouter.swift`, `QuoteBlock.swift` | 4 | `refocus(_:)`; the accent wash |
| `app/…/ContentView.swift` | 2, 4, 5 | flush on close (2); the shell host (4); `InboxPage`, the Inbox exclusion, the column reset (5) |
| `app/…/Views/Inbox/InboxPage.swift` (moved from `InboxListView.swift`) | 5 | the page |
| `app/…/Views/Inbox/InboxColumns.swift`, `InboxQuestionList.swift` (new) | 5 | the reducer, rows, row slots, eyebrow, tabs; the list and the Undo row |
| `app/…/Views/Inbox/QuestionResolution.swift` (moved from `QuestionView.swift`) | 5 | `QuestionResolution`, `MergeReject` |
| `app/…/Views/Inbox/InboxCardView.swift` | 5 | **deleted** |
| `app/…/Views/Shell/TitlebarHelp.swift`, `Views/Sources/ChannelSourceView.swift`, `Views/Common/CicadaSearchField.swift` | 5 | the Inbox's `?`; Deletions; the doc comment |
| Tests (new) | 1–5 | `ColumnLayoutTests`, `ControlVocabularyTests`, `ResolveGraceTests`, `InboxFocusCardFitTests`, `ReaderColumnLayoutTests`, `InboxColumnsTests`, `InboxProvenanceIdLintTests` |
| Tests (edited) | 2–5 | `InboxQuestionTests`, `InboxPresentationTests`, `CitedSpanTests`, `ReaderTurnsTests`, `ProvenanceRouterTests`, `ThemeContrastTests`, `CicadaMotionTests`, `TitlebarHelpTests`, `CountLiteralLintTests`, `SelectionTintLintTests` |
| Docs | 6 | `CLAUDE.md`, `docs/design/DESIGN_RULES.md` §9, `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (G115, G118) |

---

### Task 1: The column grammar and the controls it needs (§5.3 — DR-26, DR-27, DR-36, DR-40, DR-44, DR-61, DR-62, DR-70)

Pure widths, the reusable container, the curves, and three controls. Nothing adopts them yet. The branch stays
shippable.

**Files:**
- Create: `app/…/Views/Common/ProgressiveColumns.swift`, `app/…/Views/Common/NeutralButton.swift`,
  `app/…/Views/Common/TextButton.swift`, `app/…/Views/Common/Tag.swift`
- Modify: `app/…/Theme/CicadaMotion.swift` (append after `spanReveal`, `:114-116`)
- Test: `ColumnLayoutTests.swift` (new), `ControlVocabularyTests.swift` (new), `CicadaMotionTests.swift` (one test added)

**Interfaces:**
- Produces:
  - `ColumnPlan` (`list`, `detail`, `trailing`, `listStyle: .wide | .triage | .titles | .hidden`, `gutter`,
    `cardPadding`, `listHidden`);
  - `ColumnLayout.plan(contentWidth:navWidth:scale:hasList:hasDetail:hasTrailing:)`, `.readerWidth(window:)`,
    `.triageListWidth(window:)`, and the constants;
  - `ProgressiveColumns(hasDetail:hasTrailing:navWidth:header:list:detail:trailing:)`;
  - `CicadaCurve.out / .inOut / .drawer / .ease`;
  - `CicadaMotion.columns / readerIn / readerOut / cardFade / rowLeave / undoFade / fade / readerTransition`;
  - `Instant.run(_:)`;
  - `NeutralButton`, `TextButton`, `Tag`, `RowMetrics`.
- Consumes: `CicadaTheme` tokens, `ShellMetrics.railWidth` / `sidebarWidth`, `KeyHint`, `ringed(_:in:)`.

- [ ] **Step 1: Failing tests.** Create `ColumnLayoutTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// §5.3 / DR-27 — the progressive columns' widths, pure. The table is DESIGN_RULES §5.3's, row for row;
/// the sweep holds DR-31's "never pushes content off-window" for every arrangement at every zoom.
final class ColumnLayoutTests: XCTestCase {
    private func nav(labelled: Bool, scale: CGFloat) -> CGFloat {
        ((labelled ? ShellMetrics.sidebarWidth : ShellMetrics.railWidth) * scale * 10).rounded() / 10
    }

    private func plan(_ window: CGFloat, labelled: Bool = false, scale: CGFloat = 1, list: Bool = true,
                      detail: Bool, reader: Bool) -> ColumnPlan {
        let n = nav(labelled: labelled, scale: scale)
        return ColumnLayout.plan(contentWidth: window - n, navWidth: n, scale: scale,
                                 hasList: list, hasDetail: detail, hasTrailing: reader)
    }

    func testTheDesignRulesTableAtOneX() {
        // window, labelled, S1 list, S1 question, S2 list, S2 question, S2 reader
        let table: [(CGFloat, Bool, CGFloat, CGFloat, CGFloat, CGFloat, CGFloat)] = [
            (1440, false, 328, 1056, 260, 704, 420),
            (1440, true, 328, 904, 260, 552, 420),
            (1200, false, 280, 864, 260, 524, 360),
            (1200, true, 280, 712, 0, 632, 360),
        ]
        for (w, labelled, l1, q1, l2, q2, r2) in table {
            let s1 = plan(w, labelled: labelled, detail: true, reader: false)
            XCTAssertEqual([s1.list, s1.detail, s1.trailing], [l1, q1, 0], "S1 \(w) labelled \(labelled)")
            XCTAssertEqual(s1.listStyle, .triage)
            XCTAssertEqual([s1.gutter, s1.cardPadding], [40, 28])
            let s2 = plan(w, labelled: labelled, detail: true, reader: true)
            XCTAssertEqual([s2.list, s2.detail, s2.trailing], [l2, q2, r2], "S2 \(w) labelled \(labelled)")
            XCTAssertEqual(s2.listStyle, l2 == 0 ? .hidden : .titles)
            XCTAssertEqual([s2.gutter, s2.cardPadding], [24, 24], "§5.3: the gutter and the card's padding drop to 24")
        }
    }

    func testStateZeroIsTheListAloneAtFullWidth() {
        let s0 = plan(1440, detail: false, reader: false)
        XCTAssertEqual([s0.list, s0.detail, s0.trailing], [1384, 0, 0])
        XCTAssertEqual(s0.listStyle, .wide)
    }

    /// R-DI8 — a Reader opened elsewhere sits beside the full list; the page never closes it.
    func testAReaderOpenedElsewhereSitsBesideTheWholeList() {
        let p = plan(1440, detail: false, reader: true)
        XCTAssertEqual([p.list, p.trailing], [964, 420])
        XCTAssertEqual(p.listStyle, .wide)
    }

    /// DR-70 / R-DI7 — widths are units: at 1.4× a 1440 window lays out like a ~1029 one.
    func testZoomNarrowsTheColumnsInUnits() {
        let s1 = plan(1440, scale: 1.4, detail: true, reader: false)
        XCTAssertEqual(s1.list, 392, "280 units")
        XCTAssertEqual(s1.detail, 1440 - 78.4 - 392, accuracy: 0.01)
        let s2 = plan(1440, scale: 1.4, detail: true, reader: true)
        XCTAssertEqual(s2.listStyle, .hidden, "DR-27 — the list goes before the question drops under 440")
        XCTAssertEqual(s2.trailing, 504, "360 units")
        XCTAssertEqual(s2.detail, 1440 - 78.4 - 504, accuracy: 0.01)
    }

    /// R-DI7 (§9) — when neither floor fits, the question and the Reader share the width 440 : 360.
    func testWhenNeitherFloorFitsTheTwoShareTheWidthAndNothingOverflows() {
        let s2 = plan(1200, labelled: true, scale: 1.4, detail: true, reader: true)
        let content: CGFloat = 1200 - 291.2
        XCTAssertEqual(s2.listStyle, .hidden)
        XCTAssertEqual(s2.detail + s2.trailing, content, accuracy: 0.01)
        XCTAssertEqual(s2.trailing / content, 360.0 / 800.0, accuracy: 0.01)
    }

    /// R-DI6 — the shell's host: the page is the detail, the Reader the trailing column.
    func testTheShellHostGivesThePageTheRest() {
        let p = plan(1200, list: false, detail: true, reader: true)
        XCTAssertEqual([p.list, p.detail, p.trailing], [0, 784, 360])
        let closed = plan(1200, list: false, detail: true, reader: false)
        XCTAssertEqual([closed.detail, closed.trailing], [1144, 0])
    }

    /// DR-31 — every arrangement sums to the content width, at every zoom, with either sidebar.
    func testEveryArrangementSumsToTheContentWidth() {
        let shapes: [(Bool, Bool, Bool)] = [(true, false, false), (true, true, false), (true, true, true),
                                            (true, false, true), (false, true, true), (false, true, false)]
        for scale: CGFloat in [0.8, 1.0, 1.2, 1.4] {
            for labelled in [false, true] {
                for window in stride(from: CGFloat(600), through: 2400, by: 37) {
                    let content = window - nav(labelled: labelled, scale: scale)
                    for (list, detail, reader) in shapes {
                        let p = plan(window, labelled: labelled, scale: scale, list: list, detail: detail, reader: reader)
                        XCTAssertEqual(p.list + p.detail + p.trailing, content, accuracy: 0.001,
                                       "\(window) \(scale) \(labelled) \(list)/\(detail)/\(reader)")
                        XCTAssertTrue([p.list, p.detail, p.trailing].allSatisfy { $0 >= 0 })
                    }
                }
            }
        }
    }
}
```

Create `ControlVocabularyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// DR-40 / DR-44 / DR-34 — the controls' fixed numbers, read from one place.
final class ControlVocabularyTests: XCTestCase {
    func testTheNeutralButtonIsTwentyEightOrThirtyTwoAndDisabledIsFortyFivePercent() {
        XCTAssertEqual(NeutralButton.Size.compact.height, 28)
        XCTAssertEqual(NeutralButton.Size.regular.height, 32)
        XCTAssertEqual(NeutralButton.disabledOpacity, 0.45, "DR-41")
        XCTAssertEqual(TextButton.height, 32)
    }

    func testTheOnePillIsEighteenTall() {
        XCTAssertEqual(Tag.height, 18)
        XCTAssertEqual(Tag.dotSize, 6)
    }

    /// DR-34 / §5.5 — each row role has one height.
    func testEachRowRoleHasOneHeight() {
        XCTAssertEqual(RowMetrics.oneLine, 36)
        XCTAssertEqual(RowMetrics.twoLine, 56)
        XCTAssertEqual(RowMetrics.titleOnly, 36)
        XCTAssertEqual(RowMetrics.option, 48)
        XCTAssertEqual(RowMetrics.twoLineGap, 2)
        XCTAssertEqual(RowMetrics.optionGap, 4)
    }
}
```

Append to `CicadaMotionTests.swift`:

```swift
    /// DR-61 / DR-66 — the columns move on the drawer curve under 300 ms; under Reduce Motion the
    /// widths jump and the Reader, the card and the Undo row still fade (100 ms, linear).
    func testTheColumnMotionStaysUnderTheUICeilingAndKeepsAFadeUnderReduceMotion() {
        for d in [CicadaMotion.columnDuration, CicadaMotion.readerInDuration, CicadaMotion.readerOutDuration,
                  CicadaMotion.cardFadeDuration, CicadaMotion.rowLeaveDuration, CicadaMotion.undoFadeDuration] {
            XCTAssertLessThanOrEqual(d, 0.3)
        }
        XCTAssertLessThan(CicadaMotion.readerOutDuration, CicadaMotion.readerInDuration, "DR-65: exits are faster")
        XCTAssertNil(CicadaMotion.columns(reduceMotion: true))
        XCTAssertEqual(CicadaMotion.readerIn(reduceMotion: true), CicadaMotion.fade)
        XCTAssertEqual(CicadaMotion.undoFade(reduceMotion: true), CicadaMotion.fade)
    }
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'ColumnLayoutTests|ControlVocabularyTests|CicadaMotionTests' 2>&1 | tail -20`.
It fails to compile, because the types do not exist. That is the red.

- [ ] **Step 2: Implement `ProgressiveColumns.swift`:**

```swift
import SwiftUI

/// One arrangement of the progressive columns (DESIGN_RULES §5.3), in points that sum to exactly
/// the content width — so nothing is ever pushed off-window (DR-31). The `.inspector` the Reader
/// used to live in could not promise that, and clipped the Reader's text (R-DI6).
struct ColumnPlan: Equatable {
    enum ListStyle: Equatable {
        /// STATE 0 — one-line rows at full width, or beside a Reader opened elsewhere (R-DI8).
        case wide
        /// STATE 1 — the triage column: two-line rows.
        case triage
        /// STATE 2 — titles only, so the question keeps its 440.
        case titles
        /// DR-27 — the question and the Reader could not both keep their floor with it on screen.
        case hidden
    }

    var list: CGFloat
    var detail: CGFloat
    var trailing: CGFloat
    var listStyle: ListStyle
    /// 40 with at most two columns, 24 once the Reader sits beside the question (§5.3 STATE 2).
    var gutter: CGFloat
    /// The focus card's padding: `spacingCard` (28), 24 in STATE 2.
    var cardPadding: CGFloat

    var listHidden: Bool { listStyle == .hidden }
}

/// §5.3's widths, pure (DR-27, DR-36, DR-70; R-DI7). Every number is at uiScale 1 — "units" — and
/// `plan` works in units and hands back points, so ⌘+ narrows the columns exactly as it grows the
/// type (G130): at 1.4× a 1440 window lays out like a ~1030 one. The table's widths are keyed on
/// the WINDOW (the rail and the labelled sidebar share them), the floors on the space left.
enum ColumnLayout {
    static let minQuestion: CGFloat = 440       // DR-27
    static let minReader: CGFloat = 360         // DR-27
    static let titlesList: CGFloat = 260        // §5.3 STATE 2
    static let questionMaxWidth: CGFloat = 720  // DR-36 — the focus card
    static let textMaxWidth: CGFloat = 760      // DR-36 — a row's text
    static let gutterWide: CGFloat = 40
    static let gutterNarrow: CGFloat = 24
    static let cardPaddingWide: CGFloat = 28    // `spacingCard`
    static let cardPaddingNarrow: CGFloat = 24

    /// 280 at a 1200 window, 328 at 1440, straight between, clamped (§5.3's table).
    static func triageListWidth(window: CGFloat) -> CGFloat {
        min(max(280 + (window - 1200) * 0.2, 280), 328)
    }

    /// 360 at a 1200 window, 420 at 1440, straight between, clamped.
    static func readerWidth(window: CGFloat) -> CGFloat {
        min(max(360 + (window - 1200) * 0.25, 360), 420)
    }

    /// R-DI7 (§9) — neither floor fits: the question and the Reader share the width 440 : 360.
    private static func overflowReader(_ available: CGFloat) -> CGFloat {
        available * minReader / (minQuestion + minReader)
    }

    static func plan(contentWidth: CGFloat, navWidth: CGFloat, scale: CGFloat,
                     hasList: Bool = true, hasDetail: Bool, hasTrailing: Bool) -> ColumnPlan {
        let s = max(scale, 0.1)
        let content = max(contentWidth, 0)
        let window = (content + max(navWidth, 0)) / s
        let available = content / s
        // Nearest, not down: 280 × 1.4 is 391.99999… in binary floating point. The flexible column
        // takes the remainder, so rounding a fixed one never breaks the exact sum.
        func points(_ units: CGFloat) -> CGFloat { (units * s).rounded() }
        func scaled(_ units: CGFloat) -> CGFloat { (units * s * 10).rounded() / 10 }

        var listUnits: CGFloat = 0
        var readerUnits: CGFloat = hasTrailing ? min(readerWidth(window: window), available) : 0
        var style = ColumnPlan.ListStyle.hidden
        switch (hasList, hasDetail) {
        case (true, false):
            if available - readerUnits >= titlesList || !hasTrailing {
                style = .wide
            } else {
                readerUnits = available
            }
        case (true, true) where !hasTrailing:
            let triage = triageListWidth(window: window)
            if available - triage >= minQuestion {
                listUnits = triage
                style = .triage
            }
        case (true, true):
            if available - titlesList - readerUnits >= minQuestion {
                listUnits = titlesList
                style = .titles
            } else if available - readerUnits < minQuestion {
                readerUnits = overflowReader(available)
            }
        case (false, true):
            if hasTrailing, available - readerUnits < minQuestion { readerUnits = overflowReader(available) }
        case (false, false):
            break
        }

        let reader = hasTrailing ? points(readerUnits) : 0
        let list: CGFloat
        let detail: CGFloat
        if hasDetail {
            list = style == .hidden ? 0 : points(listUnits)
            detail = max(content - list - reader, 0)
        } else {
            list = style == .hidden ? 0 : max(content - reader, 0)
            detail = 0
        }
        let narrow = hasDetail && hasTrailing
        return ColumnPlan(
            list: list, detail: detail, trailing: hasTrailing ? max(content - list - detail, 0) : 0,
            listStyle: hasList ? style : .hidden,
            gutter: scaled(narrow ? gutterNarrow : gutterWide),
            cardPadding: scaled(narrow ? cardPaddingNarrow : cardPaddingWide))
    }
}

/// §5.3 — the list alone; the list and its detail; the list, the detail and the source. One
/// container: the Inbox adopts it (DS-2), and Clusters, the Feed, Sources and Projects next (§10).
///
/// The header (the eyebrow row, DR-25) spans the list and the detail; the trailing column runs the
/// full height beside both, as the approved mock draws the Reader. The widths come from
/// `ColumnLayout.plan` alone and the whole arrangement is clipped to the container, so a child with
/// a rigid minimum can never widen the window (R-DI6). Animation belongs to the caller: a pointer
/// path wraps its change in `withAnimation`, a keyboard path in `Instant.run` (DR-60).
struct ProgressiveColumns<Header: View, List: View, Detail: View, Trailing: View>: View {
    let hasDetail: Bool
    let hasTrailing: Bool
    /// The shell's navigation width, scaled (`ShellMetrics.navWidth(labelled:)`) — the table's widths
    /// are keyed on the window, which is this container plus the rail or the sidebar.
    let navWidth: CGFloat
    @ViewBuilder var header: (ColumnPlan) -> Header
    @ViewBuilder var list: (ColumnPlan) -> List
    @ViewBuilder var detail: (ColumnPlan) -> Detail
    @ViewBuilder var trailing: (ColumnPlan) -> Trailing

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let plan = ColumnLayout.plan(contentWidth: geo.size.width, navWidth: navWidth,
                                         scale: CGFloat(CicadaTheme.uiScale),
                                         hasDetail: hasDetail, hasTrailing: hasTrailing)
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    header(plan)
                    HStack(spacing: 0) {
                        if !plan.listHidden {
                            list(plan).frame(width: plan.list).frame(maxHeight: .infinity)
                        }
                        if hasDetail {
                            detail(plan)
                                .frame(width: plan.detail)
                                .frame(maxHeight: .infinity)
                                .transition(.opacity)
                        }
                    }
                }
                .frame(width: plan.list + plan.detail)
                if hasTrailing {
                    trailing(plan)
                        .frame(width: plan.trailing)
                        .frame(maxHeight: .infinity)
                        .transition(CicadaMotion.readerTransition(reduceMotion: reduceMotion))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
            .clipped()
        }
        // DR-61 — the trailing column opens on the drawer curve and closes faster, whoever opened it
        // (a chip, "Show in conversation", the palette). Esc closes it inside `Instant.run`, whose
        // transaction disables this animation (DR-60).
        .animation(hasTrailing ? CicadaMotion.readerIn(reduceMotion: reduceMotion)
                               : CicadaMotion.readerOut(reduceMotion: reduceMotion), value: hasTrailing)
    }
}

/// DR-34 / §5.5 — each row role has one height; no row sets its own vertical padding.
enum RowMetrics {
    static let oneLine: CGFloat = 36
    static let twoLine: CGFloat = 56
    static let titleOnly: CGFloat = 36
    static let option: CGFloat = 48
    static let twoLineGap: CGFloat = 2
    static let optionGap: CGFloat = 4
}
```

- [ ] **Step 3: Implement the three controls.** `NeutralButton.swift`:

```swift
import SwiftUI

/// DR-40 — the neutral button: `bgButton` plus a resting ring, `textPrimary` in 13 medium (12 compact),
/// 28 or 32 pt, `cornerRadiusSmall`. Resume, Retry, Submit, Merge, Got it, Keep, Archive, Undo. The
/// Inbox has no primary action, so every answer control that is a button is this one (DR-7: "Keep",
/// "Got it", "Archive" are neutral). It replaces `InboxActionButton`, whose `color` parameter was
/// the P2 problem in one argument.
struct NeutralButton: View {
    enum Size {
        case compact, regular
        var height: CGFloat { self == .compact ? 28 : 32 }
    }

    /// DR-41 — disabled keeps its label, dims to 45 %, and says why in `.help`.
    static let disabledOpacity = 0.45

    let title: String
    var systemImage: String? = nil
    var size: Size = .regular
    /// DR-49 — the key that acts, shown where it acts ("⏎" on Submit).
    var keyHint: String? = nil
    var shortcut: KeyboardShortcut? = nil
    var isDisabled = false
    var help: String? = nil
    var disabledHelp: String? = nil
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let systemImage {
                    Image(systemName: systemImage).font(CicadaTheme.icon(.inline))
                }
                Text(title)
                if let keyHint { KeyHint(keyHint) }
            }
            .font(CicadaTheme.font(size: size == .compact ? 12 : 13, weight: .medium))
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.scaled(size == .compact ? 10 : 12))
            .frame(height: CicadaTheme.scaled(size.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering && !isDisabled ? CicadaTheme.bgButtonHover : CicadaTheme.bgButton))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        }
        .buttonStyle(.cicadaPlain)
        .keyboardShortcut(shortcut)
        .disabled(isDisabled)
        .opacity(isDisabled ? Self.disabledOpacity : 1)
        .help(isDisabled ? (disabledHelp ?? help ?? title) : (help ?? title))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
```

`TextButton.swift`:

```swift
import SwiftUI

/// DR-40 — the text button: no fill at rest, `bgSelected` on hover, `textSecondary` → `textPrimary`.
/// Not now, Skip, Dismiss, Show all, "‹ 6 questions".
struct TextButton: View {
    static let height: CGFloat = 32

    let title: String
    var keyHint: String? = nil
    var help: String? = nil
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(title)
                if let keyHint { KeyHint(keyHint) }
            }
            .font(CicadaTheme.font(size: 13))
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(Self.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? CicadaTheme.bgSelected : Color.clear))
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
```

`Tag.swift`:

```swift
import SwiftUI

/// DR-44 — the one pill: 11 medium `textSecondary` on a `bgSelected` capsule, 18 pt tall, tabular.
/// A colour variant adds a 6 pt dot INSIDE the pill and never tints the pill. Never a filter, never
/// mono. The option rows' ages are this (DR-42).
struct Tag: View {
    static let height: CGFloat = 18
    static let dotSize: CGFloat = 6

    let text: String
    var dot: Color? = nil

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(5)) {
            if let dot {
                Circle().fill(dot).frame(width: CicadaTheme.scaled(Self.dotSize), height: CicadaTheme.scaled(Self.dotSize))
            }
            Text(text).monospacedDigit()
        }
        .font(CicadaTheme.font(size: 11, weight: .medium))
        .foregroundStyle(CicadaTheme.textSecondary)
        .padding(.horizontal, CicadaTheme.scaled(7))
        .frame(height: CicadaTheme.scaled(Self.height))
        .background(Capsule().fill(CicadaTheme.bgSelected))
    }
}
```

- [ ] **Step 4: The motion names.** Append to `CicadaMotion.swift`:
  - Put the durations and functions inside `enum CicadaMotion`, after `spanReveal`.
  - Put `CicadaCurve` and `Instant` at file scope. They must be in this file, because `MotionLiteralLintTests` allows
    `duration:` only here.

```swift
    // MARK: - Progressive columns (DR-61, DR-66)
    static let columnDuration: TimeInterval = 0.25
    static let readerInDuration: TimeInterval = 0.25
    static let readerOutDuration: TimeInterval = 0.18
    static let cardFadeDuration: TimeInterval = 0.15
    static let rowLeaveDuration: TimeInterval = 0.15
    static let undoFadeDuration: TimeInterval = 0.12
    /// DR-66 — Reduce Motion removes movement; a fade stays, shortened. The one family here that is
    /// not nil under Reduce Motion, on purpose: a column appearing with no fade at all reads as a jump.
    static let reducedFadeDuration: TimeInterval = 0.1
    static var fade: Animation { .linear(duration: reducedFadeDuration) }

    /// STATE 0 → 1 by pointer: the list's width on the drawer curve. Width is movement, so nil under
    /// Reduce Motion.
    static func columns(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : CicadaCurve.drawer(columnDuration)
    }
    static func readerIn(reduceMotion: Bool) -> Animation {
        reduceMotion ? fade : CicadaCurve.drawer(readerInDuration)
    }
    static func readerOut(reduceMotion: Bool) -> Animation {
        reduceMotion ? fade : CicadaCurve.drawer(readerOutDuration)
    }
    static func cardFade(reduceMotion: Bool) -> Animation {
        reduceMotion ? fade : CicadaCurve.out(cardFadeDuration)
    }
    static func rowLeave(reduceMotion: Bool) -> Animation {
        reduceMotion ? fade : CicadaCurve.out(rowLeaveDuration)
    }
    static func undoFade(reduceMotion: Bool) -> Animation {
        reduceMotion ? fade : CicadaCurve.out(undoFadeDuration)
    }
    /// The Reader column arriving: 16 pt of travel plus a fade, leaving by a fade (DR-61, DR-65);
    /// a fade alone under Reduce Motion.
    static func readerTransition(reduceMotion: Bool) -> AnyTransition {
        reduceMotion ? .opacity
            : .asymmetric(insertion: .opacity.combined(with: .offset(x: 16)), removal: .opacity)
    }
```

```swift
/// DR-62 — the four curves, with the approved mocks' control points: `out` is their
/// `cubic-bezier(.23,1,.32,1)`, `drawer` is the drawer curve columns open on, `ease` is CSS `ease`.
/// `.easeIn` never appears.
enum CicadaCurve {
    static func out(_ duration: TimeInterval) -> Animation { .timingCurve(0.23, 1, 0.32, 1, duration: duration) }
    static func inOut(_ duration: TimeInterval) -> Animation { .timingCurve(0.77, 0, 0.175, 1, duration: duration) }
    static func drawer(_ duration: TimeInterval) -> Animation { .timingCurve(0.32, 0.72, 0, 1, duration: duration) }
    static func ease(_ duration: TimeInterval) -> Animation { .timingCurve(0.25, 0.1, 0.25, 1, duration: duration) }
}

/// DR-60 — a keyboard action never animates. `body` runs in a transaction that disables every
/// implicit animation, so a pointer path's `.animation(_:value:)` on the same value cannot catch it.
enum Instant {
    static func run(_ body: () -> Void) {
        var transaction = Transaction()
        transaction.disablesAnimations = true
        withTransaction(transaction, body)
    }
}
```

- [ ] **Step 5: Green.**
  - Run the Step 1 filter. It passes.
  - `swift build` succeeds.
  - The full `swift test` reports 0 failures.
- [ ] **Step 6: Commit.** Stage only the four new sources, `CicadaMotion.swift` and the three test files. Message:
  `feat(ds2): progressive columns and the controls they need — ColumnLayout, NeutralButton, TextButton, Tag (DR-26, DR-27, DR-31, DR-34, DR-36, DR-40, DR-41, DR-44, DR-60, DR-61, DR-62, DR-66, DR-70)`.

---

### Task 2: One tap holds the answer for 5 s — the send delay (DR-42; G113, G115; R-DI2…R-DI5)

After this task every answer is held and sent later. The old list still hides the card at once and shows no Undo row
yet (Task 5 draws it). Visible behaviour is unchanged except that the POST leaves 5 s later, or at quit.

**Files:**
- Create: `app/…/Sync/ResolveGrace.swift`, `app/…/Support/QuitFlush.swift`, `app/…/Theme/Copy+Inbox.swift`
- Modify:
  - `app/…/Sync/Store.swift`: the stored properties next to `hiddenInboxIds` (`:47-57`), `visibleInbox`, and the guard
    in `hydrate` after the bank is resolved (after `:179`);
  - `app/…/Sync/Mutations.swift`: `ActivateBank.optimistic` (`:430`);
  - `app/…/Theme/CicadaTiming.swift`;
  - `app/…/Support/DockOpenQueue.swift`: `CicadaAppDelegate`, `:29`;
  - `app/…/CicadaApp.swift`: the `.onAppear` wiring beside `inboxVM.onResolved`, `:246-248`;
  - `app/…/ContentView.swift`: one `.onDisappear` on `body`;
  - `app/…/ViewModels/InboxViewModel.swift`: `resolve` → `answer` / `undo`;
  - `app/…/Models/InboxPresentation.swift`: `UndoLabel`;
  - `app/…/Views/Inbox/InboxListView.swift:56-66` and `app/…/Views/Sources/ChannelSourceView.swift:129-135`: call
    `answer`.
- Test: `ResolveGraceTests.swift` (new); `InboxQuestionTests.swift:99-127` (the two resolve tests move onto `answer`).

**Interfaces:**
- Produces:
  - `ResolveGrace` (`resolve`, `label`, `shortLabel`, `question`, `kind`, `channel`, `bank`, `token`, `id`);
  - on the Store: `heldResolve`, `sendingInboxIds`, `currentHeld`, `graceHiddenIds`, `hold(_:label:shortLabel:question:kind:channel:)`,
    `undoHeld() -> String?`, `flushHeld() async`, `expire(token:) async`, `graceWait` (a test seam) and
    `onHeldResolveSent`;
  - `QuitFlush.reply(hasHeld:)` and `QuitFlush.run(_:limit:)`;
  - `CicadaTiming.undoWindow` (5) and `quitFlushLimit` (3);
  - `UndoLabel.of(_:item:)`;
  - `InboxViewModel.answer(_:_:)` and `undo(reopen:) -> InboxItem?`;
  - `Copy.Inbox`.
- Consumes: `Store.perform`, `InboxResolve`, `ActivateBank`, `FakeSyncAPI` (tests).

- [ ] **Step 1: Failing tests.** Create `ResolveGraceTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// DR-42 — one tap resolves, and Undo is a SEND DELAY: nothing is POSTed until the window closes,
/// the next answer starts, the bank changes, the window closes or the app quits. An undone answer
/// therefore writes no commit, no claim and no G113 `resolution` event (R-DI2 … R-DI4).
@MainActor
final class ResolveGraceTests: XCTestCase {
    private static let twoItems = """
    [{"id":"inbox-001","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use now?",
      "question":"What does alpha-project use now?",
      "options":[{"key":"a","label":"Tool Example A"},{"key":"b","label":"Tool Example B"}]},
     {"id":"inbox-002","kind":"merge_suggestion","requiredInput":"merge","title":"Same as tool-example-a?"}]
    """

    private func makeStore() throws -> (Store, FakeSyncAPI) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: api)
        api.replies[.inbox] = .notModified
        store.inbox.value = try JSONDecoder().decode([InboxItem].self, from: Data(Self.twoItems.utf8))
        // The window never closes on its own unless a test says so.
        store.graceWait = { _ in try? await Task.sleep(for: .seconds(3600)) }
        return (store, api)
    }

    private func hold(_ store: Store, _ id: String, action: String = "resolve", optionKey: String? = "b") {
        store.hold(InboxResolve(id: id, action: action, optionKey: optionKey),
                   label: "Answered · Tool Example B", shortLabel: "Answered", question: "q",
                   kind: .conflict, channel: nil)
    }

    private func eventually(_ condition: @autoclosure () -> Bool,
                            file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<200_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never happened", file: file, line: line)
    }

    func testAHeldAnswerSendsNothingAndHidesItsQuestionAtOnce() throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        XCTAssertEqual(api.writes, [], "a tap is not a commit")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-002"], "the badge, Home and the palette agree at once")
        XCTAssertEqual(store.currentHeld?.id, "inbox-001")
    }

    func testUndoInsideTheWindowSendsNothingEver() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        let token = try XCTUnwrap(store.heldResolve?.token)
        XCTAssertEqual(store.undoHeld(), "inbox-001")
        await store.expire(token: token)
        await store.flushHeld()
        XCTAssertEqual(api.writes, [], "an undone answer emits no G113 verdict")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"])
    }

    func testTheWindowClosingSendsTheAnswerOnce() async throws {
        let (store, api) = try makeStore()
        store.graceWait = { _ in }
        hold(store, "inbox-001")
        await eventually(api.writes == ["resolveInbox:inbox-001:resolve:b:nil"])
        XCTAssertNil(store.heldResolve)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-002"], "still hidden until a snapshot drops it")
    }

    func testTheNextAnswerSendsThePreviousAtOnce() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        hold(store, "inbox-002", action: "skip", optionKey: nil)
        XCTAssertEqual(store.visibleInbox.map(\.id), [], "the first is on the wire, the second is held — neither flashes back")
        await eventually(api.writes.count == 1)
        XCTAssertEqual(api.writes, ["resolveInbox:inbox-001:resolve:b:nil"])
        XCTAssertEqual(store.heldResolve?.id, "inbox-002")
    }

    /// R-DI3 — every bank switch is `ActivateBank`; it sends the held answer before the bank moves.
    func testABankSwitchSendsTheHeldAnswerFirst() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        _ = await store.perform(ActivateBank(name: "work"))
        XCTAssertEqual(Array(api.writes.prefix(2)), ["resolveInbox:inbox-001:resolve:b:nil", "activateBank:work"])
    }

    func testAFailedSendPutsTheQuestionBackAndSaysSo() async throws {
        let (store, api) = try makeStore()
        api.failWrites = true
        hold(store, "inbox-001")
        await store.flushHeld()
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"])
        XCTAssertEqual(store.toast, "Couldn't resolve that item — reverted")
    }

    /// R-DI4 — a skipped question is still pending: gone for the window, back after the send.
    func testASkippedQuestionComesBackOnceItIsSent() async throws {
        let (store, _) = try makeStore()
        hold(store, "inbox-002", action: "skip", optionKey: nil)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001"])
        await store.flushHeld()
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"])
    }

    /// R-DI3 — ids repeat across banks; a hold is only ever sent to the bank it was made in.
    func testAHoldIsNeverSentIntoAnotherBank() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        store.bank = "another-bank"
        XCTAssertNil(store.currentHeld, "a hold from another bank hides nothing here")
        await store.flushHeld()
        XCTAssertEqual(api.writes, [])
        XCTAssertEqual(store.toast, Copy.Inbox.answerNotSaved)
    }

    /// R-DI3 — answered elsewhere inside the window (MCP, an organic Sleep resolve): nothing to send, and no
    /// "reverted" toast for an answer that was never refused.
    func testAQuestionThatVanishedInsideTheWindowSendsNothing() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        store.inbox.value = store.inbox.value?.filter { $0.id != "inbox-001" }
        await store.flushHeld()
        XCTAssertEqual(api.writes, [])
        XCTAssertNil(store.toast)
    }

    func testTheMenuBarHearsWhenAHeldAnswerLands() async throws {
        let (store, _) = try makeStore()
        var heard = 0
        store.onHeldResolveSent = { heard += 1 }
        hold(store, "inbox-001")
        await store.flushHeld()
        XCTAssertEqual(heard, 1)
    }

    func testQuitWaitsOnlyWhenSomethingIsHeldAndNeverPastItsLimit() async {
        XCTAssertEqual(QuitFlush.reply(hasHeld: false), .terminateNow)
        XCTAssertEqual(QuitFlush.reply(hasHeld: true), .terminateLater)
        let hung = await QuitFlush.run({ try? await Task.sleep(for: .seconds(60)) }, limit: .milliseconds(50))
        XCTAssertFalse(hung, "a backend that is gone never keeps the app open")
        let quick = await QuitFlush.run({}, limit: .seconds(5))
        XCTAssertTrue(quick)
    }

    func testTheViewModelAnswersThroughTheHoldAndUndoReturnsTheQuestion() throws {
        let (store, api) = try makeStore()
        let vm = InboxViewModel(store: store)
        let item = try XCTUnwrap(store.inbox.value?.first)
        vm.answer(item, QuestionResolution(action: "resolve", optionKey: "b"))
        XCTAssertEqual(vm.pendingCount, 1, "the rail badge drops on the tap")
        XCTAssertEqual(api.writes, [])
        XCTAssertEqual(store.heldResolve?.label, "Answered · Tool Example B")
        XCTAssertEqual(vm.undo(reopen: false)?.id, "inbox-001")
        XCTAssertEqual(vm.pendingCount, 2)
    }
}

/// R-DI5 — what the Undo row says: words, never the action's wire name.
final class UndoLabelTests: XCTestCase {
    private func item(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testEveryActionHasItsWords() throws {
        let conflict = try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","options":[{"key":"b","label":"Tool Example B"}]}"#)
        let info = try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","informational":true}"#)
        func words(_ r: QuestionResolution, _ i: InboxItem) -> [String] {
            let w = UndoLabel.of(r, item: i)
            return [w.full, w.short]
        }
        XCTAssertEqual(words(.init(action: "resolve", optionKey: "b"), conflict), ["Answered · Tool Example B", "Answered"])
        XCTAssertEqual(words(.init(action: "resolve", answer: "Tool C", optionKey: "neither"), conflict), ["Answered · Tool C", "Answered"])
        XCTAssertEqual(words(.init(action: "resolve", optionKey: "remind_later"), conflict), ["Not now", "Not now"])
        XCTAssertEqual(words(.init(action: "answer", answer: "a colleague"), conflict), ["Answered · a colleague", "Answered"])
        XCTAssertEqual(words(.init(action: "defer", remindDays: 7), conflict), ["Not now", "Not now"])
        XCTAssertEqual(words(.init(action: "dismiss"), info), ["Got it", "Got it"])
        XCTAssertEqual(words(.init(action: "dismiss"), conflict), ["Dismissed", "Dismissed"])
        XCTAssertEqual(words(.init(action: "skip"), conflict), ["Skipped", "Skipped"])
        XCTAssertEqual(words(.init(action: "reject", mergeTarget: "x"), conflict), ["Kept separate", "Kept"])
        XCTAssertEqual(words(.init(action: "merge", mergeTarget: "x"), conflict), ["Merged", "Merged"])
        XCTAssertEqual(words(.init(action: "keep_active"), conflict), ["Kept", "Kept"])
        XCTAssertEqual(words(.init(action: "archive"), conflict), ["Archived", "Archived"])
    }
}
```

In `InboxQuestionTests.swift:99-125`, replace the two `vm.resolve(...)` tests with their `answer` twins (the class is
already `@MainActor` and has a `decode(_:)` helper):

```swift
    private func heldStore() throws -> (Store, FakeSyncAPI, InboxViewModel, InboxItem) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: api)
        api.replies[.inbox] = .notModified
        let item = try decode(#"{"id":"inbox-001","kind":"conflict","requiredInput":"choice","title":"t","options":[{"key":"b","label":"B"}]}"#)
        store.inbox.value = [item]
        return (store, api, InboxViewModel(store: store), item)
    }

    func testAnswerPassesOptionKeyThroughWhenTheWindowCloses() async throws {
        let (store, api, vm, item) = try heldStore()
        vm.answer(item, QuestionResolution(action: "resolve", optionKey: "b"))
        XCTAssertEqual(api.writes, [], "held for its Undo window (DR-42)")
        await store.flushHeld()
        XCTAssertTrue(api.writes.contains("resolveInbox:inbox-001:resolve:b:nil"))
    }

    func testDeferPassesRemindDaysThroughWhenTheWindowCloses() async throws {
        let (store, api, vm, item) = try heldStore()
        vm.answer(item, QuestionResolution(action: "defer", remindDays: 14))
        XCTAssertEqual(store.visibleInbox.map(\.id), [], "a deferred question leaves the list on the tap")
        await store.flushHeld()
        XCTAssertTrue(api.writes.contains("resolveInbox:inbox-001:defer:nil:14"))
    }
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'ResolveGraceTests|UndoLabelTests|InboxQuestionTests' 2>&1 | tail -20`.
It fails to compile. That is the red.

- [ ] **Step 2: Timing and words.** In `CicadaTiming.swift`, add inside the enum:

```swift
    /// DR-42 — how long an answer waits for Undo before it is sent. A delay, not motion: Reduce
    /// Motion never shortens the time a person has to take a tap back.
    static let undoWindow: TimeInterval = 5
    /// R-DI3 — how long quit waits for a held answer to land before the app closes anyway.
    static let quitFlushLimit: TimeInterval = 3
```

Create `Theme/Copy+Inbox.swift`. It is its own file for the reason `Copy+Provenance.swift` gives: parallel tracks edit
`Copy.swift`.

```swift
import Foundation

/// DS-2 — every sentence the Inbox's columns say, in one place (DR-59: sentence case, plain verbs,
/// no "!", no bare "%", no ids — DR-54).
extension Copy {
    enum Inbox {
        static let title = "Inbox"
        static func pending(_ n: Int) -> String { "\(UsageFormat.count(n)) pending" }
        static func position(_ i: Int, of n: Int) -> String { "\(UsageFormat.count(i)) of \(UsageFormat.count(n))" }
        static let all = "All"

        // The Undo row (R-DI5)
        static let answered = "Answered"
        static func answered(_ what: String) -> String { "Answered · \(what)" }
        static let notNow = "Not now"
        static let gotIt = "Got it"
        static let dismissed = "Dismissed"
        static let skipped = "Skipped"
        static let keptSeparate = "Kept separate"
        static let kept = "Kept"
        static let merged = "Merged"
        static let archived = "Archived"
        static let undo = "Undo"
        static let undoHelp = "Undo (⌘Z)"
        /// R-DI3 — another client moved the active bank inside the window.
        static let answerNotSaved = "Your last answer wasn't saved because the memory bank changed. It's still in the inbox."
    }
}
```

- [ ] **Step 3: `UndoLabel`** (append to `Models/InboxPresentation.swift`):

```swift
/// R-DI5 / DR-42 — what the Undo row says for an answer: the full form in the list, the short
/// one while the Reader is open ("Answered · Undo"). Words, never the action's wire name.
enum UndoLabel {
    static func of(_ r: QuestionResolution, item: InboxItem) -> (full: String, short: String) {
        let typed = r.answer?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        switch r.action {
        case "resolve":
            if r.optionKey == "remind_later" { return (Copy.Inbox.notNow, Copy.Inbox.notNow) }
            if !typed.isEmpty { return (Copy.Inbox.answered(typed), Copy.Inbox.answered) }
            if let key = r.optionKey, let option = item.options.first(where: { $0.key == key }) {
                return (Copy.Inbox.answered(option.label), Copy.Inbox.answered)
            }
            return (Copy.Inbox.answered, Copy.Inbox.answered)
        case "answer":
            return (typed.isEmpty ? Copy.Inbox.answered : Copy.Inbox.answered(typed), Copy.Inbox.answered)
        case "defer", "remind_later":
            return (Copy.Inbox.notNow, Copy.Inbox.notNow)
        case "dismiss":
            let words = item.informational ? Copy.Inbox.gotIt : Copy.Inbox.dismissed
            return (words, words)
        case "skip": return (Copy.Inbox.skipped, Copy.Inbox.skipped)
        case "reject": return (Copy.Inbox.keptSeparate, Copy.Inbox.kept)
        case "merge": return (Copy.Inbox.merged, Copy.Inbox.merged)
        case "keep_active": return (Copy.Inbox.kept, Copy.Inbox.kept)
        case "archive": return (Copy.Inbox.archived, Copy.Inbox.archived)
        default: return (Copy.Inbox.answered, Copy.Inbox.answered)
        }
    }
}
```

- [ ] **Step 4: The Store's state.** In `Store.swift`, add these after `hiddenInboxIds` (`:51`) and replace
  `visibleInbox` (`:55-57`):

```swift
    /// DR-42 (R-DI2) — the one answer inside its Undo window, and the ids whose held answer is on
    /// the wire. Both leave `visibleInbox`, so the rail badge, Home and the palette drop a question
    /// the moment it is tapped — not five seconds later, and not only on the Inbox.
    var heldResolve: ResolveGrace?
    var sendingInboxIds: Set<String> = []
    @ObservationIgnored var graceTask: Task<Void, Never>?
    @ObservationIgnored var graceToken = 0
    /// How the window waits; tests replace it (it is the only seam `ResolveGraceTests` needs).
    @ObservationIgnored var graceWait: @MainActor (Duration) async -> Void = { try? await Task.sleep(for: $0) }
    /// Wired by `InboxViewModel` to the menu-bar badge's refresh, the hook `resolve` used to call.
    @ObservationIgnored var onHeldResolveSent: (() async -> Void)?

    /// The inbox as the UI should see it: the snapshot minus anything hidden by an in-flight or
    /// already-confirmed resolve, and minus an answer inside its Undo window (DR-42).
    var visibleInbox: [InboxItem] {
        let grace = graceHiddenIds
        return (inbox.value ?? []).filter { !hiddenInboxIds.contains($0.id) && !grace.contains($0.id) }
    }
```

In `hydrate(bank:)`, insert this right after the bank is resolved (before `var loaded`, `:181`):

```swift
        // R-DI3 — a held answer belongs to the bank it was made in. `ActivateBank` sends it before
        // the switch; a switch that arrives from elsewhere (another client moved the roster) drops
        // it with a word rather than post it into the wrong bank.
        if let held = heldResolve, held.bank != bank {
            graceTask?.cancel()
            graceTask = nil
            heldResolve = nil
            toast = Copy.Inbox.answerNotSaved
        }
```

- [ ] **Step 5: `Sync/ResolveGrace.swift`:**

```swift
import Foundation

/// DR-42 — one answer held for its Undo window (R-DI2). Undo is a SEND DELAY, not a revert:
/// `POST /inbox/{id}/resolve` leaves only when the window closes, when the next answer starts, or
/// before a bank switch, the main window closing or a quit (R-DI3). An undone answer therefore
/// writes no commit, no claim and no G113 `resolution` event — there is nothing to revert. The
/// send itself is the ordinary `InboxResolve` mutation: its optimistic hide, rollback-with-toast
/// and `.inbox` refresh are reused, not re-implemented.
struct ResolveGrace {
    static var window: Duration { .seconds(CicadaTiming.undoWindow) }

    let resolve: InboxResolve
    /// "Answered · sqlite-vec" in the list; the short form beside the Reader (R-DI5).
    let label: String
    let shortLabel: String
    let question: String
    let kind: InboxKind
    /// G129 — a removal's browser channel, so the Sources page shows its own Undo row (R-DI16).
    let channel: String?
    /// Ids repeat across banks (`inbox-001` is in every one): a hold is sent only to its own bank.
    let bank: String
    let token: Int

    var id: String { resolve.id }
}

extension Store {
    /// The held answer, if it belongs to the bank on screen.
    var currentHeld: ResolveGrace? {
        guard let held = heldResolve, held.bank == bank else { return nil }
        return held
    }

    /// What the send delay hides from `visibleInbox`.
    var graceHiddenIds: Set<String> {
        var ids = sendingInboxIds
        if let held = currentHeld { ids.insert(held.id) }
        return ids
    }

    /// Hold an answer for the Undo window. A previous hold is sent NOW, without waiting, so the next
    /// question paints this frame; it moves to `sendingInboxIds` first so it never flashes back.
    func hold(_ resolve: InboxResolve, label: String, shortLabel: String, question: String,
              kind: InboxKind, channel: String?) {
        if let previous = heldResolve {
            heldResolve = nil
            sendingInboxIds.insert(previous.id)
            Task { await self.send(previous) }
        }
        graceToken &+= 1
        let token = graceToken
        heldResolve = ResolveGrace(resolve: resolve, label: label, shortLabel: shortLabel, question: question,
                                   kind: kind, channel: channel, bank: bank, token: token)
        graceTask?.cancel()
        let wait = graceWait
        graceTask = Task { [weak self] in
            await wait(ResolveGrace.window)
            guard !Task.isCancelled else { return }
            await self?.expire(token: token)
        }
    }

    /// Undo inside the window: nothing was sent, so nothing is reverted. Returns the id to reopen.
    @discardableResult
    func undoHeld() -> String? {
        guard let held = heldResolve else { return nil }
        graceTask?.cancel()
        graceTask = nil
        heldResolve = nil
        return held.id
    }

    /// The window closed on its own; a stale token (an Undo, or a newer hold) sends nothing.
    func expire(token: Int) async {
        guard let held = heldResolve, held.token == token else { return }
        await flushHeld()
    }

    /// Send the held answer now: the window's end, a bank switch, the window closing, quit.
    func flushHeld() async {
        guard let held = heldResolve else { return }
        graceTask?.cancel()
        graceTask = nil
        heldResolve = nil
        sendingInboxIds.insert(held.id)
        await send(held)
    }

    private func send(_ held: ResolveGrace) async {
        defer { sendingInboxIds.remove(held.id) }
        guard held.bank == bank else {
            toast = Copy.Inbox.answerNotSaved
            return
        }
        // R-DI3 — answered elsewhere inside the window: a fresh snapshot without the id means the server
        // already closed it, and a POST would 404 into a "reverted" toast. No snapshot at all (a cache
        // miss) is not evidence of that, so it still sends.
        if let items = inbox.value, !items.contains(where: { $0.id == held.id }) { return }
        _ = await perform(held.resolve)
        await onHeldResolveSent?()
    }
}
```

- [ ] **Step 6: Every bank switch sends first.** At the top of `ActivateBank.optimistic` (`Mutations.swift:430`), add
  the flush:

```swift
        // DR-42 (R-DI3) — a held answer is sent before the bank moves: the POST goes to the bank that
        // is active on the server, and `hydrate` clears every hide. Every switch path is this mutation.
        await store.flushHeld()
```

- [ ] **Step 7: Quit and the window closing.** Create `Support/QuitFlush.swift`:

```swift
import AppKit

/// DR-42 (R-DI3) — ⌘Q inside an Undo window sends the answer first, so a tap is never lost to
/// quitting; a backend that is gone never holds the app open past `quitFlushLimit`.
enum QuitFlush {
    static func reply(hasHeld: Bool) -> NSApplication.TerminateReply {
        hasHeld ? .terminateLater : .terminateNow
    }

    /// Runs `send`, but returns by `limit` at the latest. True when the send finished in time.
    /// `withTaskGroup` waits for every child, so the cap holds because the losing child is CANCELLED and
    /// the send is cancellation-aware: `perform` → `URLSession` drops its request on cancellation.
    @MainActor
    static func run(_ send: @escaping @MainActor () async -> Void, limit: Duration) async -> Bool {
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { await send(); return true }
            group.addTask { try? await Task.sleep(for: limit); return false }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
    }
}
```

In `CicadaAppDelegate` (`DockOpenQueue.swift`), add:

```swift
    /// DR-42 (R-DI3) — set by `CicadaApp` once the Store exists.
    var heldAnswer: () -> Bool = { false }
    var sendHeldAnswer: (@MainActor () async -> Void)?

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard QuitFlush.reply(hasHeld: heldAnswer()) == .terminateLater, let send = sendHeldAnswer else {
            return .terminateNow
        }
        Task { @MainActor in
            _ = await QuitFlush.run(send, limit: .seconds(CicadaTiming.quitFlushLimit))
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
```

In `CicadaApp.swift`'s `.onAppear`, next to `inboxVM.onResolved = …` (`:246-248`), add:

```swift
                    appDelegate.heldAnswer = { [store] in store.heldResolve != nil }
                    appDelegate.sendHeldAnswer = { [store] in await store.flushHeld() }
```

In `ContentView.body`, after `.onAppear { … }`, add:

```swift
        // DR-42 (R-DI3) — the window closing sends a held answer now; the app lives on in the menu bar.
        .onDisappear { Task { await store.flushHeld() } }
```

- [ ] **Step 8: The view model.** In `InboxViewModel.swift`:
  - Replace `resolve(...)` (`:59-91`) with `answer` and `undo` below.
  - In `init`, add `store.onHeldResolveSent = { [weak self] in await self?.onResolved?() }`.
  - Update the type's doc comment (`:4-9`): the POST now waits for the Undo window.

```swift
    /// DR-42 — the one tap. The answer is held (`Store.hold`) and its question leaves every list at
    /// once; the POST waits for the Undo window (R-DI2). Nothing to await: there is no request yet.
    func answer(_ item: InboxItem, _ resolution: QuestionResolution) {
        let words = UndoLabel.of(resolution, item: item)
        store.hold(InboxResolve(id: item.id, action: resolution.action, answer: resolution.answer,
                                optionKey: resolution.optionKey, remindDays: resolution.remindDays,
                                mergeTarget: resolution.mergeTarget, mergeSurvivor: resolution.mergeSurvivor),
                   label: words.full, shortLabel: words.short, question: item.questionText,
                   kind: item.kind, channel: item.channel)
    }

    /// DR-42 — Undo: the held answer is dropped unsent. Returns the question so the page can reopen
    /// it; `reopen: false` is the Sources page's, which has no columns (R-DI16).
    @discardableResult
    func undo(reopen: Bool = true) -> InboxItem? {
        guard let id = store.undoHeld() else { return nil }
        return store.inbox.value?.first { $0.id == id }
    }
```

`reopen` is kept in the signature now, and Task 5 uses it once the columns exist.

In `InboxListView.swift:56-66` and `ChannelSourceView.swift:129-135`, replace the closure body with:

```swift
                                    viewModel.answer(item, resolution)   // `inboxVM` in ChannelSourceView
                                    return true
```

- [ ] **Step 9: Green.**
  - Run the Step 1 filter, then `swift build`, then the full `swift test`. All pass with 0 failures.
  - `rg -n 'func resolve\(' app/CicadaApp/Sources/CicadaApp/ViewModels` prints nothing.
- [ ] **Step 10: Commit.** Stage named files only. Message:
  `feat(ds2, g113): one tap holds the answer for 5 s — sent when the window ends, on the next answer, before a bank switch, when the window closes and at quit (DR-42)`.

---

### Task 3: The focus card — every kind, one-tap option rows, the quote hero, the source in a person's words (DR-16…DR-18, DR-42…DR-44, DR-49, DR-52…DR-58; G60, G98, G115, G118, G141 PJ-6)

The question column's content. It is built and tested here, and mounted by Task 5. The branch stays shippable: the old
list keeps `InboxCardView` until then.

**Files:**
- Create: `app/…/Views/Inbox/InboxFocusCard.swift`, `app/…/Views/Inbox/OptionRow.swift`,
  `app/…/Views/Inbox/FocusCardVariants.swift`
- Modify:
  - `app/…/Models/InboxPresentation.swift`;
  - `app/…/Models/InboxItem.swift`: `icon` `:50-63` and `ageCapsule` `:91-100`;
  - `app/…/Models/QuestionSelection.swift`: add `highlight(_:)`;
  - `app/…/Views/Common/CitedSpan.swift`;
  - `app/…/Views/Inbox/QuestionView.swift`: `QuestionResolution` gains `: Equatable` (`:6`), and `:153`'s `firstURL`
    becomes `HintLink.firstURL`, so the rule has one source until Task 5 retires the view.
- Test: `InboxPresentationTests.swift`, `InboxQuestionTests.swift`, `CitedSpanTests.swift`, `InboxFocusCardFitTests.swift`
  (new)

**Interfaces:**
- Produces:
  - `InboxAge.compact(days:)`, `InboxRowAge.of(_:now:locale:timeZone:)`;
  - `InboxSourceLine.full / row / help / markOrigin / app`;
  - `ExcerptText.clean(_:)`;
  - `QuoteSegments.of(_:)`, `.isDerived(_:)`;
  - `InboxGuess.text(_:)`, `HintLink.firstURL(in:)`, `FreeTextSubmit.resolution(for:text:)`;
  - `FocusCardVariant.of(_:)`, `MergeDirection.line(...)`, `QuestionSelection.highlight(_:)`;
  - `CitedSpan.Mark.mention`, `CitedSpan.fallback(_:reveal:)`, `.citedSpans(reveal:)`;
  - `InboxFocusCard(item:padding:onClose:hiddenListCount:onShowList:onEscape:onEditingChange:onAnswer:)`, `OptionRow`,
    `RadioMark`, `KindGlyph`;
  - new `Copy.Inbox` strings.
- Consumes: `InboxItem`, `InboxCause.readerTarget`, `ReaderTime`, `EvidenceSpeaker`, `OriginIconography`, `QuoteBlock.parts`,
  `ProvenanceRouter?` (an optional environment value, as `InboxCardView` reads it), Task 1's controls.

- [ ] **Step 1: Failing tests.** Append to `InboxPresentationTests.swift`. Use en_US and UTC so the day format is stable
  (the `ReaderTurnsTests` note on en_GB's "Sept").

```swift
    // MARK: - DS-2 (R-DI12, R-DI15, R-DI22)

    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!

    private func item(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    private func caused(_ cause: String, extra: String = "") throws -> InboxItem {
        try item(#"{"id":"inbox-001","kind":"conflict","requiredInput":"choice","title":"t"\#(extra),"cause":\#(cause)}"#)
    }

    func testCompactAgesShareThePhrasesBoundaries() {
        XCTAssertEqual([0, 1, 5, 13, 14, 20, 59, 60, 193, 364, 365, 800].map(InboxAge.compact(days:)),
                       ["today", "1d", "5d", "13d", "2w", "3w", "8w", "2mo", "6mo", "12mo", "1y", "2y"])
    }

    func testTheSourceLineNamesAConversationTheWayAPersonWould() throws {
        let titled = try caused(#"{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","conversationTitle":"Index choice","excerpt":"x","tier":"claim"}"#)
        XCTAssertEqual(InboxSourceLine.full(titled, locale: us, timeZone: utc), "Claude Code · Index choice · Aug 25")
        XCTAssertEqual(InboxSourceLine.row(titled, locale: us, timeZone: utc), "Claude Code · Aug 25")
        XCTAssertEqual(InboxSourceLine.help(titled), "Episode ep_2026-08-25_001")
        XCTAssertEqual(InboxSourceLine.markOrigin(titled), "claude-code")

        let untitled = try caused(#"{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","excerpt":"x","tier":"claim"}"#)
        XCTAssertEqual(InboxSourceLine.full(untitled, locale: us, timeZone: utc), "a Claude Code conversation · Aug 25")

        let exported = try caused(#"{"episodeId":"ep_2026-05-02_003","timestamp":"2026-05-02T09:00:00Z","origin":"chatgpt-export","conversationTitle":"Planning","excerpt":"x","tier":"entity"}"#)
        XCTAssertEqual(InboxSourceLine.full(exported, locale: us, timeZone: utc), "ChatGPT · Planning · May 2")

        let none = try caused(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)
        XCTAssertEqual(InboxSourceLine.full(none), "[ no source recorded ]", "DR-55 — served exactly as written")
        XCTAssertEqual(InboxSourceLine.row(none), "[ no source recorded ]")
        XCTAssertNil(InboxSourceLine.help(none))

        for line in [InboxSourceLine.full(titled), InboxSourceLine.row(titled), InboxSourceLine.full(untitled)] {
            XCTAssertFalse(line.contains("ep_") || line.contains("claude-code"), "DR-54: \(line)")
        }
    }

    func testTheRowAgeIsCompactWithTheDayInHelpAndADashWithItsReason() throws {
        let now = ISO8601DateFormatter().date(from: "2026-09-22T10:00:00Z")!
        let titled = try caused(#"{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","excerpt":"x","tier":"claim"}"#)
        let age = InboxRowAge.of(titled, now: now, locale: us, timeZone: utc)
        XCTAssertEqual(age.text, "4w")
        XCTAssertEqual(age.help, "Aug 25, 2026")
        let none = try caused(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)
        XCTAssertEqual(InboxRowAge.of(none, now: now).text, "—")
        XCTAssertEqual(InboxRowAge.of(none, now: now).help, Copy.Inbox.noSourceAge)
    }

    /// DR-56 / R-DI22 — clean per segment: markers and wikilinks go, a segment's edges stay.
    func testTheExcerptIsCleanTextAndKeepsItsEdges() {
        XCTAssertEqual(ExcerptText.clean("# Episode 12\n- swapped the store"), "Episode 12 swapped the store")
        XCTAssertEqual(ExcerptText.clean("see [[alpha-project-notes]] now"), "see Alpha Project Notes now")
        XCTAssertEqual(ExcerptText.clean("[[alpha-project|Alpha]] and > quoted"), "Alpha and > quoted")
        XCTAssertEqual(ExcerptText.clean("> a quote\n\n  and more  "), "a quote and more ")
        XCTAssertEqual(ExcerptText.clean(" so anomaly"), " so anomaly", "never trims — it would glue the segments")
        XCTAssertEqual(ExcerptText.clean(" - 3 more", atLineStart: false), " - 3 more", "a mid-line segment keeps its minus")
        XCTAssertEqual(ExcerptText.clean("see [[alpha-project|"), "see ", "a link the mention split leaves no brackets")
        XCTAssertEqual(ExcerptText.clean("]] and on"), " and on")
    }

    /// R-DI18 / DR-53 — every kind glyph is an outline symbol; the hue alone carries the kind (DR-8).
    func testKindGlyphsAreOutlineSymbols() {
        let kinds: [InboxKind] = [.decay, .conflict, .clarification, .mergeSuggestion, .divergence, .normalization,
                                  .removal, .followup, .unknown]
        XCTAssertEqual(kinds.filter { $0.icon.hasSuffix(".fill") }, [])
    }

    /// R-DI11 — an asserted G118 span is washed; a mention found by name is semibold and says so.
    func testTheQuoteWashesOnlyWhatWasQuoted() throws {
        let asserted = try caused(#"{"episodeId":"ep_1","excerpt":"Discussed swapping the store","mentionOffsets":[[10,18]],"start":0,"tier":"claim","spanKind":"asserted"}"#)
        XCTAssertEqual(QuoteSegments.of(asserted), [.init(text: "Discussed ", mark: .plain),
                                                    .init(text: "swapping", mark: .current),
                                                    .init(text: " the store", mark: .plain)])
        XCTAssertFalse(QuoteSegments.isDerived(asserted))
        let derived = try caused(#"{"episodeId":"ep_1","excerpt":"Discussed swapping the store","mentionOffsets":[[10,18]],"start":0,"tier":"claim","spanKind":"derived"}"#)
        XCTAssertEqual(QuoteSegments.of(derived)?[1], .init(text: "swapping", mark: .mention))
        XCTAssertTrue(QuoteSegments.isDerived(derived))
        let none = try caused(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)
        XCTAssertNil(QuoteSegments.of(none), "no source → no quote block at all")
    }

    func testTheGuessIsTheExtractorsAndNeverOnAnInformationalCard() throws {
        XCTAssertEqual(InboxGuess.text(try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","extractorModel":"gpt-5.4-mini","extractorConfidence":0.85}"#)),
                       "gpt-5.4-mini's guess at 0.85")
        XCTAssertEqual(InboxGuess.text(try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","extractorConfidence":0.4}"#)),
                       "Cicada's guess at 0.40")
        XCTAssertNil(InboxGuess.text(try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","extractorModel":"m","informational":true}"#)))
    }

    func testTheHintsLinkIsItsFirstURL() {
        XCTAssertEqual(HintLink.firstURL(in: "You said https://example.com/alpha-project is where to check")?.host, "example.com")
        XCTAssertNil(HintLink.firstURL(in: "Only you know this"))
    }

    /// R-DI15 — every kind lands on a variant; free text keeps its two wire shapes.
    func testEveryKindHasAVariant() throws {
        let options = #","options":[{"key":"a","label":"A"},{"key":"b","label":"B"}]"#
        let table: [(String, FocusCardVariant)] = [
            (#"{"id":"1","kind":"conflict","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"conflict","requiredInput":"choice","title":"t","informational":true\#(options)}"#, .informational),
            (#"{"id":"1","kind":"decay","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"decay","requiredInput":"choice","title":"t"}"#, .legacyDecay),
            (#"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"Who is bob-example?","allowOther":true,"allowDefer":true}"#, .freeText),
            (#"{"id":"1","kind":"merge_suggestion","requiredInput":"merge","title":"t"}"#, .merge),
            (#"{"id":"1","kind":"removal","requiredInput":"choice","title":"t","options":[{"key":"keep","label":"Keep"},{"key":"remove","label":"Remove"}]}"#, .options),
            (#"{"id":"1","kind":"divergence","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"normalization","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"followup","requiredInput":"choice","title":"t","question":"“Wire the lab cluster” — last heard 3 weeks ago. How did it go?","allowOther":true,"options":[{"key":"done","label":"Done"},{"key":"still","label":"Still going"},{"key":"stopped","label":"Stopped"},{"key":"didnt","label":"That didn't happen"},{"key":"remind_later","label":"Not now — ask again in 30 days"}]}"#, .options),
            (#"{"id":"1","kind":"conflict","requiredInput":"none","title":"t"}"#, .dismissOnly),
        ]
        for (json, expected) in table {
            XCTAssertEqual(FocusCardVariant.of(try item(json)), expected, json)
        }
        let legacy = try item(#"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"t"}"#)
        XCTAssertEqual(FreeTextSubmit.resolution(for: legacy, text: "  a colleague "), QuestionResolution(action: "answer", answer: "a colleague"))
        let object = try item(#"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"t","question":"Who?"}"#)
        XCTAssertEqual(FreeTextSubmit.resolution(for: object, text: "a colleague"), QuestionResolution(action: "resolve", answer: "a colleague"))
        XCTAssertNil(FreeTextSubmit.resolution(for: object, text: "   "))
    }
```

`QuestionResolution` gains `: Equatable` for these assertions, in `QuestionView.swift:6`. It is a plain value type of
optionals, so synthesis is enough.

In `InboxQuestionTests.swift:84-95`, update `testAgeCapsuleIsShort` to the compact forms: `"5d"`, `"3w"`, `"6mo"` and
`"2y"`, with `nil` and `"today"` unchanged. Add to `QuestionSelectionTests`:

```swift
    /// DR-42 — the pointer highlights too; a row out of range is ignored.
    func testThePointerMovesTheHighlight() {
        var s = QuestionSelection(optionCount: 3, allowOther: true)
        s.highlight(2)
        XCTAssertEqual(s.index, 2)
        s.highlight(3)
        XCTAssertTrue(s.isOtherRow)
        s.highlight(9)
        XCTAssertEqual(s.index, 3)
    }
```

Add to `CitedSpanTests.swift`:

```swift
    /// R-DI11 / DR-57 — a mention found by name is emphasised and never washed; `reveal` fades the wash.
    func testAMentionIsEmphasisedNotWashedAndRevealScalesTheWash() {
        let s = CitedSpan.fallback([.init(text: "found", mark: .mention), .init(text: "cited", mark: .current)], reveal: 0)
        let runs = Array(s.runs).map(\.attributes)
        XCTAssertNil(runs[0].swiftUI.backgroundColor)
        XCTAssertEqual(runs[0].inlinePresentationIntent, .stronglyEmphasized)
        XCTAssertEqual(runs[1].swiftUI.backgroundColor, CicadaTheme.wash.opacity(0), "the frame before spanReveal")
    }
```

Create `InboxFocusCardFitTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-43 / R-DI21 — every variant renders inside the focus card, and nothing in it is rigid: at the
/// question column's floor (440) and its cap (720), at 1× and 1.4×, the card never wants more width
/// than it is given (a rigid child is how the Reader's text clipped). The demo bank has no removal,
/// divergence, normalization or informational item; this is where they are reached.
@MainActor
final class InboxFocusCardFitTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private static let cause = #","cause":{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","conversationTitle":"Alpha project storage: a very long conversation title that has to truncate somewhere","excerpt":"Discussed swapping alpha-project's flat-CSV storage for sqlite-vec so anomaly lookups do not need a full scan; https://example.com/an-unbroken-url-that-is-far-longer-than-any-column-could-ever-be-at-this-size","mentionOffsets":[[10,70]],"start":0,"tier":"claim","spanKind":"asserted"}"#
    private static let options = #","options":[{"key":"a","label":"Tool Example A","description":"8 months ago · last mentioned Jan 5","ageDays":240},{"key":"b","label":"Tool Example B","description":"4 weeks ago · last mentioned Aug 25","ageDays":28,"recommended":true}]"#

    static let fixtures: [String: String] = [
        "conflict": #"{"id":"1","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use now?","allowOther":true,"allowDefer":true,"hint":"You said https://example.com/alpha-project is where to check","extractorModel":"gpt-5.4-mini","extractorConfidence":0.85"# + options + cause + "}",
        "informational": #"{"id":"1","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use?","predicate":"uses","informational":true"# + options + "}",
        "decay": #"{"id":"1","kind":"decay","requiredInput":"choice","title":"Still tracking Beta Project?","allowDefer":true,"options":[{"key":"archive","label":"Archive","description":"Last mentioned 3 months ago · move it to the archive; it comes back on the next mention"},{"key":"keep","label":"Keep active","description":"Last mentioned 3 months ago · still relevant"}]}"#,
        "legacyDecay": #"{"id":"1","kind":"decay","requiredInput":"choice","title":"No recent mentions of Beta Project"}"#,
        "freeText": #"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"Who is bob-example?","allowOther":true,"allowDefer":true}"#,
        "merge": #"{"id":"1","kind":"merge_suggestion","requiredInput":"merge","title":"Tool Example A (CLI)","entityName":"Tool Example A (CLI)","mergeTargetHint":"tool-example-a","suggestedClassification":"tool"}"#,
        "removal": #"{"id":"1","kind":"removal","requiredInput":"choice","title":"Removed from Chrome","channel":"chrome-bookmarks","options":[{"key":"keep","label":"Keep it"},{"key":"remove","label":"Archive it"}]}"#,
        "divergence": #"{"id":"1","kind":"divergence","requiredInput":"choice","title":"Keep your statement?","allowDefer":true"# + options + "}",
        "normalization": #"{"id":"1","kind":"normalization","requiredInput":"choice","title":"Was this fold right?","options":[{"key":"correct","label":"Correct fold"},{"key":"wrong","label":"Wrong fold"}]}"#,
        "followup": #"{"id":"1","kind":"followup","requiredInput":"choice","title":"t","question":"“Wire the lab cluster” — last heard 3 weeks ago. How did it go?","allowOther":true,"options":[{"key":"done","label":"Done","description":"Finished — dated today"},{"key":"still","label":"Still going"},{"key":"stopped","label":"Stopped"},{"key":"didnt","label":"That didn't happen"},{"key":"remind_later","label":"Not now — ask again in 30 days"}]}"#,
        "dismissOnly": #"{"id":"1","kind":"conflict","requiredInput":"none","title":"Nothing to pick"}"#,
    ]

    func testEveryVariantFitsItsColumnAtEveryZoomInBothThemes() throws {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [1.0, 1.4] {
                CicadaTheme.uiScale = scale
                for width: CGFloat in [440, 720] {
                    let proposed = width * CGFloat(scale)
                    for (name, json) in Self.fixtures {
                        let item = try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
                        let renderer = ImageRenderer(content: InboxFocusCard(item: item, padding: 28, onClose: {}) { _ in })
                        renderer.proposedSize = ProposedViewSize(width: proposed, height: nil)
                        let size = try XCTUnwrap(renderer.nsImage, name).size
                        XCTAssertLessThanOrEqual(size.width, proposed + 0.5, "\(name) at \(width) × \(scale) wants \(size.width)")
                        XCTAssertGreaterThan(size.height, 80, "\(name) rendered nothing")
                    }
                }
            }
        }
    }
}
```

The `+ options + cause + "}"` joins build valid JSON because `options` and `cause` each begin with a comma. A typo
fails the `JSONDecoder` call with the fixture's name in the thrown error.

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'InboxPresentationTests|InboxQuestionTests|QuestionSelectionTests|CitedSpanTests|InboxFocusCardFitTests' 2>&1 | tail -20`.
It fails to compile. That is the red.

- [ ] **Step 2: The pure presentation** (append to `Models/InboxPresentation.swift`). This adds `InboxAge.compact`,
  `InboxRowAge`, `InboxSourceLine`, `ExcerptText.clean`, `QuoteSegments`, `InboxGuess`, `HintLink`, `FreeTextSubmit`,
  `FocusCardVariant` and `MergeDirection`:

```swift
extension InboxAge {
    /// DR-58 / R-DI12 — an age for a row or an option tag: "today", "5d", "3w", "6mo", "2y". The
    /// same branch boundaries and half-even rounding as `phrase(days:)`, so "3w" beside "3 weeks ago"
    /// on the same card never disagree.
    static func compact(days: Int) -> String {
        if days <= 0 { return "today" }
        if days < 14 { return "\(days)d" }
        if days < 60 { return "\(Int((Double(days) / 7).rounded(.toNearestOrEven)))w" }
        if days < 365 { return "\(Int((Double(days) / 30).rounded(.toNearestOrEven)))mo" }
        return "\(Int((Double(days) / 365).rounded(.toNearestOrEven)))y"
    }
}

/// DR-58 — a row's age: compact, measured from the conversation that raised it, with the absolute
/// day in `.help`. A question with no source keeps G125's "—", and its reason (DR-55).
enum InboxRowAge {
    static func of(_ item: InboxItem, now: Date, locale: Locale = .autoupdatingCurrent,
                   timeZone: TimeZone = .autoupdatingCurrent) -> (text: String, help: String) {
        guard item.hasCause, let cause = item.cause,
              let then = cause.timestamp.flatMap({ ReaderTime.instant($0, timeZone: timeZone) })
                ?? cause.episodeId.flatMap({ ReaderTime.episodeDate($0, timeZone: timeZone) }) else {
            return ("—", Copy.Inbox.noSourceAge)
        }
        let days = max(0, Int(now.timeIntervalSince(then) / 86_400))
        let day = ReaderTime.day(timestamp: cause.timestamp, episode: cause.episodeId ?? "",
                                 locale: locale, timeZone: timeZone) ?? ""
        return (InboxAge.compact(days: days), day)
    }
}

/// DR-54 / R-DI12 — a source named the way a person would: the app, the conversation's title, the
/// day. Ids and slugs never reach body weight; the episode id lives in `.help` only. Replaces
/// `causeLine()`, which printed the raw harness slug.
enum InboxSourceLine {
    /// G115 / DR-55 — served exactly as written, never louder than a real source line.
    static let noSource = "[ no source recorded ]"

    static func app(_ cause: InboxCause) -> String? {
        if let agent = EvidenceSpeaker.agentName(harness: cause.harness, origin: cause.origin) { return agent }
        guard let origin = cause.origin?.trimmingCharacters(in: .whitespaces), !origin.isEmpty,
              origin != "unknown", origin != "mcp" else { return nil }
        return OriginIconography.label(for: origin)
    }

    /// The origin whose real mark sits beside the line (DR-52) — the same precedence as `app`.
    static func markOrigin(_ item: InboxItem) -> String? {
        guard item.hasCause, let cause = item.cause else { return nil }
        if let agent = EvidenceSpeaker.agentOrigin(harness: cause.harness, origin: cause.origin) { return agent }
        guard let origin = cause.origin, !origin.isEmpty, origin != "unknown", origin != "mcp" else { return nil }
        return origin
    }

    private static func day(_ cause: InboxCause, _ locale: Locale, _ timeZone: TimeZone) -> String? {
        ReaderTime.day(timestamp: cause.timestamp, episode: cause.episodeId ?? "", locale: locale,
                       timeZone: timeZone, withYear: false)
    }

    private static func title(_ cause: InboxCause) -> String? {
        let t = cause.conversationTitle?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? nil : t
    }

    /// The card's line: "Claude Code · Index choice · Aug 25" / "a Claude Code conversation · Aug 25".
    static func full(_ item: InboxItem, locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> String {
        guard item.hasCause, let cause = item.cause else { return noSource }
        var parts: [String] = []
        if let title = title(cause) {
            if let app = app(cause) { parts.append(app) }
            parts.append(title)
        } else {
            parts.append(app(cause).map(Copy.Inbox.aConversation) ?? Copy.Inbox.aConversationPlain)
        }
        if let d = day(cause, locale, timeZone) { parts.append(d) }
        return parts.joined(separator: " · ")
    }

    /// The row's slot (§5.3): "Claude Code · Aug 25" — the title is the card's to say.
    static func row(_ item: InboxItem, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent) -> String {
        guard item.hasCause, let cause = item.cause else { return noSource }
        var parts = [app(cause) ?? title(cause) ?? Copy.Inbox.aConversationPlain]
        if let d = day(cause, locale, timeZone) { parts.append(d) }
        return parts.joined(separator: " · ")
    }

    /// DR-54 — the id, reachable only through `.help` ("Episode ep_…").
    static func help(_ item: InboxItem) -> String? {
        guard item.hasCause, let ep = item.cause?.episodeId, !ep.isEmpty else { return nil }
        return "Episode \(ep)"
    }
}

extension ExcerptText {
    /// DR-56 / R-DI22 — clean text for a quote: heading hashes, bullets and quote markers at a line's
    /// start go, `[[a|b]]` reads "b", `[[slug-name]]` reads "Slug Name", and every whitespace run is
    /// one space. It runs on each segment AFTER the split, so the mention's scalar offsets never
    /// move, and it never trims a segment's edges — that would glue "Discussed" to "swapping".
    /// `atLineStart: false` is for a segment that begins mid-line (the span, the text after it): its
    /// first line is not a line start, so a "- " there is a minus, not a bullet. A link the mention
    /// split in two leaves a stray `[[`, `[[target|` or `]]` at a segment's edge; those go too.
    static func clean(_ text: String, atLineStart: Bool = true) -> String {
        let linePrefix = try? NSRegularExpression(pattern: #"^\s*(?:#{1,6}\s+|[-*+]\s+|>\s?|\d+\.\s+)"#)
        let lines = text.components(separatedBy: "\n").enumerated().map { index, line -> String in
            guard let linePrefix, index > 0 || atLineStart else { return line }
            let ns = line as NSString
            return linePrefix.stringByReplacingMatches(in: line, range: NSRange(location: 0, length: ns.length),
                                                       withTemplate: "")
        }
        var joined = lines.joined(separator: " ")
        if let link = try? NSRegularExpression(pattern: #"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]"#) {
            let ns = joined as NSString
            var out = ""
            var last = 0
            for m in link.matches(in: joined, range: NSRange(location: 0, length: ns.length)) {
                out += ns.substring(with: NSRange(location: last, length: m.range.location - last))
                if m.range(at: 2).location != NSNotFound {
                    out += ns.substring(with: m.range(at: 2)).trimmingCharacters(in: .whitespaces)
                } else {
                    out += humanised(ns.substring(with: m.range(at: 1)).trimmingCharacters(in: .whitespaces))
                }
                last = m.range.location + m.range.length
            }
            out += ns.substring(from: last)
            joined = out
        }
        joined = joined.replacingOccurrences(of: #"\[\[(?:[^\[\]|]*\|)?|\]\]"#, with: "", options: .regularExpression)
        return joined.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
    }

    /// A slug reads as its page's name ("alpha-project-notes" → "Alpha Project Notes").
    private static func humanised(_ name: String) -> String {
        guard name.range(of: #"^[a-z0-9]+(?:-[a-z0-9]+)+$"#, options: .regularExpression) != nil else { return name }
        return name.split(separator: "-").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
    }
}

/// §5.3 item 3 / R-DI11 — the focus card's quote: the cause excerpt split at its first mention,
/// each piece cleaned (DR-56). An asserted G118 span is washed and underlined (DR-18); a mention
/// found by name is semibold and unwashed (DR-57, G118 §4.9) — the words were found, not quoted.
enum QuoteSegments {
    static func of(_ item: InboxItem) -> [CitedSpan.Segment]? {
        guard item.hasCause, let cause = item.cause, !cause.excerpt.isEmpty else { return nil }
        let parts = QuoteBlock.parts(excerpt: cause.excerpt, mentionOffsets: cause.mentionOffsets)
        let mark: CitedSpan.Mark = cause.spanKind == "asserted" ? .current : .mention
        let pieces: [(String, CitedSpan.Mark)] = [(parts.before, .plain), (parts.span, mark), (parts.after, .plain)]
        // Only `before` opens on a real line start; the span and the rest begin mid-line (R-DI22).
        let segments = pieces.enumerated()
            .map { i, piece in CitedSpan.Segment(text: ExcerptText.clean(piece.0, atLineStart: i == 0), mark: piece.1) }
            .filter { !$0.text.isEmpty }
        return segments.isEmpty ? nil : segments
    }

    /// Whether the card says "Found by searching the conversation" under the quote.
    static func isDerived(_ item: InboxItem) -> Bool {
        guard item.hasCause, let cause = item.cause else { return false }
        return cause.spanKind != "asserted" && !cause.mentionOffsets.isEmpty
    }
}

/// G115 §7 — the extractor's side of the question, stated before the person answers. Never on an
/// informational card: there is nothing to grade (the mock's `hasGuess && !vInfo`).
enum InboxGuess {
    static func text(_ item: InboxItem) -> String? {
        guard !item.informational,
              let model = item.extractorModel ?? (item.extractorConfidence.map { _ in "Cicada" }) else { return nil }
        return item.extractorConfidence.map { String(format: "%@'s guess at %.2f", model, $0) } ?? "\(model)'s guess"
    }
}

/// G61 — the hint's "Open source ↗" target: its first URL, or nothing to open.
enum HintLink {
    static func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
        return detector.firstMatch(in: text, range: NSRange(text.startIndex..., in: text))?.url
    }
}

/// A typed answer, in the wire shape each item was built for: a G60 question object answers through
/// `resolve` (the backend closes every option claim and records the person's words; a clarification
/// takes `resolve` as an alias of `answer`); a legacy clarification through `answer`. Both shapes
/// shipped before DS-2 (the Other… field and the legacy Answer row), and both keep working.
enum FreeTextSubmit {
    static func resolution(for item: InboxItem, text: String) -> QuestionResolution? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        if item.question != nil || !item.options.isEmpty {
            return QuestionResolution(action: "resolve", answer: t,
                                      optionKey: item.options.contains { $0.key == "neither" } ? "neither" : nil)
        }
        return QuestionResolution(action: "answer", answer: t)
    }
}

/// DR-43 / R-DI15 — which body the focus card draws. Order matters: G98's informational flag
/// outranks the options it lists; options outrank the legacy shapes they replaced.
enum FocusCardVariant: Equatable {
    case informational, options, merge, legacyDecay, freeText, dismissOnly

    static func of(_ item: InboxItem) -> FocusCardVariant {
        if item.informational { return .informational }
        if !item.options.isEmpty { return .options }
        if item.kind == .mergeSuggestion || item.requiredInput == .merge { return .merge }
        if item.kind == .decay { return .legacyDecay }
        if item.allowOther || item.requiredInput == .freetext || item.question != nil { return .freeText }
        return .dismissOnly
    }
}

/// The merge's direction in words: "Tool Example A (CLI) → tool-example-a".
enum MergeDirection {
    static func line(survivorIsMention: Bool, mention: String, existing: String) -> String? {
        let (from, to) = survivorIsMention ? (existing, mention) : (mention, existing)
        guard !from.isEmpty, !to.isEmpty else { return nil }
        return "\(from) → \(to)"
    }
}
```

Add to `Copy.Inbox`:

```swift
        static func aConversation(_ app: String) -> String { "a \(app) conversation" }
        static let aConversationPlain = "a conversation"
        static let noSourceAge = "No source recorded, so no date to measure from"
        static let recommended = "Recommended"
        static let other = "Other…"
        static let otherPrompt = "What's actually true?"
        static let answerPrompt = "Type your answer…"
        static let submit = "Submit"
        /// DR-41 — a disabled control says why in `.help`.
        static let submitNeedsText = "Type what's actually true first"
        static let answerNeedsText = "Type an answer first"
        static let mergeNeedsTarget = "Name the existing entity first"
        static func pressKey(_ n: Int) -> String { "Press \(n)" }
        static let notNowSevenDays = "Not now — ask again in 7 days"
        static let notNowHelp = "Ask again in 7 days (L)"
        static let close = "Close (Esc)"
        static let showConversationHelp = "Open the conversation beside this question"
        static let hideConversation = "Hide conversation"
        static let hideConversationHelp = "Close the conversation (Esc)"
        static let openSource = "Open source"
        static func openSourceHelp(_ where: String) -> String { "Open \(`where`)" }
        static func informational(_ predicate: String?) -> String {
            "These can all be true — \(predicate ?? "this") holds several values. Nothing to pick."
        }
        static let describeEntity = "Describe this entity"
        static let describePrompt = "Describe this entity…"
        static let existingEntity = "Existing entity"
        static let existingPrompt = "Existing entity…"
        static let keepAsCanonical = "Keep as canonical"
        static let newFromExtraction = "New from extraction"
        static let existingPage = "Existing page"
        static let answer = "Answer"
        static let merge = "Merge"
        static let keepSeparate = "Keep separate"
        static let skip = "Skip"
        static let dismiss = "Dismiss"
        static let keepActive = "Keep active"
        static let archive = "Archive"
        static func questions(_ n: Int) -> String { n == 1 ? "‹ 1 question" : "‹ \(UsageFormat.count(n)) questions" }
        static let showQuestions = "Show the questions"
        static let showFewer = "Show fewer"
        static func showAll(_ n: Int) -> String { "Show all \(UsageFormat.count(n))" }
        static let openQuestion = "Open this question"
```

In `InboxItem.swift`, apply two edits:
- `ageCapsule` becomes `ageDays.map(InboxAge.compact(days:))`, with its doc comment updated to R-DI12.
- `icon` changes `conflict: "exclamationmark.triangle"` and `clarification: "questionmark.circle"` (R-DI18, DR-53
  outline variants).

In `QuestionSelection.swift`, add:

```swift
    /// DR-42 — the pointer highlights too: hovering row `i` moves the ⏎ target there. The Other row
    /// is `optionCount`; anything out of range is ignored.
    mutating func highlight(_ i: Int) {
        guard i >= 0, i < rowCount else { return }
        index = i
    }
```

- [ ] **Step 3: `CitedSpan` learns the derived mention and the reveal.** In `CitedSpan.swift`:
  - `enum Mark { case plain, current, other, mention }`.
  - `fallback(_ segments:, reveal: Double = 1)`: `.current` sets the wash to `CicadaTheme.wash.opacity(reveal)` and the
    underline colour to `CicadaTheme.accent.opacity(reveal)`. `.other` sets `CicadaTheme.washSoft.opacity(reveal)`.
    `.mention` sets `piece.inlinePresentationIntent = .stronglyEmphasized` and no fill.
  - `text(_:)`: `.mention` becomes `text + Text(segment.text).fontWeight(.semibold)`.
  - `CitedSpanRenderer` gains `var reveal: Double = 1` and
    `var animatableData: Double { get { reveal } set { reveal = newValue } }`. It fills with
    `(tag.current ? wash : washSoft).opacity(reveal)` and the underline with `underline.opacity(reveal)`, so
    `spanReveal` fades the wash in (DR-61) instead of popping it.
  - `citedSpans(reveal: Double = 1)` passes it through.
  - Every existing call site compiles unchanged, because the parameter defaults to 1.

The doc comment gains one paragraph: "`.mention` — a match found by name (G118 §4.9, DR-57): semibold, never washed; the
wash and the underline are for words someone quoted (R-DI11)."

- [ ] **Step 4: The card's pieces.** `OptionRow.swift`:

```swift
import SwiftUI

/// DR-42 — one answer, one tap: a radio (1.5 pt `textTertiary` ring, a 6 pt accent dot when
/// highlighted), the label (14 medium), its description (12 `textTertiary` — the server's words, age
/// first, G60), "Recommended" (`accentText`, `textPrimary` on the hover fill, DR-6), the age as a
/// `Tag`, ⏎ on the highlighted row and the row's number (DR-49). At rest `bgOption` with a resting
/// ring; hover one step up; highlighted a 1.5 pt accent ring (DR-5 use 3). A click answers at once.
struct OptionRow: View {
    let option: InboxOption
    /// 1…9; nil past the ninth row.
    let number: Int?
    let highlighted: Bool
    let onHover: () -> Void
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static var hoverFill: Color { CicadaTheme.mode == .dark ? CicadaTheme.bgButton : CicadaTheme.bgHover }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingMD) {
                RadioMark(on: highlighted)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(1)) {
                    Text(option.label)
                        .font(CicadaTheme.font(size: 14, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let description = option.description, !description.isEmpty {
                        Text(description)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if option.recommended {
                    Text(Copy.Inbox.recommended)
                        .font(CicadaTheme.metaMediumFont)
                        .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.accentText)
                }
                if let age = option.ageCapsule { Tag(text: age) }
                if highlighted { KeyHint("⏎") }
                if let number { KeyHint(String(number)) }
            }
            .padding(.leading, CicadaTheme.scaled(14))
            .padding(.trailing, CicadaTheme.scaled(12))
            .frame(height: CicadaTheme.scaled(RowMetrics.option))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? Self.hoverFill : CicadaTheme.bgOption))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(highlighted ? CicadaTheme.accent : CicadaTheme.ring(.resting), lineWidth: highlighted ? 1.5 : 1))
        }
        .buttonStyle(.cicadaPlain)
        .help(option.description ?? option.label)
        .onHover { hovering = $0; if $0 { onHover() } }
        .accessibilityLabel(option.recommended ? "\(option.label), \(Copy.Inbox.recommended.lowercased())" : option.label)
        .accessibilityHint(number.map(Copy.Inbox.pressKey) ?? "")
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// The option row's radio (DR-42): drawn, so the ring is exactly 1.5 pt at every zoom.
struct RadioMark: View {
    let on: Bool
    var body: some View {
        Circle()
            .strokeBorder(on ? CicadaTheme.accent : CicadaTheme.textTertiary, lineWidth: 1.5)
            .frame(width: CicadaTheme.scaled(16), height: CicadaTheme.scaled(16))
            .overlay {
                if on {
                    Circle().fill(CicadaTheme.accent)
                        .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
                }
            }
            .accessibilityHidden(true)
    }
}

/// DR-8 / DR-3 / R-DI18 — a kind's hue appears once, as this outline glyph, which carries the kind's
/// name for the pointer and VoiceOver (light merge measures 2.98:1 and never stands alone).
struct KindGlyph: View {
    let kind: InboxKind
    var body: some View {
        Image(systemName: kind.icon)
            .font(CicadaTheme.icon(.list))
            .foregroundStyle(kind.color)
            .help(kind.label)
            .accessibilityLabel(kind.label)
    }
}
```

`FocusCardVariants.swift` holds the bodies that are not option rows. There are five internal (not `private`) structs,
each taking `onAnswer`, plus the item and the card's focus binding where it reads them (the exact initialisers are the
ones `variantBody` calls in Step 5):

- **`InformationalBody`** (DR-43, G98):
  - `Text(Copy.Inbox.informational(item.predicate))` in `detailBodyFont`, `textSecondary`;
  - then one 36 pt `bgOption` row per option: a `checkmark.circle` glyph in `textTertiary`, the label in 14 medium, and
    a `Tag(age)`;
  - then a trailing `NeutralButton(title: Copy.Inbox.gotIt)` → `QuestionResolution(action: "dismiss")`.
- **`FreeTextBody`**, R-DI15:
  - an `InboxTextField(prompt: Copy.Inbox.answerPrompt, text:, isFocused: field == .answer)` (Step 5). DR-9 allows real
    borders on text inputs.
  - `.focused(fieldBinding, equals: .answer)` and `.onSubmit` → `FreeTextSubmit.resolution`;
  - beside it `NeutralButton(title: Copy.Inbox.submit, keyHint: "⏎", isDisabled: text.trimmed.isEmpty, disabledHelp: Copy.Inbox.answerNeedsText)`;
  - under it, **only when `item.question == nil`** (the legacy shape), a row of
    `TextButton(title: Copy.Inbox.dismiss)` → `dismiss` and `TextButton(title: Copy.Inbox.skip)` → `skip`.
- **`MergeBody`**, the port of `InboxCardView.swift:355-497`:
  - two labelled fields in a two-column `Grid`: `Copy.Inbox.describeEntity` → `answerText`, and
    `Copy.Inbox.existingEntity` → `mergeText`, seeded from `mergeTargetHint` on appear;
  - `SectionLabel("Keep as canonical")`, then two 48 pt survivor rows with `RadioMark`, name and note. The notes are
    `[Copy.Inbox.newFromExtraction, suggestedClassification].compactMap { $0 }.joined(separator: " · ")` and
    `Copy.Inbox.existingPage` (composed outside `Text(` so `CountLiteralLintTests` stays quiet, R-DI23);
  - the `MergeDirection.line` in meta;
  - then a row: `TextButton(title: Copy.Inbox.skip)` → `skip`, a `Spacer`, and three neutral buttons:
    - `NeutralButton(title: Copy.Inbox.answer, isDisabled: answerText.trimmed.isEmpty, disabledHelp: Copy.Inbox.answerNeedsText)`
      → `QuestionResolution(action: "answer", answer: answerText.trimmed)`;
    - `NeutralButton(title: Copy.Inbox.keepSeparate, isDisabled: MergeReject.resolution(existingName: existingName) == nil, disabledHelp: Copy.Inbox.mergeNeedsTarget)`
      → that resolution, where `existingName` is today's rule (`mergeText` trimmed, else `mergeTargetHint`);
    - `NeutralButton(title: Copy.Inbox.merge, isDisabled: mergeText.trimmed.isEmpty, disabledHelp: Copy.Inbox.mergeNeedsTarget)` → `merge`
      with `mergeTarget` + `mergeSurvivor` exactly as `InboxCardView.swift:384-391`.
- **`LegacyDecayBody`**: one row of three neutral buttons, `Keep active` → `keep_active`, `Archive` → `archive` and
  `Not now` → `defer` 7 (DR-43 "one row of neutral buttons").
- **`DismissBody`**: `NeutralButton(title: Copy.Inbox.dismiss)` → `dismiss`.

The merge body's field focus uses the same `Field` enum as the card. Every field reports focus through
`onEditingChange` (R-DI4).

- [ ] **Step 5: `InboxFocusCard.swift`.** The card, in the order §5.3 lists. It is one `VStack(alignment: .leading, spacing: 0)`
  inside `bgFocus`, `radiusLarge`, `ringed(in:)`, with `padding` and `.frame(maxWidth: scaled(ColumnLayout.questionMaxWidth))`.
  There is no glass and no shadow (DR-10, DR-14).

```swift
import AppKit
import SwiftUI

/// §5.3 STATE 1 — C's focus card (DR-42, DR-43): the header, the question stated once, the quote
/// hero, where it came from in a person's words, the extractor's guess, the answers, the hint and
/// Not now. Every kind renders here (`FocusCardVariant`, R-DI15). It never sends anything: an
/// answer goes to `onAnswer`, and the Store holds it for its Undo window (R-DI2). The page keys it
/// by `item.id`, so a swap is a fresh card whose seeded state never animates on mount (DR-65).
struct InboxFocusCard: View {
    let item: InboxItem
    let padding: CGFloat
    /// Close × (STATE 1 → 0). nil where there is no column to close — the Sources page (R-DI16).
    var onClose: (() -> Void)? = nil
    /// DR-27 — "‹ N questions", only while the list is hidden.
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    /// DR-28 — Esc with nothing open inside the card belongs to the page.
    var onEscape: () -> Void = {}
    /// R-DI4 — while a field here has focus, ⌘Z is the field's own.
    var onEditingChange: (Bool) -> Void = { _ in }
    let onAnswer: (QuestionResolution) -> Void

    enum Field: Hashable { case other, answer, merge }

    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @State private var selection: QuestionSelection
    @State private var otherText = ""
    @State private var showAllLines = false
    @FocusState private var field: Field?

    init(item: InboxItem, padding: CGFloat, onClose: (() -> Void)? = nil, hiddenListCount: Int? = nil,
         onShowList: @escaping () -> Void = {}, onEscape: @escaping () -> Void = {},
         onEditingChange: @escaping (Bool) -> Void = { _ in },
         onAnswer: @escaping (QuestionResolution) -> Void) {
        self.item = item
        self.padding = padding
        self.onClose = onClose
        self.hiddenListCount = hiddenListCount
        self.onShowList = onShowList
        self.onEscape = onEscape
        self.onEditingChange = onEditingChange
        self.onAnswer = onAnswer
        // G115 R6 — the first highlight is Sleep's own proposal; a conflict with none starts on row 1.
        _selection = State(initialValue: QuestionSelection(optionCount: item.options.count,
                                                           allowOther: item.allowOther,
                                                           initialIndex: item.recommendedIndex))
    }

    private var variant: FocusCardVariant { FocusCardVariant.of(item) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Text(item.questionText)
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            quote
            sourceLine
            if let guess = InboxGuess.text(item) {
                Label(guess, systemImage: "sparkles")
                    .labelStyle(.titleAndIcon)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.top, CicadaTheme.spacingXS)
            }
            variantBody.padding(.top, CicadaTheme.scaled(20))
            hintRow
            if item.allowDefer, variant != .informational, variant != .legacyDecay {
                TextButton(title: Copy.Inbox.notNowSevenDays, keyHint: "L", help: Copy.Inbox.notNowHelp) {
                    onAnswer(QuestionResolution(action: "defer", remindDays: 7))
                }
                .padding(.top, CicadaTheme.scaled(20))
                .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
        .padding(padding)
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth), alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .focusable()
        .focusEffectDisabled()
        .onChange(of: field) { _, now in onEditingChange(now != nil) }
        .onMoveCommand { direction in
            guard variant == .options, field == nil else { return }
            switch direction {
            case .down: selection.moveDown()
            case .up: selection.moveUp()
            default: break
            }
        }
        .onKeyPress(.return) {
            guard variant == .options, field == nil, let action = selection.activate() else { return .ignored }
            switch action {
            case .pick(let i): pick(i)
            case .openOther: field = .other
            default: break
            }
            return .handled
        }
        .onKeyPress(KeyEquivalent("o")) {
            guard field == nil else { return .ignored }
            switch variant {
            case .options where item.allowOther: selection.openOther(); field = .other
            case .freeText: field = .answer
            default: return .ignored
            }
            return .handled
        }
        .onKeyPress(KeyEquivalent("l")) {
            // DR-49 — a key acts only where its pointer twin is on the card: an informational card
            // shows no Not now, so L does nothing there either.
            guard field == nil, item.allowDefer, variant != .informational else { return .ignored }
            onAnswer(QuestionResolution(action: "defer", remindDays: 7))
            return .handled
        }
        .onKeyPress(characters: .decimalDigits) { press in
            guard variant == .options, field == nil, let n = Int(press.characters),
                  case .pick(let i)? = selection.pickNumber(n) else { return .ignored }
            pick(i)
            return .handled
        }
        // DR-28 — an open Other… closes in ONE press (the field loses focus and the row folds; the
        // pre-DS-2 lesson in `QuestionView`: closing only the field left a second Esc doing nothing),
        // then another focused field, then the page's own Esc (the Reader, then the question). A
        // keyboard action never animates (DR-60): the page's Esc is `Instant.run`.
        .onKeyPress(.escape) {
            if selection.otherExpanded {
                field = nil
                _ = selection.escape()
                return .handled
            }
            if field != nil { field = nil; return .handled }
            onEscape()
            return .handled
        }
    }

    // MARK: Header — the kind glyph, the entity, Close × (and "‹ N questions" when the list hides)

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let n = hiddenListCount {
                TextButton(title: Copy.Inbox.questions(n), help: Copy.Inbox.showQuestions, action: onShowList)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
            KindGlyph(kind: item.kind)
            Text(item.displayName)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let onClose {
                IconButton(systemName: "xmark", help: Copy.Inbox.close, action: onClose)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(28))
        .padding(.bottom, CicadaTheme.spacingSM)
    }

    // MARK: The quote hero (DR-18, R-DI11, R-DI22)

    @ViewBuilder
    private var quote: some View {
        if let segments = QuoteSegments.of(item) {
            CitedSpan.text(segments)
                .font(CicadaTheme.quoteFont)
                .lineSpacing(CicadaTheme.quoteLineSpacing)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .citedSpans()
                .quoteBlock()
                .padding(.top, CicadaTheme.scaled(20))
            if QuoteSegments.isDerived(item) {
                Text(Copy.Provenance.derivedCaption)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.top, CicadaTheme.spacingXS)
            }
        } else if !item.hasCause, !item.body.isEmpty {
            // Owner defect 2 (2026-09-03) survives: a long legacy body shows three lines and "Show all N".
            // Cleaned line by line: `clean` joins lines with a space, which would fold the three kept
            // lines back into the one run-on paragraph the collapse exists to prevent.
            let collapsed = CollapsedLines(item.body)
            Text((showAllLines ? collapsed.lines : collapsed.head).map { ExcerptText.clean($0) }.joined(separator: "\n"))
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .quoteBlock()
                .padding(.top, CicadaTheme.scaled(20))
            if collapsed.needsCollapse {
                TextButton(title: showAllLines ? Copy.Inbox.showFewer : Copy.Inbox.showAll(collapsed.lines.count)) {
                    showAllLines.toggle()
                }
                .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
    }

    // MARK: The source line (DR-54) and "Show in conversation ›"

    private var sourceLine: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let origin = InboxSourceLine.markOrigin(item) {
                OriginMark(origin: origin, size: CicadaTheme.scaled(14)).markHover()
            }
            Text(InboxSourceLine.full(item))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let provenance,
               let target = item.cause?.readerTarget(subjectId: item.entityId.isEmpty ? nil : item.entityId) {
                let showing = provenance.isPresented && provenance.current?.episode == target.episode
                Button { showing ? provenance.close() : provenance.open(target) } label: {
                    HStack(spacing: CicadaTheme.scaled(3)) {
                        Text(showing ? Copy.Inbox.hideConversation : Copy.Provenance.showInConversation)
                        Image(systemName: showing ? "chevron.left" : "chevron.right").font(CicadaTheme.icon(.inline))
                    }
                }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.accentText)
                .help(showing ? Copy.Inbox.hideConversationHelp : Copy.Inbox.showConversationHelp)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(22))
        .help(InboxSourceLine.help(item) ?? "")
        .padding(.top, CicadaTheme.scaled(QuoteSegments.of(item) == nil ? 10 : 12))
    }

    // MARK: The answers

    @ViewBuilder
    private var variantBody: some View {
        switch variant {
        case .options: optionsBody
        case .informational: InformationalBody(item: item, onAnswer: onAnswer)
        case .freeText: FreeTextBody(item: item, field: $field, onAnswer: onAnswer)
        case .merge: MergeBody(item: item, field: $field, onAnswer: onAnswer)
        case .legacyDecay: LegacyDecayBody(onAnswer: onAnswer)
        case .dismissOnly: DismissBody(onAnswer: onAnswer)
        }
    }

    private var optionsBody: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.optionGap)) {
            ForEach(Array(item.options.enumerated()), id: \.element.id) { pair in
                OptionRow(option: pair.element, number: pair.offset < 9 ? pair.offset + 1 : nil,
                          highlighted: !selection.otherExpanded && selection.index == pair.offset,
                          onHover: { selection.highlight(pair.offset) }) { pick(pair.offset) }
            }
            if item.allowOther {
                OtherRow(expanded: selection.otherExpanded,
                         highlighted: selection.isOtherRow) {
                    selection.openOther()
                    field = .other
                }
                if selection.otherExpanded {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        InboxTextField(prompt: Copy.Inbox.otherPrompt, text: $otherText, isFocused: field == .other)
                            .focused($field, equals: .other)
                            .onSubmit(submitOther)
                        NeutralButton(title: Copy.Inbox.submit, keyHint: "⏎",
                                      isDisabled: otherText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                                      disabledHelp: Copy.Inbox.submitNeedsText, action: submitOther)
                    }
                    .padding(.top, CicadaTheme.spacingXS)
                }
            }
        }
    }

    // MARK: The hint (G61) — "Open source ↗"; no check line until G61 S3 serves one (R-DI13)

    @ViewBuilder
    private var hintRow: some View {
        if let hint = item.hint, !hint.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(6)) {
                Image(systemName: "link").font(CicadaTheme.icon(.inline))
                Text(hint).lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                if let url = HintLink.firstURL(in: hint) {
                    Button { NSWorkspace.shared.open(url) } label: {
                        HStack(spacing: CicadaTheme.scaled(3)) {
                            Text(Copy.Inbox.openSource)
                            Image(systemName: "arrow.up.right").font(CicadaTheme.icon(.inline))
                        }
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.accentText)
                    .help(Copy.Inbox.openSourceHelp(url.host ?? url.absoluteString))
                }
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.top, CicadaTheme.scaled(20))
        }
    }

    // MARK: Actions

    private func pick(_ i: Int) {
        guard item.options.indices.contains(i) else { return }
        onAnswer(QuestionResolution(action: "resolve", optionKey: item.options[i].key))
    }

    private func submitOther() {
        guard let r = FreeTextSubmit.resolution(for: item, text: otherText) else { return }
        onAnswer(r)
    }
}
```

In the same file, define the two helpers the card uses:
- **`OtherRow`** has `OptionRow`'s anatomy: a pencil glyph in place of the radio, "Other…" in 14 medium `textSecondary`,
  and `KeyHint("O")`. At rest it is `bgOption` + ring. When expanded or highlighted it gets the 1.5 pt accent ring. A
  click opens the field.
- **`InboxTextField(prompt:text:isFocused:)`** is a 32 pt `TextField` (`.textFieldStyle(.plain)`) in `detailBodyFont`,
  with a `bgBase` fill and an input border, `ring(.input)` stroking `shape(cornerRadiusSmall)`, that becomes the accent
  at 70 % while `isFocused` (DR-5 use 1, the focus ring). The caller owns focus: it applies `.focused(_:equals:)` to the
  field and passes `isFocused` from the same `@FocusState`, so one field never carries two focus bindings.

`MergeBody` and `FreeTextBody` use `InboxTextField` too, alongside the card's Other… field.

- [ ] **Step 6: Green.**
  - Run the Step 1 filter, `swift build`, then the full `swift test`. There are 0 failures.
  - `swift test --filter FontLiteralLintTests` passes: the card's `displayFont(size: 22)` carries its tracking.
  - `swift test --filter MotionLiteralLintTests` passes.
- [ ] **Step 7: Commit.** Stage named files only. Message:
  `feat(ds2, g115): the focus card — every kind, one-tap option rows, the quote hero in CitedSpan, the source in a person's words (DR-16, DR-17, DR-18, DR-42, DR-43, DR-44, DR-49, DR-52, DR-53, DR-54, DR-55, DR-56, DR-57, DR-58)`.

---

### Task 4: The Reader is a column, and never pushed off-window (DR-31, DR-32, DR-18, DR-16, DR-61; G118 slice 2; R-DI6, R-DI9, R-DI11, R-DI20)

The Reader becomes one view with C's styling, hosted by the shell as a trailing column on every page. That includes the
Inbox until Task 5 gives it a column of its own. `.inspector` retires, and with it the clipped-text bug.

**Files:**
- Move: `git mv app/…/Views/Provenance/ReaderInspector.swift app/…/Views/Provenance/ReaderColumn.swift`, then rewrite
  its views.
- Modify:
  - `app/…/Views/Provenance/ProvenanceRouter.swift`: `refocus`;
  - `app/…/Views/Provenance/QuoteBlock.swift:48-57`: the accent wash;
  - `app/…/Views/Provenance/ReaderModel.swift`: `ReaderText.segments`;
  - `app/…/ContentView.swift:193-205`: the host;
  - `app/…/Theme/Copy+Provenance.swift`.
- Test: `ReaderColumnLayoutTests.swift` (new), `ReaderTurnsTests.swift`, `ProvenanceRouterTests.swift`,
  `ThemeContrastTests.swift`.

**Interfaces:**
- Produces:
  - `ReaderColumn()` (environment-driven, as `ReaderInspector` was);
  - `ReaderColumnHeader`, `ReaderTurnsView(blocks:landingTurn:revealed:)`, `ReaderTurnView`, `ReaderNotedList`,
    `ReaderBannerView`;
  - `ReaderText.segments(_:)`;
  - `ShellReaderHost(showsReader:navWidth:page:reader:)`;
  - `ProvenanceRouter.refocus(_:)`.
- Consumes: Task 1's `ColumnLayout`, `CicadaMotion.readerIn/Out`, `Instant`, `NeutralButton`, `IconButton`, `SectionLabel`,
  and Task 3's `CitedSpan.Mark.mention` / `reveal`.

- [ ] **Step 1: Failing tests.** Create `ReaderColumnLayoutTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// R-DI6 / DR-31 — the Reader is never pushed off-window and never wants more than its column. The
/// clipped-text bug had two possible roots — a rigid child inside the Reader, or a page beside it
/// that would not give way — and both are measured here.
@MainActor
final class ReaderColumnLayoutTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    /// A conversation built to break a layout: an unbroken 300-character token, a long speaker
    /// line, a stale banner's worth of words, a cited span that runs across the token.
    private func hostileBlocks() -> [ReaderBlock] {
        let token = "https://example.com/" + String(repeating: "x", count: 300)
        let text = "user: can we stop? \(token)\nassistant: Yes. We moved the index to sqlite-vec for alpha-project."
        let doc = EpisodeText(episode: "ep_2026-09-03_004", text: text, title: String(repeating: "Long title ", count: 12),
                              timestamp: "2026-09-03T10:00:00+00:00", harness: "claude-code", origin: "claude-code",
                              turns: [EpisodeTurn(index: 1, start: 0, contentStart: 6, end: 19 + token.count, role: "user", marker: "user"),
                                      EpisodeTurn(index: 2, start: 20 + token.count, contentStart: 31 + token.count,
                                                  end: text.unicodeScalars.count, role: "assistant", marker: "assistant")])
        return ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: 10..<60, focusStyle: .focus,
                                   others: [70..<90])
    }

    func testTheReadersTextNeverWantsMoreThanItsColumn() throws {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [0.8, 1.0, 1.4] {
                CicadaTheme.uiScale = scale
                for column: CGFloat in [360, 420] {
                    let width = column * CGFloat(scale)
                    let renderer = ImageRenderer(content: ReaderTurnsView(blocks: hostileBlocks(), landingTurn: 2, revealed: true))
                    renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                    let size = try XCTUnwrap(renderer.nsImage).size
                    XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(column) × \(scale): \(size.width)")
                }
            }
        }
    }

    /// The host decides the Reader's width first; a page with a rigid 2000 pt child is clipped to the
    /// rest, never the Reader past the window's edge.
    func testAPageThatWillNotGiveWayNeverPushesTheReaderOffWindow() throws {
        for (content, reader) in [(CGFloat(1144), CGFloat(360)), (1384, 420)] {
            let host = ShellReaderHost(showsReader: true, navWidth: 56) {
                Color.clear.frame(width: 2000, height: 10)
            } reader: {
                Color.clear
            }
            let renderer = ImageRenderer(content: host)
            renderer.proposedSize = ProposedViewSize(width: content, height: 800)
            XCTAssertEqual(try XCTUnwrap(renderer.nsImage).size.width, content, accuracy: 0.5)
            let plan = ColumnLayout.plan(contentWidth: content, navWidth: 56, scale: 1, hasList: false,
                                         hasDetail: true, hasTrailing: true)
            XCTAssertEqual(plan.trailing, reader)
        }
    }
}
```

Append to `ReaderTurnsTests.swift`:

```swift
    /// R-DI11 — the washes become CitedSpan segments: the cited span current, the others soft, a
    /// derived match a mention; a focus that starts where another span does wins; out of range is skipped.
    func testWashesBecomeCitedSegments() {
        let block = ReaderBlock(index: 1, chunk: 0, role: "user", speaker: "You", mark: nil, time: nil,
                                text: "alpha beta gamma delta", contentStart: 0,
                                washes: [ReaderWash(range: 6..<10, style: .other), ReaderWash(range: 6..<16, style: .focus),
                                         ReaderWash(range: 17..<22, style: .mention), ReaderWash(range: 40..<50, style: .other)])
        XCTAssertEqual(ReaderText.segments(block), [
            .init(text: "alpha ", mark: .plain), .init(text: "beta gamma", mark: .current),
            .init(text: " ", mark: .plain), .init(text: "delta", mark: .mention)])
    }
```

Append to `ProvenanceRouterTests.swift`:

```swift
    /// R-DI9 — a swap onto the same conversation re-lands in place: no new Back step.
    func testRefocusReplacesTheTopForTheSameDocumentAndOpensAnyOther() {
        let router = ProvenanceRouter()
        router.open(ReaderTarget(episode: "ep_1", focus: .span(start: 1, end: 5, hash: nil, derived: true)))
        let before = router.revision
        let next = ReaderTarget(episode: "ep_1", focus: .span(start: 9, end: 14, hash: nil, derived: true))
        router.refocus(next)
        XCTAssertEqual(router.stack, [next])
        XCTAssertGreaterThan(router.revision, before, "the palette and the Belief Timeline still step aside")
        router.refocus(ReaderTarget(episode: "ep_2"))
        XCTAssertEqual(router.stack.map(\.episode), ["ep_1", "ep_2"], "another document is a real step")
        XCTAssertTrue(router.canGoBack)
    }
```

Append to `ThemeContrastTests.swift`:

```swift
    /// DR-18 / R-DI11 — cited words stay primary-ink legible on the wash, on the Reader's pane and
    /// on the focus card, in both themes. Measured on the rules' mocked system blue, like every accent
    /// bar in this file (R-DS4): the live accent is whatever the test Mac's is.
    func testPrimaryInkReadsOnTheCitedWash() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let accent = Color(hex: mode == .dark ? 0x0A84FF : 0x007AFF)
            let alpha = mode == .dark ? 0.18 : 0.10   // `CicadaTheme.wash`'s opacity
            for surface in [CicadaTheme.bgPane, CicadaTheme.bgFocus] {
                let wash = ThemeTokenTests.blend(accent, over: surface, alpha: alpha)
                XCTAssertGreaterThanOrEqual(c(CicadaTheme.textPrimary, wash), 7, "\(mode.rawValue)")
            }
        }
    }
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'ReaderColumnLayoutTests|ReaderTurnsTests|ProvenanceRouterTests|ThemeContrastTests' 2>&1 | tail -20`.
It fails to compile. That is the red.

- [ ] **Step 2: `ReaderText.segments`.** Replace `ReaderText.attributed` and its dandelion constants
  (`ReaderInspector.swift:479-513`). Put this in `ReaderModel.swift`, so the pure half stays in the model file:

```swift
/// R-DI11 — a turn's washes as `CitedSpan` segments: the cited span `.current` (the wash and the
/// accent underline, DR-18), another span the same entity cites `.other` (`washSoft`), a derived
/// match `.mention` (semibold, never washed, DR-57). Scalar offsets, as `ReaderLayout` computes them;
/// a wash that does not fit, or starts inside an earlier one, is skipped — never trapped on. At one
/// offset the cited span wins over a soft one.
enum ReaderText {
    static func segments(_ block: ReaderBlock) -> [CitedSpan.Segment] {
        let text = ScalarText(block.text)
        func rank(_ s: ReaderWash.Style) -> Int { s == .other ? 1 : 0 }
        let washes = block.washes
            .filter { $0.range.lowerBound >= 0 && $0.range.upperBound <= text.count && !$0.range.isEmpty }
            .sorted { ($0.range.lowerBound, rank($0.style)) < ($1.range.lowerBound, rank($1.style)) }
        var out: [CitedSpan.Segment] = []
        var cursor = 0
        for wash in washes where wash.range.lowerBound >= cursor {
            if wash.range.lowerBound > cursor {
                out.append(.init(text: text.slice(cursor, wash.range.lowerBound), mark: .plain))
            }
            let mark: CitedSpan.Mark = switch wash.style {
            case .focus: .current
            case .other: .other
            case .mention: .mention
            }
            out.append(.init(text: text.slice(wash.range.lowerBound, wash.range.upperBound), mark: mark))
            cursor = wash.range.upperBound
        }
        if cursor < text.count { out.append(.init(text: text.slice(cursor, text.count), mark: .plain)) }
        return out
    }
}
```

`QuoteBlock.swift:56` becomes `middle.backgroundColor = CicadaTheme.wash`. Its doc comment (`:48`) now reads: "the
accent `wash` (DR-18, R-DI11); the dandelion wash retired with the Reader's margin bar (DR-13)."

- [ ] **Step 3: `ProvenanceRouter.refocus`** (after `open`, `ProvenanceRouter.swift:122-128`). While in the file,
  `isPresented`'s doc comment ("Bound to `.inspector(isPresented:)`… The inspector's own toggle") becomes "Read by the
  Reader column's host; the stack is kept so the closing animation never shows an empty Reader". In
  `ReaderModel.swift:3-4`, "so `ReaderInspector` is a renderer" becomes "so `ReaderColumn` is a renderer".

```swift
    /// DR-29 / R-DI9 — the next question cites the conversation already open: re-land on its span in
    /// place. The top target is replaced, not pushed — Back is for moving between documents, and
    /// answering five questions beside one conversation must not build five Back steps. Anything
    /// else is an ordinary `open`.
    func refocus(_ target: ReaderTarget) {
        guard isPresented, let top = stack.last, top.episode == target.episode else {
            open(target)
            return
        }
        stack[stack.count - 1] = target
        revision &+= 1
    }
```

- [ ] **Step 4: `ReaderColumn.swift`.** After the `git mv`, keep the loader verbatim: `Phase`, `load()` with its
  cancellation guards, `act(_:)`, `step`, `jumpTo` and `land`. Replace the view tree.
  - **`ReaderColumn`**: the type is renamed from `ReaderInspector`, and its doc comment cites R-DI6 and the clipping
    root cause. The body is `VStack(spacing: 0) { ReaderColumnHeader(…); content }` — `content` switches on `phase`
    as today, and its loaded case is `document(…)`, which draws the pinned capture-and-navigator row above its own
    `ScrollView` (below) — with:
    - `.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)`;
    - `.background(CicadaTheme.bgPane)` and `.columnEdge()` (DR-9: the column edge is the one rule);
    - `.focusable()` and `.focusEffectDisabled()`, so Tab reaches the Reader after the question (R-DI10) and Esc
      reaches it while it holds focus;
    - `.onExitCommand { Instant.run { router.close() } }`, because Esc never animates (DR-60);
    - `.task(id: router.current) { await load() }`.
  - **`ReaderColumnHeader`** is a value view, laid out as the mock's header:
    `ReaderColumnHeader(canGoBack: Bool, onBack: () -> Void, page: EpisodeText?, markOrigin: String, episode: String,
    title: String, meta: String, canResume: Bool, agent: String?, onResume: () -> Void, onClose: () -> Void)`. `page`
    is the loaded document when `isPage`, else nil; `markOrigin` is today's `ReaderHeader.markOrigin(harness:origin:)`
    call (`:141-142`); `title`/`meta` are today's `title`/`meta` (`:153-158`); `canResume` is
    `conversationId.map { conversations.canResume($0) } ?? false`; `agent` is
    `EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin)`. Padding is 18 top, 16 trailing, 12 bottom and
    28 leading, all through `CicadaTheme.scaled`. Its parts:
    - `IconButton(systemName: "chevron.left", help: "\(Copy.Provenance.back) (⌥⌘[)", shortcut: KeyboardShortcut("[", modifiers: [.command, .option]))`,
      only when `canGoBack`. This keeps R-PU9's ⌥⌘[ ruling.
    - The mark at 20 pt. A page uses `LogoImage(entityId:name:type: .media, size:)`; anything else uses `OriginMark`
      with `.markHover()` and `.help("Episode \(episode)")` (DR-54, DR-52).
    - A `VStack` of the title, `displayFont(size: 20)` + `displayTracking(size: 20)`, `lineLimit(2)`, and the meta,
      `metaFont` `textTertiary` (`ReaderHeader.meta`).
    - `NeutralButton(title: Copy.Provenance.resume, systemImage: "arrow.uturn.right", size: .compact, help: Copy.Provenance.resumeHelp(agent))`,
      only when `canResume`, and `onResume` runs the existing `Task { await act(await conversations.resume(id)) }`.
      The descriptor comes from
      `POST /conversations/{id}/resume`, which only ever checks `isfile()`.
    - `IconButton(systemName: "xmark", help: Copy.Provenance.closeHelp)` → `router.close()`. That is a pointer path, so the host's
      animation plays.
  - **The capture-and-navigator row** is pinned above the scroll, for the reason `ReaderInspector.swift:234-237` gives:
    ⌥↑/⌥↓ must stay realised. It stays where the navigator lives today — at the top of `document(_:scalars:target:)`,
    above that function's `ScrollView` — because `presentation` and `stops` are computed there; only the loaded state
    has it (loading, gone and failed show no row).
    - `if let line = ReaderHeader.captureLine(doc) { Text(line) }` in `metaFont` `textTertiary`. The `info.circle` goes
      (DR-53: a glyph that adds nothing).
    - When `stops.count > 1`: `IconButton(systemName: "chevron.up", help: "\(Copy.Provenance.previousCited) (⌥↑)", shortcut: .init(.upArrow, modifiers: .option))`,
      the `ReaderNavigator.label` in `metaFont` `textSecondary` `monospacedDigit()`, and
      `IconButton(systemName: "chevron.down", help: "\(Copy.Provenance.nextCited) (⌥↓)", shortcut: .init(.downArrow, modifiers: .option))`. The ends are disabled as today.
    - Horizontal padding is 28.
  - **Content**, one `ScrollView` whose `LazyVStack(alignment: .leading, spacing: 0)` has padding 4 top, 28 horizontal
    and 72 bottom. There is no nested `ScrollView`, because DR-30 says each column scrolls once. In order:
    - **Banners.** `ReaderBannerView` becomes one meta line: glyph plus words, `metaFont` `textSecondary`, **no fill**
      (DR-37).
    - **Turns.** `ReaderTurnsView(blocks:landingTurn:revealed:)`, with 16 pt between turns and each block `.id(block.id)`.
    - **Noted.** `ReaderNotedList` at 32 pt top.
  - **`ReaderTurnView`** has two parts:
    - The speaker line (only on `startsTurn`): the `OriginMark` at 12 when `block.mark` is set, the speaker in 12
      medium `textSecondary`, then `"· " + Copy.Provenance.turn(index)` and the time, both in `metaFont`
      `textTertiary`. The time shows only when stored.
    - The words:
      `CitedSpan.text(ReaderText.segments(block)).font(CicadaTheme.quoteFont).lineSpacing(CicadaTheme.quoteLineSpacing).foregroundStyle(isLanding ? textPrimary : textSecondary).fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).citedSpans(reveal: revealed ? 1 : 0)`.
      The dandelion margin bar is deleted (DR-13), and the accessibility label and rotor entries are unchanged.
  - **`ReaderNotedList`** is a value view taking `rows`, `currentRange`, `isPage`, `agent`, `alsoOn: [String]` (today's
    `payload.entities` minus the cited subjects, `:338-340`), `partial` (`payload.partial`), `onJump` and
    `onShowOnGraph`. It sits inside the content's one `ScrollView`, so it is only built for a loaded document.
    - It starts with `SectionLabel(Copy.Provenance.noted(count:isPage:))`, a new Copy function returning
      "Noted from this conversation (3)" through `UsageFormat.count`.
    - Then one row per citation (DR-48): the claim text (13 regular `textPrimary`, `lineLimit(2)`, a strikethrough when
      not current) over its who-line (`metaFont`, `textTertiary`, or `textTertiaryOnFill` on the current row).
      `EvidenceLabel.speaker(kind: row.displayKind, agent: agent)` (as `:375-376`) is followed by
      " · " + `Copy.Provenance.noLongerCurrent` when the row is not current — joined outside `Text(` (R-DI23).
    - The row is `bgSelected` when `range == currentRange`, `bgHover` on hover, and has no fill otherwise, at
      `cornerRadiusSmall`.
    - A click jumps; it is disabled without a range, as today. A trailing `IconButton(systemName: "scope", help: Copy.Provenance.showOnGraph(name))`
      sets `appRouter.pendingTab = .graph` + `graphVM.revealEntity(id:)` exactly as `:398-401` does.
    - Below the rows come `alsoOn` / `notedPartial` / `nothingNoted` as meta lines. The subject logo leaves the row
      (DR-38: the claim already names it; the mock draws none).
  - **Loading** (DR-32) is a skeleton in the header's shape: four `bgSelected` bars at 30 % / 94 % / 88 % / 52 % of the
    column, 12–14 pt tall, `radiusXS`. They sit under a header built from `router.current?.knownTitle` /
    `knownHarness`. `accessibilityHidden(true)`, with no shimmer.
  - **Gone:** `Text(Copy.Provenance.gone)` in `detailBodyFont` `textTertiary`.
  - **Failed:** `Text(Copy.Provenance.failed)` + `NeutralButton(title: Copy.Provenance.retry, size: .compact) { Task { await load() } }`.
  - **Empty:** `Copy.Provenance.empty`.
  - **`ShellReaderHost`**, in the same file:

```swift
/// R-DI6 / DR-31 — the shell's trailing column for every page that has not adopted
/// `ProgressiveColumns` yet. The Reader's width is decided FIRST (`ColumnLayout`) and the page gets
/// the rest in a fixed, clipped frame, so a page with a rigid minimum can never push the Reader past
/// the window's edge — which is what the retired `.inspector` did. Pointer paths animate on the
/// drawer curve; Esc arrives inside `Instant.run` and does not (DR-60, DR-61).
struct ShellReaderHost<Page: View, Reader: View>: View {
    let showsReader: Bool
    let navWidth: CGFloat
    @ViewBuilder var page: () -> Page
    @ViewBuilder var reader: () -> Reader

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let plan = ColumnLayout.plan(contentWidth: geo.size.width, navWidth: navWidth,
                                         scale: CGFloat(CicadaTheme.uiScale), hasList: false,
                                         hasDetail: true, hasTrailing: showsReader)
            HStack(spacing: 0) {
                page()
                    .frame(width: plan.detail, height: geo.size.height, alignment: .topLeading)
                    .clipped()
                if showsReader {
                    reader()
                        .frame(width: plan.trailing, height: geo.size.height)
                        .transition(CicadaMotion.readerTransition(reduceMotion: reduceMotion))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
        }
        .animation(showsReader ? CicadaMotion.readerIn(reduceMotion: reduceMotion)
                               : CicadaMotion.readerOut(reduceMotion: reduceMotion), value: showsReader)
    }
}
```

Add to `Copy.Provenance`:

```swift
    static let closeHelp = "Close (Esc)"
    static func resumeHelp(_ agent: String?) -> String { "Resume this conversation in \(agent ?? "its app")" }
    static func noted(count: Int, isPage: Bool) -> String {
        "\(isPage ? notedFromThisPage : notedFromThisConversation) (\(UsageFormat.count(count)))"
    }
    static func rotorLabel(speaker: String, turn n: Int) -> String { "\(speaker), \(turn(n))" }
```

The rotor entries use `rotorLabel`, so no count is interpolated inside a `Text(` line (R-DI23).

- [ ] **Step 5: The shell hosts it.** In `ContentView.swift:190-205`, replace `detailContent … .inspector { … }` with:

```swift
            // DR-31 / R-DI6 — the Reader is a column beside whatever is open, sized first; the page gets
            // the rest. It replaced a trailing `.inspector`, whose width was not the page's to give.
            ShellReaderHost(showsReader: provenance.isPresented,
                            navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) {
                detailContent
                    .background(CicadaTheme.background)
                    // A rolled-back mutation posts `store.toast`; it shows at the bottom of the page (§5.4).
                    .overlay(alignment: .bottom) { toastBanner }
            } reader: {
                ReaderColumn()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
```

The Inbox keeps using this host until Task 5 gives it its own column. `rg -n '\.inspector\(' app/CicadaApp/Sources`
must print nothing.

- [ ] **Step 6: Green.**
  - Run the Step 1 filter, `swift build`, then the full `swift test`. There are 0 failures.
  - `swift test --filter 'FontLiteralLintTests|SectionLabelLintTests|ElevationLintTests|MeadowPlacementLintTests'` passes.
    The Reader title is `displayFont(size: 20)` with its tracking, the floor being 20.
- [ ] **Step 7: Commit.** Stage named files only, including the rename. Message:
  `feat(ds2, g118): the Reader is a column — CitedSpan turns, Resume, the pinned navigator, Noted rows, states in words; never pushed off-window (DR-9, DR-13, DR-16, DR-18, DR-31, DR-32, DR-37, DR-40, DR-48, DR-52, DR-53, DR-57, DR-60, DR-61)`.

---

### Task 5: The Inbox in progressive columns (§5.3 — DR-22…DR-31, DR-42, DR-45, DR-46, DR-48, DR-50, DR-60, DR-68; R-DI8, R-DI10, R-DI14, R-DI16…R-DI19, R-DI23, R-DI25, R-DI26)

The page adopts the container. There are three states and one Undo row, keyboard-first. The old list, card and chip
retire.

**Files:**
- Move:
  - `git mv app/…/Views/Inbox/InboxListView.swift app/…/Views/Inbox/InboxPage.swift` (rewrite);
  - `git mv app/…/Views/Inbox/QuestionView.swift app/…/Views/Inbox/QuestionResolution.swift`. Keep only
    `QuestionResolution` (now `Equatable`) and `MergeReject`; delete the view.
- Delete: `app/…/Views/Inbox/InboxCardView.swift` (`git rm`).
- Create: `app/…/Views/Inbox/InboxColumns.swift`, `app/…/Views/Inbox/InboxQuestionList.swift`
- Modify:
  - `app/…/ViewModels/InboxViewModel.swift`;
  - `app/…/Views/Shell/TitlebarHelp.swift:9-15`;
  - `app/…/ContentView.swift`: `:442-443`, the `showsReader` from Task 4, and the bank `onChange` at `:87-90`;
  - `app/…/Views/Sources/ChannelSourceView.swift:120-138`;
  - `app/…/Views/Common/CicadaSearchField.swift:3-4` (the doc comment drops "and the Inbox");
  - `app/…/Models/InboxPresentation.swift`: delete `causeLine()`, `:96-108`, which has no readers left;
  - doc comments only: `app/…/Models/QuestionSelection.swift`, `app/…/Models/InboxItem.swift`,
    `app/…/Extensions/String+Trimmed.swift`, `app/…/Theme/CicadaTheme.swift` (Step 8).
- Test: `InboxColumnsTests.swift` (new), `InboxProvenanceIdLintTests.swift` (new), `TitlebarHelpTests.swift`,
  `CountLiteralLintTests.swift` (scope), `SelectionTintLintTests.swift` (scope), and `InboxPresentationTests.swift`
  (delete `testCauseLineReadsFromTitleHarnessAndAge`, `:44-62`, together with `causeLine`).

**Interfaces:**
- Produces:
  - `InboxColumns` (`openId`, `kindFilter`; `select`, `readerEffect(for:readerEpisode:)`, `neighbour`, `afterAnswer`,
    `undo`, `reconcile`, `filter`, `land`, `escape`, `close`, `visible(_:filter:)`, `precedes`);
  - `InboxRows.entries(visible:held:snapshot:filter:)` and `InboxRowEntry`;
  - `InboxRowSlots.of(listUnits:)` (R-DI26);
  - `InboxEyebrow.text(visible:openId:)`, `InboxTabs.tabs(_:)`;
  - on `InboxViewModel`: `columns`, `visible`, `openItem`, `held`, `heldQuestion`, `rows`, `eyebrow`, `tabs`,
    `setFilter`, `reconcile`, `resetColumns`, `heldRemoval(channel:)`, `answerAndFollow(_:_:reader:)`;
  - `InboxPage`, `InboxQuestionList`, `InboxRow`, `InboxUndoRow`, `HelpContent.inbox`.
- Consumes: everything above.

- [ ] **Step 1: Failing tests.** Create `InboxColumnsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// §5.3 / DR-27…DR-30 / R-DI8…R-DI10 — which question is open, pure. `@MainActor` because
/// `InboxResolve` (inside `ResolveGrace`) conforms to the main-actor `Mutation` protocol.
@MainActor
final class InboxColumnsTests: XCTestCase {
    private func item(_ id: String, kind: String = "conflict", priority: Double = 0.5, created: String = "2026-09-01",
                      episode: String? = nil) throws -> InboxItem {
        let cause = episode.map { #","cause":{"episodeId":"\#($0)","excerpt":"x","mentionOffsets":[[0,1]],"start":0,"tier":"claim"}"# } ?? ""
        return try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"\#(id)","kind":"\#(kind)","requiredInput":"choice","title":"\#(id)","priority":\#(priority),"createdDate":"\#(created)","entityId":"alpha-project"\#(cause)}"#.utf8))
    }

    func testTheOrderIsPriorityThenNewest() throws {
        let a = try item("a", priority: 0.2), b = try item("b", priority: 0.9), c = try item("c", priority: 0.2, created: "2026-09-10")
        XCTAssertEqual(InboxColumns.visible([a, b, c], filter: nil).map(\.id), ["b", "c", "a"])
        XCTAssertEqual(InboxColumns.visible([a, b, try item("d", kind: "decay")], filter: .decay).map(\.id), ["d"])
    }

    /// DR-29 — the Reader closes on a swap unless the new question cites the same conversation.
    func testASwapKeepsTheReaderOnlyForTheSameConversation() throws {
        let same = try item("a", episode: "ep_1"), other = try item("b", episode: "ep_2"), none = try item("c")
        var c = InboxColumns()
        XCTAssertEqual(c.select(same, in: [same, other, none], readerEpisode: nil), .keep, "no Reader, nothing to do")
        let effect = c.select(same, in: [same, other, none], readerEpisode: "ep_1")
        guard case .refocus(let t) = effect else { return XCTFail("same conversation re-lands in place (R-DI9)") }
        XCTAssertEqual(t.episode, "ep_1")
        XCTAssertEqual(c.select(other, in: [same, other, none], readerEpisode: "ep_1"), .close)
        XCTAssertEqual(c.select(none, in: [same, other, none], readerEpisode: "ep_1"), .close)
        XCTAssertEqual(c.openId, "c")
    }

    /// DR-29 — after an answer the next row opens at once; the last answer returns to STATE 0.
    func testAfterAnAnswerTheNextRowOpensAndTheLastReturnsToStateZero() throws {
        let a = try item("a"), b = try item("b"), c = try item("c")
        var cols = InboxColumns()
        _ = cols.select(b, in: [a, b, c], readerEpisode: nil)
        cols.afterAnswer("b", remaining: [a, c])
        XCTAssertEqual(cols.openId, "c", "the row that moved into the answered row's place")
        cols.afterAnswer("c", remaining: [a])
        XCTAssertEqual(cols.openId, "a", "the last row answered: the one before it")
        cols.afterAnswer("a", remaining: [])
        XCTAssertNil(cols.openId)
        cols.afterAnswer("zzz", remaining: [a])
        XCTAssertNil(cols.openId, "an answer from elsewhere (the Sources page) moves nothing")
    }

    func testUndoReopensTheQuestionAndClearsAFilterThatHidesIt() throws {
        let d = try item("d", kind: "decay")
        var cols = InboxColumns()
        cols.kindFilter = .conflict
        cols.undo(d)
        XCTAssertEqual(cols.openId, "d")
        XCTAssertNil(cols.kindFilter)
    }

    /// A question answered elsewhere (MCP, an organic Sleep resolve) hands the column to its neighbour.
    func testAVanishedQuestionHandsOverToItsNeighbourAndAnEmptiedTabReturnsToAll() throws {
        let a = try item("a"), b = try item("b"), c = try item("c")
        var cols = InboxColumns()
        _ = cols.select(b, in: [a, b, c], readerEpisode: nil)
        cols.reconcile(visible: [a, c], kinds: [.conflict])
        XCTAssertEqual(cols.openId, "c")
        cols.kindFilter = .decay
        cols.reconcile(visible: [a, c], kinds: [.conflict])
        XCTAssertNil(cols.kindFilter)
        cols.reconcile(visible: [], kinds: [])
        XCTAssertNil(cols.openId)
    }

    /// DR-45 — a tab keeps the open question when it shows it, else opens its first; STATE 0 stays 0.
    func testATabSwitchKeepsOrReplacesTheOpenQuestion() throws {
        let a = try item("a"), d = try item("d", kind: "decay")
        var cols = InboxColumns()
        cols.filter(.decay, visibleAfter: [d])
        XCTAssertNil(cols.openId)
        _ = cols.select(a, in: [a, d], readerEpisode: nil)
        cols.filter(.decay, visibleAfter: [d])
        XCTAssertEqual(cols.openId, "d")
        cols.filter(nil, visibleAfter: [a, d])
        XCTAssertEqual(cols.openId, "d")
    }

    /// DR-28 — Esc closes the rightmost open thing (the card has already closed its field).
    func testEscapeClosesTheReaderThenTheQuestion() throws {
        var cols = InboxColumns()
        XCTAssertEqual(cols.escape(readerOpen: false), .none)
        XCTAssertEqual(cols.escape(readerOpen: true), .closeReader, "R-DI8 — STATE 0 + Reader")
        _ = cols.select(try item("a"), in: [], readerEpisode: nil)
        XCTAssertEqual(cols.escape(readerOpen: true), .closeReader)
        XCTAssertEqual(cols.escape(readerOpen: false), .closeQuestion)
    }

    /// DR-68 — ↑/↓ on the list: the neighbour, the first or last from nothing, clamped at the ends.
    func testArrowsWalkTheListAndStopAtItsEnds() throws {
        let a = try item("a"), b = try item("b")
        var cols = InboxColumns()
        XCTAssertEqual(cols.neighbour(1, in: [a, b])?.id, "a")
        XCTAssertEqual(cols.neighbour(-1, in: [a, b])?.id, "b")
        _ = cols.select(b, in: [a, b], readerEpisode: nil)
        XCTAssertEqual(cols.neighbour(1, in: [a, b])?.id, "b")
        XCTAssertEqual(cols.neighbour(-1, in: [a, b])?.id, "a")
    }

    /// G136 / DR-30 — a palette or Home hand-off: every kind shown, that question open.
    func testALandingClearsTheFilterAndOpensTheQuestion() {
        var cols = InboxColumns()
        cols.kindFilter = .decay
        cols.land("inbox-007")
        XCTAssertEqual(cols.openId, "inbox-007")
        XCTAssertNil(cols.kindFilter)
    }

    /// DR-42 — the Undo row takes the answered row's place in the list.
    func testTheUndoRowSitsWhereTheAnsweredRowWas() throws {
        let a = try item("a", priority: 0.9), b = try item("b", priority: 0.5), c = try item("c", priority: 0.1)
        let held = ResolveGrace(resolve: InboxResolve(id: "b", action: "resolve", optionKey: "x"), label: "Answered · x",
                                shortLabel: "Answered", question: "b", kind: .conflict, channel: nil, bank: "demo", token: 1)
        XCTAssertEqual(InboxRows.entries(visible: [a, c], held: held, snapshot: [a, b, c], filter: nil).map(\.id), ["a", "b", "c"])
        XCTAssertEqual(InboxRows.entries(visible: [a, c], held: held, snapshot: [a, b, c], filter: .decay).map(\.id), ["a", "c"])
        XCTAssertEqual(InboxRows.entries(visible: [a, c], held: nil, snapshot: [a, b, c], filter: nil).map(\.id), ["a", "c"])
    }

    /// R-DI26 / DR-31 — a one-line row's fixed slots go before they would overflow the column.
    func testAWideRowDropsItsSlotsBeforeItOverflows() {
        XCTAssertEqual(InboxRowSlots.of(listUnits: 1384), .init(entity: true, source: true))
        XCTAssertEqual(InboxRowSlots.of(listUnits: 680), .init(entity: true, source: true))
        XCTAssertEqual(InboxRowSlots.of(listUnits: 632), .init(entity: false, source: true), "1200 labelled + Reader")
        XCTAssertEqual(InboxRowSlots.of(listUnits: 441), .init(entity: false, source: false), "1.4× beside a Reader")
    }

    /// DR-25 — "Inbox · 6 pending", "Inbox · 1 of 6 · Conflict".
    func testTheEyebrowAndTheTabs() throws {
        let a = try item("a"), b = try item("b"), d = try item("d", kind: "decay", priority: 0.1)
        XCTAssertEqual(InboxEyebrow.text(visible: [a, b, d], openId: nil), "Inbox · 3 pending")
        XCTAssertEqual(InboxEyebrow.text(visible: [a, b, d], openId: "b"), "Inbox · 2 of 3 · Conflict")
        XCTAssertEqual(InboxEyebrow.text(visible: [], openId: nil), "Inbox")
        let tabs = InboxTabs.tabs([a, b, d])
        XCTAssertEqual(tabs.map(\.label), ["All", "Decay", "Conflict"], "present kinds, in the stable order")
        XCTAssertEqual(tabs.map(\.count), [3, 1, 2])
        XCTAssertEqual(tabs.map(\.id), [nil, .decay, .conflict])
    }
}
```

Create `InboxProvenanceIdLintTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// DR-54 (scoped to the Inbox, R-DI23) — a source is named the way a person would. An episode id, a
/// harness slug or an origin id reaches the Inbox's screen only through `.help`, an accessibility
/// label or a copy action — never interpolated into a `Text`.
final class InboxProvenanceIdLintTests: XCTestCase {
    static let needles = ["\\(cause.harness", "\\(cause.origin", "\\(cause.episodeId", "\\(item.cause", "ep_"]

    func testTheInboxNeverPrintsAnIdOrASlug() throws {
        let files = try ThemeTokenTests.swiftSources().filter { $0.path.contains("/Views/Inbox/") }
        XCTAssertGreaterThanOrEqual(files.count, 6, "the scope moved — this lint would pass vacuously")
        var offenders: [String] = []
        for file in files {
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains("Text(") {
                if Self.needles.contains(where: line.contains) { offenders.append("\(file.lastPathComponent):\(i + 1)") }
            }
        }
        XCTAssertEqual(offenders, [], "DR-54 — name the source through InboxSourceLine")
    }
}
```

Edit the two scope lists:
- `CountLiteralLintTests.scope` (`:34-43`) gains `"/Views/Inbox/"` and `"/Views/Provenance/ReaderColumn.swift"`.
- `SelectionTintLintTests.scoped` gains `"Views/Inbox/InboxQuestionList.swift"`.

In `TitlebarHelpTests.swift`, `testHelpContentIsExactlyTwoCases` becomes `…ExactlyThreeCases`, with
`[.aboutCicada, .howSleepWorks, .inbox]` and the exhaustive switch. Add:

```swift
    /// R-DI17 / DR-25 — the Inbox's old subtitle and its keys live behind its `?`.
    func testTheInboxAnswersForItself() {
        XCTAssertEqual(HelpContent.page(.inbox), .inbox)
        XCTAssertEqual(HelpContent.page(.sleep), .howSleepWorks)
        XCTAssertEqual(HelpContent.page(.graph), .aboutCicada)
        XCTAssertEqual(InboxHelp.keys.map(\.key), ["1–9", "↑ ↓", "⏎", "O", "L", "⌘Z", "Esc", "Tab"])
    }
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'InboxColumnsTests|InboxProvenanceIdLintTests|TitlebarHelpTests' 2>&1 | tail -20`.
It fails to compile. That is the red.

- [ ] **Step 2: `InboxColumns.swift`** (pure):

```swift
import Foundation

/// §5.3 — which question is open, pure (DR-27…DR-30; R-DI8…R-DI10, R-DI19). The Reader's own state
/// is `ProvenanceRouter`'s; this only answers what the page does with it. Held by `InboxViewModel`,
/// so a page switch keeps the open question and the tab; a bank switch resets both (ids repeat
/// across banks).
struct InboxColumns: Equatable {
    private(set) var openId: String?
    var kindFilter: InboxKind?
    /// Where the open question sat, so one that vanishes hands the column to its neighbour.
    private(set) var openIndex: Int?

    enum ReaderEffect: Equatable {
        case keep, close
        /// R-DI9 — the same conversation: re-land in place on the new question's span.
        case refocus(ReaderTarget)
    }

    enum Escape: Equatable { case closeReader, closeQuestion, none }

    /// G115 — the inbox's one order: priority, then newest.
    static func precedes(_ a: InboxItem, _ b: InboxItem) -> Bool {
        a.priority != b.priority ? a.priority > b.priority : a.createdDateValue > b.createdDateValue
    }

    static func visible(_ items: [InboxItem], filter: InboxKind?) -> [InboxItem] {
        items.filter { filter == nil || $0.kind == filter }.sorted(by: precedes)
    }

    /// DR-29 — the Reader stays on a swap only when the new question cites its conversation.
    static func readerEffect(for item: InboxItem?, readerEpisode: String?) -> ReaderEffect {
        guard let readerEpisode else { return .keep }
        guard let item, let target = item.cause?.readerTarget(subjectId: item.entityId.isEmpty ? nil : item.entityId),
              target.episode == readerEpisode else { return .close }
        return .refocus(target)
    }

    mutating func select(_ item: InboxItem, in visible: [InboxItem], readerEpisode: String?) -> ReaderEffect {
        openId = item.id
        openIndex = visible.firstIndex { $0.id == item.id }
        return Self.readerEffect(for: item, readerEpisode: readerEpisode)
    }

    mutating func close() {
        openId = nil
        openIndex = nil
    }

    /// DR-68 — ↑/↓ on the list: the neighbour, clamped; from nothing, the first (↓) or the last (↑).
    func neighbour(_ delta: Int, in visible: [InboxItem]) -> InboxItem? {
        guard !visible.isEmpty else { return nil }
        guard let id = openId, let i = visible.firstIndex(where: { $0.id == id }) else {
            return delta >= 0 ? visible.first : visible.last
        }
        return visible[min(max(i + delta, 0), visible.count - 1)]
    }

    /// DR-29 — the next row opens at once: the one now in the answered row's place, else the one
    /// before; the last answer returns the page to STATE 0. An answer made elsewhere moves nothing.
    mutating func afterAnswer(_ id: String, remaining: [InboxItem]) {
        guard openId == id else { return }
        guard !remaining.isEmpty else { return close() }
        let i = min(openIndex ?? 0, remaining.count - 1)
        openId = remaining[i].id
        openIndex = i
    }

    /// DR-42 — Undo reopens its question, clearing a tab that would hide it.
    mutating func undo(_ item: InboxItem) {
        if let k = kindFilter, k != item.kind { kindFilter = nil }
        openId = item.id
        openIndex = nil
    }

    /// A snapshot moved: a vanished question hands over to its neighbour (or STATE 0), and a tab
    /// whose kind emptied returns to All.
    mutating func reconcile(visible: [InboxItem], kinds: Set<InboxKind>) {
        if let k = kindFilter, !kinds.contains(k) { kindFilter = nil }
        guard let id = openId else { return }
        if let i = visible.firstIndex(where: { $0.id == id }) {
            openIndex = i
            return
        }
        guard !visible.isEmpty else { return close() }
        let i = min(openIndex ?? 0, visible.count - 1)
        openId = visible[i].id
        openIndex = i
    }

    /// DR-45 — a tab keeps the open question when it shows it, else opens its first; STATE 0 stays 0.
    mutating func filter(_ kind: InboxKind?, visibleAfter: [InboxItem]) {
        kindFilter = kind
        guard let id = openId, !visibleAfter.contains(where: { $0.id == id }) else { return }
        openId = visibleAfter.first?.id
        openIndex = visibleAfter.isEmpty ? nil : 0
    }

    /// G136 / DR-30 — a palette or Home hand-off: every kind shown, that question open.
    mutating func land(_ id: String) {
        kindFilter = nil
        openId = id
        openIndex = nil
    }

    /// DR-28 — Esc closes the rightmost open thing. The card has already closed its own field.
    func escape(readerOpen: Bool) -> Escape {
        readerOpen ? .closeReader : (openId == nil ? .none : .closeQuestion)
    }
}

/// One line of the list: a question, or the Undo row that took its place (DR-42). The Undo row keeps
/// the question's id, so the swap is a content change in place — instant, never a transition (DR-61).
enum InboxRowEntry: Identifiable {
    case item(InboxItem)
    case undo(ResolveGrace, InboxItem)

    var id: String {
        switch self {
        case .item(let item): item.id
        case .undo(let held, _): held.id
        }
    }
}

enum InboxRows {
    static func entries(visible: [InboxItem], held: ResolveGrace?, snapshot: [InboxItem],
                        filter: InboxKind?) -> [InboxRowEntry] {
        var rows = visible.map(InboxRowEntry.item)
        guard let held, let item = snapshot.first(where: { $0.id == held.id }),
              filter == nil || filter == item.kind else { return rows }
        let at = visible.firstIndex { !InboxColumns.precedes($0, item) } ?? visible.count
        rows.insert(.undo(held, item), at: at)
        return rows
    }
}

/// R-DI26 / DR-31 — which fixed slots a STATE 0 row can afford. Glyph, gaps, age, chevron and
/// padding take ~132 units and the question needs ~120 to say anything, so the entity (180) goes
/// under 680 units of list and the source (220) under 480. A fixed frame in an `HStack` never
/// shrinks: without this, a list beside a Reader at 1.4× draws its rows under the Reader.
struct InboxRowSlots: Equatable {
    var entity: Bool
    var source: Bool

    static let entityFloor: CGFloat = 680
    static let sourceFloor: CGFloat = 480

    static func of(listUnits: CGFloat) -> InboxRowSlots {
        InboxRowSlots(entity: listUnits >= entityFloor, source: listUnits >= sourceFloor)
    }
}

/// DR-25 — "Inbox · 6 pending", or "Inbox · 1 of 6 · Conflict" while a question is open.
enum InboxEyebrow {
    static func text(visible: [InboxItem], openId: String?) -> String {
        if let id = openId, let i = visible.firstIndex(where: { $0.id == id }) {
            return Eyebrow.text(Copy.Inbox.title, Copy.Inbox.position(i + 1, of: visible.count), visible[i].kind.label)
        }
        return Eyebrow.text(Copy.Inbox.title, visible.isEmpty ? "" : Copy.Inbox.pending(visible.count))
    }
}

/// DR-45 — "All 6 · Decay 1 · Conflict 2 …": the kinds present, in a stable order, never a dot.
enum InboxTabs {
    static let order: [InboxKind] = [.decay, .conflict, .clarification, .followup, .mergeSuggestion,
                                     .removal, .divergence, .normalization]

    static func tabs(_ items: [InboxItem]) -> [TextTab<InboxKind>] {
        let counts = Dictionary(grouping: items, by: \.kind).mapValues(\.count)
        return [TextTab(id: nil, label: Copy.Inbox.all, count: items.count)]
            + order.compactMap { k in counts[k].map { TextTab(id: k, label: k.label, count: $0) } }
    }
}
```

- [ ] **Step 3: The view model.** In `InboxViewModel.swift`, add:

```swift
    /// R-DI19 — the page's selection, kept across page switches, reset by a bank switch.
    var columns = InboxColumns()

    var visible: [InboxItem] { InboxColumns.visible(items, filter: columns.kindFilter) }
    var openItem: InboxItem? { columns.openId.flatMap { id in items.first { $0.id == id } } }
    var held: ResolveGrace? { store.currentHeld }
    /// The held answer's question, from the snapshot (`visibleInbox` hides it) — the Undo row's words.
    var heldQuestion: InboxItem? { held.flatMap { h in store.inbox.value?.first { $0.id == h.id } } }
    var rows: [InboxRowEntry] {
        InboxRows.entries(visible: visible, held: held, snapshot: store.inbox.value ?? [], filter: columns.kindFilter)
    }
    var eyebrow: String { InboxEyebrow.text(visible: visible, openId: columns.openId) }
    var tabs: [TextTab<InboxKind>] { InboxTabs.tabs(items) }

    func setFilter(_ kind: InboxKind?) {
        columns.filter(kind, visibleAfter: InboxColumns.visible(items, filter: kind))
    }
    func reconcile() { columns.reconcile(visible: visible, kinds: Set(items.map(\.kind))) }
    func resetColumns() { columns = InboxColumns() }

    /// R-DI16 — the Sources page's own Undo row: a held removal for that browser channel, with its
    /// question (still in the snapshot; only `visibleInbox` hides it).
    func heldRemoval(channel: String?) -> (held: ResolveGrace, item: InboxItem)? {
        guard let held, held.kind == .removal, held.channel == channel,
              let item = store.inbox.value?.first(where: { $0.id == held.id }) else { return nil }
        return (held, item)
    }

    /// DR-29 — answer, then the Reader follows the next question: it stays only for the same
    /// conversation (R-DI9), and closes after the last answer. The router is passed in because it is
    /// an environment value, not the model's; the Sources page calls plain `answer`.
    func answerAndFollow(_ item: InboxItem, _ resolution: QuestionResolution, reader: ProvenanceRouter) {
        answer(item, resolution)
        let episode = reader.isPresented ? reader.current?.episode : nil
        switch InboxColumns.readerEffect(for: openItem, readerEpisode: episode) {
        case .keep: break
        case .close: reader.close()
        case .refocus(let target): reader.refocus(target)
        }
    }
```

Two changes to the existing methods:
- `answer(_:_:)` gains a final line, `columns.afterAnswer(item.id, remaining: visible)` (DR-29).
- `undo(reopen:)` becomes
  `guard let id = store.undoHeld(), let item = store.inbox.value?.first(where: { $0.id == id }) else { return nil }; if reopen { columns.undo(item) }; return item`.

The `countByKind` projection (`:40-42`) is deleted, because `InboxTabs` replaces its one reader.

- [ ] **Step 4: The list.** `InboxQuestionList.swift` holds `InboxQuestionList`, `InboxRow` and `InboxUndoRow`.
  - **`InboxQuestionList`** is a `ScrollViewReader { ScrollView { VStack(spacing:) { ForEach(entries) … } } }`.
    - The stack is not lazy: an Undo row's ⌘Z must stay realised (R-DI4), and an inbox is tens of rows.
    - Spacing is `RowMetrics.twoLineGap` in `.triage` and 0 otherwise.
    - Padding, every value through `CicadaTheme.scaled`: `.wide` is top 0, horizontal 30 (30 + a row's own 10 = the
      40 gutter), bottom 72; `.triage` and `.titles` are top 0, trailing 8, bottom 24, leading 12 (the mock's CSS
      `0 8 24 12`).
    - It takes `width` (the plan's `list`, points) and hands each `.wide` row
      `InboxRowSlots.of(listUnits: width / CGFloat(CicadaTheme.uiScale))` (R-DI26).
    - It is `.focusable()` and `.focusEffectDisabled()`, bound to the page's `.list` focus.
    - `.onMoveCommand` → `move(±1)`, `.onKeyPress(.return)` → `focusQuestion()`, and `.onExitCommand` → `escape()`.
    - On `.onChange(of: landingToken)`, `proxy.scrollTo(openId, anchor: .center)` inside `Instant.run` (DR-30).
    - `.animation(CicadaMotion.rowLeave(reduceMotion:), value: entries.map(\.id))` animates a row that leaves on the
      server's word. An Undo row keeps its question's id, so the tap itself is instant (DR-61).
  - **`InboxRow(item:style:slots:selected:now:open:)`** is a `Button` over the whole row, styled `.cicadaPlain`. `now`
    is `Date.now`, read in the list's body, so an age is computed when read (DR-58) and never stored.
    - **Fill:** `bgSelected` when selected, `bgHover` on hover, clear otherwise, at `cornerRadiusSmall`. No scale, no
      lift, no shadow (DR-48).
    - **Tokens:** selected text is `textPrimary`, question weight medium, meta `textTertiaryOnFill` (DR-2). Otherwise
      the question is `textSecondary` regular and the meta `textTertiary`.
    - **`.wide`** (36 pt, one line), leading to trailing:
      - `KindGlyph`;
      - the question, 13 regular, `lineLimit(1)`, `.frame(maxWidth: scaled(ColumnLayout.textMaxWidth))`, flexing;
      - the entity, 12, `lineLimit(1)`, `.frame(width: scaled(180), alignment: .leading)` — only when `slots.entity`;
      - the source slot, `.frame(width: scaled(220), alignment: .leading)`: `OriginMark` at 12 plus
        `InboxSourceLine.row`, with `.help(InboxSourceLine.help(item) ?? "")` — only when `slots.source` (R-DI26);
      - the age, `InboxRowAge.of(item, now: now)`: 12, `monospacedDigit()`, right-aligned, `.frame(width: scaled(30))`,
        with `.help(age.help)`;
      - `IconButton(systemName: "chevron.right", help: Copy.Inbox.openQuestion)` → `open`.
    - **`.triage`** (56 pt, two lines, top-aligned): line 1 is the glyph, the question and the age; line 2 is the entity,
      a middle dot, the mark and `InboxSourceLine.row`. Nothing in it has a fixed width: every text is `lineLimit(1)`
      and truncates, because the column can be 280 units wide.
    - **`.titles`** (36 pt): the glyph and the question, with `.help(item.questionText)`.
    - **Height** is `RowMetrics.*` through `CicadaTheme.scaled`. No row sets its own vertical padding (DR-34).
    - **Accessibility label:** `(selected ? "Open: " : "") + kind.label + " — " + questionText`, with
      `.accessibilityAddTraits(selected ? .isSelected : [])`.
  - **`InboxUndoRow(held:item:style:shortcutEnabled:onUndo:)`** (DR-42) has the same height as the row it replaced and
    a resting ring (`ringed(in:)`), with no fill and no shadow.
    - It holds a `checkmark.circle` glyph (14, `textTertiary`), then `held.label` (13 medium, `textSecondary`,
      `lineLimit(1)`).
    - Beside the label sits the question in 12 `textTertiary`: in a row for `.wide`, a column for `.triage`, omitted for
      `.titles`. The `.titles` form uses `held.shortLabel`.
    - Then `NeutralButton(title: Copy.Inbox.undo, size: .compact, shortcut: shortcutEnabled ? KeyboardShortcut("z", modifiers: .command) : nil, help: Copy.Inbox.undoHelp, action: onUndo)`.
    - It is `accessibilityElement(children: .contain)`, the mock's `role="status"`. When it appears it posts
      `AccessibilityNotification.Announcement(held.label)`, so VoiceOver hears what was answered and that Undo is there.
    - It leaves with `.transition(.opacity)` under `CicadaMotion.undoFade(reduceMotion:)`.

- [ ] **Step 5: The page.** Rewrite `InboxPage.swift` (renamed from `InboxListView`). The skeleton is below. The
  loading, error and empty states keep their existing truthful words: the `emptyStateDetail` logic moves verbatim,
  with its count going through `UsageFormat.count`.

```swift
import SwiftUI

/// The Inbox in progressive columns (DESIGN_RULES §5.3, the owner's Direction D). With nothing open
/// it is the questions alone at full width; a click narrows them to the triage column and opens the
/// question beside them; "Show in conversation" opens the Reader as the third column. One tap
/// answers, and an Undo row holds the answer for 5 s before anything is sent (DR-42, R-DI2).
struct InboxPage: View {
    @Environment(InboxViewModel.self) private var viewModel
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Focus: Hashable { case list, question, reader }
    @FocusState private var focus: Focus?
    @State private var editingText = false
    @State private var landingToken = 0

    var body: some View {
        Group {
            if let err = viewModel.errorMessage, viewModel.items.isEmpty, viewModel.held == nil {
                errorState(err)
            } else if viewModel.isLoading {
                loadingState
            } else if viewModel.items.isEmpty && viewModel.held == nil && !provenance.isPresented {
                emptyState
            } else {
                columns
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.bgBase)
        .onAppear { consumeLanding(); viewModel.reconcile() }
        .onChange(of: router.pendingInboxItem) { _, _ in consumeLanding() }
        .onChange(of: viewModel.items.map(\.id)) { _, _ in viewModel.reconcile() }
    }

    private var columns: some View {
        ProgressiveColumns(hasDetail: viewModel.openItem != nil, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: viewModel.eyebrow,
                       horizontalPadding: viewModel.openItem == nil && !provenance.isPresented
                           ? plan.gutter : CicadaTheme.spacingXL) {
                TextTabs(tabs: viewModel.tabs, selection: Binding(
                    get: { viewModel.columns.kindFilter },
                    set: { viewModel.setFilter($0) }))
            }
        } list: { plan in
            InboxQuestionList(entries: viewModel.rows, style: plan.listStyle, width: plan.list,
                              openId: viewModel.columns.openId,
                              undoShortcut: !editingText, landingToken: landingToken,
                              open: { open($0) }, undo: { undo() }, move: { move($0) },
                              focusQuestion: { focus = .question }, escape: { escape() })
                .focused($focus, equals: .list)
        } detail: { plan in
            if let item = viewModel.openItem {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingMD) {
                        // R-DI25 — the list is hidden, so its Undo row (and ⌘Z) moves here.
                        if plan.listHidden, let held = viewModel.held, let question = viewModel.heldQuestion {
                            InboxUndoRow(held: held, item: question, style: .titles,
                                         shortcutEnabled: !editingText) { undo() }
                        }
                        InboxFocusCard(item: item, padding: plan.cardPadding,
                                       onClose: { closeQuestion() },
                                       hiddenListCount: plan.listHidden ? viewModel.visible.count : nil,
                                       onShowList: { showList() },
                                       onEscape: { escape() },
                                       onEditingChange: { editingText = $0 }) { resolution in
                            // DR-29 / DR-61 — the swap after an answer is instant for pointer and key alike;
                            // a Reader that closes because the next question cites another conversation
                            // closes with it, never on the drawer curve (DR-60 for 1–9 and ⏎).
                            Instant.run { viewModel.answerAndFollow(item, resolution, reader: provenance) }
                        }
                        .id(item.id)
                        .focused($focus, equals: .question)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, plan.gutter)
                    .padding(.bottom, CicadaTheme.scaled(72))
                }
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
    }
}
```

Beside the view (not in `InboxViewModel`: the router is an environment value), add these private helpers:

- **`readerEpisode`**: `provenance.isPresented ? provenance.current?.episode : nil`. A closed router keeps its stack
  (`ProvenanceRouter.close()` only flips `isPresented`), so `current` alone is not "the Reader is showing".
- **`open(_ item:)`** is the pointer path.
  - From STATE 0 it runs
    `withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { apply(viewModel.columns.select(item, in: viewModel.visible, readerEpisode: readerEpisode)) }`.
  - A swap in place (a question already open) runs the same call without animation (DR-61).
  - Then `focus = .question` (R-DI10).
- **`move(_ delta:)`** is the keyboard path, inside `Instant.run`: `guard let next = viewModel.columns.neighbour(delta,
  in: viewModel.visible)`, then `apply(viewModel.columns.select(next, in: viewModel.visible, readerEpisode: readerEpisode))`.
  Focus stays on the list.
- **`apply(_ effect:)`**: `.close` → `provenance.close()`, `.refocus(t)` → `provenance.refocus(t)`, `.keep` → nothing.
- **Answering** goes through `InboxViewModel.answerAndFollow(_:_:reader:)` (Step 3), inside `Instant.run` (the skeleton).
- **`undo()`** runs inside `Instant.run` (⌘Z is a key; a click reopens in place, which DR-61 makes instant too):
  `if let item = viewModel.undo() { apply(InboxColumns.readerEffect(for: item, readerEpisode: readerEpisode)); focus = .question }`.
- **`escape()`** runs inside `Instant.run`: `.closeReader` → `provenance.close()`; `.closeQuestion` →
  `viewModel.columns.close()` then `focus = .list`.
- **`closeQuestion()`** is the pointer path (the × button):
  `withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { provenance.close(); viewModel.columns.close() }`.
- **`showList()`** (DR-27) closes the Reader if one is open, else the question. That matches `escape(readerOpen:)`,
  animated because it is a pointer path.
- **`consumeLanding()`** runs inside `Instant.run` (a ⌘K or Home hand-off is not a pointer path on this page):
  `guard let id = router.consumeInboxItem() else { return }`, then `viewModel.columns.land(id)`,
  `apply(InboxColumns.readerEffect(for: viewModel.openItem, readerEpisode: readerEpisode))`, and `landingToken &+= 1` so
  the row scrolls into view (DR-30).

The page states. Their words move into `Copy.Inbox` unchanged (`checking = "Checking what needs you…"`,
`loadFailed = "Couldn't load the inbox"`, `retry = "Retry"`, `nothingPending = "Nothing pending"`), so the page spells
no sentence of its own:
- **Loading** (DR-43): the eyebrow row, then `Copy.Inbox.checking` in `detailBodyFont` `textTertiary`, over six
  `bgSelected` skeleton bars at 62/48/71/39/55/66 % of 520 pt, 12 pt tall, 24 pt apart. There is no shimmer.
- **Error** (DR-43): a `radiusLarge` `bgFocus` ringed card, centred, 420 pt max. It holds `Copy.Inbox.loadFailed` in
  `headingFont`, the message in `detailBodyFont` `textTertiary`, and
  `NeutralButton(title: Copy.Inbox.retry) { Task { await viewModel.loadInbox() } }`. The `.borderedProminent` and the
  accent tint go (DR-40).
- **Empty** (DR-50): the existing `EmptyStateView(title: Copy.Inbox.nothingPending, message: emptyStateDetail)` under the
  eyebrow row, with its message unchanged except `UsageFormat.count(queued)`.

The page never publishes `pageFind`, because R-DI14 retires the field.

- [ ] **Step 6: The Inbox's `?`.** In `TitlebarHelp.swift`:
  - Add `case inbox` to `HelpContent`, and make `page(_:)` a `switch`: `.sleep` → `.howSleepWorks`, `.inbox` →
    `.inbox`, default → `.aboutCicada`.
  - The popover's switch gains `.inbox: InboxHelpPopover()`.
  - Add the popover and its key table:

```swift
/// R-DI17 / DR-25 — the Inbox's `?`: the subtitle the page no longer prints, and the keys that act on
/// it, each with its pointer twin on the page (DR-49, DR-68).
enum InboxHelp {
    struct Key: Equatable { let key: String; let does: String }
    static let keys: [Key] = [
        .init(key: "1–9", does: "Answer with an option"),
        .init(key: "↑ ↓", does: "Move through the questions, or the answers"),
        .init(key: "⏎", does: "Answer with the highlighted option"),
        .init(key: "O", does: "Other… — say what's actually true"),
        .init(key: "L", does: "Not now — ask again in 7 days"),
        .init(key: "⌘Z", does: "Undo the last answer"),
        .init(key: "Esc", does: "Close Other…, then the rightmost column"),
        .init(key: "Tab", does: "Move between the list, the question and the conversation"),
    ]
}

struct InboxHelpPopover: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SectionLabel("How the inbox works")
            Text(Copy.inboxSubtitle).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textPrimary)
            ForEach(InboxHelp.keys, id: \.key) { k in
                HStack(spacing: CicadaTheme.spacingSM) {
                    KeyHint(k.key).frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                    Text(k.does).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: CicadaTheme.scaled(340))
        .background(CicadaTheme.bgMenu)
    }
}
```

- [ ] **Step 7: The shell, and the Sources page.** In `ContentView.swift`:
  - `:442-443` becomes `InboxPage()`.
  - Task 4's `ShellReaderHost(showsReader:)` becomes `provenance.isPresented && selectedTab != .inbox`: the Inbox hosts
    its own Reader column (R-DI6).
  - The bank `onChange` (`:87-90`) gains `inboxVM.resetColumns()` (R-DI19).

In `ChannelSourceView.swift` (R-DI16), apply two edits:
- The section's guard (`:45`) becomes
  `if !removals.isEmpty || inboxVM.heldRemoval(channel: source.channelId) != nil { deletionsSection }`. `removals` reads
  `store.visibleInbox` (`:36-38`), so without this the last answered removal would hide the section and its own Undo row.
- The section's `VStack` (`:127-136`) becomes:

```swift
            VStack(spacing: CicadaTheme.spacingSM) {
                if let pending = inboxVM.heldRemoval(channel: source.channelId) {
                    InboxUndoRow(held: pending.held, item: pending.item, style: .wide, shortcutEnabled: true) {
                        inboxVM.undo(reopen: false)
                    }
                }
                ForEach(removals) { item in
                    InboxFocusCard(item: item, padding: CicadaTheme.spacingLG) { inboxVM.answer(item, $0) }
                }
            }
```

Its doc comment (`:120-122`) keeps its first line and ends: "…render the identical focus card and the identical Undo row
(R-DI16)."

- [ ] **Step 8: Retire the old views.**
  - `git rm app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift`.
  - After the `git mv`, `QuestionResolution.swift` holds only `QuestionResolution` (`Equatable`) and `MergeReject`, with
    their doc comments. `QuestionResolution`'s first line ("What a `QuestionView` interaction resolves to") becomes
    "What a focus-card answer resolves to", or the check below finds it.
  - Delete `causeLine()` and its test.
  - Update the doc comments that still name retired views, so they name what replaced them (`InboxViewModel`'s old
    `resolve` comment went with the method in Task 2):
    - `QuestionSelection.swift:3` → `InboxFocusCard`;
    - `InboxItem.swift:281` → the focus card's H1;
    - `Extensions/String+Trimmed.swift:3` → `InboxFocusCard` and its variants;
    - `Theme/CicadaTheme.swift:525` → `KindGlyph`.
  - `rg -n 'InboxCardView|InboxActionButton|KindChip|QuestionView\b|causeLine\(' app/CicadaApp` prints nothing.
- [ ] **Step 9: Green.**
  - Run the Step 1 filter, `swift build`, then the full `swift test`. There are 0 failures.
  - Negative control: add `.foregroundStyle(CicadaTheme.accent)` to a line in `InboxQuestionList.swift`.
    `swift test --filter SelectionTintLintTests` must FAIL. Revert it and confirm green.
  - Negative control: add a member that compiles anywhere in `InboxPage`,
    `private func lintProbe(_ item: InboxItem) -> Text { Text("\(item.cause?.harness ?? "")") }`.
    `swift test --filter InboxProvenanceIdLintTests` must FAIL (so will `CountLiteralLintTests`, which also watches the
    directory now). Revert it.
  - A lint that has never failed is not known to work.
- [ ] **Step 10: Commit.** Stage named files only: the renames, the `git rm`, and the edits. Message:
  `feat(ds2, g115): the Inbox in progressive columns — questions alone, the question beside them, the Reader as the third; eyebrow and text tabs; the Undo row (DR-22, DR-25, DR-26, DR-27, DR-28, DR-29, DR-30, DR-31, DR-34, DR-38, DR-40, DR-42, DR-43, DR-45, DR-46, DR-48, DR-50, DR-54, DR-58, DR-60, DR-61, DR-68)`.

---

### Task 6: Docs — the Inbox and the Reader as Direction D ships them

**Files:**
- Modify:
  - `CLAUDE.md`: the "Provenance viewer (G118 slice 2)" paragraph; "Graphite and Meadow" (`CitedSpan` "no view uses it
    yet"); Features §2/3 (a new paragraph after "Every resolution is a verdict (G113)"); and "Design rules — Direction D"
    (DS-2 shipped).
  - `docs/design/DESIGN_RULES.md` §9: new dated lines appended after `:672`. Old lines are never edited.
  - `docs/goals/TODO.md`: "Where things stand" / "Pick up here".
  - `docs/goals/memory-evolution.md`: one sentence each on G115 and G118.

- [ ] **Step 1: DESIGN_RULES §9.** Append one line per departure, each dated **2026-09-24** and in the file's voice.
  Cite this plan's ruling id in each.
  - **R-DI7:** the overflow regime. The question and the Reader split 440 : 360 when neither floor fits, because DR-31
    wins over DR-27.
  - **R-DI8:** STATE 0 + Reader.
  - **R-DI11:** a derived mention is semibold and unwashed, with "Found by searching the conversation". This follows
    DR-57 and CLAUDE.md's provenance rail over §5.3 item 3.
  - **R-DI14:** the Inbox's in-page field retires. This is DR-46 applied, and it reverses G136 S5.
  - **R-DI21:** the demo bank has no removal, divergence, normalization or informational item. `InboxFocusCardFitTests`
    renders them until a backend batch adds them.
  - **R-DI3:** the send-delay flush points add the window closing, and a page switch is not one; a held answer whose
    question left the snapshot is dropped, not sent.
  - **R-DI2:** `ResolveGrace` is a held `InboxResolve` in the `Store`, not a new `Mutation` (DR-42's sketch).
  - **R-DI6:** `ReaderInspector` is renamed `ReaderColumn` (DR-31 names the old type); pages that have not adopted
    `ProgressiveColumns` host it through `ShellReaderHost`.
  - **R-DI25:** with the list hidden, the Undo row sits at the head of the question column (DR-42 places it in the list).
  - **R-DI13:** no check line until G61 S3 serves a result.
  - **R-DI1:** no design flag, as R-DS1.

  Replace the closing paragraph's sentence about CLAUDE.md paragraphs "keep describing what ships until the track that
  implements D lands" with a new line. It says the Inbox and Provenance-viewer paragraphs describe D as of DS-2. Only
  the sentence changes; the dated lines above stay as they are.
- [ ] **Step 2: CLAUDE.md.** The new Inbox paragraph comes under Features §2/3, between "Every resolution is a verdict
  (G113)" and "Cause (G115 Phase 1…)", in the file's voice, about 12 wrapped lines:

  > **The page (Direction D, DS-2).** Progressive columns (`ProgressiveColumns`, `ColumnLayout` — DESIGN_RULES §5.3): the
  > questions alone at full width; a click narrows them to the triage column and opens the question as C's focus card;
  > "Show in conversation" opens the Reader as the third column. Widths are units (÷ uiScale); the list hides before the
  > question drops under 440, and when neither the question's 440 nor the Reader's 360 fits they share the width, so
  > nothing is pushed off-window. **One tap answers, and Undo is a send delay** (`ResolveGrace`, in the `Store`): the
  > answer leaves `visibleInbox` at once and `POST /inbox/{id}/resolve` waits 5 s (`CicadaTiming.undoWindow`), sent
  > early by the next answer, `ActivateBank` (before the bank moves), the window closing and quit (`.terminateLater`,
  > ≤ 3 s) — an undone answer makes no commit, claim or G113 event; a page switch does not send. Every kind renders in
  > the card (`FocusCardVariant`), options come from the server (a follow-up's 30-day "not now" is its own option), the
  > source is named in a person's words (`InboxSourceLine`, ids in `.help` only), an asserted span is washed and
  > underlined and a found mention is semibold. Esc closes the Other… field, then the Reader, then the question; keys
  > never animate. No in-page search field — ⌘K's Inbox group lands in STATE 1. The Sources page's Deletions render the
  > same card and Undo row.

  The Provenance-viewer paragraph's "a trailing `.inspector` on the main window" becomes "a column (`ReaderColumn`): the
  Inbox's third progressive column, and on every other page the shell's trailing column (`ShellReaderHost`), sized
  before the page so it is never pushed off-window". Add that it shows C's header (mark, title, meta, a neutral Resume
  when `isfile()` says the session is resumable), the pinned "1 of N cited here" navigator, turns in the quote face
  with `CitedSpan`, and the "Noted from this conversation" rows. A swap onto the same conversation re-lands in place
  (`ProvenanceRouter.refocus`). "Washed when quoted, bold when derived, plain when stale" stays verbatim. The dandelion
  wash is gone.
- [ ] **Step 3: TODO.md.**
  - "Where things stand" records DS-2 on `feat/d-inbox-reader`: what shipped, the rulings count, and the verified
    Swift counts.
  - "Pick up here" names the next DS tracks (Clusters, Feed, Sources, Projects adopt `ProgressiveColumns`).
  - Add the backend follow-up to the backlog's small list: `demo_bank.py` should write a removal, divergence,
    normalization and informational item, so DR-43's "the app reaches every variant through the demo bank" holds.
  - Use placeholders only; no bank contents.
- [ ] **Step 4: memory-evolution.md.**
  - **G115** gains: "DS-2 (2026-09-24): the Inbox is D's progressive columns; one tap with a 5 s send-delay Undo, so an
    undone answer never reaches the ledger."
  - **G118** gains: "DS-2: the Reader is a column; asserted spans wash, found mentions are semibold, in the Inbox's quote
    too."
  - Edit the rows in place (never a second row).
- [ ] **Step 5: Commit.** Stage `CLAUDE.md`, `docs/design/DESIGN_RULES.md`, `docs/goals/TODO.md` and
  `docs/goals/memory-evolution.md` only. Message:
  `docs(ds2): the Inbox and the Reader as Direction D ships them; §9 rulings (DR-27, DR-31, DR-42, DR-43, DR-46, DR-57)`.

---

## Not in scope

These are named so a reviewer does not read an absence as an oversight.

- **Other pages' bodies:** Graph and the entity card, Clusters, the Feed, Sources, Home, and Projects (PJ-5). They keep
  the shell's trailing Reader column (`ShellReaderHost`) until their DS track adopts `ProgressiveColumns`. The
  exception is the Sources page's Deletions section, which renders the Inbox's own card (R-DI16).
- **Any backend change:**
  - no `check` result and no "Check now" (G61 S3+);
  - no demo-bank items for the four kinds it lacks (a noted backend follow-up);
  - no new field, endpoint, ETag component or Store domain.
- **The evidence chip and "Where this came from" restyle.** Only `QuoteBlock`'s wash colour moves, with the dandelion's
  retirement (R-DI11).
- **The app-wide lints R-DS28 deferred:** `DividerLintTests`, app-wide `ContinuousCornerLintTests`,
  `KeyboardAnimationLintTests`, `EasingLintTests`, app-wide `ProvenanceIdLintTests`, and a UI-measured `ColumnLayoutTests`
  for DR-26. This track adds only the scoped Inbox lint and the scope growth in R-DI23.
- **The `cicada.design.focus` flag (R-DI1).**
- **⌘Z as an Edit-menu command.** It is the Undo row's button shortcut (R-DI4).
- **Persisting a held answer across a crash (R-DI4, disclosed).**
- **Image-golden snapshots at 0.8× / 1.0× / 1.4× (DR-70).** The fit tests hold the layout, and the orchestrator's live
  check holds the look.
- **The palette's Inbox rows and Home's "Needs you" rows restyle.** They route into STATE 1 unchanged.
- **The menu bar.**

---

## Verification the orchestrator runs at the end

1. **Suites.**
   - `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` succeeds.
   - `swift test 2>&1 | tail -20` reports **0 failures** (≥ 1623 executed plus the new tests). Re-run
     `SleepViewModelTests` or the search-latency tests alone if they are the only red.
   - `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` is green.
2. **Lints fail when they should.** Repeat Task 5 Step 9's two negative controls (the accent in
   `InboxQuestionList.swift`, the `lintProbe` harness in `InboxPage.swift`) and confirm each fails and then passes.
3. **Nothing retired survives.**
   - `rg -n '\.inspector\(|InboxCardView|InboxActionButton|KindChip|dandelionFill' app/CicadaApp/Sources` prints nothing
     outside `Theme/`.
   - `rg -n 'Search questions' app/CicadaApp/Sources` prints nothing.
4. **Live, on the demo bank, installed build.** Check at 1440 × 900 and 1200 × 800, with the rail and the labelled
   sidebar, at 1.0× and 1.4×, in dark and light:
   - **STATE 0:** the questions alone, with no detail pane. Rows show a real mark and "Claude Code · Aug 25"-style
     sources.
   - **STATE 1:** a click narrows the list (the drawer curve) and opens the card. The eyebrow reads
     "Inbox · 1 of N · Kind".
   - **STATE 2:** "Show in conversation" opens the Reader and the list becomes titles-only. At 1200 labelled the list
     hides and "‹ N questions" brings it back; an answer made there shows its Undo row above the card, and ⌘Z works
     (R-DI25).
   - **STATE 0 beside a Reader at 1.4×** (open one from an evidence chip, then switch to the Inbox): rows drop their
     entity and source slots rather than draw under the Reader (R-DI26).
   - **The Reader is never clipped** at the right edge, on the Inbox and beside the Graph's entity card via an evidence
     chip, at 1200 and 1.4×.
   - **Cited spans show their wash and underline** in the focus card's quote and in the Reader, and a derived mention
     shows semibold.
     - If a wash is missing only where `.textSelection(.enabled)` is applied, the macOS 26 text-selection path has
       bypassed the `TextRenderer`. In that case, drop `.textSelection` from the quote and the Reader turns in a
       follow-up commit. DR-18's wash is the requirement; selection is not.
5. **One tap plus Undo.** Watch `git -C "<demo bank>" log -1 --format='%h %s %an'` while testing:
   - Answer a conflict with one click. The Undo row appears in its place and the next question opens. **No new commit
     lands for 5 s**; one lands after, with `Cicada-Author: user`.
   - Answer, then Undo (click and ⌘Z) inside 5 s. **No commit ever lands**, and the question reopens.
   - Answer, then ⌘Q inside 5 s, and relaunch. The commit is there.
   - Answer, then switch memory bank inside 5 s. The commit lands in the demo bank, not the other.
   - Answer, then close the window. The commit lands at once.
6. **Every kind on the demo bank.**
   - **Decay:** Archive / Keep active, and Not now · L.
   - **Conflict:** Recommended first, 1–9, ⏎, O with Submit disabled until text, and the hint's Open source ↗.
   - **Clarification:** free text; Dismiss and Skip.
   - **Merge:** both fields, the survivor radios, the direction line, and Answer / Merge / Keep separate / Skip, each
     disabled until it can act.
   - **Follow-up:** options exactly as served, including "Not now — ask again in 30 days" as an option, no 7-day footer,
     and Other… with a date phrase.
7. **Keys.** 1–9, ↑/↓ (list and card), ⏎, O, L, Tab (list → question → Reader), and ⌥↑/⌥↓ / ⌥⌘[ in the Reader. Esc
   steps: Other… field → Reader → question → nothing. None of them animate.
8. **Resume.** It shows for a resumable demo conversation and hands off as today. Nothing reads a transcript.
9. **Reader states.** Gone, failed plus Try again, and the stale / grown / derived / inferred / truncated banners, each in
   words.
10. **The rest of the Reader.** The palette's Ask mode and the Belief Timeline sheet step aside when the Reader opens. A
    bank switch closes the Reader and resets the Inbox's selection.
11. **The Sources page.** A browser source's Deletions show the same card, and an answered removal shows the same Undo
    row.
12. **The `?`.** The Inbox's `?` shows "Questions waiting on you." and the key map.
13. **PR body must state:**
    - the DR ids applied, and the §9 lines added;
    - that the ETag recipes, `VersionVector.mapping` and every endpoint are **unchanged**;
    - that no price, token count or `$` appears on any surface this PR touches;
    - that the demo bank cannot show removal, divergence, normalization or informational items (R-DI21), and where they
      are tested instead.
