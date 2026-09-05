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

1. **A plan exists before code.** One markdown plan per track under `docs/superpowers/plans/`,
   committed. It carries Global Constraints, numbered **Rulings** (decisions with their reason), a
   file map, and per-task Files / Interfaces / Steps with the *exact* code and the *exact* commands.
   No placeholders — "add appropriate error handling" is a plan defect, not a shortcut.
2. **A critic has read the plan against the code.** Every `file:line` the plan cites is opened and
   confirmed; every API it assumes is grepped; broken fixtures are fixed *in the plan* before an
   implementer ever runs.
3. **Each task is one reviewable commit** built test-first: write the failing test, watch it fail,
   implement, watch it pass, run the full suite, commit with the message the plan names.
4. **Each task is reviewed by a separate agent** that re-runs the tests itself rather than trusting
   the report, with a bounded fix loop (max 3 rounds) before it is recorded as unresolved.
5. **Two whole-branch lenses at the end** — correctness/regression and rails/privacy/docs — then one
   fix pass and a scoped re-review.
6. **The orchestrator verifies again** before merging: both suites, by hand, with the real numbers
   quoted in the PR.
7. **Docs move with the code.** CLAUDE.md for architecture and rails, the `G` row marked shipped with
   what stays open, `TODO.md` for state. A stale handoff is worse than none, because it is trusted.

### Test baselines (memorise these, they are not failures)

| Suite | Command | Expected |
|---|---|---|
| Backend | `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` | **0 failures**, 2014 passed (2026-09-03, PR #50) |
| App | `cd app/CicadaApp && swift test` | **0 failures** |
| Graph (JS) | `node --test app/CicadaApp/Tests/graph/*.test.js` | **0 failures.** Pass the glob, not the directory — a bare directory arg fails with a bare "test failed". |

**Every suite is green. Anything red is yours** — that was not true before PR #50, which removed the
last twelve expected failures. Two causes, both worth not reintroducing:

- **The developer's `api/.env` was leaking into the suite.** `litellm/__init__.py` calls `load_dotenv()`
  at import time, so the first test reaching `api.main` copied that machine's config into `os.environ`
  for the rest of the process, and every later bare `Settings()` read it. Order-dependent by
  construction: pass alone, fail in the run. A session fixture in `api/tests/conftest.py` drops those
  names now. Never assert on a bare `Settings()` expecting the developer's config.
- **Eight calendar tests were on a timer.** Their ICS fixtures carried fixed 2026-07 dates and fell out
  of the ±window about a month after they were written. They are built relative to today now, which is
  what a window test actually means. Use `_soon(days)`; pin a date only where the window boundary
  itself is under test (those pass their own `now` to `parse_ics`).

Still: do not trust a remembered count. Re-measure with `git stash` before blaming your own diff.

Anything else red is yours. Never `swift run` the app (bundle-less binary, window never becomes key);
`make dev` is the only correct launch.

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
- **Branching.** PRs open against `dev`. `main` is a manual, deliberate promotion. Devin's review
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
cd /Users/rorosaga/Documents/roros_lab/cicada
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

Verify both suites yourself → `git merge --no-edit origin/dev` in the worktree and resolve conflicts
(they are almost always `CLAUDE.md`, `TODO.md`, `memory-evolution.md`, and the telemetry kind tuples
where two tracks each added a kind — take the **union**) → push → `gh pr create --base dev` →
`gh pr merge --merge` → pull `dev` → replace `PR #TBD` in the docs → restart the backend
(`launchctl kickstart -k gui/$(id -u)/com.cicada.backend`) → `make dev` if Swift changed →
`git worktree remove` → update the handoff.

---

## 3. The queue

### Running now

**Nothing.** G115 Phase 1 merged as PR #48 on 2026-09-03 and the owner paused the queue there. The last
five tracks landed the same day: #44 evidence spans (G118 slice 1), #45 live state + handshake (G53/G75),
#46 deterministic capture (G105), #47 the Sources page (G124), #48 the inbox's first slice (G115).

### Next

**Nothing is scheduled.** The queue below is paused on the owner's instruction; each entry carries enough
to restart it cold. Start one by writing a brief from its entry and following §2.

### Paused, in the order they should resume

#### 1. G113 slices 3–7 — the grounded-reward ledger, half-built

**What shipped** (PR #31, `feat/feedback-ledger`): slice 1, every inbox resolution's commit trigger
names the action taken (`inbox/<kind>/resolved:<label>`, deferral stays `inbox/deferred`, decay
archive/keep land as `statusChange`); slice 2, a `resolution` telemetry event per resolve/defer with
the R3 verdict table (`agreed|overruled|neutral`), plus `audit` events from Stage-3 reconcile and
`dedup_verdict` per judged pair, all ids/enums only, all excluded from spend rollups
(`telemetry.FEEDBACK_KINDS`). So the system records verdicts today — and nothing reads them back.

**What remains, verified against `dev` on 2026-09-03** (do not trust the plan's own prose here, it
predates three merged tracks):

| Task | Still to do | Verified state |
|---|---|---|
| 3 | `divergence` + `normalization` become real inbox kinds, API **and** the Swift `InboxKind` enum in the same commit | **Not started.** `InboxKind` on `dev` is still `decay·conflict·clarification·merge_suggestion`; Sleep writes the other two and `load_inbox` silently drops them. |
| 4 | A rejected merge suggestion stays rejected — `<bank>/_merge_rejected.yaml` read by `clarification_manager.create` and `dedup_sweep`, plus a `reject` action and `cicada_resolve_inbox(reject=true)` | **Not started.** `api/services/merge_rejections.py` does not exist. |
| 5 | Decay `keep_active` and clarification free-text answers write back to the claim layer | **Half superseded.** G115 Phase 1 moves `remind_later` onto a real 7-day defer (the plan's `_defer(days=…, label=…)` half). What remains is only the claim write-back. |
| 6 | `consumption_stats.feedback()`, `ConsumptionFeedback` schema, `GET /consumption/feedback`, and the tile | **Not started, and its UI target moved.** The plan says "a fifth Usage tile"; G124 deleted `UsageView`/`UsageAdvancedView` and every price surface. The tile now goes in the named slot that already exists for it: `Views/Sources/AdvancedStatsView.swift` → `feedbackTileSlot` (currently `EmptyView()`), showing a **rate and counts, never a price**. |
| 7 | Docs: CLAUDE.md inbox kinds (six, not four), the ledger paragraph, the endpoint; G113 row shipped; TODO handoff | Follows 3–6. |

**Why it is worth finishing:** the ledger is the measurement half of "does extraction actually agree
with the person" (G78's prerequisite, G98's live number, and what makes a compiled skill's evidence
trustworthy in G112). Right now every verdict is written and none is legible.

**How to resume it.** The plan is already written and committed on the branch
(`docs/superpowers/plans/2026-09-02-g113-feedback-ledger.md`, tasks 1–7, rulings R1–R7 — R3 is the
verdict table, R5 puts merge rejection in a bank file, R7 keeps feedback rows out of connection
rollups). The worktree still exists at `.worktrees/g113` on `feat/feedback-ledger`, sitting where
PR #31 left it.

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113
git merge --no-edit origin/dev          # it is several tracks behind; expect doc + telemetry-tuple conflicts
```

then resume the run — tasks 1–2 replay from cache, work restarts at task 3:

```
Workflow({
  scriptPath: "~/.claude/projects/-Users-rorosaga-Documents-roros-lab-cicada--worktrees-g113/1d742a99-90a0-46a2-a0d9-4642052335bf/workflows/scripts/g113-feedback-ledger-wf_a38168f3-39b.js",
  resumeFromRunId: "wf_a38168f3-39b",
  args: { worktree: ".../.worktrees/g113",
          plan: ".../.worktrees/g113/docs/superpowers/plans/2026-09-02-g113-feedback-ledger.md",
          out: "<scratchpad>/g113",
          base: "78e9873" }
})
```

**Before restarting, patch the plan** (the critic pass is cached, so nobody will catch these for you):
task 6's Swift steps must target `AdvancedStatsView.feedbackTileSlot` rather than the deleted
`UsageView`, and task 5 must check what G115 already did to `_defer` instead of re-implementing it.
If a resumed cached task looks wrong against today's `dev`, prefer starting a fresh track with a
brief written from this table over fighting the cache.

#### The rest, in order

0. **G129 slice 2 — bookmark deletions.** Slice 1 shipped (PR #52): browsers are watched, a save
   reaches the queue in seconds, and each browser row has a status light. Slice 2 is the other
   direction — an unbookmark proposes a removal and waits for a keep/remove answer. Two rails are
   written on the row and both are correctness, not polish: the diff is only valid **inside the
   folder scope that was synced** (with `folders:` selection everything outside the chosen prefixes
   looks deleted), and it must be **browser-then vs browser-now, never browser vs memory**, or a
   bookmark the person chose to keep is re-proposed after every sync forever. That needs one small
   per-channel seen-set beside `url_index.json`. Removal is a proposal: an inbox item, rendered
   again as a Deletions subsection on the browser's page — one write path, two views.

2. ~~**G125 — Sleep page as the study desk.**~~ — **shipped 2026-09-05, PR #55**
   (`feat/study-desk`): the `reading` mascot state, a clock-free speech bubble, a book pile keyed on
   queued characters per source, the study list replacing the old queue card + debt breakdown, a
   server-parsed consolidation history with a per-cycle detail and telemetry-joined duration, and
   four schedule modes (manual · daily · every N hours · after imports). Open remainder, not this
   row: the same toolbar audit on Graph/Clusters, and **G122** (engine/model picker).
3. **G122 — engine and model picker on the Sleep page**, with Ollama guided as a first-class option.
   *Why here:* the ladder exists and works (`CICADA_LLM_MODE=auto` → Claude Max), but choosing it
   means editing `api/.env`. It is also step 1 of onboarding.
4. **G117 — first-run onboarding**, including capturing the owner's identity so the owner entity
   renders as *Name (you)* and replaces the last hardcoded observer literal. *Why here:* release
   blocker, and the owner plans a clean-install run to watch a new user's first hour.
5. **G126 — Settings → Integrations by category.** The page over the existing channel registry
   first, then adapters: YouTube subscriptions (Takeout, no key) → Strava (weekly aggregates only)
   → Todoist/Reminders → Garmin/Apple Health exports.
6. **G118 slice 2 — the provenance viewer.** Slice 1 shipped (PR #44): claims carry verified spans
   and `GET /episodes/{id}/span` serves the passage. The viewer is the half the owner actually asked
   for: click a belief, see the conversation with the cited sentence highlighted. *Why not sooner:*
   it is the largest UI surface of the four and wants the inbox card settled first (G115), since both
   render the same cause pane.
7. **G93 — cross-stream ask.** A question that spans conversations, links, calendar and notes, with
   span citations rather than page citations. Partly a DECIDE row: what "smart" adds over today's
   `/ask` is still open.

**Filed 2026-09-03, unqueued:** **G128** — visits and places as a capture channel, grounded in MemPal
(arXiv:2502.01801), whose transferable result is that *a text diary beat a spatial index*. First step is
the camera roll, not a wearable: time and GPS give the place, and on-device Vision gives what held you
there — OCR of the wall label first (in a museum the placard *is* the metadata), then scene labels,
feature prints for dedup and recurrence, faces detected but never identified. Apple's People API and
Visual Look Up are not available to third parties, so the equivalent is OCR plus the owner confirming
through the inbox. "Which artworks influenced me" then falls out of G120 recurrence + G118 provenance +
G66 decay rather than a new subsystem.

Then the standing bigger rocks, unchanged: **G81 → G95** (contacts, then meetings and human-to-human
conversations — the largest gap between the vision and the code), **G112 steps 2–4** (portable
skills), **G76** (paste-prompt install), **G127** (mascot identity — decide, don't build).

### Known-broken, small, unclaimed

- Ask panel and source-page chips now land on their node (G123 seam). The *other* places that open an
  entity from outside the canvas — if any get added — should call `revealEntity`, never `selectEntity`.

Closed 2026-09-03 (PR #49): the sidebar sun/moon toggle and the two origin-less source cards.
Closed 2026-09-03 (PR #51): the sidebar settings gear.
The toggle was not a palette problem — `CicadaTheme.mode` was a plain static, so flipping it changed
what every colour token returned but invalidated no view; only the two views reading the AppStorage
key repainted. It is backed by an `@Observable` store now, which also let the `.id()` rebuild go, so
a theme flip no longer tears down the graph's web view.

The gear next to it had a subtler version of the same shape. It sent the private selector
`showSettingsWindow:` through `NSApp.sendAction`, which on macOS 26 is **accepted and then ignored**:
the target is SwiftUI's own AppDelegate, the call returns `true`, and no window is created. The only
signal available to the caller said success. `SettingsLink` (macOS 14+, the documented way to open a
`Settings` scene) is what actually opens it — verified by firing the real control through a temporary
keyboard shortcut and watching the window list gain the scene. **The lesson worth keeping: a private
AppKit selector that still resolves is not evidence that it still works.** Two rules now have source
lints in `SettingsEntryPointTests`, because neither failure mode is unit testable.

---

## 4. Standing rulings that shape any new work

- **Provenance is the vision, not a feature** (owner, 2026-09-02). Spans, not copies; the contributor's
  reasoning is citable; the prompt that caused a write is part of the record. G118 is the spine.
- **World facts are a cache** (G121). A page is anchored on why it matters to the person; encyclopedia
  facts are dated, low-trust context an agent re-verifies. Not yet built.
- **No prices or tokens in the app** (G124, owner 2026-09-03). The `/consumption/*` endpoints and the
  ledger stay for later; the UI shows counts.
- **Capture is deterministic, not agent-judgment** (G105). The hook fires at session end; what is kept
  is a parser decision.
- **The inbox asks like Claude Code asks** (G115). One question object per item, the cause on the card,
  Sleep's proposal marked *(Recommended)*, never auto-applied.
