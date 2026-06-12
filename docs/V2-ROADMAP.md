# Cicada v2 — Roadmap

**Branch:** `feat/v2-revamp` · **Date:** 2026-06-12

v2 turns Cicada from a thesis prototype into a plug-and-play second-brain memory layer that is friendly to **both** agents (small LLMs traverse it via files; LEANN handles fuzzy recall) and users (one inbox, a meaningful graph, a menu-bar bookworm companion).

Full implementation-ready specs live in [`docs/design/`](design/). This document is the map.

---

## Why v2 (what the audit found)

A six-agent audit of every subsystem (June 2026) converged on five structural problems:

1. **Entity pages are critically thin.** Median body ≈ 50 words; only ~22% have any section; 4 of 1882 entities capture a URL. Retrieval surfaces frontmatter-level signal, not knowledge.
2. **The graph is flat.** No hub/abstract tier (no "Contacts", no topic clusters). 1882 leaves, 4571 edges, no navigational entry point — for the d3 view *or* for a small LLM.
3. **Wikilinks are decorative.** They appear in 681 entity bodies but no code ever parses or traverses them. Two competing edge sources exist (`graph_edges.yaml` vs `related` frontmatter).
4. **Two inboxes, one job.** Nudges and clarifications are near-identical list/resolve systems; `NudgeType.clarification` is dead code; all 39 live nudges are decay-type. Users face two badges with no mental model for the split.
5. **Nothing is plug-and-play.** Manual venv setup, hand-edited MCP config with `/path/to/cicada` placeholders, hardcoded OpenAI embeddings, no installer, no launchd, the menu-bar state machine never receives a single update call.

Plus concrete bugs: clarification answers in the nudge card were silently sent as `archive`; nudge IDs collide after resolutions (count-based numbering); resolution commits are invisible in sleep history; conflict answers are appended as raw paragraphs.

## The v2 shape

```
memory/
├── _index.md            ← map-of-content: cold-start entry point for ANY agent
├── hubs/                ← persisted hub pages (type hubs + tag-cluster topic hubs)
│   ├── people.md           regenerated each sleep cycle, zero LLM cost
│   └── ...                 members listed in BODY (markdown) + frontmatter (API)
├── entities/            ← v2 layout: ## Summary / Key Facts / History / Related / Links / Open Questions
├── episodes/            ← unchanged; media saves become episodes too (source: bookmark|youtube|…)
├── sources/             ← url_index.json dedup for saved media
├── inbox/               ← ONE queue replacing nudges/ + clarifications/
│   └── inbox-NNN.md        kind: decay|conflict|clarification|merge_suggestion
│                           required_input: none|choice|freetext|merge
└── leann/               ← unchanged; embeddings configurable (openai|local)
```

**Traversal story for a small LLM:** `_index.md` → `hubs/<hub>.md` → `entities/<id>.md` → `episodes/<ep>.md`. Each level is one cheap file read. LEANN remains the fuzzy entry point; the MCP `cicada_recall` adds a machine-parseable `cicada-hints` JSON block (suggested next entities + relevant hub) so models that ignore prose still navigate.

## The six axes (specs)

| Axis | Spec | Core decisions |
|------|------|----------------|
| Unified inbox | [`unified-inbox.md`](design/unified-inbox.md) | One `memory/inbox/` store, `kind` + `required_input` discriminators, `GET /inbox` + `POST /inbox/{id}/resolve`, legacy endpoints as deprecated shims, idempotent startup migration (move + scoped commit + marker), `GET /status` aggregate for the avatar. Fixes ID-collision, raw-append, and invisible-commit bugs. |
| Hubs + traversal | [`hubs-and-traversal.md`](design/hubs-and-traversal.md) | Persisted `memory/hubs/` pages (8 type hubs + ≤30 tag-cluster hubs), regenerated per cycle without LLM calls; root `_index.md`; wikilinks materialized as `mentions` edges; `graph_edges.yaml` becomes the single canonical edge source; `hub` is a render/file concept, **not** a 9th entity type; tolerant `resolve_entity_file` for 181 legacy filenames. |
| Entity pages v2 | [`entity-pages-v2.md`](design/entity-pages-v2.md) | Fixed section grammar owned by `api/services/entity_body.py`; extraction/synthesis prompts rewritten (richness raised, URL capture mandatory); section-aware merge replaces raw appends; lazy migration (`layout_version: 2`) + optional two-tier backfill (structural = free, enrich ≈ $1 for all 1882). |
| Media ingestion | [`media-ingestion.md`](design/media-ingestion.md) | `POST /sources/upload` (Netscape bookmarks HTML, Chrome JSON, Takeout watch-later, URL lists) + `POST /sources/save` (single URL; share-sheet/MCP path); Open Graph + YouTube oEmbed enrichment, keyless, offline-safe, no login scraping; dual write = episode (sleep extracts from it) + first-class `media` entity (deliberate save ⇒ skips promotion gate); URL-hash dedup; edges injected by joining on shared `source_episodes` so media connects even when fresh concepts don't cross the promotion threshold. |
| Graph viz | [`graph-viz-redesign.md`](design/graph-viz-redesign.md) | Ego/focus mode (double-click = ≤2-hop neighborhood, ESC restores); hub-anchored layout; three-tier semantic zoom (hub labels → big-node labels → all + edge labels); one channel per attribute (hue=type, size=confidence, opacity=status, pulse=pending, ring=hub); incremental updates preserve positions (fixes post-sleep layout explosion); mtime-cached `build_graph` + server-side `degree`/`is_hub`/`has_pending`. |
| Companion + install | [`companion-and-install.md`](design/companion-and-install.md) | Menu-bar bookworm tamagotchi: sprites as code-defined pixel grids (from `app/assets/book_worm.png`) rendered as template NSImages; states awake/sleeping(+stage dots)/digesting/hungry/curious(+badge)/happy with pure `deriveBookwormState` precedence; 30s `/status` poll + 1s during cycles; idempotent `install.sh` (memory scaffold, launchd, `claude mcp add`, doctor checks); `CICADA_EMBEDDING_MODE=openai|local` (sentence-transformers fallback) so install works without an OpenAI key; `SKILL.md` for Claude-skill distribution. |

## Locked cross-axis contracts

- `GET /status` emits the nested shape defined in `companion-and-install.md`; `avatar_state` is derived client-side.
- Python `EntityType` gains exactly one new value: `media`. `GraphNode.type` widens to `str` (accepts `hub`). Swift `EntityType` gains `media`, `hub`, and a decode-tolerant `unknown` (unknown values must never blank the graph).
- Inbox `kind ∈ {decay, conflict, clarification, merge_suggestion}`, `required_input ∈ {none, choice, freetext, merge}`. Future `media_suggestion` is one enum value + one dispatcher branch.
- Hub member lists exist twice by design: frontmatter (for `graph_builder`, parsed with pyyaml) and body markdown (for MCP/small LLMs, no nested-YAML parsing required).
- Colors: `media` #EC4899; `hub` rendered as ringed gold anchor.

## Implementation plan (waves, strict file ownership)

| Wave | Workstreams | Status |
|------|-------------|--------|
| 1 | Python unified inbox + `/status` · d3 graph redesign · Swift menu-bar tamagotchi | in progress |
| 2 | Python hubs + traversal (+ `/search`, `/entities/{id}/context`) · Swift inbox UI + EntityType fix + filter unification | pending |
| 3 | Python media ingestion · Python entity pages v2 | pending |
| 4 | install.sh + doctor + launchd + embedding fallback + SKILL.md · full verification | pending |

## Deferred (post-v2)

- Temporal graph playback (scrub git history; uniquely enabled by git-as-database).
- Instagram authenticated ingestion (no standard export; URL-list path ships in v2).
- Inbox `media_suggestion` items ("I connected your saved video to project X — confirm?").
- Skill evolution pass (skills currently never update once created — spec'd but lower priority).
- `.dmg` packaging with embedded Python runtime; Tauri/single-binary exploration.
- SSE stream for `/sleep/status` (poll is fine at current scale).

## Out of scope, by decision

- Neo4j/database migration — filesystem-as-truth stays; it is the thesis position and it works at personal scale.
- Real-time consolidation — batch sleep cycles remain.
- Multi-user anything.
