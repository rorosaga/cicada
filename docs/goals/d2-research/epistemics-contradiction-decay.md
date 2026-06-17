# Confidence, provenance, contradiction, forgetting

Research sweep on how agent memory systems should model epistemic trust — confidence scoring, source provenance, contradiction/invalidation, and forgetting/decay. Covers truth-maintenance theory, recent LLM-agent memory papers (2024–2026), and concrete implications for Cicada's markdown+git+sqlite-vec substrate.

---

## TL;DR

- **Bi-temporal fact modeling** (valid_from / valid_to / observed_at / recorded_at) is the strongest known mechanism for contradiction without deletion: superseded facts are closed, not erased, so history and audit are free.
- **Source hierarchy beats a single confidence float**: trust should encode *origin* (user-stated > agent-inferred > LLM-reflected) as a separate field from *certainty* (0.0–1.0), because the two decay differently.
- **The three-signal retrieval score** from Park et al. Generative Agents — `score = recency × importance × relevance` — is now the de facto standard and demonstrably beats cosine-only retrieval; Cicada's Sleep cycle should compute and store all three.
- **Episodic ground-truth preservation** (MemMachine, TierMem) shows that keeping raw episodes and treating extracted facts as *derived, lossy* views prevents compounding extraction errors and enables re-derivation.
- **Staleness in high-confidence memories is the hardest open problem**: decay works for low-relevance noise, but a highly-retrieved stale fact (e.g., "Rodrigo works at X") is actively dangerous; no system has solved this cleanly.
- **Rashomon Memory / multi-perspective argumentation** offers a principled way to preserve conflicting beliefs without forced reconciliation — relevant to Cicada's context-dependent identity problem.

---

## Findings

### 1. Truth Maintenance Systems and Defeasible Reasoning (Classical Foundation)

Truth Maintenance Systems (TMS), introduced by Doyle (1979) and extended through Reason Maintenance Systems ([Wikipedia: Reason maintenance](https://en.wikipedia.org/wiki/Reason_maintenance)), provide the theoretical backbone for belief revision in AI. A TMS tracks the logical support structure for each belief: if a supporting premise is retracted, all beliefs that depended on it are automatically suspended. This is *non-monotonic*: later information can invalidate earlier conclusions without deleting them.

Defeasible logic (DeLP) extends this with argumentation: competing conclusions are evaluated by constructing attack chains between arguments, and the system selects the "winning" interpretation. The recent paper [Exploring formal defeasible reasoning of LLMs (ScienceDirect, 2025)](https://www.sciencedirect.com/science/article/abs/pii/S0950705125006100) finds that current LLMs struggle with formal defeasible inference but that Chain-of-Thought prompting substantially improves this.

**Key classical insight for Cicada**: beliefs should carry their *justification structure*, not just a confidence float. When a justification is invalidated (e.g., "I thought X because Rodrigo said Y, but Y was corrected"), the dependent belief should be automatically flagged for review — not just decayed.

### 2. Bi-Temporal Fact Modeling (the strongest practical mechanism)

The most significant engineering idea from the recent literature is **bi-temporal knowledge graph modeling**, implemented by Zep/Graphiti ([Graphiti - Neo4j blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/), [Zep temporal KG explainer](https://www.getzep.com/ai-agents/temporal-knowledge-graph/), [Graph-based Agent Memory survey, arXiv 2602.05665](https://arxiv.org/html/2602.05665v1)).

Each fact/relationship carries **four timestamps**:

| Field | Meaning |
|-------|---------|
| `valid_from` | When the fact became true in the world |
| `valid_to` | When it stopped being true (null = currently true) |
| `observed_at` | When the source stated/mentioned it |
| `recorded_at` | When the system ingested it (provenance) |

When new information contradicts an existing fact, the system **closes** the old fact's `valid_to` rather than deleting or overwriting it. This means:
- Point-in-time queries work: "what did Cicada believe about X on 2025-03-01?"
- Contradiction is never data loss — it is a temporal state transition
- The `valid_to` closing event itself carries a `source_episode` pointer, so you know *why* the belief changed

This directly eliminates "the single most common cause of agent hallucination" — serving contradictory facts simultaneously because you can always retrieve only facts where `valid_to IS NULL` (currently believed).

### 3. Source Hierarchy and Trust Levels

[From Lossy to Verified (TierMem, arXiv 2602.17913)](https://arxiv.org/html/2602.17913v1) and [Provenance tracing survey (arXiv 2606.04990)](https://arxiv.org/html/2606.04990) establish a source-trust hierarchy that should be encoded explicitly:

```
user-stated (explicit assertion)       → highest trust
user-implied (inferred from behavior)  → high trust
agent-extracted (Sleep LLM extraction) → medium trust
agent-reflected (LLM generalization)   → lower trust
third-party/RSS/external               → lowest trust, flagged
```

Key insight: **trust and certainty are orthogonal**. A user statement can be certain but wrong (they misspoke). An agent inference can be uncertain but from high-quality signals. They should be separate fields:

- `source_trust`: enumerated origin tier (above)
- `confidence`: 0.0–1.0 epistemic certainty

The [SSGM framework (arXiv 2603.11768)](https://arxiv.org/html/2603.11768v1) goes further and proposes cryptographic provenance (`σ(μ)`) — overkill for a single-user system, but the principle matters: **provenance should be unforgeable**. In Cicada, git commit hashes already provide this for Sleep-cycle writes.

### 4. The Three-Signal Retrieval Score (Park et al. de facto standard)

[Generative Agents: Interactive Simulacra of Human Behavior (Park et al., arXiv 2304.03442)](https://arxiv.org/pdf/2304.03442) introduced the composite retrieval score that has become the field standard:

```
score(m) = α_recency × recency(m) + α_importance × importance(m) + α_relevance × relevance(m)
```

- **Recency**: exponential decay since last access, factor ≈ 0.995/hr. Strongly penalizes memories never retrieved.
- **Importance**: integer score (1–10) assigned by LLM at write time ("how important is this memory on a scale of 1–10?"). Distinguishes mundane from core.
- **Relevance**: cosine similarity between query embedding and memory embedding.

All three α weights = 1 in the original implementation; downstream systems (Mem0, MemoryBank) tune these. The [survey (arXiv 2603.07670)](https://arxiv.org/html/2603.07670v1) notes this substantially outperforms pure cosine similarity.

**For Cicada**: `importance` is already partially captured by `confidence`. `recency` is partially captured by `last_referenced`. `relevance` is the sqlite-vec cosine score. The gap: these are not *combined* at retrieval time, and `importance` is never LLM-scored at write time.

### 5. Temporal Decay Strategies

Multiple strategies exist, with different tradeoff profiles:

**Ebbinghaus forgetting curve** ([FOREVER paper, arXiv 2601.03938](https://arxiv.org/pdf/2601.03938), [MemoryBank]): `retention = e^{-t/S}` where S is "memory strength" (increases with each retrieval). This mirrors human memory well. Frequent retrieval strengthens; neglect weakens.

**Weibull-based decay** ([SSGM, arXiv 2603.11768](https://arxiv.org/html/2603.11768v1)): `w(Δτ) = exp(-(Δτ/η)^κ)`. Parameterizable shape — can model fast initial drop or slow sustained decay. Below a freshness threshold `θ_fresh`, items are pruned from active retrieval.

**Explicit TTL / expiry timestamps**: Rather than continuous decay, facts carry `expires_at` set at write time (useful for deadline-type entities) or updated by Sleep logic. Clean, binary, easy to query.

**Per-entity decay_rate** (Cicada's current approach): A `decay_rate` field in frontmatter that modulates how fast confidence drops. This is reasonable but conflates decay with confidence — they should arguably be computed separately and combined for retrieval ranking.

**Critical gap identified by [mem0 blog (2026)](https://mem0.ai/blog/state-of-ai-agent-memory-2026)**: decay works for low-relevance noise. High-relevance stale memories (employer, city of residence, relationship status) remain confidently wrong because their high retrieval frequency *prevents* decay. This is unsolved. The best available mitigation: staleness detection via `valid_to` closing events, not confidence decay.

### 6. Contradiction Detection

Systems handle contradiction in three ways:

**Temporal invalidation** (Graphiti, Zep): close the old fact's `valid_to`. No deletion. Works well for factual updates ("switched from Postgres to SQLite"). Does not work for genuinely conflicting simultaneous beliefs.

**TMS-style logical contradiction check** ([SSGM](https://arxiv.org/html/2603.11768v1)): during write validation, if `new_fact ∧ core_beliefs ⊧ ⊥`, the write is rejected. Protects core beliefs from hallucinated overwrites. Requires a notion of "core" vs. "soft" beliefs.

**Multi-perspective preservation** ([Rashomon Memory, arXiv 2604.03588](https://arxiv.org/pdf/2604.03588)): instead of resolving contradictions, preserve both perspectives tagged by viewpoint/context. Argumentation semantics determine which perspective is "acceptable" for a given query. This is the most honest approach when two things are genuinely both true (different contexts, different times in life).

[ContraDoc benchmark](https://arxiv.org/html/2510.03418v2) showed GPT-4 struggles with subtle internal inconsistencies in long documents — automatic contradiction detection via LLM is unreliable. Temporal invalidation + human-in-the-loop (nudges) is more robust.

### 7. Provenance-Aware Tiered Memory (TierMem / MemMachine)

[TierMem (arXiv 2602.17913)](https://arxiv.org/html/2602.17913v1) and [MemMachine (arXiv 2604.04853)](https://arxiv.org/html/2604.04853v1) both converge on a key architectural insight: **extracted facts are lossy views of raw episodes**. Keeping only extracted facts causes compounding errors (each extraction can introduce mistakes that compound through later LLM calls).

The dual-tier solution:
- **Tier 2 (immutable log)**: raw episodes, append-only, ground truth. Never modified.
- **Tier 1 (semantic cache)**: extracted facts/summaries with provenance pointers back to Tier 2 page IDs.

On retrieval: use Tier 1 (cheap). When Tier 1 evidence is insufficient, escalate to Tier 2 (expensive, but always correct). This is very close to Cicada's existing design (episodes/ as raw log, entities/ as derived), but Cicada currently lacks the explicit provenance pointer from each entity field back to the originating episode sentence.

### 8. Honcho's Observer/Observed Model

[Honcho by Plastic Labs](https://github.com/plastic-labs/honcho) takes a distinct approach: the memory system runs as an *observer* of the conversation rather than being embedded in it. Rather than extracting facts, it builds a running "user model" — a coherent picture of the user's beliefs, preferences, communication style, and contradictions — by reasoning about conversations after they happen ("dreaming").

The observer/observed (peer) model is philosophically elegant for Cicada's context-dependent identity problem: Rodrigo-as-engineer and Rodrigo-as-thesis-student are different "observed" facets of the same person, and the observer (Cicada) maintains both without forcing them to be consistent. Honcho's implementation uses PostgreSQL+pgvector+Redis+async LLM workers — heavier than Cicada's substrate, but the *idea* of treating user modeling as a separate reasoning process (not just extraction) is directly applicable.

---

## Concrete data-model ideas for Cicada

These are concrete proposals for evolving Cicada's markdown frontmatter and sqlite-vec metadata without migrating the substrate.

### A. Add bi-temporal fields to entity frontmatter

```yaml
---
# existing fields...
confidence: 0.82
# NEW: explicit temporal validity
valid_from: 2026-01-15          # when this belief became true (not when recorded)
valid_to: null                   # null = currently believed; set when superseded
recorded_at: 2026-01-15T02:00Z  # when Sleep cycle wrote this (already in git, but explicit is better)
# NEW: source trust tier
source_trust: agent_extracted    # user_stated | user_implied | agent_extracted | agent_reflected | external
# NEW: importance score (LLM-assigned at write time, 1-10)
importance: 7
# NEW: justification pointer (what belief/episode this depends on)
derived_from:
  - ep_2026-01-15_002            # already in source_episodes; rename or alias
  - entity: MongoDB               # if derived from an existing entity claim
```

When a Sleep cycle detects a contradicting belief, it does not update `confidence`. It:
1. Sets `valid_to` on the old version
2. Creates a new entity page version with the new belief and `valid_from` set
3. Git commits both changes with a structured message linking the two

### B. Extend sqlite-vec metadata per chunk

Each LEANN/sqlite-vec chunk should carry:
```json
{
  "chunk_id": "ep_2026-01-15_002_chunk_003",
  "source_trust": "user_stated",
  "importance": 6,
  "recorded_at": "2026-01-15T02:00Z",
  "valid_from": "2026-01-15",
  "valid_to": null
}
```

At retrieval, the /ask endpoint computes:
```
retrieval_score = recency_score × importance_norm × cosine_similarity
```
where `recency_score = 0.995^(hours_since_last_retrieval)` and `importance_norm = importance / 10`.

### C. Contradiction nudge with temporal invalidation

When Sleep cycle extraction produces a belief that contradicts an existing active entity:
1. Do NOT silently overwrite. 
2. Write a `nudges/conflict_YYYYMMDD_NNN.md` with both the old belief (+ its `valid_from`, `source_episodes`) and the new belief.
3. User resolves → Sleep closes old `valid_to`, opens new entity version.
4. If user doesn't resolve within N days → apply recency heuristic (newer wins) but flag as auto-resolved.

### D. Source-trust as a decay modifier

Per-entity `decay_rate` should be modulated by `source_trust`:
```
effective_decay = base_decay_rate × trust_multiplier[source_trust]
# user_stated: 0.5 (decay slowly — user said it explicitly)
# agent_extracted: 1.0 (baseline)
# agent_reflected: 1.5 (decay faster — generalization, may be wrong)
# external: 2.0 (decay fast — RSS/web, likely stale)
```

### E. Importance scoring at Sleep write time

The Sleep cycle LLM prompt should ask, for each extracted entity/belief:
> "On a scale of 1–10, how important is this information to Rodrigo's long-term memory? Consider frequency of mention, emotional weight, and connection to goals."

Store as `importance: N` in frontmatter. Use in retrieval ranking.

### F. Two-tier retrieval in /ask

```
1. Query sqlite-vec with recency × importance × cosine score
2. If top-k confidence is low (all scores < threshold) → escalate to raw episodes
3. Return citations with source_trust and valid_to status
4. Flag any retrieved belief where valid_to IS NOT NULL ("this belief was superseded on DATE")
```

---

## Tradeoffs / where it fails

**Bi-temporal overhead**: Maintaining `valid_from`/`valid_to` on ~1,882 existing entity pages requires a migration script. Pages don't have versioned "fact lines" — the whole page is a unit. Bi-temporal modeling works cleanly on *claims* (triples), not on freeform markdown paragraphs. A pragmatic middle ground: only frontmatter fields are bi-temporal; the body text uses git blame for line-level history (already implemented).

**Defeasible reasoning requires structured facts**: TMS and argumentation semantics work on explicit logical propositions. Cicada's entities are semi-structured markdown, not formal propositions. The LLM effectively acts as the inference engine, which means contradiction detection is probabilistic not formal. This is fine for a single-user system but means you can't guarantee contradiction-freeness.

**Importance scores are noisy**: LLM-assigned importance scores (1–10) vary between Sleep cycles for similar content. They need normalization and possibly human calibration for the first N entities. Not a blocker but means the retrieval weighting has non-deterministic noise.

**Rashomon multi-perspective approach adds graph complexity**: Preserving conflicting beliefs rather than resolving them grows the graph and creates retrieval ambiguity. If Cicada doesn't know which perspective is "current," it might surface outdated beliefs. Requires explicit context tagging (which facet is this belief about: engineer-Rodrigo, thesis-Rodrigo, etc.) at write time — which is additional Sleep cycle burden.

**Honcho-style "dreaming" is expensive**: Async background reasoning across all ingested conversations requires sustained LLM calls. Cicada's Sleep cycle does this in batch (acceptable), but real-time dreaming would need a separate always-on process. Not compatible with current architecture without a background daemon.

**High-relevance stale facts**: As noted by mem0 (2026), decay does not help here. The only known mitigations are: (a) explicit `valid_to` closing triggered by user confirmation or new contradicting evidence, and (b) periodic review nudges for high-confidence beliefs older than a threshold (e.g., `confidence > 0.8 AND last_referenced < 90 days ago → generate staleness nudge`).

---

## Open questions

1. **Granularity of bi-temporal modeling**: Should `valid_from`/`valid_to` apply to the whole entity page, or to individual frontmatter fields, or to individual paragraphs in the body? A per-field approach is most precise but hardest to implement in freeform markdown. Git blame covers body-line history; frontmatter fields are the sweet spot.

2. **Context tagging for multi-faceted identity**: Rodrigo's observation that he holds different beliefs per context (engineer vs. family vs. philosophy) maps well to Rashomon's multi-perspective model. But what is the right *labeling scheme* for contexts? Should contexts be typed entities themselves? Should they be tags? Is this too much structure to extract reliably?

3. **When should contradiction auto-resolve vs. queue for user?**: Simple factual updates (city of residence, employer) should probably auto-resolve with recency heuristic. Nuanced contradictions (changed opinion about a framework, relationship change) should queue. What is the decision rule? Can the Sleep LLM reliably classify which type a contradiction is?

4. **How does importance decay?**: In Park et al., importance is fixed at write time. But a past deadline (importance=10 when created) is importance=0 after the date passes. Should importance have its own temporal function, or should `valid_to` handle this?

5. **Does the promotion gate interact with bi-temporal validity?**: If a pending entity (sub-threshold) is never promoted, should it carry temporal markers? The entity doesn't exist yet in the graph. Should LEANN chunks for sub-threshold mentions carry `valid_to`-style expiry?

6. **Provenance for user manual edits**: When Rodrigo edits an entity page directly (companion app or Obsidian), the `source_trust` should be `user_stated` and the `valid_from` should be the edit timestamp. But the Sleep cycle currently doesn't re-process manually edited pages differently. Needs a detection mechanism (git blame diff actor = "user" vs. "sleep").

---

*Sources consulted:*
- [Reason maintenance — Wikipedia](https://en.wikipedia.org/wiki/Reason_maintenance)
- [Belief Revision: LLM Adaptability — ResearchGate](https://www.researchgate.net/publication/381851536_Belief_Revision_The_Adaptability_of_Large_Language_Models_Reasoning)
- [Memory for Autonomous LLM Agents — arXiv 2603.07670](https://arxiv.org/html/2603.07670v1)
- [SSGM: Governing Evolving Memory — arXiv 2603.11768](https://arxiv.org/html/2603.11768v1)
- [FOREVER: Forgetting Curve-Inspired Replay — arXiv 2601.03938](https://arxiv.org/pdf/2601.03938)
- [Beyond Dialogue Time: Temporal Semantic Memory — arXiv 2601.07468](https://arxiv.org/pdf/2601.07468)
- [Graph-based Agent Memory Survey — arXiv 2602.05665](https://arxiv.org/html/2602.05665v1)
- [Rashomon Memory — arXiv 2604.03588](https://arxiv.org/pdf/2604.03588)
- [MemMachine — arXiv 2604.04853](https://arxiv.org/html/2604.04853v1)
- [TierMem: Provenance-Aware Tiered Memory — arXiv 2602.17913](https://arxiv.org/html/2602.17913v1)
- [Provenance tracing survey — arXiv 2606.04990](https://arxiv.org/html/2606.04990)
- [Generative Agents (Park et al.) — arXiv 2304.03442](https://arxiv.org/pdf/2304.03442)
- [State of AI Agent Memory 2026 — mem0.ai](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Graphiti knowledge graph memory — Neo4j blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [Zep: Temporal Knowledge Graph — getzep.com](https://www.getzep.com/ai-agents/temporal-knowledge-graph/)
- [Honcho — Plastic Labs / GitHub](https://github.com/plastic-labs/honcho/blob/main/CLAUDE.md)
- [Practical Guide to LLM Agent Memory — Towards Data Science](https://towardsdatascience.com/a-practical-guide-to-memory-for-autonomous-llm-agents/)
- [LegalWiz contradiction detection — arXiv 2510.03418](https://arxiv.org/html/2510.03418v2)
- [Defeasible reasoning of LLMs — ScienceDirect 2025](https://www.sciencedirect.com/science/article/abs/pii/S0950705125006100)
