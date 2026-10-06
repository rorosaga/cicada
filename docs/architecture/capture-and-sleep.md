# Capture and Sleep

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

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
  `next_episode_id` is max-suffix+1 per date (a count-based rule collides after any gap), and timestamps are aware UTC from
  `episode_ids.utc_now_iso` — never a naive local time with a `Z` appended. Legacy files are not
  migrated: readers accept both shapes and the queue sorts by `timestamp_sort_key`. A processed
  episode carries `processed_by` (`sleep` vs `agent`) so a flipped flag is distinguishable from a
  consolidation. `processed_by` also takes `user` — a companion note the person wrote in the app
  (G141 PJ-3b's Log; already processed, so Sleep never re-reads it).
- **Unique across processes, revision-safe against Sleep** (audit 2026-10-02 K01/A01). A new episode
  is created with `episode_ids.create_episode`, which never replaces a file: when another process
  (a stdio MCP server, the Stop hook, the backend) took the minted id first, it mints again. Dedup
  checks and every read-modify-write of an existing episode — transcript capture's
  find-session-or-update, MCP `save_episode`'s hash check, each stager edit, rename, restamp and
  tombstone, and Sleep's retirement — run under `episode_ids.episode_lock`, an `flock` on the
  episodes directory's own descriptor (cross-process, re-entrant per thread, nothing created in the
  bank), held for one operation and never for an import or a stage. Staging temp files match
  `.*.tmp`, which every bank's ignore rules carry (`bank_registry.DERIVED_ARTIFACTS`). Sleep records a
  `body_revision` (sha256 of the text it extracted) per episode and flips `processed: true` only
  when the file still holds that text; a session resumed or a source edited mid-cycle stays queued
  for the next run (the drain in progress counts it settled — its earlier revision was filed — so a
  growing conversation never keeps one drain re-reading it). Capture never waits on Sleep for longer
  than one episode's retirement. **An agent's mark is revision-checked too (2026-10-05):**
  `cicada_pending` shows each episode's `rev` and the MCP process remembers it; `cicada_mark_processed`
  (`agentic_write.mark_episodes_processed`) retires an episode only while its text is still that rev
  (or one passed in `revisions`), refuses an id it never listed, and reports a conversation that kept
  going as changed, left for the next pass. **MCP hash dedup (G183(c)):** `save_episode` scans episode
  text outside the lock, recording each file's signature before reading it. Under the lock it checks
  the current names and signatures (device, inode, nanosecond mtime/ctime, size), re-reads only new or
  changed files, then mints and creates. A duplicate added or edited during the scan is still refused;
  an atomic replacement or a same-size edit with restored mtime cannot reuse a stale check. Metadata
  enumeration remains under the lock, but unchanged episode text is never read there. The shared
  source-keyed stager retains its cached frontmatter scan and identity rules.
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
Home's "Last read" shows the last batch's pages. Details › Last cycle's cost line and "took" row still come from the newest history commit (one batch) — the run's own totals are in Past nights' run row. **Pause and a hard plan rejection mid-batch still discard the batch in progress** (no journal of paid answers — the tail must say "the part it was reading is read again", never "read and kept"). A scheduled drain pins its bank for hours (the same 409 as any run) and, on a metered engine, has no ceiling Cicada sets. The **app's own** Projects and Backlog controls key off `writing` (`ProjectWriteGate`; `/status` and the SSE `sleep` event carry it, and the sync version's `sleep` component moves when it flips), so they are disabled, saying "Sleep is running", only inside a batch's write window and come back between batches; an older backend without the field falls back to `running`. After a stop, Details says how many stay filed and never a batch count (the wire's `batches` is the plan); a cancelled or plan-paused strip and tail retire with the backend's cancel window and the vendor's reset time respectively. A drain on a consumer plan is the largest plan spend Cicada makes; the "leave room" reserve covers every window the engine reports (the 5-hour and the weekly one alike), is a line and not a guarantee, and a window the engine never reports is served `enforced: false`.

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
