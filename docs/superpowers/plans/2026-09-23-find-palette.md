# The find palette and search fields (Track S-ui, G136 app half) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ⌘K stops being an Ask sheet and becomes a **find palette** (owner, 2026-09-23: "make sure to
add quick retrieval fast search bars"). Typing shows grouped results at once from what the app
already holds — entities, saved items, sources, inbox questions, settings, actions, banks, questions
asked before — and ~150 ms later the server's full-text index adds conversations (passages grouped
by conversation, with who said it), beliefs (with superseded ones shown as history, "Was … until
3 Sep") and anything the local tier missed, appended below what is already shown so nothing jumps.
Ask is a mode of the same panel (⌘⏎), hosting today's answer body unchanged. The keyboard does
everything (↑/↓, ⌘↑/⌘↓, Tab/⇧Tab, ⏎, ⌥⏎, ⌘⏎, Esc). ⌘K and ⌘F become real menu commands, and every
in-page search field — Graph, Clusters, Feed, a source's conversations, Inbox — is one component
ranked by one matcher. Finally `/graph` nodes carry `aliases`, after the payload growth is measured.

**Architecture:** One pure ranker (`QuickMatch`) folds text exactly like the server's `text_fold`
and ranks by tier × field weight. One immutable local index (`QuickIndex`), built off the main actor
from the `Store`'s snapshots whenever an input moves, answers every keystroke. One pure merge
(`FindMerge`) turns local rows and server rows into `FindResults` without ever reordering a shown
row, and one pure selection walker (`FindSelection`) drives the keys. An `@Observable`
`FindPaletteModel` owns the query, the mode, the debounced server passes (injected API and clock)
and an `AskViewModel`. The views (`FindPalette` overlay → `FindPanelBody` → `FindRowView`) are thin
renderers; `FindPanelBody` is public to the app so the upcoming Home page can host the same field.
`ContentView.openFind(_:)` is the one place a destination turns into navigation.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, macOS 14 floor, Swift 5.10 tools), Python 3 /
FastAPI / Pydantic (`api/`, Task 7 only), markdown + git bank.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` decisions 6, 7,
12 and **18** (binding) and `docs/superpowers/specs/2026-09-23-round3-design-settings-search-provenance.md`
§0, §1.1–§1.4, **§3** (all of it) and §6 slices **S3–S6** (binding where the brief does not override
them — the overrides are recorded as rulings below). The server this builds against merged in PR #74:
`docs/superpowers/plans/2026-09-23-search-backend.md` → "The wire", rulings G136 R1–R22. Backlog rows
**G136** (this track), **G93** (search/ask; cross-stream stays its own), **G123** (the graph node
search this generalises), **G118** (spans), **G137** (Meadow: glass, motion, fonts). Standing rulings:
no prices or tokens in the app (2026-09-03), ETag ship-together, telemetry ids-only, the privacy rule,
portability.

---

## What the code actually does today (verified against `feat/find-palette` @ `f7dfd21`)

Paths are relative to `app/CicadaApp/Sources/CicadaApp/` unless they start with `api/` or `app/`.

**⌘K, ⌘F and Ask.**
- `ContentView.swift:22-23` — `@State showAskPanel`. `:96-105` — ⌘K is a hidden zero-size `Button`
  with `.keyboardShortcut("k")`. `:124-135` — Ask is a `.sheet` presenting `AskPanel`, whose citation
  closure switches to Graph and calls `graphVM.revealEntity(id:)` (G123).
- `ContentView.swift:195` — `GraphContainerView(selectedTab:showAskPanel:)`; `:186-203` — the graph
  is **always mounted** under every other tab (opacity 0, hit-testing off), which is exactly why the
  graph field's hidden ⌘F button (`:596-602`) fires on an invisible field from Feed or Inbox (design
  §1.4, R6 §4.1). `:272` / `:506-533` — `AskButton` ("Ask", `sparkle.magnifyingglass`).
- `ContentView.swift:558-654` — `GraphSearchField`: plain `TextField` (`:575`), `.onKeyPress` for
  ↑/↓/Esc (`:581-583` — the proven key path this plan reuses), `.onSubmit` for ⏎ (`:580`), name-only
  matches through `graphVM.searchMatches` (`:567`), dropdown rows with a type dot and no logo.
- `Ask/AskPanel.swift:7-69` — the struct, `@State vm`, the body (`header` at `:23`, frame
  `560×460` at `:54`, `.task` creating the view model at `:61-68`). `:73-108` — `header` + `submit`.
  **`:110-253` — the answer body** (`answerView`, `citationChip` with the snippet only in `.help`
  at `:169`, `confidenceMeter`, `recentQuestions`, `errorBanner`). **Track P (Provenance UI) is
  editing that body in parallel** (design §3.5 items 1–2); this plan does not touch a line of it.
- `Ask/AskViewModel.swift:31-34` `loadHistory`, `:39-54` `ask()` (posts through `APIClient.shared`
  — **`/ask` spends**, so no test here may call it), `:58-61` `select(_:)`.

**Ranking today.**
- `ViewModels/GraphViewModel.swift:434-437` — `revealEntity(id:)`. `:442-446` — `searchMatches`.
  `:448-467` — `rankNames`: `lowercased()` prefix > space-split word start > contains, then degree,
  then name. Pinned by `app/CicadaApp/Tests/CicadaAppTests/GraphSearchRankTests.swift` (three tests —
  they must stay green unchanged).
- `ViewModels/FeedViewModel.swift:60-68` — title/site/tags `lowercased().contains`.
- `Views/Topics/TopicsView.swift:87-113` — `filteredEntities` lowercases name, tags **and the whole
  `markdownContent`** (the node summary, `GraphViewModel.swift:204-223`) on every keystroke;
  `:190` the field; `:640-685` `TopicRowListItem` draws the name with no highlight.
- `Models/SourceOverview.swift:239-245` — `ConversationFilter.apply`: lowercased substring over
  `displayTitle`, order kept (pinned by `SourcesPageTests.swift:85-94`).
  `Views/Sources/HarnessConversationsView.swift:21-24` — a `.roundedBorder` field over ≤ 200 loaded rows.
- `Views/Inbox/InboxListView.swift:12-19` — no search at all; `:108-111` `orderedKinds` omits
  `.divergence` and `.normalization` (R6 §2.6). `Views/Inbox/InboxCardView.swift:20` —
  `@State isExpanded = false`, no way to open a card expanded.
- `Models/InboxPresentation.swift:47-62` — `ExcerptText.attributed(_:bold:)` bolds `[start, end)`
  **Unicode-scalar** ranges and ignores out-of-range ones — the unit the server's `snippetOffsets`
  use (G136 R21). This plan reuses it for every bold run; there is no second highlighter.

**The network.**
- `Services/APIClient.swift:1875-1879` — `search(q:topK:)` sends `indexes=entities` and decodes the
  pre-G136 seven fields (`Models/GraphFilter.swift:76-114`, `GraphSearchHit`). **Nothing calls it.**
- `api/routers/search.py:28-47` + `api/models/schemas.py:1005-1070` — the merged server: `q`,
  `kinds` (`entity, claim, episode, media, inbox`, plus plural/palette aliases), `mode=prefix|hybrid`,
  `per_kind ≤ 20`; `SearchHit` = the old seven plus `kind, subtitle, snippetOffsets, matchedField,
  subjectId, episodeId, conversationId, harness, origin, timestamp, start, end, hash, evidenceKind,
  validFrom, validTo, supersededBy`; `SearchResponse` = `results, totals, mode, indexState`. Verified
  field-by-field; the Swift `Decodable` in Task 4 uses exactly these camelCase keys.
  `api/services/search_service.py:374-398` (claims: `subtitle` = subject name, `validTo`/`supersededBy`
  = history) and `:531-548` (episodes: `name` = title, `timestamp`, `evidenceKind` from
  `evidence.speaker_kind` — `user` | `assistant`).
- `Services/APIClient.swift:1401-1417` — `fetchRecentConversations(limit:harness:origin:)`; the server
  already takes `q` (`api/routers/conversations.py:97`, applied before the cap, G136 R17).
  `Sync/SyncAPI.swift:73` declares it; the only other conformer is `FakeSyncAPI`
  (`app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift:206`).
- `Views/Graph/EntityDetailCard.swift:368` — opening a card already posts the ids-only `read` event
  (`surface: "app"`); `api/models/schemas.py:280-283` accepts only `"app" | "mcp"`.

**Plumbing.**
- `Support/AppRouter.swift:14-87` — `pendingTab`, `pendingAddSource`, `pendingFirstRun`,
  `activateMainWindow()` (Track P R7). No palette, inbox, clusters or source hand-off yet. **Track Z
  (`feat/mascot-page`) adds `pendingSourceDetail` / `routeToSourceDetail(_:)` /
  `consumeSourceDetail()` here and the consumer in `Views/Sources/SourcesPageView.swift`** — this plan
  needs the same seam and reuses it (R-SU18). *Critic, 2026-09-23:* Track Z has since **merged into
  `dev` (PR #76, `0354538`)** with hunks byte-identical to the four seam blocks below, so Task 3
  Step 0's merge brings them in and those blocks are skipped.
- `Sync/Snapshot.swift:31-46` — `SyncDomain`, with `.askHistory` as the one cache-only domain;
  `Sync/Store.swift:283-285` skips it in `refresh`; `MutationTests.swift:317` subtracts it.
- `CicadaApp.swift:212-221` — the only `.commands` block (View → Zoom). `:95-106` — the main
  window's environment.
- `Views/Feed/FeedView.swift:153-196` — the Feed field; `:208-214` — a search that matches nothing
  shows **"Nothing saved yet"** (wrong: something is saved, nothing matched); `:440`
  `FeedItemPreviewSheet` is `private`.
- `Theme/LiquidGlass.swift:1-30` — chrome-only glass through `liquidGlass(_:in:)`; the header says
  **"Never over the graph canvas without the G109 frame-time check."** `Theme/CicadaMotion.swift` —
  the only home of a `duration:` (`MotionLiteralLintTests`).
- `Views/Common/SettingsSectionLink.swift` — the one way into Settings (a `SettingsLink` view; the
  seed key's single writer). `EmptyStateView.swift:8-14` forbids an `openSettings()` closure (A5,
  spike S0 is Track O's).

**Branches that touch the same files** (read with `git show`, never edited). *Updated by the critic,
2026-09-23 — `dev` moved while this plan was written:*
- **Track Z** (`feat/mascot-page`) — **merged, PR #76** (`0354538`): the source-detail hand-off above.
- **Track F** (`feat/local-sources`) — **merged, PR #77** (`dev` @ `a5fb5f1`): `MediaFeedItem.paper:
  PaperSummary?` (`authors: [String]`, `arxivId: String?`, `doi: String?`, `Models/Paper.swift`) and
  `nonisolated static func FeedViewModel.matches(_:query:)` (pinned by `PaperCardTests`), which
  `filteredItems` now calls. Task 5 Step 0's **Found** branch is therefore the expected one. Track F
  also touches `CicadaApp.swift` (a `localSources` environment line after `browserWatcher`),
  `SourceOverview.swift` (a `voice` kind) and `SettingsSectionLink.swift` (now generic over its label,
  with the same `init(section:label:)` convenience) — none of it conflicts with this plan's anchors.
- **Track P** (`feat/provenance-ui`) — **five commits (P1–P4), not merged**. Its `ProvenanceRouter`
  (`Views/Provenance/ProvenanceRouter.swift`) is an optional environment value, and its
  `ReaderTarget` is a **struct**, not design §1.4's enum: `ReaderTarget(episode:focus:subjectId:
  knownTitle:knownHarness:)` with `Focus` = `.none | .span(start:end:hash:derived:) |
  .mention(entityId:) | .inferred | .stale`, opened by `ProvenanceRouter.open(_:)`. Task 4 Step 0
  maps onto that shape. Track P still edits the Ask answer body and `InboxCardView`.

**Baselines:** backend green (the brief's 2225 predates #74/#75 — **re-measure**), Swift 0 failures
(the brief's 1,012 predates #72–#77 — **re-measure after Task 3 Step 0's merge**; at `dev` @ `a5fb5f1`
1,253 execute), graph node tests green. This track adds 64 Swift tests (65 with Task 5's Track F
paper case, now the expected branch) and 4 backend tests.

**How this plan was checked.** Every code block below was compiled and run while planning, against a
scratch copy of `app/CicadaApp` and `api/` at `f7dfd21` with Tasks 1–7 applied exactly as written
(the worktree was never touched): the package builds with no warning in the new files, all 64 new
Swift tests and the touched suites (lints included) pass, the full run executed 1,153 tests whose
only failures were three that read `<repo>/api/tests/fixtures/` by a repo-relative path the scratch
copy lacked (`VideoRefTests` ×2, `RemoteConnectorTests`), and the four S6 backend tests pass beside
`test_graph_builder.py`, `test_sync.py` and `test_graph_claim_overlay.py`. The view code compiles;
its behaviour is the orchestrator's live check.

**Re-checked by the plan critic (2026-09-23)** on a scratch export of `dev` @ `a5fb5f1` (Tracks Z and F
merged — exactly what Task 3 Step 0's merge produces), with Tasks 1–7 applied as written, Task 5's
Track F **Found** branch, and the critic's fixes folded in below (each marked *Critic*): `swift build`
clean with no warning in any new file, the full `swift test` **1,318 executed, 0 failures**, the full
backend suite **2,849 passed** with Task 7 (`test_graph_aliases.py` printed +16.9 % at the 8-alias
cap), and `node --test` 7/7.

---

## Global Constraints

- `<worktree>` is `<repo>/.worktrees/su` (branch `feat/find-palette`, based on `dev` @ `f7dfd21`). Work
  ONLY there. Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks a
  relative `cd`; ignore its stderr warning). Never an unquoted `--include=*.ext` (zsh globs it).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Fixtures are synthetic: `alpha-project`, `bob-example`, `beta-bank`, `example.com`,
  `claude-code`.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full
  `api/tests` suite must report **0 failures**. `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
  is order-dependent — if it is the ONLY red, re-run it alone and report both results.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures**. Graph JS: `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`.
  SourceKit diagnostics naming OTHER worktrees are noise. NEVER `make dev`, `make install-app`,
  `swift run`, or launch/kill the app or the launchd backend — the owner's app is live.
- **No test may reach the network.** `AskViewModel.ask()` posts `/ask` through `APIClient.shared`,
  which on a dev machine is the owner's live backend, and `/ask` spends. No test calls
  `FindPaletteModel.askNow()`, `activate` on an `.ask`/re-ask row, or constructs a
  `FindPaletteModel` without an injected `FindSearchAPI` once Task 4 lands.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv`, or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore
  Devin/PR comments.
- **Fonts:** every size through `CicadaTheme.font(size:weight:design:)`, every dimension through
  `CicadaTheme.scaled(_:)` or a spacing token; `displayFont` nowhere (it is ≥ 22 pt only, and nothing
  here is display type); snippets in `CicadaTheme.quoteFont(size:)`. **Motion:** only through
  `CicadaMotion` (the lint). **Glass:** only through `liquidGlass(_:in:)` (the lint). **Colour:** tokens
  only.
- **No prices, no tokens, no LLM** anywhere this track touches; the only spend in the palette is Ask
  mode's existing `/ask`.
- **The query is never stored, logged or sent anywhere but `GET /search` and
  `GET /conversations/recent?q=`** (design §3.8, K9). Recents are `(kind, id)` pairs.
- **Decode tolerance:** every new wire field is optional-with-default and tested against a payload
  that omits it (an old backend never blanks a view, R10).
- **Privacy (standing, 2026-09-02):** no owner name, no author-machine path, no bank contents in code,
  docs, commits or PR bodies.
- Docstrings explain **why**, citing the G-row, design section or ruling id. Match the density of the
  files touched.
- Line numbers above are from `f7dfd21` and drift as tasks land — read the cited code before editing.

---

## Rulings (binding)

The design's §3 and decision 18 hold. Everything below is a decision this plan takes where the brief
or the design left a choice, or where the code overrode the design; each carries its reason so no
task re-opens it.

- **R-SU1 — One folding rule on both tiers: the server's.** Design §1.2 sketched
  `folding(options: [.caseInsensitive, .diacriticInsensitive])`. The server's twin was amended at its
  final review (G136 R21, `api/services/text_fold.py:1-33`) to NFD + combining marks dropped +
  lowercase, because a full case fold rewrites "ß" as "ss" while FTS5 indexes it as written — the
  exact stored spelling then hit one tier and missed the other. `QuickMatch.fold` does the same per
  scalar (combining marks are dropped **before** lowercasing, so "İ" folds to "i" exactly as Python's
  `fold` does) and keeps a back-map, so every range is in **original Unicode scalars** — the unit
  `ExcerptText.attributed` and the server's `snippetOffsets` share.
- **R-SU2 — Tokens split on whitespace (design), up to eight, deduplicated after folding; a
  one-character token matches only at a field start or a word start.** "a" should list names that
  begin with a, not every name that contains one — and it keeps the first keystroke cheap. The server
  tier runs only when some token has two or more characters (`text_fold.MIN_TOKEN_CHARS`).
- **R-SU3 — Word starts are `unicode61`'s:** letters and numbers are word characters, everything else
  (including `_` and `-`) separates. Initials need a token of ≥ 2 characters that is a prefix of the
  field's word initials ("cc" → "Claude Code").
- **R-SU4 — `GraphViewModel.rankNames` becomes a wrapper over `QuickMatch.rank`** with the same
  signature; `GraphSearchRankTests` stays byte-identical and green. The design's "the graph typeahead
  and the palette can never rank one name differently" is satisfied by construction.
- **R-SU5 — What the local tier indexes, and when.** Graph nodes except facets, hubs and `media`
  nodes (a media page is a *Sources & papers* row, as the server's R8 reports it once under `media`);
  Feed items deduplicated by `mediaEntityId` (148 live bookmarks share one id, `FeedIdentityTests`);
  source cards; the *visible* inbox; `SettingsSection.allCases`; actions; banks; Ask history. The
  index is rebuilt off the main actor whenever an input's `loadedAt` (or a count that changes a
  title) moves, **eagerly from `ContentView`**, so the first ⌘K is instant rather than waiting on a
  build. A new index never reorders rows on screen: it applies on the next keystroke, or at once when
  nothing is typed or nothing is shown. *Critic:* the rebuild task lives in its own zero-size view
  (`FindIndexTask`), so the snapshots it watches re-evaluate that view, not `ContentView`'s whole body;
  and a build superseded while it ran (a bank switch mid-build — `Task.detached` ignores the `.task`
  cancellation) is dropped, never installed over the newer one.
- **R-SU6 — Recents are `(kind, id)` only, per bank, in a new cache-only `.quickRecents` domain
  handled exactly like `.askHistory`.** Only kinds the local tier can draw again are recorded
  (entity, media, source, inbox, setting, action, bank): a conversation or a belief lives only on the
  server, and redrawing one without its text would mean storing the text.
- **R-SU7 — Ask mode ships in Task 3, not with the server tier (S4)**, so no commit leaves ⌘K without
  Ask. **`AskPanel` is hosted, not rewritten:** it gains `hostedViewModel`; when set it drops its own
  header and fixed sheet size, and everything from `// MARK: - Answer` down is untouched, so Track P's
  parallel edits to that body merge without a conflict. The palette owns one long-lived
  `AskViewModel`. The design's `danger` token for the error banner (§3.5) is **not** done here — it
  is inside the body Track P is editing; a one-line follow-up after both merge.
- **R-SU8 — The mode switch is a native segmented `Picker`.** `PillPicker` is Track O's O1 component
  and is not on `dev`.
- **R-SU9 — ⌘K and ⌘F are menu commands in one file** (`Support/FindCommands.swift`,
  `CommandGroup(after: .textEditing)`), and `HiddenShortcutLintTests` fails the build on a
  `.keyboardShortcut("k"` / `("f"` anywhere else. ⌘F calls the scene's `pageFind` focused value, which
  a page publishes only while it is the visible page and the palette is closed; with none published
  the menu item is disabled, so an invisible field can never catch it (A6).
- **R-SU10 — The graph publishes ⌘F only while `selectedTab == .graph`** — it stays mounted under
  every other tab (`ContentView.swift:186-203`).
- **R-SU11 — Keys.** ↑/↓/⌘↑/⌘↓/Tab/⇧Tab/⌥⏎/⌘⏎/Esc go through ONE `.onKeyPress` handler mapped by the
  pure `FindKeymap`; plain ⏎ stays on `.onSubmit` (the path `GraphSearchField` proved). The selection
  clamps at the ends (no wrap — the Ask row is the top, the last row the bottom). **⌘C "copy link" is
  dropped:** a shortcut on a row would steal ⌘C from text selected in the field; each row's context
  menu offers its primary and secondary actions instead.
- **R-SU12 — A Settings row explains; it does not open.** ⏎ on it shows "Click Open to see this in
  Settings." and its trailing `SettingsSectionLink(section:label: "Open")` opens it on a click — A5/K3
  unchanged (S0 is Track O's spike). The rows are `SettingsSection.allCases`, so Settings v3's new
  sections appear without an edit; per-setting rows are Track O's `SettingsIndex` (hand-off).
- **R-SU13 — Actions:** Consolidate now / Stop consolidating (the Sleep page's own `sleepVM`
  methods), Go to each tab (⌘1–n), Switch to light/dark, Zoom in/out/Actual size, Switch to each
  other bank. **Not** "Add a source" or "Import an export…": decision 13 (Track I) retires the
  upload overlay and rebuilds intake; a palette action pointing at it would be rewritten next week.
  *Critic:* "the same call the page makes" is taken literally — Consolidate is offered only while
  something is queued (the Sleep page's own gate, `SleepPageModel.consolidateEnabled`, R-A7) and
  refreshes `[.status, .channels]` after `triggerManually()` exactly as `SleepControlRow` does; a bank
  switch goes through `banksVM.activate(_:)` then `graphVM.loadGraph()`, `BankSwitcher.switchTo`'s
  pair, not a bare `ActivateBank` mutation.
- **R-SU14 — Server timing and kinds.** Debounce **150 ms** (the brief's 150–200 ms overrides
  §1.1's 120 ms); Pass A `mode=prefix&kinds=entity,claim,episode,media&per_kind=5`; Pass B
  `mode=hybrid` at 450 ms idle, appended silently; "Search deeper" runs Pass B at once. `inbox` is not
  asked for — the local tier already holds every visible inbox item. "Show all" on a server-fed group
  re-asks that one kind with `per_kind=20`.
- **R-SU15 — Counts are honest or absent** (`FindCount`). A group fed by one tier shows its exact
  count ("Show all N", header "5 of N"); a group fed by both is `.atLeast` ("More…") — the local
  tier counts what it matched, the server counts lexical documents, and their union is unknown.
  Conversations are exact only when no two episodes merged into one row (`totals.episode` counts
  episodes); a hybrid response with semantic-only rows is `.atLeast` (semantic neighbours are ranked,
  never counted, G136 R11); a kind with no `totals` entry is exact only when fewer than `per_kind`
  came back.
- **R-SU16 — No telemetry is added.** Opening an entity from the palette opens its card, which already
  posts the ids-only `read` (`EntityDetailCard.swift:368`, surface `app`); a `palette` surface would
  need a server `Literal` change and would count that open twice.
- **R-SU17 — Glass.** The palette container is chrome: `.liquidGlass(.control)` (= `Glass.regular`),
  radius `CicadaTheme.radiusLarge` (18), with the **results area on an opaque `surface`** (no glass on
  glass). The graph field's `.overCanvas` style stays the `glassCard` material the graph's other
  controls use: `LiquidGlass.swift`'s own rule (no glass over the canvas without the G109 frame-time
  check) outranks design §1.3.
- **R-SU18 — The Reader seam.** At the start of Task 4, `git merge --no-edit dev`; if
  `ProvenanceRouter` exists, conversation rows and a belief's ⌥⏎ open the Reader through it. If not,
  `FindReaderSeam.isAvailable` stays `false`: a conversation row opens **Sources → that source's
  conversations, filtered to the conversation's title** (Track Z's `routeToSourceDetail` — merged in
  PR #76, so reused), a belief reveals its subject on the graph, and no "where it was said" secondary
  is offered (never an action that does nothing). *Critic:* `SourcesPageView` gives the detail view
  `.id(source.id)` (Task 3) — without it, routing from one source's open detail to another keeps
  `HarnessConversationsView`'s `@State` view model and shows the first source's conversations under
  the second one's header.
- **R-SU19 — Beliefs.** Current claims rank before superseded ones (server R10); a superseded one is
  drawn as history: "Was <claim> · until 3 Sep", tertiary ink, and read as "Earlier belief". Scrolling
  the entity card to the claim on Perspectives is Track P's (the card).
- **R-SU20 — A page that has its own order keeps it.** The Feed (its sort), Inbox (priority), a
  source's conversations (newest first) filter through `QuickMatch` and highlight, but do not re-rank;
  the Graph typeahead and the Clusters search list rank, as they did before.
- **R-SU21 — Paper fields live in one list, `FeedSearch.fields(_:)`**, which the Feed and the palette
  both read. Authors / arXiv id / DOI join it only if Track F's `MediaFeedItem.paper` is on `dev` at
  Task 5's start; this track never adds that field itself (Track F owns the wire model), and if Track
  F's `FeedViewModel.matches(_:query:)` exists it becomes a one-line wrapper. *Critic:* the Feed page
  folds that list **once per `store.sources` snapshot**, not per read — `filteredItems` is read two or
  three times a render, and re-folding every description and URL of 1,500 saved items measured
  ~100 ms a pass in a debug build (the old filter read three short fields). `QuickMatch`'s own rule:
  fields are folded when an index is built, never per keystroke.
- **R-SU22 — A source's conversations past the cap.** The loaded page (≤ 200) filters locally at once;
  only when it **hit** the cap does a debounced `GET /conversations/recent?q=` widen it; the union
  keeps local rows first and dedupes by id.
- **R-SU23 — `GraphNode.aliases` ships only if the measurement says so.** Measured on a synthetic
  2,000-node, links-free bank with two aliases on every node (a pessimistic ratio: every node has
  aliases and no edges dilute the payload); the 8-alias cap is printed for the record. ≤ 10 % → ship,
  capped at 8, and fold a node-shape tag into `/graph`'s ETag `extra` so every existing client gets
  exactly one 200 instead of 304-ing into an alias-less cache forever (no component and no
  `VersionVector` mapping changes). > 10 % → revert the field and record the number; aliases then
  arrive with the server tier only. *Planning-time probe of exactly Task 7's code:* 1,154,091 →
  1,220,614 bytes (**+5.8 %**) with two aliases per node, and **+16.9 %** at the 8-alias cap — the
  cap stays 8 to match `search_service` (real pages carry far fewer); the gate re-runs at
  implementation and its numbers are the ones recorded.
- **R-SU24 — The local budget.** p95 ≤ **8 ms** per keystroke over 3,000 entities + 1,500 media + 200
  inbox items in a **release** build (design §3.10); the plain `swift test` (debug) run asserts
  ≤ **300 ms**, a gate against an algorithmic regression (an accidental O(n²) over 4,700 documents
  costs seconds), not the budget — measured while planning, debug p95 was ~84 ms and a release build
  of the same matcher ~3 ms, so 300 ms leaves room for a machine busy building other worktrees. The
  orchestrator runs the release number.
- **R-SU25 — Vocabulary.** The design's group names, including "Entities" — the app's own word
  (`Copy.clustersSubtitle`: "Every entity, grouped by type").
- **R-SU26 — Focus is not restored to the prior element on close** (§3.8): SwiftUI exposes no prior
  first responder. Disclosed, not faked.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `…/Search/QuickMatch.swift` (new) | 1 | fold with back-map, tokens, tiers, weights, `match`, `rank`, `matches` |
| `…/ViewModels/GraphViewModel.swift` | 1, 5, 7 | `rankNames` wraps `QuickMatch`; `searchHits` (name, tags, aliases); `clusterSearchIndex()` |
| `…/Search/FindModels.swift` (new) | 2 | `FindMode`, `FindKind`, `FindRowKey`, `FindGroupID`, `FindMark`, `ReaderSpan`, `ConversationTarget`, `PaletteAction`, `FindDestination`, `FindRow`, `FindCount`, `FindSection`, `FindResults`, `FindReaderSeam` |
| `…/Search/FindMerge.swift` (new) | 2 | `FindMerge.fresh/append`, `FindStep`, `FindSelection`, `FindRecents`, `FindRowText` |
| `…/Search/QuickIndex.swift` (new) | 2, 7 | `QuickIndexInputs`, `QuickIndex.build/query/emptyState`, per-kind docs |
| `…/Search/PaletteActions.swift` (new) | 2 | the actions table and the empty-state suggestions |
| `…/Search/FeedSearch.swift`, `…/Search/InboxSearch.swift` (new) | 2, 5 | the one field list per saved item / inbox item |
| `…/Search/SearchTiming.swift` (new) | 2 | debounce, idle, per-kind, budget constants |
| `…/Search/ConversationSource.swift` (new) | 3 | which Sources card a conversation belongs to |
| `…/Search/FindPaletteModel.swift` (new) | 3, 4 | the palette's state, keys, recents, Ask hand-off, server passes |
| `…/Search/FindKeymap.swift` (new) | 3 | key + modifiers → action |
| `…/Support/FindCommands.swift` (new) | 3 | `FindCommands`, `PageFindAction`, `pageFind`, `publishesPageFind`, `PaletteRequest`, `PaletteToggle` |
| `…/Views/Find/FindPalette.swift`, `FindPanelBody.swift`, `FindRowView.swift` (new) | 3, 4 | the overlay, the hostable body, the row |
| `…/Support/AppRouter.swift` | 3 | palette / inbox / clusters / conversation-query hand-offs (+ Track Z's source detail if absent) |
| `…/ContentView.swift` | 3, 5 | overlay, request consumer, index rebuild, `openFind`, preview sheet, `SearchButton`; graph field |
| `…/CicadaApp.swift` | 3 | `FindPaletteModel` in the main window's environment; `FindCommands` |
| `…/Ask/AskPanel.swift` | 3 | `hostedViewModel` (above the answer body only) |
| `…/Views/Inbox/InboxListView.swift`, `InboxCardView.swift` | 3, 6 | land on an item expanded; the search field; the two missing kind chips |
| `…/Views/Topics/TopicsView.swift` | 3, 5 | open an entity handed over; `CicadaSearchField`, precomputed index, highlight |
| `…/Views/Sources/SourcesPageView.swift`, `HarnessConversationsView.swift` | 3, 6 | source-detail hand-off; conversation query; field; past-the-cap search |
| `…/Views/Feed/FeedView.swift`, `…/ViewModels/FeedViewModel.swift` | 3, 5 | preview sheet internal; field; honest no-match state; `FeedSearch` |
| `…/Sync/Snapshot.swift`, `…/Sync/Store.swift` | 3 | `.quickRecents` |
| `…/Theme/CicadaMotion.swift` | 3 | `paletteIn`, `paletteOut`, `groupExpand` |
| `…/Search/MemorySearch.swift`, `…/Search/FindServerRows.swift` (new) | 4 | the wire, the protocol, hits → rows, totals, dates, speakers |
| `…/Services/APIClient.swift` | 4, 6 | `searchMemory`; `fetchRecentConversations(query:)` |
| `…/Views/Common/CicadaSearchField.swift`, `SearchAllMemoryRow.swift` (new) | 5 | the one in-page field; "Search all of memory for …" |
| `…/Search/ClusterSearchIndex.swift` (new) | 5 | Clusters' folded index |
| `…/Models/SourceOverview.swift`, `…/ViewModels/ConversationsViewModel.swift`, `…/Sync/SyncAPI.swift` | 6 | `ConversationFilter` on `QuickMatch`; `ConversationSearch`; `query:` |
| `…/Models/Entity.swift` | 7 | `GraphNode.aliases` |
| `api/models/schemas.py`, `api/services/graph_builder.py`, `api/routers/graph.py` | 7 | `aliases` on nodes, capped; the ETag node-shape tag |
| Tests (Swift) | all | `QuickMatchTests`, `QuickIndexTests`, `PaletteMergeTests`, `QuickIndexLatencyTests`, `FindFixtures`, `FindPaletteTests`, `FindRoutingTests`, `HiddenShortcutLintTests`, `FindServerTests`, `SearchFieldsTests`, `PageSearchTests`; edits to `MutationTests`, `CicadaMotionTests`, `StoreTests` (`FakeSyncAPI`), `ConversationsTests` |
| Tests (Python) | 7 | `api/tests/test_graph_aliases.py` |
| Docs | 7 | `docs/goals/memory-evolution.md` (G136, G93, G123), `docs/goals/TODO.md`, `CLAUDE.md` |

`…` = `app/CicadaApp/Sources/CicadaApp`. Tests live in `app/CicadaApp/Tests/CicadaAppTests/`.

---
### Task 1: `QuickMatch` — the one ranker (S3, R-SU1…R-SU4)

Pure, no view change. The graph typeahead is the first caller, so the branch ships a real consumer
and `GraphSearchRankTests` proves nothing about G123 moved.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Search/QuickMatch.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift:448-467` (`rankNames` body only)
- Test: `app/CicadaApp/Tests/CicadaAppTests/QuickMatchTests.swift` (new); `GraphSearchRankTests.swift` must pass **unchanged**

**Interfaces:**
- Produces `QuickMatch.Weight` (`name` 1.0, `alias` 0.9, `keyword` 0.7, `body` 0.4), `QuickMatch.Tier`,
  `QuickMatch.Folded`, `QuickMatch.Field(_:weight:)`, `QuickMatch.Token`, `QuickMatch.Match`
  (`score`, `ranges(inField:)`), `QuickMatch.fold(_:)`, `tokens(_:)`, `hit(_:in:)`, `match(_:fields:)`,
  `rank(_:query:limit:fields:tieBreak:name:)`, `matches(_:fields:)`, `maxTokens`.
- Consumed by every later task.

- [ ] **Step 1: Failing tests** — `QuickMatchTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 plan R-SU1…R-SU4 — the one ranker. The palette's instant tier, the
/// graph typeahead (G123) and every in-page field rank and bold through
/// `QuickMatch`, so these pin the rules they share with each other and with
/// the server's `text_fold` (G136 R21).
final class QuickMatchTests: XCTestCase {
    private func tier(_ query: String, _ text: String) -> QuickMatch.Tier? {
        guard let token = QuickMatch.tokens(query).first else { return nil }
        return QuickMatch.hit(token, in: QuickMatch.fold(text))?.tier
    }

    private func score(_ query: String, _ text: String) -> Double? {
        QuickMatch.match(QuickMatch.tokens(query), fields: [QuickMatch.Field(text, weight: QuickMatch.Weight.name)])?.score
    }

    func testTiersRankWholeFieldThenPrefixThenWordStartThenInitialsThenSubstring() {
        XCTAssertEqual(tier("gamma", "Gamma"), .exact)
        XCTAssertEqual(tier("gam", "Gamma"), .prefix)
        XCTAssertEqual(tier("alp", "Beta alpha"), .wordStart)
        XCTAssertEqual(tier("cc", "Claude Code"), .initials)
        XCTAssertEqual(tier("alp", "Catalpha"), .substring)
        XCTAssertNil(tier("zeta", "Catalpha"))
        XCTAssertEqual([score("gamma", "Gamma"), score("gam", "Gamma"), score("alp", "Beta alpha"),
                        score("cc", "Claude Code"), score("alp", "Catalpha")], [5, 4, 3, 2, 1])
    }

    /// R-SU2: one letter lists what BEGINS with it, not everything that contains it.
    func testASingleCharacterMatchesOnlyAtAFieldOrWordStart() {
        XCTAssertEqual(tier("a", "Alpha"), .prefix)
        XCTAssertEqual(tier("a", "Beta alpha"), .wordStart)
        XCTAssertNil(tier("a", "Beta"), "no substring tier for one character")
        XCTAssertNil(tier("c", "Xc"), "no substring tier for one character")
    }

    func testEveryTokenMustMatchSomewhere() {
        let fields = [QuickMatch.Field("Alpha Project", weight: QuickMatch.Weight.name),
                      QuickMatch.Field("robotics", weight: QuickMatch.Weight.keyword)]
        XCTAssertNotNil(QuickMatch.match(QuickMatch.tokens("alpha robo"), fields: fields))
        XCTAssertNil(QuickMatch.match(QuickMatch.tokens("alpha zeta"), fields: fields), "AND, not OR")
        XCTAssertNil(QuickMatch.match([], fields: fields), "an empty query ranks nothing")
    }

    /// R-SU1: the server's fold, so the two tiers never disagree about one word.
    func testDiacriticsFoldButSharpSStaysAsTheServerIndexesIt() {
        XCTAssertEqual(tier("zurich", "Zürich"), .exact)
        XCTAssertEqual(tier("zürich", "Zurich"), .exact, "both sides fold")
        XCTAssertEqual(tier("zur", "Zu\u{0308}rich"), .prefix, "a decomposed input folds the same way")
        XCTAssertEqual(tier("straße", "Hauptstraße"), .substring)
        XCTAssertNil(tier("strasse", "Hauptstraße"), "G136 R21: no full case fold")
        XCTAssertEqual(tier("istanbul", "İstanbul"), .exact)
    }

    func testRangesAreOriginalScalarsSoADecomposedLetterIsBoldedWhole() {
        let decomposed = QuickMatch.match(QuickMatch.tokens("zur off"),
                                          fields: [QuickMatch.Field("Zu\u{0308}rich office", weight: 1)])
        XCTAssertEqual(decomposed?.ranges(inField: 0), [[0, 4], [8, 11]])
        let initials = QuickMatch.match(QuickMatch.tokens("cc"), fields: [QuickMatch.Field("Claude Code", weight: 1)])
        XCTAssertEqual(initials?.ranges(inField: 0), [[0, 1], [7, 8]])
        let overlap = QuickMatch.match(QuickMatch.tokens("alpha alp"), fields: [QuickMatch.Field("Alpha", weight: 1)])
        XCTAssertEqual(overlap?.ranges(inField: 0), [[0, 5]], "overlapping runs merge")
    }

    /// G136 R7 keeps the same surprise server-side, so the tiers agree.
    func testAnExactAliasOutranksANamePrefixBecauseWeightsMultiplyTiers() {
        let prefixOnName = QuickMatch.match(QuickMatch.tokens("delta"),
                                            fields: [QuickMatch.Field("Delta Ops", weight: QuickMatch.Weight.name)])?.score
        let exactAlias = QuickMatch.match(QuickMatch.tokens("delta"),
                                          fields: [QuickMatch.Field("Omega", weight: QuickMatch.Weight.name),
                                                   QuickMatch.Field("delta", weight: QuickMatch.Weight.alias)])?.score
        XCTAssertEqual(prefixOnName, 4.0)
        XCTAssertEqual(exactAlias ?? 0, 4.5, accuracy: 0.0001)
    }

    func testTokensAreWhitespaceSplitFoldedDedupedAndCappedAtEight() {
        XCTAssertEqual(QuickMatch.tokens("  Alpha  alpha ÄLPHA ").count, 1)
        XCTAssertEqual(QuickMatch.tokens((1...12).map { "w\($0)" }.joined(separator: " ")).count, QuickMatch.maxTokens)
        XCTAssertTrue(QuickMatch.tokens("   ").isEmpty)
    }

    func testWhitespaceRunsCollapseAndWordStartsSplitLikeUnicode61() {
        XCTAssertEqual(tier("alpha", "  alpha  "), .exact)
        XCTAssertEqual(QuickMatch.fold("a   b").scalars.count, 3)
        XCTAssertEqual(tier("vec", "sqlite-vec"), .wordStart)
        XCTAssertEqual(tier("vec", "sqlite_vec"), .wordStart, "unicode61 treats _ as a separator")
    }

    func testRankOrdersByScoreThenTieBreakThenName() {
        let items: [(String, String, Int)] = [("a", "Alpha Project", 3), ("b", "Alphabet", 7),
                                              ("c", "Beta alpha", 9), ("d", "Alphabet Inc", 7)]
        let ranked = QuickMatch.rank(items, query: "alpha",
                                     fields: { [QuickMatch.Field($0.1, weight: 1)] },
                                     tieBreak: { Double($0.2) }, name: { $0.1.lowercased() }).map { $0.item.0 }
        XCTAssertEqual(ranked, ["b", "d", "a", "c"])
    }

    func testMatchesKeepsEverythingForAnEmptyQuery() {
        XCTAssertTrue(QuickMatch.matches("", fields: []))
        XCTAssertTrue(QuickMatch.matches("gra", fields: [QuickMatch.Field("Graph physics", weight: 1)]))
        XCTAssertFalse(QuickMatch.matches("zeta", fields: [QuickMatch.Field("Graph physics", weight: 1)]))
    }
}
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter QuickMatchTests 2>&1 | tail -20` → compile
failure (`QuickMatch` does not exist). That is the red.

- [ ] **Step 2: Implement** — `Search/QuickMatch.swift`:

```swift
import Foundation

/// The one ranker (G136; round-3 design §1.2). The ⌘K palette's instant tier,
/// the graph typeahead (G123), Clusters, the Feed, a source's conversations and
/// the Inbox all rank and bold through this file, so no two surfaces can
/// disagree about one name.
///
/// **Folding is the server's rule, not Foundation's** (plan R-SU1). The design
/// sketched `folding(options: [.caseInsensitive, .diacriticInsensitive])`; the
/// server's twin (`api/services/text_fold.py`, G136 R21) was amended at its
/// final review to NFD + combining marks dropped + lowercase, because a full
/// case fold rewrites "ß" as "ss" while FTS5's `unicode61` indexes it as
/// written — the exact stored spelling then hit one tier and missed the other.
/// Marks are dropped BEFORE lowercasing, as Python's `fold` does, so "İ" folds
/// to "i" on both sides.
///
/// **Tiers** (per token, per field, the best wins): whole field 0, field
/// prefix 1, word-start prefix 2, initials 3 ("cc" → "Claude Code"),
/// substring 4. The server ranks tiers 0–2 with the same weights (G136 R7);
/// 3 and 4 have no index behind them there, which is why this tier exists.
/// A one-character token matches only at a field or word start (R-SU2).
/// **Score** = Σ over tokens of `(5 − tier) × weight`, every token required
/// (AND). **Ranges** are ORIGINAL Unicode scalars — the unit
/// `ExcerptText.attributed(_:bold:)` and the server's `snippetOffsets` use —
/// so a bold run lands on the same characters whichever tier found the row.
///
/// Fields are folded once, when an index is built, never per keystroke
/// (`QuickIndex`, `ClusterSearchIndex`).
enum QuickMatch {
    /// Design §1.2's weights; the server's `search_service` uses the same four.
    enum Weight {
        static let name = 1.0
        static let alias = 0.9
        static let keyword = 0.7
        static let body = 0.4
    }

    enum Tier: Int, Comparable, Sendable {
        case exact = 0, prefix, wordStart, initials, substring
        static func < (lhs: Tier, rhs: Tier) -> Bool { lhs.rawValue < rhs.rawValue }
        var points: Double { Double(5 - rawValue) }
    }

    /// `text_fold.MAX_TOKENS` — past eight words a query is a paragraph.
    static let maxTokens = 8

    /// One field, folded once.
    struct Folded: Sendable, Equatable {
        /// NFD, combining marks dropped, lowercased; whitespace runs collapsed
        /// to one space and both ends trimmed.
        var scalars: [UInt32] = []
        /// `back[i]` is the index, in the ORIGINAL scalars, `scalars[i]` came from.
        var back: [Int] = []
        /// Folded offsets where a word starts (R-SU3: letters and numbers are
        /// word characters, everything else separates — `unicode61`'s split).
        var wordStarts: [Int] = []
        /// Presence mask of `scalars`: a token whose mask is not a subset
        /// cannot match at any tier, which rejects most documents in one AND.
        var mask: UInt64 = 0
    }

    struct Field: Sendable {
        let folded: Folded
        let weight: Double
        init(_ text: String, weight: Double) {
            self.folded = QuickMatch.fold(text)
            self.weight = weight
        }
    }

    struct Token: Sendable, Equatable {
        let scalars: [UInt32]
        let mask: UInt64
    }

    struct Hit: Equatable {
        let tier: Tier
        /// Folded `[start, end)` runs the token covered.
        let runs: [Range<Int>]
    }

    struct Match: Sendable, Equatable {
        let score: Double
        /// Field index → merged `[start, end)` ranges in ORIGINAL scalars.
        let ranges: [Int: [[Int]]]
        func ranges(inField index: Int) -> [[Int]] { ranges[index] ?? [] }
    }

    // MARK: Folding

    static func fold(_ text: String) -> Folded {
        var out = Folded()
        let count = text.unicodeScalars.count
        out.scalars.reserveCapacity(count)
        out.back.reserveCapacity(count)
        var pendingSpace: Int? = nil
        var previousIsWord = false
        func emit(_ value: UInt32, from index: Int) {
            let isWord = isWordScalar(value)
            if isWord && !previousIsWord { out.wordStarts.append(out.scalars.count) }
            previousIsWord = isWord
            out.scalars.append(value)
            out.back.append(index)
            out.mask |= bit(value)
        }
        for (index, scalar) in text.unicodeScalars.enumerated() {
            if scalar.properties.isWhitespace {
                if !out.scalars.isEmpty, pendingSpace == nil { pendingSpace = index }
                continue
            }
            if let space = pendingSpace {
                emit(0x20, from: space)
                pendingSpace = nil
            }
            if scalar.isASCII {
                let value = scalar.value
                emit((65...90).contains(value) ? value + 32 : value, from: index)
                continue
            }
            for piece in String(scalar).decomposedStringWithCanonicalMapping.unicodeScalars
            where piece.properties.canonicalCombiningClass == .notReordered {
                for lower in piece.properties.lowercaseMapping.unicodeScalars {
                    emit(lower.value, from: index)
                }
            }
        }
        return out
    }

    static func isWordScalar(_ value: UInt32) -> Bool {
        if value < 128 {
            return (48...57).contains(value) || (97...122).contains(value) || (65...90).contains(value)
        }
        guard let scalar = Unicode.Scalar(value) else { return false }
        return scalar.properties.isAlphabetic || scalar.properties.numericType != nil
    }

    static func bit(_ value: UInt32) -> UInt64 { 1 << UInt64(value % 64) }

    // MARK: Matching

    static func tokens(_ query: String) -> [Token] {
        var seen = Set<[UInt32]>()
        var out: [Token] = []
        for part in query.split(whereSeparator: { $0.isWhitespace }) {
            let folded = fold(String(part))
            guard !folded.scalars.isEmpty, seen.insert(folded.scalars).inserted else { continue }
            out.append(Token(scalars: folded.scalars, mask: folded.mask))
            if out.count == maxTokens { break }
        }
        return out
    }

    static func hit(_ token: Token, in field: Folded) -> Hit? {
        let t = token.scalars, s = field.scalars
        guard !t.isEmpty, t.count <= s.count, token.mask & ~field.mask == 0 else { return nil }
        if t == s { return Hit(tier: .exact, runs: [0..<t.count]) }
        if s.starts(with: t) { return Hit(tier: .prefix, runs: [0..<t.count]) }
        for start in field.wordStarts where start > 0 && start + t.count <= s.count {
            if s[start..<(start + t.count)].elementsEqual(t) {
                return Hit(tier: .wordStart, runs: [start..<(start + t.count)])
            }
        }
        guard t.count >= 2 else { return nil }   // R-SU2
        if field.wordStarts.count >= t.count, zip(field.wordStarts, t).allSatisfy({ s[$0.0] == $0.1 }) {
            return Hit(tier: .initials, runs: field.wordStarts.prefix(t.count).map { $0..<($0 + 1) })
        }
        let first = t[0]
        var index = 0
        while index <= s.count - t.count {
            if s[index] == first, s[index..<(index + t.count)].elementsEqual(t) {
                return Hit(tier: .substring, runs: [index..<(index + t.count)])
            }
            index += 1
        }
        return nil
    }

    static func match(_ tokens: [Token], fields: [Field]) -> Match? {
        guard !tokens.isEmpty else { return nil }
        var score = 0.0
        var runs: [Int: [Range<Int>]] = [:]
        for token in tokens {
            var best: (points: Double, field: Int, hit: Hit)?
            for (index, field) in fields.enumerated() {
                guard let hit = hit(token, in: field.folded) else { continue }
                let points = hit.tier.points * field.weight
                if best == nil || points > best!.points { best = (points, index, hit) }
            }
            guard let best else { return nil }
            score += best.points
            runs[best.field, default: []] += best.hit.runs
        }
        var ranges: [Int: [[Int]]] = [:]
        for (index, folded) in runs { ranges[index] = originalRanges(folded, in: fields[index].folded) }
        return Match(score: score, ranges: ranges)
    }

    /// Folded runs → merged ranges in the ORIGINAL scalars: `[a, b)` covers
    /// `[back[a], back[b-1] + 1)`, so "u" + U+0308 folded to one "u" is bolded whole.
    static func originalRanges(_ runs: [Range<Int>], in folded: Folded) -> [[Int]] {
        let mapped = runs.compactMap { run -> (Int, Int)? in
            guard !run.isEmpty, run.upperBound <= folded.back.count else { return nil }
            return (folded.back[run.lowerBound], folded.back[run.upperBound - 1] + 1)
        }.sorted { $0.0 < $1.0 }
        var merged: [[Int]] = []
        for (start, end) in mapped {
            if let last = merged.last, start <= last[1] {
                merged[merged.count - 1][1] = max(last[1], end)
            } else {
                merged.append([start, end])
            }
        }
        return merged
    }

    // MARK: Conveniences

    /// Best first: score, then `tieBreak` (higher first), then `name`
    /// ascending — G123's typeahead order, which `GraphViewModel.rankNames`
    /// now delegates to (R-SU4). Items that miss any token are dropped.
    static func rank<Item>(_ items: [Item], query: String, limit: Int? = nil,
                           fields: (Item) -> [Field], tieBreak: (Item) -> Double,
                           name: (Item) -> String) -> [(item: Item, match: Match)] {
        let tokens = tokens(query)
        guard !tokens.isEmpty else { return [] }
        var scored: [(item: Item, match: Match, tie: Double, name: String)] = []
        for item in items {
            guard let found = match(tokens, fields: fields(item)) else { continue }
            scored.append((item, found, tieBreak(item), name(item)))
        }
        scored.sort { a, b in
            if a.match.score != b.match.score { return a.match.score > b.match.score }
            if a.tie != b.tie { return a.tie > b.tie }
            return a.name < b.name
        }
        let cut = limit.map { Array(scored.prefix($0)) } ?? scored
        return cut.map { (item: $0.item, match: $0.match) }
    }

    /// For a list that keeps its own order (R-SU20): does every token match
    /// somewhere? An empty query keeps everything.
    static func matches(_ query: String, fields: [Field]) -> Bool {
        let tokens = tokens(query)
        return tokens.isEmpty || match(tokens, fields: fields) != nil
    }
}
```

`GraphViewModel.swift:448-467` — replace the body of `rankNames` (signature and doc comment above
`searchMatches` unchanged):

```swift
    /// G123's ranking, now `QuickMatch`'s (G136 R-SU4): the palette and this
    /// typeahead can never order one name differently. `GraphSearchRankTests`
    /// pins the behaviour it had before.
    nonisolated static func rankNames(_ items: [(id: String, name: String, degree: Int)], query: String, limit: Int = 8) -> [String] {
        QuickMatch.rank(items, query: query, limit: limit,
                        fields: { [QuickMatch.Field($0.name, weight: QuickMatch.Weight.name)] },
                        tieBreak: { Double($0.degree) },
                        name: { $0.name.lowercased() }).map { $0.item.id }
    }
```

- [ ] **Step 3: Green.** `swift test --filter QuickMatchTests` and `swift test --filter GraphSearchRankTests`
  → all pass; then `swift build 2>&1 | tail -5` and the full `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 4: Commit** — stage `Search/QuickMatch.swift`, `ViewModels/GraphViewModel.swift`,
  `Tests/CicadaAppTests/QuickMatchTests.swift`:
  `feat(search): QuickMatch, one ranker for every local search; the graph typeahead delegates to it (G136 S3, R-SU1…R-SU4)`.

---

### Task 2: The palette's instant tier — `QuickIndex`, the models, the merge rule (S3, R-SU5, R-SU6, R-SU13, R-SU15, R-SU24)

Everything the palette decides is a pure value with a table test; no view yet, so the branch stays
shippable.

**Files:**
- Create: `…/Search/FindModels.swift`, `…/Search/FindMerge.swift`, `…/Search/QuickIndex.swift`,
  `…/Search/PaletteActions.swift`, `…/Search/FeedSearch.swift`, `…/Search/InboxSearch.swift`,
  `…/Search/SearchTiming.swift`
- Test: `FindFixtures.swift`, `QuickIndexTests.swift`, `PaletteMergeTests.swift`,
  `QuickIndexLatencyTests.swift` (all new)

**Interfaces:**
- Produces the vocabulary (`FindMode`, `FindKind`, `FindRowKey`, `FindGroupID`, `FindMark`,
  `ReaderSpan`, `ConversationTarget`, `PaletteAction`, `FindDestination`, `FindRow`, `FindCount`,
  `FindSection`, `FindResults`, `FindReaderSeam`), `FindMerge.fresh/append`, `FindStep`,
  `FindSelection.initial/move/flat`, `FindRecents.push`, `FindRowText`, `QuickIndexInputs`
  (`from(_:askHistory:)`, `token(_:askHistoryCount:)`), `QuickIndex` (`build`, `query`, `emptyState`,
  `Result`), `PaletteActions.docs/suggested`, `FeedSearch.fields/matches/filter`,
  `InboxSearch.fields/filter`, `SearchTiming`.
- Consumes `QuickMatch`, `GraphNode`, `MediaFeedItem`, `SourceOverview` + `SourceDisplayName.of`,
  `InboxItem`, `MemoryBank`, `AskHistoryEntry`, `SettingsSection`, `AppTab`, `Copy.settings`,
  `UsageFormat.count`, `AppColorScheme`.

- [ ] **Step 1: Failing tests.** `FindFixtures.swift` (a test helper, placeholders only):

```swift
import Foundation
@testable import CicadaApp

/// Synthetic rows for the G136 palette tests — placeholders only
/// (alpha-project, bob-example, beta-bank, example.com), never a bank.
enum FindFixtures {
    static func node(_ id: String, _ name: String, type: EntityType = .project, tags: [String] = [],
                     summary: String? = nil, degree: Int = 0, isHub: Bool = false,
                     isFacet: Bool = false) -> GraphNode {
        GraphNode(id: id, name: name, type: type, tags: tags, degree: degree, isHub: isHub,
                  isFacet: isFacet, summary: summary)
    }

    static func media(_ entity: String, title: String, url: String = "https://example.com/a",
                      site: String? = nil, description: String? = nil, origin: String? = nil,
                      savedAt: String = "2026-09-01") -> MediaFeedItem {
        var object: [String: Any] = ["mediaEntityId": entity, "url": url, "title": title,
                                     "mediaType": "bookmark", "savedAt": savedAt,
                                     "tags": [String](), "relevance": 0.5]
        if let site { object["site"] = site }
        if let description { object["description"] = description }
        if let origin { object["origin"] = origin }
        return try! JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: object))
    }

    static func inbox(_ id: String, question: String, entityName: String = "", excerpt: String = "",
                      kind: String = "clarification", priority: Double = 0.5) -> InboxItem {
        let object: [String: Any] = ["id": id, "kind": kind, "requiredInput": "choice", "title": question,
                                     "question": question, "entityName": entityName, "priority": priority,
                                     "cause": ["excerpt": excerpt]]
        return try! JSONDecoder().decode(InboxItem.self, from: JSONSerialization.data(withJSONObject: object))
    }

    static func bank(_ name: String) -> MemoryBank {
        try! JSONDecoder().decode(MemoryBank.self, from: Data(#"{"name": "\#(name)"}"#.utf8))
    }

    static func inputs() -> QuickIndexInputs {
        var inputs = QuickIndexInputs()
        inputs.nodes = [
            node("alpha-project", "alpha-project", tags: ["robotics"], summary: "A research project about retrieval.", degree: 5),
            node("bob-example", "bob-example", type: .person, degree: 2),
            node("hub:project", "Alpha Hub", type: .hub, isHub: true),
            node("alpha-project#work", "alpha-project", isFacet: true),
            node("media-alpha", "Alpha paper notes", type: .media),
        ]
        inputs.media = [
            media("media-alpha", title: "Alpha paper notes", site: "example.com"),
            media("media-alpha", title: "Alpha paper notes", url: "https://example.com/b"),
        ]
        inputs.sources = [SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness,
                                         mark: "claude-code", episodes: 12, harness: "claude-code")]
        inputs.inbox = [inbox("inbox-001", question: "Still tracking alpha-project?", entityName: "alpha-project",
                              excerpt: "we paused alpha-project in June")]
        inputs.banks = [bank("default"), bank("beta-bank")]
        inputs.activeBank = "default"
        inputs.unprocessed = 3
        return inputs
    }
}
```

`QuickIndexTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 S3 / plan R-SU5, R-SU13 — the instant tier indexes what the app
/// already holds, and nothing twice.
final class QuickIndexTests: XCTestCase {
    private let index = QuickIndex.build(FindFixtures.inputs())

    private func ids(_ result: QuickIndex.Result, _ group: FindGroupID) -> [String] {
        result.rows.filter { $0.group == group }.map(\.key.id)
    }

    func testEntitiesSkipFacetsHubsAndMediaNodesAndASavedItemIsListedOnce() {
        let result = index.query("alpha")
        XCTAssertEqual(ids(result, .entities), ["alpha-project"])
        XCTAssertEqual(result.rows.filter { $0.key.kind == .media }.map(\.key.id), ["media-alpha"])
        XCTAssertEqual(result.counts[.entities], 1)
        let row = result.rows.first { $0.key.id == "alpha-project" }
        XCTAssertEqual(row?.titleRanges, [[0, 5]], "the title's own bold run")
        XCTAssertEqual(row?.destination, .entity(id: "alpha-project"))
        XCTAssertEqual(row?.secondary, .entityInClusters(id: "alpha-project"))
    }

    func testTagsSummariesInboxCausesAndSourceCardsAreFound() {
        XCTAssertEqual(ids(index.query("robotics"), .entities), ["alpha-project"])
        XCTAssertEqual(ids(index.query("retrieval"), .entities), ["alpha-project"])
        XCTAssertEqual(ids(index.query("paused"), .inbox), ["inbox-001"])
        XCTAssertEqual(ids(index.query("claude"), .sources), ["harness:claude-code"])
        XCTAssertEqual(index.query("claude").rows.first { $0.key.kind == .source }?.mark, .origin("claude-code"))
    }

    func testSettingsActionsAndBanksReflectTheirState() {
        XCTAssertEqual(ids(index.query("integrations"), .settings), [SettingsSection.integrations.rawValue])
        XCTAssertEqual(index.query("consolidate").rows.first?.title, "Consolidate now")
        XCTAssertEqual(index.query("beta").rows.first { $0.key.kind == .bank }?.destination, .bank(name: "beta-bank"))
        XCTAssertTrue(index.query("switch to default").rows.filter { $0.key.kind == .bank }.isEmpty,
                      "the active bank is not offered")
        var sleeping = FindFixtures.inputs()
        sleeping.isSleeping = true
        sleeping.appearance = .light
        let busy = QuickIndex.build(sleeping)
        XCTAssertEqual(busy.query("stop").rows.first?.destination, .action(.stopConsolidating))
        XCTAssertEqual(busy.query("dark").rows.first?.destination, .action(.darkMode))
        var rested = FindFixtures.inputs()
        rested.unprocessed = 0
        XCTAssertTrue(QuickIndex.build(rested).query("consolidate").rows.filter { $0.key.kind == .action }.isEmpty,
                      "nothing queued, nothing to run — the Sleep page's own gate")
    }

    func testTheEmptyStateResolvesRecentsAndSuggestsOnlyWhatIsTrue() {
        let recents = [FindRowKey(kind: .entity, id: "bob-example"), FindRowKey(kind: .entity, id: "gone")]
        let empty = index.emptyState(recents: recents)
        XCTAssertEqual(empty.groups[.recent]?.map(\.key.id), ["bob-example"], "an id that no longer resolves is dropped")
        XCTAssertEqual(empty.groups[.suggested]?.map(\.title), ["Consolidate now", "Answer 1 question"])
        var quiet = FindFixtures.inputs()
        quiet.unprocessed = 0
        quiet.inbox = []
        XCTAssertNil(QuickIndex.build(quiet).emptyState(recents: []).groups[.suggested])
    }

    func testAskHistoryIsFoundAndTheNewestThreeAreOffered() {
        var inputs = FindFixtures.inputs()
        inputs.askHistory = (0..<5).map { AskHistoryEntry(question: "question \($0)", askedAt: Date(timeIntervalSince1970: Double(100 - $0)), answer: nil) }
        let built = QuickIndex.build(inputs)
        XCTAssertEqual(built.emptyState(recents: []).groups[.askedBefore]?.map(\.title), ["question 0", "question 1", "question 2"])
        XCTAssertEqual(built.query("question 4").rows.first { $0.group == .askedBefore }?.destination,
                       .askedBefore(question: "question 4"))
    }

    func testFeedSearchReadsDescriptionUrlAndOriginAndKeepsOrder() {
        let a = FindFixtures.media("m-a", title: "First", url: "https://example.com/alpha-notes", description: "about retrieval")
        let b = FindFixtures.media("m-b", title: "Second", origin: "chrome-bookmark")
        XCTAssertEqual(FeedSearch.filter([a, b], query: "retrieval").map(\.mediaEntityId), ["m-a"])
        XCTAssertEqual(FeedSearch.filter([a, b], query: "notes").map(\.mediaEntityId), ["m-a"], "a URL word")
        XCTAssertEqual(FeedSearch.filter([a, b], query: "chrome").map(\.mediaEntityId), ["m-b"])
        XCTAssertEqual(FeedSearch.filter([b, a], query: "").map(\.mediaEntityId), ["m-b", "m-a"], "R-SU20: order kept")
    }

    func testInboxSearchReadsQuestionEntityAndCause() {
        let items = [FindFixtures.inbox("i1", question: "Still tracking alpha-project?", entityName: "alpha-project"),
                     FindFixtures.inbox("i2", question: "Which role?", entityName: "bob-example", excerpt: "bob-example moved teams")]
        XCTAssertEqual(InboxSearch.filter(items, query: "teams").map(\.id), ["i2"])
        XCTAssertEqual(InboxSearch.filter(items, query: "alpha").map(\.id), ["i1"])
        XCTAssertEqual(InboxSearch.filter(items, query: "").map(\.id), ["i1", "i2"])
    }
}
```

`PaletteMergeTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 design §3.2 "the list never jumps" / plan R-SU15 — the merge rule,
/// the counts and the keyboard walk, as pure values.
final class PaletteMergeTests: XCTestCase {
    private func row(_ kind: FindKind, _ id: String, _ group: FindGroupID, score: Double = 1) -> FindRow {
        FindRow(key: FindRowKey(kind: kind, id: id), group: group, title: id, mark: .symbol("circle"),
                score: score, destination: .entity(id: id))
    }

    private func local(_ rows: [FindRow]) -> QuickIndex.Result {
        QuickIndex.Result(rows: rows, counts: Dictionary(grouping: rows, by: \.group).mapValues(\.count))
    }

    func testFreshPutsAskFirstAndLiftsTheTopHitOutOfItsGroup() {
        let results = FindMerge.fresh(query: "al", local: local([row(.entity, "a", .entities, score: 4),
                                                                 row(.entity, "b", .entities, score: 3),
                                                                 row(.media, "m", .sources, score: 4)]))
        XCTAssertEqual(results.ask?.destination, .ask("al"))
        XCTAssertEqual(results.topHit?.key.id, "a", "a tie goes to the earlier group")
        XCTAssertEqual(results.groups[.entities]?.map(\.key.id), ["b"])
        XCTAssertEqual(results.count(for: .entities), .exact(1))
        XCTAssertEqual(results.sections(expanded: []).map(\.group), [.ask, .topHit, .entities, .sources])
        XCTAssertNil(FindMerge.fresh(query: "  ", local: local([])).ask, "nothing typed, no Ask row")
    }

    func testServerRowsAppendDedupeAndNeverReorder() {
        var results = FindMerge.fresh(query: "al", local: local([row(.entity, "a", .entities, score: 4),
                                                                 row(.entity, "b", .entities, score: 3)]))
        results = FindMerge.append([row(.entity, "a", .entities, score: 9), row(.entity, "c", .entities, score: 9),
                                    row(.conversation, "s1", .conversations)],
                                   totals: [.entities: .exact(5), .conversations: .exact(1)], to: results)
        XCTAssertEqual(results.topHit?.key.id, "a", "the top hit is the local tier's and stays")
        XCTAssertEqual(results.groups[.entities]?.map(\.key.id), ["b", "c"], "a not repeated; c after what was shown")
        XCTAssertEqual(results.count(for: .entities), .atLeast, "two tiers fed it — the union is unknown")
        XCTAssertEqual(results.count(for: .conversations), .exact(1))
        let again = FindMerge.append([], totals: [.conversations: .exact(1)], to: results)
        XCTAssertEqual(again.count(for: .conversations), .exact(1), "a second pass replaces, never compounds")
    }

    func testAGroupShowsFiveThenShowAllWithAnHonestNumber() {
        let rows = (0..<7).map { row(.entity, "e\($0)", .entities, score: Double(10 - $0)) }
        let results = FindMerge.fresh(query: "e", local: local(rows))
        let section = results.sections(expanded: []).first { $0.group == .entities }
        XCTAssertEqual(section?.rows.count, 5)
        XCTAssertEqual(section?.more, .exact(6), "e0 is the top hit; six remain")
        XCTAssertEqual(section?.headerCount, "5 of 6")
        XCTAssertNil(results.sections(expanded: [.entities]).first { $0.group == .entities }?.more)
        var merged = results
        merged = FindMerge.append([], totals: [.entities: .exact(40)], to: merged)
        XCTAssertEqual(merged.sections(expanded: []).first { $0.group == .entities }?.more, .atLeast)
        XCTAssertNil(merged.sections(expanded: []).first { $0.group == .entities }?.headerCount,
                     "never a guessed number")
    }

    func testCountsCombine() {
        XCTAssertEqual(FindCount.combine(local: nil, server: .exact(9)), .exact(9))
        XCTAssertEqual(FindCount.combine(local: .exact(0), server: .exact(9)), .exact(9))
        XCTAssertEqual(FindCount.combine(local: .exact(3), server: .exact(0)), .exact(3))
        XCTAssertEqual(FindCount.combine(local: .exact(3), server: .exact(9)), .atLeast)
    }

    func testTheSelectionStartsOnTheTopHitClampsAndJumpsGroups() {
        let results = FindMerge.fresh(query: "x", local: local([row(.entity, "a", .entities, score: 5),
                                                                row(.entity, "b", .entities, score: 4),
                                                                row(.inbox, "i", .inbox, score: 3)]))
        let sections = results.sections(expanded: [])
        let start = FindSelection.initial(sections)
        XCTAssertEqual(start?.id, "a")
        XCTAssertEqual(FindSelection.move(start, .next, in: sections)?.id, "b")
        let top = FindSelection.move(start, .previous, in: sections)
        XCTAssertEqual(top?.kind, .ask)
        XCTAssertEqual(FindSelection.move(top, .previous, in: sections)?.kind, .ask, "no wrap")
        XCTAssertEqual(FindSelection.move(start, .nextGroup, in: sections)?.id, "b")
        XCTAssertEqual(FindSelection.move(FindRowKey(kind: .entity, id: "b"), .nextGroup, in: sections)?.id, "i")
        XCTAssertEqual(FindSelection.move(FindRowKey(kind: .inbox, id: "i"), .previousGroup, in: sections)?.id, "b")
        XCTAssertEqual(FindSelection.move(start, .last, in: sections)?.id, "i")
        XCTAssertEqual(FindSelection.move(start, .first, in: sections)?.kind, .ask)
    }

    func testTheSelectionSurvivesAServerAppend() {
        let results = FindMerge.fresh(query: "x", local: local([row(.entity, "a", .entities, score: 5)]))
        let key = FindSelection.initial(results.sections(expanded: []))
        let merged = FindMerge.append([row(.belief, "c1", .beliefs)], totals: [:], to: results)
        XCTAssertNotNil(key.flatMap { merged.row(for: $0) })
    }

    func testRecentsAreIdsOnlyDedupedCappedAndLocallyResolvable() {
        var list: [FindRowKey] = []
        for i in 0..<8 { list = FindRecents.push(FindRowKey(kind: .entity, id: "e\(i)"), into: list) }
        XCTAssertEqual(list.count, FindRecents.limit)
        XCTAssertEqual(list.first?.id, "e7")
        list = FindRecents.push(FindRowKey(kind: .entity, id: "e5"), into: list)
        XCTAssertEqual(list.first?.id, "e5")
        XCTAssertEqual(list.filter { $0.id == "e5" }.count, 1)
        let unchanged = FindRecents.push(FindRowKey(kind: .conversation, id: "ses_1"), into: list)
        XCTAssertEqual(unchanged, list, "R-SU6: a conversation cannot be drawn again without its text")
    }

    func testRowTextNamesTheKindAndThePosition() {
        let belief = FindRow(key: FindRowKey(kind: .belief, id: "c1"), group: .beliefs, title: "alpha-project uses sqlite-vec",
                             detail: "alpha-project", mark: .symbol("circle"), history: "until 3 Sep",
                             destination: .belief(subjectId: "alpha-project", claimId: "c1"))
        XCTAssertEqual(FindRowText.accessibilityLabel(belief), "Earlier belief, alpha-project uses sqlite-vec, alpha-project, until 3 Sep")
        XCTAssertEqual(FindRowText.announcement(belief, position: 2, of: 7), "Earlier belief, alpha-project uses sqlite-vec, 2 of 7")
        XCTAssertEqual(FindRowText.moreLabel(.exact(12)), "Show all 12")
        XCTAssertEqual(FindRowText.moreLabel(.atLeast), "More…")
    }
}
```

`QuickIndexLatencyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 design §3.10 / plan R-SU24 — the local tier's budget at the live
/// bank's scale, from a fixed seed and made-up syllables (the backend
/// latency test's rule, G136 R18: the same bank on every machine, no names).
/// The design's 8 ms is a RELEASE number; a debug `swift test` gates at
/// 300 ms, which still fails an accidental O(n²) (plan R-SU24). The orchestrator runs:
/// `swift test -c release -Xswiftc -enable-testing --filter QuickIndexLatencyTests`.
final class QuickIndexLatencyTests: XCTestCase {
    #if DEBUG
    static let budgetMs = 300.0
    #else
    static let budgetMs = SearchTiming.localBudgetMs
    #endif

    func testALocalKeystrokeIsWithinBudgetAtTheLiveBanksScale() {
        var rng = FindSeededGenerator(seed: 7)
        let syllables = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
                         "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]
        func word() -> String {
            (0..<Int.random(in: 2...4, using: &rng)).map { _ in syllables.randomElement(using: &rng)! }.joined()
        }
        func sentence(_ n: Int) -> String { (0..<n).map { _ in word() }.joined(separator: " ") }
        var inputs = QuickIndexInputs()
        inputs.nodes = (0..<3000).map { i in
            FindFixtures.node("e-\(i)", "\(word()) \(word()) \(i)", tags: [word()], summary: sentence(28), degree: i % 17)
        }
        inputs.media = (0..<1500).map { i in
            FindFixtures.media("m-\(i)", title: sentence(6), url: "https://example.com/\(word())/\(i)",
                               site: "example.com", description: sentence(30))
        }
        inputs.inbox = (0..<200).map { i in
            FindFixtures.inbox("inbox-\(i)", question: "Still tracking \(word())?", entityName: word(), excerpt: sentence(40))
        }
        let buildStart = DispatchTime.now().uptimeNanoseconds
        let index = QuickIndex.build(inputs)
        let buildMs = Double(DispatchTime.now().uptimeNanoseconds - buildStart) / 1_000_000
        var queries = (0..<40).map { _ in String(word().prefix(Int.random(in: 1...6, using: &rng))) }
        queries += (0..<10).map { _ in "\(word()) \(word().prefix(3))" }
        for query in queries.prefix(5) { _ = index.query(query) }   // warm
        var samples: [Double] = []
        for query in queries {
            let start = DispatchTime.now().uptimeNanoseconds
            _ = FindMerge.fresh(query: query, local: index.query(query))
            samples.append(Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
        }
        samples.sort()
        let p50 = samples[samples.count / 2]
        let p95 = samples[Int(Double(samples.count - 1) * 0.95)]
        print("G136 local tier: 3,000 entities + 1,500 media + 200 inbox; build \(String(format: "%.0f", buildMs)) ms; "
              + "keystroke p50 \(String(format: "%.2f", p50)) ms, p95 \(String(format: "%.2f", p95)) ms (budget \(Self.budgetMs) ms)")
        XCTAssertLessThanOrEqual(p95, Self.budgetMs)
    }
}

/// SplitMix64 — a fixed-seed generator so the synthetic bank is identical on every machine.
struct FindSeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
}
```

Run: `swift test --filter "QuickIndexTests|PaletteMergeTests|QuickIndexLatencyTests" 2>&1 | tail -20`
→ compile failure. That is the red.

- [ ] **Step 2: Implement.** `Search/FindModels.swift`:

```swift
import Foundation

/// The ⌘K palette's vocabulary (G136; round-3 design §3.3). Pure values: the
/// instant tier (`QuickIndex`), the server tier (`FindServerRows`), the merge
/// (`FindMerge`) and the views all speak these; nothing here touches the
/// network or the Store.

enum FindMode: String, Codable, Sendable { case find, ask }

enum FindKind: String, Codable, Sendable {
    case ask, entity, conversation, belief, media, source, inbox, setting, action, bank, askedBefore
}

/// A row's identity — the merge rule's dedupe key, `(kind, id)` (design §3.2),
/// and all a recent ever stores (R-SU6).
struct FindRowKey: Hashable, Codable, Sendable {
    let kind: FindKind
    let id: String
}

/// The fixed order (design §3.3: Top hit, Entities, Conversations, Beliefs,
/// Sources & papers, Inbox, Settings, Actions, Asked before), with the
/// empty-state groups (§3.6: Recent, Asked before, Suggested) in the same sequence.
enum FindGroupID: Int, CaseIterable, Comparable, Sendable {
    case ask, topHit, recent, entities, conversations, beliefs, sources, inbox, settings, actions, askedBefore, suggested

    static func < (lhs: FindGroupID, rhs: FindGroupID) -> Bool { lhs.rawValue < rhs.rawValue }

    var title: String {
        switch self {
        case .ask: ""
        case .topHit: "Top hit"
        case .recent: "Recent"
        case .entities: "Entities"
        case .conversations: "Conversations"
        case .beliefs: "Beliefs"
        case .sources: "Sources & papers"
        case .inbox: "Inbox"
        case .settings: "Settings"
        case .actions: "Actions"
        case .askedBefore: "Asked before"
        case .suggested: "Suggested"
        }
    }

    var glyph: String {
        switch self {
        case .ask: "sparkle.magnifyingglass"
        case .topHit: "star"
        case .recent: "clock"
        case .entities: "point.3.connected.trianglepath.dotted"
        case .conversations: "bubble.left.and.bubble.right"
        case .beliefs: "text.quote"
        case .sources: "photo.stack"
        case .inbox: "tray.full"
        case .settings: "gearshape"
        case .actions: "bolt"
        case .askedBefore: "arrow.uturn.left"
        case .suggested: "lightbulb"
        }
    }
}

/// A row's leading mark: the entity's own logo, a service's real mark
/// (`OriginMark` — installed app icon → bundled PNG → symbol), or a symbol.
enum FindMark: Equatable, Sendable {
    case entity(id: String, name: String, type: EntityType)
    case origin(String)
    case symbol(String)
}

/// A span into an evidence document (G118): what the Reader opens at.
struct ReaderSpan: Equatable, Sendable {
    let doc: String
    let start: Int?
    let end: Int?
    let hash: String?
    let claimId: String?
}

struct ConversationTarget: Equatable, Sendable {
    let span: ReaderSpan
    let conversationId: String?
    let harness: String?
    let origin: String?
    let title: String
}

/// R-SU13 — the palette's verbs, each one the same call the page that owns it makes.
enum PaletteAction: String, Codable, Sendable {
    case consolidate, stopConsolidating, zoomIn, zoomOut, actualSize, lightMode, darkMode
}

/// What a row opens. `ContentView.openFind(_:)` runs the navigating cases;
/// `FindPaletteModel.activate` handles `.ask`, `.askedBefore` and `.settings` itself.
enum FindDestination: Equatable, Sendable {
    case entity(id: String)
    case entityInClusters(id: String)
    case feedItem(mediaEntityId: String)
    case openURL(String)
    case source(id: String)
    case conversations(harness: String?, origin: String?, query: String?)
    case conversation(ConversationTarget)
    case belief(subjectId: String, claimId: String)
    case evidence(ReaderSpan)
    case inbox(id: String)
    case settings(SettingsSection)
    case tab(AppTab)
    case action(PaletteAction)
    case bank(name: String)
    case ask(String)
    case askedBefore(question: String)
}

struct FindRow: Identifiable, Equatable, Sendable {
    let key: FindRowKey
    var id: FindRowKey { key }
    var group: FindGroupID
    let title: String
    /// Scalar ranges to bold in `title` (`ExcerptText.attributed`).
    var titleRanges: [[Int]] = []
    var detail: String? = nil
    /// A passage, drawn in `quoteFont` (conversations).
    var snippet: String? = nil
    var snippetRanges: [[Int]] = []
    var badge: String? = nil
    var mark: FindMark
    var trailing: String? = nil
    /// "You said" / "Agent replied" / "From page" / "Inferred" (design §4.2's labels).
    var speaker: String? = nil
    /// Set only on a superseded belief: "until 3 Sep" (R-SU19).
    var history: String? = nil
    var score: Double = 0
    var tieBreak: Double = 0
    var destination: FindDestination
    var secondary: FindDestination? = nil
}

/// R-SU15 — a count is exact or it is "More…"; never a guessed number (design §3.3).
enum FindCount: Equatable, Sendable {
    case exact(Int)
    case atLeast

    /// Two tiers feeding one group: the local tier counts what it matched, the
    /// server counts lexical documents, and their union is unknown — unless one
    /// side found nothing.
    static func combine(local: FindCount?, server: FindCount) -> FindCount {
        switch (local, server) {
        case (nil, _), (.exact(0)?, _): return server
        case (_, .exact(0)): return local ?? server
        default: return .atLeast
        }
    }
}

struct FindSection: Identifiable, Equatable, Sendable {
    let group: FindGroupID
    let rows: [FindRow]
    /// The row under the group: "Show all N" (`.exact`) or "More…" (`.atLeast`); nil when all is shown.
    let more: FindCount?
    /// "5 of 12" beside the header — only for an exact count.
    let headerCount: String?
    var id: FindGroupID { group }
}

struct FindResults: Equatable, Sendable {
    static let perGroup = 5
    static let empty = FindResults()

    var query = ""
    var ask: FindRow? = nil
    var topHit: FindRow? = nil
    var groups: [FindGroupID: [FindRow]] = [:]
    /// Every local match per group (before the render cap).
    var localCounts: [FindGroupID: Int] = [:]
    /// The latest server pass's count per group — replaced by each pass, never compounded.
    var serverCounts: [FindGroupID: FindCount] = [:]

    var keys: Set<FindRowKey> {
        var out = Set(groups.values.flatMap { $0.map(\.key) })
        if let ask { out.insert(ask.key) }
        if let topHit { out.insert(topHit.key) }
        return out
    }

    var rowCount: Int { groups.values.reduce(0) { $0 + $1.count } + (topHit == nil ? 0 : 1) }
    var groupCount: Int { groups.values.filter { !$0.isEmpty }.count + (topHit == nil ? 0 : 1) }

    func row(for key: FindRowKey) -> FindRow? {
        if ask?.key == key { return ask }
        if topHit?.key == key { return topHit }
        for rows in groups.values { if let found = rows.first(where: { $0.key == key }) { return found } }
        return nil
    }

    func count(for group: FindGroupID) -> FindCount {
        let local = localCounts[group].map { FindCount.exact($0) }
        guard let server = serverCounts[group] else { return local ?? .exact(groups[group]?.count ?? 0) }
        return FindCount.combine(local: local, server: server)
    }

    /// What renders, in the fixed order: the Ask row, the top hit, then each
    /// non-empty group capped at `perGroup` unless expanded.
    func sections(expanded: Set<FindGroupID>) -> [FindSection] {
        var out: [FindSection] = []
        if let ask { out.append(FindSection(group: .ask, rows: [ask], more: nil, headerCount: nil)) }
        if let topHit { out.append(FindSection(group: .topHit, rows: [topHit], more: nil, headerCount: nil)) }
        for group in FindGroupID.allCases where group != .ask && group != .topHit {
            guard let rows = groups[group], !rows.isEmpty else { continue }
            let open = expanded.contains(group)
            let shown = open ? rows : Array(rows.prefix(Self.perGroup))
            let more: FindCount?
            var header: String? = nil
            switch count(for: group) {
            case .exact(let n):
                more = n > shown.count ? .exact(n) : nil
                if n > shown.count { header = "\(UsageFormat.count(shown.count)) of \(UsageFormat.count(n))" }
            case .atLeast:
                // An expanded "More…" group has asked for all the server will give (R-SU14).
                more = open ? nil : .atLeast
            }
            out.append(FindSection(group: group, rows: shown, more: more, headerCount: header))
        }
        return out
    }
}

/// R-SU18 — whether the provenance Reader (Track P's `ProvenanceRouter`,
/// round-3 design §1.4/§4.4) is in this build. `false` until that track
/// merges: a conversation row then opens its source's conversation list
/// filtered to its title, and a belief's "where it was said" secondary is
/// withheld rather than offered and dropped. Flip it in the same commit that
/// routes `.conversation` / `.evidence` through the Reader (`ContentView.openFind`).
enum FindReaderSeam {
    static let isAvailable = false
}
```

`Search/FindMerge.swift`:

```swift
import Foundation

/// Design §3.2's merge rule, as pure functions: local rows render first; server
/// rows dedupe against them by `(kind, id)` and APPEND in their group; rows
/// already shown for this query never reorder; a new keystroke re-sorts
/// everything; the top hit comes from the local tier only.
enum FindMerge {
    static func fresh(query: String, local: QuickIndex.Result) -> FindResults {
        var results = FindResults(query: query)
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return results }
        results.ask = FindRow(key: FindRowKey(kind: .ask, id: "ask"), group: .ask,
                              title: "Ask Cicada: “\(trimmed)”", mark: .symbol("sparkle.magnifyingglass"),
                              trailing: "⌘⏎", destination: .ask(trimmed))
        var groups = Dictionary(grouping: local.rows, by: \.group)
        results.localCounts = local.counts
        // An Asked-before row repeats a question; it never stands for the thing searched.
        var top: FindRow?
        for row in local.rows where row.group != .askedBefore {
            if let best = top, !(row.score > best.score || (row.score == best.score && row.group < best.group)) { continue }
            top = row
        }
        if var hit = top {
            groups[hit.group]?.removeAll { $0.key == hit.key }
            results.localCounts[hit.group] = max(0, (local.counts[hit.group] ?? 1) - 1)
            hit.group = .topHit
            results.topHit = hit
        }
        results.groups = groups.filter { !$0.value.isEmpty }
        return results
    }

    static func append(_ server: [FindRow], totals: [FindGroupID: FindCount], to results: FindResults) -> FindResults {
        var out = results
        var seen = out.keys
        for row in server where seen.insert(row.key).inserted {
            out.groups[row.group, default: []].append(row)
        }
        for (group, count) in totals { out.serverCounts[group] = count }
        return out
    }
}

enum FindStep: Equatable, Sendable { case next, previous, first, last, nextGroup, previousGroup }

/// The keyboard walk over what renders (design §3.4). The selection is a
/// key, never an index, so an append can never move it (§3.2).
enum FindSelection {
    static func flat(_ sections: [FindSection]) -> [(group: FindGroupID, key: FindRowKey)] {
        sections.flatMap { section in section.rows.map { (group: section.group, key: $0.key) } }
    }

    /// The top hit, else the first row that is not the Ask row, else the Ask row.
    static func initial(_ sections: [FindSection]) -> FindRowKey? {
        if let top = sections.first(where: { $0.group == .topHit })?.rows.first { return top.key }
        if let first = sections.first(where: { $0.group != .ask })?.rows.first { return first.key }
        return sections.first?.rows.first?.key
    }

    /// R-SU11: clamps at both ends.
    static func move(_ current: FindRowKey?, _ step: FindStep, in sections: [FindSection]) -> FindRowKey? {
        let rows = flat(sections)
        guard !rows.isEmpty else { return nil }
        guard let current, let index = rows.firstIndex(where: { $0.key == current }) else { return initial(sections) }
        switch step {
        case .next: return rows[min(index + 1, rows.count - 1)].key
        case .previous: return rows[max(index - 1, 0)].key
        case .first: return rows[0].key
        case .last: return rows[rows.count - 1].key
        case .nextGroup:
            let group = rows[index].group
            return rows[index...].first(where: { $0.group != group })?.key ?? current
        case .previousGroup:
            let group = rows[index].group
            guard let previous = rows[..<index].last(where: { $0.group != group })?.group else { return current }
            return rows.first(where: { $0.group == previous })?.key
        }
    }
}

/// R-SU6 — ids only, per bank, and only what the local tier can draw again.
enum FindRecents {
    static let limit = 6
    static let recordable: Set<FindKind> = [.entity, .media, .source, .inbox, .setting, .action, .bank]

    static func push(_ key: FindRowKey, into list: [FindRowKey]) -> [FindRowKey] {
        guard recordable.contains(key.kind) else { return list }
        return Array(([key] + list.filter { $0 != key }).prefix(limit))
    }
}

/// Every string a row speaks, pure so VoiceOver's text is tested (design §3.8).
enum FindRowText {
    static func kindLabel(_ row: FindRow) -> String {
        switch row.key.kind {
        case .ask: "Ask"
        case .entity: row.badge ?? "Entity"
        case .conversation: "Conversation"
        case .belief: row.history == nil ? "Belief" : "Earlier belief"
        case .media: "Saved item"
        case .source: "Source"
        case .inbox: "Question"
        case .setting: "Setting"
        case .action: "Action"
        case .bank: "Memory bank"
        case .askedBefore: "Asked before"
        }
    }

    static func accessibilityLabel(_ row: FindRow) -> String {
        let quote = row.snippet.map { snippet in row.speaker.map { "\($0): \(snippet)" } ?? snippet }
        return [kindLabel(row), row.title, row.detail, row.history, quote]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
    }

    static func announcement(_ row: FindRow, position: Int, of total: Int) -> String {
        "\(kindLabel(row)), \(row.title), \(position) of \(total)"
    }

    static func moreLabel(_ count: FindCount) -> String {
        switch count {
        case .exact(let n): "Show all \(UsageFormat.count(n))"
        case .atLeast: "More…"
        }
    }

    static func primaryVerb(_ destination: FindDestination) -> String {
        switch destination {
        case .entity, .belief: "Show on graph"
        case .entityInClusters: "Open in Clusters"
        case .feedItem: "Preview"
        case .openURL: "Open in browser"
        case .source, .conversations: "Open in Sources"
        case .conversation, .evidence: FindReaderSeam.isAvailable ? "Open conversation" : "Open in Sources"
        case .inbox: "Answer"
        case .settings: "Open in Settings"
        case .tab: "Go"
        case .action: "Run"
        case .bank: "Switch"
        case .ask: "Ask"
        case .askedBefore: "Show answer"
        }
    }

    static func secondaryVerb(_ destination: FindDestination?) -> String? {
        switch destination {
        case .entityInClusters?: "Open in Clusters"
        case .openURL?: "Open in browser"
        case .conversations?: "All from this app"
        case .evidence?: "Where it was said"
        case .ask?: "Ask again"
        default: nil
        }
    }
}
```

`Search/SearchTiming.swift`:

```swift
import Foundation

/// The palette's clock and sizes (round-3 design §1.1). Not motion, so they
/// live here rather than in `CicadaMotion`.
enum SearchTiming {
    /// The owner's brief (2026-09-23) set 150–200 ms, over the design's 120 ms
    /// (R-SU14): a fast typist never sends a mid-word request, and the server
    /// answers a prefix in ~5 ms warm, so the pause is the latency.
    static let serverDebounce: Duration = .milliseconds(150)
    /// Idle before the hybrid (vector) pass — once the typing has settled.
    static let semanticIdle: Duration = .milliseconds(450)
    static let perKind = 5
    /// "Show all" on a server-fed group re-asks that kind at the server's cap (`MAX_PER_KIND`).
    static let expandedPerKind = 20
    /// Design §3.10: p95 per keystroke in a release build (R-SU24).
    static let localBudgetMs = 8.0

    /// `text_fold.MIN_TOKEN_CHARS`: the server searches nothing shorter than two characters.
    static func wantsServer(_ query: String) -> Bool {
        QuickMatch.tokens(query).contains { $0.scalars.count >= 2 }
    }
}
```

`Search/FeedSearch.swift`:

```swift
import Foundation

/// Every field a saved item is found by — ONE list, read by the Feed page and
/// by the palette (design §3.7: title, site, tags plus description, about, url,
/// channel, origin). Paper authors / arXiv id / DOI join here when Track F's
/// `MediaFeedItem.paper` is on the wire (R-SU21).
enum FeedSearch {
    static func fields(_ item: MediaFeedItem) -> [QuickMatch.Field] {
        var fields = [QuickMatch.Field(item.title.isEmpty ? item.url : item.title, weight: QuickMatch.Weight.name)]
        for value in [item.site, item.channel, item.origin].compactMap({ $0 }) where !value.isEmpty {
            fields.append(QuickMatch.Field(value, weight: QuickMatch.Weight.keyword))
        }
        fields += item.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
        if let description = item.description, !description.isEmpty {
            fields.append(QuickMatch.Field(description, weight: QuickMatch.Weight.body))
        }
        fields.append(QuickMatch.Field(item.url, weight: QuickMatch.Weight.body))
        fields += (item.about ?? []).map { QuickMatch.Field($0, weight: QuickMatch.Weight.body) }
        return fields
    }

    static func matches(_ item: MediaFeedItem, query: String) -> Bool {
        QuickMatch.matches(query, fields: fields(item))
    }

    /// R-SU20: the Feed's own sort is kept; this only filters.
    static func filter(_ items: [MediaFeedItem], query: String) -> [MediaFeedItem] {
        let tokens = QuickMatch.tokens(query)
        guard !tokens.isEmpty else { return items }
        return items.filter { QuickMatch.match(tokens, fields: fields($0)) != nil }
    }
}
```

`Search/InboxSearch.swift`:

```swift
import Foundation

/// The fields an inbox question is found by — the palette and the Inbox page's
/// own field read this one list (design §3.2's Inbox row: question/title 1.0,
/// entity name 0.7, the cause excerpt 0.4).
enum InboxSearch {
    static func title(_ item: InboxItem) -> String {
        if let question = item.question, !question.isEmpty { return question }
        return item.title
    }

    static func fields(_ item: InboxItem) -> [QuickMatch.Field] {
        var fields = [QuickMatch.Field(title(item), weight: QuickMatch.Weight.name)]
        if !item.entityName.isEmpty { fields.append(QuickMatch.Field(item.entityName, weight: QuickMatch.Weight.keyword)) }
        if let excerpt = item.cause?.excerpt, !excerpt.isEmpty {
            fields.append(QuickMatch.Field(excerpt, weight: QuickMatch.Weight.body))
        }
        return fields
    }

    /// R-SU20: the Inbox keeps its priority order.
    static func filter(_ items: [InboxItem], query: String) -> [InboxItem] {
        let tokens = QuickMatch.tokens(query)
        guard !tokens.isEmpty else { return items }
        return items.filter { QuickMatch.match(tokens, fields: fields($0)) != nil }
    }
}
```

`Search/QuickIndex.swift`:

```swift
import Foundation

/// A value copy of what the local tier reads, taken on the main actor and
/// handed to a detached build (design §3.2: "built off the main actor").
struct QuickIndexInputs: Sendable {
    var nodes: [GraphNode] = []
    var media: [MediaFeedItem] = []
    var sources: [SourceOverview] = []
    var inbox: [InboxItem] = []
    var banks: [MemoryBank] = []
    var activeBank: String? = nil
    var askHistory: [AskHistoryEntry] = []
    var isSleeping = false
    var unprocessed = 0
    var appearance: AppColorScheme = .dark

    @MainActor
    static func from(_ store: Store, askHistory: [AskHistoryEntry]) -> QuickIndexInputs {
        QuickIndexInputs(nodes: store.graph.value?.nodes ?? [], media: store.sources.value ?? [],
                         sources: store.sourcesOverview.value ?? [], inbox: store.visibleInbox,
                         banks: store.banks.value?.banks ?? [], activeBank: store.bank,
                         askHistory: askHistory,
                         isSleeping: store.status.value?.sleep.status == "running",
                         unprocessed: store.status.value?.episodes.unprocessed ?? 0,
                         appearance: CicadaTheme.mode)
    }

    /// Changes whenever an input could have (R-SU5) — timestamps, counts and
    /// flags only, never a name or a query. `unprocessed` enters as a flag: a
    /// capture on every agent turn must not rebuild the index each time.
    @MainActor
    static func token(_ store: Store, askHistoryCount: Int) -> String {
        let stamps = [store.graph.loadedAt, store.sources.loadedAt, store.sourcesOverview.loadedAt,
                      store.inbox.loadedAt, store.banks.loadedAt]
            .map { $0.map { String($0.timeIntervalSince1970) } ?? "-" }
        let flags = ["\(store.hiddenInboxIds.count)", "\(askHistoryCount)",
                     store.status.value?.sleep.status ?? "",
                     (store.status.value?.episodes.unprocessed ?? 0) > 0 ? "waiting" : "rested",
                     CicadaTheme.mode.rawValue]
        return ([store.bank] + stamps + flags).joined(separator: "|")
    }
}

/// The palette's instant tier (G136; round-3 design §3.2 "Tier 1"): an
/// immutable value over the Store's snapshots, folded once per build and
/// queried on every keystroke with no network. Budget: R-SU24.
struct QuickIndex: Sendable {
    struct Doc: Sendable {
        let row: FindRow
        /// `fields[0]` is always the row's title — its ranges bold the title.
        let fields: [QuickMatch.Field]
    }

    struct Result: Equatable, Sendable {
        var rows: [FindRow] = []
        /// Every local match per group before the materialisation cap — the honest "Show all N".
        var counts: [FindGroupID: Int] = [:]
    }

    /// Past this, a group stops materialising rows; its count stays exact.
    static let rowCap = 50
    static let empty = QuickIndex()

    private(set) var docs: [Doc] = []
    private(set) var byKey: [FindRowKey: Int] = [:]
    private(set) var suggested: [FindRow] = []
    private(set) var askedBefore: [FindRow] = []

    init() {}

    static func build(_ inputs: QuickIndexInputs) -> QuickIndex {
        var index = QuickIndex()
        let asked = askedDocs(inputs.askHistory)
        index.docs = entityDocs(inputs.nodes) + mediaDocs(inputs.media) + sourceDocs(inputs.sources)
            + inboxDocs(inputs.inbox) + settingsDocs() + PaletteActions.docs(inputs) + asked
        for (i, doc) in index.docs.enumerated() where index.byKey[doc.row.key] == nil {
            index.byKey[doc.row.key] = i
        }
        index.suggested = PaletteActions.suggested(inputs)
        index.askedBefore = asked.prefix(3).map(\.row)
        return index
    }

    func query(_ text: String) -> Result {
        let tokens = QuickMatch.tokens(text)
        guard !tokens.isEmpty else { return Result() }
        var byGroup: [FindGroupID: [(doc: Int, match: QuickMatch.Match)]] = [:]
        for (i, doc) in docs.enumerated() {
            if let found = QuickMatch.match(tokens, fields: doc.fields) {
                byGroup[doc.row.group, default: []].append((i, found))
            }
        }
        var result = Result()
        for group in FindGroupID.allCases {
            guard let hits = byGroup[group] else { continue }
            result.counts[group] = hits.count
            let ordered = hits.sorted { a, b in
                if a.match.score != b.match.score { return a.match.score > b.match.score }
                let ra = docs[a.doc].row, rb = docs[b.doc].row
                if ra.tieBreak != rb.tieBreak { return ra.tieBreak > rb.tieBreak }
                return ra.title < rb.title
            }
            for hit in ordered.prefix(Self.rowCap) {
                var row = docs[hit.doc].row
                row.score = hit.match.score
                row.titleRanges = hit.match.ranges(inField: 0)
                result.rows.append(row)
            }
        }
        return result
    }

    /// Nothing typed (design §3.6): Recent (ids resolved here; a gone id is
    /// dropped), then Asked before (three), then Suggested.
    func emptyState(recents: [FindRowKey]) -> FindResults {
        var results = FindResults()
        let recent = recents.compactMap { key -> FindRow? in
            guard let i = byKey[key] else { return nil }
            var row = docs[i].row
            row.group = .recent
            return row
        }
        if !recent.isEmpty { results.groups[.recent] = recent }
        if !askedBefore.isEmpty { results.groups[.askedBefore] = askedBefore }
        if !suggested.isEmpty { results.groups[.suggested] = suggested }
        return results
    }
}

extension QuickIndex {
    /// Graph nodes minus facets, hubs and media pages (R-SU5).
    static func entityDocs(_ nodes: [GraphNode]) -> [Doc] {
        nodes.compactMap { node in
            guard !node.isFacet, !node.isHub, node.type != .hub, node.type != .media else { return nil }
            var fields = [QuickMatch.Field(node.name, weight: QuickMatch.Weight.name)]
            fields += node.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
            if let summary = node.summary, !summary.isEmpty {
                fields.append(QuickMatch.Field(summary, weight: QuickMatch.Weight.body))
            }
            let row = FindRow(key: FindRowKey(kind: .entity, id: node.id), group: .entities, title: node.name,
                              detail: node.summary.flatMap(firstLine), badge: node.type.label,
                              mark: .entity(id: node.id, name: node.name, type: node.type),
                              tieBreak: Double(node.degree), destination: .entity(id: node.id),
                              secondary: .entityInClusters(id: node.id))
            return Doc(row: row, fields: fields)
        }
    }

    /// One row per media page, whatever number of URLs share its id.
    static func mediaDocs(_ items: [MediaFeedItem]) -> [Doc] {
        var seen = Set<String>()
        return items.compactMap { item in
            guard seen.insert(item.mediaEntityId).inserted else { return nil }
            let title = item.title.isEmpty ? item.url : item.title
            let row = FindRow(key: FindRowKey(kind: .media, id: item.mediaEntityId), group: .sources, title: title,
                              detail: item.site ?? item.channel, badge: item.mediaType,
                              mark: .entity(id: item.mediaEntityId, name: title, type: .media),
                              tieBreak: item.recencyDate.timeIntervalSince1970,
                              destination: .feedItem(mediaEntityId: item.mediaEntityId),
                              secondary: .openURL(item.url))
            return Doc(row: row, fields: FeedSearch.fields(item))
        }
    }

    /// The Sources page's cards, under the product names that page prints.
    static func sourceDocs(_ rows: [SourceOverview]) -> [Doc] {
        rows.map { source in
            let name = SourceDisplayName.of(source)
            var fields = [QuickMatch.Field(name, weight: QuickMatch.Weight.name),
                          QuickMatch.Field(source.label, weight: QuickMatch.Weight.alias)]
            fields += (source.origins + [source.harness].compactMap { $0 })
                .map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
            let row = FindRow(key: FindRowKey(kind: .source, id: source.id), group: .sources, title: name,
                              badge: "Source", mark: .origin(source.mark), tieBreak: Double(source.episodes),
                              destination: .source(id: source.id))
            return Doc(row: row, fields: fields)
        }
    }

    static func inboxDocs(_ items: [InboxItem]) -> [Doc] {
        items.map { item in
            let row = FindRow(key: FindRowKey(kind: .inbox, id: item.id), group: .inbox, title: InboxSearch.title(item),
                              detail: item.entityName.isEmpty ? nil : item.entityName, badge: item.kind.label,
                              mark: .symbol(item.kind.icon), tieBreak: item.priority, destination: .inbox(id: item.id))
            return Doc(row: row, fields: InboxSearch.fields(item))
        }
    }

    /// R-SU12 — one row per Settings section, whatever sections exist.
    static func settingsDocs() -> [Doc] {
        SettingsSection.allCases.enumerated().map { i, section in
            let row = FindRow(key: FindRowKey(kind: .setting, id: section.rawValue), group: .settings,
                              title: section.title, detail: Copy.settings, mark: .symbol(section.icon),
                              tieBreak: -Double(i), destination: .settings(section))
            return Doc(row: row, fields: [QuickMatch.Field(section.title, weight: QuickMatch.Weight.name),
                                          QuickMatch.Field(Copy.settings, weight: QuickMatch.Weight.keyword)])
        }
    }

    static func askedDocs(_ history: [AskHistoryEntry]) -> [Doc] {
        history.map { entry in
            let row = FindRow(key: FindRowKey(kind: .askedBefore, id: entry.id), group: .askedBefore,
                              title: entry.question, mark: .symbol("arrow.uturn.left"),
                              tieBreak: entry.askedAt.timeIntervalSince1970,
                              destination: .askedBefore(question: entry.question), secondary: .ask(entry.question))
            return Doc(row: row, fields: [QuickMatch.Field(entry.question, weight: QuickMatch.Weight.name)])
        }
    }

    static func firstLine(_ text: String) -> String? {
        let line = text.split(whereSeparator: \.isNewline).first.map(String.init)?
            .trimmingCharacters(in: .whitespaces)
        return (line?.isEmpty ?? true) ? nil : line
    }
}
```

`Search/PaletteActions.swift`:

```swift
import Foundation

/// The palette's actions table (design §3.3, trimmed by R-SU13). Each title is
/// the verb the page that owns the action already uses, and each runs the same
/// call that page makes (`ContentView.openFind`).
enum PaletteActions {
    static func docs(_ inputs: QuickIndexInputs) -> [QuickIndex.Doc] {
        var docs: [QuickIndex.Doc] = []
        func add(_ id: String, _ title: String, keywords: [String], symbol: String, trailing: String? = nil,
                 destination: FindDestination, kind: FindKind = .action, order: Int) {
            let row = FindRow(key: FindRowKey(kind: kind, id: id), group: .actions, title: title,
                              mark: .symbol(symbol), trailing: trailing, tieBreak: -Double(order),
                              destination: destination)
            docs.append(QuickIndex.Doc(row: row, fields: [QuickMatch.Field(title, weight: QuickMatch.Weight.name)]
                + keywords.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }))
        }
        if inputs.isSleeping {
            add("stop-consolidating", "Stop consolidating", keywords: ["sleep", "cancel", "stop"],
                symbol: "stop.circle", destination: .action(.stopConsolidating), order: 0)
        } else if inputs.unprocessed > 0 {
            // The Sleep page's own gate (`SleepPageModel.consolidateEnabled`,
            // R-A7): nothing queued, nothing to run.
            add("consolidate", "Consolidate now", keywords: ["sleep", "run", "consolidate"],
                symbol: "moon.zzz", destination: .action(.consolidate), order: 0)
        }
        for (i, tab) in AppTab.allCases.enumerated() {
            add("tab.\(tab.rawValue)", "Go to \(tab.title)", keywords: ["open", "page", "show"], symbol: tab.icon,
                trailing: i < 9 ? "⌘\(i + 1)" : nil, destination: .tab(tab), order: 10 + i)
        }
        if inputs.appearance == .dark {
            add("appearance.light", "Switch to light", keywords: ["appearance", "theme", "day"],
                symbol: "sun.max", destination: .action(.lightMode), order: 30)
        } else {
            add("appearance.dark", "Switch to dark", keywords: ["appearance", "theme", "night"],
                symbol: "moon", destination: .action(.darkMode), order: 30)
        }
        add("zoom.in", "Zoom in", keywords: ["text size", "bigger", "larger"], symbol: "plus.magnifyingglass",
            trailing: "⌘+", destination: .action(.zoomIn), order: 31)
        add("zoom.out", "Zoom out", keywords: ["text size", "smaller"], symbol: "minus.magnifyingglass",
            trailing: "⌘−", destination: .action(.zoomOut), order: 32)
        add("zoom.reset", "Actual size", keywords: ["text size", "zoom", "reset"], symbol: "1.magnifyingglass",
            trailing: "⌘0", destination: .action(.actualSize), order: 33)
        for (i, bank) in inputs.banks.enumerated() where bank.name != inputs.activeBank {
            add(bank.name, "Switch to \(bank.name)", keywords: ["memory bank", "bank", "switch"], symbol: "tray.2",
                destination: .bank(name: bank.name), kind: .bank, order: 40 + i)
        }
        return docs
    }

    /// The empty state's suggestions (design §3.6), each only when it is true.
    static func suggested(_ inputs: QuickIndexInputs) -> [FindRow] {
        var rows: [FindRow] = []
        if !inputs.isSleeping && inputs.unprocessed > 0 {
            rows.append(FindRow(key: FindRowKey(kind: .action, id: "suggest.consolidate"), group: .suggested,
                                title: "Consolidate now", detail: "New memories are waiting to be read",
                                mark: .symbol("moon.zzz"), destination: .action(.consolidate)))
        }
        if !inputs.inbox.isEmpty {
            let n = inputs.inbox.count
            rows.append(FindRow(key: FindRowKey(kind: .action, id: "suggest.inbox"), group: .suggested,
                                title: n == 1 ? "Answer 1 question" : "Answer \(UsageFormat.count(n)) questions",
                                mark: .symbol("tray.full"), destination: .tab(.inbox)))
        }
        return rows
    }
}
```

- [ ] **Step 3: Green.** `swift test --filter "QuickIndexTests|PaletteMergeTests|QuickIndexLatencyTests" 2>&1 | tail -30`
  → pass; copy the `G136 local tier:` line into the task report. Then `swift build` and the full
  `swift test` → 0 failures.
- [ ] **Step 4: Commit** — stage the seven `Search/*.swift` files and the four test files:
  `feat(search): the palette's instant tier — QuickIndex, the merge rule, honest counts (G136 S3, R-SU5/R-SU15/R-SU24)`.

---
### Task 3: ⌘K is a find palette with Ask as a mode; ⌘K/⌘F are menu commands (S3 + Ask from S4; A4, A6, A11; R-SU6…R-SU13, R-SU17, R-SU18)

The Ask sheet is replaced in the same commit that brings Ask back as a mode (R-SU7), so ⌘K never
loses Ask. Every local row opens something real by the end of this task; the server groups arrive in
Task 4.

**Files:**
- Create: `…/Search/FindPaletteModel.swift`, `…/Search/FindKeymap.swift`, `…/Search/ConversationSource.swift`,
  `…/Support/FindCommands.swift`, `…/Views/Find/FindPalette.swift`, `…/Views/Find/FindPanelBody.swift`,
  `…/Views/Find/FindRowView.swift`
- Modify: `…/Support/AppRouter.swift`, `…/CicadaApp.swift`, `…/ContentView.swift`, `…/Ask/AskPanel.swift`
  (above `// MARK: - Answer` only), `…/Views/Inbox/InboxListView.swift`, `…/Views/Inbox/InboxCardView.swift`,
  `…/Views/Topics/TopicsView.swift`, `…/Views/Sources/SourcesPageView.swift`,
  `…/Views/Sources/HarnessConversationsView.swift`, `…/Views/Feed/FeedView.swift:440`,
  `…/Sync/Snapshot.swift`, `…/Sync/Store.swift:283-285`, `…/Theme/CicadaMotion.swift`
- Test: `FindPaletteTests.swift`, `FindRoutingTests.swift`, `HiddenShortcutLintTests.swift` (new);
  `MutationTests.swift:314-318`, `CicadaMotionTests.swift:23-26` (edit)

**Interfaces:**
- Produces `FindPaletteModel` (`query`, `mode`, `results`, `sections`, `selection`, `expanded`, `hint`,
  `isPresented`, `ask`, `fieldText`, `recents`, `setFieldText`, `setQuery`, `setMode`, `install`,
  `rebuildIndex`, `present`, `dismissed`, `move`, `select`, `escape`, `askNow`, `submit`, `activate`,
  `toggleExpanded`, `footerText`, `selectionAnnouncement`); `FindKeyAction` + `FindKeymap.action`;
  `ConversationSource.sourceId`; `PageFindAction`, `FocusedValues.pageFind`, `View.publishesPageFind`,
  `FindCommands`, `PaletteRequest`, `PaletteToggle`; `FindPalette`, **`FindPanelBody`** (the Home
  page's host), `FindRowView`, `FindMarkView`; `AppRouter.requestPalette/consumePalette`,
  `pendingInboxItem`, `pendingClustersEntity`, `pendingConversationQuery` + consumers; Track Z's
  `pendingSourceDetail`/`routeToSourceDetail`/`consumeSourceDetail`; `SyncDomain.quickRecents`;
  `CicadaMotion.paletteIn/paletteOut/groupExpand`; `SearchButton`; `FindIndexTask` (file-private in
  `ContentView.swift`); `AskPanel(onSelectEntity:hostedViewModel:)`.
- Consumes Task 1–2's values, `AskViewModel`, `LogoImage`, `OriginMark`, `SettingsSectionLink`,
  `ExcerptText.attributed`, `liquidGlass`, `iconHover`, `CicadaMotion`, `SleepViewModel.triggerManually/cancel`,
  `BanksViewModel.activate(_:)`, `GraphViewModel.loadGraph()`.

- [ ] **Step 0: Is Track Z's source-detail hand-off on `dev` yet?**
  `cd <worktree> && git merge --no-edit dev && grep -n "routeToSourceDetail\|consumeSourceDetail" app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourcesPageView.swift`.
  If both files already have it, **skip** every block Step 2 marks *Track Z seam* (three in
  `AppRouter.swift`, one in `SourcesPageView.swift`) and use theirs. If not, add those blocks
  **byte-for-byte, at exactly the positions given**, so that when Track Z merges
  its identical hunks merge clean (R-SU18). Either way, run the suites once after the merge to
  re-measure the baseline. *Critic:* Track Z merged in PR #76 and Track F in PR #77, so the expected
  outcome is **both greps hit — skip the four seam blocks**; the merge applies cleanly over Tasks 1–2
  (neither track touches `GraphViewModel.swift` or `Search/`), and the dev baseline it leaves was
  1,253 Swift tests at `a5fb5f1`. Every line number cited below is from `f7dfd21`; after this merge
  `SourceOverview.swift`, `AppRouter.swift`, `SourcesPageView.swift`, `CicadaApp.swift`,
  `FeedViewModel.swift` and `FeedView.swift` have moved — find each edit by its quoted anchor.

- [ ] **Step 1: Failing tests.** `FindPaletteTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// G136 S3/S4 — the palette's state machine, keys and hand-offs, without a
/// view. NEVER call `askNow()` or activate an Ask / re-ask row here:
/// `AskViewModel.ask()` posts `/ask` through `APIClient.shared` — on a dev
/// machine the owner's live backend — and `/ask` spends.
@MainActor
final class FindPaletteTests: XCTestCase {
    private func model(_ inputs: QuickIndexInputs = FindFixtures.inputs()) -> FindPaletteModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let model = FindPaletteModel(store: store)
        model.install(QuickIndex.build(inputs))
        return model
    }

    func testTypingFillsTheGroupsAtOnceAndSelectsTheTopHit() {
        let m = model()
        m.setQuery("alpha")
        XCTAssertEqual(m.results.ask?.destination, .ask("alpha"))
        XCTAssertEqual(m.results.topHit?.key, FindRowKey(kind: .entity, id: "alpha-project"))
        XCTAssertEqual(m.selection, FindRowKey(kind: .entity, id: "alpha-project"))
        XCTAssertTrue(m.footerText.hasPrefix("3 results in 3 groups"))
    }

    func testArrowsMoveAndReturnOpensTheSelectedRow() {
        let m = model()
        m.setQuery("alpha")
        XCTAssertEqual(m.submit(), .entity(id: "alpha-project"))
        m.move(.previous)
        XCTAssertEqual(m.selection?.kind, .ask)
        m.move(.last)
        XCTAssertEqual(m.selection?.kind, .inbox)
    }

    func testEscapeGoesAskToFindThenClearsThenCloses() {
        let m = model()
        m.present(prefill: "alpha")
        XCTAssertTrue(m.isPresented)
        m.setMode(.ask)
        XCTAssertEqual(m.ask.question, "alpha", "the text travels into Ask")
        XCTAssertFalse(m.escape())
        XCTAssertEqual(m.mode, .find)
        XCTAssertEqual(m.query, "alpha", "Esc in Ask keeps the text")
        XCTAssertFalse(m.escape())
        XCTAssertEqual(m.query, "")
        XCTAssertTrue(m.escape(), "the third Esc closes")
        m.dismissed()
        XCTAssertFalse(m.isPresented)
    }

    func testRecentsKeepIdsOnly() throws {
        let m = model()
        m.setQuery("alpha")
        XCTAssertEqual(m.activate(FindRowKey(kind: .entity, id: "alpha-project")), .entity(id: "alpha-project"))
        XCTAssertEqual(m.recents, [FindRowKey(kind: .entity, id: "alpha-project")])
        m.setQuery("")
        XCTAssertEqual(m.results.groups[.recent]?.map(\.key.id), ["alpha-project"])
        let data = try JSONEncoder().encode(m.recents)
        let objects = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [[String: String]])
        XCTAssertEqual(Set(objects[0].keys), ["kind", "id"], "a recent is a key — never the query, never a title")
    }

    func testASettingsRowExplainsInsteadOfOpening() {
        let m = model()
        m.setQuery("integrations")
        XCTAssertNil(m.activate(FindRowKey(kind: .setting, id: SettingsSection.integrations.rawValue)))
        XCTAssertNotNil(m.hint)
        m.setQuery("integration")
        XCTAssertNil(m.hint, "the next keystroke clears it")
    }

    func testAnAskedBeforeRowShowsTheCachedAnswerInAskMode() throws {
        var inputs = FindFixtures.inputs()
        inputs.askHistory = [AskHistoryEntry(question: "where does alpha run", askedAt: Date(),
                                             answer: AskResponse(answer: "On the example host.", confidence: 0.8))]
        let m = model(inputs)
        m.ask.history = inputs.askHistory
        m.setQuery("where does")
        let key = try XCTUnwrap(m.results.groups[.askedBefore]?.first?.key)
        XCTAssertNil(m.activate(key))
        XCTAssertEqual(m.mode, .ask)
        XCTAssertEqual(m.ask.answer?.answer, "On the example host.")
        XCTAssertEqual(m.fieldText, "where does alpha run")
    }

    func testANewIndexNeverReordersWhatIsShown() {
        let m = model()
        m.setQuery("alpha")
        let before = m.results
        var more = FindFixtures.inputs()
        more.nodes.append(FindFixtures.node("alpha-2", "alpha", degree: 99))
        m.install(QuickIndex.build(more))
        XCTAssertEqual(m.results, before, "applies on the next keystroke (R-SU5)")
        m.setQuery("alpha ")
        XCTAssertEqual(m.results.topHit?.key.id, "alpha-2")
    }

    func testTheKeymap() {
        XCTAssertEqual(FindKeymap.action(key: .downArrow, modifiers: [], mode: .find), .move(.next))
        XCTAssertEqual(FindKeymap.action(key: .downArrow, modifiers: .command, mode: .find), .move(.last))
        XCTAssertEqual(FindKeymap.action(key: .upArrow, modifiers: .command, mode: .find), .move(.first))
        XCTAssertEqual(FindKeymap.action(key: .tab, modifiers: [], mode: .find), .move(.nextGroup))
        XCTAssertEqual(FindKeymap.action(key: .tab, modifiers: .shift, mode: .find), .move(.previousGroup))
        XCTAssertEqual(FindKeymap.action(key: KeyEquivalent("\u{19}"), modifiers: .shift, mode: .find), .move(.previousGroup))
        XCTAssertEqual(FindKeymap.action(key: .return, modifiers: .command, mode: .find), .askNow)
        XCTAssertEqual(FindKeymap.action(key: .return, modifiers: .option, mode: .find), .secondary)
        XCTAssertEqual(FindKeymap.action(key: .return, modifiers: [], mode: .find), .none, "plain ⏎ is onSubmit's")
        XCTAssertEqual(FindKeymap.action(key: .escape, modifiers: [], mode: .ask), .escape)
        XCTAssertEqual(FindKeymap.action(key: .downArrow, modifiers: [], mode: .ask), .none, "an answer has no list")
    }

    func testCommandKTogglesButARequestWithTextAlwaysOpens() {
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: false),
                       .open(prefill: "", mode: .find))
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: true, firstRunShowing: false), .close)
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(prefill: "alpha"), isOpen: true, firstRunShowing: false),
                       .open(prefill: "alpha", mode: .find), "a Search-all-of-memory row never closes what it asks for")
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: true), .ignore,
                       "never over the first-run sheet (§3.1)")
        XCTAssertNotEqual(PaletteRequest(), PaletteRequest(), "two ⌘K presses are two changes")
    }

    func testAConversationFindsItsSourceCard() {
        let rows = [SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, harness: "claude-code"),
                    SourceOverview(id: "chat-export:chatgpt", label: "ChatGPT export", kind: .harness,
                                   origins: ["chatgpt-export"])]
        XCTAssertEqual(ConversationSource.sourceId(harness: "claude-code", origin: nil, rows: rows), "harness:claude-code")
        XCTAssertEqual(ConversationSource.sourceId(harness: nil, origin: "chatgpt-export", rows: rows), "chat-export:chatgpt")
        XCTAssertNil(ConversationSource.sourceId(harness: "cursor", origin: nil, rows: rows), "never a guessed neighbour")
    }
}
```

`FindRoutingTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 — the router hand-offs the palette stages. Each is read-then-clear,
/// like `consumeAddSource`, so an `onAppear` and an `onChange` that both see
/// one hand-off can never consume it twice.
@MainActor
final class FindRoutingTests: XCTestCase {
    func testAPaletteRequestIsReadThenCleared() {
        let router = AppRouter()
        router.requestPalette(prefill: "alpha")
        XCTAssertEqual(router.consumePalette()?.prefill, "alpha")
        XCTAssertNil(router.consumePalette())
    }

    func testInboxClustersAndConversationHandOffsAreReadThenCleared() {
        let router = AppRouter()
        router.pendingInboxItem = "inbox-001"
        router.pendingClustersEntity = "alpha-project"
        router.pendingConversationQuery = "planning notes"
        XCTAssertEqual(router.consumeInboxItem(), "inbox-001")
        XCTAssertNil(router.consumeInboxItem())
        XCTAssertEqual(router.consumeClustersEntity(), "alpha-project")
        XCTAssertNil(router.consumeClustersEntity())
        XCTAssertEqual(router.consumeConversationQuery(), "planning notes")
        XCTAssertNil(router.consumeConversationQuery())
    }

    func test_findPalette_sourceRowsStageTheSourcesTabAndTheCard() {
        let router = AppRouter()
        router.routeToSourceDetail("harness:claude-code")
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertEqual(router.consumeSourceDetail(), "harness:claude-code")
        XCTAssertNil(router.consumeSourceDetail())
    }
}
```

`HiddenShortcutLintTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 A6 / plan R-SU9 — ⌘K and ⌘F are menu commands in one file. A hidden
/// zero-size button with either shortcut is how ⌘F used to fire on the
/// graph's invisible field from another tab (the graph stays mounted), and a
/// behaviour test cannot see a literal arrive in a diff.
final class HiddenShortcutLintTests: XCTestCase {
    static let home = "Support/FindCommands.swift"
    static let needles = [#".keyboardShortcut("k""#, #".keyboardShortcut("f""#]

    func testFindShortcutsLiveOnlyInTheMenuCommands() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.hasSuffix(Self.home) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "⌘K/⌘F belong to FindCommands (G136 A6)")
    }

    func testTheHomeFileDeclaresBoth() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(Self.home) })
        let text = try String(contentsOf: file, encoding: .utf8)
        for needle in Self.needles { XCTAssertTrue(text.contains(needle), "\(needle) — the lint would pass vacuously") }
    }
}
```

Edits to existing tests: `MutationTests.swift:314-318` — the comment and assertion become
`XCTAssertEqual(Set(api.calls), Set(SyncDomain.allCases).subtracting([.askHistory, .quickRecents]), …)`
with the comment extended by "`.quickRecents` (G136) is the palette's cache-only twin of it". In
`CicadaMotionTests.swift:23-25` add `CicadaMotion.paletteInDuration, CicadaMotion.paletteOutDuration,
CicadaMotion.groupExpandDuration` to `durations`.

Run: `swift test --filter "FindPaletteTests|FindRoutingTests|HiddenShortcutLintTests" 2>&1 | tail -20`
→ compile failure. That is the red.

- [ ] **Step 2: Implement.**

**`Sync/Snapshot.swift`** — after `case askHistory` (`:41`):

```swift
    /// G136 — the ⌘K palette's recents: `(kind, id)` pairs only, per bank
    /// (plan R-SU6). Cache-only like `.askHistory`: nothing to GET, no ETag, no
    /// version-vector mapping; `Store.refresh` skips both.
    case quickRecents
```

**`Sync/Store.swift:283-285`** — the skip covers both:

```swift
            case .askHistory, .quickRecents:
                pendingDomains.remove(domain)
                continue
```

**`Theme/CicadaMotion.swift`** — after `morphDuration` (and add the three functions after `morph`):

```swift
    /// G136 — the ⌘K palette arriving (`snappy`, with a 0.98 → 1 scale) and
    /// leaving (fade), and a group's "Show all" (round-3 design §1.1).
    static let paletteInDuration: TimeInterval = 0.16
    static let paletteOutDuration: TimeInterval = 0.12
    static let groupExpandDuration: TimeInterval = 0.2
```

```swift
    static func paletteIn(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: paletteInDuration) }
    static func paletteOut(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeOut(duration: paletteOutDuration) }
    static func groupExpand(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: groupExpandDuration) }
```

**`Support/AppRouter.swift`.** *Track Z seam, block 1* (skip if Step 0 found it) — immediately after
`var pendingFirstRun = false`:

```swift
    /// Track Z §7.1 — a Sleep spine's "Open in Sources ›". The source id rides
    /// with the tab switch, like the Feed hand-off, and `SourcesPageView`
    /// consumes it once it is on screen.
    var pendingSourceDetail: String?
```

*Track Z seam, block 2* — immediately after `routeToFeedAddSource(_:)`'s closing brace and its blank line:

```swift
    /// Sets both fields together, for the same reason `routeToFeedAddSource`
    /// does: a staged source with no tab switch would never be consumed.
    func routeToSourceDetail(_ sourceID: String) {
        pendingTab = .sources
        pendingSourceDetail = sourceID
        activateMainWindow()
    }

```

*Track Z seam, block 3* — at the end of the class, after `consumeAddSource()`:

```swift

    /// Read-then-clear, for the same double-firing reason as `consumeAddSource`
    /// (`SourcesPageView.onAppear` and its `onChange` can both see one hand-off).
    @discardableResult
    func consumeSourceDetail() -> String? {
        defer { pendingSourceDetail = nil }
        return pendingSourceDetail
    }
```

*This track's own block* — between `requestFirstRun()`'s closing brace and `consumeAddSource`'s doc
comment (a position Track Z does not touch, so neither merge conflicts):

```swift
    // MARK: G136 — the find palette's hand-offs

    /// ⌘K (from any window, through `FindCommands`) and every "Search all of
    /// memory for …" row stage a request; `ContentView` opens or closes the
    /// palette (round-3 design §1.4). The request carries a nonce, so two ⌘K
    /// presses are two changes.
    var pendingPalette: PaletteRequest?
    /// A palette inbox row lands on its card, expanded (design §3.3).
    var pendingInboxItem: String?
    /// A palette entity row's ⌥⏎ opens it in Clusters (design §3.3).
    var pendingClustersEntity: String?
    /// Until the Reader lands (R-SU18), a conversation row opens its source's
    /// conversations filtered to its title; `HarnessConversationsView` reads this.
    var pendingConversationQuery: String?

    func requestPalette(prefill: String = "", mode: FindMode = .find) {
        pendingPalette = PaletteRequest(prefill: prefill, mode: mode)
        activateMainWindow()
    }

    @discardableResult
    func consumePalette() -> PaletteRequest? {
        defer { pendingPalette = nil }
        return pendingPalette
    }

    @discardableResult
    func consumeInboxItem() -> String? {
        defer { pendingInboxItem = nil }
        return pendingInboxItem
    }

    @discardableResult
    func consumeClustersEntity() -> String? {
        defer { pendingClustersEntity = nil }
        return pendingClustersEntity
    }

    @discardableResult
    func consumeConversationQuery() -> String? {
        defer { pendingConversationQuery = nil }
        return pendingConversationQuery
    }
```

**`Support/FindCommands.swift`**:

```swift
import SwiftUI

/// ⌘K and ⌘F as menu commands (G136; round-3 design §1.4, ruling A6; plan
/// R-SU9). Both used to be hidden zero-size buttons (`ContentView`), and the
/// ⌘F one lived on the graph's field — which stays mounted under every other
/// tab — so ⌘F on the Feed focused a field nobody could see. A menu item is
/// discoverable, reachable through the accessibility tree, and disabled when
/// no page offers a field. `HiddenShortcutLintTests` keeps both shortcuts in
/// this file.
struct FindCommands: Commands {
    let router: AppRouter
    @FocusedValue(\.pageFind) private var pageFind

    var body: some Commands {
        CommandGroup(after: .textEditing) {
            Button("Find in Memory…") { Task { @MainActor in router.requestPalette() } }
                .keyboardShortcut("k", modifiers: .command)
            Button("Find on This Page…") { pageFind?.focus() }
                .keyboardShortcut("f", modifiers: .command)
                .disabled(pageFind == nil)
        }
    }
}

/// What a page publishes to take ⌘F: focus its own search field.
struct PageFindAction {
    let focus: () -> Void
    func callAsFunction() { focus() }
}

struct PageFindKey: FocusedValueKey {
    typealias Value = PageFindAction
}

extension FocusedValues {
    /// The classic key form rather than `@Entry`, so a macOS 14 SDK still builds.
    var pageFind: PageFindAction? {
        get { self[PageFindKey.self] }
        set { self[PageFindKey.self] = newValue }
    }
}

private struct PageFindPublisher: ViewModifier {
    let enabled: Bool
    let focus: () -> Void

    /// Only the visible page publishes (R-SU10): two publishers in one scene
    /// leave SwiftUI to pick either, and a hidden one could shadow the page
    /// you are looking at.
    @ViewBuilder
    func body(content: Content) -> some View {
        if enabled {
            content.focusedSceneValue(\.pageFind, PageFindAction(focus: focus))
        } else {
            content
        }
    }
}

extension View {
    func publishesPageFind(enabled: Bool = true, focus: @escaping () -> Void) -> some View {
        modifier(PageFindPublisher(enabled: enabled, focus: focus))
    }
}

/// A request to open the palette; the nonce makes every ⌘K a change `onChange` sees.
struct PaletteRequest: Equatable {
    var prefill: String = ""
    var mode: FindMode = .find
    var nonce = UUID()
}

/// Design §3.4: ⌘K opens the palette and, when it is open, closes it. A request
/// that carries text or asks for Ask always opens — a "Search all of memory
/// for …" row must never close what it asks for. Never over the first-run
/// sheet (§3.1).
enum PaletteToggle {
    enum Outcome: Equatable {
        case open(prefill: String, mode: FindMode)
        case close
        case ignore
    }

    static func outcome(for request: PaletteRequest, isOpen: Bool, firstRunShowing: Bool) -> Outcome {
        if firstRunShowing { return .ignore }
        let plain = request.prefill.isEmpty && request.mode == .find
        if isOpen && plain { return .close }
        return .open(prefill: request.prefill, mode: request.mode)
    }
}
```

**`Search/FindKeymap.swift`**:

```swift
import SwiftUI

enum FindKeyAction: Equatable {
    case move(FindStep)
    case secondary
    case askNow
    case escape
    case none
}

/// The palette's keys (design §3.4; R-SU11) as one pure map, so every
/// binding is tested. Plain ⏎ is `.none` on purpose: it stays on the field's
/// `onSubmit`, the path `GraphSearchField` proved; everything else arrives
/// through ONE `.onKeyPress` handler.
enum FindKeymap {
    /// What a Shift-Tab keypress can report as its key (backtab).
    static let backtab = KeyEquivalent("\u{19}")

    static func action(key: KeyEquivalent, modifiers: EventModifiers, mode: FindMode) -> FindKeyAction {
        if key == .escape { return .escape }
        guard mode == .find else { return .none }   // Ask shows an answer, not a list
        switch key {
        case .downArrow: return modifiers.contains(.command) ? .move(.last) : .move(.next)
        case .upArrow: return modifiers.contains(.command) ? .move(.first) : .move(.previous)
        case .tab: return modifiers.contains(.shift) ? .move(.previousGroup) : .move(.nextGroup)
        case backtab: return .move(.previousGroup)
        case .return:
            if modifiers.contains(.command) { return .askNow }
            if modifiers.contains(.option) { return .secondary }
            return .none
        default: return .none
        }
    }
}
```

**`Search/ConversationSource.swift`**:

```swift
import Foundation

/// Which Sources card a conversation belongs to (R-SU18's fallback): its
/// harness's card (`harness:<name>`), else the card whose origins include the
/// episode's origin (a chat export). `nil` when neither is listed — the caller
/// shows the grid rather than a guessed neighbour.
enum ConversationSource {
    static func sourceId(harness: String?, origin: String?, rows: [SourceOverview]) -> String? {
        if let harness, !harness.isEmpty, let row = rows.first(where: { $0.harness == harness }) { return row.id }
        if let origin, !origin.isEmpty, let row = rows.first(where: { $0.origins.contains(origin) }) { return row.id }
        return nil
    }
}
```

**`Search/FindPaletteModel.swift`**:

```swift
import Foundation
import Observation

/// The ⌘K palette's state (G136; round-3 design §3; decision 18: a find
/// palette with Ask as a mode). The views render it; everything a key does is
/// a method here, so the keyboard map is tested without a window.
///
/// One `AskViewModel` lives here for the life of the app (R-SU7): the Ask
/// mode hosts today's answer body, and its per-bank history doubles as the
/// "Asked before" group.
@Observable
@MainActor
final class FindPaletteModel {
    private(set) var query = ""
    private(set) var mode: FindMode = .find
    private(set) var results = FindResults.empty
    private(set) var selection: FindRowKey?
    private(set) var expanded: Set<FindGroupID> = []
    /// One line under the rows — why ⏎ did not open Settings (R-SU12). The next keystroke clears it.
    private(set) var hint: String?
    /// True while the overlay is up: page fields stop claiming ⌘F (R-SU9).
    private(set) var isPresented = false
    let ask: AskViewModel

    @ObservationIgnored private(set) var index = QuickIndex.empty
    @ObservationIgnored private(set) var recents: [FindRowKey] = []
    @ObservationIgnored private var loadedBank: String?
    @ObservationIgnored private let store: Store

    init(store: Store) {
        self.store = store
        self.ask = AskViewModel(store: store)
    }

    var sections: [FindSection] { results.sections(expanded: expanded) }

    /// The field shows the search in Find and the question in Ask.
    var fieldText: String { mode == .ask ? ask.question : query }

    // MARK: Typing

    func setFieldText(_ text: String) {
        if mode == .ask { ask.question = text } else { setQuery(text) }
    }

    func setQuery(_ text: String) {
        query = text
        hint = nil
        expanded = []
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        results = trimmed.isEmpty ? index.emptyState(recents: recents)
                                  : FindMerge.fresh(query: text, local: index.query(trimmed))
        selection = FindSelection.initial(sections)
    }

    /// Find ↔ Ask keeps the text (design §3.1).
    func setMode(_ newMode: FindMode) {
        guard newMode != mode else { return }
        if newMode == .ask {
            ask.question = query
            mode = .ask
        } else {
            mode = .find
            setQuery(ask.question)
        }
    }

    // MARK: The index

    /// R-SU5 — a new index never reorders rows on screen; it applies on the
    /// next keystroke, or at once when nothing is typed or nothing is shown.
    func install(_ newIndex: QuickIndex) {
        index = newIndex
        if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || results.rowCount == 0 {
            setQuery(query)
        }
    }

    /// Builds the instant tier off the main actor from the Store's snapshots;
    /// a bank switch reloads that bank's recents and Ask history first.
    func rebuildIndex() async {
        if loadedBank != store.bank {
            loadedBank = store.bank
            await ask.loadHistory()
            recents = await store.cache.load(.quickRecents, bank: store.bank, as: [FindRowKey].self)?.value ?? []
        }
        let inputs = QuickIndexInputs.from(store, askHistory: ask.history)
        let built = await Task.detached(priority: .userInitiated) { QuickIndex.build(inputs) }.value
        // `.task(id:)` cancels this pass when an input moves again, but a
        // detached build runs to its end regardless: an older, slower build
        // (a bank switch mid-build) must never land over the newer one.
        guard !Task.isCancelled else { return }
        install(built)
    }

    // MARK: Presenting

    func present(prefill: String = "", mode newMode: FindMode = .find) {
        isPresented = true
        mode = .find
        setQuery(prefill)
        if newMode == .ask { setMode(.ask) }
    }

    func dismissed() {
        isPresented = false
        mode = .find
        setQuery("")
    }

    // MARK: Keys

    func move(_ step: FindStep) { selection = FindSelection.move(selection, step, in: sections) }
    func select(_ key: FindRowKey) { selection = key }

    /// Esc (design §3.4): Ask → Find with the text kept, then clear, then close. `true` = close.
    func escape() -> Bool {
        if mode == .ask { setMode(.find); return false }
        if !query.isEmpty { setQuery(""); return false }
        return true
    }

    /// ⌘⏎ — ask the current text (design §3.1). Spends: never call from a test.
    func askNow() {
        let text = fieldText.trimmingCharacters(in: .whitespacesAndNewlines)
        setMode(.ask)
        guard !text.isEmpty else { return }
        ask.question = text
        Task { await ask.ask() }
    }

    /// ⏎ — in Ask it asks; in Find it opens the selected row.
    func submit() -> FindDestination? {
        if mode == .ask { askNow(); return nil }
        guard let selection else { return nil }
        return activate(selection)
    }

    /// A row's primary (or ⌥ secondary) action. What the palette owns —
    /// asking, an asked-before answer, the Settings hint — happens here and
    /// returns nil; what navigates comes back for the host to run, and is
    /// remembered as a recent (R-SU6).
    func activate(_ key: FindRowKey, secondary: Bool = false) -> FindDestination? {
        guard let row = results.row(for: key) else { return nil }
        selection = key
        guard let destination = secondary ? row.secondary : row.destination else { return nil }
        switch destination {
        case .ask(let text):
            setMode(.ask)
            ask.question = text
            Task { await ask.ask() }
            return nil
        case .askedBefore(let question):
            setMode(.ask)
            ask.question = question
            if let entry = ask.history.first(where: { $0.question == question }) { ask.select(entry) }
            return nil
        case .settings:
            hint = "Click Open to see this in Settings."
            return nil
        default:
            remember(row.key)
            return destination
        }
    }

    func toggleExpanded(_ group: FindGroupID) {
        if expanded.contains(group) { expanded.remove(group) } else { expanded.insert(group) }
    }

    private func remember(_ key: FindRowKey) {
        let next = FindRecents.push(key, into: recents)
        guard next != recents else { return }
        recents = next
        let bank = store.bank
        let cache = store.cache
        Task { await cache.save(next, etag: nil, domain: .quickRecents, bank: bank) }
    }

    // MARK: What the footer and VoiceOver say

    var footerText: String {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard mode == .find, !trimmed.isEmpty else { return "" }
        let n = results.rowCount, g = results.groupCount
        guard n > 0 else { return "Nothing matches “\(trimmed)”." }
        return "\(UsageFormat.count(n)) \(n == 1 ? "result" : "results") in \(g) \(g == 1 ? "group" : "groups")"
    }

    var selectionAnnouncement: String? {
        let rows = FindSelection.flat(sections)
        guard let selection, let position = rows.firstIndex(where: { $0.key == selection }),
              let row = results.row(for: selection) else { return nil }
        return FindRowText.announcement(row, position: position + 1, of: rows.count)
    }
}
```

**`Views/Find/FindRowView.swift`**:

```swift
import SwiftUI

/// One palette row (design §3.3): mark, title with the matched runs bold,
/// type capsule, one detail line, a quoted passage for a conversation, a date
/// on the right and — on the selected row — what ⏎ and ⌥⏎ will do. A
/// superseded belief reads as history (R-SU19). Rows are content: fills, never glass.
struct FindRowView: View {
    let row: FindRow
    let selected: Bool
    @State private var hovered = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            FindMarkView(mark: row.mark)
            VStack(alignment: .leading, spacing: 2) {
                titleLine
                if let detail = row.detail {
                    Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
                if let snippet = row.snippet { snippetLine(snippet) }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if let trailing = row.trailing {
                Text(trailing).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if case .settings(let section) = row.destination {
                SettingsSectionLink(section: section, label: "Open")
            }
            if selected { hints }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
            .fill(selected || hovered ? CicadaTheme.surfaceHover : Color.clear))
        .contentShape(Rectangle())
        .onHover { hovered = $0 }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(FindRowText.accessibilityLabel(row))
        .accessibilityHint(FindRowText.primaryVerb(row.destination))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    private var titleLine: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            if row.history != nil {
                Text("Was").font(CicadaTheme.font(size: 10, weight: .semibold)).foregroundStyle(CicadaTheme.textTertiary)
            }
            Text(ExcerptText.attributed(row.title, bold: row.titleRanges))
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(row.history == nil ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .lineLimit(1)
            if let badge = row.badge {
                Text(badge)
                    .font(CicadaTheme.font(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingXS)
                    .background(Capsule().fill(CicadaTheme.surfaceHover))
            }
            if let history = row.history {
                Text(history).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func snippetLine(_ snippet: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
            if let speaker = row.speaker {
                Text(speaker).font(CicadaTheme.font(size: 10, weight: .semibold)).foregroundStyle(CicadaTheme.textSecondary)
            }
            Text(ExcerptText.attributed(snippet, bold: row.snippetRanges))
                .font(CicadaTheme.quoteFont(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
        }
    }

    private var hints: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("⏎ \(FindRowText.primaryVerb(row.destination))")
            if let verb = FindRowText.secondaryVerb(row.secondary) { Text("⌥⏎ \(verb)") }
        }
        .font(CicadaTheme.font(size: 10, design: .monospaced))
        .foregroundStyle(CicadaTheme.textTertiary)
        .accessibilityHidden(true)
    }
}

/// A row's mark: the entity's own logo, a service's real mark, or a symbol.
struct FindMarkView: View {
    let mark: FindMark

    var body: some View {
        switch mark {
        case .entity(let id, let name, let type):
            LogoImage(entityId: id, name: name, type: type, size: CicadaTheme.scaled(20))
        case .origin(let origin):
            OriginMark(origin: origin, size: CicadaTheme.scaled(20))
        case .symbol(let name):
            Image(systemName: name)
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(20), height: CicadaTheme.scaled(20))
        }
    }
}
```

**`Views/Find/FindPanelBody.swift`**:

```swift
import SwiftUI

/// The palette's body — field, Find/Ask switch, and the grouped rows or the
/// Ask answer (G136; round-3 design §3). Exposed on its own so the upcoming
/// Home page (Track I, decision 12) hosts the same search field in-page; the
/// overlay chrome is `FindPalette`'s. `open` runs what a row navigates to —
/// the host owns the tabs, the sheets and the router.
struct FindPanelBody: View {
    enum Placement { case palette, page }

    let model: FindPaletteModel
    var placement: Placement = .palette
    let open: (FindDestination) -> Void
    var close: () -> Void = {}

    @FocusState private var fieldFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            field
            Divider().background(CicadaTheme.border)
            Group {
                if model.mode == .ask {
                    AskPanel(onSelectEntity: { run(.entity(id: $0)) }, hostedViewModel: model.ask)
                } else {
                    rows
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(CicadaTheme.surface)   // R-SU17: opaque content, no glass on glass
            footer
        }
        .onExitCommand { if model.escape() { close() } }
        .defaultFocus($fieldFocused, true)
        .task { fieldFocused = true }
    }

    private var field: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: model.mode == .find ? "magnifyingglass" : "sparkle.magnifyingglass")
                .font(CicadaTheme.font(size: 15))
                .foregroundStyle(CicadaTheme.accent)
                .accessibilityHidden(true)
            TextField(model.mode == .find ? "Search your memory" : "Ask your memory",
                      text: Binding(get: { model.fieldText }, set: { model.setFieldText($0) }))
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 15))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($fieldFocused)
                .onSubmit { if let destination = model.submit() { run(destination) } }
                .onKeyPress(phases: .down) { press in
                    handle(FindKeymap.action(key: press.key, modifiers: press.modifiers, mode: model.mode))
                }
                .accessibilityLabel(model.mode == .find ? "Search your memory" : "Ask your memory")
            if model.mode == .ask, model.ask.isAsking { ProgressView().controlSize(.small) }
            Picker("Find or ask", selection: Binding(get: { model.mode }, set: { newMode in
                withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) { model.setMode(newMode) }
            })) {
                Text("Find").tag(FindMode.find)
                Text("Ask").tag(FindMode.ask)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            if placement == .palette {
                Button(action: close) {
                    Image(systemName: "xmark.circle.fill")
                        .font(CicadaTheme.font(size: 14))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel("Close")
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    private var rows: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    if model.results.rowCount == 0 { emptyMessage }
                    ForEach(model.sections) { section in
                        if section.group != .ask { header(section) }
                        ForEach(section.rows) { row in
                            FindRowView(row: row, selected: row.key == model.selection)
                                .id(row.key)
                                .onTapGesture { if let destination = model.activate(row.key) { run(destination) } }
                                .contextMenu { menu(for: row) }
                        }
                        if let more = section.more { moreRow(section.group, more) }
                    }
                    if let hint = model.hint {
                        Text(hint).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                            .padding(.horizontal, CicadaTheme.spacingMD)
                    }
                }
                .padding(CicadaTheme.spacingSM)
            }
            .onChange(of: model.selection) { _, key in
                guard let key else { return }
                proxy.scrollTo(key)
                if let text = model.selectionAnnouncement { AccessibilityNotification.Announcement(text).post() }
            }
        }
    }

    private var emptyMessage: some View {
        let trimmed = model.query.trimmingCharacters(in: .whitespacesAndNewlines)
        return Text(trimmed.isEmpty
                    ? "Type to find anything Cicada remembers — people, projects, conversations, saved links."
                    : "Nothing matches “\(trimmed)”.")
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingMD)
    }

    private func header(_ section: FindSection) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: section.group.glyph)
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .iconHover()
            Text(section.group.title.uppercased())
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .tracking(1.2)
            Spacer()
            if let count = section.headerCount {
                Text(count).font(CicadaTheme.font(size: 10, design: .monospaced))
            }
        }
        .foregroundStyle(CicadaTheme.textTertiary)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.top, CicadaTheme.spacingSM)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private func moreRow(_ group: FindGroupID, _ more: FindCount) -> some View {
        Button {
            withAnimation(CicadaMotion.groupExpand(reduceMotion: reduceMotion)) { model.toggleExpanded(group) }
        } label: {
            Text(FindRowText.moreLabel(more)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.accent)
        }
        .buttonStyle(.cicadaPlain)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .accessibilityLabel("\(FindRowText.moreLabel(more)) in \(group.title)")
    }

    @ViewBuilder
    private func menu(for row: FindRow) -> some View {
        Button(FindRowText.primaryVerb(row.destination)) {
            if let destination = model.activate(row.key) { run(destination) }
        }
        if let verb = FindRowText.secondaryVerb(row.secondary) {
            Button(verb) { if let destination = model.activate(row.key, secondary: true) { run(destination) } }
        }
    }

    private var footer: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(model.footerText)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityAddTraits(.updatesFrequently)
            Spacer()
            Text(model.mode == .find ? "↑↓ move · ⏎ open · ⌥⏎ more · ⌘⏎ ask · esc close"
                                     : "⏎ ask · esc back to find")
                .font(CicadaTheme.font(size: 10, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
        }
        .padding(.horizontal, CicadaTheme.spacingLG)
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    private func handle(_ action: FindKeyAction) -> KeyPress.Result {
        switch action {
        case .none: return .ignored
        case .move(let step): model.move(step)
        case .secondary:
            if let key = model.selection, let destination = model.activate(key, secondary: true) { run(destination) }
        case .askNow: model.askNow()
        case .escape: if model.escape() { close() }
        }
        return .handled
    }

    private func run(_ destination: FindDestination) {
        open(destination)
        if placement == .palette { close() }
    }
}
```

**`Views/Find/FindPalette.swift`**:

```swift
import SwiftUI

/// The ⌘K palette's chrome (round-3 design §3.1): an overlay on
/// `ContentView`'s root — not a sheet, which is modal to the title bar and
/// cannot be glass (A11) — 640 pt wide, its top at 14 % of the window,
/// Liquid Glass (`.control` = `Glass.regular`) around an opaque body (R-SU17),
/// over a light click-outside scrim.
struct FindPalette: View {
    let model: FindPaletteModel
    let open: (FindDestination) -> Void
    let close: () -> Void

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                Color.black.opacity(0.12)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture(perform: close)
                    .accessibilityHidden(true)
                FindPanelBody(model: model, placement: .palette, open: open, close: close)
                    .frame(width: min(CicadaTheme.scaled(640), geo.size.width - CicadaTheme.spacingXL * 2),
                           height: min(CicadaTheme.scaled(560), geo.size.height * 0.72))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))
                    .liquidGlass(.control, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))
                    .shadow(color: .black.opacity(0.25), radius: 24, y: 10)
                    .padding(.top, geo.size.height * 0.14)
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("Find in memory")
                    .accessibilityAddTraits(.isModal)
            }
            .frame(maxWidth: .infinity)
        }
    }
}
```

**`Ask/AskPanel.swift`** — three edits, all above `// MARK: - Answer` (R-SU7). Replace `:12-18`:

```swift
    /// Called when a citation chip (or a history row with a cached answer)
    /// is tapped — the host switches to the Graph tab and closes itself.
    var onSelectEntity: (String) -> Void
    /// G136 (round-3 design §3.5, A11) — the ⌘K palette hosts this body in Ask
    /// mode. When set, the palette owns the question field and the view model,
    /// so this view draws the answer only: no header, no sheet size. `nil`
    /// keeps the standalone panel exactly as it was. Nothing below
    /// `// MARK: - Answer` changes — Track P edits that body in parallel.
    var hostedViewModel: AskViewModel? = nil

    @State private var ownViewModel: AskViewModel?
    private var vm: AskViewModel? { hostedViewModel ?? ownViewModel }
    @FocusState private var questionFocused: Bool
```

In `body`, wrap `header` + its `Divider` in `if hostedViewModel == nil { … }`; replace
`.frame(width: 560, height: 460)` with
`.frame(width: hostedViewModel == nil ? 560 : nil, height: hostedViewModel == nil ? 460 : nil)`; and
replace the `.task { … }` with:

```swift
        .task {
            // Hosted: the palette made the view model, loaded its history and
            // owns the field's focus.
            guard hostedViewModel == nil else { return }
            if ownViewModel == nil {
                let newVM = AskViewModel(store: store)
                ownViewModel = newVM
                await newVM.loadHistory()
            }
            questionFocused = true
        }
```

(`header`'s `set: { vm?.question = $0 }` still compiles: `vm` is a class reference.)

**`CicadaApp.swift`** — a `@State private var findModel: FindPaletteModel` beside the other view
models, created in `init()` after `_usageVM` as `_findModel = State(initialValue: FindPaletteModel(store: store))`;
`.environment(findModel)` added to the `WindowGroup`'s `ContentView()` chain (after `.environment(store)`);
and `FindCommands(router: appRouter)` added inside the existing `.commands { … }` block, after the
`CommandGroup(after: .sidebar)`.

**`ContentView.swift`.**
1. Replace `:22-23` (`// ⌘K Ask panel …` + `showAskPanel`) with:

```swift
    /// G136 — the ⌘K find palette (Find, with Ask as a mode; round-3 design
    /// §3). An overlay on this root, not a sheet (A11).
    @State private var paletteOpen = false
    /// A palette saved-item row previews the item in place (design §3.3).
    @State private var previewItem: MediaFeedItem?
    /// "Switch to light/dark" writes the key `CicadaApp` already observes.
    @AppStorage(ThemeStore.defaultsKey) private var colorSchemeRaw = AppColorScheme.dark.rawValue
    @Environment(FindPaletteModel.self) private var find
    /// "Switch to <bank>" makes `BankSwitcher`'s own call (R-SU13).
    @Environment(BanksViewModel.self) private var banksVM
```

2. Replace the hidden ⌘K `.background { … }` block (`:96-105`) with:

```swift
        // G136 — ⌘K is a menu command (`FindCommands`, A6) that stages a
        // request on the router, so it works from the Settings window too.
        .overlay {
            if paletteOpen {
                FindPalette(model: find, open: openFind, close: closePalette)
                    .transition(.opacity.combined(with: .scale(scale: 0.98, anchor: .top)))
            }
        }
        .onChange(of: router.pendingPalette) { _, _ in consumePaletteRequest() }
        // R-SU5 — the instant tier is rebuilt off the main actor whenever an
        // input moves, open or not, so the first ⌘K never waits on a build.
        .background { FindIndexTask() }
```

   and, at the end of `ContentView.swift` (a file-private view, so the snapshots the token reads —
   graph, feed, inbox, Sleep's status, the theme — re-evaluate it and not `ContentView`'s body; *Critic*):

```swift
/// R-SU5 — keeps the palette's instant tier current. Its own view, so the
/// inputs it watches (the graph, the inbox, Sleep's status, the theme) move
/// this empty view when they change, never `ContentView`'s whole body.
private struct FindIndexTask: View {
    @Environment(Store.self) private var store
    @Environment(FindPaletteModel.self) private var find

    var body: some View {
        Color.clear
            .frame(width: 0, height: 0)
            .accessibilityHidden(true)
            .task(id: QuickIndexInputs.token(store, askHistoryCount: find.ask.history.count)) {
                await find.rebuildIndex()
            }
    }
}
```

3. Replace the Ask `.sheet(isPresented: $showAskPanel) { … }` (`:124-135`) with:

```swift
        .sheet(item: $previewItem) { item in
            FeedItemPreviewSheet(item: item)
        }
```

4. `:195` → `GraphContainerView(selectedTab: $selectedTab)`.
5. Add these methods to `ContentView` (after `evaluateFirstRun()`):

```swift
    private func consumePaletteRequest() {
        guard let request = router.consumePalette() else { return }
        switch PaletteToggle.outcome(for: request, isOpen: paletteOpen, firstRunShowing: showFirstRun) {
        case .open(let prefill, let mode):
            find.present(prefill: prefill, mode: mode)
            withAnimation(CicadaMotion.paletteIn(reduceMotion: reduceMotion)) { paletteOpen = true }
        case .close:
            closePalette()
        case .ignore:
            break
        }
    }

    private func closePalette() {
        withAnimation(CicadaMotion.paletteOut(reduceMotion: reduceMotion)) { paletteOpen = false }
        find.dismissed()
    }

    /// The one place a palette row becomes navigation (design §3.3). The
    /// palette has already closed itself; `.ask`, `.askedBefore` and
    /// `.settings` never arrive here (`FindPaletteModel.activate`).
    private func openFind(_ destination: FindDestination) {
        switch destination {
        case .entity(let id), .belief(let id, _):
            // Seam (Track P): a belief should also open the card on
            // Perspectives, scrolled to the claim — the card is Track P's.
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .graph }
            graphVM.revealEntity(id: id)
        case .entityInClusters(let id):
            router.pendingClustersEntity = id
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .clusters }
        case .feedItem(let id):
            if let item = store.sources.value?.first(where: { $0.mediaEntityId == id }) {
                previewItem = item
            } else {
                openFind(.entity(id: id))
            }
        case .openURL(let raw):
            if let url = URL(string: raw) { NSWorkspace.shared.open(url) }
        case .source(let id):
            router.routeToSourceDetail(id)
        case .conversations(let harness, let origin, let query):
            if let id = ConversationSource.sourceId(harness: harness, origin: origin,
                                                    rows: store.sourcesOverview.value ?? []) {
                router.pendingConversationQuery = query
                router.routeToSourceDetail(id)
            } else {
                withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .sources }
            }
        case .conversation(let target):
            // Seam (R-SU18 → Track P, P6): the Reader opens `target.span` here
            // once `ProvenanceRouter` lands; until then its own source lists it,
            // filtered to its title.
            openFind(.conversations(harness: target.harness, origin: target.origin, query: target.title))
        case .evidence:
            // Produced only when `FindReaderSeam.isAvailable` (R-SU18).
            break
        case .inbox(let id):
            router.pendingInboxItem = id
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .inbox }
        case .tab(let tab):
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = tab }
        case .action(let action):
            run(action)
        case .bank(let name):
            // `BankSwitcher.switchTo`'s own pair (R-SU13).
            Task { if await banksVM.activate(name) { await graphVM.loadGraph() } }
        case .settings, .ask, .askedBefore:
            break
        }
    }

    /// R-SU13 — the same calls the owning pages make.
    private func run(_ action: PaletteAction) {
        switch action {
        // `SleepControlRow`'s own call: trigger, then refresh what it changed.
        case .consolidate: Task { await sleepVM.triggerManually(); await store.refresh([.status, .channels]) }
        case .stopConsolidating: Task { await sleepVM.cancel() }
        case .zoomIn: CicadaTheme.zoomIn()
        case .zoomOut: CicadaTheme.zoomOut()
        case .actualSize: CicadaTheme.resetZoom()
        case .lightMode: colorSchemeRaw = AppColorScheme.light.rawValue
        case .darkMode: colorSchemeRaw = AppColorScheme.dark.rawValue
        }
    }
```

6. `GraphContainerView`: delete `@Binding var showAskPanel: Bool`; `AskButton(showAskPanel: $showAskPanel)`
   → `SearchButton()`; `GraphSearchField()` → `GraphSearchField(isActive: selectedTab == .graph)`.
7. Replace the `AskButton` struct (`:506-533`) with:

```swift
// MARK: - Search Button (G136)

/// The graph's visible twin of ⌘K (design §3.1: "`AskButton` … is renamed
/// Search and opens Find"). Ask is one keystroke away inside (⌘⏎).
struct SearchButton: View {
    @Environment(AppRouter.self) private var router
    @State private var isHovered = false

    var body: some View {
        Button { router.requestPalette() } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "magnifyingglass")
                    .font(CicadaTheme.font(size: 12))
                    .iconHover(hovering: isHovered)
                Text("Search")
                    .font(CicadaTheme.font(size: 12, weight: .medium))
            }
            .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.accent)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
        }
        .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .onHover { isHovered = $0 }
        .help("Search your memory (⌘K)")
        .accessibilityLabel("Search your memory")
    }
}
```

8. `GraphSearchField` (`:561`): add `var isActive = true` and
   `@Environment(FindPaletteModel.self) private var find: FindPaletteModel?`; delete the hidden ⌘F
   `.background( Button("") … )` (`:596-602`) and put in its place
   `.publishesPageFind(enabled: isActive && !(find?.isPresented ?? false)) { focused = true }`. (Task 5
   replaces this field; this keeps ⌘F working and the lint green in between.)

**`Views/Feed/FeedView.swift`** — `:440` `private struct FeedItemPreviewSheet` → `struct FeedItemPreviewSheet`
(the palette previews a saved item in place), and the `:58` comment's "GraphContainerView's AskButton"
becomes "GraphContainerView's SearchButton".

**`Views/Sources/SourcesPageView.swift`** — *Track Z seam, block 4* (skip if Step 0 found it): after
`@Environment(Store.self) private var store` add `@Environment(AppRouter.self) private var router`;
after `.background(CicadaTheme.background)` in `body` add:

```swift
        // Track Z §7.1 — a Sleep spine's "Open in Sources ›" lands here with
        // the tab switch; `onAppear` covers arriving from another tab and
        // `onChange` a hand-off made while this page is already showing.
        .onAppear { openPendingSource() }
        .onChange(of: router.pendingSourceDetail) { _, _ in openPendingSource() }
```

and after `body`'s closing brace:

```swift
    /// Track Z §7.1 — land on the source a Sleep spine named. A source id that
    /// no longer resolves (the overview changed underneath) leaves the grid
    /// showing rather than guessing a neighbour.
    private func openPendingSource() {
        guard let id = router.consumeSourceDetail(), let source = rows.first(where: { $0.id == id }) else { return }
        route = .detail(source)
    }
```

*This track's own edit, always (Critic, R-SU18)* — in `body`'s `case .detail(let source):` give the
detail view its source's identity, so a hand-off from one open source to another rebuilds it
instead of keeping the first source's `HarnessConversationsView` state (its `@State` view model and
`loadedOnce`) under the second source's header:

```swift
            case .detail(let source):
                SourceDetailView(source: source, onBack: { route = .grid }, onSelectEntity: onSelectEntity)
                    .id(source.id)
```

**`Views/Sources/HarnessConversationsView.swift`** — add `@Environment(AppRouter.self) private var router`
and, on the outer `VStack` after `.padding(.horizontal, CicadaTheme.spacingXL)`:

```swift
        // G136 R-SU18 — a palette conversation row, until the Reader lands,
        // opens this list filtered to its title.
        .onAppear { if let q = router.consumeConversationQuery() { query = q } }
        .onChange(of: router.pendingConversationQuery) { _, _ in
            if let q = router.consumeConversationQuery() { query = q }
        }
```

**`Views/Inbox/InboxCardView.swift`** — after `let item: InboxItem` add
`/// G136 — a palette inbox row opens its card expanded (design §3.3).` + `var startsExpanded = false`;
on the outer `VStack` add
`.onAppear { if startsExpanded { isExpanded = true } }` and
`.onChange(of: startsExpanded) { _, now in if now { isExpanded = true } }`.

**`Views/Inbox/InboxListView.swift`** — add `@Environment(AppRouter.self) private var router` and
`@State private var focusedItem: String?`; wrap the `ScrollView` of the populated branch in
`ScrollViewReader { proxy in … }`, pass `startsExpanded: item.id == focusedItem` to `InboxCardView`
(its call becomes `InboxCardView(item: item, startsExpanded: item.id == focusedItem) { resolution in … }`),
give each card `.id(item.id)`, and on the `ScrollView` add:

```swift
                    // G136 — a palette inbox row lands here: every kind shown,
                    // the card scrolled to and opened.
                    .onAppear { land(proxy) }
                    .onChange(of: router.pendingInboxItem) { _, _ in land(proxy) }
```

with, in the view:

```swift
    private func land(_ proxy: ScrollViewProxy) {
        guard let id = router.consumeInboxItem() else { return }
        kindFilter = nil
        focusedItem = id
        withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { proxy.scrollTo(id, anchor: .top) }
    }
```

**`Views/Topics/TopicsView.swift`** — in `TopicsView` add `@Environment(AppRouter.self) private var router`,
and on the outer `ZStack`:

```swift
        // G136 — a palette entity row's ⌥⏎ opens it here.
        .onAppear { openPendingEntity() }
        .onChange(of: router.pendingClustersEntity) { _, _ in openPendingEntity() }
```

with:

```swift
    private func openPendingEntity() {
        guard let id = router.consumeClustersEntity(),
              let entity = graphVM.entities.first(where: { $0.id == id }) else { return }
        withAnimation(CicadaMotion.panel(reduceMotion: reduceMotion)) { selectedEntity = entity }
    }
```

- [ ] **Step 3: Green.** `swift test --filter "FindPaletteTests|FindRoutingTests|HiddenShortcutLintTests|MutationTests|CicadaMotionTests|MotionLiteralLintTests|LiquidGlassLintTests|FontLiteralLintTests"`
  → pass; then `swift build 2>&1 | tail -5` and the full `swift test 2>&1 | tail -20` → 0 failures.
  `grep -rn "showAskPanel\|AskButton(" app/CicadaApp/Sources` → nothing.
  `git diff dev -- app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift` → every hunk is above
  `// MARK: - Answer`.
- [ ] **Step 4: Commit** — stage every file listed under **Files** by name:
  `feat(app): ⌘K is a find palette with Ask as a mode; ⌘K/⌘F are menu commands (G136 S3/S4, A4/A6/A11)`.

---
### Task 4: The server tier — conversations, beliefs and history, appended without moving a row (S4; R-SU14, R-SU15, R-SU18, R-SU19)

**Files:**
- Create: `…/Search/MemorySearch.swift`, `…/Search/FindServerRows.swift`
- Modify: `…/Services/APIClient.swift` (add `searchMemory` beside `search(q:topK:)` at `:1875`),
  `…/Search/FindPaletteModel.swift`, `…/Views/Find/FindPanelBody.swift`, `FindPaletteTests.swift` (helper only)
- Test: `FindServerTests.swift` (new)

**Interfaces:**
- Produces `MemorySearchHit`, `MemorySearchResponse`, `FindSearchAPI` (+ `APIClient` conformance and
  `APIClient.searchMemory(_:kinds:mode:perKind:)`), `FindSleeper` + `FindSleepers.real`,
  `FindServerPhase` (+ `isUnreachable(_:)`), `FindServerRows.kinds/group(forKind:)/kind(for:)/Context/rows/totals/speaker`,
  `FindDates.parse/short`; on the model `serverPhase`, `indexState`, `serverTask`, `expandTask`,
  `runPass`, `searchDeeper`, `offersSearchDeeper`, `serverNote`, and `init(store:api:sleeper:)`.
- Consumes the wire exactly as `api/models/schemas.py:1005-1070` declares it (verified in "What the
  code actually does today").

- [ ] **Step 0: Is the Reader on `dev`?** `cd <worktree> && git merge --no-edit dev && grep -rn "final class ProvenanceRouter\|struct ReaderTarget" app/CicadaApp/Sources`.
  (*Critic:* the earlier `enum ReaderTarget` grep could never hit — Track P ships `ReaderTarget` as a
  struct; see "Branches that touch the same files".)
  - **Not found** (the expected case today — Track P is unmerged): do Steps 1–3 as written;
    `FindReaderSeam.isAvailable` stays `false` and `ContentView.openFind`'s two seam comments stay
    (R-SU18).
  - **Found**: read both declarations. If they still have the shape Track P had at `bbc7943`
    (`ReaderTarget(episode:focus:subjectId:knownTitle:knownHarness:)`, `Focus.span(start:end:hash:derived:)`
    and `.none`, `ProvenanceRouter.open(_:)`), *also*: (a) set `FindReaderSeam.isAvailable = true`;
    (b) create `…/Search/FindReaderRoute.swift`:

    ```swift
    import Foundation

    /// R-SU18 — a palette hit's span → where the Reader opens (Track P's
    /// `ReaderTarget`). A whole span lands on its words; anything less opens
    /// the document at the top — never a guessed offset. A hit's span is never
    /// `derived`: `/search` ships stored spans and passage offsets only.
    enum FindReaderRoute {
        static func target(for span: ReaderSpan, title: String? = nil, harness: String? = nil) -> ReaderTarget {
            let focus: ReaderTarget.Focus
            if let start = span.start, let end = span.end, start >= 0, end > start {
                focus = .span(start: start, end: end, hash: span.hash, derived: false)
            } else {
                focus = .none
            }
            return ReaderTarget(episode: span.doc, focus: focus, knownTitle: title, knownHarness: harness)
        }
    }
    ```

    with this test in `FindServerTests`:

    ```swift
        func testASpanLandsOnItsWordsAndAnythingLessOpensAtTheTop() {
            let exact = FindReaderRoute.target(for: ReaderSpan(doc: "ep_1", start: 120, end: 180, hash: "abcdef123456", claimId: nil))
            XCTAssertEqual(exact.episode, "ep_1")
            XCTAssertEqual(exact.focus, ReaderTarget.Focus.span(start: 120, end: 180, hash: "abcdef123456", derived: false))
            let bare = FindReaderRoute.target(for: ReaderSpan(doc: "ep_2", start: nil, end: nil, hash: nil, claimId: nil))
            XCTAssertEqual(bare.focus, ReaderTarget.Focus.none)
        }
    ```

    (c) in `ContentView` add `@Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?`
    (optional, as Track P's own chips read it) and replace the `.conversation` / `.evidence` cases of
    `openFind` with:

    ```swift
            case .conversation(let target):
                if let provenance {
                    provenance.open(FindReaderRoute.target(for: target.span, title: target.title, harness: target.harness))
                } else {
                    openFind(.conversations(harness: target.harness, origin: target.origin, query: target.title))
                }
            case .evidence(let span):
                provenance?.open(FindReaderRoute.target(for: span))
    ```

    (the `.conversations` fallback case stays — it is still ⌥⏎ on a conversation row). If the
    declarations have moved on from that shape, map field for field and say so in the task report.

- [ ] **Step 1: Failing tests** — `FindServerTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// A `FindSearchAPI` that never touches a network. Every call is recorded.
final class FakeFindSearch: FindSearchAPI, @unchecked Sendable {
    struct Call: Equatable { let query: String; let mode: String; let kinds: [String]; let perKind: Int }
    var calls: [Call] = []
    var response = MemorySearchResponse()
    var error: Error?

    func searchMemory(_ query: String, kinds: [String], mode: String, perKind: Int) async throws -> MemorySearchResponse {
        calls.append(Call(query: query, mode: mode, kinds: kinds, perKind: perKind))
        if let error { throw error }
        return response
    }

    static func decode(_ json: String) -> MemorySearchResponse {
        try! JSONDecoder().decode(MemorySearchResponse.self, from: Data(json.utf8))
    }
}

/// G136 S4 — the wire, hits → rows, the counts, and the debounced passes.
final class FindServerTests: XCTestCase {
    /// "The wire" (`2026-09-23-search-backend.md`), one hit per kind plus a
    /// second passage of one conversation and a superseded claim.
    static let wire = """
    {"results": [
      {"id": "alpha-project", "name": "alpha-project", "type": "project", "status": "active", "confidence": 0.8,
       "score": 4, "snippet": "", "kind": "entity", "subtitle": "alpha", "snippetOffsets": [], "matchedField": "alias"},
      {"id": "ep_2026-09-03_001", "name": "Planning notes", "type": "episode", "status": "active", "confidence": 0,
       "score": 3, "snippet": "we moved the index to sqlite-vec", "kind": "episode", "snippetOffsets": [[22, 32]],
       "matchedField": "body", "episodeId": "ep_2026-09-03_001", "conversationId": "ses_a", "harness": "claude-code",
       "timestamp": "2026-09-03T10:00:00+00:00", "start": 120, "end": 180, "hash": "abcdef123456", "evidenceKind": "user"},
      {"id": "ep_2026-09-03_002", "name": "Planning notes", "type": "episode", "status": "active", "confidence": 0,
       "score": 2, "snippet": "sqlite-vec again", "kind": "episode", "snippetOffsets": [[0, 10]], "matchedField": "body",
       "episodeId": "ep_2026-09-03_002", "conversationId": "ses_a", "harness": "claude-code"},
      {"id": "clm_1", "name": "alpha-project uses sqlite-vec", "type": "project", "status": "active", "confidence": 0.7,
       "score": 2, "snippet": "alpha-project uses sqlite-vec", "kind": "claim", "subtitle": "alpha-project",
       "subjectId": "alpha-project", "episodeId": "ep_2026-09-03_001", "start": 120, "end": 150,
       "hash": "abcdef123456", "evidenceKind": "user"},
      {"id": "clm_0", "name": "alpha-project uses FAISS", "type": "project", "status": "active", "confidence": 0.4,
       "score": 1, "snippet": "", "kind": "claim", "subtitle": "alpha-project", "subjectId": "alpha-project",
       "validTo": "2026-09-03", "supersededBy": "clm_1"},
      {"id": "media-alpha", "name": "Alpha paper notes", "type": "media", "status": "active", "confidence": 0.5,
       "score": 1, "snippet": "", "kind": "media", "subtitle": "Ada Example, Bob Example", "timestamp": "2025-01-02"},
      {"id": "inbox-001", "name": "Still tracking alpha-project?", "type": "decay", "status": "active",
       "confidence": 0, "score": 1, "snippet": "", "kind": "inbox", "subjectId": "alpha-project"}
    ],
    "totals": {"entity": 1, "episode": 2, "claim": 2, "media": 1}, "mode": "prefix", "indexState": "ready"}
    """

    private var context: FindServerRows.Context {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        var context = FindServerRows.Context()
        context.now = ISO8601DateFormatter().date(from: "2026-09-23T12:00:00Z")!
        context.locale = Locale(identifier: "en_GB")
        context.calendar = calendar
        context.mediaURL = { $0 == "media-alpha" ? "https://example.com/alpha" : nil }
        context.readerAvailable = false
        return context
    }

    func testTheWireDecodesAndAnOldBackendStillDecodes() {
        let response = FakeFindSearch.decode(Self.wire)
        XCTAssertEqual(response.results.count, 7)
        XCTAssertEqual(response.totals["episode"], 2)
        XCTAssertEqual(response.results[1].snippetOffsets, [[22, 32]])
        XCTAssertEqual(response.results[4].validTo, "2026-09-03")
        let old = FakeFindSearch.decode(#"{"results": [{"id": "a", "name": "A", "type": "concept", "status": "active", "confidence": 0.5, "score": 1, "snippet": ""}]}"#)
        XCTAssertEqual(old.results.first?.kind, "entity", "pre-G136 rows were all entities")
        XCTAssertEqual(old.totals, [:])
        XCTAssertEqual(old.indexState, "ready")
    }

    func testHitsBecomeRowsGroupedByConversationWithHistoryAndSpeakers() {
        let rows = FindServerRows.rows(FakeFindSearch.decode(Self.wire), query: "sqlite", context: context)
        XCTAssertEqual(rows.map(\.group), [.entities, .conversations, .beliefs, .beliefs, .sources], "inbox is the local tier's")
        XCTAssertEqual(rows[0].detail, "Also called alpha")
        let conversation = rows[1]
        XCTAssertEqual(conversation.key, FindRowKey(kind: .conversation, id: "ses_a"))
        XCTAssertEqual(conversation.detail, "2 matches")
        XCTAssertEqual(conversation.speaker, "You said")
        XCTAssertEqual(conversation.trailing, "3 Sep")
        XCTAssertEqual(conversation.mark, .origin("claude-code"))
        XCTAssertEqual(conversation.snippetRanges, [[22, 32]])
        XCTAssertEqual(conversation.secondary, .conversations(harness: "claude-code", origin: nil, query: nil))
        guard case .conversation(let target) = conversation.destination else { return XCTFail("a conversation opens a conversation") }
        XCTAssertEqual(target.span, ReaderSpan(doc: "ep_2026-09-03_001", start: 120, end: 180, hash: "abcdef123456", claimId: nil))
        XCTAssertEqual(rows[2].detail, "alpha-project · You said")
        XCTAssertNil(rows[2].history)
        XCTAssertNil(rows[2].secondary, "R-SU18: no Reader, no 'where it was said'")
        XCTAssertEqual(rows[3].history, "until 3 Sep", "R-SU19: a superseded belief is history")
        XCTAssertEqual(rows[4].trailing, "2 Jan 2025")
        XCTAssertEqual(rows[4].secondary, .openURL("https://example.com/alpha"))
    }

    func testTotalsAreHonest() {
        let response = FakeFindSearch.decode(Self.wire)
        let rows = FindServerRows.rows(response, query: "sqlite", context: context)
        let totals = FindServerRows.totals(response, rows: rows, kinds: FindServerRows.kinds, perKind: 5)
        XCTAssertEqual(totals[.entities], .exact(1))
        XCTAssertEqual(totals[.beliefs], .exact(2))
        XCTAssertEqual(totals[.conversations], .atLeast, "two episodes merged into one row: not a row count")
        let semantic = FakeFindSearch.decode(#"{"results": [{"id": "a", "name": "A", "type": "concept", "status": "active", "confidence": 0.5, "score": 1, "snippet": "", "kind": "entity", "matchedField": "semantic"}], "totals": {"entity": 0}, "mode": "hybrid"}"#)
        XCTAssertEqual(FindServerRows.totals(semantic, rows: [], kinds: ["entity"], perKind: 5)[.entities], .atLeast)
        let capped = MemorySearchResponse(results: Array(repeating: response.results[0], count: 5))
        XCTAssertEqual(FindServerRows.totals(capped, rows: [], kinds: ["entity"], perKind: 5)[.entities], .atLeast)
    }

    func testDatesSpeakTheReadersLocaleAndOnlyNameAnotherYear() {
        let c = context
        XCTAssertEqual(FindDates.short("2026-09-03T10:00:00+00:00", now: c.now, locale: c.locale, calendar: c.calendar), "3 Sep")
        XCTAssertEqual(FindDates.short("2026-09-03T10:00:00.123Z", now: c.now, locale: c.locale, calendar: c.calendar), "3 Sep")
        XCTAssertEqual(FindDates.short("2025-01-02", now: c.now, locale: c.locale, calendar: c.calendar), "2 Jan 2025")
        XCTAssertEqual(FindDates.short("2026-09-03", now: c.now, locale: Locale(identifier: "en_US"), calendar: c.calendar), "Sep 3")
        XCTAssertNil(FindDates.short(nil, now: c.now, locale: c.locale, calendar: c.calendar))
        XCTAssertNil(FindDates.short("soon", now: c.now, locale: c.locale, calendar: c.calendar))
    }

    func testOnlyARealConnectionFailureReadsAsUnreachable() {
        XCTAssertTrue(FindServerPhase.isUnreachable(APIError.serverUnreachable))
        XCTAssertTrue(FindServerPhase.isUnreachable(URLError(.cannotConnectToHost)))
        XCTAssertFalse(FindServerPhase.isUnreachable(URLError(.cancelled)))
        XCTAssertFalse(FindServerPhase.isUnreachable(APIError.httpError(500, "")))
    }

    func testTheClientAsksForTheFourKindsAndEncodesTheQuery() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/search")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("q=sqlite%20vec%26more"), query)
            XCTAssertTrue(query.contains("kinds=entity,claim,episode,media"), query)
            XCTAssertTrue(query.contains("mode=prefix"), query)
            XCTAssertTrue(query.contains("per_kind=5"), query)
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"results": [], "totals": {}, "mode": "prefix", "indexState": "ready"}"#.utf8))
        }
        let result = try await APIClient(session: MockURLProtocol.makeSession())
            .searchMemory("sqlite vec&more", kinds: FindServerRows.kinds, mode: "prefix", perKind: 5)
        XCTAssertEqual(result.indexState, "ready")
    }
}

/// The debounced passes against a fake (design §3.10 `PaletteDebounceTests`).
/// The sleeper only checks cancellation, so a cancelled pass never calls out.
@MainActor
final class PaletteServerTierTests: XCTestCase {
    private func model(_ api: FakeFindSearch) -> FindPaletteModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let model = FindPaletteModel(store: store, api: api, sleeper: { _ in try Task.checkCancellation() })
        model.install(QuickIndex.build(FindFixtures.inputs()))
        return model
    }

    func testUnderTwoCharactersNothingIsAsked() async {
        let api = FakeFindSearch()
        let m = model(api)
        m.setQuery("a")
        await m.serverTask?.value
        XCTAssertTrue(api.calls.isEmpty)
        XCTAssertEqual(m.serverPhase, .idle)
    }

    func testAKeystrokeCancelsThePassInFlight() async {
        let api = FakeFindSearch()
        let m = model(api)
        m.setQuery("al")
        m.setQuery("alp")
        await m.serverTask?.value
        XCTAssertEqual(api.calls.map(\.query), ["alp", "alp"])
        XCTAssertEqual(api.calls.map(\.mode), ["prefix", "hybrid"])
        XCTAssertEqual(api.calls.first?.kinds, FindServerRows.kinds)
        XCTAssertEqual(api.calls.first?.perKind, SearchTiming.perKind)
    }

    func testServerRowsAppendBelowAndNothingShownMoves() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(FindServerTests.wire)
        let m = model(api)
        m.setQuery("alpha")
        let top = m.results.topHit?.key
        let selected = m.selection
        await m.serverTask?.value
        XCTAssertEqual(m.results.topHit?.key, top)
        XCTAssertEqual(m.selection, selected)
        XCTAssertNil(m.results.groups[.entities], "the server's alpha-project is the local top hit: not repeated")
        XCTAssertEqual(m.results.groups[.conversations]?.count, 1)
        XCTAssertEqual(m.results.groups[.beliefs]?.count, 2)
        XCTAssertEqual(m.results.groups[.sources]?.map(\.key.id), ["media-alpha"], "local media-alpha is not repeated")
        XCTAssertEqual(m.serverPhase, .done)
    }

    func testAnOldBackendHidesConversationsAndBeliefs() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(#"{"results": [{"id": "bob-example", "name": "bob-example", "type": "person", "status": "active", "confidence": 0.5, "score": 1, "snippet": ""}]}"#)
        let m = model(api)
        m.setQuery("alpha")
        await m.serverTask?.value
        XCTAssertNil(m.results.groups[.conversations])
        XCTAssertNil(m.results.groups[.beliefs])
        XCTAssertEqual(m.results.groups[.entities]?.map(\.key.id), ["bob-example"])
    }

    func testAnUnreachableBackendKeepsTheLocalRowsAndSaysSo() async {
        let api = FakeFindSearch()
        api.error = URLError(.cannotConnectToHost)
        let m = model(api)
        m.setQuery("alpha")
        await m.serverTask?.value
        XCTAssertEqual(m.serverPhase, .unreachable)
        XCTAssertEqual(m.results.topHit?.key.id, "alpha-project")
        XCTAssertTrue(m.footerText.contains("isn't answering"))
    }

    func testShowAllReasksOneKindAtTheServersCap() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(FindServerTests.wire)
        let m = model(api)
        m.setQuery("alpha")
        await m.serverTask?.value
        m.toggleExpanded(.conversations)
        await m.expandTask?.value
        XCTAssertEqual(api.calls.last, FakeFindSearch.Call(query: "alpha", mode: "prefix", kinds: ["episode"],
                                                           perKind: SearchTiming.expandedPerKind))
    }

    func testSearchDeeperRunsTheHybridPassNow() async {
        let api = FakeFindSearch()
        let m = model(api)
        m.setQuery("zeta")
        await m.serverTask?.value
        XCTAssertTrue(m.offersSearchDeeper, "nothing matched")
        api.calls = []
        m.searchDeeper()
        await m.serverTask?.value
        XCTAssertEqual(api.calls.map(\.mode), ["hybrid"])
    }
}
```

And in `FindPaletteTests.swift`'s `model(_:)` helper, construct the model with
`FindPaletteModel(store: store, api: FakeFindSearch(), sleeper: { _ in try Task.checkCancellation() })`
— from this task on, no test builds a palette that could reach `APIClient.shared`.

Run: `swift test --filter "FindServerTests|PaletteServerTierTests" 2>&1 | tail -20` → compile failure.

- [ ] **Step 2: Implement.** `Search/MemorySearch.swift`:

```swift
import Foundation

/// One `GET /search` row (G136 server half, PR #74; `api/models/schemas.py`
/// `SearchHit`, verified field by field). Decode-tolerant: a pre-G136 backend
/// sends the old seven fields and no `kind` — every row was an entity — and
/// that must never blank the palette (R10).
struct MemorySearchHit: Decodable, Equatable, Sendable {
    let id: String
    let name: String
    let type: String
    let status: String
    let score: Double
    let snippet: String
    let kind: String
    let subtitle: String?
    let snippetOffsets: [[Int]]
    let matchedField: String?
    let subjectId: String?
    let episodeId: String?
    let conversationId: String?
    let harness: String?
    let origin: String?
    let timestamp: String?
    let start: Int?
    let end: Int?
    let hash: String?
    let evidenceKind: String?
    let validFrom: String?
    let validTo: String?
    let supersededBy: String?

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, score, snippet, kind, subtitle, snippetOffsets, matchedField, subjectId
        case episodeId, conversationId, harness, origin, timestamp, start, end, hash, evidenceKind
        case validFrom, validTo, supersededBy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? "concept"
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "active"
        score = try c.decodeIfPresent(Double.self, forKey: .score) ?? 0
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "entity"
        subtitle = try c.decodeIfPresent(String.self, forKey: .subtitle)
        snippetOffsets = (try? c.decodeIfPresent([[Int]].self, forKey: .snippetOffsets)) ?? []
        matchedField = try c.decodeIfPresent(String.self, forKey: .matchedField)
        subjectId = try c.decodeIfPresent(String.self, forKey: .subjectId)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        hash = try c.decodeIfPresent(String.self, forKey: .hash)
        evidenceKind = try c.decodeIfPresent(String.self, forKey: .evidenceKind)
        validFrom = try c.decodeIfPresent(String.self, forKey: .validFrom)
        validTo = try c.decodeIfPresent(String.self, forKey: .validTo)
        supersededBy = try c.decodeIfPresent(String.self, forKey: .supersededBy)
    }
}

/// `totals` are exact LEXICAL counts per kind (G136 R11); `indexState`
/// `building | unavailable` means claims and conversations are empty on
/// purpose, and the palette hides those groups rather than showing them empty.
struct MemorySearchResponse: Decodable, Equatable, Sendable {
    let results: [MemorySearchHit]
    let totals: [String: Int]
    let mode: String
    let indexState: String

    enum CodingKeys: String, CodingKey { case results, totals, mode, indexState }

    init(results: [MemorySearchHit] = [], totals: [String: Int] = [:], mode: String = "prefix", indexState: String = "ready") {
        self.results = results
        self.totals = totals
        self.mode = mode
        self.indexState = indexState
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        results = try c.decodeIfPresent([MemorySearchHit].self, forKey: .results) ?? []
        totals = (try? c.decodeIfPresent([String: Int].self, forKey: .totals)) ?? [:]
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "hybrid"
        indexState = try c.decodeIfPresent(String.self, forKey: .indexState) ?? "ready"
    }
}

/// The palette's one network dependency, injected so the passes are tested
/// with a fake (design §3.10) and no test can reach the live backend.
protocol FindSearchAPI: Sendable {
    func searchMemory(_ query: String, kinds: [String], mode: String, perKind: Int) async throws -> MemorySearchResponse
}

extension APIClient: FindSearchAPI {}

/// The debounce clock, injected (the `SyncEngine` pattern).
typealias FindSleeper = @Sendable (Duration) async throws -> Void

enum FindSleepers {
    static let real: FindSleeper = { try await Task.sleep(for: $0) }
}

enum FindServerPhase: Equatable, Sendable {
    case idle, searching, done, unreachable

    /// A backend that is not answering — as opposed to a cancelled request
    /// (the next keystroke) or an error reply (an old backend, a 422), which
    /// leave the local rows standing without a banner.
    static func isUnreachable(_ error: Error) -> Bool {
        if let api = error as? APIError, case .serverUnreachable = api { return true }
        if let url = error as? URLError { return url.code != .cancelled }
        return false
    }
}
```

`Services/APIClient.swift` — beside `search(q:topK:)` (`:1875`):

```swift
    /// G136 — the ⌘K palette's server tier (`GET /search`, "The wire" in the
    /// search-backend plan). `mode=prefix` is FTS only and never embeds;
    /// `hybrid` adds the stored vectors. The query is percent-encoded the way
    /// `fetchRecentConversations` encodes its filters, and it goes nowhere
    /// else — no log, no cache, no telemetry (design §3.8).
    func searchMemory(_ query: String, kinds: [String], mode: String, perKind: Int) async throws -> MemorySearchResponse {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        let q = query.addingPercentEncoding(withAllowedCharacters: allowed) ?? query
        return try await get("/search?q=\(q)&kinds=\(kinds.joined(separator: ","))&mode=\(mode)&per_kind=\(perKind)")
    }
```

`Search/FindServerRows.swift`:

```swift
import Foundation

/// Server hits → palette rows (G136 S4; round-3 design §3.3). Pure.
enum FindServerRows {
    /// R-SU14 — Pass A's and Pass B's kinds; `inbox` is the local tier's already.
    static let kinds = ["entity", "claim", "episode", "media"]

    static func group(forKind kind: String) -> FindGroupID? {
        switch kind {
        case "entity": .entities
        case "episode": .conversations
        case "claim": .beliefs
        case "media": .sources
        default: nil
        }
    }

    static func kind(for group: FindGroupID) -> String? {
        kinds.first { self.group(forKind: $0) == group }
    }

    struct Context {
        var now = Date()
        var locale = Locale.autoupdatingCurrent
        var calendar = Calendar.current
        /// A saved item's URL from the Feed snapshot the app holds — a hit carries none.
        var mediaURL: (String) -> String? = { _ in nil }
        var readerAvailable = FindReaderSeam.isAvailable
    }

    static func rows(_ response: MemorySearchResponse, query: String, context: Context) -> [FindRow] {
        let tokens = QuickMatch.tokens(query)
        func bold(_ text: String) -> [[Int]] {
            QuickMatch.match(tokens, fields: [QuickMatch.Field(text, weight: QuickMatch.Weight.name)])?.ranges(inField: 0) ?? []
        }
        func date(_ iso: String?) -> String? {
            FindDates.short(iso, now: context.now, locale: context.locale, calendar: context.calendar)
        }
        var rows: [FindRow] = []
        var conversationRow: [String: Int] = [:]
        var conversationHits: [String: Int] = [:]
        for hit in response.results {
            switch hit.kind {
            case "entity":
                let type = EntityType(rawValue: hit.type) ?? .unknown
                rows.append(FindRow(key: FindRowKey(kind: .entity, id: hit.id), group: .entities, title: hit.name,
                                    titleRanges: bold(hit.name), detail: entityDetail(hit), badge: type.label,
                                    mark: .entity(id: hit.id, name: hit.name, type: type), score: hit.score,
                                    destination: .entity(id: hit.id), secondary: .entityInClusters(id: hit.id)))
            case "media":
                rows.append(FindRow(key: FindRowKey(kind: .media, id: hit.id), group: .sources, title: hit.name,
                                    titleRanges: bold(hit.name), detail: hit.subtitle, badge: "Saved",
                                    mark: .entity(id: hit.id, name: hit.name, type: .media),
                                    trailing: date(hit.timestamp), score: hit.score,
                                    destination: .feedItem(mediaEntityId: hit.id),
                                    secondary: context.mediaURL(hit.id).map { .openURL($0) }))
            case "claim":
                let subject = hit.subjectId ?? ""
                let type = EntityType(rawValue: hit.type) ?? .concept
                // R-SU19 — the server ranks these after every current claim (R10); drawn as history.
                let isHistory = hit.validTo != nil || hit.supersededBy != nil
                let span = hit.episodeId.map {
                    ReaderSpan(doc: $0, start: hit.start, end: hit.end, hash: hit.hash, claimId: hit.id)
                }
                let detail = [hit.subtitle, speaker(hit.evidenceKind)].compactMap { $0 }.joined(separator: " · ")
                rows.append(FindRow(key: FindRowKey(kind: .belief, id: hit.id), group: .beliefs, title: hit.name,
                                    titleRanges: bold(hit.name), detail: detail.isEmpty ? nil : detail,
                                    mark: .entity(id: subject, name: hit.subtitle ?? subject, type: type),
                                    history: isHistory ? (date(hit.validTo).map { "until \($0)" } ?? "no longer current") : nil,
                                    score: hit.score, destination: .belief(subjectId: subject, claimId: hit.id),
                                    secondary: context.readerAvailable ? span.map { .evidence($0) } : nil))
            case "episode":
                // One row per conversation (the wire: "the palette does that
                // grouping on conversationId"); its best passage is the first.
                let key = hit.conversationId ?? hit.episodeId ?? hit.id
                conversationHits[key, default: 0] += 1
                if let index = conversationRow[key] {
                    rows[index].detail = "\(UsageFormat.count(conversationHits[key] ?? 1)) matches"
                    continue
                }
                conversationRow[key] = rows.count
                let span = ReaderSpan(doc: hit.episodeId ?? hit.id, start: hit.start, end: hit.end,
                                      hash: hit.hash, claimId: nil)
                let target = ConversationTarget(span: span, conversationId: hit.conversationId,
                                                harness: hit.harness, origin: hit.origin, title: hit.name)
                rows.append(FindRow(key: FindRowKey(kind: .conversation, id: key), group: .conversations,
                                    title: hit.name, titleRanges: bold(hit.name),
                                    snippet: hit.snippet.isEmpty ? nil : hit.snippet, snippetRanges: hit.snippetOffsets,
                                    mark: .origin(hit.harness ?? hit.origin ?? "unknown"),
                                    trailing: date(hit.timestamp), speaker: speaker(hit.evidenceKind), score: hit.score,
                                    destination: .conversation(target),
                                    secondary: .conversations(harness: hit.harness, origin: hit.origin, query: nil)))
            default:
                continue
            }
        }
        return rows
    }

    /// R-SU15 — per group, what the header and "Show all" may claim.
    static func totals(_ response: MemorySearchResponse, rows: [FindRow], kinds: [String], perKind: Int) -> [FindGroupID: FindCount] {
        var out: [FindGroupID: FindCount] = [:]
        for kind in kinds {
            guard let group = group(forKind: kind) else { continue }
            let hits = response.results.filter { $0.kind == kind }
            let shown = rows.filter { $0.group == group }.count
            if hits.contains(where: { $0.matchedField == "semantic" }) {
                out[group] = .atLeast   // semantic neighbours are ranked, never counted (G136 R11)
            } else if let total = response.totals[kind] {
                // `totals.episode` counts episodes: once two merged into one row it is not a row count.
                out[group] = (kind == "episode" && shown < hits.count) ? .atLeast : .exact(total)
            } else {
                out[group] = hits.count >= perKind ? .atLeast : .exact(shown)
            }
        }
        return out
    }

    /// Design §4.2's labels for `evidenceKind` — the row-level twin of the
    /// chips Track P draws on the entity card.
    static func speaker(_ kind: String?) -> String? {
        switch kind ?? "" {
        case "user": "You said"
        case "assistant": "Agent replied"
        case "page": "From page"
        case "reasoning": "Inferred"
        default: nil
        }
    }

    private static func entityDetail(_ hit: MemorySearchHit) -> String? {
        switch hit.matchedField ?? "" {
        case "alias": return hit.subtitle.map { "Also called \($0)" }
        case "claim": return hit.subtitle
        default: return hit.snippet.isEmpty ? nil : hit.snippet
        }
    }
}

/// "3 Sep" this year, "2 Jan 2025" otherwise — in the reader's own order
/// ("Sep 3" in en_US). A timestamp that does not parse is no date, never a guess.
enum FindDates {
    static func parse(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: iso) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: iso) { return date }
        formatter.formatOptions = [.withFullDate]
        return formatter.date(from: String(iso.prefix(10)))
    }

    static func short(_ iso: String?, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                      calendar: Calendar = .current) -> String? {
        guard let date = parse(iso) else { return nil }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.setLocalizedDateFormatFromTemplate(sameYear ? "dMMM" : "dMMMyyyy")
        return formatter.string(from: date)
    }
}
```

`Search/FindPaletteModel.swift` — five edits.
1. Beside the other state, add:

```swift
    private(set) var serverPhase: FindServerPhase = .idle
    /// The server's `indexState` for the last pass (G136 R11).
    private(set) var indexState: String?
    @ObservationIgnored private let api: any FindSearchAPI
    @ObservationIgnored private let sleeper: FindSleeper
    /// The current text's passes, and a "Show all" re-ask — tests await them.
    @ObservationIgnored private(set) var serverTask: Task<Void, Never>?
    @ObservationIgnored private(set) var expandTask: Task<Void, Never>?
```

2. Replace `init(store:)` with:

```swift
    init(store: Store, api: any FindSearchAPI = APIClient.shared, sleeper: @escaping FindSleeper = FindSleepers.real) {
        self.store = store
        self.api = api
        self.sleeper = sleeper
        self.ask = AskViewModel(store: store)
    }
```

3. As the last line of `setQuery(_:)`: `scheduleServer(trimmed)`.
4. Replace `toggleExpanded(_:)` and `footerText` with the versions below, and add the rest:

```swift
    func toggleExpanded(_ group: FindGroupID) {
        if expanded.contains(group) { expanded.remove(group); return }
        expanded.insert(group)
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let kind = FindServerRows.kind(for: group), SearchTiming.wantsServer(q) else { return }
        expandTask?.cancel()
        expandTask = Task { [weak self] in
            await self?.runPass(q, mode: "prefix", kinds: [kind], perKind: SearchTiming.expandedPerKind)
        }
    }

    // MARK: The server tier (design §3.2 "Tier 2")

    /// Debounced and cancellable: each keystroke cancels the passes in flight;
    /// under two characters nothing is asked (R-SU2); Pass A (prefix, FTS
    /// only) after the debounce, Pass B (hybrid) once the typing has settled.
    private func scheduleServer(_ q: String) {
        serverTask?.cancel()
        expandTask?.cancel()
        indexState = nil
        guard SearchTiming.wantsServer(q) else {
            serverTask = nil
            serverPhase = .idle
            return
        }
        serverPhase = .searching
        let sleeper = self.sleeper
        serverTask = Task { [weak self] in
            do { try await sleeper(SearchTiming.serverDebounce) } catch { return }
            await self?.runPass(q, mode: "prefix")
            do { try await sleeper(SearchTiming.semanticIdle - SearchTiming.serverDebounce) } catch { return }
            await self?.runPass(q, mode: "hybrid")
        }
    }

    /// One pass, merged by the rule that never moves a shown row (design
    /// §3.2). A stale answer — cancelled, or for text that has changed — is dropped.
    func runPass(_ q: String, mode passMode: String, kinds: [String] = FindServerRows.kinds,
                 perKind: Int = SearchTiming.perKind) async {
        do {
            let response = try await api.searchMemory(q, kinds: kinds, mode: passMode, perKind: perKind)
            guard !Task.isCancelled, isCurrent(q) else { return }
            let feed = store.sources.value ?? []
            var context = FindServerRows.Context()
            context.mediaURL = { id in feed.first { $0.mediaEntityId == id }?.url }
            let rows = FindServerRows.rows(response, query: q, context: context)
            let totals = FindServerRows.totals(response, rows: rows, kinds: kinds, perKind: perKind)
            results = FindMerge.append(rows, totals: totals, to: results)
            if selection.flatMap({ results.row(for: $0) }) == nil { selection = FindSelection.initial(sections) }
            indexState = response.indexState
            serverPhase = .done
        } catch {
            guard !Task.isCancelled, isCurrent(q) else { return }
            serverPhase = FindServerPhase.isUnreachable(error) ? .unreachable : .done
        }
    }

    private func isCurrent(_ q: String) -> Bool {
        mode == .find && query.trimmingCharacters(in: .whitespacesAndNewlines) == q
    }

    /// "Search deeper" (design §3.6): the hybrid pass, now.
    func searchDeeper() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard SearchTiming.wantsServer(q) else { return }
        serverTask?.cancel()
        serverPhase = .searching
        serverTask = Task { [weak self] in await self?.runPass(q, mode: "hybrid") }
    }

    var offersSearchDeeper: Bool {
        mode == .find && serverPhase == .done && results.rowCount < 3
            && SearchTiming.wantsServer(query.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    /// Design §3.6's states, as the footer's second clause (the live region).
    var serverNote: String? {
        switch serverPhase {
        case .searching: return "Searching conversations…"
        case .unreachable: return "Conversations and beliefs need the Cicada backend. It isn't answering."
        case .done where indexState == "building" || indexState == "unavailable":
            return "Cicada is still reading your conversations — try again in a moment."
        default: return nil
        }
    }

    var footerText: String {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard mode == .find, !trimmed.isEmpty else { return "" }
        let n = results.rowCount, g = results.groupCount
        let base = n == 0 ? "Nothing matches “\(trimmed)”."
            : "\(UsageFormat.count(n)) \(n == 1 ? "result" : "results") in \(g) \(g == 1 ? "group" : "groups")"
        return [base, serverNote].compactMap { $0 }.joined(separator: " · ")
    }
```

`Views/Find/FindPanelBody.swift` — two additions. In `body`, between `field` and the `Divider`:

```swift
            // Design §3.6: a hairline while the server tier is out. Under
            // Reduce Motion there is no indeterminate bar — the footer's
            // "Searching conversations…" is its text twin.
            if model.serverPhase == .searching && !reduceMotion {
                ProgressView().progressViewStyle(.linear).controlSize(.mini).accessibilityHidden(true)
            }
```

and in `rows`, after the `ForEach(model.sections)` and before the hint:

```swift
                    if model.offersSearchDeeper {
                        Button { model.searchDeeper() } label: {
                            Label("Search deeper", systemImage: "sparkle.magnifyingglass").font(CicadaTheme.captionFont)
                        }
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .help("Also find things that mean the same, not only the same words")
                    }
```

- [ ] **Step 3: Green.** `swift test --filter "FindServerTests|PaletteServerTierTests|FindPaletteTests|PaletteMergeTests"`
  → pass; the full `swift test` → 0 failures; `swift build` clean.
- [ ] **Step 4: Commit** — stage `Search/MemorySearch.swift`, `Search/FindServerRows.swift`,
  `Search/FindPaletteModel.swift`, `Views/Find/FindPanelBody.swift`, `Services/APIClient.swift`,
  `Tests/CicadaAppTests/FindServerTests.swift`, `Tests/CicadaAppTests/FindPaletteTests.swift` (and,
  only in Step 0's "found" branch, `Search/FindReaderRoute.swift`, `Search/FindModels.swift`,
  `ContentView.swift`):
  `feat(app): the palette's server tier — conversations, beliefs and history, appended without moving a row (G136 S4)`.

---
### Task 5: One search field — Graph, Clusters and Feed on `CicadaSearchField` (S5; G123; R-SU10, R-SU17, R-SU20, R-SU21)

**Files:**
- Create: `…/Views/Common/CicadaSearchField.swift`, `…/Views/Common/SearchAllMemoryRow.swift`,
  `…/Search/ClusterSearchIndex.swift`
- Modify: `…/ContentView.swift` (`GraphSearchField`), `…/ViewModels/GraphViewModel.swift`
  (`searchHits`, `searchMatches`, `clusterSearchIndex()`), `…/Views/Topics/TopicsView.swift`,
  `…/Views/Feed/FeedView.swift`, `…/ViewModels/FeedViewModel.swift:60-68`
  (+ `…/Search/FeedSearch.swift` only in Step 0's Track F branch)
- Test: `SearchFieldsTests.swift` (new)

**Interfaces:**
- Produces `CicadaSearchField(text:prompt:style:findEnabled:width:onSubmit:onMove:onFocusChange:)`
  with `Style` (`.content`, `.overCanvas`), `EscapeAction`, `escape(textIsEmpty:)`,
  `showsFindHint(text:focused:)`; `SearchAllMemoryRow(query:)` + `title(_:)`/`trimmed(_:)`;
  `GraphViewModel.SearchHit`, `searchHits(_:limit:)`, `searchFields(_:)`, `clusterSearchIndex()`;
  `ClusterSearchIndex` (`init(_:)`, `rank(_:)`, `titleRanges(_:query:)`).
- Consumes `QuickMatch`, `FeedSearch`, `ExcerptText.attributed`, `publishesPageFind`,
  `AppRouter.requestPalette`, `FindPaletteModel.isPresented`, `LogoImage`.

- [ ] **Step 0: Is Track F's paper block on `dev`?** `cd <worktree> && git merge --no-edit dev && grep -n "let paper: PaperSummary?" app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift && grep -n "static func matches" app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift`.
  - **Found** (R-SU21): in `FeedSearch.fields(_:)` add, before `return fields`:

    ```swift
            // G133 (Track F) — a paper is found by its authors, arXiv id and DOI.
            if let paper = item.paper {
                fields += paper.authors.map { QuickMatch.Field($0, weight: QuickMatch.Weight.alias) }
                for id in [paper.arxivId, paper.doi].compactMap({ $0 }) where !id.isEmpty {
                    fields.append(QuickMatch.Field(id, weight: QuickMatch.Weight.keyword))
                }
            }
    ```

    make `FeedViewModel.matches(_:query:)`'s body the one line below (Track F's `PaperCardTests`
    then run against it unchanged — verified green by the critic):

    ```swift
        nonisolated static func matches(_ item: MediaFeedItem, query: String) -> Bool {
            FeedSearch.matches(item, query: query)
        }
    ```

    and add this case to Step 1's `SearchFieldsTests`:

    ```swift
        /// G133 (Track F) — a paper is found by its byline through the one field list.
        func testAPaperIsFoundByAuthorArxivIdAndDoi() throws {
            let json = #"{"mediaEntityId": "media-paper-alpha", "url": "https://example.com/paper", "title": "Paper Alpha", "mediaType": "bookmark", "savedAt": "2026-09-01", "tags": [], "relevance": 0.5, "kind": "paper", "paper": {"authors": ["Ada Example"], "arxivId": "2401.00001", "doi": "10.9999/abc"}}"#
            let paper = try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
            for query in ["ada", "2401.00001", "10.9999"] {
                XCTAssertTrue(FeedSearch.matches(paper, query: query), query)
            }
            XCTAssertFalse(FeedSearch.matches(paper, query: "zebra"))
        }
    ```

    *Critic:* Track F merged in PR #77, so this is the expected branch; commit `Search/FeedSearch.swift`
    with the task.
  - **Not found**: leave `FeedSearch` as Task 2 wrote it; the field list is the one seam Track F adds
    to (hand-off). Never add `paper` to `MediaFeedItem` here.

- [ ] **Step 1: Failing tests** — `SearchFieldsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 S5 — the one in-page field and what three pages search with it.
@MainActor
final class SearchFieldsTests: XCTestCase {
    private func store() -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: FakeSyncAPI())
    }

    func testEscapeClearsThenLeavesAndTheHintShowsOnlyWhenIdle() {
        XCTAssertEqual(CicadaSearchField.escape(textIsEmpty: false), .clear)
        XCTAssertEqual(CicadaSearchField.escape(textIsEmpty: true), .blur)
        XCTAssertTrue(CicadaSearchField.showsFindHint(text: "", focused: false))
        XCTAssertFalse(CicadaSearchField.showsFindHint(text: "", focused: true))
        XCTAssertFalse(CicadaSearchField.showsFindHint(text: "a", focused: false))
    }

    func testTheSearchAllRowCarriesTheWordsTrimmed() {
        XCTAssertEqual(SearchAllMemoryRow.title("  alpha "), "Search all of memory for “alpha” (⌘K)")
        XCTAssertEqual(SearchAllMemoryRow.trimmed("  alpha "), "alpha")
    }

    func testTheGraphTypeaheadFindsATagAndBoldsTheName() async throws {
        let store = store()
        let vm = GraphViewModel(store: store)
        store.graph.value = GraphResponse(nodes: [FindFixtures.node("alpha-project", "alpha-project", tags: ["robotics"], degree: 1),
                                                  FindFixtures.node("bob-example", "bob-example", type: .person)])
        store.graph.loadedAt = Date()
        let deadline = Date().addingTimeInterval(3)
        while vm.nodes.isEmpty {
            if Date() > deadline { return XCTFail("nodes never synced from the store") }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        XCTAssertEqual(vm.searchHits("robo").map(\.node.id), ["alpha-project"], "a tag is a search field now")
        XCTAssertEqual(vm.searchHits("alp").first?.ranges, [[0, 3]])
        XCTAssertEqual(vm.searchMatches("bob").map(\.id), ["bob-example"])
        XCTAssertEqual(vm.clusterSearchIndex().rank("robotics").map(\.id), ["alpha-project"])
    }

    func testClustersRankNameThenTagThenBody() {
        func entity(_ id: String, _ name: String, tags: [String] = [], body: String = "") -> Entity {
            Entity(id: id, name: name, type: .concept, status: .active, confidence: 0.5, created: "",
                   lastReferenced: "", decayRate: 0, sourceEpisodes: [], tags: tags, related: [], version: 0,
                   markdownContent: body, history: [])
        }
        let index = ClusterSearchIndex([entity("a", "Zeta notes", body: "about alpha retrieval"),
                                        entity("b", "Alpha project"), entity("c", "Omega", tags: ["alpha"])])
        XCTAssertEqual(index.rank("alpha").map(\.id), ["b", "c", "a"])
        XCTAssertEqual(ClusterSearchIndex.titleRanges("Alpha project", query: "alp"), [[0, 3]])
        XCTAssertTrue(index.rank("zzz").isEmpty)
    }

    func testTheFeedFiltersWithTheOneFieldListAndKeepsItsSort() {
        let store = store()
        let vm = FeedViewModel(store: store)
        store.sources = Snapshot(value: [FindFixtures.media("m-a", title: "First", description: "about retrieval"),
                                         FindFixtures.media("m-b", title: "Second retrieval")], loadedAt: Date())
        vm.searchText = "retrieval"
        XCTAssertEqual(vm.filteredItems.map(\.mediaEntityId), ["m-a", "m-b"], "R-SU20: the Feed's order, not a rank")
        vm.searchText = "zzz"
        XCTAssertTrue(vm.filteredItems.isEmpty)
    }
}
```

Run: `swift test --filter SearchFieldsTests 2>&1 | tail -20` → compile failure.

- [ ] **Step 2: Implement.** `Views/Common/CicadaSearchField.swift`:

```swift
import SwiftUI

/// The one in-page search field (G136 S5; round-3 design §1.3, §3.7). Graph,
/// Clusters, the Feed, a source's conversations and the Inbox all use it, so
/// the keys are learned once: Esc clears and a second Esc leaves the field;
/// ↑/↓ reach the page's result list when it has one; ⏎ submits. A 28 pt
/// capsule — magnifier, prompt, a clear button when there is text, a "⌘F"
/// hint when it is empty and idle.
///
/// ⌘F arrives through the `pageFind` menu command (A6), published only while
/// `findEnabled` — the graph's field sits under every other tab (R-SU10) —
/// and never while the ⌘K palette is up (R-SU9).
struct CicadaSearchField: View {
    enum Style {
        /// Content layer (R9 §2.7): a hover fill and a hairline, never glass.
        case content
        /// Floating over the graph, in the material its other controls use —
        /// Liquid Glass over the canvas waits on the G109 frame-time check
        /// (`LiquidGlass.swift`; plan R-SU17).
        case overCanvas
    }

    enum EscapeAction: Equatable { case clear, blur }

    @Binding var text: String
    let prompt: String
    var style: Style = .content
    var findEnabled = true
    var width: CGFloat? = nil
    var onSubmit: () -> Void = {}
    var onMove: ((Int) -> Void)? = nil
    var onFocusChange: (Bool) -> Void = { _ in }

    @FocusState private var focused: Bool
    @Environment(FindPaletteModel.self) private var palette: FindPaletteModel?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "magnifyingglass")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            TextField(prompt, text: $text)
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($focused)
                .onSubmit(onSubmit)
                .onKeyPress(.downArrow) { move(1) }
                .onKeyPress(.upArrow) { move(-1) }
                .onKeyPress(.escape) {
                    switch Self.escape(textIsEmpty: text.isEmpty) {
                    case .clear: text = ""
                    case .blur: focused = false
                    }
                    return .handled
                }
                .accessibilityLabel(prompt)
            if !text.isEmpty {
                Button { text = "" } label: {
                    Image(systemName: "xmark.circle.fill").font(CicadaTheme.font(size: 11))
                }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityLabel("Clear search")
            } else if Self.showsFindHint(text: text, focused: focused) {
                Text("⌘F")
                    .font(CicadaTheme.font(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help("Find on this page (⌘F)")
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(width: width, height: CicadaTheme.scaled(28))
        .modifier(SearchFieldChrome(style: style))
        .onChange(of: focused) { _, now in onFocusChange(now) }
        .publishesPageFind(enabled: findEnabled && !(palette?.isPresented ?? false)) { focused = true }
    }

    private func move(_ delta: Int) -> KeyPress.Result {
        guard let onMove else { return .ignored }
        onMove(delta)
        return .handled
    }

    static func escape(textIsEmpty: Bool) -> EscapeAction { textIsEmpty ? .blur : .clear }
    static func showsFindHint(text: String, focused: Bool) -> Bool { text.isEmpty && !focused }
}

private struct SearchFieldChrome: ViewModifier {
    let style: CicadaSearchField.Style

    @ViewBuilder
    func body(content: Content) -> some View {
        switch style {
        case .content:
            content
                .background(Capsule().fill(CicadaTheme.surfaceHover))
                .overlay(Capsule().stroke(CicadaTheme.border, lineWidth: 1))
        case .overCanvas:
            content.glassCard(cornerRadius: CicadaTheme.scaled(14))
        }
    }
}
```

`Views/Common/SearchAllMemoryRow.swift`:

```swift
import SwiftUI

/// Every in-page "no match" ends with this row (design §3.7): the same words,
/// searched everywhere — it opens the ⌘K palette prefilled.
struct SearchAllMemoryRow: View {
    let query: String
    @Environment(AppRouter.self) private var router

    var body: some View {
        Button { router.requestPalette(prefill: Self.trimmed(query)) } label: {
            Label(Self.title(query), systemImage: "magnifyingglass").font(CicadaTheme.captionFont)
        }
        .buttonStyle(.cicadaPlain)
        .foregroundStyle(CicadaTheme.accent)
        .help("Search all of memory (⌘K)")
    }

    static func trimmed(_ query: String) -> String { query.trimmingCharacters(in: .whitespacesAndNewlines) }
    static func title(_ query: String) -> String { "Search all of memory for “\(trimmed(query))” (⌘K)" }
}
```

`Search/ClusterSearchIndex.swift`:

```swift
import Foundation

/// Clusters' search, precomputed (G136 S5; design §3.7). The old filter
/// lowercased every entity's name, tags and summary on every keystroke
/// (`TopicsView.filteredEntities`); this folds them once per graph snapshot
/// (`GraphViewModel.clusterSearchIndex()`) and ranks through `QuickMatch`.
struct ClusterSearchIndex {
    struct Entry {
        let entity: Entity
        let fields: [QuickMatch.Field]
    }

    private(set) var entries: [Entry] = []

    init(_ entities: [Entity] = []) {
        entries = entities.map { entity in
            var fields = [QuickMatch.Field(entity.name, weight: QuickMatch.Weight.name)]
            fields += entity.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
            if !entity.markdownContent.isEmpty {
                fields.append(QuickMatch.Field(entity.markdownContent, weight: QuickMatch.Weight.body))
            }
            return Entry(entity: entity, fields: fields)
        }
    }

    /// Best first — the flat ranked list Clusters shows while searching.
    func rank(_ query: String) -> [Entity] {
        QuickMatch.rank(entries, query: query, fields: { $0.fields }, tieBreak: { _ in 0 },
                        name: { $0.entity.name.lowercased() }).map { $0.item.entity }
    }

    /// A row's bold runs in its name.
    static func titleRanges(_ name: String, query: String) -> [[Int]] {
        QuickMatch.match(QuickMatch.tokens(query), fields: [QuickMatch.Field(name, weight: 1)])?.ranges(inField: 0) ?? []
    }
}
```

`ViewModels/GraphViewModel.swift` — replace `searchMatches(_:limit:)` (`:442-446`, keep `rankNames`
from Task 1) with:

```swift
    /// A typeahead row: the node and the scalar runs to bold in its name.
    struct SearchHit {
        let node: GraphNode
        let ranges: [[Int]]
    }

    /// G123 through `QuickMatch` (G136 S5): the name, then tags — the
    /// palette's ranker, so the two never order one name differently.
    func searchHits(_ query: String, limit: Int = 8) -> [SearchHit] {
        QuickMatch.rank(nodes, query: query, limit: limit, fields: Self.searchFields,
                        tieBreak: { Double($0.degree) }, name: { $0.name.lowercased() })
            .map { SearchHit(node: $0.item, ranges: $0.match.ranges(inField: 0)) }
    }

    nonisolated static func searchFields(_ node: GraphNode) -> [QuickMatch.Field] {
        [QuickMatch.Field(node.name, weight: QuickMatch.Weight.name)]
            + node.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
    }

    func searchMatches(_ query: String, limit: Int = 8) -> [GraphNode] {
        searchHits(query, limit: limit).map(\.node)
    }

    @ObservationIgnored private var clusterSearchCache: (stamp: Date?, count: Int, index: ClusterSearchIndex)?

    /// Clusters' index (G136 S5): folded once per graph snapshot, on the first
    /// keystroke after it changed — never per keystroke, and never for a
    /// snapshot nobody searches. `entities` and `lastSyncedLoadedAt` move
    /// together in `syncFromStore`, so the pair is the snapshot's identity.
    func clusterSearchIndex() -> ClusterSearchIndex {
        if let cache = clusterSearchCache, cache.stamp == lastSyncedLoadedAt, cache.count == entities.count {
            return cache.index
        }
        let index = ClusterSearchIndex(entities)
        clusterSearchCache = (lastSyncedLoadedAt, entities.count, index)
        return index
    }
```

`ContentView.swift` — replace the whole `GraphSearchField` (Task 3's version) with:

```swift
// MARK: - Graph node search (G123, on the shared field — G136 S5)

/// A small typeahead over the graph snapshot: ⏎ zooms to the node's
/// neighbourhood and opens its card (`revealEntity`), and with nothing
/// matched it hands the words to the ⌘K palette. ⌘F lands here only while
/// the Graph tab is showing (R-SU10).
struct GraphSearchField: View {
    var isActive = true
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var router
    @State private var query = ""
    @State private var highlighted = 0
    @State private var focused = false
    @State private var hovered: String?

    private var hits: [GraphViewModel.SearchHit] { graphVM.searchHits(query) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            CicadaSearchField(text: $query, prompt: "Find a node", style: .overCanvas, findEnabled: isActive,
                              width: CicadaTheme.scaled(200), onSubmit: submit, onMove: move,
                              onFocusChange: { focused = $0 })
                .onChange(of: query) { _, _ in highlighted = 0 }
            if focused, !SearchAllMemoryRow.trimmed(query).isEmpty {
                dropdown.padding(.top, CicadaTheme.spacingXS)
            }
        }
    }

    private var dropdown: some View {
        let list = hits
        return VStack(alignment: .leading, spacing: 0) {
            if list.isEmpty {
                Text("No node matches")
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .padding(.top, CicadaTheme.spacingSM)
                SearchAllMemoryRow(query: query)
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .padding(.vertical, CicadaTheme.spacingXS)
            }
            ForEach(Array(list.enumerated()), id: \.element.node.id) { index, hit in
                HStack(spacing: CicadaTheme.spacingXS) {
                    LogoImage(entityId: hit.node.id, name: hit.node.name, type: hit.node.type, size: CicadaTheme.scaled(18))
                    Circle().fill(CicadaTheme.entityColor(for: hit.node.type))
                        .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
                    Text(ExcerptText.attributed(hit.node.name, bold: hit.ranges))
                        .font(CicadaTheme.font(size: 12))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Text(hit.node.type.label)
                        .font(CicadaTheme.font(size: 10))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.vertical, CicadaTheme.spacingXS)
                .background(index == highlighted || hovered == hit.node.id ? CicadaTheme.surfaceHover : Color.clear)
                .contentShape(Rectangle())
                .onHover { inside in hovered = inside ? hit.node.id : (hovered == hit.node.id ? nil : hovered) }
                .onTapGesture { pick(index) }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(hit.node.type.label), \(hit.node.name)")
                .accessibilityAddTraits(index == highlighted ? [.isButton, .isSelected] : .isButton)
            }
        }
        .frame(width: CicadaTheme.scaled(260))
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
    }

    private func submit() {
        if hits.isEmpty {
            router.requestPalette(prefill: SearchAllMemoryRow.trimmed(query))
        } else {
            pick(highlighted)
        }
    }

    private func move(_ delta: Int) {
        let count = hits.count
        guard count > 0 else { return }
        highlighted = (highlighted + delta + count) % count
    }

    private func pick(_ index: Int) {
        let list = hits
        guard list.indices.contains(index) else { return }
        graphVM.revealEntity(id: list[index].node.id)
        query = ""
        highlighted = 0
    }
}
```

`Views/Topics/TopicsView.swift` (`TopicsListView`):
1. In `filteredEntities` (`:89-115` at `f7dfd21`, before Task 3's edits to the file) replace everything
   after the `if searchText.isEmpty { … }` early return (from `let query = searchText.lowercased()`
   through `.map { $0.0 }`) with:

```swift
        // G136 S5 — ranked by `QuickMatch` over an index folded once per graph
        // snapshot (the old path lowercased every summary on every keystroke).
        let allowed = Set(list.map(\.id))
        return graphVM.clusterSearchIndex().rank(searchText).filter { allowed.contains($0.id) }
```

2. Replace the search sub-`HStack` of the search + filter row (magnifier, `TextField("Search clusters...")`,
   clear button, and its two paddings + `glassCard`, `:185-208` at `f7dfd21`) with
   `CicadaSearchField(text: $searchText, prompt: "Search clusters…").frame(maxWidth: CicadaTheme.scaled(360))`.
3. In the `if isSearching {` branch of the list, before its `ForEach`:

```swift
                                if filteredEntities.isEmpty {
                                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                                        Text("No entity matches “\(SearchAllMemoryRow.trimmed(searchText))”.")
                                            .font(CicadaTheme.bodyFont)
                                            .foregroundStyle(CicadaTheme.textSecondary)
                                        SearchAllMemoryRow(query: searchText)
                                    }
                                    .padding(.vertical, CicadaTheme.spacingMD)
                                }
```

   and pass `highlight: ClusterSearchIndex.titleRanges(entity.name, query: searchText)` to that branch's
   `TopicRowListItem`.
4. `TopicRowListItem` (`:640` at `f7dfd21`): add `var highlight: [[Int]] = []` between `let entity` and `let onTap`,
   and draw the name as `Text(ExcerptText.attributed(entity.name, bold: highlight))` (same modifiers).

`ViewModels/FeedViewModel.swift` — `filteredItems` (`:60-68` at `f7dfd21`; after Track F it is the
four-line version that calls `Self.matches`, which the Step 0 branch keeps as a wrapper) becomes the
block below. *Critic:* not `FeedSearch.filter(items, query:)` — that builds (and so folds) every
item's fields on every read, and a render reads `filteredItems` two or three times (R-SU21's note).

```swift
    /// G136 S5 — `FeedSearch`'s one field list (title, site, channel, origin,
    /// tags, description, url, about — and a paper's byline when Track F's
    /// block is on the wire), filtered in the Feed's own order (R-SU20).
    /// The fields are folded once per snapshot (`foldedFields`), never per
    /// keystroke: a render reads this two or three times, and re-folding every
    /// description and URL of ~1,500 saved items on each read measured ~100 ms
    /// a pass in a debug build while planning (QuickMatch's own rule).
    var filteredItems: [MediaFeedItem] {
        let tokens = QuickMatch.tokens(searchText)
        guard !tokens.isEmpty else { return items }
        let folded = foldedFields()
        return items.filter { QuickMatch.match(tokens, fields: folded[$0.id] ?? FeedSearch.fields($0)) != nil }
    }

    /// Keyed on the snapshot's change token and size — the pair
    /// `GraphViewModel.clusterSearchIndex()` uses for the same job.
    @ObservationIgnored private var searchCache: (stamp: Date?, count: Int, fields: [String: [QuickMatch.Field]])?

    private func foldedFields() -> [String: [QuickMatch.Field]] {
        let all = store.sources.value ?? []
        if let cache = searchCache, cache.stamp == store.sources.loadedAt, cache.count == all.count {
            return cache.fields
        }
        let fields = Dictionary(all.map { ($0.id, FeedSearch.fields($0)) }, uniquingKeysWith: { first, _ in first })
        searchCache = (store.sources.loadedAt, all.count, fields)
        return fields
    }
```

and in `SearchFieldsTests.testTheFeedFiltersWithTheOneFieldListAndKeepsItsSort`, after the `"zzz"`
assertion, pin that a new snapshot is never served from the old fold:

```swift
        store.sources = Snapshot(value: [FindFixtures.media("m-c", title: "Third retrieval")],
                                 loadedAt: Date().addingTimeInterval(1))
        vm.searchText = "retrieval"
        XCTAssertEqual(vm.filteredItems.map(\.mediaEntityId), ["m-c"], "a new snapshot is folded again, never served stale")
```

`Views/Feed/FeedView.swift` — in `searchAndSortRow` replace the search sub-`HStack` (magnifier,
`TextField("Search saved media...")`, clear button, paddings, `glassCard`, `:155-177` at `f7dfd21`) with
`CicadaSearchField(text: Binding(get: { viewModel.searchText }, set: { viewModel.searchText = $0 }), prompt: "Search saved media…")`;
in `content`, insert before the `else if viewModel.filteredItems.isEmpty {` branch:

```swift
        } else if viewModel.filteredItems.isEmpty, !SearchAllMemoryRow.trimmed(viewModel.searchText).isEmpty {
            // Something is saved; nothing matched — say that, not "Nothing saved yet".
            VStack(spacing: CicadaTheme.spacingSM) {
                Spacer()
                Text("Nothing saved matches “\(SearchAllMemoryRow.trimmed(viewModel.searchText))”.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                SearchAllMemoryRow(query: viewModel.searchText)
                Spacer()
            }
            .frame(maxWidth: .infinity)
```

- [ ] **Step 3: Green.** `swift test --filter "SearchFieldsTests|GraphSearchRankTests|HiddenShortcutLintTests|LiquidGlassLintTests|FontLiteralLintTests|PaperCardTests"`,
  then the full `swift test` → 0 failures; `swift build` clean.
- [ ] **Step 4: Commit** — stage the three new files, `ContentView.swift`, `ViewModels/GraphViewModel.swift`,
  `Views/Topics/TopicsView.swift`, `Views/Feed/FeedView.swift`, `ViewModels/FeedViewModel.swift`,
  `Tests/CicadaAppTests/SearchFieldsTests.swift` (and `Search/FeedSearch.swift` in the Track F branch):
  `feat(app): one search field — Graph, Clusters and Feed on CicadaSearchField (G136 S5, G123)`.

---

### Task 6: A source's conversations past the cap, and a search field on the Inbox (S5; R-SU20, R-SU22)

**Files:**
- Create: `…/Search/ConversationSearch.swift`
- Modify: `…/Models/SourceOverview.swift` (`ConversationFilter`, `:254-260` after the merge), `…/Sync/SyncAPI.swift:69-73`,
  `…/Services/APIClient.swift:1390-1417`, `…/ViewModels/ConversationsViewModel.swift`,
  `…/Views/Sources/HarnessConversationsView.swift`, `…/Views/Inbox/InboxListView.swift`,
  `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift:202-211` (`FakeSyncAPI`)
- Test: `PageSearchTests.swift` (new); `ConversationsTests.swift` (one added test);
  `SourcesPageTests.swift:85-94` must pass unchanged

**Interfaces:**
- Produces `ConversationSearch.cap/needsServer(loaded:query:)/merge(local:server:)`;
  `SyncAPI.fetchRecentConversations(limit:harness:origin:query:)`; `ConversationsViewModel.beyondCap`
  + `searchBeyondCap(query:harness:origin:)`; `FakeSyncAPI.recentQueries`.
- Consumes `QuickMatch`, `InboxSearch`, `SearchTiming`, `CicadaSearchField`, `SearchAllMemoryRow`;
  the server's `GET /conversations/recent?q=` (before the cap, G136 R17).

- [ ] **Step 1: Failing tests** — `PageSearchTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G136 S5 — a source's conversations and the Inbox, on the shared field.
@MainActor
final class PageSearchTests: XCTestCase {
    func testTheTitleFilterFoldsAndKeepsNewestFirst() {
        let rows = [ConversationSummary(conversationId: "a", title: "Zürich planning"),
                    ConversationSummary(conversationId: "b", title: "Graph physics"),
                    ConversationSummary(conversationId: "c", title: "zurich retro")]
        XCTAssertEqual(ConversationFilter.apply(rows, query: "zurich").map(\.id), ["a", "c"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "graph phys").map(\.id), ["b"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "").map(\.id), ["a", "b", "c"])
    }

    func testOnlyACappedPageWidensToTheServer() {
        XCTAssertFalse(ConversationSearch.needsServer(loaded: 199, query: "planning"))
        XCTAssertTrue(ConversationSearch.needsServer(loaded: 200, query: "planning"))
        XCTAssertFalse(ConversationSearch.needsServer(loaded: 200, query: "p"), "one character stays local")
        let local = [ConversationSummary(conversationId: "a", title: "x")]
        let server = [ConversationSummary(conversationId: "a", title: "x"), ConversationSummary(conversationId: "z", title: "x")]
        XCTAssertEqual(ConversationSearch.merge(local: local, server: server).map(\.id), ["a", "z"])
    }

    func testTheViewModelAsksTheServerOnlyPastTheCap() async {
        let api = FakeSyncAPI()
        api.recentConversations = (0..<200).map { ConversationSummary(conversationId: "c\($0)", title: "row \($0)") }
            + [ConversationSummary(conversationId: "old", title: "planning notes")]
        let vm = ConversationsViewModel(api: api)
        await vm.load(limit: ConversationSearch.cap)
        XCTAssertEqual(vm.conversations.count, 200, "the fake honours the cap like the server")
        await vm.searchBeyondCap(query: "planning")
        XCTAssertEqual(vm.beyondCap.map(\.id), ["old"])
        XCTAssertEqual(api.recentQueries.last, "planning")
        let small = FakeSyncAPI()
        small.recentConversations = [ConversationSummary(conversationId: "a", title: "planning")]
        let vm2 = ConversationsViewModel(api: small)
        await vm2.load(limit: ConversationSearch.cap)
        await vm2.searchBeyondCap(query: "planning")
        XCTAssertTrue(vm2.beyondCap.isEmpty)
        XCTAssertEqual(small.recentQueries, [nil], "below the cap the local filter already saw everything")
    }
}
```

And in `ConversationsTests.swift`, beside `testFetchRecentConversations…` (`:95-113`):

```swift
    /// G136 R-SU22 — `q` is percent-encoded and sent only when there is one
    /// (the server applies it before its cap, G136 R17).
    func testFetchRecentConversationsSendsTheTitleQuery() async throws {
        MockURLProtocol.handler = { request in
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("q=planning%20notes"), query)
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data("[]".utf8))
        }
        _ = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchRecentConversations(limit: 200, harness: nil, origin: nil, query: "planning notes")
        MockURLProtocol.handler = { request in
            XCTAssertFalse((request.url?.query ?? "").contains("q="))
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data("[]".utf8))
        }
        _ = try await APIClient(session: MockURLProtocol.makeSession()).fetchRecentConversations(limit: 20)
    }
```

Run: `swift test --filter "PageSearchTests|ConversationsTests" 2>&1 | tail -20` → compile failure.

- [ ] **Step 2: Implement.** `Search/ConversationSearch.swift`:

```swift
import Foundation

/// A source's conversations past `/conversations/recent`'s cap (G136 R-SU22).
enum ConversationSearch {
    /// CLAUDE.md: the recent list is CAPPED (limit ≤ 200) and never a membership test.
    static let cap = 200

    /// Only a page that HIT the cap can be hiding a title; below it the local
    /// filter already saw everything. One character stays local (R-SU2).
    static func needsServer(loaded: Int, query: String) -> Bool {
        loaded >= cap && SearchTiming.wantsServer(query)
    }

    /// Local rows first, in their order; server rows the page lacked, after.
    static func merge(local: [ConversationSummary], server: [ConversationSummary]) -> [ConversationSummary] {
        var seen = Set(local.map(\.id))
        return local + server.filter { seen.insert($0.id).inserted }
    }
}
```

`Models/SourceOverview.swift` — `enum ConversationFilter` (`:239-245` at `f7dfd21`; `:254-260` after
Task 3's merge of `dev`, where Track Z added `ownsQueuedOrigin`/`owning(origin:in:)` above it):

```swift
enum ConversationFilter {
    /// Titles, every word somewhere, folded like every other field (G136,
    /// `QuickMatch`) — order kept: this list is newest-first, and a filter
    /// must not reshuffle it (R-SU20).
    static func apply(_ rows: [ConversationSummary], query: String) -> [ConversationSummary] {
        let tokens = QuickMatch.tokens(query)
        guard !tokens.isEmpty else { return rows }
        return rows.filter {
            QuickMatch.match(tokens, fields: [QuickMatch.Field($0.displayTitle, weight: QuickMatch.Weight.name)]) != nil
        }
    }
}
```

`Sync/SyncAPI.swift:73` — the requirement gains `query: String?`, and its doc comment one line:
"`query` (G136 R-SU22) is a title filter the backend applies before the same cap (G136 R17)."

```swift
    func fetchRecentConversations(limit: Int, harness: String?, origin: String?, query: String?) async throws -> [ConversationSummary]
```

`Services/APIClient.swift:1401` — signature `fetchRecentConversations(limit: Int = 20, harness: String? = nil, origin: String? = nil, query: String? = nil)`,
and after the `origin` clause:

```swift
        if let query, !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            path += "&q=\(query.addingPercentEncoding(withAllowedCharacters: allowed) ?? query)"
        }
```

`StoreTests.swift` (`FakeSyncAPI`) — add `var recentQueries: [String?] = []` beside
`recentConversations`, and make the method honour the new argument and the cap, as the server does:

```swift
    func fetchRecentConversations(limit: Int, harness: String?, origin: String?, query: String?) async throws -> [ConversationSummary] {
        recentQueries.append(query)
        if failRecentConversations { throw APIError.serverUnreachable }
        let rows = recentConversations.filter { row in
            if let harness, !(row.harness == harness || (harness == "unknown" && row.harness.isEmpty)) { return false }
            if let origin, row.origin != origin { return false }
            return true
        }
        let matched = query.map { ConversationFilter.apply(rows, query: $0) } ?? rows
        return Array(matched.prefix(limit))
    }
```

`ViewModels/ConversationsViewModel.swift` — `load(limit:harness:origin:)` passes `query: nil`; add:

```swift
    /// G136 R-SU22 — titles past the capped page that match, fetched with
    /// `q=` (applied before the cap, G136 R17). Empty below the cap: the local
    /// filter already saw every row.
    private(set) var beyondCap: [ConversationSummary] = []

    func searchBeyondCap(query: String, harness: String? = nil, origin: String? = nil) async {
        guard ConversationSearch.needsServer(loaded: conversations.count, query: query) else {
            beyondCap = []
            return
        }
        do {
            beyondCap = try await api.fetchRecentConversations(limit: ConversationSearch.cap, harness: harness,
                                                               origin: origin, query: query)
        } catch {
            // The loaded page still filters; a failed widening is not an error to show.
            beyondCap = []
        }
    }
```

For the small-page case the test above expects `recentQueries == [nil]` (the load's call only),
which this guard gives.

`Views/Sources/HarnessConversationsView.swift`:
- `visible` becomes
  `ConversationSearch.merge(local: ConversationFilter.apply(viewModel.conversations, query: query), server: viewModel.beyondCap)`.
- The `TextField("Filter by title", …).textFieldStyle(.roundedBorder)…` block (`:21-24`) becomes
  `CicadaSearchField(text: $query, prompt: "Filter by title").frame(maxWidth: CicadaTheme.scaled(320))`.
- The no-match `Text` (`:38-39`) keeps its words and, when `!query.isEmpty`, is followed by
  `SearchAllMemoryRow(query: query)` (wrap both in a `VStack(alignment: .leading, spacing: CicadaTheme.spacingSM)`).
- `load()` is unchanged. A debounced widening follows the text, asked with the same source filter
  `load()` uses (the harness, else the first origin), on the outer `VStack` beside the existing
  `.task`. *Critic:* its id carries the loaded count as well as the text — a palette hand-off
  (Task 3) sets `query` in `onAppear`, before the first page has landed, and `needsServer` reads
  `conversations.count`; keyed on the text alone, the widening ran once against an empty page and
  never again, so a conversation older than the newest 200 was silently missing:

```swift
        .task(id: "\(viewModel.conversations.count)|\(query)") {
            // R-SU22 — debounced like the palette; only a capped page asks.
            // Keyed on the loaded count too: a hand-off sets `query` before
            // the first page lands, and the widening must run once it has.
            try? await Task.sleep(for: SearchTiming.serverDebounce)
            guard !Task.isCancelled else { return }
            await viewModel.searchBeyondCap(query: query, harness: source.harness,
                                            origin: source.harness == nil ? source.origins.first : nil)
        }
```

`Views/Inbox/InboxListView.swift`:
- Add `@State private var query = ""`; `visibleItems` filters the kind-filtered `base` through
  `InboxSearch.filter(base, query: query)` before its existing sort.
- `orderedKinds` (`:108-111`) becomes
  `[.decay, .conflict, .clarification, .mergeSuggestion, .removal, .divergence, .normalization]` —
  the two kinds Sleep writes (G113 slice 3) finally get their chips (R6 §2.6).
- In `headerBar`, under the kind-chip `HStack`, inside the same `if !viewModel.items.isEmpty`:
  `CicadaSearchField(text: $query, prompt: "Search questions…").frame(maxWidth: CicadaTheme.scaled(320)).padding(.horizontal, CicadaTheme.spacingXL).padding(.bottom, CicadaTheme.spacingMD)`.
- In the populated branch, when `visibleItems.isEmpty && !query.isEmpty`, show (instead of the empty
  `LazyVStack`):

```swift
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text("No question matches “\(SearchAllMemoryRow.trimmed(query))”.")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    SearchAllMemoryRow(query: query)
                }
                .padding(CicadaTheme.spacingXL)
```

- Task 3's `land(_:)` also clears the field: add `query = ""` beside `kindFilter = nil`, so a palette
  hand-off is never hidden by an old filter.

- [ ] **Step 3: Green.** `swift test --filter "PageSearchTests|ConversationsTests|SourcesPageTests|StoreTests|ConversationAffordanceTests"`,
  then the full `swift test` → 0 failures; `swift build` clean.
- [ ] **Step 4: Commit** — stage `Search/ConversationSearch.swift`, `Models/SourceOverview.swift`,
  `Sync/SyncAPI.swift`, `Services/APIClient.swift`, `ViewModels/ConversationsViewModel.swift`,
  `Views/Sources/HarnessConversationsView.swift`, `Views/Inbox/InboxListView.swift`,
  `Tests/CicadaAppTests/PageSearchTests.swift`, `Tests/CicadaAppTests/ConversationsTests.swift`,
  `Tests/CicadaAppTests/StoreTests.swift`:
  `feat(app): search a source's conversations past the cap, and the Inbox (G136 S5)`.

---
### Task 7: `GraphNode.aliases`, measured first — and the docs (S6; R-SU23)

The only backend change in this track, gated on a number. The docs close the G136 row in the same
commit so the handoff never lags the code.

**Files:**
- Create: `api/tests/test_graph_aliases.py`
- Modify: `api/models/schemas.py:937-982` (`GraphNode`), `api/services/graph_builder.py`
  (`MAX_NODE_ALIASES`, `node_aliases`, the entity `GraphNode(...)` at `:160-176`),
  `api/routers/graph.py` (`NODE_SHAPE`, the ETag `extra`), `…/Models/Entity.swift:852-990`
  (`GraphNode`), `…/Search/QuickIndex.swift` (`entityDocs`), `…/ViewModels/GraphViewModel.swift`
  (`searchFields`), `FindFixtures.swift` (`node(…aliases:)`), `QuickIndexTests.swift`;
  `docs/goals/memory-evolution.md` (G136, G93, G123), `docs/goals/TODO.md`, `CLAUDE.md`

**Interfaces:**
- Produces `GraphNode.aliases` on the wire (`aliases`, ≤ 8) and in Swift (decode-tolerant),
  `graph_builder.MAX_NODE_ALIASES`, `graph_builder.node_aliases(fm)`, `graph.NODE_SHAPE`.
- Consumes `search_service`'s existing `aliases` convention (`strs(fm.get("aliases"))[:8]`,
  `api/services/search_service.py:666`) — the same cap, so both tiers see the same eight.

- [ ] **Step 1: Failing tests** — `api/tests/test_graph_aliases.py`:

```python
"""G136 S6 — `GraphNode.aliases` on `/graph`, measured before it ships (plan R-SU23).

The design (round-3 §3.9 item 5) gates the field on its payload cost: `/graph`
is the app's largest snapshot. The fixture is pessimistic on purpose — every
one of 2,000 nodes carries aliases and there are no edges to dilute the ratio —
generated from a fixed seed and made-up syllables (no names, the same bank on
every machine; the G136 R18 rule). Run with `-s` to see the numbers.
"""
from __future__ import annotations

import json
import random

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import GraphResponse
from api.routers import graph as graph_router
from api.services import bank_index, graph_builder, markdown_parser, sync_service

N_NODES = 2000
_SYLLABLES = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
              "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4)))


def _bank(root, aliases_per_node: int):
    memory = root / f"aliases-{aliases_per_node}"
    (memory / "entities").mkdir(parents=True)
    rng = random.Random(7)
    types = ["project", "person", "concept", "tool"]
    for i in range(N_NODES):
        prose = " ".join(" ".join(_word(rng) for _ in range(12)).capitalize() + "." for _ in range(6))
        markdown_parser.write(
            memory / "entities" / f"e-{i}.md",
            {"name": f"{_word(rng)} {_word(rng)} {i}", "type": types[i % 4], "status": "active",
             "confidence": 0.5, "tags": [_word(rng)], "aliases": [_word(rng) for _ in range(aliases_per_node)]},
            f"## Summary\n{prose}\n",
        )
    return memory


def _build(memory) -> GraphResponse:
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})   # keyed on mtimes, not paths
    return graph_builder.build_graph(memory)


def _wire_bytes(resp: GraphResponse, *, with_aliases: bool) -> int:
    """What `GET /graph` sends: camelCase, compact separators (Starlette's JSONResponse)."""
    exclude = None if with_aliases else {"nodes": {"__all__": {"aliases"}}}
    body = resp.model_dump(mode="json", by_alias=True, exclude=exclude)
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())


def _growth(resp: GraphResponse) -> tuple[int, int, float]:
    base = _wire_bytes(resp, with_aliases=False)
    grown = _wire_bytes(resp, with_aliases=True)
    return base, grown, (grown - base) / base


def test_two_aliases_on_every_node_grow_the_graph_payload_by_at_most_ten_percent(tmp_path):
    base, grown, growth = _growth(_build(_bank(tmp_path, 2)))
    print(f"\nG136 S6 /graph, {N_NODES} nodes x 2 aliases: {base:,} -> {grown:,} bytes (+{growth:.1%})")
    assert grown > base, "the field must be on the wire to be measured"
    assert growth <= 0.10


def test_aliases_are_capped_at_eight_and_the_worst_case_is_recorded(tmp_path):
    resp = _build(_bank(tmp_path, 12))
    assert max(len(node.aliases) for node in resp.nodes) == graph_builder.MAX_NODE_ALIASES
    base, grown, growth = _growth(resp)
    print(f"\nG136 S6 /graph at the cap, {N_NODES} nodes x 8 aliases: {base:,} -> {grown:,} bytes (+{growth:.1%})")


def test_node_aliases_are_strings_only_blank_free_and_ordered():
    assert graph_builder.node_aliases({"aliases": ["alpha", " ", 7, True, None, "beta"]}) == ["alpha", "7", "beta"]
    assert graph_builder.node_aliases({"aliases": "alpha"}) == ["alpha"]
    assert graph_builder.node_aliases({}) == []
    assert graph_builder.node_aliases({"aliases": {"a": 1}}) == []


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "aliases": ["alpha"]}, "About alpha-project.")
    with TestClient(main.app) as c:
        yield c, tmp_path
    config.get_settings.cache_clear()


def test_graph_serves_aliases_and_its_etag_moves_once_for_the_new_shape(client):
    c, mem = client
    r = c.get("/graph")
    node = next(n for n in r.json()["nodes"] if n["id"] == "alpha-project")
    assert node["aliases"] == ["alpha"]
    default_extra = "None|None|0.0|None|True|False"
    before = sync_service.etag_for(mem, "entities", "edges", "hubs", "inbox", "logos", extra=default_extra)
    assert r.headers["etag"] != before, "a pre-S6 client gets one 200, never a 304 into an alias-less cache"
    assert r.headers["etag"] == sync_service.etag_for(
        mem, "entities", "edges", "hubs", "inbox", "logos", extra=f"{default_extra}|{graph_router.NODE_SHAPE}")
```

Swift, in `QuickIndexTests.swift`:

```swift
    /// G136 S6 — an alias finds its node at the alias weight, and a payload
    /// without the field (an older backend, an on-disk cache) still decodes.
    func testAnAliasFindsItsNodeAndAnOldPayloadStillDecodes() throws {
        var inputs = FindFixtures.inputs()
        inputs.nodes.append(FindFixtures.node("bob-example-2", "bob-example-2", aliases: ["beta tester"]))
        XCTAssertEqual(QuickIndex.build(inputs).query("tester").rows.first?.key.id, "bob-example-2")
        let old = try JSONDecoder().decode(GraphNode.self, from: Data(#"{"id": "a", "name": "A", "type": "concept", "confidence": 0.5}"#.utf8))
        XCTAssertEqual(old.aliases, [])
        let new = try JSONDecoder().decode(GraphNode.self, from: Data(#"{"id": "a", "name": "A", "type": "concept", "confidence": 0.5, "aliases": ["alpha"]}"#.utf8))
        XCTAssertEqual(new.aliases, ["alpha"])
    }
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_graph_aliases.py -q -s -p no:cacheprovider`
→ fails (`AttributeError: 'GraphNode' object has no attribute 'aliases'` / `node_aliases`), and the
Swift test fails to compile. That is the red.

- [ ] **Step 2: Implement the backend.** `api/services/graph_builder.py`, beside `content_hash`:

```python
MAX_NODE_ALIASES = 8


def node_aliases(fm: dict) -> list[str]:
    """G136 S6 — a page's ``aliases:`` for ``GraphNode.aliases``, so the app's
    instant tier finds a node by another name before the server answers.
    Strings (and numbers) only, blanks dropped, order kept, at most
    ``MAX_NODE_ALIASES`` — the cap ``search_service`` already applies, so both
    tiers see the same eight. A hand-written scalar (``aliases: alpha``) is one
    alias, not five letters. Already inside ``content_hash`` (it hashes the
    frontmatter), so a changed alias repaints the node's delta."""
    raw = fm.get("aliases")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = [str(a).strip() for a in raw
           if isinstance(a, (str, int, float)) and not isinstance(a, bool) and str(a).strip()]
    return out[:MAX_NODE_ALIASES]
```

and `aliases=node_aliases(fm),` in the entity `GraphNode(...)` call (after `is_owner=...`).
`api/models/schemas.py`, `GraphNode`, after `is_owner`:

```python
    # G136 S6 — the page's `aliases:` (≤ 8, `graph_builder.node_aliases`), for the
    # app's instant search tier. Shipped after measuring the payload (plan
    # R-SU23; the number is on the G136 row). Additive/defaulted.
    aliases: list[str] = []
```

`api/routers/graph.py`, above `get_graph`:

```python
# G136 S6 (plan R-SU23) — nodes gained `aliases`. The ETag's components did not
# move (aliases already live in the entity files), so an app holding a pre-S6
# `/graph` would 304 into an alias-less cache until some entity changed. The
# node shape rides `extra`: every client pays one 200, once. Bump it whenever a
# node gains a field a client must see; no `VersionVector` change is needed.
NODE_SHAPE = "aliases"
```

and `extra = f"{types}|{statuses}|{min_confidence}|{tags}|{include_hubs}|{hubs_only}|{NODE_SHAPE}"`.

- [ ] **Step 3: The gate.** Run `api/.venv/bin/python -m pytest api/tests/test_graph_aliases.py -q -s -p no:cacheprovider`
  and copy both `G136 S6` lines into the task report.
  - **Growth ≤ 10 %** (expected — the planning probe measured +5.8 %): all four tests pass; go on
    to Step 4.
  - **Growth > 10 %** — R-SU23's other branch: revert the three backend edits, delete
    `api/tests/test_graph_aliases.py`, and do not add the Swift test; record the printed number on the
    G136 row as "S6 skipped: aliases would add N % to `/graph` on the pessimistic fixture; they arrive
    with the server tier only (`matchedField: alias`)". Skip Step 4; do Steps 5–7 (the commit then
    carries only the docs).

- [ ] **Step 4: Implement the app side.** `Models/Entity.swift` (`GraphNode`): `let aliases: [String]`
  after `isOwner` with the doc comment "G136 S6 — the page's other names (≤ 8), for the palette's
  instant tier and the graph typeahead. Decode-tolerant: an older backend and an on-disk cache omit
  it."; `aliases` added to `CodingKeys`; `aliases: [String] = []` appended to `init(...)`'s
  parameters with `self.aliases = aliases`; in `init(from:)`
  `aliases = try c.decodeIfPresent([String].self, forKey: .aliases) ?? []`.
  `Search/QuickIndex.swift` `entityDocs`: after the name field,
  `fields += node.aliases.map { QuickMatch.Field($0, weight: QuickMatch.Weight.alias) }`.
  `GraphViewModel.searchFields(_:)`: the same line between the name and the tags.
  `FindFixtures.node(...)`: a trailing `aliases: [String] = []` parameter passed to `GraphNode(…, aliases: aliases)`.
  Then `swift test --filter QuickIndexTests` → green, and the full `swift test` → 0 failures.

- [ ] **Step 5: Docs** (privacy rule: placeholders only, no bank contents, no counts read from a bank).
  - `docs/goals/memory-evolution.md`, row **G136**: replace the "**Open:** the palette (…)" sentence
    with "**App half shipped (2026-09-23, `feat/find-palette`; plan
    `../superpowers/plans/2026-09-23-find-palette.md`, rulings R-SU1–R-SU26):**" followed by one dense
    paragraph citing ruling ids, not restating them — ⌘K is a find palette with Ask as a mode (⌘⏎,
    the answer body hosted unchanged); one ranker (`QuickMatch`, the server's fold); an instant tier
    (`QuickIndex`) rebuilt off the main actor; the debounced server tier (150 ms prefix, 450 ms hybrid)
    appended by a merge that never moves a shown row; conversations grouped by conversation with who
    said it; superseded beliefs as history; honest counts; ⌘K/⌘F as menu commands with a lint; one
    `CicadaSearchField` on Graph, Clusters, Feed, a source's conversations (past the cap through
    `q=`) and the Inbox (plus its two missing kind chips); the S6 measurement (both printed numbers)
    and its outcome; the local-tier release p95 the orchestrator measured. Then "**Still open:**" —
    Reader routing for conversation and belief rows (Track P, P6; `FindReaderSeam`), per-setting rows
    (Track O's `SettingsIndex` into `QuickIndex.settingsDocs`), a paper's byline in `FeedSearch` if
    Track F landed after this, the error banner's `danger` token inside the Ask body, MCP recall
    adoption (Track R). Status cell: "✅ server + palette; Reader routing is Track P's". *Critic:* in
    the same row, correct "`feat/search-everywhere`, PR #75" to **PR #74** (`git log --merges`: #74 is
    search-everywhere, #75 is the remote connector).
  - Row **G93**: append "G136 (2026-09-23) made ⌘K a find palette with Ask as a mode (⌘⏎); what
    'smart' adds — cross-stream retrieval — stays this row's."
  - Row **G123**: append "G136 S5 (2026-09-23): the field is the shared `CicadaSearchField`, ranked by
    `QuickMatch` over name, tags and aliases; ⌘F is a menu command only the visible Graph tab claims."
  - `docs/goals/TODO.md`: the "**Search (G136):**" line under *Pick up here* becomes "shipped — server
    (PR #74) and palette (this track); what is open is on the row"; the *Shipped* → **Search** line
    gains the palette; *Where things stand* gains one sentence for this track with the re-measured
    backend and Swift baselines.
  - `CLAUDE.md`, *Companion App* → **Navigation**: replace "⌘K opens the Ask panel." with "⌘K opens
    the find palette (below)." and add after the **View menu** paragraph:

    > **Find palette (G136).** ⌘K ("Find in Memory…") and ⌘F ("Find on This Page…") are menu
    > commands in `Support/FindCommands.swift` — a lint keeps both shortcuts there, and ⌘F reaches
    > only the visible page's field. The palette is an overlay, chrome glass around an opaque body,
    > whose instant tier (`QuickIndex`) is rebuilt off the main actor from the Store's snapshots and
    > answers every keystroke with no network; ~150 ms later `GET /search` (prefix, then hybrid)
    > appends conversations, beliefs (superseded ones as history) and whatever the local tier missed —
    > a shown row never moves. Ask is a mode (⌘⏎) hosting the unchanged `AskPanel` body. One ranker,
    > `QuickMatch`, folds text exactly like the server's `text_fold`; every in-page field is
    > `CicadaSearchField`. Recents are `(kind, id)` pairs in the cache-only `.quickRecents` domain; the
    > query is never stored, logged or sent anywhere but `/search` and `/conversations/recent?q=`.
    > `FindPanelBody` is the hostable body (Home).

    and, if S6 shipped, append to the **ETags** paragraph: "`/graph`'s `extra` carries a node-shape tag
    (`graph.NODE_SHAPE`), bumped when a node gains a field a client must see."

- [ ] **Step 6: Green, all of it.** The full backend suite (`api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
  → 0 failures), `swift build`, the full `swift test` (0 failures) and `node --test app/CicadaApp/Tests/graph/*.test.js`.
- [ ] **Step 7: Commit** — stage `api/tests/test_graph_aliases.py`, `api/models/schemas.py`,
  `api/services/graph_builder.py`, `api/routers/graph.py`, `Models/Entity.swift`, `Search/QuickIndex.swift`,
  `ViewModels/GraphViewModel.swift`, `Tests/CicadaAppTests/FindFixtures.swift`,
  `Tests/CicadaAppTests/QuickIndexTests.swift`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`,
  `CLAUDE.md` (the skip branch stages only the docs):
  `feat(graph): node aliases on /graph after measuring the payload; docs: G136 palette shipped (G136 S6)`.

---

## Not in scope

Named so a reviewer reads an absence as a decision, not an oversight.

- **Server ranking or new server fields.** `/search` is used exactly as PR #74 shipped it; where the
  palette wants something the wire lacks (a media hit's URL, a claim's evidence date) it reads what
  the app already holds or goes without, and says so in a ruling. The one backend edit is S6's field.
- **Settings search and per-setting rows** — Track O (`SettingsIndex`, spike S0). The palette lists
  sections and explains how to open them (R-SU12).
- **The Reader** and routing into it — Track P (P2/P6). This track leaves one flag and two seam
  comments (R-SU18).
- **Evidence snippets and `sourceEpisodes` chips in the Ask answer, and its `danger` error token** —
  inside the answer body Track P is editing (R-SU7).
- **MCP recall adoption** of `search_service` — Track R.
- **"Add a source" / "Import an export…" actions** — Track I's one intake (R-SU13).
- **⌘C "copy link"** on a row (R-SU11), and **restoring focus** to the element that held it before
  the palette opened (R-SU26).
- **Liquid Glass on the graph's search field** until the G109 frame-time check (R-SU17).
- **Aliases in Clusters' own index** — `graphVM.entities` are stubs with no alias field; Clusters
  finds a node by name, tags and summary, and the palette finds it by alias.
- **Typo tolerance, date-scoped search, saved searches** — G93 / G99 territory.
- **Any telemetry** (R-SU16) and **any LLM** outside Ask mode's existing `/ask`.

## Hand-off

1. **Track P (P6).** After P2 lands, set `FindReaderSeam.isAvailable = true` and route
   `FindDestination.conversation(target)` → `ReaderTarget` for `target.span` and `.evidence(span)` →
   `ReaderTarget` for `span`, in `ContentView.openFind` (Task 4 Step 0 spells the mapping, written
   against Track P's struct `ReaderTarget` at `bbc7943`). Belief rows also want the entity card to open
   on Perspectives scrolled to the claim — the card is P's.
2. **Track I (Home, decision 12).** Host `FindPanelBody(model:placement: .page, open:)` with the
   environment's `FindPaletteModel` (or a second instance for an independent field) and pass
   `ContentView.openFind` as `open`.
3. **Track O (O2).** Feed `SettingsIndex` rows into `QuickIndex.settingsDocs()` — same group, same
   `FindDestination.settings`, plus the row id once `SettingsSectionLink` carries one.
4. **Track F.** Merged in PR #77 before this track's Task 3, so Task 5 Step 0's **Found** branch
   lands the byline in `FeedSearch.fields(_:)` here; this hand-off only applies if that step somehow
   found nothing, in which case add the lines it spells — the Feed and the palette both pick them up.

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0 failures**
   (re-measure the dev baseline first; the order-dependent `test_agent_provenance` case, if it is the
   only red, is re-run alone and both results reported).
2. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success; `swift test 2>&1 | tail -20`
   → **0 failures** (the re-measured dev count + 65 with the Track F paper case — the critic's run on
   `a5fb5f1`: 1,253 + 65 = 1,318). `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → green.
3. **The release budget:** `cd <worktree>/app/CicadaApp && swift test -c release -Xswiftc -enable-testing --filter QuickIndexLatencyTests 2>&1 | grep "G136 local tier"`
   → p95 ≤ 8 ms; quote the line in the PR and on the G136 row.
4. **The lints bite once each:** add `.keyboardShortcut("k", modifiers: .command)` to any view outside
   `Support/FindCommands.swift` → `swift test --filter HiddenShortcutLintTests` FAILS; revert → green.
   Same for a literal `.glassEffect(` in `Views/Find/FindPalette.swift` (`LiquidGlassLintTests`).
5. `api/.venv/bin/python -m pytest api/tests/test_graph_aliases.py -q -s -p no:cacheprovider` → the two
   `G136 S6` lines, quoted in the PR.
6. `git diff dev -- app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift` → every hunk above
   `// MARK: - Answer`. `grep -rn "showAskPanel\|AskButton(" app/CicadaApp/Sources` → nothing.
7. **Live, after installing, on the demo bank** (`macos-harness`; the Edit menu through the
   accessibility tree): the Edit menu shows "Find in Memory… ⌘K" and "Find on This Page… ⌘F" with no
   second ⌘F item; ⌘K from Graph, Feed and the Settings window opens the palette on the main window;
   typing two letters fills Entities / Sources & papers / Inbox / Actions at once, and Conversations
   and Beliefs arrive ~150 ms later **below** without anything above moving; ↑/↓, ⌘↑/⌘↓, Tab/⇧Tab
   walk the rows; ⏎ on an entity switches to Graph and reveals it; ⌥⏎ opens it in Clusters; ⏎ on a
   saved item opens its preview sheet; on an inbox row, the Inbox with that card open; on a source
   row, its Sources page — **also from another source's open detail**, which must show the new
   source's conversations, not the old ones (the `.id(source.id)` fix); on a conversation row, that
   source's conversations filtered to the title (or the Reader, if Track P merged); "Consolidate now"
   is offered only while something is queued; a superseded belief reads "Was … until …"; ⌘⏎ asks and shows
   the answer in the same panel; Esc goes Ask → Find → clear → closed; ⌘F on each page focuses that
   page's field and on the Sleep page is disabled; the Graph field still reveals nodes. Then **Reduce
   Motion** (no scale-in, no hairline, footer still says "Searching conversations…"), **Reduce
   Transparency** (opaque panel), **VoiceOver** (row labels, header traits, the position
   announcement), **dark and light**, **1.0× and 1.4× zoom**, and on macOS 26 the glass panel with
   an opaque body.
8. **The `/graph` cost on the live bank** (orchestrator only, numbers only): `Content-Length` of
   `GET /graph` before and after installing (`curl -s -o /dev/null -w '%{size_download}\n' -H "Authorization: Bearer $(cat ~/.cicada/api_token)" http://localhost:8000/graph`)
   → the percentage goes on the G136 row beside the fixture's.
9. **PR body states:** no ETag component and no `VersionVector` mapping changed — `/graph`'s `extra`
   gained the node-shape tag (one 200 per client, pinned by `test_graph_aliases.py`), and
   `.quickRecents` is cache-only like `.askHistory`; no telemetry added; the query goes only to
   `/search` and `/conversations/recent?q=` and is never stored (recents are `(kind, id)`); no price,
   token count or LLM call added; `AskPanel`'s answer body untouched; the Reader, Settings rows and the
   paper byline are hand-offs, each named above.
