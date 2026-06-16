# Inspiration & Related Systems

Comparative analyses of adjacent memory / second-brain systems, kept as a reference
for a planned **wave of improvements** to Cicada. Each entry: what the system is, why
it's good, what's worth stealing, and where it maps onto Cicada's architecture.

> Notes-to-self, not commitments. Use them to seed roadmap items.

## Systems

- [**Honcho** (Plastic Labs)](honcho.md) — "memory is reasoning, not retrieval"; theory
  of mind via `(observer, observed)` peer representations; the **Dialectic API**.
  <https://honcho.dev/> · <https://github.com/plastic-labs/honcho>
- [**gbrain** (Garry Tan)](gbrain.md) — the convergent twin: markdown+git, self-wiring
  typed graph, overnight enrichment, MCP. `gbrain think` = synthesized answers with
  **gap analysis**. <https://github.com/garrytan/gbrain>

---

## Cross-cutting takeaways for the improvement wave

Both systems independently point at the **same two gaps** in Cicada:

1. **Retrieval should return *answers*, not pages.** Honcho (dialectic) and gbrain
   (`think`) both moved past "return chunks." Cicada's transparent substrate makes its
   version *better*: answer + git-blame citations + gap analysis + confidence. Single
   highest-leverage idea here → candidate `POST /ask` endpoint + `cicada_ask` MCP tool.
2. **Model the user's epistemic state, not just their world.** Honcho's theory-of-mind
   and gbrain's salience/contradiction scoring both track *how confident/current* knowledge
   is. Cicada has the raw materials (confidence, decay, provenance) but doesn't yet
   *synthesize* them into a belief-state answer.

Where Cicada stays differentiated against both: **temporal decay as an active signal**,
**git/markdown transparency end-to-end**, the **entity promotion model**, and a
**human-facing curation app**. Lean into these in the thesis; borrow the answer-synthesis
interface from them.
