# Predicate Normalization — Rationale & Audit Seed (M5 prep)

Companion to `predicates-seed.yaml`. This is a DESIGN/DATA artifact only — no code, no
commits. It documents how the seed was derived, the evidence (frequency table), and the
explicit list of predicates left UNFOLDED for the mandatory normalization-audit nudge.

## Why this is the #1 correctness risk

CPCG stores claims as `(subject, predicate, object)` with bi-temporal validity and
`superseded_by`. Contradiction detection on **single-valued** predicates ("X uses ONE
primary store") depends entirely on predicates being **canonical**: if `chose`, `selected`,
and `picked` are three distinct keys, the system never notices that "chose SQLite" supersedes
"chose Postgres" — the conflict is invisible. Conversely, over-eager folding collapses
genuinely different relations and manufactures false contradictions. The seed therefore
folds **conservatively** and routes everything uncertain to an audit nudge.

## Method

1. **Source of vocabulary.** Extracted every `label:` value from `memory/graph_edges.yaml`.
   The entity `related:` frontmatter fields were sampled and found to be **untyped bare
   wikilinks** (e.g. `related: [openmp-taskloop, simd]`) — they carry NO predicate
   semantics. So 100% of the relation vocabulary comes from edge labels.
2. **Frequency analysis.** Normalized quoting/whitespace, then `sort | uniq -c`. Result:
   **4571 edges, 2446 distinct labels** — an extreme heavy tail.
3. **Conservative clustering.** Folded only labels that are (a) the same relation and
   (b) the same direction. Three fold types allowed:
   - *Morphological/tense*: `worked at` -> `works-at`, `used` -> `uses`.
   - *Modality-stripped*: `may use`/`can use`/`plans to use` -> `uses` (the modality is a
     candidate epistemic flag, noted, not a separate predicate).
   - *Clear lexical synonyms*: `is based in`/`located in`/`operates in` -> `located-in`.
4. **Direction guard.** Passive/inverse phrasings (`is used by`, `is sponsored by`,
   `hosted by`) were placed in `inverse_pairs` (flip-then-canonicalize), **never** in
   `synonyms` — folding them naively would reverse the edge.
5. **Contradiction typing.** Split canonicals into `single_valued` (contradiction keys)
   vs `multi_valued` (coexist), with caveats noted where object-typing is needed to be safe.
6. **Audit routing.** Any HEAD label whose fold target was not unambiguous, plus the entire
   freq==1 long tail (as a class), is flagged for the mandatory normalization-audit nudge.

## Distribution summary

| Metric | Value |
|---|---|
| Total edges | 4571 |
| Distinct raw labels | 2446 |
| Labels with freq >= 3 | 285 (cover 2076 edges) |
| Labels with freq >= 2 | 619 (cover 2744 edges) |
| Labels with freq == 1 (long tail) | 1827 |
| Single most common label (`uses`) | 232 (~5% of all edges) |
| Entity `related:` predicates | 0 (untyped wikilinks) |

The top label `uses` alone is 232 occurrences; the next twenty cover the bulk of typed
meaning. The 1827 singletons are mostly bespoke natural-language phrasings
("enables interactive 3D axes in", "creates networking opportunity for") that should NOT be
auto-folded — they are audited as a class.

## Frequency table — head of the distribution (folded variants grouped under canonical)

(Counts are raw-label occurrences from `graph_edges.yaml`.)

### `uses` cluster (canonical: `uses`) — single-valued (primary), AUDIT for object-typing
| raw label | freq | fold |
|---|---|---|
| uses | 232 | canonical |
| used | 20 | -> uses |
| built with | 14 | -> uses |
| may use | 10 | -> uses |
| built on | 9 | -> uses |
| can use | 8 | -> uses |
| is built on | 7 | -> uses |
| wants to use | 5 | -> uses |
| could use | 4 | -> uses |
| is built with | 3 | -> uses |
| powers | 3 | -> uses |
| is powered by | 3 | -> uses (inverse pair) |
| would use / use / plans to use / backend uses | 2 each | -> uses |
| powered by | 1 | -> uses (inverse pair) |
| **built** | 16 | **UNFOLDED — ambiguous (uses vs creates vs located-at)** |

### `includes` / `part-of` / `contains` cluster (composition)
| raw label | freq | canonical |
|---|---|---|
| includes | 76 | includes |
| is part of | 36 | part-of |
| contains | 28 | contains |
| belongs to | 9 | part-of |
| part of | 5 | part-of |

### `works-*` cluster (person/org/project)
| raw label | freq | canonical |
|---|---|---|
| works at | 35 | works-at |
| works with | 16 | works-with |
| worked at | 11 | works-at |
| works for | 8 | works-at |
| works on | 7 | works-on |
| works in | 7 | **UNFOLDED — location vs role ambiguity** |
| interned at | 4 | works-at |
| worked with/on, previously worked at, worked in | 2-3 each | works-with/-on/-at |

### location cluster (canonical: `located-in` / `takes-place-in`)
| raw label | freq | canonical |
|---|---|---|
| is based in | 13 | located-in |
| takes place in | 9 | takes-place-in |
| is located in | 9 | located-in |
| located in | 6 | located-in |
| takes place at | 5 | takes-place-in |
| operates in | 5 | located-in |
| held at / hosted at | 3 each | takes-place-in / hosts (audit) |

### other high-frequency canonicals (kept as-is)
| canonical | freq |
|---|---|
| supports | 53 |
| implements | 49 |
| depends on | 39 |
| provides | 31 |
| hosts | 26 |
| requires | 23 |
| connects to | 19 |
| sponsors | 20 |
| contrasts with | 16 |
| compares against | 13 |
| integrates with | 12 |
| enables | 12 |
| references | 10 |
| is considering | 11 |

## FLAGGED — uncertain, left UNFOLDED, MUST go through the normalization-audit nudge

These are NOT auto-folded. The audit nudge should ask the user/operator to confirm a target.

1. **`built`** (16) — bare verb. Could be `uses` (built-with), `creates` (built X), or
   `located-in`/`built-at`. Direction and object type unknown. HIGH PRIORITY.
2. **`works in`** (7) — role-in-field ("works in robotics") vs location ("works in Madrid").
   Disambiguate by object type (concept vs location).
3. **`has`** (5) — too generic; could map to `includes`, `provides`, or `located-in`.
   Explicitly NOT folded.
4. **Phrase-split risks** — canonical head matches but the tail changes the relation:
   - `is a construct in`, `is a feature of` -> should be **part-of**, NOT `is-a`.
   - `is a role at` -> employment/role, not classification.
   - `uses for retrieval`, `uses for dashboard`, `uses as frontend` — object-qualified
     `uses`; decide whether to strip the qualifier or retain as claim context.
5. **`supports`** (53), **`provides`** (31), **`hosts`** (26) — kept canonical but each spans
   multiple object types (capability vs endorsement; service vs access; infra vs event
   hosting). Object-typing recommended before treating any as single-valued.
6. **`depends-on`** (39) vs **`requires`** (23) — overlapping; kept separate. single- vs
   multi-valued unresolved without object typing (a project legitimately has many deps).
7. **`relates-to` SINK** — verify during audit that no single-valued relation was dumped into
   the generic association bucket via `is associated with` / `is relevant to`.
8. **Entire freq==1 long tail (1827 labels)** — audited as a class. Default action: keep
   verbatim OR map to `relates-to` only with confirmation; never silently fold.

## Single- vs multi-valued (contradiction keys) — design note

`single_valued` predicates are the ones M5 reconciliation watches for contradictions: a
second *valid* (non-superseded) object on the same `(subject, predicate)` triggers
conflict-resolution. The honest caveat: real graphs in `memory/` legitimately list
**multiple** `uses` edges per subject (a project uses many tools). So `uses` is single-valued
ONLY for the "primary X of a kind" sense (primary store, primary runtime). Making this safe
requires object-typing (is this the primary datastore, or just one of many libraries?). Until
that typing exists, the audit nudge should treat single-valued `uses`/`depends-on` conflicts
as **proposals**, not auto-supersessions — consistent with the architecture's
"agent proposes, user disposes" and trust-protected human claims.

## Handoff

`predicates-seed.yaml` seeds `memory/_predicates.yaml`. Before first production fold, run the
mandatory normalization-audit nudge over (a) the `uncertain_flag_for_audit` list and (b) the
freq==1 tail. Re-derive frequencies after any large ingestion, since the head can shift.
