# Audit batch 3 — app consistency (A03, A05, A06)

Source: [`docs/goals/audit-2026-10-02/README.md`](../goals/audit-2026-10-02/README.md), revalidated on `dev` `efd5386e`
(2026-10-05). The files are unchanged since the audit. Branch `fix/audit-app-consistency`.

## Rulings

- **R1 (A03).** `Store` keeps an `entityGeneration` counter, bumped by `hydrate` (every bank load), by
  `invalidateAllEntities` and by `invalidateEntity(id)`. `invalidateEntity(id)` also bumps a per-id counter in
  `entityInvalidations`. `entity(_:)` captures `(bank, generation, per-id)` before awaiting the fetch and re-checks
  all three after it:
  - The bank changed: return `nil` and cache nothing. The answer belongs to another bank, and a card asking under
    the new bank asks again.
  - The cache was invalidated: fetch again, up to three attempts, so a read that started before a mutation never
    repopulates the pre-mutation body. A caller still gets the newest body.

  Nothing else about the memo changes.
- **R2 (A05).** `SourceWriteQueue` is a `@MainActor` serial chain owned by the Look-it-up section (card-local
  `@State`, so one per open page). Every source write (`EntitySourceWrite`) and every add (A06) runs through it in
  submission order. Each mutation's optimistic step therefore snapshots the list as the previous write left it, so
  its rollback restores only its own change, and a slow first response can no longer overwrite a newer one. A
  card for another entity, or a closed card, has its own queue; a late write lands in its own dead binding,
  never in a newer card.
- **R3 (A06).** An add becomes the `EntitySourceAdd` mutation through `Store.perform`, so a failure toasts the
  server's sentence (`SourceWriteFailure.message`, the same as an edit) and nothing is painted that would need
  rolling back. `SyncAPI` gains `addEntitySource`; `APIClient` already implements it. The field keeps the draft
  while the request is in flight. `SourceDraft.afterAdd(submitted:current:landed:)` decides what the field holds
  after the answer:
  - it landed and the person didn't change the text: empty;
  - it landed and they typed something new: their new text;
  - it failed: what they have now, or the submitted text if they cleared the field.

  A second ⏎ on the same pending text is ignored.

## Tests (first)

- **Store (A03), with a gated fake `fetchEntity`:**
  - a read started under bank A and answered after a switch to B returns nil and caches nothing;
  - a read started before `invalidateEntity` refetches and caches the new body;
  - `invalidateAllEntities` behaves the same.
- **Source queue (A05):**
  - B's request is not issued while A is parked;
  - A fails after being released, then B succeeds: the final list is B's server answer, with A's optimistic paint
    rolled back;
  - two successes in a row: the final list is the second answer.
- **Add (A06):**
  - a 409 returns false and toasts the server's sentence, leaving the list unchanged;
  - success replaces the list;
  - the `afterAdd` table covers all four cases.

## Verification

`cd app/CicadaApp && swift test` (baseline 2,788/0 on `dev`). No UI change beyond a toast already used by edits.
Per DR-59 (copy), no new copy is introduced.
