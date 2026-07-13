# Cognitive-science memory models & Generative Agents

## TL;DR

- Cognitive science (ACT-R, SOAR, Tulving) splits memory into **episodic** (what happened, when, where), **semantic** (abstracted facts and patterns), and **procedural** (how to do things) — all three are distinct and all three matter for agent usefulness; most current LLM agents under-invest in semantic and procedural tiers.
- Park et al. 2023 (Generative Agents) showed that a flat timestamped memory stream plus **multi-signal retrieval** (recency × importance × relevance) plus periodic **reflection** (hierarchical abstraction from observations → insights) dramatically improved agent coherence — and these mechanisms transfer directly to Cicada's sleep cycle design.
- ACT-R's **activation equation** (base-level learning = recency + frequency of use + contextual spreading) is a more principled replacement for Cicada's current binary promotion gate and linear decay; it makes retrieval priority a continuous score rather than a threshold crossing.
- The hippocampus-to-neocortex consolidation model — fast-write episodic store, slow-write semantic store, offline replay to transfer important traces — is the best biological justification for Cicada's Awake/Sleep split, and also motivates a **dual-index** design: raw episode embeddings (hippocampal, high fidelity) + consolidated semantic embeddings (neocortical, compressed, higher confidence).
- BeliefMem (2026) and Honcho show that storing **probability distributions over conclusions** rather than single deterministic facts avoids self-reinforcing error and maps cleanly to Cicada's `confidence` field — extend it to per-field belief distributions, not just entity-level scores.
- Procedural memory is the most under-engineered tier in current agent systems (including Cicada); skills and preferences deserve a distinct, **executable** representation — not just another entity type — so an agent can pattern-match and directly apply them.

---

## Findings

### 1. The canonical four-memory taxonomy

The cognitive science literature converges on four stores that interact through a central executive (the LLM, in agent terms), drawn from Baddeley's model and Tulving's episodic/semantic distinction:

| Store | Cognitive science | LLM agent equivalent |
|---|---|---|
| **Working memory** | Phonological loop, visuospatial sketchpad, episodic buffer; ~7±2 chunks | Active context window (prompt) |
| **Episodic memory** | Timestamped autobiographical events; who/what/when/where; reconstructive | Raw episode files, conversation logs |
| **Semantic memory** | Decontextualized facts and patterns; no temporal tag | Entity pages, consolidated knowledge graph |
| **Procedural memory** | Implicit skills; condition-action rules; hard to verbalize | Skill/preference rules, agent tool-use patterns |

The critical design implication: **promotion should move memories along this axis**, not just from "raw chunk" to "entity page." A memory can and should exist at multiple levels simultaneously — the episodic record stays for provenance; the semantic abstraction is what gets queried for reasoning.

Sources: [Cognitive Architectures for LLMs, Bluetick Consultants](https://bluetickconsultants.medium.com/building-ai-agents-with-memory-systems-cognitive-architectures-for-llms-176d17e642e7) · [Memory for Autonomous LLM Agents survey](https://arxiv.org/html/2603.07670v1)

### 2. Generative Agents: the landmark paper (Park et al. 2023)

Park et al. built 25 LLM-driven agents in a simulated town. Their memory architecture has three components directly relevant to Cicada:

**a. Memory stream.** Every observation is stored as a natural-language sentence with a timestamp, an importance score (LLM-rated 1–10), and an embedding vector. There is no schema, no type system, no promotion gate — everything is recorded immediately. The agent never loses information at capture time.

**b. Multi-signal retrieval.** When the agent needs memories, a retriever scores all stored entries by:
- `recency`: exponential decay since last access (not last write)
- `importance`: the pre-assigned LLM score
- `relevance`: cosine embedding similarity to the current query

Final score = normalized linear combination of all three. This beats pure semantic search because purely semantic retrieval misses temporally important but semantically distant memories ("the crash two sessions ago").

**c. Reflection.** When the sum of importance scores for recent events crosses a threshold (roughly 2–3x per simulated day), the agent queries its own memory stream to generate higher-level insights ("Isabella seems to care about X"). Reflections are stored back into the stream with their own importance scores, building a hierarchy: raw observations → insights → higher-order patterns. This is the mechanism by which episodic facts consolidate into semantic beliefs.

Sources: [Generative Agents paper](https://arxiv.org/pdf/2304.03442) · [Paper review](https://artgor.medium.com/paper-review-generative-agents-interactive-simulacra-of-human-behavior-cc5f8294b4ac) · [Enhanced retrieval via cross-attention networks](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1591618/full)

### 3. ACT-R: activation-based retrieval and forgetting

ACT-R (Anderson's Adaptive Control of Thought-Rational) is the most empirically grounded cognitive architecture. Its declarative memory module uses a continuous activation score to decide what gets retrieved:

```
Activation(chunk) = BaseLevel(recency, frequency) + SpreadingActivation(context) + Noise
```

- **BaseLevel**: logarithmic decay — each past access contributes, with more recent accesses weighted more heavily. Frequency of past use raises the floor.
- **SpreadingActivation**: chunks semantically associated with the current goal state receive a boost (equivalent to embedding similarity in LLM implementations).
- **Retrieval threshold**: chunks below threshold are not retrieved — they are "forgotten" for this task. They remain in memory but are inaccessible until the threshold drops or context changes.

The key transfer to Cicada: **replace the binary promotion gate with a continuous activation score**. A first mention does not pass a gate — it just starts with low activation. Multiple mentions, high importance, recent access, and semantic relevance to current context all raise activation. Retrieval becomes a natural filter, not a hard schema rule.

Recent work (Human-Like Remembering and Forgetting in LLM Agents, 2025) implements ACT-R activation in an LLM agent by computing cosine similarity as spreading activation, tracking usage frequency per chunk, and applying temporal decay — showing human-like forgetting curves that improve downstream task performance.

Sources: [ACT-R + LLM paper](https://dl.acm.org/doi/10.1145/3765766.3765803) · [Hybrid personalization via ACT-R](https://arxiv.org/pdf/2505.05083) · [AI Meets Brain survey](https://arxiv.org/pdf/2512.23343)

### 4. SOAR: procedural memory and production rules

SOAR (State, Operator, And Result) separates knowledge sharply:
- **Working memory**: current problem state, instantiated as a symbolic structure.
- **Procedural memory**: production rules (`IF <conditions> THEN <actions>`). Rules fire automatically when their conditions match working memory.
- **Episodic/semantic memory**: later additions; store past states and factual knowledge respectively.

The SOAR insight for Cicada: procedural knowledge is **condition-action mappings**, not facts. "Rodrigo prefers snake_case in Python files" is not a fact about Rodrigo — it is a production rule `IF writing Python file THEN use snake_case`. Storing it as a `skill` entity (string in frontmatter) is under-powered. An executable representation — a short rule or template that the agent can directly pattern-match and apply — is more useful.

LLM integration of SOAR: when no applicable production rule exists, query the LLM for an action + a new rule to add to the library. When rules exist, sample and apply. This is the Voyager skill-library pattern, applied to preference memory.

Sources: [SOAR + LLM integration](https://www.turingpost.com/p/aia9) · [From LLM to Agent: memory + planning](https://dev.to/superorange0707/from-llm-to-agent-how-memory-planning-turn-a-chatbot-into-a-doer-35ck)

### 5. MemGPT: tiered memory with agent-controlled paging

MemGPT (Packer et al., now Letta) applies the OS virtual memory metaphor to agents:
- **Main context** (RAM): active window — system prompt, recent messages, currently retrieved records.
- **Recall storage** (disk): searchable database of all past messages.
- **Archival storage** (cold storage): vector-indexed documents and long-term knowledge.

The agent calls explicit functions (`archival_memory_search`, `core_memory_append`, etc.) to move data between tiers. This gives the agent metacognitive control over its own memory — it can decide what to promote or evict. However, orchestration failures are silent: wrong evictions degrade responses without obvious error signals.

Sources: [MemGPT / Letta overview](https://www.leoniemonigatti.com/papers/memgpt.html) · [Memory for LLM Agents survey](https://arxiv.org/html/2603.07670v1)

### 6. Hippocampal consolidation and the sleep analogy

The neuroscience of memory consolidation directly validates Cicada's Awake/Sleep split. The systems consolidation model proposes:
- **Hippocampus**: fast, high-fidelity binding of episodic traces (pattern separation). Writes quickly; high capacity for novel episodes. This is the Awake phase.
- **Neocortex**: slow, compressed, overlapping representations that capture statistical regularities across experiences. This is the Sleep phase.
- **Offline replay**: during sleep, sharp-wave ripples replay hippocampal traces; slow oscillations coordinate transfer to neocortex. Biologically, this selects important traces (via importance/novelty weighting) and integrates them into existing cortical structure.

For Cicada: the Sleep cycle should not just write entity pages — it should maintain two parallel indexes: a high-fidelity episodic index (raw embeddings, all episodes) and a consolidated semantic index (entity-page embeddings, post-sleep). Retrieval can query both and weight by confidence/recency.

Sources: [AI Meets Brain survey](https://arxiv.org/pdf/2512.23343) · [TiMem temporal-hierarchical consolidation](https://arxiv.org/pdf/2601.02845) · [Systems memory consolidation during sleep, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12576410/)

### 7. BeliefMem: probabilistic beliefs vs. deterministic facts

BeliefMem (2026) replaces single-conclusion memory entries with belief distributions. Instead of storing "Rodrigo uses Postgres," it stores `{Postgres: 0.8, SQLite: 0.4}` — multiple candidate values with probabilities updated via noisy-OR as evidence arrives.

This directly addresses Cicada's conflict-resolution problem. Contradictory information doesn't force a winner; it creates a multi-hypothesis state that the agent surfaces to the user (via nudges) or resolves incrementally as evidence accumulates. The data model per memory slot:
```
attribute: preferred_db
candidates:
  - value: postgres
    probability: 0.82
    last_updated: 2026-03-20
    supporting_episodes: [ep_2026-01-10_001, ep_2026-02-14_003]
  - value: sqlite
    probability: 0.41
    last_updated: 2026-04-01
    supporting_episodes: [ep_2026-04-01_002]
```

Source: [BeliefMem paper](https://arxiv.org/html/2605.05583v1)

### 8. Honcho: the observer/observed user model

Honcho (Plastic Labs) formalizes a user-model architecture that resonates with Rodrigo's multi-context-self intuition. Its core design:
- All entities (human users and AI agents alike) are **peers**.
- Memory is stored indexed by `(observer, observed)` pairs — so "what the coding agent knows about Rodrigo" vs. "what the life-coach agent knows about Rodrigo" are separate indexed collections, even though both are about the same person.
- The system extracts **conclusions** (not raw chunks) from conversations via async background reasoning, storing them as structured peer representations.
- Retrieval combines BM25 + vector similarity, but the output is a reasoned synthesis, not raw chunks.

The observer/observed model naturally handles Rodrigo's context-dependent self: engineer-Rodrigo and family-Rodrigo can be separate observer contexts that cross-reference each other without collapsing into a single flat entity page.

Sources: [Honcho GitHub](https://github.com/plastic-labs/honcho) · [Honcho / Hermes Agent docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/honcho)

### 9. Reflection and self-consistency risks

Reflexion (Shinn et al. 2023) showed that storing verbal post-mortems after failures and surfacing them on retry improved HumanEval from 80% to 91%. Generative Agents showed reflection trees build useful higher-order beliefs.

The risks that concrete research flags:
- **Summarization drift**: each compression pass silently discards low-frequency but high-importance details. Safety-critical facts ("never write to production DB directly") vanish after enough cycles. Mitigation: pin certain memories as `immutable: true` / never-compress.
- **Self-reinforcing error**: a wrong reflection persists indefinitely. Mitigation: require reflections to cite specific episode IDs (auditable backlinks); a reflection without evidence support decays faster.
- **Reflection entrenchment**: agent may falsely generalize that certain approaches "always fail." Mitigation: set a max-confidence ceiling on reflections derived from <N episodes.

Sources: [Memory for LLM Agents survey](https://arxiv.org/html/2603.07670v1) · [Forgetful but Faithful](https://arxiv.org/html/2512.12856v1)

---

## Concrete data-model ideas for Cicada

These translate directly to markdown+git+sqlite-vec:

### Idea 1: Replace promotion gate with ACT-R-style activation score
Every mention writes an episodic record (no gate). Each entity/fact gets an `activation` score computed at retrieval time:
```
activation = log(sum of recency-weighted access events) + spreading(query_similarity) + importance_base
```
Store in sqlite-vec as a metadata column, recomputed on query. The "promotion" that creates an entity page becomes automatic at activation > threshold, not at mention-count > 2. This is more principled and continuous.

### Idea 2: Dual-index retrieval (episodic + semantic)
Maintain two sqlite-vec tables:
- `episodes_index`: raw episode embeddings, high fidelity, never deleted
- `entities_index`: entity page embeddings, post-sleep, higher confidence

On `/ask`, query both. Weight episodic results by recency+importance, semantic results by confidence. Merge and deduplicate. This mirrors hippocampal + neocortical retrieval.

### Idea 3: Reflection nodes in the entity graph
After sleep consolidation, create a separate entity type `reflection` (or `insight`) that is derived from N episode IDs, holds a higher-level abstraction, and cites its sources. Example:
```yaml
type: reflection
derived_from_episodes: [ep_2026-01-10_001, ep_2026-02-14_003]
derived_from_entities: [python-preferences]
confidence: 0.75
body: "Rodrigo consistently restructures FastAPI routers before adding new endpoints, suggesting a preference for architecture-first refactoring."
```
Reflections decay faster than entity pages if not confirmed by new episodes.

### Idea 4: Per-field belief distributions instead of entity-level confidence
Extend frontmatter to allow per-field belief slots for contested or uncertain attributes:
```yaml
beliefs:
  preferred_db:
    - value: postgres
      probability: 0.82
      episodes: [ep_2026-01-10_001]
    - value: sqlite
      probability: 0.41
      episodes: [ep_2026-04-01_002]
```
The entity-level `confidence` score becomes the mean of field-level probabilities, preserving backward compat with the existing 1,882 pages.

### Idea 5: Procedural memory as executable rule files
Replace `skill`-type entity pages with a separate `memory/procedures/` directory. Each file is a short IF-THEN rule:
```yaml
---
trigger: "writing Python code in any repo"
condition: "variable names visible"
action: "use snake_case; never camelCase"
confidence: 0.95
source_episodes: [ep_2026-02-01_003]
---
```
The sleep cycle extracts these from episodes specifically looking for pattern+preference signals. The `/ask` endpoint retrieves applicable procedures separately from factual entities and injects them into the system prompt as explicit behavioral constraints.

### Idea 6: Observer-context scoping for multi-faceted identity
Add an optional `context` field to entities and the sqlite-vec index. "Rodrigo as engineer" and "Rodrigo as son" share the same entity ID but different context facets:
```yaml
# entities/rodrigo-sagastegui.md
facets:
  engineer:
    tags: [python, fastapi, distributed-systems]
    related: [Cicada, IE University]
  family:
    tags: [Madrid, siblings]
    related: [personal-projects]
```
The `/ask` endpoint accepts a `context` param. Cross-context links are explicit wikilinks with a `cross-context: true` annotation.

### Idea 7: Multi-signal retrieval scoring (Generative Agents style)
Extend the sqlite-vec query function to score:
```
final_score = α * recency_score + β * importance_score + γ * embedding_similarity
```
Default weights: α=0.3, β=0.3, γ=0.4. Let the sleep cycle tune α and β per-entity based on how often it was accessed recently vs. how important it was at creation time. Store `importance` as a float in episode frontmatter at capture time (LLM-rated 1–10 normalized).

---

## Tradeoffs / where it fails

- **ACT-R activation is expensive at retrieval time.** Computing log-sum over all past access events for every candidate chunk requires either maintaining running tallies (adds write complexity) or iterating at query time (adds latency). Mitigation: pre-compute and cache activation scores, update incrementally on each access.

- **Reflection quality degrades without grounding.** The sleep cycle's LLM may generate plausible but false reflections, especially early in the memory's life when few episodes exist. No cognitive architecture has a good solution to this; the best mitigation is citation enforcement and confidence ceilings.

- **Per-field belief distributions conflict with human-readable markdown.** Nested YAML probability tables are ugly for a human viewing the file in Obsidian. The practical tradeoff: keep entity body human-readable, put belief distributions in a companion `.beliefs.yaml` sidecar file in the same folder. Or: only use belief distributions for fields the system has flagged as contested.

- **Observer-context facets fragment retrieval.** If Rodrigo-engineer and Rodrigo-family are separate facets, a query without context param may miss cross-context links. The `/ask` endpoint needs a context-inference step, or it defaults to returning all facets ranked by relevance.

- **Procedural memory in separate files creates a three-way retrieval problem.** Episodes, entities, and procedures must all be queried and merged. The implementation cost is real. Start with procedures as a special entity subtype, migrate to separate directory once the pattern is validated.

- **The 1,882 existing entity pages don't have activation scores or belief distributions.** Migration is incremental: old pages keep their single `confidence` field; the sleep cycle only adds `beliefs:` blocks when it detects a conflict. Activation scores can be bootstrapped from `last_referenced` and `source_episodes` count.

- **Reflection entrenchment is hard to detect.** A confident, well-cited reflection can survive for cycles even after the underlying behavior changes. Proposed fix: reflections have a `max_ttl_cycles` field; after that many sleep cycles without fresh episode support, confidence drops by 0.1/cycle.

---

## Open questions

1. **What is the right importance signal at episode capture time?** Park et al. use an LLM call per observation to rate importance 1–10. This adds latency and cost to the Awake phase, which is supposed to be "no LLM." Alternative: use keyword heuristics at capture + LLM rating deferred to sleep cycle. How much does deferred importance scoring hurt retrieval?

2. **How many reflection tiers are useful?** Generative Agents build a tree: observations → insights → higher-order patterns. For a single-user personal memory, is one reflection tier (episodes → beliefs) sufficient, or does a second tier (beliefs → life-patterns) add value without adding noise?

3. **Can the same sqlite-vec index handle both episodic and semantic retrieval?** Using metadata columns to tag rows as `type=episode` vs `type=entity` and filtering at query time is the simplest approach — but it conflates two very different embedding distributions. A single embedding model (EmbeddingGemma-300M) trained on generic text may not optimally represent both raw conversational episodes and structured knowledge claims.

4. **Should procedures be extracted by the sleep cycle or captured explicitly by the user?** Automatic extraction risks false positives ("user once asked for snake_case" → permanent rule). Explicit capture via a `/procedure add` command gives user authority but adds friction. A hybrid (auto-suggest + user confirm via nudge) is most coherent with Cicada's existing UX principles.

5. **How does BeliefMem interact with Cicada's wikilink graph?** If an entity's attribute is contested (probability distribution), wikilinks FROM that attribute to other entities become uncertain too. Does the graph model need probabilistic edges? This may be over-engineering for Cicada's current scale.

6. **Is the observer/observed (Honcho-style) model overkill for a single-user system?** For Rodrigo, the "observer" is always the same agent — the Cicada Bookworm. The value of multi-observer modeling would only appear if multiple specialized agents (coding agent, life-coach agent) maintain separate belief models about the user. That's a valid future direction but probably not MVP.
