# Cicada — TODO & handoff

> **If you are an agent picking this project up cold, read this section first.** It is the
> compacted context of the 2026-08-31/09-01 session: what is true right now, what is in flight,
> the rulings that would be expensive to rediscover, and how work is run here.

## Where things stand (2026-09-01)

**Merged to `dev`:** PRs #21–#26. The big one is **#25 — the agent engine (G74a)**: Sleep can now
run on the user's Claude Max plan via `claude -p`, after ~2.5 months with no engine. Also #24, the
**correctness gate**, which fixed decay (see rulings below), #23's app fixes, and #26's `saved_at`
fix (re-import backfill + Pinterest date normalisation).

**Also merged:** **#27** sleep cancel/cap/debt screen — Devin round 1 (1 🔴 + 5 🟡) fixed and
round 2 came back **clean**. Its 🔴 is worth knowing: Stage 2 used to make clarifier/index writes
*inline* inside the per-name judging loop, so cancelling mid-Stage-2 left partial writes — including a
**deleted** inbox item. Writes are now queued as callables and flushed only if the loop completes.

**Open PRs — both mid-flight, resume here:**

- **#29 wikilinks** (`feat/wikilink-nav`, worktree `.worktrees/wikilinks`) — renders/clicks/back-stack,
  424/424 green, **verified independently**. Devin left **3 🟡, no 🔴**, all unaddressed:
  (i) `MarkdownBody.swift` — punctuated wikilinks sanitize to ids that target nonexistent entities;
  (ii) `GraphViewModel.swift:420` — a broken link still pushes onto the back stack, creating false
  history; (iii) `TopicsView.swift:725` — a late topic load undoes navigation. **Decide whether to fix
  or merge with them filed** — (ii) is the one a user would actually feel.
- **#28 dev loop** (`feat/devloop`, worktree `.worktrees/devloop`) — **fix round COMPLETE** (`688fb5f`,
  pushed); `swift test` 414/414, `pytest` 1525 passed (8 pre-existing calendar failures). **Awaiting a
  Devin round 2**, warranted because round 1 carried a 🔴. Both findings fixed:
  - **🔴 bank split-brain, closed as a class rather than as a path.** The bug: after a default install
    outside `~/cicada`, `installRoot` pointed agent setup commands at the *checkout's* memory while the
    app used another bank — silent, because memory gets written and the app just shows nothing. The root
    cause was **two independent computations that had to coincidentally agree** (a Swift heuristic vs.
    `install.sh`/`Settings` defaults). Now there is one source of truth: `GET /healthz` reports
    `memoryRoot` (raw `Settings.memory_root`/`CICADA_MEMORY_PATH`, distinct from the resolved-active-bank
    `memoryPath` it already returned), and when the backend answers, that **overrides the local guess
    everywhere** `CICADA_MEMORY_PATH` is emitted — every agent's steps, the shared `mcpJSON`, the Cursor
    deeplink — not just the line Devin flagged. `installRoot()` survives only as a fallback until a
    backend has ever answered, and still supplies `home` (python/mcp-server paths), where a wrong value
    fails loudly instead of diverging silently. **Verified live**, not argued: a temp backend was pointed
    at the main checkout's memory and the running app's Connect page showed the backend's real root
    instead of the worktree-derived guess it would have shown before.
  - **🟡 destructive update** (`install_app.sh`) — now stages, verifies, then swaps, with the old bundle
    recoverable. **Proved by injecting two failures:** a `codesign` that always fails aborted *before
    quitting the running app* (checksum/signature/PID untouched), and an `mv` that failed only the
    staging→installed move restored the previous app byte-identically. A normal `make dev` afterwards ran
    clean with no leftover `.staging`/`.previous`.

**Live environment (verified):** backend runs under **launchd** (`com.cicada.backend`,
RunAtLoad+KeepAlive, `python -m uvicorn`), keys in `~/.cicada/secrets.env` (0600). Cicada's MCP
server is registered at **user scope** so every Claude Code session sees it, both skills are in
`~/.claude/skills/`, and **Claude Desktop is registered** (needs a Desktop restart). Active bank:
`claude-chats`, 1,731 entities.

**How to run the app:** `make run-app` (NOT `swift run` — that produces a bundle-less executable
whose window never becomes *key*, which silently breaks graph clicks and text-field focus).

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
   days; 4 episodes from one very long session.

## How work is run here

- **PRs merge to `dev`**; `main` is a manual promotion. Never commit directly to `dev` except docs.
- **Devin gate: one round.** Fix round-1 findings, then merge. A second round only after a
  High/Critical. Docs-only PRs skip it. Devin has been consistently worth it — it caught the stale
  drag-throw, three Sleep/Ask concurrency bugs, and a re-import path that discarded save dates.
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

**Session paused 2026-09-01 on usage limits, mid-flight. Nothing is broken; two PRs are unfinished.**

1. **Merge #28 once its Devin round 2 clears** — the fix round is done, pushed and live-verified
   (details above); nothing to re-dispatch. A round 2 is owed only because round 1 had a 🔴.
2. **Rule on #29's three 🟡** (above), then merge. No 🔴; it is mergeable as-is if the calls are filed.
3. **G109 (urgent)** — graph physics: deceleration is tuned invisible and disconnected nodes explode
   into a ring; evaluate Obsidian/Pixi, cosmograph, sigma+graphology rather than re-tuning blindly.
4. **G110 is filed as RESEARCH, deliberately not started.** Its own cheapest-first ruling: build
   **G53**/**G75** (state dictionary + handshake — a curated cursor with no transcript read) and see
   whether the fork want survives, rather than building fork machinery first.
5. **G7 is open again, on purpose.** The hygiene pass could not find the measurement TODO.md claimed
   ("premise measured false") anywhere in tracked history — it was likely eyeballed on the live
   (gitignored) bank and never written down. Either re-measure it or delete the claim; do not
   re-close it on the strength of the old assertion.
6. Then the waves below.

**Worktrees left in place** (all with committed, pushed work): `.worktrees/wikilinks`,
`.worktrees/devloop`, `.worktrees/sleepctl`, `.worktrees/hygiene`. `git worktree list` to see them.

---


The **execution view**. [`memory-evolution.md`](memory-evolution.md) stays the reference: it holds
the full reasoning, evidence and file:line for every row. This file answers one question only —
*what is done, what is moving, and what is next.*

**Rule:** every row here is a pointer. Add detail to the backlog row, not to this file.

_Last synced: 2026-09-01 (hygiene pass + G110 filed; PRs #21–#27 merged, #28/#29 open and mid-flight)._

---

## ✅ Shipped

Verified in code, not by checkbox.

**Foundations** — G1 memory banks · G3 feed page · G9 cross-harness origin provenance ·
G12 chat-history import · G17 deadlines-as-claims · G18 `directory` split · G20 delta re-import ·
G47 saved-content importer family · G58 sync engine

**Capture & connectors** — G29 Telegram · G30 browser bookmarks · G50 provider connections ·
**G71 save-with-reason + Imports catalog** (Pinterest/Reddit/X connectors, export preview,
LinkedIn/TikTok/Reddit parsers, one adapter registry)

**Memory model** — G60 conflict resolution with time-aware questions · G61 fact sources ·
G66 decay classes · A5 gap analysis

**App** — G23/G24/G25 media previews & hero · G26 light/dark · G27 local refs ·
G28 bookworm animation · G51 consumption dashboard · G52 Ask panel · G59 entity logos ·
G62 capture redesign · G63 connections clarity · G64 import walkthroughs · G67 commit-diff views ·
G68 UI round 2 · A1 per-commit diffs · A2 contributors · A3 ingestion animation · G15 avatars

**Provenance** — **G48 conversation provenance + resume** (session stamping, `Cicada-Session:`
trailers, Ghostty resume)

**This session (PRs #21–#26, merged to dev)**
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
- Outside PRs: Cicada in **every** Claude session (user-scope MCP + both skills + launchd backend
  with durable keys), CLAUDE.md reframed, doctor cleanup, installer shebang fix,
  **G99a** the 35 MB index untracked before it could commit ~11 GB/yr
- Backlog hygiene (2026-09-01, docs-only): closed rows for work that had shipped without ever
  updating the backlog — **G21** dedup-sweep endpoint, **G19(e)(f)** provider-factory adoption +
  stray `.bak` removal, **A4** skill preference capture, and the shipped halves of **G11**
  (in-app preview), **G89** (feed following), **G93** (search/ask endpoints), **G87** (non-active
  import warning) — plus merged 9 duplicate/superseded rows and parked 2; see
  `memory-evolution.md` for the per-row evidence

---

## 🔄 In progress

| What | State | Next action |
|---|---|---|
| **G74(a) agent engine** | **PR #25 — merged** (14 commits, `0fb0d38` round-1 Devin fixes included: Sleep/Ask share a throttle breaker, doubled concurrency cap, connector commits absorb a dirty tree), first-cycle archive re-verified at **0** with a negative control. Rung (b), the in-session agent path, is not built — G74 stays open in the backlog. | Run **one** cycle by hand. Do not enable a schedule. |
| **G88 dev loop** | Restarts clean (stopped mid-build, nothing committed) | `make install-app`, `make dev`, `installRoot()` fix, README run-section |
| Claude Desktop | **Registered 2026-09-01** — needs a Desktop restart | Then: it captures only what an agent chooses to save (see G105) |

---

## 🎯 Next — in priority order

### Wave A · finish what the engine needs
1. **Engine follow-up: episode cap + cancel route** — today the only way to stop a running cycle is
   killing the backend, and a kill mid-write leaves a dirty bank the next cycle mis-attributes.
   *Blocks any unattended cycle.* — S
2. **G88** run Cicada like an installed app *(in progress)* — S
2b. **G109 🔴** graph physics — deceleration invisible (velocityDecay 0.45 + alphaMin 0.05 swallow
   the seeded throw) and zero-degree nodes fly to a ring now that the cold-paint fix renders them;
   evaluate an established engine instead of re-tuning — S/M to decide, M to port
3. **G90** README + screenshots. Blocked on #1 so Sleep is shown working; **demo bank or
   frame-by-frame review** — the live bank holds real people. — S

### Wave B · make what exists trustworthy
4. **G98 remainder** — the predicate/entity-resolution half (~15 of 27 conflicts are artifacts) — M
4b. **G104** a resumed conversation is consolidated twice — reconsolidation is the likely answer
   (the claim layer's `superseded_by` already models "replaced by a better-informed belief") — M
4c. **G105** deterministic conversation extraction — stop capture depending on a model choosing to
   call a tool (measured: 4 episodes from one long session, 0 MCP calls in 12 days). Includes
   source logos in the Sleep queue — S/M
5. **G97** inbox items show the conversation that caused them (43/49 reach an episode in ~100 ms,
   no LLM). Ship the ETag widening in the same commit or the app caches stale context forever. — S/M
6. **G82** hub pages are unaddressable — your "Couldn't load history"; 15 sites hardcode
   `entities/<id>.md`; both layers must move together — M
7. **G84(c)(d)** legend describes claim-context while nodes colour by type (byte-identical hexes),
   plus the observer relabel — S
8. **G86** feed dedup — 789 rows render 603 pages; absorbs G65 — M
9. **G19** dead-code sweep *((e)(f) done — provider factory adopted, stray `.bak` removed)* — XS

### Wave C · the north star's output half
10. **G53 + G75** state dictionary + handshake — highest fan-out of anything unbuilt
    (G76, G77, G54 all assume it); zero LLM — M
11. **G100** span citation — which *sentence* convinced the contributor, rendered in a
    DiffView-style source viewer with prev/next across conversations — M
12. **G103** observer model in the UI — whose belief, who was in the room — S
12a. **G107** tamagotchi status mascot — state machine is done, the ART is the work (the current
    sprite is a 16px monochrome menu-bar template scaled to 72pt); time estimates deferred until
    the engine model is settled — M
12c. **G108** landing page + navigation — decide *before* building: status vs graph as the front
    door, and linear vs browser-style history (G106 makes history the better bet) — decision
12b. **G106** two-way conversations ↔ entities browser — the inverse index works today; content
    search next; deep-linked snippets gated on G100 — M
13. **G93** cross-stream retrieval — the only row that advances the *unbuilt* half of the north
    star; everything above is intake or repair — L
14. **G102** site recon → entities, not summaries. Cheap first slice: extract over the OG text
    already stored, zero new fetches — S/M

### Wave D · new intake, in dependency order
15. **G81** contacts — identity anchors *(prerequisite for 16; absorbs G46)* — M
16. **G95** meetings & human↔human conversations — M/L
17. **G101** raw-conversation evidence layer — what to keep, what to discard — M
18. **G91** share-to-Cicada *(needs G88's signed app; absorbs G37)* — M
19. **G94** life-data streams — aggregates, never samples — L
20. **G76** effortless install + always-on capture — L
21. **G89** feeds first-class metadata *(feed-following already shipped via M4 — Substack needs no
    connector, just the (i)-(vii) metadata-quality work)* — S/M

### Wave E · thesis & product
22. **G78** gbrain evals — the thesis's weakest link is measurement, not architecture — M
23. **G92** onboarding at scale — decide what Cicada *is* before optimising a funnel — decision
24. **G72** skills manager · **G73** prompt library · **G70** design memory *(absorbs G14)* — M each
25. **G54** onboarding interview · **G55** executable skills · **G13** tasks/ideas backlog

### Research / decisions (not builds)
- **G99** relational tier — **DECLINED**; revisit only on a named trigger (warm p50 > 250 ms,
  claims > 25k, or a merged G94 adapter retaining raw samples). G99a (bank `.gitignore` for the
  vector index) has shipped; absorbs G96 (vector-as-entryway — validated, its storage question
  is what G99 answered).
- **G77** voice packets · **G10** bulk re-extraction *(re-filed 2026-09-01 — its D2 architecture
  gate is resolved; now purely a 💸 spend decision, read alongside G74/G80/G78)*

### Parked — no near-term work
- **G56** Cicada as MHS memory layer · **G16** shared memories + shared contributors

### Small & cheap — grab when passing
G7 centrality *(recommended for closing — "premise measured false" per a prior session, but this
hygiene pass could not find the underlying measurement anywhere in tracked docs; left OPEN — see
the report for what was checked)*

---

## 🩹 Known-broken, not yet queued
- No episode cap / no cancel route on a running cycle *(Wave A #1)*
- Bank `.git` is 69 MB against 16 MB of markdown — future growth stopped, **history not rewritten**
  (destructive; user's call)
- 8 date-dependent `test_calendar_registry.py` failures — pre-existing baseline on dev
