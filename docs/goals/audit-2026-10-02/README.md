# Cicada code and performance audit — 2026-10-02

**Status: audit complete; fixes not implemented; live CPU attribution pending.**

Audited revision: `9f7d8f5ba19f3a399543cf63f9c843ad319591e6` (`dev` at worktree creation).
Isolated branch: `audit-2026-10-02`; worktree: `<repo>/.worktrees/audit-2026-10-02`.
The main checkout's pre-existing changes were excluded and preserved. This branch adds
documentation and synthetic diagnostic probes only. No application fixes, installation,
live-bank mutation, paid model calls, repository commits, publication or PR were performed.

The review covered storage/capture/Sleep, bank management, API/MCP boundaries, app sync
and optimistic writes, and graph/animation lifecycles. It used sequential code review,
fault injection, synthetic fixtures and existing suites. It is a focused audit, not a
claim that every path or security property has been exhaustively verified.

Read [validation and reproduction](VALIDATION.md) for commands, results and limitations;
use [the handoff prompt](HANDOFF.md) to continue in a new session. Source line references
below refer to the pinned revision; recheck them against any newer `dev`.

## Revalidation on current `dev` (2026-10-05, `efd5386e`)

The audit was written at `9f7d8f5b`, before G176 (PRs #164–#166). `git diff 9f7d8f5b efd5386e`
touches **no file under `api/`** and, among the audited Swift/JS files, only `MenuBarManager.swift`
and `BookwormView.swift`. Every other line reference below is still exact. The durable probes were
rerun on `efd5386e` from a docs worktree with the existing API virtualenv, synthetic `/tmp` banks,
`CICADA_CAPTURE=off` and dotenv disabled; their output was byte-identical to the audit's.

| ID | Verdict on `efd5386e` | Evidence | Reconciled with |
|---|---|---|---|
| A01 | **Confirmed** | `storage.py`: `new_revision_marked_processed: true`, `remaining_queue: 0` | G104/G105 (resumed-session capture); new fix, no new G id |
| A02 | **Confirmed** | `storage.py`: `old_file_preserved: false`, `bytes_remaining: 20` | — |
| A03 | **Confirmed (static)** | `Store.swift` unchanged since the audit | — |
| A04 | **Confirmed** | `storage.py`: `external_file_copied: true` | — |
| A05/A06 | **Confirmed (static)** | `SourceMutations.swift`, `LookItUpSection.swift` unchanged | G61 (sources) |
| A07 | **Confirmed** | `graph-loops.cjs`: pending node renders 120/120 frames and still queues one at alpha 0 | G109 (d3-force stays) |
| A08 | **Confirmed (static)** | `GraphView.swift` unchanged; the ownership pattern is the probe's | G109 |
| A09 | **Confirmed** | `graph-loops.cjs`: `alphaAfter400Ticks ≈ 0.1` with mouseup omitted | G109 |
| A10 | **Confirmed (static)** | `sync.py`, `sync_service.py`, `bank_index.py`, `sleep_debt.py` unchanged; timings not rerun | — |
| A11 | **Confirmed (static)** | `ExportWalkthroughSheet.swift:23` still asks `frameInterval(lowPower: false)` and has no visibility reader | G145 (walkthrough); G176 follow-up 1 owns the Sleep page CPU, not this sheet |
| A12 | **Gone — fixed by G176** | `MenuBarManager.swift:38–40,207–222`: the chained frame timer only runs when `isVisible && !displaysAsleep && !reduceMotion` (pinned by `BookwormRendererTests.swift:93–95`); `BookwormView.swift:27,39,48–49`: Reduce Motion selects `.still` and draws one static frame with no `TimelineView`, and a hidden window pauses it | G176 |
| K01 | **Confirmed** | `episode_ids.py:70–85` unchanged; no cross-process allocation lock exists | G114 (one id rule) / G135 (disclosed race, TODO "G135 … G114's standing rule") |

**A11/A12 and the G176 Sleep-page CPU follow-up** (`docs/specs/2026-10-02-g176-followups-handoff.md`,
item 1: 11.9 % of a core against ≤ 3 %) are one piece of work in the sense that both are animation
clocks, but they do not overlap in code: A12 is already closed by G176, A11 is the Import
walkthrough sheet, and the Sleep page's cost is per boundary inside the room's sprite layers.
The Sleep-page item needs on-screen release-build profiling with the owner's word, so it stays
with that handoff; it is not duplicated here.

Status of each fix lives in [STATUS.md](STATUS.md).

## Main conclusion

The highest priorities are protecting captured revisions and file writes, then stopping
graph work when its surface is inactive. Sleep can mark a newer episode processed even
though it extracted an older body; an interrupted markdown overwrite can truncate the
original. The graph schedules frames indefinitely for one pending node after physics
has settled, and its native wrapper has a reproducible WebKit retention cycle.

The reported **about 55% combined app/WebKit CPU for 41 hours, plus about 4% API CPU**
remains a user-supplied observation. The code contains credible mechanisms for sustained
work, but this audit did not establish that they caused those exact process readings.
Shell process inspection was blocked (`ps: Operation not permitted`). Activity Monitor
access was rejected again after the user explicitly approved it: **“Computer Use was not
approved to use Activity Monitor.”** Application scheduling and ownership were reproduced
without reading the live bank; actual hidden-window WebKit delivery and CPU were not.

If “41 hours” came from Activity Monitor's **CPU Time** column, it is accumulated CPU time,
not evidence of 41 hours of continuous 55% utilization. Establish process elapsed time,
sampling interval and WebKit ownership before making that stronger claim.

## Ranked findings

P1 = prioritize for data preservation or sustained resource drain; P2 = correctness or
material scaling issue; P3 = bounded efficiency improvement. “Reproduced” describes the
specified diagnostic, not every end-to-end consequence. A01–A06 correspond to the first
audit's findings 1–6; A07–A12 are its performance extension.

| ID | Priority | Finding | Evidence level | Suggested batch |
|---|---|---|---|---|
| [A01](#a01--sleep-can-retire-an-unread-episode-revision) | P1 | Sleep retires an unread episode revision | Reproduced | Storage |
| [A02](#a02--markdown-overwrites-are-not-atomic) | P1 | Partial overwrite destroys the old markdown | Fault-injected | Storage |
| [A03](#a03--late-entity-reads-can-cross-bank-or-invalidation-boundaries) | P2 | Late entity response repopulates stale cache | Static async trace | App sync |
| [A04](#a04--bank-duplication-follows-external-symlinks) | P2 | Duplicate includes data outside the bank | Reproduced | Bank boundary |
| [A05](#a05--source-edit-rollback-can-undo-a-different-successful-edit) | P2 | Overlapping source writes overwrite each other locally | Static async trace | Source editing |
| [A06](#a06--failed-source-add-discards-the-draft-silently) | P2 | Source-add failure loses input silently | Static control-flow trace | Source editing |
| [A07](#a07--pending-pulses-keep-the-entire-graph-redrawing) | P1 | Graph pulse loop lacks app visibility control | Scheduler reproduced; live CPU pending | App energy |
| [A08](#a08--graph-web-view-and-script-handler-retain-each-other) | P2 | Graph web view ownership cycle | Real WebKit ownership probe | App energy |
| [A09](#a09--interrupted-drag-can-leave-physics-permanently-active) | P2 | Interrupted drag keeps positive alpha target | Conditional handler reproduction | App energy |
| [A10](#a10--idle-sse-repeatedly-scans-the-bank-per-connection) | P2 | Idle SSE filesystem work scales with bank and clients | Synthetic timing + static trace | API efficiency |
| [A11](#a11--walkthrough-ignores-the-existing-visibility-and-power-policy) | P3 | Walkthrough requests full animation cadence unnecessarily | Static trace | Animation efficiency |
| [A12](#a12--hidden-or-static-sprites-still-have-frame-clocks) | P3 | Hidden menu sprite and static reduced-motion sprite still tick | Static trace | Animation efficiency |

Every finding remains **open**. Code review findings A03/A05/A06/A11/A12 need controlled
regression reproductions before a fix is declared complete. No new permanent `G` numbers
were assigned in this documentation pass; reconcile with existing rows during triage.

## Storage and correctness findings

### A01 — Sleep can retire an unread episode revision

**Evidence:** [`sleep_cycle.py:2674–2699`](../../../api/services/sleep_cycle.py#L2674-L2699)
selects an episode body without a revision/hash;
[`2515–2524`](../../../api/services/sleep_cycle.py#L2515-L2524) maps extracted IDs back to
those selected episodes; [`2802–2819`](../../../api/services/sleep_cycle.py#L2802-L2819)
then rereads the current file and unconditionally sets `processed: true`.
Meanwhile [`transcript_capture.py:335–392`](../../../api/services/transcript_capture.py#L335-L392)
can update that same session episode and reset it to unprocessed.

**Reproduction:** select revision one; write a later synthetic correction to the same
episode with revision two; mark the selected item processed. The selected content did
not contain the correction, but the newer file became processed and the queue became
empty. This reproduced the retirement race without calling an extraction model.

**Improvement:** carry a selected revision and compare it with the current file under a
write critical section shared with capture. Retire only the revision actually read.
Use a content-derived fallback for legacy files without a stored hash. A check followed
by an unlocked write still races. Keep capture available during Sleep.

**Acceptance:** capture between selection and retirement leaves the changed episode
queued; an unchanged selected episode retires once; the predicate is protected against
another write between comparison and replacement. Test source-keyed edits and resumed
session capture, not just a manually updated dictionary.

### A02 — Markdown overwrites are not atomic

**Evidence:** [`markdown_parser.py:69–72`](../../../api/services/markdown_parser.py#L69-L72)
uses `Path.write_text` on the destination itself. This common writer serves persistent
markdown, so truncation is not confined to a disposable cache.

**Reproduction:** inject an `OSError` after the opened destination writes 20 bytes. The
original complete document is gone and only 20 bytes remain.

**Improvement:** stage the complete document in a uniquely named adjacent temporary file,
then atomically replace the destination. Preserve intended permissions and clean up
failed temporary writes; consider file/directory sync for the durability guarantee the
project chooses. Keep temporary names out of markdown scans.

**Acceptance:** a failed temporary write leaves the original bytes intact; successful
writes parse normally; cleanup and permissions are verified. Atomic replacement does
not itself fix stale read/modify/write decisions or episode-ID collisions.

### A03 — Late entity reads can cross bank or invalidation boundaries

**Evidence:** [`Store.swift:185–200`](../../../app/CicadaApp/Sources/CicadaApp/Sync/Store.swift#L185-L200)
clears entities during bank hydration, but
[`600–609`](../../../app/CicadaApp/Sources/CicadaApp/Sync/Store.swift#L600-L609) awaits
`fetchEntity` then caches the result unconditionally.
[`615–625`](../../../app/CicadaApp/Sources/CicadaApp/Sync/Store.swift#L615-L625) invalidates
without preventing an older in-flight read from repopulating it. The domain-refresh path
already checks bank/refresh epoch at
[`340–395`](../../../app/CicadaApp/Sources/CicadaApp/Sync/Store.swift#L340-L395).
[`GraphViewModel.swift:581–591`](../../../app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift#L581-L591)
consumes the fetched entity by ID.

**Failure sequence:** start bank A's entity fetch; hydrate bank B, which has the same ID;
finish A's response. A's body is returned and cached after the bank changed. Likewise,
a read started before a mutation can undo cache invalidation. These sequences follow
the implementation; a controlled suspended-fetch regression is still needed.

**Improvement / acceptance:** check bank generation and per-entity/global invalidation
generation after the await, before both returning and caching. Prove that late reads
are discarded across bank change, mutation invalidation and graph replacement.

### A04 — Bank duplication follows external symlinks

**Evidence:** [`bank_registry.py:574–625`](../../../api/services/bank_registry.py#L574-L625)
copies directory children with `copytree` and other children with `copy2`, using defaults
that dereference symlinks. Export explicitly skips links at
[`766–784`](../../../api/services/bank_registry.py#L766-L784).

**Reproduction:** a synthetic source bank contains a directory symlink pointing to a
synthetic directory outside the bank. Duplicate includes the target's file in a normal
directory. This can unintentionally ingest external/private data; it does not establish
remote exploitation or show that the user's actual bank contains such links.

**Improvement / acceptance:** use an explicit recursive link policy consistent with
export: skip or reject symlinks, or allow only targets demonstrably confined to the bank.
Verify directory, file, nested and dangling symlinks, including outside-bank targets.

### A05 — Source-edit rollback can undo a different successful edit

**Evidence:** [`SourceMutations.swift:24–39`](../../../app/CicadaApp/Sources/CicadaApp/Sync/SourceMutations.swift#L24-L39)
snapshots and replaces the whole binding list, then restores the whole old list on
failure. [`LookItUpSection.swift:146–152`](../../../app/CicadaApp/Sources/CicadaApp/Views/Graph/LookItUpSection.swift#L146-L152)
starts independent tasks; [`Store.swift:512–531`](../../../app/CicadaApp/Sources/CicadaApp/Sync/Store.swift#L512-L531)
does not serialize them. The mutation refreshes only `.graph` at
[`SourceMutations.swift:45`](../../../app/CicadaApp/Sources/CicadaApp/Sync/SourceMutations.swift#L45).
Sources remain card-local state loaded by entity ID at
[`EntityDetailCard.swift:263–281`](../../../app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift#L263-L281).

**Failure sequence:** A snapshots the list and waits; B succeeds; A fails and rolls back
its entire earlier snapshot, hiding B's successful server change. Reordered successful
responses can also replace a newer list with an older response. This is a local display
consistency problem; server data loss was not demonstrated.

**Improvement / acceptance:** serialize writes for one entity or use revision-aware
overlays with narrow rollback and authoritative refetch. Test both completion orders,
one failure after another success, and leaving/changing the active entity or bank.

### A06 — Failed source add discards the draft silently

**Evidence:** [`LookItUpSection.swift:129–142`](../../../app/CicadaApp/Sources/CicadaApp/Views/Graph/LookItUpSection.swift#L129-L142)
clears `newRef` before awaiting the request and uses `try?`. There is no failure branch
to restore input or surface the error. Network failure, validation error or a write-window
409 therefore leaves the person with an empty field and no explanation.

**Improvement / acceptance:** preserve the pending draft and handle failures explicitly,
using the existing mutation/error surface where suitable. Preserve any new text typed
while the request is pending. Verify success, 409, validation and network failures, and
coexistence with the ordering policy from A05.

## Performance findings

### A07 — Pending pulses keep the entire graph redrawing

**Evidence:** [`graph.js:1294–1310`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L1294-L1310)
recursively requests another frame while `anyPending` is true, even at simulation alpha
zero. [`935`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L935)
computes that flag over graph-filter-visible nodes, not nodes actually on screen.
[`1345–1408`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L1345-L1408)
redraws links/nodes and pulse rings without viewport culling.
[`ContentView.swift:483–488`](../../../app/CicadaApp/Sources/CicadaApp/ContentView.swift#L483-L488)
keeps `GraphPage` mounted at opacity zero on other tabs. `GraphView` has no corresponding
native visibility/occlusion-to-JavaScript suspension bridge.

**Reproduction:** with real bundled graph code and d3, stopped simulation and alpha zero,
an explicitly drained frame queue renders once and empties without pending items. With
one pending node it renders all 120 requested frames and still queues another. Setting
a synthetic `document.hidden = true` does not change application scheduling. That last
case tests the absence of an application guard; it does **not** simulate WebKit's own
hidden-page frame throttling. An earlier offscreen synthetic probe still issued whole
graph draw calls with every node outside the viewport.

**Artifact check:** the installed app's graph resource and the pinned source had the same
SHA-256: `3f95fc678c939bcbb8b0af4b528953441215c7aba372345fa7f8be96f109c53c`.
This matches that on-disk JavaScript resource only; it does not identify the loaded
process's whole Swift build or prove what a long-running process had loaded.

**Improvement:** propagate selected-tab, native window visibility/occlusion, app hiding
and covering-sheet state to the graph. Suspend queued frames **and** d3 timers while
inactive; preserve positions/zoom and resume without gratuitous reheating. While visible,
animate only on-screen pulses, derive phase from elapsed time, and benchmark a bounded
cadence. A cached static base plus a pulse overlay is a possible later optimization,
after lifecycle fixes and measurement.

**Acceptance:** queued-frame tests for settle, pending, suspend, resume and destruction;
real foreground/other-tab/hidden/minimized/occluded CPU measurements; stable zoom and
positions on return. **G109 remains binding: keep d3-force.** Do not replace its layout
engine on this evidence, and do not stop capture/SSE to make the app look idle.

### A08 — Graph web view and script handler retain each other

**Evidence:** [`GraphView.swift:24–38`](../../../app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphView.swift#L24-L38)
registers the coordinator as a retained script message handler and assigns the web view
to it. [`154–164`](../../../app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphView.swift#L154-L164)
holds that view strongly. There is no `dismantleNSView` handler-removal path.

**Reproduction:** an isolated real `WKWebView` with the same ownership pattern and a
nonpersistent data store retains both objects after external references are dropped.
Removing the handler and clearing its view reference releases both. No page or bank
was loaded. The count of leaked web views in the user's running app was not measured.

**Improvement / acceptance:** make the coordinator's web-view reference weak and provide
explicit teardown that removes the handler and suspends rendering. A test must show the
actual graph wrapper deallocates on window/view destruction and repeated recreation does
not accumulate graph instances. This could amplify A07; the live magnitude is unresolved.

### A09 — Interrupted drag can leave physics permanently active

**Evidence:** [`graph.js:1789`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L1789)
sets `alphaTarget(0.1)` on node press; the normal release at
[`1916`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L1916)
resets it to zero. Blur handling at
[`544`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L544)
only clears transient pan mode, while
[`1969`](../../../app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js#L1969)
mouseleave handling only clears hover. There is no shared interrupted-drag cleanup.

**Conditional reproduction:** node press, mouseleave and no mouseup, followed by 400
manual ticks, leaves a live drag and alpha approximately `0.1`, above the stop threshold.
The OS/WebKit sequence that actually loses mouseup was not reproduced. A normal held
drag is expected to keep physics active.

**Improvement / acceptance:** centralize cleanup for pointer cancellation/lost capture,
blur, suspension and destruction; release pins and transient velocity, reset alpha target
without a release reheat. Test interrupted gestures, normal click/throw, pan mode and
hide-during-drag against the real handler wiring.

### A10 — Idle SSE repeatedly scans the bank per connection

**Evidence:** [`sync.py:16,41–54,128`](../../../api/routers/sync.py#L16)
runs version and debt checks every second in each SSE generator.
[`sync_service.py:165–184`](../../../api/services/sync_service.py#L165-L184)
walks episode/source/entity/hub/inbox/backlog stamps;
[`bank_index.py:49–56,119–122`](../../../api/services/bank_index.py#L49-L56)
still scans/stats files even with cached YAML.
[`sleep_debt.py:166,282–293`](../../../api/services/sleep_debt.py#L282-L293)
walks episodes again, with synchronous filesystem work occurring on the async caller
before the bounded git-history await. Unchanged clients duplicate the work.

**Measurement:** [the durable synthetic probe](repros/idle-sync.py), after three warmups,
25 samples, 1,900 entities, 20 hubs, 250 inbox items, 25 nudges and all episodes already
processed, measured the following on the audit machine:

| Episodes | Wall median / p95 | CPU median | Version median | Debt median |
|---|---|---|---|---|
| 2,000 | 23.00 / 26.23 ms | 22.64 ms | 15.76 ms | 7.04 ms |
| 10,000 | 81.00 / 97.74 ms | 79.45 ms | 43.22 ms | 37.76 ms |

An earlier synthetic series measured 16.72 / 18.57 ms and 63.51 / 67.25 ms respectively
(wall median / p95). These are local fixture timings, with ordinary run/setup variation,
not release targets. At one check per second, the durable probe's CPU work alone is about
2.3% / 7.9% of one core. It makes the reported API usage plausible in scale; it does not
attribute the user's 4% reading or include all endpoint/HTTP/subprocess work.

**Improvement / acceptance:** share a publisher per active bank rather than scanning per
subscriber; cache queue/debt inputs; combine writer invalidation and filesystem watching
with a bounded fallback scan for external edits. Move bounded filesystem work off the
event loop. Preserve SSE progress/keepalives, bank isolation, external markdown-edit
detection and disposable indexes. Compare no-change cost and client fanout, plus write
detection latency, against the same generated bank before and after.

### A11 — Walkthrough ignores the existing visibility and power policy

**Evidence:** [`ExportWalkthroughSheet.swift:23–25`](../../../app/CicadaApp/Sources/CicadaApp/Views/Onboarding/ExportWalkthroughSheet.swift#L23-L25)
always selects `frameInterval(lowPower: false)` and has no window-visibility reader.
[`ExportWalkthrough.swift:126–132`](../../../app/CicadaApp/Sources/CicadaApp/Support/ExportWalkthrough.swift#L126-L132)
intentionally repeats steps; under Reduce Motion the frame is static between step changes.

**Improvement / acceptance:** reuse the existing scene visibility and real low-power
policy; schedule reduced-motion step transitions rather than full-rate static frames.
Test window hiding/occlusion, power-policy changes and reduced-motion progression. The
looping tutorial is intentional; “animation never completes” is **not** a finding.
Existing painted scenes already have native visibility handling, so this does not justify
removing app artwork or assuming every TimelineView runs continuously in the background.

### A12 — Hidden or static sprites still have frame clocks

**Evidence:** [`MenuBarManager.swift:19–22,171–187`](../../../app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift#L171-L187)
changes status-item visibility without stopping its animation timer.
[`BookwormView.swift:88–91`](../../../app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift#L88-L91)
uses a periodic timeline even when reduced-motion frame selection stays at frame zero.

**Improvement / acceptance:** stop the sprite frame timer while its menu item is disabled,
continue receiving semantic status changes, and render the current state when re-enabled.
Use a static reduced-motion branch when the frame cannot change. Verify re-enable,
status changes while hidden and reaction behavior. This is a smaller wakeup optimization;
no claim is made that it explains the reported 55% drain.

## Existing backlog work confirmed, not new discoveries

| Item | Current evidence / constraint | Next step |
|---|---|---|
| **K01 — G114/G135 episode-ID collision (P1)** | [`episode_ids.py:70–85`](../../../api/services/episode_ids.py#L70-L85) scans max suffix without reserving it. [`mcp_tools.py:3115–3131,3165–3176`](../../../api/services/mcp_tools.py#L3115-L3131), [`episode_staging.py:447–463`](../../../api/services/episode_staging.py#L447-L463) and transcript capture do not share one cross-process allocation/write lock. A barrier-forced concurrent MCP capture and stager both returned success with the same ID, leaving one file instead of two. TODO already discloses this under G135. | Reconcile with G114/G135; use a shared per-bank cross-process allocation/dedup/write protocol or one writer. Test mixed channels and independent MCP processes. A thread-only lock is insufficient. |
| **G177 — remaining app guard** | [`ProjectMutations.swift:136–141`](../../../app/CicadaApp/Sources/CicadaApp/Sync/ProjectMutations.swift#L136-L141) still blocks on whole-run `status == running`; the backend's write-window predicate is narrower. | Finish the existing row, including the backend status field, ETag component and client mapping together. |
| **G148 — memory quality** | Benchmark work is already queued in TODO. Existing blockers include setup path/clock/engine pinning. | Fix the harness first; measure useful provenance, corrections and action support against no-memory/transcript baselines in throwaway banks. No paid benchmark was authorized or run by this audit. |

G109's existing Swift track needs its stale “rebuild on each tab switch” description
reconciled with the current persistent `GraphPage`; A07/A08 belong in that scope.
Do not duplicate known rows. G173's parked dedup concerns and G163's declined parallel
reading are not reopened here. No proposal requires replacing the markdown substrate,
adding a source-of-truth database, or changing scheduled-plan/spend rulings.

## Implementation order and completion bar

1. **Storage integrity:** A02 atomic replacement, A01 revision-safe retirement, and K01's
   existing allocation race. They share writer-boundary concerns but need separate tests.
2. **App energy:** A07 explicit graph lifecycle, A08 teardown and A09 interrupted gestures;
   profile before/after with identical synthetic data and record native window state.
3. **App consistency:** A03 stale reads, then A05/A06 source ordering and failure handling.
4. **Bank boundary:** A04 recursive symlink policy; give it a focused change and fixture set.
5. **API scaling:** A10 shared change detection and cached debt, with external-edit tests.
6. **Small animation savings:** A11/A12 after the larger sources of work are controlled.

Read the current `CLAUDE.md`, `docs/goals/TODO.md`, `memory-evolution.md`,
`working-method.md`, relevant architecture docs and design rules before implementing.
Revalidate against current `dev`; work in fresh isolated fix worktrees. Keep changes
focused and update affected architecture/backlog state. Finish meaningful regressions and
required verification before proposing a PR to `dev`. None of these recommendations
authorizes deployment, live-bank mutation, paid calls or promotion to `main`.
