# Entity promotion: keep or kill?

> Research note for Cicada's v2 design wave. Companion to [`honcho.md`](../honcho.md)
> and [`gbrain.md`](../gbrain.md). Scope: critically evaluate whether the **entity
> promotion gate** ("don't extract on first mention; promote on recurrence") and the
> **closed 8-type taxonomy** constrain good consolidation. Decisions D1 (storage),
> D2 (entity-model), D4 (peers) are research-only — this doc informs them, it does not
> assume a build.

## TL;DR

- **Promotion and taxonomy are two separate decisions that got bundled.** The promotion
  *gate* (when does a node materialize) and the *closed 8-type set* (what a node may be)
  are independent knobs. You can keep one and kill the other. Treat them separately — this
  is the single most important reframe in this doc.
- **The promotion gate is mostly right but currently too binary.** "Nothing until the 2nd
  mention" throws away a real signal: a single substantive first mention often *is* a
  durable entity, and the gate can't see cross-mention links until both ends exist. The
  fix is **soften, not kill** — introduce **shadow/candidate entities** (lightweight,
  uncolored, low-confidence stubs) so recurrence detection and cross-linking can operate on
  *materialized* candidates rather than on raw LEANN chunks.
- **The closed 8-type taxonomy is the bigger constraint on abstraction.** Forcing every
  node into person/project/company/concept/tool/deadline/skill/location at *creation* time
  is a premature commitment. The field has moved the other way: **Zep/Graphiti and gbrain
  both extract types emergently / via open "schema packs"**, precisely because you don't
  know the right schema until you've seen the data. Recommend making the 8 types a
  **default-but-extensible** set, with an `concept` catch-all and tag-based cross-cutting
  links carrying the abstract relationships the type system can't.
- **Cross-domain abstraction lives in *edges and tags*, not node types.** The literature is
  consistent: emergent cross-links and "communities" come from clustering and
  relationship discovery over the graph, not from the entity-type label. So the taxonomy
  doesn't *directly* block abstraction — but a thin/late node layer (the promotion gate)
  *does*, because you can't draw an edge to a node that doesn't exist yet.
- **The biological framing actually argues for softening, not for the hard gate.** Cicada's
  pitch is hippocampal→cortical consolidation. In that model the hippocampus *does* encode
  one-shot traces immediately (fast, episodic) and the cortex slowly schematizes them. The
  hard "no entity until 2nd mention" gate is *more* aggressive than biology: the brain
  keeps the labile trace and lets it decay if unreinforced. That is exactly the
  shadow-entity + decay design. **Confidence: medium-high** on the reframe, **medium** on
  the specific thresholds.

## Findings

### 1. The field is moving away from fixed, upfront schemas

The clearest external signal: the two most credible current agent-memory graph systems
both reject a fixed closed ontology applied at extraction time.

- **Zep / Graphiti (Rasmussen et al., 2025).** "Rather than relying on predefined
  ontologies, entities and facts **emerge through semantic extraction** from episodes."
  Each entity is embedded and deduplicated against the existing graph; edges carry validity
  windows. The whole architecture is bet on *not* committing to types up front. See the
  paper [arXiv:2501.13956](https://arxiv.org/abs/2501.13956) and Neo4j's writeup
  ([neo4j.com/blog/developer/graphiti-knowledge-graph-memory](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)).
  Note the cost flip side: Graphiti's "check every new edge against the entire graph"
  dedup is ~2.25× more expensive than Mem0 on complex sessions
  ([dev.to benchmark](https://dev.to/juandastic/i-benchmarked-graphiti-vs-mem0-the-hidden-cost-of-context-blindness-in-ai-memory-4le3)).
  Emergent extraction is not free — Cicada's promotion gate is partly a *cost* control, and
  that's legitimate.

- **gbrain** uses **open "schema packs"** (custom page types like person/company/meeting)
  rather than a fixed schema, with **zero-LLM typed-edge extraction on every write**
  (already noted in [`gbrain.md`](../gbrain.md)). The design lesson: types are *extensible
  and user/domain-defined*, and edge extraction is cheap enough to do eagerly.

- **GraphRAG practitioner consensus.** The recurring practitioner finding is that defining
  an ontology before you've seen the corpus "adds unnecessary complexity… you rarely know
  what your schema should look like until you start extracting." Better to "begin with a
  flexible structure that can evolve" and "extract what's cost-effective… and let the
  retrieval pipeline fill the gaps."
  ([Towards Data Science, GraphRAG in Practice](https://towardsdatascience.com/graphrag-in-practice-how-to-build-cost-efficient-high-recall-retrieval-systems/);
  [premai.io GraphRAG guide 2026](https://blog.premai.io/graphrag-implementation-guide-entity-extraction-query-routing-when-it-beats-vector-rag-2026/)).
  Counter-note: most of these are *agent/team/enterprise* corpora. Cicada is **single-user,
  personal-scale (hundreds of entities)** — the exact regime where a curated closed set is
  defensible (same family of argument as "markdown over Neo4j"). The "schema must evolve"
  literature is solving a bigger-corpus problem than Cicada has.

- **Honcho** is the extreme schema-light end: it stores **no fixed entities at all** —
  raw messages plus derived per-peer *representations*, interrogated via the Dialectic API
  ([`honcho.md`](../honcho.md)). It is the existence proof that useful memory can run with
  *zero* entity taxonomy. But it pays for that with opacity (reasoning lives in vectors,
  not inspectable pages) — which is the exact property Cicada is built to reject.
  **Honcho's schema-lightness is inseparable from its opacity; Cicada can't copy one
  without the other.**

**Takeaway:** the closed-taxonomy-at-creation decision is the part of Cicada that most
diverges from where the field has landed. That's not automatically wrong (personal scale,
transparency, node coloring all argue for it) — but it needs an explicit defense, and the
honest defense is "personal scale + d3 node coloring + human legibility," **not** "this is
how memory should work."

### 2. Closed vs open type sets: it's a precision/recall tradeoff, and a closed set buys precision at the cost of recall

Classic NER framing maps cleanly onto Cicada. Traditional NER is "constrained to a fixed
set of entity types (person, organization, location)"; modern open/zero-shot NER lets the
type be "defined at query time" and "generalizes to novel fine-grained entity types"
([NER Retriever, arXiv:2509.04011](https://arxiv.org/html/2509.04011v1);
[WhisperNER, arXiv:2409.08107](https://arxiv.org/pdf/2409.08107)).

The relevant metric is **recall vs precision** (precision = TP/(TP+FP), recall =
TP/(TP+FN); a *missed* entity is a false negative,
[nervaluate / SemEval-13](https://github.com/MantisAI/nervaluate)). Mapping to Cicada:

- The **closed 8-type set + promotion gate = a high-precision, low-recall stance.** Few
  false entities (clean graph, the anti-pollution goal), but real things that don't fit a
  type, or were only mentioned once-but-substantively, are **silent false negatives** —
  they never become nodes, so they can never be linked, surfaced, or decayed. They're
  invisible. *Cicada currently has no way to measure its own recall* — dropped mentions
  leave no trace except in LEANN.
- Schema-light systems take the opposite stance: higher recall, more noise, dedup/pruning
  later. Mem0's pipeline is illustrative — extract all facts, then MD5/embedding dedup and
  prune ([Mem0 v3 algorithm](https://docs.mem0.ai/migration/oss-v2-to-v3);
  [mem0.ai state of agent memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)).

This is the crux: **graph pollution is a precision problem; the promotion gate is a
precision tool. But Cicada has no recall instrument at all.** You're optimizing one side of
a tradeoff you can only see half of.

### 3. Does committing to entities up front hurt *abstract cross-links*? Partly — but the culprit is node *existence*, not node *type*

Where do abstract / cross-domain connections come from in these systems? The literature is
consistent that they come from **clustering and relationship discovery over the graph**,
not from the type label:

- GraphRAG organizes entities "into topic-centered communities through clustering…
  enabling retrieval from varying levels of abstraction" and "cross-domain connections"
  ([premai.io 2026 guide](https://blog.premai.io/graphrag-implementation-guide-entity-extraction-query-routing-when-it-beats-vector-rag-2026/)).
- gbrain's value-add is *self-wiring typed edges* + overnight enrichment that finds links —
  again an *edge/relationship* operation.

So the type taxonomy is **not the primary thing** standing between Cicada and abstract
cross-links. The primary blocker is subtler and it's the **promotion gate**:

- You cannot draw an edge to a node that does not exist. If A is mentioned once
  substantively and B is mentioned once substantively in a *different* conversation, the
  abstract link A–B is exactly the kind of cross-link Cicada wants — but under the strict
  gate **neither A nor B is materialized at the moment the link could be drawn**, and the
  link lives only as latent semantic proximity in LEANN, where it can't be labeled,
  surfaced, or versioned.
- This is the "thin late node layer starves the edge layer" failure. gbrain avoids it by
  materializing candidate nodes/edges cheaply on every write; Graphiti avoids it by
  extracting eagerly. Cicada's gate is the most conservative of the three and therefore the
  most exposed to this specific miss.

Where the *type* set genuinely does constrain abstraction: a single node can only carry one
of 8 types, but real abstract entities are often *cross-cutting* ("my interest in
biologically-inspired systems" spans concept+skill+project). Cicada already has the right
escape hatch — **freeform `tags` and `related` wikilinks** — but tags are second-class
(not colored, not first-class in the graph view). **Promoting tags/clusters to first-class
abstract nodes is where cross-domain linking actually lives**, and that's orthogonal to the
8 types.

### 4. The biological framing argues for *softening*, not for the hard gate

Cicada's whole identity is hippocampal (fast, episodic) → cortical (slow, semantic)
consolidation. Worth checking the actual neuroscience against the actual design:

- **Schemas accelerate consolidation when new info fits** (Tse et al. 2007, *Schemas and
  Memory Consolidation*, Science; [science.org/doi/10.1126/science.1135935](https://www.science.org/doi/10.1126/science.1135935),
  summarized via [Edinburgh Research Explorer](https://www.research.ed.ac.uk/en/publications/schemas-and-memory-consolidation/)).
  "Systems consolidation can occur extremely quickly if an associative schema… has
  previously been created." New traces matching an existing schema "became assimilated and
  rapidly hippocampal-independent."
  *Cicada analogy:* a mention that links to an existing high-confidence entity should
  promote **immediately** — which Cicada's "explicitly linked to a high-confidence entity"
  threshold already captures. Good, keep that.
- **The corollary — schema-*incongruent* info does NOT get the fast-track and stays
  hippocampus-dependent longer — is the well-established flip side of this literature**
  (Tse-line work; I did not re-verify the exact incongruent-condition statistic — *mark as
  my inference from the consolidation literature, confidence medium*). Biologically, novel
  un-schematized experience is **still encoded** as a labile hippocampal trace and either
  gets reinforced into cortex or decays. It is *not* discarded at encoding.
- **This is the key mismatch.** Cicada's hard gate effectively says "don't even form the
  labile trace until the 2nd mention." That's *more* aggressive than the hippocampus, which
  forms one-shot traces eagerly and lets homeostasis/decay prune them. Cicada **already has
  the decay machinery** (`last_referenced`, `decay_rate`, archive at <0.2). So the
  biologically faithful design is: **form a weak trace (shadow entity) on first substantive
  mention, let decay kill it if never reinforced** — instead of refusing to form it at all.
  The shadow-entity proposal is *more* on-brand for the thesis than the current gate, not
  less.

### 5. The legitimate case FOR keeping the gate (steelman)

To argue both sides honestly:

- **Graph pollution is real and it's the stated goal.** Upfront-extraction systems *do*
  drown in single-mention noise; that's why GraphRAG practitioners now say "extract what's
  essential, let retrieval fill gaps." Cicada's gate is a principled, cheap answer.
- **Cost.** No-LLM-at-capture is a real architectural win. Eager extraction (Graphiti)
  costs 2.25× and runs LLM calls on the hot path. The gate keeps capture as pure file I/O.
- **Personal scale changes the math.** At hundreds of entities with d3 node-coloring and a
  human reading the graph, a clean curated set genuinely beats a sprawling emergent one.
  Obsidian users empirically complain about *over-linking* and noise
  ([thoughtfulatlas, "Over-linking…"](https://thoughtfulatlas.substack.com/p/over-linking-and-the-multi-faceted-nature-of-a-pkm-system)).
- **Deferred linking is a recognized good pattern.** Obsidian's *unlinked mentions* are
  exactly "materialize the link later, when it's worth it" — "retrieval as an ambient,
  emergent property of naming"
  ([Obsidian unlinked mentions](https://forum.obsidian.md/t/list-unresolved-links-as-unlinked-mentions/55659)).
  Cicada's gate is a programmatic version of the same instinct. **This is the strongest
  external validation of the *idea* behind promotion** — but note Obsidian keeps the raw
  text *materialized and named* so the mention is *visible and one-click linkable*. Cicada's
  gate hides the mention in LEANN. The lesson: **defer the *link*, not the *visibility*.**

## What this means for Cicada

Concrete and opinionated:

1. **Unbundle the two decisions in the thesis writeup.** "Promotion gate" and "closed
   taxonomy" should be defended (or softened) separately. Right now they're argued as one
   thing and they aren't.

2. **Introduce shadow/candidate entities (soften the gate).** On the *first* substantive
   mention, materialize a **shadow entity**: a real markdown page with `status: candidate`,
   low `confidence` (e.g. 0.2–0.3), **no committed type yet** (or `type: unresolved`), not
   rendered as a colored node in the graph (or rendered ghosted/dashed — Cicada already has
   a dashed-border decay visual to reuse). Benefits:
   - Recurrence detection and cross-linking now operate over *materialized* candidates, not
     raw LEANN chunks — fixing the "can't link a node that doesn't exist" problem (§3).
   - Decay does the pruning the gate used to do: an unreinforced shadow entity decays below
     0.2 and is archived. **Same anti-pollution outcome, but now it's measurable and
     visible**, and it's the biologically faithful path (§4).
   - The Clarification Queue becomes the natural surfacing point for shadow entities the
     system is unsure about — which Cicada already has the UI for.

3. **Make the 8 types default-but-extensible, and lean on the `concept` catch-all.** Keep
   the 8 as the *colored, first-class* set (the d3 coloring story is genuinely good). But:
   (a) let Sleep assign `type: concept` or `type: unresolved` rather than forcing a wrong
   fit; (b) allow user-defined types in frontmatter that render in a neutral color — the
   gbrain "schema pack" instinct, bounded for personal scale. Defend the closed *default*
   set on transparency/coloring/scale grounds, not on "this is correct."

4. **Promote tags/clusters to first-class abstract nodes — this is where cross-domain
   linking actually lives (§3).** A Sleep-stage-4 pattern-detection output ("you keep
   connecting biologically-inspired systems across robotics + memory + thesis") should be
   able to *materialize as a cluster/theme node* that links across types. This is the
   single highest-leverage move for "abstract cross-links," and it's independent of the
   gate decision.

5. **Build a recall instrument.** Today Cicada can't see what it dropped (§2). Log every
   *un-promoted substantive mention* (even just a count + the LEANN chunk id) so the thesis
   Results section can report a real precision/recall-style number for the gate. This also
   makes the gate's threshold tunable with evidence rather than vibes — and it dovetails
   with the existing Table 2 ablation harness (promotion 1/3 sweep).

6. **Defer the link, not the visibility (the Obsidian lesson, §5).** Even if you keep a
   strict gate, surface un-promoted mentions the way Obsidian surfaces unlinked mentions —
   so the user can one-click promote. Hiding mentions in LEANN is the part of the current
   design with the weakest justification.

## Recommendation

**Soften, don't kill — and unbundle.**

- **Promotion gate → SOFTEN to shadow/candidate entities.** Replace the hard "no node until
  2nd mention" with "weak shadow node on 1st substantive mention, decay prunes it if
  unreinforced." This preserves the anti-pollution goal (decay does the pruning), fixes the
  cross-link starvation problem, makes dropped-entity recall measurable, and is *more*
  biologically faithful to the hippocampal-trace framing than the current gate. This is the
  headline recommendation. **Confidence: high** on direction, **medium** on thresholds.
- **Closed 8-type taxonomy → KEEP as default, SOFTEN to extensible.** Keep the 8 as the
  first-class colored set (the transparency/coloring/personal-scale defense is real and
  thesis-worthy), but add a `concept`/`unresolved` catch-all path so Sleep never force-fits,
  and allow bounded user-defined types (gbrain schema-pack instinct). **Confidence:
  medium-high.**
- **Abstract cross-links → fix via first-class cluster/tag nodes + edge enrichment, not via
  the type system.** The taxonomy is *not* the main blocker on abstraction; the thin late
  node layer is. **Confidence: high.**

Net: the promotion *instinct* is validated externally (Obsidian deferred linking, GraphRAG
"extract what's essential", cost control vs Graphiti). The *implementation* (hard binary
gate + force-fit closed types at creation, with dropped mentions invisible) is the part the
field and the biology both push back on. Shadow entities + decay-as-pruner + extensible
types gets you the same clean graph with measurable recall and better abstraction.

## Open questions (need Rodrigo's input)

1. **Cost ceiling for Sleep.** Shadow entities mean more markdown pages and more
   resolution/dedup work per cycle (the Graphiti 2.25× tax, scaled down to personal size).
   At hundreds of entities this is probably trivial — but do you have a budget/latency
   target for a Sleep cycle that shadow entities must fit inside? (Ties to Table 3
   operational metrics.)
2. **Where does the shadow→full promotion decision live?** Pure threshold (confidence > X
   after N reinforcements), Sleep-LLM judgment, or user action via Clarification Queue?
   Probably all three, but the default path matters for the UX story.
3. **Do you actually want user-defined types,** or does that break the d3 node-coloring
   story you like? Bounded extension (neutral color for custom types) vs strict 8 is a real
   product call, not a research one.
4. **Recall instrument scope.** Is logging dropped mentions worth the added complexity for
   the thesis Results, or is the bespoke Table 1/2/3 framing enough? My bias: a single
   "promotion recall" number would meaningfully strengthen the gate's defense — but it's
   work.
5. **Verification I could not complete:** I could not fetch the Tse et al. 2007 full text
   (403). The "schemas accelerate congruent consolidation" finding is solid from secondary
   sources; the exact *incongruent-info* corollary I used in §4 is my inference from the
   consolidation literature and should be checked against the primary paper before it goes
   in the thesis.
