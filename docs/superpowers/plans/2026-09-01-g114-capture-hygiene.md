# G114 Capture-Writer Hygiene — Implementation Plan

> **For agentic workers:** executed by a Workflow of sequential implementer → reviewer
> dispatches in the `.worktrees/g114` worktree (branch `feat/capture-hygiene`). Tasks are
> ordered so that shared helpers land before their consumers; each task ends green and
> committed.

**Goal:** one episode-id rule, one timestamp shape, the Telegram message date honoured (and
`/remind` no longer a silent lie), the subscribed feeds + calendars actually polled by the
nightly Sleep tail, and a `processed_by` stamp so an agent-marked episode is distinguishable
from a Sleep-consolidated one.

**Architecture:** a new tiny module `api/services/episode_ids.py` owns the two rules every
capture writer duplicated (id minting, UTC timestamp) and every writer — importer, MCP,
media, Telegram, calendar, notes — calls it. The Sleep tail grows one more non-fatal slot
(feeds + calendars) beside the connector poll, under the SAME clean-tree guard, because both
`poll_*` functions commit with `git add -A`. Nothing here needs an LLM; everything is $0.

**Spec:** `docs/goals/memory-evolution.md` row **G114** (line ~676) — read it once; it lists
the five defects with their file:line evidence. The rulings below settle the open questions
the row leaves.

## Rulings (binding for every task)

- **R1 — id rule is max-suffix+1 per date.** `next_episode_id(episodes_dir, "YYYY-MM-DD")`
  returns `ep_<date>_<NNN>` where `NNN = 1 + max(existing suffixes for that date)` (zero-padded
  to 3, but a 4-digit suffix parses fine). A count-based rule (the importer's) collides after
  any deletion or any gap; max+1 never does. The importer keeps its per-batch `date_counts`
  dict for O(1) writes but SEEDS it from `max_suffix_by_date()` instead of counting files.
- **R2 — timestamp shape is aware-UTC ISO-8601 with `+00:00`** — exactly what
  `datetime.now(timezone.utc).isoformat()` yields, and exactly what the two newest writers
  (MCP `mcp/server.py:1707`, Telegram `telegram_capture.py:408`) already emit. Every naive
  `datetime.now().isoformat() + "Z"` (a LOCAL time falsely labelled UTC — off by the machine's
  offset) and every `fromtimestamp(epoch).isoformat() + "Z"` becomes a call into the helper.
  **No migration** of existing episode files: readers (`sleep_debt._parse_episode_timestamp`,
  Python 3.11 `fromisoformat`) already accept both shapes; the Sleep queue sort gains a
  normalising key so legacy naive-local files still order correctly against new UTC ones.
- **R3 — Telegram: the message's own `date` is the episode timestamp** (and the id's date
  part) — a webhook retry or a late delivery must not restamp yesterday's message as today.
  For a URL save, the message date also becomes `RawItem.added` (the platform-saved date) so
  the media entity's saved date is the day it was sent, not the day it was imported.
- **R4 — `/remind` is honest, not scheduled.** It stays in `_COMMAND_RE`, the text is saved as
  a note episode carrying `capture_kind: reminder` in frontmatter, and the ACK says plainly
  that reminders aren't scheduled yet ("Saved as a note — reminders aren't scheduled yet.").
  A real reminder (an inbox item with `remind_after`) is a feature, not hygiene — it gets its
  own backlog row, not a half-build here.
- **R5 — feeds + calendars poll in the Sleep tail under the EXISTING opt-in gate**
  `CICADA_ALLOW_FEED_FETCH=1` (unchanged semantics: opt-IN, unlike the connectors' opt-OUT
  `CICADA_ALLOW_CONNECTOR_FETCH`). They run in the same guarded branch as
  `_poll_connectors_safely` — never on a tree with uncommitted Sleep writes — because
  `_commit_poll` uses `git add -A`. `install.sh`'s LaunchAgent plist gains
  `CICADA_ALLOW_FEED_FETCH=1`: an installed backend whose subscriptions never refresh is
  broken by construction. The test suite is unaffected (it never sets the var, so the gate
  stays closed there). With zero subscriptions the slot logs nothing.
- **R6 — `processed_by` is a string: `"sleep"` or `"agent"`** (an agent mark via MCP may pass a
  more specific id, e.g. the harness name, but the default is `"agent"`). It is written only
  alongside `processed: true`; never removed; surfaced on `GET /sleep/episodes` as an optional
  field so an older app build keeps decoding.

## Global Constraints

- Python backend only; no Swift changes. Run tests from the worktree root:
  `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`. Baseline on `dev`:
  8 pre-existing date-dependent failures in `test_calendar_registry.py` — those are NOT yours;
  everything else must stay green.
- Never `git add -A`; stage named files. Never commit `memory/`, `logs/`, `.claude/settings.json`,
  `api/.venv`. Commit per task, conventional prefix (`feat(capture): …`, `fix(sleep): …`,
  `docs: …`). Do not push.
- No new dependencies. No transcript content, no bank content, no personal names in tests or
  docs — fixtures use placeholder text.
- Match surrounding style (docstrings that explain WHY, `logger.warning` for non-fatal slots).

---

### Task 1: `episode_ids.py` — one id rule, one clock

**Files:**
- Create: `api/services/episode_ids.py`
- Create: `api/tests/test_episode_ids.py`
- Modify: `api/services/media_ingestor.py:1322-1333` (`_next_episode_id` → thin alias of the
  new helper, kept because `calendar_registry.py` and `notes_sync.py:38` import it by that name —
  point both imports at the new module and delete the alias if nothing else references it),
  `api/services/telegram_capture.py:398-404`, `mcp/server.py:1690-1696`,
  `api/routers/conversations.py:743-746` + `_write_new_episode` (~:815-823).

**Produces (later tasks rely on these exact names):**
```python
# api/services/episode_ids.py
EPISODE_ID_RE: re.Pattern            # ^ep_(\d{4}-\d{2}-\d{2})_(\d+)$
def parse_episode_id(stem: str) -> tuple[str, int] | None
def max_suffix_by_date(episodes_dir: Path) -> dict[str, int]   # one glob("ep_*.md"), tolerant of junk
def next_episode_id(episodes_dir: Path, ep_date: str) -> str   # R1
def utc_now_iso() -> str                                        # R2: datetime.now(timezone.utc).isoformat()
def to_utc_iso(value: datetime | int | float) -> str            # epoch → aware UTC; naive datetime → assume UTC; aware → astimezone(utc)
def timestamp_sort_key(raw: str | None) -> str                  # normalised UTC ISO for ordering; "" if unparseable; naive input = LOCAL time (matches sleep_debt)
```

**Tests (write first, watch them fail, then implement):**
- `next_episode_id` with `ep_2026-09-01_001.md` and `ep_2026-09-01_005.md` present → `ep_2026-09-01_006`
  (NOT `_003`); empty dir → `_001`; a junk file `ep_2026-09-01_x.md` is ignored; a 4-digit suffix
  `_1000` → `_1001`; other dates don't interfere.
- `max_suffix_by_date` returns `{"2026-09-01": 5, "2026-08-31": 2}` for a mixed dir.
- `utc_now_iso()` ends with `+00:00`; `to_utc_iso(0)` == `"1970-01-01T00:00:00+00:00"`;
  `to_utc_iso(datetime(2026,1,1,12,0))` (naive) treats it as UTC; an aware `+02:00` value converts.
- `timestamp_sort_key`: `"2026-09-01T08:00:00Z"` and `"2026-09-01T08:00:00+00:00"` produce the
  same key; a naive `"2026-09-01T10:00:00"` on a UTC+2 machine sorts equal to the two above
  (patch `TZ` or compute expected via the same local conversion); `None`/garbage → `""`.
- Importer regression in `api/tests/test_conversations.py` (extend the existing import tests):
  pre-create `ep_<date>_003.md` in the target episodes dir, import a conversation dated `<date>`
  → new file is `_004`, and importing a second conversation on the same date in the same
  request yields `_005` (the seeded dict increments).
- Existing tests for telegram / media / notes / calendar / MCP must stay green (they exercise
  the id path; `test_mcp_tool_descriptions.py` imports `mcp.server`).

**Commit:** `feat(capture): one episode-id rule (episode_ids.next_episode_id) for every writer`

---

### Task 2: one timestamp shape (R2)

**Files:**
- Modify: `api/services/media_ingestor.py:1392` (episode `timestamp`), `:1637` (`saved_at` when it is a
  datetime-now stamp; read `:1533` — if `today` there is a `date`, normalise it to a plain
  `YYYY-MM-DD` and leave a one-line comment, do not invent a time), `api/services/notes_sync.py:231`,
  `api/services/calendar_registry.py:346` and `:407`, `api/routers/conversations.py:406,418,429`
  (epoch → `to_utc_iso`), `:521` (read where `dt` comes from — a Claude export `Z` string → aware
  UTC via `to_utc_iso`), `:828` (`utc_now_iso()`), and the `claude_memory` episodes built at
  `:300-340` with `timestamp: None` → give them the conversation's timestamp when known, else the
  export's `update_time`, else `utc_now_iso()` at write time — never `None`.
- Modify: `api/services/sleep_cycle.py:1126` and `:1186` — sort key becomes
  `(episode_ids.timestamp_sort_key(r.get("timestamp")), r["id"])`.
- Modify: `api/services/sleep_debt.py:108-120` docstring — it says "MCP capture writes naive local
  time"; that has been false since `mcp/server.py:1707`. Rewrite: every writer now emits aware UTC
  (`episode_ids.utc_now_iso`); legacy files may still be naive-local or `Z`, and this parser accepts
  all three. Keep the M1 review note.
- Tests: extend `test_notes_sync.py`, `test_calendar_registry.py` (don't touch the 8 date-baked
  failures), `test_conversations.py`, and a new `test_sleep_cycle_queue_order.py` proving a
  naive-local legacy episode and a `Z` episode and a `+00:00` episode order by true instant, not
  by string.

**Verification:** `grep -rn 'isoformat() + "Z"' api mcp` returns nothing outside tests/docs.

**Commit:** `fix(capture): every writer stamps aware-UTC timestamps; Sleep sorts by instant`

---

### Task 3: Telegram — message date honoured, `/remind` honest (R3, R4)

**Files:**
- Modify: `api/services/telegram_capture.py` — `SaveEpisodeFn` / `SaveUrlFn` protocols and
  `_default_save_episode` / `_default_save_url` gain keyword-only `captured_at: str | None = None`
  (aware-UTC ISO from the parsed `date` at `:129-135`); `_default_save_episode` uses it for
  `timestamp` and derives the id date from it (`captured_at[:10]`), falling back to
  `utc_now_iso()`; the URL path sets `RawItem.added` from `captured_at[:10]` (check
  `saved_at.validate` accepts `YYYY-MM-DD` — it is the normalised shape). Add the `/remind`
  branch per R4: `capture_kind: reminder` in frontmatter, ACK text
  `"Saved as a note — reminders aren't scheduled yet."` (keep whatever ACK prefix/shape the note
  path uses). Read `handle_update` (~:170-260) first: today `/remind` matches the regex and falls
  into the note path silently.
- Tests: `api/tests/test_telegram_capture.py` — a message with `date: 1756684800` (an epoch)
  produces an episode whose `timestamp` is that instant in `+00:00` form and whose id carries that
  UTC date; a missing/invalid `date` falls back to now; `/remind call the dentist` → episode body
  contains `call the dentist`, frontmatter `capture_kind: reminder`, ACK contains
  `reminders aren't scheduled yet`; a `/save <url> reason` passes `captured_at` to the URL fn
  (assert on the injected fake's kwargs).

**Commit:** `feat(telegram): stamp episodes with the message date; /remind saves an honest note`

---

### Task 4: Sleep tail polls feeds + calendars (R5)

**Files:**
- Modify: `api/services/sleep_cycle.py` — add `_poll_feeds_and_calendars_safely(memory_path)`
  right after `_poll_connectors_safely` (~:277): for each of `feed_registry.poll_feeds` and
  `calendar_registry.poll_calendars`, skip silently when there are no subscriptions
  (`feed_registry.list_feeds` / `calendar_registry.list_calendars` empty), otherwise call it
  inside its own `try/except Exception` → `logger.warning(...)`, and log one info line per
  registry: `Feed poll: <new> new item(s) from <polled> feed(s)` or
  `Feed poll skipped: CICADA_ALLOW_FEED_FETCH is not "1"` when the result carries
  `skipped_no_network`. Call it from `_run_engine_independent_tail` in the SAME guarded branch as
  `_poll_connectors_safely` (after it), never in the `else`. Update both docstrings (the tail's and
  the new slot's) with the why: both `poll_*` commit via `git add -A`.
- Modify: `install.sh:305-309` — add `<key>CICADA_ALLOW_FEED_FETCH</key><string>1</string>` to the
  plist's `EnvironmentVariables` dict, with a one-line comment above the heredoc block explaining it
  is the opt-in for the nightly feed/calendar refresh (user-initiated `POST /sources/poll-feeds`
  is also gated by it — say so).
- Tests: `api/tests/test_sleep_connector_poll.py` is the model — add `test_sleep_feed_poll.py`
  with monkeypatched `feed_registry.poll_feeds` / `calendar_registry.poll_calendars` async fakes:
  (a) idle cycle with one subscribed feed → both fakes called; (b) zero subscriptions → neither
  called; (c) a fake that raises → cycle still completes, warning logged; (d) write-started +
  never-committed + dirty tree → NOT called (mirror the connector test); (e) a fake returning
  `{"skipped_no_network": True, ...}` → the skip line is logged.

**Commit:** `feat(sleep): nightly tail polls subscribed feeds and calendars (opt-in gate; installer sets it)`

---

### Task 5: `processed_by` stamp (R6)

**Files:**
- Modify: `api/services/agentic_write.py:464-491` — `mark_episodes_processed(memory_path, ids, *, by: str = "agent")`
  writes `fm["processed_by"] = by` beside `fm["processed"] = True`.
- Modify: `api/services/sleep_cycle.py:1209-1219` `_mark_episodes_processed` → `processed_by: "sleep"`.
- Modify: `mcp/server.py` — the `cicada_mark_processed` tool passes `by=` (the harness name when
  the process knows it — see how `harness` is minted for G48 — else `"agent"`) and its description
  (`:333`) mentions the stamp in one clause.
- Modify: `api/models/schemas.py` `EpisodeQueueItem` (~:1034) gains `processed_by: str | None = None`;
  `api/routers/sleep.py:154` passes `ep.get("processed_by")`.
- Tests: `test_agentic_write.py` (default `"agent"`, explicit `by="claude-code"`), a Sleep test
  asserting `"sleep"` after a cycle marks episodes (extend an existing sleep-cycle test that
  already inspects `processed`), `test_mcp_tool_descriptions.py` if it pins the description text,
  and the `/sleep/episodes` route test if one exists (else add a minimal one).

**Commit:** `feat(episodes): processed_by stamp — sleep vs agent — surfaced on /sleep/episodes`

---

### Task 6: docs

**Files:**
- Modify: `CLAUDE.md` Awake section ("Episode tracking" paragraph): id rule = `episode_ids.next_episode_id`
  (max-suffix+1 per date), timestamp = aware UTC from `episode_ids.utc_now_iso`, `processed_by`
  (`sleep` | `agent`), and one sentence on the Sleep-tail feed/calendar poll under the opt-in
  `CICADA_ALLOW_FEED_FETCH=1` (installer sets it) — keep the existing density; no new section.
- Modify: `docs/goals/memory-evolution.md` G114 row → `| ✅ |` with a `**Shipped 2026-09-01 (PR
  #<n>, feat/capture-hygiene):**` clause naming the module, the rulings R3–R6 in one line each, and
  the disclosed non-fix: no migration of legacy timestamps (readers tolerate all shapes).
- Modify: `docs/goals/TODO.md` — move the G114 entry to Shipped (under the 2026-08-31 → 09-01
  heading), drop it from "Pick up here" and Wave A, update `_Last synced:_`.

**Commit:** `docs: G114 shipped — capture-writer hygiene`
