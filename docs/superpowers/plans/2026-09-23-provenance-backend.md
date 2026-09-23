# Provenance viewer, server half (Track P-back, G118 slice 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slice 1 made every new claim point at the words it came from; nothing can yet read them
back. This track ships every **server** piece the provenance viewer needs, so the later Swift track
is Swift-only: a span in a conversation that *continued* stops reading `stale` (`grown`); the whole
conversation comes back with its turn structure and per-turn times (`GET /episodes/{id}/text`); an
entity says who wrote its beliefs, which conversations fed it and how many carry an exact quote
(`GET /entities/{id}/provenance`); a conversation says what it taught Cicada
(`GET /episodes/{id}/citations`); `/ask` citations carry their spans; and the chat importer stops
throwing away each message's time.

**Architecture:** One freshness rule (`evidence.span_status`) and one turn parser (the marker lines
`speaker_kind` already reads) live in `api/services/evidence.py`; one new read-only module,
`api/services/provenance.py`, builds the three payloads; routes are added to the two existing
routers that already own these URL prefixes (`episodes.py`, `claims.py`). Everything is
engine-free, bank-text-only, computed at read and never written. No new Store domain, no
`VersionVector` change, no Swift, no MCP change.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (`api/`), markdown + git bank, pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-design-settings-search-provenance.md` §4
(§4.1 wire, §4.8 server additions — **this track owns them**, §4.9 honesty rules, §4.10 tests) and
§6 slices P2–P5 (server parts), amendment **A7**; `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`
decision **19**. Backlog: **G118** (edited), cross-referenced **G103**, **G106**, **G115**; G100's
derived-span class lands here. Standing rulings: provenance outranks polish (owner, 2026-09-02),
spans not copies, transcripts under `~/.claude` never read, ETag ship-together, privacy in docs,
portability.

---

## What the code actually does today (verified on `feat/provenance-viewer` @ `bef2e55`)

**Evidence (slice 1).**
- `api/services/evidence.py:57-65` — `_TURN_RE` (`user|human|assistant|ai|system|unknown`, then `:`)
  and `_ASSISTANT_ROLES`; `:166-186` `speaker_kind` scans `splitlines()` through the end of the line
  containing `start` and returns the last marker's kind (`system`/`unknown`/no marker → `user`).
  `:68-71` `body_hash` = `sha256[:12]`. `:78-91` `source_path` refuses any non-bare id (the one
  traversal rail) and resolves `ep_*` → `episodes/`, else `entities/`. `:94-105` `source_text`
  (episode body; page body with the claims fence stripped).
- `api/services/claims.py:52-59` — `EVIDENCE_KINDS` is closed at four; `:89-109`
  `Evidence.from_dict` demotes any other kind to `reasoning`. `:173-185` `all_session_ids()`.
- `api/routers/episodes.py:33-59` — `GET /episodes/{id}/span`; `:48` + `:57` —
  `stale = bool(hash) and hash != body_hash(whole text)`. `:27-30` `MAX_CONTEXT = 2000`. No ETag
  by design (slice-1 R9).
- `api/services/inbox_context.py:296-307` — `_asserted_span` drops a span whose hash differs from
  the WHOLE body (`:303`), so the cause falls back to a derived name match. `:73-91`
  `locate_mention` (name → id-as-words → id → a ≥4-char name token, case-insensitive), `:94-135`
  `excerpt_around` (±240, word-boundary cut, offsets rebased; `start`/`end` are the window's
  absolute offsets), `:284-292` the cause carries both.
- **Why continued conversations read stale (A7).** `transcript_capture.py:273-289` rewrites a
  session's ONE episode in place on every later Stop; `:134-137` the body is `role: text` lines;
  `transcript_extract.py:43-46` `SESSION_CAP_CHARS` is head-stable "so … byte offsets … do not
  move". G20 does the same for a grown chat export (`conversations.py:924-943`). Prototyped on this
  base: a span minted after the first Stop, re-read after a second Stop that appended two turns,
  hashes equal to the turn-boundary prefix → exact.

**The importer (per-turn times).**
- `api/routers/conversations.py:287` (Claude `created_at`) and `:442-450` (ChatGPT `create_time`)
  parse every message's time; `:797-803` `_stage_episodes` builds the body as
  `"\n".join(f"{role}: {text}")` and hashes exactly that string; `:900-920` `_write_new_episode`
  and `:934-943` `_update_episode_in_place` never write the times. `:856-868`
  `_normalise_import_timestamp` renders an aware stamp as `+00:00`, keeps a naive one verbatim.
- `markdown_parser.py:14-26` returns `parts[2].strip()` as the body; the importer's body has
  nothing to strip (stripped message texts, a role first), so an offset into the built string is an
  offset into the evidence text.
- **The `turns` key already exists with a different type:** `transcript_capture.py:261` and `:284`
  write `turns: len(conv.turns)` — an int — on every Stop-hook episode. No reader of that key
  exists outside `test_capture_transcript.py` (grepped `api/`, `mcp/`, `app/…/Sources`).
- **Measured cost of a frontmatter sidecar** (this base, CPython 3.12.11, PyYAML's pure-Python
  `SafeLoader`, which `markdown_parser.parse` uses): one episode's frontmatter parses in ~0.14 ms
  without it, ~2.9 ms with 50 entries, ~11.5 ms with 200, ~28 ms with 500 (block vs flow style: no
  difference; libyaml's `CSafeLoader` would be ~7× faster but is a global change — Not in scope).

**Provenance inputs.**
- `api/services/git_service.py:311-326` `_classify_author_kind`, `:329-353` `_provider_for_model`
  (private; the contributors strip reaches them only through `get_contributors`). `:415-503`
  `get_entity_history` — blame + one `git log -1` per commit; `EntityHistoryEntry`
  (`schemas.py:159-181`) has no kind/provider. `:394-412` `_run_git`. Trailer directive verified on
  git 2.50.1: `--format=%x1e%(trailers:key=Cicada-Author,valueonly,separator=%x1f)` prints one
  record per commit, empty for an untrailered commit, values joined by `\x1f`.
- `schemas.py:637-668` `ClaimModel` carries `authored_by`/`origin`/`evidence` but not
  `session_ids`/`recorded_at`/author kind/provider; `routers/claims.py:39-61` `_claim_to_model`.
  **There is a second, identical builder:** `transclusion_resolver.py:45-67` `_to_model` (called at
  `:183` and `:206`) serves `/transclude`. Adding fields to only one of them would ship two shapes
  of the same claim, so Task 4 makes the resolver's the one builder and the router delegates to it.
- `api/services/session_stats.py:75-159` `_group` parses **every entity's claims block** per call
  (`:123`) — O(bank), fine for `/conversations`, too slow to call per entity card.
- `api/services/bank_index.py:62-120` `files()` caches frontmatter by `(mtime_ns, size)`;
  `IndexedFile.body()` (`:36-37`) re-parses lazily.
- `api/services/vector_index.py:537-596` `index_claims` stores claim metadata **without
  evidence** — the claims index cannot answer "which claims cite this episode".

**Ask.**
- `api/services/ask_service.py:74-92` `_load_entity` already holds the page `body` (claims block
  included); `:196-205` a claim-first hit carries `claim_provenance.claim_id`; `:521-544`
  `_citations_for` puts it on the dict — and `routers/ask.py:41` `AskCitation(**c)` silently drops
  it (`AskCitation`, `schemas.py:818-823`, has no such field). So no claim id and no span ever
  reached the wire.
- `mcp/server.py:728-737`, `:768-775` — the MCP adapter and `_render_ask` read named keys only;
  new citation keys change nothing there (no MCP change needed).

**ETags.** `sync_service.py:206-215` `etag_for(mp, *components, extra=)`, `:218-223`
`conditional`. `entities` = max mtime over `entities/*.md` + dir; `episodes` = count:max mtime;
`git_head` reads `.git/HEAD` (cheap).

**Sibling tracks (checked 2026-09-23):** `feat/local-sources` and `feat/search-everywhere` have no
commits beyond `dev`; no round-3 track has merged Swift or backend code. The `speaker:` marker
family (Track N) does not exist on this base.

- `api/services/agentic_write.py:101` — an MCP `cicada_write_claim` reaches the reconciler with
  `litellm_model = "mcp-agentic-write"`, so those claims carry `authored_by: mcp-agentic-write`,
  which `author_identity` classifies as `("model", "other")` (seen on the demo bank while
  validating this plan). Track R's R-R6 ("MCP claim authorship") owns the write-side fix; this track
  reports the stored value honestly and does not relabel it.

**Baseline on this base:** backend **2225 passed** (dev, 2026-09-06).

**This plan was validated before hand-off.** Every code block below was applied verbatim, task by
task, to a scratch copy of this base (outside the repo) and run: each task's new tests went red
before its implementation and green after, and the full suite otherwise matched an unpatched
scratch copy exactly. The demo-bank budget script in *Verification* measured
`/entities/{id}/provenance` at ~15 ms warm (design budget 150 ms) and `/citations` at ~2 ms.
**Critic pass (2026-09-23):** re-applied verbatim on a fresh scratch copy of `bef2e55` — 63 new
tests, full suite 2288 passed, 0 failed. It then found three defects the tests did not catch
(`/transclude` kept a second `ClaimModel` builder without the author fields; conversation rows
ordered timestamps as strings, against G114; `?focus=../x` resolved a file outside `entities/`),
added a red-first test for each and fixed them in Tasks 3 and 4: **66 new tests**, full suite
**2291 passed**, 0 failed.

---

## Global Constraints

- `<worktree>` below means the track worktree the orchestrator assigned (branch
  `feat/provenance-viewer`). Work ONLY there. Every shell command is `cd <worktree> && <cmd>` with
  the ABSOLUTE path (zoxide hijacks a relative `cd`; ignore its stderr warning). No unquoted
  `--include=*.ext`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library`, `~/.claude/projects`. Fixtures
  are synthetic: `alpha-project`, `bob-example`, `example.org`/`example.com`, placeholder session ids.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full
  `api/tests` suite must report **0 failures** (2225 passed on this base, plus this track's tests).
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
  order-dependent and pre-existing — if it is the ONLY red, re-run it alone and report both results.
- Never `git add -A`; stage the named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv`, `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin/PR
  comments. **This plan file is committed with Task 1** (it is the track's first artifact).
- **Do not touch:** anything under `app/` or `mcp/`; `api/services/claims.py` (`EVIDENCE_KINDS`
  stays closed — `derived` is read-only, R-PB9); `api/services/transcript_capture.py` /
  `transcript_extract.py` (the hook's `turns: <int>` stays, R-PB4); `api/services/session_stats.py`.
  Do **not** create `api/services/episode_staging.py` (the Local-sources track owns it).
- **Engine-free** (G80): no LLM, no vector index, no `~/.claude` contact in any new read path;
  `provenance.py`'s import list is pinned by a test.
- **Spans, not copies:** nothing here writes a file. Excerpts and derived offsets are recomputed per
  request.
- Docstrings explain **why**, citing the G-row / ruling / design section that motivated the rule —
  the density of `evidence.py` and `inbox_context.py`.
- **Privacy (standing, 2026-09-02):** no owner name, no author-machine path, no bank contents in code,
  docs, commits or the PR body.
- Line numbers above are from `bef2e55` and drift as tasks land — read the cited code before editing.

---

## Rulings (binding)

Design §4.9 and A7 hold as written, and §4.8 holds except where a ruling below says it **departs**
from it. Four do, each for a reason stated in the ruling: R-PB5 (the cap is 400,000 characters, not
400 KB), R-PB7 (conversation rows come from `bank_index`, not `session_stats`), R-PB10 (`/citations`
does not wait for Track S's FTS table, and `partial` means "capped", not "index cold") and R-PB11
(the ETag recipes are wider than §4.8's). Everything else below is a decision this plan takes where
the brief or design left a choice, with the reason, so no task re-opens it.

- **R-PB1 — One freshness rule, `evidence.span_status(text, *, end, hash, appendable)` →
  `current | grown | stale`.** `current`: no hash, or the whole-text hash matches (slice-1 R2).
  `grown` (A7): an episode whose whole hash differs, but some prefix `text[:cut]` — `cut` being the
  newline just before a turn-marker line, with `cut >= end` — hashes to the stored value. Computed
  in ONE incremental pass (`hashlib` `update` + `copy`), so it is O(len) whatever the turn count.
  `stale`: neither. `appendable=False` for a `page` document (descriptions are rewritten, not
  appended). Every reader goes through it: `/span`, `/text`'s focus, the provenance best span,
  citations and the inbox cause (R-PB14). Exact, never fuzzy: a 48-bit hash over a string that was
  once the whole body.
- **R-PB2 — A stale span never travels with wash offsets.** On every read payload this track adds,
  a stale focus/best/citation has `start: null, end: null` (and no `mentionOffsets`); only the raw
  stored `evidence` record keeps its numbers, because it *is* the record (`/claims` already serves
  it). §4.9 "stale never highlights" becomes unrepresentable rather than a client convention.
- **R-PB3 — One turn parser.** `evidence._marker_lines` (the same `_TURN_RE` + `splitlines` as
  `speaker_kind`) feeds `turn_starts`, `turns` and `span_status`; `speaker_kind` itself is not
  edited. A test pins `turn.role == speaker_kind(text, off)` for every offset in every turn. Track
  N's `speaker:` family, when it lands, extends `_TURN_RE` and the role mapping in this one file and
  both move together.
- **R-PB4 — The per-turn time sidecar.** Key and shape exactly `turns: [{offset, ts, speaker}]`
  (the Local-sources coordination contract). Written by the chat importer only
  (`conversations.py`), always the **last** frontmatter key, **outside** `content_hash` (the hash is
  over the body string, which is unchanged). `offset` = the message's `role:` line start in the
  evidence text; `ts` = `_normalise_import_timestamp` of the message's own time; `speaker` = the
  role written on that line. An entry only for a message that has a time (an entry whose only news is
  the role repeats the marker); the key is omitted when no message has one. Written only when the
  body is exactly the messages' own rendering (a caller passing another body gets no sidecar — the
  offsets would vouch for text they do not index). **Capped head-stable at `MAX_TURN_STAMPS = 500`**
  because every cold `bank_index` scan parses it (the measured costs above); later turns carry no
  time, and no time is ever inferred. Update-in-place rewrites (or removes) it; a SKIP never touches
  the file, so already-imported threads gain times only on a grown re-import or a fresh bank (no
  backfill — G20's skip means "nothing changed" and stays byte-identical). The Stop hook's
  `turns: <count>` is untouched; the reader (`evidence.turn_stamps`) treats any non-list as "no
  stamps".
- **R-PB5 — `GET /episodes/{id}/text`.** Cap `MAX_TEXT_CHARS = 400_000` **characters** (offsets are
  code-point indices, and the cut must land on one); `length` and `hash` always describe the whole
  text; turns starting past the cap are dropped and the straddling one clipped. A page is ONE block
  with `role: "page"` (the client always iterates `turns`; design's "no turns" is the header's turn
  count, not the payload); a marker-less episode is one `user` block with `marker: null` (R4's
  default), never an error. `ts`/`speaker` come only from a sidecar entry at exactly a turn start
  and are passed through verbatim. Focus: `?start&end[&hash]` is asserted (422 on a half or
  out-of-range pair); `?focus=<entity>` is derived via `locate_mention`; an unknown focus entity
  yields `focus: null`, not 404 (the document exists). So does a `focus` that resolves to a file
  outside `entities/` (`resolve_entity_file` joins its argument onto `entities/` as given, so
  `../x` would otherwise read an arbitrary `.md` — the `source_path` rail applies to the hint too). The payload never carries `project_dir` or
  `resumable`: `GET /conversations/{id}` stays the one place that `isfile()`s a transcript.
- **R-PB6 — Provenance counts CURRENT claims** (`valid_to is None and not superseded_by`): the section
  explains the beliefs the card shows; superseded beliefs have `/timeline`. Contributors = claim
  `authored_by` counts (None → `unknown`) plus commit counts from **one**
  `git log -n501 --format=%x1e%(trailers:key=Cicada-Author,valueonly,separator=%x1f) -- entities/<id>.md`
  — every commit that touched the page, not blame survivors, trailers only (never `%b`: a Sleep
  body is a manifest of every entity it touched), capped at `MAX_PROVENANCE_COMMITS = 500` with
  `commitsTruncated`. Kind/provider come from a new public `git_service.author_identity(author)`,
  the one seam the chip, the history row and this payload share.
- **R-PB7 — Conversations on the provenance payload are grouped from episode frontmatter via
  `bank_index`** (`session_id` → `source_id` → the episode itself), not `session_stats._group` (O(bank)
  per call). Title from the earliest episode, harness the first non-empty, origin from the latest —
  `_group`'s own rule, applied to this entity's episodes only — except that "earliest"/"latest" and
  the row order are by **instant** (`episode_ids.timestamp_sort_key`, the G114 R2 rail: a bank holds
  naive, `Z` and `+00:00` stamps side by side). `_group` still sorts the raw strings; that is a
  pre-existing G114 gap in `session_stats.py`, which this track does not touch. At most
  `MAX_PROVENANCE_CONVERSATIONS = 50` rows (claim count desc, then newest), and `best` is computed
  only for those, so the body-read budget is bounded by what is shown; `totals.conversations` is the
  honest total. A `source_episodes` id with no file on disk is a row with `available: false`.
- **R-PB8 — The best quote per conversation:** an asserted span that still holds (`current` or
  `grown`; newest-recorded claim first) → a derived name match in the conversation's newest
  readable episode → a stale span (excerpt only, R-PB2) → none. A derived match outranks a stale
  span because it shows the right words, labelled for what it is.
- **R-PB9 — `derived` is a read-payload kind only.** It never enters `EVIDENCE_KINDS` and is never
  written; `Evidence.from_dict(kind="derived")` already degrades to `reasoning` and a test pins both.
  One derivation rule everywhere: `inbox_context.locate_mention` over the subject's name and id —
  the rule the inbox cause already uses, so "found by name" means the same thing on every surface.
- **R-PB10 — Citations' "cold path" is the pages' own claims blocks, prefiltered by raw text.** A page
  is parsed only if its raw text contains the document id (a page can only cite an id it spells;
  `ep_YYYY-MM-DD_nnn` is distinctive), at most `MAX_CITATION_PAGES = 200` parses, `partial: true`
  when capped. Not the vector claims index (no evidence in its metadata) and not Track S's FTS table
  (not depended on; it may later back the same response shape).
- **R-PB11 — ETags, and no Store domain.** `/text` and `/citations` ETag over
  `episodes`+`entities` (+ the request in `extra`); `/provenance` adds `git_head`, because its
  commit counts come from git and a commit that lands after the file write would otherwise 304 a
  stale count. `/span` stays ETag-less (slice-1 R9). None of these joins the Store, so there is no
  `VersionVector` mapping to ship (design K10); if one ever does, the mapping ships in the same
  commit.
- **R-PB12 — `/ask` evidence is read from the page, not the index.** `_citations_for` looks the
  claim up in the `body` `_load_entity` already holds (zero extra I/O) and adds `claim_id` +
  `evidence` (the stored entries, raw — freshness is `/span`'s job). Entity-only hits carry neither.
  `AskCitation` gains `claim_id: Optional[str]` and `evidence: list[EvidenceModel]`.
- **R-PB13 — P3's server half includes the author fields its Swift half renders** (design §4.1,
  §4.6): `ClaimModel` gains `session_ids`, `recorded_at`, `author_kind`, `author_provider`;
  `EntityHistoryEntry` gains `author_kind`, `author_provider`. Additive; an older app ignores them.
  **One builder:** `transclusion_resolver.claim_to_model` (today's private `_to_model`, renamed) fills
  them, and `routers/claims._claim_to_model` delegates to it, so `/claims`, `/timeline` and
  `/transclude` can never ship two shapes of one claim.
- **R-PB14 — The inbox cause honours `grown`.** `_asserted_span` asks `span_status` instead of
  comparing whole hashes, so a G115 cause keeps its exact quote when the conversation continued.
- **R-PB15 — No new router module.** `/text` and `/citations` join `routers/episodes.py`;
  `/provenance` joins `routers/claims.py` (it is a claims projection); the three builders live in the
  one new `api/services/provenance.py`. CLAUDE.md's router count stays true.
- **R-PB16 — P5's inbox half needs no server field.** The cause already carries the excerpt
  window's absolute `start` and the mention offsets relative to it (`inbox_context.py:94-135`,
  `:284-292`); the Reader opens `/text?start=<start+m0>&end=<start+m1>` with no hash (the cause is
  recomputed at read, so it is `current` by construction).

---

## Coordination with parallel tracks

- **Local sources** (`feat/local-sources`): writes the same `turns` key through its own
  `episode_staging.py`. The contract is the key, the shape, and "offset = a turn start in the parsed
  body"; `evidence.turn_stamps` is the one reader for both writers. If that track moves
  `_stage_episodes`, `_message_line` / `_turn_stamps` / `MAX_TURN_STAMPS` move with it (two call
  sites, kept deliberately small).
- **Note-takers (`speaker:` family):** extends `_TURN_RE` + the role mapping in `evidence.py` only;
  `test_turns_agree_with_speaker_kind_at_every_offset` keeps the Reader and the chip in lockstep.
- **Search everywhere** (`feat/search-everywhere`): may back `/citations` with FTS later; the
  response shape and `partial` stay. This track imports nothing from it.
- **Remote connector:** a `claude-web` author is classified by whatever that track teaches
  `_classify_author_kind`; `author_identity` inherits it.
- **Imports + onboarding:** a reworked import pipeline must keep the two `_turn_stamps` call sites.
- **The Swift viewer (later):** consumes these payloads per design §4.1 (every field decoded
  optional-with-default).

---

## File map

| File | Responsibility |
|---|---|
| `api/services/evidence.py` | `_marker_lines`, `turn_starts`, `SPAN_*`, `span_status` (T1); `TurnSpan`, `turns`, `turn_stamps`, `source_document` (T3) |
| `api/routers/episodes.py` | `/span` gains `grown` (T1); `GET /episodes/{id}/text` (T3); `GET /episodes/{id}/citations` (T5) |
| `api/services/inbox_context.py` | `_asserted_span` reads `span_status` (T1) |
| `api/routers/conversations.py` | `MAX_TURN_STAMPS`, `_message_line`, `_turn_stamps`; the sidecar in both writers (T2) |
| `api/services/provenance.py` (new) | `episode_document` (T3), `entity_provenance` (T4), `episode_citations` (T5) |
| `api/services/git_service.py` | `author_identity`, `MAX_PROVENANCE_COMMITS`, `entity_commit_authors`; history rows carry kind/provider (T4) |
| `api/services/transclusion_resolver.py` | `_to_model` → public `claim_to_model`, the one `ClaimModel` builder, with the author fields (T4) |
| `api/routers/claims.py` | `_claim_to_model` delegates to `claim_to_model`; `GET /entities/{id}/provenance` (T4) |
| `api/services/ask_service.py` | `_claim_evidence`; `claim_id` + `evidence` on claim-first citations (T5) |
| `api/models/schemas.py` | `EpisodeSpan.grown` (T1); `EpisodeTurn`, `EpisodeFocus`, `EpisodeText` (T3); `ProvenanceSpan`, `ProvenanceContributor`, `ProvenanceConversation`, `ProvenancePage`, `ProvenanceTotals`, `EntityProvenance`, `ClaimModel`/`EntityHistoryEntry` fields (T4); `EpisodeCitation`, `EpisodeCitationEntity`, `EpisodeCitations`, `AskCitation` fields (T5) |
| Tests (new) | `api/tests/test_evidence_grown.py` (T1), `test_import_turn_stamps.py` (T2), `test_episode_text_endpoint.py` (T3), `test_entity_provenance.py` (T4), `test_episode_citations.py` + `test_ask_evidence.py` (T5) |
| Docs | `docs/goals/memory-evolution.md` (G118, G103, G106, G115), `docs/goals/TODO.md`, `CLAUDE.md` (T6) |

---

### Task 1: `grown` — a conversation that continued stops reading stale (A7)

**Files:**
- Modify: `api/services/evidence.py` (`__all__` `:39-43`; insert after `speaker_kind`, `:186`)
- Modify: `api/routers/episodes.py:1-15` (docstring), `:48-59`
- Modify: `api/models/schemas.py:689-706` (`EpisodeSpan`)
- Modify: `api/services/inbox_context.py:296-307` (`_asserted_span`)
- Test: `api/tests/test_evidence_grown.py` (new)
- Also stage: `docs/superpowers/plans/2026-09-23-provenance-backend.md` (this plan)

**Interfaces:**
- Produces `evidence._marker_lines(text) -> list[tuple[int, str, int]]`, `evidence.turn_starts(text) -> list[int]`, `evidence.SPAN_CURRENT/SPAN_GROWN/SPAN_STALE`, `evidence.span_status(text, *, end, hash, appendable=True) -> str`; `EpisodeSpan.grown: bool`.
- Consumes `_TURN_RE`, `body_hash`, `speaker_kind` (unchanged).

- [ ] **Step 1: Failing tests** — create `api/tests/test_evidence_grown.py`:

```python
"""G118 slice 2 (A7) — a span in a conversation that CONTINUED is `grown`, not `stale`.

Slice 1 compared a span's stored hash with the whole current text, so every
span in a Stop-hook episode read `stale` the moment the session took another
turn (the hook rewrites the session's ONE episode in place with appended
turns — G104/G105), and every span in a G20-grown chat export did the same.
`evidence.span_status` tries the turn-boundary prefixes before giving up:
exact, never fuzzy, one pass. Fixtures are synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index, evidence, inbox_service, markdown_parser
from api.services import transcript_capture as tc
from api.services.claims import Claim, Evidence, write_claims

BODY = (
    "user: Should alpha-project move to sqlite-vec?\n"
    "assistant: Yes — bob-example agreed last week.\n"
    "user: Then ship it."
)
GROWN = BODY + "\nassistant: Shipped.\nuser: Thanks."
SID = "22222222-3333-4444-8555-666666666666"


def _span(text: str, quote: str) -> tuple[int, int]:
    start = text.index(quote)
    return start, start + len(quote)


# ---------- turn_starts: the lines speaker_kind reads, and nothing else ----------


def test_turn_starts_are_exactly_the_marker_lines_speaker_kind_reads():
    text = "preamble\nuser: a\nb\nASSISTANT:  c\nsystem: d\nunknown: e\nAI: f"
    starts = evidence.turn_starts(text)
    assert starts == [text.index("user:"), text.index("ASSISTANT:"), text.index("system:"),
                      text.index("unknown:"), text.index("AI:")]
    assert [evidence.speaker_kind(text, s) for s in starts] == ["user", "assistant", "user", "user", "assistant"]


def test_a_marker_less_document_has_no_turn_starts():
    assert evidence.turn_starts("A note with no speaker lines.\nuser mentioned: nothing") == []


# ---------- span_status ----------


def test_current_when_the_hash_matches_or_none_was_given():
    _s, e = _span(BODY, "bob-example agreed")
    assert evidence.span_status(BODY, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_CURRENT
    assert evidence.span_status(BODY, end=e, hash="") == evidence.SPAN_CURRENT
    assert evidence.span_status(BODY, end=e, hash=None) == evidence.SPAN_CURRENT


def test_grown_when_turns_were_appended_after_the_span_was_minted():
    s, e = _span(BODY, "bob-example agreed")
    assert evidence.span_status(GROWN, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_GROWN
    assert GROWN[s:e] == BODY[s:e]  # the offsets still mean the same words


def test_stale_when_a_byte_before_the_span_changed():
    _s, e = _span(BODY, "bob-example agreed")
    edited = GROWN.replace("Should", "Shall")
    assert evidence.span_status(edited, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_STALE


def test_stale_when_the_matching_prefix_ends_before_the_span():
    # The only prefix hashing to the old value is BODY itself; a span that
    # reaches past it cannot have been minted against it.
    _s, e = _span(GROWN, "Shipped")
    assert evidence.span_status(GROWN, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_STALE


def test_a_page_never_grows():
    _s, e = _span(BODY, "bob-example agreed")
    assert evidence.span_status(GROWN, end=e, hash=evidence.body_hash(BODY),
                                appendable=False) == evidence.SPAN_STALE


def test_grown_is_exact_across_non_ascii_text():
    base = "user: café 🙂 naïve résumé\nassistant: 東京 ok"
    _s, e = _span(base, "東京")
    assert evidence.span_status(base + "\nuser: more 🙂", end=e,
                                hash=evidence.body_hash(base)) == evidence.SPAN_GROWN


# ---------- through the real writers ----------


def _line(typ: str, content, ts: str = "2026-09-03T10:00:00.000Z") -> str:
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": typ, "content": content}})


def _transcript(turns: list[tuple[str, str]]) -> str:
    return "\n".join(_line(r, t if r == "user" else [{"type": "text", "text": t}]) for r, t in turns) + "\n"


@pytest.fixture
def bank(tmp_path: Path, monkeypatch) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    projects = tmp_path / "claude-projects"
    (projects / "-home-example-alpha-project").mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: projects)
    monkeypatch.setattr(tc, "_episode_cache", {})
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_a_stop_hook_episode_that_took_another_turn_reads_grown_not_stale(bank, tmp_path):
    transcript = tmp_path / "claude-projects" / "-home-example-alpha-project" / f"{SID}.jsonl"
    first = [("user", "Should alpha-project move to sqlite-vec?"),
             ("assistant", "Yes — bob-example agreed last week.")]
    transcript.write_text(_transcript(first), encoding="utf-8")
    r1 = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                               cwd=None, keep_assistant=True)
    ev = evidence.verify(bank, r1.episode_id, "bob-example agreed")
    assert ev.is_span() and ev.kind == "assistant"

    transcript.write_text(_transcript(first + [("user", "Then ship it."), ("assistant", "Shipped.")]),
                          encoding="utf-8")
    r2 = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                               cwd=None, keep_assistant=True)
    assert r2.status == "updated" and r2.episode_id == r1.episode_id

    params = {"start": ev.start, "end": ev.end, "hash": ev.hash}
    with TestClient(main.app) as client:
        grown = client.get(f"/episodes/{ev.episode}/span", params=params).json()
        assert grown["stale"] is False and grown["grown"] is True
        assert grown["text"] == "bob-example agreed"

        # A byte edited BEFORE the span: nothing may be highlighted.
        path = bank / "episodes" / f"{ev.episode}.md"
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("Should", "Shall", 1))
        stale = client.get(f"/episodes/{ev.episode}/span", params=params).json()
    assert stale["stale"] is True and stale["grown"] is False


def test_a_current_span_reports_grown_false(bank):
    markdown_parser.write(bank / "episodes" / "ep_2026-09-01_001.md", {"id": "ep_2026-09-01_001"}, BODY)
    s, e = _span(BODY, "bob-example agreed")
    with TestClient(main.app) as client:
        data = client.get("/episodes/ep_2026-09-01_001/span",
                          params={"start": s, "end": e, "hash": evidence.body_hash(BODY)}).json()
    assert data["stale"] is False and data["grown"] is False


def test_a_grown_chat_export_reads_grown(tmp_path):
    def export(messages):
        return [{"uuid": "uuid-grow", "name": "Planning", "created_at": "2026-02-24T12:39:00.000000Z",
                 "updated_at": f"2026-02-24T13:{len(messages):02d}:00.000000Z",
                 "chat_messages": [{"uuid": f"m{i}", "sender": s, "text": t, "content": [],
                                    "created_at": f"2026-02-24T12:39:{i:02d}.000000Z"}
                                   for i, (s, t) in enumerate(messages)]}]

    ep_dir = tmp_path / "episodes"
    first = [("human", "Does alpha-project use sqlite-vec?"), ("assistant", "Yes, since last week.")]
    conv._stage_episodes(conv.parse_anthropic_conversations(export(first)), ep_dir)
    path = next(ep_dir.glob("*.md"))
    ev = evidence.verify(tmp_path, path.stem, "since last week")
    conv._stage_episodes(conv.parse_anthropic_conversations(export(first + [("human", "Great.")])), ep_dir)
    text = evidence.source_text(tmp_path, path.stem)
    assert text.endswith("user: Great.")
    assert evidence.span_status(text, end=ev.end, hash=ev.hash) == evidence.SPAN_GROWN


def test_the_inbox_cause_keeps_its_asserted_span_when_the_conversation_continued(tmp_path):
    bank_index.invalidate()
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    (memory / "inbox").mkdir()
    ep_path = memory / "episodes" / "ep_2026-08-20_001.md"
    first = "user: Bob Example moved to beta-corp last week."
    markdown_parser.write(ep_path, {"id": "ep_2026-08-20_001", "timestamp": "2026-08-20T10:00:00+00:00",
                                    "title": "Planning", "session_id": "ses_2026-08-20_abcdef12",
                                    "harness": "claude-code", "origin": "claude-code", "processed": True}, first)
    s, e = _span(first, "moved to beta-corp")
    claim = Claim(id="clm_2026-08-20_b2", text="Bob Example works at beta-corp", subject="bob-example",
                  predicate="works-at", object="beta-corp", valid_from="2026-08-20", recorded_at="2026-08-20",
                  source_episodes=["ep_2026-08-20_001"],
                  evidence=[Evidence(episode="ep_2026-08-20_001", start=s, end=e, kind="user",
                                     hash=evidence.body_hash(first))])
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active", "confidence": 0.6,
                           "created": "2026-08-01", "last_referenced": "2026-08-20", "source_episodes": [],
                           "tags": [], "related": [], "version": 1},
                          write_claims("# Bob Example\n", [claim]))
    markdown_parser.write(memory / "inbox" / "inbox-005.md",
                          {"status": "pending", "required_input": "choice", "created_date": "2026-08-21",
                           "kind": "conflict", "entity_id": "bob-example", "entity_name": "Bob Example",
                           "title": "q", "predicate": "works-at", "question": "q?",
                           "claim_id": "clm_2026-08-20_b2",
                           "options": [{"key": "b", "label": "beta-corp", "claim_id": "clm_2026-08-20_b2"}]},
                          "ctx")
    # The conversation continued after Sleep minted the span.
    markdown_parser.write(ep_path, markdown_parser.parse(ep_path).frontmatter,
                          first + "\nassistant: Noted.\nuser: And bob-example starts Monday.")
    [item] = inbox_service.load_inbox(memory)
    assert item.cause.span_kind == "asserted"
    ms, me = item.cause.mention_offsets[0]
    assert item.cause.excerpt[ms:me] == "moved to beta-corp"
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: module 'api.services.evidence' has no attribute 'turn_starts'` / `'span_status'`, `KeyError: 'grown'`, and the inbox test's `span_kind == "derived"`):

`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_evidence_grown.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement.**

(a) `api/services/evidence.py` — replace `__all__` (`:39-43`) with:

```python
__all__ = [
    "EVIDENCE_KINDS", "MAX_QUOTE_CHARS", "body_hash", "is_episode_id", "source_path",
    "source_text", "locate", "speaker_kind", "reasoning", "verify", "verify_many",
    "attach_relationship_evidence",
    # G118 slice 2
    "SPAN_CURRENT", "SPAN_GROWN", "SPAN_STALE", "turn_starts", "span_status",
]
```

(b) Insert directly after `speaker_kind` (after `:186`, before `def reasoning`):

```python
def _marker_lines(text: str) -> list[tuple[int, str, int]]:
    """``(line start, marker word, content start)`` for every turn-marker line.

    The SAME lines :func:`speaker_kind` treats as turn boundaries — same
    ``_TURN_RE``, same ``splitlines`` — so a turn's role and a span's kind can
    never disagree (slice 2, R-PB3: one parser, server-side). ``content start``
    skips the marker and the spaces after it, so no client runs a regex of its
    own. Ascending by construction.
    """
    out: list[tuple[int, str, int]] = []
    pos = 0
    for line in (text or "").splitlines(keepends=True):
        m = _TURN_RE.match(line)
        if m:
            content = m.end()
            while content < len(line) and line[content] in " \t":
                content += 1
            out.append((pos, m.group(1).lower(), pos + content))
        pos += len(line)
    return out


def turn_starts(text: str) -> list[int]:
    """Offsets of every turn-marker line, ascending (R-PB3)."""
    return [start for start, _marker, _content in _marker_lines(text)]


# G118 slice 2 (design amendment A7) — what a stored span's hash says about the
# text it is read against NOW. `grown` is exact: the offsets still index the
# words that were cited, so it highlights; `stale` never does (§4.9).
SPAN_CURRENT = "current"
SPAN_GROWN = "grown"
SPAN_STALE = "stale"


def span_status(
    text: str,
    *,
    end: int,
    hash: str | None,  # noqa: A002 - the field's own name
    appendable: bool = True,
) -> str:
    """A7 (amends slice-1 R2): is a span minted against ``hash`` still exact here?

    Slice 1 compared the stored hash with the WHOLE current text, so every
    span in a conversation that continued after Sleep read ``stale``: the Stop
    hook rewrites a session's one episode in place with appended turns
    (``transcript_capture.capture_transcript``), G20 rewrites a grown chat
    export the same way, and ``transcript_extract.SESSION_CAP_CHARS`` is
    head-stable precisely so those offsets do not move. So when the whole text
    does not match, try every prefix that ends at the newline just before a
    turn-marker line and still covers the span (``cut >= end``): if one hashes
    to ``hash``, the cited text is byte-identical and the answer is ``grown``.

    One incremental pass (``update`` + ``copy``), so it costs O(len) however
    many turns there are. Exact — a 48-bit hash over a string that was once
    the whole body — and never fuzzy. ``appendable=False`` for a ``page``
    document: a description is rewritten, not appended, so a prefix match
    there would be a coincidence. No ``hash`` means nothing to be stale
    against: ``current`` (slice-1 R2).
    """
    if not hash:
        return SPAN_CURRENT
    text = text or ""
    if body_hash(text) == hash:
        return SPAN_CURRENT
    if not appendable:
        return SPAN_STALE
    digest = hashlib.sha256()
    pos = 0
    for start in turn_starts(text):
        cut = start - 1
        if cut < 0 or text[cut] != "\n":
            continue
        digest.update(text[pos:cut].encode("utf-8"))
        pos = cut
        if cut >= end and digest.copy().hexdigest()[:12] == hash:
            return SPAN_GROWN
    return SPAN_STALE
```

(c) `api/routers/episodes.py` — in the module docstring replace

```text
construction — one ``markdown_parser.parse`` and string slicing (G80) —
and honest about drift: ``stale`` is set when the caller's ``hash`` no
longer matches the current evidence text (R2), and the slice is still
returned so the viewer can show *something* while saying it may have moved.
```

with

```text
construction — one ``markdown_parser.parse`` and string slicing (G80) —
and honest about drift: ``stale`` is set when the caller's ``hash`` matches
neither the current evidence text (R2) nor, for an episode, any
turn-boundary prefix of it — that case is ``grown`` (slice 2 / A7: the
conversation continued and the offsets are still exact). The slice is
returned either way so the viewer can show *something* while saying it may
have moved.
```

and replace `:48-59` (from `current = evidence.body_hash(text)` to the end of the return) with:

```python
    # A7: one freshness rule for every reader (R-PB1) — a Stop-hook episode
    # that took another turn is `grown`, not `stale`; a page never grows.
    status = evidence.span_status(
        text, end=end, hash=hash, appendable=evidence.is_episode_id(episode_id),
    )
    return EpisodeSpan(
        episode=episode_id,
        text=text[start:end],
        before=text[max(0, start - context):start],
        after=text[end:end + context],
        start=start,
        end=end,
        length=len(text),
        stale=status == evidence.SPAN_STALE,
        grown=status == evidence.SPAN_GROWN,
        kind=evidence.speaker_kind(text, start) if evidence.is_episode_id(episode_id) else "page",
    )
```

(d) `api/models/schemas.py` — `EpisodeSpan` (`:689-706`): append to the docstring, before the closing
`"""`:

```text
    ``grown`` (G118 slice 2, amendment A7) is true when the document was
    APPENDED to after the span was minted and a turn-boundary prefix still
    hashes to ``hash``: the offsets are exact and the span highlights.
    ``stale`` and ``grown`` are never both true.
```

and add the field after `stale: bool = False`:

```python
    grown: bool = False
```

(e) `api/services/inbox_context.py` — in `_asserted_span` replace

```python
        if e.hash and e.hash != ev.body_hash(body):
            continue
```

with

```python
        # G118 slice 2 (R-PB14): a conversation that continued after the
        # span was minted keeps its exact quote (`grown`); only `stale` falls
        # back to the derived name match.
        if ev.span_status(body, end=e.end, hash=e.hash) == ev.SPAN_STALE:
            continue
```

- [ ] **Step 4: Run — expect PASS:**
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_evidence_grown.py api/tests/test_evidence.py api/tests/test_episode_span_endpoint.py api/tests/test_inbox_context.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite** — `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 6: Commit** —
`cd <worktree> && git add api/services/evidence.py api/routers/episodes.py api/models/schemas.py api/services/inbox_context.py api/tests/test_evidence_grown.py docs/superpowers/plans/2026-09-23-provenance-backend.md && git commit -m "feat(provenance): grown spans — a conversation that continued no longer reads stale (G118 s2, A7)"`
(body: one paragraph naming R-PB1/R-PB14; end with the session's attribution trailer).

---

### Task 2: The chat importer keeps each message's time (R-PB4)

**Files:**
- Modify: `api/routers/conversations.py` — new constant + two helpers above `_stage_episodes`
  (`:746`); `:799-802` (body build); `_write_new_episode` `:900-920`; `_update_episode_in_place`
  `:934-943`
- Test: `api/tests/test_import_turn_stamps.py` (new)

**Interfaces:**
- Produces `conversations.MAX_TURN_STAMPS`, `conversations._message_line(msg) -> str`,
  `conversations._turn_stamps(messages, body) -> list[dict]`; episode frontmatter
  `turns: [{offset, ts, speaker}]` on imported episodes.
- Consumes `_normalise_import_timestamp` (`:856`), `evidence.turn_starts` (T1, tests only).

- [ ] **Step 1: Failing tests** — create `api/tests/test_import_turn_stamps.py`:

```python
"""G118 slice 2 / R-PB4 — the chat importer keeps each message's time.

The parsers always read per-message times and `_stage_episodes` threw them
away. They now ride beside the body as `turns: [{offset, ts, speaker}]` — the
exact key and shape the Local-sources track writes — and never enter
`content_hash`, so a re-import of an unchanged thread is still a byte-
identical SKIP. Synthetic exports only.
"""
from __future__ import annotations

import hashlib

from api.routers import conversations as conv
from api.services import bank_index, evidence, markdown_parser


def _claude(uuid: str, messages: list[tuple[str, str]], *, updated: str = "2026-02-24T13:00:00.000000Z",
            times: bool = True) -> list[dict]:
    return [{
        "uuid": uuid, "name": "Planning", "created_at": "2026-02-24T12:39:00.000000Z", "updated_at": updated,
        "chat_messages": [
            {"uuid": f"{uuid}-m{i}", "sender": sender, "text": text, "content": [],
             **({"created_at": f"2026-02-24T12:39:{i:02d}.000000Z"} if times else {})}
            for i, (sender, text) in enumerate(messages)
        ],
    }]


def _only(ep_dir):
    [path] = list(ep_dir.glob("*.md"))
    return path, markdown_parser.parse(path)


def test_a_claude_import_keeps_each_message_time_beside_the_body(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Does alpha-project use sqlite-vec?"), ("assistant", "Yes.")])), ep_dir)
    _path, parsed = _only(ep_dir)
    turns = parsed.frontmatter["turns"]
    assert turns == [
        {"offset": 0, "ts": "2026-02-24T12:39:00+00:00", "speaker": "user"},
        {"offset": len("user: Does alpha-project use sqlite-vec?") + 1,
         "ts": "2026-02-24T12:39:01+00:00", "speaker": "assistant"},
    ]
    for entry in turns:
        assert set(entry) == {"offset", "ts", "speaker"}  # the coordination contract, exactly
        assert entry["offset"] in evidence.turn_starts(parsed.body)
        assert parsed.body[entry["offset"]:].startswith(f"{entry['speaker']}:")
    assert list(parsed.frontmatter)[-1] == "turns"  # always the last key


def test_a_chatgpt_import_keeps_its_epoch_times(tmp_path):
    data = [{"conversation_id": "conv-1", "title": "Chat", "create_time": 1_700_000_000,
             "update_time": 1_700_000_500, "mapping": {
                 "n1": {"message": {"author": {"role": "user"}, "content": {"parts": ["hello alpha-project"]},
                                    "create_time": 1_700_000_000}},
                 "n2": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["hi"]},
                                    "create_time": 1_700_000_060}},
             }}]
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_chatgpt_json(data), ep_dir)
    _path, parsed = _only(ep_dir)
    assert [(t["ts"], t["speaker"]) for t in parsed.frontmatter["turns"]] == [
        ("2023-11-14T22:13:20+00:00", "user"), ("2023-11-14T22:14:20+00:00", "assistant")]


def test_the_sidecar_never_enters_the_content_hash(tmp_path):
    msgs = [("human", "Q1"), ("assistant", "A1")]
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs)), tmp_path / "a" / "episodes")
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs, times=False)),
                         tmp_path / "b" / "episodes")
    _pa, a = _only(tmp_path / "a" / "episodes")
    _pb, b = _only(tmp_path / "b" / "episodes")
    assert a.body == b.body
    assert a.frontmatter["content_hash"] == b.frontmatter["content_hash"] \
        == hashlib.sha256(a.body.encode()).hexdigest()[:12]
    assert "turns" in a.frontmatter and "turns" not in b.frontmatter


def test_an_unchanged_reimport_is_a_byte_identical_skip(tmp_path):
    ep_dir = tmp_path / "episodes"
    data = _claude("u1", [("human", "Q1"), ("assistant", "A1")])
    conv._stage_episodes(conv.parse_anthropic_conversations(data), ep_dir)
    path, _ = _only(ep_dir)
    before = path.read_bytes()
    assert conv._stage_episodes(conv.parse_anthropic_conversations(data), ep_dir) == (0, 0, 1)
    assert path.read_bytes() == before


def test_a_skip_never_backfills_times_onto_an_old_import(tmp_path):
    ep_dir = tmp_path / "episodes"
    msgs = [("human", "Q1"), ("assistant", "A1")]
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs, times=False)), ep_dir)
    path, _ = _only(ep_dir)
    before = path.read_bytes()
    assert conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs)), ep_dir) == (0, 0, 1)
    assert path.read_bytes() == before  # R-PB4: a SKIP means untouched


def test_a_grown_reimport_rewrites_the_sidecar(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Q1"), ("assistant", "A1")])), ep_dir)
    grown = _claude("u1", [("human", "Q1"), ("assistant", "A1"), ("human", "Q2")],
                    updated="2026-02-25T09:00:00.000000Z")
    assert conv._stage_episodes(conv.parse_anthropic_conversations(grown), ep_dir) == (0, 1, 0)
    _path, parsed = _only(ep_dir)
    assert [t["offset"] for t in parsed.frontmatter["turns"]] == evidence.turn_starts(parsed.body)
    assert parsed.frontmatter["turns"][-1] == {
        "offset": parsed.body.rindex("user: Q2"), "ts": "2026-02-24T12:39:02+00:00", "speaker": "user"}


def test_an_update_that_loses_its_times_drops_the_key(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", [("human", "Q1")])), ep_dir)
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Q1"), ("assistant", "A1")], times=False,
                updated="2026-02-25T09:00:00.000000Z")), ep_dir)
    _path, parsed = _only(ep_dir)
    assert "turns" not in parsed.frontmatter


def test_messages_without_times_write_no_turns_key(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv._parse_chatgpt_html(
        "<div class='conversation'><p>a message long enough to keep</p></div>"), ep_dir)
    _path, parsed = _only(ep_dir)
    assert "turns" not in parsed.frontmatter


def test_the_sidecar_is_capped_head_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(conv, "MAX_TURN_STAMPS", 2)
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Q1"), ("assistant", "A1"), ("human", "Q2")])), ep_dir)
    _path, parsed = _only(ep_dir)
    assert [t["ts"] for t in parsed.frontmatter["turns"]] == [
        "2026-02-24T12:39:00+00:00", "2026-02-24T12:39:01+00:00"]


def test_a_body_that_is_not_the_messages_own_rendering_gets_no_sidecar(tmp_path):
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    (episode,) = conv.parse_anthropic_conversations(_claude("u1", [("human", "Q"), ("assistant", "A")]))
    path = conv._write_new_episode(episode, ep_dir, "user: Q", "abc124", {})
    assert "turns" not in markdown_parser.parse(path).frontmatter


def test_bank_index_reads_times_as_strings(tmp_path):
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", [("human", "Q1")])),
                         tmp_path / "episodes")
    bank_index.invalidate()
    [f] = bank_index.files(tmp_path, "episodes")
    assert isinstance(f.frontmatter["turns"][0]["ts"], str)
```

- [ ] **Step 2: Run — expect FAIL: 6 failed, 5 passed** (`KeyError: 'turns'`; `AttributeError: … has no attribute 'MAX_TURN_STAMPS'`). The five that pass already are guards that pin what must NOT change — `test_an_unchanged_reimport_is_a_byte_identical_skip`, `test_a_skip_never_backfills_times_onto_an_old_import`, `test_an_update_that_loses_its_times_drops_the_key`, `test_messages_without_times_write_no_turns_key`, `test_a_body_that_is_not_the_messages_own_rendering_gets_no_sidecar`.

`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_import_turn_stamps.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement** in `api/routers/conversations.py`.

(a) Directly above `def _stage_episodes(` (after the `# --- Staging ---` comment):

```python
# G118 slice 2 / R-PB4 — per-message times, kept BESIDE the body.
# The parsers have always read each message's own time (`created_at`,
# `create_time`) and staging threw it away, so a span could say WHERE in a
# thread a belief came from but never WHEN. The body cannot carry it:
# `content_hash` is computed over the exact `role: text` lines, and a new body
# shape would "update" every already-imported thread on the next re-import and
# re-queue the whole corpus for Sleep (paid). So the times ride in frontmatter
# as `turns: [{offset, ts, speaker}]` — the key and shape the Local-sources
# track writes too — outside the hash by construction.
#
# Capped, head-stable, because frontmatter is parsed on every cold
# `bank_index` scan: measured 2026-09-23 (CPython 3.12, PyYAML's pure-Python
# SafeLoader) a sidecar costs ~2.9 ms at 50 entries, ~11.5 ms at 200 and
# ~28 ms at 500 per parse, against ~0.14 ms for the same frontmatter without
# it. Turns past the cap carry no time; the Reader shows a time only when one
# is stored and never infers one.
MAX_TURN_STAMPS = 500


def _message_line(msg: dict) -> str:
    """One body line — the ONLY place the importer spells its `role: text`
    shape, so the hashed body and `_turn_stamps`' offsets cannot disagree."""
    return f"{msg['role']}: {msg['text']}"


def _turn_stamps(messages: list[dict], body: str) -> list[dict]:
    """``[{offset, ts, speaker}]`` for ``body``, or ``[]`` (R-PB4).

    ``offset`` is the message's ``role:`` line start in the evidence text —
    ``markdown_parser.parse`` strips the body, and one built from stripped
    message texts has nothing to strip — so it is a turn start
    ``evidence.turns`` finds. ``speaker`` is the role that line is marked
    with; ``ts`` the message's own time in the one aware-UTC shape. A message
    without a time gets no entry (it would only repeat the marker). Returns
    ``[]`` when ``body`` is not exactly these messages' own rendering: the
    offsets would vouch for text they do not index.
    """
    lines = [_message_line(msg) for msg in messages]
    if "\n".join(lines) != body:
        return []
    out: list[dict] = []
    offset = 0
    for msg, line in zip(messages, lines):
        ts = _normalise_import_timestamp(msg.get("timestamp"))
        if ts and len(out) < MAX_TURN_STAMPS:
            out.append({"offset": offset, "ts": ts, "speaker": str(msg["role"])})
        offset += len(line) + 1
    return out
```

(b) In `_stage_episodes`, replace

```python
        content_lines: list[str] = []
        for msg in episode.get("messages", []):
            content_lines.append(f"{msg['role']}: {msg['text']}")
        content_str = "\n".join(content_lines)
```

with

```python
        content_str = "\n".join(_message_line(msg) for msg in episode.get("messages", []))
```

(c) In `_write_new_episode`, immediately before `path = episodes_dir / f"{episode_id}.md"`:

```python
    # G118 slice 2 (R-PB4): each message's time beside the body — outside
    # `content_hash`, and the LAST key so the thread's identity reads first.
    turns = _turn_stamps(episode.get("messages", []), content_str)
    if turns:
        frontmatter["turns"] = turns
```

(d) In `_update_episode_in_place`, immediately before `markdown_parser.write(path, fm, content_str)`:

```python
    # G118 slice 2 (R-PB4): the grown thread's times replace the old ones; a
    # re-export that lost them drops the key rather than keeping stale offsets.
    turns = _turn_stamps(episode.get("messages", []), content_str)
    fm.pop("turns", None)
    if turns:
        fm["turns"] = turns
```

- [ ] **Step 4: Run — expect PASS:**
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_import_turn_stamps.py api/tests/test_conversations.py api/tests/test_evidence_grown.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite** → 0 failures.

- [ ] **Step 6: Commit** —
`cd <worktree> && git add api/routers/conversations.py api/tests/test_import_turn_stamps.py && git commit -m "feat(import): keep each message's time as a turns sidecar outside content_hash (G118 s2, R-PB4)"`

---

### Task 3: `GET /episodes/{id}/text` — the whole conversation, with its turns (P2)

**Files:**
- Modify: `api/services/evidence.py` (import `dataclass`; `__all__`; `TurnSpan`, `turns`,
  `turn_stamps`, `source_document`; `source_text` delegates)
- Create: `api/services/provenance.py`
- Modify: `api/routers/episodes.py` (imports, docstring, new route)
- Modify: `api/models/schemas.py` (after `EpisodeSpan`: `EpisodeTurn`, `EpisodeFocus`, `EpisodeText`)
- Test: `api/tests/test_episode_text_endpoint.py` (new)

**Interfaces:**
- Produces `evidence.TurnSpan`, `evidence.turns(text, *, page=False, stamps=None)`,
  `evidence.turn_stamps(frontmatter) -> dict[int, dict]`,
  `evidence.source_document(memory_path, doc_id) -> tuple[dict, str] | None`;
  `provenance.MAX_TEXT_CHARS`, `provenance.SpanOutOfRange`, `provenance.episode_document(...)`;
  `GET /episodes/{id}/text?start&end&hash&focus` → `EpisodeText`.
- Consumes `span_status`, `_marker_lines` (T1), the T2 sidecar, `inbox_context.locate_mention`,
  `id_utils.resolve_entity_file`, `sync_service.etag_for/conditional`.

- [ ] **Step 1: Failing tests** — create `api/tests/test_episode_text_endpoint.py`:

```python
"""G118 slice 2 — `GET /episodes/{id}/text`: the whole document for the Reader.

The Reader scrolls to a span inside the WHOLE conversation, so the server
returns the evidence text with its turn structure (one parser — the marker
lines `speaker_kind` reads), per-turn times only where the episode stores
them, and an optional asserted or derived focus. Engine-free, bank text only,
nothing written. Fixtures are synthetic.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index, evidence, markdown_parser, provenance
from api.services.claims import Claim, write_claims

SID = "44444444-5555-4666-8777-888888888888"
HOOK = (
    "user: Should alpha-project move to sqlite-vec?\n"
    "assistant: Yes — bob-example agreed last week.\n"
    "user: Then ship it."
)
LEGACY = "A note about alpha-project with no speaker lines."
MEDIA = "## Summary\nSaved.\n\n## Description\nA guide to alpha-project."
URL = "/episodes/ep_2026-09-03_001/text"


@pytest.fixture
def memory(tmp_path: Path, monkeypatch) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-09-03_001.md", {
        "id": "ep_2026-09-03_001", "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code",
        "origin": "claude-code", "title": "Sync race", "session_id": SID, "harness": "claude-code",
        "capture_kind": "transcript", "turns": 3, "project_dir": "/home/example/alpha-project"}, HOOK)
    markdown_parser.write(memory / "episodes" / "ep_2026-08-01_001.md",
                          {"id": "ep_2026-08-01_001", "title": "A note"}, LEGACY)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "decay_class": "active"}, "# Alpha Project\n")
    markdown_parser.write(memory / "entities" / "media-example-org.md",
                          {"name": "Example guide", "type": "media", "decay_class": "evergreen"},
                          write_claims(MEDIA, [Claim(id="c", text="t")]))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_the_whole_text_comes_back_with_its_turns(memory):
    with TestClient(main.app) as client:
        r = client.get(URL)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text"] == HOOK and data["length"] == len(HOOK) and data["hash"] == evidence.body_hash(HOOK)
    assert data["kind"] == "episode" and data["truncated"] is False
    assert [t["index"] for t in data["turns"]] == [1, 2, 3]
    assert [t["role"] for t in data["turns"]] == ["user", "assistant", "user"]
    assert [HOOK[t["contentStart"]:t["end"]] for t in data["turns"]] == [
        "Should alpha-project move to sqlite-vec?", "Yes — bob-example agreed last week.", "Then ship it."]
    assert all(t["ts"] is None for t in data["turns"])  # the hook's `turns: 3` is a count, not a sidecar
    for t in data["turns"]:
        assert evidence.speaker_kind(HOOK, t["start"]) == t["role"]


def test_the_header_names_the_conversation_and_never_its_project_dir(memory):
    with TestClient(main.app) as client:
        r = client.get(URL)
    data = r.json()
    assert (data["title"], data["harness"], data["origin"]) == ("Sync race", "claude-code", "claude-code")
    assert data["conversationId"] == SID and data["captureKind"] == "transcript"
    assert data["timestamp"] == "2026-09-03T10:00:00+00:00"
    assert "projectDir" not in data and "resumable" not in data  # R-PB5
    assert "/home/example" not in r.text


def test_per_turn_times_come_only_from_the_import_sidecar(memory):
    export = [{"uuid": "uuid-times", "name": "Planning", "created_at": "2026-02-24T12:39:00.000000Z",
               "updated_at": "2026-02-24T13:00:00.000000Z",
               "chat_messages": [
                   {"uuid": "m0", "sender": "human", "text": "Does alpha-project use sqlite-vec?", "content": [],
                    "created_at": "2026-02-24T12:39:00.000000Z"},
                   {"uuid": "m1", "sender": "assistant", "text": "Yes.", "content": [],
                    "created_at": "2026-02-24T12:39:01.000000Z"}]}]
    conv._stage_episodes(conv.parse_anthropic_conversations(export), memory / "episodes")
    [path] = [p for p in (memory / "episodes").glob("*.md")
              if markdown_parser.parse(p).frontmatter.get("source_id") == "uuid-times"]
    with TestClient(main.app) as client:
        data = client.get(f"/episodes/{path.stem}/text").json()
    assert [t["ts"] for t in data["turns"]] == ["2026-02-24T12:39:00+00:00", "2026-02-24T12:39:01+00:00"]
    assert [t["speaker"] for t in data["turns"]] == ["user", "assistant"]
    assert data["conversationId"] == "uuid-times"


def test_a_legacy_episode_without_markers_is_one_block(memory):
    with TestClient(main.app) as client:
        data = client.get("/episodes/ep_2026-08-01_001/text").json()
    assert data["turns"] == [{"index": 1, "start": 0, "contentStart": 0, "end": len(LEGACY),
                              "role": "user", "marker": None, "speaker": None, "ts": None}]


def test_a_page_is_one_page_block_with_the_claims_fence_excluded(memory):
    with TestClient(main.app) as client:
        data = client.get("/episodes/media-example-org/text").json()
    assert data["kind"] == "page" and data["title"] == "Example guide"
    assert data["text"] == evidence.source_text(memory, "media-example-org") and "claims" not in data["text"]
    assert [t["role"] for t in data["turns"]] == ["page"]


def test_an_asserted_focus_reports_its_kind_and_freshness(memory):
    s = HOOK.index("bob-example agreed")
    e = s + len("bob-example agreed")
    with TestClient(main.app) as client:
        ok = client.get(URL, params={"start": s, "end": e, "hash": evidence.body_hash(HOOK)}).json()["focus"]
        stale = client.get(URL, params={"start": s, "end": e, "hash": "deadbeefcafe"}).json()["focus"]
    assert ok == {"start": s, "end": e, "kind": "assistant", "derived": False, "stale": False, "grown": False}
    assert stale["stale"] is True and stale["start"] is None and stale["end"] is None  # R-PB2


def test_a_derived_focus_finds_the_entity_by_name_and_says_so(memory):
    with TestClient(main.app) as client:
        focus = client.get(URL, params={"focus": "alpha-project"}).json()["focus"]
        unknown = client.get(URL, params={"focus": "no-such-entity"}).json()["focus"]
    assert focus["derived"] is True and focus["kind"] == "derived"
    assert HOOK[focus["start"]:focus["end"]] == "alpha-project"
    assert unknown is None  # R-PB5: the document exists; the hint simply found nothing


def test_a_derived_focus_is_never_written_back(memory):
    with TestClient(main.app) as client:
        client.get(URL)  # the app's own startup work is done before the snapshot
        before = {p: p.read_bytes() for sub in ("episodes", "entities") for p in (memory / sub).rglob("*.md")}
        client.get(URL, params={"focus": "alpha-project"})
        after = {p: p.read_bytes() for sub in ("episodes", "entities") for p in (memory / sub).rglob("*.md")}
    assert after == before


def test_the_cap_truncates_text_and_turns_but_not_length_or_hash(memory, monkeypatch):
    monkeypatch.setattr(provenance, "MAX_TEXT_CHARS", 60)
    with TestClient(main.app) as client:
        data = client.get(URL).json()
    assert data["truncated"] is True and data["text"] == HOOK[:60]
    assert data["length"] == len(HOOK) and data["hash"] == evidence.body_hash(HOOK)
    assert [t["index"] for t in data["turns"]] == [1, 2]
    assert all(t["start"] < 60 and t["end"] <= 60 and t["contentStart"] <= 60 for t in data["turns"])


def test_bad_ids_and_ranges_are_refused(memory):
    with TestClient(main.app) as client:
        assert client.get("/episodes/ep_2026-01-01_999/text").status_code == 404
        assert client.get("/episodes/..%2Fepisodes%2Fep_2026-09-03_001/text").status_code in (404, 422)
        for params in ({"start": 0}, {"end": 5}, {"start": 5, "end": 5}, {"start": 0, "end": len(HOOK) + 1},
                       {"start": -1, "end": 3}):
            assert client.get(URL, params=params).status_code == 422, params


def test_the_etag_304s_and_moves_when_the_episode_changes(memory):
    path = memory / "episodes" / "ep_2026-09-03_001.md"
    with TestClient(main.app) as client:
        etag = client.get(URL).headers["etag"]
        assert client.get(URL, headers={"If-None-Match": etag}).status_code == 304
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, parsed.frontmatter, parsed.body + "\nassistant: Shipped.")
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        again = client.get(URL, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_the_text_endpoint_is_bearer_gated(memory, monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", "secret-token")
    with TestClient(main.app) as client:
        assert client.get(URL).status_code == 401
        assert client.get(URL, headers={"Authorization": "Bearer secret-token"}).status_code == 200


# ---------- pure helpers ----------


def test_turns_agree_with_speaker_kind_at_every_offset():
    text = "preamble\nuser: a\nb\nASSISTANT:  c\nsystem: d\nunknown: e\nAI: f"
    spans = evidence.turns(text)
    assert [(t.role, t.marker) for t in spans] == [
        ("user", None), ("user", "user"), ("assistant", "assistant"), ("user", "system"),
        ("user", "unknown"), ("assistant", "ai")]
    for t in spans:
        for off in range(t.start, t.end):
            assert evidence.speaker_kind(text, off) == t.role, (t, off)


def test_turn_stamps_ignores_the_hooks_count_and_malformed_entries():
    assert evidence.turn_stamps({"turns": 3}) == {}
    assert evidence.turn_stamps({}) == {}
    assert evidence.turn_stamps({"turns": [
        {"offset": "x"}, "junk", {"offset": -1, "ts": "t"},
        {"offset": 4, "ts": "2026-02-24T12:39:00+00:00", "speaker": "user"},
        {"offset": 4, "ts": "duplicate"},
        {"offset": 9, "speaker": "Speaker 2"},
    ]}) == {4: {"ts": "2026-02-24T12:39:00+00:00", "speaker": "user"}, 9: {"ts": None, "speaker": "Speaker 2"}}


def test_the_provenance_module_is_engine_free():
    """G80 / the transcript rail: no LLM, no vector index, and nothing that
    touches `~/.claude` may be imported by the read paths this module serves."""
    tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{a.name}" for a in node.names}
    forbidden = ("litellm", "agent_engine", "providers", "vector_index", "ask_service", "engine_select",
                 "session_stats", "transcript_capture", "transcript_extract")
    assert not [n for n in names if any(f in n for f in forbidden)], names


def test_a_focus_that_names_a_file_outside_entities_is_refused(memory):
    """`focus` is a free query string and `resolve_entity_file` joins it onto
    `entities/` as given, so `../outside` would reach a file the bank never
    stored as a page. Only a page inside `entities/` may name a mention."""
    markdown_parser.write(memory / "outside.md", {"name": "alpha-project"}, "not a page")
    with TestClient(main.app) as client:
        focus = client.get(URL, params={"focus": "../outside"}).json()["focus"]
    assert focus is None
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: cannot import name 'provenance'`):
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_episode_text_endpoint.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement.**

(a) `api/services/evidence.py`:
- add `from dataclasses import dataclass` to the imports;
- extend `__all__`'s slice-2 line to
  `"SPAN_CURRENT", "SPAN_GROWN", "SPAN_STALE", "turn_starts", "span_status", "TurnSpan", "turns", "turn_stamps", "source_document",`;
- replace `source_text` (`:94-105`) with:

```python
def source_document(memory_path: Path | None, doc_id: str) -> tuple[dict, str] | None:
    """``(frontmatter, evidence text)`` from ONE parse and the same resolver
    as :func:`source_text`, so the Reader's header and its text can never
    come from two different files (slice 2). ``None`` for an unknown or
    non-bare id."""
    path = source_path(memory_path, doc_id)
    if path is None:
        return None
    try:
        parsed = markdown_parser.parse(path)
    except Exception:
        return None
    body = parsed.body if is_episode_id(doc_id) else strip_claims_block(parsed.body)
    return (parsed.frontmatter or {}), body


def source_text(memory_path: Path | None, doc_id: str) -> str | None:
    """The evidence text of a document (R1): the parsed body for an episode;
    for an entity page, the body with the ```claims fence stripped — so the
    claim that cites a page never stales its own span by being written."""
    doc = source_document(memory_path, doc_id)
    return None if doc is None else doc[1]
```

- insert after `turn_starts` (before the `SPAN_*` constants):

```python
@dataclass
class TurnSpan:
    """One turn of a document, as offsets into its evidence text (slice 2).

    ``start`` is the first character of the turn's marker line (``user: …``),
    or of the document for a block before any marker; ``content_start`` skips
    the marker and the spaces after it; ``end`` is exclusive and stops before
    the newline that separates it from the next turn. ``role`` is exactly what
    :func:`speaker_kind` answers inside the turn (``user`` | ``assistant``), or
    ``page`` for an entity page. ``marker`` is the word as written, lower-cased
    — ``system``/``unknown`` count as the person under R4 and the Reader may
    say so — and ``None`` for a block with no marker line. ``ts``/``speaker``
    come only from a stored ``turns`` sidecar entry at exactly ``start``: a
    time is never inferred (§4.4).
    """

    index: int
    start: int
    content_start: int
    end: int
    role: str
    marker: str | None = None
    ts: str | None = None
    speaker: str | None = None


def turns(text: str, *, page: bool = False, stamps: dict[int, dict] | None = None) -> list[TurnSpan]:
    """The document as turns (R-PB3, R-PB5) — the marker lines
    :func:`speaker_kind` reads, so a turn's ``role`` and a span's ``kind``
    never disagree (``test_turns_agree_with_speaker_kind_at_every_offset``).

    A page is one ``page`` block. An episode with no marker at all (a legacy
    MCP note, a Telegram capture) is one ``user`` block — never an error — and
    text before the first marker is its own block under R4's default.
    """
    text = text or ""
    if not text:
        return []
    if page:
        return [TurnSpan(index=1, start=0, content_start=0, end=len(text), role="page")]
    stamps = stamps or {}
    blocks: list[tuple[int, str | None, int]] = list(_marker_lines(text))
    if not blocks or blocks[0][0] > 0:
        blocks.insert(0, (0, None, 0))
    out: list[TurnSpan] = []
    for i, (start, marker, content_start) in enumerate(blocks):
        nxt = blocks[i + 1][0] if i + 1 < len(blocks) else len(text)
        end = start + len(text[start:nxt].rstrip("\r\n"))
        stamp = stamps.get(start) or {}
        out.append(TurnSpan(
            index=i + 1, start=start, content_start=min(content_start, end), end=end,
            role="assistant" if marker in _ASSISTANT_ROLES else "user",
            marker=marker, ts=stamp.get("ts"), speaker=stamp.get("speaker"),
        ))
    return out


def turn_stamps(frontmatter: dict | None) -> dict[int, dict]:
    """The ``turns: [{offset, ts, speaker}]`` sidecar (R-PB4), keyed by offset.

    Written by the chat importer (``conversations._turn_stamps``) and by the
    Local-sources track's stager — the same key and shape, which IS the
    coordination contract. Tolerant by design: the Stop hook's
    ``turns: <count>`` (``transcript_capture``) is an int, not a sidecar, and
    reads as no stamps; a malformed or duplicate entry is skipped, never
    raised. ``ts``/``speaker`` pass through verbatim (``None`` when absent) —
    nothing here infers a time.
    """
    raw = (frontmatter or {}).get("turns")
    if not isinstance(raw, list):
        return {}
    out: dict[int, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            offset = int(entry.get("offset"))
        except (TypeError, ValueError):
            continue
        if offset < 0 or offset in out:
            continue
        ts, speaker = entry.get("ts"), entry.get("speaker")
        out[offset] = {
            "ts": str(ts) if ts not in (None, "") else None,
            "speaker": str(speaker) if speaker not in (None, "") else None,
        }
    return out
```

(b) `api/models/schemas.py` — after `EpisodeSpan`:

```python
class EpisodeTurn(CamelModel):
    """One turn of a document (G118 slice 2, design §4.8.1) — offsets into the
    evidence text, never a copy of it. See ``evidence.TurnSpan``: ``role`` is
    ``user`` | ``assistant`` | ``page``; ``marker`` is the word as written
    (``None`` for a marker-less block); ``ts``/``speaker`` exist only where the
    episode stores a ``turns`` sidecar entry for this turn."""

    index: int
    start: int
    content_start: int
    end: int
    role: str = "user"
    marker: Optional[str] = None
    speaker: Optional[str] = None
    ts: Optional[str] = None


class EpisodeFocus(CamelModel):
    """The span the Reader lands on (G118 slice 2). Asserted
    (``?start&end&hash``): ``kind`` is the speaker at ``start`` and
    ``stale``/``grown`` come from ``evidence.span_status``; a stale focus
    carries NO offsets (R-PB2 — stale never highlights). Derived
    (``?focus=<entity>``): ``kind == "derived"``, a name match found at read
    and never written (G100's class, R-PB9)."""

    start: Optional[int] = None
    end: Optional[int] = None
    kind: str = "user"
    derived: bool = False
    stale: bool = False
    grown: bool = False


class EpisodeText(CamelModel):
    """``GET /episodes/{id}/text`` — a whole stored document for the Reader
    (G118 slice 2, design §4.8.1). ``text`` is capped at 400,000 characters
    (``truncated``); ``length`` and ``hash`` always describe the WHOLE
    evidence text, so ``hash`` can be handed back to ``/span``. ``kind`` is
    ``episode`` or ``page``. ``conversation_id`` is the stamped ``session_id``
    or G20's ``source_id``; ``project_dir`` and ``resumable`` are deliberately
    absent — ``GET /conversations/{id}`` is the one place a transcript is
    ``isfile()``-d (R-PB5). Fetched on demand, not a Store domain."""

    episode: str
    kind: str = "episode"
    text: str = ""
    length: int = 0
    hash: str = ""
    truncated: bool = False
    title: str = ""
    timestamp: Optional[str] = None
    harness: Optional[str] = None
    origin: Optional[str] = None
    conversation_id: Optional[str] = None
    capture_kind: Optional[str] = None
    turns: list[EpisodeTurn] = []
    focus: Optional[EpisodeFocus] = None
```

(c) Create `api/services/provenance.py`:

```python
"""G118 slice 2 (server half) — reading provenance back out of the bank.

Slice 1 made every new claim point at the words it came from (``evidence``
spans, ``api/services/evidence.py``); nothing could yet show them. This module
builds the read payloads the viewer needs, and nothing else:

* :func:`episode_document` — ``GET /episodes/{id}/text``: the whole evidence
  text with its turns, so the Reader can scroll to a span and highlight it
  (design §4.4 / §4.8.1).
* :func:`entity_provenance` — ``GET /entities/{id}/provenance`` (§4.5 / §4.8.4).
* :func:`episode_citations` — ``GET /episodes/{id}/citations`` (§4.8.3, G106).

Rails, enforced here rather than documented:

* **Engine-free, bank text only** (G80, G48). No LLM, no vector index, and
  never a transcript under ``~/.claude`` — every document is a bank file
  resolved by ``evidence.source_path``. ``test_the_provenance_module_is_engine_free``
  pins the import list.
* **Spans, not copies; computed at read, never stored.** Excerpts and derived
  offsets are recomputed per call, and nothing here writes a file.
* **Never fuzzy; stale never highlights** (§4.9). An asserted span is the
  stored offsets judged by ``evidence.span_status``; a ``derived`` span is a
  name match (``inbox_context.locate_mention``), labelled and never written
  back (R-PB9); a stale span travels WITHOUT wash offsets (R-PB2).
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from api.models.schemas import EpisodeFocus, EpisodeText, EpisodeTurn
from api.services import evidence, inbox_context, markdown_parser
from api.services.id_utils import resolve_entity_file

# The Reader's cap (R-PB5). A Stop-hook episode is already capped at 100,000
# chars (`transcript_extract.SESSION_CAP_CHARS`); an import is not, and one
# pasted log in a chat export must not become a multi-megabyte response.
# Characters, not bytes: offsets index code points and the cut must land on one.
MAX_TEXT_CHARS = 400_000


class SpanOutOfRange(ValueError):
    """A caller-supplied ``[start, end)`` that is not inside the document."""


def _opt(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _asserted_focus(text: str, start: int, end: int, hash: str | None, *,  # noqa: A002
                    is_episode: bool) -> EpisodeFocus:
    status = evidence.span_status(text, end=end, hash=hash, appendable=is_episode)
    kind = evidence.speaker_kind(text, start) if is_episode else "page"
    if status == evidence.SPAN_STALE:
        return EpisodeFocus(kind=kind, stale=True)  # R-PB2: no offsets to wash
    return EpisodeFocus(start=start, end=end, kind=kind, grown=status == evidence.SPAN_GROWN)


def _derived_focus(memory_path: Path, text: str, entity_ref: str) -> EpisodeFocus | None:
    page = resolve_entity_file(memory_path, entity_ref)
    # `focus` is a free query string and `resolve_entity_file` joins it onto
    # `entities/` as given, so `../<name>` would reach a file the bank never
    # stored as a page. Only a page that lives in `entities/` may name the
    # mention — the `evidence.source_path` rail, applied to the hint too.
    if page is None or page.resolve().parent != (Path(memory_path) / "entities").resolve():
        return None
    try:
        name = str(markdown_parser.parse(page).frontmatter.get("name") or page.stem)
    except Exception:
        name = page.stem
    hit = inbox_context.locate_mention(text, name, page.stem)
    if hit is None:
        return None
    return EpisodeFocus(start=hit[0], end=hit[1], kind="derived", derived=True)


def episode_document(
    memory_path: Path,
    doc_id: str,
    *,
    start: int | None = None,
    end: int | None = None,
    hash: str | None = None,  # noqa: A002 - the field's own name
    focus: str | None = None,
) -> EpisodeText | None:
    """The whole evidence text of ``doc_id`` with its turns, or ``None``.

    ``start``/``end`` (both or neither) ask for an asserted focus, judged by
    ``evidence.span_status`` against ``hash``; ``focus`` names an entity whose
    first mention becomes a derived focus. Raises :class:`SpanOutOfRange` for
    a half or out-of-range pair. Reads one file; writes nothing.
    """
    doc = evidence.source_document(memory_path, doc_id)
    if doc is None:
        return None
    fm, text = doc
    is_episode = evidence.is_episode_id(doc_id)
    length = len(text)
    if (start is None) != (end is None):
        raise SpanOutOfRange("start and end go together")
    if start is not None and not (0 <= start < end <= length):
        raise SpanOutOfRange(f"span [{start}, {end}) is outside the document (length {length})")

    stamps = evidence.turn_stamps(fm) if is_episode else {}
    spans = evidence.turns(text, page=not is_episode, stamps=stamps)
    truncated = length > MAX_TEXT_CHARS
    if truncated:
        spans = [
            replace(t, content_start=min(t.content_start, MAX_TEXT_CHARS), end=min(t.end, MAX_TEXT_CHARS))
            for t in spans if t.start < MAX_TEXT_CHARS
        ]

    focus_model: EpisodeFocus | None = None
    if start is not None:
        focus_model = _asserted_focus(text, start, end, hash, is_episode=is_episode)
    elif focus:
        focus_model = _derived_focus(memory_path, text, focus)

    return EpisodeText(
        episode=doc_id,
        kind="episode" if is_episode else "page",
        text=text[:MAX_TEXT_CHARS],
        length=length,
        hash=evidence.body_hash(text),
        truncated=truncated,
        title=_opt(fm.get("title") if is_episode else fm.get("name")) or doc_id,
        timestamp=_opt(fm.get("timestamp")),
        harness=_opt(fm.get("harness")),
        origin=_opt(fm.get("origin")) or _opt(fm.get("source")),
        conversation_id=_opt(fm.get("session_id")) or _opt(fm.get("source_id")),
        capture_kind=_opt(fm.get("capture_kind")),
        turns=[EpisodeTurn(**asdict(t)) for t in spans],
        focus=focus_model,
    )
```

(d) `api/routers/episodes.py`:
- imports become:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import EpisodeSpan, EpisodeText
from api.services import evidence, provenance, sync_service
```

- append to the module docstring (before its closing `"""`):

```text

``GET /episodes/{id}/text`` (G118 slice 2) returns the WHOLE document with its
turns for the Reader — see ``provenance.episode_document``. It carries an
ETag for the client's in-memory cache only: it is fetched on demand and is
not a Store domain, so there is no ``VersionVector`` mapping (R-PB11).
```

- append the route:

```python
@router.get("/episodes/{episode_id}/text", response_model=EpisodeText)
async def get_episode_text(
    episode_id: str,
    request: Request,
    response: Response,
    start: int | None = Query(None, ge=0),
    end: int | None = Query(None, ge=1),
    hash: str | None = Query(None, max_length=64),  # noqa: A002 - the field's own name
    focus: str | None = Query(None, max_length=200),
    settings: Settings = Depends(get_settings),
):
    """The whole evidence text of one document, with its turns (G118 s2).

    ``start``/``end`` (+ ``hash``) ask for an asserted focus; ``focus=<entity>``
    for a derived one. 404 for an unknown or non-bare id (the ``source_path``
    rail), 422 for a half or out-of-range pair. Engine-free: one parse.
    """
    memory_path = settings.memory_path
    etag = sync_service.etag_for(
        memory_path, "episodes", "entities",
        extra=f"text|{episode_id}|{start}|{end}|{hash or ''}|{focus or ''}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    try:
        doc = await run_in_threadpool(
            provenance.episode_document, memory_path, episode_id,
            start=start, end=end, hash=hash, focus=focus,
        )
    except provenance.SpanOutOfRange as exc:
        raise HTTPException(422, str(exc))
    if doc is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    return doc
```

- [ ] **Step 4: Run — expect PASS:**
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_episode_text_endpoint.py api/tests/test_evidence.py api/tests/test_episode_span_endpoint.py api/tests/test_evidence_grown.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite** → 0 failures.

- [ ] **Step 6: Commit** —
`cd <worktree> && git add api/services/evidence.py api/services/provenance.py api/routers/episodes.py api/models/schemas.py api/tests/test_episode_text_endpoint.py && git commit -m "feat(provenance): GET /episodes/{id}/text — the whole conversation, its turns and times (G118 s2, P2)"`

---

### Task 4: `GET /entities/{id}/provenance` + author identity on the wire (P3)

**Files:**
- Modify: `api/services/git_service.py` (public `author_identity`; `MAX_PROVENANCE_COMMITS`,
  `entity_commit_authors` after `get_entity_history`; history rows at `:493-501`)
- Modify: `api/services/provenance.py` (imports; `MAX_PROVENANCE_CONVERSATIONS`, `_Episodes`,
  helpers, `entity_provenance`)
- Modify: `api/services/transclusion_resolver.py` (import; `_to_model` `:45-67` → `claim_to_model`
  with the author fields; its call sites `:183`, `:206`)
- Modify: `api/routers/claims.py` (imports, docstring, `_claim_to_model` delegates, new route)
- Modify: `api/models/schemas.py` (`EntityHistoryEntry` `:159-181`, `ClaimModel` `:637-668`, new
  provenance models after `EpisodeText`)
- Test: `api/tests/test_entity_provenance.py` (new)

**Interfaces:**
- Produces `transclusion_resolver.claim_to_model(claim) -> ClaimModel` (the one builder),
  `git_service.author_identity(author) -> tuple[str, str | None]`,
  `git_service.MAX_PROVENANCE_COMMITS`, `git_service.entity_commit_authors(memory_path, entity_id, *, limit=None) -> tuple[dict[str, int], bool]`;
  `provenance.MAX_PROVENANCE_CONVERSATIONS`, `provenance.entity_provenance(memory_path, page, *, commit_authors=None, commits_truncated=False) -> EntityProvenance`;
  `GET /entities/{id}/provenance`; wire fields `ClaimModel.{sessionIds, recordedAt, authorKind, authorProvider}`, `EntityHistoryEntry.{authorKind, authorProvider}`.
- Consumes `span_status`, `bank_index.files`, `inbox_context.locate_mention/excerpt_around`,
  `parse_claims`, `Claim.all_session_ids`, `episode_ids.timestamp_sort_key`.

- [ ] **Step 1: Failing tests** — create `api/tests/test_entity_provenance.py`:

```python
"""G118 slice 2 — `GET /entities/{id}/provenance`: who wrote an entity's beliefs,
which conversations fed it, the best quote from each, and how many beliefs
carry an exact quote at all (design §4.5 / §4.8.4). Synthetic fixtures; git
histories are throwaway repos with hand-built trailers.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, demo_bank, evidence, git_service, markdown_parser, provenance
from api.services.claims import Claim, Evidence, EVIDENCE_KINDS, write_claims

SID = "33333333-4444-4555-8666-777777777777"
HOOK = ("user: Should alpha-project move to sqlite-vec?\n"
        "assistant: Yes, bob-example moved alpha-project onto sqlite-vec last week.")
FOLLOW = "user: One more thing about alpha-project."
IMPORT = "user: What does alpha-project index with?\nassistant: It uses sqlite-vec."
LEGACY = "user: Alpha Project needs a new logo."
MEDIA = "## Summary\nSaved.\n\n## Description\nA guide to sqlite-vec for alpha-project."


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _episode(memory: Path, ep_id: str, body: str, **fm) -> None:
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", {"id": ep_id, **fm}, body)


def _span(text: str, quote: str, doc: str, kind: str) -> Evidence:
    s = text.index(quote)
    return Evidence(episode=doc, start=s, end=s + len(quote), kind=kind, hash=evidence.body_hash(text))


def _build(memory: Path) -> Path:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-09-01_001", HOOK, timestamp="2026-09-01T10:00:00+00:00", title="Sync race",
             session_id=SID, harness="claude-code", origin="claude-code", capture_kind="transcript", turns=2)
    _episode(memory, "ep_2026-09-02_001", FOLLOW, timestamp="2026-09-02T10:00:00+00:00", title="Later title",
             session_id=SID, origin="mcp")
    _episode(memory, "ep_2026-08-12_001", IMPORT, timestamp="2026-08-12T09:00:00+00:00", title="Planning notes",
             source_id="conv-import-1", origin="chatgpt-export")
    _episode(memory, "ep_2026-08-01_001", LEGACY, timestamp="2026-08-01T09:00:00+00:00", title="Logo")
    markdown_parser.write(memory / "entities" / "media-example-org.md",
                          {"name": "Example guide", "type": "media", "decay_class": "evergreen"},
                          write_claims(MEDIA, []))
    media_text = evidence.source_text(memory, "media-example-org")
    claims = [
        Claim(id="clm_1", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
              object="sqlite-vec", authored_by="claude-sonnet-4-5", recorded_at="2026-09-01",
              source_episodes=["ep_2026-09-01_001"], session_ids=[SID],
              evidence=[_span(HOOK, "moved alpha-project onto sqlite-vec", "ep_2026-09-01_001", "assistant")]),
        Claim(id="clm_2", text="alpha-project indexes with sqlite-vec", subject="alpha-project",
              authored_by="gpt-5.4-mini", recorded_at="2026-08-12", source_episodes=["ep_2026-08-12_001"],
              evidence=[Evidence(episode="ep_2026-08-12_001", start=46, end=62, kind="assistant",
                                 hash="deadbeefcafe")]),
        Claim(id="clm_3", text="alpha-project needs a logo", subject="alpha-project", authored_by="user",
              recorded_at="2026-08-01", source_episodes=["ep_2026-08-01_001"]),
        Claim(id="clm_4", text="alpha-project is ongoing", subject="alpha-project",
              authored_by="claude-sonnet-4-5", recorded_at="2026-09-02",
              evidence=[Evidence(episode="ep_2026-09-02_001", kind="reasoning", hash=evidence.body_hash(FOLLOW))]),
        Claim(id="clm_5", text="alpha-project used LEANN", subject="alpha-project", authored_by="gpt-5.4-mini",
              recorded_at="2026-07-01", valid_to="2026-09-01", superseded_by="clm_1",
              source_episodes=["ep_2026-08-12_001"]),
        Claim(id="clm_6", text="alpha-project has a sqlite-vec guide", subject="alpha-project",
              authored_by="gpt-5.4-mini", recorded_at="2026-08-20",
              evidence=[_span(media_text, "A guide to sqlite-vec", "media-example-org", "page")]),
    ]
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project", "status": "active",
                                 "source_episodes": ["ep_2026-08-01_001", "ep_2026-09-01_001"]},
                          write_claims("# Alpha Project\n", claims))
    return page


@pytest.fixture
def built(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory)
    bank_index.invalidate()
    return memory, page


# ---------- the payload ----------


def test_counts_cover_the_current_claims_only(built):
    memory, page = built
    result = provenance.entity_provenance(memory, page)
    assert (result.entity_id, result.entity_name, result.entity_type) == ("alpha-project", "Alpha Project", "project")
    t = result.totals
    assert (t.claims, t.with_span, t.legacy, t.conversations) == (5, 3, 1, 3)  # clm_5 is superseded (R-PB6)
    assert result.inferred_count == 1
    assert [(p.entity_id, p.name, p.claim_count) for p in result.pages] == [("media-example-org", "Example guide", 1)]


def test_conversations_group_by_session_then_import_identity(built):
    memory, page = built
    rows = provenance.entity_provenance(memory, page).conversations
    assert [r.conversation_id for r in rows] == [SID, "conv-import-1", None]
    live = rows[0]
    assert live.episode_ids == ["ep_2026-09-01_001", "ep_2026-09-02_001"]
    assert live.episode_id == "ep_2026-09-02_001" and live.timestamp == "2026-09-02T10:00:00+00:00"
    assert (live.title, live.harness, live.origin, live.claim_count) == ("Sync race", "claude-code", "mcp", 2)
    assert rows[1].claim_count == 1 and rows[2].episode_ids == ["ep_2026-08-01_001"]
    assert all(r.available for r in rows)


def test_conversation_order_is_by_instant_not_by_string(tmp_path):
    """G114 R2: a bank holds `+02:00`, `Z` and `+00:00` stamps side by side and
    lexical order across them is wrong, so a conversation's first and newest
    episodes are chosen by instant (`episode_ids.timestamp_sort_key`)."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    # 01:00+02:00 is 23:00Z the day before: EARLIER than 23:30Z, though it sorts later as a string.
    _episode(memory, "ep_2026-09-02_001", "user: alpha-project first.", timestamp="2026-09-02T01:00:00+02:00",
             title="First", session_id=SID)
    _episode(memory, "ep_2026-09-01_001", "user: alpha-project second.", timestamp="2026-09-01T23:30:00+00:00",
             title="Second", session_id=SID)
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project",
                                 "source_episodes": ["ep_2026-09-01_001", "ep_2026-09-02_001"]}, "# A\n")
    bank_index.invalidate()
    [row] = provenance.entity_provenance(memory, page).conversations
    assert row.episode_ids == ["ep_2026-09-02_001", "ep_2026-09-01_001"]
    assert (row.title, row.episode_id, row.timestamp) == ("First", "ep_2026-09-01_001", "2026-09-01T23:30:00+00:00")


def test_the_best_quote_is_asserted_then_derived_then_stale(built):
    memory, page = built
    live, imported, legacy = provenance.entity_provenance(memory, page).conversations
    b = live.best
    assert (b.kind, b.derived, b.stale, b.grown) == ("assistant", False, False, False)
    assert HOOK[b.start:b.end] == "moved alpha-project onto sqlite-vec"
    s, e = b.mention_offsets[0]
    assert b.excerpt[s:e] == "moved alpha-project onto sqlite-vec" and b.excerpt_start + s == b.start
    # clm_2's span is stale; a name match in the same conversation outranks it (R-PB8).
    assert (imported.best.kind, imported.best.derived) == ("derived", True)
    assert IMPORT[imported.best.start:imported.best.end] == "alpha-project"
    assert legacy.best.derived is True and LEGACY[legacy.best.start:legacy.best.end] == "Alpha Project"


def test_a_stale_span_with_no_name_match_shows_words_but_no_wash(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-09-04_001", "user: Nothing relevant is said here.",
             timestamp="2026-09-04T09:00:00+00:00")
    page = memory / "entities" / "zeta-example.md"
    markdown_parser.write(page, {"name": "Zeta Example", "type": "person"}, write_claims("# Zeta\n", [
        Claim(id="clm_z", text="z", subject="zeta-example", source_episodes=["ep_2026-09-04_001"],
              evidence=[Evidence(episode="ep_2026-09-04_001", start=6, end=13, kind="user", hash="deadbeefcafe")])]))
    bank_index.invalidate()
    best = provenance.entity_provenance(memory, page).conversations[0].best
    assert best.stale is True and best.start is None and best.end is None  # R-PB2
    assert best.mention_offsets == [] and best.excerpt


def test_a_conversation_that_continued_keeps_its_exact_quote(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    first = "user: Should alpha-project move to sqlite-vec?"
    _episode(memory, "ep_2026-09-05_001", first, timestamp="2026-09-05T09:00:00+00:00", session_id=SID)
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"}, write_claims("# A\n", [
        Claim(id="clm_g", text="g", subject="alpha-project", source_episodes=["ep_2026-09-05_001"],
              evidence=[_span(first, "move to sqlite-vec", "ep_2026-09-05_001", "user")])]))
    _episode(memory, "ep_2026-09-05_001", first + "\nassistant: Done.",
             timestamp="2026-09-05T09:00:00+00:00", session_id=SID)
    bank_index.invalidate()
    best = provenance.entity_provenance(memory, page).conversations[0].best
    assert (best.grown, best.stale, best.derived, best.kind) == (True, False, False, "user")
    s, e = best.mention_offsets[0]
    assert best.excerpt[s:e] == "move to sqlite-vec"


def test_a_legacy_only_entity_still_says_where_it_came_from(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-08-01_001", LEGACY, timestamp="2026-08-01T09:00:00+00:00")
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project",
                                 "source_episodes": ["ep_2026-08-01_001", "ep_2026-01-01_009"]}, "# Alpha\n")
    bank_index.invalidate()
    result = provenance.entity_provenance(memory, page)
    assert result.totals.claims == 0 and result.totals.conversations == 2
    found = {r.episode_id: r for r in result.conversations}
    assert found["ep_2026-08-01_001"].best.derived is True and found["ep_2026-08-01_001"].claim_count == 0
    gone = found["ep_2026-01-01_009"]
    assert gone.available is False and gone.best is None and gone.title == ""


def test_derived_is_a_read_only_kind():
    assert "derived" not in EVIDENCE_KINDS  # R-PB9: never stored
    assert Evidence.from_dict({"episode": "ep_x", "start": 1, "end": 4, "kind": "derived"}).kind == "reasoning"


def test_fifty_claims_across_twenty_episodes_stay_in_budget(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    bodies: dict[str, str] = {}
    for i in range(20):
        ep = f"ep_2026-08-{i + 1:02d}_001"
        body = f"user: note {i} about alpha-project and sqlite-vec.\nassistant: noted {i}."
        _episode(memory, ep, body, timestamp=f"2026-08-{i + 1:02d}T09:00:00+00:00", title=f"Note {i}",
                 session_id=f"ses_2026-08-{i + 1:02d}_00000000")
        bodies[ep] = body
    claims = []
    for j in range(50):
        ep = f"ep_2026-08-{j % 20 + 1:02d}_001"
        claims.append(Claim(id=f"clm_{j:03d}", text=f"claim {j}", subject="alpha-project",
                            authored_by="claude-sonnet-4-5", recorded_at=f"2026-08-{j % 20 + 1:02d}",
                            source_episodes=[ep], evidence=[_span(bodies[ep], "sqlite-vec", ep, "user")]))
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project", "source_episodes": sorted(bodies)},
                          write_claims("# Alpha Project\n", claims))
    bank_index.invalidate()
    provenance.entity_provenance(memory, page)  # warm bank_index, as a running backend is
    calls: list[str] = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p: (calls.append(Path(p).name), real(p))[1])
    t0 = time.perf_counter()
    result = provenance.entity_provenance(memory, page)
    elapsed = time.perf_counter() - t0
    assert (result.totals.claims, result.totals.with_span, result.totals.conversations) == (50, 50, 20)
    assert len(calls) <= 21, calls  # the page + at most one body read per episode; no frontmatter re-parse
    assert elapsed < 1.0  # smoke bound; the 150 ms design budget is measured by the orchestrator


def test_the_demo_bank_answers_with_an_exact_quote(tmp_path):
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    demo_bank.populate(bank)
    bank_index.invalidate()
    counts, truncated = asyncio.run(git_service.entity_commit_authors(bank, "alpha-project"))
    result = provenance.entity_provenance(bank, bank / "entities" / "alpha-project.md",
                                          commit_authors=counts, commits_truncated=truncated)
    assert result.totals.with_span >= 1
    assert any(c.best is not None and not c.best.derived and not c.best.stale for c in result.conversations)
    assert sum(c.commits for c in result.contributors) >= 1


# ---------- contributors (git) ----------


@pytest.fixture
def repo(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "--", ".")
    _git(memory, "commit", "-q", "-m", git_service.build_commit_message(
        "Sleep cycle 2026-09-01",
        ["entities/alpha-project.md: created (source: ep_2026-09-01_001, trigger: sleep/extraction)"],
        authors=["claude-sonnet-4-5"]))
    with page.open("a", encoding="utf-8") as fh:
        fh.write("\nEdited by hand.\n")
    _git(memory, "commit", "-q", "-am", git_service.build_commit_message(
        "Manual edit", ["entities/alpha-project.md: updated (trigger: user/manual_edit)"], authors=["user"]))
    with page.open("a", encoding="utf-8") as fh:
        fh.write("Legacy line.\n")
    _git(memory, "commit", "-q", "-am", "legacy commit without trailers")
    with (memory / "entities" / "media-example-org.md").open("a", encoding="utf-8") as fh:
        fh.write("\nMore.\n")
    _git(memory, "commit", "-q", "-am", git_service.build_commit_message(
        "Enrich", ["entities/media-example-org.md: updated"], authors=["gpt-5.4-mini"]))
    bank_index.invalidate()
    return memory, page


def test_commit_counts_come_from_the_pages_own_trailers(repo):
    memory, _page = repo
    counts, truncated = asyncio.run(git_service.entity_commit_authors(memory, "alpha-project"))
    assert counts == {"claude-sonnet-4-5": 1, "user": 1, "unknown": 1} and truncated is False
    newest, cut = asyncio.run(git_service.entity_commit_authors(memory, "alpha-project", limit=1))
    assert newest == {"unknown": 1} and cut is True


def test_no_git_means_no_commits_not_an_error(built):
    memory, _page = built
    assert asyncio.run(git_service.entity_commit_authors(memory, "alpha-project")) == ({}, False)


def test_contributors_merge_claim_and_commit_authors(repo):
    memory, page = repo
    counts, truncated = asyncio.run(git_service.entity_commit_authors(memory, "alpha-project"))
    result = provenance.entity_provenance(memory, page, commit_authors=counts, commits_truncated=truncated)
    by = {c.author: c for c in result.contributors}
    assert (by["claude-sonnet-4-5"].claims, by["claude-sonnet-4-5"].commits) == (2, 1)
    assert (by["gpt-5.4-mini"].claims, by["gpt-5.4-mini"].commits) == (2, 0)
    assert (by["user"].claims, by["user"].commits) == (1, 1)
    assert (by["unknown"].claims, by["unknown"].commits) == (0, 1)
    assert (by["claude-sonnet-4-5"].kind, by["claude-sonnet-4-5"].provider) == ("model", "anthropic")
    assert (by["gpt-5.4-mini"].kind, by["gpt-5.4-mini"].provider) == ("model", "openai")
    assert (by["user"].kind, by["user"].provider) == ("user", None)
    assert [c.author for c in result.contributors][:2] == ["claude-sonnet-4-5", "gpt-5.4-mini"]


def test_history_rows_carry_the_same_author_identity(repo):
    memory, _page = repo
    entries = asyncio.run(git_service.get_entity_history("alpha-project", memory))
    kinds = {e.author: (e.author_kind, e.author_provider) for e in entries}
    assert kinds["claude-sonnet-4-5"] == ("model", "anthropic")
    assert kinds["user"] == ("user", None) and kinds["unknown"] == ("unknown", None)


# ---------- the route ----------


@pytest.fixture
def client_bank(tmp_path: Path, monkeypatch):
    memory = tmp_path / "memory"
    _build(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_the_route_serves_camel_case_and_404s_the_unknown(client_bank):
    with TestClient(main.app) as client:
        ok = client.get("/entities/alpha-project/provenance")
        missing = client.get("/entities/no-such-entity/provenance")
    assert ok.status_code == 200, ok.text
    assert missing.status_code == 404
    data = ok.json()
    assert data["entityId"] == "alpha-project" and data["inferredCount"] == 1
    assert data["totals"] == {"claims": 5, "withSpan": 3, "legacy": 1, "conversations": 3}
    assert data["conversations"][0]["claimCount"] == 2
    assert "mentionOffsets" in data["conversations"][0]["best"] and data["commitsTruncated"] is False


def test_the_route_etag_304s_and_moves_with_an_episode(client_bank):
    url = "/entities/alpha-project/provenance"
    path = client_bank / "episodes" / "ep_2026-08-12_001.md"
    with TestClient(main.app) as client:
        etag = client.get(url).headers["etag"]
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 304
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_claims_carry_author_identity_sessions_and_recorded_at(client_bank):
    with TestClient(main.app) as client:
        claims = {c["id"]: c for c in client.get("/entities/alpha-project/claims").json()["claims"]}
    c1 = claims["clm_1"]
    assert (c1["authorKind"], c1["authorProvider"], c1["sessionIds"], c1["recordedAt"]) == (
        "model", "anthropic", [SID], "2026-09-01")
    assert (claims["clm_3"]["authorKind"], claims["clm_3"]["authorProvider"]) == ("user", None)


def test_transcluded_claims_carry_the_same_author_identity(client_bank):
    """`/transclude` builds its claims through the same function as `/claims`
    (R-PB13), so an embedded claim never ships without its author fields."""
    with TestClient(main.app) as client:
        payload = client.get("/transclude", params={"ref": "claim:clm_1"}).json()
    [c] = payload["claims"]
    assert (c["authorKind"], c["authorProvider"], c["sessionIds"], c["recordedAt"]) == (
        "model", "anthropic", [SID], "2026-09-01")
```

- [ ] **Step 2: Run — expect FAIL: 17 failed, 1 passed** (`AttributeError: module 'api.services.provenance' has no attribute 'entity_provenance'`, `git_service … 'entity_commit_authors'`, `KeyError: 'authorKind'`; `test_derived_is_a_read_only_kind` passes already — it is a guard):
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_entity_provenance.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement.**

(a) `api/services/git_service.py` — directly after `_provider_for_model` (after `:353`):

```python
def author_identity(author: str | None) -> tuple[str, str | None]:
    """``(kind, provider)`` for an author id — the ONE rule the contributors
    strip, the claim chip, the history row and the provenance section read
    (G15 / R-L6; G118 slice 2 R-PB6). Public so no caller re-derives it; an
    empty author is the legacy ``unknown`` bucket."""
    name = (author or "").strip() or UNKNOWN_AUTHOR
    return _classify_author_kind(name), _provider_for_model(name)
```

In `get_entity_history`, replace the `entries.append(EntityHistoryEntry(` call (`:493-501`) with:

```python
        author_kind, author_provider = author_identity(author)
        entries.append(EntityHistoryEntry(
            date=date,
            change_type=change_type,
            description=description,
            author=author,
            author_kind=author_kind,
            author_provider=author_provider,
            commit_hash=commit_hash,
            diff=diff,
            sessions=sessions,
        ))
```

Directly after `get_entity_history` (before `def _infer_change_type`):

```python
# G118 slice 2 (R-PB6): enough history for "N changes by <author>" on the
# entity card. A page touched by more commits than this says so
# (`commitsTruncated`) instead of walking the whole history per card open.
MAX_PROVENANCE_COMMITS = 500


async def entity_commit_authors(
    memory_path: Path, entity_id: str, *, limit: int | None = None,
) -> tuple[dict[str, int], bool]:
    """Commits that touched ``entities/<entity_id>.md``, counted per
    ``Cicada-Author`` (an untrailered commit is ``unknown``), and whether the
    walk was cut at ``limit``.

    ONE ``git log`` over the path with git's own trailer directive: every
    commit that ever changed the page (not only blame survivors — a decay pass
    that was later overwritten still contributed), and never ``%b``, because a
    Sleep commit's body is a manifest of every entity it touched (the M1
    lesson). ``entity_id`` is a resolved page stem; ``--`` keeps it a path.
    ``({}, False)`` on a non-git bank or a git failure — provenance never
    blocks on history.
    """
    limit = MAX_PROVENANCE_COMMITS if limit is None else max(1, int(limit))
    if not (Path(memory_path) / ".git").exists():
        return {}, False
    try:
        out = await _run_git(
            memory_path, "log", f"-n{limit + 1}",
            f"--format=%x1e%(trailers:key={AUTHOR_TRAILER},valueonly,separator=%x1f)",
            "--", f"entities/{entity_id}.md",
        )
    except GitError:
        return {}, False
    records = out.split("\x1e")[1:]
    counts: dict[str, int] = {}
    for record in records[:limit]:
        authors = [a.strip() for a in record.strip("\n").split("\x1f") if a.strip()] or [UNKNOWN_AUTHOR]
        for author in dict.fromkeys(authors):
            counts[author] = counts.get(author, 0) + 1
    return counts, len(records) > limit
```

(b) `api/models/schemas.py`:
- `EntityHistoryEntry` — after `author: str = "unknown"` add:

```python
    # G118 slice 2 (R-PB13): the author's bucket and provider, from the one
    # `git_service.author_identity` rule, so the History tab renders a
    # contributor without re-deriving it. Additive; an older app ignores them.
    author_kind: str = "unknown"
    author_provider: Optional[str] = None
```

- `ClaimModel` — after `evidence: list[EvidenceModel] = []` add:

```python
    # G118 slice 2 (R-PB13) — additive. `session_ids` is every conversation
    # that wrote or reinforced the claim (`Claim.all_session_ids`);
    # `author_kind`/`author_provider` come from `git_service.author_identity`
    # over `authored_by`, so the chip never duplicates the provider rule.
    session_ids: list[str] = []
    recorded_at: Optional[str] = None
    author_kind: str = "unknown"
    author_provider: Optional[str] = None
```

- after `EpisodeText`:

```python
class ProvenanceSpan(CamelModel):
    """The one quote a provenance row shows (G118 slice 2, design §4.5).
    ``kind`` is the evidence kind (``user`` | ``assistant`` | ``page``) or
    ``derived`` — a name match found at read, never written (R-PB9).
    ``start``/``end`` are absolute offsets to wash, ``None`` when ``stale``
    (R-PB2). ``excerpt`` is ±240 chars cut on word boundaries,
    ``excerpt_start`` its absolute offset, ``mention_offsets`` relative to it
    — the inbox cause's shape (G115)."""

    episode: str
    start: Optional[int] = None
    end: Optional[int] = None
    hash: str = ""
    kind: str = "derived"
    excerpt: str = ""
    excerpt_start: int = 0
    mention_offsets: list[list[int]] = []
    stale: bool = False
    grown: bool = False
    derived: bool = False


class ProvenanceContributor(CamelModel):
    """One author of an entity (R-PB6): ``claims`` = current claims with that
    ``authored_by``; ``commits`` = commits that touched the page with that
    ``Cicada-Author``. ``kind``/``provider`` as on ``Contributor``."""

    author: str
    kind: str = "unknown"
    provider: Optional[str] = None
    claims: int = 0
    commits: int = 0


class ProvenanceConversation(CamelModel):
    """A conversation that fed the entity (R-PB7): episodes grouped by
    ``session_id``, then ``source_id``, else the episode alone
    (``conversation_id`` null). ``episode_id`` is its newest episode;
    ``claim_count`` counts current claims citing any of its episodes;
    ``available`` is false when no episode file is left in the bank."""

    conversation_id: Optional[str] = None
    episode_id: str
    episode_ids: list[str] = []
    title: str = ""
    harness: Optional[str] = None
    origin: Optional[str] = None
    timestamp: Optional[str] = None
    claim_count: int = 0
    available: bool = True
    best: Optional[ProvenanceSpan] = None


class ProvenancePage(CamelModel):
    entity_id: str
    name: str = ""
    claim_count: int = 0


class ProvenanceTotals(CamelModel):
    """Coverage stated honestly (design §4.5 item 5): of ``claims`` current
    beliefs, ``with_span`` carry at least one exact quote and ``legacy`` carry
    no evidence at all (written before slice 1; there is no backfill)."""

    claims: int = 0
    with_span: int = 0
    legacy: int = 0
    conversations: int = 0


class EntityProvenance(CamelModel):
    """``GET /entities/{id}/provenance`` — "Where this came from" in one call
    (G118 slice 2, design §4.8.4). ``conversations`` is capped at 50
    (``totals.conversations`` is the honest total); ``inferred_count`` counts
    current claims whose only evidence is the contributor's own reasoning.
    Fetched on demand, not a Store domain (R-PB11)."""

    entity_id: str
    entity_name: str = ""
    entity_type: str = ""
    contributors: list[ProvenanceContributor] = []
    conversations: list[ProvenanceConversation] = []
    pages: list[ProvenancePage] = []
    inferred_count: int = 0
    totals: ProvenanceTotals = Field(default_factory=ProvenanceTotals)
    commits_truncated: bool = False
```

(c) `api/services/provenance.py` — the imports become:

```python
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from api.models.schemas import (
    EntityProvenance,
    EpisodeFocus,
    EpisodeText,
    EpisodeTurn,
    ProvenanceContributor,
    ProvenanceConversation,
    ProvenancePage,
    ProvenanceSpan,
    ProvenanceTotals,
)
from api.services import bank_index, episode_ids, evidence, git_service, inbox_context, markdown_parser
from api.services.claims import Claim, Evidence, parse_claims
from api.services.id_utils import resolve_entity_file
```

and append:

```python
# How many conversation rows one provenance payload carries (R-PB7). The card
# shows five and "+N more"; `totals.conversations` is the honest total, and
# `best` is computed only for the rows that ship, so body reads stay bounded
# by what is shown.
MAX_PROVENANCE_CONVERSATIONS = 50


class _Episodes:
    """Episode frontmatter from ``bank_index`` (one scandir, cached parses)
    and bodies read lazily, at most once each — the G97 budget rule, so an
    entity citing twenty conversations costs twenty body reads, not a bank
    scan (``test_fifty_claims_across_twenty_episodes_stay_in_budget``)."""

    def __init__(self, memory_path: Path):
        self._memory_path = memory_path
        self._index: dict[str, bank_index.IndexedFile] | None = None
        self._bodies: dict[str, str | None] = {}

    def meta(self, ep_id: str) -> bank_index.IndexedFile | None:
        if self._index is None:
            self._index = {f.stem: f for f in bank_index.files(self._memory_path, "episodes")}
        return self._index.get(ep_id)

    def body(self, ep_id: str) -> str | None:
        if ep_id not in self._bodies:
            indexed = self.meta(ep_id)
            try:
                self._bodies[ep_id] = indexed.body() if indexed is not None else None
            except Exception:
                self._bodies[ep_id] = None
        return self._bodies[ep_id]


def _current(claim: Claim) -> bool:
    return claim.valid_to is None and not claim.superseded_by


def _recency(claim: Claim) -> str:
    return str(claim.recorded_at or claim.valid_from or "")


def _span_model(text: str, episode: str, start: int, end: int, *, hash: str, kind: str,  # noqa: A002
                grown: bool = False, derived: bool = False) -> ProvenanceSpan:
    ex = inbox_context.excerpt_around(text, (start, end))
    return ProvenanceSpan(episode=episode, start=start, end=end, hash=hash, kind=kind,
                          excerpt=ex.excerpt, excerpt_start=ex.start or 0,
                          mention_offsets=ex.mention_offsets, grown=grown, derived=derived)


def _stale_model(text: str, ev: Evidence) -> ProvenanceSpan:
    """A stale span still shows its neighbourhood — "the words may have
    moved" (§4.2) — but carries no offsets to wash (R-PB2)."""
    anchor = (ev.start, min(ev.end, len(text))) if 0 <= ev.start < len(text) else None
    ex = inbox_context.excerpt_around(text, anchor)
    return ProvenanceSpan(episode=ev.episode, hash=ev.hash, kind=ev.kind, excerpt=ex.excerpt,
                          excerpt_start=ex.start or 0, stale=True)


def _best_span(docs: _Episodes, episode_ids: list[str],
               spans_by_episode: dict[str, list[tuple[Claim, Evidence]]],
               name: str, entity_id: str) -> ProvenanceSpan | None:
    """R-PB8: an asserted span that still holds (newest claim first) → a
    derived name match in the newest readable episode → a stale span → none."""
    candidates = [pair for ep in episode_ids for pair in spans_by_episode.get(ep, [])]
    candidates.sort(key=lambda pair: _recency(pair[0]), reverse=True)
    stale: tuple[str, Evidence] | None = None
    for _claim, ev in candidates:
        text = docs.body(ev.episode)
        if text is None:
            continue
        status = evidence.span_status(text, end=ev.end, hash=ev.hash)
        if status == evidence.SPAN_STALE or ev.end > len(text):
            stale = stale or (text, ev)
            continue
        return _span_model(text, ev.episode, ev.start, ev.end, hash=ev.hash, kind=ev.kind,
                           grown=status == evidence.SPAN_GROWN)
    for ep in reversed(episode_ids):
        text = docs.body(ep)
        if not text:
            continue
        hit = inbox_context.locate_mention(text, name, entity_id)
        if hit is not None:
            return _span_model(text, ep, hit[0], hit[1], hash=evidence.body_hash(text),
                               kind="derived", derived=True)
    if stale is not None:
        return _stale_model(*stale)
    return None


def entity_provenance(
    memory_path: Path,
    page: Path,
    *,
    commit_authors: dict[str, int] | None = None,
    commits_truncated: bool = False,
) -> EntityProvenance:
    """Where ``page``'s current beliefs came from and who wrote them (R-PB6…8).

    One page parse, cached episode frontmatter, at most one body read per
    shown conversation; ``commit_authors`` is the router's single
    ``git_service.entity_commit_authors`` call (kept outside so this stays a
    pure, thread-pool-safe function). Writes nothing.
    """
    memory_path = Path(memory_path)
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter or {}
    entity_id = page.stem
    name = str(fm.get("name") or entity_id)
    current = [c for c in parse_claims(parsed.body) if _current(c)]
    commit_authors = commit_authors or {}
    docs = _Episodes(memory_path)

    claim_authors = Counter((c.authored_by or git_service.UNKNOWN_AUTHOR) for c in current)
    contributors: list[ProvenanceContributor] = []
    for author in set(claim_authors) | set(commit_authors):
        kind, provider = git_service.author_identity(author)
        contributors.append(ProvenanceContributor(
            author=author, kind=kind, provider=provider,
            claims=claim_authors.get(author, 0), commits=commit_authors.get(author, 0),
        ))
    contributors.sort(key=lambda c: (-(c.claims + c.commits), c.author))

    cited: dict[str, set[str]] = {}
    spans_by_episode: dict[str, list[tuple[Claim, Evidence]]] = {}
    page_claims: dict[str, set[str]] = {}
    with_span = inferred = legacy = 0
    for claim in current:
        episodes = {e for e in claim.source_episodes if evidence.is_episode_id(e)}
        for ev in claim.evidence:
            if not evidence.is_episode_id(ev.episode):
                if ev.is_span():
                    page_claims.setdefault(ev.episode, set()).add(claim.id)
                continue
            episodes.add(ev.episode)
            if ev.is_span():
                spans_by_episode.setdefault(ev.episode, []).append((claim, ev))
        cited[claim.id] = episodes
        if any(ev.is_span() for ev in claim.evidence):
            with_span += 1
        elif claim.evidence:
            inferred += 1
        else:
            legacy += 1

    fed_by = [str(e) for e in (fm.get("source_episodes") or []) if evidence.is_episode_id(str(e))]
    ordered = list(dict.fromkeys(fed_by + sorted({e for eps in cited.values() for e in eps})))

    groups: dict[str, dict] = {}
    for ep_id in ordered:
        indexed = docs.meta(ep_id)
        efm = indexed.frontmatter if indexed is not None else {}
        conversation_id = _opt(efm.get("session_id")) or _opt(efm.get("source_id"))
        group = groups.setdefault(conversation_id or ep_id, {"id": conversation_id, "episodes": []})
        group["episodes"].append((str(efm.get("timestamp") or ""), ep_id, efm, indexed is not None))

    rows: list[ProvenanceConversation] = []
    for group in groups.values():
        # By instant, never by string (G114 R2): a bank holds naive, `Z` and
        # `+00:00` stamps side by side, and lexical order across them is wrong.
        group["episodes"].sort(key=lambda e: (episode_ids.timestamp_sort_key(e[0]), e[1]))
        ep_ids = [e[1] for e in group["episodes"]]
        first, last = group["episodes"][0], group["episodes"][-1]
        members = set(ep_ids)
        rows.append(ProvenanceConversation(
            conversation_id=group["id"],
            episode_id=last[1],
            episode_ids=ep_ids,
            title=str(first[2].get("title") or ""),
            harness=next((_opt(e[2].get("harness")) for e in group["episodes"] if _opt(e[2].get("harness"))), None),
            origin=_opt(last[2].get("origin")) or _opt(last[2].get("source")),
            timestamp=last[0] or None,
            claim_count=sum(1 for eps in cited.values() if eps & members),
            available=any(e[3] for e in group["episodes"]),
        ))
    rows.sort(key=lambda r: (r.claim_count, episode_ids.timestamp_sort_key(r.timestamp)), reverse=True)
    shown = rows[:MAX_PROVENANCE_CONVERSATIONS]
    for row in shown:
        row.best = _best_span(docs, row.episode_ids, spans_by_episode, name, entity_id)

    pages: list[ProvenancePage] = []
    for doc_id, claim_ids in sorted(page_claims.items()):
        pdoc = evidence.source_document(memory_path, doc_id)
        pname = str((pdoc[0] if pdoc else {}).get("name") or doc_id)
        pages.append(ProvenancePage(entity_id=doc_id, name=pname, claim_count=len(claim_ids)))

    return EntityProvenance(
        entity_id=entity_id,
        entity_name=name,
        entity_type=str(fm.get("type") or ""),
        contributors=contributors,
        conversations=shown,
        pages=pages,
        inferred_count=inferred,
        totals=ProvenanceTotals(claims=len(current), with_span=with_span, legacy=legacy,
                                conversations=len(rows)),
        commits_truncated=commits_truncated,
    )
```

(d) `api/services/transclusion_resolver.py` — the one `ClaimModel` builder (R-PB13). Its import
line `from api.services import markdown_parser` becomes
`from api.services import git_service, markdown_parser` (no cycle: `git_service` imports only
`api.models.schemas`). Replace `_to_model` (`:45-67`) with:

```python
def claim_to_model(claim: Claim) -> ClaimModel:
    """The ONE ``Claim`` → ``ClaimModel`` builder. ``routers/claims._claim_to_model``
    delegates here, so ``/entities/{id}/claims``, ``/timeline`` and
    ``/transclude`` can never ship two shapes of one claim — G118 slice 2
    (R-PB13) found the two copies drifting the moment author fields were added
    to only one. ``author_kind``/``author_provider`` come from
    ``git_service.author_identity``, the rule the contributors strip reads."""
    author = claim.authored_by or "unknown"
    author_kind, author_provider = git_service.author_identity(author)
    return ClaimModel(
        id=claim.id,
        text=claim.text,
        subject=claim.subject,
        predicate=claim.predicate,
        object=claim.object,
        object_kind=claim.object_kind,
        observer=claim.observer,
        context=claim.context,
        epistemic=claim.epistemic,
        source_trust=claim.source_trust,
        confidence=claim.confidence,
        valid_from=claim.valid_from or "",
        valid_to=claim.valid_to,
        superseded_by=claim.superseded_by,
        supersedes=claim.supersedes,
        source_episodes=claim.source_episodes,
        premises=claim.premises,
        authored_by=author,
        origin=claim.origin,
        evidence=[EvidenceModel(**e.to_dict()) for e in (claim.evidence or [])],
        # G118 slice 2 (R-PB13) — additive.
        session_ids=claim.all_session_ids(),
        recorded_at=claim.recorded_at,
        author_kind=author_kind,
        author_provider=author_provider,
    )
```

and rename its two call sites: `claims=[_to_model(claim)],` (`:183`) → `claims=[claim_to_model(claim)],`
and `claims=[_to_model(c) for c in facet_claims],` (`:206`) → `claims=[claim_to_model(c) for c in facet_claims],`.
`grep -n "_to_model" api/services/transclusion_resolver.py` must then print only `claim_to_model` lines
(no test references the old name).

(e) `api/routers/claims.py`:
- imports become (`EvidenceModel` is no longer used here):

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    ClaimListResponse,
    ClaimModel,
    ClaimTimeline,
    EntityProvenance,
    TransclusionPayload,
)
from api.services import git_service, markdown_parser, provenance, sync_service, transclusion_resolver
from api.services.claims import Claim, parse_claims
from api.services.id_utils import resolve_entity_file
```

- `_claim_to_model` (`:39-61`) becomes:

```python
def _claim_to_model(c: Claim) -> ClaimModel:
    """Every claim on the wire goes through ``transclusion_resolver.claim_to_model``
    (G118 slice 2, R-PB13): one builder, so this router and ``/transclude``
    never disagree about a claim's author identity, sessions or evidence."""
    return transclusion_resolver.claim_to_model(c)
```

- in the module docstring, `All three are read-only projections` becomes `All four are read-only
  projections`, and add a bullet after the `/transclude` bullet:

```text
- ``GET /entities/{id}/provenance`` → ``EntityProvenance`` (G118 slice 2) —
  contributors, the conversations that fed the page, the best quote from
  each, and honest coverage; built by ``provenance.entity_provenance``.
```

- append the route directly after `get_entity_timeline` (before `def _timeline_sort_key`):

```python
@router.get("/entities/{entity_id}/provenance", response_model=EntityProvenance)
async def get_entity_provenance(
    entity_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Where an entity's beliefs came from and who wrote them (G118 s2, §4.8.4).

    One call for the card's "Where this came from" instead of N+2 (claims,
    history, one ``/conversations/{id}`` per session). Engine-free: one page
    parse, cached episode frontmatter, at most one body read per shown
    conversation, and ONE trailer-only ``git log`` of the page. Fetched on
    demand — not a Store domain — so the ETag serves the client's in-memory
    cache only and there is no ``VersionVector`` mapping (R-PB11); ``git_head``
    is in the recipe because the commit counts come from git, and a commit that
    lands after the file write would otherwise 304 a stale count.
    """
    memory_path = settings.memory_path
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    etag = sync_service.etag_for(
        memory_path, "entities", "episodes", "git_head", extra=f"provenance|{page.stem}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    commits, truncated = await git_service.entity_commit_authors(memory_path, page.stem)
    return await run_in_threadpool(
        provenance.entity_provenance, memory_path, page,
        commit_authors=commits, commits_truncated=truncated,
    )
```

- [ ] **Step 4: Run — expect PASS:**
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_entity_provenance.py api/tests/test_claim_endpoints.py api/tests/test_session_provenance_views.py api/tests/test_episode_text_endpoint.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite** → 0 failures.

- [ ] **Step 6: Commit** —
`cd <worktree> && git add api/services/git_service.py api/services/provenance.py api/services/transclusion_resolver.py api/routers/claims.py api/models/schemas.py api/tests/test_entity_provenance.py && git commit -m "feat(provenance): GET /entities/{id}/provenance + author identity on claims and history (G118 s2, P3)"`

---

### Task 5: `GET /episodes/{id}/citations` + `/ask` evidence (P4, P5)

**Files:**
- Modify: `api/services/provenance.py` (imports; `MAX_CITATION_PAGES`, `_candidate_pages`,
  `episode_citations`)
- Modify: `api/routers/episodes.py` (schema import; new route)
- Modify: `api/models/schemas.py` (`AskCitation` `:818-823`; new citation models after
  `EntityProvenance`)
- Modify: `api/services/ask_service.py` (import; `_claim_evidence`; `_citations_for` `:521-544`)
- Test: `api/tests/test_episode_citations.py`, `api/tests/test_ask_evidence.py` (new)

**Interfaces:**
- Produces `provenance.MAX_CITATION_PAGES`, `provenance.episode_citations(memory_path, doc_id) -> EpisodeCitations | None`;
  `GET /episodes/{id}/citations` → `EpisodeCitations`; `ask_service._claim_evidence(body, claim_id) -> list[dict]`;
  wire `AskCitation.{claimId, evidence}`.
- Consumes `evidence.source_document`, `span_status`, `inbox_context.locate_mention`,
  `parse_claims`, `EvidenceModel`.

- [ ] **Step 1: Failing tests.**

`api/tests/test_episode_citations.py`:

```python
"""G118 slice 2 — `GET /episodes/{id}/citations`: what a conversation taught Cicada.

The reverse direction (G106 (ii), design §4.8.3): every claim whose evidence
points into the document, every legacy claim that lists it in
`source_episodes` (a derived, labelled name match), and every page that lists
it in frontmatter. Built from the pages' own claims blocks after a raw-text
prefilter (R-PB10) — no index dependency. Synthetic fixtures.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, markdown_parser, provenance
from api.services.claims import Claim, Evidence, write_claims

EP = "ep_2026-09-01_001"
BODY = (
    "user: I moved alpha-project onto sqlite-vec last week.\n"
    "assistant: Noted — sqlite-vec replaces LEANN for alpha-project.\n"
    "user: bob-example reviewed it."
)


def _span(quote: str, kind: str, *, hash: str | None = None) -> Evidence:  # noqa: A002
    s = BODY.index(quote)
    return Evidence(episode=EP, start=s, end=s + len(quote), kind=kind, hash=hash or evidence.body_hash(BODY))


def _page(memory: Path, stem: str, name: str, claims: list[Claim], *, episodes=(), etype: str = "project") -> None:
    markdown_parser.write(memory / "entities" / f"{stem}.md",
                          {"name": name, "type": etype, "status": "active", "source_episodes": list(episodes)},
                          write_claims(f"# {name}\n", claims))


def _build(memory: Path) -> None:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {"id": EP, "title": "Index talk"}, BODY)
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md", {"id": "ep_2026-09-02_001"},
                          "user: gamma-project uses Tool Example C.")
    _page(memory, "alpha-project", "Alpha Project", [
        Claim(id="clm_a1", text="sqlite-vec replaced LEANN", subject="alpha-project",
              authored_by="claude-sonnet-4-5", source_episodes=[EP],
              evidence=[_span("sqlite-vec replaces LEANN", "assistant")]),
        Claim(id="clm_a2", text="alpha-project is active", subject="alpha-project",
              authored_by="gpt-5.4-mini", source_episodes=[EP]),
        Claim(id="clm_a3", text="alpha-project moved to sqlite-vec", subject="alpha-project", authored_by="user",
              valid_to="2026-09-02", superseded_by="clm_a1", source_episodes=[EP],
              evidence=[_span("moved alpha-project onto sqlite-vec", "user")]),
    ], episodes=[EP])
    _page(memory, "bob-example", "Bob Example", [
        Claim(id="clm_b1", text="bob-example reviewed the migration", subject="bob-example",
              evidence=[_span("bob-example reviewed it", "user", hash="deadbeefcafe")]),
        Claim(id="clm_b2", text="bob-example cares about the index", subject="bob-example",
              evidence=[Evidence(episode=EP, kind="reasoning", hash=evidence.body_hash(BODY))]),
    ], etype="person")
    _page(memory, "beta-project", "Beta Project", [], episodes=[EP])
    _page(memory, "gamma-project", "Gamma Project", [
        Claim(id="clm_g1", text="gamma-project uses Tool Example C", subject="gamma-project",
              source_episodes=["ep_2026-09-02_001"])], episodes=["ep_2026-09-02_001"])
    for i in range(40):
        _page(memory, f"filler-{i:02d}", f"Filler {i}", [])


@pytest.fixture
def built(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    _build(memory)
    bank_index.invalidate()
    return memory


def test_citations_list_spans_derived_reasoning_and_pages(built):
    result = provenance.episode_citations(built, EP)
    rows = result.citations
    assert [r.claim_id for r in rows] == ["clm_a3", "clm_a2", "clm_a1", "clm_b1", "clm_b2"]
    a3, a2, a1, b1, b2 = rows
    assert a1.kind == "assistant" and BODY[a1.start:a1.end] == "sqlite-vec replaces LEANN"
    assert a1.evidence.hash == evidence.body_hash(BODY) and (a1.stale, a1.grown, a1.derived) == (False, False, False)
    assert (a1.subject_id, a1.subject_name, a1.subject_type, a1.authored_by) == (
        "alpha-project", "Alpha Project", "project", "claude-sonnet-4-5")
    assert a3.current is False and a1.current is True
    assert (a2.kind, a2.derived, a2.evidence) == ("derived", True, None)
    assert BODY[a2.start:a2.end] == "alpha-project"
    assert b1.stale is True and b1.start is None and b1.end is None and b1.evidence.start >= 0  # R-PB2
    assert b2.kind == "reasoning" and b2.start is None and b2.evidence.kind == "reasoning"
    assert [(e.entity_id, e.name, e.type) for e in result.entities] == [
        ("alpha-project", "Alpha Project", "project"), ("beta-project", "Beta Project", "project")]
    assert result.partial is False


def test_a_conversation_that_continued_still_highlights(built):
    path = built / "episodes" / f"{EP}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body + "\nassistant: Glad it landed.")
    rows = {r.claim_id: r for r in provenance.episode_citations(built, EP).citations}
    assert rows["clm_a1"].grown is True and rows["clm_a1"].start is not None


def test_only_pages_that_name_the_episode_are_parsed(built, monkeypatch):
    calls: list[str] = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p: (calls.append(Path(p).name), real(p))[1])
    provenance.episode_citations(built, EP)
    assert sorted(calls) == sorted([f"{EP}.md", "alpha-project.md", "beta-project.md", "bob-example.md"])


def test_the_page_cap_says_partial(built, monkeypatch):
    monkeypatch.setattr(provenance, "MAX_CITATION_PAGES", 1)
    result = provenance.episode_citations(built, EP)
    assert result.partial is True
    assert {r.subject_id for r in result.citations} == {"alpha-project"}


def test_an_unknown_document_is_none(built):
    assert provenance.episode_citations(built, "ep_2026-01-01_999") is None
    assert provenance.episode_citations(built, "../episodes/" + EP) is None


@pytest.fixture
def client_bank(tmp_path: Path, monkeypatch):
    memory = tmp_path / "memory"
    _build(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_the_route_serves_camel_case_404s_and_etags(client_bank):
    url = f"/episodes/{EP}/citations"
    path = client_bank / "episodes" / f"{EP}.md"
    with TestClient(main.app) as client:
        ok = client.get(url)
        assert ok.status_code == 200, ok.text
        data = ok.json()
        assert data["episode"] == EP and data["partial"] is False
        assert {"claimId", "subjectId", "subjectName", "evidence", "stale", "derived"} <= set(data["citations"][0])
        assert client.get("/episodes/ep_2026-01-01_999/citations").status_code == 404
        etag = ok.headers["etag"]
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 304
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 200
```

`api/tests/test_ask_evidence.py`:

```python
"""G118 slice 2 / G93's output half — `/ask` citations carry their spans.

A claim-first hit already knew its `claim_id`; the router dropped it and no
span ever reached the wire. The spans are read from the page `_load_entity`
already holds (R-PB12), never from the claims index. The LLM is injected;
nothing here reaches a model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import AskCitation
from api.services import ask_service, evidence, markdown_parser
from api.services.claims import Claim, Evidence, write_claims

EP = "ep_2026-09-01_001"
BODY = "user: I moved alpha-project onto sqlite-vec last week."
QUOTE = "moved alpha-project onto sqlite-vec"


def _bank(memory: Path) -> Evidence:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {"id": EP}, BODY)
    s = BODY.index(QUOTE)
    ev = Evidence(episode=EP, start=s, end=s + len(QUOTE), kind="user", hash=evidence.body_hash(BODY))
    claim = Claim(id="clm_1", text="alpha-project uses sqlite-vec", subject="alpha-project",
                  source_episodes=[EP], evidence=[ev])
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "source_episodes": [EP]},
                          write_claims("# Alpha Project\nA project.", [claim]))
    return ev


def _llm(prompt: str) -> str:
    return json.dumps({"answer": "It uses sqlite-vec.", "confidence": 0.8,
                       "used_entities": ["alpha-project"], "gaps": []})


def test_a_claim_first_citation_carries_its_claim_id_and_spans(tmp_path):
    ev = _bank(tmp_path)
    hit = {"score": 0.9, "text": "alpha-project uses sqlite-vec",
           "metadata": {"entity_id": "alpha-project", "entity_name": "Alpha Project",
                        "claim_id": "clm_1", "observer": "agent"}}
    result = ask_service.answer_query(tmp_path, "what index", retrieve_fn=lambda q, k: [hit], llm_fn=_llm)
    [c] = result["citations"]
    assert c["claim_id"] == "clm_1" and c["evidence"] == [ev.to_dict()]
    assert c["source_episodes"] == [EP]
    assert AskCitation(**c).evidence[0].start == ev.start


def test_an_entity_only_citation_has_no_claim_and_no_spans(tmp_path):
    _bank(tmp_path)
    hit = {"score": 0.9, "text": "", "metadata": {"entity_id": "alpha-project", "entity_name": "Alpha Project"}}
    result = ask_service.answer_query(tmp_path, "what index", retrieve_fn=lambda q, k: [hit], llm_fn=_llm)
    [c] = result["citations"]
    assert "claim_id" not in c and "evidence" not in c
    wire = AskCitation(**c)
    assert wire.claim_id is None and wire.evidence == []


@pytest.fixture
def client_bank(tmp_path: Path, monkeypatch):
    memory = tmp_path / "memory"
    ev = _bank(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    yield ev
    config.get_settings.cache_clear()


def test_the_wire_carries_claim_id_and_evidence(client_bank, monkeypatch):
    ev = client_bank
    monkeypatch.setattr(ask_service, "answer_query", lambda memory_path, query, top_k=6: {
        "answer": "It uses sqlite-vec.", "confidence": 0.8, "gaps": [], "used_entities": ["alpha-project"],
        "citations": [{"entity_id": "alpha-project", "entity_name": "Alpha Project", "file_path": "",
                       "snippet": "", "source_episodes": [EP], "claim_id": "clm_1",
                       "evidence": [ev.to_dict()], "claim_provenance": {"claim_id": "clm_1"}}],
    })
    with TestClient(main.app) as client:
        r = client.post("/ask", json={"query": "what index"})
    assert r.status_code == 200, r.text
    c = r.json()["citations"][0]
    assert c["claimId"] == "clm_1" and c["evidence"][0]["start"] == ev.start
    assert c["sourceEpisodes"] == [EP] and "claimProvenance" not in c
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: … 'episode_citations'`, `KeyError: 'claim_id'`, `KeyError: 'claimId'`):
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_episode_citations.py api/tests/test_ask_evidence.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement.**

(a) `api/models/schemas.py`:
- `AskCitation` becomes:

```python
class AskCitation(CamelModel):
    entity_id: str
    entity_name: str
    file_path: str
    snippet: str
    source_episodes: list[str] = []
    # G118 slice 2 (R-PB12) — set when the retrieval hit was a claim: the
    # claim and the spans behind it, read from the page (the source of truth),
    # raw as stored; freshness is `/episodes/{id}/span`'s job. Additive.
    claim_id: Optional[str] = None
    evidence: list[EvidenceModel] = []
```

- after `EntityProvenance`:

```python
class EpisodeCitation(CamelModel):
    """One belief a document contributed (G118 slice 2, design §4.8.3).
    ``evidence`` is the stored entry for a span or reasoning row, ``None`` for
    a derived one. ``start``/``end`` are what to wash — the asserted offsets,
    a derived name match, or ``None`` (reasoning, no match, or ``stale``:
    R-PB2). ``current`` is false for a superseded or closed claim."""

    claim_id: str
    subject_id: str
    subject_name: str = ""
    subject_type: str = ""
    text: str = ""
    current: bool = True
    authored_by: str = "unknown"
    observer: str = "agent"
    evidence: Optional[EvidenceModel] = None
    kind: str = "reasoning"
    start: Optional[int] = None
    end: Optional[int] = None
    stale: bool = False
    grown: bool = False
    derived: bool = False


class EpisodeCitationEntity(CamelModel):
    entity_id: str
    name: str = ""
    type: str = ""


class EpisodeCitations(CamelModel):
    """``GET /episodes/{id}/citations`` — spans first in document order (the
    Reader's navigator steps through them), then rows without offsets.
    ``entities`` are the pages whose frontmatter ``source_episodes`` lists the
    document. ``partial`` is true when more pages named it than one call
    parses (R-PB10). Fetched on demand, not a Store domain."""

    episode: str
    citations: list[EpisodeCitation] = []
    entities: list[EpisodeCitationEntity] = []
    partial: bool = False
```

(b) `api/services/provenance.py` — add `import os` to the stdlib imports, and extend the schema
import to also include `EpisodeCitation`, `EpisodeCitationEntity`, `EpisodeCitations`,
`EvidenceModel` (alphabetical inside the parenthesised list). Append:

```python
# The most entity pages one citations call parses (R-PB10). A page is parsed
# only when its raw text names the document, so this bounds the pathological
# case — a conversation cited by hundreds of pages — and `partial` says so.
MAX_CITATION_PAGES = 200


def _candidate_pages(memory_path: Path, doc_id: str) -> tuple[list[Path], bool]:
    """Entity pages whose raw text contains ``doc_id``, in filename order,
    capped. A substring test before any YAML parse: a page can only cite a
    document whose id is written in it (a claim's ``evidence`` or
    ``source_episodes``, or the frontmatter's), and an ``ep_YYYY-MM-DD_nnn``
    id is distinctive, so a false positive costs one parse and a miss is
    impossible. This is the "cold" path the design names (§4.8.3): the pages'
    own claims blocks — not the vector claims index, whose metadata carries no
    evidence (``vector_index.index_claims``), and not Track S's FTS table,
    which this track does not depend on."""
    entities_dir = Path(memory_path) / "entities"
    try:
        with os.scandir(entities_dir) as it:
            names = sorted(e.name for e in it if e.is_file() and e.name.endswith(".md"))
    except FileNotFoundError:
        return [], False
    out: list[Path] = []
    for fname in names:
        path = entities_dir / fname
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if doc_id not in raw:
            continue
        if len(out) >= MAX_CITATION_PAGES:
            return out, True
        out.append(path)
    return out, False


def episode_citations(memory_path: Path, doc_id: str) -> EpisodeCitations | None:
    """Every belief ``doc_id`` contributed (G106 (ii) at claim precision), or
    ``None`` for an unknown / non-bare id. Engine-free; writes nothing.

    Per claim: one row per span into the document (freshness from
    ``span_status``; stale rows carry no offsets, R-PB2); else one
    ``reasoning`` row when the contributor inferred it from here; else — a
    legacy claim that only lists the document in ``source_episodes`` — one
    ``derived`` row located by the subject's name (R-PB9), with offsets only
    when the name is found.
    """
    doc = evidence.source_document(memory_path, doc_id)
    if doc is None:
        return None
    _fm, text = doc
    is_episode = evidence.is_episode_id(doc_id)
    pages, partial = _candidate_pages(memory_path, doc_id)
    rows: list[EpisodeCitation] = []
    entities: list[EpisodeCitationEntity] = []
    for path in pages:
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        pfm = parsed.frontmatter or {}
        subject_id = path.stem
        subject_name = str(pfm.get("name") or subject_id)
        subject_type = str(pfm.get("type") or "")
        if doc_id in [str(e) for e in (pfm.get("source_episodes") or [])]:
            entities.append(EpisodeCitationEntity(entity_id=subject_id, name=subject_name, type=subject_type))
        for claim in parse_claims(parsed.body):
            base = {
                "claim_id": claim.id, "subject_id": subject_id, "subject_name": subject_name,
                "subject_type": subject_type, "text": claim.text, "current": _current(claim),
                "authored_by": claim.authored_by or git_service.UNKNOWN_AUTHOR, "observer": claim.observer,
            }
            mine = [ev for ev in claim.evidence if ev.episode == doc_id]
            spans = [ev for ev in mine if ev.is_span()]
            for ev in spans:
                status = evidence.span_status(text, end=ev.end, hash=ev.hash, appendable=is_episode)
                stale = status == evidence.SPAN_STALE or ev.end > len(text)
                rows.append(EpisodeCitation(
                    **base, evidence=EvidenceModel(**ev.to_dict()), kind=ev.kind,
                    start=None if stale else ev.start, end=None if stale else ev.end,
                    stale=stale, grown=not stale and status == evidence.SPAN_GROWN,
                ))
            if spans:
                continue
            if mine:
                rows.append(EpisodeCitation(**base, evidence=EvidenceModel(**mine[0].to_dict()), kind="reasoning"))
            elif doc_id in claim.source_episodes:
                hit = inbox_context.locate_mention(text, subject_name, subject_id)
                rows.append(EpisodeCitation(**base, kind="derived", derived=True,
                                            start=hit[0] if hit else None, end=hit[1] if hit else None))
    rows.sort(key=lambda r: (r.start is None, r.start if r.start is not None else 0, r.subject_name, r.claim_id))
    return EpisodeCitations(episode=doc_id, citations=rows, entities=entities, partial=partial)
```

(c) `api/routers/episodes.py` — the schema import becomes
`from api.models.schemas import EpisodeCitations, EpisodeSpan, EpisodeText`; append to the module
docstring `` ``GET /episodes/{id}/citations`` lists every belief the document contributed — see
``provenance.episode_citations`` (same ETag rule). `` and append the route:

```python
@router.get("/episodes/{episode_id}/citations", response_model=EpisodeCitations)
async def get_episode_citations(
    episode_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """What this conversation taught Cicada (G118 s2, §4.8.3; G106 (ii)).

    Spans in document order, then rows without offsets; ``partial`` when more
    pages named the document than one call parses. Engine-free, nothing
    written. 404 for an unknown or non-bare id.
    """
    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "episodes", "entities", extra=f"citations|{episode_id}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    result = await run_in_threadpool(provenance.episode_citations, memory_path, episode_id)
    if result is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    return result
```

(d) `api/services/ask_service.py` — add `from api.services.claims import parse_claims` beside the
existing `from api.services import json_parse, markdown_parser`; add above `_citations_for`:

```python
def _claim_evidence(body: str, claim_id: str) -> list[dict]:
    """G118 slice 2 (R-PB12): the spans behind a claim-first citation, read
    from the page itself — the source of truth — not from the claims index,
    whose metadata carries no evidence and is only as fresh as its last
    rebuild. ``body`` is the one ``_load_entity`` already read, so this is a
    ``parse_claims`` and no I/O. ``[]`` when the claim is gone or legacy."""
    for claim in parse_claims(body or ""):
        if claim.id == claim_id:
            return [e.to_dict() for e in claim.evidence]
    return []
```

and in `_citations_for` replace

```python
        prov = ent.get("claim_provenance")
        if prov:
            citation["claim_provenance"] = prov
```

with

```python
        prov = ent.get("claim_provenance")
        if prov:
            citation["claim_provenance"] = prov
            claim_id = str(prov.get("claim_id") or "").strip()
            if claim_id:
                citation["claim_id"] = claim_id
                citation["evidence"] = _claim_evidence(ent.get("body", ""), claim_id)
```

- [ ] **Step 4: Run — expect PASS:**
`cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_episode_citations.py api/tests/test_ask_evidence.py api/tests/test_ask_service.py api/tests/test_ask_claim_retrieval.py api/tests/test_episode_text_endpoint.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite** → 0 failures.

- [ ] **Step 6: Commit** —
`cd <worktree> && git add api/services/provenance.py api/routers/episodes.py api/models/schemas.py api/services/ask_service.py api/tests/test_episode_citations.py api/tests/test_ask_evidence.py && git commit -m "feat(provenance): GET /episodes/{id}/citations and /ask evidence (G118 s2, P4/P5)"`

---

### Task 6: Docs — where the next reader will look

**Files:**
- Modify: `docs/goals/memory-evolution.md` (rows `G118` `:680`, `G103` `:665`, `G106` `:668`,
  `G115` `:677`)
- Modify: `CLAUDE.md` (the *Claims, evidence and provenance* section, after `:282`)
- Modify: `docs/goals/TODO.md` (the 🔄 In progress table `:335-340`; "Pick up here" `:158-159`)

Before each edit, confirm the anchor is unique:
`cd <worktree> && grep -c "<anchor>" <file>` must print `1`. Placeholders only — no bank contents,
no names, no counts read from a bank (the privacy rule).

- [ ] **Step 1: G118.** Replace the row's tail

```text
**Open:** slice 2 viewer (entity → claim → chip → raw pane, Swift `Evidence` model), slice 3 trigger traces, slice 4 rationale, G100's derived-span class, `describes` claims on link enrichment (a whole-section span — trivial once the viewer wants it). | 🛠️ slice 1 ✅ (PR #44); slices 2–4 open |
```

with

```text
**Slice 2, server half, built 2026-09-23 (`feat/provenance-viewer`, plan `docs/superpowers/plans/2026-09-23-provenance-backend.md`):** one freshness rule, `evidence.span_status` → `current | grown | stale` — design amendment A7: a turn-boundary prefix of an appended episode that still hashes to the stored value is `grown`, exact, and highlights (the Stop hook and G20 both rewrite by appending; pages never grow) — used by `/span` (+`grown`), the inbox cause and every new payload, and a stale span travels without wash offsets; `GET /episodes/{id}/text` (the whole evidence text ≤ 400,000 chars, `turns[]` from the one marker parser `speaker_kind` reads, per-turn `ts` only from a stored sidecar, an asserted `start/end/hash` or derived `focus=<entity>`); `GET /entities/{id}/provenance` (contributors = claim `authored_by` + one trailer-only `git log` of the page, conversations grouped by `session_id`/`source_id`, best quote asserted → derived → stale, coverage over current claims stated honestly); `GET /episodes/{id}/citations` (raw-text prefilter over `entities/`, spans + derived + reasoning rows, capped with `partial`); `/ask` citations carry `claimId` + `evidence`; `ClaimModel`/`EntityHistoryEntry` gain `authorKind`/`authorProvider` (+ `sessionIds`, `recordedAt`). The chat importer keeps each message's time as `turns: [{offset, ts, speaker}]` outside `content_hash`, capped at 500 because frontmatter is parsed on every cold scan (costs measured in the plan). G100's derived-span class exists on read payloads only — never in `EVIDENCE_KINDS`, never written. None of the payloads is a Store domain (ETags for the client's in-memory cache only; no `VersionVector` mapping). **Open:** the Swift viewer (P1–P6 client, after Meadow M1), per-turn times for Stop-hook episodes (their `turns` key is a count today), slice 3 trigger traces, slice 4 rationale, `describes` claims on link enrichment. | 🛠️ slice 1 ✅ (PR #44); slice 2 server ✅; viewer + slices 3–4 open |
```

- [ ] **Step 2: G103, G106, G115 — one sentence each**, inserted immediately before each row's
final ` | 🔲 |`:
  - G103 (anchor `side by side with who said each. | 🔲 |`): ` **G118 slice 2 (server) makes "who wrote this" legible:** \`GET /entities/{id}/provenance\` returns per-author claim and commit counts with \`kind\`/\`provider\` from one \`git_service.author_identity\`, and \`ClaimModel\` carries \`authorKind\`/\`authorProvider\`, so the card and the chip render a contributor without re-deriving it; per-claim observer labels and "who was in the room" stay this row's.`
  - G106 (anchor `opens a list instead of a place. | 🔲 |`): ` **G118 slice 2 (server) ships (ii) and the anchor route:** \`GET /episodes/{id}/citations\` is the inverse index at claim precision (spans, derived name matches for legacy claims, and the pages that list the episode), and \`GET /episodes/{id}/text\` is the conversation-with-anchor route (whole text, turns, an asserted or derived focus); (i)'s content search and the page itself remain (Track S, the Swift viewer).`
  - G115 (anchor `Phases 2–3 unchanged. | 🔲 |`): ` **G118 slice 2 (server):** the cause's asserted span now survives a continued conversation (\`grown\` — \`_asserted_span\` reads \`evidence.span_status\`), and "Show in conversation" needs no new field: the Reader opens \`GET /episodes/{id}/text?start=&end=\` at the cause window's absolute offset plus the mention offset.`

- [ ] **Step 3: CLAUDE.md.** Insert after the line
`claims carry no \`evidence\` and \`to_dict\` omits the empty key; there is no backfill.` (a blank line
before and after), keeping the section's ~100-column wrap:

~~~markdown
**Reading provenance back (G118 slice 2, server half).** Three engine-free, bank-only reads, all
built in `api/services/provenance.py` and fetched on demand — none is a Store domain, so each ETag
serves the client's in-memory cache and there is no `VersionVector` mapping: `GET
/episodes/{id}/text` (the whole evidence text, capped at 400,000 chars, with `turns[]` from the
same marker lines `speaker_kind` reads and an asserted `start/end/hash` or derived
`focus=<entity>`), `GET /entities/{id}/provenance` (contributors from claim `authored_by` plus one
trailer-only `git log` of the page — ETag includes `git_head` — conversations grouped by
`session_id`/`source_id`, the best quote per conversation, coverage over current claims), and `GET
/episodes/{id}/citations` (every claim citing the document, by a raw-text prefilter over
`entities/` — no index dependency). `/ask` citations also carry `claimId` + `evidence`, read from
the cited page rather than the index. Every claim on the wire is built by one function,
`transclusion_resolver.claim_to_model`, and carries `authorKind`/`authorProvider` from
`git_service.author_identity`. **Freshness is one rule, `evidence.span_status`:** `current`,
`grown` (an episode that was appended to after the span was minted — the Stop hook and G20 both
rewrite that way — and a turn-boundary prefix still hashes to the stored value, so the offsets are
exact) or `stale`. A stale span travels without
wash offsets; a `derived` span (found by name, `inbox_context.locate_mention`) exists on read
payloads only — never in `EVIDENCE_KINDS`, never written. The chat importer keeps each message's
time as `turns: [{offset, ts, speaker}]` in frontmatter, outside `content_hash`; the Stop hook's
`turns:` is still a count, and a reader treats any non-list as no times.
~~~

- [ ] **Step 4: TODO.md.**
  - In the 🔄 In progress table, insert a row directly under `|---|---|---|` (above the `G129` row):
    `| **G118 slice 2 — server half** | Built on \`feat/provenance-viewer\` (plan \`2026-09-23-provenance-backend.md\`): \`grown\` spans, \`/episodes/{id}/text\`, \`/entities/{id}/provenance\`, \`/episodes/{id}/citations\`, \`/ask\` evidence, per-turn import times. | Merge after the orchestrator's re-run; then the Swift viewer track (P1–P6 client) once Meadow M1 lands. |`
  - In "Pick up here" (`:158-159`), replace `(the provenance viewer — its server half has shipped
and nothing renders it)` with `(the provenance viewer — slice 1's spans and slice 2's read routes
are server-side; nothing renders them yet)`. The old phrase **spans the line break** after
`shipped` in the file, so match it across the newline (an exact single-line match finds nothing),
then re-wrap the paragraph at ~100 columns.

- [ ] **Step 5: Commit** —
`cd <worktree> && git add docs/goals/memory-evolution.md docs/goals/TODO.md CLAUDE.md && git commit -m "docs: G118 slice 2 server half — the read routes, grown spans and the turns sidecar (G103/G106/G115 cross-refs)"`

---

## Not in scope

Named so a reviewer does not read an absence as an oversight.

- **Swift** — `Evidence`, `EvidenceChip`, the Reader, "Where this came from", `ScalarSlice`, every
  P1–P6 client piece. A later track, after Meadow M1 merges.
- **FTS** (Track S, spec decision 7). `/citations` does not import it; it may back the same shape
  later (R-PB10).
- **MCP changes** and **any LLM**. `_render_ask` reads named keys only; nothing here spends.
- **Per-turn times for Stop-hook episodes.** `transcript_extract` knows each turn's time, but the
  hook's `turns` key is a count; switching its type is a coordinated follow-up with the capture
  path, recorded in G118.
- **Backfilling `turns` onto already-imported episodes** — a SKIP never rewrites a file (R-PB4).
- **`markdown_parser` on libyaml's `CSafeLoader`** (~7× faster in the measurement above) — a
  global parser change with its own risk, not a provenance change.
- **The `harness` author kind for remote writes** (Track R, R-R5), and **the `mcp-agentic-write`
  pseudo-author on MCP-written claims** (Track R, R-R6 — a write-side fix); `author_identity`
  inherits whatever those change and reports stored values as they are.
- **Stored `speaker`/`media` evidence kinds** (Tracks N / O); `EVIDENCE_KINDS` is untouched here.
- **Slices 3 (trigger traces) and 4 (rationale)** of G118.
- **`resumable` or `project_dir` on `/text`** — `GET /conversations/{id}` stays the one `isfile()` site.
- **The `/conversations/upload` origin-stamping defect** (R7 §1.2 #1) — the imports track.
- **Changes to the demo bank** — it is read by one smoke test, not edited.

---

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0
   failures** (≥ 2225 passed + this track's tests). If
   `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
   the only red, re-run it alone and report both results.
2. The new files alone, green:
   `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_evidence_grown.py api/tests/test_import_turn_stamps.py api/tests/test_episode_text_endpoint.py api/tests/test_entity_provenance.py api/tests/test_episode_citations.py api/tests/test_ask_evidence.py -q -p no:cacheprovider`.
3. Rails, each must print nothing:
   `cd <worktree> && git diff --stat dev...HEAD -- app mcp api/services/claims.py api/services/transcript_capture.py api/services/transcript_extract.py api/services/session_stats.py`
   and `cd <worktree> && grep -nE "^(from|import) .*(litellm|agent_engine|vector_index|session_stats|transcript_)" api/services/provenance.py`
   (import lines only: the module's comments deliberately name `transcript_extract.SESSION_CAP_CHARS`
   and `vector_index.index_claims` to explain what it does NOT use)
   and `cd <worktree> && ls api/services/episode_staging.py 2>/dev/null`.
4. Budget on the demo bank (scratch only, never committed) — report the warm number in the PR; the
   design budget is **< 150 ms**:

   ```bash
   cd <worktree> && api/.venv/bin/python - <<'EOF'
   import asyncio, tempfile, time
   from pathlib import Path
   from api.services import bank_index, bank_registry, demo_bank, git_service, provenance
   bank = Path(tempfile.mkdtemp()) / "demo"
   bank_registry.scaffold_bank(bank); demo_bank.populate(bank); bank_index.invalidate()
   page = bank / "entities" / "alpha-project.md"
   provenance.entity_provenance(bank, page)  # warm bank_index
   t = time.perf_counter()
   counts, cut = asyncio.run(git_service.entity_commit_authors(bank, "alpha-project"))
   r = provenance.entity_provenance(bank, page, commit_authors=counts, commits_truncated=cut)
   print(f"{(time.perf_counter() - t) * 1000:.1f} ms", r.totals)
   EOF
   ```

5. A lint that has never failed is not known to work: temporarily add `import litellm` to
   `api/services/provenance.py`, run
   `api/.venv/bin/python -m pytest api/tests/test_episode_text_endpoint.py::test_the_provenance_module_is_engine_free -q -p no:cacheprovider`
   → must FAIL; revert and confirm green.
6. **Live bank (orchestrator only, numbers only, never content into docs):** after the branch is
   running, `GET /entities/<id>/provenance` for three entities and report `totals` — this is the
   design's unverified "live-bank share of claims with evidence".
7. **PR body must state:** no Store domain and no `VersionVector` change (`git diff dev...HEAD -- app/`
   empty); the four ETag recipes (R-PB11); the A7 amendment and that `/span` gained `grown`; the
   `turns` sidecar key/shape and its measured parse cost; that `derived` is never written; and
   that no price, token count or `/consumption/*` read is involved.
