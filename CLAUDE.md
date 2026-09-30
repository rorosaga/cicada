# CLAUDE.md

Guidance for Claude Code working in this repository.

**This file is the philosophy and the rails. The detail lives in
[`docs/goals/`](docs/goals/) — read it before proposing work.**

---

## Project

**Cicada** — Author: Rodrigo Sagastegui.

The goal: **capture the human experience seamlessly, and make it something you can hold a
conversation over — with agents that can understand it, contribute to it, and draw their own
relations across it.**

Concretely, Cicada aims to span:

- **Every kind of media ingestion** — links, articles, papers, videos, images, bookmarks, RSS,
  files, saved collections exported from the platforms where they pile up.
- **Every conversation** — the ones with agents (MCP-native clients, plus imported ChatGPT/Claude
  exports), and, as recording becomes part of the workflow, **conversations with other people**:
  meetings ingested the same way, through the same source-agnostic pipeline.
- **The moving parts of a life** — projects, ideas, current interests, the things being decided and
  the things quietly going stale.

The design principle that follows: memory must be **legible to an agent without ceremony**. An
agent should be able to arrive, be told what Cicada is and how to use it, read the graph,
contribute beliefs with provenance, and leave the store better than it found it. The
markdown-and-git substrate, the claim layer, the author/session trailers and the MCP surface all
exist to make that true.

The architecture is biologically inspired: **Awake** = hippocampal encoding (fast, episodic capture,
no processing at capture time), **Sleep** = cortical consolidation (slow, semantic, batch), and
**temporal decay** = synaptic homeostasis (absence of mention is itself a signal). Episodic noise
gets compressed into a structured, versioned knowledge graph rather than accumulating as a
transcript pile.

### Why: the human-to-agent experience port

Cicada is the **port between a human's experience and the agents that will act on it** — the first
step toward capturing everything of a person's experience and their interactions with the world in
a form an agent can understand, so that, eventually, agents, humans and robots coexist on one
legible record of what happened and what it meant. Two papers frame the design, and every backlog
row should be readable against them.

**Silver & Sutton, *Welcome to the Era of Experience* (2025).** Their claim: the next generation of
agents will learn predominantly from *streams* of experience rather than snippets of human data,
grounded in an environment, with rewards from that environment and reasoning not confined to human
terms. Cicada's reading: **the person's life is the environment, and Cicada is the instrument that
turns it into a stream an agent can inhabit.** Four correspondences, each a design constraint:

1. **Streams, not sessions.** A conversation is a snippet; a life is a stream. Awake capture is the
   stream's intake, Sleep is what makes it more than a transcript pile, and decay is the stream's
   own clock — silence is data. Anything that fragments the stream (a resumed conversation
   consolidated twice, G104; capture that depends on a model choosing to call a tool, G105) is a
   defect against this, not a nicety.
2. **Observations *and* actions.** Every capture channel is an observation. Every agent write with
   provenance — a claim, a `Cicada-Author:` trailer, an inbox resolution — is an action on the
   shared record. The port is two-way or it is a diary.
3. **Grounded rewards.** When the person answers a nudge, overrules a claim, keeps or archives an
   entity, that is a reward signal *from the environment*. Cicada should treat these resolutions as
   the signal it learns from, not just as edits to apply (G113).
4. **Reasoning beyond prose.** The claim layer — typed predicates, bi-temporal validity, observer
   and trust — exists so an agent can reason over the record structurally. Prose is for humans;
   claims are the machine-legible half.

**Tang et al., *WikiSkill* (2026, arXiv:2608.27454).** Separating *raw experience* from a
*persistent wiki* from *executable skills* is what makes skill evolution work (the wiki is worth
+15 points to the skill proposer in ablation), and evolved skills **transfer across models and
model families**. Cicada holds the first two layers: `episodes/` is the raw layer, the
entity-plus-claim graph is the wiki. The third — compiling what the graph knows about *how this
person works* into portable, agent-loadable skills — is **G112**. The bar: **a skill compiled from
one person's experience should load into any harness on any plan, with Cicada being nothing more
than its provenance.**

**Portability is the point, not a feature.** The goal is other people running this on their own
plans and harnesses (G50 connections, G76 install, G92 onboarding). A hardcoded owner name, a path
that only exists on the author's machine, a bank that cannot be handed over intact — each is a bug
against the mission, not a polish item.

---

## Branches

- `main`: production/stable branch
- `dev`: active development branch — all work goes here first

PRs open against `dev`. Promotion to `main` is a manual, deliberate step — never a PR target.

---

## Backlog and handoff (`docs/goals/`)

**Read these before proposing work.** A proposal that duplicates a `G` row or re-opens a settled
ruling is wasted effort. Detail belongs in the backlog; state belongs in TODO.md. After finishing
work, update both.

- **[`memory-evolution.md`](docs/goals/memory-evolution.md) — the backlog.** One row per idea,
  `G<n>`, numbered in the order raised and never renumbered, so a `G` id is a permanent address:
  cite `G74a` in commits and PR bodies the way you would cite a ticket. A row carries the
  *reasoning* — the problem, the evidence (file:line, a measured number, a reproduction), and the
  design constraint any fix must respect. Triaged **APPLY** / **RESEARCH** / **DECIDE**; 💸 marks
  paid LLM spend. When you learn something that changes a row's argument, edit the row — never open
  a second one.
- **[`TODO.md`](docs/goals/TODO.md) — execution view + handoff.** Same work ordered by what to do
  next. Its header is written for an agent picking the project up cold: current state, open PRs,
  the verified live environment, and a "Pick up here" line. Above all it carries the **rulings** —
  decisions that cost real measurement, each with the evidence that settled it. **A ruling is
  binding.** Revisit one only on the trigger its row names, and only after reading why it was made:
  several were reached by disproving the obvious answer, so re-deriving them from first principles
  reliably gets them wrong.
- **[`working-method.md`](docs/goals/working-method.md) — how the work is run.** The bar a change
  clears (plan → critic → per-task implement+review → two-lens final review → verify yourself → PR
  to `dev`), the test baselines that are *not* failures, the rails that override convenience, and
  the paused queue with the reasoning for its order.

**Privacy rule (standing, 2026-09-02).** Nothing personal about the owner or anyone in their life
goes into `docs/goals/`, this file, a plan, a commit message, or a PR body: no names of other
people, employers, clients or companies from the bank; no episode or inbox titles; no quoted
conversation or claim text; no URLs, handles or contact details. The owner's own *thoughts and
ideas* are fine to quote — a row starting "Rodrigo 2026-09-01: …" carrying a design opinion is the
intended voice. When a row needs an example, use placeholders (`<surname-a>`, `alpha-project`,
`bob-example`) and say "real values redacted". **The repo is public; the bank is not, and the line
between them is this rule.**

---

## Repository Structure

`api/` FastAPI backend, `app/` SwiftUI macOS app, `mcp/` the MCP server, `memory/` the runtime bank
(gitignored), `docs/goals/` the backlog. Read the tree with `ls` — it is not duplicated here.

---

## Core Architecture: Awake/Sleep

### Awake — capture
Continuous episode capture. Raw timestamped chunks go to the `episodes/` inbox. **No LLM
processing at capture time** — just file I/O.

Sources are many and the pipeline is **source-agnostic**: MCP-native clients, hook-driven session
capture, chat exports, browsers (bookmarks and Safari tabs), Telegram, direct saved-content
connectors (Pinterest/Reddit/X), RSS, calendars, files. The per-channel detail lives in
`api/services/` and in the backlog rows that introduced each one — read the code, not a list here.
Seven rails hold across all of them:

- **The app reads `~/Library`, the backend parses bytes.** The launchd backend has no Full Disk
  Access and must never open those paths itself. An unreadable file shows the exact fix in the app.
  Apple Notes is the same: the app runs the AppleScript as its own child `osascript`
  (`AppleNotesReader`, `NSAppleEventsUsageDescription`) and posts the dump to `POST /sources/sync-notes`,
  which 422s without one — run from the launchd backend, macOS asked whether "python3.12" may control Notes.
  `POST /sources/sync-bookmarks` likewise 422s without bookmark bytes (there is no local-file fallback), and no
  route stats a path the request names. Folders a page declares follow it too: `GET /entities/{id}/location`
  returns the path and the app lists it (`LocationLister`), a declared repo's git runs in the app (`GitRunner`,
  see `repos:`), and Resume's folder is entered by the terminal — the backend never stats any of them.
  A browser is read only after the person turned it on — a Sync now, an all-folders import, or
  onboarding's tick — through `cicada.browserWatch.enabled.<channel>`; an install that synced
  before this gate keeps syncing (Track I T1). Browsers (round 4, C9): Chrome, Safari, Brave,
  Vivaldi, Comet and Dia — each read from its default profile only (`<browser>-bookmarks`, the
  Chromium `Bookmarks` JSON through one parser); Safari's Reading List keeps its added date and
  Safari's excerpt, and a sync reads recently saved first and stamps Reading List / Favorites
  counts as the channel's `parts`. Safari's excerpt is scrubbed, capped at 500 characters and used
  only when the page gave no description of its own.
- **Capture must not depend on a model deciding to call a tool** (G105). Every Claude Code and
  Codex session is captured by the harness's own `Stop` hook
  (`api/hooks/capture.py` → `POST /capture/transcript`). **The backend reads the transcript**, and
  only after the path resolves under the harness root as `<session_id>.jsonl` within the size cap —
  anything else is refused unread. `transcript_extract.py` keeps only the person's turns and the
  agent's final reply per turn; tool calls, thinking, file dumps and harness-injected text are
  skipped by construction. From a kept agent turn it reads two more facts and nothing else (round
  4 C1, G49 lifted for harness writes): the model id (Claude Code's `message.model`, Codex's
  `turn_context.payload.model`) and the reasoning effort (Claude Code's top-level `effort`, Codex's
  `turn_context.payload.effort`, and for the last reply the Stop hook's stdin `effort.level`). Both
  are cleaned by `agent_turns` (an effort is one of `minimal|low|medium|high|xhigh|max`, and
  anything else is dropped). They ride the sidecar on agent entries only; the transcript wins over
  the hook. Secrets scrubbed, per-turn and per-session caps applied. **One episode
  per session** — a later Stop rewrites it in place and flips `processed: false`, never two
  episodes for one conversation (G104). Cicada's own `claude -p` and `codex exec` spawns run with
  `CICADA_CAPTURE=off`. **Recall is the same move (G149):** the harness's `SessionStart` and
  `UserPromptSubmit` hooks (`api/hooks/recall.py` → `POST /capture/hook-context`) put Cicada's note
  in front of the model: the primer at session start, and the pages a message names on every
  prompt. Recall therefore no longer depends on a model calling `cicada_recall`. The prompt travels
  in a JSON body and is never logged, and `transcript_extract` drops any block opening with
  `recall_text.INJECTION_PREFIX`, so a recalled note is never captured back as the person's words.
- **Transcripts under `~/.claude/` are never read anywhere else.** The MCP seam and the resume path
  only ever `isfile()` them to answer "is this session still resumable"; that answer is computed
  per request and never persisted.
- **Every writer mints ids through one rule** (G114, `api/services/episode_ids.py`):
  `next_episode_id` is max-suffix+1 per date (a count-based rule collides after any gap, and
  `markdown_parser.write` overwrites on collision), and timestamps are aware UTC from
  `episode_ids.utc_now_iso` — never a naive local time with a `Z` appended. Legacy files are not
  migrated: readers accept both shapes and the queue sorts by `timestamp_sort_key`. A processed
  episode carries `processed_by` (`sleep` vs `agent`) so a flipped flag is distinguishable from a
  consolidation. `processed_by` also takes `user` — a companion note the person wrote in the app
  (G141 PJ-3b's Log; already processed, so Sleep never re-reads it).
- **Every writer scrubs, and every source-keyed writer stages through one module** (G133/G134,
  R-N3). `api/services/episode_scrub.py` — secrets, long base64 runs, one-time codes anchored on a
  connector word — runs before every writer's hash and write, and `test_episode_writers_scrub.py`
  fails for any module that mints an episode id without it. `api/services/episode_staging.py` is the
  G20 stager they share: an `EpisodeDraft` keyed by `source_id`, the hash over the scrubbed body, an
  edit rewritten in place with `processed: false`, a rename kept by content hash, a deletion
  tombstoned (`source_deleted_at`) and never unlinked. A multi-turn source records G118's per-turn
  sidecar `turns: [{offset, ts, speaker, model?, effort?}, …]` (R-PB4: an entry only for a turn with
  a time, the last key, outside `content_hash`, capped head-stable at 500; `model`/`effort` only on
  an agent turn (round 4 C1)) — the one shape `evidence.turn_stamps`
  reads. The Stop hook writes it too since G141 PJ-4 (R-PJ16): its `role: text` body is the stager's
  line shape, so `episode_staging.stamps_for` builds the list, and the episode `timestamp` stays the
  session's start while each turn carries its own time. A Stop-hook episode written before PJ-4 still
  holds an integer count, which reads as no stamps.
- **A local source is read by the app and parsed by the backend** (G133/G134). A watched folder:
  security-scoped bookmark, FSEvents, an mtime+size+sha manifest, bytes posted with relative paths to
  `POST /sources/folders/{id}/sync`; files under an agent glob land as `evidence_kind: assistant`,
  already processed, so an agent's sweep is never the owner's words. Saving new rules re-derives
  every existing episode of the folder in place — frontmatter only, the hash unchanged; agent → owner
  is queued, owner → agent is parked unless Sleep already read it — in one `user` commit (trigger
  `folder/authorship`), and the papers' why-claims follow (F2-back R-B6, R-B7). Wispr Flow: its SQLite opened
  read-only by the app through a column whitelist (never audio, screenshots, accessibility or pasted
  text); meetings and notes by default, dictation only when the person turns it on. A meeting line is
  `speaker:<label>:` and counts as `user` evidence only when its label is one of the owner's listed
  names. Apple Calendar (G142): the app reads EventKit after the one standard permission prompt and
  posts a rolling window to `POST /sources/calendar-local/sync` (one request = the whole window).
  `calendar_local.py` stages each event keyed `calendar-local:<id>`:
  - notes are scrubbed, then cut at 2,000 characters;
  - a link keeps no query;
  - an event gone from the window is tombstoned, only for the calendars the request named;
  - one `user` commit per sync (`capture/calendar`).
  The app half: `CalendarReader` reads every calendar on the Mac through EventKit, only after Connect and
  macOS's full-access prompt, 30 days back to 60 ahead, and posts on launch, on `EKEventStoreChanged`
  (debounced), every 3 hours, after a bank switch and on Sync now; an empty read is never posted (it would
  tombstone the window); Disconnect stops it and deletes nothing. ICS subscriptions are unchanged.
  Chrome's open tab groups (round 4, G160 first slice): the app reads the default profile's
  `Sessions/Session_<n>` (SNSS; only a clear version-3 file carrying its initial-state marker, never `Tabs_*`, never
  the encrypted directory; commands 25/27 and each member tab's current navigation — never the page state after its
  title) only after the person turns on its own switch (`cicada.browserWatch.enabled.chrome-tab-groups`); FSEvents on
  `Sessions/`, debounced 10 s and floored at 60 s, and a per-bank digest that never counts a fold.
  `POST /sources/tab-groups/sync` stages one snapshot episode per group keyed
  `tab-group:<browser>:<profile>:<saved guid | title+colour | session token>`, `http(s)` tabs only (query kept and
  scrubbed, fragment dropped), tombstoned per browser and profile, one `user` commit per sync (`capture/tab-groups`).
  macOS Contacts (G154): the app reads the address book through the Contacts framework after one prompt
  (`NSContactsUsageDescription`) and posts the whole book — names and booleans for which facts a card holds, a
  thumbnail ≤ 64 KB; never an address, a number or the notes field — to `POST /sources/contacts-local/sync`, on
  Connect, on launch when `currentHistoryToken` moved or a day passed, on `CNContactStoreDidChange` (debounced) and on
  a bank switch; an empty read is never posted. `contacts_local.py` matches exactly one `person` page by folded full
  name or alias and never creates one; matched facts become `sources:` entries `{ref: addressbook://<id>, kind: app,
  predicate, added_by: cicada}` the sync alone reconciles; the photo is cached at
  `$CICADA_HOME/pictures/<bank>/contacts/<id>.<jpg|png>` — `contacts_local.photo_path(bank, id, ext)`, the one path
  T-People's picture ladder reads — and marked `contacts_photo: {sha, ext}`; 409 while Sleep runs; one `user` commit
  per sync (`capture/contacts`).
- **Capture never writes into a demo bank** (G117's synthetic bank; G141 capture-side track). A bank
  is the demo when `<bank>/_bank.yaml` says `kind: demo` — written first by `demo_bank.populate` and
  committed as `cicada` — or, for a demo made before that file, when its `.git/config` carries the
  generator's identity; never by its name (`api/services/demo_guard.py`). While it is active: every
  POST/PUT under `/capture/` and `/sources/` answers **409** (one route dependency,
  `refuse_capture_into_demo`, and a test that fails for a new route that is neither gated nor named);
  the intake checks the bank it writes into, so `?bank=` into your own memory still works; the MCP
  write tools refuse with a sentence the agent relays; Telegram answers 200 with a reply saying
  nothing was saved; and the Stop hook saves the session into the real bank left most recently
  (`last_active_at`, stamped by `activate_bank`; the response says `bank` and `redirectedFrom`), or
  answers 409 when it cannot tell which — the next reply after switching back saves the whole
  session. A demo bank's Sleep consolidates its own made-up episodes, but its tail skips the
  connector, feed/calendar, link-backfill, paper and Wispr to-do steps (connector credentials are
  machine-global). The generator itself is never gated.

**Conversation identity (G48).** An MCP episode carries `session_id` plus `harness` and
`project_dir` when exposed — minted once per MCP process from `CLAUDE_CODE_SESSION_ID` →
`CICADA_SESSION_ID` → a `ses_*` fallback that groups but never resumes. Entities credit to
conversations transitively via `source_episodes`. A conversation row's `model` stays null. The
model lives per turn instead (round 4, G49's reservation lifted for harness writes, TODO ruling 11):

- the Stop-hook episode's `turns` sidecar records each agent turn's `model`/`effort`;
- a claim written through the MCP seam carries `recorded_ts`;
- `turn_authorship.py` joins the two at read (`authorModel`/`authorEffort`), never guessed and
  never self-reported.

An app with no capture hook (the Claude app, ChatGPT, Cursor, a remote connector) has no turn to
join, and neither does a Codex MCP write, because Codex gives an MCP server no session id. The app
then says the model wasn't shared.

### Sleep — 5-stage nightly batch
1. **Entity & relationship extraction** — LLM over episode chunks, structured output.
2. **Entity resolution & dedup** — fuzzy match, embedding similarity, LLM disambiguation.
3. **Conflict resolution & pruning** — contradictions detected, recency wins, old state archived;
   temporal decay applied.
4. **Pattern detection & skill extraction** — recurring patterns distilled into skill entities.
5. **Nudge generation, clarification queue & versioning** — snapshot, git commit.

An **engine-independent tail** runs on every exit path, idle nights included: the state-dictionary
refresh, claim expiry (first in the clean-tree-guarded slot, its own `commit_paths` commit),
follow-ups (G141 PJ-6, right after expiry, its own `cicada` commit), the exact-match source links (G61 S3-a, `source_links`,
its own `cicada` commit, dirty pages skipped), the site check (G61 S3-b, behind `CICADA_ALLOW_CONNECTOR_FETCH`, its own
`cicada` commit), the connector poll, RSS/ICS polling (opt-in via `CICADA_ALLOW_FEED_FETCH=1`), and the link
enrichment backfill — all in a clean-tree-guarded slot, after `_finalize`'s own commit so the poll's
`git add -A` sweeps only its own files.

**Consolidate reads everything (owner, 2026-09-29; TODO ruling 13; scheduled runs too since 2026-09-30, ruling 16).** "I don't want to cap the max episodes per sleep —
it's just progress Cicada has to go through." A **person-started** run (`POST /sleep/trigger`, so every Consolidate door:
the Sleep page, Home's and the intake card's *Read now*, the menu-bar worm) — and, since ruling 16, a **scheduled** one, on the scheduled engine — is a **drain** — `run(..., drain=True)`, one
`run()` that keeps `status == "running"` for its whole length. It freezes the ids waiting when it started
(`sleep_cycle._drain`; episodes captured meanwhile wait for the next run, counted as `arrivedSince`), resolves the engine
**once** ("Auto" must not flip to another, paid, engine at batch 9) and reads them in batches of
`sleep_max_episodes_per_cycle` (default 25; Reading options can make it 10, 25 or 50 — the setting keeps its name and now means *how often progress is saved*). Each
batch is a whole pipeline under its own `<drain id>_b<nnn>` cycle id, breaker scope, models ledger and clock, and **Stage 5
files and commits it** (`Sleep cycle <date> (batch k of n)`, `sleep_run` refs gain `drain_id`/`batch`/`batches`, ids and
ints only), so a cancel or a plan stop loses at most the batch in progress and the next Consolidate continues with what is
left. A plan limit (`EngineThrottled`/`Exhausted`/`Overage`, the breaker tripped by a swallowed per-episode throttle, or the
ChatGPT pre-flight's used-up sentence, whose snapshot `resets_at` rides along via `codex_engine.last_limit_resets_at`) is a **pause, not a failure**: the vendor's own sentence and reset time
(`agent_engine.breaker_resets_at`) ride `drain.stop`, `error` stays null, and the run does **not** continue itself after the
reset unless the person switched on *Continue after a plan reset* (off by default, ruling 15, below) — otherwise the person presses Continue. A cancel is the
existing cooperative one: a batch before Stage 5 is discarded (its paid reads are lost and it is read again next time — the API's cancel message says so), one already writing commits, then the loop stops. A
conversation that fails **for its own reasons** (an empty answer, a timeout, an unparseable reply — `sleep_drain.classify_episode`)
goes first in the very next batch for **one more try and is then parked**; a failure that is the **engine's** (signed out,
throttled, exhausted, model not found) stops the run after the batch commits what it read and is never counted against a
conversation. An id another writer marked processed meanwhile is `skipped`, and a bank switch between batches stops the run (`bank_switched`; `activate`, `demo`,
`leave-demo` and the active bank's rename answer **409** while `SleepState.drain_run`). **A scheduled cycle drains too**
(ruling 16: both scheduler entry points pass `drain=True`) but with `user_triggered=False`, so ruling 4 holds — it never uses
a plan; on a metered engine it spends until the queue is empty, with no limit Cicada sets, and the engine menu and Details
say so in words. **Once per drain, not per batch:** temporal decay (both engines,
`decay=False` on `resolve_and_prune` / `reconcile_stage3` / `run_claim_pipeline`) and Stage 5.57's page reads run only in the
batch that empties the queue (a decay-only finishing pass covers a last batch whose ids were read elsewhere), so decay is
charged once (TODO ruling 1) and a stopped drain never decays; **once per run:** the whole engine-independent tail, whose
tree guard reads the *last attempted* batch (a batch that raised after writing keeps every poll off the dirty tree), with the
link backfill skipped after a plan stop. G85's `(decay)` split and the one-git-writer rule are untouched — each batch's
`_finalize` runs under the same per-bank lock. `GET /sleep/status` carries a `drain` block (frozen, batchSize, batch,
batches, filed, requeued, skipped, active, finished, `stop{reason, sentence, resetsAt}`, arrivedSince — measured counts,
never an estimate, G107), the entity/episode counters as the run's running sums, `episodesQueued` the frozen total,
`episodeCap` the batch size of the run in progress (0 with none), `batchSize` the configured one, always served, `readByOrigin` cumulative; the SSE `sleep` event gains a compact `drain`. **The write window
(G177):** `sleep_cycle.is_writing()` is the one predicate behind every "Sleep is running" refusal that guards a page
(projects, entities, backlog, local sources, memory, maintenance, the remote connector's writes, paper details) and behind
`GET /sleep/status`'s `writing`, which MCP's `_backend_sleep_running` and `BACKLOG_SLEEPING` read. A plain or scheduled cycle
holds the bank for its whole run, as before; a drain holds it only from a batch's Stage 2 (which loads the pages Stage 5
rewrites) through its commit, plus the run's start and its tail. Stage 1's engine calls and the gaps between batches touch no
page, so the *server* accepts page writes there and a stdio agent's claim **commits alone under its own harness** there instead of being
swept by the next batch's `git add -A` under the Sleep author. A claim written *inside* a window still stands uncommitted
and rides that batch's commit (minutes, the pre-drain exposure); bank switching, export and delete still answer 409 for the
whole run (the run is pinned to its bank), and `activate`'s sentence is shown as the toast. A batch that commits with the
plan's breaker tripped stops the drain only while frozen ids are still waiting; with none left it is a finished run (the
note is logged, the link backfill still runs).
**Sleep page v5, backend (2026-09-30; TODO rulings 15 and 16; the boards are applied on top of the drain).**
- **Reading options** — `GET/PUT /sleep/run-options` (`sleep_run_prefs`, machine-wide in `~/.cicada/connections.json` under `sleep-run`, snapshotted when a run starts, never 409s): batch size 10/25/50, *Continue after a plan reset* (off), *Leave room in my plan* (off, set in the engine menu). "Read faster" is **not** built (owner, 2026-09-30): no parallel reading and no small-model map.
- **Machine-local state, never in a bank** (`sleep_local`: `$CICADA_HOME/sleep/<bank>-<hash>/`, 0700 dir, 0600 files, ids and counts and enums only, never a title): `run.json` (the run's sidecar), `parked.json`, `runs.json` (one summary per run, the newest 100).
- **Paused is a fact about a run, not a state of Sleep.** A run that stops with conversations still waiting (Pause = the cancel path, a plan limit, the engine going away, the reserve line, or a restart) leaves a `paused` record in its sidecar (`sleep_paused`); `status` stays `idle`, `is_writing()` is false, nothing is held. `POST /sleep/trigger {"continue": true}` rebuilds the drain from it (same run id, the frozen list minus what is filed, the counters carried, batch numbering from what was committed); **a no-body trigger stays a fresh run and clears it** (the documented curl); `POST /sleep/run/end` forgets it (409 while reading); `POST /sleep/parked/retry` unparks and reads exactly those ids (409 while running or paused). **The scheduler reads nothing while a paused run waits** — except a *scheduled* run's pause no person chose: a `restart`, or an `engine` pause at least 6 hours old, is ended (Past nights says `ended`) and replaced by a fresh unattended drain (`sleep_paused.schedule_may_replace`) — it still runs the engine-free tail (`run(tail_only=True)`: expiry, follow-ups, the state refresh, the polls, the link backfill; the after-import probe at most once a day), and the paused record stays on the wire meanwhile — and counts *readable* conversations (`sleep_debt`'s `readableCount` = waiting minus `parkedCount`). `sync_service`'s `sleep` component and the SSE event carry the pause, so the app hears it. Only the Sleep page continues a paused run (the app's doors route to it; the server stays permissive).
- **Honest live progress** on `drain` and the SSE event (every key optional): `startedBy`, `firstRun`, `calls` (each spawned engine call; only grows, a discarded batch's included), `elapsedMs`/`pausedMs` (measured, never a remaining time), `batchState`, `stages` (Read/Sort/Decide fill only from finished work; Notice and File carry no number), `byOrigin` (frozen = filed + read + waiting + couldNotBeRead + parked + skipped), a live `arrivedSince`, `ownerPage` beliefs, `reserve`. `GET /sleep/queue` serves the per-conversation rows from frontmatter only (≤ 200). Neither it nor `GET /sleep/run-options` / `GET /sleep/runs/{id}` is a Store domain (no `VersionVector` mapping; in-memory caches in the app, emptied on a bank switch).
- **The reserve is a soft stop** (`sleep_reserve`): Stage 1 stops *starting* reads once a plan window is past the line, what was read is filed, the rest is not an attempt; the run pauses with "Paused to leave room in your plan." A line, not a guarantee: overshoot is unmeasured, a window the engine never reports is served `enforced: false`, and the ChatGPT plan is read from the pre-flight snapshot each batch already takes. Off leaves the Claude rung's own R-E12 90% stop; a reserve lifts it for that run.
- **Continue after a plan reset** (`sleep_autocontinue`, ruling 15): a one-shot job per bank (`job_id`; a trigger or End in one bank never drops another's, and a bank's activation re-arms its own), for a run the person started, only after a 5-hour window (or the reserve on one, or extra usage) that gave a reset time, at most twice, within 36 hours, same engine, never weekly, never scheduled; `run(continue_from=…)` is called from the Continue route and this module only.
- **Past nights groups by run:** history rows carry `drainId`/`batch`/`batches` and a `run` summary (from `runs.json`; a paused run dropped without a Continue — a fresh Consolidate, an empty Continue, End, the schedule's replacement — is `ended` with its pause closed, and a restart records its open `restart` pause), and `GET /sleep/runs/{id}` (ETag) sums by `refs.drain_id` over every `llm_call` — models with the ledger's own stage names, plan windows per batch (a reset between two batches is never averaged away), pages touched. `SleepEnginePreview.billing` (`plan|charged|local`) lets the app word the spend without naming a provider.

**Disclosed asymmetries (not fixed here):** Stage 5.57's `recommends` person credit reads only the last batch's changes;
Home's "Last read" shows the last batch's pages. Details › Last cycle's cost line and "took" row still come from the newest history commit (one batch) — the run's own totals are in Past nights' run row. **Pause and a hard plan rejection mid-batch still discard the batch in progress** (no journal of paid answers — the tail must say "the part it was reading is read again", never "read and kept"). A scheduled drain pins its bank for hours (the same 409 as any run) and, on a metered engine, has no ceiling Cicada sets. The **app's own** Projects, Backlog and Fade-pace controls still key off `sleep.status == "running"` (`ProjectWriteGate`; `/status` does not carry `writing`), so they stay disabled, saying "Sleep is running", for the whole drain although the server would accept a write between batches. After a stop, Details says how many stay filed and never a batch count (the wire's `batches` is the plan); a cancelled or plan-paused strip and tail retire with the backend's cancel window and the vendor's reset time respectively. A drain on a consumer plan is the largest plan spend Cicada makes; the "leave room" reserve covers every window the engine reports (the 5-hour and the weekly one alike), is a line and not a guarantee, and a window the engine never reports is served `enforced: false`.

### Entity promotion
Entities are NOT extracted from every mention — that pollutes the graph. First mention stays in the
vector index only; promotion needs **2+ separate conversations**, OR substantive discussion (>3
exchanges) in one, OR an explicit link to an existing high-confidence entity. What Sleep hears about a
name before it has a page is not lost (G141 PJ-0b): Stage 5.56 holds those claims on the name's line in
`<bank>/pending_entities.jsonl` (`api/services/pending_store.py`: spans, not copies; at most 50 per name,
the rest counted) and releases them onto the page, first and through Stage 3, in the cycle whose Stage 5
gives the name one — a holding line leaves the store only then.

### Temporal decay
Absence of mention IS a signal, and **how often something came up sets how fast its absence
counts** (G147). Each Sleep cycle charges an unreferenced page at most one week
(`MAX_DECAY_DAYS_PER_CYCLE`, measured from `max(last_referenced, decayed_through)` — TODO ruling 1)
at **base × f(w) × the bank's per-type pace**: the base is the decay class's rate or an explicit
`decay_rate:` (G66); `w` is the number of distinct ISO weeks among the page's `source_episodes`
dates plus the weeks the person answered *keep* to a decay question (`kept_on`; every unparseable id
together counts once); `f(w) = max(0.25, 1 / (1 + 0.6·ln w))` (`decay_spacing_alpha` /
`decay_spacing_floor`) — fifty mentions in one afternoon are one week, and a page that came up across
twelve weeks fades about 2.5× slower. The per-type pace comes from `<bank>/_decay_tuning.yaml`,
written only when the person applies a suggestion in Settings → Memory; suggestions are derived from
the bank's own decay answers in git history (`GET /memory/decay-suggestions`) and never applied on
their own. One function, `decay_policy.effective`, serves the pass and the entity wire's derived
`decay` block. Claims fade the same way (`claim_reconciler._decay_claims`: weeks from the claim's
episodes and cited `ep_*` documents plus the subject's keeps; session ids carry no date and never
count). **An import is not silence:** a page or claim a cycle creates or references from months-old
episodes keeps that date as its content date (`last_referenced`, `valid_from`) but gets
`decayed_through` = the cycle's date, so silence counts from when Cicada learned it and a
multi-cycle drain of a backdated export never charges or archives what it just read.
Below 0.2 → `status: archived` (the page stays in `entities/`); below 0.4 → a decay nudge.
Mentioned again → promoted back at `confidence = max(current, 0.6)`. Evergreen entities skip all
decay math. **Confidence does not rank recall:** search puts archived pages last and otherwise ranks
by relevance (`search_service._page`'s sort key and the per-kind cut's archived tier); whether
confidence should weigh in is a question for G148's benchmark pass to measure before anything
changes.

---

## Storage Layer

### Markdown, not a database
Wikilinked `.md` files with YAML frontmatter, git-versioned. **The filesystem is the single source
of truth** — the API reads and writes the same files the Sleep cycle does. At personal scale
(hundreds of entities) the LLM follows wikilinks; it doesn't need Cypher. Zero infrastructure,
human-readable, portable, Obsidian-compatible.

### Entity schema

```yaml
---
type: person | project | company | concept | tool | deadline | skill | location | media | directory
status: active | decaying | archived | dropped
confidence: 0.85
created: 2026-01-10
last_referenced: 2026-03-22
decay_rate: 0.05           # per-entity, not global
decay_class: active        # evergreen | durable | active | volatile (G66)
source_episodes: [ep_2026-01-10_001]
tags: []                   # open set, freeform
related: []                # duplicates wikilinks for programmatic access
version: 3
---
```

**Entity types are a closed set of 10** (`api/models/schemas.py::EntityType`): `person`, `project`,
`company`, `concept`, `tool`, `deadline`, `skill` (procedural memory / preferences), `location`,
`media` (ingested item with an agent-generated summary), `directory` (a filesystem path, split out
from `location` in G18).

**Two exclusions matter (G17).** `deadline` still renders for legacy pages but is **no longer
produced by Stage-1 extraction** — `PRODUCIBLE_ENTITY_TYPES` excludes it; due-dates attach as a
`due` claim on the relevant project instead of spawning a standalone entity. `media` is likewise
excluded — it comes from the ingestion path, not conversation extraction.

**Status lifecycle:** `active` → `decaying` → `archived` → `dropped` (user-dismissed, never
resurfaced).

### Decay classes (G66)
One resolver, `api/services/decay_policy.py`. `resolve(fm)` returns `(class, rate)`: an explicit
`decay_class:` wins; otherwise inferred from `type` (`media` → evergreen, `skill` → durable, else
active) so legacy pages keep working. An explicit numeric `decay_rate:` still wins for the three
decaying classes; `evergreen` pins its rate to `0.0` unconditionally.

| Class | Base entity rate/wk | Claim multiplier | Meaning |
|---|---|---|---|
| `evergreen` | 0.0 | 0.0 | Never fades. Artifacts (media/bookmarks) + anything the user pins. |
| `durable` | 0.02 | 0.5 | Stable preferences, skills, long-lived concepts. |
| `active` | 0.05 | 1.0 | Default for a belief about the user's life. |
| `volatile` | 0.15 | 2.0 | Expected to change within weeks (role, status, current focus). |

**Anti-pollution rail** (mirrors `PRODUCIBLE_ENTITY_TYPES`): Stage-1 may propose
`durable|active|volatile` and **never `evergreen`** (`AGENT_PRODUCIBLE_DECAY_CLASSES`, enforced at
extraction AND again in the create branch). Evergreen is reserved for ingest writers and the user,
so an over-eager extractor can never stop the graph from archiving.

**Both engines honor it.** `conflict_resolver.resolve_and_prune` skips evergreen entities outright —
no decay math, no nudge, never auto-archived, so a bookmark can't generate a "still interested?"
question. `claim_reconciler._decay_claims` multiplies its per-epistemic × source_trust rate by the
SUBJECT's class multiplier. Since G147 the class rate is the *base*: both engines multiply it by the
spacing factor and the per-type pace (see Temporal decay).

### Claims, evidence and provenance

**Claims** are the machine-legible half: typed predicates, bi-temporal validity, observer and trust.
A predicate the vocabulary marks multi-valued (`predicates.cardinality`) never opens a conflict.

**Contexts and the fence (F1).** `context` is an open vocabulary whose *shape* is pinned by
`claim_contexts` — a short lowercase slug. Any other value (G60's `as of <date>`) keeps its job as a
claim key but is never a graph satellite, a legend row or an edge colour. `general` means "no
particular context" and is never a facet: a satellite needs two real contexts. The claims fence sits
after a page's last section (`write_claims`, the one writer), so **every reader strips it before
sectioning** — `strip_claims_block` on the server, `EntityProse` in the app.

**Evidence spans (G118) — spans, not copies.** Every claim written since that slice carries
`evidence: [{episode, start, end, kind, hash}]`. `start`/`end` are character offsets into the source
document's *evidence text* (the body as `markdown_parser.parse` returns it, with the ```claims fence
stripped for an entity page, so writing a claim never stales its own span); `hash` is
`sha256[:12]` of that text, and a mismatch reads as `stale` rather than mis-highlighting. `kind` is
one of six: `user` | `assistant` | `page` | `speaker` (a meeting participant who is not the owner,
G134) | `media` (what a video said — a watch record's timed `video [m:ss]:` line, G140; its position
in the video is derived at read, never stored) | `reasoning` (the contributor's own inference:
`start == end == -1`, never a faked span); an episode's `evidence_kind: user|assistant` (a folder's
authorship rule, R-F2; a Claude memory export is always `assistant`, its lines being `system:`) overrides the line markers. One marker grammar, `evidence._marker`, reads
both line families, plus the chat importer's `attachment [<file name>]:` turn — the text Claude extracted from an
upload, every line quoted (`> `) so it can open no turn — which is `page`, never the person's words. One module, `api/services/evidence.py`, does the work for every writer: locate
is exact → whitespace-normalised → case-insensitive and **never fuzzy**; an unlocatable quote
becomes `reasoning` and **the claim is still written — provenance never blocks memory**. Legacy
claims carry no `evidence` and `to_dict` omits the empty key; there is no backfill.

**Events (G141).** Two predicates, `happened` (ongoing | done | dropped) and `milestone` (planned |
done | missed | dropped), with four optional fields omitted when empty — `status` (as of
`valid_from`), `target` (a milestone's planned date; expiry never reads it), `participants`
(`[{role, surface?, entity?, url?}]`, a closed role set; `surface` is an exact substring of the plain
sentence — no wikilinks in YAML) and `date_basis` (stated | turn | episode | person | written). A
done happening is **born closed** (`valid_to == valid_from`), so every reader that treats open as
current stays right; the history readers call `claims.is_event` (a grep gate enforces it). Events are
not records: they stay in FTS and citations, where they read as dated happenings, never 'no longer
current'. A milestone's slot is `(subject, milestone, slug)` across observers — the slug is its
`object`, never its `context`. Event cardinality is multi and lives in code. **Only `progress.py`
writes an event**: `write_claim` refuses the predicates, `claim_pipeline` relabels a stray label.
Dates are decided by `when.py`'s closed table; nothing relative is stored. `companion_app` is a
human origin (G141 R-PJ18): only `routers/projects.py` sets it (and the synthetic demo, which replays
app writes), no MCP tool accepts an `origin`, and `is_human` protects the person's milestones and Log
entries — an agent's different state on them coexists with a divergence item.

**Stated ends (G140).** A claim may carry `expected_end` — the date the fact itself says it stops
being true — and a G17 `due` claim's ISO-date object is its own. Never a future `valid_to`, which
every reader takes to mean *closed*. Sleep's engine-free tail closes such a claim the day after its
end (`claim_expiry`), in its own `Expiry <date>` commit (`Cicada-Author: cicada`, trigger
`sleep/expiry`); a failed commit restores the pages rather than leaving them for the next
`git add -A` writer. An agent withdraws a claim IT wrote with `cicada_retract_claim`: the claim
closes and a born-closed `retracts` record keeps the reason and any cited words; a human or Sleep
claim is never an agent's to withdraw.

**Reading provenance back (G118 slice 2, server half).** Three engine-free, bank-only reads, all
built in `api/services/provenance.py` and fetched on demand — none is a Store domain, so each ETag
serves the client's in-memory cache and there is no `VersionVector` mapping: `GET
/episodes/{id}/text` (the whole evidence text, capped at 400,000 chars, with `turns[]` from the
same marker lines `speaker_kind` reads — `speaker:<label>:` included, role `speaker`; a timed
`video [m:ss]:` line is role `media` with its `t` in seconds, as a span's `t` is — each turn's
role the `evidence.kind_for` answer, so an `evidence_kind` override relabels every turn — and an
asserted `start/end/hash` or derived `focus=<entity>`), `GET /entities/{id}/provenance` (contributors from claim `authored_by` plus one
trailer-only `git log` of the page — ETag includes `git_head` — conversations grouped by
`session_id`/`source_id`, the best quote per conversation, coverage over current claims), and `GET
/episodes/{id}/citations` (every claim citing the document, by a raw-text prefilter over
`entities/` — no index dependency). `/ask` citations also carry `claimId` + `evidence`, read from
the cited page rather than the index. Every claim on the wire is built by one function,
`transclusion_resolver.claim_to_model`, and carries `authorKind`/`authorProvider` from
`git_service.author_identity`. **Freshness is one rule, `evidence.span_status`:** `current`,
`grown` (an episode that was appended to after the span was minted — the Stop hook and G20 both
rewrite that way — and a turn-boundary prefix still hashes to the stored value, so the offsets are
exact) or `stale`. A stale span travels without wash offsets; a `derived` span (found by name,
`inbox_context.locate_mention`) exists on read payloads only — never in `EVIDENCE_KINDS`, never
written. The chat importer and every Local-sources draft keep each turn's time as
`turns: [{offset, ts, speaker}]` in frontmatter, written by `episode_staging` outside
`content_hash`; the Stop hook writes the same list (G141 PJ-4), and a reader treats any non-list — an
older Stop-hook episode's count — as no times. Round 4 (C2–C4):

- Every claim on the wire also carries `recordedTs` (stored on MCP writes only), and
  `authorModel`/`authorEffort` for a harness write. These are joined by
  `turn_authorship.TurnAuthorship`: the claim's session → its capture episode → the last person's
  turn at or before `recorded_ts` → the agent turn that answered it, with both sides floored to the
  second.
- An `assistant` span carries its turn's `model`/`effort`.
- A harness contributor lists `models: [{model, effort?, beliefs}]`.
- `/episodes/{id}/text` carries `agent` (the most recent agent turn's, null when that turn names
  neither) and per-turn `model`/`effort`.
- A watch episode's `/episodes/{id}/text` also carries `watch: {basis?, engine?, fidelity, authorModel?, authorEffort?}`
  (G162; `fidelity` is `approximate` for `video_link`, `other` and an absent engine, else `verbatim`; the model is the
  same turn join, from the `describes` claim that cites the episode) and each `media` turn its `fidelity`; `/citations`
  rows of kind `media` carry it too.
- `claim_to_model(claim, *, turns)` takes the request's join as a required keyword.
- `AUTHOR_SHAPE` also rides `/episodes/{id}/text` and both `/projects` ETags.

**Optional frontmatter keys**, each with a narrow meaning — don't conflate them:

- `repos:` — links a project/directory entity to local git checkouts. The page only ever *declares*
  which repos; **the backend never runs git, stats or resolves a declared path**. `GET
  /entities/{id}/repos` serves the declarations (path exactly as written), `this_device`, and per repo
  `on_this_device` — `local_refs.is_this_device`, the one device rule: no device or a word like `Mac` is this
  Mac, else any of its host, local host or computer names, folded (case, `.local`, punctuation); the app's
  `GitRunner` runs one fixed read-only list (`repo_context.REPO_COMMANDS`, pinned on both sides by
  `api/tests/fixtures/repo_commands.json`; CLT/Xcode/Homebrew git, never the `/usr/bin/git` shim) in the
  ones on this Mac and posts the raw outputs to `POST …/repos/observed`, which refuses any undeclared path
  and parses them with the one parser, `repo_context.parse_snapshot` (a refusal is `denied`, and the card
  names Files and Folders). Only the last observation per `(path, device)` is kept —
  branch, dirty, ahead/behind, status, when — in `$CICADA_HOME/repos/<bank>.json`, **never in a bank**.
  `_state.md` renders that cache: `repos_probed_at` is the oldest observation shown, one older than 7
  days reads `state: stale`, and no time sits inside a block (R1). The MCP tool `cicada_repo_context`
  still probes live, in the process the agent harness launched.
- `sources:` (G61) — *where to look a fact up*, distinct from `source_episodes` (where a belief came
  from) and from the body's `## Links`. Keyed on `(ref, predicate)`, so one link can serve two facts.
  A conflict card's `hint` is **derived at read** from them (`fact_sources.served_hint` — the wire,
  the MCP render and the lexical row), never stored since G61 phase 2 S0, and its voice follows
  `added_by`: "You said …" only when the person added it; "Claude Code added …", "Cicada found …",
  "An agent found …" otherwise, the ref always in the sentence. An older item whose sources no longer
  match keeps its stored hint. Each entry is `{ref, kind: url|path|note|app|repo, predicate?, access?,
  added_by, added_at, accepted?, only_me?}` (phase 2 S1): `access` (`public|signed_in|local|unknown`)
  is stored only when stated, else inferred at read (`fact_sources.effective_access`: a refused or
  login host is `signed_in`, a path or repo `local`, an app `signed_in`); `accepted` marks an
  agent-found source the person took; `only_me` is the person's "Only I know" for one predicate —
  never a hint. The person's repeat of an entry applies those three; an agent's never changes one.
  Stage 5.56 attaches a URL found verbatim in a new Stage-1 claim's cited span as a source for that
  predicate (`added_by: <model>`, zero LLM) when the predicate's `locus:` is `world` or `artifact` —
  the vocabulary's where-the-truth-lives marking (seed + bank map, the most conservative winning:
  `person` > `artifact` > `world`; unseen is `unknown`). Nothing is fetched. An `addressbook://` ref reads
  'Their card in your Contacts (…)' (R-SR16), and the entity card names it "Their card in Contacts", the id only in
  the tooltip (DR-54).
  **A living set (G61 S3-a, 2026-09-30).** A page holds MANY sources, per fact, capped (`MAX_SOURCES` 30, `MAX_PER_PREDICATE`
  8; past a cap an agent's add is refused in words, the person's never is). `fact_sources.rank` is the one function every
  reader that must pick uses (the person's, then one they took or Cicada's read confirmed, then Cicada's, then an agent's;
  the owner's own page counts only what the person added or took); `source_trusted` is the trust rule. Three more optional
  keys on an entry: `origin: remote:<id>` (a connection's own entry — what ownership compares), `entity: <page id>` (the page
  that knows more about this source — its own memory node; validated, never creates a page, a stale id reads as none) and
  PR2's `verified`. **Ownership:** an agent (`cicada_change_source`) changes or removes ONLY an entry it added
  (`fact_sources.owns_source`); never the person's, one they took (`accepted`), an `only_me`, Cicada's own or a Sleep model's,
  and the unidentified `agent` label owns nothing; a connection owns exactly its `origin`, a local agent never a remote app's
  and the reverse. **Removal is remembered:** the entry leaves `sources:` and a row joins the page's `sources_removed:` (≤ 20,
  newest kept; `{ref, predicate?, by, at, reason?}`; git keeps the history, the row is what makes it stick; a replace
  (`new_ref`/`new_predicate`) tombstones the old key too). Today the writers that respect it are `attach_cited_urls`, `cicada_write_claim(sources=)`,
  `cicada_add_source` and Cicada's own DOI/skill-page adds (a refusal there never fails the page write); and (G61 S3-b) Stage 1's site proposal (`fact_sources.propose_site`) and the website backfill (`site_sources`).
  `website` matches by site. An agent's
  add (`cicada_add_source`, `write_claim(sources=)`) is refused what the person or Cicada removed but may put back what an
  agent removed, and the reply says who removed it and why; the person's add clears the tombstone, and the person's removal
  (`POST /entities/{id}/sources/change`, or the older index DELETE) writes one too. A ref the scrub would alter is REFUSED, not
  stored redacted. `entity_merge` carries `sources` and `sources_removed` to the winner and repoints other pages' `entity:`.
  `entity:` is filled for existing sources by exact match only (`source_links`: a URL whose `url_hash` is a saved page's, a path
  equal to a directory page's own frontmatter `path:` exactly — not a path found in its body), never over a set link or one the person
  or an agent explicitly cleared (`entity_unlinked: true`, stamped by an unlink, removed by a later link or replace), on the Sleep tail and `POST /maintenance/link-sources`, one
  `cicada`-authored commit (`Source links <date>`, triggers `sleep/source-links`, `maintenance/source-links`). The graph draws a
  linked source as a read-time edge labelled by its predicate (never persisted, like `has repo`; `kind: "source"` on the link,
  which the person map and "What's happening" skip — a source is where to look, not a relationship); the card's row wears the linked
  page's picture and offers "Open page ›". The person's three source routes answer 409 while Sleep runs; `cicada_add_source`
  is refused then too (it used to write uncommitted). A Contacts card row offers only Remove on the card.
- `website` (G61 S3-b) — the official-site ROLE: a `sources:` entry with `predicate: website`, many allowed. Stage 1 may
  propose ONE for a `company`, `tool` or `project` (an optional `website` field on the extracted entity;
  `site_sources.sanitize_website` keeps only an https origin of a public host that is not a platform (`PLATFORM_HOSTS`:
  code hosts, encyclopedias, social, profile and article hosts) or a walled one, and drops it for every other type); the
  create branch stores it UNVERIFIED (`added_by: agent`, no network), never over a tombstone. An engine-free backfill
  (`site_sources.candidates`) proposes one for a page that has none from ONLY its own current `website` claim or a
  `## Links` URL whose host is the page's own name (or whose title says official/homepage/website) — never a domain
  guessed from a name. Cicada's own read confirms it (`link_enrichment.fetch_identity`, sharing `_stream_html` with
  `default_fetch`: 4 s, ≤ 512 KB, no cookies, `net_guard`, a block never retried; a walled or platform host is refused
  before any request): `judge` needs the page's name (or an alias) whole-word in the site's title or `og:site_name` AND
  two distinctive words of its own summary on the page. Outcomes (D1): `verified` stamps `verified: {at, how}` and
  `access: public`; a `mismatch` or `walled` site is removed and remembered (`sources_removed`, by `cicada`, with the
  reason); a thin page keeps it `checked: {outcome: unconfirmed}` ("not confirmed", re-read after 30 days, one tap of
  "Use this site" = `accepted` trusts it); a network failure is `tries` up to three nights, then dropped and remembered.
  `fact_sources.trusted` (the person's, one they took, or verified) is the only trust; nothing else draws a picture. The
  Sleep tail step (`sleep_cycle._site_sources_safely`: propose, then verify, ≤ 25 fetches a night, one per site) runs
  behind `CICADA_ALLOW_CONNECTOR_FETCH`, in one path-scoped `cicada` commit `Site check <date>`, trigger
  `sleep/site-check`, no engine trailer, dirty pages skipped, a failed commit restores; `POST /maintenance/verify-sites`
  is the person's click (ungated, ≤ 100, 409 while Sleep runs, trigger `user/companion_app`), counts only.
- `logo:` — a domain hint for `logo_service`. Logos are cached under `$CICADA_HOME/logos/<bank>/`,
  **never inside a bank** — a logo is a derived artifact of the outside world, not versioned memory. Since G61 S3-b a
  page's domain comes from a source and never a guess: `logo:` first, else the first TRUSTED `website` source
  (`logo_service.domain_for`); no `## Links` fallback, no saved link's site, no `website` claim, no `<name>.com` guess,
  no platform or walled host, and never a `person` or `media` page (G146/G159). `LOGO_RULE = 2`: a bank's cache written
  under the older rule is purged ONCE (`ensure_rule`, marker `logos/<bank>/.rule`; `sites/` is spared), and a page that
  no longer resolves a domain drops its cached mark and records a miss. `GET /entities/{id}/sources/icon/{site}` serves
  the mark of a trusted site THIS page lists (icon service only, keyed on the site, never a ref).
- `picture:` (G146) — the person's own choice of picture for a page: `{kind: upload, sha, ext, added}` for a
  picture they uploaded, whose bytes live **in the bank** at `assets/pictures/<id>.<png|jpg>` (their record, so it
  travels with the bank; the path is derived from the id, never read from the page), or `{kind: initials, added}`
  for "Use initials instead". Written only by `POST|DELETE /entities/{id}/picture` and `…/picture/initials`, each
  committed alone as `user`, 409 while Sleep runs; never by an agent. The app shrinks a picture to ≤ 512 px before
  it leaves the Mac; the server keeps only a PNG or JPEG ≤ 512 KB (no Pillow). `entity_picture.resolve` is the one
  precedence (the person's choice → a person's Contacts photo → a brand's logo → a media page's thumbnail → a ring
  monogram), resolved at read onto `/graph` nodes and the entity; the app's `EntityPictureResolver` is its twin over
  `api/tests/fixtures/entity_picture.json`. A person never gets a logo and no service is sent a person's name (G159).
- `contacts_photo:` (G154, read by G146) — `{sha, ext}` on a `person` page Contacts matched (`ext` jpg|png, jpg when
  absent); the thumbnail itself is a cache at `$CICADA_HOME/pictures/<bank>/contacts/<id>.<ext>`, never in a bank.
  Written by the Contacts sync only (`contacts_local.photo_path`, the same path `entity_picture.contacts_path` reads).
- `owner: true` (G117) — marks the one `person` page as the bank's owner; `owner_identity.
  resolve_observer` is what decides which page gets it, and every user-stated claim's `observer`
  field is that resolved value. **Every new bank starts with it** (`bank_registry.create_bank` →
  `owner_identity.seed_owner_page`, its own `cicada` commit; never the demo, which writes its
  own): the machine-level name from `owner.json` when one was saved (a name and an id, never
  another bank's knowledge), else a neutral `Owner` page (`owner_placeholder: true`, id `owner`,
  the id `resolve_observer` already answers with) opening "The main person this memory belongs
  to." `name` stays the plain name — Stage 2 matches a mention to a page by `name`, so a stored
  "(you)" would stop the person's own name from resolving — and the app renders "Name (you)" from
  the flag. `PUT /settings/owner` **adopts** a placeholder (renames it, keeps its id and claims)
  instead of writing a second owner page. Beliefs accrue through chats and consolidation. The
  first-boot default bank is scaffolded by the lifespan, not `create_bank`, so the lifespan seeds it
  the same way when it is brand new (`seed_owner_if_brand_new`: no entity page, no episode). Because
  a bank now starts with one node, **the app's empty means "no node but the owner's"**
  (`hasNoContentBeyondOwner`: `FirstRunGate`'s graph input, the Graph's and Clusters' "Nothing here
  yet"); the `/banks` `entityCount` of a new bank is 1.
- `kept_on:` (G147) — the days the person answered *keep* to a decay question; each joins the page's
  mention weeks, so a kept page fades a little slower. Written only by the decay resolver, deduped,
  capped at 52. Not an episode id and never read as one.
- `paths:` (G133) — on a `project` page a watched folder anchors: `[{path, device}]`, where that
  folder lives on which Mac. For display and relink only; the backend never opens it.
- `media.kind: paper` + `paper:` (G133) — a paper page: `arxiv_id`, `doi`, `authors`, `published`,
  `venue`, `sections`, and `metadata_status` once a lookup failed. The ids are the identity
  (`media-arxiv-<id>` / `media-doi-<hash>`); the abstract is a `describes` claim from
  `external:arxiv` or `external:crossref`, a dated cache shown under the personal tier (G121).
- On an episode (G133/G134): `turns` (the G118 per-turn sidecar), `evidence_kind`,
  `source_deleted_at`, and a section's `content_sha` — see the Awake rails.

### Backlogs (G150)

A project's backlog is memory, not a table in some repository: **one markdown file per item** at
`<bank>/backlog/<project-id>/<item-id>.md`. Frontmatter: `id`, `title` (the brief task), `project`, `status`
(`open | doing | done | dropped`), `triage` (`apply | research | decide`, optional), `paid` (the 💸 flag), `created` /
`updated` (the machine zone's days), `added_by` (`user` | a harness label | `cicada`), `session`, `links: [{kind:
pr|commit|url|doc|entity, ref}]`, `order` (hand-set), and last a `notes: [{at, by, session}]` sidecar. Body:
`## Description` (the reasoning) then `## Notes`, append-only `### <day> · <who>` entries — a status move is itself a
signed note, and a note is edited only through git history; any heading inside a text is demoted so it can never forge
a note. **Never an entity page**: Stage 1 never extracts one, it never decays, and the writer never touches
`entities/`. Ids are `<PREFIX><n>` like G-ids — the project page's `backlog_prefix:`, else the prefix most of its items
share (an imported G-row list continues its sequence), else the name's initials (`Orchard` → `ORC`) — max+1, claimed by
an exclusive create (the backend and every stdio MCP process mint in one folder). **One writer**,
`api/services/backlog.py`, behind every door: REST (`routers/backlog.py` — `GET/POST /projects/{id}/backlog`,
`POST /projects/{id}/backlog/import`, `GET/PATCH /backlog/{project}/{item}`, `POST /backlog/{project}/{item}/notes`;
409 while Sleep runs; each write commits alone as `Backlog update <day>`, `Cicada-Author: user`, trigger
`user/companion_app`, an import as `Backlog import <day>`, `user/backlog_import`), MCP (`cicada_backlog` read;
`cicada_add_backlog_item` and `cicada_add_backlog_note` record — the harness as author and the conversation as
`Cicada-Session:`, refused while Sleep runs and in a demo bank; a remote connection without `sources` is told the
person's own words exist, never shown them), the importer (`backlog_import.py`, `scripts/import-backlog.sh`: G-row
tables and `### G<n>` sections, ids and statuses kept, an id already filed skipped) and the demo. Every text is
scrubbed (writer `backlog`), and an open item whose title matches a new one exactly refuses the new one — one row per
idea, later findings are notes. Both reads ETag over the `backlog` sync component (a stat walk) and `entities`; neither
is a Store domain (`BacklogCache` in the app, like `ProjectsCache`). A note's model and effort are joined to its turn at
read once round 4's per-turn join lands; until then a note names its harness.

### Live state + handshake (G53 / G75)

**`<bank>/_state.md` is a *cursor* into the graph, never a copy of it** — YAML frontmatter plus a
short wikilinked body, ≤ 6 KB, zero LLM, deterministic. Written only by
`state_dictionary.refresh`. A digest of the `entities`/`inbox`/`episodes`/`bank`/`backlog` sync components is
stored as `inputs_version`; unchanged inputs mean no write. **Never `git_head`** — its own
`State snapshot` commit would self-invalidate.

Every regeneration that touches disk goes through `state_dictionary.refresh_and_commit`, which
commits `_state.md` ALONE (`commit_paths`, never `git add -A`) as `State snapshot <date>` /
`Cicada-Author: cicada`. **The read path commits too, on purpose:** a projection left dirty "for
Sleep's tail" gets swept into the next `git add -A` writer's commit under the wrong author — the
G85-class smear. `sleep.next_at` is computed per request, never persisted: in the file it advanced
every day and made every idle night commit.

**`_state.md` schema v3 (G141):** each of the top 7 project rows gains `next: {slug, name, target}`
and, once happenings exist, `now: {claim, text ≤ 80, since, verbatim?}` — the first claim text the
file holds; `verbatim` marks the person's own Log sentence, which a remote primer shows as 'a note of
yours' without `sources`. Neither field depends on today, and `_fit` drops every `now` before it
drops a project. **v4 (G150)** adds `backlog_open` (items open or doing) to a project row that has any, and
`backlog` joins the input components; the primer's Current row says "backlog: n open" under the same gate as
`now`/`next`. Contract item 3 names the backlog tools (CONTRACT_VERSION 8 with G149's item 8; each branch alone had taken 7).

**The handshake** (`api/services/handshake.py`) turns `_state.md` + a fixed contract into ≤ 1,800
tokens of primer: what Cicada is, a per-harness prelude (the contract never varies), the contract
itself, the now-view, and capability notes. The now-view is **Standing** — the person's page and
one-liner (through G117's resolver), their timezone (per request, never in `_state.md`, part of the
cache key), *How to work with me* (standing `skill` pages by confidence alone), long-standing
durable/evergreen pages — then **Current** — projects, each project with its `now`/`next` (G141),
pages in focus in the last 14 days, people, recent conversations (G140, schema v2). A test holds R12 for every argument either primer names, for
every remote scope set. Contract item 3 names `cicada_note_progress` (G141 PJ-3a; remotely only when the
connection holds it). Delivered four ways: the MCP `initialize` result's
`instructions` (which Claude Code truncates), the `cicada_handshake` tool, `GET /handshake`, and the
SessionStart hook's `additionalContext` under a "From Cicada" header (G149). Contract item 8 tells an
agent what a "From Cicada" note is. **R12: a primer naming an
argument the schema rejects is a bug** — every argument it names must exist in the tool schema.
`SKILL.md` points at the generated text rather than restating the contract — one prose source.

**A reader that finds `_state.md` stale or absent must still work:** every field has a live twin
(`/status`, `/inbox`, `/conversations/recent`, `cicada_repo_context`).

### sqlite-vec (vector index)
`api/services/vector_index.py`. Embeddings are **stored, not recomputed at query time**, so search
is one in-process ANN lookup. Default backend is EmbeddingGemma-300M (768-dim, on-device) with
asymmetric query/document prompts. The index is **derived and disposable** — synced by Sleep from
markdown, safe to delete at any time. **The sync is incremental** (`SqliteVecIndexer._sync_kind`): each
row keeps a stable `key` and the `hash` of the text that was embedded, so a cycle embeds only new and
changed texts, removes deleted ones and refreshes a page's metadata in place without an embed; a missing
table, a pre-`hash` schema, another model (recorded per kind as `model:<kind>`) or another width rebuilds
that table in full, and an embed that fails leaves the previous index untouched. Sleep runs the blocking
sync through `asyncio.to_thread`, never on the event loop.

### SQLite FTS5 (lexical index, G136)
`api/services/search_index.py`. One `search_index.db` per bank, **beside `vector_index.db` and never
inside it**: entity names + aliases + prose, every claim (superseded ones kept as history), episode
titles + 600-character passages that tile the evidence text exactly, media/paper metadata, inbox
questions and backlog items (G150), in seven per-kind FTS5 tables (`unicode61 remove_diacritics 2`, prefix `2 3 4`; rowid
`doc_id << 16 | n`). `dropped` pages are never indexed. **Derived and disposable** (TODO ruling 3):
deleting it costs a few seconds of CPU and never a fact; a missing, corrupt or schema-mismatched file is
rebuilt, never an error. **Never tracked:** `bank_registry.ensure_derived_excluded` writes
`.git/info/exclude` before the file first exists. It follows a worktree or submodule bank's `.git` file
to the real git dir, and a new bank's `.gitignore` lists the file too. It never edits an existing
`.gitignore`, which would dirty the tree and smear into the next `git add -A` commit. **Freshness:**
Sleep brings it up to date beside the vectors (`search_index.refresh`, off the event loop — the
stamp diff `ensure_fresh` uses, so an idle night re-indexes nothing; a full build only when the file is
missing, damaged or of another schema); every read path calls `ensure_fresh`, a `bank_index` stamp diff
(at most one check a second, inline up to 64 changed files, one background worker beyond); the
lifespan and a bank switch warm it in the background. The caller always passes the active bank's path
— the module never resolves a bank (the split-brain rule). `search_service` ranks over it (QuickMatch
tiers 0–2), fuses it with the stored vectors in `mode=hybrid`, and **never embeds in `mode=prefix`**.
**The query is never logged**: not by loguru, and not by uvicorn's access log (`api/main.py` strips the
query string of `/search` and `/conversations/recent`, G136 R22).

### Telemetry ledger (`~/.cicada/telemetry/`)
Append-only JSONL, machine-global, **never in a bank or git**. `CICADA_TELEMETRY=off` disables it.
**IDs and enums only — never claim text, query text or answer text.** The `read` kind (G124) records
an entity id and a surface enum, filed in a sibling `reads-*.jsonl` that
`sync_service.components["telemetry"]` deliberately does not stat — the app maps that component onto
its consumption domain, so a card open must not move it. The `hook_recall` kind (G149) is one row per
recall-hook firing: harness, event, reason enum, the page ids and their count, token and latency buckets,
and the model id when the harness sends one. It is filed beside `read` for the same reason, and like
`capture` it is a per-turn receipt that `consumption_stats._activity` keeps out of every Usage view. The
prompt never is. The `read_agent` kind (G166) is one row per `cicada_record_read` call — entity id, an `outcome` enum, a
`host_class` enum (`walled | public`), the harness and connector id; never a URL, the tool the agent named, a note or an
excerpt — filed beside `read` and kept out of every Usage view like `capture`. The `video_queue` kind (G162) is one row per claim, release or completion — `action`, `count`, a
closed fail-code enum, the harness and connector ids; never a link, a title or a reason — filed beside `read` and kept
out of every Usage view (`SIBLING_KINDS`, `NON_SPEND_KINDS`, `PER_TURN_KINDS`).

**Cycle usage (2026-09-28 ruling, Sleep page only).** Every `llm_call` a Sleep cycle makes carries `refs.cycle_id`
(from the ambient `sleep:<id>` scope, so it survives `to_thread`/`gather`; the engine-independent tail runs outside
that scope and is never counted), and the cycle's `sleep_run` gains `usage_tagged: true` plus, when observed,
`plan: {connection, windows: [{window, before, after, resets_at, before_is_first_seen}]}` — numbers and enums only.
Claude's windows come from the calls' rate-limit signals (`before` is the value after the first call); the ChatGPT
plan's from two fresh app-server snapshots bracketing the cycle. `api/services/cycle_usage.py` derives `usage` for
`GET /sleep/history/{commit}` and `usageSummary` for `GET /sleep/history` at read, joined after the git cache; every
figure carries its basis (`charged` | `list` | `plan` | `free`), and a cycle without the marker reads `null`, never zero.
The Sleep page's Details (Last cycle, Past nights, an opened cycle's Models) and the engine menu's captions read them
(2026-09-28 ruling); a `plan` block and a `cycle_id` are numbers and ids, never text.
Since Sleep page v5 a drain's calls also carry `refs.drain_id` (the run's id, ids only), so `GET /sleep/runs/{id}` sums a whole run — a paused or discarded batch's calls included — and `sleep_run` rows carry `drain_id`/`batch`/`batches`; `usage_for_drain` lists a plan window at the run level only when every batch saw the same reset time.

**Feedback events (G113):** every inbox resolution emits a `resolution` event (`stage: feedback`,
`refs` = item id, kind, predicate, entity id, action label, `verdict: agreed|overruled|neutral`,
winner/loser claim ids, the extractor's confidence and model — ids and enums only, never claim
text), Stage-3 reconcile emits one `audit` event per supersede/reject, and the dedup sweep emits one
`dedup_verdict` per judged pair. `telemetry.FEEDBACK_KINDS` names the three (a superset,
`NON_SPEND_KINDS`, also excludes `capture`/`handshake`/`read`); `consumption_stats.stats()` excludes
them from `by_connection` so they never show as an "unknown" connection. Nothing learned from the
ledger is auto-applied — `GET /consumption/feedback` shows the rates; feeding them back into
prompts is G78.

### Git — versioning and provenance

Every Sleep cycle commits with a **machine-parseable message**:

```
Sleep cycle 2026-03-20

entities/recruiting-thread.md: updated (source: ep_2026-03-20_002, trigger: sleep/extraction)
nudges/nudge_005.md: resolved (trigger: user/companion_app)

Cicada-Author: gpt-5.4-mini
Cicada-Engine: claude-cli
Cicada-Session: <id>
```

**Triggers:** `sleep/extraction`, `sleep/promotion`, `sleep/conflict_resolution`, `sleep/decay`,
`sleep/state`, `sleep/expiry`, `sleep/followup`, `sleep/source-links`, `maintenance/source-links`, `sleep/site-check`, `capture/calendar`, `capture/tab-groups`, `capture/contacts`, `nudge/resolved`, `clarification/resolved`, `user/manual_edit`,
`user/companion_app` (also the Projects page's writes, G141 — `Project update <date>`,
`Cicada-Author: user` — and the Backlog section's, `Backlog update <date>`), `user/backlog_import` (G150's
importer),
`mcp/<harness>` (a local agent's write), `remote/<harness>` (a remote connector's write, G135).

**Three trailer families, all inert to entity-line parsing — extend them, don't break them:**

- **`Cicada-Author:`** — *which agent authored this*. A model id for agent writes, **a harness
  label** (`claude-code`, `claude-web`, `chatgpt`, …; `agent` when none was sent) for a write that
  arrived through MCP, where the model is not disclosed (G135; the trailer never names a model — since round 4 it is joined at read from the captured
  turn), the
  literal **`user`** for manual/companion-app writes, **`unknown`** for legacy untrailered commits,
  and **`cicada`** for system maintenance with no model and no user in the loop (the one-shot
  migrations, the split-out decay commit, the `State snapshot` commit, the `Expiry` and `Follow-ups` commits). Built by
  `git_service.build_commit_message(...)`, parsed by `_parse_authors`.
  `git_service.author_identity` buckets a harness label (and `agent`) as kind `harness`, which the app
  names and marks as that app; the pre-G135 `mcp-agentic-write` claim placeholder reads as `agent`
  through `canonical_author`, never rewritten (F2-back R-B9, R-B10). A read whose body carries an
  author kind folds `git_service.AUTHOR_SHAPE` into its ETag; bump it when the buckets move.
  Powers `GET /contributors`.
- **`Cicada-Engine:`** — exactly one per main commit (`claude-cli|ollama|litellm`), **omitted
  entirely rather than guessed** when no LLM ran. Read back via git's own
  `%(trailers:key=…,valueonly)` directive, not a Python parse of `%b` — pulling the whole body to
  extract one line grew the endpoint from 787 B to 378 KB for 8 commits on the live bank.
- **`Cicada-Session:`** — one line per distinct conversation consolidated, capped at
  `MAX_SESSION_TRAILERS` (50) by the call site, not the builder. User-action commits stay
  session-less.

**G85 — decay gets its own `cicada`-authored commit.** Temporal decay runs over entities a cycle
never referenced: no LLM, no source episode, pure arithmetic. Folding it into the main commit
stamped it with whichever model happened to run Stage 1/2, inflating that model's contributor counts
for work it never did. `_finalize` splits `sleep/decay` entity lines into their own commit —
`Sleep cycle <date> (decay)`, `Cicada-Author: cicada` — committed *before* the main commit so the
main commit's `git status` scan never sees them. A split that can't happen degrades back to the old
behavior rather than aborting the cycle. **Known asymmetry, disclosed not fixed:** the split is
path-granular, not hunk-granular, so a subject that is both decay-eligible and claim-touched in the
same cycle lands whole in the `cicada` commit. Narrow in practice; fixing it needs hunk-level
staging.

**A drain's commits.** Each batch is one `Sleep cycle <date> (batch k of n)` commit (k counts batches actually run, n is
recomputed from what is still waiting, so skipped ids shrink it; a lone batch keeps the plain subject — `_cycle_kind` reads
only a trailing `(decay)`). Its manifest lists only that batch's episodes, `Cicada-Session:` only that batch's
conversations (batch size ≤ 50 keeps every one), `Cicada-Author:` the models that batch used. The `(decay)` commit exists
once, in the last batch, before its main commit.

**One git writer per bank (F2-back R-B1 … R-B4).** Every mutating git command — `git_service`'s
commits, a `_run_git` write, the one-shot migrations, the expiry restore — runs in a worker thread
under one re-entrant lock per resolved bank path, so tasks, threads and `asyncio.run` bridges queue
instead of colliding on `index.lock`; the backend is one process, git's own lock is the cross-process
guard, and only its `File exists` refusal is retried (five tries, the lock never deleted). Reads pass
`GIT_OPTIONAL_LOCKS=0`, and `test_git_write_lock.py` refuses a git write spawned anywhere else.
A folder, paper or Wispr commit that still fails keeps its paths in `cicada-pending-commits.json`
in the bank's own git dir (a worktree's, never the shared common dir), says so on its channel, and
lands on that writer's next run — or at the start of the next Sleep cycle, before any stage writes —
under its own author (R-B5).

**Entity-level provenance uses `git blame`** enriched with parsed commit metadata; repo-level
history uses `git log`. **No changelog in frontmatter** — git handles all history, zero storage
overhead, no growing fields.

---

## MCP "Bookworm" Tool

The interface between any LLM and the memory system. On `initialize` the server returns the G75
handshake as `instructions`. On query: check `memory/inbox/` for relevant pending items → search the
vector index → search the markdown graph → follow wikilinks for relational depth → progressive
disclosure (cluster pages → entity pages → episodic sources).

**Recall (G140).** Three legs fused by one RRF (`search_service.rrf_fuse`): the stored vectors, the
FTS lexical leg (names, aliases and prose, word by word), and current claims mapped to their
subject — so an alias or a relationship label reaches its page. The top three pages carry a bounded
"Changed recently" block (claims closed in the last 30 days, ≤ 5 lines);
`cicada_get_perspective(history=true)` lists every earlier claim. **`cicada_timeline(since)`**
answers "what changed" from the commit manifests on demand — ids and counts only, nothing stored,
`read` scope remotely. **`cicada_record_watch`** records what an agent's own tools saw in a saved
video — a summary and ≤ 12 timestamped quotes as `media` spans; Cicada never downloads or watches a
video, and never keeps a transcript. **`cicada_project(project, since?, tz?)`** (G141 PJ-2, `read`
scope remotely) answers where a project stands — next milestones, what passed with no word, the Sleep
queue, what happened and what is around it — from the engine-free read model, printing every relative
word beside its absolute date ("yesterday (2026-09-22)"); a quote of the person's words needs
`sources` remotely. **`cicada_note_progress`** (G141) records a happening or a milestone the person
described — observer always the agent, `record` scope remotely, never creates a page, echoes how the date
was decided; `cicada_retract_claim` withdraws an event the same way.
**`cicada_add_source(subject, ref, predicate?, access?, kind?)`** (G61 phase 2 S1) records where a
fact can be checked when there is no claim to write — only a source the person named, never one the
agent guessed; it is not `cicada_sources` (conversations). `record` scope remotely, where a path, a
repo or `access: local` is refused; it commits alone under the harness. `cicada_write_claim(sources=)`
takes a string or `{ref, access}`. Since G61 S3-a (contract 12, remote 9) the primer names it, and takes an optional
`entity` (an existing page that knows more about the source). **`cicada_change_source(subject, ref, predicate, action,
reason, new_ref?, new_predicate?, access?, entity?)`** corrects (`update`) or removes (`remove`, `reason` required) a source
the caller added — keyed `(ref, predicate)`; `record` scope remotely, a remote caller never names a path, a repo or `access:
local`; refused with nothing written in a demo bank, while Sleep runs, for no such page or key, for an entry that is not the
caller's, for a ref that holds a secret; one commit under the harness whose manifest line names neither the ref nor the reason
(both are in the diff and the tombstone). Its ledger row is ids and enums only (`source_added|source_changed|source_removed`).
**`cicada_backlog`**, **`cicada_add_backlog_item`** and **`cicada_add_backlog_note`** (G150) read and file a
project's backlog — see Backlogs.
**Video watch (G162, TODO ruling 17).** `cicada_record_watch` takes three more arguments the agent states about its
own work — `basis` (`transcript | frames | both`), `engine` (`captions | video_link | local_frames | speech_to_text |
browser | other`) and `duration` (kept only when the page has none) — none verified (R-VU2: the app says "an agent recorded
that it watched", never "Cicada watched"); an unrecognised value is dropped and the record is still written. A repeat
of the same record with a new basis merges into the episode in place (`transcript` + `frames` is `both`; `content_hash`
and `processed` untouched). **A video's state is derived, never stored** (`video_state.py`): `none | transcript | watched
| watched_and_transcript | recorded`, the set-union over the `source: video-watch` episodes that name its link, matched by
the url-index key (`media_ingestor.url_hash`, never the media entity id); a record with no basis is `recorded`, never
`watched`. The set of videos is the Feed's (`is_video_page`, the twin of `FeedKind.of`, pinned by
`api/tests/fixtures/video_kind.json`). **The person's video queue lives outside every bank** —
`$CICADA_HOME/video_queue/<bank>.json` (`video_queue.py`; a bank name that is not a plain slug gets an ASCII slug plus a short sha1 of its name, never a refusal; orphans are dropped only while the url index answers non-empty; keys only, never a URL or a title; flock plus atomic replace;
expiry applied in memory and persisted inside a write) — so nothing in its lifecycle dirties a bank, commits, or answers
409 while Sleep runs. `cicada_video_queue` (`read`, read-only) lists what waits; `cicada_video_claim` (`record`) leases
the oldest queued videos (10 a call, 45-minute lease) or, with `release=[{url, code, reason}]`, hands one back
(`needs_login` tells the agent not to sign in and tells the person). It is in `WRITE_TOOLS` (the demo gate, the write
lock; only its per-video title/channel lines are fenced, Cicada's own instructions in the reply stay outside) but `runtime._writes_bank` is false for it, and **a lapsed lease is judged only when Sleep is not
holding the pages** (`ToolContext.pages_held()`, asked lazily), so a drain cannot burn a video's three attempts; while a
lapsed lease is due, the `videoQueue` stamp also carries that hold bit (`<mtime>:<due>:<held>`), so the hold ending moves
the component the app follows with nothing written. `VideoStateCache.reset()` on a bank switch keeps what a page asked
for (`asked`), and the switch reads the new bank at once.
`record_watch` credits the queue whether or not its bank commit ran. **No batch cap** (a hand-off takes every selected
video; the queue file's ceiling is 2,000 rows) and **no site list** (any saved video can be queued; a login wall is handed
back and surfaced). The hand-off prompt (`video_prompt.py`, ≤ 1,200 characters) is provider-neutral, names no browser
route by default, and carries the browser permission only while the single reading permission is on; the seam for "how
your agent watches" is `video_prompt.method_clause`. Recall and its hook are deliberately not extended for video. Contract
item 3 names all of it (CONTRACT_VERSION 11, remote 8, past G166's 9 and 6; remote names each tool only where held).
**Reading with the person's own agent (G166, spec `2026-09-29-reading-the-web-design.md` §8.4, Route A).** Cicada never
spawns a browser and never signs in (`test_reading_never_spawns_browser.py`, R-RW9: `--chrome` is in no argv). The
person's own agent — a local harness with a browser tool, or a remote connection that can drive one — reads through a
queue. The person's per-link **Ask an agent** (`POST /reading/asks`) is a row in
`$CICADA_HOME/reading_asks/<bank>.json` (`reading_asks.py`: outside every bank, no URL stored — joined at read from
`sources/url_index.json` —, 7-day expiry applied in memory, `fcntl.flock` because the backend and every stdio process
write it); an unsaved link is saved first *without a fetch* (`RawItem.defer_enrich`) as the person's own save.
`cicada_reading_queue(limit)` (`read` scope, fenced remotely) lists what waits: the person's asks first (oldest first),
then **saved pages of sites the person allowed** (below) — empty unless `reading.agent` is on, never a denied class,
**one entry per site per call** (the rest are counted). It is one read model, `reading_queue.py`, behind the tool, the hook
count, the Feed's `waiting` and the settings page: asks are rows, a site's pages are *derived at read* from
`reading_walls.py` (never fanned out as rows, so a site switch writes one line, a new wall page joins with no write and
turning a site or the master off dequeues at once). A site entry whose page was not saved through a saved-content channel
(Telegram, an agent's save, a chat export: the person's own words) is served only to a caller holding `sources`. `cicada_record_read(url, outcome, summary?, excerpts?, via?, note?, title?)` (`record` scope) takes `read |
needs_login | blocked | not_found | failed`. Only a **successful read is memory** (`page_read.py`): one episode
(`assistant:` summary, then a quoted `attachment [host]:` block, so quotes are `page` spans — text the agent
*reported*, never the person's words or checked by Cicada —, `processed: true`, `processed_by: agent`), one `describes`
claim (a re-read closes the previous one), a thin description filled, and a `read:` stamp on the page; it commits alone as
the harness and never mints a page. **Only a link the person asked about, or a wall page of a site they allowed, can be recorded** (`reading_queue.authorizes`: `("ask", row)`, `("site", None)` or nothing; a row this tool wrote itself, `origin: site`, authorizes only while its site is still allowed and the page still a wall page, so switching a site off revokes recording at once): `cicada_record_read` refuses every outcome for any other URL (a saved public page with no wall included), and `reading_asks.record_outcome` creates a row only for that site case (`create=True`, `origin: site`) — an agent, or a page steering it, cannot rewrite a saved link's description or plant a `needs_login` banner on a link nobody asked about or on a site nobody allowed. **The exposure, stated:** with a site grant the person consented to a *site*, not to a page, so any agent holding `record` can then record a wall page of that site; the structural denials (R-RW5), the master switch, "every outcome but `read` is ask-store only" and `page`-kind spans bound it. A site-origin `read` writes no ask row (the page's own `read:` stamp keeps it out of the queue) and site rows are evicted before any explicit ask (`MAX_SITE_ROWS` 200). A `read` is also refused while Sleep runs on stdio, as the remote path refuses it (its reply says to keep the summary and record it when Cicada has finished). A `page` span from `page_read` reads "From the page, as <agent> read it" everywhere the app labels it (the episode's `source: page-read` rides `/episodes/{id}/text` and the provenance conversation rows), never a bare "From the page". **The other four outcomes touch only the ask store**: no bank write, no commit, no Sleep
gate (`RemoteRuntime._writes_bank`), and the `reading` sync component (asks + `reading.json` mtimes) moves so the app
shows "needs you to sign in" over SSE at once; the tool's reply tells the agent to stop. `via` is what the agent *said*
it read with — self-reported, never proof. The last successful read's day is kept in `~/.cicada/reading-last.json` (one small file; `GET /reading/settings` never scans the ledger). Settings live in `~/.cicada/reading.json` (`reading_settings.py`: `agent`,
`agent_sites` — `{site: day}`, empty by default, granted only for a site Cicada's reader could not read —, `agent_ack` with
a version (2) that re-asks when the sheet's wording changes; the old `agent_hosts` key is ignored and dropped on the next
write). **There is no pre-picked list of sites** (owner, 2026-09-30: "limiting the amount of sites makes no sense to me,
because we will never know which sites this will happen"): a **wall page** is a saved page Cicada's own reader could not
read — a sign-in, a consent wall, a refusal, or a host the backend never requests — decided by `reading_walls.wall_kind`
from stamps the fetchers already write (`fetch_status`) plus the closed host set, and only while it holds no words (no
`describes` claim, agent read stamp, substantive `## Description`, `description_source`, or — an X bookmark, whose saved item is the post — a non-empty `## Notes`; a saved sign-in or consent URL is
never one). The stamps are written wherever the reader fails: at save time (`MediaMeta.fetch_status`), in the in-cycle pass
and in the backfill, in the backfill's own vocabulary and 30-day backoff, so a site surfaces when its page is walled, not
when the capped backfill reaches it. Wall pages group by **site** (`reading_hosts.site_of`: a walled family folds to its
name, else the registrable-ish domain, never folded under a shared host such as `github.io`); the sites surface on
`GET /reading/sites` (hosts and measured counts only, ETag over `reading`+`entities`+`sources`, `def` in the threadpool,
memoised in `reading_queue.sites_snapshot`; a row's `allowed` counts only while agent reading is on, `granted` is the
stored grant, and `waitingNotAllowed` follows `allowed`) and a `PUT /reading/settings` `sites` patch grants or removes one (422 for a
site never surfaced; turning a site on again lifts its `needs_login` pause — an agent that was not signed in pauses that
site's derived entries until the row expires, a week). Per-page "Ask an agent" stays and needs no site permission. The
closed host sets are one module (`reading_hosts.py`, dot-boundary matching, no DNS): walled hosts (X, Facebook, LinkedIn,
Instagram, TikTok and Reddit, the families the backend never requests; `t.co` is never offered at all) have their **page never
fetched by the backend's page readers** (R-RW4: `media_ingestor.enrich` and the `link_enrichment` backfill, through
`link_enrichment._excluded_media`; the exceptions are TikTok's provider oEmbed call, which never loads the page, and the
Reddit and X connectors' own API calls), and a link that carries a secret or a
side effect, is local, an AI vendor's own page, a video (`cicada_record_watch`) or a paper is never offered at all
(R-RW5). Contract item 9 (`CONTRACT_VERSION` 9, `REMOTE_CONTRACT_VERSION` 6) exists only while the switch is on and is an
*instruction*, not a promise: read in the person's own session, never sign in, record `needs_login` and move on, never
post. The **choice of how the agent reads** (`agent_methods.py`, `$CICADA_HOME/agent_methods.json`, `GET|PUT /agent-methods`) is an
instruction Cicada passes to the person's own agent, never authority: `auto` (the default, no tool named), `own` ("don't
load a separate skill") or a catalog skill whose `roles` list the job ("the person chose the `<name>` skill for this: use
it, and if it is not installed for you, say so and stop"). It flows into "Copy for an agent" (`reading_prompt`), the stdio
queue reply and one primer line (`handshake.build(methods=)`, `MAX_METHOD_LINES` 2, fixed part, R12-checked); a tool reply
or primer line never names a skill to a remote connection or a client that is not one of `skill_catalog.AGENTS`, and the
copied prompt, which can be pasted anywhere, names it conditionally ("if you run on this Mac and can load skills … else
your own browser tools"). A skill the person picks gets a page in the graph
(`skill_pages.py`, the one writer, only from that selection or "Add to your graph": `type: skill`, `tags: [agent-skill]`
(`skill_tag.py`, so `state_dictionary._preferences` never lists an installed tool as a working agreement and Stage 4 never
mistakes one for a pattern), evergreen, `human_edited`, no claims, one `user` commit; an agent-made `tool`/`concept` page of the
same name is adopted, any page the person edited is left alone). Every string in these paths is neutral about providers
(`test_provider_neutral_copy.py`). The remote reply for `cicada_reading_queue` is fenced as reference data, so the never-sign-in rule also sits in its unfenced tool description, and a connection that can read but not record is told to stop and tell the person. A saved page's title is folded to one line and scrubbed before it is printed. Because the queue is outside the bank, nothing in `_state.md` can say links are waiting, so the recall hook and the
remote handshake add one per-request sentence (`recall_text.reading_line`) when more wait than the session was told; a session that has seen the queue drain hears the next ask as new.
Routes (`routers/reading.py`, none a Store domain): `GET|PUT /reading/settings` (shape `reading-2`),
`GET /reading/sites`, `GET /reading/sites/{site}/icon`, `GET|POST /reading/asks`, `DELETE /reading/asks/{urlHash}`,
`GET /reading/prompt`; `GET /sources` carries `MediaSourceItem.read` (`status, by, tier, at, via, harness, host, askable,
reason` — `askable` is the structural verdict plus the master switch, never a site —, `wall, siteKey, siteLabel, siteAllowed,
siteIconHost` for a page the reader could not open, `queuedBy: site`, merged from the page stamp and the ask row, newest
wins) so the app holds no host table; a retired interstitial or login-wall page (`enrichment_status: junk`) is let through
the Feed's junk filter only when it is such a wall or an agent already read it (Track P R5, amended 2026-09-30). **Site icons**
(`logo_service.ensure_site_icon`, `logos/<bank>/sites/`) come from the icon service only — the walled site is never
contacted, not even for its favicon; a 404 is retried once with `www.`, only a site the surfaced list holds is served, and the
service is told the site's name (the registrable domain, never a saved subdomain), under `CICADA_ALLOW_LOGO_FETCH`.
**The app half (G166).** `VersionVector.mapping["reading"] = [.sources]`, so an agent's outcome (an ask-store write, no
bank write) refreshes the Feed over SSE; `MediaFeedItem.read` (`MediaReadState`, decoded leniently — an older backend, or
a value this build cannot read, drops the block and never the row). **Settings → Reading the web** (`SettingsSection.reading`,
in Customize after Integrations; `ReadingWebView`, `ReadingAgentModel`; not a Store domain — fetched when the page opens and
answered by every write) has three groups. *With an agent*: "Let an agent read pages for you", off by default; turning it on
raises `SettingsSheet`'s first-use sheet (what asking does, that Cicada only asks, Cicada's instruction to the agent — no
credentials typed, nothing posted, messaged or changed — with the honest limit that it can't see or enforce what happens in
the browser, the sites' terms, an "I understand" that must be ticked, DR-41 — **no site picker**) and nothing changes until "Turn on", which sends the acknowledgement in one
`PUT /reading/settings`; once on, "Copy for an agent" (`GET /reading/prompt`) sits in the group. *How your agent reads*: the
`agent_methods` choice as radio rows (a skill wears a Skill tag, says whether it is installed, and offers Open in graph,
Add to your graph or **Install…**, which opens that skill's own `SkillDetailView` as this page's sub-page — the Skills
list shows only five, so a lower-ranked skill has no card there — with an `agent-prompt` plan's sentence and a Copy
button; the footer says the choice applies to agents on this Mac that can load a skill). *Sites that need your browser*: every site `GET /reading/sites` surfaced — only a site Cicada's own reader could
not read — each with its favicon drawn like a browser tab's (`SiteIcon`: 20 pt, a 4 pt corner, never a circle or a ring; from
`SiteIconStore`, in memory per bank and cleared on a bank switch, over `GET /reading/sites/{site}/icon` — the app makes no
network call of its own, a lint holds it; until it arrives, and for a site with none, the family's bundled mark, else a
ring monogram), its wall in words (`wallWords`), measured counts and one switch (the stored grant, so a site allowed while agent
reading is off still shows on, says "Allowed · agent reading is off" and can be turned off; a paused site's pages "wait
until you sign in", never "queued"); a site switched on while the sheet is
unacknowledged raises the sheet, whose one line says the site rides the same call, and a paused site ("your agent wasn't
signed in") offers Try again. The **Feed's detail column**
gains a Read section (`FeedReadSection`, words and controls from the pure `ReadWords`): "Waiting for your agent",
"Read by <agent> · <day>", "Needs you to sign in to <site>" with **Open in browser** (the person signs in themselves; the
app opens an http(s) link and nothing else) and **Ask again**, and "Ask an agent" (`POST /reading/asks`, which copies the
hand-off sentence). It is drawn only when something was recorded, an agent may be asked, or Cicada's reader could not open the page (`wall`:
"Cicada's reader couldn't open this page: it needs a signed-in browser / it stopped at a consent page / the site refused
it", with the site's icon at 16 pt, and **Let an agent read <site>** beside Ask an agent — one `PUT` when the sheet is
already acknowledged, else the same first-use sheet; a page of an allowed site reads "Waiting for your agent · <site> is
allowed"; a disabled Ask carries the server's own `reason`); an ordinary page with agent reading off draws nothing.
Settings → Agents keeps one row, "Reading pages", linking here. **Home** gains its own block, *Needs your browser*
(`ReadingSitesSection` between Needs you and Last read, over `ReadingSitesCache` — in memory, ETag-revalidated when Home
appears or the sources move, emptied on a bank switch, never a Store domain): "N saved pages need your browser to be read"
(the server's `waitingNotAllowed`), up to three of those sites' icons, linking to Settings → Reading the web; hidden at
zero and once every listed site is allowed, and never counted in Needs you. The wall
is not shown only there: the Feed row's second line says "Needs sign-in" (`ReadWords.rowFlag`) and `ContentView`
toasts a link that just hit one (`ReadWords.newlyWalled`; the first look after launch or a bank switch announces
nothing). The wall reads in the text ladder with a neutral glyph, never `warning` (DR-7), and the agent's own note shows
as "<agent> noted: …". No line says "in your browser" of what an agent did, or promises what it will not do.

**Implicit recall (G149).** G105 stopped capture depending on a model's tool call, and recall now works the
same way.

- **The hook.** `api/hooks/recall.py` is stdlib only. One command is registered under both `SessionStart` and
  `UserPromptSubmit` in `~/.claude/settings.json` and `~/.codex/hooks.json`, owned by its own marker in
  `api/hooks/registry.py`. It posts to `POST /capture/hook-context` and prints
  `hookSpecificOutput.additionalContext` (the one shape both harnesses parse) or nothing. It always exits 0,
  never 2 (which erases a prompt), under a 0.9 s client timeout.
- **The note.** `hook_recall` answers engine-free from the derived FTS index. SessionStart gets the primer. A
  prompt gets at most three pages it **names**: a whole name or alias, and one word only for a person, project,
  company, tool or place. Each page comes with its summary and at most two current claims with their dates,
  plus at most one open inbox question as a pointer to `cicada_check_nudges`. The note is ≤ 400 tokens or
  nothing, produced within a hard 300 ms.
- **The vectors.** They only re-order pages already named, and only when the on-device embedder is already
  loaded. A hosted embedder is never sent a prompt.
- **Repeats.** A per-session window keeps a page from being re-sent on consecutive turns.
- **The bank.** It reads the bank a capture would write into: the real bank while the demo is open, and
  nothing when there is none.
- **When it is skipped.** `CICADA_CAPTURE=off` spawns, `CICADA_RECALL=off`, and a Codex sub-agent's prompt.
  Codex also runs a new hook only after the person trusts it at startup.
- **The ledger.** One `hook_recall` ledger row per firing, ids and enums only, filed beside `read`.
- **Waiting reads (G166).** While agent reading is on, a session hears once — at SessionStart, or on its first prompt —
  "N links are waiting in Cicada's reading queue for an agent to read" (`hook_recall.with_reading_note`), and again only
  when more of the person's own asks wait than it was told, or pages of allowed sites grew by ten or more. The derived
  part is counted only when the bank's page cache is warm (a cold cache counts the asks and warms in the background), so
  the hook's 300 ms budget never meets a bank parse. One sentence beside the page note (its 400-token budget is the page note's own), per request,
  never stored, dropped from a captured transcript like every "From Cicada" note.
- **Remote.** Remote connectors have no hooks.

**Proactive behaviors:** surface only *topic-relevant* nudges (never all of them), raise a pending
clarification naturally in the flow when the conversation touches its entity, and offer related
saved resources.

---

## Companion App

The user-facing management layer for inspecting and curating the graph — it makes the system
observable rather than a black box. **The app is NOT the primary interaction surface** — that's the
chat, via MCP.

**Stack:** native SwiftUI macOS app; FastAPI backend at `localhost:8000` spawned as a child process
on launch (`Process()`) and terminated on quit; graph rendered with d3-force in a `WKWebView`.
SwiftUI→d3 via `evaluateJavaScript()`, d3→SwiftUI via `postMessage()`.

**Ruling (G109, 2026-09-02) — d3-force stays.** Evaluated against sigma.js/ForceAtlas2, Pixi,
cosmos, ngraph and d3-force-3d at ~1,900 nodes: the two G109 symptoms were three local bugs in how
`graph.js` drove d3-force, not a library problem. The only flip trigger is an in-app p95 frame time
above 16.7 ms on the live bank, or a graph well past ~10k nodes. **Two rules follow:**

1. **Every custom force multiplies by the `alpha` d3 passes it** (a guard that only removes energy
   is the one exception).
2. **The release path never bumps alpha** — a throw coasts on velocity, not on a hot graph.

`app/CicadaApp/Tests/graph/graph-physics.test.js` (real d3, real `graph.js`) is the regression net;
a KE/node plateau at tick 400 is the signature of a force that broke rule 1.

**Sync engine.** One `Store` holds a `Snapshot` per domain, hydrated instantly from a per-bank
on-disk cache before the first network round-trip, so the app renders real data cold even with the
backend down. A `SyncEngine` holds one SSE connection to `GET /sync/events`, reconnecting with
backoff and falling back to polling while disconnected; each `version` event refreshes only the
changed domains, always with `If-None-Match` so an unchanged domain costs a 304. View models are
thin projections and **never blank** — always last-known-good. Writes go through a `Mutation`:
optimistic apply, rollback with a toast on failure. **The graph receives deltas, not a full
re-layout**, so d3 node positions survive a Sleep cycle or a live edit.

**Ruling (2026-09-28, TODO ruling 12): plan usage and model prices show on the Sleep page's Details and its engine
menu — and nowhere else yet.** This supersedes the 2026-09-03 ruling ("prices and token usage are not shown anywhere
in the app") for those two surfaces only: no cost tiles, no `$`/token columns and no cost-per-day chart elsewhere, and
the `/consumption/*` endpoints are unchanged. Every figure states its basis in words ("charged", "at list price", a
plan window's share) and a plan's before → after carries the honest limit that it covers all use of the plan
(`CycleUsageText`, `UsageFormat.currency`).

**Navigation (Direction D, DS-1).** A 56 pt icon rail (`Views/Shell/NavRail.swift`): Home, Graph, Clusters, Feed,
Sleep, Inbox, Sources, Projects at ⌘1–8 in `AppTab.allCases` order (`RailItem`; a page switch is instant), each cell's tooltip
naming its page and shortcut (450 ms, then instant while warm), selection by brightness and one neutral fill
(`bgSelected` — never the accent, `SelectionTintLintTests`), the Inbox count a neutral `bgBadge` numeral, a spinner on
Sleep while a cycle runs, the gear and the sun/moon toggle at its foot, no wordmark. ⌃⌘S or the titlebar toggle swaps it
for a 208 pt labelled sidebar, remembered per viewer (`cicada.shell.labelledSidebar`). Relaunch restores the last tab:
nothing stored, or a value no build knows, opens Home, and a stored Graph stays on Graph; `AppTab` raw values are the
persisted identity and `AppTab.restored(from:)` maps retired ones. **The titlebar is a SwiftUI toolbar** with the
title hidden (AppKit keeps the drag area in every gap): the sidebar toggle after the traffic lights; the **command
bar** centred — the memory-bank selector (`BankSwitcher`, moved from the Graph page; the only switcher view in the
app, `SingleBankSwitcherTests` — the palette's "Switch to <bank>" row and the intake card's switch act on the same
`BanksViewModel` in the same window) and "Search your memory ⌘K", which opens the find palette through
`AppRouter.requestPalette()`; and the visible page's `?` at the right (`HelpContent.page`), one per window. macOS 26's
toolbar platter is hidden (`ChromeToolbarItem`). **Settings is a panel inside this window (DR-33)**: ⌘,
(`ShellCommands`, which opens the window first if none is) and the gear open it over a scrim — 880 × 620 at 1×,
inset ≥ 40 pt — with a `bgPane` sidebar that starts with a `CicadaSearchField` and groups its rows as Cicada ·
Customize · Engines & keys (`SettingsGroup`, G139) — Cicada: General · You · Privacy & data · Memory · Sleep;
Customize: Integrations · Reading the web · Agents · From anywhere · Skills; Engines & keys: Engines · Plans & keys · Advanced — and each
page's own header with an `esc` keycap and a close ×. It is modal: the shell under it is inert, ⌘K waits, Esc and a
scrim click close it. `AppRouter.openSettings(_:row:)` is the one door (`SettingsSectionLink`, the gear, ⌘,), every
hand-off to a page closes it, and `cicada.settingsSection` is only its remembered selection — the `Settings{}` scene
and its cross-window seeds are gone. Privacy & data exports a bank and moves one to `<root>/.trash/`, but never
switches banks (that is the command bar's); Memory has no "Look for duplicates" until the dedup endpoint stops
blocking the event loop and commits what it merges (R-O17). Memory also holds
G147's *How things fade*: pace suggestions from the person's own "Still tracking…?" answers
(Apply · Not now — the latter per viewer) and each chosen per-type pace (Reset). Search is `SettingsIndex` over `QuickMatch` — the
palette's one ranker — and landing always selects, scrolls, washes (the selected fill and the focus ring) and
announces the row (G139). `SettingsSection` raw values did not move. General's appearance offers System, which
follows the Mac's own light/dark through one app-scope observer (`ThemeStore.observeSystemAppearance`). General (F-10:
Look · Startup · When Cicada is closed) also holds Scene (four choices, the clock's scene beside it), Open Cicada at
login (`LoginItemService` over `SMAppService.mainApp`; an unsigned build that macOS does not keep says so), Show in
menu bar (per viewer, on by default; hides the menu-bar bookworm, the Dock icon stays); a login launch opens no
window — the bookworm waits in the menu bar, and the Dock icon brings the window (`LaunchKind` from the 'oapp' event,
`LaunchState`, R-OB18) and Keep memory working when
Cicada is closed (`BackendAgentService`: a read-only `launchctl print`, and Install runs
`scripts/install-backend-agent.sh` from the app's own checkout after the click, `CICADA_CAPTURE=off`, then hands
launchd the port). ⌘K and ⌘F are
menu commands in `Support/FindCommands.swift` (`HiddenShortcutLintTests`); ⌘, and ⌃⌘S live in
`Support/ShellCommands.swift`. Track P's audit removed the global Sleep button, because a cycle starts from the Sleep
page's one Consolidate control (G125 R10) or the menu-bar bookworm.
**One intake (Track I, spec decision 13).** Every way a file arrives — a drop anywhere on the
window, the Dock icon, File → Import… (⌘⇧I), the menu-bar worm's *Import a file…*, an empty state,
each `+` chat tile, the Sleep room's worm — goes through one `IntakeRouter`: sniff (`POST /intake/sniff`, stages nothing) →
preview (counts, date range, new · grew · already here, skipped files by name, *Into* a memory) →
import (`POST /intake/import`; a 202 and a job counter above 10 episodes) → a *what happens next*
card that never closes on its own. `UploadOverlay` and the Feed's Upload button are gone; the router
owns `Store.intakeInFlight` through a counter of requests in flight. The card's *Read now* is G125
R10's first narrow amendment: a user trigger, subtitled with the manual engine like Consolidate,
shown only when an engine can run and the import landed in the active bank. **Every
`IntakeRouter` door refuses the same roots** (`IntakeRouter.feedGuard`, Track Z): a drop that
resolves under `~/.claude`, `~/.codex` or `~/.cicada` (or `$CLAUDE_CONFIG_DIR`, `$CODEX_HOME`,
`$CICADA_HOME`) is refused before any folder is walked, a refused root met inside a dropped folder
is never descended into and refuses the drop, a drop with nothing export-shaped in it is refused by
name, and nothing is sent; `accept` answers (`IntakeAcceptance`) so the Sleep room tells a refusal
in its worm's words while every other door shows it in the panel. Three pickers still sit outside
the router — the Add-source walkthrough's drop and *Choose file…*, its saved-content picker, and
Settings' local-folder picker — and check only the chosen file or folder
(`IntakeRouter.refusedRoot(of:)`); a watched folder that *contains* a refused root is still walked
(open, G125).

**Home (G108; Direction D, DS-3b; F-09, round 4).** The front door at ⌘1: a 208 pt living band —
`PaintedScene(.hero(band:))`, the one component Home, the Welcome and onboarding's panes share (C10) — painting the
person's Scene (Settings → General: Automatic · Day · Afternoon · Night; Automatic follows `SceneClock`, NOAA's sun
over the Mac's time zone's tzdb point, no location; the afternoon is the last two hours before sunset through civil
dusk), never the theme (G144); its meadow line at two thirds of the band, faded into the window from 72 %. Slow
one-way clouds, grass swaying from its roots, seeds by day, fireflies and stars by night and a slow camera breath run
in one `TimelineView` at ≤ 30 fps (15 under Low Power) that rests while the window cannot be seen, while the Welcome
covers the shell and off-tab; Reduce Motion or Low Power make it gentler, never frozen (DR-66); a scene change
crossfades the same composition in 1.2 s. Under it, "What would you like to remember?" as a `PageTitle` — text never
sits on paint — then the palette's own `FindPanelBody` in `.page` placement in a 640 pt block: a second
`FindPaletteModel` sharing the one Ask and keeping no recents; ⌘K on Home focuses it, a pasted `http(s)` link offers
*Save this link*. Below it, in one 760 pt column: Getting started (while it lasts), Today (one row to Sources:
captured today, UTC, with the three busiest origins' marks, names and counts), Needs you (the Inbox's kind glyph,
question and age, *Open Inbox* at the label's right, landing in STATE 1) and Last read (the newest Sleep commit, its
pages as `Tag`s) — each number once, each a link to the page that owns it; the waiting count links to Sleep, never a
Consolidate. Right after onboarding ends (Open Cicada or *Set up later*), *Make it yours* (Appearance and Scene; `AppearanceTipPolicy`, per
viewer) sits beside the column where it fits, else atop it; once hidden it lives only in Settings.

**Onboarding (G145, round 4 phase B).** Six pages in one full-window layer, raised by the unchanged `FirstRunGate`
(unknown is never empty) or by the one door, `OnboardingState.reset` + `AppRouter.requestFirstRun` (Settings →
General's *Run setup again*, the demo's *Finish setting up*): Welcome and You're set on the full living painting
with a card (`WelcomeHero`); Import, Agents, Who reads and Keep it running in a split frame — the page's pane
painting (`OnboardingPane`, 540 pt, which gives way before the column does), the column with "Step n of 6 · k still
coming in", Back and one primary (⏎ never animates). Get started is the owner PUT, alone and first; after it **a
tick starts that source at once** through the one turn-on (`FoundTurnOn`; app-side sources register an
`AppSourceDriver`), an untick stops it keeping up and keeps what came in, and × shows only where a run can stop
(a browser's; a chat export shows its progress and never an ×). Nothing is pre-ticked and nothing is read before a
tick. The Import rows are one table (`ImportCatalog`: supported installed browsers, Calendar, Apple Notes — a
one-time read — Wispr Flow when present, the chat drop zone and *See how* per provider, a drawn walkthrough over
`ExportWalkthrough`'s data opening `WalkthroughVendor.exportURL`); Contacts sits under *Calendar & contacts* and
Chrome's open tab groups as a sub-row under Chrome (only where Chrome is), each one `ImportEntry` and one driver over
its own reader (`ContactsReader.connect`, `TabGroupWatcher.enable`), which Home's Getting started registers too. Every row, the topbar's count, You're set and Home's Getting started read one projection,
`SetupProgress`, over `SetupRunner`, `SyncActivity` and the channels. Agents reuse `AgentSelector` /
`AgentSetupSteps` with a live ✓; Claude Code's and Codex's *Connect for me* here also turns on *Remembers
automatically* (its commands shown first; Settings → Agents keeps it its own click). Who reads is `EngineChooser`,
writing only on a click; Keep it running holds the same switches as Settings → General and turns none on. You're
set shows one public-domain quote (`MemoryQuotes`, G153, kept per install) and Open Cicada marks the bank, records
the connected agents, asks `TourOffer` and lands on Home. *Set up later* and *Try the demo* (`SetupRunner.demoPlan`)
remain; export reminders (`ExportWaits`) ask for notification permission only when a delay is chosen. Getting started
continues on Home — the first read (*Read now*, G125 R10's second narrow amendment, only inside the card) and "Keep
reading on its own?" asked once of a person still on `manual`, its options gated by ruling 4.

**Settings → Engines: the engine picker (G122, Track E; moved by G139 A3).** A row of cards with real marks — Auto,
Claude plan, ChatGPT plan, OpenRouter, Ollama (tagged *Local*), API key — over the connections registry's candidates writes
`PUT /sleep/engine`, which lands in the same bank-independent `~/.cicada/connections.json` prefs
`use_for_sleep` already uses, never `api/.env`. A plan card is selectable once that plan is signed
in. The card shows both `preview.manual` and `preview.scheduled` lines rather than hiding **ruling
4** (a scheduled cycle never spends Claude *or* ChatGPT plan quota — `engine_select.SUBSCRIPTION_MODES`)
— the asymmetry stays visible, not silently applied. *Keep going on extra usage* (off) is the only
way a Claude cycle continues past the plan's included usage; otherwise it stops with one plain
sentence and the reset time. Ask follows the same choice. The ChatGPT plan runs as `codex exec` in
Cicada's own Codex home (`~/.cicada/codex`), signed into in-app with a device code; Cicada never
opens that home's files — `codex app-server` answers plan, limit and models.
`EngineChooser` is the component (`EngineCard` wraps it for onboarding); the Sleep page's quick engine
menu (beside Consolidate) reads and writes the same `PUT /sleep/engine` through the same
`SleepEngineViewModel` and the same write rule (`EngineWrite`), and shows both previews — "When you
start a cycle" / "Scheduled cycles", the one wording app-wide. The Claude plan's old *Use for Sleep* switch moved here too —
same `use_for_sleep` pref, same endpoint — but `engine_select.resolve_llm_mode` reads that pref only
when the chosen mode is `byok`, so it shows only while the API key card is chosen, as *Use my Claude
plan when I start a cycle*, and a flip reloads the chooser's preview. Plans & keys is credentials
only: the Max-tier cost-estimate picker is gone (prices live on the Sleep page, ruling 12).
**Who reads (round 4, R-AG10…R-AG14).** OpenRouter is its own card: *Sign in with OpenRouter* (PKCE, the nonce in
the callback path) or *Paste a key instead*; under the hood it is `byok` with an `openrouter/` model, so ruling 4 is
unchanged and `PUT {mode: "openrouter"}` is a 422 — every card becomes a mode through `EngineWrite.mode(of:)`, and
`selected` on the wire names the card. The API key card is a provider picker (Anthropic, OpenAI, Gemini, xAI, Groq,
Mistral), each writing its tested default model and offering its key field in place; a key's model pins its judge.
Ollama wears a *Local* tag and no card says "slower". Under the cards, `LeavesMacNote` — a pure function — says
where reads leave the Mac and to whom, only for engines that send data out (never Ollama, nor Auto resolving to it).
A preview line or the Sleep page's button that runs on an `openrouter/` model names and marks OpenRouter.

**Settings → Integrations (G126).** A categorized, logo-first page over the existing
`GET /sources/channels` registry — no new adapters, just a frame. The rule this page draws: a
*standing* connection (sign in once, polled on the Sleep tail, disconnect here) lives in
Integrations; a *one-shot* import (drop an export, sync a folder once) stays where it already was,
behind the Feed's `+`. Both read the same `channel_registry`, so a channel never drifts between the
two surfaces. Round 3 added **Notes & files** (Apple Notes, every watched folder, *Add a folder* and,
when Obsidian is installed, *Obsidian vault*) and **Voice & meetings** (Wispr Flow once it is on this
Mac) — both standing connections, so both live here; their marks are the installed apps' own icons.
Harness rows wear their app's real mark ("Other agents" a neutral glyph); a folder's Manage, Wispr
Flow and a connector's Connect/Manage open as sheets (`SettingsSheet`), never popovers; the
add-folder sheet labels its fields and asks which subfolders an agent wrote as a checklist
(`AgentFolders`), the wire still a `<folder>/**` glob (DS-3b). **Browsers (round 4, C9)** are drawn
from `BrowserInventory` — the browsers on this Mac by bundle id, each with its installed icon: Chrome,
Safari, Brave, Vivaldi, Comet and Dia as `SourceRow`s (Turn on / Sync now, or Try again with the
Full Disk Access fix under Safari when a read was refused, 'Last synced …'); under Chrome, *Open tab groups* is a
sub-row with its own switch and the open groups as tags in Chrome's colours (G160); and the ones Cicada cannot sync
yet (Arc, Firefox, Edge, Opera) named once in the header, never as a row. Safari's source page groups its items as
Recently saved · Favorites · Other bookmarks. **Calendars, contacts & feeds** offers Calendar on this Mac and
Contacts (G154), both app-owned rows.

**Agent wiring (Track I T3/T7).** `GET /agents/wiring` is read-only: per harness it reports
*recall* (the MCP server registered — `claude mcp get cicada` / `codex mcp get cicada --json`, 6 s
each and side by side (round 4: at 2 s the live Welcome read Claude Code as 'couldn't check in
time'), a timeout is `unknown`) and *auto-save* (the G105 Stop hook, via `api/hooks/registry.py`; an
unparseable settings file is `invalid`, never `off`), *auto-recall* (G149: `autorecall`
= `on|off|stale|invalid|n/a` for the recall hooks, with `autorecallOn` / `autorecallOff` argv kept apart from
`connect`: onboarding's *Connect for me* for Claude Code and Codex runs `connect` and then `autorecallOn` (every command
shown before the click), and Settings → Agents → *Remembers automatically* keeps its own click), plus the exact
argv install.sh would run. The **app** runs them, only after the person's click (spec decision 14, D-1), with
`CICADA_CAPTURE=off`, behind an allowlist pinned to its own checkout (which also accepts the recall hook's two
events and `registry.py uninstall --hook recall`); the backend never writes a harness root. `GET /agents/setup?harness=` (round 4 C5, G76's in-app half) serves what to hand an
agent instead of running anything:

- for Claude Code, Codex and Gemini CLI, a plain prompt (≤ 1,200 characters) that names the exact
  commands, built by the same step builders `/agents/wiring` uses (both steps always,
  `display == shlex.join(argv)`);
- for Cursor, its install link;
- for the Claude app, a config merge the APP performs.

No probe, no subprocess, no ETag.

Settings → Agents (round-4 D5) adds, per harness, Connect for me (the same `AgentConnect.run`), Copy
setup prompt (`GET /agents/setup`'s prompt shown verbatim, then copied — the agent runs the install itself), Open in
Cursor (the catalog's own deeplink) and Set up Claude (`ClaudeDesktopConfig` merges `mcpServers.cicada` into Claude
desktop's config: backup first, merge never replace, an unreadable file left untouched; the app computes the path and
the value itself). Round 4 C8: Settings → Agents is one selector of ten agents (`AgentCatalog`, pinned to
`agent_live.LIVE_AGENTS` by `api/tests/fixtures/agent_catalog.json`) with numbered steps below (`AgentSetupSteps`),
reused by onboarding. OpenCode, Hermes and OpenClaw register by editing their own config from a pasted prompt — Cicada
runs nothing for them and only reads that file (`agent_wiring.config_state`, ≤ 256 KB, parse-only); Claude, ChatGPT and
Grok go through From anywhere (`kind: remote`). `GET /agents/live` lights a pill's ✓ from the local handshake ledger
rows, a used connector (`last_used_at`) or the agent's own config — no subprocess, never `~/Library`, never
`~/.claude.json`; polled every 3 s while the page is visible.

**Settings → Skills (G138).** A reviewed catalog (`api/data/recommended_skills.json`: source,
licence, the reviewed commit and SKILL.md hash, needs, agents, a terms note, the Cicada tool it
bridges; `scripts/verify-skills.sh` re-checks it) served by `GET /skills/recommended` — at most
five not-installed entries by rank, install state derived per request from `SKILL.md` files and
Claude Code plugin ids, never an agent's config. **The backend never installs anything.** The app
runs only the agent's own installer (`claude`, `codex`, `npx skills` pinned to the reviewed
commit), after a consent sheet that shows the exact command, as an argv with
`CICADA_CAPTURE=off`; hosted MCP servers are copy-only. The app writes files only for Cicada's
own `cicada` and `cicada-librarian` (`SkillInstaller`, a `.cicada-managed.json` marker, never
over a changed copy). The handshake gains a capability line only for an installed, active bridge
whose tool exists: papers (`cicada_save_url`), video (`cicada_record_watch`) and meetings
(`cicada_save_episode`, one `speaker:<name>:` line per utterance, never `user:`) are active;
documents stays off until something says who wrote a document (F2-back R-B14).
**Role skills and the `agent-prompt` method (G166).** An entry may carry `roles` (`reading` | `watching`), the
`invoke` name the agent sees, a `pageName`, a catalog-authored `pageSummary` and a plain `reach` line, and its install
`method` may be **`agent-prompt`**: a text (≤ 1,200 characters, pinned to the reviewed version, no global trigger, "ask me
before any permission") for the person's own agent to run upstream's installer, so the plan is copy-only (`runnable: false`,
no steps, `prompt`) and `PROGRAMS` gains nothing — a bare `npx skills add` would copy the SKILL.md and leave the CLI the
skill drives missing, a half install that would read "installed". `browser-harness` and `macos-harness` (pinned, hash
verified by `scripts/verify-skills.sh`, whose `--print-urls` is pinned offline) are offered for reading and watching, each
with a `terms` line; `macos-harness` states plainly that it can control the whole Mac. Choosing one is Settings, How your
agent reads (`agent_methods`), not an install.

**Sources page — v2 in Direction D (G124, DS-3c).**
- **What stays from v2.** Every tile keeps Sources v2's five facts: mark · brand name · one status verb
  (`SourceLiveness`, no backend field) · a 14-day capture sparkline + lifetime total · four week-dots + delta.
  **Two nouns, never one**: the big number is the row's own unit, and the line and the delta are always
  *captured*. Every number goes through `UsageFormat.count` on the viewer's locale (`CountLiteralLintTests`).
- **D's material.** A tile is 96 pt including its padding, on `bgFocus` with a ring, the strong ring and a 1 pt
  lift on hover, and no shadow. It is clipped to its shape. Its mark stands bare. A failure speaks in `warning`
  with its dot hidden, and a live source keeps a green dot.
- **Packing.** One column count (`SourceGridColumns`, 2–4) is shared by every section. Sections share a row by
  span (`SourceGridPacking`), and the contributors block takes what the last row leaves when that is two columns
  or more.
- **Detail columns.** Opening a source, or an author in *Who wrote your memory* (a chip strip over a neutral,
  labelled share bar), narrows the page to a list of rows and opens it as the detail column (`SourcesSelection`,
  `SourceDetailView`, `ContributorDetailColumn`). A conversation's Reader is the third column.
- **What changed from v2.** The contributor drill-down is a column, not a sheet, so its "from conversation" is
  never under a modal. A compact G129 light never draws the Full Disk Access fix
  (`BrowserStatusLight.showsFixHint`); the fix lives in the source's detail column. *Advanced statistics* is a
  remembered disclosure on the old toggle's `cicada.usageMode` key. "Add a source" is a neutral button in the
  eyebrow row, which reads "Sources · n connected".

**Source rows and last sync (round 4).** Every source that keeps up renders one `SourceRow`
(`Views/Common/SourceRow.swift`) from a pure `SourceRowModel`: the bare mark, name and what it reads, what came in
(`SourceRowText.countLine`: the count in the reader's locale and the channel's `parts`), and on the right 'Syncing now'
with an × or 'Last synced 2 minutes ago' (the persisted `lastSync`, re-read every 30 s; an import says 'Imported …').
× cancels the run only (R-SR11). Sources' detail column, the browser, tab-group and Contacts rows in Integrations, and
Home's Getting started rows use it. `BrowserWatcher`, `TabGroupWatcher` and `ContactsReader` report their runs into
`SyncActivity`; `LocalSourceWatcher` and `CalendarReader` keep their own lights (R-SR17).

**What came in, by name (G161).** Under a source row, a "What came in" disclosure (collapsed, remembered per viewer
per channel, `cicada.sources.capturedOpen.<channel>`) lists the items that source brought in by their own title and
day, newest first, twenty at a time with "Show more" (`CapturedItemsList`): under onboarding's Import rows (a preview —
the rows open nothing there), under every Integrations row, and as the Sources detail column's content for a source
whose items are not saved links. `GET /sources/channels/{id}/items?offset&limit` (≤ 200; `api/services/channel_items.py`)
derives it at read from the same set the row's count means — the notes index, the calendar and tab-group episodes (never
a tombstoned one), the bookmark seen-set joined to the url index, a channel's media pages, a folder's files — engine-free
and read-only; titles only (scrubbed, one line), never a body, and for Contacts the matched page's name only. Its
`total` is its own count, not a promise to equal the row's (a notes index keeps a deleted note). It ETags over
`sources`+`episodes`+`entities` with the channel and page in `extra`, and is **not** a Store domain: `ChannelItemsCache`
keeps it in memory, revalidates when the list opens or the channels move, and empties on a bank switch. A row opens its
episode in the Reader, a saved item in the Feed, a person in Clusters.

**Clusters and the Feed (Direction D, DS-3c).** Both are list pages in progressive columns: an eyebrow row with
text tabs (`AdaptiveTextTabs`: with counts, then without, then a menu, so a tab is never clipped), the list, a
detail column, and the Reader as the third column (each list page hosts its own: `AppTab.hostsOwnReader`).
`ListColumns<ID>` holds the open row: a row that leaves the data, or that the chosen tab does not show, closes the
detail; one that find (or Clusters' View menu) hides stays open. Keys follow DR-68: ↑/↓ swap in place, ⏎ steps in, Esc closes the rightmost column, and ⌘F opens
the page's find row.
- **Clusters has one filter:** a View menu with the Graph's own types (`graphVM.filter.types`), labels, and a
  remembered *Expand all*. Its tabs are navigation: All plus each present type, by plural name. With nothing open it
  is mock A's icon-led cards (F-11, G146): People · Projects · Companies · Tools · Concepts · Media two to a row, the
  rest three to a short row, each a card of 56 pt tiles — `EntityPicture`, the name, one line in words (never tags or
  a percentage) — six in the first row of cards and four after, "Show all ›" opening the type's tab (one card, every
  tile); `ClustersGrid` decides it, pure. A click on a tile's picture opens the image picker (no separate hover button, owner 2026-09-30); its
  words open the card. ⌘F shows the list column (its find row, then find's ranked rows) in place of the cards while it
  is open. Beside a card the list keeps rows with pictures and an age, recently mentioned first
  (`lastReferenced` on `/graph` nodes). The detail column hosts DS-3a's `EntityDetailCard`, in its `.card` style, with
  its `TopicDetailNavigation` trail and the page's Esc order passed through the card's `onEscape`. A ⌘K ⌥⏎ landing
  opens the entity's type tab.
- **The Feed** has sort tabs (Relevance · Recent) and kind tabs (`FeedKind`: paper, video, bookmark, link). Its
  rows are 56 pt, each with the origin's real mark. The Connected strip and the export waits scroll with the list,
  and only with nothing open, so the eyebrow is the only fixed band. That fixed the header drawn under the
  titlebar.
- **A saved item's detail column** shows `MediaPreview` (a video plays at the column's width), "Why it's saved"
  (the page's own words, then the pages it is about, known ids only), and "Saved from" (the origin's mark, name,
  folder and day, or `[ no source recorded ]`). The palette's saved-item row and a source page's items land there
  through `AppRouter.routeToFeedItem`, and the preview sheet is gone. The one-shot import's `+` (with ⌘N) is an
  icon in the eyebrow row and opens the unchanged `AddSourceSheet`, whose root hosts the one `IntakePanel`.
- **Videos (G162, the approved boards, 2026-09-30).** The app reads `GET /videos/state` and `/videos/summary` through
  `VideoStateCache` (app-level, in memory, ETag-revalidated, never a Store domain; `VideoRefresh` follows the
  `videoQueue`, `episodes`, `entities` and `bank` components, one revalidation is scheduled at the wire's
  `nextChangeAt` so a lapsed lease never sticks as "Picked up", a bank switch empties it, and a 404 from an older
  backend hides every video addition). **The server is the only deriver** of a video's state; the app decodes and labels.
  A Feed video row carries a 64 × 36 frame (the stored thumbnail or a neutral play tile, never a URL derived from an id),
  "channel · site · length · saved day" and one state word (a queue word wins). The Videos tab's 44 pt strip says how
  many are not read yet and the one queue wording, and *Choose videos…* turns the page into the watch run: the picker's
  tabs (Not yet read · Queued · Read, disjoint, nothing pre-selected) replace the sort and kind tabs, the list becomes
  64 pt pick rows with `NeutralCheckToggleStyle`, and the detail becomes `VideoRunCard` — per-video Transcript/Watch,
  known-length size words (no price, no estimate), how the agent should read, the prompt shown before it is copied
  (`GET /videos/run/prompt`), and one primary, *Copy for an agent* (`POST /videos/run/handoff`, no cap); after it, the
  progress card counts `batch.done` only. `VideoBlock` ("What Cicada has from this video") sits in a saved video's
  detail column and the entity card's media block: the state, who recorded it (the harness and, where the turn join
  found one, the model — data only), whether Sleep read it, the first quote, the honesty line, and Queue transcript /
  Queue watch / Remove / Try again; a `needs_login` hand-back adds *Open in browser*, and the sentence about the
  reading permission and its Settings button wait for the reading branch (`VideoActions.for(_:permission:)` takes `nil`
  today, and `nil` shows no sentence — none points at a setting this build lacks). The honesty lines promise only what
  the record says: "a model's reading, not captions" only when its engine is `video_link`, else "may be approximate";
  a record with no basis reads "The agent didn't say how it read this", never a claim about when it was made.
  The Reader's header for a watch record and each `media` turn's fidelity are built from the episode's `watch` block.
  Every string is in `Copy+Videos.swift`, and `VideoCopyNeutralityTests` fails on a provider or model name.

**Projects (G141 PJ-5, Direction D).** The eighth page (⌘8, after Sources), the first designed for D: a list page in
progressive columns over `GET /projects` and `GET /projects/{id}/timeline`, which are **not** Store domains —
`ProjectsCache` (app-level, in memory) revalidates them with the server's ETag when the page appears, a project opens, a
write lands, or a sync event moves `entities`/`episodes`/`inbox`/`bank`, and a bank switch empties it (no
`VersionVector` mapping, nothing on disk). The wire decodes leniently into local `Project*` types (the shared `Claim` is
untouched); derived state is `ProjectState`, the Swift twin of `project_state.timeline_state`, running the same
`api/tests/fixtures/timeline_state.json`; every relative word comes from `RelativeDay` over `ISODay` in the viewer's
calendar (a lint keeps the day words there), and midnight re-derives the page with no network. The story is derived off the main actor (`ProjectDerived`, keyed
by project, day and cache revision; the last value stays up while the next builds) and Lately is one lazy list, so a
project whose happenings cite hundreds of pages opens at once (round-4 D6). Every Swift test reads
the demo scenario's real wire, `app/CicadaApp/Tests/fixtures/projects-demo.json`, pinned by
`api/tests/test_projects_app_fixture.py`.
- **The list:** text tabs Active · Quiet · All (resting projects only under All); sub-projects indented under a shown
  parent; each row's where-it-stands line, a mini `progressFill` bar, the next milestone or "No plan yet", people from
  the graph's `person` neighbours (never the owner), the compact age; "still indexing" while the server says `partial`.
- **The band** (`BandLayout`, pure, the approved mock's coordinates): `progressFill` from the first moment up to a
  "You, today" marker in `textPrimary`; done milestones filled inside the green, planned ones hollow on the track, a
  closed `due` slashed ("passed, no word on how it went"), a moved one's dashed ghost and bracket; happenings as neutral
  dots, ongoing threads as spans to today that dash once quiet; months and words near today. Every mark is a button: a
  `textPrimary` ring, its first words and date on hover, ←/→ along the band, ⏎ into the Reader. It is never called
  "Timeline" — that is the entity card's tab, which can share the screen.
- **The story:** Log progress (⏎ done, ⌘⏎ still going; the server dates it from the words, else the date chip, else
  today, and the page says which and how, with Undo = withdraw); Now (the threads; a quiet one whose follow-up waits in
  the Inbox links to that card); Lately (Today · Yesterday · This week · Earlier — one sentence per happening, every
  participant a chip that opens its card, at most eight per sentence with a '+N more' that opens that row (round-4
  D6; the server sends the first 12 and `participantsTotal`), the owner as the sentence's own word with a "you" tag; a status word; a
  source line with the origin's mark and "Show in conversation ›"; Resume where resumable; Not right); Plan (Add with
  an optional picked date, Mark done, Rename, "moved once ›"); Around this project (People · Tools & infrastructure, a
  tool unfolding its specs · Documents & links · Ideas · Parts of this project). The Reader or an entity card is the
  third column; Esc closes the Reader, then the item or card, then the project.
- **Backlog (G150):** after Plan, text tabs Open · Doing · Done · All (a dropped item only under All); rows with the
  id, the title, a triage tag and the age of the last note; Add to backlog. A row opens the item as the third column
  — the title as the heading, the moves, the description and every note as page prose signed with its author's mark,
  the links, Add a note. The third column is one slot: the Reader, else a backlog item, else an entity's card.
- **Writes** are `ProjectWrite` mutations through `Store.perform`: painted where the answer is known (a thread settled
  or restated, a milestone done, renamed or added, a withdrawal), rolled back with the server's own 409/422 sentence
  (a 400's or 404's detail is never shown — it names ids), disabled while Sleep runs; nothing relative is sent as a
  value. L · M · D are key presses on the focused project (the Inbox's O / L precedent), never menu key equivalents.

**Sleep page — the study room (G125 v4, Track Z).** One 760 pt column at every width: the room,
one sentence in the display face under it, one Consolidate/Cancel control with the engine menu
beside it — a neutral button naming what a cycle you start would run (`preview.manual`, "Auto ·"
under Auto) that opens the five engines with their real marks, the chosen engine's model and both
ruling-4 previews; the "Runs on …" caption retired into it, and Cancel's caption shows while running
— one whisper line for the schedule, and everything else under a single **Details** disclosure (Last
cycle · What's waiting · Readout · Past nights) in D's list grammar — section labels over rows, no
cards; Last cycle's rows in words, "Rested" as a sentence, the readout as key–value rows, and, while videos are
queued, one Videos row in What's waiting (`VideosWaitingRow`, G162: the queue wording and *Choose videos ›*, starting
nothing) — closed by
default, remembered per viewer
(`cicada.sleep.detailsOpen`) and not built while closed. The worm speaks in that one fixed slot —
`roomSentence` / `wormAnswers`, pure
`SentenceLine` values over `SleepPageModel` (lead ≤ 40, tail ≤ 80, clock-free; a missing fact
omits its rung, never shows a guess); the floating bubble is retired. **Two kinds of art (R-Z1):**
*state art* — the mood's frames, the lamp (= the schedule), the pile, and the window's **weather**,
a total function of the mood with a legend popover as its twin — and *response art* (gaze, perk,
talk, cheer), transient and never contradicting state. The art layer stays inert; interaction is a
hotspot layer derived from the pure layout (`deskHotspots`), and **no click on art changes what the
machine does**: the lamp's popover shows the scheduled engine and its reason *before* its labelled
toggle can flip, and Consolidate stays the one trigger. The strip appears only while running or
frozen after a cancel or failure; the running stage is `activeStage(completed:)` = completed + 1
everywhere (page, menu bar, onboarding, strip). A real completion cheers once and offers "See what
changed ›"; a cancel neither chews nor cheers. Memory sources left the page (Sources v2 draws it;
the series live in `Views/Sources/ActivitySeries.swift`). **Feeding (Z9).** A file, files or a
folder dropped on the room — or *Feed a file…* from the worm's context menu and VoiceOver actions,
which open the intake's own `IntakePicker` — go to `IntakeRouter.accept(urls:from: .sleepRoom)` and
nowhere else. While a file hovers, the worm is expectant toward it and eager over itself behind a
dashed chrome outline, and the window's veil steps aside (`nearerDrop`); it gulps when the router
takes the drop and shakes when it does not, and the sentence tells the router's own phase in words
with no number — the panel has the counts. A sleeping worm takes the drop and stays asleep; a stale
page sends nothing. **Meadow (Z10).** The sentence is the display face (SF Pro Display semibold 30,
`displayTracking`) over an SF italic tail (F1 R-FX13), Consolidate is the page's one `PrimaryActionButton`, `SleepMotion` forwards its shared names
to `CicadaMotion`, and the sky band above the page is OFF (`SkyBand.ships`, TODO ruling 10). The
pile is compressed to its column at every zoom and queue size — at most eight spines, the order and
every count kept, never cut (`fitPile`) — and the title is `PageTitle`, the view `PageHeader` draws.
Refused: autonomous beats with no fact behind them, cloud drift, a storm flash, duration estimates, and any price or plan figure outside Details and the engine menu (TODO ruling 12) — inside them only a measured or list-price figure that states its basis ("charged", "at list price", a plan window's share).

**Consolidate reads everything — the app half (G163, ruling 13).** No new door: every trigger already POSTs with no body, and
the server drains. `SleepStatusResponse.drain` (`SleepDrainInfo`, lenient like every field) and the SSE event's compact
`SleepDrainSSE` are merged by one pure `resolveDrain(sse:status:)`: the status holds the whole block, the event overlays the
moving counts only when it describes the same run (same frozen total), and neither is ever a hybrid of two runs. While it
reads, the sentence's tail is "Batch 3 of 12 · 62 of 287 filed." (measured counts through `UsageFormat.count`, G107, and only
with more than one batch); the lead, the strip's Read fill and the study list already read the cumulative origin dicts. A plan
stop is a *pause*, not a failure: the tail is the vendor's own sentence (reset time inside it), the strip freezes where it
stopped and the worm neither chews nor cheers (`SleepPageModel.stoppedEarly` feeds `stageStripState`, `stageStripIsVisible`,
`deriveSleepPageMood` and `isRealCompletion(drainStop:)`). **Cancel keeps its name** and its semantics (stop at the next safe
point, drop a batch that has not begun filing), so its caption and tooltip say what is kept and what is not
(`Copy.cancelDrainCaption`), never "after this batch" and never "nothing is lost". Details › Last cycle gains a "Read everything"
row (only when it took more than one batch or something waits), a "Paused at your plan's limit" row carrying the vendor's whole
sentence, a drain-aware cancel text, and no "Episode cap reached" row for a drain. Home's Getting started says "Keep reading"
after an early stop (`FirstReadAction.keepReading`) and "Your memory has N pages now." after a full drain. Since ruling 16 the lamp's popover and the engine menu's Scheduled row say a scheduled run reads everything waiting too
(`Copy.scheduledReadsAll`), with how it spends in words from `preview.scheduled.billing` ("charged per use; Cicada sets no limit", "on this
Mac") — never a provider's name.
**Sleep page v5, the app half (2026-09-30; rulings 15, 16).** All copy is `Theme/Copy+SleepV5.swift`, provider-neutral
(`SleepProviderNeutralLintTests`: no provider or model named in a literal under `Views/Sleep`/`Views/Intake` outside the files that render the
person's own choice) and journal-honest (no "read and kept": a Pause reads the part in progress again). The **paused run** (`SleepPausedRun`, on
`GET /sleep/status` and in brief on the SSE event, where a present `null` means none) outranks every idle rung of the sentence — Paused / Paused to
leave room in your plan / Your plan window is full / The engine needs a look / Cicada restarted while reading — with what is filed and, when armed
(ruling 15), "Continues after 3:40 PM" (one locale-aware formatter, `sleepClockWords`); the mood is `.reading`, never an error or a cheer. **One
primary at a time (DR-40):** Consolidate / Pause (a drain's cancel, "Pausing…") / Continue (named for the manual engine; held while a weekly limit's
reset is ahead) with *End this run* beside it. `SleepViewModel.continueRun()` is the only sender of `{"continue": true}`; **every other door goes
through `triggerManually()`, which routes to the Sleep page while a run is paused** (`AppRouter.routeToSleep`), and the menu bar, the intake card's
and Home's *Read now* say what the click reads — "Consolidate now — all 287", "Reads all 318 waiting, oldest first, saving every 25." (`SleepDoor`,
readable = waiting minus parked, M7; a pause whose record has not loaded says only "Paused", and an unknown batch size is left out, never a
fallback — `Store.onSleepPausedChanged` refetches the record app-wide, not only on the Sleep page). While a drain reads: "Reading 14 of 25." / "Sorting 31 of 86." / "Deciding 4 of 12." / "Filing…" (a stage
fills only from finished work over a fixed total; Notice and File never), a caption under the strip in words, `RunProgressBar` (filed ·
read, waiting to file · waiting · could not be read, and calls made; one accessibility value; elapsed "Running 27 m", never a remaining time),
and the first save's "Your page has 31 beliefs so far" with *See your page ›*. *Reading options…* (`ReadingOptionsSheet`, 720 pt) sets batch size
10/25/50 and *Continue by itself when my plan resets* (off) on change; it has no Read faster row, no engine advice and no site list. The engine
menu's *Keep plan free* (Off or 5–30 % of the window, plan engines only, a line not a guarantee, an unreported window said so) is one of ruling
12's two homes; Details is the other: Last cycle's run rows (`LastCycleRow.runRows`, merged over the pre-v5 drain rows), per-source counts and
per-conversation rows from `GET /sleep/queue` (refetched when the run's counts move, never per tick) with Retry for a parked one — offered only while no run reads or waits paused, since the
server refuses it then (`LastCycleRow.canRetryParked`) — a scheduled run's spend note billed from the run's own usage, never today's preview, and Past nights
folded by run (`PastNightItem.group`, the run's numbers from the server's `run`, never summed from visible rows; opened: models, cost, pages,
batches and pauses from `GET /sleep/runs/{id}`, cached in the view model and refetched when the run's counts, pause or end move; touched pages
by name, the id in `.help`). The app-level `SleepViewModel` empties its queue, run details and history details on a bank switch
(`Store.onBankChanged`). `PriceLintTests` keeps `$` and token literals out of every other Sleep
file.
A refused bank switch shows the server's own 409 sentence (`BankSwitchFailure`), from every door: the switcher, the demo's enter and leave (`DemoMode.leaveToast`) and an active bank's rename.

**Mascot states (G107).** `BookwormState` gained `reading` for this page only —
`deriveSleepPageMood` returns it where the menu bar's `deriveBookwormState` returns `.curious`, and
the menu bar's own precedence and sprite meaning are unchanged. `store.intakeInFlight` (set while
the intake router has a request in flight) forces `reading` ahead of `happy`/`hungry` but never ahead of
`sleeping`/`error`/`digesting`. Per-cycle duration *estimates* stay deferred (G107's own ruling);
only a measured, telemetry-joined duration is ever shown. Track Z adds **response art** inside
`BookwormSprites`: `BookwormPose` (idle · attentive(gaze) · expectant(gaze) · eager) and
`BookwormReaction` (perk · talk · gulp · shake · cheer), gated by one state × response matrix
(`BookwormState.allows`, `acceptsGaze`) so a sleeping worm's eyes stay shut and red pupils never
look away; every beat is ≤ 3 frames × 0.12 s; a hop is a whole-cell shift (a capped state crouches
instead — the nightcap owns the grid's headroom); and a lint bans
`.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(` on the worm except its lattice placement. The
renderer key gains one `look` segment, omitted for idle (every older key byte-identical); the
page's reachable set is ≤ 256 keys per size and the wipe bound is 1024. **Feeding** — a file dropped
on the worm imports through the one intake (R-Z10) — shipped in Z9; the matrix decides its gulp and
shake like every other beat.

**View menu (G130 slice 1a).** ⌘+ / ⌘− / ⌘0 scale the whole chrome — one persisted `uiScale` behind
every `CicadaTheme` font and spacing token, so every reader repaints with no `.id()` anywhere (the
PR #49 lesson repeated). The graph canvas keeps its own zoom; ⌘+/⌘− means chrome, not canvas, same
as a browser's page zoom vs. a map widget's. `Settings` gains a *General* tab (Appearance + a Text
size slider) alongside Agents, Plans & keys and Schedule. Slice 1b (PR #58) finished the job:
every literal `.font(.system(size:))` / `Font.system(size:)` in `Sources/` now goes through
`CicadaTheme.font(size:...)`, and `FontLiteralLintTests` fails the build on a new one.

**Find palette (G136).** ⌘K ("Find in Memory…") and ⌘F ("Find on This Page…") are menu commands in
`Support/FindCommands.swift` — a lint (`HiddenShortcutLintTests`) keeps both shortcuts there, and ⌘F
reaches only the visible page's field. The palette is an overlay anchored 4 pt under the titlebar — 640
pt, an opaque `bgMenu` floating surface over the panel scrim — that appears and leaves in one frame
(DR-60); its instant tier (`QuickIndex`) is rebuilt off the main actor from the Store's snapshots and
answers every keystroke with no network; ~150 ms later `GET /search` (prefix, then hybrid) appends
conversations, beliefs (superseded ones as history), backlog items (G150; the server tier only) and whatever
the local tier missed — a shown row
never moves. Ask is a mode (⌘⏎) hosting the unchanged `AskPanel` body. One ranker, `QuickMatch`,
folds text exactly like the server's `text_fold`; every in-page field is `CicadaSearchField`.
Recents are `(kind, id)` pairs in the cache-only `.quickRecents` domain; the query is never stored,
logged or sent anywhere but `/search` and `/conversations/recent?q=`. `FindPanelBody` is the hostable
body (Home). Settings' pages and every static row are in the palette from `SettingsIndex` (one index,
one ranker); ⏎ lands on the row through `AppRouter.openSettings(_:row:)` (DS-3b).

**The demo and the guided tour (G117 round 4, G152).** The demo bank shows every page with something in it:
`demo_showcase.write`, called last by `demo_bank.populate`, adds people and a company with pictures (the C11 upload
rung; pastel avatars drawn in code by `demo_pictures`, never a photo), a saved NASA video (read from its captions by an agent, through the same Leo session) plus two direct example.com
video files — one recorded from frames and captions, one nobody has read — and an article with a
public-domain preview, an arXiv paper with its CC0 details, a calendar day, an open Chrome tab group, beliefs Claude Code
wrote over MCP that the card signs with the model and effort of their turn, and every inbox kind — each in its live
writer's shape and committed as that writer commits, with `today` pinned; the only URLs off example.com are
`demo_showcase.PUBLIC_URLS`, each with its licence. `/banks` rows carry `demo` (`demo_guard`, never the name);
`POST /banks/demo` re-opens a demo that exists and `POST /banks/leave-demo` returns to the real bank left most recently
(else `default`, else a new "My memory"). While the demo is active, `DemoBanner` — a floating bar laid out under the
page area, never over a row — offers *Restart tour* and *Finish setting up →*, which leaves the demo and opens onboarding
through the one door (`OnboardingState.reset(bank:)` + `AppRouter.requestFirstRun()`). The guided tour (`TourController`,
`TourLayer`) is six coach marks — the command bar, Home, the Inbox, a person card, Projects, Sleep — on floating
surfaces over a scrim on the page area; Next (⏎) · Back (←) · Skip tour (Esc); it navigates through `AppRouter` and never
acts (`TourLintTests`), opening `DemoShowcase`'s person and project only in the demo. It starts by itself on the demo's
first visit, is offered once on Home after onboarding (`TourOffer`), and replays from Settings → General, every `?` and
the banner; finishing or skipping is remembered per viewer (`cicada.tour.done`).

**Brand marks (Track L).** One map, `OriginIconography.logoName(for:)`, and one precedence:
**installed app icon → bundled PNG → SF Symbol**. Apple's marks are never committed (Safari and
Apple Notes resolve through `NSWorkspace` by bundle id, then their own SF Symbol); every other mark
is fetched once by a maintainer with `scripts/fetch-logos.sh`, declared in
`Resources/logos/logos.manifest.json` (source, licence, trademark restriction, sha256) and
attributed in `Resources/logos/LOGOS.md` — marks committed before the pipeline are declared
`legacy` (10 of the 30): the script never fetches them, their sha256 is verified on every run, and
their licence line records the commit that introduced them rather than an upstream grant. Origins are
`commons | repo | recut | legacy`; a `repo` mark (R-AG9: OpenCode, OpenRouter) is pinned to a 40-hex
commit on the vendor's own repository, with the same upstream-drift guard as Commons. **No
runtime network:** none of the three outbound gates is involved. A raster whose background IS the
mark (`hermes`, the only one) is never recut — every surface that draws one clips it to its own
curvature instead, and `LogoAssetTests` names any opaque plate so another cannot arrive unnoticed.
**Claude Code is the Claude mark plus an app-drawn `>_` badge** (R-AG8, `BrandMark`, composed in
`LogoImage`: `claude-code` → `claude.png` + badge, `claude-desktop` → the plain `claude.png`); callers
keep passing the logical name, and no mark file is edited. Nominative use only — a vendor mark is never restyled or recoloured; the one permitted
transform is an exact luminance inversion of a *monochrome* mark into its `-dark` sibling, which
`LogoImage` picks under a dark theme. Drawn brand glyphs are gone and do not come back.

**Design rules — Direction D, "Focus columns" (2026-09-23).** [`docs/design/DESIGN_RULES.md`](docs/design/DESIGN_RULES.md)
is the binding target for every UI change: graphite neutrals, the system accent, SF Pro only, a 56 pt icon rail, a centred
command bar holding the bank selector and search, and progressive columns (the list alone → list + detail → list + detail +
Reader). Rules are numbered `DR-n` and a UI PR cites the ids it applies; a departure needs a dated ruling in its §9. The owner
chose D from three mocked directions (the Inbox and the Reader). DS-1 shipped the tokens, the type, the shell and the
Settings panel; DS-2 (2026-09-24) shipped the Inbox in progressive columns and the Reader as a column; DS-3b
(2026-09-24) shipped Home, the Sleep page's engine menu and Details, and the Settings panel's fixes. DS-3a (2026-09-24)
shipped the Graph page and the entity card, and DS-3c (2026-09-24) shipped Clusters, the Feed and Sources in progressive
columns. Every other
page paragraph below describes what ships until that page's DS track lands.

**Graphite and Meadow (Direction D, G137).** Working surfaces are graphite — `bgRail` · `bgBase` · `bgPane` · `bgHover`
· `bgFocus` · `bgOption` · `bgButton` · `bgSelected` · `bgMenu` · `bgKey` · `bgBadge` (DESIGN_RULES §3.1, chroma ≤ 4,
`ThemeTokenTests`) — with the pre-D names as aliases (`background`, `surface`, `surfaceHover`, `surfaceElevated`) and
`border`/`borderLight` the opaque twins of the resting ring and the input border (graph.js's edges). Text is four steps
plus `textTertiaryOnFill` (`ThemeContrastTests` holds every surface). The accent is the Mac's (`Color.accentColor`);
DR-5 allows it six uses, and the pre-D call sites that still read `CicadaTheme.accent` (now the Mac's accent, so a
state dot among them changes hue on a red or orange Mac) are swept by each page's DS track. `accentText` derives from it — exactly the rules' values for the default blue, pushed to ≥ 4.5:1 for
any other (`AccentInk`). The retired indigo survives only as a data hue (the "active" status, the heat ramp). Depth is
an inset ring, never a shadow in dark and one soft shadow on a light floating surface (`ringed`, `floatingSurface`,
`Theme/Elevation.swift`; `ElevationLintTests`) — the target; the two sites that lint still allowlists
(`MediaPreview`, `HeroPreview`) shadow until their tracks; `GlassCard` is a `bgFocus` card with a ring. The nature tokens (`sky`,
`meadow`, `dandelion`, `cloud`, `bark`, `soil`, their washes, the procedural skies) are for art and reward moments
only, never a data encoding and never behind a row — `progressFill` (§3.8) is the one exception, for Projects.
**Liquid Glass lives in the chrome layer only**, through `Theme/LiquidGlass.swift` (gated on macOS 26 with a material
fallback, opaque under Reduce Transparency); a lint fails the build on any glass API elsewhere. **Painted art**
(`Resources/art/`, `art.manifest.json` with generator, prompt, date, licence and sha256; every painting ships as day,
afternoon and night of one composition — `docs/design/ART_DIRECTION.md`) appears only on non-data surfaces — never the
graph, a list, a grid, a form or a number, and text never sits directly on paint — enforced by an allowlist lint;
Home's band and the Welcome are `PaintedScene` (C10), composed inside `Views/Meadow/`, and its particle colours are
the art's (`ScenePaint`), never theme tokens. **Type:** SF only. `displayFont(size:italic:)` is SF Pro Display
semibold (tracking −0.3 at 20 pt, −0.4 above, floor 20, paired and counted by `FontLiteralLintTests`), `quoteFont` SF
15 regular, one `SectionLabel` (11 medium, sentence case, never mono or tracked — `SectionLabelLintTests`), monospace
only on `MonospaceLintTests`' allowlist (code, commands, paths, keys, ids), and `CitedSpan` the washed, underlined span,
read by the Inbox's quote and the Reader's turns since DS-2 (a mention found by name is its semibold, unwashed case). **Motion:** `CicadaMotion` (nil under Reduce Motion) is the only place outside
`SleepMotion` a duration is spelled; `hoverLift()` for things that open, `iconHover()` for glyphs; a keyboard action
never animates.

**Video (Track V).** A saved video plays where the user already is — a saved item's detail column in the
Feed, the entity Content tab and the entity hero, all through `MediaPreview`/`HeroPreview` — and the provider is
derived from the URL at read time (`VideoRef.resolve`), never read out of the page, so a bank never
needs rewriting to teach the app a new one.

**Provenance viewer (G118 slice 2).** Every claim carries evidence chips (`Views/Provenance/`): the
label says who spoke ("You said", "<agent> replied", "From the page", "Inferred", "Mentioned here"
for a legacy claim's name match found at read) — an agent's chip names its model when capture recorded one ("Claude
Code · Opus 5.5 · high effort", `ModelNames`; round-4 C3/C4), as do the hover, the Reader's meta line and turn labels,
"Where this came from" and a belief's help; an app with no capture says "model not shared by this app" — hovering shows the words in the quote face — washed
when quoted, bold when derived, plain when stale — and a click opens the **Reader**, a column
(`ReaderColumn`): the third progressive column on the list pages that host it (the Inbox, Clusters, the Feed,
Sources and Projects — `AppTab.hostsOwnReader`), and on every other page the shell's trailing column (`ShellReaderHost`),
sized before the page so it is never pushed off-window. It is driven by
`ProvenanceRouter` (a stack of `ReaderTarget`s), beside whatever is open so a belief and its sentence
are on screen together (Direction D, DS-2). It shows C's header — mark, title, meta, and a neutral
Resume when an `isfile()` check says the session is resumable — the pinned "1 of N cited here"
navigator, the turns in the quote face with `CitedSpan`, and the "Noted from this conversation" rows;
a swap onto the same conversation re-lands in place (`ProvenanceRouter.refocus`) rather than stacking
a Back step. The dandelion wash and margin bar are gone (DR-13). It reads `/episodes/{id}/text`
and `/citations` through `ProvenanceCache` — in memory, ETag-revalidated, **never a Store domain**,
so there is no `VersionVector` mapping — slices every offset as a Unicode scalar through one
`ScalarText`, reads a quote and a turn without their markup or role labels (`ExcerptText.stripMarkup` /
`quoteParts`: deletion only, so every span maps exactly; the Reader keeps a turn's lines, drawing a bullet as "•"),
shows a time only when the episode stores one, and says stale / grown / derived /
inferred / truncated in words — a span its rewritten document no longer reaches (the server's 422) is
stale too, never "couldn't open". The entity card's "Where this came from" (Content, after the page and its beliefs) reads
`/entities/{id}/provenance` once per card; G61's section is "Look it up at". Chips read the router
and cache as optional environment values, so a chip outside the main window renders without a
click-through rather than trapping; the Ask sheet steps aside when the Reader
opens (the Belief Timeline is inline in its tab since DS-3a), and a bank switch closes it and empties the cache (episode ids repeat across banks).

---

## API Design

35 routers mounted in `api/main.py`, plus repo-context and maintenance endpoints. **Read the routers
for the endpoint list** — it is not duplicated here. What is *not* derivable:

**Auth.** Every endpoint except `GET /healthz`, `POST /capture/telegram`, an OAuth adapter's
`GET /sources/connectors/{id}/callback`, and OpenRouter's sign-in landing
`GET /connections/byok-openrouter/callback/<nonce>` (R-AG10 — gated by its own single-use, 10-minute nonce
carried in the path, since OpenRouter appends only `code`; the PKCE verifier never leaves the backend) requires `Authorization: Bearer <token>`, from
`~/.cicada/api_token` (`CICADA_API_TOKEN` overrides; `CICADA_API_AUTH=off` for tests). The Telegram
webhook is exempt because Telegram's servers cannot send the header — today it is gated only by
Telegram being configured, not by a per-request secret (**see G57**). Each OAuth callback lands in
the user's browser, which likewise cannot send the header, so it is gated by its own single-use,
10-minute `state` nonce; `auth.py::_is_oauth_callback_path` resolves the exemption live against the
connectors registry rather than hardcoding a literal per adapter.

**ETags.** `/graph`, `/inbox`, `/contributors`, `/sources`, `/sources/channels`, `/origins` and
`/banks` all return an `ETag` and honor `If-None-Match` with a `304`. This matters: `/graph` on the
live bank is ~1.8 MB. **Ship the ETag and its client mapping together** — `GET /inbox` ETags over
`inbox`+`entities`+`episodes`, and `VersionVector.swift` maps `entities` and `episodes` onto
`.inbox`; change one half, change both. `/graph`'s `extra` carries a node-shape tag
(`graph.NODE_SHAPE`), bumped when a node gains a field a client must see or the body changes for
the same files (F1's context filter and fence strip); an entity node's hash also folds its derived
`contexts` and `summary`, so `GraphDiff` re-pushes a node whose derivation changed. `/projects` and
`/projects/{id}/timeline` (G141) ETag over `entities`+`episodes`+`inbox` with `extra` =
`projects|<shape>|<author shape>|<machine zone>` (`git_service.AUTHOR_SHAPE` since round 4, R4B-9) — never today, never a viewer zone — and are **not** Store domains
(no `VersionVector` mapping, fetched on demand like provenance). A timeline item carries at most
12 participants plus `participantsTotal`, and a cluster group at most 8 names no page holds yet
(round 4 D6; `PROJECT_SHAPE` g141-3). The person's writes (G141 PJ-3b) —
`POST /projects/{id}/milestones`, `PATCH /projects/{id}/milestones/{slug}`, `POST /projects/{id}/happenings`
(the Log: one time phrase becomes the day, a companion episode keeps the words), `POST
/projects/{id}/threads/{claim_id}` and `POST /projects/{id}/withdraw` (happenings only) — answer **409**
while Sleep runs and each commits alone over its own pages as `Cicada-Author: user`,
`user/companion_app`.

`GET /videos/state` and `GET /videos/summary` (G162) ETag over `entities`+`episodes`+`sources`+`videoQueue` with
`extra` = `<name>|video-1` (`video_state.VIDEO_SHAPE`, which also rides both provenance ETags) and are **not** Store
domains (the app's `VideoStateCache` revalidates on `VideoRefresh`, no `VersionVector` mapping). The `videoQueue`
component is `<queue file mtime>:<how many leases, failed rows and finished batches have come due>`: a lease lapsing
writes nothing, yet changes the body, so the count is what moves the tag; both reads carry `nextChangeAt` so the app
schedules one revalidation there. The queue's writes (`PUT|DELETE /videos/queue/{key}`, `POST …/retry`,
`POST /videos/run/handoff`) touch no bank file: no commit, no 409 while Sleep runs, and none sits under `/capture/` or
`/sources/`, so queueing works in a demo bank (the demo's queue is a picture of the flow: `cicada_video_claim` and
`cicada_record_watch` refuse it). `GET /videos/run/prompt?count=&method=` is the pure preview.

**Endpoint traps worth knowing before you touch them:**

- `GET /entities/{id}/history/{commit}/diff` — a file's FIRST commit has no parent, so `git show`
  diffs it against the empty tree and it comes back all-adds; a MERGE commit needs `--first-parent`,
  else git emits a combined (`--cc`) `@@@` diff the parser can't read and the endpoint silently
  returns nothing. `truncated` is the UNION of three caps; `linesTruncated` specifically means "the
  ordered list was cut" and is what a client renders its banner on.
- `GET /conversations/recent` is **CAPPED** (limit ≤ 200) and is never a membership test; filters
  (`harness`, `origin`, and `q`, a title filter) apply BEFORE the cap. Use `GET /conversations/{id}` to
  resolve one id against the whole bank.
- `GET /search` runs in the threadpool. `mode=prefix` (the per-keystroke pass) is FTS only and never
  loads the embedding model; `mode=hybrid` (the default) fuses FTS with the stored vectors and reports
  `mode: lexical` when no vector index answered. `totals` are exact **lexical** counts — semantic
  neighbours are ranked, never counted. An `indexState` other than `ready`/`stale` means entities and
  media only, from the frontmatter cache. No ETag: it is never a Store domain. Its query string (and
  `/conversations/recent`'s) is stripped from uvicorn's access log; a new query-bearing GET joins
  `_QUERY_PATHS` in `api/main.py`.
- `POST /conversations/{id}/resume` returns a validated descriptor — **transcripts are never read,
  `isfile()` only**.
- `POST /banks/demo` re-opens a demo bank that exists (200, never re-populated); a real bank that happens to be called
  `demo` still answers **409**. `POST /banks/leave-demo` activates the real bank left most recently (else `default`, else
  a new `my-memory`) and changes nothing outside the demo.
- `POST /maintenance/enrich-links` returns `409` both while a Sleep cycle runs and while another
  call is still running (a process-local lock — two overlapping clicks would stage each other's
  half-written pages under their own trailers).
- `GET /sync/version` is the cheap change-detector (<10 ms); `GET /sync/events` is the SSE stream.
- `GET /projects[/{id}/timeline]` serve absolute days (`tzName` is the machine zone they are bucketed
  in) and never a relative word; the client derives 'yesterday', 'overdue' and 'quiet' through
  `project_state.timeline_state` (its Swift twin shares `api/tests/fixtures/timeline_state.json`). A
  404 means no page or not a `project`.
- `POST /intake/import` answers **202** with `{job}` when more than 10 episodes would be written; poll
  `GET /intake/jobs/{id}` (process-local — gone after a restart or an hour; the episodes are not). One
  stage runs at a time per process.
- `POST /conversations/upload` is a deprecated shim over the one intake — new callers use
  `POST /intake/import`; its `turns` sidecar is a list, as on Stop-hook episodes since G141 PJ-4 —
  only a Stop-hook episode written before PJ-4 holds an **integer count**, so a reader checks the type.
- `GET /memory/decay-suggestions` / `PUT /memory/decay-tuning` (G147) are not Store domains and carry
  no ETag; both answer one shape (`bank`, `windowDays`, `tuning`, `suggestions` — types and counts,
  never a page id). The PUT merges `{type: multiplier | null}` within [0.25, 3.0], answers **409**
  while Sleep runs, and commits `_decay_tuning.yaml` alone as `Cicada-Author: user`.

---

## Features

### 1. Graph Explorer
Force-directed d3 graph: node color by type, size by confidence, edge labels, cluster detection,
decay/clarification indicators. Open ideas live in the backlog.

**The page (Direction D, DS-3a).** The canvas fills the content area under the command bar. Its chrome is one
floating group at the bottom-left — the whose-beliefs text tabs (only with more than one observer; they move
into the Legend under 640 units), Legend, − + fit and the pan toggle — an opaque floating surface, never glass
over the canvas until the G109 frame-time check has run (R-DG2). The Legend is the context legend, the filters
and a key in one: a context click shows only that context, confidence is words, Show logos is a switch. ⌘F
opens find on the canvas as an overlay (⌘K searches everything); the page's own field is gone. A node opens
its entity card as the right-hand column (`GraphColumns`: 560 alone, 480 beside the Reader, never under 440;
the canvas takes the rest and keeps the open node in view by panning, never zooming), and its evidence opens
the Reader beside it. × or a click on empty canvas closes the column with its Reader; Esc closes one thing at
a time — find, Legend, Reader, column; another node swaps the column in place and keeps the Reader. graph.js
posts `backgroundClicked` and `escape` and takes `setSelectedNode` (a neutral ring), read and spelled in one
place (`GraphMessage`, `GraphJS`) and tested on both sides — none of them touches the simulation.

**The entity card (DS-3a).** One component, `EntityDetailCard` — the Graph's column, Clusters' card. Header:
the type as a `Tag`, status and confidence in words ("Active · very confident", the number in `.help`), the
name, the page's Summary, Back ⌘[ and ×; text tabs Content · Perspectives · History · Timeline with counts once
known. Content: Rendered/Source and Copy; the page; its folder or repository in words; What Cicada knows (R-FX11
pages); Where this came from; Look it up at — each G61 source's fact ("For uses"), how it can be read (the
stated `access`, else a path or repo is "A file on this Mac" and an app "An app"; `effective_access` is not on
this endpoint), who added it with their mark, "You chose to use this" / "Only you know this", no check line
until G61 S3 serves one, and the page's open inbox question with Open in Inbox; Details (collapsed, remembered):
tags, related, dates, how it fades. Beliefs are rows — the sentence, its evidence chip and its age, the rest in
`.help`. History: Show in conversation (straight to the Reader when one conversation maps here) and What
changed. Timeline: contested beliefs inline; a belief's clock opens its own.

**Pictures and the person card (G146, round 4).** Every entity avatar is `EntityPicture` over the one picture
precedence (`entity_picture.resolve` and its Swift twin `EntityPictureResolver`, one fixture): the person's own upload
or "initials" → a person's Contacts photo → a brand's logo → a media page's thumbnail → a ring monogram, never a solid
fill; `PictureStore` holds uploads, Contacts photos and thumbnails by URL (the bearer only for Cicada's own paths, never
to a provider), `LogoStore` the logos. Any editable picture opens the image picker on a click, takes a dropped image,
dims under a camera on hover and offers "Use initials instead" / "Remove picture" on right-click; the app shrinks the
picture (ImageIO, ≤ 512 px) and `EntityPictureWrite` paints the answer before the server gives it. A `person` opens
with mock C's top (F-12): an 88 pt picture, the name at 24, the Summary as a standfirst, the picture's source line and a
facts strip whose every cell comes from something the card loaded (`PersonFacts`); then the tabs, and in Content two
columns — beliefs signed with who wrote them (`SignedLine`: harness, model and effort from the captured turn), Where
this came from, the page behind a remembered disclosure — beside *How you know <name>* (`PersonMapLayout`, the graph's
own edges) and *What's happening* (`PersonHappenings`, from `ProjectsCache`). Every other type keeps this header with a
40 pt picture. In Clusters a person's card may grow to 1024 units; the header adds "Show on the graph".

### 2/3. Unified inbox (`memory/inbox/`)
Nudges and clarifications live in **one store**: `memory/inbox/inbox-NNN.md`, each with a `kind`
discriminator (`decay`, `conflict`, `clarification`, `merge_suggestion`, `removal`, `divergence`,
`normalization` — the last two were written by Sleep since G49/G98 but only became loadable and
resolvable kinds with G113; `removal` is written by a live browser sync, not Sleep, at proposal
time (G129 slice 2); `followup`, G141 PJ-6, by Sleep's engine-free tail), behind `GET /inbox` /
`POST /inbox/{id}/resolve`. `api/routers/nudges.py` and `clarifications.py` are thin **deprecated**
shims (they set `Deprecation: true`) kept only for external callers — the app calls `/inbox`.

**Question object (G60).** Every item carries `question`, `options: [{key, label, description, …}]`,
`allow_other`, `allow_defer`, `predicate` and an optional `hint`. Descriptions lead with the age
phrase ("6 months ago") so staleness is visible before choosing; `age_days` is derived at read time,
never stored. Legacy flat `options: [str]` still render.

**Dedup + time.** Items are keyed `(entity_id, predicate)`. A second competing value **merges** into
the open item as another option instead of writing a duplicate. Each Sleep,
`inbox_questions.refresh_open_questions` bumps re-mentioned options, auto-resolves questions the
user answered organically, escalates a question whose every option has been silent for
`inbox_stale_after_days` (90) by inserting "Neither anymore", and keeps deferred items out of
`GET /inbox`.

**Resolve is claim-aware.** Picking an option supersedes every losing claim (`valid_to` +
`superseded_by`); "both" keeps them open with a `context` qualifier; "neither"/free text writes a
`user_stated` claim that closes them; `defer` writes `remind_after`. All commit with
`Cicada-Author: user`.

**Every resolution is a verdict (G113).** The commit trigger names the action taken
(`inbox/<kind>/resolved:<label>`; a deferral stays `inbox/deferred`), decay `archive`/`keep_active`
land as `statusChange` history entries, a decay `keep_active` and a clarification free-text answer
write back to the claim layer, a rejected merge is remembered in `<bank>/_merge_rejected.yaml` so
neither `clarification_manager` nor the dedup sweep proposes the pair again, and `remind_later` is a
7-day defer (shipped with G115 Phase 1). Each of these also records a `resolution` telemetry event —
see Telemetry ledger.

**The page (Direction D, DS-2).** Progressive columns (`ProgressiveColumns`, `ColumnLayout` — DESIGN_RULES §5.3): the
questions alone at full width; a click narrows them to the triage column and opens the question as C's focus card;
"Show in conversation" opens the Reader as the third column. Widths are units (÷ uiScale); the list hides before the
question drops under 440, and when neither the question's 440 nor the Reader's 360 fits they share the width, so
nothing is pushed off-window. **One tap answers, and Undo is a send delay** (`ResolveGrace`, in the `Store`): the
answer leaves `visibleInbox` at once and `POST /inbox/{id}/resolve` waits 5 s (`CicadaTiming.undoWindow`), sent
early by the next answer, `ActivateBank` (before the bank moves), the window closing and quit (`.terminateLater`,
≤ 3 s) — an undone answer makes no commit, claim or G113 event; a page switch does not send. Every kind renders in
the card (`FocusCardVariant`), options come from the server (a follow-up's 30-day "not now" is its own option), the
source is named in a person's words (`InboxSourceLine`, ids in `.help` only), an asserted span is washed and
underlined and a found mention is semibold. Esc closes the Other… field, then the Reader, then the question; keys
never animate. No in-page search field — ⌘K's Inbox group lands in STATE 1. The list takes the
keys when the page appears and after every answer (the question only when DR-27 hides the list), so a
repeated digit never sweeps the queue past its one Undo (DS-3c). An option, an informational value or a merge target
that is exactly a page's id reads as the page's name (`Store.entityNames`, display only). The Sources page's Deletions render the same card and Undo row.

**Cause (G115 Phase 1, delivers G97).** Every item carries its `cause` — episode, timestamp,
conversation, harness, excerpt, offsets — resolved **at read** by `api/services/inbox_context.py` in
three tiers (item → claim → entity), engine-free. The excerpt is ±240 chars around the mention, cut
on word boundaries, **offsets recomputed on every read and never stored**. Nothing resolves →
`tier: none` and a literal `[ no source recorded ]`, served — never a hidden card.

**Checkability (G61 phase 2 S2).** Every item also carries `check` — `{state:
checkable|needs_source|inform_only|never, reason, locus, targets[], rungs[], settle_eligible}` —
derived at read by `source_check.for_item` from the item, the subject page's `sources:`, `owner:`
flag and claims, and the predicate `locus`: pure, engine-free, zero-network, never stored. Nothing
acts on it yet (no check, hold or settle — S3+), and the app does not read it. `GET
/inbox/check-census` and `scripts/check-census.sh <bank>` report it as ids-free counts — the coverage
gate for S3–S8.

**Decay is no longer the special case.** Served as `Still tracking {name}?` with `archive` / `keep`,
synthesised at read from the page's `last_referenced`, never written. (The item *file* Sleep writes for
a decay nudge is only the anchor the app answers; **it is keyed `(entity_id)` and asked once**: an
entity with an open decay item — pending or deferred, raised by the entity path or by any of its
fading claims — is refreshed (`priority`, `updated_date`, and each fading claim it names joins `claim_ids`, so
a *keep* answer reaches every claim the question covered, not only the first), never duplicated; a bank's
older pile of copies is collapsed once by `inbox_migration.dedup_decay_items` (its own `.deduped_decay`
marker, oldest kept, claim ids folded in); and a cycle opens at most
`decay_inbox_cap_per_cycle` new ones (10), lowest confidence first, through one `DecayBudget` shared by
`inbox_generator.generate` and `write_claim_nudges`. What the cap turns away is counted in the cycle's
`sleep_run` row as `decay_nudges_deferred` and raised again next cycle — never silently dropped.) Its question sets
`allow_other: false` and **the whole stack now means it**: free text on resolve is a `400`.

**Neither is a bookmark removal.** Served the same way as decay — two closed options
(`keep`/`remove`), no free text, no recommendation (the proposal came from the browser's own
before/after diff, not the extractor) — `remove` archives the media entity it named; it is never
deleted.

**Follow-ups (G141 PJ-6).** A quiet ongoing happening (quiet ≥ max(21 days, the project's own Q)), a
planned milestone 3 days overdue, or a `due` that expiry closed in the last 14 days raises one
engine-free `followup` item — at most one open per project and three in the bank — written by Sleep's
tail right after expiry (`Follow-ups <date>`, `cicada`, `sleep/followup`, dirty pages skipped) and served
as a question at read, like decay. Its 'not now' is an explicit option that defers 30 days (`allow_defer`
false, so the shipped app's 7-day button never shows; the server clamps any defer to 30). Answers go
through `progress.py` (origin `clarification`) and grade the extractor: done/still agreed, 'That didn't
happen' overruled, a person's own thread always neutral.

**G98 rule.** A multi-valued predicate never opens a conflict; an existing one is served
`informational: true` — the card lists the values and offers `Got it`, which removes the item and
touches no claim.

**Three resolution paths for a clarification:** organic (the user provides context later, Sleep
promotes it), agent-initiated (the agent asks in flow when the topic comes up), manual (the app).

**Observer inconsistency — resolved (G117).** All five sites (the inbox resolve path, Telegram
capture, `agentic_write`'s trust/origin gate, and MCP `cicada_write_claim`'s schema/description) now
read `owner_identity.resolve_observer` instead of a hardcoded literal, so a bank's claim lineage
never forks across writers.

### 4. Manual Sleep trigger
"Run Sleep cycle now" + next-scheduled indicator. A person's trigger **drains the queue** (see Sleep — Consolidate reads
everything, TODO ruling 13); `POST /sleep/cancel` says so ("Batches already filed stay filed"), and while a drain runs the
bank-switching routes answer 409. `POST /sleep/trigger` takes an optional `{"continue": true}` (Sleep page v5).

**Schedule modes (G125 R6/R7).** Settings → Schedule offers four modes on `ScheduleConfig.mode`:
`manual`, `daily` (hour/minute), `interval` (`interval_hours`, 1–168, default 6), and `after_import`
— no writer hooks an import; `sleep_scheduler` installs a 5-minute `IntervalTrigger` probe that
fires `run(user_triggered=False)` only once the queue has *settled* (idle, non-empty, and the
newest unprocessed episode is ≥ `AFTER_IMPORT_SETTLE_MINUTES` (10) old — `SleepDebt` carries
`newest_unprocessed_at` so the probe and `next_run_at` share one scan). `enabled` is derived
(`mode != "manual"`) and always written on the wire so an older client still decodes; an old
`PUT {enabled,hour,minute}` with no `mode` is accepted and mapped onto `daily`/`manual`. Every
scheduled path — daily, interval, or the settle probe — passes `user_triggered=False`, so a
scheduled cycle never spends Claude or ChatGPT plan quota (the standing ruling in `TODO.md`), **and reads everything
waiting, in batches** (ruling 16: unattended, on the scheduled engine — on a key that is spend with no limit Cicada sets; a
paused run is left for the person to continue or end; the tail still runs over it).

### 5. Conversation upload
**One chat-export pipeline (Track I).** Claude, ChatGPT and Gemini exports — a whole .zip, a
folder, or one file — go through `api/routers/intake.py`: every member a parser knows (a Claude
zip's conversations, memories and projects), the known extras (`user(s).json`, feedback and
comparison files, ChatGPT's `chat.html` viewer) skipped **by name**, the vendor's `origin` stamped
on every path, per-message times kept as `turns: [{offset, ts, speaker}]` outside `content_hash`,
and re-imports updating grown threads in place (G20) without duplicating. `POST /intake/sniff`
previews and stages nothing; `POST /intake/import` stages. `/conversations/upload` (deprecated,
`Deprecation: true`) and `/banks/{name}/import` are shims over it.

---

## UX Principles

1. **Minimal friction**: responding to a nudge = one tap. Never require "memory maintenance".
2. **Transparency over magic**: the user sees WHY the agent knows something (provenance), WHEN it
   learned it, HOW confident it is.
3. **User authority**: agent proposes, user disposes. Every automated action can be overridden.
4. **Non-intrusive nudging**: available when wanted, not pushed. The inbox is there when you want it.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Markdown over Neo4j | Same relational expressiveness at personal scale. Zero infrastructure. Portable. The LLM is the query engine. |
| sqlite-vec over LEANN/FAISS | Stored (not recomputed) vectors give single-lookup latency with no cloud dependency; the index is derived and disposable. |
| FTS5 beside sqlite-vec | Type-as-you-go needs words, not meanings: a derived lexical index answers a prefix in ~12.5 ms p95 at 2k entities / 1.5k episodes without an embedding call, and finds aliases, claims and conversation text by what they say. Derived and disposable, like the vectors. |
| Batch over real-time consolidation | Conversations don't have clean endings. Batch sees patterns across a full day. Clean evaluation. |
| Entity promotion over upfront extraction | Avoids polluting the graph with noise from single mentions. |
| Temporal decay as an active signal | Absence of mention is informative. No other system does this. |
| Clarification queue over silent drops | Ask rather than guess or discard. Prevents cascading hallucination. |
| MCP-native + export fallback | MCP for real-time, export for ChatGPT/Claude. Source-agnostic pipeline. |
| SwiftUI + FastAPI | Native macOS feel. Python backend for the LLM/ML ecosystem. |
| d3-force in WKWebView | Best graph-visualization ecosystem. Sufficient at personal scale (G109). |
| Filesystem as single source of truth | No separate database. The API reads/writes the same files as Sleep. |
| Decay class over a bare per-writer rate | A hardcoded float was invisible to the agent, unchangeable by the user, and decayed bookmarks — artifacts that never become less true. |

---

## Reaching the outside world

Three gates, and they do **not** mean the same thing — read the difference before adding a fourth:

- **`CICADA_ALLOW_CONNECTOR_FETCH`** gates the default transport of every fetch Sleep starts on its
  own: the unattended nightly connector poll, **link enrichment's page read** — Stage 5.57's
  in-cycle pass (`sleep_cycle._link_summarizer`, G61 phase 2 S0) and the G102 tail backfill, both
  through `link_enrichment.default_fetch`, the rail's reference transport — **the site check** (G61 S3-b: the Sleep tail's
  `site_sources.verify` reads a proposed official site through `link_enrichment.fetch_identity`, which shares that
  transport's `_stream_html`; a walled or platform host is never requested) — and paper details
  (below). It is **opt-OUT** (on by default; `=off` disables it, which is what the test suite sets).
  A user-initiated `sync_now`, `POST /maintenance/enrich-links`, `POST /maintenance/verify-sites`, every OAuth
  `authorize_url`/`exchange_code` call and OpenRouter's sign-in key exchange (`openrouter.ai/api/v1/auth/keys`,
  R-AG10; the key lands only in `secrets.env`) are **never** gated by it — they always need the network to
  do what the user just asked.
- **`CICADA_ALLOW_FEED_FETCH`** gates RSS/ICS polling and is **opt-IN** (`=1`). A fresh install's
  LaunchAgent plist sets it; `install.sh` never rewrites a plist behind a running backend, so an
  older plist needs the key added by hand.
- **`CICADA_ALLOW_LOGO_FETCH=off`** disables logo fetching entirely. The test suite runs that way
  and injects fetchers instead. It also gates the icons of the sites Settings, Reading the web, lists (G166): those
  come from the icon service only and the login-walled site is never contacted for its favicon (nor, since
  `fetch_logo` skips its first two rungs for a walled host, is a company or tool page's logo domain when it is one).

**The remote connector (G135) — the one way in from outside this Mac.** Off by default
(`~/.cicada/remote/settings.json`). When on, a **second listener on `127.0.0.1:8765`**
(`CICADA_REMOTE_PORT`) serves **only MCP** — none of the FastAPI routers — to cloud AI apps
through a tunnel **the person** runs (Tailscale Funnel or ngrok); **Cicada never starts, stops or
reconfigures a tunnel** — `GET /remote/status` only detects one — on PATH or in
the standard install folders, since an older LaunchAgent's PATH is bare (F2-back R-B15). Access is a per-connector
capability token `cic_rc_<id>_<secret>`: shown once, only its sha256 stored in
`~/.cicada/remote/connectors.db` (0600, never in a bank), scoped (`search`/`read`/`record` default;
`sources`/`answer`/`ask` opt-in — `sources` gates every verbatim word of the person's, recall's
episode excerpts and the inbox `Cause:` quote alike; `pending`, `mark_processed` and `repo_context`
never), expiring
(7/30/90 days) and revocable. It arrives as a secret link (`/c/<token>/mcp`) or a bearer header —
one verifier. Tools outside a connector's scopes are absent from `tools/list`; any `Origin` header
is refused; the listener has no access log (a secret link's path IS the token). Every remote write
commits alone as `Cicada-Author: <app harness>`, `Cicada-Session: rc_…`, trigger
`remote/<harness>`, no engine; a remote claim is `origin: remote:<id>` and can never be the
person's own words. Each call leaves one ids-only `remote_call` ledger row, filed beside `read` in
`reads-*.jsonl` so it never ticks the app's consumption domain. Every server-side fetch of someone
else's URL goes through `net_guard` (`is_global`, never `is_private`, because tailnet addresses are
neither; the name lookup runs off the event loop).

**A failed poll is recorded, not raised** (`sync_state.record_error`) and surfaces per-channel as
`lastError`; a gate-skipped poll is recorded distinctly (`record_skip`) so a skip never reads as a
failure or as a stale success.

**Paper details (G133) ride the first gate, not a fourth.** The unattended Sleep-tail lookup is behind
`CICADA_ALLOW_CONNECTOR_FETCH`; a folder sync the person asked for (`?resolve=true`) is not. Only two
APIs are ever called — `export.arxiv.org/api/query` (≤ 50 ids a request, ≥ 3 s apart) and
`api.crossref.org/works/{doi}` (public pool; no email is ever sent) — at the rail's 4 s / ≤ 512 KB;
arxiv.org pages and PDFs are never fetched, and a 403/429 stops that API for the run. That holds for
a paper link saved any other way too (a bookmark, `cicada_save_url`, Telegram): `papers.never_scraped`
keeps arXiv/DOI links and every arxiv.org page out of save-time enrichment and the link backfill.

**Reading with an agent (G166) does not loosen the rail below; it sits beside it.** The rail governs *Cicada's own*
fetcher, and the backend's page readers (`media_ingestor.enrich`, the `link_enrichment` backfill) no longer fetch the
page of a login-walled host (R-RW4, one closed set in `reading_hosts.py`, which also closed the X gap; TikTok's provider
oEmbed call and the Reddit and X connectors' own API calls remain, and none loads the walled page). What the person's own agent does in its own signed-in browser is the person's and the
agent's, not Cicada's: Cicada only *asks*, per link or per site the person turned on after a page from it could not be read, after a
first-use acknowledgement, and promises nothing about what the agent does there. The backend never holds a session, a cookie or a
browser profile. An ask's URL is the person's explicit hand-off to their agent, and a site entry's URL rests on the person's grant for
the site, so a remote connection holding `read` sees them (TODO ruling 14; a site entry from a channel that is the
person's own words needs `sources`); `sources` still gates every verbatim word of the person's conversations and any
chat-harvested URL.

**The ToS rail — this one is not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never
behind auth. Consent interstitials and login walls are classified and retired as `junk` **without a
byte fetched**. **A block is never retried with different headers.** No scraping behind
authentication, ever.

**Credentials** live in `~/.cicada/secrets.env` (0600) — **never in a bank, never logged**. The
shared `base.forget()` removes them on disconnect, so a fields-vs-stored drift can't orphan a
secret. Where a vendor bills per request (X's "owned reads"), the sync result carries the count so a
cost is stated plainly rather than hidden behind a "connected" checkbox.
Cicada's own Codex sign-in lives in `~/.cicada/codex/` — Codex's files, never opened by Cicada,
never in a bank.

**Video (Track V, 2026-09-05).** Only a provider's own player URL is ever loaded — YouTube
(`youtube-nocookie.com/embed/…`, incl. `videoseries?list=`), Vimeo, TikTok and Loom — and an
oEmbed response is read for its *fields* only, never its `html` blob: the player URL is derived
from the id by `video_urls.resolve` / `VideoRef`, so nothing a provider returns is ever executed.
**A stream is never derived** — no `yt-dlp`, no CDN or `.m3u8` URL lifted out of a page — so a
direct file the app plays is one the *user* saved as a direct URL. Twitch stays external (its
player validates `parent` against the real embedding origin; synthesising one is circumvention),
X and Instagram stay external. The app itself makes **no** network call to classify: oEmbed runs
only on the ingest/enrich path, under the gates that path already has, and the three new
provider calls take the rail's own 4 s / ≤ 512 KB numbers rather than the older, looser `_TIMEOUT`.

---

## Installation & Setup

`install.sh` is the source of truth; `install.md` is the paste-into-your-agent path for a fresh Mac
(clone → `./install.sh` → `make install-app` → open the app; G76), and it never loops `make doctor`.
The rest of the paste-prompt install story is G76 in the backlog.
`scripts/install-backend-agent.sh` is the one source of the `com.cicada.backend` plist; `install.sh` step 6 calls it
behind its healthy-skip guard, and the app runs it from Settings → General (G143). `BackendProcess` spawns
`python -m uvicorn`, never the venv's `uvicorn` script. `make login-item` is the old developer path; the app's switch
is the supported one.
