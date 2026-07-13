# Context-dependent identity: facets, named graphs, perspectives

## TL;DR

- Every mature approach to context-dependent identity converges on the same insight: **a claim (belief, fact, attribute) is a triple PLUS a context label** — whether that context label is an RDF named graph URI, a quad's 4th element, an RDF-star nested triple, or a YAML `context:` field in a markdown frontmatter.
- The two viable camps for a lightweight substrate are **(a) context-scoped edges** (attach `context:` to each relationship/claim individually) vs **(b) per-context entity facets** (one entity node with multiple named facet sub-documents or sub-sections); they are not mutually exclusive — the best designs use both.
- Danah boyd's "Faceted Id/entity" (MIT Media Lab, 2002) remains the clearest conceptual frame: a single identity presents different facets to different audiences; **context collapse** (merging audiences) is what breaks naive single-page entity models. In Cicada terms: a single `Rodrigo` page will silently average the engineer-self and the family-self into noise.
- Honcho's (Plastic Labs) `(observer, observed)` model is practically the most relevant: beliefs are **relational** — what the agent believes about Rodrigo IS the agent's model of Rodrigo, and that model is explicitly keyed by *who is observing*. This is a generalisation of named graphs to social cognition.
- Graphiti/Zep (2025) ships the closest production implementation: **three-tier hierarchy** (episode → semantic entity → community) where each semantic edge carries `valid_at`/`invalid_at` timestamps AND a `fact_context` field — effectively an inline named graph per claim.
- For Cicada on markdown+git: the cheapest path to context-scoped claims is **a `context:` field inside each wikilink or relationship YAML stanza**, combined with **named sections or facet sub-files** per entity when a context has enough mass to deserve its own page.

---

## Findings

### 1. The core problem: context collapse on single-identity pages

Goffman (1959) showed that humans perform different selves for different audiences ("front stage vs back stage"). boyd (2002) formalised this as *faceted identity* and coined *context collapse* for what happens when those audiences merge — the presenter must flatten to a lowest-common denominator [Faceted Id/entity, MIT Media Lab](https://smg.media.mit.edu/people/danah/thesis/danahThesis.pdf). In a knowledge graph, a single entity page for "Rodrigo" commits context collapse by design: all beliefs about Rodrigo across all life contexts are merged into one node. The engineering career preferences, the family dynamics, and the philosophical worldview overwrite or average each other.

The implication for agent memory: **an LLM querying "how does Rodrigo prefer to work?" needs to know WHICH context (FastAPI project, thesis writing, personal life) is currently active**, or it returns an averaged answer that is accurate in none.

### 2. RDF named graphs and quads: the formal solution

The standard semantic web answer is the **quad**: `(subject, predicate, object, graph_name)`. A named graph URI is a label on a set of triples; you can attach metadata to the named graph itself (provenance, time range, context type) as ordinary triples in the default graph. This is how SPARQL 1.1 Dataset works.

Key properties ([Oracle RDF Knowledge Graph Guide](https://docs.oracle.com/en/database/oracle/oracle-database/19/rdfrm/rdf-semantic-graph-overview.html); [Named Graphs Pattern](https://patterns.dataincubator.org/book/named-graphs.html)):
- Named graphs enable **provenance at the batch level** (all triples from episode X go in graph X).
- Quads enable **provenance at the statement level** — each individual triple can carry a different graph label.
- Graph merging is still possible: SPARQL `UNION` or `FROM NAMED` queries traverse multiple named graphs. You get both isolation and federation.

**Tradeoff:** named graphs are coarse-grained (everything in the graph shares the same context label). If one belief from a session belongs to context A and another to context B, you need two named graphs for that session, which explodes graph count.

### 3. RDF-star / RDF 1.2: statement-level metadata without reification verbosity

Standard RDF reification to annotate a single triple requires 4 extra triples per annotation — verbose and hard to query. **RDF-star** (now incorporated into RDF 1.2) allows `<<subject predicate object>>` as the subject or object of another triple, directly expressing "this specific claim was asserted in engineering-context with confidence 0.9" in one line. Benchmarks show RDF-star is faster and smaller than both standard reification and singleton properties ([Ontotext: Is RDF-star the best choice?](https://www.ontotext.com/blog/graphdb-users-ask-is-rdf-star-best-choice-for-reification/); [Easy and complex: RDF-star and Named Graphs, 2022](https://arxiv.org/pdf/2211.16195)).

For Cicada, this maps to a YAML pattern like:

```yaml
relationships:
  - target: "[[FastAPI]]"
    type: prefers
    context: engineering
    confidence: 0.92
    source_episodes: [ep_2026-01-10_001]
  - target: "[[Family time]]"
    type: values_highly
    context: personal
    confidence: 0.88
```

Each relationship stanza IS an RDF-star-style annotated edge. The `context:` key is the 4th dimension.

### 4. Property graph facet patterns

In property graph systems (Neo4j, Memgraph), the standard pattern for faceted entities is either:
- **Role nodes**: an extra node type `EngineerSelf`, `FamilySelf` that points to the core `Rodrigo` node via `HAS_FACET` edges, with context-specific properties on the facet node. Cross-context links become edges between facet nodes (or between their parent entity nodes with a `cross_context:true` tag).
- **Context-typed edges**: keep one entity node per person; attach context labels to the edges rather than the nodes. "Rodrigo PREFERS FastAPI [context=engineering]" vs "Rodrigo PREFERS long_weekend [context=personal]".

The multi-perspective knowledge graph embedding literature ([MGIF, ScienceDirect 2024](https://www.sciencedirect.com/science/article/abs/pii/S0020025524003517)) treats each "perspective" as a learnable subspace of entity embeddings — which is the vector-level analogue of faceted nodes in a symbolic graph. The same entity gets a different embedding vector per context. This is relevant if Cicada's sqlite-vec index is extended to support per-context embeddings.

### 5. Honcho's (observer, observed) model

Honcho ([docs.honcho.dev](https://honcho.dev/docs/v3/documentation/core-concepts/reasoning)) structures all memory as collections keyed by `(observer, observed)` peer pairs. This is a social-cognition generalization of named graphs: the "context" of a belief is **which agent is doing the believing, about which subject**. The agent's model of Rodrigo-as-engineer is a different collection than its model of Rodrigo-as-family-member — even though the underlying subject is the same.

Rather than pre-categorizing what to store, Honcho extracts belief layers via formal reasoning:
1. **Explicit premises** (what was directly stated in the episode)
2. **Deductive conclusions** (what follows necessarily)
3. **Inductive patterns** (what recurs across conclusions)
4. **Abductive inferences** (simplest explanation for observed behavior)

The key philosophical point: **beliefs are never stored flat**. They are structured by their epistemic status and by the observer/observed pair. For Cicada, this suggests that what looks like a single "Rodrigo prefers X" fact is actually `(Cicada-agent, Rodrigo, engineering-context) → prefers X with confidence 0.9 from abductive inference`. The provenance chain includes the reasoning step, not just the episode.

### 6. Graphiti/Zep temporal graph (production implementation, Jan 2025)

Graphiti ([arXiv:2501.13956](https://arxiv.org/abs/2501.13956); [Neo4j blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)) is the closest published system to what Cicada needs. Its three-tier architecture:

- **Episode subgraph**: raw timestamped messages/events, never deleted, ground truth record.
- **Semantic entity subgraph**: extracted entities and typed edges. Each edge carries `valid_at` and `invalid_at` (not deletion — contradiction sets `invalid_at`), plus a `fact_context` field scoping the claim. When a new episode contradicts a prior edge, the old edge is invalidated rather than overwritten — this is temporal provenance without graph bloat.
- **Community subgraph**: clusters of entities that co-occur frequently, auto-detected. Useful for surfacing "in the engineering domain, these entities cluster together" vs "in the personal domain, these cluster."

The `fact_context` field on edges is effectively an inline named graph per claim. Graphiti shows this is tractable in production (beats MemGPT at 94.8% vs 93.4% on DMR benchmark).

### 7. Danah boyd's "Faceted Id/entity" framework (architectural takeaway)

boyd's thesis identifies three properties of context that must be preserved:
1. **Audience segregation**: who is receiving this facet.
2. **Setting**: the norms and expectations of the context (professional, intimate, public).
3. **Cues and signals**: what cues collapse or separate contexts.

For a knowledge graph, "setting" maps to a named context (engineering, personal, philosophical), "audience segregation" maps to the observer in Honcho's pair, and "cues" map to the topic signals that should trigger retrieval of one facet over another. Context collapse is the failure mode where the system conflates these three and merges beliefs that should remain separated.

---

## Concrete data-model ideas for Cicada

These are design options, not prescriptions. They can be combined.

### Option A: Context-scoped edges (lowest cost, add `context:` to relationship YAML)

Extend each relationship stanza in entity frontmatter with a `context:` tag:

```yaml
# In entities/rodrigo.md
relationships:
  - target: "[[FastAPI]]"
    type: prefers_for
    context: engineering
    confidence: 0.91
    note: "repo structure, async endpoints, no ORM"
  - target: "[[long conversations]]"
    type: avoids_in
    context: engineering
    note: "prefers concise async tasks"
  - target: "[[philosophy reading]]"
    type: engages_with
    context: personal-evening
    confidence: 0.85
```

**How retrieval uses this:** `/ask` queries the sqlite-vec index using the current conversation's detected context tag (a small LLM call: "what context is this conversation in?") and filters or weights relationships by matching `context:`. The agent gets "Rodrigo-as-engineer" beliefs for a code session without noise from personal beliefs.

**Cross-context links** (Rodrigo's design intuition: abstract links between not-obviously-related things) are explicit edges with `context: cross` or `context: meta`:

```yaml
  - target: "[[Systems thinking]]"
    type: applies_across
    context: cross
    note: "present in both engineering architecture decisions and life philosophy; Sleep cycle inferred"
```

**Migration cost:** Additive — existing edges without `context:` remain valid and are treated as `context: general`. No existing pages break.

### Option B: Facet sub-sections within one entity page

For entities with substantial mass in multiple contexts, use named H2 sections:

```markdown
---
type: person
name: Rodrigo Sagastegui
contexts: [engineering, personal, philosophical]
---

## engineering-self
- Prefers FastAPI with async patterns, no ORMs
- Thinks in systems: latency, failure modes, observability
- Works in focused 2-3 hour blocks; hates context switching mid-session
- [[Cicada]], [[LEANN]], [[IE University capstone]] as anchors

## personal-self
- Values long uninterrupted family time on weekends
- [[Madrid]], [[family]] as anchors
- Reads philosophy slowly; prefers re-reading to breadth

## philosophical-self
- Drawn to epistemological humility, coherentism, emergence
- Connects to [[Systems thinking]] (cross-context link)
- Honcho's (observer, observed) philosophy resonates
```

The Sleep cycle extracts context-tagged paragraphs from episodes and appends to the relevant section. The `/ask` endpoint can return the full page OR a specific section based on detected context.

**How cross-context abstract links surface:** the Sleep cycle's pattern-detection stage (Stage 4 currently) becomes context-aware pattern detection — it explicitly looks for patterns that recur across two or more context sections and writes a `cross-context` relationship stanza.

**Migration cost:** Medium. Existing single-section pages remain valid. Sleep cycle needs a context-classification step during extraction (Stage 1).

### Option C: Per-context facet sub-files (for high-mass entities)

For entities with very high context-mass (the `Rodrigo` entity itself, or a long-running project), create sub-files:

```
entities/rodrigo.md               ← canonical hub, index of facets, cross-context links
entities/rodrigo--engineering.md  ← engineering-self facts
entities/rodrigo--personal.md     ← personal-self facts
entities/rodrigo--philosophy.md   ← philosophical-self facts
```

The hub page contains the cross-context wikilinks and the `related:` list. Each facet file has standard frontmatter with a `facet_of: "[[rodrigo]]"` field. The sqlite-vec index tags embeddings with both entity ID and context label, enabling filtered search.

**Retrieval:** context-detected queries hit `rodrigo--engineering.md` directly; cross-context queries hit `rodrigo.md` which traverses all facet files. This is the named-graph pattern in markdown form.

**Migration cost:** High — requires file splitting and Sleep cycle routing logic. Justified only for `type: person` entities with substantial cross-context mass (probably only a handful of entities warrant this).

### Option D: Honcho-style belief objects (most expressive, highest cost)

Replace the current YAML frontmatter + body model with structured belief objects stored in YAML blocks:

```yaml
beliefs:
  - id: b_001
    claim: "prefers FastAPI repo structure with routers/, services/, models/ layers"
    context: engineering
    epistemic_status: inductive  # explicit/deductive/inductive/abductive
    confidence: 0.93
    source_episodes: [ep_2026-01-10_001, ep_2026-03-15_003]
    valid_from: 2026-01-10
    contradicted_by: null
  - id: b_002
    claim: "believes knowledge graphs are overengineered for most personal-scale problems"
    context: engineering-philosophy
    epistemic_status: abductive
    confidence: 0.75
    contradicted_by: null
    cross_context_resonance:
      - context: philosophical-self
        note: "epistemological humility — prefers minimal structures that can be extended"
```

This is the richest model and the one most faithful to Honcho's reasoning layers. Each belief is a first-class object with context, epistemic status, and cross-context resonance links.

**Migration cost:** Very high — requires rewriting all 1,882 entity pages and a new Sleep cycle extraction schema. Not incrementally migratable without a conversion script.

### Recommended combination for Cicada

1. **Start with Option A** (context-scoped edges): zero migration cost, immediate benefit for procedural/preference memory (`context: engineering` on preference edges).
2. **Add Option B** (facet sub-sections) for the `Rodrigo` entity and any entity the Sleep cycle identifies as context-split (entities where beliefs across two contexts contradict each other are the signal).
3. **Add `epistemic_status`** to belief stanzas as a lightweight subset of Option D — just a field, not a full restructure. This captures Honcho's reasoning-layer insight at minimal cost.
4. **Defer Option C and D** until the entity count in each context is large enough to justify file splitting (likely never needed for non-self entities).

---

## Tradeoffs / where it fails

**Context classification is a hard problem.** The Sleep cycle must determine which context a given episode belongs to during Stage 1 extraction. This classification is imperfect — many conversations blend contexts (talking about career while also touching on life philosophy). If misclassified, beliefs end up in the wrong facet and may never surface. Mitigation: allow `context: [engineering, philosophical]` multi-tags, and add a `context: general` fallback for ambiguous beliefs.

**Cross-context links require human or LLM curation.** The most valuable insight in Rodrigo's design intuition — "draw abstract links between not-obviously-related things" — is precisely what naive extraction misses. The Sleep cycle pattern-detection stage must be explicitly prompted to look for structural similarities across contexts, not just recurrence within one context. This is a prompt engineering problem, not a data model problem, but it is real work.

**Facet sub-sections fragment search.** If `rodrigo--engineering.md` and `rodrigo--personal.md` are separate files, a query that doesn't correctly identify context will hit the wrong file and miss relevant beliefs. The sqlite-vec index must embed both the content AND the context label, and the retrieval step must use context-weighted search rather than pure semantic similarity.

**Context boundaries are fuzzy in practice.** "Engineering-self" and "philosophical-self" are not cleanly separable — Rodrigo's architectural preferences are partly philosophical. Any hard boundary will require constant reclassification or result in beliefs that belong in multiple contexts. The `context: cross` edge type partially addresses this but requires deliberate authoring.

**No existing benchmark.** There is no standard benchmark for context-dependent retrieval accuracy in personal AI memory. Graphiti uses DMR (Dialog-based Multihop Reasoning) which does not test multi-context identity. The thesis would need to design a custom eval.

**RDF-star and named graphs are overkill for the substrate.** Cicada's substrate is markdown+git+sqlite-vec, not a triplestore. The conceptual insights from RDF named graphs (context as 4th dimension, statement-level metadata) transfer cleanly to YAML fields, but the SPARQL machinery does not. The LLM is the query engine — it can reason over context-tagged YAML without needing SPARQL.

---

## Open questions

1. **How should the Sleep cycle detect that a context boundary has been crossed within a single episode?** (A conversation about FastAPI structure that drifts into life philosophy.) Should it split the episode into sub-episodes, or tag individual claims?

2. **Is "context" the right abstraction, or is "role" or "audience" more precise?** Honcho uses `(observer, observed)`; boyd uses "audience + setting". For a single-agent, single-user system like Cicada, "context" (life domain) may be sufficient — but if Cicada is ever extended to multi-agent scenarios, the Honcho model is more expressive.

3. **Should the `Rodrigo` entity be the root of a per-context sub-graph, or should context be distributed across all entity pages?** Option A (distributed context tags) scales better but loses the centralized view. Option C (sub-files) gives a centralized view but requires routing logic.

4. **How do cross-context abstract links decay?** If the link between "FastAPI service structure" (engineering) and "emergentism" (philosophy) was inferred by the Sleep cycle, how should confidence decay if neither belief is reinforced? Should cross-context links have their own decay rate?

5. **Can sqlite-vec support per-context embedding partitions efficiently?** Filtering by a `context` metadata field in sqlite-vec is possible (with a WHERE clause on a joined table) but has not been benchmarked in the current Cicada setup. This should be tested before committing to Option C.

6. **What is the minimum viable context taxonomy?** Starting with a closed set of 3-5 contexts (engineering, personal, academic/thesis, philosophical, cross) is safer than open-ended labels — consistent labels enable reliable filtering. Should contexts be a closed set like entity types were?

---

*Sources consulted:*
- [RDF Named Graphs Pattern, Data Incubator](https://patterns.dataincubator.org/book/named-graphs.html)
- [Oracle RDF Knowledge Graph Guide](https://docs.oracle.com/en/database/oracle/oracle-database/19/rdfrm/rdf-semantic-graph-overview.html)
- [Is RDF-star the best choice for reification? Ontotext](https://www.ontotext.com/blog/graphdb-users-ask-is-rdf-star-best-choice-for-reification/)
- [Easy and complex: RDF-star and Named Graphs (2022)](https://arxiv.org/pdf/2211.16195)
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956)
- [Graphiti Knowledge Graph Memory — Neo4j blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [Honcho Reasoning — Plastic Labs](https://honcho.dev/docs/v3/documentation/core-concepts/reasoning)
- [Faceted Id/entity — Danah boyd, MIT Media Lab](https://smg.media.mit.edu/people/danah/thesis/danahThesis.pdf)
- [Multi-perspective KG completion, ScienceDirect 2024](https://www.sciencedirect.com/science/article/abs/pii/S0020025524003517)
- [Benchmarking RDF Metadata Representations, IEEE 2021](https://ieeexplore.ieee.org/document/9364401/)
- [Context Collapse — Wikipedia](https://en.wikipedia.org/wiki/Context_collapse)
- [Provenance-Aware KG survey, Springer 2020](https://link.springer.com/article/10.1007/s41019-020-00118-0)
