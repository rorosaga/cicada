# Memory Evolution — Research Findings

Index + synthesis for the eight research notes commissioned during Cicada's v2
improvement wave (2026-06-16). Each note investigates one question feeding the four
open decisions in [`../../goals/memory-evolution.md`](../../goals/memory-evolution.md):
**D1 storage**, **D2 entity model**, **D3 retrieval interface** (already decided = BOTH),
**D4 peers / multi-bank**. D1, D2, D4 are research-only (inform, don't commit); D3 is
committed and these notes scope *how* to build it.

## The eight notes

| # | Doc | One-line takeaway |
|---|-----|-------------------|
| R1 | [r1-honcho-philosophy.md](r1-honcho-philosophy.md) | Steal Honcho's Dialectic *NL-ask front door*, reject its opaque substrate — Cicada can ship a synthesized `ask_memory` that is *also* git-blame auditable, which Honcho structurally cannot. |
| R2 | [r2-skillopt.md](r2-skillopt.md) | SkillOpt (MSR) treats `skill.md` as a trainable artifact behind a strict validation gate; "library drift" proves ungoverned self-improving skills go net-negative — adopt the *governance pattern* (failure ledger + bounded gated rewrites), not the optimizer. |
| R3 | [r3-postgres-pgvector.md](r3-postgres-pgvector.md) | Keep markdown+git as source of truth, replace LEANN with a stored-embedding derived index (default sqlite-vec, pgvector as upgrade path) — LEANN trades latency for a storage win Cicada doesn't need and that now fights D3. |
| R4 | [r4-contextual-entities.md](r4-contextual-entities.md) | Model context-dependent identity as one canonical entity + optional named "facets" (lenses) with independent decay/confidence/provenance; reject separate per-context graphs. |
| R5 | [r5-reconsolidation-cost.md](r5-reconsolidation-cost.md) | Reconsolidation is cheap ($1–4 cheap-tier / $10–20 quality-tier per full pass at current scale); cost isn't the constraint — graph-size scaling and merge-quality are. Run incremental cheap-tier nightly, route only disambiguation/conflict to Sonnet/Opus. |
| R6 | [r6-sync-connectors.md](r6-sync-connectors.md) | Build connectors as dumb Awake-phase *episode emitters* so the Sleep pipeline absorbs them with zero new code; ship keyless Netscape-HTML bookmarks + RSS for MVP, defer auth-heavy Notes/Spotify/Readwise. |
| R7 | [r7-entity-promotion.md](r7-entity-promotion.md) | Soften, don't kill: replace the hard 2nd-mention gate with decay-pruned *shadow/candidate entities*; keep the 8 types as a colored default but make them extensible. Unbundle "promotion gate" from "closed taxonomy". |
| R8 | [r8-peer-model.md](r8-peer-model.md) | Don't build Honcho's full `(observer, observed)` network for single-user; adopt the cheap slice (opinion-vs-observed split, an upgraded `skill` self-model), and *design* a peer-ready `observer`-defaults-to-`self` substrate without building it. |

---

## Cross-cutting synthesis

A few themes recur across all eight notes and tie them together before the per-decision
breakdown:

- **markdown+git is the moat; everything else is derived or layered.** R1, R3, R4, R7, R8
  independently conclude that Cicada's transparency/provenance/portability lives in the
  *files*, and that vector indexes, peer perspectives, facets, and shadow entities are all
  *derived or additive layers on top* — none should threaten the canonical substrate. This
  is the single strongest cross-cutting result and it keeps every decision reversible.
- **"Consolidate then reason" is externally validated, twice.** Honcho's async "deriver"
  (R1) and SkillOpt's nightly "SkillOpt-Sleep" (R2) are two independent teams reinventing
  Cicada's Awake/Sleep split — strong thesis-grade validation of the core architecture.
- **Cicada's two defensible differentiators are transparency (git-blame provenance) and
  temporal decay as active signal.** R1 verifies Honcho has neither; R2's failure-ledger,
  R4's per-facet decay, R7's decay-as-pruner, and R8's faster-decaying opinion layer all
  *extend* decay into new territory. Decay is the through-line that makes each borrowed idea
  land differently than the system it was borrowed from.
- **Push the "context dimension" down a level, and surface synthesis at retrieval.** R4 and
  R8 converge: scope claims by `(context, subject)` (facets) now, generalize to
  `(observer, context, subject)` (peers) later; and treat "connect non-obvious things"
  /"whose view is this" as *retrieval-time* behaviors on the D3 ask endpoint, not storage
  changes.

### D1 — Storage backend (research-only)

**What the research implies.** R3 is decisive and R5/R8 reinforce it. The storage question
splits cleanly into two independent decisions: *source of truth* (settled — markdown+git,
because that's where provenance/transparency/Obsidian-portability live, none of which come
from the index) and *what powers retrieval* (a **derived, disposable** index). LEANN
optimizes storage at the cost of ~2s query latency — a win Cicada doesn't need at ~1,882
entities (single-digit MB of raw embeddings) and a latency tax that now actively conflicts
with D3's interactive ask endpoint and live graph filtering. gbrain — the most
architecturally convergent system — already does exactly this: markdown-canonical, DB-derived
hybrid (vector + BM25) retrieval, reporting +31.4 P@5 over vector-only. R5 confirms a full
re-embed/reconsolidation is cheap, so a rebuildable derived index is low-risk; R8 notes a
single-user system doesn't need Postgres concurrency.

**Recommendation.** Adopt the **hybrid architecture**: keep markdown+git as the immutable
source of truth; **replace LEANN with a stored-embedding derived index rebuilt by the Sleep
cycle** (slots into stage 5 alongside the versioned snapshot). Default to **sqlite-vec**
(embedded, no daemon, ships in the app bundle — right infra profile for a single-user macOS
app), and **document pgvector as the upgrade path** for Honcho-grade hybrid (true BM25 via
`pg_textsearch` + RRF) or a future server/multi-user deployment. Because the index is
*derived*, switching sqlite-vec → pgvector later is a rebuild, not a migration — so D1 stays
reversible and the only genuinely open sub-call is how central best-in-class hybrid search is
to the thesis's quality story. *Before writing any storage section: run `du -sh memory/leann`
and time a real query — if LEANN latency is already sub-300ms, the urgency drops though the
hybrid/metadata-filter arguments stand.*

### D2 — Entity model philosophy (research-only)

**What the research implies.** R7, R4, R1, R8, and R2 all bear on D2 and they point the same
way: *soften and layer, don't rip out*. R7's central reframe is that the **promotion gate**
and the **closed 8-type taxonomy** are two bundled-but-independent decisions. The hard "no
node until 2nd mention" gate is *more aggressive than the hippocampal framing it claims*
(the brain forms a labile one-shot trace and lets it decay), it starves cross-linking (you
can't draw an edge to a node that doesn't exist), and it leaves dropped entities invisible
and recall unmeasurable. R4 says context-dependent identity (engineer-self vs family-self)
should be one canonical entity + optional **facets**, never separate graphs. R1+R8 agree the
single overloaded `skill` type should graduate into a richer, decay-aware **self-model /
opinion layer**. R2 adds that any entity-body rewrite (skills included) must be
failure-driven, bounded, and gated.

**Recommendation.** Treat D2 as a coordinated set of *additive softenings* on the existing
model, all preserving the colored-node + git-provenance story:

1. **Soften the gate to shadow/candidate entities** — materialize a weak, low-confidence,
   `type: unresolved` stub on first substantive mention; let existing decay prune it if
   unreinforced. Same anti-pollution outcome, but now measurable, linkable, and more
   biologically faithful. (R7, headline.)
2. **Keep the 8 types as a colored default, make them extensible** with a `concept`/
   `unresolved` catch-all so Sleep never force-fits. (R7.)
3. **Promote the user's self-model to a first-class faceted entity** with per-facet decay —
   the clearest home for the engineer/family/philosophy lenses and the upgraded `skill`/
   theory-of-mind layer R1/R8 both call for. (R4 + R1 + R8.)
4. **Move abstract cross-linking into first-class cluster/tag nodes + edge enrichment**, not
   the type system — that's where cross-domain abstraction actually lives. (R7.)
5. **Add a git-versioned failure ledger + bounded, gated entity-body rewrites** as a unified
   "validation-gated, failure-driven revision" mechanism, human-approval-gated by default.
   (R2.)

The unifying thesis frame: *Cicada keeps a clean, legible, colored graph (its precision/
transparency win) but adds shadow entities (measurable recall), facets (per-context decay),
and a failure-gated revision loop (governed self-improvement) — each a decay-aware extension
no adjacent system has.*

### D3 — Retrieval interface = BOTH (committed)

**What the research implies.** D3 is already decided (NL `ask`/dialectic endpoint *and*
direct file traversal), and the research strongly endorses it. R1 names Honcho's Dialectic
API as the single highest-value, lowest-cost steal and shows Cicada's version is *strictly
better*: a synthesized answer that cites `git blame` lines, shows confidence, links entity
pages, and admits gaps — a dialectic interface that is also auditable, which is genuinely
thesis-novel (Honcho has the reasoning but not the transparency; gbrain has the graph but a
weaker ask). R3 says the ask endpoint *wants* a low-latency hybrid (BM25+vector) index with
metadata filters — directly motivating the D1 LEANN→derived-index move. R4 and R7 both note
that the "connect not-obviously-related things" / bridge-finding wish is a **retrieval-time
mode** on this endpoint (analogical/bridge mode with gap analysis), *not* a storage change.
R5 flags the open cost/latency question: every `ask` is an LLM call, so a p95 budget and
possibly a cached-representation layer (Honcho's static-snapshot trick) need defining.

**Recommendation.** Build the **`ask_memory` Bookworm tool** as the flagship D3 feature:
synthesize an answer over markdown+graph+derived-index, **always returning provenance
(git-blame citations) + confidence + explicit gap analysis** (folds in backlog item A5),
and keep direct file traversal alongside. Add a **`mode="bridges"` analogical/cross-facet
retrieval mode** (fed by Sleep-staged candidate links the user approves) as the home for the
"connect non-obvious things" wish. Resolve two open calls early: (a) how much pure synthesis
vs guided-traversal-with-gloss, and (b) the read-path latency budget / whether a cached
representation layer is needed. This is the work that depends on D1's derived index, so
sequence them together.

### D4 — Peers & multi-bank scope (research-only)

**What the research implies.** R8 (with R1) is clear: do **not** build Honcho's full
`(observer, observed)` peer network for the single-user MVP — at one trusted observer it's
N×-cost for N≈1, and the MAS literature's own "epistemic drift" warnings make it mostly
downside. But there's one cheap, high-value slice: an explicit **opinion-vs-observed split**
(keep `entities/` as asserted facts; treat the agent's abductive beliefs/self-model as a
separable, *faster-decaying* opinion layer — which is the same `skill`-self-model upgrade
D2/R1/R4 already want). R4's facet key `(context, subject)` and R8's observer axis compose:
design so a future world is the clean generalization `(observer, context, subject)`, one
field added later, no migration. R8 also gives a strong, low-cost thesis figure: a d3
"disagreement halo + peer-filter toggle" that makes perspectival memory concrete *even as a
mockup*.

**Recommendation.** **Adopt the opinion-vs-observed slice now** (start as enriched
self-model/`skill` frontmatter with a `basis_type` deductive/inductive/abductive field
borrowed from Honcho; wire decay so opinions fade faster than asserted facts). **Design but
do not build** the full `peers/` + `perspectives/<observer>/` layout, with an optional
`observer` axis defaulting to `self` across schema, the `/ask` endpoint, and d3 — so turning
peers on later is additive. **Gate the full build on a concrete second observer** (robot,
second agent, teammate, or multi-user mode). Ship the disagreement-halo + peer-filter
*design/mockup* as a thesis figure; frame peers as "the simplification personal scale earns"
(one trusted observer), mirroring "markdown over Neo4j," with Honcho + Rashomon/Belief-Memory
as related work.

---

## Suggested sequencing

Ordered by dependency and leverage. The first block is foundational (D1+D3 are coupled and
unlock the flagship feature); later blocks are additive and individually shippable.

1. **Instrument first (cheap, de-risks everything).** Run `benchmarks.run_table3` with token
   `usage` accounting (R5) and measure real LEANN size/latency (`du -sh memory/leann` + a
   timed query, R3). These convert modeled numbers to measured ones and confirm/deny the
   urgency of the LEANN swap before any code changes.
2. **D1 derived index → unblocks D3.** Replace LEANN with a Sleep-rebuilt stored-embedding
   index (sqlite-vec default), giving the low-latency hybrid retrieval the ask endpoint
   needs. (R3) Do this before/with the ask endpoint — they're coupled.
3. **D3 `ask_memory` flagship.** Synthesized answer + git-blame citations + confidence + gap
   analysis (A5), over the new index; keep file traversal. This is the highest-leverage,
   most thesis-novel single feature. (R1, R3)
4. **D2 self-model facets + shadow-entity softening.** Promote the user self-model to a
   first-class faceted entity (R4), then introduce shadow/candidate entities + decay-pruning
   and the extensible-type catch-all (R7). Self-model first because it's the highest-value,
   lowest-risk facet target; shadow entities second because they add Sleep dedup work.
5. **R2 failure-ledger + gated revision loop.** Add the `## Failures` section, bounded
   `sleep/skill_revision` rewrites, and human-approval-by-default gate. Independent of the
   above; sequence by appetite.
6. **R6 connectors (parallelizable any time).** Ship the keyless Netscape-HTML bookmark
   importer (reuses upload UI) + RSS connector as Awake episode emitters — zero new Sleep
   code, immediate "feed" demo. Defer Notes/Readwise/Spotify as labeled post-MVP.
7. **D4 / R8 as design + mockup, last.** Land the opinion-vs-observed `basis_type` slice
   while building the self-model (step 4), but keep the full peer network and the
   disagreement-halo/peer-filter as a *designed* thesis figure, not a build — gated on a real
   second observer.
8. **Bridge/analogy retrieval mode, last and lowest-confidence.** Add `ask_memory(mode=
   "bridges")` once facets exist; validate with a small experiment before committing thesis
   claims, since cross-connection quality on a personal-scale graph is genuinely unproven.
   (R4, R7)
