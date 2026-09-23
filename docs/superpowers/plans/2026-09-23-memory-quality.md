# Memory quality from the Instinct comparison, and the video watch record (Track Q) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take what is worth taking from the Instinct memory article and make the video chain honest.
MCP recall finds a page by its aliases and by each query word, reaches a person through the claims
about them, and shows what changed recently as dated lines. `cicada_get_perspective` can list a
subject's earlier claims. Three new tools: `cicada_timeline(since)` reports what changed, read from
git on demand. `cicada_retract_claim` lets an agent withdraw a claim it wrote, keeping the reason.
`cicada_record_watch` records what an agent saw in a saved video as timestamped `media` spans. A
claim may state its end (`expected_end`, or a `due` date), and Sleep's engine-free tail closes it
the day after. The primer splits into *Standing* (the person, their timezone, how to work with
them, what lasts) and *Current* (what is in motion), using the decay classes the bank already
carries. `cicada_save_url` keeps a note given for an already-saved link and names the episode to
cite. Vimeo and Loom descriptions are kept, with chapters parsed from them.

**Architecture:** Every addition is **engine-free and derived at read time or written through an
existing seam**. Recall adopts `search_service`'s two MCP-shaped legs (the G136 hand-off) through
two seams: the existing `_keyword_search_entities`, which a test already patches, and a new
`_claim_subject_search`, which the hermetic recall tests learn to stub. The timeline is one bounded `git log` parsed by
`git_service.parse_cycle_body`, and it stores nothing. A retraction and an expiry both close
claims the way Stage 3 does (`valid_to`, plus `superseded_by` for a retraction), and nothing is
deleted. The watch record writes one episode and then one claim through `agentic_write.write_claim`,
so there is one reconcile path. The `media` evidence kind comes from a turn marker, the same way
`user` and `assistant` do. The primer's new rows are ids and one-liners already on pages. Four new
pure modules: `change_timeline`, `claim_expiry`, `video_chapters` and `watch_record`. No LLM call
is added anywhere.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), the stdio MCP server (`mcp/server.py`), the
remote connector (`api/remote/`), markdown + git bank. **No Swift in this track.**

**Sources (binding):**
- The round-3 spec: `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`.
  Decision 8 covers the watch record and the `media` kind. The Track-Q row is "standing/current
  primer, timeline tool, dated facts close, retract with provenance".
- The search plan's **Hand-off 1**: `docs/superpowers/plans/2026-09-23-search-backend.md`, "Hand-off".
- The remote-connector plan: tool bodies in `api/services/mcp_tools.py` behind `ToolContext`, and
  the `remote` handshake variant.
- Two research reports: R3 (the Instinct article, idea mapping §3, proposals P1–P11 §4) and R5
  (video defects §2, metadata §5.6, the watch record §5.7, file guidance §5.9). **They live in a
  session scratchpad and are not committed.** Every fact this plan uses from them is restated
  inline in *What the code actually does today*, and that section is the citable source.

**Backlog rows:** new **G140**; edits to **G22**, **G53**, **G75**, **G118**, **G136**.

**Standing rulings that bind here:**
- TODO ruling 3: a `.db` is fine only if it is derived and disposable. This track adds none.
- TODO ruling 4: plan quota. It is untouched, because nothing here calls an engine.
- The ETag ship-together rule: **no ETag is added or changed**.
- G75 R12: a primer or skill must not name an argument the schema rejects.
- Privacy in docs.
- Portability: no owner name, no author-machine path.
- The Track V rail: Cicada never derives a stream and never downloads a video.

---

## What the code actually does today (verified against `feat/memory-quality` @ `0354538`)

**Recall** (`api/services/mcp_tools.py`):
- `recall` is at `:416-534`. `:445-447` fuses exactly two legs: `_leann_search_entities`
  (vector) and `_keyword_search_entities`.
- `_keyword_search_entities` (`:1010-1038`) is a **whole-query substring** match on name, tags,
  related and body. It **never reads `aliases`**, even though Stage 1 extracts and merges them
  (R3 §2). So "project alpha" misses a page named "Alpha Project", and "takeout" misses a page
  whose alias is `takeout`.
- `_rrf_fuse` (`:396-413`) is a local copy. `search_service.rrf_fuse` (`api/services/search_service.py:93-104`)
  is the same formula and is pinned to it by `api/tests/test_search_service.py:108-115`.
- **Claims are never a recall leg.** Only `ask_service.py:344` queries claims, through the vector
  index.
- `search_service.lexical_entity_hits` (`:763-771`) and `claim_subject_hits` (`:774-779`) return
  exactly the `{"entity_id", "source", "score"}` shape `_rrf_fuse` reads. The search plan's
  Hand-off 1 assigns their adoption to "Track R". **It did not happen**: the remote plan moved the
  bodies verbatim, so it lands here.
- `search()` never resolves a bank (`:726-728`: "MCP will pass its own resolved path").
- On a bank with no index file, `ensure_fresh` returns `building`, spawns a **daemon** builder
  (`search_index.py:656-664`), and the legs answer from the `bank_index` frontmatter fallback.
  Recall never blocks.
- Tests depend on `_keyword_search_entities` in three ways, which is why its name and signature
  `(entities_dir, query, top_k)` are kept:
  - `test_mcp_recall_episode_fallback.py:26` **patches** it;
  - `test_entity_read_events.py:109-121` stubs every other leg and relies on the **real** keyword
    leg to find `alpha-project` (its comment at `:115-117` names the function);
  - the golden run (`test_mcp_stdio_golden.py`) calls it unpatched.
- `search_service`'s own docstrings still describe the hand-off as pending: the module docstring
  (`:6`), `rrf_fuse` ("a port … not an import", `:93-104`) and `lexical_entity_hits` ("Adoption is
  Track R's", `:763-771`). They go stale the moment Task 1 lands.
- `search_service.search()` answers a bank with no FTS file from `_search_fallback`
  (`:676-712`): names, aliases and tags from `bank_index`, with every query token required
  (word-start prefix), never a body read, and **no claims**. So on a cold bank the claim leg is
  empty and a body-only match is missed until the background build finishes; the indexed path
  reads prose too.

**History is hidden:**
- `get_perspective` (`mcp_tools.py:905-965`) filters to `valid_to is None and not superseded_by`
  (`:934-938`) and has no way to show earlier claims.
- `vector_index.search_claims(include_superseded=…)` (`vector_index.py:638-681`) is dead:
  - `index_claims` skips every claim with `valid_to` (`:600-601`).
  - `claim_reconciler._close` always stamps both `valid_to` and `superseded_by` (`claim_reconciler.py:138-141`).
  - So the flag can only surface a claim with a `superseded_by` marker and `valid_to: None`, which
    no writer produces. `test_claims.py:404-437` builds exactly that impossible claim to test it.
  - No production caller passes the flag: `ask_service.py:344` uses the default.
- `GET /entities/{id}/claims?include_superseded=` (`api/routers/claims.py:66-76`) is a different,
  working path.

**The primer:**
- `handshake._now_block` (`handshake.py:220-263`) prints:
  - the bank line and the owner **id** only (`:241-242`);
  - projects, people ids and conversations;
  - "Standing preferences", which are the top-5 `skill` pages ranked
    `confidence / (1 + days/30)` (`state_dictionary.py:137-145, :377-378`).
- The recency term means a standing preference **falls out of the list when nobody mentions it
  for a month**.
- Nothing in the primer uses `decay_class` (G66), even though `decay_policy.resolve(fm)`
  (`decay_policy.py:103-120`) gives every page one.
- The builder reads the owner **only** from the env override `settings.observer_owner`
  (`state_dictionary.py:389-391`). It never reads G117's `owner_identity.resolve_observer`
  (`owner_identity.py:62-83`), so a bank onboarded through the app has no `owner_id` in `_state.md`.
- The primer has no timezone.
- Skill pages are written with `tags: []` (`inbox_generator.py:257-274`), so a tag-only "how to
  work with me" row would be empty on every real bank.
- Budget and caching:
  - `MAX_TOKENS = 1800` by chars/4 (`:47`).
  - `_fit` (`:270-281`) drops people, then preferences, then conversations, then project one-liners.
  - The cache key is `f"{CONTRACT_VERSION}:{variant}:{stamp}"` (`:357`), plus the remote key (`:352`).
- **R12 is not enforced for arguments in the local primer**:
  - The contract says `cicada_recall_detail(id)` (`:177`). That tool's only property is `entity_id`
    (`mcp/server.py:188-190`).
  - The remote contract repeats it (`handshake.py:87`).
  - `test_remote_tools.py:54-63` checks tool *names* only.

**Claims and closure:**
- `Claim.valid_to` means "`None` = currently valid; a date = closed" (`claims.py:133`). **13
  modules** read it that way (the `grep -l "valid_to is None\|.valid_to"` list in
  `api/services` + `api/routers`).
- No field holds a *stated* end.
- G17 `due` claims come from Stage 1 with the date literal as their object
  (`entity_extractor.py:113-116`).
- `claim_reconciler.is_human` (`:77-86`) means `user_stated` **and** a manual or clarification
  origin. No agent claim may close such a claim (`:11-19`).
- `_reinforce` (`:144-179`) merges episodes, sessions and spans.
- `Claim.to_dict` omits an empty `evidence` (`claims.py:187-193`) so that re-rendering a page
  never diffs legacy claims (G118 R7).
- Every stdio MCP claim written before G135 carries `authored_by: mcp-agentic-write`: `_stamp_new`
  (`claim_reconciler.py:120-135`) reads `_ReconcileSettings.litellm_model` (`agentic_write.py:95-103`).

**Tools, scopes, R12:**
- The stdio `TOOLS` list is at `mcp/server.py:167-480`. `handle_tool` is at `:627-685`.
- The remote schemas are at `api/remote/tools.py:41-136`, `TOOL_SCOPE` at
  `api/remote/catalog.py:29-42`, `WRITE_TOOLS` at `:44`, `READ_TOOLS` at `:45-46`, and `_DISPATCH`
  at `api/remote/runtime.py:170-188`.
- `test_remote_tools.py:40-45` requires every stdio tool to sit in exactly one of `TOOL_SCOPE` or
  `NEVER_REMOTE`, and `REMOTE_TOOLS == TOOL_SCOPE`.
- `:54-63` proves, for all 63 scope sets, that nothing a connection is told names a tool it lacks.
- `:66-75` requires `destructive_hint: false` on every tool, and `read_only_hint` false exactly for
  `WRITE_TOOLS ∪ {resolve_inbox}`.
- `test_mcp_tools_context.py:21-33` fails the build if `mcp_tools.py`'s **source text** contains
  `resolve_repo_context`, `mark_episodes_processed`, `list_unprocessed_episodes`, `import mcp` or
  `from mcp`.

**The video chain (R5 §2, four defects, all re-verified):**
1. `ingest_one` returns `duplicate` before reading `item.note` (`media_ingestor.py:1749-1765`). The
   router answers "Already saved" (`api/routers/sources.py:129-133`). **A note given for a video
   saved earlier is silently dropped.** That is G22's primary case: save now, watch later.
2. `save_url`'s replies name the entity, never the episode (`mcp_tools.py:286-289, :336-341`). The
   router already returns `episode_id` (`SourceSaveResponse`, `schemas.py:1759-1766`), and
   `cicada_write_claim.evidence` needs an episode id.
3. `evidence.speaker_kind` returns `user` for any line with no marker (`evidence.py:178-200`). A
   transcript quote saved with `cicada_save_episode` is therefore **recorded as the person's own
   words**. `_episode_body` writes an agent's `note` under `## User note` (`media_ingestor.py:1514-1515`),
   so an agent's summary also reads as `user`. `claims.py:52-58` anticipates a fifth kind, and
   `Evidence.from_dict` degrades an unknown kind to `reasoning` (`:94-109`).
4. `skills/cicada-librarian/SKILL.md:69` tells agents `external:<name>`, but the stdio observer
   schema is an `enum` of `owner|agent|external|<legacy>` (`mcp/server.py:346`).
   `test_agentic_write.py:361-364` pins the legacy value's presence in that enum.

**Video metadata:**
- `_enrich_oembed` (`media_ingestor.py:325-369`) sets `description=""` at `:362`, even though Vimeo
  and Loom oEmbed return one (R5 §5.6, probed).
- `_episode_body` (`:1510-1511`) and `_entity_body` (`:1522-1523`) already render
  `meta.description` under `## Description`. Keeping the field is enough; neither body builder
  changes for it.
- `link_enrichment` already writes a `describes` claim (`_build_describes_claim`, `:95-113`, origin
  `sleep/link_enrichment`, a `page` span), and its backfill **skips any media page that already
  has a `describes` claim** (`link_enrichment.py:699`).
- `_media_entity_id` (`:1609-1622`) slugs the title alone. Two different URLs whose enrichment
  returns the same title get the **same** page id, and the second save overwrites the first page.
  Test fakes must return distinct titles per URL.
- YouTube's oEmbed has no description. `_enrich_youtube` stays untouched (its R12 note, `:275-279`).
- `write_media_entity` writes `provider` and `duration_s` only when set (`:1683-1693`).
- `EntityMedia` is at `schemas.py:403-432`, and `_build_media_block` at `api/routers/entities.py:163-204`.

**The Sleep tail:**
- `_run_engine_independent_tail` (`sleep_cycle.py:695-767`) runs `_refresh_state_safely` first and
  unconditionally.
- It then runs the connector poll, the feed poll and the link backfill **only** when
  `outcome.committed or not write_started or tree clean` (`:745-753`). This is the H1 guard: those
  writers' `git add -A` would otherwise sweep a half-written cycle.
- The G85 decay commit is `Sleep cycle <date> (decay)` with `Cicada-Author: cicada` (`:1719-1735`).
- `get_sleep_history` greps `^Sleep cycle` and `^Inbox resolution` (`git_service.py:1084`),
  and its rows are consolidations.

**Commit manifests:**
- Every writer puts `<path>: <action> (source: …, trigger: …)` lines above its trailers.
- `git_service.parse_cycle_body` (`:984-1025`) reads any such body into entities, actions,
  authors, sessions and engine.
- Decay lines carry `archive`, `decay_nudge` or `decay` as their action
  (`conflict_resolver.py:206, :216, :226`).
- `_MANIFEST_LINE_RE` (`git_service.py:968`) takes any `\w+` action, so `retracted` and `expired`
  parse with no change there.
- Agent writes are `Agent write <date>` / `Remote write <date>` (`agent_commits.py:52-55`,
  `mcp_tools.ToolContext.commit_subject`).

**Evidence and turns:**
- `_TURN_RE` (`evidence.py:68`) is `^(user|human|assistant|ai|system|unknown)\s*:`. Only this module
  reads it. `_marker_lines` (`:203-222`) returns 3-tuples, which only `turn_starts` and `turns`
  (`:256-284`) unpack.
- `provenance.py:153` builds `EpisodeTurn(**asdict(t))` from every `TurnSpan`. A field added to
  `TurnSpan` must therefore be added to `EpisodeTurn` in the same commit, or `GET
  /episodes/{id}/text` raises.
- `EvidenceModel.kind` is a plain `str` (`schemas.py:638`), and `transclusion_resolver.claim_to_model`
  builds `ClaimModel` field by field. A new evidence kind or a new `Claim` field therefore never
  breaks the wire.
- No Swift file decodes an evidence kind on this base.

**The remote copy that must not move:** `_remote_capabilities`' sentence "Can't delete or rewrite."
(`handshake.py:118`) is the same string as the app's `RemoteScope.summary`
(`RemoteConnector.swift:100-102`). It is pinned on both sides: `test_handshake_remote.py:48` and
`RemoteConnectorTests.swift:37-50`. This track has no Swift, so that sentence stays.

**Baseline on this base:** `api/tests` collects **2714** (measured 2026-09-23, about 2 minutes).
In the critic's run, 2713 passed and
`test_search_latency.py::test_prefix_mode_stays_within_budget_with_a_staleness_scan_on_every_request`
failed on its timing budget. Re-run alone, that file passed (3 passed). It is load-sensitive, since
other worktrees run suites at the same time. The brief's 2225 predates the round-3 merges.

---

## Global Constraints

- **Where to work:**
  - Work ONLY in `<worktree>` = `.worktrees/q` (branch `feat/memory-quality`, based on `dev` @ `0354538`).
  - Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path. zoxide hijacks a
    relative `cd`; ignore its stderr warning.
  - Never an unquoted `--include=*.ext`, because zsh globs it.
- **What never to read:** NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library` or
  `~/.claude/projects`. Fixtures are synthetic: `alpha-project`, `bob-example`, `example.com`,
  `vimeo.com/123456789`.
- **Test commands:**
  - Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`.
  - The full `api/tests` run must report **0 failures** (2714 collected on this base).
  - Two known flakes. If one of them is the ONLY red, re-run it alone and report both results:
    - `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
      is order-dependent.
    - `test_search_latency.py::test_prefix_mode_stays_within_budget_with_a_staleness_scan_on_every_request`
      is a wall-clock budget. It failed once in a loaded full run and passed alone (see Baseline).
    - Anything else red is this track's.
- **Git discipline:**
  - Never `git add -A`; stage named files only.
  - Never commit `memory/`, `logs/`, `.claude/`, `api/.venv` or `*-report.md`.
  - No push, no new branches or worktrees, no subagents.
  - Ignore Devin and PR comments.
  - End every commit message with the session's attribution trailer.
- **The `mcp_tools.py` source lint** (`test_mcp_tools_context.py:21-33`): no new text in that file
  (comments and docstrings included) may contain `resolve_repo_context`, `mark_episodes_processed`,
  `list_unprocessed_episodes`, `import mcp` or `from mcp`.
- **No LLM anywhere in this track.** No new module imports `litellm`, `providers` or `ask_service`.
  Final verification greps for it.
- **R12, both servers:**
  - A new tool lands in the stdio `TOOLS`, `TOOL_SCOPE` (or `NEVER_REMOTE`), `REMOTE_TOOLS` and
    `_DISPATCH` in the **same commit**. `test_remote_tools.py` fails otherwise.
  - A remote description names another tool only when both share a scope.
- **Telemetry is ids and enums only:** never a claim text, summary, quote, reason or query.
- **Evidence is spans, not copies:** a watch excerpt lives in the episode, and a claim holds
  offsets into it.
- **Privacy (standing, 2026-09-02):**
  - No owner name in code (the portability rail) and no author-machine path anywhere. Write
    `<worktree>` / `<repo>`.
  - One exception, which CLAUDE.md names: a backlog row may open in the owner's own voice
    (`Rodrigo <date>: "…"`) when it quotes the owner's own design opinion, as G140 does below.
  - No bank contents in docs.
  - The article's author and product (Dhravya Shah, Instinct, supermemory) may be named; the
    owner's data may not.
- **Docstrings explain WHY**, citing the G-row or ruling (`G140 Q-R…`, `R3 P…`, `R5 §…`), at the
  density of the files touched.
- Line numbers above are from `0354538` and drift as tasks land. Read the cited code before editing.

---

## Rulings (binding)

Every place the brief left a choice is decided here, with the reason, so no task re-opens it. Ids
are `Q-R<n>`.

- **Q-R1: recall's lexical legs are `search_service`'s, reached through two seams.**
  - `_keyword_search_entities(entities_dir, query, top_k)` keeps its name and signature, because
    three tests depend on it: one patches it, one relies on the real leg, and the golden run calls
    it. Its body becomes `search_service.lexical_entity_hits(entities_dir.parent, …)`.
  - A new seam, `_claim_subject_search(memory_path, query, top_k)`, wraps `claim_subject_hits`,
    which is lexical in both modes (G136 R9). It is fused as RRF's **third** list.
  - `mcp_tools._rrf_fuse` becomes the name `search_service.rrf_fuse` (Hand-off 1(c)). The parity
    test compares a function with itself, so it is deleted and replaced by an identity assertion.
  - The MCP process passes its own per-call bank path (the split-brain rule).
  - The honest gap (`No entities found matching …`) and the RRF constant (k = 60) are unchanged.
  - **Cold bank, disclosed.** With no FTS file yet, both legs answer from `_search_fallback` while
    a daemon builds the index, so recall never blocks. That fallback matches names, aliases and
    tags, and returns no claims. A match that only the body or a claim carries shows up once the
    build lands, seconds later. The old leg scanned bodies on every call, and that per-call scan
    is what this removes.
  - **Rejected:** typo tolerance (`difflib`). G136 kept it out of the server default, and recall is
    no different.

- **Q-R2: history is bounded, dated and read from the page.**
  - For recall's top 3 hits, show closed claims whose `valid_to` is 0–30 days old, newest first:
    ≤ 2 per page, ≤ 5 in total, objects clipped at 80 characters.
  - The block is "**Changed recently (last 30 days):**", placed after the summaries.
  - Each line reads `- \`<id>\` <predicate>: was "X" until <date> → now "Y"`. Task 3 adds the
    *withdrawn* wording and Task 4 the *ended* wording.
  - The source is the page's `claims` block, the source of truth, parsed for pages recall already
    reads. The FTS rows are not used.
  - `cicada_get_perspective(history=true)` lists every closed claim for the subject, ≤ 20, newest
    first. It is **off by default and byte-identical when off**; the golden fixture pins that.
  - Why these numbers: they give supermemory's "old versions included automatically" without
    letting history outgrow the summaries recall exists to show.

- **Q-R3: `include_superseded` is removed from `vector_index.search_claims`.** The vector claims
  index stays current-only (G136 R10). History is served by the page (Q-R2) and by FTS. The
  defensive `superseded_by` filter stays. The HTTP `?include_superseded=` on
  `/entities/{id}/claims` works and is untouched. **Why remove rather than fix:**
  - Fixing it means indexing closed claims in the vector table. Every existing reader would then
    need a new filter.
  - Closed claims would give each subject extra always-present semantic neighbours: the G136 R9
    effect.
  - All of that would buy nothing FTS does not already provide.

- **Q-R4: the timeline is `api/services/change_timeline.py`, an MCP tool only, and it stores nothing.**
  - One `git log` per call: `-n1000`, a 3-second timeout, `%ad` in iso-strict. Bodies are parsed
    in-process by `parse_cycle_body` and never sent anywhere.
  - Captured episodes are counted per `origin` from `bank_index` frontmatter.
  - `State snapshot` commits are skipped.
  - A bank that is not its own git root is never read, so `git` cannot climb into an enclosing repo
    (the `agent_commits` rule).
  - `since` is a date or a number of days. The default is 7; it is clamped to 90 back and never
    after today.
  - **Ids and counts only.** No episode title, no claim text, no conversation id. The remote `read`
    scope must never carry the person's words, which belong to the `sources` scope (G135).
  - No HTTP route and no app surface this track (see Not in scope).

- **Q-R5: a withdrawal is its own tool, `cicada_retract_claim(subject, claim_id, reason, evidence?)`.**
  It is not an argument on `cicada_write_claim`: a withdrawal is not a fact, and a second meaning
  on one tool muddies R12 and the tool description.
  - **Who may withdraw.** A caller may withdraw only a claim it wrote:
    - **Remote:** `claim.origin == "remote:<its connector>"`.
    - **Stdio:** `authored_by` equals its author label, or the pre-G135 `mcp-agentic-write`
      placeholder (any local agent could have written that). The claim's origin must not be
      `remote:`.
    - The stdio identity is the **harness label** (`ctx.author`, e.g. `claude-code`), not the
      session. G135 R-R11 made the harness the author, and G49 keeps the model reserved. So any
      Claude Code session may withdraw a claim another Claude Code session wrote. That is the
      finest identity a claim carries today.
    - **Never:** a human claim (`claim_reconciler.is_human`), a Sleep claim (whose author is a
      model id), or another harness's claim. For those, the reply points to a new claim or to the
      app.
  - **What it writes.**
    - The target gets `valid_to = today` and `superseded_by = <record>`.
    - A **record claim** is appended to the same page:
      - `id: clm_retract_<sha1(target)[:8]>`
      - `predicate: retracts`, `object: <target id>`, `object_kind: literal`
      - `text` = the reason (≤ 240 characters, required)
      - the target's observer, context and trust
      - `authored_by` = the caller
      - `evidence` = the agent's verified quotes, else `reasoning`
      - **born closed** (`valid_from == valid_to == today`), so it is history and never a
        current belief.
    - Nothing is deleted.
  - **Commit and remote handling.**
    - The commit line's action is `retracted`.
    - Remote scope is `record`, inside `WRITE_TOOLS`, so it gets the write lock and the Sleep gate.
    - `destructive_hint: false`, because nothing is lost; `idempotent: true`.
  - R3 P7's broader half stays open in G140: the person's own "that's off" closing a user claim,
    and entity-level forget through a `removal` item.

- **Q-R6: a stated end is `Claim.expected_end`, never a future `valid_to`.**
  - Thirteen modules read a non-null `valid_to` as *closed*. A future date there would hide the
    fact the day it was written, which is the opposite of the intent.
  - The key is omitted from YAML when unset (G118 R7), so no legacy page ever diffs.
  - **Writers:** `cicada_write_claim(expected_end="YYYY-MM-DD")` on both servers.
  - A G17 `due` claim's own ISO-date object **is** its stated end. That end is derived at expiry
    time and never stamped.
  - An unparseable `expected_end` is ignored and said so in the reply. The claim is still written,
    because provenance never blocks memory.
  - In `_reinforce`, a restated end replaces the old one (it is the newer statement), and a
    restatement without an end keeps it.
  - **Not built:** Stage-1 extraction of ends from prose ("this weekend"). That is a paid prompt
    change, and the brief limits expiry to explicit ends.

- **Q-R7: expiry runs in the Sleep tail's guarded branch, first, before the polls.**
  - **What closes.** `claim_expiry.expire` closes every open claim whose stated end is
    **strictly before today**. The end date is inclusive: "until Friday" is current through Friday.
    It sets `valid_to = max(end, valid_from)`, so a claim recorded after its end never gets a
    negative window. It sets no `superseded_by`, because nothing replaced it.
  - **Human claims close too.** The end is the claim's own content, the person's statement, so this
    is not an agent closing a human claim.
  - **The commit.** One `commit_paths` commit, `Expiry <date>`, with lines
    `entities/<id>.md: expired (source: n/a, trigger: sleep/expiry)` and `Cicada-Author: cicada`.
    It carries no engine trailer, because no LLM ran (the G85 shape).
  - **The subject is deliberately not `Sleep cycle … (expiry)`.** `get_sleep_history` greps
    `^Sleep cycle`, and the Sleep page's rows mean consolidations. `cicada_timeline` reports expiries.
  - **Failure handling.** A failed commit restores the touched pages from HEAD
    (`git checkout -- <paths>`). The change is re-derived tomorrow, while a dirty page would be
    stamped by the next `git add -A` writer (the G85 smear).
  - **Placement.** Only the guarded branch runs it, because on a half-written cycle `commit_paths`
    would take Sleep's uncommitted hunks on the same page.
  - Idle nights included: expiry is time-driven, not episode-driven, which is why it belongs to
    the tail and not to Stage 3.

- **Q-R8: the watch record's signature follows the brief exactly:**
  `cicada_record_watch(url, summary, excerpts=[{t, quote}], chapters=[{t, title}]?)`.
  - **Caps.** A summary is ≤ 1,500 characters on **one line**: newlines are folded, so no line can
    pose as a turn marker. At most 12 excerpts × 240 characters; at most 50 chapters × 120.
    Anything over is dropped or cut, and the reply says so.
  - **Times.** `t` takes `m:ss`, `h:mm:ss` or integer seconds. An unreadable `t` drops that
    excerpt, and so does a `t` past `MAX_T_S` (24 hours). The cap keeps every written stamp within
    the `video [h:mm:ss]:` marker's two-digit hour field (Q-R9), so a quote can never land in the
    summary's turn by accident.
  - **The episode.** Its body is `assistant: <summary>`, a blank line, then `video [m:ss]: <quote>`
    lines in time order. It is idempotent by content hash, read through `bank_index`.
  - **An unsaved URL.** `http(s)` is saved first through `save_url`: same two paths, same
    `net_guard`, same commit. `file://` is refused with "add it in the app first" (the app owns
    local files).
  - **The claim.** The `describes` claim is written through `agentic_write.write_claim`.
    `describes` is unseen by the cardinality map, so it is multi-valued: each watch keeps its own
    summary. The origin is `agent/watch` on stdio and `remote:<id>` remotely (R-R23). Its evidence
    is the summary span (`assistant`) plus each excerpt's span (`media`), located inside its own
    line's window.
  - **`describes` already has a producer.** `link_enrichment` writes one from a page's stored
    description (origin `sleep/link_enrichment`, a `page` span). Its backfill skips any page that
    already has a `describes` claim (`link_enrichment.py:699`), so a watched video is never
    re-described by the backfill. That is intended, because the watch is the better description.
    The two stay distinguishable: only a watch carries a `media` span.
  - **The commit.** The episode and the page are committed **together** under the agent. The
    existing stdio `save_episode` stays uncommitted by G135 ruling, but a new tool has no
    byte-identical constraint, and one commit keeps the pair's provenance whole.
    - The page line always reads `updated`, because the watch adds a claim to the page.
    - Disclosed, not fixed: when this call had to save the link first on stdio's backend-down path
      (`save_url` path 2), that save is uncommitted, exactly as a plain `cicada_save_url` leaves it
      today. The page's creation therefore rides in the watch commit, under the same agent.
      `sources/url_index.json` and the save's own episode stay dirty for the next writer, as they
      do after any stdio backend-down save. This tool does not widen that ruling. On path 1 and
      remotely the save already committed itself.
  - **Chapters.** An agent's chapters fill `media.chapters` **only when the page has none**:
    description-parsed chapters are the provider's own and win.
  - **"Watched"** is derived, never stored: a `describes` claim with at least one `media` span.
  - **Nothing here fetches.** Cicada never downloads, transcribes or watches; the agent's own tools
    did.

- **Q-R9: `media` is the fifth evidence kind, derived from a turn marker.**
  - It is appended to `EVIDENCE_KINDS`; older readers degrade it to `reasoning`.
  - `_TURN_RE` gains a **second alternative**: `video` or `media`, followed by a **required**
    `[m:ss]` or `[h:mm:ss]`, before the colon.
    - The time is required on purpose. "Video:" and "Media:" open ordinary lines in a person's
      own messages and notes. With an optional time, such a line would silently become a video's
      words, which is R5 §2 defect 3 in reverse.
    - The six existing words keep their old alternative exactly. `user [0:10]:` does **not**
      become a marker, and no existing episode changes how it reads.
  - A `_marker_word(m)` helper returns whichever alternative matched.
  - `speaker_kind` and `turns()` return `media` for those lines, through one `_role()` helper, so
    a turn's role and a span's kind can never disagree (R-PB3).
  - The position in the video is derived at read time from the marker line (`evidence.media_time`).
    It is served as `t` on `EpisodeSpan` and `EpisodeTurn`, and **never stored** on `Evidence`: a
    new field would appear on every claim of every re-rendered page.

- **Q-R10: `cicada_save_url` keeps a note on a duplicate, and names episodes.**
  - `media_ingestor.write_note_episode` is called **only** by the two single-save paths:
    `POST /sources/save` and `save_url`'s backend-down path. `ingest_one` never calls it, because a
    re-import must not mint a note per bookmark.
  - One episode per (media entity, note). The `content_hash` is read back through `bank_index`.
  - **Why not Telegram's approach.** Telegram appends a `## Saved because` section to the
    existing episode (`telegram_capture._append_saved_because_section_if_absent`), and that path
    is untouched. It is not reused here, for two reasons:
    - Appending prose to an episode that may already be cited would turn every span on it
      `stale`: G118 A7's `grown` needs a turn-boundary prefix.
    - A `processed: true` episode is never read by Sleep again.
    A new episode is citable at once and consolidated next cycle.
  - Both replies name the entity **and** the episode. A kept note says "cite that id as evidence".
  - **An agent's note is the agent's words.** A note arriving with a session id is written after an
    `assistant:` marker. That applies in the new note episode **and** in the create path's episode
    body, where it used to sit under `## User note`. The tool cannot know a note relays the person
    (the R-N2/R-F2 rule; G135 R-R12 already treats an MCP save as the agent's). The person's own
    note from the app keeps `## User note`.
  - `SourceSaveResponse.note_episode_id` is additive.

- **Q-R11: the observer spelling.**
  - The stdio `cicada_write_claim.observer` becomes a single `pattern`:
    `^(owner|agent|external|<legacy>|external:[a-z0-9][a-z0-9-]{0,63})$`.
  - It is not an `enum`, because in JSON Schema an `enum` and a `pattern` must *both* hold.
  - The legacy value stays accepted and unadvertised (Track P R8). `test_agentic_write.py:361-364`
    moves from `enum` membership to `fullmatch`.
  - The remote schema keeps `agent|external` (R-R23; its test pins it). Nothing asks for more there.

- **Q-R12: video metadata is fields only.**
  - Vimeo, Loom and TikTok oEmbed `description` is kept, cut at 5,000 characters, in the episode
    and on the page (`## Description`, as articles already do).
  - `video_chapters.parse` reads chapters from it. A list counts only as ≥ 2 lines that each **open**
    with a timestamp, the first at `0:00`, strictly increasing. Anything else yields `[]`, because
    absent beats a guess (R17).
  - `media.chapters` is written only when set (R15). `EntityMedia.chapters` is additive and keeps
    only well-formed rows.
  - YouTube is unchanged, because its oEmbed has no description. `channel_url`, `published_at`,
    captions and the YouTube Data API (R5 D5) are out.

- **Q-R13: the primer's Standing/Current split reads the decay classes.** All rows are ids,
  one-liners or enums already on pages.
  - **How to work with me** (the `preferences` key, name kept for readers of schema v1): `skill`
    pages whose class is durable or evergreen, ranked by **confidence alone**. Pages tagged
    `autonomy`, `communication-style` or `working-style` sort first. That is a convention with no
    producer yet (Stage 4 writes `tags: []`), so it does not make the row empty.
  - **Standing:** non-skill pages, excluding types that have their own row or are artifacts
    (project, person, media, directory, deadline). Their class must be durable or evergreen,
    ranked by confidence.
  - **In focus:** pages outside those types whose class is active or volatile and whose
    `last_referenced` is within 14 days. Ranked by recency, then volatile first, then confidence.
  - **Identity:**
    - The owner row comes from `owner_identity.resolve_observer`, G117's one resolver. This fixes
      the env-only read.
    - `owner_one_liner` is the owner page's summary sentence.
    - The **timezone** comes from `tzlocal.get_localzone_name()` per request. `tzlocal` is
      APScheduler's own dependency (`api/uv.lock:153`, installed in `api/.venv` as tzlocal 5.3.1), and
      the fallback is the UTC offset.
    - The timezone is **never written to `_state.md`**: the file travels with the bank, and an idle
      night must not commit because the owner travelled (R1). It is part of the handshake cache key.
  - **Schema.** `SCHEMA_VERSION = 2`, and `inputs_version` folds the schema in, so an upgraded
    backend rebuilds a v1 file once.
  - **The 14-day window is a date, and that is disclosed rather than hidden.** On the night a page
    leaves the window, Sleep's forced rebuild writes one `State snapshot`. That is a real change
    to the cursor, the same kind the existing recency ranking makes. The window never moves the
    file every night: R1's `sleep.next_at` failure was a clock written into the file, and nothing
    here writes a clock.
  - **Trim orders.**
    - The state file, at 6 KiB: people → focus → standing → conversations → preferences → projects.
    - The primer, at 1,800 tokens: people → focus → conversations → standing → project one-liners →
      preference one-liners.
    - Current rows go before standing ones. The working agreements go last, because they are the
      most useful tokens per line (Instinct's "autonomy calibration"). The project list keeps R10's
      last place.
  - **Rejected:** Instinct's approach of ~4,250 tokens of LLM-written, unstamped prose. It breaks
    G53's "a cursor, never a copy", and the author measured a two-day lag on it.

- **Q-R14: contract v3 (local) and v2 (remote) name the new tools, and a new R12 test parses every
  `` `cicada_x(args)` `` in both primers against the schemas.**
  - It found `cicada_recall_detail(id)`, which is fixed to `(entity_id)` in both contracts.
  - The remote closing line drops "or rewrites". Withdrawing one's own claim is a rewrite of
    validity, and the old sentence would become untrue.
  - `_remote_capabilities`' "Can't delete or rewrite." stays byte-identical. It is the app's
    `RemoteScope.summary` string, pinned on both sides (`test_handshake_remote.py:48`,
    `RemoteConnectorTests.swift:37-50`), and this track ships no Swift.
    - It stays true in the sense that line means: a connection never deletes and never rewrites
      a claim's words. A withdrawal keeps the claim and its text, and closes it.
    - Rewording both sides is Track O's, with its Settings copy.

- **Q-R15: P9 is not built this track.** P9 is the article's 13-point rubric as a retrieval eval
  on the demo bank. It is recorded **open** in G140 with its design: a $0 half asserting "expected
  id in recall top-k" for single fact, alias, paraphrase, typo, relationship label,
  superseded-not-current, abstention and two-hop; and an LLM-judged half on demand. The track
  already has eight commits, and the eval deserves its own reviewable change.

- **Q-R16: the golden fixture builds its FTS index inline.** `_bank` calls
  `search_index.ensure_fresh(memory, wait=True)` before the first reply, so recall never races the
  background builder. The fixture is re-recorded only where a reply legitimately changes:
  - Task 1: `recall*`, if ranking moved. The expected diff is none.
  - Task 5: `save_url`, which now names its episode.
  - Every other key must stay byte-identical.

- **Q-R17: coordinating with the other round-3 tracks, and the order of this track.**
  - **Local-sources (R-N3):** owns secret and one-time-code scrubbing on every episode writer. It
    must add the two writers this track creates (`watch_record._write_episode` and
    `media_ingestor.write_note_episode`) to its wrap.
  - **Track N:** may edit `_TURN_RE` for meeting speakers. On a conflict, keep both alternations;
    `EVIDENCE_KINDS` is append-only.
  - **Track P:** renders `media` and `t`.
  - **Track O:** its recommended-skills manifest names `cicada_record_watch` as the bridge tool and
    owns the handshake bridge line.
  - **Order:** the three new tools (Tasks 2, 3 and 6) ship before the contract that names them
    (Task 7). Each tool lands silent in the primer and shippable alone.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/mcp_tools.py` | recall legs + history (T1); `timeline` (T2); `retract_claim` (T3); `write_claim(expected_end=)` (T4); `save_url` replies + duplicate note (T5); `record_watch` (T6) |
| `api/services/search_service.py` | T1: docstrings only. The module docstring, `rrf_fuse` and `lexical_entity_hits` say the hand-off is done. Its `rrf_fuse`, `lexical_entity_hits` and `claim_subject_hits` are consumed unchanged |
| `api/services/vector_index.py` | `search_claims` loses `include_superseded` (T1) |
| `api/services/change_timeline.py` (new) | T2: `parse_since`, `kind_of`, `collect`, `render` |
| `api/services/agentic_write.py` | T3: `owns`, `retract_claim`; T4: `write_claim(expected_end=)`, `_iso_date` |
| `api/services/claims.py` | T4: `Claim.expected_end` (omitted when unset); T6: `media` appended to `EVIDENCE_KINDS` |
| `api/services/claim_reconciler.py` | T4: `_reinforce` carries a restated end |
| `api/services/claim_expiry.py` (new) | T4: `stated_end`, `expire`, `commit_message`, `restore` |
| `api/services/sleep_cycle.py` | T4: `_expire_claims_safely`, first in the tail's guarded branch |
| `api/services/video_chapters.py` (new) | T5: `seconds`, `stamp`, `parse` |
| `api/services/media_ingestor.py` | T5: `MediaMeta.chapters`, description kept, an agent's note under `assistant:`, `write_note_episode` |
| `api/routers/sources.py` | T5: a duplicate with a note keeps it and commits it; `noteEpisodeId` |
| `api/routers/entities.py` | T5: `_build_media_block` → `chapters` |
| `api/services/evidence.py` | T6: timed `video`/`media` markers (the time is required), `_marker_word`, `_role`, `media_time`, `TurnSpan.t` |
| `api/routers/episodes.py` | T6: `EpisodeSpan.t` |
| `api/services/watch_record.py` (new) | T6: `resolve`, `record` |
| `api/services/state_dictionary.py` | T7: schema v2: `preferences` re-ranked, `standing`, `focus`, owner one-liner |
| `api/services/handshake.py` | T7: Standing/Current, `local_timezone`, contract v3/v2 |
| `api/config.py` | T7: `state_standing`, `state_focus` |
| `api/models/schemas.py` | T5: `VideoChapter`, `EntityMedia.chapters`, `SourceSaveResponse.note_episode_id`; T6: `EpisodeSpan.t`, `EpisodeTurn.t` |
| `mcp/server.py` | every task's stdio schema + dispatch; T5: the observer pattern |
| `api/remote/catalog.py`, `api/remote/tools.py`, `api/remote/runtime.py` | scopes, remote schemas, dispatch for the three new tools; `history` and `expected_end` arguments; T3: `tools.py`'s module docstring names the withdrawal |
| `skills/cicada-librarian/SKILL.md` | T6: the "after watching a video" trigger and the video steps become `cicada_record_watch` |
| Tests (new) | `test_mcp_recall_legs.py`, `test_change_timeline.py`, `test_retract_claim.py`, `test_claim_expiry.py`, `test_video_chapters.py`, `test_video_save_defects.py`, `test_watch_record.py`, `test_handshake_r12.py` |
| Tests (edited) | `test_claims.py`, `test_search_service.py`, `test_mcp_stdio_golden.py` + its fixture, `test_mcp_tools_context.py`, `test_agentic_write.py`, `test_owner_name_portability.py`, `test_video_enrichment.py`, `test_claims_evidence.py`, `test_state_dictionary.py`, `test_state_wiring.py` (`schema_version`), `test_handshake.py`, `test_entity_read_events.py` and `test_mcp_recall_episode_fallback.py` (a claim-leg stub, plus a comment) |
| Docs | `docs/goals/memory-evolution.md` (G140 new; G22, G53, G75, G118, G136), `docs/goals/TODO.md`, `CLAUDE.md`, `SKILL.md:44` (T7: `cicada_open_hub(hub_id)` → `(hub)`, R12) |

---

### Task 1: Recall reads aliases, words and claims; history on request (R3 P1, P2, P4; Q-R1–Q-R3, Q-R16)

This task fixes the whole-query substring leg (a word order or an alias used to be a miss), adds
claims as a third recall leg, adds bounded dated history, adds `history` to
`cicada_get_perspective`, and removes the dead `include_superseded` flag. The branch stays
shippable: every reply that does not touch history is unchanged.

**Files:**
- Modify: `api/services/mcp_tools.py`. The import line `:37`; `_rrf_fuse` at `:396-413`; `recall`
  at `:444-448` and after `:490`; `get_perspective` at `:905-965`; `_keyword_search_entities` at
  `:1010-1038`; new helpers after `_truncate_to_desc_and_recent_history` (`:1088-1097`).
- Modify: `mcp/server.py`. The `cicada_get_perspective` schema (`:259-280`), the `handle_tool`
  branch (`:645-650`), and `handle_get_perspective` (`:749-750`).
- Modify: `api/remote/tools.py`, the `cicada_get_perspective` properties (`:60-67`), and
  `api/remote/runtime.py`, the `cicada_get_perspective` dispatch (`:174-175`).
- Modify: `api/services/vector_index.py`, `search_claims` (`:638-681`).
- Modify: `api/services/search_service.py`, docstrings only (module `:6`, `rrf_fuse` `:93-104`,
  `lexical_entity_hits` `:763-771`).
- Modify: `api/tests/test_claims.py:404-437`, `api/tests/test_search_service.py:108-115` (delete),
  `api/tests/test_mcp_stdio_golden.py` (`_bank`), `api/tests/test_entity_read_events.py:109-117`
  (a claim-leg stub and the comment), and `api/tests/test_mcp_recall_episode_fallback.py:26` (a
  claim-leg stub). Both are hermetic seam sets, and the new leg is a new seam.
- Test: `api/tests/test_mcp_recall_legs.py` (new).

**Interfaces:**
- Produces:
  - `mcp_tools._claim_subject_search(memory_path, query, top_k) -> list[dict]`
  - `mcp_tools._recent_changes(entities_dir, hits, today) -> list[str]`
  - `mcp_tools._history_line(eid, old, page) -> str`
  - `mcp_tools._how_closed(old, page) -> str`
  - `mcp_tools._page_claims(path) -> list[Claim]`
  - the constants `RECENT_CHANGE_DAYS = 30`, `RECENT_CHANGES_PER_PAGE = 2`,
    `RECENT_CHANGES_TOTAL = 5` and `PERSPECTIVE_HISTORY_MAX = 20`
  - `mcp_tools.get_perspective(ctx, subject, observer=None, context=None, history=False)`
  - the stdio and remote schema property `history`
- Consumes: `search_service.rrf_fuse`, `lexical_entity_hits` and `claim_subject_hits`;
  `search_index.ensure_fresh`; `claims.parse_claims`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_mcp_recall_legs.py`:

```python
"""G140 Q-R1..Q-R3 (R3 P1, P2, P4) — MCP recall's legs, and history on request.

Before: recall's keyword leg matched the WHOLE query as one substring of
name/tags/related/body and never read `aliases`; claims were never a recall
leg; a closed claim never surfaced anywhere an agent looks. Hermetic: no
vector index (the indexer raises, as in the golden run), a synthetic bank, the
FTS index built inline (Q-R16). Placeholders only.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.remote import runtime as remote_runtime
from api.remote import tools as remote_tools
from api.services import markdown_parser, mcp_tools, search_index, search_service, vector_index
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer

mcp = stdio_server()
TODAY = date.today()


def _ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def _page(memory: Path, eid: str, name: str, *, etype: str = "concept", aliases=(), body: str = "",
          claims=()) -> None:
    text = f"## Summary\n{body or name + ' is a synthetic page.'}\n"
    if claims:
        text = write_claims(text, list(claims))
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": etype, "status": "active", "confidence": 0.6,
                           "aliases": list(aliases), "tags": [], "related": []}, text)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)

    class _NoIndex:
        def __init__(self, *a, **k):
            raise RuntimeError("no vector index in this bank")

    monkeypatch.setattr(vector_index, "SqliteVecIndexer", _NoIndex)
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(mcp.mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    return memory


FENCE = "`" * 3  # spelled out so this file never holds a literal fence


def _suggested(reply: str) -> list[str]:
    m = re.search(FENCE + r"cicada-hints\n(.*?)\n" + FENCE, reply, re.S)
    return json.loads(m.group(1))["suggested_entities"] if m else []


def _changes(reply: str) -> list[str]:
    head = f"**Changed recently (last {mcp_tools.RECENT_CHANGE_DAYS} days):**\n"
    return reply.split(head, 1)[1].split("\n\n", 1)[0].splitlines() if head in reply else []


def _closed_pair(subject: str, old_obj: str, new_obj: str, closed_on: str) -> list[Claim]:
    new = Claim(id=f"clm_{subject}_uses_{new_obj}", text=f"{subject} uses {new_obj}", subject=subject,
                predicate="uses", object=new_obj, valid_from=closed_on)
    old = Claim(id=f"clm_{subject}_uses_{old_obj}", text=f"{subject} uses {old_obj}", subject=subject,
                predicate="uses", object=old_obj, valid_from="2026-01-01", valid_to=closed_on,
                superseded_by=new.id)
    return [old, new]


def test_an_alias_reaches_its_page(bank):
    _page(bank, "dining-preferences", "Dining", aliases=["takeout", "delivery"])
    _page(bank, "alpha-project", "Alpha Project", etype="project")
    search_index.ensure_fresh(bank, wait=True)
    assert _suggested(mcp.handle_recall("takeout")) == ["dining-preferences"]


def test_query_words_match_one_by_one(bank):
    _page(bank, "alpha-project", "Alpha Project", etype="project",
          body="Alpha Project is a synthetic search index.")
    search_index.ensure_fresh(bank, wait=True)
    assert "alpha-project" in _suggested(mcp.handle_recall("project alpha"))


def test_a_matching_claim_leads_to_its_subject(bank):
    claim = Claim(id="clm_bob_partner", text="Bob Example is the partner of the person",
                  subject="bob-example", predicate="partner-of", object="owner", valid_from="2026-01-01")
    _page(bank, "bob-example", "Bob Example", etype="person", body="Bob Example is a synthetic person.",
          claims=[claim])
    search_index.ensure_fresh(bank, wait=True)
    assert mcp_tools._claim_subject_search(bank, "partner", 8) == [
        {"entity_id": "bob-example", "source": "claim", "score": 0.0}]


def test_the_claim_leg_is_fused_as_a_third_list(bank, monkeypatch):
    _page(bank, "bob-example", "Bob Example", etype="person")
    monkeypatch.setattr(mcp.mcp_tools, "_keyword_search_entities", lambda entities_dir, query, top_k: [])
    monkeypatch.setattr(mcp.mcp_tools, "_claim_subject_search",
                        lambda memory_path, query, top_k: [{"entity_id": "bob-example", "source": "claim"}])
    assert _suggested(mcp.handle_recall("anything at all")) == ["bob-example"]


def test_recall_fuses_with_the_one_rrf():
    assert mcp_tools._rrf_fuse is search_service.rrf_fuse
    assert mcp._rrf_fuse is search_service.rrf_fuse, "the stdio server keeps re-exporting the name"


def test_a_replaced_value_reads_was_until_now(bank):
    _page(bank, "alpha-project", "Alpha Project", etype="project",
          claims=_closed_pair("alpha-project", "sqlite", "duckdb", _ago(5)))
    search_index.ensure_fresh(bank, wait=True)
    assert _changes(mcp.handle_recall("alpha project")) == [
        f'- `alpha-project` uses: was "sqlite" until {_ago(5)} → now "duckdb"']


def test_history_is_bounded_per_page_and_by_age(bank):
    claims = [Claim(id=f"clm_t{i}", text=f"alpha tried tool {i}", subject="alpha-project",
                    predicate=f"tried-{i}", object=f"tool-{i}", valid_from="2026-01-01",
                    valid_to=_ago(1 + i)) for i in range(4)]
    claims.append(Claim(id="clm_ancient", text="alpha was hosted on ancient", subject="alpha-project",
                        predicate="hosted-on", object="ancient", valid_from="2025-01-01",
                        valid_to=_ago(mcp_tools.RECENT_CHANGE_DAYS + 5)))
    _page(bank, "alpha-project", "Alpha Project", etype="project", claims=claims)
    search_index.ensure_fresh(bank, wait=True)
    lines = _changes(mcp.handle_recall("alpha project"))
    assert [line.split(":")[0] for line in lines] == ["- `alpha-project` tried-0", "- `alpha-project` tried-1"]


def test_history_is_capped_across_pages(bank):
    for eid in ("alpha-one", "alpha-two", "alpha-three"):
        _page(bank, eid, eid.replace("-", " ").title(), claims=[
            Claim(id=f"clm_{eid}_{i}", text=f"{eid} tried {i}", subject=eid, predicate=f"tried-{i}",
                  object=f"tool-{i}", valid_from="2026-01-01", valid_to=_ago(1 + i)) for i in range(2)])
    search_index.ensure_fresh(bank, wait=True)
    assert len(_changes(mcp.handle_recall("alpha"))) == mcp_tools.RECENT_CHANGES_TOTAL


def test_perspective_history_lists_earlier_claims_on_request(bank):
    _page(bank, "alpha-project", "Alpha Project", etype="project",
          claims=_closed_pair("alpha-project", "sqlite", "duckdb", _ago(5)))
    plain = mcp.handle_tool("cicada_get_perspective", {"subject": "alpha-project"})
    assert "Earlier" not in plain and "1 valid claim" in plain
    full = mcp.handle_tool("cicada_get_perspective", {"subject": "alpha-project", "history": True})
    assert full.startswith(plain), "the current half is byte-identical"
    assert "Earlier, newest first (1):" in full
    assert 'replaced by "duckdb"' in full and f"→ {_ago(5)}" in full


def test_history_is_in_both_schemas_and_the_remote_dispatch(monkeypatch):
    stdio = {t["name"]: t for t in mcp.TOOLS}["cicada_get_perspective"]["inputSchema"]["properties"]
    remote = remote_tools.REMOTE_TOOLS["cicada_get_perspective"]["inputSchema"]["properties"]
    assert stdio["history"]["type"] == remote["history"]["type"] == "boolean"
    seen: dict = {}
    monkeypatch.setattr(mcp_tools, "get_perspective",
                        lambda ctx, subject, observer, context, history: seen.update(history=history) or "ok")
    remote_runtime._DISPATCH["cicada_get_perspective"](None, {"subject": "x", "history": True})
    assert seen == {"history": True}


def test_search_claims_has_no_dead_flag():
    assert "include_superseded" not in inspect.signature(SqliteVecIndexer.search_claims).parameters
```

  Also replace `api/tests/test_claims.py::test_search_claims_excludes_superseded_by_default`
  (`:404-437`) with the version below, keeping its setup lines exactly and adding `import inspect`
  at the top of the file:

```python
def test_search_claims_never_returns_a_superseded_claim(tmp_path):
    """G140 Q-R3: the vector claims index is current-only. `include_superseded`
    could only ever surface a marker-only claim (superseded_by set, valid_to
    None) that no writer produces — `claim_reconciler._close` stamps both — so
    it was removed; the defensive `superseded_by` filter stays."""
    # … the existing `_write_page_with_claims(...)` setup and `indexer.index_claims()`, unchanged …
    hits = indexer.search_claims("python web framework api", top_k=5)
    assert {h["metadata"]["claim_id"] for h in hits} == {"clm_live"}
    assert "include_superseded" not in inspect.signature(SqliteVecIndexer.search_claims).parameters
```

- [ ] **Step 2: Run them, and expect them to fail.**
  - Command: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_mcp_recall_legs.py api/tests/test_claims.py -q -p no:cacheprovider`
  - Expected failures:
    - the alias and word-order tests (both are misses today);
    - `_claim_subject_search` does not exist;
    - `_rrf_fuse is not search_service.rrf_fuse`;
    - no "Changed recently" block;
    - `history` is not in the schemas;
    - the `include_superseded` parameter still exists.

- [ ] **Step 3: Implement `mcp_tools.py`.**
  1. Line `:37`: `from api.services import agent_commits, agentic_write, episode_ids, search_service`.
  2. Replace the whole `_rrf_fuse` function (`:396-413`) with:

```python
# G136 hand-off 1(c) / G140 Q-R1: one reciprocal-rank fusion for search and
# recall. The API's port was pinned to this helper by a parity test; now there
# is one function, and `mcp/server.py` keeps re-exporting the name.
_rrf_fuse = search_service.rrf_fuse
```

  3. In `recall`, replace `:444-447` (the comment and the three leg lines) with:

```python
    # === Sources 1+2+3: semantic, lexical and claims, rank-fused (G140 Q-R1) ===
    # The lexical leg is search_service's (aliases, word by word, word-start
    # prefix); the claim leg maps a matching CURRENT claim to its subject
    # (R3 P2), so "partner" reaches the person a `partner-of` claim is about.
    semantic = _leann_search_entities(memory_path, query, top_k=8)
    keyword = _keyword_search_entities(entities_dir, query, top_k=8)
    claim_subjects = _claim_subject_search(memory_path, query, top_k=8)
    merged = _rrf_fuse(semantic, keyword, claim_subjects)
```

  4. In `recall`, directly after `output_parts.append("\n\n".join(entity_blocks))` and its `if` (`:489-490`), insert:

```python
    # === G140 Q-R2 (R3 P4c): what changed recently on the top pages ===
    changes = _recent_changes(entities_dir, merged, date.today())
    if changes:
        output_parts.append(
            f"**Changed recently (last {RECENT_CHANGE_DAYS} days):**\n" + "\n".join(changes)
        )
```

  5. Replace the whole `_keyword_search_entities` function (`:1010-1038`) with the following, and
     add the claim seam directly below it:

```python
def _keyword_search_entities(entities_dir: Path, query: str, top_k: int) -> list[dict]:
    """Recall's lexical leg (G140 Q-R1): ``search_service.lexical_entity_hits``.

    It used to match the WHOLE query as one substring of name/tags/related/
    body and never read ``aliases`` — "project alpha" missed "Alpha Project",
    and an alias Stage 1 extracted and merged was invisible (R3 P1). The FTS
    index behind this reads names, aliases and prose word by word. Name and
    signature are kept: tests patch this seam. ``entities_dir`` is the active
    bank's, resolved per call by the caller (the split-brain rule), so its
    parent is the bank. Never raises: a broken index is recall with one leg
    fewer, not an error."""
    try:
        return search_service.lexical_entity_hits(entities_dir.parent, query, top_k=top_k)
    except Exception:  # noqa: BLE001 — a leg, never the reason recall fails
        return []


def _claim_subject_search(memory_path: Path, query: str, top_k: int) -> list[dict]:
    """Recall's claim leg (G140 Q-R1, R3 P2): current claims whose words match,
    mapped to the page they are about — how "partner" reaches a person whose
    page never says it but whose claims do. Lexical on purpose (G136 R9: a
    vector claim leg hands every page with nearby claims a second,
    always-present vote)."""
    try:
        return search_service.claim_subject_hits(memory_path, query, top_k=top_k)
    except Exception:  # noqa: BLE001
        return []
```

  6. After `_truncate_to_desc_and_recent_history`, add:

```python
# ---------- Helpers: what changed (G140 Q-R2, R3 P4) ----------

RECENT_CHANGE_DAYS = 30
RECENT_CHANGES_PER_PAGE = 2
RECENT_CHANGES_TOTAL = 5
PERSPECTIVE_HISTORY_MAX = 20
_HISTORY_CLIP = 80


def _clip(text, limit: int = _HISTORY_CLIP) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _age_days(value, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(value)[:10])).days
    except (TypeError, ValueError):
        return None


def _page_claims(path: Path) -> list:
    """The page's claims block — the source of truth, not the index (Q-R2)."""
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    try:
        return parse_claims(markdown_parser.parse(path).body)
    except Exception:  # noqa: BLE001 — history is garnish; a bad page shows none
        return []


def _how_closed(old, page: list) -> str:
    """How a closed claim stopped being current, read off the page alone."""
    new = {c.id: c for c in page}.get(old.superseded_by or "")
    if new is not None and new.valid_to is None:
        return f'replaced by "{_clip(new.object or new.text)}"'
    if old.superseded_by:
        return f"superseded by `{old.superseded_by}`"
    return "closed"


def _history_line(eid: str, old, page: list) -> str:
    """One closed claim as a dated line — supermemory's "old versions
    included", done as data: ``was X until D → now Y`` (R3 P4c)."""
    head = f"- `{eid}` {old.predicate or 'claim'}:"
    was = f'"{_clip(old.object or old.text)}"'
    new = {c.id: c for c in page}.get(old.superseded_by or "")
    if new is not None and new.valid_to is None and new.predicate == old.predicate:
        return f'{head} was {was} until {old.valid_to} → now "{_clip(new.object or new.text)}"'
    return f"{head} was {was} until {old.valid_to}"


def _recent_changes(entities_dir: Path, hits: list[dict], today: date) -> list[str]:
    """Bounded, dated history for recall's top pages (Q-R2): claims closed in
    the last ``RECENT_CHANGE_DAYS``, at most ``RECENT_CHANGES_PER_PAGE`` per
    page and ``RECENT_CHANGES_TOTAL`` overall, newest first. Engine-free: one
    parse per page recall already reads."""
    lines: list[str] = []
    for hit in hits[:3]:
        eid = hit.get("entity_id") or hit.get("id")
        path = entities_dir / f"{eid}.md" if eid else None
        if path is None or not path.exists():
            continue
        page = _page_claims(path)
        closed = []
        for c in page:
            age = _age_days(c.valid_to, today) if c.valid_to else None
            if age is not None and 0 <= age <= RECENT_CHANGE_DAYS:
                closed.append(c)
        closed.sort(key=lambda c: (str(c.valid_to), c.id), reverse=True)
        for c in closed[:RECENT_CHANGES_PER_PAGE]:
            lines.append(_history_line(eid, c, page))
            if len(lines) >= RECENT_CHANGES_TOTAL:
                return lines
    return lines
```

  7. Replace `get_perspective`'s signature, then the lines from `claims = [` (`:934`) to the end of
     the function (`:965`), with the version below. The docstring gains the last paragraph shown.

```python
def get_perspective(
    ctx: ToolContext,
    subject: str, observer: str | None = None, context: str | None = None, history: bool = False,
) -> str:
    """(existing docstring, unchanged, then:)

    ``history`` (G140 Q-R2, R3 P4b): also list the subject's closed claims,
    newest first, at most ``PERSPECTIVE_HISTORY_MAX``, each with how it
    stopped being current. Off, the reply is byte-identical to before — the
    stdio golden fixture pins it.
    """
    # … unchanged through `parsed = markdown_parser.parse(page)` …
    page_claims = parse_claims(parsed.body)
    claims = [c for c in page_claims if c.valid_to is None and not c.superseded_by]
    if observer:
        claims = [c for c in claims if c.observer == observer]
    if context:
        claims = [c for c in claims if c.context == context]
    earlier: list = []
    if history:
        earlier = [c for c in page_claims if c.valid_to is not None or c.superseded_by]
        if observer:
            earlier = [c for c in earlier if c.observer == observer]
        if context:
            earlier = [c for c in earlier if c.context == context]
        earlier.sort(key=lambda c: (str(c.valid_to or ""), c.id), reverse=True)
        earlier = earlier[:PERSPECTIVE_HISTORY_MAX]

    fm = parsed.frontmatter or {}
    title = str(fm.get("name", page.stem.replace("-", " ").title()))
    perspective = []
    if observer:
        perspective.append(f"observer={observer}")
    if context:
        perspective.append(f"context={context}")
    header = f"Perspective on {title}"
    if perspective:
        header += f" ({', '.join(perspective)})"

    if not claims and not earlier:
        return f"{header}: no currently-valid claims match."

    lines = [f"{header} — {len(claims)} valid claim(s):", ""]
    for c in claims:
        prov = (
            f"{c.observer} · {c.context} · {c.source_trust} · "
            f"conf {c.confidence:.2f} · since {c.valid_from or 'undated'}"
        )
        lines.append(f"- {c.text}\n  _({prov})_")
    if earlier:
        lines += ["", f"Earlier, newest first ({len(earlier)}):"]
        for c in earlier:
            lines.append(
                f"- {c.text}\n  _({_how_closed(c, page_claims)} · valid {c.valid_from or 'undated'} → "
                f"{c.valid_to or 'undated'} · {c.observer} · {c.source_trust})_"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Implement the schemas, the dispatch and the vector index.**
  1. In `mcp/server.py`, add to the `cicada_get_perspective` `properties` (after `context`):

```python
                "history": {
                    "type": "boolean",
                    "description": "Optional. Also list the subject's earlier claims — replaced, withdrawn or ended — newest first, with when each stopped being current. Default false.",
                },
```

  2. The `handle_tool` branch passes `bool(arguments.get("history", False))` as the fourth
     argument. `handle_get_perspective` becomes:

```python
def handle_get_perspective(subject, observer=None, context=None, history=False) -> str:
    return mcp_tools.get_perspective(_ctx(), subject, observer, context, history)
```

  3. In `api/remote/tools.py`, add to `cicada_get_perspective`'s properties:
     `"history": {"type": "boolean", "description": "Optional: also list earlier facts — replaced, withdrawn or ended — newest first."}`.
  4. In `api/remote/runtime.py`, change the `cicada_get_perspective` lambda to:

```python
    "cicada_get_perspective": lambda c, a: mcp_tools.get_perspective(
        c, str(a.get("subject") or ""), a.get("observer"), a.get("context"), bool(a.get("history", False))),
```

  5. In `api/services/vector_index.py`, give `search_claims` this signature and body tail:

```python
    def search_claims(
        self,
        query: str,
        top_k: int = 5,
        *,
        observer: str | None = None,
        context: str | None = None,
    ) -> list[dict]:
        """KNN over currently-valid claims, with optional perspective filters.

        ``observer`` / ``context`` are SQL-free post-filters applied to the
        ``claims``-kind metadata. A claim carrying a ``superseded_by`` marker
        is never returned. G140 Q-R3 removed ``include_superseded``: this index
        holds only claims with no ``valid_to`` (``index_claims``) and
        ``claim_reconciler._close`` always stamps both fields, so the flag
        could only surface a marker-only claim no writer produces. History is
        the page's (MCP recall, ``cicada_get_perspective(history=true)``) and
        the FTS index's (G136 R10). Returns ``[]`` gracefully on a missing db
        or a missing ``claims`` table.
        """
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            # over-fetch so post-filtering doesn't starve the result set
            results = self._knn(conn, "claims", query, top_k * 3)
        except sqlite3.OperationalError as exc:
            logger.warning(f"vector_index.search_claims: query failed ({exc}); degrading to []")
            return []
        finally:
            conn.close()
        filtered: list[dict] = []
        for r in results:
            meta = r.get("metadata", {})
            if observer is not None and meta.get("observer") != observer:
                continue
            if context is not None and meta.get("context") != context:
                continue
            if meta.get("superseded_by"):
                continue
            filtered.append(r)
        return filtered[:top_k]
```

  6. Delete `test_search_service.py::test_rrf_fuse_matches_the_mcp_helper_exactly` (`:108-115`).
     The identity assertion in the new file replaces it.
  7. In `test_entity_read_events.py`, two edits. The assertions do not change.
     - Beside the other stubs (`:109-114`), add
       `monkeypatch.setattr(mcp.mcp_tools, "_claim_subject_search", lambda memory_path, query, top_k: [])`.
       The test's own comment says every leg but the keyword scan is stubbed, and the claim leg is
       a new leg.
     - The comment at `:115-117`, which says the keyword leg is "a whole-query substring match",
       becomes: `# The keyword leg is search_service's lexical leg (G140 Q-R1), which reads the
       page's name word by word — with no FTS file yet, from bank_index's frontmatter fallback.`
  7a. In `test_mcp_recall_episode_fallback.py`, add the same `_claim_subject_search` stub under the
      `_keyword_search_entities` one (`:25-27`). Its docstring promises that "every retrieval source
      handle_recall touches is monkeypatched". Unstubbed, the claim leg would start an FTS build on
      the test's `tmp_path`.
  7b. In `api/services/search_service.py`, bring three docstrings up to date. No code changes.
      - The module docstring's `:6` reference to `mcp/server.py::_rrf_fuse` becomes
        `mcp_tools.recall`.
      - `rrf_fuse`'s "A port of … not an import … so Track R can make the MCP copy an import of
        this one" becomes: "The one reciprocal-rank fusion: `/search` and MCP recall
        (`mcp_tools._rrf_fuse` is this function, G140 Q-R1)."
      - `lexical_entity_hits`' "The keyword leg `mcp/server.py::handle_recall` fuses (:953-956) …
        Adoption is Track R's (the G136 hand-off)" becomes: "MCP recall's keyword leg
        (`mcp_tools._keyword_search_entities`, G140 Q-R1): alias-aware and token-level (R3 P1).
        Pure lexical: claim-reached rows are `claim_subject_hits`' job."
  8. In `test_mcp_stdio_golden.py::_bank`, insert these lines before `return memory`:

```python
    # G140 Q-R16: recall's lexical legs read the FTS index — build it inline
    # so the first recall never races the background builder.
    from api.services import search_index

    search_index.ensure_fresh(memory, wait=True)
```

- [ ] **Step 5: Green, then re-check the golden fixture.**
  - Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_mcp_recall_legs.py api/tests/test_claims.py api/tests/test_search_service.py api/tests/test_mcp_recall_fusion.py api/tests/test_mcp_recall_episode_fallback.py api/tests/test_entity_read_events.py api/tests/test_mcp_handshake.py api/tests/test_mcp_perspective.py api/tests/test_mcp_tools_context.py api/tests/test_remote_runtime.py api/tests/test_remote_tools.py api/tests/test_ask_claim_retrieval.py api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`
  - Everything must be green.
  - **If only the golden test is red**:
    - Re-record with `cd <worktree> && CICADA_RECORD_GOLDEN=1 api/.venv/bin/python -m pytest api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`.
    - Then run `git diff api/tests/fixtures/mcp_stdio_golden.json`. The only keys allowed to differ
      are `recall` and `recall_again`, and each change must be a ranking or suggestion that the new
      legs explain.
    - The expected result is **no diff**: the golden query "alpha project" reached `alpha-project`
      before and still does.
    - Anything else means STOP and report.
- [ ] **Step 6: Commit.** Stage the files above by name, including
  `api/tests/test_mcp_recall_episode_fallback.py` and `api/services/search_service.py`. Message:
  `feat(recall): aliases, words and claims as recall legs; dated history; perspective history (G140 Q-R1..Q-R3, R3 P1/P2/P4, G136 hand-off)`.

### Task 2: `cicada_timeline(since)` — what changed, read from git on demand (R3 P6; Q-R4)

Instinct keeps `timeline/daily` folders. Cicada already records every change in machine-parseable
commit manifests, so this task reads them and stores nothing.

**Files:**
- Create: `api/services/change_timeline.py`.
- Modify:
  - `api/services/mcp_tools.py`: a new `timeline` body, placed after `sources`.
  - `mcp/server.py`: a `TOOLS` entry after `cicada_handshake`, a `handle_tool` branch, and
    `handle_timeline`.
  - `api/remote/catalog.py`: `TOOL_SCOPE` and `READ_TOOLS`.
  - `api/remote/tools.py`: a `REMOTE_TOOLS` entry after `cicada_sources`.
  - `api/remote/runtime.py`: a `_DISPATCH` entry.
  - `api/tests/test_mcp_tools_context.py`: `MOVED` gains `"timeline"`.
- Test: `api/tests/test_change_timeline.py` (new).

**Interfaces:**
- Produces:
  - `change_timeline.DEFAULT_DAYS = 7`, `MAX_DAYS = 90`, `MAX_COMMITS = 1000`, `GIT_TIMEOUT_S = 3.0`
    and `IDS_PER_ROW = 5`
  - `Day`
  - `parse_since(raw, today) -> date`
  - `kind_of(subject) -> str | None`
  - `collect(memory_path, since, until, *, git_log=None) -> list[Day]`
  - `render(days, since, until) -> str`
  - `mcp_tools.timeline(ctx, since=None) -> str`
  - the tool `cicada_timeline` (remote scope `read`)
- Consumes: `git_service.parse_cycle_body`, `bank_index.files` and `episode_ids.timestamp_sort_key`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_change_timeline.py`:

```python
"""G140 Q-R4 (R3 P6) — `cicada_timeline`: what changed in memory, read from
git on demand. A synthetic bank whose commits carry the manifests Cicada's
writers produce, with fixed dates; no network, nothing stored."""
from __future__ import annotations

import os
import subprocess
from datetime import date

import pytest

from _stdio_server import stdio_server
from api.remote import catalog
from api.services import change_timeline, markdown_parser

D1, D2 = "2026-09-20", "2026-09-21"


def _git(repo, *args, when: str | None = None):
    env = dict(os.environ)
    if when:
        env.update(GIT_AUTHOR_DATE=f"{when}T00:30:00+00:00", GIT_COMMITTER_DATE=f"{when}T00:30:00+00:00")
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _commit(repo, message: str, when: str):
    _git(repo, "commit", "-q", "--allow-empty", "-m", message, when=when)


def _repo(path):
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        _git(path, *args)


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    _repo(memory)
    _commit(memory, "Sleep cycle 2026-09-20\n\n"
            "entities/alpha-project.md: created (source: ep_2026-09-20_001, trigger: sleep/extraction)\n"
            "entities/bob-example.md: updated (source: ep_2026-09-20_001, trigger: sleep/extraction)\n\n"
            "Cicada-Author: gpt-5.4-mini\nCicada-Engine: litellm\nCicada-Session: ses_2026-09-20_abcd1234", D1)
    _commit(memory, "Sleep cycle 2026-09-20 (decay)\n\n"
            "entities/beta-project.md: archive (source: n/a, trigger: sleep/decay)\n"
            "entities/gamma-concept.md: decay (source: n/a, trigger: sleep/decay)\n\nCicada-Author: cicada", D1)
    _commit(memory, "State snapshot 2026-09-20\n\n_state.md: updated (trigger: sleep/state)\n\n"
            "Cicada-Author: cicada", D1)
    _commit(memory, "Agent write 2026-09-21\n\n"
            "entities/alpha-project.md: updated (source: n/a, trigger: mcp/claude-code)\n\n"
            "Cicada-Author: claude-code\nCicada-Session: 11111111-2222-4333-8444-555555555555", D2)
    _commit(memory, "Inbox resolution 2026-09-21\n\n"
            "inbox/inbox-001.md: resolved (trigger: inbox/decay/resolved:keep)\n\nCicada-Author: user", D2)
    markdown_parser.write(memory / "episodes" / "ep_2026-09-21_001.md",
                          {"id": "ep_2026-09-21_001", "timestamp": "2026-09-21T12:00:00+00:00",
                           "origin": "claude-code", "title": "A private title"}, "user: something private")
    return memory


def test_days_are_read_from_the_commit_manifests(bank):
    days = change_timeline.collect(bank, date(2026, 9, 19), date(2026, 9, 22))
    assert [d.day.isoformat() for d in days] == [D2, D1], "newest day first"
    d2, d1 = days
    assert d1.created == ["alpha-project"] and d1.updated == 1 and d1.consolidations == 1
    assert d1.authors == ["gpt-5.4-mini"] and d1.conversations == {"ses_2026-09-20_abcd1234"}
    assert d1.archived == ["beta-project"] and d1.faded == 1
    assert dict(d2.agent_writes) == {"claude-code": 1} and d2.answered == 1
    assert dict(d2.captured) == {"claude-code": 1}


def test_a_state_snapshot_is_not_a_change(bank):
    (d1,) = change_timeline.collect(bank, date(2026, 9, 20), date(2026, 9, 20))
    assert d1.consolidations == 1, "the Sleep cycle, never the State snapshot"
    assert change_timeline.kind_of("State snapshot 2026-09-20") is None


def test_the_reply_is_ids_and_counts_only(bank):
    since, until = date(2026, 9, 19), date(2026, 9, 22)
    text = change_timeline.render(change_timeline.collect(bank, since, until), since, until)
    assert text.index("## 2026-09-21") < text.index("## 2026-09-20")
    assert "`alpha-project`" in text and "`beta-project`" in text
    assert "A private title" not in text and "something private" not in text
    assert "ses_2026" not in text and "11111111" not in text, "conversations are counted, never named"


def test_since_is_a_date_or_a_number_of_days_and_is_clamped():
    today = date(2026, 9, 23)
    assert change_timeline.parse_since(None, today) == date(2026, 9, 16)
    assert change_timeline.parse_since("3", today) == date(2026, 9, 20)
    assert change_timeline.parse_since(3, today) == date(2026, 9, 20)
    assert change_timeline.parse_since("3d", today) == date(2026, 9, 20)
    assert change_timeline.parse_since("2026-09-01", today) == date(2026, 9, 1)
    assert change_timeline.parse_since("2020-01-01", today) == date(2026, 6, 25), "MAX_DAYS back"
    assert change_timeline.parse_since("2027-01-01", today) == today
    assert change_timeline.parse_since("soon", today) == date(2026, 9, 16)


def test_no_git_and_an_empty_window_never_raise(tmp_path):
    memory = tmp_path / "plain"
    (memory / "episodes").mkdir(parents=True)
    assert change_timeline.collect(memory, date(2026, 9, 1), date(2026, 9, 2)) == []
    assert change_timeline.render([], date(2026, 9, 1), date(2026, 9, 2)).startswith("Nothing changed")


def test_a_bank_inside_another_repo_never_reads_that_repo(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    _repo(outer)
    _commit(outer, "Sleep cycle 2026-09-20\n\nentities/x.md: created (source: n/a, trigger: sleep/extraction)", D1)
    memory = outer / "bank"
    (memory / "episodes").mkdir(parents=True)
    assert change_timeline.collect(memory, date(2026, 9, 19), date(2026, 9, 22)) == []


def test_the_tool_is_wired_on_stdio_and_read_scope_remotely(bank, monkeypatch):
    today = date.today().isoformat()
    _commit(bank, f"Agent write {today}\n\nentities/alpha-project.md: updated (source: n/a, "
                  "trigger: mcp/codex)\n\nCicada-Author: codex", today)
    srv = stdio_server()
    monkeypatch.setattr(srv, "get_memory_path", lambda: bank)
    out = srv.handle_tool("cicada_timeline", {"since": "1"})
    assert f"## {today}" in out and "codex 1" in out
    assert {t["name"] for t in srv.TOOLS} >= {"cicada_timeline"}
    assert catalog.TOOL_SCOPE["cicada_timeline"] == "read" and "cicada_timeline" in catalog.READ_TOOLS
    assert "cicada_timeline" in catalog.tool_names_for({"read"})
```

- [ ] **Step 2:** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_change_timeline.py -q -p no:cacheprovider`.
  Expect failure: `change_timeline` does not exist.
- [ ] **Step 3: Implement.** Create `api/services/change_timeline.py`:

```python
"""``cicada_timeline(since)`` — what changed in memory, read from git on demand (G140 Q-R4, R3 P6).

Instinct keeps ``timeline/daily`` and ``timeline/weekly`` folders, and the
article's replication demos "what changed recently?". Cicada already holds the
answer in machine-parseable form: every writer commits one manifest line per
file (``<path>: <action> (source: …, trigger: …)``) under a subject that
names the writer, above its ``Cicada-*`` trailers. So this module READS the
history and stores nothing — no file in the bank (a second timeline is the
redundant, stale copy the article itself reports), no cache (the
``sleep.next_at`` precedent: a clock-shaped answer is computed per request).

Rails:
* **Engine-free and bounded.** One ``git log`` with ``-n MAX_COMMITS`` and a
  timeout; bodies are parsed HERE by ``git_service.parse_cycle_body`` and
  never sent anywhere (``get_sleep_history``'s lesson: ``%b`` over the wire
  grew one endpoint to 378 KB). Captures come from ``bank_index``'s
  frontmatter cache.
* **Ids and counts only.** No episode title, no claim text, no conversation
  id leaves this module — a remote connection holding only ``read`` must not
  receive the person's words (G135: that is the ``sources`` scope).
* **Its own repo or nothing.** A bank that is not a git root is never read:
  ``git`` would otherwise climb into whatever repo encloses it (the
  ``agent_commits`` rule).
* **Never raises.** No git, a timeout, a garbled body — each is fewer rows.
"""
from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from api.services import bank_index, episode_ids, git_service

DEFAULT_DAYS = 7
MAX_DAYS = 90
MAX_COMMITS = 1000
GIT_TIMEOUT_S = 3.0
IDS_PER_ROW = 5
_SEP, _REC = "\x1f", "\x1e"


@dataclass
class Day:
    """One day of change, as counts and page ids (never text)."""

    day: date
    captured: Counter = field(default_factory=Counter)       # episode origin -> episodes
    consolidations: int = 0
    authors: list[str] = field(default_factory=list)         # models that ran Sleep
    conversations: set = field(default_factory=set)          # counted, never rendered
    created: list[str] = field(default_factory=list)
    updated: int = 0
    archived: list[str] = field(default_factory=list)
    faded: int = 0
    expired: list[str] = field(default_factory=list)
    agent_writes: Counter = field(default_factory=Counter)   # author -> commits
    retracted: int = 0
    answered: int = 0

    def empty(self) -> bool:
        return not (self.captured or self.consolidations or self.archived or self.faded or self.expired
                    or self.agent_writes or self.answered)


def parse_since(raw, today: date) -> date:
    """``since`` as an agent sends it: a date (``2026-09-16``), a number of
    days (``7``, ``"7d"``), or nothing (``DEFAULT_DAYS``). Clamped to
    ``MAX_DAYS`` back and never after today; anything unreadable is the default."""
    start = today - timedelta(days=DEFAULT_DAYS)
    value = "" if raw is None or isinstance(raw, bool) else str(raw).strip().lower()
    if value:
        digits = value[:-1] if value.endswith("d") else value
        if digits.isdigit():
            start = today - timedelta(days=int(digits))
        else:
            try:
                start = date.fromisoformat(value[:10])
            except ValueError:
                pass
    return min(max(start, today - timedelta(days=MAX_DAYS)), today)


def kind_of(subject: str) -> str | None:
    """Which writer made a commit, from its subject. ``None`` = not a change
    worth reporting (the ``State snapshot`` projection)."""
    s = (subject or "").strip().lower()
    if s.startswith("state snapshot"):
        return None
    if s.startswith("sleep cycle"):
        return "decay" if s.endswith("(decay)") else "sleep"
    if s.startswith("expiry"):
        return "expiry"
    if s.startswith("inbox resolution"):
        return "inbox"
    if s.startswith(("agent write", "remote write")):
        return "agent"
    return "other"


def _git_log(memory_path: Path, since: date, until: date) -> str | None:
    """git's ``--since``/``--until`` read LOCAL time while a commit's ``%ad``
    carries its own zone, so the window is padded a day each side and
    ``collect`` cuts it on the commit's own date — the same day the Sleep
    page shows (``get_sleep_history`` reads ``%ad`` too)."""
    try:
        proc = subprocess.run(
            ["git", "log", f"-n{MAX_COMMITS}", f"--since={(since - timedelta(days=1)).isoformat()}",
             f"--until={(until + timedelta(days=1)).isoformat()}T23:59:59", "--date=iso-strict",
             f"--format=%H{_SEP}%ad{_SEP}%s{_SEP}%b{_REC}"],
            cwd=str(memory_path), capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _local_day(raw) -> date | None:
    """An episode timestamp of any stored shape as a LOCAL calendar day
    (G114: legacy naive, ``Z`` and ``+00:00`` coexist; YAML may hand back a
    ``datetime``)."""
    if isinstance(raw, datetime):
        dt = raw
    else:
        key = episode_ids.timestamp_sort_key(str(raw) if raw else None)
        if not key:
            return None
        try:
            dt = datetime.fromisoformat(key)
        except ValueError:
            return None
    try:
        return dt.astimezone().date()
    except (ValueError, OverflowError, OSError):
        return None


def collect(memory_path: Path, since: date, until: date, *,
            git_log: Callable[[Path, date, date], str | None] | None = None) -> list[Day]:
    """Every day in ``[since, until]`` that had a change, newest first."""
    memory_path = Path(memory_path)
    days: dict[date, Day] = {}

    def row(d: date) -> Day:
        return days.setdefault(d, Day(d))

    raw = (git_log or _git_log)(memory_path, since, until) if (memory_path / ".git").exists() else None
    for record in (raw or "").split(_REC):
        fields = record.strip("\n").split(_SEP, 3)
        if len(fields) < 4:
            continue
        kind = kind_of(fields[2])
        if kind is None or kind == "other":
            continue
        try:
            d = date.fromisoformat(fields[1].strip()[:10])
        except ValueError:
            continue
        if not since <= d <= until:
            continue
        m = git_service.parse_cycle_body(fields[2], fields[3])
        r = row(d)
        if kind == "sleep":
            r.consolidations += 1
            r.conversations.update(m.sessions)
            r.authors += [a for a in m.authors if a not in r.authors]
            for e in m.entities:
                if e["action"] == "created":
                    r.created.append(e["id"])
                else:
                    r.updated += 1
        elif kind == "decay":
            for e in m.entities:
                if e["action"] == "archive":   # conflict_resolver's action word
                    r.archived.append(e["id"])
                else:
                    r.faded += 1
        elif kind == "expiry":
            r.expired += [e["id"] for e in m.entities]
        elif kind == "inbox":
            r.answered += 1
        elif kind == "agent":
            for author in m.authors or ["agent"]:
                r.agent_writes[author] += 1
            r.retracted += sum(1 for e in m.entities if e["action"] == "retracted")
    for f in bank_index.files(memory_path, "episodes"):
        d = _local_day(f.frontmatter.get("timestamp"))
        if d is not None and since <= d <= until:
            row(d).captured[str(f.frontmatter.get("origin") or f.frontmatter.get("harness") or "unknown")] += 1
    return [days[d] for d in sorted(days, reverse=True) if not days[d].empty()]


def _ids(ids: list[str]) -> str:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return ""
    more = f" +{len(ids) - IDS_PER_ROW} more" if len(ids) > IDS_PER_ROW else ""
    return " (" + ", ".join(f"`{i}`" for i in ids[:IDS_PER_ROW]) + more + ")"


def _counted(counter: Counter) -> str:
    return ", ".join(f"{k} {n}" for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def render(days: list[Day], since: date, until: date) -> str:
    """The tool's reply: one section per day, ids and counts only."""
    span = f"{since.isoformat()} → {until.isoformat()}"
    if not days:
        return f"Nothing changed in memory between {span}."
    lines = [f"What changed in memory, {span} (newest day first; ids and counts only — "
             "open a page with cicada_recall_detail):"]
    for d in days:
        lines += ["", f"## {d.day.isoformat()}"]
        if d.captured:
            lines.append(f"- Captured {sum(d.captured.values())} episode(s): {_counted(d.captured)}")
        if d.consolidations:
            who = f" by {', '.join(d.authors)}" if d.authors else ""
            convs = f" from {len(d.conversations)} conversation(s)" if d.conversations else ""
            lines.append(f"- Sleep{who}{convs}: {len(d.created)} new page(s){_ids(d.created)}, "
                         f"{d.updated} updated")
        if d.archived or d.faded:
            lines.append(f"- Faded: {d.faded} page(s) lost confidence, {len(d.archived)} archived{_ids(d.archived)}")
        if d.expired:
            lines.append(f"- Reached their stated end: facts on {len(d.expired)} page(s){_ids(d.expired)}")
        if d.agent_writes:
            extra = f" ({d.retracted} withdrawal(s))" if d.retracted else ""
            lines.append(f"- Agent writes: {_counted(d.agent_writes)}{extra}")
        if d.answered:
            lines.append(f"- Questions answered in the inbox: {d.answered}")
    return "\n".join(lines)
```

  Then wire the tool in these places:
  - **`mcp_tools.py`**, after `sources`:

```python
def timeline(ctx: ToolContext, since=None) -> str:
    """``cicada_timeline`` (G140 Q-R4, R3 P6) — what changed, day by day, read
    from git on demand. See ``change_timeline``: nothing is stored, ids and
    counts only, no LLM."""
    from api.services import change_timeline

    today = date.today()
    start = change_timeline.parse_since(since, today)
    return change_timeline.render(change_timeline.collect(ctx.memory_path(), start, today), start, today)
```

  - **`mcp/server.py`**, in `TOOLS` after `cicada_handshake`:

```python
    {
        "name": "cicada_timeline",
        "description": "What changed in Cicada's memory recently, day by day, read from its git history: episodes captured per source, pages Sleep created or updated, pages that faded or were archived, facts that reached their stated end, agent writes (and withdrawals), and inbox questions answered. Ids and counts only — open a page with cicada_recall_detail. Use when the person asks what's new, what happened this week, or what you missed since you last talked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "Optional. A date (YYYY-MM-DD) or a number of days back (e.g. '7'). Default 7 days; at most 90.",
                },
            },
        },
    },
```

  - **`mcp/server.py`**, `handle_tool`: add `elif name == "cicada_timeline": return handle_timeline(arguments.get("since"))`,
    then add `def handle_timeline(since=None) -> str: return mcp_tools.timeline(_ctx(), since)` next to
    `handle_sources`.
  - **`api/remote/catalog.py`**: add `"cicada_timeline": "read",` to `TOOL_SCOPE`, and add
    `"cicada_timeline"` to `READ_TOOLS` (so its reply is fenced and capped).
  - **`api/remote/tools.py`**, after `cicada_sources` (the description names `cicada_recall_detail`,
    which shares the `read` scope):

```python
    _tool("cicada_timeline",
          "What changed in the person's memory recently, day by day: what was captured, the pages Cicada "
          "created or updated overnight, pages that faded, facts that reached their stated end, and what "
          "agents wrote. Ids and counts only — open a page with cicada_recall_detail.",
          {"since": {"type": "string", "description": "Optional: a date (YYYY-MM-DD) or a number of days "
                                                      "back. Default 7, at most 90."}},
          read_only=True),
```

  - **`api/remote/runtime.py`**, in `_DISPATCH`: `"cicada_timeline": lambda c, a: mcp_tools.timeline(c, a.get("since")),`.
  - **`test_mcp_tools_context.py`**: `MOVED` gains `"timeline"`.
- [ ] **Step 4: Green.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_change_timeline.py api/tests/test_remote_tools.py api/tests/test_remote_runtime.py api/tests/test_mcp_tools_context.py api/tests/test_handshake_remote.py api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`
  Everything must be green; the golden fixture is unchanged.
- [ ] **Step 5: Commit.** `feat(mcp): cicada_timeline — what changed, read from git on demand (G140 Q-R4, R3 P6)`.

### Task 3: `cicada_retract_claim` — an agent withdraws its own claim, and the reason is kept (R3 P7; Q-R5)

Instinct forgets explicit negations. Cicada closes a claim only when Sleep later extracts the
correction. This task gives the agent in the conversation a provenance-bearing way to withdraw what
**it** recorded. Nothing is deleted.

**Files:**
- Modify:
  - `api/services/agentic_write.py`: the import from `claim_reconciler` gains `is_human`; add
    `RETRACT_PREDICATE`, `MAX_REASON_CHARS`, `owns` and `retract_claim` after `write_claim`.
  - `api/services/mcp_tools.py`: `retract_claim`; `_is_record`; the withdrawn wording in
    `_history_line` and `_how_closed`; record claims filtered out of `_recent_changes` and
    `get_perspective`'s earlier list.
  - `mcp/server.py`: a `TOOLS` entry after `cicada_write_claim`, a `handle_tool` branch, and
    `handle_retract_claim`.
  - `api/remote/catalog.py`: `TOOL_SCOPE` and `WRITE_TOOLS`.
  - `api/remote/tools.py`: a `REMOTE_TOOLS` entry after `cicada_write_claim`.
  - `api/remote/runtime.py`: a `_DISPATCH` entry.
  - `api/tests/test_mcp_tools_context.py`: `MOVED` gains `"retract_claim"`.
- Test: `api/tests/test_retract_claim.py` (new).

**Interfaces:**
- Produces:
  - `agentic_write.owns(claim, *, author, origin) -> bool`
  - `agentic_write.retract_claim(memory_path, subject, claim_id, *, reason, author, origin=None, session_id=None, evidence=None, today=None) -> dict`
    - `action` is one of `retracted | already_closed | not_found | not_yours | error`.
  - `mcp_tools.retract_claim(ctx, subject, claim_id, reason, evidence=None) -> str`
  - the tool `cicada_retract_claim` (remote scope `record`)
- Consumes: `claim_reconciler.is_human`, `evidence.verify_many`, `agent_commits.commit_write` and
  `telemetry.record`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_retract_claim.py`:

```python
"""G140 Q-R5 (R3 P7) — an agent withdraws a claim IT wrote; the claim is kept
as history, a record keeps the reason, nothing is deleted. Synthetic bank."""
from __future__ import annotations

import re
import subprocess
from datetime import date

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import change_timeline, markdown_parser, mcp_tools
from api.services.claims import Claim, parse_claims, write_claims

TODAY = date.today().isoformat()
REASON = "The person said the index moved to another engine."


def _claims(memory, eid="alpha-project") -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}


def _add(memory, claim: Claim, eid="alpha-project"):
    page = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter,
                          write_claims(parsed.body, [*parse_claims(parsed.body), claim]))


@pytest.fixture
def srv(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity("ses_retract_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    return server, memory


def _write(server, obj="sqlite-vec") -> str:
    reply = server.handle_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "uses", "object": obj})
    return re.search(r"claim `([^`]+)`", reply).group(1)


def _retract(server, claim_id, reason=REASON, **extra):
    return server.handle_tool("cicada_retract_claim",
                              {"subject": "alpha-project", "claim_id": claim_id, "reason": reason, **extra})


def test_an_agent_withdraws_its_own_claim_and_the_reason_is_kept(srv):
    server, memory = srv
    claim_id = _write(server)
    out = _retract(server, claim_id)
    assert out.startswith(f"Withdrew claim `{claim_id}` on `alpha-project`"), out
    claims = _claims(memory)
    target = claims[claim_id]
    record = claims[target.superseded_by]
    assert target.valid_to == TODAY
    assert (record.predicate, record.object, record.object_kind) == ("retracts", claim_id, "literal")
    assert record.valid_from == record.valid_to == TODAY, "born closed: history, never a belief"
    assert record.text == REASON and record.supersedes == claim_id and record.authored_by == "claude-code"
    assert [e.kind for e in record.evidence] == ["reasoning"]
    assert "sqlite-vec" not in server.handle_tool("cicada_get_perspective", {"subject": "alpha-project"})


def test_the_withdrawal_is_committed_under_the_agent_and_counted_by_the_timeline(srv):
    server, memory = srv
    _retract(server, _write(server))
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%s%n%b"],
                         capture_output=True, text=True, check=True).stdout
    assert "entities/alpha-project.md: retracted (source: n/a, trigger: mcp/claude-code)" in log
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_retract_fixed" in log
    (day,) = change_timeline.collect(memory, date.today(), date.today())
    assert day.retracted == 1


def test_twice_is_a_no_op(srv):
    server, memory = srv
    claim_id = _write(server)
    _retract(server, claim_id)
    before = (memory / "entities" / "alpha-project.md").read_text()
    assert "already stopped being current" in _retract(server, claim_id)
    assert (memory / "entities" / "alpha-project.md").read_text() == before


@pytest.mark.parametrize("claim", [
    Claim(id="clm_sleep", text="alpha uses duckdb", subject="alpha-project", predicate="uses", object="duckdb",
          authored_by="gpt-5.4-mini", origin="claude-code", valid_from="2026-09-01"),
    Claim(id="clm_person", text="alpha is mine", subject="alpha-project", predicate="owned-by", object="owner",
          observer="owner", source_trust="user_stated", origin="manual_edit", authored_by="claude-code",
          valid_from="2026-09-01"),
    Claim(id="clm_other_app", text="alpha uses redis", subject="alpha-project", predicate="uses", object="redis",
          authored_by="claude-code", origin="remote:zz99zz99", valid_from="2026-09-01"),
], ids=["sleep", "the-person", "a-remote-app"])
def test_a_claim_this_agent_did_not_write_is_refused(srv, claim):
    server, memory = srv
    _add(memory, claim)
    before = (memory / "entities" / "alpha-project.md").read_text()
    assert "was not written by this agent" in _retract(server, claim.id)
    assert (memory / "entities" / "alpha-project.md").read_text() == before


def test_a_pre_g135_local_claim_can_be_withdrawn_by_a_local_agent(srv):
    server, memory = srv
    _add(memory, Claim(id="clm_legacy", text="alpha uses faiss", subject="alpha-project", predicate="uses",
                       object="faiss", authored_by="mcp-agentic-write", origin="mcp", valid_from="2026-08-01"))
    assert _retract(server, "clm_legacy").startswith("Withdrew")


def test_a_reason_is_required(srv):
    server, memory = srv
    claim_id = _write(server)
    assert "a reason is required" in _retract(server, claim_id, reason="   ")
    assert _claims(memory)[claim_id].valid_to is None


def test_the_persons_words_become_the_records_evidence(srv):
    server, memory = srv
    claim_id = _write(server)
    _retract(server, claim_id, evidence=[{"episode": "ep_2026-09-02_001", "quote": "ship alpha"}])
    record = _claims(memory)[_claims(memory)[claim_id].superseded_by]
    assert [e.kind for e in record.evidence] == ["user"]


def test_history_says_withdrawn(srv, monkeypatch):
    server, memory = srv
    monkeypatch.setattr(server.mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    claim_id = _write(server)
    _retract(server, claim_id)
    full = server.handle_tool("cicada_get_perspective", {"subject": "alpha-project", "history": True})
    assert f"withdrawn by claude-code: {REASON}" in full
    # The count is what pins the filter: a listed record would render as its
    # reason text with "closed", and never print the word `retracts`.
    assert "Earlier, newest first (1):" in full, "a record is bookkeeping, never listed as a belief"
    lines = mcp_tools._recent_changes(memory / "entities", [{"entity_id": "alpha-project"}], date.today())
    assert lines == [f'- `alpha-project` uses: "sqlite-vec" withdrawn {TODAY} by claude-code — {REASON}']


def test_a_connection_can_only_withdraw_what_it_wrote(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        runtime = RemoteRuntime(post=lambda path, payload: {}, sleep_running=lambda: False)
        mine = catalog.Connector(id="aaaaaaaa", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                 created_at="2026-09-01T00:00:00+00:00")
        theirs = catalog.Connector(id="bbbbbbbb", label="Laptop", app="chatgpt", scopes=catalog.DEFAULT_SCOPES,
                                   created_at="2026-09-01T00:00:00+00:00")
        text, _ = runtime.call(mine, "cicada_write_claim",
                               {"subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec"})
        claim_id = re.search(r"claim `([^`]+)`", text).group(1)
        args = {"subject": "alpha-project", "claim_id": claim_id, "reason": REASON}
        assert "was not written by this agent" in runtime.call(theirs, "cicada_retract_claim", args)[0]
        assert runtime.call(mine, "cicada_retract_claim", args)[0].startswith("Withdrew")
    finally:
        config.get_settings.cache_clear()
    assert catalog.TOOL_SCOPE["cicada_retract_claim"] == "record"
    assert "cicada_retract_claim" in catalog.WRITE_TOOLS
```

- [ ] **Step 2:** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_retract_claim.py -q -p no:cacheprovider`.
  Expect failure: unknown tool `cicada_retract_claim`.
- [ ] **Step 3: Implement.**
  - **`agentic_write.py`**: change `from api.services.claim_reconciler import reconcile_stage3` to
    `from api.services.claim_reconciler import is_human, reconcile_stage3`, and add after
    `write_claim`:

```python
RETRACT_PREDICATE = "retracts"
MAX_REASON_CHARS = 240
# Every stdio MCP claim written before G135 R-R11 carried this author: the
# reconcile shim's model name, stamped by `_stamp_new`. Any local agent could
# have written it, so any local agent may withdraw it (Q-R5).
_LEGACY_MCP_AUTHOR = _ReconcileSettings.litellm_model


def owns(claim: Claim, *, author: str, origin: str | None) -> bool:
    """May this caller withdraw ``claim``? Only its own (G140 Q-R5).

    A remote connection owns exactly the claims stamped ``remote:<its id>``
    (R-R23); a local agent owns what its harness label authored, or the
    pre-G135 placeholder, and never a remote app's. Nobody but the person
    withdraws a human claim — ``is_human`` is the same protection Stage 3
    gives it — and a Sleep claim's author is a model id, so it never matches.
    """
    if is_human(claim):
        return False
    claim_origin = claim.origin or ""
    if origin and origin.startswith("remote:"):
        return claim_origin == origin
    if claim_origin.startswith("remote:"):
        return False
    return (claim.authored_by or "") in {author, _LEGACY_MCP_AUTHOR}


def retract_claim(
    memory_path: Path,
    subject: str,
    claim_id: str,
    *,
    reason: str,
    author: str,
    origin: str | None = None,
    session_id: str | None = None,
    evidence: list[dict] | None = None,
    today: date | None = None,
) -> dict:
    """Withdraw one claim this caller wrote, keeping it as history (G140 Q-R5, R3 P7).

    Instinct forgets an explicit negation; Cicada only ever closed a claim
    when Sleep later extracted the correction, so an agent that recorded
    something wrong could not say so. This closes the TARGET the way Stage 3
    does (``valid_to`` = today, ``superseded_by`` = the record) and appends a
    RECORD claim that holds the why: ``predicate: retracts``, ``object`` = the
    target id, ``text`` = the reason, ``evidence`` = the caller's verified
    quotes (the person's "that's wrong") or ``reasoning``. The record is born
    closed (``valid_from == valid_to``) — history, never a current belief —
    and nothing is deleted. Never raises.
    """
    reason = " ".join(str(reason or "").split())[:MAX_REASON_CHARS]
    if not reason:
        return {"action": "error", "error": "a reason is required — say why the claim is wrong; nothing was changed"}
    memory_path = Path(memory_path)
    page = resolve_entity_file(memory_path, (subject or "").strip())
    if page is None or not page.exists():
        return {"action": "not_found", "error": f"no page for subject {subject!r}"}
    try:
        parsed = markdown_parser.parse(page)
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        return {"action": "error", "error": f"the page's claims block is unreadable ({exc}); nothing was changed"}
    except Exception as exc:  # noqa: BLE001 — a bad page is an error reply, never a crashed tool
        return {"action": "error", "error": f"the page could not be read ({type(exc).__name__}); nothing was changed"}
    target = next((c for c in claims if c.id == claim_id), None)
    if target is None:
        return {"action": "not_found", "entity_id": page.stem, "error": f"no claim {claim_id!r} on {page.stem}"}
    if target.valid_to is not None:
        return {"action": "already_closed", "entity_id": page.stem, "claim_id": claim_id,
                "valid_to": target.valid_to}
    if not owns(target, author=author, origin=origin):
        return {"action": "not_yours", "entity_id": page.stem, "claim_id": claim_id}
    day = (today or date.today()).isoformat()
    spans = evidence_mod.verify_many(memory_path, evidence) or [evidence_mod.reasoning("")]
    record = Claim(
        id=f"clm_retract_{hashlib.sha1(claim_id.encode('utf-8')).hexdigest()[:8]}",
        text=reason,
        subject=target.subject or page.stem,
        predicate=RETRACT_PREDICATE,
        object=target.id,
        object_kind="literal",
        observer=target.observer,
        context=target.context,
        epistemic="explicit",
        source_trust=target.source_trust,
        confidence=1.0,
        valid_from=day,
        valid_to=day,
        supersedes=target.id,
        recorded_at=day,
        authored_by=author,
        origin=origin or target.origin,
        session_id=(session_id or "").strip() or None,
        evidence=spans,
    )
    target.valid_to = day
    target.superseded_by = record.id
    try:
        markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, [*claims, record]))
    except OSError as exc:
        return {"action": "error", "error": f"the page could not be written ({type(exc).__name__}); nothing was changed"}
    return {"action": "retracted", "entity_id": page.stem, "claim_id": claim_id, "record_id": record.id,
            "path": f"entities/{page.name}", "evidence": [e.to_dict() for e in spans]}
```

  - **`mcp_tools.py`**:
    1. After `write_claim`:

```python
def retract_claim(ctx: ToolContext, subject: str, claim_id: str, reason: str, evidence: list | None = None) -> str:
    """``cicada_retract_claim`` (G140 Q-R5, R3 P7): withdraw a claim THIS caller
    wrote. The claim stays in its page's history, a record keeps the reason,
    and the page commits alone under the caller — like ``write_claim``."""
    memory_path = ctx.memory_path()
    result = agentic_write.retract_claim(
        memory_path, subject, (claim_id or "").strip(), reason=reason, author=ctx.author,
        origin=ctx.claim_origin, session_id=ctx.session_id, evidence=evidence,
    )
    action = result.get("action")
    if action == "already_closed":
        return (f"Claim `{claim_id}` on `{result['entity_id']}` already stopped being current on "
                f"{result['valid_to']}; nothing changed.")
    if action == "not_found":
        return f"No claim `{claim_id}` on '{subject}' — use the claim id cicada_write_claim returned."
    if action == "not_yours":
        return (f"Claim `{claim_id}` was not written by this agent, so it can't be withdrawn here. Record the "
                "correction as a new claim with cicada_write_claim, or let the person answer it in the Cicada app.")
    if action != "retracted":
        return f"Could not withdraw the claim: {result.get('error', 'unknown error')}"

    from api.services import telemetry

    refs = {"entity_id": result["entity_id"], "claim_id": claim_id, "episode_id": None, "action": "retracted",
            "session_id": ctx.session_id, "harness": ctx.harness, "client_name": ctx.client_name,
            "client_version": ctx.client_version}
    if ctx.is_remote:
        refs["connector_id"] = ctx.connector_id
    telemetry.record(telemetry.UsageEvent(
        kind="agentic_write", stage="driver", connection="session",
        engine="mcp-remote" if ctx.is_remote else "mcp-client",
        model=None, bank=memory_path.name, billing="subscription", invocations=1, refs=refs,
    ))
    if not ctx.sleep_running():
        agent_commits.commit_write(
            memory_path, subject=ctx.commit_subject,
            lines=[f"{result['path']}: retracted (source: n/a, trigger: {ctx.trigger})"],
            paths=[result["path"]], author=ctx.author, session=ctx.session_id,
        )
    cited = sum(1 for e in result.get("evidence") or [] if e.get("kind") != "reasoning")
    ev = f"{cited} quote verified" if cited else "reasoning"
    return (f"Withdrew claim `{claim_id}` on `{result['entity_id']}`. It stays in history with your reason "
            f"(record `{result['record_id']}`, evidence: {ev}); nothing was deleted.")
```

    2. In the history helpers, add `_is_record` above `_how_closed`:

```python
def _is_record(claim) -> bool:
    """A withdrawal record (``cicada_retract_claim``) is bookkeeping about a
    claim, never a belief of its own, so no history list shows it."""
    return claim.predicate == agentic_write.RETRACT_PREDICATE
```

    3. Each of `_how_closed` and `_history_line` gains a first branch after `new` is looked up:

```python
    # in _how_closed:
    if new is not None and _is_record(new):
        return f"withdrawn by {new.authored_by or 'an agent'}: {_clip(new.text, 160)}"
    # in _history_line:
    if new is not None and _is_record(new):
        return f"{head} {was} withdrawn {old.valid_to} by {new.authored_by or 'an agent'} — {_clip(new.text, 160)}"
```

    4. In `_recent_changes`, the `if age is not None and …` test gains `and not _is_record(c)`. In
       `get_perspective`, the `earlier = [...]` comprehension gains `and not _is_record(c)`.
  - **`mcp/server.py`**, in `TOOLS` after `cicada_write_claim` (`handle_tool`: `elif name == "cicada_retract_claim": return handle_retract_claim(arguments.get("subject", ""), arguments.get("claim_id", ""), arguments.get("reason", ""), arguments.get("evidence"))`,
    and `def handle_retract_claim(subject, claim_id, reason, evidence=None) -> str: return mcp_tools.retract_claim(_ctx(), subject, claim_id, reason, evidence)`):

```python
    {
        "name": "cicada_retract_claim",
        "description": "Withdraw ONE claim you wrote earlier with cicada_write_claim that turned out to be wrong — for example the person says 'that's not right' about something you recorded. Nothing is deleted: the claim stops being current, stays in its page's history, and a record keeps your reason (and, when you cite them, the person's exact words). You can only withdraw a claim this agent wrote — never one the person stated, one Sleep extracted, or another agent's; for those, record the correction as a new claim with cicada_write_claim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The entity the claim is on (the `entity` cicada_write_claim returned)."},
                "claim_id": {"type": "string", "description": "The claim id cicada_write_claim returned (e.g. 'clm_alpha-project_uses_38309bd1')."},
                "reason": {"type": "string", "description": "Why it is wrong, in one sentence (at most 240 characters)."},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "episode": {"type": "string", "description": "The episode the words are in."},
                            "quote": {"type": "string", "description": "The exact words, copied verbatim (at most 240 characters)."},
                        },
                        "required": ["episode", "quote"],
                    },
                    "description": "Optional. The person's exact words showing it is wrong, from a saved episode — verified and stored as offsets, never copied.",
                },
            },
            "required": ["subject", "claim_id", "reason"],
        },
    },
```

  - **`api/remote/catalog.py`**: `"cicada_retract_claim": "record",` in `TOOL_SCOPE`, and add it to
    `WRITE_TOOLS` (the write lock and the Sleep gate).
  - **`api/remote/tools.py` module docstring.** Its "No tool is destructive: nothing deletes or
    edits in place." gains: "`cicada_retract_claim` closes a claim this connection wrote and keeps
    it, with the reason, as history (G140 Q-R5): its validity changes, its words never do." Do
    **not** touch `handshake._remote_capabilities`' "Can't delete or rewrite." (Q-R14: it is
    pinned against Swift).
  - **`api/remote/tools.py`**, after `cicada_write_claim`:

```python
    _tool("cicada_retract_claim",
          "Withdraw a fact this connection recorded earlier with cicada_write_claim and now knows is wrong. "
          "The fact stays in history with your reason; nothing is deleted. Only facts this connection wrote "
          "can be withdrawn.",
          {"subject": {"type": "string", "description": "The page the fact is on."},
           "claim_id": {"type": "string", "description": "The claim id cicada_write_claim returned."},
           "reason": {"type": "string", "description": "Why it is wrong, in one sentence."},
           "evidence": {"type": "array", "description": "Optional: the person's exact words showing it is wrong.",
                        "items": {"type": "object", "required": ["episode", "quote"], "properties": {
                            "episode": {"type": "string",
                                        "description": "The episode id cicada_save_episode returned."},
                            "quote": {"type": "string",
                                      "description": "The exact words, copied verbatim (at most 240 characters)."},
                        }}}},
          ("subject", "claim_id", "reason"), read_only=False, idempotent=True),
```

  - **`api/remote/runtime.py`** `_DISPATCH`: `"cicada_retract_claim": lambda c, a: mcp_tools.retract_claim(c, str(a.get("subject") or ""), str(a.get("claim_id") or ""), str(a.get("reason") or ""), a.get("evidence")),`.
  - **`test_mcp_tools_context.py`**: `MOVED` gains `"retract_claim"`.
- [ ] **Step 4: Green.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_retract_claim.py api/tests/test_mcp_recall_legs.py api/tests/test_agentic_write.py api/tests/test_agent_write_commits.py api/tests/test_remote_tools.py api/tests/test_remote_runtime.py api/tests/test_mcp_tools_context.py api/tests/test_run_events.py api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`
  Everything must be green.
- [ ] **Step 5: Commit.** `feat(mcp): cicada_retract_claim — withdraw your own claim, keep the reason (G140 Q-R5, R3 P7)`.

### Task 4: A fact with a stated end stops being current at that end (R3 P8; Q-R6, Q-R7)

"Exams this weekend" should not survive three weeks of volatile decay. A claim gains an optional
**stated end**, and Sleep's engine-free tail closes it the day after. A G17 `due` date is its own
stated end.

**Files:**
- Modify:
  - `api/services/claims.py`: `Claim.expected_end`, appended after `evidence`; `to_dict` omits it
    when unset; `from_dict` reads it.
  - `api/services/claim_reconciler.py`: `_reinforce`.
  - `api/services/agentic_write.py`: `write_claim(expected_end=)`, `_iso_date`.
  - `api/services/mcp_tools.py`: `write_claim(..., expected_end=None)` and its reply; the *ended*
    wording in `_history_line` and `_how_closed`.
  - `mcp/server.py`: the `cicada_write_claim` schema property, the `handle_tool` branch, and
    `handle_write_claim`.
  - `api/remote/tools.py`: the `cicada_write_claim` property.
  - `api/remote/runtime.py`: the `cicada_write_claim` dispatch.
  - `api/services/sleep_cycle.py`: `_expire_claims_safely`, and the tail's guarded branch
    (`:745-753`) with its warning text.
- Create: `api/services/claim_expiry.py`.
- Test: `api/tests/test_claim_expiry.py` (new).

**Interfaces:**
- Produces:
  - `Claim.expected_end: str | None`
  - `claim_expiry.TRIGGER = "sleep/expiry"` and `AUTHOR = "cicada"`
  - `stated_end(claim) -> str | None`
  - `Report(paths, claims)`
  - `expire(memory_path, today) -> Report`
  - `commit_message(report, today) -> str`
  - `restore(memory_path, paths) -> None`
  - `sleep_cycle._expire_claims_safely(memory_path)`
  - `agentic_write.write_claim(..., expected_end=None)`, whose result gains `expected_end` and
    `expected_end_ignored`
  - the stdio and remote schema property `expected_end`
- Consumes: `git_service.commit_paths` and `build_commit_message`; `markdown_parser`; `claims`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_claim_expiry.py`:

```python
"""G140 Q-R6/Q-R7 (R3 P8) — a fact with a stated end stops being current at
that end: `expected_end`, or a G17 `due` date, closed by Sleep's engine-free
tail in its own `cicada` commit. Synthetic bank; no LLM, no network."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api.remote import tools as remote_tools
from api.services import claim_expiry, git_service, markdown_parser, mcp_tools, sleep_cycle
from api.services.claim_reconciler import _reinforce
from api.services.claims import Claim, parse_claims, write_claims

TODAY = date(2026, 9, 23)


def _page(memory: Path, eid: str, claims: list[Claim], body: str | None = None):
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": eid.replace("-", " ").title(), "type": "project", "status": "active"},
                          body if body is not None else write_claims("## Summary\nA page.\n", claims))


def _claims(memory: Path, eid: str) -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}


def _c(cid, **kw) -> Claim:
    kw.setdefault("subject", "alpha-project")
    kw.setdefault("predicate", "has")
    kw.setdefault("object", cid)
    kw.setdefault("valid_from", "2026-09-18")
    return Claim(id=cid, text=f"alpha {cid}", **kw)


def _git(memory: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def test_expected_end_round_trips_and_is_omitted_when_unset():
    claim = _c("c1", expected_end="2026-09-27")
    assert claim.to_dict()["expected_end"] == "2026-09-27"
    assert Claim.from_dict(claim.to_dict()).expected_end == "2026-09-27"
    assert "expected_end" not in _c("c2").to_dict(), "a legacy page never diffs"
    fence = "`" * 3
    body = f"{fence}claims\n- id: c3\n  text: t\n  expected_end: 2026-09-27\n{fence}\n"
    assert parse_claims(body)[0].expected_end == "2026-09-27", "YAML's date comes back as the ISO string"


def test_a_stated_end_that_has_passed_closes_the_claim(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("gone", expected_end="2026-09-20"),
                                    _c("today", expected_end="2026-09-23"),
                                    _c("open")])
    report = claim_expiry.expire(memory, TODAY)
    claims = _claims(memory, "alpha-project")
    assert claims["gone"].valid_to == "2026-09-20" and claims["gone"].superseded_by is None
    assert claims["today"].valid_to is None, "an end is inclusive: current through its own day"
    assert claims["open"].valid_to is None
    assert report.paths == ["entities/alpha-project.md"] and report.claims == [("alpha-project", "gone")]


def test_a_past_due_date_is_its_own_stated_end(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("due", predicate="due", object="2026-09-10", valid_from="2026-09-01"),
                                    _c("due-word", predicate="due", object="next-friday")])
    claim_expiry.expire(memory, TODAY)
    claims = _claims(memory, "alpha-project")
    assert claims["due"].valid_to == "2026-09-10"
    assert claims["due-word"].valid_to is None, "not a date, not an end"


def test_the_persons_own_stated_end_closes_too(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("mine", observer="owner", source_trust="user_stated",
                                       origin="manual_edit", expected_end="2026-09-20")])
    claim_expiry.expire(memory, TODAY)
    assert _claims(memory, "alpha-project")["mine"].valid_to == "2026-09-20", "Q-R7: the end is their statement"


def test_an_end_recorded_after_it_passed_never_closes_before_it_began(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("late", valid_from="2026-09-22", expected_end="2026-09-15"),
                                    _c("undated", valid_from="undated", expected_end="2026-09-15")])
    claim_expiry.expire(memory, TODAY)
    claims = _claims(memory, "alpha-project")
    assert claims["late"].valid_to == "2026-09-22"
    assert claims["undated"].valid_to == "2026-09-15", "a non-date valid_from never becomes valid_to"


def test_closed_claims_and_corrupt_pages_are_left_alone(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("done", expected_end="2026-09-20", valid_to="2026-09-19",
                                       superseded_by="x")])
    fence = "`" * 3
    corrupt = f"## Summary\nA page.\n\n{fence}claims\n- id: bad\n  expected_end: [unclosed\n{fence}\n"
    _page(memory, "beta-project", [], body=corrupt)
    before = (memory / "entities" / "beta-project.md").read_text()
    report = claim_expiry.expire(memory, TODAY)
    assert report.paths == []
    assert _claims(memory, "alpha-project")["done"].valid_to == "2026-09-19"
    assert (memory / "entities" / "beta-project.md").read_text() == before


def test_a_page_without_a_stated_end_is_never_parsed(tmp_path, monkeypatch):
    memory = tmp_path / "m"
    _page(memory, "plain", [_c("c", predicate="uses")])
    calls: list = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p: calls.append(p) or real(p))
    claim_expiry.expire(memory, TODAY)
    assert calls == []


def test_a_restated_end_replaces_the_old_one():
    existing = _c("a", expected_end="2026-09-20")
    _reinforce(existing, _c("a", expected_end="2026-09-27"))
    assert existing.expected_end == "2026-09-27"
    _reinforce(existing, _c("a"))
    assert existing.expected_end == "2026-09-27", "a restatement without an end keeps it"


def test_write_claim_takes_an_expected_end(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    out = server.handle_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "has",
                                                     "object": "exams", "expected_end": "2026-09-27"})
    assert "current through 2026-09-27" in out
    bad = server.handle_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "has",
                                                     "object": "a trip", "expected_end": "next week"})
    assert "expected_end ignored" in bad
    by_obj = {c.object: c for c in _claims(memory, "alpha-project").values()}
    assert by_obj["exams"].expected_end == "2026-09-27" and by_obj["a trip"].expected_end is None
    for props in ({t["name"]: t for t in server.TOOLS}["cicada_write_claim"]["inputSchema"]["properties"],
                  remote_tools.REMOTE_TOOLS["cicada_write_claim"]["inputSchema"]["properties"]):
        assert props["expected_end"]["type"] == "string"


def _git_bank(tmp_path) -> Path:
    memory = _bank(tmp_path)
    ended = (date.today() - timedelta(days=3)).isoformat()
    _page(memory, "alpha-project", [_c("gone", expected_end=ended, valid_from="2026-01-01")])
    _git(memory, "add", "entities/alpha-project.md")
    _git(memory, "commit", "-q", "-m", "seed a stated end")
    return memory


def test_the_tail_commits_expiry_alone_as_cicada(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _git_bank(tmp_path)
    asyncio.run(sleep_cycle._expire_claims_safely(memory))
    log = _git(memory, "log", "-1", "--format=%s%n%b")
    assert log.startswith(f"Expiry {date.today().isoformat()}")
    assert "entities/alpha-project.md: expired (source: n/a, trigger: sleep/expiry)" in log
    assert "Cicada-Author: cicada" in log and "Cicada-Engine" not in log
    assert _git(memory, "status", "--porcelain") == ""
    history = asyncio.run(git_service.get_sleep_history(memory, limit=10))
    assert not any(h.message.startswith("Expiry") for h in history), "the Sleep page lists consolidations"


def test_a_failed_expiry_commit_puts_the_pages_back(tmp_path, monkeypatch):
    memory = _git_bank(tmp_path)

    async def boom(*a, **k):
        raise git_service.GitError("index.lock is held")

    monkeypatch.setattr(git_service, "commit_paths", boom)
    asyncio.run(sleep_cycle._expire_claims_safely(memory))
    assert _git(memory, "status", "--porcelain") == "", "never left for the next `git add -A` writer"
    assert _claims(memory, "alpha-project")["gone"].valid_to is None, "re-derived tomorrow"


def _order(monkeypatch) -> list[str]:
    order: list[str] = []

    def fake(name):
        async def _f(*a, **k):
            order.append(name)
        return _f

    for name in ("_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely",
                 "_poll_feeds_and_calendars_safely", "_backfill_links_safely", "_warm_logos_safely",
                 "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, fake(name))
    return order


def test_expiry_runs_first_in_the_guarded_branch(monkeypatch):
    order = _order(monkeypatch)
    asyncio.run(sleep_cycle._run_engine_independent_tail(
        Path("/nonexistent"), SimpleNamespace(), sleep_cycle._StageOutcome(committed=True)))
    assert order[:3] == ["_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely"]


def test_expiry_never_runs_on_a_half_written_cycle(monkeypatch):
    order = _order(monkeypatch)

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    sleep_cycle._state.write_started = True
    try:
        asyncio.run(sleep_cycle._run_engine_independent_tail(
            Path("/nonexistent"), SimpleNamespace(), sleep_cycle._StageOutcome(committed=False)))
    finally:
        sleep_cycle._state.write_started = False
    assert "_expire_claims_safely" not in order


def test_history_says_a_fact_ended_at_its_stated_end(tmp_path):
    memory = tmp_path / "m"
    ended = (date.today() - timedelta(days=2)).isoformat()
    _page(memory, "alpha-project", [_c("exams", expected_end=ended, valid_from="2026-01-01", valid_to=ended)])
    lines = mcp_tools._recent_changes(memory / "entities", [{"entity_id": "alpha-project"}], date.today())
    assert lines == [f'- `alpha-project` has: "exams" ended {ended} (its stated end)']
```

- [ ] **Step 2:** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_claim_expiry.py -q -p no:cacheprovider`.
  Expect failure: no `expected_end` field and no `claim_expiry` module.
- [ ] **Step 3: Implement the claim field, reinforce and the writer.**
  - **`claims.py`**:
    - Add the last field of `Claim` (after `evidence`):

```python
    # G140 Q-R6 (R3 P8) — a STATED end: the date the fact itself says it stops
    # being true ("exams this weekend" → the Sunday; "until Friday"). NOT
    # `valid_to`, which thirteen readers take to mean CLOSED — a future date
    # there would hide the fact the day it was written. `claim_expiry` copies
    # it into `valid_to` once it has passed. Omitted from the YAML when unset
    # (G118 R7's reason: re-rendering a page must never diff every legacy
    # claim for a field it lacks).
    expected_end: str | None = None
```

    - `to_dict` also pops `expected_end` when it is `None`:
      `if data.get("expected_end") is None: data.pop("expected_end", None)`.
    - `from_dict` passes `expected_end=_opt_str(data.get("expected_end"))`.
  - **`claim_reconciler._reinforce`**: at the end:

```python
    # G140 Q-R6: a restatement that names an end is the newer statement of it;
    # one that names none leaves the known end alone.
    if incoming.expected_end:
        existing.expected_end = incoming.expected_end
```

  - **`agentic_write.py`**:
    - Add `_iso_date` above `write_claim`:

```python
def _iso_date(value) -> str | None:
    """``YYYY-MM-DD`` or ``None`` — a stated end is a date or it is nothing (G140 Q-R6)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None
```

    - `write_claim` gains the keyword parameter `expected_end: str | None = None`, with a docstring
      paragraph:
      ``` ``expected_end`` (G140 Q-R6): the date the fact says it ends, as YYYY-MM-DD; anything else is ignored — reported back, the claim still written. ```
    - Compute `end = _iso_date(expected_end)` before building `new_claim`, and pass
      `expected_end=end` into `Claim(...)`.
    - The success dict gains `"expected_end": end, "expected_end_ignored": bool(expected_end) and end is None`.
  - **`mcp_tools.write_claim`**:
    - Add `expected_end=None` as the last keyword parameter and pass `expected_end=expected_end` to
      `agentic_write.write_claim`.
    - Directly before the final `return`, add:

```python
    if result.get("expected_end"):
        ev_note += f"; current through {result['expected_end']}, then closed by Sleep"
    elif result.get("expected_end_ignored"):
        ev_note += "; expected_end ignored (use YYYY-MM-DD)"
```

      With no `expected_end`, the reply is byte-identical, and the golden `write_claim` key holds.
  - **`mcp/server.py`**:
    - In the `cicada_write_claim` properties, after `evidence`:

```python
                "expected_end": {
                    "type": "string",
                    "description": "Optional. The date this fact stops being true, when the person stated one — 'exams this weekend' → that Sunday, 'until Friday', a due date — as YYYY-MM-DD. The claim stays current through that day; Sleep closes it after. Nothing is deleted.",
                },
```

    - `handle_write_claim` gains `expected_end=None` and passes `expected_end=expected_end`.
    - The `handle_tool` branch passes `expected_end=arguments.get("expected_end")`.
  - **`api/remote/tools.py`**, in `cicada_write_claim`:
    `"expected_end": {"type": "string", "description": "Optional: the date this fact stops being true, if the person said (YYYY-MM-DD)."}`.
  - **`api/remote/runtime.py`**: the `cicada_write_claim` lambda passes `expected_end=a.get("expected_end")`.
- [ ] **Step 4: Implement the expiry.** Create `api/services/claim_expiry.py`:

```python
"""Facts with a stated end stop being current at that end (G140 Q-R6/Q-R7, R3 P8).

Supermemory expires temporary facts; Instinct keeps "exams this weekend"
until a model decides to remove it; Cicada's volatile class (G66) fades it
over weeks. A fact that STATES its end should close at that end. Two stated
ends exist, both explicit — nothing here reads prose, and no LLM runs:

* ``Claim.expected_end`` — written by an agent through ``cicada_write_claim``;
* a G17 ``due`` claim's own ISO-date object.

``expire`` closes every open claim whose end is strictly before today (an end
is inclusive — "until Friday" is current on Friday): ``valid_to`` = the end,
never earlier than ``valid_from``; no ``superseded_by``, because nothing
replaced it; nothing deleted. A person's own claim closes too — the end is
their own statement, so this is not an agent closing a human claim (Q-R7).

Sleep's engine-free tail calls it on every exit path, idle nights included
(an end is a date, not an episode), in the guarded branch, and commits the
result alone as ``cicada`` (the G85 shape). The subject is ``Expiry <date>``,
never ``Sleep cycle …``: the Sleep page's history rows are consolidations.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import git_service, markdown_parser
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

TRIGGER = "sleep/expiry"
AUTHOR = "cicada"
# A page with neither string cannot hold a stated end: skip it without a
# parse (most of a bank, every night).
_NEEDLES = ("expected_end:", "predicate: due")


def stated_end(claim: Claim) -> str | None:
    """The claim's own end as ``YYYY-MM-DD``, or ``None``."""
    candidates = (claim.expected_end, claim.object if claim.predicate == "due" else None)
    for raw in candidates:
        if not raw:
            continue
        try:
            return date.fromisoformat(str(raw).strip()[:10]).isoformat()
        except ValueError:
            continue
    return None


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)                 # memory-relative pages written
    claims: list[tuple[str, str]] = field(default_factory=list)    # (entity id, claim id) closed


def expire(memory_path: Path, today: date) -> Report:
    """Close every open claim whose stated end has passed. Never raises on a
    normal bank; a page whose claims block is unreadable is skipped, never
    rewritten (the strict-parse rule every read-modify-write path follows)."""
    report = Report()
    entities = Path(memory_path) / "entities"
    if not entities.is_dir():
        return report
    day = today.isoformat()
    for path in sorted(entities.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not any(needle in raw for needle in _NEEDLES):
            continue
        try:
            parsed = markdown_parser.parse(path)
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            logger.warning(f"expiry skipped {path.name}: unreadable claims block ({type(exc).__name__})")
            continue
        except Exception as exc:  # noqa: BLE001 — one bad page never stops the night
            logger.warning(f"expiry skipped {path.name}: {type(exc).__name__}")
            continue
        closed: list[str] = []
        for claim in claims:
            if claim.valid_to is not None or claim.superseded_by:
                continue
            end = stated_end(claim)
            if end is None or end >= day:
                continue
            # Never a window that closes before it opens. `valid_from` is only
            # trusted when it IS a date: a hand-edited "undated" would win a
            # string `max` and land in `valid_to`.
            try:
                began = date.fromisoformat(str(claim.valid_from or "")[:10]).isoformat()
            except ValueError:
                began = end
            claim.valid_to = max(end, began)
            closed.append(claim.id)
        if not closed:
            continue
        markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
        report.paths.append(f"entities/{path.name}")
        report.claims.extend((path.stem, cid) for cid in closed)
    return report


def commit_message(report: Report, today: date) -> str:
    return git_service.build_commit_message(
        f"Expiry {today.isoformat()}",
        [f"{p}: expired (source: n/a, trigger: {TRIGGER})" for p in report.paths],
        authors=[AUTHOR],
    )


def restore(memory_path: Path, paths: list[str]) -> None:
    """Put pages back as HEAD has them after a failed expiry commit (Q-R7).
    The expiry is re-derived tomorrow; a page left dirty would be stamped by
    the next ``git add -A`` writer under the wrong author — the G85 smear."""
    if not paths or not (Path(memory_path) / ".git").exists():
        return
    try:
        subprocess.run(["git", "checkout", "--", *paths], cwd=str(memory_path),
                       capture_output=True, timeout=10, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(f"expiry restore failed: {type(exc).__name__}")
```

  **`sleep_cycle.py`**:
  - Change `from datetime import datetime` (`:5`) to `from datetime import date, datetime`.
  - Add, after `_refresh_state_safely`:

```python
async def _expire_claims_safely(memory_path: Path) -> None:
    """G140 Q-R7 (R3 P8) — close facts whose stated end has passed, in one
    `cicada` commit. Time-driven, not episode-driven, so it lives on the tail
    and runs on idle nights too. Only in the guarded branch: `commit_paths`
    stages whole files, and on a half-written cycle it would take Sleep's
    uncommitted hunks on the same page. A failed commit restores the pages
    (see `claim_expiry.restore`). Never raises."""
    from api.services import claim_expiry

    today = date.today()
    try:
        report = await asyncio.to_thread(claim_expiry.expire, memory_path, today)
    except Exception as exc:
        logger.warning(f"Claim expiry failed: {type(exc).__name__}: {exc}")
        return
    if not report.paths:
        return
    if not (memory_path / ".git").exists():
        logger.info(f"Claim expiry: {len(report.claims)} fact(s) closed (no git — not committed)")
        return
    try:
        async with _lock:
            await git_service.commit_paths(memory_path, claim_expiry.commit_message(report, today), report.paths)
        logger.info(f"Claim expiry: {len(report.claims)} fact(s) reached their stated end")
    except Exception as exc:
        logger.warning(f"Claim expiry commit failed — restoring {len(report.paths)} page(s): "
                       f"{type(exc).__name__}: {exc}")
        await asyncio.to_thread(claim_expiry.restore, memory_path, report.paths)
```

  - In `_run_engine_independent_tail`'s guarded branch, make `await _expire_claims_safely(memory_path)`
    the **first** statement. Before `_poll_connectors_safely`, add the comment
    `# G140 Q-R7: expiry commits itself via commit_paths; first, so no poll's git add -A can sweep it.`
  - Change the `else` warning to begin `"claim expiry, connector, feed/calendar and link-backfill steps skipped: …"`.
  - Add one docstring sentence: `G140: expiry (_expire_claims_safely) shares this branch — its commit is scoped, but on a half-written cycle it would stage Sleep's hunks on the same page.`
- [ ] **Step 5: The *ended* wording.** In `mcp_tools._how_closed` and `_history_line`, add a second
  branch after the withdrawn one:

```python
    # in _how_closed:
    if not old.superseded_by and _ended_at_stated_end(old):
        return "ended at its stated end"
    # in _history_line:
    if not old.superseded_by and _ended_at_stated_end(old):
        return f"{head} {was} ended {old.valid_to} (its stated end)"
```

  With the helper:

```python
def _ended_at_stated_end(claim) -> bool:
    """Closed by ``claim_expiry`` (G140 Q-R7): no successor, and a stated end."""
    from api.services import claim_expiry

    return claim_expiry.stated_end(claim) is not None
```

- [ ] **Step 6: Green.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_claim_expiry.py api/tests/test_claims.py api/tests/test_claims_evidence.py api/tests/test_claim_reconciler.py api/tests/test_agentic_write.py api/tests/test_sleep_feed_poll.py api/tests/test_sleep_engine_state.py api/tests/test_sleep_link_backfill.py api/tests/test_agent_provenance.py api/tests/test_remote_tools.py api/tests/test_remote_runtime.py api/tests/test_mcp_recall_legs.py api/tests/test_retract_claim.py api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`
  Everything must be green.
- [ ] **Step 7: Commit.** `feat(claims): a stated end closes the fact — expected_end, due dates, a cicada Expiry commit on the tail (G140 Q-R6/Q-R7, R3 P8)`.

### Task 5: The video chain, part one — a kept note, citable episode ids, the observer spelling, descriptions and chapters (R5 §2 defects 1, 2, 4 and §5.6; Q-R10–Q-R12)

**Files:**
- Create: `api/services/video_chapters.py`.
- Modify:
  - `api/services/media_ingestor.py`:
    - imports (`:30`);
    - `DESCRIPTION_LIMIT`;
    - `MediaMeta.chapters` (`:102-117`);
    - `_enrich_oembed` (`:354-369`);
    - `_episode_body` (`:1485-1517`) and `write_media_episode` (`:1547-1550`);
    - `write_media_entity` (`:1690-1693`);
    - new `write_note_episode` after `save_url_index`.
  - `api/models/schemas.py`: `VideoChapter` above `EntityMedia`; `EntityMedia.chapters`;
    `SourceSaveResponse.note_episode_id`.
  - `api/routers/entities.py`: `_build_media_block` and a `_chapters` helper.
  - `api/routers/sources.py`: `save_source` (`:79-146`).
  - `api/services/mcp_tools.py`: `save_url` (`:257-343`) and `_saved_reply`.
  - `mcp/server.py`: the `cicada_write_claim.observer` schema (`:326-348`).
  - `api/tests/test_agentic_write.py:361-364`, `api/tests/test_owner_name_portability.py:115`,
    `api/tests/test_video_enrichment.py` (new tests appended), and the golden fixture (the
    `save_url` key).
- Test: `api/tests/test_video_chapters.py` and `api/tests/test_video_save_defects.py` (new).

**Interfaces:**
- Produces:
  - `video_chapters.MAX_CHAPTERS = 50` and `TITLE_LIMIT = 120`
  - `seconds(raw) -> int | None`
  - `stamp(total) -> str`
  - `parse(description) -> list[{"t": int, "title": str}]`
  - `media_ingestor.DESCRIPTION_LIMIT = 5000`
  - `MediaMeta.chapters`
  - `write_note_episode(memory_path, item, existing) -> tuple[str, bool] | None` (the episode id,
    and whether it was newly written)
  - `EntityMedia.chapters: list[VideoChapter] | None` (wire `chapters: [{t, title}]`)
  - `SourceSaveResponse.note_episode_id` (wire `noteEpisodeId`)
  - `mcp/server.py` `OBSERVER_PATTERN`
- Consumes: `bank_index.files` and `episode_ids`.

- [ ] **Step 1: Failing tests.**
  - Create `api/tests/test_video_chapters.py`:

```python
"""G140 Q-R12 (R5 §5.6) — chapters parsed from a video's own description text,
deterministically; absent beats a guess (R17)."""
from api.services import video_chapters as vc


def test_a_chapter_list_is_parsed():
    text = "A tour of alpha.\n0:00 Intro\n1:05 - Indexing\n(12:40) Wrap-up\n1:02:03 | Bonus"
    assert vc.parse(text) == [{"t": 0, "title": "Intro"}, {"t": 65, "title": "Indexing"},
                              {"t": 760, "title": "Wrap-up"}, {"t": 3723, "title": "Bonus"}]


def test_prose_with_a_time_is_not_a_chapter_list():
    assert vc.parse("At 3:15 we talk about alpha.\nSee you at 5:00.") == []


def test_a_list_must_start_at_zero_increase_and_have_two_lines():
    assert vc.parse("0:30 A\n1:00 B") == []
    assert vc.parse("0:00 A\n2:00 B\n1:00 C") == []
    assert vc.parse("0:00 Intro") == []
    assert vc.parse(None) == [] and vc.parse("") == []


def test_titles_are_capped_and_lists_bounded():
    lines = "\n".join(f"{i}:00 {'x' * 200}" for i in range(70))
    parsed = vc.parse(lines)
    assert len(parsed) == vc.MAX_CHAPTERS and all(len(c["title"]) == vc.TITLE_LIMIT for c in parsed)


def test_seconds_and_stamp():
    assert [vc.seconds(v) for v in ("12:34", "1:02:03", 754, "754", "0:05")] == [754, 3723, 754, 754, 5]
    assert [vc.seconds(v) for v in ("1:75", "soon", True, -1, None, "")] == [None] * 6
    assert (vc.stamp(754), vc.stamp(3723), vc.stamp(5)) == ("12:34", "1:02:03", "0:05")
```

  - Create `api/tests/test_video_save_defects.py`:

```python
"""G140 Q-R10/Q-R11 (R5 §2 defects 1, 2, 4) — a note given for an already-saved
link is kept and citable, both save replies name the episode, an agent's note
is never the person's words, and the librarian's `external:<name>` is a value
the schema accepts. Synthetic; no network (enrich is faked, the backend is
unreachable so the stdio tool takes its direct path)."""
from __future__ import annotations

import re
import urllib.request

import pytest

from _stdio_server import stdio_server
from api.services import evidence, markdown_parser, media_ingestor, owner_identity
from api.services.media_ingestor import IngestResult, MediaMeta, RawItem

URL = "https://vimeo.com/123456789"


async def _meta(url, client, from_bookmark_file=False):
    return MediaMeta(title="A clip", site="vimeo.com", media_type="url", provider="vimeo")


@pytest.fixture
def srv(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "sources"):
        (memory / sub).mkdir(parents=True)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(media_ingestor, "enrich", _meta)

    def _offline(*a, **k):
        raise OSError("no backend in this test")

    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    return server, memory


def test_both_replies_name_the_episode_and_a_duplicates_note_is_kept(srv):
    server, memory = srv
    first = server.handle_tool("cicada_save_url", {"url": URL})
    entity, episode = re.search(r"\(entity (\S+), episode (ep_[0-9_-]+)\)", first).groups()
    again = server.handle_tool("cicada_save_url", {"url": URL, "note": "It explains\nalpha indexing."})
    assert again.startswith(f'Already saved: "A clip" (entity {entity}, episode {episode}).')
    note_ep = re.search(r"Your note was kept as episode (ep_[0-9_-]+)", again).group(1)
    parsed = markdown_parser.parse(memory / "episodes" / f"{note_ep}.md")
    assert parsed.frontmatter["media_entity_id"] == entity and parsed.frontmatter["processed"] is False
    assert parsed.body.endswith("## Note\nassistant: It explains alpha indexing.")
    assert evidence.verify(memory, note_ep, "explains alpha indexing").kind == "assistant", \
        "an agent's summary is never the person's words"
    repeat = server.handle_tool("cicada_save_url", {"url": URL, "note": "It explains\nalpha indexing."})
    assert f"kept as episode {note_ep}" in repeat, "one episode per (page, note)"


def test_no_note_writes_no_episode(srv):
    server, memory = srv
    server.handle_tool("cicada_save_url", {"url": URL})
    count = len(list((memory / "episodes").glob("*.md")))
    assert "Your note was kept" not in server.handle_tool("cicada_save_url", {"url": URL})
    assert len(list((memory / "episodes").glob("*.md"))) == count


def test_the_persons_note_stays_theirs_and_an_agents_new_save_is_marked(tmp_path):
    existing = IngestResult(status="duplicate", media_entity_id="media-a-clip", episode_id="ep_2026-09-01_001",
                            title="A clip", media_type="url", url=URL)
    ep, created = media_ingestor.write_note_episode(tmp_path, RawItem(url=URL, note="Save this for the talk."),
                                                    existing)
    assert created and markdown_parser.parse(tmp_path / "episodes" / f"{ep}.md").body.endswith(
        "## Note\nSave this for the talk.")
    assert evidence.verify(tmp_path, ep, "Save this").kind == "user"
    assert media_ingestor.write_note_episode(tmp_path, RawItem(url=URL, note="   "), existing) is None
    agent = RawItem(url="https://example.com/a", note="Summary by the agent.", session_id="ses_x")
    ep2 = media_ingestor.write_media_episode(tmp_path / "episodes", agent,
                                             MediaMeta(title="A", site="example.com"), "media-a")
    body = markdown_parser.parse(tmp_path / "episodes" / f"{ep2}.md").body
    assert "## Note\nassistant: Summary by the agent." in body and "## User note" not in body


def test_the_save_route_keeps_the_persons_note_on_a_duplicate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setattr(media_ingestor, "enrich", _meta)
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        first = client.post("/sources/save", json={"url": URL}).json()
        again = client.post("/sources/save", json={"url": URL, "note": "Watch the indexing part."}).json()
        assert again["status"] == "duplicate" and again["episodeId"] == first["episodeId"]
        assert again["noteEpisodeId"] and again["message"] == "Already saved — your note was kept"
        body = markdown_parser.parse(memory / "episodes" / f"{again['noteEpisodeId']}.md").body
        assert body.endswith("## Note\nWatch the indexing part."), "the app's note is the person's"
        assert client.post("/sources/save", json={"url": URL}).json()["noteEpisodeId"] is None
    finally:
        config.get_settings.cache_clear()


def test_the_librarians_external_name_is_a_value_the_schema_accepts(srv):
    server, memory = srv
    prop = {t["name"]: t for t in server.TOOLS}["cicada_write_claim"]["inputSchema"]["properties"]["observer"]
    assert "enum" not in prop, "JSON Schema ANDs an enum with a pattern"
    pattern = re.compile(prop["pattern"])
    for ok in ("owner", "agent", "external", "external:bob-example", owner_identity.LEGACY_OBSERVER):
        assert pattern.fullmatch(ok), ok
    for bad in ("External", "external:", "external:Bob Example", "user", "external:" + "x" * 65):
        assert not pattern.fullmatch(bad), bad
    assert "external:<name>" in prop["description"]
```

  - Append to `api/tests/test_video_enrichment.py`:

```python
# --- G140 Q-R12: descriptions and chapters, fields only ----------------------


def test_vimeo_and_loom_keep_their_description_and_its_chapters():
    desc = "A tour of alpha.\n0:00 Intro\n1:05 Indexing\n12:40 Wrap-up"
    for url in ("https://vimeo.com/123456789", "https://www.loom.com/share/abc123def4567890abc123def4567890"):
        client = FakeClient(FakeResponse({"title": "T", "description": desc, "html": "<iframe></iframe>"}))
        meta = run(media_ingestor.enrich(url, client))
        assert meta.description == desc
        assert meta.chapters == [{"t": 0, "title": "Intro"}, {"t": 65, "title": "Indexing"},
                                 {"t": 760, "title": "Wrap-up"}]


def test_a_long_description_is_cut_not_refused():
    client = FakeClient(FakeResponse({"title": "T", "description": "x" * 9000}))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert len(meta.description) == media_ingestor.DESCRIPTION_LIMIT and meta.chapters is None


def test_write_media_entity_writes_chapters_and_the_description_only_when_set(tmp_path):
    from api.services import markdown_parser
    media_ingestor.write_media_entity(
        tmp_path, "media-c", RawItem(url="https://vimeo.com/123456789"),
        MediaMeta(title="C", site="vimeo.com", provider="vimeo", description="0:00 A\n1:00 B",
                  chapters=[{"t": 0, "title": "A"}, {"t": 60, "title": "B"}]), "ep_2026-09-23_001")
    parsed = markdown_parser.parse(tmp_path / "media-c.md")
    assert parsed.frontmatter["media"]["chapters"] == [{"t": 0, "title": "A"}, {"t": 60, "title": "B"}]
    assert "## Description\n0:00 A" in parsed.body
    media_ingestor.write_media_entity(tmp_path, "media-d", RawItem(url="https://example.com/d"),
                                      MediaMeta(title="D", site="example.com"), "ep_2026-09-23_002")
    assert "chapters" not in markdown_parser.parse(tmp_path / "media-d.md").frontmatter["media"]


def test_the_entity_media_block_keeps_well_formed_chapters_only():
    from api.routers.entities import _build_media_block

    block = _build_media_block({"media": {"url": "https://vimeo.com/1", "media_type": "url", "chapters": [
        {"t": 0, "title": "Intro"}, {"t": "5", "title": "bad t"}, {"t": 30, "title": ""}, "junk"]}}, "")
    assert [(c.t, c.title) for c in block.chapters] == [(0, "Intro")]
    assert _build_media_block({"media": {"url": "https://vimeo.com/1", "media_type": "url"}}, "").chapters is None
```

  - Update `test_agentic_write.py:361-364`. Keep the "never advertised" assertion, and replace the
    `enum` membership assertion with:

```python
    assert re.fullmatch(tool["inputSchema"]["properties"]["observer"]["pattern"],
                        owner_identity.LEGACY_OBSERVER), "still accepted (Q-R11), never advertised"
```

    (Add `import re` at the top if the file lacks it.)
  - Update `test_owner_name_portability.py:115` the same way. The legacy value is protocol and
    must stay accepted:
    `assert re.fullmatch(observer_schema["pattern"], SLUG), "the legacy observer stays accepted, it just stops being advertised"`.
    Add `import re` if the file lacks it. Its other assertions do not change: no description
    names a person, and no skill doc names the legacy value.
- [ ] **Step 2:** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_video_chapters.py api/tests/test_video_save_defects.py api/tests/test_video_enrichment.py api/tests/test_agentic_write.py -q -p no:cacheprovider`.
  Expect failure.
- [ ] **Step 3: Implement `video_chapters.py`.**

```python
"""Chapters from a video's own description text (G140 Q-R12, R5 §5.6) — fields only.

YouTube's rule for chapters is "formatted timestamps (for example, 00:00) in
the description text", and Vimeo and Loom descriptions follow the same habit.
So a chapter list is PARSED, deterministically, from text a provider already
returned — never fetched, never inferred, never a model. A list counts only
when it looks like one: at least two lines that each OPEN with a timestamp,
the first at 0:00, strictly increasing. Anything else — a lone "at 3:15 we…"
sentence — is prose and yields nothing: absent beats a guess (R17).

``seconds``/``stamp`` are the one reading of a video time in the backend, so
a watch record's excerpt times (``watch_record``) and a description's
chapter times can never parse differently.
"""
from __future__ import annotations

import re

MAX_CHAPTERS = 50
TITLE_LIMIT = 120
_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?[(\[]?(?P<t>(?:\d{1,2}:)?\d{1,2}:\d{2})[)\]]?\s*(?:[-–—:|]\s*)?(?P<title>\S.*?)\s*$"
)


def seconds(raw) -> int | None:
    """``m:ss`` / ``h:mm:ss`` / whole seconds (int or digits) → seconds;
    ``None`` when unreadable. Minutes and seconds after the first field must
    be < 60."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    nums = [int(p) for p in parts]
    if any(n >= 60 for n in nums[1:]):
        return None
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


def stamp(total: int) -> str:
    """Seconds → ``m:ss`` or ``h:mm:ss`` — the form a player shows."""
    hours, rest = divmod(max(0, int(total)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def parse(description: str | None) -> list[dict]:
    out: list[dict] = []
    for line in (description or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        t = seconds(m.group("t"))
        title = m.group("title").strip()[:TITLE_LIMIT]
        if t is None or not title:
            continue
        if out and t <= out[-1]["t"]:
            return []
        out.append({"t": t, "title": title})
        if len(out) >= MAX_CHAPTERS:
            break
    if len(out) < 2 or out[0]["t"] != 0:
        return []
    return out
```

- [ ] **Step 4: Implement `media_ingestor.py`.**
  1. Change `:30` to `from api.services import bank_index, decay_policy, episode_ids, markdown_parser, net_guard, saved_at, video_chapters, video_urls`.
     Add a module constant beside `_OEMBED_MAX_BYTES`:
     `DESCRIPTION_LIMIT = 5000  # G140 Q-R12: a description is kept, cut here — a field, not a document`.
  2. Add to `MediaMeta`, after `duration_s`:

```python
    # G140 Q-R12 — chapters parsed from the provider's own description
    # (`video_chapters.parse`), never inferred; `None` when there is no list.
    chapters: list[dict] | None = None
```

  3. In `_enrich_oembed`:
     - Before the `return`, add
       `description = str(data.get("description") or "").strip()[:DESCRIPTION_LIMIT]`.
     - Replace `description="",` with `description=description,` and add
       `chapters=video_chapters.parse(description) or None,`.
     - Extend its docstring's field list to "`title`, `author_name`, `thumbnail_url`, `duration`,
       `description` (G140: Vimeo and Loom return one, and it used to be discarded)".
  4. `_episode_body` gains the keyword `note_by_agent: bool = False`. Replace its `if note:` line with:

```python
    if note:
        # G140 Q-R10: an agent's note is the agent's words. The tool cannot
        # know a note relays the person, so it is written under an
        # `assistant:` marker — never where `evidence.speaker_kind` would read
        # it as theirs (the R-N2/R-F2 rule; G135 R-R12 calls an MCP save the
        # agent's). The person's own note keeps its heading.
        if note_by_agent:
            lines += ["", "## Note", "assistant: " + " ".join(note.split())]
        else:
            lines += ["", "## User note", note]
```

  5. `write_media_episode` passes `note_by_agent=bool((item.session_id or "").strip())` to `_episode_body`.
  6. `write_media_entity`, after the `duration_s` block:

```python
    if meta.chapters:
        frontmatter["media"]["chapters"] = [dict(c) for c in meta.chapters]
```

  7. After `save_url_index`:

```python
def write_note_episode(memory_path: Path, item: RawItem, existing: IngestResult) -> tuple[str, bool] | None:
    """A note given for a URL that is ALREADY saved (G140 Q-R10, R5 §2 defect 1).

    ``ingest_one`` returns ``duplicate`` before it reads ``item.note`` — right
    for a re-import (a Takeout re-run must not mint a note per bookmark), wrong
    for the one-link saves, where the note IS the point: G22's chain is "save
    a video, watch it later, write back what it covers", and that second
    save's summary vanished. So the two single-save paths (``POST
    /sources/save`` and ``cicada_save_url``'s backend-down path) call this on a
    duplicate; the batch paths never do.

    One episode per (media page, note): its ``content_hash`` is read back
    through ``bank_index``'s frontmatter cache, so a repeat returns the same
    id. An agent's note (the call carries a session id) is written under an
    ``assistant:`` marker, as in ``_episode_body``. Returns ``(episode id,
    newly written)``, or ``None`` for an empty note.
    """
    note = (item.note or "").strip()
    if not note:
        return None
    by_agent = bool((item.session_id or "").strip())
    if by_agent:
        note = " ".join(note.split())
    content_hash = hashlib.sha256(f"{existing.media_entity_id}\x00{note}".encode("utf-8")).hexdigest()[:12]
    for f in bank_index.files(memory_path, "episodes"):
        if f.frontmatter.get("content_hash") == content_hash:
            return f.stem, False
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_id = episode_ids.next_episode_id(episodes_dir, datetime.now().strftime("%Y-%m-%d"))
    body = "\n".join([f"# Note on {existing.title}", "", f"**URL:** {item.url}", "", "## Note",
                      f"assistant: {note}" if by_agent else note])
    frontmatter = {
        "id": episode_id,
        "timestamp": episode_ids.utc_now_iso(),
        "source": existing.media_type,
        "title": f"Note on {existing.title}"[:120],
        "processed": False,
        "content_hash": content_hash,
        "url": item.url,
        "media_entity_id": existing.media_entity_id,
    }
    if item.origin:
        frontmatter["origin"] = item.origin
    if item.session_id:
        frontmatter["session_id"] = item.session_id
        if item.harness and item.harness != "unknown":
            frontmatter["harness"] = item.harness
        if item.project_dir:
            frontmatter["project_dir"] = item.project_dir
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id, True
```

- [ ] **Step 5: Implement the wire, the router and the MCP reply.**
  1. **`schemas.py`**: directly above `class EntityMedia` add

```python
class VideoChapter(CamelModel):
    """One chapter of a saved video (G140 Q-R12): seconds from the start and a
    title — parsed from the provider's own description or recorded by an
    agent's watch, never inferred."""

    t: int
    title: str
```

     - Give `EntityMedia` the field `chapters: Optional[list[VideoChapter]] = None`, with a comment
       beside it: additive, and present only on a page written after G140, the same argument as
       Track V's two keys.
     - Give `SourceSaveResponse` the field `note_episode_id: Optional[str] = None`, with the comment
       `# G140 Q-R10 — the kept note's episode on a duplicate`.
  2. **`entities.py`**: `_build_media_block` passes `chapters=_chapters(media.get("chapters"))`, and
     the helper goes above it:

```python
def _chapters(raw) -> list[VideoChapter] | None:
    """G140 Q-R12 — keep only well-formed rows: a hand-edited page could carry
    anything, and absent beats a guess (R17)."""
    if not isinstance(raw, list):
        return None
    out = [VideoChapter(t=c["t"], title=str(c["title"]).strip()[:120]) for c in raw
           if isinstance(c, dict) and isinstance(c.get("t"), int) and not isinstance(c.get("t"), bool)
           and c["t"] >= 0 and str(c.get("title") or "").strip()]
    return out or None
```

     Import `VideoChapter` alongside `EntityMedia`.
  3. **`sources.py` `save_source`**:
     - After the `if result.status == "created":` block, insert:

```python
    # G140 Q-R10: a note for a link that is already saved is kept, not dropped
    # (G22's save-now-watch-later case). Committed alone, under whoever sent it.
    note_episode_id = None
    if result.status == "duplicate":
        note = media_ingestor.write_note_episode(memory_path, item, result)
        if note is not None:
            note_episode_id, created_note = note
            if created_note:
                by_agent = bool((request.session_id or "").strip())
                author = agent_commits.author_for(request.harness) if by_agent else "user"
                trigger = f"mcp/{author}" if by_agent else "user/media_save"
                from api.services import git_service

                try:
                    await git_service.commit_paths(memory_path, git_service.build_commit_message(
                        f"Sources note {date.today().isoformat()}",
                        [f"episodes/{note_episode_id}.md: created (trigger: {trigger})"],
                        authors=[author], sessions=[request.session_id] if by_agent else None,
                    ), [f"episodes/{note_episode_id}.md"])
                except Exception as e:
                    logger.warning(f"Note commit failed: {type(e).__name__}: {e}")
```

     - The `message` becomes:
       `"Saved — it joins the graph after the next Sleep cycle" if result.status == "created" else ("Already saved — your note was kept" if note_episode_id else "Already saved")`.
     - The response passes `note_episode_id=note_episode_id`.
     - Import `date` from `datetime` if the router lacks it.
  4. **`mcp_tools.py`**:
     - Add above `save_url`:

```python
def _saved_reply(status: str, title: str, media_type: str, entity_id: str, episode_id: str,
                 note_episode_id: str | None) -> str:
    """One reply for both save paths (G140 Q-R10, R5 §2 defect 2): the episode
    id is what ``cicada_write_claim``'s ``evidence`` cites, and the old replies
    never named it."""
    if status == "duplicate":
        kept = (f" Your note was kept as episode {note_episode_id} — cite that id as evidence."
                if note_episode_id else "")
        return f"Already saved: \"{title}\" (entity {entity_id}, episode {episode_id}).{kept}"
    return (f"Saved \"{title}\" as {media_type} media (entity {entity_id}, episode {episode_id}). "
            "It joins the graph after the next Sleep cycle.")
```

     - Path 1's `return` becomes
       `return _saved_reply(data.get("status", "created"), data.get("title", url), data.get("mediaType", "url"), data.get("mediaEntityId", "?"), data.get("episodeId", "?"), data.get("noteEpisodeId"))`.
     - In path 2, `_save()` returns `(result, note)`. After `media_ingestor.save_url_index(...)` it
       computes
       `note = media_ingestor.write_note_episode(memory_path, item, result) if result.status == "duplicate" else None`.
       The caller unpacks `result, note = asyncio.run(_save())`.
     - After the existing remote commit of a created save, add:

```python
        if ctx.is_remote and note and note[1]:
            # R-R11: a kept note commits alone, under its app, like any remote write.
            agent_commits.commit_write(
                memory_path, subject=ctx.commit_subject,
                lines=[f"episodes/{note[0]}.md: created (trigger: {ctx.trigger})"],
                paths=[f"episodes/{note[0]}.md"], author=ctx.author, session=ctx.session_id)
```

     - Path 2's two returns become one:
       `return _saved_reply(result.status, result.title, result.media_type, result.media_entity_id, result.episode_id, note[0] if note else None)`.
  5. **`mcp/server.py`**:
     - Below the `LEGACY_OBSERVER` import:

```python
# G140 Q-R11: one pattern, not an enum — JSON Schema ANDs an `enum` with a
# `pattern`, and the librarian skill's `external:<name>` (a named third party)
# must be a value the schema accepts (R5 §2 defect 4, G75 R12). The legacy
# value stays accepted and unadvertised (Track P R8), imported, never typed.
OBSERVER_PATTERN = (
    rf"^(owner|agent|external|{re.escape(LEGACY_OBSERVER)}|external:[a-z0-9][a-z0-9-]{{0,63}})$"
)
```

     - The `observer` property becomes (the comment above it is kept, with "ENUM" read as
       "pattern"):
       `"type": "string", "pattern": OBSERVER_PATTERN, "description": "Who holds this belief. 'owner' = the user stated this themselves (trust-protected). 'agent' = you inferred/extracted this. 'external' = attributed to a third party — or 'external:<name>' (lowercase letters, digits, hyphens) to name them. Defaults to 'agent'."`.
- [ ] **Step 6: Green, then re-record the golden fixture.**
  - Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_video_chapters.py api/tests/test_video_save_defects.py api/tests/test_video_enrichment.py api/tests/test_agentic_write.py api/tests/test_sources.py api/tests/test_agent_write_commits.py api/tests/test_remote_runtime.py api/tests/test_owner_name_portability.py -q -p no:cacheprovider`
    Everything must be green.
  - The golden test is now red on exactly one key. Re-record it with
    `CICADA_RECORD_GOLDEN=1 api/.venv/bin/python -m pytest api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`,
    then run `git diff api/tests/fixtures/mcp_stdio_golden.json`.
  - The diff must be **only** the `save_url` value, which now reads
    `Saved "Example Post" as url media (entity media-example-post, episode ep_<today>_002). It joins the graph after the next Sleep cycle.`
    The suffix is `002` because the run's earlier `save_episode` minted `ep_<today>_001` and its
    duplicate minted nothing. Any other suffix means the run's order changed: STOP.
  - The golden `save_url` call passes `note: "worth keeping"`. That note now lands in the episode
    under `## Note` / `assistant:` instead of `## User note` (Q-R10). The fixture holds only the
    reply, so this does not show in the diff.
  - Any other key moving means STOP.
- [ ] **Step 7: Commit.** `fix(video): a kept note on a saved link, citable episode ids, the external:<name> observer, descriptions and chapters (G140 Q-R10..Q-R12, R5 §2/§5.6, G22)`.

### Task 6: The watch record — `cicada_record_watch` and the `media` evidence kind (R5 §2 defect 3, §5.7; Q-R8, Q-R9)

**Files:**
- Modify:
  - `api/services/claims.py`: `EVIDENCE_KINDS` (`:52-59`), the comment and the tuple.
  - `api/services/evidence.py`: `_TURN_RE` (`:68-69`), `_marker_word`, `_role`, `speaker_kind` (`:180-200`),
    `_marker_lines` (`:203-223`), `turn_starts`, `TurnSpan` (`:231-256`), `turns` (`:259-282`),
    `media_time`, and `__all__`.
  - `api/models/schemas.py`: `EpisodeSpan.t` and `EpisodeTurn.t`.
  - `api/routers/episodes.py`: `get_episode_span`.
  - `api/services/mcp_tools.py`: `record_watch`.
  - `mcp/server.py`: a `TOOLS` entry after `cicada_save_url`, a `handle_tool` branch, and
    `handle_record_watch`.
  - `api/remote/catalog.py`, `api/remote/tools.py` and `api/remote/runtime.py`.
  - `skills/cicada-librarian/SKILL.md:28-29` and `:37-44` (the "after watching a video" trigger
    and the video steps).
  - `api/tests/test_claims_evidence.py:13`.
  - `api/tests/test_mcp_tools_context.py`: `MOVED` gains `"record_watch"`.
- Create: `api/services/watch_record.py`.
- Test: `api/tests/test_watch_record.py` (new).

**Interfaces:**
- Produces:
  - `EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning", "media")`
  - `evidence.media_time(text, start) -> int | None`
  - `TurnSpan.t`, and `role` gains the value `media`
  - `EpisodeSpan.t` and `EpisodeTurn.t` (wire `t`)
  - `watch_record.MAX_SUMMARY_CHARS = 1500`, `MAX_EXCERPTS = 12`, `MAX_QUOTE_CHARS = 240`,
    `MAX_CHAPTERS = 50`, `MAX_T_S = 24 * 3600`, `PREDICATE = "describes"`, `ORIGIN = "agent/watch"`,
    `SOURCE = "video-watch"` and `MARKER = "video"`
  - `watch_record.Target`
  - `watch_record.resolve(memory_path, url) -> Target | None`
  - `watch_record.record(memory_path, target, *, summary, excerpts=None, chapters=None, session_frontmatter=None, author="agent", session_id=None, origin=ORIGIN) -> dict`
  - `mcp_tools.record_watch(ctx, url, summary, excerpts=None, chapters=None) -> str`
  - the tool `cicada_record_watch` (remote scope `record`)
- Consumes:
  - `agentic_write.write_claim`
  - `evidence.source_text`, `verify_many` and `MAX_QUOTE_CHARS`
  - `media_ingestor.load_url_index` and `url_hash`
  - `video_chapters.seconds`, `stamp` and `TITLE_LIMIT` (Task 5)
  - `mcp_tools.save_url` (Task 5)

- [ ] **Step 1: Failing tests.**
  - Change `test_claims_evidence.py:13` to
    `assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning", "media")`.
  - Create `api/tests/test_watch_record.py`:

```python
"""G140 Q-R8/Q-R9 (R5 §2 defect 3, §5.7; G22) — what an agent saw in a saved
video, recorded as provenance: one watch episode (`assistant:` summary +
`video [m:ss]:` quotes), one `describes` claim whose spans are `assistant` and
`media`, times derived at read. Cicada fetches nothing. Synthetic bank."""
from __future__ import annotations

import re
import subprocess
import urllib.request

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config, main
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import evidence, markdown_parser, media_ingestor, mcp_tools
from api.services.claims import EVIDENCE_KINDS, Evidence, parse_claims
from api.services.media_ingestor import MediaMeta

URL = "https://vimeo.com/123456789"
SUMMARY = "A talk on how alpha indexes notes with sqlite-vec and why it stays local."
EXCERPTS = [{"t": 754, "quote": "search is one lookup"}, {"t": "1:05", "quote": "we keep every vector on the laptop"}]


async def _meta(url, client, from_bookmark_file=False):
    # One title per URL: `_media_entity_id` slugs the title alone, so a shared
    # title would make the second save overwrite the first page.
    title = "Alpha Talk" if url == URL else "Beta Talk"
    return MediaMeta(title=title, site="vimeo.com", media_type="url", provider="vimeo")


def _offline(*a, **k):
    raise OSError("no backend in this test")


@pytest.fixture
def saved(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    (memory / "sources").mkdir(exist_ok=True)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity("ses_watch_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    monkeypatch.setattr(media_ingestor, "enrich", _meta)
    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    server.handle_tool("cicada_save_url", {"url": URL})
    return server, memory


def _record(server, **kw):
    args = {"url": URL, "summary": SUMMARY, "excerpts": EXCERPTS, **kw}
    return server.handle_tool("cicada_record_watch", args)


def _ids(out):
    return (re.search(r"entity `([^`]+)`", out).group(1), re.search(r"episode `(ep_[^`]+)`", out).group(1),
            re.search(r"claim `([^`]+)`", out).group(1))


def _claim(memory, eid, cid):
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}[cid]


def test_a_video_line_is_media_and_carries_its_time():
    text = "assistant: a summary\n\nvideo [12:34]: a quote\nuser: later"
    at = text.index("a quote")
    assert evidence.speaker_kind(text, at) == "media" and evidence.media_time(text, at) == 754
    assert evidence.media_time(text, text.index("summary")) is None
    assert evidence.speaker_kind(text, text.index("later")) == "user"
    assert [(t.role, t.t) for t in evidence.turns(text)] == [("assistant", None), ("media", 754), ("user", None)]
    assert "media" in EVIDENCE_KINDS
    assert Evidence.from_dict({"episode": "ep_x", "start": 1, "end": 5, "kind": "media"}).kind == "media"


def test_an_untimed_video_line_stays_the_persons_words():
    """Q-R9: the time is what makes a line a video's. A person writing
    "Video: …" in their own message is still the person."""
    text = "user: here is my plan\nVideo: the one I recorded\nuser [0:10]: not a marker either"
    assert evidence.speaker_kind(text, text.index("the one I recorded")) == "user"
    assert evidence.media_time(text, text.index("the one I recorded")) is None
    assert [t.role for t in evidence.turns(text)] == ["user"], "one turn: neither line is a marker"


def test_a_watch_is_an_episode_and_a_describes_claim_with_media_spans(saved):
    server, memory = saved
    out = _record(server)
    eid, ep, cid = _ids(out)
    parsed = markdown_parser.parse(memory / "episodes" / f"{ep}.md")
    assert parsed.body.splitlines() == [f"assistant: {SUMMARY}", "",
                                        "video [1:05]: we keep every vector on the laptop",
                                        "video [12:34]: search is one lookup"], "time order, one line each"
    fm = parsed.frontmatter
    assert (fm["source"], fm["media_entity_id"], fm["processed"], fm["session_id"]) == (
        "video-watch", eid, False, "ses_watch_fixed")
    claim = _claim(memory, eid, cid)
    assert (claim.predicate, claim.object, claim.origin, claim.authored_by) == (
        "describes", SUMMARY, "agent/watch", "claude-code")
    text = evidence.source_text(memory, ep)
    assert [(e.kind, evidence.media_time(text, e.start)) for e in claim.evidence] == [
        ("assistant", None), ("media", 65), ("media", 754)]
    assert "never the transcript" in out


def test_a_quote_the_summary_repeats_still_lands_on_its_video_line(saved):
    server, memory = saved
    out = _record(server, summary="It says search is one lookup, which is the point.",
                  excerpts=[{"t": "0:10", "quote": "search is one lookup"}])
    eid, ep, cid = _ids(out)
    text = evidence.source_text(memory, ep)
    (media,) = [e for e in _claim(memory, eid, cid).evidence if e.kind == "media"]
    assert text[:media.start].endswith("video [0:10]: ")


def test_caps_hold_and_the_reply_says_so(saved):
    server, memory = saved
    excerpts = [{"t": i, "quote": f"{i:02d} " + "q" * 300} for i in range(20)] + [
        {"t": "soon", "quote": "x"}, {"t": "25:00:00", "quote": "past a day"}]
    out = _record(server, summary="word " * 600, excerpts=excerpts)
    _, ep, _ = _ids(out)
    lines = markdown_parser.parse(memory / "episodes" / f"{ep}.md").body.splitlines()
    assert len(lines[0]) <= len("assistant: ") + 1500 and "\n" not in lines[0]
    video = [line for line in lines if line.startswith("video [")]
    assert len(video) == 12 and all(len(line.split(": ", 1)[1]) <= 240 for line in video)
    assert "past a day" not in "\n".join(lines), "a time past MAX_T_S is dropped, never written"
    assert "10 excerpt(s) left out" in out and "cut at 1,500 characters" in out


def test_nothing_is_fetched_for_a_saved_video(saved, monkeypatch):
    server, _ = saved

    async def spy(*a, **k):
        raise AssertionError("record_watch fetched")

    monkeypatch.setattr(media_ingestor, "enrich", spy)
    assert _record(server).startswith("Recorded the watch")


def test_an_unsaved_link_is_saved_first_and_a_local_file_is_refused(saved):
    server, memory = saved
    other = "https://vimeo.com/987654321"
    assert _record(server, url=other).startswith("Recorded the watch")
    assert media_ingestor.url_hash(other) in media_ingestor.load_url_index(memory)
    assert "isn't saved in Cicada yet" in _record(server, url="file:///tmp/example-clip.mov")


def test_the_watch_commits_both_files_under_the_agent_and_is_idempotent(saved):
    server, memory = saved
    eid, ep, _ = _ids(_record(server))
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%s%n%b"],
                         capture_output=True, text=True, check=True).stdout
    assert f"episodes/{ep}.md: created (trigger: mcp/claude-code)" in log
    assert f"entities/{eid}.md: updated (source: {ep}, trigger: mcp/claude-code)" in log
    assert "Cicada-Author: claude-code" in log
    count = len(list((memory / "episodes").glob("*.md")))
    assert _ids(_record(server))[1] == ep and len(list((memory / "episodes").glob("*.md"))) == count


def test_chapters_fill_an_empty_page_and_never_overwrite(saved):
    server, memory = saved
    out = _record(server, chapters=[{"t": "2:00", "title": "Demo"}, {"t": "0:00", "title": "Intro"}])
    eid = _ids(out)[0]
    media = markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter["media"]
    assert media["chapters"] == [{"t": 0, "title": "Intro"}, {"t": 120, "title": "Demo"}] and "Chapters saved" in out
    again = _record(server, summary="A second look.", chapters=[{"t": "0:00", "title": "Other"}])
    assert "already has chapters" in again
    assert markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter["media"]["chapters"][0]["title"] == "Intro"


def test_the_span_route_serves_the_time(saved, monkeypatch):
    server, memory = saved
    _, ep, _ = _ids(_record(server))
    text = evidence.source_text(memory, ep)
    start = text.index("search is one lookup")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        body = TestClient(main.app).get(f"/episodes/{ep}/span", params={"start": start, "end": start + 20}).json()
    finally:
        config.get_settings.cache_clear()
    assert body["kind"] == "media" and body["t"] == 754


def test_a_remote_watch_is_record_scope_and_the_apps(saved, monkeypatch):
    _, memory = saved
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        runtime = RemoteRuntime(post=lambda path, payload: {}, sleep_running=lambda: False)
        phone = catalog.Connector(id="aaaaaaaa", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                  created_at="2026-09-01T00:00:00+00:00")
        text, status = runtime.call(phone, "cicada_record_watch", {"url": URL, "summary": SUMMARY,
                                                                   "excerpts": EXCERPTS})
    finally:
        config.get_settings.cache_clear()
    assert status == "ok" and text.startswith("Recorded the watch"), text
    eid, _, cid = _ids(text)
    assert _claim(memory, eid, cid).origin == "remote:aaaaaaaa"
    assert catalog.TOOL_SCOPE["cicada_record_watch"] == "record" and "cicada_record_watch" in catalog.WRITE_TOOLS
```

- [ ] **Step 2:** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_watch_record.py api/tests/test_claims_evidence.py -q -p no:cacheprovider`.
  Expect failure.
- [ ] **Step 3: Implement the evidence kind.**
  - **`claims.py`**: the comment above `EVIDENCE_KINDS` gains the line
    `# G140 Q-R9: `media` is the fifth — what a video said (a watch record's cited excerpt, a `video [m:ss]:` line). Append-only: older readers degrade an unknown kind to `reasoning`.`
    The tuple becomes `("user", "assistant", "page", "reasoning", "media")`.
  - **`evidence.py`**:
    1. Replace `_TURN_RE` and `_ASSISTANT_ROLES` with:

```python
# G140 Q-R9: a `video`/`media` line is what a video said — a watch record's
# cited excerpt (`video [12:34]: …`, `watch_record`). Its `[m:ss]`/`[h:mm:ss]`
# is REQUIRED: "Video:" opens ordinary lines in a person's own messages, and
# reading those as a video's words would be R5 §2 defect 3 in reverse. The six
# original words keep their alternative byte for byte, so no stored episode
# reads differently. `media_time` reads the time back at read time.
_TURN_RE = re.compile(
    r"^(?:(user|human|assistant|ai|system|unknown)"
    r"|(video|media)\s*\[(?P<t>\d{1,2}(?::\d{2}){1,2})\])\s*:",
    re.IGNORECASE,
)
_ASSISTANT_ROLES = frozenset({"assistant", "ai"})
_MEDIA_ROLES = frozenset({"video", "media"})


def _marker_word(m: re.Match[str]) -> str:
    """The marker word a ``_TURN_RE`` match stands on, lower-cased — group 1
    for the six conversation words, group 2 for a timed video line."""
    return (m.group(1) or m.group(2) or "").lower()


def _role(marker: str | None) -> str:
    """The kind a marker word stands for — ONE mapping, read by both
    ``speaker_kind`` and ``turns``, so a turn's role and a span's kind can
    never disagree (R-PB3)."""
    word = (marker or "").lower()
    if word in _ASSISTANT_ROLES:
        return "assistant"
    if word in _MEDIA_ROLES:
        return "media"
    return "user"
```

    2. In `speaker_kind`, the loop body becomes `kind = _role(_marker_word(m))`. Its docstring's
       first line becomes: `R4: ``assistant`` when the last turn marker at or before ``start`` is the model's, ``media`` when it is a timed video line (G140), ``user`` otherwise — …`.
    3. `_marker_lines` returns 4-tuples `(line start, marker word, content start, time or None)`.
       Its append becomes `out.append((pos, _marker_word(m), pos + content, m.group("t")))`, and
       its return annotation is `list[tuple[int, str, int, str | None]]`. `turn_starts` becomes
       `return [start for start, *_ in _marker_lines(text)]`. Every other `m.group(1)` in the
       module goes through `_marker_word`: group 1 is `None` on a video line.
    4. `TurnSpan` gains `t: int | None = None` last, documented as
       `seconds into the video for a `video [m:ss]:` turn (G140 Q-R9) — derived from the marker, never stored`.
       The `role` doc line gains `| media`.
    5. In `turns`:
       - the placeholder becomes `blocks.insert(0, (0, None, 0, None))`;
       - the loop unpacks `for i, (start, marker, content_start, stamp_raw) in enumerate(blocks):`
         (rename the existing `stamp = stamps.get(start) or {}` local to `sidecar` to avoid the
         clash);
       - the `TurnSpan(...)` gets `role=_role(marker)` and `t=_seconds(stamp_raw) if _role(marker) == "media" else None`.
    6. Add after `speaker_kind`:

```python
def _seconds(raw: str | None) -> int | None:
    """``m:ss`` / ``h:mm:ss`` → seconds. Local on purpose: this module
    imports only ``markdown_parser`` and ``claims`` (G80)."""
    if not raw:
        return None
    total = 0
    for part in raw.split(":"):
        if not part.isdigit():
            return None
        total = total * 60 + int(part)
    return total


def media_time(text: str, start: int) -> int | None:
    """Seconds into the video for a span on a ``video [m:ss]:`` line (G140
    Q-R9) — read at read time from the marker line at or before ``start``,
    the same line ``speaker_kind`` reads, and never stored on the evidence.
    ``None`` on any other line."""
    text = text or ""
    start = max(int(start), 0)
    line_end = text.find("\n", start)
    head = text if line_end == -1 else text[:line_end]
    found = None
    for line in head.splitlines():
        m = _TURN_RE.match(line)
        if m:
            found = m
    if found is None or _role(_marker_word(found)) != "media":
        return None
    return _seconds(found.group("t"))
```

    7. `__all__` gains `"media_time"`.
  - **`schemas.py`**:
    - `EpisodeTurn` gains `t: Optional[int] = None` last. Its docstring role list becomes
      `user | assistant | page | media`, and gains `t = seconds into the video for a media turn (G140)`.
    - `EpisodeSpan` gains `t: Optional[int] = None` last, documented as
      `G140 Q-R9: for a span on a video line, seconds into the video — derived, never stored`.
  - **`episodes.py` `get_episode_span`**: add `t=evidence.media_time(text, start) if evidence.is_episode_id(episode_id) else None,`
    to the `EpisodeSpan(...)`.
- [ ] **Step 4: Implement the watch record.** Create `api/services/watch_record.py`:

```python
"""The video watch record (G140 Q-R8, G22, R5 §5.7): what an agent saw in a
saved video, kept as provenance — spans, not copies.

Cicada never watches, downloads or transcribes a video; the Track V rail ("a
stream is never derived") holds. A person's agent may watch one with its own
tools, on its own machine, with its own keys. This module records what it
brings back:

* one **watch episode** — ``assistant: <summary>``, then one
  ``video [m:ss]: <quote>`` line per cited excerpt, in time order. The
  ``video`` marker is what makes ``evidence.speaker_kind`` answer ``media``
  (Q-R9), so a creator's words are never read as the person's (R5 §2
  defect 3);
* one **``describes`` claim** on the media page, written through
  ``agentic_write.write_claim`` (one reconcile path), whose evidence is the
  summary span (``assistant``) and each excerpt's span (``media``) — each
  located inside its own line, so a quote the summary repeats still cites
  the video;
* **chapters**, only when the page has none (a description's own win).

Caps (Q-R8): the summary is one line of at most 1,500 characters — folded,
so no line of it can pose as a turn marker; at most 12 excerpts of 240, each
at most ``MAX_T_S`` into the video; at most 50 chapters. A transcript does not
fit and is never asked for (R5 D3).
"Watched" is derived, never stored: a ``describes`` claim with a ``media`` span.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api.services import agentic_write, bank_index, episode_ids, markdown_parser, media_ingestor, video_chapters
from api.services import evidence as evidence_mod

MAX_SUMMARY_CHARS = 1500
MAX_EXCERPTS = 12
MAX_QUOTE_CHARS = 240
MAX_CHAPTERS = 50
# A day of video. Past it a stamp needs a three-digit hour, which the
# `video [h:mm:ss]:` marker does not read (Q-R9), and the quote would land in
# the summary's turn. So a later time is dropped, never written.
MAX_T_S = 24 * 3600
PREDICATE = "describes"
ORIGIN = "agent/watch"
SOURCE = "video-watch"
MARKER = "video"


@dataclass
class Target:
    entity_id: str
    title: str
    url: str


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def resolve(memory_path: Path, url: str) -> Target | None:
    """The saved media page for ``url``, through the dedup index every saver
    writes (``url_hash``) — a video saved from the app, a bookmark import or
    ``cicada_save_url`` resolves alike. ``None`` when not saved."""
    entry = media_ingestor.load_url_index(Path(memory_path)).get(media_ingestor.url_hash(url))
    if not entry or not entry.get("media_entity_id"):
        return None
    entity_id = str(entry["media_entity_id"])
    if not (Path(memory_path) / "entities" / f"{entity_id}.md").exists():
        return None
    return Target(entity_id=entity_id, title=str(entry.get("title") or entity_id), url=url)


def _excerpts(raw) -> tuple[list[tuple[int, str]], int]:
    """``[(seconds, quote)]`` in time order, capped, and how many were left out."""
    kept: list[tuple[int, str]] = []
    dropped = 0
    for item in list(raw or []):
        t = video_chapters.seconds(item.get("t")) if isinstance(item, dict) else None
        quote = _one_line(item.get("quote"))[:MAX_QUOTE_CHARS].rstrip() if isinstance(item, dict) else ""
        if t is None or t > MAX_T_S or not quote:
            dropped += 1
            continue
        kept.append((t, quote))
    kept.sort(key=lambda e: e[0])
    if len(kept) > MAX_EXCERPTS:
        dropped += len(kept) - MAX_EXCERPTS
        kept = kept[:MAX_EXCERPTS]
    return kept, dropped


def _chapters(raw) -> list[dict]:
    out = []
    for item in list(raw or [])[:MAX_CHAPTERS]:
        if not isinstance(item, dict):
            continue
        t = video_chapters.seconds(item.get("t"))
        title = _one_line(item.get("title"))[: video_chapters.TITLE_LIMIT]
        if t is not None and t <= MAX_T_S and title:
            out.append({"t": t, "title": title})
    return sorted(out, key=lambda c: c["t"])


def _write_episode(memory_path: Path, target: Target, body: str, session_fm: dict) -> str:
    """One episode per (page, body): a repeated call returns the same id."""
    content_hash = hashlib.sha256(f"{target.entity_id}\x00{body}".encode("utf-8")).hexdigest()[:12]
    for f in bank_index.files(memory_path, "episodes"):
        if f.frontmatter.get("content_hash") == content_hash:
            return f.stem
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_id = episode_ids.next_episode_id(episodes_dir, datetime.now().strftime("%Y-%m-%d"))
    frontmatter = {
        "id": episode_id,
        "timestamp": episode_ids.utc_now_iso(),
        "source": SOURCE,
        # G9's closed origin vocabulary: an agent's write through MCP.
        "origin": "mcp",
        "title": f"Watched: {target.title}"[:120],
        "processed": False,
        "content_hash": content_hash,
        "url": target.url,
        "media_entity_id": target.entity_id,
        **session_fm,
    }
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id


def _store_chapters(memory_path: Path, entity_id: str, chapters: list[dict]) -> bool:
    """Q-R8: an agent's chapters fill ``media.chapters`` only when it is empty."""
    path = memory_path / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(path)
    media = parsed.frontmatter.get("media")
    if not isinstance(media, dict) or media.get("chapters"):
        return False
    media["chapters"] = chapters
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    return True


def record(
    memory_path: Path,
    target: Target,
    *,
    summary: str,
    excerpts=None,
    chapters=None,
    session_frontmatter: dict | None = None,
    author: str = "agent",
    session_id: str | None = None,
    origin: str = ORIGIN,
) -> dict:
    """Write the watch episode and the ``describes`` claim. Never raises on a
    normal input; returns ``{error}`` or the ids, counts and ``paths`` to commit."""
    memory_path = Path(memory_path)
    summary = _one_line(summary)
    if not summary:
        return {"error": "a summary is required — say what the video covers; nothing was recorded"}
    clipped = len(summary) > MAX_SUMMARY_CHARS
    summary = summary[:MAX_SUMMARY_CHARS].rstrip()
    kept, dropped = _excerpts(excerpts)
    video_lines = [f"{MARKER} [{video_chapters.stamp(t)}]: {quote}" for t, quote in kept]
    body = "\n".join([f"assistant: {summary}", *([""] + video_lines if video_lines else [])])
    episode_id = _write_episode(memory_path, target, body, session_frontmatter or {})
    text = evidence_mod.source_text(memory_path, episode_id) or body
    cites: list[dict] = [{"episode": episode_id, "quote": summary[: evidence_mod.MAX_QUOTE_CHARS]}]
    for line, (_, quote) in zip(video_lines, kept):
        item = {"episode": episode_id, "quote": quote}
        at = text.find(line)
        if at >= 0:
            item["window"] = [at, at + len(line)]
        cites.append(item)
    result = agentic_write.write_claim(
        memory_path, target.entity_id, PREDICATE, summary, observer="agent", confidence=0.75,
        context="general", source_episode=episode_id, object_kind="literal",
        text=f"{target.title}: {summary}", session_id=session_id, origin=origin, evidence=cites,
        authored_by=author,
    )
    paths = [f"episodes/{episode_id}.md"]
    if result.get("action") in ("error", "ambiguous_subject", "corrupt_claims_block"):
        return {"error": result.get("error") or result.get("action"), "episode_id": episode_id, "paths": paths}
    wanted = _chapters(chapters)
    chapters_stored = _store_chapters(memory_path, target.entity_id, wanted) if wanted else None
    paths.append(result.get("path") or f"entities/{target.entity_id}.md")
    return {"entity_id": target.entity_id, "episode_id": episode_id, "claim_id": result.get("claim_id"),
            "evidence": result.get("evidence") or [], "excerpts": len(kept), "dropped": dropped,
            "summary_clipped": clipped, "chapters": chapters_stored, "paths": paths}
```

  **`mcp_tools.py`**, after `save_url`:

```python
def record_watch(ctx: ToolContext, url: str, summary: str, excerpts: list | None = None,
                 chapters: list | None = None) -> str:
    """``cicada_record_watch`` (G140 Q-R8, R5 §5.7): record what the caller's
    own tools saw in a saved video — a summary, ≤ 12 timestamped quotes, and
    optional chapters — as one episode and one ``describes`` claim, committed
    together under the caller. Cicada fetches nothing for a saved video; an
    unsaved ``http(s)`` link is saved first through ``save_url`` (its own
    rails), and a ``file://`` one must be added in the app."""
    from api.services import watch_record

    url = (url or "").strip()
    if not url.startswith(("http://", "https://", "file://")):
        return "Error: url must be the saved video's link (http(s):// or file://)."
    memory_path = ctx.memory_path()
    target = watch_record.resolve(memory_path, url)
    if target is None:
        if url.startswith("file://"):
            return ("That video isn't saved in Cicada yet. Add the file in the Cicada app first, then record "
                    "the watch.")
        # Q-R8: saved first through save_url's own two paths and rails. On
        # stdio's backend-down path that save stays uncommitted (as any
        # cicada_save_url does there), so the page's creation rides in the
        # watch commit below; url_index.json and the save's episode do not.
        saved = save_url(ctx, url, None)
        if saved.startswith("Error"):
            return saved
        target = watch_record.resolve(memory_path, url)
        if target is None:
            return "Error: the link could not be saved, so the watch was not recorded."
    r = watch_record.record(
        memory_path, target, summary=summary, excerpts=excerpts, chapters=chapters,
        session_frontmatter=ctx.session_frontmatter(), author=ctx.author, session_id=ctx.session_id,
        origin=ctx.claim_origin or watch_record.ORIGIN,
    )
    if r.get("error"):
        return f"Could not record the watch: {r['error']}"

    from api.services import telemetry

    refs = {"entity_id": r["entity_id"], "claim_id": r["claim_id"], "episode_id": r["episode_id"],
            "action": "watch_recorded", "session_id": ctx.session_id, "harness": ctx.harness,
            "client_name": ctx.client_name, "client_version": ctx.client_version}
    if ctx.is_remote:
        refs["connector_id"] = ctx.connector_id
    telemetry.record(telemetry.UsageEvent(
        kind="agentic_write", stage="driver", connection="session",
        engine="mcp-remote" if ctx.is_remote else "mcp-client",
        model=None, bank=memory_path.name, billing="subscription", invocations=1, refs=refs,
    ))
    if not ctx.sleep_running():
        agent_commits.commit_write(
            memory_path, subject=ctx.commit_subject,
            lines=[f"episodes/{r['episode_id']}.md: created (trigger: {ctx.trigger})",
                   f"entities/{r['entity_id']}.md: updated (source: {r['episode_id']}, trigger: {ctx.trigger})"],
            paths=r["paths"], author=ctx.author, session=ctx.session_id,
        )
    quotes = sum(1 for e in r["evidence"] if e.get("kind") == "media")
    parts = [f"Recorded the watch of \"{target.title}\" (entity `{r['entity_id']}`): episode "
             f"`{r['episode_id']}`, claim `{r['claim_id']}`. Evidence: the summary and {quotes} timestamped "
             "quote(s) from the video."]
    if r["dropped"]:
        parts.append(f"{r['dropped']} excerpt(s) left out (no readable time, a time past 24 hours, empty, "
                     "or past the 12-quote cap).")
    if r["summary_clipped"]:
        parts.append("The summary was cut at 1,500 characters.")
    if r["chapters"] is True:
        parts.append("Chapters saved on the page.")
    elif r["chapters"] is False:
        parts.append("The page already has chapters; yours were not stored.")
    parts.append("Cicada keeps these short quotes, never the transcript.")
    return " ".join(parts)
```

  **The schemas, dispatch and scopes:**
  - **`mcp/server.py`**, in `TOOLS` after `cicada_save_url` (`handle_tool`: `elif name == "cicada_record_watch": return handle_record_watch(arguments.get("url", ""), arguments.get("summary", ""), arguments.get("excerpts"), arguments.get("chapters"))`;
    `def handle_record_watch(url, summary, excerpts=None, chapters=None) -> str: return mcp_tools.record_watch(_ctx(), url, summary, excerpts, chapters)`):

```python
    {
        "name": "cicada_record_watch",
        "description": "After you watch a video the person saved (with your own video tools — Cicada never downloads or watches one), record what it covers: a short summary and up to 12 short quotes with the time each is said. Cicada keeps one episode and a 'describes' claim on the video's page whose evidence points at your summary and at each quote, marked as the video's words — never the person's. Cite ≤240-character excerpts; never paste the transcript. A link that is not saved yet is saved first. The reply names the episode, to cite from cicada_write_claim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The video's link as saved (http(s)://, or file:// for a local recording the app added)."},
                "summary": {"type": "string", "description": "Your faithful account of what the video covers, one paragraph (at most 1,500 characters)."},
                "excerpts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "t": {"type": "string", "description": "When it is said: m:ss or h:mm:ss (e.g. '12:34'), or whole seconds."},
                            "quote": {"type": "string", "description": "The words the video says, verbatim (at most 240 characters)."},
                        },
                        "required": ["t", "quote"],
                    },
                    "description": "Optional. Up to 12 short timestamped quotes — the video's own words.",
                },
                "chapters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"t": {"type": "string"}, "title": {"type": "string"}},
                        "required": ["t", "title"],
                    },
                    "description": "Optional. The video's chapters as {t, title}; stored only when the page has none.",
                },
            },
            "required": ["url", "summary"],
        },
    },
```

  - **`api/remote/catalog.py`**: `"cicada_record_watch": "record",` in `TOOL_SCOPE`, and add it to
    `WRITE_TOOLS`.
  - **`api/remote/tools.py`**, after `cicada_save_url` (it names only same-scope tools):

```python
    _tool("cicada_record_watch",
          "After you watch a video the person saved, record what it covers: a short summary and up to 12 "
          "short quotes with the time each is said. Cicada keeps these quotes as the video's words, never "
          "the whole transcript, and never downloads the video itself. The reply names the episode to cite "
          "in cicada_write_claim.",
          {"url": {"type": "string", "description": "The video's link as saved."},
           "summary": {"type": "string", "description": "What the video covers, one paragraph."},
           "excerpts": {"type": "array", "description": "Optional: up to 12 short quotes with their time.",
                        "items": {"type": "object", "required": ["t", "quote"], "properties": {
                            "t": {"type": "string", "description": "When it is said, e.g. '12:34'."},
                            "quote": {"type": "string", "description": "The words, verbatim (at most 240 characters)."},
                        }}},
           "chapters": {"type": "array", "description": "Optional: the video's chapters.",
                        "items": {"type": "object", "required": ["t", "title"], "properties": {
                            "t": {"type": "string"}, "title": {"type": "string"}}}}},
          ("url", "summary"), read_only=False, idempotent=True, open_world=True),
```

  - **`api/remote/runtime.py`** `_DISPATCH`: `"cicada_record_watch": lambda c, a: mcp_tools.record_watch(c, str(a.get("url") or ""), str(a.get("summary") or ""), a.get("excerpts"), a.get("chapters")),`.
  - **`test_mcp_tools_context.py`**: `MOVED` gains `"record_watch"`.
- [ ] **Step 5: The librarian skill (R12: skill text names only what exists).** Replace the
  `**Video**` bullet (`skills/cicada-librarian/SKILL.md:37-44`) with:

```markdown
- **Video**: when the person asks you to watch a video they saved, use a video
  skill of your own (for example the `claude-video` skill's `/watch`). Cicada
  never downloads or watches a video itself. Then call
  `cicada_record_watch(url, summary, excerpts=[{t, quote}])`:
  1. `summary` — your faithful account of what the video covers, one paragraph.
  2. `excerpts` — up to 12 short quotes (at most 240 characters) with the time
     each is said (`"12:34"`): the words the video actually says. **Never paste
     the transcript** — Cicada keeps these quotes as cited evidence, marked as
     the video's words, not the person's.
  3. A local recording saved as `file://…` is a path on disk for your skill,
     not a URL — convert it before you run the skill.
  4. Then `cicada_write_claim(...)` for relational facts the video establishes
     (subject = the video's entity id, e.g. predicate `is-about`), citing the
     watch episode the reply names.
```

  Also replace the "When to run" bullet at `:28-29`, which still says to consolidate "a transcript
  + summary". It contradicts the step above. The new text:

```markdown
- **After watching a video** — once your video skill has run, record the
  watch with `cicada_record_watch` (below): a summary and short timestamped
  quotes, never the transcript.
```

  Line 69's `external:<name>` row stays: Task 5 made the schema accept it.
- [ ] **Step 6: Green.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_watch_record.py api/tests/test_claims_evidence.py api/tests/test_evidence.py api/tests/test_evidence_grown.py api/tests/test_evidence_agent_writes.py api/tests/test_episode_text_endpoint.py api/tests/test_entity_provenance.py api/tests/test_remote_tools.py api/tests/test_remote_runtime.py api/tests/test_mcp_tools_context.py api/tests/test_search_service.py api/tests/test_video_save_defects.py api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider`
  Everything must be green.
  - `test_episode_text_endpoint.py` drives `evidence.turns` and `GET /episodes/{id}/text`. That
    route builds `EpisodeTurn(**asdict(t))` (`provenance.py:153`), so it is the test that fails if
    `TurnSpan.t` lands without `EpisodeTurn.t`.
  - The provenance, grown and span tests cover the rest of the `turns()` shape change.
- [ ] **Step 7: Commit.** `feat(video): cicada_record_watch and the media evidence kind — timestamped quotes as the video's words, never the transcript (G140 Q-R8/Q-R9, R5 §5.7, G22, G118)`.

### Task 7: The primer — Standing and Current, the person and their timezone, how to work with them, and a contract that names the new tools (R3 P5; Q-R13, Q-R14)

All three new tools exist by now, so the contract can name them (R12). The now-view borrows
Instinct's "identity + autonomy calibration + communication style" and supermemory's static/dynamic
split. It uses the decay classes every page already carries, with no prose and no classifier.

**Files:**
- Modify:
  - `api/services/state_dictionary.py`: `SCHEMA_VERSION` (`:73`), `_DEFAULTS` (`:94`), new
    constants, `inputs_version` (`:103-106`), new selectors, `build` (`:366-402`), `render_body`
    (`:407-433`), `_fit` (`:443-456`).
  - `api/services/handshake.py`: `CONTRACT_VERSION` (`:46`), `REMOTE_CONTRACT_VERSION` (`:56`),
    `_remote_contract` (`:83-113`), `_CONTRACT` (`:175-194`), `local_timezone`, `_now_block`
    (`:220-263`), `_assemble` / `_fit` / `build` / `build_remote` (`:266-304`), `load_or_build`
    (`:340-360`).
  - `api/config.py`: after `state_conversations` (`:234`), add
    `state_standing: int = 5  # CICADA_STATE_STANDING` and `state_focus: int = 5  # CICADA_STATE_FOCUS`.
  - `api/tests/test_state_dictionary.py` (new tests; `:33` `schema_version == 1` → `== 2`),
    `api/tests/test_state_wiring.py` (`:150` `data["schema_version"] == 1` → `== 2`: `GET /state`
    serves the file's frontmatter) and `api/tests/test_handshake.py` (new tests; `:55`
    `CONTRACT_VERSION == 2` → `== 3`).
  - `SKILL.md:44`: `cicada_open_hub(hub_id)` → `cicada_open_hub(hub)`. The stdio property is
    `hub`, so this is the same R12 defect class the new test finds in the primers. The skill text
    is not parsed by that test, so it is fixed by hand.
- Test: `api/tests/test_handshake_r12.py` (new).

**Interfaces:**
- Produces:
  - `state_dictionary.SCHEMA_VERSION = 2`
  - `STANDING_CLASSES`, `CURRENT_CLASSES`, `FOCUS_WINDOW_DAYS = 14` and `WORKING_TAGS`
  - the state keys `owner_one_liner`, `standing: [{id, name, one_liner}]` and
    `focus: [{id, name, one_liner, last_referenced}]`; `preferences` is re-ranked
  - `handshake.local_timezone() -> str | None`
  - `build(..., tz=None)` and `build_remote(..., tz=None)`
  - `CONTRACT_VERSION = 3` and `REMOTE_CONTRACT_VERSION = 2`
- Consumes: `decay_policy.resolve`, `owner_identity.resolve_observer`, `tzlocal.get_localzone_name`,
  and the stdio `TOOLS` / remote `REMOTE_TOOLS` schemas (in the R12 test).

- [ ] **Step 1: Failing tests.**
  - Create `api/tests/test_handshake_r12.py`:

```python
"""G75 R12, enforced for ARGUMENTS (G140 Q-R14): every `cicada_x(args)` a
primer names must be a tool the reader holds, and every argument it names
must be a property of that tool's schema — for the three local variants and
for all 63 remote scope sets. It found `cicada_recall_detail(id)` (the
property is `entity_id`)."""
from __future__ import annotations

import re
from itertools import combinations

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _ok_repo, _settings
from api.remote import catalog
from api.remote import tools as remote_tools
from api.services import handshake, state_dictionary

CALL = re.compile(r"`(cicada_[a-z_]+)\(([^`]*)\)`")
SUBSETS = [frozenset(c) for n in range(1, len(catalog.SCOPES) + 1) for c in combinations(catalog.SCOPES, n)]


def _args(arglist: str) -> list[str]:
    """Top-level argument names: `a, b=[{x, y}], c|d` → a, b, c, d. A quoted
    literal or `<placeholder>` names nothing."""
    parts, depth, current = [], 0, ""
    for ch in arglist:
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    names = []
    for part in parts:
        for alt in part.split("|"):
            m = re.match(r"\s*([a-z_]+)\s*(=|$)", alt)
            if m:
                names.append(m.group(1))
    return names


def _check(text: str, schemas: dict[str, set[str]]):
    for tool, arglist in CALL.findall(text):
        assert tool in schemas, tool
        for arg in _args(arglist):
            assert arg in schemas[tool], (tool, arg)


def test_every_argument_the_local_primer_names_is_in_the_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    schemas = {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}
    for variant in handshake.VARIANTS:
        _check(handshake.build(state_dictionary.read_state(memory), variant=variant, bank="memory",
                               tz="Europe/Madrid"), schemas)


@pytest.mark.parametrize("scopes", SUBSETS, ids=lambda s: "+".join(sorted(s)))
def test_every_argument_a_remote_primer_names_is_in_its_schema(scopes):
    schemas = {n: set(d["inputSchema"]["properties"]) for n, d in remote_tools.REMOTE_TOOLS.items()}
    _check(handshake.build_remote(None, tools=catalog.tool_names_for(scopes), bank="memory"), schemas)


def test_the_parser_reads_nested_and_alternative_arguments():
    assert _args("subject, evidence=[{episode, quote}], sources=[url]") == ["subject", "evidence", "sources"]
    assert _args("entity_id|path") == ["entity_id", "path"] and _args("'projects'") == []
    assert _args("entity_ids=<recall ids>") == ["entity_ids"]
```

  - Append to `api/tests/test_state_dictionary.py`:

```python
# --- G140 Q-R13: standing and current, read off the decay classes -----------


def test_standing_focus_and_how_to_work_with_me(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "local-first", type="concept", decay_class="durable", confidence=0.9,
            last_referenced="2026-01-01", body="## Summary\nKeeps data on the device.\n")
    _entity(memory, "pinned-tool", type="tool", decay_class="evergreen", confidence=0.5)
    _entity(memory, "exam-week", type="concept", decay_class="volatile", confidence=0.4,
            last_referenced="2026-09-01")
    _entity(memory, "old-interest", type="concept", confidence=0.9, last_referenced="2026-07-01")
    _entity(memory, "saved-link", type="media", decay_class="evergreen", confidence=0.9)
    _entity(memory, "ask-first", type="skill", confidence=0.4, tags=["autonomy"],
            body="## Summary\nAsk before acting on anything irreversible.\n")
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["schema_version"] == 2
    assert [s["id"] for s in fm["standing"]] == ["local-first", "pinned-tool"], "confidence alone, no recency"
    assert [f["id"] for f in fm["focus"]] == ["exam-week"], "active/volatile, touched in 14 days"
    assert [p["id"] for p in fm["preferences"]] == ["ask-first", "concise-summaries"], "a working tag sorts first"
    assert "saved-link" not in str(fm["standing"]) + str(fm["focus"]), "an artifact is never a belief row"
    for heading in ("## In focus (last 14 days)", "## How to work with me", "## Standing"):
        assert heading in body


def test_the_owner_row_comes_from_the_one_resolver(tmp_path):
    memory = _bank(tmp_path)
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert "owner_id" not in fm
    from api.services import owner_identity
    owner_identity.save_owner({"entity_id": "bob-example"})
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["owner_id"] == "bob-example", "G117's owner.json, not only the env override"
    assert fm["owner_one_liner"].startswith("Bob Example is a synthetic fixture")
    assert "## The person" in body


def test_the_schema_is_an_input(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    before = state_dictionary.inputs_version(memory)
    monkeypatch.setattr(state_dictionary, "SCHEMA_VERSION", 99)
    assert state_dictionary.inputs_version(memory) != before, "an upgraded backend rebuilds a v1 file once"


def test_the_size_cap_gives_up_current_before_standing_and_keeps_the_agreements(tmp_path):
    memory = _bank(tmp_path)
    long = "## Summary\n" + "A long synthetic line " * 8 + ".\n"
    for i in range(40):
        _entity(memory, f"focus-{i:02d}", type="concept", decay_class="volatile", last_referenced="2026-09-02", body=long)
        _entity(memory, f"standing-{i:02d}", type="concept", decay_class="durable", confidence=0.9, body=long)
        _entity(memory, f"person-{i:02d}", type="person", confidence=0.9, body=long)
    settings = _settings(memory, state_people=40, state_focus=40, state_standing=40)
    fm, body = state_dictionary.build(memory, settings, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert len(state_dictionary.render(fm, body).encode("utf-8")) <= state_dictionary.MAX_BYTES
    assert not fm["people"] and not fm["focus"], "current rows go first"
    assert fm["preferences"] and fm["projects"], "the working agreements and the projects stay"
```

    (The file's `_tmp_home` autouse fixture already points `CICADA_HOME` at a tmp directory, so
    `save_owner` writes there.)
  - Change the two pinned schema versions to 2: `test_state_dictionary.py:33`
    (`fm["schema_version"] == 1`) and `test_state_wiring.py:150` (`data["schema_version"] == 1`).
    Both go red the moment `SCHEMA_VERSION` moves, and both are this task's.
  - Append to `api/tests/test_handshake.py`, and change its `CONTRACT_VERSION == 2` assertion
    (`:55`) to `== 3`:

```python
# --- G140 Q-R13/Q-R14: standing and current, identity and timezone -----------

from _synthetic_bank import _entity  # noqa: E402
from api.remote import catalog  # noqa: E402


def test_the_now_view_splits_standing_from_current(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "local-first", type="concept", decay_class="durable", confidence=0.9)
    _entity(memory, "exam-week", type="concept", decay_class="volatile", last_referenced="2026-09-02")
    state_dictionary.refresh(memory, _settings(memory, observer_owner="bob-example"), force=True,
                             today=TODAY, now=NOW, repo_resolver=_ok_repo)
    state = state_dictionary.read_state(memory)
    text = handshake.build(state, variant="generic", bank="memory", tz="Europe/Madrid")
    standing, current = text.split("### Standing — changes rarely", 1)[1].split("### Current — in motion", 1)
    assert "`bob-example` — Bob Example is a synthetic fixture" in standing
    assert "Their timezone: Europe/Madrid." in standing
    assert "How to work with me: Prefers concise summaries over long reports." in standing
    assert "`local-first`" in standing and "`exam-week`" in current and "`alpha-project`" in current
    assert len(text) // 4 <= handshake.MAX_TOKENS
    remote = handshake.build_remote(state, tools=catalog.tool_names_for(catalog.DEFAULT_SCOPES), bank="memory",
                                    tz="Europe/Madrid")
    assert "### Standing" in remote and "Europe/Madrid" in remote and len(remote) // 4 <= handshake.MAX_TOKENS


def test_a_v1_state_file_still_renders():
    state = {"type": "state", "generated_at": NOW.isoformat(), "bank": "memory", "engine": {}, "sleep": {},
             "inbox": {}, "projects": [], "people": [], "conversations": [],
             "preferences": [{"id": "p", "name": "P", "one_liner": "Short replies."}]}
    text = handshake.build(state, variant="generic", bank="memory")
    assert "How to work with me: Short replies." in text and "### Current — in motion" in text


def test_the_primer_gives_up_current_rows_before_the_working_agreements():
    big = [{"id": f"x-{i}", "name": "N" * 60, "one_liner": "o" * 110} for i in range(80)]
    state = {"type": "state", "generated_at": NOW.isoformat(), "bank": "memory", "engine": {}, "sleep": {},
             "inbox": {}, "projects": [{"id": "alpha-project", "name": "Alpha Project", "one_liner": "Alpha."}],
             "people": big, "focus": big, "standing": big,
             "conversations": [{"id": f"c{i}", "harness": "codex", "title": "T" * 60} for i in range(80)],
             "preferences": [{"id": "ask-first", "name": "Ask First", "one_liner": "Ask before acting."}]}
    text = handshake.build(state, variant="generic", bank="memory")
    assert len(text) // 4 <= handshake.MAX_TOKENS
    assert "How to work with me: Ask before acting." in text and "`alpha-project`" in text
    assert "People recently in play" not in text and "In focus" not in text


def test_the_timezone_is_per_request_never_persisted_and_moves_the_cache(tmp_path, monkeypatch):
    memory = _with_state(tmp_path)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "Europe/Madrid")
    a, _ = handshake.load_or_build(memory, "claude-code", cache_dir=tmp_path / "c")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "America/Lima")
    b, meta = handshake.load_or_build(memory, "claude-code", cache_dir=tmp_path / "c")
    assert "Europe/Madrid" in a and "America/Lima" in b and meta["cached"] is False
    assert "Madrid" not in (memory / "_state.md").read_text(encoding="utf-8")


def test_the_contract_names_the_new_tools():
    text = handshake.build(None, variant="generic", bank="memory")
    for needle in ("cicada_timeline(since)", "cicada_record_watch(url, summary, excerpts=[{t, quote}])",
                   "`expected_end`", "cicada_retract_claim(subject, claim_id, reason)",
                   "cicada_recall_detail(entity_id)"):
        assert needle in text, needle
    remote = handshake.build_remote(None, tools=frozenset(catalog.TOOL_SCOPE), bank="memory")
    assert "cicada_retract_claim" in remote and "deletes or rewrites" not in remote
```

- [ ] **Step 2:** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_handshake_r12.py api/tests/test_state_dictionary.py api/tests/test_handshake.py -q -p no:cacheprovider`.
  Expected failures: `cicada_recall_detail(id)` is caught by the R12 test; `standing` and `focus`
  are missing; there is no `tz` keyword.
- [ ] **Step 3: Implement `state_dictionary.py`.**
  1. `SCHEMA_VERSION = 2`. `_DEFAULTS` gains `"state_standing": 5, "state_focus": 5`. Below
     `_DEFAULTS`, add:

```python
# G140 Q-R13 (R3 P5) — the now-view split by the decay classes (G66) every
# page already carries: STANDING is what changes rarely, CURRENT what is in
# motion. Supermemory's static/dynamic profile and its [Summary]/[Recent]
# labels are the same idea; Cicada needs no classifier and no prose.
STANDING_CLASSES = frozenset({"durable", "evergreen"})
CURRENT_CLASSES = frozenset({"active", "volatile"})
FOCUS_WINDOW_DAYS = 14
# Types with a row of their own (projects, people), artifacts (a bookmark is
# evergreen and would flood "standing"), paths and the retired deadline type.
_OWN_ROW_TYPES = frozenset({"project", "person", "media", "directory", "deadline"})
# A tag convention, not a producer: a skill page tagged with one of these is a
# working agreement ("ask before acting", "short replies") and sorts first in
# "How to work with me". Stage 4 writes `tags: []` today, so the row never
# depends on it (Instinct's "autonomy calibration", R3 P5).
WORKING_TAGS = frozenset({"autonomy", "communication-style", "working-style"})
```

  2. `inputs_version` sets `parts["schema"] = SCHEMA_VERSION` before hashing, with the comment:
     `# G140: the schema is an input — an upgraded backend rebuilds a v1 file once instead of serving it until something else changes.`
  3. After `_one_liner`, add:

```python
def _class_of(fm: dict) -> str:
    from api.services import decay_policy

    cls, _ = decay_policy.resolve(fm)
    return str(getattr(cls, "value", cls))


def _confidence(fm: dict) -> float:
    try:
        return float(fm.get("confidence", 0.5) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _live(fm: dict) -> bool:
    return str(fm.get("status", "active") or "active").lower() not in _ARCHIVED


def _row(f: bank_index.IndexedFile) -> dict:
    return {"id": f.stem, "name": _name(f), "one_liner": _one_liner(f)}


def _preferences(memory_path: Path, n: int) -> list[dict]:
    """How to work with me (Q-R13): `skill` pages whose class is standing,
    ranked by confidence ALONE — the old `/(1 + days/30)` term let a standing
    preference fall out after a quiet month (R3 P5). Working-agreement tags
    sort first; ties break on id so two runs agree (R1)."""
    rows = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        if str(fm.get("type") or "") != "skill" or not _live(fm) or _class_of(fm) not in STANDING_CLASSES:
            continue
        raw_tags = fm.get("tags")
        tags = {str(t).strip().lower() for t in raw_tags} if isinstance(raw_tags, list) else set()
        rows.append((0 if tags & WORKING_TAGS else 1, -_confidence(fm), f.stem, f))
    rows.sort(key=lambda r: r[:3])
    return [_row(r[3]) for r in rows[: max(0, n)]]


def _standing(memory_path: Path, n: int) -> list[dict]:
    """What lasts (Q-R13): non-skill pages outside the own-row types whose
    class is durable or evergreen, by confidence."""
    rows = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        etype = str(fm.get("type") or "")
        if etype in _OWN_ROW_TYPES or etype == "skill" or not _live(fm):
            continue
        if _class_of(fm) in STANDING_CLASSES:
            rows.append((-_confidence(fm), f.stem, f))
    rows.sort(key=lambda r: r[:2])
    return [_row(r[2]) for r in rows[: max(0, n)]]


def _focus(memory_path: Path, today: date, n: int) -> list[dict]:
    """What is in motion (Q-R13): pages outside the own-row types whose class
    is active or volatile and that were referenced in the last
    ``FOCUS_WINDOW_DAYS``; most recent first, volatile before active."""
    rows = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        if str(fm.get("type") or "") in _OWN_ROW_TYPES or not _live(fm):
            continue
        cls = _class_of(fm)
        days = _days_since(fm.get("last_referenced"), today)
        if cls in CURRENT_CLASSES and days <= FOCUS_WINDOW_DAYS:
            rows.append((days, 0 if cls == "volatile" else 1, -_confidence(fm), f.stem, f))
    rows.sort(key=lambda r: r[:4])
    return [{**_row(r[4]), "last_referenced": str(r[4].frontmatter.get("last_referenced") or "")[:10] or None}
            for r in rows[: max(0, n)]]


def _owner(memory_path: Path, settings) -> tuple[str | None, str]:
    """The person's own page and its one-liner (Q-R13) — through
    ``owner_identity.resolve_observer``, the one resolver every writer has
    used since G117. The builder used to read only the env override, so a
    bank onboarded in the app never showed its owner here. Only a page that
    exists; never a name in code (the portability rail)."""
    from api.services import owner_identity

    try:
        owner = str(owner_identity.resolve_observer(memory_path, settings) or "").strip()
    except Exception:  # noqa: BLE001 — a cursor row is never worth a failed build
        return None, ""
    for f in bank_index.files(memory_path, "entities") if owner else []:
        if f.stem == owner:
            return owner, _one_liner(f)
    return None, ""
```

  4. In `build`:
     - Replace the `preferences = [...]` assignment with
       `preferences = _preferences(memory_path, _limit(settings, "state_preferences"))`.
     - Replace the owner block (`:387-391`) with:

```python
    # Portability rail: the owner is an entity id from the one resolver (G117),
    # never a name in code, and only when that page exists in this bank.
    owner_id, owner_line = _owner(memory_path, settings)
    if owner_id:
        fm["owner_id"] = owner_id
        if owner_line:
            fm["owner_one_liner"] = owner_line
```

     - In `fm.update({...})`, after `"preferences": preferences,` add
       `"standing": _standing(memory_path, _limit(settings, "state_standing")), "focus": _focus(memory_path, today, _limit(settings, "state_focus")),`.
  5. Replace `render_body` with:

```python
def render_body(fm: dict) -> str:
    """The human-readable half: a cursor (wikilinks + ids), never entity
    bodies. G140 Q-R13: the person, then what is in motion, then what lasts."""
    def row(p: dict) -> str:
        return f"- [[{p['name']}]] (`{p['id']}`)" + (f" — {p['one_liner']}" if p.get("one_liner") else "")

    lines = ["# Cicada — now", "",
             f"Bank `{fm['bank']}` · engine {fm['engine']['engine']} ({fm['engine']['model'] or 'unset'}) · "
             f"inbox {fm['inbox']['pending']} pending · queue {fm['sleep']['queue_depth']} · "
             f"last Sleep {fm['sleep']['last_at'] or 'never'} · as of {fm['generated_at']}"]
    if fm.get("owner_id"):
        lines += ["", "## The person",
                  f"- `{fm['owner_id']}`" + (f" — {fm['owner_one_liner']}" if fm.get("owner_one_liner") else "")]
    lines += ["", "## Projects"]
    for p in fm["projects"]:
        repo_bits = ", ".join(
            f"{r['path']}@{r['branch']}" + (f" (dirty {r['dirty']})" if r.get("dirty") else "")
            if r.get("state") == "ok" else f"{r['path']} ({r.get('state')})" for r in p.get("repos", [])
        )
        tail = f" — {p['one_liner']}" if p.get("one_liner") else ""
        lines.append(f"- [[{p['name']}]] (`{p['id']}`){tail}" + (f" — repo: {repo_bits}" if repo_bits else ""))
    if not fm["projects"]:
        lines.append("- (no active projects yet)")
    lines += ["", f"## In focus (last {FOCUS_WINDOW_DAYS} days)"]
    lines += [row(p) for p in fm.get("focus") or []] or ["- (nothing recent)"]
    lines += ["", "## People"]
    lines += [row(p) for p in fm["people"]] or ["- (none yet)"]
    lines += ["", "## Recent conversations"]
    lines += [f"- `{c['id']}` · {c['harness'] or 'unknown'} · {c['title']} · {c['last_seen'][:10]}"
              for c in fm["conversations"]] or ["- (none recorded)"]
    lines += ["", "## How to work with me"]
    lines += [row(p) for p in fm["preferences"]] or ["- (none extracted yet)"]
    lines += ["", "## Standing"]
    lines += [row(p) for p in fm.get("standing") or []] or ["- (none yet)"]
    lines += ["", "## Rules for agents",
              f"- {fm['world_facts_note']}",
              "- This file is a cursor: open `entities/<id>.md` (or `cicada_recall_detail`) for the page; `_index.md` is the map.",
              "- Never edit entity files directly — write through `cicada_write_claim` / `cicada_save_episode`."]
    return "\n".join(lines)
```

  6. In `_fit`:
     - The trim loop becomes
       `for key in ("people", "focus", "standing", "conversations", "preferences", "projects"): while fm.get(key) and size() > MAX_BYTES: fm[key].pop()`.
     - The comment becomes: `G140 Q-R13: current rows go before standing ones, the working agreements late, and projects last (R10's reason stands).`
- [ ] **Step 4: Implement `handshake.py`.**
  1. Change `CONTRACT_VERSION = 3`, and add to its comment:
     `# 3: G140 — timeline, record_watch, expected_end and retract named; recall_detail(entity_id) (R12).`
     Change `REMOTE_CONTRACT_VERSION = 2` with the same reason.
  2. In `_CONTRACT`, replace items 1, 3 and 4 (item 2 and items 5–7 stay byte-identical):

```python
    "1. Recall first: `cicada_recall(query)` at the start of a topic, `cicada_recall_detail(entity_id)` for a "
    "page, `cicada_ask` for a direct factual question, `cicada_timeline(since)` for what changed recently. State "
    "only what the tools returned.\n"
    # item 2 unchanged
    "3. Save as you learn: `cicada_save_episode(content, title)` for a decision, plan or fact worth keeping; "
    "`cicada_save_url` for a link; after watching a video the person saved, `cicada_record_watch(url, summary, "
    "excerpts=[{t, quote}])` — short timestamped quotes, never the transcript.\n"
    "4. Write facts as claims: `cicada_write_claim(subject, predicate, object, evidence=[{episode, quote}], "
    "sources=[url])` — quote the exact words you relied on, give `sources` for anything you looked up, and "
    "`expected_end` when the fact states an end; withdraw a claim you wrote that proved wrong with "
    "`cicada_retract_claim(subject, claim_id, reason)`.\n"
```

  3. In `_remote_contract`:
     - The `reads` tuple:
       - uses `` "`cicada_recall_detail(entity_id)` for a page" ``;
       - gains `("cicada_timeline", "`cicada_timeline(since)` for what changed recently")`.
     - After the `cicada_save_episode` item, add:

```python
    if "cicada_record_watch" in tools:
        items.append("After watching a video the person saved: `cicada_record_watch(url, summary, "
                     "excerpts=[{t, quote}])` — short timestamped quotes, never the transcript.")
```

     - The `cicada_write_claim` item ends
       `"… quote the exact words you relied on; add `expected_end` when the fact states an end."`.
     - Then add:

```python
    if "cicada_retract_claim" in tools:
        items.append("Withdraw a claim this connection wrote that proved wrong with "
                     "`cicada_retract_claim(subject, claim_id, reason)`; it stays in history with your reason.")
```

     - The closing item becomes `"Nothing here deletes memory: every write is added with its source, and nothing you write overrides what the person said."`,
       with the comment `# Q-R14: withdrawing one's own claim rewrites its validity, so "or rewrites" went.`
  4. Add `local_timezone` after `variant_for`:

```python
def local_timezone() -> str | None:
    """The machine's IANA zone (``Europe/Madrid``) — G140 Q-R13, Instinct's
    identity block without the account email. Per request, never stored:
    ``_state.md`` travels with the bank (portability) and an idle night must
    not commit because its owner travelled (R1). ``tzlocal`` is APScheduler's
    own dependency, already installed; a failure falls back to the UTC
    offset, and ``None`` only when even that is unknown."""
    try:
        from tzlocal import get_localzone_name

        name = get_localzone_name()
        if name:
            return str(name)
    except Exception:  # noqa: BLE001 — a primer line is never worth a failed connect
        pass
    offset = datetime.now().astimezone().strftime("%z")
    return f"UTC{offset[:3]}:{offset[3:]}" if offset else None
```

  5. Replace `_now_block` with the version below. The old docstring's first paragraph is kept and
     the G140 paragraph is added.

```python
def _now_block(state: dict | None, bank: str, *, remote: bool = False, tz: str | None = None) -> str:
    """``remote`` (G135 R-R15) drops what a caller off this Mac must not see
    or cannot act on: the `GET /state` hint (a loopback endpoint) and every
    repo path. Repo paths never leave the Mac. Stdio output is unchanged.

    G140 Q-R13 (R3 P5) splits the view by the decay classes: **Standing** —
    the person, their timezone, how to work with them, what lasts
    (durable/evergreen) — and **Current** — projects, pages in focus this
    fortnight, people, recent conversations (active/volatile). Every row is
    an id or a one-liner already on a page; ``tz`` comes from
    ``load_or_build`` per request and never from the file."""
    tz_line = f"- Their timezone: {tz}." if tz else None
    if state is None and remote:
        head = f"## Now\n- Bank `{bank}` has no now-view yet; the contract above still applies."
        return head + (f"\n{tz_line}" if tz_line else "")
    if state is None:
        head = (
            "## Now\n"
            f"- Bank `{bank}` has no `_state.md` yet — run a Sleep cycle or `GET /state?refresh=true` "
            "to generate the now-view; the contract above still applies."
        )
        return head + (f"\n{tz_line}" if tz_line else "")
    eng = state.get("engine") or {}
    slp = state.get("sleep") or {}
    inb = state.get("inbox") or {}
    lines = [
        "## Now",
        f"- Bank `{state.get('bank', bank)}` · engine {eng.get('engine')} ({eng.get('model') or 'unset'}) · "
        f"inbox: {inb.get('pending', 0)} pending · Sleep queue {slp.get('queue_depth', 0)} · "
        f"last Sleep {slp.get('last_at') or 'never'} · as of {state.get('generated_at')}",
    ]
    standing: list[str] = []
    if state.get("owner_id"):
        one = state.get("owner_one_liner")
        standing.append(f"- The person's own entity: `{state['owner_id']}`" + (f" — {one}" if one else "."))
    if tz_line:
        standing.append(tz_line)
    prefs = state.get("preferences") or []
    if prefs:
        standing.append("- How to work with me: " + "; ".join(p.get("one_liner") or p["name"] for p in prefs))
    lasting = state.get("standing") or []
    if lasting:
        standing.append("- Long-standing: " + "; ".join(f"`{s['id']}` {s['name']}" for s in lasting))
    if standing:
        lines += ["### Standing — changes rarely", *standing]
    lines.append("### Current — in motion")
    projects = state.get("projects") or []
    lines.append("- Current projects:" if projects else "- No active projects recorded yet.")
    for p in projects:
        repos = "" if remote else ", ".join(
            f"{r['path']}@{r.get('branch')}" + (f" dirty {r['dirty']}" if r.get("dirty") else "")
            for r in p.get("repos", []) or [] if r.get("state") == "ok"
        )
        tail = f" — {p['one_liner']}" if p.get("one_liner") else ""
        lines.append(f"  - `{p['id']}` {p['name']}{tail}" + (f" [{repos}]" if repos else ""))
    focus = state.get("focus") or []
    if focus:
        lines.append(f"- In focus (last {state_dictionary.FOCUS_WINDOW_DAYS} days): "
                     + ", ".join(f"`{f['id']}` {f['name']}" for f in focus))
    people = state.get("people") or []
    if people:
        lines.append("- People recently in play: " + ", ".join(f"`{p['id']}`" for p in people))
    convs = state.get("conversations") or []
    if convs:
        lines.append("- Recent conversations (id · harness · title):")
        for c in convs:
            lines.append(f"  - `{c['id']}` · {c.get('harness') or 'unknown'} · {c.get('title', '')}")
    return "\n".join(lines)
```

  6. Thread `tz` through:
     - `_assemble(state, variant, bank, tz=None)` passes `_now_block(state, bank, tz=tz)`.
     - `build(state, *, variant, bank, tz=None)` passes `lambda st: _assemble(st, variant, bank, tz)`.
     - `build_remote(state, *, tools, bank, tz=None)` passes `_now_block(st, bank, remote=True, tz=tz)`.
  7. Replace `_fit` with:

```python
def _fit(assemble, state: dict | None) -> str:
    text = assemble(state)
    if len(text) // 4 <= MAX_TOKENS or state is None:
        return text
    slim = dict(state)
    # G140 Q-R13: current rows before standing ones, the working agreements
    # last — the most useful tokens per line (Instinct's "autonomy
    # calibration"). Projects keep R10's place: the list a cursor exists for.
    for key in ("people", "focus", "conversations", "standing"):
        slim[key] = []
        text = assemble(slim)
        if len(text) // 4 <= MAX_TOKENS:
            return text
    slim["projects"] = [{**p, "one_liner": ""} for p in slim.get("projects", []) or []]
    text = assemble(slim)
    if len(text) // 4 <= MAX_TOKENS:
        return text
    slim["preferences"] = [{**p, "one_liner": ""} for p in slim.get("preferences", []) or []]
    return assemble(slim)
```

  8. In `load_or_build`, directly after the `stamp` is computed, add
     `tz = local_timezone()` and `tz_key = tz or "-"`, with the comment:
     `# G140 Q-R13: the zone is per request and part of the key — never in the file.`
     Then:
     - The remote key becomes `f"r{REMOTE_CONTRACT_VERSION}:{cache_name}:{stamp}:{tz_key}"` and its
       `make` passes `tz=tz`.
     - The local key becomes `f"{CONTRACT_VERSION}:{variant}:{stamp}:{tz_key}"` and its `make`
       passes `tz=tz`.
  9. The module docstring's "Shape:" paragraph gains:
     `The now-view is Standing (the person, their timezone, how to work with them, what lasts) then Current (G140).`
- [ ] **Step 5: Green.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_handshake_r12.py api/tests/test_state_dictionary.py api/tests/test_handshake.py api/tests/test_handshake_remote.py api/tests/test_mcp_handshake.py api/tests/test_remote_tools.py api/tests/test_remote_runtime.py api/tests/test_state_wiring.py api/tests/test_owner_name_portability.py -q -p no:cacheprovider`
  Everything must be green. Then:
  - Check that nothing still says "Standing preferences":
    `cd <worktree> && grep -rn --exclude-dir=.venv "Standing preferences" api app/CicadaApp/Sources SKILL.md skills`
    must print nothing (`SKILL.md` points at the generated text; `--exclude-dir` keeps grep out of
    the virtualenv).
  - Fix `SKILL.md:44`: `cicada_open_hub(hub_id)` becomes `cicada_open_hub(hub)`.
- [ ] **Step 6: Commit.** Stage `SKILL.md` and `api/tests/test_state_wiring.py` with the rest.
  Message: `feat(handshake): Standing and Current, the person and their timezone, how to work with me; contract v3 names the new tools (G140 Q-R13/Q-R14, R3 P5, G53, G75)`.

### Task 8: Docs — G140, the row edits, CLAUDE.md and TODO.md

**Files:** `docs/goals/memory-evolution.md`, `CLAUDE.md`, `docs/goals/TODO.md`.

Every insertion below is written for a public repo:
- no bank contents;
- no names from the bank;
- placeholders only;
- the article's author and product may be named.

The rows are single table lines. Edit them with the Edit tool against a unique fragment. Never
rewrite a row wholesale.

- [ ] **Step 1: Add row G140** directly after the last existing `| G1…` row (today G137; if Tracks
  O/I/N landed G138/G139 first, after those):

```markdown
| G140 | **What the Instinct comparison changed — memory quality borrowed on Cicada's rails, and the video watch record** (Rodrigo 2026-09-23, on Dhravya Shah's article reverse-engineering the memory of the Instinct iMessage assistant: "I think maybe some things here can be of use. See what and see if we can work on implementing." — and on a video-watching skill: "Could match well for storing and having info about videos. Maybe getting the metadata or whatever else.") | **The article, in one line.** Instinct keeps git-tracked markdown, injects a ~4.25k-token LLM-written profile (life context, autonomy calibration, communication style) plus a compaction recap, retrieves by grep over files that carry `aliases`, reconciles once a day, and forgets only explicit negations; the author's supermemory replication adds a static/dynamic profile, time-based expiry and auto-included history. Everything about Instinct is inferred from outside the product. **Adopted (Track Q, `feat/memory-quality`, plan `../superpowers/plans/2026-09-23-memory-quality.md`, rulings Q-R1…Q-R17):** (1) *aliases and word-by-word matching* — MCP recall's keyword leg was a whole-query substring that never read `aliases`; it is now `search_service`'s lexical leg (the G136 hand-off); (2) *relationship labels resolve* — current claims are recall's third RRF leg, mapped to their subject; (3) *old versions, bounded* — recall shows claims closed in the last 30 days as `was X until D → now Y` (≤ 2 a page, ≤ 5 in all) and `cicada_get_perspective(history=true)` lists every earlier claim; the dead `include_superseded` on the vector claims index is removed (it could only surface a state no writer produces); (4) *a static/dynamic profile without prose* — the primer's now-view splits into Standing (the person's page and one-liner via G117's resolver, their timezone per request and never stored, "How to work with me" = standing `skill` pages by confidence alone, long-standing durable/evergreen pages) and Current (projects, pages in focus in the last 14 days, people, conversations), read off the G66 decay classes; (5) *a timeline an agent can read* — `cicada_timeline(since)` reads the commit manifests on demand, ids and counts only, nothing stored; (6) *explicit negation, with provenance* — `cicada_retract_claim` lets an agent withdraw a claim IT wrote: the claim closes, a born-closed `retracts` record keeps the reason and any cited words, nothing is deleted, a human or Sleep claim is refused; (7) *time-based expiry* — a claim may carry `expected_end` (or be a G17 `due` date) and Sleep's engine-free tail closes it the day after, in a `cicada`-authored `Expiry <date>` commit (trigger `sleep/expiry`). **Video (R5):** `cicada_save_url` keeps a note given for an already-saved link and names the episode to cite; an agent's note is written as the agent's words; `external:<name>` is a value the observer schema accepts; `cicada_record_watch(url, summary, excerpts=[{t, quote}], chapters?)` records a watch as one episode + one `describes` claim whose spans are `assistant` (the summary) and `media` (each quote, time derived at read) — excerpts only, never a transcript, and Cicada never downloads a video; Vimeo/Loom descriptions are kept and chapters parsed from them. **Already better in Cicada, kept:** commit trailers naming author, engine and session vs bare reconciliation commits; typed, bi-temporal claims with trust tiers vs bullet lists of dated prose; supersede-never-delete vs prose rewrites; evidence spans with hash staleness (G118) vs no link from a fact to its sentence; temporal decay (G66) vs no automatic forgetting; one episode per session (G104) vs one document per day; capture with no intake ceiling vs "come back tomorrow"; a dated, deterministic cursor (`_state.md`) vs an unstamped profile with a measured ~2-day lag; hybrid retrieval vs grep (Instinct's own probes miss a paraphrase). **Rejected, and the rail that rejects it:** an LLM-written profile (G53: a cursor, never a copy; stale by construction; a daily cost); redundant fan-out writes (G101's stable address — Instinct itself reports stale duplicates); a "compress and remove incidental details" pass (destroys G118 spans; recall already truncates at read); read-only agent memory (the two-way port); supermemory as a backend (hosted and closed, replaces git — breaks G50/G76/G92 and the trailers); a daily-only intake with a token cap; an in-context todo board. **Open:** P9 — the article's 13-point rubric as a $0 retrieval eval on the demo bank (expected id in recall top-k for single fact, alias, paraphrase, typo, relationship label, superseded-not-current, abstention, two-hop; the LLM-judged half on demand) — the harness **G78** asks for; P3 secret and one-time-code scrubbing on every episode writer (Local-sources track, R-N3 — including the two writers this row added); P10 an open-loops cursor row; P11 a "last time in this project" pointer; typo tolerance; Stage-1 extraction of stated ends from prose (a paid prompt change); the person's own "that's off" closing a user-stated claim and entity-level forget through a `removal` item (P7's broader half); an app surface for the timeline, the watch record (▶ m:ss chips, a Watched pill, chapter seek buttons) and withdrawals. → extends **G53**, **G75**, **G93**, **G118**, **G136**, **G66**, **G17**, **G22**, **G113**; feeds **G78**. | 🛠️ adopted parts shipped; P9 open |
```

- [ ] **Step 2: Edit the named rows.** Each insertion goes immediately before the row's final ` | <status> |`.
  - **G22**, insert:
    `**G140 (2026-09-23, `feat/memory-quality`):** the four defects in the documented watch chain are fixed — a note for an already-saved video is kept as its own episode instead of dropped; both save replies name the episode to cite; `external:<name>` is a value the observer schema accepts; and a watch is recorded by `cicada_record_watch(url, summary, excerpts=[{t, quote}], chapters?)` as one episode (`assistant:` summary, `video [m:ss]:` quotes) plus one `describes` claim whose quote spans have the new `media` kind — excerpts only, never a transcript (R5 D3), Cicada never downloads a video. Vimeo/Loom descriptions are kept and chapters parsed from them (`media.chapters`). The row's "transcript stored with the entity" is superseded by cited excerpts. Open: the app's watch UI (Track P/O).`
    Then change the status cell to:
    `🛠️ partial (save + watch record + `media` spans shipped; the in-app watch UI and the recommended skill are Tracks P/O)`.
  - **G53**, insert:
    `**G140 (2026-09-23): schema v2.** The now-view reads the G66 classes — `standing` (durable/evergreen non-skill pages), `focus` (active/volatile pages referenced in the last 14 days), `preferences` re-ranked by confidence alone with working-agreement tags first — and the owner comes from `owner_identity.resolve_observer` with an `owner_one_liner` (the builder used to read only the env override). `inputs_version` folds in the schema, so an upgraded backend rebuilds once. Trim order: people → focus → standing → conversations → preferences → projects. The timezone is never written here (it is per request, in the handshake).`
  - **G75**, insert:
    `**G140 (2026-09-23, `CONTRACT_VERSION` 3, remote 2):** Standing ("changes rarely": the person, their timezone per request, How to work with me, long-standing pages) / Current ("in motion"); the contract names `cicada_timeline(since)`, `cicada_record_watch(url, summary, excerpts=[{t, quote}])`, `expected_end` and `cicada_retract_claim(subject, claim_id, reason)`; the cache key carries the timezone. A new test enforces R12 for ARGUMENTS in both primers (every scope set) and found `cicada_recall_detail(id)` — the property is `entity_id` — fixed.`
  - **G118**, insert:
    `**G140 (2026-09-23):** a fifth kind, `media` — what a video said, a `video [m:ss]:` line in a watch episode (the time is required, so a person's own "Video: …" line stays theirs); `speaker_kind` and `turns()` share one `_role()`, and the position is derived at read (`evidence.media_time`, served as `t` on `/episodes/{id}/span` and each turn), never stored. An agent's note on a saved link is written under `assistant:` so it never reads as the person's.`
  - **G136**, insert:
    `**G140 (2026-09-23):** MCP recall adopted the hand-off — its keyword leg is `lexical_entity_hits`, current claims are its third RRF list through `claim_subject_hits`, and `mcp_tools._rrf_fuse` IS `search_service.rrf_fuse` (the parity test went).`
    Then, in the same row's **Open:** list, change `payload measurement), MCP recall adoption.` to
    `payload measurement).` The adoption is done.
- [ ] **Step 3: `CLAUDE.md`.** Four precise edits (the second touches three lines), at the density
  of the surrounding text. Match the file as it is: several sentences wrap across lines, so edit
  against a unique fragment:
  1. In *Claims, evidence and provenance*, change "`kind` is `user` | `assistant` | `page` | `reasoning`"
     to "`kind` is `user` | `assistant` | `page` | `reasoning` | `media`". After that sentence's
     parenthesis ends, add:
     `` `media` is what a video said — a watch record's `video [m:ss]:` line (G140); its position is derived at read, never stored. ``
     After the paragraph, add a new one:

     > **Stated ends (G140).** A claim may carry `expected_end` — the date the fact itself says it stops being true — and a G17 `due` claim's ISO-date object is its own. Never a future `valid_to`, which every reader takes to mean *closed*. Sleep's engine-free tail closes such a claim the day after its end (`claim_expiry`), in its own `Expiry <date>` commit (`Cicada-Author: cicada`, trigger `sleep/expiry`); a failed commit restores the pages rather than leaving them for the next `git add -A` writer. An agent withdraws a claim IT wrote with `cicada_retract_claim`: the claim closes and a born-closed `retracts` record keeps the reason and any cited words; a human or Sleep claim is never an agent's to withdraw.

  2. In the **Triggers:** list, add `sleep/expiry` after `sleep/state`. In the `Cicada-Author:`
     bullet, the `cicada` list "(the one-shot migrations, the split-out decay commit, the `State
     snapshot` commit)" gains "the `Expiry` commit". In *Sleep*'s engine-independent tail
     sentence ("the state-dictionary refresh, the connector poll, …"), add "claim expiry (first in
     the clean-tree-guarded slot, its own `commit_paths` commit)" after "the state-dictionary
     refresh".
  3. In *Live state + handshake*, after the sentence ending "…the now-view, and capability notes.", add:

     > The now-view is **Standing** — the person's page and one-liner (through G117's resolver), their timezone (per request, never in `_state.md`, part of the cache key), *How to work with me* (standing `skill` pages by confidence alone), long-standing durable/evergreen pages — then **Current** — projects, pages in focus in the last 14 days, people, recent conversations (G140, schema v2). A test holds R12 for every argument either primer names, for every remote scope set.

  4. In *MCP "Bookworm" Tool*, after the first paragraph, add:

     > **Recall (G140).** Three legs fused by one RRF (`search_service.rrf_fuse`): the stored vectors, the FTS lexical leg (names, aliases and prose, word by word), and current claims mapped to their subject — so an alias or a relationship label reaches its page. The top three pages carry a bounded "Changed recently" block (claims closed in the last 30 days, ≤ 5 lines); `cicada_get_perspective(history=true)` lists every earlier claim. **`cicada_timeline(since)`** answers "what changed" from the commit manifests on demand — ids and counts only, nothing stored, `read` scope remotely. **`cicada_record_watch`** records what an agent's own tools saw in a saved video — a summary and ≤ 12 timestamped quotes as `media` spans; Cicada never downloads or watches a video, and never keeps a transcript.

- [ ] **Step 4: `TODO.md`.** Under *Where things stand*, after the Track S-back paragraph, add:

  > **Round 3, Track Q — memory quality from the Instinct comparison + the video watch record (2026-09-23, `feat/memory-quality`, G140).** Recall reads aliases, words and claims (the G136 hand-off) and shows bounded dated history; `cicada_timeline`, `cicada_retract_claim` and `cicada_record_watch` are new; stated ends (`expected_end`, `due`) close on Sleep's tail in a `cicada` `Expiry` commit; the primer is Standing/Current with the person, their timezone and How to work with me (contract v3); the video chain's four defects are fixed and `media` is the fifth evidence kind. Backend **<N> passed** on the branch (2714 on its base). P9 (the rubric eval) is open in G140. Hand-offs: Track P renders `media` spans and `t`; Track O's skills manifest names `cicada_record_watch`; the Local-sources scrub wraps the two new episode writers.

  Replace `<N>` with the full-suite count measured in the final verification.
- [ ] **Step 5: Commit.** `docs: G140 — what the Instinct comparison changed; G22/G53/G75/G118/G136, CLAUDE.md, TODO.md`.

---

## Not in scope

Listed so a reviewer reads an absence as a decision, not an oversight.

- **P9, the 13-point rubric eval** (Q-R15). It is recorded open in G140 with its design.
- **P3, secret and one-time-code scrubbing on every episode writer.** That is the Local-sources
  track's (R-N3). It must wrap this track's two new writers (see Hand-off).
- **P10 (an open-loops cursor row) and P11 (a "last time in this project" pointer).**
- **Stage-1 extraction of stated ends from prose** ("this weekend"). That is a paid prompt change.
  Only explicit ends expire (Q-R6).
- **Typo tolerance in recall** (R3 P1's `difflib`). G136 kept it out of the server default.
- **R3 P7's broader half:** the person's own "that's off" closing a user-stated claim in
  conversation, and entity-level forget through a `removal` inbox item.
- **Any Swift.** The app's watch UI (▶ m:ss evidence chips, a "Watched" pill derived from a
  `describes` claim with a `media` span, `EntityMedia.chapters` as seek buttons), a timeline
  surface, and a withdrawal view are Tracks P and O. The wire fields ship here and are additive.
- **An HTTP `GET /timeline`.** The tool is MCP-only this track.
- **The recommended-skills catalog**, the Skills page, the consent sheet, the installer, and the
  handshake's per-installed-skill bridge line. That is Track O (R5 §5.1–§5.5).
- **YouTube Data API metadata** (duration, captions flag, description; R5 D5), `channel_url` and
  `published_at`.
- **Indexing closed claims in the vector index** (Q-R3).
- **Any change to `/search`, the FTS schema, an ETag or a Store domain.**

---

## Hand-off

1. **Track P (provenance viewer):**
   - `media` is a new evidence kind and turn role. `EpisodeSpan.t` and `EpisodeTurn.t` carry
     seconds into the video for a `video [m:ss]:` line.
   - The speaker label the design lists gains "From the video".
   - "Watched" is derived: a `describes` claim with at least one `media` span.
   - A decoder must treat an unknown kind as `reasoning`, the backend's own degrade rule.
   - `Claim.expected_end` is not on the wire. `transclusion_resolver.claim_to_model` builds
     `ClaimModel` field by field, so the key never leaks and nothing breaks. A viewer that wants to
     show a stated end adds `expected_end: Optional[str]` to `ClaimModel` and one line to
     `claim_to_model`. Both changes are additive, and neither has an ETag.
2. **Track O (Settings v3 + skills):**
   - `cicada_record_watch` exists in both schemas, so `api/data/recommended_skills.json` may name
     it as a `bridge.tool` (R12 holds).
   - The handshake bridge line for an installed video skill is Track O's. Because
     `CONTRACT_VERSION` is now 3, Track O bumps it to 4 if it changes the contract.
3. **The Local-sources track (R-N3 scrubbing):** wrap `watch_record._write_episode` and
   `media_ingestor.write_note_episode`. Both write episode bodies through `markdown_parser.write`.
4. **Track N (speaker-aware evidence):** `evidence._TURN_RE` now has two alternatives.
   - The six conversation words are unchanged, in group 1.
   - `video|media` followed by a **required** `[m:ss]`/`[h:mm:ss]` is group 2, with the time as
     `t`.
   - The word is read through `_marker_word(m)`, and roles come from `_role()`.
   - On a conflict, add a meeting-speaker alternative beside these two. Read its word through
     `_marker_word` and route its role through `_role()`. Never make the video time optional
     (Q-R9). `EVIDENCE_KINDS` is append-only.

---

## Verification the orchestrator runs at the end

1. **Full suite.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
   must report **0 failures** and ≥ 2714 passed plus the new tests (about 150, most of them the 63
   parametrised R12 cases). If the only red is one of the two known flakes (Global Constraints:
   the order-dependent decay-commit test, or the `test_search_latency.py` wall-clock budget),
   re-run it alone and report both results.
2. **Golden fixture.** `cd <worktree> && git diff dev -- api/tests/fixtures/mcp_stdio_golden.json`
   must show only the `save_url` value (plus `recall`/`recall_again` if Task 1's commit explains a
   ranking change). Every other stdio reply must be byte-identical.
3. **No LLM, no fetch in the new modules.**
   `grep -n "litellm\|resolve_llm_fn\|providers\|ask_service\|httpx\|urllib" api/services/change_timeline.py api/services/claim_expiry.py api/services/video_chapters.py api/services/watch_record.py`
   must print nothing.
   `grep -n "resolve_repo_context\|mark_episodes_processed\|list_unprocessed_episodes\|import mcp\|from mcp" api/services/mcp_tools.py`
   must print nothing.
4. **Make each guard fail once on purpose.** A guard that has never failed is not known to work.
   - (a) Revert Task 7's `cicada_recall_detail(entity_id)` to `(id)` in `_CONTRACT`. Run
     `api/tests/test_handshake_r12.py`: it must FAIL. Restore it and confirm green.
   - (b) Change `claim_expiry.expire`'s `end >= day` to `end > day`. Run
     `api/tests/test_claim_expiry.py::test_a_stated_end_that_has_passed_closes_the_claim`: it must
     FAIL. Restore it.
   - (c) Remove `and not _is_record(c)` from `get_perspective`'s earlier list. Run
     `api/tests/test_retract_claim.py::test_history_says_withdrawn`: it must FAIL. Restore it.
5. **Privacy.** Run `git diff dev -- docs CLAUDE.md skills` and read every added line. There must
   be no bank contents, no owner name, and no author-machine path. The article's author and product
   may appear.
6. **Live check, on the demo bank only.** After the merge and a backend restart
   (`launchctl kickstart -k gui/$(id -u)/com.cicada.backend`):
   1. Make **demo** the active bank. From a fresh Claude Code session (the stdio MCP server
      resolves the active bank per call), check:
      - (a) `cicada_handshake` shows `### Standing — changes rarely` with the machine's timezone,
        and `### Current — in motion`.
      - (b) `cicada_timeline` with `since="30"` lists days with ids and counts, and no conversation
        titles.
      - (c) `cicada_recall` on an alias of a demo page suggests that page.
      - (d) In the demo bank's directory, `git status --porcelain` is empty after (a)–(c). Reads
        write nothing.
   2. Re-activate the previous bank.
   3. Nothing from any bank goes into a doc, a commit or the PR body.
7. **The PR body states:**
   - no Swift, no ETag, no Store domain, no `/search` change;
   - no LLM call added, and no network fetch except `record_watch` saving an unsaved `http(s)` link
     through `save_url`'s existing rails;
   - the golden fixture diff (the `save_url` key only);
   - the four hand-offs;
   - P9 is open in G140.
