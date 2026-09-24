# CLAUDE.md

Guidance for Claude Code working in this repository.

**This file is the philosophy and the rails. The detail lives in
[`docs/goals/`](docs/goals/) — read it before proposing work.**

---

## Project

**Cicada** — Author: Rodrigo Sagastegui.

The goal: **capture the human experience seamlessly, and make it something you can hold a
conversation over — with agents that can understand it, contribute to it, and draw their own
relations across it.**

Concretely, Cicada aims to span:

- **Every kind of media ingestion** — links, articles, papers, videos, images, bookmarks, RSS,
  files, saved collections exported from the platforms where they pile up.
- **Every conversation** — the ones with agents (MCP-native clients, plus imported ChatGPT/Claude
  exports), and, as recording becomes part of the workflow, **conversations with other people**:
  meetings ingested the same way, through the same source-agnostic pipeline.
- **The moving parts of a life** — projects, ideas, current interests, the things being decided and
  the things quietly going stale.

The design principle that follows: memory must be **legible to an agent without ceremony**. An
agent should be able to arrive, be told what Cicada is and how to use it, read the graph,
contribute beliefs with provenance, and leave the store better than it found it. The
markdown-and-git substrate, the claim layer, the author/session trailers and the MCP surface all
exist to make that true.

The architecture is biologically inspired: **Awake** = hippocampal encoding (fast, episodic capture,
no processing at capture time), **Sleep** = cortical consolidation (slow, semantic, batch), and
**temporal decay** = synaptic homeostasis (absence of mention is itself a signal). Episodic noise
gets compressed into a structured, versioned knowledge graph rather than accumulating as a
transcript pile.

### Why: the human-to-agent experience port

Cicada is the **port between a human's experience and the agents that will act on it** — the first
step toward capturing everything of a person's experience and their interactions with the world in
a form an agent can understand, so that, eventually, agents, humans and robots coexist on one
legible record of what happened and what it meant. Two papers frame the design, and every backlog
row should be readable against them.

**Silver & Sutton, *Welcome to the Era of Experience* (2025).** Their claim: the next generation of
agents will learn predominantly from *streams* of experience rather than snippets of human data,
grounded in an environment, with rewards from that environment and reasoning not confined to human
terms. Cicada's reading: **the person's life is the environment, and Cicada is the instrument that
turns it into a stream an agent can inhabit.** Four correspondences, each a design constraint:

1. **Streams, not sessions.** A conversation is a snippet; a life is a stream. Awake capture is the
   stream's intake, Sleep is what makes it more than a transcript pile, and decay is the stream's
   own clock — silence is data. Anything that fragments the stream (a resumed conversation
   consolidated twice, G104; capture that depends on a model choosing to call a tool, G105) is a
   defect against this, not a nicety.
2. **Observations *and* actions.** Every capture channel is an observation. Every agent write with
   provenance — a claim, a `Cicada-Author:` trailer, an inbox resolution — is an action on the
   shared record. The port is two-way or it is a diary.
3. **Grounded rewards.** When the person answers a nudge, overrules a claim, keeps or archives an
   entity, that is a reward signal *from the environment*. Cicada should treat these resolutions as
   the signal it learns from, not just as edits to apply (G113).
4. **Reasoning beyond prose.** The claim layer — typed predicates, bi-temporal validity, observer
   and trust — exists so an agent can reason over the record structurally. Prose is for humans;
   claims are the machine-legible half.

**Tang et al., *WikiSkill* (2026, arXiv:2608.27454).** Separating *raw experience* from a
*persistent wiki* from *executable skills* is what makes skill evolution work (the wiki is worth
+15 points to the skill proposer in ablation), and evolved skills **transfer across models and
model families**. Cicada holds the first two layers: `episodes/` is the raw layer, the
entity-plus-claim graph is the wiki. The third — compiling what the graph knows about *how this
person works* into portable, agent-loadable skills — is **G112**. The bar: **a skill compiled from
one person's experience should load into any harness on any plan, with Cicada being nothing more
than its provenance.**

**Portability is the point, not a feature.** The goal is other people running this on their own
plans and harnesses (G50 connections, G76 install, G92 onboarding). A hardcoded owner name, a path
that only exists on the author's machine, a bank that cannot be handed over intact — each is a bug
against the mission, not a polish item.

---

## Branches

- `main`: production/stable branch
- `dev`: active development branch — all work goes here first

PRs open against `dev`. Promotion to `main` is a manual, deliberate step — never a PR target.

---

## Backlog and handoff (`docs/goals/`)

**Read these before proposing work.** A proposal that duplicates a `G` row or re-opens a settled
ruling is wasted effort. Detail belongs in the backlog; state belongs in TODO.md. After finishing
work, update both.

- **[`memory-evolution.md`](docs/goals/memory-evolution.md) — the backlog.** One row per idea,
  `G<n>`, numbered in the order raised and never renumbered, so a `G` id is a permanent address:
  cite `G74a` in commits and PR bodies the way you would cite a ticket. A row carries the
  *reasoning* — the problem, the evidence (file:line, a measured number, a reproduction), and the
  design constraint any fix must respect. Triaged **APPLY** / **RESEARCH** / **DECIDE**; 💸 marks
  paid LLM spend. When you learn something that changes a row's argument, edit the row — never open
  a second one.
- **[`TODO.md`](docs/goals/TODO.md) — execution view + handoff.** Same work ordered by what to do
  next. Its header is written for an agent picking the project up cold: current state, open PRs,
  the verified live environment, and a "Pick up here" line. Above all it carries the **rulings** —
  decisions that cost real measurement, each with the evidence that settled it. **A ruling is
  binding.** Revisit one only on the trigger its row names, and only after reading why it was made:
  several were reached by disproving the obvious answer, so re-deriving them from first principles
  reliably gets them wrong.
- **[`working-method.md`](docs/goals/working-method.md) — how the work is run.** The bar a change
  clears (plan → critic → per-task implement+review → two-lens final review → verify yourself → PR
  to `dev`), the test baselines that are *not* failures, the rails that override convenience, and
  the paused queue with the reasoning for its order.

**Privacy rule (standing, 2026-09-02).** Nothing personal about the owner or anyone in their life
goes into `docs/goals/`, this file, a plan, a commit message, or a PR body: no names of other
people, employers, clients or companies from the bank; no episode or inbox titles; no quoted
conversation or claim text; no URLs, handles or contact details. The owner's own *thoughts and
ideas* are fine to quote — a row starting "Rodrigo 2026-09-01: …" carrying a design opinion is the
intended voice. When a row needs an example, use placeholders (`<surname-a>`, `alpha-project`,
`bob-example`) and say "real values redacted". **The repo is public; the bank is not, and the line
between them is this rule.**

---

## Repository Structure

`api/` FastAPI backend, `app/` SwiftUI macOS app, `mcp/` the MCP server, `memory/` the runtime bank
(gitignored), `docs/goals/` the backlog. Read the tree with `ls` — it is not duplicated here.

---

## Core Architecture: Awake/Sleep

### Awake — capture
Continuous episode capture. Raw timestamped chunks go to the `episodes/` inbox. **No LLM
processing at capture time** — just file I/O.

Sources are many and the pipeline is **source-agnostic**: MCP-native clients, hook-driven session
capture, chat exports, browsers (bookmarks and Safari tabs), Telegram, direct saved-content
connectors (Pinterest/Reddit/X), RSS, calendars, files. The per-channel detail lives in
`api/services/` and in the backlog rows that introduced each one — read the code, not a list here.
Seven rails hold across all of them:

- **The app reads `~/Library`, the backend parses bytes.** The launchd backend has no Full Disk
  Access and must never open those paths itself. An unreadable file shows the exact fix in the app.
  A browser is read only after the person turned it on — a Sync now, an all-folders import, or
  onboarding's tick — through `cicada.browserWatch.enabled.<channel>`; an install that synced
  before this gate keeps syncing (Track I T1).
- **Capture must not depend on a model deciding to call a tool** (G105). Every Claude Code and
  Codex session is captured by the harness's own `Stop` hook
  (`api/hooks/capture.py` → `POST /capture/transcript`). **The backend reads the transcript**, and
  only after the path resolves under the harness root as `<session_id>.jsonl` within the size cap —
  anything else is refused unread. `transcript_extract.py` keeps only the person's turns and the
  agent's final reply per turn; tool calls, thinking, file dumps and harness-injected text are
  skipped by construction. From a kept agent turn it reads two more facts and nothing else (round
  4 C1, G49 lifted for harness writes): the model id (Claude Code's `message.model`, Codex's
  `turn_context.payload.model`) and the reasoning effort (Claude Code's top-level `effort`, Codex's
  `turn_context.payload.effort`, and for the last reply the Stop hook's stdin `effort.level`). Both
  are cleaned by `agent_turns` (an effort is one of `minimal|low|medium|high|xhigh|max`, and
  anything else is dropped). They ride the sidecar on agent entries only; the transcript wins over
  the hook. Secrets scrubbed, per-turn and per-session caps applied. **One episode
  per session** — a later Stop rewrites it in place and flips `processed: false`, never two
  episodes for one conversation (G104). Cicada's own `claude -p` and `codex exec` spawns run with
  `CICADA_CAPTURE=off`. **Recall is the same move (G149):** the harness's `SessionStart` and
  `UserPromptSubmit` hooks (`api/hooks/recall.py` → `POST /capture/hook-context`) put Cicada's note
  in front of the model: the primer at session start, and the pages a message names on every
  prompt. Recall therefore no longer depends on a model calling `cicada_recall`. The prompt travels
  in a JSON body and is never logged, and `transcript_extract` drops any block opening with
  `recall_text.INJECTION_PREFIX`, so a recalled note is never captured back as the person's words.
- **Transcripts under `~/.claude/` are never read anywhere else.** The MCP seam and the resume path
  only ever `isfile()` them to answer "is this session still resumable"; that answer is computed
  per request and never persisted.
- **Every writer mints ids through one rule** (G114, `api/services/episode_ids.py`):
  `next_episode_id` is max-suffix+1 per date (a count-based rule collides after any gap, and
  `markdown_parser.write` overwrites on collision), and timestamps are aware UTC from
  `episode_ids.utc_now_iso` — never a naive local time with a `Z` appended. Legacy files are not
  migrated: readers accept both shapes and the queue sorts by `timestamp_sort_key`. A processed
  episode carries `processed_by` (`sleep` vs `agent`) so a flipped flag is distinguishable from a
  consolidation. `processed_by` also takes `user` — a companion note the person wrote in the app
  (G141 PJ-3b's Log; already processed, so Sleep never re-reads it).
- **Every writer scrubs, and every source-keyed writer stages through one module** (G133/G134,
  R-N3). `api/services/episode_scrub.py` — secrets, long base64 runs, one-time codes anchored on a
  connector word — runs before every writer's hash and write, and `test_episode_writers_scrub.py`
  fails for any module that mints an episode id without it. `api/services/episode_staging.py` is the
  G20 stager they share: an `EpisodeDraft` keyed by `source_id`, the hash over the scrubbed body, an
  edit rewritten in place with `processed: false`, a rename kept by content hash, a deletion
  tombstoned (`source_deleted_at`) and never unlinked. A multi-turn source records G118's per-turn
  sidecar `turns: [{offset, ts, speaker, model?, effort?}, …]` (R-PB4: an entry only for a turn with
  a time, the last key, outside `content_hash`, capped head-stable at 500; `model`/`effort` only on
  an agent turn (round 4 C1)) — the one shape `evidence.turn_stamps`
  reads. The Stop hook writes it too since G141 PJ-4 (R-PJ16): its `role: text` body is the stager's
  line shape, so `episode_staging.stamps_for` builds the list, and the episode `timestamp` stays the
  session's start while each turn carries its own time. A Stop-hook episode written before PJ-4 still
  holds an integer count, which reads as no stamps.
- **A local source is read by the app and parsed by the backend** (G133/G134). A watched folder:
  security-scoped bookmark, FSEvents, an mtime+size+sha manifest, bytes posted with relative paths to
  `POST /sources/folders/{id}/sync`; files under an agent glob land as `evidence_kind: assistant`,
  already processed, so an agent's sweep is never the owner's words. Saving new rules re-derives
  every existing episode of the folder in place — frontmatter only, the hash unchanged; agent → owner
  is queued, owner → agent is parked unless Sleep already read it — in one `user` commit (trigger
  `folder/authorship`), and the papers' why-claims follow (F2-back R-B6, R-B7). Wispr Flow: its SQLite opened
  read-only by the app through a column whitelist (never audio, screenshots, accessibility or pasted
  text); meetings and notes by default, dictation only when the person turns it on. A meeting line is
  `speaker:<label>:` and counts as `user` evidence only when its label is one of the owner's listed
  names. Apple Calendar (G142): the app reads EventKit after the one standard permission prompt and
  posts a rolling window to `POST /sources/calendar-local/sync` (one request = the whole window).
  `calendar_local.py` stages each event keyed `calendar-local:<id>`:
  - notes are scrubbed, then cut at 2,000 characters;
  - a link keeps no query;
  - an event gone from the window is tombstoned, only for the calendars the request named;
  - one `user` commit per sync (`capture/calendar`).
  The app half: `CalendarReader` reads every calendar on the Mac through EventKit, only after Connect and
  macOS's full-access prompt, 30 days back to 60 ahead, and posts on launch, on `EKEventStoreChanged`
  (debounced), every 3 hours, after a bank switch and on Sync now; an empty read is never posted (it would
  tombstone the window); Disconnect stops it and deletes nothing. ICS subscriptions are unchanged.
- **Capture never writes into a demo bank** (G117's synthetic bank; G141 capture-side track). A bank
  is the demo when `<bank>/_bank.yaml` says `kind: demo` — written first by `demo_bank.populate` and
  committed as `cicada` — or, for a demo made before that file, when its `.git/config` carries the
  generator's identity; never by its name (`api/services/demo_guard.py`). While it is active: every
  POST/PUT under `/capture/` and `/sources/` answers **409** (one route dependency,
  `refuse_capture_into_demo`, and a test that fails for a new route that is neither gated nor named);
  the intake checks the bank it writes into, so `?bank=` into your own memory still works; the MCP
  write tools refuse with a sentence the agent relays; Telegram answers 200 with a reply saying
  nothing was saved; and the Stop hook saves the session into the real bank left most recently
  (`last_active_at`, stamped by `activate_bank`; the response says `bank` and `redirectedFrom`), or
  answers 409 when it cannot tell which — the next reply after switching back saves the whole
  session. A demo bank's Sleep consolidates its own made-up episodes, but its tail skips the
  connector, feed/calendar, link-backfill, paper and Wispr to-do steps (connector credentials are
  machine-global). The generator itself is never gated.

**Conversation identity (G48).** An MCP episode carries `session_id` plus `harness` and
`project_dir` when exposed — minted once per MCP process from `CLAUDE_CODE_SESSION_ID` →
`CICADA_SESSION_ID` → a `ses_*` fallback that groups but never resumes. Entities credit to
conversations transitively via `source_episodes`. A conversation row's `model` stays null. The
model lives per turn instead (round 4, G49's reservation lifted for harness writes, TODO ruling 11):

- the Stop-hook episode's `turns` sidecar records each agent turn's `model`/`effort`;
- a claim written through the MCP seam carries `recorded_ts`;
- `turn_authorship.py` joins the two at read (`authorModel`/`authorEffort`), never guessed and
  never self-reported.

An app with no capture hook (the Claude app, ChatGPT, Cursor, a remote connector) has no turn to
join, and neither does a Codex MCP write, because Codex gives an MCP server no session id. The app
then says the model wasn't shared.

### Sleep — 5-stage nightly batch
1. **Entity & relationship extraction** — LLM over episode chunks, structured output.
2. **Entity resolution & dedup** — fuzzy match, embedding similarity, LLM disambiguation.
3. **Conflict resolution & pruning** — contradictions detected, recency wins, old state archived;
   temporal decay applied.
4. **Pattern detection & skill extraction** — recurring patterns distilled into skill entities.
5. **Nudge generation, clarification queue & versioning** — snapshot, git commit.

An **engine-independent tail** runs on every exit path, idle nights included: the state-dictionary
refresh, claim expiry (first in the clean-tree-guarded slot, its own `commit_paths` commit),
follow-ups (G141 PJ-6, right after expiry, its own `cicada` commit), the connector poll, RSS/ICS polling (opt-in via `CICADA_ALLOW_FEED_FETCH=1`), and the link
enrichment backfill — all in a clean-tree-guarded slot, after `_finalize`'s own commit so the poll's
`git add -A` sweeps only its own files.

### Entity promotion
Entities are NOT extracted from every mention — that pollutes the graph. First mention stays in the
vector index only; promotion needs **2+ separate conversations**, OR substantive discussion (>3
exchanges) in one, OR an explicit link to an existing high-confidence entity. What Sleep hears about a
name before it has a page is not lost (G141 PJ-0b): Stage 5.56 holds those claims on the name's line in
`<bank>/pending_entities.jsonl` (`api/services/pending_store.py`: spans, not copies; at most 50 per name,
the rest counted) and releases them onto the page, first and through Stage 3, in the cycle whose Stage 5
gives the name one — a holding line leaves the store only then.

### Temporal decay
Absence of mention IS a signal, and **how often something came up sets how fast its absence
counts** (G147). Each Sleep cycle charges an unreferenced page at most one week
(`MAX_DECAY_DAYS_PER_CYCLE`, measured from `max(last_referenced, decayed_through)` — TODO ruling 1)
at **base × f(w) × the bank's per-type pace**: the base is the decay class's rate or an explicit
`decay_rate:` (G66); `w` is the number of distinct ISO weeks among the page's `source_episodes`
dates plus the weeks the person answered *keep* to a decay question (`kept_on`; every unparseable id
together counts once); `f(w) = max(0.25, 1 / (1 + 0.6·ln w))` (`decay_spacing_alpha` /
`decay_spacing_floor`) — fifty mentions in one afternoon are one week, and a page that came up across
twelve weeks fades about 2.5× slower. The per-type pace comes from `<bank>/_decay_tuning.yaml`,
written only when the person applies a suggestion in Settings → Memory; suggestions are derived from
the bank's own decay answers in git history (`GET /memory/decay-suggestions`) and never applied on
their own. One function, `decay_policy.effective`, serves the pass and the entity wire's derived
`decay` block. Claims fade the same way (`claim_reconciler._decay_claims`: weeks from the claim's
episodes and cited `ep_*` documents plus the subject's keeps; session ids carry no date and never
count). Below 0.2 → `status: archived` (the page stays in `entities/`); below 0.4 → a decay nudge.
Mentioned again → promoted back at `confidence = max(current, 0.6)`. Evergreen entities skip all
decay math. **Confidence does not rank recall:** search puts archived pages last and otherwise ranks
by relevance (`search_service._page`'s sort key and the per-kind cut's archived tier); whether
confidence should weigh in is a question for G148's benchmark pass to measure before anything
changes.

---

## Storage Layer

### Markdown, not a database
Wikilinked `.md` files with YAML frontmatter, git-versioned. **The filesystem is the single source
of truth** — the API reads and writes the same files the Sleep cycle does. At personal scale
(hundreds of entities) the LLM follows wikilinks; it doesn't need Cypher. Zero infrastructure,
human-readable, portable, Obsidian-compatible.

### Entity schema

```yaml
---
type: person | project | company | concept | tool | deadline | skill | location | media | directory
status: active | decaying | archived | dropped
confidence: 0.85
created: 2026-01-10
last_referenced: 2026-03-22
decay_rate: 0.05           # per-entity, not global
decay_class: active        # evergreen | durable | active | volatile (G66)
source_episodes: [ep_2026-01-10_001]
tags: []                   # open set, freeform
related: []                # duplicates wikilinks for programmatic access
version: 3
---
```

**Entity types are a closed set of 10** (`api/models/schemas.py::EntityType`): `person`, `project`,
`company`, `concept`, `tool`, `deadline`, `skill` (procedural memory / preferences), `location`,
`media` (ingested item with an agent-generated summary), `directory` (a filesystem path, split out
from `location` in G18).

**Two exclusions matter (G17).** `deadline` still renders for legacy pages but is **no longer
produced by Stage-1 extraction** — `PRODUCIBLE_ENTITY_TYPES` excludes it; due-dates attach as a
`due` claim on the relevant project instead of spawning a standalone entity. `media` is likewise
excluded — it comes from the ingestion path, not conversation extraction.

**Status lifecycle:** `active` → `decaying` → `archived` → `dropped` (user-dismissed, never
resurfaced).

### Decay classes (G66)
One resolver, `api/services/decay_policy.py`. `resolve(fm)` returns `(class, rate)`: an explicit
`decay_class:` wins; otherwise inferred from `type` (`media` → evergreen, `skill` → durable, else
active) so legacy pages keep working. An explicit numeric `decay_rate:` still wins for the three
decaying classes; `evergreen` pins its rate to `0.0` unconditionally.

| Class | Base entity rate/wk | Claim multiplier | Meaning |
|---|---|---|---|
| `evergreen` | 0.0 | 0.0 | Never fades. Artifacts (media/bookmarks) + anything the user pins. |
| `durable` | 0.02 | 0.5 | Stable preferences, skills, long-lived concepts. |
| `active` | 0.05 | 1.0 | Default for a belief about the user's life. |
| `volatile` | 0.15 | 2.0 | Expected to change within weeks (role, status, current focus). |

**Anti-pollution rail** (mirrors `PRODUCIBLE_ENTITY_TYPES`): Stage-1 may propose
`durable|active|volatile` and **never `evergreen`** (`AGENT_PRODUCIBLE_DECAY_CLASSES`, enforced at
extraction AND again in the create branch). Evergreen is reserved for ingest writers and the user,
so an over-eager extractor can never stop the graph from archiving.

**Both engines honor it.** `conflict_resolver.resolve_and_prune` skips evergreen entities outright —
no decay math, no nudge, never auto-archived, so a bookmark can't generate a "still interested?"
question. `claim_reconciler._decay_claims` multiplies its per-epistemic × source_trust rate by the
SUBJECT's class multiplier. Since G147 the class rate is the *base*: both engines multiply it by the
spacing factor and the per-type pace (see Temporal decay).

### Claims, evidence and provenance

**Claims** are the machine-legible half: typed predicates, bi-temporal validity, observer and trust.
A predicate the vocabulary marks multi-valued (`predicates.cardinality`) never opens a conflict.

**Contexts and the fence (F1).** `context` is an open vocabulary whose *shape* is pinned by
`claim_contexts` — a short lowercase slug. Any other value (G60's `as of <date>`) keeps its job as a
claim key but is never a graph satellite, a legend row or an edge colour. `general` means "no
particular context" and is never a facet: a satellite needs two real contexts. The claims fence sits
after a page's last section (`write_claims`, the one writer), so **every reader strips it before
sectioning** — `strip_claims_block` on the server, `EntityProse` in the app.

**Evidence spans (G118) — spans, not copies.** Every claim written since that slice carries
`evidence: [{episode, start, end, kind, hash}]`. `start`/`end` are character offsets into the source
document's *evidence text* (the body as `markdown_parser.parse` returns it, with the ```claims fence
stripped for an entity page, so writing a claim never stales its own span); `hash` is
`sha256[:12]` of that text, and a mismatch reads as `stale` rather than mis-highlighting. `kind` is
one of six: `user` | `assistant` | `page` | `speaker` (a meeting participant who is not the owner,
G134) | `media` (what a video said — a watch record's timed `video [m:ss]:` line, G140; its position
in the video is derived at read, never stored) | `reasoning` (the contributor's own inference:
`start == end == -1`, never a faked span); an episode's `evidence_kind: user|assistant` (a folder's
authorship rule, R-F2) overrides the line markers. One marker grammar, `evidence._marker`, reads
both line families. One module, `api/services/evidence.py`, does the work for every writer: locate
is exact → whitespace-normalised → case-insensitive and **never fuzzy**; an unlocatable quote
becomes `reasoning` and **the claim is still written — provenance never blocks memory**. Legacy
claims carry no `evidence` and `to_dict` omits the empty key; there is no backfill.

**Events (G141).** Two predicates, `happened` (ongoing | done | dropped) and `milestone` (planned |
done | missed | dropped), with four optional fields omitted when empty — `status` (as of
`valid_from`), `target` (a milestone's planned date; expiry never reads it), `participants`
(`[{role, surface?, entity?, url?}]`, a closed role set; `surface` is an exact substring of the plain
sentence — no wikilinks in YAML) and `date_basis` (stated | turn | episode | person | written). A
done happening is **born closed** (`valid_to == valid_from`), so every reader that treats open as
current stays right; the history readers call `claims.is_event` (a grep gate enforces it). Events are
not records: they stay in FTS and citations, where they read as dated happenings, never 'no longer
current'. A milestone's slot is `(subject, milestone, slug)` across observers — the slug is its
`object`, never its `context`. Event cardinality is multi and lives in code. **Only `progress.py`
writes an event**: `write_claim` refuses the predicates, `claim_pipeline` relabels a stray label.
Dates are decided by `when.py`'s closed table; nothing relative is stored. `companion_app` is a
human origin (G141 R-PJ18): only `routers/projects.py` sets it (and the synthetic demo, which replays
app writes), no MCP tool accepts an `origin`, and `is_human` protects the person's milestones and Log
entries — an agent's different state on them coexists with a divergence item.

**Stated ends (G140).** A claim may carry `expected_end` — the date the fact itself says it stops
being true — and a G17 `due` claim's ISO-date object is its own. Never a future `valid_to`, which
every reader takes to mean *closed*. Sleep's engine-free tail closes such a claim the day after its
end (`claim_expiry`), in its own `Expiry <date>` commit (`Cicada-Author: cicada`, trigger
`sleep/expiry`); a failed commit restores the pages rather than leaving them for the next
`git add -A` writer. An agent withdraws a claim IT wrote with `cicada_retract_claim`: the claim
closes and a born-closed `retracts` record keeps the reason and any cited words; a human or Sleep
claim is never an agent's to withdraw.

**Reading provenance back (G118 slice 2, server half).** Three engine-free, bank-only reads, all
built in `api/services/provenance.py` and fetched on demand — none is a Store domain, so each ETag
serves the client's in-memory cache and there is no `VersionVector` mapping: `GET
/episodes/{id}/text` (the whole evidence text, capped at 400,000 chars, with `turns[]` from the
same marker lines `speaker_kind` reads — `speaker:<label>:` included, role `speaker`; a timed
`video [m:ss]:` line is role `media` with its `t` in seconds, as a span's `t` is — each turn's
role the `evidence.kind_for` answer, so an `evidence_kind` override relabels every turn — and an
asserted `start/end/hash` or derived `focus=<entity>`), `GET /entities/{id}/provenance` (contributors from claim `authored_by` plus one
trailer-only `git log` of the page — ETag includes `git_head` — conversations grouped by
`session_id`/`source_id`, the best quote per conversation, coverage over current claims), and `GET
/episodes/{id}/citations` (every claim citing the document, by a raw-text prefilter over
`entities/` — no index dependency). `/ask` citations also carry `claimId` + `evidence`, read from
the cited page rather than the index. Every claim on the wire is built by one function,
`transclusion_resolver.claim_to_model`, and carries `authorKind`/`authorProvider` from
`git_service.author_identity`. **Freshness is one rule, `evidence.span_status`:** `current`,
`grown` (an episode that was appended to after the span was minted — the Stop hook and G20 both
rewrite that way — and a turn-boundary prefix still hashes to the stored value, so the offsets are
exact) or `stale`. A stale span travels without wash offsets; a `derived` span (found by name,
`inbox_context.locate_mention`) exists on read payloads only — never in `EVIDENCE_KINDS`, never
written. The chat importer and every Local-sources draft keep each turn's time as
`turns: [{offset, ts, speaker}]` in frontmatter, written by `episode_staging` outside
`content_hash`; the Stop hook writes the same list (G141 PJ-4), and a reader treats any non-list — an
older Stop-hook episode's count — as no times. Round 4 (C2–C4):

- Every claim on the wire also carries `recordedTs` (stored on MCP writes only), and
  `authorModel`/`authorEffort` for a harness write. These are joined by
  `turn_authorship.TurnAuthorship`: the claim's session → its capture episode → the last person's
  turn at or before `recorded_ts` → the agent turn that answered it, with both sides floored to the
  second.
- An `assistant` span carries its turn's `model`/`effort`.
- A harness contributor lists `models: [{model, effort?, beliefs}]`.
- `/episodes/{id}/text` carries `agent` (the most recent agent turn's, null when that turn names
  neither) and per-turn `model`/`effort`.
- `claim_to_model(claim, *, turns)` takes the request's join as a required keyword.
- `AUTHOR_SHAPE` also rides `/episodes/{id}/text` and both `/projects` ETags.

**Optional frontmatter keys**, each with a narrow meaning — don't conflate them:

- `repos:` — links a project/directory entity to local git checkouts. The page only ever *declares*
  which repos; live git context (branch, ahead/behind, dirty, worktrees) is resolved **on demand,
  never cached** — `git_service` shells out fresh on every call.
- `sources:` (G61) — *where to look a fact up*, distinct from `source_episodes` (where a belief came
  from) and from the body's `## Links`. Keyed on `(ref, predicate)`, so one link can serve two facts.
  A conflict card's `hint` is **derived at read** from them (`fact_sources.served_hint` — the wire,
  the MCP render and the lexical row), never stored since G61 phase 2 S0, and its voice follows
  `added_by`: "You said …" only when the person added it; "Claude Code added …", "Cicada found …",
  "An agent found …" otherwise, the ref always in the sentence. An older item whose sources no longer
  match keeps its stored hint. Each entry is `{ref, kind: url|path|note|app|repo, predicate?, access?,
  added_by, added_at, accepted?, only_me?}` (phase 2 S1): `access` (`public|signed_in|local|unknown`)
  is stored only when stated, else inferred at read (`fact_sources.effective_access`: a refused or
  login host is `signed_in`, a path or repo `local`, an app `signed_in`); `accepted` marks an
  agent-found source the person took; `only_me` is the person's "Only I know" for one predicate —
  never a hint. The person's repeat of an entry applies those three; an agent's never changes one.
  Stage 5.56 attaches a URL found verbatim in a new Stage-1 claim's cited span as a source for that
  predicate (`added_by: <model>`, zero LLM) when the predicate's `locus:` is `world` or `artifact` —
  the vocabulary's where-the-truth-lives marking (seed + bank map, the most conservative winning:
  `person` > `artifact` > `world`; unseen is `unknown`). Nothing is fetched.
- `logo:` — a domain hint for `logo_service`. Logos are cached under `$CICADA_HOME/logos/<bank>/`,
  **never inside a bank** — a logo is a derived artifact of the outside world, not versioned memory.
- `picture:` (G146) — the person's own choice of picture for a page: `{kind: upload, sha, ext, added}` for a
  picture they uploaded, whose bytes live **in the bank** at `assets/pictures/<id>.<png|jpg>` (their record, so it
  travels with the bank; the path is derived from the id, never read from the page), or `{kind: initials, added}`
  for "Use initials instead". Written only by `POST|DELETE /entities/{id}/picture` and `…/picture/initials`, each
  committed alone as `user`, 409 while Sleep runs; never by an agent. The app shrinks a picture to ≤ 512 px before
  it leaves the Mac; the server keeps only a PNG or JPEG ≤ 512 KB (no Pillow). `entity_picture.resolve` is the one
  precedence (the person's choice → a person's Contacts photo → a brand's logo → a media page's thumbnail → a ring
  monogram), resolved at read onto `/graph` nodes and the entity; the app's `EntityPictureResolver` is its twin over
  `api/tests/fixtures/entity_picture.json`. A person never gets a logo and no service is sent a person's name (G159).
- `contacts_photo:` (G154, read by G146) — `{sha}` on a `person` page Contacts matched; the thumbnail itself is a
  cache at `$CICADA_HOME/contacts/<bank>/<id>.jpg`, never in a bank. Written by the Contacts sync only.
- `owner: true` (G117) — marks the one `person` page as the bank's owner; `owner_identity.
  resolve_observer` is what decides which page gets it, and every user-stated claim's `observer`
  field is that resolved value.
- `kept_on:` (G147) — the days the person answered *keep* to a decay question; each joins the page's
  mention weeks, so a kept page fades a little slower. Written only by the decay resolver, deduped,
  capped at 52. Not an episode id and never read as one.
- `paths:` (G133) — on a `project` page a watched folder anchors: `[{path, device}]`, where that
  folder lives on which Mac. For display and relink only; the backend never opens it.
- `media.kind: paper` + `paper:` (G133) — a paper page: `arxiv_id`, `doi`, `authors`, `published`,
  `venue`, `sections`, and `metadata_status` once a lookup failed. The ids are the identity
  (`media-arxiv-<id>` / `media-doi-<hash>`); the abstract is a `describes` claim from
  `external:arxiv` or `external:crossref`, a dated cache shown under the personal tier (G121).
- On an episode (G133/G134): `turns` (the G118 per-turn sidecar), `evidence_kind`,
  `source_deleted_at`, and a section's `content_sha` — see the Awake rails.

### Live state + handshake (G53 / G75)

**`<bank>/_state.md` is a *cursor* into the graph, never a copy of it** — YAML frontmatter plus a
short wikilinked body, ≤ 6 KB, zero LLM, deterministic. Written only by
`state_dictionary.refresh`. A digest of the `entities`/`inbox`/`episodes`/`bank` sync components is
stored as `inputs_version`; unchanged inputs mean no write. **Never `git_head`** — its own
`State snapshot` commit would self-invalidate.

Every regeneration that touches disk goes through `state_dictionary.refresh_and_commit`, which
commits `_state.md` ALONE (`commit_paths`, never `git add -A`) as `State snapshot <date>` /
`Cicada-Author: cicada`. **The read path commits too, on purpose:** a projection left dirty "for
Sleep's tail" gets swept into the next `git add -A` writer's commit under the wrong author — the
G85-class smear. `sleep.next_at` is computed per request, never persisted: in the file it advanced
every day and made every idle night commit.

**`_state.md` schema v3 (G141):** each of the top 7 project rows gains `next: {slug, name, target}`
and, once happenings exist, `now: {claim, text ≤ 80, since, verbatim?}` — the first claim text the
file holds; `verbatim` marks the person's own Log sentence, which a remote primer shows as 'a note of
yours' without `sources`. Neither field depends on today, and `_fit` drops every `now` before it
drops a project.

**The handshake** (`api/services/handshake.py`) turns `_state.md` + a fixed contract into ≤ 1,800
tokens of primer: what Cicada is, a per-harness prelude (the contract never varies), the contract
itself, the now-view, and capability notes. The now-view is **Standing** — the person's page and
one-liner (through G117's resolver), their timezone (per request, never in `_state.md`, part of the
cache key), *How to work with me* (standing `skill` pages by confidence alone), long-standing
durable/evergreen pages — then **Current** — projects, each project with its `now`/`next` (G141),
pages in focus in the last 14 days, people, recent conversations (G140, schema v2). A test holds R12 for every argument either primer names, for
every remote scope set. Contract item 3 names `cicada_note_progress` (G141 PJ-3a; remotely only when the
connection holds it). Delivered four ways: the MCP `initialize` result's
`instructions` (which Claude Code truncates), the `cicada_handshake` tool, `GET /handshake`, and the
SessionStart hook's `additionalContext` under a "From Cicada" header (G149). Contract item 8 tells an
agent what a "From Cicada" note is. **R12: a primer naming an
argument the schema rejects is a bug** — every argument it names must exist in the tool schema.
`SKILL.md` points at the generated text rather than restating the contract — one prose source.

**A reader that finds `_state.md` stale or absent must still work:** every field has a live twin
(`/status`, `/inbox`, `/conversations/recent`, `cicada_repo_context`).

### sqlite-vec (vector index)
`api/services/vector_index.py`. Embeddings are **stored, not recomputed at query time**, so search
is one in-process ANN lookup. Default backend is EmbeddingGemma-300M (768-dim, on-device) with
asymmetric query/document prompts. The index is **derived and disposable** — rebuilt by Sleep from
markdown, safe to delete at any time.

### SQLite FTS5 (lexical index, G136)
`api/services/search_index.py`. One `search_index.db` per bank, **beside `vector_index.db` and never
inside it**: entity names + aliases + prose, every claim (superseded ones kept as history), episode
titles + 600-character passages that tile the evidence text exactly, media/paper metadata and inbox
questions, in six per-kind FTS5 tables (`unicode61 remove_diacritics 2`, prefix `2 3 4`; rowid
`doc_id << 16 | n`). `dropped` pages are never indexed. **Derived and disposable** (TODO ruling 3):
deleting it costs a few seconds of CPU and never a fact; a missing, corrupt or schema-mismatched file is
rebuilt, never an error. **Never tracked:** `bank_registry.ensure_derived_excluded` writes
`.git/info/exclude` before the file first exists. It follows a worktree or submodule bank's `.git` file
to the real git dir, and a new bank's `.gitignore` lists the file too. It never edits an existing
`.gitignore`, which would dirty the tree and smear into the next `git add -A` commit. **Freshness:**
Sleep rebuilds it beside the vectors; every read path calls `ensure_fresh`, a `bank_index` stamp diff
(at most one check a second, inline up to 64 changed files, one background worker beyond); the
lifespan and a bank switch warm it in the background. The caller always passes the active bank's path
— the module never resolves a bank (the split-brain rule). `search_service` ranks over it (QuickMatch
tiers 0–2), fuses it with the stored vectors in `mode=hybrid`, and **never embeds in `mode=prefix`**.
**The query is never logged**: not by loguru, and not by uvicorn's access log (`api/main.py` strips the
query string of `/search` and `/conversations/recent`, G136 R22).

### Telemetry ledger (`~/.cicada/telemetry/`)
Append-only JSONL, machine-global, **never in a bank or git**. `CICADA_TELEMETRY=off` disables it.
**IDs and enums only — never claim text, query text or answer text.** The `read` kind (G124) records
an entity id and a surface enum, filed in a sibling `reads-*.jsonl` that
`sync_service.components["telemetry"]` deliberately does not stat — the app maps that component onto
its consumption domain, so a card open must not move it. The `hook_recall` kind (G149) is one row per
recall-hook firing: harness, event, reason enum, the page ids and their count, token and latency buckets,
and the model id when the harness sends one. It is filed beside `read` for the same reason, and like
`capture` it is a per-turn receipt that `consumption_stats._activity` keeps out of every Usage view. The
prompt never is.

**Feedback events (G113):** every inbox resolution emits a `resolution` event (`stage: feedback`,
`refs` = item id, kind, predicate, entity id, action label, `verdict: agreed|overruled|neutral`,
winner/loser claim ids, the extractor's confidence and model — ids and enums only, never claim
text), Stage-3 reconcile emits one `audit` event per supersede/reject, and the dedup sweep emits one
`dedup_verdict` per judged pair. `telemetry.FEEDBACK_KINDS` names the three (a superset,
`NON_SPEND_KINDS`, also excludes `capture`/`handshake`/`read`); `consumption_stats.stats()` excludes
them from `by_connection` so they never show as an "unknown" connection. Nothing learned from the
ledger is auto-applied — `GET /consumption/feedback` shows the rates; feeding them back into
prompts is G78.

### Git — versioning and provenance

Every Sleep cycle commits with a **machine-parseable message**:

```
Sleep cycle 2026-03-20

entities/recruiting-thread.md: updated (source: ep_2026-03-20_002, trigger: sleep/extraction)
nudges/nudge_005.md: resolved (trigger: user/companion_app)

Cicada-Author: gpt-5.4-mini
Cicada-Engine: claude-cli
Cicada-Session: <id>
```

**Triggers:** `sleep/extraction`, `sleep/promotion`, `sleep/conflict_resolution`, `sleep/decay`,
`sleep/state`, `sleep/expiry`, `sleep/followup`, `capture/calendar`, `nudge/resolved`, `clarification/resolved`, `user/manual_edit`,
`user/companion_app` (also the Projects page's writes, G141 — `Project update <date>`,
`Cicada-Author: user`),
`mcp/<harness>` (a local agent's write), `remote/<harness>` (a remote connector's write, G135).

**Three trailer families, all inert to entity-line parsing — extend them, don't break them:**

- **`Cicada-Author:`** — *which agent authored this*. A model id for agent writes, **a harness
  label** (`claude-code`, `claude-web`, `chatgpt`, …; `agent` when none was sent) for a write that
  arrived through MCP, where the model is not disclosed (G135; the trailer never names a model — since round 4 it is joined at read from the captured
  turn), the
  literal **`user`** for manual/companion-app writes, **`unknown`** for legacy untrailered commits,
  and **`cicada`** for system maintenance with no model and no user in the loop (the one-shot
  migrations, the split-out decay commit, the `State snapshot` commit, the `Expiry` and `Follow-ups` commits). Built by
  `git_service.build_commit_message(...)`, parsed by `_parse_authors`.
  `git_service.author_identity` buckets a harness label (and `agent`) as kind `harness`, which the app
  names and marks as that app; the pre-G135 `mcp-agentic-write` claim placeholder reads as `agent`
  through `canonical_author`, never rewritten (F2-back R-B9, R-B10). A read whose body carries an
  author kind folds `git_service.AUTHOR_SHAPE` into its ETag; bump it when the buckets move.
  Powers `GET /contributors`.
- **`Cicada-Engine:`** — exactly one per main commit (`claude-cli|ollama|litellm`), **omitted
  entirely rather than guessed** when no LLM ran. Read back via git's own
  `%(trailers:key=…,valueonly)` directive, not a Python parse of `%b` — pulling the whole body to
  extract one line grew the endpoint from 787 B to 378 KB for 8 commits on the live bank.
- **`Cicada-Session:`** — one line per distinct conversation consolidated, capped at
  `MAX_SESSION_TRAILERS` (50) by the call site, not the builder. User-action commits stay
  session-less.

**G85 — decay gets its own `cicada`-authored commit.** Temporal decay runs over entities a cycle
never referenced: no LLM, no source episode, pure arithmetic. Folding it into the main commit
stamped it with whichever model happened to run Stage 1/2, inflating that model's contributor counts
for work it never did. `_finalize` splits `sleep/decay` entity lines into their own commit —
`Sleep cycle <date> (decay)`, `Cicada-Author: cicada` — committed *before* the main commit so the
main commit's `git status` scan never sees them. A split that can't happen degrades back to the old
behavior rather than aborting the cycle. **Known asymmetry, disclosed not fixed:** the split is
path-granular, not hunk-granular, so a subject that is both decay-eligible and claim-touched in the
same cycle lands whole in the `cicada` commit. Narrow in practice; fixing it needs hunk-level
staging.

**One git writer per bank (F2-back R-B1 … R-B4).** Every mutating git command — `git_service`'s
commits, a `_run_git` write, the one-shot migrations, the expiry restore — runs in a worker thread
under one re-entrant lock per resolved bank path, so tasks, threads and `asyncio.run` bridges queue
instead of colliding on `index.lock`; the backend is one process, git's own lock is the cross-process
guard, and only its `File exists` refusal is retried (five tries, the lock never deleted). Reads pass
`GIT_OPTIONAL_LOCKS=0`, and `test_git_write_lock.py` refuses a git write spawned anywhere else.
A folder, paper or Wispr commit that still fails keeps its paths in `cicada-pending-commits.json`
in the bank's own git dir (a worktree's, never the shared common dir), says so on its channel, and
lands on that writer's next run — or at the start of the next Sleep cycle, before any stage writes —
under its own author (R-B5).

**Entity-level provenance uses `git blame`** enriched with parsed commit metadata; repo-level
history uses `git log`. **No changelog in frontmatter** — git handles all history, zero storage
overhead, no growing fields.

---

## MCP "Bookworm" Tool

The interface between any LLM and the memory system. On `initialize` the server returns the G75
handshake as `instructions`. On query: check `memory/inbox/` for relevant pending items → search the
vector index → search the markdown graph → follow wikilinks for relational depth → progressive
disclosure (cluster pages → entity pages → episodic sources).

**Recall (G140).** Three legs fused by one RRF (`search_service.rrf_fuse`): the stored vectors, the
FTS lexical leg (names, aliases and prose, word by word), and current claims mapped to their
subject — so an alias or a relationship label reaches its page. The top three pages carry a bounded
"Changed recently" block (claims closed in the last 30 days, ≤ 5 lines);
`cicada_get_perspective(history=true)` lists every earlier claim. **`cicada_timeline(since)`**
answers "what changed" from the commit manifests on demand — ids and counts only, nothing stored,
`read` scope remotely. **`cicada_record_watch`** records what an agent's own tools saw in a saved
video — a summary and ≤ 12 timestamped quotes as `media` spans; Cicada never downloads or watches a
video, and never keeps a transcript. **`cicada_project(project, since?, tz?)`** (G141 PJ-2, `read`
scope remotely) answers where a project stands — next milestones, what passed with no word, the Sleep
queue, what happened and what is around it — from the engine-free read model, printing every relative
word beside its absolute date ("yesterday (2026-09-22)"); a quote of the person's words needs
`sources` remotely. **`cicada_note_progress`** (G141) records a happening or a milestone the person
described — observer always the agent, `record` scope remotely, never creates a page, echoes how the date
was decided; `cicada_retract_claim` withdraws an event the same way.
**`cicada_add_source(subject, ref, predicate?, access?, kind?)`** (G61 phase 2 S1) records where a
fact can be checked when there is no claim to write — only a source the person named, never one the
agent guessed; it is not `cicada_sources` (conversations). `record` scope remotely, where a path, a
repo or `access: local` is refused; it commits alone under the harness. `cicada_write_claim(sources=)`
takes a string or `{ref, access}`. The primer does not name `cicada_add_source` until S3's contract.

**Implicit recall (G149).** G105 stopped capture depending on a model's tool call, and recall now works the
same way.

- **The hook.** `api/hooks/recall.py` is stdlib only. One command is registered under both `SessionStart` and
  `UserPromptSubmit` in `~/.claude/settings.json` and `~/.codex/hooks.json`, owned by its own marker in
  `api/hooks/registry.py`. It posts to `POST /capture/hook-context` and prints
  `hookSpecificOutput.additionalContext` (the one shape both harnesses parse) or nothing. It always exits 0,
  never 2 (which erases a prompt), under a 0.9 s client timeout.
- **The note.** `hook_recall` answers engine-free from the derived FTS index. SessionStart gets the primer. A
  prompt gets at most three pages it **names**: a whole name or alias, and one word only for a person, project,
  company, tool or place. Each page comes with its summary and at most two current claims with their dates,
  plus at most one open inbox question as a pointer to `cicada_check_nudges`. The note is ≤ 400 tokens or
  nothing, produced within a hard 300 ms.
- **The vectors.** They only re-order pages already named, and only when the on-device embedder is already
  loaded. A hosted embedder is never sent a prompt.
- **Repeats.** A per-session window keeps a page from being re-sent on consecutive turns.
- **The bank.** It reads the bank a capture would write into: the real bank while the demo is open, and
  nothing when there is none.
- **When it is skipped.** `CICADA_CAPTURE=off` spawns, `CICADA_RECALL=off`, and a Codex sub-agent's prompt.
  Codex also runs a new hook only after the person trusts it at startup.
- **The ledger.** One `hook_recall` ledger row per firing, ids and enums only, filed beside `read`.
- **Remote.** Remote connectors have no hooks.

**Proactive behaviors:** surface only *topic-relevant* nudges (never all of them), raise a pending
clarification naturally in the flow when the conversation touches its entity, and offer related
saved resources.

---

## Companion App

The user-facing management layer for inspecting and curating the graph — it makes the system
observable rather than a black box. **The app is NOT the primary interaction surface** — that's the
chat, via MCP.

**Stack:** native SwiftUI macOS app; FastAPI backend at `localhost:8000` spawned as a child process
on launch (`Process()`) and terminated on quit; graph rendered with d3-force in a `WKWebView`.
SwiftUI→d3 via `evaluateJavaScript()`, d3→SwiftUI via `postMessage()`.

**Ruling (G109, 2026-09-02) — d3-force stays.** Evaluated against sigma.js/ForceAtlas2, Pixi,
cosmos, ngraph and d3-force-3d at ~1,900 nodes: the two G109 symptoms were three local bugs in how
`graph.js` drove d3-force, not a library problem. The only flip trigger is an in-app p95 frame time
above 16.7 ms on the live bank, or a graph well past ~10k nodes. **Two rules follow:**

1. **Every custom force multiplies by the `alpha` d3 passes it** (a guard that only removes energy
   is the one exception).
2. **The release path never bumps alpha** — a throw coasts on velocity, not on a hot graph.

`app/CicadaApp/Tests/graph/graph-physics.test.js` (real d3, real `graph.js`) is the regression net;
a KE/node plateau at tick 400 is the signature of a force that broke rule 1.

**Sync engine.** One `Store` holds a `Snapshot` per domain, hydrated instantly from a per-bank
on-disk cache before the first network round-trip, so the app renders real data cold even with the
backend down. A `SyncEngine` holds one SSE connection to `GET /sync/events`, reconnecting with
backoff and falling back to polling while disconnected; each `version` event refreshes only the
changed domains, always with `If-None-Match` so an unchanged domain costs a 304. View models are
thin projections and **never blank** — always last-known-good. Writes go through a `Mutation`:
optimistic apply, rollback with a toast on failure. **The graph receives deltas, not a full
re-layout**, so d3 node positions survive a Sleep cycle or a live edit.

**Ruling (2026-09-03): prices and token usage are not shown anywhere in the app** — no cost tiles,
no `$`/token columns, no cost-per-day chart. The `/consumption/*` endpoints and the ledger are
unchanged for future use.

**Navigation (Direction D, DS-1).** A 56 pt icon rail (`Views/Shell/NavRail.swift`): Home, Graph, Clusters, Feed,
Sleep, Inbox, Sources, Projects at ⌘1–8 in `AppTab.allCases` order (`RailItem`; a page switch is instant), each cell's tooltip
naming its page and shortcut (450 ms, then instant while warm), selection by brightness and one neutral fill
(`bgSelected` — never the accent, `SelectionTintLintTests`), the Inbox count a neutral `bgBadge` numeral, a spinner on
Sleep while a cycle runs, the gear and the sun/moon toggle at its foot, no wordmark. ⌃⌘S or the titlebar toggle swaps it
for a 208 pt labelled sidebar, remembered per viewer (`cicada.shell.labelledSidebar`). Relaunch restores the last tab:
nothing stored, or a value no build knows, opens Home, and a stored Graph stays on Graph; `AppTab` raw values are the
persisted identity and `AppTab.restored(from:)` maps retired ones. **The titlebar is a SwiftUI toolbar** with the
title hidden (AppKit keeps the drag area in every gap): the sidebar toggle after the traffic lights; the **command
bar** centred — the memory-bank selector (`BankSwitcher`, moved from the Graph page; the only switcher view in the
app, `SingleBankSwitcherTests` — the palette's "Switch to <bank>" row and the intake card's switch act on the same
`BanksViewModel` in the same window) and "Search your memory ⌘K", which opens the find palette through
`AppRouter.requestPalette()`; and the visible page's `?` at the right (`HelpContent.page`), one per window. macOS 26's
toolbar platter is hidden (`ChromeToolbarItem`). **Settings is a panel inside this window (DR-33)**: ⌘,
(`ShellCommands`, which opens the window first if none is) and the gear open it over a scrim — 880 × 620 at 1×,
inset ≥ 40 pt — with a `bgPane` sidebar that starts with a `CicadaSearchField` and groups its rows as Cicada ·
Customize · Engines & keys (`SettingsGroup`, G139) — Cicada: General · You · Privacy & data · Memory · Sleep;
Customize: Integrations · Agents · From anywhere · Skills; Engines & keys: Engines · Plans & keys · Advanced — and each
page's own header with an `esc` keycap and a close ×. It is modal: the shell under it is inert, ⌘K waits, Esc and a
scrim click close it. `AppRouter.openSettings(_:row:)` is the one door (`SettingsSectionLink`, the gear, ⌘,), every
hand-off to a page closes it, and `cicada.settingsSection` is only its remembered selection — the `Settings{}` scene
and its cross-window seeds are gone. Privacy & data exports a bank and moves one to `<root>/.trash/`, but never
switches banks (that is the command bar's); Memory has no "Look for duplicates" until the dedup endpoint stops
blocking the event loop and commits what it merges (R-O17). Memory also holds
G147's *How things fade*: pace suggestions from the person's own "Still tracking…?" answers
(Apply · Not now — the latter per viewer) and each chosen per-type pace (Reset). Search is `SettingsIndex` over `QuickMatch` — the
palette's one ranker — and landing always selects, scrolls, washes (the selected fill and the focus ring) and
announces the row (G139). `SettingsSection` raw values did not move. General's appearance offers System, which
follows the Mac's own light/dark through one app-scope observer (`ThemeStore.observeSystemAppearance`). General also
holds Scene, Open Cicada at login (`LoginItemService` over `SMAppService.mainApp`; an unsigned build that macOS does
not keep says so) and Keep memory working when Cicada is closed (`BackendAgentService`: a read-only `launchctl print`,
and Install runs `scripts/install-backend-agent.sh` from the app's own checkout after the click, `CICADA_CAPTURE=off`,
then hands launchd the port). ⌘K and ⌘F are
menu commands in `Support/FindCommands.swift` (`HiddenShortcutLintTests`); ⌘, and ⌃⌘S live in
`Support/ShellCommands.swift`. Track P's audit removed the global Sleep button, because a cycle starts from the Sleep
page's one Consolidate control (G125 R10) or the menu-bar bookworm.
**One intake (Track I, spec decision 13).** Every way a file arrives — a drop anywhere on the
window, the Dock icon, File → Import… (⌘⇧I), the menu-bar worm's *Import a file…*, an empty state,
each `+` chat tile, the Sleep room's worm — goes through one `IntakeRouter`: sniff (`POST /intake/sniff`, stages nothing) →
preview (counts, date range, new · grew · already here, skipped files by name, *Into* a memory) →
import (`POST /intake/import`; a 202 and a job counter above 10 episodes) → a *what happens next*
card that never closes on its own. `UploadOverlay` and the Feed's Upload button are gone; the router
owns `Store.intakeInFlight` through a counter of requests in flight. The card's *Read now* is G125
R10's first narrow amendment: a user trigger, subtitled with the manual engine like Consolidate,
shown only when an engine can run and the import landed in the active bank. **Every
`IntakeRouter` door refuses the same roots** (`IntakeRouter.feedGuard`, Track Z): a drop that
resolves under `~/.claude`, `~/.codex` or `~/.cicada` (or `$CLAUDE_CONFIG_DIR`, `$CODEX_HOME`,
`$CICADA_HOME`) is refused before any folder is walked, a refused root met inside a dropped folder
is never descended into and refuses the drop, a drop with nothing export-shaped in it is refused by
name, and nothing is sent; `accept` answers (`IntakeAcceptance`) so the Sleep room tells a refusal
in its worm's words while every other door shows it in the panel. Three pickers still sit outside
the router — the Add-source walkthrough's drop and *Choose file…*, its saved-content picker, and
Settings' local-folder picker — and check only the chosen file or folder
(`IntakeRouter.refusedRoot(of:)`); a watched folder that *contains* a refused root is still walked
(open, G125).

**Home (G108; Direction D, DS-3b).** The front door at ⌘1: the painted `hero-day` band — its
`-dark` sibling at dusk and night by the clock (`SceneClock`: NOAA's sun over the Mac's time zone's tzdb point, no
location; `SceneStore` re-checks at each crossing, on a time-zone change and on wake) and Settings → General → Scene
(Automatic · Always day · Always night), never the theme (G144; DESIGN_RULES §9 2026-09-24) —
(`HomeHeroBand`, paint only, 120 pt, faded into the window), "What would you like to remember?" as a
`PageTitle` on the row under it — text never sits on paint — then the palette's own `FindPanelBody` in
`.page` placement in a 640 pt block: a second `FindPaletteModel` sharing the one Ask and keeping no
recents; ⌘K on Home focuses it, a pasted `http(s)` link offers *Save this link*. Below it, in one
760 pt column, labelled `glassCard` blocks of 36 pt rows: Getting started (while it lasts), Today
(captured today, UTC, with the three busiest marks), Needs you (the Inbox's own `InboxRow`s, landing in
STATE 1) and Last read (the newest Sleep commit, its pages as `Tag`s) — each number once, each a link
(`InlineLink`) to the page that owns it; the waiting count links to Sleep, never a Consolidate.

**Onboarding (G117, Track I part b).** One full-window Welcome, shown by the unchanged
`FirstRunGate` (unknown is never empty): the hero meadow as its band (`WelcomeHero`, the same scene rule as Home's:
day or its `-dark` sibling by the clock and Settings → General → Scene, never the theme — G144), the headline on the card that
rises into it, what Cicada found on this Mac as a checklist whose ticks are the consent (own acts, no
new permission prompt, no other app — `FoundPolicy`), a chat-export drop zone that stages rows and
imports nothing before Start, the engine cards with each one's cost model (`EngineChoice`, never
blocking — an untouched choice keeps the install's configured engine, and Getting started asks
"who reads" only if that cannot run), and one meadow pill whose text twin says exactly what it
will do. A browser's bookmarks are neither counted nor read before its tick. Start is `SetupRunner`:
the owner PUT first and alone, then Home, then every ticked row side by side, each failure on its
own row. Getting started continues on Home — rows from the machine's own state, the first read
(*Read now*, G125 R10's second narrow amendment, only inside the card), and "Keep reading on its
own?" asked once of a person still on `manual`, its options gated by ruling 4. *Set up later*,
*Try the demo instead* and Settings → General's *Run setup again* / *Show setup checklist* remain.
Export reminders (`ExportWaits`) ask for notification permission only when the person chooses a
delay; the Feed strip, the menu bar and the card say the same with notifications off.

**Settings → Engines: the engine picker (G122, Track E; moved by G139 A3).** A row of cards with real marks — Auto,
Claude plan, ChatGPT plan, Ollama, API key — over the connections registry's candidates writes
`PUT /sleep/engine`, which lands in the same bank-independent `~/.cicada/connections.json` prefs
`use_for_sleep` already uses, never `api/.env`. A plan card is selectable once that plan is signed
in. The card shows both `preview.manual` and `preview.scheduled` lines rather than hiding **ruling
4** (a scheduled cycle never spends Claude *or* ChatGPT plan quota — `engine_select.SUBSCRIPTION_MODES`)
— the asymmetry stays visible, not silently applied. *Keep going on extra usage* (off) is the only
way a Claude cycle continues past the plan's included usage; otherwise it stops with one plain
sentence and the reset time. Ask follows the same choice. The ChatGPT plan runs as `codex exec` in
Cicada's own Codex home (`~/.cicada/codex`), signed into in-app with a device code; Cicada never
opens that home's files — `codex app-server` answers plan, limit and models.
`EngineChooser` is the component (`EngineCard` wraps it for onboarding); the Sleep page's quick engine
menu (beside Consolidate) reads and writes the same `PUT /sleep/engine` through the same
`SleepEngineViewModel` and the same write rule (`EngineWrite`), and shows both previews — "When you
start a cycle" / "Scheduled cycles", the one wording app-wide. The Claude plan's old *Use for Sleep* switch moved here too —
same `use_for_sleep` pref, same endpoint — but `engine_select.resolve_llm_mode` reads that pref only
when the chosen mode is `byok`, so it shows only while the API key card is chosen, as *Use my Claude
plan when I start a cycle*, and a flip reloads the chooser's preview. Plans & keys is credentials
only: the Max-tier cost-estimate picker is gone (the no-price ruling).

**Settings → Integrations (G126).** A categorized, logo-first page over the existing
`GET /sources/channels` registry — no new adapters, just a frame. The rule this page draws: a
*standing* connection (sign in once, polled on the Sleep tail, disconnect here) lives in
Integrations; a *one-shot* import (drop an export, sync a folder once) stays where it already was,
behind the Feed's `+`. Both read the same `channel_registry`, so a channel never drifts between the
two surfaces. Round 3 added **Notes & files** (Apple Notes, every watched folder, *Add a folder* and,
when Obsidian is installed, *Obsidian vault*) and **Voice & meetings** (Wispr Flow once it is on this
Mac) — both standing connections, so both live here; their marks are the installed apps' own icons.
Harness rows wear their app's real mark ("Other agents" a neutral glyph); a folder's Manage, Wispr
Flow and a connector's Connect/Manage open as sheets (`SettingsSheet`), never popovers; the
add-folder sheet labels its fields and asks which subfolders an agent wrote as a checklist
(`AgentFolders`), the wire still a `<folder>/**` glob (DS-3b).

**Agent wiring (Track I T3/T7).** `GET /agents/wiring` is read-only: per harness it reports
*recall* (the MCP server registered — `claude mcp get cicada` / `codex mcp get cicada --json`, 6 s
each and side by side (round 4: at 2 s the live Welcome read Claude Code as 'couldn't check in
time'), a timeout is `unknown`) and *auto-save* (the G105 Stop hook, via `api/hooks/registry.py`; an
unparseable settings file is `invalid`, never `off`), *auto-recall* (G149: `autorecall`
= `on|off|stale|invalid|n/a` for the recall hooks, with `autorecallOn` / `autorecallOff` argv kept apart from
`connect`, which onboarding runs; Settings → Agents → *Remembers automatically* runs them), plus the exact
argv install.sh would run. The **app** runs them, only after the person's click (spec decision 14, D-1), with
`CICADA_CAPTURE=off`, behind an allowlist pinned to its own checkout (which also accepts the recall hook's two
events and `registry.py uninstall --hook recall`); the backend never writes a harness root. `GET /agents/setup?harness=` (round 4 C5, G76's in-app half) serves what to hand an
agent instead of running anything:

- for Claude Code, Codex and Gemini CLI, a plain prompt (≤ 1,200 characters) that names the exact
  commands, built by the same step builders `/agents/wiring` uses (both steps always,
  `display == shlex.join(argv)`);
- for Cursor, its install link;
- for the Claude app, a config merge the APP performs.

No probe, no subprocess, no ETag.

Settings → Agents (round-4 D5) adds, per harness, Connect for me (the same `AgentConnect.run`), Copy
setup prompt (`GET /agents/setup`'s prompt shown verbatim, then copied — the agent runs the install itself), Open in
Cursor (the catalog's own deeplink) and Set up Claude (`ClaudeDesktopConfig` merges `mcpServers.cicada` into Claude
desktop's config: backup first, merge never replace, an unreadable file left untouched; the app computes the path and
the value itself).

**Settings → Skills (G138).** A reviewed catalog (`api/data/recommended_skills.json`: source,
licence, the reviewed commit and SKILL.md hash, needs, agents, a terms note, the Cicada tool it
bridges; `scripts/verify-skills.sh` re-checks it) served by `GET /skills/recommended` — at most
five not-installed entries by rank, install state derived per request from `SKILL.md` files and
Claude Code plugin ids, never an agent's config. **The backend never installs anything.** The app
runs only the agent's own installer (`claude`, `codex`, `npx skills` pinned to the reviewed
commit), after a consent sheet that shows the exact command, as an argv with
`CICADA_CAPTURE=off`; hosted MCP servers are copy-only. The app writes files only for Cicada's
own `cicada` and `cicada-librarian` (`SkillInstaller`, a `.cicada-managed.json` marker, never
over a changed copy). The handshake gains a capability line only for an installed, active bridge
whose tool exists: papers (`cicada_save_url`), video (`cicada_record_watch`) and meetings
(`cicada_save_episode`, one `speaker:<name>:` line per utterance, never `user:`) are active;
documents stays off until something says who wrote a document (F2-back R-B14).

**Sources page — v2 in Direction D (G124, DS-3c).**
- **What stays from v2.** Every tile keeps Sources v2's five facts: mark · brand name · one status verb
  (`SourceLiveness`, no backend field) · a 14-day capture sparkline + lifetime total · four week-dots + delta.
  **Two nouns, never one**: the big number is the row's own unit, and the line and the delta are always
  *captured*. Every number goes through `UsageFormat.count` on the viewer's locale (`CountLiteralLintTests`).
- **D's material.** A tile is 96 pt including its padding, on `bgFocus` with a ring, the strong ring and a 1 pt
  lift on hover, and no shadow. It is clipped to its shape. Its mark stands bare. A failure speaks in `warning`
  with its dot hidden, and a live source keeps a green dot.
- **Packing.** One column count (`SourceGridColumns`, 2–4) is shared by every section. Sections share a row by
  span (`SourceGridPacking`), and the contributors block takes what the last row leaves when that is two columns
  or more.
- **Detail columns.** Opening a source, or an author in *Who wrote your memory* (a chip strip over a neutral,
  labelled share bar), narrows the page to a list of rows and opens it as the detail column (`SourcesSelection`,
  `SourceDetailView`, `ContributorDetailColumn`). A conversation's Reader is the third column.
- **What changed from v2.** The contributor drill-down is a column, not a sheet, so its "from conversation" is
  never under a modal. A compact G129 light never draws the Full Disk Access fix
  (`BrowserStatusLight.showsFixHint`); the fix lives in the source's detail column. *Advanced statistics* is a
  remembered disclosure on the old toggle's `cicada.usageMode` key. "Add a source" is a neutral button in the
  eyebrow row, which reads "Sources · n connected".

**Clusters and the Feed (Direction D, DS-3c).** Both are list pages in progressive columns: an eyebrow row with
text tabs (`AdaptiveTextTabs`: with counts, then without, then a menu, so a tab is never clipped), the list, a
detail column, and the Reader as the third column (each list page hosts its own: `AppTab.hostsOwnReader`).
`ListColumns<ID>` holds the open row: a row that leaves the data, or that the chosen tab does not show, closes the
detail; one that find (or Clusters' View menu) hides stays open. Keys follow DR-68: ↑/↓ swap in place, ⏎ steps in, Esc closes the rightmost column, and ⌘F opens
the page's find row.
- **Clusters has one filter:** a View menu with the Graph's own types (`graphVM.filter.types`), labels, and a
  remembered *Expand all*. Its tabs are navigation: All plus each present type. All's groups show five rows (three
  beside a card) and "Show all N ›". The detail column hosts DS-3a's `EntityDetailCard` as it is, in its `.card`
  style, with its `TopicDetailNavigation` trail and the page's Esc order passed through the card's `onEscape`. A ⌘K
  ⌥⏎ landing opens the entity's type tab. Rows carry no logo and no age: `/graph` nodes have no `lastReferenced`.
- **The Feed** has sort tabs (Relevance · Recent) and kind tabs (`FeedKind`: paper, video, bookmark, link). Its
  rows are 56 pt, each with the origin's real mark. The Connected strip and the export waits scroll with the list,
  and only with nothing open, so the eyebrow is the only fixed band. That fixed the header drawn under the
  titlebar.
- **A saved item's detail column** shows `MediaPreview` (a video plays at the column's width), "Why it's saved"
  (the page's own words, then the pages it is about, known ids only), and "Saved from" (the origin's mark, name,
  folder and day, or `[ no source recorded ]`). The palette's saved-item row and a source page's items land there
  through `AppRouter.routeToFeedItem`, and the preview sheet is gone. The one-shot import's `+` (with ⌘N) is an
  icon in the eyebrow row and opens the unchanged `AddSourceSheet`, whose root hosts the one `IntakePanel`.

**Projects (G141 PJ-5, Direction D).** The eighth page (⌘8, after Sources), the first designed for D: a list page in
progressive columns over `GET /projects` and `GET /projects/{id}/timeline`, which are **not** Store domains —
`ProjectsCache` (app-level, in memory) revalidates them with the server's ETag when the page appears, a project opens, a
write lands, or a sync event moves `entities`/`episodes`/`inbox`/`bank`, and a bank switch empties it (no
`VersionVector` mapping, nothing on disk). The wire decodes leniently into local `Project*` types (the shared `Claim` is
untouched); derived state is `ProjectState`, the Swift twin of `project_state.timeline_state`, running the same
`api/tests/fixtures/timeline_state.json`; every relative word comes from `RelativeDay` over `ISODay` in the viewer's
calendar (a lint keeps the day words there), and midnight re-derives the page with no network. The story is derived off the main actor (`ProjectDerived`, keyed
by project, day and cache revision; the last value stays up while the next builds) and Lately is one lazy list, so a
project whose happenings cite hundreds of pages opens at once (round-4 D6). Every Swift test reads
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
  participant a chip that opens its card, at most eight per sentence with a '+N more' that opens that row (round-4
  D6; the server sends the first 12 and `participantsTotal`), the owner as the sentence's own word with a "you" tag; a status word; a
  source line with the origin's mark and "Show in conversation ›"; Resume where resumable; Not right); Plan (Add with
  an optional picked date, Mark done, Rename, "moved once ›"); Around this project (People · Tools & infrastructure, a
  tool unfolding its specs · Documents & links · Ideas · Parts of this project). The Reader or an entity card is the
  third column; Esc closes the Reader, then the card, then the project.
- **Writes** are `ProjectWrite` mutations through `Store.perform`: painted where the answer is known (a thread settled
  or restated, a milestone done, renamed or added, a withdrawal), rolled back with the server's own 409/422 sentence
  (a 400's or 404's detail is never shown — it names ids), disabled while Sleep runs; nothing relative is sent as a
  value. L · M · D are key presses on the focused project (the Inbox's O / L precedent), never menu key equivalents.

**Sleep page — the study room (G125 v4, Track Z).** One 760 pt column at every width: the room,
one sentence in the display face under it, one Consolidate/Cancel control with the engine menu
beside it — a neutral button naming what a cycle you start would run (`preview.manual`, "Auto ·"
under Auto) that opens the five engines with their real marks, the chosen engine's model and both
ruling-4 previews; the "Runs on …" caption retired into it, and Cancel's caption shows while running
— one whisper line for the schedule, and everything else under a single **Details** disclosure (Last
cycle · What's waiting · Readout · Past nights) in D's list grammar — section labels over rows, no
cards; Last cycle's rows in words, "Rested" as a sentence, the readout as key–value rows — closed by
default, remembered per viewer
(`cicada.sleep.detailsOpen`) and not built while closed. The worm speaks in that one fixed slot —
`roomSentence` / `wormAnswers`, pure
`SentenceLine` values over `SleepPageModel` (lead ≤ 40, tail ≤ 80, clock-free; a missing fact
omits its rung, never shows a guess); the floating bubble is retired. **Two kinds of art (R-Z1):**
*state art* — the mood's frames, the lamp (= the schedule), the pile, and the window's **weather**,
a total function of the mood with a legend popover as its twin — and *response art* (gaze, perk,
talk, cheer), transient and never contradicting state. The art layer stays inert; interaction is a
hotspot layer derived from the pure layout (`deskHotspots`), and **no click on art changes what the
machine does**: the lamp's popover shows the scheduled engine and its reason *before* its labelled
toggle can flip, and Consolidate stays the one trigger. The strip appears only while running or
frozen after a cancel or failure; the running stage is `activeStage(completed:)` = completed + 1
everywhere (page, menu bar, onboarding, strip). A real completion cheers once and offers "See what
changed ›"; a cancel neither chews nor cheers. Memory sources left the page (Sources v2 draws it;
the series live in `Views/Sources/ActivitySeries.swift`). **Feeding (Z9).** A file, files or a
folder dropped on the room — or *Feed a file…* from the worm's context menu and VoiceOver actions,
which open the intake's own `IntakePicker` — go to `IntakeRouter.accept(urls:from: .sleepRoom)` and
nowhere else. While a file hovers, the worm is expectant toward it and eager over itself behind a
dashed chrome outline, and the window's veil steps aside (`nearerDrop`); it gulps when the router
takes the drop and shakes when it does not, and the sentence tells the router's own phase in words
with no number — the panel has the counts. A sleeping worm takes the drop and stays asleep; a stale
page sends nothing. **Meadow (Z10).** The sentence is the display face (SF Pro Display semibold 30,
`displayTracking`) over an SF italic tail (F1 R-FX13), Consolidate is the page's one `PrimaryActionButton`, `SleepMotion` forwards its shared names
to `CicadaMotion`, and the sky band above the page is OFF (`SkyBand.ships`, TODO ruling 10). The
pile is compressed to its column at every zoom and queue size — at most eight spines, the order and
every count kept, never cut (`fitPile`) — and the title is `PageTitle`, the view `PageHeader` draws.
Refused: autonomous beats with no fact behind them, cloud drift, a storm flash, estimates, prices.

**Mascot states (G107).** `BookwormState` gained `reading` for this page only —
`deriveSleepPageMood` returns it where the menu bar's `deriveBookwormState` returns `.curious`, and
the menu bar's own precedence and sprite meaning are unchanged. `store.intakeInFlight` (set while
the intake router has a request in flight) forces `reading` ahead of `happy`/`hungry` but never ahead of
`sleeping`/`error`/`digesting`. Per-cycle duration *estimates* stay deferred (G107's own ruling);
only a measured, telemetry-joined duration is ever shown. Track Z adds **response art** inside
`BookwormSprites`: `BookwormPose` (idle · attentive(gaze) · expectant(gaze) · eager) and
`BookwormReaction` (perk · talk · gulp · shake · cheer), gated by one state × response matrix
(`BookwormState.allows`, `acceptsGaze`) so a sleeping worm's eyes stay shut and red pupils never
look away; every beat is ≤ 3 frames × 0.12 s; a hop is a whole-cell shift (a capped state crouches
instead — the nightcap owns the grid's headroom); and a lint bans
`.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(` on the worm except its lattice placement. The
renderer key gains one `look` segment, omitted for idle (every older key byte-identical); the
page's reachable set is ≤ 256 keys per size and the wipe bound is 1024. **Feeding** — a file dropped
on the worm imports through the one intake (R-Z10) — shipped in Z9; the matrix decides its gulp and
shake like every other beat.

**View menu (G130 slice 1a).** ⌘+ / ⌘− / ⌘0 scale the whole chrome — one persisted `uiScale` behind
every `CicadaTheme` font and spacing token, so every reader repaints with no `.id()` anywhere (the
PR #49 lesson repeated). The graph canvas keeps its own zoom; ⌘+/⌘− means chrome, not canvas, same
as a browser's page zoom vs. a map widget's. `Settings` gains a *General* tab (Appearance + a Text
size slider) alongside Agents, Plans & keys and Schedule. Slice 1b (PR #58) finished the job:
every literal `.font(.system(size:))` / `Font.system(size:)` in `Sources/` now goes through
`CicadaTheme.font(size:...)`, and `FontLiteralLintTests` fails the build on a new one.

**Find palette (G136).** ⌘K ("Find in Memory…") and ⌘F ("Find on This Page…") are menu commands in
`Support/FindCommands.swift` — a lint (`HiddenShortcutLintTests`) keeps both shortcuts there, and ⌘F
reaches only the visible page's field. The palette is an overlay anchored 4 pt under the titlebar — 640
pt, an opaque `bgMenu` floating surface over the panel scrim — that appears and leaves in one frame
(DR-60); its instant tier (`QuickIndex`) is rebuilt off the main actor from the Store's snapshots and
answers every keystroke with no network; ~150 ms later `GET /search` (prefix, then hybrid) appends
conversations, beliefs (superseded ones as history) and whatever the local tier missed — a shown row
never moves. Ask is a mode (⌘⏎) hosting the unchanged `AskPanel` body. One ranker, `QuickMatch`,
folds text exactly like the server's `text_fold`; every in-page field is `CicadaSearchField`.
Recents are `(kind, id)` pairs in the cache-only `.quickRecents` domain; the query is never stored,
logged or sent anywhere but `/search` and `/conversations/recent?q=`. `FindPanelBody` is the hostable
body (Home). Settings' pages and every static row are in the palette from `SettingsIndex` (one index,
one ranker); ⏎ lands on the row through `AppRouter.openSettings(_:row:)` (DS-3b).

**Brand marks (Track L).** One map, `OriginIconography.logoName(for:)`, and one precedence:
**installed app icon → bundled PNG → SF Symbol**. Apple's marks are never committed (Safari and
Apple Notes resolve through `NSWorkspace` by bundle id, then their own SF Symbol); every other mark
is fetched once by a maintainer with `scripts/fetch-logos.sh`, declared in
`Resources/logos/logos.manifest.json` (source, licence, trademark restriction, sha256) and
attributed in `Resources/logos/LOGOS.md` — marks committed before the pipeline are declared
`legacy` (12 of the 27): the script never fetches them, their sha256 is verified on every run, and
their licence line records the commit that introduced them rather than an upstream grant. **No
runtime network:** none of the three outbound gates is involved. A raster whose background IS the
mark (`claude-code`, `claude-desktop`, `hermes`) is never recut — every surface that draws one
clips it to its own curvature instead, and `LogoAssetTests` names them so a fourth cannot arrive
unnoticed. Nominative use only — a vendor mark is never restyled or recoloured; the one permitted
transform is an exact luminance inversion of a *monochrome* mark into its `-dark` sibling, which
`LogoImage` picks under a dark theme. Drawn brand glyphs are gone and do not come back.

**Design rules — Direction D, "Focus columns" (2026-09-23).** [`docs/design/DESIGN_RULES.md`](docs/design/DESIGN_RULES.md)
is the binding target for every UI change: graphite neutrals, the system accent, SF Pro only, a 56 pt icon rail, a centred
command bar holding the bank selector and search, and progressive columns (the list alone → list + detail → list + detail +
Reader). Rules are numbered `DR-n` and a UI PR cites the ids it applies; a departure needs a dated ruling in its §9. The owner
chose D from three mocked directions (the Inbox and the Reader). DS-1 shipped the tokens, the type, the shell and the
Settings panel; DS-2 (2026-09-24) shipped the Inbox in progressive columns and the Reader as a column; DS-3b
(2026-09-24) shipped Home, the Sleep page's engine menu and Details, and the Settings panel's fixes. DS-3a (2026-09-24)
shipped the Graph page and the entity card, and DS-3c (2026-09-24) shipped Clusters, the Feed and Sources in progressive
columns. Every other
page paragraph below describes what ships until that page's DS track lands.

**Graphite and Meadow (Direction D, G137).** Working surfaces are graphite — `bgRail` · `bgBase` · `bgPane` · `bgHover`
· `bgFocus` · `bgOption` · `bgButton` · `bgSelected` · `bgMenu` · `bgKey` · `bgBadge` (DESIGN_RULES §3.1, chroma ≤ 4,
`ThemeTokenTests`) — with the pre-D names as aliases (`background`, `surface`, `surfaceHover`, `surfaceElevated`) and
`border`/`borderLight` the opaque twins of the resting ring and the input border (graph.js's edges). Text is four steps
plus `textTertiaryOnFill` (`ThemeContrastTests` holds every surface). The accent is the Mac's (`Color.accentColor`);
DR-5 allows it six uses, and the pre-D call sites that still read `CicadaTheme.accent` (now the Mac's accent, so a
state dot among them changes hue on a red or orange Mac) are swept by each page's DS track. `accentText` derives from it — exactly the rules' values for the default blue, pushed to ≥ 4.5:1 for
any other (`AccentInk`). The retired indigo survives only as a data hue (the "active" status, the heat ramp). Depth is
an inset ring, never a shadow in dark and one soft shadow on a light floating surface (`ringed`, `floatingSurface`,
`Theme/Elevation.swift`; `ElevationLintTests`) — the target; the three sites that lint still allowlists
(`MediaPreview`, `HeroPreview`, `WelcomeView`) shadow until their tracks; `GlassCard` is a `bgFocus` card with a ring. The nature tokens (`sky`,
`meadow`, `dandelion`, `cloud`, `bark`, `soil`, their washes, the procedural skies) are for art and reward moments
only, never a data encoding and never behind a row — `progressFill` (§3.8) is the one exception, for Projects.
**Liquid Glass lives in the chrome layer only**, through `Theme/LiquidGlass.swift` (gated on macOS 26 with a material
fallback, opaque under Reduce Transparency); a lint fails the build on any glass API elsewhere. **Painted art**
(`Resources/art/`, `art.manifest.json` with generator, prompt, date, licence and sha256; every file has a `-dark`
sibling) appears only on non-data surfaces — never the graph, a list, a grid, a form or a number, and text never sits
directly on paint — enforced by an allowlist lint; the Welcome's hero band (`WelcomeHero`) and Home's sky band
(`HomeHeroBand`) are composed inside `Views/Meadow/`. **Type:** SF only. `displayFont(size:italic:)` is SF Pro Display
semibold (tracking −0.3 at 20 pt, −0.4 above, floor 20, paired and counted by `FontLiteralLintTests`), `quoteFont` SF
15 regular, one `SectionLabel` (11 medium, sentence case, never mono or tracked — `SectionLabelLintTests`), monospace
only on `MonospaceLintTests`' allowlist (code, commands, paths, keys, ids), and `CitedSpan` the washed, underlined span,
read by the Inbox's quote and the Reader's turns since DS-2 (a mention found by name is its semibold, unwashed case). **Motion:** `CicadaMotion` (nil under Reduce Motion) is the only place outside
`SleepMotion` a duration is spelled; `hoverLift()` for things that open, `iconHover()` for glyphs; a keyboard action
never animates.

**Video (Track V).** A saved video plays where the user already is — a saved item's detail column in the
Feed, the entity Content tab and the entity hero, all through `MediaPreview`/`HeroPreview` — and the provider is
derived from the URL at read time (`VideoRef.resolve`), never read out of the page, so a bank never
needs rewriting to teach the app a new one.

**Provenance viewer (G118 slice 2).** Every claim carries evidence chips (`Views/Provenance/`): the
label says who spoke ("You said", "<agent> replied", "From the page", "Inferred", "Mentioned here"
for a legacy claim's name match found at read) — an agent's chip names its model when capture recorded one ("Claude
Code · Opus 5.5 · high effort", `ModelNames`; round-4 C3/C4), as do the hover, the Reader's meta line and turn labels,
"Where this came from" and a belief's help; an app with no capture says "model not shared by this app" — hovering shows the words in the quote face — washed
when quoted, bold when derived, plain when stale — and a click opens the **Reader**, a column
(`ReaderColumn`): the third progressive column on the list pages that host it (the Inbox, Clusters, the Feed,
Sources and Projects — `AppTab.hostsOwnReader`), and on every other page the shell's trailing column (`ShellReaderHost`),
sized before the page so it is never pushed off-window. It is driven by
`ProvenanceRouter` (a stack of `ReaderTarget`s), beside whatever is open so a belief and its sentence
are on screen together (Direction D, DS-2). It shows C's header — mark, title, meta, and a neutral
Resume when an `isfile()` check says the session is resumable — the pinned "1 of N cited here"
navigator, the turns in the quote face with `CitedSpan`, and the "Noted from this conversation" rows;
a swap onto the same conversation re-lands in place (`ProvenanceRouter.refocus`) rather than stacking
a Back step. The dandelion wash and margin bar are gone (DR-13). It reads `/episodes/{id}/text`
and `/citations` through `ProvenanceCache` — in memory, ETag-revalidated, **never a Store domain**,
so there is no `VersionVector` mapping — slices every offset as a Unicode scalar through one
`ScalarText`, reads a quote and a turn without their markup or role labels (`ExcerptText.stripMarkup` /
`quoteParts`: deletion only, so every span maps exactly; the Reader keeps a turn's lines, drawing a bullet as "•"),
shows a time only when the episode stores one, and says stale / grown / derived /
inferred / truncated in words — a span its rewritten document no longer reaches (the server's 422) is
stale too, never "couldn't open". The entity card's "Where this came from" (Content, after the page and its beliefs) reads
`/entities/{id}/provenance` once per card; G61's section is "Look it up at". Chips read the router
and cache as optional environment values, so a chip outside the main window renders without a
click-through rather than trapping; the Ask sheet steps aside when the Reader
opens (the Belief Timeline is inline in its tab since DS-3a), and a bank switch closes it and empties the cache (episode ids repeat across banks).

---

## API Design

32 routers mounted in `api/main.py`, plus repo-context and maintenance endpoints. **Read the routers
for the endpoint list** — it is not duplicated here. What is *not* derivable:

**Auth.** Every endpoint except `GET /healthz`, `POST /capture/telegram`, and an OAuth adapter's
`GET /sources/connectors/{id}/callback` requires `Authorization: Bearer <token>`, from
`~/.cicada/api_token` (`CICADA_API_TOKEN` overrides; `CICADA_API_AUTH=off` for tests). The Telegram
webhook is exempt because Telegram's servers cannot send the header — today it is gated only by
Telegram being configured, not by a per-request secret (**see G57**). Each OAuth callback lands in
the user's browser, which likewise cannot send the header, so it is gated by its own single-use,
10-minute `state` nonce; `auth.py::_is_oauth_callback_path` resolves the exemption live against the
connectors registry rather than hardcoding a literal per adapter.

**ETags.** `/graph`, `/inbox`, `/contributors`, `/sources`, `/sources/channels`, `/origins` and
`/banks` all return an `ETag` and honor `If-None-Match` with a `304`. This matters: `/graph` on the
live bank is ~1.8 MB. **Ship the ETag and its client mapping together** — `GET /inbox` ETags over
`inbox`+`entities`+`episodes`, and `VersionVector.swift` maps `entities` and `episodes` onto
`.inbox`; change one half, change both. `/graph`'s `extra` carries a node-shape tag
(`graph.NODE_SHAPE`), bumped when a node gains a field a client must see or the body changes for
the same files (F1's context filter and fence strip); an entity node's hash also folds its derived
`contexts` and `summary`, so `GraphDiff` re-pushes a node whose derivation changed. `/projects` and
`/projects/{id}/timeline` (G141) ETag over `entities`+`episodes`+`inbox` with `extra` =
`projects|<shape>|<author shape>|<machine zone>` (`git_service.AUTHOR_SHAPE` since round 4, R4B-9) — never today, never a viewer zone — and are **not** Store domains
(no `VersionVector` mapping, fetched on demand like provenance). A timeline item carries at most
12 participants plus `participantsTotal`, and a cluster group at most 8 names no page holds yet
(round 4 D6; `PROJECT_SHAPE` g141-3). The person's writes (G141 PJ-3b) —
`POST /projects/{id}/milestones`, `PATCH /projects/{id}/milestones/{slug}`, `POST /projects/{id}/happenings`
(the Log: one time phrase becomes the day, a companion episode keeps the words), `POST
/projects/{id}/threads/{claim_id}` and `POST /projects/{id}/withdraw` (happenings only) — answer **409**
while Sleep runs and each commits alone over its own pages as `Cicada-Author: user`,
`user/companion_app`.

**Endpoint traps worth knowing before you touch them:**

- `GET /entities/{id}/history/{commit}/diff` — a file's FIRST commit has no parent, so `git show`
  diffs it against the empty tree and it comes back all-adds; a MERGE commit needs `--first-parent`,
  else git emits a combined (`--cc`) `@@@` diff the parser can't read and the endpoint silently
  returns nothing. `truncated` is the UNION of three caps; `linesTruncated` specifically means "the
  ordered list was cut" and is what a client renders its banner on.
- `GET /conversations/recent` is **CAPPED** (limit ≤ 200) and is never a membership test; filters
  (`harness`, `origin`, and `q`, a title filter) apply BEFORE the cap. Use `GET /conversations/{id}` to
  resolve one id against the whole bank.
- `GET /search` runs in the threadpool. `mode=prefix` (the per-keystroke pass) is FTS only and never
  loads the embedding model; `mode=hybrid` (the default) fuses FTS with the stored vectors and reports
  `mode: lexical` when no vector index answered. `totals` are exact **lexical** counts — semantic
  neighbours are ranked, never counted. An `indexState` other than `ready`/`stale` means entities and
  media only, from the frontmatter cache. No ETag: it is never a Store domain. Its query string (and
  `/conversations/recent`'s) is stripped from uvicorn's access log; a new query-bearing GET joins
  `_QUERY_PATHS` in `api/main.py`.
- `POST /conversations/{id}/resume` returns a validated descriptor — **transcripts are never read,
  `isfile()` only**.
- `POST /maintenance/enrich-links` returns `409` both while a Sleep cycle runs and while another
  call is still running (a process-local lock — two overlapping clicks would stage each other's
  half-written pages under their own trailers).
- `GET /sync/version` is the cheap change-detector (<10 ms); `GET /sync/events` is the SSE stream.
- `GET /projects[/{id}/timeline]` serve absolute days (`tzName` is the machine zone they are bucketed
  in) and never a relative word; the client derives 'yesterday', 'overdue' and 'quiet' through
  `project_state.timeline_state` (its Swift twin shares `api/tests/fixtures/timeline_state.json`). A
  404 means no page or not a `project`.
- `POST /intake/import` answers **202** with `{job}` when more than 10 episodes would be written; poll
  `GET /intake/jobs/{id}` (process-local — gone after a restart or an hour; the episodes are not). One
  stage runs at a time per process.
- `POST /conversations/upload` is a deprecated shim over the one intake — new callers use
  `POST /intake/import`; its `turns` sidecar is a list, as on Stop-hook episodes since G141 PJ-4 —
  only a Stop-hook episode written before PJ-4 holds an **integer count**, so a reader checks the type.
- `GET /memory/decay-suggestions` / `PUT /memory/decay-tuning` (G147) are not Store domains and carry
  no ETag; both answer one shape (`bank`, `windowDays`, `tuning`, `suggestions` — types and counts,
  never a page id). The PUT merges `{type: multiplier | null}` within [0.25, 3.0], answers **409**
  while Sleep runs, and commits `_decay_tuning.yaml` alone as `Cicada-Author: user`.

---

## Features

### 1. Graph Explorer
Force-directed d3 graph: node color by type, size by confidence, edge labels, cluster detection,
decay/clarification indicators. Open ideas live in the backlog.

**The page (Direction D, DS-3a).** The canvas fills the content area under the command bar. Its chrome is one
floating group at the bottom-left — the whose-beliefs text tabs (only with more than one observer; they move
into the Legend under 640 units), Legend, − + fit and the pan toggle — an opaque floating surface, never glass
over the canvas until the G109 frame-time check has run (R-DG2). The Legend is the context legend, the filters
and a key in one: a context click shows only that context, confidence is words, Show logos is a switch. ⌘F
opens find on the canvas as an overlay (⌘K searches everything); the page's own field is gone. A node opens
its entity card as the right-hand column (`GraphColumns`: 560 alone, 480 beside the Reader, never under 440;
the canvas takes the rest and keeps the open node in view by panning, never zooming), and its evidence opens
the Reader beside it. × or a click on empty canvas closes the column with its Reader; Esc closes one thing at
a time — find, Legend, Reader, column; another node swaps the column in place and keeps the Reader. graph.js
posts `backgroundClicked` and `escape` and takes `setSelectedNode` (a neutral ring), read and spelled in one
place (`GraphMessage`, `GraphJS`) and tested on both sides — none of them touches the simulation.

**The entity card (DS-3a).** One component, `EntityDetailCard` — the Graph's column, Clusters' card. Header:
the type as a `Tag`, status and confidence in words ("Active · very confident", the number in `.help`), the
name, the page's Summary, Back ⌘[ and ×; text tabs Content · Perspectives · History · Timeline with counts once
known. Content: Rendered/Source and Copy; the page; its folder or repository in words; What Cicada knows (R-FX11
pages); Where this came from; Look it up at — each G61 source's fact ("For uses"), how it can be read (the
stated `access`, else a path or repo is "A file on this Mac" and an app "An app"; `effective_access` is not on
this endpoint), who added it with their mark, "You chose to use this" / "Only you know this", no check line
until G61 S3 serves one, and the page's open inbox question with Open in Inbox; Details (collapsed, remembered):
tags, related, dates, how it fades. Beliefs are rows — the sentence, its evidence chip and its age, the rest in
`.help`. History: Show in conversation (straight to the Reader when one conversation maps here) and What
changed. Timeline: contested beliefs inline; a belief's clock opens its own.

### 2/3. Unified inbox (`memory/inbox/`)
Nudges and clarifications live in **one store**: `memory/inbox/inbox-NNN.md`, each with a `kind`
discriminator (`decay`, `conflict`, `clarification`, `merge_suggestion`, `removal`, `divergence`,
`normalization` — the last two were written by Sleep since G49/G98 but only became loadable and
resolvable kinds with G113; `removal` is written by a live browser sync, not Sleep, at proposal
time (G129 slice 2); `followup`, G141 PJ-6, by Sleep's engine-free tail), behind `GET /inbox` /
`POST /inbox/{id}/resolve`. `api/routers/nudges.py` and `clarifications.py` are thin **deprecated**
shims (they set `Deprecation: true`) kept only for external callers — the app calls `/inbox`.

**Question object (G60).** Every item carries `question`, `options: [{key, label, description, …}]`,
`allow_other`, `allow_defer`, `predicate` and an optional `hint`. Descriptions lead with the age
phrase ("6 months ago") so staleness is visible before choosing; `age_days` is derived at read time,
never stored. Legacy flat `options: [str]` still render.

**Dedup + time.** Items are keyed `(entity_id, predicate)`. A second competing value **merges** into
the open item as another option instead of writing a duplicate. Each Sleep,
`inbox_questions.refresh_open_questions` bumps re-mentioned options, auto-resolves questions the
user answered organically, escalates a question whose every option has been silent for
`inbox_stale_after_days` (90) by inserting "Neither anymore", and keeps deferred items out of
`GET /inbox`.

**Resolve is claim-aware.** Picking an option supersedes every losing claim (`valid_to` +
`superseded_by`); "both" keeps them open with a `context` qualifier; "neither"/free text writes a
`user_stated` claim that closes them; `defer` writes `remind_after`. All commit with
`Cicada-Author: user`.

**Every resolution is a verdict (G113).** The commit trigger names the action taken
(`inbox/<kind>/resolved:<label>`; a deferral stays `inbox/deferred`), decay `archive`/`keep_active`
land as `statusChange` history entries, a decay `keep_active` and a clarification free-text answer
write back to the claim layer, a rejected merge is remembered in `<bank>/_merge_rejected.yaml` so
neither `clarification_manager` nor the dedup sweep proposes the pair again, and `remind_later` is a
7-day defer (shipped with G115 Phase 1). Each of these also records a `resolution` telemetry event —
see Telemetry ledger.

**The page (Direction D, DS-2).** Progressive columns (`ProgressiveColumns`, `ColumnLayout` — DESIGN_RULES §5.3): the
questions alone at full width; a click narrows them to the triage column and opens the question as C's focus card;
"Show in conversation" opens the Reader as the third column. Widths are units (÷ uiScale); the list hides before the
question drops under 440, and when neither the question's 440 nor the Reader's 360 fits they share the width, so
nothing is pushed off-window. **One tap answers, and Undo is a send delay** (`ResolveGrace`, in the `Store`): the
answer leaves `visibleInbox` at once and `POST /inbox/{id}/resolve` waits 5 s (`CicadaTiming.undoWindow`), sent
early by the next answer, `ActivateBank` (before the bank moves), the window closing and quit (`.terminateLater`,
≤ 3 s) — an undone answer makes no commit, claim or G113 event; a page switch does not send. Every kind renders in
the card (`FocusCardVariant`), options come from the server (a follow-up's 30-day "not now" is its own option), the
source is named in a person's words (`InboxSourceLine`, ids in `.help` only), an asserted span is washed and
underlined and a found mention is semibold. Esc closes the Other… field, then the Reader, then the question; keys
never animate. No in-page search field — ⌘K's Inbox group lands in STATE 1. The list takes the
keys when the page appears and after every answer (the question only when DR-27 hides the list), so a
repeated digit never sweeps the queue past its one Undo (DS-3c). An option, an informational value or a merge target
that is exactly a page's id reads as the page's name (`Store.entityNames`, display only). The Sources page's Deletions render the same card and Undo row.

**Cause (G115 Phase 1, delivers G97).** Every item carries its `cause` — episode, timestamp,
conversation, harness, excerpt, offsets — resolved **at read** by `api/services/inbox_context.py` in
three tiers (item → claim → entity), engine-free. The excerpt is ±240 chars around the mention, cut
on word boundaries, **offsets recomputed on every read and never stored**. Nothing resolves →
`tier: none` and a literal `[ no source recorded ]`, served — never a hidden card.

**Checkability (G61 phase 2 S2).** Every item also carries `check` — `{state:
checkable|needs_source|inform_only|never, reason, locus, targets[], rungs[], settle_eligible}` —
derived at read by `source_check.for_item` from the item, the subject page's `sources:`, `owner:`
flag and claims, and the predicate `locus`: pure, engine-free, zero-network, never stored. Nothing
acts on it yet (no check, hold or settle — S3+), and the app does not read it. `GET
/inbox/check-census` and `scripts/check-census.sh <bank>` report it as ids-free counts — the coverage
gate for S3–S8.

**Decay is no longer the special case.** Served as `Still tracking {name}?` with `archive` / `keep`,
synthesised at read from the page's `last_referenced`, never written. Its question sets
`allow_other: false` and **the whole stack now means it**: free text on resolve is a `400`.

**Neither is a bookmark removal.** Served the same way as decay — two closed options
(`keep`/`remove`), no free text, no recommendation (the proposal came from the browser's own
before/after diff, not the extractor) — `remove` archives the media entity it named; it is never
deleted.

**Follow-ups (G141 PJ-6).** A quiet ongoing happening (quiet ≥ max(21 days, the project's own Q)), a
planned milestone 3 days overdue, or a `due` that expiry closed in the last 14 days raises one
engine-free `followup` item — at most one open per project and three in the bank — written by Sleep's
tail right after expiry (`Follow-ups <date>`, `cicada`, `sleep/followup`, dirty pages skipped) and served
as a question at read, like decay. Its 'not now' is an explicit option that defers 30 days (`allow_defer`
false, so the shipped app's 7-day button never shows; the server clamps any defer to 30). Answers go
through `progress.py` (origin `clarification`) and grade the extractor: done/still agreed, 'That didn't
happen' overruled, a person's own thread always neutral.

**G98 rule.** A multi-valued predicate never opens a conflict; an existing one is served
`informational: true` — the card lists the values and offers `Got it`, which removes the item and
touches no claim.

**Three resolution paths for a clarification:** organic (the user provides context later, Sleep
promotes it), agent-initiated (the agent asks in flow when the topic comes up), manual (the app).

**Observer inconsistency — resolved (G117).** All five sites (the inbox resolve path, Telegram
capture, `agentic_write`'s trust/origin gate, and MCP `cicada_write_claim`'s schema/description) now
read `owner_identity.resolve_observer` instead of a hardcoded literal, so a bank's claim lineage
never forks across writers.

### 4. Manual Sleep trigger
"Run Sleep cycle now" + next-scheduled indicator.

**Schedule modes (G125 R6/R7).** Settings → Schedule offers four modes on `ScheduleConfig.mode`:
`manual`, `daily` (hour/minute), `interval` (`interval_hours`, 1–168, default 6), and `after_import`
— no writer hooks an import; `sleep_scheduler` installs a 5-minute `IntervalTrigger` probe that
fires `run(user_triggered=False)` only once the queue has *settled* (idle, non-empty, and the
newest unprocessed episode is ≥ `AFTER_IMPORT_SETTLE_MINUTES` (10) old — `SleepDebt` carries
`newest_unprocessed_at` so the probe and `next_run_at` share one scan). `enabled` is derived
(`mode != "manual"`) and always written on the wire so an older client still decodes; an old
`PUT {enabled,hour,minute}` with no `mode` is accepted and mapped onto `daily`/`manual`. Every
scheduled path — daily, interval, or the settle probe — passes `user_triggered=False`, so a
scheduled cycle never spends Claude or ChatGPT plan quota (the standing ruling in `TODO.md`).

### 5. Conversation upload
**One chat-export pipeline (Track I).** Claude, ChatGPT and Gemini exports — a whole .zip, a
folder, or one file — go through `api/routers/intake.py`: every member a parser knows (a Claude
zip's conversations, memories and projects), the known extras (`user(s).json`, feedback and
comparison files, ChatGPT's `chat.html` viewer) skipped **by name**, the vendor's `origin` stamped
on every path, per-message times kept as `turns: [{offset, ts, speaker}]` outside `content_hash`,
and re-imports updating grown threads in place (G20) without duplicating. `POST /intake/sniff`
previews and stages nothing; `POST /intake/import` stages. `/conversations/upload` (deprecated,
`Deprecation: true`) and `/banks/{name}/import` are shims over it.

---

## UX Principles

1. **Minimal friction**: responding to a nudge = one tap. Never require "memory maintenance".
2. **Transparency over magic**: the user sees WHY the agent knows something (provenance), WHEN it
   learned it, HOW confident it is.
3. **User authority**: agent proposes, user disposes. Every automated action can be overridden.
4. **Non-intrusive nudging**: available when wanted, not pushed. The inbox is there when you want it.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Markdown over Neo4j | Same relational expressiveness at personal scale. Zero infrastructure. Portable. The LLM is the query engine. |
| sqlite-vec over LEANN/FAISS | Stored (not recomputed) vectors give single-lookup latency with no cloud dependency; the index is derived and disposable. |
| FTS5 beside sqlite-vec | Type-as-you-go needs words, not meanings: a derived lexical index answers a prefix in ~12.5 ms p95 at 2k entities / 1.5k episodes without an embedding call, and finds aliases, claims and conversation text by what they say. Derived and disposable, like the vectors. |
| Batch over real-time consolidation | Conversations don't have clean endings. Batch sees patterns across a full day. Clean evaluation. |
| Entity promotion over upfront extraction | Avoids polluting the graph with noise from single mentions. |
| Temporal decay as an active signal | Absence of mention is informative. No other system does this. |
| Clarification queue over silent drops | Ask rather than guess or discard. Prevents cascading hallucination. |
| MCP-native + export fallback | MCP for real-time, export for ChatGPT/Claude. Source-agnostic pipeline. |
| SwiftUI + FastAPI | Native macOS feel. Python backend for the LLM/ML ecosystem. |
| d3-force in WKWebView | Best graph-visualization ecosystem. Sufficient at personal scale (G109). |
| Filesystem as single source of truth | No separate database. The API reads/writes the same files as Sleep. |
| Decay class over a bare per-writer rate | A hardcoded float was invisible to the agent, unchangeable by the user, and decayed bookmarks — artifacts that never become less true. |

---

## Reaching the outside world

Three gates, and they do **not** mean the same thing — read the difference before adding a fourth:

- **`CICADA_ALLOW_CONNECTOR_FETCH`** gates the default transport of every fetch Sleep starts on its
  own: the unattended nightly connector poll, **link enrichment's page read** — Stage 5.57's
  in-cycle pass (`sleep_cycle._link_summarizer`, G61 phase 2 S0) and the G102 tail backfill, both
  through `link_enrichment.default_fetch`, the rail's reference transport — and paper details
  (below). It is **opt-OUT** (on by default; `=off` disables it, which is what the test suite sets).
  A user-initiated `sync_now`, `POST /maintenance/enrich-links` and every OAuth
  `authorize_url`/`exchange_code` call are **never** gated by it — they always need the network to
  do what the user just asked.
- **`CICADA_ALLOW_FEED_FETCH`** gates RSS/ICS polling and is **opt-IN** (`=1`). A fresh install's
  LaunchAgent plist sets it; `install.sh` never rewrites a plist behind a running backend, so an
  older plist needs the key added by hand.
- **`CICADA_ALLOW_LOGO_FETCH=off`** disables logo fetching entirely. The test suite runs that way
  and injects fetchers instead.

**The remote connector (G135) — the one way in from outside this Mac.** Off by default
(`~/.cicada/remote/settings.json`). When on, a **second listener on `127.0.0.1:8765`**
(`CICADA_REMOTE_PORT`) serves **only MCP** — none of the FastAPI routers — to cloud AI apps
through a tunnel **the person** runs (Tailscale Funnel or ngrok); **Cicada never starts, stops or
reconfigures a tunnel** — `GET /remote/status` only detects one — on PATH or in
the standard install folders, since an older LaunchAgent's PATH is bare (F2-back R-B15). Access is a per-connector
capability token `cic_rc_<id>_<secret>`: shown once, only its sha256 stored in
`~/.cicada/remote/connectors.db` (0600, never in a bank), scoped (`search`/`read`/`record` default;
`sources`/`answer`/`ask` opt-in — `sources` gates every verbatim word of the person's, recall's
episode excerpts and the inbox `Cause:` quote alike; `pending`, `mark_processed` and `repo_context`
never), expiring
(7/30/90 days) and revocable. It arrives as a secret link (`/c/<token>/mcp`) or a bearer header —
one verifier. Tools outside a connector's scopes are absent from `tools/list`; any `Origin` header
is refused; the listener has no access log (a secret link's path IS the token). Every remote write
commits alone as `Cicada-Author: <app harness>`, `Cicada-Session: rc_…`, trigger
`remote/<harness>`, no engine; a remote claim is `origin: remote:<id>` and can never be the
person's own words. Each call leaves one ids-only `remote_call` ledger row, filed beside `read` in
`reads-*.jsonl` so it never ticks the app's consumption domain. Every server-side fetch of someone
else's URL goes through `net_guard` (`is_global`, never `is_private`, because tailnet addresses are
neither; the name lookup runs off the event loop).

**A failed poll is recorded, not raised** (`sync_state.record_error`) and surfaces per-channel as
`lastError`; a gate-skipped poll is recorded distinctly (`record_skip`) so a skip never reads as a
failure or as a stale success.

**Paper details (G133) ride the first gate, not a fourth.** The unattended Sleep-tail lookup is behind
`CICADA_ALLOW_CONNECTOR_FETCH`; a folder sync the person asked for (`?resolve=true`) is not. Only two
APIs are ever called — `export.arxiv.org/api/query` (≤ 50 ids a request, ≥ 3 s apart) and
`api.crossref.org/works/{doi}` (public pool; no email is ever sent) — at the rail's 4 s / ≤ 512 KB;
arxiv.org pages and PDFs are never fetched, and a 403/429 stops that API for the run. That holds for
a paper link saved any other way too (a bookmark, `cicada_save_url`, Telegram): `papers.never_scraped`
keeps arXiv/DOI links and every arxiv.org page out of save-time enrichment and the link backfill.

**The ToS rail — this one is not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never
behind auth. Consent interstitials and login walls are classified and retired as `junk` **without a
byte fetched**. **A block is never retried with different headers.** No scraping behind
authentication, ever.

**Credentials** live in `~/.cicada/secrets.env` (0600) — **never in a bank, never logged**. The
shared `base.forget()` removes them on disconnect, so a fields-vs-stored drift can't orphan a
secret. Where a vendor bills per request (X's "owned reads"), the sync result carries the count so a
cost is stated plainly rather than hidden behind a "connected" checkbox.
Cicada's own Codex sign-in lives in `~/.cicada/codex/` — Codex's files, never opened by Cicada,
never in a bank.

**Video (Track V, 2026-09-05).** Only a provider's own player URL is ever loaded — YouTube
(`youtube-nocookie.com/embed/…`, incl. `videoseries?list=`), Vimeo, TikTok and Loom — and an
oEmbed response is read for its *fields* only, never its `html` blob: the player URL is derived
from the id by `video_urls.resolve` / `VideoRef`, so nothing a provider returns is ever executed.
**A stream is never derived** — no `yt-dlp`, no CDN or `.m3u8` URL lifted out of a page — so a
direct file the app plays is one the *user* saved as a direct URL. Twitch stays external (its
player validates `parent` against the real embedding origin; synthesising one is circumvention),
X and Instagram stay external. The app itself makes **no** network call to classify: oEmbed runs
only on the ingest/enrich path, under the gates that path already has, and the three new
provider calls take the rail's own 4 s / ≤ 512 KB numbers rather than the older, looser `_TIMEOUT`.

---

## Installation & Setup

`install.sh` is the source of truth; `install.md` is the paste-into-your-agent path for a fresh Mac
(clone → `./install.sh` → `make install-app` → open the app; G76), and it never loops `make doctor`.
The rest of the paste-prompt install story is G76 in the backlog.
`scripts/install-backend-agent.sh` is the one source of the `com.cicada.backend` plist; `install.sh` step 6 calls it
behind its healthy-skip guard, and the app runs it from Settings → General (G143). `BackendProcess` spawns
`python -m uvicorn`, never the venv's `uvicorn` script. `make login-item` is the old developer path; the app's switch
is the supported one.
