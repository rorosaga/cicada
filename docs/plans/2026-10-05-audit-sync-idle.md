# Audit batch 4 — idle sync cost (A10) and the walkthrough clock (A11)

Source: [`docs/goals/audit-2026-10-02/README.md`](../goals/audit-2026-10-02/README.md), revalidated on `dev` `efd5386e`
(2026-10-05). Baseline from the audit's `repros/idle-sync.py` on this machine, the same day:
- 2,000 processed episodes: **14.35 ms** wall median per tick, 14.32 ms CPU;
- 10,000 processed episodes: **52.24 ms** wall median per tick, 52.19 ms CPU.

Both use 1,900 entities. Every connected SSE client paid that once per second, on the event loop's caller for the debt
half. Branch `fix/audit-sync-idle`.

## Constraints

- Markdown stays the source of truth. No watcher daemon, no new persistent state.
- External edits (Obsidian, an editor) are still detected by the same full scan. Detection latency must not grow
  beyond the existing 1 s poll.
- SSE progress, keepalives, bank isolation and the event payloads are byte-identical.

## Rulings

- **R1 — one computation per bank per tick.** `api/services/sync_ticker.py`'s `current(memory_path, settings,
  max_age)` returns a shared `Tick(info, debt)`, computed at most once per `max_age` per bank.
  - The SSE loop passes `0.9 × POLL_SECONDS`.
  - A per-(event loop, bank) `asyncio.Lock` makes concurrent subscribers await the one computation instead of
    duplicating it. Keying by loop keeps it safe across test clients.
  - `/sync/version` and `/sleep/status` are untouched: exact, per request.
- **R2 — off the event loop.** The whole filesystem half of a tick runs in one worker thread: `version` plus the
  debt queue scan. Only the HEAD-keyed `git log` read stays on the loop, as an awaited subprocess.
  `sleep_debt.compute` itself also moves its scan to a thread, so `/sleep/status` stops blocking the loop too.
- **R3 — one scan per directory per tick.** `bank_index.shared_scans()` is a thread-local memo of `_scan`, active
  only inside the ticker's worker call. `version`'s `dir_stamp(episodes)` and debt's `files(episodes)` then share
  one `scandir` of the directory. Outside the context nothing changes, so every other caller stays exact.
- **R4 — cheaper stamps.** `graph_builder._dir_mtime` moves from `Path.glob` + `Path.stat` per file to one
  `os.scandir` with `DirEntry.stat()`. The semantics are the same: the max mtime over non-hidden `*.md` files and
  the directory itself.

## A11

`ExportWalkthroughSheet` asked `SceneRunPolicy.frameInterval(lowPower: false)` regardless of power and had no
visibility reader.
- It now reads `SceneStore.shared.lowPower` (the policy the painted scenes and sprites use) and a
  `WindowVisibilityReader`, so the `TimelineView` is paused while the window is hidden.
- Under Reduce Motion the frame only changes at step boundaries, so the timeline asks for a schedule of those
  boundaries (`ExportWalkthrough.stepBoundaries`) instead of animation cadence.
- The looping tutorial stays as it is (the audit: "animation never completes" is not a finding).
- **A12 is gone** (G176). The Sleep page's 11.9 % is G176 follow-up 1's, not this PR's.

## Tests (first)

- `test_sync_idle.py` covers:
  - five concurrent subscribers on one bank, producing one `version` computation;
  - a tick older than `max_age` recomputing;
  - two banks never sharing a tick;
  - an in-place external edit changing the version on the next tick;
  - the debt scan running off the event loop thread;
  - one `scandir` of `episodes/` per tick;
  - SSE payload equality against the unshared path.
- Swift: the walkthrough's schedule under Reduce Motion lands on step boundaries only, and the walkthrough
  honours Low Power.

## Verification

- The full API suite, compared with `dev`.
- `swift test`.
- `idle-sync.py` before and after on the same generated banks, plus a fanout measurement with 4 subscribers.
