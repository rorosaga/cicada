---
name: verify-video-queue
description: Model-checks the G162 video queue's lease lifecycle (claim, lease, refresh, release, the record_watch queue credit, lapse, failed-row expiry, orphan drop, and the session ids callers carry) in TLA+ with TLC. Use it for any change to api/services/video_queue.py, to video_state's satisfies / newer_than / saved_videos / watch_records, to mcp_tools' video_claim / record_watch / _credit_video_queue / pages_held, to watch_record's episode writer, to how a stdio, CLI or remote caller gets its session id, or to the queue routes in api/routers/videos.py. Also use it before you claim the queue never leases a video twice, never loses one, or that a fix for F1-F5 is complete.
---

# Verify the video queue

The video queue (`$CICADA_HOME/video_queue/<bank>.json`, G162) is written by the backend and by every stdio MCP
server at once. `VideoQueue.tla` models one video's row through every order of claim, refresh, release, record,
re-queue, Sleep holding the pages, time passing, a new wall-clock second, a page being saved or hidden, a process
restarting with a new session id, and a queue credit that never runs. TLC checks every interleaving within the
bounds below. The default run covers one video and two callers to the end. The two-video, two-caller run
(`deep-safety`) has never finished: see "Scope and bounds".

## Does my change touch it?

```sh
python3 .claude/skills/verify-video-queue/coverage.py
```

Exit 3 means one of three things moved since the sync commit, and it lists which:

- a covered definition (`coverage.lock` holds a sha256 per definition, decorators included; the reply builders
  `record_watch`, `video_claim` and `watch_record.record` are hashed with their sentences blanked, so rewording a
  reply does not count, but any change to a call, an argument, a condition or a short string key does);
- the set of places that name a queue writer (`video_queue.put`, `remove`, `retry`, `handoff`, `claim`,
  `release`, `complete`) under `api/`, `mcp/` and `plugins/`, outside tests. A new caller is an actor the model
  may lack;
- a citation. Every line citation in this skill is `<module>.<function>:<line>`, and coverage.py checks that the
  line falls inside that function. A line number with no qualified name in front of it is an error too.

`run.sh` runs this check first and stops with exit 3. `ALLOW_DRIFT=1` runs it anyway while you bring the model in
line.

## Run it

```sh
.claude/skills/verify-video-queue/run.sh            # code, findings, proposed fixes and every break: ~60 s
.claude/skills/verify-video-queue/run.sh --breaks   # only the breaks: ~15 s
.claude/skills/verify-video-queue/run.sh --deep     # restarting ids, fixes under page churn, two videos: see bounds
python3 .claude/skills/verify-video-queue/able_to_fail.py   # real-code breaks in a temporary copy: ~90 s
```

`run.sh` needs Java 11 or newer (it tries `$JAVA`, then Homebrew's `openjdk@17`, then `java` on the PATH), `curl`,
`python3` and `xargs`. It downloads `tla2tools.jar` v1.7.4 from the official tlaplus GitHub release into
`~/.cache/cicada-tla/v1.7.4/` (override with `CICADA_TLA_TOOLS`) through a per-run temporary file, and refuses the
jar unless its sha256 is `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`. The release publishes
no digest, so this pin was recorded on first download. The jar is never in git. It runs `JOBS=2` checks at once
with `WORKERS=2` TLC workers each. Logs and one readable trace per violation (`<check>.trace.txt`, from
`trace.py`) land in `$OUT`, default a fresh `mktemp -d` directory. Exit 0 means every check ended as its `EXPECT`
row in `run.sh` says, and every passing check explored at least the row's minimum number of distinct states, so a
model that silently lost an action fails as `TOO FEW STATES`.

`able_to_fail.py` copies `api/`, `mcp/`, `plugins/` and this skill into a temporary directory and never edits the
working tree (it hashes `video_queue.py` before and after). For each scratch break it shows a real test failing,
`coverage.py` exiting 3 with exactly the edited function listed, the mirrored `break-*` check failing, and the test
passing again once the file is restored. `PYTHON` names an interpreter with the backend's dependencies; the default
is `api/.venv/bin/python` here or in the main checkout of a worktree.

## The properties

Each is judged on what happened, with history the code does not keep: `holder` (who really holds each lease,
whatever the row's session field says) and each record's place against the request (written before or after it,
in its second or not). No property reads an operator a fix edits.

| | Property (TLA+ name) | In one sentence | Harm if broken | Code today | With the proposals |
|---|---|---|---|---|---|
| P1 | `NoDoubleClaim` | A lease that has not lapsed never passes to another caller in one step. | Two agents watch one video. | verified | verified |
| P2 | `NoLostRow` | A saved video's row leaves only when removed, aged out, or some record of it exists. | The person's request vanishes. | verified since ruling 34 (`code-churn`, `--deep`; was **F2**) | verified (`fixed-churn`, `--deep`) |
| P3 | `ReleaseOnlyByHolder` | Only the leaseholder hands a leased video back. | One agent fails another's work in progress. | verified since ruling 34 (was **F1**) | verified |
| P4 | `RecordByOtherCorruptsNothing` | A credit by a caller that does not hold the lease ends it only on a record written after the request. | A working agent loses its lease unannounced. | **F3** (accepted); F5 fixed by ruling 34 | verified |
| P5 | `DoneIsSupported` | A row closes as done only on a record written after its request, or on its leaseholder's own record. | A request is closed by a record that predates it. | **F3** (accepted) | verified, sub-second order included |
| P6 | `Idempotent` | Releasing, or recording with the same basis, twice leaves the queue as once did. | A retried tool call changes the outcome. | verified | verified |
| P7 | `NoBurnWhileHeld` | A lapse costs an attempt only while Sleep is not holding the pages. | A long drain fails videos nobody had a chance at. | verified | verified |
| P8 | `NoBurnWhenSatisfied` | A lapse never costs an attempt when a record written after the request satisfies it. | A watched video is re-queued or failed. | verified | verified |
| P9 | `LeaseEnds` | Every lease ends in every reader's view once its caller goes quiet. | A video stays "picked up" forever. | verified, and since ruling 34 also while the caller keeps calling (`code-lease-cap`; was **F4**) | unchanged |
| P10 | `FailedEnds` | Every failed row eventually ages out or is tried again. | A failed row never leaves the list. | verified | unchanged |
| P11 | `FailedReturnsOnlyByPerson` | A failed video returns to the queue only when the person asks. | An agent walks back into a login wall another agent reported. | verified | verified |
| P12 | `NoLeaseTakenAway` | A live lease ends only by a release, a record's credit, the person's Remove, or its page going away. | Queueing again, or any other write, takes a video from its agent. | verified | verified |
| P13 | `HolderCanRelease` | A caller can always hand back a live lease it holds. | An agent that cannot do a video must wait 45 minutes and burn an attempt. | verified (the lease token, F1) | verified with F1; **fails** with a session compare (`F1s-*`) |

"Verified" means TLC explored every state within the bounds and found no violation, for every id mode the row's
checks cover. The breaks below show each property can fail.

## Findings, and ruling 34

#399 left five findings with failing repros in `api/tests/test_video_queue_formal.py`. Ruling 34
(`docs/goals/TODO.md`, 2026-10-22) decided them: F1, F2, F4 and F5 are fixed in the code and their tests now pass
as guards; F3 is accepted and its two tests stay `xfail(strict=True, raises=AssertionError)`, so a change that
closes it flips them. A hang (a 10 s thread guard) or a crash fails the run instead of counting as the finding.

- **F1, release ignored who asks (fixed).** `s1` claimed `k1`; `s2` called `cicada_video_claim(release=[k1])` and
  the row failed. Now `claim` mints a 128-bit `lease_token` per leased row (`video_queue.claim:680`), the reply
  shows it on the video's line, and `release` ends a lease only with that row's token
  (`video_queue.release:712`, `video_queue._token_matches:652`); anything else answers `not_yours` and the lease
  lapses on its own clock, as does a row claimed before tokens existed. The session id is never compared: TLC
  shows a session compare lets a handle-less remote conversation release another's lease
  (`F1s-session-compare-shared-ids`), and leaves a CLI caller with no id or a restarted stdio process unable to
  hand back its own (`F1s-session-compare-sessionless`, `F1s-session-compare-restart`).
- **F2, a stale saved snapshot dropped a fresh row (fixed).** Every writer read the saved videos before its lock,
  and a video saved and queued meanwhile was dropped as an orphan (`video_queue._open:505`). Every writer now reads
  them under its lock (`video_queue.claim:668`, `video_queue.complete:739` and the rest; the writers no longer take
  a `saved` argument), and the MCP handler reads them again after the claim for its reply lines only.
- **F3, a record older than the request closes it (accepted).** `record_watch` writes its episode
  (`mcp_tools.record_watch:635`). The person queues the video, and another caller claims it. The credit then
  runs (`mcp_tools.record_watch:651`) and a stated basis closes the row (`video_queue.complete:747`) whatever the
  record's age, ending the other caller's lease. A second path needs no credit gap: `requested_at` is kept to the
  second (`video_queue._iso:149`) and `newer_than` compares with `>=` (`video_state.newer_than:239`), so a record
  from earlier in the request's own second counts as newer, both here and in the lapse sweep
  (`video_queue._settle:342`). **Likelihood: negligible.** A watch that meets the request exists, written seconds
  before the person asked, which is what the person wants in the only realistic case. **Revisit** (ruling 34) if a
  lease is ever seen ending on an older record: then take the microsecond compare below.
- **F4, an active caller kept its leases forever (fixed).** A claim, release or complete carrying the caller's
  session id refreshes every unlapsed lease stored under that id (`video_queue.claim:670`,
  `video_queue.release:699`, `video_queue.complete:750`). A refresh now never carries a lease past
  `MAX_LEASE_PERIODS` (3) lease periods from its claim (`video_queue._refresh:644`, `video_queue._lease_cap:629`),
  so a forgotten lease lapses at most 135 minutes after its claim however often the caller calls.
- **F5, a shared session id let one conversation close another's lease (fixed).** Two remote conversations on one
  connector that both omit their `conversation` handle share one id (`runtime.resolve_handle:75`). A record with no
  basis now closes a leased row only with that row's lease token (`video_queue.complete:749`), which
  `cicada_record_watch` takes as `lease_token`; without it the row is `left`.

## The fixes, mirrored in the model

The model's `Fixes` constant holds each one. The `code-*` checks run with `{"F1", "F2", "F4", "F5"}`, what the
code does since ruling 34. Each finding's check (`F1-*`, `F2-*`, `F4-*`, `F5-*`) runs the code with that one fix
taken out and must still fail, which shows the passing checks can fail. `fixed-*` adds the F3 proposal and checks
every safety property across the session-id modes. The rejected first proposals for F1 and F3 are kept as `F1s`
and `F3s`, and their checks are expected to fail.

- **F1, the lease token.** Modeled as the claimer itself: only its conversation sees the reply, and that survives a
  process restart. With a unique token per claim, P3 holds almost by definition, so the checks that carry weight
  are P13 and the legacy rows (`fixed-legacy-rows`, a row may carry no token). `break-release_ignores_token` shows
  P3 fails without the check.
- **F2, the saved videos read under the lock.** With F2 a snapshot is never stale. `break-f2_credit_stale` shows a
  half fix that leaves `complete`'s read before the lock still loses rows.
- **F4, the lease cap.** Each row carries `cap`, the ticks left before its cap (3 lease periods at claim); a refresh
  sets the lease to `Min(LeaseTicks, cap)`. `code-lease-cap` holds P9 with one caller that never stops calling;
  `break-no_lease_cap` and `F4-active-session-keeps-lease` show it fails without the cap.
- **F5, the token for a record with no basis.** `break-record_ignores_token` shows P4 fails without it.
- **F3, the proposal if the trigger ever fires: the microsecond compare.** Keep `requested_at` to the microsecond,
  pass the record's own episode timestamp to `complete`, and close a stated-basis row only when that timestamp
  is after `requested_at`. The lapse sweep then compares at full precision too. The first proposal, passing the
  record's time through `newer_than`, still closes a row on a record from earlier in the same second
  (`F3s-seconds-compare-same-second`). Gaps that remain: one wall clock is assumed across processes, so a clock
  stepped back between the episode write and the put can still misorder them; rows queued before the change keep
  second precision until queued again; a repeated record with the same summary reuses its first episode and that
  episode's older timestamp (`watch_record._write_episode:153`), which errs towards leaving the row; `claim` sorts
  by the `requested_at` string, so mixed precisions should sort by the parsed instant.

## Reading a result

`run.sh` prints `check | expected | got | states | s`. On anything unexpected, read `$OUT/<check>.trace.txt`.
Each step names the call and the code it models.

- **A violation nobody expected.** Replay the steps against the code, one line at a time. If some step is
  something the code cannot do (a guard the model lacks, a field the code resets, a call the code does not
  make), it is a **modeling error**. Fix the operator in `VideoQueue.tla` to match the code, cite the line, and
  rerun. If every step is something the code does, it is a **real bug**. Write a test that drives the real entry
  points in that order (see `test_video_queue_formal.py`), mark it `xfail(strict=True, raises=AssertionError)`
  with a new finding id, add a `models/F<n>-*.cfg` expected to violate, and add it to `EXPECT_DEFAULT`. Never weaken
  a property or remove a behaviour from the model to get a pass.
- **A break shows only in the `fixed-*` checks.** A property with an open finding (P4, P5: F3, accepted) is
  checked on the code only by its finding's check, which already fails. The `fixed-*` checks hold every property
  with the F3 proposal in place, so a new way to break P4-P5 surfaces there.
- **A finding's check now passes.** Either the code fixed it, or the model drifted. Confirm against the code. If
  the fix is real, mirror it (change the operator so the code-today checks describe the fixed code), flip the
  expectation to `pass` with a minimum state count, and remove the test's `xfail` marker.
- **A passing check now fails after an intended change.** Decide whether the property still states a promise the
  code makes. Change a property only with an owner's ruling recorded in `docs/goals/TODO.md`.
- **`TOO FEW STATES`.** A passing check explored fewer states than at the sync commit. An action or a branch was
  lost. Find it before trusting any pass.
- **`error` in the got column.** TLC could not parse or evaluate the spec. The log names the line.

## Keeping it in step

**Sync point: the ruling-34 fix** (branch `fix/video-lease` on `dev` at `10bf8f4d`, 2026-10-22; `coverage.lock`
holds the fingerprints). At that point the model describes these definitions:

| Code | Model |
|---|---|
| `video_queue._locked:250`, `video_queue._write:263`, `video_queue._read_file:214` | one locked step per write call |
| `video_queue._lapsed:296`, `video_queue.LEASE_MINUTES:65` | `Lapsed`, `LeaseTicks`, `Tick` |
| `video_queue._failed_expiry:291`, `video_queue.EXPIRE_FAILED_DAYS:74` | `FailExpired`, `FailTicks` |
| `video_queue._settle:314`, `video_queue.MAX_ATTEMPTS:68` | `SettleRow`, `Settle` |
| `video_queue._drop_orphans:372`, `video_queue._open:496`, `video_queue._saved:482` | `Open`, the `snap` of each snapshot step (never stale with F2) |
| `video_queue._refresh:633`, `video_queue._lease_cap:627`, `video_queue.MAX_LEASE_PERIODS:67` | `Refresh`, `Extended`, `cap` (by session id; none refreshes nothing; F4 caps it) |
| `video_queue.claim:655` (stored id `video_queue.claim:679`, token `video_queue.claim:680`) | `ClaimBegin`, `ClaimLocked`, `ClaimFn`, `Takes` (any non-empty subset), `Tokens` |
| `video_queue.release:686`, `video_queue._token_matches:649` | `ReleaseBegin`, `ReleaseLocked`, `ReleaseFn`, `MayRelease` |
| `video_queue.complete:725` (saved set `video_queue.complete:739`) | `CreditBegin`, `CompleteLocked`, `CompleteFn`, `Done` |
| `video_queue.put:532`, `video_queue.handoff:586`, `video_queue._upsert:516`, `video_queue.remove:550`, `video_queue.retry:569`, `video_queue._reset:510` | `PutBegin`, `RemoveBegin`, `RetryBegin`, `PersonLocked`, `Restarted` |
| `video_queue.view:388` | the settled view each locked step starts from; `EffClaimed` |
| `video_queue._iso:148`, `video_queue._parse:152`, `video_queue._now:144`, `video_queue._clean_row:178` | request time to the second; `same` places; `CodeNewer` |
| `video_state.satisfies:242`, `video_state.newer_than:232`, `video_state.clean_basis:71`, `video_state.basis_facts:81`, `video_state.BASES:58`, `video_state.watch_records:202` | `SatisfiesCode`, `Fact`, the records |
| `video_state.saved_videos:148` | `saved`, `SaveVideo`, `HideVideo` |
| `mcp_tools.video_claim:1215` (reply-only read `mcp_tools.video_claim:1255`) | `ClaimBegin`, `ReleaseBegin` |
| `mcp_tools.record_watch:585` (episode `mcp_tools.record_watch:635`, credit `mcp_tools.record_watch:651`), `mcp_tools._credit_video_queue:1120`, `watch_record._write_episode:139`, `watch_record.record:239`, `episode_ids.utc_now_iso:213` | `RecordEpisode`, `CreditBegin`, `CompleteLocked`, `DropCredit`, `Fresh` |
| `mcp_tools.ToolContext.pages_held:209`, `mcp_tools._backend_sleep_running:54` | `holding`, `SleepStart`, `SleepEnd` |
| `session_identity.parse:42`, `session_identity.stdio_identity:54`, `session_identity.cli_identity:64`, `cli._tool_context:237`, `cli_app.door:305`, `tool_door.Caller:58`, `tool_door.context:182`, `runtime.resolve_handle:68`, `runtime.mint_handle:63` | `IdMode`, `FirstId`, `sid`, `Restart` |
| `videos._view:69`, `videos._put:136`, `videos.delete_video_queue:150`, `videos._retry:155`, `videos._handoff:179` | `PutBegin`, `RemoveBegin`, `RetryBegin`, `PersonLocked` |

When a covered definition changes on purpose:

1. Run `coverage.py` to list what moved, and read each change.
2. Edit the matching operator in `VideoQueue.tla` and fix any citation coverage.py lists.
3. If a scratch break's text moved, update `BREAKS` in `able_to_fail.py`.
4. Run `ALLOW_DRIFT=1 run.sh` and `able_to_fail.py`. Read every unexpected result as above. If a pass's state
   count moved on purpose, update its minimum in `run.sh`.
5. Only after the model describes the new code: run `python3 coverage.py --update`, and move the sync commit
   above to the commit you checked.

## Scope and bounds

- **Bounds.** One video and two callers plus the person, explored to the end, for each session-id mode: `stable`
  (a harness id), `shared` (one id for both, the remote day bucket), `sessionless` (no id, the CLI door; an id over
  80 characters behaves the same, since every compare fails), and `restart` (either caller may restart once and
  take a new id, `--deep`). Liveness: one video, two calls per caller (`CallBudget = 2`), and one caller with no
  call budget for the lease cap (`code-lease-cap`). Orphans: two videos and one caller with pages saved and hidden
  (`F2`, `break-f2_credit_stale`, and `code-churn` and `fixed-churn` in `--deep`). A lease
  lasts 2 ticks, a failed row 1 tick, and three lapses fail a row, as in the code. Symmetry over videos and callers
  applies to safety only.
- **`--deep` has never finished its two-video run.** `deep-safety` (two videos, two callers, stable ids) was
  stopped at a 15-minute cap on 2026-10-22 after 12,923,785 distinct states with no violation and 3.6 million
  states still queued (before ruling 34; not rerun since). The rest of `--deep` finishes; before ruling 34
  `code-ids-restart` and `fixed-ids-restart` took 339,464 states, about 12 s each, and `fixed-churn` 22,903,520
  states, about 4 minutes with four workers. On the ruling-34 model (the lease cap adds a field), `code-ids-restart`
  and `fixed-ids-restart` take 887,240 states, about a minute each, and `code-churn` (P2 on the fixed code)
  97,464,544 states, 21 minutes with four workers, no violation; `fixed-churn` and `deep-safety` have not been rerun
  and keep a minimum of 0. The one-video argument below is what the default run rests on.
- **Why one video is enough.** Every property is about one video, and every step changes a row as a function of
  that row alone, with two exceptions. A call that refreshes the caller's other leases does, on one video, what a
  claim that finds nothing does. The orphan drop needs a non-empty snapshot that lacks the key, so its checks keep
  two videos.
- **The reduction.** When a snapshot cannot be stale (pages never change, or fix F2), the snapshot step reads a
  constant and writes only its caller's state, so the model runs its locked step next, with only time, Sleep, a
  new second and a restart in between. A stale snapshot step is never fused, and neither is the episode-to-credit
  gap.
- **Abstractions.**
  - Time is relative ticks for leases, plus a "new second" step for the wall clock.
  - A record keeps only its fact and its place against the current request (five places), and each video keeps
    only the records no other record of the same fact dominates. Every query asks whether some record exists, and a
    dominating record answers yes wherever the dominated one does, now and after any new request or second.
  - A record with no basis is not kept, because it satisfies nothing. Its credit still runs.
  - The code reads `now` before it takes the lock, and the model times each locked step at the lock. Another
    writer that ran in between already settled anything that lapsed in that gap, so the stale clock only changes
    the stamps the step writes (a lease a few milliseconds shorter). If no writer ran in between, the code's step
    is the model's step taken before the tick.
  - `claim` may take any non-empty subset of the claimable rows, a superset of oldest first. A hand-off is one
    `put` per video. A lease token is the claimer's identity, and a holder always passes it; a holder that omits
    it acts as a non-holder would (`not_yours`, `left`), a subset of what the model explores for the other caller.
  - The lease cap counts ticks from the claim and is cleared when the lease lapses (a lapsed lease is never
    refreshed again), so it adds no state once it cannot matter.
- **Left out.** Batches (`done`, expiry, the active batch), `MAX_ROWS`, the scrubbing and capping of reasons, the
  release codes (all one transition), `stamp`, `next_change_at`, ETags and the parse cache, `bank_slug`, the
  remote runtime's busy refusal, the demo-bank refusal, Sleep's admission internals (a flag here), clock skew
  between processes, a repeated record reusing its first episode, and two person requests at once. Each locked
  step is atomic, so only the snapshot race matters there, and F2 covers it with one person.

## Files

`VideoQueue.tla` (the model), `models/*.cfg` (one check each), `run.sh`, `trace.py`, `coverage.py` and
`coverage.lock`, `able_to_fail.py`, and `statechart.md` (the statechart and every transition with its code line,
drawn before the model).
