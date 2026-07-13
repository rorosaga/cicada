# mem0 / cognee / Letta(MemGPT): production agent-memory frameworks

_Researched June 2026. Sources linked inline._

---

## TL;DR

- **Mem0** converged on "ADD-only" single-pass extraction (v3, 2026): every new fact is appended alongside the old one rather than overwriting it. Contradiction is resolved at _read_ time (recency wins) not write time. This is a reversal of their prior ADD/UPDATE/DELETE design and is the biggest practical lesson from two years of production.
- **Cognee** is the most structurally ambitious: every knowledge unit is a versioned, typed Pydantic `DataPoint` with a deterministic UUID, stored simultaneously in graph (Kuzu/Neo4j), vector (LanceDB/Qdrant), and relational (SQLite/Postgres) stores. The `cognify` pipeline is the closest thing to Cicada's Sleep cycle in the wild.
- **Letta** (ex-MemGPT) puts the agent in control of its own memory via explicit tool calls (`core_memory_replace`, `archival_memory_insert`). OS-inspired: core = RAM (in-context), recall = cache (conversation log), archival = disk (vector store). The agent is the consolidator.
- All three converged on the same three-tier cognitive taxonomy: **working / episodic / semantic** (they just name the tiers differently).
- **Procedural memory is the unresolved gap** across all three: none has a well-designed "how Rodrigo likes things done" layer. It is either bolted on as freeform text in core-memory blocks (Letta) or absent entirely (Mem0, Cognee).
- Temporal validity and contradiction at scale remain unsolved. Mem0 acknowledged this explicitly in their 2026 state-of-memory report. Cognee's temporal feature is newer and unproven. Letta leaves it to agent logic.

---

## Findings

### mem0

**Architecture overview**  
[mem0 paper (arXiv 2504.19413)](https://arxiv.org/html/2504.19413v1) | [token-efficient algorithm blog](https://mem0.ai/blog/mem0-the-token-efficient-memory-algorithm) | [state-of-memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)

Mem0 stores memories as **natural-language text facts** in a vector database (20 backends supported). The core data model is:

```
Memory {
  id:          UUID
  memory:      string          # the extracted fact, NL
  created_at:  timestamp
  updated_at:  timestamp
  user_id:     string          # scope key
  agent_id:    string          # scope key (optional)
  run_id:      string          # session scope (optional)
  metadata:    dict            # freeform, e.g. {"context": "healthcare"}
}
```

Scopes compose: `user_id + agent_id + run_id` give you user-level, agent-level, or session-level isolation and retrieval.

**Fact extraction: the v2 → v3 reversal**

_v2 (2024):_ Two LLM passes. Pass 1 extracts candidate facts. Pass 2 reconciles candidates against the top-10 nearest existing memories and decides ADD / UPDATE / DELETE / NOOP for each. This is clean but caused information loss: UPDATE overwrote details, DELETE discarded valid history.

_v3 (2026, current):_ Single-pass ADD-only. Every extracted fact is appended as an independent record. Old facts survive. The system relies on `created_at` timestamps + retrieval-time recency ranking to surface the most current value. Contradictions are preserved in the store; the LLM reading the retrieved context resolves them.

**Why this matters:** it is a pragmatic admission that write-time reconciliation is fragile. The complexity was moved to retrieval, where the LLM is more capable of nuanced judgment than a fixed algorithm.

**Retrieval: multi-signal fusion**  
Three parallel passes, scores fused:
1. Semantic similarity (vector embedding distance)
2. BM25 keyword matching
3. Entity matching (query entities vs `{collection}_entities` index)

This yielded +29.6 points on temporal queries and +23.1 on multi-hop reasoning vs v2 (LoCoMo / LongMemEval benchmarks).

**Graph variant: Mem0^g**  
Graph structure `G = (V, E, L)`:
- Nodes `V`: entities with type, embedding, creation timestamp
- Edges `E`: typed relationships as triplets `(source, relation, destination)`
- Labels `L`: semantic types (Person, Location, Event, ...)

Conflict detection marks obsolete relationships as **invalid** rather than deleting them — same ADD-only philosophy applied to the graph. Retrieval uses dual strategy: entity-centric (expand from matched entities) + semantic triplet (embed query, match triplets by cosine). Overhead: ~14k tokens per conversation vs ~7k for flat Mem0. Dropped external Neo4j/Kuzu in v3 in favor of built-in entity linking; traversable graph API removed.

**Production stats:** ~48,000 GitHub stars, $24M Series A (Oct 2025), AWS Agent SDK exclusive memory provider, SOC 2 Type II. Token cost per conversation: ~7k tokens (v3 flat), ~14k (graph variant).

---

### cognee

**Architecture overview**  
[cognee.ai architecture blog](https://www.cognee.ai/blog/fundamentals/how-cognee-builds-ai-memory) | [DataPoints docs](https://docs.cognee.ai/core-concepts/building-blocks/datapoints) | [GitHub](https://github.com/topoteretes/cognee)

Cognee is the most structurally opinionated of the three. The fundamental unit is the **DataPoint** — a versioned, typed Pydantic model that simultaneously describes a graph node, its vector embeddings, and its relational metadata.

**DataPoint schema:**

```python
class DataPoint(BaseModel):
    id:              UUID           # deterministic (UUID5) from identity_fields
    created_at:      int            # epoch ms
    updated_at:      int            # epoch ms
    version:         int            # starts at 1, incremented manually
    topological_rank: Optional[int] # dependency ordering
    metadata:        dict           # includes index_fields list
    type:            str            # Python class name ("Person", "Project", ...)
    belongs_to_set:  Optional[list] # group membership

# Example subclass:
class Person(DataPoint):
    name:        str   # in metadata.index_fields → gets embedded
    role:        str
    company:     Optional[Company]          # typed reference → graph edge
    projects:    list[Project]              # list ref → multiple edges
    notes:       (Edge(weight=0.8), str)    # weighted edge
```

Relationships are typed references on the class; Cognee converts them to graph edges automatically. The `metadata.index_fields` list controls which fields get vectorized — non-indexed fields live only in graph and relational stores.

**Storage: poly-store hybrid**
- Graph store (default: Kuzu; swappable to Neo4j, FalkorDB, Memgraph, Neptune)
- Vector store (default: LanceDB; swappable to Qdrant, pgvector, Redis, Chroma, DuckDB, Pinecone)
- Relational store (default: SQLite; scales to Postgres) — tracks documents, chunks, provenance

Every graph node has a corresponding embedding. Movement between semantic search and relational traversal is seamless.

**The cognify pipeline (6 stages):**
1. Classify documents
2. Check permissions
3. Extract chunks
4. LLM extracts entities + relationships → DataPoints
5. Generate summaries
6. Embed + commit to graph

Only new/changed files reprocess (content hashing). This is structurally similar to Cicada's Sleep cycle.

**Versioning and update:**
The update pattern is manual:
```python
entity.name = "New Name"
entity.update_version()     # version += 1, updated_at = now()
await add_data_points([entity])   # upserts all three stores
```
No automatic conflict detection. Stale nodes are pruned by the **Memify** background pass: prune stale nodes, strengthen frequent connections, reweight edges by usage, add derived facts. This is the closest thing in production to Cicada's temporal decay.

**Memory tiers:**
- Session memory: short-term working context, pronoun resolution across turns
- Permanent memory: long-term knowledge, interaction traces, external docs, relationships

**Production stats:** ~7,000 GitHub stars, $7.5M seed, 70+ companies in production (2026), 500x pipeline volume growth in 2025 (2,000 → 1M+ runs). No SOC 2 / HIPAA. GitHub Secure Open Source program (2025).

---

### Letta (MemGPT)

**Architecture overview**  
[Letta vs Mem0 comparison](https://vectorize.io/articles/mem0-vs-letta) | [Letta docs (legacy MemGPT)](https://docs.letta.com/guides/legacy/memgpt-agents-legacy/) | [walkthrough](https://sureprompts.com/blog/letta-memgpt-walkthrough) | [MemGPT paper (arXiv 2310.08560)](https://arxiv.org/abs/2310.08560)

Letta's design philosophy is distinct: **the agent is the memory manager**. Rather than a framework extracting facts passively, the agent decides what to remember by calling explicit tool functions during its reasoning loop.

**Three-tier OS-inspired architecture:**

| Tier | Analogy | Characteristics |
|------|---------|-----------------|
| Core memory (memory blocks) | RAM | Always in context window; bounded; agent reads/writes directly |
| Recall memory | Disk cache | Full conversation history; searchable on demand via tool call |
| Archival memory | Cold storage | Vector-indexed; unlimited; queried via tool call |

**Memory block schema (core memory):**
Memory blocks are labeled persistent strings, typically a few hundred to ~2000 tokens each. Default blocks:
- `human`: what the agent knows about the user (preferences, name, role, history)
- `persona`: agent's self-description, behavior rules, standing instructions

Custom blocks are common for task state, project context, or procedural rules.

**Self-editing functions:**
```python
core_memory_append(label, content)           # add to named block
core_memory_replace(label, old_str, new_str) # overwrite span (for contradictions)
archival_memory_insert(content)              # push to long-term vector store
archival_memory_search(query)                # semantic retrieval from archival
conversation_search(query)                   # search recall (conversation log)
```

The agent calls these in its normal reasoning loop. When context grows too large, it compresses and moves content from core → archival, then retrieves when needed.

**Contradiction handling:** agent-implemented. `core_memory_replace` is the tool for correcting stale beliefs. No automated detection. Correctness depends on agent reasoning quality.

**Sleep-time compute:** Letta supports reflective background passes when no user message is pending — the agent consolidates, reorganizes, and updates memory unprompted. This is the most direct analog to Cicada's Sleep cycle, but it is LLM-driven autonomous behavior rather than a deterministic batch pipeline.

**Archival memory implementation:** vector index (BAAI/bge-small-en-v1.5 by default) with semantic retrieval. No graph structure — archival is a flat embedding store.

**Procedural memory in practice:** stored as freeform instructions in the `persona` block or a custom `preferences` block. Not a separate memory tier. Lacks formalism.

**Production stats:** $10M seed, UC Berkeley research backing, ~15,000 GitHub stars. Smaller community than Mem0. Enterprise pricing opaque (consultation required).

---

## Concrete data-model ideas for Cicada

These are _translations_ of what works in production onto the Cicada substrate (markdown + git + sqlite-vec).

**1. Drop the promotion gate; use a confidence-weighted belief store instead (from Mem0 v3)**  
Mem0's reversal from DELETE-on-contradiction to ADD-only is directly applicable. Rather than blocking entity creation until a second mention, create the entity page immediately with `confidence: 0.3` and `status: candidate`. Let confidence accumulate from recurrence. This eliminates the "first mention is lost" problem without polluting the graph with full-weight noise. The git version history is already the audit trail — no information is truly deleted.

**2. Typed DataPoint classes for entity pages (from Cognee)**  
Cognee's `DataPoint` subclass pattern maps cleanly to Cicada's YAML frontmatter: each entity type (`Person`, `Project`, `Tool`) is a schema with declared fields and declared `index_fields` (which fields get embedded in sqlite-vec). Relations are typed references, not just freeform wikilinks. This allows the Sleep cycle to emit structured JSON that maps 1:1 to the markdown frontmatter schema.

**3. Explicit belief units, not whole-entity pages (from Mem0 flat store)**  
Mem0 stores individual facts (`"Rodrigo prefers FastAPI over Flask"`) rather than entity-centric documents. For Cicada, this suggests a hybrid: keep entity pages for identity and relationship structure, but add a `beliefs/` subfolder with individual claim records (or a `claims:` list in the entity frontmatter). Each claim gets a `created_at`, `source_episode`, `confidence`, and `superseded_by` field for the ADD-only temporal pattern.

**4. Faceted/block-based identity for context-dependent self (from Letta)**  
Letta's labeled memory blocks — `human`, `persona`, custom blocks — suggest Cicada could model Rodrigo's multi-contextual self via **named facets** in the entity frontmatter rather than separate entity pages. For example, `entity/rodrigo.md` would have a `facets:` list: `[engineer, family, philosophy]` each with its own beliefs and confidence scores. Cross-facet links would be the "abstract connections between not-obviously-related things" he mentioned.

**5. Memify-style background graph refinement (from Cognee)**  
Cognee's `memify` operation (prune stale nodes, strengthen frequent connections, reweight by usage, add derived facts) maps to what Cicada's Sleep cycle stage 4 (Pattern Detection) should become. Instead of discrete stages, a continuous graph health pass that runs after extraction: strengthen edges by episode co-occurrence, decay confidence on unreferenced entities, surface derived relationships the LLM can validate.

**6. Procedural memory as first-class entities (gap identified in all three)**  
None of the production frameworks handle "how Rodrigo likes to do X" cleanly. The closest is Letta's `persona` block (freeform) and Mem0's skill-type entities. For Cicada: a dedicated `skill` entity type with `trigger_context`, `preferred_approach`, `examples: [ep_id, ...]`, and `confidence`. Retrieved by the agent when context matches `trigger_context`. Sleep cycle identifies candidates from recurrence patterns in episodes.

---

## Tradeoffs / where it fails

**Mem0**
- ADD-only is elegant but bloats the store over long-running users. At personal scale (years of data), retrieval context could become noisy without periodic pruning or explicit supersession markers.
- Dropped traversable graph API in v3. Multi-hop relational queries (which entity connects X to Y?) are no longer first-class — they require LLM inference over retrieved context, which is less reliable.
- No temporal validity windows. "Used to live in NYC" and "now lives in Madrid" both live as facts; recency ranking helps but is not a hard guarantee. Applications that need precise fact validity cannot rely on this.
- Scope model (user/agent/session) is flat. No concept of contextual facets or belief perspectives — all facts are equally "about the user."

**Cognee**
- Versioning is manual (`update_version()` + `add_data_points()`). The Sleep cycle writer must know to call this; no automatic dirty-tracking. Easy to create silent duplicates.
- Poly-store complexity: three databases must stay consistent. Failure in any one leaves the system in an inconsistent state. At Cicada's scale (solo dev, on-device), this is real operational risk.
- `memify` refinement is newer and less battle-tested. Pruning stale nodes is risky without a clear definition of staleness — Cicada's decay model is more principled.
- No built-in temporal reasoning beyond `created_at`/`updated_at`. The "Time Awareness" feature added in 2025 is documented but not publicly benchmarked.
- Self-hosted graph databases (Kuzu, Neo4j) add non-trivial operational overhead for a solo project.

**Letta**
- Agent-managed memory is powerful but non-deterministic. Consistency depends on the quality of the agent's reasoning each turn. Cicada's deterministic Sleep cycle batch is more auditable and replayable.
- Core memory blocks are size-bounded (~2k tokens). For a rich personal knowledge graph of ~1,882 entities, this approach does not scale — archival becomes the primary store and retrieval latency climbs.
- No graph structure at all. Multi-hop relational queries require round-trip archival searches. Relationships between entities are implicit in natural language, not structural.
- Sleep-time compute (background consolidation) is LLM-autonomous and expensive. Each consolidation pass costs full inference. Cicada's rule-based decay + LLM-only-where-needed is more cost-efficient.
- Recall memory (conversation log) gives raw episodes but no semantic consolidation. Episodic → semantic promotion requires explicit agent action, which can be forgotten or inconsistent.

**Shared failure across all three**
- Procedural memory is an afterthought everywhere. None has a principled "trigger → preferred approach → examples" schema.
- Contradiction handling at scale is unsolved. All three rely on LLM judgment at read-time after storing conflicting facts.
- Context-dependent identity (same person behaves differently across contexts) is not modeled by any framework. Letta blocks come closest but are freeform strings.

---

## Open questions

1. **Is the ADD-only pattern right for Cicada?** Mem0's shift away from DELETE is compelling, but Cicada's git history already provides the immutable record. Could Cicada be ADD-only at the Sleep cycle level while still having a "current canonical belief" in the markdown frontmatter (updated by the Sleep cycle) + full history in git? This gives both clean querying and full auditability without a bloating fact store.

2. **Should beliefs be a separate data layer from entities?** Mem0 stores facts orthogonally to entities; Cognee bakes facts into entity DataPoints; Letta keeps facts in natural language blocks. Cicada's markdown-page-per-entity model sits between Cognee and Letta. Worth exploring: add a `claims:` list to entity frontmatter (each claim = text + confidence + source_episode + created_at) without needing a separate beliefs/ folder.

3. **Cognee's `index_fields` pattern for sqlite-vec**: currently Cicada embeds full entity page text. Could adopting per-field embedding (name, summary, tags separately indexed) improve retrieval precision? Worth prototyping on the existing 1,882 pages.

4. **Letta's sleep-time compute vs Cicada's nightly batch**: should Cicada have a lighter "micro-Sleep" that runs after each conversation (cheap: just decay updates and pending-clarification checks) vs the full nightly LLM batch? The overhead would be minimal and freshness would improve dramatically.

5. **How does Cognee's `memify` handle the case where an entity was important then irrelevant?** Cicada's decay model is explicit (per-entity `decay_rate`); Cognee's is implicit (usage signal reweighting). The explicit model is more auditable but requires the Sleep cycle to maintain decay state. Is there a hybrid — implicit signal accumulation during awake phase, explicit decay only at Sleep?

6. **Multi-contextual facets**: none of the three production frameworks have solved this. Is it worth designing a novel `facets:` frontmatter extension for Cicada, or is context-in-tags sufficient (e.g., `tags: [engineer, family]` on separate belief claims)?
