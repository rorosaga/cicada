# P4 — Origin Provenance + Cross-Harness Sync Design (G9)

**Status:** Design artifact — do NOT commit code changes, do NOT touch `api/`.
**Author:** Prep agent, 2026-06-17.
**Backlog ref:** G9 in `docs/goals/memory-evolution.md`.
**Related:** D2 final-architecture ADDENDUM (confirmed, authoritative) in
`docs/goals/d2-architecture-final.md`; M3 `Cicada-Author` contributors work.

---

## 0. The Three Provenance Dimensions — Disambiguation

Before designing `origin`, it is essential to hold all three provenance axes distinct:

| Field | Question answered | Lives on | Example value |
|---|---|---|---|
| `authored_by` | **Which model wrote this memory?** | Claim, git trailer `Cicada-Author:` | `gpt-5.4-mini`, `user` |
| `observer` | **Whose belief is this?** | Claim (primary key dim) | `agent`, `rodrigo`, `external:karpathy` |
| `origin` | **Which harness/surface did the episode come from?** | Episode frontmatter → Claim | `claude-code`, `codex`, `chatgpt-export` |

`authored_by` (M3) answers the model attribution audit question.
`observer` (D2/M5) answers the epistemological "who believes X" question.
`origin` (G9/this doc) answers the operational "where in the world did this conversation happen"
question.

They are sibling fields on a Claim, never collapsed.

---

## 1. The `origin` Field — End-to-End Design

### 1a. Canonical value set

A closed core with an open extension tail (`custom:<slug>`):

```
claude-code          — Claude Code (this MCP server, cicada_save_episode)
codex                — OpenAI Codex CLI / Codex agent
cursor               — Cursor IDE agent
openclaw             — OpenClaw / custom agent harness
chatgpt-export       — ChatGPT HTML/JSON export batch ingest
claude-export        — Claude.ai Desktop/iOS conversation export batch ingest
telegram             — Telegram bot (/save, /note, /remind)
manual_edit          — Direct markdown edit or companion-app UI write
clarification        — Companion-app clarification-queue answer
rss                  — RSS/Atom feed connector (M4 media ingestor)
bookmark             — Browser bookmark / cicada_save_url
custom:<slug>        — Future / unknown harness (slug = sanitize_id(harness name))
unknown              — Fallback when origin cannot be inferred
```

**Invariant:** `origin` is a **harness identifier**, not a model id and not a trust class.
`origin: claude-code` + `authored_by: claude-sonnet-4-6` + `observer: agent` are all valid
simultaneously on the same claim.

### 1b. Where `origin` is set — capture layer

Origin must be set at **episode creation time**, not inferred later. The Sleep cycle
cannot reliably recover origin from content alone.

**Episode frontmatter schema extension (additive):**

```yaml
---
id: ep_2026-06-17_001
timestamp: '2026-06-17T10:00:00Z'
source: claude-code          # ← EXISTING field, already used; rename semantics below
origin: claude-code          # ← NEW explicit field (G9); supersedes `source` for this role
title: ...
processed: false
content_hash: abc123
---
```

**Relationship to the existing `source` field:**

The live `memory/episodes/` corpus uses `source` with values: `claude` (107 episodes),
`claude_memory` (6), `claude_project` (3), `mcp` (1). These map to the new `origin` values as:

| Legacy `source` value | Maps to `origin` |
|---|---|
| `claude` | `claude-code` (when captured via MCP server) |
| `claude_memory` | `claude-code` |
| `claude_project` | `claude-code` |
| `mcp` | `claude-code` |
| *(missing)* | `unknown` |

Migration: Sleep cycle Stage 1 should read `origin` if present; if absent, derive it from
`source` using the table above and write it back to the episode frontmatter. This is a
one-pass idempotent backfill — cheap, no LLM cost.

**Per-harness write point:**

| Harness | Where `origin` is set |
|---|---|
| `mcp/server.py` → `handle_save_episode` | `origin: claude-code` in the written frontmatter |
| Export batch ingestor (`conversations/upload`) | `origin: chatgpt-export` or `claude-export` per file type |
| Telegram bot | `origin: telegram` |
| Media ingestor / RSS | `origin: rss` or `origin: bookmark` (already sets `source` on media entities) |
| Companion-app clarification resolve | `origin: clarification` |
| Direct markdown edit | `origin: manual_edit` |
| Future Codex/Cursor hook | `origin: codex` / `origin: cursor` |

### 1c. Propagation: episode → extracted entity/claim

Sleep cycle Stage 1 (entity/claim extraction) already propagates `source_episode` from the
episode dict into each extracted entity/claim dict (see `entity_extractor.py` lines 184–226).
`origin` propagation piggybacks on the same mechanism:

1. `_get_unprocessed_episodes` (in `sleep_cycle.py`, lines 236–251) already reads
   `source: parsed.frontmatter.get("source", "unknown")` into the episode dict.
   Add: `"origin": parsed.frontmatter.get("origin") or _derive_origin(parsed.frontmatter.get("source", ""))`.

2. `entity_extractor.extract(episodes, settings)` stamps `source_episode` on each entity/rel.
   Add a parallel stamp: `entity["origin"] = episode.get("origin", "unknown")`.

3. Claim extraction (M5a, `claims.py` — `Claim.origin` already exists as a field with
   `origin: str | None = None`): the extractor sets `claim.origin = episode["origin"]` when
   constructing each claim from an episode.

4. `conflict_resolver.apply_changes` and `entity_body.py` can then persist `origin` in the
   entity page frontmatter as `source_origin` (a list, like `source_episodes`, tracking all
   origins that contributed). The claim's `origin` field is the per-claim record.

**Resulting claim (worked example):**

```yaml
- id: clm_2026-06-17_001
  text: "Rodrigo is interviewing with Charles, CEO of Strawberry Browser."
  subject: rodrigo
  predicate: interviewed-with
  object: charles-strawberry-browser
  observer: agent
  context: career
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.85
  valid_from: '2026-04-16'
  valid_to: null
  source_episodes: [ep_2026-04-16_001]
  authored_by: gpt-5.4-mini
  origin: claude-code           # ← the episode's source was `mcp`, derives to `claude-code`
```

### 1d. Entity-level frontmatter

Entity pages gain an optional `source_origins` list field (parallel to `source_episodes`),
populated by conflict_resolver from the union of all contributing episodes' `origin` values:

```yaml
source_origins:
  - claude-code
  - chatgpt-export
```

This makes origin queryable at the entity level without reading every claim.

---

## 2. Sync Queue — How Any Harness Pushes Episodes

### 2a. Options comparison

Three viable mechanisms, evaluated on: zero-setup for user, works when API is down,
handles dedup, works cross-process, and real-time vs batch.

**Option A — MCP `cicada_save_episode` (existing)**

- **How it works:** The harness calls `cicada_save_episode(content=..., title=...)` via the
  MCP protocol. `mcp/server.py` writes the episode file to `memory/episodes/` with
  `source: mcp`, `processed: false`, and a content hash for dedup.
- **Pros:** Already exists and works (M1). Zero setup for MCP-native clients (Claude Code,
  Cursor). Natural integration point. Dedup via content hash is already implemented.
  Works offline (no API needed — MCP server writes directly to the filesystem).
- **Cons:** Requires the harness to be an MCP client. Codex CLI and ChatGPT exports are
  not MCP clients. Does not batch well for large exports. No structured metadata beyond
  `title`/`content`.
- **Missing for G9:** `origin` is not passed as a parameter today — the MCP server hardcodes
  `source: mcp`. Must be extended to accept an optional `origin` hint.

**Option B — File-drop watched queue directory (`memory/inbox/`)**

- **How it works:** Any harness (stop-hook, shell script, CI job, Python script) drops a
  pre-formatted episode `.md` file into `memory/inbox/`. A filesystem watcher (or the Sleep
  cycle's pre-Stage-1 step) moves files into `memory/episodes/` after validation and dedup.
  The harness sets `origin:` in the frontmatter before dropping.
- **Pros:** Zero protocol dependency — any script that can write a file works. Works fully
  offline. Natural for batch/export ingesters (ChatGPT JSON parser dumps N files at once).
  Harness stop-hooks (shell `EXIT` trap or a Codex/Cursor on-session-end hook) can dump a
  session transcript here without needing an HTTP server. Easy to inspect and debug.
- **Cons:** Requires a watcher daemon or a cron job. File-level dedup requires reading
  content hashes. Possible race conditions if multiple harnesses write simultaneously
  (mitigated by per-harness subdirectory or atomic rename).
- **Variant:** Per-harness subdirectory (`memory/inbox/codex/`, `memory/inbox/claude-code/`)
  so origin is inferrable from path even if frontmatter is missing.

**Option C — Small ingest HTTP API (`POST /episodes/ingest`)**

- **How it works:** A FastAPI endpoint accepts `{content, title, origin, metadata}` and
  writes the episode file. Harnesses call it via HTTP. The endpoint validates, deduplicates,
  and returns the assigned episode id.
- **Pros:** Structured, versioned, testable. Language-agnostic (any harness that can make an
  HTTP request). Can enforce schema at ingestion time. Easy to monitor via API logs.
- **Cons:** Requires the FastAPI backend to be running. Adds a network round-trip for local
  harnesses. A harness stop-hook that fires as the session exits may race with backend
  shutdown. Adds a new router to maintain.

### 2b. Recommendation: Layered (A + B), with C as an opt-in extension

**Primary path (now, minimal work): extend MCP `cicada_save_episode` (Option A).**

Extend the tool schema with an optional `origin` parameter (default `"claude-code"` when
called from the MCP server context). The server writes `origin:` into the episode frontmatter.

```python
# mcp/server.py — extended tool schema (additive, non-breaking)
{
    "name": "cicada_save_episode",
    "description": "...",
    "inputSchema": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "title": {"type": "string"},
            "origin": {
                "type": "string",
                "description": (
                    "The harness/surface this episode came from. "
                    "Defaults to 'claude-code' when called via MCP. "
                    "Valid values: claude-code | codex | cursor | telegram | manual_edit | ..."
                ),
            },
        },
        "required": ["content"],
    },
}
```

**Secondary path (for non-MCP harnesses): file-drop inbox (Option B), gated behind a
`memory/queue/` directory** (distinct from the existing `memory/inbox/` which holds nudge/
clarification items — naming collision must be avoided).

Proposed layout:

```
memory/
└── queue/                  # ← NEW: harness episode drop zone
    ├── claude-code/        # episodes from Claude Code MCP (overflow / stop-hook)
    ├── codex/              # Codex CLI stop-hook drops here
    ├── chatgpt-export/     # batch export parser outputs here
    └── telegram/           # Telegram bot drops here
```

A lightweight `queue_watcher.py` service (or a pre-Stage-1 step inside `sleep_cycle.run()`)
scans `memory/queue/**/*.md`, validates frontmatter, deduplicates against the content-hash
index, and moves valid files to `memory/episodes/`. Origin is inferred from the subdirectory
name if not in frontmatter.

**Stop-hook integration for Codex/Cursor:**

A harness stop-hook is a shell EXIT trap or a `~/.config/codex/hooks/session_end.sh` script.
Minimal example:

```bash
#!/usr/bin/env bash
# ~/.config/codex/hooks/session_end.sh
# Dump session transcript to Cicada's queue on session exit.
set -euo pipefail
QUEUE_DIR="${CICADA_MEMORY_PATH:-$HOME/cicada/memory}/queue/codex"
mkdir -p "$QUEUE_DIR"
DATE=$(date +%Y-%m-%d)
SEQ=$(ls "$QUEUE_DIR"/ep_${DATE}_*.md 2>/dev/null | wc -l)
SEQ=$(printf "%03d" $((SEQ + 1)))
EPISODE_ID="ep_${DATE}_${SEQ}"
HASH=$(echo "$CICADA_SESSION_CONTENT" | sha256sum | cut -c1-12)
cat > "$QUEUE_DIR/${EPISODE_ID}.md" <<EOF
---
id: ${EPISODE_ID}
timestamp: '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
source: codex
origin: codex
title: ${CICADA_SESSION_TITLE:-Codex session}
processed: false
content_hash: ${HASH}
---

${CICADA_SESSION_CONTENT}
EOF
```

The session content and title are injected as environment variables by the harness
(Codex already has a `--on-exit` hook mechanism).

**Option C (HTTP API):** implement later as a convenience wrapper around the same file-write
logic, for harnesses that prefer HTTP (browser extensions, remote agents, CI). Not a
prerequisite for G9.

### 2c. Deduplication contract

Dedup is based on `content_hash` (SHA-256 of content, first 12 hex chars — already
implemented in `mcp/server.py`). The `queue_watcher` reads the existing content-hash index
before moving a file. An episode already present in `memory/episodes/` with the same hash is
silently dropped (not an error). The queue file is removed after successful move or dedup.

---

## 3. Origin in the Contributors-Style View

### 3a. Existing contributors view (M3 baseline)

`GET /contributors` (implemented in M3, `api/routers/contributors.py`) returns a per-author
(model/user) aggregate over `Cicada-Author:` git trailers:

```json
[
  {"author": "gpt-5.4-mini", "commits": 12, "files_changed": 34, "entities_touched": 28, "last_active": "2026-05-05"},
  {"author": "user", "commits": 4, "files_changed": 7, "entities_touched": 5, "last_active": "2026-06-15"},
  {"author": "unknown", "commits": 89, "files_changed": 310, "entities_touched": 270, "last_active": "2026-03-22"}
]
```

This answers "which model wrote each commit." It is git-level, not episode-level.

### 3b. Origin view — what it adds

Origin is an **episode-level and claim-level** dimension. It cannot be read from git trailers
alone — it lives in episode frontmatter and (after M5) in claim fields.

The simplest viable implementation is a new `GET /contributors/origins` endpoint (or an
optional `?by=origin` query param on the existing endpoint) that scans `memory/episodes/`
and aggregates by `origin`:

```json
[
  {
    "origin": "claude-code",
    "episode_count": 113,
    "processed_count": 112,
    "unprocessed_count": 1,
    "date_range": {"first": "2024-10-28", "last": "2026-06-17"},
    "examples": ["ep_2026-04-16_001", "ep_2026-06-17_002"]
  },
  {
    "origin": "chatgpt-export",
    "episode_count": 47,
    "processed_count": 47,
    "unprocessed_count": 0,
    "date_range": {"first": "2025-01-10", "last": "2025-12-30"},
    "examples": ["ep_2025-01-10_001"]
  },
  {
    "origin": "telegram",
    "episode_count": 8,
    "processed_count": 8,
    "unprocessed_count": 0,
    "date_range": {"first": "2026-02-01", "last": "2026-05-20"},
    "examples": ["ep_2026-02-01_001"]
  }
]
```

After M5a/M5b (claims scaffolded), the response can additionally include `claim_count` per
origin by scanning the `origin` field in the in-page claims blocks. The vector index
(`meta_claims` JSON-metadata table) will store `origin` as a pivot axis, so
`claim_count_by_origin` becomes a single SQL GROUP BY query.

### 3c. Companion-app surface

The Companion app (SwiftUI, M5c) can add an **Origin Breakdown** section in the Sleep
Dashboard or Contributors view:

- A horizontal stacked bar showing episode share by origin (color-coded by harness).
- Tapping an origin segment shows the episode list for that harness.
- The existing `CicadaTheme` palette can assign stable per-origin colors using the same
  `contextColor(_:)` stable-hash approach used for contexts.

In the d3 graph (M5c), `origin` can optionally be surfaced as a node badge (similar to the
`observer` badge design), so nodes whose only supporting claims come from, say, `chatgpt-export`
are visually distinguishable from nodes grounded in `claude-code` live conversations. This is
a low-priority overlay — origin is more an operational audit dimension than a belief-quality
dimension — but it is available since it is in the claim metadata.

### 3d. API shape (additive, no breaking changes)

```
GET /contributors                    → existing per-model git-trailer view (unchanged)
GET /contributors/origins            → NEW: per-origin episode + claim aggregate
GET /contributors/origins/{origin}   → NEW: episode list for one origin (for drill-down)
```

All three are read-only scans of `memory/episodes/` and (after M5) the claims index.
No new write paths.

---

## 4. Implementation Order (Dependency Graph)

```
P4a — Episode frontmatter: add `origin` field to mcp/server.py (cicada_save_episode)
      + derive origin from legacy `source` in _get_unprocessed_episodes.
      Cost: ~30 min, zero LLM cost. Non-breaking.

P4b — Sleep Stage 1: propagate episode["origin"] → entity["origin"] → claim.origin.
      Cost: ~1 hr, zero LLM cost. Requires P4a.

P4c — queue/ directory + queue_watcher pre-Stage-1 step.
      Cost: ~2 hrs, zero LLM cost. Requires P4a.
      Unlocks: Codex/Cursor stop-hook pattern, batch export re-ingestion.

P4d — GET /contributors/origins endpoint.
      Cost: ~1 hr, zero LLM cost. Requires P4a (episodes have origin).
      Requires P4b for claim_count (can ship episode-only first).

P4e — Companion-app origin breakdown view (SwiftUI).
      Cost: ~2 hrs, zero LLM cost. Requires P4d. Gated behind M5c app work.
```

P4a and P4b can land inside M5a (the claims scaffolding milestone) as zero-cost addenda.
P4c is a thin service, appropriate to land in M5a or M5b. P4d lands with or after M5c.
P4e is a nice-to-have for the thesis demo.

---

## 5. Invariants and Edge Cases

**`origin` is set at capture, never inferred by the LLM.** The Sleep extractor does not
attempt to guess origin from conversation content. If `origin` is missing and cannot be
derived from `source`, it defaults to `unknown` — which is honest.

**Multiple origins on one entity are expected and correct.** An entity mentioned in a
`claude-code` conversation AND in a `chatgpt-export` conversation correctly lists both in
`source_origins`. The claim-level `origin` tracks the per-claim lineage more precisely.

**`origin` is not a trust signal.** `source_trust` (`user_stated | agent_extracted |
agent_reflected | external`) is the trust axis. `origin: telegram` does not imply lower
trust than `origin: claude-code` — a manual `/save` on Telegram is `source_trust: user_stated`.
The Sleep cycle's trust rules apply to `source_trust`, not `origin`.

**The `source` field is kept for backward compatibility.** The new `origin` field is additive.
The `source` field continues to be written and read. Legacy episodes without `origin` fall
back to the derivation table in section 1b. No existing episode is mutated unless the
backfill step runs.

**Dedup is content-hash-based, not origin-based.** The same conversation captured from two
different harnesses produces the same hash → deduplicated to one episode. This is the correct
behavior (one episode per conversation, regardless of how many harnesses tried to capture it).

---

## 6. Open Questions (for Rodrigo to decide)

1. **Queue directory name:** `memory/queue/` vs `memory/drop/` vs `memory/harness-inbox/`.
   Must not collide with the existing `memory/inbox/` (nudges/clarifications).
   Recommendation: `memory/queue/`.

2. **Backfill timing:** Run the `source` → `origin` derivation pass immediately as part of
   the next Sleep cycle (writes `origin` to episode frontmatter), or defer until M5a lands.
   Recommendation: defer to M5a so it can be tested with the new Sleep refactor.

3. **Codex stop-hook:** Is Codex CLI available / used? If yes, the stop-hook pattern in
   section 2b is the right approach. If not, drop it from scope.

4. **HTTP API (Option C):** Defer until post-thesis, or build it in M5 as a convenience
   layer? Recommendation: defer — the MCP + file-drop combination covers all active harnesses.
