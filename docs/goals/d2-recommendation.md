# D2: Recommended Memory Structure

## Executive recommendation

Adopt a **belief-centric, bi-temporal claim layer on top of the existing entity pages** — a
disciplined hybrid that takes **Evolved-Cicada's substrate and migration stance as the chassis**
and grafts onto it the **three highest-scoring ideas from the other candidates**: Temporal-Fact-Graph's
*mechanical, predicate-keyed contradiction handling*; Perspectival-Belief-Memory's *`(observer, context, subject)`
keying and per-epistemic-status decay table*; and Tiered-Cognitive's *hard split between always-injected
preferences and similarity-gated procedures*. The atom of truth becomes a **claim** (a dated, sourced,
context-scoped, bi-temporally-valid statement) stored as a YAML list inside the same markdown entity
page it is about; the page body becomes a *generated card* over its currently-valid claims; the
sqlite-vec index gains a per-claim kind so retrieval is per-assertion, not per-page-smear. This wins
because it is the only configuration that scores at-or-near the top on **all three judge lenses
simultaneously** — it keeps Evolved's decisive C6=10 (a legacy page is *already* a valid new page,
$0 required migration, byte-reversible), while closing Evolved's only real expressiveness gaps
(facet-by-default instead of facet-by-heuristic, mechanical contradiction detection instead of LLM-judged)
by importing the exact mechanisms the expressiveness and retrieval judges rewarded in the candidates
they crowned. We deliberately **do not** adopt a separate `facts/` or `beliefs/` primary store, a
`facets/` directory, or five index kinds — each of those is the specific thing a judge flagged as the
losing candidate's fatal maintenance/migration tax.

---

## The model

Name: **Cicada Claim Layer (CCL)**. One sentence: *the entity page stays as the human-readable,
git-versioned, Obsidian-compatible home for a subject, but the unit of truth, retrieval, and provenance
is an atomic claim living in a fenced YAML block inside that page, keyed by `(observer, context, subject)`,
bi-temporally valid, and indexed individually.*

### File layout (what changes, what doesn't)

```
memory/
├── entities/             ← UNCHANGED location. Pages gain a ```claims fence + ## facet: sections.
│   │                        A page with no claims fence is a valid CCL page (its body = one implicit claim).
│   ├── rodrigo.md
│   ├── cicada.md
│   └── ... (all 1,882 stay in place)
├── episodes/             ← UNCHANGED. Raw, immutable, append-only. Gains optional importance: at Sleep.
├── candidates/           ← NEW. Shadow entities as markdown stubs with an `activation` score,
│   │                        replacing the opaque pending_entities.jsonl front door (jsonl kept for back-compat).
│   └── gaka-chu-research.md
├── _preferences.md       ← NEW. The always-injected behavioral block (preferences only).
├── _procedures/          ← NEW (optional). Task-triggered reusable step-lists (procedures only).
│   └── fastapi-repo-layout.md
├── _predicates.yaml      ← NEW. Canonical predicate-synonym map (chose ≈ selected ≈ picked → chose).
├── graph_edges.yaml      ← UNCHANGED schema; edges gain OPTIONAL context / valid_from / valid_to / claim_id.
├── leann/ → vector_index.db  ← sqlite-vec; gains a `claims` vec0 kind + per-facet entity rows.
├── nudges/ clarifications/ hubs/ sources/ inbox/   ← UNCHANGED.
```

**The one load-bearing invariant:** an unmodified legacy page (no `claims` fence, no facets) is a
*valid CCL page* — its body is its single implicit claim with `observer: agent`, `context: general`,
`source_trust: agent_extracted`, `epistemic: explicit`, `valid_from = created`, `valid_to: null`.
This is the property the pragmatics judge scored C6=10 and refused to give any other candidate. We keep it.

### The unit: a claim

Claims live in a fenced ` ```claims ` block inside the entity page (so they round-trip through the
existing `markdown_parser` — which already returns `body` verbatim — needing only a new
*fence reader*, not a parser rewrite). One claim:

```yaml
- id: clm_2026-05-05_009              # stable: clm_<learned-date>_<seq>
  text: "Cicada uses sqlite-vec for its derived semantic index."   # the embedded string
  subject: cicada                     # the entity id this file is about (defaults to file stem)
  predicate: uses                     # OPEN verb; normalized against _predicates.yaml by Sleep
  object: sqlite-vec                  # entity-id OR literal
  object_kind: node                   # node | literal
  observer: agent                     # agent | rodrigo | external:<name>   (Honcho graft)
  context: engineering                # engineering|family|philosophical|career|cross|general (OPEN)
  epistemic: explicit                 # explicit | deductive | inductive | abductive  (drives decay)
  source_trust: user_stated           # user_stated | agent_extracted | agent_reflected | external
  confidence: 0.95                    # 0..1, ORTHOGONAL to source_trust
  valid_from: '2026-05-05'            # true-in-world start
  valid_to: null                      # null = currently valid; a date = closed/superseded
  superseded_by: null                 # claim id that replaced this one
  supersedes: null                    # claim id this one closed
  source_episodes: [ep_2026-05-05_003]
  premises: []                        # for deductive/inductive: claim-ids this was derived from
  authored_by: gpt-5.4-mini           # also a Cicada-Author git trailer
```

**Why claims-in-the-page, not a separate `facts/` or `beliefs/` store.** All three rivals to Evolved
proposed a new primary directory and were docked for it (C6=4–7, C8=3–6) by the pragmatics judge; the
belief-perspective judge separately flagged PBM's `beliefs/` + `facets/` dual-write and `generated: true`
cards as a real solo-dev footgun ("Obsidian invites hand-editing; the overwrite contract silently
destroys the edit"). Co-locating claims in the page they describe keeps **one file per subject = one
source of truth = one `git blame`**, keeps Obsidian rendering, and makes the legacy page a valid CCL
page for free. We get the fact judge's "claim is the retrieval unit" win *without* the migration/maintenance
cost that sank his actual winner (TFG, C6=4/C8=4).

### Edges, facets, context

- **Facets** are `## facet: <name>` sub-sections in the entity body, and `context:` on each claim.
  One `Rodrigo` page carries engineering / family / philosophy claims; the index stores **one vector
  per facet** plus one per-claim vector, so engineer-Rodrigo and family-Rodrigo are distinct retrieval
  targets with **no context collapse and no entity cloning**. *Correction to Evolved:* faceting is **not**
  opt-in-by-heuristic (the expressiveness judge's disqualifying objection — "context collapse is the
  default, de-collapse is opt-in, for a user whose central premise is multi-context identity"). Instead,
  **every claim carries a `context` field always** (default `general`); facet *sub-sections* are rendered
  whenever a subject has claims in ≥2 contexts. Multi-context identity is the default, not a special case.
- **`(observer, context, subject)` is the conceptual key** (PBM's C2=10 graft), expressed as three claim
  fields rather than a directory fork. `observer` separates "who holds this belief" from "how much to
  trust it" — the pragmatics judge's explicit recommended graft from PBM, "Honcho's (observer, observed)
  win at near-zero cost." `external:<name>` makes "Rodrigo *read* this" honestly distinct from "Rodrigo
  *asserts* this."
- **`graph_edges.yaml`** keeps its `{source, target, label}` shape (the d3 `/graph` view is untouched);
  edges gain optional `context`, `valid_from`, `valid_to`, `claim_id`. Sleep regenerates valid-only edges
  from claims — the RDF named-graph 4th dimension at zero infra.

### Temporal change + contradiction handling (mechanical, not LLM-judged)

This is the **decisive graft from TFG**, and it patches the shared weakness the expressiveness judge
called out in *both* PBM and Tiered ("they oversell C3 by hiding the detection problem… contradiction
*detection* is a fragile prompt; if missed, two contradictory beliefs both get indexed, reintroducing
the exact failure they claim to eliminate").

Sleep **Stage 3 becomes a mechanical invalidate-and-supersede pass**:
1. Normalize the new claim's predicate against `_predicates.yaml` (canonical-synonym map).
2. Query existing **valid** claims with the **same `(subject, predicate, context)`** key.
3. If found and the relation is single-valued (the LLM is asked once: "can both hold at once?"), stamp the
   old claim `valid_to = new.valid_from`, `superseded_by = new.id`; set `new.supersedes = old.id`.
   **Nothing is deleted.** Multi-valued relations (`uses`, `relates-to`) coexist.
4. The closing is a one-line YAML edit → `git blame` on the `valid_to:` line gives the exact commit,
   episode, and authoring model that retired the belief.

The `_predicates.yaml` normalization is itself the thing the retrieval judge flagged as TFG's one
correctness risk ("if synonym normalization drifts, the contradiction key silently fails"). **Mitigation
is mandatory, not optional:** Stage 5 emits a `normalization-audit` nudge whenever a new predicate is
auto-folded into an existing canonical form, so a human can catch a bad merge before it corrupts the key.

### Confidence + provenance

- **`confidence` ⊥ `source_trust`** (two orthogonal axes), per the epistemics research — a user-stated
  fact decays slowly even when uncertain; an agent-reflected generalization decays fast even when confident.
- **Decay is a per-epistemic-status lookup table** (PBM graft, the retrieval judge's explicit recommended
  graft): `asserted/explicit → 0.02`, `deductive → 0.05`, `inductive → 0.10`, `abductive → 0.20` per cycle,
  multiplied by a `source_trust` factor (`user_stated 0.3×`, `agent_extracted 1×`, `agent_reflected 1.5×`,
  `external 1×`). This removes a stored per-claim `decay_rate` field (one fewer thing the LLM must set
  correctly) and makes abductive cross-context guesses self-prune in ~10 cycles unless reinforced.
- **Per-claim provenance**: `source_episodes`, `premises`, `authored_by` (→ existing `Cicada-Author`
  git trailer). `/ask` citations point at a `claim_id` with its valid-window and trust class — the most
  auditable answer the retrieval judge identified.

### Procedural / preference memory (hard split)

The **Tiered-Cognitive graft** the pragmatics judge recommended ("the cleaner procedural model"), kept
as files, not a three-tier directory architecture:
- **Preferences** (`_preferences.md`, a single always-injected block): soft behavioral constraints
  ("split FastAPI routers by domain"). **Never similarity-gated** — injected as a compact block at
  conversation start (the retrieval judge's "preferences are behavioral priming that must fire
  unconditionally"). Each carries `scope:` tags and a `superseded_by` field for contradiction-retirement.
- **Procedures** (`_procedures/<name>.md`, task-triggered): reusable step-lists with a `trigger:`
  description and `verified_in:` episode citations (Voyager-style). Embedded on their trigger in the
  `claims` index, retrieved only when the query is task-shaped.

Both supersede on change via the same bi-temporal discipline — solving the preference-change-detection
gap all three production frameworks (mem0/cognee/Letta) fail.

### Candidates replace the promotion gate

`candidates/<slug>.md` is a slim, *human-readable, retrievable* entity stub with `status: candidate` and
a continuous `activation` score (`w_r·recency + w_f·log(mention_count) + w_i·importance +
w_c·max_contextual_similarity`). Promotion is `activation ≥ θ_promote` (default 0.5, **ablatable in
Table 2** — preserving the thesis's existing ablation harness); archive is `activation < θ_archive`.
The hard "count-to-2" rule is gone; a single substantive conversation can promote on importance alone, ten
trivial mentions never will. The legacy `pending_entities.jsonl` + `vec_pending` are retained as the
back-compat back-end so nothing breaks on day 0.

### Index changes (additive, within the existing `vec_<kind>`/`meta_<kind>` machinery)

Confirmed against `vector_index.py`: per-kind `vec0` virtual table + rowid-aligned `meta_<kind>` table
with a JSON metadata blob, built by `_rebuild_table`, searched by `_knn`. Three additive changes:
1. **New kind `claims`.** One row per *currently-valid* claim (`valid_to IS NULL`), embed = `claim.text`,
   metadata = `{claim_id, subject, predicate, object, observer, context, epistemic, source_trust,
   confidence, valid_from}`. Invalidated claims are **not** indexed (audit lives in git + the file).
2. **Facet-aware entity rows.** A page with facets indexes one row per facet sub-section (`metadata.facet`)
   instead of one whole-page row; pages without facets keep their single row (unchanged).
3. **Metadata filters** on `context` / `source_trust` / `valid_to` after KNN — exactly the existing
   post-filter pattern in `search_entities`. We add **at most one new kind**, not five (Tiered's flagged tax).

The index stays **fully derived and disposable**: `rebuild` reads markdown (claims + facets) and
regenerates everything. The DB is never migrated — it is deleted and rebuilt.

### Retrieval / `/ask` integration

`ask_service.answer_query` keeps its exact shape (`answer / confidence / citations / gaps`) and its
`retrieve_fn` dependency-injection seam (confirmed: defaults to `search_entities`). We swap the default
`retrieve_fn` to a **claim-first retrieve**:
1. **Always-on prelude (not gated):** inject `_preferences.md` (scope-matched) as a compact block — "who
   is Rodrigo right now."
2. **KNN over the `claims` kind** + facet rows; SQL post-filter `valid_to IS NULL` by default (lift it
   only when the query is historical, "what did Cicada use *before* sqlite-vec"); optional `context`
   boost when the MCP client supplies a hint. **Defensive default:** if no context hint is supplied,
   retrieval is context-blind (no down-weighting) — this avoids PBM's silent-degradation failure where a
   missing/wrong caller hint makes retrieval *worse* than a flat index.
3. **Score** = `cosine × confidence × recency` (Generative-Agents three-signal), drop invalidated claims.
4. **1-hop graph expansion** via `subject`/`object` index lookups for relational depth.
5. **Citations** point at `claim_id` + valid-window + `source_trust` + `observer`. `gaps` honestly reports
   "I hold only a superseded claim for X."

MCP Bookworm gains one tool: `get_facet(subject, context)` → that context's valid claims (the Honcho
user-model injection that hit 90.4% accuracy at 5% context cost).

---

## Worked examples

### 1. Faceted self (engineer-Rodrigo vs family-Rodrigo, no collapse)

One `entities/rodrigo.md`, `## facet: engineering` and `## facet: family` sections, claims:

```yaml
- id: clm_..._01
  text: "In engineering, Rodrigo values shipping fast and iterating."
  subject: rodrigo  predicate: values  object: shipping-speed
  observer: agent  context: engineering  epistemic: inductive  source_trust: agent_extracted
  confidence: 0.8  valid_from: '2025-09-01'  valid_to: null
- id: clm_..._02
  text: "With family, Rodrigo values being present and unhurried."
  subject: rodrigo  predicate: values  object: presence
  observer: agent  context: family  epistemic: inductive  source_trust: user_stated
  confidence: 0.9  valid_from: '2025-09-01'  valid_to: null
- id: clm_..._03                                  # Stage-4 cross-context abductive bridge
  text: "Across contexts Rodrigo strips to the essential — fast where it ships value,
          slow where presence is the value."
  subject: rodrigo  predicate: optimizes-for  object: the-essential
  observer: agent  context: cross  epistemic: abductive  premises: [clm_..._01, clm_..._02]
  confidence: 0.5  source_trust: agent_reflected  valid_from: '2026-03-01'  valid_to: null
```

No contradiction (different `context`). The index stores a `rodrigo/engineering` vector and a
`rodrigo/family` vector. "What does Rodrigo value when building software" hits engineering; "what matters
to Rodrigo about home" hits family. Claim `_03` is the **abstract cross-link Rodrigo wants** — abductive,
low-confidence, flagged as a clarification nudge ("Does this resonate?"), and it self-prunes in ~10 cycles
(decay 0.20) unless a later episode reinforces it. This is the expressiveness judge's exact rationale for
crowning PBM, delivered without a `facets/` directory.

### 2. A belief that changes: Postgres → SQLite

Day 1 in `entities/cicada.md`'s claims fence: `{predicate: uses, object: postgres, context: engineering,
valid_from: 2026-01-15, valid_to: null}`. Day 110, an episode says "switched the index to sqlite-vec."
Stage 3 keys on `(cicada, uses, engineering)`, finds the open Postgres claim, single-valued → closes it:

```yaml
- id: clm_2026-01-15_002
  predicate: uses  object: postgres  context: engineering
  valid_from: '2026-01-15'  valid_to: '2026-05-05'  superseded_by: clm_2026-05-05_009
- id: clm_2026-05-05_009
  predicate: uses  object: sqlite-vec  context: engineering
  valid_from: '2026-05-05'  valid_to: null  supersedes: clm_2026-01-15_002  confidence: 0.95
```

`/ask "what's Cicada's vector store"` → SQLite (only the open claim is indexed). `/ask "what did Cicada
use before SQLite"` → finds the closed claim (in file + git). `git blame` on the `valid_to:` line → the
exact Sleep commit and model that retired the Postgres belief. Mechanical, lossless, zero LLM judgment at
read time — the retrieval and expressiveness judges' shared top criterion (C3=10).

### 3. A preference

Rodrigo corrects the agent's FastAPI scaffolding. Stage 4 writes to `_preferences.md`:

```markdown
- id: pref_017  scope: [coding, fastapi, python]  status: active
  source_trust: user_stated  confidence: 0.85  source_episodes: [ep_2026-02-10_004, ep_2026-03-02_011]
  Rule: Split FastAPI routers by domain (one module per resource); services thin; models separate.
```

Always injected at conversation start (never similarity-gated). If Rodrigo later says "one big router is
fine for small services," Stage 3 writes a new preference with `supersedes: pref_017` and sets the old to
`status: superseded` — the agent stops applying the stale rule. (Task-shaped *procedures* with step-lists
live in `_procedures/` and are trigger-retrieved instead.)

### 4. A saved media item

A saved talk/RSS article becomes an entity with a **soft type** the closed enum never allowed, plus claims
whose `observer` is the source:

```yaml
---
name: "Karpathy — Intro to LLMs (talk)"
type: media            # SOFT type: not in the core set, accepted verbatim, stored as an opaque index tag
source_trust: external  url: https://...  created: '2026-06-01'
---
```claims
- id: clm_2026-06-01_021
  text: "Karpathy frames an LLM as a lossy compression of its training corpus."
  predicate: claims  observer: external:karpathy-talk  context: engineering
  epistemic: explicit  source_trust: external  confidence: 0.6
  valid_from: '2026-06-01'  valid_to: null  source_episodes: [ep_2026-06-01_002]
```

`/ask` can cite the claim while signalling `observer: external:karpathy-talk` + `source_trust: external`
— the agent attributes it to Karpathy, not to Rodrigo. New media/problem/open-question kinds need **no
schema change** (C7).

---

## Why this beats the alternatives

The three judges crowned three *different* winners under their lenses — TFG (retrieval), PBM
(expressiveness), Evolved (pragmatics). CCL is the configuration that takes the **pragmatics winner as the
base** (because C6/C8 are existential for a solo dev on a live 1,882-page store) and **imports exactly the
mechanisms the other two judges rewarded**, so it sits at-or-near the top on every lens at once:

| Criterion | Evolved | TFG | PBM | Tiered | **CCL (this)** | Why CCL ≥ each |
|---|---|---|---|---|---|---|
| C1 retrieval | 8 | **9** | 8 | 8 | **9** | per-claim index = TFG's homogeneous unit, *one* new kind not five; context-blind default avoids PBM's hint-degradation |
| C2 identity | 7 | 8 | **10** | 8/9 | **9** | `(observer,context,subject)` keying + facet-by-default fixes Evolved's facet-by-heuristic flaw (the expressiveness judge's disqualifier) |
| C3 temporal | **10** | **10** | 9 | 9 | **10** | TFG's mechanical predicate-keyed close, *with* mandatory normalization-audit nudge (the judge's required fix) |
| C4 provenance | 8/9 | **9** | 8/9 | 9 | **9** | claim-id citations + valid-window + `observer` + Cicada-Author trailers |
| C5 procedural | 7/8 | 8/9 | 8/9 | **9/10** | **9** | Tiered's preference/procedure split (always-injected vs trigger-gated), as files not a third tier |
| C6 migration | **10** | 4/6/7 | 6/7 | 4/6 | **10** | legacy page *is* a valid CCL page; $0 required, byte-reversible — Evolved's whole point, kept intact |
| C7 extensibility | 8 | **9** | 8/9 | 8 | **8/9** | soft types + open predicates + `_predicates.yaml` normalization (graft) |
| C8 simplicity | 6 | 4/5 | 5/6 | **3** | **6** | claims-in-page (no new primary store, no `facets/` dual-write, no 5 kinds) — the lowest surface among expressive candidates |

**The grafts are each judge-justified, not a grab-bag:**
- *Mechanical predicate-keyed contradiction from TFG* — the expressiveness judge's highest-leverage
  robustness graft onto PBM, and the fix for the C3 "detection is a fragile prompt" flaw shared by PBM and
  Tiered. We take the mechanism but **not** TFG's separate `facts/` store (its C6=4/C8=4 sinker).
- *`observer` field + `(observer,context,subject)` keying + per-epistemic decay table from PBM* — the
  retrieval judge's *and* pragmatics judge's explicitly recommended grafts ("Honcho's (observer,observed)
  win at near-zero cost"; "per-epistemic-status decay as a lookup table is strictly better for retrieval
  trust"). We take these but **not** PBM's `beliefs/` + `facets/` dual-write or `generated: true`
  hand-edit footgun.
- *Preference/procedure hard split with always-injection from Tiered* — the retrieval judge's and
  pragmatics judge's recommended graft ("the cleaner procedural model"). We take the split as **two files**,
  **not** Tiered's three-directory / five-index-kind architecture (its C8=3 floor).
- *Evolved's lazy, byte-reversible, $0-required migration* — the pragmatics judge's decisive C6=10, taken
  as the chassis and never compromised.

**What we explicitly reject and why:** a pure claim-DAG with no entity pages (loses Obsidian + C6); a
separate primary `facts/`/`beliefs/` directory (every judge docked it); a `facets/` directory (dual-write
with `context:`, the pragmatics judge's redundancy flag); five index kinds (Tiered's merge-correctness
tax); facet-by-heuristic (the expressiveness judge's disqualifier for *this* multi-context user);
caller-context-hint-dependent retrieval as the *default* (PBM's silent-degradation flaw).

---

## Migration plan

From the current **1,882 typed entity pages + graph_edges.yaml + episodes**. Phased on the existing M-numbered
milestone scheme; every wave runs first in a `/tmp/cicada_bench_*` workspace per the benchmark safety
rails, never mutating live `memory/` until validated. **Core principle: a legacy page is already a valid
CCL page; no bulk LLM pass is *required* to ship.**

**M5a — Code, no data change (~2–3 days eng, $0 LLM).** Add a `parse_claims(body)` / `write_claims()`
fence reader to `markdown_parser` (returns `[]` if absent; `write` already round-trips body). Add the
`claims` vec0 kind to `vector_index.py` (`index_claims` / `search_claims`, mirroring `index_entities`).
Teach the entity embed step to emit per-facet rows when `## facet:` sections exist. Add `candidates/` as an
alias front-end over the existing pending store. Create empty `_preferences.md`, `_procedures/`,
`_predicates.yaml`. **All additive; legacy pages behave exactly as today.**

**M5b — Mechanical frontmatter backfill ($0 LLM, one commit).** A pure-Python script stamps
`schema_version: 1`, `source_trust: agent_extracted` (these pages were LLM-written), and an initial
`activation` (from `last_referenced` + `len(source_episodes)`) on all 1,882 pages. Convert every
`graph_edges.yaml` stanza to a seed claim **deterministically** (`{subject: source, predicate: label,
object: target, context: general, source_trust: agent_extracted}`) — this backfills the relational layer
for **free** (TFG's free-conversion insight). Rebuild the index — with no prose claims yet, identical to
today's per-page index (a few cents of embeddings, $0 on local EmbeddingGemma).

**M5c — Stage-3/4 rewrite + retrieval swap (eng, $0 LLM).** Make Sleep Stage 3 the mechanical
invalidate-and-supersede pass (predicate-keyed). Add Stage-4 preference/procedure extraction + cross-context
abductive bridge pass. Add the mandatory `normalization-audit` nudge. Swap `ask_service`'s default
`retrieve_fn` to claim-first (keep `search_entities` as graceful-degrade fallback). Run `benchmarks.run_table1`
on both paths; the claim path should win on temporal/contradiction questions and tie-or-better on recall.

**M5d — Lazy claim extraction (amortized, optional, $0 required).** Pages are **not** mass-converted.
A page upgrades to `schema_version: 2` (prose body parsed into a claims fence) **only when Sleep next
touches it** — extraction was running on that page anyway, so the marginal cost is one extra structured
field in the prompt. Cold pages stay legacy forever at no cost. **Optional full backfill for the thesis
Results:** 1,882 pages × ~1 cheap structured call. Bodies are short (confirmed: the sampled page is one
~50-word sentence with wikilinks) — at ~600 in / ~400 out tokens on a mini model, ≈ **\$2–6 total**, the
magnitude of one Sleep cycle, runnable overnight. **This is the only LLM cost, and it is optional.**

**M5e — Facets where they pay (cents).** Faceting is applied to the genuinely multi-context entities
(`rodrigo`, plus ~5–20 others surfaced by claims spanning ≥2 contexts) via one LLM pass each to split the
body into `## facet:` sections. Most pages stay single-facet (`context: general`) — but *every claim still
carries a context*, so multi-context identity is the default representation, not an opt-in.

**Rollback at any milestone:** delete the `claims` fences + `facets:` keys + the new `_*` files → every
page is byte-compatible with today's model; the index rebuild regenerates the old shape. No lock-in, no
all-or-nothing bet. This is the ratchet property the pragmatics judge required.

---

## Risks & unknowns

1. **Predicate normalization is the one correctness-critical dependency** (the retrieval judge's TFG fatal
   flaw, inherited with the graft). If `_predicates.yaml` mis-folds synonyms (e.g. `uses` into `chose-over`),
   the `(subject, predicate, context)` contradiction key silently fails and two contradictory "valid" claims
   both get indexed. **Mitigation (mandatory, not optional):** every auto-fold emits a `normalization-audit`
   nudge; start with a hand-seeded conservative map and grow it only via audited Sleep proposals.
2. **Stage-3 single-valued vs multi-valued judgment** ("can both hold at once?") is still one LLM call per
   contradiction candidate. A wrong "yes" leaves a stale claim open; a wrong "no" wrongly closes a coexisting
   fact. Lower-stakes than read-time judgment (it is dated, sourced, and reversible in git), but it is the
   residual LLM dependency in an otherwise-mechanical pass. Surface borderline calls as conflict nudges.
3. **Cross-context abductive bridges can pollute** if decay is mis-tuned. The 0.20 abductive decay should
   self-prune unreinforced guesses in ~10 cycles; validate this empirically before trusting it (it is
   directly ablatable in the Table-2 harness alongside the promotion threshold).
4. **Activation scoring replaces a clean, ablation-friendly binary gate with a continuous score with four
   weights.** This is more expressive but harder to reason about; keep `θ_promote` and the four weights in
   one config and ablate them in Table 2 so the thesis can defend the choice empirically.
5. **`observer` may be under-used in practice.** If the extractor defaults everything to `observer: agent`,
   the Honcho win evaporates. Worth a deliberate prompt rule that external sources and direct user assertions
   get the correct observer — and a quick audit after the first real Sleep cycle.
6. **Facet assignment quality is LLM-bound.** Even though *every* claim carries a context, the *value* the
   extractor picks can be wrong. Mitigate by keeping the context set small and named, and by making a wrong
   context a cheap, git-visible, user-correctable edit rather than a structural fork.

---

## Decisions Rodrigo must make before build

1. **Optional full claim backfill, or lazy-only?** Lazy ($0) keeps cold pages legacy forever; a full
   ~\$2–6 backfill gives a uniform store and cleaner thesis Results numbers. *Recommendation: run the full
   backfill once for the Results chapter, ship lazy as the steady-state behavior.*
2. **Context vocabulary.** Lock the small named set now (`engineering | family | philosophical | career |
   cross | general`?) or let it stay fully open. *Recommendation: a small named core + open tail, with a
   normalization nudge — open sets drift (the C2 weakness every candidate shared).*
3. **`observer` cardinality.** Just `agent | rodrigo | external:<name>`, or richer? *Recommendation: start
   with those three; `external:<name>` is the high-value case (media/RSS provenance).*
4. **Decay constants.** Accept the proposed per-epistemic table (0.02/0.05/0.10/0.20 × trust factor) or
   tune first? *Recommendation: accept as defaults, expose in config, ablate in Table 2.*
5. **Promotion threshold + activation weights.** Pick the starting `θ_promote` (0.5?) and the four weights.
   *Recommendation: start at 0.5 with equal weights, ablate.*
6. **Does the thesis narrative keep "biologically-inspired Awake/Sleep" framing?** CCL maps cleanly onto it
   (episodic capture → claim consolidation → bi-temporal semantic store), but the new mandate says don't
   preserve anything *merely* for thesis differentiation. *Recommendation: keep the framing — it is now
   load-bearing engineering, not decoration.*
7. **Preferences as a single file vs many.** `_preferences.md` (one always-injected block) vs one file each.
   *Recommendation: one block — always-injection wants a single compact read.*
8. **Do you want the d3 `/graph` view to show facets/contexts** (e.g. context-colored edges), or stay
   entity-level for now? *Recommendation: defer; `graph_edges.yaml` already carries optional `context`, so
   this is a later UI-only change.*
