# Goal: Memory Evolution (improvement wave)

Backlog distilled from Rodrigo's notes (2026-06-16). Triaged into three tracks:
**APPLY** (buildable now, low architecture risk), **RESEARCH** (needs investigation —
findings land in [`../inspiration/research/`](../inspiration/research/)), and **DECIDE**
(needs Rodrigo's call before work proceeds — see "Open decisions" at bottom).

Status legend: 🔲 todo · 🔬 researching · ❓ awaiting decision · 🛠️ in progress · ✅ done

Related: [`../inspiration/`](../inspiration/) (Honcho + gbrain analyses), [`../V2-ROADMAP.md`](../V2-ROADMAP.md).

---

## Implementation progress (branch `feat/memory-evolution`)

- ✅ **M1 — storage spine (D1):** LEANN replaced by `SqliteVecIndexer` (sqlite-vec,
  stored embeddings, derived/rebuildable). Entities + episodes + pending all ported;
  all consumers rewired (sleep_cycle, entity_resolver, routers, mcp). **EmbeddingGemma-300M**
  (768-dim, gated — HF auth done) is the default on-device backend, off the OpenAI API;
  asymmetric query/document prompts; model+dim recorded in the index. Verified end-to-end
  on real `memory/` (e.g. *"company I interned at"* → amazon). 7 tests green.
  - *Remaining cleanup:* remove `leann` dependency + delete `leann_indexer.py`; consider
    a one-off full reindex of the live 1,882-entity graph (~10–15 min CPU).
- ✅ **M2 — `ask_memory` endpoint (D3=BOTH):** `POST /ask` + `api/services/ask_service.py`
  (`answer_query(memory_path, query, top_k, *, retrieve_fn=None, llm_fn=None)`). Auditable
  synthesis: a grounded NL answer with **entity-level citations** (id, name, file_path,
  snippet, source_episodes) and explicit **gap analysis** (honest "I don't have information
  about X" — folds in A5). Empty/low retrieval => honest gap answer, low confidence, **no
  LLM call, no hallucination**. Retrieval defaults to `SqliteVecIndexer.search_entities`,
  synthesis to litellm JSON-mode per `Settings`; both injectable for hermetic tests.
  `cicada_ask` MCP tool wraps it (prefers running backend, degrades to the service direct).
  6 new TDD tests (`api/tests/test_ask_service.py`); full suite 13 green.
  - *Follow-up (nice-to-have):* line-level git-blame citations (entity-level shipped);
    request-time top_k tuning + answer caching.

## APPLY — buildable now (low architecture risk)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| A1 | **Per-commit diff view in node history** | Expand entity history to show added-vs-removed (git diff per entity per commit). Builds on existing `/entities/{id}/history`. | 🔲 |
| A2 | **Contributors view** | Which LLM model wrote which contribution to memory. Record model id in Sleep commit metadata/trailers; surface a "contributors" view + per-node attribution. | 🔲 |
| A3 | **Animated bookworm on ingestion page** | Reuse the menu-bar tamagotchi sprite/state machine on the conversation-upload/ingestion screen. | 🔲 |
| A4 | **Enrich `skill` entity capture** | Store "Rodrigo usually asks to do X a certain way" (e.g. FastAPI project layout & repo structure conventions). Procedural-preference skills. → ties to D2/D5. | 🔲 |
| A5 | **Explicit gap analysis ("I don't know")** | Retrieval/answer surface admits what it does NOT know (no edge between X/Y, low confidence, stale `last_referenced`). Endorsed by both Honcho & gbrain notes. → ties to D3. | 🔲 |

> Note: A4/A5 partly depend on the decisions below; listed here because the mechanics are
> low-risk even if the framing shifts.

## RESEARCH — findings documented by background workflow

✅ **Done (2026-06-16).** Findings + synthesis in [`../inspiration/research/`](../inspiration/research/)
([index & cross-cutting synthesis](../inspiration/research/README.md)).

| ID | Topic | Headline recommendation | Status |
|----|-------|-------------------------|--------|
| R1 | [Why Honcho is good (deep)](../inspiration/research/r1-honcho-philosophy.md) | Steal the Dialectic NL-ask front door; reject the opaque substrate. Cicada's ask can be git-blame auditable — thesis-novel. | ✅ |
| R2 | [SkillOpt (Microsoft)](../inspiration/research/r2-skillopt.md) | Adopt the *governance pattern* (failure ledger + bounded gated rewrites), not the optimizer. Ungoverned self-improving skills drift net-negative. | ✅ |
| R3 | [Postgres+pgvector vs markdown+git+LEANN](../inspiration/research/r3-postgres-pgvector.md) | Keep markdown+git as source of truth; **replace LEANN with a Sleep-rebuilt stored-embedding index** (sqlite-vec default, pgvector as upgrade path). | ✅ |
| R4 | [Contextual / multi-dimensional entities](../inspiration/research/r4-contextual-entities.md) | One canonical entity + optional named **facets** (per-context lenses, independent decay). Reject separate per-context graphs. | ✅ |
| R5 | [Cost model for reconsolidation](../inspiration/research/r5-reconsolidation-cost.md) | Cheap ($1–4 cheap-tier / $10–20 quality per full pass). Cost isn't the constraint. Nightly incremental cheap-tier; route only conflicts to Sonnet/Opus. | ✅ |
| R6 | [Sync connectors](../inspiration/research/r6-sync-connectors.md) | Build connectors as Awake-phase **episode emitters** (zero new Sleep code). Ship keyless bookmarks HTML + RSS first; defer Notes/Spotify/Readwise. | ✅ |
| R7 | [Entity promotion: keep or kill?](../inspiration/research/r7-entity-promotion.md) | **Soften, don't kill**: hard 2nd-mention gate → decay-pruned shadow/candidate entities. Unbundle "promotion gate" from "closed taxonomy". | ✅ |
| R8 | [Peer / observer-observed model](../inspiration/research/r8-peer-model.md) | Don't build the full peer network for single-user. Adopt the cheap slice (opinion-vs-observed split); design a peer-ready `observer`-defaults-to-`self` substrate. | ✅ |

## DESIGN — new structures (proposals, pending decisions)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G1 | **Multiple memory banks / "memory projects"** | Several versioned memory banks for re-consolidating past conversations (another model, or parallel ongoing banks for testing). Banks cross-reference. → ties to D2/D4. | ❓ |
| G2 | **Extend entity taxonomy** | New types: website/bookmark, research paper, idea, project-note, recipe, song/media, … Reference e.g. a song on another entity's wiki page with a personal-relevance note. → gated by D2. | ❓ |
| G3 | **Bookworm "feed" knowledge page** | Sync-driven feed (bookmarks first), each item an entity with summary + *personal* relevance. Filterable view across articles/bookmarks/songs by a **relevance metric**. | ❓ |
| G4 | **Problem-log entity sections** | "We solved this problem by doing X" + open-ended "we discussed this — how did it end up going?" Likely sections under project/concept entities. | 🔲 |
| G5 | **"Project improvements" sections** | Things discussed to improve on a given project. Probably a section grammar under `project` entities. | 🔲 |
| G6 | **Entity-type audit interface** | A way to easily audit which entity types exist and structure info per type (section grammar per type). Meta-tooling over the taxonomy. | 🔲 |
| G7 | **Reduce Rodrigo-node centrality** | "Rodrigo" is over-central; introduce more intermediate hub/bridge nodes. Overlaps v2 hubs work. | 🔲 |
| G8 | **Agent-research memory + opinions** | Memory of agents' work (e.g. the Honcho mini-research, with raw traces). A second agent can add an *opinion* → two versions of the same memory side by side (observer/observed). → ties to D4/R8. | ❓ |

---

## Open decisions (asked to Rodrigo — answers recorded here)

These are the foundational forks; most of the backlog hangs off them.

- **D1 — Storage backend.** Stay markdown+git+LEANN? Move toward Postgres+pgvector (Honcho/gbrain)? Hybrid (markdown = source of truth, pg = index)? — _awaiting_
- **D2 — Entity model philosophy.** Keep closed 8-type set + promotion gate? Move toward Honcho-style emergent/belief/observer-observed (drop promotion)? Hybrid (entities + per-context dimensions)? — _awaiting_
- **D3 — Retrieval interface.** Add a natural-language `ask`/dialectic endpoint (agent queries memory in NL)? Keep direct file traversal? Both? — _awaiting_
- **D4 — Peers & multi-bank scope.** Build peers (humans/agents/robots equal) + multiple memory banks as a near-term feature, or research-only for now? — _awaiting_

> Answers (2026-06-16):
>
> - **D1 (storage): DECIDED (2026-06-17)** — markdown+git stays the source of truth; **add a derived embedding index, and Rodrigo is willing to go straight to Postgres+pgvector** (rather than sqlite-vec first) so pgvector + derived indexes land directly, then the ask endpoint. Research recommended sqlite-vec-first for a single-user bundle; the Postgres-direct path is viable because the index is *derived/rebuildable* — see dossier §D1 for the tradeoff. LEANN is being replaced either way.
> - **D2 (entity model): research-only** — no commitment yet; R4 + R7 findings inform it. Keep closed types + promotion for now.
> - **D3 (retrieval): BOTH** ✅ — add a natural-language `ask`/dialectic endpoint (answer + git-blame citations + gap analysis) AND keep direct file traversal. → unblocks A5; new design item.
> - **D4 (peers + multi-bank): research-only** — design the peer (observer/observed) model + multi-bank "memory projects", don't build yet. R8 informs it.

**Consequence of D3 = BOTH:** the `ask`/dialectic endpoint is now a committed design item
(not just research). It folds in A5 (gap analysis) and the Honcho/gbrain "answer not pages"
insight. Spec to be written once R1/R7 land. Everything else stays research-gated.
