# Cicada — TODO & handoff

> **If you are an agent picking this project up cold, read this section first.** It is the
> compacted context of the 2026-08-31 → 09-02 sessions: what is true right now, what is in flight,
> the rulings that would be expensive to rediscover, and how work is run here.

## Where things stand (2026-09-02)

**Merged 2026-09-02 as PR #35: `feat/safari-import`** — Safari iCloud
tabs + bookmark folder selection + the family → member import catalog; G30/G47/G71 rows carry the
shipped clauses, G119 (Arc/Firefox/Brave) is filed. The imports were run
against the live bank the same day (iPhone tabs: 188 new / 9 skipped; the big Favorites folder:
0 new / 496 skipped — the idempotency proof). Until each browser
row syncs on its own, `chrome-bookmarks` / `safari-bookmarks` both read the legacy `bookmarks` count.

**Merged to `dev`:** PRs #21–#35. **Open:** `feat/mascot` (G107, PR #TBD — fill in once opened).
The big one is **#25 — the agent engine (G74a)**: Sleep can now run on the user's Claude Max plan
via `claude -p`, after ~2.5 months with no engine.
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

**G109 phase 1 — graph physics (2026-09-02, PR #32 against `dev`).** The research run ruled: keep
d3-force, fix `graph.js` — the "no deceleration" and "orphan ring" were three local bugs, not the
engine (an un-alpha-scaled custom force, a release-path reheat, nothing opposing charge on degree-0
nodes). Two `graph.js` commits plus a committed headless bench (`Tests/graph/graph-physics.bench.js`,
real d3 driving the real `startSimulation`): KE/node at tick 400 20 → 4e-6, a flick coasts 0 → 13
ticks / 100 wu, a release moves the rest of the graph 1,200 → 9 wu, isolate max radius 2.0× → 1.3×
core p90. Two rules now in CLAUDE.md: alpha-scale every custom force; never bump alpha on release.
**Not done:** the live-bank visual check (needs Rodrigo at the machine — the bank holds real people),
phase 2 (own the loop + `__cicadaPerf`, then the tuning pass — including the **no-op-delta shuffle**
the final review measured: a delta with no change still moves a dense core 80 wu mean / 573 max,
bench `deltaNoop*`; the lever and why it is not pulled in phase 1 are in the G109 row), phase 3
(isolates out of the sim), and the Swift track (`ContentView` rebuilds the `WKWebView` per tab
switch — that is the "explosion on return").

**G107 pixel mascot (2026-09-02, `feat/mascot`, PR #TBD).** The bracket-text interim is superseded: a
nine-colour 24×24 sprite set, every state always moving, `error` state added, the menu bar shows one
animated worm with the count in the sprite (no more text badge), and `BookwormView` on a `TimelineView`
at whole-cell sizes on five surfaces. `swift test` green (four new test files, 31 new cases); the visual
pass — menu bar light/dark, Sleep page, Reduce Motion — is the install step, not yet done at the time of
this commit.

**Live environment (verified):** backend runs under **launchd** (`com.cicada.backend`,
RunAtLoad+KeepAlive, `python -m uvicorn`), keys in `~/.cicada/secrets.env` (0600). Cicada's MCP
server is registered at **user scope** so every Claude Code session sees it, both skills are in
`~/.claude/skills/`, and **Claude Desktop is registered** (needs a Desktop restart). Active bank:
`claude-chats`, 1,731 entities. **One-time step after G114:** `install.sh` only writes the launchd
plist when no backend answers `/healthz`, so this pre-G114 plist lacks the feed-poll opt-in — add
`<key>CICADA_ALLOW_FEED_FETCH</key><string>1</string>` to its `EnvironmentVariables` dict, then
`launchctl bootout gui/$(id -u)/com.cicada.backend && launchctl bootstrap gui/$(id -u)
~/Library/LaunchAgents/com.cicada.backend.plist`; until then the nightly feed/calendar poll logs
`skipped: CICADA_ALLOW_FEED_FETCH is not "1"` every cycle.

**2026-09-02:** **PR #30 (G114 capture-writer hygiene) and PR #31 (G113 slices 1–2, the feedback ledger:
`_verdict`, the `resolution` event, R1 trigger labels) merged to `dev` at `09a4b66`.** G109 phase 1 is in
flight on `feat/graph-physics`. The inbox redesign study (four designs, three judges, critic pass) is
folded in as **G115** (the design, APPLY) and **G116** (its two contract rulings, DECIDE).

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

**Nothing is broken; one branch is awaiting a PR: `feat/mascot` (G107 pixel mascot, PR #TBD).**
Its last unchecked box is the visual pass on the installed app — menu bar in light and dark, the
Sleep page at 120 pt, Reduce Motion holding frame 0 — which needs `make install-app` and Rodrigo at
the machine; the suites are green. Before it: `feat/safari-import` merged as PR #35 (2026-09-02), **G114** shipped as PR #30, the 2026-09-01 evening session merged #28/#29, reframed CLAUDE.md around the *experience
port* north star (Silver & Sutton's *Era of Experience*, WikiSkill), filed **G112/G113/G114**
research-grounded, and started **G109** as a research run (inventory → five engine candidates →
three-lens judge → decision memo) rather than a blind re-tune.

0. **Merge `feat/safari-import`** after an independent re-run of both suites (`pytest api/tests`
   → only the baseline calendar/provenance failures; `swift build && swift test` → 0 failures), then
   run the live import once with the owner present (Full Disk Access to Cicada.app is a one-time
   grant — the launchd backend never gets it, only the app bundle does).
0b. **Owner priorities (2026-09-02):** after the three in-flight tracks (mascot, Safari import, link
   summaries) land, the order is **G118 slice 1 → G105 → G93 → G53+G75 → G81→G95**, with G113 s3–7,
   G115 p1 and G117 interleaved as app polish. Provenance is the vision, not a feature.
1. **G109 phase 1 is in PR #32 (merged)** — merged after an independent re-run of
   `node app/CicadaApp/Tests/graph/graph-physics.test.js`, the four sibling JS tests and
   `swift test`, then have Rodrigo eyeball the live bank at fit-zoom (isolates should read as discs
   on their type clusters, not a halo). Then the **Swift track** (one long-lived `WKWebView`, reset
   `isGraphReady` on teardown — ~0.5 day) before phase 2; without it the user still sees a re-layout
   every time they return to the Graph tab. Phases 2–3 are in the G109 row.
2. **G113 slices 3–7 ($0, APPLY)** — slices 1–2 (`_verdict`, the `resolution` event, R1 labels) merged
   as PR #31; the rest of the ledger (audit/dedup verdicts, the Activity card, `remind_later → _defer(7)`)
   is still open. Slice 5 (closing the loop) stays 💸 DECIDE.
3. **G115 Phase 1 ($0, 1–2 days, engine-free)** — the inbox redesign's first slice: cause on the card,
   `(Recommended)` from the shipped `_verdict`, decay through `QuestionView`, number keys, ETag BOTH
   halves, `render_question` v2. Delivers G97. Parallel to G113 in its own worktree — disjoint
   functions of `inbox_service.py`. The two rulings it needs for Phase 3 are G116.
4. **G112 step 1** is a bug fix, not a feature — do it when passing.
5. **G53 + G75**, then **G105**, then **G115 Phase 2** — the same order the waves give.
6. **G110 is RESEARCH, deliberately not started.** Its own cheapest-first ruling: build G53/G75 and
   see whether the fork want survives. Second data point to read first: Cursor's "Import from Claude
   Code".
7. **G7 is open again, on purpose.** The hygiene pass could not find the measurement TODO.md claimed
   ("premise measured false") anywhere in tracked history. Re-measure it or delete the claim.
8. **G90 README screenshots** wait for Rodrigo to be at the machine (demo bank or frame-by-frame
   review — the live bank holds real people). Same for any `macos-harness` verification that
   needs a permission prompt accepted.

**Worktrees:** `.worktrees/safari-import` holds `feat/safari-import` until its PR merges;
`.worktrees/g113` (`feat/feedback-ledger`), `.worktrees/link-summaries` and `.worktrees/mascot` are
other in-flight branches — check each's `git status --porcelain -uall` before touching it. Never
commit a `*-report.md` left as untracked scratch in any of them. `git worktree list` to see them; never `--force`-remove one without
looking at `git status --porcelain -uall` in it first.

---


The **execution view**. [`memory-evolution.md`](memory-evolution.md) stays the reference: it holds
the full reasoning, evidence and file:line for every row. This file answers one question only —
*what is done, what is moving, and what is next.*

**Rule:** every row here is a pointer. Add detail to the backlog row, not to this file.

_Last synced: 2026-09-02 (PRs #21–#35 merged — #30 G114, #31 G113 slices 1–2, #32 G109 phase 1, #33/#34 install + CLI-discovery fixes, #35 Safari import + catalog; G107 pixel mascot on `feat/mascot`, PR #TBD; G118 (provenance) and G119 (Arc/Firefox/Brave) filed)._

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
G68 UI round 2 · A1 per-commit diffs · A2 contributors · A3 ingestion animation · G15 avatars · G107 pixel mascot + single menu-bar Tamagotchi

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
- **Safari import track** (`feat/safari-import`, PR #TBD) — Safari iCloud tabs (device picker),
  bookmark folder selection with tree preview (Reading List as its own folder), per-browser channels,
  the app reads `~/Library` and posts bytes (the launchd backend never could), Full-Disk-Access fix
  shown in place, and the `+` sheet re-layered into a logo-first family → member catalog with keyboard
  navigation. Follow-up: G119 (Arc/Firefox/Brave).
- **G109 phase 1** graph physics (PR #32) — alpha-scaled hub gravity, no reheat on release,
  `velocityDecay` 0.2 / `alphaMin` 0.001, per-isolate phyllotaxis slots, speed clamp; headless
  physics bench + test under `Tests/graph/`; numbers in the G109 row

---

## 🔄 In progress

| What | State | Next action |
|---|---|---|
| **G74(a) agent engine** | **PR #25 — merged** (14 commits, `0fb0d38` round-1 Devin fixes included: Sleep/Ask share a throttle breaker, doubled concurrency cap, connector commits absorb a dirty tree), first-cycle archive re-verified at **0** with a negative control. Rung (b), the in-session agent path, is not built — G74 stays open in the backlog. | Run **one** cycle by hand. Do not enable a schedule. |
| **G109 graph physics** | **Phase 1 in PR #32** (2026-09-02): ruling = keep d3-force, fix `graph.js`; three commits + a committed bench, numbers in the row. Phases 2–3 and the Swift `WKWebView`-rebuild track are open | Merge after an independent re-run; live-bank visual check with Rodrigo; then the Swift track, then phase 2 |
| Claude Desktop | **Registered 2026-09-01** — needs a Desktop restart | Then: it captures only what an agent chooses to save (see G105) |

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
   confidence-calibration curve as a fourth Activity card. Slice 5 (feeding rates back into
   prompts) stays 💸 DECIDE under G78 — slices 1–2 merged (PR #31); 3–7 open — S/M
4d. **G115 Phase 1** — inbox redesign, first slice: one question object for every kind, `cause` on the
   card (three tiers, `[ no source recorded ]` served), `(Recommended)` = the option `_verdict` scores
   `agreed` (never on merge), decay through `QuestionView`, number keys / `Esc` no-trace skip, ETag
   widened server-side AND `.inbox` added to `VersionVector`'s `entities`/`episodes` in the same
   commit, `render_question` v2 with a `Cause:` line. $0, engine-free, 1–2 days, in parallel with
   G113 slices 3–7 (disjoint functions). Phase 2 (ask gate, `never` rules, observer capsule) after
   G113 3–4 and G106(i); Phase 3 (grouping, Sleep-counted silence-close, rule executor) after G116 — S/M
4. **G98 remainder** — the predicate/entity-resolution half (~15 of 27 conflicts are artifacts) — M
4b. **G104** a resumed conversation is consolidated twice — reconsolidation is the likely answer
   (the claim layer's `superseded_by` already models "replaced by a better-informed belief") — M
4c. **G105** deterministic conversation extraction — stop capture depending on a model choosing to
   call a tool (measured: 4 episodes from one long session, 0 MCP calls in 12 days). Includes
   source logos in the Sleep queue — S/M
5. **G97** inbox items show the conversation that caused them (43/49 reach an episode in ~100 ms,
   no LLM) — **delivered by G115 Phase 1 (4d above)**; the ETag widening is both halves there. — S/M
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
    the vision (2026-09-02). Slice 1 = span capture in Stage-1 + resolver; absorbs G100 — L
9c. **G93 cross-stream ask** and **G105 deterministic capture** — moved up (owner, 2026-09-02): G105
    is what makes every write have a cause; G93 is where citations become answers — M each
10. **G53 + G75** state dictionary + handshake — highest fan-out of anything unbuilt
    (G76, G77, G54 all assume it); zero LLM — M
11. **G100** span citation — which *sentence* convinced the contributor, rendered in a
    DiffView-style source viewer with prev/next across conversations — M
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
22a. **G117** first-run onboarding in the app — **release blocker**: a three-step first-run sheet
    (engine → capture channel → first Sleep), honest empty states per tab, and a one-click synthetic
    demo bank so the graph is never blank. Ships with G76 and G90 for a downloadable 1.0 — M
23. **G92** onboarding at scale — decide what Cicada *is* before optimising a funnel — decision
24. **G72** skills manager · **G73** prompt library · **G70** design memory *(absorbs G14)* — M each
25. **G54** onboarding interview · **G55** executable skills · **G13** tasks/ideas backlog

### Research / decisions (not builds)
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
G7 centrality *(recommended for closing — "premise measured false" per a prior session, but this
hygiene pass could not find the underlying measurement anywhere in tracked docs; left OPEN — see
the report for what was checked)*

---

## 🩹 Known-broken, not yet queued
- Graph re-lays out on every return to the Graph tab: `ContentView` rebuilds the `WKWebView` per
  tab switch *(G109 Swift track — Wave A #1; the physics half shipped in phase 1)*
- Bank `.git` is 69 MB against 16 MB of markdown — future growth stopped, **history not rewritten**
  (destructive; user's call)
- 8 date-dependent `test_calendar_registry.py` failures — pre-existing baseline on dev
