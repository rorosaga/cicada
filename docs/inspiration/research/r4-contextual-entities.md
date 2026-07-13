# Contextual / multi-dimensional entities vs separate graphs

> Research note for Cicada's improvement wave. Companion to
> [`honcho.md`](../honcho.md) and [`gbrain.md`](../gbrain.md). Addresses Rodrigo's
> insight: *he holds different, overlapping beliefs about himself and things
> depending on context (engineer-self vs family-self vs life-philosophy), and a
> great memory system should also draw abstract relationships between
> not-obviously-related things.* This maps to two distinct design questions:
> (1) how to represent the **same subject under multiple contexts**, and
> (2) how to **surface non-obvious cross-context connections**. They are related
> but should not be conflated — (1) is a storage/modeling decision, (2) is a
> retrieval/synthesis decision.

## TL;DR

- **Recommend (a) with a twist: one canonical entity page + lightweight named
  "facet" sub-sections (lenses), NOT separate per-context graphs.** Separate
  graphs (option b) fragment identity, duplicate maintenance, and fight Cicada's
  "filesystem as single source of truth" and Obsidian-compatibility decisions.
  One entity with context-scoped dimensions keeps the graph navigable while
  letting each facet decay, carry confidence, and cite provenance independently.
- **Honcho's `(observer, observed)` keying (c) is the right *abstraction*, but
  for single-user Cicada it collapses into `(context, subject)` — a "lens"
  rather than a peer.** Don't build peers now (D4 is research-only). Do borrow
  the idea that *a representation is perspectival and scoped*, and design the
  facet model so a future `observer` dimension is a clean generalization.
- **The KG literature already names this**: context-dependent entity
  representations (an entity has different "senses" per relation/context) and
  **role-based modeling** (one object plays many context-bound roles). Both
  argue for *one identity, many context-scoped views* — supporting option (a)
  over (b). RDF's answer (named graphs / quads / reification) is the "add a
  context dimension to each statement" pattern; Cicada can do the markdown
  equivalent without RDF machinery.
- **The "connect not-obviously-related things" wish is a separate, retrieval-time
  feature**, best served by the planned ask/dialectic endpoint (D3) doing
  analogical/cross-facet synthesis over LEANN + graph, *not* by changing storage.
  Storing facets well makes this feature *possible*; it doesn't deliver it.
- **Confidence: medium-high on the modeling recommendation** (well-supported by
  KG + roles literature and by Cicada's own constraints); **medium on the exact
  YAML shape** (a design sketch, not validated against real episodes);
  **lower on the cross-connection retrieval** (genuinely open research, marked
  below).

## Findings

### 1. The four candidate approaches, assessed

**(a) One entity with per-context dimensions / sub-nodes.**
The KG-embedding literature directly supports the premise that one entity
legitimately has *multiple senses depending on context*. Static single-vector
embeddings are criticized precisely because "all senses of a polysemous entity
have to share the same representation"; context-dependent models (KGCR, DOLORES,
deep contextualized KG embeddings) encode an entity differently depending on the
relation/neighborhood it appears in — e.g. the same entity clusters by
*nationality* under one relation and by *profession* under another
([DOLORES, arXiv:1811.00147](https://arxiv.org/pdf/1811.00147);
[Deep Contextualized KG Embeddings, OpenReview](https://openreview.net/pdf?id=ajrveGQBl0);
[Contextual Views, arXiv:2508.02413](https://arxiv.org/html/2508.02413v1)).
The conceptual takeaway for Cicada (which does *not* need embeddings for this —
it's markdown): identity is one node, but its *properties are context-scoped*.

**Role-based modeling** makes the same point in plain conceptual-modeling terms
and is the closest match to Rodrigo's "engineer-self vs family-self": "roles
capture both context-dependent and collaborative behavior of objects… one object
may play several roles at a time," and crucially "a role type characterizes only
its properties *in a certain context*" — unlike a class, which fully describes an
individual ([Roles as Entity Types, ResearchGate](https://www.researchgate.net/publication/221268476_Roles_as_Entity_Types_A_Conceptual_Modelling_Pattern);
[An Analysis of Roles: Towards Ontology-Based Modelling](https://www.academia.edu/6524087/An_Analysis_of_Roles_Towards_Ontology_Based_Modelling);
[A Good Role Model for Ontologies](https://software-lab.org/publications/ijeis2010.pdf)).
A role is always bound to a *context (an "institution")* — which is exactly the
"engineer context", "family context", "life-philosophy context" framing.
This is strong, decades-old conceptual-modeling support for **one identity,
many context-bound facets**.

**(b) Separate per-context memory graphs that cross-reference.**
This is the role-modeling "context" taken to the extreme of separate stores.
Honcho *does* support genuinely separate representations (Alice-about-Bob is a
different collection than Charlie-about-Bob), but note that's driven by genuine
*epistemic separation* (different observers literally saw different messages) —
not by a single user's multiple self-facets. For a single user, splitting into
separate graphs buys little and costs a lot: duplicated entities, cross-graph
sync, broken wikilink locality, and it directly contradicts Cicada's
"filesystem as single source of truth" and Obsidian-compatibility decisions.
The KG-completion work is explicit that the *value* is in the shared structure
("you shall know an entity by the relationships it involves") — fragmenting the
graph destroys exactly the cross-facet edges that make connection-finding
possible. **Assessed as the weakest option for Cicada.**

**(c) Honcho's `(observer, observed)` representations.**
Verified from the docs: representations are scoped at two levels — a **global**
peer-level model (`observe_me`, built from everything a peer ever said) and a
**session-scoped / relational** model (`observe_others`, built only from
messages that observer actually witnessed). Keying is directional and
asymmetric; perspectives diverge because observation histories differ
([Honcho — Peer Representations](https://honcho.dev/docs/v3/documentation/core-concepts/representation);
[plastic-labs/honcho DeepWiki](https://deepwiki.com/plastic-labs/honcho)).
The mechanism that matters for Cicada is the **global + scoped split**: a
canonical view *plus* context-scoped views layered on top. For single-user
Cicada there is effectively one observer (the user), so `(observer, observed)`
degenerates to `(context, subject)` — a **lens**. The peer machinery is the
right *generalization target* (D4), not something to build now.

**(d) KG "context/perspective" modeling generally.**
RDF's canonical answers are **named graphs, quads, and reification** — all
variations of "attach a context/provenance dimension to a statement so the same
triple can be true-in-context-X and superseded-in-context-Y." Named graphs are
"a reformulation of quads with clearer semantics," used for "context, provenance,
or versioning"; reification is "making statements about statements… who said it,
when, with what confidence, and under what conditions"
([Provenance-Aware Knowledge Representation survey, Springer](https://link.springer.com/article/10.1007/s41019-020-00118-0);
[Named graphs, ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1570826805000235);
[Graph Reification, TrustGraph](https://trustgraph.ai/guides/key-concepts/graph-reification/)).
Cicada already does a markdown-native version of reification: per-entity
confidence + git-blame provenance. **Extending that "context dimension" from
the entity level down to the *facet/claim* level is the whole move** — and it's
consistent with what Cicada already does, not a new paradigm.

### 2. The second, separable wish: connecting not-obviously-related things

This is **not** a storage problem and should not drive the entity model. The
relevant literature is analogical inference and serendipity/literature-based
discovery over graphs: "analogical inference maps the target problem to a known
source problem"; retrievers operate at entity-, relation-, and triple-level;
LBD "reveals hidden connections that traditional methods overlook"; and a 2025
study frames LLMs explicitly as serendipity-discovery engines over KGs
([Analogical Inference Enhanced KGE, arXiv:2301.00982](https://arxiv.org/pdf/2301.00982);
[LLMs for Serendipity Discovery in KGs, arXiv:2511.12472](https://arxiv.org/html/2511.12472v1);
[Literature-based discovery, PMC11920161](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11920161/)).
For Cicada this is a **retrieval/synthesis behavior** delivered by the planned
ask/dialectic endpoint (D3) + the Sleep pattern-detection stage — e.g. an
explicit "find bridges" mode that asks the LLM to surface latent connections
across facets/tags and reports them as *candidate* edges (with gap analysis, à
la gbrain). Good facet modeling makes these bridges *expressible*; it doesn't
generate them.

### 3. Convergent signal from prior art

- **Honcho**: global representation + scoped representations = canonical + lens.
- **gbrain**: typed edges + tags + overnight enrichment that *finds* links.
- **Roles / KG-context literature**: one identity, many context-bound views.
- **Cicada already**: `tags` (open set, "cross-cutting concerns") + closed
  8-type set + per-entity confidence/decay + git provenance.

All four point the same way: **don't fragment identity; add a context dimension
to the views/claims; do cross-connection at retrieval time.**

## What this means for Cicada

**1. Keep one entity page per subject. Add optional, named "facets" (lenses)
inside it.** A facet is a context-scoped section of an entity with its *own*
confidence, `last_referenced`, decay, and source episodes. Most entities will
have zero facets (a `tool` like FastAPI doesn't need an engineer-self vs
family-self split). Facets exist for entities that genuinely carry
context-dependent meaning — chiefly the user's self-model (today crammed into
the single `skill` type, which both adjacent-system notes already flag as
underpowered).

**2. Promote the user's self-model into a first-class, faceted entity.** This is
where the "engineer-self / family-self / life-philosophy" insight actually
lands. It dovetails with the Honcho note's recommendation to elevate `skill`
beyond one of 8 types into a richer self-model. A facet that stops being
reinforced *decays independently* — "engineer-self values X" can fade while
"family-self values Y" stays warm. That's Cicada's temporal-decay thesis applied
at the facet grain, which is novel and thesis-worthy.

**3. Model "context" as a controlled vocabulary, reusing `tags` semantics.** A
facet's context label (`engineer`, `family`, `philosophy`, `career`, …) should
be the same open-set vocabulary as `tags`. This unifies two mechanisms: tags
already exist "for cross-cutting concerns"; a facet is just a tag *promoted to a
structured, decaying view*. It also gives the cross-connection feature a natural
axis to traverse ("show me where the `philosophy` lens touches the `engineer`
lens").

**4. Treat cross-facet connection as a retrieval mode, shipped via D3's
ask/dialectic endpoint** — `ask_memory(..., mode="bridges")` returning
*candidate* abstract links + gap analysis + confidence, never silently written.
Sleep's pattern-detection stage can pre-compute candidate bridges and stage them
as nudges/clarifications for user approval (agent proposes, user disposes).

**5. Do NOT build separate graphs, and do NOT build peers — yet.** Design the
facet key as `(context, subject)` so that a future multi-bank / peer world (D4)
is the clean generalization `(observer, context, subject)`. One field added
later; no migration of the storage model.

### Sketch data model

Markdown-native, Obsidian-compatible, backward-compatible (facets optional;
existing entities are unchanged = the implicit single "canonical" facet).

```markdown
---
type: person | project | ... | skill   # (self-model likely a richer `skill`/`person`)
status: active
confidence: 0.82          # canonical/whole-entity confidence
created: 2026-01-10
last_referenced: 2026-06-10
decay_rate: 0.05
tags: [identity, career]
related: [Robotics, Capstone]
version: 4

# NEW — optional, context-scoped views. Absent for most entities.
facets:
  - context: engineer          # drawn from the tag/context vocabulary
    confidence: 0.88
    last_referenced: 2026-06-12
    decay_rate: 0.04
    source_episodes: [ep_2026-06-12_003]
    summary: "Optimizes for simplicity, distrusts premature abstraction."
    related: [FastAPI, Cicada]     # facet-local edges
  - context: family
    confidence: 0.55
    last_referenced: 2026-04-02    # decaying independently
    decay_rate: 0.07
    source_episodes: [ep_2026-04-02_001]
    summary: "Prioritizes presence over ambition; weekends are protected."
  - context: philosophy
    confidence: 0.70
    last_referenced: 2026-05-20
    decay_rate: 0.03
    source_episodes: [ep_2026-05-20_002]
    summary: "Stoic leanings; values craftsmanship as meaning."
---

# Self
Canonical body...

## Facet: engineer
Markdown body for the engineer lens (wikilinks resolve normally)...

## Facet: family
...
```

Design properties this gives you:
- **One node in the graph** (no fragmentation); facets can render as
  sub-nodes/rings around the parent in d3 if desired, or as a facet filter.
- **Per-facet decay/confidence/provenance** — the temporal-decay thesis at finer
  grain; each facet has its own `git blame` trail.
- **Backward compatible** — no `facets` key ⇒ today's behavior exactly.
- **Clean generalization to peers** — add `observer:` beside `context:` later;
  `(context, subject)` → `(observer, context, subject)`.
- **Cross-connection axis** — facet `context` labels + `tags` give the bridge-
  finder a structured space to traverse and to report against.

## Recommendation

**Adopt approach (a), refined as "canonical entity + optional named facets
(lenses)," and explicitly reject (b) separate per-context graphs.** Frame facets
in the thesis as a markdown-native fusion of (c) Honcho's perspectival,
scoped representations and (d) RDF context/reification — i.e. *the context
dimension pushed from the entity level down to the claim/view level, while
keeping one navigable identity*. Borrow Honcho's global-plus-scoped split as the
abstraction and role-based modeling as the conceptual justification; keep peers
strictly as a future generalization (D4 stays research-only). Treat
"connecting not-obviously-related things" as a **separate retrieval feature**
on the D3 ask/dialectic endpoint (analogical/bridge mode with gap analysis,
gbrain-style), fed by Sleep-staged candidate links the user approves — not as a
reason to touch storage. **Priority order:** (1) promote the user self-model to a
first-class faceted entity; (2) add the optional `facets` schema; (3) per-facet
decay; (4) bridge/analogy retrieval mode last.

## Open questions

- **Facet granularity & explosion.** What stops every entity sprouting facets and
  re-polluting the graph the promotion model was designed to keep clean? Likely a
  *facet promotion threshold* (a context must recur N times for that subject
  before a facet is minted) — needs Rodrigo's call and validation against real
  episodes.
- **Whose contexts?** Is the context vocabulary user-defined, Sleep-discovered,
  or both? If Sleep auto-detects facets, that's powerful but risks imposing a
  self-model the user didn't author (tension with "user authority").
- **Does this need to leave the self-model at all?** Maybe only `person`/`skill`/
  self entities ever get facets in v2, and projects/tools never do. Scoping
  facets to identity-type entities first would de-risk the whole feature.
- **Graph rendering.** Facets as sub-nodes (denser, busier) vs. a facet *filter*
  on one node (cleaner, less expressive)? UX decision for the d3 view.
- **Decay interaction.** When a *facet* decays below threshold but the canonical
  entity is healthy, what surfaces — a facet-level decay nudge? archive just the
  facet? This is new nudge surface area not in the current 3-type model.
- **Cross-connection quality (lowest confidence).** Analogical/bridge retrieval
  over a personal-scale graph is genuinely unproven here; it may produce noise,
  not insight. Needs a small experiment before committing thesis claims to it.
