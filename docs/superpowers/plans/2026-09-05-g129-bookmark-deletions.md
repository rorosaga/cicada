# Bookmark deletions (G129 slice 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An unbookmark asks before it forgets. `sync_bookmarks` gains a per-channel
browser-then-vs-browser-now seen-set beside `url_index.json`, diffs it correctly (never against
memory, never across a folder-scope change), and turns each URL that left the browser into one
`removal` inbox item (`keep` / `remove`, `remove` archives — never deletes — the media entity). The
same open item renders twice: the unified Inbox, and a new Deletions subsection on the browser's
own source page. Slice 1 (watch + catch-up + status light, PR #52) is unaffected.

**Architecture:** Five tasks, backend-first. (1) `api/services/bookmark_seen.py` — a pure diff
function plus a small per-channel JSON file — and `bookmark_sync.sync_bookmarks` wiring it into a
new `propose_removals` step that writes inbox items directly (no Sleep involvement; this fires at
Awake time, from a live sync). (2) `removal` becomes a real, resolvable `InboxKind` on the API,
following the exact end-to-end recipe G113 slice 3 used for `divergence`/`normalization`. (3) The
same on Swift: enum case, theme colors in both palettes, a filter chip, and — new, because
`InboxKind`'s decode has never been forward-compat before — a `.unknown` fallback case so a future
kind this app build has never heard of degrades instead of blanking the whole inbox. (4) The
browser's `ChannelSourceView` gains a Deletions subsection that renders the same `InboxCardView` /
`QuestionView` / resolve path filtered to its own channel — one write path, two views — plus an
honest "N removals to review" line on Sync now. (5) Docs.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + git (`memory/`), MCP
server (`mcp/server.py`), SwiftUI + XCTest (`app/CicadaApp`).

**Spec:** `docs/goals/memory-evolution.md` row **G129** (both correctness rails are quoted verbatim
in Global Constraints below), `docs/superpowers/plans/2026-09-02-g113-feedback-ledger.md` Task 3
(the exact template this plan's Task 2 follows for adding an `InboxKind`),
`docs/superpowers/specs/…` n/a — no separate spec doc for this row; the backlog row *is* the spec.

## What the code actually does today (verified against `dev` @ `9149781`, G113 slices 3–7 merged as PR #59)

- **`api/services/bookmark_sync.py`** (303 lines): `sync_bookmarks(memory_path, *, chrome_data,
  safari_data, folders, ingest_fn)` calls `_batches()` → per-origin `RawItem` lists tagged
  `chrome-bookmark`/`safari-bookmark` (`CHANNEL_BY_ORIGIN` maps each to the `sync_state.json` key
  `chrome-bookmarks`/`safari-bookmarks`) → `filter_by_folders` → `media_ingestor.ingest_batch`
  (dedups on `sources/url_index.json`, keyed by `url_hash`) → returns
  `{new, skipped, sources: [{origin, channel, found, new, skipped}]}`. No seen-set exists anywhere;
  a URL that leaves a browser is invisible to this module today. The router
  (`api/routers/sources.py:318-395`, `POST /sources/sync-bookmarks`) stamps
  `sync_state.record_sync(channel, count=found)` per source after the call and otherwise passes the
  result straight through as `BookmarkSyncResponse(**result)`.
- **`api/services/media_ingestor.py`**: `url_hash(url) -> str` (`:174`, sha256[:12] of
  `normalize_url`) is the ONE hash function every writer must reuse.
  `load_url_index`/`save_url_index` (`:1535-1550`) read/write `sources/url_index.json`, keyed by
  hash, each entry `{media_entity_id, episode_id, url, title, media_type, thumbnail, saved_at,
  content_saved_at?}` — **no `origin` field on the index entry**; a URL's origin lives only on the
  media entity page's own `origin:` frontmatter key, written once at creation
  (`write_media_entity`) and never updated on a later duplicate hit.
- **`api/services/sync_state.py`**: `sync_state.json` is a flat per-channel dict
  (`{"last_sync", "count", "last_error"?, ...}`), read/written independently of any bank component
  wiring — it already rides the `sources` sync-service component (see below), so nothing new is
  needed there for a sibling file.
- **`api/services/sync_service.py:137-186`** (`components`): the `"sources"` component is
  `f"{src_count}:{src_max}:{url_index mtime}:{feeds mtime}:{calendars mtime}:{sync_state mtime}"`
  where `src_count, src_max = bank_index.dir_stamp(mp, "sources")`. **Verified this session by
  reading `bank_index._scan`'s actual body (`api/services/bank_index.py:49-59`, not assumed):**
  `_scan` filters `entry.name.endswith(".md")` — `dir_stamp` is `.md`-only, NOT "every file in the
  directory". A new `memory/sources/bookmark_seen.json` (a `.json` file) therefore does **not** ride
  `dir_stamp`, and no `.md` files live in `sources/` today, so `src_count`/`src_max` are unaffected
  either way. This is why the component string ALSO stats `url_index.json`/`feeds.yaml`/
  `calendars.yaml`/`sync_state.json` individually with explicit `file_mtime()` calls right next to
  `dir_stamp`'s output — those three non-.md files need their own stat for exactly the same reason
  `bookmark_seen.json` would. **What actually keeps the `"sources"` component live for this feature
  is unrelated to `dir_stamp`:** the router (`api/routers/sources.py`, `POST /sources/sync-bookmarks`)
  already calls `sync_state.record_sync(memory_path, channel, count=...)` for every source it
  touches on every sync — unconditionally, regardless of whether a removal was proposed — which
  writes `sync_state.json`, and THAT file's `file_mtime()` is one of the four already-explicit terms
  in the `"sources"` string above. So the component ticks on every real sync call for a
  pre-existing reason that has nothing to do with this row; `bookmark_seen.json`'s own mtime rides no
  component at all, which is harmless because nothing reads that file through any API endpoint — Ruling
  1 below draws the correct conclusion (no `sync_service.py` change needed) from this evidence.
- **`app/…/Sync/VersionVector.swift`**: `"sources"` maps to `[.sources, .feeds, .calendars,
  .channels, .sourcesOverview]`; `"inbox"` maps to `[.inbox, .graph, .status]`. A removal item is an
  **inbox** write (`inbox_mtime` moves via `sync_service.inbox_mtime`, unrelated to `dir_stamp`), and
  every actual bookmark sync already advances `sync_state.json` (see above) — a **sources** write —
  regardless of whether it proposed a removal. Both are already-wired components, so the Deletions
  subsection (which reads `store.inbox`) and the channel card both refresh on their existing domains.
  **Ruling 1** makes this the second half: zero Swift/`sync_service.py` changes needed for this
  feature to be live-visible.
- **`api/models/schemas.py:875-886`** (`InboxKind`): `decay, conflict, clarification,
  merge_suggestion, divergence, normalization` — six kinds (G113 slices 1–2 shipped `divergence`/
  `normalization` end to end in PR #59, per the exact template this plan's Task 2 reuses).
  `InboxItem` (`:948-983`) carries `channel`-shaped info nowhere yet.
  `BookmarkSyncResponse` (`:1481-1484`) is `{new, skipped, sources}` only.
- **`api/services/inbox_service.py`** (verified line numbers, this session):
  - `_required_input_for` (`:49-52`): `choice` for `decay, conflict, divergence, normalization`,
    `merge` for `merge_suggestion`, else `freetext`.
  - `_item_from_file` (`:57-…`): `allow_other` defaults `kind in ("conflict", "clarification")`;
    `allow_defer` defaults `kind in ("conflict", "clarification", "divergence")` (`:80-81`) — both
    are only *defaults* used when the frontmatter omits the key; an item that writes the key
    explicitly (this plan's items do) is unaffected.
  - `_action_label` (`:360-388`): per-kind action-naming, switches on `kind`.
  - `_NEUTRAL_LABELS = ("defer", "skip", "remind_later")` (`:395`); `_verdict` (`:398-441`): per-kind
    agreed/overruled/neutral table, `label in _NEUTRAL_LABELS` checked first.
  - `recommended_key` (`:512-…`): `if kind in ("merge_suggestion", "clarification"): return None`
    (`:536`) — the two kinds that never carry an initial-highlight proposal.
  - `resolve()` (`:718-…`): parses the item, runs `_normalize_decay_request` (decay-only) and the
    kind-agnostic `defer`/`remind_later` early-outs, then computes `label = _action_label(...)` and
    `feedback = _feedback_refs(...)` **before** the kind dispatch (`:749-776`, verified this
    session):
    ```python
    extra_lines: list[str] = []
    if kind == "decay":
        entity_id, skipped = await _resolve_decay(path, parsed, request, settings)
    elif kind == "conflict":
        entity_id, skipped, extra_lines = await _resolve_conflict(path, parsed, request, settings)
    elif kind == "divergence":
        entity_id, skipped, extra_lines = await _resolve_divergence(path, parsed, request, settings, item_id)
    elif kind == "normalization":
        entity_id, skipped, extra_lines = await _resolve_normalization(path, parsed, request, settings, item_id)
    elif kind in ("clarification", "merge_suggestion"):
        entity_id, skipped, extra_lines = await _resolve_clarification(path, parsed, request, settings)
    else:
        raise HTTPException(400, f"Unknown kind {kind}")
    ```
    then unconditionally `_emit_resolution(...)`, then (`:786-798`, verified this session):
    ```python
    change = "updated"
    if kind == "decay" and label == "archive":
        change = "status archived"
    elif kind == "decay" and label == "keep_active":
        change = "status active"
    await git_service.commit_resolution(settings.memory_path, entity_id,
        f"inbox/{kind}/resolved:{label}", extra_lines, change=change)
    ```
  - `_resolve_decay` (`:857-919`) is the template for a kind with **no free text, no defer beyond
    the generic one, two named actions** — the shape `removal` needs, closer than
    `_resolve_conflict`'s claim-supersession machinery.
  - `_feedback_refs` (`:600-…`) has no `removal` branch needed: its default return
    (`winner=None, losers=[], extractor_confidence=None, extractor_model=None`) is exactly correct
    for a kind with no claim behind it — it falls through every `elif kind == …` untouched and the
    final `if lookup_id:` guard is `None`-guarded already.
- **`api/services/inbox_context.py`** (`InboxContext.cause_for`, `:225-…`): three episode-anchored
  tiers (item → claim → entity), each requiring `self.episode(ep_id)` to resolve — **a `removal`
  item has no episode; it was raised by a browser sync, not a conversation.** Falling through
  unmodified would serve `[ no source recorded ]` for every removal card, which is honest but throws
  away real provenance the item DOES carry (`synced_at`, `channel`). This needs one new branch.
- **`api/services/inbox_generator.py`**: `find_open(memory_path, kind, entity_id, predicate=None)`
  (`:39-71`) — dedup lookup, keyed by `dedup_key(kind, fm)` which for any kind outside
  `conflict`/`clarification`/`merge_suggestion` is `(entity_id, "")` (`:17-35`, the "anything else"
  branch) — **already exactly the idempotency key `removal` needs**, no change to either function.
  `next_inbox_num` — actually lives in `inbox_service.py:38-44` (public, `def next_inbox_num`), NOT
  `inbox_generator.py` (that module's own `_next_inbox_num` at `:459-465` is a private duplicate used
  only by `write_claim_nudges`) — this plan's writer uses the public one.
- **Swift `InboxKind`** (`Models/InboxItem.swift:6-38`): plain `enum InboxKind: String, Codable`,
  **no fallback case, no custom decoder** — an unrecognized raw value throws
  `DecodingError.dataCorrupted` out of `InboxItem.init(from:)`, which propagates out of
  `[InboxItem]`'s array decode and drops **every** pending item, not just the unrecognized one. This
  predates the tolerance pattern already used by `EntityType` (`Models/Entity.swift:3-39`, call-site
  `try?` + `.unknown`) and `Epistemic`/`SourceTrust` (`Models/Claim.swift:57-75`, a custom
  `init(from:)` on the enum itself, `Type(rawValue:) ?? .unknown`). `InboxCardView.swift` and
  `QuestionView.swift` are **kind-agnostic already** (verified this session): the action row routes
  on `item.informational` / `!item.options.isEmpty` / `item.requiredInput`, never on `item.kind`
  directly — a `removal` item with two options and no `informational` flag renders through
  `QuestionView` with **zero changes to either file**.
- **`Views/Inbox/InboxListView.swift:108-111`** (`orderedKinds`): hardcodes
  `[.decay, .conflict, .clarification, .mergeSuggestion]` for the filter chips — **`divergence`/
  `normalization` are not in this list either** (a pre-existing gap from G113 slice 3, not this
  row's to fix — see Not in scope).
- **`app/…/Services/APIClient.swift:334-338`** (`BookmarkSyncResult`): plain `struct … : Codable`
  with a synthesized memberwise init — `Tests/CicadaAppTests/BrowserImportModelTests.swift:76-78`
  constructs it with the 3-arg form (`BookmarkSyncResult(new:skipped:sources:)`) directly, so adding
  fields must preserve that call site (Task 4 rail).
- **`app/…/Sync/Mutations.swift:534-548`** (`SyncBrowserBookmarks`): `refreshDomains: [.channels,
  .sources, .status]` — **no `.inbox`** — a sync that proposes a removal today would not force an
  immediate Deletions-subsection refresh (it would still arrive via the next SSE/poll tick, since
  `inbox_mtime` moved, but not instantly on the mutation's own completion).
- **`app/…/Views/Sources/ChannelSourceView.swift`** (122 lines): `stateCard` → optional
  `folderCounts` → the Feed-filtered `items` list. No inbox awareness at all today.

## Global Constraints

- Work ONLY in `<worktree>/` (branch
  `feat/bookmark-deletions`, based on `dev` @ `9149781`). Every shell command is
  `cd <worktree>/ && <cmd>` with
  absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never an unquoted
  `--include=*.ext` (zsh globbing) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`,
  `~/Library`, or `~/.claude/projects`. Fixtures are synthetic: `example.com`/`example.org` URLs,
  `bob-example`/`alpha-project`-style entity ids.
- Python: `api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; full `api/tests` must be
  **0 failures** (2014 passed 2026-09-03). One known order-dependent case:
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` passes
  alone — if it's the ONLY red in a full run, re-run it alone and report both results.
- Swift: `cd …/app/CicadaApp && swift build 2>&1 | tail -5` must succeed;
  `swift test 2>&1 | tail -20` must report 0 failures (SourceKit diagnostics naming OTHER worktrees
  are noise).
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin/PR
  comments.
- **The two correctness rails, quoted from the G129 row (binding, verbatim):**
  1. *"the diff is only valid INSIDE the folder scope that was synced — with `folders:` selection,
     everything outside the chosen prefixes looks deleted; compute removals only within the
     selected prefixes, and when a sync used different folders than the previous seen-set, do not
     propose anything (record why)."*
  2. *"the diff is browser-then vs browser-now, NEVER browser vs memory — a URL the person chose to
     keep has already left the browser and a memory-based diff would re-propose it after every sync
     forever. So: one small per-channel seen-set beside `url_index.json`."*
- **Never read `~/Library` from the backend** — the app reads bookmark files and posts bytes
  (unchanged, slice 1 rail); this plan's tests use synthetic in-memory bytes exactly like the
  existing `test_bookmark_sync.py` fixtures.
- **A removal never deletes a page.** `remove` sets `status: archived` on the media entity; the page,
  its claims (if any) and its git history all survive — evergreen, claim-linked, and git already
  keeps every version regardless.
- **Font rule (G130, PR #54, still binding):** never write a literal `.font(.system(size:))` /
  `Font.system(size:)` in Swift — `CicadaTheme.font(size:weight:design:)` only.
  `FontLiteralLintTests` fails the suite on a violation. This plan adds no new Swift text rendering
  that isn't already routed through existing `CicadaTheme` font tokens (`InboxCardView`/
  `QuestionView` are reused unmodified), so no new call site is at risk — verify this stays true when
  writing Task 4's Deletions section header.
- **Privacy rule:** no owner name, no real URLs, no bank content in docs/commits/PR body; fixtures
  use `example.com`/`example.org`.
- Docstrings explain WHY, citing the G-row; match the density of the files touched.
- Line numbers above are from this session's read of `dev` @ `9149781` and may drift a few lines as
  tasks land — read the cited code before editing, same as every prior plan in this repo.

## Rulings (binding — decided here, do not re-derive)

- **R1 — no `sync_service`/`VersionVector` changes needed.** Verified by reading the actual code
  (see "What the code actually does today"): a `removal` inbox item rides the `"inbox"` component via
  `inbox_mtime`, unchanged. `sources/bookmark_seen.json` itself rides NO component (`dir_stamp` is
  `.md`-only, per the corrected reading above) — but every real sync already writes `sync_state.json`
  through the router's existing, unconditional `sync_state.record_sync(...)` call, and that file's
  mtime is one of the four already-explicit terms in the `"sources"` component string. So the
  `"sources"` component already ticks on every actual sync pass for a reason that predates this row,
  and both components already map to the Swift domains this feature needs (`.sourcesOverview`/
  `.channels` and `.inbox` respectively). Stop here — adding an explicit key for either would be
  redundant plumbing, not a fix for a real gap; do NOT add a `bookmark_seen.json` term to the
  `"sources"` component string either — nothing reads that file through any API endpoint, so there is
  nothing for a client to notice.
- **R2 — the hint ("also saved from…") is computed once, at proposal time, from `url_index`'s
  existing per-entity `origin:` frontmatter — never a live cross-channel seen-set scan.** The G129
  row's own reasoning is that `origin` "records only whoever got there first" — i.e. it is a weak
  signal on its own, but it is exactly the signal available at the moment a removal is proposed: if
  the media entity's `origin:` differs from the channel currently proposing removal, some other path
  (a manual save, the OTHER browser) is where it actually came from, and is very likely still true.
  Computed once rather than re-derived at read time like G97's cause/G98's `informational` — those
  are correctness-relevant (a stale cause misattributes provenance); this is a courtesy aside with no
  correctness stakes, and a live cross-channel scan would require reading `bookmark_seen.json` on
  every `GET /inbox`, real cost for a "nice to know."
- **R3 — verdict is `neutral` for both `keep` and `remove` (decided, not "keep=overruled").** The
  brief poses this as an open question and answers it: the proposal came from the **browser's own
  diff**, not from the extractor's judgement — there is no model belief to agree or disagree with,
  the same reasoning `_verdict`'s conflict branch already uses for an entity-path conflict with no
  `claim_id` ("there is no extractor belief to agree or disagree with, and calling it an overrule
  would skew the feedback ratio against a model that never took a side"). `recommended_key` returns
  `None` for `removal` for the identical reason — Sleep proposed nothing here; the browser did.
- **R4 — `removal`'s options are written directly to frontmatter at proposal time, `keep` first.**
  Unlike `decay` (whose "still relevant?" phrasing needs the subject's *live* `last_referenced` and
  is therefore synthesised at read time, R5 of G115), a removal's `keep`/`remove` pair and its
  question text (`"It was removed from {Browser}."`) never go stale — the browser and the fact of
  removal are both fixed at the moment of proposal. Writing them once, like every other pre-G115
  question kind, is simpler and avoids adding a fourth read-time-synthesis special case next to
  decay's. **`keep` is listed first** so `QuestionSelection`'s documented fallback (`initialIndex:
  nil` → index `0`, verified in `Models/QuestionSelection.swift:31-35`) makes `⏎` resolve to `keep`
  in the absence of a Recommended marker (R3 guarantees there never is one) — the safe,
  non-destructive default when nothing is highlighted.
- **R5 — the seen-set always advances to the current sync's hashes, regardless of the person's
  eventual answer.** The seen-set answers one question only — "was this URL in the browser last
  time we looked" — never "has the person settled this." Once a URL drops out of the browser, the
  NEXT sync's seen-set (with or without the person having resolved the pending item yet) already
  lacks it, so the diff against THAT sync never re-proposes it. This is what makes "a kept URL is
  never re-proposed" true without any bookkeeping on the `keep`/`remove` answer itself, and it is
  the literal test the brief asks for (Task 1 test list, "second sync without it in the browser → no
  new item").
- **R6 — a folder-scope mismatch is silent (not a recorded skip reason) on a channel's very first
  sync.** `diff_removed` returns `None` both when there is no previous seen-set (nothing to diff
  yet — expected, not an error) and when the folder scope changed since a previous sync exists. Only
  the second case is worth a `removals_skipped` reason; the first would otherwise falsely read as
  "something went wrong" on every channel's first-ever sync.
- **R7 — an inbox item that both browsers would propose in the same sync pass collapses to ONE
  item, attributed to whichever origin `_batches` processes first (Chrome, then Safari).** Rare (it
  needs the exact same URL removed from both browsers in one sync), and `find_open`'s existing
  per-entity dedup already prevents a duplicate question — accepted as a minor, disclosed cosmetic
  edge case (the card may say "removed from Chrome" when it also left Safari) rather than plumbing a
  second attribution path for it.
- **R8 — `InboxKind`'s new `.unknown` fallback case is added in this plan because `removal` is the
  vehicle that exposes the gap, but the fix itself is general** (matches `EntityType`/`Epistemic`/
  `SourceTrust`'s existing forward-compat pattern in the same codebase) — any future kind this app
  build has never heard of degrades to one greyed-out card instead of blanking the entire inbox.
  Colour/label for `.unknown` reuse the existing muted text tokens (`Dark.textTertiary` /
  `Light.textTertiary`) rather than new hex — it is a "something newer exists" bucket, not a real
  category with its own visual identity.
- **R9 — `removal`'s theme colour is decay's amber, darkened**, per the brief's own suggestion: a
  retraction reads as a graver cousin of decay's fade rather than a wholly new hue, consistent with
  G113 slice 3's "no new hue budget" precedent for `divergence`/`normalization`.
- **Not fixed here (disclosed):** `InboxListView.orderedKinds` already omits `divergence`/
  `normalization` chips (a pre-existing G113 gap, not this row's). This plan adds `removal` to that
  same array and stops — widening scope to also add the two missing chips is a separate, unrelated
  fix belonging to G113's own row.

## Not in scope

- Arc, Brave, Firefox (G119) — this plan's writer keys off the existing `CHANNEL_BY_ORIGIN` map
  (Chrome/Safari only); generalizing is free once G119 adds a browser to that map, but no new browser
  is added here.
- iCloud tabs removals — a tab closing is not an unsave (existing G129 row ruling, unchanged).
- A Chrome extension / any true push mechanism — slice 1's territory, already shipped, unchanged.
- Feeding the `resolution` ledger's per-kind rates back into extraction (G78) — out of scope for
  every inbox kind, not just this one.
- Fixing `InboxListView.orderedKinds`'s pre-existing omission of `divergence`/`normalization` chips
  (Ruling, above) — that's a G113 gap.
- A live cross-channel "still bookmarked elsewhere" scan (Ruling R2) — the hint is a point-in-time
  courtesy, not a tracked fact.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/bookmark_seen.py` (new) | `read_seen`, `write_channel_seen`, `diff_removed` — the pure diff + the small JSON file |
| `api/services/bookmark_sync.py` | `sync_bookmarks(..., propose_removals=True)`, `_propose_removals`, `_BROWSER_LABEL` |
| `api/models/schemas.py` | `InboxKind.removal`; `InboxItem.channel`; `BookmarkSyncResponse.removals_proposed/removals_skipped` |
| `api/services/inbox_service.py` | `_required_input_for`, `_action_label`, `_verdict`, `recommended_key`, `resolve()` dispatch + `change`, new `_resolve_removal` |
| `api/services/inbox_context.py` | `cause_for`'s new `removal` tier-`item` branch |
| `api/tests/test_bookmark_seen.py` (new) | pure diff/seen-set tests, both rails |
| `api/tests/test_bookmark_sync.py` | extend: removal-proposal integration, idempotency, hint, folder-scope refusal; fix 3 pre-existing strict-equality assertions |
| `api/tests/test_inbox_removal.py` (new) | load/resolve/cause/verdict for the new kind |
| `api/tests/test_mcp_inbox_questions.py` | one added passthrough test (documents "no MCP code change needed") |
| `app/…/Models/InboxItem.swift` | `InboxKind.removal` + `.unknown` + custom `init(from:)`; `InboxItem.channel` |
| `app/…/Theme/CicadaTheme.swift` | `Dark.inboxColor`/`Light.inboxColor` gain `.removal`/`.unknown` |
| `app/…/Views/Inbox/InboxListView.swift` | `orderedKinds` gains `.removal` |
| `app/…/Services/APIClient.swift` | `BookmarkSyncResult.removalsProposed/removalsSkipped` |
| `app/…/Models/BrowserImport.swift` | `BrowserImportSummary.bookmarks` feedback line |
| `app/…/Sync/Mutations.swift` | `SyncBrowserBookmarks.refreshDomains` gains `.inbox` |
| `app/…/Views/Sources/ChannelSourceView.swift` | Deletions subsection |
| `app/…/Tests/CicadaAppTests/InboxKindDecodingTests.swift` | extend: `.removal` decode + `.unknown` fallback |
| `app/…/Tests/CicadaAppTests/BrowserImportModelTests.swift` | extend: new fields decode/default |
| `app/…/Tests/CicadaAppTests/InboxRemovalTests.swift` (new) | `InboxItem.openRemovals` pure filter |
| `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`, `docs/goals/working-method.md`, `CLAUDE.md` | docs |

---

### Task 1: Backend seen-set + diff + removal proposal

**Files:**
- New: `api/services/bookmark_seen.py`, `api/tests/test_bookmark_seen.py`
- Modify: `api/services/bookmark_sync.py`
- Modify: `api/tests/test_bookmark_sync.py`

**Interfaces:**
- Produces: `bookmark_seen.read_seen(memory_path) -> dict`,
  `bookmark_seen.write_channel_seen(memory_path, channel, *, folders, hashes, at=None) -> None`,
  `bookmark_seen.diff_removed(previous: dict | None, current_hashes: list[str], *,
  previous_folders, current_folders) -> list[str] | None` (pure; `None` = refuse).
  `bookmark_sync.sync_bookmarks(..., propose_removals: bool = True)` now also returns
  `removals_proposed: int` and `removals_skipped: str | None`.
- Consumes: `media_ingestor.url_hash`, `media_ingestor.load_url_index`, `inbox_service.next_inbox_num`,
  `inbox_generator.find_open`, `episode_ids.utc_now_iso`, `markdown_parser.write`.

- [ ] **Step 1: Write `api/services/bookmark_seen.py`**

```python
"""Per-channel "what the browser showed us last sync" seen-set (G129 slice 2).

Sibling to ``sources/url_index.json`` but answers a different question:
``url_index`` answers "have we ever ingested this URL" (forever); this answers
"was this URL in THIS channel's browser file the last time we looked" — the
only thing that makes a removal proposal correct rather than destructive.

Shape, ``sources/bookmark_seen.json``::

    {"chrome-bookmarks": {"folders": ["Reading"] | null, "hashes": ["ab12cd34ef56", ...], "at": "2026-09-05T10:00:00Z"},
     "safari-bookmarks": {...}}

**Rail 1 — the diff is only valid inside the folder scope that was synced.**
With a ``folders:`` selection, everything outside the chosen prefixes was
never looked at this pass and would look deleted for the wrong reason.
:func:`diff_removed` refuses (returns ``None``) whenever the current sync's
folder scope differs from the previous sync's recorded scope — the two sets
are simply not comparable, and the caller must record why rather than guess.

**Rail 2 — the diff is browser-then vs browser-now, NEVER browser vs memory.**
A URL the person chose to keep has already left the browser; diffing against
``url_index.json`` (which keeps every URL forever) would re-propose it after
every subsequent sync. Diffing against the PREVIOUS seen-set instead, and
always advancing the seen-set to the CURRENT sync's hashes regardless of what
the person eventually answers, means a URL that has left the browser drops out
of ``hashes`` on the very sync that notices it — the next sync's diff (browser
still lacking it, seen-set already lacking it) is empty, so nothing is ever
re-proposed. No bookkeeping of the person's answer is needed for this to hold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api.services import episode_ids

SEEN_FILENAME = "bookmark_seen.json"


def seen_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SEEN_FILENAME


def read_seen(memory_path: Path) -> dict:
    path = seen_path(memory_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_channel_seen(
    memory_path: Path,
    channel: str,
    *,
    folders: list[str] | None,
    hashes: list[str],
    at: str | None = None,
) -> None:
    """Replace ``channel``'s entry with the CURRENT sync's scope + hashes.

    Always called after a sync attempt for a channel that was actually looked
    at this pass — regardless of whether any removal was proposed or the
    person has answered one yet (Rail 2's "always advance" half).
    """
    state = read_seen(memory_path)
    state[channel] = {
        "folders": sorted(set(folders)) if folders else None,
        "hashes": sorted(set(hashes)),
        "at": at or episode_ids.utc_now_iso(),
    }
    path = seen_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_folders(folders: list[str] | None) -> list[str] | None:
    """``None``, ``[]`` and ``[""]`` all mean "no filter" (matches
    ``bookmark_sync.filter_by_folders``'s own truthiness/``""`` rules) and
    compare equal; any other list compares as a sorted, deduped set so
    selection order never spuriously trips the mismatch check."""
    if not folders or "" in folders:
        return None
    return sorted(set(folders))


def diff_removed(
    previous: dict[str, Any] | None,
    current_hashes: list[str],
    *,
    previous_folders: list[str] | None,
    current_folders: list[str] | None,
) -> list[str] | None:
    """Hashes present in ``previous`` but missing from ``current_hashes``.

    Pure. Returns ``None`` (refuse — Rail 1/2) when there is no previous seen
    entry to diff against (nothing synced before; not an error, R6) or when
    the current sync's folder scope differs from the previous sync's (Rail 1
    — a real scope change, worth recording as a reason). Otherwise returns the
    sorted list of hashes that dropped out — possibly empty.
    """
    if previous is None:
        return None
    if _normalize_folders(previous_folders) != _normalize_folders(current_folders):
        return None
    prev_hashes = set(previous.get("hashes") or [])
    current = set(current_hashes)
    return sorted(prev_hashes - current)
```

- [ ] **Step 2: Write `api/tests/test_bookmark_seen.py`**

```python
"""G129 slice 2: the per-channel seen-set + its diff — both correctness rails."""
from __future__ import annotations

from pathlib import Path

from api.services import bookmark_seen


def test_diff_removed_none_with_no_previous_seen_set():
    assert bookmark_seen.diff_removed(
        None, ["a"], previous_folders=None, current_folders=None
    ) is None


def test_diff_removed_finds_dropped_hashes():
    previous = {"hashes": ["a", "b", "c"], "folders": None}
    assert bookmark_seen.diff_removed(
        previous, ["a", "c"], previous_folders=None, current_folders=None
    ) == ["b"]


def test_diff_removed_empty_when_nothing_dropped():
    previous = {"hashes": ["a", "b"], "folders": None}
    assert bookmark_seen.diff_removed(
        previous, ["a", "b", "z"], previous_folders=None, current_folders=None
    ) == []


def test_diff_removed_refuses_on_folder_scope_change():
    previous = {"hashes": ["a", "b"], "folders": ["Reading"]}
    assert bookmark_seen.diff_removed(
        previous, ["a"], previous_folders=["Reading"], current_folders=["Other"]
    ) is None


def test_diff_removed_none_and_empty_list_and_blank_string_folders_are_equivalent():
    previous = {"hashes": ["a"], "folders": None}
    for current in (None, [], [""]):
        assert bookmark_seen.diff_removed(
            previous, ["a"], previous_folders=None, current_folders=current
        ) == []


def test_diff_removed_folder_order_does_not_matter():
    previous = {"hashes": ["a"], "folders": ["B", "A"]}
    assert bookmark_seen.diff_removed(
        previous, ["a"], previous_folders=["B", "A"], current_folders=["A", "B"]
    ) == []


def test_write_and_read_channel_seen_round_trip(tmp_path: Path):
    memory = tmp_path / "memory"
    bookmark_seen.write_channel_seen(
        memory, "chrome-bookmarks", folders=["Reading"], hashes=["b", "a"], at="2026-09-05T10:00:00Z"
    )
    state = bookmark_seen.read_seen(memory)
    assert state["chrome-bookmarks"] == {
        "folders": ["Reading"], "hashes": ["a", "b"], "at": "2026-09-05T10:00:00Z",
    }
    assert (memory / "sources" / "bookmark_seen.json").exists()


def test_write_channel_seen_channels_are_independent(tmp_path: Path):
    memory = tmp_path / "memory"
    bookmark_seen.write_channel_seen(memory, "chrome-bookmarks", folders=None, hashes=["a"], at="t1")
    bookmark_seen.write_channel_seen(memory, "safari-bookmarks", folders=None, hashes=["b"], at="t2")
    state = bookmark_seen.read_seen(memory)
    assert set(state) == {"chrome-bookmarks", "safari-bookmarks"}
    assert state["chrome-bookmarks"]["hashes"] == ["a"]


def test_read_seen_corrupt_file_degrades_to_empty(tmp_path: Path):
    memory = tmp_path / "memory"
    (memory / "sources").mkdir(parents=True)
    (memory / "sources" / "bookmark_seen.json").write_text("not json", encoding="utf-8")
    assert bookmark_seen.read_seen(memory) == {}
```

- [ ] **Step 3: Run to verify green (this is a new module — nothing to fail-then-fix, but confirm no import errors)**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_bookmark_seen.py -q -p no:cacheprovider`
Expected: 8 passed.

- [ ] **Step 4: Wire `sync_bookmarks` — read the module docstring + `sync_bookmarks` (`api/services/bookmark_sync.py`) before editing.** Add imports:

```python
from datetime import date

from api.services import bookmark_seen, episode_ids, inbox_generator, inbox_service, markdown_parser
```

Add, near `CHANNEL_BY_ORIGIN`:

```python
# Display label for a removal item's question text and its hint (R2) — the
# same two origins `_tag_origin` ever stamps.
_BROWSER_LABEL = {"chrome-bookmark": "Chrome", "safari-bookmark": "Safari"}
```

- [ ] **Step 5: Add `_propose_removals`**

```python
def _propose_removals(
    memory_path: Path, *, origin: str, channel: str, removed_hashes: list[str], at: str,
) -> int:
    """One ``removal`` inbox item per hash in ``removed_hashes`` that still
    names a live, non-archived media entity and has no open removal item
    already (idempotency — a second sync before the person answers must not
    spawn a second question for the same URL; ``inbox_generator.find_open``'s
    existing ``(entity_id, "")`` dedup key, unchanged, already covers this).

    ``remove`` never deletes the page (G129 row rule) — that happens on
    resolve, not here; this function only ever proposes. Returns the count of
    items actually written.
    """
    idx = media_ingestor.load_url_index(memory_path)
    inbox_dir = memory_path / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    next_num = inbox_service.next_inbox_num(inbox_dir)
    browser = _BROWSER_LABEL.get(origin, origin)
    written = 0
    for h in removed_hashes:
        entry = idx.get(h)
        entity_id = str((entry or {}).get("media_entity_id") or "")
        if not entity_id:
            continue  # never ingested, or the index entry is gone — nothing to ask about
        entity_path = memory_path / "entities" / f"{entity_id}.md"
        if not entity_path.exists():
            continue
        try:
            efm = markdown_parser.parse(entity_path).frontmatter
        except Exception:
            continue
        if str(efm.get("status", "active") or "active") in ("archived", "dropped"):
            continue  # already gone — nothing left to ask
        if inbox_generator.find_open(memory_path, "removal", entity_id) is not None:
            continue  # already asked, still pending
        entity_name = str(efm.get("name") or entry.get("title") or entity_id)
        # R2: the entity's own first-save origin vs THIS sync's origin — a
        # mismatch means some other path (a manual save, the other browser)
        # is where it actually came from, worth surfacing on the card.
        entity_origin = str(efm.get("origin") or "") or None
        hint = f"Also saved via {entity_origin}" if entity_origin and entity_origin != origin else None
        item_id = f"inbox-{next_num:03d}"
        next_num += 1
        frontmatter = {
            "kind": "removal",
            "required_input": "choice",
            "status": "pending",
            "priority": 0.4,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "title": f"Still keep {entity_name}?",
            "created_date": str(date.today()),
            "question": f"It was removed from {browser}.",
            # R4: keep first — QuestionSelection's documented no-recommendation
            # fallback highlights index 0.
            "options": [
                {"key": "keep", "label": "Keep"},
                {"key": "remove", "label": "Remove"},
            ],
            "allow_other": False,
            "allow_defer": True,
            "channel": channel,
            "browser": browser,
            "url": str(entry.get("url") or ""),
            "synced_at": at,
            "hint": hint,
            "trigger": "sync/bookmark_removal",
        }
        markdown_parser.write(
            inbox_dir / f"{item_id}.md", frontmatter,
            f"{entity_name} was removed from {browser}.",
        )
        written += 1
    return written
```

- [ ] **Step 6: Wire the diff + seen-set write into `sync_bookmarks`**

Replace the per-source loop body (the exact text quoted in "What the code actually does today"
above) with:

```python
    sources: list[dict[str, Any]] = []
    total_new = 0
    total_skipped = 0
    total_removals_proposed = 0
    removals_skip_reasons: list[str] = []

    at = episode_ids.utc_now_iso()
    prev_seen = bookmark_seen.read_seen(memory_path) if propose_removals else {}

    for origin, items in _batches(chrome_data, safari_data):
        items = filter_by_folders(items, folders) if folders else items
        channel = CHANNEL_BY_ORIGIN[origin]
        if not items:
            sources.append({"origin": origin, "channel": channel, "found": 0, "new": 0, "skipped": 0})
        else:
            created, duplicates = await fn(items, memory_path, from_bookmark_file=True)
            total_new += created
            total_skipped += duplicates
            sources.append({
                "origin": origin, "channel": channel,
                "found": len(items), "new": created, "skipped": duplicates,
            })

        if propose_removals:
            current_hashes = sorted({media_ingestor.url_hash(i.url) for i in items})
            prev_entry = prev_seen.get(channel)
            removed = bookmark_seen.diff_removed(
                prev_entry, current_hashes,
                previous_folders=(prev_entry or {}).get("folders"),
                current_folders=folders,
            )
            if removed is None:
                if prev_entry is not None:  # R6: silent on a channel's first-ever sync
                    removals_skip_reasons.append(f"{channel}: folder scope changed since the last sync")
            elif removed:
                total_removals_proposed += _propose_removals(
                    memory_path, origin=origin, channel=channel, removed_hashes=removed, at=at,
                )
            bookmark_seen.write_channel_seen(memory_path, channel, folders=folders, hashes=current_hashes, at=at)

    return {
        "new": total_new, "skipped": total_skipped, "sources": sources,
        "removals_proposed": total_removals_proposed,
        "removals_skipped": "; ".join(removals_skip_reasons) or None,
    }
```

Add `propose_removals: bool = True` to `sync_bookmarks`'s signature (after `ingest_fn`). Update the
function's docstring to describe the new return keys and cite both rails (mirror the module
docstring's language — don't restate it differently).

- [ ] **Step 7: Fix the three pre-existing strict-equality assertions in `api/tests/test_bookmark_sync.py`**

`test_sync_bookmarks_reports_new_and_skipped_via_injected_ingest_fn` (`:156-164`) and
`test_sync_bookmarks_no_data_provided_ingests_nothing` (`:176`): add
`"removals_proposed": 0, "removals_skipped": None` to both literal `result == {...}` dicts.
`test_sync_bookmarks_endpoint_no_body_reads_local_files_best_effort` (`:334`): change
`assert body == {"new": 0, "skipped": 0, "sources": []}` to
`assert body == {"new": 0, "skipped": 0, "sources": [], "removalsProposed": 0, "removalsSkipped": None}`.

- [ ] **Step 8: Run the full existing file to confirm nothing else broke**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_bookmark_sync.py -q -p no:cacheprovider`
Expected: all passing (same count as before, plus the 3 fixed assertions still pass).

- [ ] **Step 9: Add the new integration tests to `api/tests/test_bookmark_sync.py`** — append at the
  end of the file (reuse `_offline_enrich`/`run` already defined there):

```python
# --- G129 slice 2: removal proposals -----------------------------------------

def _one_url_chrome_json():
    return {
        "version": 1,
        "roots": {
            "bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": [
                {"type": "url", "name": "Example One", "url": "https://example.com/one"},
            ]},
            "other": {"type": "folder", "name": "Other bookmarks", "children": []},
        },
    }


def test_sync_bookmarks_proposes_removal_when_a_url_drops_out(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"

    r1 = run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(CHROME_BOOKMARKS_JSON).encode()))
    assert r1["removals_proposed"] == 0
    assert r1["removals_skipped"] is None

    # Second sync: only one of the two Chrome bookmarks survives.
    r2 = run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(_one_url_chrome_json()).encode()))
    assert r2["removals_proposed"] == 1
    assert r2["removals_skipped"] is None

    files = sorted((memory / "inbox").glob("inbox-*.md"))
    assert len(files) == 1
    fm = markdown_parser.parse(files[0]).frontmatter
    assert fm["kind"] == "removal"
    assert fm["channel"] == "chrome-bookmarks"
    assert fm["browser"] == "Chrome"
    assert [o["key"] for o in fm["options"]] == ["keep", "remove"]
    assert fm["question"] == "It was removed from Chrome."

    # Third sync, SAME one-url state: idempotent — no second item.
    r3 = run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(_one_url_chrome_json()).encode()))
    assert r3["removals_proposed"] == 0
    assert len(list((memory / "inbox").glob("inbox-*.md"))) == 1


def test_removed_url_is_never_reproposed_once_it_stays_gone(tmp_path, monkeypatch):
    """R5: the seen-set advances regardless of whether the person answered —
    a URL that stays out of the browser is never asked about twice."""
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(CHROME_BOOKMARKS_JSON).encode()))
    run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(_one_url_chrome_json()).encode()))
    before = sorted((memory / "inbox").glob("inbox-*.md"))
    for _ in range(3):
        r = run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(_one_url_chrome_json()).encode()))
        assert r["removals_proposed"] == 0
    assert sorted((memory / "inbox").glob("inbox-*.md")) == before


def test_folder_scope_change_refuses_and_records_why(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    data = plistlib.dumps(SAFARI_PLIST_TREE)
    run(bookmark_sync.sync_bookmarks(memory, safari_data=data, folders=["BookmarksBar"]))
    r2 = run(bookmark_sync.sync_bookmarks(memory, safari_data=data, folders=["BookmarksBar/Big Folder"]))
    assert r2["removals_proposed"] == 0
    assert r2["removals_skipped"] is not None
    assert "safari-bookmarks" in r2["removals_skipped"]


def _example_two_only_chrome_json():
    """Same tree as `CHROME_BOOKMARKS_JSON` minus `https://example.com/one` —
    i.e. what Chrome looks like after the person unbookmarks it."""
    return {
        "version": 1,
        "roots": {
            "bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": [
                {"type": "url", "name": "Example Two", "url": "https://example.com/two"},
            ]},
            "other": {"type": "folder", "name": "Other bookmarks", "children": []},
        },
    }


def test_removal_hint_names_the_url_s_original_source(tmp_path, monkeypatch):
    """R2: a URL first saved manually (origin `saved-link`), later also seen
    in a Chrome sync, then removed from Chrome — the card says where it
    actually came from."""
    _offline_enrich(monkeypatch)
    from api.services.media_ingestor import RawItem, ingest_batch

    memory = tmp_path / "memory"
    manual = RawItem(url="https://example.com/one", title="Example One", origin="saved-link")
    run(ingest_batch([manual], memory, from_bookmark_file=False))

    # Chrome now ALSO has it (a duplicate hit — no new entity) plus one other.
    run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(CHROME_BOOKMARKS_JSON).encode()))
    # Chrome drops it — only "Example Two" survives.
    run(bookmark_sync.sync_bookmarks(memory, chrome_data=json.dumps(_example_two_only_chrome_json()).encode()))

    files = sorted((memory / "inbox").glob("inbox-*.md"))
    assert len(files) == 1
    fm = markdown_parser.parse(files[0]).frontmatter
    assert fm["hint"] == "Also saved via saved-link"
```

Add `from api.services import markdown_parser` to the test file's imports (not yet imported there).

- [ ] **Step 10: Run the full file, then the full suite**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_bookmark_sync.py api/tests/test_bookmark_seen.py api/tests/test_backfill_bookmark_origins.py api/tests/test_bookmarks_safari.py -q -p no:cacheprovider`
Expected: all passing.
Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
Expected: 0 failures beyond the disclosed baseline (8 pre-existing `test_calendar*` failures per
`working-method.md`; report the exact count).

- [ ] **Step 11: Commit**

```bash
cd <worktree>/ && git add api/services/bookmark_seen.py api/services/bookmark_sync.py api/tests/test_bookmark_seen.py api/tests/test_bookmark_sync.py && git commit -m "feat(bookmarks): a removed URL proposes keep/remove, never re-asked once gone (G129 slice 2 part 1)"
```

---

### Task 2: `removal` becomes a resolvable `InboxKind` (API)

**Files:**
- Modify: `api/models/schemas.py` (`InboxKind`, `InboxItem`, `BookmarkSyncResponse`)
- Modify: `api/services/inbox_service.py` (`_required_input_for`, `_action_label`, `_verdict`,
  `recommended_key`, `resolve()`'s dispatch + `change` computation, new `_resolve_removal`,
  `_item_from_file`'s `channel=` pass-through)
- Modify: `api/services/inbox_context.py` (`cause_for`)
- New: `api/tests/test_inbox_removal.py`
- Modify: `api/tests/test_mcp_inbox_questions.py` (one added test)

**Interfaces:**
- Produces: `InboxKind.removal`; `InboxItem.channel: Optional[str]`;
  `BookmarkSyncResponse.removals_proposed: int = 0`, `.removals_skipped: Optional[str] = None`;
  `inbox_service._resolve_removal(path, parsed, request, settings) -> tuple[str, bool]`.
- Consumes: Task 1's frontmatter shape (`kind`, `channel`, `browser`, `url`, `synced_at`, `hint`,
  `options: [keep, remove]`).

- [ ] **Step 1: Write the failing tests — `api/tests/test_inbox_removal.py`**

```python
"""G129 slice 2: a bookmark-removal proposal is a resolvable inbox kind.

Follows the exact end-to-end template G113 slice 3 used for `divergence`/
`normalization` (docs/superpowers/plans/2026-09-02-g113-feedback-ledger.md
Task 3): schema enum, `_required_input_for`, a `_resolve_*` function, the
`resolve()` dispatch, and the ledger's `_verdict`/`recommended_key` tables.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.schemas import InboxKind, InboxResolveRequest
from api.services import inbox_service
from api.services.markdown_parser import parse


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(memory), *args], check=True, capture_output=True, text=True
    ).stdout


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


def _media_entity(origin: str) -> str:
    return f"""---
type: media
status: active
confidence: 0.9
created: 2026-06-01
last_referenced: 2026-06-01
decay_class: evergreen
decay_rate: 0.0
source_episodes: []
tags: []
related: []
version: 1
origin: {origin}
---
# Example Article
"""


def _removal_item(hint: str | None) -> str:
    hint_line = f"hint: {hint}" if hint else "hint: null"
    return f"""---
kind: removal
required_input: choice
status: pending
priority: 0.4
entity_id: example-article
entity_name: Example Article
title: Still keep Example Article?
created_date: 2026-09-05
question: It was removed from Chrome.
options:
  - key: keep
    label: Keep
  - key: remove
    label: Remove
allow_other: false
allow_defer: true
channel: chrome-bookmarks
browser: Chrome
url: https://example.com/article
synced_at: '2026-09-05T10:00:00Z'
{hint_line}
trigger: sync/bookmark_removal
---
Example Article was removed from Chrome.
"""


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    (m / "entities" / "example-article.md").write_text(_media_entity("chrome-bookmark"))
    (m / "inbox" / "inbox-001.md").write_text(_removal_item(None))
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def test_removal_loads_as_a_choice_item_keep_first_no_recommendation(memory):
    items = run(inbox_service.load_inbox(memory))
    assert len(items) == 1
    item = items[0]
    assert item.kind == InboxKind.removal
    assert item.required_input.value == "choice"
    assert [o.key for o in item.options] == ["keep", "remove"]
    assert item.allow_other is False
    assert item.allow_defer is True
    assert item.recommended_key is None
    assert all(not o.recommended for o in item.options)
    assert item.channel == "chrome-bookmarks"


def test_removal_cause_is_tier_item_with_the_sync_timestamp(memory):
    item = run(inbox_service.load_inbox(memory))[0]
    assert item.cause is not None
    assert item.cause.tier == "item"
    assert item.cause.timestamp == "2026-09-05T10:00:00Z"
    assert "Chrome" in item.cause.excerpt


def test_removal_keep_closes_the_item_without_touching_the_entity(memory):
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", option_key="keep"), _Settings(memory)
    ))
    assert out["status"] == "resolved"
    assert not (memory / "inbox" / "inbox-001.md").exists()
    fm = parse(memory / "entities" / "example-article.md").frontmatter
    assert fm["status"] == "active"


def test_removal_remove_archives_never_deletes(memory):
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", option_key="remove"), _Settings(memory)
    ))
    assert out["status"] == "resolved"
    assert (memory / "entities" / "example-article.md").exists()
    fm = parse(memory / "entities" / "example-article.md").frontmatter
    assert fm["status"] == "archived"
    body = _git(memory, "log", "-1", "--format=%B")
    assert "trigger: inbox/removal/resolved:remove" in body
    assert "status archived" in body
    assert "Cicada-Author: user" in body


def test_removal_bad_option_key_400s(memory):
    with pytest.raises(HTTPException):
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve", option_key="archive"), _Settings(memory)
        ))


def test_removal_verdict_is_neutral_for_both_answers():
    assert inbox_service._verdict("removal", "keep", "keep", None, []) == "neutral"
    assert inbox_service._verdict("removal", "remove", "remove", None, []) == "neutral"


def test_removal_never_recommended():
    assert inbox_service.recommended_key("removal", {}, [
        {"key": "keep"}, {"key": "remove"},
    ]) is None


def test_removal_hint_passes_through_when_saved_elsewhere(tmp_path):
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q"); _git(m, "config", "user.email", "t@example.com"); _git(m, "config", "user.name", "t")
    (m / "entities" / "example-article.md").write_text(_media_entity("safari-bookmark"))
    (m / "inbox" / "inbox-001.md").write_text(_removal_item("Also saved via safari-bookmark"))
    _git(m, "add", "."); _git(m, "commit", "-q", "-m", "seed")
    item = run(inbox_service.load_inbox(m))[0]
    assert item.hint == "Also saved via safari-bookmark"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_inbox_removal.py -q -p no:cacheprovider`
Expected: FAIL — `ValueError: 'removal' is not a valid InboxKind`.

- [ ] **Step 3: Schema — `api/models/schemas.py`**

`InboxKind` (`:875-886`), after `normalization = "normalization"`:

```python
    # G129 slice 2: a bookmark that left the browser — keep it, or archive
    # the media entity it named. The proposal comes from the browser's own
    # diff, never from the extractor, so it carries no recommendation and its
    # verdict is always `neutral` (see `inbox_service._verdict`).
    removal = "removal"
```

`InboxItem` (`:948-983`), after `hint: Optional[str] = None`:

```python
    # G129 slice 2 — which sync_state channel (`chrome-bookmarks`/
    # `safari-bookmarks`) proposed this item, so the app's Deletions
    # subsection can filter `GET /inbox`'s result without a new endpoint.
    # Null for every other kind.
    channel: Optional[str] = None
```

`BookmarkSyncResponse` (`:1481-1484`):

```python
class BookmarkSyncResponse(CamelModel):
    new: int
    skipped: int
    sources: list[BookmarkSyncSourceSummary] = []
    # G129 slice 2 — how many `removal` inbox items this sync proposed, and
    # (mutually exclusive in practice, but both default absent) why none were
    # computed when the rails refused (folder-scope mismatch since the last
    # sync on some channel this pass touched).
    removals_proposed: int = 0
    removals_skipped: Optional[str] = None
```

- [ ] **Step 4: `_required_input_for`, `_item_from_file`'s `channel=` — `api/services/inbox_service.py`**

`:49-52`:

```python
def _required_input_for(kind: str) -> str:
    if kind in ("decay", "conflict", "divergence", "normalization", "removal"):
        return "choice"
    if kind == "merge_suggestion":
        return "merge"
    return "freetext"
```

In `_item_from_file`'s `InboxItem(...)` construction, add `channel=_opt_str(fm.get("channel")),`
next to the existing `hint=_opt_str(fm.get("hint")),` line.

- [ ] **Step 5: `_action_label`**

In the `if kind in ("conflict", "divergence", "normalization"):` branch (`:375`), a removal item's
request never carries a positional `option_key` in the `"0"/"1"` sense — it carries the semantic
keys `"keep"`/`"remove"` directly, which is closer to decay's verb-shaped actions. Add its own
branch, mirroring decay's simplicity (`:372-373`):

```python
    if kind == "removal":
        if action == "skip":
            return "skip"
        if key in ("keep", "remove"):
            return key
        return action or "answer"
```

Insert this branch directly after the `if kind == "decay": return action or "answer"` line so the
two verb-shaped kinds sit together.

- [ ] **Step 6: `_verdict`**

Immediately after `if label in _NEUTRAL_LABELS: return "neutral"` (`:420-421`), add:

```python
    # R3: the proposal came from the browser's own diff, never from the
    # extractor — there is no model belief to agree or disagree with, the
    # same reasoning already used for an entity-path conflict with no
    # `claim_id` just below.
    if kind == "removal":
        return "neutral"
```

- [ ] **Step 7: `recommended_key`**

Change `:536` from `if kind in ("merge_suggestion", "clarification"):` to
`if kind in ("merge_suggestion", "clarification", "removal"):` and extend the docstring's list of
"never recommended" kinds with one sentence: *"nor on `removal` — Sleep proposed nothing here; the
browser did (R3)."*

- [ ] **Step 8: `_resolve_removal` + the `resolve()` dispatch + `change`**

Add, near `_resolve_decay` (after it, `:919`):

```python
async def _resolve_removal(path, parsed, request: InboxResolveRequest, settings) -> tuple[str, bool]:
    """``keep`` closes the question with no change to the entity — the
    browser's own diff produced this ask, not a belief to walk back. ``remove``
    archives the media entity: NEVER deletes the page (G129 row rule) — it may
    be claim-linked, and git keeps every version regardless of status.
    """
    entity_id = str(parsed.frontmatter.get("entity_id", "") or "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    action = (request.action or "").strip().lower()
    key = (request.option_key or "").strip().lower()
    verb = key if key in ("keep", "remove") else (action if action in ("keep", "remove") else "")

    if not verb:
        raise HTTPException(
            400,
            f"A removal item takes optionKey 'keep' or 'remove' — got {key or action!r}.",
        )
    if verb == "remove" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "archived"
        entity.frontmatter["last_referenced"] = str(date.today())
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
    path.unlink(missing_ok=True)
    return entity_id, False
```

In `resolve()`'s dispatch (the block quoted in "What the code actually does today"), add a branch
between `decay` and `conflict` (order is cosmetic, this reads naturally next to decay's own
two-verb shape):

```python
    elif kind == "removal":
        entity_id, skipped = await _resolve_removal(path, parsed, request, settings)
```

In the `change` computation right after the dispatch (`:790-795`), add one more `elif`:

```python
    change = "updated"
    if kind == "decay" and label == "archive":
        change = "status archived"
    elif kind == "decay" and label == "keep_active":
        change = "status active"
    elif kind == "removal" and label == "remove":
        change = "status archived"
```

- [ ] **Step 9: `cause_for` — `api/services/inbox_context.py`**

At the top of `InboxContext.cause_for` (`:225-…`, before `entity_id = str(fm.get("entity_id", "")
or "")`):

```python
    # G129 slice 2: a `removal` item was raised by a browser sync, not a
    # conversation — none of the three episode-anchored tiers below apply
    # (there is no episode to excerpt). The item carries its own real
    # provenance directly (`synced_at`, `browser`); serve THAT as tier "item"
    # instead of falling through to `[ no source recorded ]`, which would be
    # honest but would throw away provenance the item actually has.
    if str(fm.get("kind", "") or "") == "removal":
        at = _opt(fm.get("synced_at"))
        if at is None:
            return Cause()
        browser = _opt(fm.get("browser")) or _opt(fm.get("channel")) or "a browser"
        url = _opt(fm.get("url"))
        excerpt = f"Removed from {browser}" + (f" — {url}" if url else "")
        return Cause(tier="item", timestamp=at, origin=_opt(fm.get("channel")), excerpt=excerpt)
```

- [ ] **Step 10: MCP passthrough test — `api/tests/test_mcp_inbox_questions.py`**

Append, matching the existing `test_resolve_inbox_posts_the_option_key` style (read it first for the
exact `server`/`monkeypatch` fixture shape used in that file):

```python
def test_resolve_inbox_posts_removal_keys_unchanged(server, monkeypatch):
    """G129 slice 2: `cicada_resolve_inbox` needs no new code — `option_key`
    is already a free-form string on the wire; `keep`/`remove` pass straight
    through the same path `divergence`'s `"0"`/`"1"` already exercises."""
    posted = {}

    def fake_post(path, payload):
        posted["path"], posted["payload"] = path, payload
        return {"status": "resolved"}

    monkeypatch.setattr(server, "_backend_post", fake_post)
    server.handle_resolve_inbox("inbox-001", "remove", None, False, None)
    assert posted["path"] == "/inbox/inbox-001/resolve"
    assert posted["payload"] == {"action": "resolve", "optionKey": "remove"}
```

- [ ] **Step 11: Run**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_inbox_removal.py api/tests/test_mcp_inbox_questions.py api/tests/test_inbox_divergence_normalization.py api/tests/test_inbox_resolve_claims.py api/tests/test_claim_inbox.py api/tests/test_inbox_questions.py api/tests/test_feedback_ledger.py api/tests/test_inbox_context.py -q -p no:cacheprovider`
Expected: all passing.
Run the full suite as in Task 1 Step 10.

- [ ] **Step 12: Commit**

```bash
cd <worktree>/ && git add api/models/schemas.py api/services/inbox_service.py api/services/inbox_context.py api/tests/test_inbox_removal.py api/tests/test_mcp_inbox_questions.py && git commit -m "feat(inbox): removal is a resolvable kind — keep or archive, never delete (G129 slice 2 part 2)"
```

---

### Task 3: `InboxKind.removal` end to end on Swift, plus a forward-compat fallback

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxListView.swift`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/InboxKindDecodingTests.swift`
- New: `app/CicadaApp/Tests/CicadaAppTests/InboxRemovalTests.swift`

**Interfaces:**
- Produces: `InboxKind.removal`, `InboxKind.unknown` (+ custom `init(from:)`), `InboxItem.channel`,
  `InboxItem.openRemovals(in:channelId:) -> [InboxItem]`.
- Consumes: nothing new from `QuestionView`/`InboxCardView` — both are kind-agnostic already
  (verified this session); this task touches neither file.

- [ ] **Step 1: `InboxKind` — `Models/InboxItem.swift:6-38`**

```swift
enum InboxKind: String, Codable {
    case decay, conflict, clarification
    case mergeSuggestion = "merge_suggestion"
    case divergence
    case normalization
    // G129 slice 2: a bookmark removed from the browser — keep it or archive
    // the media entity it named.
    case removal
    // Forward-compat fallback (matches `EntityType`/`Epistemic`/`SourceTrust`'s
    // existing pattern in this codebase). Before this, an unrecognized raw
    // value threw `DecodingError.dataCorrupted` out of `InboxItem.init(from:)`,
    // which propagates out of `[InboxItem]`'s array decode and drops EVERY
    // pending item, not just the one this build has never heard of — `removal`
    // is what exposed the gap, but any future kind hits the same failure
    // without this case.
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = InboxKind(rawValue: raw) ?? .unknown
    }

    var label: String {
        switch self {
        case .decay: "Decay"
        case .conflict: "Conflict"
        case .clarification: "Clarification"
        case .mergeSuggestion: "Possible duplicate"
        case .divergence: "Divergence"
        case .normalization: "Predicate fold"
        case .removal: "Removed bookmark"
        case .unknown: "Update available"
        }
    }

    /// Leading-icon SF Symbol per kind.
    var icon: String {
        switch self {
        case .decay: "clock.arrow.circlepath"
        case .conflict: "exclamationmark.triangle.fill"
        case .clarification: "questionmark.circle.fill"
        case .mergeSuggestion: "arrow.triangle.merge"
        case .divergence: "arrow.triangle.branch"
        case .normalization: "arrow.triangle.merge"
        case .removal: "bookmark.slash"
        case .unknown: "questionmark.circle"
        }
    }

    var color: Color { CicadaTheme.inboxColor(for: self) }
}
```

- [ ] **Step 2: `InboxItem.channel` — same file, `InboxItem` struct + `CodingKeys` + `init(from:)`**

Add a stored property right after `var hint: String?`:

```swift
    // G129 slice 2 — which browser channel (`chrome-bookmarks`/
    // `safari-bookmarks`) proposed a `removal` item; nil for every other kind.
    var channel: String?
```

Add `channel` to `CodingKeys` (after `hint`) and to the manual `init(from:)` (after the `hint =`
line): `channel = try c.decodeIfPresent(String.self, forKey: .channel)`.

- [ ] **Step 3: `openRemovals` — same file, bottom, mirrors `SourceOverview.ownedItems`'s pattern**

```swift
extension InboxItem {
    /// Open `removal` items proposed against one browser channel (G129 slice
    /// 2) — pure so `ChannelSourceView`'s Deletions subsection is testable
    /// without a view, same pattern as `SourceOverview.ownedItems`.
    static func openRemovals(in items: [InboxItem], channelId: String) -> [InboxItem] {
        items.filter { $0.kind == .removal && $0.channel == channelId }
    }
}
```

- [ ] **Step 4: Theme colours — `Theme/CicadaTheme.swift`**

`Dark.inboxColor` (`:370-384`), add before the closing brace:

```swift
            // G129 slice 2 — decay's amber, darkened: a retraction reads as a
            // graver cousin of decay's fade, not a wholly new hue (R9, same
            // "no new hue budget" precedent as divergence/normalization above).
            case .removal: Color(hex: 0xC9822E)
            // Forward-compat bucket — no real category, reuse the muted text
            // token rather than inventing a colour for it (R8).
            case .unknown: Dark.textTertiary
```

`Light.inboxColor` (`:473-484`), add before its closing brace:

```swift
            case .removal: Color(hex: 0x8A5A10)
            case .unknown: Light.textTertiary
```

- [ ] **Step 5: Filter chip — `Views/Inbox/InboxListView.swift:108-111`**

```swift
    private var orderedKinds: [InboxKind] {
        let present = Set(viewModel.items.map(\.kind))
        return [.decay, .conflict, .clarification, .mergeSuggestion, .removal].filter { present.contains($0) }
    }
```

(`.unknown` is deliberately never added here — same reasoning as `EntityType.selectableCases`
excluding `.unknown`: it is an internal forward-compat bucket, not a real filterable category. An
`.unknown`-kind card still appears under "All" since `visibleItems`/`countByKind` are generic.)

- [ ] **Step 6: Extend `InboxKindDecodingTests.swift`**

Add two test methods to the existing `final class InboxKindDecodingTests`:

```swift
    func testDecodesRemoval() throws {
        let json = #"""
        [{"id":"inbox-020","kind":"removal","requiredInput":"choice","status":"pending","priority":0.4,
          "entityId":"example-article","entityName":"Example Article","title":"t","createdDate":"2026-09-05",
          "options":[{"key":"keep","label":"Keep"},{"key":"remove","label":"Remove"}],
          "channel":"chrome-bookmarks"}]
        """#
        let items = try JSONDecoder().decode([InboxItem].self, from: Data(json.utf8))
        XCTAssertEqual(items.map(\.kind), [.removal])
        XCTAssertEqual(items[0].channel, "chrome-bookmarks")
        XCTAssertEqual(InboxKind.removal.label, "Removed bookmark")
    }

    func testUnknownFutureKindDoesNotBlankTheWholeInbox() throws {
        let json = #"""
        [{"id":"inbox-021","kind":"a_kind_from_the_future","requiredInput":"freetext","status":"pending","priority":0.1,
          "entityId":"","entityName":"","title":"t","createdDate":"2026-09-05","options":[]},
         {"id":"inbox-022","kind":"decay","requiredInput":"choice","status":"pending","priority":0.5,
          "entityId":"example-article","entityName":"Example Article","title":"t","createdDate":"2026-09-05","options":[]}]
        """#
        let items = try JSONDecoder().decode([InboxItem].self, from: Data(json.utf8))
        XCTAssertEqual(items.count, 2)
        XCTAssertEqual(items[0].kind, .unknown)
        XCTAssertEqual(items[1].kind, .decay)
    }
```

- [ ] **Step 7: `InboxRemovalTests.swift` (new)**

```swift
import XCTest
@testable import CicadaApp

/// G129 slice 2: the pure filter `ChannelSourceView`'s Deletions subsection
/// runs on `store.visibleInbox` (Task 4) — tested here without a view.
final class InboxRemovalTests: XCTestCase {
    private func item(id: String, channel: String?, kind: InboxKind = .removal) throws -> InboxItem {
        let json = """
        {"id":"\(id)","kind":"\(kind.rawValue)","requiredInput":"choice","status":"pending","priority":0.4,
         "entityId":"e","entityName":"E","title":"t","createdDate":"2026-09-05","options":[],
         "channel":\(channel.map { "\"\($0)\"" } ?? "null")}
        """
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testOpenRemovalsFiltersByKindAndChannel() throws {
        let a = try item(id: "a", channel: "chrome-bookmarks")
        let b = try item(id: "b", channel: "safari-bookmarks")
        let c = try item(id: "c", channel: "chrome-bookmarks", kind: .decay)
        let result = InboxItem.openRemovals(in: [a, b, c], channelId: "chrome-bookmarks")
        XCTAssertEqual(result.map(\.id), ["a"])
    }

    func testOpenRemovalsEmptyWhenNoneMatch() throws {
        // `InboxItem` is not `Equatable` — assert emptiness, not array equality.
        let a = try item(id: "a", channel: "safari-bookmarks")
        XCTAssertTrue(InboxItem.openRemovals(in: [a], channelId: "chrome-bookmarks").isEmpty)
    }
}
```

- [ ] **Step 8: Build + test**

Run: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5`
Expected: success. (If it fails on the two exhaustive `inboxColor` switches, you missed a case — the
compiler names the exact switch.)
Run: `swift test 2>&1 | tail -30`
Expected: 0 failures, including the new `InboxKindDecodingTests`/`InboxRemovalTests` methods.

- [ ] **Step 9: Commit**

```bash
cd <worktree>/ && git add app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxListView.swift app/CicadaApp/Tests/CicadaAppTests/InboxKindDecodingTests.swift app/CicadaApp/Tests/CicadaAppTests/InboxRemovalTests.swift && git commit -m "feat(inbox): removal kind on Swift, plus a forward-compat fallback for future kinds (G129 slice 2 part 3)"
```

---

### Task 4: The browser's Deletions subsection + an honest sync feedback line

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (`BookmarkSyncResult`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/BrowserImport.swift` (`BrowserImportSummary.bookmarks`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift` (`SyncBrowserBookmarks.refreshDomains`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/BrowserImportModelTests.swift`

**Interfaces:**
- Produces: `BookmarkSyncResult.removalsProposed/removalsSkipped` (defaulted, memberwise-init-safe);
  `ChannelSourceView`'s Deletions section reading `InboxItem.openRemovals` (Task 3) over
  `store.visibleInbox`.
- Consumes: `InboxCardView`/`InboxViewModel.resolve` unmodified (Task 3's "no changes needed" holds).

- [ ] **Step 1: `BookmarkSyncResult` — `Services/APIClient.swift:334-338`**

Replace the struct so the new fields default (preserving the existing 3-arg memberwise call sites —
`BrowserImportModelTests.swift:76-78` constructs it that way directly) and the `Codable`
conformance + custom decode live in an extension (same reason `Models/InboxItem.swift`'s
`InboxOption` does this: a custom `init(from:)` in the PRIMARY declaration would suppress the
synthesized memberwise init; in an extension it does not):

```swift
struct BookmarkSyncResult {
    let new: Int
    let skipped: Int
    let sources: [BookmarkSyncSourceSummary]
    /// G129 slice 2 — how many `removal` inbox items this sync proposed.
    /// Defaulted so the pre-existing 3-arg call sites still compile.
    var removalsProposed: Int = 0
    /// Non-nil only when the correctness rails refused to compute removals
    /// this sync (a folder-scope change since the last sync on some channel).
    var removalsSkipped: String? = nil
}

extension BookmarkSyncResult: Codable {
    enum CodingKeys: String, CodingKey { case new, skipped, sources, removalsProposed, removalsSkipped }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        new = try c.decode(Int.self, forKey: .new)
        skipped = try c.decode(Int.self, forKey: .skipped)
        sources = try c.decodeIfPresent([BookmarkSyncSourceSummary].self, forKey: .sources) ?? []
        removalsProposed = try c.decodeIfPresent(Int.self, forKey: .removalsProposed) ?? 0
        removalsSkipped = try c.decodeIfPresent(String.self, forKey: .removalsSkipped)
    }
}
```

- [ ] **Step 2: Feedback line — `Models/BrowserImport.swift`, `BrowserImportSummary.bookmarks`**

```swift
    static func bookmarks(_ r: BookmarkSyncResult) -> String {
        var line = "\(r.new == 0 ? "Nothing new" : "\(r.new) new") · \(r.skipped) already saved"
        if r.removalsProposed > 0 {
            line += " · \(r.removalsProposed) removal\(r.removalsProposed == 1 ? "" : "s") to review"
        }
        return line
    }
```

- [ ] **Step 3: `SyncBrowserBookmarks.refreshDomains` — `Sync/Mutations.swift:547`**

```swift
    var refreshDomains: Set<SyncDomain> { [.channels, .sources, .status, .inbox] }
```

- [ ] **Step 4: `BrowserImportModelTests.swift` — extend `testSyncSummaries` and `testDecodesTheBackendShapes`**

```swift
    func testSyncSummaryIncludesRemovalsWhenAny() {
        var r = BookmarkSyncResult(new: 1, skipped: 0, sources: [])
        r.removalsProposed = 2
        XCTAssertEqual(BrowserImportSummary.bookmarks(r), "1 new · 0 already saved · 2 removals to review")
    }
```

In `testDecodesTheBackendShapes`, right after the existing `XCTAssertNil(legacy.sources[0].channel)`
line, add:

```swift
        // G129 slice 2 — an older backend's payload carries neither key; both
        // default so a pre-slice-2 cache still decodes.
        XCTAssertEqual(legacy.removalsProposed, 0)
        XCTAssertNil(legacy.removalsSkipped)
        let withRemovals = try JSONDecoder().decode(BookmarkSyncResult.self, from: Data(#"""
        {"new":1,"skipped":0,"sources":[],"removalsProposed":2,"removalsSkipped":null}
        """#.utf8))
        XCTAssertEqual(withRemovals.removalsProposed, 2)
        let skippedSync = try JSONDecoder().decode(BookmarkSyncResult.self, from: Data(#"""
        {"new":0,"skipped":0,"sources":[],"removalsProposed":0,"removalsSkipped":"safari-bookmarks: folder scope changed since the last sync"}
        """#.utf8))
        XCTAssertEqual(skippedSync.removalsSkipped, "safari-bookmarks: folder scope changed since the last sync")
```

- [ ] **Step 5: The Deletions subsection — `Views/Sources/ChannelSourceView.swift`**

Add a computed property (near `items`):

```swift
    /// G129 slice 2 — open `removal` items proposed against THIS channel.
    /// `store.visibleInbox`, not `store.inbox.value`, so an optimistic
    /// resolve here hides the card the instant it's clicked, same as the
    /// main Inbox page (`InboxViewModel.items`).
    private var removals: [InboxItem] {
        guard let id = source.channelId else { return [] }
        return InboxItem.openRemovals(in: store.visibleInbox, channelId: id)
    }
```

Add `@Environment(InboxViewModel.self) private var inboxVM` next to the existing
`@Environment(BrowserWatcher.self) private var watcher` line (already available app-wide —
`.environment(inboxVM)` wraps `ContentView()` at the app root, verified this session).

In `body`, right after `if let channel { stateCard(channel) }`:

```swift
                if !removals.isEmpty { deletionsSection }
```

Add the section (near `folderCounts`, same file):

```swift
    /// One write path (`InboxViewModel.resolve` → `POST /inbox/{id}/resolve`),
    /// two views: the unified Inbox and this page render the identical
    /// `InboxCardView` for the identical open items.
    private var deletionsSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Removed from \(source.label)")
                .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            VStack(spacing: CicadaTheme.spacingSM) {
                ForEach(removals) { item in
                    InboxCardView(item: item) { resolution in
                        await inboxVM.resolve(
                            id: item.id, action: resolution.action, answer: resolution.answer,
                            optionKey: resolution.optionKey, remindDays: resolution.remindDays,
                            mergeTarget: resolution.mergeTarget, mergeSurvivor: resolution.mergeSurvivor
                        )
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingMD).glassCard()
    }
```

This gates on data (`!removals.isEmpty`), not on `source.id`/`channelId` being literally
`chrome-bookmarks`/`safari-bookmarks` — a deliberate choice: the section lights up for whatever
channel actually has open removal items, so a future browser G119 adds gets this for free the moment
its sync starts writing `channel:`-tagged removal items, with no list of hardcoded channel ids to
maintain here.

- [ ] **Step 6: Build + test**

Run: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5`
Run: `swift test 2>&1 | tail -30`
Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
cd <worktree>/ && git add app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Models/BrowserImport.swift app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift app/CicadaApp/Tests/CicadaAppTests/BrowserImportModelTests.swift && git commit -m "feat(sources): a browser's page shows its own pending removals (G129 slice 2 part 4)"
```

---

### Task 5: Docs

**Files:**
- Modify: `docs/goals/memory-evolution.md` (G129 row)
- Modify: `docs/goals/TODO.md`
- Modify: `docs/goals/working-method.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `docs/goals/memory-evolution.md` — G129 row**

Append to the row's evidence/status column (the `🛠️ **slice 1 shipped …**` cell), after "**Slice 2
(deletions) is next and not started.**":

> **Slice 2 shipped 2026-09-05** (this branch): `bookmark_seen.json` (per-channel seen-set beside
> `url_index.json`), `sync_bookmarks`'s `propose_removals` diffing browser-then vs browser-now
> (never vs memory) and refusing on a folder-scope change (both rails from this row, unchanged), a
> new `removal` inbox kind (`keep`/`remove`, always graded `neutral` — the proposal is the browser's,
> not the extractor's), and the browser's own source page rendering the same open items as a
> Deletions subsection. `InboxKind` also gained a Swift `.unknown` forward-compat fallback while
> adding `removal` — a decode gap that predated this row. **What stays open: G119** (Arc/Brave/
> Firefox — this slice keys off the existing Chrome/Safari `CHANNEL_BY_ORIGIN` map and generalizes
> for free once G119 adds a browser to it).

Do not guess a PR number here — the established pattern in this repo (e.g. the G113 row's own
"Shipped 2026-09-05 (PR #59, …)" line, added in a SEPARATE later commit,
`9149781 docs: G113 slices 3–7 are PR #59`) is to add the PR number in a follow-up docs commit once
the PR actually exists, not to invent it now.

- [ ] **Step 2: `CLAUDE.md` — inbox kinds list**

In the "Unified inbox" section, change:

> `memory/inbox/inbox-NNN.md`, each with a `kind` discriminator (`decay`, `conflict`,
> `clarification`, `merge_suggestion`), behind `GET /inbox` / `POST /inbox/{id}/resolve`.

Check the current text first — G113 already updated this once to add `divergence`/`normalization`
(verified this session, CLAUDE.md §"2/3. Unified inbox" already reads `decay, conflict,
clarification, merge_suggestion, divergence, normalization`). Add `removal` to that same
parenthetical list, and add one sentence after the existing "**Decay is no longer the special
case.**" paragraph:

> **Neither is a bookmark removal.** Served the same way as decay — two closed options
> (`keep`/`remove`), no free text, no recommendation (the proposal came from the browser's own
> before/after diff, not the extractor) — `remove` archives the media entity it named; it is never
> deleted.

- [ ] **Step 3: `docs/goals/TODO.md`**

In "Where things stand", append this branch's merge to the list once it lands (leave a `**#NN**
G129 slice 2 (bookmark deletions)` slot for whoever runs the merge/PR step — same "don't guess the
number" rule as Step 1).

Change the "🔄 In progress" table row:

```
| **G129 bookmarks** | **Both slices shipped** — slice 1 (PR #52): file watch, catch-up sync, six-state light. Slice 2 (this branch): seen-set, removal proposals, Deletions subsection. | G119 (Arc/Brave/Firefox) generalizes for free once added to `CHANNEL_BY_ORIGIN`. |
```

Change "The queue there, in order:" line — remove `**G129 slice 2** (bookmark deletions — item 0,
small) →` from the front of the list (it is item 0 no longer; the next item, G125, is already
marked shipped in `working-method.md` per this session's read, so re-derive the new head of the
queue by reading `working-method.md` §3 fresh rather than assuming G122 is next — read it, don't
guess).

- [ ] **Step 4: `docs/goals/working-method.md` — item 0**

Change item 0's text (`§"The rest, in order"`) to a struck-through shipped entry, matching item 2's
(G125) existing style exactly:

```
~~0. **G129 slice 2 — bookmark deletions.**~~ — **shipped 2026-09-05** (branch
   `feat/bookmark-deletions`): the seen-set + diff, the `removal` inbox kind (`keep`/`remove`,
   always `neutral` — the proposal is the browser's), and the browser page's own Deletions
   subsection. Open remainder, not this row: G119 (more browsers).
```

Renumber the remaining items only if this file's convention numbers them sequentially rather than
by original position — read the surrounding items first (this session found items numbered 0, 2, 3,
4… with 1 apparently already consumed by a prior shipped row, so the file may NOT strictly
renumber on ship — match whatever convention is actually there rather than assuming).

- [ ] **Step 5: Verify doc changes don't violate the privacy rule**

Grep your own diff for anything that looks like a real URL, a real person's name, or a bank path
before committing: `git diff --cached -- docs/ CLAUDE.md | grep -iE "http|@|/Users/[a-z]+/(?!Documents/roros_lab/cicada)"` —
expect no hits beyond `example.com`/`example.org` and the repo's own path.

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add docs/goals/memory-evolution.md docs/goals/TODO.md docs/goals/working-method.md CLAUDE.md && git commit -m "docs(G129): slice 2 shipped — removal proposals, Deletions subsection, queue advanced"
```

---

## Verification (run at the end, by the orchestrator)

1. Full Python suite: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`. Expect 0 failures beyond the
   disclosed 8 pre-existing `test_calendar*`/`test_sources_calendars*` failures. If
   `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
   the ONLY other red, re-run it alone (`-k
   test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`) and report both results per
   the known order-dependence.
2. Full Swift suite: `cd .../app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -30`. Expect success + 0 failures.
3. `git log --oneline dev..HEAD` shows exactly 5 commits (one per task), each independently green
   per its own Step "Run" — never a single squashed diff.
4. Read the final diff for the two correctness rails by eye: `diff_removed` must return `None` (not
   `[]`, not raise) on both a missing-previous-set and a folder-scope mismatch, and
   `write_channel_seen` must be called for every channel actually synced this pass regardless of
   whether a removal was proposed.
5. Confirm no `~/Library` read was added to any backend path (`grep -rn "Library" api/services/bookmark_seen.py api/services/bookmark_sync.py` should show nothing new beyond the two existing
   `chrome_bookmarks_path`/`safari_bookmarks_path` functions, both already gated behind
   `sync_from_local_files`'s "best-effort, tests/curl only" contract).
6. Confirm the docs diff carries no personal data (Task 5 Step 5's grep).
