# Cicada audit handoff prompt

Paste the following into a new coding session rooted at the Cicada repository. It
authorizes implementation when the owner uses it; this documentation pass itself did
not implement fixes. If the audit files are still uncommitted, read them in the existing
audit worktree before creating fix worktrees; do not discard or reset that worktree.

```text
Continue the Cicada code/performance audit documented in
<repo>/.worktrees/audit-2026-10-02/docs/goals/audit-2026-10-02/.

Read README.md, VALIDATION.md and this HANDOFF.md there first. The report was audited
at 9f7d8f5ba19f3a399543cf63f9c843ad319591e6 on branch audit-2026-10-02. Audit docs and
synthetic probes may be uncommitted. Preserve them and all main-checkout changes.
Inspect current dev and revalidate each finding before implementing it; line numbers
and branch/PR status may have changed. Work in separate focused fix worktrees.

Read applicable AGENTS.md/CLAUDE.md, docs/goals/TODO.md, memory-evolution.md,
working-method.md, relevant architecture docs and docs/design/DESIGN_RULES.md.
Follow current instructions for reviews/delegation; the audit used sequential review.
Reconcile findings with existing G rows before adding permanent IDs. In particular:
G109 keeps d3-force; G114/G135 already disclose the capture allocation race; G177
owns write-window guards; G148 owns benchmark quality work. Do not reopen parked or
declined G163/G173 decisions without their recorded trigger.

Implement in focused batches, each with a concrete plan/review, regression reproduction,
fix, verification and updated architecture/backlog state:
1. Storage integrity: A02 atomic markdown replacement; A01 revision-safe episode
   retirement; K01 shared cross-process per-bank allocation/dedup/write protocol.
   Atomic replacement, revision checks and unique ID allocation are separate guarantees.
2. App energy: A07 graph visibility/occlusion suspension and bounded visible pulses;
   A08 weak web-view ownership and explicit teardown; A09 interrupted-drag cleanup.
   Preserve zoom/positions, normal throws, capture, SSE and menu-bar state. Stop both
   RAF and d3 timers while inactive; do not reheat on release/resume without need.
3. App consistency: A03 stale entity reads; A05/A06 source-edit ordering and draft/error
   handling. A04 symlink-safe duplication should be its own focused bank-boundary fix.
4. API efficiency: A10 shared/cached change detection, with external-edit and fanout
   tests. Then A11/A12 animation clock savings, preserving intentional visible motion.

The CPU report (~55% app/WebKit, ~4% API, “41 hours”) is not confirmed live evidence.
The scheduler loop and WebKit ownership pattern were reproduced; actual hidden-window
WebKit frame delivery, process ownership, process age and CPU attribution were not.
The user approved Activity Monitor inspection, but the tool still rejected it; ps was
sandbox-blocked. Retry permitted profiling if available, following VALIDATION.md's
matrix. Use generated data first. CPU Time is cumulative CPU, not elapsed runtime.
Do not attribute unrelated WebKit services to Cicada or promise a measured reduction
without a comparable before/after trace. Keep unresolved profiling clearly labeled.

Run durable probes under docs/goals/audit-2026-10-02/repros/ from the audit worktree
using an existing API virtualenv, then turn diagnostic bug outputs into positive
regression tests in fix branches. Use only synthetic temporary banks/homes, disable
capture/automatic fetches and dotenv, and make no paid model calls. Do not inspect
private banks/transcripts or mutate the installed app/live backend for convenience.

Baseline: full API 5868 passed/9 failed/1 skipped, not green. Two failures resolved
with the correct script interpreter; four listener tests were socket-blocked; one
latency failure passed alone; the usage join passed with fixed Git dates; the local
provider-default/catalog mismatch remains. Full Swift built but stopped in clipboard
testing (permission failure/signal 5), not a completed pass. Selected sync/source tests
30/30 passed, selected animation/drop tests 35/35 passed, graph suites 8/8 passed.
Recheck meaningful affected tests and full required checks when permissions allow.
Document real failures instead of declaring them environmental or loosening thresholds.

The public repo must contain no personal bank content, titles, claims, people, URLs,
contact details or owner-machine paths. Use synthetic placeholders. Keep filesystem
markdown/git as source of truth and indexes disposable. Ship any new API/ETag component
with its Swift mapping. Capture continues during Sleep; scheduled plan/spend rulings
and the unified writing-window predicate remain binding.

Complete each selected batch before moving on; update the audit finding's status with
fix revision, meaningful test evidence and profiling limits. Prepare reviewable changes
for dev; no deployment, paid calls, live-bank migration, push or promotion to main
without the owner's instruction. Finish with completed IDs, remaining IDs, exact test
results, measured CPU/resource changes and the next handoff.
```
