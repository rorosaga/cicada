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
  **Notes keeps up and is dated when written (2026-10-23).** `AppleNotesWatcher` reads after the person's own first
  read (Connect, Refresh, onboarding's tick), then on launch, after a bank switch and every two hours — only while
  Notes is already open, since `tell application "Notes"` would launch it; Disconnect stops it, deleting nothing. Each
  record adds the modification date as AppleScript's locale-free `«class isot»` and the Mac's UTC offset, so
  `notes_sync` dates the episode when the note was last written (read on time); the human `modified` string stays the
  dedup key, and a 6-field record from an older app still parses and is dated now.
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
  saved. **A new save is dated when it was saved (owner decision B, 2026-10-22):** its episode's `timestamp` and id
  day are `added_at` (the id its local day), else `saved_at` itself as the id day and noon UTC of it as the timestamp
  (never later than now), so Sleep and Ask read the save on its own day, as a calendar event is read on its start; with no recorded date it is the day Cicada took it in, and an
  existing episode is never renamed (ruling 34). The media page's `created` stays the ingest day. A moved bookmark is a URL already held, so a reorganisation is never fresh. **A re-save is fresh (G191 v3,
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
  Cicada; now the status says the first and the bookmark page's Remove does the second. **An unchanged file is no news (perf 2026-10-24):** the
seen-set is rewritten only when its hashes, folder scope, `newest_added` or `left` map move
(`bookmark_seen.entry_unchanged`); a sync that changes none of them writes nothing and commits nothing. Before, every
wake of an unchanged file (the watch fires on each write Chrome makes) rewrote the file with a new `at` and made a
`Bookmark sync` commit, and the file's mtime ticked the app's sources domain. A pending bookmark removal
  question is retired on the channel's next sync, its link marked from the day it was asked (`_retire_removal_questions`,
  trigger `sync/bookmark_left`); papers' `removal` questions are untouched.
- **Capture must not depend on a model deciding to call a tool** (G105). Every Claude Code and
  Codex session is captured by the harness's own `Stop` hook
  (`api/hooks/capture.py` → `POST /capture/transcript`; on a client of a server elsewhere, read there and posted as
  turns to `POST /capture/session`, below). Cursor and Gemini CLI are captured by their own
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
  `episode_ids.utc_now_iso` — never a naive local time with a `Z` appended. **The date in an id is the conversation's
  local day** (ruling 34, 2026-10-22): the person's zone at its first turn, never the UTC day. The two hook writers
  sliced the UTC stamp; `transcript_capture.write_session` (Claude Code, Codex, `/capture/turn`, relayed turns) and
  `telegram_capture` now mint through `episode_ids.id_day`, in this machine's zone or, for a client of a server
  elsewhere, the `utc_offset_minutes` its hook posts (below). The follow-up (2026-10-22) found four more writers slicing
  a UTC stamp and moved them to `id_day` too: Messages sittings, Wispr Flow meetings and notes, watched folders
  (`original_date`, the day `episode_staging` mints from) and `watch_record`; the companion app's Log note takes
  `id_day(now)`. Wispr dictation days stay keyed by their UTC day (`wispr:dictation:<day>` is the staging source key:
  re-keying would split a day already captured into a second episode). **Relayed turns** take the zone the app sends:
  ChatGPT puts a coarse `openai/userLocation` in each tool call's `_meta`, whose `timezone` (an IANA name — nothing else
  of it is read, stored or logged) `relay_capture.offset_from_meta` turns into the offset; claude.ai sends no zone and a
  model is never asked to guess one, so its relayed ids take this server's zone. An id is never
  renamed, so a hook capture minted before 2026-10-22 between local midnight and the UTC one keeps the UTC day; the readers
  that took the day from the id (`ask_sources.said_day`, `benchmarks/hard_questions`) read the episode's `timestamp` in the
  person's zone instead, and `ask` dates each line by the local day its turn was said. **One reading rule:**
  `episode_ids.local_day` reads any stored stamp (naive legacy = this machine's time, `Z`, `+00:00`, a YAML datetime, a
  bare day) as the day it was said in this machine's zone; `ask_sources.local_day` and `change_timeline` call it, and
  Sleep dates every conversation through it (*Dates in the prompts*, below). Legacy files are not
  migrated: readers accept both shapes and the queue sorts by `timestamp_sort_key`. A processed
  episode carries `processed_by` (`sleep` vs `agent`) so a flipped flag is distinguishable from a
  consolidation. `processed_by` also takes `user` — a companion note the person wrote in the app
  (G141 PJ-3b's Log; already processed, so Sleep never re-reads it).
- **Both dates on every episode** (TODO ruling 39, owner 2026-10-24: "have both dates recorded for everything when
  available"). `timestamp` stays the item's own date where its source gives one — a note's last edit, a message's
  send, a bookmark's `date_added`, a reminder's creation or completion, a Notion row's date, a watched day's first
  watch, a calendar event's start once begun, a feed item's publication — and `received_at` (aware UTC,
  `episode_ids.RECEIVED_KEY`) is when Cicada received it. `create_episode` stamps it on every new episode, right after
  `timestamp` with the `turns` sidecar still last (`stamp_received`); the stager writes it in `write_new`
  (`EpisodeDraft.received_at` pins it for a writer with a pinned clock, the demo); a writer's own value wins. It is set
  once: an edit in place, a re-date (`redated_from` keeps the moved `timestamp`, never the receipt), a rename, a relay
  upgrade and a tombstone leave it. A live hook's two dates are the same moment, both written. Ids are never renamed
  for it and older episodes are not backfilled: a missing `received_at` is unknown. `test_both_dates.py` fails when a
  module that mints an episode id creates one without it. Surfaces show the received day only when it is at least two
  days after the item's own (`episode_time.received_shown` / `received_after`): the Reader's meta line, a Sources list
  row's help and spoken label (`received`), recall's excerpt label.
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
  names. **Wispr's own time shape (2026-10-23):** its database writes `2026-08-26 14:03:07.123 +00:00` (a space
  before the offset, milliseconds), which `fromisoformat` refuses, so every meeting, note and dictation row was
  dated the day it was imported (dictation rows were dropped outright); `wispr_flow._ts` reads that shape and its
  variants (`T`, `Z`/`UTC`, `+0000`, no fraction, no offset = UTC). A meeting or note already staged on the wrong
  day is moved in place on the next sync (`EpisodeDraft.redate`: same source key and file, `timestamp` moved,
  `redated_from` kept, `processed: false`); its id keeps the day it was minted with (ruling 34 — never renamed), and
  everything that dates an episode reads `timestamp`. `redate` is opt-in, so a writer whose first stamp is
  deliberate (a future calendar event) keeps it. Apple Calendar (G142): the app reads EventKit after the one standard permission prompt and
  posts a rolling window to `POST /sources/calendar-local/sync` (one request = the whole window).
  `calendar_local.py` stages each event keyed `calendar-local:<id>`:
  - a new episode for an event that has already begun is dated its start (timestamp and id day; read on time,
    2026-10-16 — a first sync's past month was otherwise a month of mentions today); one still ahead is dated the day
    Cicada learned of it; an existing episode keeps its id and first stamp (benchmarks/newuser, 2026-10-22);
  - notes are scrubbed, then cut at 2,000 characters;
  - a link keeps no query;
  - an event gone from the window is tombstoned, only for the calendars the request named;
  - one `user` commit per sync (`capture/calendar`).
  The app half: `CalendarReader` reads every calendar on the Mac through EventKit, only after Connect and
  macOS's full-access prompt, 30 days back to 60 ahead, and posts on launch, on `EKEventStoreChanged`
  (debounced), every 3 hours, after a bank switch and on Sync now; an empty read is never posted (it would
  tombstone the window); Disconnect stops it and deletes nothing. A subscribed ICS calendar's event is dated the
  same way since 2026-10-23 (`calendar_registry._begun_at`: its start once begun, else the day it was polled), and
  its fetch goes through `net_guard` on every hop, as the RSS poll's does (`network.md`).
  Apple Reminders (G219, the G142 path; one way, never written back — ruling 38): the app reads EventKit after the one
  Reminders prompt (`requestFullAccessToReminders`; macOS has no read-only grant, so the row says "full access" before
  it) and posts the lists the person ticked — nothing is pre-ticked, and nothing is read before a tick — to
  `POST /sources/reminders-local/sync`: every open reminder of those lists plus those completed since `completedSince`
  (the app sends 90 days). `reminders_local.py` stages each keyed `reminders-local:<calendarItemExternalIdentifier>`:
  - the body holds the title, the list (and its account), the status, created, due (a bare day when it has no
    time), priority, a link without its query, and the notes scrubbed then cut at 2,000 characters; the title is
    scrubbed too;
  - **dated when it happened:** a completed reminder at its completion, an open one at its creation, neither known the
    day Cicada learned of it; the due date is a fact in the body and `reminder_due`, never the episode's date. A
    reminder completed after it was first read moves to its completion in place (`EpisodeDraft.redate`; the id keeps
    its first day, ruling 34);
  - tombstoned only when its list is named, it was not posted, and it could have been — open when last read, or
    completed on or after `completedSince`; one completed before that aged out of the read, not out of Reminders, and
    is kept; an unticked list says nothing about its reminders;
  - the person's own words (`evidence_kind: user`), except in a list the person marked "Others add to it", whose items
    are `assistant` (never the person's own, the folder rule) with `reminder_list_shared: true`;
  - a record, not a conversation (`inbox_tend.record_origin`, beside calendar entries): never a skill's grounding or
    a conversation to pick up; turning a completed reminder into a done happening, or a dated one into a planned
    milestone, is Sleep's reading of the episode (G141), never capture's;
  - 413 above 5,000 reminders, 422 for a `completedSince` with no offset, 409 in a demo bank; one `user` commit per sync
    (`capture/reminders`), scoped to what it wrote.
  The app half (`RemindersReader`, `EventKitRemindersStore`): `CalendarReader`'s triggers (launch, a debounced
  `EKEventStoreChanged`, every 3 hours, a bank switch, Refresh, a tick); a read whose ticked lists are not there is
  never posted (it would tombstone them); unticking the last list posts nothing; Disconnect bumps a generation every
  await re-checks, so a read in flight when the person pressed it never posts and never turns the row back on. **Not
  built (slice):** a list the person names as a project's backlog mapping into G150 items with no model — the G219 row
  holds the design.
  A Notion export (G219 slice 1; ruling 38): the Markdown & CSV zip on the one intake (`/intake/sniff`,
  `/intake/import`; `notion_export.looks_like` decides by names — most `.md`/`.csv` files carry Notion's 32-hex id, and
  no chat export's files are present; part zips are read one level down). `notion_export.parse_zip` makes documents
  (`body`, `evidence_kind: user`, origin `notion-export`, scrub writer `notion`; `episode_staging.draft_from_export`
  takes a `body` beside `messages`): a plain page keyed `notion:<page id>` with its breadcrumb (`In: Parent › Child`),
  links to other pages reduced to their words and embedded files left out (web links kept), a title over sub-pages and
  nothing else skipped, a long page split by H2 like a watched folder's file (`notion:<id>#<slug>`). **One episode per
  database row**, not per database: a row is one idea with its own date (dated by its *Created* property, else *Last
  edited*; read on time), an edit re-queues that row alone, and a row maps one to one onto a backlog item later; the
  CSV row (`_all.csv` preferred) gives every property and the row's own page its body, joined by title in the
  database's folder (a title Notion cut in the file name matches by prefix); a CSV row with no page is kept, keyed
  `notion:<database id>:<title hash>`. Rows sharing a title ("Untitled") each take the page whose own property block
  agrees with the CSV row, and the page's own properties win, so a re-export in another order never swaps them. A
  page with no date of its own (every plain page, a row with no Created / Last edited) is stamped the import day but
  is **untimed**: source `notion-export-undated`, one of `episode_time.UNTIMED_SOURCES` (the memory-export rule), so
  its facts are kept and nothing it mentions counts as mentioned that day; dated rows keep source `notion-export`. A
  row whose *Created by* names someone other than the bank's owner is `assistant` (never the person's words); with no
  owner name known, a database more than one person created is; a page or table with no *Created by* is the person's.
  **What is read is bounded:** only `.md` and `.csv` members (16 MB each, 256 MB in all, checked on the declared size
  and while reading), part zips one level down only (256 MB each, a zip inside a part never opened); everything left
  out is a preview warning. A second import of the same zip skips everything (the stager's hash); an edited page
  updates in place. A page missing from a later export is never tombstoned — an export can be one page's.
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
  **Cards wait, and a card is matched on mention (owner ruling 2026-10-20).** A card that matches no page — and has a
  two-part name, so it ever could — is kept outside every bank in the people directory (`people_directory`, shared
  with the LinkedIn connections: `$CICADA_HOME/people/<bank>/contacts.json`, its thumbnails beside it in `contacts/`
  named by a hash of the card id; folder 0700, files 0600, written by a rename) with exactly what the app posted —
  names, which facts the card holds, the thumbnail — and nothing more; the bank gets nothing for it. Every sync
  rewrites the set whole, so an edited or deleted card leaves at once, thumbnail included; the response counts
  `waiting`. The address book's own "me" card (`CNContactStore.unifiedMeContact`, sent as `isMe` on that card only)
  goes to the owner's page whatever its name and never waits; with it present, a namesake card of the owner's page
  neither lands there nor waits. A waiting card promotes a person's first conversation mention on its own (*Entity
  promotion*); Sleep's engine-free tail matches the cards still waiting against the night's pages
  (`_rematch_contacts_safely` → `contacts_local.rematch`, right after the LinkedIn rematch; its own `cicada` commit,
  `sleep/contacts`; dirty pages skipped; undone on a failed commit; never the owner's page, never a demo bank), and a
  matched card stops waiting. Right after it, the tail's **Where to check** step (`_where_to_check_safely` →
  `source_proposals.propose`, ruling 36 D5, 2026-10-22) proposes the profile links and own repositories already on the
  record as sources and keeps one question per page about them — engine-free, no fetch, its own `cicada` commit
  (`sleep/where-to-check`), dirty pages skipped, undone on a failed commit (`storage.md`, "Where to check"). **Stopping Contacts forgets them (review of #391):** Disconnect, or the app finding
  access refused or taken away in System Settings, calls `DELETE /sources/contacts-local/waiting`, which deletes every
  bank's `contacts.json` and thumbnails (Contacts is app-wide; token-gated like every route; counts only), so no first
  mention and no tail rematch uses a card again; what matched pages already gained stays. LinkedIn's kept export has
  its own forget, `DELETE /sources/linkedin-connections` (this bank; *Forget kept connections* in the LinkedIn panel).
  **The Contacts forget lands at once, even while Sleep runs (review of #393):** the app sends it once, so a 409 would
  keep a disconnected address book's cards. It deletes the set and then stamps a forget marker,
  `$CICADA_HOME/people/.contacts-forgotten` (ns), under the lock every save of the set takes. Every Sleep read of the
  set is stamped with its read time (`load_waiting` → `READ_AT`) and treats a set read before the marker as empty
  (`forgotten_since`): Stage 2's index matches nothing, Stage 5's `seed_page` seeds nothing, the tail's rematch writes
  no further page and never saves the set back, and a sync that read the book before the forget never saves its
  waiting cards. A sync sent before Disconnect but handled after the forget is dropped whole (409, nothing written):
  the app mints a connection id at each Connect, sends it with every sync and names it in the forget, and the
  marker keeps the last 32 ended ids (`connection_ended`; an older app sends none). Its admission class is
  `MARKED` (`test_write_admission_sites.py`). The LinkedIn forget is admitted
  (409 while Sleep holds the pages; its panel says so in words). The notes field is still never read. A bank's trash takes its people directory with
  it and a rename moves it (`people_directory.forget` / `rename`).
  LinkedIn connections (owner 2026-10-16: "extracting people profiles from my LinkedIn connections … would be nice";
  G154's pattern): the export's `Connections.csv` — or the export `.zip` carrying it — comes in only through its own
  door, the LinkedIn tile's **Connections** (`POST /sources/linkedin-connections/preview`, then `/import`; the app reads
  the file the person picked or dropped and posts its bytes, with the CSV's modification day as `?exported_on=`; a
  zip's member date otherwise; never a future day). The save-list importer still refuses it by name and now points
  here. `linkedin_people.py` reads LinkedIn's shape — notes above the header, First/Last Name, URL, Company, Position,
  Connected On (`04 Mar 2021`); a credential after a comma in Last Name is dropped; **the Email Address column is never
  read into anything** — and matches exactly one `person` page: first a page that already lists that profile link
  among its sources, else the folded full name (either order) or an alias; never the owner's page, never a page that
  names a *different* LinkedIn profile (the owner's page is known by its `owner: true` flag and by `resolve_observer`'s
  id), and two connections on one page (duplicate names) or one on two pages match
  neither. **It never creates a page.** A match gains its profile link as a source `{ref:
  https://www.linkedin.com/in/<slug>, kind: url, predicate: linkedin, added_by: cicada, match: name|alias|link}` (how it
  matched: the page's own name, only an alias, or a link the person or an identified agent already listed as their account; a link from before the
  field gets it at the next import or rematch) and three claims observed
  `external:linkedin` (`source_trust: external`, `authored_by: cicada`, `origin: linkedin/connections`, `reasoning`
  evidence — no episode holds an export): `works-at` (a `company` page's id when exactly one has that name, else the
  words), `role`, both `valid_from` the export's day, and `connected-on` (the day they connected). **Newest wins:**
  Cicada's own LinkedIn claims for a predicate are one dated line — a newer export (or a profile the person's agent
  read, `mcp.md`) with a different value closes the current one (`valid_to`, `superseded_by`); an older export, the
  same value, or a re-import writes nothing. No other claim on the page is touched. A link the person removed
  (`sources_removed`, matched by the profile's slug in any spelling of the link, under any predicate) is never re-added and that connection writes nothing more on that page — the person said it is
  not them. Everything text-shaped is scrubbed (writer `linkedin-connections`). One `user` commit per import
  (`capture/linkedin-connections`), 409 while Sleep runs and into a demo bank (the preview too), 413 past 32 MB.
  **The directory:** every connection (names, link, company, position, day connected — no email) is kept outside every
  bank at `$CICADA_HOME/people/<bank>/linkedin-connections.json` (`people_directory`, beside Contacts' waiting cards; 0600; an older export never replaces a newer one;
  the folder goes when its bank is moved to the trash and follows a rename, so a new bank of the same name inherits
  nothing;
  `GET /sources/linkedin-connections` gives its day and size, never a name), and Sleep's engine-free tail matches it
  against the night's pages (`_rematch_linkedin_safely`, after source links, before any poll; its own `cicada` commit,
  `sleep/linkedin-connections`, dirty pages skipped, undone on a failed commit; never in a demo bank) — so a person who gets a page later
  gains their link and facts then, and nothing is ever said about anyone without one. Nothing is fetched: the link is
  where to look the person up; the profile-photo rung may use it only once the person takes the source (its own
  off-by-default gate, `person_photo`, unchanged).
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
  `NSUnarchiver` stays out of the app), never makes a tapback a turn (a tapback row quotes the OTHER side's words under
  the reactor) and skips events, names attachments (`[image: plan.png]`), folds a message's line breaks so it is one
  turn line, and stages
  one episode per **sitting** (messages more than 3 h apart start a new one; the measurement and the reasons are G179's)
  keyed `imessage:<conversation>:<first message key>`. A pass merges into the stored sittings it touches, rebuilt from
  each episode's own body, `turns` sidecar, `message_keys` and extras: an edit rewrites in place, re-queues and is
  marked `edited`, an unsent message leaves the words (an emptied sitting is tombstoned), a bridging late message merges
  two sittings into the earlier one, which keeps its key and id. **What made it a conversation (2026-10-20,
  `turn_extras`, storage.md):** the app also posts a tapback's target and emoji (`associated_message_guid`,
  `associated_message_emoji`), an inline reply's target (`thread_originator_guid`) and an attachment's `is_sticker` —
  ids and a flag, each read only where that Mac's `chat.db` has the column (`PRAGMA table_info`). A tapback
  (`associated_message_type` 2000–2007 adds, 3000–3007 removes, 1000 a placed sticker) lands on its message's
  `reactions`, one per reactor (a new one replaces theirs, a removal drops it), its row's words never read; one whose
  message is not stored is counted (`reactions_orphaned`) and dropped, and a pass that only adds a reaction touches the
  sitting's frontmatter alone — never its words, never the queue. A reply points at its target turn, or at its key when
  the target is in another sitting; attachments are described (kind, name, size, type) beside their
  `[image: …]` words; an unsent message (`date_retracted`, or `date_edited` with the words gone) stays only as where
  it was and who sent it (`unsent_turns`), its text never kept. Sittings saved before 2026-10-20 have none of this until
  the person clicks **Read again** on the Sources page → Messages (`MessagesWatcher.readAgain`: every ticked
  chat's cursor back to its first message; nothing re-reads automatically) — a sitting whose words did not change gets
  its extras frontmatter-only and is not read by Sleep again. **The exports** fill the same shape where the export has
  it: ChatGPT's uploads (`metadata.attachments`: name, size, type; an unnamed picture otherwise), a generated image and
  a code run (a `tool` message — never a turn — noted on the reply it fed) and each reply's `model_slug` (the sidecar's
  `model`); Claude's attached files (`attachments` / `files`: name, size, kind) on the person's turn, beside the
  `attachment [<name>]` turns that hold their text. Re-importing an export a person imported before adds the extras the
  same frontmatter-only way (a large deferred import writes them in its background job, after its new and grown
  conversations, never in the request). Sittings split on what was **said**; an unsent placeholder then joins the
  sitting nearest it in time, so it never bridges two (a Read again re-posting an old unsend cannot merge two stored
  episodes). Telegram has no conversation import (its bot saves links), so it has nothing to carry. **Who is who:** the person's lines are `user:`; the other side's are `assistant:` when the
  conversation is with an AI agent — the person's mark, or an `identified` detection (`agent_detectors`, G188) — else
  `speaker:<label>:`; the frontmatter `correspondent: {name, kind, decided_by, detector?, detection?, signal?}` names
  it, with `conversation`, `service`, `message_count`, `from_person`, `sitting_first_at`/`sitting_last_at` and
  `message_keys`. The person's mark changes re-render every saved sitting in place from the stored episodes (`PUT
  /sources/messages/settings`, one `user` commit with the settings file). **A mark always reaches the record**
  (2026-10-16, #312 review): a sitting whose words move (`speaker:` ↔ `assistant:`) is rewritten and re-queued — an
  already-read one too, because who said what changed and Sleep must read it again (pages it fed wrongly are
  `correspondent_repair`'s, #301); one whose words do not move (an unknown chat marked a person: still
  `speaker:<name>:`) skipped the stager's unchanged-hash check and kept `correspondent: unknown`, so the mark never
  reached Sleep or the chat's page. `messages_source._stage` now records the draft's `correspondent` and title on every
  skipped sitting, frontmatter only (`episode_staging.reattribute`: body, hash and evidence spans untouched, no new
  episode, the queue as it was — an already-read sitting is not re-queued, since nothing it says moved). One `user` commit per sync
  (`capture/messages`); scrub writer `imessage`; demo bank 409. `GET /sources/messages/waiting` sums `message_count`
  over unread, live sittings per conversation — the Sleep page's and Home's bubbles — and carries `page`: the
  correspondent's own page when one exists, found from the newest sitting's decided record by `correspondents.find_page`
  (the rule Stage 2 resolves it by), `null` while undecided or held below the promotion bar. Through Sleep, the decided
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
  itself is refused by name, pointing at its own door (LinkedIn → Connections, above).
- **What is read.** A member is opened only when its NAME is a known save list; everything else in the archive
  (messages, contacts, posts, search history) is counted and skipped unread, media is never opened, a member over
  64 MB is skipped with a warning, and the generic URL-list parsers a single dropped file may fall back to are never
  used inside an archive. Watch and browsing history are not saves (G69): read only with `include_history` — through
  every door, a single dropped `watch-history.json` or `.html` included — and otherwise left out with one warning
  (`history_warning`) and a count (`history_excluded` on the preview and the intake sniff), so the app's drop offers
  its **Include watch history** switch (2026-10-16; the CLI's `--include-history` and the API's
  `?include_history=true` are the other doors). Read, history is never a save: see *Watch history* below.

  | Platform | Files read | Kept |
  |---|---|---|
  | Instagram | `saved_posts.json`, `saved_collections.json`, `liked_posts.json` | link, account as title, save date, collection name (likes: folder `Liked posts`) |
  | TikTok | `user_data*.json` (any section wrapper) or the TXT lists (`Like List.txt`, `Favorite Videos.txt`) | link, date, `Likes`/`Favorites` |
  | YouTube (Takeout) | `playlists/*-videos.csv` (current and older layouts, `Watch later` included); `watch-history.json` or `.html` (Takeout's default) only on request | video, playlist name, added date; history as days (below) |
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
- **Indexed, not consolidated (owner ruling 2026-10-18).** A save from a platform's saved list stays in Saved with its
  metadata (title, channel, playlist or collection, date, its media page) and its episode lands already read —
  `processed: true`, `processed_by: index` — so no model reads it, item by item or at all (*Indexed, not
  consolidated* below). The YouTube oEmbed lookup at import is unchanged: it is the person's own click (the drop,
  the upload, `cicada import`), so the unattended-fetch gate does not apply, and it is bounded — one call per new
  video (a duplicate is never looked up), 8 at a time, 5 s each, 2,000 per slice; Instagram, LinkedIn, Reddit and X
  rows are never fetched (walled, or `defer_enrich`), and Sleep's link reads skip YouTube and every walled host.
  Pinterest's export is a browse-your-content HTML archive with no stable structure, so Pinterest stays with its
  connector.

**Watch history (G71, owner 2026-10-16: "my watch later videos from youtube and maybe also sync history").** YouTube's
API gives no one Watch later or watch history, so there are three doors, and they converge on one record.
- **Watch later is a save; history is experience.** Watch later rows are saves where saved videos go (`media_ingestor`,
  folder `Watch later`, origin `youtube-playlist`). History is aggregated, never dumped (G94): `watch_history` writes
  **one episode per platform per day** — `source_id` `watch-history:<platform>:<YYYY-MM-DD>`, `source: watch-history`,
  origin `youtube-history` (TikTok's browsing history, `tiktok-history`, rides the same writer), an id dated the day
  watched — listing that day's videos in order with their local times, titles and channels, through the one stager,
  **already read** (`processed_by: index`; *Indexed, not consolidated* below). Saved never sees a history row, and an
  import of years of history is that many days, which the preview says before Confirm ("N watched videos over D
  days"). Each month the history touches gets one more episode, its summary (`watch_history.rollup`, below).
- **One identity.** A video is `media_ingestor.url_hash` of its canonical URL — the key Watch later, bookmarks and
  Takeout playlists share — so `youtu.be/<id>`, `/shorts/<id>` and `watch?v=<id>&t=…` are one video. Within a day a
  video is one row (`watched` in frontmatter: `url, title, channel, times, via, seen`); a watch less than 30 minutes
  after the last one kept is the same watch, a later one a re-watch whose time is added. **`times` is derived, every
  merge, from `seen`** — every instant a door reported, distinct, the earliest 48 (`MAX_SEEN`) — so the order doors
  arrive in never changes a day (owner 2026-10-16, from the backend hunt: thinning only the kept times made Chrome,
  then Takeout, then Chrome again report a phantom re-watch). A door that knows only the day (the agent reading the
  history page, TikTok's export) merges into the row a timed door wrote. A re-read writes nothing (the stager's hash);
  a day changes only when its words do, so `via` names the doors that wrote its words — except `seen`, which a day
  whose words did not move still records in its frontmatter alone (no re-queue).
- **Door 1, Takeout (once).** `watch-history.json` and the default `watch-history.html` (read per activity entry; an ad,
  a removed video or a post is left out; the HTML's date is read in this machine's zone, the English layout only), only
  with `include_history`. Before this a dropped `watch-history.html` went to the bookmark parser and every watched video
  and channel link became a bookmark. Localized Takeout names (a non-English account's folder and file names) are not
  recognised yet.
- **Door 2, Chrome's history (live, the app).** Off by default, its own switch under Chrome in Integrations → Browsers
  (`cicada.browserWatch.enabled.chrome-youtube-history`). The app copies Chrome's `History` (locked while Chrome runs;
  never opened in place or written) into a private temporary folder, opens the copy read-only, and runs one query that
  names YouTube video pages only (`ChromeWatchHistoryReader.visitsSQL`, the SQL `test_watch_history.py` runs on a
  synthetic History), past a per-bank visit-id cursor; only link, title and visit time leave the app.
  `POST /sources/watch-history/sync` re-checks every row, keeps YouTube videos only, writes the days (capture: episodes
  only, ungated) and commits once as `user` (trigger `capture/watch-history`); 413 past 20,000 visits, 422 for another
  browser or profile, 409 in a demo bank. Channel `chrome-youtube-history` (its count is the videos memory holds). It
  reads on turning on, launch, a bank switch, Sync now and every 10 minutes when the file's size or time moved (a stat).
- **Door 3, the person's own agent (`mcp.md`, "YouTube lists").** It reads Watch later and the history page in the
  person's signed-in browser and records through `cicada_record_youtube_list`: Watch later rows as saves (a video
  already saved is a duplicate), history rows as days (the page's day).
- **Door 4, activity traces (G218, below).** A YouTube page an allowed Chromium browser showed in front for at least 20 s
  is a watch with `via: traces` and `dwell_s` (the day's seconds in front for that video, counted from the traces
  store; the larger figure wins, so any arrival order gives the same day; the body says "N min on screen"). It covers
  what door 2 misses: dwell, and a video watched with history off.
- No model runs, nothing is fetched (titles and times come from the doors), every title is scrubbed (writer
  `watch-history`).

**Activity traces (G218, ruling 38, owner 2026-10-23: "if right now I'm watching a YouTube video I didn't save or
mention, I can in the future ask what that video was and get it from memory").** What was in front of the person on
this Mac, with times — off by default, on only after the consent sheet (Sources → Traces), never ticked in onboarding.
- **The app is the only capturer** (`app/CicadaApp/Sources/CicadaApp/Services/Traces/`, `TraceRecorder`): it alone
  holds Accessibility and Screen Recording; the backend has neither and never will. Every OS call is behind a seam
  (`TraceSystem.swift`) and every permission is read by preflight only (`AXIsProcessTrusted`,
  `CGPreflightScreenCaptureAccess`, `AEDeterminePermissionToAutomateTarget(askUserIfNeeded: false)`); asking happens
  only on the person's click (`PermissionDragHelper`, and the browser's own Automation prompt when they allow a browser).
- **A focus span** `{id, start, end, bundle_id, app, title?, url?}` per stretch of one app/window/page in front. A look
  every 5 s and on every app activation; a span ends on a change, idle ≥ 2 min (cut where input stopped), the locked
  screen, secure input (a password field anywhere), a pause or an exclusion; under 2 s it is a flicker and dropped.
  Titles come from Accessibility, never for chat and mail apps unless the person turns them on per app; a URL and a tab
  title only from an allowed Chromium browser's front tab whose window `mode` is not incognito. A browser whose tab
  cannot be verified (Safari, Firefox, Arc; Chromium without Automation) keeps its name and times only — and "browser"
  means any app Launch Services registers to open `https:` links (`TraceBrowserRegistry`), not only the named ones, so
  an unlisted beta or fork fails closed (review of #456, B3).
- **Screenshots** (on with traces; their own switch; Screen Recording): event-driven — on a new span, at most one a
  minute (`TraceFrameCadence.minGap` 60 s, so an alt-tab burst costs one frame), then one every 5 min while the same
  span continues (`steadyInterval`); never while idle, locked or paused; only the **front window** of an app that may be
  described (never the whole display, so nothing behind it — a private window included — is taken). The front window
  is the first normal-layer window of that app in the window server's front-to-back list
  (`CGWindowListCopyWindowInfo(.optionOnScreenOnly)`, `TraceWindowPick`), matched by id in ScreenCaptureKit — whose own
  list is unordered and counts covered windows as on screen — and the frame is dropped when, after capture, another app
  is in front or a browser's front tab changed or turned private (`TraceRecorder.stillShows`, B2). Downscaled to 1280
  px at JPEG 0.6 (~100–200 KB; a heavy day ≤ 480 frames ≈ 70 MB, seven days ≈ 0.5 GB worst case). Text is recognized
  **on this Mac** with Vision after capture, off the tick (a queue of at most 3 frames), and posted with the frame.
- **Nothing, not even a title,** while off or paused (Pause from the menu bar: an hour, until tomorrow, until resumed),
  locked, in a password field, for an excluded app or site, a password manager, Cicada itself or a private window.
- **Nothing on the app's disk.** Spans wait in memory (≤ 500, posted once a minute) and frames in a queue of three;
  with the backend away they wait and the oldest go, never spilled to a file (`ReaderOutbox` never queues a traces
  route). On a server connection (G181) nothing is recorded: `TraceBackendGate` sends traces to This Mac's backend only.
- **The backend parses and keeps** (`POST /sources/traces/sync`, `POST /sources/traces/frames`): `trace_store` re-applies
  the policy and seals each record outside every bank (`storage.md`, "Activity traces"); `trace_memory` promotes only
  what the person's switches allow — YouTube views into the watch history (door 4 above) and, behind "Keep a daily
  summary in memory", a counted day summary (`source: traces-day`, index-only unless "Let Sleep learn from the
  summary"). Both wait until a span is past the 15-minute forget window (B1). **No model at capture**; a model reads
  traces only through that opt-in summary. A trace is not a mention.
- **Agents:** no MCP tool, no Ask leg and no CLI read the store in v1 — Ask's raw-row lookup would put rows in front of
  a model, which the rail forbids; "what was that video at 15:20" is answered through the watched day Ask and recall
  already read. Remote doors and other devices never see traces.

**Indexed, not consolidated (owner ruling 2026-10-18; G71, G94).** The owner's Takeout with history brought 45,879
watches as 2,532 day episodes and 3,156 playlist saves, and every one was queued for a full Stage-1 read — hours of
plan usage to fill the graph with channel and video pages and "who is X" questions. Owner: "maybe overanalyzing the
watch history is too much … Maybe just have it there and then maybe the metadata has it as embeddings or something."
So watch history and list saves are a record to look up, never a conversation to read:
- **What is index-only — one predicate, `history_index.kind`.** A watched day (`source: watch-history`), a month's
  summary (`source: watch-history-month`), and a save from a platform's saved list: origin `youtube-playlist` (a
  Takeout playlist, Watch later included, or the agent's read of Watch later), `instagram-saved`, `tiktok-saved`,
  `x-likes`, `linkedin-saved`, and `reddit-saved` / `x-bookmarks` only under the folder the export reader names
  (`Saved posts`/`Saved comments`, `Bookmarks`) — the Reddit and X connectors share those origins under other
  folders and are read as before. A browser bookmark, a single URL save and a save carrying the person's own note
  keep today's behaviour (no list door carries a note; one that did is stamped `has_note` and queued). **The
  person's words always win:** a list save whose frontmatter carries `saved_why`, `saved_why_earlier` or `has_note`
  is never index-only, so when they later say why they saved it (`saved_why.attach`/`edit` — e.g. a bookmark of a
  video already in their imported Watch later) or a repeat Telegram `/save` adds a reason
  (`history_index.mark_person_words`: `has_note`, re-queued when the index had read it), it goes back to the model;
  and `retire` never flips a queued list save whose body holds such a section (`## Why it was saved`, `## Saved
  because`, `## User note`) — it stamps it theirs instead.
- **Read without a model.** Capture writes them read (`processed: true`, `processed_by: index`: the stager's
  `queue_for_sleep=False`, or `media_ingestor.write_media_episode`). `history_index.waits_for_model` is the one
  "waiting for Sleep" predicate — the drain's freeze and its waiting map, the one-batch cycle, `/status`'s
  `unprocessed`, the state queue depth, sleep debt, a paused run's remaining ids — so an index-only episode never
  enters a model batch, a frozen list or a run's progress. **A bank that imported before the ruling** is handled by
  Sleep without re-import: at the start of every run that holds the bank (drain, one-batch cycle, the scheduler's
  tail-only run), before anything is frozen, `sleep_cycle._index_without_model_safely` marks every queued
  index-only episode read (`history_index.retire`, under the episode lock, re-checked before it flips) and writes
  the month summaries, in `cicada` commits of at most 500 files (`Indexed without a model <date>`, manifest lines
  `episodes/<id>.md: indexed (source: n/a, trigger: sleep/index)`, no engine trailer); a file dirty before it ran
  keeps its own writer and is skipped (it stays out of every batch meanwhile); a failed commit restores what it
  wrote. Measure first with `api/.venv/bin/python -m api.scripts.history_index_dry_run --bank <path>` (counts only,
  writes nothing: waiting, for the model, index-only by kind and origin, months against summaries).
- **The month summary is the signal, counted with no model** (`watch_history.rollup`, one episode per platform per
  month, `source_id` `watch-history-month:<platform>:<YYYY-MM>`, through the stager, read by the index): how many
  videos over how many days, the channels watched most (videos and days), the channels come back to across
  different ISO weeks, the videos watched on more than one day, and each day's count. Deterministic — the same days
  give the same words whichever order the doors brought them — and rewritten only when a day's words moved (the
  stager's hash). The import doors write the months they touch; Sleep writes any a bank lacks.
- **Found by lookup.** The files stay in `episodes/`: the lexical index covers every episode, and the episode
  vectors — synced at the end of a model batch, which these never reach — are synced by the tail's
  `_embed_indexed_episodes_safely` whenever an index-only episode is newer than the vector index (incremental by
  content hash; with the model the table holds; a bank with no vector index waits for its first). Recall's excerpts
  and search find a day or a month by its titles and channels; **Ask** reads the record for a question about
  watching (`watch_history.lookup`: a range — this/last year, a named year, since or between, the last N days, ever,
  "the most", "when did I first/last watch" — answers with a table counted from the watched days at read, no model
  (`watch_history.summarize`, bounded whatever the range; `mcp.md`); a named month with its summary; otherwise the
  watched videos whose title or channel holds the question's words, whole words, dated, the newest 40; only for a
  caller with the person's `sources`, and the answer may rest on it with no page retrieved); the **timeline** counts a
  watched day on its own day ("Watched N video(s) on YouTube") and never lists a day or a month as a capture.
- **A watched day is not a mention (decided 2026-10-18).** A channel page is never written by history: no claim, no
  `source_episodes`, no `last_referenced`, no lift, no decay-clock move, no page minted, no inbox question. Why:
  decay counts *conversations* (`decay_policy.conversations`) and a watch is not one — like a memory export entry,
  it is a record the platform kept, not the person's words; a watch is often autoplay or background; and at 45k
  watches, up to 400 a day, any page sharing a channel's name would be held at the repeat floor for good, which
  would make "absence of mention is a signal" meaningless for it. What the page gains instead is read-time and
  derived: `cicada_recall_detail` on a page whose name or alias IS a channel in the history (exact, case and spacing
  folded, never fuzzy) appends one line — videos, days, first and last day — computed from the days' frontmatter
  (`watch_history.channel_line`, cached in memory per change of the day files), never stored.

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

#### An agent's own memory notes (ruling 43, 2026-10-27)

Owner: "yes 100% cicada can read claude memory notes." Claude Code keeps auto-memory notes per project —
`~/.claude/projects/<project>/memory/*.md`, each with a YAML head (`name`, `description`, and `type`,
`originSessionId`, `modified` at the top level or under `metadata`) — plus a `MEMORY.md` index. They are agent-written,
curated summaries, often a cleaner record than the raw turns. The transcripts beside them keep their own rail.

- **Who reads: the harness's own hook.** `api/hooks/memory_notes.py` (stdlib, run by path) reads every project's
  `memory/*.md` on the machine where they live and posts their bytes to `POST /capture/agent-memory`; the backend parses
  bytes (`api/services/agent_memory_notes.py`) and opens no path for this source. Why not the backend: its one read
  under `~/.claude` stays the validated transcript read, and a client of a server elsewhere (ruling 28) or a headless
  server could not reach the notes anyway. Why not the app: Linux and a plugin-only install have none. The hook fires
  inside a session, which is when notes change. Only `<project>/memory/*.md` regular files are read — no symlink at
  any level, no `.jsonl`, nothing over 256 KB; `$CLAUDE_CONFIG_DIR/projects` when the harness sets one.
- **When.** After a Claude Code `Stop` or `PreCompact` (never `SessionEnd`, whose time is the person's exit) the
  capture hook stats every note and compares a fingerprint (each note's path, mtime and size) with the last post that
  landed (`$CICADA_HOME/state/agent-memory-notes.json`). Only when a note changed, appeared or went away, the server
  changed, or an hour passed (a bank switch, the switch turned back on) does it start a detached `--sweep` child, so the
  harness never waits; a lock keeps two sessions from sweeping at once. The first firing after install has no
  fingerprint, so it back-fills every note once; every later post is idempotent. A post that does not land is not
  spooled: the fingerprint stays, and the next firing sends again. One `capture.log` line per sweep: counts only.
- **The post** is a full snapshot (`complete: true`), newest first, at most 2,000 notes and 8 MB of note text
  (`request_limits`: 12 MB); past either, or with any note skipped rather than read (a symlink, over 256 KB, unreadable),
  it is sent incomplete and tombstones nothing. On a client it goes to the
  server with this device's token, and each device's notes are keyed under its own id
  (`agent-memory:<harness>:<device>:<project>/<file>`, `local` for the server's own token), so two machines never
  tombstone each other's.
- **The episode.** One per note through `episode_staging`: an edit updates it in place with `processed: false`; a note
  missing from a complete post is tombstoned (`source_deleted_at`), never unlinked, and cleared if it returns; the body
  is scrubbed (writer `agent-memory`); a demo bank answers 409 (`refuse_capture_into_demo`). `source: agent-memory`,
  `origin` and `harness` the harness. The body is one `assistant:` turn (the description, then the note) and the
  episode declares **`evidence_kind: assistant`** — the ruling-32 relay precedent: stored, searchable and read by Sleep,
  never the person's own words (not promotion's own-words rung, not ruling 29's settling; a claim resting on it never
  closes one resting on theirs, `inbox_tend.may_close`). `timestamp` is the note's own `modified` (else the file's
  mtime), `received_at` is stamped by `create_episode` (ruling 39); an edit moves `timestamp` in place
  (`EpisodeDraft.redate`). `agent_memory: {project, file, type, description}` carries the head.
- **Which agent and session.** `origin_session_id` is the note's `originSessionId`; `origin_episode` is that session's
  captured episode (`capture_kind: transcript`) when the bank holds it — linked on a later sync, frontmatter only, once
  the session lands after the note. Never `session_id`: that key means the episode IS the session (G104).
- **How Sleep reads it.** `episode_time.UNTIMED_SOURCES` includes `agent-memory`: a note's date is when the summary was
  last edited, not when anything in it came up — the same rule as a chat export's memory entry — so it is no mention for
  decay and never a page's activity; its facts are kept, and the session that wrote it is captured on its own. Stage 1
  prepends the memory-summary note (`entity_extractor.MEMORY_SOURCES`): older, lower trust, prefer a conversation's
  newer statement. A note's value claims are dated by the note, so newer conversation evidence closes them, never the
  reverse. **Not a conversation of its own:** promotion's "2+ conversations" (Stage 2, every rung that counts, the
  pending store's `heard_in` included) and a skill's (`skill_grounding`) count `promotion.conversation_keys` — a
  captured session is `session:<id>`, a note is its `origin_session_id`'s session (else its `origin_episode`'s key), a
  note with neither counts as none — so a session and its notes, two notes of one session, or a note and its index
  never make two. `heard_in` keeps the raw episode ids: they are the page's source credits.
- **The index.** `MEMORY.md` is mostly one link per note, each captured on its own; a line that links to a note file
  is dropped (its note says it, or the note was deleted and the pointer is stale), and an index with nothing else is no
  episode.
- **The switch.** `sources/agent_memory.json` per memory, on unless the person turned it off (`GET`/`PUT
  /capture/agent-memory/settings`; Settings → Privacy, "Your agents' notes"). Off, the route answers `{"status": "off"}`
  and stores nothing; episodes already captured stay.
- **Other harnesses.** Codex keeps a global (not per-project) `~/.codex/memories/` — a `MEMORY.md`, a
  `memory_summary.md`, `raw_memories.md` and `rollout_summaries/*.md`, itself a git repository. Not read yet: the
  `capture --harness codex` hook would need the same reader pointed there, with its own head format.

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
| Claude on the web and phone, ChatGPT, Grok | none; remote connector (G135) | — | Every turn its model relays through `cicada_capture_turns` (ruling 32, below), stored as relayed; an export upgrades it |
| Windsurf (Cascade) | `pre_user_prompt`, `post_cascade_response` in `~/.codeium/windsurf/hooks.json` | `user_prompt`; `response`; `trajectory_id`, `execution_id` | Not yet: the same shape as Cursor, so it is a registry and an adapter on `/capture/turn` (G197) |
| GitHub Copilot CLI | `userPromptSubmitted`, `agentStop` in `~/.copilot/hooks/` | `prompt`; the reply only inside `transcriptPath`, format undocumented | Not yet: the reply needs a transcript reader (G197) |
| OpenCode | JS/TS plugins only (`~/.config/opencode/plugins/`) | events (`message.updated`, `session.idle`) with undocumented payloads | Not yet: needs a plugin, not a command hook (G197) |
| Hermes, OpenClaw | no hooks documented | — | MCP saves only |

**Hookless apps, through the remote connector (ruling 32, owner 2026-10-19; amends G105 for apps with no hook).**
Owner: "Exports should only be a starter seed for users; the usual should always be real-time captures." claude.ai,
ChatGPT and their phone apps run no hook, so the one capture path they have depends on a model calling a tool — the
exception G105 names, taken knowingly and disclosed. The remote handshake's contract (and the tool's own description)
asks the app's model to call `cicada_capture_turns(message, previous_reply, conversation)` on every turn, before it
answers: the person's message word for word and its own previous reply word for word. The body
(`api/services/relay_capture.py`) is the per-turn writer below (`turn_capture.capture_turns(relay=…)`): the same
cleaning, scrub and caps, one episode per conversation keyed by the handle the handshake minted (a call without one
falls into the connector's day bucket), a re-sent turn `unchanged`. It is `record` scope, remote only
(`catalog.REMOTE_ONLY`), and behaves like a hook rather than a remote write: no commit of its own and no Sleep gate
(an episode written while Sleep runs is read by the next one), the demo guard and the remote write lock still apply.
**Relayed, not heard** (the coordinator's conservative default until the owner rules otherwise): the episode carries
`relay: {app, connector, channel: remote, first}` and `evidence_kind: assistant`, so its words are stored, searchable
and read by Sleep but never counted as the person's own — not for promotion's own-words rung and not for ruling 29's
settling — because a model may paraphrase. **An export upgrades it:** importing the app's export stages each
conversation through `episode_staging`; a Claude or ChatGPT conversation whose `source_id` is new and whose first
person message, cleaned the same way, matches exactly one not-yet-upgraded relayed episode of that app within two days
(`relay.first`, `turn_capture.relay_match_key`: letters and digits, case-folded, the first 400, at least 24) rewrites
that episode in place — same file and id, re-queued, `evidence_kind` and `hook_turns` dropped, `relay.upgraded_at` and
`upgraded_by` stamped — instead of adding a second copy. Two candidates, a short first message, another app or a date
too far apart upgrade nothing (a second episode, as before). A later relay into an upgraded conversation is answered
"already in Cicada from the export" and writes nothing; the next export brings its later turns.

**Per-turn capture (`api/services/turn_capture.py`, `POST /capture/turn`).** The hook posts `{harness, session_id,
messages: [{speaker, text}], turn_id?, retry?, model?, cwd?, hook_event, utc_offset_minutes?}` — one turn (Cursor) or one exchange (Gemini
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

**A session from another machine (G181 phase 2, owner ruling 2, 2026-10-16 — the transcript rail amended).** When
`CICADA_API_BASE` names a server elsewhere, the backend there cannot read the session (it never opens a path a client
names), so the session is read **on the machine where it lives, by Cicada's own extractor**, and only what the
extractor keeps crosses the wire:

- **The client's half** (`api/hooks/capture.py` → `hook_client.py` → `session_post.read_local`): the same path rules
  as the backend's own read (`transcript_capture.validate_transcript_path`: under the harness root, `.jsonl`, a regular
  file, `<session_id>.jsonl` for Claude Code, within the size cap — a stray path is refused unread, `refused:
  outside_root` in the log), the same `transcript_extract.extract` (scrub, fences, 16k/2k caps, the session cap's head,
  tail and marker; the agent's replies always kept here), then `POST /capture/session` with `{conversation,
  transcript_bytes, transcript_size, cwd, hook_event, effort, workspace, utc_offset_minutes}` and the device's token —
  never the path. `utc_offset_minutes` (ruling 34, additive: an older server ignores it, an older hook omits it and the
  server's zone decides) is this machine's UTC offset at the session's first turn (`hook_client.utc_offset_minutes`), so
  the id the server mints carries the person's day; a client's per-turn post (Cursor, Gemini CLI) carries it too.
  This is the hooks' one exception to "stdlib only": it imports Cicada's extractor from its own checkout, lazily,
  only in client mode. The extractor reads about 11 MB/s (a synthetic 27 MB transcript: 2.4 s for the whole firing),
  so a transcript over 16 MB is handed to a detached child of the same hook (`start_new_session`, its own 120 s
  budget) and the firing returns at once.
- **The server's half** (`transcript_capture.capture_posted`, `session_post.from_wire`): every field re-validated,
  every turn cleaned again (idempotent on what the extractor sent), a turn over its cap refused (`turn_over_cap`, 400 —
  never trimmed into something the extractor did not keep), the session cap re-applied, counts recomputed, replies
  dropped when this server's owner turned them off. Then `write_session` under the same `_lock` and `episode_lock`:
  one episode per session (G104), ids minted here, the same body, hash, sidecar, G110 metadata and demo redirect. The
  device id from the token is recorded as `device:`. **Superseded** uses the client's numbers: a post that read fewer
  bytes than stored while the client's file (stat'ed when it sends) holds at least that much is `superseded`; a file
  that really shrank is still captured.
- **The spool** (`hook_spool.py`, `$CICADA_HOME/spool/capture/`, 0700/0600): a post that does not land (no answer,
  401/403, 409, 5xx) is kept; 400/404/413/422 are dropped (a resend cannot fix them). Each entry names its target
  — the server's address and, once heard, the bank id a capture answer gave — and is sent only there, carrying
  `bank_id` so the server refuses it for another bank (G202; `headless.md`). A session keeps one entry per server, its
  newest (posts are cumulative); a live post that lands deletes the one for that server and bank. A successful MCP
  call or `cicada` command also flushes what waits for its server. Each firing that lands then flushes the rest,
  oldest first, inside the hook's 4 s client budget (under its registered 5 s; a SessionEnd flush never flushes), one
  flusher at a time (`flock`), refreshing a session's `transcript_size` from its file. No answer or a refused token
  (401/403) stops the flush; any other answer that is not final (a 5xx, a 409) is about that post: a session's entry
  is skipped and kept, so one stuck session never holds back the turns behind it (backend hunt, 2026-10-16). Per-turn
  posts (Cursor, Gemini CLI) are FIFO and a new turn waits behind any waiting turn (a turn that does not land holds
  the turns after it), so the episode keeps their order; Cursor's prompt hook
  never flushes (it holds the person's message). Bounded at 2,000 entries / 128 MiB, oldest dropped and counted in
  the log. The recall hooks read the same base and token; they do not spool (a read).

**After capture: the awake read (G207, ruling 36 D2, 2026-10-22).** A captured conversation is usable before Sleep
reads it, through a separate job that never runs inside the capture write. `/capture/transcript`, `/capture/session`
and `/capture/turn`, the relay (`cicada_capture_turns`) and an inline import call `awake_read.after_capture` /
`after_import` once their writer has returned. That call only queues a job on one daemon worker
(`cicada-awake-read`), keyed by bank, episode and kind, so a burst of turns debounces into one job. Only a `created`
or `updated` write queues anything. A job held back by Sleep, a re-embed or the admission is retried after
`RETRY_S` (120 s).

- **Step 0, no model** (`index_now`): `INDEX_SETTLE_S` (3 s) after the capture, the episode's passages are embedded
  into the episode table (`vector_index.index_episode_stems`). That is a targeted upsert: the same cut and model as
  the table holds, no other episode's rows touched, and a table it cannot diff (another model, another width) is
  `skipped`, never rebuilt from part of the bank. It gives way to Sleep within one chunk of `STOPPABLE_CHUNK` (64) texts (`should_stop`, review of #423), writing nothing
  of the batch and freeing the index's write lock for Sleep's own sync, and is retried after; a big import is queued in
  jobs of `IMPORT_INDEX_BATCH` (64) conversations so finished ones stay. It does not start while Sleep runs, while a search-model re-embed is
  running, waiting or due (`embedding_models.pending_switch`), with a hosted embedder (`runs_on_device`), or in a
  demo bank. The word index needs no job: it is fresh on every read (`search_index.ensure_fresh`, a 1 s TTL).
- **Step 1, the quick read** (`quick_read`): when the conversation ends. A Stop fires every turn, so "ends" means a
  `SessionEnd` flush (`ENDED_S`, 5 s), an import of at most `IMPORT_READ_MAX` (5) conversations, or `QUIET_S`
  (600 s) with no new capture; a relayed conversation has no end event and waits for the quiet window. The read is
  Stage 1's own extractor (`entity_extractor.extract(..., stage="quick_read")`), run once, with the person's engine
  resolved like a scheduled run (`resolve_settings(user_triggered=False)`, rulings 4 and 31) and its small model
  (`agent_disambiguation_model` / `codex_disambiguation_model` / `litellm_disambiguation_model`). It keeps only the
  claims whose subject is a page that exists (the pages' names and aliases, plus the owner's self-references,
  through `claim_pipeline.subject_resolver`). A name with no page is *held* in the record for Sleep's promotion,
  never minted and never parked in `pending_store` (Sleep reads the conversation itself, so nothing is counted
  twice). The output is one provisional record, `<bank>/.awake/<episode>.json` (`storage.md`). It is written under
  `write_admission.admitted`, off the event loop, never across the model call, and not at all when Sleep read the
  episode meanwhile. The same body revision is never read twice. At most `READS_PER_HOUR` (20) reads per process;
  past that a conversation waits for Sleep, which is logged. Nothing provisional writes a page, a claims fence, a
  pending line or a commit.
- **Sleep settles** (`awake_read.settle`, right after `_mark_episodes_processed`): each provisional claim of a
  retired episode is **confirmed** (the same deterministic claim id is now on its page), **corrected** (the page
  holds a claim from that conversation with the same subject and predicate) or **dropped**. The counts are logged as
  numbers only, then the record is deleted. A record whose episode was edited again stays for the run that reads
  the new revision.
- **`CICADA_AWAKE_READ`** = `off` | `index` (step 0) | `on` (steps 0 and 1). When unset: step 0, plus step 1 when
  `awake_read.QUICK_READ_DEFAULT` says so. There is no Settings switch (owner D2). The suite's conftest sets `off`.
  The default was decided by `benchmarks/awake_bench.py` (the numbers are in the PR and below).
- **Measured (2026-10-22, saga-01, Claude plan, haiku for answer, judge and quick read, 3 repeats, 12 questions;
  11 answerable only from a new conversation, 1 control):** easy set (6 new conversations): (a) today **1/12** every
  run (only the control), (b) step 0 **12/12** every run, (c) step 0 + 1 **12/12** every run. Hard variant (the same
  plus 30 unslept distractors): (a) 1, 1, 1; (b) 12, 12, 12; (c) 12, 12, 12, and 12, 12, 12 again on the final ranking of the provisional block. Today's recall states the stale fact on
  9–11 of 36 answers (contradicted); (b) and (c) on none. The quick read costs **1 call per conversation** (1.01 with one retry in 108), about
  10.8k input tokens (mostly Stage 1's own prompt) and 1.0–1.6k output, 6–8 s. In the verify run, Sleep's settle
  of one quick read was 3 confirmed, 1 corrected, 1 dropped. **(c) does not beat (b), so step 1 is built but off**
  (`QUICK_READ_DEFAULT = False`): step 0 alone closes the measured gap. Revisit when a set where (b) is below its
  ceiling exists (more new conversations than recall's 3 excerpt slots can hold on one topic, or questions that need
  a fact joined across conversations).

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

**`Related` reads the edges once:** `apply_changes` builds each entity's edges from `graph_edges.yaml` on the first update that needs them and reuses them for every page that pass merges (nothing in the pass writes the file); every reader of that file uses `markdown_parser.load_yaml`, the libyaml safe loader. The file grows with the claims; on a 2,000-page synthetic bank one pure-Python read cost ~3.8 s and was paid once per merged entity (`benchmarks/scale`). The hot readers (`apply_changes`, `_write_graph_edges`, `graph_builder`'s regenerate, upsert and graph read) go through `markdown_parser.load_yaml_file`, which parses the file once per change of its (inode, mtime, size) and hands each caller a private copy; `write_yaml` leaves what it wrote there, so a read straight after another step's write is a copy, not a parse (2026-10-16: a batch parsed the ~5 MB owner-scale file ~5 times at ~1.1 s each; a 3-batch synthetic drain went 147 s → 120 s). Each link's label is read against the claims on the page it starts from; `related_edges` indexes a page's claims by
object once per rebuild instead of scanning the whole fence per edge (perf 2026-10-24: the owner page's thousands of
links × thousands of claims on every owner write and every `refresh_related`; a 2-batch owner-scale drain spent 7.0 s
in `_reconcile_related`, now 1.3 s, labels identical — `test_related_labels.py` checks them against a full scan).

**One batch's page reads come from a cache (2026-10-16, owner decision 1).** Every step of a batch re-reads the pages —
~212k parses on a 3-batch owner-scale drain. `_run_batch` runs each batch inside `markdown_parser.page_cache(bank)`:
a file under that bank unchanged since its last parse is served as a copy (the frontmatter a pickle round trip, so no
caller edits another's), keyed on the file's (inode, mtime_ns, size) and, for a page whose claims overflow into a
ledger, the ledger's stamp too. Every write through `markdown_parser` drops its path from every open cache first; an
admitted writer's release (`write_admission`) empties the cache of its bank, whatever it wrote and however; a git
command that rewrites working-tree files (`checkout`, `restore`, `reset`, `stash`…) starts it over. The cache is the
batch's only — its task and the worker threads `asyncio.to_thread` starts — freed when the batch ends, never across
banks. Synthetic owner-scale drain (3 × 25, fake engine): 113.1 → 99.8 s, YAML loads 212k → 57k, the pages written
byte-identical.

**Stage 3's and Stage 4's fixed rules are a system message (2026-10-16).** The merge (`_SYNTHESIS_RULES`), the
contradiction check (`_CONTRADICTION_RULES`) and skill detection (`SKILL_DETECTION_RULES`) send their instructions as
the system message — the same bytes on every call, so an engine's prompt cache serves them — and the page, the new
information and the dates as the user message (`*_INPUT`). Every line of the one prompt each replaces is sent once, in
its order within its message (`test_stage_prompt_split.py`); the one wording change is the merge rule's "the LATER
DATE above", now "(under DATES)", since the dates arrive after it. Synthetic owner-scale batch (`sleep_tokens`): the
share of each stage's prompt characters a prompt cache can serve went merge 1 → 45 %, conflict 16 → 37 % (skills is one
call a batch: its 1k-character rules repeat across batches, not within one); ~22k characters (~5.5k tokens) of a
batch's ~360k tokens become cacheable. A 3-batch fake-engine drain wrote byte-identical pages before and after.

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
wikilink brackets and trailing punctuation) is dropped; every other sentence becomes a Key Fact (a sentence that leans
on the one before it stays joined to it: *Facts keep their context*). Nothing goes to History any more: the "Undated
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

**The legacy merge asks only for what is kept (perf report 2026-10-24, item 2).** Since only the Summary and the new
History lines were ever kept, the call now asks for exactly those: `{"summary": …, "history": ["YYYY-MM-DD: …"]}`.
It used to rewrite the whole body, about 3k output tokens a call and 26% of Sleep's model time. `_body_from_answer`
builds the page body every caller already takes: the page as it is, every section kept exactly (a hand-written one
included), with the answer's Summary and its new History lines (`adopt_rewrite`). Stage 5 and the inbox's conflict
answer read it unchanged. An answer that is not that JSON is read as a whole body, as before.

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
  note gives the conversation's own day (its `timestamp` read in the person's zone by `episode_ids.local_day`, else the
  date in its id: `source_dates.episode_day`, the same rule as a claim's `valid_from` and a page's `created` and
  `last_referenced`, ruling 34 — words said at 00:27 local are never dated the UTC day before) and today, which is fixed once per `extract()` run. For a conversation older than `OLD_AFTER_DAYS` (90),
  the note names the month and year to write it as of. An undated conversation gets no note, and nothing is guessed.
  A memory export entry gets `source_dates.summary_note` instead: its date is when the summary was edited, never a
  day to date a fact to, and nothing in it is written as current or recent (the 90-day rule does not apply).
  A message conversation (G179) also gets `entity_extractor.correspondent_note`, after the date note: whose lines are
  the person's (`user:`) and whose are the other side's — an AI agent's `assistant:` lines named by the contact
  ("Instinct"), or a person's `speaker:` lines — and that "I" in their lines is them. After the evidence locate, the
  model's own `observer` on a relationship is dropped, and a relationship whose located spans are all the other side's
  gets observer `external:<name>` (`correspondent_observer`; any other assistant's: `assistant_observer`, *Facts keep
  their context*); one the person's words also back stays `agent`
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
`cicada` commit), the tracked-source re-check (ruling 26), **the web check** (below), the connector poll, RSS/ICS
polling (opt-in via `CICADA_ALLOW_FEED_FETCH=1`), and the link enrichment backfill (which reads for the person's reason, below) — all in a clean-tree-guarded slot,
after `_finalize`'s own commit so the poll's `git add -A` sweeps only its own files. After them, unguarded (no git),
the episode vectors are synced when an index-only episode is newer than the vector index (owner ruling 2026-10-18).

**The web check (owner ruling 2026-10-16, TODO ruling 27; `sleep_cycle._web_check_safely`, `web_lookup`).** After the
run's last nudges, up to `web_check_per_run` (8; `CICADA_WEB_CHECK_PER_RUN`, 0 = off) pending questions about public
things (`web_settle.classify`, `mcp.md`) are looked up, one engine call each, and the ones the search answers are
settled with a cited claim and moved to `inbox/settled/` (features.md). **Gate:** `CICADA_ALLOW_CONNECTOR_FETCH`; a
demo bank never. **Engine (ruling 4):** resolved lazily, only when there is something to look up: a person-started run
on the Claude plan gets one `claude -p` whose ONE tool is the plan's web search (`--tools WebSearch --allowedTools
WebSearch`, `agent_engine.ALLOWED_TOOLS`); a scheduled run uses the Claude plan's search only when the person let
scheduled runs use their plan (ruling 4b, `engine_select.scheduled_plan_allowed`, on by default since 4c) — never on an explicit
`CICADA_LLM_MODE` pin alone — and a metered engine whose model litellm lists with web search uses the provider's own search
(`web_search_options: {search_context_size: low}`, one search) at its price, scheduled or not — when the person chose it
(ruling 31; a resolved Auto with no engine skips with `no_engine`) — **only on a provider
whose searches litellm reports with their query** (`web_lookup.SEARCH_REPORTED_PROVIDERS`: Anthropic, whose
`server_tool_use` comes back as a `web_search` tool call). Any other metered engine — OpenRouter (the router bills, so
`openrouter/anthropic/…` counts as OpenRouter), OpenAI's search models, Gemini, xAI — skips with `search_unreported`
before any paid call, since its searches could never pass the pinned-query check; the ChatGPT plan and a local model
get no search, so the step skips. **The lookup tier (2026-10-19):** on the Claude plan a lookup runs on the plan's
`web_check_agent_model` tier (`CICADA_WEB_CHECK_AGENT_MODEL`, default `sonnet`; empty = the person's Sleep model) for
that one call — the same plan, scheduled-plan switch and limits (`web_lookup.lookup_tier`); a metered key's model is
never changed. Measured on synthetic shapes with the person's notes: the cheap tier settled 4 of 10 public things its
own search named outright (8 of 10 with the clearer sure bar below, still inconsistent on arXiv ids), the larger tier
10 of 10; two small local places searched by name stayed unsure on both. The ledger names the model that answered: a
family alias ("sonnet") matches its own `modelUsage` key before the most-output-tokens fallback, since the search's
side-call can out-write the main turn (`agent_engine.model_from_envelope`). **The sure bar:** sure when the results
clearly describe one public thing by the name and the notes point nowhere else (a paper, book, film, quote, method,
event the results name outright); not sure when different things share the name and the notes do not say which
(usual for a small local place), when the results do not answer, or when the subject could be a private person or
someone's own file or project; the quote is the result's words as the search showed them (a search tool shows result
text, not the page). Each call is an `llm_call` of stage `web_check` in the run's own scope (a
drain's tagged with its `drain_id`), so Past reads counts it with its basis (ruling 12). **The pinned query:** the
subject's name plus at most ONE category word from a fixed list (works, tools, companies and startups, places such as
a restaurant, café, bar or clinic; a Spanish form is sent as its English word), read from Cicada's own one-line
description, else — 2026-10-19, a restaurant searched by its bare name found other things — from a mention line where
the word stands beside the name ("the restaurant <name>", "a startup called <name>", "<name>, a small café", "<name>
is a band", "<name> app"; `web_settle.context_category`, no model; only the word leaves, never the line) — never
from a description that only guesses ("possibly", "or"), never "concept", never a word the name already carries
(measured 2026-10-19: "<anime> software", "<film> concept" and "arXiv paper <id> paper" stayed unsure where the bare
names settled), never from the page's type alone, none on a question about what the thing is, none that an option label carries, a bare name
when unsure (`web_settle.query_for`) — and every search the engine reports (the stream's `tool_use` blocks; a metered
response's search tool calls) must be that query word for word, at most two; a call that searched anything else, or
nothing, settles nothing (`query_strayed`). **The local context (ruling 27a, owner 2026-10-16: "Yes, use local
context"):** the prompt also carries what Cicada knows about the subject, for the model to tell which result is the
thing the person meant — `web_settle.local_context`: the description (left out of a type question, where it is one of
the options) and up to two lines where the subject was mentioned (the item's conversation, then each option claim's
evidence span or first mention, then the page's latest conversations), ≤ 600 characters, scrubbed
(`episode_scrub`), links, addresses, handles and paths replaced, every person's name or alias in the bank (the owner's
too, and a person held without a page) replaced by "someone" — whole words, any case, accents folded ("maría" takes
"Maria"), the full name and each of its parts of 3+ letters (a joined part such as "Su-bin" as one unit), a word of the
subject's own name aside. Only a relation-shaped name keeps words (`web_settle.relation_shaped`: a relation plus an
opening article or possessive, a possessive, or "of"/"de" — "his brother <name>", "<name>'s dad", "dad of <name>"):
its articles, possessives and plain relations from one audited list that holds nobody's given name or surname
(`web_settle._NEVER_A_NAME`; re-review of #366: "Her", "Sin", "Via", "Friend", "Doctor", "Sobrino", "User" are
surnames, so in "Pa Her" or "Tom User" every part goes). A relation phrase with no name in it ("his dad") goes as its
whole phrase; a lone pronoun ("her") is no one's name. A person-typed page that is a thing is redacted by every part
like any name and counted by the census for the person to fix (`web_settle.name_shape`; over-redaction is the safe
failure); each line is cleaned whole before it is cut, so a cut never leaves half a name or a code without its cue. It is never searched for; the same engine read those conversations during Sleep. **Order:**
clarifications first, then conflicts with a mention line, then the rest — each by priority, then age
(`web_lookup.select`). **On every plan run (ruling 27b, owner 2026-10-19: "That's not what the inbox is for"):** with
the scheduled-plan switch on by default (4c), a scheduled run looks up on the plan's search too. **The sweep:** the
backlog already open gets a one-off pass the person starts — `POST /inbox/web-check?dryRun=true|false[&limit=N]
[&includeRecent=true]`, `GET /inbox/web-check` for its counts (`web_lookup.sweep`): the same eligibility, query, local
context and citation, on the engine a run the person starts would use (the connector gate reported, never applied — a
person's start is never gated); every eligible question, not eight; one lookup at a time with the model call outside any
lock, each settle under the bank's write admission and page lock with its own `Web check` commit
(`web_lookup._settle_admitted`; an edit already on the page committed apart first), undoable under "Settled by a
check"; its closing `_state.md` refresh is admitted too and skipped while Sleep holds the pages; a dry run looks up at
most 20 unless given `limit`; it stops when Sleep starts, on a plan limit, or after three engine failures in a row; 409 while Sleep, a tidy
or another sweep runs, and `/sleep/status`'s `inboxTidy` is true while it runs so an updater waits. **The dry run:**
`api/scripts/web_check_dry_run.py --bank <path> [--census | --limit N (default 20)] [--include-recent]` (`web_lookup.sweep` with
`dry_run=True`) prints counts only: the census (`web_settle.census` — per kind, how many are `public`, `repo_state`, or
stay and why: `person`, `person_context`, `private_type`, `own_settings`, `no_page` …), then, unless `--census`, the
person's engine on up to N of them (eligible, looked up, would settle, reasons by kind); it writes nothing — no settle,
no memo, no ledger row (a no-op usage sink), no commit. `--trace` (for the person's own eyes) adds, per lookup, only the
pinned query, where its category word came from, the context's line count, how many names it replaced and the outcome
(`no_search` apart from `unsure`: the engine answered without searching); `--trace-raw` adds the searches run, the
links each returned, the model and its raw reply cut to 400 characters — printed only, never written,
plus counts of how the bank's person names are redacted and how many person-typed names read as a thing
(`web_settle.person_name_census` — a page typed person that is a technique or a department is the bank's to fix). **Who the description says it is:** Stage 1's way of naming the
speaker ("the user mentioned it", "the person's") is taken out before the person cues read a page-less subject's
description (`web_settle.person_context`), and a description that says the subject is the speaker's own (built by the
user, the user's project or file, their own) keeps it home. An unsure or uncited answer settles nothing either; a type question's single option without
`others_ruled_out: true` settles nothing (`not_exclusive`), and an option the item lacks never does (`no_option`). A question looked up and left open is not looked
up again for 30 days (`$CICADA_HOME/web_check/<bank>.json`, ids and enums). A page or item someone left dirty waits. A
plan limit stops the step (the rest waits for the next run); a drain stopped at the plan's limit skips it. One commit,
`Web check <date>`, under the model that looked (`Cicada-Engine` its engine), trigger `sleep/web-check`. Every file a
settle touches is snapshotted first; a failed step or commit puts them all back, unstages them and clears their memo
rows (`web_lookup.restore`), so nothing dangles for a later `git add -A` to commit under the wrong author.

**Sleep tends the inbox (owner ruling 2026-10-17, TODO ruling 29; `sleep_cycle._tend_inbox_safely`, `inbox_tend`).**
Every batch, right after `_finalize`'s commit and still inside its write window (so no person's answer lands between
its read and its settle), Sleep: **(1)** reads the open `conflict` / `clarification` / `merge_suggestion` questions this
batch's conversations are about (the ask gate's rule over the person's own turns; at most 8 a batch, one engine call
each, stage `inbox_tend`) and settles one only when the engine copies the person's words and they are found exactly in
the person's own turn (`evidence.verify`, kind `user`) — the conversation that raised a question never answers it; and
**(2)**, once per drain (the batch that runs decay), assumes the small stuff by engine-free rules plus the duplicate
judges on at most 6 questions — duplicates, conflicts (label-only ones too, first by the person's newest words on them,
`newest_words`), label folds, fading pages — and a name said once in passing (`in_passing`, part 3) — and then, on at
most 4 questions still open (a clarification, follow-up or conflict), **(3)** looks across the whole record for the
person's own words already answering it (the page's evidence pointers plus the lexical index; located exactly in
their own turn, `said_on_record`; `features.md` has the table). Each settle goes through the person's own resolver and
commits alone as Sleep's (`Inbox settled by Sleep`, trigger `inbox/<kind>/settled:<label>`), undoable under "Settled by
Sleep"; the state projection is refreshed once after. The engine is the batch's own, so ruling 4 holds as for every
stage; a plan limit stops the tending and trips the batch's breaker, so the drain pauses as for a Stage-1 limit. A
cancel requested before the tending skips it. `inbox_settled` counts the run's settles on the wire. The one-time tidy
of an existing backlog (`POST /inbox/tidy`) is the same policy outside Sleep, each settle under write admission.

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
left. **No engine (ruling 31, owner 2026-10-19: "the defaults now are either the Claude plan or the Codex/ChatGPT
plan"):** the shipped `llm_mode` is `auto` — the Claude plan, the ChatGPT plan, a running local model — and when none
of them may read (and no API key was chosen) the resolved copy carries `no_engine_reason`; the batch stops before
Stage 1 with that sentence and its fix (reason `engine`, nothing read, nothing spent, the queue intact), and every call
built from such a copy anywhere (Ask, the link backfill, a rebuild) refuses before it is sent
(`providers.resolve_llm_fn`) — as does a call from an Auto no caller resolved (its label reads `auto`, never
`litellm`; the dedup sweep now resolves first). The sentence names the server's command too. A plan limit (`EngineThrottled`/`Exhausted`/`Overage`, the breaker tripped by a swallowed per-episode throttle, or the
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
**A provider's refusal is said in words (2026-10-17).** When a metered engine's provider refuses a call, its own text
is sorted (`engine_cause`, text first, then litellm's class names) into a spending or credit limit reached, a refused
key, an unknown model, or a rate limit, and the stop's sentence — the drain's, the paused record's and `error` — says
that cause and its fix in provider-neutral words: raise the key's limit or add credit with the provider; check the key
in Settings → Intelligence → Plans & keys; choose another engine in Settings → Intelligence, or change the model where it was set (Settings no longer edits a model id, 2026-10-22); continue later. A scheduled run that ruling 4
kept off the plan (`engine_select.SCHEDULE_DEGRADED`) also names *Scheduled runs may use my plan* in Settings → Sleep
as a fix — named, never flipped (ruling 4b). The provider's raw text never reaches the wire. A cause outranks G117's
"no engine chosen" guess (a refused key on such an install names both doors); no recognised cause keeps the generic
sentence, and Cicada's own engine errors (the plan CLIs) keep their own words.
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
selection chooses a plan (ruling 4) **only through "Scheduled runs may use my plan"** (ruling 4b, 2026-10-16:
`sleep_run_prefs.scheduled_use_plan`, machine-wide; `PUT /sleep/run-options {"scheduledUsePlan"}`, Settings → Sleep,
`cicada sleep schedule --use-plan on|off`) — **on unless the person turned it off** (ruling 4c, owner 2026-10-19: "Make
scheduled runs run on the plan by default"; an off is stored as `false` so it outlives the default, a machine that never
chose reads as on). With it on, a scheduled run
resolves exactly as one the person starts would — the Claude or the ChatGPT plan, each only when it is the chosen
engine and signed in (`engine_select.SCHEDULE_PLAN_MODES`, the switch being `SUBSCRIPTION_MODES`' only door besides
the dotfile pin) — and drains like any scheduled run; its plan-limit pause (`plan_window`, `plan_weekly`) is the
schedule's to replace once the limit has reset (the vendor's `resets_at`, else after `ENGINE_RETRY_S`), since on a
server nobody presses Continue; extra usage stays the person's, and continue-after-reset (ruling 15) still never arms
from a scheduled run. The dotfile pin keeps its one batch (ruling 16); on a metered engine it spends until the queue is empty, with no limit Cicada sets, and the engine menu and Details
say so in words. With the switch off, a plan the person chose — or Auto's plan rungs — gives a scheduled run no engine
(`SCHEDULE_DEGRADED`), never the metered key by itself (ruling 31); a key the person chose still reads; an explicit `CICADA_LLM_MODE` CLI
override also reaches the transient retry/pause policy. Such a scheduled engine pause is eligible for replacement
by a fresh unattended run only after six hours (`sleep_paused.ENGINE_RETRY_S`), rather than the next scheduler tick.

**The person's own Cursor, OpenCode and Grok (G49/G50, 2026-10-28).** Three more plan engines beside the Claude and
ChatGPT plans — `llm_mode` `cursor` / `opencode` / `grok`, engine labels `cursor-cli` / `opencode-cli` / `grok-cli`,
ledger connections `cursor-plan` / `opencode-plan` / `grok-plan` (no Plans & keys adapter) — each one headless call per
LLM call on the CLI the person installed and signed into (`cli_engines`, one `EngineSpec` per tool). All three are in
`SUBSCRIPTION_MODES`; Cursor and OpenCode are in `SCHEDULE_PLAN_MODES` (a scheduled run reaches them only through the
switch above), **Grok reads only when the person starts a read** (`SCHEDULE_USER_ONLY`, said in words) until a live
sign-in shows what a subscription call reports. **Ruling 46 (owner, 2026-10-28): Cursor, then OpenCode, close Auto's
ladder** after the two plans (`engine_select._AUTO_LADDER`, `cli_engines.AUTO_SPECS`); **Grok is never a rung**, nor a
scheduled engine, until that live sign-in. A tool is a rung only installed and signed in — OpenCode only with a GitHub
Copilot or OpenCode Go model listed — else skipped, never an error and never a key; an installed tool skipped (signed
out, only key-backed models, no answer) is named in the no-engine sentence, an absent one is not. The rungs read #494's
cached status (`cli_engines.ladder_status`): a fresh answer at once, else one background refresh for both tools at once,
waited on at most `LADDER_WAIT_S` (9 s) by a cycle and never by the Sleep page (`cli_wait=0`; its cards warm the cache);
an unknown or hung tool (`Status.timed_out`) is skipped for that run in words. The handshake's Now line and the cards'
POWERS read the cache only (`cached_connected`). A landing says what runs — Cursor's with its billing note
(`CURSOR_USAGE_NOTE`) — on the Sleep page's line and in the run's detail (`engine_select.run_detail`, the landing
sentence before the pre-flight's line). **No MCP context (review of #494):** Grok runs with every Claude/Cursor compatibility cell off
(`GROK_{CLAUDE,CURSOR}_{MCPS,HOOKS,RULES,SKILLS,AGENTS}_ENABLED=false`, `GROK_MANAGED_MCPS_ENABLED=false`); OpenCode gets
Cicada's own `OPENCODE_CONFIG_CONTENT` (set after the scrub) turning off every MCP server its global config names, Cicada
included; Cursor has no documented run-wide switch, so it never gets `--approve-mcps` and its `Mcp(*:*)` calls are
denied. The belt for all three (and Grok's own `config.toml` servers, which nothing turns off): every child carries
`CICADA_ENGINE_SPAWN=1`, and Cicada's MCP server started under it offers no instructions, no tools and no "agent reached
Cicada" row (`mcp/server.py` `in_engine_spawn`). Cicada never installs, signs in or reads a
tool's credentials; the variables that would move a tool off its sign-in (`CURSOR_API_KEY`, `XAI_API_KEY`, an inline
`OPENCODE_CONFIG_CONTENT`/`OPENCODE_PERMISSION`) are stripped (`base.CLI_ENGINE_OVERRIDE_ENV`), and `CICADA_CAPTURE=off`
/ `CICADA_RECALL=off` ride every child, so Cicada's own Cursor and Gemini CLI hooks, and the Claude Code hooks Grok also
runs, stay silent. **No tools:** every call runs in a fresh empty directory under `$CICADA_HOME/engine-scratch/<mode>`,
deleted after; Cursor `agent -p --output-format json --mode ask --trust --workspace <dir>` without `--force`, plus a
deny-all `.cursor/cli.json`; OpenCode `opencode run --format json --pure --dir <dir> -m <provider/model> --file
<request>` with `OPENCODE_PERMISSION={"*":"deny"}` and no Claude Code or project config; Grok `grok --prompt-file
<request> --output-format json --permission-mode dontAsk` with every tool kind denied, `--disable-web-search
--no-subagents --no-plan --disallowed-tools Agent`. **Plan, not metered:** OpenCode counts only GitHub Copilot and
OpenCode Go (`OPENCODE_PLAN_PROVIDERS`); a model on any other provider is refused before a call (the PUT answers 422,
the pre-flight and the call refuse in words, "Nothing was read"). Cursor bills past its included usage only if the
person turned that on in their Cursor account — said on the card (`billingNote`). Grok runs only xAI's built-in
`grok-…` ids (a `config.toml` model with its own provider or key outranks the sign-in, so anything else is refused and
never listed; `config.toml` is never read), and OpenCode and Grok always get an explicit model — never the tool's own
config default. What remains is a key override set on a built-in id in Grok's own settings, said on the card; a reply
carrying a charged cost stops the run (`EngineOverage`) — unverified until a live sign-in shows whether subscription
calls ever report one (the docs say an absent cost never proves a free call). **Pre-flight** (`cli_engines.preflight`, each batch): installed, signed
in (Cursor `agent status`; OpenCode: `opencode models` lists a plan model; Grok `grok models`), the saved model still
offered — a model the tool no longer lists stops the run in words, never swapped — and OpenCode's unpicked model is the
first plan model it lists (Grok's too). Usage and rate-limit words are `EngineThrottled` (the breaker, a pause); signed-out words name
the exact sign-in command. The model a tool reports (Grok's `modelUsage`, OpenCode's `step_finish`) is what the
`Cicada-Author` trailer and the ledger carry; none reported and none chosen is omitted, never guessed. The reserve line
reads only engines that report windows (`RESERVE_ENGINES`: Claude, ChatGPT). Antigravity is not an engine: Google's FAQ
says wrapping `agy` inside another application "is not supported under consumer plans", and Gemini CLI stopped serving
personal Google sign-ins on 2026-06-18.
**Before the freeze:** every run that holds the bank first marks what is only ever looked up as read — watch
history, month summaries and list saves (*Indexed, not consolidated*, above) — so they are never frozen, batched or
counted as read by the model. **Once per drain, not per batch:** temporal decay (both engines,
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
- **Paused is a fact about a run, not a state of Sleep.** A run that stops with conversations still waiting (Pause = the cancel path, a plan limit, the engine going away, the reserve line, or a restart) leaves a `paused` record in its sidecar (`sleep_paused`); `status` stays `idle`, `is_writing()` is false, nothing is held. `POST /sleep/trigger {"continue": true}` rebuilds the drain from it (same run id, the frozen list minus what is filed, the counters carried, batch numbering from what was committed); **a no-body trigger stays a fresh run and clears it** (the documented curl); `POST /sleep/run/end` forgets it (409 while reading); `POST /sleep/parked/retry` unparks and reads exactly those ids (409 while running or paused). **The scheduler reads nothing while a paused run waits** — except a *scheduled* run's pause no person chose: a `restart`, an `engine` pause at least 6 hours old, or (ruling 4b) a plan-limit pause whose limit has reset, is ended (Past nights says `ended`) and replaced by a fresh unattended drain (`sleep_paused.schedule_may_replace`) — it still runs the engine-free tail (`run(tail_only=True)`: expiry, follow-ups, the state refresh, the polls, the link backfill; the after-import probe at most once a day), and the paused record stays on the wire meanwhile — and counts *readable* conversations (`sleep_debt`'s `readableCount` = waiting minus `parkedCount`). `sync_service`'s `sleep` component and the SSE event carry the pause, so the app hears it. Only the Sleep page continues a paused run (the app's doors route to it; the server stays permissive). **A paused run is not in flight**: the record, its sentence, an armed continue-after-reset and the queue all outlive a backend restart (`recover_after_restart` touches only a `running` sidecar; `test_a_paused_record_outlives_a_restart`), so the dev `scripts/dev/auto-update.sh` and the release updater install under it, deferring only for a cycle `running` (a paused run's upkeep tail included), `writing: true` or a drain still reading (2026-10-17: deferring on any `paused` block held every update from a failed 03:00 run until 15:09).
- **Honest live progress** on `drain` and the SSE event (every key optional): `startedBy`, `firstRun`, `calls` (each spawned engine call; only grows, a discarded batch's included), `elapsedMs`/`pausedMs` (measured, never a remaining time), `batchState`, `stages` (Read/Sort/Decide fill only from finished work; Notice and File carry no number), `byOrigin` (frozen = filed + read + waiting + couldNotBeRead + parked + skipped), a live `arrivedSince`, `ownerPage` beliefs, `reserve`. `GET /sleep/queue` serves the per-conversation rows from frontmatter only (≤ 200). Neither it nor `GET /sleep/run-options` / `GET /sleep/runs/{id}` is a Store domain (no `VersionVector` mapping; in-memory caches in the app, emptied on a bank switch).
- **The reserve is a soft stop** (`sleep_reserve`): Stage 1 stops *starting* reads once a plan window is past the line, what was read is filed, the rest is not an attempt; the run pauses with "Paused to leave room in your plan." A line, not a guarantee: overshoot is unmeasured, a window the engine never reports is served `enforced: false`, and the ChatGPT plan is read from the pre-flight snapshot each batch already takes. Off leaves the Claude rung's own R-E12 90% stop; a reserve lifts it for that run.
- **Continue after a plan reset** (`sleep_autocontinue`, ruling 15): a one-shot job per bank (`job_id`; a trigger or End in one bank never drops another's, and a bank's activation re-arms its own), for a run the person started, only after a 5-hour window (or the reserve on one, or extra usage) that gave a reset time, at most twice, within 36 hours, same engine, never weekly, never scheduled; `run(continue_from=…)` is called from the Continue route and this module only.
- **Past nights groups by run:** history rows carry `drainId`/`batch`/`batches` and a `run` summary (from `runs.json`; a paused run dropped without a Continue — a fresh Consolidate, an empty Continue, End, the schedule's replacement — is `ended` with its pause closed, and a restart records its open `restart` pause), and `GET /sleep/runs/{id}` (ETag) sums by `refs.drain_id` over every `llm_call` — models with the ledger's own stage names, plan windows per batch (a reset between two batches is never averaged away), pages touched. `SleepEnginePreview.billing` (`plan|charged|local`) lets the app word the spend without naming a provider.

**Link summaries read for the person's reason (vision item 1, 2026-10-28).** When the person said why they saved a link (`saved_why.reason_of`), Stage 5.57's summary and the backfill's are asked to lead with what the page shows or says about that, about the page only (never "the user" or the reason itself), at most two sentences (`link_enrichment._SAVED_WHY`, read by `_summarize_excerpt`; 160 output tokens instead of 100 when a reason rides). A page described before its reason was given is read again **once** for it, as the backfill's third tier after reuse and fetch and inside the same cap (`needs_reason_read`; not a page the person's own agent read): the new `describes` claim supersedes the old one (history kept), Cicada's own summary gives way, a description the page itself gave stays, and the page is stamped `read_for` (the reason's `at`, or its words' hash) whatever the fetch answered, so a reason costs one read; a new reason earns one more. An engine failure leaves the page unstamped. Measured on a copy of the owner's bank (8,541 episodes, 4,027 saved-link pages): 12 saves carry a reason, 11 already described; the haiku dry run read 9 (2 pages returned no text); of the 8 whose reason names something specific, the new description speaks to it on 6, the old one on 2 (2 more in part), and none mentions the person; `scan_backfill` +0.05 s (0.57 → 0.62 s median). **Stage 1 is unchanged:** a saved link's episode already holds its reason section, and a before/after eval on the same 12 saves (haiku, the plan) found the reason recorded faithfully in 12 of 12 without a note; a 130-token note invented one reason and dropped another, an 89-token one changed nothing measurable, so neither shipped. A reason adds no promotion weight of its own: a marker-less save already reads as the person's writing in `promotion.exchanges`, with or without one (G191 row).

**Disclosed asymmetries (not fixed here):** Stage 5.57's `recommends` person credit reads only the last batch's changes;
Home's "Last read" shows the last batch's pages. Details' last-cycle figures — "Last cycle took", "Last engine" and "What it cost" — come from one record the backend finds, `/sleep/status`'s `lastFinishedCycle` (`last_cycle.latest`, 2026-10-16): it walks the newest 200 "Sleep cycle" commits (trailers only, decay skipped) and takes the first that is a plain cycle or a batch of a run whose summary says it ended (`finished | failed | ended`); a batch of a run still running or paused is skipped — and so is any commit since such a run began whose ledger row is missing — so a long or paused drain filling every history row the app holds no longer hides the cycle before it. A drain is one cycle: the run's `read_ms`, its commits' `Cicada-Engine`, and its cost summed by `drain_id` over every call (a discarded batch's included), the ledger window opening at the chosen commit's day and widening only back to the run's own start. The miss path runs off the event loop; cached per (bank, HEAD, runs-file stamp); a chosen commit with no ledger row is retried after 5 s only while it is under 5 minutes old (a demo or pre-ledger bank is not recomputed per poll). `null` = none in the walk; the app falls back to the newest history row's own figures, titled "last batch", only when the key is absent (an older backend). A plan run's line is its window's before → after with no price. The status's in-memory `lastEngine` (reset at every run start) no longer feeds the row; the page rereads status and history on every visit and when the Store's newest Sleep time or Sleep's state moves — at most every 30 s while a run reads (`SleepPageRefresh`). **Pause and a hard plan rejection mid-batch still discard the batch in progress** (no journal of paid answers — the tail must say "the part it was reading is read again", never "read and kept"). A scheduled drain pins its bank for hours (the same 409 as any run) and, on a metered engine, has no ceiling Cicada sets. The **app's own** Projects and Backlog controls key off `writing` (`ProjectWriteGate`; `/status` and the SSE `sleep` event carry it, and the sync version's `sleep` component moves when it flips), so they are disabled, saying "Sleep is running", only inside a batch's write window and come back between batches; an older backend without the field falls back to `running`. After a stop, Details says how many stay filed and never a batch count (the wire's `batches` is the plan); a cancelled or plan-paused strip and tail retire with the backend's cancel window and the vendor's reset time respectively. A drain on a consumer plan is the largest plan spend Cicada makes; the "leave room" reserve covers every window the engine reports (the 5-hour and the weekly one alike), is a line and not a guarantee, and a window the engine never reports is served `enforced: false`.

### Entity promotion
Entities are NOT extracted from every mention — that pollutes the graph. First mention stays in the
vector index only; promotion needs **2+ separate conversations**, OR substantive discussion (>3
exchanges) in one, OR an explicit link to an existing high-confidence entity.

**A project is born from a repository or the person's words, never from this rule (ruling 36 D4, G141,
2026-10-22; `api/services/project_birth.py`).** For a `project` mention the rungs below do not apply. Stage 1 computes,
on the conversation it read (no model), a `project_birth` record and drops any the model's JSON carried:
- **repo** — the episode is a harness session the hook observed in a git checkout (`workspace_identity` with a
  `family_hash`, bound to the stored `project_dir` by its `cwd_hash`; G110 D2), and the mention's name or an alias,
  folded (case, accents, punctuation), is the checkout's folder name: the last component of `project_dir`, or the one
  before a `.worktrees`/`worktrees` folder. Read from the two stored strings only — the backend never opens, stats or
  runs git in the path, and **no remote is read** (D2 allows the hook only the `rev-parse` pair, so the remote the
  ruling's text mentions is not available; the folder name stands in for it, disclosed).
- **words** — one sentence of a person's own turn (`user`, or a meeting `speaker`) names it within five words of
  *project* (or *proyecto*, *projet*, *Projekt*, *progetto*, *projeto*, plurals), inside one clause (no comma, colon,
  semicolon or parenthesis between them — except one colon after the project word's clause that introduces the name,
  "New project with Teo: fernpost", W3 2026-10-22), outside a recorded gap; kept as a span `{start, end, hash, kind}` into the
  episode, never a copy (G118). A name that itself contains "project" does not call itself one.
Stage 2 promotes a `project` exactly when one of the batch's extractions of that name carries a record (the oldest
conversation's wins); everything else is never a project page.
**The fallback page (owner 2026-10-23, amends D4; `entity_resolver._settle_unborn`).** A project mention with no record
and no match is decided after the per-name loop, so the thing shows in the app without breaking D4. Each such name is
weighed by the judge — never by an alias alone — against what it may already be: the project pages on disk and born this
batch, the fallback pages, this batch's other unborn names and the project lines an earlier batch parked
(`_unborn_candidates`: what shares a conversation first, then a word or alias, then the rest, latest first, at most 12;
a pair sharing no word gets a note saying that is no lead either way). "Same" as a page makes it that page's update; the
names judged the same as each other form one group, and **the ordinary rule is read over the group**: 2+ conversations
between its names, or one name substantive or linked on its own. A group over the bar gets ONE page under the name heard
in the most conversations, the other spellings as aliases, every member's pending line and held claims folded in, typed
`concept` — the closed set's general type, the only one of the ten that holds an endeavour that is not a person,
organisation, place, tool, skill or folder — and marked `proposed_type: project`. A group below the bar is held, each
name on its own line, as before. "Unsure" against a page holds the name (never a second page beside it) and asks the
person only when the two share a word or a conversation — the first newuser run asked "Is Epoxy & fiberglass workshop
the same as Cedar-strip canoe?", a pair with no lead, which is no question for a stranger. A later mention judged the
same as a fallback page lands on it (`_candidate_types` lets a project mention meet the page at the judge); one that
carries a birth rides to Stage 5, which makes **the same page** the project — `type: project`, `born:` written once, the
marker gone (`project_birth.retype_on_birth`, only on a `concept` carrying the marker and no `born`; a project page or a
page born with another type is never retyped). A mention with a birth that the loop matched to nothing is weighed
against every fallback page the same way (`_fallback_match`: aliases count, no shared word needed, the judge decides,
a rejected pair never brought), so "Canoe restoration" retypes a page named "Hull build project" that lists "Canoe"
instead of minting a project beside it (review of #441). A birth inside the batch that creates a fallback page makes it
a project from the start.
"A project" is the type the create will write (`_written_type`: a sibling's `project` overrides a `concept` when the
payloads merge), never only the chosen mention's (W4). A project mention with no match whose recorded alias names
exactly one project page — on disk, else born this batch — brings that page to the judge (W2): "same" makes it the
page's update, "unsure" asks the person, "different" or a pair the person rejected leaves it a held mention. An alias
brings its page to the judge, never a decision (owner 2026-10-08).
Stage 5 writes the record once, as the page's `born:` frontmatter (`storage.md`). A watched folder the person named as
a project (`folder_source.ensure_project`) is born `{origin: words, via: folder}`. Pages that existed before the rule are
never archived or deleted for it; `python -m api.scripts.project_origins_dry_run --bank <path> [--json] [--quotes]` lists
each with the origin the bank can show and why, read only, for the owner before any review list is raised.

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
- **A waiting Contacts card (owner ruling 2026-10-20)** is a fourth rung, on its own: a `person` mention **the person
  made in their own words** — Stage 1 measured it `named_by_person`, in a conversation (not a save, a watch or Cicada's
  own check — `quiet_pages.episode_kind`), and the card's full name stands in one of the person's own *marked* turns
  (`user:` or a meeting's `speaker:`; `_said_in_person_turn`). So never an agent's reply, a relayed connector turn
  (`evidence_kind: assistant`, ruling 32), a body with no turn markers (which promotion reads as the person's own
  writing: a note, a feed item), a tab group's titles or a calendar entry (`CARD_REFUSED_SOURCES`, review of #391) —
  and its name or an alias must be exactly one waiting card's given + family name, either order, folded as
  `contacts_local` folds (`contacts_local.WaitingIndex.match`). Never a one-part name, a name two cards share, a name an existing person page
  already holds (that card is the page's: the sync or the tail's rematch matches it), a relation-only person
  (`role_people`'s `unnamed`), a mention from a saved link's text, a demo bank, or the person's own card (the app marks
  the "me" card and it is the owner's page's alone, G169). The page is born under the card's name (`sanitize_id` of
  it; the name the conversation used becomes an alias; a merged spelling never renames it), Stage 5 writes the card's
  G61 sources and thumbnail on it as it creates it (`contacts_local.seed_page`), and a second spelling in the same
  batch joins that page (`entity_resolver._card_for` / `_card_entity`). Stage 2 logs a count, never a name.
- **An application the person acted on (TODO ruling 42, owner 2026-10-27; `api/services/application_page.py`)** is a
  fifth rung: a specific event, program, hackathon, fellowship, course or opening gets its page from one conversation
  when Stage 1 marked it with an `application` (status `drafted|filled|sent|registered|accepted|rejected|attended`,
  `by` user or assistant — the model's field, consumed at Stage 1 and never written) **and** the conversation shows the
  act: one sentence of a person's own turn (`promotion.PERSON_KINDS`) names it (exact, `project_birth`'s name
  matching) and says it was done (`application_page.DONE`: applied, registered, signed up, RSVP'd, enrolled,
  submitted, sent the application/form/request, filled in or out, requested to join, drafted, was accepted/rejected,
  attended; a few languages), with no question, plan, wish or negation in that sentence (`NOT_DONE`: should I,
  planning to, going to, want to, thinking of, haven't, not yet…; a sentence ending "?" never counts), or — only in a
  harness transcript (`capture_kind: transcript`, not relayed) — one sentence of the agent's own line does ("The X
  form is filled in"). Never a `person`, `tool`, `skill`, `location`, `directory`, `media` or `deadline`; never a
  save, a bookmark, a mention, a plan, a question, a form named in another sentence, or a texted agent explaining how
  to apply (only a harness agent acts in the person's tools). The
  record (`application_birth`: episode, day, status, `by` = `user` or the agent's product name, the session when an
  agent acted, the name's span) rides on the extraction like `project_birth`. Stage 1 then writes the application on
  the thing (`record_facts`): a dated fact naming who acted ("As of <day>, Claude Code (session 1a2b3c4d) had filled in
  <owner>'s application to [[X]]; sending it was left to <owner>."), the open step as an open question when the status
  leaves one, and the status as a `values[]` entry — a single-valued claim a later conversation's status supersedes,
  observed `external:<harness>` when the agent acted, carrying the session. What the owner's extraction says about the
  thing — key facts, summary sentences (each standing alone), history entries naming it — moves onto it
  (`move_from_owner`); the owner keeps its relationship claim (the link). A thing the model typed `project` with no D4
  birth is written as the fallback `concept` (ruling 36 D4 still holds). Its decay is the event page's own.
- **The act's object is the event, never its venue or organiser (2026-10-28, `api/services/act_object.py`).** "I
  signed up for an <event> at the <venue>" gave both "<person> signed up for <event>" and "<person> signed up for
  <venue>", the second shown as the person's own words. After every chunk's spans are located, `act_object.hold`
  reads each relationship whose label is exactly an act (`ACT_LABEL`: applied, registered, signed up, enrolled,
  RSVP'd, submitted, requested to join, with at most to/for/in/into/at/on) against the sentence its span sits in: when
  the act word comes first, another object follows it, and the target follows a venue or organiser word (`MARKER`:
  at, in, held at, hosted/run/organised/put on/offered by, by, with, from, through, via; Spanish en, con), the target
  is where or by whom. The relationship then becomes the event's link — "<event> at / run by / with <venue>", the
  person's span kept — when the same extraction has the act on an object named between the act and the marker (in
  this act's own clause: from the last act word before the target, so "I applied to <X> and registered my startup in
  <place>" never links <X> to <place>), is dropped when that link is already there, and otherwise says what the sentence says ("<person> signed up for
  something at <venue>"). A label that already names where ("signed up for workshop at" <venue>, `WHERE_LABEL`) is
  true as written and kept, except beside the act on an event its own words name ("workshop") in its clause, where
  it folds the same way. "Signed up for the <venue> workshop", "applied to <program>", a name before the act or no
  located span are never judged (G118). `application_page` applies the same reading: a name in the act sentence that
  is a venue gets no `application_birth`. The Stage 1 prompt says it too (APPLICATION). Measured in G194's row.
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
gives the name one — a holding line leaves the store only then, or when the person's "same as" answer on the name
lands its claims on the page they named (G209, *held names* below). A Stage-4 skill seen in one conversation waits in a
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
  holds the pages, a page dirty in git skipped, a second run a no-op). **Nothing not attributable to the
  correspondent's conversation is lost or moved:** it starts from the page as it is now and subtracts only the
  conversation's part. It splits a page whose own `name` (an alias alone is `skipped_alias`) folds to a conversation's
  correspondent, that credits its episodes or holds a claim resting on them alone, and whose type does not match.
  From git, the *base* is the page before the first commit that credited the conversation, and every commit since is
  read. Claims keep their current state: one resting only on the conversation (sources and evidence) moves,
  re-subjected; one also backed elsewhere stays and a copy with only the conversation's episodes and evidence goes to
  the correspondent's page. The conversation's `source_episodes` move. Prose and the list frontmatter (`tags`,
  `aliases`, `related`, `sources`) move only when every commit since the base that changed them was a Sleep commit
  crediting the page with the conversation's episodes alone (then the old prose is the base's, the rewritten lead and
  Article move verbatim with their stamp, added items and values move); otherwise they stay and the correspondent's
  page gets its facts from its claims (`prose_left`). Person-set keys (`sources_removed`, `aliases_removed`,
  `corrections`, `picture`, …) never move. Status and confidence come from the page's own remaining history (the
  base, then every later change except the conversation's commits and the Sleep decay charges against its lift);
  `last_referenced` is the remaining conversations' latest day; `dropped` stays. The correspondent's page is an
  existing right-type page (merged human-safe) or a new one under `free_id`, born active at `RECOVERY_CONFIDENCE` with
  its conversations' days. Other pages' claims resting on the conversation alone that point at the old id are
  repointed; claim edges are regenerated (Stage 5.7's `regenerate_edges_from_claims`). A page with no version before
  the conversation, or a bank without git, is counted (`no_history`) and left alone.

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
order (`_overlap_pages`). Since 2026-10-20 the write calls (article or synthesis) run first and the contradiction checks after them, several pages a call (see *Fewer calls per conversation*). Once every answer is in, the results — the synthesized
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

**Fewer calls per conversation (2026-10-20).** A scheduled 14-conversation night on haiku made 574 model calls
(owner's telemetry ledger): disambiguation 268, merge 116, conflict 110, extraction 48 — reading was 8 % of them.
What triggered each:

- **Disambiguation** — one call per (extracted name, same-type page sharing a content word or listing the name as an
  alias), one after another until the first `same`. A name sharing a common word ("google", "model", "review", a
  first name) with N pages cost N calls, almost all `different`. Now **one call weighs up to `JUDGE_BATCH` (6) of a
  name's candidates** (`entity_resolver._llm_judge_batch`, `_DISAMBIG_BATCH_PROMPT`): the same guidelines, each
  existing page a numbered entry cut as the one-pair prompt cut it (2,000 characters; an alias entry carries the alias
  note and its page context first, and the name's connections ride along), one decision per entry. Candidates keep
  their judging order; a call holding a `same` ends the name and the first `same` in order is the match, so the
  rule is the one-by-one loop's. A lone candidate keeps `_DISAMBIG_PROMPT` byte for byte. An answer is read only when it
  lines up (`json_parse.numbered_rows`: its numbers exactly 1..n, or no numbers and exactly n rows); 0-based, duplicate,
  missing or mixed numbering, or a short or long list, is `unsure` for every entry (as an unreadable one-pair answer),
  never a decision read against the wrong page; an engine error still raises. The stage keeps its name
  `disambiguation`; its plan schemas take both shapes (`agent_engine.SCHEMA_BY_STAGE`,
  `engine_schemas.disambiguation_schema`).
- **The judge read nothing about the new name.** It was given the extraction's `description`, a legacy field
  Stage 1 almost never fills (1 of 79 entities on the synthetic night) — `summary` is what it writes. So nearly
  every call compared a page with "(empty)", and the guidelines' own rule ("an empty description and names that don't
  obviously line up" → `different`, a bare first name → `unsure`) made every first-name mention a "Possible duplicate
  of …" question. Stage 2 now reads `summary`, falling back to `description` (`_effective_summary`), for the name, for
  an in-cycle create as a candidate, and for the context of the questions it files.
- **Conflict** — one contradiction call per updated page with a summary. Now **one call checks up to
  `CONTRADICTION_BATCH` (5) pages** (`conflict_resolver._check_pages` → `_detect_contradictions`,
  `_CONTRADICTIONS_RULES`): every line of the one-page definition, then each page in its own numbered block with the
  same cuts (4,000 / 2,000 characters) and dates, answered in its own result. A page's check reads only its page as it
  was before the stage and its own update, so the checks run after all the write calls, grouped in the pages' order
  (the groups depend on that order alone, so every concurrency asks the same calls); results are applied in the
  pages' order as before. A lone page keeps `_CONTRADICTION_INPUT` byte for byte; an answer that does not line up (the same
  rule) files no question for any of its pages, as an unreadable one-page answer.
- **Merge** — one write per page with something to write (the article or the synthesis), already none for a stub, a
  re-read or a hand-edited page. Unchanged: its output is the page, too long to share a call.

Not built, and why. *A deterministic pre-filter on names* ("both names have a word of their own" → different): on
the synthetic night every such pair was `different`, but the same shape covers "Personal Site"/"Personal Website",
"ML Pipeline"/"Machine Learning Pipeline", a nickname and a surname — the judge exists for those, and with batching
the pairs it would remove share a call with the ones it must keep, so it would save a call only for names whose
every candidate it removes. *A cross-run decision ledger*: keyed on what the judge reads it never hits (the
description is new every conversation); keyed on less it replays a `different` the new description might overturn —
the first-name case. *An embedding-distance cut*: a threshold that is conservative on the synthetic night is a guess
on the owner's bank. Exact names, fuzz > 85 and a type mismatch were already settled with no call.

Measured (`benchmarks/scale/sleep_calls.py`: a ~290-page synthetic developer bank, eight conversations, one drain on
the plan with haiku for every stage, one call at a time, articles and summary synthesis on, the clock pinned; a
prompt the change did not alter is answered from the earlier run's record, so the bank diff is the change's own):

| calls per conversation | extraction | disambiguation | merge | conflict | skills + inbox | total |
|---|---|---|---|---|---|---|
| before | 1.0 | 4.4 | 5.4 | 4.6 | 0.6 | 16.0 (128) |
| batching | 1.0 | 2.6 | 5.4 | 1.0 | 0.6 | 10.6 (85) |
| batching + the judge reads the summary | 1.0 | 2.6 | 6.1 | 1.1 | 0.5 | 11.4 (91) |

Batching alone: every page, claim and source identical; of 35 judged pairs 33 got the same decision, and the two that
differ flip on the one-pair prompt itself (re-asked three times each: `different, unsure, unsure` and
`different` ×3 against a recorded `unsure`) — run-to-run variance, not the batch; 37 contradiction checks, none found
either way, and on ten labelled pairs (five unresolvable) the one-page and the batched check were both 10/10. The
summary fix then merged six first-name and short-form mentions into their own pages (a colleague, the advisor, a
recruiter, a teacher, a friend, the thesis) — correct on the fixture, the namesake pages judged `different` —
instead of filing six "Possible duplicate" questions (inbox 15 → 9), so six more pages were updated (merge +6,
conflict +1). Stage 2's wall time 137 → 96 s; contradiction-call time 130 → 55 s. For the 14-conversation night
above: disambiguation ≈ one call per name with candidates (≤ 6 each; ~60–90), conflict 110 → 22, merge ~116–130,
the rest unchanged (extraction 48, inbox tend 18, enrichment 12, skills, web check): **~280–320 calls, ~20–23 a
conversation, against 574 (~41)**. The owner's own next night is the measurement that counts.

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
same-type alias holder judged (first `same` stops; since 2026-10-20 the holders and the token-sharing pages share one call, the holders as its first entries — see *Fewer calls per conversation*); a name with no shared word went from 0 calls and a duplicate to
usually 1 call; one that shares a word and names its alias holder usually costs fewer calls than before, because the
holder is judged first. A judge call with no alias candidate gets the prompt it always got, byte for byte. Link recon
(`match_existing`) does not read aliases.

**One person, one page: leads, never merges (G209, 2026-10-22).** A live bank held one person three times: a
full-name page already listing a handle as an alias, a page titled by the handle (both born in one Sleep run), and
a pending line `handle (Full Name)`. Measured there: 14 of 277 person pages carried a name that another person page
listed as an alias. Four gaps caused it, each closed:
- **In-cycle alias parity.** `_created_llm_candidates` reads an in-cycle create's aliases the way
  `_existing_llm_candidates` reads a page's. A same-type create listing the name is judged first, with the alias
  note, the create's other names (`_alias_context`) and the name's batch connections. A name with no shared word now
  meets the create, where before it got no candidate at all. Same rule as on disk: `same` merges, `unsure` asks.
- **An exact page no longer hides the alias.** When a name matches its own person page and another person page lists
  that name as an alias or links it as an account, Stage 2 files "Possible duplicate of …" with no model call
  (`person_leads.PersonIndex.leads_for`, `_create_lead_clarification`). The context says the lead in words ("<holder>
  already lists "<name>" among the other names it goes by"). The mention is still credited to its own page: it is
  never a merge. A pair the person called different (`merge_rejections`) is never asked again. A mention of the name
  closes an open duplicate question only when it merged into the page that question proposed
  (`check_organic_resolution(merged_into=)`).
- **A linked account is a lead.** A profile link on a person page (`x.com/<h>`, its `/status/` posts,
  `github.com/<h>` but not a repository under it, `instagram.com/<h>`, `linkedin.com/in/<h>`, in `sources:` or in the
  body) makes a new person name equal to that handle a question, never a page: the name parks as a pending line, and the
  question context names the account. A handle is never derived from a name; it must already be written on the page.
- **`Full Name (handle)` / `handle (Full Name)`** in a person extraction (`person_leads.split_named_handle`: one side a
  handle, `@x` or one lowercase token that is not a relation word, and the other two or more words) is keyed by the
  full name with the handle as its alias. The raw spelling still resolves edges and claims (`name_to_id`). A pending
  line parked under that spelling folds into the page the full name resolves to, with its text, credits and held claims,
  and leaves the store through `promoted_pending`.

- **A held name meets the page its alias names (W1, benchmarks/newuser 2026-10-22).** Specific names are judged
  first, so a full name said once (aliases the short name and a handle) is held before the short name its other
  conversations promote has a page. After the loop, every held person name — this batch's and the pending store's —
  whose recorded alias is the name of exactly one person page raises "Possible duplicate of …"
  (`_held_alias_questions`); an alias two pages answer to asks nothing. At most three such questions about a name with
  no page are open at once (`MAX_HELD_ALIAS_QUESTIONS`), so a first Sleep over a long pending store never floods the
  inbox; dismissing a "Possible duplicate" card records the pair in `_merge_rejected.yaml`, like "not the same", so
  the line re-read from the store is not asked again.
- **A held full name meets the page its given name titles (benchmarks/newuser 2026-10-23).** A held name with no alias
  that names a page asks the same question when it is a full name as written (two to four capitalised name words, no
  handle, digit or parenthesis), it has no page of its own, and its given name (folded) is the whole title of exactly
  one person page while no other person page's name begins with that word (`_given_name_pages`): "<given> <surname>"
  held beside a page titled "<given>" asks; two pages for one given name ("<given>", "<given> <other-surname>") ask
  nothing. The owner's page and a page titled by a relation (`role_people`) never count. Same cap, same
  `merge_rejections`, never a merge; the card says the conversation named the full name and the page carries only
  the given name.

Nothing here settles who a person is (ruling 29): every lead ends in the person's question. A duplicate question about
a name still parked below the promotion bar is live while its pending line exists (`inbox_service._subject_gone`,
`pending_store.waiting_ids`). Before 2026-10-22 it was read as "no longer in your memory", hidden from the inbox and
retired by Sleep's tending the same night. That predated G209 and also hit Stage 2's own `unsure` duplicates.
**The person's answer sticks (review of #421).** A "same" answer on a name with no page adds the name to the target's
aliases and takes its pending line (a line still holding claims stays until they are written there). Stage 2 then reads
the answer's note on the page (`person_leads.answered_same`) as the person's own verdict: the name goes to that page,
with no judge and no question. A "different" answer (`merge_rejections`) drops that page from both the lead and the
judge's `unsure`, so the name promotes or parks by the usual rule and is never held back by a question that will not be
asked again.
`python -m api.scripts.person_leads_dry_run --bank <path> [--json]` lists every lead for a bank: page↔page, a parked
name another page carries, and a parked `handle (Full Name)` line with its page. Each lead shows whether its question is
open or was answered "different". It writes nothing. Proven on a scratch bank (plan, haiku): four conversations naming
`<person-a>`, `<person-a> (<handle-a>)` and `@<handle-a>` in one batch. Before, they made two pages and no question;
after, they make one page, because haiku judged the alias `same`. An agent-added X profile link plus two conversations
naming that handle raised "Is <handle> the same as <person>?", which the inbox served after Sleep.

**Spellings, shared aliases and co-occurring names (G209, 2026-10-27).** A live bank showed one person as three
person pages, and a fourth page — another person's — listing her name and nickname among its aliases. Three
mechanisms, each closed for every type, not only people:
- **A new name's own aliases and close spellings bring pages to the judge.** Candidates were found by the new name
  only (a page listing it, a page sharing a word with it); the extraction's own `aliases` were never looked up, and a
  dictated misspelling shares no word with the real name and scores under the direct match's 85, so it met no page and
  was born. Now `_existing_llm_candidates` / `_created_llm_candidates` also bring a same-type page that shares an alias
  with the new name (its name or one of its aliases is one of the new name's aliases) or whose name or alias the new
  name is a close spelling of (`close_spelling`: both ≥ 4 letters folded, same first letter, at most 1 edit apart, 2 when
  both have ≥ 6 letters; under `fuzz.ratio` 85). The judge is told why (`_lead_note`). A page that is BOTH a close
  spelling and a shared alias is never cleared by the judge alone (`_never_cleared`): `different` reads as `unsure`, so
  the name is held and "Possible duplicate of …" asked; it joins only on `same`. A pair the person called different is
  never brought by a lead. A pronoun or reference alias ("she") is no lead on either side. Measured on that bank: 69
  same-type close-spelling pairs, 8 of them also sharing an alias.
- **Two person names the direct match would join are the judge's unless they are one spelling.** `fuzz.ratio > 85`
  joined "<name-a>" and "<name-a'>" (one letter apart) with no judge — a merge on a name's resemblance, which the
  `role_people` rail forbids. For a person, the direct match now needs the names to be one spelling once case, accents,
  spacing and punctuation are set aside (`_near_person`); any other near-spelling goes to the judge as a close spelling.
  Other types keep the direct match, under the distinct-name rule below. (Edges and claims still key a held name
  through `endpoint_id`'s fuzzy rule.)
- **An alias is a name this page goes by, never co-occurrence.** Stage 1 gave one person the name and nickname of the
  other person in the same conversation, and Stage 5 unions every new alias onto the page for good, where it brings that
  page to every later judge call and lead question. Now Stage 2 drops, before anything keys a name, an alias that is the
  name or an alias of ANOTHER entry extracted from the same conversation (`_drop_conversation_names`, before the G209
  handle split) — unless that entry lists this one's name back ("Full Name" ↔ "Nick": the extractor saying they are one
  thing), or the alias starts a word of this entry's own name (its own short form). A nickname two entries of one
  conversation both claim otherwise goes from both. Either way the pair is marked named together (`NAMED_WITH`) and goes
  to the judge with that note, so neither is ever created unjudged. What a page already lists is untouched; removing an
  existing wrong alias is the person's repair. An alias is NOT dropped for being another page's name or alias: a
  nickname the person uses is kept even when others share it (ruling 41, below).
- **Nicknames at scale (ruling 41, owner 2026-10-27).** A nickname never joins on its own: a person page titled by a
  nickname (`nickname_title`), or a name two or more other person pages answer to, is never a direct match — it goes to
  the judge with every page answering to it (`_shared_name`; one other holder stays G209's lead question). More than
  `MAX_NAME_HOLDERS` (5) pages listing one name make it common ("babe", "bro", initials): those alias holders are not
  each judged, but everything more specific still points — the mention's own aliases ("Alex" said as "Alex Kim"), a name
  said with it, a close spelling, and the page titled exactly by the name, which joins on the judge's `same`. A name
  whose page id is another page's that it did not join (judged different, or unsure) is never created over it: it is
  held and "Possible duplicate of …" is asked; once the person says it is someone else, it gets a page of its own,
  "<name> (another)". A held name that an existing page bears has no endpoint (`HELD_ENDPOINT` in `name_to_id`): its
  edges are dropped and its claims never keyed to that page by name: every claim whose subject OR object is the held
  name is taken out of the page path (`claim_pipeline._split_held`) and held on its pending line under the plain slug —
  as its subject, or as another page's claim with it as the object — so no page fence ever holds a `held:` value. The
  line carries `held_against: <page>`: its claims are released onto that page only when Stage 2 joins the name there
  (`decided_names`), never because the page shares its name; an object-side claim is released by re-pointing its
  object and stays on its subject's page (`pending_store.ready`). **The person's answer releases it too (2026-10-27):**
  "same as B" on the name's "Possible duplicate" question lands the line's claims on B in the resolver's own write
  (`inbox_service._release_answered` → `pending_store.answered` → `claim_pipeline.land_answered`: through Stage 3
  against the page's claims exactly as Stage 5.56's release, decay left to Sleep, its questions to the inbox in the
  same commit; an object-side claim re-pointed the same way; the conversation credits the page), the landed claims
  leave the line (`drop_released`) and the pages plus `pending_entities.jsonl` ride in the answer's commit, so Sleep's
  undo (or a revert) takes them back off. A claim whose page is gone stays held. Only a question about the held
  MENTION releases: Stage 2 marks the questions it raises about a name it holds (`held_mention`), because the
  mention's id can be the id of the page it was held against; a question about a page (`fold_page`, a page pair, or an
  older unmarked item) never releases a line held against that page, and Sleep's "same" settle never folds the page a
  held mention shares its id with, nor the page of an unflagged question raised from 2026-10-27 on
  (`UNFLAGGED_FOLD_CUTOFF`) — where the fold is refused Sleep does not settle at all, and the question waits for the
  person. "Someone else", dismiss and skip release nothing: the resolver never mints a page,
  so the name waits for Stage 2's promotion rule ("<name> (another)") and its claims follow there. With no titled page and no lead, the mention
  goes on by the usual rule. The leads are looked up in one
  index built per run (`NameIndex`: name/alias key → pages; folded spelling bucketed by first letter and length), never
  by a scan over every alias of every page: 43 ms to build and 2.3 ms a name for candidates (0.4 ms the direct match) on
  a synthetic 2,500-page bank with ~20k aliases.

**The misread trace (G118, G209, 2026-10-27).** One Claude Code session showed four Sleep-side classes; each is fixed
for every case, measured on the owner's bank copy (numbers in the report, never here):
- **Taking part needs a role in the text.** An agent's memory note called an application answer "the <event>
  story"; the person had not taken part in that event. Stage 1's prompt now says it (TAKING PART NEEDS A ROLE
  IN THE TEXT), and a deterministic guard holds it for any engine (`participation.hold`, right after the G118 span is
  located): a relationship whose label STARTS with a claim of taking part — competed / took part / participated in,
  won, attended, works / worked / interned at, studied at, enrolled in, graduated from — is read against its located
  span's sentence and one sentence either side (speaker labels stripped). **An agent's or a summary's words** (any
  evidence kind but `user`, where the misread came from): kept only when that window says a role of the family, not
  negated ("did not compete"), in English or Spanish. **The person's own words:** kept unless the window positively
  shows a topic marker ("story", "about", "essay on", "topic") and no role word — people say roles every way ("my new
  gig at …", "Me gradué de …"). **No located span:** kept, dates included (G118: provenance never blocks memory).
  A relabel makes it `mentioned`: the link stays, the claim of taking part and its STARTS/ENDS/AT go. "competes with",
  "planned to attend", "works with" are not this rule's (review of #491 narrowed it: 37 of 176 stored claims would
  have flipped, now 7).
- **A fuzzy join never takes a name with a word or number the other lacks.** `fuzz.ratio > 85` joined "<agency> <city>"
  to the city's page, "Amazon EBS" to "Amazon EKS", "Course 2" to "Course 1", "ask" to "dask" — at the direct match
  (an entity merged into the wrong page) and at `endpoint_id` (an edge or claim keyed to it). `distinct_names` now
  refuses a pair when a word on one side has no spelling of it on the other, or the numbers differ; spacing, case,
  accents and punctuation never count, a word spelt two ways is one word (`_variant_words`: a 4+ letter prefix, one
  edit at 5+ letters, two at 8+, a plural), and a word hyphen-joined to a shared word is part of its spelling
  ("browser-use harness" / "browser-harness"). The entity then goes to the judge with the pages it shares a word with
  (`_existing_llm_candidates` no longer skips such a page as "the direct match's"); an edge endpoint resolves to
  nothing, so its claim is held page-less, never landed on the wrong page (`fuzzy_same`).
- **Organisations, labs, projects and tools get people's alias lead.** One lab lived on three pages (company, company,
  project), each listing another's name among its aliases. `person_leads.PersonIndex(pages, ORG_TYPES)` keys the same
  alias lead across `company`, `project` and `tool` (never a person, never a profile handle, never a shared word —
  the alias must be the other page's whole name; archived and dropped pages are not indexed), and a mention that
  matches such a page by name raises the same "Possible duplicate of …" question (`_create_lead_clarification`,
  "could refer to the same thing as"), never a merge. `person_leads_dry_run --family org` lists the groups.

**A reference is not recorded as a new alias (2026-10-08, narrowed in fix round 1).** An alias is another NAME for the
thing; a phrase that only points at it inside one conversation ("the lock", "this project", "la base") is not.
`alias_policy.is_reference` is deliberately narrow: two or more words, all lowercase, no digit, the first an article or
demonstrative (English or Spanish) — or, since 2026-10-27, one all-lowercase personal pronoun ("she", "her", "ella";
"Ella" stays a name). Titles and names keep a capital at least at the start ("La casa de papel", "The
Economist"), a number makes a name ("The 100", "El 47"), and a possessive ("my mom", "mi mamá") is how the person
refers to one thing consistently, so none of those is a reference. It is used in ONE place: `apply_changes` drops
references from the aliases Sleep adds (a create's, and only the new ones of an update); what a page already lists —
a person's merge records the losing page's name there — stays, and the #249 alias index reads every alias as before. A
real name typed all lowercase and article-led is the accepted false positive: it is only not recorded as a new alias,
and a lowercase spelling of a page's own name already matches by name. The extraction prompt no longer shows `"the db"`
as an example alias and says a part, product, dataset, format or version of a thing is not its alias. An alias a page
already lists that is another page's name is not removed by anything automatic: it may be the lead for a merge (a NEW
one is not written, 2026-10-27, above). For an existing bank,
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
`skill_grounding.ground` matches each evidence name, without a model, to this batch's conversations — conversations
only: a saved item or a calendar entry (`inbox_tend.record_origin`) is a record, never evidence of how the person
works (benchmarks/newuser, 2026-10-22: two bookmarks had grounded a "skill") — (Stage 1's names,
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
**A summary that outlived its facts (W6, 2026-10-23).** Because the prose is written once, a skill born before a switch
keeps describing the old stack ("<person-a> reviews the <tool> pull requests" after the project dropped the tool). Such a
skill is left out of the handshake's *How to work with me* on the next cursor rebuild, which every Sleep runs
(`skill_staleness`, `storage.md` "The handshake"), but the row never drops below three: the least stale stay,
marked; only a belief an ending closes counts. No model call is added. Rewriting the summary instead would need
Stage 4 to be shown the stale skills and allowed to replace their prose — a few hundred input tokens on the call it
already makes, and a change to the "prose is not touched" rule above — and is not done.

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

**Every engine call sends Cicada's own system prompt (perf report 2026-10-24, items 1 and 3).** `agent_engine.build_argv`
always passes `--system-prompt=`, the replace form and never `--append-system-prompt`. A stage with no system message
gets `DEFAULT_SYSTEM_PROMPT` (one line) instead of the CLI's default coding-agent prompt (~2.3k tokens a call).
Disambiguation and the article writer have their own short ones. Every prompt ends with `CONTEXT_GUARD`, because the
CLI still attaches context of its own. That includes **the signed-in account's email address**: on `claude` 2.1.310
it comes from the plan sign-in, and no flag or variable removes it. In one benchmark Sleep it reached the owner page as
three key facts. In the 2026-10-24 A/B a dev Sleep also gave the synthetic owner an alias made of the address's words
before the `@`. The floor under the guard is `engine_identity`. On the Claude plan only, Stage 1 (link recon's batch
call included) and the merge stage read the account's email from `claude auth status --json`, keep it in memory, and
never log, write or send it. Async code reads it through `aidentities`, on a worker thread, so a cache miss never runs
the CLI on the event loop. Its forms are the address, and the words before the `@` when there are two or more of three
letters or more. The address counts only whole; the name only as its words adjacent and in order ("Anna May",
"anna.may") or last word first before a comma ("May, Anna"), never the same words apart in a sentence. They drop
any item carrying a form (an alias, a fact, a history line, a link, a claim, a summary sentence, an entity named for
it, an article) unless what the model was given says it: the episode, the owner's name and source note in the
extraction prompt, or the merge's own input. An address or a full name the person typed is kept, and the evidence
rail places its span as before. The account's profile name is not filtered on its own, because it is often the
owner's own page.

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
- **A nickname is the title only until a name is found** (ruling 41, owner 2026-10-27): Stage 1's "<nickname>
  (unnamed)" (no relation word) becomes a page titled by the nickname, `unnamed: true` + `nickname_title: true`, the
  nickname also an alias (`canonicalize`, `nickname_of`), asked "What's <nickname>'s name?" when it holds no relation.
  A name question Sleep finds answered only by a nickname (`inbox_tend._nickname`: the reader marks it one, or it is
  lowercase where the quote has capitals) titles the page by it as its own Sleep commit — the question stays open and
  follows the page, a nickname exactly one other person page answers to asks "Is <A> the same as <B>?", never a merge.
  A name — the person's inbox answer, or a settle that passes `written_as_name` — takes the title through `rename`,
  which keeps the nickname as an alias and drops `nickname_title`; that switch is never asked. The mark is how the page
  shows it is a nickname until a name arrives.
- **Stage 5.4b asks about one relation held twice** (`ask_exclusive`, 2026-10-27): a relation one person holds at a time
  (`EXCLUSIVE`: partner — partner, spouse, girlfriend, boyfriend, wife, husband, fiancé(e) and the Spanish words —,
  mother, father, stepmother, stepfather) held by two or more live person pages (`exclusive_holders`: `owner_roles`, a
  placeholder titled by it, or an open claim or edge between the page and the owner whose predicate names it exactly, as
  the repair reads evidence; a partner word reads the same from either side) raises "Is <A> the same as <B>?" once per
  pair when a page this batch touched is one of them (`ask_same`: subject and candidate by id, `fold_page`, so "merge"
  folds one page into the other). Never a merge without the person's answer; a pair they called different is never
  asked again. Nothing compared pages by the relation they hold before: one person under a name and under a nickname
  both "the owner's girlfriend" raised nothing.
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
  person said it matters; one fact once, as many as the conversation establishes (the "usually 0-5" was lifted
  2026-10-17, below); a detail of the assistant's answer is not an entity unless the
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

### Facts keep their context (2026-10-27)

A Key Fact is read alone — by recall, by `cicada_ask`, on an owner page of ~2,000 Key Facts — so it must say what it
is about, who did it, and never say one thing twice. Four mechanisms, each engine-free except the prompt:

- **A displaced orientation splits into facts that stand alone (`fact_policy.standalone`).** Before, every writer that
  turned an orientation which lost the Summary into Key Facts (`entity_body.retain_orientation`,
  `merge_sections_fallback`, `entity_orientation.compose`, `pending_store._carry`, `entity_resolver`'s same-name fold)
  split it at every sentence, so "<owner> … is applying to [[X]]. As of <day> he had the application form filled in …"
  became two bullets and the second named no event (owner bank: 322 owner bullets name nothing beyond the owner; 58 of
  them sit, unrecorded, right after a sentence naming a thing — the split's signature). Now a sentence that **leans**
  (`fact_policy.leans`) stays joined to the one before it when that one names something other than the page: it names
  nothing beyond the page (no wikilink, no capitalised word but the first, a month, a weekday or "I"), or it opens with
  a pronoun or demonstrative after a sentence not about the page (one that does not open with the page's name or a
  pronoun). A leading date phrase ("As of 2026-10-21", "In March 2026,") is read past. Lossless: words are only kept
  together. `entity_body.lead` keeps a leaning sentence with the one it leans on when that one leaves the Summary.
  `fact_policy.sentences` (the Summary's own sentence list, dedup) is unchanged.
- **One fact said twice folds when written (`fact_policy.extends`, `fold_extensions`; ruling 23's trigger).** A fact
  folds into another only when every word of it is there, in order, at the start of the other (after an optional
  leading date phrase), and the other goes on past a clause boundary (`, ; : . ! ?` and a space, a dash, a bracket, or
  with / which / who / whose / where / including / via / through) — "Rolling admissions" into "Rolling admissions with
  no deadline, …". Never inside a word or a number ("Acme" / "Acme's competitor", "200" / "200,000"), never past "or",
  "but", "than", "until" or "to", never a dated fact into an undated one. The longer takes the shorter's place, so no
  word, date or number is lost, and the folded fact's G118 rows move onto it (`section_provenance.refresh` and
  `merge_selected`). `fact_policy.union` and `entity_body._merge_facts` apply it — existing bullets included on a
  machine page, never on a page a person edited (`extend_existing=False`). Measured on the owner bank: 109 facts on 79
  pages fold, every one of 25 sampled loss-free. Paraphrase is not touched: ~2,700 facts on 477 pages pair up at
  content-word Jaccard ≥ 0.6, and 2,741 Key Facts on 772 pages re-introduce their page ("X is a …", a displaced
  orientation) — only the opt-in synthesis call folds those (ruling 23).
- **Who said it, who did it.** A claim resting only on the other side's words is theirs (`entity_extractor
  .assistant_observer`): a texted agent's (G179), and now a harness session's agent (`external:<harness>`) and a chat
  export's assistant (`external:chatgpt|claude|gemini`); a relayed episode (`evidence_kind`) keeps its own rail. Such
  an observer shares Cicada's own `agent` slot in the reconciler (`claim_reconciler.slot_observer`: the same
  extraction of the same conversation), so a newer value or application status closes an older one whichever wrote
  it, a restatement reinforces, and the bank's assistant-only claims already written `agent` need no repair; the trust
  table and the owner's-words rail keep either from closing the person's own claim (an agent-only status after the
  person's own words is asked about). A
  harness transcript's chunks open with a note naming the agent (`agent_session_note`): what it says it did is its
  act, a step it left to the person is not done. The prompt's KEY FACTS: every fact stands alone and names its thing;
  WHO DID IT — the person's act only from their own lines or a record (a confirmation, a receipt); an explanation or a
  suggestion is never the person's act, a plan stays a plan; an agent's act names the agent, and a step it left is a
  fact, an open question and a status value on the thing.
- **The session rides the claim.** `_get_unprocessed_episodes` passes `harness` and `capture_kind`; every Stage-1 claim
  read from an episode with a `session_id` carries it in `session_ids` (the Sleep claim's `session_id` scalar stays the
  MCP writer's, empty). Owner bank before: 2,147 of 2,150 claims from harness sessions carried none.

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
  like the synthesis switch): in Stage 3, a machine page that gains anything (the re-read gate still applies) and
  that the writer takes (`entity_article.worth_writing`) gets ONE JSON call in place of the synthesis call; the
  contradiction call is unchanged. The writer takes a page resting on 2+ conversations once the update lands, or —
  since 2026-10-17 — one on a single conversation whose record already holds `CICADA_PAGE_ARTICLE_MIN_MATERIAL` (4)
  inputs: facts, dated lines, current claims, open questions and what this update said, never the page's own earlier
  prose or its links. **A new page is born an article** on the same test (`conflict_resolver._create_job`: one call,
  no contradiction call — nothing to contradict; Stage 5 composes it with the same `entity_article.compose` from an
  empty page). Below the floor a page is a stub: a lead and a fact or two, which an article would only restate — the
  deterministic merge, no call. A page whose prompt is over `CICADA_PAGE_ARTICLE_MAX_INPUT_CHARS` (60,000) is fitted, never
  clipped mid-input (`entity_article.fit`, owner page 2026-10-14): claims sharing a predicate and an object fold into
  one input (the latest text, how many conversations said it, first and last day, every evidence row); then claim
  inputs are left out — a log's (`entity_body.is_log`: a predicate the stems positively call activity, in a family held
  for more than 3 objects; when unsure, a fact) before a fact's ("studies at") or one about a person page (who is in a life is never a log), the fewest conversations and the
  longest ago first — then History lines, oldest first; this
  update's words, the earlier lead and article, facts, questions and links never; LINKABLE keeps the names a kept
  input mentions. The record keeps every claim and line. Only a page whose own record is still over the budget
  keeps the deterministic merge if it has an article, else today's path.
- **Uncapped (owner 2026-10-17: "It's not that I want a huge page for each thing. It's just that I want to kind of
  uncap what the agents can write to.")** Measured on the owner's bank (non-archived pages, prose words outside the
  claims fence; real values redacted beyond these counts): pages with an article, median 454 words (p90 1,092);
  pages without, median 45 (p90 154); 767 of 4,693 under 40 words. The article writer had no length cap — the thin
  pages were the ones it never ran on: promoted on one conversation, and new pages (a create never got the writer,
  only a later update did). What limited a page, and what was done:
  - *The 2+ conversation gate* → lifted to the material floor above, for updates and creates alike.
  - *Stage 1's "usually 0-5 facts"* and "a short wiki article" → "as many facts as the conversation establishes
    … never pad": the article is compiled from what Stage 1 extracts, so this is the per-conversation lever. Not
    measurable offline (recorded answers); the fixtures' Stage 1 answers give a median of 3 facts per entity (max 7).
  - *Kept:* the Summary's 600-character orientation budget and the type's sentence counts (`summary_policy`, Stage 1's
    SUMMARY): on an article page the writer owns the lead at any length, so the budget only shapes stubs and banks
    with articles off, and what it displaces is kept as Key Facts; the legacy merge prompt's 1-3 sentences (only a page
    over the input budget, or articles off); the input budget (`fit` folds and orders, never clips); the capture caps
    (a capture rail, G110); every writer rail — a paragraph with no cited input is not written, no padding, dated not
    now, provenance per paragraph.
  - *Cost:* one more call per new page over the floor and per one-conversation page update over it; a stub still
    costs none. Offline (`page_quality --articles`, mechanical fake writer): article calls 5 → 9 over 3 batches, pages
    with an article 3 → 4 of 4, median words 219 → 238.5 (p90 258 → 293), no extracted fact lost; `page_articles`:
    18 → 19 calls (the 15-conversation page's create now written), the stub stays a stub.
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
  is the linked page, the claims ledger and the timeline, not the person's article or its Related.
  **Each link is named by what is true now** (`conflict_resolver.related_edges`, benchmarks/newuser 2026-10-23, on
  every page, hub or not): `graph_edges.yaml` keeps every relationship ever extracted and never closes one, and the
  first edge used to name a link for good, so after a job change the person's page read "<old employer> — works at"
  and "<new employer> — interviewing with" though the claims said otherwise. Each label is now read against the claims
  on the page the edge starts from (this page's, or the other page's for an inbound edge) with that object and the
  label's normalized predicate: the newest open one names the link; with none open, the first label no claim speaks
  to, as before; a link whose every label's claims are closed keeps its first label marked "(until <day>)" and goes
  after the rest. An event (born closed) and a withdrawal record never count as an ending (R-PJ3). On a hub, an ended
  link yields every kept line to a current one and counts as the oldest in its family line's "latest". No link is dropped, confidence plays no part, and a page with no claims renders as it did. Stage 5
  rebuilds Related before the batch's claims exist, so the claim pass renames the links of each page whose claims it
  changes from the claims it writes (`conflict_resolver.refresh_related`, only the Related block); an inbound link on
  the other page follows at that page's next write. A page with a stamped article is
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
  skipped as archived/media/human/stubs (`one_conversation`: one conversation, under the material floor)/already
  articles/over budget, selected and how many of them rest on one conversation, prompt characters, estimated calls,
  batches; never a name). Pages go **newest-mentioned first** (`last_referenced`), so a stopped run has done the pages
  most likely to be opened. `--limit N` / `--entity <id>` narrow it; `--preview-dir <outside-the-bank>` makes the calls and writes
  `<id>.before.md`/`<id>.after.md` there, touching nothing in the bank; `--apply` is refused before any call unless the
  backend says Sleep is idle, makes the calls outside the write admission, then writes **`--batch-size` (25) pages a
  commit** (`trigger: maintenance/page-articles`, the model as `Cicada-Author`), checking Sleep again before each
  batch, skipping a page written since it was read. The engine is the one a person-started Sleep resolves (a plan
  allowed; a metered key only with `--allow-metered`); a plan limit is a pause, never waited out here (ruling 15).
  `--rewrite` also rewrites article pages, counting one written today as done, so a rerun continues. One page's
  trouble is that page's (2026-10-13, after a malformed answer aborted a 1,056-page run): a malformed, empty or
  unparseable answer, a timeout, a lost connection, a failed or refused call, a page too long for the model — the
  page is skipped and counted under `page_failures`, as Sleep's article path falls back on the same answer. What
  every later page would meet — a plan limit, an unreachable engine, a missing model, a metered key's quota or
  outage — or 5 engine failures in a row (counted across batches), or Sleep starting between batches, stop the run
  (the backend is asked three times, 8 s each, before a slow or absent answer stops anything, and the stop says which
  it was — "Sleep started", or the backend slow, unreachable or unreadable; `migrate_claims_jsonl.backend_problem`):
  no new page starts, the pages in flight finish, and what was written is kept (the preview files, or every batch
  committed so far with the stopped batch's finished pages), with `stopped` and `not_attempted` in the counts and exit
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
written only when the person applies a suggestion in Settings → Privacy & data; suggestions are derived from
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
watermark (one no charge has covered — every live mention) revives it (`max(current, 0.6)` whatever its status —
since the read-on-time ruling an active page below 0.6 is raised too — and `active`) and restarts its clock when it
was said: the gap until Cicada read it is proven silence, charged once by the pass that settles it, never below where
the page stood before the mention (`confidence_before_mention`, kept only until then; never on an evergreen page).
**The day it was said** (ruling 34, follow-up 2026-10-22) is the conversation's local day: a page's `created`,
`last_referenced` and new-mention day come from its conversations' timestamps through `source_dates.stamp_day`
(`conflict_resolver._said_day_string`), a claim's `valid_from` through `source_dates.episode_day`. Only that attribution
moved — no rate, floor, cap or watermark rule changed. A claim id hashes its `valid_from`, so re-reading a conversation
said between local and UTC midnight mints a new id for the same belief; Stage 3 recognises a re-read by what the claim
says, not only its id (`claim_reconciler._reread_twin`: closed, not withdrawn, same slot and object, and every
conversation it was heard in already cited), so a closed claim stays closed and an ending is never recorded twice. A claim's *said* day (`decay_policy.latest_said`, `mention_weeks`,
`inbox_tend._said`) still reads its episode ids' day: local for every id minted since 2026-10-22, at most one day early
for a hook capture minted before it in the window between local and UTC midnight (left: it needs a header read per
episode inside the decay pass; the trigger is a page seen fading a day early).

**Read on time** (owner 2026-10-16): a conversation dated *before* the watermark and read late — a newly connected
source's history, an export imported after the page was known — counts as if Cicada had read it the day it was said.
Its source and its week count at once; the newest such conversation the page does not already credit is kept in
`read_late` until the decay pass, which places it (`conflict_resolver._revive_on_time`, `decay_policy.on_time`):
revived to 0.6 on the day it was said, less the silence since — proven silence (floored for a repeat) up to the day
Cicada read the page's previous last mention (`learned_on`), live silence after it in full — through the watermark
plus at most one pass of live silence (`decay_policy.through_day`, ruling 1; through today for an archived page, whose
watermark stopped the day it archived). Only raises; the status rises with it (archived → decaying → active), the
watermark moves to where it was charged, `last_referenced` to the newest mention, `learned_on` stays. So a page last
heard 2026-09-01 and decaying, that a newly connected chat mentioned on 10-13, read on 10-16, lands where reading the
chat on 10-13 would have left it: revived on 10-13 and faded for three days. A mention from long ago revives nothing
its age would not have kept alive (an older-than-latest mention never lifts; a 2024 mention placed today lands far
below where the page stands). A lift its age leaves below 0.4, heard more than a week late, is `faded_by_age` (never
asked); one back above 0.4 drops the mark and is asked like any page when live silence carries it across. Because only
the newest late mention matters and it is placed at the drain's final pace, the order late conversations are read in
and the batches they fall in never change the result; across separate runs only the spacing factor can differ (it
counts the weeks known when a silence is charged, G147). When an older conversation makes a one-off its age faded
(`faded_by_age`) a repeat, the page is also lifted to where the two conversations read in one run would have left it:
the repeat floor less the live silence from the day its age was settled to today (`_lift_to_repeat_floor`; only
raises, archived → decaying where it lands at or above 0.2), so how imports split across runs never changes the
result. Claims follow the same rule (`claim_reconciler._reinforce` → `Claim.read_late` → `_place_on_time` in the
decay pass): a late restatement is placed on its day from its own confidence; a settled claim restated after its
watermark but read on a later day is also placed on the day it was said, charged the proven silence since and never
lowered — so a page and its claim from the same late capture land alike. Nothing is charged mid-drain (the batches before the last
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
with no dated conversation, counts as said today) gets the higher confidence and a clock restarted today (said on an
earlier day, the restored confidence is placed on that day, as above); an older restatement is placed on its day
(read on time, above); a memory entry adds the source only. A subject read this pass is charged its proven silence only.
Only Sleep charges claims: the agent and progress writers reconcile with `decay=False` (G85), so a restatement they
record from an older conversation is placed by the next Sleep decay pass. A claim with no dated
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
lines rewritten, a second run a no-op. What the old late-read rule left faded is placed on its day once by
`api/scripts/recompute_read_on_time.py` (`read_on_time_recompute`): the old rule's one mark is a `last_referenced`
later than `learned_on` (every other path moves `learned_on` to the read day), a claim's latest dated conversation
later than its `recorded_at`; the dry run counts, overall and by type, `read_late`, `lifted` (`to_active`,
`to_decaying`, `still_archived`, `faded_by_age`) and `claims_read_late` / `claims_lifted` (a claim is placed from
0.6, its late restatement's confidence not being stored); `--apply` is one `cicada` commit (`trigger:
maintenance/read-on-time`), refused while Sleep runs, only raises, a second run a no-op. A mention said the very day
its page was last read is indistinguishable from an ordinary one and is left alone.
**A memory export entry is facts, not activity** (owner, 2026-10-08). A `source: claude_memory` episode is a summary
of the person dated by the export entry's `updated_at`, not by when anything in it came up. `episode_time` is the one
predicate: such an episode is no week in `w` (page, claim and card alike), and Stage 1 hands Stage 2 its entities
with no timestamp or day and `untimed: true`. A change made only of memory entries creates a page with **no
`last_referenced`** (`created` and `decayed_through` are the cycle's day), and on an existing page moves neither
`last_referenced` nor `decayed_through` and recovers no status; its facts, claims (with their `valid_from`) and
`source_episodes` are written as usual. Any real conversation in the same change dates it as before.
**A feed item is facts, not activity either** (TODO ruling 39, owner 2026-10-24). An RSS/Atom item is dated by when it
was published (its `timestamp` and id day, `published_at`) and records when Cicada received it (`received_at`);
`episode_time.is_feed_item` (`published_at` set, or `origin: rss` for the items written before, dated their poll day)
makes it untimed by the same rule, so a new subscription's back catalogue is neither a burst of mentions today nor a
page started years ago: what decay reads is the page's `last_referenced` / `decayed_through` / `learned_on` and the
dated ids among `source_episodes`, and a feed id is never one of them. Stage 1 is told the item's published day and
that it is the publisher's text (`source_dates.feed_note`), not an assistant's summary.
Below 0.2 → `status: archived` (the page stays in `entities/`); below 0.4 → a decay nudge when live silence carries it across (never for what its age took there).
Mentioned again → promoted back at `confidence = max(current, 0.6)` on the day it was said, read live or late (read
on time); a mention never lowers, and one from long ago revives nothing its age would not have kept alive. Evergreen
entities (the owner's page among them) skip all decay math. **Confidence does not rank recall:** search puts archived pages last and otherwise ranks
by relevance (`search_service._page`'s sort key and the per-kind cut's archived tier); whether
confidence should weigh in is a question for G148's benchmark pass to measure before anything
changes.

---
