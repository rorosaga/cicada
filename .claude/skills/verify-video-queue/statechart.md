# The video queue's lease lifecycle, as the code implements it

Drawn from the code at the sync commit in `SKILL.md`, before the model was written. Every citation is
`<module>.<function>:<line>`, and `coverage.py` fails when a line falls outside the function it names.

## One video's row

```mermaid
stateDiagram-v2
    [*] --> NotQueued
    NotQueued --> Queued: put / handoff, key saved (video_queue._upsert:498)
    Queued --> Queued: put again (watch upgrades, never downgrades, video_queue._upsert:501)
    Queued --> Claimed: claim by any caller, key in the saved snapshot (video_queue.claim:627)
    Claimed --> Claimed: a claim, release or complete carrying the stored session id refreshes (video_queue._refresh:609)
    Claimed --> Lapsed: lease_until <= now, nothing written (video_queue._lapsed:280)
    Lapsed --> NotQueued: next write, Sleep not holding, a record "newer" than the request (video_queue._settle:322)
    Lapsed --> Queued: next write, Sleep not holding, attempts + 1 < 3 (video_queue._settle:337)
    Lapsed --> Failed: next write, Sleep not holding, attempts + 1 = 3 (video_queue._settle:333)
    Lapsed --> Lapsed: Sleep holds the pages (video_queue._settle:316)
    Claimed --> Failed: release by ANY caller (video_queue.release:661)
    Lapsed --> Failed: release by any caller, only while Sleep holds the pages (video_queue.release:661)
    Claimed --> NotQueued: complete with a stated basis that meets the request (video_queue.complete:694)
    Queued --> NotQueued: complete with that basis, any caller (video_queue.complete:694)
    Failed --> NotQueued: complete with that basis, any caller (video_queue.complete:694)
    Claimed --> NotQueued: complete with no basis, caller's id equals the stored one (video_queue.complete:696)
    Lapsed --> NotQueued: complete with no basis, same id, only while Sleep holds (video_queue.complete:696)
    Claimed --> Claimed: complete, transcript for a watch request: stays (video_queue.complete:699)
    Failed --> Queued: retry (requested_at kept, video_queue.retry:557) or put (requested_at now, video_queue._upsert:505)
    Failed --> NotQueued: failed.at + 7 days (video_queue._settle:309)
    Queued --> NotQueued: remove (video_queue.remove:532)
    Claimed --> NotQueued: remove (video_queue.remove:532)
    Failed --> NotQueued: remove (video_queue.remove:532)
    Queued --> NotQueued: orphan drop, key not in a non-empty saved snapshot (video_queue._open:482)
    Claimed --> NotQueued: orphan drop (video_queue._open:482)
    Failed --> NotQueued: orphan drop (video_queue._open:482)
```

`Lapsed` is not a value in the file. The file still says `claimed`; every reader settles it in memory
(`video_queue.view:372`, `video_queue._open:477`) and only a write persists the settlement. While Sleep holds the
pages a lapsed lease is left as it is, so it reads as claimed again. When Sleep does not hold them, every write
settles a lapsed lease first, so `release` and the no-basis `complete` reach a lapsed row only while Sleep holds.

## Every transition

| # | From | To | Trigger | Guard | Code |
|---|---|---|---|---|---|
| 1 | not queued | queued | person queues (PUT `/videos/queue/{key}`, POST `/videos/run/handoff`) | key in the saved snapshot | `video_queue._upsert:498`, `video_queue.put:515`, `video_queue.handoff:583`; `videos._put:137`, `videos._handoff:180` |
| 2 | queued | queued | person queues again | `want=watch` upgrades; a transcript never downgrades | `video_queue._upsert:501` |
| 3 | queued | claimed | `cicada_video_claim`, `cicada video claim` | state `queued` and key in the saved snapshot; oldest first; at most `min(limit or 5, 10)`; the caller's session id is stored only when it has one, cut to 80 characters | `video_queue.claim:627`, `video_queue.claim:635`; `mcp_tools.video_claim:1222` |
| 4 | claimed | claimed, lease extended | a claim, release or complete whose session id equals the stored one | lease not lapsed; a caller with no id refreshes nothing | `video_queue._refresh:605`, called at `video_queue.claim:626`, `video_queue.release:651`, `video_queue.complete:697` |
| 5 | claimed | lapsed | time passes `lease_until` | none; nothing is written | `video_queue._lapsed:280` |
| 6a | lapsed | not queued (done) | the next write | Sleep not holding; a record at or after `requested_at`, read to the second, meets the request | `video_queue._settle:322`; `video_state.newer_than:239` |
| 6b | lapsed | queued, attempts + 1 | the next write | Sleep not holding; attempts + 1 < 3 | `video_queue._settle:337` |
| 6c | lapsed | failed (`failed`, derived reason) | the next write | Sleep not holding; attempts + 1 = 3 | `video_queue._settle:333` |
| 6d | lapsed | lapsed | the next write | Sleep holds the pages (`mcp_tools.ToolContext.pages_held:209`) | `video_queue._settle:316` |
| 7 | claimed, any holder (lapsed only while Sleep holds) | failed (code, scrubbed reason) | `cicada_video_claim(release=[{url, code, reason}])` | state `claimed`; **who asks is not compared** | `video_queue.release:661`; `mcp_tools.video_claim:1206` |
| 8 | any row | not queued (done) | `cicada_record_watch` credits the queue | basis `frames`/`both`, or `transcript` for a transcript request; **any caller, any state, any record age** | `video_queue.complete:694`; `mcp_tools.record_watch:629`, `mcp_tools._credit_video_queue:1104` |
| 9 | claimed (lapsed only while Sleep holds) | not queued (done) | `cicada_record_watch` with no basis | the caller's session id is non-empty and equals the stored one | `video_queue.complete:696` |
| 10 | claimed | claimed | `cicada_record_watch(basis=transcript)` on a watch request | none: the row stays | `video_queue.complete:699` |
| 11 | failed | queued, attempts 0 | Try again (POST `.../retry`), or queue again | retry keeps `requested_at`; put restarts it | `video_queue.retry:557`, `video_queue._reset:490`; `video_queue._upsert:505` |
| 12 | failed | not queued | the next write | `failed.at` + 7 days <= now | `video_queue._settle:309` |
| 13 | any row | not queued | person removes (DELETE `/videos/queue/{key}`) | none | `video_queue.remove:532`; `videos.delete_video_queue:151` |
| 14 | any row | not queued | any write | the writer's saved snapshot is non-empty and lacks the key | `video_queue._drop_orphans:355`, `video_queue._open:482` |

## What is atomic, and what is not

- **Atomic: one locked read-modify-write.** `put`, `remove`, `retry`, `handoff`, `claim`, `release` and
  `complete` each read the file (`video_queue._read_file:196`), settle, drop orphans, change rows and write under
  one exclusive `fcntl.flock` on the sidecar `<bank>.json.lock` (`video_queue._locked:236`). The write is a temp
  file plus `os.replace` (`video_queue._write:250`), so a crash before the rename writes nothing and a crash after
  it is a complete write. Each call opens its own lock file description, so the lock excludes threads of one
  process as well as other processes. The model makes each of these one step.
- **Not under the lock: the saved snapshot and the clock.** Every writer reads the saved videos and `now` before
  it locks: `video_queue.put:514`, `video_queue.remove:529`, `video_queue.retry:549`, `video_queue.handoff:582`,
  `video_queue.claim:623`, `video_queue.release:647`, `video_queue.complete:682`, and the MCP handler passes its
  own snapshot from `mcp_tools.video_claim:1204`. The model splits each call into a snapshot step and a locked
  step, and times the locked step at the lock (see SKILL.md, abstractions).
- **Not one step: a record and its queue credit.** `record_watch` writes the episode and its claim
  (`mcp_tools.record_watch:613`), may commit (`mcp_tools.record_watch:620`), and only then calls
  `_credit_video_queue` (`mcp_tools.record_watch:629`), which swallows any exception
  (`mcp_tools._credit_video_queue:1109`). `complete` then reads the saved videos before its lock. The model splits
  a record into the episode write, the credit's snapshot and the locked credit, and lets the credit never run.
- **Readers take no lock.** `video_queue.view:371` reads one whole file (the rename makes it old or new, never
  half) through a parse cache keyed by `(mtime_ns, size)` and settles in memory. The model folds readers into the
  settled view every locked step starts from.
- **Inside the lock: the Sleep probe.** `holding()` is asked lazily inside `_settle` (`video_queue._settle:316`),
  under the lock. On stdio it is an HTTP probe with a 2 s timeout (`mcp_tools._backend_sleep_running:69`), so a
  writer holds the queue lock for up to 2 s when the backend is slow to answer.

## Actors

- **The person**, through the backend's routes (`api/routers/videos.py`), which run in a thread pool.
- **Agent callers**, each carrying a session id that the queue stores at claim and compares later. The id is
  not always stable or unique:
  - A Claude Code session, or any harness that sets `CICADA_SESSION_ID`, has one stable id
    (`session_identity.parse:47`).
  - A stdio MCP server under any other harness mints `ses_<date>_<hex>` per process
    (`session_identity.stdio_identity:61`), so a restarted process has a new id and no longer matches its own
    leases.
  - `cicada video claim` from the CLI with no harness id runs with session id `""`
    (`cli._tool_context:242`, `cli_app.door:313`, `tool_door.Caller:59`), so nothing is stored and nothing
    compares equal.
  - Every remote conversation that omits its `conversation` handle shares one id per connector per day
    (`runtime.resolve_handle:75`), so two such conversations look like one caller.
  - An id longer than 80 characters is stored cut (`video_queue.claim:635`) while every later compare uses the
    whole id, so it behaves exactly like no id.
- **Sleep**, which holds the pages through `write_admission`. The queue only asks whether it does.
- **Time.** Leases are 45 minutes (`video_queue.LEASE_MINUTES:53`), failed rows age out after 7 days
  (`video_queue.EXPIRE_FAILED_DAYS:60`), three lapses fail a row (`video_queue.MAX_ATTEMPTS:54`). A request's
  `requested_at` is kept to the second (`video_queue._iso:132`), an episode's timestamp to the microsecond
  (`episode_ids.utc_now_iso:221`), and `video_state.newer_than:239` compares them with `>=`.
