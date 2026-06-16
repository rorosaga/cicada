# gbrain (Garry Tan)

- GitHub: <https://github.com/garrytan/gbrain>
- Stack: TypeScript (~97%), PGLite / Postgres + pgvector, HNSW + BM25, BullMQ job queue, MCP server (stdio + HTTP/OAuth 2.1)

> Reference note for Cicada's planned improvement wave. See [`README.md`](README.md)
> for cross-cutting takeaways and the [`honcho`](honcho.md) companion analysis.

## What it is

A **production-grade, agent-operated knowledge brain** — "an intelligent intermediary
between agents and knowledge bases." Tagline: *"Search gives you raw pages. GBrain gives
you the answer."* Explicitly framed against **agent amnesia**. Note the framing
difference from Cicada: gbrain is a memory layer *for agents* (and teams), not a
human-facing PKM tool — though the substrate is nearly identical to Cicada's.

## How it works

- **Two query modes:** `gbrain search` (hybrid vector + BM25, ranked pages) and
  `gbrain think` (synthesized prose answer with citations **and explicit gap analysis**).
- **Loop:** signal detection → brain-first retrieval → informed response → auto-linking →
  overnight enrichment cycles.
- **Markdown files as system of record in git repos**, synced to a DB for retrieval.
- **Self-wiring knowledge graph with typed edges** (`works_at`, `invested_in`, `founded`,
  `advises`), built by **zero-LLM entity extraction on every page write**.
- **Schema packs** = custom page types (person, company, meeting) instead of a fixed schema.
- **Autonomous enrichment cron** runs 24/7: dedupe, fix citations, score salience, find
  contradictions.
- **Thin harness, fat skills:** minimal core + 43 curated agent skills.
- **Eval framework:** LongMemEval, NamedThingBench; reports **+31.4 P@5 over vector-only RAG**.

## gbrain vs Cicada — the convergent twin

This is the closest existing system to Cicada's architecture. Independent convergence on
nearly every core decision:

| Decision | gbrain | Cicada |
|---|---|---|
| System of record | **Markdown in git** | **Markdown in git** ✅ same |
| Graph | Self-wiring, **typed edges** | Wikilinks + `graph_edges.yaml`, typed `related` |
| Entity extraction | **Zero-LLM on write** | LLM during Sleep (promotion-gated) |
| Background consolidation | **24/7 enrichment cron** | **Sleep cycle** ✅ same idea |
| Retrieval | **Hybrid vector + BM25** | LEANN (vector) + graph traversal |
| "Answer not pages" | `gbrain think` (synthesis + **gap analysis**) | currently returns pages/chunks |
| Schema | **Schema packs** (open page types) | **Closed set of 8 entity types** |
| Interface | MCP (stdio + HTTP/OAuth) | MCP "Bookworm" |
| Eval | LongMemEval, NamedThingBench, P@5 | Custom Table 1/2/3 benchmarks |
| Audience | **Agents / teams** (federated, scope-gated) | **Single human user** (personal) |

## What to steal (ranked by fit)

1. **`think` mode with explicit gap analysis — highest value.** Same idea as Honcho's
   dialectic, but gbrain adds the killer feature: **the answer states what it *doesn't*
   know.** For Cicada this is huge — a synthesized answer that says "confidence is low,
   the graph has no edge between X and Y, last referenced 3 weeks ago" turns Cicada's
   transparency principle into a retrieval feature. Combine with Honcho's dialectic: one
   `POST /ask` endpoint returning *answer + citations (git blame) + gap analysis + confidence*.
2. **Zero-LLM entity extraction on write.** gbrain extracts typed edges deterministically
   on every page write — no LLM cost, instant. Cicada defers everything to Sleep. A cheap
   deterministic pass at capture time could pre-populate candidate edges for Sleep to
   confirm, making the graph denser without LLM spend. (Tension with Cicada's "no LLM at
   capture" principle — but this *isn't* an LLM, it's regex/NER, so it's compatible.)
3. **An eval harness against public benchmarks (LongMemEval).** Cicada's benchmarks are
   bespoke. Running a public memory benchmark would give the thesis an external,
   comparable number — strong for the Results section.
4. **Schema packs vs. closed 8-type set.** gbrain bets on extensibility; Cicada bets on a
   curated closed set. Worth a *defense* in the thesis: closed set = cleaner graph, better
   node coloring, no schema sprawl at personal scale. (Same family of argument as the v2
   decision that `hub`/`media` are deliberate, bounded additions.)
5. **Contradiction detection as a named enrichment step.** gbrain runs cross-modal
   contradiction detection in cron; Cicada has conflict nudges. Worth confirming Cicada's
   Sleep stage 3 is as aggressive about *cross-entity* contradictions, not just
   within-entity recency.

## Thesis framing

gbrain is the **architectural validation**: an independent, production-grade,
benchmark-evaluated team converged on Cicada's exact substrate (markdown + git +
self-wiring graph + overnight enrichment). Cicada's distinct contributions on top:
**temporal decay as signal**, **promotion model** (avoid graph pollution), **biological
Awake/Sleep framing**, and a **human-facing companion app** (gbrain is agent/team-facing).
The two features Cicada most clearly lacks vs. gbrain are **`think`-style synthesized
answers with gap analysis** and **public-benchmark evaluation** — both are addressable.
