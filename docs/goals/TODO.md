# Cicada — TODO

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
