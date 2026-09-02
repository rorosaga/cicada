# Cicada — TODO & handoff

> **If you are an agent picking this project up cold, read this section first.** It is the
> compacted context of the 2026-08-31/09-01 sessions: what is true right now, what is in flight,
> the rulings that would be expensive to rediscover, and how work is run here.

## Where things stand (2026-09-01, evening)

**Merged to `dev`:** PRs #21–#29. **No open PRs.** The big one is **#25 — the agent engine (G74a)**:
Sleep can now run on the user's Claude Max plan via `claude -p`, after ~2.5 months with no engine.
Also #24, the **correctness gate**, which fixed decay (see rulings below), #23's app fixes, #26's
`saved_at` fix, and #27's sleep cancel/cap/debt screen.

**#27's 🔴 is worth knowing:** Stage 2 used to make clarifier/index writes *inline* inside the
per-name judging loop, so cancelling mid-Stage-2 left partial writes — including a **deleted** inbox
item. Writes are now queued as callables and flushed only if the loop completes.

**#28 — G88 dev loop (merged 2026-09-01).** `make install-app` / `make dev` / `make login-item`, and
the **bank split-brain closed as a class rather than as a path**: after a default install outside
`~/cicada`, `installRoot` pointed agent setup commands at the *checkout's* memory while the app used
another bank — silent, because memory gets written and the app just shows nothing. The root cause
was **two independent computations that had to coincidentally agree** (a Swift heuristic vs.
`install.sh`/`Settings` defaults). Now there is one source of truth: `GET /healthz` reports
`memoryRoot`, and whenever a backend answers it **overrides the local guess everywhere**
`CICADA_MEMORY_PATH` is emitted (`LiveMemoryRootProbe`: backoff 0.5→8 s, re-armed on reconnect,
never regresses to the guess once a root is known). `installRoot()` survives only as a fallback
until a backend has ever answered. Every snippet path is escaped per format (`SnippetEscape`:
shell/json/toml/yaml). `install_app.sh` stages → verifies → swaps with the old bundle recoverable,
and an interrupted swap is recovered on the next run (EXIT/INT/TERM trap). All of it proved by
injected failures, not argued.

**#29 — wikilinks (merged 2026-09-01).** Renders, click-through, back stack. Round 2 fixed the three
real defects: a `cicada://entity/<ref>` link now carries the wikilink text **verbatim** and is
resolved at click time against the graph snapshot (`MarkdownBody.resolveEntityID`: exact id →
case-insensitive name → `sanitizeID` fallback), so `algorithms-&-data-structures.md` no longer 404s;
`GraphViewModel.pushEntity` commits Back history only once a destination is **accepted** (stub on
the spot, otherwise when the body arrives); `TopicDetailNavigation` is a generation-token value type
so a late fetch can't undo Back. Known, disclosed: the client `sanitizeID` fallback still differs
from the backend's `id_utils.sanitize_id`; `.wikilinkNavigation` traps if hosted outside a
`WindowGroup` (reads `@Environment(Store.self)`).

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

**Nothing is broken; one branch is awaiting a PR.** **G114** shipped on `feat/capture-hygiene`
(2026-09-01/02, six commits, PR pending against `dev`). The 2026-09-01 evening session merged
#28/#29, reframed CLAUDE.md around the *experience port* north star (Silver & Sutton's *Era of
Experience*, WikiSkill), filed **G112/G113/G114** research-grounded, and started **G109** as a
research run (inventory → five engine candidates → three-lens judge → decision memo) rather than
a blind re-tune.

1. **G109 (urgent)** — read the decision memo if one exists (the session writes it to its
   scratchpad, then folds the ruling into the G109 row); otherwise the row itself names the five
   candidates and the two symptoms. Phase 1 must fix both *invisible deceleration* and the *orphan
   ring* in a day, or the port decision is made for us.
2. **G113 slices 1–4 ($0, APPLY)** — the grounded-reward ledger. Every human verdict on memory
   (inbox resolve, decay keep/archive, merge accept/reject, manual edit) becomes a telemetry event;
   ids and enums only. Slice 5 (closing the loop) stays 💸 DECIDE.
3. **G112 step 1** is a bug fix, not a feature — do it when passing.
4. **G53 + G75**, then **G105**, then **G97** — the same order the waves give.
5. **G110 is RESEARCH, deliberately not started.** Its own cheapest-first ruling: build G53/G75 and
   see whether the fork want survives. Second data point to read first: Cursor's "Import from Claude
   Code".
6. **G7 is open again, on purpose.** The hygiene pass could not find the measurement TODO.md claimed
   ("premise measured false") anywhere in tracked history. Re-measure it or delete the claim.
7. **G90 README screenshots** wait for Rodrigo to be at the machine (demo bank or frame-by-frame
   review — the live bank holds real people). Same for any `macos-harness` verification that
   needs a permission prompt accepted.

**Worktrees:** `.worktrees/g114` holds `feat/capture-hygiene` until its PR merges.
`.worktrees/devloop` and `.worktrees/wikilinks` are safe to remove (`devloop-report.md` there is
untracked scratch — never commit `*-report.md`); `sleepctl`, `hygiene`, `saves-and-imports` are
stale from earlier sessions. `git worktree list` to see them; never `--force`-remove one without
looking at `git status --porcelain -uall` in it first.

---


The **execution view**. [`memory-evolution.md`](memory-evolution.md) stays the reference: it holds
the full reasoning, evidence and file:line for every row. This file answers one question only —
*what is done, what is moving, and what is next.*

**Rule:** every row here is a pointer. Add detail to the backlog row, not to this file.

_Last synced: 2026-09-02 (PRs #21–#29 merged; G114 shipped on `feat/capture-hygiene`, PR pending; G88 shipped; G112/G113 filed; G109 in research)._

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
- **G114 capture-writer hygiene** (`feat/capture-hygiene`, PR pending) — one id rule
  (`episode_ids.next_episode_id`, max-suffix+1 per date, importer collision closed), one timestamp
  shape (aware UTC from `episode_ids.utc_now_iso`; Sleep sorts by instant across legacy shapes),
  Telegram stamped with the message date and `/remind` an honest `capture_kind: reminder` note,
  feeds + calendars polled at the Sleep tail under `CICADA_ALLOW_FEED_FETCH=1` (installer sets
  it), and a `processed_by: sleep|agent` stamp on `GET /sleep/episodes`
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
| **G109 graph physics** | **Research run in flight** (2026-09-01 evening): inventory of `graph.js` physics → five candidates (fix d3-force in place, Obsidian/Pixi, cosmograph, sigma+graphology/ForceAtlas2, ngraph/d3-force-3d) → engineer/user/skeptic judges → decision memo with a one-day phase 1 | Read the memo, rule, implement phase 1 in a worktree, fold the ruling into the G109 row |
| Claude Desktop | **Registered 2026-09-01** — needs a Desktop restart | Then: it captures only what an agent chooses to save (see G105) |

---

## 🎯 Next — in priority order

### Wave A · finish what the engine needs
1. **G109 🔴** graph physics — deceleration invisible (velocityDecay 0.45 + alphaMin 0.05 swallow
   the seeded throw) and zero-degree nodes fly to a ring now that the cold-paint fix renders them;
   *research run in flight* (see In progress) — S/M to decide, M to port
2. **G111** newsletters (TLDR / TLDR AI) → "what landed today that matters to me". The TLDR path
   is verified (RSS exists; a feed row per newsletter); the Sleep-tail feed poll it needed shipped
   with G114, so it refreshes without a button press — S/M
3. **G90** README + screenshots — Sleep and the dev loop are both real now; **demo bank or
   frame-by-frame review** — the live bank holds real people — S

### Wave B · make what exists trustworthy
4a. **G113 slices 1–4** — the grounded-reward ledger: every human verdict on memory (inbox resolve,
   decay keep/archive, merge accept/reject, `Cicada-Author: user` corrections) recorded as a
   telemetry event — ids and enums only, never text — with per-predicate agreement rates and a
   confidence-calibration curve as a fourth Activity card. Slice 5 (feeding rates back into
   prompts) stays 💸 DECIDE under G78 — S/M
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
9a. **G112 step 1 ($0)** — ground the skill page: Stage-4 output through `entity_resolver`, merge
   `source_episodes` + bump `last_referenced` on update, evidence entities into `related`, v2
   layout so `source_rewrite`/hubs work, contradictions raise a normal conflict item. A bug fix
   in feature's clothing; steps 2–4 (compile → bundle → export) are Wave C — S

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
13a. **G112 steps 2–4** — portable skills: a deterministic `skill_compiler` turns a grounded
    `skill` entity into a SKILL.md bundle with `## Evidence` (episode ids, agreement rates from
    G113), exported so someone else can load it on their own plan. WikiSkill's third layer — M
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
- Graph physics: throw deceleration invisible, orphan nodes ring *(G109 — Wave A #1, in research)*
- Bank `.git` is 69 MB against 16 MB of markdown — future growth stopped, **history not rewritten**
  (destructive; user's call)
- 8 date-dependent `test_calendar_registry.py` failures — pre-existing baseline on dev
