# Sleep Trust-Reconciliation Design (M5e — Stage 3)

**Status:** PREP / DESIGN ARTIFACT. Pseudocode + decision tables only — no code, no commit.
**Author:** M5e prep agent, 2026-06-17.
**Authoritative basis:** `docs/goals/d2-architecture-final.md` — the top **ADDENDUM (CONFIRMED,
AUTHORITATIVE)**, points (3a)–(3d). Where the body of that doc says "read-only generated card" or
"separate `claims/` store", the addendum overrides: **the editable page is the source of truth, claims
live IN the page in a ` ```claims ` YAML block, the index is derived.**
**Grounded against real code:** `api/services/claims.py` (the M5a `Claim` dataclass + `parse_claims` /
`write_claims`), `api/services/conflict_resolver.py` (`resolve_and_prune`, `_detect_contradiction`),
`api/services/entity_resolver.py` (Stage 2), `api/services/entity_body.py` (section-aware
parse/merge/render), `api/services/sleep_cycle.py` (the 5 stages + `_finalize`).

---

## 0. The core decision rule (read this first)

> **A new claim and an existing claim that share the mechanical key
> `K = (subject, predicate, context, observer)` are *the same belief slot*. What happens in that slot is
> decided by TRUST, never by recency alone:**
>
> 1. **Agent never silently overwrites a human.** If `existing.source_trust == user_stated` and the
>    incoming claim is `agent_extracted` / `agent_reflected` / `external`, the agent claim **may NOT
>    close (supersede / set `valid_to`) the human claim.** It either **coexists** (different
>    object → the human belief stays open, the agent belief is recorded but flagged) or becomes a
>    **conflict nudge** (contradictory object → ask the human; do not auto-resolve).
> 2. **Only a newer *human-sourced* claim supersedes a human claim.** A human changes a memory the
>    *preferred* way — by clarifying/conversing (`origin: manual_edit | clarification`,
>    `source_trust: user_stated`). That is a high-trust supersede and IS allowed to close the old human
>    claim.
> 3. **Agent-over-agent is the mechanical TFG path** — newer agent claim on a single-valued key closes
>    the older agent claim (`valid_to = new.valid_from`, `superseded_by`, `supersedes`). Nothing is
>    deleted; the closed claim stays in the YAML for the timeline + `git blame`.
> 4. **Page prose is merged section-aware (`entity_body.py`), never regenerated** — human-authored
>    sections survive; only the machine ` ```claims ` block and agent-owned sections are rewritten.
>
> In one line: **trust gates *who may close whom*; the mechanical predicate key decides *which slot*;
> recency only breaks ties *within the same trust tier*; nothing is ever deleted.**

---

## 1. Where this runs in the pipeline

This redesign replaces the body of `conflict_resolver.resolve_and_prune` (Stage 3) and the body-merge
half of `apply_changes` (Stage 5 write). Stages 1–2 are unchanged in shape; they gain claim-emission:

- **Stage 1 (extract):** each extracted fact carries `observer/context/epistemic/source_trust` (per
  addendum (4) and the D2 schema). Routine extraction defaults to
  `observer: agent, source_trust: agent_extracted, origin: <harness>`. Manual-edit / clarification
  resolution paths (companion app, nudge resolve) inject `source_trust: user_stated, observer: rodrigo,
  origin: manual_edit | clarification`.
- **Stage 2 (resolve):** `subject`/`object` strings → subject-ids (existing resolver); `predicate`
  normalized against `_predicates.yaml`; each claim routed to its subject page's ` ```claims ` block
  (parsed by `claims.parse_claims`).
- **Stage 3 (THIS DOC):** for every incoming claim, find the same-key existing claims and apply the
  trust-reconciliation decision table below. Emit superseded-stamps, conflict nudges, or coexist
  records. Run decay (per-epistemic × trust table) on unreferenced claims.
- **Stage 5 (write):** `claims.write_claims(body, reconciled_claims)` updates the machine block;
  `entity_body` section-aware merge updates the prose, **preserving human sections**; commit with
  `Cicada-Author` trailers.

**Definitions used throughout:**

```
K(claim)           := (claim.subject, claim.predicate, claim.context, claim.observer)   # mechanical key
is_human(c)        := c.source_trust == "user_stated"
                       and c.origin in {"manual_edit", "clarification"}      # both required (see §6)
is_agent(c)        := c.source_trust in {"agent_extracted", "agent_reflected"}
is_external(c)     := c.source_trust == "external"
open(c)            := c.valid_to is None                                      # currently-valid claim
same_object(a, b)  := normalize(a.object) == normalize(b.object)             # despace+lowercase, _normalize_fact-style
single_valued(K)   := predicate is single-valued (see §5; LLM-assisted, _predicates.yaml-cached)
```

---

## 2. The reconciliation algorithm (pseudocode)

```python
def reconcile_stage3(incoming_claims, existing_claims_by_subject, settings):
    """Stage 3: trust-gated invalidate-and-supersede over claims. Nothing deleted.

    incoming_claims: list[Claim]      # from Stage 1+2, fully routed (subject-id, normalized predicate)
    existing_claims_by_subject: dict[subject_id, list[Claim]]   # parsed from each page's ```claims block
    returns: (reconciled_by_subject, conflict_nudges, audit_records)
    """
    reconciled = {sub: list(claims) for sub, claims in existing_claims_by_subject.items()}
    conflict_nudges = []
    audit = []
    referenced_subjects = set()

    for new in incoming_claims:
        sub = new.subject
        referenced_subjects.add(sub)
        slot = reconciled.setdefault(sub, [])

        # All OPEN existing claims sharing the mechanical key (same belief slot).
        same_key_open = [c for c in slot if open(c) and K(c) == K(new)]

        if not same_key_open:
            # First belief in this slot — just add it (with provenance defaults filled).
            slot.append(_stamp_new(new))
            continue

        # Is this slot single- or multi-valued? (cached; one LLM call worst case — §5)
        sv = single_valued(new.predicate, settings)

        if not sv:
            # Multi-valued relation (uses, relates-to, tagged-with, recommended ...).
            # Co-existence is the default: add unless an exact (same-object) duplicate exists.
            dup = next((c for c in same_key_open if same_object(c, new)), None)
            if dup is None:
                slot.append(_stamp_new(new))
            else:
                _reinforce(dup, new)           # bump confidence/last_seen, merge source_episodes; no supersede
            continue

        # ----- SINGLE-VALUED: exactly one belief may be open in this slot -----
        # If the new object equals the open object, it's a reaffirmation, not a change.
        existing = same_key_open[0]            # invariant: single-valued ⇒ ≤1 open per slot
        if same_object(existing, new):
            _reinforce(existing, new)
            continue

        # Object differs → a real candidate change. TRUST decides the action.
        action = trust_decision(new, existing)     # the decision table in §3
        if action == "SUPERSEDE":
            _close(existing, by=new)               # valid_to = new.valid_from; superseded_by/supersedes
            slot.append(_stamp_new(new))
            audit.append(_supersede_audit(existing, new))
        elif action == "COEXIST_FLAG":
            # Agent disagrees with a human (or external w/ human). Keep human open,
            # record agent belief but DO NOT close the human. Surface gently.
            slot.append(_stamp_new(new, status_note="shadowed_by_human"))
            conflict_nudges.append(_soft_divergence_nudge(existing, new))
        elif action == "CONFLICT_NUDGE":
            # Can't safely auto-resolve. Add nothing as superseding; ask.
            conflict_nudges.append(_conflict_nudge(existing, new))
        elif action == "REJECT":
            # New claim is strictly weaker provenance trying to trample; drop it,
            # but record that we saw it (audit), never silently.
            audit.append(_rejected_audit(existing, new))
        elif action == "KEEP_BOTH":
            slot.append(_stamp_new(new))           # genuinely different perspective slipped the key

    # Decay over claims NOT referenced this cycle (per-epistemic × trust — §7).
    decay_claims(reconciled, referenced_subjects, settings)
    return reconciled, conflict_nudges, audit
```

`_stamp_new` fills `recorded_at = today`, `valid_from = new.valid_from or earliest source-episode date`,
`authored_by = settings.litellm_model` (or `user` for manual), preserves `origin`.
`_close(old, by=new)` sets `old.valid_to = new.valid_from`, `old.superseded_by = new.id`,
`new.supersedes = old.id`. **No list element is ever removed** — closed claims stay for the timeline.

---

## 3. The trust decision table (single-valued, differing object, same key)

This is the heart of M5e. It is reached only when: same mechanical key `K`, both open, single-valued
predicate, **objects differ** (a genuine candidate change). `trust_decision(new, existing)` returns one
of `SUPERSEDE | COEXIST_FLAG | CONFLICT_NUDGE | REJECT | KEEP_BOTH`.

Read `new.source_trust` down the side, `existing.source_trust` across the top. (`user_stated` here means
the full human predicate `is_human` — `user_stated` **and** `origin ∈ {manual_edit, clarification}`; see
§6 for the degenerate "user_stated but agent-origin" case.)

| new ↓ \ existing → | **user_stated** (human) | **agent_extracted** | **agent_reflected** | **external** |
|---|---|---|---|---|
| **user_stated** (human) | **SUPERSEDE** if newer `valid_from`; else CONFLICT_NUDGE¹ | **SUPERSEDE** (human corrects agent) | **SUPERSEDE** (human corrects agent) | **SUPERSEDE** (human corrects external) |
| **agent_extracted** | **COEXIST_FLAG** (never close a human) ² | **SUPERSEDE** if newer; else CONFLICT_NUDGE³ | **SUPERSEDE** (extracted > reflected) | **SUPERSEDE** (fresh extraction > stale external) ⁴ |
| **agent_reflected** | **COEXIST_FLAG** ² | **REJECT** (don't let a guess close an observation) ⁵ | **SUPERSEDE** if newer; else KEEP_BOTH⁶ | **COEXIST_FLAG** (reflection ≠ external assertion) |
| **external** | **COEXIST_FLAG** ² (external can't close Rodrigo) | **CONFLICT_NUDGE** ⁷ | **SUPERSEDE** (external assertion > agent guess) | **SUPERSEDE** if newer source; else KEEP_BOTH⁸ |

**Footnotes (the load-bearing edge cases):**

1. **Human-over-human, same key, differing object.** This is rule (3b)/(3d): a human changed their own
   memory. If `new.valid_from > existing.valid_from` it is a clean supersede (preferred path — Rodrigo
   re-clarified). If the dates are equal/ambiguous (two human edits in the same day with no temporal
   cue), do **not** guess — `CONFLICT_NUDGE` asking which is current. **Recency only decides among human
   claims.**
2. **Agent / external vs an open human claim → `COEXIST_FLAG`, NEVER `SUPERSEDE`.** This is rule (3a),
   the addendum's central protection: routine extraction "cannot trample" a human belief. The agent
   claim is *recorded* (so retrieval/`/ask` can see the agent currently believes X) but the human claim
   **stays open and authoritative**; a soft "you said A, I'm now seeing B — still A?" divergence nudge
   is emitted. The human belief is overwritten **only** by the human themselves (row 1).
3. **Agent-over-agent, ambiguous recency.** The mechanical TFG path *needs* a temporal cue. If `new`
   has a strictly newer `valid_from`, `SUPERSEDE` (the Postgres→sqlite-vec worked example). If there is
   **no date cue to decide which is current** (two agent extractions across two conversations, neither
   dated as "switched") → `CONFLICT_NUDGE` — exactly the case `_detect_contradiction`'s
   `has_unresolvable_contradiction` already catches today, now keyed mechanically first.
4. **Agent-extracted (observation) vs external (a source's assertion).** A fresh observation of
   Rodrigo's actual state outranks a stale external claim → `SUPERSEDE`. (If the external is *newer* and
   high-trust, fall to `CONFLICT_NUDGE`.)
5. **`agent_reflected` may not close `agent_extracted`** — a low-trust inference must not retire a
   direct observation. `REJECT` (audited, not silent). The reflection can still *coexist* as a
   cross-context bridge under a different `context`, where its key differs.
6. **Reflection-over-reflection** with no recency cue → `KEEP_BOTH` (two abductive guesses; let decay
   prune the weaker — both are fast-decay).
7. **External-over-agent-extracted, differing object → `CONFLICT_NUDGE`.** A source contradicts the
   agent's own observation of Rodrigo; that's a genuine "who's right" question, not auto-resolvable.
8. **External-over-external**, newer source supersedes; tie → `KEEP_BOTH` (two sources disagree; both
   attributed, surfaced as divergence).

**Symmetric guarantee:** scan the **user_stated column** — every cell is `COEXIST_FLAG` or
`CONFLICT_NUDGE` *except* the human-over-human cell. **No agent/external claim can ever produce
`SUPERSEDE` against a human claim.** That single column is the formal statement of addendum rule (3a)+(3b).

---

## 4. Full case enumeration: (new.source_trust × existing.source_trust × same-key?)

The decision table in §3 assumes same-key + single-valued + differing object. The complete space the
implementation must handle:

| # | same key `K`? | predicate | object | new.trust | existing.trust | **Action** |
|---|---|---|---|---|---|---|
| C0 | no same-key open claim | — | — | any | — | **ADD** (new slot; `_stamp_new`) |
| C1 | yes | multi-valued | new object | any | any | **COEXIST** (add; no supersede) |
| C2 | yes | multi-valued | duplicate object | any | any | **REINFORCE** (bump conf, merge episodes) |
| C3 | yes | single-valued | same object | any | any | **REINFORCE** (reaffirmation, not a change) |
| C4 | yes | single-valued | differing | human | human | **SUPERSEDE** if newer; else **CONFLICT_NUDGE** (fn 1) |
| C5 | yes | single-valued | differing | agent | human | **COEXIST_FLAG** + soft divergence nudge (fn 2) |
| C6 | yes | single-valued | differing | external | human | **COEXIST_FLAG** + soft divergence nudge (fn 2) |
| C7 | yes | single-valued | differing | human | agent/external | **SUPERSEDE** (human corrects machine) |
| C8 | yes | single-valued | differing | agent | agent | **SUPERSEDE** if dated newer; else **CONFLICT_NUDGE** (fn 3) |
| C9 | yes | single-valued | differing | agent_reflected | agent_extracted | **REJECT** (audited) (fn 5) |
| C10 | yes | single-valued | differing | agent_extracted | agent_reflected | **SUPERSEDE** |
| C11 | yes | single-valued | differing | external | agent | **CONFLICT_NUDGE** (fn 7) / **SUPERSEDE** if external newer & extracted-stale (fn 4 mirror) |
| C12 | yes | single-valued | differing | external | external | **SUPERSEDE** if newer source; else **KEEP_BOTH** (fn 8) |
| C13 | **different observer** only | single-valued | differing | any | any | **KEEP_BOTH** — perspectival, NOT a conflict (agent-believes-X vs Rodrigo-asserts-Y) |
| C14 | **different context** only | single-valued | differing | any | any | **KEEP_BOTH** — faceted self (engineer-Rodrigo vs family-Rodrigo); no collapse |

**C13/C14 are the perspectival escape hatch and must be checked *inside* `K`-equality, not after.**
Because `observer` and `context` are *part of* the key, a claim with the same `(subject, predicate)` but
a different `observer` or `context` simply does not collide — it lands in a different slot and coexists.
This is what lets the agent hold "agent believes Rodrigo uses Postgres" alongside "Rodrigo asserts he
switched to sqlite-vec" without a false conflict: they differ on `observer`, so they never enter the
trust table at all.

---

## 5. Single-valued vs multi-valued: where the LLM is still needed

The mechanical key handles *which slot*; it cannot know whether a predicate is single-valued (a person
has one `current-employer`; a project `uses` many tools). Resolution order, cheapest first:

1. **`_predicates.yaml` cardinality map (deterministic, $0).** Seed it with the obvious cases:
   ```yaml
   predicates:
     uses:            { canonical: uses,            cardinality: multi }
     relates-to:      { canonical: relates-to,      cardinality: multi }
     recommended:     { canonical: recommended,     cardinality: multi }
     tagged-with:     { canonical: tagged-with,     cardinality: multi }
     current-employer:{ canonical: current-employer,cardinality: single }
     located-in:      { canonical: located-in,      cardinality: single }
     status:          { canonical: status,          cardinality: single }
     prefers:         { canonical: prefers,          cardinality: single }   # supersedable preference
     values:          { canonical: values,          cardinality: multi }     # can value many things
   ```
   Hit → no LLM call. This already exists as the Stage-2 normalization map per the D2 doc; we add a
   `cardinality` field. **Every auto-folded predicate still emits the mandatory `normalization-audit`
   nudge** (D2 Stage-3 requirement) so drift is visible.

2. **LLM fallback (one call per *unseen* predicate, cached into `_predicates.yaml`).** Only when the
   predicate is absent from the map AND a same-key collision with a differing object actually occurs (so
   we never pay for predicates that never conflict). Prompt: *"For predicate P on subject of type T, can
   a subject hold multiple simultaneously-true P relations, or only one at a time? Answer single |
   multi."* The answer is written back to `_predicates.yaml` (with an audit nudge) so the cost is
   amortized to roughly once per predicate over the system's lifetime. This is risk (2) in the D2 build
   plan — "one LLM call per conflict candidate, lower-stakes because dated, sourced, git-reversible."

3. **The contradiction judge (existing `_detect_contradiction`) is repurposed, not removed.** Today it
   answers "is this an unresolvable contradiction?" over free prose. In the claim world it is only
   invoked for the `CONFLICT_NUDGE` branches (C4-equal-date, C8-no-date-cue, C11) to *author the nudge's
   `contradiction` sentence + `options`* — it no longer decides supersession (the key + trust table do
   that). It keeps its exact JSON shape (`has_unresolvable_contradiction`, `contradiction`, `options`)
   so the inbox renderer is unchanged.

**Net LLM budget for Stage 3:** zero calls in the common path (mechanical); at most one cardinality call
per genuinely-new predicate (cached forever); one nudge-authoring call per claim that lands in a
`CONFLICT_NUDGE` cell. No LLM call ever decides whether a human claim is overwritten — that is pure trust
logic, by design (rule 3a must be deterministic and auditable).

---

## 6. The `user_stated`-but-not-human degenerate case (provenance integrity)

`is_human(c)` requires **both** `source_trust == user_stated` **and** `origin ∈ {manual_edit,
clarification}`. Why both: an `external` source could quote Rodrigo ("Rodrigo says he likes X"),
producing a claim the extractor might be tempted to tag `user_stated`. That is an *external observation
of* a user statement, not a *protected human edit*. Decision rule:

- `source_trust == user_stated` **and** `origin ∈ {manual_edit, clarification}` → **full human
  protection** (the user_stated column of §3).
- `source_trust == user_stated` **but** `origin ∈ {claude-code, codex, chatgpt-export, …}` (i.e. the
  user *said* it in a logged conversation, the agent extracted it) → treated as **`agent_extracted` for
  reconciliation purposes** (it can be superseded by a later extraction or a manual edit), but it keeps
  `source_trust: user_stated` in the record so retrieval still weights it as a first-person assertion.
  *Trust-for-overwrite-protection* (origin-gated) and *trust-for-retrieval-weight* (source_trust) are
  deliberately distinct.

This closes the spoofing hole where routine extraction could launder itself into overwrite-immunity by
self-labeling `user_stated`. **Protection is anchored to `origin`, which only the manual-edit and
clarification-resolution code paths may set** — never the extractor.

---

## 7. Decay (runs inside Stage 3, per-epistemic × source_trust)

Per the D2 decay table, replacing the per-entity `decay_rate` field. Decay applies to claims **not
referenced this cycle** and only *lowers confidence*; it never closes (`valid_to`) a claim and never
touches a human claim's *validity* — at most it nudges.

```
base = {explicit:0.02, deductive:0.05, inductive:0.10, abductive:0.20}[claim.epistemic]
factor = {user_stated:0.3, agent_extracted:1.0, agent_reflected:1.5, external:1.0}[claim.source_trust]
claim.confidence = max(0.0, claim.confidence - base*factor*(days_since_referenced/7))
if claim.confidence < archive_threshold(0.2):  -> mark subject 'decaying'/archive nudge (page-level), claim stays valid
if claim.confidence < decay_nudge_threshold(0.4): -> decay nudge
```

`user_stated` claims decay at 0.3× — a human belief fades ~3× slower than a routine extraction and an
abductive bridge self-prunes in ~10 cycles. **Decay lowers `confidence` (the retrieval weight); it does
NOT supersede.** A human claim never silently disappears via decay; it can only be retired by a newer
human claim (§3 row 1).

---

## 8. Page augmentation: section-aware MERGE preserving human prose (rule 3c)

Stage 5 writes two layers into each touched page; **they are kept strictly separate so human prose is
never regenerated:**

1. **The machine ` ```claims ` block** — fully owned by Sleep. `claims.write_claims(body,
   reconciled_claims)` replaces *only* the fenced block in place (M5a guarantees all surrounding prose is
   preserved verbatim, `parse_claims(write_claims(body, claims)) == claims`). Closed/superseded claims
   stay in the list (timeline + `git blame` on the `valid_to:` line).

2. **The human-readable prose sections** — merged with `entity_body.py`, never wholesale-replaced:
   ```python
   sections = entity_body.upgrade_legacy_to_v2(parsed.body, type)     # lift to canonical sections
   # Agent may augment only agent-owned sections (Summary, Key Facts, History, Links, Open Questions).
   sections = entity_body.merge_sections_fallback(sections, new_fields)  # union+dedupe, no blob-append
   # Human-authored sections are PRESERVED untouched:
   #   - any section the parser found that is NOT in CANONICAL_SECTIONS  (hand-added headings)
   #   - _preferences.md / _procedures/* are SEPARATE FILES — Sleep never overwrites them at all
   ```
   `merge_sections_fallback` already unions Key Facts / Links / Open Questions and appends-not-replaces
   Summary (it appends a follow-on sentence rather than stacking paragraphs). The one new rule M5e adds:
   **if a section was authored by a human edit (page has `human_edited: true` or the section is
   non-canonical), the agent merge is *additive only* — it may append a deduped bullet but may not
   rewrite or remove an existing human line.** Contradictions between human prose and a new agent claim
   surface as the §3 `COEXIST_FLAG` divergence nudge, not as a prose rewrite.

   **The LLM synthesis path (`_synthesize_entity_update`) is gated behind human-edit detection:** it may
   run freely on agent-only pages, but on a human-edited page it is either skipped (deterministic
   `merge_sections_fallback` only) or prompted with an explicit *"preserve every existing sentence and
   wikilink; you may only ADD"* constraint. This is the prose-level mirror of rule (3a): the LLM may not
   regenerate-away human prose any more than an agent claim may close a human claim.

---

## 9. Borderline → conflict nudge (when in doubt, ask)

Cases that become `CONFLICT_NUDGE` rather than an auto-resolution, all surfaced to the companion-app
inbox via the existing `inbox_generator`/`conflict_nudge` change shape (so no new UI is needed — the
nudge carries `conflict_context`, `options`, `source_episode`, `trigger: sleep/conflict_resolution`):

- **C4 human-vs-human, equal/ambiguous date** — two manual edits, no temporal ordering ("which is
  current?").
- **C8 agent-vs-agent, no recency cue** — the classic two-conversations-no-date contradiction; this is
  the only place the legacy `_detect_contradiction` judge still decides *whether* it's unresolvable.
- **C11 external-vs-agent-observation** — a source disagrees with what the agent observed of Rodrigo.
- **`single_valued` LLM call returns low confidence** — if the cardinality judge is itself unsure
  whether the predicate is single-valued, treat as multi-valued **and** emit a low-priority audit nudge
  (coexist is the safe default; never auto-close on an uncertain cardinality).
- **Predicate normalization auto-fold** — mandatory `normalization-audit` nudge on every predicate the
  Stage-2 map collapsed (D2 requirement), so silent predicate drift can't corrupt the key.

`COEXIST_FLAG` (agent disagreeing with a human, C5/C6) emits a **soft divergence nudge** — lower urgency
than a hard conflict: "You said A; I'm now reading B from <episode>. Keep A?" with options `[Keep my
statement (A)]` / `[Update to B]` / `[Both true — different context]`. Choosing "Update to B" creates a
new `user_stated, origin: clarification` claim that *then* legitimately supersedes the old human claim
via §3 row 1 — i.e. the human edits their memory through the preferred conversational/clarification path,
exactly as rule (3d) requires. **The agent never makes that change on its own.**

---

## 10. Invariants the implementation must preserve (test checklist)

1. **No agent/external write ever sets `valid_to`/`superseded_by` on a claim where `is_human` is true.**
   (Formal statement of rule 3a; the user_stated column of §3 has zero `SUPERSEDE` cells except
   human-over-human.)
2. **A human claim is superseded only by a newer human claim** (`is_human(new)` and
   `new.valid_from > existing.valid_from`). (Rule 3b.)
3. **Nothing is ever removed from a ` ```claims ` list** — superseded claims are stamped, not deleted.
   (Mechanical invalidate-and-supersede; timeline/`git blame` depend on it.)
4. **No human-authored prose section is rewritten or has a line removed** by an agent Sleep pass.
   (Rule 3c; `merge_sections_fallback` additive-only on human-edited pages; `_preferences.md`/
   `_procedures/` never touched.)
5. **Same `(subject, predicate)` but different `observer` or `context` never collide** — they coexist
   (C13/C14). The trust table is *only* reached on full-key equality.
6. **The overwrite-protection trust is `origin`-gated**, so the extractor cannot self-label its way into
   immunity (§6).
7. **Stage 3 makes zero LLM calls in the common (mechanical) path**; LLM use is bounded to unseen-
   predicate cardinality (cached) + nudge authoring on conflict cells.
8. **Round-trip:** after Stage 5, `parse_claims(page.body)` returns exactly the reconciled claim list
   (M5a invariant), and the derived index rebuilds from it.

---

## 11. Mapping to the existing code (what M5e touches — for the implementing agent, NOT done here)

- `conflict_resolver.resolve_and_prune` — body replaced by `reconcile_stage3` (§2). Keep the function
  signature `(resolved, existing, settings) -> changes` so `sleep_cycle.run` Stage 3 is unchanged; the
  `changes` list gains `claims`-shaped entries + `conflict_nudge`/`divergence_nudge`/`audit` records.
- `conflict_resolver._detect_contradiction` — kept, narrowed to nudge-authoring for `CONFLICT_NUDGE`
  cells only (§5.3).
- `claims.parse_claims` / `claims.write_claims` (M5a) — the read/write seam for the machine block; used
  by Stage 2 (route-in) and Stage 5 (write-out). No change needed.
- `entity_body.merge_sections_fallback` / `upgrade_legacy_to_v2` / `render_sections` — the prose-merge
  seam (§8); gains the additive-only-on-human-edit rule.
- `_predicates.yaml` — gains a `cardinality` field per predicate (§5); seeded conservatively, extended
  via cached LLM cardinality calls with audit nudges.
- `inbox_generator` / the `conflict_nudge` change shape — reused verbatim for `CONFLICT_NUDGE` and the
  new soft `divergence_nudge` (§9). No new endpoint.
- `git_service.build_commit_message(..., authors=...)` — unchanged; `authored_by` on each claim feeds
  the `Cicada-Author` trailer (`user` for manual/clarification, model id for agent).

> Scope note: this artifact is **design only**. A separate concurrent workflow owns the M5a/M5e code in
> `api/`. Nothing here was implemented or committed.
