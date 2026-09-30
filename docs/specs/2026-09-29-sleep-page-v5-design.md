# Sleep page v5: a progress you can trust, and reading faster on purpose

Status: **partly built (2026-09-30, backend half on branch `feat/sleep-v5`) — see section 11 for what was decided and what is built.**
The design below is otherwise as written. Nothing here is committed. Code read on `dev` at `2155940` (2026-09-29).
Revision 2 (same day) answers a verified critique round; where a finding was adopted the text says so
in place, and section 9's R-14 to R-16 record what it changed. Nothing in the critique round was
shown to be wrong, so nothing was skipped.
Paths are relative to the repo root unless they start with `Views/`, `ViewModels/` or `Theme/`
(those are under `app/CicadaApp/Sources/CicadaApp/`).

Reads with: `docs/design/DESIGN_RULES.md` (Direction D), `2026-09-23-round3-design-mascot-page.md`
(Track Z, which this extends and in places amends), `2026-09-01-agent-engine-design.md`
(the plan engines), G107 / G125 / G51 / G122 / G74 / G104 in `docs/goals/memory-evolution.md`, and
TODO rulings 1, 3, 4, 8, 10 and 12.

Filed 2026-09-29 as **G163** in `docs/goals/memory-evolution.md`; the first-run fixes it leans on are G169 to G172.
Spec rulings are `V5-n`. Experiments are `EX-n`. Build slices are `SL-n`.

---

## 0. In one page

1. **The progress bar cannot be reliable today, because nothing a cycle reads survives the cycle.**
   Stages 1 to 4 write nothing to disk; Stage 5 files everything and marks the episodes processed
   (`sleep_cycle.py:1370-1379`, `_cycle_cancelled`'s own docstring). A cancel, a plan stop, a crash or
   a backend restart throws away every paid Stage 1 answer. By reading the code (not by running it),
   a plan stop after some episodes were read also makes Stage 2's first judge call raise, which fails
   the cycle and throws the same work away (F1, EX-1 reproduces it).
2. **Fix the cause, not the bar.** A small **journal** remembers every LLM answer a cycle paid for,
   keyed by what was asked. A restarted, paused or cancelled cycle re-asks the same questions and gets
   the answers back at no cost. With that, "read" and "filed" become two real, durable states per
   conversation, and the bar can show both, honestly, across restarts and plan pauses.
3. **A drain is a first-class thing.** "Read everything" is a person-started run of many batches over a
   frozen list of what was waiting, pinned to one bank, with a visible batch size, a plan reserve
   ("leave room in my plan", its number set in the engine menu), pauses at limits, and an opt-in to continue by itself after the reset.
4. **Parallel reading is an explicit opt-in with the trade-off written next to it.** The honest state
   of the code: Stage 1 already runs three at a time on the plan engines (`agent_max_concurrency`
   defaults to 3); Stages 2 and 3, where most of the calls are, are fully sequential. Parallel is
   `workers` plus a smaller model for the bulk stages, applied where the order-dependence analysis
   (section 4.5) says it is safe. Git stays single-writer: every LLM call is read-only against the bank.
5. **What it cost** (ruling 12) folds in as a drain summary and a per-batch row, with the basis in words.
   Nothing on the room, the bar or the sentence is an estimate.
6. **The study room, the worm, the one sentence and the one primary button stay.** New surfaces are a
   sheet ("Read everything"), two more rows in the engine menu, a progress caption under the strip, and
   rows in Details. No new art.

Three amendments to earlier rulings are proposed and need the owner (section 8): ruling 4 (Q1,
continuing a *person-started* run after a plan reset), R-A8/P15 (Q3, "only Read carries a fill") and
G125 R10 (Q7, the page gains run controls next to its one one-batch trigger). Ruling 12 is **not**
amended: plan figures stay on Details and the engine menu (V5-16).

---

## 1. Context

### 1.1 The ask (the owner's own words, 2026-09-29)

> "a reliable progress bar that shows what has been read and consolidated would be good too."

> "if we are using the chatgpt plan, maybe even the codex harness or the plan directly we can have an
> option for parallel subagents with small models so consolidation can happen faster"

> "the owner page should be created automatically with a (you) parenthesis at the start of a new bank,
> with a small sentence like the main user or something. It gets populated with beliefs as consolidation
> and chats happen. Lets not assume users will have a bank to carry knowledge from."

The page itself is built on the local branch `fix/first-run-extraction-owner` (commit `1d00d1d`, not
merged). None of the three specs written today designs it, so section 4.8 states the minimum this spec
depends on and the one thing it adds: where the first drain shows that page filling.

The relayed brief adds: batch size (`CICADA_SLEEP_MAX_EPISODES_PER_CYCLE`, default 25) as a visible
choice; run until empty, pausing at plan limits and resuming at reset; fold in "What it cost" (PR #138,
ruling 12) and the engine menu; keep the study-room art and D's rules.

"Parallel subagents" is read as **N independent, single-purpose CLI workers that Cicada schedules**,
not a model that spawns subagents. Reasons: the engines are sandboxed on purpose (`claude -p
--safe-mode --tools ""`; `codex exec --disable multi_agent shell_tool plugins apps`, pinned in
`agent_engine.PINNED_FLAGS` and `codex_engine.CODEX_PINNED`); a model-orchestrated fan-out cannot be
counted, capped or paused; and Cicada's own scheduler already does the job deterministically.

### 1.2 What exists (read on `dev`)

| Piece | What it does today | Where |
|---|---|---|
| The cycle | One in-memory batch: Stages 1 to 4 compute, Stage 5 writes and commits, then `_mark_episodes_processed` | `sleep_cycle.py:1138-1655` |
| The cap | `sleep_max_episodes_per_cycle = 25`; the oldest 25 by instant; the rest stay `processed: false` | `sleep_cycle.py:1166-1182`, `config.py:196` |
| Progress | `stage` (completed stages), `stage1_progress` (ticks on success, failure and skip), `read_by_origin`; `progress_pct` exists for Stage 0 only | `sleep_cycle.py:180`, `routers/sync.py:55-100` |
| Strip | Five pips; only **Read** carries a fill (P15) | `Views/Sleep/SleepStageStrip.swift`, `SleepStages.swift` |
| Concurrency | Stage 1: 10 asyncio tasks (`MAX_CONCURRENCY`), chunks inside an episode sequential; the real gate for plan engines is one process-wide `threading.BoundedSemaphore(agent_max_concurrency=3)` | `entity_extractor.py:131,311,372`; `providers.py:158-194` |
| Stage 2 | Sequential per name; one judge call per candidate until the first "same"; disk side effects deferred to the end | `entity_resolver.py:183-330`, `846-929` |
| Stage 3 | Two LLM calls per updated page (merge, then contradiction), sequential | `conflict_resolver.py:72-148` |
| Plan stops | Claude: 5-hour window stop at 90%, weekly stops only on rejection, extra usage refused unless opted in. ChatGPT: refuses to start when the limit is already reached; no headroom guard | `plan_limits.py`, `codex_engine.preflight` |
| Breaker | Per-cycle scope; after a trip every new call fails fast, in-flight calls finish | `agent_engine.py:510-601` |
| Usage | Per-cycle `llm_call` rows tagged `cycle_id`, plan windows before and after on `sleep_run` | `cycle_usage.py`, TODO ruling 12 |
| Page | Room, one sentence, Consolidate / Cancel + engine menu, whisper line, strip only with news, Details closed by default | `Views/Sleep/*`, Track Z |

### 1.3 Measured, read from code, assumed

The spec keeps these apart on purpose. G107's ruling on estimates is binding, so no figure below is
used as a prediction anywhere in the product.

**Measured on this Mac, 2026-09-29**

- Claude plan, Stage 1 (`extraction`, `claude-sonnet-5`): 5 ledger rows from 2026-09-02. 30.4 to 35.8 s
  each, median 31.9 s; 3.8k to 4.6k input and 3.9k to 4.5k output tokens; list-price equivalent 4.7 to
  5.9 US cents per call. n = 5, an older build. Treat as an order of magnitude only.
- Claude plan, Stage 2 judge (`disambiguation`, `claude-haiku-4-5`): 32 rows, median 6.6 s.
- The telemetry ledger holds **zero `sleep_run` events**, so there is no measured whole-cycle duration
  on this machine yet. PR #138 records them from now on.
- ChatGPT plan, read-only `codex app-server` (no quota spent): seven visible models, each with the
  vendor's own one-line description (for example "Fast and affordable model for easier tasks", "Workhorse
  model for coding and everyday work", "Older fast and efficient model"); one rate-limit window of
  10,080 minutes (weekly) and no five-hour window; a priority service tier labelled "increased usage".
  Model names carry no size marker, and `docs/goals/subscription-first-portability.md:83` records that
  models leave ChatGPT-auth Codex on the vendor's schedule (5.4 and 5.4-mini went on 2026-08-31), so "the small model" is **discovered, never pinned**.
- The repo's own figure: a first-run queue of about 1,200 episodes (`sleep_cycle.py:1160`).

**Read from code, not executed (each becomes a test in SL-1)**

- F1 below (a stop mid-cycle discards Stage 1).
- Stage 2's prefetchable pairs are those against `existing` entities; pairs against entities created
  in the same cycle depend on loop order (`entity_resolver.py:881-890`).
- Decay is charged one week per cycle and the watermark advances by the charged amount only
  (`conflict_resolver.py:211-220`), so cycles run back to back charge decay back to back.
- `_LOGGED_OUT_MARKERS` includes `refresh_token_reused`, a sign that concurrent `codex exec` children
  sharing one home can race on token rotation (`codex_engine.py:102-105`).

**Assumed (nothing below is known, and EX-1 to EX-5 exist to replace each)**

- That six workers finish a batch meaningfully faster than three, and how much.
- That a smaller model's extraction is good enough, and what it misses.
- That a smaller model uses less of a plan window per call.
- That per-cycle fixed overhead (Stage 4, indexes, commit, tail) is large enough to justify bigger batches.
- That the vendors' limits tolerate N concurrent CLI children. The repo's own compliance note calls
  even a nightly personal batch "plausibly yes, not explicitly adjudicated"
  (`subscription-first-portability.md:262`). Vendor terms were not re-read for this spec.

---

## 2. Goals and non-goals

### Goals

1. A progress display whose every number is a count of something that finished, that survives a page
   change, an app quit, a backend restart, a plan pause and a bank switch, and that says which of
   **read** and **filed** each conversation is in.
2. A first-run **drain**: batch size as a visible choice, run until the frozen list is done, pauses at
   limits with the vendor's own reset time, resume by a click or (opt-in) by itself.
3. **Parallel reading** as an explicit opt-in with a smaller model, honest about what it trades, gated
   by measurements, off by default, never on a schedule.
4. The cost of a drain shown in ruling 12's grammar.
5. Keep the room, the worm, the sentence, the one primary button and D's rules.

### Non-goals

- **Time estimates.** No "about 12 minutes left", no rate-based projection. Elapsed time is shown; a
  past cycle's measured duration stays in Past nights (G107).
- **A blended percentage across stages.** Stages have different units; each gets its own or none.
- **Stage-2 batching** (one judge call per name), the big lever in `2026-09-01-agent-engine-design.md`
  section 7. It changes prompts and quality and needs its own measurement. This spec makes Stage 2
  parallel, not smaller, and does not block it.
- **Read-ahead pipelining** (reading batch k+1 while filing batch k). Safe with the journal but adds
  cancel and progress complexity for a gain nobody has measured. Listed in SL-5 as a maybe.
- **Parallel for Ollama.** Depends on the person's hardware and server settings; not offered in v1.
- **A model that browses during Sleep**, and anything that widens what the sandboxed engines may touch
  (sections 4.7 and 5).
- **The video watch queue's content and the browsing-modes decision.** Owned by their own specs; this
  page only hosts them (section 4.7).
- **Re-reading with a stronger model later** (G104's reconsolidation). The design keeps it possible,
  because SL-1 makes every belief record the model that wrote it (4.3), but does not build it.

---

## 3. Findings that shape the design

**F1. A cycle is all-or-nothing, so paid work is lost.** `_run_stages` computes Stages 1 to 4 in memory;
`write_started` flips only at Stage 5; the episodes are marked processed after the writes. A cancel
before Stage 5 "costs the user only the time already spent on the in-memory Stage 1-4 work discarded
here" (`_cycle_cancelled`). A restart loses the same. Worse, when the plan stops mid-Stage-1 with some
episodes done, Stage 1 swallows the throttle per episode, the "all failed" check passes, and Stage 2's
first judge call hits the tripped breaker, which raises `EngineThrottled` (`entity_resolver.py:835`
re-raises `EngineError`), which ends in `run()`'s `except` as "Failed". On a real bank almost every
cycle has at least one name that shares a token with an existing page, so it reaches a judge call.
Conclusion: on a plan, a stop at 90% of a window can cost the whole batch.

**F2. Parallelism exists and is hidden.** Stage 1 is already concurrent up to `agent_max_concurrency`
(3). What is sequential is Stage 2 (judge calls) and Stage 3 (two calls per updated page). Using
the repo's older measurement (200 to 350 calls per 20 episodes, mean 7.0 candidates per name) and this
Mac's 6.6 s median judge call, Stage 2 alone is 22 to 38 minutes for 20 episodes when nothing else
runs. That is arithmetic on two measurements, not a measurement of a cycle.

**F3. Stages 2 and 3 do have honest units.** P15 refused fake fractions because "stages 2-5 have no
per-episode unit". True for episodes. But Sort visits a known number of names and Decide a known number
of pages, and both loops already count (`tqdm`). Those are real counts with their own nouns. The
comment at `sleep_cycle.py:1342` ("Stage 3 is pure in-memory arithmetic (no LLM call)") is wrong: Stage
3 makes two LLM calls per updated page. Fix the comment in SL-1.

**F4. A drain multiplies things that assumed one cycle a day.** Decay charges up to one week per cycle
(ruling 1's cap), so 48 back-to-back cycles can charge 48 weeks in an afternoon on any page they did not
touch. The in-flight decay inbox cap (`DecayBudget`, branch `fix/sleep-inbox-and-indexes`) is per cycle,
so 48 cycles open up to 480 questions. The engine-independent tail (link backfill up to 20 fetches and
20 summaries, connector, feed and calendar polls, papers) runs after every cycle and would run 48 times.
Stage 5.57 (link page reads, in-cycle) repeats per batch too, and it is not covered by a tail skip. A
drain must own all of these (4.4 lists each).

**F5. A bank switch mid-drain is a data-integrity hazard.** The memory notes list bank split-brain as a
recurring bug class. A loop that starts batch k+1 after the person switched banks would consolidate the
wrong bank. The drain pins the bank it started on.

**F6. The queue is a moving target.** The Stop hook rewrites a resumed conversation in place and flips
`processed: false`; capture never stops. "Until the queue is empty" can therefore be forever. The drain
works over a **frozen list of ids**; arrivals are counted, shown and left for the next run.

**F7. The engine facts.** Claude: two windows matter, and today only one is guarded. The 5-hour window
stops at 90% (`plan_limits.claude_stop`); the weekly window stops **only on rejection**, on purpose,
because stopping at 90% of a week "would idle Sleep for days" for a nightly cycle. ChatGPT: today one
weekly window, no headroom guard, and the plan's limit is also the person's coding budget. A drain that
runs "until the limit", and that auto-continues after each 5-hour reset, would run until the weekly limit
rejects: the whole coding budget. So a drain needs its own, **run-level** reserve on every window the
plan reports, separate from `claude_stop` (which stays as it is for a single cycle). Where a stream does
not report the weekly figure, the reserve cannot be enforced for that window, and the sheet says so
(4.4). No reserve is a guarantee: on both plans the figure is read after a call returns, with up to
`workers` calls in flight.

---

## 4. The design

### 4.1 Vocabulary

**Episode state** (per conversation, in a run):

```
waiting -> reading -> read -> filed
              |                 ^
              v                 |
           failed --(retry)-----+       parked = failed twice for a reason about the conversation
```

- `read`: every chunk of the episode has an **accepted** answer in the journal (4.3: the episode-to-keys
  index, so this is derivable and testable). Durable, not yet in the graph.
- `filed`: the batch's commit landed and the episode is `processed: true`. Durable, in the graph.
- `failed`: this attempt did not read. Classified by exception class (4.4, V5-6): **pause-class** trouble
  (signed out, throttled, exhausted, overage) stops the run and never counts against the conversation;
  **content-class** trouble (a timeout, a protocol error, an empty envelope, an unparseable answer, a
  schema refusal) counts, and two of them park the conversation.
- `parked`: two content-class failures in one drain. Skipped by the drain, listed in Details with the
  reason, retryable.

**Run kinds.** `cycle` (today: one batch, no body on the POST) and `drain` (many batches over a frozen
list). Both use the same journal, the same progress model and the same pause semantics. Reading pages
and watching videos are **separate jobs with their own runs, bars and nouns**, defined by their own
specs; this page hosts a row for each and never merges their bar into the consolidation bar (section
4.7).

**Stage units** (V5-3): Read counts conversations; Sort counts names checked; Decide counts pages
updated; Notice has no unit (one call); File has no unit (fast, and cannot be stopped). A stage whose
total is not known when it starts shows a breathing bar and no number.

### 4.2 The honest progress model

Seven rules. Each has a test (section 7).

1. **A number is a count of finished work from the object that did it.** Never extrapolated, never
   derived from time, never rounded up to look further along.
2. **Two durable milestones per conversation: read and filed.** The bar draws both.
3. **A number never goes backwards inside a run.** The drain-level counters (filed, read, failed, calls)
   are owned by the controller and only grow. A stage's `done/total` belongs to one batch and starts over
   at the next batch, which is itself an explicit, shown event (`batch.index` moves). A new run is another.
4. **A total is fixed when its unit starts.** Read: the batch. Sort: the names after dedup. Decide: the
   pages to synthesise. The drain: the frozen list. Arrivals are a separate "N new since you started".
5. **Failures are their own count, never folded into done.** Today `stage1_progress` ticks on failure
   (`sleep_cycle.py:1262`); the wire gets `done` and `failed` apart.
6. **Every figure has its noun and its basis in words** (G125 R-A5, ruling 12). No bare percentage.
7. **Server truth.** The page reads the backend; a page change, a quit or a relaunch shows the same
   numbers because they come from the same place (`/sleep/status` and the SSE `sleep` event).

**Wire (additions only; every new key optional so older clients decode).** `GET /sleep/status`:

```jsonc
"run": {
  "id": "run_2026-09-29_101500", "kind": "drain", "bank": "default",
  "phase": "running",            // idle | running | pausing | paused | waiting_reset
  "scope": { "batchSize": 25, "frozen": 1187, "arrivedSince": 9 },
  "workers": 6, "smallModel": "claude-haiku-4-5",           // null when parallel is off
  "calls": 412,                  // LLM calls paid for so far in this drain (journal hits are not calls)
  "episodes": { "filed": 62, "read": 14, "reading": 6, "waiting": 1105, "parked": 0, "failed": 1 },
  "batch": { "index": 3, "of": 48, "episodes": { "total": 25, "read": 14, "filed": 0, "failed": 1 } },
  "stages": [
    { "id": "read",   "unit": "conversations", "done": 14, "total": 25,   "failed": 1, "state": "active"  },
    { "id": "sort",   "unit": "names",         "done": 0,  "total": null, "failed": 0, "state": "pending" },
    { "id": "decide", "unit": "pages",         "done": 0,  "total": null, "failed": 0, "state": "pending" },
    { "id": "notice", "unit": null,            "done": 0,  "total": null, "failed": 0, "state": "pending" },
    { "id": "file",   "unit": null,            "done": 0,  "total": null, "failed": 0, "state": "pending" }
  ],
  "pause": null,                 // or { reason, sentence, resumesAt, autoContinue }
  "startedAt": "…", "elapsedMs": 372000
},
"resumable": null                // or { runId, read, of, savedAt } found by the journal at startup
```

`pause.reason` is one of `user | plan_window | plan_weekly | reserve | overage | signed_out | restart |
bank_switched | no_progress | error`. `sentence` is the vendor's own words plus the reset (`plan_limits.reset_phrase`),
never a guess. `resumable` is computed at startup from `run.json` **and** the journal's episode index
(4.3), so `read` and `of` are counts of episodes whose chunks are all accepted, not of hash keys.
`GET /sleep/episodes` gains `state` and `attempts` per row, from the same index. The SSE `sleep` event carries
a compact `run` block, and its change key includes the per-stage `done` counters (the same reason
`stage1_progress` is in it today, `routers/sync.py:78-84`); at `POLL_SECONDS = 1` that is at most one
event a second.

**One status across a drain.** While a drain is *running* (including the gaps between batches and the
`pausing` phase), `status` stays `"running"`. The app's edge detection (`SleepView.onChange(of: status)`,
`SleepViewModel`'s poll) treats running to idle as "a cycle finished", so a per-batch idle would cheer,
reload history and reset the room 48 times. The completion cheer fires once, at the end of the drain.

Calling `sleep_cycle.run` once per batch does **not** give that for free, so the mechanism is specified
(V5-14). `run()` sets `_state.status = "idle"` in its `finally` (`sleep_cycle.py:1135`) and resets about
25 per-cycle fields at its top (1058-1082), and more than fourteen sites gate on `status == "running"`:
the scheduler (`sleep_scheduler.py:173,188`), `POST /sleep/trigger`, and the 409 guards in memory,
maintenance, backlog, banks, local sources, projects, entities, paper metadata and the remote runtime.
Between two batches every one of them would open.

- A drain owns a **hold**: `sleep_run` calls `sleep_cycle.reserve_cycle` once for the drain (the existing
  reservation seam, `sleep_cycle.py:222`) and records `drain_id` on module state. `run(..., drain_id=)`
  does not flip `status` to idle in its `finally` while that hold is live, and does not clear the
  drain-level fields.
- One helper, `sleep_cycle.is_active()` (`status == "running"` **or** a live hold), replaces the direct
  `status == "running"` reads at every gate above, including the scheduler's two sites and
  `POST /sleep/trigger`. Nothing else changes at those sites, so their 409 and skip behaviour is
  unchanged for a plain cycle.
- The hold is released, and `status` goes idle, whenever the drain **pauses** (any `pause.reason`),
  finishes or is ended. A drain paused for hours or days therefore never blocks the app's writers, and
  the app tells a paused drain from a finished cycle by the `run` block (`phase: paused`), not by the
  status edge; the cheer fires only on a drain's completion event.
- Stage counters are per batch (reset by `run()` as today); the drain-level counters the wire shows
  live on the controller, never in `_state` (rule 3).
- A scheduled cycle that fires while a drain is paused is allowed (it never spends a plan, ruling 4); it
  does not join the drain, and the controller skips any frozen id that a later cycle has already filed.

### 4.3 The journal: what makes it reliable

**What.** A memo of paid LLM answers, looked up at the one seam every engine already passes through
(`providers.resolve_llm_fn`, `_agent_call` and `_call`) and **written only after the caller has accepted
the answer**. Key: `sha256(engine | model | effort | stage | schema flag | messages)`. Value: the response
the shim needs, plus `model`, `stage`, `created_at` and a `state` of `pending` or `accepted`.

*Only a Sleep scope memoises.* The seam is shared by Ask, link enrichment and the dedup sweep as well as
Sleep (`providers.py:158-194`). The lookup and the write are gated on
`agent_engine.cycle_id_from_scope(current_scope())` being non-None (a `sleep:<id>` scope), so an identical
Ask or link prompt is never answered from a Sleep journal.

*Accept, then replay.* The seam cannot know whether an answer is good: `_extract_chunk` parses after the
seam returns and, on a `ValueError` or an empty or malformed answer, retries once with byte-identical
messages (`entity_extractor.py:222-270`); Stage 2 turns an unparseable reply into `unsure`
(`entity_resolver.py:812-832`). If the seam replayed whatever it stored, the retry would hit the stored
bad answer, every Continue would replay it, and it would stay bad until the purge. So:

1. The seam stores the response as `pending` and returns it.
2. The **caller accepts** it: Stage 1 after the parse succeeds and yields a result, the Stage 2 judge
   after a valid decision (an unparseable reply is *not* accepted), Stage 3 after a non-empty synthesis
   or a well-formed contradiction verdict, Stage 4 after its parse. Acceptance is one call,
   `journal.accept(key)`, made by the stage that owns the validation.
3. A lookup replays only `accepted` rows. A `pending` row is a miss: the runner is invoked again, and its
   new answer replaces the pending one. A pending row never survives a batch commit or a restart (it is
   treated as absent).

**The episode index.** A key is a hash and cannot answer "which conversation is this?". One episode is
also N chunk calls (`entity_extractor.py:349-352`). Stage 1 therefore writes, for each episode it starts,
one row `episode_keys(episode_id, chunk_index, chunks_total, key)` (same database), and an episode is
`read` exactly when all `chunks_total` keys are `accepted`. That index is what `run.episodes`,
`GET /sleep/episodes` `state`/`attempts`, `resumable: {read, of}` and the "Saved reading" row are derived
from. A rewritten conversation has a new chunk hash, so its old index rows simply stop matching and it
reads as `waiting` again, correctly.

Why at the seam and not per stage: every stage becomes resumable with no stage-specific *lookup*. Stage 1
chunks, Stage 2 judgements, Stage 3 merges and contradiction checks and Stage 4's skill call all replay.
A prompt that changed (the person edited a page, the episode grew, the model changed) hashes differently
and is simply asked again, which is the correct behaviour without any invalidation logic. What each stage
does own is the one-line `accept`.

**Where.** `$CICADA_HOME/sleep/<bank>/journal.db` (SQLite, WAL) and `run.json`. Machine-local, 0700
directory, 0600 files, next to `repos/<bank>.json`, `pictures/<bank>` and the logos. Never in a bank,
never in git, so it never travels with an exported or handed-over bank.

**What it holds.** Extracted entity names and descriptions are personal. So: it is never logged, never
in telemetry (the ledger keeps counts and enums), purged when a batch commits, hard-purged after 7 days
and at 50 MB, and there is a "Forget saved reading" row in Details (section 4.6, G). The episode text
itself is not stored; the key is a hash.

**What it changes.**

- *Cancel* becomes *pause*. Read episodes are kept; nothing is filed; **Continue** re-runs the cycle,
  every accepted call replays free, and it files. The button reads "Pause" while a journal is active.
- *A plan stop in Stage 1 with partial success* no longer loses the batch. F1 is fixed by the same
  mechanism: the cycle stops at the trip, keeps the journal, and reports "paused".
- *A restart* leaves the journal and `run.json`. On startup the backend finds them and reports
  `resumable`. It does **not** continue by itself after a restart (V5-8), except under the opt-in in
  4.4 for a plan reset.
- *Authorship must be carried, not assumed.* Today a Sleep claim is stamped in
  `claim_reconciler._stamp_new` (`claim_reconciler.py:128-137`) with `engine_select.author_model(settings)`,
  which is the **configured main model alias**; only the commit trailer reads the models actually used
  (`agent_engine.models_used()`, `sleep_cycle.py:1585-1602`). With "Read faster", Stage 1 (which produces
  the claims) runs on the small model, so the claims would be signed with the main model, the sheet's
  honesty line would be false, and a later G104 re-read could not tell which claims the small model wrote.
  SL-1 therefore carries the per-call model from the seam onto the result: the seam's response records
  its model, Stage 1 copies it onto each extracted relationship and entity, and `_stamp_new` prefers that
  value over `author_model(settings)`. A journaled answer carries its stored model, so a batch half read
  by one model and half by another signs each claim with the model that wrote it, and the commit trailer
  still merges both into `authors`. **Until this ships, no copy anywhere says a belief records its
  model** (the sheet's trade-off list, R-2's mitigation and Past nights' model column are all gated on it).

**Ruling 3 check.** Ruling 3 lets a `.db` exist only if deleting it "costs CPU and never a fact".
Deleting the journal never loses a fact (every episode is still `processed: false` in the bank) but it
does cost paid LLM calls to redo. That is a stretch, stated rather than hidden: the journal is disposable
in correctness, not in cost, and it lives where no derived artifact can be tracked. V5-2 records it.

### 4.4 The run plan and the drain controller

> **Superseded in part (owner, 2026-09-29; TODO ruling 13).** The owner asked for the smallest correct version of "reads
> everything": *"i dont want to cap the max episodes per sleep, why would we cap them? its just progress that cicada has to
> go through."* Built instead of this section's controller: a person-started `POST /sleep/trigger` **is** the drain —
> `run(drain=True)` freezes the waiting ids and reads them in batches of `sleep_max_episodes_per_cycle`, each filed and
> committed by Stage 5 — with no hold, no `is_active()`, no `run.json`, no journal, no sheet and no `/sleep/run/continue`;
> `status == "running"` stays true for the whole run. This overrides **V5-15 and Q7** (Consolidate is the drain, from every
> door). Scheduled cycles still read one batch (ruling 4). What below is still design, unbuilt: the journal and accept
> protocol, the reserve, auto-continue after a plan reset, parallel reading, the drain-tagged cost summary. The
> once-per-drain rules for decay and the page reads, and the bank pin, are as this section says.

**The plan** is one small value, `SleepRunPlan`, saved with the engine choice in
`~/.cicada/connections.json` prefs under `sleep-run` (bank-independent, like `sleep-engine`):

| Field | Meaning | Default |
|---|---|---|
| `batchSize` | conversations per batch | 25 (today's cap; EX-4 may move it) |
| `scope` | `batch` (one) or `all` (the frozen list) | `batch` |
| `reservePct` | share of **every window the plan reports** kept free; the run stops starting new reads when any of them passes `100 - reserve` | Claude 10 (today's 0.9 for the 5-hour window) and 10 for the weekly window when the stream reports it; ChatGPT weekly-only 25 (Q4) |
| `autoContinue` | continue by itself after a plan reset, this run only, at most 2 times | off |
| `workers`, `smallModel` | parallel opt-in (4.5) | 3 (today), off |

Precedence, highest first: the trigger body (one run), the saved plan, the environment. An explicit
`CICADA_SLEEP_MAX_EPISODES_PER_CYCLE` pins the batch size and the UI says so, using the
`model_fields_set` idiom `PUT /sleep/engine` already uses.

**Endpoints.**

- `GET /sleep/plan`: the saved plan, plus facts the sheet needs: queue counts by kind, the resolved
  engine, `maxWorkers`, the discoverable small models with the vendor's own descriptions, the plan
  windows (from the app-server snapshot for ChatGPT, from the last stream signals for Claude) and, per
  window, whether the reserve can be enforced (`reserveEnforceable`).
- `PUT /sleep/plan`: saves defaults. 409 while a run is active.
- `POST /sleep/trigger` **with no body always means one batch, as today, from every door** (the Sleep
  page, the menu-bar worm, Home's Getting started *Read now*, the intake card's *Read now*, the Sources
  queue strip, the sidebar Consolidate command: `APIClient.triggerSleep` posts no body through
  `TriggerSleep` and `SleepViewModel.trigger`, and G125 R10 with its two narrow amendments defines each of
  those as a user trigger of one cycle). It never starts a drain and never continues one. While a drain
  is paused, a no-body trigger runs one ordinary batch over the oldest waiting conversations; accepted
  journal answers replay free, and the drain's plan is untouched.
- `POST /sleep/trigger` with a body `{scope: "all", batchSize, workers, smallModel, reservePct,
  autoContinue}` starts a run. The body is sent only by the "Read everything" sheet's Start.
- `POST /sleep/run/continue` with `{runId}` continues a paused run. It is a separate path on purpose and
  is reachable only from the Sleep page's Continue button, so nothing that says "Read now" can resume an
  open-ended, plan-spending run. It answers `SleepTriggerResponse` with the additive status `continued`
  (existing statuses `started`, `already_running` are unchanged, and an older app never calls this path);
  a wrong or ended `runId` is 404, a run on another bank is 409 with the `bank_switched` sentence.
- `POST /sleep/cancel`: unchanged path, now means *pause* when a journal is active.
- `POST /sleep/run/end`: drops the drain's plan; the journal stays until it is filed or expires.
- `DELETE /sleep/journal`: "Forget saved reading."
- Demo gate: `refuse_capture_into_demo` is a router dependency mounted only on the capture, sources,
  connectors and local-sources routers, and cannot express a check that depends on the body. So the
  **trigger handler itself** checks: in a demo bank, a body with `scope: "all"`, `workers > 1` or a
  `smallModel` answers 409 with a sentence; the no-body trigger keeps working, because a demo's own Sleep
  consolidates its made-up episodes as before. `test_demo_capture_routes.py` gains `/sleep/trigger`
  (no body: allowed; a drain body: 409) and `/sleep/run/continue` (409).

**The controller** (`api/services/sleep_run.py`, new). It owns the loop and calls the existing
`sleep_cycle.run` for each batch, so the pipeline is not forked:

1. *Freeze* the list of waiting episode ids, oldest first (the order `_get_unprocessed_episodes` already
   uses; recency wins in conflicts, so the order is load-bearing). Write `run.json`. Take the drain's
   hold (4.2).
2. *Pin the bank* (V5-9), in two layers, because `Settings.memory_path` is resolved on every access
   (`config.py:39-41`) and `POST /banks/{name}/activate` is deliberately unguarded during a cycle
   (`banks.py:183-185`), so a switch **inside** a batch would redirect every `settings.memory_path` read
   in it (the entity resolver's `SqliteVecIndexer`, the conflict resolver's tuning load, and others) and
   let that batch write into the other bank:
   - The controller passes each batch a `Settings` copy (the one `engine_select.resolve_settings`
     already makes) with `memory_path` fixed to `run.bank` for the run's life.
   - While a run's hold is live (`running`, `pausing`), `POST /banks/{name}/activate` answers **409** with
     a sentence ("Cicada is reading. Pause first."), the same pattern export and delete already use. A
     paused run releases the hold, so a switch is allowed then; Continue on another bank is refused
     (`bank_switched`) until the person switches back. Before every batch the controller also checks the
     active bank equals `run.bank`, as a last guard.
3. For each batch: pass `only_ids=` (the next `batchSize` unfinished, unparked ids from the frozen list;
   a conversation rewritten since is read again, its chunk hashes having changed), a fresh `cycle_id`
   and the run's `drain_id`, the plan's workers and models, and the drain flags in the next item.
4. *What a batch skips* (V5-7). Decay has **two** engines and both are switched off in a batch: entity
   decay in `conflict_resolver.resolve_and_prune` (`conflict_resolver.py:154-256`, which has no decay
   parameter today; SL-2 adds `decay: bool`) and claim decay in `claim_reconciler._decay_claims`
   (`claim_reconciler.py:655`), which runs inside the in-cycle Stage 5.56 reconcile (`reconcile(...,
   decay=False)`). Both run once, on the drain's last batch. Also skipped per batch: the engine-independent
   tail (`skip_tail=True`, run once at the end) and **Stage 5.57's in-cycle link page reads**
   (`skip_links=True`; the links are picked up by the tail's backfill at the end, up to its own cap of 20,
   and the rest by later cycles). Still run per batch, because they are engine-free, idempotent and how
   the batch's claims reach the graph: the Stage 5.56 reconcile itself (decay off) and the open-question
   refresh. SL-2 confirms this list by reading, and `test_drain_skips.py` pins it.
5. After a batch: read the breaker and the plan windows. Stop cleanly on a throttle, an exhaustion, the
   reserve, an overage refusal, sign-out, an error, a cancel, or a bank switch, with a `pause` block.
6. *Outcomes and attempts.* `entity_extractor.extract()` today returns only the successes and keeps
   `failed` as a closure-local counter with exceptions logged and swallowed (`entity_extractor.py:307-451`),
   so the controller cannot tell which conversation failed or why. SL-1 changes `extract()` to return one
   **outcome per episode**: `ok`, or `failed` with a reason class. The mapping is by exception class and is
   fixed here:

   | Class raised | Reason class | Effect |
   |---|---|---|
   | `EngineUnavailable` (signed out, engine missing), `EngineThrottled`, `EngineExhausted`, `EngineOverage` | pause | the run pauses; never counted against the conversation |
   | `EngineModelNotFound` | pause (`error`) | the run pauses with the model named; the person picks another |
   | `EngineTimeout`, `EngineProtocolError`, `ValueError` (unparseable), an empty or schema-refused answer, a context-window overflow, a content refusal | content | counted; the second one parks the conversation |
   | `EngineFailed`, a provider 5xx / `BadRequestError` / any other provider `APIError`, a network or OS error | pause | (review fix, 2026-09-30) the engine's, never the conversation's |
   | anything else | content | as above — but a batch where **every** conversation failed with one is the engine's: a stop, nothing parked |

   One wrinkle is fixed at its source: on a plan engine an **empty answer arrives as `EngineUnavailable`**
   (`agent_engine.py:480-490`), the class Stage 1 labels "signed out or missing", so empty output would
   pause as `signed_out` instead of parking. SL-1 raises `EngineProtocolError` for an empty answer from an
   engine that is signed in and exited cleanly, and keeps `EngineUnavailable` only for a real signed-out
   marker. A laptop that slept mid-call surfaces as a timeout or a dropped connection; those are
   content-class by mapping, but two in a row on the same conversation park it *with the reason in
   words*, and Retry is one click, so the cost of a wrong park is small (R-9).
7. *The drain always terminates.* Every episode has a hard cap of three attempts of any class in one drain,
   after which it is parked ("kept failing"). A batch that makes no progress (no episode read and none
   filed) twice in a row pauses the run with `no_progress` instead of looping. An episode is never picked
   twice inside one batch.
8. At the end: run the engine-independent tail **once**, decay once, then the single completion.

**Shared budgets across batches (V5-7).** One `DecayBudget` for the drain (the in-flight change adds it
per cycle), decay charged once at the end and never in a batch, the tail once. A drain also carries one
inbox budget for *new questions*: the first-run history will otherwise raise a burst. Above the budget,
questions are still written (nothing is dropped) but ordered and capped in what "Needs you" shows on
Home. The exact cap is a product call outside this spec (risk R-6).

**Plan reserve, and what it can and cannot promise.**

- *Claude.* The 5-hour window: `stop_utilization = 1 - reserve` (the machinery exists). The **weekly**
  window: `claude_stop` deliberately does not stop on it, so the controller adds a run-level check on the
  weekly utilisation the streams report (`plan_limits` already parses a `seven_day` signal), pausing with
  `plan_weekly`. Where a stream does not report a weekly figure, that window's reserve is unenforceable
  and the sheet says "Your weekly limit isn't reported by this engine, so it can't be kept free" rather
  than promising it. Auto-continue never crosses a weekly pause.
- *ChatGPT.* There is no per-call signal, so the controller reads the app-server snapshot (about 0.5 s, no
  quota) every 5 finished calls and at every batch boundary, and stops when a window passes `100 - reserve`.
- *Neither is exact.* `agent_engine.complete` reads a window's utilisation only after a call returns
  (`on_signals`), never before one starts, and up to `workers` calls are in flight. So the honest
  promise is: **the run stops starting new reads once a window passes the line; calls already running
  finish**. Overshoot is bounded by `workers` calls on Claude and by 5 calls plus `workers` on ChatGPT, and
  is unmeasured on both (EX-2). Because the overshoot grows with the fan-out, **6 and 10 workers are not
  offered on either plan** until EX-2 has measured it (V5-10); on an API key, OpenRouter or Ollama there
  is no plan to overshoot.

**Pause and resume.** On a limit the vendor's reset time comes from the exception (`resets_at`, today
dropped by `trip_breaker(str(exc))`; SL-2 keeps it) or, for ChatGPT, a fresh snapshot. The run becomes
`paused` (or `waiting_reset` when auto-continue is armed and the reset is within 36 hours) and shows the
reset in the vendor's words. Continue, by the button or, if armed, by the timer, runs the same loop.

**Ruling 4.** Ruling 4 says a scheduled cycle never spends plan quota. A drain is started by a press, so
it complies. Auto-continue after a reset is the grey area: the person is not there when it spends. It is
proposed as a **per-run checkbox, off, with the reset time shown, at most two continuations, expiring
after 36 hours** and never armed by a scheduled cycle or crossing a weekly pause. This needs a written
amendment to ruling 4 ("a run the person started may continue itself after a plan reset if they said so
for that run"). Q1.

**Call volume is part of the ask, not a footnote.** A first-run drain is the largest volume of plan calls
Cicada would ever make. By the older measurement (200 to 350 Stage 2 calls per 20 episodes), 1,187
conversations is on the order of 12,000 to 21,000 judge calls alone, before Stage 1's chunks and Stage 3's
two calls per updated page, and that is with one worker. That is arithmetic on an old figure, not a
measurement, and it is never shown as a prediction. It matters because the repo's own open question
(`subscription-first-portability.md`, Risks) is whether a nightly personal batch is "ordinary, individual
usage" on a consumer plan and it warns that the Claude docs steer scripted volume to API keys. So the
running screen shows the **count of calls made so far** as a counted fact (`run.calls`), and Q1 asks
whether a drain on a consumer plan is acceptable at all, or whether the first drain should recommend an
API key or OpenRouter (Q1b).

### 4.5 Parallel reading

**What is safe to parallelise.** The whole analysis is about order. The git single-writer rule is not in
play for any LLM call: only Stage 5 and the tail write to the bank, and those stay sequential.

| Step | Order-dependent? | Parallel treatment | Result identical to sequential? |
|---|---|---|---|
| Stage 1, across episodes | No. Each answer is a function of one episode | Already gathered. `workers` replaces the constant | Yes; results are placed by input index, so order is preserved |
| Stage 1, chunks inside an episode | No. Merged in chunk order | `gather` the chunks of one episode | Yes, merge order fixed |
| Stage 2, judge calls against **existing** pages | No. `existing` is fixed at cycle start and a judgement is a function of (name, candidate) | **Prefetch**: generate every (name, existing-candidate) pair up front, judge them concurrently into the existing `llm_match_cache`, capped at K per name | Yes in the loop's output; the loop still runs sequentially and reads the cache |
| Stage 2, judge calls against **in-cycle creates** | Yes. Candidates appear as earlier names are created (`created_by_id`) | Stay on demand, sequential | Unchanged |
| Stage 2, direct (fuzzy) matches | Yes for created candidates | Deterministic pre-pass excludes names that match an existing page directly | Unchanged |
| Stage 3, merge and contradiction per updated page | No across pages | `gather` per page, apply results in the original list order (`conflict_nudge` appends keep their order) | Yes |
| Stage 4, one skills call | n/a | none | n/a |
| Stage 5 writes, indexes, commit, tail | Yes (single writer) | none | n/a |
| Stage 5.57 link summaries | No, but it fetches other people's pages under the ToS rail | out of scope | n/a |

**Prefetch's cost is honest, not free.** The sequential loop stops at the first "same"; prefetch judges
pairs the loop would never have asked. K bounds that (default 8 per name; the loop still falls back to
its own on-demand calls for any pair beyond K, so the *outcome* never depends on K). Whether the
speculative calls cost more window than the wall-clock saves is EX-5's question, and the UI never says
"cheaper".

**The knob is three numbers.**

- `workers`: 1, 3 (today), and 6 or 10 **only on an engine with no plan to overshoot** (API key,
  OpenRouter) until EX-2 has measured overshoot on the plans (4.4). Passed as `agent_max_concurrency` in the `Settings` copy that
  `engine_select.resolve_settings` already makes, and as Stage 1's concurrency. A machine-wide ceiling
  of 10 (`MAX_CONCURRENCY`). Sleep's workers and a concurrent Ask each hold their own permits today
  (`providers._AGENT_SEMS` is keyed by limit), so the process count can briefly reach workers + 3.
- `smallModel`: which model does the bulk stages. Default stage set: **Read** (`extraction`) and **Sort**
  (`disambiguation`, already `haiku` on the Claude plan). **Decide** (`merge`, `conflict`) and **Notice**
  (`skills`) stay on the main model, because the merge is the prose a person reads and a skills miss is
  silent. Q3 asks whether to widen it once EX-3 has parity data.
- `reservePct`: the guard above.

**Choosing the small model without hardcoding one.** Claude: `haiku` is in the existing picker
(`_AGENT_MODEL_CHOICES`). ChatGPT: the roster has no size marker in the names, so the picker lists the
roster **with the vendor's own description beside each entry**, and Cicada preselects nothing. It may
*suggest* one entry, only when exactly one description contains "fast", "affordable", "efficient" or
"small", labelled "suggested by its description". The priority service tier ("increased usage") is never
selected. Roster and descriptions are read live from `model/list` on every open.

**The trade-off, as the sheet says it** (section 4.6 B): faster wall-clock; your plan's window fills
faster because the same reading happens in less time; a smaller model can miss subtler links, and (once
SL-1's authorship stamp ships, 4.3) each belief records which model wrote it; if a limit is reached what
was read is kept. Off by default. It
never applies to a scheduled cycle, because scheduled cycles never use a plan (ruling 4); on an API key
it applies as-is and costs the same tokens (plus prefetch's speculative calls) in less time.

**First batch first (Q6).** The first drain of a bank always starts with one batch and then asks
"Read the rest?". That is also the cheapest quality control for a smaller model: the person sees what it
filed before committing the window to 1,100 more.

### 4.6 App surfaces

All in the one 760 pt column (DR-36). Numbers and names in the mocks are placeholders. Nothing new sits on the room; new controls appear only when they
have news (queue larger than a batch, a run active, a pause). Tokens and components are D's: `bgFocus`,
`bgBadge` tracks, `SectionLabel`, `Tag`, four button kinds (DR-40), floating surfaces for popovers,
`SettingsSheet`-style sheets for a decision with consequences.

**Plan figures stay where ruling 12 puts them (V5-16).** TODO ruling 12, DR-59 and the CLAUDE.md
Sleep-page paragraph allow a plan or price figure on Details and the engine menu "and nowhere else yet".
The room sentence, the sheet, the strip and Settings therefore carry **no** percentage of a plan window.
A reserve is *named* there ("leave room in my plan") and its number appears only in the engine menu and
in Details. Counts of finished work (conversations, names, pages, calls made) are not plan figures and
appear anywhere the page already shows counts.

**A. Idle, first run, a large queue.** The sentence names the count and the first step; one quiet text
button offers the drain; the primary button stays the one primary (DR-40). The lamp and the whisper line
are as today.

```
 Sleep                                                              [?]

 ┌ room card ────────────────────────────────────────────────────────────┐
 │   [ window · worm reading on the cushion · a tall pile of books ]     │
 │                                                                       │
 │            1,187 conversations to read.                               │
 │            The first 25 start your memory.                            │
 │                                                                       │
 │     ( ☾ Consolidate )   [ ◉ Claude plan · Sonnet ▾ ]                  │
 │                     Read all 1,187 …                                  │
 │     ☾ Manual · nothing runs unless you press.                         │
 └───────────────────────────────────────────────────────────────────────┘
 › Details
```

"Read all 1,187 …" is a `TextButton` shown only when the queue exceeds one batch; it opens the sheet and
starts nothing. Consolidate is unchanged: one batch, no body. G125 R10's record is a closed set of two
narrow amendments and this is a third control, so it is asked for rather than assumed (V5-15, Q7).

**B. The "Read everything" sheet** (a sheet, not a popover: it starts a long spend). Every count is a
real count; nothing is estimated and no plan figure appears (V5-16). The batches figure is the frozen
list divided by the batch size.

```
 ┌ Read everything ──────────────────────────────────────────── esc ×┐
 │ 1,187 conversations are waiting. They are read oldest first, in   │
 │ batches. Each batch is filed and saved before the next starts.    │
 │                                                                   │
 │ What it reads       Conversations and notes                1,187  │
 │                     Pages (42) and videos (7) are read            │
 │                     separately, from the Feed.                    │
 │                                                                   │
 │ Batch size     [ 25 ▾ ]                          48 batches of 25 │
 │                                                                   │
 │ Runs on        [ ◉ Claude plan · Sonnet ▾ ]                       │
 │   Stops starting new reads early to leave room in your plan.      │
 │   Set how much in this menu. Reads already running finish.       │
 │   Your weekly limit isn't reported by this engine, so it can't    │
 │   be kept free.                       (shown only when true)      │
 │                                                                   │
 │ ▸ Read faster                                                Off  │
 │ ☐ Continue by itself when my plan resets (at most twice, 36 h)    │
 │                                                                   │
 │ Each conversation takes several calls to your plan. The count is  │
 │ shown while it runs. On a consumer plan, an API key or OpenRouter │
 │ may suit a first read better.                                     │
 │ You can pause any time. What was read is kept.                    │
 │                                          [ Cancel ]  ( Start )    │
 └───────────────────────────────────────────────────────────────────┘
```

- Batch size is a native menu `Picker` (10 · 25 · 50 · 100), the precedent DESIGN_RULES section 9
  (2026-09-24, R-HS10) set for the engine menu's model: DR-45's text tabs are single-select filters that
  deselect on a second tap, which is wrong for a value that must always hold one. No new §9 departure.
  The reserve is **not** a control on the sheet: "Runs on" opens the same `EngineQuickMenu`, whose
  "Keep plan free" row (4.6 F) is the one place its number is shown and set (ruling 12).
- The "weekly limit isn't reported" line is data-driven from `GET /sleep/plan`'s `reserveEnforceable`,
  shown only when a window's reserve cannot be enforced.
- "Read faster" is a disclosure (DR-39), collapsed and remembered per viewer. Opened:

```
 │ ▾ Read faster                                                 On  │
 │   Reads several conversations at once with a smaller model.       │
 │   What you trade                                                  │
 │    · Your plan's window fills faster: the same reading, less time.│
 │    · A smaller model can miss subtler links between people and    │
 │      projects.                                                    │
 │    · If a limit is reached, what was read is kept.               │
 │   At once       [ 1 ▾ ]  (3 is today's default)                   │
 │   Reading model [ Haiku ▾ ]                                       │
 │   Not used for scheduled cycles. Those never spend your plan.     │
```

The line "Each belief records the model that wrote it" is **added to the list only once SL-1's authorship
stamp ships** (4.3); until then it is not true and is not written. On a plan, "At once" offers 1 and 3;
6 and 10 appear (on any engine) only after EX-2 has measured overshoot, with a `.help` saying why until
then. On the ChatGPT plan the model menu reads, per row, "GPT-6-Luna, Fast and affordable model for
easier tasks" (the vendor's words). If the first drain has never run, "Start" reads "Start with the first
batch" and the run stops after one batch to ask (Q6).

**C. Running.** The sentence carries the live count; the strip gains per-stage fills and one caption
line; a drain adds a bar and one line of words. The primary button becomes Pause.

```
            Reading 14 of 25.
            Batch 3 of 48 · 62 of 1,187 filed.

     [ ‖ Pause ]   [ ◉ Claude plan · Haiku · 3 at once ▾ ]     Running 6 min

     Read          Sort      Decide     Notice     File
     ▮▮▮▮▯▯ 14/25  ▯▯▯▯▯▯    ▯▯▯▯▯▯     ▯▯▯▯▯▯     ▯▯▯▯▯▯
     Reading conversations · 1 could not be read

     ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
     62 filed · 14 read, waiting to file · 1,111 waiting · 412 calls made
```

- Fill grammar (neutral, DR-5 keeps accent for its six uses): **filed** `textPrimary`, **read and
  waiting to file** `textTertiary`, track `bgBadge`. A failure is a `warning` glyph plus words, never a
  colour alone (DR-7). This retires the strip's accent fill, which the Sleep track's DS sweep owed.
- Read, Sort and Decide each show `done/total` with their own noun in the caption. Notice and File show
  a breathing bar and, for File, the words "Filing. It cannot be stopped now." (a cancel after Stage 5
  starts is refused by design, `sleep_cycle.py:1361-1368`).
- Elapsed time is shown ("Running 6 min"). There is no remaining time. "Calls made" is a count of paid
  calls (`run.calls`); a journal hit is not a call.
- While a drain runs, the button is Pause and nothing on the page starts a second run.
- **Amends P15 (R-A8):** "only Read carries a fill" becomes "a stage carries a fill only when it counts
  something that finished; Read, Sort and Decide do". The rule's purpose, no invented fractions, stands
  and is what Rule 1 above restates.

**D. Paused at a limit.** Mood is `.reading` (queue non-empty, nothing running), so no new art. The
lamp stays tied to the schedule; an armed auto-continue is written in the whisper line and the lamp
popover, not drawn.

```
            Paused. Your plan window is full.
            Resets after 14:00. 118 of 1,187 filed, 9 read and kept.

     ( ▶ Continue )   [ ◉ Claude plan · Sonnet ▾ ]      End this run
     ☾ Will continue by itself after 14:00. You said so for this run.     (only when armed)
```

Both tails are in the ladder (4.6 I). With auto-continue **armed**, the tail reads "Continues after
14:00." and the whisper line says so; with it off the tail is "Resets after 14:00. Continue when you
like." and the whisper line is absent, so "Continues" is never said to a person who did not arm it. On
ChatGPT with a weekly-only window the reset can be days away: "Resets Tue 14:00." and auto-continue is
not offered beyond 36 hours (Q1). "Continue" calls `POST /sleep/run/continue` (4.4), not the trigger.
"End this run" is a `TextButton`; it keeps the journal until it expires. A reserve pause reads "Paused to
leave room in your plan." with no figure (V5-16).

**E. After a restart or crash.** Same layout, `pause.reason = restart`:

```
            Cicada restarted while reading.
            14 read and kept. Continue to file them.
     ( ▶ Continue )
```

**F. The engine menu** (`EngineQuickMenu`) gains two rows under the model picker; nothing moves.

```
 ┌ ─────────────────────────────────────────────────────┐
 │ ◉ Claude plan       Session 41% · weekly 12% used     │   (existing, ruling 12)
 │ ○ ChatGPT plan      Weekly 3% used                    │
 │ ○ OpenRouter   ○ Ollama   ○ API key                   │
 │ Model            Sonnet ▾                             │
 │ Read faster      Off  ▸                               │   new: opens the same disclosure
 │ Keep plan free   10%  ▸                               │   new: the one place the reserve's number is set
 │ When you start   Claude plan · Sonnet                 │
 │ Scheduled cycles  API key · gpt-…                      │   (ruling 4, unchanged)
 │ Last cycle: 41% → 43% of your 5-hour window           │   (existing)
 └───────────────────────────────────────────────────────┘
```

The menu button reads "Claude plan · Haiku · 3 at once" only when parallel is on; otherwise it reads as
today. The reserve is a plan figure, so this menu and Details are its only homes (ruling 12).

**G. Details** (closed by default, remembered; D's list grammar, no cards).

- **Last cycle** gains, while a drain runs or after one, a *drain row* in ruling 12's grammar:
  "Reading all · 1,187 conversations in 48 batches, 2 pauses · your 5-hour window moved 12% to 47% across
  4 windows (the whole plan's meter, including anything else you used)". For ChatGPT: "tokens not
  reported", and each window's before and after from the snapshots. For an API key: "charged" versus
  "at list price", as `CycleUsageText` already words them. Unknown is never zero. This row is a plan
  figure and lives here, in `CycleUsageText`, and nowhere else.
- **What's waiting** rows carry one state glyph (read, waiting, parked) and, for a parked row, the reason
  in words and a Retry `NeutralButton`.
- **Past nights** groups a drain's batches under one "Reading all" row (joined by `refs.drain_id`, ids
  only, so no new commit trailer), each batch keeping its existing usage line. The group row shows the
  model or models that read it, so a smaller model is visible after the fact; that column is gated on
  SL-1's authorship stamp (4.3). Its cost is aggregated from the `llm_call` rows by `drain_id` (4.4 and
  SL-4), never from `sleep_run` alone, so a paused batch is counted.
- **Saved reading** (new, only while a journal exists): "14 conversations read and kept · 3 MB" with a
  `Forget saved reading` `NeutralButton` (danger label, behind a confirmation, DR-40).
- **What's waiting** ends with one quiet note row, "Sleep reads conversations and notes. It fetches a
  saved link only within Cicada's fetch limits, never behind a login, and never drives a browser. Pages
  and videos are read separately." (section 4.7). The earlier wording, "Sleep never browses", was wrong:
  Stage 5.57 and the tail backfill do fetch saved links through `link_enrichment.default_fetch`, under the
  ToS rail (4 s, at most 512 KB, no cookies, never behind auth).

**H. Settings → Sleep** gains a "Reading" group with the sheet's fields as defaults: batch size, read
faster (off) and "Keep my Mac awake while a run is going" (Q5). It carries **no reserve figure** (ruling
12): a row "Leave room in my plan" reads "Set in the Sleep page's engine menu" and opens it. One
`SleepRunPlan`, three doors (sheet, menu, Settings), the rule Track E's engine picker already follows.

**I. The sentence, the worm and the answers** (`RoomSentence.swift`, pure; lead at most 40 characters,
tail at most 80, no clock read; a reset time is a data input like `nextRunWhen`):

| State | Lead | Tail |
|---|---|---|
| Reading, one batch | Reading 14 of 25. | the stage's own detail, as today |
| Reading, a drain | Reading 14 of 25. | Batch 3 of 48 · 62 of 1,187 filed. |
| Sorting | Sorting 31 of 86. | Matching new names to what you have. |
| Deciding | Deciding 4 of 12. | Checking pages for contradictions. |
| Pausing | Pausing. | Finishing the calls already started. Nothing read is lost. |
| Paused, plan, auto-continue armed | Paused. Your plan window is full. | Continues after 14:00. 118 of 1,187 filed, 9 read and kept. |
| Paused, plan, auto-continue off | Paused. Your plan window is full. | Resets after 14:00. Continue when you like. |
| Paused, reserve | Paused to leave room in your plan. | Continue when you like. 118 of 1,187 filed. |
| Paused, you | Paused. | 118 of 1,187 filed. 9 read and kept. |
| After a restart | Cicada restarted while reading. | 14 read and kept. Continue to file them. |
| Paused, bank | Paused. You switched memory. | It continues in <bank> when you switch back. |
| Parked | (whisper) 3 conversations could not be read. | See What's waiting in Details. |
| Done | Filed 1,187 conversations. | See what changed ›. |
| First batch done (first drain) | Filed 25 conversations. | Your page has 31 beliefs so far. Read the rest? |
| Idle, videos picked up | (the idle lead as today) | An agent has picked up 3 videos. |

The last row is the sibling video spec's tail (its R-VU9 wording, "picked up", never "being watched"),
admitted here on purpose but at the **lowest** priority: it speaks only when no consolidation state has
the tail, so a drain's tail always wins, and the video spec still owns its words and its data. The
"First batch done" tail is a count from the graph (beliefs on the owner's page), not a plan figure.

The room's moods are unchanged (`sleeping` while running, `reading` while paused or waiting, `happy` on
the one cheer at the end). The worm's answers gain three rungs for paused, resumable and parked. Every
new fact has a text twin (R-A3). No new sprite, no new weather; the window's weather stays a total
function of the mood.

**J. Accessibility and motion.** The bar and the strip's pips are one accessibility element each with a
value ("62 filed, 14 read and waiting to file, 1,111 waiting, 1 could not be read"); a pause, a resume
and a finish are announced (`AccessibilityNotification`, as `Copy.sleepFinished` is). Fills settle with
`SleepMotion.settle` (no new duration, DR-61), keys never animate (DR-60), Reduce Motion holds the
terminal frame (DR-66), everything scales with `uiScale` (DR-70) and is checked light and dark (DR-71).
Each new row has a `.help` twin (DR-69).

### 4.7 Hooks for the sibling designs

Two sibling specs written the same day (video queue; reading the web) need a place on this page. They
agree with this one on the seams, and where they differ each wins for its own surface.

- **Three rows, three jobs, three nouns.** Details › What's waiting lists **Conversations** (this spec's
  queue and the only thing "Read everything" drains), **Pages waiting to be read** (reading-the-web's
  reader, with its own "Read now ›") and **Videos waiting** (video spec, "Open in Feed ›"). Each job has
  its own bar and its own words ("read" for a page, "watched" or "read" for a video, "filed" for a
  conversation). A bar that merged them would be wrong for hours after each import, which is the same
  reason R-A5 forbids a bare percentage.
- **Sleep triggers only consolidation.** The video run's control lives in the Feed's Videos view (video
  spec R-VU4, R-VU5), and page reading and any agent reading are started from their own surfaces and
  never from a schedule (reading-the-web R-RW8). On this page **Consolidate stays the only one-batch
  trigger**; the run controls (Read all, Start, Continue, Retry) are a separate, asked-for amendment
  (V5-15, Q7), and no other door (menu-bar worm, Home, the intake card, the Sources strip) can start or
  continue a run (4.4). The sheet's "What it reads" line says what is not included and where it is read.
- **A running sibling job** may show one line under What's waiting in that job's own words (the video and
  reading specs define them). They read their own state endpoints; this page adds nothing to
  `/sleep/status` for them. If they later want the journal, the pause semantics or the plan reserve, the
  machinery in 4.3 and 4.4 is generic (calls memoised at the seam, a frozen list, a reserve), but that is
  their decision and not assumed here.
- **Does consolidation use a browser or computer use? No, and it should not** (V5-12). Sleep's own engines
  are sandboxed (`--safe-mode`, `--tools ""`; `--ignore-user-config`, no plugins, apps or shell), and the
  2026-09-29 research found the Claude-in-Chrome and browser-harness stacks installed but off or
  unattached. Anything that looks at a logged-in page runs as the person's own agent, in a run the person
  chose, from the reading-the-web surface. This page therefore shows no harness status list. It carries
  one honest sentence (the note row above, which admits the fetch of saved links under the ToS rail and
  denies only a browser and a login) and a link to Settings → Reading the web, which owns the modes and
  whether an agent may read.

### 4.8 First run and the owner's page

The owner asked that a new bank start with the owner's own page, "(you)", with a small sentence, filled
by consolidation and chats, and that Cicada **not** assume anyone has a bank to carry knowledge from.
Where it stands:

- **Built elsewhere, not merged.** Local branch `fix/first-run-extraction-owner`, commit `1d00d1d`:
  `create_bank` seeds one `owner: true` person page (the machine-level name from `owner.json` when saved,
  else a neutral "Owner" placeholder), opening "The main person this memory belongs to.", committed alone
  as `cicada`. `name` stays plain so Stage 2 still matches the person's own name; the app renders
  "(you)" from `owner: true`; `PUT /settings/owner` adopts the placeholder instead of writing a second
  owner page; the demo bank is excluded. This spec depends on that and does not redesign it. It is
  the existing `ensure_owner_entity` page is evergreen, so a drain's decay never touches it;
  SL-2's `test_drain_decay_once.py` asserts that for the seeded page too.
- **No prior bank is assumed.** A first drain starts from an empty graph and the owner's page. Exports
  that carry a memory file (Claude or ChatGPT) already arrive as the *assistant's* words on that branch
  (commit `861af05`), a lead Sleep can check against what the person actually said, not the owner's
  own statements. Those files may be outdated, which is exactly why they are a lead and not a source of
  truth.
- **What this spec adds: where the first drain shows it filling.** After the first batch of a bank's
  first drain, the run stops to ask (Q6), and the sentence's tail carries a count read from the graph
  ("Your page has 31 beliefs so far. Read the rest?", 4.6 I) with "See your page ›" beside Continue. It
  is a count of claims on the `owner: true` page, engine-free, and it appears only in that one state. If
  the owner page does not exist yet (a bank made before that branch), the tail omits the sentence rather
  than showing a guess, and the drain never creates the page itself.

---

## 5. Rails and terms of service

Each is binding on the build.

1. **Every LLM call is read-only against the bank.** Only Stage 5 and the tail write, sequentially, under
   the per-bank git lock (`test_git_write_lock.py` keeps failing for any other writer). Workers never
   touch `entities/`, `episodes/` or git.
2. **Ruling 4 holds.** A scheduled cycle never spends a plan, and never runs parallel or a drain. The
   only proposed change is auto-continue after a reset for a run the person started (Q1).
3. **Ruling 12's grammar for every figure, and its two surfaces.** Basis in words; a plan's percentage
   is the whole plan's; unknown is never zero; only consolidation is counted; the ledger stays ids, enums
   and numbers. Ruling 12, DR-59 and the CLAUDE.md paragraph allow plan and price figures on **Details and
   the engine menu, "and nowhere else yet"**. So the drain summary lives in `CycleUsageText`; the reserve's
   number lives in the engine menu; and the room sentence, the sheet, the strip and Settings carry no
   plan percentage (V5-16). An earlier draft put "80% used" and "20% is kept" on the sheet and the
   sentence; that was a widening of the ruling nobody had asked for, and is withdrawn (Q8 offers the
   widening to the owner if wanted). DR-59's lint, `PriceLintTests`, **does not exist yet** (its own
   comment says so, `AutoRecallTests.swift:167`): SL-4 either writes it (new work, in scope of SL-4) or
   this rail is held by review alone. It is not claimed as passing.
4. **G107.** No estimates and no remaining-time anywhere. The bans are spread over three suites, not
   one: `RoomSentenceTests` (`:201`), `RoomFeedTests` (`:40`) and `SleepHeroTests` (`:238`) hold the
   banned words ("cluster", "insight", "est", "~"); `SleepNumbersLintTests` holds "a `%` needs a noun"
   from the fixed list `[Rested, Read, volume, age, Stage]` on `Text(` lines under `Views/Sleep`. New
   strings go through `Copy` (which the lint reads through), and the noun list is extended
   *deliberately* (adding "filed", "read", "calls") only if a new `%` string remains after V5-16 removed
   the sheet's percentages.
5. **Sandboxes are not loosened.** `--safe-mode`, `--strict-mcp-config`, `--tools ""`,
   `--setting-sources ""`; `codex exec` in Cicada's isolated home with `--ignore-user-config` and the
   `--disable` list. Parallel means more of the same children, never different flags. `CICADA_CAPTURE=off`
   on every spawn.
6. **No credential handling and no scraping.** Cicada holds no vendor token; it runs the vendors' own
   CLIs (never `--bare`, never a token replay). A plan rejection is never retried with different headers,
   another account or extra usage (the ToS rail's rule, applied to plans): the run pauses. `agent_allow_overage`
   stays off unless the person opted in.
7. **Terms, and volume.** Two separate exposures. *Concurrency:* concurrent CLI children on a consumer
   subscription is unmeasured. *Volume:* the repo's own open question is whether even a nightly personal
   batch is "ordinary, individual usage" and it warns that the Claude docs steer scripted volume to API
   keys; a first-run drain is the largest volume of plan calls Cicada would make (4.4: on the order of
   12,000 to 21,000 judge calls for 1,187 conversations at one worker, arithmetic on an old figure), and
   auto-continue chains it across windows. This spec therefore keeps parallel opt-in, person-started,
   bounded (at most 10, and 1 or 3 on a plan until measured), pauses rather than pushes at limits, shows
   the count of calls made, and asks whether a consumer-plan drain is acceptable at all (Q1b). Vendor
   terms were not re-read here; before "6" and "10" become selectable on a plan, EX-2 records the
   vendor's documented and observed behaviour and the owner signs off (Q2).
8. **Privacy.** The journal holds extracted content: machine-local, 0600, never logged, never in a bank
   or a commit, never in telemetry (counts and enums only, `journal_hits`), purged on commit, at 7 days
   and at 50 MB, with a Forget action. Nothing personal about the owner or anyone in their life goes
   into a doc, a commit or a PR for this work; examples use placeholders.
9. **Demo bank.** A demo bank refuses a drain and the parallel opt-in through a **body-aware check inside
   the trigger handler** (4.4), not through `refuse_capture_into_demo`, which is a router dependency
   mounted only on the capture, sources, connectors and local-sources routers and cannot see a body. The
   no-body trigger keeps working, so a demo's own Sleep still consolidates its made-up episodes as before.
10. **Docs move with the code:** CLAUDE.md's Sleep section and Sleep-page paragraph, DESIGN_RULES section
    9 (P15 amendment, the neutral fill grammar), the G125 R10 amendment (Q7), TODO rulings 4 and 12 cross-references, the `G125` and
    `G107` rows, a new backlog row per slice (ids assigned when filed).

**Rulings this spec proposes (`V5-n`, binding once the owner accepts them)**

| # | Ruling |
|---|---|
| V5-1 | Read and filed are two durable states; the bar shows both. |
| V5-2 | The journal memoises LLM answers at the seam, only for a Sleep scope and only after the calling stage has **accepted** the answer; machine-local, purged on commit; a stretch of ruling 3 that is disposable in correctness, not in cost. |
| V5-3 | A stage carries a fill only if it counts finished work with its own noun (amends P15). |
| V5-4 | Cancel is pause whenever a journal exists; nothing paid for is thrown away. |
| V5-5 | A drain works over a frozen id list; arrivals are counted and left for the next run. |
| V5-6 | Failures are classified by exception class: pause-class (signed out, throttled, exhausted, overage, model not found) stops the run and never counts; content-class counts, two park the conversation, and every episode has a hard cap of three attempts per drain so a drain always terminates. |
| V5-7 | A drain charges decay once, runs the tail once, and shares one decay-inbox budget. |
| V5-8 | A restart pauses a run; nothing spends the plan by itself after a restart. |
| V5-9 | A drain is pinned to the bank it started on: a fixed-bank `Settings` for every batch, and `POST /banks/{name}/activate` is refused (409) while its hold is live. A switch while paused is allowed and Continue refuses until the person switches back. |
| V5-10 | Parallel is opt-in, off by default, never on a schedule, and its trade-off is written where it is chosen. |
| V5-11 | A small model is discovered from the engine's own roster and shown with the vendor's description; none is hardcoded. |
| V5-12 | Consolidation's engines never gain a browser, a shell or a signed-in session; anything that does runs as the person's own agent. |
| V5-13 | A run-level reserve applies to every window a plan reports (Claude's weekly window included, when reported); the run **stops starting new reads** once a window passes `100 - reserve`, and calls already running finish. It is a promise about starts, not a cap. |
| V5-14 | `status` stays `running` across a drain's batches by a drain hold read through one helper, `sleep_cycle.is_active()`, at every gate (scheduler, trigger, the 409 writers); the hold is released on any pause; the cheer fires once. |
| V5-15 | *(Reversed by TODO ruling 13, 2026-09-29: a no-body trigger is a drain. The only guard kept: a paused run is continued from the Sleep page alone, which the app's doors enforce; the server keeps a no-body trigger a fresh run.)* A no-body `POST /sleep/trigger` is one batch, from every door, always. A drain starts only from the sheet's body and continues only through `POST /sleep/run/continue` from the Sleep page. Amends G125 R10 (Q7). |
| V5-16 | Plan and price figures stay on Details and the engine menu (ruling 12). The room sentence, the sheet, the strip and Settings show none, and a reserve is named there without its number. |

---

## 6. Cost

**To the person (all of this is unmeasured until the EX-n run; see 1.3).** A drain costs what its
batches cost. The ledger records each batch as it already does (ruling 12). Parallel changes the rate,
not the tokens per call, except for prefetch's speculative Stage 2 calls; a smaller model may lower the
window used per call (assumed). The journal saves cost: a paused or restarted run no longer re-buys what
it read. The first drain always shows a real before and after on the plan meter.

**To the machine.** N `claude -p` (Node) or `codex exec` children at once. Memory per child is
unmeasured (EX-2 records RSS). The default thread pool serves both these calls and the index rebuilds,
so `workers` is capped at 10.

**To build (relative sizes, an assumption).** SL-1 large (the journal with its accept protocol and
episode index, per-episode outcomes, the authorship stamp, the stage counters), SL-2 large (controller,
hold and `is_active()` at every gate, sheet, pauses, budgets), SL-3 medium (parallel, gated by
EX-2/3/5), SL-4 medium (drain-tagged usage, the paused-batch record, and `PriceLintTests` if written). Backend and app can proceed in parallel inside a slice once the wire above is agreed.

---

## 7. Phasing, and what proves each slice

Each slice is one PR to `dev`, built to `docs/goals/working-method.md`'s bar. Baselines are the
documented ones (`pytest`, `swift test`, the graph tests).

### Experiments (before any default is chosen)

| | Question | How | Cost |
|---|---|---|---|
| EX-1 | Does a plan stop after partial Stage 1 fail the cycle and lose the work? | The fake CLI in `test_claude_fake_cli.py`: throttle after k of n calls, run the cycle. Expected by code read: Stage 2 raises, no write | none |
| EX-2 | Do 1, 3, 6, 10 workers help, and what breaks? How far does a reserve overshoot? | The **demo bank** (synthetic), **each plan (Claude and ChatGPT both)**, each N: episodes per minute, 429 and `refresh_token_reused` counts, RSS per child, window movement, and how far past the reserve line a run went before it stopped starting reads | a few percent of a window, run by the owner |
| EX-3 | Is a smaller model's extraction good enough? | Same 30 demo-bank episodes on main and small models: entity-name overlap, claim count and type mix, evidence-locate rate (the `reasoning` fallback rate), JSON failure rate; the owner reviews ten diffs. Thresholds are the owner's to set | a few percent of a window |
| EX-4 | What is a batch's fixed overhead? | Time Stage 4, Stage 5, index sync and the tail at batch sizes 10, 25, 50, 100 on a synthetic bank of about 2,000 pages; compare with `fix/sleep-inbox-and-indexes` merged and not | none |
| EX-5 | How many Stage 2 pairs per name, and what does prefetch waste? | Count pairs on the demo bank; calls saved versus speculative calls at K = 4, 8, 16 | none |

### SL-1: an honest bar, and nothing paid for is lost

Backend: `sleep_journal.py` with the accept protocol and the episode-to-keys index (4.3); the seam
lookup and the pending write in `providers.py`, gated on a Sleep scope; an `accept` call in each stage
that validates (Stage 1 parse, Stage 2 decision, Stage 3 synthesis, Stage 4 parse); `extract()` returning
one outcome per episode with a reason class, and the empty-answer fix (`EngineProtocolError`, not
`EngineUnavailable`); the per-call model carried from the seam onto the extracted result and preferred by
`claim_reconciler._stamp_new` (4.3); per-stage counters and `run` on `/sleep/status` and the SSE event;
`done` and `failed` split; the pause on a plan stop (F1); `resumable` from `run.json` plus the index at
startup; pause replaces cancel when a journal exists; fix the Stage 3 comment.
App: the strip's per-stage fills and caption line, the neutral fill grammar, the two-tone bar for a
single batch, the new sentence rungs (running, pausing, paused, restart), Pause and Continue (Continue
here is only for a single paused batch and calls the trigger's no-body path; the drain's Continue arrives
with SL-2), the "Saved reading" row.

Acceptance:
- `test_sleep_journal.py`: an identical call replays with zero runner invocations and zero `llm_call`
  rows, counted as `journal_hits`; a changed prompt is a miss; purge on commit, at 7 days, at 50 MB;
  files 0600 in a 0700 directory; **a non-Sleep scope (Ask, link enrichment, the dedup sweep) never reads
  or writes the journal**.
- `test_journal_accept_protocol.py`: **the first answer is malformed, the retry must reach the runner**
  (Stage 1), and the stored bad answer is never replayed; the same for a Stage 2 unparseable reply (the
  resulting `unsure` is not accepted, so a Continue re-asks instead of replaying an `unsure` that opens
  a clarification each time) and an empty Stage 3 synthesis; a `pending` row does not survive a commit
  or a restart.
- `test_journal_episode_index.py`: one episode with N chunks is `read` only when all N keys are accepted;
  a rewritten episode reads as `waiting`; after a restart `resumable` and `GET /sleep/episodes` report
  the same `read` counts.
- `test_plan_stop_keeps_stage1.py` (EX-1 as a test): throttle after k of n calls, the cycle ends
  `paused`, the bank is untouched, a second cycle replays k answers for free and finishes.
- `test_restart_resumes.py`: kill after Stage 1, new process, `resumable` is reported, Continue files.
- `test_authors_across_resume.py`: a half-and-half batch's trailer **and each claim's `authored_by`** name
  the model that wrote that claim (the small model's Stage 1 claims are not signed with the main model).
- `test_extract_outcomes.py`: every exception class in 4.4's table maps to its reason class; an empty
  answer from a signed-in engine is content-class, not `signed_out`.
- `test_progress_monotonic.py`: drain-level `done` never decreases; failures never inflate `done`.
- Swift `SleepProgressModelTests` (fixtures from the demo bank's real wire, as `projects-demo.json`
  does), `StageStripStateTests` (Read, Sort, Decide fill; Notice, File do not), `SentenceLadderTests` for
  every row in 4.6 I within 40 and 80, and `SleepNumbersLintTests` run over the new strings (through
  `Copy`, with the noun list extended only if a new `%` string remains).

### SL-2: the drain

Backend: `sleep_run.py`; `only_ids`, `skip_tail`, `skip_links`, `decay` on the cycle, with `decay: bool`
added to `conflict_resolver.resolve_and_prune` and to the Stage 5.56 reconcile so **both** decay engines
(entity and claim) can be switched off per batch (4.4); the drain hold and `sleep_cycle.is_active()`
replacing the direct `status == "running"` reads at every gate (4.2); the fixed-bank `Settings` and the 409
on `POST /banks/{name}/activate` while a hold is live; the frozen list; the failure mapping and the three
attempt cap; the `no_progress` pause; the reserve for both plans and both Claude windows; `trip_breaker`
keeps `resets_at`; shared decay-inbox budget (rebases on the in-flight `DecayBudget`); auto-continue (if
Q1 is yes; at most two continuations, never across a weekly pause); `GET|PUT /sleep/plan`; the trigger
body; `POST /sleep/run/continue`, `run/end`, `DELETE /sleep/journal`; the body-aware demo check in the
trigger handler.
App: the "Read everything" sheet, `RunProgress` (the drain bar and line), paused and restart states,
Settings → Sleep "Reading", the awake assertion (if Q5 is yes), the drain and parked rows in Details, the
bank switcher showing the server's 409 sentence.

Acceptance:
- `test_drain_frozen_list.py`: arrivals during a drain never join it; a rewritten conversation is read
  again once.
- `test_drain_pins_bank.py`: **a switch between batches and a switch in the middle of Stage 1** (the
  latter through `POST /banks/{name}/activate`, which must answer 409 while the hold is live, and through
  a direct settings change, which the fixed-bank `Settings` must ignore) write nothing to the other bank;
  a switch while paused is allowed and Continue refuses with `bank_switched` (a regression net for the
  split-brain class).
- `test_drain_decay_once.py`: 48 batches charge decay once, at the end, from **both** engines
  (`resolve_and_prune` and `_decay_claims`), and open at most one `DecayBudget`'s worth of questions; the
  tail runs once; the seeded owner page never decays.
- `test_drain_skips.py`: a batch runs no 5.57 link read, no tail step and no decay, and does run the
  reconcile (decay off) and the question refresh.
- `test_drain_pauses.py`: a Claude 5-hour stop, a Claude weekly reserve (when reported), a weekly
  rejection, an overage refusal, a ChatGPT limit and the reserve each pause with the vendor's reset;
  `waiting_reset` only within 36 hours, only if armed, at most twice, never across a weekly pause; a
  scheduled cycle can never arm it.
- `test_content_vs_engine_failure.py`: a throttle, exhaustion or sign-out never parks a conversation; two
  empty answers do; a conversation that keeps failing is parked at the third attempt and the drain
  terminates; two zero-progress batches pause with `no_progress`.
- `test_status_stays_running_across_batches.py` (V5-14): between batches `status` stays `running`,
  **the scheduler's two sites and `POST /sleep/trigger` see the run as active** (a scheduled cycle and a
  user trigger do not start mid-drain), and each 409-guarded writer (memory, maintenance, backlog, banks,
  local sources, projects, entities, paper metadata, remote runtime) still answers 409; on a pause the
  hold is released and they open again.
- `test_trigger_contract.py` (V5-15): a no-body trigger is one batch from every door, with a drain paused
  or not; only the sheet's body starts a run; only `POST /sleep/run/continue` continues one; a wrong
  `runId` is 404.
- `test_demo_capture_routes.py` extended: `/sleep/trigger` no body allowed, a drain body 409,
  `/sleep/run/continue` 409.
- Swift `ReadAllSheetModelTests` (counts, batches, no percentage string on the sheet, the not-reported
  line only when `reserveEnforceable` is false), `RunProgressTests`, `DrainSentenceTests`,
  `SettingsSleepReadingTests`, `SleepDoorsTests` (no door but the sheet starts or continues a run), a UI
  check of both themes and 0.8×, 1.0×, 1.4×.

### SL-3: parallel reading (opt-in)

Backend: `workers` and `smallModel` in the plan and the trigger; Stage 1 chunk gather; Stage 2 prefetch
with K; Stage 3 gather; per-stage model routing; the Sleep-scoped `Settings` copy; the ceiling of 10.
App: the "Read faster" disclosure, the engine menu rows, the button label.

Gate: EX-2 (both plans, including reserve overshoot), EX-3 and EX-5 recorded; SL-1's authorship stamp
shipped (so the trade-off copy is true); and the owner's answers to Q2 and Q3. The ceiling of 10 and
the offer of 6 or 10 workers on any plan stay closed until EX-2 has measured them.

Acceptance:
- `test_stage2_prefetch_parity.py`: with a stub judge, `resolve()` returns the **identical** `changes`
  and edges with prefetch on (K = 1, 8, unbounded) and off, over a randomised bank.
- `test_stage3_gather_order.py`: `conflict_nudge` entries keep their original order.
- `test_workers_ceiling.py`: never more than `workers` live children; never more than 10.
- `test_parallel_never_scheduled.py`: a scheduled cycle ignores `workers` and `smallModel`.
- `test_small_model_routing.py`: Read and Sort use the small model; Decide and Notice do not.
- `test_prefetch_journal_accept.py`: a prefetched judge answer is journaled only when it is a valid
  decision, so a speculative call that returned garbage is re-asked, never replayed.
- Swift `ReadFasterDisclosureTests` (trade-off copy present, the "records the model" line absent until
  the stamp ships, "6" and "10" not offered on a plan until gated, the vendor's description shown, nothing
  preselected on ChatGPT).

### SL-4: what it cost, folded in

Backend: the drain's usage cannot be joined through `sleep_run` alone. `cycle_usage.py:20` records that
an aborted cycle writes **no** `sleep_run`, and under this design a paused batch is an aborted one, so its
paid `llm_call` rows (tagged with the old `cycle_id`) would have no `sleep_run` to join; the resumed
attempt gets a fresh `cycle_id`, its journal hits emit no `llm_call`, and `cycle_usage.discard(cycle_id)`
in `run()`'s `finally` would drop the paused attempt's plan windows. Drain usage would silently
under-count, which breaks ruling 12's "unknown is never zero". So:
- `llm_call` rows are tagged with `refs.drain_id` through the same ambient scope that carries `cycle_id`,
  and the drain aggregate sums `llm_call` rows **by `drain_id`**.
- A paused batch writes a `sleep_run` (or a `sleep_pause` event) carrying its `drain_id` and its plan
  windows; `discard` keeps windows for a drain-tagged cycle, and the controller holds the drain's
  first-seen `before` across attempts in `run.json`.
- `batch` and `drain_id` are added to `sleep_run` refs (ids and numbers only).
App: the drain row in Last cycle, the "Reading all" group in Past nights, the model shown per group, and,
only once a completed batch exists on each configuration, one line "Per 25 conversations: this setup
moved your window X%; the previous moved it Y%" in the ruling-12 grammar.

Acceptance: `test_drain_usage_aggregate.py` (windows crossed, "tokens not reported" on ChatGPT, unknown
never zero, pre-instrumentation batches read "Usage not recorded", **and a paused-then-resumed drain:
the paused attempt's paid calls and windows are counted once and the resumed attempt's journal hits add
none**); `CycleUsageTextTests` for the new lines. `PriceLintTests` does not exist (section 5, rail 3): SL-4
**writes it** as new work (DR-59: cost strings only in `CycleUsageText`, `EngineQuickMenu`'s captions and
Details), or drops the claim; it is not described as already passing.

### SL-5: later, only with evidence

Read-ahead (batch k+1's Stage 1 while k files), the per-stage model map exposed in Settings, video and
browsing runs on the same machinery, and a re-read with a stronger model (G104).

**Order and dependencies.** SL-1 then SL-2 are strictly ordered; SL-3 waits on its experiments and the
owner; SL-4 follows SL-2. Three local branches edit files this spec touches and none had merged when this
was written: `fix/sleep-inbox-and-indexes` (`sleep_cycle.py`, `config.py`, the decay inbox cap, the index
sync), `fix/first-run-extraction-owner` (decay watermark on import, the owner page), and
`fix/saved-links-collision-and-throughput`. SL-1 should start after the first of those lands, because
both rewrite `_run_stages`. `fix/first-run-extraction-owner` also carries the owner-page seed 4.8 relies
on.

---

## 8. Questions for the owner (only real decisions)

**Q1. May a run you started continue itself after a plan reset?** *Decided 2026-09-30: yes, as an opt-in
switch in Reading options, off by default, recorded as TODO ruling 15 with the bounds below.* This amends ruling 4 for that one
case. *Recommendation: yes, as a per-run checkbox, off by default, with the reset time shown, at most
two continuations, expiring after 36 hours, never available to a scheduled cycle and never crossing a
weekly pause.* Without it, a paused drain waits for you to open the app. Note that on a weekly-only
ChatGPT window the wait can be days, which is why 36 hours is the cap.

**Q1b. Is a first-run drain on a consumer plan acceptable at all?** *Decided 2026-09-30 by building it: Consolidate reads everything (ruling 13) on the plan the person chose for a run they start; no copy advises on providers.* A drain is the largest volume of plan
calls Cicada would make (on the order of 12,000 to 21,000 judge calls for 1,187 conversations at one
worker, arithmetic on an old figure), and the repo's own open question is whether even a nightly personal
batch is "ordinary, individual usage". *Recommendation: allow it, person-started and reserve-guarded as
designed, show the calls made, and have the sheet say an API key or OpenRouter may suit a first read
better; recommend an API key by name for the first drain if the vendors' terms, once read, say scripted
volume belongs there.* Vendor terms have not been re-read for this spec.

**Q2. When may "6" and "10" workers be chosen on a plan?** *Not built (owner, 2026-09-30): "Read faster" is out of the sheet; SL-3 stays open.* *Recommendation: only after EX-2, run on
**both** plans, shows the engine tolerates it (no `refresh_token_reused`, no rising 429s) **and** measures
how far a reserve overshoots at that fan-out, and you sign off; until then the sheet offers 1 and 3 and
says why.* The reserve cannot be guaranteed on either plan (a window is read after a call returns, with up
to `workers` calls in flight), so a larger fan-out is a larger overshoot. This is the terms-of-service,
token-race and overshoot question, and it is the gate for SL-3.

**Q3. Which stages use the small model, and may the roster suggest one?** *Not built with Q2 (2026-09-30).* *Recommendation: Read and Sort
only; Decide (the prose) and Notice stay on the main model; on ChatGPT show the vendor's descriptions
and preselect nothing, suggesting at most one when its description says "fast" or "affordable".* Widen
after EX-3. This also amends R-A8/P15 as recorded in V5-3.

**Q4. Reserve defaults.** Claude keeps today's 10% for the 5-hour window (`stop_utilization` 0.9) and
gains a run-level 10% on the weekly window when the stream reports it (today the weekly window is only
checked on rejection, so without this a chained drain would run to the weekly limit). *Recommendation:
25% for a weekly-only ChatGPT window*, because the same budget is your coding budget and there is no
per-call signal to stop precisely. Your number. The figure is set only in the engine menu (V5-16).

**Q5. Keep the Mac awake while a run you started is going?** *Recommendation: yes, released on pause,
and off on battery unless you choose otherwise.* It is a system side effect, so it is asked once in
Settings → Sleep rather than assumed.

**Q6. Should the first drain of a bank always start with one batch and then ask?** *Replaced 2026-09-30: the first save is a moment, not a stop — the run carries on and the sentence says "Filed the first 25. Your page has N beliefs so far." (`ownerPage`, `firstRun`).* *Recommendation was: yes.*
It makes the first result visible before the window is committed (including your own page filling, 4.8),
and it is the cheapest check on a smaller model.

**Q7. May the Sleep page gain run controls beside Consolidate?** *Superseded by ruling 13 (Consolidate is the drain; V5-15 reversed) and settled 2026-09-30: the page gains Pause / Continue / End this run and a parked row's Retry beside its one trigger — a G125 R10 amendment recorded in TODO.* G125 R10 keeps one trigger on this page
and its record is two narrow amendments (Home and the intake card's *Read now*). This design adds *Read
all …* (opens a sheet), the sheet's *Start*, *Continue* on a paused run and a parked row's *Retry*.
*Recommendation: yes, narrowly. Consolidate stays the only one-batch trigger, a no-body trigger is one
batch from every door, and a run starts or continues only from this page (V5-15).* The alternative, with
no amendment, is to fold "Read all" into the engine menu and Consolidate's own popover.

**Q8. Should plan figures widen beyond Details and the engine menu?** Ruling 12 says "nowhere else yet".
This revision keeps to it: the sheet and the sentence carry no percentage and the reserve is set in the
engine menu (V5-16). *Recommendation: keep it that way.* If you would rather see "Pauses at 80% used" on
the sheet and "20% is kept for you" in the sentence, that is a dated amendment to ruling 12, DR-59 and the
CLAUDE.md paragraph, which this spec would then carry.

---

## 9. Risks

| # | Risk | Likelihood, impact | Mitigation |
|---|---|---|---|
| R-1 | Concurrent `codex exec` or `claude -p` children race on the shared auth home (`refresh_token_reused`) | Unknown, high | EX-2; refresh the token once before fan-out (the app-server read does); stagger starts; a signed-out result pauses, never retries in a loop; Q2 gate |
| R-2 | A smaller model quietly lowers the graph's quality | Medium, high | Opt-in; first batch first; per-belief authorship; the model shown per group in Past nights; EX-3; re-read stays possible (G104) |
| R-3 | The drain spends more of the person's plan than they meant | Medium, high | A run-level reserve on every window a plan reports (Claude's weekly included, when reported), stops starting reads at `100 - reserve`, overshoot bounded by `workers` and unmeasured (EX-2); auto-continue capped at two and never across a weekly pause; person-started only; calls made shown; ruling 12 after |
| R-4 | Prefetch buys judge calls the sequential loop would not have | Certain, low to medium | K cap; outcome independent of K (parity test); EX-5; never labelled "cheaper" |
| R-5 | The journal leaks extracted content | Low, high | Machine-local, 0600, never logged or committed, purge rules, Forget action, keyed by hash |
| R-6 | A first-run drain floods the Inbox | High, medium | One decay-inbox budget per drain; questions ordered, not dropped; Home's "Needs you" already shows the top three. The exact cap is a product call outside this spec |
| R-7 | Merge conflicts with three local branches editing `sleep_cycle.py`, `config.py` | High, low | Sequence SL-1 after `fix/sleep-inbox-and-indexes`; keep the cycle's change small (`only_ids`, `skip_tail`, `decay`, the seam memo) |
| R-8 | A bank switch mid-drain touches the wrong bank | Low, severe | V5-9: fixed-bank `Settings` for the run, `activate` refused while the hold is live, a between-batch check; the mid-Stage-1 test; the journal is keyed by bank |
| R-9 | The Mac sleeps mid-drain and calls fail | High, low | A timeout is content-class by the exception mapping, so two on one conversation park it, with the reason in words and a one-click Retry; the three-attempt cap keeps the drain finite; the awake assertion (Q5) reduces it |
| R-10 | `to_thread` pool starvation with 10 workers plus index rebuilds | Low, medium | Ceiling of 10; EX-2 watches event-loop latency |
| R-11 | SSE event rate with per-name ticks | Low, low | One event a second by construction (`POLL_SECONDS = 1`); counters are in the change key |
| R-12 | The neutral fill grammar reads as "less progress" than the accent | Low, low | Two-tone plus words; checked light and dark (DR-71); the strip already needs the DR-5 sweep |
| R-13 | Ruling 3 stretch is contested | Low, low | Stated in V5-2 and 4.3 rather than buried |
| R-14 | Refusing `POST /banks/{name}/activate` while a drain reads is a behaviour change for a route that is deliberately unguarded during a cycle | Medium, low | Only while a drain's hold is live (running, pausing), never for a plain cycle or a paused run; the app shows the server's sentence; Q-free because it prevents a data-integrity bug, but flagged here for review |
| R-15 | A stream that does not report the weekly window makes its reserve unenforceable | Medium, medium | `reserveEnforceable` on `GET /sleep/plan`; the sheet says so instead of promising; auto-continue never crosses a weekly pause |
| R-16 | A stage forgets to call `journal.accept`, so its answers never replay | Medium, low | Fails safe (a miss re-asks and pays again, never replays a bad answer); `test_journal_accept_protocol.py` covers every stage that validates, and a grep gate names any stage that reads the seam without an accept |

---

## 10. Appendix: the numbers used above, and where they came from

- Ledger read: `~/.cicada/telemetry/events-2026-09.jsonl`, `kind == llm_call`. Extraction rows:
  durations 31,514 / 31,922 / 33,995 / 35,804 / 30,363 ms; input tokens 3,784 to 4,591; output tokens
  3,852 to 4,458. Disambiguation: 32 rows, median 6.6 s. `sleep_run` rows: none.
- ChatGPT plan read: `codex app-server` through `codex_app_server._stdio_transport`, `model/list` and
  `account/rateLimits/read`, 2026-09-29, read-only, no quota. Seven visible models; one primary window
  of 10,080 minutes; priority tier described as "increased usage".
- Stage 2 volume: `2026-09-01-agent-engine-design.md` section 7 (200 to 350 calls per 20 episodes, mean
  7.0 candidates per name, p99 84). The 22 to 38 minute figure in F2 is 200 and 350 times 6.6 s, and is
  arithmetic, not a measurement.
- Code facts: `sleep_cycle.py` (1160-1182, 1262, 1342, 1361-1379, 1505-1523), `entity_extractor.py`
  (131, 311, 372), `entity_resolver.py` (183-330, 835, 846-929), `conflict_resolver.py` (72-148,
  211-220), `providers.py` (158-194, 460-550), `agent_engine.py` (510-601), `plan_limits.py`,
  `codex_engine.py` (102-105, 300-333), `routers/sync.py` (55-100), `Views/Sleep/*`. Added in revision 2:
`claim_reconciler.py` (128-137, 655), `sleep_cycle.py` (222-244, 1037-1135), `sleep_scheduler.py`
(173, 188), `config.py` (39-41), `routers/banks.py` (183-185), `entity_extractor.py` (222-270, 307-451),
`entity_resolver.py` (812-832), `agent_engine.py` (480-490), `engine_errors.py` (the class list),
`cycle_usage.py` (:20), `plan_limits.py` (50-88), `demo_guard.py` and `test_demo_capture_routes.py`,
`APIClient.swift` (`triggerSleep`), `AutoRecallTests.swift` (167), `SleepNumbersLintTests.swift` (35),
and commit `1d00d1d` on `fix/first-run-extraction-owner`.

---

## 11. Decided and built (2026-09-30)

The owner approved the boards ("I like the sleep agent v5 designs would you be able to apply them?") with four
binding decisions, applied on top of the merged drain (ruling 13):

1. **Scheduled cycles also read everything waiting** — TODO ruling 16. Ruling 4 is untouched: they still never use a plan;
   an unattended run on a key spends with no limit Cicada sets, and the engine menu and Details say so in words.
2. **Continue after a plan reset** is an opt-in switch in Reading options, off by default — TODO ruling 15 (a narrow
   amendment to ruling 4: only a run the person started, only after its window resets; bounds in the ruling).
3. **"Read faster" is not built** — the sheet ships without it (no "At once", no "Reading model", no trade-off list).
   SL-3 (parallel reading, the small-model map, EX-1…EX-5) stays open and needs the owner's go. The engine chip reads the
   person's own engine and model.
4. **"Leave room in my plan"** — off by default, a percentage of the plan window set in the engine menu, a *soft stop*
   (the batch keeps what it read); a line, not a guarantee.

**Backend built** (`api/services/`: `sleep_run_prefs`, `sleep_parked`, `sleep_paused`, `sleep_runs`, `sleep_reserve`,
`sleep_autocontinue`, `sleep_progress`, `sleep_run_detail`, `sleep_local`; edits to `sleep_cycle`, `sleep_drain`,
`sleep_scheduler`, `cycle_usage`, `entity_extractor`, `agent_engine`, `providers`): `GET/PUT /sleep/run-options`;
`POST /sleep/trigger {"continue": true}`, `POST /sleep/run/end`, `POST /sleep/parked/retry`; `GET /sleep/queue`;
`GET /sleep/runs/{id}`; `drain` and `paused` on `GET /sleep/status` and the SSE `sleep` event; `run` / `drainId` /
`batch` / `batches` on history rows; `billing` on the engine previews and `reserve` on `GET /sleep/engine`. The wire is
pinned for the app by `app/CicadaApp/Tests/fixtures/sleep-status-drain.json` (regenerated by
`test_sleep_status_app_fixture.py`).

**Deviations from the design, and why.**
- The board's *Saved reading* and "read and kept" wording are **not** built: there is no journal (SL-1), so a Pause or a hard
  plan rejection mid-batch still discards that batch. The Pause tail must say what is true — what is filed stays filed and
  the part in progress is read again. The reserve avoids the common case because it keeps the batch.
- "Paused. You switched memory." is unreachable (a drain refuses a bank switch) and kept as a defensive rung only.
- Batch size tops out at **50** (a commit records at most 50 sessions; the board's 100 is not offered).
- Past nights groups by run from a machine-local per-run summary (`$CICADA_HOME/sleep/<bank>/runs.json`), not from the
  telemetry ledger alone, so grouping survives `CICADA_TELEMETRY=off`; cost and per-call figures still need the ledger.
- The board's "and 405 more" link is omitted: no surface lists a run's pages.
- Provider-neutral copy: the boards' strings that name a provider or model as the one doing a job ("Haiku · 3 at once",
  "your Claude plan", "Reads and sorts. Deciding stays on Sonnet.") are not copied; the app words billing from
  `preview.*.billing` and shows the engine and model the person chose.

**App half — not built.** Wire decode over the pinned fixtures, the sentence ladder (paused, restart, first save, parked),
the strip and bar, the Reading options sheet, the engine menu's *Keep plan free* row, Details, Past nights and the run
detail, the doors (one choke point: a paused run routes every door to the Sleep page), and the lints
(`SleepProviderNeutralLintTests`, `PriceLintTests`). Copy that the boards get wrong is listed in the plan's section 8; the
rule is the owner's: describe the step, never name a provider outside the person's own current choice.
