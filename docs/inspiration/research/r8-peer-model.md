# Peer / observer-observed model for Cicada

> Research note (R8) for the Cicada v2 improvement wave. Informs **D4 (peers /
> multi-bank)** — RESEARCH-ONLY, design not build — and touches **D2 (entity model)** and
> **D3 (retrieval: both NL-ask and file traversal)**. Companion analyses:
> [`../honcho.md`](../honcho.md), [`../gbrain.md`](../gbrain.md).

## TL;DR

- **Honcho's peer model is real theory-of-mind plumbing, not a metaphor.** Memory is keyed
  by `(observer, observed)` pairs: Alice's model of Bob is a *separate collection* from
  Bob's model of himself, and self-knowledge is just the degenerate case where
  `observer == observed`. Local (session-scoped, "what I witnessed") vs global ("everything
  this peer ever said") representations are toggled per-peer with `observe_me` /
  `observe_others` flags. ([Honcho representation docs](https://honcho.dev/docs/v3/documentation/core-concepts/representation), [configuration docs](https://honcho.dev/docs/v2/documentation/core-concepts/configuration))
- **At single-user scale the cost is real and the payoff is thin.** Perspectival memory
  multiplies storage, write paths, and conflict-resolution work by the number of
  (observer, observed) pairs. For one human with a private graph there is essentially **one
  observer that matters** — so the general machinery is over-engineering *today*.
- **But there is one high-value, low-cost slice Cicada should adopt now:** treat the
  **agent's belief about an entity** as a first-class, *separable* layer from the
  **observed/asserted fact**. This is "opinion vs observed" — and it falls out naturally
  from frontmatter (it is basically what `confidence` + provenance already gesture at).
- **The full peer network becomes worth it precisely when Cicada stops being single-user:**
  shared/team graphs, a robot or second agent maintaining its *own* side-by-side opinion of
  the same research, or "two models disagree about X" as a thesis demo. Design the substrate
  so this is a **clean extension, not a rewrite** — an optional `observer` axis that
  defaults to a single implicit `self` peer.
- Recommendation: **adopt a lightweight "perspective layer" (opinion-vs-observed) in the
  entity schema now; design — but do not build — the full peer network as a forward-compatible
  extension.** Mark the multi-peer build as post-MVP, gated on a concrete second-observer use
  case (robot, team, or A/B agent comparison).

## Findings

### 1. How Honcho's peer model actually works

Honcho's primitives are **Workspace → Peer → Session → Representation**
([overview](https://docs.honcho.to/), [architecture & intuition](https://docs.honcho.to/architecture-and-intuition)).

- A **Peer** is *any* participant — human or agent — as a first-class entity. There is no
  privileged "user vs assistant" distinction; both are peers.
- A **Session** is a conversation among multiple peers.
- A **Representation** is the derived model of a peer. It is **keyed by `(observer, observed)`**.
  Internally (per Honcho's own docs and CLAUDE.md) vector storage — Collections/Documents —
  is keyed by that pair, and the *same* mechanism powers self-representation
  (`observer == observed`) and cross-peer modeling (`observer != observed`)
  ([SDK reference](https://docs.honcho.dev/v2/documentation/reference/sdk),
  [features](https://docs.honcho.dev/v2/documentation/core-concepts/features)).

**Global vs local representation** ([representation docs](https://honcho.dev/docs/v3/documentation/core-concepts/representation)):

- **Global**: owned by a peer, built from *everything that peer has ever sent* across all
  sessions. "Alice owns her own global representation."
- **Local**: a peer's model of *another* peer, built **only from messages it witnessed in
  shared sessions**. "Bob has a local representation of Alice based on what he observes."
  Crucially this is **session-segregated**: Bob's Alice-conclusions reflect only sessions Bob
  and Alice shared; Charlie's Alice-conclusions reflect only *their* shared sessions — so two
  observers can hold genuinely different, non-reconcilable views of the same person, including
  "shared history, inside jokes, or past conflicts that the other knows nothing about."

**Observation is configured, not automatic** ([configuration docs](https://honcho.dev/docs/v2/documentation/core-concepts/configuration)):

- `observe_me` (default **true**): whether this peer should be modeled by others.
- `observe_others` (default **false**): whether this peer produces local representations of
  others in a session.
- To get any local representation you need *at least one* peer with `observe_others=true` and
  *at least one other* with `observe_me=true`. Session-peer flags override peer-level ones, so
  you can express any directional permutation (A watches B but B doesn't watch A, etc.).

A representation is not raw storage — it is **reasoning artifacts**: deductive / inductive /
abductive **conclusions**, rolling **summaries** (short every ~20 msgs, long every ~60), and a
**peer card** (a biographical cache: name, occupation, interests). This is the "memory is
reasoning, not retrieval" thesis made concrete.

### 2. The same idea in the research literature (and that it's a known cost)

This is not just a Honcho idiom — it's a live research direction, which is good for thesis
related-work framing:

- **Perspectival memory = one knowledge graph per perspective.** Surveys of LLM multi-agent
  memory describe exactly this: "each perspective maintains a separate knowledge graph
  populated through its encoding process," and as encodings accumulate, *each* perspective must
  independently "manage redundancy, resolve internal contradictions, and forget outdated
  information." ([LLM-MAS memory survey, TechRxiv](https://www.techrxiv.org/users/1007269/articles/1367390/master/file/data/LLM_MAS_Memory_Survey_preprint_/LLM_MAS_Memory_Survey_preprint_.pdf))
- **"Rashomon Memory"** (arXiv 2604.03588) frames *multi-perspective* agent memory explicitly —
  multiple, possibly-conflicting accounts of the same events, retrieved via argumentation rather
  than collapsed to one truth. ([arXiv](https://arxiv.org/pdf/2604.03588)) This is the academic
  name for "two agents holding side-by-side opinions of the same research."
- **"Belief Memory: Agent Memory Under Partial Observability"** (arXiv 2605.05583) treats memory
  as *belief* an agent holds given only what it could observe — the formal version of
  Honcho's local representation. ([arXiv](https://arxiv.org/html/2605.05583v1))
- **The cost is explicitly documented.** Multi-agent memory work warns about **epistemic drift**
  ("belief strengthens even as truth decays" — the AI version of rumor propagation) and the fact
  that without sync, "loosely-coupled agents update knowledge that others remain unaware of,
  leading to divergent beliefs and coordination failures." Shared memory needs coherence support
  or agents "overwrite each other, read stale information, or rely on inconsistent versions of
  shared facts"; distributed/per-perspective memory needs "explicit synchronization" or "state
  divergence becomes common." ([Shared Memory: the missing brain of multi-agent AI](https://medium.com/@amarjit.sharma_75082/shared-memory-the-missing-brain-of-multi-agent-ai-10895be481fb),
  [Neo4j: multi-agent shared graph memory](https://neo4j.com/nodes-ai/agenda/multi-agent-shared-graph-memory-building-collective-knowledge-for-agents/))

**Read:** perspectival memory is powerful and academically current, but every source that
endorses it also flags that it multiplies the consolidation/conflict workload per observer. That
is exactly the cost Cicada's Sleep cycle would have to pay N times instead of once.

### 3. Mapping this onto Cicada's markdown + git substrate

Cicada has no Postgres collections — its unit of memory is a **markdown file with YAML
frontmatter, wikilinks, and git history**. The clean translation is:

**A peer is a directory (a "memory bank"), and the observer is part of the path.**

```
memory/
├── peers/
│   ├── self.md                     # the user — the default, implicit peer
│   ├── agent-bookworm.md           # the Cicada agent itself, as a peer
│   └── robot-arm-01.md             # a second observer (post-MVP)
│
├── entities/                       # OBSERVED layer — peer-agnostic asserted facts
│   └── leann.md                    # type: tool, confidence, decay, source_episodes …
│
└── perspectives/                   # OPINION layer — keyed by (observer, observed)
    ├── self/                       # observer = self
    │   └── leann.md                # what the USER believes about LEANN
    └── agent-bookworm/             # observer = the agent
        └── leann.md                # what the AGENT believes about LEANN (its read)
```

- `entities/` stays the **shared, observed substrate** — the "what is asserted" graph. This is
  exactly today's graph; nothing breaks.
- `perspectives/<observer>/<observed>.md` is the **opinion layer**: an observer's *belief*
  about an entity, separate from the asserted fact. `observer == observed` (a peer's
  `perspectives/self/self.md`) is the self-model — the natural home for Cicada's `skill`-type
  theory-of-mind entities ("Prefers concise summaries").

**A perspective file's frontmatter** would extend the existing schema with an observer axis:

```yaml
---
observer: agent-bookworm        # who holds this opinion
observed: leann                 # which entity it is about  (-> entities/leann.md)
kind: opinion                   # opinion | observed
stance: endorses                # endorses | doubts | disputes | neutral
confidence: 0.7
claim: "Best fit for on-device personal-scale retrieval; storage win is the deciding factor."
basis:                          # provenance: episodes/sessions this opinion was witnessed in
  - ep_2026-06-10_004
diverges_from:                  # OPTIONAL: explicit pointer to a conflicting perspective
  - self/leann.md               # the user is less sure than the agent
last_referenced: 2026-06-12
decay_rate: 0.05
version: 2
---
```

Why this fits Cicada cleanly:

- **It's the same file/git/blame substrate.** `git blame perspectives/agent-bookworm/leann.md`
  gives per-line provenance of *the agent's evolving opinion*, which is a strictly stronger
  transparency story than Honcho's opaque vectors. This is on-brand for Cicada's "provenance
  over magic" principle.
- **It absorbs D3 (both retrieval modes).** An `/ask` dialectic endpoint can answer
  "what does the *agent* think about X vs what did the *user* assert?" by reading two files; a
  file-traversal client can still walk `entities/` ignoring perspectives entirely.
- **Default-collapsed.** With exactly one peer (`self`), `perspectives/self/` is almost
  redundant with `entities/` — so for the single-user MVP you can **omit the perspectives tree
  entirely** and treat `confidence` + git history on `entities/*.md` as the implicit
  self-perspective. The directory layout means turning peers *on* later is additive, not a
  migration.

**"Opinion vs observed" as the minimum viable slice.** Even with one user, the distinction
between *what was asserted in an episode* (observed) and *what the agent has concluded/believes*
(opinion) is genuinely useful and cheap: it is the difference between "the user said they
switched to SQLite" (observed, high certainty, datable) and "the agent infers the user prefers
zero-infra tools" (opinion, abductive, decays). Honcho's deductive/inductive/**abductive**
conclusion taxonomy is worth borrowing as a `basis_type` field here.

### 4. Visualizing a peer collaboration network in d3-force

Cicada already renders entities as a force graph in a `WKWebView`. Adding peers/perspectives
maps onto d3-force idioms cleanly ([d3-force](https://d3js.org/d3-force),
[d3 force layout in depth](https://www.d3indepth.com/force-layout/)):

1. **Peers as a distinct node class.** Add a 9th visual class (peers are *not* one of the 8
   entity types — render them differently: larger, ringed, e.g. a halo or avatar glyph) so
   `self`, `agent-bookworm`, `robot-arm-01` read as observers, not entities.
2. **Perspective edges = directed, observer-colored.** Draw a directed edge
   `peer --(opinion)--> entity`, colored by the *observer* and styled by `stance`
   (solid = endorses, dashed = doubts, red = disputes). This is the "ego-network" idiom — each
   peer is the center of its own opinion fan ([collaboration ego-network in networkD3](http://www.raffaelevacca.com/a-collaboration-ego-network-in-networkd3/),
   [D3 social-network viz](https://medium.com/@john.goodman/d3js-visualizing-social-networks-f813f7528da4)).
3. **Disagreement as the headline visual.** When two perspective edges point at the *same*
   entity with conflicting `stance`, render a **"disagreement halo"** on that entity (e.g. a
   split-color ring or a small ⚡ badge) — the single most compelling demo of perspectival memory:
   *"the agent and the user hold side-by-side, divergent opinions of the same research."* This is
   directly the Rashomon-memory framing made visible.
4. **Peer-filter toggle (the killer interaction).** A control to **filter the graph by observer**:
   "show me the world as the *agent* sees it" vs "as I asserted it." Switching the active peer
   recolors/re-weights edges and fades entities that observer has no opinion on. Force layout
   re-settles, so the same shared `entities/` substrate visibly *reorganizes* around each
   perspective. (Force simulation makes this animate for free.)
5. **Collaboration links between peers.** `peer --(observes)--> peer` edges (from `observe_*`
   config) show *who watches whom* — the actual collaboration topology, distinct from the
   opinion edges.

Keep entity nodes peer-agnostic and let **edges + halos carry the perspective**; this avoids
duplicating nodes per observer (which would explode the graph) while still making divergence
legible.

### 5. The cost of perspectival memory at single-user scale

Honest accounting:

- **Storage / write amplification:** O(observers × observed-entities) perspective files vs O(entities)
  today. For one user that's a ~1× multiplier on a layer that is mostly redundant with
  `confidence`.
- **Sleep-cycle cost multiplies:** stages 1–3 (extraction, resolution, conflict) would run *per
  observer* to keep each perspective current — the literature's documented per-perspective
  "manage redundancy, resolve internal contradictions" tax. At single-user scale this is paying
  N× LLM cost for N≈1 observers.
- **New failure mode (epistemic drift):** maintaining agent-opinion separately risks the agent's
  belief reinforcing itself away from what the user actually asserted — the exact drift the MAS
  literature warns about. With one user this is mostly downside with little upside.
- **Conceptual overhead for the user:** the companion app's whole pitch is transparency; a
  perspective layer the user doesn't need adds UI surface ("whose view am I looking at?") that
  could muddy the core graph.

**When it flips to worth-it:**

- A **second real observer** exists: a robot/embodied agent, a second AI agent, or a teammate —
  each genuinely sees a *different slice* and divergence is informative, not noise.
- You want **agent-vs-user disagreement as a feature** (the thesis demo: "the agent doubts a
  fact the user asserted, and surfaces it as a clarification" — perspectival memory makes that
  natural rather than bolted-on).
- Cicada goes **multi-user / shared / federated** (the gbrain "teams, scope-gated" direction),
  where Honcho's full `(observer, observed)` machinery earns its keep.

## What this means for Cicada

1. **Do not build the full peer network for the MVP.** At single-user scale it is the same kind
   of over-engineering as "Neo4j over markdown" — pay infrastructure cost for expressiveness you
   don't use. The honcho.md note's instinct ("peers — probably out of scope, worth one line in
   related work") is correct *as a build decision*.
2. **But do adopt the cheap, high-value slice now: an explicit opinion-vs-observed split.**
   Keep `entities/` as the asserted/observed substrate. Introduce a notion of *agent opinion*
   (abductive conclusions, beliefs, the self-model) as a distinguishable layer — even if, for
   the MVP, it lives as richer frontmatter / a tag on `skill`-type entities rather than a full
   `perspectives/` tree. This directly upgrades the `skill` entity into the theory-of-mind layer
   honcho.md already recommended, and it pairs perfectly with **decay** (an *opinion* that stops
   being reinforced should decay faster than an *observed fact* that was explicitly asserted).
3. **Design the substrate to be peer-ready, default-collapsed.** Reserve the `peers/` and
   `perspectives/<observer>/` layout. Treat today's graph as the implicit `self` observer.
   Anything you build now (schema, API, d3) should carry an **optional `observer` field that
   defaults to `self`** — so turning peers on later is additive, never a migration. This is the
   "decision designed for, not committed to" posture D4 asked for.
4. **Steal the observation-config idea conceptually, not the flags.** `observe_me` /
   `observe_others` are the right *abstraction* for "who models whom," but Cicada doesn't need
   the session-peer permutation matrix yet. One line in the thesis: Cicada collapses Honcho's
   per-peer observation config to a single trusted observer (the user), the same simplification
   personal scale earns elsewhere.
5. **The d3 disagreement-halo + peer-filter toggle is a strong thesis figure even as a mockup.**
   If a full build is out of scope, a *designed* visualization (and a one-entity worked example
   of agent-vs-user divergence) is high thesis value for low cost — it makes the perspectival
   idea concrete in the Results/Design chapter without the engineering tax.

## Recommendation

**Adopt a lightweight perspective layer now; design — but do not build — the full peer network.**

- **Build now (cheap, on-brand):** an explicit **opinion-vs-observed** distinction. `entities/`
  = observed/asserted facts; agent beliefs/abductive conclusions = a separable *opinion* layer
  (start as enriched `skill`/self-model frontmatter with a `basis_type`:
  deductive/inductive/abductive field borrowed from Honcho). Wire decay to treat opinions as
  faster-decaying than asserted facts. This is the genuinely useful core of theory-of-mind at
  single-user scale, and it costs ~one schema change.
- **Design now, build later (forward-compatible):** the `peers/` + `perspectives/<observer>/`
  directory layout and an **optional `observer` axis defaulting to `self`** across schema, the
  `/ask` endpoint, and the d3 graph. No multi-peer consolidation, no observation-config matrix
  in the MVP.
- **Gate the full build on a concrete second observer** — a robot/embodied agent, a second AI
  agent holding its own opinion of the same research, a teammate, or multi-user/federated mode.
  Until one of those exists, the `(observer, observed)` machinery is N×-cost for N≈1 and should
  stay on paper.
- **Thesis framing:** position peers as *the simplification personal scale earns* (one trusted
  observer), mirroring "markdown over Neo4j" — and present the perspectival graph (disagreement
  halo + peer-filter toggle) as a **designed extension** with a worked agent-vs-user example.
  This gets the thesis credit for the idea without the build cost, and cleanly cites Honcho +
  Rashomon/Belief-Memory as related work.

## Open questions

1. **Is "the agent" a real second observer, or just the user's mirror?** The whole
   opinion-vs-observed value hinges on whether Bookworm's *inferred* beliefs (abductive) are
   meaningfully distinct from the user's *asserted* facts. If they collapse to the same thing in
   practice, even the cheap slice isn't worth it. Needs Rodrigo's read on whether agent-vs-user
   divergence is a feature he wants to surface (e.g. as a clarification nudge).
2. **Where does the opinion layer physically live for the MVP** — enriched frontmatter on
   existing `entities/`/`skill` pages, or a separate `perspectives/self/` tree from day one?
   (Frontmatter is cheaper now but a separate tree is cleaner when peers arrive.)
3. **Does decay apply differently to opinion vs observed?** Proposal above says yes (opinions
   decay faster). Needs a decision — it interacts with the conflict-resolution stage.
4. **Is there an actual second-observer use case on the roadmap** (robot, second agent, team)?
   This is the single gate for whether the full peer build ever happens. Unverified whether any
   is planned.
5. **Confidence flag:** the Honcho mechanics here (`observe_me`/`observe_others`, global/local,
   `(observer, observed)` keying, peer cards, conclusion taxonomy) are **well-verified** from
   current Honcho docs. The *cost framing* is supported by the MAS-memory literature but is my
   synthesis, not a measured number — treat the "N× cost" claim as directional, not benchmarked.
   The d3 visualization scheme is a **design proposal**, unbuilt and untested.
