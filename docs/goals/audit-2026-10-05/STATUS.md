# Audit 2026-10-05 — status (2026-10-06)

The owner's code audit of `dev` at `3d28cd0c`. Every finding was reproduced with a regression test that failed on the
unfixed code, fixed, reviewed by a separate agent against CLAUDE.md's rails, and merged to `dev`.

| ID | Finding | Reproduced | Outcome | PR |
|---|---|---|---|---|
| P1-1 | Merges discard the loser's claims | yes (6 tests) | fixed: both claim sets kept with provenance and supersession; references repointed before the delete; the inbox's merge branches use the primitive | #180 |
| P1-2 | Concurrent claim writes lose updates | yes (thread and retract races) | fixed: `page_lock`, a cross-process `flock` held across the page write and its commit; lock order page → git → episode | #181 |
| P1-3 | Inbox resolutions commit unrelated changes as the user | yes (4 tests) | fixed: commits only the answer's files; an edit already there is committed apart with no author | #189 |
| P2-4 | A partial model switch corrupts rankings | yes | fixed: each table is queried with its own recorded model; multi-kind search embeds once per model | #190 |
| P2-5 | Dropped entities surface through semantic recall | yes | fixed: hits are read against the current page; recall filters every leg before fusion, hints and render | #190 |
| P2-6 | Older app responses overwrite newer ones (`ProjectsCache`) | yes (parked requests) | fixed: request generations per resource, `BacklogCache` too; a confirmed paint is cleared only by an answer requested after it | #191 |
| P2-7 | Failed app refreshes stay stale on a healthy SSE stream | yes (static trace confirmed by a test) | fixed: the 15 s `ping` retries pending domains, at most 8 times until the next version event | #191 |
| P2-8 | MCP recall embeds the query twice | yes | fixed: one query embedding per model, shared for 60 s (keyed by model, table width and a query hash) | #190 |
| P2-9 | Version stamps can miss edits | yes (8 tests) | fixed: fingerprints of names, sizes and nanosecond mtimes over the shared scan; no `VersionVector` change needed | #193 |
| — | Release versioning (app 0.2 vs API 0.1.0) | — | left to G182, where #182's `VERSION` file closed it | — |

Disclosed and still open:
- Sleep's own page writes and the inbox's resolvers other than follow-ups are not under the page lock (`docs/architecture/storage.md`).
- `POST /maintenance/dedup-sweep` leaves its merges uncommitted for the next writer (G21).
- A follow-up event write that merges into an already-open conflict item does not list that item in its manifest (predates P1-3).

## Tests (synthetic environment: a `/tmp` home, capture off, dotenv off, fetches off)

- Baseline on `3d28cd0c`: API 5,913 passed, 1 failed (`test_cycle_usage` ledger join), 1 skipped; Swift 2,813 passed.
- Final `origin/dev` `4264e297`, clean worktree:
  - API: **6,016 passed, 1 failed** (the same `test_cycle_usage.py::test_history_and_detail_join_usage_from_the_ledger`), 1 skipped;
  - Swift: **2,957 tests, 0 failures**;
  - Graph JS: **9/9 pass**.
