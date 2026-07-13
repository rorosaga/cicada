# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project

**Cicada** — A Cognitive Agent Architecture for Personal Knowledge Evolution via Structured Memory Consolidation. BSc Capstone Thesis at IE University. Author: Rodrigo Sagastegui. Supervisor: Prof. Raul Perez Pelaez.

Cicada is a personal AI agent memory system using a biologically-inspired Awake/Sleep consolidation architecture. It compresses episodic noise into a structured, versioned knowledge graph. The biological analogy: Awake = hippocampal encoding (fast, episodic), Sleep = cortical consolidation (slow, semantic), temporal decay = synaptic homeostasis.

## Branches

- `main`: production/stable branch
- `dev`: active development branch — all work goes here first

---

## Repository Structure

```
cicada/
├── api/                        ← FastAPI backend (Python)
│   ├── main.py
│   ├── routers/
│   │   ├── graph.py
│   │   ├── nudges.py
│   │   ├── clarifications.py
│   │   ├── sleep.py
│   │   └── conversations.py
│   ├── services/               ← sleep cycle logic, entity resolution, LEANN integration
│   └── requirements.txt
│
├── app/                        ← SwiftUI macOS app
│   ├── CicadaApp.xcodeproj
│   └── CicadaApp/
│       ├── Views/
│       │   ├── GraphView.swift         ← WKWebView wrapper for d3
│       │   ├── NudgeInboxView.swift
│       │   ├── ClarificationQueueView.swift
│       │   ├── SleepDashboardView.swift
│       │   └── ConversationUploadView.swift
│       ├── ViewModels/                 ← @Observable ViewModels per screen
│       ├── Services/
│       │   └── APIClient.swift         ← URLSession async/await wrapper
│       ├── Models/                     ← Swift data models matching API responses
│       └── Resources/
│           └── graph/                  ← bundled d3 files
│               ├── index.html
│               └── graph.js
│
├── memory/                     ← runtime data (separate git repo or gitignored)
│   ├── episodes/               ← raw timestamped conversation chunks
│   ├── entities/               ← markdown entity pages with YAML frontmatter
│   ├── nudges/                 ← pending nudge files
│   └── clarifications/         ← pending clarification files
│
├── CLAUDE.md                   ← You are here
└── README.md
```

---

## Core Architecture: Awake/Sleep

### Awake Cycle
Continuous episode capture during conversations. Raw timestamped chunks go to `episodes/` inbox. **No LLM processing at capture time** — just logging. This is cheap (just file I/O).

**Input sources:**
- **MCP-native clients** (Claude Code, Cursor): Cicada MCP server is directly in the conversation loop. Episodes captured automatically. This is the primary deployment model.
- **Export-based ingestion** (ChatGPT, Claude Desktop/iOS): Periodic import from conversation exports. ChatGPT gives HTML/JSON, Claude gives JSON. LEANN has built-in importers.
- **Telegram bot** (`/save`, `/note`, `/remind`): On-the-go capture of links, voice notes (Whisper transcription), text snippets. Stages in `inbox/`.
- **Ingested sources**: Safari bookmarks, saved links, PDFs, repos. Indexed in LEANN for semantic retrieval.

**Episode tracking:** Each episode has unique ID (`ep_YYYY-MM-DD_NNN`), timestamp, and `processed: false` flag. Sleep cycle processes all unprocessed episodes regardless of source — the pipeline is source-agnostic.

### Sleep Cycle (5-Stage Nightly Batch Pipeline)
Triggered by cron or manual command:

1. **Entity & Relationship Extraction**: LLM processes episode chunks with structured extraction prompts. Outputs typed entities and relationships as JSON.
2. **Entity Resolution & Deduplication**: Reconciles against existing graph via fuzzy matching, embedding similarity, LLM disambiguation. "Mongo" → "MongoDB", "the project" → which project?
3. **Conflict Resolution & Pruning**: Detects contradictions ("switched from Postgres to SQLite"). Recency wins, old state archived in version history. Temporal decay: absence of mention triggers confidence drop.
4. **Pattern Detection & Skill Extraction**: Scans for recurring interaction patterns across cycles. Distills into procedural skills (preferences, routines, workflows) stored as skill-type entities.
5. **Nudge Generation, Clarification Queue & Versioning**: Generates three nudge types (decay, conflict, clarification). Creates versioned snapshot. Commits to git.

### Entity Promotion Model
Entities are NOT extracted upfront from every mention. The promotion model avoids graph pollution:
1. First mention → raw chunk stays in LEANN index only
2. Second mention across a different conversation → Sleep cycle notices recurrence
3. Promotion threshold met → create entity page with backfilled context

Thresholds: referenced in 2+ separate conversations, OR discussed substantively (>3 exchanges) in a single conversation, OR explicitly linked to an existing high-confidence entity.

### Temporal Decay
Absence of mention IS a signal. If you talked about Salesforce daily for a week then stopped for two weeks, that silence is informative.
- Every entity has `last_referenced` and `decay_rate` in frontmatter
- Sleep drops confidence for unreferenced entities proportional to how frequently they USED to be referenced
- Below archive threshold (0.2): entity moves to `archive/`
- Below nudge threshold (0.4): generates decay nudge
- If mentioned again: promoted back, confidence restored

---

## Storage Layer

### Structured Markdown Folder (Knowledge Graph)
Wikilinked `.md` files with YAML frontmatter. LLM reads and writes. Git-versioned. Zero infrastructure — just a folder.

**Why markdown over Neo4j:** At personal scale (hundreds of entities, not millions), the LLM can read markdown and follow wikilinks — it doesn't need Cypher. Zero infrastructure, human-readable, git-versioned, portable, Obsidian-compatible.

### Entity Schema
Every entity page uses this YAML frontmatter:

```yaml
---
type: person | project | company | concept | tool | deadline | skill | location
status: active | decaying | archived | dropped
confidence: 0.85          # 0.0–1.0
created: 2026-01-10
last_referenced: 2026-03-22
decay_rate: 0.05           # per-entity, not global
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

**Entity types (closed set of 8):**

| Type | Description | Examples |
|------|-------------|---------|
| `person` | Named individual | supervisor, teammate, recruiter |
| `project` | Active or past work | capstone, startup prototype, side project |
| `company` | Organization | university partner, internship host, startup |
| `concept` | Idea, topic, knowledge area | Knowledge Graphs, Context Engineering |
| `tool` | Technology, framework, software | Neo4j, LEANN, FastAPI |
| `deadline` | Time-bound commitment | final submission deadline |
| `skill` | Procedural memory, preferences | "Prefers concise summaries" |
| `location` | Place | home city, conference city |

**Status lifecycle:** `active` → `decaying` → `archived` → `dropped` (user-dismissed, never resurfaced)

### LEANN (Vector Index)
Lightweight on-device semantic search. Graph-based selective recomputation, 97% less storage than FAISS (400K chunks = 64MB vs 1.8GB). MIT license, Berkeley Sky Computing Lab. Handles fuzzy "find me stuff related to X" queries. Runs locally, zero cloud costs.

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
are attributed to **`unknown`**. The trailer carries no entity id, so it is **inert to the
entity-line parsing** above — extend it, don't break it. Built by
`git_service.build_commit_message(subject, body_lines, authors=...)` and parsed by
`git_service._parse_authors`. This powers `GET /contributors` (repo-wide per-author
commit/file/entity counts + last-active) and the per-commit `author` field on
`GET /entities/{id}/history` — a memory system honest about which model authored each belief.

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
1. Checks `nudges/` and `clarifications/` for relevant pending items
2. Searches LEANN for semantically similar chunks
3. Searches markdown graph for structurally related entities
4. LLM follows wikilinks for relational depth
5. Progressive disclosure: cluster pages → entity pages → episodic sources

### Proactive Behaviors (Awake Phase)
When a new conversation starts, Bookworm checks:
1. **Pending nudges**: Surfaces relevant decay or conflict nudges based on conversation context (only topic-related, not all)
2. **Clarification queue**: If conversation touches an entity with a pending clarification, the agent asks naturally within the flow
3. **Related saved resources**: LEANN search over ingested bookmarks, links, papers
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

---

## API Design

One endpoint per screen:

```
GET  /graph                     → nodes + edges JSON for d3
GET  /nudges                    → list of pending nudges
POST /nudges/{id}/resolve       → submit resolution for a nudge
GET  /clarifications            → list of pending clarifications
POST /clarifications/{id}       → answer / dismiss / merge / skip
GET  /entities/{id}/history     → git blame on entity file, enriched with structured commit metadata
                                  (+ per-commit author from Cicada-Author trailer; ?include_diff=true inlines diffs)
GET  /entities/{id}/history/{commit}/diff → added/removed lines for that entity file at that commit
GET  /contributors              → repo-wide per-author (model/user) commit/file/entity counts + last-active
POST /sleep/trigger             → manually trigger the sleep cycle
GET  /sleep/history             → git log on whole repo (chronological Sleep cycle history)
POST /conversations/upload      → ingest a conversation export file
```

The API reads and writes the same markdown files and git repo that the Sleep cycle operates on. **There's no separate database — the filesystem is the single source of truth.**

### Data Flow
```
Sleep cycle generates nudges → writes to nudges/ and clarifications/
User opens companion app → SwiftUI calls FastAPI → FastAPI reads nudges/ and clarifications/
User responds to nudge → POST to FastAPI → FastAPI writes resolution to entity page or creates new entity
Next Sleep cycle picks up manual changes → integrates into consolidation
```

---

## MVP Features (Thesis Scope, Priority Order)

### 1. Graph Explorer
Interactive force-directed graph visualization, inspired by Obsidian's graph view.

- Force-directed layout with nodes and edges (d3-force in WKWebView)
- **Node colors by entity type:**
  - person = blue, project = purple, company = orange, concept = green
  - tool = teal, deadline = red, skill = yellow, location = gray
- Node size reflects confidence score (higher = larger)
- Edge labels show relationship types
- Clicking a node opens the entity page (rendered markdown with frontmatter metadata visible)
- Search/filter by entity type, tags, status, confidence range
- Cluster detection: automatic grouping of related entities
- Zoom, pan, and navigate
- Visual indicators for decaying entities (fading opacity or dashed borders)
- Visual indicators for entities with pending clarifications (pulsing or question mark icon)

**Nice-to-have:**
- Temporal playback: scrub through git history to see graph evolution
- Sleep cycle overlay: highlight nodes/edges added, modified, or pruned per cycle
- 3D view via Three.js

### 2. Nudge Inbox
Queue of pending nudges generated by the Sleep cycle.

- List view sorted by priority/recency
- Each nudge shows: entity involved, nudge type (decay/conflict/clarification), question, relevant context
- Quick-action buttons per nudge type:
  - **Decay** ("Still interested in Salesforce?"): `Yes, keep active` / `No, archive it` / `Remind me later`
  - **Conflict** ("Postgres or SQLite?"): `[Option A]` / `[Option B]` / `Both are true (different contexts)`
  - **Clarification** ("Who is Francesco?"): Free-text input field
- Responding writes the resolution back to the entity page (or creates a new entity)
- Nudges resolved organically by later conversation are automatically removed (`resolved_organically`)
- Badge count on nudge inbox icon

### 3. Clarification Queue
Dedicated view for entities the system couldn't confidently extract. Different interaction pattern from general nudges.

- Shows: entity name/mention, source episode context, what the system is uncertain about (type? relationship? identity?), suggested classification (low-confidence guess)
- User actions:
  - **Answer**: text response → entity promotion in next Sleep cycle
  - **Dismiss** ("not important"): stays in LEANN as raw chunk, never promotes
  - **Merge** ("same as [existing entity]"): links to existing entity page
  - **Skip** ("later"): stays in queue
- Organically resolved clarifications disappear with notification

**Three resolution paths for clarifications:**
1. **Organic**: User naturally provides context in later conversation → next Sleep cycle promotes
2. **Agent-initiated**: Agent detects current topic relates to pending clarification, asks in conversation flow
3. **Manual**: User answers in companion app's clarification queue

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

- **Entity Management**: Full CRUD on entity pages (view, edit, create, delete, merge, version history, provenance)
- **Full Sleep Cycle Dashboard**: Per-cycle summaries, diff views, complete history
- **3D graph** (Three.js / react-three-fiber)
- **Mobile companion** — lightweight nudge review on iOS
- **Obsidian plugin** — render graph inside Obsidian
- **Tauri rewrite** — single Rust-backed binary
- **Privacy mode**: `/private` toggle stops writing to episodic buffer for that session
- **Berry verification layer**: HallBayes post-Sleep, pre-write verification gate (Bayesian entailment scoring)

---

## Installation & Setup

Cicada ships as a macOS `.dmg`. Drag-to-Applications.

On first launch, guided onboarding flow:
1. Create `~/cicada/memory/` with correct directory structure
2. Register MCP server in `~/.claude/mcp_servers.json`
3. Register FastAPI backend as a launchd service (auto-starts on login)
4. Set up nightly cron for Sleep cycle

After onboarding, the user never interacts with the backend directly. The companion app and any MCP-compatible client just work.

---

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
| LEANN over FAISS | 97% storage savings (64MB vs 1.8GB for 400K chunks). Critical for on-device use. |
| Batch over real-time consolidation | Conversations don't have clean endings. Batch sees patterns across full day. Clean evaluation. |
| Entity promotion over upfront extraction | Avoids polluting graph with noise from single mentions. |
| Temporal decay as active signal | Absence of mention is informative. No other system does this. |
| Clarification queue over silent drops | Ask rather than guess or discard. Prevents cascading hallucination. |
| MCP-native + export fallback | MCP for real-time, export for ChatGPT/Claude. Source-agnostic pipeline. |
| SwiftUI + FastAPI | Native macOS feel. Python backend for LLM/ML ecosystem access. |
| d3-force in WKWebView | Best graph visualization ecosystem. Sufficient for personal scale. |
| Filesystem as single source of truth | No separate database. API reads/writes same files as Sleep cycle. |

---

## Thesis Benchmarks (`benchmarks/` package)

Benchmark tooling for the thesis `Results` section lives in `benchmarks/`. Four runnable scripts plus a shared fresh-workspace scaffold, all at repo root. Runbook is `benchmarks/README.md`.

### Scripts

- `benchmarks.rebuild_leann` — one-shot helper to rebuild the LEANN indexes in place. **Required prerequisite before `run_table1`** if `memory/leann/episodes.*` is incomplete (the episodes-only baseline can't retrieve anything without it). Costs a few cents of `text-embedding-3-small`.
- `benchmarks.run_table1` — three-condition recall eval (Cicada full vs Cicada no-Sleep episode-LEANN-only vs manual commercial baseline). Writes JSONL + scoring-sheet CSV. Scoring is manual per the four-dimensional rubric in `sections/experiments.tex`.
- `benchmarks.run_table3` — operational measurements. Static counts, disk sizes, recall latency (median/p95/etc.), and optional `--sleep-cycle-time` for fresh-workspace wall-clock.
- `benchmarks.run_ablation` — Table 2 threshold sweep. Runs one fresh sleep cycle per config (default + promotion 1/3 + decay 0.3/0.5) in throwaway `/tmp/cicada_bench_table2_*` workspaces.

### Safety rails

- None of the runners mutate the live `memory/` directory. Any sleep cycle runs happen inside `/tmp/cicada_bench_*` workspaces seeded from `memory/episodes`.
- `workspace.destroy_workspace` refuses to delete any path whose name doesn't contain `cicada_bench_`.
- `api/.env` is auto-loaded into `os.environ` by `benchmarks/_bootstrap.py` — shell exports still win.

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
