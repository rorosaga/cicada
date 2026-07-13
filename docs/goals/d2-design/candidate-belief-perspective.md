# Perspectival Belief Memory (PBM)

> A belief-centric knowledge model for Cicada. The atom of memory is a **belief**
> keyed by `(observer, context, subject)`. Entities stop being the unit of truth
> and become *emergent indexes* over beliefs. A faceted self-model is first-class.
> Abductive guesses decay faster than asserted facts. Everything still lives in
> markdown + git, and the sqlite-vec index becomes a belief index.

---

## Philosophy

Cicada today stores **one markdown page per entity**, and that page *is* the belief:
its body is canonical truth, its frontmatter carries a single `confidence` float, a
single `status`, and a single `last_referenced`. This is the architecture that
Danah boyd's "context collapse" predicts will fail for a multi-context person: the
`Rodrigo` page silently averages engineer-Rodrigo, family-Rodrigo, and
philosopher-Rodrigo into one mush, and there is nowhere to put "this was true until
March" except an ad-hoc `## History` bullet the LLM has to remember to write.

PBM inverts the ownership. The atom becomes a **belief**: a single, atomic,
self-contained claim — *"Rodrigo uses SQLite for Cicada's index"* — stamped with:

- **who holds it** (`observer`: the agent, or Rodrigo himself, or an external source),
- **in what context it is true** (`context`: `engineering | family | philosophical | career | general | …` — an *open* set),
- **what it is about** (`subject`: the entity id it attaches to),
- **its epistemic status** (`asserted | deductive | inductive | abductive`), which sets its decay rate,
- **bi-temporal validity** (`valid_from / valid_to` = true-in-world; `recorded_at` + git commit = learned-by-system),
- **provenance** (source episode(s), authoring model, source-trust class),
- **confidence**, kept *orthogonal* to source-trust.

Entities do not disappear — Rodrigo, SQLite, FastAPI still have pages — but a page is
now a **generated peer-card**: a rendered, human-readable *view* over the beliefs whose
`subject` is that entity, grouped by context. The card is rebuildable from the belief
store the way the sqlite-vec index is rebuildable from markdown. Truth lives in the
beliefs; the card is a projection. This directly absorbs Honcho's `(observer, observed)`
reframing (the agent's model of engineer-Rodrigo is a *genuinely different object* from
its model of family-Rodrigo, not a filtered slice of one), Graphiti's "facts not
entities are the temporal unit," and Mem0's 2026 ADD-only reversal (never overwrite a
belief — close its `valid_to` and add a new one; git holds the rest).

Three commitments make this opinionated rather than a grab-bag:

1. **No promotion gate.** The 2nd-mention rule is deleted. A belief is written on first
   observation; whether it *surfaces* is decided at read time by an ACT-R-style
   activation score (recency × frequency × confidence × source-trust), not by a hard
   threshold at write time. Low-signal beliefs simply have low activation and sink.
2. **Decay is per-epistemic-status, not a global `decay_rate`.** An asserted fact
   ("Rodrigo's supervisor is Raul") barely decays. An abductive guess ("Rodrigo
   *probably* prefers Postgres") decays fast and self-prunes if never reinforced. This
   is the single cleanest answer to "asserted facts vs inferences should not age alike."
3. **Context is a first-class key, not a tag.** `(observer, context, subject)` is the
   primary key. The same subject can carry contradictory beliefs *without* conflict if
   their contexts differ — engineer-Rodrigo "prefers terseness," family-Rodrigo "prefers
   warmth" — and the Sleep cycle's cross-context pass is exactly the place abstract links
   between not-obviously-related things get drawn.

---

## Data model

### On-disk layout

```
memory/
├── beliefs/                         ← NEW: the atom. One file per subject-entity,
│   │                                   holding all beliefs about that subject as a
│   │                                   YAML list. (Co-locating by subject keeps
│   │                                   git diffs legible and blame per-subject.)
│   ├── rodrigo.beliefs.yaml
│   ├── cicada-index.beliefs.yaml
│   └── …
├── entities/                        ← KEPT but DEMOTED: generated peer-cards.
│   │                                   Human-readable projection of beliefs/, with a
│   │                                   `generated: true` flag. Obsidian still works.
│   ├── rodrigo.md
│   └── …
├── facets/                          ← NEW: the faceted self-model. One file per
│   │                                   (observer-of-self) context dimension.
│   ├── rodrigo.engineering.md
│   ├── rodrigo.family.md
│   └── rodrigo.philosophical.md
├── episodes/                        ← UNCHANGED (raw source of truth for capture)
├── procedures/                      ← NEW: procedural/preference memory, IF-THEN rules
│   ├── fastapi-repo-structure.md
│   └── …
├── sources/                         ← UNCHANGED (media items)
├── graph_edges.yaml                 ← KEPT, EXTENDED with belief-typed edges
├── vector_index.db                  ← KEPT; gains vec_beliefs / vec_procedures tables
└── hubs/ , nudges/ , clarifications/, _index.md   ← UNCHANGED
```

Why a YAML list per subject rather than one file per belief? At ~1,882 subjects and a
handful-to-dozens of beliefs each, one-file-per-belief means tens of thousands of tiny
files (slow git, slow globbing, noisy diffs). One-file-per-subject keeps `git blame
beliefs/rodrigo.beliefs.yaml` answering "when did we learn each belief about Rodrigo, and
which model authored it" — the existing provenance machinery (`Cicada-Author` trailers,
per-commit `author` on `/entities/{id}/history`) keeps working unchanged.

### A belief, on disk

`memory/beliefs/cicada-index.beliefs.yaml`:

```yaml
subject: cicada-index            # the entity id this file is about
subject_name: Cicada vector index
beliefs:
  - id: blf_2026-03-20_004a      # stable id: episode-derived + hash suffix
    claim: "Cicada's semantic index is built on sqlite-vec."
    observer: agent              # agent | rodrigo | external:<name>
    context: engineering         # OPEN set; `general` if context-free
    epistemic: asserted          # asserted|deductive|inductive|abductive
    confidence: 0.9              # how sure we are it's correct
    source_trust: user_stated    # user_stated|agent_extracted|agent_reflected|external
    valid_from: '2026-03-20'     # true-in-world start
    valid_to: null               # null = still believed true
    recorded_at: '2026-03-20'    # when the system learned it
    source_episodes: [ep_2026-03-20_002]
    premises: []                 # for deductive beliefs: ids of beliefs it rests on
    relations:                   # typed edges this belief asserts (mirror to graph_edges)
      - predicate: replaces
        object: leann
  - id: blf_2026-01-08_011x
    claim: "Cicada's semantic index is built on LEANN."
    observer: agent
    context: engineering
    epistemic: asserted
    confidence: 0.85
    source_trust: user_stated
    valid_from: '2026-01-08'
    valid_to: '2026-03-20'       # CLOSED — superseded, not deleted
    superseded_by: blf_2026-03-20_004a
    recorded_at: '2026-01-08'
    source_episodes: [ep_2026-01-08_001]
```

Key field semantics:

- **`epistemic` drives decay.** Effective decay rate is a lookup, not a stored per-entity
  number: `asserted → 0.02`, `deductive → 0.05`, `inductive → 0.10`, `abductive → 0.20`
  per Sleep cycle, multiplied *down* by `source_trust` (`user_stated` decays at 0.3×;
  `agent_reflected` at 1.5×). This replaces the global `decay_rate: 0.05` with something
  that actually distinguishes a stated fact from a guess.
- **`valid_to` is contradiction handling.** When a new episode contradicts an existing
  belief *in the same context*, Sleep does not overwrite: it stamps `valid_to` +
  `superseded_by` on the old belief and appends the new one. Both stay queryable. Across
  *different* contexts there is no contradiction — both stay open.
- **`confidence` ⟂ `source_trust`.** A user-stated belief decays slowly even at moderate
  confidence; an agent-reflected generalization decays fast even at high confidence. The
  `/ask` endpoint surfaces both so the calling agent knows *how sure* and *why*.

### The generated peer-card (`entities/cicada-index.md`)

```markdown
---
name: Cicada vector index
generated: true                  # NEVER hand-edit; Sleep overwrites
belief_file: beliefs/cicada-index.beliefs.yaml
type: tool                       # retained as a coarse label for graph node color
status: active
activation: 0.81                 # ACT-R score, replaces raw `confidence` for ranking
contexts: [engineering]
last_referenced: '2026-03-20'
version: 7
---

## Current beliefs (engineering)
- Built on **sqlite-vec**, replacing [[leann]]. _(asserted, conf 0.90, since 2026-03-20)_

## Superseded
- ~~Built on [[leann]]~~ — held 2026-01-08 → 2026-03-20, replaced by sqlite-vec.
```

The card is a *deterministic render* of the belief file — no LLM call needed to
regenerate it. Obsidian, the d3 graph, and the existing `markdown_parser` all keep
working because the file is still markdown-with-frontmatter. `type` is kept purely as a
coarse 8-color label for the graph; it is no longer load-bearing for truth.

### Faceted self-model (`facets/rodrigo.engineering.md`)

The self is not one entity. It is N facet files, each a peer-card over the beliefs whose
`subject: rodrigo` AND `context: <facet>`. A `cross` facet file is generated by the Sleep
cross-context pass and holds *abstract links* it drew between facets ("engineer-Rodrigo's
preference for minimal infra echoes philosopher-Rodrigo's value of simplicity").

### Edges (`graph_edges.yaml`, extended)

The existing `{source, target, label}` shape is kept (the graph builder and
`graph_edges-yaml.md` mirror stay valid). Two optional fields are added so edges become
context-aware and belief-grounded:

```yaml
edges:
  - source: cicada-index
    target: leann
    label: replaces
    context: engineering         # NEW (optional; absent = general)
    belief_id: blf_2026-03-20_004a   # NEW (optional; provenance back to the belief)
```

Edges remain *derived* from `relations:` stanzas in belief files (materialized in Stage
5.5, exactly like today's wikilink→`mentions` materialization), so there is one source of
truth and the YAML is rebuildable.

### sqlite-vec index changes

The index gains tables, following the *exact* existing pattern in `vector_index.py`
(`vec_<kind>` virtual table + rowid-aligned `meta_<kind>` table, JSON metadata blob):

- **`vec_beliefs` / `meta_beliefs`** — one row per *open* belief (`valid_to is null`).
  Embedded text = `claim` (the atomic claim embeds far better than a whole page; this is
  Honcho's "atomic claims are the queryable substrate"). Metadata JSON:
  `{belief_id, subject, subject_name, observer, context, epistemic, confidence,
  source_trust, activation, valid_from}`. Context + status become *post-filters* on the
  KNN result set, exactly like today's `status != archived` filter in `search_entities`.
- **`vec_procedures` / `meta_procedures`** — one row per procedure, embedded on its
  trigger description (see below).
- **`vec_entities`** stays as a coarse card-level index for whole-page semantic hits;
  **`vec_episodes`** is unchanged. `vec_pending` is **removed** (no promotion gate ⇒ no
  pending tier; `pending_entities.jsonl` is retired).

A new `index_beliefs()` method mirrors `index_entities()`: glob `beliefs/*.yaml`, emit
one row per open belief, `self._embed(claims)`, `self._rebuild_table(conn, "beliefs",
rows)`. Same injected `embed_fn`, same model-swap detection, same `is_query` asymmetric
prompting.

### How Sleep writes it (mapped onto the real 5 stages)

The pipeline keeps its 5-stage shape and the `git_service.build_commit_message(subject,
body_lines, authors=…)` provenance contract:

1. **Extraction** → now emits **beliefs**, not entity drafts: typed atomic claims with
   `observer/context/epistemic` already attached (the extraction prompt asks the model to
   classify epistemic status and infer context from the episode).
2. **Resolution & dedup** → resolves each belief's `subject` against existing subject ids
   (fuzzy + embedding + the existing `entity_resolver`). Identical open beliefs are merged
   (bump `confidence`, refresh activation); near-duplicates in the same context are
   candidates for supersession in Stage 3.
3. **Conflict & decay** → the bi-temporal close. Same-context contradictions stamp
   `valid_to`/`superseded_by`. Decay applies the per-epistemic, trust-weighted rate.
   Below-archive beliefs get `status: archived` in the card (the belief row is dropped
   from `vec_beliefs`, kept in YAML + git).
4. **Pattern & skill** → writes/updates `procedures/*.md` (preferences & workflows) and
   runs the **cross-context pass**: for each subject with beliefs in ≥2 contexts, ask the
   LLM whether an abstract cross-link exists; if so, write a belief with
   `context: cross`, `epistemic: inductive`.
5. **Nudge & versioning** → regenerates peer-cards + facet files (deterministic render),
   regenerates hubs/`_index.md`, materializes edges (Stage 5.5), reindexes
   `vec_entities/vec_episodes/vec_beliefs/vec_procedures`, and commits with
   `Cicada-Author` trailers — all unchanged machinery.

### How /ask + MCP retrieve it

`ask_service.answer_query` keeps its full auditable shape (answer + citations +
confidence + gaps) and its dependency-injection seams. Only the default `retrieve_fn`
changes — from `search_entities` to a **belief-first retrieve**:

1. KNN over `vec_beliefs` for the query (top-k claims).
2. **Activation re-rank** (Generative-Agents formula): `score = w₁·sim + w₂·recency +
   w₃·activation`, where activation folds frequency + confidence + source-trust. This is
   where temporally-critical-but-semantically-distant beliefs surface.
3. **Context filter / boost**: if the calling agent passes a `context` hint (MCP can; the
   conversation's topic implies it), in-context beliefs are boosted and the opposing
   facet is down-weighted — this is the read-time answer to context collapse.
4. Group surviving beliefs by `subject`, load the peer-card snippet for citation, and
   build the prompt. Citations now carry `belief_id` + `source_episodes` + `valid_from`,
   so the agent can see *which atomic claim*, *when true*, *how trusted*. `gaps` naturally
   reports "I hold a superseded belief but no current one for X."

MCP "Bookworm" progressive disclosure becomes: matched beliefs → subject peer-card →
facet file → episode. The promotion-gate check in proactive behaviors is replaced by an
activation check (surface low-activation-but-on-topic beliefs as soft clarifications).

---

## Worked examples

### 1. Engineer-self vs family-self (faceted identity)

Two beliefs, same subject, different context, both open, no contradiction:

```yaml
# beliefs/rodrigo.beliefs.yaml (excerpt)
- id: blf_2026-02-01_007
  claim: "Rodrigo prefers terse, code-first answers with no preamble."
  observer: agent
  context: engineering
  epistemic: inductive          # learned from many sessions
  confidence: 0.8
  source_trust: agent_extracted
  valid_from: '2026-02-01'
  valid_to: null
- id: blf_2026-02-14_002
  claim: "Rodrigo values warmth and patience when discussing family."
  observer: agent
  context: family
  epistemic: inductive
  confidence: 0.7
  source_trust: agent_extracted
  valid_from: '2026-02-14'
  valid_to: null
```

Renders to `facets/rodrigo.engineering.md` ("prefers terse code-first answers") and
`facets/rodrigo.family.md` ("values warmth"). An MCP client in a coding session passes
`context: engineering`; `/ask "how should I talk to Rodrigo"` boosts the first belief and
down-weights the second — no averaging, no collapse. The Stage-4 cross pass may emit:

```yaml
- id: blf_2026-03-01_cross1
  claim: "Across contexts, Rodrigo optimizes for low-friction interaction — terseness in
          engineering and emotional ease in family are the same underlying value."
  observer: agent
  context: cross
  epistemic: abductive          # a guess → decays fast unless reinforced
  confidence: 0.45
  source_trust: agent_reflected
```

That abductive cross-link self-prunes in ~10 cycles if no later episode supports it —
exactly the desired "draw abstract links but don't let speculation calcify into fact."

### 2. A belief that changes over time (Postgres → SQLite)

Episode on 2026-01-08: "I'm using Postgres for the index." Sleep writes
`blf_…_a (claim: uses Postgres, context: engineering, valid_to: null)`. Episode on
2026-03-20: "Switched the index to SQLite + sqlite-vec." Stage 3 detects a same-context
contradiction and performs the bi-temporal close:

```yaml
- id: blf_2026-01-08_a
  claim: "Rodrigo uses Postgres for Cicada's index."
  context: engineering
  valid_from: '2026-01-08'
  valid_to: '2026-03-20'        # CLOSED
  superseded_by: blf_2026-03-20_b
- id: blf_2026-03-20_b
  claim: "Rodrigo uses SQLite + sqlite-vec for Cicada's index."
  context: engineering
  valid_from: '2026-03-20'
  valid_to: null
```

`vec_beliefs` now indexes only the SQLite belief, so `/ask "what database does Cicada
use"` returns SQLite with high confidence — the primary RAG-for-memory failure (an old
semantically-similar belief beating the new one) is eliminated *at index time*, not hoped
away at read time. `/entities/cicada-index/history` still shows the full arc via git +
the `Superseded` card section, with the authoring model on each commit.

### 3. A procedural preference (`procedures/fastapi-repo-structure.md`)

```markdown
---
type: procedure
trigger: "scaffolding or refactoring a FastAPI backend"
scope: [engineering, python, fastapi]
status: active
confidence: 0.9
source_trust: user_stated
source_episodes: [ep_2026-02-10_003, ep_2026-04-02_001]
supersedes: null
version: 2
---

## Preference
Split FastAPI routers by domain (one router module per resource), services in a
`services/` package, Pydantic models separate from routers.

## Steps
1. `routers/<resource>.py` per domain noun.
2. Business logic in `services/<resource>_service.py`, never in the router.
3. Dependency-inject services for hermetic testing.

## Verified in
- ep_2026-02-10_003 (Cicada's own `api/` layout)
```

Embedded in `vec_procedures` on its **trigger** ("scaffolding or refactoring a FastAPI
backend"), retrieved at task recognition, and — per the Voyager/Honcho finding — injected
as a compact block at conversation start rather than fetched mid-task. If a later episode
contradicts it ("actually, keep it flat for small services"), Stage 4 writes a new
procedure with `supersedes: <old_id>` and sets the old to `status: superseded` — the same
bi-temporal discipline as beliefs, audit trail via git.

### 4. A saved media item

A saved article keeps its existing `sources/` ingestion, but now *contributes beliefs*
instead of being an inert node:

```yaml
# sources unchanged; Sleep emits beliefs observed FROM the source
- id: blf_2026-05-01_m3
  claim: "Graphiti models facts as bi-temporal edges, not entities."
  observer: external:graphiti-blog       # the source IS the observer
  context: engineering
  epistemic: asserted
  confidence: 0.8
  source_trust: external                  # external trust → moderate decay
  source_episodes: [src_2026-05-01_graphiti]
  relations:
    - predicate: informs
      object: cicada-index
```

`/ask "what did I read about temporal knowledge graphs"` retrieves the belief, and its
`observer: external:graphiti-blog` makes the provenance honest — the agent knows this is
something Rodrigo *read*, not something he *asserted*. The Stage-5.55 media→entity `about`
edge injection still fires, now belief-grounded.

---

## Migration (from ~1,882 typed entity pages)

The migration is **mechanical-first, LLM-second**, and incremental — the system stays
queryable throughout because peer-cards remain at `entities/*.md`.

**Step 0 — branch + freeze.** New branch; existing `entities/` untouched until Step 3.

**Step 1 — deterministic belief seeding (no LLM, ~free).** A script walks every
`entities/*.md`. For each page it emits one *seed belief* per page into
`beliefs/<id>.beliefs.yaml`:
- `claim` = first sentence of the body (or `name + ": " + body[:200]`),
- `subject` = file stem, `observer: agent`, `context: general` (provisional),
- `epistemic: asserted` if `source_trust` would be user_stated else `inductive`,
- `confidence` ← existing `confidence`, `valid_from` ← `created`,
  `recorded_at` ← `created`, `source_episodes` ← existing list,
- existing `## History` bullets → additional beliefs with `valid_from` parsed from the
  bullet date; the *latest* stays open, earlier ones get `valid_to` = next bullet's date.
This alone gives a working belief store with bi-temporal history *for free* and maps the
8 types onto: `skill`→`procedures/`, everything else→a subject with beliefs. Cost: $0,
minutes of runtime.

**Step 2 — context + epistemic enrichment (LLM, batched, the only real cost).** A
one-pass Sleep-style job re-reads each seed belief *with its source episodes* and fills
the provisional fields: real `context` (engineering/family/…), real `epistemic`,
split-one-page-into-multiple-beliefs where a page actually held several claims.
Cost estimate: ~1,882 subjects, batch ~20 per call ≈ 95 calls; with a cheap model
(`gpt-5.4-mini`-class) at a few-hundred input tokens each, this is **single-digit
dollars**, comparable to one `benchmarks.rebuild_leann` run. It is *resumable* (idempotent
per subject) and can run overnight as a one-off "deep Sleep."

**Step 3 — regenerate + reindex.** Run the deterministic card/facet renderer over the new
belief store (overwrites `entities/*.md` with `generated: true`), build `facets/`,
materialize edges, build `vec_beliefs`/`vec_procedures`, retire
`pending_entities.jsonl`/`vec_pending`. One commit with `Cicada-Author` trailers.

**Step 4 — flip the default `retrieve_fn`** in `ask_service` to belief-first; keep
`search_entities` as a fallback (graceful-degrade pattern already in the code). Ship.

Rollback is `git revert` + delete `beliefs/`/`facets/`/`vector_index.db`; the original
entity pages are recoverable from history. No data is destroyed at any step.

---

## Scorecard (C1–C9, honest)

- **C1 — Agent retrieval quality & usability: 9.** Atomic claims embed far better than
  whole pages; activation re-rank surfaces important-but-distant memories; bi-temporal
  filtering kills the stale-fact failure mode at index time. Best-in-class for an LLM
  reader.
- **C2 — Context-dependent identity: 10.** This is the design's home turf:
  `(observer, context, subject)` is the primary key, facet files are first-class, the
  cross-context pass actively draws abstract links. Nothing else in the research digest
  matches this.
- **C3 — Temporal change & contradiction: 9.** Bi-temporal `valid_from/valid_to` +
  `superseded_by`, never-overwrite, per-epistemic decay. Weakness: same-context
  contradiction *detection* still depends on LLM judgment in Stage 3 (Graphiti gets this
  partly mechanical via edge keys; here it's a prompt).
- **C4 — Provenance & confidence: 9.** Orthogonal `confidence` ⟂ `source_trust`,
  `observer` records *who holds* each belief, git + `Cicada-Author` trailers per write,
  belief-level citations in `/ask`. Slight loss vs entity-pages: blame is now per-subject-
  file, not per-line-claim (still better than today).
- **C5 — Procedural / preference memory: 9.** Dedicated `procedures/` with trigger
  semantics, scope tags, supersession, verified-in citations, injected-at-start retrieval
  — ahead of mem0/cognee/Letta per the digest. Not a 10 only because execution/veraction
  of skills (Voyager-style) is out of scope.
- **C6 — Implementation cost & incremental migratability: 7.** Honest weak-ish point. The
  substrate (markdown+git+sqlite-vec) is reused and the migration is mostly mechanical,
  but it *is* a new primary store (`beliefs/`), a new index table, a rewritten extraction
  prompt, a card renderer, and a single-digit-dollar LLM enrichment pass. Real work,
  spread over a few PRs.
- **C7 — Extensibility: 9.** New knowledge kinds = new `observer`/`context`/`epistemic`
  values or a new `predicate` — *no schema migration, no graph sprawl*, because the type
  taxonomy stopped being load-bearing. Media, open-questions, problems all become beliefs
  or procedures.
- **C8 — Simplicity / maintainability: 6.** The **biggest weakness.** Two derived layers
  (cards + index) over one source (beliefs) is more moving parts than "one page = truth."
  A solo dev must trust the renderer and never hand-edit cards. Mitigated by determinism
  (cards/edges are pure functions of beliefs) and by reusing every existing Sleep stage
  and provenance mechanism rather than inventing new infra — but it is undeniably more
  conceptual surface than the status quo.
- **C9 — OVERALL best agent memory system: 9.** For *this* user (multi-context self,
  changing beliefs, strong procedural needs, an agent that must say how much to trust a
  memory), the belief atom + faceted self + bi-temporal validity + epistemic-weighted
  decay is the strongest fit in the research set. The cost is maintainability surface
  (C8) and a one-time migration (C6) — a deliberate, defensible trade.
