# Working method + paused queue

> **For an agent picking this up cold.** [`TODO.md`](TODO.md) says *what the project's state is*.
> [`memory-evolution.md`](memory-evolution.md) says *why each idea exists*. This file says **how the
> work is actually run, what "done" means here, and what the queue is** — including the tracks that
> are deliberately paused and how to restart one. Written 2026-09-03, at the owner's request, so that
> a session that ends mid-flight loses nothing but time.

---

## 1. The bar

A change is not done when it compiles. It is done when **every one of these is true**, and the same
list is what a reviewer checks:

1. **A plan exists before code.** One markdown plan per track under `docs/plans/`,
   committed. It carries Global Constraints, numbered **Rulings** (decisions with their reason), a
   file map, and per-task Files / Interfaces / Steps with the *exact* code and the *exact* commands.
   No placeholders — "add appropriate error handling" is a plan defect, not a shortcut.
2. **A critic has read the plan against the code.** Every `file:line` the plan cites is opened and
   confirmed; every API it assumes is grepped; broken fixtures are fixed *in the plan* before an
   implementer ever runs.
3. **Each task is one reviewable commit** built test-first: write the failing test, watch it fail,
   implement, watch it pass, run the test files of the modules it touched plus their direct callers and
   `make test-crucial`, commit with the message the plan names (see *Test tiers* below).
4. **Each task is reviewed by a separate agent** that re-runs the tests itself rather than trusting
   the report, with a bounded fix loop (max 3 rounds) before it is recorded as unresolved.
5. **Two whole-branch lenses at the end** — correctness/regression and rails/privacy/docs — then one
   fix pass and a scoped re-review.
6. **The orchestrator verifies again** before merging: `make test-crucial` and the touched files, by hand, with the
   real numbers quoted in the PR. The full suites run once before each release.
7. **Docs move with the code.** The area's doc in `docs/architecture/` for how a subsystem works (updated in the
   same PR that makes it wrong), `CLAUDE.md` only when a *rail* changes — one or two lines pointing at the doc; it is
   loaded into every session and `test_claude_md_size.py` fails above 60,000 characters (2026-10-01: it had grown to
   203,000 by carrying every feature's detail) — the `G` row marked shipped with what stays open, `TODO.md` for state.
   A stale handoff is worse than none, because it is trusted.

### Test baselines (memorise these, they are not failures)

| Suite | Command | Expected |
|---|---|---|
| Crucial tier | `make test-crucial` | **0 failures** — 247 backend tests in ~16 s, 47 Swift tests in ~4 s (+ build), 2026-10-19 |
| Bench tier | `make test-bench` | 12 tests, ~50 s, 2026-10-19: **1 known failure**, `test_projects_bench.py` (the 2,500-page project list's p95 is ~230 ms against its 80 ms budget; it was an unrun `CICADA_BENCH=1` opt-in until the marker). Run on a quiet machine |
| Backend | `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` | October 5 audit on `4264e297`: 6,016 passed, **1 known G185 failure**, 1 skipped; rerun for the change |
| App | `cd app/CicadaApp && swift test` | **0 failures** |
| Graph (JS) | `node --test app/CicadaApp/Tests/graph/*.test.js` | **0 failures.** Pass the glob, not the directory — a bare directory arg fails with a bare "test failed". |

**Current disclosed backend failure is G185** ([audit status](audit-2026-10-05/STATUS.md)); do not hide it or classify an unrelated regression as expected. Counts above are dated reported evidence. PR #50 removed the old twelve failures, including the following causes:

- **The developer's `api/.env` was leaking into the suite.** `litellm/__init__.py` calls `load_dotenv()`
  at import time, so the first test reaching `api.main` copied that machine's config into `os.environ`
  for the rest of the process, and every later bare `Settings()` read it. Order-dependent by
  construction: pass alone, fail in the run. A session fixture in `api/tests/conftest.py` drops those
  names now. Never assert on a bare `Settings()` expecting the developer's config.
- **Eight calendar tests were on a timer.** Their ICS fixtures carried fixed 2026-07 dates and fell out
  of the ±window about a month after they were written. They are built relative to today now, which is
  what a window test actually means. Use `_soon(days)`; pin a date only where the window boundary
  itself is under test (those pass their own `now` to `parse_ics`).
- **The suite wrote into the developer's real `~/.cicada` (2026-10-19).** The per-test `CICADA_HOME` covered only
  a test's own body: a `monkeypatch.undo()` mid-test (nine files), a module-scoped fixture, a thread outliving its
  test or a hook subprocess fell back to `~/.cicada` — write-admission locks (`sleep/<bank>-<hash>/admission.lock`),
  hook hints, the image cache, telemetry. `conftest.py` now pins `HOME` and `CICADA_HOME` for the whole process to a
  session tmp dir before anything is imported; `test_suite_home_isolation.py` holds it. A scratch HOME on the command
  line is still good practice, no longer the only guard.

### Test tiers (owner 2026-10-19: "only crucial stuff")

The Mac is shared, and the full suites cost ~22 min (10,065 backend tests, measured file by file 2026-10-19) plus
~3.5 min of Swift. So the work runs in three tiers, plus the benchmarks:

- **Every change:** the test files of the modules it touched plus their direct callers (grep for the imports), and
  `make test-crucial`. Never the whole backend suite, never `swift test` unfiltered — `swift test --filter
  '\.(ClassA|ClassB)/'`. Niced (`nice -n 10`), one run at a time, no parallel suites.
- **Daily / before a PR:** `make test-crucial` — the tests that guard CLAUDE.md's rails, ~20 s of tests in all.
  The lists are `api/tests/crucial.txt` (the `crucial` pytest marker is put on what it names, so `pytest -m crucial`
  selects the same set) and `app/CicadaApp/Tests/crucial-tests.txt` (joined into one `--filter` regex), each grouped
  by the rail a test guards. `test_crucial_tier.py` fails when a line names a test that no longer exists, and pins the
  rails that are numbers (the 1,800-token handshake, the ToS rail's 4 s / 512 KB).
- **Before a release:** `make test` — every backend and Swift test, benchmarks included (`-o addopts=""`), once, by
  the coordinator.
- **Benchmarks (`bench` marker):** a wall-clock budget (search, the SessionStart route, hook recall, the project list,
  the inbox at the owner's scale, a slow registry) or a benchmark-harness run. They flake on a busy Mac, so
  `api/pyproject.toml`'s addopts (`-m 'not bench'`) leaves them out of every default run, a bare `pytest` on their
  file included; `make test-bench` (`-m bench`) runs them alone on a quiet machine. A later `-m` replaces the addopts,
  so `-m crucial` selects exactly the crucial list, and `conftest.py` refuses a crucial line that names a `bench` test:
  a rail's guard asserts behaviour, never a stopwatch. A new wall-clock assertion is `@pytest.mark.bench` (the old
  `CICADA_BENCH=1` opt-in is gone).

**Keeping the suite cheap (suite cuts, 2026-10-19).** A test that needs the demo scenario takes
`_demo_scenario.demo(tmp_path, …)`: a copy of a template built once per process for those flags (only the determinism
tests call `build`). An expensive fixture bank is built once per module and copied per test (`test_cli_app.py`'s
`_template`). A fake HTTP server polls at 10 ms (`serve_forever(poll_interval=0.01)`): the default 0.5 s is paid on
every `shutdown()`. Checks that mirror each other across connectors, registries or writers are one parametrized test.

**Joining the tier.** A test joins when it is the strongest guard of a rail CLAUDE.md states and no listed test already
guards it — one strong test per rail, not a file's worth. A new rail adds its line in the same PR. A test leaves only
with the rail. Speed is a tiebreak, never the reason.

Do not trust a remembered count. Compare the same command on a clean baseline in an isolated checkout when attribution is needed; preserve shared staged/unstaged work.

Any additional failure needs attribution against the current baseline. Never `swift run` the app (bundle-less binary, window never becomes key);
`make dev` is the only correct launch of the person's own app.

**Verifying a change end to end (2026-10-22).** `.claude/skills/verify-cicada/` runs the backend, the MCP server, a
Sleep cycle (Claude plan, haiku), the CLI and a second copy of the app (its own bundle id) on scratch state, never
touching the live install, and keeps a feature map of every user-facing feature with its recipe. Use it instead of
driving the person's app or backend.

**A Swift test that hangs inside an AppKit render is the machine, not the test (2026-10-20).** The first layer-backed
`NSView` in an `xctest` process runs `+[NSApplication initialize]`, which opens the general pasteboard over a
synchronous XPC call. When the system's `pboard` daemon is wedged (seen 2026-10-20: its general-pasteboard queue blocked
waiting on a remote pasteboard item's data), every such test waits forever: `ClustersGridTests` and `EntityHeaderTests`
(a picture's drop target is an AppKit view) and every `NSHostingView` render. The same tests pass in under a second once
`pboard` answers. Check before chasing it: `perl -e 'alarm 10; exec @ARGV' /usr/bin/pbpaste >/dev/null; echo $?` —
`142` means the pasteboard does not answer. The person restarts it (`launchctl kickstart -k gui/$(id -u)/com.apple.pboard`,
or logs out and back in); a worker never kills a process it did not start.

### Rails that override convenience

- **Privacy.** Nothing personal in `docs/goals/`, plans, commit messages or PR bodies: no other
  people's names, no episode or inbox titles, no quoted claim text, no URLs or handles. The owner's
  own ideas *are* the intended voice of the backlog. Fixtures use `alpha-project`, `bob-example`,
  `example.com`.
- **The bank is never read by a build agent.** `memory/`, `~/.cicada` and `~/.claude/projects` are
  off limits to planners, implementers and reviewers. The orchestrator measures the live bank when a
  brief needs a number, and passes the number in.
- **Transcripts.** Only the deterministic capture path (G105) reads a transcript, at the block level:
  the person's text turns and the agent's final reply per turn. Tool blocks, code and secrets never
  enter a bank.
- **Telemetry is ids and enums.** Never claim text, never answer text. Nothing learned from the
  ledger is auto-applied.
- **Sleep-safety.** Read paths are engine-free; no LLM at capture time; the engine-independent tail
  runs behind the clean-tree guard.
- **ETag ship-together.** A payload that gains a field fed by a new file needs the server component
  *and* the Swift `VersionVector` mapping in the same commit, or the app serves stale data forever.
- **Portability.** No owner name, no author-machine path in shipped code. (Committed plans currently
  do carry the worktree path — a known, disclosed inconsistency, not a licence to add more.)
- **Branching.** PRs open against `dev`. A release is a `dev` → `main` PR whose merge publishes it (TODO ruling 19). Devin's review
  comments are ignored by standing instruction (2026-09-01).

---

## 2. The machinery

Work runs as a **Workflow track**: one git worktree, one branch, one plan, agents doing
plan → critic → commit → (implement → review → fix)×N → two-lens final review → fix → re-review.

The reusable script is:

```
~/.claude/projects/-Users-rorosaga-Documents-roros-lab-cicada/1d742a99-90a0-46a2-a0d9-4642052335bf/workflows/scripts/track-plan-build-wf_bc906a18-ee3.js
```

It takes `args`: `{worktree, branch, base, name, planFile, fixTag, out, swift, python, brief}`.
The **brief** is the whole input — it names the rows to read, states what already exists with
verified anchors, lists what to build, and ends with the rails and an explicit "not in scope". A
brief that says "improve the inbox" produces nothing; a brief that says "close these two defects,
here are the file:line anchors, here is the ruling" produces a mergeable branch.

### Starting a track

```sh
cd <your cicada checkout>
git worktree add -q .worktrees/<name> -b feat/<branch> dev
ln -s "$PWD/api/.venv" .worktrees/<name>/api/.venv     # the venv is not per-worktree
mkdir -p "<scratchpad>/<name>"
```

Then call `Workflow` with the script path above and the args.

### Resuming a stopped track

A run stops for one reason in practice: the session or model limit. Completed agents are cached, so:

```sh
cd .worktrees/<name> && git stash -u          # implementers BLOCK on a dirty tree
```

then `Workflow({scriptPath, resumeFromRunId: "<run id>", args: <the same args>})`. Drop the stash
afterwards — it is a half-written task the resumed agent redoes from scratch.

### Landing a track

Verify the crucial tier and the touched files yourself → `git merge --no-edit origin/dev` in the worktree and resolve conflicts
(they are almost always a `docs/architecture/` doc, `TODO.md`, `memory-evolution.md`, and the telemetry kind tuples
where two tracks each added a kind — take the **union**) → push → `gh pr create --base dev` →
`gh pr merge --merge` → pull `dev` → replace `PR #88` in the docs → restart the backend
(`launchctl kickstart -k gui/$(id -u)/com.cicada.backend`) → `make dev` if Swift changed →
`git worktree remove` → update the handoff.

---

## 3. The queue

**Current execution order lives only in [TODO.md](TODO.md), updated 2026-10-06.** Detailed reasoning is in [memory-evolution.md](memory-evolution.md); completed scopes are in [DONE.md](DONE.md). The earlier round-2/round-3 paused queue is historical and remains in git, not a parallel list of next work.

Start from the named remaining scope in TODO, reproduce it against current `dev`, then use the method above. Preserve safe capture/write/consolidation while progressing the owner’s delivery deadline and hands-on memory trial; CLI and headless packaging follow. The owner’s explicit delivery priority for 2026-10-06 is G182: working releases, automatic release/main/website alignment and every-integration post-consolidation read/contribution checks, with applicable integrity/release gates. Selected iMessage capture (G179, minimal G188 source/detector seam) and rebuilding whole-system benchmarks from scratch (G148) are now P1 alongside trial/continuity work. Broader frontend/backend provider and source modularity is P2 with Cursor/headless work. Cross-model skills, design/mascot and sharing follow TODO order. Full-dataset comparisons and model changes follow the small system pilot; the full harness does not gate a hands-on trial.

## 4. Standing rulings that shape any new work

- **Provenance is the vision, not a feature** (owner, 2026-09-02). Spans, not copies; the contributor's
  reasoning is citable; the prompt that caused a write is part of the record. G118 is the spine.
- **World facts are a cache** (G121). A page is anchored on why it matters to the person; encyclopedia
  facts are dated, low-trust context an agent re-verifies. Not yet built.
- **No prices or tokens in the app, except on the Sleep page's Details and its engine menu** (G124, owner
  2026-09-03; narrowed by TODO ruling 12, 2026-09-28). Nowhere else: every other surface shows counts. There,
  a figure is measured or a list price and states its basis in words. The `/consumption/*` endpoints and
  the ledger are unchanged.
- **Capture is deterministic, not agent-judgment** (G105). The Stop hook fires after each completed agent reply; what is kept
  is a parser decision.
- **The inbox asks like Claude Code asks** (G115). One question object per item, the cause on the card,
  Sleep's proposal marked *(Recommended)*, never auto-applied.
- **Cicada never asks an agent to do what it may not do itself** (G61 phase 2, D-AC2). The ToS rail binds
  Cicada's own bytes; an agent in the person's own session is the person reading (the G140 precedent).
  Cicada never spawns, schedules or drives a browsing agent, never relays a credential, never searches
  for a person, and gives no `Check first:` line for a host it refuses to fetch (`_excluded_media`,
  `papers.never_scraped`).

## Implementation versus backlog labels (2026-10-06)

Use [the per-ID implementation review](BACKLOG_IMPLEMENTATION_REVIEW.md) before choosing a row. It separates implemented slices, missing workflows, acceptance and conditional/declined work. TODO is the execution order; earlier progress labels are history. Confirm relevant current call paths before reopening an audit fix or moving a whole idea to DONE.
