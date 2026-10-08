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
  (`api/hooks/capture.py` → `POST /capture/transcript`). Cursor's local IDE integration supplies startup
  context/MCP only; automatic capture is unsupported, no Stop hook is registered and no Cursor transcript
  is read (current nullable pointer has no proved confinement/format contract; `mcp.md`).
  **The flush (G110 gate A, owner ruling 2026-10-07):** the
  same command is also registered under `PreCompact` and `SessionEnd` (install.sh step 5b, both harnesses; the app's
  Connect through `flushOn`). Stop stays the trigger (TODO ruling 7): a flush is the same idempotent request —
  `unchanged` after a Stop with no new turn — and it is the only capture of a turn the person interrupted (no Stop
  fires) before compacting, clearing or quitting, which the requested continuity read then discloses as "its last request
  has no captured reply". A SessionEnd flush bounds its request with a 1.2 s client timeout (a socket
  timeout, not a whole-process deadline; the backend finishes the write regardless). Claude Code's SessionEnd budget is
  1.5 s by default but is raised to the largest per-hook `timeout` in the settings files, and Cicada registers 5 s — so
  the flush can delay an exit by about that request timeout plus interpreter start, not "within 1.5 s". **A stale
  capture never overwrites a newer one** (fix round 1): a write records the transcript bytes it read
  (`transcript_bytes`, outside `content_hash`), and under `episode_lock` a capture that read fewer bytes than the
  episode stores — while the file now holds at least that much — writes nothing and answers `superseded` (a flush that
  stalled while a later Stop committed). A transcript that really shrank is still captured. Every `~/.cicada/logs/capture.log` line names its event
  (`<harness> <sid8> Stop|PreCompact|SessionEnd|other …`), so ruling 7's revisit signal — a Stop `error:` line — is
  never confused with a flush's; the capture ledger row carries the same enum as `event`. `autosave` in
  `/agents/wiring` stays the Stop hook alone, so an install from before the flush is never shown as broken; `make doctor`
  passes an absent flush with a note and fails only a half-registered or stale one. **The backend reads the transcript**, and
  only after the path resolves under the harness root as `<session_id>.jsonl` within the size cap —
  anything else is refused unread. `transcript_extract.py` keeps only the person's turns and the
  agent's final reply per turn; tool calls, thinking, file dumps and harness-injected text are
  skipped by construction. From a kept agent turn it reads two more facts and nothing else (round
  4 C1, G49 lifted for harness writes): the model id (Claude Code's `message.model`, Codex's
  `turn_context.payload.model`) and the reasoning effort (Claude Code's top-level `effort`, Codex's
  `turn_context.payload.effort`, and for the last reply the Stop hook's stdin `effort.level`). Both
  are cleaned by `agent_turns` (an effort is one of `minimal|low|medium|high|xhigh|max`, and
  anything else is dropped). They ride the sidecar on agent entries only; the transcript wins over
  the hook. **Retention (G110 A2, owner D1/D1-tail):** after the same fence removal and secret scrub, the first
  eligible person message keeps its head up to 16,000 characters (including a terminal ellipsis if clipped).
  Structurally excluded housekeeping/meta records and empty cleaned messages do not consume that allowance.
  Later person turns keep their head up to 2,000. A final agent reply keeps approximately equal head and tail
  within its existing 2,000-character budget, including the newline-delimited
  `[Cicada: part of this reply was not kept]` gap and a fixed `…` prefix on the resumed tail. The prefix prevents
  a mid-line cut from manufacturing a turn-marker line (`user:`, `assistant:`, `speaker:`, timed video, etc.).
  Both fragments remain nonempty; tiny explicit caps that cannot fit the gap, prefix and both sides use head clipping.
  The recorded gap offset and omitted count use the actual kept cleaned text; neither raw secrets
  nor code are retained elsewhere. Short replies stay whole. Tool calls/intermediate replies remain excluded.
  The first message spends the same session budget as every other turn; the 100,000-character ceiling is unchanged.
  A paired synthetic Stage-1 diagnostic (20 sessions, first person message 14k, six turns each) grew stored body
  text from 169,740 to 409,740 characters. Keeping only the longer first message grew actual extraction messages
  (system + user, including overlap) from 328,180 to 736,620 characters and calls from 20 to 40; A2's reply-gap
  notes brought messages to 740,480. This is input size through the real loader/chunker with fake completions,
  not measured model tokens, dollars, full-Sleep quality or real workload cost.
  **The session cap keeps the head and the tail
  (G110 gate B2, owner ruling 2026-10-07).** Under `SESSION_CAP_CHARS` (100,000 characters of kept turn text) every
  turn is kept. Over it the body is the HEAD — the longest prefix within 60,000 (3/5 of the cap; its offsets never
  move, so G118 spans into it stay exact) — then one marker line, `[Cicada: <k> turns from <t1> to <t2> were not
  kept]` (`evidence.gap_line`, the one spelling), then the TAIL: the latest turns within 40,000, starting on a
  multiple of `TAIL_BLOCK_TURNS` (10) so it advances in blocks of whole turns rather than on every Stop; the latest
  turn is always kept. **The marker is Cicada's own line, never a speaker's, for every consumer** (fix rounds 1–2).
  It is known ONLY from the episode's own record, never from its words: `evidence.gap_ranges(frontmatter, body)` takes
  `capture_gap.offset` when the line there opens with `[Cicada: ` (even if edited since), else the one whole line that
  spells the record's own marker (an older or shifted body), else nothing. An episode without `capture_gap` has no
  session gap. Reply gaps require the exact reply marker at a recorded `reply_gaps.offset` and a positive
  `omitted_chars`; there is no text-pattern fallback. Without either recorded range, a person who pastes marker-like
  words — and everything they wrote after — keeps them as theirs. Every reader
  takes those ranges as `gaps`: inside one, `speaker_kind`/`kind_for` answer `gap` (no declared authorship covers it)
  and a following line that opens no turn goes back to the speaker before it; `verify` makes any touching span
  `reasoning` (read from disk it uses the episode's own record; Stage 1 passes it); the Reader draws the line as its
  own block labelled "Not captured · Cicada's note" (Reader indexes still count blocks); `turn_at` skips it and
  counts a resumed reply tail as part of the original turn. Reply fragments retain time, model and effort;
  a focus on the gap never highlights; the span
  route answers `gap`; the lexical index blanks it to spaces (`mask_gaps`, offsets kept) and keeps the range in the
  row's meta, so a hit on it carries no span, kind or hash; vector chunks are cut from the blanked body; Stage 1
  blanks it on the WHOLE body before the production chunker slices (so no chunk can open on a fragment of it) and
  tells each chunk that touches it in a separate note ahead of the conversation; an agent reading an entity's source
  episodes (`cicada_sources`) sees Cicada's note in its place (`label_gaps`); and the continuity reader cuts it from
  the head's last turn at the same range, and labels reply gaps as nobody's words within the agent reply. The G118 sidecar and
  `tail_turns` are built from the head and the tail separately, so every offset stays exact around it. A reply's
  `model`/`effort` that only the stored sidecar knew is carried to the new sidecar only for the SAME reply — same time
  and the identical rendered text at its old offset — and remapped to wherever it sits now; a reply that slid onto an
  old offset never inherits another's. **The G104
  costs the ruling accepted, stated plainly:** (1) while an over-cap session is active, every Stop with a new turn
  changes the body and re-queues the episode for a whole-body re-extraction — no `metadata` short-cut, unlike the
  head-only cap it replaced; (2) when the tail slides, a claim quoting a turn that slid out is re-extracted as
  `reasoning`, and an existing span into the old tail (or into the 60–100k region, once the cap is first crossed)
  reads `stale` — the claim is still written; (3) more `body_revision` mismatches between Sleep's read and its
  retirement while the session runs; (4) the person's words in the dropped middle leave the bank (they are disclosed
  in `capture_gap` and the requested continuity read, never kept). **One episode
  per session** — a later Stop rewrites it in place and flips `processed: false`, never two
  episodes for one conversation (G104). Cicada's own `claude -p` and `codex exec` spawns run with
  `CICADA_CAPTURE=off`. **Where capture stopped (G110 slice 1a).** Every write also records, outside
  `content_hash` and before `turns`: `last_turn_at` (the last kept turn's own time), `turn_count`, `tail_turns`
  (the last 8 kept turns as `{offset, speaker, at?}`, exact offsets into the body — the G118 sidecar stops at 500
  and skips untimed turns), `capture_gap` (`{dropped_turns, first_dropped_at?, last_dropped_at?, offset}`, only while the
  session cap drops the middle; an episode captured before gate B2 may still carry the older
  `{dropped_turns, last_seen_at}`, which the requested continuity read labels "turns past the limit"),
  `reply_gaps` (`[{offset, omitted_chars}]`, kept clipped agent replies only) and `capture_flags`
  (`first_request_clipped: true` when the cleaned first person request exceeded 16k; `note_like_turns`, kept person turns holding a line that opens like a
  Cicada note — counted and kept, never removed for that), optional `workspace_identity` (hook-observed family,
  checkout and cwd hashes plus time; B2, `mcp.md`), plus `continues`: the one episode id the continuity
  registry says Cicada pointed this session at, stamped once and never rewritten. An unchanged body whose metadata
  moved (a late `continues`) is rewritten in place under `episode_lock` with the same body,
  hash and `processed` state — status `metadata`, nothing re-queued. The capture ledger row gains the two counts.
  **Recall is the same move (G149):** the harness's `SessionStart` and
  `UserPromptSubmit` hooks (`api/hooks/recall.py` → `POST /capture/hook-context`) put Cicada's note
  in front of the model: the primer at session start, and the pages a message names on every
  prompt. Recall therefore no longer depends on a model calling `cicada_recall`. The prompt travels
  in a JSON body and is never logged. **What capture drops of a note (G110 gate C, owner ruling 2026-10-07:
  harness-marked only):** a Cicada note is dropped only when the harness records it as a whole record that is not the
  person's — Claude Code's attachment/hook records and `isMeta` user records, Codex's non-user roles — which is how
  Claude Code documents hook context. Text inside the person's own block is kept as their words, whatever it looks like
  (a pasted note, a quoted header line, a `<session-start-hook>` tag): it is counted in `capture_flags.note_like_turns`
  (a line that opens with `recall_text.INJECTION_PREFIX`, past any leading tags) and the requested continuity read
  discloses the count. The textual `is_injection` deletion and the hook-tag span/first-tag rules were removed for
  person text; G105 R5's tool-output rules — the `<system-reminder>` span strip and the first-tag skip for harness tags —
  are a different rail and stay.
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

**Claim preservation (G148 regression):** Stage 5 rewrites prose with the stored `claims` fences removed from section parsing, then reattaches those fences unchanged. Rebuilding `Related` cannot remove beliefs before the claim pipeline reconciles them; synthesis output never authors a claims fence.

**`Related` reads the edges once:** `apply_changes` builds each entity's edges from `graph_edges.yaml` on the first update that needs them and reuses them for every page that pass merges (nothing in the pass writes the file); every reader of that file uses `markdown_parser.load_yaml`, the libyaml safe loader. The file grows with the claims; on a 2,000-page synthetic bank one pure-Python read cost ~3.8 s and was paid once per merged entity (`benchmarks/scale`).

**The claim write-back renders only changed pages:** `run_claim_pipeline` keeps each page's claims as read (by value — the reconciler edits claims in place) and skips the parse/render/write of every page whose reconciled claims equal them and that gains no episode credit; such a page still counts as written. On a 2,000-page synthetic bank ~1,940 of 2,006 renders per batch were byte-identical (8 s).

**Item provenance (G118 sections, 1a-i).** After extraction, Summary/description and
Key Facts receive transient source-episode `reasoning` records over the full stored body
hash. This adds no prompt instructions, quotes, retries or calls. Stage 2 carries metadata
with the fields it actually selects. After G169, it follows the chosen effective Summary,
its description copy, the fact union, and orientation text retained as facts; only exact
selected text receives the original source record. Carry unions unique evidence rows per
selected field/text, so repeated mentions cannot multiply identical records when Summary
and description share the same words. The pending-store limitation remains; earlier pending
facts are not restored by provenance. Stage 5 records exact surviving items
on create and fallback/human-safe updates. The B-update fixture retains A's Summary only
when B supplies no new Summary (or one already contained); an appended Summary invalidates
that one item's guard while A's facts keep their links.

Sleep synthesis retains exact old items by identity, without changing its prompt/return shape.
Rephrased items become unrecorded; incoming facts not supplied to synthesis cannot gain links.
All refreshes share the existing atomic page write, locks and commit/rollback boundary.
Any open code fence can hide sections from the original or final body: refresh preserves
their stored records and guards, reporting unavailable metadata until the body is readable.
Closed claim fences exclude their machine text even if the claims YAML is malformed or repeated.
Inbox/merge selected-input hooks, other prose sections, Related claim navigation and rephrasing
selection are later scope; existing preserved records still fail closed through exact guards.
The paid quote prompt is **1a-ii (💸), deferred** until owner approval and a reviewed paired
G148 usage/locate-rate pilot; the reasoning-only slice does not authorize that spend.

**Dates in the prompts (G194 A1, 2026-10-07).** Every model call that writes about a conversation is told when it was
said and what day it is now (`api/services/source_dates.py`).
- **Stage 1.** Every chunk, and its one retry, opens with Cicada's date note, after the gap note when there is one. The
  note gives the conversation's own day (its `timestamp`, else the date in its id: the same rule as a claim's
  `valid_from`) and today, which is fixed once per `extract()` run. For a conversation older than `OLD_AFTER_DAYS` (90),
  the note names the month and year to write it as of. An undated conversation gets no note, and nothing is guessed.
  The system prompt's TIME rules say:
  - write as of the conversation's date;
  - name the month and year for anything changeable from old material, and for every plan or intention;
  - never use "currently" or "recently";
  - resolve relative phrases in the direction the sentence states;
  - keep explicitly stated dates.
- **Merge and contradiction.** The synthesis prompt (both callers: Stage 3 and an inbox conflict answer) gets today, the
  page's `last_referenced` and every day the new information was said. "Newer" means a later date, not a later read.
  Those days are the ones Stage 1 resolved (a conversation's timestamp, else its id's date: `source_episode_day` on the
  extracted entity, `source_episode_days` on Stage 2's change). They are prompt-only: `last_referenced` and `created`
  still come from the stored timestamps, and no timestamp is invented from an id.
  The contradiction prompt dates both descriptions.
- **What this changes, and what it does not.** The note is in the model's message only, never in a stored body, so G118
  offsets and hashes do not move. A quote of the note itself degrades to `reasoning`. **This is prompt guidance:** no code
  path checks or rewrites what the model returns, and pages written before it keep their present-tense prose. The
  code-level floor (A3), the one-off pass over old pages (B) and intention claims (C) are deferred, with their open
  blockers listed in the G194 plan.

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
conversation that fails **for its own reasons** (an empty answer, a provider request timeout, an unparseable reply — `sleep_drain.classify_episode`)
goes first in the very next batch for **one more try and is then parked**; a failure that is the **engine's** (signed out,
throttled, exhausted, model not found) stops the run after the batch commits what it read and is never counted against a
conversation. **Transient CLI engine failures (G171/G163):** extraction already retries each call once (10 s after
`EngineTimeout`, 2 s after `EngineFailed` or `EngineProtocolError`). Retry eligibility alone does not diagnose an
outage: `TRANSIENT` names only `EngineTimeout`, `EngineConnectionLost` and `EngineProtocolError`. Other CLI calls
inside a drain retry only those positive diagnoses once at the provider seam, releasing the concurrency permit
during backoff. A first exhausted extraction timeout discards the batch before Stage 2, including successful
reads in a mixed batch. Once doomed, the batch starts no further Stage-1 calls; calls already in flight finish.
The sidecar persists timeout observations by episode across Continue and process restarts. Each previously
observed id that times out again can receive its second conversation attempt and be parked (`timed_out`), even
when multiple ids time out together or the batch has no healthy neighbor. A newly affected id still pauses first;
its discarded leg retains observations but charges no content attempt. Connection loss always pauses and never
charges a timeout/content attempt.
An unnamed `EngineFailed` during extraction is content `other` only when another conversation was read in the
same batch. It then gets the normal next-batch retry-then-park without discarding healthy reads. A lone retry
may use already-filed work in this run plus its existing attempt as that evidence. When nothing was read and
every input failed unnamed, a fresh singleton or a multi-input batch stops as `engine/needs_fix`: no new content
attempts, no parking, and no calls beyond that batch. Earlier successful batches do not exempt a fresh or
multi-input failing batch from this guard. Generic unobserved failures on every conversation retain the same
engine guard. An unnamed failure escaping a later stage is an error with a
trimmed diagnosis (up to 300 characters), not a transient pause or a promise that retrying will fix it.
A positively transient error escaping a later stage pauses with reason `engine`, no `error`,
reset time or auto-continue. The frozen ids and prior committed batches stay intact; Continue resumes the same run
and reads the interrupted batch again. An empty/unparseable extraction answer still gets the conversation
retry-then-park rule. Positively identified authentication, model and plan errors are never retried by this policy;
an unclassified extraction rejection retains its legacy call retry. Calls outside drains retain their existing policy.
**Connectivity (owner, 2026-10-07):** failed CLI transport diagnostics (routing discovery, exhausted reconnect
warnings, DNS, refused/reset connections and offline/network errors) become `EngineConnectionLost`, a retryable
`EngineFailed` subtype. The existing one-retry/2-second policy then pauses with Continue; repeated connectivity
loss never consumes an episode's timeout/parking attempt. Detection includes empty/non-JSON failed output and
the reading engine's connection-retry metadata. Completed turns that recovered from reconnect warnings remain
successful; sign-out, model, quota and billing diagnoses outrank old reconnect notices. Raw diagnostics remain
available in Details, while the page speaks provider-neutral pause/fix copy.
Routing-discovery authorization/account errors and the reading engine's authentication/login and low-credit
diagnoses are explicitly non-transient. Failed-turn warning events only inform connectivity detection, not model,
auth or quota matching; a timeout stays a timeout despite an unrelated unsupported-config warning.
An id another writer marked processed meanwhile is `skipped`, and a bank switch between batches stops the run (`bank_switched`; `activate`, `demo`,
`leave-demo` and the active bank's rename answer **409** while `SleepState.drain_run`). **A scheduled cycle drains too**
(ruling 16: both scheduler entry points pass `drain=True`) but with `user_triggered=False`, so automatic engine
selection never chooses a plan (ruling 4); on a metered engine it spends until the queue is empty, with no limit Cicada sets, and the engine menu and Details
say so in words. The default scheduled BYOK/local selection is unchanged; an explicit `CICADA_LLM_MODE` CLI
override also reaches the transient retry/pause policy. Such a scheduled engine pause is eligible for replacement
by a fresh unattended run only after six hours (`sleep_paused.ENGINE_RETRY_S`), rather than the next scheduler tick.
**Once per drain, not per batch:** temporal decay (both engines,
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
(projects, entities — the decay class and repo links since G183(a) —, the inbox's every resolve door, backlog, local
sources, memory, maintenance — the dedup sweep since G183(e) —, the remote connector's writes, paper details) and behind
`GET /sleep/status`'s `writing`, which MCP's `_backend_sleep_running` and `BACKLOG_SLEEPING` read. A plain or scheduled cycle
holds the bank for its whole run, as before; a drain holds it only from a batch's Stage 2 (which loads the pages Stage 5
rewrites) through its commit, plus the run's start and its tail. Stage 1's engine calls and the gaps between batches touch no
page, so the *server* accepts page writes there and a stdio agent's claim **commits alone under its own harness** there instead of being
swept by the next batch's `git add -A` under the Sleep author. The refusal is asked **under admission** (G183,
`write_admission`): a guarded writer asks it holding the bank's write admission and keeps the hold through its own
commit (an async writer's transaction runs on the writer loop, so neither a cancelled request nor its loop's teardown can drop it early); Sleep opens
a window (the run's start, a batch's Stage 2, the tail) by setting its flag and then waiting, off the loop, until no
holder is left — so a writer that saw the window shut commits before Sleep reads a page, and every later one refuses.
The wait is bounded: past 60 s Sleep reads nothing — the drain stops as a `busy` pause, a run's start reads nothing,
the tail is skipped. Order is admission → page → git; no admission spans a model call or a fetch. Not covered, and
disclosed in `storage.md`, "Write admission": `enrich-links`, `verify-sites`, the paper-details run and batch intake.
A claim written *inside* a window still stands uncommitted
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

**The engine's own runtime is never a page.** The `claude -p` CLI still tells the model its cwd, platform and shell despite `--system-prompt` (probed 2.1.x; `--exclude-dynamic-system-prompt-sections` is ignored with it), so the extraction prompt says that is not conversation content and Stage 2 drops, with a text-free debug line, any entity named for `$CICADA_HOME` or a path under it (`agent_engine.is_runtime_path`; the scratch dir is one).

**The owner is never a page of a pronoun (G169).** One closed, language-aware list of self-reference spellings
(`owner_identity.SELF_REFERENCE_FORMS`: "User", "the user", "I", "me", "myself", "the person", "the owner",
"owner", "el usuario", "la usuaria", "usuario", "usuaria", "yo", "mí"; compared NFC, case-, outer-quote-,
trailing-punctuation- and spacing-insensitive) feeds both the resolver and the prompts' wording
(`self_reference_list`), so neither can name a form the other misses. A spelling is the person only when it is a
**speaker reference** — one qualified decision, `owner_identity.SelfReferences`: the name is a person or carries
no type (an edge or claim endpoint, a wikilink) **and** no non-person page, no typed non-person pending line
(`pending_store` — a company heard once is still that company when a later batch names it only as an endpoint), and
no non-person entity in this batch holds that exact name. So a company "Owner", a concept "I", a tool "Me", a company "Yo" keep their own facts,
edges, claims and held claims, while an old duplicate *person* page named "User" reserves nothing. Every step that
keys a name builds it from the same inputs: Stage 2 merges a speaker-reference entity into the `owner: true` page
under its name and type (speaker-reference aliases dropped; several such payloads union their key facts, links,
questions and aliases; each input's one effective summary — `summary`, else the legacy `description` — competes,
the longer is the summary, and every other distinct one is kept once as a key fact) and resolves speaker
endpoints to it; Sleep's claims (`claim_pipeline.subject_resolver`) and holds (`hold_page_less`'s `reserved`) and
Stage 5.5's wikilink `mentions` (`materialize_wikilink_edges(memory_path, extracted, settings)` — the same
`settings` owner tie-break when a bank holds two owner pages: `[[User]]`, `[[the
user|…]]`, `[[mí]]` → the owner page, never an old duplicate; the prose is never rewritten) agree. With no owner
page a speaker reference is dropped — never a page, a pending line or a "Who is User?" question. A link to the
owner page, or to a speaker reference, is **not** the promotion rule's link to a high-confidence page (everything
the person mentions is linked to them). Stage 1's prompt gains an owner block (`entity_extractor.owner_block`) and
the synthesis prompt an owner line (`conflict_resolver._owner_line`) naming the owner page's `name`, read once per
extraction (`owner_identity.owner_name`), so prose says the name, never "the user"; a bank without an owner page
keeps both prompts byte-identical. An older bank's `user` page is not migrated: speaker references stop feeding it,
and folding it in is the dedup merge (`dedup_sweep` / `entity_merge`, loser `user`, winner the owner page) behind
the person's explicit call — not built. Disclosed: a "User" Stage 1 types as a concept is not a speaker reference
and becomes its own page.

**Known limitations (G169, deferred — backlog):**
- *A later collision re-binds earlier wikilinks.* Stage 5.5 re-reads every page's prose each cycle under that
  cycle's decision. A page written when `[[Yo]]` meant the person gets `→ owner`; when a later batch introduces a
  company "Yo", the unchanged page also gains `→ yo`, and both `mentions` edges persist (the non-claim edge merge is
  additive). The fix is to bind a speaker wikilink to the owner when the prose is written (keeping its label), or to
  remember the resolved identity per page revision — never to reinterpret unchanged prose with later type evidence.
- *Synthesis drops additive fields (pre-existing).* When an update carries a `description`, Stage 3's synthesis
  prompt (`conflict_resolver._synthesize_entity_update`) is given the description and history only, and its body
  replaces the page's on an agent-only page — so the unioned key facts, links and open questions of a merged
  payload (several self-references on the owner page included) do not reach the written page on that path. The
  deterministic and human-edited paths keep them. The fix is to send the whole merged payload to synthesis, or to
  merge the additive fields deterministically into its result.

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
