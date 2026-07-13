# Tiered Cognitive Memory (Cicada-Cortex)

## Philosophy

A memory system for an agent should mirror the architecture that already works in
the only general intelligence we have: the brain stores **different kinds of memory
in different structures**, retrieves them by **different access laws**, and moves
information *between* stores via an offline consolidation process. Cicada's existing
Awake/Sleep split already gestures at this; this design makes it the organizing
principle of the knowledge model rather than a metaphor bolted onto a flat entity
graph.

Three claims drive the design:

1. **One unit type cannot serve three jobs.** Raw conversation (high-fidelity, time-
   stamped, never edited — *episodic*), distilled stable knowledge about the world
   (entities/concepts/beliefs — *semantic*), and "how Rodrigo likes things done"
   (triggerable rules and reusable procedures — *procedural*) have genuinely
   different write patterns, decay laws, schemas, and retrieval triggers. Forcing
   all three into "one markdown page per entity with a `type:` field" is the root
   cause of the current model's weaknesses (skills modeled as concept-shaped pages;
   preferences buried in prose; episodes only reachable through entities).

2. **The promotion gate is the wrong abstraction; consolidation should be a
   continuous reflection process, not a 2nd-mention rule.** Instead of a hard
   threshold deciding *whether* a mention becomes an entity, a **reflection pass**
   decides *what to write up which tier* based on importance and surprisal. A single
   substantive conversation can mint a semantic entity immediately; a fleeting
   mention stays episodic-only and is reachable by vector search without polluting
   the graph. No information is ever discarded — it just lives at the tier that fits
   it.

3. **Context is a tag, not a fork.** Rodrigo's "engineer-self vs family-self" is
   handled not by cloning entities per context but by attaching `context:` to the
   atomic **beliefs** inside an entity and letting retrieval filter/rank by the
   active context. One `Rodrigo` page, many context-scoped beliefs — the
   Generative-Agents retrieval score (importance × recency × relevance) does the
   rest, surfacing the engineer-self beliefs in an engineering session and the
   family-self beliefs in a personal one, while still allowing abstract cross-context
   links to be drawn at reflection time.

The substrate is unchanged: **markdown + git is the source of truth; sqlite-vec is a
derived, rebuildable index.** The three tiers are three *directories* and three
*index `kind`s* — no new infrastructure, no database, fully Obsidian-compatible.

---

## Data model

### The three tiers as directories

```
memory/
├── episodes/        ← TIER 1: EPISODIC  (raw, immutable, append-only)   [exists today]
├── entities/        ← TIER 2: SEMANTIC  (entities + atomic beliefs)     [exists today, augmented]
├── procedures/      ← TIER 3: PROCEDURAL (skills + preferences)         [NEW dir, drains skill-type]
├── reflections/     ← consolidation artifacts: cross-tier links + cluster summaries [NEW]
├── graph_edges.yaml ← typed edges across all tiers                      [exists today]
└── leann/ → vector_index.db  ← derived sqlite-vec, now 5 `kind`s        [exists today]
```

The closed 8-type taxonomy is **collapsed**, not extended:

- `person | project | company | concept | tool | location | deadline` stay as the
  **semantic-tier `type:`** (they are genuinely "things in the world"). `deadline`
  becomes a `temporal:` facet on any entity rather than its own type when it's an
  attribute, but is kept as a type for standalone commitments — backward-compatible.
- `skill` **leaves the semantic tier entirely** and becomes the procedural tier.

This is the "schema sweet-spot": ~7 world-types for nouns, plus two procedural kinds
(`preference`, `procedure`), plus a first-class **belief** sub-unit inside semantic
pages. We get structure without the degenerate `RELATES_TO` sprawl of schema-free.

---

### Tier 1 — Episodic (unchanged structure, new role)

Already exists exactly as needed: `episodes/ep_YYYY-MM-DD_NNN.md` with frontmatter
(`id`, `timestamp`, `source`, `title`, `processed`, `content_hash`) and raw
conversation body. **The only addition is an `importance:` field**, scored during
Sleep (not at capture — keeps Awake cheap), 1–10, used by retrieval.

```yaml
---
id: ep_2026-06-10_003
timestamp: '2026-06-10T18:10:41Z'
source: claude
title: Decided to switch the thesis DB from Postgres to SQLite
processed: true
content_hash: 818c859de9d4
importance: 8          # NEW — surprisal/decision-density scored at Sleep
---
user: I'm dropping Postgres for the memory store, SQLite is enough...
```

Episodes are **never edited and never decay** (they are the audit trail; git already
versions them, but their value is permanence). They are chunked and embedded as the
`episodes` index kind (already implemented in `vector_index.index_episodes`).

---

### Tier 2 — Semantic (entity page = container of atomic beliefs)

The entity page stays one markdown file per world-thing, but its body is restructured
from free prose into a **frontmatter card + a `## Beliefs` block of atomic, individually
addressable, individually time-stamped claims.** This is the Honcho/Graphiti insight:
*the belief/fact, not the entity, is the temporal and provenance unit.* The page is the
human-readable peer-card; the beliefs are the queryable substrate.

`entities/rodrigo.md`:

```yaml
---
name: Rodrigo
type: person
status: active
confidence: 0.95
created: '2024-10-28'
last_referenced: '2026-06-16'
decay_rate: 0.02
source_episodes: [ep_2024-10-28_001, ep_2026-06-16_002]
tags: [self, capstone, robotics]
related: [Cicada, IE University, capstone-thesis]
contexts: [engineering, family, philosophy]   # NEW: declared facets present below
version: 7
---

Rodrigo — the user. Final-year BSc student; builds Cicada. Multi-context self;
see per-context beliefs below.

## Beliefs
- id: blf_001                                  # stable id → addressable, citable, embeddable
  claim: "Prefers SQLite over Postgres for on-device single-user storage"
  context: engineering
  epistemic: explicit          # explicit | deductive | inductive | abductive
  source_trust: user_stated    # user_stated | agent_extracted | agent_reflected | external
  confidence: 0.9
  valid_from: '2026-06-10'
  valid_to: null               # null = currently held; date = superseded (bi-temporal)
  observed_at: '2026-06-10'    # when true in the world
  recorded_at: '2026-06-11'    # when Sleep learned it
  superseded_by: null
  source_episodes: [ep_2026-06-10_003]

- id: blf_000
  claim: "Uses Postgres for the thesis memory store"
  context: engineering
  epistemic: explicit
  source_trust: user_stated
  confidence: 0.9
  valid_from: '2026-03-01'
  valid_to: '2026-06-10'        # CLOSED — superseded, but still queryable as history
  superseded_by: blf_001
  source_episodes: [ep_2026-03-01_002]

- id: blf_014
  claim: "Optimizes for clean, minimal infrastructure; dislikes heavyweight deps"
  context: philosophy           # cross-cuts engineering — a candidate cross-link
  epistemic: inductive          # Sleep generalized this from several episodes
  source_trust: agent_reflected
  confidence: 0.7
  valid_from: '2026-02-01'
  valid_to: null
  source_episodes: [ep_2026-01-15_001, ep_2026-04-02_003]
```

**Edges** stay in `graph_edges.yaml` (already exists), gaining an optional
`context:` and `belief:` field so a relationship can be scoped:

```yaml
- source: rodrigo
  target: cicada
  label: builds
  context: engineering
  belief: blf_022        # optional: which belief grounds this edge
```

**Why YAML-list beliefs inside the page rather than a separate beliefs/ tier:**
keeps the page human-readable and Obsidian-renderable, keeps git diffs legible
(a superseded belief shows as a one-line `valid_to` change), and lets the agent
read one file to get the whole picture of an entity. The beliefs are *also* indexed
individually (below), so retrieval precision is per-belief, not per-page.

---

### Tier 3 — Procedural (skills + preferences as first-class files)

`procedures/` holds two kinds, distinguished by `kind:` frontmatter, reflecting the
research finding that **skills (retrieved on task recognition) and preferences
(always-injected behavioral constraints) are different sub-problems**.

`procedures/pref_fastapi-router-layout.md`:

```yaml
---
kind: preference                 # preference | procedure
id: pref_017
scope: [coding, fastapi, python] # tags used to gate always-injection
trigger: "Working in a FastAPI repo / designing API structure"
status: active                   # active | superseded
confidence: 0.85
source_trust: user_stated
created: '2026-03-12'
last_referenced: '2026-06-01'
contradicts: null                # → id of preference this overrides
superseded_by: null
source_episodes: [ep_2026-03-12_004, ep_2026-05-20_001]
---
**Rule:** Split FastAPI routers by domain — one router module per resource
(`routers/graph.py`, `routers/nudges.py`), wired in `main.py`. Avoid a monolithic
`api.py`.

**Confidence note:** stated twice, never contradicted.
```

`procedures/proc_rebuild-leann-index.md` (a `kind: procedure` — reusable steps):

```yaml
---
kind: procedure
id: proc_004
trigger: "Need to rebuild the vector index after editing entities"
scope: [cicada, ops]
status: active
verified_in: [ep_2026-04-16_001]   # episodes where this procedure actually worked
...
---
## Steps
1. `python -m benchmarks.rebuild_leann`
2. Verify `memory/leann/episodes.*` non-empty
3. Re-run `/ask` smoke test
```

Preferences carry `contradicts:`/`superseded_by:` so the **Sleep contradiction pass**
can retire a stale preference (set `status: superseded`, point `superseded_by`) when a
new conflicting one appears — git keeps the audit trail. This directly fixes the
"append-only preferences become contradictory" failure mode.

---

### How the sqlite-vec index changes

The indexer already builds per-`kind` `vec_{kind}` + `meta_{kind}` tables. We go from
2 kinds (`entities`, `episodes`, plus `pending`) to **5 retrieval kinds**, all in the
same `vector_index.db`, all rebuilt by Sleep from markdown:

| kind | unit embedded | metadata keys | decay law |
|------|---------------|---------------|-----------|
| `episodes` | episode chunk | `episode_id, source, importance, timestamp` | none (permanent) |
| `beliefs` | one belief `claim` (+context) | `entity_id, belief_id, context, epistemic, source_trust, confidence, valid_to` | per-belief |
| `entities` | entity card summary | `entity_id, type, status, confidence` | per-entity |
| `preferences` | preference rule text | `pref_id, scope[], status` | slow (user_stated) |
| `procedures` | procedure trigger+steps | `proc_id, scope[], status` | none until contradicted |

The new `beliefs` kind is the precision win: `/ask` retrieves *individual claims*
(filterable by `context` and `valid_to IS NULL`) instead of whole pages. Closed
beliefs (`valid_to` set) are still embedded but down-ranked unless the query is
explicitly historical.

`vector_index.py` gains `index_beliefs()`, `index_preferences()`,
`index_procedures()` mirroring the existing `index_entities()` / `index_episodes()`;
each parses the YAML belief list / procedure frontmatter and writes one row per unit.
Search adds an optional `context` and `active_only` filter applied to the
`meta_{kind}` row after KNN (sqlite-vec returns rowids; we already join to
`meta_{kind}`).

---

### How Sleep writes it (revised 5-stage + reflection)

The existing 5 stages are retargeted; the promotion gate is replaced by an importance/
surprisal scorer and a reflection pass:

1. **Extraction** — LLM extracts atomic beliefs (claim + context + epistemic +
   source_trust) and candidate procedures/preferences from unprocessed episodes.
   Also scores each episode's `importance`.
2. **Resolution** — match beliefs/entities against the graph (fuzzy + vector +
   LLM disambiguation, as today). Beliefs attach to their entity page; new world-
   things mint an entity page **immediately if importance/substance warrants**
   (no 2nd-mention wait) — otherwise the belief stays attached but the entity stays
   `status: provisional` and lives in the `pending` index.
3. **Contradiction & temporal close** — *replaces* "conflict resolution by overwrite."
   A new belief that conflicts with an open one **closes the old** (`valid_to`,
   `superseded_by`) rather than deleting it. Same pass retires contradicted
   preferences. Per-belief and per-entity decay applied here (trust-weighted:
   `user_stated` decays slow, `agent_reflected` fast).
4. **Reflection (was "pattern detection")** — the cross-tier promotion engine:
   (a) generalize recurring episodic patterns into `inductive` beliefs;
   (b) distill recurring "how Rodrigo does X" into procedures/preferences;
   (c) **draw abstract cross-context links** — when a `philosophy`-context belief
   predicts an `engineering`-context one, write a `reflections/refl_NNN.md` note and
   a `graph_edges.yaml` edge labeled `informs`. This is where Rodrigo's "abstract
   links between not-obviously-related things" lives.
5. **Nudges, clusters & commit** — generate decay/conflict/clarification nudges;
   regenerate `reflections/cluster-*.md` community summaries over dense wikilink
   groups (the GraphRAG win, replaces `hubs/`); commit with the existing
   `Cicada-Author:` trailers and structured per-file lines. Then rebuild the 5 index
   kinds.

### How /ask + MCP retrieve it (Generative-Agents scoring)

`/ask` (and the MCP Bookworm `search`) takes an optional `context` hint (inferred from
the conversation or passed by the client) and runs **tiered retrieval with a unified
score**:

```
score(unit) = w_r·recency(unit) + w_i·importance(unit) + w_s·similarity(query, unit)
              + w_c·context_match(unit.context, active_context)
```

Retrieval order, all merged and re-ranked by the score above:
1. **Preferences** whose `scope` matches the active context → injected as a compact
   always-on block (not similarity-gated): "who is Rodrigo right now."
2. **Beliefs** (`beliefs` kind, `valid_to IS NULL`, context-boosted) → the precise
   claims grounding the answer.
3. **Entities** (page cards) → for relational traversal; LLM follows `related:`/edges.
4. **Procedures** (only if the query is task-shaped) → matched on `trigger`.
5. **Episodes** → raw fallback when semantic tiers are thin (audit + cold-start).

Each citation carries `epistemic`, `source_trust`, `confidence`, and `valid_to`, so
`/ask`'s existing confidence+gap output becomes *honest about why*: a `user_stated
explicit` belief and an `agent_reflected inductive` one are flagged differently to the
calling agent.

---

## Worked examples

### 1. Engineer-self vs family-self (faceted identity)

One `entities/rodrigo.md`, `contexts: [engineering, family, philosophy]`. Beliefs carry
`context:`:

- `blf_001` ("prefers SQLite", context: engineering)
- `blf_031` ("values time with family on weekends, guards Sundays", context: family,
  source_trust: user_stated)
- `blf_014` ("optimizes for minimal infrastructure / minimalism", context: philosophy,
  epistemic: inductive)

In an engineering session, `/ask` with `context=engineering` boosts `blf_001`/`blf_014`
via `context_match`, leaves `blf_031` low-ranked — no context collapse, no cloned page.
In a personal session (`context=family`), `blf_031` surfaces. At reflection, Sleep
notices `blf_014` (philosophy: minimalism) *predicts* `blf_001` (engineering: SQLite)
and writes `reflections/refl_009.md` + an `informs` edge — the abstract cross-link
Rodrigo wants, surfaced when either belief is retrieved.

### 2. A belief that changes over time (Postgres → SQLite)

- Episode `ep_2026-03-01_002` mints `blf_000` ("uses Postgres", valid_from 2026-03-01,
  valid_to null).
- Episode `ep_2026-06-10_003` ("dropping Postgres for SQLite") is extracted in Stage 1.
- Stage 3 contradiction pass sees `blf_new` conflicts with open `blf_000`: it writes
  `blf_001` ("prefers SQLite", valid_from 2026-06-10) and **closes** `blf_000`
  (`valid_to: 2026-06-10`, `superseded_by: blf_001`). The git diff is a clean two-line
  change. `/ask "what DB does Rodrigo use?"` retrieves only `blf_001` (open). `/ask
  "what DB did Rodrigo use in April?"` (historical) retrieves `blf_000` because the
  query's temporal cue lifts the `valid_to`-set down-rank. No hallucinated
  simultaneity, full history preserved at zero extra storage.

### 3. A procedural preference

Two episodes mention splitting FastAPI routers by domain. Stage 4 reflection distills
`procedures/pref_017` (`kind: preference`, scope `[coding, fastapi, python]`, trigger
"working in a FastAPI repo"). Next time an agent opens a FastAPI session, MCP matches
`scope` to the active context and **injects the rule as an always-on block** before the
user even asks — the agent structures routers correctly unprompted. If Rodrigo later
says "actually, one big router is fine for small services," Stage 3 writes a new
preference with `contradicts: pref_017` and sets `pref_017.status: superseded` — the
agent stops applying the old rule, git keeps both.

### 4. A saved media item

A saved article (RSS/media ingestor, already implemented) lands as `entities/<slug>.md`
with `type: concept` today; under this model it stays a semantic page but gains a
`kind: media` marker in frontmatter and **belief rows extracted from its content**
(e.g. `blf_212`: "sqlite-vec gives ANN search with no recompute tax",
`source_trust: external`, context: engineering). The media edge (`about`) wired in
Stage 5.55 stays. So the article is both a citable source page *and* contributes
externally-sourced beliefs that `/ask` can use — flagged `source_trust: external` so
the agent trusts it less than a `user_stated` belief. New media kinds need no schema
change: they are just semantic pages whose beliefs are `external`-trust.

---

## Migration

From the current **1,882 typed entity pages + graph_edges.yaml + episodes** —
incremental, reversible, three waves. All runs in throwaway `/tmp/cicada_bench_*`
workspaces first (the benchmark safety rail), then applied to `memory/`.

**Wave 0 — structural, zero LLM (cheap, mechanical):**
- Create `procedures/` and `reflections/`. **Move the 95 `type: skill` pages** into
  `procedures/`, rewriting frontmatter to `kind: preference|procedure` (a heuristic:
  imperative "prefers/always/never" → preference, step-lists → procedure; ~95 pages,
  one cheap classify call each ≈ **$0.05–0.20 total**).
- Add `importance: 5` default to all 117 episodes (back-scored lazily in Wave 2).
- Add empty `## Beliefs` block + `contexts: [general]` to the 1,787 remaining pages.
- `deadline`/etc. types untouched. Git commit. **Fully backward-compatible** — old
  flat-prose pages still parse; the index still builds.

**Wave 1 — belief extraction (the one real LLM cost):**
- For each of the 1,787 semantic pages, one extraction call turns the existing prose
  body + `## History` into atomic belief rows (claim/context/epistemic/source_trust/
  valid_from from `created`, source_episodes copied down). At ~1.5k in / 0.5k out
  tokens/page on a mini model (~$0.15/1M in, $0.60/1M out): **≈ $0.40–0.80 total** for
  all 1,787 pages. Batchable, idempotent (re-runnable per page), resumable.
- Default context = `general`; the LLM assigns `engineering/family/philosophy` only
  when the prose supports it. No-belief pages keep an empty block (harmless).

**Wave 2 — derived rebuild + reflection (compute, near-zero $):**
- Run `vector_index` rebuild to populate the 3 new index kinds (`beliefs`,
  `preferences`, `procedures`) — embeddings only, no LLM (~minutes of EmbeddingGemma
  on-device).
- Run one reflection-only Sleep pass to back-score episode `importance` and mint the
  first cross-context links + cluster summaries. One full-graph LLM pass, bounded by
  surprisal sampling: **≈ $1–3**.

**Total migration LLM cost ≈ $2–4**, dominated by Wave 1, fully resumable, never
mutates live `memory/` until validated. Rollback = `git revert` (the substrate is git).

---

## Scorecard

- **C1 Agent retrieval quality & usability — 5/5.** Per-belief embedding + tiered
  Generative-Agents scoring + context filtering is a real precision jump over per-page
  retrieval; preferences as always-on block means the agent is correctly primed before
  asking. Traversal via edges/`related:` preserved.
- **C2 Context-dependent identity — 5/5.** `context:` on beliefs + `contexts:` on pages
  + context-boosted retrieval + reflection cross-links is exactly Rodrigo's stated
  intuition, with no entity cloning and explicit abstract-link generation. Weakness:
  context is a flat tag set, not a learned hierarchy — overlapping contexts are
  union-matched, not weighted by semantic distance.
- **C3 Temporal change & contradiction — 5/5.** Bi-temporal belief close
  (`valid_from/valid_to/superseded_by`) makes contradiction mechanical and history
  queryable; trust-weighted decay. Strongest area. Risk: belief-conflict detection
  quality depends on the Stage-3 LLM matcher.
- **C4 Provenance & confidence — 5/5.** Every belief carries `source_episodes`,
  `epistemic`, `source_trust`, `confidence`, plus git/`Cicada-Author`. `/ask`
  surfaces *why* it's certain. Orthogonal trust vs confidence axes implemented.
- **C5 Procedural / preference memory — 5/5.** First-class tier with skill/preference
  split, trigger semantics, always-injection, and contradiction-retirement — ahead of
  mem0/cognee/Letta on Rodrigo's top priority.
- **C6 Implementation cost & migratability — 3.5/5.** Honest weakness: belief
  extraction touches all 1,787 pages and the page-body format changes from free prose
  to a structured belief list — the biggest schema change of any candidate. Mitigated
  by backward-compatible Wave 0 and ~$2–4 total, but it's real work and the belief
  list must be kept clean or pages bloat.
- **C7 Extensibility — 4.5/5.** New knowledge kinds (media, problems, open questions)
  are just semantic pages whose beliefs carry a `source_trust`/`kind` marker, or a new
  procedural `kind:` — no taxonomy edit, no graph sprawl. Slight risk of `kind:`
  proliferation if undisciplined.
- **C8 Simplicity / maintainability — 3/5.** Honest weakness: this is the *most*
  complex candidate — three tiers, five index kinds, bi-temporal beliefs, a reflection
  pass. For a solo dev that's more surface area to maintain than a flat graph. The
  payoff is real but so is the cognitive load; the belief-list-inside-markdown choice
  is the main thing keeping it human-auditable.
- **C9 OVERALL — 4.5/5.** The best-aligned candidate to the mandate ("best agent memory
  system"): it directly maximizes C1–C5 (the criteria that matter for an agent that
  must write, retrieve, reason, and *trust*), at a deliberate, accepted cost in C6/C8
  complexity.
