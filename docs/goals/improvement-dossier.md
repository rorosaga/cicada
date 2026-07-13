# Cicada Improvement Dossier

**Author of record:** Rodrigo Sagastegui (ideas & direction) · compiled with Claude Code
**Date:** 2026-06-17 · **Branch:** `feat/v2-revamp`
**Status:** planning artifact — *nothing here is implemented yet.* This is the reference
we build from.

> This document collects everything we figured out for the next wave of Cicada
> improvements: the research findings, **Rodrigo's own ideas** (preserved verbatim in
> intent and credited), the reasoning behind each recommendation, and *how* each finding
> was produced so the provenance is auditable. It is deliberately long — it is meant to be
> the single place to re-orient from.

Companion docs:
- [`memory-evolution.md`](memory-evolution.md) — the triaged backlog + decision log (the tracker)
- [`../inspiration/honcho.md`](../inspiration/honcho.md), [`../inspiration/gbrain.md`](../inspiration/gbrain.md) — the two adjacent-system analyses
- [`../inspiration/research/`](../inspiration/research/) — the eight deep-research notes + [synthesis](../inspiration/research/README.md)

---

## 0. How this dossier was produced (methodology & provenance)

Rodrigo asked for three things across this session, in order:

1. **"Understand Honcho — why it's good, what it can inspire in Cicada, and its personal-memory use cases."**
   *How it was done:* fetched the live `honcho.dev` site and the `plastic-labs/honcho`
   GitHub README (not from model memory — explicitly re-fetched so the analysis reflects
   the current product), then wrote a structured comparison against Cicada's architecture.
   *Why this way:* Honcho's framing ("memory is reasoning, not retrieval") is the closest
   *philosophical* sibling to Cicada's Sleep cycle, so grounding in primary sources mattered.
   → [`../inspiration/honcho.md`](../inspiration/honcho.md)

2. **"Do the same analysis for gbrain (Garry Tan)."**
   *How it was done:* fetched the `garrytan/gbrain` GitHub README and analyzed it the same way.
   *Finding that justified the effort:* gbrain turned out to be the closest *architectural*
   sibling — independently markdown+git + self-wiring typed graph + overnight enrichment +
   MCP. Two independent teams converging on Cicada's substrate is thesis-grade validation.
   → [`../inspiration/gbrain.md`](../inspiration/gbrain.md)

3. **"Set up a goal with workflows/subagents to research the open questions and document findings."**
   *How it was done:* Rodrigo's pasted notes were triaged into three tracks — **APPLY**
   (buildable now), **RESEARCH** (needs investigation), **DECIDE** (needs Rodrigo's call).
   Four foundational decisions (D1–D4) were put to Rodrigo directly. In parallel, a
   background **multi-agent workflow** spawned **eight subagents**, one per open question,
   each doing its own web research and writing a findings doc, followed by a ninth synthesis
   agent. *Cost/scale of that run:* 9 agents, ~677k tokens, ~5 min wall-clock.
   *Why a workflow:* the eight questions are independent, so fanning them out in parallel
   (rather than researching serially) was the right shape; each agent's findings are
   independently auditable in its own file.
   → [`../inspiration/research/`](../inspiration/research/)

**Confidence note:** web-researched specifics (pricing, library latencies, the existence of
"SkillOpt" by that exact name) are flagged where uncertain in the individual research docs.
Treat the *recommendations* as well-reasoned defaults, not settled fact — each is reversible
because (per the strongest cross-cutting finding) markdown+git remains the immutable source
of truth and everything else is a derived or additive layer.

---

## 1. The one finding that anchors everything

**markdown+git is the moat; everything else is derived or layered on top.**

Five of the eight research notes independently reached this conclusion. Cicada's
transparency, provenance (git-blame), portability, and Obsidian-compatibility live in the
*files*. Vector indexes, peer perspectives, per-context facets, shadow entities, and the
ask endpoint are all **derived or additive** — none should ever threaten the canonical
substrate. Practical consequence: **every decision below is reversible.** We can swap the
vector index, soften the entity gate, or turn peers on later, all without a data migration,
because the source of truth never moves.

Second anchor: **"consolidate then reason" is externally validated, twice.** Honcho's async
"deriver" and Microsoft's nightly "SkillOpt-Sleep" are two independent reinventions of
Cicada's Awake/Sleep split. And Cicada's two *defensible* differentiators —
**git-blame transparency** and **temporal decay as an active signal** — are things *neither*
Honcho nor gbrain has. The strategy throughout: borrow their best interface ideas, but make
each one land differently by running it through Cicada's decay + provenance machinery.

---

## 2. Findings by theme (what we asked, what we found, why it matters)

Each subsection: *the question → how it was researched → what was found → the recommendation
→ why.* Full detail in the linked research note.

### 2.1 Storage: where memory lives — D1
*Question:* keep markdown+git+LEANN, move to Postgres+pgvector (like Honcho/gbrain), or hybrid?
*Researched via:* [r3-postgres-pgvector.md](../inspiration/research/r3-postgres-pgvector.md) —
web research on current pgvector + LEANN state, sized against Cicada's ~1,882 entities.

**Found:** the question splits cleanly into two *independent* sub-decisions:
- *Source of truth* — settled: **markdown+git** (that's where provenance/portability live).
- *What powers retrieval* — a **derived, disposable index**, rebuilt by the Sleep cycle.

The pointed result: **LEANN is now the wrong tool for Cicada.** LEANN's whole value is a 97%
storage saving achieved by recomputing embeddings at query time — paying ~2s latency to save
disk. At Cicada's scale the raw embeddings are single-digit MB, so the storage win is
irrelevant and the latency tax *actively fights* the D3 ask endpoint and live graph filtering.
gbrain (the most architecturally convergent system) already does markdown-canonical +
DB-derived hybrid (vector+BM25) retrieval, reporting **+31.4 P@5 over vector-only**.

**Recommendation (research default):** replace LEANN with a Sleep-rebuilt stored-embedding
index; **sqlite-vec** as the default (embedded, no daemon, ships in the app bundle — the
right infra profile for a single-user macOS app), **pgvector documented as the upgrade path**.
Because the index is derived, sqlite-vec → pgvector later is a *rebuild, not a migration*.

**Rodrigo's call (2026-06-17):** willing to **go straight to Postgres+pgvector** and
implement the derived index there directly, *then* build the ask endpoint.
*The honest tradeoff to weigh:* pgvector gives you (a) Honcho/gbrain-grade true hybrid search
(real BM25 via `pg_textsearch` + reciprocal-rank fusion), (b) richer metadata filtering, and
(c) thesis alignment + a clean multi-user/server future — at the cost of running a Postgres
daemon inside what is otherwise a zero-infra, drag-to-Applications single-user app. sqlite-vec
avoids the daemon but tops out at a weaker hybrid story. **Either is defensible and the choice
is low-stakes** precisely because the index is derived. If we go Postgres, the install flow
(`install.sh` / launchd) must own Postgres lifecycle so the user never touches it — keep the
"user never starts the backend" promise intact.

### 2.2 Entity model philosophy — D2
*Question (Rodrigo's, sharp):* "Am I constraining consolidation by establishing entities? Is
the promotion gate worth it — maybe delete it? Is Honcho's belief / observer-observed
philosophy better? I hold different beliefs about myself by context (engineer-self vs
family-self vs life-philosophy) — should one entity have dimensions per context?"
*Researched via:* [r7-entity-promotion.md](../inspiration/research/r7-entity-promotion.md) +
[r4-contextual-entities.md](../inspiration/research/r4-contextual-entities.md).

**Found — the key reframe:** the **promotion gate** and the **closed 8-type taxonomy** are
two *bundled but independent* decisions, and conflating them is what makes the model feel
constraining. Specifically:
- The hard "no node until 2nd mention" gate is *more aggressive than the hippocampus it's
  modeled on* (the brain forms a labile one-shot trace, then lets it decay). It also starves
  cross-linking — **you cannot draw an edge to a node that doesn't exist yet** — and leaves
  dropped mentions invisible, so recall is unmeasurable.
- Context-dependent identity (your engineer/family/philosophy insight) is best modeled as
  **one canonical entity + optional named "facets"** (lenses), each with its *own* decay,
  confidence, and provenance. Separate per-context graphs were considered and **rejected** —
  they fragment cross-domain linking, which is the very thing you want more of.

**Recommendation:** *soften and layer, don't rip out* — a coordinated set of additive changes
that keep the clean colored-node + git-provenance story:
1. **Shadow/candidate entities:** materialize a weak, low-confidence `type: unresolved` stub
   on first substantive mention; let existing decay prune it if unreinforced. Same
   anti-pollution outcome, but now measurable, linkable, and more biologically faithful.
2. **Keep the 8 types as a colored default but make them extensible** (a `concept`/`unresolved`
   catch-all so Sleep never force-fits a mention into a wrong type).
3. **Promote the user self-model to a first-class faceted entity** with per-facet decay — the
   home for engineer/family/philosophy lenses and the upgraded `skill`/theory-of-mind layer.
4. **Put abstract cross-linking in cluster/tag nodes + edge enrichment**, not the type system.

*Why:* this directly answers "is promotion worth it" with **"yes, but soften it"** — you keep
the precision that prevents graph pollution while removing the parts that block measurement
and cross-linking. It is also the most thesis-friendly answer: every change is a
*decay-aware extension* no adjacent system has.

### 2.3 Retrieval interface — D3 (DECIDED = BOTH)
*Question:* Honcho-style natural-language "ask the memory" vs. the agent reading files directly?
*Rodrigo's call:* **both.**
*Researched via:* [r1-honcho-philosophy.md](../inspiration/research/r1-honcho-philosophy.md).

**Found:** the research calls this the **single highest-value, lowest-cost idea to steal — and
Cicada's version is strictly better than Honcho's.** Honcho's Dialectic API answers
natural-language questions *about* a peer from a reasoned model, but the reasoning is opaque
(it lives in vectors). Cicada can ship a synthesized answer that **cites `git blame` lines,
shows a confidence score, links the entity pages it used, and explicitly admits gaps** — a
dialectic interface that is *also auditable*. Honcho has the reasoning but not the
transparency; gbrain has the graph but a weaker ask. **Auditable synthesis is genuinely
thesis-novel.**

**Recommendation:** build `ask_memory` as the flagship feature — an answer over
markdown+graph+derived-index that **always returns provenance + confidence + explicit gap
analysis** (this folds in the "I don't know" / gap-analysis note, backlog A5). Keep direct
file traversal alongside. Add a `mode="bridges"` analogical retrieval mode later (see §2.8).
It depends on the D1 derived index, so **D1 and D3 are sequenced together.**

### 2.4 Self-improving skills (SkillOpt) — R2
*Question:* integrate something like Microsoft's "SkillOpt" so an agent gets smarter via better
skill/entity rewrites, noting what failed before and why.
*Researched via:* [r2-skillopt.md](../inspiration/research/r2-skillopt.md) (with an honesty
flag on whether "SkillOpt" exists under that exact name — see the note).

**Found:** treat `skill.md` as a *trainable artifact behind a strict validation gate*. The
cautionary result: **"library drift" — ungoverned self-improving skills go net-negative** as
the agent rewrites itself into incoherence. So adopt the **governance pattern, not the
optimizer**: a git-versioned **failure ledger** (what was tried, why it failed) plus
**bounded, gated rewrites** (human-approval-by-default).

**Recommendation:** add a `## Failures` section to entity/skill pages and a
`sleep/skill_revision` trigger that proposes bounded rewrites the user approves. This is
independent of the storage/retrieval spine — schedule it by appetite. *Why it's a good fit:*
it rides Cicada's existing git-provenance and nudge-approval machinery; the failure ledger is
just another structured, decay-aware section.

### 2.5 Cost of reconsolidation — R5 ("how do I finance this")
*Question (Rodrigo's):* help me figure out how I'll finance re-consolidating memory.
*Researched via:* [r5-reconsolidation-cost.md](../inspiration/research/r5-reconsolidation-cost.md)
— web-researched current model pricing, modeled against the corpus.

**Found:** **cost is not the constraint.** A full reconsolidation pass is ~**$1–4 on a cheap
tier** / ~**$10–20 on a quality tier** at current scale. The real constraints are graph-size
scaling and merge quality, not dollars.

**Recommendation:** run **incremental cheap-tier reconsolidation nightly**, and route only the
hard cases (disambiguation, conflict resolution) to Sonnet/Opus. This pairs naturally with the
**contributors/audit** idea (§3.3) — you record which model did which write, so the cheap/quality
routing is visible and auditable.

### 2.6 Sync connectors & the "feed" — R6
*Question (Rodrigo's):* a bookworm "feed" page that syncs whatever's syncable — bookmarks first,
then Notes app, Spotify, Substack/read-later — turning saved media into referenceable entities.
*Researched via:* [r6-sync-connectors.md](../inspiration/research/r6-sync-connectors.md).

**Found — the clean architectural insight:** build every connector as a dumb **Awake-phase
episode emitter.** A connector's only job is to drop episodes into the inbox; the existing
Sleep pipeline then absorbs them with **zero new consolidation code.** That keeps connectors
trivial and source-agnostic (exactly Cicada's existing design principle).

**Recommendation:** ship **keyless Netscape-HTML bookmarks + RSS** for the MVP (no auth, reuses
the upload UI), and **defer auth-heavy Notes/Spotify/Readwise** as labeled post-MVP. This
delivers Rodrigo's "feed" demo fast and safely.

### 2.7 Peers & multi-bank — D4
*Question (Rodrigo's):* peer entities (robots, agents, humans as equals that collaborate);
memory of agents with raw traces; a second agent adding an *opinion* so two versions of the
same memory live side by side (opinion / observer-observed); and several memory banks / "memory
projects" for re-consolidating with another model or parallel testing.
*Researched via:* [r8-peer-model.md](../inspiration/research/r8-peer-model.md).

**Found:** the *full* Honcho `(observer, observed)` network is **not worth building for a
single user** — it's N×-cost for N≈1, and the multi-agent-systems literature's own
"epistemic drift" warnings make it mostly downside today. **But** there's one cheap,
high-value slice: an explicit **opinion-vs-observed split** — keep `entities/` as asserted
facts, and treat an agent's abductive beliefs/self-model as a *separable, faster-decaying*
opinion layer (the same self-model upgrade D2 already wants).

**Recommendation:** adopt the opinion-vs-observed slice now (a `basis_type`
deductive/inductive/abductive field borrowed from Honcho, with opinions decaying faster than
facts). **Design — but don't build —** the full `peers/` + `perspectives/<observer>/` layout,
with an `observer` axis that **defaults to `self`** everywhere (schema, ask endpoint, d3), so
turning peers on later adds one field with no migration. Gate the real peer build on a concrete
second observer (a robot, a second agent, a teammate, or multi-user mode). Ship the
**"disagreement halo" + peer-filter** as a thesis *figure/mockup*.

### 2.8 Bridge / analogy retrieval — R4 + R7 (lowest confidence)
*Rodrigo's wish:* "draw abstract relationships between things that are not specially related"
(e.g. relate a song to an unrelated entity by personal relevance).
**Found:** this is a **retrieval-time mode** on the ask endpoint, *not* a storage change —
`ask_memory(mode="bridges")` fed by Sleep-staged candidate links the user approves.
**Recommendation:** build it *last*, after facets exist, and validate with a small experiment
before making any thesis claim — cross-connection quality on a personal-scale graph is
genuinely unproven.

---

## 3. Rodrigo's ideas — preserved, credited, and mapped

These are **Rodrigo's own ideas** from the pasted notes. They are good and several are now
load-bearing in the plan. Captured here so none is lost; each maps to where it lives in the
plan.

### 3.1 The ingestion page with the bookworm mascot *(UX — Rodrigo emphasized this)*
A dedicated **media-ingestion page that shows the same animated bookworm mascot** as the menu
bar — the worm "digesting" what you feed it. This is the front door for feeding *different
types of media* into memory (bookmarks, articles, papers, songs, recipes, ideas…). It makes
ingestion feel alive and gives the consolidation process a face.
→ *Plan home:* pairs with §2.6 connectors. The connectors fill the feed; this page is how a
human watches/curates it. Reuses the existing `deriveBookwormState` sprite state machine
(awake/digesting/curious…). **Backlog A3, elevated to a headline UX item.**

### 3.2 Many media types as first-class, referenceable entities
Websites/bookmarks, Substack articles, blogposts, research papers, ideas, projects, recipes,
**songs** — saved so much that they deserve to be entities. Each carries a **summary** *and*
a **personal-relevance** note ("what this is, and why it's relevant to *me*"). The payoff
Rodrigo named: being able to **reference a song on another entity's wiki page** — true
cross-media wikilinks.
→ *Plan home:* §2.2 (extensible types — these slot in as new colored defaults, gated behind
the soften-don't-kill taxonomy work) + §2.6 (connectors emit them). The "personal relevance"
field is exactly the kind of per-entity, decay-aware signal Cicada is built for.

### 3.3 Contributors / audit built into the architecture *(Rodrigo emphasized this)*
A **"contributors" view**: which **LLM model** wrote which contribution to memory — and the
ability to **audit every agent/model** that has written, and even **score some models better
than others.** Rodrigo wants this *built into the framework's architecture*, not bolted on.
→ *Plan home:* record the model id (and trigger) in **Sleep commit trailers** so git-blame
already carries it; surface a contributors view + per-node attribution. This composes
beautifully with §2.5 (cheap/quality model routing becomes visible) and §2.7 (opinion layer
— *whose* opinion, written by *which* model). **This is a genuinely distinctive architectural
choice** — a memory system that is honest about which model authored each belief. Backlog A2,
elevated. *(Also unlocks model-quality scoring as a future evaluation axis.)*

### 3.4 A filterable view with a relevance metric
A view to **filter all articles/bookmarks/songs/etc. by a relevance metric** — so the feed is
navigable, not a pile.
→ *Plan home:* a derived "relevance" score (confidence × recency/decay × personal-relevance)
surfaced as a sort/filter in the companion app, over the new media entities (§3.2).

### 3.5 Problem log: solved + open-ended *(Rodrigo's idea)*
Save **"we solved this problem by doing X"**, and track **open-ended problems** — "we discussed
this; how did it end up going?" — so unresolved threads resurface.
→ *Plan home:* structured **sections** under `project`/`concept` entities (`## Solved`,
`## Open Questions`). Open problems are a natural fit for **decay-driven nudges** ("you never
resolved X"). Backlog G4.

### 3.6 "Project improvements" sections + an entity-type audit interface *(Rodrigo's idea)*
A place to capture **things discussed to improve a given project** — likely a **section under
`project` entities** — plus an **interface to audit which entity types exist and structure
info per type** (a section grammar per type).
→ *Plan home:* §2.2 (the section grammar already owned by `entity_body.py` in v2). The
type-audit interface is meta-tooling over the taxonomy — a strong companion-app feature.
Backlog G5/G6.

### 3.7 Skills as "how Rodrigo likes things done" *(Rodrigo's idea)*
Store procedural preferences — e.g. *"Rodrigo usually starts a FastAPI project this way and
structures the repo this other way."*
→ *Plan home:* the upgraded faceted self-model (§2.2 #3) + the governed rewrite loop (§2.4).
This *is* Cicada's theory-of-mind layer, told in Rodrigo's own words.

### 3.8 Reduce Rodrigo-node centrality *(Rodrigo's observation)*
The "Rodrigo" node is over-central; the graph wants **more intermediate nodes.**
→ *Plan home:* §2.2 #4 (cluster/tag hub nodes) + the v2 hubs work already in
[`../V2-ROADMAP.md`](../V2-ROADMAP.md). Intermediate hubs are both a viz fix *and* a
cross-linking fix.

### 3.9 Per-commit diff view of node history *(Rodrigo's idea)*
An expanded per-commit view showing **what was added vs removed** in a node over time.
→ *Plan home:* extends the existing `/entities/{id}/history` with a git-diff render. Pairs
with §3.3 (you see *what* changed *and which model* changed it). Backlog A1.

### 3.10 Multiple memory banks / "memory projects" *(Rodrigo's idea)*
Several versioned memory banks — to re-consolidate past conversations with another model, or
run parallel ongoing banks (mainly for testing now).
→ *Plan home:* §2.7. Low-cost given §2.5 (reconsolidation is cheap). Design the substrate so a
"bank" is just a separate memory directory/git repo the API can point at; defer multi-bank UI.

---

## 4. Consolidated improvement catalog

Everything we can do, grouped. IDs cross-reference [`memory-evolution.md`](memory-evolution.md).

**Storage & retrieval spine (do first, coupled):**
- D1 — derived embedding index replacing LEANN (Postgres+pgvector per Rodrigo, or sqlite-vec). §2.1
- D3 — `ask_memory` flagship: synthesized answer + git-blame citations + confidence + gap analysis (A5). §2.3

**Entity model (additive softenings):**
- Shadow/candidate entities + decay pruning; extensible types. §2.2 / R7
- Faceted self-model (engineer/family/philosophy lenses, per-facet decay). §2.2 / R4
- Cluster/tag hub nodes for cross-linking + reduced Rodrigo-centrality. §2.2#4 / §3.8

**Media, feed & UX (Rodrigo-led):**
- Ingestion page with animated bookworm mascot. §3.1 / A3
- New media entity types (bookmark, article, paper, song, recipe, idea, project-note). §3.2 / G2
- Connectors as Awake episode emitters: bookmarks-HTML + RSS first. §2.6 / R6
- Relevance-metric filter view across media. §3.4
- Cross-media wikilinks (reference a song on any entity page). §3.2

**Provenance, audit & governance (distinctive):**
- Contributors view: per-write model attribution via commit trailers + scoring. §3.3 / A2
- Per-commit diff view of node history. §3.9 / A1
- Failure ledger + bounded gated skill/entity rewrites. §2.4 / R2

**Knowledge structure (sections under types):**
- Problem log: `## Solved` + `## Open Questions` (open → decay nudges). §3.5 / G4
- Project-improvements sections + entity-type audit interface. §3.6 / G5–G6

**Peers & banks (design now, build on a trigger):**
- Opinion-vs-observed split (`basis_type`, faster-decaying opinion layer). §2.7
- `observer`-defaults-to-`self` substrate; full peers + disagreement-halo as designed figure. §2.7 / R8
- Multiple memory banks / "memory projects". §3.10 / G1

**Reconsolidation policy:**
- Nightly incremental cheap-tier; route conflicts to Sonnet/Opus; cost is not the constraint. §2.5 / R5

**Experimental (last, lowest confidence):**
- `ask_memory(mode="bridges")` analogical/cross-facet retrieval. §2.8

---

## 5. Recommended sequencing

From the research synthesis, adjusted for Rodrigo's Postgres lean and UX emphasis.

0. **Instrument first (cheap, de-risks the spine):** measure real LEANN size/latency
   (`du -sh memory/leann` + a timed query) and add token accounting to `run_table3`.
   Converts modeled numbers to measured ones before any code.
1. **D1 — derived index.** Stand up Postgres+pgvector (or sqlite-vec) as a Sleep-rebuilt
   derived index; retire LEANN. Install flow must own the Postgres daemon if we go that route.
2. **D3 — `ask_memory` flagship** over the new index (+ gap analysis A5). Coupled to step 1.
3. **D2 — self-model facets, then shadow entities + extensible types.**
4. **Media + UX:** bookmark/RSS connectors → ingestion page with bookworm → media entity
   types → relevance filter. (Parallelizable; great visible demo value.)
5. **Provenance/audit:** contributors view (commit-trailer model attribution) + per-commit
   diff view. (Composes with everything; high distinctiveness.)
6. **Governance:** failure ledger + gated rewrites (R2). By appetite.
7. **Peers/banks:** opinion-vs-observed slice + `observer=self` substrate; full peers + banks
   as designed figures, gated on a real second observer.
8. **Bridge/analogy retrieval mode** — last, validate experimentally.

---

## 6. Open decisions still on the table

- **D1 sub-call:** Postgres+pgvector (Rodrigo's lean — richer hybrid search, infra cost, thesis
  alignment) vs sqlite-vec (zero-daemon bundle). Reversible either way. *Resolve before step 1.*
- **D2:** not formally committed — the soften-don't-kill package is the recommendation; needs
  Rodrigo's yes before touching the entity model.
- **D3 read-path budget:** how much pure synthesis vs guided-traversal-with-gloss, and the p95
  latency budget / whether a cached-representation layer (Honcho's static-snapshot trick) is needed.
- **D4 trigger:** what concrete "second observer" justifies building full peers later.
- **Contributors scoring:** how/whether to *rank* models that write to memory (Rodrigo's idea) —
  needs a scoring rubric; worth a small design before building.
