# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project

**Cicada** — Author: Rodrigo Sagastegui.

Cicada started as a BSc capstone thesis at IE University — *A Cognitive Agent Architecture for
Personal Knowledge Evolution via Structured Memory Consolidation* — and has since evolved into a
personal project with a larger goal: **capture the human experience seamlessly, and make it
something you can hold a conversation over — with agents that can understand it, contribute to it,
and draw their own relations across it.**

Concretely, that means Cicada aims to span:

- **Every kind of media ingestion** — links, articles, papers, videos, images, bookmarks, RSS,
  files, saved collections exported from the platforms where they pile up.
- **Every conversation** — the ones with agents (MCP-native clients, plus imported ChatGPT/Claude
  exports), and, as recording becomes part of the workflow, **conversations with other people**:
  meetings ingested the same way, through the same source-agnostic pipeline.
- **The moving parts of a life** — projects, ideas, current interests, the things being decided and
  the things quietly going stale.

The design principle that follows from that goal: memory must be **legible to an agent without
ceremony**. An agent should be able to arrive, be told what Cicada is and how to use it, read the
graph, contribute beliefs with provenance, and leave the store better than it found it. The
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
with actions and observations grounded in an environment, rewards grounded in that environment
(the human being part of it), and reasoning that is not confined to human terms. Cicada's reading:
**the person's life is the environment, and Cicada is the instrument that turns it into a stream an
agent can inhabit.** Four correspondences, each a design constraint:

1. **Streams, not sessions.** A conversation is a snippet; a life is a stream. Awake capture is the
   stream's intake, Sleep is what makes it more than a transcript pile, and decay is the stream's
   own clock — silence is data. Anything that fragments the stream (a resumed conversation
   consolidated twice, G104; capture that depends on a model choosing to call a tool, G105) is a
   defect against this, not a nicety.
2. **Observations *and* actions.** Every capture channel is an observation. Every agent write with
   provenance — a claim, a `Cicada-Author:` trailer, an inbox resolution — is an action on the
   shared record. The port is two-way or it is a diary.
3. **Grounded rewards.** When the person answers a nudge, overrules a claim, keeps or archives an
   entity, that is a reward signal *from the environment*, not a prejudgement of the agent's
   output. Cicada should treat these resolutions as the signal it learns from, not just as edits to
   apply (G113).
4. **Reasoning beyond prose.** The claim layer — typed predicates, bi-temporal validity, observer
   and trust — exists so an agent can reason over the record structurally. Prose is for humans;
   claims are the machine-legible half.

**Tang et al., *WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill
Evolution* (2026, arXiv:2608.27454).** Their result: separating *raw experience* from a
*persistent wiki* from *executable skills* is what makes skill evolution work (the wiki is worth
+15 points to the skill proposer in ablation), and evolved skills **transfer across models and
model families** — a skill evolved by a stronger model can beat one the target model evolved for
itself. Cicada already holds the first two layers: `episodes/` is the raw layer and the
entity-plus-claim graph, with its provenance trailers, is the wiki. The third layer — compiling what
the graph knows about *how this person works* into portable, agent-loadable skills — is **G112**.
The bar it sets: **a skill compiled from one person's experience should load into any harness on
any plan, with Cicada being nothing more than its provenance.**

**Portability is the point, not a feature.** The goal is other people running this on their own
plans and harnesses (G50 connections, G76 install, G92 onboarding). A hardcoded owner name, a path
that only exists on the author's machine, a bank that cannot be handed over intact — each is a bug
against the mission, not a polish item.

## Branches

- `main`: production/stable branch
- `dev`: active development branch — all work goes here first

PRs open against `dev`. Promotion to `main` is a manual, deliberate step — never a PR target.

---

## Backlog and handoff (`docs/goals/`)

Two files, one split: **why** something is worth doing lives apart from **what to do next**.
Read both before proposing work; a proposal that duplicates a `G` row or re-opens a settled
ruling is wasted effort.

**[`docs/goals/memory-evolution.md`](docs/goals/memory-evolution.md) — the backlog (reference).**
One row per idea, `G<n>`, numbered in the order it was raised and never renumbered — a `G` id is
a permanent address, so cite `G74a` in commits, PR bodies, and specs the way you would cite a
ticket. A row carries the *reasoning*: the problem, the evidence for it (file:line, a measured
number, a reproduction), and the design constraint any fix must respect. Rows are triaged
**APPLY** / **RESEARCH** / **DECIDE**, and the 💸 flag marks anything needing paid LLM spend.
When you learn something that changes a row's argument, edit the row — do not open a second one.

**[`docs/goals/TODO.md`](docs/goals/TODO.md) — the execution view + handoff.** Same work,
ordered by what to do next: Shipped / In progress / Next / To close / Known-broken. Its header
is a **handoff document written for an agent picking the project up cold** — current state,
open PRs, the verified live environment (how the backend runs, where secrets live, which bank is
active, the one correct way to launch the app), the working agreements, and a "Pick up here"
line. Above all it carries the **rulings**: decisions that cost real measurement to reach, each
with the evidence that settled it. Treat a ruling as binding. Revisit one only on the trigger its
row names, and only after reading why it was made — several were reached by disproving the
obvious answer, so re-deriving them from first principles reliably gets them wrong.

Keep the split honest: **add detail to the backlog, track state in TODO.md.** After finishing
work, update both — mark the `G` row done and move its TODO entry to Shipped — and refresh the
handoff header if anything it asserts about the environment or the in-flight PRs has changed. A
handoff header that is stale is worse than none, because it is trusted.

---

## Repository Structure

`api/` FastAPI backend, `app/` SwiftUI macOS app, `mcp/` the MCP server, `memory/` the runtime
bank (gitignored), `benchmarks/` thesis tooling, `docs/goals/` the backlog. Read the tree with
`ls` — it is not duplicated here.

## Core Architecture: Awake/Sleep

### Awake Cycle
Continuous episode capture during conversations. Raw timestamped chunks go to `episodes/` inbox. **No LLM processing at capture time** — just logging. This is cheap (just file I/O).

**Input sources:**
- **MCP-native clients** (Claude Code, Cursor): Cicada MCP server is directly in the conversation loop. Episodes captured automatically. This is the primary deployment model.
- **Export-based ingestion** (ChatGPT, Claude Desktop/iOS): Periodic import from conversation exports (`/banks/{name}/import`). ChatGPT and Claude both give JSON/HTML exports parsed by dedicated import parsers.
- **Telegram bot** (`/save`, `/note`, `/remind`): On-the-go capture of links, voice notes, text snippets, via `POST /capture/telegram`. `/save <url> <reason…>` also captures *why* — see Save-with-reason (G71) below.
- **Ingested sources**: Safari bookmarks, saved links, RSS feeds, PDFs, repos. Indexed in the sqlite-vec vector index for semantic retrieval.
- **Direct saved-content connectors** (G71): **Pinterest** (v5, BYO OAuth app, `boards:read`/`pins:read`
  — board name becomes the item folder), **Reddit** (script app, `/user/{me}/saved`, newest-first to
  the previously-seen fullname; the GDPR `saved_posts.csv` export backfills past the ~1,000-item listing
  cap), and **X/Twitter** (OAuth 2.0 + PKCE, `/2/users/:id/bookmarks`, pay-per-use "owned reads" billing
  — the sync summary surfaces `resources_read` so a cost is never hidden behind a plain "connected"
  checkbox). Credentials live in `~/.cicada/secrets.env` (0600), never in a bank. Polled at the tail of
  every Sleep cycle — after `_finalize`'s own commit, so the poll's `git add -A` sweeps only its own
  files instead of the cycle's still-uncommitted entity writes (G71 final review H1) — including an idle
  cycle, and on demand via `POST /sources/connectors/{id}/sync`. `CICADA_ALLOW_CONNECTOR_FETCH` gates
  ONLY that unattended nightly poll's default transport — opt-OUT (on by default, mirroring
  `CICADA_ALLOW_LOGO_FETCH`; `=off` disables it, which is what the test suite sets). A user-initiated
  `sync_now` and every OAuth `authorize_url`/`exchange_code` call are never gated by it — they always
  need the network to do what the user just asked (G71 final review H2). A failed poll is recorded
  per-channel (`sync_state.record_error`) and surfaces on `GET /sources/channels` as `lastError`; a
  gate-skipped poll is recorded too (`sync_state.record_skip`) and surfaces as a skip, distinctly from
  both a failure and a stale success.
- **Export parsers** (`media_ingestor.parse_upload`): Instagram saved, YouTube playlist export, Google
  Takeout (JSON/CSV/zip), Chrome/Safari bookmarks, **LinkedIn saved items** (URL + date only — post bodies
  are deliberately never fetched, so these stay thin, `origin: linkedin-saved`), **TikTok favourites/likes**
  (`origin: tiktok-saved`; Browsing History is opt-in via `?include_history=true` and keeps a distinct
  `tiktok-history` origin), and the **Reddit GDPR export** (`origin: reddit-saved`). Non-Takeout archives
  must be unzipped first — the app's step-path copy says so and the preview reports it.
  `POST /sources/upload?preview=true` runs the identical sniff/parse but stages nothing, returning a
  per-collection item breakdown so the import overlay can show what it's about to import before Confirm.

**Episode tracking (G114):** Each episode has a unique ID (`ep_YYYY-MM-DD_NNN`), a timestamp, and a `processed: false` flag. Every writer — importer, MCP, media, Telegram, calendar, notes — mints the id through the one rule in `api/services/episode_ids.py`: `next_episode_id` is max-suffix+1 per date (a count-based rule collides after any gap, and `markdown_parser.write` overwrites on collision), and stamps the timestamp as aware UTC from `episode_ids.utc_now_iso` (`+00:00` — never a naive local time with a `Z` appended). Legacy files are not migrated: readers accept both shapes and the Sleep queue sorts by `episode_ids.timestamp_sort_key`, so the mix still orders by instant. A Telegram episode is stamped with the message's own `date`, not receipt time. When an episode is marked processed it also carries `processed_by`: `sleep` for a Sleep cycle, `agent` (or the harness name) for `cicada_mark_processed`, so a flipped flag is distinguishable from a consolidation. Sleep cycle processes all unprocessed episodes regardless of source — the pipeline is source-agnostic. Its engine-independent tail also polls subscribed RSS feeds and ICS calendars, opt-in via `CICADA_ALLOW_FEED_FETCH=1` (a fresh install's LaunchAgent plist sets it — `install.sh` never rewrites a plist behind an already-running backend, so an older plist needs the key added by hand, see TODO.md's Live environment; the test suite never does), in the same clean-tree-guarded slot as the connector poll.

**Conversation identity (G48).** An episode captured through MCP also carries `session_id`
(the client conversation), plus `harness` and `project_dir` when the client exposes them —
minted once per MCP process from `CLAUDE_CODE_SESSION_ID` → `CICADA_SESSION_ID` → a
`ses_YYYY-MM-DD_xxxxxxxx` fallback that groups but never resumes. Entities credit to
conversations transitively via `source_episodes`, exactly as they do for `origin`.
**Transcripts under `~/.claude/` are never read** — the only contact is an `isfile()` check
answering "is this session still resumable", computed per request and never persisted.
A conversation row's `model` is **reserved — always null**, and will be populated once engine
calls carry session refs (G49); nothing that writes memory records a model against a
conversation id today, so the row states that rather than joining a ledger that can't answer.

### Sleep Cycle (5-Stage Nightly Batch Pipeline)
Triggered by cron or manual command:

1. **Entity & Relationship Extraction**: LLM processes episode chunks with structured extraction prompts. Outputs typed entities and relationships as JSON.
2. **Entity Resolution & Deduplication**: Reconciles against existing graph via fuzzy matching, embedding similarity, LLM disambiguation. "Mongo" → "MongoDB", "the project" → which project?
3. **Conflict Resolution & Pruning**: Detects contradictions ("switched from Postgres to SQLite"). Recency wins, old state archived in version history. Temporal decay: absence of mention triggers confidence drop.
4. **Pattern Detection & Skill Extraction**: Scans for recurring interaction patterns across cycles. Distills into procedural skills (preferences, routines, workflows) stored as skill-type entities.
5. **Nudge Generation, Clarification Queue & Versioning**: Generates three nudge types (decay, conflict, clarification). Creates versioned snapshot. Commits to git.

### Entity Promotion Model
Entities are NOT extracted upfront from every mention. The promotion model avoids graph pollution:
1. First mention → raw chunk stays in the sqlite-vec index only
2. Second mention across a different conversation → Sleep cycle notices recurrence
3. Promotion threshold met → create entity page with backfilled context

Thresholds: referenced in 2+ separate conversations, OR discussed substantively (>3 exchanges) in a single conversation, OR explicitly linked to an existing high-confidence entity.

### Temporal Decay
Absence of mention IS a signal. If you talked about Salesforce daily for a week then stopped for two weeks, that silence is informative.
- Every entity has `last_referenced` and `decay_rate` in frontmatter
- Sleep drops confidence for unreferenced entities proportional to how frequently they USED to be referenced
- Below archive threshold (0.2): entity moves to `archive/`
- Below nudge threshold (0.4): generates decay nudge
- If mentioned again: promoted back with `confidence = max(current, 0.6)` (recovery promotion, see Decay classes)
- Evergreen entities (media/bookmarks, user-pinned) skip all decay math and decay nudges

---

## Storage Layer

### Structured Markdown Folder (Knowledge Graph)
Wikilinked `.md` files with YAML frontmatter. LLM reads and writes. Git-versioned. Zero infrastructure — just a folder.

**Why markdown over Neo4j:** At personal scale (hundreds of entities, not millions), the LLM can read markdown and follow wikilinks — it doesn't need Cypher. Zero infrastructure, human-readable, git-versioned, portable, Obsidian-compatible.

### Entity Schema
Every entity page uses this YAML frontmatter:

```yaml
---
type: person | project | company | concept | tool | deadline | skill | location | media | directory
status: active | decaying | archived | dropped
confidence: 0.85          # 0.0–1.0
created: 2026-01-10
last_referenced: 2026-03-22
decay_rate: 0.05           # per-entity, not global
decay_class: active        # evergreen | durable | active | volatile (G66)
source_episodes:
  - ep_2026-01-10_001
  - ep_2026-03-22_002
tags:                       # open set, freeform labels for cross-cutting concerns
  - career
  - robotics
related:                    # duplicates wikilinks for programmatic access
  - Recruiting
  - Career Planning
version: 3
---
```

**Entity types (closed set of 10, `api/models/schemas.py::EntityType`):**

| Type | Description | Examples |
|------|-------------|---------|
| `person` | Named individual | supervisor, teammate, recruiter |
| `project` | Active or past work | capstone, startup prototype, side project |
| `company` | Organization | university partner, internship host, startup |
| `concept` | Idea, topic, knowledge area | Knowledge Graphs, Context Engineering |
| `tool` | Technology, framework, software | sqlite-vec, EmbeddingGemma, FastAPI |
| `deadline` | Time-bound commitment | final submission deadline |
| `skill` | Procedural memory, preferences | "Prefers concise summaries" |
| `location` | Place | home city, conference city |
| `media` | Ingested image/video/audio with agent-generated summary | saved video, image mood-board item |
| `directory` | A filesystem folder/path, split out from `location` (G18) | `~/Documents/roros_lab/cicada` |

**Note (G17):** `deadline` is still a valid, renderable type (legacy pages keep working) but is **no longer produced by Stage-1 extraction** — `PRODUCIBLE_ENTITY_TYPES` in `schemas.py` excludes it; due-dates are attached as a `due` claim/relationship on the relevant project instead of spawning a standalone deadline entity. `media` is likewise excluded from Stage-1's producible set — it's produced by the media-ingestion path, not conversation extraction.

**Status lifecycle:** `active` → `decaying` → `archived` → `dropped` (user-dismissed, never resurfaced)

### Decay classes (G66)
Every entity carries a semantic `decay_class:` beside the numeric `decay_rate:`,
resolved by the one resolver `api/services/decay_policy.py`:

| Class | Entity rate/wk | Claim multiplier | Meaning |
|---|---|---|---|
| `evergreen` | 0.0 | 0.0 | Never fades. Artifacts (media/bookmarks) + anything the user pins. |
| `durable` | 0.02 | 0.5 | Fades slowly. Stable preferences, skills, long-lived concepts. |
| `active` | 0.05 | 1.0 | The default for a belief about the user's life. |
| `volatile` | 0.15 | 2.0 | Expected to change within weeks (role, status, current focus). |

`decay_policy.resolve(fm)` returns `(class, rate)`: an explicit `decay_class:`
wins; otherwise the class is inferred from `type` (`media` → evergreen, `skill`
→ durable, everything else → active) so legacy pages keep working untouched. An
explicit numeric `decay_rate:` that differs from the class map still wins for
the three decaying classes (the class stays as the label); `evergreen` pins its
rate to `0.0` unconditionally.

**Anti-pollution rail (mirrors `PRODUCIBLE_ENTITY_TYPES`):** Stage-1 extraction
may PROPOSE `durable|active|volatile` and **never `evergreen`**
(`AGENT_PRODUCIBLE_DECAY_CLASSES` in `schemas.py`, enforced by
`decay_policy.agent_class` at extraction AND again in the create branch).
Evergreen is reserved for the ingest writers and the user, so an over-eager
extractor can never stop the graph from archiving.

**Both engines honor it.** The entity engine
(`conflict_resolver.resolve_and_prune`) takes its rate from the resolver and
skips evergreen entities outright — no decay math, no decay nudge, never
auto-archived, so a bookmark can no longer generate a "still interested?"
question. The claim engine (`claim_reconciler._decay_claims`) multiplies its
per-epistemic × source_trust rate by the SUBJECT's class multiplier, supplied by
an injected `decay_class_fn` (default: `decay_policy.class_lookup(memory_path)`).

**Recovery.** A `decaying`/`archived` entity mentioned again is promoted back to
`active` with `confidence = max(current, 0.6)` — the counter-signal half of
"time as a signal", promised in this file long before it existed. `dropped` is
never resurrected.

**Migration.** `api/services/decay_migration.backfill_decay_classes` runs once
per bank (marker `.decay_classed`, author `cicada`, trigger
`maintenance/decay_class_backfill`): media → evergreen/0.0 with any
wrongly-faded page restored to `active` at confidence ≥ 0.7, skills → durable.
Its commit names **exactly the pages it rewrote** — never a `entities/`
directory pathspec — so a pre-existing dirty edit or a concurrent Sleep write is
never mis-attributed to `cicada`. It runs from
`api/services/bank_migrations.run_bank_migrations`, the shared set of one-shot
per-bank migrations (this plus the two inbox ones) invoked both from API startup
for the boot-time bank and from `POST /banks/{name}/activate` for a bank
switched to at runtime.

### Repo links
Project/directory entities may carry an optional `repos:` frontmatter key linking them to local git checkouts:

```yaml
repos:
  - path: ~/Documents/roros_lab/cicada        # tilde-style declared path
    device: rorosaga-mbp                       # optional
    remote: git@github.com:rorosaga/cicada.git # optional
    default_branch: main                       # optional declared hint
    worktrees:                                 # optional declared list
      - path: ~/Documents/roros_lab/cicada
        branch: feat/memory-evolution
        primary: true
```

`GET /entities/{id}/repos` and `PATCH /entities/{id}/repos` read/write only this key. The live git context (current branch, ahead/behind, dirty files, worktree state) is resolved **on demand, never cached** — the entity page only ever declares which repos it's linked to; `git_service` shells out fresh on every call to answer "what's the state of this repo right now." Surfaced in the graph as a synthetic `repo:<slug>` node per distinct path, and via the `cicada_repo_context` MCP tool.

### Fact sources (G61)
Entity pages may carry an optional `sources:` frontmatter key — *where to look a fact up*,
distinct from `source_episodes` (where a belief came from) and from the body's `## Links`:

```yaml
sources:
  - ref: https://www.linkedin.com/in/rodrigosagastegui
    kind: url            # url | path | note (inferred from `ref` when not given)
    predicate: works-at  # optional — which fact this source refreshes
    added_by: user       # model id, or "user"
    added_at: '2026-08-30'
```

Read/written by `api/services/fact_sources.py` behind `GET/POST/DELETE /entities/{id}/sources`
(note: `api/services/entity_sources.py` is a *different* module — it resolves an entity's episodes
back to whole conversations). `cicada_write_claim` accepts `sources: [str]`, attributed to the
model that wrote the claim. Conflict generation consults them: a matching source becomes the
card's "Source to check" hint. Nothing is fetched in this slice.

### Save-with-reason (G71)
A Telegram `/save <url> <reason…>` writes the reason twice: verbatim as a
`## Saved because` section on the media episode (so Stage-1 extraction mines its
concepts exactly as it would conversation text), and as a `saved-because` claim on
the media entity — `observer: rodrigo`, `source_trust: user_stated`,
`object_kind: literal`, `origin: telegram`. `literal` keeps it out of the graph:
Stage 5.7 projects only node-object claims into edges. `telegram` is deliberately
**not** in `claim_reconciler.is_human`'s manual-assertion channel set, so the claim
reads as user-stated without inheriting manual-edit overwrite protection — a bot
webhook is not an authenticated manual-assertion channel. `agentic_write.write_claim`
gained an optional `origin=` for exactly this; omitting it is unchanged (falls back
to `manual_edit` for `observer="rodrigo"`, else `mcp`).

### Connector seam (G71)
Pinterest, Reddit, and X (Twitter) each get a peer adapter module under
`api/services/connectors/` — not one bespoke integration per platform, but a
documented module-as-adapter contract (the required surface is spelled out in
`api/services/connectors/__init__.py`'s docstring: `CHANNEL_ID`, `LABEL`,
`FIELDS`, `LOGIN_MODE`, `CHANNEL_NOUN`, `SECRET_NAMES`, `is_connected()`,
`credential_fields()`, `forget()`, `sync()`, plus `authorize_url()` /
`exchange_code()` for an OAuth adapter). `ADAPTERS` — keyed by `CHANNEL_ID` — is
the single roster every consumer (the `connectors` router, `channel_registry`'s
`CHANNEL_IDS` splice, and the Sleep-tail poll) iterates instead of re-declaring
its own copy of "which connectors exist." `base.run_sync` is the shared driver
every adapter's `sync()` delegates to: the not-connected skip, the
`CICADA_ALLOW_CONNECTOR_FETCH` background-fetch gate (opt-OUT, on by default —
gates only an unattended Sleep-tail poll, never a user-initiated `sync_now`/OAuth
call), the try/except that turns any failure into a recorded-not-raised error
(`sync_state.record_error`; a gate-skipped poll is recorded distinctly via
`sync_state.record_skip`), and the `media_ingestor.ingest_batch` call
(chunked in `MAX_BATCH`-sized slices so a >2,000-item pull is never silently
truncated) all live there once. Credentials are stored under `SECRET_NAMES` in
`~/.cicada/secrets.env` (0600) and removed by the shared `base.forget()`, so a
FIELDS-vs-what's-actually-stored drift can never orphan a secret on disconnect.
A credential save, a disconnect, and a completed OAuth exchange all call
`sync_state.record_credentials_changed` so the `sources` SSE component ticks
even though the change itself landed outside `memory_path`. X is billed
pay-per-use ("owned reads" at ~$0.001/read, no subscription tier) — its sync
result carries an additional `resources_read` count so the cost is stated
plainly rather than hidden behind a plain "connected" checkbox.

### sqlite-vec (Vector Index)
Lightweight on-device semantic search (`api/services/vector_index.py`, replaces the earlier LEANN wrapper — `leann_indexer.py` has been deleted). Embeddings are stored, not recomputed at query time, so search is a single in-process ANN lookup with no latency tax. Default backend is **EmbeddingGemma-300M** (768-dim, on-device, gated HF model) with asymmetric query/document embedding prompts; the index is *derived and disposable* — rebuilt from entity/episode markdown by the Sleep cycle, and can be deleted and regenerated at any time. Runs locally, zero cloud costs for the default backend.

### Telemetry ledger (`~/.cicada/telemetry/`)
Append-only JSONL under `~/.cicada/telemetry/events-YYYY-MM.jsonl` (machine-global, never in a bank or git), fed by `providers.resolve_llm_fn` (every LLM call is now routed through it), Sleep `_finalize`, and MCP `cicada_write_claim`. `CICADA_TELEMETRY=off` disables recording.

### Entity logos (`~/.cicada/logos/<bank>/`)
`api/services/logo_service.py` resolves an entity page to a domain (explicit
`logo:` frontmatter → a `url`-kind `sources:` entry → the first `## Links` URL →
`media.url` → a `website` claim or a single-token-name `.com` guess, and never
for a `person`), fetches an icon keylessly (`apple-touch-icon` → the homepage's
`<link rel=icon>` → DuckDuckGo's icon service, 4 s, ≤ 512 KB, ≥ 16 px), and
caches the result — hits for 30 days, misses for 7 — under
`$CICADA_HOME/logos/<bank>/` with a `meta.json` index. **Never inside a bank:**
a logo is a derived artifact of the outside world, not versioned memory.
`GET /entities/{id}/logo` serves it (first request fetches, bounded by a
semaphore of 4); `GET /graph` only reads the index to set `has_logo` and never
touches the network. `CICADA_ALLOW_LOGO_FETCH=off` disables fetching entirely —
the test suite runs that way and injects fetchers instead.

### Git (Versioning & Provenance)
Every Sleep cycle commits with **structured commit messages** for machine-parseable provenance:

```
Sleep cycle 2026-03-20

entities/recruiting-thread.md: updated (source: ep_2026-03-20_002, trigger: sleep/extraction)
entities/recruiter-contact.md: created (source: ep_2026-03-20_002, trigger: clarification/resolved)
nudges/nudge_005.md: resolved (trigger: user/companion_app)

Cicada-Author: gpt-5.4-mini
Cicada-Author: gpt-5.4-nano
```

**Trigger types:** `sleep/extraction`, `sleep/promotion`, `sleep/conflict_resolution`, `sleep/decay`, `nudge/resolved`, `clarification/resolved`, `user/manual_edit`, `user/companion_app`

**Commit-author trailers (`Cicada-Author:`).** Every Cicada write records *which agent
authored it* as one or more `Cicada-Author:` git trailers appended after a blank line at the
end of the commit body. The value is a **model id** (e.g. `gpt-5.4-mini`; the Stage-2
disambiguation model is recorded too when distinct) for sleep-cycle/agent writes, or the
literal **`user`** for manual/companion-app/media-save writes; legacy untrailered commits
are attributed to **`unknown`**. A third literal, **`cicada`**, is reserved for *system
maintenance* writes the system performs on its own behalf with no model and no user in the
loop — the one-shot inbox dedup migration (`inbox_migration._commit_dedup`, trigger
`inbox/dedup`), the one-shot decay-class backfill (`decay_migration.backfill_decay_classes`),
and, every Sleep cycle, the split-out decay-only commit (G85, below). It classifies as an
author like any other, so it shows up in
`GET /contributors` as a distinct, provider-less contributor. The trailer carries no entity id, so it is **inert to the
entity-line parsing** above — extend it, don't break it. Built by
`git_service.build_commit_message(subject, body_lines, authors=...)` and parsed by
`git_service._parse_authors`. This powers `GET /contributors` (repo-wide per-author
commit/file/entity counts + last-active) and the per-commit `author` field on
`GET /entities/{id}/history` — a memory system honest about which model authored each belief.

**G85 — decay changes get their own `cicada`-authored commit.** `conflict_resolver`'s
temporal-decay math (`trigger: sleep/decay` — the `archive`/`decay_nudge`/`decay` actions) runs
over EXISTING entities a Sleep cycle never referenced: no LLM call, no source episode, pure
confidence arithmetic. Folding it into the same commit as everything else stamped it with
whichever model happened to run Stage 1/2 that cycle, inflating that model's `GET /contributors`
counts for arithmetic it never touched. `sleep_cycle._finalize` now splits any `sleep/decay`
entity lines into their OWN commit — subject `Sleep cycle <date> (decay)`, `Cicada-Author: cicada`,
touching only the entity files those changes wrote — committed *before* the cycle's main commit so
the main commit's `git status` scan never sees them. Everything a decay change indirectly causes
(e.g. a `decay_nudge`'s own new inbox item) still rides in the main commit; only the
entity-frontmatter line itself moves. A decay change that can't be split out for any reason (its
entity file is missing on disk, or the split commit itself fails) degrades — folds back into the
main commit exactly as it would have before this fix — rather than aborting the whole cycle.
**Known asymmetry (disclosed, not fixed):** the split is path-granular, not hunk-granular —
`commit_paths` stages the whole entity file — so if Stage 5.56's claim write-back also touches that
same file this cycle (a subject can be claim-touched independently of `referenced_ids`), the whole
file, claim content included, lands in the `cicada` commit. This is the inverse of the bug being
fixed; narrow in practice (needs a subject to be both decay-eligible and claim-touched in the same
cycle) and accepted rather than fixed, since doing better needs hunk-level rather than file-level
staging.

**Commit-engine trailer (`Cicada-Engine:`).** A Sleep cycle's main commit also carries exactly one
`Cicada-Engine: claude-cli|ollama|litellm` line — which engine drove that cycle's extraction/
resolution/conflict/skills pipeline, mirroring `/sleep/status`'s `lastEngine` field into git history
so `GET /sleep/history` can report it too. Singular (a commit has one engine, unlike the
author/session lists) and omitted entirely — never a guessed value — when no LLM engine ran at all,
which is always true of the `cicada`-authored decay-only commit above. Built by
`git_service.build_commit_message(..., engine=...)`. Read back by `get_sleep_history` via git's own
`%(trailers:key=Cicada-Engine,valueonly,separator=)` pretty-format directive rather than a Python-side
parse of the full body (`%b`) — pulling the whole body just to extract one line grew the endpoint's
payload with the size of every commit message ever written (measured on the live bank: 787 B -> 378 KB
for 8 commits). Inert to entity-line parsing by the same contract as the other two trailers.

**Commit-session trailers (`Cicada-Session:`).** Alongside *which model* wrote a belief,
a Sleep commit records *which conversations* it consolidated: one `Cicada-Session: <id>`
line per distinct id, in the same trailer block, after the `Cicada-Author:` lines. The id
is a Claude Code session uuid (stamped at capture by the MCP seam) or G20's `source_id`
for an imported chat thread. Built by `git_service.build_commit_message(..., sessions=...)`
and parsed by `git_service._parse_sessions`; capped at `MAX_SESSION_TRAILERS` (50) by the
`sleep_cycle._finalize` call site, not by the builder. Inert to entity-line parsing by the
same contract as `Cicada-Author:` — it carries no entity id. Surfaced as `sessions` on
`GET /entities/{id}/history` entries and `GET /contributors/commits` rows. User-action
commits stay session-less: they are `Cicada-Author: user` writes with no conversation.

**Entity-level provenance** uses `git blame`:
- `git blame entities/recruiting-thread.md` → which commit wrote each current line
- Each commit's structured message provides: source episode, trigger type, timestamp
- The API enriches blame output with parsed commit metadata to produce a per-field timeline

**Repo-level history** uses `git log`:
- `git log` on the whole repo → chronological history of all Sleep cycles (for Sleep Cycle Dashboard)
- This is repo-wide, not per-entity

No changelog in frontmatter — git handles all history. Zero storage overhead, no growing fields.

---

## MCP "Bookworm" Tool
Interface between any LLM and the memory system. On query:
1. Checks `memory/inbox/` for relevant pending items
2. Searches the sqlite-vec index for semantically similar chunks
3. Searches markdown graph for structurally related entities
4. LLM follows wikilinks for relational depth
5. Progressive disclosure: cluster pages → entity pages → episodic sources

### Proactive Behaviors (Awake Phase)
When a new conversation starts, Bookworm checks:
1. **Pending nudges**: Surfaces relevant decay or conflict nudges based on conversation context (only topic-related, not all)
2. **Clarification queue**: If conversation touches an entity with a pending clarification, the agent asks naturally within the flow
3. **Related saved resources**: sqlite-vec search over ingested bookmarks, links, papers
4. **Relational inference**: LLM follows wikilinks across entity pages for deeper connections

---

## Companion App

### What It Is
The user-facing interface for inspecting, managing, and curating the knowledge graph. Makes the memory system observable rather than a black box. The user sees exactly what the agent "knows," corrects errors, resolves ambiguities, and manages entity lifecycles.

**The app is NOT the primary interaction surface** — that's the chat (via MCP). The app is the management layer.

### Technical Stack
- **Frontend**: Native macOS app in SwiftUI
- **Backend**: FastAPI (Python), running locally at `localhost:8000`
- **Graph rendering**: d3-force, embedded in a `WKWebView` inside the SwiftUI app

**Why d3-force:** Best ecosystem for node coloring, edge labels, zoom/pan, click handlers. More than sufficient for personal-scale graphs (hundreds of nodes). Obsidian uses Pixi.js for large scale — not a concern here.

### Communication Patterns
- **Backend↔SwiftUI**: Standard HTTP via `URLSession` / Swift `async`/`await`. Views backed by `@Observable` ViewModels that call FastAPI endpoints.
- **SwiftUI→d3**: `WKWebView.evaluateJavaScript()` to push graph data or trigger actions
- **d3→SwiftUI**: `window.webkit.messageHandlers.<handler>.postMessage()` for node tap events etc.

### Backend Process Management
SwiftUI app spawns the FastAPI server as a child process on launch using Swift's `Process()` API (`uvicorn api.main:app --port 8000`). User never manually starts the backend. On app quit, child process is terminated.

### Sync engine
A single `Store` holds one `Snapshot` per domain (graph, inbox, sources, channels, contributors, origins, status, banks, feeds, calendars, connections), hydrated instantly from a per-bank on-disk `SnapshotCache` (`~/Library/Application Support/Cicada/cache/<bank>/`) before the first network round-trip, so the app renders real data cold, even with the backend down. A `SyncEngine` holds one long-lived SSE connection to `GET /sync/events`, reconnecting with backoff and falling back to polling `GET /sync/version` while disconnected; each `version` event diffs against the last-seen vector and refreshes only the changed domains, every refresh sending `If-None-Match` so an unchanged domain costs a 304. View models are thin projections over `Store` snapshots (never blank — always the last-known-good data). Writes go through a `Mutation` protocol: optimistic apply to the local snapshot, rollback with a toast on failure. The graph view receives **deltas** (added/updated/removed node ids, each keyed by a `content_hash`) rather than a full re-layout, so d3 node positions are preserved across a Sleep cycle or a live edit. The sidebar is six rows — Graph, Clusters, Feed, Sleep, Inbox, Activity — reachable via ⌘1–6 (with matching accessibility labels); Feed carries the capture channels and the `+`/⌘N add-source sheet, Sleep carries the episode queue, and Activity merges consumption and contributor attribution behind a segmented control with the origins strip. Setup lives in a native `Settings{}` scene (⌘, or the sidebar's footer gear, which dots when a subscription login expires) holding Agents and Plans & keys. `AppTab` raw values are the persisted identity of a tab, and `AppTab.restored(from:)` maps the five retired ones (`Capture`, `Contributors`, `Usage`, `Connections`, `Connect`) onto the pages that inherited them, so an older selection never traps. Entity logos are cached on disk, and ⌘K opens an Ask panel (G52) that sends a question to `POST /ask` and renders the answer with clickable wikilink citations. Feed's `+`/⌘N sheet (G71) is now a two-level Imports catalog: platform tiles wearing brand logos route either to a `ConnectorSetupPanel` (Connect — Pinterest, Reddit, X) or an export-drop overlay (Import file), both reading live channel state and a real-time `?preview=true` parse preview before the user commits to an import.

---

## API Design

Grew past "one endpoint per screen" as the companion app matured. 20 routers currently mounted
in `api/main.py` (`graph`, `search`, `ask`, `inbox`, `status`, `nudges`, `clarifications`,
`entities`, `claims`, `contributors`, `origins`, `sleep`, `conversations`, `sources`, `banks`,
`local_refs`, `capture`, `connectors`, `connections`, `sync`), plus repo-context and maintenance endpoints:

Every endpoint except `GET /healthz`, `POST /capture/telegram`, and `GET /sources/connectors/{id}/callback`
for an OAuth adapter (Pinterest and X today; Reddit is credentials-only and has no callback route) requires
`Authorization: Bearer <token>` — the token lives at `~/.cicada/api_token` (`CICADA_API_TOKEN` overrides;
`CICADA_API_AUTH=off` for tests). The Telegram webhook is exempt because Telegram's servers cannot send the
header; today it is gated only by Telegram being configured (`CICADA_TELEGRAM_BOT_TOKEN`), not by a
per-request secret — see G57. Each OAuth callback lands in the user's own browser, which likewise cannot
send the header, so it is gated instead by its own single-use, 10-minute `state` nonce minted by
`POST /sources/connectors/{id}/authorize` (`api/services/auth.py::_is_oauth_callback_path` resolves the
exemption live against the connectors registry rather than hardcoding one literal per adapter).

`/graph`, `/inbox`, `/contributors`, `/sources`, `/sources/channels`, `/origins`, and `/banks` all support ETags: each response carries an `ETag` header, and a request sent with `If-None-Match` gets back a `304 Not Modified` (empty body) whenever nothing in that domain changed, letting the app skip re-parsing and re-rendering large payloads (`/graph` on the live bank is ~1.8 MB).

```
GET  /graph                               → nodes + edges JSON for d3 (incl. synthetic repo: nodes, has_logo)
GET  /search                              → cross-graph search (entities + episodes)
POST /ask                                 → grounded NL answer over the graph, with citations + gap analysis
GET  /inbox                               → unified pending-item queue (nudges + clarifications + merge suggestions)
POST /inbox/{id}/resolve                  → resolve a pending inbox item (accepts optionKey / answer / remindDays; action "defer" hides it until remind_after)
GET  /nudges                              → DEPRECATED thin projection over /inbox (kept for compat)
POST /nudges/{id}/resolve                 → DEPRECATED — see /inbox/{id}/resolve
GET  /clarifications                      → DEPRECATED thin projection over /inbox (kept for compat)
POST /clarifications/{id}                 → DEPRECATED — see /inbox/{id}/resolve
GET  /healthz, GET /status                → backend health + summary status
GET  /entities/{id}                       → single entity page
GET  /entities/{id}/history               → git blame on entity file, enriched with structured commit metadata
                                            (+ per-commit author from Cicada-Author trailer; ?include_diff=true inlines diffs)
GET  /entities/{id}/history/{commit}/diff → unified diff for that entity file at that commit (G69):
                                            ordered `lines: [{kind: context|add|remove|hunk, oldLine,
                                            newLine, text}]` from `git show -U4 --first-parent`, so
                                            unchanged context is shown with line numbers, GitHub-style.
                                            A file's FIRST commit has no parent — `git show` diffs it
                                            against the empty tree, so it comes back as all-adds; a MERGE
                                            commit needs `--first-parent`, else git emits a combined
                                            (`--cc`) `@@@` diff the parser can't read and the endpoint
                                            silently returns nothing. `added`/`removed`/`truncated` are
                                            kept alongside for back-compat (an older app build, or a
                                            payload cached pre-G69, falls back to those two blocks).
                                            Capped: DIFF_MAX_LINES (400) per flat side,
                                            DIFF_MAX_CONTEXT_LINES (2000) for `lines`. `truncated` is the
                                            UNION of the three caps; `linesTruncated` is specifically
                                            "the ordered list was cut" and is what a client rendering
                                            `lines` shows its "diff clipped" banner on.
                                            (rendered inline by the app's shared DiffView — entity History rows
                                             and the Contributors drill-down both expand into it)
GET  /entities/{id}/location              → directory-entity listing
GET  /entities/{id}/context               → entity + related context bundle
GET  /entities/{id}/repos                 → declared repos: frontmatter + live-resolved git context per repo
PATCH /entities/{id}/repos                → rewrite the repos: frontmatter key
PUT  /entities/{id}/decay                 → set decay class {decayClass: evergreen|durable|active|volatile}
GET  /entities/{id}/logo                  → cached entity logo image (ETag, max-age=86400; 404 = draw a monogram)
GET  /entities/{id}/sources               → declared "where to check this fact" sources (G61)
POST /entities/{id}/sources               → append a source {ref, kind?, predicate?}; kind inferred
DELETE /entities/{id}/sources/{index}     → remove one source
GET  /entities/{id}/claims                → claim layer for an entity
GET  /entities/{id}/timeline              → bi-temporal claim timeline
GET  /transclude                          → transclusion payload for embedding one page inside another
GET  /contributors                        → repo-wide per-author (model/user) commit/file/entity counts + last-active
GET  /contributors/commits?author=&limit= → one author's recent commits (+ entities touched) for the diff drill-down
GET  /origins                             → origin-harness provenance aggregation (G9)
POST /sleep/trigger                       → manually trigger the sleep cycle
GET  /sleep/status, /sleep/history,
     /sleep/episodes, /sleep/schedule     → sleep status/history/queue/schedule
PUT  /sleep/schedule                      → update the sleep-cycle schedule
POST /conversations/upload                → ingest a conversation export file
GET  /conversations/recent                → conversations that wrote to memory (MCP sessions +
                                            imports), newest first; ETag'd; `resumable` per-request.
                                            CAPPED (limit ≤ 200) — never a membership test
GET  /conversations/{id}                  → one conversation by exact id, resolved against the
                                            whole bank (404 = the bank truly has no episode for it)
POST /conversations/{id}/resume           → validated `claude --resume` descriptor (400 bad id /
                                            404 unknown / 409 transcript_gone). Transcripts are
                                            never read — isfile() only.
POST /sources/save, /sources/upload,
     /sources/rss, /sources/sync-bookmarks → capture links/files/RSS/bookmarks into memory
POST /sources/upload?preview=true         → parse an export WITHOUT staging anything:
                                            {recognized, platform, total,
                                             collections:[{name,kind,count}], warnings}
                                            (+ ?include_history=true opts TikTok browsing history in)
GET  /sources/connectors                  → connector status (pinterest/reddit/x): fields present, never values
PUT/DELETE /sources/connectors/{id}/credentials → store/forget creds in ~/.cicada/secrets.env (0600)
POST /sources/connectors/{id}/authorize   → mint the vendor consent URL (oauth adapters; single-use state)
GET  /sources/connectors/{id}/callback    → generalized OAuth redirect target, one route for every
                                            oauth adapter (Pinterest, X today); auth-exempt only for
                                            an id whose LOGIN_MODE is oauth
POST /sources/connectors/{id}/sync        → run one poll now
GET  /sources                             → list ingested sources
GET  /sources/channels                    → capture channels + whether each is actually connected (G62)
GET/POST/DELETE /sources/feeds            → RSS feed subscription management
POST /sources/poll-feeds                  → on-demand RSS poll
GET/POST /banks, POST /banks/{name}/activate|duplicate|rename|import → memory-bank management
GET  /local-ref                           → resolve local device/path references
POST /capture/telegram                    → token-gated Telegram capture webhook
POST /maintenance/dedup-sweep             → full-graph dedup sweep (G21)
GET  /connections, GET /connections/{id}   → provider connections (plan, price, connected) — probed via vendor CLIs
POST /connections/{id}/login|logout        → start the vendor CLI's own login flow / sign out
GET  /connections/{id}/login/{sid}         → device-code login progress (ChatGPT/Codex)
PUT/DELETE /connections/{id}/key           → BYOK key into ~/.cicada/secrets.env (0600)
PUT  /connections/{id}/prefs               → tier override (Claude Max 5x/20x), enabled flag
GET  /sync/version                        → mtime + git-HEAD version vector for change detection (<10 ms)
GET  /sync/events                         → SSE stream of `version` (on change, polled server-side every 1 s), `sleep` (sleep state on change), and `ping` (every 15 s) events
GET  /consumption/summary|calendar|stats|connections|harness → consumption/traceability dashboard (G51);
                                            ledger at ~/.cicada/telemetry/events-YYYY-MM.jsonl (CICADA_TELEMETRY=off disables)
```

The API reads and writes the same markdown files and git repo that the Sleep cycle operates on. **There's no separate database — the filesystem is the single source of truth.**

### Data Flow
```
Sleep cycle generates pending items → writes to memory/inbox/
User opens companion app → SwiftUI calls FastAPI → FastAPI reads memory/inbox/ via GET /inbox
User responds to an inbox item → POST /inbox/{id}/resolve → FastAPI writes resolution to entity page or creates new entity
Next Sleep cycle picks up manual changes → integrates into consolidation
```

---

## MVP Features (Thesis Scope, Priority Order)

### 1. Graph Explorer

Force-directed d3 graph in a WKWebView: node color by entity type, size by confidence, edge
labels, cluster detection, decay/clarification indicators. Feature detail and open ideas live in
[`docs/goals/memory-evolution.md`](docs/goals/memory-evolution.md).

### 2. Nudge Inbox & 3. Clarification Queue — unified `memory/inbox/`
Nudges and clarifications now live in **one unified store**: `memory/inbox/inbox-NNN.md`, each with
a `kind` discriminator (`decay`, `conflict`, `clarification`, `merge_suggestion`), loaded and
resolved by `api/services/inbox_service.py` behind `GET /inbox` / `POST /inbox/{id}/resolve`.
`api/routers/nudges.py` and `api/routers/clarifications.py` are now thin **deprecated** shims
(they set a `Deprecation: true` response header and project the unified store into the old
response shapes) kept only so the SwiftUI app and any external caller keep working mid-migration
— the app itself calls `/inbox` directly.

- List view sorted by priority/recency across all pending kinds
- Each item shows: entity involved, kind, question, relevant context
- Quick-action buttons per kind:
  - **Decay** ("Still interested in Salesforce?"): `Yes, keep active` / `No, archive it` / `Remind me later`
  - **Clarification** ("Who is Francesco?"): free-text answer, dismiss, merge into an existing entity, or skip
  - **Merge suggestion**: confirm or reject a proposed entity merge
- Responding writes the resolution back to the entity page (or creates a new entity)
- Items resolved organically by later conversation are automatically removed
- Badge count on the inbox icon

**Question object (G60):** every `conflict` / `clarification` / `merge_suggestion` item carries
  `question` (one sentence), `options: [{key, label, description, claim_id, observed_at,
  last_referenced}]`, `allow_other`, `allow_defer`, `predicate`, and an optional `hint`
  (from the entity's `sources:`). Descriptions lead with the age phrase ("6 months ago") so
  staleness is visible before choosing; `age_days` is derived at read time, never stored.
  Legacy flat `options: [str]` items still render — they are upgraded to `{key, label}` on read.

**Dedup + time:** items are keyed `(entity_id, predicate)` (clarifications by
  `(entity_id, uncertainty_type)`, merges by the sorted entity pair). A second competing value
  **merges** into the open item as another option instead of writing a duplicate file. Each Sleep,
  `inbox_questions.refresh_open_questions` bumps re-mentioned options, auto-resolves a question the
  user answered organically in conversation, escalates a question every option of which has been
  silent for `inbox_stale_after_days` (default 90) by inserting a "Neither anymore" option, and
  keeps deferred items (`remind_after` in the future) out of `GET /inbox` and `cicada_check_nudges`.

**Resolve is claim-aware:** picking an option supersedes every losing claim (`valid_to` +
  `superseded_by`); "both" keeps them open with a `context` qualifier; "neither"/free text writes a
  `user_stated` claim that closes them; `defer` writes `remind_after`. All four commit with
  `Cicada-Author: user`.

**Three resolution paths for clarifications:**
1. **Organic**: User naturally provides context in later conversation → next Sleep cycle promotes
2. **Agent-initiated**: Agent detects current topic relates to a pending clarification, asks in conversation flow
3. **Manual**: User answers in the companion app's inbox

**Redesign direction (G115).** Every inbox item becomes one question object for every kind — the
card shows the *cause* (the conversation and sentence that raised it), marks Sleep's own proposal
as `(Recommended)` (the option the ledger's `_verdict` would score `agreed`; never on a merge),
lets the person write a scoped "don't ask again" rule once in `<memory>/_inbox_rules.yaml`, and
reaches an agent only through a server-side ask gate keyed on entity identity rather than body
text. Zero LLM on any of it, ledger ids-only, user commits stay session-less pending G116; the
full ruling, phases and rails are in the G115 row of `docs/goals/memory-evolution.md`.

### 4. Manual Sleep Trigger
Button to run the Sleep cycle on demand.

- "Run Sleep cycle now" button
- Status indicator: next scheduled Sleep cycle time
- Full dashboard (per-cycle summaries, diff views) is nice-to-have

### 5. Conversation Upload
Manual ingestion of exports from non-MCP sources (ChatGPT, Claude Desktop/iOS).

- File picker accepting JSON and HTML exports
- Upload triggers parsing and staging into `episodes/` inbox
- Status feedback: episodes extracted, queued for next Sleep cycle
- Deduplication: skip already-ingested episodes (timestamp + content hash)

---

## Post-MVP Features

Tracked in [`docs/goals/memory-evolution.md`](docs/goals/memory-evolution.md) (G-rows), not here.

## Installation & Setup

`install.sh` is the source of truth; the paste-prompt install story is G76 in the backlog.

## UX Principles

1. **Minimal friction**: Responding to a nudge = one tap. Reviewing the graph = immediate. Never require "memory maintenance."
2. **Transparency over magic**: User sees WHY the agent knows something (provenance), WHEN it learned it (timestamps), HOW confident it is (confidence score).
3. **User authority**: Agent proposes, user disposes. Every automated action can be overridden.
4. **Non-intrusive nudging**: Nudges available when wanted, not pushed as notifications (unless enabled). Inbox is there when you want it.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Markdown over Neo4j | Same relational expressiveness at personal scale. Zero infrastructure. Portable. LLM is the query engine. |
| sqlite-vec over LEANN/FAISS | Started on LEANN for its storage savings; replaced by a derived, disposable sqlite-vec index (`api/services/vector_index.py`) with EmbeddingGemma on-device embeddings — stored (not recomputed) vectors give single-lookup query latency with no cloud dependency. |
| Batch over real-time consolidation | Conversations don't have clean endings. Batch sees patterns across full day. Clean evaluation. |
| Entity promotion over upfront extraction | Avoids polluting graph with noise from single mentions. |
| Temporal decay as active signal | Absence of mention is informative. No other system does this. |
| Clarification queue over silent drops | Ask rather than guess or discard. Prevents cascading hallucination. |
| MCP-native + export fallback | MCP for real-time, export for ChatGPT/Claude. Source-agnostic pipeline. |
| SwiftUI + FastAPI | Native macOS feel. Python backend for LLM/ML ecosystem access. |
| d3-force in WKWebView | Best graph visualization ecosystem. Sufficient for personal scale. |
| Filesystem as single source of truth | No separate database. API reads/writes same files as Sleep cycle. |
| Decay class over a bare per-writer rate | A hardcoded `decay_rate` float was invisible to the agent and unchangeable by the user, and it decayed bookmarks — artifacts that never become less true. A four-value class the agent estimates, both engines honor and the user overrides makes the policy legible and correctable. |

---

## Thesis Benchmarks (`benchmarks/` package)

Benchmark tooling for the thesis `Results` section lives in `benchmarks/`. Three runnable scripts plus a shared fresh-workspace scaffold, all at repo root. Runbook is `benchmarks/README.md`.

### Scripts and safety rails

Three runnable scripts plus a shared fresh-workspace scaffold; the runbook is
[`benchmarks/README.md`](benchmarks/README.md) and the how-to-run detail lives in the
`thesis-benchmarks` skill. Two rails that are NOT derivable: no runner ever mutates the live
`memory/` directory (sleep-cycle runs happen in `/tmp/cicada_bench_*` workspaces), and
`workspace.destroy_workspace` refuses any path whose name lacks `cicada_bench_`.

### CRITICAL: Personal-data privacy pattern

**`benchmarks/questions.example.yaml` and `benchmarks/queries.example.txt` are TEMPLATE files with placeholder content only. Never commit real personal questions or queries to them.**

The repo's `.gitignore` automatically excludes three paths:

```
benchmarks/*.local.*
benchmarks/questions.yaml
benchmarks/queries.txt
```

The recommended workflow is the `.local.` copy pattern:

```sh
cp benchmarks/questions.example.yaml benchmarks/questions.local.yaml
cp benchmarks/queries.example.txt     benchmarks/queries.local.txt
# Fill the .local files with real content grounded in personal memory.
# They are gitignored; they will never end up in a commit.

api/.venv/bin/python -m benchmarks.run_table1 \
    --questions benchmarks/questions.local.yaml \
    --memory memory \
    --out benchmark_results/table1

api/.venv/bin/python -m benchmarks.run_table3 \
    --memory memory \
    --queries benchmarks/queries.local.txt \
    --out benchmark_results/table3
```

Rules for any future Claude session that touches the benchmark tooling:

1. **Never paste real personal names, projects, or organizations into `benchmarks/questions.example.yaml` or `benchmarks/queries.example.txt`.** These are committed templates. Neutral but plausible thesis-shaped examples are fine (a generic capstone, "the supervisor", "the university", an unnamed internship, the thesis deadline) — anything that could be true of any final-year project. No real names, no real companies, no real episode IDs, no anything you would not want a stranger reading.
2. **Never add new files under `benchmarks/` that contain real personal content** unless they use the `*.local.*` suffix (or are under `benchmark_results/`, which is also gitignored).
3. **`benchmark_results/` is gitignored** — raw retrieval dumps, scoring sheets, and workspace metadata live there. Safe to write to, never safe to commit.
4. **If you are drafting a new question or query for demonstration purposes in a commit message, PR description, or README**, use generic placeholders (`<placeholder fact question>`, `placeholder query one`), never real entities from `memory/`.
5. **The `run_table1` scoring sheet contains the retrieved context and final answer verbatim** — that content will include personal data from real queries. It is written to `benchmark_results/` by default. Never move it out of that directory into a committed path.
