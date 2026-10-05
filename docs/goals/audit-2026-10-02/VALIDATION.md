# Validation record and reproducible probes

Revision and scope are recorded in [the audit](README.md). All fixtures were synthetic;
the live memory bank and private transcript directories were not used. Raw test output
remained in temporary local storage and is not copied into public documentation. The
results below distinguish application defects, test setup issues and sandbox limits.

## Existing suite results

| Check | Result | Limit |
|---|---|---|
| Full `api/tests` | **5,868 passed, 9 failed, 1 skipped**; 580.09 s | Not a green baseline; failure breakdown below |
| Graph Node suites | **8 files passed, 0 failed**; 25.81 s | Existing physics harness stubs requestAnimationFrame as a no-op |
| Full Swift suite | Built, then stopped in clipboard testing with signal 5 after pasteboard access failure | Full suite did not complete; permission cause should be retested outside restricted environment |
| `StoreTests\|EntitySourceWriteTests` | **30 passed, 0 failed**; 3.95 s | Existing tests do not cover all adversarial ordering cases in A03/A05 |
| `PaintedSceneTests\|ExportWalkthroughTests\|BookwormViewTests\|GraphDropTests` | **35 passed, 0 failed**; 0.16 s | Pure policy/geometry tests do not measure live rendering or occluded CPU |

Full API failure classification:

- **Two script tests:** `test_backlog_import.py::test_the_script_runs_twice_and_the_second_run_changes_nothing`
  and `test_check_census.py::test_the_script_prints_the_census_and_refuses_a_non_bank`
  selected a fallback interpreter lacking `loguru`, because the worktree had no API
  virtualenv. Both passed when the existing API virtualenv's `bin` led `PATH`.
- **One catalog mismatch:** `test_byok_providers.py::test_every_default_is_a_model_litellm_knows_with_structured_output`
  still failed in isolation: a configured `openrouter/~openai/gpt-mini-latest` default
  was absent from the installed LiteLLM catalog. This establishes a local default/catalog
  mismatch, not that a provider rejects the model. Verify the configuration/catalog
  relationship before changing a production default; no paid request was made.
- **One clock-dependent fixture:** `test_cycle_usage.py::test_history_and_detail_join_usage_from_the_ledger`
  joins fixed September 29 telemetry to a commit created with the current October 2
  date. It failed alone, then passed with both Git author/committer dates pinned to
  September 29. Fix fixture clock control; no production usage-loss finding is made.
- **Four listener tests:** `test_remote_listener.py` failed because socket operations
  were not permitted, including binding to loopback. They need an environment that
  permits the test listener; their outcomes do not establish a listener implementation bug.
- **One latency test:** `test_search_latency.py::test_prefix_mode_stays_within_budget_with_a_staleness_scan_on_every_request`
  measured p95 **51.7 ms** against a **50 ms** budget in the full run, then passed alone.
  Keep the signal for a stable performance run; do not treat one marginal result as an
  architecture verdict or silently raise the threshold.

The five non-socket failures were rerun with the correct interpreter environment:
three passed and two remained (catalog mismatch and clock fixture). The clock-pinned
follow-up passed. No blanket assertion that all failures were environmental is warranted.

## Running the durable diagnostics

Run from the **audit worktree root**. If its API virtualenv is absent, explicitly set
`AUDIT_PYTHON` to the existing checkout's API virtualenv interpreter; do not install or
upgrade dependencies solely to rerun this audit. Each Python probe sets synthetic
`CICADA_HOME` and bank paths before importing application code and cleans up its fixture.
These commands do not start the API, capture hooks or a Sleep model run.

```sh
AUDIT_PYTHON="${AUDIT_PYTHON:-$PWD/api/.venv/bin/python}"
PYTHONDONTWRITEBYTECODE=1 "$AUDIT_PYTHON" docs/goals/audit-2026-10-02/repros/storage.py
node docs/goals/audit-2026-10-02/repros/graph-loops.cjs
PYTHONDONTWRITEBYTECODE=1 "$AUDIT_PYTHON" docs/goals/audit-2026-10-02/repros/idle-sync.py
```

Observed outputs on the pinned code:

```json
{"finding":"A01","selected_contains_correction":false,"new_revision_marked_processed":true,"remaining_queue":0}
{"finding":"A02","old_file_preserved":false,"bytes_remaining":20}
{"finding":"A04","external_file_copied":true,"copied_alias_is_symlink":false}
```

For A07: no-pending case renders one frame and has no queued frames left. Both pending
cases render 120 frames and retain one queued frame at alpha zero, including the
synthetically hidden document. For A09: `draggingStillActive = true`, `alphaTarget = 0.1`,
`alphaAfter400Ticks = 0.09999999987713105` after omitting mouseup.

The graph probe drains a mocked callback queue, not a real display. Its drawing context
is a no-op. A09 deliberately constructs the interrupted condition; it does not establish
that the OS loses the event in ordinary interaction. These diagnostics describe the
audited bugs; **convert them to positive regression assertions when implementing fixes**.
They are not a substitute for actual wrapper/lifecycle integration tests.

On macOS with local WebKit permitted, compile and run the ownership probe:

```sh
swiftc -module-cache-path /private/tmp/cicada-audit-module-cache \
  docs/goals/audit-2026-10-02/repros/webkit-retention.swift \
  -o /private/tmp/cicada-audit-webkit-retention
/private/tmp/cicada-audit-webkit-retention
```

All four statements printed `true`: view and handler remained after external owners
dropped, then both released after breaking the cycle. It uses a nonpersistent data
store and loads no page. It proves the ownership pattern, not the number of currently
leaked Cicada windows or their CPU consumption.

`idle-sync.py` generates banks of 2,000 and 10,000 processed episodes with 1,900 entities,
20 hubs, 250 inbox entries and 25 nudges, then reports 25 warmed samples. It calls the
same `sync_service.version` and `sleep_debt.compute` used by SSE, without HTTP, actual
SSE fanout or a real git history. Timing includes local filesystem/host variation;
numbers are in README and must not be presented as measurements of the live API.

## Existing-suite reproduction environment

Use an empty **temporary** home/bank, disable capture and automatic fetches, and bypass
dotenv loading. Do not point these checks at the person's bank or use actual credentials.

```sh
AUDIT_SCRATCH="$(mktemp -d /private/tmp/cicada-audit-suite.XXXXXX)"
export CICADA_HOME="$AUDIT_SCRATCH/home"
export CICADA_MEMORY_PATH="$AUDIT_SCRATCH/bank"
export CICADA_CAPTURE=off PYTHON_DOTENV_DISABLED=1 CICADA_API_AUTH=off
export CICADA_ALLOW_CONNECTOR_FETCH=off CICADA_ALLOW_FEED_FETCH=off CICADA_ALLOW_LOGO_FETCH=off
export PYTHONDONTWRITEBYTECODE=1
export PATH="$(dirname "$AUDIT_PYTHON"):$PATH"
"$AUDIT_PYTHON" -m pytest api/tests -q -p no:cacheprovider
node --test app/CicadaApp/Tests/graph/*.test.js
```

Clock-fixture diagnostic, using the same environment:

```sh
GIT_AUTHOR_DATE=2026-09-29T10:00:00Z GIT_COMMITTER_DATE=2026-09-29T10:00:00Z \
  "$AUDIT_PYTHON" -m pytest \
  api/tests/test_cycle_usage.py::test_history_and_detail_join_usage_from_the_ledger \
  -q -p no:cacheprovider
```

Swift selected-suite command, from `app/CicadaApp` with temporary module/scratch caches:

```sh
CLANG_MODULE_CACHE_PATH=/private/tmp/cicada-audit-clang-cache \
SWIFTPM_MODULECACHE_OVERRIDE=/private/tmp/cicada-audit-swift-cache \
  swift test --disable-sandbox --scratch-path /private/tmp/cicada-audit-swift-build \
  --filter 'StoreTests|EntitySourceWriteTests'
```

Use the animation/drop filter from the table for the second selected run. Disabling
SwiftPM's nested sandbox does not grant permissions denied by the enclosing environment;
it did not make clipboard access, sockets, `ps` or Activity Monitor available here.

## Live CPU investigation still required

The user approved Activity Monitor inspection, but the computer-use tool rejected
access. No process CPU samples, Instruments trace, process-age evidence, live frame-rate
measurement or WebKit ownership mapping were collected. No live app was restarted,
installed, force-quit or reconfigured for profiling.

Use an instrumented build and a generated bank first. Record OS/hardware, build revision,
graph resource hash, bank size, pending-node count, power/Reduce Motion policy and the
actual native visibility state. Keep raw process samples local; public reports contain
only sanitized function/process metrics, never bank text or personal paths.

1. Identify Cicada, its **owned** WebKit processes and the API by process lineage. A
   `com.apple.WebKit.WebContent` label alone is insufficient to assign ownership. Record
   PID and start/elapsed time separately from cumulative CPU time.
2. Collect several timestamped CPU observations over at least 60 seconds per condition,
   after startup and graph settling. Prefer a 120-second trace where feasible. Report
   mean/range or distribution and sampling interval, not a single screenshot.
3. Compare graph foreground with no pending node, graph foreground with a pending node,
   another tab, covered graph, minimized window, hidden app and fully occluded window.
   Changing selected tab, opacity, browser page visibility and native occlusion are
   distinct states. Include repeated close/reopen cycles and interrupted drag.
4. Profile app main-thread/SwiftUI work, WebContent JavaScript/canvas and any owned WebKit
   GPU/network services separately. Inspect whether `scheduleRedraw`/`draw`, force ticks,
   sprite clocks or SwiftUI updates dominate. Count live graph instances on recreation.
5. Profile the API with zero, one and multiple SSE subscribers using the same synthetic
   bank. Distinguish version/debt scans from capture, scheduled jobs and other traffic.
6. Repeat the identical cases after each lifecycle fix. Record whether the exact reported
   drain reproduces and how much each change reduces it; retain any unexplained residual.

Do not obtain apparent savings by disabling capture, abandoning SSE correctness,
breaking menu-bar state, replacing d3-force or changing Sleep's write-window/spend rules.
The measured post-fix target should be chosen from an idle baseline on the target Mac;
the audit does not invent a guaranteed CPU reduction percentage.
