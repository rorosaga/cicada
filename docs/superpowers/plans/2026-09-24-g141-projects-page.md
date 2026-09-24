# G141 PJ-5 — the Projects page: a green band that fills up to today, every node clickable (Direction D) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner asked for "a good way to track 'projects' … I'd like to see graphically me today and progress
throughout the timeline", and, on the look, "maybe like a green bar that fills up? … make nodes in the timeline
clickable and stuff". The backend has served that for two days (PJ-1/2/3/6, #92/#93: `GET /projects`,
`GET /projects/{id}/timeline`, five person writes, the `followup` inbox kind). This track draws it. Projects becomes
the eighth rail page (⌘8). Its list shows every project at D density: where it stands now, a mini green bar, the next
milestone or "No plan yet", when it last moved, the people around it. A project opens beside the list:

- **The band.** A `progressFill` track fills up to a "You, today" marker. Done milestones are filled diamonds inside
  the green, planned ones are hollow on the unfilled track, and a closed `due` is slashed "passed, no word on how it
  went". Happenings are neutral dots, ongoing threads thin spans with an open cap at today (dashed once quiet), and
  there are month labels plus relative words near today. A project with no plan fills to today with an open end and
  "No plan yet — Add a milestone". Every node is a button: a click rings it and brings its row into view, hover shows
  its first words and date, ←/→ step, ⏎ opens its source in the Reader.
- **The sections.** Log progress sits above Now (ongoing threads, their follow-up linked to its Inbox card), Lately
  (one sentence per happening, every participant a chip that opens its card, a status word, a source line with "Show
  in conversation ›" into the Reader, Resume where resumable), Plan (targets, Add, Mark done, Rename, "passed, no
  word"), and Around this project (People · Tools & infrastructure, a tool expanding to its specs · Documents &
  links · Ideas · Parts of this project).
- **The Reader or a card** opens as the third column.
- **Writes.** Every write is a `Mutation` (optimistic where the result is known, rolled back with a toast), says the
  409-while-Sleep-runs message in plain words, and never sends a relative date.

**Architecture:** Every decision is a pure function with a table test; the views render what those functions return.

- **The wire:** `Project*` types (`Models/Project.swift`), lenient decoding.
- **Derived state:** `ProjectState`, a line-for-line port of `api/services/project_state.py` that runs the SAME shared
  fixture, `api/tests/fixtures/timeline_state.json`.
- **Relative words:** `ISODay` and `RelativeDay`, the one door (DR-58).
- **The data:** `ProjectsCache`, in memory, ETag-revalidated, not a Store domain (R-PJ7).
- **Pure models:** `ProjectsModel` (the list), `BandLayout` (the band), `ProjectSource` (source lines and Reader
  targets), `ProjectStory` / `ProjectPlan` / `ProjectAround` (the sections).
- **Writes:** `ProjectWrite`, one `Mutation` for the five endpoints, with `ProjectOverlay` painting its optimistic
  half.
- **Shared pieces reused, unchanged** (one exception: `ReaderColumn.act` moves onto `ResumeOutcome.toast`, R-PP26):
  DS-2's `ProgressiveColumns`, `ReaderColumn` and `CitedSpan`; DS-3c's
  `ListColumns`, `EyebrowRow`, `AdaptiveTextTabs`, `PageFind*` and `ListSkeleton`/`ListErrorCard`; DS-3a's
  `EntityDetailCard` in its `.column` style; G118's `EvidenceChip`, `QuoteBlock` and `ProvenanceCache`.
- **The fixture:** the demo scenario's real wire, generated from `demo_bank.populate(today=2026-09-23)` and pinned by
  one pytest, is every Swift test's fixture.

**No backend change**: no `api/` module is edited; the one Python file added is a test.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, macOS 14 floor, built on the macOS 26 SDK); one pytest under
`api/tests/` (test only).

**Binding sources:**

- The owner's brief for PJ-5 as the orchestrator relayed it — it overrides the spec and DESIGN_RULES where it says so
  (the sections, the tabs, the Lately groups, "Undo where the server supports withdraw").
- `docs/design/DESIGN_RULES.md` for every DR id cited, in particular §3.8 (`progressFill`), §5.3 (progressive
  columns), §6 (DR-40…DR-53), §7 (DR-54…DR-59), §8 (DR-60…DR-70), §9 (the band ruling, ⌘8) and §10 Projects.
- The owner-approved mocks `D-Projects.dc.html`, `D-Project.dc.html` and `D-Project-Reader.dc.html` (one file, three
  preview states; session scratchpad, **not committed**). Row anatomy, the band's coordinates, the section grammar and
  the third column are translated from their markup and `renderVals()`, never embedded.
- `docs/superpowers/specs/2026-09-23-g141-project-timelines-design.md` — §6 (read model), §7 (provenance), §8
  (relative dates at read), §10.1 (the wire), §11 (the app) and rulings **R-PJ4, R-PJ6, R-PJ7, R-PJ11, R-PJ13, R-PJ15,
  R-PJ21, R-PJ22**, as amended by the owner's rulings recorded in TODO.md ("G141 DECIDEs — ruled 2026-09-23") and
  DESIGN_RULES §9.
- The round-3 spec's standing rails (no prices; marks via `OriginMark`; Meadow only as §3.8's one exception).
- CLAUDE.md's rails: privacy in docs, portability, ETag ship-together (untouched here — no Store domain), Sleep-safety
  (the page's reads are engine-free server reads), provenance (spans, not copies; washed when quoted, bold when
  derived), the G117 owner resolver (the owner is `isOwner` on the wire, never a name in code).
- Prior D tracks' rulings R-DS*, R-DI*, R-DG*, R-DL* — this plan builds on them and re-opens none.

Backlog row: **G141** (this track is its slice **PJ-5**). Commits cite `G141 PJ-5` and the DR ids they apply.

---

## What the code actually does today (verified at `feat/g141-projects-page` = `dev` @ `6612efe`)

`app/…` = `app/CicadaApp/Sources/CicadaApp`. Tests live in `app/CicadaApp/Tests/CicadaAppTests/`.

### The server (read only — nothing here changes)

- `api/routers/projects.py:80-90` — `GET /projects` → `ProjectsResponse`. `:93-114` — `GET /projects/{id}/timeline`
  → `ProjectTimeline` (404 for a page that is not a live `project`). Both ETag over `entities`+`episodes`+`inbox`
  with `extra` = `projects|<PROJECT_SHAPE>|<machine zone>` (never today, never a viewer zone), answer
  `If-None-Match` with a 304, and drop the ETag while the FTS index is not `ready` or the body is `partial`
  (`_unpin_degraded`, `:67-77`), so a degraded body is never revalidated into a 304.
- `:125-128` — one write lock; the words `BUSY = "Sleep is writing this project, try again in a moment"`,
  `TWO_DAYS = "Say one day, or pick it with the date chip"`, `OUT_OF_RANGE = "That day is outside what Cicada can date
  — pick it with the date chip"`. `:136-140` — `_guard()` answers **409** with `BUSY` while a cycle runs.
- The five writes, each answering `ProjectWriteResponse {action, claimId, day, dateBasis, episodeId, claims}`:
  - `:233` `POST /projects/{id}/milestones {name, target?}`;
  - `:250` `PATCH /projects/{id}/milestones/{slug} {target?, status?, on?, name?}` — a read-compat `due-<date>` is
    promoted by its first touch; a rename is the one in-place edit;
  - `:292` `POST /projects/{id}/happenings {text, status: done|ongoing, when?}` — the Log. One time phrase in the
    words is cut out and becomes the day (basis `stated`); else `when` (the date chip, basis `person`); else today.
    Two phrases, or a vaguer time word left behind → 422 `TWO_DAYS`; a phrase out of range → 422 `OUT_OF_RANGE`;
  - `:350` `POST /projects/{id}/threads/{claimId} {status: done|ongoing|dropped, on?}`;
  - `:379` `POST /projects/{id}/withdraw {claimId}` — happenings only (a milestone is a 400).
- `api/models/schemas.py:1042-1255` — the wire types. Notable for the app:
  - `TimelineItem` (`:1083`) is `kind: moment|happening|history|created` with `day` (a local day in `tzName`), `at`,
    `dateBasis`, `state`, `via`, `project`, `text`, `facts`, `moreFacts`, `participants` (resolved: `id`, `name`,
    `type`, `role`, `surface`, `url`, `isOwner`, `derived`), `quote {episode, start?, end?, kind, status}` (no hash),
    `conversation {id?, episodeId, title, origin, harness, resumable}` and `claim` (a `ClaimModel`).
  - `MilestoneRow` (`:1102`): `slug, name, status (planned|done|missed|dropped|passed-no-word), target, doneOn, moved,
    source (milestone|due|expectedEnd), on, claimId, chain` — `chain` newest first, crossing the `due` → `milestone`
    hop. A read-compat `due`'s earlier target is its `object`.
  - `ProjectRow` (`:1182`) has no people and no last-happening text.
- `api/services/project_timeline.py:1264` — rows are sorted newest `lastMomentDay` first, undated last, then by id; a
  child can precede its parent. `:62` — cluster groups are labelled `People`, `Tools & infrastructure`, `Documents`,
  `Ideas`, `Sub-projects`, `Places & organisations`; empty groups are omitted.
- `api/services/project_state.py` — `timeline_state(input, today)`, the one derived-state function, run in Python by
  `api/tests/test_project_state.py` over `api/tests/fixtures/timeline_state.json` (five cases). Its docstring names
  the Swift twin this track writes (`ProjectState.swift`).
- `api/routers/graph.py:32` — `NODE_SHAPE = "aliases+f1-facets"`: `GraphNode` carries no `created`/`lastReferenced`
  (the spec's §10.1 cold-paint bump is a backend change, so it is reported, not made — R-PP3).

**The demo scenario's wire, measured** (a fresh `demo_bank.populate(today=2026-09-23)`, zone UTC):
- 15 projects. Six are in motion — rover, pick-and-place, alpha, beta (a child of alpha), gamma and garden — none is
  quiet, and nine synthetic ones have no activity (resting).
- Rover: `created 2026-07-15`; four milestones:
  - `arm-assembled`, done 08-09 against a 08-12 target;
  - `first-grasp`, planned 10-01, moved from the `due` of 09-09;
  - `due-2026-10-05`, "Pick And Place Demo", on the sub-project;
  - `due-2026-11-02`, "Lab showcase".
- Rover, continued:
  - two open threads: "connecting …" since 09-23, and the camera since 08-30, quiet 24 days with Q = 20;
  - one `followup` inbox item for the camera thread (`inbox-007`, whose `claimId` is the thread's);
  - `pending.unconsolidated == 1`;
  - items: happenings on 07-15, 08-09, 08-30 (ongoing), 09-22 and 09-23 (ongoing); moments on 07-22, 08-19, 09-09
    and 09-22; one `created` item.
- Garden: unplanned, three moments, Q = 43.
- `resumable` is false everywhere, since no transcript exists.
- `/graph` on the same bank has 67 nodes and **no links**: the generator writes no `graph_edges.yaml`, the only edge
  source (`api/services/graph_builder.py:614-627`). So on the demo no project has a `person` neighbour in `/graph`, and
  R-PP7's people slot is empty on every row (its unit test builds its own graph).

### The app

- **The rail** (`Views/Shell/AppTab.swift:21-28`) has seven cases in ⌘ order; `restored(from:)` (`:32-41`) maps retired
  raw values. `NavRail` draws `AppTab.allCases`, so ⌘8 comes free with an eighth case (`ShellMetrics.swift:24`
  `RailItem.digit`). `hostsOwnReader` (`:62-67`) names the pages that draw the Reader themselves.
- **Mounting.** `ContentView.swift:420-460` (`otherTabContent`) switches on the tab. `:88-92` — a bank switch closes
  the Reader and empties `provenanceCache`. `:316-320` — a palette `.entity` row opens the Graph.
- **The palette's pages** are `PaletteActions.docs` (`Search/PaletteActions.swift:26-29`), one "Go to <page>" row per
  `AppTab.allCases` with `⌘<n>` as its trailing hint — Projects is indexed automatically.
- **`?` help** (`Views/Shell/TitlebarHelp.swift:13-34`): `HelpContent.page(tab)`; list pages answer with
  `ListHelpPopover(page: ListHelp.<page>)` (`:98-158`).
- **The router** (`Support/AppRouter.swift`) has `routeToClustersEntity`/`pendingClustersEntity` (`:69`, `:169`,
  `:192`) and `pendingInboxItem` (`:167`), which `InboxPage` consumes (`Views/Inbox/InboxPage.swift:43`, `:194`).
  There is no project hand-off. A hand-off stages `pendingTab`, which `ContentView` (`:122-126`) turns into the tab.
- **Nothing projects-shaped exists yet:** no model, view or test names a project timeline. The theme already holds
  `progressFill` (`Theme/CicadaTheme.swift:251-252`, §3.8, pinned by `ThemeTokenTests.swift:164` and
  `ThemeContrastTests.swift:96-97`); `bgBadge` is the track.
- **`Claim`** (`Models/Claim.swift:88-160`) decodes no event fields (`status`, `target`, `participants`,
  `dateBasis`).
- **Writes** go through `Mutation` + `Store.perform` (`Sync/Mutations.swift:15-37`, `Sync/Store.swift:494-513`):
  optimistic, request on `any SyncAPI`, rollback plus `store.toast = failureMessage`. `MutationMemo` carries what a
  request learned (`SyncSafariTabs`, `Sync/Mutations.swift:521-535`). `FakeSyncAPI`
  (`Tests/CicadaAppTests/StoreTests.swift:49`) records writes through a private `record(_:)` (`:115`), and can park
  one (`gateWrites`, `waitForParkedWrite()`, `releaseWriteGate()`). `FakeSyncAPI` and `APIClient` are the only
  `SyncAPI` conformers, so a new requirement touches exactly those two.
- **Non-Store fetches** are `ProvenanceAPI` + `ProvenanceCache` (`Services/ProvenanceAPI.swift`,
  `Views/Provenance/ProvenanceCache.swift`): `APIClient.getConditional` (`Services/APIClient.swift:2292`; a 304 is
  `notModified`, any other non-2xx — a 404 included — throws `APIError.httpError(code, body)`) plus an ETag and
  last-known-good; `APIClient.provenancePath` (`Services/ProvenanceAPI.swift:48`) encodes an id into a path.
  `APIClient`'s `post`/`put`/`makeRequest`/`session`/`decoder` are `private` (`Services/APIClient.swift:999-1073`,
  `:2191-2285`), so a new request helper goes in an extension in that same file.
- **Keys while typing.** An ancestor's `.onKeyPress` can see a letter typed into a focused descendant `TextField` —
  so the Inbox's card guards O / L / 1–9 with `field == nil` (`Views/Inbox/InboxFocusCard.swift:104-121`) rather
  than trust the field to swallow them.
  Plain ⏎ in a field stays on `onSubmit`; ⌘⏎ is read with `.onKeyPress` on the field itself
  (`Views/Find/FindPanelBody.swift:82-88`, `Search/FindKeymap.swift`).
- **Resume** is `ConversationsViewModel.resume(_:)` (`ViewModels/ConversationsViewModel.swift:132`), which returns a
  `ResumeOutcome`; the Reader words it in `ReaderColumn.act` (`Views/Provenance/ReaderColumn.swift:132-139`).
- **The undo window** is `CicadaTiming.undoWindow` (5 s, `Theme/CicadaTiming.swift:18`).
- **Lints this track must satisfy:** `FontLiteralLintTests`, `CountLiteralLintTests` (a named scope, `:40-55`),
  `SelectionTintLintTests` (a named file list), `ElevationLintTests`, `SectionLabelLintTests`,
  `HiddenShortcutLintTests` (⌘K/⌘F only), `AccentSourceLintTests` and `MeadowPlacementLintTests`.

**Baselines on this base:** Swift **0 failures** (the brief's figure is 1623 executed; the suite at `6612efe` holds
about 1,950 `func test…`, and a trial run of this plan's code executed 1,999 — this track adds 47); graph node tests
green; backend untouched. The bar is 0 failures and no test lost, not a particular count.

---

## Global Constraints

**Where you work.**

- Work ONLY in `<worktree>` = `<repo>/.worktrees/pj5`, on branch `feat/g141-projects-page` (based on `dev` @
  `6612efe`). `<repo>` is the repository root; the orchestrator's brief gives both absolute paths, and every command
  below spells `<worktree>` out in full when you run it. The path is not written here: an author-machine path in a
  public repo is a portability defect (CLAUDE.md).
- Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks a relative `cd`; ignore its
  stderr warning). Never `grep --include=*.ext` (zsh globs it) — use `rg`.
- The worktree has no `api/.venv`. Python runs as `<repo>/api/.venv/bin/python -m pytest …` **from `<worktree>`** (so
  the worktree's `api` package is the one imported).

**What you never touch.**

- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`. Every fixture is
  the synthetic demo scenario (`bob-example`, `hana-example`, `rover-arm-project`, `example.com`).
- **No backend change.** No file under `api/` except the one new test in Task 1. If a field you need is missing,
  stop and say so.
- **Do not edit** `Views/Graph/EntityDetailCard.swift` (DS-3a's; hosted as it is) or the Inbox's views.

**How you verify.**

- `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed; `swift test 2>&1 | tail -20` must report
  **0 failures** (≥ 1623 executed plus this track's tests). `SleepViewModelTests` poll tests and the search-latency
  tests can flake under load — re-run them alone before calling one yours. SourceKit diagnostics naming OTHER
  worktrees are noise.
- `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` (pass the glob) stays green (untouched).
- NEVER run `make dev`, `make install-app` or `swift run`, and never launch or kill the Cicada app or the launchd
  backend. The owner's installed app is live; the orchestrator installs and live-checks at the end.

**Git.**

- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv` or
  `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin and PR comments.
- End every commit message with the attribution lines your session's system reminder names. Each commit cites
  `G141 PJ-5` and the DR ids it applies.

**Tokens, type and motion (DESIGN_RULES).**

- Colours only from `CicadaTheme`. The one hue on the band is `progressFill` (§3.8); nodes are shapes in the text
  ladder; selection is a `textPrimary` ring (band) or `bgSelected` (rows), never the accent (DR-5, DR-22). The accent
  appears only as links (`InlineLink`, `accentText`), the focus ring and a cited span.
- Every size goes through `CicadaTheme.font(size:weight:)` or a named token, and every dimension through
  `CicadaTheme.scaled(_:)` (DR-70). Semibold only where DR-16 allows (the H1); the band's labels are regular/medium.
- Every rounded rectangle through `CicadaTheme.shape(_:)` (DR-12); depth is a ring (`.ringed`), never a shadow
  outside `Theme/` (DR-9/DR-10); no `Divider()` (DR-11).
- Durations only from `CicadaMotion` / `CicadaTiming`. A keyboard action never animates (DR-60): wrap it in
  `Instant.run { }`.
- Every count goes through `UsageFormat.count` (DR-21; `CountLiteralLintTests` gains this track's paths). A view
  never writes `Text("…\(n)…")` — words are composed in `Copy.Projects` or a pure model.

**Copy.**

- Plain, friendly, sentence case; no "!", no bare "%", no prices or token counts (DR-59). Ids, slugs, episode ids
  and paths appear only in `.help` or an accessibility label (DR-54).
- A service is named with its real mark through `OriginMark` (DR-52).
- Relative day words ("Today", "Yesterday", "Tomorrow", "in 8 days", "3d") come ONLY from `RelativeDay`
  (`RelativeDayTests`' lint, DR-58).
- New words live in `Theme/Copy+Projects.swift` (Task 1), never in `Copy.swift`.

**Docstrings** explain WHY, citing the DR id, this plan's ruling (R-PP*), a G141 spec ruling (R-PJ*) or a prior
track's ruling. Match the density of the files you touch. Line numbers above are from `6612efe` and drift as tasks
land — read the cited code before editing.

**Test snippets.** "Append to `XTests.swift`" means inside that file's existing test class, before its closing
brace. The package is Swift 5 language mode; a test that builds a `Store`, a cache or a view model is `@MainActor`.

---

## Rulings (binding)

Each ruling is a decision this plan takes where the brief, the spec or the mock left a choice, with its reason, so no
task re-opens it. Those marked **§9** are dated in DESIGN_RULES §9 by Task 6.

- **R-PP1 — §9 — No `cicada.design.focus` flag (DR-73).** R-DS1's reasons hold unchanged; comparison is the installed
  build against the branch on a freshly generated demo bank.
- **R-PP2 — The wire decodes into local `Project*` types, leniently; the shared `Claim` does not grow event fields.**
  - **Lenient:** a missing or mistyped key takes its default (the house rule for a new wire), so a server one field
    ahead or behind never blanks the page.
  - **`ProjectClaim`** is the subset the page reads: status, target, date basis, origin, evidence, validity.
  - **Why not the shared `Claim`:** its readers (the belief rows, the palette, the card) would then render events.
    That is spec §10.2's "day · status · sentence" work, outside this brief, and reported.
- **R-PP3 — `/projects` is not a Store domain (R-PJ7).**
  - **`ProjectsCache`** is one per app (`@State` in `CicadaApp`, beside `ProvenanceCache`). It is in memory,
    revalidated with the server's ETag, and keeps last-known-good. `reset()` on a bank switch bumps an epoch, so an
    answer in flight across the switch is dropped.
  - **When it asks again:** when the page appears, when a project opens, after every write, and when a sync version
    event moves `entities`, `episodes`, `inbox` or `bank` (`ProjectsRefresh`) — the components both ETags fold.
  - **No `VersionVector` mapping and no disk cache**, so the ship-together rule has nothing to pair. The first open
    after a launch shows the skeleton.
  - **No cold paint from `/graph`:** `GraphNode` has no dates, and the spec's `NODE_SHAPE` bump is a backend change
    (reported).
- **R-PP4 — `ProjectState` is `project_state.py` line for line and runs the shared fixture (R-PJB17).** It is the
  QuickMatch/`text_fold` precedent: two languages, one table, so the app and `cicada_project` never disagree about
  whether a thread is quiet.
  - **A thread reads quiet** once `quietDays > quietThreshold` — the section's own rule, `idle <= q` → in motion.
  - **Its follow-up** is offered only when the Inbox holds one for its claim (R-PP18).
- **R-PP5 — `RelativeDay` is the one door for relative words (DR-58, spec §8).**
  - **`ISODay`** is whole-day arithmetic with no zone (Hinnant's days-from-civil). "24 days" is therefore 24 across a
    DST change, and the numbers match Python's `date` arithmetic.
  - **"Today"** is read from the viewer's calendar, and `.NSCalendarDayChanged` re-derives every word with no network.
    The server never sends today, and the ETag does not move at midnight.
  - **A lint** keeps "Today" / "Yesterday" / "Tomorrow" literals to `RelativeDay.swift` across this track's files.
- **R-PP6 — The tabs are Active · Quiet · All (the brief and the mock).**
  - **What each shows.** Active is `inMotion` and Quiet is `quiet` (`ProjectState.Section`). A resting project shows
    only under All.
  - **The default.** The page opens on Active unless Active is empty, then All.
  - **Tapping the active tab** returns to All (DR-45).
  - **A tab is navigation:** a project the chosen tab does not show closes (R-DL6).
  - **The eyebrow** is the brief's "Projects · N", naming the tab when one narrows the list ("Projects · 6 active",
    the mock), and "Projects · 1 of 6 · Planned" with a project open.
- **R-PP7 — A row, at the mock's density.**
  - **Wide (36 pt):** the project dot, the name (220), where it stands now, the 64 pt mini bar, the next milestone or
    "No plan yet" (200), the people (64), "1 question" (74) and the compact age (40), then the chevron.
  - **Triage (56 pt, two lines):** the name and the age; then a 40 pt bar and "1 of 4 done · First grasp Oct 1".
  - **Titles (36 pt):** the name.
  - **"Where it stands now"** is a ladder, the first rung that holds: the newest live thread's sentence → "Quiet 24
    days · <the quiet thread>" → a quiet project's "Quiet N days" → a resting one's "Resting · last heard Sep 14"
    (or "Nothing heard yet") → the one-liner → "Last heard <day>".
  - **Sub-projects** sit indented under a visible parent, and flat when the parent is not shown.
  - **The people** are the `person` neighbours of the project node in the Store's `/graph` snapshot. The owner and
    facets are left out; at most three, by degree then name, as initials in a neutral circle. `ProjectRow` carries no
    people, and this uses data the app already holds rather than a new field (reported). A person has no service mark,
    so DR-52 does not apply. A row with no person neighbour draws an empty slot — every row on the freshly generated
    demo bank, whose `/graph` has no edges; a bank Sleep has run on has them.
- **R-PP8 — `partial` is said in words.** While the server says `partial: true`, the eyebrow ends "· still indexing",
  with its reason in `.help`. The detail says it under Around this project.
- **R-PP9 — §9 — One bar geometry and one new token (§3.8).**
  - **`ProgressSpan` feeds both** the mini bar and the band, so they never disagree about how full a project is.
  - **It starts** at the earliest of `created`, the moments and the targets.
  - **It ends:** with a plan, at the latest target when that is after today, else a week past today; with no plan, a
    week past today and an open end. That is the mock's `bounds`.
  - **The fill runs to today.**
  - **The open end is `CicadaTheme.progressOpenEnd`** (white 22 % / black 22 %, the mock's dash). §3.8 says "a dashed
    open end" and names no token, so it joins §3.8's table.
- **R-PP10 — The band, in the mock's coordinates.**
  - **The frame** is 112 units with a 14-unit side inset. The track is at 22–32, the lanes are centred at 27 (track), 43
    (below) and 13 (above), thread rows at 56 and 68, month ticks at 80, month labels at 86 and the words near today
    at 100.
  - **Drawing.** A `Canvas` draws the track, the fill, the open end, the ticks, the brackets and the today marker.
    Every node is a real `Button` above it.
  - **Lanes, deterministically:**
    - milestones own the track;
    - a happening prefers the track, and a moment or a history bullet prefers below;
    - a neighbour within 12 units pushes a mark to the next lane;
    - a fourth mark crowding one spot folds into its neighbour's "+N more here".
  - **Threads.** At most two thread rows. An ongoing happening is a thread, never a dot.
  - **A long window** (more than 540 days) keeps the last 365 and folds the rest into one "N earlier" mark.
  - **Words near today:** months, plus "2 weeks ago" / "in 2 weeks" ("a month ago" past 180 days) between 8 % and 94 %
    of the width.
  - **Labels.** The next milestone's name and distance sit above its diamond, hidden when it would collide with "You,
    today". "You, today" is 11 medium, not semibold (DR-16).
- **R-PP11 — One selection, shared by the band and the sections.**
  - **The key.** A `ProjectKey` (item / thread / milestone) rings the band's node and marks the section row.
  - **A pick from the band** opens that row's section if it was collapsed and scrolls the row into view (DR-30),
    instantly (DR-60).
  - **The mock "folds" the sections above instead; this does not.** A folded story hides the context a reader came
    for, and a scroll keeps it.
  - **Keys.** ←/→ step the band's order; ⏎ opens the selection's source in the Reader.
  - **With the Reader open,** a pick that cites the same conversation re-lands it (`ProvenanceRouter.refocus`), and
    any other pick closes it (DR-29).
- **R-PP12 — §9 — The band never says "Timeline" (R-PJ22).** The card's Timeline tab (contested beliefs) can share the
  screen in the third column, so the band's label is "Progress of <project>". A lint holds every string literal under
  `Views/Projects/` and in `Copy+Projects.swift` to that.
- **R-PP13 — The sections are Now · Lately · Plan · Around this project, with Log progress above them** (the mock's
  order, the brief's list).
  - **Collapsible,** each remembered per viewer (`cicada.projects.collapsed`, DR-39).
  - **Not built:** the spec's Conversations list and "Where this came from" (§11.3 items 8–9). Every row already
    carries its own source line and the Reader, and the brief does not ask for them (reported).
- **R-PP14 — Lately's headers are Today · Yesterday · This week · Earlier (the brief).**
  - **This week** is 2–6 days back, a rolling week, so a Monday's This week is never empty.
  - **Dates.** A row's date is absolute ("Sep 22"), with the full date in `.help`; the header carries the relative
    word.
  - **The `created` item** is the section's foot line, "Cicada started tracking this · Jul 15".
- **R-PP15 — One sentence per happening, every participant a chip (R-PJ15).**
  - **Where the chips go.** A participant's `surface` (else its name) is linked where the sentence says it, first
    non-overlapping occurrence. One the sentence never names follows it as a chip. An unlinked name stays words.
  - **Layout.** `SentenceFlowLayout` lays the sentence out word by word, so a chip wraps with the sentence rather than
    breaking it. Punctuation right after a chip rides with it.
  - **The owner** reads as the sentence's own word with a small "you" tag, and opens nothing (the mock). A literal
    "You" would break the sentence ("You is connecting"), and the tag is the owner's own "[user]" made visual.
  - **Every other chip** opens that entity's card in the third column.
- **R-PP16 — §9 — Where a row came from, said once (DR-54, DR-55, DR-57).**
  - **The source line:**
    - a conversation reads as its origin's real mark, then "<App> · <title>", its `EvidenceChip` (who spoke and the
      day) and "Show in conversation ›";
    - a Log note reads "Your note in Cicada";
    - an app-set milestone reads "Set by you in Cicada" — DR-57's sixth label, but as a source line, not a chip, so
      `EvidenceChip` is untouched;
    - a history bullet reads "From the page's history — no source sentence";
    - nothing reads `[ no source recorded ]`.
  - **The Reader's target, in order:**
    - the claim's own span, with its hash, so the server can say grown or stale;
    - else the quote's offsets (the quote carries no hash — reported);
    - `.stale` for a stale quote;
    - bold, never washed, for a derived one.
- **R-PP17 — The third column is the Reader or an entity card, one slot (spec §11.3 item 7).**
  - **The card** is `EntityDetailCard` in its `.column` style, with Clusters' "go deeper, then come back" trail.
  - **Esc** closes the Reader, then the card, then the project (DR-28).
  - **Who opens what.** A chip opens the card and closes the Reader; a Reader opened from inside the card returns to
    it on close.
  - **Projects open themselves.** A project's card offers "Open project ›". "Parts of this project" rows and the "Part
    of <parent> ›" breadcrumb open the project itself — it is a destination on this page.
- **R-PP18 — §9 — A quiet thread's follow-up is a link to its Inbox card, not options inline (the brief).** When the
  Inbox holds a `followup` for the thread's claim, the row shows "How did it go? ›" (`AppRouter.routeToInboxItem`) in
  place of its three buttons. The Inbox owns answering and its Undo (DR-42), and a question is stated once (DR-59).
  The mock's inline options are not built.
- **R-PP19 — Writes are `ProjectWrite` mutations run by `Store.perform`.**
  - **Optimistic** (`ProjectOverlay` on `ProjectsCache`) where the result is known: a thread settled or restated, a
    milestone done, renamed or added, a withdrawal.
  - **Not optimistic for the Log:** the server decides its day.
  - **Rollback** plus a toast on failure; then the cache revalidates.
  - **The failure words** are a 409's or a 422's own `detail` — plain words `routers/projects.py` writes for the
    person — else this page's own. Never a 400's or a 404's detail, which names ids (DR-54).
- **R-PP20 — While Sleep runs, every write control is disabled with its reason in `.help` (DR-41).** The check is
  `status.sleep.status == "running"`, the server's own 409 condition. A race still gets the 409 toast.
- **R-PP21 — §9 — Log progress is one line, dated by the server.**
  - **Keys.** ⏎ saves it as done; ⌘⏎ as still going.
  - **The day** comes from the words (`when.py`, the one date grammar), else the date chip (a native `DatePicker`
    capped at today, sent as `YYYY-MM-DD`), else today. The chip exists because the server's own 422 words say "pick
    it with the date chip".
  - **After saving:** "Logged on <project> for Sep 22 (yesterday) — dated from your words", with Undo for
    `CicadaTiming.undoWindow`.
  - **Undo withdraws.** It is not DR-42's send delay: the day must come back from the server before it can be shown.
    The companion note stays — it is the person's own words, and withdrawing only takes the claim back.
- **R-PP22 — §9 — The Plan's writes: Add a milestone (a name, plus a date from a native `DatePicker`, optional), Mark
  done (today), Rename (inline, ⏎ saves, Esc cancels).**
  - **Nothing is typed as a date.** Python decides every date from words (R-PJ6), and a second date grammar in the app
    would drift. The mock's "Demo dry run by Oct 1" is not parsed.
  - **No Move.** It is a later refinement; a moved milestone's chain ("moved once ›") still shows.
  - **The words:**
    - a closed `due` reads "passed, no word on how it went";
    - overdue reads "Overdue since Sep 20";
    - a sub-project's milestone adds "on <name>" when its name differs.
- **R-PP23 — L / M / D are key presses on the focused detail column, not menu commands.** This is the Inbox's O / L
  precedent (`InboxFocusCard.swift:104-113`). A bare-letter menu key equivalent would fire while typing in the Log
  field. DR-68 already lists the keys for Projects; `HiddenShortcutLintTests` is about ⌘K/⌘F and is unaffected.
  - **Never while typing.** Like the Inbox's `field == nil`, each key is ignored while the Log field is focused or a
    Plan field (Rename, Add a milestone) is open — otherwise typing "d" in the Log would mark a milestone done.
  - **Where the keys come from.** The detail column takes them when ⏎ steps in from the list (`focusDetail`, DR-68)
    or a band mark is clicked (the band takes focus, so ←/→ walk on from the clicked mark).
- **R-PP24 — Entry points:**
  - the rail (⌘8);
  - ⌘K's "Go to Projects" (automatic from `AppTab.allCases`);
  - a ⌘K entity row whose node is a project, which lands in STATE 1 (`AppRouter.routeToProject`, spec §11.1);
  - the breadcrumb and the "Parts of this project" rows.
  - **Not built:** Home's "In motion" and the Graph card's "Open project ›" (DS-3a's file), both reported.
- **R-PP25 — "Not right" on a happening.** An expanded Lately happening offers it (`POST …/withdraw`, happenings only,
  R-PJB28). A moment has no claim of its own to withdraw, so it offers nothing.
- **R-PP26 — Resume where `conversation.resumable && conversation.id != nil`, through `ConversationsViewModel.resume`.**
  - **The check** is `isfile()` only; a gone transcript says so in words.
  - **One wording.** `ResumeOutcome.toast` becomes the wording the Reader and this page share.
- **R-PP27 — The fixture is the demo's real wire.**
  - **What:** `app/CicadaApp/Tests/fixtures/projects-demo.json`, generated by `api/tests/test_projects_app_fixture.py`
    from a fresh demo bank with today pinned (T = 2026-09-23, zone UTC).
  - **The pin:** the test fails on any byte of drift. It is a test only, with no `api/` module change — the
    `video_urls.json` precedent.
  - **Who reads it:** every Swift test that needs a wire.

---

## File map

`app/…` = `app/CicadaApp/Sources/CicadaApp`; tests in `app/CicadaApp/Tests/CicadaAppTests/`.

| File | Task | Responsibility |
|---|---|---|
| `app/…/Models/Project.swift` (new) | 1 | the wire (`ProjectsResponse`, `ProjectRow`, `ProjectTimeline`, `ProjectItem`, `ProjectMilestone`, …), `KeyedDecodingContainer.lenient` |
| `app/…/Models/ProjectState.swift` (new) | 1 | `ProjectState` — `project_state.timeline_state` in Swift |
| `app/…/Models/RelativeDay.swift` (new) | 1 | `ISODay`, `RelativeDay` (the one door for relative words) |
| `app/…/Services/ProjectsAPI.swift` (new) | 1 | `ProjectsAPI` + `APIClient` conformance (the two reads) |
| `app/…/Views/Projects/ProjectsCache.swift` (new) | 1, 5 | `ProjectsCache`, `ProjectsRefresh` (1); `ProjectOverlay` (5) |
| `app/…/Theme/Copy+Projects.swift` (new) | 1 | every word on the page |
| `api/tests/test_projects_app_fixture.py` (new), `app/CicadaApp/Tests/fixtures/projects-demo.json` (generated) | 1 | the shared wire fixture and its pin |
| `app/…/Views/Shell/AppTab.swift`, `NavRail.swift`, `TitlebarHelp.swift`, `Support/AppRouter.swift`, `ContentView.swift`, `CicadaApp.swift`, `Theme/ZoomKeyRouter.swift` (doc only) | 2 | ⌘8, help, the hand-offs, mounting, the cache |
| `app/…/Theme/CicadaTheme.swift` | 2 | `progressOpenEnd` |
| `app/…/Views/Projects/ProjectsModel.swift`, `ProjectsPage.swift`, `ProjectsRows.swift`, `ProjectDetailColumn.swift` (new) | 2–5 | the list's model, the page, the rows and mini bar, the detail column |
| `app/…/Views/Projects/ProjectBand.swift` (new) | 3 | `ProjectKey`, `BandLayout`, `ProjectBandView`, `BandMark` |
| `app/…/Views/Projects/ProjectSource.swift` (new) | 3 | source lines, Reader targets, the evidence index |
| `app/…/Views/Projects/ProjectStory.swift`, `ProjectSentence.swift`, `ProjectSections.swift`, `ProjectEntityColumn.swift` (new) | 4 | the sections' models and views, the third column |
| `app/…/ViewModels/ConversationsViewModel.swift`, `Views/Provenance/ReaderColumn.swift` | 4 | `ResumeOutcome.toast` |
| `app/…/Sync/SyncAPI.swift`, `Services/APIClient.swift`, `Sync/ProjectMutations.swift` (new), `Views/Projects/ProjectLogField.swift` (new) | 5 | the five writes |
| Tests (new) | 1–5 | `ProjectFixtures`, `ProjectWireTests`, `ProjectStateTests`, `RelativeDayTests`, `ProjectsCacheTests`, `ProjectsListTests`, `ProjectBandTests`, `ProjectStoryTests`, `ProjectWritesTests` |
| Tests (edited) | 2–5 | `SidebarTabTests`, `NavRailTests`, `CommandBarTests`, `ListColumnsTests`, `TitlebarHelpTests`, `CountLiteralLintTests`, `SelectionTintLintTests`, `StoreTests` (`FakeSyncAPI`). The router's two new hand-offs are tested in `ProjectsListTests`, so `AppRouterTests` is untouched. |
| Docs | 6 | `CLAUDE.md`, `docs/design/DESIGN_RULES.md` (§3.8, §5.2, DR-25, DR-57, §9), `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (G141) |

---

### Task 1: The wire, its derived state, relative days and the cache — no UI (R-PP2…R-PP5, R-PP27; R-PJ6, R-PJ7, R-PJ13; DR-21, DR-58)

Everything later tasks draw stands on this: the demo's real wire as a fixture, decoded leniently; the server's one
derived-state function in Swift, proven against the shared table; the one door for relative words; and an in-memory
cache that revalidates with the server's ETag. Nothing is on screen yet, so the branch stays shippable.

**Files:**
- Create: `api/tests/test_projects_app_fixture.py`; `app/CicadaApp/Tests/fixtures/projects-demo.json` (generated by
  it); `app/…/Models/Project.swift`, `ProjectState.swift`, `RelativeDay.swift`; `app/…/Services/ProjectsAPI.swift`;
  `app/…/Views/Projects/ProjectsCache.swift`; `app/…/Theme/Copy+Projects.swift`.
- Test: `ProjectFixtures.swift` (helper), `ProjectWireTests.swift`, `ProjectStateTests.swift`, `RelativeDayTests.swift`,
  `ProjectsCacheTests.swift` (all new).

**Interfaces:**
- Produces: `KeyedDecodingContainer.lenient`; the `Project*` wire types; `ProjectState` (`Input`, `Output`, `Section`,
  `ThreadState`, `MilestoneState`, `state(_:today:)`, `milestoneState(_:today:)`, `medianGap`, `quietThreshold`);
  `ISODay`; `RelativeDay` (`phrase`, `absolute`, `spoken`, `weekday`, `month`, `distance`, `compactAge`, `group`,
  `title`, `bandWords`); `ProjectsAPI`; `ProjectsCache` (`list`, `listPhase`, `timelines`, `phase(_:)`,
  `display(_:)`, `refreshList()`, `refreshTimeline(_:)`, `reset()`); `ProjectsRefresh.shouldRevalidate`;
  `Copy.Projects`.
- Consumes: `APIClient.getConditional` / `provenancePath`, `Conditional`, `Evidence`, `EntityType`, `UsageFormat`,
  `Eyebrow`, `api/tests/_demo_scenario.py` (`demo`, `T`).

- [ ] **Step 1: The fixture's pin, and the fixture.** Create `api/tests/test_projects_app_fixture.py`:

```python
"""G141 PJ-5 — the app's Projects fixture IS the server's wire on the demo scenario (R-PP27).

Every Swift test of the Projects page (decode, `ProjectState`, the band, the story) reads
`app/CicadaApp/Tests/fixtures/projects-demo.json`. This test regenerates the same payloads from a
fresh demo bank with `today` pinned (spec §12) and fails on any byte of drift — the
`video_urls.json` / `timeline_state.json` precedent: two languages, one table, so the app can never
be tested against a wire the server no longer sends. Synthetic only: demo fiction on example.com.

After a deliberate wire change, rewrite it: `CICADA_WRITE_APP_FIXTURE=1 python -m pytest <this file>`.
"""
import json
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from _demo_scenario import T, demo
from api import config, main
from api.services import bank_index, handshake

FIXTURE = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures" / "projects-demo.json"
PROJECTS = ("rover-arm-project", "pick-and-place-demo", "garden-sensor-project")
# A follow-up's question and its options' age phrases are synthesised at read from the real clock (spec §9: "last
# heard 4 weeks ago"), so only the fields that never move are pinned — the ones the app joins a thread on.
FOLLOWUP_KEYS = ("id", "kind", "requiredInput", "status", "title", "entityId", "entityName", "claimId", "predicate",
                 "createdDate")


def _wire(tmp_path, monkeypatch) -> dict:
    bank = demo(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        return {
            "today": T.isoformat(),
            "projects": c.get("/projects").json(),
            "timelines": {pid: c.get(f"/projects/{pid}/timeline").json() for pid in PROJECTS},
            "followup": {k: v for k, v in next(i for i in c.get("/inbox").json() if i["kind"] == "followup").items()
                         if k in FOLLOWUP_KEYS},
        }
    finally:
        config.get_settings.cache_clear()


def test_the_app_fixture_is_the_demo_wire(tmp_path, monkeypatch):
    text = json.dumps(_wire(tmp_path, monkeypatch), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("CICADA_WRITE_APP_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "the app's fixture drifted from the demo wire — rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate change")


def test_the_fixture_is_synthetic():
    """Privacy (CLAUDE.md): demo fiction only, every URL on example.com, no machine path."""
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2].endswith("example.com"), url
```

Generate it, then prove the pin holds:

```
cd <worktree> && CICADA_WRITE_APP_FIXTURE=1 <repo>/api/.venv/bin/python -m pytest api/tests/test_projects_app_fixture.py -q -p no:cacheprovider
cd <worktree> && <repo>/api/.venv/bin/python -m pytest api/tests/test_projects_app_fixture.py -q -p no:cacheprovider
```

Expected: `2 passed` both times, and `app/CicadaApp/Tests/fixtures/projects-demo.json` exists (~85 KB; generating it twice gives identical bytes). Open it and
check by eye that it names only demo fiction (`bob-example`, `hana-example`, `rover-arm-project`, …).

- [ ] **Step 2: Failing Swift tests.** Create `ProjectFixtures.swift` (a helper, not a test case):

```swift
import Foundation
import XCTest
@testable import CicadaApp

/// G141 PJ-5 (R-PP27) — the demo scenario's wire, generated from a fresh `demo_bank.populate(today=2026-09-23)` by
/// `api/tests/test_projects_app_fixture.py`, which also fails on any drift. Synthetic only (spec §12).
enum ProjectFixtures {
    struct Wire: Decodable {
        let today: String
        let projects: ProjectsResponse
        let timelines: [String: ProjectTimeline]
        let followup: InboxItem
    }

    static let today = ISODay(year: 2026, month: 9, day: 23)

    /// Resolved from THIS file's own path (`ThemeTokenTests.swiftSources()`'s rule), never a caller's `#filePath`:
    /// …/Tests/CicadaAppTests/ProjectFixtures.swift → …/Tests/fixtures/projects-demo.json.
    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/projects-demo.json")

    static func load(file: StaticString = #filePath, line: UInt = #line) throws -> Wire {
        let wire = try JSONDecoder().decode(Wire.self, from: Data(contentsOf: url))
        XCTAssertGreaterThanOrEqual(wire.projects.projects.count, 3,
                                    "read \(url.path) — a test over no projects passes vacuously", file: file, line: line)
        return wire
    }

    static func timeline(_ id: String) throws -> ProjectTimeline { try XCTUnwrap(load().timelines[id]) }
    static func row(_ id: String) throws -> ProjectRow { try XCTUnwrap(load().projects.projects.first { $0.id == id }) }
}
```

  Create `ProjectWireTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP2 — the Projects wire decodes whole from the demo's real payloads, and leniently from a sparse one.
final class ProjectWireTests: XCTestCase {
    func testTheListDecodes() throws {
        let wire = try ProjectFixtures.load()
        XCTAssertEqual(wire.projects.tzName, "UTC")
        XCTAssertFalse(wire.projects.partial)
        let rover = try ProjectFixtures.row("rover-arm-project")
        XCTAssertEqual(rover.name, "Rover Arm Project")
        XCTAssertEqual(rover.children, ["pick-and-place-demo"])
        XCTAssertTrue(rover.planned)
        XCTAssertEqual(rover.progress, ProjectProgress(done: 1, total: 4))
        XCTAssertEqual(rover.followups, 1)
        XCTAssertEqual(rover.openThreads.count, 2)
        XCTAssertEqual(try ProjectFixtures.row("pick-and-place-demo").parent, "rover-arm-project")
        XCTAssertFalse(try ProjectFixtures.row("garden-sensor-project").planned)
    }

    func testATimelineDecodesItsItemsParticipantsAndChain() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        XCTAssertEqual(t.project.created, "2026-07-15")
        XCTAssertEqual(t.pending.unconsolidated, 1)
        let guide = try XCTUnwrap(t.items.first { $0.kind == "happening" && $0.day == "2026-09-22" })
        XCTAssertEqual(guide.claim?.status, "done")
        XCTAssertEqual(guide.dateBasis, "stated")
        XCTAssertEqual(guide.participants.first?.isOwner, true)
        XCTAssertEqual(guide.participants.first { $0.role == "document" }?.url,
                       "https://example.com/guides/lab-cluster-onboarding.pdf")
        XCTAssertEqual(guide.participants.first { $0.role == "from" }?.type, .person)
        XCTAssertEqual(guide.conversation?.origin, "telegram")
        XCTAssertEqual(guide.quote?.kind, "user")
        let grasp = try XCTUnwrap(t.milestones.first { $0.slug == "first-grasp" })
        XCTAssertTrue(grasp.moved)
        XCTAssertEqual(grasp.chain.map(\.predicate), ["milestone", "due"])
        XCTAssertEqual(grasp.chain.last?.object, "2026-09-09")
        XCTAssertEqual(grasp.chain.first?.origin, "companion_app")
        XCTAssertEqual(t.cluster.groups.map(\.label), ["People", "Tools & infrastructure", "Documents", "Sub-projects"])
        XCTAssertTrue(t.items.contains { $0.kind == "created" })
    }

    func testTheFollowupNamesItsThread() throws {
        let wire = try ProjectFixtures.load()
        XCTAssertEqual(wire.followup.kind, .followup)
        XCTAssertEqual(wire.followup.claimId,
                       try ProjectFixtures.row("rover-arm-project").openThreads.first { $0.since == "2026-08-30" }?.claimId)
    }

    /// A server one field behind never blanks the page: every key is optional-with-default.
    func testASparsePayloadStillDecodes() throws {
        let row = try JSONDecoder().decode(ProjectRow.self, from: Data(#"{"id":"alpha-project","name":"Alpha"}"#.utf8))
        XCTAssertEqual(row.openThreads, [])
        XCTAssertEqual(row.progress, ProjectProgress())
        XCTAssertFalse(row.planned)
        let item = try JSONDecoder().decode(ProjectItem.self, from: Data(#"{"kind":"moment","id":"m:1","participants":[{"name":"X","type":"not-a-type"}]}"#.utf8))
        XCTAssertEqual(item.participants.first?.type, .unknown)
        let write = try JSONDecoder().decode(ProjectWriteResponse.self, from: Data(#"{"action":"created"}"#.utf8))
        XCTAssertNil(write.claimId)
    }
}
```

  Create `ProjectStateTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP4 / R-PJB17 — `ProjectState` and `project_state.timeline_state` run ONE table,
/// `api/tests/fixtures/timeline_state.json`: add a rule on one side only and the other goes red.
final class ProjectStateTests: XCTestCase {
    private struct Case: Decodable {
        let name: String
        let today: String
        let input: ProjectState.Input
        let expected: ProjectState.Output
    }

    private func cases() throws -> [Case] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/timeline_state.json")
        let cases = try JSONDecoder().decode([Case].self, from: Data(contentsOf: file))
        XCTAssertGreaterThanOrEqual(cases.count, 5, "read \(cases.count) cases from \(file.path) — vacuous below 5")
        return cases
    }

    func testTheSharedFixture() throws {
        for c in try cases() {
            XCTAssertEqual(ProjectState.state(c.input, today: try XCTUnwrap(ISODay(c.today))), c.expected, c.name)
        }
    }

    /// The demo's live wire agrees with §12's expected values after PJ-3.
    func testTheDemoRoverReadsAsTheServerSaysIt() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let s = ProjectState.state(ProjectState.Input(t), today: ProjectFixtures.today)
        XCTAssertEqual(s.quietThreshold, 20)
        XCTAssertEqual(s.section, .inMotion)
        XCTAssertEqual(s.progress, ProjectProgress(done: 1, total: 4))
        XCTAssertEqual(s.next, "first-grasp")
        let camera = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" })
        XCTAssertEqual(s.thread(camera.claimId)?.quietDays, 24)
        XCTAssertEqual(s.thread(camera.claimId)?.followupEligible, true)
        XCTAssertTrue(s.isQuiet(camera.claimId))
        let garden = ProjectState.state(ProjectState.Input(try ProjectFixtures.timeline("garden-sensor-project")),
                                        today: ProjectFixtures.today)
        XCTAssertFalse(garden.planned)
        XCTAssertEqual(garden.quietThreshold, 43)
    }
}
```

  Create `RelativeDayTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP5 / DR-58 — every relative word on the Projects page is computed at read, here, from an absolute day.
final class RelativeDayTests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let t = ISODay(year: 2026, month: 9, day: 23)   // a Wednesday

    func testISODayIsWholeDays() {
        XCTAssertEqual(ISODay("1970-01-01")?.ordinal, 0)
        XCTAssertEqual(ISODay("2026-09-23"), t)
        XCTAssertEqual(ISODay("2026-09-23T16:04:00Z"), t, "an instant's day part parses")
        XCTAssertEqual(t - ISODay(year: 2026, month: 8, day: 30), 24)
        XCTAssertEqual(t.adding(8).description, "2026-10-01")
        XCTAssertEqual(ISODay("2024-02-29")?.adding(365).description, "2025-02-28")
        XCTAssertEqual(ISODay("1969-12-31")?.ordinal, -1)
        XCTAssertNil(ISODay("Sep 23"))
        XCTAssertNil(ISODay(nil))
        XCTAssertNil(ISODay("2026-13-01"))
    }

    /// Today is the viewer's: the same instant is the 24th in Tokyo and the 23rd in Los Angeles.
    func testTodayIsReadInTheViewersCalendar() throws {
        var tokyo = Calendar(identifier: .gregorian)
        tokyo.timeZone = try XCTUnwrap(TimeZone(identifier: "Asia/Tokyo"))
        var la = Calendar(identifier: .gregorian)
        la.timeZone = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        let instant = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-09-23T20:00:00Z"))
        XCTAssertEqual(ISODay.today(now: instant, calendar: tokyo).description, "2026-09-24")
        XCTAssertEqual(ISODay.today(now: instant, calendar: la).description, "2026-09-23")
    }

    func testThePhraseLadder() {
        XCTAssertEqual(RelativeDay.phrase(t, today: t, locale: us), "Today")
        XCTAssertEqual(RelativeDay.phrase(t.adding(-1), today: t, locale: us), "Yesterday")
        XCTAssertEqual(RelativeDay.phrase(t.adding(1), today: t, locale: us), "Tomorrow")
        XCTAssertEqual(RelativeDay.phrase(t.adding(-2), today: t, locale: us), "Monday")
        XCTAssertEqual(RelativeDay.phrase(t.adding(-14), today: t, locale: us), "Sep 9")
        XCTAssertEqual(RelativeDay.phrase(ISODay(year: 2025, month: 9, day: 9), today: t, locale: us), "Sep 9, 2025")
        XCTAssertEqual(RelativeDay.spoken(t, locale: us), "September 23")
        XCTAssertEqual(RelativeDay.month(t, locale: us), "Sep")
    }

    /// Midnight moves every word with no network: yesterday's "Today" is today's "Yesterday".
    func testMidnightRollsTheWordsOver() {
        XCTAssertEqual(RelativeDay.phrase(t, today: t.adding(1), locale: us), "Yesterday")
        XCTAssertEqual(RelativeDay.distance(t.adding(8), today: t.adding(1)), "in 7 days")
    }

    func testDistancesAgesAndGroups() {
        XCTAssertEqual(RelativeDay.distance(t, today: t), "today")
        XCTAssertEqual(RelativeDay.distance(t.adding(1), today: t), "tomorrow")
        XCTAssertEqual(RelativeDay.distance(t.adding(8), today: t), "in 8 days")
        XCTAssertEqual(RelativeDay.distance(t.adding(-1), today: t), "yesterday")
        XCTAssertEqual(RelativeDay.distance(t.adding(-24), today: t), "24 days ago")
        XCTAssertEqual(RelativeDay.compactAge(t, today: t), "today")
        XCTAssertEqual(RelativeDay.compactAge(t.adding(-9), today: t), "9d")
        XCTAssertEqual(RelativeDay.compactAge(t.adding(-29), today: t), "4w")
        XCTAssertEqual(RelativeDay.compactAge(t.adding(-120), today: t), "4mo")
        XCTAssertEqual(RelativeDay.compactAge(nil, today: t), "—")
        XCTAssertEqual(RelativeDay.group(t, today: t), .today)
        XCTAssertEqual(RelativeDay.group(t.adding(-1), today: t), .yesterday)
        XCTAssertEqual(RelativeDay.group(t.adding(-6), today: t), .thisWeek)
        XCTAssertEqual(RelativeDay.group(t.adding(-7), today: t), .earlier)
        XCTAssertEqual(RelativeDay.group(t.adding(2), today: t), .today, "a day ahead (a clock that moved) is today")
        XCTAssertEqual(RelativeDay.bandWords(spanDays: 110).map(\.text), ["2 weeks ago", "in 2 weeks"])
        XCTAssertEqual(RelativeDay.bandWords(spanDays: 200).map(\.text), ["a month ago"])
    }

    /// DR-58 — "Today"/"Yesterday"/"Tomorrow" are spelled once, in `RelativeDay`; the Projects files never spell them.
    func testRelativeWordsAreSpelledOnlyByRelativeDay() throws {
        let scope = ["/Views/Projects/", "/Models/Project", "/Theme/Copy+Projects.swift"]
        let needles = [#""Today""#, #""Yesterday""#, #""Tomorrow""#, #""today""#, #""yesterday""#, #""tomorrow""#]
        var offenders: [String] = []
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources() where scope.contains(where: file.path.contains) {
            scanned += 1
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && needles.contains(where: line.contains) {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertGreaterThan(scanned, 0, "the lint scanned nothing — its scope no longer matches a file")
        XCTAssertEqual(offenders, [], "DR-58: relative day words come from RelativeDay only")
    }
}
```

  Create `ProjectsCacheTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// A `ProjectsAPI` that answers from a queue and records the ETag each call sent.
@MainActor
final class FakeProjectsAPI: ProjectsAPI {
    var listReplies: [Result<Conditional<ProjectsResponse>, any Error>] = []
    var timelineReplies: [String: [Result<Conditional<ProjectTimeline>, any Error>]] = [:]
    private(set) var listETags: [String?] = []
    private(set) var timelineETags: [String: [String?]] = [:]
    /// Parks the next list fetch until `release()` — lets a test switch banks mid-flight.
    var gated = false
    private var gate: CheckedContinuation<Void, Never>?

    func release() { gate?.resume(); gate = nil }

    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse> {
        listETags.append(etag)
        if gated { gated = false; await withCheckedContinuation { gate = $0 } }
        guard !listReplies.isEmpty else { throw APIError.serverUnreachable }
        return try listReplies.removeFirst().get()
    }

    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline> {
        timelineETags[id, default: []].append(etag)
        guard var queue = timelineReplies[id], !queue.isEmpty else { throw APIError.serverUnreachable }
        let next = queue.removeFirst()
        timelineReplies[id] = queue
        return try next.get()
    }
}

/// R-PP3 / R-PJ7 — the cache revalidates with the server's ETag, keeps last-known-good, says a 404 as "gone", and
/// forgets everything on a bank switch — including an answer that was in flight across it.
@MainActor
final class ProjectsCacheTests: XCTestCase {
    private func fresh<T>(_ v: T, _ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: v, etag: etag, notModified: false))
    }
    private func notModified<T>(_ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: nil, etag: etag, notModified: true))
    }

    func testTheListIsFetchedThenRevalidatedWithItsETag() async throws {
        let wire = try ProjectFixtures.load()
        let api = FakeProjectsAPI()
        api.listReplies = [fresh(wire.projects, "e1"), notModified("e1")]
        let cache = ProjectsCache(api: api)
        await cache.refreshList()
        await cache.refreshList()
        XCTAssertEqual(api.listETags, [nil, "e1"], "never an ETag with nothing cached; then the one the server sent")
        XCTAssertEqual(cache.list?.projects.count, wire.projects.projects.count, "a 304 keeps what was shown")
        XCTAssertEqual(cache.listPhase, .loaded)
    }

    func testAFailureKeepsWhatWasShownAndSaysSoOnlyWhenNothingWas() async throws {
        let wire = try ProjectFixtures.load()
        let api = FakeProjectsAPI()
        api.listReplies = [fresh(wire.projects, "e1"), .failure(APIError.serverUnreachable)]
        let cache = ProjectsCache(api: api)
        await cache.refreshList()
        await cache.refreshList()
        XCTAssertNotNil(cache.list)
        XCTAssertEqual(cache.listPhase, .loaded, "a failed revalidation over good data stays silent")
        let cold = ProjectsCache(api: FakeProjectsAPI())
        await cold.refreshList()
        guard case .failed(let message) = cold.listPhase else { return XCTFail("\(cold.listPhase)") }
        XCTAssertTrue(message.contains("isn't answering"), message)
    }

    func testATimelineRevalidatesAndA404ReadsAsGone() async throws {
        let rover = try ProjectFixtures.timeline("rover-arm-project")
        let api = FakeProjectsAPI()
        api.timelineReplies["rover-arm-project"] = [fresh(rover, "t1"), notModified("t1")]
        api.timelineReplies["gone-project"] = [.failure(APIError.httpError(404, #"{"detail":"No project"}"#))]
        let cache = ProjectsCache(api: api)
        await cache.refreshTimeline("rover-arm-project")
        await cache.refreshTimeline("rover-arm-project")
        XCTAssertEqual(api.timelineETags["rover-arm-project"], [nil, "t1"])
        XCTAssertEqual(cache.display("rover-arm-project")?.project.id, "rover-arm-project")
        await cache.refreshTimeline("gone-project")
        XCTAssertEqual(cache.phase("gone-project"), .gone)
        XCTAssertNil(cache.display("gone-project"))
    }

    func testABankSwitchForgetsEverythingAndDropsAnAnswerInFlight() async throws {
        let wire = try ProjectFixtures.load()
        let api = FakeProjectsAPI()
        api.listReplies = [fresh(wire.projects, "e1")]
        api.gated = true
        let cache = ProjectsCache(api: api)
        let inFlight = Task { await cache.refreshList() }
        while api.listETags.isEmpty { await Task.yield() }
        cache.reset()
        api.release()
        await inFlight.value
        XCTAssertNil(cache.list, "an answer for the old bank never paints the new one")
        XCTAssertEqual(cache.listPhase, .idle)
    }

    func testTimelinesAreBounded() async throws {
        let rover = try ProjectFixtures.timeline("rover-arm-project")
        let api = FakeProjectsAPI()
        let cache = ProjectsCache(api: api)
        for i in 0...ProjectsCache.timelineCapacity {
            api.timelineReplies["p\(i)"] = [fresh(rover, "t\(i)")]
            await cache.refreshTimeline("p\(i)")
        }
        XCTAssertNil(cache.display("p0"), "the least recent is forgotten")
        XCTAssertNotNil(cache.display("p\(ProjectsCache.timelineCapacity)"))
    }

    /// The page asks again only when a component both ETags fold moved (R-PJ7) — never on a Sleep tick alone.
    func testRevalidationFollowsTheComponentsTheETagsFold() {
        let a = VersionVector(version: "1", components: ["entities": "1", "episodes": "1", "inbox": "1", "sleep": "1"])
        XCTAssertTrue(ProjectsRefresh.shouldRevalidate(old: nil, new: a))
        XCTAssertFalse(ProjectsRefresh.shouldRevalidate(old: a, new: a))
        XCTAssertFalse(ProjectsRefresh.shouldRevalidate(old: a, new: nil))
        for key in ["entities", "episodes", "inbox", "bank"] {
            var c = a.components
            c[key] = "2"
            XCTAssertTrue(ProjectsRefresh.shouldRevalidate(old: a, new: VersionVector(version: "2", components: c)), key)
        }
        var sleepOnly = a.components
        sleepOnly["sleep"] = "2"
        XCTAssertFalse(ProjectsRefresh.shouldRevalidate(old: a, new: VersionVector(version: "2", components: sleepOnly)))
    }
}
```

- [ ] **Step 3: See them fail.**
  `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectWireTests|ProjectStateTests|RelativeDayTests|ProjectsCacheTests' 2>&1 | tail -20`
  fails to compile (`ProjectsResponse`, `ISODay`, `ProjectsCache` … are unknown).

- [ ] **Step 4: The wire.** Create `app/…/Models/Project.swift`:

```swift
import Foundation

// G141 PJ-5 — the Projects wire, camelCase as `api/models/schemas.py` serialises it (`ProjectsResponse` :1193,
// `ProjectTimeline` :1199, `ProjectWriteResponse` :1247). Every field decodes leniently — a missing or mistyped key
// takes its default (R-PP2, the house rule for a new wire) — so a server one field ahead or behind never blanks the
// page. Days are `YYYY-MM-DD` and instants ISO strings: nothing relative travels (R-PJ6); the page reads them through
// `ISODay` and `RelativeDay`. Fields a `ProjectOverlay` paints (Task 5) are `var`.

extension KeyedDecodingContainer {
    /// A present, well-typed value, or `fallback`: one bad field never fails the payload.
    func lenient<T: Decodable>(_ key: Key, _ fallback: T) -> T {
        (try? decodeIfPresent(T.self, forKey: key)) ?? fallback
    }

    /// A present, well-typed value, or nil.
    func lenient<T: Decodable>(_ key: Key) -> T? {
        try? decodeIfPresent(T.self, forKey: key)
    }
}

struct ProjectProgress: Decodable, Equatable, Sendable {
    var done: Int
    var total: Int

    init(done: Int = 0, total: Int = 0) {
        self.done = done
        self.total = total
    }

    enum CodingKeys: String, CodingKey { case done, total }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        done = c.lenient(.done, 0)
        total = c.lenient(.total, 0)
    }
}

struct ProjectActivityDay: Decodable, Equatable, Sendable {
    var day: String
    var n: Int

    enum CodingKeys: String, CodingKey { case day, n }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = c.lenient(.day, "")
        n = c.lenient(.n, 0)
    }
}

/// One claim as `ClaimModel` sends it — only what the page reads: an event's status, target and date basis, who wrote
/// it and where, and its evidence spans. A local subset, not new fields on the shared `Claim` (R-PP2).
struct ProjectClaim: Decodable, Equatable, Sendable {
    var id: String
    var text: String
    var subject: String
    var predicate: String
    var object: String
    var validFrom: String
    var validTo: String?
    var supersededBy: String?
    var status: String?
    var target: String?
    var dateBasis: String?
    var origin: String?
    var authoredBy: String
    var authorKind: String?
    var evidence: [Evidence]
    var sourceEpisodes: [String]

    enum CodingKeys: String, CodingKey {
        case id, text, subject, predicate, object, validFrom, validTo, supersededBy, status, target, dateBasis
        case origin, authoredBy, authorKind, evidence, sourceEpisodes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        text = c.lenient(.text, "")
        subject = c.lenient(.subject, "")
        predicate = c.lenient(.predicate, "")
        object = c.lenient(.object, "")
        validFrom = c.lenient(.validFrom, "")
        validTo = c.lenient(.validTo)
        supersededBy = c.lenient(.supersededBy)
        status = c.lenient(.status)
        target = c.lenient(.target)
        dateBasis = c.lenient(.dateBasis)
        origin = c.lenient(.origin)
        authoredBy = c.lenient(.authoredBy, "unknown")
        authorKind = c.lenient(.authorKind)
        evidence = c.lenient(.evidence, [])
        sourceEpisodes = c.lenient(.sourceEpisodes, [])
    }
}

/// A page (or an unlinked name) in a happening or a moment, resolved by the server (§6.1): `surface` is the exact
/// words the sentence used (R-PJ15), `derived` a read-time relink by name (R-PJ9), `isOwner` the G117 owner page.
struct ProjectParticipant: Decodable, Equatable, Hashable, Sendable {
    var id: String?
    var name: String
    var typeName: String?
    var role: String?
    var surface: String?
    var url: String?
    var isOwner: Bool
    var derived: Bool

    var type: EntityType { typeName.flatMap(EntityType.init(rawValue:)) ?? .unknown }

    init(id: String?, name: String, type: String? = nil, role: String? = nil, surface: String? = nil,
         url: String? = nil, isOwner: Bool = false, derived: Bool = false) {
        self.id = id
        self.name = name
        self.typeName = type
        self.role = role
        self.surface = surface
        self.url = url
        self.isOwner = isOwner
        self.derived = derived
    }

    enum CodingKeys: String, CodingKey { case id, name, typeName = "type", role, surface, url, isOwner, derived }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id)
        name = c.lenient(.name, "")
        typeName = c.lenient(.typeName)
        role = c.lenient(.role)
        surface = c.lenient(.surface)
        url = c.lenient(.url)
        isOwner = c.lenient(.isOwner, false)
        derived = c.lenient(.derived, false)
    }
}

struct ProjectFact: Decodable, Equatable, Sendable {
    var claimId: String
    var phrase: String
    var state: String

    enum CodingKeys: String, CodingKey { case claimId, phrase, state }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = c.lenient(.claimId, "")
        phrase = c.lenient(.phrase, "")
        state = c.lenient(.state, "said")
    }
}

/// A moment's or a happening's best words — offsets into `episode`, never a copy (G118). No hash travels, so a Reader
/// opened from a moment cannot ask for grown/stale (R-PP16; reported).
struct ProjectQuote: Decodable, Equatable, Sendable {
    var episode: String
    var start: Int?
    var end: Int?
    var kind: String
    var status: String

    enum CodingKeys: String, CodingKey { case episode, start, end, kind, status }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = c.lenient(.episode, "")
        start = c.lenient(.start)
        end = c.lenient(.end)
        kind = c.lenient(.kind, "derived")
        status = c.lenient(.status, "current")
    }
}

/// Where a row was said. `resumable` is per request and may be stale behind a 304 (spec §7): the click re-checks.
struct ProjectConversation: Decodable, Equatable, Sendable {
    var id: String?
    var episodeId: String
    var title: String
    var origin: String?
    var harness: String?
    var resumable: Bool

    enum CodingKeys: String, CodingKey { case id, episodeId, title, origin, harness, resumable }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id)
        episodeId = c.lenient(.episodeId, "")
        title = c.lenient(.title, "")
        origin = c.lenient(.origin)
        harness = c.lenient(.harness)
        resumable = c.lenient(.resumable, false)
    }
}

/// One row of a project's story (spec §6.1): `moment` (derived, "said here"), `happening` (an event claim),
/// `history` (a `## History` bullet) or `created` ("Cicada started tracking this").
struct ProjectItem: Decodable, Equatable, Identifiable, Sendable {
    var kind: String
    var id: String
    var day: String?
    var at: String?
    var dateBasis: String?
    var state: String?
    var via: String?
    var project: String?
    var text: String
    var facts: [ProjectFact]
    var moreFacts: Int
    var participants: [ProjectParticipant]
    var quote: ProjectQuote?
    var conversation: ProjectConversation?
    var claim: ProjectClaim?
    var verbatim: Bool

    enum CodingKeys: String, CodingKey {
        case kind, id, day, at, dateBasis, state, via, project, text, facts, moreFacts, participants, quote
        case conversation, claim, verbatim
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = c.lenient(.kind, "moment")
        id = c.lenient(.id, "")
        day = c.lenient(.day)
        at = c.lenient(.at)
        dateBasis = c.lenient(.dateBasis)
        state = c.lenient(.state)
        via = c.lenient(.via)
        project = c.lenient(.project)
        text = c.lenient(.text, "")
        facts = c.lenient(.facts, [])
        moreFacts = c.lenient(.moreFacts, 0)
        participants = c.lenient(.participants, [])
        quote = c.lenient(.quote)
        conversation = c.lenient(.conversation)
        claim = c.lenient(.claim)
        verbatim = c.lenient(.verbatim, false)
    }

    /// A happening's own status (`ongoing`/`done`/`dropped`), else the moment's state (`said`/`changed`/`ended`).
    var status: String { claim?.status ?? state ?? "said" }
}

/// A milestone slot's head (R-PJ4): `status` is `planned|done|missed|dropped|passed-no-word`; `chain` is the slot's
/// history newest first, crossing the `due` → `milestone` hop (detail only — the list's rows carry none).
struct ProjectMilestone: Decodable, Equatable, Identifiable, Sendable {
    var slug: String
    var name: String
    var status: String
    var target: String?
    var doneOn: String?
    var moved: Bool
    var source: String
    var on: String?
    var claimId: String?
    var chain: [ProjectClaim]

    var id: String { slug }

    init(slug: String, name: String, status: String, target: String? = nil, doneOn: String? = nil, moved: Bool = false,
         source: String = "milestone", on: String? = nil, claimId: String? = nil, chain: [ProjectClaim] = []) {
        self.slug = slug
        self.name = name
        self.status = status
        self.target = target
        self.doneOn = doneOn
        self.moved = moved
        self.source = source
        self.on = on
        self.claimId = claimId
        self.chain = chain
    }

    enum CodingKeys: String, CodingKey { case slug, name, status, target, doneOn, moved, source, on, claimId, chain }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        slug = c.lenient(.slug, "")
        name = c.lenient(.name, "")
        status = c.lenient(.status, "planned")
        target = c.lenient(.target)
        doneOn = c.lenient(.doneOn)
        moved = c.lenient(.moved, false)
        source = c.lenient(.source, "milestone")
        on = c.lenient(.on)
        claimId = c.lenient(.claimId)
        chain = c.lenient(.chain, [])
    }
}

struct ProjectOpenThread: Decodable, Equatable, Identifiable, Sendable {
    var claimId: String
    var text: String
    var since: String
    var lastHeard: String
    var on: String?
    var verbatim: Bool

    var id: String { claimId }

    init(claimId: String, text: String, since: String, lastHeard: String, on: String? = nil) {
        self.claimId = claimId
        self.text = text
        self.since = since
        self.lastHeard = lastHeard
        self.on = on
        self.verbatim = false
    }

    enum CodingKeys: String, CodingKey { case claimId, text, since, lastHeard, on, verbatim }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = c.lenient(.claimId, "")
        text = c.lenient(.text, "")
        since = c.lenient(.since, "")
        lastHeard = c.lenient(.lastHeard, since)
        on = c.lenient(.on)
        verbatim = c.lenient(.verbatim, false)
    }
}

/// A page around the project (§6.4). `pending` is a name no page holds yet ("mentioned once, not a page yet").
struct ProjectMember: Decodable, Equatable, Identifiable, Sendable {
    var memberId: String?
    var typeName: String?
    var name: String
    var rolePhrase: String
    var fact: String
    var lastSeen: String?
    var count: Int
    var pending: Bool

    var id: String { memberId ?? "pending:\(name)" }
    var type: EntityType { typeName.flatMap(EntityType.init(rawValue:)) ?? .unknown }

    enum CodingKeys: String, CodingKey {
        case memberId = "id", typeName = "type", name, rolePhrase, fact, lastSeen, count, pending
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        memberId = c.lenient(.memberId)
        typeName = c.lenient(.typeName)
        name = c.lenient(.name, "")
        rolePhrase = c.lenient(.rolePhrase, "")
        fact = c.lenient(.fact, "")
        lastSeen = c.lenient(.lastSeen)
        count = c.lenient(.count, 0)
        pending = c.lenient(.pending, false)
    }
}

struct ProjectMemberGroup: Decodable, Equatable, Identifiable, Sendable {
    var label: String
    var members: [ProjectMember]
    var more: Int

    var id: String { label }

    enum CodingKeys: String, CodingKey { case label, members, more }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = c.lenient(.label, "")
        members = c.lenient(.members, [])
        more = c.lenient(.more, 0)
    }
}

struct ProjectCluster: Decodable, Equatable, Sendable {
    var groups: [ProjectMemberGroup] = []
    var alsoUses: [ProjectMember] = []

    init() {}

    enum CodingKeys: String, CodingKey { case groups, alsoUses }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        groups = c.lenient(.groups, [])
        alsoUses = c.lenient(.alsoUses, [])
    }
}

struct ProjectRef: Decodable, Equatable, Sendable {
    var id: String
    var name: String
    var oneLiner: String
    var parent: String?
    var children: [String]
    var status: String
    var created: String?

    enum CodingKeys: String, CodingKey { case id, name, oneLiner, parent, children, status, created }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        name = c.lenient(.name, "")
        oneLiner = c.lenient(.oneLiner, "")
        parent = c.lenient(.parent)
        children = c.lenient(.children, [])
        status = c.lenient(.status, "active")
        created = c.lenient(.created)
    }
}

struct ProjectNow: Decodable, Equatable, Sendable {
    var threads: [ProjectOpenThread] = []
    var next: ProjectMilestone?

    init() {}

    enum CodingKeys: String, CodingKey { case threads, next }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        threads = c.lenient(.threads, [])
        next = c.lenient(.next)
    }
}

struct ProjectPending: Decodable, Equatable, Sendable {
    var unconsolidated: Int = 0
    var newestDay: String?

    init() {}

    enum CodingKeys: String, CodingKey { case unconsolidated, newestDay }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        unconsolidated = c.lenient(.unconsolidated, 0)
        newestDay = c.lenient(.newestDay)
    }
}

/// `GET /projects` — one row per live project, lighter than the detail (§6.5).
struct ProjectRow: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var name: String
    var oneLiner: String
    var parent: String?
    var children: [String]
    var status: String
    var created: String?
    var planned: Bool
    var lastMomentDay: String?
    var medianGapDays: Double?
    var openThreads: [ProjectOpenThread]
    var milestones: [ProjectMilestone]
    var progress: ProjectProgress
    var activity: [ProjectActivityDay]
    var followups: Int

    enum CodingKeys: String, CodingKey {
        case id, name, oneLiner, parent, children, status, created, planned, lastMomentDay, medianGapDays
        case openThreads, milestones, progress, activity, followups
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        name = c.lenient(.name, "")
        oneLiner = c.lenient(.oneLiner, "")
        parent = c.lenient(.parent)
        children = c.lenient(.children, [])
        status = c.lenient(.status, "active")
        created = c.lenient(.created)
        planned = c.lenient(.planned, false)
        lastMomentDay = c.lenient(.lastMomentDay)
        medianGapDays = c.lenient(.medianGapDays)
        openThreads = c.lenient(.openThreads, [])
        milestones = c.lenient(.milestones, [])
        progress = c.lenient(.progress, ProjectProgress())
        activity = c.lenient(.activity, [])
        followups = c.lenient(.followups, 0)
    }
}

struct ProjectsResponse: Decodable, Equatable, Sendable {
    var projects: [ProjectRow]
    var tzName: String
    var partial: Bool

    enum CodingKeys: String, CodingKey { case projects, tzName, partial }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        projects = c.lenient(.projects, [])
        tzName = c.lenient(.tzName, "UTC")
        partial = c.lenient(.partial, false)
    }
}

/// `GET /projects/{id}/timeline` — one project's whole story (spec §10.1).
struct ProjectTimeline: Decodable, Equatable, Sendable {
    var project: ProjectRef
    var tzName: String
    var now: ProjectNow
    var pending: ProjectPending
    var milestones: [ProjectMilestone]
    var items: [ProjectItem]
    var activity: [ProjectActivityDay]
    var momentDays: [String]
    var lastMomentDay: String?
    var medianGapDays: Double?
    var cluster: ProjectCluster
    var conversations: [ProjectConversation]
    var partial: Bool

    enum CodingKeys: String, CodingKey {
        case project, tzName, now, pending, milestones, items, activity, momentDays, lastMomentDay, medianGapDays
        case cluster, conversations, partial
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decode(ProjectRef.self, forKey: .project)   // the one field without which there is no page
        tzName = c.lenient(.tzName, "UTC")
        now = c.lenient(.now, ProjectNow())
        pending = c.lenient(.pending, ProjectPending())
        milestones = c.lenient(.milestones, [])
        items = c.lenient(.items, [])
        activity = c.lenient(.activity, [])
        momentDays = c.lenient(.momentDays, [])
        lastMomentDay = c.lenient(.lastMomentDay)
        medianGapDays = c.lenient(.medianGapDays)
        cluster = c.lenient(.cluster, ProjectCluster())
        conversations = c.lenient(.conversations, [])
        partial = c.lenient(.partial, false)
    }
}

/// What every Projects write answers (`routers/projects.py`): the claim it wrote, the day and how that day was
/// decided (R-PJ6 — the Log's confirmation says it), and a Log's companion note.
struct ProjectWriteResponse: Decodable, Equatable, Sendable {
    var action: String
    var claimId: String?
    var day: String?
    var dateBasis: String?
    var episodeId: String?

    init(action: String, claimId: String? = nil, day: String? = nil, dateBasis: String? = nil, episodeId: String? = nil) {
        self.action = action
        self.claimId = claimId
        self.day = day
        self.dateBasis = dateBasis
        self.episodeId = episodeId
    }

    enum CodingKeys: String, CodingKey { case action, claimId, day, dateBasis, episodeId }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        action = c.lenient(.action, "")
        claimId = c.lenient(.claimId)
        day = c.lenient(.day)
        dateBasis = c.lenient(.dateBasis)
        episodeId = c.lenient(.episodeId)
    }
}
```

- [ ] **Step 5: Relative days.** Create `app/…/Models/RelativeDay.swift`:

```swift
import Foundation

/// A calendar day as the Projects wire sends it — `YYYY-MM-DD` (G141 R-PJ6: absolute only). Arithmetic is whole days
/// in the proleptic Gregorian calendar with no time zone in it (Hinnant's days-from-civil), so "24 days" is 24 across
/// a DST change and the numbers match Python's `date` arithmetic, which `ProjectState` needs to run the shared fixture.
/// A zone enters only when today is read — the viewer's calendar (R-PP5); the server never sends today (R-PJ7).
struct ISODay: Hashable, Comparable, Sendable, CustomStringConvertible {
    /// Days since 1970-01-01.
    let ordinal: Int

    init(ordinal: Int) { self.ordinal = ordinal }

    init(year: Int, month: Int, day: Int) { ordinal = Self.daysFromCivil(year, month, day) }

    /// The first ten characters as `YYYY-MM-DD` (an instant's day part parses too); anything else is nil.
    init?(_ raw: String?) {
        guard let raw, raw.count >= 10 else { return nil }
        let parts = raw.prefix(10).split(separator: "-")
        guard parts.count == 3, let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]),
              (1...12).contains(m), (1...31).contains(d) else { return nil }
        self.init(year: y, month: m, day: d)
    }

    static func today(now: Date = Date(), calendar: Calendar = .autoupdatingCurrent) -> ISODay {
        let c = calendar.dateComponents([.year, .month, .day], from: now)
        return ISODay(year: c.year ?? 1970, month: c.month ?? 1, day: c.day ?? 1)
    }

    func adding(_ days: Int) -> ISODay { ISODay(ordinal: ordinal + days) }

    static func - (lhs: ISODay, rhs: ISODay) -> Int { lhs.ordinal - rhs.ordinal }
    static func < (lhs: ISODay, rhs: ISODay) -> Bool { lhs.ordinal < rhs.ordinal }

    var civil: (year: Int, month: Int, day: Int) { Self.civilFromDays(ordinal) }

    var description: String {
        let c = civil
        return String(format: "%04d-%02d-%02d", c.year, c.month, c.day)
    }

    /// Noon on this day in `calendar`'s zone — what a formatter needs to print it without a zone shift.
    func date(in calendar: Calendar) -> Date {
        let c = civil
        return calendar.date(from: DateComponents(year: c.year, month: c.month, day: c.day, hour: 12)) ?? Date()
    }

    private static func daysFromCivil(_ year: Int, _ m: Int, _ d: Int) -> Int {
        let y = m <= 2 ? year - 1 : year
        let era = (y >= 0 ? y : y - 399) / 400
        let yoe = y - era * 400
        let doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
        return era * 146_097 + doe - 719_468
    }

    private static func civilFromDays(_ days: Int) -> (year: Int, month: Int, day: Int) {
        let z = days + 719_468
        let era = (z >= 0 ? z : z - 146_096) / 146_097
        let doe = z - era * 146_097
        let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
        let mp = (5 * doy + 2) / 153
        let d = doy - (153 * mp + 2) / 5 + 1
        let m = mp < 10 ? mp + 3 : mp - 9
        return (yoe + era * 400 + (m <= 2 ? 1 : 0), m, d)
    }
}

/// DR-58 / G141 §8 — every relative word on the Projects page, computed at read from an absolute day and the viewer's
/// today; nothing relative is stored or sent (R-PJ6). The ONLY place the day words are spelled
/// (`RelativeDayTests.testRelativeWordsAreSpelledOnlyByRelativeDay`), so a second, drifting spelling cannot appear.
enum RelativeDay {
    /// Lately's headers (R-PP14).
    enum Group: Hashable, CaseIterable, Sendable { case today, yesterday, thisWeek, earlier }

    /// "Today" · "Yesterday" · "Tomorrow" · a weekday within the last six days · "Sep 9" · "Sep 9, 2025".
    static func phrase(_ day: ISODay, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        switch day - today {
        case 0: "Today"
        case -1: "Yesterday"
        case 1: "Tomorrow"
        case -6 ... -2: weekday(day, locale: locale)
        default: absolute(day, today: today, locale: locale)
        }
    }

    /// "Sep 9", with the year only when it is not this one — a row's date (DR-58: the full date is its `.help`).
    static func absolute(_ day: ISODay, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: day.civil.year == today.civil.year ? "MMMd" : "yMMMd", locale: locale)
    }

    /// "September 23" — what VoiceOver says ("You are here, today, September 23").
    static func spoken(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "MMMMd", locale: locale)
    }

    /// "Tuesday, September 22, 2026" — a date's `.help`.
    static func full(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "EEEEyMMMMd", locale: locale)
    }

    static func weekday(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "EEEE", locale: locale)
    }

    /// "Sep" — the band's month labels.
    static func month(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "MMM", locale: locale)
    }

    /// "today" · "tomorrow" · "in 8 days" · "yesterday" · "24 days ago" — the lower-case clause after a date
    /// ("Oct 1 · in 8 days").
    static func distance(_ day: ISODay, today: ISODay) -> String {
        let n = day - today
        switch n {
        case 0: return "today"
        case 1: return "tomorrow"
        case -1: return "yesterday"
        case 2...: return "in \(UsageFormat.count(n)) days"
        default: return "\(UsageFormat.count(-n)) days ago"
        }
    }

    /// DR-58 — a row's compact age: "today" · "9d" · "4w" · "4mo"; "—" with no day (its reason is the row's `.help`).
    static func compactAge(_ day: ISODay?, today: ISODay) -> String {
        guard let day else { return "—" }
        let n = today - day
        if n <= 0 { return "today" }
        if n < 14 { return "\(UsageFormat.count(n))d" }
        if n < 60 { return "\(UsageFormat.count(n / 7))w" }
        return "\(UsageFormat.count(n / 30))mo"
    }

    /// R-PP14 — This week is 2–6 days back, a rolling week, so a Monday's is never empty. A day ahead of today (a
    /// clock that moved) reads as Today rather than vanishing.
    static func group(_ day: ISODay, today: ISODay) -> Group {
        switch today - day {
        case ...0: .today
        case 1: .yesterday
        case 2...6: .thisWeek
        default: .earlier
        }
    }

    static func title(_ group: Group) -> String {
        switch group {
        case .today: "Today"
        case .yesterday: "Yesterday"
        case .thisWeek: "This week"
        case .earlier: "Earlier"
        }
    }

    /// The band's words near the marker (R-PP10): two weeks either side, or a month back on a window past 180 days.
    static func bandWords(spanDays: Int) -> [(offset: Int, text: String)] {
        spanDays > 180 ? [(-30, "a month ago")] : [(-14, "2 weeks ago"), (14, "in 2 weeks")]
    }

    private static func format(_ day: ISODay, template: String, locale: Locale) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        let f = DateFormatter()
        f.locale = locale
        f.calendar = calendar
        f.timeZone = calendar.timeZone
        f.setLocalizedDateFormatFromTemplate(template)
        return f.string(from: day.date(in: calendar))
    }
}
```

- [ ] **Step 6: Derived state.** Create `app/…/Models/ProjectState.swift`:

```swift
import Foundation

/// G141 §6.2 — a project's derived state on one day, the Swift twin of `api/services/project_state.py` (R-PP4,
/// R-PJB17). Both run ONE table, `api/tests/fixtures/timeline_state.json`, so the app and an agent (`cicada_project`)
/// never disagree about whether a thread is quiet or a milestone overdue. `today` is an argument: nothing here reads a
/// clock, and nothing here is stored (R-PJ7). Keep it line for line with the Python — a rule changed on one side
/// only fails `ProjectStateTests`.
enum ProjectState {
    static let quietFloorDays = 14        // R-PJ13
    static let quietMultiplier = 2.0      // R-PJ13: 2×, not derived-first's 3×
    static let followupFloorDays = 21     // R-PJ13
    static let overdueAskDays = 3         // §9: asked about once 3 days overdue
    static let gapWindowDays = 180        // R-PJB6: ending at the last moment day
    static let quietSectionDays = 90      // §6.2: Quiet ≤ 90 days, Resting beyond
    static let restingStatuses: Set<String> = ["decaying", "archived"]
    static let counted: Set<String> = ["planned", "done", "missed", "passed-no-word"]   // R-PJ11: dropped never counts

    enum Section: String, Decodable, Sendable { case inMotion, quiet, resting }

    /// A payload's absolute fields (`input_from_timeline`), or the fixture's hand-written ones.
    struct Input: Decodable, Sendable {
        var status: String
        var momentDays: [String]
        var lastMomentDay: String?
        var medianGapDays: Double?
        var openThreads: [ProjectOpenThread]
        var milestones: [ProjectMilestone]

        init(status: String = "active", momentDays: [String] = [], lastMomentDay: String? = nil,
             medianGapDays: Double? = nil, openThreads: [ProjectOpenThread] = [], milestones: [ProjectMilestone] = []) {
            self.status = status
            self.momentDays = momentDays
            self.lastMomentDay = lastMomentDay
            self.medianGapDays = medianGapDays
            self.openThreads = openThreads
            self.milestones = milestones
        }

        init(_ row: ProjectRow) {
            self.init(status: row.status, lastMomentDay: row.lastMomentDay, medianGapDays: row.medianGapDays,
                      openThreads: row.openThreads, milestones: row.milestones)
        }

        init(_ t: ProjectTimeline) {
            self.init(status: t.project.status, momentDays: t.momentDays, lastMomentDay: t.lastMomentDay,
                      medianGapDays: t.medianGapDays, openThreads: t.now.threads, milestones: t.milestones)
        }

        enum CodingKeys: String, CodingKey { case status, momentDays, lastMomentDay, medianGapDays, openThreads, milestones }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            status = c.lenient(.status, "active")
            momentDays = c.lenient(.momentDays, [])
            lastMomentDay = c.lenient(.lastMomentDay)
            medianGapDays = c.lenient(.medianGapDays)
            openThreads = c.lenient(.openThreads, [])
            milestones = c.lenient(.milestones, [])
        }
    }

    struct ThreadState: Decodable, Equatable, Sendable {
        let claimId: String
        let quietDays: Int?
        let followupEligible: Bool
    }

    struct MilestoneState: Decodable, Equatable, Sendable {
        let slug: String
        /// `upcoming | overdue | someday | done | missed | dropped | passed-no-word`.
        let state: String
        /// Days to the target (planned), or done − target (done: < 0 early, > 0 late).
        let days: Int?
        let moved: Bool
        let followupEligible: Bool
    }

    struct Output: Decodable, Equatable, Sendable {
        let medianGapDays: Double?
        let quietThreshold: Int
        let section: Section
        let threads: [ThreadState]
        let milestones: [MilestoneState]
        let progress: ProjectProgress
        let next: String?
        let planned: Bool

        func thread(_ claimId: String) -> ThreadState? { threads.first { $0.claimId == claimId } }
        func milestone(_ slug: String) -> MilestoneState? { milestones.first { $0.slug == slug } }

        /// R-PP4 — quiet past Q, the section's own rule (`idle <= q` is in motion).
        func isQuiet(_ claimId: String) -> Bool { (thread(claimId)?.quietDays ?? 0) > quietThreshold }
    }

    /// The median gap between distinct moment days in the 180 days ending at the LAST one — data-anchored, so the
    /// server can serve it without today (R-PJB6).
    static func medianGap(_ days: [String]) -> Double? {
        let ds = Array(Set(days.compactMap { ISODay($0) })).sorted()
        guard let last = ds.last, ds.count >= 2 else { return nil }
        let window = ds.filter { last - $0 <= gapWindowDays }
        let gaps = zip(window, window.dropFirst()).map { $1 - $0 }.sorted()
        guard !gaps.isEmpty else { return nil }
        let mid = gaps.count / 2
        return gaps.count % 2 == 1 ? Double(gaps[mid]) : Double(gaps[mid - 1] + gaps[mid]) / 2
    }

    /// Q = max(14, 2 × median gap), rounded half-up.
    static func quietThreshold(_ gap: Double?) -> Int {
        guard let gap else { return quietFloorDays }
        return max(quietFloorDays, Int((quietMultiplier * gap + 0.5).rounded(.down)))
    }

    static func milestoneState(_ m: ProjectMilestone, today: ISODay) -> MilestoneState {
        let target = ISODay(m.target)
        let doneOn = ISODay(m.doneOn)
        switch m.status {
        case "planned":
            guard let target else {
                return MilestoneState(slug: m.slug, state: "someday", days: nil, moved: m.moved, followupEligible: false)
            }
            return MilestoneState(slug: m.slug, state: target >= today ? "upcoming" : "overdue", days: target - today,
                                  moved: m.moved, followupEligible: today - target >= overdueAskDays)
        case "done":
            let days: Int? = if let target, let doneOn { doneOn - target } else { nil }
            return MilestoneState(slug: m.slug, state: "done", days: days, moved: m.moved, followupEligible: false)
        case "missed", "dropped", "passed-no-word":
            return MilestoneState(slug: m.slug, state: m.status, days: nil, moved: m.moved, followupEligible: false)
        default:
            return MilestoneState(slug: m.slug, state: "someday", days: nil, moved: m.moved, followupEligible: false)
        }
    }

    static func progress(_ milestones: [ProjectMilestone]) -> ProjectProgress {
        let goals = milestones.filter { $0.source != "expectedEnd" && counted.contains($0.status) }
        return ProjectProgress(done: goals.filter { $0.status == "done" }.count, total: goals.count)
    }

    /// The open planned milestone with the earliest target, undated last — upcoming OR overdue, found without today.
    static func nextSlug(_ milestones: [ProjectMilestone]) -> String? {
        milestones
            .filter { $0.status == "planned" && $0.source != "expectedEnd" }
            .sorted { a, b in
                let ka = (a.target == nil ? 1 : 0, a.target ?? "", a.slug)
                let kb = (b.target == nil ? 1 : 0, b.target ?? "", b.slug)
                return ka < kb
            }
            .first?.slug
    }

    static func state(_ input: Input, today: ISODay) -> Output {
        var gap = input.medianGapDays
        if gap == nil, !input.momentDays.isEmpty { gap = medianGap(input.momentDays) }
        let q = quietThreshold(gap)
        let last = ISODay(input.lastMomentDay) ?? input.momentDays.compactMap { ISODay($0) }.max()
        let idle = last.map { today - $0 }
        let section: Section
        if restingStatuses.contains(input.status) || idle == nil || (idle ?? 0) > quietSectionDays {
            section = .resting
        } else if let idle, idle <= q {
            section = .inMotion
        } else {
            section = .quiet
        }
        let threads = input.openThreads.map { t -> ThreadState in
            let heard = ISODay(t.lastHeard) ?? ISODay(t.since)
            let quietDays = heard.map { today - $0 }
            return ThreadState(claimId: t.claimId, quietDays: quietDays,
                               followupEligible: quietDays.map { $0 >= max(followupFloorDays, q) } ?? false)
        }
        return Output(
            medianGapDays: gap, quietThreshold: q, section: section, threads: threads,
            milestones: input.milestones.filter { $0.source != "expectedEnd" }.map { milestoneState($0, today: today) },
            progress: progress(input.milestones), next: nextSlug(input.milestones), planned: !input.milestones.isEmpty)
    }
}
```

  `let days: Int? = if let target, let doneOn { … } else { nil }` is an `if` expression (Swift 5.9); if the toolchain
  rejects it, write it as a two-line `var days: Int? = nil; if let target, let doneOn { days = doneOn - target }`.

- [ ] **Step 7: The reads.** Create `app/…/Services/ProjectsAPI.swift`:

```swift
import Foundation

/// G141 PJ-5 — the two Projects reads. Not a Store domain (R-PJ7, R-PP3): fetched on demand into `ProjectsCache`,
/// revalidated with the ETag the server sends, and no `VersionVector` mapping — the provenance reads' precedent
/// (`ProvenanceAPI`). On a protocol so the cache's tests can fake it.
protocol ProjectsAPI: Sendable {
    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse>
    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline>
}

extension APIClient: ProjectsAPI {
    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse> {
        try await getConditional("/projects", etag: etag)
    }

    /// A project id lands in a PATH, so it is encoded the way every id-in-a-path is (`provenancePath`): a `/`, `?` or
    /// `#` never reshapes the URL.
    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline> {
        try await getConditional(Self.provenancePath("/projects", id, "/timeline"), etag: etag)
    }
}
```

- [ ] **Step 8: The words.** Create `app/…/Theme/Copy+Projects.swift` with every word the page uses (later tasks read
  them; creating the file once keeps each task's diff to its views):

```swift
import Foundation

/// G141 PJ-5 — the Projects page's words (DR-59: sentence case, plain verbs, no "!", no bare "%", no ids — DR-54; no
/// prices). Its own file for the reason `Copy+Lists.swift` gives: parallel tracks edit `Copy.swift`. Day words are NOT
/// here — `RelativeDay` spells them, once (DR-58). And nothing here says "Timeline": that is the entity card's tab for
/// contested beliefs, and the card can share the screen with the band (R-PP12, R-PJ22).
extension Copy {
    enum Projects {
        // MARK: The page
        static let page = "Projects"
        static let active = "Active"
        static let quiet = "Quiet"
        static let tabMenu = "Show"
        static let gathering = "Gathering your projects…"
        static let reading = "Reading this project…"
        static let readingCard = "Reading this page…"
        static let loadFailedTitle = "Couldn't load your projects"
        static let projectFailedTitle = "Couldn't open this project"
        static let emptyTitle = "No projects yet"
        static let emptyMessage = "Projects appear once Cicada has heard about one in two conversations."
        static let noneActive = "Nothing is in motion right now."
        static let noneQuiet = "Nothing has gone quiet."
        static let gone = "This project isn't in this bank any more."
        static let find = "Find a project…"
        static let stillIndexing = "still indexing"
        static let stillIndexingHelp = "Cicada is still building its search index, so a few links may be missing for a moment."
        static let planned = "Planned"
        static let noPlanYet = "No plan yet"
        static let closeHelp = "Close (Esc)"
        static let openHelp = "Open this project"
        static let tag = "Project"
        static let moreHelp = "More for this project"
        static let openCard = "Open its card"
        static func projectsBack(_ n: Int) -> String { n == 1 ? "‹ 1 project" : "‹ \(UsageFormat.count(n)) projects" }
        static func partOf(_ name: String) -> String { "Part of \(name) ›" }
        static func loadFailed(_ error: any Error) -> String {
            if let api = error as? APIError, case .serverUnreachable = api {
                return "Cicada's backend isn't answering. It restarts on its own — try again in a moment."
            }
            return "Something went wrong reading your projects. Try again in a moment."
        }
        static func countActive(_ n: Int) -> String { "\(UsageFormat.count(n)) active" }
        static func countQuiet(_ n: Int) -> String { "\(UsageFormat.count(n)) quiet" }
        static func position(_ i: Int, of n: Int) -> String { "\(UsageFormat.count(i)) of \(UsageFormat.count(n))" }
        static func noMatch(_ query: String) -> String { "No project matches “\(query)”" }

        // MARK: A row (R-PP7)
        static func quietThread(days: Int, text: String) -> String { "Quiet \(UsageFormat.count(days)) days · \(text)" }
        static func quietFor(days: Int) -> String { "Quiet \(UsageFormat.count(days)) days" }
        static func resting(lastHeard day: String) -> String { "Resting · last heard \(day)" }
        static let nothingHeard = "Nothing heard yet"
        static func lastHeard(_ day: String) -> String { "Last heard \(day)" }
        static func next(_ name: String, _ when: String?) -> String { when.map { "Next · \(name), \($0)" } ?? "Next · \(name)" }
        static func nextOverdue(_ name: String, since day: String) -> String { "Next · \(name), overdue since \(day)" }
        static func doneOf(_ p: ProjectProgress) -> String {
            "\(UsageFormat.count(p.done)) of \(UsageFormat.count(p.total)) done"
        }
        static func milestonesDone(_ p: ProjectProgress) -> String {
            "\(UsageFormat.count(p.done)) of \(UsageFormat.count(p.total)) milestones done"
        }
        static func shortPlanned(_ p: ProjectProgress, next: String?) -> String {
            next.map { "\(doneOf(p)) · \($0)" } ?? doneOf(p)
        }
        static func noPlanLast(_ day: String?) -> String { day.map { "No plan yet · last \($0)" } ?? noPlanYet }
        static func nextShort(_ name: String, _ day: String?) -> String { day.map { "\(name) \($0)" } ?? name }
        static func questions(_ n: Int) -> String { n == 1 ? "1 question" : "\(UsageFormat.count(n)) questions" }
        static func lastActivity(_ day: String) -> String { "Last activity \(day)" }
        static let noActivity = "No activity yet"
        static func people(_ names: [String]) -> String { "With \(names.joined(separator: ", "))" }
        static func barHelp(planned: Bool, progress: ProjectProgress) -> String {
            planned ? "\(milestonesDone(progress)); the green runs to today"
                : "No plan yet; the green runs from the first moment to today, and the end stays open"
        }
        static func rowLabel(_ name: String, planned: Bool, progress: ProjectProgress) -> String {
            "\(name) — \(planned ? milestonesDone(progress) : "no plan yet")"
        }

        // MARK: The band (R-PP10, R-PP12)
        static func since(_ day: String) -> String { "Since \(day)" }
        static let youToday = "You, today"
        static func bandLabel(_ name: String, planned: Bool, progress: ProjectProgress, today: String) -> String {
            "Progress of \(name), \(planned ? milestonesDone(progress) : "no plan yet"). You are here, today, \(today)."
        }
        static func happened(_ words: String, _ when: String) -> String { "Happened: \(words), \(when)" }
        static func saidHere(_ words: String, _ when: String) -> String { "Said here: \(words), \(when)" }
        static func fromHistory(_ words: String, _ when: String) -> String { "From the page's history: \(words), \(when)" }
        static func milestoneMark(_ name: String, _ words: String) -> String { "Milestone \(name), \(words)" }
        static func milestoneDoneOn(_ day: String) -> String { "done \(day)" }
        static func milestoneUpcoming(_ day: String, _ distance: String) -> String { "\(day) · \(distance)" }
        static func milestoneOverdue(_ day: String) -> String { "\(day) · overdue" }
        static func milestonePassed(_ day: String) -> String { "\(day) · passed, no word" }
        static func milestoneMissed(_ day: String) -> String { "\(day) · missed" }
        static func earlierTarget(_ name: String) -> String { "\(name) — its earlier date" }
        static func movedOn(_ from: String, _ on: String) -> String { on.isEmpty ? from : "\(from), moved \(on)" }
        static func nextMark(_ name: String, _ distance: String) -> String { "\(name) · \(distance)" }
        static func earlier(_ n: Int) -> String { n == 1 ? "1 earlier" : "\(UsageFormat.count(n)) earlier" }
        static func moreHere(_ n: Int) -> String { "+\(UsageFormat.count(n)) more here" }
        static func inMotion(_ text: String, _ when: String) -> String { "In motion: \(text), \(when)" }
        static func sinceDay(_ day: String) -> String { "since \(day)" }
        static func quietDays(_ n: Int) -> String { "quiet \(UsageFormat.count(n)) days" }
        static let startedToday = "started today"
        static func ongoingUntil(_ day: String) -> String { "ongoing until \(day)" }

        // MARK: The sections (R-PP13…R-PP18)
        static let now = "Now"
        static let lately = "Lately"
        static let plan = "Plan"
        static let around = "Around this project"
        static let collapse = "Collapse"
        static let expand = "Expand"
        static func inMotionCount(_ n: Int) -> String { "\(UsageFormat.count(n)) in motion" }
        static func happeningsCount(_ n: Int) -> String { n == 1 ? "1 happening" : "\(UsageFormat.count(n)) happenings" }
        static func nothingInMotion(lastHeard day: String?, distance: String?) -> String {
            guard let day, let distance else { return "Nothing in motion right now" }
            return "Nothing in motion right now · last heard \(day) (\(distance))"
        }
        static func waiting(_ n: Int, newest: String?) -> String {
            let count = n == 1 ? "1 conversation is" : "\(UsageFormat.count(n)) conversations are"
            return newest.map { "\(count) waiting for Sleep — the newest from \($0)" } ?? "\(count) waiting for Sleep"
        }
        static let waitingHelp = "Cicada reads these the next time it sleeps; until then they aren't in this project's story."
        static func threadSince(_ day: String) -> String { "Since \(day)" }
        static func threadQuiet(since day: String, days: Int) -> String { "Since \(day) · quiet \(UsageFormat.count(days)) days" }
        static let threadStartedToday = "Started today"
        static func threadHeard(since day: String, heard: String) -> String { "Since \(day) · last heard \(heard)" }
        static let howDidItGo = "How did it go? ›"
        static let howDidItGoHelp = "Answer this follow-up in the Inbox"
        static let statusDone = "Done"
        static let statusOngoing = "Ongoing"
        static let statusSaid = "Said here"
        static let statusChanged = "Changed"
        static let statusEnded = "Ended"
        static let statusStopped = "Stopped"
        static let statusHistory = "From the page's history"
        static func statusQuiet(_ n: Int) -> String { "Quiet \(UsageFormat.count(n)) days" }
        static func statusOngoingUntil(_ day: String) -> String { "Ongoing until \(day)" }
        static func moreFacts(_ n: Int) -> String { "+\(UsageFormat.count(n)) \(n == 1 ? "fact" : "facts")" }
        static func via(_ name: String) -> String { "via \(name)" }
        static func onProject(_ name: String) -> String { "on \(name)" }
        static let showInConversation = "Show in conversation ›"
        static let hideConversation = "Hide conversation"
        static let showHelp = "Open the words this came from beside the project"
        static let yourNote = "Your note in Cicada"
        static let setByYou = "Set by you in Cicada"
        static let pageHistory = "From the page's history — no source sentence"
        static let noSource = "[ no source recorded ]"
        static let you = "you"
        static func youHelp(_ name: String) -> String { "\(name) — you" }
        static func openEntity(_ name: String, type: String) -> String { "Open \(name), \(type.lowercased())" }
        static func openLink(_ host: String) -> String { host.isEmpty ? "Open the link" : "Open \(host)" }
        static let resume = "Resume"
        static func resumeHelp(_ app: String) -> String { "Resume this conversation in \(app)" }
        static func startedTracking(_ day: String) -> String { "Cicada started tracking this · \(day)" }
        static let basisStated = "Dated from your words"
        static let basisTurn = "Dated by when it was said"
        static let basisEpisode = "Dated by the conversation's day"
        static let basisPerson = "Set by you"
        static let basisWritten = "Dated when it was recorded"
        static let basisDay = "Dated by the day it was noted"
        static func doneOn(_ day: String) -> String { "Done \(day)" }
        static func early(_ n: Int) -> String { "\(UsageFormat.count(n)) \(n == 1 ? "day" : "days") early" }
        static func late(_ n: Int) -> String { "\(UsageFormat.count(n)) \(n == 1 ? "day" : "days") late" }
        static let onItsDate = "on its date"
        static func upcoming(_ day: String, _ distance: String) -> String { "\(day) · \(distance)" }
        static func overdueSince(_ day: String) -> String { "Overdue since \(day)" }
        static let someday = "Someday · no date yet"
        static func passedNoWord(_ day: String) -> String { "\(day) · passed, no word on how it went" }
        static func missed(_ day: String?) -> String { day.map { "Missed · \($0)" } ?? "Missed" }
        static let dropped = "Dropped"
        static func moved(_ n: Int) -> String { n == 1 ? "moved once" : "moved \(UsageFormat.count(n)) times" }
        static func plannedOn(target: String, on: String) -> String { "\(target) — planned \(on)" }
        static func movedByYou(target: String, on: String) -> String { "\(target) — moved by you on \(on)" }
        static func movedOnDay(target: String, on: String) -> String { "\(target) — moved on \(on)" }
        static let noPlan = "No plan yet. Nothing here is late or missing — it just hasn't been dated."
        static let documentsAndLinks = "Documents & links"
        static let partsOfThisProject = "Parts of this project"
        static let notAPageYet = "mentioned once, not a page yet"
        static let notAPageYetHelp = "Mentioned once — it becomes a page when it comes up in a second conversation"
        static func lastSeen(_ day: String) -> String { "last \(day)" }
        static func lastMentioned(_ day: String) -> String { "Last mentioned \(day)" }
        static func moreMembers(_ n: Int) -> String { "+\(UsageFormat.count(n)) more" }
        static func alsoUses(_ names: [String]) -> String { "Also uses: \(names.joined(separator: " · "))" }
        static func showSpecs(_ name: String) -> String { "Show what Cicada knows about \(name)" }
        static func hideSpecs(_ name: String) -> String { "Hide what Cicada knows about \(name)" }
        static let noSpecs = "Nothing recorded about it yet."
        static let aroundIndexing = "Still indexing — more may appear here in a moment."
        static let openProject = "Open project ›"

        // MARK: Writes (R-PP19…R-PP22, R-PP25)
        static let logPlaceholder = "Log progress — “Yesterday I got …”"
        static func logLabel(_ name: String) -> String { "Log progress on \(name)" }
        static let logButton = "Log"
        static let logHint = "⏎ saves it as done · ⌘⏎ as still going · the day comes from your words, or the date chip"
        static let saving = "Saving…"
        static func logged(_ name: String, day: String, how: String) -> String { "Logged on \(name) for \(day) — \(how)" }
        static let fromYourWords = "dated from your words"
        static let fromTheChip = "the day you picked"
        static let noDayInWords = "no day in your words, so today"
        static func dayAndDistance(_ day: String, _ distance: String) -> String { "\(day) (\(distance))" }
        static let dateChipHelp = "Pick the day this happened, when your words don't say it"
        static let undo = "Undo"
        static let undoHelp = "Take this back"
        static let done = "Done"
        static let stillGoing = "Still going"
        static let stopped = "Stopped"
        static let doneHelp = "Mark it done, dated today (D)"
        static let stillGoingHelp = "Still going as of today"
        static let stoppedHelp = "It stopped without finishing — dated today"
        static let markDone = "Mark done"
        static let rename = "Rename"
        static let renameHelp = "Change what this milestone is called"
        static let save = "Save"
        static let cancel = "Cancel"
        static let addMilestone = "Add a milestone"
        static let addMilestoneHelp = "Add a milestone (M)"
        static let milestoneName = "What's the milestone?"
        static let milestonePlaceholder = "A milestone — “Demo dry run”"
        static let addDate = "Add a date"
        static let removeDate = "No date"
        static let add = "Add"
        static let notRight = "Not right"
        static let notRightHelp = "Cicada misheard — take this back"
        static let sleepBusy = "Sleep is writing this project, try again in a moment"
        static let sleepRunningHelp = "Sleep is writing your memory — this can be saved once it finishes"
        static let saveFailed = "Couldn't save that — nothing changed"
        static let notOnProject = "That's no longer on this project — showing what's there now"
        static let backendDown = "Cicada's backend isn't answering — nothing changed"
        static let noPlanAdd = "No plan yet —"
    }
}
```

- [ ] **Step 9: The cache.** Create `app/…/Views/Projects/ProjectsCache.swift`:

```swift
import Foundation
import Observation

/// G141 PJ-5 — the Projects page's in-memory cache (R-PP3, R-PJ7; spec §10.1). One for the app, owned by `CicadaApp`
/// as `@State` beside `ProvenanceCache`, so a tab switch keeps what was read and the page repaints at once.
///
/// **Never a Store domain.** Both reads are fetched on demand and revalidated with `If-None-Match` — a 304 costs
/// nothing and keeps the page honest after a Sleep cycle. There is no `SnapshotCache` entry and no `VersionVector`
/// mapping, so the ship-together rule has nothing to pair; the page asks again when a sync version event moves a
/// component both ETags fold (`ProjectsRefresh`).
///
/// **Never blank.** A failed or 304 answer keeps the last value; an error is shown only when there is nothing to show
/// (DR-43). **Not keyed by bank**, so a bank switch empties it (`reset()`) — project ids repeat across banks — and an
/// answer in flight across the switch is dropped by its epoch rather than painted under the new bank.
@Observable
@MainActor
final class ProjectsCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    /// Detail payloads are ~20–30 KB each; a dozen covers any afternoon of clicking.
    static let timelineCapacity = 12

    private(set) var list: ProjectsResponse?
    private(set) var listPhase: Phase = .idle
    private(set) var timelines: [String: ProjectTimeline] = [:]
    private(set) var timelinePhases: [String: Phase] = [:]

    @ObservationIgnored private let api: any ProjectsAPI
    @ObservationIgnored private var listETag: String?
    @ObservationIgnored private var timelineETags: [String: String] = [:]
    @ObservationIgnored private var recent: [String] = []
    @ObservationIgnored private var epoch = 0

    init(api: any ProjectsAPI = APIClient.shared) { self.api = api }

    func phase(_ id: String) -> Phase { timelinePhases[id] ?? .idle }

    /// What the page draws for a project.
    func display(_ id: String) -> ProjectTimeline? { timelines[id] }

    /// Forget everything — a bank switch (`ContentView`, R-PU26's reason).
    func reset() {
        epoch &+= 1
        list = nil
        listPhase = .idle
        listETag = nil
        timelines = [:]
        timelinePhases = [:]
        timelineETags = [:]
        recent = []
    }

    func refreshList() async {
        let started = epoch
        if list == nil { listPhase = .loading }
        do {
            // Never an ETag with nothing cached: a 304 would leave the page with nothing to draw.
            let answer = try await api.fetchProjects(etag: list == nil ? nil : listETag)
            guard started == epoch else { return }
            if let value = answer.value {
                list = value
                listETag = answer.etag
            }
            listPhase = .loaded
        } catch {
            guard started == epoch else { return }
            listPhase = list == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    func refreshTimeline(_ id: String) async {
        let started = epoch
        if timelines[id] == nil { timelinePhases[id] = .loading }
        do {
            let answer = try await api.fetchProjectTimeline(id: id, etag: timelines[id] == nil ? nil : timelineETags[id])
            guard started == epoch else { return }
            if let value = answer.value { store(value, etag: answer.etag, for: id) }
            timelinePhases[id] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            timelines[id] = nil
            timelineETags[id] = nil
            timelinePhases[id] = .gone
        } catch {
            guard started == epoch else { return }
            timelinePhases[id] = timelines[id] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    private func store(_ value: ProjectTimeline, etag: String?, for id: String) {
        timelines[id] = value
        timelineETags[id] = etag
        recent.removeAll { $0 == id }
        recent.append(id)
        while recent.count > Self.timelineCapacity {
            let old = recent.removeFirst()
            timelines[old] = nil
            timelineETags[old] = nil
            timelinePhases[old] = nil
        }
    }
}

/// R-PP3 — when the visible Projects page asks again: a sync version event that moved a component both `/projects`
/// ETags fold (`entities`, `episodes`, `inbox`; `routers/projects.py`) or the bank itself. A Sleep tick alone does
/// not: nothing the page shows moved.
enum ProjectsRefresh {
    static let components = ["entities", "episodes", "inbox", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}
```

- [ ] **Step 10: Green.** Run
  `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectWireTests|ProjectStateTests|RelativeDayTests|ProjectsCacheTests' 2>&1 | tail -20`
  (all pass), then `swift build 2>&1 | tail -5` and the full `swift test 2>&1 | tail -20` (0 failures).

- [ ] **Step 11: Commit.**

```
cd <worktree> && git add api/tests/test_projects_app_fixture.py app/CicadaApp/Tests/fixtures/projects-demo.json \
  app/CicadaApp/Sources/CicadaApp/Models/Project.swift app/CicadaApp/Sources/CicadaApp/Models/ProjectState.swift \
  app/CicadaApp/Sources/CicadaApp/Models/RelativeDay.swift app/CicadaApp/Sources/CicadaApp/Services/ProjectsAPI.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsCache.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy+Projects.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProjectFixtures.swift app/CicadaApp/Tests/CicadaAppTests/ProjectWireTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProjectStateTests.swift app/CicadaApp/Tests/CicadaAppTests/RelativeDayTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProjectsCacheTests.swift
cd <worktree> && git commit -m "feat(projects): the Projects wire, its shared state, relative days and an in-memory cache (G141 PJ-5, R-PP2…R-PP5, R-PP27; DR-21, DR-58)"
```

---

### Task 2: Projects is the eighth page — the list, the page in progressive columns, the detail's heading (DR-5, DR-8, DR-21, DR-22, DR-25…DR-31, DR-34, DR-38, DR-40, DR-43, DR-45, DR-46, DR-48, DR-50, DR-52, DR-54, DR-58, DR-60, DR-68, DR-70; §3.8; R-PP3, R-PP6…R-PP9, R-PP24)

The rail gains its eighth cell and ⌘8; the palette lists the page by itself. The page opens on the list at D density
with a mini green bar per row, opens a project beside it (its heading and the band's header line, "Since Jul 15 ·
1 of 4 done"), and hosts its own Reader. The band and the sections arrive in Tasks 3–4; this commit's detail column is
small but true.

**Files:**
- Create: `app/…/Views/Projects/ProjectsModel.swift`, `ProjectsPage.swift`, `ProjectsRows.swift`,
  `ProjectDetailColumn.swift`.
- Modify: `app/…/Views/Shell/AppTab.swift`, `NavRail.swift` (doc only), `TitlebarHelp.swift`;
  `app/…/Support/AppRouter.swift`; `app/…/ContentView.swift`; `app/…/CicadaApp.swift`; `app/…/Theme/CicadaTheme.swift`;
  `app/…/Theme/ZoomKeyRouter.swift` (doc only).
- Test: `ProjectsListTests.swift` (new). Edit `SidebarTabTests.swift`, `NavRailTests.swift`, `CommandBarTests.swift`,
  `ListColumnsTests.swift`, `TitlebarHelpTests.swift`, `CountLiteralLintTests.swift`, `SelectionTintLintTests.swift`.

**Interfaces:**
- Produces: `AppTab.projects`; `AppRouter.routeToProject(_:)` / `consumeProject()` / `pendingProject` /
  `routeToInboxItem(_:)`; `HelpContent.projects`, `ListHelp.projects`; `CicadaTheme.progressOpenEnd`; `ProjectsTab`,
  `ProjectLine`, `PersonMark`, `ProgressSpan`, `ProjectLayout`, `ProjectsModel` (`state`, `lines`, `tabs`,
  `defaultTab`, `eyebrow`, `nowLine`, `nextLine`, `shortLine`, `age`, `questions`, `accessibilityLabel`, `bar`, `span`,
  `earlierTarget`, `firstWords`, `peopleIndex`, `initials`, `isProject`); `ProjectsListState`; `ProjectsPage`,
  `ProjectsListColumn`, `ProjectRowView`, `ProgressBarView`, `PeopleMarks`, `MidLine`; `ProjectDetailColumn`.
- Consumes: Task 1's wire, state, cache and words; `ProgressiveColumns`, `ColumnLayout`, `ListColumns`, `ListFocus`,
  `ListInsets`, `ListRowSurface`, `listKeys`, `ListSkeleton`, `ListErrorCard`, `EyebrowRow`, `Eyebrow`,
  `AdaptiveTextTabs`, `TextTab`, `PageFindButton`, `PageFindRow`, `publishesPageFind`, `ReaderColumn`, `TypeDot`,
  `Tag`, `InlineLink`, `IconButton`, `TextButton`, `EmptyStateView`, `QuickMatch`, `Instant`, `CicadaMotion.columns`.

- [ ] **Step 1: Failing tests.** Create `ProjectsListTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP6…R-PP9, R-PP24 — what the Projects list shows, pure, on the demo's real wire at T = 2026-09-23.
@MainActor
final class ProjectsListTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")
    private func rows() throws -> [ProjectRow] { try ProjectFixtures.load().projects.projects }

    func testTabsCountTheDemoAndDefaultToActive() throws {
        let rows = try rows()
        let tabs = ProjectsModel.tabs(rows, today: today)
        XCTAssertEqual(tabs.map(\.label), ["Active", "Quiet", "All"])
        XCTAssertEqual(tabs.map(\.count), [6, 0, 15])
        XCTAssertEqual(ProjectsModel.defaultTab(rows, today: today), .active)
        XCTAssertNil(ProjectsModel.defaultTab(rows, today: today.adding(400)), "nothing in motion opens on All")
    }

    /// §11.2 — a sub-project sits indented under its parent when the parent is shown, and flat when it is not.
    func testSubProjectsSitUnderAVisibleParent() throws {
        let lines = ProjectsModel.lines(try rows(), tab: .active, query: "", today: today)
        XCTAssertEqual(lines.map(\.id), ["rover-arm-project", "pick-and-place-demo", "alpha-project", "beta-project",
                                         "gamma-project", "garden-sensor-project"])
        XCTAssertEqual(lines.map(\.depth), [0, 1, 0, 1, 0, 0])
        let found = ProjectsModel.lines(try rows(), tab: nil, query: "Beta", today: today)
        XCTAssertEqual(found.map(\.id), ["beta-project"])
        XCTAssertEqual(found.first?.depth, 0, "a child whose parent is not shown sits flat")
        XCTAssertEqual(ProjectsModel.lines(try rows(), tab: .quiet, query: "", today: today), [])
        XCTAssertEqual(ProjectsModel.lines(try rows(), tab: nil, query: "", today: today).count, 15)
    }

    func testTheRowSaysWhereItStandsNow() throws {
        let lines = ProjectsModel.lines(try rows(), tab: nil, query: "", today: today)
        func line(_ id: String) throws -> ProjectLine { try XCTUnwrap(lines.first { $0.id == id }) }
        let rover = try line("rover-arm-project")
        XCTAssertEqual(ProjectsModel.nowLine(rover, today: today, locale: us),
                       "Bob is connecting to Lab Cluster Example to run the Pick And Place Demo",
                       "the live thread, never the quiet one")
        XCTAssertEqual(ProjectsModel.nextLine(rover, today: today, locale: us), "Next · First grasp, Oct 1")
        XCTAssertEqual(ProjectsModel.shortLine(rover, today: today, locale: us), "1 of 4 done · First grasp Oct 1")
        XCTAssertEqual(ProjectsModel.questions(rover.row), "1 question")
        XCTAssertEqual(ProjectsModel.age(rover.row, today: today, locale: us).text, "today")
        XCTAssertEqual(ProjectsModel.accessibilityLabel(rover), "Rover Arm Project — 1 of 4 milestones done")
        let garden = try line("garden-sensor-project")
        XCTAssertEqual(ProjectsModel.nowLine(garden, today: today, locale: us), "Soil sensors that report from the garden.")
        XCTAssertEqual(ProjectsModel.nextLine(garden, today: today, locale: us), "No plan yet")
        XCTAssertEqual(ProjectsModel.shortLine(garden, today: today, locale: us), "No plan yet · last Sep 14")
        XCTAssertEqual(ProjectsModel.age(garden.row, today: today, locale: us).text, "9d")
        XCTAssertEqual(ProjectsModel.age(garden.row, today: today, locale: us).help, "Last activity Monday, September 14, 2026")
        let delta = try line("delta-project")
        XCTAssertEqual(ProjectsModel.nowLine(delta, today: today, locale: us), "Nothing heard yet")
        XCTAssertEqual(ProjectsModel.age(delta.row, today: today, locale: us).text, "—")
        XCTAssertEqual(ProjectsModel.age(delta.row, today: today, locale: us).help, "No activity yet")
        XCTAssertNil(ProjectsModel.questions(delta.row))
        // A month on, both threads are quiet: the row leads with the quiet days, never a stale "is connecting".
        let later = today.adding(30)
        let quietRover = ProjectLine(row: rover.row, state: ProjectsModel.state(rover.row, today: later), depth: 0)
        XCTAssertEqual(ProjectsModel.nowLine(quietRover, today: later, locale: us),
                       "Quiet 30 days · Bob is connecting to Lab Cluster Example to run the Pick And Place Demo")
    }

    func testTheEyebrowSaysWhereYouAre() {
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 6, tab: .active, position: nil, openPlanned: nil, partial: false),
                       "Projects · 6 active")
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 15, tab: nil, position: nil, openPlanned: nil, partial: false),
                       "Projects · 15")
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 6, tab: .active, position: 1, openPlanned: true, partial: false),
                       "Projects · 1 of 6 · Planned")
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 6, tab: .active, position: 6, openPlanned: false, partial: true),
                       "Projects · 6 of 6 · No plan yet · still indexing")
    }

    /// §3.8 / R-PP9 — the mini bar and the band share one geometry: from the first moment, through today, to the plan.
    func testTheBarFillsToTodayAndEndsWhereThePlanDoes() throws {
        let rover = ProjectsModel.bar(try ProjectFixtures.row("rover-arm-project"), today: today)
        XCTAssertEqual(rover.start.description, "2026-07-15")
        XCTAssertEqual(rover.end.description, "2026-11-02")
        XCTAssertEqual(rover.fill, 70.0 / 110.0, accuracy: 0.0001)
        XCTAssertTrue(rover.planned)
        let garden = ProjectsModel.bar(try ProjectFixtures.row("garden-sensor-project"), today: today)
        XCTAssertEqual(garden.end, today.adding(7), "no plan: a week past today, and an open end")
        XCTAssertEqual(garden.fill, 52.0 / 59.0, accuracy: 0.0001)
        XCTAssertFalse(garden.planned)
        let allPast = ProgressSpan.of(created: today.adding(-30), days: [], targets: [today.adding(-3)], planned: true,
                                      today: today)
        XCTAssertEqual(allPast.end, today.adding(7), "every target behind today: the bar still reaches past today")
        XCTAssertEqual(ProjectsModel.span(try ProjectFixtures.timeline("rover-arm-project"), planned: true, today: today),
                       rover, "the detail's span is the row's")
    }

    /// R-PP7 — people come from the graph the app already holds: a project's `person` neighbours, never the owner.
    func testPeopleAreThePersonNeighboursButNeverTheOwner() {
        let graph = GraphResponse(nodes: [
            GraphNode(id: "rover-arm-project", name: "Rover Arm Project", type: .project),
            GraphNode(id: "hana-example", name: "Hana Example", type: .person, degree: 3),
            GraphNode(id: "bob-example", name: "Bob Example", type: .person, degree: 9, isOwner: true),
            GraphNode(id: "cara-example", name: "Cara Example", type: .person, degree: 1),
            GraphNode(id: "tool-example-a", name: "Tool Example A", type: .tool),
        ], links: [
            GraphEdge(source: "hana-example", target: "rover-arm-project", label: "works-on"),
            GraphEdge(source: "rover-arm-project", target: "bob-example", label: "with"),
            GraphEdge(source: "rover-arm-project", target: "cara-example", label: "with"),
            GraphEdge(source: "rover-arm-project", target: "tool-example-a", label: "uses"),
        ])
        let people = ProjectsModel.peopleIndex(graph)["rover-arm-project"] ?? []
        XCTAssertEqual(people.map(\.name), ["Hana Example", "Cara Example"])
        XCTAssertEqual(people.first?.initials, "HE")
        XCTAssertTrue(ProjectsModel.isProject("rover-arm-project", in: graph))
        XCTAssertFalse(ProjectsModel.isProject("hana-example", in: graph))
    }

    func testTheListSaysWhatItHasBeforeItHasRows() {
        XCTAssertEqual(ProjectsListState.of(phase: .loading, hasList: false, rows: 0, lines: 0, finding: false), .loading)
        XCTAssertEqual(ProjectsListState.of(phase: .failed("x"), hasList: false, rows: 0, lines: 0, finding: false), .failed("x"))
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 0, lines: 0, finding: false), .empty)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 0, finding: false), .tabEmpty)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 0, finding: true), .noMatch)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 2, finding: false), .list)
    }

    /// R-PP24 — ⌘8 and the palette's page row come from `AppTab`; a project row, and a follow-up, hand off.
    func testTheEighthPageAndItsHandOffs() {
        XCTAssertEqual(RailItem.shortcut(for: .projects), "⌘8")
        XCTAssertEqual(RailItem.tooltipTitle(.projects, busy: false), "Projects", "the tooltip reads \"Projects ⌘8\"")
        XCTAssertEqual(AppTab.projects.icon, "point.topleft.down.to.point.bottomright.curvepath")
        XCTAssertTrue(AppTab.projects.hostsOwnReader)
        XCTAssertEqual(AppTab.restored(from: "Projects"), .projects)
        let row = PaletteActions.docs(QuickIndexInputs()).first { $0.row.key.id == "tab.Projects" }?.row
        XCTAssertEqual(row?.title, "Go to Projects")
        XCTAssertEqual(row?.trailing, "⌘8")
        let router = AppRouter()
        router.routeToProject("rover-arm-project")
        XCTAssertEqual(router.pendingTab, .projects)
        XCTAssertEqual(router.consumeProject(), "rover-arm-project")
        XCTAssertNil(router.consumeProject(), "read-then-clear")
        router.routeToInboxItem("inbox-007")
        XCTAssertEqual(router.pendingTab, .inbox)
        XCTAssertEqual(router.consumeInboxItem(), "inbox-007")
    }
}
```

  Edit the existing tests:
  - `SidebarTabTests.swift`: rename `testTheSidebarIsSevenRowsInVisualOrder` to `testTheSidebarIsEightRowsInVisualOrder`
    and assert `[.home, .graph, .clusters, .feed, .sleep, .inbox, .sources, .projects]`; in
    `testSurvivingRawValuesAreUnchanged` add `XCTAssertEqual(AppTab.projects.rawValue, "Projects")`; in
    `testEveryTabHasAShortcutSlotAndAnIcon` the count becomes `8` and its doc comment "⌘1–8"; the class doc says eight
    rows (G141 PJ-5 added Projects at ⌘8).
  - `NavRailTests.swift` `testTheRailIsAppTabInItsCommandOrder`: add
    `XCTAssertEqual(RailItem.shortcut(for: .projects), "⌘8", "the eighth page, after Sources — no shortcut moved")`.
  - `CommandBarTests.swift` `testOneHelpPerWindow`: the loop becomes
    `for tab in AppTab.allCases where ![.sleep, .inbox, .graph, .clusters, .feed, .sources, .projects].contains(tab) {`
    and add `XCTAssertEqual(HelpContent.page(.projects), .projects)` above it.
  - `ListColumnsTests.swift`: the `hostsOwnReader` assertion becomes `[.clusters, .feed, .inbox, .sources, .projects]`.
  - `TitlebarHelpTests.swift`: `testHelpContentCasesAreExhaustive` lists and switches over `.projects` too; in
    `testTheInboxAnswersForItself` add `XCTAssertEqual(HelpContent.page(.projects), .projects)` and
    `XCTAssertEqual(ListHelp.projects.keys.map(\.key), ["⌘F", "↑ ↓", "⏎", "Esc"])`.
  - `CountLiteralLintTests.swift` `scope`: append `"/Views/Projects/"`, `"/Theme/Copy+Projects.swift"`,
    `"/Models/Project.swift"`, `"/Models/ProjectState.swift"`, `"/Models/RelativeDay.swift"`, and extend its doc
    comment's list with "— and the Projects page (G141 PJ-5): every row's counts and ages".
  - `SelectionTintLintTests.swift` `scoped`: append `"Views/Projects/ProjectsRows.swift"`.

- [ ] **Step 2: See them fail.**
  `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectsListTests|SidebarTabTests|NavRailTests|CommandBarTests|ListColumnsTests|TitlebarHelpTests|CountLiteralLintTests|SelectionTintLintTests' 2>&1 | tail -20`
  fails to compile (`AppTab.projects`, `ProjectsModel`, `routeToProject` unknown).

- [ ] **Step 3: The eighth page.** In `app/…/Views/Shell/AppTab.swift`:
  - the doc's first line reads "The eight primary views.";
  - after `case sources = "Sources"` add:

```swift
    /// G141 PJ-5 — the eighth page, ⌘8 (owner ruling 2026-09-23: the first free cell after Sources, so no existing
    /// shortcut moves; DESIGN_RULES §9, DR-22). A new raw value, so `restored(from:)` needs no mapping.
    case projects = "Projects"
```

  - in `icon`, after `case .sources: "tray.2"` add `case .projects: "point.topleft.down.to.point.bottomright.curvepath"`
    (spec §11.1's glyph; an outline, DR-53);
  - `hostsOwnReader` becomes `case .inbox, .clusters, .feed, .sources, .projects: true`, and its doc adds "and
    Projects (G141 PJ-5)".

  In `NavRail.swift`'s doc (`:18`) "⌘1–7" becomes "⌘1–8". In `ContentView.swift`'s two comments (`:222`, `:226`)
  and `Theme/ZoomKeyRouter.swift`'s doc (`:31`) "⌘1–7" becomes "⌘1–8" (the last three places the digit range is
  spelled; `rg -n "1–7" app/CicadaApp/Sources` prints nothing afterwards).

  Adding a case needs no other switch edit: the only exhaustive switches over `AppTab` are `icon` (above) and
  `ContentView.otherTabContent` (Step 10); `HelpContent.page` has a `default`.

- [ ] **Step 4: The hand-offs and the help.** In `app/…/Support/AppRouter.swift`, after `routeToClustersEntity(_:)`:

```swift
    /// G141 PJ-5 (R-PP24) — a project opened from elsewhere (a ⌘K entity row) lands in the Projects page's detail
    /// column; the tab and the id move together, `routeToFeedItem`'s reason.
    var pendingProject: String?

    func routeToProject(_ id: String) {
        closeSettings()
        pendingTab = .projects
        pendingProject = id
        activateMainWindow()
    }

    /// Read-then-clear, for `consumeAddSource`'s double-firing reason (`onAppear` and `onChange` can both see it).
    @discardableResult
    func consumeProject() -> String? {
        defer { pendingProject = nil }
        return pendingProject
    }

    /// R-PP18 — a quiet thread's "How did it go? ›" opens its follow-up's card in the Inbox; the Inbox owns answering
    /// and its Undo (DR-42). The tab and the item move together.
    func routeToInboxItem(_ id: String) {
        closeSettings()
        pendingTab = .inbox
        pendingInboxItem = id
        activateMainWindow()
    }
```

  In `app/…/Views/Shell/TitlebarHelp.swift`: add `case projects` to `HelpContent` (after `sources`); in `page(_:)` add
  `case .projects: .projects`; in `TitlebarHelpButton`'s popover switch add
  `case .projects: ListHelpPopover(page: ListHelp.projects)`; extend `HelpContent`'s doc ("…then Sources, then
  Projects —"); and after `ListHelp.sources` add:

```swift
    /// G141 PJ-5 — the Projects page's `?`: what the band means, and its keys (DR-68). Task 3 adds the band's keys and
    /// Task 5 the Log's, each with the code that answers them.
    static let projects = Page(
        title: "How Projects works",
        subtitle: "Where each project stands today: a green bar that fills up to today, what's in motion, what happened lately and what's planned. Open a project to see the rest.",
        keys: [
            .init(key: "⌘F", does: "Find on this page"),
            .init(key: "↑ ↓", does: "Move through projects"),
            .init(key: "⏎", does: "Step into the project"),
            .init(key: "Esc", does: "Close the rightmost column"),
        ])
```

- [ ] **Step 5: The open end's token.** In `app/…/Theme/CicadaTheme.swift`, after `static var progressFill`:

```swift
    /// §3.8 / R-PP9 — an unplanned project's open end: the approved mock's dash (white 22 % / black 22 %). It is drawn
    /// only past today on a bar with no plan, so it never reads as a grey remainder ("almost done").
    static var progressOpenEnd: Color { mode == .dark ? Color.white.opacity(0.22) : Color.black.opacity(0.22) }
```

- [ ] **Step 6: The list's model.** Create `app/…/Views/Projects/ProjectsModel.swift`:

```swift
import SwiftUI

/// R-PP6 — which projects a tab shows; `nil` is All. A resting project shows only under All.
enum ProjectsTab: Hashable, Sendable { case active, quiet }

/// One list row: the project, its derived state on the viewer's today, and its depth under a visible parent.
struct ProjectLine: Identifiable, Equatable {
    let row: ProjectRow
    let state: ProjectState.Output
    let depth: Int
    var id: String { row.id }
}

/// R-PP7 — a person beside a project, drawn as initials (a person has no service mark, DR-52).
struct PersonMark: Identifiable, Equatable {
    let id: String
    let name: String
    var initials: String { ProjectsModel.initials(name) }
}

/// §5.3 / DR-36 — the detail column's widths, in units: the band runs to 880 (the approved mock), text stays ≤ 760.
enum ProjectLayout {
    static let detailMaxWidth: CGFloat = 880
    static let textMaxWidth: CGFloat = 760
}

/// §3.8 / R-PP9 — the green bar's geometry, shared by the list row's mini bar and the band, so the two never disagree
/// about how full a project is. From the project's first moment (or `created`, or an earlier target — whichever is
/// first) to its end: with a plan, the latest target when it lies after today, else a week past today; with no plan, a
/// week past today and an open end — never a grey remainder that reads "almost done". The fill runs to today.
struct ProgressSpan: Equatable {
    static let tailDays = 7

    let start: ISODay
    let end: ISODay
    let today: ISODay
    let planned: Bool

    var days: Int { max(1, end - start) }
    var fill: Double { fraction(today) }

    func fraction(_ day: ISODay) -> Double { min(max(Double(day - start) / Double(days), 0), 1) }

    static func of(created: ISODay?, days: [ISODay], targets: [ISODay], planned: Bool, today: ISODay) -> ProgressSpan {
        let first = ([created].compactMap { $0 } + days + targets).min() ?? today
        let tail = today.adding(tailDays)
        let end: ISODay
        if planned, let last = targets.max(), last > today { end = last } else { end = tail }
        return ProgressSpan(start: min(first, today), end: end, today: today, planned: planned)
    }
}

/// G141 PJ-5 — what the Projects list shows, pure (the `ClustersModel` pattern). Every word that depends on today is
/// computed here from the absolute days the server sent (R-PJ6, DR-58); `today` is an argument, so a test pins it and
/// midnight re-derives the list with no network.
enum ProjectsModel {
    static func state(_ row: ProjectRow, today: ISODay) -> ProjectState.Output {
        ProjectState.state(ProjectState.Input(row), today: today)
    }

    static func shows(_ state: ProjectState.Output, tab: ProjectsTab?) -> Bool {
        switch tab {
        case .active: state.section == .inMotion
        case .quiet: state.section == .quiet
        case nil: true
        }
    }

    /// DR-46 — find matches a project's name and one-liner, folded as the palette folds (one ranker, `QuickMatch`).
    static func matches(_ row: ProjectRow, query: String) -> Bool {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return true }
        return QuickMatch.matches(q, fields: [QuickMatch.Field(row.name, weight: QuickMatch.Weight.name),
                                             QuickMatch.Field(row.oneLiner, weight: QuickMatch.Weight.keyword)])
    }

    /// The rows in the server's order (newest activity first), each parent followed by its shown children (§11.2),
    /// at most two levels deep; a child whose parent is not shown sits flat.
    static func lines(_ rows: [ProjectRow], tab: ProjectsTab?, query: String, today: ISODay) -> [ProjectLine] {
        let states = Dictionary(rows.map { ($0.id, state($0, today: today)) }, uniquingKeysWith: { first, _ in first })
        let visible = rows.filter { shows(states[$0.id] ?? state($0, today: today), tab: tab) && matches($0, query: query) }
        let ids = Set(visible.map(\.id))
        var out: [ProjectLine] = []
        var placed = Set<String>()
        func append(_ row: ProjectRow, depth: Int) {
            guard placed.insert(row.id).inserted else { return }
            out.append(ProjectLine(row: row, state: states[row.id] ?? state(row, today: today), depth: depth))
            guard depth < 2 else { return }
            for child in visible where child.parent == row.id { append(child, depth: depth + 1) }
        }
        for row in visible where row.parent.map({ !ids.contains($0) }) ?? true { append(row, depth: 0) }
        for row in visible where !placed.contains(row.id) { append(row, depth: 0) }   // a cycle never hides a row
        return out
    }

    static func tabs(_ rows: [ProjectRow], today: ISODay) -> [TextTab<ProjectsTab>] {
        let sections = rows.map { state($0, today: today).section }
        return [TextTab(id: .active, label: Copy.Projects.active, count: sections.filter { $0 == .inMotion }.count),
                TextTab(id: .quiet, label: Copy.Projects.quiet, count: sections.filter { $0 == .quiet }.count),
                TextTab(id: nil, label: Copy.Lists.all, count: rows.count)]
    }

    /// R-PP6 — Active unless nothing is in motion, then All.
    static func defaultTab(_ rows: [ProjectRow], today: ISODay) -> ProjectsTab? {
        rows.contains { state($0, today: today).section == .inMotion } ? .active : nil
    }

    /// DR-25 — "Projects · 6 active"; with a project open, "Projects · 1 of 6 · Planned" (the mock); R-PP8's
    /// "still indexing" while the server says `partial`.
    static func eyebrow(visible: Int, tab: ProjectsTab?, position: Int?, openPlanned: Bool?, partial: Bool) -> String {
        let indexing = partial ? Copy.Projects.stillIndexing : ""
        if let openPlanned {
            return Eyebrow.text(Copy.Projects.page, position.map { Copy.Projects.position($0, of: visible) } ?? "",
                                openPlanned ? Copy.Projects.planned : Copy.Projects.noPlanYet, indexing)
        }
        let count: String
        switch tab {
        case .active: count = Copy.Projects.countActive(visible)
        case .quiet: count = Copy.Projects.countQuiet(visible)
        case nil: count = UsageFormat.count(visible)
        }
        return Eyebrow.text(Copy.Projects.page, count, indexing)
    }

    /// R-PP7 — where a project stands now, the first rung that holds (a missing fact never shows a guess).
    static func nowLine(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        let st = line.state
        if let live = row.openThreads.filter({ !st.isQuiet($0.claimId) }).max(by: { $0.since < $1.since }) {
            return live.text
        }
        if let quiet = row.openThreads.first {
            return Copy.Projects.quietThread(days: st.thread(quiet.claimId)?.quietDays ?? 0, text: quiet.text)
        }
        let last = ISODay(row.lastMomentDay)
        switch st.section {
        case .quiet:
            return Copy.Projects.quietFor(days: last.map { today - $0 } ?? 0)
        case .resting:
            return last.map { Copy.Projects.resting(lastHeard: RelativeDay.absolute($0, today: today, locale: locale)) }
                ?? Copy.Projects.nothingHeard
        case .inMotion:
            if !row.oneLiner.isEmpty { return row.oneLiner }
            return last.map { Copy.Projects.lastHeard(RelativeDay.absolute($0, today: today, locale: locale)) }
                ?? Copy.Projects.nothingHeard
        }
    }

    /// "Next · First grasp, Oct 1", "Next · First grasp, overdue since Sep 9", "1 of 4 done" or "No plan yet" — never
    /// red (DR-7) and never a percentage (R-PJ11). Progress is the server's (`row.progress`): a row carries only five
    /// milestones, so counting them here could undercount.
    static func nextLine(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        if let slug = line.state.next, let m = row.milestones.first(where: { $0.slug == slug }) {
            guard let target = ISODay(m.target) else { return Copy.Projects.next(m.name, nil) }
            let day = RelativeDay.absolute(target, today: today, locale: locale)
            return target < today ? Copy.Projects.nextOverdue(m.name, since: day) : Copy.Projects.next(m.name, day)
        }
        return row.planned ? Copy.Projects.doneOf(row.progress) : Copy.Projects.noPlanYet
    }

    /// The triage row's second line: "1 of 4 done · First grasp Oct 1", or "No plan yet · last Sep 14".
    static func shortLine(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        guard row.planned else {
            return Copy.Projects.noPlanLast(ISODay(row.lastMomentDay).map { RelativeDay.absolute($0, today: today, locale: locale) })
        }
        let next = line.state.next.flatMap { slug in row.milestones.first { $0.slug == slug } }.map { m in
            Copy.Projects.nextShort(m.name, ISODay(m.target).map { RelativeDay.absolute($0, today: today, locale: locale) })
        }
        return Copy.Projects.shortPlanned(row.progress, next: next)
    }

    /// DR-58 — the compact age, with the full date as its `.help` ("—" with its reason when nothing happened yet).
    static func age(_ row: ProjectRow, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String) {
        let last = ISODay(row.lastMomentDay)
        return (RelativeDay.compactAge(last, today: today),
                last.map { Copy.Projects.lastActivity(RelativeDay.full($0, locale: locale)) } ?? Copy.Projects.noActivity)
    }

    static func questions(_ row: ProjectRow) -> String? {
        row.followups > 0 ? Copy.Projects.questions(row.followups) : nil
    }

    static func accessibilityLabel(_ line: ProjectLine) -> String {
        Copy.Projects.rowLabel(line.row.name, planned: line.row.planned, progress: line.row.progress)
    }

    static func bar(_ row: ProjectRow, today: ISODay) -> ProgressSpan {
        let days = (row.activity.map(\.day) + [row.lastMomentDay].compactMap { $0 } + row.openThreads.map(\.since))
            .compactMap { ISODay($0) }
        let targets = row.milestones.flatMap { [ISODay($0.target), ISODay($0.doneOn)].compactMap { $0 } }
        return ProgressSpan.of(created: ISODay(row.created), days: days, targets: targets, planned: row.planned,
                               today: today)
    }

    /// The same span over the detail's fuller data — the band's (R-PP9).
    static func span(_ t: ProjectTimeline, planned: Bool, today: ISODay) -> ProgressSpan {
        let items = t.items.filter { $0.kind != "created" }.compactMap { ISODay($0.day) }
        let threads = t.now.threads.compactMap { ISODay($0.since) }
        let targets = t.milestones.filter { $0.source != "expectedEnd" }.flatMap { m in
            [ISODay(m.target), ISODay(m.doneOn), earlierTarget(m)].compactMap { $0 }
        }
        return ProgressSpan.of(created: ISODay(t.project.created), days: items + threads, targets: targets,
                               planned: planned, today: today)
    }

    /// A moved milestone's previous target: the newest earlier claim in its chain — a `milestone`'s `target`, or a
    /// read-compat `due`'s own date, its `object` — so the chain crosses the `due` → `milestone` hop (R-PJ4).
    static func earlierTarget(_ m: ProjectMilestone) -> ISODay? {
        guard m.moved, m.chain.count > 1 else { return nil }
        let head = ISODay(m.target)
        for claim in m.chain.dropFirst() {
            if let day = ISODay(claim.target) ?? (claim.predicate == "due" ? ISODay(claim.object) : nil), day != head {
                return day
            }
        }
        return nil
    }

    /// A mark's hover words: the sentence's first six words.
    static func firstWords(_ text: String, count: Int = 6) -> String {
        let words = text.split(separator: " ")
        return words.count > count ? words.prefix(count).joined(separator: " ") + "…" : text
    }

    /// R-PP7 — each project's `person` neighbours in the graph the Store holds, the owner and facets left out, at most
    /// three, by degree then name. `ProjectRow` carries no people; this is data the app already has.
    static func peopleIndex(_ graph: GraphResponse?) -> [String: [PersonMark]] {
        guard let graph else { return [:] }
        var nodes: [String: GraphNode] = [:]
        for node in graph.nodes where !node.isFacet { nodes[node.id] = node }
        var found: [String: [GraphNode]] = [:]
        for edge in graph.links {
            for (a, b) in [(edge.source, edge.target), (edge.target, edge.source)] {
                guard let project = nodes[a], project.type == .project,
                      let person = nodes[b], person.type == .person, !person.isOwner,
                      !(found[a]?.contains { $0.id == person.id } ?? false) else { continue }
                found[a, default: []].append(person)
            }
        }
        return found.mapValues { people in
            people.sorted { ($0.degree, $1.name) > ($1.degree, $0.name) }.prefix(3).map { PersonMark(id: $0.id, name: $0.name) }
        }
    }

    static func initials(_ name: String) -> String {
        name.split(separator: " ").prefix(2).compactMap(\.first).map { String($0).uppercased() }.joined()
    }

    /// R-PP24 — a ⌘K entity row lands in Projects when its node is a project.
    static func isProject(_ id: String, in graph: GraphResponse?) -> Bool {
        graph?.nodes.contains { $0.id == id && $0.type == .project } ?? false
    }
}
```

- [ ] **Step 7: The rows.** Create `app/…/Views/Projects/ProjectsRows.swift`:

```swift
import SwiftUI

/// What the list column says before it has rows to draw, in precedence order (DR-43, DR-50).
enum ProjectsListState: Equatable {
    case loading, failed(String), empty, tabEmpty, noMatch, list

    static func of(phase: ProjectsCache.Phase, hasList: Bool, rows: Int, lines: Int, finding: Bool) -> ProjectsListState {
        if !hasList {
            if case .failed(let message) = phase { return .failed(message) }
            return .loading
        }
        if rows == 0 { return .empty }
        if lines == 0 { return finding ? .noMatch : .tabEmpty }
        return .list
    }
}

/// §5.3 / §10 — the Projects list in its three styles (R-PP7): one line at full width, two lines beside a project,
/// titles beside a project and the Reader. Selection is `bgSelected`, never the accent (DR-22, `SelectionTintLintTests`).
struct ProjectsListColumn: View {
    let lines: [ProjectLine]
    let style: ColumnPlan.ListStyle
    let today: ISODay
    let people: [String: [PersonMark]]
    let state: ProjectsListState
    let tab: ProjectsTab?
    let query: String
    @Binding var findOpen: Bool
    @Binding var findText: String
    let openId: String?
    let open: (String) -> Void
    let move: (Int) -> Void
    let focusDetail: () -> Void
    let escape: () -> Void
    let retry: () -> Void

    var body: some View {
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // DR-46 — the find row sits above the scroll (Clusters' reason: a lazy row scrolled away is released).
                if findOpen {
                    PageFindRow(text: $findText, isOpen: $findOpen, prompt: Copy.Projects.find)
                        .padding(EdgeInsets(top: 0, leading: ListInsets.of(style).leading, bottom: CicadaTheme.spacingSM,
                                            trailing: ListInsets.of(style).trailing))
                }
                ScrollView {
                    LazyVStack(alignment: .leading,
                               spacing: style == .triage ? CicadaTheme.scaled(RowMetrics.twoLineGap) : 0) {
                        switch state {
                        case .loading:
                            ListSkeleton(message: Copy.Projects.gathering)
                        case .failed(let message):
                            ListErrorCard(title: Copy.Projects.loadFailedTitle, message: message, retry: retry)
                        case .empty:
                            EmptyStateView(title: Copy.Projects.emptyTitle, message: Copy.Projects.emptyMessage)
                        case .tabEmpty:
                            note(tab == .quiet ? Copy.Projects.noneQuiet : Copy.Projects.noneActive)
                        case .noMatch:
                            note(Copy.Projects.noMatch(query.trimmingCharacters(in: .whitespaces)))
                        case .list:
                            ForEach(lines) { line in
                                ProjectRowView(line: line, style: style, today: today, people: people[line.id] ?? [],
                                               selected: line.id == openId) { open(line.id) }
                                    .id(line.id)
                            }
                        }
                    }
                    .padding(ListInsets.of(style))
                }
                .onChange(of: openId) { _, id in
                    guard let id else { return }
                    Instant.run { proxy.scrollTo(id) }
                }
            }
        }
        .listKeys(move: move, enter: {
            guard openId != nil else { return false }
            focusDetail()
            return true
        }, escape: escape)
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(10))
    }
}

/// One project (R-PP7). The whole row opens it; the chevron is its visible twin, outside the row's button (a button
/// nested in a button is two targets for one click). Ages and counts are tabular (DR-21); ids only in `.help` (DR-54).
struct ProjectRowView: View {
    let line: ProjectLine
    let style: ColumnPlan.ListStyle
    let today: ISODay
    let people: [PersonMark]
    let selected: Bool
    let action: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            Button(action: action) { content }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel(ProjectsModel.accessibilityLabel(line))
                .accessibilityAddTraits(selected ? [.isSelected] : [])
            if style == .wide {
                IconButton(systemName: "chevron.right", help: Copy.Projects.openHelp, action: action)
            }
        }
        .listRowSurface(height: ListRowSurface.height(style), selected: selected)
    }

    private var indent: CGFloat { CicadaTheme.scaled(CGFloat(line.depth) * (style == .wide ? 16 : 12)) }
    private var tertiary: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }

    @ViewBuilder
    private var content: some View {
        let row = line.row
        let age = ProjectsModel.age(row, today: today)
        let bar = ProjectsModel.bar(row, today: today)
        let barHelp = Copy.Projects.barHelp(planned: row.planned, progress: row.progress)
        switch style {
        case .wide:
            HStack(spacing: CicadaTheme.scaled(10)) {
                TypeDot(type: .project).padding(.leading, indent)
                Text(row.name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .frame(width: max(CicadaTheme.scaled(220) - indent, 0), alignment: .leading)
                Text(ProjectsModel.nowLine(line, today: today))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                Spacer(minLength: 0)
                ProgressBarView(span: bar, width: 64, help: barHelp)
                Text(ProjectsModel.nextLine(line, today: today))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(tertiary)
                    .lineLimit(1)
                    .frame(width: CicadaTheme.scaled(200), alignment: .leading)
                PeopleMarks(people: people, knockout: selected ? CicadaTheme.bgSelected : CicadaTheme.bgBase)
                    .frame(width: CicadaTheme.scaled(64), alignment: .trailing)
                Text(ProjectsModel.questions(row) ?? "")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(tertiary)
                    .frame(width: CicadaTheme.scaled(74), alignment: .trailing)
                Text(age.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(tertiary)
                    .frame(width: CicadaTheme.scaled(40), alignment: .trailing)
                    .help(age.help)
            }
        case .triage:
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(5)) {
                HStack(spacing: CicadaTheme.scaled(10)) {
                    TypeDot(type: .project).padding(.leading, indent)
                    Text(row.name)
                        .font(selected ? CicadaTheme.rowFont : CicadaTheme.bodyFont)
                        .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Text(age.text).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(tertiary).help(age.help)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressBarView(span: bar, width: 40, help: barHelp)
                    Text(ProjectsModel.shortLine(line, today: today))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(tertiary)
                        .lineLimit(1)
                }
                .padding(.leading, indent + CicadaTheme.scaled(18))
            }
        case .titles, .hidden:
            HStack(spacing: CicadaTheme.scaled(10)) {
                TypeDot(type: .project).padding(.leading, indent)
                Text(row.name)
                    .font(selected ? CicadaTheme.rowFont : CicadaTheme.bodyFont)
                    .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .help(row.name)
                Spacer(minLength: 0)
            }
        }
    }
}

/// §3.8 / R-PP9 — the mini bar: `progressFill` from the first moment to today on the `bgBadge` track; with no plan,
/// the fill and a dashed open end, never a grey remainder. Solid, never a gradient; its words are its `.help` and its
/// accessibility label, since the track itself is not held to 3:1 (§3.8, disclosed).
struct ProgressBarView: View {
    let span: ProgressSpan
    let width: CGFloat
    let help: String

    var body: some View {
        let w = CicadaTheme.scaled(width)
        let h = CicadaTheme.scaled(4)
        let filled = max(h, w * CGFloat(span.fill))
        ZStack(alignment: .leading) {
            if span.planned {
                Capsule().fill(CicadaTheme.bgBadge)
            } else {
                MidLine()
                    .stroke(CicadaTheme.progressOpenEnd, style: StrokeStyle(lineWidth: 2, dash: [3, 2]))
                    .padding(.leading, filled + 2)
            }
            Capsule().fill(CicadaTheme.progressFill).frame(width: filled)
        }
        .frame(width: w, height: h)
        .help(help)
        .accessibilityElement()
        .accessibilityLabel(help)
    }
}

/// A horizontal line through the middle of its frame — the open end, and a quiet thread's dashed tail.
struct MidLine: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        }
    }
}

/// R-PP7 — up to three people as initials in neutral circles, overlapped and knocked out of the row's own fill.
struct PeopleMarks: View {
    let people: [PersonMark]
    let knockout: Color

    var body: some View {
        HStack(spacing: -CicadaTheme.scaled(4)) {
            ForEach(people) { person in
                Text(person.initials)
                    .font(CicadaTheme.font(size: 9, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(20), height: CicadaTheme.scaled(20))
                    .background(Circle().fill(CicadaTheme.bgButton))
                    .background(Circle().fill(knockout).padding(-2))
                    .help(person.name)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(people.isEmpty ? "" : Copy.Projects.people(people.map(\.name)))
    }
}
```

- [ ] **Step 8: The detail column's heading.** Create `app/…/Views/Projects/ProjectDetailColumn.swift`:

```swift
import SwiftUI

/// §5.3 STATE 1 — one project beside the list. The heading is DR-16's H1 role (`displayFont(size: 22)`): a
/// sub-project's "Part of <parent> ›" above it, the name with its "Project" tag, the one-liner; the column's controls
/// are "‹ N projects" when DR-27 hid the list, and Close ×. Under it, the band's header line — "Since Jul 15" and "1 of
/// 4 done" (or "No plan yet") — and the band itself from Task 3. It reads `ProjectsCache` (R-PP3): a skeleton on a
/// first open, words when the project is gone, the error card with Retry — never a blank (DR-43).
struct ProjectDetailColumn: View {
    let projectId: String
    let row: ProjectRow?
    let parentName: String?
    let today: ISODay
    let gutter: CGFloat
    let hiddenListCount: Int?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void
    let openProject: (String) -> Void

    @Environment(ProjectsCache.self) private var cache

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let t = cache.display(projectId) {
                content(t)
            } else {
                header(name: row?.name ?? "", oneLiner: row?.oneLiner ?? "", parent: row?.parent)
                switch cache.phase(projectId) {
                case .gone:
                    Text(Copy.Projects.gone)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .padding(.top, CicadaTheme.spacingLG)
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.projectFailedTitle, message: message) {
                        Task { await cache.refreshTimeline(projectId) }
                    }
                default:
                    ListSkeleton(message: Copy.Projects.reading).padding(.top, CicadaTheme.spacingLG)
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.detailMaxWidth), maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        // R-DG11's reason — focus inside the column still reaches the page's Esc order (DR-28).
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape() }
        .task(id: projectId) { await cache.refreshTimeline(projectId) }
    }

    @ViewBuilder
    private func content(_ t: ProjectTimeline) -> some View {
        let state = ProjectState.state(ProjectState.Input(t), today: today)
        header(name: t.project.name, oneLiner: t.project.oneLiner, parent: t.project.parent)
        bandHeader(t, state: state)
        Spacer(minLength: 0)
    }

    private func header(name: String, oneLiner: String, parent: String?) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let n = hiddenListCount {
                    TextButton(title: Copy.Projects.projectsBack(n), help: Copy.Lists.showList, action: onShowList)
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
                if let parent, let parentName {
                    InlineLink(title: Copy.Projects.partOf(parentName), help: Copy.Projects.openHelp) { openProject(parent) }
                }
                Spacer(minLength: 0)
                IconButton(systemName: "xmark", help: Copy.Projects.closeHelp, action: onClose)
            }
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(10)) {
                Text(name)
                    .font(CicadaTheme.displayFont(size: 22))
                    .tracking(CicadaTheme.displayTracking(size: 22))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                Tag(text: Copy.Projects.tag, dot: CicadaTheme.entityColor(for: .project))
            }
            if !oneLiner.isEmpty {
                Text(oneLiner)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2)
            }
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    /// The band's header line (the mock): where the green starts, and "N of M done" in words (R-PJ11: never a
    /// percentage) — or "No plan yet", which Task 5 follows with "Add a milestone".
    private func bandHeader(_ t: ProjectTimeline, state: ProjectState.Output) -> some View {
        let span = ProjectsModel.span(t, planned: state.planned, today: today)
        return HStack(spacing: CicadaTheme.scaled(6)) {
            Text(Copy.Projects.since(RelativeDay.absolute(span.start, today: today)))
                .foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: 0)
            Text(state.planned ? Copy.Projects.doneOf(state.progress) : Copy.Projects.noPlanYet)
                .fontWeight(state.planned ? .medium : .regular)
                .foregroundStyle(state.planned ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                .help(Copy.Projects.barHelp(planned: state.planned, progress: state.progress))
        }
        .font(CicadaTheme.metaFont)
        .monospacedDigit()
        .frame(height: CicadaTheme.scaled(22))
        .padding(.top, CicadaTheme.scaled(18))
    }
}
```

- [ ] **Step 9: The page.** Create `app/…/Views/Projects/ProjectsPage.swift`:

```swift
import SwiftUI

/// G141 PJ-5 — the Projects page (DESIGN_RULES §10, the first screen designed for D): a list page in progressive
/// columns (§5.3). STATE 0 is every project as a one-line row; a click narrows the list to the triage column and opens
/// the project beside it; its evidence opens the Reader as the third column, which this page hosts itself
/// (`AppTab.hostsOwnReader`, R-DL7). Its data is `ProjectsCache` — not a Store domain (R-PJ7, R-PP3).
struct ProjectsPage: View {
    @Environment(Store.self) private var store
    @Environment(ProjectsCache.self) private var cache
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var columns = ListColumns<String>()
    @State private var tab: ProjectsTab? = .active
    /// R-PP6 — until the viewer picks a tab, the page follows `defaultTab` as the list arrives.
    @State private var tabChosen = false
    @State private var query = ""
    @State private var findOpen = false
    /// R-PP5 — the viewer's today; `.NSCalendarDayChanged` moves it and every word re-derives with no network.
    @State private var today = ISODay.today()
    @FocusState private var focus: ListFocus?

    private var rows: [ProjectRow] { cache.list?.projects ?? [] }

    /// DR-45 — a tab switch is instant; a project the new tab does not show closes (R-DL6: a tab is navigation).
    private var tabSelection: Binding<ProjectsTab?> {
        Binding(get: { tab }, set: { newTab in
            Instant.run {
                tab = newTab
                tabChosen = true
                if let id = columns.openId,
                   !ProjectsModel.lines(rows, tab: newTab, query: "", today: today).contains(where: { $0.id == id }) {
                    columns.close()
                }
            }
        })
    }

    var body: some View {
        let lines = ProjectsModel.lines(rows, tab: tab, query: findOpen ? query : "", today: today)
        let people = ProjectsModel.peopleIndex(store.graph.value)
        let openId = columns.openId
        ProgressiveColumns(hasDetail: openId != nil, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: eyebrow(lines),
                       horizontalPadding: openId == nil && !provenance.isPresented ? plan.gutter : CicadaTheme.spacingXL) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    AdaptiveTextTabs(tabs: ProjectsModel.tabs(rows, today: today), selection: tabSelection,
                                     menuTitle: Copy.Projects.tabMenu)
                    PageFindButton(isOpen: $findOpen).padding(.leading, CicadaTheme.spacingSM)
                }
            }
            .help(cache.list?.partial == true ? Copy.Projects.stillIndexingHelp : "")
        } list: { plan in
            ProjectsListColumn(
                lines: lines, style: plan.listStyle, today: today, people: people,
                state: ProjectsListState.of(phase: cache.listPhase, hasList: cache.list != nil, rows: rows.count,
                                            lines: lines.count,
                                            finding: findOpen && !query.trimmingCharacters(in: .whitespaces).isEmpty),
                tab: tab, query: query, findOpen: $findOpen, findText: $query, openId: openId,
                open: { openProject($0) }, move: { move($0, in: lines) },
                focusDetail: { focus = .detail }, escape: { escape() },
                retry: { Task { await cache.refreshList() } })
                .focused($focus, equals: .list)
        } detail: { plan in
            if let id = openId {
                let row = rows.first { $0.id == id }
                ProjectDetailColumn(
                    projectId: id, row: row, parentName: parentName(of: row?.parent), today: today, gutter: plan.gutter,
                    hiddenListCount: plan.listHidden ? lines.count : nil,
                    onShowList: { showList() }, onClose: { closeProject() }, onEscape: { escape() },
                    openProject: { openProject($0) })
                    .id(id)
                    .focused($focus, equals: .detail)
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
        .background(CicadaTheme.bgBase)
        // DR-46 — ⌘F opens the find row; published from a leaf (Clusters' reason: an if/else on the page rebuilt it).
        .background { Color.clear.publishesPageFind(enabled: !findOpen) { findOpen = true } }
        .onChange(of: findOpen) { _, isOpen in if !isOpen { query = "" } }
        .task { await cache.refreshList() }
        .onAppear { openPendingProject(); arrive() }
        .onChange(of: router.pendingProject) { _, _ in openPendingProject() }
        .onChange(of: cache.list?.projects.map(\.id)) { _, ids in
            guard let ids else { return }
            columns.reconcile(present: Set(ids))
            if !tabChosen { tab = ProjectsModel.defaultTab(rows, today: today) }
        }
        // R-PP3 — a sync version event that moved what the ETags fold asks again (a 304 costs nothing).
        .onChange(of: store.version) { old, new in
            guard ProjectsRefresh.shouldRevalidate(old: old, new: new) else { return }
            Task {
                await cache.refreshList()
                if let id = columns.openId { await cache.refreshTimeline(id) }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in today = ISODay.today() }
    }

    private func eyebrow(_ lines: [ProjectLine]) -> String {
        guard let list = cache.list else { return Copy.Projects.page }
        let openId = columns.openId
        let position = openId.flatMap { id in lines.firstIndex { $0.id == id }.map { $0 + 1 } }
        let openPlanned = openId.flatMap { id in rows.first { $0.id == id }?.planned }
        return ProjectsModel.eyebrow(visible: lines.count, tab: tab, position: position, openPlanned: openPlanned,
                                     partial: list.partial)
    }

    private func parentName(of id: String?) -> String? {
        guard let id else { return nil }
        return rows.first { $0.id == id }?.name ?? store.entityNames.name(for: id)
    }

    // MARK: - Paths (a pointer path may animate, a keyboard path never does — DR-60)

    /// STATE 0 → 1 narrows the list on the drawer curve; a swap in place is instant (DR-61). A Reader the old project
    /// opened closes with it (DR-29).
    private func openProject(_ id: String) {
        let change = {
            columns.open(id)
            if provenance.isPresented { provenance.close() }
        }
        if columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        focus = .list
    }

    private func move(_ delta: Int, in lines: [ProjectLine]) {
        Instant.run {
            guard let next = columns.neighbour(delta, in: lines.map(\.id)) else { return }
            columns.open(next)
            if provenance.isPresented { provenance.close() }
        }
    }

    /// DR-28 — Esc closes the rightmost open thing.
    private func escape() {
        Instant.run {
            switch columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeDetail:
                columns.close()
                focus = .list
            case .none: break
            }
        }
    }

    private func closeProject() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            columns.close()
        }
        focus = .list
    }

    /// DR-27 — "‹ N projects" brings the list back by closing the Reader, else the project.
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else { columns.close() }
        }
    }

    /// R-PP24 — a ⌘K project row lands here. Read-then-clear; a project the tab hides opens All first, so its row is
    /// drawn (R-DL12's reason).
    private func openPendingProject() {
        guard let id = router.consumeProject() else { return }
        Instant.run {
            findOpen = false
            query = ""
            if !ProjectsModel.lines(rows, tab: tab, query: "", today: today).contains(where: { $0.id == id }) {
                tab = nil
                tabChosen = true
            }
            columns.open(id)
        }
    }

    /// R-DL8 — the list takes the keys when the page appears (deferred one turn, R-DL4's reason).
    private func arrive() {
        DispatchQueue.main.async { focus = .list }
    }
}
```

- [ ] **Step 10: Mount it.** In `app/…/CicadaApp.swift`, beside `provenanceCache` (`:43`):

```swift
    /// G141 PJ-5 (R-PP3) — the Projects page's in-memory cache; app-level so a tab switch keeps what was read.
    @State private var projectsCache = ProjectsCache()
```

  and after `.environment(provenanceCache)` (`:153`) add `.environment(projectsCache)`.

  In `app/…/ContentView.swift`:
  - after `@Environment(ProvenanceCache.self) private var provenanceCache` (`:48`) add
    `@Environment(ProjectsCache.self) private var projectsCache`;
  - in the bank-switch `.onChange(of: store.bank)` block that calls `provenanceCache.reset()` (`:88-92`), add
    `projectsCache.reset()` and extend its comment "…and the Projects cache: project ids repeat across banks (R-PP3)";
  - in `openFind(_:)`, insert directly above `case .entity(let id), .belief(let id, _):` (`:316`):

```swift
        case .entity(let id) where ProjectsModel.isProject(id, in: store.graph.value):
            // G141 PJ-5 (R-PP24, spec §11.1) — a project opens where it is tracked: Projects, its detail open.
            router.routeToProject(id)
```

  - in `otherTabContent`, after the `.sources` case (`:451-457`) add:

```swift
        case .projects:
            ProjectsPage()
```

- [ ] **Step 11: Green.**
  `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectsListTests|SidebarTabTests|NavRailTests|CommandBarTests|ListColumnsTests|TitlebarHelpTests|CountLiteralLintTests|SelectionTintLintTests|FontLiteralLintTests|RelativeDayTests' 2>&1 | tail -20`
  passes; then `swift build 2>&1 | tail -5` and the full `swift test 2>&1 | tail -20` (0 failures).

- [ ] **Step 12: Commit.**

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsModel.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsPage.swift app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsRows.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectDetailColumn.swift app/CicadaApp/Sources/CicadaApp/Views/Shell/AppTab.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Shell/NavRail.swift app/CicadaApp/Sources/CicadaApp/Views/Shell/TitlebarHelp.swift \
  app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift \
  app/CicadaApp/Sources/CicadaApp/CicadaApp.swift app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift \
  app/CicadaApp/Sources/CicadaApp/Theme/ZoomKeyRouter.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProjectsListTests.swift app/CicadaApp/Tests/CicadaAppTests/SidebarTabTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/NavRailTests.swift app/CicadaApp/Tests/CicadaAppTests/CommandBarTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/ListColumnsTests.swift app/CicadaApp/Tests/CicadaAppTests/TitlebarHelpTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/CountLiteralLintTests.swift app/CicadaApp/Tests/CicadaAppTests/SelectionTintLintTests.swift
cd <worktree> && git commit -m "feat(projects): Projects is the eighth page — the list at D density with a mini green bar, in progressive columns (G141 PJ-5, R-PP3, R-PP6…R-PP9, R-PP24; DR-5, DR-8, DR-21, DR-22, DR-25…DR-31, DR-34, DR-40, DR-43, DR-45, DR-46, DR-48, DR-50, DR-54, DR-58, DR-60, DR-68, DR-70; §3.8)"
```

---

### Task 3: The band — a green bar that fills up to today, every node clickable (§3.8, §9's band ruling, §10 Projects; DR-5, DR-8, DR-16, DR-28, DR-29, DR-31, DR-53, DR-55, DR-57, DR-60, DR-68, DR-69, DR-70; R-PP10…R-PP12, R-PP16; R-PJ4, R-PJ21, R-PJ22)

The owner's band. `BandLayout` turns a timeline into marks at the mock's coordinates, pure and tested on the demo's
wire; `ProjectBandView` draws it over a `Canvas` with every mark a real button. A pick rings the mark, ←/→ walk the
band, ⏎ opens the mark's source in the Reader through `ProjectSource`, which also decides every source line Task 4
draws.

**Files:**
- Create: `app/…/Views/Projects/ProjectBand.swift`, `ProjectSource.swift`.
- Modify: `app/…/Views/Projects/ProjectDetailColumn.swift` (the band under its header line; selection; keys),
  `app/…/Views/Shell/TitlebarHelp.swift` (`ListHelp.projects` gains the band's keys).
- Test: `ProjectBandTests.swift` (new). Edit `TitlebarHelpTests.swift`, `SelectionTintLintTests.swift`.

**Interfaces:**
- Produces: `ProjectKey`, `ProjectSection`, `BandLayout` (`make`, `step(from:delta:)`, `order`, `todayX`, `x(_:)`),
  `ProjectBandView`, `BandMark`, `ProjectSource` (`Line`, `line(_:)`, `line(_:conversations:)`, `evidence(_:)`,
  `target(_:projectId:)`, `target(for:in:projectId:)`, `docIndex(_:)`).
- Consumes: Task 1–2's types; `ReaderTarget`, `ProvenanceRouter.open` / `refocus` / `close` / `current`,
  `EvidenceDocIndex`, `EvidenceDocMeta`, `Evidence`, `EvidenceKind(wire:)`, `OriginIconography.label(for:)`.

- [ ] **Step 1: Failing tests.** Create `ProjectBandTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP10…R-PP12, R-PP16 — the band's marks and where each one's words come from, pure, on the demo's wire at
/// T = 2026-09-23 and a 600-unit band (the rover spans Jul 15 → Nov 2: 110 days, 60/11 units a day).
@MainActor
final class ProjectBandTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")

    private func rover() throws -> (ProjectTimeline, BandLayout) {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let state = ProjectState.state(ProjectState.Input(t), today: today)
        return (t, BandLayout.make(t, state: state, width: 600, today: today, locale: us))
    }

    private func item(_ t: ProjectTimeline, _ kind: String, _ day: String) throws -> ProjectItem {
        try XCTUnwrap(t.items.first { $0.kind == kind && $0.day == day })
    }

    func testTheGreenFillsToTodayAgainstThePlan() throws {
        let (_, band) = try rover()
        XCTAssertTrue(band.span.planned)
        XCTAssertEqual(band.todayX, 600 * 70 / 110, accuracy: 0.01)
        XCTAssertEqual(band.months.map(\.label), ["Jul", "Aug", "Sep", "Oct", "Nov"])
        XCTAssertEqual(band.months[1].x, 600 * 17 / 110, accuracy: 0.01, "Aug 1")
        XCTAssertEqual(band.words.map(\.label), ["2 weeks ago", "in 2 weeks"])
        XCTAssertEqual(band.since, "Since Jul 15")
        XCTAssertEqual(band.progressWords, "1 of 4 done")
        XCTAssertEqual(band.next?.label, "First grasp · in 8 days")
        XCTAssertEqual(band.accessibility,
                       "Progress of Rover Arm Project, 1 of 4 milestones done. You are here, today, September 23.")
    }

    /// §3.8 — done milestones filled inside the green, planned ones hollow past today, a moved one with a dashed ghost at
    /// its earlier date and a bracket to the new one.
    func testMilestonesOwnTheTrack() throws {
        let (_, band) = try rover()
        func mark(_ slug: String, _ kind: BandLayout.Mark) -> BandLayout.Node? {
            band.nodes.first { $0.key == .milestone(slug) && $0.mark == kind }
        }
        let arm = try XCTUnwrap(mark("arm-assembled", .milestoneDone))
        XCTAssertEqual(arm.x, 600 * 25 / 110, accuracy: 0.01, "placed at its done day, Aug 9")
        XCTAssertEqual(arm.lane, .track)
        XCTAssertEqual(arm.when, "done Aug 9")
        let grasp = try XCTUnwrap(mark("first-grasp", .milestonePlanned))
        XCTAssertEqual(grasp.x, 600 * 78 / 110, accuracy: 0.01)
        let ghost = try XCTUnwrap(mark("first-grasp", .ghost))
        XCTAssertEqual(ghost.x, 600 * 56 / 110, accuracy: 0.01, "Sep 9, its earlier date")
        XCTAssertEqual(ghost.when, "Sep 9, moved Sep 10")
        XCTAssertEqual(band.brackets.count, 1)
        XCTAssertEqual(band.brackets[0].x0, ghost.x, accuracy: 0.01)
        XCTAssertEqual(band.brackets[0].x1, grasp.x, accuracy: 0.01)
        XCTAssertNotNil(mark("due-2026-11-02", .milestonePlanned))
    }

    /// R-PP10 — a happening prefers the track, a moment below; a neighbour within 12 units pushes to the next lane.
    func testLanesAreDecidedDeterministically() throws {
        let (t, band) = try rover()
        func node(_ item: ProjectItem) -> BandLayout.Node? { band.nodes.first { $0.key == .item(item.id) } }
        let started = try XCTUnwrap(node(try item(t, "happening", "2026-07-15")))
        XCTAssertEqual(started.lane, .track)
        XCTAssertEqual(started.mark, .done)
        let assembled = try XCTUnwrap(node(try item(t, "happening", "2026-08-09")))
        XCTAssertEqual(assembled.lane, .below, "the arm-assembled milestone holds the track on Aug 9")
        let guide = try XCTUnwrap(node(try item(t, "happening", "2026-09-22")))
        XCTAssertEqual(guide.lane, .track)
        XCTAssertEqual(guide.label, "Bob got the lab cluster onboarding…")
        XCTAssertEqual(guide.when, "Yesterday")
        let specs = try XCTUnwrap(node(try item(t, "moment", "2026-09-22")))
        XCTAssertEqual(specs.mark, .said)
        XCTAssertEqual(specs.lane, .below)
        XCTAssertNil(node(try item(t, "happening", "2026-09-23")), "an ongoing happening is a thread, never a dot")
    }

    /// Threads end in an open cap at today; a quiet one fades after its last-heard day.
    func testThreadsRunToTodayAndFadeWhenQuiet() throws {
        let (t, band) = try rover()
        let camera = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" })
        let connecting = try XCTUnwrap(t.now.threads.first { $0.since == "2026-09-23" })
        let quiet = try XCTUnwrap(band.threads.first { $0.key == .thread(camera.claimId) })
        XCTAssertEqual(quiet.x0, 600 * 46 / 110, accuracy: 0.01)
        XCTAssertEqual(quiet.x1, band.todayX, accuracy: 0.01)
        XCTAssertEqual(quiet.solid, 0, accuracy: 0.0001, "quiet since the day it started: all dashed")
        XCTAssertEqual(quiet.cap, .open)
        XCTAssertEqual(quiet.when, "since Aug 30 · quiet 24 days")
        let live = try XCTUnwrap(band.threads.first { $0.key == .thread(connecting.claimId) })
        XCTAssertEqual(live.solid, 1)
        XCTAssertEqual(live.when, "started today")
        XCTAssertLessThanOrEqual(band.threads.count, BandLayout.threadRows)
    }

    /// ←/→ walk every mark left to right; a ghost is no stop (it selects its milestone).
    func testTheKeysWalkTheBandInOrder() throws {
        let (t, band) = try rover()
        let order = band.order
        XCTAssertEqual(order.first, .item(try item(t, "happening", "2026-07-15").id))
        XCTAssertEqual(order.last, .milestone("due-2026-11-02"))
        XCTAssertEqual(order.filter { $0 == .milestone("first-grasp") }.count, 1)
        XCTAssertEqual(band.step(from: nil, delta: 1), order.first)
        XCTAssertEqual(band.step(from: nil, delta: -1), order.last)
        XCTAssertEqual(band.step(from: order.last, delta: 1), order.last, "clamped at the end")
        XCTAssertEqual(band.step(from: order[0], delta: 1), order[1])
    }

    /// No plan: the fill runs to today and the end stays open; nothing is invented to fill the right side.
    func testAnUnplannedProjectHasAnOpenEnd() throws {
        let t = try ProjectFixtures.timeline("garden-sensor-project")
        let band = BandLayout.make(t, state: ProjectState.state(ProjectState.Input(t), today: today), width: 590,
                                   today: today, locale: us)
        XCTAssertFalse(band.span.planned)
        XCTAssertNil(band.progressWords)
        XCTAssertNil(band.next)
        XCTAssertEqual(band.todayX, 590 * 52 / 59, accuracy: 0.01)
        XCTAssertTrue(band.nodes.allSatisfy { $0.mark == .said }, "three moments, no milestone")
        XCTAssertTrue(band.accessibility.contains("no plan yet"))
    }

    /// A window past 540 days keeps the last 365 and folds the rest into one "N earlier" mark.
    func testALongWindowFoldsTheOldestIntoOneMark() throws {
        var t = try ProjectFixtures.timeline("garden-sensor-project")
        t.project.created = "2024-01-10"
        let first = try XCTUnwrap(t.items.firstIndex { $0.kind == "moment" && $0.day == "2026-08-02" })
        t.items[first].day = "2024-01-10"
        let band = BandLayout.make(t, state: ProjectState.state(ProjectState.Input(t), today: today), width: 600,
                                   today: today, locale: us)
        XCTAssertEqual(band.span.start, today.adding(-BandLayout.keptDays))
        let earlier = try XCTUnwrap(band.nodes.first { $0.mark == .earlier })
        XCTAssertEqual(earlier.x, 0)
        XCTAssertEqual(earlier.label, "1 earlier")
    }

    /// R-PP16 — a row's source line and the Reader's target, said once.
    func testSourcesAndReaderTargets() throws {
        let (t, _) = try rover()
        let guide = try item(t, "happening", "2026-09-22")
        XCTAssertEqual(ProjectSource.line(guide), .conversation(origin: "telegram", app: "Telegram", title: "Notes on the lab cluster"))
        let target = try XCTUnwrap(ProjectSource.target(guide, projectId: t.project.id))
        guard case let .span(start, end, hash, derived) = target.focus else { return XCTFail("\(target.focus)") }
        let own = try XCTUnwrap(guide.claim?.evidence.first { $0.isSpan })
        XCTAssertEqual([start, end], [own.start, own.end])
        XCTAssertEqual(hash, own.hash, "the claim's own span carries its hash, so the server can say grown or stale")
        XCTAssertFalse(derived)
        XCTAssertEqual(target.subjectId, "pick-and-place-demo")
        let specs = try item(t, "moment", "2026-09-22")
        guard case let .span(_, _, momentHash, _) = try XCTUnwrap(ProjectSource.target(specs, projectId: t.project.id)).focus else {
            return XCTFail("a moment's quote lands on its span")
        }
        XCTAssertNil(momentHash, "a moment's quote carries no hash (reported)")
        XCTAssertEqual(ProjectSource.line(specs), .conversation(origin: "claude-code", app: "Claude Code", title: "Lab cluster specs"))
        // Spelled out: a bare `.none` could be read as `Optional.none` once XCTAssertEqual promotes to `Line?`.
        XCTAssertEqual(ProjectSource.line(try XCTUnwrap(t.items.first { $0.kind == "created" })), ProjectSource.Line.none)
        let grasp = try XCTUnwrap(t.milestones.first { $0.slug == "first-grasp" })
        XCTAssertEqual(ProjectSource.line(grasp, conversations: t.conversations), .setByYou,
                       "the person moved it in the app: reasoning evidence, origin companion_app (§7)")
        XCTAssertNil(ProjectSource.target(for: .milestone("first-grasp"), in: t, projectId: t.project.id),
                     "nothing to open: no sentence says it")
        let camera = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" })
        XCTAssertEqual(ProjectSource.target(for: .thread(camera.claimId), in: t, projectId: t.project.id)?.episode,
                       "ep_2026-08-30_002")
        XCTAssertEqual(ProjectSource.docIndex(t).meta("ep_2026-09-22_003")?.harness, "claude-code")
    }

    /// R-PP12 / R-PJ22 — the band never says "Timeline": the card's Timeline tab can share the screen.
    func testNothingOnThePageSaysTimeline() throws {
        let literal = try NSRegularExpression(pattern: #""[^"\n]*Timeline[^"\n]*""#)
        var offenders: [String] = []
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources()
        where file.path.contains("/Views/Projects/") || file.path.hasSuffix("/Theme/Copy+Projects.swift") {
            scanned += 1
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                let ns = line as NSString
                if literal.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) != nil {
                    offenders.append("\(file.lastPathComponent):\(i + 1)")
                }
            }
        }
        XCTAssertGreaterThan(scanned, 0)
        XCTAssertEqual(offenders, [], "R-PJ22: the band is 'Progress', the card's tab is 'Timeline'")
    }
}
```

  The long-window test mutates a decoded timeline, so in `Models/Project.swift` the fields it writes are already `var`
  (`ProjectRef.created`, `ProjectItem.day`). In `TitlebarHelpTests.swift` the `ListHelp.projects` keys become
  `["⌘F", "↑ ↓", "⏎", "← →", "Esc"]`. In `SelectionTintLintTests.swift` append `"Views/Projects/ProjectBand.swift"`.

- [ ] **Step 2: See them fail.** `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectBandTests|TitlebarHelpTests' 2>&1 | tail -20`
  fails to compile (`BandLayout`, `ProjectSource` unknown).

- [ ] **Step 3: Sources.** Create `app/…/Views/Projects/ProjectSource.swift`:

```swift
import Foundation

/// R-PP16 — where a row on the Projects page came from, said once, and where the Reader opens (DR-31, DR-54, DR-55,
/// DR-57; G118: spans, not copies). Pure: Task 4's source lines and the band's ⏎ read the same answers.
enum ProjectSource {
    enum Line: Equatable {
        /// A conversation: its origin's real mark, "<App> · <title>" (DR-54).
        case conversation(origin: String, app: String, title: String)
        /// The person's own Log entry — a companion note (R-PJ18).
        case note
        /// Written in the app with no sentence behind it: DR-57's sixth label, as a source line, never a chip (§7).
        case setByYou
        /// A `## History` bullet (§6.1 layer 5).
        case pageHistory
        /// A span whose conversation the payload does not name: the chip alone says who spoke.
        case chipOnly
        /// Nothing at all — `[ no source recorded ]`, served exactly as written (G115, DR-55).
        case none
    }

    static func line(_ item: ProjectItem) -> Line {
        if item.kind == "history" { return .pageHistory }
        if let conversation = item.conversation {
            if conversation.origin == "companion_app" { return .note }
            let origin = conversation.harness ?? conversation.origin ?? ""
            return .conversation(origin: origin, app: OriginIconography.label(for: origin), title: conversation.title)
        }
        if let claim = item.claim, claim.origin == "companion_app", claim.evidence.allSatisfy({ !$0.isSpan }) {
            return .setByYou
        }
        return item.quote == nil ? .none : .chipOnly
    }

    /// A milestone's line reads its slot's head claim: the person set or moved it in the app, or a sentence said it.
    static func line(_ m: ProjectMilestone, conversations: [ProjectConversation]) -> Line {
        guard let head = m.chain.first else { return .none }
        if head.origin == "companion_app", head.evidence.allSatisfy({ !$0.isSpan }) { return .setByYou }
        guard let span = head.evidence.first(where: \.isSpan) else { return .none }
        if let c = conversations.first(where: { $0.episodeId == span.episode }) {
            let origin = c.harness ?? c.origin ?? ""
            return .conversation(origin: origin, app: OriginIconography.label(for: origin), title: c.title)
        }
        return .chipOnly
    }

    /// The evidence entry a row's chip shows: the claim's own span on the quoted episode (it carries the hash), else the
    /// quote's offsets. A stale quote has none — its words moved, and a chip would wash words that are no longer there.
    static func evidence(_ item: ProjectItem) -> Evidence? {
        guard let quote = item.quote, quote.status != "stale" else { return nil }
        if let own = item.claim?.evidence.first(where: { $0.episode == quote.episode && $0.isSpan }) { return own }
        guard let start = quote.start, let end = quote.end, end > start else { return nil }
        return Evidence(episode: quote.episode, start: start, end: end,
                        kind: quote.status == "derived" ? .derived : EvidenceKind(wire: quote.kind))
    }

    static func target(_ item: ProjectItem, projectId: String) -> ReaderTarget? {
        guard let quote = item.quote, !quote.episode.isEmpty else { return nil }
        let subject = item.claim?.subject ?? item.project ?? projectId
        let title = item.conversation?.title
        let harness = item.conversation?.harness
        if quote.status == "stale" {
            return ReaderTarget(episode: quote.episode, focus: .stale, subjectId: subject, knownTitle: title,
                                knownHarness: harness)
        }
        if let own = item.claim?.evidence.first(where: { $0.episode == quote.episode && $0.isSpan }) {
            return ReaderTarget.evidence(own, subjectId: subject, knownTitle: title, knownHarness: harness)
        }
        if let start = quote.start, let end = quote.end, end > start {
            let derived = quote.kind == "derived" || quote.status == "derived"
            return ReaderTarget(episode: quote.episode, focus: .span(start: start, end: end, hash: nil, derived: derived),
                                subjectId: subject, knownTitle: title, knownHarness: harness)
        }
        return ReaderTarget(episode: quote.episode, focus: .none, subjectId: subject, knownTitle: title,
                            knownHarness: harness)
    }

    static func target(_ m: ProjectMilestone, projectId: String) -> ReaderTarget? {
        guard let head = m.chain.first, let span = head.evidence.first(where: \.isSpan) else { return nil }
        return ReaderTarget.evidence(span, subjectId: head.subject.isEmpty ? projectId : head.subject)
    }

    /// The band's ⏎ and a section row's "Show in conversation ›": the selected key's words.
    static func target(for key: ProjectKey, in t: ProjectTimeline, projectId: String) -> ReaderTarget? {
        switch key {
        case .item(let id), .thread(let id):
            return t.items.first { $0.id == id }.flatMap { target($0, projectId: projectId) }
        case .milestone(let slug):
            return t.milestones.first { $0.slug == slug }.flatMap { target($0, projectId: projectId) }
        }
    }

    /// Every conversation the payload names, by episode — so an assistant chip says "Claude Code replied", not "The
    /// agent replied" (`EvidenceDocIndex`'s reason: no fetch per chip).
    static func docIndex(_ t: ProjectTimeline) -> EvidenceDocIndex {
        var byEpisode: [String: EvidenceDocMeta] = [:]
        for c in t.conversations + t.items.compactMap(\.conversation) {
            byEpisode[c.episodeId] = EvidenceDocMeta(title: c.title.isEmpty ? nil : c.title, harness: c.harness,
                                                     origin: c.origin)
        }
        return EvidenceDocIndex(byEpisode: byEpisode)
    }
}
```

- [ ] **Step 4: The band.** Create `app/…/Views/Projects/ProjectBand.swift`:

```swift
import SwiftUI

/// R-PP11 — what is selected on a project: one key shared by the band and the sections, so a click on either rings the
/// other (the owner: "make nodes in the timeline clickable").
enum ProjectKey: Hashable, Sendable {
    case item(String), milestone(String), thread(String)

    var id: String {
        switch self {
        case .item(let s): "item:\(s)"
        case .milestone(let s): "milestone:\(s)"
        case .thread(let s): "thread:\(s)"
        }
    }

    /// Which section draws the key's row (a thread in Now, a milestone in Plan, anything else in Lately).
    var section: ProjectSection {
        switch self {
        case .thread: .now
        case .milestone: .plan
        case .item: .lately
        }
    }
}

enum ProjectSection: String, CaseIterable, Sendable { case now, lately, plan, around }

/// §3.8 / §9 (2026-09-23) / R-PP10 — the band, pure: every mark at the approved mock's coordinates, in units that
/// `ProjectBandView` scales (DR-70). The green is the band's one hue; every mark is a neutral shape in the text ladder
/// (R-PJ21 as the owner settled it); every mark is a button.
struct BandLayout: Equatable {
    enum Lane: Int, CaseIterable { case track, below, above }
    enum Mark: Equatable { case done, said, history, milestoneDone, milestonePlanned, milestoneClosed, ghost, earlier }
    enum Cap: Equatable { case open, done }

    struct Node: Identifiable, Equatable {
        let key: ProjectKey
        let mark: Mark
        let x: CGFloat
        var lane: Lane
        let label: String
        let when: String
        var more = 0
        var id: String { "\(key.id)|\(mark)" }
    }

    struct Thread: Identifiable, Equatable {
        let key: ProjectKey
        let x0: CGFloat
        let x1: CGFloat
        /// The share of the span drawn solid: 1 while heard from, then dashed from its last-heard day once quiet.
        let solid: Double
        let cap: Cap
        let row: Int
        let label: String
        let when: String
        var id: String { key.id }
    }

    struct Tick: Equatable { let x: CGFloat; let label: String }
    struct Bracket: Equatable { let x0: CGFloat; let x1: CGFloat }

    let span: ProgressSpan
    let width: CGFloat
    let months: [Tick]
    let words: [Tick]
    let nodes: [Node]
    let threads: [Thread]
    let brackets: [Bracket]
    let next: Tick?
    let since: String
    let progressWords: String?
    let accessibility: String

    func x(_ day: ISODay) -> CGFloat { CGFloat(span.fraction(day)) * width }
    var todayX: CGFloat { x(span.today) }

    /// ←/→ — every mark left to right; a ghost (a moved milestone's old date) selects its milestone, so it is no stop.
    var order: [ProjectKey] {
        let marks = nodes.filter { $0.mark != .ghost }.map { (x: $0.x, rank: $0.lane.rawValue, key: $0.key) }
        let spans = threads.map { (x: $0.x0, rank: Lane.allCases.count + $0.row, key: $0.key) }
        var seen = Set<ProjectKey>()
        return (marks + spans).sorted { ($0.x, $0.rank) < ($1.x, $1.rank) }.compactMap { seen.insert($0.key).inserted ? $0.key : nil }
    }

    /// DR-68 — ← / → from the selection, clamped; from nothing, the first (→) or the last (←).
    func step(from key: ProjectKey?, delta: Int) -> ProjectKey? {
        let keys = order
        guard !keys.isEmpty else { return nil }
        guard let key, let i = keys.firstIndex(of: key) else { return delta >= 0 ? keys.first : keys.last }
        return keys[min(max(i + delta, 0), keys.count - 1)]
    }

    // The approved mock's coordinates, in units (`ProjectBandView` scales them).
    static let height: CGFloat = 112
    static let inset: CGFloat = 14
    static let trackTop: CGFloat = 22
    static let trackHeight: CGFloat = 10
    static let todayTop: CGFloat = 14
    static let todayHeight: CGFloat = 60
    static let tickTop: CGFloat = 80
    static let monthTop: CGFloat = 86
    static let wordTop: CGFloat = 100
    static let labelTop: CGFloat = -7
    static let threadRows = 2
    static let minGap: CGFloat = 12
    static let longWindowDays = 540
    static let keptDays = 365

    static func y(_ lane: Lane) -> CGFloat {
        switch lane {
        case .track: 27
        case .below: 43
        case .above: 13
        }
    }

    static func threadY(_ row: Int) -> CGFloat { 56 + CGFloat(row) * 12 }

    static func make(_ t: ProjectTimeline, state: ProjectState.Output, width: CGFloat, today: ISODay,
                     locale: Locale = .autoupdatingCurrent) -> BandLayout {
        let items = t.items.filter { $0.kind != "created" }
        var span = ProjectsModel.span(t, planned: state.planned, today: today)
        var earlier: [ProjectItem] = []
        if today - span.start > longWindowDays {
            let kept = today.adding(-keptDays)
            earlier = items.filter { ISODay($0.day).map { $0 < kept } ?? false }
            span = ProgressSpan(start: kept, end: span.end, today: today, planned: span.planned)
        }
        func x(_ day: ISODay) -> CGFloat { CGFloat(span.fraction(day)) * width }
        func absolute(_ day: ISODay) -> String { RelativeDay.absolute(day, today: today, locale: locale) }

        var placed: [Node] = []
        /// R-PP10 — the preferred lane, then the others; a mark with no free lane folds into its nearest neighbour.
        func place(_ node: Node, prefer: Lane) {
            for lane in [prefer] + Lane.allCases.filter({ $0 != prefer })
            where !placed.contains(where: { $0.lane == lane && abs($0.x - node.x) < minGap }) {
                var n = node
                n.lane = lane
                placed.append(n)
                return
            }
            if let i = placed.indices.min(by: { abs(placed[$0].x - node.x) < abs(placed[$1].x - node.x) }) {
                placed[i].more += 1
            }
        }

        // Milestones own the track (§3.8).
        var brackets: [Bracket] = []
        let milestones = t.milestones.filter { $0.source != "expectedEnd" }
        for m in milestones.sorted(by: { ($0.doneOn ?? $0.target ?? "~") < ($1.doneOn ?? $1.target ?? "~") }) {
            let st = state.milestone(m.slug) ?? ProjectState.milestoneState(m, today: today)
            let at: ISODay?
            let mark: Mark
            let words: (ISODay) -> String
            switch st.state {
            case "done":
                at = ISODay(m.doneOn) ?? ISODay(m.target)
                mark = .milestoneDone
                words = { Copy.Projects.milestoneDoneOn(absolute($0)) }
            case "passed-no-word":
                at = ISODay(m.target)
                mark = .milestoneClosed
                words = { Copy.Projects.milestonePassed(absolute($0)) }
            case "missed":
                at = ISODay(m.target)
                mark = .milestoneClosed
                words = { Copy.Projects.milestoneMissed(absolute($0)) }
            case "overdue":
                at = ISODay(m.target)
                mark = .milestonePlanned
                words = { Copy.Projects.milestoneOverdue(absolute($0)) }
            case "upcoming":
                at = ISODay(m.target)
                mark = .milestonePlanned
                words = { Copy.Projects.milestoneUpcoming(absolute($0), RelativeDay.distance($0, today: today)) }
            default:
                continue   // someday has no date to stand on; a dropped milestone leaves nothing planned
            }
            guard let at, at >= span.start else { continue }
            place(Node(key: .milestone(m.slug), mark: mark, x: x(at), lane: .track, label: m.name, when: words(at)),
                  prefer: .track)
            if mark == .milestonePlanned, let old = ProjectsModel.earlierTarget(m), old >= span.start {
                let movedOn = ISODay(m.chain.first?.validFrom).map(absolute) ?? ""
                place(Node(key: .milestone(m.slug), mark: .ghost, x: x(old), lane: .track,
                           label: Copy.Projects.earlierTarget(m.name), when: Copy.Projects.movedOn(absolute(old), movedOn)),
                      prefer: .track)
                brackets.append(Bracket(x0: min(x(old), x(at)), x1: max(x(old), x(at))))
            }
        }
        if let oldest = earlier.min(by: { ($0.day ?? "") < ($1.day ?? "") }), let day = ISODay(oldest.day) {
            place(Node(key: .item(oldest.id), mark: .earlier, x: 0, lane: .track,
                       label: Copy.Projects.earlier(earlier.count), when: absolute(day)), prefer: .track)
        }

        // Happenings prefer the track, then moments and history bullets prefer below; an ongoing happening is a thread.
        let dated = items.compactMap { item -> (ProjectItem, ISODay)? in
            guard let day = ISODay(item.day), day >= span.start else { return nil }
            return (item, day)
        }.sorted { $0.1 < $1.1 }
        for (item, day) in dated where item.kind == "happening" && item.status != "ongoing" {
            let words = ProjectsModel.firstWords(item.text)
            place(Node(key: .item(item.id), mark: .done, x: x(day), lane: .track, label: words,
                       when: RelativeDay.phrase(day, today: today, locale: locale)), prefer: .track)
        }
        for (item, day) in dated where item.kind == "moment" || item.kind == "history" {
            let words = ProjectsModel.firstWords(item.text)
            place(Node(key: .item(item.id), mark: item.kind == "moment" ? .said : .history, x: x(day), lane: .below,
                       label: words, when: RelativeDay.phrase(day, today: today, locale: locale)), prefer: .below)
        }

        // Threads: the open ones first (to today, an open cap), then a settled one (to its end, a closed cap).
        var threads: [Thread] = []
        for (row, th) in t.now.threads.prefix(threadRows).enumerated() {
            guard let since = ISODay(th.since) else { continue }
            let heard = ISODay(th.lastHeard) ?? since
            let quietDays = state.thread(th.claimId)?.quietDays ?? (today - heard)
            let quiet = quietDays > state.quietThreshold
            let solid = quiet && today > since ? Double(heard - since) / Double(today - since) : 1
            let when = quiet ? "\(Copy.Projects.sinceDay(absolute(since))) · \(Copy.Projects.quietDays(quietDays))"
                : (since == today ? Copy.Projects.startedToday : Copy.Projects.sinceDay(absolute(since)))
            threads.append(Thread(key: .thread(th.claimId), x0: x(max(since, span.start)), x1: x(today),
                                  solid: min(max(solid, 0), 1), cap: .open, row: row, label: th.text, when: when))
        }
        for item in items where threads.count < threadRows && item.kind == "happening" && item.status == "ongoing" {
            guard let to = ISODay(item.claim?.validTo), let from = ISODay(item.claim?.validFrom ?? item.day) else { continue }
            threads.append(Thread(key: .item(item.id), x0: x(max(from, span.start)), x1: x(to), solid: 1, cap: .done,
                                  row: threads.count, label: item.text, when: Copy.Projects.ongoingUntil(absolute(to))))
        }

        // Months, plus the start's month when the first tick sits past 7 % (the mock).
        var months: [Tick] = []
        func monthStart(_ year: Int, _ month: Int) -> ISODay {
            month > 12 ? ISODay(year: year + 1, month: month - 12, day: 1) : ISODay(year: year, month: month, day: 1)
        }
        let s = span.start.civil
        var tick = s.day == 1 ? span.start : monthStart(s.year, s.month + 1)
        while tick <= span.end {
            months.append(Tick(x: x(tick), label: RelativeDay.month(tick, locale: locale)))
            let c = tick.civil
            tick = monthStart(c.year, c.month + 1)
        }
        if (months.first?.x ?? .infinity) > width * 0.07 {
            months.insert(Tick(x: 0, label: RelativeDay.month(span.start, locale: locale)), at: 0)
        }
        let words = RelativeDay.bandWords(spanDays: span.days).compactMap { w -> Tick? in
            let day = today.adding(w.offset)
            guard day >= span.start, day <= span.end else { return nil }
            let px = x(day)
            return px > width * 0.08 && px < width * 0.94 ? Tick(x: px, label: w.text) : nil
        }
        let next = state.next.flatMap { slug in milestones.first { $0.slug == slug } }.flatMap { m in
            ISODay(m.target).map { Tick(x: x($0), label: Copy.Projects.nextMark(m.name, RelativeDay.distance($0, today: today))) }
        }

        return BandLayout(
            span: span, width: width, months: months, words: words, nodes: placed, threads: threads, brackets: brackets,
            next: next, since: Copy.Projects.since(absolute(span.start)),
            progressWords: state.planned ? Copy.Projects.doneOf(state.progress) : nil,
            accessibility: Copy.Projects.bandLabel(t.project.name, planned: state.planned, progress: state.progress,
                                                   today: RelativeDay.spoken(today, locale: locale)))
    }
}

/// §3.8 — the band, drawn: a `Canvas` for the track, the green, the open end, the brackets, the ticks and the "You,
/// today" marker; every mark a real `Button` over it (the owner's "clickable"), with an instant hover tooltip whose text
/// twin is the mark's accessibility label (DR-69). Selection is a `textPrimary` ring, never the accent (DR-5).
struct ProjectBandView: View {
    let layout: BandLayout
    let selected: ProjectKey?
    let isFocused: Bool
    let pick: (ProjectKey) -> Void

    @State private var hovered: String?

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        ZStack(alignment: .topLeading) {
            Canvas { context, _ in drawStatic(context) }
                .frame(width: layout.width, height: s(BandLayout.height))
                .accessibilityHidden(true)
            labels
            ForEach(layout.threads) { thread($0) }
            ForEach(layout.nodes) { node($0) }
            tooltip
        }
        .frame(width: layout.width, height: s(BandLayout.height), alignment: .topLeading)
        .padding(.horizontal, s(BandLayout.inset))
        .padding(.top, s(8))
        .overlay {
            if isFocused {
                CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).strokeBorder(CicadaTheme.focusRing, lineWidth: 2)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(layout.accessibility)
    }

    private func drawStatic(_ context: GraphicsContext) {
        let track = CGRect(x: 0, y: s(BandLayout.trackTop), width: layout.width, height: s(BandLayout.trackHeight))
        let radius = track.height / 2
        let todayX = layout.todayX
        if layout.span.planned {
            context.fill(Path(roundedRect: track, cornerRadius: radius), with: .color(CicadaTheme.bgBadge))
        } else {
            var end = Path()
            end.move(to: CGPoint(x: todayX + 2, y: track.midY))
            end.addLine(to: CGPoint(x: layout.width, y: track.midY))
            context.stroke(end, with: .color(CicadaTheme.progressOpenEnd), style: StrokeStyle(lineWidth: 2, dash: [4, 3]))
        }
        let filled = CGRect(x: 0, y: track.minY, width: max(todayX, track.height), height: track.height)
        context.fill(Path(roundedRect: filled, cornerRadius: radius), with: .color(CicadaTheme.progressFill))
        for b in layout.brackets {
            var arc = Path()
            let top = track.minY - s(8)
            arc.move(to: CGPoint(x: b.x0, y: track.minY - s(2)))
            arc.addLine(to: CGPoint(x: b.x0, y: top))
            arc.addLine(to: CGPoint(x: b.x1, y: top))
            arc.addLine(to: CGPoint(x: b.x1, y: track.minY - s(2)))
            context.stroke(arc, with: .color(CicadaTheme.textTertiary), style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
        }
        for m in layout.months {
            context.fill(Path(CGRect(x: m.x, y: s(BandLayout.tickTop), width: 1, height: s(4))),
                         with: .color(CicadaTheme.textTertiary))
        }
        // "You, today" — 2 units of textPrimary on a bgBase knockout: the marker is not the accent (§3.8, R-PJ21).
        let marker = CGRect(x: todayX - 1, y: s(BandLayout.todayTop), width: 2, height: s(BandLayout.todayHeight))
        context.fill(Path(roundedRect: marker.insetBy(dx: -1.5, dy: -1.5), cornerRadius: 2), with: .color(CicadaTheme.bgBase))
        context.fill(Path(roundedRect: marker, cornerRadius: 1), with: .color(CicadaTheme.textPrimary))
    }

    private var labels: some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(layout.months.enumerated()), id: \.offset) { _, m in
                edgeLabel(m.label, x: m.x, y: s(BandLayout.monthTop))
            }
            ForEach(Array(layout.words.enumerated()), id: \.offset) { _, w in
                edgeLabel(w.label, x: w.x, y: s(BandLayout.wordTop))
            }
            Text(Copy.Projects.youToday)
                .font(CicadaTheme.font(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize()
                .position(x: layout.todayX, y: s(BandLayout.labelTop + 7))
            // The next milestone's words sit over its diamond — hidden when they would run into "You, today".
            if let next = layout.next, abs(next.x - layout.todayX) > s(72) {
                edgeLabel(next.label, x: next.x, y: s(BandLayout.labelTop))
            }
        }
        .accessibilityHidden(true)
    }

    /// A label centred on `x`, pulled inside the band at either end so it is never clipped.
    private func edgeLabel(_ text: String, x: CGFloat, y: CGFloat) -> some View {
        let nearStart = x < s(24)
        let nearEnd = x > layout.width - s(24)
        return Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize()
            .frame(width: s(96), alignment: nearStart ? .leading : (nearEnd ? .trailing : .center))
            .position(x: nearStart ? x + s(48) : (nearEnd ? x - s(48) : x), y: y + s(7))
    }

    private func node(_ n: BandLayout.Node) -> some View {
        Button { pick(n.key) } label: {
            BandMark(mark: n.mark, selected: selected == n.key && n.mark != .ghost)
                .frame(width: s(20), height: s(20))
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .position(x: n.x, y: s(BandLayout.y(n.lane)))
        .onHover { inside in hovered = inside ? n.id : (hovered == n.id ? nil : hovered) }
        .accessibilityLabel(accessibility(n))
        .accessibilityAddTraits(selected == n.key ? [.isSelected] : [])
    }

    private func accessibility(_ n: BandLayout.Node) -> String {
        let base: String
        switch n.mark {
        case .done, .earlier: base = Copy.Projects.happened(n.label, n.when)
        case .said: base = Copy.Projects.saidHere(n.label, n.when)
        case .history: base = Copy.Projects.fromHistory(n.label, n.when)
        case .milestoneDone, .milestonePlanned, .milestoneClosed, .ghost: base = Copy.Projects.milestoneMark(n.label, n.when)
        }
        return n.more > 0 ? "\(base), \(Copy.Projects.moreHere(n.more))" : base
    }

    private func thread(_ t: BandLayout.Thread) -> some View {
        let length = max(t.x1 - t.x0, 0)
        let isSelected = selected == t.key
        return Button { pick(t.key) } label: {
            ZStack(alignment: .leading) {
                Circle().fill(CicadaTheme.textSecondary).frame(width: s(6), height: s(6)).offset(x: -s(3))
                Capsule().fill(CicadaTheme.textSecondary).frame(width: length * t.solid, height: 2)
                if t.solid < 1 {
                    MidLine()
                        .stroke(CicadaTheme.textSecondary.opacity(0.55), style: StrokeStyle(lineWidth: 2, dash: [3, 3]))
                        .frame(width: length * (1 - t.solid), height: 2)
                        .offset(x: length * t.solid)
                }
                ThreadCap(cap: t.cap, selected: isSelected).offset(x: length - s(5))
            }
            .frame(width: length, height: s(16), alignment: .leading)
            .padding(.horizontal, s(8))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .position(x: t.x0 + length / 2, y: s(BandLayout.threadY(t.row)))
        .onHover { inside in hovered = inside ? t.id : (hovered == t.id ? nil : hovered) }
        .accessibilityLabel(Copy.Projects.inMotion(t.label, t.when))
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
    }

    /// The hover words: the sentence's first words and its date, on a floating surface (DR-10), instant — a mark this
    /// small needs its words the moment the pointer arrives.
    @ViewBuilder
    private var tooltip: some View {
        if let id = hovered, let tip = tip(id) {
            HStack(spacing: s(6)) {
                Text(tip.label).foregroundStyle(CicadaTheme.textPrimary)
                Text(tip.when).foregroundStyle(CicadaTheme.textTertiary)
            }
            .font(CicadaTheme.metaMediumFont)
            .lineLimit(1)
            .padding(.horizontal, s(8))
            .frame(height: s(24))
            .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .fixedSize()
            .position(x: min(max(tip.x, s(90)), max(layout.width - s(90), s(90))), y: tip.y - s(22))
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }

    private func tip(_ id: String) -> (label: String, when: String, x: CGFloat, y: CGFloat)? {
        if let n = layout.nodes.first(where: { $0.id == id }) {
            let when = n.more > 0 ? "\(n.when) · \(Copy.Projects.moreHere(n.more))" : n.when
            return (n.label, when, n.x, s(BandLayout.y(n.lane)))
        }
        if let t = layout.threads.first(where: { $0.id == id }) {
            return (ProjectsModel.firstWords(t.label), t.when, t.x1, s(BandLayout.threadY(t.row)))
        }
        return nil
    }
}

/// One mark: a shape in the text ladder with a 2-unit `bgBase` knockout, so a mark inside the green reads (§3.8);
/// selected, a `textPrimary` ring (R-PP11).
struct BandMark: View {
    let mark: BandLayout.Mark
    let selected: Bool

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        switch mark {
        case .done: dot(filled: true)
        case .said: dot(filled: false)
        case .history:
            CicadaTheme.shape(1).fill(CicadaTheme.textTertiary)
                .frame(width: s(3), height: s(12))
                .background(CicadaTheme.shape(2).fill(CicadaTheme.bgBase).padding(-2))
                .overlay { if selected { CicadaTheme.shape(2).stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
        case .milestoneDone: diamond(fill: CicadaTheme.textPrimary, stroke: nil, dashed: false, size: 11)
        case .milestonePlanned: diamond(fill: CicadaTheme.bgBase, stroke: CicadaTheme.textSecondary, dashed: false, size: 11)
        case .milestoneClosed:
            diamond(fill: CicadaTheme.bgBase, stroke: CicadaTheme.textSecondary, dashed: false, size: 11)
                .overlay { Rectangle().fill(CicadaTheme.textSecondary).frame(width: 1.5, height: s(17)) }
        case .ghost: diamond(fill: CicadaTheme.bgBase, stroke: CicadaTheme.textTertiary, dashed: true, size: 10)
        case .earlier:
            Text("…").font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func dot(filled: Bool) -> some View {
        Circle()
            .fill(filled ? CicadaTheme.textPrimary : CicadaTheme.bgBase)
            .overlay { if !filled { Circle().strokeBorder(CicadaTheme.textPrimary, lineWidth: 1.5) } }
            .frame(width: s(8), height: s(8))
            .background(Circle().fill(CicadaTheme.bgBase).padding(-2))
            .overlay { if selected { Circle().stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
    }

    private func diamond(fill: Color, stroke: Color?, dashed: Bool, size: CGFloat) -> some View {
        let shape = CicadaTheme.shape(2)
        return shape.fill(fill)
            .overlay {
                if let stroke {
                    shape.strokeBorder(stroke, style: StrokeStyle(lineWidth: 1.5, dash: dashed ? [2, 2] : []))
                }
            }
            .frame(width: s(size), height: s(size))
            .background(shape.fill(CicadaTheme.bgBase).padding(-2))
            .overlay { if selected { shape.stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
            .rotationEffect(.degrees(45))
    }
}

/// A thread's end at today: open (a ring) while it runs, filled once a successor settled it.
struct ThreadCap: View {
    let cap: BandLayout.Cap
    let selected: Bool

    var body: some View {
        let side = CicadaTheme.scaled(10)
        Circle()
            .fill(cap == .done ? CicadaTheme.textPrimary : CicadaTheme.bgBase)
            .overlay { if cap == .open { Circle().strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5) } }
            .frame(width: side, height: side)
            .background(Circle().fill(CicadaTheme.bgBase).padding(-2))
            .overlay { if selected { Circle().stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
    }
}
```

- [ ] **Step 5: The band in the detail column.** In `ProjectDetailColumn.swift`:
  - add the environment and state the band needs:

```swift
    @Environment(ProvenanceRouter.self) private var provenance
    /// R-PP11 — one selection for the band and (Task 4) the sections.
    @State private var selection: ProjectKey?
    @State private var bandWidth: CGFloat = 0
    @FocusState private var bandFocused: Bool
```

  - `content(_:)` becomes:

```swift
    @ViewBuilder
    private func content(_ t: ProjectTimeline) -> some View {
        let state = ProjectState.state(ProjectState.Input(t), today: today)
        let band = BandLayout.make(t, state: state, width: max(bandWidth - 2 * CicadaTheme.scaled(BandLayout.inset), 1),
                                   today: today)
        header(name: t.project.name, oneLiner: t.project.oneLiner, parent: t.project.parent)
        bandHeader(band, progress: state.progress)
        ProjectBandView(layout: band, selected: selection, isFocused: bandFocused) { pick($0, in: t) }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background { GeometryReader { geo in Color.clear.onAppear { bandWidth = geo.size.width }
                .onChange(of: geo.size.width) { _, w in bandWidth = w } } }
            .padding(.top, CicadaTheme.scaled(6))
            .focusable()
            .focused($bandFocused)
            .focusEffectDisabled()
            // DR-68 — ← / → step along the band; ⏎ opens the selection's words in the Reader. Keys never animate.
            .onMoveCommand { direction in
                switch direction {
                case .left: Instant.run { selection = band.step(from: selection, delta: -1) }
                case .right: Instant.run { selection = band.step(from: selection, delta: 1) }
                default: break
                }
            }
            .onKeyPress(.return) {
                guard let key = selection, let target = ProjectSource.target(for: key, in: t, projectId: projectId) else {
                    return .ignored
                }
                Instant.run { provenance.open(target) }
                return .handled
            }
        Spacer(minLength: 0)
    }

    /// R-PP11 — a pick rings the mark (a second pick clears it) and gives the band the keys (R-PP23). With the Reader
    /// open, a pick that cites the same conversation re-lands it in place; any other closes it (DR-29).
    private func pick(_ key: ProjectKey, in t: ProjectTimeline) {
        bandFocused = true
        Instant.run {
            selection = selection == key ? nil : key
            guard provenance.isPresented, let chosen = selection else { return }
            if let target = ProjectSource.target(for: chosen, in: t, projectId: projectId),
               target.episode == provenance.current?.episode {
                provenance.refocus(target)
            } else {
                provenance.close()
            }
        }
    }
```

  - the column's `.task(id: projectId)` also clears the selection: `.task(id: projectId) { selection = nil; await
    cache.refreshTimeline(projectId) }`.
  - `bandHeader` reads its words from the band, so the header line and the bar can never disagree. Replace it with:

```swift
    /// The band's header line (the mock): where the green starts, and "N of M done" in words (R-PJ11: never a
    /// percentage) — or "No plan yet", which Task 5 follows with "Add a milestone".
    private func bandHeader(_ band: BandLayout, progress: ProjectProgress) -> some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Text(band.since).foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: 0)
            if let words = band.progressWords {
                Text(words)
                    .fontWeight(.medium)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .help(Copy.Projects.barHelp(planned: true, progress: progress))
            } else {
                Text(Copy.Projects.noPlanYet).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .font(CicadaTheme.metaFont)
        .monospacedDigit()
        .frame(height: CicadaTheme.scaled(22))
        .padding(.top, CicadaTheme.scaled(18))
    }
```

    and in `content(_:)` the call becomes `bandHeader(band, progress: state.progress)`.

  In `TitlebarHelp.swift`'s `ListHelp.projects` keys, insert `.init(key: "← →", does: "Step along the bar; ⏎ shows
  it in the conversation")` after the `⏎` row, and add "Every mark on the bar opens what it stands for." to its
  subtitle.

- [ ] **Step 6: Green.** `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectBandTests|TitlebarHelpTests|SelectionTintLintTests|FontLiteralLintTests|ElevationLintTests|RelativeDayTests|ProjectsListTests' 2>&1 | tail -20`
  passes; then `swift build` and the full `swift test` (0 failures).

- [ ] **Step 7: Commit.**

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectBand.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectSource.swift app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectDetailColumn.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Shell/TitlebarHelp.swift app/CicadaApp/Tests/CicadaAppTests/ProjectBandTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/TitlebarHelpTests.swift app/CicadaApp/Tests/CicadaAppTests/SelectionTintLintTests.swift
cd <worktree> && git commit -m "feat(projects): the band — a green bar that fills up to today, every node clickable, ←/→ and ⏎ to the Reader (G141 PJ-5, R-PP10…R-PP12, R-PP16; §3.8; DR-5, DR-8, DR-16, DR-28, DR-29, DR-31, DR-53, DR-55, DR-57, DR-60, DR-68, DR-69, DR-70)"
```

---

### Task 4: Now · Lately · Plan · Around this project, and the third column (DR-9, DR-16, DR-18, DR-20, DR-28, DR-29, DR-31, DR-37, DR-39, DR-40, DR-44, DR-47, DR-48, DR-52, DR-54, DR-55, DR-56, DR-57, DR-58, DR-60, DR-69; R-PP11, R-PP13…R-PP18, R-PP22, R-PP26; R-PJ4, R-PJ11, R-PJ15)

Under the band, the project's story. Every sentence carries every participant as a chip that opens its card in the
third column; every row says where it came from and opens the Reader beside it; a quiet thread's follow-up links to
its Inbox card. The words are decided in one pure file, `ProjectStory.swift`, tested on the demo wire; the views only
draw them. The write buttons arrive in Task 5 through optional closures that are nil here, so nothing is a dead
control.

**Files:**
- Create: `app/…/Views/Projects/ProjectStory.swift`, `ProjectSentence.swift`, `ProjectSections.swift`,
  `ProjectEntityColumn.swift`.
- Modify: `app/…/Views/Projects/ProjectDetailColumn.swift` (full replacement below), `ProjectsPage.swift` (the third
  column), `app/…/ViewModels/ConversationsViewModel.swift` (`ResumeOutcome.toast`),
  `app/…/Views/Provenance/ReaderColumn.swift` (`act` uses it).
- Test: `ProjectStoryTests.swift` (new). Edit `SelectionTintLintTests.swift`.

**Interfaces:**
- Produces: `StoryToken`; `ProjectStory` (`tokens`, `Group`, `groups`, `createdLine`, `status`, `Glyph`, `glyph`,
  `basis`, `rowDate`, `factsLine`, `nowThreads`, `threadMeta`, `nowEmpty`, `pendingLine`, `followups`); `ProjectPlan`
  (`Row`, `rows`, `meta`, `chain`, `canMarkDone`, `Diamond`, `diamond`, `isPending`); `ProjectAround` (`label`,
  `last`, `expands`, `specs`, `opensProject`); `SentenceFlowLayout`, `StorySentence`, `ParticipantChip`, `OwnerChip`,
  `ProjectSourceLineView`, `ProjectQuoteBlock`, `StoryRowSurface`, `StoryGlyph`, `PlanDiamond`;
  `ProjectSectionHeader`, `ProjectNowSection`, `ProjectLatelySection`, `ProjectPlanSection`, `ProjectAroundSection`;
  `ProjectEntityColumn`; `ResumeOutcome.toast`.
- Consumes: Tasks 1–3; `EvidenceChip`, `EvidenceChipModel`, `QuoteBlock`, `ProvenanceCache.span`, `EntityDetailCard`
  (`.column`), `TopicDetailNavigation`, `EntityCardNavigation`, `ConversationsViewModel.resume`,
  `Store.visibleInbox`, `Store.entityNames`, `APIClient.fetchClaims(subject:)`, `APIClient.fetchEntity(id:)`,
  `NeutralButton`, `TextButton`, `InlineLink`, `SectionLabel`, `TypeDot`, `OriginMark`.

- [ ] **Step 1: Failing tests.** Create `ProjectStoryTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP13…R-PP18, R-PP22, R-PP26 — the story's words, pure, on the demo's wire at T = 2026-09-23.
@MainActor
final class ProjectStoryTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")

    private func rover() throws -> (ProjectTimeline, ProjectState.Output) {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        return (t, ProjectState.state(ProjectState.Input(t), today: today))
    }

    private func item(_ t: ProjectTimeline, _ kind: String, _ day: String) throws -> ProjectItem {
        try XCTUnwrap(t.items.first { $0.kind == kind && $0.day == day })
    }

    /// R-PP15 — one sentence: the owner, then words, then every page the sentence names, where it names it.
    func testASentenceLinksEveryParticipantWhereItIsSaid() throws {
        let (t, _) = try rover()
        let guide = try item(t, "happening", "2026-09-22")
        let (tokens, extra) = ProjectStory.tokens(guide.text, participants: guide.participants)
        XCTAssertEqual(tokens.map(\.kind), [.owner, .word, .word, .page, .word, .page, .word, .word, .word, .word, .word, .page])
        XCTAssertEqual(tokens.filter { $0.kind != .word }.map(\.text),
                       ["Bob", "lab cluster onboarding guide", "Hana Example", "Lab Cluster Example"])
        XCTAssertEqual(tokens[5].trailing, ";", "punctuation rides with the chip before it")
        XCTAssertFalse(tokens[0].spaceBefore)
        XCTAssertTrue(tokens[1].spaceBefore)
        XCTAssertTrue(tokens[6].spaceBefore, "“it” follows the “; ” the chip carried")
        XCTAssertEqual(tokens[3].participant?.url, "https://example.com/guides/lab-cluster-onboarding.pdf")
        XCTAssertEqual(extra, [])
        // A moment's participants carry no surface: their names link where the phrase says them.
        let used = try item(t, "moment", "2026-09-09")
        let moment = ProjectStory.tokens(used.text, participants: used.participants)
        XCTAssertEqual(moment.tokens.map(\.kind), [.word, .word, .word, .word, .page])
        XCTAssertEqual(moment.tokens.last?.text, "Tool Example E")
        // A page the sentence never names follows it as a chip; an unlinked name stays words.
        let absent = ProjectParticipant(id: "tool-example-z", name: "Tool Example Z", type: "tool")
        let unlinked = ProjectParticipant(id: nil, name: "gripper camera")
        let more = ProjectStory.tokens("Bob started calibrating the gripper camera",
                                       participants: [unlinked, absent])
        XCTAssertEqual(more.extra, [absent])
        XCTAssertTrue(more.tokens.allSatisfy { $0.kind == .word })
    }

    /// R-PP14 — Today · Yesterday · This week · Earlier, in the server's order; `created` is the foot line.
    func testLatelyGroupsByTheViewersDay() throws {
        let (t, _) = try rover()
        let groups = ProjectStory.groups(t.items, today: today)
        XCTAssertEqual(groups.map(\.group), [.today, .yesterday, .earlier])
        XCTAssertEqual(groups[1].items.map(\.kind), ["happening", "moment"])
        XCTAssertEqual(groups.last?.items.count, 6)
        XCTAssertFalse(groups.flatMap(\.items).contains { $0.kind == "created" })
        XCTAssertEqual(ProjectStory.createdLine(t.items, today: today, locale: us), "Cicada started tracking this · Jul 15")
        XCTAssertEqual(ProjectStory.groups(t.items, today: today.adding(3)).map(\.group), [.thisWeek, .earlier],
                       "three days on, the same rows read as this week — derived at read, never stored")
    }

    func testEachRowSaysItsStatusDateAndHowItWasDated() throws {
        let (t, state) = try rover()
        let guide = try item(t, "happening", "2026-09-22")
        XCTAssertEqual(ProjectStory.status(guide, state: state, today: today, locale: us), "Done")
        XCTAssertEqual(ProjectStory.glyph(guide), .done)
        XCTAssertEqual(ProjectStory.rowDate(guide, today: today, locale: us).text, "Sep 22")
        XCTAssertEqual(ProjectStory.rowDate(guide, today: today, locale: us).help, "Tuesday, September 22, 2026")
        XCTAssertEqual(ProjectStory.basis(guide.dateBasis), "Dated from your words")
        let camera = try item(t, "happening", "2026-08-30")
        XCTAssertEqual(ProjectStory.status(camera, state: state, today: today, locale: us), "Quiet 24 days")
        XCTAssertEqual(ProjectStory.glyph(camera), .ongoing)
        let connecting = try item(t, "happening", "2026-09-23")
        XCTAssertEqual(ProjectStory.status(connecting, state: state, today: today, locale: us), "Ongoing")
        let specs = try item(t, "moment", "2026-09-22")
        XCTAssertEqual(ProjectStory.status(specs, state: state, today: today, locale: us), "Said here")
        XCTAssertEqual(ProjectStory.glyph(specs), .said)
        XCTAssertEqual(ProjectStory.factsLine(specs, names: EntityNames(byId: ["lab-cluster-example": "Lab Cluster Example"])),
                       "+1 fact · via Lab Cluster Example")
        XCTAssertNil(ProjectStory.factsLine(guide, names: .empty))
        XCTAssertEqual(ProjectStory.basis("person"), "Set by you")
        XCTAssertNil(ProjectStory.basis(nil))
    }

    /// Now: the live thread first, then the quiet one; a quiet thread's follow-up is found by its claim.
    func testNowListsLiveThreadsFirstAndFindsTheirFollowUp() throws {
        let (t, state) = try rover()
        let threads = ProjectStory.nowThreads(t, state: state)
        XCTAssertEqual(threads.map(\.since), ["2026-09-23", "2026-08-30"])
        XCTAssertEqual(ProjectStory.threadMeta(threads[0], state: state, today: today, locale: us), "Started today")
        XCTAssertEqual(ProjectStory.threadMeta(threads[1], state: state, today: today, locale: us), "Since Aug 30 · quiet 24 days")
        let wire = try ProjectFixtures.load()
        let followups = ProjectStory.followups([wire.followup])
        XCTAssertEqual(followups[threads[1].claimId]?.id, wire.followup.id)
        XCTAssertNil(followups[threads[0].claimId])
        XCTAssertEqual(ProjectStory.pendingLine(t.pending, today: today), "1 conversation is waiting for Sleep — the newest from today")
        let garden = try ProjectFixtures.timeline("garden-sensor-project")
        XCTAssertEqual(ProjectStory.nowEmpty(garden, today: today, locale: us),
                       "Nothing in motion right now · last heard Sep 14 (9 days ago)")
        XCTAssertNil(ProjectStory.pendingLine(garden.pending, today: today))
    }

    /// R-PP22 — the Plan's words: early/late, upcoming, "passed, no word", and a moved milestone's chain.
    func testThePlanSaysWhereEachMilestoneStands() throws {
        let (t, _) = try rover()
        let rows = ProjectPlan.rows(t.milestones, today: today)
        XCTAssertEqual(rows.map(\.id), ["arm-assembled", "first-grasp", "due-2026-10-05", "due-2026-11-02"])
        let names = EntityNames(byId: ["pick-and-place-demo": "Pick And Place Demo"])
        func meta(_ i: Int) -> String {
            ProjectPlan.meta(rows[i], onName: rows[i].milestone.on.flatMap { names.name(for: $0) }, today: today, locale: us)
        }
        XCTAssertEqual(meta(0), "Done Aug 9 — 3 days early")
        XCTAssertEqual(meta(1), "Oct 1 · in 8 days")
        XCTAssertEqual(meta(2), "Oct 5 · in 12 days", "no \"on Pick And Place Demo\" when the milestone bears its name")
        XCTAssertEqual(meta(3), "Nov 2 · in 40 days")
        XCTAssertEqual(ProjectPlan.chain(rows[1].milestone, today: today, locale: us),
                       ["Sep 9 — planned Jul 22", "Oct 1 — moved by you on Sep 10"])
        XCTAssertEqual(ProjectPlan.diamond(rows[0]), .filled)
        XCTAssertEqual(ProjectPlan.diamond(rows[1]), .hollow)
        XCTAssertFalse(ProjectPlan.canMarkDone(rows[0]))
        XCTAssertTrue(ProjectPlan.canMarkDone(rows[1]))
        // A due that expiry closed before anyone said how it went (R-PJ4).
        let passed = ProjectPlan.Row(milestone: ProjectMilestone(slug: "due-2026-09-09", name: "First grasp",
                                                                 status: "passed-no-word", target: "2026-09-09", source: "due"),
                                     state: ProjectState.milestoneState(ProjectMilestone(slug: "due-2026-09-09", name: "First grasp",
                                                                                         status: "passed-no-word", target: "2026-09-09"),
                                                                        today: today))
        XCTAssertEqual(ProjectPlan.meta(passed, onName: nil, today: today, locale: us),
                       "Sep 9 · passed, no word on how it went")
        XCTAssertEqual(ProjectPlan.diamond(passed), .slashed)
        XCTAssertTrue(ProjectPlan.canMarkDone(passed), "saying it happened is the answer the follow-up asks for")
        let overdue = ProjectMilestone(slug: "dry-run", name: "Dry run", status: "planned", target: "2026-09-20")
        XCTAssertEqual(ProjectPlan.meta(ProjectPlan.Row(milestone: overdue, state: ProjectState.milestoneState(overdue, today: today)),
                                        onName: nil, today: today, locale: us), "Overdue since Sep 20")
        let sub = ProjectMilestone(slug: "calibrated", name: "Camera calibrated", status: "planned", target: "2026-10-10",
                                   on: "pick-and-place-demo")
        XCTAssertEqual(ProjectPlan.meta(ProjectPlan.Row(milestone: sub, state: ProjectState.milestoneState(sub, today: today)),
                                        onName: "Pick And Place Demo", today: today, locale: us),
                       "Oct 10 · in 17 days · on Pick And Place Demo")
        XCTAssertTrue(ProjectPlan.isPending(ProjectMilestone(slug: "pending-1", name: "x", status: "planned")))
    }

    /// Around this project: the brief's labels, a tool that opens to its specs, a sub-project that opens itself.
    func testAroundUsesThePagesWords() throws {
        let (t, _) = try rover()
        XCTAssertEqual(t.cluster.groups.map { ProjectAround.label($0.label) },
                       ["People", "Tools & infrastructure", "Documents & links", "Parts of this project"])
        let tools = try XCTUnwrap(t.cluster.groups.first { $0.label == "Tools & infrastructure" })
        let cluster = try XCTUnwrap(tools.members.first { $0.memberId == "lab-cluster-example" })
        XCTAssertTrue(ProjectAround.expands(cluster))
        XCTAssertEqual(ProjectAround.last(cluster, today: today, locale: us)?.text, "last Sep 23")
        XCTAssertTrue(ProjectAround.opensProject(try XCTUnwrap(t.cluster.groups.last)))
        XCTAssertFalse(ProjectAround.expands(try XCTUnwrap(t.cluster.groups.first?.members.first)), "a person opens its card")
        let claims = try JSONDecoder().decode([Claim].self, from: Data("""
        [{"id":"c1","text":"Lab Cluster Example has 4 GPU nodes.","predicate":"spec","objectKind":"literal"},
         {"id":"c2","text":"Lab Cluster Example hosts the demo.","predicate":"hosts","objectKind":"node"},
         {"id":"c3","text":"old spec","predicate":"spec","objectKind":"literal","validTo":"2026-09-01"}]
        """.utf8))
        XCTAssertEqual(ProjectAround.specs(claims).map(\.id), ["c1"], "open spec claims first")
        XCTAssertEqual(ProjectAround.specs([claims[1]]).map(\.id), [], "no literal: nothing to list")
    }

    /// R-PP26 — one wording for Resume's outcome, the Reader's and this page's.
    func testResumeSaysWhatHappenedInWords() {
        XCTAssertEqual(ResumeOutcome.launched("Ghostty").toast, "Reopening in Ghostty…")
        XCTAssertEqual(ResumeOutcome.gone.toast, "That conversation's transcript is gone — nothing to resume")
        XCTAssertEqual(ResumeOutcome.failed("x").toast, "x")
    }
}
```

  In `SelectionTintLintTests.swift` append `"Views/Projects/ProjectSections.swift"` (not `ProjectSentence.swift`: a
  document chip's ↗ is a link in `accentText` — DR-5's use 5 — and the lint's `CicadaTheme.accent` needle would read it
  as selection).

- [ ] **Step 2: See them fail.** `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectStoryTests' 2>&1 | tail -20`
  fails to compile.

- [ ] **Step 3: The story's words.** Create `app/…/Views/Projects/ProjectStory.swift`:

```swift
import Foundation

/// R-PP15 — one piece of a happening's sentence: a word, the owner, or a page the sentence names.
struct StoryToken: Identifiable, Equatable {
    enum Kind: Equatable { case word, owner, page }

    let id: Int
    let kind: Kind
    let text: String
    /// Punctuation right after a chip rides with it, so "." never wraps onto a line of its own (the mock).
    let trailing: String
    /// Whether a space came before it in the sentence; `SentenceFlowLayout` draws the gap.
    let spaceBefore: Bool
    let participant: ProjectParticipant?
}

/// G141 PJ-5 — the story's words, pure: a sentence cut into words and chips, Lately's groups, a row's status word, date
/// and how it was dated, a thread's line, the Now section's empty and pending lines. Every relative word comes from
/// `RelativeDay` (DR-58); nothing here is stored.
enum ProjectStory {
    /// R-PP15 / R-PJ15 — each participant's `surface` (else its name) links at its first occurrence no other link took.
    /// A page the sentence never names comes back in `extra`, to follow the sentence as a chip; an unlinked name (no
    /// page) stays words — there is nothing to open; the owner is found by its surface only (never by the name, which
    /// a third-person sentence does not use).
    static func tokens(_ text: String, participants: [ProjectParticipant])
        -> (tokens: [StoryToken], extra: [ProjectParticipant]) {
        var links: [(range: Range<String.Index>, participant: ProjectParticipant)] = []
        var extra: [ProjectParticipant] = []
        for p in participants {
            let surface = p.surface.flatMap { $0.isEmpty ? nil : $0 }
            let needle = surface ?? (p.isOwner ? nil : p.name)
            var found: Range<String.Index>?
            if let needle, !needle.isEmpty {
                var from = text.startIndex
                while from < text.endIndex, let r = text.range(of: needle, range: from..<text.endIndex) {
                    if !links.contains(where: { $0.range.overlaps(r) }) {
                        found = r
                        break
                    }
                    from = r.upperBound
                }
            }
            if let found, p.id != nil || p.isOwner {
                links.append((found, p))
            } else if found == nil, p.id != nil, !p.isOwner {
                extra.append(p)
            }
        }
        links.sort { $0.range.lowerBound < $1.range.lowerBound }

        var out: [StoryToken] = []
        var cursor = text.startIndex
        func spaced(_ i: String.Index) -> Bool { i > text.startIndex && text[text.index(before: i)].isWhitespace }
        func words(upTo end: String.Index) {
            var i = cursor
            while i < end {
                while i < end, text[i].isWhitespace { i = text.index(after: i) }
                guard i < end else { break }
                var j = i
                while j < end, !text[j].isWhitespace { j = text.index(after: j) }
                out.append(StoryToken(id: out.count, kind: .word, text: String(text[i..<j]), trailing: "",
                                      spaceBefore: spaced(i), participant: nil))
                i = j
            }
            cursor = end
        }
        for link in links {
            words(upTo: link.range.lowerBound)
            var end = link.range.upperBound
            while end < text.endIndex, ".,;:!?".contains(text[end]) { end = text.index(after: end) }
            out.append(StoryToken(id: out.count, kind: link.participant.isOwner ? .owner : .page,
                                  text: String(text[link.range]), trailing: String(text[link.range.upperBound..<end]),
                                  spaceBefore: spaced(link.range.lowerBound), participant: link.participant))
            cursor = end
        }
        words(upTo: text.endIndex)
        return (out, extra)
    }

    struct Group: Identifiable, Equatable {
        let group: RelativeDay.Group
        let items: [ProjectItem]
        var id: RelativeDay.Group { group }
    }

    /// R-PP14 — the story in the server's order (newest first), bucketed by the viewer's day; an undated history
    /// bullet reads under Earlier; `created` is the foot line, never a row.
    static func groups(_ items: [ProjectItem], today: ISODay) -> [Group] {
        var buckets: [RelativeDay.Group: [ProjectItem]] = [:]
        for item in items where item.kind != "created" {
            let group = ISODay(item.day).map { RelativeDay.group($0, today: today) } ?? .earlier
            buckets[group, default: []].append(item)
        }
        return RelativeDay.Group.allCases.compactMap { g in buckets[g].map { Group(group: g, items: $0) } }
    }

    static func createdLine(_ items: [ProjectItem], today: ISODay, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let day = items.first(where: { $0.kind == "created" }).flatMap({ ISODay($0.day) }) else { return nil }
        return Copy.Projects.startedTracking(RelativeDay.absolute(day, today: today, locale: locale))
    }

    enum Glyph: Equatable { case done, ongoing, said, history, stopped }

    static func glyph(_ item: ProjectItem) -> Glyph {
        switch item.kind {
        case "history": .history
        case "moment": .said
        default:
            switch item.status {
            case "ongoing": .ongoing
            case "dropped": .stopped
            default: .done
            }
        }
    }

    /// The row's status word (the mock): a happening's state as of its day, a quiet thread's days, a moment's kind.
    static func status(_ item: ProjectItem, state: ProjectState.Output, today: ISODay,
                       locale: Locale = .autoupdatingCurrent) -> String {
        switch item.kind {
        case "history":
            return Copy.Projects.statusHistory
        case "moment":
            switch item.state {
            case "changed": return Copy.Projects.statusChanged
            case "ended": return Copy.Projects.statusEnded
            default: return Copy.Projects.statusSaid
            }
        default:
            switch item.status {
            case "ongoing":
                if let to = ISODay(item.claim?.validTo) {
                    return Copy.Projects.statusOngoingUntil(RelativeDay.absolute(to, today: today, locale: locale))
                }
                if state.isQuiet(item.id) { return Copy.Projects.statusQuiet(state.thread(item.id)?.quietDays ?? 0) }
                return Copy.Projects.statusOngoing
            case "dropped":
                return Copy.Projects.statusStopped
            default:
                return Copy.Projects.statusDone
            }
        }
    }

    /// R-PJ6 / spec §7 — the date is provenance too: how this one was decided, in words.
    static func basis(_ basis: String?) -> String? {
        switch basis {
        case "stated": Copy.Projects.basisStated
        case "turn": Copy.Projects.basisTurn
        case "episode": Copy.Projects.basisEpisode
        case "person": Copy.Projects.basisPerson
        case "written": Copy.Projects.basisWritten
        case "day": Copy.Projects.basisDay
        default: nil
        }
    }

    /// R-PP14 / DR-58 — a row's date is absolute; the full date is its `.help`.
    static func rowDate(_ item: ProjectItem, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String) {
        guard let day = ISODay(item.day) else { return ("", "") }
        return (RelativeDay.absolute(day, today: today, locale: locale), RelativeDay.full(day, locale: locale))
    }

    /// A moment's facts beyond its lead, and the member it came through (§11.3: "+N facts", "via X").
    static func factsLine(_ item: ProjectItem, names: EntityNames) -> String? {
        let more = item.moreFacts > 0 ? Copy.Projects.moreFacts(item.moreFacts) : ""
        let via = item.via.map { Copy.Projects.via(names.display($0)) } ?? ""
        let line = Eyebrow.text(more, via)
        return line.isEmpty ? nil : line
    }

    /// Now: the threads heard from first (newest first), then the quiet ones.
    static func nowThreads(_ t: ProjectTimeline, state: ProjectState.Output) -> [ProjectOpenThread] {
        t.now.threads.sorted { a, b in
            let qa = state.isQuiet(a.claimId)
            let qb = state.isQuiet(b.claimId)
            return qa != qb ? !qa : a.since > b.since
        }
    }

    static func threadMeta(_ t: ProjectOpenThread, state: ProjectState.Output, today: ISODay,
                           locale: Locale = .autoupdatingCurrent) -> String {
        guard let since = ISODay(t.since) else { return "" }
        let sinceWords = RelativeDay.absolute(since, today: today, locale: locale)
        if state.isQuiet(t.claimId) {
            return Copy.Projects.threadQuiet(since: sinceWords, days: state.thread(t.claimId)?.quietDays ?? 0)
        }
        if since == today { return Copy.Projects.threadStartedToday }
        let heard = ISODay(t.lastHeard) ?? since
        return heard == since ? Copy.Projects.threadSince(sinceWords)
            : Copy.Projects.threadHeard(since: sinceWords, heard: RelativeDay.distance(heard, today: today))
    }

    static func nowEmpty(_ t: ProjectTimeline, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let last = ISODay(t.lastMomentDay)
        return Copy.Projects.nothingInMotion(lastHeard: last.map { RelativeDay.absolute($0, today: today, locale: locale) },
                                             distance: last.map { RelativeDay.distance($0, today: today) })
    }

    /// §6.1 layer 7 — "me today" is honest about what the story does not hold yet.
    static func pendingLine(_ p: ProjectPending, today: ISODay) -> String? {
        guard p.unconsolidated > 0 else { return nil }
        return Copy.Projects.waiting(p.unconsolidated, newest: ISODay(p.newestDay).map { RelativeDay.distance($0, today: today) })
    }

    /// R-PP18 — each open follow-up, by the thread claim it asks about.
    static func followups(_ inbox: [InboxItem]) -> [String: InboxItem] {
        var out: [String: InboxItem] = [:]
        for item in inbox where item.kind == .followup {
            if let claim = item.claimId, out[claim] == nil { out[claim] = item }
        }
        return out
    }
}

/// R-PP22 — the Plan's rows and words (R-PJ4, R-PJ11).
enum ProjectPlan {
    struct Row: Identifiable, Equatable {
        let milestone: ProjectMilestone
        let state: ProjectState.MilestoneState
        var id: String { milestone.slug }
    }

    enum Diamond: Equatable { case filled, hollow, slashed }

    /// By target (a done one by its target too, so it keeps its place in the plan), undated last.
    static func rows(_ milestones: [ProjectMilestone], today: ISODay) -> [Row] {
        milestones
            .map { Row(milestone: $0, state: ProjectState.milestoneState($0, today: today)) }
            .sorted { a, b in
                (a.milestone.target ?? a.milestone.doneOn ?? "~", a.milestone.slug)
                    < (b.milestone.target ?? b.milestone.doneOn ?? "~", b.milestone.slug)
            }
    }

    static func meta(_ row: Row, onName: String?, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let m = row.milestone
        func day(_ d: ISODay) -> String { RelativeDay.absolute(d, today: today, locale: locale) }
        let target = ISODay(m.target)
        var words: String
        switch row.state.state {
        case "done":
            let head = Copy.Projects.doneOn(day(ISODay(m.doneOn) ?? today))
            if let days = row.state.days {
                let tail = days < 0 ? Copy.Projects.early(-days) : (days > 0 ? Copy.Projects.late(days) : Copy.Projects.onItsDate)
                words = "\(head) — \(tail)"
            } else {
                words = head
            }
        case "upcoming":
            words = target.map { Copy.Projects.upcoming(day($0), RelativeDay.distance($0, today: today)) } ?? Copy.Projects.someday
        case "overdue":
            words = target.map { Copy.Projects.overdueSince(day($0)) } ?? Copy.Projects.someday
        case "passed-no-word":
            words = target.map { Copy.Projects.passedNoWord(day($0)) } ?? Copy.Projects.someday
        case "missed":
            words = Copy.Projects.missed(target.map(day))
        case "dropped":
            words = Copy.Projects.dropped
        default:
            words = Copy.Projects.someday
        }
        if let onName, !onName.isEmpty, onName != m.name { words = Eyebrow.text(words, Copy.Projects.onProject(onName)) }
        return words
    }

    /// A moved milestone's history, oldest first (R-PJ4: the chain IS the history): "Sep 9 — planned Jul 22", then
    /// "Oct 1 — moved by you on Sep 10". Empty when it never moved.
    static func chain(_ m: ProjectMilestone, today: ISODay, locale: Locale = .autoupdatingCurrent) -> [String] {
        guard m.moved else { return [] }
        let ordered = Array(m.chain.reversed())
        return ordered.enumerated().compactMap { i, c in
            guard let target = ISODay(c.target) ?? (c.predicate == "due" ? ISODay(c.object) : nil),
                  let on = ISODay(c.validFrom) else { return nil }
            let t = RelativeDay.absolute(target, today: today, locale: locale)
            let o = RelativeDay.absolute(on, today: today, locale: locale)
            if i == 0 { return Copy.Projects.plannedOn(target: t, on: o) }
            return c.origin == "companion_app" ? Copy.Projects.movedByYou(target: t, on: o) : Copy.Projects.movedOnDay(target: t, on: o)
        }
    }

    /// Mark done answers a planned, overdue or undated milestone, and a closed `due` nobody said anything about.
    static func canMarkDone(_ row: Row) -> Bool {
        !isPending(row.milestone) && row.milestone.source != "expectedEnd"
            && ["upcoming", "overdue", "someday", "passed-no-word"].contains(row.state.state)
    }

    static func diamond(_ row: Row) -> Diamond {
        switch row.state.state {
        case "done": .filled
        case "passed-no-word", "missed": .slashed
        default: .hollow
        }
    }

    /// An optimistic row (Task 5) has no slot on the server yet: nothing may act on it until the answer lands.
    static func isPending(_ m: ProjectMilestone) -> Bool { m.slug.hasPrefix("pending-") }
}

/// R-PP13 / §6.4 — Around this project, in the brief's words.
enum ProjectAround {
    /// The brief names two groups differently from the server; the rest read as served.
    static func label(_ server: String) -> String {
        switch server {
        case "Documents": Copy.Projects.documentsAndLinks
        case "Sub-projects": Copy.Projects.partsOfThisProject
        default: server
        }
    }

    static func last(_ m: ProjectMember, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String)? {
        ISODay(m.lastSeen).map {
            (Copy.Projects.lastSeen(RelativeDay.absolute($0, today: today, locale: locale)),
             Copy.Projects.lastMentioned(RelativeDay.full($0, locale: locale)))
        }
    }

    /// The brief: "a tool row expands to its spec claims" — tools and the directories grouped with them.
    static func expands(_ m: ProjectMember) -> Bool {
        !m.pending && m.memberId != nil && (m.type == .tool || m.type == .directory)
    }

    /// Its open `spec` claims; with none, up to three open literal claims (§6.4's "one fact" rule, unfolded).
    static func specs(_ claims: [Claim]) -> [Claim] {
        let open = claims.filter(\.isValid)
        let spec = open.filter { $0.predicate == "spec" }
        return spec.isEmpty ? Array(open.filter { $0.objectKind == "literal" }.prefix(3)) : spec
    }

    /// R-PP17 — a part of this project opens as the project, not as a card.
    static func opensProject(_ group: ProjectMemberGroup) -> Bool { group.label == "Sub-projects" }
}
```

  In `app/…/ViewModels/ConversationsViewModel.swift`, after the `ResumeOutcome` enum:

```swift
extension ResumeOutcome {
    /// R-PP26 — one sentence per outcome, so the Reader and the Projects page's Resume never word it two ways.
    var toast: String {
        switch self {
        case .launched(let app): "Reopening in \(app)…"
        case .copied(let command): "Copied “\(command)”"
        case .gone: "That conversation's transcript is gone — nothing to resume"
        case .failed(let message): message
        }
    }
}
```

  and in `Views/Provenance/ReaderColumn.swift`, `act(_:)` (`:132-139`) becomes `store.toast = outcome.toast` (its
  doc keeps its reason).

- [ ] **Step 4: Sentences, chips and source lines.** Create `app/…/Views/Projects/ProjectSentence.swift`:

```swift
import AppKit
import SwiftUI

/// Whether a token had a space before it in the sentence (R-PP15); `SentenceFlowLayout` draws the gap.
private struct SpaceBefore: LayoutValueKey {
    static let defaultValue = false
}

/// R-PP15 — a sentence laid out token by token: words and chips flow left to right and wrap at the width, each line's
/// tokens centred on one line, so a 22-unit chip and the words beside it share a centre (the mock's inline chips). Not
/// the entity card's `FlowLayout`, which top-aligns and spaces every item alike.
struct SentenceFlowLayout: Layout {
    var space: CGFloat
    var lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(subviews, width: proposal.width ?? .infinity).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arranged = arrange(subviews, width: bounds.width)
        for (i, subview) in subviews.enumerated() {
            let f = arranged.frames[i]
            subview.place(at: CGPoint(x: bounds.minX + f.minX, y: bounds.minY + f.minY), proposal: ProposedViewSize(f.size))
        }
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> (size: CGSize, frames: [CGRect]) {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        var lines: [[Int]] = [[]]
        var x: CGFloat = 0
        for (i, size) in sizes.enumerated() {
            let gap = subviews[i][SpaceBefore.self] && x > 0 ? space : 0
            if x > 0, x + gap + size.width > width {
                lines.append([])
                x = 0
            }
            x += (subviews[i][SpaceBefore.self] && x > 0 ? space : 0) + size.width
            lines[lines.count - 1].append(i)
        }
        var frames = Array(repeating: CGRect.zero, count: sizes.count)
        var y: CGFloat = 0
        var widest: CGFloat = 0
        for line in lines where !line.isEmpty {
            let height = line.map { sizes[$0].height }.max() ?? 0
            var lx: CGFloat = 0
            for i in line {
                if subviews[i][SpaceBefore.self], lx > 0 { lx += space }
                frames[i] = CGRect(x: lx, y: y + (height - sizes[i].height) / 2, width: sizes[i].width, height: sizes[i].height)
                lx += sizes[i].width
            }
            widest = max(widest, lx)
            y += height + lineSpacing
        }
        return (CGSize(width: min(widest, width), height: max(0, y - lineSpacing)), frames)
    }
}

/// R-PP15 — a happening as ONE sentence: its words, the owner as the sentence's own word with a "you" tag, and every
/// page a chip that opens its card in the third column. A happening's sentence leads its row (14, `textPrimary`); a
/// moment's is its fact (13, `textSecondary`).
struct StorySentence: View {
    let text: String
    let participants: [ProjectParticipant]
    var lead = true
    let openEntity: (String) -> Void

    private var font: Font { lead ? CicadaTheme.detailBodyFont : CicadaTheme.bodyFont }
    private var ink: Color { lead ? CicadaTheme.textPrimary : CicadaTheme.textSecondary }

    var body: some View {
        let parts = ProjectStory.tokens(text, participants: participants)
        SentenceFlowLayout(space: CicadaTheme.scaled(4), lineSpacing: CicadaTheme.scaled(3)) {
            ForEach(parts.tokens) { token in
                tokenView(token).layoutValue(key: SpaceBefore.self, value: token.spaceBefore)
            }
            ForEach(Array(parts.extra.enumerated()), id: \.offset) { _, p in
                ParticipantChip(participant: p, text: p.name, trailing: "", font: font, open: openEntity)
                    .layoutValue(key: SpaceBefore.self, value: true)
            }
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private func tokenView(_ token: StoryToken) -> some View {
        switch token.kind {
        case .word:
            Text(token.text).font(font).foregroundStyle(ink)
        case .owner:
            if let p = token.participant { OwnerChip(participant: p, text: token.text, trailing: token.trailing, font: font) }
        case .page:
            if let p = token.participant {
                ParticipantChip(participant: p, text: token.text, trailing: token.trailing, font: font, open: openEntity)
            }
        }
    }
}

/// A page the sentence names: its type's dot (DR-8: a hue once per item) and the sentence's own words on a neutral
/// capsule (never a tinted pill, DR-44); a click opens its card. A document with a URL adds ↗, a link (DR-5 use 5).
struct ParticipantChip: View {
    let participant: ProjectParticipant
    let text: String
    let trailing: String
    let font: Font
    let open: (String) -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 0) {
            Button { if let id = participant.id { open(id) } } label: {
                HStack(spacing: CicadaTheme.scaled(5)) {
                    TypeDot(type: participant.type)
                    Text(text).font(font).fontWeight(.medium).foregroundStyle(CicadaTheme.textPrimary)
                }
                .padding(.leading, CicadaTheme.scaled(7))
                .padding(.trailing, CicadaTheme.scaled(8))
                .frame(height: CicadaTheme.scaled(22))
                .background(Capsule().fill(hovering ? CicadaTheme.bgButtonHover : CicadaTheme.bgSelected))
                .contentShape(Capsule())
            }
            .buttonStyle(.cicadaPlain)
            .onHover { hovering = $0 }
            .help(Copy.Projects.openEntity(participant.name, type: participant.type.label))
            .accessibilityLabel(Copy.Projects.openEntity(participant.name, type: participant.type.label))
            if let url = participant.url.flatMap(URL.init(string:)) {
                Button { NSWorkspace.shared.open(url) } label: {
                    Image(systemName: "arrow.up.right")
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.accentText)
                        .padding(.horizontal, CicadaTheme.scaled(4))
                        .frame(height: CicadaTheme.scaled(22))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help(Copy.Projects.openLink(url.host ?? ""))
                .accessibilityLabel(Copy.Projects.openLink(url.host ?? ""))
            }
            if !trailing.isEmpty { Text(trailing).font(font).foregroundStyle(CicadaTheme.textSecondary) }
        }
    }
}

/// R-PP15 — the owner: the sentence's own word with a small "you" tag (the owner's own "[user]" made visual; G117's
/// "Name (you)"). It opens nothing: the page is already about you. The tag sits on `bgBase`, not `Tag`'s `bgSelected`,
/// because it rides on a `bgSelected` capsule and would vanish.
struct OwnerChip: View {
    let participant: ProjectParticipant
    let text: String
    let trailing: String
    let font: Font

    var body: some View {
        HStack(spacing: 0) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Text(text).font(font).fontWeight(.medium).foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.Projects.you)
                    .font(CicadaTheme.captionFont)
                    .fontWeight(.medium)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.scaled(5))
                    .frame(height: CicadaTheme.scaled(16))
                    .background(Capsule().fill(CicadaTheme.bgBase))
            }
            .padding(.leading, CicadaTheme.scaled(8))
            .padding(.trailing, CicadaTheme.scaled(4))
            .frame(height: CicadaTheme.scaled(22))
            .background(Capsule().fill(CicadaTheme.bgSelected))
            .help(Copy.Projects.youHelp(participant.name))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Copy.Projects.youHelp(participant.name))
            if !trailing.isEmpty { Text(trailing).font(font).foregroundStyle(CicadaTheme.textSecondary) }
        }
    }
}

/// R-PP16 — where a row came from, once (DR-54): the origin's real mark (DR-52) and "<App> · <title>", its evidence
/// chip (who spoke and the day, DR-57), and "Show in conversation ›" into the Reader column (DR-31). Nothing is served
/// as `[ no source recorded ]`, exactly as written, at meta weight (DR-55).
struct ProjectSourceLineView: View {
    let line: ProjectSource.Line
    let evidence: Evidence?
    let subjectId: String
    let showing: Bool
    let show: (() -> Void)?

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            switch line {
            case .conversation(let origin, let app, let title):
                OriginMark(origin: origin, size: CicadaTheme.scaled(14))
                Text(Eyebrow.text(app, title)).lineLimit(1)
            case .note:
                Image(systemName: "square.and.pencil").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                Text(Copy.Projects.yourNote)
            case .setByYou:
                Image(systemName: "pencil").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                Text(Copy.Projects.setByYou)
            case .pageHistory:
                Text(Copy.Projects.pageHistory)
            case .none:
                Text(Copy.Projects.noSource)
            case .chipOnly:
                EmptyView()
            }
            if let evidence {
                EvidenceChip(model: EvidenceChipModel(source: .stored(evidence)), subjectId: subjectId)
            }
            Spacer(minLength: 0)
            if let show {
                InlineLink(title: showing ? Copy.Projects.hideConversation : Copy.Projects.showInConversation,
                           help: Copy.Projects.showHelp, action: show)
            }
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
    }
}

/// An expanded row's words (the mock's quote), through `QuoteBlock` — the one door: washed when quoted, bold when found
/// by name, plain when stale (G118 §4.9). Fetched on demand through `ProvenanceCache`; nothing is copied.
struct ProjectQuoteBlock: View {
    let evidence: Evidence
    @Environment(ProvenanceCache.self) private var provenanceCache
    @State private var span: EpisodeSpan?

    var body: some View {
        Group {
            if let span, !span.text.isEmpty {
                QuoteBlock(before: span.before, span: span.text, after: span.after, kind: evidence.kind, label: nil,
                           caption: nil, style: span.stale ? .plain : (evidence.kind == .derived ? .bold : .wash))
            }
        }
        .task(id: evidence) { span = await provenanceCache.span(evidence).value }
    }
}

/// A story row's surface (the mock): `bgHover` under the pointer, `bgFocus` with the strong ring while selected — a
/// ring, never a shadow (DR-9). It grows with its content (rows expand in place), so it is not `ListRowSurface`.
struct StoryRowSurface: ViewModifier {
    let selected: Bool
    @State private var hovering = false

    func body(content: Content) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadius)
        return content
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(shape.fill(selected ? CicadaTheme.bgFocus : (hovering ? CicadaTheme.bgHover : Color.clear)))
            .overlay { if selected { shape.strokeBorder(CicadaTheme.ring(.strong), lineWidth: 1) } }
            .contentShape(Rectangle())
            .onHover { hovering = $0 }
    }
}

/// A row's status glyph (the mock): ● done, ◐ ongoing, ○ said here, a tick for history, a square for stopped — neutral
/// shapes, never a hue (R-PJ21); one glyph, never a dot beside it (DR-48).
struct StoryGlyph: View {
    let glyph: ProjectStory.Glyph

    var body: some View {
        let side = CicadaTheme.scaled(glyph == .ongoing ? 10 : 8)
        Group {
            switch glyph {
            case .done:
                Circle().fill(CicadaTheme.textSecondary)
            case .ongoing:
                Circle().strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(CicadaTheme.textSecondary).frame(width: side / 2)
                    }
                    .clipShape(Circle())
            case .said:
                Circle().strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5)
            case .history:
                CicadaTheme.shape(1).fill(CicadaTheme.textTertiary).frame(width: CicadaTheme.scaled(3))
            case .stopped:
                CicadaTheme.shape(2).strokeBorder(CicadaTheme.textTertiary, lineWidth: 1.5)
            }
        }
        .frame(width: side, height: glyph == .history ? CicadaTheme.scaled(11) : side)
        .accessibilityHidden(true)
    }
}

/// The Plan's diamond (§3.8's shapes): filled when done, hollow when planned, slashed when it passed with no word.
struct PlanDiamond: View {
    let style: ProjectPlan.Diamond

    var body: some View {
        let shape = CicadaTheme.shape(1.5)
        let side = CicadaTheme.scaled(9)
        shape.fill(style == .filled ? CicadaTheme.textPrimary : CicadaTheme.bgBase)
            .overlay { if style != .filled { shape.strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5) } }
            .frame(width: side, height: side)
            .rotationEffect(.degrees(45))
            .overlay { if style == .slashed { Rectangle().fill(CicadaTheme.textSecondary).frame(width: 1.5, height: CicadaTheme.scaled(14)) } }
            .frame(width: CicadaTheme.scaled(14), height: CicadaTheme.scaled(14))
            .accessibilityHidden(true)
    }
}
```

- [ ] **Step 5: The sections.** Create `app/…/Views/Projects/ProjectSections.swift`:

```swift
import SwiftUI

/// R-PP13 — a section's head: its label (DR-20's `SectionLabel`) with a disclosure chevron, and — collapsed — what it
/// holds in words, so a closed section still says so (DR-39).
struct ProjectSectionHeader: View {
    let title: String
    let meta: String
    let isOpen: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.font(size: 9, weight: .medium))
                    .rotationEffect(.degrees(isOpen ? 90 : 0))
                    .foregroundStyle(CicadaTheme.textTertiary)
                SectionLabel(title)
                if !isOpen, !meta.isEmpty {
                    Text(meta).font(CicadaTheme.captionFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(height: CicadaTheme.scaled(24))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(isOpen ? Copy.Projects.collapse : Copy.Projects.expand)
        .accessibilityAddTraits(.isHeader)
    }
}

/// Now (§6.3): the ongoing threads — heard-from first, then quiet — each with its line of days; a quiet one whose
/// follow-up waits in the Inbox links to that card (R-PP18). Under them, the Sleep queue's honest line (§6.1 layer 7).
/// Task 5 passes `settle`, which draws Done · Still going · Stopped.
struct ProjectNowSection: View {
    let timeline: ProjectTimeline
    let state: ProjectState.Output
    let today: ISODay
    let selection: ProjectKey?
    let followups: [String: InboxItem]
    let pick: (ProjectKey) -> Void
    let openEntity: (String) -> Void
    let showSource: (ProjectKey) -> Void
    let openInbox: (String) -> Void
    var settle: ((String, String) -> Void)? = nil
    var writesBlocked = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(ProjectStory.nowThreads(timeline, state: state)) { thread in
                row(thread).id(ProjectKey.thread(thread.claimId).id)
            }
            if timeline.now.threads.isEmpty {
                Text(ProjectStory.nowEmpty(timeline, today: today))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
            }
            if let pending = ProjectStory.pendingLine(timeline.pending, today: today) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "hourglass").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                    Text(pending)
                }
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .help(Copy.Projects.waitingHelp)
            }
        }
    }

    private func row(_ thread: ProjectOpenThread) -> some View {
        let key = ProjectKey.thread(thread.claimId)
        let selected = selection == key
        let item = timeline.items.first { $0.id == thread.claimId }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                StoryGlyph(glyph: .ongoing).padding(.top, CicadaTheme.scaled(6))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    StorySentence(text: thread.text, participants: item?.participants ?? [], openEntity: openEntity)
                    Text(ProjectStory.threadMeta(thread, state: state, today: today))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let followup = followups[thread.claimId] {
                    InlineLink(title: Copy.Projects.howDidItGo, help: Copy.Projects.howDidItGoHelp) { openInbox(followup.id) }
                } else if let settle {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        NeutralButton(title: Copy.Projects.done, size: .compact, isDisabled: writesBlocked,
                                      help: Copy.Projects.doneHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                            settle(thread.claimId, "done")
                        }
                        NeutralButton(title: Copy.Projects.stillGoing, size: .compact, isDisabled: writesBlocked,
                                      help: Copy.Projects.stillGoingHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                            settle(thread.claimId, "ongoing")
                        }
                        NeutralButton(title: Copy.Projects.stopped, size: .compact, isDisabled: writesBlocked,
                                      help: Copy.Projects.stoppedHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                            settle(thread.claimId, "dropped")
                        }
                    }
                }
            }
            if selected, let item {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    if let ev = ProjectSource.evidence(item) { ProjectQuoteBlock(evidence: ev) }
                    ProjectSourceLineView(line: ProjectSource.line(item), evidence: ProjectSource.evidence(item),
                                          subjectId: item.claim?.subject ?? timeline.project.id, showing: false,
                                          show: ProjectSource.target(item, projectId: timeline.project.id) == nil
                                              ? nil : { showSource(key) })
                }
                .padding(.leading, CicadaTheme.scaled(22))
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(key) }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

/// Lately (the brief): Today · Yesterday · This week · Earlier — each happening ONE sentence with its participants as
/// chips, a status word and its date, and its source line; selected, its words, how it was dated, Resume where
/// resumable (R-PP26) and — Task 5 — "Not right". `created` is the foot line.
struct ProjectLatelySection: View {
    let timeline: ProjectTimeline
    let state: ProjectState.Output
    let today: ISODay
    let selection: ProjectKey?
    let readerEpisode: String?
    let names: EntityNames
    let pick: (ProjectKey) -> Void
    let openEntity: (String) -> Void
    let showSource: (ProjectKey) -> Void
    let closeReader: () -> Void
    var withdraw: ((String) -> Void)? = nil
    var writesBlocked = false

    @Environment(Store.self) private var store
    @State private var conversations = ConversationsViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(ProjectStory.groups(timeline.items, today: today)) { group in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    SectionLabel(RelativeDay.title(group.group)).padding(.horizontal, CicadaTheme.spacingMD)
                    ForEach(group.items) { item in row(item).id(ProjectKey.item(item.id).id) }
                }
            }
            if let foot = ProjectStory.createdLine(timeline.items, today: today) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    StoryGlyph(glyph: .history)
                    Text(foot)
                }
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingMD)
            }
        }
    }

    private func row(_ item: ProjectItem) -> some View {
        let key = ProjectKey.item(item.id)
        let selected = selection == key
        let evidence = ProjectSource.evidence(item)
        let target = ProjectSource.target(item, projectId: timeline.project.id)
        let showing = selected && readerEpisode != nil && readerEpisode == target?.episode
        let date = ProjectStory.rowDate(item, today: today)
        return HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            StoryGlyph(glyph: ProjectStory.glyph(item)).padding(.top, CicadaTheme.scaled(6))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                StorySentence(text: item.text, participants: item.participants, lead: item.kind == "happening",
                              openEntity: openEntity)
                if let facts = ProjectStory.factsLine(item, names: names) {
                    Text(facts).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                if selected {
                    if let evidence { ProjectQuoteBlock(evidence: evidence) }
                    if let basis = ProjectStory.basis(item.dateBasis) {
                        Text(basis).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    actions(item)
                }
                ProjectSourceLineView(line: ProjectSource.line(item), evidence: evidence,
                                      subjectId: item.claim?.subject ?? timeline.project.id, showing: showing,
                                      show: target == nil ? nil : { showing ? closeReader() : showSource(key) })
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            VStack(alignment: .trailing, spacing: CicadaTheme.scaled(2)) {
                Text(ProjectStory.status(item, state: state, today: today))
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Text(date.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(date.help)
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(key) }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    @ViewBuilder
    private func actions(_ item: ProjectItem) -> some View {
        let resumable = item.conversation.flatMap { c in c.resumable ? c.id : nil }
        if resumable != nil || (item.kind == "happening" && withdraw != nil) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let id = resumable, let c = item.conversation {
                    NeutralButton(title: Copy.Projects.resume, systemImage: "arrow.uturn.right", size: .compact,
                                  help: Copy.Projects.resumeHelp(OriginIconography.label(for: c.harness ?? c.origin ?? ""))) {
                        // R-PP26 — `POST /conversations/{id}/resume` only checks `isfile()`; a gone transcript says so.
                        Task { store.toast = await conversations.resume(id).toast }
                    }
                }
                if item.kind == "happening", let withdraw {
                    TextButton(title: Copy.Projects.notRight, help: writesBlocked ? Copy.Projects.sleepRunningHelp : Copy.Projects.notRightHelp) {
                        withdraw(item.id)
                    }
                    .disabled(writesBlocked)
                }
            }
        }
    }
}

/// Plan (R-PP22): the milestones by target, each with its diamond, name and state in words; "moved once ›" unfolds
/// its chain. Task 5 passes `markDone`, `rename` and `add`.
struct ProjectPlanSection: View {
    let timeline: ProjectTimeline
    let today: ISODay
    let selection: ProjectKey?
    let names: EntityNames
    let pick: (ProjectKey) -> Void
    let showSource: (ProjectKey) -> Void
    var markDone: ((String) -> Void)? = nil
    var rename: ((String, String) -> Void)? = nil
    var add: ((String, String?) -> Void)? = nil
    /// Bumped by the M key (Task 5) to open the add field.
    var addRequest = 0
    var writesBlocked = false
    /// R-PP23 — true while Rename or Add a milestone is open, so the column's L / M / D stand aside (the Inbox's
    /// `field == nil` guard): a letter typed into these fields is the person's word, never a command.
    var onEditingChange: (Bool) -> Void = { _ in }

    @State private var chainOpen: Set<String> = []
    @State private var renaming: String?
    @State private var renameText = ""
    @State private var adding = false
    @State private var newName = ""
    @State private var hasDate = false
    @State private var newDate = Date()
    @FocusState private var renameFocused: Bool
    @FocusState private var addFocused: Bool

    var body: some View {
        let rows = ProjectPlan.rows(timeline.milestones, today: today)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if rows.isEmpty {
                Text(Copy.Projects.noPlan)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
            }
            ForEach(rows) { row in planRow(row).id(ProjectKey.milestone(row.id).id) }
            if add != nil { addRow }
        }
        .onChange(of: addRequest) { _, _ in
            adding = true
            DispatchQueue.main.async { addFocused = true }
        }
        .onChange(of: renaming != nil || adding) { _, editing in onEditingChange(editing) }
    }

    private func planRow(_ row: ProjectPlan.Row) -> some View {
        let m = row.milestone
        let key = ProjectKey.milestone(m.slug)
        let selected = selection == key
        let chain = ProjectPlan.chain(m, today: today)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                PlanDiamond(style: ProjectPlan.diamond(row))
                if renaming == m.slug, let rename {
                    TextField(Copy.Projects.milestoneName, text: $renameText)
                        .textFieldStyle(.roundedBorder)
                        .focused($renameFocused)
                        .onSubmit {
                            let name = renameText.trimmingCharacters(in: .whitespacesAndNewlines)
                            if !name.isEmpty, name != m.name { rename(m.slug, name) }
                            renaming = nil
                        }
                        .onExitCommand { renaming = nil }
                        .frame(maxWidth: CicadaTheme.scaled(280))
                } else {
                    Text(m.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                }
                Text(ProjectPlan.meta(row, onName: m.on.flatMap { names.name(for: $0) }, today: today))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                if chain.count > 1 {
                    Button {
                        if chainOpen.contains(m.slug) { chainOpen.remove(m.slug) } else { chainOpen.insert(m.slug) }
                    } label: {
                        HStack(spacing: CicadaTheme.scaled(3)) {
                            Text(Copy.Projects.moved(chain.count - 1))
                            Image(systemName: "chevron.right")
                                .rotationEffect(.degrees(chainOpen.contains(m.slug) ? 90 : 0))
                        }
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .buttonStyle(.cicadaPlain)
                }
                Spacer(minLength: 0)
                if let markDone, ProjectPlan.canMarkDone(row) {
                    NeutralButton(title: Copy.Projects.markDone, size: .compact, isDisabled: writesBlocked,
                                  help: Copy.Projects.doneHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                        markDone(m.slug)
                    }
                }
            }
            if chainOpen.contains(m.slug) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(Array(chain.enumerated()), id: \.offset) { i, line in
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Capsule()
                                .fill(i == chain.count - 1 ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                                .frame(width: CicadaTheme.scaled(10), height: 1.5)
                            Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        }
                    }
                }
                .padding(.leading, CicadaTheme.scaled(26))
            }
            if selected {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProjectSourceLineView(line: ProjectSource.line(m, conversations: timeline.conversations),
                                          evidence: m.chain.first?.evidence.first(where: \.isSpan),
                                          subjectId: m.chain.first?.subject ?? timeline.project.id, showing: false,
                                          show: ProjectSource.target(m, projectId: timeline.project.id) == nil
                                              ? nil : { showSource(key) })
                    if rename != nil, renaming != m.slug, !ProjectPlan.isPending(m) {
                        TextButton(title: Copy.Projects.rename, help: Copy.Projects.renameHelp) {
                            renameText = m.name
                            renaming = m.slug
                            DispatchQueue.main.async { renameFocused = true }
                        }
                        .disabled(writesBlocked)
                    }
                }
                .padding(.leading, CicadaTheme.scaled(26))
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(key) }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    /// R-PP22 — a name, and a date only from a native picker (Python decides every date from words; the app has no
    /// second date grammar). Nothing relative is sent: the picker's day goes out as `YYYY-MM-DD` (R-PJ6).
    @ViewBuilder
    private var addRow: some View {
        if adding {
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField(Copy.Projects.milestonePlaceholder, text: $newName)
                    .textFieldStyle(.roundedBorder)
                    .focused($addFocused)
                    .onSubmit(submitAdd)
                    .onExitCommand { adding = false }
                    .accessibilityLabel(Copy.Projects.milestoneName)
                    .frame(maxWidth: CicadaTheme.scaled(320))
                if hasDate {
                    DatePicker("", selection: $newDate, in: Date()..., displayedComponents: .date)
                        .labelsHidden()
                        .datePickerStyle(.field)
                    TextButton(title: Copy.Projects.removeDate) { hasDate = false }
                } else {
                    TextButton(title: Copy.Projects.addDate) { hasDate = true }
                }
                Spacer(minLength: 0)
                TextButton(title: Copy.Projects.cancel) {
                    adding = false
                    newName = ""
                }
                NeutralButton(title: Copy.Projects.add, size: .compact,
                              isDisabled: writesBlocked || newName.trimmingCharacters(in: .whitespaces).isEmpty,
                              help: Copy.Projects.addMilestoneHelp,
                              disabledHelp: writesBlocked ? Copy.Projects.sleepRunningHelp : Copy.Projects.milestoneName) {
                    submitAdd()
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
        } else {
            TextButton(title: Copy.Projects.addMilestone, keyHint: "M", help: Copy.Projects.addMilestoneHelp) {
                adding = true
                DispatchQueue.main.async { addFocused = true }
            }
            .disabled(writesBlocked)
            .padding(.leading, CicadaTheme.scaled(2))
        }
    }

    private func submitAdd() {
        let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !writesBlocked, let add else { return }
        add(name, hasDate ? ISODay.today(now: newDate).description : nil)
        newName = ""
        hasDate = false
        adding = false
    }
}

/// Around this project (§6.4, the brief's labels): each group's pages as one-line rows — the type's dot, the name, its
/// role and one fact, when it was last mentioned. A page opens its card in the third column; a part of this project
/// opens as the project (R-PP17); a tool unfolds its spec claims, each with its chip and "Show in conversation ›"; a
/// name no page holds yet is greyed, "mentioned once, not a page yet" — the promotion rule made visible.
struct ProjectAroundSection: View {
    let cluster: ProjectCluster
    let today: ISODay
    let partial: Bool
    let openCard: String?
    let openEntity: (String) -> Void
    let openProject: (String) -> Void
    let openSource: (ReaderTarget) -> Void

    @State private var expanded: Set<String> = []
    @State private var specs: [String: [Claim]] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(cluster.groups) { group in
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    SectionLabel(ProjectAround.label(group.label)).padding(.horizontal, CicadaTheme.scaled(10))
                    ForEach(group.members) { member in
                        memberRow(member, opensProject: ProjectAround.opensProject(group))
                    }
                    if group.more > 0 {
                        Text(Copy.Projects.moreMembers(group.more))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.horizontal, CicadaTheme.scaled(10))
                    }
                }
            }
            if !cluster.alsoUses.isEmpty {
                Text(Copy.Projects.alsoUses(cluster.alsoUses.map(\.name)))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.scaled(10))
            }
            if partial {
                Text(Copy.Projects.aroundIndexing)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.scaled(10))
            }
        }
    }

    @ViewBuilder
    private func memberRow(_ m: ProjectMember, opensProject: Bool) -> some View {
        if let id = m.memberId, !m.pending {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TypeDot(type: m.type)
                    Text(m.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if !m.rolePhrase.isEmpty {
                        Text(m.rolePhrase).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    }
                    if !m.fact.isEmpty {
                        Text(m.fact).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    if let last = ProjectAround.last(m, today: today) {
                        Text(last.text).font(CicadaTheme.metaFont).monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary).help(last.help)
                    }
                    if ProjectAround.expands(m) {
                        IconButton(systemName: expanded.contains(id) ? "chevron.down" : "chevron.right",
                                   help: expanded.contains(id) ? Copy.Projects.hideSpecs(m.name) : Copy.Projects.showSpecs(m.name)) {
                            toggle(id)
                        }
                    }
                }
                .listRowSurface(height: RowMetrics.oneLine, selected: openCard == id)
                .onTapGesture { opensProject ? openProject(id) : openEntity(id) }
                .accessibilityElement(children: .contain)
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(Copy.Projects.openEntity(m.name, type: m.type.label))
                if expanded.contains(id) { specsView(id) }
            }
        } else {
            HStack(spacing: CicadaTheme.spacingSM) {
                Circle().strokeBorder(CicadaTheme.textTertiary, lineWidth: 1.5)
                    .frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
                Text(m.name).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                Text(Copy.Projects.notAPageYet).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(RowMetrics.oneLine))
            .help(Copy.Projects.notAPageYetHelp)
        }
    }

    @ViewBuilder
    private func specsView(_ id: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if let claims = specs[id] {
                if claims.isEmpty {
                    Text(Copy.Projects.noSpecs).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(claims) { claim in
                    let chips = EvidenceChipModel.chips(evidence: claim.evidence, sourceEpisodes: claim.sourceEpisodes,
                                                        subjectId: id)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(claim.text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                        if let chip = chips.first { EvidenceChip(model: chip, subjectId: id) }
                        Spacer(minLength: 0)
                        if let target = chips.first?.target(subjectId: id, meta: nil) {
                            InlineLink(title: Copy.Projects.showInConversation, help: Copy.Projects.showHelp) {
                                openSource(target)
                            }
                        }
                    }
                }
            } else {
                Text(Copy.Projects.readingCard).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.leading, CicadaTheme.scaled(28))
        .padding(.vertical, CicadaTheme.spacingXS)
    }

    private func toggle(_ id: String) {
        if expanded.contains(id) {
            expanded.remove(id)
            return
        }
        expanded.insert(id)
        guard specs[id] == nil else { return }
        Task {
            let claims = (try? await APIClient.shared.fetchClaims(subject: id)) ?? []
            specs[id] = ProjectAround.specs(claims)
        }
    }
}
```

- [ ] **Step 6: The third column's card.** Create `app/…/Views/Projects/ProjectEntityColumn.swift`:

```swift
import SwiftUI

/// R-PP17 — an entity's card as the Projects page's third column, the Reader's slot: DS-3a's `EntityDetailCard` as it
/// is, in its `.column` style (the card draws its own column edge), with the "go deeper, then come back" trail Clusters
/// keeps (`TopicDetailNavigation`, G108 bug 3) so a wikilink inside it never moves the Graph's selection. A project's
/// card adds "Open project ›", which opens it on this page.
struct ProjectEntityColumn: View {
    let entityId: String
    let openProject: (String) -> Void
    let onClose: () -> Void
    let onEscape: () -> Void

    @Environment(GraphViewModel.self) private var graphVM
    @State private var fullEntity: Entity?
    @State private var nav = TopicDetailNavigation<Entity>()
    @State private var navTask: Task<Void, Never>?

    private var displayEntity: Entity? { nav.pushed ?? fullEntity ?? graphVM.entities.first { $0.id == entityId } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let entity = displayEntity {
                if entity.type == .project {
                    InlineLink(title: Copy.Projects.openProject, help: Copy.Projects.openHelp) { openProject(entity.id) }
                        .padding(.horizontal, CicadaTheme.scaled(28))
                        .padding(.top, CicadaTheme.spacingSM)
                }
                EntityDetailCard(entity: entity, showsCloseButton: true, navigation: cardNavigation, style: .column,
                                 onClose: onClose, onEscape: onEscape)
                    .id(entity.id)
            } else {
                ListSkeleton(message: Copy.Projects.readingCard).padding(CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgBase)
        .task(id: entityId) { fullEntity = try? await APIClient.shared.fetchEntity(id: entityId) }
    }

    private func navigate(to id: String) {
        navTask?.cancel()
        guard let from = displayEntity else { return }
        let token = nav.navigate(from: from, toStub: graphVM.entities.first { $0.id == id })
        navTask = Task {
            guard let full = try? await APIClient.shared.fetchEntity(id: id) else { return }
            nav.apply(full, token: token)
        }
    }

    private func goBack() {
        navTask?.cancel()
        nav.goBack(rootID: entityId)
    }

    private var cardNavigation: EntityCardNavigation {
        EntityCardNavigation(canGoBack: nav.canGoBack, backTargetName: nav.backTarget?.name, goBack: goBack,
                             navigate: navigate)
    }
}
```

- [ ] **Step 7: The detail column, whole.** Replace `app/…/Views/Projects/ProjectDetailColumn.swift` with:

```swift
import SwiftUI

/// §5.3 STATE 1 — one project beside the list, top to bottom (the approved mock): the heading (DR-16's H1 role), the
/// band's header line and the band (Task 3), then the story in one scroll — Now, Lately, Plan, Around this project
/// (R-PP13), each collapsible and remembered per viewer (DR-39). One selection (R-PP11) rings the band's mark and
/// marks the section row; a pick from the band scrolls its row into view (DR-30). It reads `ProjectsCache` (R-PP3): a
/// skeleton on a first open, words when the project is gone, the error card with Retry — never a blank (DR-43).
struct ProjectDetailColumn: View {
    let projectId: String
    let row: ProjectRow?
    let parentName: String?
    let today: ISODay
    let gutter: CGFloat
    let hiddenListCount: Int?
    let openCard: String?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void
    let openProject: (String) -> Void
    let openEntity: (String) -> Void

    @Environment(ProjectsCache.self) private var cache
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    /// DR-39 — which sections this viewer folded, remembered (a convenience, so `UserDefaults`).
    @AppStorage("cicada.projects.collapsed") private var collapsedRaw = ""
    @State private var selection: ProjectKey?
    @State private var scrollToken = 0
    @State private var bandWidth: CGFloat = 0
    @FocusState private var bandFocused: Bool

    private var collapsed: Set<ProjectSection> {
        Set(collapsedRaw.split(separator: ",").compactMap { ProjectSection(rawValue: String($0)) })
    }

    private func setOpen(_ section: ProjectSection, _ open: Bool) {
        var c = collapsed
        if open { c.remove(section) } else { c.insert(section) }
        collapsedRaw = c.map(\.rawValue).sorted().joined(separator: ",")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let t = cache.display(projectId) {
                content(t)
            } else {
                header(name: row?.name ?? "", oneLiner: row?.oneLiner ?? "", parent: row?.parent)
                switch cache.phase(projectId) {
                case .gone:
                    Text(Copy.Projects.gone)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .padding(.top, CicadaTheme.spacingLG)
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.projectFailedTitle, message: message) {
                        Task { await cache.refreshTimeline(projectId) }
                    }
                default:
                    ListSkeleton(message: Copy.Projects.reading).padding(.top, CicadaTheme.spacingLG)
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.detailMaxWidth), maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape() }
        .task(id: projectId) {
            selection = nil
            await cache.refreshTimeline(projectId)
        }
    }

    @ViewBuilder
    private func content(_ t: ProjectTimeline) -> some View {
        let state = ProjectState.state(ProjectState.Input(t), today: today)
        let band = BandLayout.make(t, state: state, width: max(bandWidth - 2 * CicadaTheme.scaled(BandLayout.inset), 1),
                                   today: today)
        header(name: t.project.name, oneLiner: t.project.oneLiner, parent: t.project.parent)
        bandHeader(band, progress: state.progress)
        bandView(band, t)
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(26)) {
                    sections(t, state: state)
                }
                .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                .padding(.top, CicadaTheme.spacingSM)
                .padding(.bottom, CicadaTheme.scaled(72))
                // Every chip below names its conversation's agent ("Claude Code replied") with no fetch per chip.
                .environment(\.evidenceDocIndex, ProjectSource.docIndex(t))
            }
            .onChange(of: scrollToken) { _, _ in
                guard let key = selection else { return }
                Instant.run { proxy.scrollTo(key.id, anchor: .center) }
            }
        }
    }

    @ViewBuilder
    private func sections(_ t: ProjectTimeline, state: ProjectState.Output) -> some View {
        let names = store.entityNames
        let readerEpisode = provenance.isPresented ? provenance.current?.episode : nil
        section(.now, title: Copy.Projects.now, meta: Copy.Projects.inMotionCount(t.now.threads.count)) {
            ProjectNowSection(timeline: t, state: state, today: today, selection: selection,
                              followups: ProjectStory.followups(store.visibleInbox),
                              pick: { pickRow($0, in: t) }, openEntity: openEntity, showSource: { show($0, in: t) },
                              openInbox: { router.routeToInboxItem($0) })
        }
        section(.lately, title: Copy.Projects.lately,
                meta: Copy.Projects.happeningsCount(t.items.filter { $0.kind != "created" }.count)) {
            ProjectLatelySection(timeline: t, state: state, today: today, selection: selection,
                                 readerEpisode: readerEpisode, names: names, pick: { pickRow($0, in: t) },
                                 openEntity: openEntity, showSource: { show($0, in: t) },
                                 closeReader: { provenance.close() })
        }
        section(.plan, title: Copy.Projects.plan,
                meta: state.planned ? Copy.Projects.doneOf(state.progress) : Copy.Projects.noPlanYet) {
            ProjectPlanSection(timeline: t, today: today, selection: selection, names: names,
                               pick: { pickRow($0, in: t) }, showSource: { show($0, in: t) })
        }
        if !t.cluster.groups.isEmpty || !t.cluster.alsoUses.isEmpty {
            section(.around, title: Copy.Projects.around, meta: "") {
                ProjectAroundSection(cluster: t.cluster, today: today, partial: t.partial, openCard: openCard,
                                     openEntity: openEntity, openProject: openProject,
                                     openSource: { provenance.open($0) })
            }
        }
    }

    private func section<Body: View>(_ s: ProjectSection, title: String, meta: String,
                                     @ViewBuilder body: () -> Body) -> some View {
        let open = !collapsed.contains(s)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ProjectSectionHeader(title: title, meta: meta, isOpen: open) { setOpen(s, !open) }
            if open { body() }
        }
    }

    private func bandView(_ band: BandLayout, _ t: ProjectTimeline) -> some View {
        ProjectBandView(layout: band, selected: selection, isFocused: bandFocused) { pickMark($0, in: t) }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                GeometryReader { geo in
                    Color.clear
                        .onAppear { bandWidth = geo.size.width }
                        .onChange(of: geo.size.width) { _, w in bandWidth = w }
                }
            }
            .padding(.top, CicadaTheme.scaled(6))
            .focusable()
            .focused($bandFocused)
            .focusEffectDisabled()
            // DR-68 — ← / → step along the band; ⏎ opens the selection's words in the Reader. Keys never animate.
            .onMoveCommand { direction in
                switch direction {
                case .left: step(band, -1)
                case .right: step(band, 1)
                default: break
                }
            }
            .onKeyPress(.return) {
                guard let key = selection else { return .ignored }
                show(key, in: t)
                return .handled
            }
    }

    // MARK: - Selection (R-PP11)

    /// A mark on the band: select it, open its section if folded, bring its row into view. The band takes the keys
    /// (R-PP23), so ←/→ walk on from the clicked mark and ⏎ opens its words — a mark's `Button` does not take focus
    /// on a click by itself.
    private func pickMark(_ key: ProjectKey, in t: ProjectTimeline) {
        pickRow(key, in: t)
        bandFocused = true
        guard selection == key else { return }
        if collapsed.contains(key.section) { setOpen(key.section, true) }
        scrollToken &+= 1
    }

    private func step(_ band: BandLayout, _ delta: Int) {
        Instant.run { selection = band.step(from: selection, delta: delta) }
        if let key = selection, collapsed.contains(key.section) { setOpen(key.section, true) }
        scrollToken &+= 1
    }

    /// A pick toggles; with the Reader open, a pick citing the same conversation re-lands it, any other closes it
    /// (DR-29).
    private func pickRow(_ key: ProjectKey, in t: ProjectTimeline) {
        Instant.run {
            selection = selection == key ? nil : key
            guard provenance.isPresented, let chosen = selection else { return }
            if let target = ProjectSource.target(for: chosen, in: t, projectId: projectId),
               target.episode == provenance.current?.episode {
                provenance.refocus(target)
            } else {
                provenance.close()
            }
        }
    }

    /// "Show in conversation ›" and the band's ⏎: the Reader as the third column, on the cited words.
    private func show(_ key: ProjectKey, in t: ProjectTimeline) {
        guard let target = ProjectSource.target(for: key, in: t, projectId: projectId) else { return }
        selection = key
        provenance.open(target)
    }

    // MARK: - Heading

    private func header(name: String, oneLiner: String, parent: String?) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let n = hiddenListCount {
                    TextButton(title: Copy.Projects.projectsBack(n), help: Copy.Lists.showList, action: onShowList)
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
                if let parent, let parentName {
                    InlineLink(title: Copy.Projects.partOf(parentName), help: Copy.Projects.openHelp) { openProject(parent) }
                }
                Spacer(minLength: 0)
                Menu {
                    Button(Copy.Projects.openCard) { openEntity(projectId) }
                } label: {
                    Image(systemName: "ellipsis").font(CicadaTheme.icon(.list))
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help(Copy.Projects.moreHelp)
                .accessibilityLabel(Copy.Projects.moreHelp)
                IconButton(systemName: "xmark", help: Copy.Projects.closeHelp, action: onClose)
            }
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(10)) {
                Text(name)
                    .font(CicadaTheme.displayFont(size: 22))
                    .tracking(CicadaTheme.displayTracking(size: 22))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                Tag(text: Copy.Projects.tag, dot: CicadaTheme.entityColor(for: .project))
            }
            if !oneLiner.isEmpty {
                Text(oneLiner).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
            }
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    private func bandHeader(_ band: BandLayout, progress: ProjectProgress) -> some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Text(band.since).foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: 0)
            if let words = band.progressWords {
                Text(words)
                    .fontWeight(.medium)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .help(Copy.Projects.barHelp(planned: true, progress: progress))
            } else {
                Text(Copy.Projects.noPlanYet).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .font(CicadaTheme.metaFont)
        .monospacedDigit()
        .frame(height: CicadaTheme.scaled(22))
        .padding(.top, CicadaTheme.scaled(18))
    }
}
```

- [ ] **Step 8: The third column on the page.** In `ProjectsPage.swift`:
  - add `@State private var card: String?` (R-PP17 — an entity's card in the third column; the Reader wins the slot);
  - `ProgressiveColumns(hasDetail: …, hasTrailing: provenance.isPresented || card != nil, …)`;
  - the detail closure's call becomes (the parameters in `ProjectDetailColumn`'s declaration order):

```swift
                ProjectDetailColumn(
                    projectId: id, row: row, parentName: parentName(of: row?.parent), today: today, gutter: plan.gutter,
                    hiddenListCount: plan.listHidden ? lines.count : nil, openCard: card,
                    onShowList: { showList() }, onClose: { closeProject() }, onEscape: { escape() },
                    openProject: { openProject($0) }, openEntity: { openCard($0) })
```

  - the trailing closure becomes:

```swift
        } trailing: { _ in
            if provenance.isPresented {
                ReaderColumn().focused($focus, equals: .reader)
            } else if let card {
                ProjectEntityColumn(entityId: card, openProject: { openProject($0) }, onClose: { closeCard() },
                                    onEscape: { escape() })
                    .id(card)
                    .focused($focus, equals: .reader)
            }
        }
```

  - add the paths, and fold the card into the existing ones:

```swift
    /// R-PP17 — a chip or a member opens its card beside the project; the Reader steps aside (one slot). A Reader
    /// opened from inside the card returns to it on close.
    private func openCard(_ id: String) {
        card = id
        if provenance.isPresented { provenance.close() }
    }

    private func closeCard() { card = nil }
```

    `openProject(_:)`'s `change` closure and `move(_:in:)`'s `Instant.run` body each add `card = nil` beside their
    `provenance.close()`; `closeProject()` adds `card = nil` inside its `withAnimation`; `showList()` becomes:

```swift
    /// DR-27 — "‹ N projects" brings the list back by closing the rightmost thing: the Reader, else the card, else
    /// the project.
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else if card != nil { card = nil } else { columns.close() }
        }
    }
```

    and `escape()` becomes:

```swift
    /// DR-28 — Esc closes the rightmost open thing: the Reader, then the card, then the project.
    private func escape() {
        Instant.run {
            if provenance.isPresented {
                provenance.close()
            } else if card != nil {
                card = nil
            } else if columns.openId != nil {
                columns.close()
                focus = .list
            }
        }
    }
```

  - a bank switch forgets the card and the open project: `.onChange(of: store.bank) { _, _ in card = nil;
    columns.close() }`.

- [ ] **Step 9: Green.** `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectStoryTests|ProjectBandTests|ProjectsListTests|SelectionTintLintTests|FontLiteralLintTests|SectionLabelLintTests|CountLiteralLintTests|RelativeDayTests|ElevationLintTests|MeadowPlacementLintTests' 2>&1 | tail -20`
  passes; then `swift build` and the full `swift test` (0 failures).

- [ ] **Step 10: Commit.**

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectStory.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectSentence.swift app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectSections.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectEntityColumn.swift app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectDetailColumn.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsPage.swift app/CicadaApp/Sources/CicadaApp/ViewModels/ConversationsViewModel.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderColumn.swift app/CicadaApp/Tests/CicadaAppTests/ProjectStoryTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/SelectionTintLintTests.swift
cd <worktree> && git commit -m "feat(projects): Now · Lately · Plan · Around this project, every participant a chip, the Reader or a card as the third column (G141 PJ-5, R-PP11, R-PP13…R-PP18, R-PP22, R-PP26; DR-9, DR-16, DR-18, DR-20, DR-28, DR-29, DR-31, DR-37, DR-39, DR-40, DR-44, DR-47, DR-48, DR-52, DR-54…DR-58, DR-60, DR-69)"
```

---

### Task 5: Writes — Log progress, the threads' answers, the Plan's milestones, "Not right"; L · M · D (DR-40, DR-41, DR-49, DR-55, DR-59, DR-60, DR-68; R-PP19…R-PP23, R-PP25; R-PJ6, R-PJ18)

The person's five writes, through the one write path the app has: a `Mutation` run by `Store.perform`. Where the
answer is known before the server speaks, the page paints it at once and rolls it back with a toast on failure. A
409 says the server's own sentence. The Log is dated by the server and says how, with Undo. While Sleep runs, every
write control waits, with its reason on hover.

**Files:**
- Create: `app/…/Sync/ProjectMutations.swift`, `app/…/Views/Projects/ProjectLogField.swift`.
- Modify: `app/…/Sync/SyncAPI.swift`, `app/…/Services/APIClient.swift`, `app/…/Views/Projects/ProjectsCache.swift`
  (overlays), `ProjectDetailColumn.swift` (the Log, the sections' closures, the keys, the gate, the menu),
  `app/…/Views/Shell/TitlebarHelp.swift` (L · M · D), `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift`
  (`FakeSyncAPI`).
- Test: `ProjectWritesTests.swift` (new). Edit `TitlebarHelpTests.swift`.

**Interfaces:**
- Produces: `SyncAPI.addProjectMilestone` / `changeProjectMilestone` / `logProjectHappening` / `settleProjectThread` /
  `withdrawProjectHappening`; `APIClient.projectPath`; `MilestoneChange`; `ProjectWrite` (`Action`, `overlay`,
  `overlayId`, `result`); `ProjectWriteFailure`; `ProjectWriteGate`; `ProjectOverlay` (`Change`, `apply`);
  `ProjectsCache.overlays` / `add` / `remove(overlayId:)` / `confirm(_:)`; `ProjectLogWords`; `ProjectLogField`.
- Consumes: `Mutation`, `MutationMemo`, `Store.perform`, `Store.toast`, `Store.status`, `CicadaTiming.undoWindow`,
  `KeyHint`, Tasks 1–4.

- [ ] **Step 1: Failing tests.** Create `ProjectWritesTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-PP19…R-PP21 — every Projects write is a `Mutation`: painted where the answer is known, rolled back in words, and
/// never a relative word sent as a value.
@MainActor
final class ProjectWritesTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func harness() async throws -> (Store, FakeSyncAPI, ProjectsCache, FakeProjectsAPI) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let reads = FakeProjectsAPI()
        reads.timelineReplies["rover-arm-project"] = [
            .success(Conditional(value: try ProjectFixtures.timeline("rover-arm-project"), etag: "t1", notModified: false))]
        let cache = ProjectsCache(api: reads)
        await cache.refreshTimeline("rover-arm-project")
        return (store, api, cache, reads)
    }

    func testSettlingAThreadHidesItAtOnceAndSendsTheWrite() async throws {
        let (store, api, cache, _) = try await harness()
        let camera = try XCTUnwrap(cache.display("rover-arm-project")?.now.threads.first { $0.since == "2026-08-30" })
        let write = ProjectWrite(projectId: "rover-arm-project", action: .settle(claimId: camera.claimId, status: "done"),
                                 cache: cache, day: ProjectFixtures.today)
        api.gateWrites = true
        let running = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        XCTAssertFalse(try XCTUnwrap(cache.display("rover-arm-project")).now.threads.contains { $0.claimId == camera.claimId },
                       "painted before the server answers")
        api.releaseWriteGate()
        let ok = await running.value
        XCTAssertTrue(ok)
        XCTAssertEqual(api.writes.last, "settleProjectThread:rover-arm-project:\(camera.claimId):done")
    }

    /// A 409 — Sleep is writing — rolls the paint back and says the server's own sentence.
    func testA409RollsBackAndSaysSoInPlainWords() async throws {
        let (store, api, cache, _) = try await harness()
        api.projectWriteError = APIError.httpError(409, #"{"detail":"Sleep is writing this project, try again in a moment"}"#)
        let write = ProjectWrite(projectId: "rover-arm-project",
                                 action: .changeMilestone(slug: "first-grasp", change: MilestoneChange(status: "done")),
                                 cache: cache, day: ProjectFixtures.today)
        let ok = await store.perform(write)
        XCTAssertFalse(ok)
        XCTAssertEqual(cache.display("rover-arm-project")?.milestones.first { $0.slug == "first-grasp" }?.status, "planned")
        XCTAssertEqual(store.toast, "Sleep is writing this project, try again in a moment")
        XCTAssertTrue(cache.overlays["rover-arm-project", default: []].isEmpty)
    }

    /// R-PP21 — the Log paints nothing (the server decides the day) and sends no relative word as a value.
    func testTheLogKeepsTheServersDayAndSaysHowItWasDecided() async throws {
        let (store, api, cache, _) = try await harness()
        api.projectWriteReply = ProjectWriteResponse(action: "created", claimId: "clm_x", day: "2026-09-22",
                                                     dateBasis: "stated", episodeId: "ep_2026-09-23_050")
        let write = ProjectWrite(projectId: "rover-arm-project",
                                 action: .log(text: "Yesterday I got the guide", status: "done", when: nil),
                                 cache: cache, day: ProjectFixtures.today)
        XCTAssertNil(write.overlay)
        let ok = await store.perform(write)
        XCTAssertTrue(ok)
        XCTAssertEqual(write.result?.day, "2026-09-22")
        XCTAssertEqual(api.writes.last, "logProjectHappening:rover-arm-project:done:nil")
        XCTAssertEqual(ProjectLogWords.confirmation("Rover Arm Project", answer: try XCTUnwrap(write.result), sentDay: false,
                                                    today: ProjectFixtures.today, locale: us),
                       "Logged on Rover Arm Project for Sep 22 (yesterday) — dated from your words")
        XCTAssertEqual(ProjectLogWords.confirmation("Rover Arm Project",
                                                    answer: ProjectWriteResponse(action: "created", claimId: "c",
                                                                                 day: "2026-09-20", dateBasis: "person"),
                                                    sentDay: true, today: ProjectFixtures.today, locale: us),
                       "Logged on Rover Arm Project for Sep 20 (3 days ago) — the day you picked")
        XCTAssertEqual(ProjectLogWords.confirmation("Rover Arm Project",
                                                    answer: ProjectWriteResponse(action: "created", claimId: "c",
                                                                                 day: "2026-09-23", dateBasis: "person"),
                                                    sentDay: false, today: ProjectFixtures.today, locale: us),
                       "Logged on Rover Arm Project for Sep 23 (today) — no day in your words, so today")
    }

    /// DR-54 — only a 409's or a 422's sentence is shown as the server wrote it; a 400's or a 404's names ids.
    func testFailureWordsNeverLeakAnId() {
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(422, #"{"detail":"Say one day, or pick it with the date chip"}"#)),
                       "Say one day, or pick it with the date chip")
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(404, #"{"detail":"No happening or milestone 'clm_x' on this project"}"#)),
                       Copy.Projects.notOnProject)
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(400, #"{"detail":"on must be a date (YYYY-MM-DD)"}"#)),
                       Copy.Projects.saveFailed)
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(422, #"{"detail":[{"loc":["body","text"]}]}"#)),
                       Copy.Projects.saveFailed, "a validation list is not a sentence")
        XCTAssertEqual(ProjectWriteFailure.message(APIError.serverUnreachable), Copy.Projects.backendDown)
        XCTAssertEqual(ProjectWriteFailure.message(nil), Copy.Projects.saveFailed)
    }

    /// A paint stays until the server's next answer holds the write, and every paint does what it says.
    func testOverlaysPaintThenClearOnTheNextAnswer() async throws {
        let (store, _, cache, reads) = try await harness()
        let add = ProjectWrite(projectId: "rover-arm-project", action: .addMilestone(name: "Demo dry run", target: "2026-10-03"),
                               cache: cache, day: ProjectFixtures.today)
        _ = await store.perform(add)
        cache.confirm(add.overlayId)
        XCTAssertTrue(try XCTUnwrap(cache.display("rover-arm-project")).milestones
            .contains { $0.name == "Demo dry run" && ProjectPlan.isPending($0) })
        reads.timelineReplies["rover-arm-project"] = [
            .success(Conditional(value: try ProjectFixtures.timeline("rover-arm-project"), etag: "t2", notModified: false))]
        await cache.refreshTimeline("rover-arm-project")
        XCTAssertTrue(cache.overlays["rover-arm-project", default: []].isEmpty, "the server's answer replaces the paint")

        var t = try ProjectFixtures.timeline("rover-arm-project")
        func paint(_ change: ProjectOverlay.Change) -> ProjectOverlay {
            ProjectOverlay(id: UUID(), projectId: "rover-arm-project", change: change, day: ProjectFixtures.today)
        }
        let quiet = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" }).claimId
        t = ProjectOverlay.apply([paint(.threadRestated(claimId: quiet))], to: t)
        XCTAssertEqual(t.now.threads.first { $0.claimId == quiet }?.lastHeard, "2026-09-23", "still going: heard from today")
        t = ProjectOverlay.apply([paint(.milestoneRenamed(slug: "first-grasp", name: "First pick"))], to: t)
        XCTAssertEqual(t.milestones.first { $0.slug == "first-grasp" }?.name, "First pick")
        t = ProjectOverlay.apply([paint(.milestoneDone(slug: "first-grasp"))], to: t)
        XCTAssertEqual(t.milestones.first { $0.slug == "first-grasp" }?.doneOn, "2026-09-23")
        t = ProjectOverlay.apply([paint(.withdrawn(claimId: quiet))], to: t)
        XCTAssertFalse(t.items.contains { $0.id == quiet })
        XCTAssertFalse(t.now.threads.contains { $0.claimId == quiet })
    }

    /// R-PP20 — the controls wait while Sleep writes (the server's own 409 condition).
    func testWritesWaitWhileSleepRuns() {
        func status(_ sleep: String) -> StatusSnapshot {
            StatusSnapshot(sleep: .init(status: sleep, stage: 0, totalStages: 5, cycleId: nil, error: nil),
                           inbox: .init(total: 0, byKind: [:]), episodes: .init(unprocessed: 0, lastIngestedAt: nil),
                           lastSleepAt: nil, nextSleepAt: nil)
        }
        XCTAssertTrue(ProjectWriteGate.blocked(status("running")))
        XCTAssertFalse(ProjectWriteGate.blocked(status("idle")))
        XCTAssertFalse(ProjectWriteGate.blocked(nil))
    }
}
```

  In `TitlebarHelpTests.swift` the `ListHelp.projects` keys become `["⌘F", "↑ ↓", "⏎", "← →", "L", "M", "D", "Esc"]`.

- [ ] **Step 2: See them fail.** `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectWritesTests|TitlebarHelpTests' 2>&1 | tail -20`
  fails to compile.

- [ ] **Step 3: The writes on the wire.** In `app/…/Sync/SyncAPI.swift`, in the Writes block after `triggerSleep()`:

```swift
    /// G141 PJ-5 (R-PP19) — the Projects page's five writes (`routers/projects.py`), each answering the claim it wrote,
    /// the day and how that day was decided. Every day sent is `YYYY-MM-DD`: nothing relative is sent as a value
    /// (R-PJ6). All answer 409 while a Sleep cycle runs.
    func addProjectMilestone(project: String, name: String, target: String?) async throws -> ProjectWriteResponse
    func changeProjectMilestone(project: String, slug: String, change: MilestoneChange) async throws -> ProjectWriteResponse
    func logProjectHappening(project: String, text: String, status: String, when: String?) async throws -> ProjectWriteResponse
    func settleProjectThread(project: String, claimId: String, status: String) async throws -> ProjectWriteResponse
    func withdrawProjectHappening(project: String, claimId: String) async throws -> ProjectWriteResponse
```

  In `app/…/Services/APIClient.swift`, at the end of the file (an extension in the same file, so the private `post`,
  `makeRequest`, `session` and `decoder` are in reach):

```swift
// MARK: - Projects (G141 PJ-5) — the person's five writes

extension APIClient {
    /// `/projects/<id>/<tail…>`, every component encoded the way `provenancePath` encodes an id: a slug or a claim id
    /// never reshapes the URL.
    nonisolated static func projectPath(_ id: String, _ tail: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/projects/" + ([id] + tail).map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    func addProjectMilestone(project: String, name: String, target: String?) async throws -> ProjectWriteResponse {
        var body: [String: Any] = ["name": name]
        if let target { body["target"] = target }
        return try await post(Self.projectPath(project, "milestones"), body: body)
    }

    func changeProjectMilestone(project: String, slug: String, change: MilestoneChange) async throws -> ProjectWriteResponse {
        try await patch(Self.projectPath(project, "milestones", slug), body: change.body)
    }

    func logProjectHappening(project: String, text: String, status: String, when: String?) async throws -> ProjectWriteResponse {
        var body: [String: Any] = ["text": text, "status": status]
        if let when { body["when"] = when }
        return try await post(Self.projectPath(project, "happenings"), body: body)
    }

    func settleProjectThread(project: String, claimId: String, status: String) async throws -> ProjectWriteResponse {
        try await post(Self.projectPath(project, "threads", claimId), body: ["status": status])
    }

    func withdrawProjectHappening(project: String, claimId: String) async throws -> ProjectWriteResponse {
        try await post(Self.projectPath(project, "withdraw"), body: ["claimId": claimId])
    }

    /// The PATCH twin of `put` — `PATCH /projects/{id}/milestones/{slug}` is the one PATCH the app sends.
    private func patch<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        var request = makeRequest(path, method: "PATCH")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
}
```

  In `Tests/CicadaAppTests/StoreTests.swift`, inside `FakeSyncAPI` after `triggerSleep()`:

```swift
    // MARK: Projects (G141 PJ-5)

    /// What every Projects write answers; set `projectWriteError` to drive a rollback (a 409 with the server's words).
    var projectWriteReply = ProjectWriteResponse(action: "created", claimId: "clm_fake", day: "2026-09-23",
                                                 dateBasis: "person")
    var projectWriteError: (any Error)?

    private func projectWrite(_ what: String) async throws -> ProjectWriteResponse {
        try await record(what)
        if let projectWriteError { throw projectWriteError }
        return projectWriteReply
    }

    func addProjectMilestone(project: String, name: String, target: String?) async throws -> ProjectWriteResponse {
        try await projectWrite("addProjectMilestone:\(project):\(name):\(target ?? "nil")")
    }
    func changeProjectMilestone(project: String, slug: String, change: MilestoneChange) async throws -> ProjectWriteResponse {
        try await projectWrite("changeProjectMilestone:\(project):\(slug):\(change.status ?? "nil"):\(change.name ?? "nil")")
    }
    func logProjectHappening(project: String, text: String, status: String, when: String?) async throws -> ProjectWriteResponse {
        try await projectWrite("logProjectHappening:\(project):\(status):\(when ?? "nil")")
    }
    func settleProjectThread(project: String, claimId: String, status: String) async throws -> ProjectWriteResponse {
        try await projectWrite("settleProjectThread:\(project):\(claimId):\(status)")
    }
    func withdrawProjectHappening(project: String, claimId: String) async throws -> ProjectWriteResponse {
        try await projectWrite("withdrawProjectHappening:\(project):\(claimId)")
    }
```

- [ ] **Step 4: The mutation.** Create `app/…/Sync/ProjectMutations.swift`:

```swift
import Foundation

/// `PATCH /projects/{id}/milestones/{slug}` — a rename, a new state, or both (the server applies the name first).
struct MilestoneChange: Equatable, Sendable {
    var name: String?
    var status: String?
    var target: String?
    var on: String?

    var body: [String: Any] {
        var body: [String: Any] = [:]
        if let name { body["name"] = name }
        if let status { body["status"] = status }
        if let target { body["target"] = target }
        if let on { body["on"] = on }
        return body
    }
}

/// G141 PJ-5 (R-PP19) — one of the Projects page's five writes, run by `Store.perform` like every write the app sends:
/// its optimistic half paints `ProjectsCache` (the page's data lives there, not in a Store domain — R-PP3), its
/// request goes out through `SyncAPI`, and a failure rolls the paint back and toasts in plain words. The server's
/// answer (the claim, the day and how the day was decided) is kept in `result` for the Log's confirmation and its Undo
/// (`SyncSafariTabs`' memo pattern). `refreshDomains` is empty: the page revalidates the cache itself, and the Store
/// follows the bank's own sync events.
struct ProjectWrite: Mutation {
    enum Action: Equatable {
        case addMilestone(name: String, target: String?)
        case changeMilestone(slug: String, change: MilestoneChange)
        case log(text: String, status: String, when: String?)
        case settle(claimId: String, status: String)
        case withdraw(claimId: String)
    }

    let projectId: String
    let action: Action
    let cache: ProjectsCache
    /// The viewer's today: the day an optimistic paint is dated.
    let day: ISODay
    let overlayId = UUID()
    private let memo = MutationMemo<ProjectWriteResponse>()
    private let failure = MutationMemo<any Error>()

    init(projectId: String, action: Action, cache: ProjectsCache, day: ISODay) {
        self.projectId = projectId
        self.action = action
        self.cache = cache
        self.day = day
    }

    var result: ProjectWriteResponse? { memo.value }

    /// R-PP19 — painted only where the answer is known before the server speaks. Never the Log: its day comes from
    /// the words, decided by `when.py`.
    var overlay: ProjectOverlay? {
        let change: ProjectOverlay.Change
        switch action {
        case .addMilestone(let name, let target):
            change = .milestoneAdded(name: name, target: target)
        case .changeMilestone(let slug, let c):
            if c.status == "done" {
                change = .milestoneDone(slug: slug)
            } else if let name = c.name {
                change = .milestoneRenamed(slug: slug, name: name)
            } else {
                return nil
            }
        case .log:
            return nil
        case .settle(let claimId, let status):
            change = status == "ongoing" ? .threadRestated(claimId: claimId) : .threadSettled(claimId: claimId)
        case .withdraw(let claimId):
            change = .withdrawn(claimId: claimId)
        }
        return ProjectOverlay(id: overlayId, projectId: projectId, change: change, day: day)
    }

    func optimistic(_ store: Store) async {
        if let overlay { cache.add(overlay) }
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            switch action {
            case .addMilestone(let name, let target):
                memo.value = try await api.addProjectMilestone(project: projectId, name: name, target: target)
            case .changeMilestone(let slug, let change):
                memo.value = try await api.changeProjectMilestone(project: projectId, slug: slug, change: change)
            case .log(let text, let status, let when):
                memo.value = try await api.logProjectHappening(project: projectId, text: text, status: status, when: when)
            case .settle(let claimId, let status):
                memo.value = try await api.settleProjectThread(project: projectId, claimId: claimId, status: status)
            case .withdraw(let claimId):
                memo.value = try await api.withdrawProjectHappening(project: projectId, claimId: claimId)
            }
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        cache.remove(overlayId: overlayId)
    }

    var failureMessage: String { ProjectWriteFailure.message(failure.value) }
}

/// R-PP19 — a failed write in words. A 409 (Sleep is writing) and a 422 (a date the words could not settle) carry
/// `routers/projects.py`'s own sentences, written for the person; every other failure gets this page's words — a 400's
/// or a 404's detail names ids and field names (DR-54).
enum ProjectWriteFailure {
    static func message(_ error: (any Error)?) -> String {
        guard let api = error as? APIError else { return Copy.Projects.saveFailed }
        switch api {
        case .httpError(let code, let body) where code == 409 || code == 422:
            return detail(body) ?? (code == 409 ? Copy.Projects.sleepBusy : Copy.Projects.saveFailed)
        case .httpError(404, _):
            return Copy.Projects.notOnProject
        case .serverUnreachable:
            return Copy.Projects.backendDown
        default:
            return Copy.Projects.saveFailed
        }
    }

    /// FastAPI's `{"detail": "…"}`, when the detail is a sentence (a validation error's detail is a list — not ours).
    static func detail(_ body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] as? String, !detail.isEmpty else { return nil }
        return detail
    }
}

/// R-PP20 — while Sleep runs every Projects write answers 409 (`_guard`, `routers/projects.py`), so the controls say
/// so before a click (DR-41: disabled, with the reason in `.help`).
enum ProjectWriteGate {
    static func blocked(_ status: StatusSnapshot?) -> Bool { status?.sleep.status == "running" }
}

/// R-PP21 — the Log's confirmation: the day the server chose, with its distance, and how it was decided.
enum ProjectLogWords {
    static func confirmation(_ name: String, answer: ProjectWriteResponse, sentDay: Bool, today: ISODay,
                             locale: Locale = .autoupdatingCurrent) -> String {
        let day = ISODay(answer.day) ?? today
        let when = Copy.Projects.dayAndDistance(RelativeDay.absolute(day, today: today, locale: locale),
                                                RelativeDay.distance(day, today: today))
        let how = answer.dateBasis == "stated" ? Copy.Projects.fromYourWords
            : (sentDay ? Copy.Projects.fromTheChip : Copy.Projects.noDayInWords)
        return Copy.Projects.logged(name, day: when, how: how)
    }
}
```

- [ ] **Step 5: Paints on the cache.** In `ProjectsCache.swift`:
  - add `private(set) var overlays: [String: [ProjectOverlay]] = [:]` beside `timelines`;
  - `display(_:)` becomes `timelines[id].map { ProjectOverlay.apply(overlays[id] ?? [], to: $0) }`;
  - `reset()` also sets `overlays = [:]`;
  - in `refreshTimeline(_:)`, right after `if let value = answer.value { store(value, etag: answer.etag, for: id) }`,
    add `if answer.value != nil { overlays[id]?.removeAll(where: \.confirmed) }` — a fresh answer holds every write
    confirmed before it;
  - add:

```swift
    // MARK: - Optimistic writes (R-PP19)

    func add(_ overlay: ProjectOverlay) { overlays[overlay.projectId, default: []].append(overlay) }

    func remove(overlayId: UUID) {
        for key in overlays.keys { overlays[key]?.removeAll { $0.id == overlayId } }
    }

    /// The server accepted it: the paint stays until the next fresh answer, which holds the write.
    func confirm(_ overlayId: UUID) {
        for key in overlays.keys {
            if let i = overlays[key]?.firstIndex(where: { $0.id == overlayId }) { overlays[key]?[i].confirmed = true }
        }
    }
```

  and, after `ProjectsRefresh`:

```swift
/// R-PP19 — a write painted over the cached timeline before the server answers: only what the answer cannot change —
/// a thread settled or restated today, a milestone done today or renamed, a new milestone, a withdrawal. A milestone
/// added here has no slot yet (`pending-…`), so nothing acts on it until the answer lands.
struct ProjectOverlay: Identifiable, Equatable {
    enum Change: Equatable {
        case threadSettled(claimId: String)
        case threadRestated(claimId: String)
        case milestoneDone(slug: String)
        case milestoneRenamed(slug: String, name: String)
        case milestoneAdded(name: String, target: String?)
        case withdrawn(claimId: String)
    }

    let id: UUID
    let projectId: String
    let change: Change
    let day: ISODay
    var confirmed = false

    static func apply(_ overlays: [ProjectOverlay], to timeline: ProjectTimeline) -> ProjectTimeline {
        var t = timeline
        for o in overlays {
            let day = o.day.description
            switch o.change {
            case .threadSettled(let id):
                t.now.threads.removeAll { $0.claimId == id }
            case .threadRestated(let id):
                if let i = t.now.threads.firstIndex(where: { $0.claimId == id }) { t.now.threads[i].lastHeard = day }
            case .milestoneDone(let slug):
                if let i = t.milestones.firstIndex(where: { $0.slug == slug }) {
                    t.milestones[i].status = "done"
                    t.milestones[i].doneOn = day
                }
            case .milestoneRenamed(let slug, let name):
                if let i = t.milestones.firstIndex(where: { $0.slug == slug }) { t.milestones[i].name = name }
            case .milestoneAdded(let name, let target):
                t.milestones.append(ProjectMilestone(slug: "pending-\(o.id.uuidString)", name: name, status: "planned",
                                                     target: target))
            case .withdrawn(let id):
                t.items.removeAll { $0.id == id }
                t.now.threads.removeAll { $0.claimId == id }
            }
        }
        return t
    }
}
```

- [ ] **Step 6: Log progress.** Create `app/…/Views/Projects/ProjectLogField.swift`:

```swift
import SwiftUI

/// R-PP21 — Log progress: one line above the story (the mock). ⏎ saves it as done, ⌘⏎ as still going. The day comes
/// from the words, decided by the server (`when.py`, the one date grammar); the date chip picks it when the words don't
/// say it (the server's own 422 sentence points at the chip); else today. Nothing relative is sent as a value (R-PJ6):
/// the words go as the person wrote them, the chip as `YYYY-MM-DD`. After saving, the day the server chose and how, with
/// Undo for `CicadaTiming.undoWindow` — Undo withdraws the claim the server wrote; the note keeps the person's words.
struct ProjectLogField: View {
    let projectName: String
    let today: ISODay
    let blocked: Bool
    let focus: FocusState<Bool>.Binding
    let save: (_ text: String, _ status: String, _ when: String?) async -> ProjectWriteResponse?
    let undo: (_ claimId: String) async -> Void

    @State private var text = ""
    @State private var day: ISODay?
    @State private var pickerOpen = false
    @State private var saving = false
    @State private var logged: (words: String, claimId: String)?

    private var isEmpty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                Image(systemName: "plus.bubble")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                TextField(Copy.Projects.logPlaceholder, text: $text)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.detailBodyFont)
                    .focused(focus)
                    .disabled(blocked)
                    .accessibilityLabel(Copy.Projects.logLabel(projectName))
                    // The palette's split (`FindPanelBody`, `FindKeymap`): plain ⏎ stays on the field's own
                    // `onSubmit`; ⌘⏎ is read here, on the field, and handled so `onSubmit` never also fires.
                    .onSubmit { submit("done") }
                    .onKeyPress(keys: [.return]) { press in
                        guard press.modifiers.contains(.command) else { return .ignored }
                        submit("ongoing")
                        return .handled
                    }
                dateChip
                if isEmpty {
                    KeyHint("L")
                } else {
                    NeutralButton(title: Copy.Projects.logButton, size: .compact, keyHint: "⏎",
                                  isDisabled: blocked || saving, help: Copy.Projects.logHint,
                                  disabledHelp: Copy.Projects.sleepRunningHelp) { submit("done") }
                }
            }
            .padding(.leading, CicadaTheme.spacingMD)
            .padding(.trailing, CicadaTheme.scaled(5))
            .frame(height: CicadaTheme.scaled(38))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .ringed(.input, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .help(blocked ? Copy.Projects.sleepRunningHelp : "")
            status.padding(.leading, CicadaTheme.spacingMD)
        }
    }

    @ViewBuilder
    private var status: some View {
        if saving {
            Text(Copy.Projects.saving).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        } else if let logged {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "checkmark").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                Text(logged.words)
                TextButton(title: Copy.Projects.undo, help: Copy.Projects.undoHelp) {
                    let claimId = logged.claimId
                    self.logged = nil
                    Task { await undo(claimId) }
                }
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
        } else if !isEmpty {
            Text(Copy.Projects.logHint).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// The date chip: today's word until one is picked; a native graphical picker, capped at today (a happening is
    /// never in the future).
    private var dateChip: some View {
        TextButton(title: RelativeDay.phrase(day ?? today, today: today), help: Copy.Projects.dateChipHelp) {
            pickerOpen = true
        }
        .disabled(blocked)
        .popover(isPresented: $pickerOpen, arrowEdge: .bottom) {
            DatePicker("", selection: Binding(get: { (day ?? today).date(in: .autoupdatingCurrent) },
                                              set: { picked in
                                                  day = ISODay.today(now: picked)
                                                  pickerOpen = false
                                              }),
                       in: ...Date(), displayedComponents: .date)
                .labelsHidden()
                .datePickerStyle(.graphical)
                .padding(CicadaTheme.spacingMD)
        }
    }

    private func submit(_ status: String) {
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !words.isEmpty, !saving, !blocked else { return }
        saving = true
        let chosen = day
        Task {
            let answer = await save(words, status, chosen?.description)
            saving = false
            // A failure keeps the words in the field; the toast said why (R-PP19).
            guard let answer, let claimId = answer.claimId else { return }
            text = ""
            day = nil
            logged = (ProjectLogWords.confirmation(projectName, answer: answer, sentDay: chosen != nil, today: today), claimId)
            try? await Task.sleep(for: .seconds(CicadaTiming.undoWindow))
            if logged?.claimId == claimId { logged = nil }
        }
    }
}
```

- [ ] **Step 7: Wire the writes into the detail column.** In `ProjectDetailColumn.swift`:
  - add `@FocusState private var logFocused: Bool`, `@State private var addRequest = 0`, `@State private var
    pendingScroll: String?`, `@State private var planEditing = false` (the Plan's Rename or Add field is open,
    R-PP23), `private var blocked: Bool { ProjectWriteGate.blocked(store.status.value) }`, and
    `private var typing: Bool { logFocused || planEditing }`;
  - add the one write path:

```swift
    /// R-PP19 — every write: a `ProjectWrite` through `Store.perform` (paint, send, roll back with a toast), then the
    /// cache asks again for what the server now holds (a 304 costs nothing).
    @discardableResult
    private func write(_ action: ProjectWrite.Action) async -> ProjectWriteResponse? {
        let w = ProjectWrite(projectId: projectId, action: action, cache: cache, day: today)
        let ok = await store.perform(w)
        if ok { cache.confirm(w.overlayId) }
        await cache.refreshTimeline(projectId)
        await cache.refreshList()
        return ok ? w.result : nil
    }

    /// M, the menu and "No plan yet — Add a milestone": open the Plan and its field, and bring it into view.
    private func requestAdd() {
        setOpen(.plan, true)
        addRequest &+= 1
        pendingScroll = "section.plan"
        scrollToken &+= 1
    }

    /// DR-68 (R-PP23) — D marks the selected thread or milestone done, dated today; never while typing, so a "d" in
    /// the Log or a milestone's name stays a letter.
    private func markSelectedDone() -> Bool {
        guard !blocked, !typing, let key = selection, let t = cache.display(projectId) else { return false }
        switch key {
        case .thread(let id):
            Task { await write(.settle(claimId: id, status: "done")) }
            return true
        case .milestone(let slug):
            guard let m = t.milestones.first(where: { $0.slug == slug }),
                  ProjectPlan.canMarkDone(ProjectPlan.Row(milestone: m, state: ProjectState.milestoneState(m, today: today)))
            else { return false }
            Task { await write(.changeMilestone(slug: slug, change: MilestoneChange(status: "done"))) }
            return true
        case .item:
            return false
        }
    }
```

  - the scroll handler reads the pending target first: `.onChange(of: scrollToken) { _, _ in let target =
    pendingScroll ?? selection?.id; pendingScroll = nil; guard let target else { return }; Instant.run {
    proxy.scrollTo(target, anchor: .center) } }`; and the Plan's `section(.plan, …)` wrapper gets `.id("section.plan")`;
  - at the top of the scroll's `VStack` (above Now — the mock's place), add:

```swift
                    ProjectLogField(projectName: t.project.name, today: today, blocked: blocked, focus: $logFocused,
                                    save: { text, status, when in await write(.log(text: text, status: status, when: when)) },
                                    undo: { claimId in _ = await write(.withdraw(claimId: claimId)) })
                        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
```

  - the sections gain their closures: `ProjectNowSection(…, settle: { id, status in Task { await write(.settle(claimId:
    id, status: status)) } }, writesBlocked: blocked)`; `ProjectLatelySection(…, withdraw: { id in Task { await
    write(.withdraw(claimId: id)) } }, writesBlocked: blocked)`; `ProjectPlanSection(…, markDone: { slug in Task { await
    write(.changeMilestone(slug: slug, change: MilestoneChange(status: "done"))) } }, rename: { slug, name in Task {
    await write(.changeMilestone(slug: slug, change: MilestoneChange(name: name))) } }, add: { name, target in Task {
    await write(.addMilestone(name: name, target: target)) } }, addRequest: addRequest, writesBlocked: blocked,
    onEditingChange: { planEditing = $0 })`;
  - `bandHeader`'s no-plan branch becomes the mock's "No plan yet — Add a milestone":

```swift
            } else {
                Text(Copy.Projects.noPlanAdd).foregroundStyle(CicadaTheme.textTertiary)
                TextButton(title: Copy.Projects.addMilestone, keyHint: "M", help: Copy.Projects.addMilestoneHelp) {
                    requestAdd()
                }
                .disabled(blocked)
            }
```

  - the header's `Menu` gains, above "Open its card": `Button(Copy.Projects.addMilestone) { requestAdd() }` and
    `Button(Copy.Projects.logLabel(name)) { logFocused = true }`, both
    `.disabled(blocked || cache.display(projectId) == nil)` — the header also draws while the project is still
    loading, when there is no Log field or Plan to act on (no dead control);
  - the keys, on the column (above `.focusable()`), answered only with a project on screen and never while typing.
    A letter typed into the Log or a Plan field can reach the column's `.onKeyPress` too (the Inbox guards the same
    way with `field == nil`), so every key returns `.ignored` while `typing` and the letter lands in the field:

```swift
        // R-PP23 / DR-68 — L · M · D, the Inbox's O / L precedent (key presses on the focused column, never menu key
        // equivalents), and like its `field == nil`, never while a field of this column is being typed in. A key
        // never animates (DR-60).
        .onKeyPress(KeyEquivalent("l")) {
            guard cache.display(projectId) != nil, !blocked, !typing else { return .ignored }
            logFocused = true
            return .handled
        }
        .onKeyPress(KeyEquivalent("m")) {
            guard cache.display(projectId) != nil, !blocked, !typing else { return .ignored }
            Instant.run { requestAdd() }
            return .handled
        }
        .onKeyPress(KeyEquivalent("d")) { markSelectedDone() ? .handled : .ignored }
```

  In `TitlebarHelp.swift`'s `ListHelp.projects`, insert after the `← →` row:

```swift
            .init(key: "L", does: "Log progress"),
            .init(key: "M", does: "Add a milestone"),
            .init(key: "D", does: "Mark the selected thread or milestone done"),
```

- [ ] **Step 8: Green.** `cd <worktree>/app/CicadaApp && swift test --filter 'ProjectWritesTests|TitlebarHelpTests|MutationTests|StoreTests|ProjectStoryTests|ProjectsCacheTests|CountLiteralLintTests|FontLiteralLintTests|RelativeDayTests' 2>&1 | tail -20`
  passes; then `swift build` and the full `swift test` (0 failures).

- [ ] **Step 9: Commit.**

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Sync/ProjectMutations.swift app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift \
  app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsCache.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectLogField.swift app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectDetailColumn.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Shell/TitlebarHelp.swift app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProjectWritesTests.swift app/CicadaApp/Tests/CicadaAppTests/TitlebarHelpTests.swift
cd <worktree> && git commit -m "feat(projects): Log progress dated by the server, the threads' answers, the Plan's milestones and Not right — Mutations with a plain-words 409 (G141 PJ-5, R-PP19…R-PP23, R-PP25; DR-40, DR-41, DR-49, DR-55, DR-59, DR-60, DR-68)"
```

---

### Task 6: Docs — the Projects page as it ships (the privacy rule; R-PP1, R-PP9, R-PP11, R-PP12, R-PP15, R-PP16, R-PP18, R-PP21, R-PP22)

CLAUDE.md gains the page's paragraph, DESIGN_RULES gains the token row, the sixth source label and its dated
departures, and the backlog and TODO say PJ-5 is built. No personal names, titles, URLs or quotes — demo fiction and
the owner's own design words only (the privacy rule).

**Files:**
- Modify: `CLAUDE.md`, `docs/design/DESIGN_RULES.md`, `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (the
  G141 row).

- [ ] **Step 1: CLAUDE.md.**
  - In **Navigation (Direction D, DS-1)** (`:645-646`), "Home, Graph, Clusters, Feed, Sleep, Inbox, Sources at ⌘1–7"
    becomes "Home, Graph, Clusters, Feed, Sleep, Inbox, Sources, Projects at ⌘1–8".
  - In **Provenance viewer (G118 slice 2)** (`:953-954`), "(the Inbox, Clusters, the Feed and Sources —
    `AppTab.hostsOwnReader`)" becomes "(the Inbox, Clusters, the Feed, Sources and Projects — `AppTab.hostsOwnReader`)".
  - After the **Clusters and the Feed (Direction D, DS-3c)** block and before **Sleep page — the study room**
    (`:817`), insert:

```markdown
**Projects (G141 PJ-5, Direction D).** The eighth page (⌘8, after Sources), the first designed for D: a list page in
progressive columns over `GET /projects` and `GET /projects/{id}/timeline`, which are **not** Store domains —
`ProjectsCache` (app-level, in memory) revalidates them with the server's ETag when the page appears, a project opens, a
write lands, or a sync event moves `entities`/`episodes`/`inbox`/`bank`, and a bank switch empties it (no
`VersionVector` mapping, nothing on disk). The wire decodes leniently into local `Project*` types (the shared `Claim` is
untouched); derived state is `ProjectState`, the Swift twin of `project_state.timeline_state`, running the same
`api/tests/fixtures/timeline_state.json`; every relative word comes from `RelativeDay` over `ISODay` in the viewer's
calendar (a lint keeps the day words there), and midnight re-derives the page with no network. Every Swift test reads
the demo scenario's real wire, `app/CicadaApp/Tests/fixtures/projects-demo.json`, pinned by
`api/tests/test_projects_app_fixture.py`.
- **The list:** text tabs Active · Quiet · All (resting projects only under All); sub-projects indented under a shown
  parent; each row's where-it-stands line, a mini `progressFill` bar, the next milestone or "No plan yet", people from
  the graph's `person` neighbours (never the owner), the compact age; "still indexing" while the server says `partial`.
- **The band** (`BandLayout`, pure, the approved mock's coordinates): `progressFill` from the first moment up to a
  "You, today" marker in `textPrimary`; done milestones filled inside the green, planned ones hollow on the track, a
  closed `due` slashed ("passed, no word on how it went"), a moved one's dashed ghost and bracket; happenings as neutral
  dots, ongoing threads as spans to today that dash once quiet; months and words near today. Every mark is a button: a
  `textPrimary` ring, its first words and date on hover, ←/→ along the band, ⏎ into the Reader. It is never called
  "Timeline" — that is the entity card's tab, which can share the screen.
- **The story:** Log progress (⏎ done, ⌘⏎ still going; the server dates it from the words, else the date chip, else
  today, and the page says which and how, with Undo = withdraw); Now (the threads; a quiet one whose follow-up waits in
  the Inbox links to that card); Lately (Today · Yesterday · This week · Earlier — one sentence per happening, every
  participant a chip that opens its card, the owner as the sentence's own word with a "you" tag; a status word; a
  source line with the origin's mark and "Show in conversation ›"; Resume where resumable; Not right); Plan (Add with
  an optional picked date, Mark done, Rename, "moved once ›"); Around this project (People · Tools & infrastructure, a
  tool unfolding its specs · Documents & links · Ideas · Parts of this project). The Reader or an entity card is the
  third column; Esc closes the Reader, then the card, then the project.
- **Writes** are `ProjectWrite` mutations through `Store.perform`: painted where the answer is known (a thread settled
  or restated, a milestone done, renamed or added, a withdrawal), rolled back with the server's own 409/422 sentence
  (a 400's or 404's detail is never shown — it names ids), disabled while Sleep runs; nothing relative is sent as a
  value. L · M · D are key presses on the focused project (the Inbox's O / L precedent), never menu key equivalents.
```

- [ ] **Step 2: DESIGN_RULES.**
  - §3.8's table (`:186`), after the `progressFill` row, add:
    `| \`progressOpenEnd\` (new) | white 22 % | black 22 % | an unplanned project's open end, on the band and the list row's mini bar — drawn only past Today, never a remainder |`
  - §5.2's table (`:301`): "List page (Inbox, Clusters, Feed, Sources)" becomes "List page (Inbox, Clusters, Feed,
    Sources, Projects)"; DR-25 (`:290`): "Inbox, Clusters, Feed and Sources open" becomes "Inbox, Clusters, Feed,
    Sources and Projects open".
  - DR-57 (`:539`): after its first bullet add
    `- **One source-line label joins them on the Projects page (G141 PJ-5):** "Set by you in Cicada", for an event the person wrote in the app with no sentence behind it. It is a source line, never a chip — it opens nothing.`
  - §9, after the last 2026-09-24 line (`:709`), add:

```markdown
- **2026-09-24: PJ-5 ships without the `cicada.design.focus` flag (R-PP1, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on a freshly generated demo bank.
- **2026-09-24: The open end of an unplanned bar is `progressOpenEnd` (R-PP9, §3.8).** §3.8 asks for "a dashed open end" and named no token; the approved mock's dash (white 22 % / black 22 %) joins the table.
- **2026-09-24: A band pick scrolls its row into view; the sections above do not fold (R-PP11, DR-30).** The mock folded them; a folded story hides the context a reader came for.
- **2026-09-24: The band's label is "Progress of …", never "Timeline" (R-PP12, G141 R-PJ22).** The entity card's Timeline tab (contested beliefs) can share the screen in the third column; a lint holds the page's strings to it.
- **2026-09-24: The owner reads as the sentence's own word with a small "you" tag, and opens nothing (R-PP15, DR-44).** A literal "You" would break the sentence; the tag sits on `bgBase` because `Tag`'s `bgSelected` would vanish on the chip's own fill.
- **2026-09-24: "Set by you in Cicada" is DR-57's sixth label, as a source line (R-PP16).** `EvidenceChip` keeps its five: an app-written event has no sentence to open.
- **2026-09-24: A quiet thread's follow-up links to its Inbox card; it is not answered inline (R-PP18, DR-42, DR-59).** The brief asks for the link; the Inbox owns answering and its Undo, and a question is stated once. The mock's inline options are not built.
- **2026-09-24: The Log's Undo withdraws what the server wrote; it is not DR-42's send delay (R-PP21).** The day comes back from the server (`when.py`) and is shown before Undo; the note keeps the person's words.
- **2026-09-24: A milestone's date comes from a native date picker, never typed words (R-PP22, G141 R-PJ6).** Python decides every date from words; a second date grammar in the app would drift. There is no Move yet; a moved milestone's chain still shows.
```

  - §9's closing paragraph (`:711`): "…and its Clusters, Feed and Sources paragraphs describe D as it ships" becomes
    "…its Clusters, Feed and Sources paragraphs, and (PJ-5) its Projects paragraph describe D as it ships".

- [ ] **Step 3: TODO.md.**
  - `:346-347`: "~~**Clusters**, **Feed**, **Sources**~~ (DS-3c) and **Projects** (G141 PJ-5)" becomes "~~**Clusters**,
    **Feed**, **Sources**~~ (DS-3c) and ~~**Projects**~~ (G141 PJ-5, built on `feat/g141-projects-page`)".
  - `:374-376` (the first phrase wraps across `:374-375`, "PJ-5 waits for" / "the DS shell;"): "PJ-5 waits for the
    DS shell;" becomes "PJ-5 built on `feat/g141-projects-page` (plan
    `2026-09-24-g141-projects-page.md`, R-PP1…R-PP27);", and "`GraphNode` dates ride PJ-5." becomes "`GraphNode` dates
    did not ride PJ-5: they are a backend change, reported with the track (the list shows a skeleton on its first open
    after a launch)."
  - `:689-690`: "**PJ-5** the Projects page (after the DS shell + a G108 ruling on the rail cell)" becomes "**PJ-5** the
    Projects page ✅ built (`feat/g141-projects-page`)".

- [ ] **Step 4: The G141 row** (`docs/goals/memory-evolution.md:705`, one line). Insert before the row's status cell
  (` | 🟡 PJ-1/2/3/6 built`):

```markdown
 **Built PJ-5 (2026-09-24, `feat/g141-projects-page`, plan `docs/superpowers/plans/2026-09-24-g141-projects-page.md`, R-PP1…R-PP27).** Projects is the eighth page (⌘8). The list, at D density, shows Active · Quiet · All, a mini green bar per project, the next milestone or "No plan yet", people from the graph and the compact age. A project opens with the band — a green bar that fills up to "You, today", every mark a button (ring, hover words, ←/→, ⏎ into the Reader) — then Log progress (dated by the server from the words, with Undo), Now, Lately (one sentence per happening, every participant a chip), Plan and Around this project; the Reader or a card is the third column. Writes are `Mutation`s with the server's own 409 sentence. `/projects` stays out of the Store (an in-memory, ETag-revalidated cache). `ProjectState` runs `timeline_state.json` beside the Python, and the app's fixture is the demo's real wire, pinned by a pytest. **Reported, not built:** `GraphNode` dates (a backend change), people on `ProjectRow`, a hash on `TimelineQuote`, Home's "In motion", the Graph card's "Open project ›", event rows elsewhere ("day · status · sentence"), Move, and the PJ-8 menu item.
```

  and the status cell's text becomes `🟡 PJ-1/2/3/6 built (feat/g141-read-write); PJ-0b built (feat/g141-hold-page-less);
  PJ-5 built (feat/g141-projects-page); GraphNode dates reported (backend)`.

- [ ] **Step 5: Privacy check.** `cd <worktree> && git diff -- CLAUDE.md docs/ | rg -n -i "/users/|/private/|http"` must
  print nothing but `example.com`, and a read of the added lines finds no person's name, employer, title or quote
  beyond the owner's own design words (the privacy rule).

- [ ] **Step 6: Commit.**

```
cd <worktree> && git add CLAUDE.md docs/design/DESIGN_RULES.md docs/goals/TODO.md docs/goals/memory-evolution.md
cd <worktree> && git commit -m "docs(projects): the Projects page as it ships — CLAUDE.md, DESIGN_RULES §3.8/§5.2/DR-25/DR-57/§9, TODO and G141 (G141 PJ-5, R-PP1, R-PP9, R-PP11, R-PP12, R-PP15, R-PP16, R-PP18, R-PP21, R-PP22)"
```

---

## Not in scope

- **Any backend change** (the brief). No file under `api/` changes except the one new test in Task 1.
  - `GraphNode`'s `created`/`lastReferenced` and the `NODE_SHAPE` bump that would let the list paint cold from `/graph`
    (spec §10.1) are therefore not built (R-PP3).
  - People on `ProjectRow` and a hash on `TimelineQuote` are not added (R-PP7, R-PP16).
- **Sleep extraction (PJ-7)** and the **consented re-read (PJ-8)**, so there is no "Read this project's past
  conversations" menu item.
- **Event rows elsewhere** — the palette, the entity card and the citation list rendering an event as "day · status ·
  sentence" (spec §10.2). The shared `Claim` is untouched (R-PP2).
- **Home's "In motion"** section and **"Open project ›" on the Graph's entity card** (DS-3a's file). Inside the
  Projects page, a project's card already offers it (R-PP17, R-PP24).
- **The spec's "All projects" band** in STATE 0 (§11.2). The approved mock replaced it with each row's mini bar.
- **The spec's Conversations list and "Where this came from"** under a project (§11.3 items 8–9). Every row carries
  its source line and the Reader (R-PP13).
- **Moving a milestone's target**, a date picker on the Inbox's follow-up, and **editing a happening's words**
  (withdraw and log again; spec §16).
- **Answering a follow-up inline** on the Projects page (R-PP18).
- **Changing the Inbox, the Reader's internals, `EntityDetailCard` or the Graph page.** The one exception is
  `ReaderColumn.act`, which moves onto `ResumeOutcome.toast` (R-PP26).

## Reported to the orchestrator

1. **`GraphNode` carries no dates** (`api/routers/graph.py:32`, `NODE_SHAPE = "aliases+f1-facets"`). Spec §10.1 bumps
   it in PJ-5 so the list paints cold from `/graph`, but that is a backend change. The list shows its skeleton on the
   first open after a launch (R-PP3).
2. **`ProjectRow` has no people.** The list derives them from the Store's `/graph` edges — `person` neighbours of the
   project node, the owner and facets left out (R-PP7). A server field would make them match the detail's Around
   exactly. On the freshly generated demo bank `/graph` has no edges at all (`demo_bank` writes no
   `graph_edges.yaml`), so the live check sees an empty people slot on every row.
3. **`TimelineQuote` has no hash.** A moment's Reader span opens without a freshness check, so it cannot say "grown"
   or "stale" the way a happening's claim span can (R-PP16).
4. **The server's 422 words name "the date chip".** The page ships the chip so those words stay true (R-PP21). A
   future track that drops the chip must change `routers/projects.py:127-128` in the same PR.
5. **Spec items outside the brief**, deferred and listed under Not in scope: event rows elsewhere, Home "In motion",
   the Graph card's "Open project ›", Conversations and "Where this came from" under a project, and Move.

## Verification the orchestrator runs at the end

1. **The suites.**
   - `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` builds.
   - `swift test 2>&1 | tail -20` reports **0 failures**, with ≥ 1623 plus this track's tests executed. Re-run a
     `SleepViewModelTests` poll or search-latency failure alone before calling it.
   - `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` is green.
   - `cd <worktree> && <repo>/api/.venv/bin/python -m pytest api/tests/test_projects_app_fixture.py api/tests/test_project_state.py -q -p no:cacheprovider`
     passes: the fixture is still the demo's wire, and both languages still agree on `timeline_state.json`.
2. **The lints** (inside `swift test`): `RelativeDayTests`' day-word lint, `ProjectBandTests`' "Timeline" lint,
   `CountLiteralLintTests`, `SelectionTintLintTests`, `FontLiteralLintTests`, `SectionLabelLintTests`,
   `ElevationLintTests`, `HiddenShortcutLintTests`, `AccentSourceLintTests`, `MeadowPlacementLintTests`. No allowlist
   entry is added.
3. **The privacy grep:**
   `cd <worktree> && git diff dev -- . ':!app/CicadaApp/Tests/fixtures' ':!api/tests/test_projects_app_fixture.py' | rg -n -i "/users/|/private/"`
   prints nothing new, and the added docs name no real person or project (the privacy rule). The two excluded files
   are checked by the fixture's own pytest (`test_the_fixture_is_synthetic`, whose assertion spells the very
   `"/Users/"` needle this grep looks for).
4. **The live check**, installed build against a freshly generated demo bank (never the on-disk `memory/banks/demo`;
   spec §2), at 1440 × 900 and 1200 × 800, in both themes, at 1.0× and 1.4×, with the rail and the labelled sidebar.
   Screenshots go in the PR body (DR-71, DR-73).
   - **The rail and the palette.** ⌘8 and the rail's eighth cell (tooltip "Projects ⌘8") open the page; ⌘K "Go to
     Projects" works; a ⌘K project row lands in STATE 1.
   - **STATE 0.** The eyebrow reads "Projects · 6 active". Active · Quiet · All read 6 · 0 · 15. Pick And Place Demo
     sits indented under Rover Arm Project. Each row shows its now line, a mini green bar (the garden's with a dashed
     open end), "Next · First grasp, Oct 1" (dates relative to the day of the check) and the age. The people slot is
     empty on this bank (its `/graph` has no edges, reported), and "1 question" sits on the rover's row.
   - **STATE 1, the rover.**
     - The band fills to "You, today". Arm assembled is a filled diamond inside the green; First grasp is hollow with
       a dashed ghost and a bracket; the camera thread dashes; the connecting thread's open cap sits at today.
     - Every mark rings on click, shows its words on hover, and ←/→ walk them. ⏎ opens the Reader with the cited words
       washed and underlined.
     - Lately: Yesterday's happening reads as one sentence with chips. "Bob" carries a "you" tag. The guide chip has
       ↗. Hana Example and Lab Cluster Example open their cards in the third column.
     - Around this project: Lab Cluster Example unfolds its three specs.
   - **Unplanned.** The garden's band has an open end and "No plan yet — Add a milestone".
   - **Writes:**
     - Log "Yesterday I got the lab cluster guide" → "Logged on … for <yesterday> (yesterday) — dated from your words",
       and Undo takes it back.
     - Done on a thread hides it at once.
     - Add a milestone with a picked date; Mark done; Rename.
     - Start a Consolidate and every write control is disabled with its reason; a forced race answers with the 409
       sentence in a toast.
   - **Follow-ups and keys.** The camera thread shows "How did it go? ›", which opens its Inbox card. Esc closes the
     Reader, then the card, then the project. With the project holding the keys (⏎ from the list, or a click on a band
     mark): L focuses the Log, M opens Add a milestone, D marks the selected thread done — and typing "l", "m" or "d"
     into the Log or a milestone's name types the letter and triggers nothing.
   - **Midnight.** Leaving the page open across midnight re-words every relative date with no network call (or change
     the Mac's date and wait for `.NSCalendarDayChanged`).
5. **The PR body** cites G141 PJ-5, every DR id in the commits, the §9 lines added, R-PP1…R-PP27, and the "Reported"
   list above.
