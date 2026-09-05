# Cicada — TODO & handoff

> **If you are an agent picking this project up cold, read this section first.** It is the
> compacted context of the 2026-08-31 → 09-03 sessions: what is true right now, what is in flight,
> the rulings that would be expensive to rediscover, and how work is run here.

## Where things stand (2026-09-04)

**Nothing is running. No open PRs. No worktree in flight except `.worktrees/g113`.** The owner
paused the queue on 2026-09-03; it is still paused deliberately.

**`dev` is ahead of `main`.** `main` was promoted at `381cfd3` (evening 2026-09-02); everything
since is on `dev` only. Merged since that promotion: **#40** G102 link summaries · **#44** G118
slice 1 (evidence spans) · **#45** G53+G75 (live state + handshake) · **#46** G105 (deterministic
capture) · **#47** G124 (Sources page) · **#48** G115 Phase 1 (inbox cause + Recommended) ·
**#49** theme toggle + `saved-link`/`rss` origins · **#50** the backend suite is green ·
**#51** the sidebar Settings gear · **#52** G129 slice 1 (browser bookmark watch).
**Per-PR detail is in git — `git log --oneline 381cfd3..dev` — not here.**

**Read [`working-method.md`](working-method.md) before starting anything.** It carries the bar, the
test baselines, the rails, the Workflow-track machinery, and the paused queue with its reasoning.
Do not re-derive the queue from this file.

### Live environment (verified 2026-09-04)

- **Backend** runs under **launchd** (`com.cicada.backend`, RunAtLoad + KeepAlive,
  `python -m uvicorn`). Restart it with
  `launchctl kickstart -k gui/$(id -u)/com.cicada.backend`.
- **Active bank** `claude-chats` — 1,866 entities, 1,396 episodes (`GET /healthz`; re-read it
  rather than trusting this number).
- **Keys** live in `~/.cicada/secrets.env` (0600). Never in a bank, never logged.
- **MCP** is registered at **user scope**, so every Claude Code session sees it. The G105 `Stop`
  hook is registered in `~/.claude/settings.json` — confirmed present.
- **Launching the app: `make dev`.** Never `swift run` — that produces a bundle-less executable
  whose window never becomes *key*, which silently breaks graph clicks and text-field focus. Run it
  from the repo root; `cd ..` from `app/CicadaApp` lands in `app/`, not the root.

**One manual step still outstanding on this machine:** the launchd plist predates G114 and its
`EnvironmentVariables` dict has no `CICADA_ALLOW_FEED_FETCH` (checked 2026-09-04 — still missing),
so the nightly feed/calendar poll logs `skipped: CICADA_ALLOW_FEED_FETCH is not "1"` every cycle.
`install.sh` only writes the plist when no backend answers `/healthz`, so it will not fix itself.
Add `<key>CICADA_ALLOW_FEED_FETCH</key><string>1</string>` to that dict, then
`launchctl bootout gui/$(id -u)/com.cicada.backend && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cicada.backend.plist`.

### Known and disclosed — open, not forgotten

- **Wikilinks (PR #29):** the client `sanitizeID` fallback still differs from the backend's
  `id_utils.sanitize_id`; `.wikilinkNavigation` traps if hosted outside a `WindowGroup` (it reads
  `@Environment(Store.self)`).
- **G109:** phase 1 shipped; phases 2–3, the Swift `WKWebView`-rebuild track, and the live-bank
  visual check are open — see the G109 row and Wave A.
- **Owner-present checks, none blocking:** the mascot visual pass in light and dark, the G109 graph
  eyeball at fit-zoom, the G124/G115 checks in their rows, the G129 status light and Sleep queue as
  rendered, and the README screenshots (G90), which must come from the **demo** bank, never the live
  one.
- **Parked review findings** that are real but deferred are listed per-area in the backlog rows they
  belong to; do not rediscover them.


## Rulings that cost real work to derive — do not re-litigate without reading them

1. **Decay charges once, and never for an outage.** Decay used to re-subtract the whole elapsed
   interval every run (proven: `octo.md` 0.85 → 0.4714 → 0.0928 in three commits *on one day*).
   Fixed with a `decayed_through` watermark + a per-cycle cap, plus a one-shot migration because
   the first cycle after the 75-day engine outage would have **archived 1,536 of 1,882 pages**.
   The principle: *an engine outage is a system failure, not user silence.* Migration has run;
   first-cycle archive count is now **0**, verified with a negative control.
2. **No relational tier** (G99). Measured, not assumed — three of four "SQL would fix this"
   arguments collapsed. Revisit only on the named triggers in that row.
3. **Markdown+git is the only source of truth.** A `.db` may exist only if deleting it costs CPU
   and never a fact, and **no derived artifact is ever tracked in a bank's git** (the 35 MB index
   was tracked and would have committed ~11 GB/yr once Sleep resumed).
4. **Scheduled cycles cannot spend plan quota.** `user_triggered` is threaded through; a scheduled
   cycle returns `byok` before the registry is touched. The UI copy says "never on the nightly
   schedule" and that is now literally true.
5. **Raw storage does not replace Sleep** (G101). Text cannot decay — only a belief can go stale or
   be contradicted — so "time as a signal" needs a belief object.
6. **Capture is agent-judgment and that is a measured problem** (G105): 0 MCP invocations in 12
   days; 4 episodes from one very long session. **Answered by the G105 hook (2026-09-03):** capture
   is now a property of the harness's Stop hook, not of a model's tool call — the MCP
   `cicada_save_episode` path stays as the deliberate, agent-chosen episode.
7. **The Stop hook, not SessionEnd, is the capture trigger** (G105 R1) — SessionEnd never fires for
   a closed window or a killed process and shares a 1.5 s budget; the endpoint's content-hash
   short-circuit makes per-turn firing idempotent. Revisit only if `capture.log` starts showing
   timeout `error:` lines (the hook's 3 s budget, `TIMEOUT_S` in `api/hooks/capture.py`) on the live
   bank — the hook logs no timing, so a blown budget surfaces as an `error:` line, not a latency figure.

## How work is run here

- **PRs merge to `dev`**; `main` is a manual promotion. Never commit directly to `dev` except docs.
- **Devin reviews are ignored (Rodrigo 2026-09-01: "from now on ignore them, they only slow us
  down").** Do not wait on a round, fix its findings, or reply to them. Merge on the session's own
  verification — an independent re-run of both suites plus a diff read. (The earlier one-round gate
  did catch real bugs — the stale drag-throw, three Sleep/Ask concurrency bugs, a re-import path that
  discarded save dates — so a reviewer of our own is worth keeping; Devin's latency is not.)
- **One writer per worktree.** Parallel work goes in `.worktrees/<name>` on its own branch. Never
  `git add -A` there (an untracked `api/.venv` symlink lives in each).
- **Verify, do not trust reports.** Run the suites yourself before merging. This session: an agent
  disclosed spawning a fork that wrote concurrently into a shared worktree; a test fixture encoded
  the same timezone bug as the code it tested; and a review predicted "0 deletions" that a sloppy
  `awk` made me briefly misread as 1,851. Independent checks caught all three.
- **Baseline:** 8 date-dependent `test_calendar_registry.py` failures are pre-existing on `dev`.
  Everything else must be green.
- Reports and briefs live in `.superpowers/sdd/<plan>/` (gitignored).

## Pick up here

**Nothing is running and nothing is queued to start.** The owner paused the queue on 2026-09-03 after
G115 Phase 1 landed. Everything about *what to do next and why* now lives in one place:

> **[`working-method.md`](working-method.md)** — the bar a change has to clear, the test baselines that
> are not failures, the rails, how to start / resume / land a Workflow track, and the paused queue with
> the reasoning for its order.

The queue there, in order: **G129 slice 2** (bookmark deletions — item 0, small) → **G113 slices 3–7** (the grounded-reward ledger, half-built — its entry carries
a per-task table verified against `dev` and the two places its committed plan is now stale) → **G125**
(Sleep as the study desk) → **G122** (engine/model picker) → **G117** (first-run onboarding) → **G126**
(Integrations page) → **G118 slice 2** (the provenance viewer) → **G93** (cross-stream ask). Then the
bigger rocks: **G81 → G95**, **G112 steps 2–4**, **G76**, and **G127** as a decision, not a build.

Owner-present checks still unticked, none blocking: the mascot visual pass in light and dark, the G109
graph eyeball at fit-zoom, the G124 and G115 checks in the paragraphs above, and the README screenshots
(G90), which must come from the demo bank rather than the live one.

**One manual step on any existing install:** re-run `./install.sh` (idempotent) so the G105 `Stop` hook is
registered in `~/.claude/settings.json`; `make doctor` check 12 confirms it. Done on the owner's machine.

**Worktrees:** only `.worktrees/g113` remains, holding `feat/feedback-ledger` (G113 slices 1–2 merged as
PR #31; slices 3–7 paused). Every other track worktree was removed after its PR merged. A worktree's
`api/.venv` is a symlink to the main checkout's. Never `--force`-remove one without reading
`git status --porcelain -uall` in it first, and never commit a `*-report.md` left there as scratch.

_Last synced: **2026-09-04**. Queue still paused. Merged since the last sync: #49 (theme toggle, origins), #50 (backend suite green), #51 (Settings gear), #52 (G129 slice 1). Backlog rows added: **G130** (app-wide ⌘+/⌘− zoom) and **G131** (replace the harness's auto-memory with Cicada). Next work and its reasoning: [`working-method.md`](working-method.md)._

## ✅ Shipped

Verified in code, not by checkbox.

**Foundations** — G1 memory banks · G3 feed page · G9 cross-harness origin provenance ·
G12 chat-history import · G17 deadlines-as-claims · G18 `directory` split · G20 delta re-import ·
G47 saved-content importer family · G58 sync engine

**Capture & connectors** — G29 Telegram · G30 browser bookmarks · G50 provider connections ·
**G71 save-with-reason + Imports catalog** (Pinterest/Reddit/X connectors, export preview,
LinkedIn/TikTok/Reddit parsers, one adapter registry) · **G105 hook-driven deterministic capture
(2026-09-03, PR #46)** — Claude Code `Stop` hook → `POST /capture/transcript`, block-level extractor
(person's turns + agent's final replies; tool blocks/code/secrets never), one episode per session
updated in place, Sleep-queue source marks (`OriginMark`)

**Memory model** — G60 conflict resolution with time-aware questions · G61 fact sources ·
G66 decay classes · A5 gap analysis · **G115 Phase 1 / G97 (2026-09-03)** — cause on the card,
Recommended, decay through the question component, the G98 informational rule

**App** — G23/G24/G25 media previews & hero · G26 light/dark · G27 local refs ·
G28 bookworm animation · G51 consumption dashboard · G52 Ask panel · G59 entity logos ·
G62 capture redesign · G63 connections clarity · G64 import walkthroughs · G67 commit-diff views ·
G68 UI round 2 · A1 per-commit diffs · A2 contributors · A3 ingestion animation · G15 avatars · G107 pixel mascot + single menu-bar Tamagotchi ·
**G125 the study desk (2026-09-05, PR #TBD)** — Sleep page rebuilt around a `reading` mascot state
and clock-free speech bubble, a book pile encoding queued characters per source (log scale, no
charts), a study list replacing the old queue card + debt breakdown, consolidation history with a
server-parsed per-cycle detail and telemetry-joined duration, four schedule modes (manual · daily ·
every N hours · after imports, always `user_triggered=False`), and the deprecated top-right
Sleep/Upload buttons removed from this page. **Disclosed gap:** `GET /status`'s `next_sleep` (the
one user-visible "Next run …" text, R6/R7) is calibrated from `sleep_debt.compute`'s
`last_cycle_at`/`newest_unprocessed_at`; `GET /state`'s own `sleep.next_at`
(`api/routers/state.py:100`, feeding the MCP handshake's now-view, not the app) is not — it calls
`sleep_scheduler.next_run_at` with neither, so `interval` mode reads "N hours from now" instead of
"N hours from the last real cycle" and `after_import` always reads `null`. Lower-stakes than the app
surface (an agent's primer briefly imprecise right after a schedule-mode change, never a wrong clock
shown to the user) and left as-is rather than adding a second `sleep_debt.compute` scan to an
engine-free read path on a late pass — fold in alongside the next `/state` touch.
· **G130 slice 1a app-wide zoom (2026-09-05,
PR #54)** — one persisted `uiScale` behind every `CicadaTheme` font/spacing token, a View menu
(⌘=/⌘−/⌘0, plus a ⌘⇧= key monitor), a Settings *General* tab with a text-size slider; the graph
canvas keeps its own zoom (slice 2 stays open on a measured need; slice 1b, the literal-font
migration + lint, is its own follow-up)

**Provenance** — **G48 conversation provenance + resume** (session stamping, `Cicada-Session:`
trailers, Ghostty resume) · **G118 slice 1 evidence spans (2026-09-03, PR #44)** — `Claim.evidence` offsets + hash, Stage-1 quote
verification, agent/Telegram/link-recon writers, `/episodes/{id}/span`; absorbs G100 (i)/(ii) ·
**G124 Sources page (2026-09-03, PR #47)** — Activity → Sources: card grid from /sources/overview,
per-source pages with Resume, contributors calendar per model, Advanced counts; prices/tokens out
of the app; **Track D (2026-09-05, PR #53)** — grouped-by-kind grid with real logos, G129 status
lights + hover quick actions, per-source blurbs, and a queue strip with Consolidate now
**G53 + G75 live state + handshake (2026-09-03, PR #45)** — `_state.md` cursor, `initialize.instructions`,
`cicada_handshake`, `/state`, `/handshake`

**2026-08-31 → 09-01 (PRs #21–#29, merged to dev)**
- #21 diff context lines with line numbers, merge-commit handling
- #22 the G71 slice + connector seam consolidation
- #23 G83 button hit areas & press feedback (87 sites), G84(a)(b) graph cold paint + drag physics
- #24 **the correctness gate** — decay charges once and never for the outage (first-cycle archive
  count **700 → 0** on the active bank), inbox subject gate, set-valued predicates, WAL, Telegram
  webhook secret (G57), bank-import honesty (G87 partial — the non-active-import warning; the
  BankSwitcher UI gaps it also found are still open), benchmarks import fix
- #25 **G74(a) agent engine** — Sleep runs on the user's Claude Max plan via `claude -p`, after
  ~2.5 months with no engine; round-1 Devin fixes (throttle breaker, concurrency cap, connector
  commit scoping) included
- #26 `saved_at` fix (G99d) — `RawItem.added` plumbed end to end across 5 parsers; re-import
  backfill + Pinterest date normalisation
- #27 sleep cancel route + episode cap + debt screen — Stage-2 writes queued and flushed only on a
  completed loop, so a cancel can no longer leave a half-deleted inbox item
- #28 **G88 dev loop** — `make install-app`/`make dev`/`make login-item`, non-destructive
  stage→verify→swap install with interrupted-swap recovery, and the app/agent bank split-brain
  closed at the source (`/healthz` `memoryRoot` overrides the local guess everywhere it is emitted)
- #29 wikilinks — render, click-through, back stack; refs resolved at click time against the graph
  snapshot, history committed only on an accepted destination, generation-token topic navigation
- Outside PRs: Cicada in **every** Claude session (user-scope MCP + both skills + launchd backend
  with durable keys), CLAUDE.md reframed twice (the project, then the *experience port* north
  star), doctor cleanup, installer shebang fix, **G99a** the 35 MB index untracked before it could
  commit ~11 GB/yr
- **G114 capture-writer hygiene** (`feat/capture-hygiene`, PR #30) — one id rule
  (`episode_ids.next_episode_id`, max-suffix+1 per date, importer collision closed), one timestamp
  shape (aware UTC from `episode_ids.utc_now_iso`; Sleep sorts by instant across legacy shapes),
  Telegram stamped with the message date and `/remind` an honest `capture_kind: reminder` note,
  feeds + calendars polled at the Sleep tail under `CICADA_ALLOW_FEED_FETCH=1` (a fresh
  install's plist sets it; an existing plist needs the key by hand — see Live environment), and
  a `processed_by: sleep|agent` stamp on `GET /sleep/episodes`
- Backlog hygiene (2026-09-01, docs-only): closed rows for work that had shipped without ever
  updating the backlog — **G21** dedup-sweep endpoint, **G19(e)(f)** provider-factory adoption +
  stray `.bak` removal, **A4** skill preference capture, and the shipped halves of **G11**
  (in-app preview), **G89** (feed following), **G93** (search/ask endpoints), **G87** (non-active
  import warning) — plus merged 9 duplicate/superseded rows and parked 2; see
  `memory-evolution.md` for the per-row evidence

**2026-09-02**
- **Safari import track** (`feat/safari-import`, PR #36) — Safari iCloud tabs (device picker),
  bookmark folder selection with tree preview (Reading List as its own folder), per-browser channels,
  the app reads `~/Library` and posts bytes (the launchd backend never could), Full-Disk-Access fix
  shown in place, and the `+` sheet re-layered into a logo-first family → member catalog with keyboard
  navigation. Follow-up: G119 (Arc/Firefox/Brave).
- **G109 phase 1** graph physics (PR #32) — alpha-scaled hub gravity, no reheat on release,
  `velocityDecay` 0.2 / `alphaMin` 0.001, per-isolate phyllotaxis slots, speed clamp; headless
  physics bench + test under `Tests/graph/`; numbers in the G109 row
- **G102 cheap slice** (PR #40) — link backfill on the Sleep tail + `POST /maintenance/enrich-links`; recon
  over stored OG text → `about` claims/edges through the existing Stage-1 prompt and Stage-2
  judgment; `GET /sources` `description`/`about`. Plan:
  `docs/superpowers/plans/2026-09-02-link-summaries-backfill.md`

---

## 🔄 In progress

| What | State | Next action |
|---|---|---|
| **G129 bookmarks** | **Slice 1 merged as PR #52** — file watch, catch-up sync, six-state light. Slice 2 (deletions) not started; its two correctness rails are in the G129 row | Slice 2, queued as item 0 in `working-method.md` §3 |
| **G74(a) agent engine** | **PR #25 — merged** (14 commits, `0fb0d38` round-1 Devin fixes included: Sleep/Ask share a throttle breaker, doubled concurrency cap, connector commits absorb a dirty tree), first-cycle archive re-verified at **0** with a negative control. Rung (b), the in-session agent path, is not built — G74 stays open in the backlog. | Run **one** cycle by hand. Do not enable a schedule. |
| **G109 graph physics** | **Phase 1 in PR #32** (2026-09-02): ruling = keep d3-force, fix `graph.js`; three commits + a committed bench, numbers in the row. Phases 2–3 and the Swift `WKWebView`-rebuild track are open | Merge after an independent re-run; live-bank visual check with Rodrigo; then the Swift track, then phase 2 |

---

## 🎯 Next — in priority order

### Wave A · finish what the engine needs
1. **G109 phases 2–3 + Swift track** — phase 1 shipped (see In progress). Next: the Swift track
   (`ContentView.swift:137-139` rebuilds the `WKWebView` per tab switch — the "explosion on
   return"; keep one alive, reset `isGraphReady` on teardown) — S; phase 2 (own the rAF loop with a
   physical settle criterion, `__cicadaPerf.report()`, live-bank tuning pass incl. the delta
   reheat / collide lever for the no-op-delta shuffle) — S/M; phase 3
   (isolates out of the simulation, tick 6.7 → 4.5 ms measured) — S
2. **G111** newsletters (TLDR / TLDR AI) → "what landed today that matters to me". The TLDR path
   is verified (RSS exists; a feed row per newsletter); the Sleep-tail feed poll it needed shipped
   with G114, so it refreshes without a button press — S/M
3. **G90** README + screenshots — Sleep and the dev loop are both real now; **demo bank or
   frame-by-frame review** — the live bank holds real people — S

### Wave B · make what exists trustworthy
4a. **G113 slices 1–4** — the grounded-reward ledger: every human verdict on memory (inbox resolve,
   decay keep/archive, merge accept/reject, `Cicada-Author: user` corrections) recorded as a
   telemetry event — ids and enums only, never text — with per-predicate agreement rates and a
   confidence-calibration curve as a tile in Sources ▸ Advanced (the `feedbackTileSlot`); R6
   (`remind_later → _defer(7)`) landed with G115 Phase 1. Slice 5 (feeding rates back into prompts)
   stays 💸 DECIDE under G78 — slices 1–2 merged (PR #31); 3–7 open — S/M
4d. ~~**G115 Phase 1**~~ *(owner 2026-09-03: start with the dead chevron and the unbounded URL list
   on cards)* — **shipped 2026-09-03 (`feat/inbox-phase1`)**
4d″. **G115 Phase 2 — suggested outcome** *(owner 2026-09-03)*: a confidence-gated one-sentence "Cicada thinks…"
    under the recommended option, accept with ⏎, never auto-applied; suggestion id + confidence in the G113
    ledger so agreement becomes a rate and a training set — S/M, after G118 slice 1 (needs the cause spans)
    + research-resolvable conflicts: the same judge may grep a linked repo / read a declared source and must
    cite what it checked; multi-valued predicates (`uses`) never open a conflict at all (G98)
4d′. ~~**G115 Phase 1**~~ — **shipped 2026-09-03 (`feat/inbox-phase1`)** — inbox redesign, first
   slice: one question object for every kind, `cause` on the
   card (three tiers, `[ no source recorded ]` served), `(Recommended)` = the option `_verdict` scores
   `agreed` (never on merge), decay through `QuestionView`, number keys / `Esc` no-trace skip, ETag
   widened server-side AND `.inbox` added to `VersionVector`'s `entities`/`episodes` in the same
   commit, `render_question` v2 with a `Cause:` line. $0, engine-free, 1–2 days, in parallel with
   G113 slices 3–7 (disjoint functions). Phase 2 (ask gate, `never` rules, observer capsule) after
   G113 3–4 and G106(i); Phase 3 (grouping, Sleep-counted silence-close, rule executor) after G116 — S/M
4. **G98 remainder** — the predicate/entity-resolution half (~15 of 27 conflicts are artifacts) — M
4b. **G104** a resumed conversation is consolidated twice — reconsolidation is the likely answer
   (the claim layer's `superseded_by` already models "replaced by a better-informed belief") — M
4c. ~~**G105** deterministic conversation extraction~~ — **shipped 2026-09-03** (`feat/deterministic-capture`,
   PR #46): the Stop hook, `POST /capture/transcript`, the block-level extractor and the Sleep-queue
   source marks; the open remainder (Cursor/other harnesses, Codex payload verification) is in the G105 row
5. ~~**G97**~~ — delivered by G115 Phase 1 (2026-09-03): inbox items show the conversation that caused
   them (43/49 reach an episode in ~100 ms, no LLM); the ETag widening shipped as both halves there. — S/M
6. **G82** hub pages are unaddressable — your "Couldn't load history"; 15 sites hardcode
   `entities/<id>.md`; both layers must move together — M
7. **G84(c)(d)** legend describes claim-context while nodes colour by type (byte-identical hexes),
   plus the observer relabel — S
8. **G86** feed dedup — 789 rows render 603 pages; absorbs G65 — M
9. **G19** dead-code sweep *((e)(f) done — provider factory adopted, stray `.bak` removed)* — XS
9a. **G112 step 1 ($0)** — ground the skill page: Stage-4 output through `entity_resolver`, merge
   `source_episodes` + bump `last_referenced` on update, evidence entities into `related`, v2
   layout so `source_rewrite`/hubs work, contradictions raise a normal conflict item. A bug fix
   in feature's clothing; steps 2–4 (compile → bundle → export) are Wave C — S

### Wave C · the north star's output half
9b. **G118 full provenance** — spans (not copies) on every claim, the contributor's rationale as a
    citable source, the prompt/turn that triggered every agent write, and a raw-source viewer with the
    cited passage highlighted (NotebookLM, but bi-temporal and attributed). Owner-marked central to
    the vision (2026-09-02). Slice 1 shipped (spans + agent citations + span endpoint, PR #44); next:
    slice 2 viewer (Swift `Evidence` model, chips → raw pane with highlight), then triggers (G105 shipped —
    unblocked),
    then rationale — L
9e. **G122 Sleep engine & model picker** — `GET/PUT /sleep/engine`, an Engine card on the Sleep page
    (Auto · Claude plan · Codex · Ollama · Key, live state + model, next-cycle preview), Ollama guided as a
    first-class option; prefs in `~/.cicada/connections.json`, never `api/.env` — M
9d. **G121 world facts vs personal facts** — `source_trust: model_knowledge` + volatile decay for anything not
    grounded in an episode, two-tier entity card ("why it's in your memory" / "context as of <date>, verify"), the
    rule in the G75 handshake; a dry-run backfill count on the live bank first — M
9c. **G93 cross-stream ask** — moved up (owner, 2026-09-02) beside G105, which has now shipped (4c above;
    ruled 2026-09-03: block-level extraction — the person's text turns + the agent's final reply per turn; tool
    blocks/code/secrets never; hook-driven): G105 is what makes every write have a cause; G93 is where citations
    become answers — M
10. ~~**G53 + G75** state dictionary + handshake — highest fan-out of anything unbuilt
    (G76, G77, G54 all assume it); zero LLM — M~~ — shipped PR #45 (`feat/state-handshake`); open:
    SessionStart hook (G49/G76), Store fetch of `/state`
11. ~~G100~~ — absorbed into G118 (slice 1 shipped the write-time citation; the derived-span class and
    the viewer are G118 slice 2)
12. **G103** observer model in the UI — whose belief, who was in the room — S
12c. **G108** landing page + navigation — decide *before* building: status vs graph as the front
    door, and linear vs browser-style history (G106 makes history the better bet) — decision
12b. **G106** two-way conversations ↔ entities browser — the inverse index works today; content
    search next; deep-linked snippets gated on G100 — M
13. **G93** cross-stream retrieval — the only row that advances the *unbuilt* half of the north
    star; everything above is intake or repair — L
13a. **G112 steps 2–4** — portable skills: a deterministic `skill_compiler` turns a grounded
    `skill` entity into a SKILL.md bundle with `## Evidence` (episode ids, agreement rates from
    G113), exported so someone else can load it on their own plan. WikiSkill's third layer — M
14. **G102** site recon — cheap slice shipped 2026-09-02 (see Shipped). Next slice: relate a link to a
    pending candidate when it promotes; fetch-side improvements stay out of scope until a measured
    need — S

### Wave D · new intake, in dependency order
14a. **G126** Settings → Integrations by category over the existing channel registry (page first), then
    adapters in this order: YouTube subscriptions (Takeout parser, no key) → Strava (OAuth, weekly aggregates)
    → Todoist/Reminders (tasks → G13) → Garmin/Apple Health exports — S/M + S–M each
15. **G81** contacts — identity anchors *(prerequisite for 16; absorbs G46)* — M
16. **G95** meetings & human↔human conversations — M/L
17. **G101** raw-conversation evidence layer — what to keep, what to discard — M
18. **G91** share-to-Cicada *(needs G88's signed app; absorbs G37)* — M
19. **G94** life-data streams — aggregates, never samples — L
19a. **G120** attention frequency — source attribution at ingest (channel/account/author), a rebuildable
    recurrence index, promotion to a `follows` claim that decays honestly, a "you keep coming back to"
    strip; feeds G111's ranking and G93's retrieval weight — M
20. **G76** effortless install + always-on capture — L
21. **G89** feeds first-class metadata *(feed-following already shipped via M4 — Substack needs no
    connector, just the (i)-(vii) metadata-quality work)* — S/M

### Wave E · thesis & product
22. **G78** gbrain evals — the thesis's weakest link is measurement, not architecture — M
22a. **G117** first-run onboarding in the app — **release blocker**: a three-step first-run sheet
    (engine → capture channel → first Sleep), honest empty states per tab, and a one-click synthetic
    demo bank so the graph is never blank. Ships with G76 and G90 for a downloadable 1.0 — M
23. **G92** onboarding at scale — decide what Cicada *is* before optimising a funnel — decision
24. **G72** skills manager *(owner 2026-09-03: two halves — skills Cicada compiled about you (G112) and the
    harness skills you actually use, ranked by the harness's own usage counters, adoptable into memory)* · **G73** prompt library · **G70** design memory *(absorbs G14)* — M each
25. **G54** onboarding interview · **G55** executable skills · **G13** tasks/ideas backlog

### Research / decisions (not builds)
- **G131** replace the harness's own auto-memory with Cicada — it is a per-project markdown graph with an
  always-loaded index (`~/.claude/projects/<cwd>/memory/`), i.e. `entities/` + `_state.md` built by someone
  else and invisible to the bank. Cicada wins on decay, provenance, contradiction handling and portability;
  auto-memory wins on zero-cost injection before the first token — which G75's handshake already solves.
  So the real question is what belongs in that slot besides the now-view (answer: the `feedback` category,
  i.e. G112). Measure the SessionStart-hook path and the token budget before writing code — M
- **G127** mascot identity — bookworm vs a friendly WALL·E-*inspired* librarian robot (never a copy of the
  character); prototype = three states behind a `mascot` setting, live with it a week, then rule — owner
  said document only for now (2026-09-03)
- **G99** relational tier — **DECLINED**; revisit only on a named trigger (warm p50 > 250 ms,
  claims > 25k, or a merged G94 adapter retaining raw samples). G99a (bank `.gitignore` for the
  vector index) has shipped; absorbs G96 (vector-as-entryway — validated, its storage question
  is what G99 answered).
- **G116** the inbox redesign's two contract rulings, needed before G115 Phase 3: (a) who authors a
  rule-executed Stage-5 write (recommended `cicada`, rule string in the manifest line — not yet
  ruled); (b) whether an in-conversation resolve carries `Cicada-Session:` on its `user` commit
  (recommended no — the session ref lives in the `resolution` ledger event; not yet ruled). $0.
- **G77** voice packets · **G10** bulk re-extraction *(re-filed 2026-09-01 — its D2 architecture
  gate is resolved; now purely a 💸 spend decision, read alongside G74/G80/G78)*

### Parked — no near-term work
- **G56** Cicada as MHS memory layer · **G16** shared memories + shared contributors

### Small & cheap — grab when passing
- **G130** app-wide zoom (⌘+ / ⌘− / ⌘0) — today only the graph *canvas* zooms; the chrome is fixed at
  `CicadaTheme`'s hardcoded font/spacing constants and the app defines no `.commands` at all, so the
  shortcut is unbound. Slice 1: a persisted `uiScale` the theme constants derive from (read through the
  `@Observable` store — a `static let` notifies nothing, and **no `.id()` on the root**, or every zoom step
  reloads the graph WKWebView, the exact regression PR #49 removed), a View menu `CommandGroup`, and a
  Settings slider beside appearance. Bind `=` and `+` both. Leave the graph canvas on its own zoom — S
- **G123** graph node search — shipped 2026-09-03 (PR #43); follow-up: route Ask citations and Sources
  entity chips through `revealEntity` so they land on the node too — XS
G7 centrality *(recommended for closing — "premise measured false" per a prior session, but this
hygiene pass could not find the underlying measurement anywhere in tracked docs; left OPEN — see
the report for what was checked)*

---

## 🩹 Known-broken, not yet queued
- Sidebar footer: the sun/moon button next to the gear writes `cicada.colorScheme` but the owner reports
  nothing happens on press (2026-09-03) — verify whether the scheme is applied at the root (`preferredColorScheme`)
  and whether the graph page (hard-coded dark d3 palette, see GraphView.swift comment) masks it — XS
- Graph re-lays out on every return to the Graph tab: `ContentView` rebuilds the `WKWebView` per
  tab switch *(G109 Swift track — Wave A #1; the physics half shipped in phase 1)*
- Bank `.git` is 69 MB against 16 MB of markdown — future growth stopped, **history not rewritten**
  (destructive; user's call)
- 8 date-dependent `test_calendar_registry.py` failures — pre-existing baseline on dev
- `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` fails when run
  with its own file, passes alone — order-dependent, pre-existing (seen 2026-09-02 on plain dev)
