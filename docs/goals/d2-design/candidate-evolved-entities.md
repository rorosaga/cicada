# EVOLVED-CICADA

A conservative, incremental redesign of Cicada's knowledge model that keeps every existing
markdown entity page, every git commit, and the sqlite-vec retrieval index exactly where they
are — and layers four additions on top: (1) a first-class **claim/belief** layer with
provenance, confidence, source-trust, and bi-temporal validity; (2) per-context **facets** on
entities; (3) **shadow/candidate** entities that replace the hard 2nd-mention promotion gate
with a continuous activation score; and (4) **soft (open) types** that drop the closed taxonomy
to a small *core* plus an extensible long tail. Nothing is rewritten; everything is added in a
way that legacy pages keep working untouched.

---

## Philosophy

The current model has one structural lie baked in: **an entity page is a single flat assertion
of "what is true about X."** That breaks in four ways Rodrigo actually hits.

1. **A page averages contradictory beliefs into mush.** "We use Postgres" and "we switched to
   SQLite" can't both live in a body paragraph without one silently overwriting the other and
   the older one being lost as a retrievable, dated claim. Git *has* the history, but the
   *retrieval substrate* (the body text and its embedding) only sees the latest smear.

2. **A page collapses contexts** (boyd's "context collapse"). The `Rodrigo` page that merges
   engineer-self, family-self, and life-philosophy-self produces an embedding that is the
   centroid of three distinct people and retrieves well for none of them.

3. **The promotion gate is a cliff.** A mention is either a full entity page or an invisible
   JSONL row. There is no smooth ramp, so a substantively-discussed-once topic and a
   mentioned-in-passing-once topic are treated identically (both sub-threshold), and the "2nd
   separate conversation" rule is an arbitrary discontinuity that the research (ACT-R activation,
   Generative Agents recency×importance×similarity) says should be a smooth score.

4. **The closed 8-type set fragments and mislabels.** `easy_kropki`, `manager()-dict()`,
   `multiprocessing-queue` are all crammed into `concept`/`tool`; a saved YouTube video, an
   open question, and a coding-style preference have no honest home.

The evolved philosophy: **the entity page stays as the human-readable, git-versioned, embeddable
"current canonical card" for an entity, but the atomic unit of *truth* becomes the claim.** A
claim is a self-contained, dated, sourced, context-scoped statement. The page *body* is now a
**generated peer-card** — a rendering of that entity's currently-valid claims. This is the Honcho
conclusions-DAG idea and the Graphiti facts-are-the-temporal-unit idea, fused onto markdown+git
with **zero new infrastructure**: claims live in the same file, in a fenced block, and the
existing sqlite-vec index gains one new kind (`claims`) alongside `entities`/`episodes`/`pending`.

Design commitments (and what they cost):

- **Append-only beliefs, resolve-at-read** (Mem0 2026 reversal). Sleep never destroys a claim; it
  *invalidates* it by stamping `valid_to`. Contradictions are preserved and visible.
- **Source-trust ⊥ confidence** (epistemics research). A user-stated fact decays slowly even if
  uncertain; an agent-inferred generalization decays fast even if confident.
- **Facets, not separate graphs.** One `Rodrigo` page, multiple `## facet:` sub-sections, each
  separately embeddable. Cheaper than per-context graphs, and cross-facet links are just edges.
- **Activation replaces the gate.** Candidates carry a continuous `activation` float; promotion is
  `activation ≥ θ`, not "mention #2." The hard rule becomes a tunable threshold (ablatable in
  Table 2).
- **Core types + open tail.** 5 core types are validated; anything else is a free-text `type:`
  string that the index treats as an opaque tag. No enum gate rejects new kinds.

---

## Data model

### File layout (what changes, what doesn't)

```
memory/
├── entities/            ← UNCHANGED location; pages gain claim-block + facets (both optional)
│   ├── anodos-labs.md
│   └── rodrigo.md
├── episodes/            ← UNCHANGED
├── candidates/          ← NEW: shadow entities as markdown stubs (replaces opaque pending JSONL)
│   └── gaka-chu-research.md
├── claims/              ← OPTIONAL spillover dir for orphan claims not tied to one entity
│   └── clm_2026-04-10_017.md
├── graph_edges.yaml     ← UNCHANGED schema; edges gain OPTIONAL context/valid_to fields
├── leann/  (→ vector_index.db)
│   ├── vector_index.db  ← sqlite-vec; gains a `claims` vec0 table + facet rows in `entities`
│   └── pending_entities.jsonl  ← retained for back-compat; candidates/ is the new front door
└── nudges/, clarifications/, hubs/, sources/   ← UNCHANGED
```

The two load-bearing rules: **(a)** an unmodified legacy page (no claim block, no facets) is a
valid evolved page — its body *is* its single implicit claim, `source_trust: agent_extracted`,
`valid_from = created`. **(b)** Every new field is additive; `markdown_parser.parse/write` already
round-trips arbitrary YAML, so no parser change is required for frontmatter, only a new fenced
block reader.

### The entity page (evolved)

Frontmatter is a **superset** of today's — every current key stays, four are added:

```yaml
---
name: Rodrigo Sagastegui
type: person                       # CORE type (validated set) — unchanged key
status: active                     # unchanged
confidence: 0.9                    # unchanged: page-level rollup (max of valid-claim confidences)
created: '2026-01-10'              # unchanged
last_referenced: '2026-06-15'      # unchanged
decay_rate: 0.03                   # unchanged
source_episodes: [ep_2026-01-10_001, ...]   # unchanged
tags: [self, founder, engineer]    # unchanged
related: [anodos-labs, ie-university]        # unchanged (mirrors wikilinks)
version: 7                         # unchanged
# --- NEW (all optional; absent ⇒ legacy semantics) ---
facets: [engineering, family, philosophy]    # declared context dimensions for this entity
source_trust: user_stated          # default trust for claims authored from this page's edits
activation: 0.91                   # continuous salience (replaces binary promotion state)
schema_version: 2                  # 1 = legacy flat page; 2 = has claim block / facets
---

A short human prose intro stays for readability (Obsidian still renders it).

## facet: engineering
Rodrigo as a systems engineer — biases toward buildable, single-user, on-device designs.
[[Anodos Labs]] · [[Cicada]]

## facet: family
Rodrigo in a family context — values from home, Venezuela/Greece ties.

```claims
- id: clm_2026-04-10_017
  text: "Cicada's source of truth is markdown + git; sqlite-vec is derived and disposable."
  predicate: believes
  object: markdown-git-substrate
  facet: engineering
  epistemic: explicit            # explicit | deductive | inductive | abductive
  source_trust: user_stated      # user_stated | agent_extracted | agent_reflected | external
  confidence: 0.95
  source_episodes: [ep_2026-04-10_003]
  valid_from: '2026-04-10'
  valid_to: null                 # null ⇒ currently valid; a date ⇒ superseded
  superseded_by: null            # claim id that replaced this one
  premises: []                   # for deductive/inductive: claim ids this was derived from
- id: clm_2026-02-01_004
  text: "Rodrigo prefers concise, code-first answers over long prose."
  predicate: prefers
  facet: engineering
  epistemic: inductive
  source_trust: agent_reflected
  confidence: 0.7
  source_episodes: [ep_2026-01-22_002, ep_2026-02-01_004]
  valid_from: '2026-02-01'
  valid_to: null
```
```

The `claims` fenced block is the heart of the model. It is YAML inside a `​```claims` fence so it
is (a) trivially parseable, (b) invisible to wikilink/`mentions` materialization, (c) diff-friendly
in git (one claim = a few lines; supersession is a one-line `valid_to` edit visible in
`git blame`), and (d) ignored by any tool that doesn't know about it (graceful degradation).

The prose body above the block is **generated by Sleep** from the currently-valid claims (a peer
card), but hand edits survive because Sleep only rewrites the region between `<!-- card:auto -->`
markers, leaving human prose alone.

### Edges (`graph_edges.yaml`)

Schema is unchanged and back-compatible; two optional keys are added so edges can themselves be
contextual and temporal — the missing 4th RDF dimension at near-zero cost:

```yaml
edges:
- source: rodrigo
  target: sqlite                     # was postgres; superseded
  label: project uses
  context: engineering               # NEW optional: named-graph dimension
  valid_from: '2026-05-01'           # NEW optional
  valid_to: null                     # NEW optional
- source: rodrigo
  target: postgres
  label: project uses
  context: engineering
  valid_from: '2026-01-01'
  valid_to: '2026-05-01'             # closed, not deleted — stays queryable
```

### Candidates (shadow entities, replacing the hard gate)

`memory/candidates/<slug>.md` — same format as a slim entity page but with `status: candidate`
and an `activation` score. A candidate is a *real, inspectable, retrievable* object (it gets a
row in the sqlite-vec `pending` kind, exactly as today's JSONL does), but it is now human-readable
markdown the companion app can render and the user can promote/dismiss directly.

```yaml
---
name: Gaka-chu economically autonomous robot research
type: concept
status: candidate
activation: 0.34          # recency·frequency·importance·contextual-fit, ACT-R style
confidence: 0.8
created: '2026-04-10'
source_episodes: [ep_2026-04-10_005]
related: [eduardo-castello]
schema_version: 2
---
A robotics research effort associated with [[Eduardo Castello]] ...
```

`activation` is recomputed each Sleep from: `w_r·recency + w_f·log(mention_count) +
w_i·importance + w_c·max_contextual_similarity_to_existing_entities`. When `activation ≥ θ_promote`
(default 0.5, ablatable), Sleep moves the file `candidates/ → entities/`, sets `status: active`,
and backfills a claim block. When it drops below `θ_archive`, it moves to `archive/`. **There is
no "count to 2" rule anymore** — a single substantive conversation can promote on importance
alone, and ten trivial passing mentions never will.

### How the sqlite-vec index changes

Today (confirmed in `vector_index.py`): per-kind `vec0` virtual tables (`entities`, `episodes`,
`pending`) + a `_meta` table holding `text` + JSON `metadata`. Three additive changes, all within
the existing `_rebuild_table`/`_knn` machinery:

1. **New kind `claims`.** One row per *currently-valid* claim (`valid_to is null`), embedding =
   `claim.text`, metadata = `{claim_id, entity_id, facet, epistemic, source_trust, confidence,
   valid_from}`. This makes retrieval *per-claim* (high precision) instead of per-page (smeary).
   Invalidated claims are **not** indexed (they live in git + the file for audit, not in search).
2. **Facet-aware entity rows.** When a page has facets, index *one row per facet* (text = that
   facet sub-section + its facet-scoped claims) instead of one row for the whole page, with
   `metadata.facet` set. The `Rodrigo/engineering` vector and `Rodrigo/family` vector become
   distinct retrieval targets. Pages without facets keep their single whole-page row (unchanged).
3. **Metadata filter on `source_trust`/`epistemic`.** `_knn` already round-trips JSON metadata;
   `/ask` can now down-rank `agent_reflected`/`abductive` claims or surface trust to the caller.

The index stays **fully derived and disposable** — `rebuild` reads the markdown (claim blocks +
facets included) and regenerates everything. No migration of the DB itself is ever needed; you
delete and rebuild.

### How Sleep writes it (5 stages, evolved in place)

- **Stage 1 (Extraction):** extractor now emits **claims**, not just entities:
  `{predicate, object, text, epistemic, facet?, confidence}`. Existing entity extraction is the
  `epistemic: explicit, facet: general` special case — back-compatible prompt extension.
- **Stage 2 (Resolution):** unchanged entity resolution, **plus** claim attachment: each claim is
  routed to its subject entity's claim block (or to `claims/` if orphan), and facet is assigned
  by the disambiguation model (the same Stage-2 model already recorded in `Cicada-Author`).
- **Stage 3 (Conflict/Decay):** becomes the **invalidation** pass. A new claim that contradicts a
  valid one stamps the old claim's `valid_to` + `superseded_by` (Graphiti mechanic) — *no LLM
  judgment at read time*. Decay now operates on `source_trust`-weighted rates: `effective_decay =
  decay_rate · trust_multiplier[source_trust]` (user_stated 0.3×, agent_reflected 2×).
- **Stage 4 (Skills):** procedural/preference claims (`predicate: prefers`, `facet: engineering`)
  are first-class outputs, written as claims on the relevant entity *and* mirrored to a compact
  `entities/_preferences.md` always-loaded block for `/ask` injection.
- **Stage 5 (Versioning):** regenerates auto-card bodies from valid claims, recomputes `activation`
  on candidates, promotes/archives across the `candidates/`↔`entities/`↔`archive/` boundary, and
  commits with the existing `Cicada-Author` trailers. **No commit-message format change** — the
  claim-block lives in file bodies, which git already versions; `git blame` on a `valid_to:` line
  gives you exactly when and by which model a belief was retired.

### How /ask + MCP retrieve it

`ask_service` retrieval becomes a **two-pass merge** with no API contract change:

1. Retrieve top-k from the new `claims` kind (precise, dated, trust-tagged) **and** top-k entity
   facet rows. Merge by `score · trust_weight · recency_weight`, drop `valid_to != null` claims.
2. Build context as today (entity cards), but each card now lists its *valid claims with
   confidence + source_trust + valid_from*. The LLM prompt gains one rule: "prefer the claim with
   the latest `valid_from`; if two valid claims conflict, surface both and lower confidence."
3. Citations get richer for free: `used_entities` can now cite `claim_id`s, so a `/ask` answer
   points at the exact dated belief, not just the page. The existing gap-analysis output is
   unchanged.

MCP Bookworm gains one tool surface: `get_facet(entity, facet)` returns the facet sub-section +
its valid claims — a "who is Rodrigo *as an engineer* right now" synthesis (the Honcho user-model
injection that hit 90.4% at 5% context cost), instead of dumping the whole averaged page.

---

## Worked examples

### 1. Engineer-self vs family-self (faceted identity)

One file `entities/rodrigo.md`, `facets: [engineering, family, philosophy]`. Body has
`## facet: engineering` and `## facet: family` sub-sections; the claim block carries
`facet:`-tagged claims. The index stores **three** vectors for Rodrigo. A query "what does Rodrigo
value when building software" hits the `engineering` facet vector and its claims
(`prefers buildable single-user on-device designs`); "what matters to Rodrigo about home" hits the
`family` facet vector. No averaging, no context collapse, one page, one git history. A cross-facet
abstract link (Sleep-detected) is just an edge: `rodrigo --(value carries across)--> rodrigo`
with `context: cross`, or more usefully an edge between a `family` claim and an `engineering`
claim that share a tag.

### 2. A belief that changes: Postgres → SQLite

Day 1, `entities/cicada.md` claim block gains:

```yaml
- id: clm_2026-01-15_002
  text: "Cicada uses Postgres for the derived index."
  predicate: uses
  object: postgres
  epistemic: explicit
  source_trust: user_stated
  confidence: 0.9
  valid_from: '2026-01-15'
  valid_to: null
```

Day 110, an episode says "switched the index to sqlite-vec." Sleep Stage 3 detects the
contradiction (same subject+predicate, conflicting object), and **without deleting anything**:

```yaml
- id: clm_2026-01-15_002
  ...
  valid_to: '2026-05-05'          # closed
  superseded_by: clm_2026-05-05_009
- id: clm_2026-05-05_009
  text: "Cicada uses sqlite-vec for the derived index."
  predicate: uses
  object: sqlite-vec
  source_trust: user_stated
  confidence: 0.95
  valid_from: '2026-05-05'
  valid_to: null
```

The `claims` index now only embeds the SQLite claim, so `/ask "what's Cicada's vector store"`
returns SQLite. But `/ask "what did Cicada use before SQLite"` can still find the closed claim
(it's in the file + git), and `git blame` on the `valid_to:` line shows the exact Sleep commit and
authoring model that retired the Postgres belief. `graph_edges.yaml` mirrors this with a closed
`valid_to` Postgres edge and an open SQLite edge.

### 3. A procedural preference

Episode: Rodrigo corrects the agent's FastAPI scaffolding. Sleep Stage 4 emits a claim on
`entities/fastapi.md` (and mirrors into `_preferences.md`):

```yaml
- id: clm_2026-03-02_011
  text: "When scaffolding a FastAPI service, split routers by domain (one file per resource) and keep services thin."
  predicate: prefers
  object: fastapi-router-per-domain
  facet: engineering
  epistemic: inductive
  source_trust: agent_reflected
  confidence: 0.75
  source_episodes: [ep_2026-02-10_004, ep_2026-03-02_011]
  valid_from: '2026-03-02'
  valid_to: null
```

`_preferences.md` is always injected at conversation start (a compact behavioral block, per the
procedural-memory research's "inject, don't retrieve" rule). If Rodrigo later flips this
preference, Stage 3 closes it with `valid_to` + `superseded_by`, so the agent stops applying the
stale rule — solving the preference-change-detection gap all three production frameworks fail.

### 4. A saved media item

A saved YouTube video / RSS article (today in `sources/`) becomes an entity with a **soft type**
the closed enum never allowed:

```yaml
---
name: "Andrej Karpathy — Intro to LLMs (talk)"
type: media               # SOFT type: not in the 5-core set, accepted verbatim
status: active
source_trust: external
url: https://youtu.be/...
created: '2026-06-01'
source_episodes: [ep_2026-06-01_002]
related: [llm, context-engineering]
schema_version: 2
---
<!-- card:auto -->
A talk introducing LLM fundamentals; saved because it relates to [[Context Engineering]].
<!-- /card:auto -->

```claims
- id: clm_2026-06-01_021
  text: "Karpathy frames an LLM as a lossy compression of its training corpus."
  predicate: claims
  epistemic: explicit
  source_trust: external          # decays slow, but flagged as not-the-user's-belief
  confidence: 0.6
  source_episodes: [ep_2026-06-01_002]
  valid_from: '2026-06-01'
  valid_to: null
```
```

`type: media` is stored as an opaque metadata tag in sqlite-vec; no enum rejects it. `/ask` can
cite the external claim while signalling `source_trust: external` so the agent attributes it to
Karpathy, not to Rodrigo.

---

## Migration (from ~1,882 existing typed entity pages)

**Core principle: zero-downtime, lazy, and reversible. A legacy page is already a valid evolved
page.** No bulk LLM pass is *required* to ship; the model degrades gracefully and migrates pages
on touch.

**Step 0 — Code (no data change, ~1 day).** Extend `markdown_parser` with a `parse_claims(body)`
reader for the `​```claims` fence (returns `[]` if absent). Add the `claims` vec0 kind to
`vector_index.py` (`index_claims()`, `search_claims()`, mirroring `index_entities`). Teach
`_entity_embed_text` to emit per-facet rows when `facets:` present. Add `candidates/` as an alias
front-end over the existing pending store. **All four are additive; legacy pages with no claim
block / no facets behave exactly as today.** Cost: engineering only, $0 LLM.

**Step 1 — Backfill frontmatter (mechanical, $0).** A script stamps `schema_version: 1`,
`source_trust: agent_extracted` (these pages were LLM-written), and `activation` (computed from
existing `last_referenced` + `source_episodes` length) on all 1,882 pages. Pure Python, one
commit, no LLM.

**Step 2 — Index rebuild ($, ~once).** Rebuild the sqlite-vec DB. With no claim blocks yet, this
is *identical* to today's index (one row per page). Cost = current rebuild cost (a few cents of
embeddings; local EmbeddingGemma is $0).

**Step 3 — Lazy claim extraction (amortized $, optional).** Pages are *not* mass-converted. A page
is upgraded to `schema_version: 2` (its body parsed into a claim block) **only when Sleep next
touches it** (new episode mentions it) — extraction was going to run on that page anyway, so the
marginal cost is ~one extra structured field in the prompt. Cold pages stay legacy forever at no
cost. If a full backfill is wanted for the thesis Results: 1,882 pages × ~1 cheap structured call
≈ **\$2–6 total** on a mini model (the same magnitude as one Sleep cycle), runnable overnight in a
`/tmp/cicada_bench_*` workspace per the benchmark safety rails. **This is the only LLM cost, and
it's optional.**

**Step 4 — Facets only where they pay (tiny $).** Faceting is applied to the handful of genuinely
multi-context entities (`rodrigo`, maybe 5–20 others), not all 1,882. Identified by an edge-count
+ tag-diversity heuristic, then one LLM pass each to split the body. Cost: cents.

**Rollback:** delete the `claims` fences and `facets:` keys → every page is byte-compatible with
the old model. The index rebuild regenerates the old shape. **No lock-in.**

---

## Scorecard (C1–C9, honest)

- **C1 Agent retrieval quality — 9/10.** Per-claim + per-facet indexing is strictly more precise
  than per-page smear; trust/recency-weighted merge and dated claims let the agent know *how much
  to trust* each fact. Weakness: two indexes (claims + entity facets) add a merge/ranking knob
  that needs tuning.
- **C2 Context-dependent identity — 8/10.** Facets + `context:` edges deliver multi-faceted
  identity and cross-context links on one page, no per-context graphs. Weakness: facet assignment
  is LLM-judged and can mis-bin; only entities flagged multi-context get faceted, so a missed
  flag silently collapses a context.
- **C3 Temporal change & contradiction — 10/10.** Bi-temporal `valid_from`/`valid_to` +
  `superseded_by`, append-only, git blame on the closing line. This is the model's strongest axis
  and the current model's weakest. No read-time LLM contradiction guessing.
- **C4 Provenance & confidence — 9/10.** `source_trust ⊥ confidence`, per-claim `source_episodes`,
  `epistemic` type, plus existing `Cicada-Author` trailers and git blame. Claim-level citations in
  `/ask`. Weakness: more provenance fields = more for Sleep to populate correctly.
- **C5 Procedural / preference memory — 9/10.** `predicate: prefers` claims + always-injected
  `_preferences.md` + supersession-based change detection — beats every framework surveyed.
  Weakness: distinguishing a durable preference from a one-off correction is still an inductive
  judgment that can over-generalize.
- **C6 Migration cost & incrementality — 10/10.** This is the stance's whole point: legacy pages
  are valid as-is, migration is lazy/on-touch, total *required* LLM cost is \$0 (optional full
  backfill ≈ \$2–6), fully reversible. Lowest risk of all candidates by construction.
- **C7 Extensibility — 8/10.** Soft types absorb media/problems/open-questions with no enum gate;
  new claim `predicate`s need no schema change. Weakness: soft types can drift into synonym sprawl
  (`tool` vs `library` vs `framework`) without a periodic Sleep normalization pass.
- **C8 Simplicity / maintainability — 6/10.** **The honest weak point.** This adds real concepts a
  solo dev must hold: claims-in-a-fence, facets, bi-temporal validity, activation, two index
  kinds. It is more moving parts than today's flat page. Mitigated by additivity (each piece is
  independently shippable and ignorable) but it is undeniably more surface area.
- **C9 Overall — 8.5/10.** The best *risk-adjusted* agent memory: it captures ~90% of the upside
  of a full claim-graph rewrite (precise dated trustable beliefs, faceted identity, real
  procedural memory) while keeping every existing page, commit, and index valid and migrating for
  ~\$0. It trades the top 10% of theoretical elegance (a pure claim-DAG with no entity pages) for
  near-zero migration risk and continued human/Obsidian readability — the right trade for a solo
  thesis on a live 1,882-page store.
