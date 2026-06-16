# Honcho (Plastic Labs)

- Site: <https://honcho.dev/>
- GitHub: <https://github.com/plastic-labs/honcho>
- License: AGPL-3.0 · Stack: FastAPI + Postgres/pgvector, Python & TS SDKs

> Reference note for Cicada's planned improvement wave. See [`README.md`](README.md)
> for cross-cutting takeaways and the [`gbrain`](gbrain.md) companion analysis.

## What it is

An **AI-native memory platform** whose central bet is different from almost everyone
else's: **memory is reasoning, not retrieval.** Most memory systems (mem0, Zep, plain
RAG) store facts and fetch the relevant ones. Honcho stores raw messages, then runs
background reasoning to build a *model of the person* — beliefs, preferences, how they
think — and serves that model back. The intellectual core is **theory of mind**:
"what does this agent know/believe about this user, and how is the user changing?"

## Primitives

| Primitive | What it is |
|---|---|
| **Workspace** | Top-level isolation boundary |
| **Peer** | *Any* participant — human or agent — as a first-class entity (not "user vs assistant") |
| **Session** | A conversation among multiple peers, with configurable observation |
| **Representations** | Per-peer derived models, keyed by `(observer, observed)` pairs |
| **Dialectic / Chat endpoint** | You ask Honcho a natural-language question *about a peer* and it answers from the model |

## The genuinely interesting parts

1. **`(observer, observed)` keying.** Memory is *perspectival*, not global. What Alice
   knows about Bob is a separate collection from what Bob knows about himself. Real
   theory-of-mind plumbing, not a metaphor.
2. **The Dialectic API.** Instead of `search(query) → chunks`, you do
   `chat("Is this user a beginner or expert at Rust?") → reasoned answer`. The memory
   system *is* an agent you interrogate, not an index you query. Nobody else really has this.
3. **Async "Dreaming"/"Neuromancer".** Background reasoning that synthesizes patterns,
   tests hypotheses, resolves conflicts — off the hot path so runtime stays ~200ms.
   **This is Cicada's Sleep cycle, independently reinvented.**

## Honcho vs Cicada

| Dimension | Honcho | Cicada |
|---|---|---|
| What's stored | Derived *conclusions/representations* (about people) | A *knowledge graph of typed entities* (the user's world) |
| Substrate | Postgres + pgvector, opaque | Markdown + git, human-readable, Obsidian-compatible |
| Subject of memory | The **user as a mind** (theory of mind) | The user's **knowledge & relationships** |
| Retrieval | Dialectic ("ask about the peer") | Wikilink graph traversal + LEANN |
| Transparency | Reasoning implicit, in vectors | Provenance via git blame, confidence, versions |
| Decay | Conflict resolution, hypothesis testing | First-class **temporal decay as signal** |

**Key insight: Honcho models *you*; Cicada models *what you know*.** Complementary, not
competing. Cicada's `skill`-type entities ("Prefers concise summaries") are the one place
Cicada already does Honcho-style theory-of-mind — currently just one of 8 entity types
rather than the whole product.

## What to steal (ranked by fit)

1. **A Dialectic endpoint — highest value, lowest cost.** Add a Bookworm tool like
   `ask_memory("What does the user currently believe about X?")` that synthesizes an
   answer with confidence + provenance instead of returning raw pages. Cicada's
   markdown+git substrate is *better* than vectors for this because the answer can cite
   `git blame` lines. Thesis-worthy: **a dialectic interface over a transparent, versioned graph.**
2. **Theory-of-mind as a first-class layer, not just a `skill` entity.** Elevate `skill`
   into a richer self-model that tracks beliefs, open questions, and changing positions —
   which dovetails with decay (a belief that stops being reinforced decays).
3. **Peers / perspectival memory — probably out of scope** for single-user personal
   memory, but worth one line in related-work as the simplification personal scale earns
   (same logic as "markdown over Neo4j").

## Thesis framing

Honcho is the strongest *independent* argument that "consolidate-then-reason" beats
"retrieve facts" — it validates Cicada's core thesis from another team. Cicada's
differentiators against it: **transparency** (markdown/git/provenance vs. an opaque
reasoning blob) and **temporal decay as an active signal** (Honcho lacks it).
