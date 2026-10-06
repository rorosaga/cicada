# Audit 2026-10-02 — status (2026-10-05)

Revalidated on `dev` `efd5386e` (the revalidation table is in the README). Every fix is a PR to `dev`, unmerged.

| ID | Revalidation | Outcome | PR |
|---|---|---|---|
| A01 | confirmed | fixed: revision-checked retirement under `episode_lock` | #168 |
| A02 | confirmed | fixed: temp file + fsync + `os.replace` | #168 |
| K01 | confirmed | fixed: no-clobber `create_episode`, lock for dedup | #168 |
| A03 | confirmed (static) | fixed: bank and invalidation generation checked | #172 |
| A04 | confirmed | fixed: duplicate skips symlinks | #171 |
| A05/A06 | confirmed (static) | fixed: serial write queue + `isCurrent`; the add keeps its draft | #172 |
| A07 | confirmed | fixed: `setGraphActive`; on-screen 30 fps pulse | #169 |
| A08 | confirmed (static) | fixed: weak web view, teardown | #169 |
| A09 | confirmed | fixed: `cancelInteraction` | #169 |
| A10 | confirmed (static) | fixed: shared per-bank tick, off the loop | #173 |
| A11 | confirmed (static) | fixed: cadence follows visibility, power and Reduce Motion | #173 |
| A12 | **gone** (G176) | none needed | — |

Docs and probes: #167. Disclosed gaps that remain open:
- ~~the agent's `cicada_mark_processed` carries no revision~~ — closed 2026-10-05 (`fix/agent-mark-processed-revision`);
- MCP's dedup scan holds the lock;
- `ActivateBank`'s hydrate-before-switch window.

## Tests

The environment was synthetic: a `/tmp` home, capture off, dotenv off, fetches off.
- **API, `dev`:** 5,876 passed, 1 failed (the known `test_cycle_usage` join), 1 skipped.
- **API, after each fix:**
  - #168: 5,892 passed;
  - #171: 5,881 passed;
  - #173: 5,887 passed.

  Each of those has the same single failure.
- **Swift, baseline:** 2,788 passed, 0 failures.
- **Swift, after each fix:**
  - #169: 2,794 passed, 0 failures;
  - #172: 2,798 passed, 0 failures;
  - #173: 2,791 passed, 0 failures.
- **Graph JS:** 8/8 suites before, 9/9 after (#169).
- Each new regression test failed on the old behaviour; each PR names which, and how that was checked.

## Measurements

- **A10.** Generated banks with 1,900 entities. Median process CPU per tick, before → after:
  - 10,000 episodes: 42.3 → 24.3 ms for one stream, and 169.1 → 24.6 ms for four;
  - 2,000 episodes: 11.9 → 6.2 ms for one stream, and 50.3 → 6.2 ms for four.
- **Installed app before the fixes.** Read-only `top -l 13 -s 5` over 60 s; the UI state was unknown:
  - CicadaApp: 13.6% (12.6–14.4);
  - WebContent: 17.2% (15.8–17.8), whose `sample` shows rAF-driven canvas drawing;
  - backend: 7.7% (3.6–32.8).
- **After the fixes, live:** unmeasured. Installing or launching the app was off limits.

## Next

The owner reviews and merges #167–#173. Then, with the owner's word, measure on screen per VALIDATION.md (graph
foreground, another tab, minimized, hidden), and take on G176 follow-up 1 (the Sleep page's CPU) separately.
