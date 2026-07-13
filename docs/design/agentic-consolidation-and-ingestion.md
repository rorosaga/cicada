# Design: Agentic consolidation skill + unified ingestion

**Date:** 2026-07-03 · **Status:** proposed (awaiting Rodrigo's approval) · **Branch:** `feat/memory-evolution`

Two linked designs: (1) the **agentic consolidation skill** — how a user's own agent builds
memory through the MCP, so no Cicada API key is needed; (2) the **ingestion model** — how
bookmarks/videos/messages get in, and whether that's an import page, a sync queue, or both.

---

## Part 1 — Agentic consolidation skill

### The idea
A distributable **`SKILL.md`** (installs in Claude Code / Codex / Cursor via the same universal
skills installer `claude-video` uses) that turns the user's *own* agent into Cicada's consolidation
engine. Recall is already local/free; this makes the *write* path key-free too — the agent the user
already pays for does the extraction and summarization, writing through the MCP.

### What the agent can already do (shipped)
- `cicada_save_episode(content, title)` — stage a raw episode (`processed: false`, `origin: mcp`).
- `cicada_save_url(url, note)` — save a link as a `media` entity.
- `cicada_sources(entity_id)` — read the primary conversation chunks behind an entity (grounding).
- `/watch <url> <question>` (the `claude-video` skill) — download + frame + transcribe a video.

### The one new primitive: `cicada_write_claim`
Today the agent can only *stage* episodes; turning them into structured memory still needs the batch
LLM. The gap: let the agent **write claims directly**, reusing the deterministic claim layer built
for the retrieval work (`claims.write_claims` + `claim_reconciler.reconcile_stage3`).

```
cicada_write_claim(subject, predicate, object, *, observer, confidence,
                   context="general", source_episode=None, object_kind="node")
```
- Writes a `Claim` into the subject entity's ` ```claims ` block (creating the page if needed).
- **`observer` is the load-bearing field:** the agent tags each claim as `rodrigo` (the user
  *stated* this) vs `agent` (the agent *inferred* it) vs `external:<name>`. This is what finally
  gives the graph real observer diversity — the "All/Rodrigo/Cicada/External" filter becomes
  meaningful (it's currently inert because every claim is `agent`).
- The existing **Stage-3 reconciler** runs on write: trust-gated dedup/supersession, never lets an
  agent claim overwrite a human-stated one, decay untouched. So the agent gets latitude to write
  rich content; the deterministic layer keeps the structure guarantees. (This is exactly the G10
  "hybrid" recommendation — agent does rich extraction; the pipeline owns dedup/contradiction/decay.)
- A batch convenience `cicada_consolidate(episode_ids?)` wraps it: the agent reads unprocessed
  episodes (`cicada_sources`-style), extracts entities+claims, writes them, marks episodes processed.

### The skill's policy (`SKILL.md`)
Tells the agent: **when** to consolidate (end of a session, on request, after `/watch`), **how** to
tag observers (user-asserted → `rodrigo`; agent-inferred → `agent`), to keep summaries rich but
strictly grounded in the episode/transcript, and to route a video through `/watch` → `cicada_save_url`
(+ transcript as source of truth) → `cicada_write_claim` for the "recommends / is about" edges.

### The local-LLM fallback (the "Both" Rodrigo chose)
Wire **Ollama** as a consolidation backend in `providers.py` (a third branch beside litellm/OpenRouter):
`CICADA_LLM_MODE=agent|byok|local`. In `local` mode the nightly deterministic Sleep cycle runs with
no key (lower extraction quality, fully offline). So three tiers, user picks:
- **agent** (default, best): your agent consolidates via the skill — no key, frontier quality.
- **byok**: OpenRouter/OpenAI key drives the deterministic nightly batch.
- **local**: Ollama, offline, no key.

### Why this is the keystone
No separate key, frontier-quality summaries (answers the "how are summary boxes written" concern —
a good model writes them, for free to us), and it populates the observer/claim data that the graph
and `cicada_get_perspective` were built for.

---

## Part 2 — Ingestion: import page **and** sync queue (one queue underneath)

Rodrigo's question: an "Import bookmarks/videos" page with per-source icons, **or** an app-sync
queue that the Sleep cycle drains? **Answer: both — they're two producers feeding one queue.**

### The unifying model (matches R6 "connectors as episode emitters")
```
producers ─────────────►  ONE QUEUE  ─────────►  ONE CONSUMER
                          episodes/ (+ sources/)   the Sleep cycle
                          processed:false, origin  (drains + consolidates)
```
Everything captured — any route — lands as a staged item (`origin` = where it came from). The Sleep
cycle is the single consumer; **zero new Sleep code** per R6. Dedup is by content-hash + url-hash
(already built).

### Producer A — the **Import page** (manual, one-off) — the icons
A proper "Sources / Import" page (grows out of today's `UploadOverlay`), a grid of source tiles:
**Chat exports** (Claude/ChatGPT/Gemini), **Chrome bookmarks**, **Safari bookmarks**, **RSS feed**,
**YouTube / video**, **paste a URL**. Click a tile → pick a file / paste → it stages into the queue.
Best for bulk one-off pulls (a bookmarks export, a conversation export). Parsers already exist:
Netscape/Chrome (M4), Safari plist (G30), RSS (M4), media/OG (M4).

### Producer B — **Sync connectors** (ongoing, per-app) — the queue
For sources that *change over time*, a connector emits new items on a schedule instead of a manual
re-import. Which apps support true sync vs. import-only:

| Source | Sync? | How |
|---|---|---|
| **Chrome bookmarks** | ✅ sync | poll the local `Bookmarks` JSON, diff since last sync, emit new — keyless, local |
| **Safari bookmarks** | ✅ sync | poll `~/Library/Safari/Bookmarks.plist` (G30 parser), diff, emit — keyless, local |
| **RSS** | ✅ sync | poll the feed URL (M4) |
| **YouTube / video** | ✅ via skill | `/watch` → agent saves → emits (Part 1) |
| **Telegram** | ✅ sync | a bot receives forwarded messages → emits; **needs the user's bot token** |
| **macOS/iOS Share-sheet** | ✅ push | "Share to Cicada" → emits an item |
| **Chat exports** | ❌ import-only | no live API; manual export file (delta-dedup on re-upload already works, G20) |
| **WhatsApp** | ⚠️ hard | no clean personal API; realistic path = forward-to-a-Shortcut that hits the same ingest endpoint, or defer |

### Producer C — the **MCP save tools** (agent-driven)
`cicada_save_url` / `cicada_save_episode` / the video chain already emit into the queue.

### The app surface — a "Capture" page that shows BOTH
- **Top:** the import tiles (Producer A).
- **Below:** **connected sources + the pending queue** — "Chrome: 3 new bookmarks since last sync",
  "Telegram: connected", "12 items queued for the next Sleep cycle", with a "consolidate now" button
  (runs Sleep / triggers the agent skill). This makes the queue visible and the sync status honest.

### Origin provenance (G9, folds in here)
Every staged item carries `origin` (chrome-bookmark / safari-bookmark / telegram / share-sheet /
claude-code / …). Propagated episode → entity → claim, and surfaced in a contributors-style
"where did this come from" filter. Distinct from the M3 `Cicada-Author` (which *model* wrote it).

---

## Build order (proposed)
1. **`cicada_write_claim` MCP tool** (+ `cicada_consolidate` batch) — the keystone; reuses claims +
   reconciler. Unlocks the agentic path AND observer diversity. **TDD, hermetic.**
2. **`SKILL.md`** for the Cicada consolidation/capture skill (policy + the `/watch` chain).
3. **Ollama local backend** in `providers.py` (the `local` mode).
4. **Import page** (Producer A) — the source-icon grid in the app (grows `UploadOverlay`).
5. **Sync connectors** (Producer B): Chrome/Safari local-file poll first (keyless), then Telegram
   (needs token), then share-sheet. Each is a thin emitter; the Sleep cycle already drains.
6. **Capture page** queue view + origin filter.

Steps 1–3 are the "no key, plug-and-play" core; 4–6 are the ingestion UX.
