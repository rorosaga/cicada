# Provenance viewer, the app (Track P-UI, G118 slice 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slice 1 made every new claim point at the words it came from and slice 2's server half
(PR #72) made those words readable; nothing in the app shows them. The owner asked for exactly this
("I want full provenance and traceability of memory"; 2026-09-23: "show snippets in contribution of
provenance in more detail to see where in conversation the memory comes from" and "easier and more
friendly design to show who contributed to what memory"). This track ships the app half: every
claim carries **evidence chips** that preview the exact words on hover and open the **Reader** — the
whole conversation beside whatever is on screen, scrolled to the washed sentence, honest about
stale, grown and derived quotes — and every entity card gains **"Where this came from"**: who wrote
its beliefs (with their real marks), the conversations that fed it with the best sentence of each,
and how many beliefs carry an exact quote. The inbox cause and Ask answers open the same Reader.

**Architecture:** Every decision is a pure, table-tested function (`ScalarText`, `ReaderLayout`,
`ReaderPresentation`, `ReaderNavigator`, `EvidenceChipModel`, `EvidenceLabel`,
`ProvenanceSummary`, `InboxCause.readerTarget`) and the views render them. One
`ProvenanceRouter` (a stack of `ReaderTarget`s) drives one `.inspector` on the main window; one
`ProvenanceCache` holds the four read payloads **in memory only** — none is a Store domain, so
there is no `VersionVector` mapping and no `SnapshotCache` entry (R-PB11, design K10). Chips read
the router and cache as optional environment values. No server change, no MCP change.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, Swift 5.10 tools, macOS 14 floor), the merged
FastAPI read routes of PR #72.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-design-settings-search-provenance.md` §1.1
(timing constants), §1.3 (components), §1.4 (navigation plumbing), **§4** (all of it — §4.1 model,
§4.2 chip, §4.3 interactions, §4.4 Reader, §4.5 "Where this came from", §4.6 footer + History,
§4.7 inbox/Ask, §4.9 honesty rules, §4.10 tests) and §6 slices P1–P5 (client parts; P6 is a
documented seam); `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`
decision **19** and R-M2…R-M5; the server contract is
`docs/superpowers/plans/2026-09-23-provenance-backend.md` (rulings **R-PB1…R-PB16** — every field
name below was verified against `api/models/schemas.py` and `api/services/provenance.py` on this
base). Backlog: **G118** (edited in Task 7), cross-referenced **G103**, **G106**, **G115**.
Standing rulings: provenance outranks polish (owner, 2026-09-02); spans, not copies; transcripts
under `~/.claude` are never read; no prices or token counts in the app (2026-09-03); ETag
ship-together; privacy in docs; portability.

---

## What the code actually does today (verified on `feat/provenance-ui` = `dev` @ `040f0fe`)

App paths are relative to `app/CicadaApp/Sources/CicadaApp/` unless they start with `api/` or
`app/`.

**The server contract (PR #72, read, not changed).**
- `api/routers/episodes.py:44-75` — `GET /episodes/{id}/span?start&end[&context][&hash]` →
  `EpisodeSpan` (`schemas.py:702-725`: `episode, text, before, after, start, end, length, stale,
  grown, kind`). `start` is required and `end ≥ 1`; 404 for an unknown id; **no ETag** (slice-1 R9).
- `episodes.py:78-111` — `GET /episodes/{id}/text?[start&end[&hash]] | [focus=<entity>]` →
  `EpisodeText` (`schemas.py:761-784`: `episode, kind ("episode"|"page"), text (≤ 400,000 chars),
  length, hash, truncated, title, timestamp, harness, origin, conversationId, captureKind, turns[],
  focus`); `EpisodeTurn` (`:728-742`: `index, start, contentStart, end, role, marker, speaker, ts`);
  `EpisodeFocus` (`:745-758`: `start?, end?, kind, derived, stale, grown` — a stale focus has **no
  offsets**, R-PB2). ETag over `episodes`+`entities` + the request. A half or out-of-range pair is a
  422; an unknown focus entity is `focus: null`, not a 404 (R-PB5).
- `episodes.py:114-133` — `GET /episodes/{id}/citations` → `EpisodeCitations` (`schemas.py:875-914`:
  `episode, citations[{claimId, subjectId, subjectName, subjectType, text, current, authoredBy,
  observer, evidence?, kind, start?, end?, stale, grown, derived}], entities[{entityId, name, type}],
  partial`). Spans first in document order. `partial` means "capped at 200 pages" (R-PB10).
- `api/routers/claims.py:105-145` — `GET /entities/{id}/provenance` → `EntityProvenance`
  (`schemas.py:787-872`: `entityId, entityName, entityType, contributors[{author, kind, provider,
  claims, commits}], conversations[{conversationId?, episodeId, episodeIds, title, harness, origin,
  timestamp, claimCount, available, best?}], pages[{entityId, name, claimCount}], inferredCount,
  totals{claims, withSpan, legacy, conversations}, commitsTruncated}`; `best` is a `ProvenanceSpan`
  (`episode, start?, end?, hash, kind, excerpt, excerptStart, mentionOffsets, stale, grown,
  derived`) — `excerptStart` absolute, `mentionOffsets` relative to the excerpt. ETag adds `git_head`.
  At most 50 conversation rows; `totals.conversations` is the honest total (R-PB7). A derived `best`
  carries the WHOLE text's hash (`provenance.py:240-241`) — never a span hash.
- `schemas.py:642-681` — `ClaimModel` carries `evidence[]`, `sessionIds`, `recordedAt`, `origin`,
  `authorKind` (`user|system|model|harness|unknown`), `authorProvider`; `:159-189`
  `EntityHistoryEntry` carries `authorKind`, `authorProvider`; `:1027-1037` `AskCitation` carries
  `claimId?` + `evidence[]`; `:1170-1197` `InboxCause` unchanged — `start`/`end` are the **excerpt
  window's** absolute offsets and `mentionOffsets` are relative (R-PB16, `inbox_context.py:94-135`).
- `api/routers/conversations.py:771-793` — the importer's `turns` sidecar stores the **role** as
  `speaker` (`"user"`/`"assistant"`), so a sidecar `speaker` is not a person's name. Only a meeting
  (Track N, not on this base) will ever carry one.
- `schemas.py:280-283` — `EntityReadRequest.surface` is `Literal["app", "mcp"]`: a Reader `read`
  event with `surface: "span"` (design §4.4) would 422 (→ R-PU12).
- `schemas.py:355-385` — `ConversationSummary` carries **no episode id** (→ R-PU5).

**The Swift seams this track changes.**
- `Models/Claim.swift:98-147` — `Claim` decodes 18 fields; `CodingKeys` (`:120-124`) never names
  `evidence`, so slice 1's spans have been dropped on the floor since PR #44. `:81-89`
  `SourceTrust.label` returns `"user stated"` / `"agent extracted"` / … (read only by `TrustPill`).
- `Models/Entity.swift:181-250` — `EntityHistoryEntry` has `author` but no kind/provider.
- `Models/Ask.swift:12-40` — `AskCitation` has no `claimId`/`evidence`.
- `Models/InboxItem.swift:125-161` — `InboxCause` decodes everything the Reader needs; its doc comment
  calls `start`/`end` "the absolute offsets into the episode body", which R-PB16 corrects (they are the
  excerpt window's). `Models/InboxPresentation.swift:47-60` `ExcerptText.attributed` already slices by
  Unicode scalar — the rule this track generalises.
- `Views/Common/ClaimChip.swift:13-54` — the footer: `ObserverBadge`, `ContextPill`, `TrustPill`,
  `ConfidenceRing`, `AuthorPill` (`:175-194`, the raw model id as text) and `EpisodePill`
  (`:196-212`, "inert for now": the FIRST source episode id in monospace, A9). `ClaimChip` is used at
  `Views/Graph/EntityDetailCard.swift:1244` (Perspectives), `Views/Graph/BeliefTimelineView.swift:205`,
  `Views/Common/TranscludingMarkdownView.swift:247`.
- `Views/Contributors/ContributorsView.swift:283-375` — `ContributorAvatar(contributor:kind:)`, fixed
  22 pt (`private static let size`), `user | system | unknown | model` branches; no `harness`.
  `Views/Contributors/ContributorIdentity.swift:34-55` — `displayName(author:kind:)` (pinned by
  `ContributorIdentityTests.swift:9-19` and `ContributorStripTests.swift:80-86`) and `kind(of:)`.
- `Views/Graph/EntityDetailCard.swift` — body `:141-170` (`.wikilinkNavigation` `:165`, the Belief
  Timeline `.sheet(item:)` `:166`); Content tab `:306-400` ending in `sourcesSection` (`:359`) and
  `metadataSection` (`:362`); G61's section header `Text("Sources")` `:682`; History row
  `FromConversationButton(sessionIds:)` `:1137` and the author capsule `:1152-1164`; the card's own
  back is `⌘[` at `:194`.
- `Views/Sources/ConversationPopover.swift:13-78` — "Written by" popover with Resume/Copy only;
  `:6-12` records the "shown in place" deviation (A10). `FromConversationButton` `:80-107`.
- `Views/Inbox/InboxCardView.swift:82-85` — the cause line (text only); `:175-184` `excerptPane`
  (12 pt, no way into the conversation).
- `Ask/AskPanel.swift:115-131` — SOURCES chips (entity only), `:153-171` `citationChip`. The panel
  is a `.sheet` from `ContentView.swift:124`.
- `ContentView.swift:44-52` — the `NavigationSplitView` detail column (where the inspector goes);
  `:32` `@Environment(AppRouter.self)`. `CicadaApp.swift:36, 93-106` — main-window environment
  objects. `Support/AppRouter.swift:14-16` — `pendingTab`, consumed by `ContentView.swift:110-114`.
- `Services/APIClient.swift:2141-2166` — `getConditional(_:etag:)` (internal, `If-None-Match`,
  304 → `notModified`); `get` (`:2035`) and `encodedID` (`:1188`) are **private**, so the new routes
  live in an extension over `getConditional`. `Tests/CicadaAppTests/EntitySourceTests.swift:10-38` —
  `MockURLProtocol` + `APIClient(session:)`.
- `Theme/CicadaTheme.swift:315-324` — `displayFont(size:italic:)` (≥ 22 pt, lint-enforced
  `FontLiteralLintTests.swift:62-76`) and `quoteFont(size:)` (New York italic); `:155`
  `dandelionFill`. `Theme/CicadaMotion.swift:29-66` — the motion vocabulary (`MotionLiteralLintTests`
  bans `duration:` outside it and `SleepMotion`); `hoverLift()` / `iconHover()` `:68-179`.
- Keyboard: `⌘[` is already bound by `EntityDetailCard.swift:194` and `SourceDetailView.swift:61`.

**Baseline on this base:** Swift **1061 executed, 0 failures** (measured 2026-09-23 on a scratch copy
of `040f0fe`; the brief's 1012 predates Meadow M1's tests — re-measure, never trust a remembered
count). Graph JS **7 pass, 0 fail**. Backend untouched by this track.

**This plan was validated before hand-off.** Every code block below was applied verbatim, task by
task, to a scratch copy of this base (outside the repo) and run: after each task the package built
and the full Swift suite passed — 1083, 1112, 1124, 1137, 1143, 1148 executed, 0 failures (re-run in
full after the plan critic's fixes, R-PU25…R-PU28) — and each
task's new tests failed to compile before its implementation existed.

---

## Global Constraints

- `<worktree>` below means the track worktree the orchestrator assigned (branch `feat/provenance-ui`,
  based on `dev` @ `040f0fe`). Work ONLY there. Every shell command is `cd <worktree> && <cmd>` with
  the ABSOLUTE path (zoxide hijacks a relative `cd`; ignore its stderr warning). No unquoted
  `--include=*.ext`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library`, `~/.claude/projects`. Fixtures are
  synthetic: `alpha-project`, `bob-example`, `example.com`, `ses_alpha`, `ep_2026-09-03_004`.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures** (1061 executed on this base, plus each
  task's tests). Graph JS: `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` (pass the
  glob). SourceKit diagnostics naming OTHER worktrees are noise. NEVER run `make dev`,
  `make install-app`, `swift run`, or launch/kill the Cicada app or the launchd backend — the owner's
  installed app is live; the orchestrator installs and live-checks at the end.
- **Applying the code.** A ```swift block under "Create" is a whole new file, written verbatim. A
  ```diff block under "Modify" is exact against this base plus the earlier tasks; apply it from
  `<worktree>` with `git apply --check <file> && git apply <file>` after writing the block to a file in
  your scratchpad (or make the identical edits by hand). If a hunk does not apply, STOP and read the
  cited code — never force it.
- Never `git add -A`; stage the named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv`, `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin/PR
  comments. **This plan file is committed with Task 1.**
- **Do not touch:** anything under `api/` or `mcp/` (server gaps are recorded as hand-offs, never
  patched here); `Theme/Copy.swift` (four round-3 tracks edit it — this track's copy lives in
  `Theme/Copy+Provenance.swift`, R-PU17); `Views/Capture/OriginIconography.swift`,
  `Views/Common/OriginMark.swift`, `Views/Common/LogoImage.swift` (consume only); `Sync/` (no Store
  domain, R-PU3).
- **Fonts / motion / colour / glass:** every size through `CicadaTheme.font(size:…)`,
  `quoteFont(size:)` or `displayFont(size: ≥ 22)`; spacing through the `spacingXS…XXL` tokens and
  every frame that sizes content (marks, placeholders, widths) through `CicadaTheme.scaled(_:)` — pill
  paddings and 1–3 pt rules stay the literals the neighbouring pills in `ClaimChip.swift` already use,
  exactly as the code blocks below spell them; no `duration:` outside `Theme/CicadaMotion.swift`; no hex outside the theme; **no glass in
  `Views/Provenance/`** — the Reader, chips and quotes are content (R-M5, K12). The lints
  (`FontLiteralLintTests`, `MotionLiteralLintTests`, `ThemeTokenTests`, `LiquidGlassLintTests`) run
  in the suite.
- **No prices, no token counts** anywhere (2026-09-03 ruling). Counts go through `UsageFormat.count`.
- **Decode tolerance:** every new wire field is optional-with-default and asserted against a payload
  that omits it (R10).
- **Privacy (standing, 2026-09-02):** no owner name, no author-machine path, no bank contents in code,
  docs, commits or the PR body.
- Docstrings explain **why**, citing the G-row, ruling or design section — the density of
  `Models/InboxPresentation.swift` and `api/services/provenance.py`.
- Commit messages end with the session's attribution trailer.
- Line numbers above are from `040f0fe` and drift as tasks land — read the cited code before editing.

---

## Rulings (binding)

The design's §4.9 honesty rules and the backend plan's R-PB1…R-PB16 hold as written. Everything
below is a decision this plan takes where the brief or the design left a choice (or where the design
did not survive contact with the code), with the reason, so no task re-opens it.

- **R-PU1 — One scalar rule: `ScalarText`.** Every evidence offset is a Python `str` index (a code
  point). All slicing goes through `Utilities/ScalarText.swift`, which holds `Array(unicodeScalars)`
  once: `unicodeScalars.index(_:offsetBy:)` is O(n) per call and the Reader slices every turn of a
  document of up to 400,000 characters. Fixtures in `ScalarTextTests` were generated once from the
  backend's own `text[start:end]` (emoji, combining accent, CJK, flag, ZWJ family). Out-of-range
  offsets clamp; nothing traps.
- **R-PU2 — Decode tolerance everywhere.** `EvidenceKind` is forward-compatible (`unknown` renders
  like `reasoning`), an `Evidence` with no `kind` is `reasoning` (the server's own default), and
  every new field on `Claim`, `EntityHistoryEntry`, `AskCitation` and the new payloads decodes with
  `decodeIfPresent … ?? default`. A payload missing everything optional still decodes (tests pin it).
- **R-PU3 — In memory only.** `ProvenanceCache` (one for the app — `CicadaApp` owns it as `@State`
  beside `appRouter` and injects it into the main window scene) holds the four payloads in LRU
  maps — spans 256 (design §4.2), documents 12, provenance 64, citations 24. ETagged payloads are
  revalidated on every ask (a 304 is cheap and keeps "Where this came from" true after a Sleep
  cycle); a **404 is `gone` even when something is cached** (the bank no longer has it); a **422 is
  stale** (R-PU25); any other failure serves last-known-good; a bank switch empties it (R-PU26). No
  Store domain → no `VersionVector` mapping (K10); if one ever joins `SnapshotCache`, the mapping
  ships in the same commit.
- **R-PU4 — Optional environment for chips.** `ProvenanceRouter` and `ProvenanceCache` are injected
  into the MAIN window only (`CicadaApp.swift`; Settings never opens a Reader). Every chip, quote and
  entry point reads them as `@Environment(T.self) var x: T?`, so a chip hosted anywhere else renders
  and previews without a click-through rather than trapping on a missing environment object.
- **R-PU5 — No `.conversation(id)` target.** The Reader reads `/episodes/{id}/text`, and
  `ConversationSummary` carries no episode id (`schemas.py:355-385`). So `ReaderTarget` is always an
  episode (or page) id, and the History tab's "from conversation" popover offers **Open
  conversation** only for ids the entity's `/provenance` payload maps to an episode
  (`ProvenanceSummary.episodeByConversation`). The Contributors drill-down's popover keeps Resume/Copy
  only. Hand-off H1.
- **R-PU6 — A chip says only what the surface already knows.** `/span` carries no title or harness,
  and fetching `/text` per chip to name the agent would be N whole documents per card. The entity
  card injects an `EvidenceDocIndex` built from its one `/provenance` payload, so chips there say
  "Claude Code replied"; a chip anywhere else says "The agent replied" — honest, never guessed. For
  the same reason the chip carries **no stale badge** (that would be a `/span` per chip per render):
  staleness is said in the preview and in the Reader. The design's preview line "turn 14 of 42" is
  dropped (`/span` has no turns); the Reader shows turns.
- **R-PU7 — Legacy claims get derived chips.** A claim with no `evidence` renders one `derived` chip
  per `ep_*` id in `source_episodes`, capped at 3, and asks the server to find the subject's name
  (`?focus=<subject>`, `inbox_context.locate_mention` — the one derivation rule, R-PB9). Its preview
  fetches `/text?focus=` through the SAME cache entry the Reader will use, so hover-then-click costs
  one request. Most live claims are legacy (the orchestrator's probe), so this is the common case.
- **R-PU8 — Honest labels, in the owner's words.** An asserted quote is captioned **"Quoted by the
  contributor"**; a derived one **"Found by searching the conversation"** (the brief's wording, over
  the design's "Found by name"). A derived chip is labelled "Mentioned here", outlined dashed, and its
  words are **bold, never washed**; a stale quote is plain. A target's own `derived` flag wins over
  the server's asserted focus — an inbox cause found by name is re-asked by offsets (R-PB16) and must
  stay labelled found by name.
- **R-PU9 — Keys.** The Reader's back is **⌥⌘[** (the design's ⌘[ is already the entity card's own
  back, `EntityDetailCard.swift:194`, and the card stays open beside the Reader); the navigator is
  ⌥↑ / ⌥↓, on a bar **pinned above the scrolling text** — landing scrolls the cited turn to the
  centre, so a bar inside the scrolled stack would leave the screen the moment the Reader arrived;
  Esc closes (`onExitCommand`). Space on a focused chip toggles the preview; the
  accessibility action "Preview quote" is its guaranteed twin (a focused button needs Full Keyboard
  Access on macOS).
- **R-PU10 — "+N more" expands in place.** More than 3 chips on one claim fold behind "+N more",
  which expands the run where it is. The design's "opens the entity's Where this came from" is not
  possible from `ClaimChip`'s generic hosts (transclusion, timeline sheet, Ask), which cannot switch
  the card's tab.
- **R-PU11 — The Reader is an `.inspector` on the detail column** (`ContentView.swift:44-52`), width
  `scaled(360…440…560)`, beside whatever is open; content, never glass. Its title is the track's one
  display-face moment — `displayFont(size: 22)` (R-M3); the body is `bodyFont`, selectable. The cited
  span gets `dandelionFill` at 35% plus a 2 pt `dandelion` margin bar; other spans the subject cites
  get 15% and no bar. The wash fades in over `CicadaMotion.spanReveal` (0.25 s; nil under Reduce
  Motion → static). Landing announces "Cited passage: …" to VoiceOver.
- **R-PU12 — No `read` telemetry from the Reader.** `EntityReadRequest.surface` is
  `Literal["app","mcp"]` (`schemas.py:283`); sending `span` would 422, and the card that opened the
  Reader already recorded its read. Hand-off H2.
- **R-PU13 — "Where this came from" is one call per card, loaded at the card level.** The same
  `/provenance` payload names the agent on every chip in Perspectives/Timeline (R-PU6) and maps a
  history row's conversation to an episode (R-PU5), so it loads in a card-level
  `.task(id: entity.id)`, not the Content tab's. The section sits at the bottom of the Content tab,
  always present; a 404 (an older backend) hides it, any other failure says "Couldn't load where this
  came from." Its header matches the neighbouring section's (`captionFont`, `textTertiary`). Its
  sentence names places in words ("2 in Claude Code"); every conversation row beneath carries that
  place's real mark (`OriginMark`) and every contributor chip its real face, so a service is never
  named far from its mark.
- **R-PU14 — Contributors: two nouns, vendor first.** A chip reads "12 beliefs · 3 edits" (claims
  with that `authored_by`; commits that touched the page) — never one number meaning two things (the
  Sources v2 rule). A model is named "Claude (claude-sonnet-4-5)" through a new
  `ContributorIdentity.vendorName(provider:)`; `displayName` only gains a `harness` branch (a remote
  write's app label → its product name), so the strip's pinned names are unchanged. The writers
  sentence leaves `unknown` ("Before provenance") to its chip. No share bar (the Sources strip owns
  the one volume chart, §4.5).
- **R-PU15 — Plain trust labels.** `SourceTrust.label` becomes "You told Cicada" / "Cicada noticed" /
  "Cicada concluded" / "From a source" / "Not recorded". `TrustPill` (`ClaimChip.swift:113-138`) is
  its only reader; the axis and its colours are unchanged, still orthogonal to confidence.
- **R-PU16 — Speakers and times.** A time is shown only when the episode stores one (`turns[].ts`):
  an aware ISO stamp → a short local time, a naive one read in the viewer's zone (G114), a meeting
  offset passes through; nothing is inferred. A sidecar `speaker` that is a role word is not a name.
  A meeting speaker is never "You" (R-N2) — "Someone else" / "Someone else said" until a name is
  stored. Chips follow the server's `kind` (R4: `system`/`unknown` markers are the person's side); the
  Reader is more precise about those two lines ("Setup message", "Unlabelled message").
- **R-PU17 — Copy lives in `Theme/Copy+Provenance.swift`** as `extension Copy { enum Provenance }`,
  and each later task appends an `extension Copy.Provenance` block — four round-3 tracks edit
  `Copy.swift` in parallel, and an extension in its own file merges with none of them.
- **R-PU18 — Delays are not motion.** `CicadaTiming.hoverPreviewDelay` (0.35 s) and
  `hoverPreviewGrace` (0.2 s) live in their own file (`Theme/CicadaTiming.swift`): Reduce Motion
  leaves a delay alone, which is exactly what `CicadaMotion`'s members do not do. `spanReveal` is
  motion and joins `CicadaMotion` (the lint's exempt file). Design §1.1 asks the literal rule to cover
  the new timing names too: `EvidenceChipLabelTests.testProvenanceViewsSpellNoLiteralDelay` fails on a
  literal `.seconds(<number>)` anywhere under `Views/Provenance/` (scoped, because the app's toast
  timer at `ContentView.swift:179` predates this track and is not its to move).
- **R-PU19 — Seams, not builds.** Find-in-conversation needs Track S's `CicadaSearchField` (S5); P6
  (palette rows → the Reader) needs Track S's palette (S4). The seam for both is
  `ProvenanceRouter.open(_:)` plus the `ReaderTarget` factories (`evidence`, `best`, `.mention`,
  `InboxCause.readerTarget`). No `AppRouter.pendingReader` is added: nothing in the Settings window
  opens a Reader.
- **R-PU20 — Sheets step aside.** Opening the Reader bumps `ProvenanceRouter.revision`; the Ask sheet
  (`ContentView`) and the Belief Timeline sheet (`EntityDetailCard`) close on it, so the sentence is
  never under a modal.
- **R-PU21 — "Noted from this conversation" rows jump in place.** A row with offsets re-focuses the
  Reader on its words (no router push — the trail is for moving between documents); a trailing
  **Show on the graph** button lands on the subject through `AppRouter.pendingTab = .graph` +
  `graphVM.revealEntity(id:)` (G123), replacing the design's option-click, which is neither
  discoverable nor reachable by keyboard. Superseded claims stay listed, struck through and labelled
  "No longer current".
- **R-PU22 — `media` evidence** (R5 D4, a sibling track's kind) renders "In the video" and opens the
  Reader like a page; seeking the embedded player (`VideoRef.embedURL(at:)`) is hand-off H5.
- **R-PU23 — A superseded fetch never lands.** `.task(id:)` cancels, but cancellation is cooperative:
  the Reader re-checks `router.current == target` after every await, and the card re-checks
  `Task.isCancelled` before writing its provenance state.
- **R-PU24 — The inbox cause's target.** `start + mentionOffsets[0] … start + mentionOffsets[1]`
  with **no hash** (the cause is recomputed at read, so it is current by construction, R-PB16);
  `derived` unless `spanKind == "asserted"`; a cause with no mention opens its conversation at the top;
  tier `none` offers no button. The Swift `InboxCause` doc comment is corrected to match.
- **R-PU25 — A span the document no longer reaches is stale, not a failure.** `/span` and `/text`
  answer **422** for a pair past the end (`episodes.py:57-58` and `:107-108`,
  `provenance.SpanOutOfRange` at `provenance.py:122-123`) — which is exactly what a stored span
  becomes once a page description or a re-synced file is rewritten shorter. `/citations` already reads `end > len(text)` as stale
  (`provenance.py:440`). The cache does the same: a 422 on `/span` is served as a stale span with no
  words (the preview says "the words may have moved"), and a 422 on `/text?start&end` re-asks with no
  focus and returns the whole document with a stale focus (the Reader opens it under the stale banner,
  landing as near the old offset as the text reaches). Never "Couldn't open this conversation" for a
  conversation that is there.
- **R-PU26 — A bank switch closes the Reader and empties the cache.** Nothing in `ProvenanceCache` is
  keyed by bank, and episode ids restart at `_001` every day in every bank (G114), so without this a
  document, span or last-known-good copy from one bank could be shown under another — the split-brain
  class. `ContentView` watches `store.bank` (as it already does for the first-run gate) and calls
  `provenance.close()` + `provenanceCache.reset()`. (The entity card's `/provenance` state lives in
  the card and is re-asked whenever it shows another entity, `.task(id: entity.id)`.)
- **R-PU27 — The capture-honesty line is the Stop hook's alone.** It keys on `captureKind ==
  "transcript"` (`transcript_capture.CAPTURE_KIND`), never on "a capture kind is present": Telegram's
  `/remind` note is stamped `reminder` (`telegram_capture.py:240`) and holds exactly what was sent. (The
  design's example payload says `"stop-hook"`; no writer produces that value.)
- **R-PU28 — A named agent always wears its mark.** `EvidenceSpeaker.agentOrigin(harness:origin:)`
  returns the origin whose mark belongs beside `agentName`'s words, by the same precedence, so a label
  and its mark never disagree. The chip ("ChatGPT replied" on an imported conversation wears the
  ChatGPT mark, not a generic bubble) and every agent turn's speaker line in the Reader (§4.4: "a
  harness mark with its label") draw it; the person's turns and an unnamed agent draw none.

---

## Coordination with parallel tracks

- **Search everywhere (Track S, `feat/search-everywhere`)** — replaces ⌘K's Ask sheet with a palette
  overlay (A11) and the hidden ⌘K/⌘F buttons with menu commands (A6), both in `ContentView.swift`.
  This track adds `.inspector` after `.overlay(alignment: .bottom) { toastBanner }` (`:51`) and one
  `.onChange(of: provenance.revision)` before `.sheet(isPresented: $showAskPanel)` (`:124`). When S
  lands the palette, that `onChange` must close the palette instead (same rule, R-PU20). P6 and
  find-in-conversation plug into R-PU19's seam.
- **Local sources (Track L, `feat/local-sources`)** — adds the stored `speaker` evidence kind and the
  `speaker:<label>:` marker family. The app already decodes `.speaker`, renders "Someone else said",
  and `EvidenceSpeaker.turnSpeaker` handles `role == "speaker"` with a stored name. Once `/span`
  carries the speaker's label (H3), `EvidenceLabel.speaker(kind:agent:speakerName:)` already takes it.
- **Remote connector (Track R, merged to `dev` after this base as PR #75)** — remote writes are
  authored by an app label (`claude-web`, `chatgpt`, `perplexity`; R-R5, `api/remote/catalog.py`).
  The design says `author_identity` buckets those as `harness`, but **no server does yet** — on this
  base and on `dev` @ `f7dfd21`, `git_service._classify_author_kind` returns only
  `user|system|unknown|model`, so `claude-web` arrives as `model`/`anthropic` (substring `claude`)
  and `chatgpt` as `model`/`openai` (substring `gpt`). This track builds the client half ready —
  `ContributorAvatar`'s `harness` branch draws `OriginMark(origin: author)` and `displayName` uses
  `OriginIconography.label` — and records the server half as **H6**; it does not re-derive the bucket
  in Swift (one rule, server-side, R-PB6). Track R already added the app labels and marks to
  `OriginIconography` on `dev`.
- **Settings v3 / Imports / Mascot (O, I, Z)** — all edit `Theme/Copy.swift`; this track never does
  (R-PU17).
- **Meadow M2** — may restyle these surfaces; every colour, font and duration here is a token, so a
  restyle is a token change.

## Hand-off (server fields this track degrades around — not built here)

- **H1** — `ConversationSummary` gains an `episodeId` (newest) so "Open conversation" works outside
  an entity card (Contributors drill-down, a future Conversations page) — R-PU5.
- **H2** — `EntityReadRequest.surface` accepts `span` so the Reader can record a read (§4.4) — R-PU12.
- **H3** — `/span` carries the turn's `speaker` label (and, cheaply, the document's `title` and
  `harness`) so a chip outside the entity card can say "Claude Code replied" / "Speaker 2 said" —
  R-PU6, R-PU16.
- **H4** — per-turn times for Stop-hook episodes (their `turns` key is still a count) — already on the
  G118 row.
- **H5** — seeking a video from a `media` chip once Track F/O's `media` evidence lands — R-PU22.
- **H6** — `git_service._classify_author_kind` buckets the remote catalog's app labels
  (`claude-web`, `chatgpt`, `perplexity`, …) as `harness` with no provider (the design's §4.1 rule,
  built by neither PR #72 nor PR #75), so a remote write is named after its app — "Claude", with the
  app's mark — rather than as a model ("Claude (claude-web)"). The app side is ready (Coordination,
  Track R).

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `Models/Evidence.swift` (new) | 1 | `EvidenceKind`, `Evidence`, `EpisodeSpan`, `EpisodeTurn`, `EpisodeFocus`, `EpisodeText` |
| `Models/Provenance.swift` (new) | 1 | `ProvenanceSpan`, `ProvenanceContributor`, `ProvenanceConversation`, `ProvenancePage`, `ProvenanceTotals`, `EntityProvenance`, `EpisodeCitation`, `EpisodeCitationEntity`, `EpisodeCitations` |
| `Utilities/ScalarText.swift` (new) | 1 | the one scalar-offset rule (R-PU1) |
| `Services/ProvenanceAPI.swift` (new) | 1 | `ProvenanceAPI`, `ReaderFocusQuery`, `APIClient` conformance over `getConditional` |
| `Models/Claim.swift` | 1, 3 | `Claim` evidence + author fields (1); plain `SourceTrust.label` (3) |
| `Models/Entity.swift` | 1 | `EntityHistoryEntry.authorKind/authorProvider` |
| `Models/Ask.swift` | 1 | `AskCitation.claimId/evidence` |
| `Theme/Copy+Provenance.swift` (new) | 2–6 | every string the viewer says (R-PU17) |
| `Theme/CicadaMotion.swift` | 2 | `spanRevealDuration`, `spanReveal(reduceMotion:)` |
| `Views/Provenance/ProvenanceRouter.swift` (new) | 2 | `ReaderTarget` (+ factories), `ProvenanceRouter` |
| `Views/Provenance/ProvenanceCache.swift` (new) | 2 | `LRUCache`, `ProvenanceLoad`, `ProvenanceCache` (a 422 reads as stale, R-PU25; `reset()`, R-PU26) |
| `Views/Provenance/ReaderModel.swift` (new) | 2, 5 | `EvidenceSpeaker`, `ReaderTime`, `ReaderWash`, `ReaderBlock`, `ReaderLayout`, `ReaderBanner`, `ReaderPresentation`, `ReaderHeader` (2); `ReaderNavigator`, `ReaderPresentation.citation` (5) |
| `Views/Provenance/ReaderInspector.swift` (new) | 2, 5 | the Reader view, `ReaderTurnView`, `ReaderText`, `ReaderBannerView` (2); citations, navigator, "Noted from this conversation" (5) |
| `CicadaApp.swift`, `ContentView.swift` | 2, 6 | inject router + cache; the `.inspector`; a bank switch closes the Reader and resets the cache (2); the Ask sheet steps aside (6) |
| `Theme/CicadaTiming.swift` (new) | 3 | hover dwell and grace (R-PU18) |
| `Views/Provenance/EvidenceChipModel.swift` (new) | 3, 6 | `EvidenceDocMeta`, `EvidenceDocIndex` (+ environment key), `EvidenceChipModel`, `EvidenceLabel` (3); `AskCitation.evidenceChips` (6) |
| `Views/Provenance/QuoteBlock.swift` (new) | 3 | the quoted passage component |
| `Views/Provenance/EvidenceChip.swift` (new) | 3 | `EvidenceChip`, `EvidencePreview`, `EvidenceChipRun` |
| `Views/Common/ClaimChip.swift` | 3 | footer: `AuthorPill` with `ContributorAvatar`, evidence chips; `EpisodePill` deleted |
| `Views/Contributors/ContributorsView.swift` | 3 | `ContributorAvatar` any size, bare `(author, kind, provider)` init, `harness` |
| `Views/Contributors/ContributorIdentity.swift` | 3, 4 | `displayName` harness branch, `kind(author:serverKind:)` (3); `vendorName(provider:)` (4) |
| `Views/Provenance/ProvenanceSummary.swift` (new) | 4 | the section's sentences, counts, coverage, the conversation→episode map |
| `Views/Provenance/WhereThisCameFromSection.swift` (new) | 4 | `ProvenanceSectionState`, the section view |
| `Views/Graph/EntityDetailCard.swift` | 4 | card-level provenance load, doc index, the section, "Look it up at", History faces, timeline sheet steps aside |
| `Views/Sources/ConversationPopover.swift` | 4 | "Open conversation" (A10) |
| `Models/InboxItem.swift`, `Views/Inbox/InboxCardView.swift` | 6 | `InboxCause.readerTarget`, doc fix; mark, quote face, "Show in conversation" |
| `Ask/AskPanel.swift` | 6 | evidence chips under each source |
| Tests (new) | 1–6 | `EvidenceDecodeTests`, `ScalarTextTests`, `ProvenanceAPITests` (1); `ReaderTurnsTests`, `ProvenanceRouterTests` (2); `EvidenceChipLabelTests` (3); `ProvenanceSummaryTests` (4); `ReaderNavigatorTests` (5); `ProvenanceEntryPointTests` (6) |
| Docs | 7 | `docs/goals/memory-evolution.md` (G118, G103, G106, G115), `docs/goals/TODO.md`, `CLAUDE.md` |

All Swift paths are under `app/CicadaApp/Sources/CicadaApp/` (tests under
`app/CicadaApp/Tests/CicadaAppTests/`).

---

### Task 1: Read the evidence back — wire models, scalar offsets, the four routes (P1, data half)

Nothing renders yet; the app simply stops dropping what the server sends. The branch stays
shippable: every new field is additive and decode-tolerant.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Evidence.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Provenance.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Utilities/ScalarText.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Services/ProvenanceAPI.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Claim.swift:98-147` (six fields, `CodingKeys`, decode)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift:181-250` (`EntityHistoryEntry.authorKind/authorProvider`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Ask.swift:12-40` (`AskCitation.claimId/evidence`)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/EvidenceDecodeTests.swift`, `ScalarTextTests.swift`, `ProvenanceAPITests.swift`
- Commit this plan: `docs/superpowers/plans/2026-09-23-provenance-ui.md`

**Interfaces:**
- Produces: `EvidenceKind` (`user|assistant|page|reasoning|media|speaker|derived|unknown`, `init(wire:)`, `hasOffsets`), `Evidence` (`isSpan`, `isEpisode`), `EpisodeSpan`, `EpisodeTurn`, `EpisodeFocus` (`range`), `EpisodeText` (`isPage`), `ProvenanceSpan` (`displayKind`), `ProvenanceContributor`, `ProvenanceConversation`, `ProvenancePage`, `ProvenanceTotals`, `EntityProvenance`, `EpisodeCitation` (`range`, `displayKind`), `EpisodeCitationEntity`, `EpisodeCitations`; `ScalarText` (`count`, `clamped`, `slice`, `around`); `protocol ProvenanceAPI` + `ReaderFocusQuery` (`none | span | mention`, `queryItems`) + `APIClient.provenancePath(_:_:_:query:)` and its four fetches; `Claim.evidence/sessionIds/origin/recordedAt/authorKind/authorProvider`; `EntityHistoryEntry.authorKind/authorProvider`; `AskCitation.claimId/evidence`.
- Consumes: `APIClient.getConditional(_:etag:)` (`APIClient.swift:2141`), `Conditional` (`Sync/SyncAPI.swift:9`), `MockURLProtocol` (`EntitySourceTests.swift:10`).

- [ ] **Step 1: Failing tests.** Create the three test files.

`app/CicadaApp/Tests/CicadaAppTests/EvidenceDecodeTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G118 slice 2 (design §4.1, §4.10) — the provenance payloads decode from
/// the server's exact camelCase shape, and every one of them degrades rather
/// than throws: an older backend, a legacy claim or a kind this build has
/// never heard of must never blank a view (R10).
final class EvidenceDecodeTests: XCTestCase {

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }

    // MARK: Claim

    func testAClaimCarriesItsEvidenceAndAuthorFields() throws {
        let claim = try decode(Claim.self, """
        {"id": "clm_2026-09-03_001", "text": "alpha-project uses sqlite-vec",
         "authoredBy": "claude-sonnet-4-5", "origin": "sleep",
         "evidence": [{"episode": "ep_2026-09-03_004", "start": 930, "end": 951,
                       "kind": "assistant", "hash": "a1b2c3d4e5f6"}],
         "sessionIds": ["ses_alpha"], "recordedAt": "2026-09-03T10:00:00+00:00",
         "authorKind": "model", "authorProvider": "anthropic"}
        """)
        XCTAssertEqual(claim.evidence, [Evidence(episode: "ep_2026-09-03_004", start: 930, end: 951,
                                                 kind: .assistant, hash: "a1b2c3d4e5f6")])
        XCTAssertEqual(claim.sessionIds, ["ses_alpha"])
        XCTAssertEqual(claim.origin, "sleep")
        XCTAssertEqual(claim.recordedAt, "2026-09-03T10:00:00+00:00")
        XCTAssertEqual(claim.authorKind, "model")
        XCTAssertEqual(claim.authorProvider, "anthropic")
    }

    func testAClaimWithoutEvidenceDecodesToAnEmptyList() throws {
        let claim = try decode(Claim.self, #"{"id": "clm_legacy", "text": "t", "sourceEpisodes": ["ep_2026-01-01_001"]}"#)
        XCTAssertEqual(claim.evidence, [])
        XCTAssertEqual(claim.sessionIds, [])
        XCTAssertNil(claim.origin)
        XCTAssertNil(claim.authorKind)
        XCTAssertNil(claim.authorProvider)
        XCTAssertEqual(claim.sourceEpisodes, ["ep_2026-01-01_001"])
    }

    // MARK: Evidence

    func testAnUnknownKindDecodesToUnknownAndIsNeverASpan() throws {
        let ev = try decode(Evidence.self, #"{"episode": "ep_2026-09-03_004", "start": 1, "end": 9, "kind": "hologram"}"#)
        XCTAssertEqual(ev.kind, .unknown)
        XCTAssertFalse(ev.isSpan, "an unknown kind renders like reasoning (§4.10)")
    }

    func testReasoningIsNeverASpanEvenWithOffsets() {
        XCTAssertFalse(Evidence(episode: "ep_2026-09-03_004", start: -1, end: -1, kind: .reasoning).isSpan)
        XCTAssertFalse(Evidence(episode: "ep_2026-09-03_004", start: 3, end: 9, kind: .reasoning).isSpan)
        XCTAssertFalse(Evidence(episode: "", start: 3, end: 9, kind: .user).isSpan, "no document, no span")
        XCTAssertFalse(Evidence(episode: "ep_x", start: 9, end: 9, kind: .user).isSpan, "an empty range is no span")
        XCTAssertTrue(Evidence(episode: "ep_x", start: 3, end: 9, kind: .user).isSpan)
        XCTAssertTrue(Evidence(episode: "media-example-com", start: 0, end: 4, kind: .page).isSpan)
    }

    func testEvidenceMissingEveryFieldIsReasoningNotACrash() throws {
        let ev = try decode(Evidence.self, "{}")
        XCTAssertEqual(ev.kind, .reasoning, "the server's own default kind")
        XCTAssertEqual(ev.start, -1)
        XCTAssertFalse(ev.isSpan)
    }

    func testDerivedIsAReadKindThatNeverClaimsOffsets() {
        XCTAssertFalse(EvidenceKind.derived.hasOffsets)
        XCTAssertEqual(EvidenceKind(wire: "DERIVED"), .derived)
        XCTAssertEqual(EvidenceKind(wire: nil), .unknown)
    }

    // MARK: /span

    func testASliceOneSpanPayloadHasNoGrownAndReadsAsNotGrown() throws {
        let span = try decode(EpisodeSpan.self, """
        {"episode": "ep_2026-09-03_004", "text": "sqlite-vec", "before": "moved to ", "after": " so",
         "start": 9, "end": 19, "length": 22, "stale": false, "kind": "assistant"}
        """)
        XCTAssertFalse(span.grown)
        XCTAssertEqual(span.kind, .assistant)
        XCTAssertEqual(span.before + span.text + span.after, "moved to sqlite-vec so")
    }

    // MARK: /text

    func testEpisodeTextDecodesTurnsFocusAndHeader() throws {
        let doc = try decode(EpisodeText.self, """
        {"episode": "ep_2026-09-03_004", "kind": "episode", "text": "user: hi\\nassistant: hello",
         "length": 26, "hash": "a1b2c3d4e5f6", "truncated": false, "title": "Index choice",
         "timestamp": "2026-09-03T10:00:00+00:00", "harness": "claude-code", "origin": "claude-code",
         "conversationId": "ses_alpha", "captureKind": "transcript",
         "turns": [{"index": 1, "start": 0, "contentStart": 6, "end": 8, "role": "user", "marker": "user"},
                   {"index": 2, "start": 9, "contentStart": 20, "end": 26, "role": "assistant",
                    "marker": "assistant", "ts": "2026-09-03T10:01:00+00:00", "speaker": "assistant"}],
         "focus": {"start": 20, "end": 26, "kind": "assistant", "derived": false, "stale": false, "grown": true}}
        """)
        XCTAssertEqual(doc.turns.count, 2)
        XCTAssertEqual(doc.turns[1].contentStart, 20)
        XCTAssertEqual(doc.turns[1].ts, "2026-09-03T10:01:00+00:00")
        XCTAssertNil(doc.turns[0].ts, "a time is never inferred")
        XCTAssertEqual(doc.focus?.range, 20..<26)
        XCTAssertEqual(doc.focus?.grown, true)
        XCTAssertEqual(doc.captureKind, "transcript", "the Stop hook's own stamp (`transcript_capture.CAPTURE_KIND`)")
        XCTAssertFalse(doc.isPage)
    }

    func testAStaleFocusHasNoRangeToWash() throws {
        let focus = try decode(EpisodeFocus.self, #"{"start": null, "end": null, "kind": "user", "stale": true}"#)
        XCTAssertNil(focus.range, "R-PB2 — stale never highlights")
        XCTAssertTrue(focus.stale)
    }

    // MARK: /provenance

    func testEntityProvenanceDecodesAndDefaultsEverythingOptional() throws {
        let full = try decode(EntityProvenance.self, """
        {"entityId": "alpha-project", "entityName": "Alpha project", "entityType": "project",
         "contributors": [{"author": "claude-sonnet-4-5", "kind": "model", "provider": "anthropic",
                           "claims": 12, "commits": 3},
                          {"author": "user", "kind": "user", "claims": 4, "commits": 2}],
         "conversations": [{"conversationId": "ses_alpha", "episodeId": "ep_2026-09-03_004",
                            "episodeIds": ["ep_2026-09-03_004"], "title": "Index choice",
                            "harness": "claude-code", "timestamp": "2026-09-03T10:00:00+00:00",
                            "claimCount": 5, "available": true,
                            "best": {"episode": "ep_2026-09-03_004", "start": 930, "end": 951,
                                     "hash": "a1b2c3d4e5f6", "kind": "derived", "excerpt": "…sqlite-vec…",
                                     "excerptStart": 900, "mentionOffsets": [[30, 40]],
                                     "stale": false, "grown": false, "derived": true}}],
         "pages": [{"entityId": "media-example-com", "name": "example.com", "claimCount": 1}],
         "inferredCount": 2, "totals": {"claims": 18, "withSpan": 9, "legacy": 7, "conversations": 3},
         "commitsTruncated": false}
        """)
        XCTAssertEqual(full.contributors.map(\.author), ["claude-sonnet-4-5", "user"])
        XCTAssertNil(full.contributors[1].provider)
        XCTAssertEqual(full.conversations.first?.best?.displayKind, .derived,
                       "a derived match is never labelled with a speaker (§4.9)")
        XCTAssertEqual(full.totals.withSpan, 9)
        XCTAssertEqual(full.pages.first?.name, "example.com")

        let bare = try decode(EntityProvenance.self, #"{"entityId": "alpha-project"}"#)
        XCTAssertEqual(bare.contributors, [])
        XCTAssertEqual(bare.totals, ProvenanceTotals())
        XCTAssertFalse(bare.commitsTruncated)
    }

    func testAStaleBestQuoteTravelsWithoutOffsets() throws {
        let best = try decode(ProvenanceSpan.self, """
        {"episode": "ep_2026-09-03_004", "start": null, "end": null, "kind": "user",
         "excerpt": "the words may have moved", "stale": true}
        """)
        XCTAssertNil(best.start)
        XCTAssertTrue(best.stale)
        XCTAssertEqual(best.displayKind, .user)
    }

    // MARK: /citations

    func testCitationsDecodeSpanDerivedAndReasoningRows() throws {
        let payload = try decode(EpisodeCitations.self, """
        {"episode": "ep_2026-09-03_004", "partial": true,
         "citations": [
           {"claimId": "clm_1", "subjectId": "alpha-project", "subjectName": "Alpha project",
            "subjectType": "project", "text": "uses sqlite-vec", "current": true, "authoredBy": "claude-sonnet-4-5",
            "observer": "agent", "evidence": {"episode": "ep_2026-09-03_004", "start": 930, "end": 951,
            "kind": "assistant", "hash": "a1b2c3d4e5f6"}, "kind": "assistant", "start": 930, "end": 951},
           {"claimId": "clm_2", "subjectId": "bob-example", "kind": "derived", "derived": true,
            "start": 12, "end": 23},
           {"claimId": "clm_3", "subjectId": "bob-example", "kind": "reasoning",
            "evidence": {"episode": "ep_2026-09-03_004", "start": -1, "end": -1, "kind": "reasoning"}}],
         "entities": [{"entityId": "alpha-project", "name": "Alpha project", "type": "project"}]}
        """)
        XCTAssertTrue(payload.partial)
        XCTAssertEqual(payload.citations.map(\.displayKind), [.assistant, .derived, .reasoning])
        XCTAssertEqual(payload.citations[0].range, 930..<951)
        XCTAssertNil(payload.citations[2].range)
        XCTAssertEqual(Set(payload.citations.map(\.id)).count, 3, "every row keeps its own identity")
    }

    // MARK: History + Ask

    func testHistoryEntryAndAskCitationCarryTheNewFieldsAndToleratesTheirAbsence() throws {
        let entry = try decode(EntityHistoryEntry.self, """
        {"date": "2026-09-03", "changeType": "updated", "description": "d", "author": "cicada",
         "authorKind": "system", "authorProvider": null}
        """)
        XCTAssertEqual(entry.authorKind, "system")
        XCTAssertNil(entry.authorProvider)
        let old = try decode(EntityHistoryEntry.self, #"{"date": "2026-01-01", "changeType": "created", "description": "d"}"#)
        XCTAssertNil(old.authorKind)

        let cited = try decode(AskCitation.self, """
        {"entityId": "alpha-project", "entityName": "Alpha project", "filePath": "", "snippet": "s",
         "claimId": "clm_1", "evidence": [{"episode": "ep_2026-09-03_004", "start": 1, "end": 5,
         "kind": "user", "hash": "h"}]}
        """)
        XCTAssertEqual(cited.claimId, "clm_1")
        XCTAssertEqual(cited.evidence.first?.kind, .user)
        let plain = try decode(AskCitation.self, #"{"entityId": "alpha-project"}"#)
        XCTAssertNil(plain.claimId)
        XCTAssertEqual(plain.evidence, [])
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/ScalarTextTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Design §4.1 / §4.10 — offsets are Python `str` indices (code points).
/// Every fixture pair below was generated ONCE from the backend's own
/// `text[start:end]` (CPython 3.12, 2026-09-23), so a Swift slice that agrees
/// with them agrees with `/span`, `/text` and every evidence entry.
final class ScalarTextTests: XCTestCase {

    // (text, start, end, python text[start:end], python len(text))
    private let pythonFixtures: [(String, Int, Int, String, Int)] = [
        // An emoji is ONE code point but TWO UTF-16 units: an NSRange would land one early.
        ("user: I \u{1F600} moved the index to sqlite-vec", 29, 39, "sqlite-vec", 39),
        ("user: I \u{1F600} moved the index to sqlite-vec", 8, 9, "\u{1F600}", 39),
        // A combining accent is its own code point: `e` + U+0301 is one Character, two scalars.
        ("user: the cafe\u{0301} on alpha-project closes at 6", 19, 32, "alpha-project", 44),
        ("user: the cafe\u{0301} on alpha-project closes at 6", 13, 14, "e", 44),
        ("user: the cafe\u{0301} on alpha-project closes at 6", 13, 15, "e\u{0301}", 44),
        // CJK: one code point per ideograph, and no surrogate pairs.
        ("assistant: \u{6211}\u{4EEC}\u{628A}\u{7D22}\u{5F15}\u{79FB}\u{5230}\u{4E86} sqlite-vec "
            + "\u{6240}\u{4EE5}\u{641C}\u{7D22}\u{662F}\u{4E00}\u{6B21}\u{67E5}\u{627E}", 20, 30, "sqlite-vec", 40),
        // A flag is two regional indicators; a ZWJ family is five code points.
        ("user: \u{1F1EF}\u{1F1F5} trip with bob-example \u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} next week",
         19, 30, "bob-example", 46),
        ("user: \u{1F1EF}\u{1F1F5} trip with bob-example \u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} next week",
         6, 8, "\u{1F1EF}\u{1F1F5}", 46),
        ("user: \u{1F1EF}\u{1F1F5} trip with bob-example \u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} next week",
         31, 36, "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}", 46),
    ]

    func testSlicesAgreeWithPythonOnEmojiCombiningAccentsAndCJK() {
        for (text, start, end, expected, length) in pythonFixtures {
            let doc = ScalarText(text)
            XCTAssertEqual(doc.count, length, "count must be len(text) for \(text)")
            XCTAssertEqual(doc.slice(start, end), expected, "[\(start), \(end)) of \(text)")
        }
    }

    func testCharacterAndUTF16CountsDisagreeWithTheServerWhichIsWhyThisTypeExists() {
        let text = "user: I \u{1F600} moved the index to sqlite-vec"
        XCTAssertNotEqual(text.utf16.count, ScalarText(text).count)
        let accented = "cafe\u{0301}"
        XCTAssertNotEqual(accented.count, ScalarText(accented).count)
    }

    func testOutOfRangeOffsetsClampInsteadOfTrapping() {
        let doc = ScalarText("abc")
        XCTAssertEqual(doc.slice(-5, 2), "ab")
        XCTAssertEqual(doc.slice(1, 99), "bc")
        XCTAssertEqual(doc.slice(5, 9), "")
        XCTAssertEqual(doc.slice(2, 1), "", "an inverted range is empty, not a crash")
        XCTAssertEqual(doc.clamped(2, 1), 2..<2)
    }

    func testAroundGivesContextOnBothSides() {
        let doc = ScalarText("I \u{1F600} moved the index")
        let parts = doc.around(4, 9, radius: 2)
        XCTAssertEqual(parts.span, "moved")
        XCTAssertEqual(parts.before, "\u{1F600} ")
        XCTAssertEqual(parts.after, " t")
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/ProvenanceAPITests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G118 slice 2 — the four read routes are asked for with exactly the query
/// the server takes (`api/routers/episodes.py`, `claims.py`), and an ETag
/// round-trips so a 304 keeps what the cache already holds.
final class ProvenanceAPITests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private func respond(_ body: String, status: Int = 200, etag: String? = nil,
                         check: @escaping (URLRequest) -> Void) {
        MockURLProtocol.handler = { request in
            check(request)
            var headers: [String: String] = [:]
            if let etag { headers["ETag"] = etag }
            let response = HTTPURLResponse(url: request.url!, statusCode: status,
                                           httpVersion: nil, headerFields: headers)!
            return (response, Data(body.utf8))
        }
    }

    private var client: APIClient { APIClient(session: MockURLProtocol.makeSession()) }

    func testSpanAsksForStartEndAndHash() async throws {
        respond(#"{"episode": "ep_2026-09-03_004", "text": "x", "start": 1, "end": 2}"#) { request in
            XCTAssertEqual(request.url?.path, "/episodes/ep_2026-09-03_004/span")
            XCTAssertEqual(request.url?.query, "start=1&end=2&hash=a1b2c3d4e5f6")
        }
        let span = try await client.fetchEpisodeSpan(episode: "ep_2026-09-03_004", start: 1, end: 2,
                                                     hash: "a1b2c3d4e5f6")
        XCTAssertEqual(span.text, "x")
    }

    func testTextSpellsEachFocusTheWayTheRouterReadsIt() {
        XCTAssertEqual(APIClient.provenancePath("/episodes", "ep_1", "/text"), "/episodes/ep_1/text")
        XCTAssertEqual(
            APIClient.provenancePath("/episodes", "ep_1", "/text",
                                     query: ReaderFocusQuery.span(start: 3, end: 9, hash: nil).queryItems),
            "/episodes/ep_1/text?start=3&end=9",
            "no hash means no hash parameter — the inbox cause is current by construction (R-PB16)")
        XCTAssertEqual(
            APIClient.provenancePath("/episodes", "ep_1", "/text",
                                     query: ReaderFocusQuery.mention(entityId: "alpha-project").queryItems),
            "/episodes/ep_1/text?focus=alpha-project")
        XCTAssertEqual(APIClient.provenancePath("/episodes", "ep/../x", "/text"), "/episodes/ep%2F..%2Fx/text",
                       "a slash in an id never reshapes the path")
        XCTAssertEqual(
            APIClient.provenancePath("/episodes", "ep_1", "/text",
                                     query: ReaderFocusQuery.mention(entityId: "a+b").queryItems),
            "/episodes/ep_1/text?focus=a%2Bb", "a plus is never read back as a space")
    }

    func testTextSendsTheETagAndReportsA304AsNotModified() async throws {
        respond("", status: 304) { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "If-None-Match"), "\"v1\"")
        }
        let result = try await client.fetchEpisodeText(episode: "ep_1", focus: .none, etag: "\"v1\"")
        XCTAssertTrue(result.notModified)
        XCTAssertNil(result.value)
    }

    func testProvenanceAndCitationsHitTheirRoutes() async throws {
        respond(#"{"entityId": "alpha-project"}"#, etag: "\"p1\"") { request in
            XCTAssertEqual(request.url?.path, "/entities/alpha-project/provenance")
        }
        let provenance = try await client.fetchEntityProvenance(entityId: "alpha-project", etag: nil)
        XCTAssertEqual(provenance.value?.entityId, "alpha-project")
        XCTAssertEqual(provenance.etag, "\"p1\"")

        respond(#"{"episode": "ep_1", "citations": []}"#) { request in
            XCTAssertEqual(request.url?.path, "/episodes/ep_1/citations")
        }
        let citations = try await client.fetchEpisodeCitations(episode: "ep_1", etag: nil)
        XCTAssertEqual(citations.value?.episode, "ep_1")
    }

    func testA404IsAnHTTPErrorTheCacheCanNameAsGone() async {
        respond(#"{"detail": "No stored document"}"#, status: 404) { _ in }
        do {
            _ = try await client.fetchEpisodeText(episode: "ep_gone", focus: .none, etag: nil)
            XCTFail("a 404 must surface")
        } catch APIError.httpError(let code, _) {
            XCTAssertEqual(code, 404)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}
```

- [ ] **Step 2: Watch them fail.**
`cd <worktree>/app/CicadaApp && swift test --filter "EvidenceDecodeTests|ScalarTextTests|ProvenanceAPITests" 2>&1 | tail -20`
→ compile errors naming `Evidence`, `EpisodeSpan`, `ScalarText`, `ReaderFocusQuery`… That is the red.

- [ ] **Step 3: Implement.** Create `Models/Evidence.swift`:

```swift
import Foundation

// MARK: - Evidence (G118 slice 1 on the wire, read back by slice 2)
//
// A claim points at the words it came from as `(episode, start, end, kind,
// hash)` — offsets into a stored document, never a copy (`EvidenceModel`,
// `api/models/schemas.py`). Slice 1 shipped the field; the app dropped it
// because `Claim.CodingKeys` never named it. These types read it back, and
// every one decodes tolerantly: an older backend, a legacy claim with no
// evidence, or a kind this build has never heard of must never blank a view
// (design §4.1, R10 — the same rule `Epistemic`/`SourceTrust` follow).

/// What kind of words a span points at. The server stores `user`,
/// `assistant`, `page` and `reasoning` today (`claims.EVIDENCE_KINDS`);
/// `speaker` (a meeting utterance, R-N2) and `media` (a video excerpt, R5 D4)
/// are the kinds sibling tracks add; `derived` exists ONLY on read payloads —
/// a name match found at read, never written (R-PB9, §4.9). `unknown` is the
/// forward-compatible tail and renders like `reasoning`.
enum EvidenceKind: String, Codable, Hashable, CaseIterable {
    case user, assistant, page, reasoning, media, speaker, derived, unknown

    init(wire: String?) {
        self = EvidenceKind(rawValue: (wire ?? "").lowercased()) ?? .unknown
    }

    init(from decoder: Decoder) throws {
        self.init(wire: try? decoder.singleValueContainer().decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(rawValue)
    }

    /// Kinds whose stored offsets index words the Reader can wash. `reasoning`
    /// is the contributor citing itself (`start == end == -1`); `derived`
    /// offsets are real but are a name match, styled bold, never washed.
    var hasOffsets: Bool {
        switch self {
        case .user, .assistant, .page, .media, .speaker: true
        case .reasoning, .derived, .unknown: false
        }
    }
}

/// One evidence entry on a claim (`EvidenceModel`). `episode` is a
/// source-document id: `ep_*` is an episode, anything else an entity page (a
/// `page` span cites the media entity, `evidence.source_path`).
struct Evidence: Codable, Hashable {
    let episode: String
    let start: Int
    let end: Int
    let kind: EvidenceKind
    let hash: String

    /// A span the Reader can land on and wash. Never true for `reasoning`
    /// (design §4.10) — offsets of -1 are "no sentence", not "sentence zero".
    var isSpan: Bool { kind.hasOffsets && !episode.isEmpty && start >= 0 && end > start }

    /// `ep_*` → an episode (a conversation); anything else → a page.
    var isEpisode: Bool { episode.hasPrefix("ep_") }

    init(episode: String, start: Int, end: Int, kind: EvidenceKind, hash: String = "") {
        self.episode = episode
        self.start = start
        self.end = end
        self.kind = kind
        self.hash = hash
    }

    enum CodingKeys: String, CodingKey { case episode, start, end, kind, hash }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? -1
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? -1
        // The server's own default is `reasoning` (`EvidenceModel.kind`): an
        // entry that names no kind makes no claim about whose words these are.
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .reasoning
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
    }
}

// MARK: - GET /episodes/{id}/span

/// `EpisodeSpan` — the cited words with context either side, for the hover
/// preview. `stale` and `grown` are never both true (amendment A7): `grown`
/// means the conversation continued and the offsets are still exact, so it
/// highlights; `stale` never does (§4.9).
struct EpisodeSpan: Codable, Hashable {
    let episode: String
    let text: String
    let before: String
    let after: String
    let start: Int
    let end: Int
    let length: Int
    let stale: Bool
    let grown: Bool
    let kind: EvidenceKind

    /// Built client-side for one case only: a span the document no longer
    /// reaches (`/span` answers 422 once a rewrite made the text shorter than
    /// `end`) is served as a stale span with no words (R-PU25), because "the
    /// words moved" is the truth and "couldn't open" is not.
    init(episode: String, text: String = "", before: String = "", after: String = "", start: Int, end: Int,
         length: Int = 0, stale: Bool = false, grown: Bool = false, kind: EvidenceKind = .user) {
        self.episode = episode
        self.text = text
        self.before = before
        self.after = after
        self.start = start
        self.end = end
        self.length = length
        self.stale = stale
        self.grown = grown
        self.kind = kind
    }

    enum CodingKeys: String, CodingKey { case episode, text, before, after, start, end, length, stale, grown, kind }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        before = try c.decodeIfPresent(String.self, forKey: .before) ?? ""
        after = try c.decodeIfPresent(String.self, forKey: .after) ?? ""
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? 0
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? 0
        length = try c.decodeIfPresent(Int.self, forKey: .length) ?? 0
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        // A slice-1 backend has no `grown`; absent reads as "not grown", which
        // is exactly what that backend meant.
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .user
    }
}

// MARK: - GET /episodes/{id}/text

/// One turn of a document (`EpisodeTurn`) — offsets into the evidence text,
/// never a copy. `role` is `user` | `assistant` | `page` (and `speaker` once
/// the note-taker track extends the one marker parser, R-PB3); `marker` is
/// the word as written (`nil` for a marker-less block); `ts`/`speaker` exist
/// only where the episode stores a `turns` sidecar entry — a time is never
/// inferred (§4.4).
struct EpisodeTurn: Codable, Hashable, Identifiable {
    let index: Int
    let start: Int
    let contentStart: Int
    let end: Int
    let role: String
    let marker: String?
    let speaker: String?
    let ts: String?

    var id: Int { index }

    init(index: Int, start: Int, contentStart: Int, end: Int, role: String = "user",
         marker: String? = nil, speaker: String? = nil, ts: String? = nil) {
        self.index = index
        self.start = start
        self.contentStart = contentStart
        self.end = end
        self.role = role
        self.marker = marker
        self.speaker = speaker
        self.ts = ts
    }

    enum CodingKeys: String, CodingKey { case index, start, contentStart, end, role, marker, speaker, ts }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        index = try c.decodeIfPresent(Int.self, forKey: .index) ?? 0
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? 0
        contentStart = try c.decodeIfPresent(Int.self, forKey: .contentStart) ?? start
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? start
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? "user"
        marker = try c.decodeIfPresent(String.self, forKey: .marker)
        speaker = try c.decodeIfPresent(String.self, forKey: .speaker)
        ts = try c.decodeIfPresent(String.self, forKey: .ts)
    }
}

/// The span the Reader lands on (`EpisodeFocus`). A stale focus carries NO
/// offsets (R-PB2) — "stale never highlights" is unrepresentable, not a
/// client convention. `derived` is a name match found at read (R-PB9).
struct EpisodeFocus: Codable, Hashable {
    let start: Int?
    let end: Int?
    let kind: EvidenceKind
    let derived: Bool
    let stale: Bool
    let grown: Bool

    init(start: Int?, end: Int?, kind: EvidenceKind = .user, derived: Bool = false,
         stale: Bool = false, grown: Bool = false) {
        self.start = start
        self.end = end
        self.kind = kind
        self.derived = derived
        self.stale = stale
        self.grown = grown
    }

    enum CodingKeys: String, CodingKey { case start, end, kind, derived, stale, grown }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .user
        derived = try c.decodeIfPresent(Bool.self, forKey: .derived) ?? false
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
    }

    /// `[start, end)` when the server sent a washable pair, else nil.
    var range: Range<Int>? {
        guard let start, let end, start >= 0, end > start else { return nil }
        return start..<end
    }
}

/// `EpisodeText` — a whole stored document for the Reader. `text` is capped
/// at 400,000 characters server-side (`truncated`, R-PB5); `length` and
/// `hash` always describe the WHOLE text. `conversationId` is the stamped
/// `session_id` or G20's `source_id`. `projectDir`/`resumable` are
/// deliberately absent — `GET /conversations/{id}` is the one place a
/// transcript is `isfile()`-d.
struct EpisodeText: Codable, Hashable {
    let episode: String
    let kind: String
    let text: String
    let length: Int
    let hash: String
    let truncated: Bool
    let title: String
    let timestamp: String?
    let harness: String?
    let origin: String?
    let conversationId: String?
    let captureKind: String?
    let turns: [EpisodeTurn]
    let focus: EpisodeFocus?

    var isPage: Bool { kind == "page" }

    init(episode: String, kind: String = "episode", text: String, length: Int? = nil, hash: String = "",
         truncated: Bool = false, title: String = "", timestamp: String? = nil, harness: String? = nil,
         origin: String? = nil, conversationId: String? = nil, captureKind: String? = nil,
         turns: [EpisodeTurn] = [], focus: EpisodeFocus? = nil) {
        self.episode = episode
        self.kind = kind
        self.text = text
        self.length = length ?? text.unicodeScalars.count
        self.hash = hash
        self.truncated = truncated
        self.title = title
        self.timestamp = timestamp
        self.harness = harness
        self.origin = origin
        self.conversationId = conversationId
        self.captureKind = captureKind
        self.turns = turns
        self.focus = focus
    }

    enum CodingKeys: String, CodingKey {
        case episode, kind, text, length, hash, truncated, title, timestamp, harness, origin
        case conversationId, captureKind, turns, focus
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "episode"
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        length = try c.decodeIfPresent(Int.self, forKey: .length) ?? text.unicodeScalars.count
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        truncated = try c.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        captureKind = try c.decodeIfPresent(String.self, forKey: .captureKind)
        turns = try c.decodeIfPresent([EpisodeTurn].self, forKey: .turns) ?? []
        focus = try c.decodeIfPresent(EpisodeFocus.self, forKey: .focus)
    }
}
```

Create `Models/Provenance.swift`:

```swift
import Foundation

// MARK: - GET /entities/{id}/provenance (G118 slice 2, design §4.5 / §4.8.4)
//
// "Where this came from" in one call — contributors, the conversations that
// fed the page with their best quote, and coverage stated honestly. Every
// field is optional-with-default: a backend without the route 404s (the
// section hides), and one that ships fewer fields still decodes (R10).

/// The one quote a provenance row shows (`ProvenanceSpan`). `kind` is the
/// stored evidence kind or `derived`; `start`/`end` are absolute offsets to
/// wash and are nil when `stale` (R-PB2). `excerpt` is ±240 chars cut on word
/// boundaries; `excerptStart` is its absolute offset and `mentionOffsets` are
/// RELATIVE to it — the inbox cause's shape (G115).
struct ProvenanceSpan: Codable, Hashable {
    let episode: String
    let start: Int?
    let end: Int?
    let hash: String
    let kind: EvidenceKind
    let excerpt: String
    let excerptStart: Int
    let mentionOffsets: [[Int]]
    let stale: Bool
    let grown: Bool
    let derived: Bool

    init(episode: String, start: Int?, end: Int?, hash: String = "", kind: EvidenceKind,
         excerpt: String, excerptStart: Int = 0, mentionOffsets: [[Int]] = [],
         stale: Bool = false, grown: Bool = false, derived: Bool = false) {
        self.episode = episode
        self.start = start
        self.end = end
        self.hash = hash
        self.kind = kind
        self.excerpt = excerpt
        self.excerptStart = excerptStart
        self.mentionOffsets = mentionOffsets
        self.stale = stale
        self.grown = grown
        self.derived = derived
    }

    enum CodingKeys: String, CodingKey {
        case episode, start, end, hash, kind, excerpt, excerptStart, mentionOffsets, stale, grown, derived
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .derived
        excerpt = try c.decodeIfPresent(String.self, forKey: .excerpt) ?? ""
        excerptStart = try c.decodeIfPresent(Int.self, forKey: .excerptStart) ?? 0
        mentionOffsets = try c.decodeIfPresent([[Int]].self, forKey: .mentionOffsets) ?? []
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
        derived = try c.decodeIfPresent(Bool.self, forKey: .derived) ?? false
    }

    /// A derived match is never "You said" (§4.9): the kind the chip renders
    /// is `derived` whenever the server says the words were found by name.
    var displayKind: EvidenceKind { derived ? .derived : kind }
}

/// One author of an entity (`ProvenanceContributor`, R-PB6): `claims` =
/// current claims with that `authored_by`; `commits` = commits that touched
/// the page with that `Cicada-Author`. `kind`/`provider` come from the one
/// `git_service.author_identity` rule, so the app never re-derives them.
struct ProvenanceContributor: Codable, Hashable, Identifiable {
    let author: String
    let kind: String
    let provider: String?
    let claims: Int
    let commits: Int

    var id: String { author }

    init(author: String, kind: String, provider: String? = nil, claims: Int = 0, commits: Int = 0) {
        self.author = author
        self.kind = kind
        self.provider = provider
        self.claims = claims
        self.commits = commits
    }

    enum CodingKeys: String, CodingKey { case author, kind, provider, claims, commits }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? "unknown"
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "unknown"
        provider = try c.decodeIfPresent(String.self, forKey: .provider)
        claims = try c.decodeIfPresent(Int.self, forKey: .claims) ?? 0
        commits = try c.decodeIfPresent(Int.self, forKey: .commits) ?? 0
    }
}

/// A conversation that fed the entity (`ProvenanceConversation`, R-PB7).
/// `episodeId` is its newest episode; `available == false` means no episode
/// file is left in the bank (the row stays, honestly, but opens nothing).
struct ProvenanceConversation: Codable, Hashable, Identifiable {
    let conversationId: String?
    let episodeId: String
    let episodeIds: [String]
    let title: String
    let harness: String?
    let origin: String?
    let timestamp: String?
    let claimCount: Int
    let available: Bool
    let best: ProvenanceSpan?

    var id: String { conversationId ?? episodeId }

    init(conversationId: String? = nil, episodeId: String, episodeIds: [String]? = nil, title: String = "",
         harness: String? = nil, origin: String? = nil, timestamp: String? = nil, claimCount: Int = 0,
         available: Bool = true, best: ProvenanceSpan? = nil) {
        self.conversationId = conversationId
        self.episodeId = episodeId
        self.episodeIds = episodeIds ?? [episodeId]
        self.title = title
        self.harness = harness
        self.origin = origin
        self.timestamp = timestamp
        self.claimCount = claimCount
        self.available = available
        self.best = best
    }

    enum CodingKeys: String, CodingKey {
        case conversationId, episodeId, episodeIds, title, harness, origin, timestamp, claimCount, available, best
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId) ?? ""
        episodeIds = try c.decodeIfPresent([String].self, forKey: .episodeIds) ?? [episodeId]
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        claimCount = try c.decodeIfPresent(Int.self, forKey: .claimCount) ?? 0
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? true
        best = try c.decodeIfPresent(ProvenanceSpan.self, forKey: .best)
    }
}

struct ProvenancePage: Codable, Hashable, Identifiable {
    let entityId: String
    let name: String
    let claimCount: Int

    var id: String { entityId }

    init(entityId: String, name: String = "", claimCount: Int = 0) {
        self.entityId = entityId
        self.name = name
        self.claimCount = claimCount
    }

    enum CodingKeys: String, CodingKey { case entityId, name, claimCount }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        claimCount = try c.decodeIfPresent(Int.self, forKey: .claimCount) ?? 0
    }
}

/// Coverage stated honestly (§4.5 item 5): of `claims` current beliefs,
/// `withSpan` carry at least one exact quote and `legacy` carry no evidence
/// at all (recorded before slice 1; there is no backfill).
struct ProvenanceTotals: Codable, Hashable {
    let claims: Int
    let withSpan: Int
    let legacy: Int
    let conversations: Int

    init(claims: Int = 0, withSpan: Int = 0, legacy: Int = 0, conversations: Int = 0) {
        self.claims = claims
        self.withSpan = withSpan
        self.legacy = legacy
        self.conversations = conversations
    }

    enum CodingKeys: String, CodingKey { case claims, withSpan, legacy, conversations }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claims = try c.decodeIfPresent(Int.self, forKey: .claims) ?? 0
        withSpan = try c.decodeIfPresent(Int.self, forKey: .withSpan) ?? 0
        legacy = try c.decodeIfPresent(Int.self, forKey: .legacy) ?? 0
        conversations = try c.decodeIfPresent(Int.self, forKey: .conversations) ?? 0
    }
}

struct EntityProvenance: Codable, Hashable {
    let entityId: String
    let entityName: String
    let entityType: String
    let contributors: [ProvenanceContributor]
    let conversations: [ProvenanceConversation]
    let pages: [ProvenancePage]
    let inferredCount: Int
    let totals: ProvenanceTotals
    let commitsTruncated: Bool

    init(entityId: String, entityName: String = "", entityType: String = "",
         contributors: [ProvenanceContributor] = [], conversations: [ProvenanceConversation] = [],
         pages: [ProvenancePage] = [], inferredCount: Int = 0, totals: ProvenanceTotals = ProvenanceTotals(),
         commitsTruncated: Bool = false) {
        self.entityId = entityId
        self.entityName = entityName
        self.entityType = entityType
        self.contributors = contributors
        self.conversations = conversations
        self.pages = pages
        self.inferredCount = inferredCount
        self.totals = totals
        self.commitsTruncated = commitsTruncated
    }

    enum CodingKeys: String, CodingKey {
        case entityId, entityName, entityType, contributors, conversations, pages, inferredCount, totals
        case commitsTruncated
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        entityType = try c.decodeIfPresent(String.self, forKey: .entityType) ?? ""
        contributors = try c.decodeIfPresent([ProvenanceContributor].self, forKey: .contributors) ?? []
        conversations = try c.decodeIfPresent([ProvenanceConversation].self, forKey: .conversations) ?? []
        pages = try c.decodeIfPresent([ProvenancePage].self, forKey: .pages) ?? []
        inferredCount = try c.decodeIfPresent(Int.self, forKey: .inferredCount) ?? 0
        totals = try c.decodeIfPresent(ProvenanceTotals.self, forKey: .totals) ?? ProvenanceTotals()
        commitsTruncated = try c.decodeIfPresent(Bool.self, forKey: .commitsTruncated) ?? false
    }
}

// MARK: - GET /episodes/{id}/citations (G118 slice 2, §4.8.3; G106 (ii))

/// One belief a document contributed (`EpisodeCitation`). `evidence` is the
/// stored entry for a span or reasoning row, nil for a derived one;
/// `start`/`end` are what to wash — nil for reasoning, a missed name, or a
/// stale span (R-PB2). `current == false` is a superseded or closed claim.
struct EpisodeCitation: Codable, Hashable, Identifiable {
    let claimId: String
    let subjectId: String
    let subjectName: String
    let subjectType: String
    let text: String
    let current: Bool
    let authoredBy: String
    let observer: String
    let evidence: Evidence?
    let kind: EvidenceKind
    let start: Int?
    let end: Int?
    let stale: Bool
    let grown: Bool
    let derived: Bool

    /// A claim can cite one document at several spans; each is its own row.
    var id: String { "\(claimId)|\(start ?? -1)|\(end ?? -1)|\(kind.rawValue)" }

    var range: Range<Int>? {
        guard let start, let end, start >= 0, end > start else { return nil }
        return start..<end
    }

    var displayKind: EvidenceKind { derived ? .derived : kind }

    init(claimId: String, subjectId: String, subjectName: String = "", subjectType: String = "",
         text: String = "", current: Bool = true, authoredBy: String = "unknown", observer: String = "agent",
         evidence: Evidence? = nil, kind: EvidenceKind = .reasoning, start: Int? = nil, end: Int? = nil,
         stale: Bool = false, grown: Bool = false, derived: Bool = false) {
        self.claimId = claimId
        self.subjectId = subjectId
        self.subjectName = subjectName
        self.subjectType = subjectType
        self.text = text
        self.current = current
        self.authoredBy = authoredBy
        self.observer = observer
        self.evidence = evidence
        self.kind = kind
        self.start = start
        self.end = end
        self.stale = stale
        self.grown = grown
        self.derived = derived
    }

    enum CodingKeys: String, CodingKey {
        case claimId, subjectId, subjectName, subjectType, text, current, authoredBy, observer
        case evidence, kind, start, end, stale, grown, derived
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId) ?? ""
        subjectId = try c.decodeIfPresent(String.self, forKey: .subjectId) ?? ""
        subjectName = try c.decodeIfPresent(String.self, forKey: .subjectName) ?? ""
        subjectType = try c.decodeIfPresent(String.self, forKey: .subjectType) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        current = try c.decodeIfPresent(Bool.self, forKey: .current) ?? true
        authoredBy = try c.decodeIfPresent(String.self, forKey: .authoredBy) ?? "unknown"
        observer = try c.decodeIfPresent(String.self, forKey: .observer) ?? "agent"
        evidence = try c.decodeIfPresent(Evidence.self, forKey: .evidence)
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .reasoning
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
        derived = try c.decodeIfPresent(Bool.self, forKey: .derived) ?? false
    }
}

struct EpisodeCitationEntity: Codable, Hashable, Identifiable {
    let entityId: String
    let name: String
    let type: String

    var id: String { entityId }

    enum CodingKeys: String, CodingKey { case entityId, name, type }

    init(entityId: String, name: String = "", type: String = "") {
        self.entityId = entityId
        self.name = name
        self.type = type
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? ""
    }
}

/// Spans first in document order (the navigator steps through them), then
/// rows without offsets. `partial` means more pages named the document than
/// one call parses (R-PB10: "capped", not "index cold").
struct EpisodeCitations: Codable, Hashable {
    let episode: String
    let citations: [EpisodeCitation]
    let entities: [EpisodeCitationEntity]
    let partial: Bool

    init(episode: String, citations: [EpisodeCitation] = [], entities: [EpisodeCitationEntity] = [],
         partial: Bool = false) {
        self.episode = episode
        self.citations = citations
        self.entities = entities
        self.partial = partial
    }

    enum CodingKeys: String, CodingKey { case episode, citations, entities, partial }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        citations = try c.decodeIfPresent([EpisodeCitation].self, forKey: .citations) ?? []
        entities = try c.decodeIfPresent([EpisodeCitationEntity].self, forKey: .entities) ?? []
        partial = try c.decodeIfPresent(Bool.self, forKey: .partial) ?? false
    }
}
```

Create `Utilities/ScalarText.swift`:

```swift
import Foundation

/// A document indexed the way the server indexes it (design §4.1): every
/// evidence offset is a Python `str` index, i.e. a Unicode **scalar** (code
/// point) index — not a `Character` (grapheme), not UTF-16. `String.count`
/// would put a span after an emoji one place early, and an `NSRange` two, so
/// every provenance slice in the app goes through this one type (the rule
/// `ExcerptText.attributed` already follows for inbox excerpts,
/// `Models/InboxPresentation.swift`).
///
/// **Why an array, not `unicodeScalars.index(_:offsetBy:)`.** Offsetting a
/// view index is O(n) per call, and the Reader slices every turn of a
/// document of up to 400,000 characters (R-PB5): ~200 turns × 100 KB is tens
/// of millions of steps on the main thread. One `Array(unicodeScalars)` is a
/// single O(n) pass and makes every slice O(length of the slice).
struct ScalarText: Hashable {
    let scalars: [Unicode.Scalar]

    init(_ text: String) { scalars = Array(text.unicodeScalars) }

    var count: Int { scalars.count }

    /// Clamps `[start, end)` into the text — a stale or out-of-range offset
    /// must never trap a view (the server recomputes offsets on every read,
    /// and a cached payload can lag the bank by a moment).
    func clamped(_ start: Int, _ end: Int) -> Range<Int> {
        let lower = max(0, min(start, count))
        let upper = max(lower, min(end, count))
        return lower..<upper
    }

    func slice(_ start: Int, _ end: Int) -> String {
        let r = clamped(start, end)
        guard !r.isEmpty else { return "" }
        var view = String.UnicodeScalarView()
        view.append(contentsOf: scalars[r])
        return String(view)
    }

    /// Up to `radius` scalars either side of `[start, end)`, the span itself
    /// in the middle — the hover preview's shape when it is built client-side
    /// from a whole document (a derived chip, `EvidencePreview`).
    func around(_ start: Int, _ end: Int, radius: Int) -> (before: String, span: String, after: String) {
        let r = clamped(start, end)
        return (slice(r.lowerBound - radius, r.lowerBound), slice(r.lowerBound, r.upperBound),
                slice(r.upperBound, r.upperBound + radius))
    }
}
```

Create `Services/ProvenanceAPI.swift`:

```swift
import Foundation

/// The four read routes the provenance viewer needs (G118 slice 2, server
/// half merged in PR #72). A protocol for the same reason `SyncAPI` is one:
/// `ProvenanceCache` is driven by a fake in tests, and `APIClient` conforms
/// below.
///
/// None of these payloads is a Store domain (R-PB11, design K10): they are
/// fetched on demand and cached in memory only, so there is no
/// `VersionVector` mapping to ship. `/text`, `/citations` and `/provenance`
/// carry an ETag for that in-memory cache (`etag` in, 304 → `notModified`);
/// `/span` has none by design (slice-1 R9 — the response validates itself).
protocol ProvenanceAPI: Sendable {
    func fetchEpisodeSpan(episode: String, start: Int, end: Int, hash: String?) async throws -> EpisodeSpan
    func fetchEpisodeText(episode: String, focus: ReaderFocusQuery, etag: String?) async throws
        -> Conditional<EpisodeText>
    func fetchEntityProvenance(entityId: String, etag: String?) async throws -> Conditional<EntityProvenance>
    func fetchEpisodeCitations(episode: String, etag: String?) async throws -> Conditional<EpisodeCitations>
}

/// What `/episodes/{id}/text` is asked to focus (R-PB5): an asserted span
/// (`?start&end[&hash]`), a derived mention of an entity (`?focus=<id>`), or
/// nothing. Its `queryItems` are the one place the query is spelled.
enum ReaderFocusQuery: Hashable, Sendable {
    case none
    case span(start: Int, end: Int, hash: String?)
    case mention(entityId: String)

    var queryItems: [URLQueryItem] {
        switch self {
        case .none:
            return []
        case let .span(start, end, hash):
            var items = [URLQueryItem(name: "start", value: String(start)),
                         URLQueryItem(name: "end", value: String(end))]
            if let hash, !hash.isEmpty { items.append(URLQueryItem(name: "hash", value: hash)) }
            return items
        case let .mention(entityId):
            return [URLQueryItem(name: "focus", value: entityId)]
        }
    }
}

extension APIClient: ProvenanceAPI {
    /// A document id is a bare stem (`evidence._DOC_ID_RE`), but it lands in a
    /// PATH, so encode it the way every other id-in-a-path is encoded here
    /// (`fetchConversation`): a `/`, `?` or `#` must never reshape the URL.
    nonisolated static func provenancePath(_ prefix: String, _ id: String, _ suffix: String,
                                           query: [URLQueryItem] = []) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
        var components = URLComponents()
        components.queryItems = query.isEmpty ? nil : query
        // `URLQueryItem` leaves `+` alone and a server reads `+` as a space;
        // a hash is hex and an entity id a slug, but encode it anyway so the
        // rule does not depend on what the values happen to look like today.
        let q = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        return "\(prefix)/\(encoded)\(suffix)" + (q.map { "?\($0)" } ?? "")
    }

    func fetchEpisodeSpan(episode: String, start: Int, end: Int, hash: String?) async throws -> EpisodeSpan {
        var query = [URLQueryItem(name: "start", value: String(start)),
                     URLQueryItem(name: "end", value: String(end))]
        if let hash, !hash.isEmpty { query.append(URLQueryItem(name: "hash", value: hash)) }
        let path = Self.provenancePath("/episodes", episode, "/span", query: query)
        let result: Conditional<EpisodeSpan> = try await getConditional(path, etag: nil)
        guard let value = result.value else { throw APIError.decodingError("empty /span response") }
        return value
    }

    func fetchEpisodeText(episode: String, focus: ReaderFocusQuery, etag: String?) async throws
        -> Conditional<EpisodeText> {
        try await getConditional(Self.provenancePath("/episodes", episode, "/text", query: focus.queryItems),
                                 etag: etag)
    }

    func fetchEntityProvenance(entityId: String, etag: String?) async throws -> Conditional<EntityProvenance> {
        try await getConditional(Self.provenancePath("/entities", entityId, "/provenance"), etag: etag)
    }

    func fetchEpisodeCitations(episode: String, etag: String?) async throws -> Conditional<EpisodeCitations> {
        try await getConditional(Self.provenancePath("/episodes", episode, "/citations"), etag: etag)
    }
}
```

Modify `Models/Claim.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift b/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift
index cf4f7dd..2205a2d 100644
--- a/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift
@@ -114,6 +114,19 @@ struct Claim: Identifiable, Codable, Hashable {
     let sourceEpisodes: [String]
     let premises: [String]
     let authoredBy: String            // model id or "user" — same vocabulary as Contributor.author
+    // G118 slice 1 shipped `evidence` on the wire and this model dropped it
+    // (CodingKeys never named it). Slice 2 reads it back, with the four author
+    // and conversation fields R-PB13 added beside it. All optional-with-default:
+    // a legacy claim has no evidence and an older backend none of the rest.
+    let evidence: [Evidence]
+    let sessionIds: [String]
+    let origin: String?
+    let recordedAt: String?
+    /// `user` | `system` | `model` | `harness` | `unknown`, from the server's
+    /// one `git_service.author_identity` rule — nil against an older backend,
+    /// where `ContributorIdentity.kind(author:)` falls back to the author id.
+    let authorKind: String?
+    let authorProvider: String?
 
     var isValid: Bool { validTo == nil }
 
@@ -121,6 +134,7 @@ struct Claim: Identifiable, Codable, Hashable {
         case id, text, subject, predicate, object, objectKind, observer, context
         case epistemic, sourceTrust, confidence, validFrom, validTo
         case supersededBy, supersedes, sourceEpisodes, premises, authoredBy
+        case evidence, sessionIds, origin, recordedAt, authorKind, authorProvider
     }
 
     init(from c: Decoder) throws {
@@ -143,6 +157,15 @@ struct Claim: Identifiable, Codable, Hashable {
         sourceEpisodes = try k.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
         premises = try k.decodeIfPresent([String].self, forKey: .premises) ?? []
         authoredBy = try k.decodeIfPresent(String.self, forKey: .authoredBy) ?? "unknown"
+        evidence = try k.decodeIfPresent([Evidence].self, forKey: .evidence) ?? []
+        sessionIds = try k.decodeIfPresent([String].self, forKey: .sessionIds) ?? []
+        origin = try k.decodeIfPresent(String.self, forKey: .origin)
+        recordedAt = try k.decodeIfPresent(String.self, forKey: .recordedAt)
+        // The server defaults both to "unknown"/null; an older backend omits
+        // them. "unknown" from the wire is kept verbatim — it is the server's
+        // answer, not a gap.
+        authorKind = try k.decodeIfPresent(String.self, forKey: .authorKind)
+        authorProvider = try k.decodeIfPresent(String.self, forKey: .authorProvider)
     }
 }
 
```

Modify `Models/Entity.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift b/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift
index 60fd005..0600f89 100644
--- a/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift
@@ -186,6 +186,12 @@ struct EntityHistoryEntry: Identifiable, Codable {
     // M3 (backlog A2): the agent that authored this commit — a model id
     // (e.g. "gpt-5.4-mini"), "user", or "unknown" for legacy untrailered commits.
     let author: String
+    // G118 slice 2 (R-PB13): the author's bucket and provider from the
+    // server's one `author_identity` rule, so the History tab draws the same
+    // `ContributorAvatar` the contributors strip does. nil against an older
+    // backend — `ContributorIdentity.kind(author:)` covers that case.
+    let authorKind: String?
+    let authorProvider: String?
     // Commit hash, used to fetch the per-commit diff on demand.
     let commitHash: String
     // Inline diff, present only when history was fetched with includeDiff=true.
@@ -201,7 +207,7 @@ struct EntityHistoryEntry: Identifiable, Codable {
     }
 
     enum CodingKeys: String, CodingKey {
-        case date, changeType, description, author, commitHash, diff, sessions
+        case date, changeType, description, author, authorKind, authorProvider, commitHash, diff, sessions
     }
 
     init(from decoder: Decoder) throws {
@@ -210,6 +216,8 @@ struct EntityHistoryEntry: Identifiable, Codable {
         changeType = try c.decode(HistoryChangeType.self, forKey: .changeType)
         description = try c.decode(String.self, forKey: .description)
         author = try c.decodeIfPresent(String.self, forKey: .author) ?? "unknown"
+        authorKind = try c.decodeIfPresent(String.self, forKey: .authorKind)
+        authorProvider = try c.decodeIfPresent(String.self, forKey: .authorProvider)
         commitHash = try c.decodeIfPresent(String.self, forKey: .commitHash) ?? ""
         diff = try c.decodeIfPresent(EntityDiff.self, forKey: .diff)
         sessions = try c.decodeIfPresent([String].self, forKey: .sessions) ?? []
@@ -220,6 +228,8 @@ struct EntityHistoryEntry: Identifiable, Codable {
         changeType: HistoryChangeType,
         description: String,
         author: String = "unknown",
+        authorKind: String? = nil,
+        authorProvider: String? = nil,
         commitHash: String = "",
         diff: EntityDiff? = nil,
         sessions: [String] = []
@@ -230,6 +240,8 @@ struct EntityHistoryEntry: Identifiable, Codable {
         self.changeType = changeType
         self.description = description
         self.author = author
+        self.authorKind = authorKind
+        self.authorProvider = authorProvider
         self.commitHash = commitHash
         self.diff = diff
         self.sessions = sessions
@@ -241,6 +253,8 @@ struct EntityHistoryEntry: Identifiable, Codable {
         try c.encode(changeType, forKey: .changeType)
         try c.encode(description, forKey: .description)
         try c.encode(author, forKey: .author)
+        try c.encodeIfPresent(authorKind, forKey: .authorKind)
+        try c.encodeIfPresent(authorProvider, forKey: .authorProvider)
         try c.encode(commitHash, forKey: .commitHash)
         try c.encodeIfPresent(diff, forKey: .diff)
         try c.encode(sessions, forKey: .sessions)
```

Modify `Models/Ask.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/Ask.swift b/app/CicadaApp/Sources/CicadaApp/Models/Ask.swift
index fcfba82..d0b6d60 100644
--- a/app/CicadaApp/Sources/CicadaApp/Models/Ask.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/Ask.swift
@@ -15,11 +15,16 @@ struct AskCitation: Codable, Identifiable, Equatable {
     let filePath: String
     let snippet: String
     let sourceEpisodes: [String]
+    // G118 slice 2 (R-PB12): set when the retrieval hit was a claim — the
+    // claim and the spans behind it, raw as stored (freshness is `/span`'s
+    // job). Absent for an entity-only hit and against an older backend.
+    let claimId: String?
+    let evidence: [Evidence]
 
     var id: String { entityId }
 
     enum CodingKeys: String, CodingKey {
-        case entityId, entityName, filePath, snippet, sourceEpisodes
+        case entityId, entityName, filePath, snippet, sourceEpisodes, claimId, evidence
     }
 
     init(from decoder: Decoder) throws {
@@ -29,14 +34,19 @@ struct AskCitation: Codable, Identifiable, Equatable {
         filePath = try c.decodeIfPresent(String.self, forKey: .filePath) ?? ""
         snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
         sourceEpisodes = try c.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
+        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
+        evidence = try c.decodeIfPresent([Evidence].self, forKey: .evidence) ?? []
     }
 
-    init(entityId: String, entityName: String, filePath: String, snippet: String, sourceEpisodes: [String] = []) {
+    init(entityId: String, entityName: String, filePath: String, snippet: String, sourceEpisodes: [String] = [],
+         claimId: String? = nil, evidence: [Evidence] = []) {
         self.entityId = entityId
         self.entityName = entityName
         self.filePath = filePath
         self.snippet = snippet
         self.sourceEpisodes = sourceEpisodes
+        self.claimId = claimId
+        self.evidence = evidence
     }
 }
 
```

- [ ] **Step 4: Green, then the whole suite.**
`cd <worktree>/app/CicadaApp && swift test --filter "EvidenceDecodeTests|ScalarTextTests|ProvenanceAPITests" 2>&1 | tail -5` → 22 tests, 0 failures.
`swift build 2>&1 | tail -5` (no new warnings in the touched files) and `swift test 2>&1 | tail -5` → **1083 executed, 0 failures**.

- [ ] **Step 5: Commit** (the plan rides this commit).
```
cd <worktree> && git add docs/superpowers/plans/2026-09-23-provenance-ui.md \
  app/CicadaApp/Sources/CicadaApp/Models/Evidence.swift app/CicadaApp/Sources/CicadaApp/Models/Provenance.swift \
  app/CicadaApp/Sources/CicadaApp/Utilities/ScalarText.swift app/CicadaApp/Sources/CicadaApp/Services/ProvenanceAPI.swift \
  app/CicadaApp/Sources/CicadaApp/Models/Claim.swift app/CicadaApp/Sources/CicadaApp/Models/Entity.swift \
  app/CicadaApp/Sources/CicadaApp/Models/Ask.swift \
  app/CicadaApp/Tests/CicadaAppTests/EvidenceDecodeTests.swift app/CicadaApp/Tests/CicadaAppTests/ScalarTextTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProvenanceAPITests.swift \
  && git commit -m "feat(provenance-ui): read evidence and the slice-2 payloads back; one scalar-offset rule (G118 s2, P1)"
```
Body: one paragraph naming R-PU1/R-PU2 and that `Claim.CodingKeys` had been dropping `evidence` since
PR #44; end with the session's attribution trailer.

---

### Task 2: The Reader — router, in-memory cache, turns, honest banners (P2)

The Reader exists and can be opened by anything holding a `ReaderTarget`; the first entry points
arrive in Task 3. Shippable: nothing opens it yet, and nothing it adds is visible until opened.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ProvenanceRouter.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ProvenanceCache.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/CicadaMotion.swift:44, 64` (`spanReveal`)
- Modify: `app/CicadaApp/Sources/CicadaApp/CicadaApp.swift:36, 99` (inject router + cache, main window only)
- Modify: `app/CicadaApp/Sources/CicadaApp/ContentView.swift:32, 51, 83` (the `.inspector`; a bank switch closes the Reader and resets the cache, R-PU26)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/ReaderTurnsTests.swift`, `ProvenanceRouterTests.swift`

**Interfaces:**
- Produces: `Copy.Provenance` (Reader strings); `ReaderTarget` (`Focus: none | span(start,end,hash,derived) | mention(entityId) | inferred | stale`, `query`, `static evidence(_:subjectId:knownTitle:knownHarness:)`, `static best(_:subjectId:knownTitle:knownHarness:)`); `ProvenanceRouter` (`stack`, `isPresented`, `revision`, `current`, `canGoBack`, `open(_:)`, `back()`, `close()`, `maxDepth`); `LRUCache`, `ProvenanceLoad` (`loaded | gone | failed`, `value`), `ProvenanceCache` (`span(_:)`, `document(episode:focus:)`, `provenance(entityId:)`, `citations(episode:)`, `reset()`); `EvidenceSpeaker` (`agentName`, `agentOrigin`, `named`, `turnSpeaker`, `markerWords`), `ReaderTime` (`label`, `instant`, `day`, `episodeDate`), `ReaderWash`, `ReaderBlock`, `ReaderLayout` (`blocks`, `blockIndex`), `ReaderBanner`, `ReaderPresentation.resolve`, `ReaderHeader` (`captureLine`, `meta`, `markOrigin`); `ReaderInspector`, `ReaderTurnView`, `ReaderText` (`focusOpacity`, `otherOpacity`, `attributed`), `ReaderBannerView`; `CicadaMotion.spanReveal(reduceMotion:)`.
- Consumes: Task 1's models and `ProvenanceAPI`; `ConversationsViewModel.load(ids:)/canResume/resume` (`ViewModels/ConversationsViewModel.swift:45, 70, 95`); `OriginMark`, `LogoImage`, `OriginIconography.label`; `Store.toast`.

- [ ] **Step 1: Failing tests.**

`app/CicadaApp/Tests/CicadaAppTests/ReaderTurnsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Design §4.4 / §4.10 — the Reader's decisions: which turn a wash lands in,
/// who is speaking, which time is shown, and what the banner says.
final class ReaderTurnsTests: XCTestCase {

    private let utc = TimeZone(identifier: "UTC")!
    /// en_GB for clock times ("14:31" on every ICU); en_US for days — en_GB's
    /// September abbreviation differs between ICU versions ("Sep"/"Sept").
    private let gb = Locale(identifier: "en_GB")
    private let us = Locale(identifier: "en_US")

    /// `user: can we stop?\nassistant: Yes. we moved the index to sqlite-vec.`
    /// Offsets are what `evidence.turns` returns for this text (turn starts at
    /// the marker line, `contentStart` skips `role: `).
    private func conversation(harness: String? = "claude-code", origin: String? = "claude-code",
                              ts: String? = nil, focus: EpisodeFocus? = nil,
                              truncated: Bool = false) -> EpisodeText {
        let text = "user: can we stop?\nassistant: Yes. we moved the index to sqlite-vec."
        return EpisodeText(
            episode: "ep_2026-09-03_004", text: text, truncated: truncated, title: "Index choice",
            timestamp: "2026-09-03T10:00:00+00:00", harness: harness, origin: origin,
            conversationId: "ses_alpha", captureKind: "transcript",
            turns: [EpisodeTurn(index: 1, start: 0, contentStart: 6, end: 18, role: "user", marker: "user"),
                    EpisodeTurn(index: 2, start: 19, contentStart: 30, end: 68, role: "assistant",
                                marker: "assistant", speaker: "assistant", ts: ts)],
            focus: focus)
    }

    private func blocks(_ doc: EpisodeText, focus: Range<Int>?, style: ReaderWash.Style = .focus,
                        others: [Range<Int>] = []) -> [ReaderBlock] {
        ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: focus, focusStyle: style,
                            others: others, locale: gb, timeZone: utc)
    }

    // MARK: Layout

    func testTurnsCarryTheirContentWithoutTheMarkerAndAHarnessSpeaker() {
        let out = blocks(conversation(), focus: nil)
        XCTAssertEqual(out.map(\.text), ["can we stop?", "Yes. we moved the index to sqlite-vec."])
        XCTAssertEqual(out.map(\.speaker), [Copy.you, "Claude Code"])
        XCTAssertEqual(out.map(\.mark), [nil, "claude-code"], "a named agent wears its mark; the person does not")
        XCTAssertEqual(out.map(\.contentStart), [6, 30])
    }

    func testAWashLandsInsideItsTurnInLocalOffsets() {
        let doc = conversation()
        let start = ScalarText(doc.text).slice(0, 68).distance(of: "sqlite-vec")!
        let out = blocks(doc, focus: start..<(start + 10))
        XCTAssertEqual(out[0].washes, [])
        XCTAssertEqual(out[1].washes, [ReaderWash(range: (start - 30)..<(start - 20), style: .focus)])
        XCTAssertEqual(ScalarText(out[1].text).slice(start - 30, start - 20), "sqlite-vec")
        XCTAssertTrue(out[1].holdsFocus)
    }

    func testASpanCrossingATurnBoundaryIsSplitIntoTwoWashes() {
        // From "stop?" in turn 1 into "Yes." in turn 2.
        let out = blocks(conversation(), focus: 13..<34)
        XCTAssertEqual(out[0].washes, [ReaderWash(range: 7..<12, style: .focus)], "\"stop?\" — to the end of turn 1")
        XCTAssertEqual(out[1].washes, [ReaderWash(range: 0..<4, style: .focus)], "\"Yes.\" — the marker is skipped")
    }

    func testOtherSpansWashFainterAndNeverDuplicateTheFocus() {
        let out = blocks(conversation(), focus: 30..<34, others: [30..<34, 6..<9])
        XCTAssertEqual(out[0].washes, [ReaderWash(range: 0..<3, style: .other)])
        XCTAssertEqual(out[1].washes, [ReaderWash(range: 0..<4, style: .focus)])
    }

    // MARK: Times — shown only when stored

    func testATimeIsShownOnlyWhenTheEpisodeStoresOne() {
        XCTAssertEqual(blocks(conversation(), focus: nil).map(\.time), [nil, nil], "never inferred")
        let stamped = blocks(conversation(ts: "2026-09-03T14:31:00+00:00"), focus: nil)
        XCTAssertEqual(stamped.map(\.time), [nil, "14:31"])
    }

    func testTimeLabelsReadEveryShapeABankHolds() {
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00Z", locale: gb, timeZone: utc), "14:31")
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00.123+00:00", locale: gb, timeZone: utc), "14:31")
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00.123456+00:00", locale: gb, timeZone: utc), "14:31",
                       "microseconds — `episode_ids.utc_now_iso`'s own shape, and every epoch an importer converts")
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00", locale: gb, timeZone: utc), "14:31",
                       "a naive stamp is read in the viewer's zone (G114)")
        XCTAssertEqual(ReaderTime.label("00:23:41", locale: gb, timeZone: utc), "00:23:41",
                       "a meeting offset passes through")
        XCTAssertNil(ReaderTime.label(nil))
        XCTAssertNil(ReaderTime.label("   "))
        XCTAssertNil(ReaderTime.label("not a time"))
    }

    func testTheDayComesFromTheTimestampElseTheEpisodeId() {
        XCTAssertEqual(ReaderTime.day(timestamp: "2026-09-03T10:00:00Z", episode: "x", locale: us, timeZone: utc),
                       "Sep 3, 2026")
        XCTAssertEqual(ReaderTime.day(timestamp: nil, episode: "ep_2026-08-12_007", locale: us, timeZone: utc),
                       "Aug 12, 2026")
        XCTAssertNil(ReaderTime.day(timestamp: nil, episode: "media-example-com", locale: us, timeZone: utc))
    }

    // MARK: Speakers

    func testSpeakersNeverPrintARoleWordAsANameAndAMeetingSpeakerIsNeverYou() {
        func speaker(_ role: String, marker: String? = nil, name: String? = nil,
                     harness: String? = nil, origin: String? = nil) -> String {
            EvidenceSpeaker.turnSpeaker(EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 1, role: role,
                                                    marker: marker, speaker: name),
                                        harness: harness, origin: origin)
        }
        XCTAssertEqual(speaker("user", marker: "user", name: "user"), Copy.you, "an importer sidecar role is not a name")
        XCTAssertEqual(speaker("user", marker: "system"), Copy.Provenance.setupMessage)
        XCTAssertEqual(speaker("user", marker: "unknown"), Copy.Provenance.unlabelledMessage)
        XCTAssertEqual(speaker("user", marker: nil), Copy.you, "a marker-less note is the person's (R4)")
        XCTAssertEqual(speaker("assistant", harness: "codex"), "Codex")
        XCTAssertEqual(speaker("assistant", origin: "chatgpt-export"), "ChatGPT")
        XCTAssertEqual(speaker("assistant", harness: "mcp"), Copy.Provenance.theAgent, "mcp names no product")
        XCTAssertEqual(speaker("assistant"), Copy.Provenance.theAgent)
        XCTAssertEqual(speaker("speaker", name: "Speaker 2"), "Speaker 2")
        XCTAssertEqual(speaker("speaker", name: "assistant"), Copy.Provenance.someoneElse)
        XCTAssertEqual(speaker("speaker"), Copy.Provenance.someoneElse, "R-N2 — never \"You\"")
        XCTAssertEqual(speaker("page"), "")

        // The mark beside a named agent follows the SAME precedence as its name.
        XCTAssertEqual(EvidenceSpeaker.agentOrigin(harness: "codex", origin: "codex"), "codex")
        XCTAssertEqual(EvidenceSpeaker.agentOrigin(harness: nil, origin: "chatgpt-export"), "chatgpt-export",
                       "an import wears its vendor's mark")
        XCTAssertNil(EvidenceSpeaker.agentOrigin(harness: "mcp", origin: "mcp"), "no product named, no mark")
        XCTAssertNil(EvidenceSpeaker.agentOrigin(harness: nil, origin: "telegram"))
    }

    // MARK: Presentation — the honesty rules (§4.9)

    private func present(_ focus: ReaderTarget.Focus, doc: EpisodeText) -> ReaderPresentation {
        ReaderPresentation.resolve(target: ReaderTarget(episode: doc.episode, focus: focus), doc: doc,
                                   textCount: ScalarText(doc.text).count)
    }

    func testAStaleSpanNeverWashesButStillLandsNearItsWords() {
        let doc = conversation(focus: EpisodeFocus(start: nil, end: nil, kind: .assistant, stale: true))
        let p = present(.span(start: 58, end: 68, hash: "old", derived: false), doc: doc)
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.stale])
        XCTAssertEqual(p.landing, 58)
    }

    func testAGrownSpanWashesAndSaysTheConversationContinued() {
        let doc = conversation(focus: EpisodeFocus(start: 58, end: 68, kind: .assistant, grown: true))
        let p = present(.span(start: 58, end: 68, hash: "h", derived: false), doc: doc)
        XCTAssertEqual(p.focus, 58..<68)
        XCTAssertEqual(p.focusStyle, .focus)
        XCTAssertEqual(p.banners, [.grown])
    }

    func testADerivedTargetBoldsAndSaysSoEvenWhenTheServerSawOffsets() {
        let doc = conversation(focus: EpisodeFocus(start: 58, end: 68, kind: .assistant))
        let p = present(.span(start: 58, end: 68, hash: nil, derived: true), doc: doc)
        XCTAssertEqual(p.focusStyle, .mention, "an inbox cause found by name stays found by name (R-PB16)")
        XCTAssertEqual(p.banners, [.derived])
    }

    func testAMentionTargetUsesTheServersDerivedFocusOrSaysItFoundNothing() {
        let found = conversation(focus: EpisodeFocus(start: 58, end: 68, kind: .derived, derived: true))
        XCTAssertEqual(present(.mention(entityId: "sqlite-vec"), doc: found).focus, 58..<68)
        XCTAssertEqual(present(.mention(entityId: "sqlite-vec"), doc: found).banners, [.derived])
        let missed = conversation(focus: nil)
        let p = present(.mention(entityId: "bob-example"), doc: missed)
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.notFound])
        XCTAssertNil(p.landing, "nothing found opens at the top")
    }

    func testInferredAndStaleTargetsOpenAtTheTopUnderTheirBanner() {
        XCTAssertEqual(present(.inferred, doc: conversation()).banners, [.inferred])
        XCTAssertEqual(present(.stale, doc: conversation()).banners, [.stale])
        XCTAssertNil(present(.inferred, doc: conversation()).landing)
    }

    func testWordsPastTheCapAreNotWashedAndTheTruncationIsSaid() {
        let doc = conversation(focus: EpisodeFocus(start: 500, end: 510), truncated: true)
        let p = present(.span(start: 500, end: 510, hash: nil, derived: false), doc: doc)
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.truncated])
    }

    // MARK: Header

    func testTheCaptureLineIsHonestAboutWhatWasKept() {
        XCTAssertEqual(ReaderHeader.captureLine(conversation()), Copy.Provenance.captureHonesty)
        let imported = EpisodeText(episode: "ep_1", text: "user: hi", origin: "chatgpt-export")
        XCTAssertEqual(ReaderHeader.captureLine(imported), Copy.Provenance.importedFrom("ChatGPT"))
        XCTAssertNil(ReaderHeader.captureLine(EpisodeText(episode: "ep_1", text: "a note", origin: "telegram")))
        XCTAssertNil(ReaderHeader.captureLine(EpisodeText(episode: "ep_1", text: "water the plants", origin: "telegram",
                                                          captureKind: "reminder")),
                     "a Telegram /remind note is stamped too, and holds exactly what was sent — the line would lie")
        XCTAssertNil(ReaderHeader.captureLine(EpisodeText(episode: "media-x", kind: "page", text: "t")))
    }

    func testTheMetaLineNamesTheAgentTheDayAndTheTurns() {
        XCTAssertEqual(ReaderHeader.meta(conversation(), locale: us, timeZone: utc),
                       "Claude Code · Sep 3, 2026 · 2 turns")
        let page = EpisodeText(episode: "media-example-com", kind: "page", text: "t",
                               turns: [EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 1, role: "page")])
        XCTAssertEqual(ReaderHeader.meta(page, locale: us, timeZone: utc), Copy.Provenance.fromThePage)
    }
}

private extension String {
    /// Scalar offset of `needle` — test-only, so fixtures can say "where
    /// sqlite-vec is" instead of hard-coding a number a reader must re-count.
    func distance(of needle: String) -> Int? {
        guard let r = range(of: needle) else { return nil }
        return unicodeScalars.distance(from: unicodeScalars.startIndex, to: r.lowerBound)
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/ProvenanceRouterTests.swift` (with `FakeProvenanceAPI`):

```swift
import XCTest
@testable import CicadaApp

/// Design §1.4 — one Reader, one stack; and the in-memory cache behind it
/// (R-PB11: never a Store domain, ETags for this cache only).
@MainActor
final class ProvenanceRouterTests: XCTestCase {

    // MARK: Targets

    func testAnEvidenceSpanOpensOnItsWordsAndReasoningOpensUnderItsBanner() {
        let span = Evidence(episode: "ep_1", start: 3, end: 9, kind: .user, hash: "h")
        XCTAssertEqual(ReaderTarget.evidence(span, subjectId: "alpha-project")?.focus,
                       .span(start: 3, end: 9, hash: "h", derived: false))
        let inferred = Evidence(episode: "ep_1", start: -1, end: -1, kind: .reasoning, hash: "h")
        XCTAssertEqual(ReaderTarget.evidence(inferred, subjectId: nil)?.focus, .inferred)
        XCTAssertNil(ReaderTarget.evidence(Evidence(episode: "", start: -1, end: -1, kind: .reasoning),
                                           subjectId: nil), "reasoning with no document has nowhere to open")
    }

    func testABestQuoteOpensExactlyBoldOrUnderTheStaleBanner() {
        let asserted = ProvenanceSpan(episode: "ep_1", start: 5, end: 9, hash: "h", kind: .assistant, excerpt: "")
        XCTAssertEqual(ReaderTarget.best(asserted, subjectId: "a").focus,
                       .span(start: 5, end: 9, hash: "h", derived: false))
        let derived = ProvenanceSpan(episode: "ep_1", start: 5, end: 9, hash: "whole", kind: .derived,
                                     excerpt: "", derived: true)
        XCTAssertEqual(ReaderTarget.best(derived, subjectId: "a").focus,
                       .span(start: 5, end: 9, hash: nil, derived: true),
                       "a derived match's hash is the whole text's — never sent as a span hash")
        let stale = ProvenanceSpan(episode: "ep_1", start: nil, end: nil, kind: .user, excerpt: "", stale: true)
        XCTAssertEqual(ReaderTarget.best(stale, subjectId: "a").focus, .stale)
    }

    func testTheQueryIsTheOneTheServerTakes() {
        XCTAssertEqual(ReaderTarget(episode: "e", focus: .mention(entityId: "a")).query, .mention(entityId: "a"))
        XCTAssertEqual(ReaderTarget(episode: "e", focus: .inferred).query, ReaderFocusQuery.none)
        XCTAssertEqual(ReaderTarget(episode: "e", focus: .span(start: 1, end: 2, hash: nil, derived: true)).query,
                       .span(start: 1, end: 2, hash: nil))
    }

    // MARK: Router

    func testOpenPresentsPushesAndBumpsTheRevisionEvenForTheSameTarget() {
        let router = ProvenanceRouter()
        let a = ReaderTarget(episode: "ep_a")
        router.open(a)
        XCTAssertTrue(router.isPresented)
        XCTAssertEqual(router.stack, [a])
        let r1 = router.revision
        router.open(a)
        XCTAssertEqual(router.stack, [a], "the same target is not pushed twice")
        XCTAssertGreaterThan(router.revision, r1, "but a presenter still hears it")
    }

    func testBackPopsAndCloseKeepsTheStackUntilTheNextOpen() {
        let router = ProvenanceRouter()
        router.open(ReaderTarget(episode: "ep_a"))
        router.open(ReaderTarget(episode: "ep_b"))
        XCTAssertTrue(router.canGoBack)
        router.back()
        XCTAssertEqual(router.current?.episode, "ep_a")
        router.back()
        XCTAssertEqual(router.current?.episode, "ep_a", "never pops the last target")
        router.close()
        XCTAssertFalse(router.isPresented)
        XCTAssertEqual(router.current?.episode, "ep_a", "no empty Reader during the closing animation")
        router.open(ReaderTarget(episode: "ep_c"))
        XCTAssertEqual(router.stack.map(\.episode), ["ep_c"], "a fresh open from closed starts a fresh trail")
    }

    func testTheTrailIsCapped() {
        let router = ProvenanceRouter()
        for i in 0..<(ProvenanceRouter.maxDepth + 5) { router.open(ReaderTarget(episode: "ep_\(i)")) }
        XCTAssertEqual(router.stack.count, ProvenanceRouter.maxDepth)
        XCTAssertEqual(router.current?.episode, "ep_\(ProvenanceRouter.maxDepth + 4)")
    }

    // MARK: LRU

    func testTheLRUEvictsTheLeastRecentlyRead() {
        var lru = LRUCache<String, Int>(capacity: 2)
        lru.set("a", 1)
        lru.set("b", 2)
        XCTAssertEqual(lru.get("a"), 1)   // a is now the most recent
        lru.set("c", 3)
        XCTAssertNil(lru.get("b"))
        XCTAssertEqual(lru.get("a"), 1)
        XCTAssertEqual(lru.get("c"), 3)
        XCTAssertEqual(lru.count, 2)
    }

    // MARK: Cache

    func testASpanIsFetchedOnceAndServedFromMemory() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let ev = Evidence(episode: "ep_1", start: 1, end: 2, kind: .user, hash: "h")
        _ = await cache.span(ev)
        _ = await cache.span(ev)
        XCTAssertEqual(api.spanCalls, 1)
    }

    func testADocumentRevalidatesWithItsETagAndKeepsTheValueOnA304() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let first = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(first.value?.title, "Index choice")
        api.textNotModified = true
        let second = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(second.value?.title, "Index choice")
        XCTAssertEqual(api.lastTextETag, "\"v1\"", "the stored validator is sent back")
    }

    func testA404IsGoneEvenWithSomethingCachedAndAnyOtherFailureIsLastKnownGood() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        _ = await cache.document(episode: "ep_1", focus: .none)
        api.textError = APIError.serverUnreachable
        let offline = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(offline.value?.title, "Index choice", "never blank on a transport failure")
        api.textError = APIError.httpError(404, "gone")
        let gone = await cache.document(episode: "ep_1", focus: .none)
        if case .gone = gone {} else { XCTFail("a 404 must read as gone, not as the cached copy") }
    }

    // MARK: A span the document no longer reaches (R-PU25)

    func testASpanPastTheEndOfARewrittenDocumentOpensTheWholeDocumentAsStale() async {
        let api = FakeProvenanceAPI()
        // `/text` 422s a pair past the end (`provenance.SpanOutOfRange`) once a
        // rewrite made the document shorter than the span.
        api.spanFocusError = APIError.httpError(422, "span [900, 951) is outside the document (length 8)")
        let cache = ProvenanceCache(api: api)
        let load = await cache.document(episode: "ep_1", focus: .span(start: 900, end: 951, hash: "h"))
        XCTAssertEqual(load.value?.title, "Index choice", "the words moved; the conversation did not vanish")
        XCTAssertEqual(load.value?.focus?.stale, true)
        XCTAssertNil(load.value?.focus?.range, "R-PB2 — stale never washes")
        guard let doc = load.value else { return XCTFail("the whole document opens") }
        let p = ReaderPresentation.resolve(
            target: ReaderTarget(episode: "ep_1", focus: .span(start: 900, end: 951, hash: "h", derived: false)),
            doc: doc, textCount: ScalarText(doc.text).count)
        XCTAssertEqual(p.banners, [.stale])
        XCTAssertEqual(p.landing, 7, "lands on the last words the document still has")
    }

    func testASpanPreviewPastTheEndReadsAsStaleNotAsAFailure() async {
        let api = FakeProvenanceAPI()
        api.spanError = APIError.httpError(422, "span [900, 951) is outside the document (length 8)")
        let cache = ProvenanceCache(api: api)
        let load = await cache.span(Evidence(episode: "ep_1", start: 900, end: 951, kind: .user, hash: "h"))
        XCTAssertEqual(load.value?.stale, true)
        XCTAssertEqual(load.value?.text, "", "no words to quote — the preview says they moved")
    }

    // MARK: A bank switch (R-PU26)

    func testResetForgetsEverythingSoAnotherBanksIdsAreNeverServed() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let ev = Evidence(episode: "ep_1", start: 1, end: 2, kind: .user, hash: "h")
        _ = await cache.span(ev)
        _ = await cache.document(episode: "ep_1", focus: .none)
        cache.reset()
        _ = await cache.span(ev)
        XCTAssertEqual(api.spanCalls, 2, "episode ids restart every day in every bank — a cached span is refetched")
        api.textError = APIError.serverUnreachable
        let offline = await cache.document(episode: "ep_1", focus: .none)
        if case .failed = offline {} else { XCTFail("no last-known-good copy survives a bank switch") }
        XCTAssertNil(api.lastTextETag, "the old bank's validator is forgotten too")
    }
}

/// A scripted `ProvenanceAPI` for the cache and view-model tests.
final class FakeProvenanceAPI: ProvenanceAPI, @unchecked Sendable {
    var spanCalls = 0
    var spanError: Error?
    var textNotModified = false
    var textError: Error?
    /// Thrown only for a `.span` focus — a document that still exists but no
    /// longer reaches the asked-for offsets.
    var spanFocusError: Error?
    var lastTextETag: String?
    var provenance = EntityProvenance(entityId: "alpha-project")
    var citations = EpisodeCitations(episode: "ep_1")

    func fetchEpisodeSpan(episode: String, start: Int, end: Int, hash: String?) async throws -> EpisodeSpan {
        spanCalls += 1
        if let spanError { throw spanError }
        let json = #"{"episode": "\#(episode)", "text": "x", "start": \#(start), "end": \#(end)}"#
        return try JSONDecoder().decode(EpisodeSpan.self, from: Data(json.utf8))
    }

    func fetchEpisodeText(episode: String, focus: ReaderFocusQuery, etag: String?) async throws
        -> Conditional<EpisodeText> {
        lastTextETag = etag
        if case .span = focus, let spanFocusError { throw spanFocusError }
        if let textError { throw textError }
        if textNotModified { return Conditional(value: nil, etag: etag, notModified: true) }
        return Conditional(value: EpisodeText(episode: episode, text: "user: hi", title: "Index choice"),
                           etag: "\"v1\"", notModified: false)
    }

    func fetchEntityProvenance(entityId: String, etag: String?) async throws -> Conditional<EntityProvenance> {
        Conditional(value: provenance, etag: "\"p1\"", notModified: false)
    }

    func fetchEpisodeCitations(episode: String, etag: String?) async throws -> Conditional<EpisodeCitations> {
        Conditional(value: citations, etag: "\"c1\"", notModified: false)
    }
}
```

- [ ] **Step 2: Watch them fail.**
`cd <worktree>/app/CicadaApp && swift test --filter "ReaderTurnsTests|ProvenanceRouterTests" 2>&1 | tail -20`
→ compile errors naming `ReaderLayout`, `ReaderTarget`, `ProvenanceRouter`, `ProvenanceCache`, `Copy.Provenance`.

- [ ] **Step 3: Implement.** Create `Theme/Copy+Provenance.swift`:

```swift
import Foundation

/// G118 slice 2 — every sentence the provenance viewer says, in one place,
/// written for someone who has never heard the words "span", "episode" or
/// "hash" (the brief: plain and friendly, no jargon). Its own file rather than
/// more lines in `Copy.swift` because four round-3 tracks edit that file in
/// parallel; an `extension` here merges with none of them.
///
/// The honesty rules of design §4.9 live in these strings as much as in the
/// code: a derived match is never "You said", a stale quote never claims to
/// be where it was, and a hook-captured conversation never pretends to be the
/// whole session.
extension Copy {
    enum Provenance {
        // MARK: The Reader (§4.4)

        static let untitled = "Untitled conversation"
        /// G105 — the Stop hook keeps the person's turns and each final reply,
        /// never tool calls or code (`transcript_extract.py`). Said once, in
        /// the header, so the Reader never implies it shows the whole session.
        static let captureHonesty = "Your words and each final reply. Tool calls and code aren't kept."
        static func importedFrom(_ vendor: String) -> String { "Imported from a \(vendor) export" }

        static let stale = "This conversation changed after this was noted. The words may have moved."
        static let grown = "The conversation continued after this was noted."
        static let inferred = "Cicada inferred this. No sentence says it in so many words."
        /// The owner's wording (2026-09-23 brief): a derived match is labelled
        /// for what it is — found by searching, not quoted by a contributor.
        static let derived = "Found by searching the conversation. This was noted before Cicada kept exact quotes."
        static let notFound = "Cicada couldn't find the name in this conversation, so it opens at the top."
        static let truncated = "This conversation is very long, so only the first part is shown."
        static let gone = "This conversation isn't in this bank any more."
        static let failed = "Couldn't open this conversation."
        static let empty = "Nothing was captured in this conversation."
        static let retry = "Try again"

        static let theAgent = "The agent"
        static let setupMessage = "Setup message"
        static let unlabelledMessage = "Unlabelled message"
        static let someoneElse = "Someone else"
        static let fromThePage = "From the page"

        static func turn(_ n: Int) -> String { "turn \(n)" }
        static func turnCount(_ n: Int) -> String {
            n == 1 ? "1 turn" : "\(UsageFormat.count(n)) turns"
        }
        static let resume = "Resume"
        static let close = "Close the conversation"
        static let back = "Back to the previous conversation"
        static func citedPassage(_ text: String) -> String { "Cited passage: \(text)" }
    }
}
```

Create `Views/Provenance/ProvenanceRouter.swift`:

```swift
import Foundation
import Observation

/// Where the Reader should open, and what it should land on (design §1.4,
/// §4.4). Every "where did this come from" affordance — an evidence chip, a
/// provenance row, an inbox cause, an Ask citation, and later a palette hit
/// (P6) — builds one of these and hands it to `ProvenanceRouter.open(_:)`.
///
/// `.conversation(id)` from the design is deliberately absent: the Reader
/// reads `/episodes/{id}/text`, and a conversation id cannot be turned into
/// an episode id without a server field `ConversationSummary` does not carry
/// (plan R-PU5). A caller that knows the conversation also knows one of its
/// episodes, or does not offer the button.
struct ReaderTarget: Hashable, Identifiable {
    enum Focus: Hashable {
        /// Open at the top.
        case none
        /// A stored span. `hash` rides along so the server can say `grown` or
        /// `stale` (A7); `derived` marks a name match found at read — it lands
        /// and bolds, never washes, and never reads "You said" (§4.9).
        case span(start: Int, end: Int, hash: String?, derived: Bool)
        /// Let the server find the entity's name (`?focus=`): the legacy-claim
        /// path, always derived (R-PB9).
        case mention(entityId: String)
        /// A `reasoning` entry: the contributor inferred it here, and no
        /// sentence says so. Opens at the top under that banner.
        case inferred
        /// A best quote whose conversation changed since (R-PB2: a stale span
        /// travels without offsets). Opens at the top under the stale banner.
        case stale
    }

    let episode: String
    let focus: Focus
    /// The entity whose beliefs brought the person here. The navigator
    /// (P4) steps through the spans this entity's claims cite.
    let subjectId: String?
    /// Header fields a caller already holds, shown while the text loads
    /// (§4.4 "Loading: the header from the target's known fields").
    let knownTitle: String?
    let knownHarness: String?

    init(episode: String, focus: Focus = .none, subjectId: String? = nil,
         knownTitle: String? = nil, knownHarness: String? = nil) {
        self.episode = episode
        self.focus = focus
        self.subjectId = subjectId
        self.knownTitle = knownTitle
        self.knownHarness = knownHarness
    }

    var id: String { "\(episode)|\(focus)|\(subjectId ?? "")" }

    /// What `/episodes/{id}/text` is asked for. `.inferred`/`.stale` ask for
    /// nothing: there is no offset to judge.
    var query: ReaderFocusQuery {
        switch focus {
        case let .span(start, end, hash, _): .span(start: start, end: end, hash: hash)
        case let .mention(entityId): .mention(entityId: entityId)
        case .none, .inferred, .stale: .none
        }
    }

    /// One stored evidence entry → where to open. A span lands on its words;
    /// a `reasoning` entry that still names its document opens that document
    /// under the "inferred" banner; anything else has nowhere to go.
    static func evidence(_ ev: Evidence, subjectId: String?, knownTitle: String? = nil,
                         knownHarness: String? = nil) -> ReaderTarget? {
        guard !ev.episode.isEmpty else { return nil }
        if ev.isSpan {
            return ReaderTarget(episode: ev.episode,
                                focus: .span(start: ev.start, end: ev.end, hash: ev.hash, derived: false),
                                subjectId: subjectId, knownTitle: knownTitle, knownHarness: knownHarness)
        }
        return ReaderTarget(episode: ev.episode, focus: .inferred, subjectId: subjectId,
                            knownTitle: knownTitle, knownHarness: knownHarness)
    }

    /// A provenance row's best quote (R-PB8) → where to open. Asserted and
    /// grown quotes land exactly; a derived one lands bold; a stale one opens
    /// at the top under the stale banner, because its offsets were withheld.
    static func best(_ best: ProvenanceSpan, subjectId: String?, knownTitle: String? = nil,
                     knownHarness: String? = nil) -> ReaderTarget {
        let focus: Focus
        if best.stale {
            focus = .stale
        } else if let start = best.start, let end = best.end, end > start {
            focus = .span(start: start, end: end, hash: best.derived ? nil : best.hash, derived: best.derived)
        } else {
            focus = .none
        }
        return ReaderTarget(episode: best.episode, focus: focus, subjectId: subjectId,
                            knownTitle: knownTitle, knownHarness: knownHarness)
    }
}

/// The Reader's navigation (design §1.4): a stack of targets, one inspector.
/// Injected into the main window's environment (`CicadaApp`) and read as an
/// OPTIONAL environment value by every chip, so a view hosted anywhere else
/// (a preview, a test) renders its chip without a click-through rather than
/// trapping on a missing environment object.
@Observable
@MainActor
final class ProvenanceRouter {
    /// A reading trail, not a history: capped so an afternoon of clicking
    /// never grows it without bound.
    static let maxDepth = 20

    private(set) var stack: [ReaderTarget] = []
    /// Bound to `.inspector(isPresented:)`. The inspector's own toggle writes
    /// `false` here; the stack is kept so the closing animation never shows
    /// an empty Reader, and the next `open` from closed starts a fresh one.
    var isPresented = false
    /// Bumped on every `open`, including re-opening the target already on
    /// top — the one signal a presenter (the Ask sheet, T6) can watch to get
    /// out of the Reader's way.
    private(set) var revision = 0

    var current: ReaderTarget? { stack.last }
    var canGoBack: Bool { stack.count > 1 }

    func open(_ target: ReaderTarget) {
        if !isPresented { stack = [] }
        if stack.last != target { stack.append(target) }
        if stack.count > Self.maxDepth { stack.removeFirst(stack.count - Self.maxDepth) }
        isPresented = true
        revision &+= 1
    }

    func back() {
        guard canGoBack else { return }
        stack.removeLast()
    }

    func close() { isPresented = false }
}
```

Create `Views/Provenance/ProvenanceCache.swift`:

```swift
import Foundation
import Observation

/// A least-recently-used map. Pure and tested: the hover preview's span
/// cache is bounded by the design (§4.2 — 256 entries keyed by
/// `(episode, start, end, hash)`), and so is everything else here, because
/// these payloads live in memory only (R-PB11 — none is a Store domain).
struct LRUCache<Key: Hashable, Value> {
    let capacity: Int
    private var storage: [Key: Value] = [:]
    private var order: [Key] = []   // least recent first

    init(capacity: Int) { self.capacity = max(1, capacity) }

    var count: Int { storage.count }

    /// Reads and marks `key` most recent.
    mutating func get(_ key: Key) -> Value? {
        guard let value = storage[key] else { return nil }
        touch(key)
        return value
    }

    mutating func set(_ key: Key, _ value: Value) {
        storage[key] = value
        touch(key)
        while order.count > capacity {
            storage[order.removeFirst()] = nil
        }
    }

    mutating func remove(_ key: Key) {
        storage[key] = nil
        order.removeAll { $0 == key }
    }

    private mutating func touch(_ key: Key) {
        order.removeAll { $0 == key }
        order.append(key)
    }
}

/// What a provenance fetch came back with. `gone` is a 404 — the document or
/// entity is not in this bank (any more), which every surface says in words
/// rather than as an error (§4.4 States).
enum ProvenanceLoad<T> {
    case loaded(T)
    case gone
    case failed(String)

    var value: T? {
        if case let .loaded(v) = self { return v }
        return nil
    }
}

/// The provenance viewer's in-memory cache (G118 slice 2). One for the app,
/// owned by `CicadaApp` as `@State` (like `appRouter`) and injected into the
/// main window scene beside `ProvenanceRouter`.
///
/// **Never a Store domain** (R-PB11, design K10): these payloads are fetched
/// on demand, so there is no `SnapshotCache` entry and no `VersionVector`
/// mapping to ship. ETagged payloads are revalidated on every ask — a 304 is
/// cheap and keeps "Where this came from" honest after a Sleep cycle — and a
/// failure keeps the last-known-good value, the app's never-blank rule.
///
/// **Not keyed by bank, so a bank switch empties it** (`reset()`, R-PU26):
/// episode ids restart at `_001` every day in every bank, so without the
/// reset another bank's document could be served — or kept as
/// last-known-good — for an id this bank also has.
@Observable
@MainActor
final class ProvenanceCache {
    static let spanCapacity = 256
    static let documentCapacity = 12
    static let provenanceCapacity = 64
    static let citationsCapacity = 24

    struct SpanKey: Hashable { let episode: String; let start: Int; let end: Int; let hash: String }
    struct DocumentKey: Hashable { let episode: String; let focus: ReaderFocusQuery }
    private struct Tagged<T> { let etag: String?; let value: T }

    @ObservationIgnored private let api: any ProvenanceAPI
    @ObservationIgnored private var spans = LRUCache<SpanKey, EpisodeSpan>(capacity: ProvenanceCache.spanCapacity)
    @ObservationIgnored private var documents =
        LRUCache<DocumentKey, Tagged<EpisodeText>>(capacity: ProvenanceCache.documentCapacity)
    @ObservationIgnored private var provenances =
        LRUCache<String, Tagged<EntityProvenance>>(capacity: ProvenanceCache.provenanceCapacity)
    @ObservationIgnored private var citationSets =
        LRUCache<String, Tagged<EpisodeCitations>>(capacity: ProvenanceCache.citationsCapacity)

    init(api: any ProvenanceAPI = APIClient.shared) { self.api = api }

    /// Forget everything — called on a bank switch (`ContentView`, R-PU26).
    func reset() {
        spans = LRUCache(capacity: Self.spanCapacity)
        documents = LRUCache(capacity: Self.documentCapacity)
        provenances = LRUCache(capacity: Self.provenanceCapacity)
        citationSets = LRUCache(capacity: Self.citationsCapacity)
    }

    /// The hover preview's words. No ETag by design (slice-1 R9), so a hit is
    /// served from memory without a request.
    func span(_ ev: Evidence) async -> ProvenanceLoad<EpisodeSpan> {
        let key = SpanKey(episode: ev.episode, start: ev.start, end: ev.end, hash: ev.hash)
        if let hit = spans.get(key) { return .loaded(hit) }
        do {
            let value = try await api.fetchEpisodeSpan(episode: ev.episode, start: ev.start, end: ev.end,
                                                       hash: ev.hash.isEmpty ? nil : ev.hash)
            spans.set(key, value)
            return .loaded(value)
        } catch let error where Self.isOutOfRange(error) {
            // R-PU25 — the document was rewritten SHORTER than this span's end
            // (a page description, a re-synced file), so `/span` answers 422.
            // The words moved; they did not fail to load — `/citations`
            // already reads `end > len(text)` as stale. Not cached: the next
            // Sleep may mint the span afresh.
            return .loaded(EpisodeSpan(episode: ev.episode, start: ev.start, end: ev.end, stale: true,
                                       kind: ev.kind))
        } catch {
            return Self.classify(error, cached: nil as EpisodeSpan?)
        }
    }

    func document(episode: String, focus: ReaderFocusQuery) async -> ProvenanceLoad<EpisodeText> {
        let key = DocumentKey(episode: episode, focus: focus)
        let cached = documents.get(key)
        do {
            let result = try await api.fetchEpisodeText(episode: episode, focus: focus, etag: cached?.etag)
            if result.notModified, let cached { return .loaded(cached.value) }
            guard let value = result.value else { return Self.classify(nil, cached: cached?.value) }
            documents.set(key, Tagged(etag: result.etag, value: value))
            return .loaded(value)
        } catch {
            if Self.isGone(error) || Self.isOutOfRange(error) { documents.remove(key) }
            // R-PU25 — `/text` 422s a stored span the document no longer
            // reaches (`provenance.SpanOutOfRange`). The conversation is still
            // here, so open ALL of it under the stale banner rather than
            // "Couldn't open": re-ask with no focus and mark the focus stale
            // (no offsets — R-PB2, so nothing washes).
            if case .span = focus, Self.isOutOfRange(error) {
                return Self.markedStale(await document(episode: episode, focus: .none))
            }
            return Self.classify(error, cached: cached?.value)
        }
    }

    func provenance(entityId: String) async -> ProvenanceLoad<EntityProvenance> {
        let cached = provenances.get(entityId)
        do {
            let result = try await api.fetchEntityProvenance(entityId: entityId, etag: cached?.etag)
            if result.notModified, let cached { return .loaded(cached.value) }
            guard let value = result.value else { return Self.classify(nil, cached: cached?.value) }
            provenances.set(entityId, Tagged(etag: result.etag, value: value))
            return .loaded(value)
        } catch {
            if Self.isGone(error) { provenances.remove(entityId) }
            return Self.classify(error, cached: cached?.value)
        }
    }

    func citations(episode: String) async -> ProvenanceLoad<EpisodeCitations> {
        let cached = citationSets.get(episode)
        do {
            let result = try await api.fetchEpisodeCitations(episode: episode, etag: cached?.etag)
            if result.notModified, let cached { return .loaded(cached.value) }
            guard let value = result.value else { return Self.classify(nil, cached: cached?.value) }
            citationSets.set(episode, Tagged(etag: result.etag, value: value))
            return .loaded(value)
        } catch {
            if Self.isGone(error) { citationSets.remove(episode) }
            return Self.classify(error, cached: cached?.value)
        }
    }

    private static func isGone(_ error: Error) -> Bool {
        if case APIError.httpError(404, _) = error { return true }
        return false
    }

    /// 422 — offsets outside the document (`/span` and `/text` both refuse a
    /// pair past the end). Only ever about offsets: an id is 404, never 422.
    private static func isOutOfRange(_ error: Error) -> Bool {
        if case APIError.httpError(422, _) = error { return true }
        return false
    }

    /// The whole document re-labelled as a stale landing (R-PU25):
    /// `ReaderPresentation` then says "the words may have moved" and lands as
    /// near the old offset as the text still reaches.
    private static func markedStale(_ load: ProvenanceLoad<EpisodeText>) -> ProvenanceLoad<EpisodeText> {
        guard case let .loaded(doc) = load else { return load }
        return .loaded(EpisodeText(
            episode: doc.episode, kind: doc.kind, text: doc.text, length: doc.length, hash: doc.hash,
            truncated: doc.truncated, title: doc.title, timestamp: doc.timestamp, harness: doc.harness,
            origin: doc.origin, conversationId: doc.conversationId, captureKind: doc.captureKind,
            turns: doc.turns, focus: EpisodeFocus(start: nil, end: nil, stale: true)))
    }

    /// A 404 is `gone` even when something was cached — the bank no longer
    /// has it, and saying otherwise would be the stale-highlight bug in
    /// another shape. Any other failure serves last-known-good if there is one.
    private static func classify<T>(_ error: Error?, cached: T?) -> ProvenanceLoad<T> {
        if let error, isGone(error) { return .gone }
        if let cached { return .loaded(cached) }
        return .failed(error?.localizedDescription ?? "empty response")
    }
}
```

Create `Views/Provenance/ReaderModel.swift`:

```swift
import Foundation

// The Reader's decisions, pure and tested (design §4.4, §4.10
// `ReaderTurnsTests`), so `ReaderInspector` is a renderer: who is speaking,
// what to wash, what to say about it, and where to land.

// MARK: - Who is speaking

enum EvidenceSpeaker {
    /// The words the one marker parser matches (`evidence._TURN_RE`). The
    /// chat importer's `turns` sidecar stores the ROLE as `speaker`
    /// (`conversations._turn_stamps`), so a sidecar `speaker` that is one of
    /// these is a role, not a name, and must never print as "user said".
    static let markerWords: Set<String> = ["user", "human", "assistant", "ai", "system", "unknown"]

    /// A product name for the agent in a conversation, or nil when nothing
    /// says which agent it was. The harness wins (a Stop-hook or MCP episode
    /// stamps it); an imported export names its vendor; `mcp`/`unknown` name
    /// no product, so they fall through to "The agent". Never the MODEL:
    /// conversation `model` is reserved-null (§4.9) and "who spoke" is not
    /// "who wrote the belief".
    static func agentName(harness: String?, origin: String?) -> String? {
        if let h = harness?.trimmingCharacters(in: .whitespaces), !h.isEmpty, h != "unknown", h != "mcp" {
            return OriginIconography.label(for: h)
        }
        switch origin {
        case "claude-export": return "Claude"
        case "chatgpt-export": return "ChatGPT"
        case "gemini-export": return "Gemini"
        default: return nil
        }
    }

    /// The origin id whose mark belongs beside `agentName`'s words — the same
    /// precedence, so a label and its mark never disagree, and a named service
    /// always wears its real mark (the round-3 brief: "use logos whenever
    /// possible"). An import's mark is its vendor's (`chatgpt-export` →
    /// the ChatGPT mark, `OriginIconography.logoName`); nil when no agent is
    /// named.
    static func agentOrigin(harness: String?, origin: String?) -> String? {
        if let h = harness?.trimmingCharacters(in: .whitespaces), !h.isEmpty, h != "unknown", h != "mcp" {
            return h
        }
        switch origin {
        case "claude-export", "chatgpt-export", "gemini-export": return origin
        default: return nil
        }
    }

    /// A real name from a meeting sidecar, or nil. Role words are not names.
    static func named(_ speaker: String?) -> String? {
        guard let s = speaker?.trimmingCharacters(in: .whitespaces), !s.isEmpty,
              !markerWords.contains(s.lowercased()) else { return nil }
        return s
    }

    /// The speaker line over one turn. R4 counts `system` and `unknown`
    /// markers as the person's side (so a chip there reads "You said"); the
    /// Reader is allowed to be more precise about what the line actually was.
    /// A meeting speaker is never "You" (R-N2): with no confirmed name it is
    /// "Someone else".
    static func turnSpeaker(_ turn: EpisodeTurn, harness: String?, origin: String?) -> String {
        switch turn.role {
        case "assistant":
            return agentName(harness: harness, origin: origin) ?? Copy.Provenance.theAgent
        case "page":
            return ""
        case "speaker":
            return named(turn.speaker) ?? Copy.Provenance.someoneElse
        default:
            switch turn.marker {
            case "system": return Copy.Provenance.setupMessage
            case "unknown": return Copy.Provenance.unlabelledMessage
            default: return Copy.you
            }
        }
    }
}

// MARK: - Times (only ever the stored one)

enum ReaderTime {
    /// A turn's time as the Reader prints it, or nil. Only a time the episode
    /// STORES is shown (§4.4 — "No time is ever inferred"): an aware ISO stamp
    /// becomes a short local clock time; a naive one (G114: a bank holds naive
    /// and aware stamps side by side) is read in the viewer's zone, as it was
    /// written; a meeting offset ("00:23:41") is already what a person would
    /// say and passes through.
    static func label(_ ts: String?, locale: Locale = .autoupdatingCurrent,
                      timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        guard let raw = ts?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else { return nil }
        if raw.range(of: #"^\d{1,2}:\d{2}(:\d{2})?$"#, options: .regularExpression) != nil { return raw }
        guard let date = instant(raw, timeZone: timeZone) else { return nil }
        var style = Date.FormatStyle(date: .omitted, time: .shortened)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    /// An ISO stamp in any of the shapes a bank holds, or nil.
    static func instant(_ raw: String, timeZone: TimeZone = .autoupdatingCurrent) -> Date? {
        let aware = ISO8601DateFormatter()
        aware.formatOptions = [.withInternetDateTime]
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = aware.date(from: raw) ?? fractional.date(from: raw) { return d }
        let naive = DateFormatter()
        naive.locale = Locale(identifier: "en_US_POSIX")
        naive.timeZone = timeZone
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            naive.dateFormat = format
            if let d = naive.date(from: raw) { return d }
        }
        return nil
    }

    /// "3 Sep 2026" for the header's meta line, from the episode's timestamp
    /// or, failing that, the date in its id (`ep_YYYY-MM-DD_nnn`, G114).
    static func day(timestamp: String?, episode: String, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent, withYear: Bool = true) -> String? {
        let date = timestamp.flatMap { instant($0, timeZone: timeZone) } ?? episodeDate(episode, timeZone: timeZone)
        guard let date else { return nil }
        var style = withYear ? Date.FormatStyle().day().month(.abbreviated).year()
                             : Date.FormatStyle().day().month(.abbreviated)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    /// The day an episode id was minted on, or nil for a page id.
    static func episodeDate(_ episode: String, timeZone: TimeZone = .autoupdatingCurrent) -> Date? {
        guard episode.hasPrefix("ep_"), episode.count >= 13 else { return nil }
        let day = String(episode.dropFirst(3).prefix(10))
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = timeZone
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: day)
    }
}

// MARK: - What to wash

/// One highlighted stretch inside a turn, as scalar offsets LOCAL to the
/// turn's text.
struct ReaderWash: Hashable {
    enum Style: Hashable {
        /// The cited span: the dandelion wash plus the margin bar (§4.4).
        case focus
        /// A derived match: bold, never washed (§4.9).
        case mention
        /// Another span the same entity cites: a fainter wash, no bar (P4).
        case other
    }
    let range: Range<Int>
    let style: Style
}

struct ReaderBlock: Hashable, Identifiable {
    let index: Int
    let role: String
    let speaker: String
    /// The origin whose mark sits beside an agent's speaker line (§4.4: "a
    /// harness mark with its label"); nil for the person, a page, or an
    /// agent nothing names.
    let mark: String?
    let time: String?
    let text: String
    /// Absolute offset of `text`'s first scalar in the document.
    let contentStart: Int
    let washes: [ReaderWash]

    var id: Int { index }
    /// The block the margin bar and the landing belong to.
    var holdsFocus: Bool { washes.contains { $0.style == .focus || $0.style == .mention } }
}

enum ReaderLayout {
    /// The document as blocks, one per server turn (`turns[]` — the client
    /// runs no marker regex of its own, R-PB3). Every range is intersected
    /// with each turn's CONTENT (the marker line prefix is replaced by the
    /// speaker label), so a span that crosses a turn boundary is split into
    /// one wash per turn (§4.4). Offsets past a truncated text are dropped.
    static func blocks(doc: EpisodeText, scalars: ScalarText, focus: Range<Int>?,
                       focusStyle: ReaderWash.Style, others: [Range<Int>] = [],
                       locale: Locale = .autoupdatingCurrent,
                       timeZone: TimeZone = .autoupdatingCurrent) -> [ReaderBlock] {
        doc.turns.compactMap { turn in
            let content = scalars.clamped(turn.contentStart, turn.end)
            guard content.upperBound > content.lowerBound || turn.role == "page" else { return nil }
            var washes: [ReaderWash] = []
            func add(_ range: Range<Int>, _ style: ReaderWash.Style) {
                let lo = max(range.lowerBound, content.lowerBound)
                let hi = min(range.upperBound, content.upperBound)
                guard hi > lo else { return }
                washes.append(ReaderWash(range: (lo - content.lowerBound)..<(hi - content.lowerBound), style: style))
            }
            if let focus { add(focus, focusStyle) }
            for other in others where other != focus { add(other, .other) }
            washes.sort { $0.range.lowerBound < $1.range.lowerBound }
            return ReaderBlock(
                index: turn.index, role: turn.role,
                speaker: EvidenceSpeaker.turnSpeaker(turn, harness: doc.harness, origin: doc.origin),
                mark: turn.role == "assistant"
                    ? EvidenceSpeaker.agentOrigin(harness: doc.harness, origin: doc.origin) : nil,
                time: ReaderTime.label(turn.ts, locale: locale, timeZone: timeZone),
                text: scalars.slice(content.lowerBound, content.upperBound),
                contentStart: content.lowerBound, washes: washes)
        }
    }

    /// The block holding `offset`, for landing. A stale focus still lands
    /// near where the words were (scrolling is not highlighting).
    static func blockIndex(containing offset: Int, in blocks: [ReaderBlock]) -> Int? {
        blocks.last { $0.contentStart <= offset }?.index ?? blocks.first?.index
    }
}

// MARK: - What to say about it, and where to land

enum ReaderBanner: Hashable {
    case stale, grown, inferred, derived, notFound, truncated
}

struct ReaderPresentation: Hashable {
    let focus: Range<Int>?
    let focusStyle: ReaderWash.Style
    let banners: [ReaderBanner]
    /// Absolute offset to scroll to; nil opens at the top.
    let landing: Int?

    /// The honesty rules of §4.9 in one function: stale never washes (and is
    /// said out loud), grown washes and says so, derived bolds and says so,
    /// inferred shows no quote. The target's own `derived` flag wins over the
    /// server's asserted focus — an inbox cause found by name is still found
    /// by name when the Reader re-asks by offsets (R-PB16).
    static func resolve(target: ReaderTarget, doc: EpisodeText, textCount: Int) -> ReaderPresentation {
        var banners: [ReaderBanner] = []
        var focus: Range<Int>?
        var style: ReaderWash.Style = .focus
        var landing: Int?
        switch target.focus {
        case let .span(start, end, _, derived):
            if doc.focus?.stale == true {
                banners.append(.stale)
                landing = start
            } else {
                focus = doc.focus?.range ?? (end > start ? start..<end : nil)
                style = derived || doc.focus?.derived == true ? .mention : .focus
                if style == .mention { banners.append(.derived) }
                if doc.focus?.grown == true { banners.append(.grown) }
            }
        case .mention:
            if let range = doc.focus?.range {
                focus = range
                style = .mention
                banners.append(.derived)
            } else {
                banners.append(.notFound)
            }
        case .inferred:
            banners.append(.inferred)
        case .stale:
            banners.append(.stale)
        case .none:
            break
        }
        if let range = focus, range.lowerBound >= textCount {
            // The words sit past the 400,000-character cap (R-PB5): nothing
            // on screen to wash or land on. The truncated banner says why.
            focus = nil
        }
        if doc.truncated { banners.append(.truncated) }
        return ReaderPresentation(focus: focus, focusStyle: style, banners: banners,
                                  landing: focus?.lowerBound ?? landing.map { min($0, max(0, textCount - 1)) })
    }
}

enum ReaderHeader {
    /// The Stop hook's own stamp (`transcript_capture.CAPTURE_KIND`). It is
    /// not the only one: Telegram's `/remind` note is `capture_kind:
    /// reminder`, and that episode holds exactly what was sent — so the line
    /// below keys on this value, never on "some capture kind is present".
    static let hookCaptureKind = "transcript"

    /// The capture-honesty line (§4.4, G105): a Stop-hook episode keeps the
    /// person's turns and each final reply only; an import says whose export
    /// it was; anything else says nothing rather than guess.
    static func captureLine(_ doc: EpisodeText) -> String? {
        if doc.isPage { return nil }
        if doc.captureKind == hookCaptureKind { return Copy.Provenance.captureHonesty }
        if let origin = doc.origin, origin.hasSuffix("-export"),
           let vendor = EvidenceSpeaker.agentName(harness: nil, origin: origin) {
            return Copy.Provenance.importedFrom(vendor)
        }
        return nil
    }

    /// "Claude Code · 3 Sep 2026 · 42 turns". A page has no turns to count.
    static func meta(_ doc: EpisodeText, locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        if doc.isPage {
            parts.append(Copy.Provenance.fromThePage)
        } else if let agent = EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin) {
            parts.append(agent)
        }
        if let day = ReaderTime.day(timestamp: doc.timestamp, episode: doc.episode, locale: locale,
                                    timeZone: timeZone) {
            parts.append(day)
        }
        if !doc.isPage, !doc.turns.isEmpty { parts.append(Copy.Provenance.turnCount(doc.turns.count)) }
        return parts.joined(separator: " · ")
    }

    /// The mark to draw: the harness, else the origin, else nothing known.
    static func markOrigin(harness: String?, origin: String?) -> String {
        if let h = harness, !h.isEmpty { return h }
        if let o = origin, !o.isEmpty { return o }
        return "unknown"
    }
}
```

Create `Views/Provenance/ReaderInspector.swift`:

```swift
import SwiftUI

/// The Reader (G118 slice 2, design §4.4): a conversation, or a page's stored
/// text, opened beside whatever is on screen and scrolled to the sentence a
/// belief came from. A trailing `.inspector` on the main window's detail
/// column, so the entity card stays visible next to it — the belief and its
/// sentence side by side is the point of the feature.
///
/// Content, not chrome: no glass anywhere in here (R-M5, K12). Everything it
/// shows is fetched from the bank on demand and held in memory only — spans,
/// not copies (§4.9).
struct ReaderInspector: View {
    @Environment(ProvenanceRouter.self) private var router
    @Environment(ProvenanceCache.self) private var cache
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Phase {
        case loading
        case loaded(EpisodeText, ScalarText)
        case gone
        case failed
    }

    @State private var phase: Phase = .loading
    @State private var washVisible = false
    @State private var landingToken = 0
    @State private var conversations = ConversationsViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.background)
        .onExitCommand { router.close() }
        .task(id: router.current) { await load() }
    }

    // MARK: Loading

    private func load() async {
        guard let target = router.current else { return }
        phase = .loading
        washVisible = false
        let result = await cache.document(episode: target.episode, focus: target.query)
        // `.task(id:)` cancels a superseded load, but cancellation is
        // cooperative: a slow fetch for the previous target must never land
        // on the Reader after the person has moved on to another.
        guard !Task.isCancelled, router.current == target else { return }
        switch result {
        case let .loaded(doc):
            phase = .loaded(doc, ScalarText(doc.text))
            landingToken &+= 1
            if let id = doc.conversationId, !doc.isPage {
                await conversations.load(ids: [id])
            }
        case .gone:
            phase = .gone
        case .failed:
            phase = .failed
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                if router.canGoBack {
                    Button { router.back() } label: {
                        Image(systemName: "chevron.left").font(CicadaTheme.font(size: 12, weight: .semibold))
                    }
                    .buttonStyle(.cicadaPlain)
                    // ⌥⌘[ rather than ⌘[: the entity card beside the Reader
                    // already owns ⌘[ for its own back (plan R-PU9).
                    .keyboardShortcut("[", modifiers: [.command, .option])
                    .help(Copy.Provenance.back)
                    .accessibilityLabel(Copy.Provenance.back)
                }
                headerMark
                VStack(alignment: .leading, spacing: 2) {
                    // The track's one display-face moment (R-M3, ≥ 22 pt): the
                    // conversation's name, set like a page title.
                    Text(title)
                        .font(CicadaTheme.displayFont(size: 22))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                    if !meta.isEmpty {
                        Text(meta)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let id = conversationId, conversations.canResume(id) {
                    Button(Copy.Provenance.resume) {
                        Task { await act(await conversations.resume(id)) }
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
                }
                Button { router.close() } label: {
                    Image(systemName: "xmark").font(CicadaTheme.font(size: 11, weight: .semibold))
                }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textSecondary)
                .help(Copy.Provenance.close)
                .accessibilityLabel(Copy.Provenance.close)
            }
            if case let .loaded(doc, _) = phase, let line = ReaderHeader.captureLine(doc) {
                Label(line, systemImage: "info.circle")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
    }

    @ViewBuilder
    private var headerMark: some View {
        if case let .loaded(doc, _) = phase, doc.isPage {
            LogoImage(entityId: doc.episode, name: doc.title, type: .media, size: CicadaTheme.scaled(20))
        } else {
            OriginMark(origin: ReaderHeader.markOrigin(harness: loadedDoc?.harness ?? router.current?.knownHarness,
                                                        origin: loadedDoc?.origin),
                       size: CicadaTheme.scaled(20))
                .iconHover()
        }
    }

    private var loadedDoc: EpisodeText? {
        if case let .loaded(doc, _) = phase { return doc }
        return nil
    }

    private var title: String {
        let known = loadedDoc?.title ?? router.current?.knownTitle ?? ""
        return known.isEmpty ? Copy.Provenance.untitled : known
    }

    private var meta: String { loadedDoc.map { ReaderHeader.meta($0) } ?? "" }
    private var conversationId: String? { loadedDoc?.conversationId }

    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)”"
        case .gone: store.toast = "That conversation's transcript is gone — nothing to resume"
        case .failed(let message): store.toast = message
        }
    }

    // MARK: Body

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            placeholder
        case .gone:
            message(Copy.Provenance.gone, icon: "tray")
        case .failed:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                message(Copy.Provenance.failed, icon: "exclamationmark.triangle")
                Button(Copy.Provenance.retry) { Task { await load() } }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
            }
        case let .loaded(doc, scalars):
            if let target = router.current {
                document(doc, scalars: scalars, target: target)
            }
        }
    }

    /// Static lines, no shimmer (§4.2 — a placeholder is not an animation).
    private var placeholder: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(0..<4, id: \.self) { i in
                RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                    .fill(CicadaTheme.surfaceHover)
                    .frame(width: CicadaTheme.scaled(i == 3 ? 180 : 320), height: CicadaTheme.scaled(10))
            }
        }
        .padding(CicadaTheme.spacingMD)
        .accessibilityHidden(true)
    }

    private func message(_ text: String, icon: String) -> some View {
        Label(text, systemImage: icon)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingMD)
    }

    private func document(_ doc: EpisodeText, scalars: ScalarText, target: ReaderTarget) -> some View {
        let presentation = ReaderPresentation.resolve(target: target, doc: doc, textCount: scalars.count)
        let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: presentation.focus,
                                         focusStyle: presentation.focusStyle)
        let landingBlock = presentation.landing.flatMap { ReaderLayout.blockIndex(containing: $0, in: blocks) }
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    ForEach(presentation.banners, id: \.self) { banner in
                        ReaderBannerView(banner: banner)
                    }
                    if blocks.isEmpty {
                        message(Copy.Provenance.empty, icon: "text.bubble")
                    }
                    ForEach(blocks) { block in
                        ReaderTurnView(block: block, isLanding: block.index == landingBlock,
                                       revealed: washVisible)
                            .id(block.index)
                    }
                }
                .padding(CicadaTheme.spacingMD)
            }
            .accessibilityRotor("Cited passages") {
                ForEach(blocks.filter(\.holdsFocus)) { block in
                    AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
                                            id: block.index)
                }
            }
            .accessibilityRotor("Turns") {
                ForEach(blocks) { block in
                    AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
                                            id: block.index)
                }
            }
            .onChange(of: landingToken, initial: true) { _, _ in
                land(proxy: proxy, block: landingBlock, blocks: blocks, presentation: presentation)
            }
        }
    }

    /// Scroll to the cited turn after the first layout, fade the wash in over
    /// `spanReveal`, then say what was landed on (§4.4 Landing).
    private func land(proxy: ScrollViewProxy, block: Int?, blocks: [ReaderBlock],
                      presentation: ReaderPresentation) {
        Task { @MainActor in
            await Task.yield()
            if let block { proxy.scrollTo(block, anchor: .center) }
            withAnimation(CicadaMotion.spanReveal(reduceMotion: reduceMotion)) { washVisible = true }
            guard presentation.focus != nil, let hit = blocks.first(where: { $0.holdsFocus }),
                  let wash = hit.washes.first(where: { $0.style != .other }) else { return }
            let words = ScalarText(hit.text).slice(wash.range.lowerBound, wash.range.upperBound)
            AccessibilityNotification.Announcement(Copy.Provenance.citedPassage(String(words.prefix(120))))
                .post()
        }
    }
}

/// One turn: the speaker line, then the words with their washes. Selectable
/// text; the landing turn reads in the primary colour, the rest secondary.
struct ReaderTurnView: View {
    let block: ReaderBlock
    let isLanding: Bool
    let revealed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if !block.speaker.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if let mark = block.mark {
                        OriginMark(origin: mark, size: CicadaTheme.scaled(12))
                    }
                    Text(block.speaker)
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text("· \(Copy.Provenance.turn(block.index))")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    if let time = block.time {
                        Text(time)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            Text(ReaderText.attributed(block, revealed: revealed))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(isLanding ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.leading, CicadaTheme.spacingSM)
        .overlay(alignment: .leading) {
            if block.washes.contains(where: { $0.style == .focus }) {
                Rectangle().fill(CicadaTheme.dandelion).frame(width: 2)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(block.speaker.isEmpty
                            ? block.text
                            : "\(block.speaker), \(Copy.Provenance.turn(block.index)): \(block.text)")
    }
}

enum ReaderText {
    /// The cited span's wash (§4.2/§4.4) — emphasis, not a data encoding, so
    /// the one nature token allowed on content (K13).
    static let focusOpacity = 0.35
    /// Other spans the same entity cites: present, quieter, no margin bar.
    static let otherOpacity = 0.15

    /// The turn's text with its washes applied. Offsets are SCALAR offsets
    /// (§4.1), converted through `unicodeScalars` exactly as
    /// `ExcerptText.attributed` does; a range that does not fit is skipped,
    /// never trapped on. `revealed == false` is the frame before the wash
    /// fades in (`spanReveal`) — and the only frame under Reduce Motion is
    /// the revealed one, because the animation is nil there.
    static func attributed(_ block: ReaderBlock, revealed: Bool) -> AttributedString {
        var out = AttributedString(block.text)
        let scalars = block.text.unicodeScalars
        let count = scalars.count
        for wash in block.washes {
            guard wash.range.lowerBound >= 0, wash.range.upperBound <= count, !wash.range.isEmpty else { continue }
            let lower = scalars.index(scalars.startIndex, offsetBy: wash.range.lowerBound)
            let upper = scalars.index(scalars.startIndex, offsetBy: wash.range.upperBound)
            guard let a = AttributedString.Index(lower, within: out),
                  let b = AttributedString.Index(upper, within: out) else { continue }
            switch wash.style {
            case .focus:
                out[a..<b].backgroundColor = CicadaTheme.dandelionFill.opacity(revealed ? focusOpacity : 0)
            case .mention:
                out[a..<b].inlinePresentationIntent = .stronglyEmphasized
            case .other:
                out[a..<b].backgroundColor = CicadaTheme.dandelionFill.opacity(revealed ? otherOpacity : 0)
            }
        }
        return out
    }
}

/// One honest sentence above the text (§4.4 States). The icon is decoration;
/// the words carry the meaning.
struct ReaderBannerView: View {
    let banner: ReaderBanner

    var body: some View {
        Label(text, systemImage: icon)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surfaceHover)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private var text: String {
        switch banner {
        case .stale: Copy.Provenance.stale
        case .grown: Copy.Provenance.grown
        case .inferred: Copy.Provenance.inferred
        case .derived: Copy.Provenance.derived
        case .notFound: Copy.Provenance.notFound
        case .truncated: Copy.Provenance.truncated
        }
    }

    private var icon: String {
        switch banner {
        case .stale: "exclamationmark.triangle"
        case .grown: "arrow.down.to.line"
        case .inferred: "lightbulb"
        case .derived: "text.magnifyingglass"
        case .notFound: "magnifyingglass"
        case .truncated: "scissors"
        }
    }
}
```

Modify `Theme/CicadaMotion.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Theme/CicadaMotion.swift b/app/CicadaApp/Sources/CicadaApp/Theme/CicadaMotion.swift
index b42efaf..f0e3bec 100644
--- a/app/CicadaApp/Sources/CicadaApp/Theme/CicadaMotion.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Theme/CicadaMotion.swift
@@ -42,6 +42,9 @@ enum CicadaMotion {
     static let liftDuration: TimeInterval = 0.18
     static let settleDuration: TimeInterval = 0.35
     static let morphDuration: TimeInterval = 0.35
+    /// G118 slice 2 (design §1.1): the Reader's cited-span wash fading in
+    /// after it lands. Short — the eye is already moving to the words.
+    static let spanRevealDuration: TimeInterval = 0.25
 
     /// Clouds drift, grass never moves (R-M6): at most 8 pt either way over a
     /// 60–120 s period — peripheral, never noticed as movement — at no more
@@ -62,6 +65,11 @@ enum CicadaMotion {
     static func lift(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: liftDuration) }
     static func settle(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeInOut(duration: settleDuration) }
     static func morph(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .smooth(duration: morphDuration) }
+    /// `spanReveal` — the Reader's wash arriving on the cited sentence. nil
+    /// under Reduce Motion: the wash is simply there (a static wash, §4.3).
+    static func spanReveal(reduceMotion: Bool) -> Animation? {
+        reduceMotion ? nil : .easeOut(duration: spanRevealDuration)
+    }
 }
 
 // MARK: - Hover lift (R-M14)
```

Modify `CicadaApp.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/CicadaApp.swift b/app/CicadaApp/Sources/CicadaApp/CicadaApp.swift
index 941cf40..52d4192 100644
--- a/app/CicadaApp/Sources/CicadaApp/CicadaApp.swift
+++ b/app/CicadaApp/Sources/CicadaApp/CicadaApp.swift
@@ -34,6 +34,11 @@ struct CicadaApp: App {
     /// as `sleepEngineVM` above: nothing but `FeedView`/`ContentView`
     /// (main window) and `IntegrationsView` (Settings) observes this.
     @State private var appRouter = AppRouter()
+    /// G118 slice 2 — the Reader's navigation and its in-memory payload
+    /// cache. Main window only: Settings never opens a Reader, and neither is
+    /// a Store domain (R-PB11), so neither needs the Store.
+    @State private var provenanceRouter = ProvenanceRouter()
+    @State private var provenanceCache = ProvenanceCache()
     @State private var banksVM: BanksViewModel
     @State private var feedVM: FeedViewModel
     @State private var contributorsVM: ContributorsViewModel
@@ -97,6 +102,8 @@ struct CicadaApp: App {
                 .environment(sleepVM)
                 .environment(sleepEngineVM)
                 .environment(appRouter)
+                .environment(provenanceRouter)
+                .environment(provenanceCache)
                 .environment(banksVM)
                 .environment(feedVM)
                 .environment(contributorsVM)
```

Modify `ContentView.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/ContentView.swift b/app/CicadaApp/Sources/CicadaApp/ContentView.swift
index 6ad8431..f4902b1 100644
--- a/app/CicadaApp/Sources/CicadaApp/ContentView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/ContentView.swift
@@ -30,6 +30,10 @@ struct ContentView: View {
     /// G126 R9 — consumes a Settings → Integrations "Import in Feed →"
     /// hand-off by switching the sidebar's own selection.
     @Environment(AppRouter.self) private var router
+    /// G118 slice 2 — drives the Reader inspector below; a bank switch
+    /// closes it and empties the cache (R-PU26).
+    @Environment(ProvenanceRouter.self) private var provenance
+    @Environment(ProvenanceCache.self) private var provenanceCache
     @Environment(\.accessibilityReduceMotion) private var reduceMotion
 
     var body: some View {
@@ -49,6 +53,15 @@ struct ContentView: View {
                 // nothing on screen) posts `store.toast`; show it at the
                 // bottom of whatever page is open (§5.4).
                 .overlay(alignment: .bottom) { toastBanner }
+                // G118 slice 2 (design §4.4) — the Reader opens BESIDE whatever
+                // is showing, never over it: the entity card stays up, so a
+                // belief and the sentence it came from are on screen together.
+                // Content, not chrome, so it is never glass (R-M5).
+                .inspector(isPresented: Bindable(provenance).isPresented) {
+                    ReaderInspector()
+                        .inspectorColumnWidth(min: CicadaTheme.scaled(360), ideal: CicadaTheme.scaled(440),
+                                              max: CicadaTheme.scaled(560))
+                }
         }
         // No `.id(colorSchemeRaw)` here any more. Keying this subtree on the
         // mode string used to be what repainted it, because the tokens were
@@ -80,6 +93,14 @@ struct ContentView: View {
         // The roster resolving the active bank, and the graph snapshot landing
         // (from the on-disk cache or the network), are the two events that turn
         // an unknown input into a known one.
         .onChange(of: store.bank) { _, _ in evaluateFirstRun() }
+        // G118 slice 2 (R-PU26) — the Reader and its cache belong to no bank:
+        // episode ids restart every day in every bank, so a switch closes the
+        // Reader and forgets every cached document rather than show another
+        // bank's conversation under this one.
+        .onChange(of: store.bank) { _, _ in
+            provenance.close()
+            provenanceCache.reset()
+        }
         .onChange(of: store.banks.loadedAt) { _, _ in evaluateFirstRun() }
         .onChange(of: store.graph.loadedAt) { _, _ in evaluateFirstRun() }
         .onChange(of: selectedTab) { _, newValue in
```

- [ ] **Step 4: Green, then the whole suite.**
`swift test --filter "ReaderTurnsTests|ProvenanceRouterTests" 2>&1 | tail -5` → 29 tests, 0 failures.
`swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -5` → **1112 executed, 0 failures**
(`MotionLiteralLintTests`, `FontLiteralLintTests` — `displayFont(size: 22)` is at its floor — and
`LiquidGlassLintTests` all run in it).

- [ ] **Step 5: Commit.**
```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/ProvenanceRouter.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/ProvenanceCache.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift \
  app/CicadaApp/Sources/CicadaApp/Theme/CicadaMotion.swift app/CicadaApp/Sources/CicadaApp/CicadaApp.swift \
  app/CicadaApp/Sources/CicadaApp/ContentView.swift \
  app/CicadaApp/Tests/CicadaAppTests/ReaderTurnsTests.swift app/CicadaApp/Tests/CicadaAppTests/ProvenanceRouterTests.swift \
  && git commit -m "feat(provenance-ui): the Reader — one router, an in-memory cache, turns and honest banners (G118 s2, P2)"
```
Body: name R-PU3, R-PU4, R-PU11, R-PU16, R-PU23, R-PU25–R-PU28; attribution trailer.

---

### Task 3: Evidence chips with a hover quote; the claim footer names its writer (P1 UI, P3 footer)

Every `ClaimChip` — Perspectives, Timeline, transclusions — now shows who wrote the belief with a
real face and every piece of evidence as a chip that previews the words and opens the Reader.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTiming.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/QuoteBlock.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChip.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift` (append the chip strings)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Claim.swift:81-89` (plain trust labels, R-PU15)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/ClaimChip.swift:13-36, 175-212` (footer; `AuthorPill` rebuilt; `EpisodePill` deleted, A9)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift:269-375` (`ContributorAvatar`: any size, bare init, `harness`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift:34-55` (`harness` name; `kind(author:serverKind:)`)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/EvidenceChipLabelTests.swift`

**Interfaces:**
- Produces: `CicadaTiming.hoverPreviewDelay/hoverPreviewGrace`; `EvidenceDocMeta`, `EvidenceDocIndex` (`from(_:)`, `meta(_:)`, `EnvironmentValues.evidenceDocIndex`); `EvidenceChipModel` (`Source: stored | mention`, `kind`, `episode`, `target(subjectId:meta:)`, `static chips(evidence:sourceEpisodes:subjectId:)`, `legacyCap`); `EvidenceLabel` (`speaker`, `agent`, `chipText`, `accessibility`, `ruleColor`, `symbol`, `visibleLimit`); `QuoteBlock` (`Style: wash | bold | plain`, `attributed`, `parts(excerpt:mentionOffsets:)`); `EvidenceChip`, `EvidencePreview`, `EvidenceChipRun`; `AuthorPill(_:kind:provider:)`; `ContributorAvatar(author:kind:provider:avatarUrl:size:)`; `ContributorIdentity.kind(author:serverKind:)`.
- Consumes: Task 2's router, cache, `ReaderTarget.evidence`, `EvidenceSpeaker`, `ReaderTime`, `ReaderText.focusOpacity`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/EvidenceChipLabelTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Design §4.2 / §4.10 — every evidence kind has a plain label; a derived
/// match never says "You said"; an agent with no known harness is "The
/// agent"; a legacy claim gets derived chips, capped; and the footer's author
/// and trust pills speak plain words.
final class EvidenceChipLabelTests: XCTestCase {

    private let utc = TimeZone(identifier: "UTC")!
    private let us = Locale(identifier: "en_US")

    // MARK: Labels

    func testEveryKindMapsToAPlainLabel() {
        for kind in EvidenceKind.allCases {
            XCTAssertFalse(EvidenceLabel.speaker(kind: kind, agent: nil).isEmpty, "\(kind)")
        }
        XCTAssertEqual(EvidenceLabel.speaker(kind: .user, agent: "Claude Code"), "You said")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: "Claude Code"), "Claude Code replied")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: nil), "The agent replied")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .page, agent: nil), "From the page")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .speaker, agent: nil, speakerName: "Speaker 2"), "Speaker 2 said")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .speaker, agent: nil, speakerName: "user"), "Someone else said",
                       "a role word is not a meeting speaker's name")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .reasoning, agent: nil), "Inferred")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .unknown, agent: nil), "Inferred", "unknown renders like reasoning")
    }

    func testADerivedChipNeverClaimsASpeaker() {
        for agent in [nil, "Claude Code"] {
            let label = EvidenceLabel.speaker(kind: .derived, agent: agent)
            XCTAssertEqual(label, "Mentioned here")
            XCTAssertNotEqual(label, "You said")
        }
    }

    func testChipTextCarriesTheDayFromTheEpisodeIdAndAPageHasNone() {
        let span = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-03_004", start: 1, end: 5,
                                                              kind: .assistant)))
        let meta = EvidenceDocMeta(title: "Index choice", harness: "claude-code", origin: nil)
        XCTAssertEqual(EvidenceLabel.chipText(span, meta: meta, locale: us, timeZone: utc),
                       "Claude Code replied · Sep 3")
        XCTAssertEqual(EvidenceLabel.chipText(span, meta: nil, locale: us, timeZone: utc),
                       "The agent replied · Sep 3", "no known harness — never a guess")
        let page = EvidenceChipModel(source: .stored(Evidence(episode: "media-example-com", start: 0, end: 4,
                                                              kind: .page)))
        XCTAssertEqual(EvidenceLabel.chipText(page, meta: nil, locale: us, timeZone: utc), "From the page")
    }

    func testTheAccessibilityLabelIsASentence() {
        let chip = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-03_004", start: 1, end: 5,
                                                              kind: .user)))
        XCTAssertEqual(EvidenceLabel.accessibility(chip, meta: EvidenceDocMeta(title: "Index choice"), opens: true,
                                                   locale: us, timeZone: utc),
                       "You said, September 3, in Index choice. Opens the conversation.")
        XCTAssertEqual(EvidenceLabel.accessibility(chip, meta: nil, opens: false, locale: us, timeZone: utc),
                       "You said, September 3.")
    }

    // MARK: Which chips

    func testStoredEvidenceGivesOneChipPerEntryWithDuplicatesFolded() {
        let a = Evidence(episode: "ep_1", start: 1, end: 5, kind: .user, hash: "h")
        let b = Evidence(episode: "ep_2", start: -1, end: -1, kind: .reasoning, hash: "h")
        let chips = EvidenceChipModel.chips(evidence: [a, a, b], sourceEpisodes: ["ep_9"], subjectId: "alpha-project")
        XCTAssertEqual(chips.map(\.kind), [.user, .reasoning], "evidence wins over source_episodes")
    }

    func testALegacyClaimGetsDerivedChipsForItsEpisodesCappedAtThree() {
        let chips = EvidenceChipModel.chips(
            evidence: [],
            sourceEpisodes: ["ep_1", "ep_2", "ep_1", "media-example-com", "ep_3", "ep_4"],
            subjectId: "alpha-project")
        XCTAssertEqual(chips.map(\.episode), ["ep_1", "ep_2", "ep_3"])
        XCTAssertTrue(chips.allSatisfy { $0.kind == .derived })
        XCTAssertEqual(chips.first?.target(subjectId: "alpha-project", meta: nil)?.focus,
                       .mention(entityId: "alpha-project"))
        XCTAssertEqual(EvidenceChipModel.chips(evidence: [], sourceEpisodes: ["ep_1"], subjectId: ""), [],
                       "no subject means no name to search for")
    }

    func testReasoningWithoutADocumentHasNowhereToOpen() {
        let chip = EvidenceChipModel(source: .stored(Evidence(episode: "", start: -1, end: -1, kind: .reasoning)))
        XCTAssertNil(chip.target(subjectId: "alpha-project", meta: nil))
    }

    func testTheDocIndexCoversEveryEpisodeOfEveryConversation() {
        let provenance = EntityProvenance(entityId: "alpha-project", conversations: [
            ProvenanceConversation(conversationId: "ses_alpha", episodeId: "ep_2",
                                   episodeIds: ["ep_1", "ep_2"], title: "Index choice", harness: "claude-code"),
        ])
        let index = EvidenceDocIndex.from(provenance)
        XCTAssertEqual(index.meta("ep_1")?.title, "Index choice")
        XCTAssertEqual(index.meta("ep_2")?.harness, "claude-code")
        XCTAssertNil(index.meta("ep_3"))
        XCTAssertEqual(EvidenceDocIndex.from(nil), .empty)
    }

    // MARK: Author and trust pills

    func testTrustLabelsArePlainWords() {
        XCTAssertEqual(SourceTrust.userStated.label, "You told Cicada")
        XCTAssertEqual(SourceTrust.agentExtracted.label, "Cicada noticed")
        XCTAssertEqual(SourceTrust.agentReflected.label, "Cicada concluded")
        XCTAssertEqual(SourceTrust.external.label, "From a source")
        XCTAssertEqual(SourceTrust.unknown.label, "Not recorded")
    }

    func testAuthorKindFallsBackToTheIdWhenAnOlderBackendSendsNone() {
        XCTAssertEqual(ContributorIdentity.kind(author: "cicada"), "system")
        XCTAssertEqual(ContributorIdentity.kind(author: "user"), "user")
        XCTAssertEqual(ContributorIdentity.kind(author: ""), "unknown")
        XCTAssertEqual(ContributorIdentity.kind(author: "claude-sonnet-4-5"), "model")
        XCTAssertEqual(ContributorIdentity.kind(author: "claude-web", serverKind: "harness"), "harness",
                       "the server's bucket wins")
        XCTAssertEqual(AuthorPill("cicada").kind, "system")
    }

    func testAHarnessAuthorIsNamedAfterItsApp() {
        XCTAssertEqual(ContributorIdentity.displayName(author: "claude-code", kind: "harness"), "Claude Code")
    }

    // MARK: Lint (design §1.1)

    /// A delay in the provenance views is a named `CicadaTiming` constant,
    /// never a literal — the rule M1's motion lint states for durations,
    /// extended to the dwell and grace this track introduces (R-PU18).
    func testProvenanceViewsSpellNoLiteralDelay() throws {
        let literal = try NSRegularExpression(pattern: #"\.seconds\(\s*[0-9]"#)
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Provenance/") {
            scanned += 1
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertNil(literal.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
                         "\(file.lastPathComponent) spells a literal delay — use CicadaTiming")
        }
        XCTAssertGreaterThan(scanned, 0, "the scope matched nothing — this lint would pass vacuously")
    }
}
```

- [ ] **Step 2: Watch them fail.**
`swift test --filter EvidenceChipLabelTests 2>&1 | tail -20` → compile errors naming `EvidenceLabel`,
`EvidenceChipModel`, `EvidenceDocIndex`, `ContributorIdentity.kind(author:)`.

- [ ] **Step 3: Implement.** Create `Theme/CicadaTiming.swift`:

```swift
import Foundation

/// Delays that are not motion (design §1.1): how long the pointer must rest
/// before something opens, and how long a surface waits before closing so the
/// pointer can travel into it. Reduce Motion leaves these alone — a delay is
/// not an animation — which is exactly why they do not live in
/// `CicadaMotion`, whose every member turns into `nil` under it.
enum CicadaTiming {
    /// G118 slice 2 — the dwell before an evidence chip's quote preview opens.
    /// Long enough that sweeping the pointer across a row of chips opens
    /// nothing; short enough that resting on one feels immediate.
    static let hoverPreviewDelay: TimeInterval = 0.35
    /// The grace before a preview closes after the pointer leaves the chip,
    /// so it can cross the gap into the popover (and its "Open conversation").
    static let hoverPreviewGrace: TimeInterval = 0.2
}
```

Create `Views/Provenance/EvidenceChipModel.swift`:

```swift
import SwiftUI

// The evidence chip's decisions, pure and tested (design §4.2, §4.10
// `EvidenceChipLabelTests`): which chips a claim gets, what each one says,
// and where it opens. `EvidenceChip` renders these and nothing else.

// MARK: - What the chip knows about a document without fetching it

/// A document's header fields, when some payload the surface already holds
/// carried them — the entity card's `/provenance` conversations, an inbox
/// cause. `/span` carries no title or harness, and fetching `/text` per chip
/// just to name the agent would be N whole documents per card, so a chip
/// with no entry here says "The agent replied" and stays honest.
struct EvidenceDocMeta: Hashable {
    var title: String?
    var harness: String?
    var origin: String?
}

struct EvidenceDocIndex: Hashable {
    var byEpisode: [String: EvidenceDocMeta] = [:]

    static let empty = EvidenceDocIndex()

    func meta(_ episode: String) -> EvidenceDocMeta? { byEpisode[episode] }

    /// Every episode of every conversation row, keyed to that row's header.
    static func from(_ provenance: EntityProvenance?) -> EvidenceDocIndex {
        guard let provenance else { return .empty }
        var out: [String: EvidenceDocMeta] = [:]
        for row in provenance.conversations {
            let meta = EvidenceDocMeta(title: row.title.isEmpty ? nil : row.title,
                                       harness: row.harness, origin: row.origin)
            for ep in Set(row.episodeIds + [row.episodeId]) { out[ep] = meta }
        }
        return EvidenceDocIndex(byEpisode: out)
    }
}

private struct EvidenceDocIndexKey: EnvironmentKey {
    static let defaultValue = EvidenceDocIndex.empty
}

extension EnvironmentValues {
    /// Set by a surface that already knows its documents (the entity card sets
    /// it from `/provenance`), read by every `EvidenceChip` below it.
    var evidenceDocIndex: EvidenceDocIndex {
        get { self[EvidenceDocIndexKey.self] }
        set { self[EvidenceDocIndexKey.self] = newValue }
    }
}

// MARK: - Which chips

struct EvidenceChipModel: Hashable, Identifiable {
    enum Source: Hashable {
        /// A stored evidence entry — a span, or the contributor's own reasoning.
        case stored(Evidence)
        /// A legacy claim with no evidence: the conversation it lists in
        /// `source_episodes`, where the server will look for the subject's
        /// name (R-PB9). Always labelled `derived`, never "You said" (§4.9).
        case mention(episode: String, subjectId: String)
    }

    let source: Source

    var id: String {
        switch source {
        case let .stored(ev): "s|\(ev.episode)|\(ev.start)|\(ev.end)|\(ev.kind.rawValue)"
        case let .mention(ep, subject): "m|\(ep)|\(subject)"
        }
    }

    var episode: String {
        switch source {
        case let .stored(ev): ev.episode
        case let .mention(ep, _): ep
        }
    }

    /// What the chip is labelled as. `unknown` renders like `reasoning`.
    var kind: EvidenceKind {
        switch source {
        case let .stored(ev): ev.kind == .unknown ? .reasoning : ev.kind
        case .mention: .derived
        }
    }

    /// Where a click goes, or nil when there is nothing to open (reasoning
    /// that names no document).
    func target(subjectId: String?, meta: EvidenceDocMeta?) -> ReaderTarget? {
        switch source {
        case let .stored(ev):
            return ReaderTarget.evidence(ev, subjectId: subjectId, knownTitle: meta?.title,
                                         knownHarness: meta?.harness)
        case let .mention(ep, subject):
            return ReaderTarget(episode: ep, focus: .mention(entityId: subject), subjectId: subject,
                                knownTitle: meta?.title, knownHarness: meta?.harness)
        }
    }

    /// Legacy claims list every conversation they were reinforced in; three
    /// derived chips is enough to show the pattern without a wall of them.
    static let legacyCap = 3

    /// A claim's chips: one per stored evidence entry (duplicates folded), or,
    /// for a legacy claim with none, one derived chip per `ep_*` episode it
    /// lists, capped (§4.2). Before this, only the first episode showed, as an
    /// inert monospaced id (`EpisodePill`, A9).
    static func chips(evidence: [Evidence], sourceEpisodes: [String], subjectId: String) -> [EvidenceChipModel] {
        if !evidence.isEmpty {
            var seen = Set<String>()
            return evidence.compactMap { ev in
                let chip = EvidenceChipModel(source: .stored(ev))
                return seen.insert(chip.id).inserted ? chip : nil
            }
        }
        guard !subjectId.isEmpty else { return [] }
        var seen = Set<String>()
        return sourceEpisodes
            .filter { $0.hasPrefix("ep_") && seen.insert($0).inserted }
            .prefix(legacyCap)
            .map { EvidenceChipModel(source: .mention(episode: $0, subjectId: subjectId)) }
    }
}

// MARK: - What the chip says

enum EvidenceLabel {
    /// More than this many chips on one claim fold behind "+N more" (§4.2).
    static let visibleLimit = 3

    /// The speaker half of the label — the carrier of meaning; colour never
    /// carries it alone (§4.2, K13). `derived` is never "You said".
    static func speaker(kind: EvidenceKind, agent: String?, speakerName: String? = nil) -> String {
        switch kind {
        case .user: Copy.Provenance.youSaid
        case .assistant: agent.map(Copy.Provenance.replied) ?? Copy.Provenance.theAgentReplied
        case .page: Copy.Provenance.fromThePage
        case .media: Copy.Provenance.inTheVideo
        case .speaker: EvidenceSpeaker.named(speakerName).map(Copy.Provenance.said) ?? Copy.Provenance.someoneElseSaid
        case .derived: Copy.Provenance.mentionedHere
        case .reasoning, .unknown: Copy.Provenance.inferredLabel
        }
    }

    static func agent(_ meta: EvidenceDocMeta?) -> String? {
        EvidenceSpeaker.agentName(harness: meta?.harness, origin: meta?.origin)
    }

    /// "You said · Sep 3" — the date from the episode id (`ep_YYYY-MM-DD_nnn`);
    /// a page has no date to give.
    static func chipText(_ chip: EvidenceChipModel, meta: EvidenceDocMeta?,
                         locale: Locale = .autoupdatingCurrent,
                         timeZone: TimeZone = .autoupdatingCurrent) -> String {
        let label = speaker(kind: chip.kind, agent: agent(meta))
        guard let day = ReaderTime.day(timestamp: nil, episode: chip.episode, locale: locale,
                                       timeZone: timeZone, withYear: false) else { return label }
        return "\(label) · \(day)"
    }

    /// The VoiceOver label (§4.3): "You said, September 3, in Index choice.
    /// Opens the conversation."
    static func accessibility(_ chip: EvidenceChipModel, meta: EvidenceDocMeta?, opens: Bool,
                              locale: Locale = .autoupdatingCurrent,
                              timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts = [speaker(kind: chip.kind, agent: agent(meta))]
        if let date = ReaderTime.episodeDate(chip.episode, timeZone: timeZone) {
            var style = Date.FormatStyle().day().month(.wide)
            style.locale = locale
            style.timeZone = timeZone
            parts.append(date.formatted(style))
        }
        var sentence = parts.joined(separator: ", ")
        if let title = meta?.title, !title.isEmpty { sentence += ", in \(title)" }
        sentence += "."
        if opens { sentence += " \(Copy.Provenance.opensTheConversation)" }
        return sentence
    }

    /// The observer colour of the quote's left rule (§4.2): the same tokens
    /// `ObserverBadge` uses for you, the agent and an outside source — never a
    /// nature token, which may not encode data (R-M2, K13).
    static func ruleColor(_ kind: EvidenceKind) -> Color {
        switch kind {
        case .user: CicadaTheme.info
        case .assistant: CicadaTheme.accent
        case .page, .media, .speaker: CicadaTheme.mediaPink
        case .reasoning, .derived, .unknown: CicadaTheme.textTertiary
        }
    }

    static func symbol(_ kind: EvidenceKind) -> String {
        switch kind {
        case .user: "person.fill"
        case .assistant: "bubble.left.fill"
        case .page: "doc.richtext"
        case .media: "play.rectangle"
        case .speaker: "person.2"
        case .reasoning, .unknown: "lightbulb"
        case .derived: "text.magnifyingglass"
        }
    }
}
```

Create `Views/Provenance/QuoteBlock.swift`:

```swift
import SwiftUI

/// A quoted passage with its neighbourhood (design §1.3, §4.2): the words
/// before and after in a quiet colour, the cited words in the quote face
/// (New York italic, R-M3). One component for the hover preview, "Where this
/// came from", and anywhere else a sentence is shown as evidence.
///
/// The style carries the honesty rule (§4.9): an asserted span is WASHED, a
/// derived match is BOLD (found by name, not quoted), and a stale quote is
/// PLAIN — shown so the person has something to read, never highlighted as if
/// its offsets still held.
struct QuoteBlock: View {
    enum Style: Hashable { case wash, bold, plain }

    let before: String
    let span: String
    let after: String
    let kind: EvidenceKind
    /// "You said", "Claude Code replied", "Mentioned here"…
    let label: String?
    /// "Quoted by the contributor" / "Found by searching the conversation".
    let caption: String?
    let style: Style
    var lineLimit: Int? = 8

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            RoundedRectangle(cornerRadius: 1)
                .fill(EvidenceLabel.ruleColor(kind))
                .frame(width: 2)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Self.attributed(before: before, span: span, after: after, style: style))
                    .font(CicadaTheme.font(size: 12))
                    .lineLimit(lineLimit)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if label != nil || caption != nil {
                    Text([label, caption].compactMap { $0 }.joined(separator: " · "))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    /// The span in `quoteFont`; the neighbourhood in `textTertiary`. The wash
    /// is `dandelionFill` at 35% — emphasis, not encoding (K13).
    static func attributed(before: String, span: String, after: String, style: Style) -> AttributedString {
        var head = AttributedString(before)
        head.foregroundColor = CicadaTheme.textTertiary
        var middle = AttributedString(span)
        middle.font = CicadaTheme.quoteFont(size: 12)
        middle.foregroundColor = CicadaTheme.textPrimary
        switch style {
        case .wash: middle.backgroundColor = CicadaTheme.dandelionFill.opacity(ReaderText.focusOpacity)
        case .bold: middle.inlinePresentationIntent = .stronglyEmphasized
        case .plain: break
        }
        var tail = AttributedString(after)
        tail.foregroundColor = CicadaTheme.textTertiary
        return head + middle + tail
    }

    /// An excerpt with its first mention (offsets RELATIVE to the excerpt,
    /// the G115 inbox-cause shape `/provenance` reuses) split into the three
    /// parts; no mention → the whole excerpt as context, nothing emphasised.
    static func parts(excerpt: String, mentionOffsets: [[Int]]) -> (before: String, span: String, after: String) {
        let text = ScalarText(excerpt)
        guard let pair = mentionOffsets.first, pair.count == 2, pair[1] > pair[0], pair[0] >= 0,
              pair[1] <= text.count else { return (excerpt, "", "") }
        return (text.slice(0, pair[0]), text.slice(pair[0], pair[1]), text.slice(pair[1], text.count))
    }
}
```

Create `Views/Provenance/EvidenceChip.swift`:

```swift
import SwiftUI

/// "Where did this come from?" as one small control (G118 slice 2, design
/// §4.2/§4.3). Replaces the inert `EpisodePill` (A9) everywhere a claim is
/// shown. Rest the pointer on it: a preview of the exact words, with who
/// said them. Click (or Return): the Reader opens on that sentence.
///
/// Reads `ProvenanceRouter`/`ProvenanceCache` as OPTIONAL environment values:
/// hosted outside the main window (a preview, a test), it still renders and
/// still previews, it just has nowhere to open.
struct EvidenceChip: View {
    let model: EvidenceChipModel
    /// The entity whose belief this is — the Reader's navigator steps through
    /// its spans, and a legacy chip asks the server to find its name.
    let subjectId: String?

    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @Environment(\.evidenceDocIndex) private var index
    @State private var chipHovered = false
    @State private var previewHovered = false
    @State private var showPreview = false
    @State private var hoverTask: Task<Void, Never>?

    private var meta: EvidenceDocMeta? { index.meta(model.episode) }
    private var target: ReaderTarget? { model.target(subjectId: subjectId, meta: meta) }

    var body: some View {
        Button(action: open) { label }
            .buttonStyle(.cicadaPlain)
            .onHover { inside in
                chipHovered = inside
                pointer(inside: inside)
            }
            .onKeyPress(.space) {
                showPreview.toggle()
                return .handled
            }
            .popover(isPresented: $showPreview, arrowEdge: .top) {
                EvidencePreview(model: model, meta: meta, subjectId: subjectId,
                                onOpen: target == nil ? nil : open)
                    .onHover { inside in
                        previewHovered = inside
                        if !inside { pointer(inside: false) }
                    }
            }
            .accessibilityLabel(EvidenceLabel.accessibility(model, meta: meta, opens: target != nil && router != nil))
            .accessibilityAction(named: Copy.Provenance.previewQuote) { showPreview = true }
            .onDisappear { hoverTask?.cancel() }
    }

    private var label: some View {
        HStack(spacing: 4) {
            mark
            Text(EvidenceLabel.chipText(model, meta: meta))
                .font(CicadaTheme.font(size: 10, weight: .regular))
                .lineLimit(1)
        }
        .foregroundStyle(CicadaTheme.textSecondary)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(CicadaTheme.surfaceHover.opacity(0.6))
        .clipShape(Capsule())
        .overlay {
            // A derived chip is outlined dashed (§4.2): the same shape, visibly
            // not a quote. The label says "Mentioned here" either way.
            if model.kind == .derived {
                Capsule().strokeBorder(CicadaTheme.borderLight, style: StrokeStyle(lineWidth: 1, dash: [2, 2]))
            }
        }
        .contentShape(Capsule())
    }

    @ViewBuilder
    private var mark: some View {
        let size = CicadaTheme.scaled(11)
        if model.kind == .assistant,
           let agent = EvidenceSpeaker.agentOrigin(harness: meta?.harness, origin: meta?.origin) {
            // The label names this agent ("ChatGPT replied"), so its real mark
            // sits beside it — an import's vendor included.
            OriginMark(origin: agent, size: size)
        } else if model.kind == .page {
            LogoImage(entityId: model.episode, name: meta?.title ?? model.episode, type: .media, size: size)
        } else {
            Image(systemName: EvidenceLabel.symbol(model.kind))
                .font(CicadaTheme.font(size: 9, weight: .medium))
                .foregroundStyle(EvidenceLabel.ruleColor(model.kind))
                .iconHover(hovering: chipHovered)
        }
    }

    private func open() {
        hoverTask?.cancel()
        guard let target, let router else {
            showPreview = true
            return
        }
        showPreview = false
        router.open(target)
    }

    /// Dwell to open, grace to close (§4.2): the preview opens after
    /// `hoverPreviewDelay` on the chip and closes `hoverPreviewGrace` after the
    /// pointer leaves — unless it has moved into the preview itself.
    private func pointer(inside: Bool) {
        hoverTask?.cancel()
        hoverTask = Task { @MainActor in
            let wait = inside ? CicadaTiming.hoverPreviewDelay : CicadaTiming.hoverPreviewGrace
            try? await Task.sleep(for: .seconds(wait))
            guard !Task.isCancelled else { return }
            if inside {
                if chipHovered { showPreview = true }
            } else if !chipHovered && !previewHovered {
                showPreview = false
            }
        }
    }
}

/// The hover preview (§4.2): who said it, the words with their neighbourhood,
/// and a way into the whole conversation. Fetches lazily through
/// `ProvenanceCache` — `/span` for a stored span, `/text?focus=` for a legacy
/// mention — and never caches text anywhere but memory (spans, not copies).
struct EvidencePreview: View {
    let model: EvidenceChipModel
    let meta: EvidenceDocMeta?
    let subjectId: String?
    let onOpen: (() -> Void)?

    @Environment(ProvenanceCache.self) private var cache: ProvenanceCache?

    enum Phase: Equatable {
        case loading
        case quote(before: String, span: String, after: String, style: QuoteBlock.Style, note: String?)
        case note(String)
    }

    @State private var phase: Phase = .loading

    private static let context = 240

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: EvidenceLabel.symbol(model.kind))
                    .foregroundStyle(EvidenceLabel.ruleColor(model.kind))
                Text(headerLine)
                    .lineLimit(1)
            }
            .font(CicadaTheme.font(size: 11, weight: .medium))
            .foregroundStyle(CicadaTheme.textSecondary)

            switch phase {
            case .loading:
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(0..<3, id: \.self) { i in
                        RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                            .fill(CicadaTheme.surfaceHover)
                            .frame(width: CicadaTheme.scaled(i == 2 ? 160 : 300), height: CicadaTheme.scaled(8))
                    }
                }
                .accessibilityHidden(true)
            case let .quote(before, span, after, style, note):
                QuoteBlock(before: before, span: span, after: after, kind: model.kind,
                           label: nil, caption: caption(style), style: style)
                if let note {
                    Text(note)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            case let .note(text):
                Text(text)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let onOpen {
                HStack {
                    Spacer()
                    Button(action: onOpen) {
                        Label(Copy.Provenance.openConversation, systemImage: "chevron.right")
                            .labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(360), alignment: .leading)
        .task(id: model.id) { await load() }
    }

    private var headerLine: String {
        var parts = [EvidenceLabel.speaker(kind: model.kind, agent: EvidenceLabel.agent(meta))]
        if let title = meta?.title, !title.isEmpty { parts.append(title) }
        if let day = ReaderTime.day(timestamp: nil, episode: model.episode, withYear: false) { parts.append(day) }
        return parts.joined(separator: " · ")
    }

    private func caption(_ style: QuoteBlock.Style) -> String? {
        switch style {
        case .wash: Copy.Provenance.quotedCaption
        case .bold: Copy.Provenance.derivedCaption
        case .plain: nil
        }
    }

    private func load() async {
        switch model.source {
        case let .stored(ev):
            guard ev.isSpan else {
                phase = .note(Copy.Provenance.inferred)
                return
            }
            guard let cache else { return }
            switch await cache.span(ev) {
            case let .loaded(span) where span.stale && span.text.isEmpty:
                // R-PU25 — the document no longer reaches this span: no words
                // to quote, and "couldn't open" would be untrue.
                phase = .note(Copy.Provenance.stale)
            case let .loaded(span):
                phase = .quote(before: span.before, span: span.text, after: span.after,
                               style: span.stale ? .plain : .wash,
                               note: span.stale ? Copy.Provenance.stale : (span.grown ? Copy.Provenance.grown : nil))
            case .gone:
                phase = .note(Copy.Provenance.gone)
            case .failed:
                phase = .note(Copy.Provenance.failed)
            }
        case let .mention(episode, subject):
            guard let cache else { return }
            switch await cache.document(episode: episode, focus: .mention(entityId: subject)) {
            case let .loaded(doc):
                guard let range = doc.focus?.range else {
                    phase = .note(Copy.Provenance.previewNotFound)
                    return
                }
                let parts = ScalarText(doc.text).around(range.lowerBound, range.upperBound, radius: Self.context)
                phase = .quote(before: parts.before, span: parts.span, after: parts.after, style: .bold, note: nil)
            case .gone:
                phase = .note(Copy.Provenance.gone)
            case .failed:
                phase = .note(Copy.Provenance.failed)
            }
        }
    }
}

/// A claim's evidence as a run of chips: the first `visibleLimit`, then
/// "+N more", which expands in place (plan R-PU10 — the chip lives inside
/// generic surfaces that cannot switch the card's tab).
struct EvidenceChipRun: View {
    let chips: [EvidenceChipModel]
    let subjectId: String?
    @Binding var expanded: Bool

    var body: some View {
        let shown = expanded ? chips : Array(chips.prefix(EvidenceLabel.visibleLimit))
        ForEach(shown) { chip in
            EvidenceChip(model: chip, subjectId: subjectId)
        }
        if chips.count > EvidenceLabel.visibleLimit {
            Button(expanded ? Copy.Provenance.fewerEvidence
                            : Copy.Provenance.moreEvidence(chips.count - EvidenceLabel.visibleLimit)) {
                expanded.toggle()
            }
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.font(size: 10, weight: .medium))
            .foregroundStyle(CicadaTheme.accent)
        }
    }
}
```

Modify `Theme/Copy+Provenance.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
index aefa4d8..b27deb3 100644
--- a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
@@ -50,3 +50,36 @@ extension Copy {
         static func citedPassage(_ text: String) -> String { "Cited passage: \(text)" }
     }
 }
+
+// MARK: - The evidence chip (§4.2) — Task 3
+
+extension Copy.Provenance {
+    static let youSaid = "You said"
+    static let theAgentReplied = "The agent replied"
+    static func replied(_ agent: String) -> String { "\(agent) replied" }
+    static let inTheVideo = "In the video"
+    static let someoneElseSaid = "Someone else said"
+    static func said(_ name: String) -> String { "\(name) said" }
+    static let inferredLabel = "Inferred"
+    static let mentionedHere = "Mentioned here"
+
+    /// The two captions the brief asked for by name (2026-09-23): whether the
+    /// words were QUOTED by whoever wrote the belief, or FOUND afterwards.
+    static let quotedCaption = "Quoted by the contributor"
+    static let derivedCaption = "Found by searching the conversation"
+
+    static let openConversation = "Open conversation"
+    static let opensTheConversation = "Opens the conversation."
+    static let previewQuote = "Preview quote"
+    static func moreEvidence(_ n: Int) -> String { "+\(UsageFormat.count(n)) more" }
+    static let fewerEvidence = "Show fewer"
+    static let previewNotFound = "Cicada couldn't find the name in this conversation."
+
+    // MARK: Plain trust labels (§4.6) — what the `source_trust` axis MEANS,
+    // not its enum name ("agent extracted" read as jargon to everyone but us).
+    static let youToldCicada = "You told Cicada"
+    static let cicadaNoticed = "Cicada noticed"
+    static let cicadaConcluded = "Cicada concluded"
+    static let fromASource = "From a source"
+    static let notRecorded = "Not recorded"
+}
```

Modify `Models/Claim.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift b/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift
index 2205a2d..2110b40 100644
--- a/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/Claim.swift
@@ -78,13 +78,15 @@ enum SourceTrust: String, Codable {
         self = SourceTrust(rawValue: (try? d.singleValueContainer().decode(String.self)) ?? "") ?? .unknown
     }
 
+    /// G118 slice 2 (§4.6) — plain words for a non-technical reader. The axis
+    /// is unchanged and still orthogonal to confidence; only its name changed.
     var label: String {
         switch self {
-        case .userStated: return "user stated"
-        case .agentExtracted: return "agent extracted"
-        case .agentReflected: return "agent reflected"
-        case .external: return "external"
-        case .unknown: return "unknown"
+        case .userStated: return Copy.Provenance.youToldCicada
+        case .agentExtracted: return Copy.Provenance.cicadaNoticed
+        case .agentReflected: return Copy.Provenance.cicadaConcluded
+        case .external: return Copy.Provenance.fromASource
+        case .unknown: return Copy.Provenance.notRecorded
         }
     }
 }
```

Modify `Views/Common/ClaimChip.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Common/ClaimChip.swift b/app/CicadaApp/Sources/CicadaApp/Views/Common/ClaimChip.swift
index 37a5c7a..35aefee 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Common/ClaimChip.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Common/ClaimChip.swift
@@ -14,6 +14,8 @@ struct ClaimChip: View {
     /// Optional clock-icon callback — opens the §4 belief timeline for this
     /// claim's `(subject, predicate, context)` key. Hidden when nil.
     var onOpenTimeline: (() -> Void)? = nil
+    /// G118 slice 2 — "+N more" evidence chips expand in place (R-PU10).
+    @State private var showAllEvidence = false
 
     var body: some View {
         VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
@@ -30,8 +32,17 @@ struct ClaimChip: View {
                 ContextPill(claim.context)
                 TrustPill(claim.sourceTrust)
                 ConfidenceRing(claim.confidence)
-                AuthorPill(claim.authoredBy)
-                if let ep = claim.sourceEpisodes.first { EpisodePill(ep) }
+                AuthorPill(claim.authoredBy, kind: claim.authorKind, provider: claim.authorProvider)
+                // G118 slice 2 (A9) — every piece of evidence, not the first
+                // episode id as inert monospace: hover for the words, click
+                // for the conversation.
+                EvidenceChipRun(
+                    chips: EvidenceChipModel.chips(evidence: claim.evidence,
+                                                   sourceEpisodes: claim.sourceEpisodes,
+                                                   subjectId: claim.subject),
+                    subjectId: claim.subject.isEmpty ? nil : claim.subject,
+                    expanded: $showAllEvidence
+                )
                 if let onOpenTimeline {
                     Button(action: onOpenTimeline) {
                         Image(systemName: "clock")
@@ -172,42 +183,42 @@ struct ConfidenceRing: View {
     }
 }
 
-/// Which model (or `user`) authored the claim — same styling as the
-/// Contributors view / EntityDetailCard history author badge.
+/// Who wrote the claim, with the face the contributors strip gives them
+/// (G118 slice 2, §4.6): `ContributorAvatar` at 14 pt beside the display
+/// name — a provider's real mark, "You", or Cicada's own bookworm — instead
+/// of the raw model id as text. A long model id is its own honest name
+/// (`ContributorIdentity.displayName`), so it is elided, never replaced, and
+/// the full id is on hover.
 struct AuthorPill: View {
     let author: String
-    init(_ author: String) { self.author = author }
+    let kind: String
+    let provider: String?
 
-    var body: some View {
-        Text(author)
-            .font(CicadaTheme.font(size: 10, weight: .regular))
-            .padding(.horizontal, 6)
-            .padding(.vertical, 2)
-            .background(color.opacity(0.18))
-            .clipShape(Capsule())
-            .foregroundStyle(color)
-    }
-
-    private var color: Color {
-        author == "user" ? CicadaTheme.info : CicadaTheme.accent
+    init(_ author: String, kind: String? = nil, provider: String? = nil) {
+        self.author = author
+        self.kind = ContributorIdentity.kind(author: author, serverKind: kind)
+        self.provider = provider
     }
-}
 
-/// The source episode chip. Tapping it is the provenance jump (future: opens
-/// the raw episode) — inert for now but visually present.
-struct EpisodePill: View {
-    let episode: String
-    init(_ episode: String) { self.episode = episode }
+    private var name: String { ContributorIdentity.displayName(author: author, kind: kind) }
 
     var body: some View {
-        Label(episode, systemImage: "doc.text")
-            .font(CicadaTheme.font(size: 10, weight: .regular, design: .monospaced))
-            .foregroundStyle(CicadaTheme.textTertiary)
-            .padding(.horizontal, 6)
-            .padding(.vertical, 2)
-            .background(CicadaTheme.surfaceHover.opacity(0.6))
-            .clipShape(Capsule())
-            .lineLimit(1)
+        HStack(spacing: 4) {
+            ContributorAvatar(author: author, kind: kind, provider: provider, size: CicadaTheme.scaled(14))
+            Text(name)
+                .font(CicadaTheme.font(size: 10, weight: .regular))
+                .lineLimit(1)
+                .truncationMode(.middle)
+        }
+        .foregroundStyle(CicadaTheme.textSecondary)
+        .padding(.leading, 2)
+        .padding(.trailing, 6)
+        .padding(.vertical, 1)
+        .background(CicadaTheme.surfaceHover.opacity(0.6))
+        .clipShape(Capsule())
+        .help(author)
+        .accessibilityElement(children: .ignore)
+        .accessibilityLabel("Written by \(name)")
     }
 }
 
```

Modify `Views/Contributors/ContributorsView.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift b/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift
index 06e3acc..ce7dd40 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift
@@ -277,14 +277,36 @@ struct ContributorDrillDown: View {
 //   unknown -> a muted question-mark glyph — the ONE place a "?" is honest,
 //              because a legacy untrailered commit genuinely has no author.
 //
+//   harness -> the app's own mark (G118 slice 2): a remote write is authored
+//              by the connector's app label (`Cicada-Author: claude-web`, R-R5),
+//              which `author_identity` buckets as `harness` — the same
+//              `OriginMark` every other surface draws for that app.
+//
 // R-S14 — internal, not `private`: the chip strip reuses this exact view
 // rather than re-deriving a mark, so a chip and its drill-down can never wear
-// two different faces for one author.
+// two different faces for one author. G118 slice 2 widens it to any size and
+// to the bare `(author, kind, provider)` a claim or a history row carries, so
+// the ClaimChip footer, the History tab and "Where this came from" draw the
+// SAME face the strip does (design §4.6).
 struct ContributorAvatar: View {
-    let contributor: Contributor
+    let author: String
     let kind: String
+    let provider: String?
+    let avatarUrl: String?
+    var size: CGFloat = 22
 
-    private static let size: CGFloat = 22
+    init(contributor: Contributor, kind: String, size: CGFloat = 22) {
+        self.init(author: contributor.author, kind: kind, provider: contributor.provider,
+                  avatarUrl: contributor.avatarUrl, size: size)
+    }
+
+    init(author: String, kind: String, provider: String?, avatarUrl: String? = nil, size: CGFloat = 22) {
+        self.author = author
+        self.kind = kind
+        self.provider = provider
+        self.avatarUrl = avatarUrl
+        self.size = size
+    }
 
     var body: some View {
         switch kind {
@@ -292,11 +314,13 @@ struct ContributorAvatar: View {
             userAvatar
         case "system":
             systemAvatar
+        case "harness":
+            OriginMark(origin: author, size: size)
         case "unknown":
             Image(systemName: "questionmark.circle.fill")
-                .font(CicadaTheme.font(size: Self.size))
+                .font(CicadaTheme.font(size: size))
                 .foregroundStyle(CicadaTheme.textTertiary)
-                .frame(width: Self.size, height: Self.size)
+                .frame(width: size, height: size)
         default:
             providerBadge
         }
@@ -311,13 +335,13 @@ struct ContributorAvatar: View {
         Image(nsImage: BookwormRenderer.cachedImage(state: .happy, frameIndex: 0, pointSize: 24))
             .interpolation(.none)
             .resizable()
-            .frame(width: Self.size, height: Self.size)
+            .frame(width: size, height: size)
             .clipShape(Circle())
     }
 
     @ViewBuilder
     private var userAvatar: some View {
-        if let urlStr = contributor.avatarUrl, let url = URL(string: urlStr) {
+        if let urlStr = avatarUrl, let url = URL(string: urlStr) {
             AsyncImage(url: url) { phase in
                 switch phase {
                 case .success(let image):
@@ -328,7 +352,7 @@ struct ContributorAvatar: View {
                     userFallback
                 }
             }
-            .frame(width: Self.size, height: Self.size)
+            .frame(width: size, height: size)
             .clipShape(Circle())
         } else {
             userFallback
@@ -337,9 +361,9 @@ struct ContributorAvatar: View {
 
     private var userFallback: some View {
         Image(systemName: "person.crop.circle.fill")
-            .font(CicadaTheme.font(size: Self.size))
+            .font(CicadaTheme.font(size: size))
             .foregroundStyle(CicadaTheme.info)
-            .frame(width: Self.size, height: Self.size)
+            .frame(width: size, height: size)
     }
 
     /// R8 — the real mark when the provider ships one, else the provider's
@@ -357,16 +381,18 @@ struct ContributorAvatar: View {
     /// rounded square — went on screen instead of the author's initials.
     @ViewBuilder
     private var providerBadge: some View {
-        if let logo = ContributorIdentity.logoName(provider: contributor.provider),
+        if let logo = ContributorIdentity.logoName(provider: provider),
            LogoImage.exists(name: logo) {
-            LogoImage(name: logo, size: Self.size)
+            LogoImage(name: logo, size: size)
         } else {
             Circle()
-                .fill(Self.providerColor(contributor.provider))
-                .frame(width: Self.size, height: Self.size)
+                .fill(Self.providerColor(provider))
+                .frame(width: size, height: size)
                 .overlay(
-                    Text(ContributorIdentity.monogram(for: contributor.author))
-                        .font(CicadaTheme.font(size: 10, weight: .bold))
+                    // 10 pt at the strip's 22 pt: the initials scale with the
+                    // circle so a 14 pt claim-chip avatar stays legible.
+                    Text(ContributorIdentity.monogram(for: author))
+                        .font(CicadaTheme.font(size: size * 10 / 22, weight: .bold))
                         .foregroundStyle(.white)
                 )
         }
```

Modify `Views/Contributors/ContributorIdentity.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift b/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift
index 5078c8a..4b273ed 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift
@@ -35,6 +35,9 @@ enum ContributorIdentity {
         if kind == "system" || author == systemAuthor { return "Cicada · maintenance" }
         if kind == "user" || author == "user" { return Copy.you }
         if kind == "unknown" || author == "unknown" { return "Before provenance" }
+        // G118 slice 2 — a remote write's author is the connector's app label
+        // (`claude-web`, R-R5); its honest name is the app's product name.
+        if kind == "harness" { return OriginIconography.label(for: author) }
         return author
     }
 
@@ -46,10 +49,18 @@ enum ContributorIdentity {
     /// against a backend that predates `kind` must classify as system, not as
     /// a model wearing the grey "?" (R-L6).
     static func kind(of contributor: Contributor) -> String {
-        if let k = contributor.kind, !k.isEmpty { return k }
-        if contributor.author == "user" { return "user" }
-        if contributor.author == systemAuthor { return "system" }
-        if contributor.author == "unknown" { return "unknown" }
+        kind(author: contributor.author, serverKind: contributor.kind)
+    }
+
+    /// The same rule for the bare `(author, authorKind)` a claim or a history
+    /// row carries (G118 slice 2, R-PB13): the server's bucket when it sent
+    /// one, else the author id's own — so an older backend's `cicada` is still
+    /// system, never a model wearing initials.
+    static func kind(author: String, serverKind: String? = nil) -> String {
+        if let k = serverKind, !k.isEmpty { return k }
+        if author == "user" { return "user" }
+        if author == systemAuthor { return "system" }
+        if author == "unknown" || author.isEmpty { return "unknown" }
         return "model"
     }
 
```

- [ ] **Step 4: Green, then the whole suite.**
`swift test --filter "EvidenceChipLabelTests|ContributorIdentityTests|ContributorStripTests" 2>&1 | tail -5`
→ 21 tests, 0 failures (the strip's pinned names are unchanged). `swift build` and `swift test` →
**1124 executed, 0 failures**. `rg -n "EpisodePill" app/CicadaApp/Sources` → only the two doc
comments that name what replaced it.

- [ ] **Step 5: Commit.**
```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Theme/CicadaTiming.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/QuoteBlock.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChip.swift \
  app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift app/CicadaApp/Sources/CicadaApp/Models/Claim.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Common/ClaimChip.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift \
  app/CicadaApp/Tests/CicadaAppTests/EvidenceChipLabelTests.swift \
  && git commit -m "feat(provenance-ui): evidence chips with a hover quote; the claim footer names its writer (G118 s2, P1/P3)"
```
Body: name A9, R-PU6…R-PU10, R-PU15, R-PU18, R-PU25 (the preview), R-PU28 (the chip's mark); attribution trailer.

---

### Task 4: "Where this came from" on the entity card; "Look it up at"; faces in History (P3)

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ProvenanceSummary.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/WhereThisCameFromSection.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift` (append)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift` (`vendorName`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift:67, 165-169, 359-363, 682, 1137, 1152-1164`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ConversationPopover.swift:13-20, 36-45, 80-103`
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/ProvenanceSummaryTests.swift`

**Interfaces:**
- Produces: `ProvenanceSummary` (`conversationsSentence`, `placeName`, `groupCounts`, `writersSentence`, `sentenceName`, `chipName`, `chipCount`, `coverage`, `legacyNote`, `alsoItems`, `list`, `episodeByConversation`, `visibleConversations`, `namedWriters`); `ProvenanceSectionState` (`loading | loaded | unavailable | failed`, `value`, `init(_ load:)`); `WhereThisCameFromSection(entityId:state:)`; `ContributorIdentity.vendorName(provider:)`; `ConversationPopover(sessionIds:openEpisode:)`, `FromConversationButton(sessionIds:openEpisode:)`.
- Consumes: `ProvenanceCache.provenance(entityId:)`, `ReaderTarget.best`, `QuoteBlock`, `EvidenceLabel`, `AuthorPill`, `ContributorAvatar`, `FlowLayout` (`EntityDetailCard.swift:1585`).

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/ProvenanceSummaryTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Design §4.5 / §4.10 — "Where this came from" in sentences: zero, one and
/// many conversations, mixed agents, harness authors, legacy-only pages, and
/// coverage stated rather than implied.
final class ProvenanceSummaryTests: XCTestCase {

    private func row(_ ep: String, harness: String? = nil, origin: String? = nil,
                     conversation: String? = nil, available: Bool = true) -> ProvenanceConversation {
        ProvenanceConversation(conversationId: conversation, episodeId: ep, harness: harness, origin: origin,
                               available: available)
    }

    // MARK: Conversations

    func testNoConversationsSaysSoPlainly() {
        let p = EntityProvenance(entityId: "alpha-project")
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p), "Recorded before Cicada kept conversation links.")
    }

    func testOneConversationAndOnePlace() {
        let p = EntityProvenance(entityId: "a", conversations: [row("ep_1", harness: "claude-code")],
                                 totals: ProvenanceTotals(conversations: 1))
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p), "From 1 conversation in Claude Code.")
    }

    func testManyConversationsAcrossPlacesAreBrokenDownMostFirst() {
        let p = EntityProvenance(entityId: "a", conversations: [
            row("ep_1", harness: "claude-code"), row("ep_2", harness: "claude-code"),
            row("ep_3", origin: "chatgpt-export"), row("ep_4", origin: "telegram"),
        ], totals: ProvenanceTotals(conversations: 4))
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p),
                       "From 4 conversations: 2 in Claude Code, 1 in ChatGPT and 1 in Telegram.")
    }

    func testAPartialPayloadStatesOnlyTheHonestTotal() {
        let p = EntityProvenance(entityId: "a", conversations: [row("ep_1", harness: "claude-code")],
                                 totals: ProvenanceTotals(conversations: 57))
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p), "From 57 conversations.",
                       "a breakdown of 50 shipped rows would be a sample, not the truth (R-PB7)")
    }

    func testAnUnknownPlaceIsOtherPlacesNeverARawId() {
        XCTAssertEqual(ProvenanceSummary.placeName(harness: nil, origin: nil), "other places")
        XCTAssertEqual(ProvenanceSummary.placeName(harness: "unknown", origin: "unknown"), "other places")
    }

    // MARK: Writers

    func testWritersNameTheModelWithItsVendorAndYouInLowerCase() {
        let p = EntityProvenance(entityId: "a", contributors: [
            ProvenanceContributor(author: "claude-sonnet-4-5", kind: "model", provider: "anthropic", claims: 12),
            ProvenanceContributor(author: "user", kind: "user", claims: 4),
            ProvenanceContributor(author: "unknown", kind: "unknown", commits: 9),
        ])
        XCTAssertEqual(ProvenanceSummary.writersSentence(p), "Written by Claude (claude-sonnet-4-5) and you.",
                       "a legacy untrailered commit is its chip's to explain, not the sentence's")
    }

    func testAHarnessAuthorIsNamedAfterItsAppAndAnUnmatchedModelKeepsItsId() {
        let p = EntityProvenance(entityId: "a", contributors: [
            ProvenanceContributor(author: "claude-code", kind: "harness", claims: 2),
            ProvenanceContributor(author: "mcp-agentic-write", kind: "model", provider: "other", claims: 1),
            ProvenanceContributor(author: "cicada", kind: "system", commits: 3),
        ])
        XCTAssertEqual(ProvenanceSummary.writersSentence(p), "Written by Claude Code, mcp-agentic-write and Cicada.")
    }

    func testMoreThanThreeWritersFoldIntoOthers() {
        let p = EntityProvenance(entityId: "a", contributors: (1...5).map {
            ProvenanceContributor(author: "model-\($0)", kind: "model", provider: "other", claims: 1)
        })
        XCTAssertEqual(ProvenanceSummary.writersSentence(p), "Written by model-1, model-2, model-3 and 2 others.")
        XCTAssertNil(ProvenanceSummary.writersSentence(EntityProvenance(entityId: "a")))
    }

    func testChipCountUsesTwoNounsNeverOneNumberForTwoThings() {
        XCTAssertEqual(ProvenanceSummary.chipCount(ProvenanceContributor(author: "u", kind: "user",
                                                                        claims: 12, commits: 3)),
                       "12 beliefs · 3 edits")
        XCTAssertEqual(ProvenanceSummary.chipCount(ProvenanceContributor(author: "cicada", kind: "system",
                                                                        commits: 1)), "1 edit")
    }

    // MARK: Coverage

    func testCoverageIsStatedAndLegacyIsExplained() {
        let t = ProvenanceTotals(claims: 18, withSpan: 9, legacy: 7, conversations: 3)
        XCTAssertEqual(ProvenanceSummary.coverage(t), "9 of 18 beliefs here have an exact quote.")
        XCTAssertEqual(ProvenanceSummary.legacyNote(t), "7 were noted before Cicada kept exact quotes.")
        XCTAssertEqual(ProvenanceSummary.coverage(ProvenanceTotals(claims: 1)),
                       "0 of 1 belief here has an exact quote.")
        XCTAssertEqual(ProvenanceSummary.legacyNote(ProvenanceTotals(claims: 1, legacy: 1)),
                       "1 was noted before Cicada kept exact quotes.")
        XCTAssertNil(ProvenanceSummary.legacyNote(ProvenanceTotals(claims: 3, withSpan: 3)))
        XCTAssertEqual(ProvenanceSummary.coverage(ProvenanceTotals()), Copy.Provenance.noBeliefs)
    }

    func testTheAlsoLineListsPagesThenInferred() {
        let p = EntityProvenance(entityId: "a", pages: [ProvenancePage(entityId: "media-example-com",
                                                                        name: "example.com", claimCount: 1)],
                                 inferredCount: 2)
        XCTAssertEqual(ProvenanceSummary.alsoItems(p),
                       ["From the page example.com · 1 belief", "Inferred by Cicada · 2 beliefs"])
    }

    // MARK: History hand-off

    func testOnlyAvailableConversationsMapToAnEpisode() {
        let p = EntityProvenance(entityId: "a", conversations: [
            row("ep_2", conversation: "ses_alpha"),
            row("ep_9", conversation: "ses_gone", available: false),
            row("ep_5"),
        ])
        XCTAssertEqual(ProvenanceSummary.episodeByConversation(p), ["ses_alpha": "ep_2"])
        XCTAssertEqual(ProvenanceSummary.episodeByConversation(nil), [:])
    }

    func testVendorNamesOnlyForProvidersWeCanName() {
        XCTAssertEqual(ContributorIdentity.vendorName(provider: "anthropic"), "Claude")
        XCTAssertEqual(ContributorIdentity.vendorName(provider: "openai"), "OpenAI")
        XCTAssertEqual(ContributorIdentity.vendorName(provider: "google"), "Google",
                       "`google` also answers for Gemma (`git_service._PROVIDER_SUBSTRINGS`) — a family name would guess")
        XCTAssertNil(ContributorIdentity.vendorName(provider: "other"))
        XCTAssertNil(ContributorIdentity.vendorName(provider: nil))
    }
}
```

- [ ] **Step 2: Watch them fail.** `swift test --filter ProvenanceSummaryTests 2>&1 | tail -20` →
compile errors naming `ProvenanceSummary` and `ContributorIdentity.vendorName`.

- [ ] **Step 3: Implement.** Create `Views/Provenance/ProvenanceSummary.swift`:

```swift
import Foundation

/// "Where this came from", as sentences (design §4.5, §4.10
/// `ProvenanceSummaryTests`). Pure over the `/provenance` payload, so the
/// section is a renderer and every sentence it can say is pinned by a test —
/// including the honest ones: no conversation links, no exact quotes, too
/// many conversations to break down.
enum ProvenanceSummary {
    /// The card shows this many conversation rows before "Show all".
    static let visibleConversations = 5
    /// The writers sentence names this many before "and N others".
    static let namedWriters = 3

    // MARK: Conversations

    /// "From 3 conversations: 2 in Claude Code and 1 in ChatGPT."
    ///
    /// The breakdown is only given when every conversation is in the payload
    /// (the server ships at most 50 rows, R-PB7); past that it would be a
    /// breakdown of a sample, so the sentence says only the honest total.
    static func conversationsSentence(_ p: EntityProvenance) -> String {
        let total = max(p.totals.conversations, p.conversations.count)
        guard total > 0 else { return Copy.Provenance.noConversations }
        let lead = "From \(Copy.Provenance.conversations(total))"
        guard p.conversations.count == total else { return lead + "." }
        let groups = groupCounts(p.conversations)
        if groups.count == 1, let only = groups.first { return "\(lead) in \(only.name)." }
        let parts = groups.map { "\(UsageFormat.count($0.count)) in \($0.name)" }
        return "\(lead): \(list(parts))."
    }

    /// Where a conversation happened, as a person would say it: the agent's
    /// product name, else the capture channel's label, else "other places".
    static func placeName(harness: String?, origin: String?) -> String {
        if let agent = EvidenceSpeaker.agentName(harness: harness, origin: origin) { return agent }
        if let origin, !origin.isEmpty, origin != "unknown" { return OriginIconography.label(for: origin) }
        return "other places"
    }

    static func groupCounts(_ rows: [ProvenanceConversation]) -> [(name: String, count: Int)] {
        var counts: [String: Int] = [:]
        for row in rows { counts[placeName(harness: row.harness, origin: row.origin), default: 0] += 1 }
        return counts.map { (name: $0.key, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.name < $1.name }
    }

    // MARK: Writers

    /// "Written by Claude (claude-sonnet-4-5) and you." — who authored the
    /// beliefs, never who spoke in the conversation (conversation `model` is
    /// reserved-null, §4.9). `unknown` is left to its chip ("Before
    /// provenance"); nil when nobody can be named.
    static func writersSentence(_ p: EntityProvenance) -> String? {
        let names = p.contributors
            .filter { $0.kind != "unknown" && ($0.claims + $0.commits) > 0 }
            .map { sentenceName($0) }
        guard !names.isEmpty else { return nil }
        var shown = Array(names.prefix(namedWriters))
        if names.count > namedWriters {
            let others = names.count - namedWriters
            shown.append(others == 1 ? "1 other" : "\(UsageFormat.count(others)) others")
        }
        return "Written by \(list(shown))."
    }

    /// A contributor's name mid-sentence: "you", "Cicada", an app's name, or
    /// a model with its vendor first and its exact id in parentheses — the id
    /// is its own honest name and is never hidden (`ContributorIdentity`).
    static func sentenceName(_ c: ProvenanceContributor) -> String {
        switch c.kind {
        case "user": return "you"
        case "system": return "Cicada"
        default: return chipName(c)
        }
    }

    /// The chip's name: `ContributorIdentity.displayName`, with a model's
    /// vendor in front when the provider has one ("Claude (claude-sonnet-4-5)").
    static func chipName(_ c: ProvenanceContributor) -> String {
        let name = ContributorIdentity.displayName(author: c.author, kind: c.kind)
        guard c.kind == "model", let vendor = ContributorIdentity.vendorName(provider: c.provider) else { return name }
        return "\(vendor) (\(name))"
    }

    /// "12 beliefs · 3 edits" — two nouns, never one number meaning two things
    /// (the Sources v2 rule). An author with only edits shows only edits.
    static func chipCount(_ c: ProvenanceContributor) -> String {
        var parts: [String] = []
        if c.claims > 0 { parts.append(Copy.Provenance.beliefs(c.claims)) }
        if c.commits > 0 { parts.append(Copy.Provenance.edits(c.commits)) }
        return parts.joined(separator: " · ")
    }

    // MARK: Coverage

    /// "9 of 18 beliefs here have an exact quote." — stated, never implied:
    /// most live claims predate exact quotes (no backfill, slice 1), and the
    /// section must not suggest every memory has a snippet.
    static func coverage(_ totals: ProvenanceTotals) -> String {
        guard totals.claims > 0 else { return Copy.Provenance.noBeliefs }
        let verb = totals.claims == 1 ? "belief here has" : "beliefs here have"
        return "\(UsageFormat.count(totals.withSpan)) of \(UsageFormat.count(totals.claims)) \(verb) an exact quote."
    }

    /// Why the rest have none, when any are legacy.
    static func legacyNote(_ totals: ProvenanceTotals) -> String? {
        guard totals.legacy > 0 else { return nil }
        let subject = totals.legacy == 1 ? "1 was" : "\(UsageFormat.count(totals.legacy)) were"
        return "\(subject) noted before Cicada kept exact quotes."
    }

    /// The "Also" line: page spans by page, then the inferred count.
    static func alsoItems(_ p: EntityProvenance) -> [String] {
        var items = p.pages.map { page in
            "\(Copy.Provenance.fromThePage) \(page.name.isEmpty ? page.entityId : page.name) · "
                + Copy.Provenance.beliefs(page.claimCount)
        }
        if p.inferredCount > 0 {
            items.append("\(Copy.Provenance.inferredByCicada) · \(Copy.Provenance.beliefs(p.inferredCount))")
        }
        return items
    }

    // MARK: Helpers

    /// "a", "a and b", "a, b and c".
    static func list(_ items: [String]) -> String {
        switch items.count {
        case 0: return ""
        case 1: return items[0]
        default: return items.dropLast().joined(separator: ", ") + " and " + items[items.count - 1]
        }
    }

    /// conversation id → its newest episode, for "Open conversation" on a
    /// history row (plan R-PU5 — the one place a conversation id meets an
    /// episode id the Reader can open).
    static func episodeByConversation(_ p: EntityProvenance?) -> [String: String] {
        var out: [String: String] = [:]
        for row in p?.conversations ?? [] where row.available {
            if let id = row.conversationId { out[id] = row.episodeId }
        }
        return out
    }
}
```

Create `Views/Provenance/WhereThisCameFromSection.swift`:

```swift
import SwiftUI

/// What the entity card knows about its own provenance payload.
enum ProvenanceSectionState {
    case loading
    case loaded(EntityProvenance)
    /// 404 — a backend without the route (or the page vanished). The section
    /// hides rather than show an error for a feature the server lacks (R10).
    case unavailable
    case failed

    var value: EntityProvenance? {
        if case let .loaded(p) = self { return p }
        return nil
    }

    init(_ load: ProvenanceLoad<EntityProvenance>) {
        switch load {
        case let .loaded(p): self = .loaded(p)
        case .gone: self = .unavailable
        case .failed: self = .failed
        }
    }
}

/// "Where this came from" (G118 slice 2, design §4.5): who wrote this page's
/// beliefs, the conversations that fed it with the best sentence from each,
/// and how many beliefs carry an exact quote. At the bottom of the Content
/// tab and always present — the owner asked for contribution to be EASY to
/// see ("easier and more friendly design to show who contributed to what
/// memory", 2026-09-23), not a tab away.
struct WhereThisCameFromSection: View {
    let entityId: String
    let state: ProvenanceSectionState

    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @State private var showAll = false

    var body: some View {
        switch state {
        case .unavailable:
            EmptyView()
        default:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(Copy.Provenance.whereThisCameFrom)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityAddTraits(.isHeader)
                content
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            VStack(alignment: .leading, spacing: 6) {
                ForEach(0..<2, id: \.self) { i in
                    RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                        .fill(CicadaTheme.surfaceHover)
                        .frame(width: CicadaTheme.scaled(i == 1 ? 180 : 300), height: CicadaTheme.scaled(9))
                }
            }
            .accessibilityHidden(true)
        case .failed:
            Text(Copy.Provenance.unavailable)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        case .unavailable:
            EmptyView()
        case let .loaded(p):
            loaded(p)
        }
    }

    private func loaded(_ p: EntityProvenance) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                Text(ProvenanceSummary.conversationsSentence(p))
                if let writers = ProvenanceSummary.writersSentence(p) { Text(writers) }
            }
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)

            if !p.contributors.isEmpty {
                FlowLayout(spacing: 6) {
                    ForEach(p.contributors) { c in contributorChip(c) }
                }
            }

            let rows = showAll ? p.conversations
                               : Array(p.conversations.prefix(ProvenanceSummary.visibleConversations))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(rows) { row in conversationRow(row) }
            }
            if p.conversations.count > ProvenanceSummary.visibleConversations {
                Button(showAll ? Copy.Provenance.showFewerConversations
                               : Copy.Provenance.showAllConversations(p.conversations.count)) {
                    showAll.toggle()
                }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.accent)
            }

            let also = ProvenanceSummary.alsoItems(p)
            if !also.isEmpty {
                Text(also.joined(separator: "   ·   "))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(ProvenanceSummary.coverage(p.totals))
                if let legacy = ProvenanceSummary.legacyNote(p.totals) { Text(legacy) }
            }
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    // MARK: Contributors

    /// One author, with the face the contributors strip gives them. No share
    /// bar here — the Sources strip owns the one volume chart (§4.5).
    private func contributorChip(_ c: ProvenanceContributor) -> some View {
        HStack(spacing: 6) {
            ContributorAvatar(author: c.author, kind: c.kind, provider: c.provider, size: CicadaTheme.scaled(18))
            VStack(alignment: .leading, spacing: 0) {
                Text(ProvenanceSummary.chipName(c))
                    .font(CicadaTheme.font(size: 11, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(ProvenanceSummary.chipCount(c))
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.leading, 4)
        .padding(.trailing, 10)
        .padding(.vertical, 4)
        .background(CicadaTheme.surfaceHover)
        .clipShape(Capsule())
        // What the two numbers count (§4.5 item 2), in plain words — never
        // the raw author id or "commit".
        .help(c.kind == "unknown" ? Copy.Provenance.beforeProvenanceHelp
                                  : Copy.Provenance.contributorHelp(ProvenanceSummary.sentenceName(c)))
        .accessibilityElement(children: .combine)
    }

    // MARK: Conversations

    private func conversationRow(_ row: ProvenanceConversation) -> some View {
        let title = row.title.isEmpty ? Copy.Provenance.untitled : row.title
        let day = ReaderTime.day(timestamp: row.timestamp, episode: row.episodeId, withYear: false)
        return Button {
            open(row)
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    OriginMark(origin: ReaderHeader.markOrigin(harness: row.harness, origin: row.origin),
                               size: CicadaTheme.scaled(16))
                        .iconHover()
                    Text(title)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let day {
                        Text(day).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Text(Copy.Provenance.beliefs(row.claimCount))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    if row.available {
                        Image(systemName: "chevron.right")
                            .font(CicadaTheme.font(size: 9, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                if !row.available {
                    Text(Copy.Provenance.notInBank)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                } else if let best = row.best, !best.excerpt.isEmpty {
                    bestQuote(best, row: row)
                }
            }
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(!row.available || router == nil)
        .hoverLift(scale: 1.005, lift: 1)
        .accessibilityLabel([title, ProvenanceSummary.placeName(harness: row.harness, origin: row.origin),
                             day ?? "", Copy.Provenance.beliefs(row.claimCount)]
                                .filter { !$0.isEmpty }.joined(separator: ", ")
                            + (row.available ? ". \(Copy.Provenance.opensTheConversation)" : "."))
    }

    /// The best sentence (R-PB8) with its honest label: who said it for an
    /// asserted quote, "Mentioned here" + "Found by searching the
    /// conversation" for a derived one, and no emphasis at all when stale.
    private func bestQuote(_ best: ProvenanceSpan, row: ProvenanceConversation) -> some View {
        let parts = QuoteBlock.parts(excerpt: best.excerpt, mentionOffsets: best.mentionOffsets)
        let style: QuoteBlock.Style = best.stale ? .plain : (best.derived ? .bold : .wash)
        let caption: String = best.stale ? Copy.Provenance.staleCaption
            : (best.derived ? Copy.Provenance.derivedCaption : Copy.Provenance.quotedCaption)
        return QuoteBlock(before: parts.before, span: parts.span, after: parts.after, kind: best.displayKind,
                          label: EvidenceLabel.speaker(kind: best.displayKind,
                                                       agent: EvidenceSpeaker.agentName(harness: row.harness,
                                                                                         origin: row.origin)),
                          caption: caption, style: style, lineLimit: 4)
    }

    private func open(_ row: ProvenanceConversation) {
        guard row.available, let router else { return }
        let target = row.best.map {
            ReaderTarget.best($0, subjectId: entityId, knownTitle: row.title, knownHarness: row.harness)
        } ?? ReaderTarget(episode: row.episodeId, focus: .mention(entityId: entityId), subjectId: entityId,
                          knownTitle: row.title, knownHarness: row.harness)
        router.open(target)
    }
}
```

Modify `Theme/Copy+Provenance.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
index b27deb3..20d8c22 100644
--- a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
@@ -83,3 +83,32 @@ extension Copy.Provenance {
     static let fromASource = "From a source"
     static let notRecorded = "Not recorded"
 }
+
+// MARK: - "Where this came from" on the entity card (§4.5) — Task 4
+
+extension Copy.Provenance {
+    static let whereThisCameFrom = "Where this came from"
+    /// G61's "Sources" section, renamed so "where to refresh this fact" can
+    /// never be read as "where this belief came from" (§4.5, R6 §5.3.7).
+    static let lookItUpAt = "Look it up at"
+
+    static let noConversations = "Recorded before Cicada kept conversation links."
+    static let noBeliefs = "No beliefs are recorded on this page yet."
+    static let unavailable = "Couldn't load where this came from."
+    static let notInBank = "No longer in this bank"
+    static let staleCaption = "This conversation changed since, so the words may have moved"
+    static let inferredByCicada = "Inferred by Cicada"
+    static func showAllConversations(_ n: Int) -> String { "Show all \(UsageFormat.count(n))" }
+    static let showFewerConversations = "Show fewer"
+    /// A contributor chip's hover: what "N beliefs · N edits" counts.
+    static func contributorHelp(_ name: String) -> String {
+        "Beliefs on this page written by \(name), and edits \(name) made to it."
+    }
+    static let beforeProvenanceHelp = "Edits made before Cicada recorded who made them."
+
+    static func beliefs(_ n: Int) -> String { n == 1 ? "1 belief" : "\(UsageFormat.count(n)) beliefs" }
+    static func edits(_ n: Int) -> String { n == 1 ? "1 edit" : "\(UsageFormat.count(n)) edits" }
+    static func conversations(_ n: Int) -> String {
+        n == 1 ? "1 conversation" : "\(UsageFormat.count(n)) conversations"
+    }
+}
```

Modify `Views/Contributors/ContributorIdentity.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift b/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift
index 4b273ed..8dcb5ad 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift
@@ -83,6 +83,23 @@ enum ContributorIdentity {
         }
     }
 
+    /// A provider's product family for a sentence — "Claude (claude-sonnet-4-5)"
+    /// (G118 slice 2, §4.5: "the model family first and the raw id in
+    /// parentheses"). nil for "other" and nil: the raw id then stands alone,
+    /// because a guessed family would claim a brand the id does not carry.
+    /// For the same reason `google` is "Google", not "Gemini": the server's
+    /// rule files Gemma under it too (`git_service._PROVIDER_SUBSTRINGS`).
+    static func vendorName(provider: String?) -> String? {
+        switch provider {
+        case "anthropic": "Claude"
+        case "openai": "OpenAI"
+        case "google": "Google"
+        case "ollama": "Ollama"
+        case "openrouter": "OpenRouter"
+        default: nil
+        }
+    }
+
     /// Every mark this map can return. An array rather than a Set because
     /// `LogoAssetTests.testEveryBundledMarkIsClaimedBySomeMap` concatenates it
     /// into the claimed-names list — this is the only thing that stops a
```

Modify `Views/Graph/EntityDetailCard.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift b/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift
index 0812d6e..a9ef757 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift
@@ -66,6 +66,16 @@ struct EntityDetailCard: View {
     /// chip snaps back to the server's truth).
     @State private var pendingDecayClass: DecayClass?
 
+    /// G118 slice 2 — "Where this came from" (§4.5), one `/provenance` call per
+    /// card, cached in memory by `ProvenanceCache` (never a Store domain,
+    /// R-PB11). Loaded at the card level, not the Content tab's, because the
+    /// same payload names the agent on every evidence chip in Perspectives and
+    /// Timeline (`evidenceDocIndex`) and maps a history row's conversation to
+    /// an episode the Reader can open.
+    @State private var provenanceState: ProvenanceSectionState = .loading
+    @Environment(ProvenanceCache.self) private var provenanceCache: ProvenanceCache?
+    @Environment(ProvenanceRouter.self) private var provenanceRouter: ProvenanceRouter?
+
     // G67 — per-commit diffs in the History tab, fetched on demand and cached
     // per (entity, commit) — `DiffCacheKey`, not commit hash alone: one
     // Sleep-cycle commit routinely touches several entity files, so the same
@@ -166,6 +176,28 @@ struct EntityDetailCard: View {
         .sheet(item: $timelineKey) { key in
             beliefTimelineSheet(key)
         }
+        // A chip in the Belief Timeline sheet opens the Reader beside this
+        // card; the sheet steps aside so the sentence is not under a modal
+        // (the rule `ContentView` applies to the Ask sheet, R-PU20).
+        .onChange(of: provenanceRouter?.revision ?? 0) { _, _ in timelineKey = nil }
+        // Outermost on purpose: the Belief Timeline sheet's chips read it too.
+        .environment(\.evidenceDocIndex, EvidenceDocIndex.from(provenanceState.value))
+        .task(id: entity.id) { await loadProvenance() }
+    }
+
+    /// One `/provenance` per entity (ETag-revalidated by the cache). A 404 —
+    /// an older backend — hides the section rather than showing an error.
+    private func loadProvenance() async {
+        guard let provenanceCache else {
+            provenanceState = .unavailable
+            return
+        }
+        provenanceState = .loading
+        let result = await provenanceCache.provenance(entityId: entity.id)
+        // A card swapped to another entity cancels this task; a late answer
+        // for the old one must not land under the new name.
+        guard !Task.isCancelled else { return }
+        provenanceState = ProvenanceSectionState(result)
     }
 
     // MARK: - Header
@@ -360,6 +392,9 @@ struct EntityDetailCard: View {
 
             Divider().background(CicadaTheme.border)
             metadataSection
+
+            Divider().background(CicadaTheme.border)
+            WhereThisCameFromSection(entityId: entity.id, state: provenanceState)
         }
         .padding(CicadaTheme.spacingLG)
         .task(id: entity.id) {
@@ -679,7 +714,9 @@ struct EntityDetailCard: View {
     /// a cheat-sheet for REFRESHING a fact.
     private var sourcesSection: some View {
         VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
-            Text("Sources")
+            // G118 slice 2 (§4.5) — renamed from "Sources": this is where to
+            // REFRESH a fact; where a belief CAME FROM is the section below.
+            Text(Copy.Provenance.lookItUpAt)
                 .font(CicadaTheme.captionFont)
                 .foregroundStyle(CicadaTheme.textTertiary)
 
@@ -1134,7 +1171,8 @@ struct EntityDetailCard: View {
                 .accessibilityLabel("Commit \(entry.date) by \(entry.author)")
             }
 
-            FromConversationButton(sessionIds: entry.sessions)
+            FromConversationButton(sessionIds: entry.sessions,
+                                   openEpisode: ProvenanceSummary.episodeByConversation(provenanceState.value))
         }
     }
 
@@ -1149,18 +1187,11 @@ struct EntityDetailCard: View {
                 Text(entry.date)
                     .font(CicadaTheme.captionFont)
                     .foregroundStyle(CicadaTheme.textTertiary)
-                // M3 (backlog A2): who authored this commit.
+                // M3 (backlog A2): who authored this commit — with the same
+                // face and name the claim footer and the contributors strip
+                // give them (G118 slice 2, §4.6).
                 if !entry.author.isEmpty {
-                    Text(entry.author)
-                        .font(CicadaTheme.captionFont)
-                        .padding(.horizontal, 6)
-                        .padding(.vertical, 1)
-                        .background(
-                            (entry.author == "user" ? CicadaTheme.info : CicadaTheme.accent)
-                                .opacity(0.18)
-                        )
-                        .clipShape(Capsule())
-                        .foregroundStyle(entry.author == "user" ? CicadaTheme.info : CicadaTheme.accent)
+                    AuthorPill(entry.author, kind: entry.authorKind, provider: entry.authorProvider)
                 }
             }
 
```

Modify `Views/Sources/ConversationPopover.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/ConversationPopover.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/ConversationPopover.swift
index e729d0e..2a7b190 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/ConversationPopover.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/ConversationPopover.swift
@@ -12,6 +12,14 @@ import SwiftUI
 /// refinement, not a missing capability.
 struct ConversationPopover: View {
     let sessionIds: [String]
+    /// G118 slice 2 (A10) — conversation id → an episode the Reader can open.
+    /// Only a caller that holds the entity's `/provenance` can fill it (the
+    /// conversation payload carries no episode id, plan R-PU5); an id missing
+    /// here simply has no "Open conversation", as before.
+    var openEpisode: [String: String] = [:]
+
+    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
+    @Environment(\.dismiss) private var dismiss
 
     @State private var viewModel = ConversationsViewModel()
     @State private var loadedOnce = false
@@ -44,6 +52,19 @@ struct ConversationPopover: View {
                         onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                         onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } }
                     )
+                    if let episode = openEpisode[conversation.id], let router {
+                        Button {
+                            dismiss()
+                            router.open(ReaderTarget(episode: episode, knownTitle: conversation.title,
+                                                     knownHarness: conversation.harness))
+                        } label: {
+                            Label(Copy.Provenance.openConversation, systemImage: "text.book.closed")
+                                .labelStyle(.titleAndIcon)
+                        }
+                        .buttonStyle(.cicadaPlain)
+                        .font(CicadaTheme.captionFont)
+                        .foregroundStyle(CicadaTheme.accent)
+                    }
                 }
             }
         }
@@ -79,6 +100,7 @@ struct ConversationPopover: View {
 /// the commit, so every pre-G48 row looks exactly as it did.
 struct FromConversationButton: View {
     let sessionIds: [String]
+    var openEpisode: [String: String] = [:]
 
     @State private var isPresented = false
 
@@ -99,7 +121,7 @@ struct FromConversationButton: View {
             .help("Show the conversation that wrote this, and reopen it")
             .accessibilityLabel("Show the conversation that wrote this")
             .popover(isPresented: $isPresented, arrowEdge: .bottom) {
-                ConversationPopover(sessionIds: sessionIds)
+                ConversationPopover(sessionIds: sessionIds, openEpisode: openEpisode)
             }
         }
     }
```

- [ ] **Step 4: Green, then the whole suite.**
`swift test --filter "ProvenanceSummaryTests|ConversationAffordanceTests" 2>&1 | tail -5` → 21 tests,
0 failures. `swift build` and `swift test` → **1137 executed, 0 failures**.

- [ ] **Step 5: Commit.**
```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Provenance/ProvenanceSummary.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/WhereThisCameFromSection.swift \
  app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorIdentity.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sources/ConversationPopover.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProvenanceSummaryTests.swift \
  && git commit -m "feat(provenance-ui): Where this came from on the entity card; Look it up at; faces in History (G118 s2, P3)"
```
Body: name A10, R-PU5, R-PU13, R-PU14, R-PU20, R-PU23, H6; attribution trailer.

---

### Task 5: The Reader's navigator and "Noted from this conversation" (P4)

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift` (append `ReaderNavigator`, `ReaderPresentation.citation`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift` (citations, jump, navigator, the list)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift` (append)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/ReaderNavigatorTests.swift`

**Interfaces:**
- Produces: `ReaderNavigator` (`stops(_:subjectId:)`, `position(of:in:)`, `step(from:count:by:)`, `label(position:count:)`); `ReaderPresentation.citation(_:truncated:textCount:)`.
- Consumes: `ProvenanceCache.citations(episode:)`, `AppRouter.pendingTab` (`Support/AppRouter.swift:15`), `GraphViewModel.revealEntity(id:)` (`ViewModels/GraphViewModel.swift:434`), `renderWikilinks` (`ClaimChip.swift`), `LogoImage(entityId:name:type:size:)`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/ReaderNavigatorTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Design §4.4 (P4) — "‹ 2 of 5 cited here ›": which spans the navigator
/// steps through, where the Reader is among them, and what a jump to one
/// says about it.
final class ReaderNavigatorTests: XCTestCase {

    private func cite(_ claim: String, subject: String, _ range: Range<Int>?, derived: Bool = false,
                      grown: Bool = false, stale: Bool = false) -> EpisodeCitation {
        EpisodeCitation(claimId: claim, subjectId: subject, kind: derived ? .derived : .assistant,
                        start: range?.lowerBound, end: range?.upperBound, stale: stale, grown: grown,
                        derived: derived)
    }

    private lazy var rows: [EpisodeCitation] = [
        cite("c3", subject: "alpha-project", 90..<99),
        cite("c1", subject: "alpha-project", 10..<20),
        cite("c2", subject: "bob-example", 40..<50),
        cite("c4", subject: "alpha-project", 10..<20),          // a second claim, same words
        cite("c5", subject: "alpha-project", nil, stale: true), // R-PB2 — no offsets, never a stop
    ]

    func testStopsAreTheSubjectsSpansInDocumentOrderDeduplicated() {
        XCTAssertEqual(ReaderNavigator.stops(rows, subjectId: "alpha-project"), [10..<20, 90..<99])
    }

    func testWithoutASubjectOrWithNoneOfItsOwnEverySpanIsAStop() {
        XCTAssertEqual(ReaderNavigator.stops(rows, subjectId: nil), [10..<20, 40..<50, 90..<99])
        XCTAssertEqual(ReaderNavigator.stops(rows, subjectId: "carol-example"), [10..<20, 40..<50, 90..<99],
                       "an entity with no span here still gets something to step through")
    }

    func testPositionFindsTheFocusExactlyOrByOverlap() {
        let stops = [10..<20, 40..<50, 90..<99]
        XCTAssertEqual(ReaderNavigator.position(of: 40..<50, in: stops), 1)
        XCTAssertEqual(ReaderNavigator.position(of: 45..<47, in: stops), 1)
        XCTAssertNil(ReaderNavigator.position(of: 60..<70, in: stops))
        XCTAssertNil(ReaderNavigator.position(of: nil, in: stops))
    }

    func testSteppingClampsAtTheEndsAndStartsFromAnEndWhenLost() {
        XCTAssertEqual(ReaderNavigator.step(from: 1, count: 3, by: 1), 2)
        XCTAssertEqual(ReaderNavigator.step(from: 2, count: 3, by: 1), 2, "the last passage is an end, not a loop")
        XCTAssertEqual(ReaderNavigator.step(from: 0, count: 3, by: -1), 0)
        XCTAssertEqual(ReaderNavigator.step(from: nil, count: 3, by: 1), 0)
        XCTAssertEqual(ReaderNavigator.step(from: nil, count: 3, by: -1), 2)
        XCTAssertNil(ReaderNavigator.step(from: nil, count: 0, by: 1))
    }

    func testTheLabelCountsFromOne() {
        XCTAssertEqual(ReaderNavigator.label(position: 1, count: 5), "2 of 5 cited here")
        XCTAssertEqual(ReaderNavigator.label(position: nil, count: 5), "5 cited here")
        XCTAssertEqual(ReaderNavigator.label(position: nil, count: 0), "")
    }

    func testAJumpIsJudgedByTheCitationsOwnFlags() {
        let derived = ReaderPresentation.citation(cite("c", subject: "a", 5..<9, derived: true),
                                                  truncated: false, textCount: 100)
        XCTAssertEqual(derived.focusStyle, .mention)
        XCTAssertEqual(derived.banners, [.derived])
        let grown = ReaderPresentation.citation(cite("c", subject: "a", 5..<9, grown: true),
                                                truncated: false, textCount: 100)
        XCTAssertEqual(grown.focusStyle, .focus)
        XCTAssertEqual(grown.banners, [.grown])
        XCTAssertEqual(grown.landing, 5)
        let past = ReaderPresentation.citation(cite("c", subject: "a", 500..<509), truncated: true, textCount: 100)
        XCTAssertNil(past.focus, "words past the cap are not on screen to wash")
        XCTAssertEqual(past.banners, [.truncated])
    }
}
```

- [ ] **Step 2: Watch them fail.** `swift test --filter ReaderNavigatorTests 2>&1 | tail -20` → compile
errors naming `ReaderNavigator` and `ReaderPresentation.citation`.

- [ ] **Step 3: Implement.** Modify `Views/Provenance/ReaderModel.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift b/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift
index f9a23cc..d7be81b 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift
@@ -292,3 +292,65 @@ enum ReaderHeader {
         return "unknown"
     }
 }
+
+// MARK: - The navigator and "Noted from this conversation" (§4.4, P4)
+
+enum ReaderNavigator {
+    /// The spans the navigator steps through, in document order: the ranges
+    /// the SUBJECT's claims cite here when the Reader was opened for an
+    /// entity, else every cited range (a Reader opened from the inbox or a
+    /// history row steps through all of them, §4.4). Stale rows carry no
+    /// offsets (R-PB2), so they are never a stop; duplicates fold.
+    static func stops(_ citations: [EpisodeCitation], subjectId: String?) -> [Range<Int>] {
+        let ranged = citations.filter { $0.range != nil }
+        let mine = subjectId.map { id in ranged.filter { $0.subjectId == id } } ?? []
+        let chosen = mine.isEmpty ? ranged : mine
+        var seen = Set<Range<Int>>()
+        return chosen.compactMap(\.range)
+            .filter { seen.insert($0).inserted }
+            .sorted { $0.lowerBound != $1.lowerBound ? $0.lowerBound < $1.lowerBound : $0.upperBound < $1.upperBound }
+    }
+
+    /// Where `focus` sits among the stops — exact match first, else the first
+    /// stop that overlaps it — or nil when it is not one of them.
+    static func position(of focus: Range<Int>?, in stops: [Range<Int>]) -> Int? {
+        guard let focus else { return nil }
+        return stops.firstIndex(of: focus) ?? stops.firstIndex { $0.overlaps(focus) }
+    }
+
+    /// The stop `delta` steps from `current` (clamped, never wrapping — the
+    /// first and last passage are ends, not a loop). With no current stop,
+    /// forward goes to the first and back to the last.
+    static func step(from current: Int?, count: Int, by delta: Int) -> Int? {
+        guard count > 0 else { return nil }
+        guard let current else { return delta >= 0 ? 0 : count - 1 }
+        return min(max(current + delta, 0), count - 1)
+    }
+
+    /// "2 of 5 cited here".
+    static func label(position: Int?, count: Int) -> String {
+        guard count > 0 else { return "" }
+        let n = UsageFormat.count(count)
+        guard let position else { return "\(n) cited here" }
+        return "\(UsageFormat.count(position + 1)) of \(n) cited here"
+    }
+}
+
+extension ReaderPresentation {
+    /// A jump inside the Reader (a navigator step or a "Noted from this
+    /// conversation" row) replaces the target's focus with a citation's own,
+    /// judged by that citation's own flags: a derived row bolds, a grown row
+    /// says so, and the target's banners no longer apply to these words.
+    static func citation(_ c: EpisodeCitation, truncated: Bool, textCount: Int) -> ReaderPresentation {
+        guard let range = c.range, range.lowerBound < textCount else {
+            return ReaderPresentation(focus: nil, focusStyle: .focus, banners: truncated ? [.truncated] : [],
+                                      landing: nil)
+        }
+        var banners: [ReaderBanner] = []
+        if c.derived { banners.append(.derived) }
+        if c.grown { banners.append(.grown) }
+        if truncated { banners.append(.truncated) }
+        return ReaderPresentation(focus: range, focusStyle: c.derived ? .mention : .focus, banners: banners,
+                                  landing: range.lowerBound)
+    }
+}
```

Modify `Views/Provenance/ReaderInspector.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift b/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift
index 5f6cb66..b345fab 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift
@@ -13,6 +13,8 @@ struct ReaderInspector: View {
     @Environment(ProvenanceRouter.self) private var router
     @Environment(ProvenanceCache.self) private var cache
     @Environment(Store.self) private var store
+    @Environment(GraphViewModel.self) private var graphVM
+    @Environment(AppRouter.self) private var appRouter
     @Environment(\.accessibilityReduceMotion) private var reduceMotion
 
     enum Phase {
@@ -26,6 +28,11 @@ struct ReaderInspector: View {
     @State private var washVisible = false
     @State private var landingToken = 0
     @State private var conversations = ConversationsViewModel()
+    /// P4 — what this document taught Cicada (`/citations`, G106 (ii)).
+    @State private var citations: EpisodeCitations?
+    /// A navigator step or a "Noted" row re-focuses the Reader IN PLACE on
+    /// that citation; the router trail is for moving between documents.
+    @State private var jump: EpisodeCitation?
 
     var body: some View {
         VStack(alignment: .leading, spacing: 0) {
@@ -45,6 +52,8 @@ struct ReaderInspector: View {
         guard let target = router.current else { return }
         phase = .loading
         washVisible = false
+        jump = nil
+        citations = nil
         let result = await cache.document(episode: target.episode, focus: target.query)
         // `.task(id:)` cancels a superseded load, but cancellation is
         // cooperative: a slow fetch for the previous target must never land
@@ -54,6 +63,9 @@ struct ReaderInspector: View {
         case let .loaded(doc):
             phase = .loaded(doc, ScalarText(doc.text))
             landingToken &+= 1
+            let cited = await cache.citations(episode: target.episode).value
+            guard !Task.isCancelled, router.current == target else { return }
+            citations = cited
             if let id = doc.conversationId, !doc.isPage {
                 await conversations.load(ids: [id])
             }
@@ -174,6 +186,10 @@ struct ReaderInspector: View {
         case let .loaded(doc, scalars):
             if let target = router.current {
                 document(doc, scalars: scalars, target: target)
+                if let citations {
+                    Divider().background(CicadaTheme.border)
+                    notedList(citations, doc: doc)
+                }
             }
         }
     }
@@ -199,43 +215,186 @@ struct ReaderInspector: View {
     }
 
     private func document(_ doc: EpisodeText, scalars: ScalarText, target: ReaderTarget) -> some View {
-        let presentation = ReaderPresentation.resolve(target: target, doc: doc, textCount: scalars.count)
+        let presentation = jump.map {
+            ReaderPresentation.citation($0, truncated: doc.truncated, textCount: scalars.count)
+        } ?? ReaderPresentation.resolve(target: target, doc: doc, textCount: scalars.count)
+        let rows = citations?.citations ?? []
+        let stops = ReaderNavigator.stops(rows, subjectId: target.subjectId)
         let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: presentation.focus,
-                                         focusStyle: presentation.focusStyle)
+                                         focusStyle: presentation.focusStyle,
+                                         others: stops.filter { $0 != presentation.focus })
         let landingBlock = presentation.landing.flatMap { ReaderLayout.blockIndex(containing: $0, in: blocks) }
         return ScrollViewReader { proxy in
-            ScrollView {
-                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
-                    ForEach(presentation.banners, id: \.self) { banner in
-                        ReaderBannerView(banner: banner)
+            VStack(alignment: .leading, spacing: 0) {
+                // Pinned ABOVE the text, never inside it: landing scrolls the
+                // cited turn to the centre, so a bar at the top of the scrolled
+                // stack would leave the screen the moment the Reader arrives
+                // (and, lazily unrealised, take ⌥↑ / ⌥↓ with it).
+                if stops.count > 1 {
+                    navigator(stops: stops, rows: rows, subjectId: target.subjectId,
+                              position: ReaderNavigator.position(of: presentation.focus, in: stops))
+                        .padding(.horizontal, CicadaTheme.spacingMD)
+                        .padding(.vertical, CicadaTheme.spacingSM)
+                    Divider().background(CicadaTheme.border)
+                }
+                ScrollView {
+                    LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
+                        ForEach(presentation.banners, id: \.self) { banner in
+                            ReaderBannerView(banner: banner)
+                        }
+                        if blocks.isEmpty {
+                            message(Copy.Provenance.empty, icon: "text.bubble")
+                        }
+                        ForEach(blocks) { block in
+                            ReaderTurnView(block: block, isLanding: block.index == landingBlock,
+                                           revealed: washVisible)
+                                .id(block.index)
+                        }
                     }
-                    if blocks.isEmpty {
-                        message(Copy.Provenance.empty, icon: "text.bubble")
+                    .padding(CicadaTheme.spacingMD)
+                }
+                .accessibilityRotor("Cited passages") {
+                    ForEach(blocks.filter(\.holdsFocus)) { block in
+                        AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
+                                                id: block.index)
                     }
+                }
+                .accessibilityRotor("Turns") {
                     ForEach(blocks) { block in
-                        ReaderTurnView(block: block, isLanding: block.index == landingBlock,
-                                       revealed: washVisible)
-                            .id(block.index)
+                        AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
+                                                id: block.index)
                     }
                 }
-                .padding(CicadaTheme.spacingMD)
+                .onChange(of: landingToken, initial: true) { _, _ in
+                    land(proxy: proxy, block: landingBlock, blocks: blocks, presentation: presentation)
+                }
+            }
+        }
+    }
+
+    // MARK: Navigator (P4)
+
+    /// "‹ 2 of 5 cited here ›" — steps through the spans this entity's claims
+    /// cite in this document (or every cited span when the Reader was not
+    /// opened for an entity). ⌥↓ / ⌥↑ from anywhere in the Reader.
+    private func navigator(stops: [Range<Int>], rows: [EpisodeCitation], subjectId: String?,
+                           position: Int?) -> some View {
+        HStack(spacing: CicadaTheme.spacingSM) {
+            Button { step(-1, stops: stops, rows: rows, subjectId: subjectId, position: position) } label: {
+                Image(systemName: "chevron.up")
+            }
+            .keyboardShortcut(.upArrow, modifiers: .option)
+            .accessibilityLabel(Copy.Provenance.previousCited)
+            .disabled(position == 0)
+            Text(ReaderNavigator.label(position: position, count: stops.count))
+                .font(CicadaTheme.captionFont)
+                .foregroundStyle(CicadaTheme.textSecondary)
+            Button { step(1, stops: stops, rows: rows, subjectId: subjectId, position: position) } label: {
+                Image(systemName: "chevron.down")
+            }
+            .keyboardShortcut(.downArrow, modifiers: .option)
+            .accessibilityLabel(Copy.Provenance.nextCited)
+            .disabled(position == stops.count - 1)
+            Spacer()
+        }
+        .buttonStyle(.cicadaPlain)
+        .font(CicadaTheme.font(size: 11, weight: .semibold))
+    }
+
+    private func step(_ delta: Int, stops: [Range<Int>], rows: [EpisodeCitation], subjectId: String?,
+                      position: Int?) {
+        guard let next = ReaderNavigator.step(from: position, count: stops.count, by: delta) else { return }
+        let stop = stops[next]
+        let candidates = rows.filter { $0.range == stop }
+        jumpTo(candidates.first { $0.subjectId == subjectId } ?? candidates.first)
+    }
+
+    private func jumpTo(_ citation: EpisodeCitation?) {
+        guard let citation, citation.range != nil else { return }
+        washVisible = false
+        jump = citation
+        landingToken &+= 1
+    }
+
+    // MARK: Noted from this conversation (P4, G106 (ii))
+
+    /// Every belief this document contributed, each with its subject's mark
+    /// and how it was sourced. A row with offsets jumps the text to its words;
+    /// the trailing pin lands on the subject in the graph (G123).
+    private func notedList(_ payload: EpisodeCitations, doc: EpisodeText) -> some View {
+        let noted = payload.citations
+        let citedIds = Set(noted.map(\.subjectId))
+        let alsoOn = payload.entities.filter { !citedIds.contains($0.entityId) }
+            .map { $0.name.isEmpty ? $0.entityId : $0.name }
+        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
+            Text("\(doc.isPage ? Copy.Provenance.notedFromThisPage : Copy.Provenance.notedFromThisConversation)"
+                 + " (\(UsageFormat.count(noted.count)))")
+                .font(CicadaTheme.captionFont)
+                .foregroundStyle(CicadaTheme.textTertiary)
+                .accessibilityAddTraits(.isHeader)
+            if noted.isEmpty {
+                Text(Copy.Provenance.nothingNoted)
+                    .font(CicadaTheme.captionFont)
+                    .foregroundStyle(CicadaTheme.textTertiary)
             }
-            .accessibilityRotor("Cited passages") {
-                ForEach(blocks.filter(\.holdsFocus)) { block in
-                    AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
-                                            id: block.index)
+            ScrollView {
+                VStack(alignment: .leading, spacing: 2) {
+                    ForEach(noted) { row in notedRow(row, doc: doc) }
                 }
             }
-            .accessibilityRotor("Turns") {
-                ForEach(blocks) { block in
-                    AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
-                                            id: block.index)
+            .frame(maxHeight: CicadaTheme.scaled(200))
+            if !alsoOn.isEmpty {
+                Text(Copy.Provenance.alsoOn(alsoOn))
+                    .font(CicadaTheme.captionFont)
+                    .foregroundStyle(CicadaTheme.textTertiary)
+                    .lineLimit(2)
+            }
+            if payload.partial {
+                Text(Copy.Provenance.notedPartial)
+                    .font(CicadaTheme.captionFont)
+                    .foregroundStyle(CicadaTheme.textTertiary)
+            }
+        }
+        .padding(CicadaTheme.spacingMD)
+    }
+
+    private func notedRow(_ row: EpisodeCitation, doc: EpisodeText) -> some View {
+        let name = row.subjectName.isEmpty ? row.subjectId : row.subjectName
+        let label = EvidenceLabel.speaker(kind: row.displayKind,
+                                          agent: EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin))
+        return HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
+            Button { jumpTo(row) } label: {
+                HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
+                    LogoImage(entityId: row.subjectId, name: name,
+                              type: EntityType(rawValue: row.subjectType) ?? .concept, size: CicadaTheme.scaled(18))
+                    VStack(alignment: .leading, spacing: 1) {
+                        Text(renderWikilinks(row.text.isEmpty ? name : row.text))
+                            .font(CicadaTheme.font(size: 12))
+                            .strikethrough(!row.current)
+                            .lineLimit(2)
+                        Text(row.current ? label : "\(label) · \(Copy.Provenance.noLongerCurrent)")
+                            .font(CicadaTheme.captionFont)
+                            .foregroundStyle(CicadaTheme.textTertiary)
+                    }
+                    Spacer(minLength: 0)
                 }
+                .contentShape(Rectangle())
             }
-            .onChange(of: landingToken, initial: true) { _, _ in
-                land(proxy: proxy, block: landingBlock, blocks: blocks, presentation: presentation)
+            .buttonStyle(.cicadaPlain)
+            .disabled(row.range == nil)
+            .opacity(row.current ? 1 : 0.6)
+            Button {
+                appRouter.pendingTab = .graph
+                graphVM.revealEntity(id: row.subjectId)
+            } label: {
+                Image(systemName: "scope").font(CicadaTheme.font(size: 11))
             }
+            .buttonStyle(.cicadaPlain)
+            .foregroundStyle(CicadaTheme.textTertiary)
+            .help(Copy.Provenance.showOnGraph(name))
+            .accessibilityLabel(Copy.Provenance.showOnGraph(name))
         }
+        .padding(.vertical, 3)
     }
 
     /// Scroll to the cited turn after the first layout, fade the wash in over
```

Modify `Theme/Copy+Provenance.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
index 20d8c22..54ed70e 100644
--- a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
@@ -107,3 +107,18 @@ extension Copy.Provenance {
         n == 1 ? "1 conversation" : "\(UsageFormat.count(n)) conversations"
     }
 }
+
+// MARK: - The Reader's reverse direction (§4.4, G106 (ii)) — Task 5
+
+extension Copy.Provenance {
+    static let notedFromThisConversation = "Noted from this conversation"
+    static let notedFromThisPage = "Noted from this page"
+    static let nothingNoted = "Nothing in memory cites this yet."
+    /// R-PB10: `partial` means the server stopped at its page cap.
+    static let notedPartial = "Some pages that name this conversation aren't listed here."
+    static func alsoOn(_ names: [String]) -> String { "Also on: \(names.joined(separator: ", "))" }
+    static let nextCited = "Next cited passage"
+    static let previousCited = "Previous cited passage"
+    static func showOnGraph(_ name: String) -> String { "Show \(name) on the graph" }
+    static let noLongerCurrent = "No longer current"
+}
```

- [ ] **Step 4: Green, then the whole suite.**
`swift test --filter "ReaderNavigatorTests|ReaderTurnsTests" 2>&1 | tail -5` → 22 tests, 0 failures.
`swift build` and `swift test` → **1143 executed, 0 failures**.

- [ ] **Step 5: Commit.**
```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderModel.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/ReaderInspector.swift \
  app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift \
  app/CicadaApp/Tests/CicadaAppTests/ReaderNavigatorTests.swift \
  && git commit -m "feat(provenance-ui): the Reader's navigator and Noted from this conversation (G118 s2, P4)"
```
Body: name G106 (ii), R-PU9 (the pinned navigator bar), R-PU21, R-PB10's `partial`; attribution trailer.

---

### Task 6: "Show in conversation" from the inbox; evidence under Ask answers (P5)

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift:125-161` (doc fix + `InboxCause.readerTarget`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift:31, 82-85, 175-184`
- Modify: `app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift:126-131` (+ `AskEvidenceRow`)
- Modify: `app/CicadaApp/Sources/CicadaApp/ContentView.swift:124` (the Ask sheet steps aside, R-PU20)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift` (`AskCitation.evidenceChips`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift` (append)
- Test (new): `app/CicadaApp/Tests/CicadaAppTests/ProvenanceEntryPointTests.swift`

**Interfaces:**
- Produces: `InboxCause.readerTarget(subjectId:)`; `AskCitation.evidenceChips`; `AskEvidenceRow` (private).
- Consumes: `ProvenanceRouter.open`/`revision`, `EvidenceChipRun`, `EvidenceChipModel.chips`, `OriginMark`, `CicadaTheme.quoteFont(size:)`.

- [ ] **Step 1: Failing tests.** `app/CicadaApp/Tests/CicadaAppTests/ProvenanceEntryPointTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Design §4.7 (P5) — the inbox and Ask reach the same Reader: an inbox
/// cause opens on its mention (labelled derived unless it was an asserted
/// G118 span), and an answer's sources carry evidence chips.
final class ProvenanceEntryPointTests: XCTestCase {

    private func cause(_ json: String) throws -> InboxCause {
        try JSONDecoder().decode(InboxCause.self, from: Data(json.utf8))
    }

    // MARK: Inbox

    func testADerivedCauseOpensOnTheMentionWithNoHashAndStaysDerived() throws {
        // The excerpt window starts at 900; the mention is excerpt[30, 40).
        let c = try cause("""
        {"episodeId": "ep_2026-09-03_004", "harness": "claude-code", "conversationTitle": "Index choice",
         "excerpt": "…", "mentionOffsets": [[30, 40]], "start": 900, "end": 1300,
         "tier": "claim", "spanKind": "derived"}
        """)
        let target = c.readerTarget(subjectId: "alpha-project")
        XCTAssertEqual(target?.episode, "ep_2026-09-03_004")
        XCTAssertEqual(target?.focus, .span(start: 930, end: 940, hash: nil, derived: true),
                       "R-PB16 — start is the WINDOW's offset; the mention sits at start + m0")
        XCTAssertEqual(target?.subjectId, "alpha-project")
        XCTAssertEqual(target?.knownTitle, "Index choice")
        XCTAssertEqual(target?.knownHarness, "claude-code")
    }

    func testAnAssertedCauseLandsWashed() throws {
        let c = try cause("""
        {"episodeId": "ep_1", "excerpt": "…", "mentionOffsets": [[0, 5]], "start": 10, "tier": "item",
         "spanKind": "asserted"}
        """)
        XCTAssertEqual(c.readerTarget(subjectId: nil)?.focus, .span(start: 10, end: 15, hash: nil, derived: false))
    }

    func testACauseWithNoMentionOpensAtTheTopAndNoSourceOpensNothing() throws {
        let top = try cause(#"{"episodeId": "ep_1", "excerpt": "head", "start": 0, "tier": "entity"}"#)
        XCTAssertEqual(top.readerTarget(subjectId: "a")?.focus, ReaderTarget.Focus.none)
        let none = try cause(#"{"excerpt": "[ no source recorded ]", "tier": "none"}"#)
        XCTAssertNil(none.readerTarget(subjectId: "a"))
        let noEpisode = try cause(#"{"excerpt": "x", "tier": "claim", "mentionOffsets": [[0, 1]], "start": 0}"#)
        XCTAssertNil(noEpisode.readerTarget(subjectId: "a"))
    }

    // MARK: Ask

    func testAClaimHitCarriesItsStoredSpansAsChips() {
        let hit = AskCitation(entityId: "alpha-project", entityName: "Alpha project", filePath: "", snippet: "s",
                              sourceEpisodes: ["ep_9"], claimId: "clm_1",
                              evidence: [Evidence(episode: "ep_1", start: 1, end: 5, kind: .user, hash: "h")])
        XCTAssertEqual(hit.evidenceChips.map(\.kind), [.user])
    }

    func testAnEntityOnlyHitFallsBackToDerivedChipsAndNothingMeansNoRow() {
        let entity = AskCitation(entityId: "alpha-project", entityName: "Alpha project", filePath: "", snippet: "s",
                                 sourceEpisodes: ["ep_1", "ep_2"])
        XCTAssertEqual(entity.evidenceChips.map(\.kind), [.derived, .derived])
        let bare = AskCitation(entityId: "alpha-project", entityName: "Alpha project", filePath: "", snippet: "s")
        XCTAssertTrue(bare.evidenceChips.isEmpty)
    }
}
```

- [ ] **Step 2: Watch them fail.** `swift test --filter ProvenanceEntryPointTests 2>&1 | tail -20` →
compile errors naming `readerTarget` and `evidenceChips`.

- [ ] **Step 3: Implement.** Modify `Models/InboxItem.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift b/app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift
index cefb964..a97ac84 100644
--- a/app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift
@@ -125,7 +125,10 @@ extension InboxOption: Codable {
 /// Why an item exists (G97): the conversation and sentence that raised it,
 /// resolved server-side at read. `mentionOffsets` index the EXCERPT as
 /// Unicode-scalar offsets (Python `str` indices); `start`/`end` are the
-/// absolute offsets into the episode body. `tier == "none"` carries the literal
+/// EXCERPT WINDOW's absolute offsets into the episode body
+/// (`inbox_context.excerpt_around` — G118 slice 2 corrected this comment,
+/// which used to call them the mention's), so the mention itself sits at
+/// `start + mentionOffsets[0]` (R-PB16). `tier == "none"` carries the literal
 /// `[ no source recorded ]` in `excerpt` — shown, never hidden.
 struct InboxCause: Codable, Hashable {
     var episodeId: String?
@@ -290,3 +293,23 @@ extension InboxItem {
         items.filter { $0.kind == .removal && $0.channel == channelId }
     }
 }
+
+extension InboxCause {
+    /// Where "Show in conversation" opens (G118 slice 2, design §4.7, R-PB16):
+    /// the mention's absolute offsets, asked for with NO hash — the cause is
+    /// recomputed at every read, so it is current by construction. A cause
+    /// found by name (`spanKind == "derived"`) stays labelled derived in the
+    /// Reader; an asserted G118 span lands washed. A cause with no mention
+    /// opens its conversation at the top; tier `none` has nothing to open.
+    func readerTarget(subjectId: String?) -> ReaderTarget? {
+        guard tier != "none", let episodeId, !episodeId.isEmpty else { return nil }
+        if let start, let pair = mentionOffsets.first, pair.count == 2, pair[0] >= 0, pair[1] > pair[0] {
+            return ReaderTarget(episode: episodeId,
+                                focus: .span(start: start + pair[0], end: start + pair[1], hash: nil,
+                                             derived: spanKind != "asserted"),
+                                subjectId: subjectId, knownTitle: conversationTitle, knownHarness: harness)
+        }
+        return ReaderTarget(episode: episodeId, subjectId: subjectId, knownTitle: conversationTitle,
+                            knownHarness: harness)
+    }
+}
```

Modify `Views/Provenance/EvidenceChipModel.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift b/app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift
index c72d556..acfd54f 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift
@@ -202,3 +202,13 @@ enum EvidenceLabel {
         }
     }
 }
+
+extension AskCitation {
+    /// An answer's source snippets as evidence chips (§4.7, P5): the claim's
+    /// stored spans when the hit was a claim (R-PB12), else — an entity-only
+    /// hit, or a legacy claim — derived chips for the conversations the page
+    /// lists, capped like any legacy claim.
+    var evidenceChips: [EvidenceChipModel] {
+        EvidenceChipModel.chips(evidence: evidence, sourceEpisodes: sourceEpisodes, subjectId: entityId)
+    }
+}
```

Modify `Views/Inbox/InboxCardView.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift b/app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift
index bddf6dc..b00a23c 100644
--- a/app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift
@@ -29,6 +29,8 @@ struct InboxCardView: View {
     /// lines until this is flipped.
     @State private var showAllLines = false
     @Environment(\.accessibilityReduceMotion) private var reduceMotion
+    /// G118 slice 2 (§4.7) — "Show in conversation" opens the Reader here.
+    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
 
     private enum MergeSurvivor { case existing, mention }
 
@@ -79,10 +81,17 @@ struct InboxCardView: View {
                     .foregroundStyle(CicadaTheme.textPrimary)
                     .lineLimit(isExpanded ? nil : 1)
 
-                Text(item.causeLine())
-                    .font(CicadaTheme.captionFont)
-                    .foregroundStyle(CicadaTheme.textSecondary)
-                    .lineLimit(isExpanded ? nil : 1)
+                HStack(spacing: 4) {
+                    // G118 slice 2 (§4.7) — the harness's real mark beside
+                    // the cause, like every other place a conversation is named.
+                    if item.hasCause, let origin = item.cause?.harness ?? item.cause?.origin, !origin.isEmpty {
+                        OriginMark(origin: origin, size: CicadaTheme.scaled(12))
+                    }
+                    Text(item.causeLine())
+                        .font(CicadaTheme.captionFont)
+                        .foregroundStyle(CicadaTheme.textSecondary)
+                        .lineLimit(isExpanded ? nil : 1)
+                }
             }
 
             Spacer()
@@ -173,13 +182,30 @@ struct InboxCardView: View {
     /// (±240 chars server-side), so this pane can never become the owner's
     /// "list of URLs that doesn't end".
     private func excerptPane(_ cause: InboxCause) -> some View {
-        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
-            RoundedRectangle(cornerRadius: 1.5).fill(CicadaTheme.borderLight).frame(width: 3)
-            Text(ExcerptText.attributed(cause.excerpt, bold: cause.mentionOffsets))
-                .font(CicadaTheme.font(size: 12))
-                .foregroundStyle(CicadaTheme.textSecondary)
-                .fixedSize(horizontal: false, vertical: true)
-                .textSelection(.enabled)
+        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
+            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
+                RoundedRectangle(cornerRadius: 1.5).fill(CicadaTheme.borderLight).frame(width: 3)
+                // G118 slice 2 (§4.7): a quoted sentence reads in the quote
+                // face (R-M3), the same as every other provenance quote.
+                Text(ExcerptText.attributed(cause.excerpt, bold: cause.mentionOffsets))
+                    .font(CicadaTheme.quoteFont(size: 12))
+                    .foregroundStyle(CicadaTheme.textSecondary)
+                    .fixedSize(horizontal: false, vertical: true)
+                    .textSelection(.enabled)
+            }
+            if let provenance,
+               let target = cause.readerTarget(subjectId: item.entityId.isEmpty ? nil : item.entityId) {
+                Button {
+                    provenance.open(target)
+                } label: {
+                    Label(Copy.Provenance.showInConversation, systemImage: "text.book.closed")
+                        .labelStyle(.titleAndIcon)
+                }
+                .buttonStyle(.cicadaPlain)
+                .font(CicadaTheme.captionFont)
+                .foregroundStyle(CicadaTheme.accent)
+                .padding(.leading, CicadaTheme.spacingMD + 3)
+            }
         }
     }
 
```

Modify `Ask/AskPanel.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift b/app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift
index b922076..ecc2813 100644
--- a/app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift
@@ -128,6 +128,14 @@ struct AskPanel: View {
                             citationChip(row.citation)
                         }
                     }
+
+                    // G118 slice 2 (§4.7, P5) — the words behind each source:
+                    // hover a chip for the sentence, click for the conversation
+                    // (the Reader opens beside the window; this sheet steps
+                    // aside, `ContentView`).
+                    ForEach(answer.citationRows.filter { !$0.citation.evidenceChips.isEmpty }, id: \.id) { row in
+                        AskEvidenceRow(citation: row.citation)
+                    }
                 }
             }
 
@@ -297,3 +305,22 @@ struct AskChipFlowLayout: Layout {
         }
     }
 }
+
+/// One cited page's evidence under an answer: its name, then its chips.
+private struct AskEvidenceRow: View {
+    let citation: AskCitation
+    @State private var expanded = false
+
+    var body: some View {
+        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
+            Text(citation.entityName)
+                .font(CicadaTheme.captionFont)
+                .foregroundStyle(CicadaTheme.textTertiary)
+                .lineLimit(1)
+                .frame(maxWidth: CicadaTheme.scaled(140), alignment: .leading)
+            AskChipFlowLayout(spacing: 6) {
+                EvidenceChipRun(chips: citation.evidenceChips, subjectId: citation.entityId, expanded: $expanded)
+            }
+        }
+    }
+}
```

Modify `ContentView.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/ContentView.swift b/app/CicadaApp/Sources/CicadaApp/ContentView.swift
index f4902b1..316d56a 100644
--- a/app/CicadaApp/Sources/CicadaApp/ContentView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/ContentView.swift
@@ -132,6 +132,10 @@ struct ContentView: View {
             showFirstRun = true
             router.pendingFirstRun = false
         }
+        // G118 slice 2 (P5) — an evidence chip inside the Ask sheet opens the
+        // Reader, which lives on THIS window; the sheet steps aside so the
+        // person sees the sentence instead of a modal covering it.
+        .onChange(of: provenance.revision) { _, _ in showAskPanel = false }
         .sheet(isPresented: $showAskPanel) {
             // G123: a citation lands ON its node — the graph zooms to that
             // node's neighbourhood, not just opens its card. An answer's
```

Modify `Theme/Copy+Provenance.swift`:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
index 54ed70e..26d1357 100644
--- a/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift
@@ -122,3 +122,9 @@ extension Copy.Provenance {
     static func showOnGraph(_ name: String) -> String { "Show \(name) on the graph" }
     static let noLongerCurrent = "No longer current"
 }
+
+// MARK: - Inbox and Ask (§4.7, P5) — Task 6
+
+extension Copy.Provenance {
+    static let showInConversation = "Show in conversation"
+}
```

- [ ] **Step 4: Green, then the whole suite.**
`swift test --filter "ProvenanceEntryPointTests|InboxPresentationTests|AskHistoryTests|StateCoverageTests" 2>&1 | tail -5`
→ 26 tests, 0 failures. `swift build` and `swift test` → **1148 executed, 0 failures**.
`cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → 7 pass, 0 fail (no JS change).

- [ ] **Step 5: Commit.**
```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift \
  app/CicadaApp/Sources/CicadaApp/ContentView.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Provenance/EvidenceChipModel.swift \
  app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProvenanceEntryPointTests.swift \
  && git commit -m "feat(provenance-ui): Show in conversation from the inbox; evidence under Ask answers (G118 s2, P5)"
```
Body: name R-PB16, R-PU20, R-PU24, G115; attribution trailer.

---

### Task 7: Docs move with the code

**Files:**
- Modify: `docs/goals/memory-evolution.md` — **G118** (slice 2 app shipped, what stays open, status),
  **G103**, **G106**, **G115** (cross-references appended; their status is unchanged)
- Modify: `docs/goals/TODO.md` — the In-progress row, Wave C item 9b
- Modify: `CLAUDE.md` — Companion App: a "Provenance viewer (G118 slice 2)" paragraph

- [ ] **Step 1: Apply.** Seven exact replacements, each anchored on text that occurs once on this
base (checked). Privacy-checked: no names, no bank contents; `<agent>` is a placeholder in the prose,
not a value. The G118/G103/G106/G115 cells are single table lines — replace within the line, keep
the row one line.

**1. G118 — slice 2 app shipped, what stays open, status** — in `docs/goals/memory-evolution.md`, replace exactly (it occurs once):

````text
**Open:** the Swift viewer (P1–P6 client, after Meadow M1), per-turn times for Stop-hook episodes (their `turns` key is a count today), slice 3 trigger traces, slice 4 rationale, `describes` claims on link enrichment. | 🛠️ slice 1 ✅ (PR #44); slice 2 server ✅; viewer + slices 3–4 open |
````

with:

````text
**Slice 2, the app, built 2026-09-23 (`feat/provenance-ui`, plan `docs/superpowers/plans/2026-09-23-provenance-ui.md`):** the app decodes `evidence` (dropped since slice 1 — `Claim.CodingKeys` never named it) and every slice-2 payload tolerantly, and slices every offset as a Unicode scalar through one `ScalarText`. Every claim carries **evidence chips** — "You said", "<agent> replied", "From the page", "Inferred", or "Mentioned here" for a legacy claim's name match — whose hover preview shows the words in the quote face, washed when quoted ("Quoted by the contributor"), bold when derived ("Found by searching the conversation"), plain when stale; a click opens the **Reader**, a trailing inspector beside whatever is open, with the conversation as turns (speaker labels, a time only where one is stored), scrolled to the washed span, stale/grown/derived/inferred/truncated said in words, the capture-honesty line, Resume, a "cited here" navigator and "Noted from this conversation" (the inverse index, each belief jumping to its words or landing on the graph). The entity card gains **"Where this came from"** — the writers with their real marks and two nouns (beliefs, edits), the conversations that fed it with the best sentence of each, and coverage stated as "N of M beliefs here have an exact quote"; G61's "Sources" became "Look it up at"; the claim footer and the History tab draw `ContributorAvatar` with plain trust words; the inbox cause gains its harness mark and "Show in conversation"; Ask answers carry evidence chips. Nothing is written, cached on disk, or made a Store domain. **Open:** P6 (palette rows → the Reader, Track S), find-in-conversation (Track S's search field), an episode id on `ConversationSummary` (so "Open conversation" works outside an entity card), a `span` read-telemetry surface, a speaker name on `/span` for meeting chips, a remote write's app label bucketed as `harness` by `author_identity` (it reads as a model today), seeking a video from a `media` chip, per-turn times for Stop-hook episodes (their `turns` key is a count today), slice 3 trigger traces, slice 4 rationale, `describes` claims on link enrichment. | 🛠️ slice 1 ✅ (PR #44); slice 2 ✅ (server PR #72, app PR #88); slices 3–4 open |
````

**2. G103 — cross-reference** — in `docs/goals/memory-evolution.md`, replace exactly (it occurs once):

````text
per-claim observer labels and "who was in the room" stay this row's. | 🔲 |
````

with:

````text
per-claim observer labels and "who was in the room" stay this row's. **G118 slice 2 (app) renders who wrote what:** every claim's footer names its writer with the contributors strip's own face (`ContributorAvatar` — a provider's real mark, "You", or Cicada's bookworm) and a plain trust word ("You told Cicada", "Cicada noticed", "Cicada concluded", "From a source"); every evidence chip says who spoke — "You said", "<agent> replied", and "Someone else said" for a meeting speaker, never "you" (R-N2); the entity card's "Where this came from" lists the writers with belief and edit counts. The inbox option's observer label and a meeting's "who was in the room" stay this row's. | 🔲 |
````

**3. G106 — cross-reference** — in `docs/goals/memory-evolution.md`, replace exactly (it occurs once):

````text
(i)'s content search and the page itself remain (Track S, the Swift viewer). | 🔲 |
````

with:

````text
(i)'s content search and the page itself remain (Track S, the Swift viewer). **G118 slice 2 (app) closes (ii) and (iii) in the UI:** the Reader opens a conversation at the cited sentence from a claim's evidence chip, a "Where this came from" row, an inbox cause or an Ask citation, steps through the spans the entity cites, and lists "Noted from this conversation" with each belief jumping to its words or landing on the graph; (i)'s browse-and-search page remains (Track S). | 🔲 |
````

**4. G115 — cross-reference** — in `docs/goals/memory-evolution.md`, replace exactly (it occurs once):

````text
the Reader opens `GET /episodes/{id}/text?start=&end=` at the cause window's absolute offset plus the mention offset. | 🔲 |
````

with:

````text
the Reader opens `GET /episodes/{id}/text?start=&end=` at the cause window's absolute offset plus the mention offset. **G118 slice 2 (app):** the cause line wears its harness's real mark, the excerpt reads in the quote face, and "Show in conversation" opens the Reader on the mention — a cause found by name stays labelled found by name there. | 🔲 |
````

**5. TODO — the In-progress row** — in `docs/goals/TODO.md`, replace exactly (it occurs once):

````text
| **G118 slice 2 — server half** | **Merged** from `feat/provenance-viewer` (plan `2026-09-23-provenance-backend.md`): `grown` spans, `/episodes/{id}/text`, `/entities/{id}/provenance`, `/episodes/{id}/citations`, `/ask` evidence, per-turn import times. | Next: the Swift viewer track (P1–P6 client), now that Meadow M1 has landed. |
````

with:

````text
| **G118 slice 2** | **Server merged** (PR #72, plan `2026-09-23-provenance-backend.md`). **App built** on `feat/provenance-ui` (plan `2026-09-23-provenance-ui.md`): evidence chips with a hover quote, the Reader inspector (turns, washed span, honest banners, navigator, "Noted from this conversation"), "Where this came from" on the entity card, contributor faces in the claim footer and History, "Show in conversation" from the inbox, evidence under Ask answers. | Orchestrator live check on the demo bank (the plan's Verification), then merge. P6 (palette → Reader) rides Track S; the server hand-offs are listed in the G118 row. |
````

**6. TODO — Wave C item 9b** — in `docs/goals/TODO.md`, replace exactly (it occurs once):

````text
    the vision (2026-09-02). Slice 1 shipped (spans + agent citations + span endpoint, PR #44); next:
    slice 2 viewer (Swift `Evidence` model, chips → raw pane with highlight), then triggers (G105 shipped —
    unblocked),
    then rationale — L
````

with:

````text
    the vision (2026-09-02). Slice 1 shipped (spans + agent citations + span endpoint, PR #44); slice 2
    shipped (server PR #72; the app's chips, Reader and "Where this came from", plan
    `2026-09-23-provenance-ui.md`); next: triggers (G105 shipped — unblocked), then rationale — L
````

**7. CLAUDE.md — Companion App, after the Video (Track V) paragraph** — in `CLAUDE.md`, replace exactly (it occurs once):

````text
needs rewriting to teach the app a new one.

---

## API Design
````

with:

````text
needs rewriting to teach the app a new one.

**Provenance viewer (G118 slice 2).** Every claim carries evidence chips (`Views/Provenance/`): the
label says who spoke ("You said", "<agent> replied", "From the page", "Inferred", "Mentioned here"
for a legacy claim's name match found at read), hovering shows the words in the quote face — washed
when quoted, bold when derived, plain when stale — and a click opens the **Reader**, a trailing
`.inspector` on the main window driven by `ProvenanceRouter` (a stack of `ReaderTarget`s), beside
whatever is open so a belief and its sentence are on screen together. It reads `/episodes/{id}/text`
and `/citations` through `ProvenanceCache` — in memory, ETag-revalidated, **never a Store domain**,
so there is no `VersionVector` mapping — slices every offset as a Unicode scalar through one
`ScalarText`, shows a time only when the episode stores one, and says stale / grown / derived /
inferred / truncated in words — a span its rewritten document no longer reaches (the server's 422) is
stale too, never "couldn't open". The entity card's "Where this came from" (bottom of Content) reads
`/entities/{id}/provenance` once per card; G61's section is "Look it up at". Chips read the router
and cache as optional environment values, so a chip outside the main window renders without a
click-through rather than trapping; the Ask and Belief Timeline sheets step aside when the Reader
opens, and a bank switch closes it and empties the cache (episode ids repeat across banks).

---

## API Design
````

- [ ] **Step 2: Check.** `cd <worktree> && git diff --stat -- docs CLAUDE.md` → three files;
`rg -n "app PR #88" docs/goals/memory-evolution.md` → the one G118 status cell the orchestrator
fills at merge. `git diff --word-diff=plain -- docs CLAUDE.md | rg -o '\{\+[^}]*\+\}' | rg -c
'Rodrigo|/Users/|alpha-project'` → no output (the ADDED words name no one and quote nothing from a
bank). Word-level on purpose: each G row is one table line, so a line-level `rg '^\+'` would show the
whole rewritten row — including the owner's own pre-existing "Rodrigo 2026-09-01: …" quote, which the
privacy rule allows — and "fail" on text this task did not write.

- [ ] **Step 3: Commit.**
```
cd <worktree> && git add docs/goals/memory-evolution.md docs/goals/TODO.md CLAUDE.md \
  && git commit -m "docs(goals): G118 slice 2 app shipped; G103/G106/G115 cross-refs; TODO and CLAUDE.md"
```
Attribution trailer.

---

## Not in scope

- **Any server change** (`api/`, `mcp/`) — the gaps are hand-offs H1–H6.
- **The ⌘K palette and P6** (palette conversation/belief rows → the Reader) — Track S; the seam is
  R-PU19.
- **Find in conversation** — needs Track S's `CicadaSearchField` (S5).
- **MCP** — no tool, prompt or handshake change.
- **The Conversations page** (G106 (i): browse and search raw conversations) — Track S.
- **Read telemetry from the Reader** (H2), **seeking a video from a `media` chip** (H5), **per-turn
  times for Stop-hook episodes** (H4).
- **G118 slices 3–4** (trigger traces, rationale) and `describes` claims.
- **The inbox option's observer label and a meeting's "who was in the room"** — G103's own rows.
- **Evidence colours by nature token** — the design kept observer tokens (K13, §7.5), reversible
  only by the owner.
- Settings, onboarding, the mascot page, Meadow M2 restyling.

---

## Verification the orchestrator runs at the end

1. **Suites, by hand, on the branch tip.**
   `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -5` →
   **1148 executed, 0 failures** (1061 + 87, on `040f0fe`; a merge of the newer `dev` adds dev's own
   tests to both numbers). `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → 7 pass,
   0 fail. `git diff $(git merge-base HEAD dev) --stat -- api mcp` → empty (`dev` has moved past this
   base, so a bare `git diff dev` would list dev's own server work; the backend suite is unaffected —
   run it only if a merge touched `api/`).
2. **Rails, by grep.** `rg -n "glassEffect|liquidGlass" app/CicadaApp/Sources/CicadaApp/Views/Provenance`
   → nothing (content is never glass). `rg -n "Rodrigo|/Users/" app/CicadaApp/Sources/CicadaApp/Views/Provenance app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift`
   → nothing. `rg -n "\\$|token" app/CicadaApp/Sources/CicadaApp/Theme/Copy+Provenance.swift` → nothing
   (no prices or token counts).
3. **Live, on the demo bank** (install with the usual `make install-app`; drive with `macos-harness`,
   rows by accessibility; light and dark; 1.0× and 1.4×):
   - Graph → an entity with claims → Content tab, bottom: **"Where this came from"** — the
     conversations sentence, the writers sentence, contributor chips with real marks and "N beliefs ·
     N edits", conversation rows with a quote (a derived row says "Found by searching the
     conversation" and is bold, not washed), the coverage line; the section above it reads **"Look it
     up at"**.
   - Perspectives → a claim footer: author avatar + name, a plain trust word, evidence chips. Rest on
     a chip ~0.35 s → the preview (label, date, the quote in New York italic with the washed span,
     caption); move into it → it stays; leave → it closes after ~0.2 s.
   - Click a chip → the **Reader** opens BESIDE the card (the card stays), title in Instrument Serif,
     harness mark, meta line, the capture-honesty line (Stop-hook episodes only — a Telegram note or
     an MCP save shows none), scrolled to the washed span with the margin bar. A legacy chip →
     "Mentioned here", bold, derived banner. The "N cited here" bar stays in view above the text after
     landing, and **⌥↓/⌥↑** step it. Land on another entity with a Noted row's graph pin, click one of
     ITS chips (a second document), then **⌥⌘[** back to the first; **Esc** closes.
   - Switch banks with the Reader open → it closes; open a chip in the new bank → that bank's text,
     never the previous bank's (R-PU26).
   - History → author pills with faces; "from conversation" → **Open conversation** for a
     conversation this entity's provenance maps.
   - Inbox → expand a card with a cause → the harness mark on the cause line, the excerpt in the
     quote face, **Show in conversation** → the Reader on the mention.
   - ⌘K Ask → an answer with sources → evidence chips → click → the sheet closes and the Reader opens.
   - Reduce Motion on → the wash appears with no fade; hover lift and icon wiggle are inert.
     VoiceOver: a chip reads "You said, September 3, in … Opens the conversation."; the Reader's
     "Cited passages" rotor lists the landing turn.
   - **The design's two unverified items (§7):** open and close the Reader while the graph is still
     settling and watch for a reheat or a jump (`graph.js` only resets the canvas on resize) and the
     G109 p95 frame budget; and on macOS 14, type in the card's "Look it up at" field, rest on a chip,
     keep typing — the hover popover must not steal key focus.
   - `/entities/{id}/provenance` answers in ~0.5 s on the live bank (the brief's probe): the section
     shows its static placeholder, then fills, and nothing else on the card waits for it.
4. **Merge hygiene.** Resolve `ContentView.swift` against Track S if it merged first (R-PU20 moves to
   the palette); take the union in `docs/goals/*` and `CLAUDE.md`; replace `PR #88` in the G118 row.
