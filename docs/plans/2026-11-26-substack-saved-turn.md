# Substack Saved takes its turn (G89, 2026-11-26)

**Problem.** Rodrigo wants his Substack *saved* posts read, not his subscriptions. The Saved list, its record tool
(`cicada_record_substack_list`, each post a `substack-saved` save read by Sleep, ruling 80) and its grouping
(`list_pages`: "Substack: Saved") all exist, but Saved was last read on 2026-11-04. `substack_lists.due` offered a
Substack list only when `saved_lists.due` returned nothing; with six sites on a 20-hour cadence one is nearly always
due (measured on the live state: LinkedIn due, Substack nothing).

**Global constraints.** G206's bounds stay: one site's list at a time, 10 reads a UTC day per bank, a pause per site.
The ToS rail and G166: only the person's own agent in their signed-in browser; nothing fetched by the backend.
Subscriptions stay off by default (they already are; his is off since 11-06); a feed item is never a save (#938).

**Rulings.**
1. One order across both tables: each table's `candidate()` returns `(asked first, unattended rank, when, table, order,
   key)`; each `due()` yields when the other table's candidate ranks first. In a tie the saved lists go first.
   Reason: G245 already chose "asked first, then read longest ago" within a table; this extends it, not a new rule.
2. Saved opens `https://substack.com/inbox/saved`, History `https://substack.com/inbox/history` — each tab has its
   own address (seen 2026-11-26 in his reader); the old "open History (the clock icon)" no longer matches the page.
3. Subscriptions unchanged (off by default). Whether to drop the switch is the owner's.

**Files.** `api/services/saved_lists.py` (`due`, new `candidate`), `api/services/substack_lists.py` (`due`, new
`candidate`, URLs, docstring), `api/services/mcp_tools.py` (docstring), `api/tests/test_substack.py` (the offer test,
a starvation test), `docs/architecture/mcp.md`, `docs/goals/memory-evolution.md` (G89), `docs/goals/feature-status.md`.

**Verify.** `pytest` on every test file importing `saved_lists` (24 files); `make test-crucial`; on the live state,
read-only, `substack_lists.due` returns `["saved"]`; a real read of the first ~5 saved posts through his browser.
