# Graphiti / Zep: bi-temporal knowledge graph for agents

Research date: 2026-06-17
Sources: Zep paper (arXiv 2501.13956), Graphiti GitHub, Zep docs, Neo4j blog, benchmark analysis

---

## TL;DR

- **Facts, not entities, are the primary unit.** A fact is a subject-predicate-object triple (e.g. "Rodrigo prefers window seats") with two independent time dimensions: *when it was true in the world* (valid-time) and *when the system learned it* (transaction-time). This is the bi-temporal core.
- **Contradictions are handled by invalidation, not deletion.** When a new fact conflicts with an existing one, the old edge gets `t_invalid` stamped; it stays queryable for history. No LLM "which is right?" judgment at read time — the timeline *is* the conflict resolution.
- **Three-tier hierarchy: Episodes → Semantic entities+facts → Communities.** Raw ingest is non-lossy (episodes). Knowledge extraction produces typed nodes+edges. Clustering produces community summaries for broad queries. Retrieval can target any tier.
- **No promotion gate.** Facts are extracted from every episode immediately, not held back until a second mention. Deduplication (embedding + BM25 + LLM compare) prevents node proliferation instead.
- **Procedural / preference memory is a first-class entity type**, not a special case — `Preference` and `Procedure` are built-in entity types with typed Pydantic schemas, extracted automatically.
- **The hard dependency is Neo4j** — both graph traversal and vector search live there. This is the main portability cost for Cicada.

---

## Findings

### The bi-temporal model

Every semantic edge (fact) in Graphiti carries four timestamps ([Zep paper §3](https://arxiv.org/html/2501.13956v1)):

```
t'_created   — transaction time: when the system ingested this fact
t'_expired   — transaction time: when the system superseded this fact record
t_valid      — valid time: when the fact became true in the real world
t_invalid    — valid time: when the fact ceased to be true
```

The separation enables queries that would otherwise be impossible or require inference:

- "What do I know right now?" → filter where `t_invalid IS NULL AND t'_expired IS NULL`
- "What was true on 2025-03-01?" → filter `t_valid <= '2025-03-01' AND (t_invalid IS NULL OR t_invalid > '2025-03-01')`
- "What did the system believe on 2025-03-01, even if wrong?" → add transaction-time filter
- "When did this agent's belief about X change?" → look at `t'_created` sequence for edges on X

Valid time is extracted from episode content (e.g. "two weeks ago" resolved against `t_ref`). Transaction time is automatic. Graphiti says it "consistently prioritizes new information" — when a new episode contradicts an existing edge, it stamps `t_invalid = new_edge.t_valid` on the old edge.

### The three-tier graph structure

```
𝒢_e  Episode subgraph       — raw timestamped events, never mutated, always queryable
        ↓ (episodic edges)
𝒢_s  Semantic subgraph      — entity nodes + fact edges with bi-temporal metadata
        ↓ (community edges)
𝒢_c  Community subgraph     — cluster summaries for broad/thematic queries
```

**Episodes** (`𝒢_e`): each episode is a node storing the raw message/text/JSON, its timestamp, the speaker/actor, and the source type. Nothing is thrown away. Bidirectional indices link every extracted fact back to the episode that produced it — full provenance chain.

**Entities** (`𝒢_s` nodes): extracted semantic subjects and objects. Each entity has a UUID, canonical name, a running LLM-generated summary (updated on each new mention), `created_at`, and zero or more custom typed attributes (Pydantic fields). No closed taxonomy is required — types are developer-defined.

**Facts/edges** (`𝒢_s` edges): a triple `(source_entity, relation_type, target_entity)` plus a natural-language `fact` description, the four timestamps above, and a pointer to source episodes. `relation_type` is a string (e.g. `"PREFERS"`, `"WORKS_AT"`, `"CONTRADICTS"`). No closed predicate set.

**Communities** (`𝒢_c`): detected via graph clustering (similar to Leiden algorithm). Each community gets a summarized description and keyword names. Community nodes are embedded and searched for broad thematic queries — analogous to the "global" query tier in Microsoft GraphRAG, but regenerated incrementally rather than in a full batch.

### Episode → entity → fact extraction pipeline

For each new episode Graphiti runs in sequence ([Zep paper §4](https://arxiv.org/html/2501.13956v1)):

1. **Entity extraction**: LLM reads the new episode + the previous 4 episodes for context. Extracts entity mentions. The speaker is always auto-extracted as an entity.
2. **Entity resolution / deduplication**: each extracted entity name is embedded (1024-dim). Cosine + BM25 search against all existing entities. LLM then compares candidates against episode context and decides: new entity, merge with existing (update canonical name + summary), or keep both as distinct.
3. **Fact extraction**: LLM reads the same context window and extracts subject-predicate-object triples between extracted entities. Temporal expressions in the text are resolved to absolute timestamps using the episode's `t_ref`.
4. **Edge deduplication**: constrained to same entity-pair — if a similar fact already exists for that pair, LLM decides merge vs. new edge.
5. **Invalidation check**: new edges are compared (semantically) against all existing edges involving the same entities. LLM flags temporally-overlapping contradictions → stamps `t_invalid` on the old edges.
6. **Community update**: affected clusters are updated; summaries regenerated for changed communities only (incremental, not global recompute).

**No promotion gate**: extraction runs on every episode. Graph pollution prevention happens through step 2 (deduplication) rather than deferral.

### Hybrid retrieval

Three parallel search channels ([arXiv 2501.13956](https://arxiv.org/html/2501.13956v1)):

- `φ_cos` — cosine similarity on embedded fact/entity texts (1024-dim, stored in Neo4j vector index)
- `φ_bm25` — Okapi BM25 full-text search on fact text, entity names, community keywords
- `φ_bfs` — n-hop breadth-first graph traversal from seed nodes to find structural neighbors

Results are fused via Reciprocal Rank Fusion (default), Maximal Marginal Relevance, episode-frequency reranker, or cross-encoder LLM reranker (most expensive). P95 latency reported at 300ms without LLM reranking. The graph traversal component is what makes Graphiti qualitatively different from pure vector search — it surfaces related facts that aren't semantically close to the query but are structurally near relevant entities.

### Procedural / preference memory

Graphiti's entity type system handles procedural memory explicitly ([Zep entity types docs](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types)):

- **`Preference`** (built-in): extracted automatically from statements like "I prefer window seats" or "I like concise summaries." Stored as a typed node with attributes, connected via `EXPRESSED_PREFERENCE` edges to the User entity.
- **`Procedure`** (built-in): multi-step behavioral instructions like "always respond with code snippets before explanation." Stored as a typed node, linked to context entities where the procedure applies.
- Custom types are Pydantic `BaseModel` subclasses. Developers define fields with descriptions that guide the extraction LLM. Example for Cicada:

```python
class CodingPreference(BaseModel):
    applies_to: Optional[str] = Field(None, description="Framework or language this applies to")
    instruction: Optional[str] = Field(None, description="The specific preference or workflow step")
    strength: Optional[str] = Field(None, description="strong | mild | contextual")
```

### Benchmarks

From the Zep paper (DMR benchmark): Zep/Graphiti scored 94.8% vs. other systems (next best 93.4%). Against Mem0 in a separate benchmark ([DEV.to analysis](https://dev.to/juandastic/i-benchmarked-graphiti-vs-mem0-the-hidden-cost-of-context-blindness-in-ai-memory-4le3)):

| Dimension | Graphiti | Mem0 |
|-----------|----------|------|
| Knowledge coverage (entity/relation tracking) | 4.75/5 | 3.25/5 |
| Contradiction handling | 4.75/5 | 3.0/5 |
| Story/causal retention | High | Lower |
| Emotional/sensory detail | Lower | Higher |
| Token cost (ingestion) | 1.68x more | baseline |

Graphiti wins on structure, Mem0 wins on cost. The extra tokens come from the deduplication and invalidation pipeline running at every ingest.

---

## Concrete data-model ideas for Cicada

The substrate remains markdown+git+sqlite-vec. The question is which *ideas* from Graphiti translate without Neo4j.

### Idea 1: Bi-temporal frontmatter on edges, not entities

Cicada's current entities track `last_referenced` and `confidence` on the entity page. Graphiti's insight is that the **edges (relationships) should carry temporal validity**, not (only) the nodes.

In practice: `graph_edges.yaml` (or per-entity `edges:` frontmatter block) gets four fields per edge:

```yaml
edges:
  - id: edge_001
    source: Rodrigo
    target: FastAPI
    relation: PREFERS_STRUCTURE
    fact: "Rodrigo prefers FastAPI repos structured with routers/, services/, models/ separation"
    t_valid: "2025-11-01"
    t_invalid: null          # null = still true
    t_created: "2026-01-15"  # when Sleep cycle wrote this
    source_episode: ep_2026-01-15_003
```

When a new episode contradicts this, Sleep cycle stamps `t_invalid` and writes a new edge — the old one stays in git history AND in the yaml for historical query.

### Idea 2: Replace promotion gate with deduplication-at-extraction

Instead of gating entity creation on 2+ mentions, extract a candidate from every episode (as Graphiti does) but run a cheap deduplication step in Sleep:
1. Embed the candidate name.
2. Search sqlite-vec for cosine neighbors among existing entity embeddings.
3. If a match exists above threshold → update existing entity's summary + add source_episode.
4. If no match → create a stub entity page with `status: candidate` and low confidence.
5. A `candidate` entity gets promoted to `active` only after it accumulates 2+ source_episodes OR is referenced by a high-confidence entity (the promotion logic stays, but now it's a post-extraction filter, not a pre-extraction gate).

This preserves Cicada's anti-pollution intent while being more principled — candidates are in the graph and queryable, just marked.

### Idea 3: Facts as first-class units in sqlite-vec

Currently sqlite-vec indexes episode chunks and entity pages. Add a third index: **fact rows**.

```sql
CREATE TABLE facts (
    id TEXT PRIMARY KEY,        -- fact_<uuid>
    source_entity TEXT,
    target_entity TEXT,
    relation TEXT,
    fact_text TEXT,             -- natural language description
    t_valid TEXT,               -- ISO date or null
    t_invalid TEXT,             -- ISO date or null (null = currently true)
    source_episode TEXT,
    embedding BLOB              -- 768-dim from EmbeddingGemma-300M
);
```

Retrieval: for a query, search facts by embedding similarity, then BFS-expand to related entities via wikilinks. This gives the hybrid semantic + structural retrieval without Neo4j. The `/ask` endpoint searches facts first (highest precision), then entity pages (context), then episodes (provenance).

### Idea 4: Community summaries as cluster-index.md files

Graphiti's community tier maps naturally to "topic cluster" files. The Sleep cycle could periodically cluster entity embeddings (k-means or Leiden via python-louvain) and write `memory/clusters/<cluster-name>.md` files with LLM-generated summaries. These become a "broad query" retrieval tier — the agent can search cluster files before drilling into entities when the query is thematic ("what do I know about my career trajectory?").

### Idea 5: Typed entity schemas via YAML frontmatter extensions

Graphiti's Pydantic entity types map to Cicada's closed-type taxonomy. Instead of 8 fixed types with fixed frontmatter fields, define per-type schema extensions:

```yaml
# In a schema config file: memory/schema/types.yaml
Preference:
  fields: [applies_to, instruction, strength, context]
Procedure:
  fields: [applies_to, steps, trigger_context]
Person:
  fields: [role, relationship_to_rodrigo, contact, org]
```

Sleep cycle validates/populates these fields during extraction. The type system stays open (add new types by adding entries in `types.yaml`) without breaking existing entity pages.

---

## Tradeoffs / where it fails

**Graphiti's strengths are real but come with costs:**

1. **Neo4j hard dependency.** Every graph traversal, vector search, and BFS query goes through Neo4j. For Cicada's single-user, on-device, zero-infra requirement, this is a hard blocker for direct adoption. Running a Neo4j instance on-device is possible (Neo4j Desktop / embedded) but adds 1-2GB RAM overhead and licensing surface.

2. **High token cost at ingestion.** The deduplication + invalidation pipeline runs LLM calls on every episode — entity extraction, entity resolution, fact extraction, edge deduplication, invalidation check. That is 4-5 LLM calls per episode. At personal Cicada scale this is manageable if batched in Sleep, but it means Sleep cycles cost real money, not pennies.

3. **No confidence scores.** Graphiti does not track per-fact confidence. The system trusts the latest LLM extraction and uses temporal ordering as the sole signal. For Cicada, where provenance and trustworthiness ("how certain is this?") are core UX requirements, this is a gap.

4. **Community detection cost.** Rebuilding community summaries is expensive. Graphiti does incremental updates but they still require LLM calls. At thousands of entities this becomes a non-trivial Sleep cycle cost.

5. **No decay model.** Graphiti has no concept of temporal decay (absence of mention lowering confidence). Facts are either valid or invalid — there is no gradient. For Cicada's design, where the silence signal is explicitly desired, Graphiti's model needs to be augmented.

6. **Not designed for global/thematic queries.** The community tier partially addresses this but it is acknowledged as weaker than Microsoft GraphRAG for broad analytical queries ("summarize everything about X theme"). Cicada's `/ask` endpoint partially fills this gap.

7. **Context window blindness at retrieval.** The Mem0 benchmark noted that even Graphiti can return a high-quality set of facts that exceeds the context window — the LLM only sees what the retrieval ranked into the top-K. Structural traversal helps but doesn't eliminate the problem.

8. **Entity summary drift.** Entity summaries are updated incrementally by LLM on each new mention — meaning the summary is always an LLM's interpretation of the latest state, not a structured log. If the LLM drops detail during update, it is gone unless the source episode is re-read. This is the opposite of Cicada's explicit, human-readable entity pages.

---

## Open questions

1. **Can the bi-temporal model be implemented purely on sqlite-vec + git without Neo4j?** The `facts` table idea above is an attempt. The missing piece is graph traversal — BFS over markdown wikilinks would require parsing `.md` files at query time, which is slow. A `wikilinks` table in SQLite as an adjacency list might work.

2. **How should t_valid be extracted for personal knowledge?** Most of Rodrigo's facts don't have explicit dates in the text. Graphiti extracts relative dates ("two weeks ago") using `t_ref` = episode timestamp. Sleep cycle would need a temporal NLP pass to extract valid-time from episode content — or default `t_valid = episode_timestamp` (weaker but safe).

3. **Should confidence be modeled as an edge property or derived from temporal/frequency signals?** Graphiti ignores confidence. Cicada's current model has per-entity confidence. The right synthesis might be: confidence = f(recency of latest valid edge, frequency of corroborating edges, source quality) — computed at read time, not stored.

4. **What is the right granularity for "fact" in personal memory?** Graphiti facts are fine-grained triples. But "Rodrigo's self in engineer context vs. family context" is not a triple — it is a multi-dimensional overlay on the same entity node. Does the fact layer handle this, or does it require the facet/perspective layer described in Rodrigo's own intuitions?

5. **How do Procedure entities age?** A coding preference from 2024 might be wrong in 2026. Graphiti has no mechanism to decay or flag stale procedural knowledge. This is a gap for agent reliability — Cicada should add a `last_confirmed` field and a procedure-specific decay / nudge path.

6. **Is the no-promotion-gate design worth the deduplication cost?** Graphiti's approach is correct in principle but requires strong deduplication. In the markdown+git substrate, "deduplication" means fuzzy-matching against ~1,882 existing entity pages during Sleep — that is an O(n) embedding lookup per extracted candidate. With sqlite-vec ANN this is fast; the cost is the LLM comparison step for near-misses.
