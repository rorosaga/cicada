# Cicada — TODO & handoff

> **If you are an agent picking this project up cold, read this section first.** It is the
> compacted context of the 2026-08-31/09-01 session: what is true right now, what is in flight,
> the rulings that would be expensive to rediscover, and how work is run here.

## Where things stand (2026-09-01)

**Merged to `dev`:** PRs #21–#25. The big one is **#25 — the agent engine (G74a)**: Sleep can now
run on the user's Claude Max plan via `claude -p`, after ~2.5 months with no engine. Also #24, the
**correctness gate**, which fixed decay (see rulings below), and #23's app fixes.

**Open PRs:** **#26** `saved_at` (Devin round in flight — re-import backfill + Pinterest date
normalisation) and **#27** sleep cancel/cap/debt screen (Devin round running). **`feat/devloop`**
(G88 `make install-app` / `make dev`) is being built, not yet a PR.

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

1. Merge #26 and #27 once their Devin rounds clear.
2. Finish **G88** (`feat/devloop`) — the one-command dev loop.
3. **G109 (urgent)** — graph physics: deceleration is tuned invisible and disconnected nodes
   explode into a ring; evaluate Obsidian/Pixi, cosmograph, sigma+graphology rather than re-tuning.
4. Then the waves below.

---


The **execution view**. [`memory-evolution.md`](memory-evolution.md) stays the reference: it holds
the full reasoning, evidence and file:line for every row. This file answers one question only —
*what is done, what is moving, and what is next.*

**Rule:** every row here is a pointer. Add detail to the backlog row, not to this file.

_Last synced: 2026-09-01 (paused mid-session — PR #25 open and ready to merge)._

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

**This session (PRs #21–#24, merged to dev)**
- #21 diff context lines with line numbers, merge-commit handling
- #22 the G71 slice + connector seam consolidation
- #23 G83 button hit areas & press feedback (87 sites), G84(a)(b) graph cold paint + drag physics
- #24 **the correctness gate** — decay charges once and never for the outage (first-cycle archive
  count **700 → 0** on the active bank), inbox subject gate, set-valued predicates, WAL, Telegram
  webhook secret, bank-import honesty, benchmarks import fix
- Outside PRs: Cicada in **every** Claude session (user-scope MCP + both skills + launchd backend
  with durable keys), CLAUDE.md reframed, doctor cleanup, installer shebang fix,
  **G99a** the 35 MB index untracked before it could commit ~11 GB/yr

---

## 🔄 In progress

| What | State | Next action |
|---|---|---|
| **G74(a) agent engine** | **PR #25 open, ready** — 14 commits, merged cleanly up from dev, 1,515 py / 400 swift green, first-cycle archive re-verified at **0** with a negative control | Merge, then run **one** cycle by hand. Do not enable a schedule. |
| **G88 dev loop** | Restarts clean (stopped mid-build, nothing committed) | `make install-app`, `make dev`, `installRoot()` fix, README run-section |
| **Devin round on #25** | 3 🟡 concurrency findings — fixes in flight | Sleep/Ask share a throttle breaker, double the concurrency cap, and a connector commit can absorb a dirty tree |
| **`saved_at` fix** | In flight (`feat/saved-at`) | `RawItem.added` written by 5 parsers, read by nothing |
| Claude Desktop | **Registered 2026-09-01** — needs a Desktop restart | Then: it captures only what an agent chooses to save (see G105) |
| Backlog hygiene | Triage done, not applied | Close 12 shipped rows, delete/merge 15 — 63 open becomes ~38 real |

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
8. **G86** feed dedup — 789 rows render 603 pages; absorbs G65(a)(b) — M
9. **G19** dead-code sweep — XS

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
15. **G81** contacts — identity anchors *(prerequisite for 16)* — M
16. **G95** meetings & human↔human conversations — M/L
17. **G101** raw-conversation evidence layer — what to keep, what to discard — M
18. **G91** share-to-Cicada *(needs G88's signed app)* — M
19. **G94** life-data streams — aggregates, never samples — L
20. **G76** effortless install + always-on capture — L
21. **G89** feeds first-class (Substack needs no connector) — S/M

### Wave E · thesis & product
22. **G78** gbrain evals — the thesis's weakest link is measurement, not architecture — M
23. **G92** onboarding at scale — decide what Cicada *is* before optimising a funnel — decision
24. **G72** skills manager · **G73** prompt library · **G70** design memory — M each
25. **G54** onboarding interview · **G55** executable skills · **G13** tasks/ideas backlog

### Research / decisions (not builds)
- **G79** north star — the scoring rule, not a task *(move to the file header)*
- **G96** vector-as-entryway — validated; its storage question was answered by G99
- **G99** relational tier — **DECLINED**; revisit only on a named trigger (warm p50 > 250 ms,
  claims > 25k, or a merged G94 adapter retaining raw samples)
- **G77** voice packets · **G80** deterministic rung · **G56** MHS · **G16** shared memories

### Small & cheap — grab when passing
G57 Telegram secret *(shipped in #24 — close it)* · G4 + G5 problem-log/improvement sections
*(merge, one edit)* · G7 centrality *(premise measured false — close)* · G2 taxonomy
*(recommend closing: three later rows independently concluded "resist adding types")*

---

## 🗂 To close / delete during hygiene

**Close as shipped:** G83 · G84(a)(b) · G21 endpoint · G19(e)(f) · A4 · G11 preview half ·
G89 feeds half · G99(a) · G93 search/ask half · G87 invariant half · G7 premise · G57

**Delete or merge:** G79 → header · G38 → CLAUDE.md · G80 → G74 · G96 → G99 · G37 → G91 ·
G46 → G81 · G69 → G71 · G65 → G86 · G5 → G4 · G14 → G70 · G56/G16 → parked · G10 → re-file ·
G2 → close

---

## 🩹 Known-broken, not yet queued
- No episode cap / no cancel route on a running cycle *(Wave A #1)*
- Bank `.git` is 69 MB against 16 MB of markdown — future growth stopped, **history not rewritten**
  (destructive; user's call)
- 8 date-dependent `test_calendar_registry.py` failures — pre-existing baseline on dev
