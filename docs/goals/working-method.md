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

**Nothing.** Round 2 (2026-09-05 evening → 09-06) landed as PRs #63–#69 on opus Workflow tracks —
the owner allowed opus for that session; **the standing rule is still small models unless the owner
says otherwise** — using `track-opus.js` in the session scratchpad (the same plan → critic →
implement/review → two-lens shape, `model: 'opus'` on the plan/implement/review agents and `'sonnet'`
on the mechanical ones). Its shape and the phase-1 method (six readers → three designers → two
judges → one spec) are recorded in the round-2 spec's preamble. The orchestrator plans, verifies and
merges; agents never push.

### Next

**G90 README screenshots** from the demo bank (an hour, no track needed), then **G118 slice 2 — the
provenance viewer** (item 6 below), then **G93** (item 7), then the bigger rocks. Start a track by
writing a brief from its entry and following §2.

### Done on 2026-09-05, kept here for the reasoning

#### 1. ~~G113 slices 3–7 — the grounded-reward ledger, half-built~~ — **shipped as PR #59**

Resumed from the committed plan with the stale anchors patched by the critic (task 5's
`remind_later` half had shipped with G115, task 6's tile target moved to `AdvancedStatsView.
feedbackTileSlot`). Six inbox kinds now load and resolve, a rejected merge stays rejected
(`<bank>/_merge_rejected.yaml`), decay `keep_active` and clarification answers reach the claim layer,
and `GET /consumption/feedback` + the Feedback tile make the ledger legible — rates and counts, never
a price. Slice 5 (feeding rates back into prompts) stays 💸 DECIDE under G78. The old resume-from-cache
instructions are gone with the worktree: a fresh track from the plan is the way to continue anything
here.

#### The rest, in order

0. ~~**G129 slice 2 — bookmark deletions.**~~ — **shipped 2026-09-05** (PR #61,
   `feat/bookmark-deletions`): the seen-set + diff, the `removal` inbox kind (`keep`/`remove`,
   always `neutral` — the proposal is the browser's), and the browser page's own Deletions
   subsection. Open remainder, not this row: G119 (more browsers).

2. ~~**G125 — Sleep page as the study desk.**~~ — **shipped 2026-09-05, PR #55**
   (`feat/study-desk`): the `reading` mascot state, a clock-free speech bubble, a book pile keyed on
   queued characters per source, the study list replacing the old queue card + debt breakdown, a
   server-parsed consolidation history with a per-cycle detail and telemetry-joined duration, and
   four schedule modes (manual · daily · every N hours · after imports). Open remainder, not this
   row: the same toolbar audit on Graph/Clusters. **G122** (engine/model picker) shipped separately,
   below.
3. ~~**G122 — engine and model picker on the Sleep page**, with Ollama guided as a first-class
   option.~~ — **shipped 2026-09-05** on `feat/settings-redesign` (Track C, PR #60): the prefs-first
   `GET/PUT /sleep/engine` ladder rung, the Sleep page's `EngineCard` (segmented picker over Claude
   plan / Ollama / a key, Codex disabled), and both `preview.manual`/`preview.scheduled` lines shown
   rather than hiding ruling 4. Codex as a selectable engine stays open under G49.
4. ~~**G117 — first-run onboarding**, including capturing the owner's identity so the owner entity
   renders as *Name (you)* and replaces the last hardcoded observer literal.~~ — **shipped
   2026-09-05** on `feat/onboarding` (PR #62): `owner_identity.resolve_observer` replaces the
   hardcoded literal at all five sites, `GET/PUT /settings/owner` + the owner entity page, the
   four-step first-run sheet (reusing G122's `EngineCard` and G126's `IntegrationsView` as steps 1
   and 2), honest empty states per tab, a deterministic demo bank, and the three install/copy gaps
   named below. Open remainder: the onboarding *interview* (G54); entity-merge-across-identity-change
   (R3's disclosed gap).
5. **G126 — Settings → Integrations by category.** ~~The page over the existing channel registry
   first~~ — **page shipped 2026-09-05** on `feat/settings-redesign` (Track C, PR #60):
   categorized, logo-first rows over `GET /sources/channels`, connect/disconnect via a
   `ConnectorSetupPanel` popover, and a one-shot import still routed to the Feed's `+`. **Adapters
   remain open**, in order: YouTube subscriptions (Takeout, no key) → Strava (weekly aggregates
   only) → Todoist/Reminders → Garmin/Apple Health exports.
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
