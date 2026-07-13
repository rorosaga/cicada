# D2 Final Architecture

**Status:** Definitive — supersedes `d2-recommendation.md` (the migration-optimized "Cicada Claim Layer").
**Author of synthesis:** D2 synthesis agent, 2026-06-17.
**Mandate:** Rodrigo's 2026-06-17 re-weighting — *best architecture, not cheapest migration; maximize companion-app demonstrability; inline transclusion as a first-class feature.*

---

## ADDENDUM — Reconciliation (2026-06-17, CONFIRMED, AUTHORITATIVE)

This addendum **overrides** the "read-only generated cards + separate authoritative
`claims/<subject>.claims.yaml` store" decision below. Where this section conflicts with the rest of
the doc, **this section wins.** Everything else (the claim *schema*, observer/context/epistemic/trust
axes, bi-temporal contradiction, transclusion, the five demo surfaces, the decay table, candidates) is
**kept** — only the *ownership* model changes.

1. **Editable rich pages are the SOURCE OF TRUTH.** Entity pages are Wikipedia-article-like: rich,
   structured, human- **and** agent-readable, arbitrarily long (size is fine). They are the human edit
   surface, editable two ways — (a) inbox clarification, (b) direct markdown edit. **Pages are NOT
   read-only or "generated"; we drop `generated: true` and the read-only-card inversion.**

2. **Claims live IN the page; the claim index is DERIVED (parsed).** Claims are a structured,
   parseable, human-inspectable block inside the page (recommended: a fenced ` ```claims ` YAML list),
   carrying the full schema (`observer/context/epistemic/source_trust ⊥ confidence/valid_from/valid_to/
   superseded_by/supersedes/premises/source_episodes/authored_by/origin`). A parser extracts them into
   the addressable `claims` vector-index kind that powers every demo (observer graph, belief timeline,
   transclusion, perspective filter, provenance chip). **We DROP the separate `memory/claims/` directory
   as an authoritative store** — the page's claims block is authoritative; the index is derived and
   disposable. This restores Cicada's founding invariant: *markdown+git is the source of truth;
   everything else (index, demos) is rebuilt from it.* Page edited → claims re-parsed → index rebuilt.

3. **Human edits are protected provenance (trust-based; MERGE, never clobber).** A hand-edit or
   clarification ⇒ `source_trust: user_stated`, `observer: rodrigo`, `origin: manual_edit | clarification`.
   Reconciliation rules the Sleep cycle MUST enforce:
   - (a) Sleep **never silently overwrites a `user_stated` claim with an `agent_extracted` one.**
   - (b) **Only a *newer human-sourced* claim supersedes a human claim** — so a human changes a memory
     by *clarifying/conversing* (a high-trust supersede), which is the **preferred** path; routine
     extraction cannot trample it.
   - (c) Page augmentation is **section-aware merge** — human-authored prose/sections are preserved, not
     regenerated away. (Builds on the v2 `entity_body.py` section-aware merge.)
   - (d) Direct hand-editing is supported and respected; the only way a human claim is "overwritten" is
     as the *indirect* result of the human themselves changing it via clarification/conversation.

4. **`origin` (backlog G9) is a first-class claim field**, sibling to `observer`/`source_trust`: which
   harness/surface a belief came from (`claude-code | codex | openclaw | manual_edit | clarification |
   chatgpt-export | …`). Distinct from `authored_by` (which *model* wrote it, M3).

5. **Worked example — Prof. John recommends two websites (must be captured):**
   - A claim records that **`external:john` recommended** the two sites — agents can pinpoint John as the
     source (`predicate: recommended`, `observer: external:john` / a `john --recommended--> site` edge),
     not just that the sites exist.
   - The two websites become **`media`/bookmark subjects** (existing media ingestion; future bookmark
     folders).
   - **Bidirectional inline transclusion:** John's page inline-embeds the sites (`![[robotics-conf-list-1]]`)
     and/or each site's page inline-references John as recommender — the recommendation is visible from
     both directions.

6. **Sleep link-enrichment subagent (new Sleep step).** When a saved link has no description from the
   conversation, a small Sleep subagent fetches the URL, reads what the site is about, and writes a
   description claim/summary so the link is retrievable when the context matters later. (Extends
   `media_ingestor`'s Open-Graph enrichment into a "scour + summarize" pass; pairs with G10's big-model
   extraction.)

7. **Build-plan impact:** M5a builds the **in-page claims parser/writer** (the ` ```claims ` block in
   `markdown_parser`) + the derived `claims` index kind in `vector_index.py` — **not** a separate
   `claims/` directory. M5b seeds claims **into pages**. M5e Stage-5 becomes **section-aware
   merge-augment of pages** (preserving human edits) rather than "regenerate read-only cards," and Stage-3
   contradiction respects the trust rules in (3). Demo surfaces (M5c) read the derived index/endpoints
   exactly as specified. M5d big-model extraction (G10) writes claims into pages.

*Read the rest of this doc with this addendum applied: wherever it says "separate `claims/` store" or
"read-only generated card," substitute "in-page claims block in an editable page + derived index."*

---

## The decision, in one paragraph

Cicada adopts the **Cicada Perspectival Claim Graph (CPCG)**: a **separate, normalized, first-class
claim store** (`memory/claims/<subject>.claims.yaml`) becomes the source of truth for *belief*, and
the 1,882 entity pages are **demoted to deterministically-generated, transcludable cards** projected
from it. The atom of memory is a **claim** keyed by `(observer, context, subject)`, bi-temporally
valid (`valid_from`/`valid_to`), epistemically typed (`explicit | deductive | inductive | abductive`),
trust-classed (`source_trust ⊥ confidence`), individually embedded as the **primary** vector-index
kind, and contradiction-handled by TFG's **mechanical predicate-keyed invalidate-and-supersede**. On
top of this sits a designed **inline-transclusion layer** (`![[subject]]`, `![[subject#facet]]`,
`![[claim:id]]`, `![[subject?context=engineering]]`) resolved server-side and rendered inline in the
companion app. The d3 graph is upgraded from colored dots to an **observer-colored, time-scrubbable,
contradiction-overlaid belief graph**. This is **Perspectival-Belief-Memory promoted to the
recommendation**, fused with **Temporal-Fact-Graph's** per-subject file layout + mechanical
contradiction key, plus a new transclusion layer and an explicit app-demonstrability surface. The
honest price is a **one-time ~$2–6 LLM extraction pass** over the existing pages plus a real schema
change touching all five Sleep stages — a cost the prior recommendation refused to pay and the new
mandate explicitly accepts.

---

## What changed from the CCL recommendation and why

The prior recommendation (**CCL**) was a disciplined, correct answer *to a different question*. It
asked: "what is the most expressive belief layer I can add **without paying any migration cost**?" Its
load-bearing move was keeping claims *inside* the entity-page body (a ` ```claims ` fence), purely so
that an untouched legacy page would be "a valid CCL page for free" — scoring a decisive **C6=10**
(migration) and **C8=6** (simplicity). Every architecturally cleaner option (a separate `claims/` /
`facts/` / `beliefs/` store) was rejected *only* because it cost a migration pass.

**The new mandate inverts the weights:**

| Criterion | Old weight | New weight | Consequence |
|---|---|---|---|
| C6 migration ease | **existential** | **LOW** (one-time cost OK) | the in-page-claims compromise stops paying for itself |
| C8 simplicity | high | secondary | a separate store + renderer is acceptable surface |
| C2 observer/context identity | high | **HIGH** | observer must be *structural*, addressable, pivotable |
| C3 temporal/contradiction | high | **HIGH** | per-claim bi-temporal blame, not per-page-fence |
| C9 overall | high | **HIGH** | — |
| **C10 companion-app demonstrability** | — | **HIGH (NEW)** | the architecture must make killer demos possible |
| **C11 inline-transclusion fit** | — | **HIGH (NEW)** | a designed embed layer, not an afterthought |

Under the old weights CCL was correct. Under the new weights it is dominated. **The single biggest
upgrade is moving truth out of the entity-page body into a separate normalized store.** That one
change — paid for by the now-permitted one-time extraction pass — is what makes `(observer, context,
subject)` a *real addressable, pivotable primary key* instead of a YAML field buried in prose, and
that is the precondition for every demo the mandate asks for:

- **Observer becomes a graph color and a pivot axis**, not metadata the app can't see. The app can
  render a literal *who-believes-what* graph (agent's-Rodrigo vs Rodrigo's-self-assertion vs an
  external source) only if the observer is addressable outside a page body. (C2, C10.)
- **A claim becomes a first-class object the app can link to, transclude, and time-scrub.**
  `![[claim:clm_id]]` and a per-belief timeline only make sense if a claim has a stable home and id
  outside prose. (C10, C11.)
- **One write touches one small YAML record, not a page-body fence**, so contradiction, decay, and
  supersession are clean per-claim git diffs and `git blame` is per-claim. (C3, C4.)

**What CPCG keeps from CCL unchanged** (these survived the re-weighting and remain good): the claim
schema fields (`epistemic`, `source_trust ⊥ confidence`, `valid_from`/`valid_to`,
`superseded_by`/`supersedes`, `premises`, `authored_by` → `Cicada-Author` git trailer); the mechanical
predicate-keyed Stage-3 invalidate-and-supersede with a **mandatory** `_predicates.yaml`
normalization-audit nudge; the per-epistemic-status decay lookup table × source-trust factor;
`candidates/` activation-score promotion replacing the count-to-2 gate; the always-injected
`_preferences.md` block + trigger-gated `_procedures/`; soft/open types; and the contract that **the
index is fully derived and disposable, rebuilt from markdown.**

**The one thing CPCG explicitly inverts vs CCL:** `claims/` is authoritative; `entities/*.md` is a
*projection*. A page can always be rebuilt from `claims/`. We mitigate PBM's only real footgun
(a human hand-edits a `generated: true` card and Sleep silently overwrites it) by routing **all**
human edits through the app/nudges → claim writes; the card is read-only render. The two places humans
author prose — `_preferences.md` and `_procedures/` — are *not* generated and never overwritten.

---

## The model

> Grounded against the real codebase on `feat/memory-evolution`: services in `api/services/`
> (`vector_index.py`, `ask_service.py`, `entity_extractor.py`, `entity_resolver.py`,
> `conflict_resolver.py`, `skill_extractor.py`, `entity_body.py`, `graph_builder.py`,
> `markdown_parser.py`, `git_service.py`, `sleep_cycle.py`), routers in `api/routers/`, the
> 5-stage `sleep_cycle.run()`, and the SwiftPM app at `app/CicadaApp/Sources/CicadaApp/` with the d3
> graph at `Resources/graph/graph.js`.

### On-disk data model

```
memory/
├── claims/                         ← NEW PRIMARY STORE. Source of truth for belief.
│   ├── rodrigo.claims.yaml         ← all claims whose subject is `rodrigo`, as a YAML list
│   ├── cicada.claims.yaml          ← per-subject file ⇒ git blame is per-subject belief history
│   └── ...                         ← ~1,882 files, one per subject (bounded, glob-friendly)
├── entities/                       ← KEPT but DEMOTED to generated cards (Obsidian still renders)
│   ├── rodrigo.md                  ← `generated: true`; body = render of valid claims, by facet
│   └── ...                         ← transclusion targets: ![[rodrigo#engineering]]
├── episodes/                       ← UNCHANGED. Raw, immutable, append-only. + importance: at Sleep.
├── candidates/                     ← shadow subjects w/ activation score (replaces the 2-mention gate)
│   └── gaka-chu-research.md
├── _preferences.md                 ← always-injected behavioral block (human-authored prose OK)
├── _procedures/                    ← trigger-gated reusable step-lists (human-authored prose OK)
│   └── fastapi-repo-layout.md
├── _predicates.yaml                ← canonical predicate-synonym map (chose ≈ selected → chose)
├── graph_edges.yaml                ← KEPT, now a DERIVED projection: Sleep regenerates valid-only
│                                     edges from claims; gains observer / context / valid_* / claim_id
├── leann/ → vector_index.db        ← sqlite-vec; PRIMARY kind becomes `claims`; facet rows on entities
└── nudges/ clarifications/ inbox/ hubs/ sources/   ← UNCHANGED
```

**Load-bearing inversion vs CCL:** `claims/` is authoritative, `entities/*.md` is a projection. If a
page is lost, Sleep regenerates it from `claims/`. This is PBM's ownership inversion, which CCL
rejected only to save migration.

### The atom: a claim

`memory/claims/cicada.claims.yaml`:

```yaml
subject: cicada
subject_name: Cicada
claims:
  - id: clm_2026-05-05_009              # stable: clm_<learned-date>_<seq>
    text: "Cicada's semantic index is built on sqlite-vec."   # the embedded string
    subject: cicada
    predicate: uses                     # OPEN verb; normalized vs _predicates.yaml at Sleep Stage 2
    object: sqlite-vec
    object_kind: node                   # node | literal
    observer: agent                     # agent | rodrigo | external:<name>   (PRIMARY KEY dim)
    context: engineering                # engineering|family|philosophical|career|cross|general (OPEN)
    epistemic: explicit                 # explicit|deductive|inductive|abductive  (drives decay)
    source_trust: user_stated           # user_stated|agent_extracted|agent_reflected|external
    confidence: 0.95                    # 0..1, ORTHOGONAL to source_trust
    valid_from: '2026-05-05'            # true-in-world start
    valid_to: null                      # null = currently valid; a date = closed/superseded
    superseded_by: null                 # claim id that replaced this one
    supersedes: clm_2026-01-15_002      # this claim closed the Postgres one
    recorded_at: '2026-05-05'           # learned-by-system (git commit is the canonical audit anchor)
    source_episodes: [ep_2026-05-05_003]
    premises: []                        # for deductive/inductive: claim-ids this was derived from
    authored_by: gpt-5.4-mini           # → Cicada-Author git trailer; or `user` for manual edits
```

**`(observer, context, subject)` is the primary key** (Honcho's `(observer, observed)` graft,
generalized with `context`). `observer == subject` is a self-belief; `observer: agent, subject:
rodrigo` is the agent's model of Rodrigo; `observer: external:karpathy-talk` is something a source
asserted. **The same subject carries contradictory claims without conflict if observer or context
differs** — engineer-Rodrigo "values speed" vs family-Rodrigo "values presence"; agent-believes-X vs
Rodrigo-asserts-Y. This is C2's home turf, now the recommendation.

**Two orthogonal trust axes** (kept from CCL, per the epistemics research): `source_trust` ⊥
`confidence`. A user-stated fact decays slowly even when uncertain; an agent-reflected generalization
decays fast even when confident. **Decay is a per-epistemic-status lookup table** ×
`source_trust` factor, *not* a stored `decay_rate` field:

| epistemic | base decay/cycle | × source_trust factor |
|---|---|---|
| explicit | 0.02 | user_stated 0.3× · agent_extracted 1× · agent_reflected 1.5× · external 1× |
| deductive | 0.05 | (same factors) |
| inductive | 0.10 | (same factors) |
| abductive | 0.20 | (same factors) |

This makes abductive cross-context guesses self-prune in ~10 cycles unless reinforced, and removes one
field the LLM must set correctly.

### The generated entity card (transclusion-aware)

`entities/cicada.md` — a **deterministic render** (no LLM call to regenerate):

```markdown
---
name: Cicada
generated: true                 # NEVER hand-edit; Sleep overwrites from claims/
claims_file: claims/cicada.claims.yaml
type: project                   # coarse label, kept ONLY for graph node color (not load-bearing)
status: active
activation: 0.81
contexts: [engineering]
observers: [agent, rodrigo]
last_referenced: '2026-05-05'
version: 8
---

## facet: engineering
- Uses **sqlite-vec** for its semantic index, replacing [[leann]].
  _(agent · explicit · conf 0.95 · since 2026-05-05 · ep_2026-05-05_003)_

## Superseded
- ~~Used [[postgres]]~~ — held 2026-01-15 → 2026-05-05, replaced by sqlite-vec.

## Related
![[rodrigo#engineering]]        ← INLINE TRANSCLUSION: engineer-facet of Rodrigo embedded here
```

### Inline transclusion (NEW — first-class, C11)

The base sigil is `![[…]]` (Obsidian-compatible, visually distinct from the wikilink `[[…]]` the app
already renders), extended with four Cicada selectors:

| Syntax | Resolves to | Use |
|---|---|---|
| `![[subject]]` | that subject's whole generated card (one-liner summary) | embed a related entity inline |
| `![[subject#facet]]` | one `## facet: <name>` section | embed *just* engineer-Rodrigo into Cicada |
| `![[claim:clm_id]]` | one rendered claim (text + provenance badge) | cite/embed a single belief inline |
| `![[subject?context=engineering]]` | all valid claims of that subject in that context | a perspective slice inline |
| `![[subject#^block-id]]` | one block (Obsidian `^block-id` convention) | embed one paragraph |

**Resolution lives in one new service, `transclusion_resolver.py`.** It is a server-side pre-render
pass with two hard guards taken from the prior-art sweep:

- **Depth cap = 3** (Markdown Preview Enhanced's proven safe limit). Beyond depth 3 the embed degrades
  to a plain `[[wikilink]]`.
- **Cycle guard:** a per-render `visited` set keyed on the resolved subject/claim id; `A ![[B]]` /
  `B ![[A]]` degrades to a plain link at the cycle boundary, never freezes.
- **Missing target:** renders a soft `⚠ ![[id]] not found` stub, never a silent gap.

It is used in **two places**, which is why transclusion serves the *memory model*, not only the UI:

1. **Server-side, in `ask_service` / MCP retrieval.** When a retrieved claim or card contains a
   transclusion, the resolver inlines the referenced facet/claim *into the prompt context* (bounded,
   deduped by id). A page about Cicada that transcludes `![[rodrigo#engineering]]` automatically pulls
   engineer-Rodrigo's relevant beliefs into any answer about Cicada — **one belief, many inlined
   homes, no re-embedding or duplication.** Transclusion is *authored relational depth*, complementing
   the implicit 1-hop graph expansion.
2. **App-side, in the entity-card renderer.** The macOS card renders the embedded facet/claim inline
   (visually nested, with a "transcluded from [[rodrigo]]" chip + click-through), exactly like
   Obsidian's embed. The user *sees* memory composed from memory.

Transclusion is **authored by Sleep** (Stage 4 writes `![[…]]` into a card's `## Related` when a
strong cross-subject link exists) and **hand-insertable** in `_preferences.md` / `_procedures/`. Scope
boundary (from the research): read-only embed only — **no** write-through, **no** query-transclusion
beyond `?context=`, **no** cross-repo refs, **no** image/PDF embeds.

### Index (within the existing `vec_<kind>` / `meta_<kind>` machinery)

Confirmed against `vector_index.py` (per-kind `vec0` virtual table + rowid-aligned `meta_<kind>`
JSON-metadata table, `_rebuild_table` / `_knn`). Three additive changes:

1. **`claims` becomes the primary kind.** One row per *currently-valid* claim (`valid_to IS NULL`),
   embed = `claim.text`, metadata = `{claim_id, subject, predicate, object, observer, context,
   epistemic, source_trust, confidence, valid_from}`. Invalidated claims are **not** indexed (audit
   lives in git + the YAML). `observer` / `context` in metadata are **pivot/post-filter axes** the app
   and MCP drive.
2. **Facet entity rows** for coarse "about X" hits: one row per `## facet:` section; pages without
   facets keep their single whole-page row.
3. **`vec_pending` retired** in favor of `candidates/` activation rows.

The DB stays **derived and disposable**: `rebuild` reads `claims/` + `entities/` and regenerates
everything. Never migrated — deleted and rebuilt.

### Sleep pipeline (re-mapped onto the real 5 stages of `sleep_cycle.run()`)

- **Stage 1 — Extraction** (`entity_extractor.py` → claim extractor): emit claims with
  `observer/context/epistemic/source_trust` attached. Existing entity extraction is the
  `observer: agent, context: general, epistemic: explicit` special case — a back-compatible prompt
  extension, not a rewrite.
- **Stage 2 — Resolution** (`entity_resolver.py`): resolve `subject`/`object` strings to subject-ids;
  normalize `predicate` against `_predicates.yaml`; route each claim into its
  `claims/<subject>.claims.yaml`.
- **Stage 3 — Contradiction = mechanical invalidate-and-supersede** (`conflict_resolver.py`): key on
  `(subject, predicate, context, observer)`; for single-valued relations, stamp the old claim
  `valid_to = new.valid_from`, `superseded_by = new.id`, set `new.supersedes = old.id`. **Nothing is
  deleted.** Multi-valued relations (`uses`, `relates-to`) coexist. Emit a **mandatory**
  `normalization-audit` nudge on any auto-folded predicate. Per-epistemic × trust decay runs here.
- **Stage 4 — Pattern/skill + cross-context bridges + transclusion authoring**
  (`skill_extractor.py`): write `_preferences.md` / `_procedures/`; for subjects with claims in ≥2
  contexts, emit `context: cross`, `epistemic: abductive` bridge claims (low-confidence, fast-decay,
  surfaced as a "does this resonate?" nudge); **author `![[…]]` transclusions** into card `## Related`
  for strong cross-subject links.
- **Stage 5 — Render + version** (`entity_body.py` / `graph_builder.py` / `git_service.py`):
  deterministically regenerate `entities/*.md` cards (by facet) and `graph_edges.yaml` (valid-only,
  observer/context-tagged); rebuild the index; commit with `Cicada-Author` trailers.
  `git blame claims/cicada.claims.yaml` on a `valid_to:` line → the exact commit, episode, and model
  that retired a belief.

### Retrieval / `/ask` (keeps the `answer / confidence / citations / gaps` contract)

`ask_service.answer_query` keeps its exact shape and its `retrieve_fn` dependency-injection seam
(confirmed: `_default_retrieve_fn` → `search_entities`). Swap the default to **claim-first,
observer/context-aware**:

1. **Always-on prelude (not gated):** inject `_preferences.md` (scope-matched) as a compact block —
   "who is Rodrigo right now."
2. **KNN over the `claims` kind** + facet rows; SQL post-filter `valid_to IS NULL` by default (lift it
   only for historical queries — "what did Cicada use *before* sqlite-vec"); optional `observer` /
   `context` boost when the MCP client supplies a hint. **Context-blind default** (no down-weighting if
   no hint) — avoids PBM's silent-degradation failure.
3. **Score** = `cosine × confidence × recency` (Generative-Agents three-signal); drop invalidated
   claims.
4. **Transclusion expansion:** inline referenced facets/claims (bounded, deduped by id) — authored
   relational depth.
5. **1-hop graph expansion** via `subject`/`object` index lookups — implicit relational depth.
6. **Citations** point at `claim_id` + valid-window + `source_trust` + **`observer`** ("Rodrigo
   asserts X" vs "Karpathy claims Y" vs "I inferred Z"). `gaps` honestly reports "I hold only a
   superseded claim for X."

MCP Bookworm gains one tool: `get_perspective(subject, observer?, context?)` → that perspective's
valid claims (Honcho's user-model injection that hit 90.4% accuracy at 5% context cost).

---

## Companion-app showcase

Five buildable surfaces, each a real SwiftUI view or d3 layer plus the exact API it consumes, all
extending the app's *actual* seams: the `@Observable` ViewModel + `actor APIClient` generic
`get`/`post` pattern, the `CicadaTheme` palette, the `EntityDetailCard` tab card, and the d3 graph's
only Swift↔JS contract — `evaluateJavaScript("updateGraph/applyFilters/setFocus")` outbound and
`window.webkit.messageHandlers.cicada.postMessage({type})` inbound. Every new Swift model decodes with
`decodeIfPresent`, so **the app compiles and runs against today's backend** (empty claims → graceful
empty states) and lights up incrementally as endpoints land. (Full code in `d2-companion-showcase.md`.)

**Shared atoms (one new file `Models/Claim.swift`):** `Claim`, `Observer` (`.agent` / `.rodrigo` /
`.external(String)`), `Epistemic`, `SourceTrust`, `ClaimTimeline`, `TransclusionPayload`, plus
`CicadaTheme.contextColor(_:)` (hard-coded core contexts + stable hash for the open tail).

1. **Inline transclusion — `TranscludingMarkdownView`** (HIGHEST DEMO LEVERAGE). Replaces the flat
   `Text(renderedMarkdownAttributed)` in `EntityDetailCard`; tokenizes the body into `.text` / `.embed(ref)`
   segments, renders each embed as a collapsible, depth-guarded (max 2 in-app), accent-barred nested
   card; tapping the embed title calls the existing `graphVM.selectEntity(id:)`. **API:**
   `GET /transclude?ref=<urlencoded>` → `TransclusionPayload {kind, ref, title, summary, claims[], resolved}`.
2. **The claim graph** — three additive d3 layers behind optional `/graph` fields, no new message
   type: **(a) context-colored edges** (replace the flat `#666` stroke via a JS mirror of
   `contextColor`), **(b) observer badges** per node (a filled dot per distinct observer), **(c) facet
   sub-nodes** (`id: "rodrigo#engineering"`, `parentId: "rodrigo"`, routed through the *existing*
   node-click channel). **API:** optional `observers`, `contexts`, `isFacet`, `parentId`, `context`,
   `claimId` fields on the existing `GET /graph`.
3. **Observer / perspective filter** — a graph-level segmented filter **All · Cicada · Rodrigo ·
   External** that *dims rather than deletes* (contrast stated vs inferred beliefs), plus a per-page
   `.perspectives` tab grouping claims by observer with a **divergence callout** for who-believes-what
   disagreements. **API:** reuses `GET /entities/{id}/claims`; `GET /graph` gains a top-level
   `observers: [String]` roster.
4. **Belief timeline — `BeliefTimelineView`** (flagship C3). Renders one `(subject, predicate,
   context)` key as a vertical `superseded_by` chain plus a horizontal context-colored validity-bar
   strip where the orange Postgres segment ends exactly where the green sqlite-vec segment begins — the
   bi-temporal story in one image. **API:** `GET /entities/{id}/timeline?predicate=<p>&context=<c>` →
   `ClaimTimeline`.
5. **Claim provenance — `ClaimChip`** (the reusable atom consumed by 1, 3, 4). Body line + a single
   provenance footer: observer badge, context pill, **orthogonal** trust-pill + confidence-ring,
   authored-by pill (same styling as the existing Contributors view), source-episode chip, clock icon
   → timeline; superseded claims dim + strikethrough. **API:** none — pure render over a `Claim`.

**Why these five and not CCL's:** all five are read-only projections of `claims/` + git; none need a
new write path. CCL could approximate (4) and the contradiction overlay, but **not** (1)/(2b)/(3)/(5)
— those require the claim/observer to be addressable *outside* a page body, which is exactly what the
separate store buys.

**Backend endpoints added (all additive; filesystem stays the single source of truth):**
`GET /entities/{id}/claims`, `GET /entities/{id}/timeline`, `GET /transclude`, plus optional fields on
`GET /graph`. The per-commit `Cicada-Author` provenance and `/contributors` shipped in M3 are reused
verbatim for the authored-by pill.

---

## Worked examples

### 1. Faceted self (engineer-Rodrigo vs family-Rodrigo, no collapse)

`memory/claims/rodrigo.claims.yaml` holds three claims:

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

No contradiction — different `context`. The index stores a `rodrigo/engineering` vector and a
`rodrigo/family` vector. "What does Rodrigo value when building software" hits engineering; "what
matters to Rodrigo about home" hits family. **In the app:** the graph shows a `rodrigo` node with two
context-colored facet satellites; the perspective tab groups by observer; the cross bridge (`_03`)
renders gold and self-prunes in ~10 cycles (decay 0.20) unless reinforced.

### 2. A belief that changes, with a timeline (Postgres → sqlite-vec)

Day 1, `claims/cicada.claims.yaml`: `{predicate: uses, object: postgres, context: engineering,
valid_from: 2026-01-15, valid_to: null}`. Day 110 an episode says "switched the index to sqlite-vec."
Stage 3 keys on `(cicada, uses, engineering, agent)`, finds the open Postgres claim, single-valued →
closes it:

```yaml
- id: clm_2026-01-15_002
  predicate: uses  object: postgres  context: engineering
  valid_from: '2026-01-15'  valid_to: '2026-05-05'  superseded_by: clm_2026-05-05_009
- id: clm_2026-05-05_009
  predicate: uses  object: sqlite-vec  context: engineering
  valid_from: '2026-05-05'  valid_to: null  supersedes: clm_2026-01-15_002  confidence: 0.95
```

`/ask "what's Cicada's vector store"` → sqlite-vec (only the open claim is indexed). `/ask "what did
Cicada use before sqlite-vec"` → finds the closed claim. `git blame` on the `valid_to:` line → the
exact Sleep commit and model that retired the Postgres belief. **In the app:** `BeliefTimelineView`
draws the orange Postgres segment ending 2026-05-05, the green sqlite-vec segment starting the same
day, a "superseded by" chevron between them, each annotated with `authored_by`.

### 3. A transcluded page

`entities/cicada.md` (generated card) ends with `## Related` containing `![[rodrigo#engineering]]`.
On open, `TranscludingMarkdownView` calls `GET /transclude?ref=rodrigo%23engineering`; the resolver
returns engineer-Rodrigo's valid claims, rendered as a nested card with a "transcluded from
[[rodrigo]]" chip. Editing `rodrigo`'s engineering claims and reopening `cicada` shows the embed
reflecting the change — one belief, two homes, no duplication. At `/ask` time, a query about Cicada
that retrieves this card pulls engineer-Rodrigo's beliefs into the prompt context automatically
(bounded, deduped).

### 4. A procedural preference

Rodrigo corrects the agent's FastAPI scaffolding. Stage 4 writes to `_preferences.md` (human-readable,
human-editable, **never** overwritten):

```markdown
- id: pref_017  scope: [coding, fastapi, python]  status: active
  source_trust: user_stated  confidence: 0.85  source_episodes: [ep_2026-02-10_004, ep_2026-03-02_011]
  Rule: Split FastAPI routers by domain (one module per resource); services thin; models separate.
```

Always injected at conversation start (never similarity-gated). If Rodrigo later says "one big router
is fine for small services," Stage 3 writes a new preference with `supersedes: pref_017` and flips the
old to `status: superseded` — the agent stops applying the stale rule. Task-shaped *procedures* with
step-lists live in `_procedures/<name>.md` with a `trigger:` description and `verified_in:` episode
citations, retrieved only when the query is task-shaped.

### 5. An external-observer media claim

A saved RSS article / talk becomes a subject with a **soft type** and claims whose `observer` is the
source:

```yaml
# claims/karpathy-intro-to-llms.claims.yaml
subject: karpathy-intro-to-llms
subject_name: "Karpathy — Intro to LLMs (talk)"
claims:
  - id: clm_2026-06-01_021
    text: "Karpathy frames an LLM as a lossy compression of its training corpus."
    predicate: claims  object: llm-as-lossy-compression  object_kind: literal
    observer: external:karpathy-talk  context: engineering
    epistemic: explicit  source_trust: external  confidence: 0.6
    valid_from: '2026-06-01'  valid_to: null  source_episodes: [ep_2026-06-01_002]
```

`/ask` can cite the claim while signalling `observer: external:karpathy-talk` + `source_trust:
external` — the agent attributes it to Karpathy, not to Rodrigo. **In the app:** the node carries an
external-observer badge (pink), the observer filter's "External" segment lights it up distinct from
Rodrigo's self-assertions, and the `ClaimChip` shows the `quote.bubble.fill` observer symbol. New
media/problem/open-question kinds need **no** schema change (C7).

---

## Build plan

Phased to **surface demos early** (not ordered for migration cheapness). Every wave runs first in a
`/tmp/cicada_bench_*` workspace per the benchmark safety rails, never mutating live `memory/` until
validated. Rollback at any wave: `git revert` + delete `claims/` + delete `vector_index.db`; cards are
regenerable, pre-migration `entities/*.md` recoverable from history. The bet is bounded and reversible
— just no longer free.

- **M5a — Store + reader + index, no data change (~3–4 days eng, $0 LLM).** Add the `claims/` store +
  a `parse_claims_file()` / `write_claims_file()` reader to `markdown_parser.py`. Make `claims` the
  primary index kind in `vector_index.py` (`index_claims` / `search_claims`, mirroring
  `index_entities`). Scaffold `candidates/`, `_preferences.md`, `_procedures/`, `_predicates.yaml`.
  Additive — legacy pages still parse and render.
- **M5b — Deterministic seeding ($0 LLM, one commit).** Convert every `graph_edges.yaml` stanza to a
  seed claim deterministically (`{subject: source, predicate: label, object: target, observer: agent,
  context: general, source_trust: agent_extracted}`) — backfills the entire relational layer **for
  free** (TFG's free-conversion insight). Stamp `schema_version`, `source_trust: agent_extracted`,
  initial `activation` (from `last_referenced` + `len(source_episodes)`).
- **M5c — DEMO-FIRST app surfaces against seeded data (eng, $0 LLM).** Build `Models/Claim.swift`,
  `ClaimChip`, `TranscludingMarkdownView`, the three d3 graph layers, the observer filter, and
  `BeliefTimelineView` — plus the thin endpoints `GET /entities/{id}/claims`,
  `GET /transclude` (with `transclusion_resolver.py`: depth-cap 3, cycle-guard, soft-missing stub),
  and the optional `/graph` fields. **This makes the killer demos visible on seeded data before the
  expensive extraction**, so a defense screenshot exists early and the surfaces are validated against
  real (if coarse) claims.
- **M5d — The one real LLM cost: prose → claims extraction (~$2–6, overnight).** 1,882 pages × one
  cheap structured call assigning `observer`/`context`/`epistemic` (bodies are short — the sampled
  pages are 1–3 sentences; ~600 in / ~400 out tokens on a mini model). **$0 on local EmbeddingGemma
  for the reindex.** This is the cost CCL refused and the mandate accepts. Output: every page's prose
  becomes addressable claims with observer/context assigned. Run `benchmarks.run_table1` on old vs new
  path — the claim path should win temporal/contradiction and tie-or-better recall.
- **M5e — Sleep rewrite + render + retrieval swap (eng, $0 LLM).** Make Stage 3 the mechanical
  invalidate-and-supersede pass; add the `normalization-audit` nudge; add Stage-4 preference/procedure
  + cross-context bridge + transclusion authoring; make Stage 5 regenerate cards (`generated: true`)
  and valid-only edges. Swap `ask_service`'s default `retrieve_fn` to claim-first; turn on
  transclusion expansion; add `get_perspective` to MCP Bookworm.
- **M5f — Remaining app polish (eng, $0 LLM).** Time-scrubber on the graph, contradiction overlay,
  perspective pivot columns, facet-where-they-pay rendering for the ~5–20 genuinely multi-context
  subjects.

**Honest total cost:** ~2 weeks eng across backend + app, **~$2–6 of LLM** (one extraction pass),
**$0 embeddings** (local). The schema change touches all five Sleep stages and inverts page ownership
— real work, accepted under the re-weighting because it buys C2/C9/C10/C11 outright while tying
C1/C3/C4/C5/C7.

**Residual risks (carried + new):** (1) **predicate-normalization drift** is the one
correctness-critical dependency — mitigated by the mandatory audit nudge + a hand-seeded conservative
`_predicates.yaml`; (2) **Stage-3 single-vs-multi-valued judgment** is one LLM call per conflict
candidate — lower-stakes because dated, sourced, git-reversible; (3) **the "human hand-edits a
generated card" footgun** — mitigated by routing all edits through claims/app (card read-only);
(4) **`observer` under-use** if the extractor defaults everything to `agent` — mitigated by a
deliberate prompt rule + post-first-Sleep audit, now *visible in the app* so under-use is obvious;
(5) **transclusion cycles/expansion blow-up** — mitigated by depth cap + cycle-guard + dedup-by-id.

---

## Decisions Rodrigo must make

1. **Per-subject claim files vs one-file-per-claim.** *Recommend per-subject*
   (`claims/<x>.claims.yaml`) — keeps `git blame` meaningful and file count bounded (~1,882). The
   TFG/PBM consensus.
2. **Card edit policy.** *Recommend cards strictly read-only* (`generated: true`); all edits via
   app→claim writes; only `_preferences.md` / `_procedures/` are human-authored prose. Closes PBM's
   overwrite footgun.
3. **Run the full extraction backfill for the thesis Results, or stay lazy?** With migration demoted,
   *recommend the full ~$2–6 backfill* for a uniform store and clean Results numbers (lazy-only leaves
   cold pages claimless and weakens the demo).
4. **Transclusion depth cap.** *Recommend 3* server-side (MPE-proven) + cycle-guard; the app collapses
   embeds at depth ≥ 2 for readability.
5. **Context vocabulary.** *Recommend a small named core* (`engineering | family | philosophical |
   career | cross | general`) + open tail with a normalization nudge — open sets drift.
6. **Observer cardinality.** *Recommend* `agent | rodrigo | external:<name>`; `external:<name>` is the
   high-value media/RSS provenance case.
7. **Decay constants + promotion threshold.** *Recommend* accepting the per-epistemic table
   (0.02/0.05/0.10/0.20 × trust factor) and `θ_promote = 0.5` as defaults, exposed in config and
   **ablated in the existing Table-2 harness** so the thesis defends them empirically.
8. **App demo scope for the thesis.** *Recommend shipping all five surfaces* — inline transclusion +
   the observer-colored graph are the two highest-impact; the belief timeline is the flagship C3
   image; all are read-only projections, cheap once the store exists.
9. **Keep the "biologically-inspired Awake/Sleep" framing?** *Recommend keep* — CPCG maps cleanly
   (episodic capture → claim consolidation → bi-temporal semantic store) and the framing is now
   load-bearing engineering, not thesis decoration.
```
