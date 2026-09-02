# Inbox questions — time-aware, deduplicated conflict resolution + fact sources (G60, G61)

**Status:** approved for implementation 2026-08-30 (Rodrigo: "go ahead and work on all these things until done").
**Backlog:** G60 (conflict resolution, Claude-Code style), G61 (update sources for facts).
**Bug that triggered it:** two open "Conflicting beliefs about Rodrigo Sagastegui (works-at): 'mongodb' vs 'supahost'" cards, created 2026-06-18 from claims observed 2026-02-18 — neither value is current, the card offers no way to say so, and the same question was written twice.

## 1. Problems in the current code

| # | Problem | Where |
|---|---------|-------|
| P1 | **No dedup.** Nothing checks for an open item on the same `(entity_id, predicate)` before writing a new `inbox-NNN.md`. | `inbox_generator.write_claim_nudges`, `write_nudges` (entity path) |
| P2 | **Time is ignored.** The item carries `created_date` only. Each competing claim's `valid_from` / `recorded_at` and the entity's `last_referenced` are known at generation time and never copied on. | `claim_reconciler._conflict_nudge`, `inbox_generator` |
| P3 | **Closed answer set.** Options are `[A, B, "Both are true (different contexts)"]`. No "neither — here's what's true", no free text, no "remind me later". | `InboxCardView` `.choice` branch |
| P4 | **Lossy resolve.** `_resolve_conflict` feeds the button label verbatim into an LLM body rewrite; `claim_id` / `existing_claim_id` are dropped by `_item_from_file` and ignored on resolve, so no claim is superseded or closed. "Both are true (different contexts)" is written into the entity body as a description. | `inbox_service._resolve_conflict`, `_item_from_file` |
| P5 | **Stale questions never refresh or close.** A later conversation that mentions the current employer produces a *new* claim (and possibly a third conflict) but never touches the open one. | Stage 3 |

## 2. Design

### 2.1 The question object (wire + file)

Every inbox item of kind `conflict`, `clarification`, or `merge_suggestion` carries a **question object** modelled on Claude Code's `AskUserQuestion`:

```yaml
question: "Where does Rodrigo work now?"          # one sentence, model-written (template fallback)
options:
  - key: a                                        # stable within the item
    label: MongoDB
    description: "Last mentioned 2026-02-18 · 6 months ago · extracted from ep_2026-02-18_004"
    claim_id: clm_2026-02-18_476e53d0
    observed_at: "2026-02-18"                     # claim.valid_from
    last_referenced: "2026-02-18"                 # bumped by Stage 3 when re-mentioned
    age_days: 193                                 # computed at read time, not stored
  - key: b
    label: Supahost
    description: "Last mentioned 2026-02-18 · 6 months ago"
    claim_id: clm_2026-02-18_a4acea50
    observed_at: "2026-02-18"
    last_referenced: "2026-02-18"
  - key: both
    label: "Both are true (different contexts)"
    description: "Keep both claims, each tagged with its context"
allow_other: true                                 # free-text "Other…" row
allow_defer: true                                 # "Not sure / remind me later"
predicate: works_at
remind_after: null                                # ISO date set by defer
```

- `question`, per-option `description` are written **at generation time**. Claim-path conflicts use a template (`"Where does {name} {predicate-verb} now?"` via a small predicate→verb table in `predicates.py`; unknown predicates fall back to `"Which is true about {name} ({predicate})?"`). The entity-path (`conflict_resolver`) already calls the LLM — its prompt is extended to return `question` and per-option `description` too; on parse failure the template is used.
- Descriptions always begin with the **age phrase** (`humanize_age(observed_at, today)` → "today", "3 days ago", "6 months ago", "a year ago") so the user sees staleness before choosing.
- `age_days` is derived in `_item_from_file` from `last_referenced` (fallback `observed_at`), never persisted.
- The legacy flat `options: [str]` remains readable (`_item_from_file` upgrades it to `{key: str(i), label: s}`); the app renders both shapes. New writes always emit the object form.

### 2.2 Dedup and merge-on-collision

Key = `(entity_id, predicate)` for conflicts (`predicate` is required on new conflict items; entity-path conflicts get `predicate: "description"`). `inbox_generator` gains `find_open(memory_path, kind, entity_id, predicate)`; before writing a conflict:

- **No open item** → write a new file.
- **Open item exists** → merge: any competing value not already an option is appended as a new option (new `key`, its own `claim_id`/`observed_at`); values already present get their option's `last_referenced` bumped to the new claim's `valid_from`; the `question` is kept; `created_date` is kept, a new `updated_date` is written; the item is **not duplicated**. The new claim id is recorded so resolve can close it.
- `merge_suggestion` dedup key = the sorted pair of entity ids; `clarification` key = `(entity_id, uncertainty_type)`. Same `find_open` helper, merge = bump `updated_date` only.
- One-shot migration `inbox_migration.dedup_open_items()` runs at backend start (idempotent, same place the existing inbox migration runs): collapses existing duplicate open items into the oldest one using the same merge rule, deletes the rest, commits `inbox/dedup`.

### 2.3 Time as a signal (Stage 3 re-scoring)

Each Sleep, after `reconcile_stage3`, a new step `refresh_open_questions(memory_path, claims_by_subject, today)`:

1. For every open conflict item, for every option with a `claim_id`: if that claim is still open and was reinforced this cycle (`recorded_at` newer than the option's `last_referenced`), bump `last_referenced` and re-order options so the most recently referenced value is first.
2. **Organic resolution (path 1):** if a claim with the same key `K` now exists with `source_trust == user_stated` (a human said it), or if one of the option claims has been **superseded** (`valid_to` set) by the reconciler, the item is resolved automatically: the surviving open claim wins, the item file is removed, commit trigger `inbox/organic_resolution`. Result is listed in the Sleep summary (`organic_resolutions: n`).
3. **Stale escalation:** if *every* option's `last_referenced` is older than `stale_after_days` (default 90, settings), the question text is rewritten to the stale template — "It's been 6 months since either came up. Is Rodrigo still at one of these?" — and a synthetic option `neither` (`label: "Neither anymore"`, `description: "Close both; tell me what's current below"`) is inserted first. Priority drops from 0.8 to 0.6 so fresh conflicts sort above stale ones.
4. Deferred items (`remind_after` in the future) are hidden from `GET /inbox` and from `cicada_check_nudges` until the date passes; the file stays.

### 2.4 Resolve semantics

`InboxResolveRequest` gains `option_key: str | None` (the app sends the key; `answer` remains for free text). `_resolve_conflict` becomes claim-aware:

| Action | Effect on claims | Effect on entity page |
|--------|------------------|-----------------------|
| `resolve` + `option_key` of a claim-backed option | Winning claim: `confidence = max(conf, 0.9)`, `source_trust` stays; **every other option claim is closed** (`_close(old, by=winner)`, `valid_to = today`). | `last_referenced = today`, `version += 1`; body rewritten by `_synthesize_entity_update` with `new_description = "<name> <verb> <label> (confirmed by user on <today>)"` — the existing LLM path, now fed a sentence, not a button label. |
| `resolve` + `option_key: both` | All option claims kept open; each gets `context` set to a distinct value if still `general` (`context = f"as of {observed_at}"`). | as above with "Both are true: …" |
| `resolve` + `option_key: neither` **or** `answer` (free text) | All option claims closed by a **new `user_stated` claim** `{subject: entity_id, predicate, object: <answer or "unknown">, valid_from: today, observer: user, authored_by: "user", confidence: 0.95}` written via the existing claim writer. If the free text is empty and `neither` was chosen, `object = ""` and no new claim is written — the old ones are simply closed. | as above with the user's sentence |
| `defer` | none | `remind_after = today + 30d` (or `request.remind_days`) written to the item; item stays. |
| `skip` | unchanged (kept for compat) | none |

Git trailers: `Cicada-Author: user` for all four. Commit body lines follow the existing `inbox/conflict/resolved` pattern plus one `entities/<id>.md: updated (source: inbox-NNN, trigger: inbox/conflict/resolved)` line per closed claim's page.

### 2.5 Fact sources (G61, minimal slice)

New frontmatter key on entity pages:

```yaml
sources:
  - ref: https://www.linkedin.com/in/rodrigosagastegui
    kind: url            # url | path | note
    predicate: works_at  # optional — which fact this source refreshes
    added_by: user       # model id or "user"
    added_at: "2026-08-30"
  - ref: "Ask me — I change jobs rarely, but I always announce it in the first conversation of the week"
    kind: note
    added_by: user
    added_at: "2026-08-30"
```

- `GET /entities/{id}/sources` → list; `POST /entities/{id}/sources` `{ref, kind?, predicate?}` (kind inferred: `http(s)://` → url, leading `/` or `~` → path, else note) → append + commit `user/companion_app`; `DELETE /entities/{id}/sources/{index}`.
- `cicada_write_claim` accepts an optional `sources: [str]` argument; each becomes a `sources:` entry on the subject entity with `added_by = <model id>` (the same author string the claim carries).
- **Conflict generation consults sources:** when a conflict is written for `(entity, predicate)` and the entity has a source with a matching `predicate` (or any `url` source when the predicate is unset), the question object gets `hint: "You said <ref> is where to check this"` and the app shows it as a small "Source to check" row with an open-link button. No fetching in this slice (the "check now" action is G61 follow-up).
- The app's entity detail card gets a **Sources** section: rows + an "Add source" field (one `TextField`, Enter to add, kind inferred by the backend), delete on hover.

### 2.6 App (SwiftUI)

- `InboxItem` gains `question: String?`, `options: [InboxOption]` (`key, label, description?, claimId?, observedAt?, lastReferenced?, ageDays?`), `allowOther`, `allowDefer`, `predicate`, `hint`, `remindAfter`, `updatedDate`. Decoder keeps accepting the legacy `[String]` options.
- `InboxCardView` conflict/clarification/merge branches are replaced by one `QuestionView`: the question (falls back to `body`), then an option list in the `AskUserQuestion` style — label on the left, description in secondary text beneath, the age as a trailing muted capsule ("6 mo"), first option pre-highlighted; then, when `allowOther`, an "Other…" row that expands into a text field with a Submit button; then a footer row with "Not sure — remind me later" (when `allowDefer`) and, for decay, the existing three buttons. Keyboard: ↑/↓ moves, ⏎ picks, `o` opens Other. The `hint` renders above the options as a link row.
- `InboxViewModel.resolve` gains `optionKey:` and `remindDays:`; `InboxResolve` mutation carries them; `defer` hides the card optimistically like a resolve (it disappears from the pending list either way).
- Card title line for conflicts becomes the **question**, subtitle the entity name; the "Conflict" badge stays.

### 2.7 MCP surface

`cicada_check_nudges` and the proactive block in `cicada_recall` render the question object: the question line, then options as `a) MongoDB — 6 months ago`, `b) …`, `Other / Later`, so an agent can ask the user in-flow and call `POST /inbox/{id}/resolve` with `option_key` or `answer` through the existing `_backend_headers` client. A new `cicada_resolve_inbox(id, option_key?, answer?, defer?)` tool wraps that call.

## 3. Out of scope

- Fetching/verifying sources ("check now") — G61 follow-up.
- LLM-written questions for the claim path (template only in this slice; entity path keeps its LLM prompt).
- Rewriting the decay kind (its three buttons stay).

## 4. Testing

- Pytest: `find_open` + merge-on-collision; `dedup_open_items` migration on a fixture with two duplicate conflicts; `humanize_age`; question-object generation from `_conflict_nudge` (template) with age phrases; `refresh_open_questions` cases (bump/re-order, organic resolution via user_stated claim, organic via superseded claim, stale escalation inserting `neither`, deferred hidden); `_resolve_conflict` for each row of the table asserting claim `valid_to`/`superseded_by`/new user claim and the entity page rewrite; sources CRUD + kind inference + `hint` on generated conflicts; legacy flat-options read path; `cicada_resolve_inbox`.
- Swift (`CicadaAppTests`): decoding legacy and new option shapes; `InboxViewModel.resolve` passes `optionKey`/`remindDays` through the mutation (using the existing fake transport pattern); `QuestionView` keyboard selection model (pure logic extracted into `QuestionSelection`).
- Live check on the `claude-chats` bank: after migration the two Rodrigo conflicts collapse to one; the card shows ages; picking "Neither anymore" + typing the current employer closes both claims and writes a `user_stated` claim (verified in the entity's claims block and `git log`).
