# Why Honcho is good (deep / philosophy)

> Research note for Cicada's improvement wave. Companion to the feature-level
> [`docs/inspiration/honcho.md`](../honcho.md). This doc goes past the feature list to the
> *why*: the intellectual bet, the theory-of-mind research lineage, what it solves that
> RAG-style memory does not, and where it breaks.
>
> Confidence is marked inline. Primary sources (Plastic Labs blog, Honcho docs, GitHub,
> their arXiv paper) are high-confidence; third-party benchmark numbers are flagged as
> reported-not-verified.

## TL;DR

- **The bet is "memory is reasoning, not retrieval."** Honcho doesn't store facts to fetch
  later; it runs background inference over raw messages to build a *model of the person*
  (beliefs, preferences, mental state) and serves that model back. This is a categorically
  different product from mem0/Zep/RAG, which store-then-fetch. **High confidence.**
- **The intellectual root is genuine: "machine theory of mind."** It traces to Plastic
  Labs' 2023 arXiv paper on reducing theory-of-mind *prediction error* in LLMs via
  metacognitive "Violation of Expectation" prompting — not marketing language retrofitted
  onto a vector DB. Their key empirical finding: LLMs are bad at predicting a user's exact
  next words but good at *imputing the user's internal mental state*, and the looser
  mental-state guess is the more useful one. **High confidence.**
- **The Dialectic API is the real innovation.** You don't `search(query) → chunks`; you
  `chat("Is this user a beginner or expert at Rust?") → reasoned answer`. Memory becomes an
  *agent you interrogate in natural language*, not an index you query. This is the piece
  worth stealing for Cicada. **High confidence.**
- **`(observer, observed)` perspectival memory + async "dreaming" are the supporting
  machinery.** Peers (human or agent) are first-class; what Alice knows about Bob is a
  separate representation from Bob's self-model; a background "deriver" consolidates off the
  hot path. The deriver is Cicada's Sleep cycle, independently reinvented. **High confidence.**
- **Its weaknesses are exactly Cicada's strengths: opacity (reasoning lives in an
  LLM-shaped blob, not auditable lines), LLM cost/latency on the reasoning path, infra
  weight (Postgres + Redis + LLM), and — confirmed — no temporal decay.** **High confidence
  on the gaps; the "decay absent" claim is verified by the absence of any decay mechanism in
  docs + README.**

## Findings

### 1. The core philosophical move: memory as reasoning, not retrieval

Honcho's central claim is that the interesting unit of memory is not a *fact* but a
*conclusion about a mind*. Most memory systems treat the problem as information retrieval:
chunk text, embed it, fetch the top-k relevant chunks at query time. Honcho instead stores
raw messages and runs continuous background reasoning to derive a structured, dense
*representation of the peer* — preferences, beliefs, contradictions, "peer cards" — that is
optimized to be dropped into an LLM prompt
([Honcho architecture docs](https://honcho.dev/docs/v2/documentation/core-concepts/architecture);
[andrew.ooo review](https://andrew.ooo/posts/honcho-plastic-labs-agent-memory-review/)).

The philosophical justification is explicitly linguistic and latent-space-shaped. From the
Dialectic API post: *"Personal context allows you to target parts of the latent space most
useful in generating tokens for specific users in specific settings,"* and *"the only way we
know to communicate and leverage that depth is with the inherent diversity of natural
language"*
([Introducing Honcho's Dialectic API, archived](https://plasticlabs.ai/blog/archive/ARCHIVED;-Introducing-Honcho's-Dialectic-API)).
The argument: because LLMs already operate inside a "human narrative space," natural language
is a *richer carrier of user context* than a structured row in a vector store. Compressing a
person into retrievable fact-chunks throws away the nuance that actually steers generation.

### 2. The theory-of-mind research lineage (this is not marketing)

The "theory of mind" framing is load-bearing and has a real research trail:

- **2023 paper — the founding result.** Courtland Leer, Vincent Trost, Vineeth Voruganti
  (Plastic Labs), *"Violation of Expectation via Metacognitive Prompting Reduces Theory of
  Mind Prediction Error in Large Language Models"* ([arXiv 2310.06983](https://arxiv.org/html/2310.06983),
  Oct 2023; eval code at [plastic-labs/voe-paper-eval](https://github.com/plastic-labs/voe-paper-eval)).
  They import **Violation of Expectation (VoE)** from developmental psychology: form a
  prediction about the user's mental state, observe the actual message, and use the
  *prediction error* as the learning signal to refine the model. They tested this on real
  conversations from their tutor product (Bloom) — 59 VoE-on vs 55 VoE-off conversations.
- **The sharpest empirical claim** comes from a follow-up note: LLMs *"struggle reliably
  predicting exact user responses, but excel at inferring internal mental states… they're
  really good at imputing internal mental states. That is, they're good at theory of mind
  predictions"* ([Loose theory-of-mind imputations are superior to verbatim response
  predictions](https://plasticlabs.ai/blog/notes/Loose-theory-of-mind-imputations-are-superior-to-verbatim-response-predictions)).
  A *loose* mental-state inference ("this user is frustrated and probably a beginner") is
  both more reliable and more actionable than a *verbatim* prediction of what they'll type.
  This is the technical reason the whole product targets mental states rather than facts.
- **Product lineage.** It started as Bloom / [tutor-gpt](https://github.com/plastic-labs/tutor-gpt),
  an "AI tutor powered by theory-of-mind reasoning" that used GPT-4 to *dynamically rewrite
  its own system prompts* per learner. Honcho is the generalization: pull the user-modeling
  layer out of the tutor and make it standalone infrastructure
  ([Theory-of-Mind Is All You Need](https://blog.plasticlabs.ai/blog/Theory-of-Mind-Is-All-You-Need);
  [User State is State of the Art](https://blog.plasticlabs.ai/blog/User-State-is-State-of-the-Art)).

Why this matters for credibility: the theory-of-mind language is *upstream* of the product,
not a label applied afterward. That makes Honcho the strongest independent argument that
"consolidate-then-reason about the subject" beats "retrieve facts."

### 3. Peers and the `(observer, observed)` belief model

Honcho's data model makes *perspective* first-class. Everything is a **Peer** (human or AI
agent — no privileged "user vs assistant" split), grouped into **Workspaces**, talking in
**Sessions**. Each peer gets two kinds of representation
([architecture docs](https://honcho.dev/docs/v2/documentation/core-concepts/architecture)):

- **Global representation** — everything a peer has ever produced, i.e. their self-model.
- **Local representation** — one peer's view of another, built *only* from what they
  actually observed. If Alice talks to Bob, both Alice's self-view and Bob's view-of-Alice
  update; if Alice later talks to Nico, Bob's local view of Alice stays frozen because Bob
  wasn't there.

This is real theory-of-mind plumbing: knowledge is *perspectival and asymmetric*, not a
single global blob. (Local representations are off by default and opt-in per peer/session,
which tells you it's the advanced, expensive path.) It cleanly supports multi-agent and
group settings — what does agent A believe agent B believes about the user — that a
flat fact store can't express.

### 4. The Dialectic API — memory you interrogate, not query

The marquee interface. Instead of returning chunks, the Dialectic / Chat endpoint
(`POST /peers/{peer_id}/chat`) takes a natural-language question *about a peer* and returns a
*reasoned answer* synthesized from that peer's representation
([architecture docs](https://honcho.dev/docs/v2/documentation/core-concepts/architecture)).
The framing from the launch post: it's *"just a conversation between two agents,
collaboratively reasoning about the best way to personalize UX"* — your app's LLM talking to
Honcho's LLM in natural language
([Dialectic API post](https://plasticlabs.ai/blog/archive/ARCHIVED;-Introducing-Honcho's-Dialectic-API)).
You consult Honcho the way you'd consult an expert *on* the user, not address the user
directly ("What is the user's mood today?", "Is this user a beginner or expert at Rust?").

This is the genuinely novel primitive. mem0/Zep give you better retrieval; Honcho gives you
a *queryable mind*. Nobody else in the personal-memory space really ships this as the front
door.

### 5. Async "dreaming" / the deriver

Reasoning is moved off the request path. A background worker (the **deriver**, historically
also called "dreaming"/"Neuromancer" in their writing) continuously processes incoming
messages, derives facts/summaries/peer-cards, tests hypotheses, and folds them into the
representation. Derivation tasks run in parallel across peers but serially within a single
peer's representation to preserve cumulative coherence
([architecture docs](https://honcho.dev/docs/v2/documentation/core-concepts/architecture);
[GitHub README](https://github.com/plastic-labs/honcho)). To keep runtime fast, they also
expose **low-latency static snapshots** of a representation so you can hydrate a prompt
without waiting for fresh reasoning. **This is structurally identical to Cicada's Awake/Sleep
split** — cheap capture on the hot path, expensive consolidation in the background — arrived
at independently. Strong validation of Cicada's core architecture.

### 6. What it solves that fact-retrieval memory (mem0 / Zep / RAG) does not

- **Stance and disposition, not just facts.** RAG can retrieve "user uses Rust." It can't
  answer "is the user a *beginner or expert*, and should I therefore over-explain?" That's a
  synthesized judgment over many weak signals — exactly what the deriver produces.
- **Contradiction handled as reasoning, not collision.** When a user changes their mind,
  fact stores either keep both rows or overwrite. Honcho's reasoning layer can hold the
  *trajectory* — "moved from X to Y" — as an inference about the person.
- **Personalization that actually steers generation.** The output is prompt-shaped natural
  language tuned to nudge the LLM's latent space toward this specific user, which is more
  directly useful than a list of retrieved facts.
- **Reported benchmark edge.** Third-party review reports ~90.4% on LongMemEval-S and ~89.9%
  on LoCoMo while using a median of ~5% of available context, vs ~65% for mem0 on
  LongMemEval ([andrew.ooo review](https://andrew.ooo/posts/honcho-plastic-labs-agent-memory-review/)).
  **Treat as reported, not independently verified** — single secondary source, and
  memory-benchmark numbers are notoriously setup-sensitive.

### 7. Weaknesses and limits (be honest)

- **Opacity — the big one.** The representation is an LLM-derived, prompt-shaped blob. There
  is *no per-claim provenance, no audit trail, no "why does it believe this and when did it
  learn it."* You get a confident synthesized answer; you can't `git blame` it. For a
  thesis about **transparency**, this is the decisive contrast — Honcho is a black box by
  construction, where Cicada's substrate is human-readable and version-traced.
- **No temporal decay.** Verified by absence: neither the architecture docs nor the README
  describe any decay, forgetting, or confidence-drop-over-time mechanism; the andrew.ooo
  review likewise reports none. Conflicts are resolved by reasoning, but *silence* (a topic
  going quiet) is not treated as signal. This is Cicada's other clean differentiator.
  **High confidence (argument-from-absence across three sources).**
- **LLM cost & latency on the reasoning path.** Every derivation and every Dialectic call is
  an LLM call. Cost is explicitly *not* quantified and depends on "the LLM you point Honcho
  at" plus embedding calls; latency of the async deriver is unspecified
  ([andrew.ooo review](https://andrew.ooo/posts/honcho-plastic-labs-agent-memory-review/)).
  The static-snapshot escape hatch exists precisely because live reasoning is too slow for
  the hot path.
- **Operational weight.** Requires PostgreSQL + Redis + an LLM dependency; reported ~30 min
  setup vs ~30 sec for mem0; unsuited to browser-only / strict-edge deployments
  ([andrew.ooo review](https://andrew.ooo/posts/honcho-plastic-labs-agent-memory-review/)).
  Cicada's "just a folder of markdown + git" is radically lighter.
- **AGPL-3.0 license.** Copyleth/network-copyleft. Fine for inspiration and for citing in
  related work; a constraint if Cicada ever wanted to vendor any of their code (it
  shouldn't — Cicada is reimplementing the *ideas*, not the code).
- **Subject mismatch with Cicada.** Honcho models *the person* (a mind). Cicada models *what
  the person knows* (a typed knowledge graph of their world). Not a weakness of Honcho per
  se, but it means most of Honcho is not directly portable — only the *interface* and the
  *self-model layer* are.

## What this means for Cicada

1. **The Dialectic endpoint is the single highest-value, lowest-cost steal — and D3 already
   commits to it.** Rodrigo has decided retrieval is BOTH NL-ask *and* file traversal. Honcho
   is the proof that the NL-ask front door is the right call. Cicada's version should be a
   Bookworm tool like `ask_memory("What does the user currently believe about X?")` that
   *synthesizes* an answer over the markdown graph + LEANN. **Cicada's substrate makes this
   strictly better than Honcho's**: the synthesized answer can cite `git blame` lines, show
   confidence, and link entity pages — a dialectic interface that is *also auditable*. That
   combination (NL reasoning over a transparent, versioned graph) is genuinely thesis-novel;
   Honcho has the reasoning but not the transparency, gbrain has the graph but a weaker ask.

2. **Theory of mind should graduate from one `skill` entity type into a real self-model
   layer — but stay scoped to D2 as research, not a build commitment.** Honcho's whole
   product is what Cicada currently squeezes into one of eight entity types ("Prefers concise
   summaries"). The VoE finding (loose mental-state inference > verbatim prediction) is the
   strongest evidence that a richer self-model — beliefs, open questions, changing positions —
   is worth modeling. And it dovetails with Cicada's decay: *a belief that stops being
   reinforced should decay*, which is a synthesis Honcho literally cannot express. Flag this
   as the most promising D2 direction without over-committing the entity model yet.

3. **Lean into the two differentiators in the thesis framing.** Against Honcho, Cicada wins on
   exactly two axes: **transparency** (markdown/git/provenance/confidence vs. an opaque
   reasoning blob) and **temporal decay as an active signal** (Honcho has none). These
   aren't incidental — they're the defensible contribution. The narrative writes itself:
   *"Honcho proves consolidate-then-reason beats retrieve-facts; Cicada adds the two things a
   black-box reasoning store structurally can't have — auditability and forgetting."*

4. **Peers / `(observer, observed)` — design awareness, not build (D4 stays research).** For a
   single-user personal system, perspectival memory is mostly overkill, and skipping it is
   the same "personal scale earns simplification" logic Cicada already used for "markdown over
   Neo4j." Worth one paragraph in related work and one sentence of design hygiene: don't bake
   in assumptions that would make a future multi-bank / multi-peer extension impossible
   (e.g., keep entity ownership/source attribution clean). Don't build it.

5. **Async deriver = independent validation of Sleep.** Cite Honcho's deriver/"dreaming" as
   convergent evidence that the Awake/Sleep split is the right shape. Two teams reinventing
   "cheap capture + background consolidation + fast static snapshot for the hot path" is a
   strong design argument to put in the thesis.

## Recommendation

**Adopt Honcho's *interface philosophy*, reject its *substrate*.** Concretely:

- **Build (post-research, D3-aligned):** a Dialectic-style `ask_memory` Bookworm tool that
  synthesizes a natural-language answer over Cicada's markdown+git graph + LEANN, returning
  the answer *with* provenance (git-blame citations), confidence, and entity links. This is
  the flagship feature to take from Honcho and is the clearest path to a novel thesis
  contribution. Keep direct file traversal alongside it (D3 = both).
- **Research deeper (D2):** elevating theory-of-mind from a single `skill` entity into a
  first-class, decay-aware self-model layer. Most promising entity-model direction; don't
  commit the schema yet.
- **Do not adopt:** Postgres/pgvector substrate, the opaque representation format, AGPL code,
  or (for now) the peers/perspectival model. Cicada's transparency and decay are *the* thesis
  differentiators — preserve them, don't trade them away for Honcho's reasoning depth.

Net: Honcho is the most important inspiration for *what the query interface should feel like*
and the strongest external validation of the consolidate-then-reason thesis. It is the
*anti-pattern* for transparency and forgetting. Steal the Dialectic front door; keep the
glass walls.

## Open questions (need Rodrigo's input)

1. **How much synthesis vs. pure traversal in `ask_memory`?** Honcho is 100% synthesized
   (opaque). Cicada could do "synthesize-but-always-cite." Is the target a fully reasoned
   answer (Honcho-style) or a guided traversal that returns pages + a short synthesized
   gloss (closer to gbrain's "think" mode)? Affects cost/latency budget and how central the
   LLM is on the read path.
2. **Does the self-model layer (D2) become a 9th entity type, a cross-cutting overlay, or a
   separate "beliefs" store?** Honcho keeps it perspectival and separate; Cicada currently
   flattens it into `skill`. This is the core D2 decision and the doc can only point at it.
3. **Is decay-aware belief modeling in scope for the thesis, or related-work future work?**
   It's the most novel synthesis (decay × theory-of-mind, which Honcho can't do) but also the
   most speculative to build before submission.
4. **Latency/cost budget for the read path.** If `ask_memory` makes an LLM call per query,
   what's the acceptable p95? Honcho dodges this with static snapshots; does Cicada need an
   equivalent cached-representation layer, or is per-query reasoning fine at personal scale?
5. **Benchmark posture.** Honcho's ~90% LongMemEval/LoCoMo numbers are reported, not
   verified. Does Cicada want to run on the same public benchmarks for comparability, or stay
   with the bespoke four-dimensional recall rubric already in `benchmarks/`? Comparability
   would strengthen the "we trade some recall for transparency+decay" claim — *if* the
   numbers hold up.

---

### Sources

- Honcho architecture / core concepts: <https://honcho.dev/docs/v2/documentation/core-concepts/architecture>
- Honcho GitHub (README, AGPL-3.0, ~5.2k stars): <https://github.com/plastic-labs/honcho>
- Introducing Honcho's Dialectic API (archived): <https://plasticlabs.ai/blog/archive/ARCHIVED;-Introducing-Honcho's-Dialectic-API>
- Loose theory-of-mind imputations > verbatim response predictions: <https://plasticlabs.ai/blog/notes/Loose-theory-of-mind-imputations-are-superior-to-verbatim-response-predictions>
- Theory-of-Mind Is All You Need: <https://blog.plasticlabs.ai/blog/Theory-of-Mind-Is-All-You-Need>
- User State is State of the Art: <https://blog.plasticlabs.ai/blog/User-State-is-State-of-the-Art>
- Leer, Trost, Voruganti (2023), VoE / metacognitive prompting reduces ToM prediction error: <https://arxiv.org/html/2310.06983> (eval code: <https://github.com/plastic-labs/voe-paper-eval>)
- tutor-gpt / Bloom (product lineage): <https://github.com/plastic-labs/tutor-gpt>
- Third-party review (benchmarks, infra, limitations — reported, not independently verified): <https://andrew.ooo/posts/honcho-plastic-labs-agent-memory-review/>
- Plastic Labs blog index: <https://blog.plasticlabs.ai/>
