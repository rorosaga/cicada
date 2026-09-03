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
| Backend | `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` | **8 failed** — all date-dependent in `test_calendar_registry.py` |
| Backend, order-dependent | same | `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` fails when run with its file, passes alone. Pre-existing. |
| App | `cd app/CicadaApp && swift test` | **0 failures** |

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

| Track | Branch / worktree | Run id | State |
|---|---|---|---|
| **G115 Phase 1** — inbox redesign | `feat/inbox-phase1` · `.worktrees/g115` | `wf_baa1ec4d-f07` | Plan written (5 tasks); critic and tasks in flight. First attempt died on a model limit with the plan already written; resumed on Opus. |

### Next, then stop

| Track | Branch / worktree | How to resume | Why it is next |
|---|---|---|---|
| **G113 slices 3–7** — grounded-reward ledger | `feat/feedback-ledger` · `.worktrees/g113` | `git merge --no-edit origin/dev` in the worktree, then resume run `wf_a38168f3-39b` with script `…--worktrees-g113/…/workflows/scripts/g113-feedback-ledger-wf_a38168f3-39b.js` and args `{worktree, plan: docs/superpowers/plans/2026-09-02-g113-feedback-ledger.md, out: <scratchpad>/g113, base: 78e9873}`. Tasks 1–2 replay from cache; work resumes at task 3. | Slices 1–2 shipped (PR #31): resolutions already name their action and emit a `resolution` event. Slices 3–7 close the loop — divergence/normalization kinds, sticky merge rejection, claim write-back for keep/answer, `GET /consumption/feedback`, docs. Without them the ledger records verdicts nobody can read. |

**After G113 merges, nothing else starts.** The queue below is paused on purpose (owner, 2026-09-03).

### Paused, in the order they should resume

1. **G125 — Sleep page as the study desk.** A `reading` mascot state while intake is being consumed,
   the queue as a per-category study list (Claude Code conversations · Safari tabs · saved links…),
   breakdowns moved to Sources/Settings, a schedule frequency picker, the deprecated toolbar buttons
   removed. *Why here:* it is the page the owner watches while the bank fills, and G105 now feeds it
   real per-source volume.
2. **G122 — engine and model picker on the Sleep page**, with Ollama guided as a first-class option.
   *Why here:* the ladder exists and works (`CICADA_LLM_MODE=auto` → Claude Max), but choosing it
   means editing `api/.env`. It is also step 1 of onboarding.
3. **G117 — first-run onboarding**, including capturing the owner's identity so the owner entity
   renders as *Name (you)* and replaces the last hardcoded observer literal. *Why here:* release
   blocker, and the owner plans a clean-install run to watch a new user's first hour.
4. **G126 — Settings → Integrations by category.** The page over the existing channel registry
   first, then adapters: YouTube subscriptions (Takeout, no key) → Strava (weekly aggregates only)
   → Todoist/Reminders → Garmin/Apple Health exports.
5. **G118 slice 2 — the provenance viewer.** Slice 1 shipped (PR #44): claims carry verified spans
   and `GET /episodes/{id}/span` serves the passage. The viewer is the half the owner actually asked
   for: click a belief, see the conversation with the cited sentence highlighted. *Why not sooner:*
   it is the largest UI surface of the four and wants the inbox card settled first (G115), since both
   render the same cause pane.
6. **G93 — cross-stream ask.** A question that spans conversations, links, calendar and notes, with
   span citations rather than page citations. Partly a DECIDE row: what "smart" adds over today's
   `/ask` is still open.

Then the standing bigger rocks, unchanged: **G81 → G95** (contacts, then meetings and human-to-human
conversations — the largest gap between the vision and the code), **G112 steps 2–4** (portable
skills), **G76** (paste-prompt install), **G127** (mascot identity — decide, don't build).

### Known-broken, small, unclaimed

- Sidebar sun/moon toggle: writes `cicada.colorScheme` and the root applies `preferredColorScheme`,
  but the owner reports nothing happens. Suspect the theme's own dark palette masks it. XS.
- `files` and `rss` source cards cannot attribute their items until three writers stamp an `origin`
  (`POST /sources/save`, `cicada_save_url`, the RSS poll). One line each. XS.
- The order-dependent provenance test above.

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
