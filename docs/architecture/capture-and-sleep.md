# Capture and Sleep

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

### Awake — capture
Continuous episode capture. Raw timestamped chunks go to the `episodes/` inbox. **No LLM
processing at capture time** — just file I/O.

Sources are many and the pipeline is **source-agnostic**: MCP-native clients, hook-driven session
capture, chat exports, browsers (bookmarks and Safari tabs), Telegram, direct saved-content
connectors (Pinterest/Reddit/X), the platforms' own data exports, RSS, calendars, files. The per-channel detail lives in
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
- **Ask why at the moment of saving (G191).** A bookmark sync reports what it newly saved: each source's
  `first_sync` (no seen-set before this pass) and `fresh` / `fresh_total` — the bookmarks that got a `url_index` row
  this pass (at most `FRESH_CAP` = 3 listed), each with its episode and `added_at`, the browser's own instant (aware
  UTC, seconds; Chrome's `date_added`, Safari's Reading List `DateAdded`, `saved_at.instant_from_*`). The episode
  keeps `added_at` beside the day in `saved_at`, so the record says *when* a page that may since have changed was
  saved. A moved bookmark is a URL already held, so a reorganisation is never fresh. **A re-save is fresh (G191 v3,
  owner 2026-10-15):** a link the bank holds that this channel's file newly saved — absent from the channel's last
  seen-set and present now, or stamped by the browser later than the newest instant the last sync saw (the seen-set
  keeps `newest_added`) — is reported with `resave: true` and its own episode, by the sync and the early look alike
  (`bookmark_sync._resaved`); refused on a first sync or a changed folder scope, like the removal diff. A move or a
  rename keeps both the URL and the node's `date_added`, so it never is. A re-save of a removed bookmark makes its page
  active again and clears its episode's `source_deleted_at` (`_revive`, in the sync's own `cicada` commit, trigger
  `sync/bookmark_resave`). The app decides whether to ask
  (see `app.md`, *Ask why*); the answer is `POST /sources/saved-why` `{url, reasons[], project?, text?, at?}` (`at`: when the person answered,
  as the app recorded it — aware, not in the future, at most 24 h old, else 422 — so an answer the app held through a
  409 keeps its own time) → the link's
  episode through `episode_staging.revise_section`: one `## Why it was saved` section (rewritten, never twinned, placed
  above an agent's `## Note` so `speaker_kind` reads it as the person's), the words scrubbed (writer `saved-why`),
  `saved_why: {reasons, project, text, at, added_at?}` in the frontmatter — **every moment of saving keeps its own
  answer (G191 v3):** the newest is `saved_why`, the older ones `saved_why_earlier` (oldest first, at most 20 in all),
  the section lists them all, oldest first; an answer replaces another only when it is the same one again (the same
  `at`, the app's retry; or the same `addedAt`, the same save) or the person edits it (`PUT /sources/saved-why`,
  `edited_at`), `processed: false` so Sleep reads it again, committed
  alone as `user` (trigger `user/saved_why`) inside the write admission (409 while Sleep holds the pages, 409 in a demo
  bank, 404 for a link not saved, 422 for an empty or unknown answer). Reason ids are a closed, stable set —
  offered (G191 v4, owner 2026-10-15: "keep options to a minimal"): `design` "The design", `product` "The product",
  `read_later` "To read later", `someday` "Useful someday"; retired but still read and still accepted: `technique`
  ("A technique to reuse") — labels separate (`saved_why.LABELS`); `project` is a project page's id (a live one, or on
  an edit any — the panel no longer offers projects; Sleep may infer the link); `text` is the person's own words
  (≤ 500). `GET /sources/saved-why/options` serves the four reasons and an always-empty `projects` — deterministic, no
  model. `explore_plan` reads `someday` as the minimal capture, like `read_later` (the page as it looked when saved). The wire for a later
  reader is the source record: `GET /sources` → `items[].savedWhy` `{reasons, labels, project, text, at, addedAt,
  editedAt}`, read from the episode (null when nobody was asked), with `savedWhyHistory` (every answer, oldest first,
  when there are several) and `lastSavedAt` (the newest moment of saving the record knows). **Remove (G191 v3):**
  `POST /sources/bookmarks/remove` archives the media page and tombstones the episode (`bookmark_forget`), never an
  unlink; the person's answers stay. The browser's copy is the app's to remove (Chrome through Apple Events on the
  person's click; Safari cannot be edited by another app).
  **Left the browser (G191 v4, owner 2026-10-15: "I'd like to know that Cicada has the status, like it's not linked, or
  is no longer a bookmark saved in Chrome").** A link that drops out of a channel's file is kept — its page, episode and
  reasons untouched — and marked in the seen-set's `left` map `{url_hash: at}` with the sync instant that first saw it
  gone (`bookmark_seen.next_left`; only links the bank holds). A link present again leaves the map on the sync that sees
  it (and is a re-save, asked about). The map moves only by the removal diff, so its rails are the diff's: a channel's
  first read, a folder-scope change, an empty read (the previous set is kept, so a half-written file never makes every
  link look gone or new) and a wholesale swap (a read sharing no link with the last one that held ≥ 5) mark nothing and
  count as no re-save, each reason but the first recorded in `removals_skipped`. A move or rename keeps the URL in the
  file, so it never marks. **No inbox question:** until v4 the sync asked "Still keep …?" (`removal`, G129 slice 2) — it
  existed because the bookmark sync had no other way to say a link had left the browser and no way to remove one from
  Cicada; now the status says the first and the bookmark page's Remove does the second. A pending bookmark removal
  question is retired on the channel's next sync, its link marked from the day it was asked (`_retire_removal_questions`,
  trigger `sync/bookmark_left`); papers' `removal` questions are untouched.
- **Capture must not depend on a model deciding to call a tool** (G105). Every Claude Code and
  Codex session is captured by the harness's own `Stop` hook
  (`api/hooks/capture.py` → `POST /capture/transcript`). Cursor and Gemini CLI are captured by their own
  per-turn hooks, whose payloads carry the words (see *Capture from every agent* below); no Cursor or Gemini
  transcript is read: both hooks send a `transcript_path`, but neither documents its format, a confined root or where
the final reply sits, and Cursor's may be null, while the posted strings already are what is kept.
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
- **A captured session's title is the person's own words, never a wrapper tag** (2026-10-14, `episode_title`). The
  first person message can open with a wrapper — `<pasted_content id="…">` around a paste, or a harness block that
  arrived inside the person's text (G110 gate C) — and the old first-line rule (G105 R12) titled the session by the
  bare tag. The title is now the first real line outside every wrapper, else the first inside one (a message that is
  only a paste); text inside a harness tag (`CLAUDE_HARNESS_TAGS`/`CODEX_HARNESS_TAGS`) never counts; a tag opens a
  wrapper only at a line's start, so `Vec<String>` mid-sentence is words. A turn with no real line (only a command tag)
  passes to the next person turn, then `<Product> session`. Title only: the body is kept as captured. Episodes titled
  before the fix are retitled once from their own stored body — the transcript is never re-read — by
  `api/scripts/retitle_wrapped_episodes.py` (the dry run prints counts; `--apply` is refused while Sleep runs, makes one
  `cicada` commit and re-queues nothing — the title is outside `content_hash`; a run that fails before its commit puts
  back every file and index entry it changed). The scan is linear: it runs in the Stop hook.
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
- **Messages conversations the person ticks (G179, 2026-10-15).** The app lists `chat.db`'s 200 most recent one-to-one
  chats for the Settings picker (names, last activity, per-side counts — `MessagesReader.conversations`; group chats are
  out of this slice; a ticked chat below that cap is appended so it can be unticked). Every pass reads the ticked
  conversations by their own id (`conversations(ids:)`, the chats' guids hashed in the app), never through that list, so
  a ticked chat syncs whatever its rank. It reads only a ticked conversation's rows (`message` id, guid, time,
  direction, `text`, `attributedBody` as base64, the reaction/event/edit/unsend columns and its attachments' names and
  types — never `attachment.filename`, a path, never the handle), past a `message.ROWID` cursor per memory, 500 at a
  time, plus every already-posted row whose edit or unsend time differs from the one the cursor recorded for it. The
  cursor keeps that time per row for rows edited or unsent within the last 30 days (by edit time) and each pass
  re-checks exactly that window (ids and times only), so an edit that reaches the Mac late, carrying an earlier edit
  time than one already seen, is still read; a single newest-edit watermark would hide it. An edit arriving more than 30
  days after it was made is not seen. Re-synced on FSEvents in `~/Library/Messages` (10 s debounce, 60 s floor). A
  conversation's id is a hash of `chat.guid`. `POST /sources/messages/sync` refuses (409) a conversation not ticked in
  `sources/messages.json` (`messages_source.load_settings`: tick, the person's mark and its history); `POST
  /sources/messages/conversations` only computes the Settings list (tick, mark, detector suggestion) and stores nothing.
  The backend decodes `attributedBody` (`typedstream`: the header, the string object's class, then its `+` bytes —
  `NSUnarchiver` stays out of the app), skips tapbacks (a tapback row quotes the OTHER side's words under the reactor)
  and events, names attachments (`[image: plan.png]`), folds a message's line breaks so it is one turn line, and stages
  one episode per **sitting** (messages more than 3 h apart start a new one; the measurement and the reasons are G179's)
  keyed `imessage:<conversation>:<first message key>`. A pass merges into the stored sittings it touches, rebuilt from
  each episode's own body, `turns` sidecar and `message_keys`: an edit rewrites in place and re-queues, an unsent
  message leaves (an emptied sitting is tombstoned), a bridging late message merges two sittings into the earlier one,
  which keeps its key and id. **Who is who:** the person's lines are `user:`; the other side's are `assistant:` when the
  conversation is with an AI agent — the person's mark, or an `identified` detection (`agent_detectors`, G188) — else
  `speaker:<label>:`; the frontmatter `correspondent: {name, kind, decided_by, detector?, detection?, signal?}` names
  it, with `conversation`, `service`, `message_count`, `from_person`, `sitting_first_at`/`sitting_last_at` and
  `message_keys`. The person's mark changes re-render every saved sitting in place from the stored episodes (`PUT
  /sources/messages/settings`, one `user` commit with the settings file). One `user` commit per sync
  (`capture/messages`); scrub writer `imessage`; demo bank 409. `GET /sources/messages/waiting` sums `message_count`
  over unread, live sittings per conversation — the Sleep page's and Home's bubbles. Through Sleep, the decided
  `correspondent` is its own page — a `tool` for an agent, a `person` for a person — never a same-name page of
  another type (*Entity promotion*, "A message conversation's correspondent").
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

**Platform data exports (G71, 2026-10-09).** What the person saved, liked or favourited on a platform comes in
through that platform's own "download your data" archive, read locally — no hosted social API, so nothing passes
through a third party. One reader, `api/services/saved_exports.py`, serves every door: the app's drop (a `.zip`, or a
folder it walks file by file), `POST /sources/upload` (bytes only; the backend never opens a path) and
`cicada import <path>` (the CLI reads the path in the person's shell and runs the same reader in-process — so the
import needs no Mac app).
- **A walked folder obeys the zip's allow-list.** The app sends a walked file named by its path inside the dropped
  folder (`twitter-archive/data/like.js`), and the backend reads a filename with a folder part only when
  `is_save_list` says so, through `parse_member` — the zip's own reader (`saved_exports.is_member_name`). The app's
  walk is narrower than a single drop too (`IntakeRouter.isWalkedExportFile`): `.json`/`.zip` (the chat side reads
  them by content), Gemini's `MyActivity.html` and ChatGPT's `chat.html`, and otherwise only save lists — so LinkedIn's
  `Connections.csv`, X's `Your archive.html` or a message page never leaves the Mac. A `Connections.csv` dropped by
  itself is refused by name.
- **What is read.** A member is opened only when its NAME is a known save list; everything else in the archive
  (messages, contacts, posts, search history) is counted and skipped unread, media is never opened, a member over
  64 MB is skipped with a warning, and the generic URL-list parsers a single dropped file may fall back to are never
  used inside an archive. Watch and browsing history are not saves (G69): read only with `include_history` — through
  every door, a single dropped `watch-history.json` included — and otherwise left out with one warning
  (`history_warning`) that names no switch, because the app's drop has none (the CLI's `--include-history` and the
  API's `?include_history=true` ask for it).

  | Platform | Files read | Kept |
  |---|---|---|
  | Instagram | `saved_posts.json`, `saved_collections.json`, `liked_posts.json` | link, account as title, save date, collection name (likes: folder `Liked posts`) |
  | TikTok | `user_data*.json` (any section wrapper) or the TXT lists (`Like List.txt`, `Favorite Videos.txt`) | link, date, `Likes`/`Favorites` |
  | YouTube (Takeout) | `playlists/*-videos.csv` (current and older layouts); `watch-history.json` only on request | video, playlist name, added date |
  | X archive | `data/like.js` (`bookmark.js` if an archive carries one) | the connector's own post URL, the post's text as title and stand-in description (scrubbed, never the person's note), no date (the archive has none), never fetched at import |
  | Reddit | `saved_posts.csv`, `saved_comments.csv` | permalink (no title or date in the export) |
  | LinkedIn | a `Saved Items` CSV | link, saved date |
- **Identity and dedup.** One saved thing is one `url_index` row keyed by its normalized URL — the identity bookmarks,
  connectors, uploads and single saves already share — so an export never forks a link saved another way, and the
  shared stager (`episode_staging`) is not used: its `source_id` would be a second identity for the same link.
  `RawItem.aliases` names other URLs of the same thing, indexed as `alias_of` rows (the papers shape every reader
  skips): the Reddit connector records a link post's permalink, so the export (permalinks only) and the connector
  (outbound links) dedupe in either order; a duplicate found under a new URL adds that URL as an alias. Within one
  archive a post found twice keeps the person's collection name over the platform default. A re-import writes nothing.
- **Size.** An upload takes up to `MAX_UPLOAD_ITEMS` (50,000) and imports `MAX_BATCH` (2,000) at a time
  (`ingest_chunked`), each slice committed alone; the preview warns past the cap, as Confirm refuses it. A slice is
  not atomic: interrupted, it can leave pages written before its `url_index` rows, which a re-import writes again.
- **Rails.** No model runs; the episode body is scrubbed as every media save is, and the X reader scrubs the post's
  words before they become a title; every `/sources/` POST answers 409 into a demo bank and `cicada import` exits 4.
  Pinterest's export is a browse-your-content HTML archive with no stable structure, so Pinterest stays with its
  connector.

**Conversation identity (G48).** An MCP episode carries `session_id` plus `harness` and
`project_dir` when exposed — minted once per MCP process from `CLAUDE_CODE_SESSION_ID` →
`CICADA_SESSION_ID` → a `ses_*` fallback that groups but never resumes. Entities credit to
conversations transitively via `source_episodes`. A conversation row's `model` stays null. The
model lives per turn instead (round 4, G49's reservation lifted for harness writes, TODO ruling 11):

- the Stop-hook episode's `turns` sidecar records each agent turn's `model`/`effort`;
- a claim written through the MCP seam carries `recorded_ts`;
- `turn_authorship.py` joins the two at read (`authorModel`/`authorEffort`), never guessed and
  never self-reported.

An app with no capture hook (the Claude app, ChatGPT, a remote connector) has no turn to
join, and neither does a Codex MCP write, because Codex gives an MCP server no session id; nor yet does a Cursor
or Gemini CLI MCP write, whose captured episode exists but whose MCP session is not tied to it. The app
then says the model wasn't shared.

#### Capture from every agent (capture-everywhere, 2026-10-14)

Owner, 2026-10-14: "The idea is for this to be an all-rounded capture and use of all providers." Every agent is
captured by its own documented hook, never by a model choosing to call a tool (G105), keeping only the person's
turns and the agent's final reply. Where a hook carries the words themselves, the hook posts those strings and
the backend opens nothing; where it carries only a transcript path, the backend reads the transcript under the
harness root (above). Docs checked 2026-10-14; "unverified" means built from the documented payload with synthetic
fixtures, not yet run against the installed app.

| Agent | Documented hook or export | What it carries | What Cicada captures |
|---|---|---|---|
| Claude Code | `Stop` (+ `PreCompact`/`SessionEnd` flush) | `session_id`, `transcript_path` (JSONL) | Every session (G105), verified |
| Codex | `Stop` in `~/.codex/hooks.json` | `session_id`, `transcript_path` (JSONL) | Every session (G105); payload R9-unverified |
| Cursor | `beforeSubmitPrompt`, `afterAgentResponse` in `~/.cursor/hooks.json` | `prompt`; `text` (final reply); `conversation_id`, `generation_id`, `model`; `transcript_path` nullable, format undocumented | Every local chat, per turn (`turn_capture`); unverified |
| Gemini CLI | `AfterAgent` in `~/.gemini/settings.json` | `prompt`, `prompt_response`, `stop_hook_active`, `session_id`; `transcript_path` format undocumented | Every session, per exchange (`turn_capture`); unverified |
| Claude app (desktop) | none; MCP only | — | Only what it saves through MCP; its chats arrive by the claude.ai data export import (G197) |
| Claude on the web, ChatGPT, Grok | none; remote connector (G135) | — | Only what they save when asked; exports through the importers |
| Windsurf (Cascade) | `pre_user_prompt`, `post_cascade_response` in `~/.codeium/windsurf/hooks.json` | `user_prompt`; `response`; `trajectory_id`, `execution_id` | Not yet: the same shape as Cursor, so it is a registry and an adapter on `/capture/turn` (G197) |
| GitHub Copilot CLI | `userPromptSubmitted`, `agentStop` in `~/.copilot/hooks/` | `prompt`; the reply only inside `transcriptPath`, format undocumented | Not yet: the reply needs a transcript reader (G197) |
| OpenCode | JS/TS plugins only (`~/.config/opencode/plugins/`) | events (`message.updated`, `session.idle`) with undocumented payloads | Not yet: needs a plugin, not a command hook (G197) |
| Hermes, OpenClaw | no hooks documented | — | MCP saves only |

**Per-turn capture (`api/services/turn_capture.py`, `POST /capture/turn`).** The hook posts `{harness, session_id,
messages: [{speaker, text}], turn_id?, retry?, model?, cwd?, hook_event}` — one turn (Cursor) or one exchange (Gemini
CLI), each text trimmed by the hook to 256k characters, never `transcript_path`, attachments, an email or a thought.
The writer is the Stop hook's (`transcript_capture.write_session`): one episode per session (G104), the same body,
`content_hash`, `turns` sidecar, G110 metadata and `capture_kind: transcript`, so continuity, titles and the Reader
read it unchanged. A posted turn is cleaned like a transcript turn (`transcript_extract.clean_turn`: code fences
stripped, `episode_scrub`, 16k for the first person message, 2k head or head+gap+tail for the rest). **The episode
is the state:** `hook_turns` (outside the hash, before `turns`) records each kept turn's offset, speaker, hook turn
id, time, model and reply gap, so the next firing splits the body back into turns; a body that does not re-render
byte for byte from it — or whose index was hand-poisoned (a missing key, a non-integer or infinite offset) — is
refused unwritten (`state_mismatch`), never a 500. Cursor turns are keyed by `generation_id`: a re-fire
with the same text is `unchanged`, a later reply for the same run replaces the earlier one (only the final reply is
kept), and a reply lands after its own prompt even when a follow-up was queued. Gemini CLI exchanges carry no id:
the same exchange again is `unchanged`, a `stop_hook_active` retry of the last prompt replaces its reply, and
anything else appends. The session cap is gate B2's (`transcript_extract.window`): once the middle is dropped it
cannot be re-read, so the head stays fixed and the tail sheds its oldest turns a block at a time into the counted
gap. The demo rule is the Stop hook's: the turn goes to the real bank left most recently, or `409`. A turn's time
is the backend's arrival time (Cursor's payload has none).

**Cursor's hook** (`api/hooks/cursor.py`, one command): `sessionStart` is startup context (`mcp.md`);
every output carries `{"continue": true}` — even for a payload it cannot read (oversized prompt-first JSON, bad
UTF-8), so a prompt is never held back by Cicada — and `beforeSubmitPrompt` posts with a 1.2 s bound (it holds the
person's message); `afterAgentResponse` posts with 3 s. `CICADA_CAPTURE=off`, a remote session (`CURSOR_CODE_REMOTE`) and
a payload over 1 MiB post nothing. `cursor_registry --hook startup|capture` makes them two switches in
`~/.cursor/hooks.json`, every other tool's entries kept; `/agents/wiring` reports capture as Cursor's `autosave`,
with its install in `connect` and its removal in `autosave_off`. **Gemini CLI** runs the capture script as
`capture.py --harness gemini-cli` under `AfterAgent` (registered by the setup prompt the person's own agent runs;
`registry.py` writes its timeout in milliseconds), prints `{}` and posts the exchange. Both log one line per
firing to `capture.log` in the Stop hook's shape (`<harness> <sid8> <event> <outcome>`), never content: a
validation error's echoed `detail` is logged as `invalid request`.

### Sleep — 5-stage nightly batch
1. **Entity & relationship extraction** — LLM over episode chunks, structured output.
2. **Entity resolution & dedup** — exact name, fuzzy match, embedding similarity, LLM disambiguation
   (bounded concurrency, decisions in order; a recorded alias brings its page to the judge; see below).
3. **Conflict resolution & pruning** — contradictions detected, recency wins, old state archived;
   temporal decay applied (pages' calls overlap, results applied in order; see below).
4. **Pattern detection & skill extraction** — recurring patterns distilled into skill entities, each written only
   with the conversations it came from (see *A skill page carries its conversations*).
5. **Nudge generation, clarification queue & versioning** — snapshot, git commit.

**Claim preservation (G148 regression):** Stage 5 rewrites prose with the stored `claims` fences removed from section parsing, then reattaches those fences unchanged. Rebuilding `Related` cannot remove beliefs before the claim pipeline reconciles them; synthesis output never authors a claims fence.

**`Related` reads the edges once:** `apply_changes` builds each entity's edges from `graph_edges.yaml` on the first update that needs them and reuses them for every page that pass merges (nothing in the pass writes the file); every reader of that file uses `markdown_parser.load_yaml`, the libyaml safe loader. The file grows with the claims; on a 2,000-page synthetic bank one pure-Python read cost ~3.8 s and was paid once per merged entity (`benchmarks/scale`).

**The claim write-back renders only changed pages:** `run_claim_pipeline` keeps each page's claims as read (by value — the reconciler edits claims in place) and skips the parse/render/write of every page whose reconciled claims equal them and that gains no episode credit; such a page still counts as written. On a 2,000-page synthetic bank ~1,940 of 2,006 renders per batch were byte-identical (8 s).

**The question refresh reads only what it asks about:** Stage 5.56's `refresh_open_questions` (and its idle-cycle twin) gets `claim_pipeline.claims_on_demand`, which parses a subject's page the first time an open conflict question names it, instead of every page's claims (a full-bank pass a batch).

**Item provenance (G118 sections, 1a-i).** After extraction, Summary/description and
Key Facts receive transient source-episode `reasoning` records over the full stored body
hash. This adds no prompt instructions, quotes, retries or calls. Stage 2 carries metadata
with the fields it actually selects, from every same-name extraction in the batch (see *Entity promotion*). After G169, it follows the chosen effective Summary,
its description copy, the fact union, and orientation text retained as facts; only exact
selected text receives the original source record. Carry unions unique evidence rows per
selected field/text, so repeated mentions cannot multiply identical records when Summary
and description share the same words. The pending-store limitation remains; earlier pending
facts are not restored by provenance. Stage 5 records exact surviving items
on create and fallback/human-safe updates. The B-update fixture keeps A's usable Summary
and its exact guard; a distinct incoming orientation becomes a Key Fact (its exact text keeps B's row) when the page
does not already say it (see *Page quality*). A's facts keep their links.

**Summary growth (G194; reworked by *Page quality*, 2026-10-09).** Deterministic create/update/dedup merges use one
600-Unicode-character, single-paragraph budget (`summary_policy`). An existing usable orientation stays exact. A machine
Summary keeps its leading whole sentences that fit the budget, once each, and never a second (re-)introduction of the
thing ("X is a CI platform. … X is a CI/CD automation platform." keeps the first: `entity_body.lead`); this also
de-glues an existing Summary on the page's next update. Whatever an orientation loses — a distinct incoming one beside
a usable Summary, the sentences a lead leaves out, a replaced one — goes through `entity_body.retain_orientation`: a
sentence equal to a Summary sentence or a Key Fact (`fact_policy`: the same text up to case, accents, whitespace,
wikilink brackets and trailing punctuation) is dropped; every other sentence becomes a Key Fact. Nothing goes to History any more: the "Undated
background:" bullets this replaced repeated Key Facts word for word (667 on the owner's clean run). Incoming facts the
Summary already holds as the same text are suppressed; existing facts/human prose are never removed. Exact input evidence follows the
surviving Summary or fact via `section_provenance.merge_selected` (a one-sentence orientation that becomes a fact
keeps its row; a split one is unrecorded, never recertified). Multiline carried facts receive stable continuation
indentation. When no sentence fits (an empty or single over-budget one), the Summary is a usable previous one or the
identity line "X is a tool." — it no longer adds "Its present role for the owner is not established.", which read as a
claim against the page's own facts. Human Summary is exempt and never extended or rewritten; incoming context is
added outside it, as Key Facts. Human flags and custom sections are honored by both entity merge and source rewrite.
This is a structural floor, not semantic synthesis: a restatement in other words ("CI platform" / "continuous
integration service") is only caught by the opt-in synthesis below.

**Opt-in orientation synthesis (G194).** `CICADA_SUMMARY_SYNTHESIS_ENABLED` defaults to false.
Off preserves the legacy description/history gate and its call count. On uses effective Summary
(then description) and all incoming structured fields, skips human/custom pages before a call,
and requests one bounded JSON Summary plus two lists (prompt version 2, page quality 2026-10-09): `restated`, the
incoming facts that say nothing beyond the new Summary or an existing Key Fact, and `covered`, the sentences of the
replaced and the incoming orientation (`orientation_sentences`, sent with the call) that do. Code leaves out only an
item the model listed AND that shares two words, beyond the thing's own name, with one sentence of the new or old
Summary or one Key Fact while adding no number, tense or status word or negation that item lacks
(`entity_orientation._confirmed`, `fact_policy.compatible`); nothing already on the page is ever removed this way. This is the one
place a restatement in other words is folded, at no extra call. Facts-only updates need one merge call; Summary/description
updates also run the existing contradiction check. `entity_orientation` passes dated inputs and
only structurally current claims (`claims.is_current`, excluding withdrawal records). Prose is
labeled unverified background; old statements and intentions must name their own date, never a
page-wide last-reference date. Input over 24,000 characters and invalid output take the deterministic
fallback without a retry. Engine failures/cancellation retain the existing propagation contract.
Composition changes only Summary and deterministically unions the complete non-Summary sections,
even ones the model did not rewrite. A replaced orientation's sentences become Key Facts unless `covered`. Exact carried
facts retain or acquire exact G118 guards; a rephrased orientation remains unrecorded. The inbox
caller shares this builder and retains its existing pre-call snapshot/write-time fence. The switch
requires owner review of benchmark call counts; fake timing does not estimate provider latency.

**Off: the legacy rewrite keeps every item (page quality, 2026-10-09).** With synthesis off, a page update that carries
a `description` or history still makes the legacy whole-body call. Its prompt now describes the v2 sections (one
600-character Summary that introduces the thing once; Key Facts kept as written, a new one only when no bullet says
it). What it returns is used only for the Summary and the History lines it adds that no line already says
(`entity_body.adopt_rewrite`); every other item is the page's own, then the extraction's key facts, links and open
questions are merged deterministically. Before, its body replaced the page's: the extraction's facts never reached
the page on that path (the prompt is given only the description and history — 12 of 50 extracted facts lost in the
offline eval) and a fact the rewrite left out or rephrased was dropped or doubled. Every exact item now keeps its
source row on this path too. The cost: the rewrite can no longer delete a Key Fact it judged superseded; the dated
History line it adds and the contradiction check's question to the person are how a superseded fact is resolved.

**A re-read is not a new mention (page quality, 2026-10-09).** Stage 3 makes no synthesis or contradiction call for
an update whose conversations the page already credits (a resumed conversation read again, G104) when every sentence
of its summary and every one of its facts is equal to a Summary sentence or Key Fact already on the page
(`entity_body.adds_anything`, the same normalization as the fold): its items merge deterministically. A re-read that
brings anything else still gets both calls, so a change stated in the resumed part is still checked. Either setting.

**Person-started prose repair, candidates only (G194 B).**
`scripts/repair_entity_prose.py --bank <bank> --scratch <outside-bank-directory>` inventories
up to 20 pages without model calls. Repeat `--entity-id` to select a stratified pilot;
otherwise pages are sorted by id. `--generate` additionally requires explicit `--engine`,
`--model`, `--max-calls` and `--token-budget`; it never selects a fallback engine. Each invocation
reserves UTF-8 input bytes + 1,024 envelope tokens + requested output tokens, reports reservations
(not measured charges), and caps calls. Output-token limits are passed to the provider; the
engine-independent hard limit is calls. Resume caps apply per invocation; review total spend
across invocations in the preserved `run-<id>.json` manifests. Each call reservation is checkpointed
before generation. Configuration/bootstrap lives in scratch, with `.env` disabled.
The tool rejects overlapping paths and symlinks, reads a clean existing bank, and writes only
0700 scratch directories / 0600 candidate JSON and a manifest. It never scaffolds, indexes,
commits or applies a bank change. `source_rewrite.generate_prose_candidates` shares the same
orientation builder; the older automatic source-rewrite writer remains a separate entry point.

Human/custom/unreadable/corrupt pages, missing linked episodes and context over 24,000 characters
are deferred before calls. All known page/claim source episodes are dated separately and read in
full; no oldest-first clipping silently excludes recent evidence. The tool cannot recover source
credit already lost by earlier writers. Candidate edits may only prefix a unique existing fact
or history item with an absolute date from a named source containing the exact original wording.
Other wording and all raw claim fences survive. Changed prose loses its exact G118 guard;
unknown metadata is preserved without certification. Page/source hashes are checked again after
generation, and dirty/changed inputs are deferred. Cached output requires matching input, engine,
prompt-version and candidate hashes. Invalid output uses no retry; engine failure checkpoints
earlier candidates and stops. Only manifest entries marked `candidate` or `cached` are eligible
for review; older scratch files may be stale. There is no apply API/flag. The owner-bank pilot,
semantic grounding/readability review and any checked apply are orchestrator work after the drain.

Legacy Sleep synthesis retains exact old items by identity, without changing its prompt/return shape.
Rephrased items become unrecorded; incoming facts not supplied to synthesis cannot gain links.
All refreshes share the existing atomic page write, locks and commit/rollback boundary.
Any open code fence can hide sections from the original or final body: refresh preserves
their stored records and guards, reporting unavailable metadata until the body is readable.
Closed claim fences exclude their machine text even if the claims payload (JSON Lines, or legacy YAML) is malformed or repeated.
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
  A memory export entry gets `source_dates.summary_note` instead: its date is when the summary was edited, never a
  day to date a fact to, and nothing in it is written as current or recent (the 90-day rule does not apply).
  A message conversation (G179) also gets `entity_extractor.correspondent_note`, after the date note: whose lines are
  the person's (`user:`) and whose are the other side's — an AI agent's `assistant:` lines named by the contact
  ("Instinct"), or a person's `speaker:` lines — and that "I" in their lines is them. After the evidence locate, the
  model's own `observer` on a relationship is dropped, and a relationship whose located spans are all the other side's
  gets observer `external:<name>` (`correspondent_observer`); one the person's words also back stays `agent`
  (`entities_to_claims` resets it when chunks disagree). Never `user_stated` either way.
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
files and commits it** (**off the event loop**, 2026-10-08: Stage 2's page load, `inbox_generator.generate`'s page
writes, Stages 5.5–5.56, 5.6, 5.7 and the processed flags each run in `asyncio.to_thread`; on the loop they froze every
request — `GET /sleep/status` measured at ~4 s on a synthetic 3,600-page bank and ~11 s on the owner's — for as long as
they ran; `entity_resolver._name_tokens` is memoised for the same reason) (`Sleep cycle <date> (batch k of n)`, `sleep_run` refs gain `drain_id`/`batch`/`batches`, ids and
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
exchanges) in one, OR an explicit link to an existing high-confidence entity.

**The bar is measured, not guessed (page quality, 2026-10-09; `api/services/promotion.py`).** A clean run of 296
conversations wrote 70% of its 3,588 pages from one conversation (median 85 words, 3 facts): a function in the
assistant's code example, a ride the assistant listed, a credential helper it suggested. The rungs were proxies almost
every extraction cleared — "substantive" was confidence ≥ 0.75 with a 200-character description, or two history
entries, or two relationships in the conversation (the prompt defines confidence as certainty, asks for a 3-5 sentence
summary and for every relationship); "an explicit link" was any relationship the model drew to any page at 0.6. Now:
- **>3 exchanges** is counted by Stage 1 on the conversation itself (`promotion.exchanges` / `measure`, no model):
  an exchange opens at each turn of a person (the owner, or a `speaker:` in a meeting) and runs through the replies;
  a document with no turn markers is the person's own writing, one exchange per paragraph. The name or an alias (a
  person's first name too) must come up in more than 3 exchanges **and** in a person's own words at least once
  (`mention_exchanges`, `named_by_person` ride on the extraction; never written to a page).
- **An explicit link** is a relationship to an existing page at ≥ 0.6 (never the owner's) whose evidence is located in
  a person's own words (`promotion.person_said`: kind `user` or `speaker`) — not one only the model's answer made or
  one it inferred.
- **2+ conversations** counts the batch's and the pending line's conversations together, so a resumed conversation
  read again (G104) is not a second one.
Below the bar nothing is lost: the pending line now carries what was said — summary, key facts, links, open questions,
aliases, their G118 item records and every conversation that named it (`heard_in`) — and a re-park unions instead of
replacing. When a later conversation promotes the name, the line is folded into the create through the same seam a
same-name extraction uses, crediting each earlier conversation (its day too). The line leaves the store only after
Stage 5 has written that page (`promoted_pending`; a line holding claims still leaves through Stage 5.56's release):
a cancel before Stage 5 keeps it, and the next run promotes it again with everything it heard. A line written before this keeps its
old shape and promotes as before. The rail and its numbers are unchanged; only how they are measured. What Sleep hears about a
name before it has a page is not lost (G141 PJ-0b): Stage 5.56 holds those claims on the name's line in
`<bank>/pending_entities.jsonl` (`api/services/pending_store.py`: spans, not copies; at most 50 per name,
the rest counted) and releases them onto the page, first and through Stage 3, in the cycle whose Stage 5
gives the name one — a holding line leaves the store only then. A Stage-4 skill seen in one conversation waits in a
store of its own (see *A new skill page needs two conversations*).

**Every mention in a batch is credited (2026-10-08).** Several conversations in one batch can name an entity by the
same lower-cased name. Stage 2 judges and promotes the name once, on its strongest extraction (first on a confidence
tie). Every other extraction of that name is then folded into the resulting change, whether that is an update, an
in-cycle create or a create made by promotion. The fold goes through the same `_merge_entity_payload` /
`_append_change_source` seam the owner merge (G169) uses, so each conversation lands in `source_episodes`, its
timestamp and day reach `last_referenced` and the Stage 3 prompts, and its facts, links, questions, aliases, tags,
history, an unclaimed `website`/`decay_class` proposal and its G118 item records all survive. A name that stays
pending parks one line carrying the merged history and tags; the line keeps the strongest mention's episode. Before
this fix those extractions were dropped whole: a 25-conversation batch credited 1 episode. Claims and edges were never
affected, because they are projected from every extraction's relationships through `name_to_id`.

**A message conversation's correspondent is its own page, of its own type (G179, owner 2026-10-15/16).** Before this,
a texted agent was resolved by name like any mention, so an existing page with the same letters took it: on the
owner's bank an archived `concept` page about the ordinary word absorbed a 55-sitting agent conversation — its claims,
its source, an article rewritten about the agent — and kept the concept's type and fading state. Now
(`api/services/correspondents.py`, one rule for Stage 1, Stage 2 and the repair):
- **The signal** is the episode's own `correspondent` record with a decided kind (`agent` | `person` — the person's
  mark, or an `identified` detection; `unknown` decides nothing), applied only to an entity Stage 1 extracted from
  *that* episode whose name or one of its aliases folds (`agent_detectors.fold`) to exactly the record's name. Stage 1
  marks it (`correspondents.mark_extraction`, after stripping any mark or pin the model wrote) and gives it its type:
  an AI agent is a `tool` (software the person uses — not a person, not an idea), a texted person a `person`.
  A mention of the same letters in any other conversation never carries the mark and takes the general resolver,
  unchanged — so this cannot widen into homonym handling.
- **Stage 2** (`entity_resolver._resolve_correspondents`, before any other name is judged) takes a marked entity out of
  the by-name path. An existing page of the right type named so (else listing the alias; never the owner's page; a
  dropped one is updated and stays dropped) is updated. Otherwise the correspondent meets the promotion rule like any
  name, unchanged (2+ conversations — this batch's sittings plus the ones its held line heard —, more than 3 exchanges
  with the person's own words, or a link the person made to an existing page). Below it, it waits in the pending store
  under **its own key**: a line named by the id its page will get (`correspondents.free_id`: always `<id>-agent` /
  `<id>-person`, then `-2`…, never the plain same-name id nor another line's slug) and marked
  `correspondent: {name, kind}` (`PendingEntity.correspondent`; found again by that mark, `correspondents.held_line`,
  never by name). Its claims are held on that line by Stage 5.56 (`pending_store.hold` keys by the line's slug), so
  no same-name page and no same-name pending line ever receives them. Once the rule passes, the page is created under
  that id (trigger `sleep/correspondent`) with everything the line held folded in (`_fold_pending`) and its held
  claims released onto it — born like any create (`created`/`last_referenced` from its conversations' days,
  `decayed_through`, `learned_on`, the decay class of its type); decay math is untouched. Every relationship of a
  correspondent episode whose endpoint names them is pinned to that id (`source_page` / `target_page`): its claim
  lands there, held or written (`entities_to_claims` reads the pin before `name_to_id`); its edge is drawn only once
  the page exists (a pin to a held correspondent draws none, and never falls back to the name). `name_to_id` maps the
  name to the page only when the page exists or is created now and no other conversation in the batch extracted that
  name. Observers are unchanged (`external:<name>` is the correspondent's name, not a page id).
- **Not covered:** a mention of the agent by name in another conversation (a coding session that talks about it) still
  resolves by name — with two pages sharing a name, the general resolver's exact match takes whichever it indexed last.
  A type-aware tiebreak would be general homonym handling, a separate decision.
- **Repair for existing banks** (`api/scripts/repair_correspondent_pages.py` → `correspondent_repair`; dry run prints
  counts only, `--apply` one `cicada` commit, trigger `maintenance/correspondent-split`, refused while Sleep runs or
  holds the pages, a page dirty in git skipped, a second run a no-op). It finds a page named as a conversation's
  correspondent that credits one of its episodes while its type does not match, and splits it from the page's own
  git history: the *base* is the page in the parent of the first commit that credited the conversation. The old page
  goes back to the base (prose, status, confidence, `last_referenced`, `decayed_through`, its claims as the base had
  them) plus anything later from another conversation; the correspondent's page (an existing right-type page, merged
  human-safe, else a new one under `free_id`, born active at `RECOVERY_CONFIDENCE` with its conversations' days) gets the conversation's
  episodes, every claim added since the base that cites one of them (re-subjected, all provenance kept), the `sources:`
  rows, tags, aliases and `related` added since the base, the lead and Article when the absorption rewrote them (moved
  verbatim, so a machine article keeps its stamp and Sleep's writer keeps rewriting it — no model), and the list items
  the base did not have. Other pages' claims from the conversation that point at the old id are repointed; claim edges
  are regenerated (Stage 5.7's `regenerate_edges_from_claims`). A page with no version before the conversation, or a
  bank without git, is counted (`no_history`) and left alone; a wikilink by name in other prose is left as written.

**Stage 2's judge calls overlap, its decisions do not (2026-10-08).** After the name and fuzzy matches, Stage 2 asks
the disambiguation judge once per (name, same-type page sharing a name token), first `same` wins. Those calls used to
run one after another — on a ~1,900-page bank a 25-conversation batch made 500–830 of them at ~4 s each, 40–56 minutes
of a batch. The judgments against pages on disk depend only on the name and the bank, so `entity_resolver._Lookahead`
takes them ahead of the per-name loop: at most `sleep_resolve_concurrency` calls in flight
(`CICADA_SLEEP_RESOLVE_CONCURRENCY`, default 3; 1 is the serial loop), and on a plan engine still under the
process-wide `agent_max_concurrency` cap Stage 1 runs under; at most `LOOKAHEAD_NAMES_PER_SLOT` (4) names per slot
ahead of the loop. A name's own candidates stay sequential with the first-`same` exit, and everything that depends on
the loop — a direct match to an in-cycle create, an in-cycle create as a candidate — is still decided inline, in
order, so every decision and every call is the serial loop's. A cancel or a plan limit starts no new call and waits
out the ones in flight (a plan call is never interrupted); the engine error is still what `resolve` raises, so the
drain pauses as before.

**Stage 3's calls overlap, its results do not (2026-10-09).** Stage 3 asks the engine once or twice per page a batch
updates — the synthesis, then (with a summary) the contradiction check — and those calls ran one page after another:
~250 calls a 12-batch run with summary synthesis off, and roughly 750–1,250 more with it on (`summary_synthesis_enabled`,
~2 calls per summary update, 1 per facts-only one), minutes per batch. A page's calls depend only on its own change and
the pages as read before the stage, never on another page's answer, so `conflict_resolver.resolve_and_prune` first
decides in order, with no call, which pages are asked and with what (`_page_job`: a missing page, a hand-edited page
under synthesis, an update with nothing to merge and a re-read are settled there), then runs those pages' calls with at
most `agent_max_concurrency` pages in flight (`CICADA_AGENT_MAX_CONCURRENCY`, default 3; 1 is the serial loop; a plan
engine is held to the same number process-wide by the provider permit; no Stage 3 knob of its own), pages started in
order (`_overlap_pages`). A page's own two calls stay in order. Once every answer is in, the results — the synthesized
body, the contradiction's `conflict_nudge` — are applied in the pages' order, so `changes`, every page Stage 5 writes
and every inbox item (a second conflict on a page merging into the first's item included) are byte-for-byte the serial
run's (`test_conflict_resolver_concurrency`: randomized per-call latency, concurrency 1 vs 2/3/5/10, both synthesis
settings). Stage 3 still writes nothing and holds no write admission; Stage 5 writes, as before. A cancel is polled
before each page starts: no new page starts and the pages in flight finish. An engine error starts no new page, waits
out the ones in flight (a plan call runs in a worker thread and is never interrupted) and re-raises the error of the
earliest page that failed — the one the serial loop would have met — as the same exception object, so the drain's
plan-limit pause and its error classification are unchanged. Measured on a fake engine through a threading permit
(25 updates, 20 with a summary: 45 calls, 8–12 s per synthesis call and 2.5–3.5 s per contradiction call):
304 s serial (concurrency 1, as before), 110 s at 3 (the default), 38 s at 10 — the measured run's setting, ~4.4 minutes
saved per batch.

**An alias brings its page to the judge, never a decision (2026-10-08).** The judge's candidates used to be only the
same-type pages sharing a content word with the name, and Stage 2 never read a page's `aliases`, so a short form or
acronym the bank had already recorded for a page (no shared word) never met it and became a duplicate page or pending
line. Now a same-type page that lists the name among its `aliases` (`entity_resolver._alias_index`) is a candidate
whether or not a word is shared, and is judged **first**, ahead of the token-sharing pages. It is not settled on the
alias: a first name recorded on one person page, or letters a different thing also uses, is exactly the case the
owner ruled out, so no page, a person page least of all, is merged on the alias alone. Instead that call carries the context
Cicada already has: a note that the page records this name and that an alias is a lead, not proof
(`_ALIAS_NOTE`); the page's other names, then its summary, key facts and `## Related` ahead of its history, so the
2,000-character cut keeps them (`_alias_page_context`); and what the name was connected to in the batch — its
relationships and the names mentioned in the same conversations, speaker references left out (`_batch_connections`).
`same` merges and folds every same-name extraction (every conversation credited); `unsure` files the usual "Possible
duplicate of …" inbox item for the person; `different` moves on to the token-sharing pages, then to a page of its own
or a pending line, as before. An alias two pages share puts both in front of the judge. The context is built before
the loop from the batch and the bank, so the lookahead still decides exactly as the serial loop. Calls: one per
same-type alias holder judged (first `same` stops); a name with no shared word went from 0 calls and a duplicate to
usually 1 call; one that shares a word and names its alias holder usually costs fewer calls than before, because the
holder is judged first. A judge call with no alias candidate gets the prompt it always got, byte for byte. Link recon
(`match_existing`) does not read aliases.

**A reference is not recorded as a new alias (2026-10-08, narrowed in fix round 1).** An alias is another NAME for the
thing; a phrase that only points at it inside one conversation ("the lock", "this project", "la base") is not.
`alias_policy.is_reference` is deliberately narrow: two or more words, all lowercase, no digit, the first an article or
demonstrative (English or Spanish). Titles and names keep a capital at least at the start ("La casa de papel", "The
Economist"), a number makes a name ("The 100", "El 47"), and a possessive ("my mom", "mi mamá") is how the person
refers to one thing consistently, so none of those is a reference. It is used in ONE place: `apply_changes` drops
references from the aliases Sleep adds (a create's, and only the new ones of an update); what a page already lists —
a person's merge records the losing page's name there — stays, and the #249 alias index reads every alias as before. A
real name typed all lowercase and article-led is the accepted false positive: it is only not recorded as a new alias,
and a lowercase spelling of a page's own name already matches by name. The extraction prompt no longer shows `"the db"`
as an example alias and says a part, product, dataset, format or version of a thing is not its alias. An alias that is
another page's name is not removed by anything automatic: it may be the lead for a merge. For an existing bank,
`python -m api.scripts.repair_skills_aliases --bank <path>` (dry run; `--list` shows what would go; `--apply` for one
`cicada` commit) removes a reference only when the page's git history PROVES Sleep wrote it: the commit that last added it is a Sleep
cycle commit carrying Sleep's own `<page>: create (source: …` line. A Sleep commit runs `git add -A`, so an update
line, or a page it merely swept up, cannot rule out the person's uncommitted hand edit in the same cycle: those are
kept and counted as `alias_references_unproven` (`--list` shows them for the person to remove by hand). Anything any
other writer added — a person's merge included — is counted and kept.

**A skill page carries its conversations (G112 (1), 2026-10-08).** Stage 4 answers `{name, description,
evidence_entities, confidence}`; the old writer kept only the name and description, so every skill page was born
with `source_episodes: []`, `created` = the cycle's day, no section provenance and no `related`, was written only
when absent (a pattern found again never moved its page), and decayed with zero mention weeks. Now
`skill_grounding.ground` matches each evidence name, without a model, to this batch's conversations (Stage 1's names,
Stage 2's `name_to_id`, the changes' own sources), keeps those where two of the named entities came up together (every conversation of the one, when only one of them
came up in the batch), and hands `apply_changes` an ordinary `create`/`update` change: dates from those
conversations, the Summary's section provenance citing each as `reasoning` (an inference, never a quotation), a
`draws on` edge to each evidence page, and its own commit line with `source:`, `sessions:` and `trigger: sleep/skills`.
A skill with no evidence in the batch is not written (logged as a count) — it fails the detection prompt's own
contract, and a later batch that shows it writes it. A name that is already a `skill` page updates that page (sources
merged, last mention moved, a decaying page recovered, and Stage 3's decay of it this batch dropped; its prose is not
touched, so re-detections do not pile undated History bullets); a page of another
type, an installed agent skill's page, a dropped page, or a page another change of the batch writes is left alone.
`skills_detected` counts the grounded skills. No contradiction check runs on a skill update (owner ruling
2026-10-09: no extra model call).
The same repair script grounds the existing unsourced skill pages from the Sleep commit that created each one.

**A new skill page needs two conversations (owner ruling 2026-10-09).** The bar is entity promotion's. A skill
`ground` finds in only one conversation is not written and not lost: `skill_grounding.settle` (Stage 5, after the
pages are written) parks it in its own store, `<bank>/pending_skills.jsonl` (`api/services/skill_hold.py`, keyed by
the page id the skill would get), with that conversation, its description, confidence and evidence pages. A later
batch that grounds the same skill on another conversation clears the bar: the page is created citing both
(dates, `reasoning` rows, `source_episodes`, the held batch's `draws on` edges joined) and the line leaves the store.
If a `skill` page of that id appeared meanwhile, the held conversation joins its update the same way. A held
conversation whose episode is gone is no evidence. Nothing expires a line, so batch 3 and batch 9 meet. A skill page
that already exists is updated on one conversation as before. **Not Stage 2's pending store** (review of the first
attempt): that store is keyed by name, and Stage 2 promotes any line a Stage-1 entity repeats under the entity's
type, crediting only the new conversation and deleting the line — a held skill there became a concept page and lost
its first conversation, and a skill create taking a same-named Stage-1 line dropped that line's history, description
and tags. Two key spaces cannot consume each other's lines. The cost: a Stage-1 mention of the same name does not count
toward a skill's bar (a name heard is not the pattern seen), and claims about a held skill's name are not held with
it, as before. The file is tracked and committed by the cycle, like the pending store.

**Unsourced skill pages are archived on request (owner ruling 2026-10-09).** `repair_skills_aliases
--archive-unsourced` (off by default; the dry run counts `skill_archivable` / `skill_archive_unproven`, `--list`
names them) sets `status: archived` — never a delete, no inbox item, and decay skips archived pages so no decay
nudge follows — on a skill page that stays without a conversation after grounding, only when git proves the old
Stage-4 writer made it and nothing but Sleep's decay touched it since: added by a Sleep cycle commit with exactly that
writer's frontmatter; every later commit a Sleep commit carrying Sleep's own `sleep/decay` line for it; and the page
now differs from what was added only in `confidence`, `status` and `decayed_through`, body unchanged (a decay commit
stages the whole file, so a hand edit it carried shows). Anything else is kept. Same rails as the rest of the tool:
refused while Sleep runs, dirty pages skipped, one `cicada` commit (`trigger: maintenance/skill-archive`).

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
- *Synthesis dropped additive fields — fixed 2026-10-09.* The legacy synthesis body used to replace the page's, so
  the unioned key facts, links and open questions of a merged payload never reached the written page on that path.
  It now contributes only its Summary and new History lines (`entity_body.adopt_rewrite`); see *Off: the legacy
  rewrite keeps every item*.

### Placeholder people (2026-10-14)
A conversation often names someone only by role — "my partner", "my dad", "my old roommate". Stage 1 used to title
such a person after the owner ("<owner>'s partner"): measured on the owner's bank, 6 of 251 person pages, among the
most important people in the owner's life; one person split across "<owner>'s friend" (active) and "<owner>'s
partner" (archived), so a fresh session said the partner's name was not recorded; and the owner's name in titles
and ids (a portability bug). `api/services/role_people.py` is the one place that knows what a role-only name is:
- **The vocabulary is closed** (`parse`): a possessive of the owner (the owner page's name, its first word, its
  aliases, "the user's", "my", "mi", "… de <owner>") or "(unnamed)", over a list of relation words with a few
  qualifiers ("former", "replacement", "best") and a trailing "from …". A bare relation ("Partner") is read as one
  only on a page already marked `unnamed: true` — a bare word can be a real name ("Tia", "Mama"), and a name is never
  read as a relation. A name after the role ("friend Alice"), someone else's relation ("<owner>'s daughter's
  teacher") or any word outside the list is not a relation.
  **Singular** relations (partner, spouse, girlfriend, father, mother…) are held by one person; the rest, and any
  past relation ("former", "ex-"), are plural.
- **Stage 2 renames before anything keys a name** (`canonicalize`, first thing in `entity_resolver.resolve`, in
  place on the batch, so promotion, claims and wikilink edges all read the same names): a role-only *person* (a
  company "Partner" keeps its name) and any endpoint that says whose relation it is take the name of the one page
  holding that relation — the named page whose `owner_roles` holds a singular relation (the person said so), else the
  placeholder page for it — or, when none does, the relation's title ("Partner"; "Tia (unnamed)" when another page
  already has that name, so an aunt's mention never lands on a friend called Tia), marked `unnamed: true` with
  `owner_roles` for its page (`conflict_resolver.apply_changes` → `create_fields`). Promotion is unchanged: the renamed
  mentions are counted, parked and promoted as any name. A role-only person below the confidence bar no longer files
  "Who or what is Partner?" (its answer would become prose, not a name). Stage 1's owner block asks the model to
  name such a person "<Relation> (unnamed)" — a marked form; a bare "Partner" from the model stays an ordinary name
  (no mark, no question), because a bare word cannot be told from a name.
- **Stage 5.4 asks** (`ask_after_write`): after the pages are written, each unnamed person page the batch touched
  gets one inbox question, "What's the name of your partner?" (`features.md`), unless one is open or the person
  declined. It rides the cycle's commit like every question the cycle opens.
- **The answer** names the page or folds it into the person of that name (`features.md`); after it, a later
  "<owner>'s partner" mention attaches to that named page, because the record says it holds the relation.
- **Never a merge on a guess.** Two people are merged only on the person's answer or on evidence on the record.
- **The repair** for an existing bank: `python -m api.scripts.repair_placeholder_people --bank <path>` (dry run:
  counts only) and `--apply` (one `cicada` commit, trigger `maintenance/placeholder-people`; refused while Sleep runs
  or holds the pages; a page another writer left dirty in git, or one a merge would touch, is skipped and counted —
  what is dirty is read once, before the run writes, so the run's own writes never count; a second run changes
  nothing). Each placeholder page **merges** into a named person only when its relation is singular and exactly one
  named person holds it on the record — an open, non-event claim (no `valid_to`, not superseded) or a
  `graph_edges.yaml` edge whose predicate names **exactly** that relation: from the person to the owner "<head>",
  "<head>-of" or "is-<head>-of"; from the owner "has-<head>", or those forms for a symmetric relation ("partner-of").
  Any other token makes it another relation and no evidence: "father-in-law-of", "step-father-of",
  "business-partner-of", "former-partner-of". An `owner_roles` entry also counts; two holders is ambiguous and
  asked. A page whose bare title is a relation word but carries no `unnamed` mark ("Tia") is a name, never a
  placeholder. Every other placeholder is **retitled** by its relation (claims, edges and references follow
  the new id) and **asked**. The merge is `entity_merge.merge_entities`: claims with provenance, sources, history and
  every reference move, the loser's title is not kept as an alias (Stage 2 finds the person by `owner_roles`).
- **Disclosed:** a plural relation's placeholder ("Friend") still gathers every unnamed friend's role-only mentions,
  as "<owner>'s friend" did; the question shows the page's own summary so the person can tell which one, and naming
  it moves those mentions to that person. A relation word outside the list stays a page of its own, as before.
  Claim *text* written before a rename keeps the old title (it is the record of what was said); ids and links move.

### Page quality (2026-10-09)
The owner, on a clean run: "the markdowns of each page are too short and some saved facts are useless." A page should
read like a short wiki article about the thing as it figures in the person's life — what it is, what it is to them,
where it stands, the facts worth remembering once each. What changed, besides promotion and summaries above:
- **Stage 1's prompt** asks for that article: the person's relation first; facts about the thing, never about the
  conversation ("the assistant suggested …", "was mentioned in a conversation", "the user asked about …"); no
  implementation trivia of one debugging session (an artifact name, an action version, an error message) unless the
  person said it matters; one fact once, usually 0-5; a detail of the assistant's answer is not an entity unless the
  person engaged with it. An assistant-said fact stays legitimate evidence (kind `assistant`); the bar is triviality,
  not source. A prompt change is not measurable offline; the deterministic parts below are.
- **Narration is dropped at Stage 1** (`fact_policy.about_the_conversation`): a fact whose subject is the thing itself
  (its name, an alias or a pronoun) and whose only other words say it came up in a conversation, counted in a debug
  line — the page's sources already say so. Any other subject ("Moving to Berlin … was discussed in a conversation")
  is a fact with content and is kept.
- **Only repeats fold** (`fact_policy.restates`; owner ruling 2026-10-09 after two review rounds): an incoming fact
  (or a sentence of a summary that lost the fold) is dropped only when it is EQUAL to an item already on the page, or
  to an earlier incoming one, after trivial normalization — case, accents, whitespace, wikilink brackets, trailing
  punctuation. Never containment, never stopword or preposition removal: "works at Acme" inside "works at Acme's
  competitor", "uses Postgres" inside "uses Postgres or SQLite", "launched" against "will launch" are all kept.
  Paraphrases and more specific restatements fold only through opt-in synthesis, behind its guard; with synthesis off
  near-duplicates stay — a duplicate is cheaper than a lost fact. Used by Stage 2's same-name fold, every section
  merge, the re-read gate and the pending store. An existing bullet is never removed or reworded.
- **Offline eval:** `python -m benchmarks.system.page_quality --scratch <new-dir>` runs the production Stage 1
  post-processing, Stage 2, Stage 3 and the page writer over synthetic conversations with recorded Stage-1 answers
  (`benchmarks/system/fixtures/page_quality.json`), with synthesis off and on, and reports pages, one-conversation
  pages, words, facts, near-duplicates, narration, fallback Summaries, background bullets, every extracted fact that
  reaches no page or pending line, and calls and prompt characters by stage per batch.
- **Existing pages:** `python -m api.scripts.repair_page_quality --bank <bank>` (dry run: counts only, never a name)
  counts one-conversation pages, which old proxy let each through (`old_rung_*`, read back from what the page kept)
  and whether the measured bar would have written them, glued/over-budget/fallback
  Summaries, background bullets, narration, restated and assistant-phrased facts. `--apply` (the person's call) repairs
  only what a Sleep update would now write, on machine pages, losslessly — background bullets and displaced Summary
  sentences become Key Facts when they add something, the fallback's clause and narration facts go — in one `cicada`
  commit (`trigger: maintenance/page-quality`), refused while Sleep runs, dirty pages and pages with free prose in a
  list section skipped (`skipped_free_prose`). Near-duplicate facts
  already on a page and one-conversation pages are counted, never changed.

### Pages as articles (G194, 2026-10-09)
The owner: "i dont get yet why the consolidation as wikipedia articles of stuff still doesnt fill like this?" — pages
read as fact sheets (a one-to-three-sentence Summary, then Key Facts bullets), because the merge prompt capped the
Summary by type, the orientation writer rewrote only the Summary under the 600-character budget, and nothing turned
a page's facts into connected writing. The direction (owner, after gbrain and Cognition's agent memory): stop
constraining the prose; git is the safety net, the claims and the dated timeline are the record.

- **Shape** (`storage.md`, *The body*): the Summary lead and a canonical `## Article` of `### ` prose sections with
  inline `[[links]]` above the line, rewritten freely; the record below (Key Facts, History, Links, Open Questions,
  Related, claims), unioned deterministically and never shortened. Key Facts stay: they are not claims (claims come
  from relationships and agent writes), so they are the record the article is compiled from, each with its G118 row.
  The `article` frontmatter stamp marks the prose as the writer's; an edit makes the page the person's.
- **The writer** (`entity_article`, `CICADA_PAGE_ARTICLES_ENABLED`, off until the owner reviews the numbers below,
  like the synthesis switch): in Stage 3, a machine page resting on 2+ conversations once the update lands, that
  gains anything (the re-read gate still applies), gets ONE JSON call in place of the synthesis call; the
  contradiction call is unchanged. A one-conversation page is a stub: the deterministic merge, no call (short because
  it is a stub, not because of a cap). A page whose prompt is over `CICADA_PAGE_ARTICLE_MAX_INPUT_CHARS` (60,000) is fitted, never
  clipped mid-input (`entity_article.fit`, owner page 2026-10-14): claims sharing a predicate and an object fold into
  one input (the latest text, how many conversations said it, first and last day, every evidence row); then claim
  inputs are left out — a log's (`entity_body.is_log`: a predicate the stems positively call activity, in a family held
  for more than 3 objects; when unsure, a fact) before a fact's ("studies at") or one about a person page (who is in a life is never a log), the fewest conversations and the
  longest ago first — then History lines, oldest first; this
  update's words, the earlier lead and article, facts, questions and links never; LINKABLE keeps the names a kept
  input mentions. The record keeps every claim and line. Only a page whose own record is still over the budget
  keeps the deterministic merge if it has an article, else today's path.
- **A hub's Related rolls up** (`entity_body.RELATED_MAX`, 60 linked pages; owner page 2026-10-14): `## Related` is a
  view of `graph_edges.yaml` rebuilt on every write, so on a page linking more pages than that, the block is **never
  more than 60 lines, family lines included**; lines go, in order of right, to its **strong facts**, then its weaker
  facts (the latest) — facts take at most 40, and strong facts past that go on one `facts` line, never dropped —
  then its latest people in the room left; every other link is one line per **family of meaning** (`- asked or
  learned about: 1,203 pages — latest [[A]], [[B]] … and 1,195 more`), the people who did not fit on a `people`
  line. Labels are free-form — the real owner page had hundreds of verbs, the commonest three times each, so
  grouping by exact verb left 1,676 of 2,024 lines (2026-10-14). `entity_body.relation_family` reads a label in this
  order: activity when it **starts** with an activity or intent verb ("considered studying at", "planned to move
  to"; received or got a degree, a job or a role excepted), whatever follows; `strong` when it folds (the bank's predicate map, else the seed's synonyms) to a fact predicate
  (`STRONG_PREDICATES`: works-at, studies-at, located-in, part-of, family relations…) or says one in another
  inflection ("studying at", "got a job at", "received a degree from", "graduate of"); then an activity family
  (`asked`, `planned`, `built`, `used`) when an activity verb says so, whatever preposition follows ("learned from"
  is activity); then `relation` for a weaker fact word ("colleague", "joined"); else `other`. **When unsure, a label
  is a fact** (reviews 2026-10-14): `is_log` is true only for an activity family the page holds for more than 3
  objects — the same rule orders the ledger's spill and the article's inputs. Each rolled-up
  link is still an edge, still on the linked page's own Related (inbound edges are mirrored there), and its claims
  are still the owner's, in the page's ledger. Per-conversation activity is not a fact about the person: its home
  is the linked page, the claims ledger and the timeline, not the person's article or its Related. A page with a stamped article is
  never handed to the orientation or legacy rewrite, whatever the settings: both replace the lead the writer owns; an
  inbox answer on it takes the fallback append.
- **Inputs**, numbered: the record after this update's deterministic union (`f` facts with the days their rows'
  conversations were said, `h` dated History lines, `q` questions, `l` links), this update's summary sentences (`s`),
  the page's earlier lead and paragraphs (`p`, unverified background), current claims (`c`, with `valid_from` and
  their evidence), today, the owner's name, the pages it already links to (the only names it may link) and suggested
  sections for the type (a project, a person, a tool and a place get different ones; the model uses what the material
  fills). No length caps: "length follows the material".
- **Rails in code** (`entity_article.parse`): each paragraph lists the inputs it was written from; a cited input must
  share a word with the paragraph. A paragraph with no valid citation is the model's own knowledge (G121), one with a
  relative time word is not written as of its date (G194), one saying "the user" breaks G169 — each is dropped and
  counted; a `[[link]]` to no page is unwrapped. A lead that fails rejects the article (no retry; the deterministic
  merge). Nothing the record holds can be lost: Stage 5 writes the record merge first. The two kinds of prose that
  are not yet record — this update's summary and, on a page's first article, its old Summary — have each sentence the
  article does not visibly carry (cited by a paragraph holding three in five of its words, every name in it and every
  number, negation and tense word, `fact_policy.compatible`) kept as a Key Fact. The writer's own earlier prose is
  rewritten freely; git keeps every version.
- **Provenance** is per paragraph, not per sentence: the app draws a paragraph as one row, so one click from a line
  is one click from its paragraph; per-sentence citations would multiply output and failure for no finer click. Each
  paragraph (and the lead) records the evidence rows of the inputs it validly cites under its exact text guard
  (`storage.md`); an edit unlinks it rather than recertifying it.
- **What the old machinery is still for.** The equality-only fold (`fact_policy`) keeps the record free of exact
  repeats — still needed, it is how Key Facts union. `entity_body.adds_anything` (the re-read gate) still saves both
  calls on a resumed conversation. The guards that protect claims (fences preserved, never parsed into prose) and the
  timeline (History merged, never rewritten) are untouched. The prose-only machinery — the 600-character lead budget
  (`bound_summary`, `lead`, `retain_orientation`) and the orientation `restated`/`covered` fold — exists because the
  Summary was capped and was the only prose; on an article page it no longer runs (the merges keep an article's lead
  as written), and it stays only for stubs and for banks with articles off. With articles on, the orientation call
  serves only a page over the article budget that has no article yet (stubs take the deterministic merge), so
  retiring `summary_synthesis_enabled` is the next simplification once articles are the default.
- **Measured offline** (`python -m benchmarks.system.page_articles --scratch <new-dir>`; a 15-conversation project, a
  5-conversation person and a one-conversation tool, one conversation per batch, fakes only): calls are equal — 36 over
  15 batches either way (18 write + 18 contradiction; today's write is the orientation call) — prompts grow 42%
  (129,365 → 183,993 characters, median batch 8,392 → 12,481) and answers about 11× (2,380 → 27,326 with the
  mechanical fake; a recorded article for the 15-conversation page is 2,479 characters from an 8,413-character prompt).
  Modelled plan-engine time (2 s a call, 5,000 input and 70 output tokens a second, assumed): Stage 3 over the run
  67.9 s → 149.2 s, the largest batch 5.0 s → 13.4 s — output-bound, so the cost is per rich page per batch, not per
  call. Every extracted fact and dated line is on its page in both runs; the stub stays a stub.
- **Existing pages:** `python -m api.scripts.rebuild_page_articles --bank <bank>` (dry run: counts only — pages,
  skipped as archived/media/human/one conversation/already articles/over budget, selected, prompt characters; never a
  name). `--limit N` / `--entity <id>` narrow it; `--preview-dir <outside-the-bank>` makes the calls and writes
  `<id>.before.md`/`<id>.after.md` there, touching nothing in the bank; `--apply` is refused before any call unless the
  backend says Sleep is idle, makes the calls outside the write admission, then writes in one commit
  (`trigger: maintenance/page-articles`, the model as `Cicada-Author`), skipping a page written since it was read. One page's
  trouble is that page's (2026-10-13, after a malformed answer aborted a 1,056-page run): a malformed, empty or
  unparseable answer, a timeout, a lost connection, a failed or refused call, a page too long for the model — the
  page is skipped and counted under `page_failures`, as Sleep's article path falls back on the same answer. What
  every later page would meet — a plan limit, an unreachable engine, a missing model, a metered key's quota or
  outage — or 5 engine failures in a row stop the run: no new page starts, the pages in flight finish, and what was
  written is kept (the preview files, or the one commit), with `stopped` and `not_attempted` in the counts and exit
  5. Running it again continues: finished pages are already articles.

### Temporal decay
Absence of mention IS a signal, and **how often something came up sets how fast its absence
counts** (G147). **Age counts from when it was said** (owner ruling 2026-10-09, amending G170's "an import is not
silence"). Silence is measured from `max(last_referenced, decayed_through)` in two parts (`decay_policy.silence`):
**proven silence** — from the last mention to the day Cicada read it (a page's `learned_on`, a claim's
`recorded_at`) — is charged in full, once: the run that read the mention read everything waiting, so the gap is the
person's, never an outage; **live silence** after that day is charged at most one week per pass
(`MAX_DECAY_DAYS_PER_CYCLE`, the watermark advancing only by what was charged — TODO ruling 1), so a gap between
runs is worked off over several. Both are charged
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
count). **One-offs archive, repeats fade** (owner 2026-10-09, after the first dry run on a real bank would have
archived 79% of it): proven silence alone never takes a page or claim resting on 2+ distinct dated conversations
(`decay_policy.conversations`; a memory export entry is not one) below 0.39, just under the question line
(`decay_policy.proven_floor` = decay-question threshold − 0.01, applied by `decay_policy.charge`) — it stays
`decaying`, dimmed and on the graph, and only live silence after Cicada read it carries it on to the archive line, at
the normal pace (at the default `active` pace, about 38 days for two conversations in different weeks, 52 for five,
66 for twelve; 27 when both fell in one week). A one-conversation page or claim falls freely. A create stamps
`decayed_through` at the content date and `learned_on` at the cycle's day. **A mention never lowers:** on a page
not yet settled (proven silence still owed — read earlier in this run, or in one that stopped) a later mention moves
`learned_on` and the age counts from it; on a settled page, a mention from a conversation dated on or after its
watermark (one no charge has covered — every live mention) revives it (`max(current, 0.6)`, `active`) and restarts
its clock when it was said: the gap until Cicada read it is proven silence, charged once by the pass that settles it,
never below where the page stood before the mention (`confidence_before_mention`, kept only until then; never on an evergreen page); one
dated before the watermark (an old conversation read late) adds its source and its week and moves nothing else —
except that when it makes a one-off its age faded (`faded_by_age`) a repeat, the page is lifted to where the two
conversations read in one run would have left it: the repeat floor less the live silence from the day its age was
settled to today (`_lift_to_repeat_floor`; an archived page's watermark stops the day it archives, so it is never the measure; only raises, archived → decaying where it lands at or above 0.2), so how imports
split across runs never changes the result. Claims are lifted the same way in `_reinforce`. A late restatement of a
settled claim (said after its watermark, read later) still restarts the claim's clock the day it is read, so a page
and its claim from the same late capture can differ slightly. Nothing is charged mid-drain (the batches before the last
run with `decay=False`), and the pass that charges decay also settles the pages its own batch creates or references
(the change's `settle` directive, applied by `apply_changes` on the page as merged, in the commit that writes the
page) — so a page said in 2024 and again in 2026 ends the drain alive whatever the order the two were read in or
where the batches broke, and a one-off from 2024 is archived on the day it is read. **What ruling 1's cap still
protects:** a page nobody mentioned during a gap between runs (an outage, a paused schedule) — its silence is
charged a week per pass. A page first heard of in a conversation from during the gap is charged its whole proven
gap at once (floored if it is a repeat); a page Cicada already knew and that was mentioned during the gap restarts
its clock instead. Claims follow the same rules (`claim_reconciler.claim_silence`, `_reinforce`): a claim minted
from a dated conversation stamps its watermark at that day; a restatement of a claim not yet settled follows the
latest mention; a settled claim restated in a conversation dated on or after its watermark (an agent's live write,
with no dated conversation, counts as said today) gets the higher confidence and a clock restarted today; an older
restatement or a memory entry adds the source only. A subject read this pass is charged its proven silence only.
Only Sleep charges claims: the agent and progress writers reconcile with `decay=False` (G85). A claim with no dated
conversation keeps the old anchor (`recorded_at`, else `valid_from`). **A question fires only when live silence
carries a page or claim across 0.4** (`decay_policy.asks`). One that its own age took below the line — proven
silence charged in a pass, the mention read more than seven days after it was said (`decay_policy.heard_late`) — is
marked `faded_by_age` (a page's frontmatter key, a claim's field) and is never asked about as live silence continues:
it archives quietly at 0.2, counted in Stage 3's one summary line. A page read late but still above 0.4 after its age
is asked when live silence later carries it across; a new mention clears the mark. Existing banks are charged once by the person's own
`api/scripts/recompute_decay_by_age.py` (`age_recompute`), with the same floor: dry run by default (counts by type
and by the age of the last mention, `would_archive`, `would_decay`, `floored_repeats`, `would_be_asked` — only pages
read within a week of being said; everything else it lowers below 0.4 is marked `faded_by_age` — and claims), `--apply` refused while Sleep runs, one `cicada` commit (`trigger:
maintenance/decay-by-age`), the day a page was read estimated from the git commit that added it, only changed claim
lines rewritten, a second run a no-op.
**A memory export entry is facts, not activity** (owner, 2026-10-08). A `source: claude_memory` episode is a summary
of the person dated by the export entry's `updated_at`, not by when anything in it came up. `episode_time` is the one
predicate: such an episode is no week in `w` (page, claim and card alike), and Stage 1 hands Stage 2 its entities
with no timestamp or day and `untimed: true`. A change made only of memory entries creates a page with **no
`last_referenced`** (`created` and `decayed_through` are the cycle's day), and on an existing page moves neither
`last_referenced` nor `decayed_through` and recovers no status; its facts, claims (with their `valid_from`) and
`source_episodes` are written as usual. Any real conversation in the same change dates it as before.
Below 0.2 → `status: archived` (the page stays in `entities/`); below 0.4 → a decay nudge when live silence carries it across (never for what its age took there).
Mentioned again in a conversation no charge has covered → promoted back at `confidence = max(current, 0.6)`, clock
restarted the day it was read; an old conversation read late never revives and never lowers. Evergreen
entities (the owner's page among them) skip all decay math. **Confidence does not rank recall:** search puts archived pages last and otherwise ranks
by relevance (`search_service._page`'s sort key and the per-kind cut's archived tier); whether
confidence should weigh in is a question for G148's benchmark pass to measure before anything
changes.

---
