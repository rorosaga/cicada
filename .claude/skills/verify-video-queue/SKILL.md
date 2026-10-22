---
name: verify-video-queue
description: Model-checks the G162 video queue's lease lifecycle (claim, lease, refresh, release, the record_watch queue credit, lapse, failed-row expiry, orphan drop) in TLA+ with TLC. Use it for any change to api/services/video_queue.py, to video_state.satisfies / newer_than / saved_videos, to mcp_tools.video_claim / record_watch / _credit_video_queue / ToolContext.pages_held, or to the queue routes in api/routers/videos.py. Also use it before you claim the queue never leases a video twice or never loses one.
---

# Verify the video queue

The video queue (`$CICADA_HOME/video_queue/<bank>.json`, G162) is written by the backend and by every stdio MCP
server at once. `VideoQueue.tla` models one video's row through every order of claim, refresh, release, record,
re-queue, Sleep holding the pages, time passing, a page being saved or hidden, and a queue credit that never
runs. TLC checks every interleaving within the bounds below. A test checks the orders someone thought of.

## Does my change touch it?

```sh
python3 .claude/skills/verify-video-queue/coverage.py
```

It fingerprints every covered function and constant (`coverage.lock`). Exit 3 lists what changed since the
sync commit. `run.sh` runs this check first and stops with exit 3 on drift. `ALLOW_DRIFT=1` runs it anyway
while you bring the model in line.

## Run it

```sh
.claude/skills/verify-video-queue/run.sh            # the code, the open findings, the proposed fixes: ~45 s
.claude/skills/verify-video-queue/run.sh --breaks   # each passing property fails on a mirrored break: ~10 s
.claude/skills/verify-video-queue/run.sh --deep     # the two-video safety run: longer than 25 min
PYTHON=api/.venv/bin/python python3 .claude/skills/verify-video-queue/able_to_fail.py   # real-code breaks: ~45 s
```

`run.sh` needs Java 11 or newer (it tries `$JAVA`, then Homebrew's `openjdk@17`, then `java` on the PATH),
`curl` and `python3`. It downloads `tla2tools.jar` v1.7.4 from the official tlaplus GitHub release into
`~/.cache/cicada-tla/v1.7.4/` (override with `CICADA_TLA_TOOLS`). It refuses the jar unless its sha256 is
`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`. The release publishes no digest, so this
pin was recorded on first download. The jar is never in git. Output and one readable trace per violation
(`<check>.trace.txt`, from `trace.py`) land in `$OUT`, default `$TMPDIR/verify-video-queue`. Exit 0 means every
check ended as the `EXPECT_*` tables in `run.sh` say.

`able_to_fail.py` edits `api/services/video_queue.py` once per scratch break. For each one it shows a real test
failing, shows the mirrored `break-*` check failing, then restores the file byte for byte and shows the test
passing again.

## The properties

| | Property (TLA+ name) | In one sentence | Harm if broken | Today |
|---|---|---|---|---|
| P1 | `NoDoubleClaim` | A lease that has not lapsed never passes to another session in one step. | Two agents watch the same video and both records land. | verified |
| P2 | `NoLostRow` | A row leaves the queue only by Remove, a satisfying record, failed-row expiry, or its page going away. | The person's request vanishes silently. | **F2** |
| P3 | `ReleaseOnlyByHolder` | Only the leaseholder hands a leased video back. | One agent fails another's work in progress. | **F1** |
| P4 | `RecordByOtherCorruptsNothing` | A record by a session that does not hold the lease cannot end it without a record newer than the request. | A working agent loses its lease unannounced. | **F3** (verified with F3's fix) |
| P5 | `DoneIsSupported` | A row closes as done only on a record newer than its request, or on its leaseholder's own record. | A request is closed by a record that predates it. | **F3** |
| P6 | `Idempotent` | Releasing, or recording with the same basis, twice leaves the queue as once did. | A retried tool call changes the outcome. | verified |
| P7 | `NoBurnWhileHeld` | A lapse costs an attempt only while Sleep is not holding the pages. | A long drain fails videos nobody had a chance at (spec P5). | verified |
| P8 | `NoBurnWhenSatisfied` | A lapse never costs an attempt when a satisfying record already exists. | A watched video is re-queued or failed. | verified |
| P9 | `LeaseEnds` | Every lease ends in every reader's view once its session goes quiet. | A video stays "picked up" forever. | verified; **F4** while the session stays active |
| P10 | `FailedEnds` | Every failed row eventually ages out or is tried again. | A failed row never leaves the list. | verified |
| P11 | `FailedReturnsOnlyByPerson` | A failed video returns to the queue only when the person asks (Try again, or queueing it again). | An agent walks back into the login wall or dead link another agent reported. | verified |
| P12 | `NoLeaseTakenAway` | A live lease ends only by a release, a record's credit, the person's Remove, or its page going away. | Queueing a video again, or any other write, takes it from the agent working on it. | verified |

"Verified" means TLC explored every state within the bounds and found no violation. The breaks below show each
of these can fail.

## Open findings

Every finding has a test in `api/tests/test_video_queue_formal.py` that drives the real code in the
counterexample's order and fails today. The tests are marked `xfail(strict=True)` with the finding id. Each fix
is mirrored behind the model's `Fixes` constant, and `fixed-safety` and `fixed-churn` pass with all three.

- **F1, release ignores the session.** `s1` claims `k1`. `s2` calls `cicada_video_claim(release=[k1])`.
  `release` finds the row `claimed` (`video_queue.py:661`) and fails it without comparing sessions. The tool
  says "hands videos back that you could not do" (`mcp/server.py:518`), and the explore queue answers
  `not_yours` (`explore_queue.py:816`). Proposal: compare `row["session"]` and answer `not_yours`.
- **F2, a stale saved snapshot drops a fresh row.** A writer reads the saved videos before its lock
  (`mcp_tools.py:1204`; `video_queue.py:514/529/549/582/623/647/682`). A video is saved and queued meanwhile.
  The writer's `_open` (:482) drops it as an orphan. Proposal: decide orphans from a saved set read under the
  lock.
- **F3, a record older than the request closes it.** `record_watch` writes its episode (`mcp_tools.py:613`).
  The person queues the video, and another session claims it. Then the credit runs (`:629` to `complete`), and
  a stated basis closes the row (`video_queue.py:692`) without the newer-than-`requested_at` rule the lapse
  sweep applies (:322). Proposal: pass the record's time to `complete` and apply `video_state.newer_than`.
- **F4, an active session keeps its leases (by design).** Every call refreshes the session's unlapsed leases
  (`_refresh` :602). A forgotten lease lives as long as the session keeps calling. This is the owner's call:
  keep it, or cap refreshes at an age from `claimed_at`.

## Reading a result

`run.sh` prints `check | expected | got`. On anything unexpected, read `$OUT/<check>.trace.txt`. Each step
names the call and the code line it models.

- **A violation nobody expected.** Replay the steps against the code, one line at a time. If some step is
  something the code cannot do (a guard the model lacks, a field the code resets, a call the code does not
  make), it is a **modeling error**. Fix the operator in `VideoQueue.tla` to match the code, cite the line,
  and rerun. If every step is something the code does, it is a **real bug**. Write a test that drives the real
  functions in that order (see `test_video_queue_formal.py`), mark it `xfail(strict=True)` with a new finding
  id, add a `models/F<n>-*.cfg` expected to violate, and add it to `EXPECT_DEFAULT`. Never weaken a property or
  remove a behaviour from the model to get a pass.
- **A finding's check now passes.** Either the code fixed it, or the model drifted. Confirm against the code.
  If the fix is real, mirror it (use the `Fixes` constant or change the operator), flip the expectation to
  `pass`, and remove the test's `xfail` marker.
- **A passing check now fails after an intended change.** Decide whether the property still states a promise
  the code makes. Change a property only with an owner's ruling recorded in `docs/goals/TODO.md`.
- **`error` in the got column.** TLC could not parse or evaluate the spec. The log names the line.

## Keeping it in step

**Sync commit: `0fa3f239b13b42f4911a088d4fa7feca22ce4890`** (`dev`, 2026-10-22). At that commit the model
describes these functions:

| Code | Model |
|---|---|
| `video_queue.py` `_locked` :229, `_write` :243, `_read_file` :194 | one locked step per write call |
| `_lapsed` :276, `LEASE_MINUTES` :53 | `Lapsed`, `LeaseTicks`, `Tick` |
| `_failed_expiry` :271, `EXPIRE_FAILED_DAYS` :60 | `FailExpired`, `FailTicks` |
| `_settle` :294, `MAX_ATTEMPTS` :54 | `SettleRow`, `Settle` |
| `_drop_orphans` :352, `_open` :474, `_saved` :459 | `Open`, `Orphans`, the `snap` of each Begin |
| `_refresh` :602 | `Refresh` |
| `claim` :613, `CLAIM_PAGE`, `DEFAULT_CLAIM` | `ClaimBegin`, `ClaimLocked` (`Takes`: any non-empty subset) |
| `release` :641, `clean_code` | `ReleaseBegin`, `ReleaseLocked`, `ReleaseFn` |
| `complete` :674 | `CompleteLocked`, `CompleteFn`, `Done` |
| `put` :509, `handoff` :562, `_upsert` :493, `remove` :526, `retry` :545, `_reset` :487 | `PutBegin`, `RemoveBegin`, `RetryBegin`, `PersonLocked` |
| `view` :368 | the settled view each locked step starts from; `EffClaimed` |
| `video_state.py` `satisfies` :242, `newer_than` :232, `clean_basis` :71 | `SatisfiesNew`, `recs` (facts newer than the request), `FactsOf` |
| `video_state.saved_videos` :148 | `saved`, `SaveVideo`, `HideVideo` |
| `mcp_tools.py` `video_claim` :1190 (snapshot :1204) | `ClaimBegin`, `ReleaseBegin` |
| `mcp_tools.py` `record_watch` :565 (episode :613, credit :629), `_credit_video_queue` :1098 | `RecordEpisode`, `CompleteLocked`, `DropCredit` |
| `mcp_tools.py` `ToolContext.pages_held` :209 | `holding`, `SleepStart`, `SleepEnd` |
| `api/routers/videos.py` `_view` :69, `_put` :136, `delete_video_queue` :150, `_retry` :155, `_handoff` :179 | `PutBegin`, `RemoveBegin`, `RetryBegin`, `PersonLocked` |

When a covered function changes on purpose:

1. Run `coverage.py` to list what moved, and read each change.
2. Edit the matching operator in `VideoQueue.tla`, and update its line reference here and in `statechart.md`.
3. If a scratch break's text moved, update `BREAKS` in `able_to_fail.py`.
4. Run `ALLOW_DRIFT=1 run.sh`, `run.sh --breaks` and `able_to_fail.py`. Read every unexpected result as above.
5. Only after the model describes the new code: run `python3 coverage.py --update`, and move the sync commit
   above to the commit you checked.

## Scope and bounds

- **Bounds.** One video (`Keys = {k1}`) and two sessions plus the person for safety, explored to the end. One video for liveness,
  with two calls per session (`CallBudget = 2`) in `code-liveness`. Two videos and one session for the orphan
  checks (`F2`, `fixed-churn`). Two videos and two sessions in `--deep`, which has not been run to the end. On
  2026-10-22 it explored 18,960,075 distinct states to depth 26 in 22 minutes with no violation, and was
  stopped with 4.1 million states still queued. A lease lasts 2 ticks, a failed row 1
  tick, and three lapses fail a row, as in the code. Symmetry over videos and sessions applies to safety only.
- **Why one video is enough.** Every property is about one video, and every step changes a row as a function of
  that row alone, with two exceptions. A call that refreshes the caller's other leases does, on one video, what
  a claim that finds nothing does. The orphan drop needs a non-empty snapshot that lacks the key, so its checks
  keep two videos. `--deep` checks the same safety properties on two videos, as a cross-check of this argument.
- **The reduction.** When the saved set cannot change (or with fix F2), the snapshot step before each lock
  reads a constant and writes only its caller's state. The model runs its locked step next, with only time and
  Sleep in between. The gap between a record and its queue credit is always kept open.
- **Abstractions.** Time is relative ticks. A record keeps only the facts newer than its row's request, which
  is all `satisfies` reads. A record in the same second as the request counts as newer in the code and is
  either before or after in the model. `claim` may take any non-empty subset of the claimable rows, a superset
  of oldest first. A hand-off is modeled as one `put` per video. All sessions have an id.
- **Left out.** Batches (`done`, expiry, the active batch), `MAX_ROWS`, the scrubbing and capping of reasons,
  the release codes (all one transition), `stamp`, `next_change_at`, ETags and the parse cache, `bank_slug`,
  the remote runtime's busy refusal, the demo-bank refusal, Sleep's admission internals (a flag here), clock
  skew between processes, and two person requests at once. Each locked step is atomic, so only the snapshot
  race matters there, and F2 covers it with one person.

## Files

`VideoQueue.tla` (the model), `models/*.cfg` (one check each), `run.sh`, `trace.py`, `coverage.py` and
`coverage.lock`, `able_to_fail.py`, and `statechart.md` (the statechart and every transition with its code line,
drawn before the model).
