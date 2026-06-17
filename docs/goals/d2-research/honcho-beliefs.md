# Honcho: beliefs & (observer, observed) representations

## TL;DR

- Honcho's fundamental primitive is the **peer** (human, agent, project, idea) — not a document or conversation chunk. Every reasoned output is scoped to a specific `(observer, observed)` peer pair, enabling perspective-relative memory that genuinely differs per observer.
- Memory formation is **reasoning at ingest time**, not retrieval at query time: a fine-tuned model (Neuromancer XR, Qwen3-8B) extracts **atomic, logically-typed conclusions** (explicit → deductive → inductive → abductive) as messages arrive, building a DAG of premises and inferences rather than a flat fact store.
- The **dialectic** endpoint lets an agent ask a natural-language question about any peer and get a synthesized, reasoning-grounded answer — it is not a vector similarity search but an agentic research pass over stored conclusions.
- Async **dreaming** (DeductionSpecialist + InductionSpecialist) runs background consolidation: compresses redundant conclusions, derives cross-session patterns, and updates compressed **peer cards** — the closest analogue to Cicada's entity pages.
- Honcho achieves 90.4% on LongMem S and 89.9% on LoCoMo benchmarks against Claude Haiku's 62.6% on full context — the gains are real and attributable to the reasoning layer, not just retrieval improvements.
- The system is **opaque and infrastructure-heavy** (PostgreSQL/pgvector + Redis + hosted LLM calls) and has **no explicit belief invalidation mechanism** — contradictions are detected during dreaming's consolidation pass but the resolution strategy is not publicly specified.

---

## Findings

### The peer paradigm

In Honcho, the atom of identity is a **peer** — any entity that can send or receive messages: a human user, an AI agent, an NPC, a project, a brand, even an abstract idea. Peers participate in **sessions** (conversations) with a many-to-many relationship; a session can have multiple peers, a peer can span sessions. The root container is a **workspace**.

Source: [GitHub — plastic-labs/honcho](https://github.com/plastic-labs/honcho), [Honcho CLAUDE.md](https://github.com/plastic-labs/honcho/blob/main/CLAUDE.md)

### (observer, observed) collections

This is Honcho's most distinctive structural choice. Internal vector storage is keyed by composite `(observer_peer_id, observed_peer_id)` pairs. Each such pair owns a separate **collection** of embedded conclusion documents. Two consequences:

1. **Self-representation**: `observer == observed` gives a peer's model of itself — its own preferences, patterns, identity.
2. **Cross-peer modeling**: `observer = agent`, `observed = user` gives the agent's belief-state about the user. If two different agents observe the same user in different sessions, they hold **different representations** of that user — there is no single ground-truth user profile, only perspective-local belief sets.

The public API surface names these **conclusions**; earlier code and some docs still say **observations** (a terminology rename in v3).

Two session-level toggles control scope:
- `observe_me` (default ON): a peer's representation is updated from all of its messages across all sessions.
- `observe_others` (session-level): a peer only forms a representation of other peers based on messages it directly witnessed in that session — preventing omniscient agents.

Source: [Honcho CLAUDE.md](https://github.com/plastic-labs/honcho/blob/main/CLAUDE.md), [Peer Representations — honcho.dev](https://honcho.dev/docs/v3/documentation/core-concepts/representation), [DeepWiki — plastic-labs/honcho](https://deepwiki.com/plastic-labs/honcho)

### Conclusion types and logical scaffolding

Honcho enforces a **certainty hierarchy** — lower-certainty conclusions cannot serve as premises for higher-certainty ones:

| Type | Definition | Current status |
|------|------------|----------------|
| Explicit | Directly stated by a participant | Implemented |
| Deductive | Necessarily follows from explicit premises with certainty | Implemented |
| Inductive | Patterns across multiple messages/sessions | Planned |
| Abductive | Simplest explanation for observed behavior | Planned |

Each conclusion is **atomic** (self-contained, independently understandable, concise), and each deductive conclusion carries its premises as metadata, forming a **reasoning chain DAG** queryable via `get_reasoning_chain`. Neuromancer XR (Qwen3-8B fine-tuned on reasoning traces) does the extraction in a single structured-output LLM call per batch — not an agentic loop.

```json
{
  "explicit": [{"content": "User prefers Python for scripting tasks"}],
  "deductive": [{
    "premises": ["User prefers Python for scripting tasks"],
    "conclusion": "When given a scripting task, user will likely default to Python unless told otherwise"
  }]
}
```

Source: [Honcho Reasoning — honcho.dev](https://honcho.dev/docs/v3/documentation/core-concepts/reasoning), [Introducing Neuromancer XR — plasticlabs.ai](https://plasticlabs.ai/blog/research/Introducing-Neuromancer-XR)

### The deriver (ingest-time memory formation)

When messages arrive (batched, up to ~16K tokens), the **Deriver** worker processes them:
1. Enqueues a `QueueItem` per peer (serial per peer to prevent race conditions).
2. Calls Neuromancer XR with custom instructions (per-workspace and per-peer configurable, capped at 2000 tokens).
3. Saves explicit + deductive conclusions as embedded documents in the `(observer, observed)` collection.
4. Updates session summaries at 20-message and 60-message intervals.

This is synchronous from the message's point of view: write a message, conclusions are queued immediately. The queue ensures ordering but processing is async relative to the API response.

Source: [Honcho CLAUDE.md](https://github.com/plastic-labs/honcho/blob/main/CLAUDE.md), [DeepWiki — plastic-labs/honcho](https://deepwiki.com/plastic-labs/honcho)

### Dreaming (async background consolidation)

The **Dreamer** is a multi-specialist background process analogous to Cicada's Sleep cycle:

- **DeductionSpecialist**: reads accumulated explicit conclusions and derives new deductive ones across sessions.
- **InductionSpecialist**: reads explicit + deductive conclusions and identifies inductive patterns (recurring behavior, preferences, long-range correlations).
- **Consolidation**: identifies redundant or contradictory conclusions — the closest thing to conflict resolution in Honcho.

Dreams are triggered on a schedule (DreamScheduler) or explicitly queued, with **surprisal-based prioritization** — peers whose recent messages diverge most from their prior representation get dreamed about sooner. The outputs are new conclusions added to the same `(observer, observed)` collections and updates to the **peer card** (a compressed biographical summary: identity, profession, core interests — a stable low-latency anchor that prevents context drift across long sessions).

Honcho does **not** document an explicit belief invalidation or retraction mechanism. Contradictions surface during consolidation, but how they are resolved (overwrite? archive? flag?) is not publicly specified.

Source: [DeepWiki — plastic-labs/honcho](https://deepwiki.com/plastic-labs/honcho), [Honcho CLAUDE.md](https://github.com/plastic-labs/honcho/blob/main/CLAUDE.md), [Honcho Reasoning](https://honcho.dev/docs/v3/documentation/core-concepts/reasoning)

### The dialectic (query interface)

The **dialectic** is Honcho's answer to "how does an agent ask about a peer?" It is not a similarity search — it is an **agentic research pass** that runs synchronously (SSE streaming) at query time. The agent calls `peer.chat("What kind of tasks does this user prefer?")` and the dialectic agent uses a toolset that includes:

- `search_memory` — hybrid BM25 + vector over conclusions
- `search_messages` — full-text over raw messages
- `get_observation_context` — fetch the full `(observer, observed)` collection context
- `grep_messages`, `get_messages_by_date_range`, `search_messages_temporal` — temporal and structural retrieval
- `get_reasoning_chain` — traverse the premise DAG of a conclusion

The reasoning tier (minimal → max) controls which tools are available and which LLM provider is used per tier, allowing cost/quality tradeoffs. At `max` tier, all tools are available and a stronger model is used; at `minimal` tier, only `search_memory` + `search_messages` are available.

Source: [Honcho CLAUDE.md](https://github.com/plastic-labs/honcho/blob/main/CLAUDE.md), [DeepWiki — plastic-labs/honcho](https://deepwiki.com/plastic-labs/honcho), [Agent Memory Providers Compared — glukhov.org](https://www.glukhov.org/ai-systems/memory/agent-memory-providers/)

### Benchmark performance

| Benchmark | Honcho | Claude Haiku (full context) |
|-----------|--------|-----------------------------|
| LongMem S | 90.4% (92.6% with Gemini 3 Pro) | 62.6% |
| LoCoMo | 89.9% (Neuromancer XR alone: 86.9%) | ~80% (Claude 4 Sonnet baseline) |

The gains are attributed to the reasoning layer genuinely improving model understanding, not just reducing context window pressure. Neuromancer XR outperforms its base model (Qwen3-8B: 69.6%) and Claude 4 Sonnet (80.0%) on LoCoMo, suggesting the fine-tuning on reasoning traces is load-bearing, not just architectural theater.

Source: [Benchmarking Honcho — plasticlabs.ai](https://plasticlabs.ai/blog/research/Benchmarking-Honcho), [Introducing Neuromancer XR](https://plasticlabs.ai/blog/research/Introducing-Neuromancer-XR)

---

## Concrete data-model ideas for Cicada

Honcho's architecture suggests several concrete adaptations for Cicada's markdown+git+sqlite-vec substrate:

### 1. Perspective-relative belief scoping as frontmatter

Currently Cicada has one entity page per entity with a flat confidence score. Honcho suggests that beliefs about an entity should be **scoped to an observer**. For Cicada's single-user context this maps naturally to **contexts/facets**: instead of one flat belief set, each entity page can have per-context belief sections or separate context-overlays (e.g., a `contexts:` frontmatter key mapping context names to confidence/notes).

```yaml
# entities/machine-learning.md
contexts:
  engineer-self:
    confidence: 0.92
    notes: "actively uses PyTorch, follows arxiv"
  life-philosophy:
    confidence: 0.45
    notes: "questions whether ML optimization is the right frame for personal growth"
```

This directly addresses Rodrigo's intuition about holding different beliefs about the same thing depending on context.

### 2. Typed conclusion units instead of or alongside entity pages

Rather than (or layered beneath) entity pages, Cicada could maintain a **conclusions table in sqlite-vec** keyed by `(observer_context, subject_entity_id, conclusion_type)`. Each row is an atomic, self-contained claim with premises stored as foreign keys. This enables:
- Reasoning chain traversal via SQL joins
- Type-filtered retrieval (give me only deductive conclusions about X)
- Contradiction detection via consolidation queries
- Dreaming as a SQL+LLM batch that reads existing conclusions and adds derived ones

Entity pages become **materialized views** — generated summaries of the underlying conclusions table, similar to Honcho's peer cards. The markdown stays human-readable and git-versioned; the sqlite-vec table is the queryable reasoning substrate.

### 3. Surprisal-based Sleep scheduling

Honcho's surprisal-based dream prioritization is directly applicable: entities whose recent episodes diverge most from their current entity page (measured by embedding distance) get prioritized in the next Sleep cycle. This avoids wasting LLM budget re-consolidating stable entities and focuses attention on genuinely changing beliefs.

### 4. Atomic conclusions with premise links for provenance

Instead of (or in addition to) `source_episodes` in frontmatter, individual claims within an entity page could carry their logical type (explicit/deductive) and premises as inline metadata. This makes the entity page itself a reasoning chain, not just a summary, enabling the `/ask` endpoint to surface *why* it believes something, not just *what* it believes.

### 5. Peer card as the entity page, conclusions as the backing store

Honcho's architecture suggests an architectural inversion for Cicada: the entity page becomes the **peer card** (compressed, stable, low-latency summary of who/what this entity is), while the detailed belief claims live in the sqlite-vec conclusions table. The Sleep cycle writes both. The `/ask` endpoint uses the full conclusions table for reasoning depth; the app displays entity pages for human readability.

---

## Tradeoffs / where it fails

**Infrastructure lock-in**: Honcho requires PostgreSQL/pgvector + Redis + hosted LLM inference. Not usable fully offline or without ongoing LLM API costs. Cicada's local sqlite-vec + local embedding model is a genuinely different tradeoff — more portable, zero marginal cost per inference, but weaker reasoning capability unless augmented with a capable model.

**No explicit invalidation**: When a belief is contradicted by new evidence, Honcho's consolidation pass detects it but the resolution strategy is undocumented. For Cicada, where Rodrigo explicitly cares about temporal change (e.g., switching from Postgres to SQLite), this is a gap that needs filling beyond what Honcho offers. Cicada's git versioning gives a head start here — every belief change is a diff.

**Closed source for the key model**: Neuromancer XR is a fine-tuned Qwen3-8B, not publicly available as weights. Cicada cannot directly use it; the architecture can be replicated but the training data and fine-tuning are Plastic Labs IP. The vanilla Qwen3-8B gets 69.6% vs Neuromancer XR's 86.9% on LoCoMo — a large gap attributable to fine-tuning, not just architecture.

**Peer model assumes social multi-agent context**: The `(observer, observed)` design shines in multi-agent or multi-user scenarios. For a single-user personal memory system, "observer" is almost always the same (Rodrigo's agent stack), so the peer dimension collapses to context/facet distinctions — which is still useful but requires reframing the abstraction.

**No open-ended entity types**: Honcho's peer concept is deliberately broad but still implicitly assumes entity-like primitives. It doesn't solve the problem of capturing open questions, evolving problems, or procedural workflows as first-class knowledge units — Cicada's taxonomy problem applies equally here.

**Hype flag**: The benchmark claims are real (methodology published) but LongMem and LoCoMo measure long-context recall of stated facts, not the harder problem of inferring implicit beliefs or handling genuine temporal contradictions across months. The system performs well on what is measured; the gap between benchmark performance and production personal-memory quality is unknown and likely significant.

---

## Open questions

1. **What is the actual storage format of a conclusion?** The JSON schema shown in docs has `content` and `premises` fields, but what are the embedding dimensions, indexing strategy, and retrieval scoring for conclusions vs. raw messages in hybrid search? The code in `src/llm/` is not publicly documented in sufficient detail.

2. **How does consolidation resolve contradictions?** Is the newer conclusion preferred? Is the higher-certainty one preferred? Is a "both are true in different contexts" resolution possible? This is the critical missing piece for temporal belief change.

3. **Can the dreaming specialists be run locally?** The DeductionSpecialist and InductionSpecialist use configurable LLM providers — is a local Qwen3-8B or Gemma3 sufficient for the deduction pass, or does quality degrade severely below GPT-4-class models?

4. **What is the latency profile of the dialectic at `max` tier?** If it runs a multi-tool agentic loop synchronously per query, p99 latency for complex peer queries could be seconds, which affects whether it's viable inside a fast agent turn.

5. **How does Honcho handle procedural/preference memory differently from factual memory?** The benchmark results are on factual recall (LongMem, LoCoMo). Procedural memory ("Rodrigo prefers FastAPI structured this way") may require different conclusion types or retrieval strategies — it's not clear that the current explicit/deductive hierarchy captures procedural knowledge well.

6. **If Cicada adopts a conclusions table alongside entity pages, what is the migration path from 1,882 existing entity pages?** The entity pages could be imported as explicit conclusions (source: `legacy_entity_page`), but this would require extracting atomic claims from existing markdown bodies, which itself is a Sleep-cycle-class LLM job.
