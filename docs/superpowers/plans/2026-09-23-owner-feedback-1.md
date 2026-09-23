# Owner feedback fixes 1 (Track F1) — Implementation Plan

> **For agentic workers:** execute task by task, in order, in this one worktree. Steps use checkbox
> (`- [ ]`) syntax. No subagents. Every task is one reviewable commit that leaves the branch
> shippable: failing test → implement → green → the task's suites → commit.

**Goal:** Fix what the owner saw in the live app on 2026-09-23. **(1) Junk facet nodes.** The graph
served extra nodes named after a raw folder id (`folder:<folder-id>:<section>`) or `general`, two
per annotated paper. Clicking one opened an empty card, and the Graph legend listed the raw id as
a context. After this track, papers write the house context, the graph never
splits a subject on `general` or on a value that is not a context, the legend lists real contexts
with readable names, a facet click opens its subject's card, and each paper has an edge to the
project that cites it. **(2) Raw-claims pages.** Pages `agentic_write` created show their
` ```claims ` YAML flattened inside the Summary box. After this track, no reader shows the fence as
text, `agentic_write` writes a real one-line Summary from the claim it is writing, existing
placeholder pages are rewritten once, and a page whose only prose is its Summary lists its beliefs
under **What Cicada knows**. **(3) A minimal display font.** Instrument Serif is replaced by SF Pro
Display through the same `displayFont(size:italic:)` API. No font is bundled any more.

**Architecture:** Two small shared rules, each written once and pinned by a test. The first is
`api/services/claim_contexts.py`: what a context may be, and that `general` is never a facet. It
has a Swift twin, and one shared JSON fixture pins both. The second is `EntityProse` in the app:
strip the claims fence before reading any section, the way the server's
`entity_body.summarize_for_recall` already does. The papers writer keeps every claim id it ever
minted: the id is derived from the *slot*, which was the old context string, so no claim is closed
and reopened. It projects its own claims' edges through the same row builder Sleep's Stage 5.7
uses. Two one-shot, marker-guarded, `Cicada-Author: cicada` migrations repair existing banks at
startup, and both are idempotent. The display face change stays behind the existing API, and a
lint keeps a bundled font from coming back.

**Tech Stack:** Python 3 / FastAPI / pytest (`api/`), SwiftUI + XCTest (`app/CicadaApp`), markdown
+ git bank.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`. Its
Decisions bind, and this plan amends Decision 6's "Instrument Serif" and R-M3 by the owner's
2026-09-23 instruction (R-FX12). Other binding context:
`docs/superpowers/plans/2026-09-23-local-sources.md` (R-LS14 … R-LS17: papers, their claims, and
how they wait for Sleep) and `docs/superpowers/plans/2026-09-23-meadow-foundation.md` (R-M15: the
display face, its registration and its lints). Backlog rows: **G133** (papers), **G24** (the
Summary box), **G137** (Meadow type roles), **G60** (the inbox's "both" context qualifier), **G118**
(evidence text is the body with the fence stripped). Standing rulings: the privacy rule, ETag
ship-together, Sleep safety (no LLM at capture or migration; engine-free read paths), and
portability.

---

## What the code actually does today (verified against `fix/owner-feedback-1` @ `7162c1c`)

**Where the junk facets come from.**
- `api/services/papers.py:371` writes `saved-because` with `context=f"folder:{folder_id}:{section}"`.
  `:374` (`cited-in`) and `:379` (`about`) write `context="general"`, and so does
  `paper_metadata.py:265` (`describes`). An annotated paper therefore has claims in two contexts.
- `papers.py:356`: `cid = claim_id(entity_id, predicate, obj, observer, context)`, so **the context
  is part of every paper claim id**. `apply_claims` `:425-426` picks a closed claim's successor by
  `d.predicate == c.predicate and d.context == c.context`. The section in the context is the only
  thing that told two sections' notes on one page apart.
- `api/services/graph_builder.py:152-157` puts every non-empty `claim.context` into
  `subject_contexts` and into `edge_claim_index`. `:300-335` (M5b) creates a satellite
  `"<subject>#<ctx>"` for **every** context once a subject has two, with `name=ctx` (`:315`). That
  is the junk: one satellite named after the raw folder id and one named `general`.
- `general` is Cicada's word for "no particular context". Evidence: `claims.py:130` defaults to it;
  every deterministic writer uses it (`entity_extractor.py:560`, `link_enrichment.py:104/128`,
  `link_recon.py:177`, `paper_metadata.py:265`, `claim_seeder.py:184`); and
  `docs/goals/d2-architecture-final.md:326-327` calls it "the `observer: agent, context: general`
  special case" of extraction. The d2 facet example (`:428-436`) splits engineer-self from
  family-self, two *real* contexts. The vocabulary is **open** (d2 `:202`, `claims.py:130`, the MCP
  schema at `mcp/server.py:353-356` gives examples, not an enum). The graph colours the core six
  (`graph.js:63-70`, `CicadaTheme.swift:457-473`) and hashes the rest to a hue.
- A second non-slug context already exists by design: G60's "both" resolution writes
  `f"as of {valid_from}"` into `context` (`inbox_service.py:1149`, `:1288`) so the two answers stop
  sharing a claim key. It must keep that job. Two such claims on one subject also produce satellites
  today.
- **The legend.** `GraphViewModel.swift:199-203` takes the union of every `node.contexts`,
  `node.context` and `link.context` as `contextRoster`. `ContextLegend.swift:73` renders the raw
  string, and so does `ContextPill` (`ClaimChip.swift:111`).
- **The empty card.** `GraphView.swift:178-181` (`nodeClicked`) calls
  `GraphViewModel.selectEntity(id:)`. Then `applySelection(id:)` (`:506-513`) selects the satellite's
  stub, which has no file, and fetches `/entities/<subject>#<ctx>`, which 404s.
- **Papers float.** `graph_edges.yaml` is the only edge source (`graph_builder._load_edges:488`).
  Claim-derived rows come only from `regenerate_edges_from_claims` (`:397-485`), which runs at Sleep
  Stage 5.7 (`sleep_cycle.py:1282`). A folder sync (`routers/local_sources.py:143-160`, which
  commits `papers.reconcile`'s `paths`) never writes an edge. So a paper's `cited-in` claim to the
  folder's project has no edge until a Sleep cycle runs, and the live bank has not consolidated yet.

**Where the raw claims come from.**
- `claims.write_claims:351-357` appends the fence **after the page's last section**. No page anywhere
  has a claims section. Sleep-written pages carry the fence after `## Key Facts` or whatever section
  comes last.
- `agentic_write._ensure_subject_page:180-196` creates a page whose only section is
  `## Summary\n<name> — created via agentic write.`. Then `write_claim` (`:457-459`) appends the
  fence, so to a line-based reader the fence sits *inside* the Summary.
- **App.** `EntityDetailCard.swift:848-860` `section(named:in:)` reads up to the next `## ` or EOF,
  so the fence is included. `summaryText` (`:894-896`) feeds `SummaryBox` (`:1552-1580`), which
  renders through `MarkdownBody.inlineAttributed`. The result is the flattened
  `claims - id: clm_… text: …` the owner screenshotted. `mediaDescription` (`:838-845`) has the same
  defect (a paper's Summary is `Saved paper — X.` plus the fence). `FeedView.swift:465` →
  `firstSection` (`:484-498`) has the same defect. `MarkdownBody.swift:92-94` already hides a ` ```claims ` code
  block in the body, so only the section readers leak.
- **Server.** `graph_builder.summarize:18-34`: an empty Summary previews as the fence line, and a
  page with no heading previews as YAML. `routers/entities.py:183-187` `_build_media_block` lifts
  `## Summary` to EOF into `media.description`. `hub_builder._one_line_summary:43-63` sections the
  body unstripped. These readers already strip first: `entity_body.summarize_for_recall:450-458`,
  `evidence.py:120`, `state_dictionary.py:168-173`, `search_index.py:322`,
  `link_enrichment.py:84-87`.
- **Claims already have a renderer:** `ClaimChip` (`ClaimChip.swift:12-68`) in the Perspectives tab
  (`EntityDetailCard.swift:1282-1310`), loaded lazily by `loadClaimsIfNeeded` (`:1489-1494`). The
  card has one identity per entity (`ContentView.swift:383-387`, `TopicsView.swift:770-775`), so its
  claim state never leaks between entities.

**The display face.**
- `Theme/CicadaTheme.swift:316-336`: `displayMinimumSize = 22`; `displayFont` returns
  `.custom(InstrumentSerif-…)`; `quoteFont` is New York italic, which is unrelated to the removed face
  and stays.
- `Theme/CicadaFonts.swift` registers `Resources/fonts/InstrumentSerif-{Regular,Italic}.ttf`
  (together with `OFL.txt` and `FONTS.md`). It is called only at `CicadaApp.swift:87-88`.
  `Package.swift:10` copies `Resources` wholesale, so deleting the files deregisters nothing else.
- Callers: `PageHeader.swift:30` (28 pt), `EmptyStateView.swift:50` (26 pt),
  `ReaderInspector.swift:100` (22 pt). The Sleep sentence still uses New York serif
  (`RoomSentence.swift:325` at 30 pt, `:404` at 22 pt italic), waiting for Z10: its docstring
  (`:286-287`) says Z10 "swaps these two calls and nothing else", and Z10
  (`2026-09-23-mascot-page.md:6060`) turns them into `displayFont(size:)` /
  `displayFont(size:italic:)`. `EmptyStateViewTests.swift:37` pins the text `displayFont(size: 26)`.
- **Sibling branches already spell display titles** (checked with `git diff dev...<branch>`):
  `feat/mascot-page-b` moves `PageHeader`'s title into a `PageTitle` view in the same file (and
  `PageTitleTests` pins exactly one `displayFont(` there), and `feat/settings-v3` adds six roman
  `displayFont(size: 24)` titles. See **Merge notes** before touching `PageHeader`.
- Tests: `CicadaFontsTests.swift` (registration, both bundle layouts, `.custom` equality) and
  `FontLiteralLintTests.swift:44-76` (no `.custom(` outside the theme; no display call under 22 pt).
- **Measured 2026-09-23** (`NSFont.systemFont(ofSize: 28, weight: .semibold)`, no tracking): SF
  sets "Integrations" at 152–153 pt and "Chrome bookmarks" at 248–249 pt (146 / 240 pt at −2 %
  tracking; re-measured by the plan critic). The serif set them at 114 pt and 189 pt (R-M16), so SF
  is about 30 % wider.

**Baselines:** all green on `dev`. The brief quotes backend 2225 and Swift 1012; TODO.md's latest is
2273 / 1141, measured on Track I. **Re-measure on this worktree before Task 1; never trust a
remembered count.** `dev` has since moved to `a27e2ca` (the find palette, PR #80); see **Merge
notes**.

---

## Global Constraints

- Work ONLY in `<worktree>` = `<repo>/.worktrees/f1`, as an absolute path (branch
  `fix/owner-feedback-1`). Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path
  (zoxide hijacks relative `cd`; ignore its stderr warning). No `grep --include=*.ext` (zsh globs
  it); use `rg` or quote it.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Fixtures are synthetic: `alpha-project`, `bob-example`, `gamma-project`, `example.com`, folder id
  `f0a1b2`, section `reading-list`, arXiv `2401.00001`, DOI `10.1234/example.5678`.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. The full
  `api/tests` must be **0 failures**. If
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
  the ONLY red, re-run it alone and report both results.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` succeeds and
  `swift test 2>&1 | tail -20` reports **0 failures**. Graph JS:
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`. SourceKit diagnostics naming
  OTHER worktrees are noise. NEVER `make dev`, `make install-app`, `swift run`, or launch/kill the
  app or the launchd backend.
- Never `git add -A`; stage named files only (`git rm` for deletions). Never commit `memory/`,
  `logs/`, `.claude/settings.json`, `api/.venv` or `*-report.md`. No push, no branches or worktrees,
  no subagents. Ignore Devin/PR comments.
- **Other tracks are editing** the Sleep page and `PageHeader` (`feat/mascot-page-b`), Settings,
  `CicadaApp.swift` and `CicadaTheme.swift` (`feat/settings-v3`), and the find palette (merged to
  `dev` as `a27e2ca`). Touch `Views/Sleep/RoomSentence.swift` only as Task 5 says (R-FX13), touch
  nothing else under `Views/Sleep/` or `Views/Settings/`, keep `GraphViewModel.swift` to the two
  edits Task 1 names, and keep `CicadaApp.swift` / `CicadaTheme.swift` / `PageHeader.swift` to the
  hunks Task 5 names. **Merge notes** (after Not in scope) say how each overlap resolves.
- **Sleep safety:** no LLM anywhere in this track. Both migrations are deterministic, marker-guarded
  and never raise. Paper writes still wait while a cycle runs (R-LS17, unchanged). The graph read
  path stays engine-free.
- **ETag ship-together:** `/graph`'s recipe (`routers/graph.py:32-35`: `entities`, `edges`, `hubs`,
  `inbox`, `logos`) already covers every file this track writes (`graph_edges.yaml` is the `edges`
  component, `sync_service.py:151`, mapped by `VersionVector.swift:14`). **No component is added
  and no `extra` changes.** Say so in the PR body. *Disclosed, not fixed:* Task 1 and Task 3's
  `summarize` are read-side only, so on a bank neither migration touches (no paper, no placeholder
  page) the ETag does not move at upgrade and the app keeps its cached graph until the next entity
  or edge write. The owner's bank is not that bank (both migrations rewrite files there), and the
  house has no version salt in `extra` to reuse.
- **App copy** is plain and friendly, with no jargon and no prices or token counts. Fonts go through
  `CicadaTheme.font` or `displayFont`; durations go through `CicadaMotion`; no hex outside the theme.
  The lints enforce all three.
- **Privacy:** no owner name, no real folder or section name, no counts read from the live bank in
  code, tests, docs, commits or PR bodies. Write `<worktree>` / `<repo>` in docs.
- Docstrings explain **why** and cite the ruling or G-row (`R-FX…`, G133, G24, G137), at the
  density of the files touched. Line numbers above are from `7162c1c` and drift as tasks land; read
  before editing.

---

## Rulings (binding)

Where the brief left a choice, it is decided here with its reason, so no task re-opens it.

- **R-FX1 — A context is a short lowercase slug. The vocabulary stays open.**
  `claim_contexts.is_valid` = `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, ≤ 32 chars. The brief's "not in the
  known context set" reading is **declined**. d2 §2 says OPEN, and the MCP schema
  (`mcp/server.py:353-356`) offers examples, not an enum, so an agent may coin `health`; a closed
  set would silently delete legitimate facets. Only the *shape* is closed.
  The rule is read-side only: a non-slug value (a `folder:` id, G60's `as of <date>`) still works as
  a claim key, but never becomes a facet, a legend row or an edge colour. Validating an agent's
  `context` at write time is **not** in this track (see Not in scope): it would change which claims
  share a key, and that is G60 territory.
- **R-FX2 — `general` is "no particular context" and is never a facet.** This is verified against
  M5b's design (d2 `:326-327`, and the engineer/family example at `:428`). A satellite exists only
  when a subject has claims in **two or more real, non-`general`** contexts, one satellite per real
  context. `general` claims stay on the parent. `general` stays in `node.contexts` and in the legend,
  because it is a real value that colours edges and filters.
- **R-FX3 — The legend shows real contexts only, with readable names, and a facet click opens its
  subject.** One pure helper per side (`claim_contexts.display_name` / `ClaimContext.displayName`:
  `machine-learning` → "Machine learning"). A shared fixture
  (`api/tests/fixtures/claim_contexts.json`, the `video_urls.json` precedent) pins both. Facet
  `name` is set with that helper on the server, so the canvas label reads "Engineering", and the
  name is folded into the facet's `content_hash`: `GraphDiff` re-pushes a node to d3 only when its
  hash moves (`Sync/GraphDiff.swift:64`), so without it an existing satellite would keep its old
  lowercase label on the canvas until its subject changed. A satellite
  has no page, so `ClaimContext.cardTarget(for:in:)` opens its `parentId`'s card. That fixes the
  empty card the owner clicked.
- **R-FX4 — Papers write `general`.** The brief's candidates were `research`, `education` and
  `engineering`; all three are declined. A watched folder declares no life-area, so
  `engineering` is a guess that files a reading list on any other subject under the owner's
  engineering self.
  `research` and `education` would coin words no other writer uses and the owner never chose. Every
  other deterministic writer says `general` (see the anchors above). Nothing is lost: the section
  already lives in `paper.sections`, in the page's tags (`papers.py:288`, `:317`) and in the paper
  card's heading (`detail()`'s `_heading_above`). *Trigger to revisit:* a per-folder context the
  owner picks in the folder sheet. Papers would then take it.
- **R-FX5 — Paper claim ids never change; supersession stays exact.** The id is derived from a
  **slot**, the exact string that used to be written as the context
  (`folder:<id>:<section>` for `saved-because`, `general` otherwise). So every id minted before this
  track is minted again unchanged, and no claim is closed and reopened by the next sync. Re-minting
  is declined because ids are referenced by `superseded_by`, telemetry refs and inbox items. Once
  every paper claim says `general`, "same predicate + same context" can no longer tell two sections'
  notes apart. The successor is therefore found by recomputing the closed claim's id over each
  desired claim's slot (`_same_slot`), which is as exact as the old rule.
- **R-FX6 — Both repairs run, belt and braces.** (a) At **startup and bank activation**, through
  `bank_migrations`, the house pattern. It is marker-guarded, commits only the rewritten paths, and
  is authored `cicada`. It is not left to the next folder sync because a file nobody edits is never
  re-read. Unlike `export_origin_migration`, one page that cannot be read or written never stops
  the rest, what did land is still committed as `cicada` (left dirty, it would ride the next
  `git add -A` under another author — the G85-class smear), and any such failure keeps the marker
  off so the next start retries. The paper repair holds `folder_source._LOCK` through its commit,
  so a folder sync cannot slip its own rows into the `graph_edges.yaml` it commits. (b) `apply_claims` also takes the writer's context on an id it already has, so a sync
  repairs whatever it re-reads (a bank restored from before the marker, a hand edit).
- **R-FX7 — The folder writer projects its own claims' edges; `graph_edges.yaml` stays the one
  edge source.** `graph_builder.upsert_claim_edges(memory_path, page_ids)` rewrites the
  claim-derived rows of exactly those pages: the rows it owns are the ones whose `claim_id` is a
  claim on one of them (open or closed, so a closed claim's row goes), replaced by their open
  node-valued claims. That is Stage 5.7's merge rule at page granularity, and it uses the same
  `_claim_edge_row` that `regenerate_edges_from_claims` now uses, so the next Sleep's Stage 5.7
  rewrites identical rows. Owning rows by *source* instead was declined: a claim whose `subject`
  is not its page's stem would have its row dropped until the next cycle. It is idempotent (it
  writes nothing when the rows already match) and never rewrites a file it could not parse. Projecting every claim edge at read time in `build_graph` is **declined**: `degree`,
  hub gravity and every node's `content_hash` are computed before claims are parsed, and doing it
  there would change the graph for every writer at once. The paper migration projects every
  existing paper once. *Disclosed, pre-existing:* `entity_merge.py:104` also writes this file,
  outside the folder lock.
- **R-FX8 — The fence's canonical position is after the last section, and every reader strips it
  first.** The brief says "its own section, as Sleep-written pages do". **Verified false:**
  `write_claims` appends after the last section on every page, Sleep's included. A claims heading
  would render as an empty section in every reader that already hides the fence. So the fence stays
  where the one writer puts it. The fix is the readers: app `EntityProse` (Summary box, body, media
  description, Feed sheet) and server (`graph_builder.summarize`, `_build_media_block`,
  `hub_builder._one_line_summary`). The Source view keeps showing the file verbatim: it *is* the
  file, and that is the transparency principle.
- **R-FX9 — `agentic_write` never writes a placeholder.** A page it creates opens with
  `entity_body.summary_line(claim_text, predicate=…)`. This is deterministic and uses no LLM. A
  hyphenated predicate token reads as words ("depends-on" → "depends on"). The first letter is
  capitalised only when the first word is all lowercase, so `iOS` is left alone. A terminal period
  is added. Later claims never rewrite it; Sleep's prose takes over when the subject is consolidated.
- **R-FX10 — The placeholder migration touches exactly the placeholder pages.** It runs only on
  non-`media` pages whose Summary, after stripping the fence, is **one line** matching
  `^.+ — created via agentic write\.$`, and which have **at least one open claim**. The new Summary
  joins the first ≤ 3 open claims' sentences, in page order, deduplicated, capped at 240 chars.
  Frontmatter is untouched: no `version` bump and no `last_referenced`, because a repair is not a
  mention. The claims list round-trips unchanged and lands where `write_claims` puts it (R-FX8). A
  page with no open claim keeps its line, and the app hides that line (R-FX11). Marker:
  `.placeholder_summaries_v1`.
- **R-FX11 — "What Cicada knows".** It applies to a full (not stub) non-`media` entity whose prose,
  after the fence is stripped, is at most a `## Summary`. The Content tab's rendered mode then lists
  the page's open claims with the Perspectives tab's `ClaimChip`, so a belief looks the same
  everywhere. Claims load only when that holds, so the graph-node stub never fetches. A Summary that
  is still the placeholder is hidden rather than shown.
- **R-FX12 — The display face is the system face.** `displayFont(size:italic:)` is kept. Roman is
  **semibold** SF, `.system(size:weight:.semibold,design:.default)`. Italic is **regular** SF
  italic, the quiet second line of a headline. Roman titles also carry
  `.tracking(displayTracking(size:))` = −2 % of the scaled size. `Font` cannot carry tracking, so
  call sites pair the two, and `FontLiteralLintTests` counts roman calls against tracking calls per
  file. Italic keeps SF's own spacing, because tightened italic reads cramped. The 22 pt floor stays
  as a *role* rule (display is for titles), not a hairline rule. Sizes do not change. Because SF is
  about 30 % wider (measured above), `PageHeader`'s title becomes `lineLimit(1)` +
  `minimumScaleFactor(0.8)`. `CicadaFonts`, the TTFs, `OFL.txt`, `FONTS.md` and `CicadaFontsTests`
  are deleted, because nothing else needs registration. A new lint fails the build if a font file
  appears under `Resources/`. `quoteFont` (New York italic) is unchanged.
- **R-FX13 — The Sleep sentence gets exactly Z10's font swap, plus tracking.** `RoomSentence.swift`
  `:325` becomes `CicadaTheme.displayFont(size: 30)` plus its tracking line, `:404` becomes
  `CicadaTheme.displayFont(size: 22, italic: true)`, and the stale docstring at `:286-287` is
  rewritten. Nothing else in `Views/Sleep/` changes. Z10 rewrites the same two calls, but its plan
  spells the lead `displayFont(size: Self.leadSize)` and pins that exact text in a test, so on a
  merge against `feat/mascot-page-b` keep **its** spelling and pair
  `.tracking(CicadaTheme.displayTracking(size: Self.leadSize))` (Merge notes). The brief requires
  the italic line to be SF, which is why this is not left to Z10.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/claim_contexts.py` (new) | `NO_CONTEXT`, `is_valid`, `is_facet`, `display_name` (R-FX1/2/3) |
| `api/tests/fixtures/claim_contexts.json` (new) | one table both sides read |
| `api/services/graph_builder.py` | valid-only overlay, real-context facets with readable names (T1); `_claim_edge_row`, `upsert_claim_edges` (T2); `summarize` strips the fence (T3) |
| `app/…/Models/ClaimContext.swift` (new) | `isValid`, `displayName`, `roster(nodes:links:)`, `cardTarget(for:in:)` |
| `app/…/ViewModels/GraphViewModel.swift` | roster via `ClaimContext.roster`, selection via `cardTarget` (two lines) |
| `app/…/Views/Graph/ContextLegend.swift`, `app/…/Views/Common/ClaimChip.swift` | readable names |
| `api/services/papers.py` | `PAPER_CONTEXT`, slot-derived ids, `_same_slot`, context self-heal, edges on reconcile (T2) |
| `api/services/paper_context_migration.py` (new) | one-shot repair + edge projection (T2) |
| `api/services/bank_migrations.py` | wires both migrations (T2, T4) |
| `api/routers/entities.py`, `api/services/hub_builder.py` | strip the fence before sectioning (T3) |
| `app/…/Views/Graph/EntityProse.swift` (new) | fence strip + section readers + placeholder/thin-page rules (T3) |
| `app/…/Views/Graph/WhatCicadaKnowsSection.swift` (new) | the beliefs list (T3) |
| `app/…/Theme/Copy+Beliefs.swift` (new) | its copy, in its own file (the `Copy+Intake.swift` precedent) (T3) |
| `app/…/Views/Graph/EntityDetailCard.swift`, `app/…/Views/Feed/FeedView.swift` | read through `EntityProse`; show the beliefs list (T3) |
| `api/services/entity_body.py` | `summary_line`, `summary_from_claims` (T4) |
| `api/services/agentic_write.py` | first Summary from the claim text (T4) |
| `api/services/placeholder_summary_migration.py` (new) | one-shot rewrite of placeholder pages (T4) |
| `app/…/Theme/CicadaTheme.swift`, `app/…/CicadaApp.swift`, `PageHeader.swift`, `EmptyStateView.swift`, `ReaderInspector.swift`, `RoomSentence.swift` | SF display face + tracking (T5) |
| deleted: `Theme/CicadaFonts.swift`, `Resources/fonts/*`, `Tests/…/CicadaFontsTests.swift` | (T5) |
| Tests (Python) | `test_claim_contexts.py`, `test_paper_context_migration.py`, `test_claims_fence_readers.py`, `test_entity_body_summary_line.py`, `test_placeholder_summary_migration.py` (new); edits to `test_papers.py`, `test_claim_edge_regen.py`, `test_agentic_write.py` |
| Tests (Swift) | `ClaimContextTests.swift`, `EntityProseTests.swift`, `DisplayFontTests.swift` (new); `FontLiteralLintTests.swift` edited |
| Docs | `CLAUDE.md`, `docs/goals/memory-evolution.md` (G24, G133, G137), `docs/goals/TODO.md`, one amendment line in the round-3 spec (T6) |

`app/…` = `app/CicadaApp/Sources/CicadaApp`.

---

### Task 1: Real contexts only — no junk satellites, a readable legend, a facet opens its subject (R-FX1 · R-FX2 · R-FX3)

This is read-side only and changes no file in any bank. After this commit the live graph stops
serving the junk satellites even before Task 2's repair runs.

**Files:**
- Create: `api/services/claim_contexts.py`, `api/tests/fixtures/claim_contexts.json`, `api/tests/test_claim_contexts.py`
- Modify: `api/services/graph_builder.py:10` (import), `:152-157`, `:300-335`
- Create: `app/CicadaApp/Sources/CicadaApp/Models/ClaimContext.swift`, `app/CicadaApp/Tests/CicadaAppTests/ClaimContextTests.swift`
- Modify: `app/…/ViewModels/GraphViewModel.swift:199-203` and `:506-507`; `app/…/Views/Graph/ContextLegend.swift:73`; `app/…/Views/Common/ClaimChip.swift:111`

**Interfaces:**
- Produces `claim_contexts.NO_CONTEXT`, `.MAX_LENGTH`, `.is_valid(ctx)`, `.is_facet(ctx)`, `.display_name(ctx)`; Swift `ClaimContext.isValid(_:)`, `.displayName(_:)`, `.roster(nodes:links:)`, `.cardTarget(for:in:)`.
- Consumes `GraphNode` / `GraphEdge` (Swift), `Claim` (Python). Task 2 consumes `NO_CONTEXT`.

- [ ] **Step 1: The shared fixture** — `api/tests/fixtures/claim_contexts.json`:

```json
{
  "cases": [
    {"context": "general", "valid": true, "facet": false, "display": "General"},
    {"context": "engineering", "valid": true, "facet": true, "display": "Engineering"},
    {"context": "family", "valid": true, "facet": true, "display": "Family"},
    {"context": "machine-learning", "valid": true, "facet": true, "display": "Machine learning"},
    {"context": "q3-planning", "valid": true, "facet": true, "display": "Q3 planning"},
    {"context": "folder:f0a1b2:reading-list", "valid": false, "facet": false, "display": null},
    {"context": "as of 2026-05-01", "valid": false, "facet": false, "display": null},
    {"context": "Engineering", "valid": false, "facet": false, "display": null},
    {"context": "two words", "valid": false, "facet": false, "display": null},
    {"context": "", "valid": false, "facet": false, "display": null},
    {"context": "-lead", "valid": false, "facet": false, "display": null},
    {"context": "trail-", "valid": false, "facet": false, "display": null},
    {"context": "a--b", "valid": false, "facet": false, "display": null},
    {"context": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "valid": false, "facet": false, "display": null}
  ]
}
```

(The last value is 33 characters.)

- [ ] **Step 2: Failing Python tests** — `api/tests/test_claim_contexts.py`:

```python
"""F1 (R-FX1 … R-FX3) — what a claim context may be, and which ones the graph shows.

The owner's live graph served two satellites per annotated paper, named after a
raw folder id and `general`, and the legend listed the raw id as a context. The
table is shared with the app (`ClaimContextTests.swift`), so a rule changed on
one side only turns the other red."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from api.services import bank_index, claim_contexts, markdown_parser
from api.services.claims import Claim, write_claims
from api.services.graph_builder import build_graph

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "claim_contexts.json").read_text(encoding="utf-8"))["cases"]


@pytest.fixture(autouse=True)
def _fresh_index():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


def test_the_fixture_is_not_vacuous():
    assert len(FIXTURE) >= 12


@pytest.mark.parametrize("case", FIXTURE, ids=lambda c: c["context"] or "<empty>")
def test_the_shared_table(case):
    assert claim_contexts.is_valid(case["context"]) is case["valid"]
    assert claim_contexts.is_facet(case["context"]) is case["facet"]
    if case["display"] is not None:
        assert claim_contexts.display_name(case["context"]) == case["display"]


def _entity(memory_path, stem, contexts, *, type_="concept"):
    entities = memory_path / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    claims = [Claim(id=f"{stem}-c{i}", text=f"fact {i}", subject=stem, predicate="notes",
                    object=f"o{i}", object_kind="literal", context=ctx) for i, ctx in enumerate(contexts)]
    markdown_parser.write(entities / f"{stem}.md", {"name": stem.replace("-", " ").title(), "type": type_},
                          write_claims("## Summary\nA page.", claims))


def test_general_is_never_a_facet_dimension(tmp_path):
    _entity(tmp_path, "alpha-project", ["engineering", "general"])
    assert [n.id for n in build_graph(tmp_path).nodes if n.is_facet] == []


def test_two_real_contexts_still_split_and_general_stays_on_the_parent(tmp_path):
    _entity(tmp_path, "bob-example", ["engineering", "family", "general"])
    graph = build_graph(tmp_path)
    facets = {n.id: n for n in graph.nodes if n.is_facet}
    assert sorted(facets) == ["bob-example#engineering", "bob-example#family"]
    assert facets["bob-example#engineering"].name == "Engineering"
    assert facets["bob-example#engineering"].context == "engineering"
    parent = next(n for n in graph.nodes if n.id == "bob-example")
    assert parent.contexts == ["engineering", "family", "general"]


def test_a_value_that_is_not_a_context_never_reaches_the_graph(tmp_path):
    _entity(tmp_path, "media-arxiv-2401-00001", ["folder:f0a1b2:reading-list", "general"], type_="media")
    # G60's "both" answer writes `as of <date>` to keep two claims apart — still
    # a key, never a satellite.
    _entity(tmp_path, "gamma-project", ["as of 2026-05-01", "as of 2026-06-01"])
    graph = build_graph(tmp_path)
    assert [n.id for n in graph.nodes if n.is_facet] == []
    assert not any(n.name.startswith("folder:") for n in graph.nodes)
    by_id = {n.id: n for n in graph.nodes}
    assert by_id["media-arxiv-2401-00001"].contexts == ["general"]
    assert by_id["gamma-project"].contexts == []


def test_an_edge_whose_claim_has_no_real_context_carries_none(tmp_path):
    entities = tmp_path / "entities"
    entities.mkdir(parents=True)
    claim = Claim(id="c1", text="Cited in Alpha Project.", subject="media-arxiv-2401-00001",
                  predicate="cited-in", object="alpha-project", context="folder:f0a1b2:reading-list")
    markdown_parser.write(entities / "media-arxiv-2401-00001.md", {"name": "Paper Alpha", "type": "media"},
                          write_claims("## Summary\nSaved paper — Paper Alpha.", [claim]))
    markdown_parser.write(entities / "alpha-project.md", {"name": "Alpha Project", "type": "project"},
                          "## Summary\nA project.")
    (tmp_path / "graph_edges.yaml").write_text(yaml.dump({"edges": [
        {"source": "media-arxiv-2401-00001", "target": "alpha-project", "label": "cited-in"}]}),
        encoding="utf-8")
    (link,) = [l for l in build_graph(tmp_path).links if l.label == "cited-in"]
    assert link.claim_id == "c1" and link.context is None
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_claim_contexts.py -q -p no:cacheprovider`.
Expected: a collection error (`claim_contexts` does not exist). That is the red.

- [ ] **Step 3: Implement** — `api/services/claim_contexts.py`:

```python
"""What a claim ``context`` may be, and which ones the graph shows (F1, owner review 2026-09-23).

A claim's ``context`` is the middle term of its ``(observer, context, subject)``
key (d2-architecture-final §2): which part of a life a belief belongs to — the
engineer-self and the family-self hold different beliefs without contradicting
each other. The vocabulary is **open** by design (d2 says "OPEN";
``Claim.context``'s own comment; the MCP schema offers examples, not an enum),
so an agent may coin ``health`` and this module never closes it (R-FX1).

What it pins is the *shape* the graph can show. The owner's live graph served
two satellites per annotated paper, one named after a raw
``folder:<id>:<section>`` value and one ``general``: a paper writer had put a
location into the context field, and the
M5b facet rule (one satellite per context once a subject has two) did the rest.
Two rules close that class for every writer, not only papers:

* **A context is a short lowercase slug** (:func:`is_valid`). Anything else —
  a ``folder:`` id, the inbox's ``as of <date>`` qualifier (G60, which keeps two
  answers apart in the claim key and must keep doing so) — still works as a
  key, but is never a facet, a legend row or an edge colour.
* **``general`` is "no particular context"** (:func:`is_facet`, R-FX2). Every
  deterministic writer says it (Stage 1 ``entity_extractor``,
  ``link_enrichment``, ``link_recon``, ``paper_metadata``, ``claim_seeder``, and
  since F1 ``papers``) and ``Claim.context`` defaults to it — d2 calls it the
  extraction special case. A subject whose claims split between ``general`` and
  one real context has one perspective, not two. It still colours and filters
  as a context, so the legend keeps it.

The Swift twin is ``Models/ClaimContext.swift``; both read
``api/tests/fixtures/claim_contexts.json``.
"""

from __future__ import annotations

import re

NO_CONTEXT = "general"
MAX_LENGTH = 32
_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def is_valid(context: object) -> bool:
    """A short lowercase slug: ``engineering``, ``machine-learning``, ``q3-planning``."""
    return isinstance(context, str) and 0 < len(context) <= MAX_LENGTH and bool(_SLUG.match(context))


def is_facet(context: object) -> bool:
    """A context the graph may split a subject on: valid, and not ``general``."""
    return is_valid(context) and context != NO_CONTEXT


def display_name(context: str) -> str:
    """``machine-learning`` → ``Machine learning``; a value that is not a context comes back as is."""
    if not is_valid(context):
        return context
    spaced = context.replace("-", " ")
    return spaced[:1].upper() + spaced[1:]
```

`graph_builder.py`. First, the import at `:10`:
`from api.services import bank_index, claim_contexts, decay_policy, logo_service, predicates`. Then,
inside the per-page claim loop, replace the `if claim.context:` and
`if claim.predicate and claim.object:` blocks (`:152-157`; the `valid_to` and `observer` lines
above them stay) with:

```python
                if claim_contexts.is_valid(claim.context):
                    subject_contexts.setdefault(eid, set()).add(claim.context)
                if claim.predicate and claim.object:
                    # F1 R-FX1: a value that is not a context (a `folder:` id,
                    # G60's `as of <date>`) never colours an edge.
                    edge_claim_index.setdefault(
                        (eid, claim.predicate, claim.object),
                        (claim.id, claim.context if claim_contexts.is_valid(claim.context) else None),
                    )
```

Next, the facet block (`:300-334`, from the `# M5b: facet sub-nodes` comment through the
`facet_links.append(...)` call; `nodes.extend(facet_nodes)` at `:335` stays). Replace it with:

```python
    # M5b: facet sub-nodes for a subject whose claims sit in >= 2 REAL contexts
    # (d2 §2c). F1 R-FX2: `general` is "no particular context" and a non-slug
    # value is not a context at all (claim_contexts), so neither is ever a
    # satellite — the owner's graph had two per annotated paper, one named after
    # a raw folder id. Each satellite is `id: "<subject>#<context>"`,
    # parentId=<subject>, joined to the parent by a short `facetOf` edge routed
    # through the existing node-click channel (the app opens the parent, R-FX3).
    facet_nodes: list[GraphNode] = []
    facet_links: list[GraphLink] = []
    node_by_id = {n.id: n for n in nodes}
    for subject, contexts in subject_contexts.items():
        facets = sorted(c for c in contexts if claim_contexts.is_facet(c))
        if len(facets) < 2 or subject not in node_by_id:
            continue
        parent = node_by_id[subject]
        for ctx in facets:
            name = claim_contexts.display_name(ctx)
            facet_nodes.append(
                GraphNode(
                    id=f"{subject}#{ctx}",
                    name=name,
                    type=parent.type,
                    status=parent.status,
                    confidence=parent.confidence,
                    is_facet=True,
                    parent_id=subject,
                    context=ctx,
                    # Facets are synthetic too — derived from the parent's
                    # claim contexts, with no file of their own. Fold the
                    # parent's own hash in so a facet moves when its subject
                    # does. (Same empty-hash re-push problem as hub:/repo:.)
                    # F1 R-FX3: the display name is folded in as well —
                    # `GraphDiff` re-pushes a node only when its hash moves, so
                    # the relabel ("engineering" → "Engineering") must move it.
                    content_hash=synthetic_hash(
                        "facet", subject, ctx, name, parent.type, parent.status,
                        parent.confidence, parent.content_hash,
                    ),
                )
            )
            facet_links.append(
                GraphLink(source=f"{subject}#{ctx}", target=subject, label="facetOf", context=ctx)
            )
```

Also update `edge_claim_index`'s annotation (`:121`) to `dict[tuple[str, str, str], tuple[str, str | None]]`.

- [ ] **Step 4: Python green** — the Step 2 command passes. Then run
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_graph_claim_overlay.py api/tests/test_graph_builder.py api/tests/test_claim_endpoints.py -q -p no:cacheprovider`.
  The engineering/family and career/personal satellites in those tests survive unchanged.

- [ ] **Step 5: Failing Swift tests** — `app/CicadaApp/Tests/CicadaAppTests/ClaimContextTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// F1 (R-FX1, R-FX3) — the app's half of `api/services/claim_contexts.py`,
/// held to the same table (`api/tests/fixtures/claim_contexts.json`). The
/// owner's Graph legend listed a raw folder id as a context, and a click on a
/// satellite opened an empty card.
final class ClaimContextTests: XCTestCase {
    private struct Case: Decodable {
        let context: String
        let valid: Bool
        let display: String?
    }
    private struct Fixture: Decodable { let cases: [Case] }

    private func fixture() throws -> [Case] {
        // …/Tests/CicadaAppTests/<this file> → …/CicadaApp → …/app → repo root
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/claim_contexts.json")
        let cases = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: file)).cases
        XCTAssertGreaterThanOrEqual(cases.count, 12, "a table test over 0 rows passes vacuously")
        return cases
    }

    func testTheSharedTable() throws {
        for c in try fixture() {
            XCTAssertEqual(ClaimContext.isValid(c.context), c.valid, c.context)
            if let display = c.display {
                XCTAssertEqual(ClaimContext.displayName(c.context), display, c.context)
            }
        }
    }

    func testTheLegendListsOnlyRealContexts() {
        let nodes = [
            GraphNode(id: "media-arxiv-2401-00001", name: "Paper Alpha", type: .media,
                      contexts: ["general", "folder:f0a1b2:reading-list"]),
            GraphNode(id: "bob-example#engineering", name: "Engineering", type: .person,
                      isFacet: true, parentId: "bob-example", context: "engineering"),
        ]
        let links = [GraphEdge(source: "media-arxiv-2401-00001", target: "alpha-project",
                               label: "cited-in", context: "as of 2026-05-01")]
        XCTAssertEqual(ClaimContext.roster(nodes: nodes, links: links), ["engineering", "general"])
    }

    func testASatelliteClickOpensItsSubjectsCard() {
        let nodes = [
            GraphNode(id: "bob-example", name: "Bob Example", type: .person),
            GraphNode(id: "bob-example#family", name: "Family", type: .person,
                      isFacet: true, parentId: "bob-example", context: "family"),
        ]
        XCTAssertEqual(ClaimContext.cardTarget(for: "bob-example#family", in: nodes), "bob-example")
        XCTAssertEqual(ClaimContext.cardTarget(for: "bob-example", in: nodes), "bob-example")
        XCTAssertEqual(ClaimContext.cardTarget(for: "not-loaded#x", in: nodes), "not-loaded#x")
    }
}
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter ClaimContextTests 2>&1 | tail -20`.
Expected: a compile failure. That is the red.

- [ ] **Step 6: Implement** — `app/CicadaApp/Sources/CicadaApp/Models/ClaimContext.swift`:

```swift
import Foundation

/// The app's copy of `api/services/claim_contexts.py` (F1, owner review
/// 2026-09-23). A claim's context is an OPEN vocabulary (d2 §2) whose shape is
/// a short lowercase slug; anything else — a raw folder id a paper writer once
/// stored there, the inbox's `as of <date>` qualifier (G60) — keeps its job
/// as a claim key but is never a legend row (R-FX1). Both sides read
/// `api/tests/fixtures/claim_contexts.json`, so a rule changed on one side
/// only turns the other red.
enum ClaimContext {
    static let maxLength = 32

    static func isValid(_ context: String) -> Bool {
        guard !context.isEmpty, context.count <= maxLength else { return false }
        return context.range(of: #"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"#, options: .regularExpression) != nil
    }

    /// `machine-learning` → "Machine learning" (R-FX3). A value that is not a
    /// context is shown as it is: a `ContextPill` on a G60 claim reads
    /// "as of 2026-05-01", which is already words.
    static func displayName(_ context: String) -> String {
        guard isValid(context) else { return context }
        let spaced = context.replacingOccurrences(of: "-", with: " ")
        return spaced.prefix(1).uppercased() + spaced.dropFirst()
    }

    /// The Graph legend's rows: every context a node, a satellite or an edge
    /// carries, minus anything that is not a context, sorted.
    static func roster(nodes: [GraphNode], links: [GraphEdge]) -> [String] {
        var all = Set(nodes.flatMap(\.contexts))
        for node in nodes { if let c = node.context { all.insert(c) } }
        for link in links { if let c = link.context { all.insert(c) } }
        return all.filter(isValid).sorted()
    }

    /// A satellite (`bob-example#family`) is a view of its subject and has no
    /// page of its own — selecting it fetched `/entities/<id>#<ctx>` and opened
    /// an empty card (the owner's report). It opens its subject instead.
    static func cardTarget(for id: String, in nodes: [GraphNode]) -> String {
        nodes.first { $0.id == id && $0.isFacet }?.parentId ?? id
    }
}
```

`GraphViewModel.swift:200-203` (inside `syncFromStore`'s non-empty branch): replace the four roster
lines (`var ctxs = …` through `contextRoster = ctxs.sorted()`) with:

```swift
        // F1 R-FX3 — real contexts only; see `ClaimContext`.
        contextRoster = ClaimContext.roster(nodes: response.nodes, links: response.links)
```

`GraphViewModel.swift:506-507`: make the first line of `applySelection(id:)` resolve the target:

```swift
    private func applySelection(id: String) {
        let id = ClaimContext.cardTarget(for: id, in: nodes)
        if let existing = entities.first(where: { $0.id == id }) {
```

`ContextLegend.swift:73`: `Text(context)` → `Text(ClaimContext.displayName(context))`.
`ClaimChip.swift:111`: `Text(context)` → `Text(ClaimContext.displayName(context))`.

- [ ] **Step 7: Green** — `swift build 2>&1 | tail -5` succeeds, `swift test 2>&1 | tail -20` reports 0
  failures, `node --test app/CicadaApp/Tests/graph/*.test.js` passes, and the full `api/tests` is 0
  failures.
- [ ] **Step 8: Commit** — stage by name the six source files (`api/services/claim_contexts.py`,
  `api/services/graph_builder.py`, `Models/ClaimContext.swift`, `ViewModels/GraphViewModel.swift`,
  `Views/Graph/ContextLegend.swift`, `Views/Common/ClaimChip.swift`), the fixture
  `api/tests/fixtures/claim_contexts.json`, and the two test files
  (`api/tests/test_claim_contexts.py`, `Tests/CicadaAppTests/ClaimContextTests.swift`). Message:
  `fix(graph): real contexts only — no satellites for general or a raw id, readable legend, a satellite opens its subject (F1 R-FX1..3)`.

---

### Task 2: Papers — the house context, the same ids, an edge to their project, and a one-shot repair (R-FX4 · R-FX5 · R-FX6 · R-FX7)

**Files:**
- Modify: `api/services/papers.py` (imports `:43-53`; constants after `WHY_PREDICATES` `:59`; `desired_claims` `:344-381`; `apply_claims` `:384-433`; `_reconcile_locked` `:574-646`)
- Modify: `api/services/graph_builder.py:397-485` (extract `_claim_edge_row`, add `upsert_claim_edges`)
- Create: `api/services/paper_context_migration.py`, `api/tests/test_paper_context_migration.py`
- Modify: `api/services/bank_migrations.py:26-94`
- Modify: `api/tests/test_papers.py` (new tests; import `write_claims`, `yaml`, `build_graph`), `api/tests/test_claim_edge_regen.py` (new tests)

**Interfaces:**
- Produces `papers.PAPER_CONTEXT`, `papers._same_slot(old, new)`, `graph_builder.upsert_claim_edges(memory_path, page_ids) -> bool`, `graph_builder._claim_edge_row(claim, page_stem)`, `graph_builder._row_key(row)`, `paper_context_migration.repair_paper_contexts(memory_path) -> {"pages", "claims", "edges"}`, and `run_bank_migrations(...)["paper_contexts"]`.
- Consumes `claim_contexts.NO_CONTEXT` (Task 1), `folder_source._LOCK`, `bank_index.files`, `git_service.build_commit_message`.

- [ ] **Step 1: Failing tests.** In `api/tests/test_papers.py`, change the imports to
  `from api.services.claims import parse_claims, write_claims` and add `import yaml` and
  `from api.services.graph_builder import build_graph`. Then append:

```python
def test_paper_claims_say_general_and_keep_the_ids_they_always_had(bank):
    """R-FX4/R-FX5 — the context is the house word; the id still names the slot."""
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    claims = _claims(bank, "media-arxiv-2401-00001")
    assert {c.context for c in claims} == {"general"}
    note = "the architecture alpha-project builds on"
    saved = {c.object: c for c in claims if c.predicate == "saved-because"}
    assert saved[note].id == papers.claim_id(
        "media-arxiv-2401-00001", "saved-because", note, "owner", f"folder:{folder['id']}:retrieval")


def test_editing_the_second_sections_note_supersedes_its_own_claim_not_its_sibling(bank):
    """R-FX5 — with every note in `general`, only the slot tells two sections apart."""
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    edited = REFERENCES.replace("reused for the eval baseline", "the baseline we compare against")
    _sync(bank, folder, [_file("REFERENCES.md", edited, mtime=1_756_100_000.0)])
    saved = {c.object: c for c in _claims(bank, "media-arxiv-2401-00001") if c.predicate == "saved-because"}
    old, new = saved["reused for the eval baseline"], saved["the baseline we compare against"]
    assert old.valid_to and old.superseded_by == new.id and new.valid_to is None
    assert saved["the architecture alpha-project builds on"].valid_to is None


def test_a_sync_repairs_a_pre_f1_context_on_a_claim_it_re_reads(bank):
    """R-FX6(b) — the writer's context wins on an id it already has."""
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    page = bank / "entities" / "media-arxiv-2401-00001.md"
    parsed = markdown_parser.parse(page)
    legacy = parse_claims(parsed.body, strict=True)
    for c in legacy:
        if c.predicate == "saved-because":
            c.context = f"folder:{folder['id']}:retrieval"
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, legacy))
    _sync(bank, folder, [_file("REFERENCES.md", "Intro.\n\n" + REFERENCES, mtime=1_756_100_000.0)])
    assert {c.context for c in _claims(bank, "media-arxiv-2401-00001")} == {"general"}


def test_a_folder_sync_puts_each_paper_by_the_project_that_cites_it(bank):
    """R-FX7 — the edges exist without waiting for a Sleep cycle, and no satellite."""
    markdown_parser.write(bank / "entities" / "retrieval.md", {"name": "Retrieval", "type": "concept"}, "## Summary\nx")
    folder = _folder(bank)
    report = _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    assert "graph_edges.yaml" in report["paths"]
    edges = yaml.safe_load((bank / "graph_edges.yaml").read_text(encoding="utf-8"))["edges"]
    pairs = {(e["source"], e["label"], e["target"]) for e in edges}
    assert ("media-arxiv-2401-00001", "cited-in", folder["project_id"]) in pairs
    assert ("media-arxiv-2401-00001", "about", "retrieval") in pairs
    bank_index.invalidate()
    graph = build_graph(bank)
    assert any(l.source == "media-arxiv-2401-00001" and l.target == folder["project_id"] for l in graph.links)
    assert not any(n.is_facet for n in graph.nodes)


def test_a_sync_that_changes_no_claim_leaves_the_edges_alone(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    edges = bank / "graph_edges.yaml"
    before = edges.read_bytes()
    report = _sync(bank, folder, [_file("REFERENCES.md", REFERENCES, mtime=1_756_100_000.0)])
    assert "graph_edges.yaml" not in report["paths"] and edges.read_bytes() == before


def test_a_deleted_file_takes_its_papers_edges_with_it(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    _sync(bank, folder, [], deleted=["REFERENCES.md"])
    edges = yaml.safe_load((bank / "graph_edges.yaml").read_text(encoding="utf-8"))["edges"]
    assert not any(e["source"] in ("media-arxiv-2401-00001", BETA) for e in edges)
```

In `api/tests/test_claim_edge_regen.py`, add
`from api.services.graph_builder import regenerate_edges_from_claims, upsert_claim_edges` and
append:

```python
def _edges(tmp_path):
    return yaml.safe_load((tmp_path / "graph_edges.yaml").read_text(encoding="utf-8"))["edges"]


def _paper(tmp_path, *, closed=False):
    _write_subject(tmp_path, "media-arxiv-2401-00001", "Paper Alpha", [
        Claim(id="clm_cited", text="Cited in Alpha Project.", subject="media-arxiv-2401-00001",
              predicate="cited-in", object="alpha-project", observer="owner",
              valid_to="2026-09-23" if closed else None),
        Claim(id="clm_why", text="why", subject="media-arxiv-2401-00001", predicate="saved-because",
              object="why", object_kind="literal", observer="owner"),
    ])


def test_upsert_projects_only_the_named_pages_and_keeps_every_other_row(tmp_path):
    _paper(tmp_path)
    kept = [
        {"source": "bob-example", "target": "alpha-project", "label": "mentions"},
        {"source": "bob-example", "target": "sqlite-vec", "label": "uses", "observer": "agent",
         "context": "general", "claim_id": "clm_bob", "valid_from": None},
    ]
    (tmp_path / "graph_edges.yaml").write_text(yaml.dump({"edges": kept}), encoding="utf-8")
    assert upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001"]) is True
    assert _edges(tmp_path) == kept + [{
        "source": "media-arxiv-2401-00001", "target": "alpha-project", "label": "cited-in",
        "observer": "owner", "context": "general", "claim_id": "clm_cited", "valid_from": None,
    }]  # the literal `saved-because` is not an edge


def test_upsert_is_idempotent_and_drops_a_closed_claims_row(tmp_path):
    _paper(tmp_path)
    assert upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001"]) is True
    before = (tmp_path / "graph_edges.yaml").read_bytes()
    assert upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001"]) is False
    assert (tmp_path / "graph_edges.yaml").read_bytes() == before
    _paper(tmp_path, closed=True)
    assert upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001"]) is True
    assert _edges(tmp_path) == []


def test_upsert_writes_the_rows_the_full_regeneration_writes(tmp_path):
    """R-FX7 — Sleep's Stage 5.7 later rewrites the same rows, not different ones."""
    _paper(tmp_path)
    _write_subject(tmp_path, "cicada", "Cicada", [
        Claim(id="clm_1", text="uses sqlite-vec", subject="cicada", predicate="uses",
              object="sqlite-vec", observer="agent", context="engineering", valid_from="2026-01-01")])
    upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001", "cicada"])
    ours = sorted(map(str, _edges(tmp_path)))
    (tmp_path / "graph_edges.yaml").unlink()
    regenerate_edges_from_claims(tmp_path)
    assert sorted(map(str, _edges(tmp_path))) == ours


def test_upsert_never_rewrites_a_file_it_could_not_read(tmp_path):
    _paper(tmp_path)
    (tmp_path / "graph_edges.yaml").write_text("edges: [unclosed", encoding="utf-8")
    assert upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001"]) is False
    assert (tmp_path / "graph_edges.yaml").read_text(encoding="utf-8") == "edges: [unclosed"


def test_upsert_owns_rows_by_claim_not_by_source(tmp_path):
    """R-FX7 — a row another page's claim projected keeps its place even when
    its source is one of the named pages; Stage 5.7 would write it too."""
    _paper(tmp_path)
    other = {"source": "media-arxiv-2401-00001", "target": "gamma-project", "label": "mentions",
             "observer": "agent", "context": "general", "claim_id": "clm_elsewhere", "valid_from": None}
    (tmp_path / "graph_edges.yaml").write_text(yaml.dump({"edges": [other]}), encoding="utf-8")
    assert upsert_claim_edges(tmp_path, ["media-arxiv-2401-00001"]) is True
    assert other in _edges(tmp_path)
```

Create `api/tests/test_paper_context_migration.py`:

```python
"""F1 (R-FX4, R-FX6, R-FX7) — the one-shot repair of pre-F1 folder-paper contexts."""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path

import yaml

from api.services import bank_index, bank_migrations, folder_source as fs, markdown_parser, papers
from api.services import paper_context_migration as mig
from api.services.claims import parse_claims, write_claims

REFERENCES = """# References

## Retrieval

- [Paper Alpha](https://arxiv.org/abs/2401.00001v2) — the architecture alpha-project builds on
- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it
"""
ALPHA = "media-arxiv-2401-00001"
BETA = papers.PaperKey(doi="10.1234/example.5678").entity_id


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _bank(tmp_path: Path) -> tuple[Path, dict]:
    """A git bank holding two papers in the pre-F1 shape: the folder and section
    in `saved-because`'s context, and no projected edges."""
    bank = tmp_path / "bank"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@cicada.local")
    _git(bank, "config", "user.name", "Cicada Test")
    project_id, _ = fs.ensure_project(bank, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    folder = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         project_id=project_id)
    bank_index.invalidate()
    staged = fs.sync(bank, folder, [_file("REFERENCES.md", REFERENCES)], [])["_staged"]
    papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched=staged.touched,
                     tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)
    for stem in (ALPHA, BETA):
        page = bank / "entities" / f"{stem}.md"
        parsed = markdown_parser.parse(page)
        claims = parse_claims(parsed.body, strict=True)
        for c in claims:
            if c.predicate == "saved-because":
                c.context = f"folder:{folder['id']}:retrieval"
        markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    (bank / "graph_edges.yaml").unlink(missing_ok=True)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    bank_index.invalidate()
    return bank, fs.get_folder(bank, folder["id"])


def _claims(bank, stem):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{stem}.md").body)


def test_the_repair_moves_only_folder_contexts_and_keeps_every_id(tmp_path):
    bank, _ = _bank(tmp_path)
    ids_before = {c.id for s in (ALPHA, BETA) for c in _claims(bank, s)}
    report = mig.repair_paper_contexts(bank)
    assert (report["pages"], report["claims"], report["edges"]) == (2, 2, True)
    for stem in (ALPHA, BETA):
        assert {c.context for c in _claims(bank, stem)} == {"general"}
    assert {c.id for s in (ALPHA, BETA) for c in _claims(bank, s)} == ids_before


def test_the_repair_projects_the_papers_edges(tmp_path):
    bank, folder = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    edges = yaml.safe_load((bank / "graph_edges.yaml").read_text(encoding="utf-8"))["edges"]
    assert (ALPHA, "cited-in", folder["project_id"]) in {(e["source"], e["label"], e["target"]) for e in edges}


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_files(tmp_path):
    bank, _ = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        [f"entities/{ALPHA}.md", f"entities/{BETA}.md", "graph_edges.yaml"])


def test_it_runs_once(tmp_path):
    bank, _ = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    head = _git(bank, "rev-parse", "HEAD")
    assert mig.repair_paper_contexts(bank) == {"pages": 0, "claims": 0, "edges": False}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_second_pass_without_the_marker_changes_nothing(tmp_path):
    bank, _ = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    head = _git(bank, "rev-parse", "HEAD")
    (bank / ".paper_contexts_v1").unlink()
    assert mig.repair_paper_contexts(bank) == {"pages": 0, "claims": 0, "edges": False}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_full_reparse_after_the_repair_changes_no_claim(tmp_path):
    """R-FX5 — the writer mints the ids the repair left, so nothing closes or reopens."""
    bank, folder = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    bank_index.invalidate()
    assert papers.reparse_folder(bank, folder)["claims_changed"] == 0


def test_a_corrupt_claims_block_is_skipped_and_never_raises(tmp_path):
    bank, _ = _bank(tmp_path)
    page = bank / "entities" / f"{BETA}.md"
    parsed = markdown_parser.parse(page)
    fence = "`" * 3
    broken = parsed.body.split(fence + "claims")[0] + f"{fence}claims\n- id: [unclosed\n{fence}\n"
    markdown_parser.write(page, parsed.frontmatter, broken)
    before = page.read_bytes()
    report = mig.repair_paper_contexts(bank)
    assert report["pages"] == 1, "Alpha is repaired; Beta's corrupt block is skipped"
    assert page.read_bytes() == before


def test_a_page_that_cannot_be_written_keeps_the_marker_off_and_the_rest_is_committed(tmp_path, monkeypatch):
    """R-FX6 — one bad page never strands the others dirty for the next `git add -A`."""
    bank, _ = _bank(tmp_path)
    real = markdown_parser.write

    def flaky(path, frontmatter, body):
        if Path(path).stem == BETA:
            raise OSError("disk full")
        return real(path, frontmatter, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    assert mig.repair_paper_contexts(bank)["pages"] == 1
    assert not (bank / ".paper_contexts_v1").exists(), "the next start must retry Beta"
    assert _git(bank, "status", "--porcelain", "--", f"entities/{ALPHA}.md") == ""
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")


def test_bank_migrations_runs_the_repair(tmp_path):
    bank, _ = _bank(tmp_path)
    assert bank_migrations.run_bank_migrations(bank)["paper_contexts"]["pages"] == 2
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_papers.py api/tests/test_claim_edge_regen.py api/tests/test_paper_context_migration.py -q -p no:cacheprovider`.
Expected: red. There are import errors (`upsert_claim_edges`, `paper_context_migration`), and the
context and edge assertions fail.

- [ ] **Step 2: `graph_builder` — one row builder, two writers.** Above
  `regenerate_edges_from_claims`, add:

```python
def _claim_edge_row(claim, page_stem: str) -> dict | None:
    """One claim's row in ``graph_edges.yaml``, or ``None`` (M5e Stage 5.7's rule).

    Shared by :func:`regenerate_edges_from_claims` and :func:`upsert_claim_edges`
    so the full projection Sleep writes and the per-page one a folder sync writes
    can never disagree about a row's shape (F1 R-FX7). Only an open, node-valued
    claim is an edge; closed and superseded beliefs live on in the page and git."""
    if claim.valid_to is not None or claim.superseded_by:
        return None
    if claim.object_kind not in ("", "node"):
        return None
    source = (claim.subject or page_stem).strip()
    target = (claim.object or "").strip()
    label = (claim.predicate or "relates-to").strip()
    if not source or not target or source == target:
        return None
    return {
        "source": source,
        "target": target,
        "label": label,
        "observer": claim.observer or "agent",
        "context": claim.context or "general",
        "claim_id": claim.id,
        "valid_from": claim.valid_from,
    }


def _row_key(row: dict) -> tuple:
    return (row["source"], row["target"], row["label"], row["observer"], row["context"])
```

In `regenerate_edges_from_claims`, replace the body of the claim loop (from
`if claim.valid_to is not None …` through `claim_edges.append({…})`) with:

```python
        for claim in parse_claims(parsed.body):
            any_claims = True
            row = _claim_edge_row(claim, filepath.stem)
            if row is None or _row_key(row) in seen:
                continue
            seen.add(_row_key(row))
            claim_edges.append(row)
```

The output is byte-identical: same keys, same order. The dedup key moves from
`claim.observer or ""` / `claim.context or ""` to the row's `observer` / `context` (`or "agent"` /
`or "general"`), which is the same value for every parsed claim because `Claim.from_dict` already
defaults both. The existing tests in `test_claim_edge_regen.py` and `test_claim_pipeline.py:234`
hold it there. Then add, after `regenerate_edges_from_claims`:

```python
def upsert_claim_edges(memory_path: Path, page_ids) -> bool:
    """Re-project the claim-derived edges of just the pages ``page_ids`` names (F1 R-FX7).

    A folder sync writes paper claims (``cited-in`` the folder's project,
    ``about`` a concept) that only Sleep's Stage 5.7 used to turn into edges, so
    the owner's papers floated unattached until a cycle ran. This is
    :func:`regenerate_edges_from_claims`'s merge rule at page granularity: the
    rows it owns are those whose ``claim_id`` is a claim on one of these pages
    (open or closed — a closed claim's row must go), and they are replaced by
    those pages' open node-valued claims through the same
    :func:`_claim_edge_row`, so Stage 5.7 later writes the same rows. Every
    other row is kept verbatim — including one whose ``source`` is a named page
    but whose claim lives elsewhere. Writes nothing when the rows already match
    (no git churn on a no-change sync) and never rewrites a file it could not
    parse; a page whose claims block is corrupt owns nothing, so its rows stay.
    A row whose claim was deleted from its page outright (a hand edit, never a
    writer's path) waits for Stage 5.7. Returns True when ``graph_edges.yaml``
    was written."""
    memory_path = Path(memory_path)
    ids = sorted({str(s) for s in (page_ids or ()) if s})
    if not ids:
        return False
    owned: set[str] = set()
    fresh: list[dict] = []
    seen: set[tuple] = set()
    for stem in ids:
        page = memory_path / "entities" / f"{stem}.md"
        if not page.exists():
            continue
        try:
            body = parse(page).body
        except Exception:
            continue
        for claim in parse_claims(body):
            if claim.id:
                owned.add(claim.id)
            row = _claim_edge_row(claim, stem)
            if row is None or _row_key(row) in seen:
                continue
            seen.add(_row_key(row))
            fresh.append(row)
    edges_file = memory_path / "graph_edges.yaml"
    edges: list[dict] = []
    if edges_file.exists():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]

    def mine(edge: dict) -> bool:
        return bool(edge.get("claim_id")) and edge.get("claim_id") in owned

    def canon(rows: list[dict]) -> list[str]:
        return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)

    if canon([e for e in edges if mine(e)]) == canon(fresh):
        return False
    merged = [e for e in edges if not mine(e)] + fresh
    edges_file.write_text(
        yaml.dump({"edges": merged}, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True
```

- [ ] **Step 3: `papers.py`.** Add `claim_contexts` to the `from api.services import (...)` list.
  After `WHY_PREDICATES`, add:

```python
# F1 R-FX4 — the house word for "no particular context". A watched folder
# declares no life-area, so any other value would be a guess; the section
# already lives in `paper.sections`, the tags and the card's heading.
PAPER_CONTEXT = claim_contexts.NO_CONTEXT
```

In `desired_claims`, replace the inner `claim(...)` helper and its three call sites:

```python
    def claim(predicate: str, obj: str, *, literal: bool, slot: str, text_: str, quote: str,
              window: tuple[int, int]) -> None:
        # R-FX5: the id is derived from the SLOT this claim fills — for
        # `saved-because` the folder and section it was annotated under, else
        # `general` — which is exactly the string that used to be stored as its
        # context. Every id minted before F1 is minted again unchanged.
        cid = claim_id(entity_id, predicate, obj, observer, slot)
        if cid in out:
            return
        made = Claim(
            id=cid, text=text_, subject=entity_id, predicate=predicate, object=obj,
            object_kind="literal" if literal else "node", observer=observer, context=PAPER_CONTEXT,
            epistemic="explicit", source_trust=trust, confidence=_CONFIDENCE[who][predicate],
            valid_from=valid_from, recorded_at=today, source_episodes=[episode_id],
            authored_by="user" if who == "user" else None, origin=ORIGIN,
            evidence=[evidence.verify(None, episode_id, quote, text=text, window=window, kind_override=kind)],
        )
        # Read by `_same_slot`; `Claim.to_dict` is `asdict`, which never
        # serialises a non-field attribute (agentic_write's `_status_note` precedent).
        made._slot = slot
        out[cid] = made

    for c in citations:
        if c.note:
            section = sanitize_id(c.section) if c.section else "top"
            claim("saved-because", c.note, literal=True, slot=f"folder:{folder_id}:{section}",
                  text_=c.note, quote=c.note, window=(c.line_start, c.line_end))
        if project_id:
            claim("cited-in", project_id, literal=False, slot=PAPER_CONTEXT,
                  text_=f"Cited in {project_name or project_id}.", quote=c.quote,
                  window=(c.line_start, c.line_end))
        concept = concept_for(c.section) if c.section else None
        if concept and c.heading_start is not None:
            claim("about", concept, literal=False, slot=PAPER_CONTEXT, text_=f"Filed under {c.section}.",
                  quote=c.section, window=(c.heading_start, c.heading_end))
    return list(out.values())
```

Above `apply_claims`, add:

```python
def _same_slot(old: Claim, new: Claim) -> bool:
    """R-FX5 — did ``old`` fill the slot ``new`` fills?

    Paper claim ids are ``claim_id(subject, predicate, object, observer, slot)``.
    Recomputing the closed claim's id over the new claim's slot answers the
    question exactly — the job "same predicate + same context" did while the
    section lived in the context. Two sections' notes on one page share a
    predicate and (since F1) a context, so without this an edited note could be
    marked superseded by its sibling's."""
    slot = getattr(new, "_slot", None) or new.context
    return claim_id(old.subject, old.predicate, old.object, old.observer, slot) == old.id
```

In `apply_claims`, inside the `for new in desired:` loop, after the `if old.valid_to: …` block, add:

```python
        # R-FX6(b): the id names the slot and the context is only the writer's
        # label, so the writer's current one wins — a sync repairs a pre-F1
        # `folder:<id>:<section>` context on any claim it re-reads.
        old.context = new.context
```

And replace the successor lookup (`:425-426`) with:

```python
        c.superseded_by = next((d.id for d in desired
                                if d.predicate == c.predicate and _same_slot(c, d)), None)
```

In `apply_claims`'s docstring (`:391-392`), "its successor in the same predicate + context" becomes
"its successor in the same predicate and slot (`_same_slot`, F1 R-FX5)".

In `_reconcile_locked`: add `claim_pages: set[str] = set()` next to `revisit`. In **both**
`if apply_claims(...)` branches (the touched loop and the tombstoned loop), add
`claim_pages.add(eid)`. Then, immediately before `report["paths"] = sorted(paths)`, add:

```python
    # R-FX7: the claims this run changed are the edges the graph should show
    # now — a paper sits by the project that cites it without waiting for
    # Stage 5.7, which later rewrites the same rows (`_claim_edge_row`).
    if claim_pages:
        from api.services import graph_builder

        if graph_builder.upsert_claim_edges(memory_path, claim_pages):
            paths.add("graph_edges.yaml")
```

The folder route already commits `report["paths"]` (`routers/local_sources.py:157-159`), and so
does the Sleep tail's `reconcile_pending` (`sleep_cycle.py:494-497`, `author="cicada"`).
`graph_edges.yaml` is the `/graph` ETag's `edges` component, so the recipe does not change.

- [ ] **Step 4: The repair** — `api/services/paper_context_migration.py`:

```python
"""F1 (owner review 2026-09-23; R-FX4, R-FX6, R-FX7) — one-shot, idempotent:
move folder-paper claims off the ``folder:<id>:<section>`` context, and project
every paper's claim edges.

Before F1, ``papers.desired_claims`` stored a ``saved-because`` claim's folder
and section in its ``context``. The M5b facet rule then gave every annotated
paper two empty graph satellites — one named after that raw value, one
``general`` — and the Graph legend listed the raw value as a context. The
writer now says ``general`` and a sync repairs what it re-reads, but a file
nobody edits is never re-read, so existing pages are repaired here once.

Scope, exactly: claims with ``origin == folder`` whose context starts with
``folder:``, on ``media.kind: paper`` pages. Ids do not change (they always
named the slot, R-FX5), nothing else on a claim moves, and no evidence span goes
stale (the fence is not part of a page's evidence text, G118 R1). The same pass
projects every paper page's claim edges (``graph_builder.upsert_claim_edges``),
so a paper sits by the project that cites it without waiting for a Sleep cycle.
Marker-guarded, one commit scoped to exactly the rewritten paths,
``Cicada-Author: cicada`` — the ``export_origin_migration`` shape — and held
under ``folder_source._LOCK`` through the commit, so a folder sync cannot slip
its own rows into the ``graph_edges.yaml`` committed here. One page that cannot
be read or written never stops the rest, and what did land is still committed
(left dirty, it would ride the next ``git add -A`` under another author — the
G85-class smear); any such failure keeps the marker off so the next start
retries. A corrupt claims block is skipped, not retried: a later folder sync
repairs whatever it re-reads (R-FX6(b)). Never raises.
"""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, folder_source, git_service, graph_builder, markdown_parser, papers
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

_MARKER = ".paper_contexts_v1"
TRIGGER = "maintenance/paper_contexts"
_LEGACY_PREFIX = "folder:"
_NOTHING = {"pages": 0, "claims": 0, "edges": False}


def repair_paper_contexts(memory_path) -> dict:
    """Repair one bank. Returns ``{"pages": n, "claims": n, "edges": bool}``."""
    memory_path = Path(memory_path)
    if not (memory_path / "entities").exists() or (memory_path / _MARKER).exists():
        return dict(_NOTHING)
    try:
        with folder_source._LOCK:
            written, moved, paper_ids, failed = _rewrite(memory_path)
            try:
                edges = graph_builder.upsert_claim_edges(memory_path, paper_ids)
            except Exception as e:
                logger.error(f"Paper-edge projection FAILED — will retry on next start: {e}")
                edges, failed = False, True
            report = {"pages": len(written), "claims": moved, "edges": edges}
            rel = [f"entities/{p.name}" for p in written] + (["graph_edges.yaml"] if edges else [])
            if rel:
                try:
                    _commit(memory_path, rel)
                except Exception as e:
                    # Files are right on disk but uncommitted (or this bank is
                    # not a git repo). No marker, so the next boot re-scans,
                    # finds nothing left, and writes it; the files ride the
                    # bank's next commit — the trade `export_origin_migration`
                    # makes, because a bank without git must still be repaired.
                    logger.warning(f"Paper-context repair commit skipped: {e}")
                    return report
    except Exception as e:
        # No marker: the next boot retries, and finds done whatever did land.
        logger.error(f"Paper-context repair FAILED — will retry on next start: {e}")
        return dict(_NOTHING)
    if not failed:
        (memory_path / _MARKER).write_text("v1", encoding="utf-8")
    return report


def _rewrite(memory_path: Path) -> tuple[list[Path], int, list[str], bool]:
    """``(pages written, claims moved, every paper page's id, whether any page failed)``."""
    written: list[Path] = []
    moved = 0
    paper_ids: list[str] = []
    failed = False
    bank_index.invalidate(memory_path)
    for f in bank_index.files(memory_path, "entities"):
        if not papers.is_paper(f.frontmatter or {}):
            continue
        paper_ids.append(f.stem)
        try:
            parsed = markdown_parser.parse(f.path)
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            logger.error(f"corrupt claims block on {f.path.name}, paper contexts skipped: {exc}")
            continue
        except Exception as exc:
            logger.error(f"could not read {f.path.name}, paper contexts retried next start: {exc}")
            failed = True
            continue
        here = 0
        for c in claims:
            if c.origin == papers.ORIGIN and c.context.startswith(_LEGACY_PREFIX):
                c.context = papers.PAPER_CONTEXT
                here += 1
        if not here:
            continue
        try:
            markdown_parser.write(f.path, parsed.frontmatter, write_claims(parsed.body, claims))
        except Exception as exc:
            logger.error(f"could not rewrite {f.path.name}, paper contexts retried next start: {exc}")
            failed = True
            continue
        written.append(f.path)
        moved += here
    return written, moved, paper_ids, failed


def _commit(memory_path: Path, rel: list[str]) -> None:
    subprocess.run(["git", "add", "--", *rel], cwd=str(memory_path), check=True)
    status = subprocess.run(["git", "status", "--porcelain", "--", *rel], cwd=str(memory_path),
                            check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Repair paper contexts {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=["cicada"],
    )
    subprocess.run(["git", "commit", "-q", "-m", message, "--", *rel], cwd=str(memory_path), check=True)
```

`bank_index.invalidate(memory_path)` drops only this bank's cache (`bank_index.py:40-46`), and
`IndexedFile.path` is `Path(memory_path) / "entities" / <name>` (`:73`, `:89`), so it parses directly.

- [ ] **Step 5: Wire it** — `bank_migrations.py`: add the import
  `from api.services.paper_context_migration import repair_paper_contexts`. Before the `return`,
  add:

```python
    # F1 (R-FX6): one-time move of folder-paper claims off the pre-F1
    # `folder:<id>:<section>` context — the junk graph satellites — plus their
    # edges, so each paper sits by the project that cites it.
    paper_contexts = repair_paper_contexts(memory_path)
    if paper_contexts["pages"] or paper_contexts["edges"]:
        logger.info(
            f"Repaired paper contexts: {paper_contexts['claims']} claim(s) on "
            f"{paper_contexts['pages']} page(s); edges projected: {paper_contexts['edges']}"
        )
```

Add `"paper_contexts": paper_contexts` to the returned dict, and add
`"paper_contexts": {"pages", "claims", "edges"}` to the docstring's shape.

- [ ] **Step 6: Green** — the Step 1 command passes. `test_an_edited_annotation_supersedes_the_old_saved_because`
  and every other `test_papers.py` test must stay green unchanged. Then run the full `api/tests`
  (0 failures).
- [ ] **Step 7: Commit** — stage `api/services/{papers,graph_builder,paper_context_migration,bank_migrations}.py`
  and the three test files by name. Message:
  `fix(papers): general context with unchanged ids, edges to their project, one-shot repair (F1 R-FX4..7, G133)`.

---

### Task 3: The claims fence is never prose — every summary reader strips it, and a thin page lists its beliefs (R-FX8 · R-FX11)

**Files:**
- Modify: `api/services/graph_builder.py:18-34` (`summarize`), `api/routers/entities.py:183-187`, `api/services/hub_builder.py:43-63`
- Create: `api/tests/test_claims_fence_readers.py`
- Create: `app/…/Views/Graph/EntityProse.swift`, `app/…/Views/Graph/WhatCicadaKnowsSection.swift`, `app/…/Theme/Copy+Beliefs.swift`, `app/CicadaApp/Tests/CicadaAppTests/EntityProseTests.swift`
- Modify: `app/…/Views/Graph/EntityDetailCard.swift` (`:392-396`, `:835-896`, the content tab's `.task` at `:418`), `app/…/Views/Feed/FeedView.swift:465-468, 484-499`

**Interfaces:**
- Produces `EntityProse.stripClaimsFence(_:)`, `.section(named:in:)`, `.stripSection(named:from:)`, `.firstSection(_:in:)`, `.isPlaceholderSummary(_:)`, `.showsBeliefs(markdown:isStub:)`; `WhatCicadaKnowsSection(claims:onOpenTimeline:)`; `Copy.Beliefs.title` / `.caption`.
- Consumes `claims.strip_claims_block`, `ClaimChip`, the card's `validClaims` / `loadClaimsIfNeeded` / `timelineKey`.

- [ ] **Step 1: Failing Python tests** — `api/tests/test_claims_fence_readers.py`:

```python
"""F1 (R-FX8) — no server reader turns the claims fence into prose.

`claims.write_claims` appends the fence after a page's last section, so on a
Summary-only page it sits inside the Summary as far as a section reader can
tell. `summarize_for_recall`, `evidence.source_text` and `state_dictionary`
strip it first; these three did not."""
from __future__ import annotations

from api.routers.entities import _build_media_block
from api.services.graph_builder import summarize
from api.services.hub_builder import _one_line_summary

FENCE = "`" * 3
BLOCK = (f"{FENCE}claims\n- id: clm_alpha\n  text: alpha-project uses sqlite-vec\n"
         f"  subject: alpha-project\n{FENCE}\n")
MEDIA = {"media": {"url": "https://arxiv.org/abs/2401.00001", "media_type": "url", "kind": "paper"}}


def test_the_graph_preview_never_shows_the_fence():
    assert summarize(f"## Summary\nAlpha Project keeps notes.\n\n{BLOCK}") == "Alpha Project keeps notes."
    assert summarize(f"## Summary\n\n{BLOCK}") is None
    assert summarize(BLOCK) is None


def test_a_media_description_stops_before_the_fence():
    assert _build_media_block(MEDIA, f"## Summary\nSaved paper — Paper Alpha.\n\n{BLOCK}").description == \
        "Saved paper — Paper Alpha."
    assert _build_media_block(MEDIA, f"## Summary\n\n{BLOCK}").description is None


def test_a_hub_one_liner_never_reads_yaml():
    # An empty Summary still falls back to the heading word (a pre-existing
    # quirk of `_one_line_summary`, out of scope) — what matters is no YAML.
    assert "clm" not in _one_line_summary(f"## Summary\n\n{BLOCK}")
    assert _one_line_summary(f"## Summary\nAlpha Project keeps notes.\n\n{BLOCK}") == "Alpha Project keeps notes."
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_claims_fence_readers.py -q -p no:cacheprovider`.
Expected: 3 failed.

- [ ] **Step 2: Implement (server).** `graph_builder.py`: change the import to
  `from api.services.claims import parse_claims, strip_claims_block`. The first line of
  `summarize`'s body becomes `text = strip_claims_block(body or "").strip()`. Append to its
  docstring:

```python
    The ```claims fence is stripped first (F1 R-FX8): `claims.write_claims`
    appends it after the last section, so an empty Summary previewed as the
    fence line and a page with no heading previewed as YAML.
```

`routers/entities.py`: import `strip_claims_block` from `api.services.claims`. `:183` becomes
`match = _SUMMARY_RE.search(strip_claims_block(body or ""))`, with a one-line comment citing
R-FX8. `hub_builder.py`: `from api.services.claims import strip_claims_block` at module top. Make
the first statement of `_one_line_summary` `body = strip_claims_block(body or "")`, with the same
one-line reason.

- [ ] **Step 3: Failing Swift tests** — `app/CicadaApp/Tests/CicadaAppTests/EntityProseTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// F1 (R-FX8, R-FX11) — the app reads an entity page the way the server does:
/// the ```claims fence is stripped before any section is read. The owner saw
/// `claims - id: clm_… text: …` flattened inside the Summary box of pages
/// whose only section is the Summary (the fence follows the last section).
final class EntityProseTests: XCTestCase {
    private let fence = String(repeating: "`", count: 3)

    private func page(summary: String, extra: String = "") -> String {
        "## Summary\n\(summary)\(extra)\n\n\(fence)claims\n- id: clm_alpha\n  text: alpha-project uses sqlite-vec\n  subject: alpha-project\n\(fence)\n"
    }

    func testTheFenceNeverReachesASection() {
        let md = page(summary: "Alpha Project — created via agentic write.")
        XCTAssertEqual(EntityProse.section(named: "## Summary", in: md), "Alpha Project — created via agentic write.")
        XCTAssertEqual(EntityProse.firstSection(["## Description", "## Summary"], in: md),
                       "Alpha Project — created via agentic write.")
        XCTAssertNil(EntityProse.section(named: "## Summary", in: "## Summary\n\n\(fence)claims\n- id: x\n\(fence)\n"))
        XCTAssertFalse(EntityProse.stripClaimsFence(md).contains("clm_alpha"))
    }

    func testOtherCodeBlocksSurvive() {
        let md = "## Summary\nx\n\n\(fence)swift\nlet a = 1\n\(fence)\n\n\(fence)claims\n- id: c\n\(fence)\n"
        let stripped = EntityProse.stripClaimsFence(md)
        XCTAssertTrue(stripped.contains("let a = 1"))
        XCTAssertFalse(stripped.contains("- id: c"))
    }

    func testAnUnterminatedFenceIsHiddenToTheEnd() {
        XCTAssertEqual(EntityProse.stripClaimsFence("## Summary\nx\n\n\(fence)claims\n- id: c\n"), "## Summary\nx")
    }

    func testThePlaceholderIsRecognisedAndNothingElseIs() {
        XCTAssertTrue(EntityProse.isPlaceholderSummary("Alpha Project — created via agentic write."))
        XCTAssertFalse(EntityProse.isPlaceholderSummary("Alpha Project depends on sqlite-vec."))
        XCTAssertFalse(EntityProse.isPlaceholderSummary("Alpha Project — created via agentic write.\nMore."))
    }

    func testBeliefsShowOnlyOnAFullPageWhoseProseIsAtMostASummary() {
        XCTAssertTrue(EntityProse.showsBeliefs(markdown: page(summary: "Alpha-project depends on sqlite-vec."), isStub: false))
        XCTAssertFalse(EntityProse.showsBeliefs(markdown: page(summary: "x", extra: "\n\n## Key Facts\n- y"), isStub: false))
        XCTAssertFalse(EntityProse.showsBeliefs(markdown: "Alpha Project keeps notes.", isStub: true),
                       "the graph-node stub never triggers a claims fetch")
    }
}
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter EntityProseTests 2>&1 | tail -20`.
Expected: a compile failure.

- [ ] **Step 4: Implement (app)** — `app/…/Views/Graph/EntityProse.swift`:

```swift
import Foundation

/// The prose half of an entity page, read the way the server reads it
/// (F1, owner review 2026-09-23; R-FX8).
///
/// `claims.write_claims` appends the ```claims fence after the page's last
/// section — there is no claims section anywhere — so a page whose only
/// section is `## Summary` carries its fence *inside* the Summary as far as a
/// line reader can tell. The server's readers strip it first
/// (`entity_body.summarize_for_recall`, `evidence.source_text`,
/// `state_dictionary`); this is the app's one copy of that rule, used by the
/// entity card's Summary box, body and media description and by the Feed
/// sheet. `MarkdownBody` already hides the fence as a code block; the leak was
/// the section readers.
enum EntityProse {
    private static let fence = String(repeating: "`", count: 3)

    /// The markdown with every ```claims block removed. An unterminated fence
    /// hides everything after it: showing machine YAML as prose is the defect
    /// this exists to prevent, and nothing prose-like follows a claims fence.
    static func stripClaimsFence(_ markdown: String) -> String {
        var kept: [String] = []
        var inFence = false
        for line in markdown.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if inFence {
                if trimmed == fence { inFence = false }
                continue
            }
            if line.hasPrefix(fence), trimmed == fence + "claims" {
                inFence = true
                continue
            }
            kept.append(line)
        }
        return kept.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The text under a `## Header` up to the next `## ` header (or EOF), with
    /// the fence stripped first; nil when absent or empty.
    static func section(named header: String, in markdown: String) -> String? {
        let lines = stripClaimsFence(markdown).components(separatedBy: "\n")
        guard let start = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == header }) else {
            return nil
        }
        var body: [String] = []
        for line in lines[(start + 1)...] {
            if line.trimmingCharacters(in: .whitespaces).hasPrefix("## ") { break }
            body.append(line)
        }
        let text = body.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    /// The first present, non-empty section among `headers`.
    static func firstSection(_ headers: [String], in markdown: String) -> String? {
        for header in headers {
            if let text = section(named: header, in: markdown) { return text }
        }
        return nil
    }

    /// `markdown` without the named `## Header` and its body. Callers strip the
    /// fence first when the result is rendered.
    static func stripSection(named header: String, from markdown: String) -> String {
        let lines = markdown.components(separatedBy: "\n")
        guard let start = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == header }) else {
            return markdown
        }
        var kept = Array(lines[..<start])
        var i = start + 1
        while i < lines.count, !lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("## ") { i += 1 }
        kept.append(contentsOf: lines[i...])
        return kept.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// `agentic_write`'s old stub line (R-FX10). Pages keep it only when they
    /// have no open claim to write a sentence from; the card hides it (R-FX11).
    static func isPlaceholderSummary(_ text: String) -> Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
            .range(of: #"^[^\n]+ — created via agentic write\.$"#, options: .regularExpression) != nil
    }

    /// R-FX11 — a full page (never the graph-node stub, whose body is a
    /// one-line preview) whose prose is at most a Summary: its beliefs are the
    /// content worth showing.
    static func showsBeliefs(markdown: String, isStub: Bool) -> Bool {
        guard !isStub else { return false }
        let rest = stripSection(named: "## Summary", from: stripClaimsFence(markdown))
        return rest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}
```

`app/…/Theme/Copy+Beliefs.swift`:

```swift
import Foundation

/// F1 R-FX11 — the entity card's beliefs list, in its own file so this track
/// and the sibling tracks appending to `Copy.swift` never edit the same lines
/// (the `Copy+Intake.swift` precedent, R-IA19). Plain words for a person who
/// has never heard "claim".
extension Copy {
    enum Beliefs {
        static let title = "What Cicada knows"
        static let caption = "Nothing's written up about this yet, so here's what Cicada has noted."
    }
}
```

`app/…/Views/Graph/WhatCicadaKnowsSection.swift`:

```swift
import SwiftUI

/// F1 R-FX11 — a page whose only prose is its Summary shows what Cicada
/// believes about it, as claims, with the Perspectives tab's `ClaimChip`, so a
/// belief looks the same wherever it appears. The owner found these pages
/// empty, or showing raw YAML.
struct WhatCicadaKnowsSection: View {
    let claims: [Claim]
    var onOpenTimeline: (Claim) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.Beliefs.title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.Beliefs.caption)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            ForEach(claims) { claim in
                ClaimChip(claim: claim, onOpenTimeline: { onOpenTimeline(claim) })
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
```

In `EntityDetailCard.swift`:
- Replace the body of `mediaDescription` (`:838-845`; its doc comment stays) with
  `EntityProse.firstSection(["## Description", "## Summary"], in: entity.markdownContent)`.
- Delete the private `section(named:in:)` and `stripSection(named:from:)` (`:847-878`). Their one
  home is now `EntityProse`, so leave a one-line comment pointing there.
- `bodyForRendering` (`:885-889`) becomes:

```swift
    private var bodyForRendering: String {
        let prose = EntityProse.stripClaimsFence(entity.markdownContent)
        return EntityProse.stripSection(named: "## Description",
                                        from: EntityProse.stripSection(named: "## Summary", from: prose))
    }
```

- `summaryText` (`:894-896`) becomes:

```swift
    private var summaryText: String? {
        guard let text = EntityProse.section(named: "## Summary", in: entity.markdownContent),
              !EntityProse.isPlaceholderSummary(text) else { return nil }
        return text
    }

    /// R-FX11 — media pages have their own card (a paper's lists its why).
    private var showsBeliefs: Bool {
        entity.type != .media
            && EntityProse.showsBeliefs(markdown: entity.markdownContent, isStub: entity.rawMarkdown.isEmpty)
    }
```

- In `contentTab`, change the rendered branch (`:392-396`, the `if showRawMarkdown { … } else { … }`
  right after the media preview) to:

```swift
            if showRawMarkdown {
                rawMarkdownView
            } else {
                renderedMarkdownView
                if showsBeliefs, !validClaims.isEmpty {
                    WhatCicadaKnowsSection(claims: validClaims) { claim in
                        timelineKey = TimelineKey(predicate: claim.predicate, context: claim.context)
                    }
                }
            }
```

- Next to the content tab's existing `.task(id: entity.id)`, add
  `.task(id: showsBeliefs) { if showsBeliefs { await loadClaimsIfNeeded() } }`. It runs once the
  full entity has replaced the stub. `loadClaimsIfNeeded` is already guarded.

`FeedView.swift`: the fallback fetch (`:465-468`, `Self.firstSection(…)`) calls
`EntityProse.firstSection(["## Description", "## Summary"], in: entity.markdownContent)`. Delete the
private static `firstSection` and its doc comment (`:484-499`).

- [ ] **Step 5: Green** — the Step 1 command passes, and so does
  `swift test --filter EntityProseTests`. Then run the full `swift build`/`swift test` (0 failures)
  and the full `api/tests` (0 failures).
- [ ] **Step 6: Commit** — stage by name the three server files (`api/services/graph_builder.py`,
  `api/routers/entities.py`, `api/services/hub_builder.py`), `api/tests/test_claims_fence_readers.py`,
  the four new Swift files (`EntityProse.swift`, `WhatCicadaKnowsSection.swift`,
  `Theme/Copy+Beliefs.swift`, `EntityProseTests.swift`), and `EntityDetailCard.swift` and
  `FeedView.swift`. Message:
  `fix(entity): the claims fence is never prose; a Summary-only page lists what Cicada knows (F1 R-FX8, R-FX11, G24)`.

---

### Task 4: `agentic_write` writes a real first Summary, and existing placeholder pages are rewritten once (R-FX9 · R-FX10)

**Files:**
- Modify: `api/services/entity_body.py` (add two pure functions after `summarize_for_recall`, `:450-483`)
- Modify: `api/services/agentic_write.py:140-197` (`_ensure_subject_page`), `:374-376`, `:407`
- Create: `api/services/placeholder_summary_migration.py`
- Modify: `api/services/bank_migrations.py`
- Create: `api/tests/test_entity_body_summary_line.py`, `api/tests/test_placeholder_summary_migration.py`
- Modify: `api/tests/test_agentic_write.py` (append)

**Interfaces:**
- Produces `entity_body.summary_line(text, *, predicate="")`, `entity_body.summary_from_claims(claims, *, limit=3, max_chars=240)`, `placeholder_summary_migration.PLACEHOLDER_RE`, `.rewrite_placeholder_summaries(memory_path) -> int`, and `run_bank_migrations(...)["placeholders"]`.
- `_ensure_subject_page(memory_path, subject, predicate, source_episode, *, summary: str = "")`. The positional call in `test_decay_writers.py:149` stays valid.

- [ ] **Step 1: Failing tests.** `api/tests/test_entity_body_summary_line.py`:

```python
"""F1 (R-FX9) — a claim's text as a Summary sentence: deterministic, no LLM."""
from __future__ import annotations

from api.services.claims import Claim
from api.services.entity_body import summary_from_claims, summary_line


def test_a_claim_reads_as_a_sentence():
    assert summary_line("alpha-project depends-on sqlite-vec", predicate="depends-on") == \
        "Alpha-project depends on sqlite-vec."
    assert summary_line("Bob Example works with Grace Example.", predicate="works-with") == \
        "Bob Example works with Grace Example."
    assert summary_line("iOS app  uses\nSwift", predicate="uses") == "iOS app uses Swift."
    assert summary_line("Is alpha-project shipping?") == "Is alpha-project shipping?"
    assert summary_line("   ") == ""


def test_a_hyphenated_predicate_is_only_humanised_as_a_whole_token():
    assert summary_line("gamma-project re-depends-on x", predicate="depends-on") == "Gamma-project re-depends-on x."


def test_open_claims_in_page_order_deduplicated_and_capped():
    claims = [
        Claim(id="a", text="alpha-project depends-on sqlite-vec", predicate="depends-on"),
        Claim(id="b", text="alpha-project uses postgres", predicate="uses", valid_to="2026-05-01"),
        Claim(id="c", text="Alpha-project depends on sqlite-vec.", predicate="depends-on"),
        Claim(id="d", text="Alpha Project ships a macOS app", predicate="ships"),
        Claim(id="e", text="Alpha Project has a logo", predicate="has"),
        Claim(id="f", text="Alpha Project is open source", predicate="is"),
    ]
    assert summary_from_claims(claims) == (
        "Alpha-project depends on sqlite-vec. Alpha Project ships a macOS app. Alpha Project has a logo.")
    assert summary_from_claims([]) == ""
    long = [Claim(id=str(i), text="word " * 30, predicate="p") for i in range(3)]
    out = summary_from_claims(long, max_chars=60)
    assert len(out) <= 60 and out.endswith("…")
```

`api/tests/test_placeholder_summary_migration.py`:

```python
"""F1 (R-FX10) — the one-shot rewrite of `agentic_write`'s placeholder pages."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import bank_migrations, entity_body, markdown_parser
from api.services import placeholder_summary_migration as mig
from api.services.claims import Claim, parse_claims, strip_claims_block, write_claims

FENCE = "`" * 3
OPEN = [
    Claim(id="clm_a1", text="alpha-project depends-on sqlite-vec", subject="alpha-project",
          predicate="depends-on", object="sqlite-vec"),
    Claim(id="clm_a2", text="Alpha Project ships a macOS app", subject="alpha-project",
          predicate="ships", object="a macOS app"),
    Claim(id="clm_a3", text="alpha-project uses postgres", subject="alpha-project", predicate="uses",
          object="postgres", valid_to="2026-05-01", superseded_by="clm_a1"),
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _page(bank, stem, *, summary, claims, type_="concept"):
    body = entity_body.compose_body_v2(summary=summary, key_facts=[], history_entries=[], related=[],
                                       links=[], open_questions=[])
    markdown_parser.write(bank / "entities" / f"{stem}.md",
                          {"name": stem.replace("-", " ").title(), "type": type_, "layout_version": 2},
                          write_claims(body, claims))


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@cicada.local")
    _git(bank, "config", "user.name", "Cicada Test")
    _page(bank, "alpha-project", summary="Alpha Project — created via agentic write.", claims=OPEN)
    _page(bank, "bob-example", claims=OPEN[:1],
          summary="Bob Example — created via agentic write.\nBob Example leads a team.")
    _page(bank, "gamma-project", summary="Gamma Project — created via agentic write.", claims=OPEN[2:])
    _page(bank, "media-example", summary="Media Example — created via agentic write.", claims=OPEN[:1],
          type_="media")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    return bank


def _body(bank, stem):
    return markdown_parser.parse(bank / "entities" / f"{stem}.md").body


def test_only_a_one_line_placeholder_with_an_open_claim_is_rewritten(tmp_path):
    bank = _bank(tmp_path)
    before = {s: _body(bank, s) for s in ("bob-example", "gamma-project", "media-example")}
    fm_before = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert mig.rewrite_placeholder_summaries(bank) == 1
    body = _body(bank, "alpha-project")
    assert strip_claims_block(body) == \
        "## Summary\nAlpha-project depends on sqlite-vec. Alpha Project ships a macOS app."
    assert [c.to_dict() for c in parse_claims(body)] == [c.to_dict() for c in OPEN]
    assert body.rstrip().endswith(FENCE), "the fence stays where write_claims puts it (R-FX8)"
    assert markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter == fm_before
    for stem, text in before.items():
        assert _body(bank, stem) == text, stem


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_page(tmp_path):
    bank = _bank(tmp_path)
    mig.rewrite_placeholder_summaries(bank)
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["entities/alpha-project.md"]


def test_it_runs_once_and_a_second_pass_changes_nothing(tmp_path):
    bank = _bank(tmp_path)
    mig.rewrite_placeholder_summaries(bank)
    head = _git(bank, "rev-parse", "HEAD")
    assert mig.rewrite_placeholder_summaries(bank) == 0
    (bank / ".placeholder_summaries_v1").unlink()
    assert mig.rewrite_placeholder_summaries(bank) == 0
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_page_that_cannot_be_written_keeps_the_marker_off_and_the_rest_is_committed(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _page(bank, "delta-project", summary="Delta Project — created via agentic write.", claims=OPEN[:1])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "delta")
    real = markdown_parser.write

    def flaky(path, frontmatter, body):
        if Path(path).stem == "delta-project":
            raise OSError("disk full")
        return real(path, frontmatter, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    assert mig.rewrite_placeholder_summaries(bank) == 1
    assert not (bank / ".placeholder_summaries_v1").exists(), "the next start must retry delta-project"
    assert _git(bank, "status", "--porcelain", "--", "entities/alpha-project.md") == ""


def test_bank_migrations_runs_it(tmp_path):
    assert bank_migrations.run_bank_migrations(_bank(tmp_path))["placeholders"] == 1
```

Append to `api/tests/test_agentic_write.py`:

```python
def test_a_new_page_opens_with_a_sentence_from_the_claim_it_was_created_for(tmp_path):
    """F1 R-FX9 — no placeholder; the fence follows the Summary as on every page."""
    from api.services.claims import strip_claims_block

    agentic_write.write_claim(tmp_path, "alpha-project", "depends-on", "sqlite-vec", observer="agent")
    body = markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body
    assert "created via agentic write" not in body
    assert strip_claims_block(body) == "## Summary\nAlpha-project depends on sqlite-vec."
    assert body.rstrip().endswith("`" * 3)


def test_the_agents_own_claim_text_wins_and_a_later_claim_never_rewrites_it(tmp_path):
    from api.services.claims import strip_claims_block

    agentic_write.write_claim(tmp_path, "Alpha Project", "runs-on", "a Raspberry Pi", observer="agent",
                              text="Alpha Project runs on a Raspberry Pi")
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent")
    body = markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body
    assert strip_claims_block(body) == "## Summary\nAlpha Project runs on a Raspberry Pi."
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_entity_body_summary_line.py api/tests/test_placeholder_summary_migration.py api/tests/test_agentic_write.py -q -p no:cacheprovider`.
Expected: import errors, and the two new agentic tests fail.

- [ ] **Step 2: Implement `entity_body`** (pure string logic, per the module's own contract):

```python
_TERMINAL = (".", "!", "?", "…")


def summary_line(text: str, *, predicate: str = "") -> str:
    """One claim's text as a Summary sentence — deterministic, no LLM (F1 R-FX9).

    ``agentic_write`` used to open every page it created with ``<name> —
    created via agentic write.``; the owner's pages then showed nothing but that
    line and, under it, the claims fence as raw YAML. The claim being written is
    the only thing Cicada knows about a new page, so it becomes the first line:
    whitespace collapsed, a hyphenated predicate slug read as words when it
    appears as a whole token (``depends-on`` → ``depends on``; the mechanical
    fallback text is ``<subject> <predicate> <object>``), the first letter
    capitalised only when the first word is all lowercase (``iOS`` stays), and a
    period added when the text has no terminal punctuation."""
    line = " ".join((text or "").split())
    if not line:
        return ""
    if predicate and "-" in predicate:
        line = re.sub(rf"(?<![\w-]){re.escape(predicate)}(?![\w-])",
                      predicate.replace("-", " "), line, count=1)
    first = line.split(" ", 1)[0]
    if first[:1].islower() and first == first.lower():
        line = line[:1].upper() + line[1:]
    if not line.endswith(_TERMINAL):
        line += "."
    return line


def summary_from_claims(claims, *, limit: int = 3, max_chars: int = 240) -> str:
    """The first ``limit`` open claims as sentences, in page order, deduplicated,
    capped at ``max_chars`` on a word boundary (F1 R-FX10). Closed and superseded
    claims are not current beliefs, so they never write the Summary. Empty when
    nothing is open. Duck-typed on ``text`` / ``predicate`` / ``valid_to`` /
    ``superseded_by`` so this module keeps importing nothing from ``claims``."""
    sentences: list[str] = []
    seen: set[str] = set()
    for claim in claims or []:
        if getattr(claim, "valid_to", None) or getattr(claim, "superseded_by", None):
            continue
        line = summary_line(getattr(claim, "text", ""), predicate=getattr(claim, "predicate", ""))
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        sentences.append(line)
        if len(sentences) == limit:
            break
    out = " ".join(sentences)
    if len(out) <= max_chars:
        return out
    return out[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
```

- [ ] **Step 3: Implement `agentic_write`.** Give `_ensure_subject_page` a keyword-only
  `summary: str = ""`. Its `compose_body_v2(summary=...)` argument becomes
  `summary=summary or f"{display_name}."`. Append a paragraph to its docstring (keep the
  `Returns ``(filepath, entity_id)``.` sentence): "``summary`` is the new page's first line —
  ``write_claim`` passes the claim being written (F1 R-FX9); the old ``— created via agentic
  write.`` placeholder left pages with nothing but that line and, under it, the claims fence." In
  `write_claim`, before the `_ensure_subject_page` call (`:374`), compute
  `claim_text = text or f"{subject_raw} {predicate_raw} {object_raw}"`, and pass
  `summary=entity_body.summary_line(claim_text, predicate=predicate_raw)`. At `:407`, the `Claim`'s
  `text=` becomes `claim_text`.

- [ ] **Step 4: The migration** — `api/services/placeholder_summary_migration.py`:

```python
"""F1 (owner review 2026-09-23; R-FX10) — one-shot, idempotent: give every page
``agentic_write`` created with the ``<name> — created via agentic write.``
placeholder a real first line, composed from its own open claims.

The owner found such pages all over the graph: the Summary box showed the stub
line and, under it, the claims fence flattened into YAML. Readers no longer
show the fence (R-FX8) and the writer no longer writes the stub (R-FX9); this
repairs the pages already on disk.

Scope, exactly: a non-``media`` page whose ``## Summary`` (fence stripped) is
one line matching :data:`PLACEHOLDER_RE` and that has at least one open claim.
The new line is ``entity_body.summary_from_claims`` over its claims — no LLM.
Nothing else moves: frontmatter is untouched (no ``version`` bump, no
``last_referenced`` — a repair is not a mention), every other section is kept,
and the claims list round-trips unchanged to where ``write_claims`` always puts
it, after the last section. The only deterministic writer of ``page`` evidence
spans, ``link_recon``, cites media pages, which this skips; a span an agent
hand-cited on one of these pages would read ``stale`` afterwards (the G118 hash
guard) — never a mis-highlight. A page with no open claim keeps its line; the
app hides it (R-FX11). Marker-guarded, one commit scoped to exactly the
rewritten pages, ``Cicada-Author: cicada``. One page that cannot be rewritten
never stops the rest, what did land is still committed (left dirty, it would
ride the next ``git add -A`` under another author — the G85-class smear), and
the marker stays off so the next start retries it. Never raises.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import entity_body, git_service, markdown_parser
from api.services.claims import MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims

PLACEHOLDER_RE = re.compile(r"^.+ — created via agentic write\.$")
_MARKER = ".placeholder_summaries_v1"
TRIGGER = "maintenance/placeholder_summary"


def rewrite_placeholder_summaries(memory_path) -> int:
    """Rewrite one bank. Returns how many pages were rewritten."""
    memory_path = Path(memory_path)
    entities = memory_path / "entities"
    if not entities.exists() or (memory_path / _MARKER).exists():
        return 0
    written: list[Path] = []
    failed = False
    for path in sorted(entities.glob("*.md")):
        try:
            if _rewrite_one(path):
                written.append(path)
        except Exception as e:
            logger.error(f"Placeholder summary for {path.name} FAILED — will retry on next start: {e}")
            failed = True
    if written:
        try:
            _commit(memory_path, [f"entities/{p.name}" for p in written])
        except Exception as e:
            # Right on disk but uncommitted (or not a git repo): no marker, the
            # next start finds nothing left to rewrite and writes it — the
            # `export_origin_migration` trade.
            logger.warning(f"Placeholder-summary commit skipped: {e}")
            return len(written)
    if not failed:
        (memory_path / _MARKER).write_text("v1", encoding="utf-8")
    return len(written)


def _rewrite_one(path: Path) -> bool:
    try:
        parsed = markdown_parser.parse(path)
    except Exception:
        return False
    fm = parsed.frontmatter or {}
    if str(fm.get("type") or "") == "media":
        return False
    sections = entity_body.parse_sections(strip_claims_block(parsed.body))
    summary = (sections.get("Summary") or "").strip()
    if "\n" in summary or not PLACEHOLDER_RE.match(summary):
        return False
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        logger.error(f"corrupt claims block on {path.name}, placeholder kept: {exc}")
        return False
    line = entity_body.summary_from_claims(claims)
    if not line:
        return False
    sections["Summary"] = line
    new_body = write_claims(entity_body.render_sections(sections), claims)
    if new_body == parsed.body:
        return False
    markdown_parser.write(path, fm, new_body)
    return True


def _commit(memory_path: Path, rel: list[str]) -> None:
    subprocess.run(["git", "add", "--", *rel], cwd=str(memory_path), check=True)
    status = subprocess.run(["git", "status", "--porcelain", "--", *rel], cwd=str(memory_path),
                            check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Write placeholder summaries {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=["cicada"],
    )
    subprocess.run(["git", "commit", "-q", "-m", message, "--", *rel], cwd=str(memory_path), check=True)
```

`bank_migrations.py`: add the import
`from api.services.placeholder_summary_migration import rewrite_placeholder_summaries` and, after the
paper repair and before the `return`:

```python
    # F1 (R-FX10): one-time real first line for the pages `agentic_write` once
    # opened with `<name> — created via agentic write.`, from their own open
    # claims — no LLM.
    placeholders = rewrite_placeholder_summaries(memory_path)
    if placeholders:
        logger.info(f"Wrote a first Summary for {placeholders} placeholder page(s)")
```

Add `"placeholders": placeholders` to the returned dict and `"placeholders": int` to the docstring's
shape.

- [ ] **Step 5: Green** — the Step 1 command passes. `test_decay_writers.py` still passes (the
  positional `_ensure_subject_page` call), and so do `test_demo_bank.py` (its pages are now composed
  deterministically from the demo claims) and the full `api/tests` (0 failures).
- [ ] **Step 6: Commit** — stage `entity_body.py`, `agentic_write.py`,
  `placeholder_summary_migration.py`, `bank_migrations.py` and the three test files by name.
  Message:
  `fix(agentic write): a real first Summary from the claim; rewrite existing placeholder pages once (F1 R-FX9, R-FX10)`.

---

### Task 5: SF Pro Display behind the same `displayFont` — no bundled face (R-FX12 · R-FX13)

**Files:**
- Modify: `app/…/Theme/CicadaTheme.swift:316-336`
- Delete (`git rm`): `app/…/Theme/CicadaFonts.swift`, `app/…/Resources/fonts/InstrumentSerif-Regular.ttf`, `app/…/Resources/fonts/InstrumentSerif-Italic.ttf`, `app/…/Resources/fonts/OFL.txt`, `app/…/Resources/fonts/FONTS.md`, `app/CicadaApp/Tests/CicadaAppTests/CicadaFontsTests.swift`
- Modify: `app/…/CicadaApp.swift:87-88` (delete both lines)
- Modify: `app/…/Views/Common/PageHeader.swift:1-11, 29-31`; `app/…/Views/Common/EmptyStateView.swift:49-50`; `app/…/Views/Provenance/ReaderInspector.swift:99-100`; `app/…/Views/Sleep/RoomSentence.swift:286-287, 325, 404`
- Create: `app/CicadaApp/Tests/CicadaAppTests/DisplayFontTests.swift`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/FontLiteralLintTests.swift:44-76`

**Interfaces:** `CicadaTheme.displayFont(size:italic:)` has an unchanged signature. New:
`CicadaTheme.displayTracking(size:) -> CGFloat`. Removed: `CicadaFonts`.

- [ ] **Step 1: Failing tests.** Create `DisplayFontTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// F1 R-FX12 — the display face is the system's SF Pro Display behind the
/// same API every caller already used. The owner, on the Instrument Serif page
/// titles (2026-09-23): "i dont like this font … Change it to something more
/// minimal."
final class DisplayFontTests: XCTestCase {
    func testRomanIsSemiboldSFAndItalicIsRegularSFItalic() {
        XCTAssertEqual(CicadaTheme.displayFont(size: 28),
                       Font.system(size: CicadaTheme.scaled(28), weight: .semibold, design: .default))
        XCTAssertEqual(CicadaTheme.displayFont(size: 22, italic: true),
                       Font.system(size: CicadaTheme.scaled(22), weight: .regular, design: .default).italic())
        XCTAssertEqual(CicadaTheme.displayFont(size: 12), CicadaTheme.displayFont(size: CicadaTheme.displayMinimumSize))
        XCTAssertEqual(CicadaTheme.quoteFont, CicadaTheme.font(size: 13, design: .serif).italic(),
                       "the provenance quote face is untouched")
    }

    func testTrackingIsSlightlyNegativeAndScalesWithTheFace() {
        XCTAssertEqual(CicadaTheme.displayTracking(size: 28), -0.02 * CicadaTheme.scaled(28), accuracy: 0.0001)
        XCTAssertLessThan(CicadaTheme.displayTracking(size: 28), 0)
        XCTAssertEqual(CicadaTheme.displayTracking(size: 12),
                       CicadaTheme.displayTracking(size: CicadaTheme.displayMinimumSize), accuracy: 0.0001)
    }
}
```

In `FontLiteralLintTests.swift`, rewrite the two doc comments, because both describe the bundled
serif. `:44-47` (above `testNoCustomFontOutsideTheTheme`) becomes:

```swift
    /// G137 R-M3, F1 R-FX12: no face is bundled any more — `displayFont` is
    /// SF — so `.custom(` anywhere would be a second face arriving unnoticed:
    /// unscaled by ⌘+/⌘−, unregistered, unlicensed. Comment lines are skipped
    /// so a doc may name the API.
```

and `:60-61` (above `testDisplayFontIsNeverAskedForLessThanItsFloor`) becomes:

```swift
    /// Display is a role — a title — not a size (F1 R-FX12): a display call
    /// under 22 pt is a heading in the wrong token. `displayFont` clamps, and
    /// this keeps a call site from asking.
```

The two test bodies do not change. Then add:

```swift
    /// F1 R-FX12: `Font` cannot carry tracking, so every roman display title
    /// pairs `.font(CicadaTheme.displayFont(size: n))` with
    /// `.tracking(CicadaTheme.displayTracking(size: n))`. Counted per file —
    /// a new title without its tracking fails here, not in a screenshot.
    /// Italic lines keep SF's own spacing and are not counted.
    func testEveryRomanDisplayTitleCarriesItsTracking() throws {
        var seen = 0
        for file in try sourceFiles() {
            let code = try String(contentsOf: file, encoding: .utf8)
                .components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            let roman = code.filter { $0.contains("displayFont(size:") && !$0.contains("italic: true") }.count
            let tracked = code.filter { $0.contains("displayTracking(size:") }.count
            XCTAssertEqual(roman, tracked, "\(file.lastPathComponent): \(roman) roman displayFont call(s) "
                           + "but \(tracked) displayTracking — pair each title with its tracking (F1 R-FX12).")
            seen += roman
        }
        XCTAssertGreaterThan(seen, 0, "no roman displayFont call found — this lint would pass vacuously")
    }

    /// F1 R-FX12: nothing is bundled any more. A font file under Resources/
    /// would be a second face arriving unregistered, unlicensed and unscaled.
    func testNoFontFileIsBundled() throws {
        let resources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp/Resources")
        let all = FileManager.default.enumerator(at: resources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL } ?? []
        XCTAssertFalse(all.isEmpty, "found nothing under \(resources.path) — the lint would pass vacuously")
        let fonts = all.filter { ["ttf", "otf", "ttc", "woff", "woff2"].contains($0.pathExtension.lowercased()) }
        XCTAssertEqual(fonts.map(\.lastPathComponent), [])
    }
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter "DisplayFontTests|FontLiteralLintTests" 2>&1 | tail -20`.
Expected: `displayTracking` does not compile. Once it is stubbed, the equality, tracking and
bundled-file tests fail.

- [ ] **Step 2: Implement.** In `CicadaTheme.swift`, replace `:316-336` with:

```swift
    // MARK: - Display + quote faces (G137, spec R-M3; F1 R-FX12)
    /// Display is a role, not a face: page titles, onboarding headlines,
    /// empty-state titles — never a number, never body text. The floor keeps
    /// the role honest (a 13 pt "display" title is a heading), and
    /// `FontLiteralLintTests` fails a literal below it.
    static let displayMinimumSize: CGFloat = 22

    /// SF Pro Display — the system face at display sizes (macOS picks the
    /// Display cut itself above 20 pt): semibold for a title, regular italic
    /// for a headline's quieter second line. The owner found the bundled
    /// Instrument Serif too ornate (2026-09-23: "Change it to something more
    /// minimal"), so nothing is bundled or registered and the API every caller
    /// used is unchanged. Scaled by `uiScale` like every token and clamped to
    /// `displayMinimumSize`.
    static func displayFont(size: CGFloat, italic: Bool = false) -> Font {
        let resolved = scaled(max(size, displayMinimumSize))
        return italic
            ? Font.system(size: resolved, weight: .regular, design: .default).italic()
            : Font.system(size: resolved, weight: .semibold, design: .default)
    }

    /// A roman display title sits 2 % tighter than SF's own display spacing —
    /// the difference between a system header and a set headline. `Font`
    /// cannot carry tracking, so each roman call site pairs
    /// `.font(displayFont(size: n))` with `.tracking(displayTracking(size: n))`;
    /// `FontLiteralLintTests` counts the pairs. Italic keeps SF's spacing.
    static func displayTracking(size: CGFloat) -> CGFloat {
        -0.02 * scaled(max(size, displayMinimumSize))
    }

    /// The person's own words — provenance excerpts and quoted snippets. New
    /// York italic ships with macOS (zero bundle cost) and is optically sized
    /// for text.
    static var quoteFont: Font { quoteFont(size: 13) }
    static func quoteFont(size: CGFloat) -> Font { font(size: size, design: .serif).italic() }
```

Then make the call-site edits:
- **PageHeader** (`:29-31`): add `.tracking(CicadaTheme.displayTracking(size: 28))`,
  `.lineLimit(1)` and `.minimumScaleFactor(0.8)` after the font. In the type's doc comment
  (`:7-10`), replace the fragment from "a display-serif title in" through "so every call site keeps
  its line)," with: "a display title in `textPrimary` (SF Pro Display semibold 28 pt, one line that
  shrinks up to 20 % before it truncates — F1 R-FX12: SF sets about 30 % wider than the serif it
  replaced, 'Integrations' 114 → 152 pt measured),". The lines around it stay.
- **EmptyStateView** (`:50`): add `.tracking(CicadaTheme.displayTracking(size: 26))`.
- **ReaderInspector** (`:100`): add `.tracking(CicadaTheme.displayTracking(size: 22))`.
- **RoomSentence** (R-FX13): at `:325`, `.font(CicadaTheme.font(size: 30, design: .serif))` becomes
  `.font(CicadaTheme.displayFont(size: 30))` followed by
  `.tracking(CicadaTheme.displayTracking(size: 30))`. At `:404`,
  `let tailFont = CicadaTheme.font(size: 22, design: .serif).italic()` becomes
  `let tailFont = CicadaTheme.displayFont(size: 22, italic: true)`. The docstring at `:286-287`
  becomes: "The lead is Meadow's `displayFont` with its tracking, the tail its italic — SF Pro
  Display since F1 (R-FX13, Z10's swap)." Nothing else in `Views/Sleep/` changes.
- **CicadaApp.swift**: delete `:87-88` (the comment and `CicadaFonts.registerBundled()`) and the
  blank line after them, so no empty gap is left in `init()`.
- **Deletions**: `git rm` the six files listed above. `grep -rn "CicadaFonts\|InstrumentSerif" app/`
  must print nothing except this plan's own references, and those are under `docs/`, not `app/`.

- [ ] **Step 3: Prove the lint can fail.** Temporarily delete the tracking line in `PageHeader`,
  then run `swift test --filter FontLiteralLintTests`. It must FAIL and name `PageHeader.swift`.
  Restore the line and confirm it is green.
- [ ] **Step 4: Green** — `swift build 2>&1 | tail -5` succeeds, `swift test 2>&1 | tail -20` reports
  0 failures, and `EmptyStateViewTests` still finds `displayFont(size: 26)`.
- [ ] **Step 5: Commit** — stage by name `Theme/CicadaTheme.swift`, `CicadaApp.swift`,
  `Views/Common/PageHeader.swift`, `Views/Common/EmptyStateView.swift`,
  `Views/Provenance/ReaderInspector.swift`, `Views/Sleep/RoomSentence.swift`,
  `Tests/CicadaAppTests/DisplayFontTests.swift` and `Tests/CicadaAppTests/FontLiteralLintTests.swift`,
  plus the six `git rm` deletions. Message:
  `feat(meadow): SF Pro Display behind displayFont — semibold titles, tighter tracking, no bundled face (F1 R-FX12, R-FX13, G137)`.

---

### Task 6: Docs — the rulings, where the next reader will look

**Files:**
- Modify: `CLAUDE.md`: the Meadow paragraph's **Type** sentence, the Sleep page paragraph's "one
  serif sentence", and one new paragraph under **Claims, evidence and provenance** after its first
  paragraph (anchors drift; find them by text)
- Modify: `docs/goals/memory-evolution.md`: rows **G24** (`:499`), **G133** (`:695`), **G137** (`:699`)
- Modify: `docs/goals/TODO.md`: "Where things stand" (after the Track L paragraph, `:57-62`), and
  the G137 row of the table (`:392`)
- Modify: `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`: one
  amendment line under Decision 6 (`:77`), R-M3 (`:137`) and Decision 16 (`:254`, "one serif
  sentence")

- [ ] **Step 1: `CLAUDE.md`.** Replace the Type sentence with: "**Type:** SF Pro Display through
  `displayFont(size:italic:)` at ≥ 22 pt — semibold titles tracked 2 % tight
  (`displayTracking(size:)`, paired at every call site and counted by `FontLiteralLintTests`),
  regular italic for a headline's second line; no font is bundled (the owner found the serif too
  ornate, 2026-09-23). New York italic through `quoteFont`, SF for everything else." Then add this
  paragraph under Claims:

  > **Contexts and the fence (F1).** `context` is an open vocabulary whose *shape* is pinned by
  > `claim_contexts` — a short lowercase slug. Any other value (G60's `as of <date>`) keeps its job
  > as a claim key but is never a graph satellite, a legend row or an edge colour. `general` means
  > "no particular context" and is never a facet: a satellite needs two real contexts. The claims
  > fence sits after a page's last section (`write_claims`, the one writer), so **every reader
  > strips it before sectioning** — `strip_claims_block` on the server, `EntityProse` in the app.

  In the Sleep page paragraph ("the study room (G125 v4, Track Z)"), change "one serif sentence"
  to "one sentence in the display face", so the doc stops naming the face that is gone.

- [ ] **Step 2: Backlog rows.** Placeholders only: no bank contents, no real folder or section
  names, no counts read from the live bank. Each addition is appended to the end of the row's
  description cell (the column before the status), after a space; the status cell is untouched.
  - **G24** gains: "**F1 (2026-09-23, owner's live review):** the box showed the claims fence as
    flattened YAML on Summary-only pages (the fence follows the last section). Every summary reader
    now strips it (app `EntityProse`; server `graph_builder.summarize`, the media description, hub
    one-liners). A Summary-only page lists its open claims under *What Cicada knows*.
    `agentic_write` opens a page with a sentence from the claim it writes instead of a placeholder,
    and existing placeholder pages were rewritten once (R-FX8 … R-FX11)."
  - **G133** gains: "**F1:** paper claims stored `folder:<id>:<section>` as their context, which the
    M5b facet rule turned into two empty graph satellites per annotated paper and a raw legend row.
    They now write `general` with unchanged ids (the id names the slot). A folder sync projects their
    `cited-in`/`about` edges, so a paper sits by its project before any Sleep cycle, and a one-shot
    `cicada`-authored repair migrated existing banks (R-FX4 … R-FX7). *Revisit:* a per-folder context
    the owner picks."
  - **G137**: in rule (3), change "Instrument Serif (bundled, OFL) for display at ≥ 22 pt" to "**SF
    Pro Display** for display at ≥ 22 pt (semibold, 2 % tight; the owner found the serif too
    ornate, 2026-09-23 — F1 R-FX12)". In the M1 sentence, "the bundled display face" becomes "the
    bundled display face (removed in F1: SF Pro Display since)". This row is edited in place, not
    appended to.
- [ ] **Step 3: `TODO.md`.** Add a **Round 3 · Track F1 — owner feedback fixes, part 1
  (2026-09-23)** paragraph. It has three sentences, one per item fixed, citing R-FX ids, and ends
  with the baselines "measured on `fix/owner-feedback-1`; replace with the merged numbers". In the
  G137 row of the table (`:392`), after "Instrument Serif" add "(replaced by SF Pro Display in F1)".
- [ ] **Step 4: Spec amendment.** Under Decision 6 (`:77`), R-M3 (`:137`) and Decision 16
  (`:254`), add the line: "*Amended 2026-09-23 (Track F1, owner's instruction):* the display face
  is SF Pro Display; Instrument Serif is no longer bundled."
- [ ] **Step 5: Commit** — stage by name `CLAUDE.md`, `docs/goals/memory-evolution.md`,
  `docs/goals/TODO.md`, the round-3 spec, and this plan if it is not committed yet. Message:
  `docs: F1 — contexts, the fence, SF Pro Display (G24, G133, G137)`.

---

## Not in scope

These are listed so a reviewer does not read an absence as an oversight.

- **Later tracks named by the owner:** Settings as an in-app panel, a model switcher on the Sleep
  page, Safari tabs and bookmarks without Full Disk Access, and the smaller UI bugs from the same
  review.
- **Validating `context` at write time** (MCP `cicada_write_claim`, telegram, wispr). The read side
  now ignores a non-slug everywhere it could show. Closing the write side changes which claims share
  a key, including G60's `as of <date>` qualifier, and is its own decision.
- **A per-folder context the owner picks** (R-FX4's revisit trigger).
- **Re-minting paper claim ids** (declined, R-FX5), and **read-time projection of every claim edge**
  in `build_graph` (declined, R-FX7).
- **`entity_merge`'s unlocked write of `graph_edges.yaml`** (pre-existing; disclosed in R-FX7).
- **Rewriting Summaries Sleep wrote**, and LLM prose for agentic pages. Sleep's own merge takes over
  when the subject is next consolidated.
- **The Source (raw) view** keeps showing the whole file, fence included. It is the file (R-FX8).
- **`TopicsView`'s search matching claim YAML** in `markdownContent` (a relevance nit, not a display
  leak), and **`markdown_content` on the wire**, which stays the full body.
- **Re-tuning display sizes per page**, and the Sleep sentence's numeral weight, which is Track Z's.
  The live check decides.
- **Anything else under `Views/Sleep/` or `Views/Settings/`**, and the find palette.

---

## Merge notes (sibling branches and `dev` drift)

Checked with `git diff dev...<branch>` on 2026-09-23. None of this is done in this track; it is
what the orchestrator (or whichever branch merges second) needs so a conflict is resolved the way
the rulings mean.

- **`dev` moved to `a27e2ca`** (the find palette, PR #80) after this worktree was cut. It touches
  `GraphViewModel.swift` (`rankNames` now calls `QuickMatch`; `applySelection` moves up about 11
  lines), `FeedView.swift` (`FeedItemPreviewSheet` becomes internal), `CicadaApp.swift` (a
  `findModel` state and `FindCommands`), `CLAUDE.md`, `TODO.md` and `memory-evolution.md`. No hunk
  overlaps this track's. Merge `dev` into `fix/owner-feedback-1` before the PR and re-run every
  suite.
- **`feat/mascot-page-b`** moves `PageHeader`'s title into a `PageTitle` view in
  `PageHeader.swift`, and its `PageTitleTests` pins exactly one `displayFont(` in that file. Resolve
  by putting this track's `.tracking(CicadaTheme.displayTracking(size: Self.size))`,
  `.lineLimit(1)` and `.minimumScaleFactor(0.8)` inside `PageTitle.body`, and move the R-FX12 width
  note into `PageTitle`'s doc. Its plan also spells the Sleep sentence's lead
  `displayFont(size: Self.leadSize)` and pins that text in a test: keep its spelling and pair
  `.tracking(CicadaTheme.displayTracking(size: Self.leadSize))`; the italic tail stays
  `displayFont(size: 22, italic: true)` either way.
- **`feat/settings-v3`** adds six roman `displayFont(size: 24)` titles. Whichever branch merges
  second, `testEveryRomanDisplayTitleCarriesItsTracking` fails until each gets
  `.tracking(CicadaTheme.displayTracking(size: 24))`. That is the lint doing its job, not a
  regression. It also adds `ThemeStore.shared.observeSystemAppearance()` directly under the two
  `CicadaApp.swift` lines this track deletes: keep its lines, drop the font ones.

---

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0
   failures**. If the order-dependent provenance case is the only red, re-run it alone and report
   both results.
2. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success, and
   `swift test 2>&1 | tail -20` → **0 failures**. `cd <worktree> && node --test
   app/CicadaApp/Tests/graph/*.test.js` → green.
3. Lint self-test: remove one `displayTracking` line and confirm `FontLiteralLintTests` fails. Put
   a stray `.ttf` under `Resources/` and confirm `testNoFontFileIsBundled` fails. Revert both.
4. `grep -rn "CicadaFonts\|InstrumentSerif" <worktree>/app` → nothing.
5. **Live** (the orchestrator installs the app and restarts the backend):
   - The startup log shows both migrations' counts, as numbers only.
   - The bank's `git log -6 --format='%s | %(trailers:key=Cicada-Author,valueonly,separator=%x2C)'`
     includes `Repair paper contexts … | cicada` and `Write placeholder summaries … | cicada` (a
     `State snapshot` commit may sit between or above them; print subjects only, never paths).
   - Print counts only, never names:
     `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" localhost:8000/graph | python3 -c 'import json,sys; g=json.load(sys.stdin); n=g["nodes"]; f=[x for x in n if x.get("isFacet")]; print(len(n), len(f), sum(1 for x in f if x.get("context")=="general" or ":" in (x.get("context") or "")), sum(1 for x in n if x.get("name","").startswith("folder:")))'`.
     The last two numbers must be **0**, and the node count must fall by roughly the paper-satellite
     count.
   - A restart runs neither migration again: no new commit.
6. **Live, by eye:**
   - At 1.0× and 1.4×, dark and light: the Graph legend shows only readable context names.
   - Papers sit by their project; a satellite click opens its subject's card.
   - A formerly placeholder page shows a sentence Summary and **What Cicada knows**, with no YAML.
   - A paper's description has no YAML.
   - Page titles are SF Pro semibold on one line (Sources, Integrations and a long per-source title
     at 1.4×); the empty-state title and the Reader title are SF.
   - The Sleep sentence is SF with an SF italic tail.
7. **PR body must state:**
   - The `/graph` ETag recipe is unchanged (`graph_edges.yaml` is its existing `edges` component).
     No sync component is added and no `extra` changed.
   - No LLM runs in any migration or read path.
   - The display face amends spec Decision 6 / R-M3 / Decision 16 by the owner's instruction.
   - The paper repair touches only the claims fence, which is not evidence text (G118). The
     placeholder rewrite changes a Summary line that no deterministic writer cites (`link_recon`
     cites media pages, which it skips); a hand-cited span would read `stale`, never mis-highlight.
   - The Merge notes: the tracking lint fails on `feat/settings-v3`'s (and `feat/mascot-page-b`'s)
     roman titles until each is paired, and `PageHeader` resolves into `PageTitle`.
