# D2 Re-derivation: The Best Memory Architecture (migration demoted)

> **Mandate change (Rodrigo, 2026-06-17).** The prior D2 recommendation (Cicada Claim Layer,
> CCL) was *deliberately* optimized for cheap/reversible migration: it took the pragmatics
> winner (Evolved-Cicada) as the chassis and forced the unit of truth to live *inside* the
> entity page purely so a legacy page would be "a valid CCL page for free" (C6=10). That
> weighting is now **overridden**. Migration is demoted from existential to a one-time cost.
> The new high-weight criteria are agent retrieval (C1), observer/context identity (C2),
> temporal/contradiction (C3), overall (C9), **companion-app demonstrability (C10, new)**, and
> **inline-transclusion fit (C11, new)**. Under those weights the claims-in-page compromise
> stops paying for itself, and a **clean, separate, normalized claim store** — the exact thing
> CCL avoided — becomes the better architecture.

---

## Executive recommendation

Adopt **Cicada Perspectival Claim Graph (CPCG)**: a **separate, normalized, first-class claim
store** as the source of truth for *belief*, with entity pages **demoted to generated,
human-readable, transcludable cards** projected from it. The atom is a **claim** keyed by
`(observer, context, subject)`, bi-temporally valid (`valid_from`/`valid_to` true-in-world +
git/`recorded_at` learned-by-system), epistemically typed (`explicit | deductive | inductive
| abductive`), and trust-classed (`source_trust ⊥ confidence`). Claims live one-YAML-file-
per-subject in `memory/claims/<subject>.claims.yaml` (the Temporal-Fact-Graph / Perspectival-
Belief-Memory layout), are individually embedded as the primary retrieval kind, and carry
mechanical **predicate-keyed invalidate-and-supersede** for contradiction. Entity pages
(`entities/*.md`) become **deterministic renders** of each subject's currently-valid claims,
grouped into `## facet: <context>` sections, and they gain a first-class **inline
transclusion** syntax (`![[subject#facet]]`, `![[claim:clm_id]]`) that the companion app
expands inline. The d3 graph is upgraded from an entity-node graph to a **claim-grounded,
observer-colored, time-scrubbable belief graph** — the killer demo.

**This is essentially Perspectival-Belief-Memory (PBM) promoted to the recommendation, fused
with Temporal-Fact-Graph's (TFG) mechanical contradiction key and per-subject file layout, and
extended with two things neither candidate had: a designed inline-transclusion layer and an
explicit app-demonstrability surface.** It is what CCL *would* have been if migration cost had
not been allowed to veto the separate store.

---

## The single biggest upgrade over CCL

**CCL kept truth *inside* the entity page (a `\`\`\`claims` fence in `entities/<x>.md`) so a
legacy page stayed valid for free. CPCG moves truth into a separate normalized
`claims/<subject>.claims.yaml` store and makes the page a generated projection.** That one
change — paid for by a one-time ~$2–6 extraction pass that the new mandate explicitly permits —
unlocks everything the high-weight criteria now reward:

- **`observer` becomes structural, not a buried YAML field.** A separate store lets
  `(observer, context, subject)` be the *primary key and the directory/index shape*, so the
  app can render a literal who-believes-what graph (agent's-Rodrigo vs Rodrigo's-Rodrigo vs
  external-source beliefs as distinct, colored, side-by-side structure). In CCL `observer` was
  a column on a claim hidden inside a page body — present, but invisible to the app and
  un-pivotable. (C2, C10.)
- **The claim is the first-class object the app can address, link to, transclude, and
  time-scrub.** Inline transclusion (`![[claim:clm_id]]`) and a per-claim timeline only make
  sense if a claim has a stable home and id *outside* a page body. (C10, C11.)
- **One write touches one small YAML record, not a page-body fence**, so contradiction,
  decay, and supersession are clean per-claim git diffs, and `git blame` is per-claim. (C3,
  C4.)

In one line: **CCL optimized for "the old page still works"; CPCG optimizes for "the belief is
a real, separate, addressable, perspectival, time-versioned object the agent retrieves and the
app can show."** With migration demoted, that is the better trade.

---

## What changes vs CCL (point by point)

| Dimension | CCL (prior winner) | **CPCG (this)** | Why the change is now worth it |
|---|---|---|---|
| **Source of truth for belief** | claim YAML *inside* `entities/<x>.md` fence | separate `claims/<subject>.claims.yaml` store; page is a render | migration no longer vetoes a clean store; separation is what makes observer/claim addressable for app + transclusion |
| **Entity page** | the canonical home, hand-editable | **generated card** (`generated: true`), edits go through claims/app/nudges | a projection can be re-rendered, transcluded, and time-scrubbed; the "human hand-edits a generated card" footgun is handled by editing claims, not prose |
| **Observer** | a field on a claim, app-invisible | **primary key dimension**, a graph color, a pivot axis | C2 + C10 are now high-weight; observer must be *visible structure*, not metadata |
| **Faceting** | `## facet:` rendered when ≥2 contexts; `context:` on claim | same, but facets are **addressable transclusion targets** (`![[rodrigo#engineering]]`) | C11 (transclusion) is new and high-weight |
| **Transclusion** | not designed | **first-class** `![[subject]]`, `![[subject#facet]]`, `![[claim:id]]`, server-expanded for `/ask`, app-rendered inline | brand-new mandate item (C11) |
| **Graph view** | entity nodes, deferred facet coloring | **claim-grounded belief graph**: observer-colored, valid-only by default, time-scrub, contradiction overlay | C10 (demonstrability) promoted to high-weight |
| **Migration** | $0 required, lazy, byte-reversible (C6=10) | **one-time ~$2–6 extraction + reindex**, reversible via git | C6 demoted; the cost buys a materially better architecture |
| **Retrieval unit** | per-claim (already) | per-claim, **observer/context-pivotable** | same strength, now pivotable for the app's perspective views |

**What CPCG keeps from CCL unchanged** (these were good and survive re-weighting): the claim
schema fields (`epistemic`, `source_trust ⊥ confidence`, `valid_from/valid_to`,
`superseded_by/supersedes`, `premises`, `authored_by`→`Cicada-Author` trailer); the mechanical
predicate-keyed Stage-3 invalidate-and-supersede with a mandatory `_predicates.yaml`
normalization-audit nudge; per-epistemic-status decay lookup table × source-trust factor;
`candidates/` activation-score promotion replacing the count-to-2 gate; the always-injected
`_preferences.md` block + trigger-gated `_procedures/`; soft/open types; and the
"index is fully derived and disposable, rebuilt from markdown" contract.

---

## Data model (concrete, on-substrate)

### File layout

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
├── _preferences.md                 ← always-injected behavioral block (preferences only)
├── _procedures/                    ← trigger-gated reusable step-lists (procedures only)
│   └── fastapi-repo-layout.md
├── _predicates.yaml                ← canonical predicate-synonym map (chose ≈ selected → chose)
├── graph_edges.yaml                ← KEPT, now a DERIVED projection: Sleep regenerates valid-only
│                                     edges from claims; gains observer / context / valid_* / claim_id
├── leann/ → vector_index.db        ← sqlite-vec; PRIMARY kind becomes `claims`; facet rows on entities
└── nudges/ clarifications/ inbox/ hubs/ sources/   ← UNCHANGED
```

The load-bearing inversion vs CCL: **`claims/` is authoritative, `entities/*.md` is a
projection.** A page can always be rebuilt from `claims/`; if a page is lost, Sleep
regenerates it. This is PBM's ownership inversion, which CCL explicitly rejected to save
migration. With migration demoted, we take it — and we mitigate PBM's one real footgun (the
human hand-edits a `generated: true` card and Sleep silently overwrites it) by routing *all*
human edits through the app/nudges → claim writes, never through page prose. The app makes
claims editable; the page is read-only render.

### The claim (the atom)

`memory/claims/cicada.claims.yaml`:

```yaml
subject: cicada
subject_name: Cicada
claims:
  - id: clm_2026-05-05_009
    text: "Cicada's semantic index is built on sqlite-vec."   # the embedded string
    subject: cicada
    predicate: uses                     # OPEN verb; normalized vs _predicates.yaml at Sleep
    object: sqlite-vec
    object_kind: node                   # node | literal
    observer: agent                     # agent | rodrigo | external:<name>   (PRIMARY KEY dim)
    context: engineering                # engineering|family|philosophical|career|cross|general (OPEN)
    epistemic: explicit                 # explicit|deductive|inductive|abductive  (drives decay)
    source_trust: user_stated           # user_stated|agent_extracted|agent_reflected|external
    confidence: 0.95                    # 0..1, ORTHOGONAL to source_trust
    valid_from: '2026-05-05'            # true-in-world start
    valid_to: null                      # null = currently valid; a date = closed/superseded
    superseded_by: null
    supersedes: clm_2026-01-15_002      # this claim closed the Postgres one
    recorded_at: '2026-05-05'           # learned-by-system (git commit is the audit anchor)
    source_episodes: [ep_2026-05-05_003]
    premises: []                        # for deductive/inductive: claim-ids derived from
    authored_by: gpt-5.4-mini           # → Cicada-Author git trailer
```

`(observer, context, subject)` is the **primary key** (Honcho's `(observer, observed)` graft,
generalized with `context`). `observer == subject` is a self-belief; `observer: agent,
subject: rodrigo` is the agent's model of Rodrigo; `observer: external:karpathy-talk` is
something a source asserted. **The same subject carries contradictory claims without conflict
if observer or context differs** — engineer-Rodrigo "values speed", family-Rodrigo "values
presence", agent-believes-X vs Rodrigo-asserts-Y. This is the C2 home-turf PBM scored 10 on,
now made the recommendation.

### The generated entity card (transclusion-aware)

`entities/cicada.md` — a deterministic render, **no LLM call to regenerate**:

```markdown
---
name: Cicada
generated: true                 # NEVER hand-edit; Sleep overwrites from claims/
claims_file: claims/cicada.claims.yaml
type: project                   # coarse label, kept ONLY for graph node color (not load-bearing)
status: active
activation: 0.81
contexts: [engineering]
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

Three address forms, modeled on Obsidian `![[note]]` / Claude Code `@file.md`:

| Syntax | Resolves to | Use |
|---|---|---|
| `![[subject]]` | that subject's whole generated card | embed a related entity's summary inline |
| `![[subject#facet]]` | one `## facet:` section of a card | embed *just* engineer-Rodrigo into Cicada |
| `![[claim:clm_id]]` | one rendered claim (text + provenance badge) | cite/embed a single belief inline |

**Resolution lives in one new service, `transclusion_resolver.py`**, with a strict depth cap
(default 2) and cycle-guard (a visited-set on `(target, depth)`) so `A embeds B embeds A`
terminates. It is used in **two places**, which is why it serves the memory model and not just
the UI:

1. **Server-side, in `ask_service`/MCP retrieval** — when a retrieved claim or card contains a
   transclusion, the resolver inlines the referenced facet/claim *into the prompt context*
   (bounded, deduped by id). This is the memory-model payoff: a page about Cicada that
   transcludes `![[rodrigo#engineering]]` automatically pulls engineer-Rodrigo's relevant
   beliefs into any answer about Cicada, **without re-embedding or duplicating them** — one
   belief, many inlined homes. Transclusion is *retrieval-time relational depth made
   authored and explicit*, complementing the implicit 1-hop graph expansion.
2. **App-side, in the entity card renderer** — the macOS card renders the embedded
   facet/claim inline (visually nested, with a subtle "transcluded from [[rodrigo]]" chip and
   a click-through), exactly like Obsidian's embed. This is a direct C10 demo: the user *sees*
   memory composing itself out of other memory.

Transclusion is **authored by Sleep** (Stage 4 writes `![[...]]` into a card's `## Related`
when a strong cross-subject link exists) and **hand-insertable** in `_preferences.md` /
`_procedures/` (the one place humans author prose), so it is both an emergent and a manual
relational primitive.

### Index changes (within the existing `vec_<kind>`/`meta_<kind>` machinery)

Confirmed against `vector_index.py` (per-kind `vec0` virtual table + rowid-aligned
`meta_<kind>` JSON-metadata table, `_rebuild_table`/`_knn`):

1. **`claims` becomes the primary kind.** One row per *currently-valid* claim
   (`valid_to IS NULL`), embed = `claim.text`, metadata = `{claim_id, subject, predicate,
   object, observer, context, epistemic, source_trust, confidence, valid_from}`. Invalidated
   claims are **not** indexed (audit lives in git + the YAML). This is TFG/PBM's per-claim
   retrieval unit, unchanged from CCL — except `observer`/`context` in metadata are now used
   as **pivot/post-filter axes** the app and MCP can drive.
2. **Facet entity rows** for the d3 "about X" coarse hits: one row per `## facet:` section.
3. **`vec_pending` retired** in favor of `candidates/` activation rows (PBM's cleanup).

The DB stays **derived and disposable**: `rebuild` reads `claims/` + `entities/` and
regenerates everything. Never migrated — deleted and rebuilt (the swap from CCL's
page-fence reader to a `claims/`-file reader is a single change in `index_claims()`).

### Sleep pipeline (5 stages, re-mapped onto the real services)

- **Stage 1 — Extraction** (`entity_extractor.py` → claim extractor): emit claims with
  `observer/context/epistemic/source_trust` attached; existing entity extraction is the
  `observer: agent, context: general, epistemic: explicit` special case (back-compatible
  prompt extension).
- **Stage 2 — Resolution** (`entity_resolver.py`): resolve `subject`/`object` strings to
  subject-ids; normalize `predicate` vs `_predicates.yaml`; route each claim into its
  `claims/<subject>.claims.yaml`.
- **Stage 3 — Contradiction = mechanical invalidate-and-supersede** (`conflict_resolver.py`):
  key on `(subject, predicate, context, observer)`; single-valued conflict → stamp old
  `valid_to`/`superseded_by`, set new `supersedes`. **Nothing deleted.** Emit a mandatory
  `normalization-audit` nudge on any auto-folded predicate. Per-epistemic × trust decay runs
  here.
- **Stage 4 — Pattern/skill + cross-context bridges + transclusion authoring**
  (`skill_extractor.py`): write `_preferences.md`/`_procedures/`; for subjects with claims in
  ≥2 contexts, emit `context: cross`, `epistemic: abductive` bridge claims (low-confidence,
  fast-decay, surfaced as a "does this resonate?" nudge); **author `![[...]]` transclusions**
  into card `## Related` for strong cross-subject links.
- **Stage 5 — Render + version** (`entity_body.py`/`graph_builder.py`/`git_service.py`):
  deterministically regenerate `entities/*.md` cards (by facet) and `graph_edges.yaml`
  (valid-only, observer/context-tagged); rebuild the index; commit with `Cicada-Author`
  trailers. `git blame claims/cicada.claims.yaml` on a `valid_to:` line → the exact commit,
  episode, and model that retired a belief.

### Retrieval / `/ask` (keeps the `answer/confidence/citations/gaps` contract)

Swap `ask_service`'s default `retrieve_fn` to **claim-first, observer/context-aware**:
1. Always-on prelude: inject `_preferences.md` (scope-matched).
2. KNN over `claims` kind; SQL post-filter `valid_to IS NULL` (lift only for historical
   queries); optional `observer`/`context` boost when the MCP client supplies a hint;
   **context-blind default** (no down-weighting if no hint — avoids PBM's silent-degradation
   flaw).
3. Score = `cosine × confidence × recency` (Generative-Agents three-signal).
4. **Transclusion expansion**: inline referenced facets/claims (bounded, deduped) — authored
   relational depth.
5. 1-hop graph expansion via `subject`/`object` index lookups — implicit relational depth.
6. Citations point at `claim_id` + valid-window + `source_trust` + **`observer`** ("Rodrigo
   asserts X" vs "Karpathy claims Y" vs "I inferred Z"). `gaps` honestly reports "I hold only a
   superseded claim for X."

MCP Bookworm gains `get_perspective(subject, observer?, context?)` → that perspective's valid
claims (Honcho's user-model injection that hit 90.4% at 5% context cost).

---

## Companion-app demonstrability (C10 — the new high-weight criterion)

This is where the separate, perspectival, bi-temporal store pays its most visible dividend.
Concrete demos the architecture makes possible that CCL's in-page claims could not show:

1. **Observer-colored belief graph.** The d3 view (`graph.js`) already has type-colored nodes,
   hub anchors, and semantic zoom. CPCG adds an **observer lens**: toggle node/edge coloring by
   `observer` (agent-belief / Rodrigo-self-belief / external-source). The graph literally
   renders *who believes what*. A claim edge from `external:karpathy-talk` is visibly a
   different color than a `rodrigo` self-assertion. This is the observer philosophy made
   visible — impossible to demo when `observer` is a buried field in a page body.
2. **Belief timeline / time-scrub.** Because claims are bi-temporal and superseded claims are
   retained, the existing `EntityDetailCard` "history" tab becomes a **per-belief timeline**
   (Postgres held 2026-01-15 → 2026-05-05, superseded by sqlite-vec), and the graph gains a
   **time-scrubber**: drag a date slider, the graph re-filters to claims valid at that date.
   Watching beliefs appear, change, and get superseded over the project's life is the thesis's
   single most compelling demo, and it is a pure function of `valid_from/valid_to`.
3. **Contradiction overlay.** Stage-3 supersessions are first-class edges
   (`supersedes`/`superseded_by`), so the app can draw a "this replaced that" overlay — a red
   strike-through arc from the closed claim to its replacement, with the exact commit/episode.
4. **Inline transclusion in cards.** The entity card renders `![[rodrigo#engineering]]` as a
   nested, attributed embed — memory visibly composed from memory (C11 + C10 together).
5. **Perspective pivot.** A subject panel can pivot on `(observer, context)`: "show me Cicada
   as the agent believes it (engineering)" vs "as Rodrigo asserts it" — three side-by-side
   columns over the same subject. This is the Honcho `(observer, observed)` UI, native.

All five are read-only projections of `claims/` + git; none require new write paths. CCL could
have approximated (2)–(3) but not (1)/(4)/(5), because those require the claim/observer to be
addressable *outside* a page body.

---

## Why CPCG beats CCL and the four candidates under the NEW weights

| Criterion (new weight) | CCL | TFG | PBM | Tiered | **CPCG** | Why CPCG wins now |
|---|---|---|---|---|---|---|
| **C1 retrieval (HIGH)** | 9 | 9 | 9 | 8 | **9** | per-claim index (= all of them) + observer/context pivot + authored transclusion depth |
| **C2 observer/context (HIGH)** | 9 | 9 | **10** | 8 | **10** | `(observer,context,subject)` is the *primary key and a render/graph axis*, not a buried field |
| **C3 temporal/contradiction (HIGH)** | 10 | 10 | 9 | 9 | **10** | TFG's mechanical predicate-keyed close + mandatory normalization-audit; per-claim git blame |
| **C4 provenance** | 9 | 9 | 9 | 9 | **9** | claim-id + valid-window + observer + Cicada-Author; per-claim (not per-page-fence) blame |
| **C5 procedural** | 9 | 9 | 9 | 9/10 | **9** | always-injected `_preferences.md` + trigger-gated `_procedures/`, supersession-retired |
| **C6 migration (LOW now)** | 10 | 7 | 7 | 3.5 | **6** | one-time ~$2–6 + reindex, git-reversible — *acceptable* under the new mandate |
| **C7 extensibility** | 8/9 | 9 | 9 | 4.5 | **9** | soft types + open predicates + new observer/context values, no schema migration |
| **C8 simplicity (LOW now)** | 6 | 6 | 6 | 3 | **5** | a separate store + renderer is more surface than in-page; accepted, secondary to "best" |
| **C9 overall (HIGH)** | 8.5 | 9 | 9 | 4.5 | **9.3** | tops every HIGH-weight lens at once |
| **C10 demonstrability (HIGH, NEW)** | 6 | 7 | 8 | 7 | **10** | observer-colored + time-scrub + contradiction overlay + transclusion + perspective pivot |
| **C11 transclusion (HIGH, NEW)** | 3 | 4 | 5 | 4 | **10** | designed first-class: `![[subject#facet]]`/`![[claim:id]]`, server-expanded + app-rendered |

CCL was engineered to win C6/C8 (the now-LOW criteria) and tie on the rest. CPCG accepts a
controlled loss on C6/C8 to **win outright on the now-HIGH C2/C9/C10/C11** and tie on
C1/C3/C4/C5/C7. Under the re-weighting, that is the dominant choice.

---

## Honest migration cost (the thing we are now allowed to pay)

From **1,882 typed entity pages + graph_edges.yaml + episodes**, phased, every wave first in a
`/tmp/cicada_bench_*` workspace per the benchmark safety rails, never mutating live `memory/`
until validated.

- **M5a — Code, no data change (~3–4 days eng, $0 LLM).** New `claims/` store + reader; make
  `claims` the primary index kind in `vector_index.py`; `transclusion_resolver.py` (depth-cap +
  cycle-guard); deterministic card renderer in `entity_body.py`; `candidates/`, `_preferences.md`,
  `_procedures/`, `_predicates.yaml` scaffolds. Additive; legacy pages still parse/render.
- **M5b — Deterministic seeding ($0 LLM, one commit).** Convert every `graph_edges.yaml` stanza
  to a seed claim deterministically (`{subject: source, predicate: label, object: target,
  observer: agent, context: general, source_trust: agent_extracted}`) — this backfills the
  entire relational layer **for free** (TFG's free-conversion insight). Stamp `schema_version`,
  `source_trust: agent_extracted`, initial `activation`.
- **M5c — The one real LLM cost: prose → claims extraction (~$2–6, overnight).** 1,882 pages ×
  one cheap structured call (bodies are short — sampled pages are 1–3 sentences). ~600 in / ~400
  out tokens on a mini model ≈ a few dollars total; **$0 on local EmbeddingGemma for the
  reindex.** This is the cost CCL refused to pay and the new mandate explicitly accepts. Output:
  every page's prose becomes addressable claims in `claims/`, with `observer`/`context` assigned.
- **M5d — Render + retrieval swap (eng, $0 LLM).** Regenerate all cards from `claims/`; swap
  `ask_service` default `retrieve_fn` to claim-first; turn on transclusion expansion. Run
  `benchmarks.run_table1` on old vs new path; claim path should win temporal/contradiction and
  tie-or-better recall.
- **M5e — App demos (eng, $0 LLM).** Observer lens + time-scrubber + contradiction overlay +
  transclusion rendering + perspective pivot in the SwiftUI/d3 app.

**Rollback at any wave:** `git revert` + delete `claims/`/`vector_index.db`; cards are
regenerable, and the pre-migration `entities/*.md` are recoverable from history. The bet is
bounded and reversible — just no longer *free*, which is now acceptable.

**Residual risks (carried from CCL, unchanged):** (1) predicate-normalization drift is the one
correctness-critical dependency — mitigated by the mandatory audit nudge and a hand-seeded
conservative `_predicates.yaml`; (2) Stage-3 single-vs-multi-valued judgment is one LLM call per
conflict candidate — lower-stakes because it is dated, sourced, git-reversible; (3) the
"human hand-edits a generated card" footgun — mitigated by routing all edits through claims/app,
making the card read-only; (4) `observer` under-use if the extractor defaults everything to
`agent` — mitigated by a deliberate prompt rule + a post-first-Sleep audit (and now *visible* in
the app, so under-use is immediately obvious). New risk: (5) transclusion cycles/expansion blow-up
— mitigated by the depth cap + cycle-guard + dedup-by-id in the resolver.

---

## Decisions Rodrigo must make before build

1. **Per-subject claim files vs one-file-per-claim.** Recommend per-subject
   (`claims/<x>.claims.yaml`) — keeps git blame meaningful and file count bounded (~1,882), the
   TFG/PBM consensus.
2. **Card edit policy.** Recommend cards strictly read-only (`generated: true`), all edits via
   app→claim writes; only `_preferences.md`/`_procedures/` are human-authored prose. This closes
   PBM's overwrite footgun.
3. **Observer cardinality.** Start `agent | rodrigo | external:<name>`; `external:<name>` is the
   high-value provenance case (media/RSS). Same as CCL.
4. **Transclusion depth cap.** Recommend 2 (embed-of-embed, then stop) + cycle-guard.
5. **Run the full extraction backfill for the thesis Results, or stay lazy?** With migration
   demoted, recommend the **full ~$2–6 backfill** for a uniform store and clean Results numbers.
6. **App demo scope for the thesis.** Observer lens + time-scrubber are the two highest-impact;
   contradiction overlay and perspective pivot are the next tier; transclusion rendering ties
   C10 and C11 together. Recommend shipping all five — they are read-only projections, cheap once
   the store exists.
