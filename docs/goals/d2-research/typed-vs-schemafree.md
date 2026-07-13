# Typed/ontology vs schema-free knowledge representation + GraphRAG

## TL;DR

- **Schema-free extraction produces noisy graphs.** Without type constraints, LLMs default to generic entity labels ("Topic", "Object") and flat "RELATES_TO" edges that cannot be queried meaningfully — essentially an expensive vector store dressed as a graph. ([Daily Dose of DS](https://blog.dailydoseofds.com/p/schema-guided-agent-memory-for-production))
- **Typed schemas cut hallucinations and boost entity yield.** A controlled study on GraphRAG with technical documents found that a 5-class domain schema extracted ~10% more entities *and* produced fewer hallucinations than the schema-less pipeline, because typed constraints prevent the LLM from extracting noise that pollutes context windows ("the distraction problem"). ([Dagstuhl/TGDK 2025](https://drops.dagstuhl.de/storage/08tgdk/tgdk-vol003/tgdk-vol003-issue002/html/TGDK.3.2.3/TGDK.3.2.3.html))
- **The abstraction level of the schema matters more than breadth.** In that same study, the 5-class schema outperformed the 8-class expansion — overly granular schemas constrain LLM interpretation and split what should be unified entities. There is an under-studied "sweet spot."
- **GraphRAG's community summaries address a failure mode naive RAG can't.** For holistic/global questions ("what are the main themes in my memory?"), hierarchical community summaries via Leiden clustering beat vector similarity ~70-80% on comprehensiveness and diversity. For entity-specific lookup, local graph search complements semantic search. ([Microsoft GraphRAG paper, arXiv 2404.16130](https://arxiv.org/abs/2404.16130))
- **Temporal invalidity is orthogonal to typing but equally critical.** Schema can be typed or open; temporal tracking (bi-temporal: when-true vs when-learned) is a separate axis. Graphiti/Zep shows this via edge validity windows — old facts are closed, not deleted. ([Zep blog](https://blog.getzep.com/stop-using-rag-for-agent-memory/))
- **Hybrid wins: typed core + open extension.** Frameworks like Graphiti and Cognee converge on defining a small typed core (3-10 entity types with Pydantic constraints) while allowing open-schema extraction to flow for novel knowledge not fitting the core types — best of both.

---

## Findings

### 1. Why pure schema-free extraction degrades graph quality

When an LLM is asked to extract entities and relationships from raw text with no type constraints, it converges on degenerate outputs: entity types become "Person", "Topic", "Object"; relationships become "RELATES_TO" or "IS_ABOUT". The resulting graph is not traversable in a semantically meaningful way. A retrieval query like "what tools does Rodrigo prefer for FastAPI projects?" cannot be answered by traversing a graph where tool nodes are indistinguishable from concept nodes with the same flat label.

Source: [Schema Guided Agent Memory for Production Agents](https://blog.dailydoseofds.com/p/schema-guided-agent-memory-for-production) — Avi Chawla, Daily Dose of DS.

### 2. GraphRAG architecture: what it actually does

Microsoft's GraphRAG ([arXiv 2404.16130](https://arxiv.org/abs/2404.16130)) works as a two-phase system:
1. **Indexing**: LLM-driven entity and relationship extraction from text chunks → knowledge graph construction → community detection via Leiden algorithm → community summary generation (bottom-up, hierarchical).
2. **Query**: Global search routes questions to community summaries (aggregated into partial responses then re-summarized). Local search routes to specific entity neighborhoods.

The default GraphRAG entity extraction prompt targets only a few types (organization, geography, person) but uses few-shot examples heavily. The community summaries are what enable holistic "sensemaking" queries that naive RAG cannot answer.

Key insight for Cicada: **GraphRAG's win is not primarily about typing — it's about the community summary layer**, which provides pre-computed cross-entity context. A personal memory system with structured markdown could get a similar benefit by periodically generating "cluster summaries" over related entity pages.

Source: [Microsoft Research GraphRAG blog](https://www.microsoft.com/en-us/research/blog/graphrag-new-tool-for-complex-data-discovery-now-on-github/), [GraphRAG auto-tuning](https://www.microsoft.com/en-us/research/blog/graphrag-auto-tuning-provides-rapid-adaptation-to-new-domains/).

### 3. Schema-guided extraction: the controlled evidence

The most directly relevant controlled study: [GraphRAG on Technical Documents — Impact of Knowledge Graph Schema (TGDK 2025)](https://drops.dagstuhl.de/storage/08tgdk/tgdk-vol003/tgdk-vol003-issue002/html/TGDK.3.2.3/TGDK.3.2.3.html) compared three pipeline variants on a mineral processing corpus:

| Pipeline | Entity count | Hallucinations | Factual accuracy |
|---|---|---|---|
| Schema-free | 195,930 | Most | Lower |
| 5-class domain schema (MDS) | 218,274 | Fewest | Highest |
| 8-class expanded schema (EMDS) | ~comparable to MDS | Comparable | Comparable |

The 5-class schema extracted ~10% more entities *because* typing focuses the LLM on what matters, reducing irrelevant extractions while capturing more relevant ones. The "distraction problem" — where schema-free pipelines leave gaps filled with irrelevant context — directly degraded LLM answer quality.

**The 5-class schema outperformed the 8-class.** Adding more types created fragmentation without retrieval benefit. This is a critical finding for Cicada's 8-type taxonomy review.

### 4. Ontology-enhanced approaches (RDF/OWL tier)

Systems like Cognee go further: they validate extracted entities against OWL class hierarchies, enabling logical inference (e.g., "cars produced by Audi" can be answered via transitive class membership even if not explicitly stated). ([Cognee ontology blog](https://www.cognee.ai/blog/deep-dives/ontology-ai-memory))

In controlled comparisons, ontology-enhanced graphs had:
- More nodes and denser connections
- Higher clustering coefficients
- Shorter paths between concepts
- Fewer isolated information islands

However, RDF/OWL complexity is high — Zep/Graphiti explicitly rejected this in favor of Pydantic models ("more developer-accessible"). ([Zep Entity Types blog](https://blog.getzep.com/entity-types-structured-agent-memory/))

For a solo developer on a personal system, Pydantic-style typed schemas with optional constraint checking is the pragmatic middle ground between raw open-IE and full OWL ontology.

### 5. Open-schema extraction: when it wins

Open-schema (no predefined types) wins when:
- The domain is genuinely unknown at design time
- Discovery of novel relationship kinds matters more than retrieval precision
- The system is a general-purpose corpus indexer, not a domain-specific agent memory

For personal agent memory where the domain IS known (Rodrigo's projects, people, tools, beliefs), open-schema mostly produces noise. However, open-schema is still valuable as a *fallback* for mentions that don't fit predefined types — the hybrid approach.

Research context: [LLM-empowered KG construction survey (arXiv 2510.20345)](https://arxiv.org/html/2510.20345v1) distinguishes schema-based paradigms (structure/normalization/consistency) vs schema-free (flexibility/discovery) — the survey's conclusion is that neither is universally better; the choice depends on domain specificity.

### 6. Graphiti/Zep's hybrid design (the current SOTA for agent memory KG)

Graphiti ([arXiv 2501.13956](https://arxiv.org/abs/2501.13956)) achieves P95 retrieval latency of 300ms via hybrid search: semantic embeddings + BM25 keyword + direct graph traversal — no LLM at retrieval time. It combines:
- **Typed default entity types**: User, Preference, Procedure (extracted with structured prompts)
- **Custom Pydantic entity types**: Developer-defined schemas (e.g., `AirTravelPreferences` with typed fields)
- **Open-schema fallback**: Facts that don't fit defined types still get extracted as generic nodes
- **Bi-temporal edge tracking**: Every edge has valid_from / valid_to — old facts are "closed" not deleted, enabling historical queries

This is explicitly designed to solve the RAG-for-memory failure mode: RAG retrieves the old "liked Adidas" fact because it's semantically similar, ignoring that this was superseded by "switched to Puma."

Source: [Stop Using RAG for Agent Memory — Zep](https://blog.getzep.com/stop-using-rag-for-agent-memory/), [Graphiti GitHub](https://github.com/getzep/graphiti), [Graphiti Entity Types](https://blog.getzep.com/entity-types-structured-agent-memory/).

### 7. Ontology-guided extraction reduces hallucinations in LLM extraction

Structured prompts with ontology specifications improve triple extraction accuracy by up to 44.2%, reduce hallucinations by 22.5%, and increase consistency by up to 20.9% compared to unconstrained extraction ([from search synthesis; see arXiv 2208.08690 and MDPI 2025](https://www.mdpi.com/2076-3417/15/7/3727)). The mechanism: constrained generation forces the LLM to output only valid (subject-type, relation, object-type) triples, preventing spurious relationship invention.

### 8. Mem0's graph abandonment — a cautionary finding

Mem0 v3 dropped its graph layer and replaced it with entity linking + vector search. Their internal benchmarks showed the graph variant "lost on single- and multi-hop recall, ran 3x slower, and cost 2x the tokens." ([codepointer comparison](https://codepointer.substack.com/p/agent-memory-systems-and-knowledge))

This is a warning against graph complexity for its own sake. The graph only pays off when: (a) traversal queries actually occur (multi-hop reasoning), and (b) the schema is structured enough to make traversal meaningful. For a personal system with ~1,882 entity pages and structured markdown + wikilinks, this is plausible — but the Mem0 finding suggests being conservative about graph traversal depth in the hot path.

---

## Concrete data-model ideas for Cicada

These ideas assume the existing substrate (markdown + git + sqlite-vec) stays in place.

### Idea A: Lean typed core (4-6 types) + open "claim" overflow

Instead of 8 types covering everything, define a minimal core of 4-6 high-signal types that cover 85% of Rodrigo's memory (e.g., Person, Project, Tool, Belief/Preference, Deadline, Concept). Any extraction that doesn't fit cleanly goes into a generic `claim` record stored in sqlite-vec (no markdown page, no git commit) until it recurs or connects to an existing entity. This mirrors the evidence: 5-class schema > 8-class in the TGDK study, and generic overflow prevents type forcing.

### Idea B: Per-entity "facets" via typed sub-sections in markdown

To handle context-dependent identity (Rodrigo as engineer vs. family-self vs. philosophy-self), represent a single entity with typed facet blocks within one markdown file:

```markdown
---
type: person/self
id: rodrigo
---

## [facet: engineer]
- Prefers FastAPI + SQLite for small projects
- Learns best with concise examples

## [facet: family]
- Considers long-term stability over technical novelty

## [facet: philosophy]
- Holds belief: autonomy > optimization
```

At retrieval time, the agent receives the full entity page; the Sleep cycle extracts and indexes each facet section separately into sqlite-vec with a `facet` metadata field. Searches can retrieve facet-specific matches without losing the cross-facet entity identity. No graph complexity added; works with existing markdown + git.

### Idea C: "Belief" as a first-class typed unit (replacing `concept` + `skill`)

Rather than a `concept` entity and a `skill` entity (which overlap badly), define a `belief` type that captures any claim Rodrigo holds, prefers, or knows, with:
- `confidence`: 0-1
- `context`: which facet/domain this belief belongs to
- `status`: active / superseded / contested
- `contradicts`: wikilink to conflicting belief
- `source_episodes`: list

This maps to the Honcho "observer/observed" philosophy: a belief is an observation by the system about Rodrigo. The Sleep cycle can generate new beliefs, supersede old ones, and detect contradictions. Procedural/preference memory ("Rodrigo likes FastAPI repo structure X") becomes a `belief` with `context: engineering`.

### Idea D: Community summary documents for cross-entity clusters

Inspired by GraphRAG community summaries: periodically generate a `clusters/cluster-<id>.md` file that is an LLM-authored synthesis of a group of related entity pages (detected by wikilink density or sqlite-vec embedding clustering). These cluster summaries become retrievable context for holistic queries ("what is Rodrigo focused on professionally right now?") without requiring graph traversal at query time. Cheap to implement on the existing substrate; high value for global-sensemaking queries.

### Idea E: Schema-constrained Sleep extraction prompts

In the Sleep cycle extraction stage, pass the entity type schema (as a Pydantic-style list) into the extraction prompt as a constraint. Evidence from the TGDK study and Zep suggests this reduces hallucinated extractions and increases recall of relevant entities. The constraint does not need to be hard (reject non-matching) — soft (prefer these types, label others as `uncategorized`) is sufficient.

---

## Tradeoffs / where it fails

| Tradeoff | Description |
|---|---|
| Schema rigidity | A fixed type set cannot capture genuinely novel knowledge kinds. If Rodrigo starts managing a team, "organization chart" relationships don't fit the existing types. Solution: allow `uncategorized` overflow + promote to type when recurrent. |
| Schema design cost | Good types require domain knowledge upfront. Wrong types (too granular, too vague) are hard to migrate when ~1,882 pages already exist. Incremental migration is possible (just add a new type and re-run extraction on recent episodes) but incomplete for historical data. |
| Facet explosion | Facets (Idea B) can multiply uncontrollably if not constrained. Every entity could end up with 10 facets. Need a bounded set of recognized facets at the system level (e.g., 4-6 life-context labels). |
| Community summary staleness | GraphRAG-style cluster summaries go stale as entities evolve. In a nightly Sleep cycle, summaries must be regenerated for affected clusters, adding LLM cost. For a personal system with slow graph evolution, weekly regeneration may be sufficient. |
| Graph traversal cost vs. flat retrieval | Mem0's finding: graph traversal was 3x slower and 2x more expensive than flat retrieval. For Cicada's scale (~1,882 entities), traversal is cheap, but this argues against deeply recursive graph queries in the hot path. Keep retrieval to 1-2 hops. |
| Open-IE noise accumulates | Any open-schema fallback (claims not fitting defined types) will accumulate noise over time unless aggressively pruned. The Sleep cycle's decay mechanism must apply to uncategorized claims as well. |
| Ontology inference vs. markdown simplicity | Full RDF/OWL inference is incompatible with plain markdown. If inference (transitive closure, class hierarchy) is needed, it requires a separate reasoning layer. Likely out of scope for a solo developer — Pydantic constraints + LLM reasoning at query time is sufficient. |

---

## Open questions

1. **What is the right abstraction level for Cicada's type set?** The TGDK study suggests 5 types outperformed 8. Should Cicada's 8 types be collapsed (e.g., merge `concept` + `skill` + `location` into `belief`/`place`/`knowledge`)? What empirical signal would tell us we got it right?

2. **Should the promotion gate be replaced by confidence-weighted open extraction?** Instead of the binary "2nd mention = promote", could every mention create a low-confidence `claim` node that accumulates confidence with each recurrence? This is closer to Graphiti's model and removes the hard gate, but requires managing many more low-confidence records.

3. **How do facets interact with entity resolution?** If Rodrigo-as-engineer and Rodrigo-as-family-self hold contradictory beliefs, should these be represented as a single entity with conflicting facets, or two separate entities that share identity? The Honcho (observer, observed) model suggests a single entity with typed observation slots — but this is unproven at scale.

4. **Can community summaries be generated incrementally (per Sleep cycle) rather than full-graph recomputation?** GraphRAG regenerates all summaries at indexing time, which is expensive. For a nightly Sleep cycle, an incremental approach (re-summarize only changed clusters) would be necessary. No published method exists for this on a markdown substrate.

5. **Is sqlite-vec sufficient for facet-level retrieval, or does it need a separate index per facet?** If facets are indexed as metadata fields in sqlite-vec, do standard approximate nearest-neighbor searches respect facet boundaries enough? Or is a separate index per life-context domain (engineering, family, philosophy) needed for precision?

6. **How should the schema evolve as Rodrigo's life changes?** Entity types are (hopefully) stable; facets and belief contexts are not. A versioned schema with migration scripts is needed but adds maintenance burden for a solo developer.
