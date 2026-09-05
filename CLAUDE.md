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
Four rails hold across all of them:

- **The app reads `~/Library`, the backend parses bytes.** The launchd backend has no Full Disk
  Access and must never open those paths itself. An unreadable file shows the exact fix in the app.
- **Capture must not depend on a model deciding to call a tool** (G105). Every Claude Code and
  Codex session is captured by the harness's own `Stop` hook
  (`api/hooks/capture.py` → `POST /capture/transcript`). **The backend reads the transcript**, and
  only after the path resolves under the harness root as `<session_id>.jsonl` within the size cap —
  anything else is refused unread. `transcript_extract.py` keeps only the person's turns and the
  agent's final reply per turn; tool calls, thinking, file dumps and harness-injected text are
  skipped by construction. Secrets scrubbed, per-turn and per-session caps applied. **One episode
  per session** — a later Stop rewrites it in place and flips `processed: false`, never two
  episodes for one conversation (G104). Cicada's own `claude -p` spawns run with
  `CICADA_CAPTURE=off`.
- **Transcripts under `~/.claude/` are never read anywhere else.** The MCP seam and the resume path
  only ever `isfile()` them to answer "is this session still resumable"; that answer is computed
  per request and never persisted.
- **Every writer mints ids through one rule** (G114, `api/services/episode_ids.py`):
  `next_episode_id` is max-suffix+1 per date (a count-based rule collides after any gap, and
  `markdown_parser.write` overwrites on collision), and timestamps are aware UTC from
  `episode_ids.utc_now_iso` — never a naive local time with a `Z` appended. Legacy files are not
  migrated: readers accept both shapes and the queue sorts by `timestamp_sort_key`. A processed
  episode carries `processed_by` (`sleep` vs `agent`) so a flipped flag is distinguishable from a
  consolidation.

**Conversation identity (G48).** An MCP episode carries `session_id` plus `harness` and
`project_dir` when exposed — minted once per MCP process from `CLAUDE_CODE_SESSION_ID` →
`CICADA_SESSION_ID` → a `ses_*` fallback that groups but never resumes. Entities credit to
conversations transitively via `source_episodes`. A conversation row's `model` is **reserved —
always null** until engine calls carry session refs (G49); nothing that writes memory records a
model against a conversation id today, so the row says so rather than joining a ledger that can't
answer.

### Sleep — 5-stage nightly batch
1. **Entity & relationship extraction** — LLM over episode chunks, structured output.
2. **Entity resolution & dedup** — fuzzy match, embedding similarity, LLM disambiguation.
3. **Conflict resolution & pruning** — contradictions detected, recency wins, old state archived;
   temporal decay applied.
4. **Pattern detection & skill extraction** — recurring patterns distilled into skill entities.
5. **Nudge generation, clarification queue & versioning** — snapshot, git commit.

An **engine-independent tail** runs on every exit path, idle nights included: the state-dictionary
refresh, the connector poll, RSS/ICS polling (opt-in via `CICADA_ALLOW_FEED_FETCH=1`), and the link
enrichment backfill — all in a clean-tree-guarded slot, after `_finalize`'s own commit so the poll's
`git add -A` sweeps only its own files.

### Entity promotion
Entities are NOT extracted from every mention — that pollutes the graph. First mention stays in the
vector index only; promotion needs **2+ separate conversations**, OR substantive discussion (>3
exchanges) in one, OR an explicit link to an existing high-confidence entity.

### Temporal decay
Absence of mention IS a signal. Every entity carries `last_referenced` and `decay_rate`; Sleep drops
confidence proportional to how frequently it *used* to be referenced. Below 0.2 → `archive/`; below
0.4 → a decay nudge. Mentioned again → promoted back at `confidence = max(current, 0.6)`. Evergreen
entities skip all decay math.

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

| Class | Entity rate/wk | Claim multiplier | Meaning |
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
SUBJECT's class multiplier.

### Claims, evidence and provenance

**Claims** are the machine-legible half: typed predicates, bi-temporal validity, observer and trust.
A predicate the vocabulary marks multi-valued (`predicates.cardinality`) never opens a conflict.

**Evidence spans (G118) — spans, not copies.** Every claim written since that slice carries
`evidence: [{episode, start, end, kind, hash}]`. `start`/`end` are character offsets into the source
document's *evidence text* (the body as `markdown_parser.parse` returns it, with the ```claims fence
stripped for an entity page, so writing a claim never stales its own span); `hash` is
`sha256[:12]` of that text, and a mismatch reads as `stale` rather than mis-highlighting. `kind` is
`user` | `assistant` | `page` | `reasoning` (the contributor's own inference: `start == end == -1`,
never a faked span). One module, `api/services/evidence.py`, does the work for every writer: locate
is exact → whitespace-normalised → case-insensitive and **never fuzzy**; an unlocatable quote
becomes `reasoning` and **the claim is still written — provenance never blocks memory**. Legacy
claims carry no `evidence` and `to_dict` omits the empty key; there is no backfill.

**Optional frontmatter keys**, each with a narrow meaning — don't conflate them:

- `repos:` — links a project/directory entity to local git checkouts. The page only ever *declares*
  which repos; live git context (branch, ahead/behind, dirty, worktrees) is resolved **on demand,
  never cached** — `git_service` shells out fresh on every call.
- `sources:` (G61) — *where to look a fact up*, distinct from `source_episodes` (where a belief came
  from) and from the body's `## Links`. Conflict generation consults them for a "Source to check"
  hint. Nothing is fetched.
- `logo:` — a domain hint for `logo_service`. Logos are cached under `$CICADA_HOME/logos/<bank>/`,
  **never inside a bank** — a logo is a derived artifact of the outside world, not versioned memory.
- `owner: true` (G117) — marks the one `person` page as the bank's owner; `owner_identity.
  resolve_observer` is what decides which page gets it, and every user-stated claim's `observer`
  field is that resolved value.

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

**The handshake** (`api/services/handshake.py`) turns `_state.md` + a fixed contract into ≤ 1,800
tokens of primer: what Cicada is, a per-harness prelude (the contract never varies), the contract
itself, the now-view, and capability notes. Delivered three ways — the MCP `initialize` result's
`instructions`, the `cicada_handshake` tool, and `GET /handshake`. **R12: a primer naming an
argument the schema rejects is a bug** — every argument it names must exist in the tool schema.
`SKILL.md` points at the generated text rather than restating the contract — one prose source.

**A reader that finds `_state.md` stale or absent must still work:** every field has a live twin
(`/status`, `/inbox`, `/conversations/recent`, `cicada_repo_context`).

### sqlite-vec (vector index)
`api/services/vector_index.py`. Embeddings are **stored, not recomputed at query time**, so search
is one in-process ANN lookup. Default backend is EmbeddingGemma-300M (768-dim, on-device) with
asymmetric query/document prompts. The index is **derived and disposable** — rebuilt by Sleep from
markdown, safe to delete at any time.

### Telemetry ledger (`~/.cicada/telemetry/`)
Append-only JSONL, machine-global, **never in a bank or git**. `CICADA_TELEMETRY=off` disables it.
**IDs and enums only — never claim text, query text or answer text.** The `read` kind (G124) records
an entity id and a surface enum, filed in a sibling `reads-*.jsonl` that
`sync_service.components["telemetry"]` deliberately does not stat — the app maps that component onto
its consumption domain, so a card open must not move it.

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
`sleep/state`, `nudge/resolved`, `clarification/resolved`, `user/manual_edit`, `user/companion_app`.

**Three trailer families, all inert to entity-line parsing — extend them, don't break them:**

- **`Cicada-Author:`** — *which agent authored this*. A model id for agent writes, the literal
  **`user`** for manual/companion-app writes, **`unknown`** for legacy untrailered commits, and
  **`cicada`** for system maintenance with no model and no user in the loop (the one-shot
  migrations, the split-out decay commit, the `State snapshot` commit). Built by
  `git_service.build_commit_message(...)`, parsed by `_parse_authors`. Powers `GET /contributors`.
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

**Entity-level provenance uses `git blame`** enriched with parsed commit metadata; repo-level
history uses `git log`. **No changelog in frontmatter** — git handles all history, zero storage
overhead, no growing fields.

---

## MCP "Bookworm" Tool

The interface between any LLM and the memory system. On `initialize` the server returns the G75
handshake as `instructions`. On query: check `memory/inbox/` for relevant pending items → search the
vector index → search the markdown graph → follow wikilinks for relational depth → progressive
disclosure (cluster pages → entity pages → episodic sources).

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

**Navigation.** Six sidebar rows (⌘1–6): Graph, Clusters, Feed, Sleep, Inbox, Sources. Setup lives
in a native `Settings{}` scene (⌘,), a `NavigationSplitView` over five sections — General · Sleep ·
Integrations · Agents · Plans & keys (`SettingsSection`, replacing the earlier four-tab `TabView`).
⌘K opens the Ask panel. `AppTab` raw values are the persisted identity of a tab, and
`AppTab.restored(from:)` maps retired ones onto the pages that inherited them, so an older selection
never traps.

**Settings → Sleep: the engine picker (G122).** A segmented picker over the connections registry's
candidates (Claude plan, Ollama, a BYOK key; Codex stays permanently `available: false` — G49's
half of the ladder) writes `PUT /sleep/engine`, which lands in the same bank-independent
`~/.cicada/connections.json` prefs `use_for_sleep` already uses, never `api/.env`. The card shows
both `preview.manual` and `preview.scheduled` lines rather than hiding **ruling 4** (a scheduled
cycle never spends plan quota) — the asymmetry stays visible, not silently applied.

**Settings → Integrations (G126).** A categorized, logo-first page over the existing
`GET /sources/channels` registry — no new adapters, just a frame. The rule this page draws: a
*standing* connection (sign in once, polled on the Sleep tail, disconnect here) lives in
Integrations; a *one-shot* import (drop an export, sync a folder once) stays where it already was,
behind the Feed's `+`. Both read the same `channel_registry`, so a channel never drifts between the
two surfaces.

**Sleep page — the study desk (G125).** The bookworm sits at a desk: a speech bubble
(`sleepBubbleText`, clock-free per R8 — the line is a pure function of state and counts, never the
wall clock, so it can't flicker between renders) above a book pile (`bookPileLayout`) whose spine
heights encode queued characters per source on a log scale — the page's one volume encoding (R1: no
bars-per-source, no tiles, no age histogram). Below it, `StudyListCard` lists what's waiting one row
per origin, largest pile first, each disclosing to its queued episodes inline, with the single
Consolidate/Cancel control in its footer (R10 — the old top-right Sleep/Upload pair left the page).
`ConsolidationHistoryCard` renders past cycles from `GET /sleep/history` (commit bodies parsed
server-side, bounded and cached — R4) and expands a row on demand into `GET /sleep/history/{commit}`
(cached per commit in the view model, R12); a cycle's duration is joined from the `sleep_run`
telemetry ledger by commit hash and reads "—", never a guess, when telemetry was off or the row is
missing (R5). `?` opens *How Cicada sleeps* — the five-stage batch in plain language, one prose
source with the "Core Architecture" section above.

**Mascot states (G107).** `BookwormState` gained `reading` for this page only —
`deriveSleepPageMood` returns it where the menu bar's `deriveBookwormState` returns `.curious`, and
the menu bar's own precedence and sprite meaning are unchanged. `store.intakeInFlight` (set while
the upload overlay runs) forces `reading` ahead of `happy`/`hungry` but never ahead of
`sleeping`/`error`/`digesting`. Per-cycle duration *estimates* stay deferred (G107's own ruling);
only a measured, telemetry-joined duration is ever shown.

**View menu (G130 slice 1a).** ⌘+ / ⌘− / ⌘0 scale the whole chrome — one persisted `uiScale` behind
every `CicadaTheme` font and spacing token, so every reader repaints with no `.id()` anywhere (the
PR #49 lesson repeated). The graph canvas keeps its own zoom; ⌘+/⌘− means chrome, not canvas, same
as a browser's page zoom vs. a map widget's. `Settings` gains a *General* tab (Appearance + a Text
size slider) alongside Agents, Plans & keys and Schedule. Slice 1b (PR #58) finished the job:
every literal `.font(.system(size:))` / `Font.system(size:)` in `Sources/` now goes through
`CicadaTheme.font(size:...)`, and `FontLiteralLintTests` fails the build on a new one.

---

## API Design

20 routers mounted in `api/main.py`, plus repo-context and maintenance endpoints. **Read the routers
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
`.inbox`; change one half, change both.

**Endpoint traps worth knowing before you touch them:**

- `GET /entities/{id}/history/{commit}/diff` — a file's FIRST commit has no parent, so `git show`
  diffs it against the empty tree and it comes back all-adds; a MERGE commit needs `--first-parent`,
  else git emits a combined (`--cc`) `@@@` diff the parser can't read and the endpoint silently
  returns nothing. `truncated` is the UNION of three caps; `linesTruncated` specifically means "the
  ordered list was cut" and is what a client renders its banner on.
- `GET /conversations/recent` is **CAPPED** (limit ≤ 200) and is never a membership test; filters
  apply BEFORE the cap. Use `GET /conversations/{id}` to resolve one id against the whole bank.
- `POST /conversations/{id}/resume` returns a validated descriptor — **transcripts are never read,
  `isfile()` only**.
- `POST /maintenance/enrich-links` returns `409` both while a Sleep cycle runs and while another
  call is still running (a process-local lock — two overlapping clicks would stage each other's
  half-written pages under their own trailers).
- `GET /sync/version` is the cheap change-detector (<10 ms); `GET /sync/events` is the SSE stream.

---

## Features

### 1. Graph Explorer
Force-directed d3 graph: node color by type, size by confidence, edge labels, cluster detection,
decay/clarification indicators. Open ideas live in the backlog.

### 2/3. Unified inbox (`memory/inbox/`)
Nudges and clarifications live in **one store**: `memory/inbox/inbox-NNN.md`, each with a `kind`
discriminator (`decay`, `conflict`, `clarification`, `merge_suggestion`, `divergence`,
`normalization` — the last two were written by Sleep since G49/G98 but only became loadable and
resolvable kinds with G113), behind `GET /inbox` /
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

**Cause (G115 Phase 1, delivers G97).** Every item carries its `cause` — episode, timestamp,
conversation, harness, excerpt, offsets — resolved **at read** by `api/services/inbox_context.py` in
three tiers (item → claim → entity), engine-free. The excerpt is ±240 chars around the mention, cut
on word boundaries, **offsets recomputed on every read and never stored**. Nothing resolves →
`tier: none` and a literal `[ no source recorded ]`, served — never a hidden card.

**Decay is no longer the special case.** Served as `Still tracking {name}?` with `archive` / `keep`,
synthesised at read from the page's `last_referenced`, never written. Its question sets
`allow_other: false` and **the whole stack now means it**: free text on resolve is a `400`.

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
scheduled cycle never spends plan quota (the standing ruling in `TODO.md`).

### 5. Conversation upload
File picker for JSON/HTML exports; parses and stages into `episodes/`; dedups on timestamp +
content hash.

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

- **`CICADA_ALLOW_CONNECTOR_FETCH`** gates ONLY the unattended nightly connector poll's default
  transport. It is **opt-OUT** (on by default; `=off` disables it, which is what the test suite
  sets). A user-initiated `sync_now` and every OAuth `authorize_url`/`exchange_code` call are
  **never** gated by it — they always need the network to do what the user just asked.
- **`CICADA_ALLOW_FEED_FETCH`** gates RSS/ICS polling and is **opt-IN** (`=1`). A fresh install's
  LaunchAgent plist sets it; `install.sh` never rewrites a plist behind a running backend, so an
  older plist needs the key added by hand.
- **`CICADA_ALLOW_LOGO_FETCH=off`** disables logo fetching entirely. The test suite runs that way
  and injects fetchers instead.

**A failed poll is recorded, not raised** (`sync_state.record_error`) and surfaces per-channel as
`lastError`; a gate-skipped poll is recorded distinctly (`record_skip`) so a skip never reads as a
failure or as a stale success.

**The ToS rail — this one is not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never
behind auth. Consent interstitials and login walls are classified and retired as `junk` **without a
byte fetched**. **A block is never retried with different headers.** No scraping behind
authentication, ever.

**Credentials** live in `~/.cicada/secrets.env` (0600) — **never in a bank, never logged**. The
shared `base.forget()` removes them on disconnect, so a fields-vs-stored drift can't orphan a
secret. Where a vendor bills per request (X's "owned reads"), the sync result carries the count so a
cost is stated plainly rather than hidden behind a "connected" checkbox.

---

## Installation & Setup

`install.sh` is the source of truth; the paste-prompt install story is G76 in the backlog.
