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
  **So the app has a sync to do when it opens after being closed (G229, 2026-11-03):** a harness's own hook kept
  capturing meanwhile, the app's readers did not. The app says what its readers are doing (`PUT /sources/catch-up`,
  `reader_catch_up`, in memory) and every client reads it on `GET /devices/status` as each machine's `catchUp`, with
  what came in while the app was closed and since it opened counted from the bank (`api.md`, `app.md`). It writes
  nothing into a bank and reads no path.
  Apple Notes is the same: the app runs the AppleScript as its own child `osascript`
  (`AppleNotesReader`, `NSAppleEventsUsageDescription`) and posts the dump to `POST /sources/sync-notes`,
  which 422s without one — run from the launchd backend, macOS asked whether "python3.12" may control Notes.
  **Notes keeps up and is dated when written (2026-10-23).** `AppleNotesWatcher` reads after the person's own first
  read (Connect, Refresh, onboarding's tick), then on launch, after a bank switch and every two hours — only while
  Notes is already open, since `tell application "Notes"` would launch it; Disconnect stops it, deleting nothing.
  **Also when Notes is opened or comes to the front (G245, track C1):** `NSWorkspace`'s launch and activation notices
  (a notice, never a poll), after a 3 s settle and no sooner than 15 minutes after the last read of any kind, so
  switching to Notes over and over reads once; the same read, so a locked note's body is still never asked for. Each
  record adds the modification date as AppleScript's locale-free `«class isot»` and the Mac's UTC offset, so
  `notes_sync` dates the episode when the note was last written (read on time); the human `modified` string stays the
  dedup key, and a 6-field record from an older app still parses and is dated now.
  **An edited note is a revision of its one episode (G104, 2026-11-23).** `notes_sync` stages through `episode_staging`
  like every other source-keyed writer: `source_id` `apple-notes:<note id>` (or the hash of name and creation date), so
  an edit finds its episode and **edits it in place** — same id, same file, `processed: false`, a `revised` record — and
  Sleep reads only the changed lines (`episode_revision`); the note is one conversation for the 2+ rule, in
  `source_episodes` and in the References. Before, every edit minted a new episode and each re-read restated the whole
  note (measured on a real bank: 227 Notes episodes for 201 notes, six notes holding 32 of them). **The body is the
  title, the `**Folder:**` line and the text — never the modification date**, which changed on every edit and would have
  been the "changed text" of every revision; it is the episode's `timestamp` (moved to the edit's date when the words
  moved, `redate`, the id keeping its day, ruling 34) and `source_updated_at`. The index still decides what is staged:
  a note whose `modified` is unchanged is never staged, so it is never written; one whose `modified` moved with the same
  words (a touch) updates the index only and is not re-queued (the stager's hash match). **Upgrading** costs unchanged
  notes nothing. The first edit of a note whose latest episode an earlier version wrote (it carries `note_id`, no
  `source_id`; the index points at it) adopts it (`episode_staging.adopt_source`, one frontmatter key) and edits it in
  place: its old `content_hash` hashed the key and the date, not the words, so it reads as changed once, and the version
  Sleep read (git) still holds the old `**Modified:**` line, which the revision sees as one removed line and reads nothing
  for. Older episodes of the same note stay as they are (not repaired). A retired locked stub drops `source_id` with the
  rest of what named it, so a note unlocked later is new. A note deleted from Notes is not noticed (no tombstone), as before.
  **Locked notes (G234, 2026-11-04).** Every property the script reads is asked through `whose password protected is
  false`, evaluated inside Notes, so no event names a locked note's body (the view-time `body` of the note on screen too,
  ROR-15, held in memory and never posted, `app.md`); a locked note gives its id and its name, its
  own event and `try`, and neither enters the dump: the ids go in `lockedNoteIds`, the names only as hashes in
  `lockedNoteKeys` (`AppleNotesReader.split`; an older backend ignores the key and never sees those notes).
  The bulk lists are separate events, so the ids are read again last and a folder that changed in between waits for the
  next read; every folder refused is a failed read (`statsMark`). `notes_sync` drops a record flagged locked whatever it
  carries, never stages a record with no text (from an older app, which sends no ids, that shape is taken as locked),
  never stores the ids or the hashes, and keeps only a count (`sync_state.json`, `notes.locked`). `retire_locked` retires
  every episode of those notes by their own `note_id`, plus any Notes episode with no text, and drops them from
  `notes_index.json`. **A retired episode is an empty record by construction:** the file stays so its id is never reused,
  with `locked_note: true`, `source_deleted_at`, the title "Locked note" and no folder, tags, note id or body
  (`history_index.kind` `locked`). Text from before the lock moves whole, with its frontmatter, to
  `sources/locked_notes/<id>.locked` (`kept_path`), committed with it, because destroying it is the person's call. No
  reader carries a check, and none can forget one: `evidence.source_document` reads no document, every other reader of
  `episodes/` finds nothing, no walk of a bank's text a reader uses takes the suffix, and a test fails if any other
  module names the folder. Only Remove's walk takes it (`sensitive_purge.bank_files`, by suffix), below. The retirement clears the words index and drops the vectors at once
  (`_forget_derived`; `_without_locked_notes` holds if that fails). An episode #608 only stamped is finished by the next
  sync or Sleep. Sleep runs the same retirement first in `_index_without_model_safely`, whatever the tree's state, before
  ids freeze; a failed commit keeps the retirement. A note unlocked later is simply new. An older app's body read from a
  locked note open at that moment cannot be told apart.
  **Measured on real Notes (2026-11-04, one throwaway note, by id):** unlocked, `password protected` is false and
  `plaintext` the full text, title first; locked and open in the session, `password protected` stays **true**, `plaintext`
  asked directly returns the **full text**, and the reader's filter returns only the id; locked and closed, `plaintext` is
  empty. So the filter is the guard, and any read of `plaintext` without it would leak an open note. **Locking gives a note
  a new id** while its name survives, so an episode kept under the old id is found by a hash of the name (`locked_key`,
  made in the app, compared, never stored) and every episode of that old id goes with it. A note this same read saw
  unlocked never matches, whatever its title, and name keys go only with a complete read (`AppleNotesReader.split`:
  no folder failed or waited, nor a note dropped), since a partial read's "saw it" protects nothing. A locked note then
  retires on the next complete read; **a folder that fails on every read stops retirement by name altogether**, and its
  cost is that an older episode stays live, said nowhere but here. Name and not name-plus-date: a note edited before its lock (the usual way
  a secret gets in) no longer has the date Cicada kept, and that date is a string in the locale and time zone of the old
  read.
  **A pinned note (ROR-15 part 2, owner 2026-11-05: "having a note pinned is important, normally has a reason and can have
  some influence for consolidation").** Notes' scripting dictionary has no pin, so the app reads it from Notes' own store
  (`AppleNotesPins`): a copy of `NoteStore.sqlite` with its `-wal`, one query for `Z_PK` alone where `ZISPINNED = 1 AND
  ZISPASSWORDPROTECTED = 0` — never `ZICNOTEDATA`, a title, a snippet or a word, and a locked note's pin is never read
  (G234). A note's id is the Core Data URI `x-coredata://<store>/ICNote/p<Z_PK>` (Apple's `NSManagedObjectID`
  format); an id that does not map is simply not pinned, and only ids already in the unlocked dump leave the app, as
  `pinnedNoteIds` beside the dump. It runs only if Full Disk Access is already held (an `open(2)` probe, no prompt, no setup
  step, no copy asking for it), under a 10 s bound, off the main actor; without it, or on any failure, the key is absent
  and the backend leaves every pin as it was (`None` is "could not tell", `[]` is "none pinned"). `notes_sync` keeps the
  pin as a frontmatter `pinned: true` on the note's latest episode and in its index entry, written through
  `episode_staging.set_pinned` under the episode lock: **it is not in `content_hash`, never sets `processed` or `revised`,
  and changes no body**, so a pin moving re-queues nothing and a pin that changes on a note Sleep already read does nothing
  to memory (`test_notes_pinned.py`). It is not routed through the stager's body path because a pin is no edit. Stage 1 gets one line in that note's source note
  (`entity_extractor.pinned_note`: the person pinned this note in their Notes app) and the model judges what it means —
  no score, no rule; a pin alone makes no page and no claim, and the note is read under its normal rules. The row carries
  `pinned` (`SHAPE` `g161-21`) and lists first. Checklist ticks are out of scope: they would mean reading `ZICNOTEDATA`.
  **What a false match costs.** An episode of a note missing from a complete read (gone from Notes, or not there yet)
  is retired if its title equals a locked note's. A note gone from Notes never comes back: its episode stays an empty
  record and no route restores it; its words stay in the kept file and in git. A note that does return comes back as a
  new episode, whose words then count as a second conversation for the 2+ rule, and the old `.locked` file stays. It is
  left rather than removed on return because the empty record holds no note id to tie them, and destroying it is the
  person's call.
  **What retirement does not reach.** What Sleep already derived from the note before the lock (a claim's text, a page's
  prose, a question, a held mention) is the bank's own words, read like any other; only the person's decision or a
  Remove (`sensitive_purge`) changes it. Earlier versions stay in git history, which no route reads for an episode
  (`get_entity_commit_diff` is scoped to a page). The app's on-disk Store replaces a row on its next fetch.
  **Remove keeps its promise over the kept file.** Remove is the person's own act and finds a value with no model, so
  the file is still read by no engine and no agent door. By value: `sensitive_purge` walks and cleans the suffix like
  any file and `residue` counts it, so Remove on another conversation's row takes a shared value out of it, and never
  reports clean while it stands there. By row: a row waiting when the note was emptied survives (`record_for_stub`
  keeps the `sensitive` record on the empty record with `row_kept`), titled "Locked note", and its Remove or Leave it
  read the kept file (`notes_sync.kept_copy`, `sensitive_flags` alone asks), so a value only that note held stays the
  person's to remove. The row goes when the value does. A kept file never starts a row of its own: no `row_kept`, no
  read, whatever the detector would find there, and a value the person left before the lock is found only by value.
  A sync that retires brings the review item in step at once, one admitted transaction with its own commit
  (`_review_in_step`), so its row loses the note's title; while Sleep holds the pages, and for Sleep's own retirement, its
  tail does the same step, and an item dirty before it is left until the next pass.
  Two things stay: earlier versions in git history (as the review's copy says); and a guarded value (unsure or common in
  this bank), which stays out of a file not tied to its row, like any other, and is said in `stayed`. The hold (`sensitive_hold`) learns a
  value from `episodes/` only, so after retirement a value on a page is held back only if the page's own text shows it
  as one.
  **Limits:** a note locked after the last sync is retired only by the next one, so a Sleep in that gap can read it; a
  note whose first line (its name) changed between the last read and the lock is not found.
  **Where an item lives (2026-11-04, PR #599).** The script's ninth field names the note's Notes **account**
  ("iCloud", "On My Mac", a mail account's name); the app moves it out of the dump into `noteAccounts` (by note id,
  `AppleNotesReader.split`) so a backend that predates it, which checks a record's field count, still reads every note
  and ignores the key (a ninth field in a dump is read too). `notes_sync` keeps `account` and `folder` in each `notes_index.json` entry (and on a new
  episode's frontmatter), never in the dedup key, and places an unchanged note there without a new episode (a note moved
  to another folder, or kept by a sync from before accounts were sent; an 8-field record keeps the account already
  known). Calendar and Reminders post each calendar's and list's **`provider`** (EventKit's source type mapped on the Mac:
  `icloud`, `google`, `exchange`, `local`, `subscribed`, `other`; optional), and each sync keeps the calendars or ticked
  lists holding an item — `{id, title, account, provider}`, titles the bodies already hold — beside the channel's last
  sync (`sync_state.json`, `source_collections.after_sync`). An empty calendar's title stays out of the bank, and the
  **Notes keeps its shape (A.4, G245, ruling 78, 2026-11-24; owner: "respect the folder structure, pins, recently modified").**
  *Spike (macOS 27, one real library, depth histogram only):* Notes' scripting returns **nested folders** — `folders of acc`
  is flat and lists every folder at any depth once, each with a `container` that is its parent folder (or the account);
  the order is not alphabetical, and a child can be listed **before** its parent, so no reader may assume parent-first;
  `Recently Deleted` is one of the folders (a localised name; its notes are read today as any folder's). The script adds,
  beside the notes, `cicada-folder` rows (account, folder id, parent id, name), `cicada-folder-held` (a folder whose every
  note is locked: its name stays out of the tree, because it would say locked notes live there) and, only after the
  unlocked lists lined up, one `cicada-at` row per **unlocked** note (note id, folder id); a locked note is never named by
  any of them and no property is asked outside the unlocked filter (G234 untouched). `AppleNotesReader.split` takes them
  out of the dump (a 9-field record is unchanged) and builds each note's **path** (names outermost first, walked up the
  parent ids, a loop or a missing parent names none) and the folder list in Notes' own order; they post as
  `noteFolderPaths` (by note id) and `noteFolders` (`[{account, path}]`) beside the dump, so an older backend ignores
  them. `notes_sync` keeps the path as `folder_path` in the index entry and the episode's frontmatter — **never in the body,
  which names the leaf only, so no hash moves**: an existing note is *placed* (index + one frontmatter key through
  `episode_staging.amend_frontmatter`, `processed` and the queue untouched, no second episode), a pin or a move never
  re-queues Sleep. A path must end in the dump's own folder or it is ignored; a folder below `CICADA_NOTES_EXCLUDE_FOLDERS`
  is excluded with it. The folder list and `pins_read` (whether the app could read pins at all, which needs the Full Disk
  Access it already holds, never prompted for) sit beside the channel's last sync (`sync_state.json`). A folder is a
  filing label: no page, claim or link, never evidence, never a conversation for the 2+ rule.
  **The collection id** of a top-level folder is what it always was (`nf-` + hash of account and name); a nested one hashes
  its whole path, so two folders of one name in different places are two collections and nothing already filed moves.
  `collections` returns each account's folders as a tree walked top-down in Notes' own order (a folder the list does not
  name — an older app's — follows by name), an empty folder included, each with `path`, `parent`, `children`, `depth`,
  `count` (its own notes) and `total`; items list by the modified **instant** (pinned first), carry `modifiedAt` and a
  one-line `snippet` (the first line of the text after the title, scrubbed, none for a one-line note, a locked stub or a line
  the sensitive finder is sure of), and both answers carry `pinsRead` so the page can say pins could not be read.
  pickers read EventKit, not this. `GET /sources/channels/{id}/collections` answers accounts → collections
  (count, newest day) for `notes`, `calendar-local` and `reminders-local` (iCloud first, then this Mac, then the rest
  by name; a collection by name; one a later sync no longer names — a list unticked — keeps its name and lists while it
  holds items), no accounts for any other channel;
  `GET …/items?collection=` narrows a page to one collection (a calendar's id, a list's id, a Notes folder's opaque
  `nf-…` id). A meeting row carries `duration_s` (SHAPE `g161-16`). Read-only, engine-free, never a Store domain.
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
  **Where Safari keeps them (checked on macOS 27.2, 2026-11-03).** One file: `~/Library/Safari/Bookmarks.plist`
  holds every bookmark and the Reading List, for every Safari profile (Apple: profiles separate history, website
  data, extensions and Tab Groups; bookmarks and Favorites are available to all of them). It is written by Safari
  and — Safari open or not — by iCloud's own Safari sync, `SafariBookmarksSyncAgent`, a launch agent that runs
  without Safari, receives iCloud's push for another device's change and merges it into that file (its sandbox
  profile, embedded in the binary, grants it `~/Library/Safari/Bookmarks.plist` and Safari's lock, and its own log
  strings start a bookmark sync "in response to a push notification"). In Safari's container, `SafariTabs.db` holds Tab Groups and their tabs (its `bookmarks` table is
  the tab tree, not bookmarks) and `CloudTabs.db` other devices' open tabs. So the app reads the one file, and a
  bookmark saved on another device reaches Cicada exactly when iCloud has merged it there; a file that has not
  moved has nothing new. The live case that settled it: Safari's file unchanged for five days, Safari.app not run
  on that Mac in that time, and the sync agent's one bookmark-container check in its retained log window finding
  only a settings change — nothing new had reached that Mac to read. The page now says what "up to date" is
  measured against (`BrowserFreshness`, `app.md`), and a launch reads nothing until the active memory is known.
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
  `edited_at`; the words it replaced stay on the answer as `before`, oldest first, at most 10, dated when they were
  set — for the app's history only, never in the section Sleep reads, 2026-11-23), `processed: false` so Sleep reads it
  again — on any later cycle, however long after the first read — committed
  alone as `user` (trigger `user/saved_why`) inside the write admission (409 while Sleep holds the pages, 409 in a demo
  bank, 404 for a link not saved, 422 for an empty or unknown answer). Reason ids are a closed, stable set —
  offered (G191 v4, owner 2026-10-15: "keep options to a minimal"): `design` "The design", `product` "The product",
  `read_later` "To read later", `someday` "Useful someday"; retired but still read and still accepted: `technique`
  ("A technique to reuse") — labels separate (`saved_why.LABELS`); `project` is a project page's id (a live one, or on
  an edit any — the panel no longer offers projects; Sleep may infer the link); `text` is the person's own words
  (≤ 500). `GET /sources/saved-why/options` serves the four reasons and an always-empty `projects` — deterministic, no
  model. `explore_plan` reads `someday` as the minimal capture, like `read_later` (the page as it looked when saved). The wire for a later
  reader is the source record: `GET /sources` → `items[].savedWhy` `{reasons, labels, project, text, at, addedAt,
  editedAt, via, before}` (`via`: where the answer was given, an origin key the app draws — `chrome-bookmark`, `cicada`;
  422 for anything else), read from the episode (null when nobody was asked), with `savedWhyHistory` (every answer, oldest first,
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
  (`<harness> <sid8> Stop|PreCompact|SessionEnd|other …`), so ruling 7's revisit signal — a Stop `no answer` line,
  and since 2026-10-29 the `in <n>ms` round trip on every answered line — is never confused with a flush's; the capture
  ledger row carries the same enum as `event`. **The answer never waits on a slow write (2026-10-29):**
  `/capture/transcript` and `/capture/session` run the writer off the event loop and answer within `CAPTURE_ANSWER_S`
  (2 s, `routers/capture.answer_within`); a write still running then answers `202 {"status": "accepted"}` (bank and
  `bankId` named, no episode id yet) and finishes on its own — same lock, same find-or-create, same refusals — and the
  awake read is queued when it lands. Finding a session's episode reads no episode it has read before: a per-bank index
  (`transcript_capture._SessionIndex`) keeps each file's `session_id` from its frontmatter lines and re-reads only a file
  whose mtime or size moved (a stat sweep, ~30 ms at 8,700 episodes); a live session's later Stops check only their own
  file. Before, every new session's first Stop read every episode in full under the capture lock (0.45 s warm, 1.4 s
  cold at 8,700), serialised across sessions firing together. **A local post that gets no answer** in the hook's 3 s
  (backend down, hung or starved) logs `no answer (timed out at 3s) … spooled for a later firing` — never `error:` — and
  its request (the hook's fields: a path, never the transcript's words) waits in the client's spool (`hook_spool`, one
  entry per session, `route: /capture/transcript`, target the loopback port); a 5xx waits the same way. The session's
  own next landed firing drops it, and any other session's landed firing sends up to three waiting ones within its 4 s
  budget (never on SessionEnd); a client's `/capture/session` entries are never sent to the local port. No spool folder
  is made on a machine where nothing waited. `autosave` in
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
  changes the body and re-queues the episode — no `metadata` short-cut, unlike the head-only cap it replaced (since
  2026-11-03 Sleep reads it as a revision: only the changed tail with its context, `episode_revision`, and a
  transcript's slid-out turns close nothing); (2) when the tail slides, a claim quoting a turn that slid out is re-extracted as
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
  row's help and spoken label (`received`), recall's excerpt label. **A source's recency is its receipt (CIC8,
  2026-10-29):** every "connected · <when>" a source shows — the overview's `last_activity_at`, an import channel's
  `last_sync` — reads `episode_time.delivered_at` (newest of `received_at`, `captured_at`, `last_turn_at`, else
  `timestamp`), so an import of year-old chats reads "today"; `episode_time.is_later` compares one stamp shape as
  strings and parses only a mixed pair (list-route p95 unchanged, measured on an 8,000-episode synthetic bank).
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
  connector word — runs before every writer's hash and write (**names and URLs, ROR-132, 2026-11-06:** a vendor prefix
  starts after anything that is not a letter or digit, never at `\b`, which does not fall after an underscore; a
  `NAME=value` credential takes any prefix on its name — `DB_PASSWORD`, `AWS_SECRET_ACCESS_KEY` — a bare name keeps
  G105's 12 characters, a prefixed one 8 and a value that looks like a secret; the value is one token, bare or quoted,
  and the name and separator stay; a `scheme://user:PASSWORD@host` password goes in the body and in a URL field;
  `placeholder_value` keeps variable references, templates, masks, expressions, `x`-runs and `your_…_here`, the one
  test `sensitive_text` shares; a key prefixed `sk_live_`, `glpat-`, `npm_`, `hf_`, `SG.`, `xai-`, `gsk_`, `pplx-` is taken
  too; forward-only, a stored body is the finder's, never rewritten here), and `test_episode_writers_scrub.py`
  fails for any module that mints an episode id without it. `api/services/episode_staging.py` is the
  G20 stager they share: an `EpisodeDraft` keyed by `source_id`, the hash over the scrubbed body, an
  edit rewritten in place with `processed: false`, a rename kept by content hash, a deletion
  tombstoned (`source_deleted_at`) and never unlinked. **An edit in place says it is one** (owner 2026-11-03: "re-ingested
  items are updates, not new"; G95): `update_in_place` writes `revised: {count, at, previous_hash, consolidated_hash?}`
  (`episode_staging.REVISED_KEY`, `revision_record`) — the number of body edits so far, when the latest landed, the
  `content_hash` of the body it replaced, and the `content_hash` of the last body that was consolidated (processed by
  Sleep or an agent, never by a parser or the index), kept through later edits until Sleep reads the episode again and
  absent while no revision was ever consolidated. It is what Sleep reads to treat a re-queued episode as a newer
  revision of what it already filed; the earlier body is in git. A new episode, a metadata-only refresh, a re-date, a
  rename and a tombstone write none. A multi-turn source records G118's per-turn
  sidecar `turns: [{offset, ts, speaker, model?, effort?}, …]` (R-PB4: an entry only for a turn with
  a time, the last key, outside `content_hash`, capped head-stable at 500; `model`/`effort` only on
  an agent turn (round 4 C1)) — the one shape `evidence.turn_stamps`
  reads. The Stop hook writes it too since G141 PJ-4 (R-PJ16): its `role: text` body is the stager's
  line shape, so `episode_staging.stamps_for` builds the list, and the episode `timestamp` stays the
  session's start while each turn carries its own time. A Stop-hook episode written before PJ-4 still
  holds an integer count, which reads as no stamps.
- **A watched folder says what it left out (2026-11-06):** a file over `FolderScanner.maxFileBytes` (2 MB) or one the app
  could not open was collected in `FolderReadResult.tooLarge` / `unreadable` and read by nothing, so the row showed
  "Synced" for a folder missing files. `LocalSourceWatcher.folderSkipped` now holds one line per folder
  (`LocalSourceCopy.skipped`: the file named, why, the rest counted) that the row draws beside the light until a scan that
  reads everything clears it. What is read and posted is unchanged.
- **A local source is read by the app and parsed by the backend** (G133/G134). A watched folder:
  security-scoped bookmark, FSEvents, an mtime+size+sha manifest, bytes posted with relative paths to
  `POST /sources/folders/{id}/sync`; files under an agent glob land as `evidence_kind: assistant`,
  already processed, so an agent's sweep is never the owner's words. Saving new rules re-derives
  every existing episode of the folder in place — frontmatter only, the hash unchanged; agent → owner
  is queued, owner → agent is parked unless Sleep already read it — in one `user` commit (trigger
  `folder/authorship`), and the papers' why-claims follow (F2-back R-B6, R-B7). Wispr Flow (**off for now, owner
  2026-11-04: nothing new is read, for anyone, while `SourceCatalog.wisprOffered` is false; its episodes stay and
  Sleep reads them as any other, `app.md`**): its SQLite opened
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
  **Ruling 47 tier 2 — Notion live (`connectors/tier2.py`, 2026-10-29; Readwise, built beside it, was removed by owner direction 2026-11-03 — its origin still scrubs and draws its mark for a bank's earlier episodes).** A connected source's sync stages
  through `episode_staging` like every capture (no model, scrubbed, `connector: <id>` in the frontmatter) and commits
  only its paths as `user` (trigger `capture/<id>`), the staging and commit as one admitted transaction: while Sleep
  holds the pages it is refused, nothing is written and the cursor stays, so the next sync fetches the same items. The
  scheduled sync runs on the backend's scheduler (every 6 h), never in Sleep's tail. *Notion:* a shared page is `notion:<id>` — the export's
  key, so the live read rewrites an exported page in place — split by H2 like the export, dated when created, a row
  with its database's title and properties; trash tombstones; unsharing keeps the page as it was (origin
  `notion-api`). A page is the person's words only when Notion names the connection's owner and that user created
  it; otherwise `assistant` + `notion_by_other`, never the person's on a guess. A unit stored as someone else's
  (`assistant` or an export's `*_by_other`) is never moved back to `user` by any later tier-2 read. The first sync
  walks the whole history (Notion's own cursor, 150 pages a sync, "Reading your shared pages: N so far"); the
  high-water mark moves only when nothing older is left.
  **Notion keeps its place (A.4, G245).** A page keeps `notion_database` (its database's title), and `notion_path` +
  `notion_path_ids` (the parents it sits under, outermost first, the database last), read from the page's own
  `<ancestor-path>` block — nothing is fetched to name a parent, and on a **chosen** scope only parents inside what the
  person picked are kept (a teamspace page above the chosen root is dropped). The REST path files a row by its database
  alone. `FORMAT` 3 re-reads each page once to learn them: a page whose words did not move gets the three keys in frontmatter alone (`episode_staging.FILING_KEYS`, like `provider_project`), never re-queued. `notion-api` has a collections tree (`channel_items._notion_tree`:
  one unnamed account, folders by parent chain, `unfiled` counting pages read before their parents were kept) and lists by
  `notion_last_edited`, not the created day. Favourites and the Private/Shared split are not read. *The `<ancestor-path>`
  tag shape is the one the stripper already names; it is covered by a fixture, not yet seen against live Notion.*
  **GitHub (G230, `connectors/github.py` + `github_repos`).** Every sync reads both lists whole (no cursor; GitHub's
  numeric repository id is the key, so a rename or a transfer keeps its page). *A repository the person owns* is
  `github:owned:<id>` (origin `github-owned`): its name, description, language, topics and visibility, staged and
  **index-only** (`history_index.LIST_ORIGINS`, ruling 30's posture — a record GitHub keeps, never the person's words,
  never a model read, never a mention), dated when the repository was created. It makes **no page**: it is offered on
  the Sources row (ruling 36 D4 / 45 — a project is born only from the hook, the person's words or the person's act).
  One gone from a list read whole is tombstoned and kept; a list cut short at 60 pages (3,000 items) tombstones nothing.
  *A repository the person starred* is a save, like a bookmark: one `media` page (`media.kind: repository`) and one
  index-only save episode (origin `github-starred`) through `media_ingestor`'s write path, dated when it was starred; a
  github.com link already saved (a bookmark of it) becomes that page rather than a second one. The page and its
  episode are written in the same admitted transaction and commit as the episodes (`tier2.Batch.after`). A later sync
  rewrites the page's `github:` block only when GitHub's record changed (never for a star count or a push), and a
  repository no longer starred keeps its page with `starred: false` and the day it was seen gone, said on the row in
  words ("N repositories are no longer starred on GitHub; their pages stay"). Nothing a sync does deletes a page or an
  episode, and a sync never brings one back: a page the person merged away is followed to the page it became
  (`page_redirects`; a `media` winner is updated, any other kind left alone), and one removed with no redirect stays
  gone — only the person's own add makes it again. *A repository the person adds* by its link (`POST /sources/github/repos`, origin `github-added`) is a save
  they made on purpose: its episode is read by Sleep like any single link they save. Pages are quiet until mentioned
  (`quiet_pages`: import evidence only).
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
  (`sleep/where-to-check`), dirty pages skipped, undone on a failed commit (`storage.md`, "Where to check"). Then
  **In short** (`_in_short_safely` → `in_short.run_tail`, ruling 48 part 5, 2026-10-29): pages with ≥ 400 words of
  article and ≥ 5 conversations in the last 30 days (by each conversation id's own day; a feed item or a watched day
  is none), busiest first, at most `in_short_per_run` (10; 0 is off), only when the article's hash changed, get 2–3
  sentences in `in_short:` on the engine the person's choice resolves to, at its small tier (haiku on the Claude plan),
  a scheduled run on a plan only through ruling 4b's switch; no qualifying page resolves no engine; a plan limit pauses
  it; one commit as the model (`In short <day>`); demo banks included (nothing comes from outside); skipped when the
  run stopped at the plan's limit. Measured on an owner-scale copy: 32 pages qualify, ~4.2k tokens in and 80–600 out
  per page, 2.6–4.5 s each; the candidate scan is 1.9–3.4 s. **Recording notes** (`_media_read_safely` → `media_read.run_tail`, ROR-117 3b, ruling
  68 (e)): the same slot and engine rules; an added file's `media` page whose words have not been read (`media.read.words`
  a hash of them; a transcript that changed is a new version) gets one call of the words from the start up to 30,000
  characters (whole passages, picture text beside the speech) and a small memory view chosen with no model (the owner's
  page; the pages the words' rarest repeated terms find, title and a line), at most `media_read_per_run` (5; 0 off), demo
  banks none. It writes `## Summary` ("Read from the first N minutes." when it stopped short) and, only when the
  sentence names a page the view showed, `## Why it matters`; a section is Sleep's only while empty or its own text (a
  hash in `media.read`), pinned fixes reapplied, `media.read.by` the contributor beside the transcriber. No claim,
  question, link or episode. A failed read is noted in `read.json` in the store (3 tries, 12 h apart); the click is
  `POST /files/{id}/read` (409 while Sleep runs). One commit as the model (`Recording notes <day>`). At haiku list price
  ($1 / $5 per million tokens) a one-hour recording is ~7,500 tokens of words plus ~900 of directions in and ~250 out:
  about $0.01. **Stopping Contacts forgets them (review of #391):** Disconnect, or the app finding
  access refused or taken away in System Settings, calls `DELETE /sources/contacts-local/waiting`, which deletes every
  bank's `contacts.json` and thumbnails (Contacts is app-wide; token-gated like every route; counts only), so no first
  mention and no tail rematch uses a card again; what matched pages already gained stays. LinkedIn's kept export has
  its own forget, `DELETE /sources/linkedin-connections` (this bank; *Forget kept connections* in the LinkedIn panel).
  **The page's faces are a second store, not a way into the first (owner 2026-11-04, `contacts_book`).** The waiting
  set keeps only what Sleep could match, so a page reading it can never show a one-part name. The app also sends every
  card's names and thumbnail, before the sync and best effort, to `PUT /sources/contacts-local/book`, kept at
  `$CICADA_HOME/people/<bank>/contacts-book/<scope>/` (never which facts a card holds, its id only hashed, never an
  organisation's name: a card with no personal name is kept nameless). `WaitingIndex`, `seed_page`, `rematch` and
  `waiting_status` never read it (`test_contacts_book.py`), so the match rules and the `waiting` count mean what they
  meant. `GET …/book` lists the cards, those with a page first; the link is read from the pages' `addressbook://`
  sources each time (one holding only a photo joins by name when exactly one card carries it), so a rematch or a removal
  shows at once. `GET …/book/{key}/photo` serves a thumbnail, `no-store`. It is the app's own read: the token's device
  picks the scope, so a client of a backend elsewhere reads only the book it posted; on a copy the routes are `local`,
  because the reader is here and not at the home. No tool, CLI row or `/v1` operation reaches it, and the remote
  listener has no such path. **The book's own state decides when it is posted (review of #602):** a sync posts it, and a
  launch with no sync due asks `GET …/book` and posts when the backend holds none or the last book it took is older than
  the address book (`ContactsReader.shouldPostBook`, its own token beside the sync's). A failed post is tried again 3
  times, a minute apart, then said in words; a refusal is final; a stopped reader asks nothing; a truly empty address book
  posts nothing. The forget removes every scope in every bank (`DELETE …/book` is the same forget, sent too
  because a copy forwards `/waiting` to the home); revoking a device removes its scope and stops a save already in
  flight (`.contacts-book-revoked`, scope hashes only); a demo bank takes and shows none. Few photos is true of the book: on the owner's Mac the store files hold at most 6 raw records with one, of 969
  raw records (count-only, 2026-11-04; size and format not measured).
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
  `GET /sources/linkedin-connections` gives its day and size, never a name; **the one route that names them is
  `GET /sources/linkedin-connections/list`**, below), and Sleep's engine-free tail matches it
  against the night's pages (`_rematch_linkedin_safely`, after source links, before any poll; its own `cicada` commit,
  `sleep/linkedin-connections`, dirty pages skipped, undone on a failed commit; never in a demo bank) — so a person who gets a page later
  gains their link and facts then, and nothing is ever said about anyone without one. Nothing is fetched: the link is
  where to look the person up; the profile-photo rung may use it only once the person takes the source (its own
  off-by-default gate, `person_photo`, unchanged).
  **The way in without a file, and the date (G245, ruling 78 (c), owner 2026-11-24: "who i have connected with and in
  chronological order which to me is super important").** The person's own agent opens LinkedIn's connections page
  (sorted by recently added) in their own signed-in browser and records `{name, profile_url, headline, connected}` per row
  (`cicada_record_saved_list`, platform `linkedin-connections`, base `linkedin`, off until turned on, the connections page only —
  never a profile, never the contact-info overlay, no email field; `mcp.md`). `linkedin_people.record_read` **merges** the rows
  into the directory above by profile link: it never deletes a row, never moves `exported_on` (an export's own day; a read keeps
  `read_on` beside it, and the tail's day is `exported_on`, else `read_on`), keeps the finer day, and keeps a row only a read knows
  through a later export (`src: read`). `connected` is an ISO day when the page shows one, else the page's own words
  ("3 weeks ago"), from which `parse_connected` stores a **day and a precision** (`day` · `week` · `month`; a year is
  counted to the month) computed from the day it was read — nothing relative is stored; words it does not read (another
  language) leave the row undated, and the reply says how many. The `headline` is kept as the page showed it (never split into a
  company and a position, so a read writes no `works-at` or `role`; only the export's columns do), and a `connected-on` claim for
  a week or month precision says "around <day> (known to the week)". No model reads it. **The list the app draws:**
  `GET /sources/linkedin-connections/list` (`query`, `since`, `until`, `offset`, `limit` ≤ 200) — newest first, each row's name,
  headline, link, day, precision and **the matched page's id when there is exactly one** (one page index per request, the same
  rules as the tail below), an ETag that is a digest of the body (not a Store domain: the app caches it in memory). **This
  amends "the directory's API gives its day and size, never a name" for this one route:** local API only (absent from `/mcp`,
  `/v1` and every remote door), 409 on a demo bank, nothing written, wiped by `DELETE /sources/linkedin-connections` and by
  trashing the bank. On a copy it answers from that computer's own directory and is not in `GET_FROM_HOME`, as the Contacts
  page's book (`contacts_book`); the home's reads reach it through the tool's `replica: home` row. The stream
  `linkedin.connections` in `GET /sources/streams` counts the directory. **A row with no profile link is never keyed or
  merged with another** (`Connection.dup` numbers same-name ones, so two stay two and the same-name refusal fires on a re-import);
  such a row and a later read of one person with a link become one connection only when it can be told safely — the one
  name in the directory, the same connected day to the day, the read the agent's — else they stay two. `imported_at` is the
  day of the latest export's import (a read never moves it).
  **The person gets the page, never the connection (owner 2026-11-24: "a linkedin connection doesnt need a page just for
  the sake of having a page, the person is what gets a page"; ruling 78 (f) withdrawn).** A connection alone never makes a
  page: the import, the list and the tail make none (the 2+ conversations, exchanges and link rungs are untouched). What
  makes one is **the person's own full-name mention** — the next paragraph. What changed first was *when the match lands*: `linkedin_people.Attacher` attaches the kept connection that matches
  the person **in the write that births their page** — Sleep's Stage 5 create (`conflict_resolver.apply_changes`, one
  instance per batch, the directory and the page index read once, every page born since added so two pages of one name
  born in one batch see each other) and a **local** agent's first claim about a new person (`agentic_write._ensure_subject_page`;
  a remote caller's never does — its page's making would tell it whether a guessed name is one of the person's connections,
  and the night's tail attaches it) —
  not at the night's tail, which still catches a page made some other way (by hand, a split, a page dirty at the tail).
  The link is a `sources:` entry exactly as the tail writes it, with `works-at` / `role` (an export's columns) and
  `connected-on` as dated claims observed `external:linkedin`. So **one person across the two directories** needs no new
  rule: a waiting Contacts card and a waiting connection with the same full name are the same lead — the card's existing
  promotion (the person's own full-name words, exactly one card) makes the page under the card's name, and the page is
  born with the card's sources and the connection's link; a held name in the pending store that equals exactly one
  connection's full name carries nothing into the bank while it waits, and its page, when a second conversation or the
  usual bar births it, is born with the link. **Never the wrong person (`_hits`):** a name-only match is refused — written
  nowhere, counted (`Report.doubted` for a doubt, `ambiguous` for two) and never named — when the bank holds a same-name
  doubt for that name (`same_name_doubts`: a doubted pair or a flagged one; a page's names and a held line's own name
  count), when two connections or two pages share it (a page born the same name as one already there counts), or when the
  page names a different profile; a link the person or an identified agent listed (`match: link`) is not a name-only match.
  **One full-name mention is enough for a page (owner 2026-11-24, asked whether one mention of a connection with no
  Contacts card suffices: "yes it should be enough").** A `person` mention the person made in their own words
  (`named_by_person`, in a conversation) whose name or an alias is exactly one **waiting** connection's given + family
  name, either order, with the full name standing in one of the person's own marked turns, makes the page that night
  (`entity_resolver._connection_for`, beside `_card_for`; only when the usual rules and a card or number card did not
  already promote it). Every refusal of the Contacts rule holds: never the owner's name or a self-reference, a relation-only
  mention, a name two rows share (two links, or two rows with no link told apart only by `dup`), a name under a same-name
  doubt, a name an existing person page holds (or a name a waiting Contacts card also carries: that card's rule decides and
  the page is born with both, as above), an agent's reply, a relayed turn, a save, a tab group, a calendar entry or a feed
  item. A link pasted in a turn is blanked first: a profile's slug is the name spelled, never said. "Waiting" is read by
  `linkedin_people.waiting_connections` over `arrivals` (the bank's own pages, its doubts and the owner's names): a name is
  offered only when every kept row of it waits. The page is born under the connection's name (the said form kept as an
  alias; a second spelling in one batch joins it), and Stage 5 attaches the connection **in the same write, its link only
  proposed** (`Attacher.attach(how=MATCH_ALIAS)`: `match: alias`, `proposed: true`, the grouped "Confirm N links" review): a
  connection list is far larger than an address book, so the name alone makes no photo request (`person_photo.is_own_account`
  is false for it), never reads as "from their connections", and the night's rematch keeps it a proposal until the person
  takes it. The proposal is no acquaintance for ruling 44's public-figure test (`web_context.known_personally` reads
  conversations from a personal channel and relations, not a page's `sources:`). The Stage 2 guards that read the pages'
  names and each episode's kind now run when either a card **or a connection** waits (a bank with connections and no waiting
  card once read an empty set). **The person's own notes (the coordinator's reading of the owner's example, 2026-11-24 —
  "wrote some in Apple Notes" — not his ruling):** for a connection only, a full name standing as whole words in the person's
  own Apple Notes or Notion note counts too (`CONNECTION_NAMED_IN_OWN_NOTES`, `_said_in_own_note`; one line to turn off): the
  folder is a filing label and blanked, a locked note (`locked_note`, a stub, `Locked note`), an agent's saved note, a
  shared Notion row (`notion_by_other`), a save or a clipped page (`authorship.is_saved`) never count, and a note cannot be
  told from text pasted into it. The Contacts rule is untouched: a note never promotes a card. A connection nobody mentioned
  makes nothing.
  The tail, the export's import and the list's matched page apply the same rules. A link the person removed
  (`sources_removed`) stays removed at birth too. Not built: pages for pages made by hand reach their connection only at
  the night's tail; a split page (a doubt by definition) is refused.
- **The accounts the person follows on X (G245, ruling 79 (b); owner 2026-11-24: "Should the accounts you follow be read?"
  "2. yes"; `follows_people.py`).** Treated like a LinkedIn connection and held to the same line: *the person gets the page,
  never the account* (a followed account's own words are never the person's, and following is not acquaintance, ruling 44).
  The person's own agent reads their Following list (`mcp.md`, "The accounts the person follows on X") into
  `$CICADA_HOME/people/<bank>/follows-x.json` — outside every bank and git, 0600, per site: display name, handle, profile
  link, the day first seen, the day this stretch of following began (`since`), last seen and `gone_on`. **No bio, count,
  picture or "follows back"; no episode, no media page, no commit; nothing logged but counts; no model reads it**, and
  `GET /sources/follows/list` (local only) is the one door that names an account. A bank's trash or rename takes the folder
  along (`people_directory`), and `DELETE /sources/follows/{site}` removes every account, handle and link it holds.
  **Attaching to a page that exists** (`rematch`, Sleep's tail in its own `cicada` commit beside the connections' and
  Contacts', `trigger: sleep/follows`, pages dirty before it ran skipped; and `Attacher`, in the write that births a person,
  organisation or tool page — Stage 5's create and a local agent's first claim): *a match on a link the page already holds*
  (a `sources:` entry that is the person's, an identified agent's or one the person took — never a proposal still waiting)
  is the match beyond doubt and writes ONE dated claim `followed-on` (object the site, `observer external:x`, `origin
  follows/x`, `valid_from` the day this stretch began, evidence `reasoning`); *a match on the display name alone* (the page's
  folded name or alias, both orders for two words; a person page needs two parts, an organisation or tool a real word)
  writes only a **proposed** profile link (`match: name`, `proposed: true`, the grouped "Confirm N links" review) and no
  fact — names on X are free text; once the person takes the link the page holds it, and the next night writes the fact.
  The claim closes (`valid_to`) only when the account is marked gone (`mcp.md` for the rule), and a gone account followed
  again gets a new dated claim. **Refusals** write nothing and are counted, never named: a same-name doubt (`same_name_doubts`),
  two pages or two followed accounts of one name, two pages holding one handle, a page that already names another handle of
  the site; a link the person removed (`sources_removed`) is never put back, and the owner's page, a project, a place, a
  concept, a media page and a dropped page gain nothing. **It is never a mention:** nothing here touches promotion, a
  conversation count, `last_referenced`, `learned_on`, `decayed_through` or the page's status, and a followed account never
  makes a page (a test walks the entities folder before and after). A demo bank takes in nothing. The photo rung does not
  draw a followed account's link (`person_photo.is_own_account` is false for Cicada's own link outside the connections'
  exception). **Names never leave (`name_guard`):** a followed account's display name and handle are blocked from any web
  query like a connection's, except one the bank already has a page for — then the page's own rule governs, so a company, a
  tool or a public figure the person follows stays searchable (following is not acquaintance); a follow file that cannot
  be read fails the guard closed; the settling agent's address-book read leaves follows out (`store_names(
  include_follows=False)`): no model reads that directory. **Consequence to watch:** a private person's name that is
  known only from the follow list (no page, nothing public) can no longer be a search's subject.
- **Meeting transcripts — Hex, any recorder's folder (G95, owner ruling 2026-11-03: "Meetings ofc should also be
  consolidated in memory").** A meeting folder is a watched folder of `kind: meetings` (`folder_source.register(kind=,
  recorder=)`; set on the first add, never flipped — a folder added before G95 has no `kind` and is notes
  (`kind_of`), and adding an already-watched folder as the other kind is a 409 with its words, `KIND_REFUSAL`, nothing
  written): the app holds the bookmark, watches it and posts the bytes of changed
  files to the same `POST /sources/folders/{id}/sync` with the Mac's IANA zone (`tzName`; a name this machine cannot read, a directory such as `America` included, is
  this machine's zone instead); the backend never opens it.
  It anchors no project, has no papers step and no authorship rules, and syncs as its own channel, `meetings:<id>`
  (`channel_for`, `folder_id_of`; a notes folder stays `folder:<id>`). `meeting_transcripts` is the one parser: **one
  episode per meeting** through the stager (`source_id` `meetings:<folder>:<relpath>` — an edited transcript is rewritten
  in place and re-queued, a rename keeps the episode by content hash, a deletion is tombstoned; files whose names carry
  the same `YYYY-MM-DD HHMM` are one meeting and the newest holds it, G104 slice 3 below), `queue_for_sleep` like
  any conversation — unlike a recording the person adds as a media file (`media_files`, read only for `media_read`'s prose). Dated by
  the meeting's own start (ruling 39): the file name's `YYYY-MM-DD HHMM` (Hex's), else a `Date:` line, read as wall time
  in the posted zone, else the file's time; a day with no time is the file's own time when that falls on the same day,
  else that day's midday (never its midnight, which a reader in another zone shows as the day before); the id day is
  the meeting's local day (ruling 34); each turn's `ts` is the start plus its offset when the start is stated to the
  minute, else the offset alone. Formats, read by content: **Hex** (anoma.ly/hex, MIT; `<YYYY-MM-DD HHMM> <title>.md` in the
  Hex meetings folder — the app resolves it from Hex's own `meetings.output_folder` setting, that one key of Hex's
  settings file, else Hex's default under Documents; the file is never renamed, so its relpath keys the meeting) — `# title`, `- **Date:**` / `- **Duration:**` /
  `- **Attendees:**` bullets, an optional `<!-- hex:notes -->` summary block with its writer's footer, `## Transcript`
  with `**You** · 00:00` / `**Them** · 00:05` headers (the older `**[mm:ss] You:** text` too); a Hex folder excludes
  Hex's `audio/**` bundle (WAVs, `manifest.json`, duplicate and translated transcripts). **WebVTT / SRT** (a `<v Name>`
  voice or a `Name:` prefix; same-speaker cues merge), **JSON** segments (Whisper / WhisperX `segments`, `utterances`,
  ndjson; `speaker`/`source`, `start` or `*_ms`), and **text** (`Name: words` only in a file where several lines say so,
  `[00:01:02] Name:`, `Name (00:01:02):`, `**Name:**`, Otter's `Name  0:00` header over its words). A file holding no
  transcript (`manifest.json`) is the sync error "not a meeting transcript", never an episode. **Whose words (TODO
  ruling 52a, decided 2026-11-03):** a line the recorder labels `You` (Hex's microphone track) or `Me` (the same
  convention elsewhere) is a `user:` line — the person's own words, an exchange for promotion; every other utterance is
  `speaker:<label>:` (evidence kind `speaker`, G134's seam; Hex's `Them` is `speaker:them`), a line with no speaker
  `speaker:unknown`, and the recorder's model-written summary an `assistant:` line — never the person's, never an
  exchange. Every line of the summary is quoted (`> `, `meeting_transcripts.summary_text`, the chat importer's
  attachment convention), so a summary line reading `User: …` or `speaker:x: …` never opens a turn. No name is ever guessed to be the person; nothing is unmarked, so R4 never credits the person with an
  unlabelled line, and no `evidence_kind` is declared. The episode's `meeting` record (`recorder`, `format`, `speakers`,
  `own_labels`, `duration_s`, `summary_writer`, `attendees` — a calendar's invitees as the file lists them, never G179's
  `participants` rows) reaches Stage 1 (`sleep_cycle` passes it), whose `meeting_note` says which lines are the
  person's, that `speaker:` lines are someone else's, and that the summary is the recorder's; `consent: unknown` (G95's
  rail). **Unnamed speakers (ROR-142):** a label the recorder gave someone it could not name — Hex's `Them`, a
  diarizer's `Speaker 1`/`SPEAKER_00`/`Speaker A`, Otter's `Unknown Speaker`, AssemblyAI's bare `A`, a numbered JSON
  speaker, the Spanish `Hablante 1` (`meeting_transcripts.is_placeholder`: a role word alone or with one number or
  separated letter, matched whole, so a name never is) — is named in Stage 1's slot by one engine call
  (`meeting_speakers.identify`, over the same masked text the chunks send, at most 60k characters). Code keeps an answer
  only when its quote is found in the transcript (exact → whitespace → case-insensitive, never fuzzy) and says the name
  — someone addresses them by it, or they introduce themselves — never the person (52a), never another placeholder,
  never two names for one voice; a calendar's attendees only help spell a name the transcript says. What is kept reaches
  the meeting note with its quote; the rest stay placeholders Stage 1 never makes a page for, never takes for the
  person, and credits only where the transcript's words say who speaks. `Them` and other track-wide labels
  (`is_group_placeholder`) may name several people. The stored body, labels and offsets never change, so episodes
  already staged get it too; a failed or refused call reads the meeting as labelled. **Asking the person (slice 2):** a one-voice
  placeholder (never `Them`) still unnamed after that call, with 5+ lines, gets one `clarification` question
  (`asks: speaker`, Stage 5.4c, `meeting_speakers.ensure_question`): the meeting, who else was named, two of the
  voice's own lines, the calendar's other attendees as options, "Someone I don't know", or a typed name. The answer is
  stored by source in `meetings/speaker-names.yaml` (one writer, `meeting_speakers`), applied by the parser on every
  sync (`draft_for_file(speaker_names=)`, `meeting.named_by_person`), and the stored meeting is relabelled in place
  (`episode_staging.relabel_in_place`: turn stamps move with the text, a `revised` revision Sleep reads where it
  changed). The person themselves is refused (52a); no tending rule, judge or other conversation settles it, and a
  question whose meeting is gone is retired. An edited transcript carries the stager's `revised` record (above), so Sleep reads it as a revision.
  **A tool's note is no turn (2026-11-23):** an HTML comment line (`<!-- … -->`) is never a turn, and an italic line
  before the first speaker is a note about the recording — `meeting.notes` (code spans, which carry commands and ids,
  dropped), and when it says which tool split the remote voices, `meeting.voices_split_by` + `meeting.voices` (read from
  the sentence "… split on this Mac with <tool> (N voices)", no tool name is matched). Never a turn, never anyone's words;
  a file that has such a note is a revision of its one episode (its body lost the line). **The reader's names (derived on
  read, `meeting_transcripts.speaker_display`, the one place):** `GET /episodes/{id}/text` serves each meeting speaker turn's
  `speaker` as the label the record lists for it (`meeting.speakers`: the recorder's, or the name the person gave, which
  always wins) and `speakerKind` — `named`, `numbered` (`Speaker 1` whatever the diarizer spelled, `SPEAKER_01` too),
  `group` (`Them`) or `unknown`, the last two with no name — and a `meeting` object (`recorder`, `duration_s`, `app`,
  `attendees` as a count, `voices_split_by`, `voices`, and `summary_turn`: the first turn when it is the recorder's
  `Summary (written by …)` block, found on read by `is_summary_turn`, so no stored body changes). Sleep still reads the
  summary as the recorder's words. **A source deleted before anything read it (ruling 75):** a tombstone of an episode no
  model or agent ever consolidated (`processed` false, no `revised.consolidated_hash`) settles it as `processed: true`,
  `processed_by: source-deleted` (`episode_staging.DELETED_UNREAD`, in `_NOT_CONSOLIDATED_BY`): it leaves every waiting
  count and list, Sleep never reads it, the file stays, `source_deleted_at` stays; the source posted again re-queues it
  (`_requeue_for_authorship`), a rule change never does while it is deleted, and one tombstoned before the rule is settled
  by the folder's next sync (`settle_deleted_unread`). Every folder-staged source whose words are not the person's own authored note — a meeting, an agent's file — while the person's own note deleted before Sleep read it is still read (rulings 13/16); a read the person's own words owe (a woken save, a reason, ruling 62) is never taken back by a deletion. Wispr Flow's meetings stay
  on their own reader (above), now under the same Sources section; their summary and notes blocks are quoted through the
  same `summary_text` (#579 review, 2026-11-03), so a model line reading `User: …` opens no turn there either.
- **Messages conversations the person ticks (G179, 2026-10-15).** The app lists `chat.db`'s 200 most recent chats for
  the Settings picker (names, last activity, per-side counts — `MessagesReader.conversations`; a ticked chat below that
  cap is appended so it can be unticked). **Group chats (2026-10-28):** `chat.style` 43 is listed too, with its
  members' handles kept in the app for its own Contacts look-up; a ticked group posts `group: true` and `members:
  [{key, name, direct?}]`, each row its `sender` — a **participant key**, `MessagesReader.memberKey` = sha256 of the
  chat's id and the handle, stable per chat, never the handle and never shared across chats. The backend
  (`messages_source.members_of`) gives each member one marker, `speaker:<label>:` (their Contacts name, else
  `member-<key prefix>`; a phone- or address-shaped name is dropped, never kept), or `assistant:` for the ONE member
  whose own one-to-one chat (`direct`) the person marked an agent; two such members both stay `speaker:`. A group
  sitting records `group: true` and `participants: [{key, marker, name?, kind}]` — who each marker is — and no
  `correspondent` (a group is nobody's page; its members reach pages only by the promotion rules). A later pass that
  names nobody keeps every marker from the stored record. Reactions are one per reactor by `(from_me, sender)`. A
  person's mark on a one-to-one chat re-renders that chat only; a group picks up a member's new mark at its next pass. Every pass reads the ticked
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
- **WhatsApp chats the person ticks (G179, 2026-10-28).** The owner, 2026-10-28: live tracking "like we do with
  messages plus a historical if I want", group chats included. WhatsApp has no personal-account API and an unofficial
  client breaks its terms (ruling 47's table), so it is the Messages model: the app reads WhatsApp Desktop's own store,
  `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (plain SQLite, the iOS app's Core
  Data schema — `ZWACHATSESSION`, `ZWAMESSAGE`, `ZWAMEDIAITEM`, `ZWAGROUPMEMBER`; public forensic write-ups and
  KnugiHK's WhatsApp-Chat-Exporter; Full Disk Access covers another app's group container), from an APFS **clone** of
  the store and its `-wal` in a 0700 temp folder, every column only where the copy has it (`WhatsAppReader`). The list
  leaves status updates and channels out (`status@broadcast`, `@newsletter`); a chat's id is a hash of its JID and a
  group member's participant key a hash of the chat's and the member's JID, so no number reaches the bank. A ticked
  chat's rows carry the stanza id, time, direction, words, `ZMESSAGETYPE`, the member's key, `ZMETADATA` as base64 and
  the media item's title, file **name** and size — never `ZMEDIALOCALPATH`'s folders, a file's bytes, a vCard or
  coordinates. **Live from the tick:** ticking sets the chat's cursor to its newest row and the backend records
  `reads_from` and drops anything older (`before_start`); **Read history** is the person's ask — `history: true` opens
  the chat back to its first message on both sides. Every batch reads the rows past the `Z_PK` cursor; the first batch
  of a pass also re-reads, as a separate bounded read (newest first, at most 500), the already-posted rows of the last
  48 h (a delete for everyone rewrites its row in place; an unchanged row is a stager skip) — so a busy chat's window
  never crowds its new rows out (#502 review B1); the cursor moves past every row seen, and a full batch that left it
  where it was stops with "its newest messages couldn't be reached" rather than spinning. An @mention in any chat
  (stored as the number) is posted as that person's name, else "@someone"; the backend neutralises any left, and every
  chat writer's words (`episode_scrub.PHONE_WRITERS`: Messages, WhatsApp, Telegram) pass a phone rule — `+`-prefixed,
  `@`-mention, `tel:`/`wa.me/`, a bracketed area code and the North American dotted form. **False negatives over lost
  words** (#502 re-check): the scrub runs before storage, so an unbracketed grouped number ("555 010 1234") and a bare
  digit run are left alone — the same shapes are timestamps, year lists, ranges, prices, SKUs, room lists and ids (ruling 55, behind its switch: the person's own number kept as a token, `storage.md`). FSEvents on the container, 3 s debounce,
  15 s floor; every read is `Task.detached`. The backend (`whatsapp_source` → `chat_live`): type 6 is a group
  event (skipped), 14 a delete for everyone (its place kept in `unsent_turns`, its words never), 4 and 5 a contact card
  and a location (named only), a media row an attachment named and described; a quoted reply is `ZMETADATA`'s
  top-level protobuf field 5 (a message key hashes the stanza id's first 16 characters, because the quoted id is stored
  truncated). Reactions and edits are accepted when posted (`reactions: [{target, member?, from_me, emoji, date}]`, a
  row's `edited`) but the reader does not post them yet: the desktop store's columns for them are not publicly
  documented, and the owner's container is never opened to find out. **`chat_live`** is the sitting engine every chat
  source after Messages shares — Messages' algorithm keyed by a `ChatSpec` (one episode per 3 h sitting,
  `<origin>:<conversation>:<first message>`, rebuilt from the episode itself), ticks in `sources/<source>.json`, the
  scrub under the source's writer, no model. Who is who: `user:` the person; a one-to-one chat's other side
  `speaker:<name>:` with a `correspondent` record (unknown until the person marks it, as Messages; the mark is
  `actor` on the settings PUT), so Stage 2 lands them on the same page whichever app they texted through; a group
  records `group: true` and `participants: [{key, marker, name?, kind}]` — the Messages group slice's shape (#499) —
  each member under their own `speaker:<label>:`, at most one `assistant`. `chat_live.CHAT_ORIGINS` is what "a texted
  conversation" means to every reader that asks (`inbox_tend`). **chats-ux-v2 (2026-10-29):** a chat with yourself
  (WhatsApp's "message yourself": its JID's account part matches one of the person's own identities in WhatsApp's
  shared preferences — `OwnJabberID`/`LastOwnJabberID` (phone JID) or `lid`/`lidd` (the linked identity, which a real
  install's self-chat carries) — read by the app, never posted; Messages' note to self: the chat's handle is the one
  Messages addressed from or an account login; Telegram's Saved Messages: Telegram's own `is_self`, ruling 47a's
  2026-10-29 amendment) posts `selfChat`; `@status`, `@lid.status`, `@newsletter` and `@broadcast` never list; `chat_live.cast_for` makes every line `user:`, writes
  no correspondent and no card, records `self_chat: true` and titles it "notes to yourself". A link-preview row
  (type 7) is words only. One row's optional field the backend cannot use no longer refuses the batch: words past 64k
  end in "…", a title or file name past 400 is clipped, a `ZMETADATA` blob past 16 KB is dropped (that row loses its
  reply link). The picker draws each chat's picture from `ZWAPROFILEPICTUREITEM` (a file inside the container only,
  ≤ 128 px, in memory) and a ticked one-to-one chat's is posted to the chat-photo store (`messages_photos`, now every
  chat source's). **Before a tick (owner 2026-11-05, ROR-110):** the owner asked for an unticked chat's picture and
  archived state in the picker, so the app reads them on this Mac at view time and holds them in memory only — never
  posted, and no picture is written to disk; WhatsApp's picture file is read once into memory, not held open. To read
  them the app does write one thing: a transient copy of the database in a private scratch folder, deleted when the
  read ends, the way the list has always worked. The list's only other
  reads are chat-list fields (`ZARCHIVED`, where the copy has it, places a row in an Archived group below the rest,
  tickable like any other), plus the one date the list already read for its order (`MAX(ZMESSAGEDATE)`, 2026-11-03: a
  date per chat, never a message's words; owner 2026-11-05 on this and the picker's reads: "it can read everything except contents of chats"). A picture is the file `ZWAPROFILEPICTUREITEM` names for the chat's own `ZJID` or its `.thumb`/`.jpg`
  sibling, read once per list load, and never a guess from a file's name (2026-11-05: `<creator>-<time>` can be a legacy
  group's, so a person's chat could wear a group's face). Measured on the owner's store, counts only: 509 of the 510 files
  in `Media/Profile` are named by a row, and the name matching found nothing rows do not. The person's own chat wears
  `Media/Profile/Photo.jpg`; a phone chat with no row of its own, the row of its `@lid` id, read once per list load from
  a transient copy of `ContactsV2.sqlite`'s `ZWAADDRESSBOOKCONTACT` (`ZWHATSAPPID`, `ZLID` only; missing means no
  bridge, a number holding two ids bridges neither); none
  draws `EntityPictureFallback`. A failed read keeps its "needs access" state, and no new permission is asked. The Sources list serves one row per chat for WhatsApp and Telegram too (`channel_items`). Measured on fixtures (2026-10-28): file change → posted,
  the app's read of a 20,000-row store plus the post, p95 9 ms over 20 (`WhatsAppReaderTests`); the backend's stage
  into a chat of 40 sittings, p95 11 ms over 30 (`test_chat_live`) — the 3 s debounce dominates.
  **What "up to date" means (2026-11-03, live).** The owner asked whether WhatsApp was still syncing: its row said
  "synced" four days back while Messages and Telegram said today. Read on a read-only copy of the live store (counts,
  ids and times only): one chat ticked (the person's own), 24 messages, its newest 6 days old and exactly the cursor;
  0 rows past it, 0 in the 48 h window; the 1,670 messages since were all in 43 unticked chats. The last post was the
  window's re-read of that newest message, 7 s before it left the 48 h window — so the reader was running and nothing
  new existed to read. The gap was in the words: a pass posts only rows it found, so the backend's `last_sync` is the
  last pass that posted (or re-posted inside the window), never the last check, and it is the same for Messages
  (`imessage`, posts only a pass with rows) and Telegram (`record_sync` only on a flush with messages). The app's two
  readers on this Mac now keep their last successful pass and the newest message in the ticked chats as their app's
  own store lists it (`ChatCheck`: `WhatsAppWatcher.check`, `MessagesWatcher.check`; in memory, cleared on a bank
  switch and when nothing is ticked), and the source page says "Connected · checked 2 min. ago · newest message
  Friday" (`SourcePageStatus.checked`, DR-58) in place of "last item <day>"; the Sources list's row counts the check
  as its last sync (`SourceCatalog.rows(checked:)`), and "What Cicada reads" adds when it reads and that a phone's
  message arrives once the app on this Mac has it. A reader that stopped now shows as an old "checked", not as a quiet
  chat. Telegram is the backend's own listener (push, `listening` in its status), so it has no pass to report; its
  page keeps "last item <day>". The backend's `last_sync` keeps its meaning (other readers and agents read it).
  **The reader heard its own copy (found verifying the above).** A pass clones `ChatStorage.sqlite` and its `-wal`
  (`FileManager.copyItem`, an APFS clone), and cloning a file raises an FSEvent on the source — `ItemCloned`, whose
  flags can also carry the file's recent `Modified`/`Created` history (measured 2026-11-03), so flags cannot tell it
  from a write. Every pass therefore ran the next one at the 15 s floor, forever, cloning the store and re-posting the
  48 h window each time: the scratch app posted 50 times in about 15 minutes with one message written, and a unit test
  on a real stream counted 30 posts in 3 s at a zero floor. (So the owner's `last_sync` kept moving for 48 h after the
  newest message, then stopped: consistent with the loop, and with nothing new.) A change event now runs a pass only
  when the store's or the `-wal`'s size or modification time moved since the last pass began
  (`WhatsAppReader.signature`; `WhatsAppReaderTests.testThePassesOwnCopyNeverRunsTheNextPass`: 1 post, then none until
  a write, which is read). Two edges (#578 review): a write that lands during a pass joins that pass's run, so when a
  pass ends with the signature moved since it began it runs once more (`testAWriteDuringAPassIsReadWhenThePassEnds`);
  a pass that failed (a refused post, the backend down) clears the signature, so the next change event retries it at
  the debounce and floor (`testAFailedPassIsRetriedOnTheNextEvent`). Messages opens `chat.db` in place and clones only the nickname store, at most hourly per
  chat, so it never looped; Telegram has no file watch.
- **Telegram chats the person ticks (ruling 47a and its amendment, 2026-10-28).** The backend's own client
  (`telegram_account`, `telegram_port`, network.md) listens while the person is connected; events wait in memory for
  1 s and are then staged per chat in the active bank (never the demo bank), under write admission, one `capture`
  commit per flush — only a one-to-one chat that is ticked in the bank AND has the person's dated consent
  confirmation (`consents.json`); anything else is dropped in memory. `telegram_source` → `chat_live`: a
  conversation id is `hash("telegram", peer id)`, a message key `hash(conversation, message id)` — no Telegram id in
  the bank. Telegram states whether an account is a bot: a bot's lines are `assistant:` (`correspondent.kind: agent`,
  `decided_by: source`), anyone else's `speaker:<name>:` (`person`, `source`). Edits replace words in place; deletes
  keep the place (a private chat's delete names only ids — the ticked chat holding them is found by key); a reaction
  change is Telegram's whole current set, one per listed reactor (Telegram names reactors only in small chats);
  forwards keep `forwarded_from`; service messages are skipped; media is named, a location or contact card never kept.
  Live from the tick (`reads_from`); history on ask reads the chat oldest first, 500 a batch, at most 20,000; a
  per-chat cursor (the newest message id, beside the session) catches up what arrived while the backend was down.
  Measured on a fake client (2026-10-28): update → staged and committed, p95 12 ms over 30 into a chat of 41 sittings
  (`test_telegram_chats`), the 1 s flush wait aside.
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
  | Reddit | `saved_posts.csv`, `saved_comments.csv`; since G232 `post_votes.csv` (only `direction` `up`) and `subscribed_subreddits.csv` | permalink (no title or date in the export); an upvote filed `Upvoted`, a joined community `Joined communities` at `www.reddit.com/r/<name>/` (never a `u_<name>` profile) — the connector's own folders, both index-only; a lone `post_votes.csv` dropped by itself is read by this reader first, never as saves |
  | Spotify | Extended streaming history, Account data's plays and `YourLibrary.json`; since G232 `Playlist<n>.json` | plays as days (*Listening history*); the library and each playlist's tracks and episodes as saved items, a playlist's entries filed under its name and dated the day each was added (`addedDate`), its description never read |
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
  connector — and, since G232, the person's agent reading their Saved Pins in their browser (`saved_lists`; Pinterest
  documents no layout for its download, so no reader is written until a real one's member names have been seen).
- **The Reddit connector (G232).** Reads saved (folder `r/<sub>`, a bare save: indexed, ruling 62), upvoted (`Upvoted`) and joined communities (`Joined communities`), the last two index-only through
  `history_index.LIST_FOLDERS` like the export's rows. Reddit gives no save or upvote date, so none is set (ruling 39:
  `received_at` says when it came). Connect and the reads in `network.md`, "Connect Reddit".

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
- **Listening history (G32, 2026-10-29).** Spotify is export-only (ruling 47's table), so its way in is the person's
  own download, read member by member by `saved_exports` (`spotify_export`): Extended streaming history
  (`Streaming_History_Audio|Video_*.json`, every play, `ts` to the second, with URIs) and Account data
  (`StreamingHistory_music|podcast_*.json`, the last year, `endTime` to the minute, no URI; `YourLibrary.json`). Every
  other member (playlists, search queries, inferences, user data) is skipped unread by name. Plays become
  `listening_history` days — one episode per local day, `listening-history:spotify:<day>`, origin `spotify-history`,
  **index-only** like a watched day (`history_index.kind == "listening"`, ruling 30: never read by a model, never a
  mention, an agent asking by id gets one line saying what it is). A play's identity is its kind and name (case- and
  space-folded; never the creator — Account data names a track's own artist, Extended its album artist, so a
  compilation would double) and the minute it ended in UTC, looked up a minute either way and on the day either side
  (the local day moves with the Mac's time zone): the two downloads, one imported twice, or an import after a time-zone
  change never double a play — and two plays whose URIs differ are always two (an "Intro" by two artists; review of #528). A day's play rows live in `sources/listening/spotify/<day>.json`,
  committed with the day, never in the episode's frontmatter, which every cold start caches (a decade of plays there
  cost a cold scan 9.5 s and +300 MB; 0.34 s against 0.29 s without, after). Plays are always read (the
  person asked Spotify for exactly this; no door ever saves a play) and never count against the saves' import cap.
  The library becomes saved items (origin `spotify-saved`, a saved list's index-only save, folders *Liked Songs*,
  *Saved albums*, *Saved podcasts*, *Saved episodes*) at `open.spotify.com/<type>/<id>` with `defer_enrich`: no
  Spotify page or API is ever asked. Every door that brings saved files (`/sources/upload`, `cicada import`) takes
  plays off the save path (`listening_history.split`) and commits their days alone (`user/listening_history`).
- **Substack reading history (G89, 2026-11-04).** Substack gives a reader no API or export (`network.md`, ruling 47's
  table), so its History comes in through the person's own agent reading it in their browser
  (`cicada_record_substack_list`, `mcp.md`). What was read is experience, never a save: `substack_reads` writes **one
  episode per day**, `reading-history:substack:<day>`, `source: reading-history`, origin `substack-history` — the kind
  activity traces' reading days are (`history_index.kind == "reading"`), **index-only** (ruling 30: never read by a
  model, never a mention). **The day (ruling 39):** the one the page shows for a read, when it shows one (never a future
  day); Substack's History lists reads with no time, so a row with no day is filed under the day the agent first saw it
  there, and the day's words say each was read on or before it — the first read of a long history lands on one day,
  every later read adds only what is new. A post is its canonical URL (`substack.post`, the key a saved post and a
  followed feed's item share) and is recorded once, ever, by this door. A day's rows live in
  `sources/reading/substack/<day>.json`, committed with the day, never in the episode's frontmatter (the shape #528
  gave Spotify's plays). Overview row `substack-history` ("Substack reading", captured).
- **Substack's feeds (G89 (i), (vii), 2026-11-04).** A followed publication's posts come in through its public `/feed`
  (`feed_registry`, the feed gate) like any feed's: `parse_rss` now gives every item its publication — the RSS
  channel's (or Atom feed's) own title — as its `channel` (the episode's **Channel:** line), and a paid post's stub (a
  "Read more" link and at most 400 characters of words, `substack.is_paywall_stub`; measured 2026-09-01 at ~142 bytes)
  never stands in for the post's words: the item keeps its title, link and date with no body.
- **One identity.** A video is `media_ingestor.url_hash` of its canonical URL — the key Watch later, bookmarks and
  Takeout playlists share — so `youtu.be/<id>`, `/shorts/<id>` and `watch?v=<id>&t=…` are one video. Within a day a
  video is one row (`url, title, channel, times, via, seen`) in the day's own rows file,
  `sources/watched/<platform>/<day>.json`, committed with the day and never in its frontmatter: every episode header
  is cached for the backend's life, and a heavy watcher's rows there cost every cold start ~1.3 s (2026-10-29, the
  shape #528 gave Spotify; a day written earlier keeps its frontmatter copy until the person moves it —
  `cicada maintenance move-watched-rows` is the dry run (counts, a few day ids), `--apply` the move in one
  `cicada` commit, from their own terminal only, never automatic — and `watch_history.stored_rows` reads either);
  a watch less than 30 minutes
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
  already saved is a duplicate), history rows as days (the page's day). Since G245 (ruling 78b) it may also read, once the
  person turns each on, the playlists index and each playlist's page (a playlist's name is the save's folder; at most 12 a
  read, least recently read first) and the Liked videos list (`list=LL`, folder `Liked videos`): saves under the same
  `youtube-playlist` origin, index-only, one page on every list a video is on.
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
- **Screenshots** (on with traces; their own switch; Screen Recording): event-driven — on a new span, **at most one
  every 5 min** (`TraceFrameCadence.minGap` 300 s), then one every **15 min** while the same span continues
  (`steadyInterval` 900 s) — owner 2026-10-28, "a low screenshot frequency"; never while idle, locked or paused. The
  Screen Recording preflight (a TCC lookup, ~6–7 ms on the main actor, measured) is asked only once the cadence says a
  frame is due, never on every five-second tick. **Which pixels:**
  - *Sheet 1 (before 2026-10-28):* only the **front window** of an app that may be described. The front window is the
    first normal-layer window of that app in the window server's front-to-back list
    (`CGWindowListCopyWindowInfo(.optionOnScreenOnly)`, `TraceWindowPick`), matched by id in ScreenCaptureKit.
  - *Sheet 2 (`ALL_SCREENS_CONSENT`, owner 2026-10-28: "capture all connected displays"):* one frame per connected
    screen (main screen first, ≤ 8), each `SCContentFilter(display:including:)` — an **allow-list** read fresh for each
    screen (`TraceScreenPick`, review of #508 B1): only normal on-screen windows on that screen of *regular* apps the
    policy may describe (`TraceScreens.shown`: never a browser, a chat/mail app whose titles stay off, an excluded app, a
    password manager, Cicada, a notification banner, Spotlight) plus the one vetted browser front window. A window that
    appeared since, an app launched mid-capture, or a system helper (Quick Look's preview of a Mail attachment, the
    open/save panel) is never named, so never drawn; a screen with nothing named gives no frame. A person on sheet 1 keeps
    front-window frames until they agree to sheet 2 (the Traces page offers it, "Review…"). Frames of one moment share
    its instant and carry `display`/`displays`. Overlays above every window — hoff's cursor and bubble (G220), which
    are a background process's click-through panels at the assistive-technology level and do not opt out of capture
    themselves — are never named, so never in a frame (`testAShowMeOverlayAboveEveryWindowIsNeverInAFrame`).
  Either way the frame is dropped when, after capture, another app is in front or a browser's front tab changed or
  turned private (`TraceRecorder.stillShows`, B2). Downscaled to 1280 px at JPEG 0.6. **Cost, measured on this Mac
  (synthetic 1280×800 screen of dense text):** ≤ ~0.5 MB a frame (a mixed screen ~0.2–0.3 MB), encode ~10 ms, on-device
  text recognition ~0.65 s wall / ~1.1 s CPU at utility priority. A heavy eight-hour day is ≤ 96 moments: per screen
  ≤ ~30 MB and ~2 CPU-minutes a day, ≤ ~0.2 GB for the seven days kept (the old 1 min / 5 min cadence: 480 moments,
  ~150 MB and ~9 CPU-minutes a day). Text is recognized **on this Mac** with Vision after capture, off the tick (a
  queue of at most 8 frames), and posted with the frame.
- **Nothing, not even a title,** while off or paused (Pause from the menu bar: an hour, until tomorrow, until resumed),
  locked, in a password field, for an excluded app or site, a password manager, Cicada itself or a private window.
- **Nothing on the app's disk.** Spans wait in memory (≤ 500, posted once a minute) and frames in a queue of eight;
  with the backend away they wait and the oldest go, never spilled to a file (`ReaderOutbox` never queues a traces
  route). On a server connection (G181) nothing is recorded: `TraceBackendGate` sends traces to This Mac's backend only.
- **The backend parses and keeps** (`POST /sources/traces/sync`, `POST /sources/traces/frames`): `trace_store` re-applies
  the policy and seals each record outside every bank (`storage.md`, "Activity traces"); `trace_memory` promotes only
  what the person's switches allow — **what you watch and read** on any site (videos into the watch history, door 4
  above; other pages into the day's index-only reading record; on with traces) and, behind **Learn from my day** (off),
  the counted day digest Sleep reads (`source: traces-day`; no title, address or screenshot text; project time only
  through the person's own projects' folders, repositories and tied addresses). All wait until a span is past the
  15-minute forget window (B1). **No model at capture**; a model reads traces only through that opt-in digest. A trace
  is not a mention.
- **Agents:** no MCP tool, no Ask leg and no CLI read the store in v1 — Ask's raw-row lookup would put rows in front of
  a model, which the rail forbids; "what was that video at 15:20" is answered through the watched day Ask and recall
  already read. Remote doors and other devices never see traces.

**Every save is read (ruling 80, owner 2026-11-24, G246: "if i save it already has a reason").** Ruling 62's lean pass below
is what is left of it: the **pile**. `history_index` is the one place; `SAVES_READ = False` restores ruling 62 whole (capture
writes every save index-only, `take_turns` releases nothing, `retire` retires a queued save again).
- **Where capture puts a save** (`history_index.entry_stamp`, `media_ingestor.write_media_episode`; file I/O only). *Waiting*
  (`processed: false`): a save he makes singly — a click, a paste, a notch or site save, a small connector poll or list read —
  and any save carrying his own note or reason, even inside a bulk. *The pile* (`processed: true, processed_by: index`, the old
  pair): a bulk (more than `BULK_ITEMS = 10` new links through one door: `ingest_batch`, an archive through `ingest_chunked`
  however its slices fall, a connector poll, an agent's list pass, the stars of a first GitHub sync, a browser's first set of
  tab groups), and a save received more than `LATE_DAYS = 30` after the day it was saved, whatever its door. *Nothing to read*
  (`processed_by: no-words`): a title, a link and a site on a link no page is read from (`link_enrichment._excluded_media`:
  a walled site, a video, a paper), alone or in a bulk. A *record* (his own repository, a joined community, an open tab) is
  index-only as before, never released, never woken (`history_index.is_record`). A feed item is as the code read it. The bulk
  decision rides a context variable (`media_ingestor.bulk_door`, `is_bulk`), so no door's signature moved.
- **`kind` names a save only while it is index-only** (`pile` or a record). `save_state` says where a save stands (`waiting`,
  `pile`, `no-words`, `read`, `record`) and `not_read` is the one place "not read yet" comes from. Every save already kept in a
  bank is stored `processed: true, processed_by: index`, so it is in the pile with nothing migrated.
- **The day's number** (`take_turns`, run by `_index_without_model_safely` at the start of every run that reads, never a tidy-up
  run): `SAVES_PER_DAY = 100` less what was released today (`turn_released_on`), newest saved day first, ties by id, flipped to
  `processed: false` in the same `cicada` commit as the rest of the index step (manifest line `queued`; a failed commit puts them
  back). A pile save with nothing to read is stamped `no-words` instead and costs no turn. A save released today and put back is
  not released again today. The scheduled catch-up counts a pile with turns left as something to read (`turns_due`). A feed item
  is never a save (`save_shaped` asks `episode_time.is_feed_item` first): one kept index-only before ruling 80, which carries a
  link and a media page like a bookmark, is never released or counted as not read (2026-11-26).
  `return_to_pile` is the revert (and what a night that ended at its line does); `released_unread(day)` lists a day's.
- **The order** (`saved_order`, one call at the freeze): every non-save first, oldest first; then saves he talked about
  (`read_asked`) or wrote words on, newest first; then the other saves grouped by origin, the origin with the newest save first.
  A conversation read in this run that names a save still waiting moves it up after the batch (`_promote_talked_saves`). With
  the option below on, the old bulk material among the other saves comes after all of them, in the same grouping.
- **Old bulk material is read on the engine's lightest model (ruling 80, owner 2026-11-24: his own answer to the cost, "ok go
  ahead with your recommendations"; `light_reads`, `sleep_run_prefs.light_old_saves`).** A save released from the pile
  (`turn_released_on` is set) that is old bulk material is read on the lightest model of the engine he chose; everything else is
  read on the model he chose, exactly as before: conversations, a save made singly (never in the pile), a save he talked about or
  gave a reason, and a pile save from a saved list he turned on and his agent read in his browser or a connector he connected.
  - **The table** (`light_reads.why`, the one place). *Old bulk:* `browser` — a browser's bookmark taken in by a sync or an import:
    origin `<browser>-bookmark` for each of `bookmark_sync.CHANNEL_BY_ORIGIN` (Chrome, Brave, Vivaldi, Comet, Dia, Safari), or
    `source: bookmark` with no origin (a bookmarks file imported before the door was stamped); `file` — a save that arrived out of a
    file he gave, any platform's export or archive (`arrived_by: file`, stamped by `media_ingestor.parse_upload` on every item of
    the file; a feed is no save and is not stamped). *His model:* every list origin read by his agent in his browser (X
    bookmarks, likes and reposts, Instagram, LinkedIn, Reddit, Pinterest, TikTok, YouTube lists, Substack, Spotify), a connector's
    saves (the X, Reddit and GitHub polls, Pinterest), a tab group and a single save. **The same origin is on both sides**, told
    apart by the door only: an Instagram save out of an export file is old bulk, the same Instagram save his agent read is not.
    A save kept before the stamp existed carries none, so a list save already in a bank reads on his model: when in doubt, his.
  - **The lightest model** (`light_reads.lighter`): the same engine, sign-in, key and billing, never another. The Claude plan:
    `haiku`, its small model (a choice already of that line is left alone). A Claude key: the newest active Haiku of the key's own
    list that has a price row (`anthropic_models.active`, `price_supplement`), if it costs less than his on a read of the measured
    size. An OpenAI key: `gpt-5.4-nano`; a Gemini key: `gemini-flash-lite-latest` (`LIGHTEST_KEY`, each priced and structured-output
    capable, held by a test), only for that provider's own model ids. **No lighter model is known** for the ChatGPT plan, the
    Cursor, OpenCode and Grok plans, a local model, a router (OpenRouter), the open-model hosts, Groq, Mistral and xAI, so those
    read on the chosen model and nothing fails; a model with no known price gets none, and a chosen model with no price still stops
    a metered run (`sleep_spend`), as before. The lighter model must also be priced when the run starts (`guard_for(also=...)`).
  - **A batch is read by one model.** `sleep_drain.next_batch_retrying` ends a batch where the model changes (a retry too), so the
    lighter saves form their own batches, after every other save, on an engine copy (`BatchPlan.lighter`) that carries the lighter
    model in its main fields (and a later-stage override follows it). The person's own main model is kept on that copy
    (`Settings.kept_main_models`) for the one call that must not get cheaper: the same-name second look
    (`same_name_tend.main_tier`), accuracy over price on a person. The spending line adds each call at its own model's price (the
    ledger's figure); the first lighter batch is sized by what the dearer model cost each, so it never holds more than the allowance
    buys. The reserve, and "a line reached with only background saves left ends the run" (`ds.background_ids`), are unchanged: a
    lighter save is a background save. A save he talks about during the run leaves the lighter class (`_promote_talked_saves`).
  - **The option** (`light_old_saves`, on unless he turned it off): `GET/PUT /sleep/run-options` (`lightOldSaves`) and
    `cicada sleep options --light-old-saves on|off`, snapshotted when a run starts; no app control. Off: everything is read on his
    model and the order is as it was.
  - **The record.** A lighter batch's `sleep_run` ledger row carries `refs.lighter`, and the run detail (`GET /sleep/runs/{id}`,
    `SHAPE = lighter-1`) says per batch the model that wrote it and whether it was lighter beside how many it filed, on top of
    the per-model calls and stages it already had, so a night that read 80 old bookmarks on the lighter model and 20 posts on his
    is legible. The commit's `Cicada-Author` names the models the engine reported (a plan engine records each reply's), else
    those of the batch's own settings, so a lighter batch names the model that wrote it.
- **A night never blocks the next.** Decay and the page reads run in the batch that leaves only background saves behind it
  (not the last batch). A spending line, a reserve, a plan window or a key limit reached while only background saves are left is
  a **finished** run: no paused record (so `schedule_may_replace` is moot), no page read, the unread released saves returned to
  the pile (`_return_unread_saves_safely`, the tail's first step), the day's number stays spent. With a conversation or a
  talked-about save left it pauses as ever. An `engine` stop stays a pause.
- **Nothing to read, and what a public title-only save costs.** Stage 1 sends no model a saved link whose body holds no section
  (`saved_reading.nothing_to_read`): it is filed with no entities and **no call** (a folder's reason or a tab group still read).
  A title-only save of a *walled or excluded* link is stamped `no-words` at capture: no model ever reads it until he talks about it
  or his agent opens it. A title-only save of a *public* link takes its turn like any save: Stage 1 costs 0 calls and the page
  behind the link is read by the existing page read (Stage 5.57, the backfill; behind the connector fetch gate and its caps), so
  what is "read" for it is that page. A save with words costs about two calls (`docs/plans/2026-11-24-saves-are-read.md` 3.6).
- **Talking about a save** (`saved_mentions`): of one still waiting, it stamps `read_asked` (first among saves, no flip) and
  leaves the ask for his own agent (`mention_asks`, ruling 78 (e)); of one in the pile, it wakes it as before; of one already read,
  or with nothing to read, it leaves only the ask. The ask no longer depends on the save being unread. **The mark (G246 Track M,
  ruling 81):** the same located words also stamp `named: {why, at}` on the save whatever state it is in (`history_index.mark_named`;
  frontmatter only under the episode lock, so `processed`, the queue and the order are untouched and no model is called; the first
  mark stays, and the five-a-conversation cap that bounds wakes and asks never bounds it; a record another service keeps, a removed source and an episode that is no save are never marked). A re-stage pops
  `read_asked` once the read is done but never `named`, which is what lets a post he talked about after Sleep read it keep its page
  (`saved_posts`, `features.md`). It is written inside the batch that read the conversation and commits with it; only his own turns
  count, so an agent's words, a relayed app's and a note an agent saved never mark one, and no route, tool or read path calls it.
- **Scripts** (counts and enums only): `api/scripts/history_index_dry_run.py` gains a `saves` block (saves by state, what would
  leave the pile tonight by origin at the day's number, what holds nothing to read, nights for the pile);
  `api/scripts/saves_night_report.py --bank --day` prints one row per save in a night (ids, origin, state, how it reached the queue,
  whether he talked about it, the pages its claims landed on, claims by observer kind, questions open).
- **Measured** (`benchmarks/consolidation/saves_battery.py run --leg single`, the real path, 288 synthetic saves and 8 conversations,
  Claude plan at haiku, one run, 395 s): 168 calls, 1.13M input tokens (gross of cache), 115k output tokens for the 91 episodes a model
  read, about 1.85 calls, 12.4k input and 1.3k output tokens each. The 103 title-only saves of a public link (3 singles and the 100
  the day's number released from the bulk list of 200) cost 0 Stage 1 calls (the connector fetch gate was off, so no page was
  read); the 100 left in the pile wait. Retrieval 12/12 by words and 11/12 by the hook's note, before and after Sleep. Gates still
  failing, and why, are in the PR that built this (the old-shape connector rows, a quill-page cap that counts `external` claims only).
- **Short saves of one origin read together (Track 3, `grouped_save_read`, built and OFF: `ON = False`, flipped by the coordinator
  after the saves battery's grouped leg is read against the single one; numbers below).** Stage 1 is one call per item, and a 60 to 250
  token post rides a fixed prompt of about 8k tokens. With the constant on, `extract` plans groups before its fan-out (`plan`): saves
  with none of his words, not talked about (`read_asked` now rides the episode dict), no tab group, feed item, book or conversation,
  none over 1,500 characters, none whose text holds the question's own marker, of one origin, up to 25 a group (a group of one reads
  alone). Each save is still prepared and finished alone (its date note, its source note, the sensitive-text hold and `on_sensitive`
  before the send, every per-item callback); only the model call is shared: one call at Stage 1's own stage label (`extraction`, so the
  spending line, the ledger and the model tier are the same and no stage enum was added) with the Stage 1 prompt plus `GROUP_PROMPT`,
  each save between `<<<SAVE n>>>` markers carrying its own date note and source note, no answer shape forced on a plan engine. The
  answer is used only when it lines up exactly (`json_parse.numbered_rows` over `results`, one numbered block per save, each block's
  lists lists); anything else, a refusal, or a timeout twice, reads each save alone with the same facts (a bad answer costs a call,
  never a fact); a rate limit, a sign-out, the network or the line are the engine's and reach each save as they would a single read
  (a spending line skips them, never fails them). A quote a block lifts from a neighbour is located only in its own save's text (so it
  is `reasoning`, and the claim is still written; the log counts them). A batch of background saves alone may hold 50 (bytes bound
  150,000) and skips Stage 4's skills call (`saves_only_batch`; a skill needs two conversations).
  *Measured once each* (`saves_battery run --leg single` and `--leg grouped`, the real path, 288 synthetic saves and 8 conversations,
  Claude plan at haiku, 80 saves sent to a model): Stage 1 calls 88 against 22 (1.10 against 0.28 a save), Stage 1 input tokens 940k
  against 263k (11.8k against 3.3k a save), output tokens 67k against 63k; every stage 163 calls against 57 (2.04 against 0.71 a
  save), 13.8k against 4.2k input and 1.4k against 1.0k output tokens a save; evidence not located 5 of 42 spans against 1 of 23; all
  12 gates the same (nothing on his page, no page from saves alone, every fact `external:`, 12 claims on the 50-post page, the 2021
  fact dated); the grouped leg kept fewer facts (42 claims from saves against 23, almost all of it on the 50 near-identical posts,
  where the page's cap is 12 either way), which is part of why its later stages are cheaper: repeat both legs before turning it on.
- **Not in this change:** the words the app and agents show about saves (Track R).

**The lean pass (ruling 62, owner 2026-11-04; G236) — since ruling 80 the pile above, which only a bulk, a late arrival and a save already kept enter.** Owner: "For chrome bookmarks, and the rest of things I told you we
can do a leaner initial pass for consolidation on those things who have no reason/user intent attached, but enough info so
that it can come up in a relevant conversation and an agent can look further into it." What a full read of a bare bookmark
buys, measured (25 synthetic bookmarks, Claude plan at haiku, connector gate off): 56 to 57 calls and 269k to 272k input
tokens, about 2.5 minutes: Stage 1 once per item at about 7,900 input tokens (the prompt, mostly cached, for a title of a
dozen words), then a judge call and a merge call for most items. No retries. It made a page sentence restating the title and
the folder, and `covers` claims from the title's own words. Recall found the same links without it (below).
- **What is lean: `history_index.kind` `saved`.** A bare save, by its own record, never by what its body says: the saving
  door's page link (`media_entity_id` and `url`: a browser bookmark, a single saved link, a feed item, a connector poll, an
  open Safari tab, any import through the media writer), an older `*-bookmark` episode, or a tab group (`source: tab-group`).
  A list save stays `list` (ruling 30; ruling 78 (e) wakes one the person names, below). **Not lean:** a save with a reason or note (`has_note`, `saved_why`,
  `saved_why_earlier`, a `## Saved because`, `## User note`, `## Why it was saved` or an agent's `## Note` section, the last
  because it says why the link matters though it is never the person's words); a book's record (`book`); an agent's report
  that carries the page's link (`video-watch`, `page-read`) and Cicada's own checks; a conversation; a save anyone already
  read. **A save read before the ruling stays exactly as it was:** `processed: true` under any writer but `index` is never
  `saved`, so its claims, pages and every reader's view of it are untouched.
- **A connector's post is no note of the person's (G245, owner 2026-11-24).** The X and Pinterest connectors used to pass a
  post's text as `RawItem.note`, so it landed under `## User note` with `has_note` and a Sleep read took it as the person's
  own words (the one place a stranger's words could reach the owner's page). It now rides `RawItem.preview` — the page's
  description, kept beside the linked page's own when there is one — so such a save is a bare save like every other
  (index-only, `kind` `saved`), and the X request asks for `created_at`, the post's `posted` day. How a save is read when it
  is read (author's observer, post day, owner guard, 8 entities, no question) is in `storage.md`, "A save a model reads is
  read as its author's".
- **What it costs: nothing.** Capture writes it read (`processed_by: index`, `media_ingestor.write_media_episode`; a tab group's
  stager draft); an edit to a group spends nothing. No model call, no claim, no page minted (the media page is the save's
  own, written at capture, link views and all), no question: Stage 5.57, the tail's link backfill and recon pass over its page
  (`link_enrichment.lean_page`: every episode the page rests on is `saved` or `list`), including the no-model reuse path,
  which writes a `describes` claim. This narrows G102's "what makes a saved link part of the graph" to saves someone said
  something about. No engine is needed, so it works with no plan: `_index_without_model_safely` runs before an engine is resolved.
- **The page behind a save Sleep reads (ruling 80, G245; the coordinator's reading of "if i save it already has a reason",
  pending the owner's confirmation).** `link_enrichment.lean_page` stays keyed on the read state — a page whose every
  episode is still stored as `saved` or `list` gets no page read, exactly as above — so the moment a save is read by Sleep
  (or owes its read) the public page behind its link is read by the existing path and no other: Stage 5.57's in-cycle pass
  and the tail's backfill, behind `CICADA_ALLOW_CONNECTOR_FETCH`, the caps (`link_enrich_max_per_cycle`,
  `link_enrich_backfill_per_cycle`, 20 each), `_excluded_media` (never a walled site, a video, arXiv, LinkedIn or Instagram)
  and `default_fetch`'s rail. **Newest saves first:** the backfill sorts newest save first (it was oldest-imported first,
  R2), and a page only saves made, which has no last mention, is ordered by its save's day in the in-cycle pass.
  **One line turns it off:** `link_enrichment.READ_SAVED_PAGES = False` makes a page every save of which has no words of the
  person's and no `read_asked` lean whatever its read state (never fetched, described or related) and puts the backfill back
  to oldest-imported first.
- **What is kept: enough to come up, `saved_lookup`.** Title, link, site, date and the page's own description when one is
  already held (no fetch), found by the indexes every episode and page already has: the FTS `med` table, a tab group's
  passages (`meta.saved_no_page`), the entity vectors. Rarity decides, as in the hook's topic leg: a word held by more than 3%
  of saved items (floor 5) finds nothing, a hit must carry 40% of the message's rare weight, and an unasked note needs two rare
  words, 60% of that weight and half of the title's own subject words. Three doors: **recall** (a media page a leg ranks shows `Link:`, its
  saved day and, while Sleep has not read it, "(not read yet)" or "(nothing to read yet)" (ruling 80, `saved_words`); the rest under *Saved links on this*, at most 3, one rare word enough; a save is no
  *conversation excerpt*), **Ask** (`SAVED LINKS`, at most 4, words then meaning; a line only the vectors found never earns a
  model call by itself; a tab group, which holds no page, only for a caller with the `sources` scope, as recall (G135), and
  `saved_lookup.find` leaves it out unless the caller says it may see one), **the hook's note** (at most 2 lines under the note's own 400-token cap and a 40 ms reserve, reason
  `saved`, ids joining the session's window so a link is not repeated turn after turn). `cicada_sources(<id>)` answers one line
  with the title and link. Vectors: the tail's `_embed_indexed_episodes_safely` also embeds a media page newer than the
  index, and makes the first sync of a bank that holds nothing but saves, since no batch ever would.
- **The way back: read once, when the person talks about it (`saved_mentions`).** `read_asked: {why, at}` takes the episode out
  of `saved` for good and queues it for the next run (`history_index.wake`, under the episode lock), where it is read like any
  conversation and is `processed_by: sleep` after. A sync never takes that read back: a lean writer's draft (a tab group's, a
  saved list's) leaves a save `history_index.owes_a_read` queued, whatever it changed, and `saved_lookup` still finds it until
  the read (`is_unread_save`). A group that changes after its read goes back to a bare save, `read_asked` dropped: no model read
  the new tabs, they spend nothing, are found, and a later mention wakes them. Three things wake it: one of the person's own turns (`evidence.turns`, role
  `user`, never an agent's reply or another speaker's line) holds its link or says its whole title of at least three subject
  words (`said-the-link`, `said-the-title`, after a batch is read, committed with it, at most 5 per conversation so a paste of
  fifty links is not fifty reads); a conversation lit its page, so it is no longer quiet (`page-mentioned`, before a run freezes,
  and `retire` does the same for a queued save whose page was lit before it was ever indexed, which is the first run's case);
  or they give a reason, the existing `saved_why`, note and Telegram doors (`mark_person_words`). **A retrieval hit is none of
  these:** nothing on a read path writes. An agent's `cicada_record_read` is its own read, with its own episode and claim, so
  Sleep does not read the same thing again. A save's text stays `page` (`authorship.of`), never the person's words.
- **Depth on mention (ruling 78 (e), owner 2026-11-24; G245; `saved_mentions`, `mention_asks`).** Owner: saves stay light,
  "but those that i actually go ahead and talk about are way more important", with "a clear logic … to not bloat cicada
  memory … but making it aware and powerful to go deeper". **Amends ruling 30 point 1 and ruling 62 point 3 for a mentioned
  list save.** (1) *The wake reaches a save from a platform's list* (`history_index.kind` `list`): only the person's own
  located words (`said-the-link`, `said-the-title`; never `page-mentioned`, which `history_index.wake` refuses for a list
  save, never a retrieval hit) stamp `read_asked`, which takes it out of `list` too (`kind` reads `read_asked` before the
  origin) and queues it for one normal Sleep read, at most 5 a conversation as before. It newly reaches 11 origins
  (`youtube-playlist`, `instagram-saved`, `tiktok-saved`, `x-likes`, `x-bookmarks`, `linkedin-saved`, `spotify-saved`,
  `github-starred`, `pinterest-saved`, `substack-saved`, `reddit-saved`; Reddit's Saved posts, Saved comments and Upvoted
  folders), and leaves out two records that are no save (`github-owned`, Reddit's Joined communities,
  `history_index.mentionable`). A list save nobody named is still indexed and read by no model (`test_more_lists_g245`
  holds the gate unchanged). A reason the person gave already made a list save theirs to read (`PERSON_KEYS`), unchanged.
  (2) *The same mention leaves an ask for the person's own agent* — a row in a queue, nothing more (`mention_asks.offer`,
  after the batch, in the same step): a provider video (`video_state.saved_videos`) goes on the video queue as a
  transcript job, a post on a walled site on the reading queue; each marked `origin: mention` with the settings key of the
  list it came from. **Which saves are on a list is `mention_asks.list_key`'s answer, not the index's `kind`**
  (`saved_mentions._saves`): an X bookmark filed in no folder and a Reddit connector save (`r/<sub>`) read as bare saves to
  `history_index.kind`, yet are on a list, and are owed the same ask; a browser bookmark or a saved link is on none. Honoured (listed, leased, counted, recordable, `reading_queue.authorizes`) only while agent reading
  and that list are on (`mention_asks.gate`); turning either off hides it at once and the settings route's `sweep` removes
  it — a leased row too, as the person's own Remove takes one (`video_queue.drop_mentions`) — and the route sweeps again
  before any switch is turned ON, under the settings of the moment, so a hidden ask is never honoured again by a switch
  coming on; no count (`reading_asks.counts`, `/reading/asks`, the queues' own) includes a hidden one; the person removes it where their own asks are listed. **At
  most 5 a day a bank across both queues and 50 waiting**, kept in `$CICADA_HOME/mention_asks/<bank>.json` (a day, a
  count and the hashes of links already offered, so a removal holds against every later mention; no url, never in a bank).
  A waiting mention ask **never expires** (an expiry would turn `asked` back into `kept` unannounced; the two bounds keep
  it small); once an agent answers, the row ages out like any outcome. Not asked: a link already read or watched by an
  agent, a link with a row already, a public page that is not a provider video, a save whose list is off, a demo bank.
  Cicada starts no agent and downloads nothing; the agent that answers records what those doors record today (a summary
  and short quotes; frames stay its own work).
- **Existing items.** The first run after this lands retires what waits, in the existing `Indexed without a model <date>` `cicada`
  commits of at most 500 files, before ids freeze, with no engine and nothing else touched; the tail embeds what it indexed.
  Between the upgrade and that run they are already out of every waiting count (`waits_for_model`, `/sleep/queue`,
  `/sleep/episodes?processed=false`). Measure with `history_index_dry_run --bank <path>`: `index_only_by_kind.saved` is that
  number, counts only.
- **What the pages say (ruling 80, Track R; the words live in `saved_words` and the app's `Copy`, never twice).** Sources
  (`source.kept` and `keptPerNight`) and the Sleep page's Waiting (`/sleep/queue`'s `kept` and `keptPerNight`): one line, "371
  saves not read yet. Sleep reads about 100 a night, newest first. Talk about one and it is read first." (`Copy.savesNotReadYet`;
  the number is `SAVES_PER_DAY`, sent by the backend). A saved-list row says `read`, `not read yet`, `nothing to read yet`,
  `waiting for your AI app` (his words named it and an ask is open) or `watched`; a stream says `read by Sleep`; watch history,
  follows, connections, owned repositories and tabs open on another device say "kept, never read: you did not save it". Recall,
  Ask and the hook's note mark an unread save "not read yet" and say when Sleep reads it; a record tool's reply says Sleep reads
  the posts it saved; none of Cicada's own words ("lookup", "indexed", "index-only", "lean", "its turn") reach a person or an
  agent (`test_words_on_screen.py`, `SaveWordsTests`).
- **Reads everything, still (rulings 13, 16 as amended by 62).** A lean read is a read: everything waiting when a run starts is
  consolidated by the end of it, the lean part with no model.
- **Measured.** All on scratch banks, Claude plan at haiku, the connector gate off, input tokens gross of cache. **25 bookmarks:** before 56 and 57 calls, 269k and 272k input tokens, about 2.5 minutes; after 0 calls, 0 tokens, 2 seconds. **The owner's 22-item shape** (7 coding sessions of which 2 long, 5 short chats, 6 bookmarks, 4 tab groups), fresh bank: before 62 calls, 421k tokens, 1 batch, its first commit after 54 calls; after 59 calls, 383k tokens, 4 batches, its first commit after 11 calls, its largest batch 19. The same again on a bank that already has those pages: before 92 calls, 522k tokens, 1 batch, first commit after 66 calls; after 75 calls, 461k tokens, 3 batches, largest 34. Conversations are most of a mixed run, so the lean pass saves little there, and more batches mean more merges (5 to 16 on the fresh bank) and a `skills` call each: the bound buys what a stop can cost, not fewer calls. **Retrieval** (15 messages about 25 bookmarks, 12 sharing words with the title and 3 only meaning; 4 unrelated; real doors, with vectors): recall 12/12 and 3/3 both when Sleep had read them and with the lean pass; the hook's note 3/12 before, 12/12 after, 0/3 by meaning both; Ask 3/4 before, 4/4 after; unrelated messages: the note 0/4 both, Ask 0/1 both, recall 4/4 both (its top-one rule shows the nearest page in a bank that holds nothing else). Words only, read by Sleep: recall 11/12 and 1/3. Nothing woke a save in all of it. **At scale:** 3,000 titles drawn from the same 70 technical words, a worst case: the leg's p95 is 3.9 ms, and 6 of 15 unrelated coding messages drew a line. Real titles have far more words; count `reason: saved` in the ledger on a real bank. **The read back:** a conversation naming one link and one whole title woke those two and not the link only the agent said; the next Sleep read them in 9 calls, and they are read for good. **Lost, disclosed:** the `covers` claims and the page's edges to concepts that a read made from the title's words, so a lean page draws unconnected until it is read. `test_lean_pass.py` pins each case.
- **What reading a save costs, measured (G245, 2026-11-24).** `benchmarks/consolidation/saves_battery.py` (fixture `saves_fixture.py`, invented saves, scratch bank, the verify skill's isolation; its README paragraph has the method and what it does not prove) woke 87 saves of one bank and read each alone, once, with today's reading, on the Claude plan at haiku, twice: on top of the baseline a save costs **2.0 to 2.2 calls, 13.1k to 13.6k input tokens gross (10.7k to 11.2k from the prompt cache) and 1.8k output tokens** (Stage 1 one call, 10.5k in, about 1.0k out; merge, fact fold and disambiguation most of the rest), about 5.7 to 5.8 s of a run's wall time (573 s and 582 s against the 113 s baseline, over 81 extra saves), the ledger's model seconds adding up to about two calls at once. Today's reading also puts a stranger's words on the owner's page (10 to 11 claims, "saved X" acts apart), makes a quiet page for each post author (8), and writes 31 to 36 claims on the one page 50 posts name, none `external:`; those are the content tracks' gates, not a verdict on reading saves. Output tokens had never been measured before this.

**Indexed, not consolidated (owner ruling 2026-10-18; G71, G94).** The owner's Takeout with history brought 45,879
watches as 2,532 day episodes and 3,156 playlist saves, and every one was queued for a full Stage-1 read — hours of
plan usage to fill the graph with channel and video pages and "who is X" questions. Owner: "maybe overanalyzing the
watch history is too much … Maybe just have it there and then maybe the metadata has it as embeddings or something."
So watch history and list saves are a record to look up, never a conversation to read:
- **What is index-only — one predicate, `history_index.kind`.** A watched day (`source: watch-history`), a month's
  summary (`source: watch-history-month`), and a save from a platform's saved list: origin `youtube-playlist` (a
  Takeout playlist, Watch later included, or the agent's read of Watch later), `instagram-saved`, `tiktok-saved`,
  `x-likes`, `x-reposts` (the browser read of the person's own reposts, `mcp.md`), `linkedin-saved`, and `reddit-saved` / `x-bookmarks` only under the folder the export reader names
  (`Saved posts`/`Saved comments`/`Upvoted`, `Bookmarks`) — the Reddit and X connectors share those origins under other
  folders. G245's browser lists write under the same labels (`x-likes`/`Likes`, `instagram-saved`/`Liked posts`,
  `reddit-saved`/`Upvoted`, `youtube-playlist`/`Liked videos` or the playlist's name), so an export's row and the browser's
  are one row, and a gate test walks every list through this predicate; a post on two lists is one page whose
  `collections:` names both (`mcp.md`, "More lists, folders, catching up and a post's own day"). A save carrying the person's own note is read (no list door carries a note; one that did is stamped
  `has_note` and queued). Every other bare save is lean, the same way (*The lean pass*, ruling 62, below). **The
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
- **A repository renamed, moved or cloned again (ruling 22 D2a, 2026-10-29).** Claude Code names a project's notes folder
  after the checkout's path, so a new path starts a new folder; notes the person brings along (moving or copying the
  folder) arrive under a new key. Each draft carries `content_sha` = sha256(file name + note bytes)[:16]: a note whose
  old key left a complete snapshot and whose bytes reappear under a new one is repointed by the stager's rename by
  content — same episode, same id, not re-queued, `previous_source_ids` kept; a note whose bytes a live note already
  holds (a copy, or a partial read) adds no episode (the post's answer counts `moved` and `copies`). Measured on a
  scratch bank: a moved folder of two notes went 2 created + 2 tombstoned → 2 repointed; a copied one 2 duplicate
  episodes → 0. A note edited before its first sweep in the new folder is still a new episode (its bytes changed);
  the remote is not used here, because the hook cannot tie a notes folder to a checkout without reading git in a
  path it was not given. Episodes held before carry no `content_sha`: the first sweep stamps it (frontmatter only).
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
- **The note's `type` (2026-10-29).** Claude Code types each note `user`, `feedback`, `project` or `reference`;
  `feedback` (guidance on how to work) and `user` (who the person is) notes are candidates for the handshake's *How to
  work with me* — at most two rows, `feedback` first, newest first, never a tombstoned note — each shown as the
  agent's ("… (an agent's note, `ep_…`)"), never the person's words; the row is the note's episode id and its own
  description (`state_dictionary._agent_note_rows`, `storage.md`). `project` and `reference` notes are read by Sleep as
  before and never ride the handshake.
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
| T3 Code (G228) | none of its own: the harness it drives fires Cicada's hooks (Claude Code through the Agent SDK with the person's user settings; Codex's `app-server` with `~/.codex/hooks.json` in its "existing login" setup; Cursor's SDK with user settings) | the driving harness's payload; the host is read by the hook from its own launch chain (exec paths only) | Every thread, as its harness's one episode labelled `host: t3code` (below); Claude Code verified only as far as T3 Code's recorded SDK fixtures (SessionStart hooks fire), the rest unverified |
| Claude app (desktop) | none; MCP only | — | Every turn its model relays through `cicada_capture_turns` on its local connection (ruling 57, below), stored as relayed; an export upgrades it |
| Claude on the web and phone, ChatGPT, Grok | none; remote connector (G135) | — | Every turn its model relays through `cicada_capture_turns` (ruling 32, below), stored as relayed; an export upgrades it |
| Windsurf (Cascade) | `pre_user_prompt`, `post_cascade_response` in `~/.codeium/windsurf/hooks.json` | `user_prompt`; `response`; `trajectory_id`, `execution_id` | Not yet: the same shape as Cursor, so it is a registry and an adapter on `/capture/turn` (G197) |
| GitHub Copilot CLI | `userPromptSubmitted`, `agentStop` in `~/.copilot/hooks/` | `prompt`; the reply only inside `transcriptPath`, format undocumented | Not yet: the reply needs a transcript reader (G197) |
| OpenCode | JS/TS plugins only (`~/.config/opencode/plugins/`) | events (`message.updated`, `session.idle`) with undocumented payloads | Not yet: needs a plugin, not a command hook (G197) |
| Hermes, OpenClaw | no hooks documented | — | MCP saves only |

**Host apps: T3 Code (G228, 2026-10-29).** A *host* drives a harness Cicada already captures without being one.
T3 Code (an open-source GUI for coding agents; source read at commit 3748c5c2) runs Claude Code through the Agent SDK
with `settingSources` left at its default — user, project and local settings, the CLI's own — so Cicada's Stop,
flush and recall hooks and the Cicada plugin (its MCP server, skill and hooks; T3 Code's docs say enabled plugins
load) run inside every T3 Code Claude thread; a thread is one SDK session id, resumed under the same id, so it is one
episode (G104). Codex runs as `codex app-server`; with T3 Code's "use an existing Codex login" setup its
`CODEX_HOME` is `~/.codex`, so `hooks.json` applies; its managed ChatGPT sign-in gives Codex a T3-owned home, which
Cicada's hooks never reach (not captured; Needs the owner on G228). Cursor runs through Cursor's SDK with user
settings loaded (unverified that `~/.cursor/hooks.json` fires there). T3 Code's own model calls (thread titles,
commit messages) pass `disableAllHooks` / `codex exec --ephemeral`, so they are never captured. **Nothing is read
from T3 Code's database** (`~/.t3/userdata`): the harness's hook is the one door, and the backend opens only the
transcript it already validates. **The label:** T3 Code sets no variable of its own on the agent's environment,
so the hook observes **its own launch chain: parent pid and exec path only, bounded, in-process, never another
process's arguments or environment** (`api/hooks/host_identity.py`: at most 10 ancestors; `proc_pidinfo` and
`proc_pidpath` on macOS, `/proc/<pid>/stat` and the `exe` link on Linux; no `KERN_PROCARGS2`, `cmdline` or
`environ`, no subprocess; never logged). It matches the desktop app's bundle path (`…/T3 Code*.app/…`) and an exec
named `t3` (the CLI, `t3 service`, the Linux app). **Not detected, by decision (PR #543 review):** `npx t3`, an
npm-global install or a checkout, whose exec is `node` — those threads are still captured under their harness, only
the label is missing. The hook posts `host: t3code` beside the harness (`/capture/transcript`, `/capture/session`,
`/capture/turn`; additive, an unknown value dropped, never a refusal). The episode keeps `harness`, `origin`, the
transcript rail and `external:<harness>` claims — the agent really is Claude Code — and gains `host: t3code` outside
the hash, kept once written; there is **no source row** for T3 Code (ROR-114: a session files under the harness it drives, `source_overview.source_key`; `t3code` is not a harness label), and a capture that kept
something stamps the last-seen registry (`agent_seen`, via `hook`), which is how the Agents page sees T3 Code.
**What T3 Code writes into a turn is not kept as the person's words — only under its host, only on its full shape**
(`transcript_extract.host_envelope(text, host)`, through `_Builder._add` on every path). It runs only when the
capture's host is `t3code`: the hook named it, or the session's episode already carries it
(`transcript_capture.envelope_host`, read from the frontmatter's top lines; a client applies only the host its own
hook named). A provider switch or a fork the provider cannot resume starts a new harness session whose first message
replays the thread; it is cut to the request only when the whole fixed shape is there — the "Context handoff (…)"
header naming `t3_thread_read`, T3 Code's fixed "Selected N intact items; omitted M items. …" sentence, at least one
full "[Historical <role>; <kind>; thread=…; run=…; item=…; provider-thread=…; status=…]" block, and a "\n\nUser
message:\n" line, the cut at the FIRST such line after the last block (a request that itself holds the line keeps
its head). A provider given history natively gets the header-and-sentence message alone and each full block as its
own message (dropped, counted `host_handoff`/`host_replay`); an ACP prompt's `<t3_code_instructions>…<user_request>`
wrapper keeps the request. Anything unsure — no host, a missing sentence, block or split line — keeps the whole text:
losing the person's words is worse than keeping a replay. A provider switch inside one T3 Code thread is two harness
sessions and two episodes (linking them would need T3 Code's thread id, which only its database holds). Hook cost (this Mac, after the review fix):
one whole Stop firing p95 56.4–57.3 → 57.1–57.7 ms (60 runs each, origin/dev and this branch alternated twice, a
refused loopback post); `detect()` alone p95 0.015 ms warm (1,000 calls), 1.2 ms cold with its import (60 runs).

**Hookless apps, through the remote connector (ruling 32, owner 2026-10-19; amends G105 for apps with no hook).**
Owner: "Exports should only be a starter seed for users; the usual should always be real-time captures." claude.ai,
ChatGPT and their phone apps run no hook, so the one capture path they have depends on a model calling a tool — the
exception G105 names, taken knowingly and disclosed. The remote handshake's contract (and the tool's own description)
asks the app's model to call `cicada_capture_turns(message, previous_reply, conversation)` on every turn, before it
answers: the person's message word for word and its own previous reply word for word. The body
(`api/services/relay_capture.py`) is the per-turn writer below (`turn_capture.capture_turns(relay=…)`): the same
cleaning, scrub and caps, one episode per conversation keyed by the handle the handshake minted (a call without one
falls into the connector's day bucket), a re-sent turn `unchanged`. It is `record` scope, and behaves like a hook rather than a remote write: no commit of its own and no Sleep gate
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
too far apart upgrade nothing (a second episode, as before). A later relay into an upgraded conversation stays in that
one episode, marked as relayed (ruling 58, below).

**The Claude desktop app, on its local connection (ruling 57, owner 2026-11-04; amends ruling 32 and G105 for hookless apps
only).** The app has no hook and keeps no chat history on disk for a claude.ai account (measured by counts on 2026-11-04,
never content: no cached `chat_conversations` response among 64,273 HTTP cache entries; a 536 KB key-value store of drafts;
Cowork's settings), so its stdio server now does what the remote connector does.

- **Telling a client apart** (`relay_capture.local_relay_allowed`, one predicate behind `tools/list`, `tools/call`, the
  primer and the tool door). `initialize`'s `clientInfo` gives a self-reported `name` and `version`, nothing else. The tool
  is offered only when the name is exactly the desktop app's (`claude-ai`, `claude-desktop`, `handshake.CLIENT_VARIANTS`),
  no session is named (`SESSION.harness` is G48's `unknown`; no `CLAUDE_CODE_SESSION_ID`, `CICADA_SESSION_ID` or
  `CICADA_SESSION_HARNESS`) and `CICADA_CAPTURE` is not `off`. Before `initialize`, or for an unknown or unnamed client, it
  is not offered: such a client hears the same "Unknown tool" it always did and writes nothing. Claude Code calling itself
  `claude-ai` still carries the session id it injects, so it is refused; a client that lies the other way is simply not
  relayed. What cannot be told apart: a harness with a hook that both names itself `claude-ai` and injects no session
  would write a second, relayed episode, which still never counts as the person's own words.
- **One episode per conversation.** One stdio process serves all the app's chats, so a chat's handle comes from the tool:
  `conversation` is required, `"new"` on the first call, whose reply gives `lc_<day>_<hex>`, passed on every later turn (a
  chat outlives the process). The stdio process mints it where the call arrives (`relay_capture.begin`), before the call
  goes anywhere, so a queued call has one and a late answer written again is the same conversation. The home stays the
  writer. Any other string is refused, nothing written; there is no day bucket here.
- **Stored as relayed.** `harness: claude-desktop`, `evidence_kind: assistant`, `relay: {app: claude, channel: local, first}`
  (plus `device` from a client machine); never the person's own words; the same writer, scrub, caps and demo refusal as the
  remote relay. `app: claude` is why a claude.ai export upgrades it in place.
- **Both doors in one app.** A connector added on claude.ai also shows in the desktop app beside the local connection, and
  both ask. A conversation's first call on a door writes nothing and is told to stop (`elsewhere`,
  `turn_capture._kept_elsewhere`, under the episode lock) when one of the other door's person turns, written within 10
  minutes of when this turn was said, is this message whole, by the episode's own offsets: a reply offering a prompt to paste, or a turn quoting it
  inside a longer one, is another conversation. A message under the match key's 24 characters cannot be matched, so it may
  be kept twice, and a model that calls the second door first on a later turn starts a partial copy there. **Disclosed
  trade-off:** a person's message repeated exactly, as the first message of a new chat on the app's other connection, within
  10 minutes of saying it there, is read as the same conversation, and the new chat is not kept. Nothing tells them apart
  without a second tool call on every turn. A malformed episode among those scanned says nothing and never stops a turn.
- **Where it runs.** The backend that holds the bank, through `/tools/call`. On the home: this computer's, so its index
  worker follows; with that backend down the stdio process writes the file, queues no index job, and Sleep's own sync
  covers it. On a replica: its outbox, which answers "Queued for the home" with the handle, and with its own backend down the turn is
  refused, never written into the copy. On a client machine: the server's, refused when it cannot be reached. Every call
  carries when it was said and this machine's offset (rulings 34, 39), so a chat that waited days lands with its own day in
  its id and `timestamp`, and `received_at` the landing.
- **What the person sees, and the switches.** The tool's description says what it does in the app's own tool list, and the
  app asks before a tool's first use unless they allowed it always. The first reply of each conversation asks the model to
  say so once, in a few words; connecting the app says it in one line (`agent_wiring`); the remote connector's Record scope
  says it too. **No new setting.** To turn it off: in the app, set that tool to never run; or disconnect the app where it
  was connected; or `CICADA_CAPTURE=off` in the server's `env`, the switch every hook answers to, which also drops the
  primer's line. On the remote connector: untick Record or revoke it. `capture_assistant_replies` still keeps the replies out.
- **Why not the browser.** Anthropic's Consumer Terms §3 bar access "through automated or non-human means" except by API
  key or where explicitly permitted, so an agent paging claude.ai's list is what the ToS rail stops, unlike G166's reads.

**Reaching claude.ai on the web and phone** needs a public address for the remote connector: one click since ruling 59
(`network.md`). A connector added on claude.ai also appears in the desktop and phone apps. The local connection covers the
desktop app alone; the relay there needs no address.

**Exports are one-time (ruling 58, owner 2026-11-04).** A new memory's start, or what an AI provider holds; `app.md`, "An
export is one-time". The official export (web or desktop, never the phone apps) comes by email with a link that expires in 24
hours and has no schedule or API; its staging is per conversation and idempotent, and upgrades a relayed episode in place.

**Choosing what an export brings in (ruling 58b, ROR-126).** `POST /intake/sniff` gives every listed chat a `key`
(`import_choices.key_for`: the source's name and its conversation id — a hash of title and date only when the parser gave no
id, never the title), what an import would do to it (`new`, `grown`, `unchanged`) and `deselected` when the person left it out
of an earlier import into this bank; the delta never counts those. `POST /intake/import` takes `since` (`YYYY-MM-DD`; an
undated chat is kept) and `exclude` (a JSON list of keys) as form fields and applies them to the parsed episodes before
`plan` and the stager, so nothing is written for a chat left out. `exclude` is remembered in the bank
(`<bank>/import_deselected.json`, keys and a day, atomic, one writer): each upload replaces the decisions for the chats its file
holds and keeps every other file's, so ticking a chat again forgets it; with no `exclude` (the CLI shim, a relay door) the
remembered ones still stay out. The start date is not remembered.

**A chat that goes on after its import (ruling 58, owner 2026-11-04).** The later turns stay in the same episode: one
conversation for every count, found by the same `lc_`/`rc_` handle. `episode_staging.append_relayed` adds them after the imported
part, whose offsets never move (`relay.tail_at` is where they start, `relay.imported_hash` what the export wrote). The imported
part stays `user:`/`assistant:`, the person's own; each later person turn is `relayed [Claude]: …`, which `evidence._marker` reads as
`assistant`, the model's words, so a span, a promotion exchange and the Reader each resolve to the right kind with no episode-wide
`evidence_kind`, which could not say both. Any line of a relayed turn that would open a turn is quoted (`> user: …`), so a model's
words can never read as the person's own. Stamped in `turns`; a revision of itself (`revised`), so Sleep reads only what grew;
Stage 1 is told what the marker means (`relayed_note`). A re-send is `unchanged`: a reply the episode holds, and a message that is
its last person turn with no new reply, even one the export brought. Over the session cap on what grew, a turn is refused in words.
**Another import** compares with `imported_hash`, so the same export is a skip. A newer one replaces the imported part (an edit in
place, `merge_relayed_tail`): the later turns it holds are the person's own now and go, matched in order; the rest stay after it.
The person sees each later turn in the Reader as "Relayed by Claude", never "You". **Ruling 60 on a relayed chat:** a person's
turn, relayed before or after the import, is read as theirs when looking for a password, so it stays out of an engine's read and can
be removed, though its provenance stays the model's. A Remove moves `tail_at`, and text taken out stays out of a re-sent turn.

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
  **What a second machine's captures need to reach the home (B3, 2026-11-24).** (1) *A 202 is not a write*: a
  session post the server answered `202 accepted` (`routers/capture.py::answer_within`) stays in the spool marked
  `accepted_at` and is sent again after `hook_spool.ACCEPT_CONFIRM_S` (30 s); only an answer with the finished write
  (200/201) drops it, so a write that failed after the 202, or a home that restarted between the two, loses nothing (a
  resend is `unchanged` when it had landed). The same on the home's own loopback path (`_flush_local`). (2) *Nothing
  waits for the next firing*: a plain client (`CICADA_API_BASE`, no process of its own) starts one detached retrier
  when a post did not land (`capture.retry_spool`, one at a time by a lock in the spool folder, backing off 20 s to
  5 min, gone when nothing waits for the server or after 2 h; the child that reads a session over 16 MB starts one too —
  the retrier's own marker is `CICADA_HOOK_RETRIER`, never the long-read child's `CICADA_HOOK_DETACHED`); a machine that keeps a copy has its backend's follower
  send the spool through the same transport as every other request to the home (`replica._flush_hook_spool`, session
  and turn routes only; an entry whose target names the bank the copy follows goes whatever address it was captured for,
  and a computer that becomes the home drains its own bank's entries into itself, `home_move.drain_own_spool`).
  Marking an entry (accepted, held) or removing it re-checks, under one short spool-wide `flock` that `put` also takes
  around its rename (`.mark.lock`, never held across a post, a hook never waits past 1 s), that the file is still the
  one that was sent (`hook_spool.signature`: mtime + inode), so a newer snapshot of the session is never overwritten
  and a dropped entry never comes back — in `_flush_local` too. (3) *Said, not silent*: the spool counts what was refused for good or dropped by its bounds
  (`.counters`), and every session post carries `unsent` (`{waiting, held, rejected}`, counts only). (4) A hook that
  posts a path to a copy's own backend is answered by `replica_gateway` instead of `409 replica_read_only` (`headless.md`).
  (5) *A local entry never waits for a hook (2026-11-25)*: the entries `_flush_local` resends (`/capture/transcript`, the
  loopback port) are also sent by the backend itself once it is up (`local_spool`, a thread from the lifespan: first pass
  5 s after the start, each minute while one waits, three a pass), through the route's own writer on the home or a single
  computer and `replica_gateway` on a copy; an entry for another address or port is not taken, and one whose transcript is
  gone, refused or empty is removed and counted in `rejected` (`_flush_local` counts a refusal too). `headless.md`.

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

#### A rename at the source (ROR-122, ruling 69)

One module, `source_names`, holds the rule; each source that owns a page calls it inside the write it already makes, under
its own admission, page lock and commit (the module touches no file). `apply(fm, door, name, day=, was=, door_was=)`
returns `baseline`, `same`, `rename` (name changed, the old one an alias) or `kept` (the person's name stands, the
source's new one an alias). The frontmatter keeps `names_seen` (door -> the name it last reported), `name_source` (the
door, name and day a source last wrote the page's `name`) and, from the person, `name_by` (`project_ownership.apply_header`:
the app's and the agent door's rename). A removed alias (`aliases_removed`) is never re-added (`page_edits.keep_aliases`).

| Source | A rename before | After |
|---|---|---|
| Apple Books, Goodreads, scans (`books`) | the first real title stayed; the new spelling became an alias only | `ensure_page` queues the door's changed title (`BookIndex.renames`); `apply_renames` applies it after the person's own commit and commits it as `cicada` (`books/rename`); two doors: the one that last changed wins |
| GitHub repositories (`github_repos.upsert`) | the `github:` block followed, the page name stayed | the page found by GitHub's id takes the new `owner/name`, the old one an alias, in the sync's one commit |
| Added files, Voice Memos (`media_pages`, `media_files`) | a store rename with the same bytes was `unchanged` and never reached the page | the name alone is kept (the words stay), the next page sync renames the page; the Mac posts a `nameOnly` row, only for a recording it actually posted and whose title changed (`VoiceMemosReader.renamed`); the backend takes the name of a kept item and never its words or frames, and writes nothing for one it never kept. A page made before the rule (no `name_source`, no `names_seen`) records a baseline only when its name is the store's title (one `cicada` commit per chunk, once); any other name is the person's and is never renamed over |
| RSS, Substack feeds (`feed_registry.note_feed_title`) | the title filled once and never moved | the channel's newest title replaces it; the old one stays in `aka` |
| Notes, Calendar, Reminders, Linear, Notion, chats, transcript folders (episodes) | the title followed only when the body changed | `episode_staging` also shows a changed title when no word moved: frontmatter only, not re-queued, nothing a revision |

Not built: a project's name from its repository (the person's, ruling 56).
**Apple Books file entries (app-fixes-1109):** a file the person added to Apple Books has no store metadata — its title is the file name (dashes or underscores, no spaces, cut at 32 characters by Apple, observed on one title) and its author the literal `UnknownAuthor`. `apple_books.clean_title` makes the name words, drops the extension and a final word cut at the limit (a title with spaces is left alone); `clean_author` makes Apple's placeholders no author. Both run where the record is built, so a re-sync rewrites the record and the page's title follows by ruling 69. With no author, ruling 71's exact lookup cannot match and is not guessed; the page says so in words (`bookNoAuthor`).

#### Books: a scanned ISBN, Apple Books, a Goodreads export (G39, G233, 2026-11-04)

**A title finds the book (ruling 71, 2026-11-06).** `book_jobs.lookup_waiting` also asks about `books.title_candidates`: a
page from Apple Books or Goodreads with no ISBN, a real title, an author, no description and no "not this book". One
Open Library search (title and first author only, behind the connector gate, one request a second) per candidate, cached
outside every bank under `title:<hash>` in the ISBN cache; a match is one exact-normalised title and every page author on
exactly one work (`book_lookup.confident_match`), then the normal ISBN lookup fills the description. `books.apply_title_matches`
writes description, year, pages, publisher, subjects and a cover id (never title, authors or ISBNs) and marks `book.title_match`;
`POST /entities/{id}/book/not-this-book` takes it back for good. `GET /sources/books/backfill-plan` is a counts-only dry run.
**Google Books is the second catalogue (2026-11-08, owner "Yes setup Google book").** Open Library stays first: only a title
Open Library has *answered* and left with no description (no match, or a match whose record holds none) is asked, once, of
Google Books' volumes search (`book_lookup.match_google`: `intitle:"<title>" inauthor:"<first author>"`, nothing else, the same
one-a-second pacer and the same connector gate). **Only with the person's own key (owner 2026-11-08: "Make sure the Google books
stuff is free, and make it being your own key, and an optional source in settings").** Cicada ships no key and sends no keyless
request, ever — the ISBN lookup's Google fallback included: `book_lookup.google_enabled()` is false without a saved key, `_get`
refuses any `www.googleapis.com` request then, and an Open Library 404 alone is the ISBN's verdict. The key is
`CICADA_GOOGLE_BOOKS_KEY` in `secrets.env` (0600), in `CONNECTOR_SECRET_ENV` (stripped from every engine child), put on the
request only at the fetch (`_signed`: Google takes `key=`), never in a URL a caller holds, a cache entry, a log or a route's
answer. **It is an optional source in Sources → Reading** (`google_books_key`, `GET|PUT|DELETE /sources/google-books`; the app
is one client): off by default, it says what it does and that it is free, links to where a key is made, takes the key in a
field and removes it in one click. Save makes one read-only request (`volumes?q=isbn:…&fields=totalItems`) and keeps the key
only if Google accepts it; a refused one is a 422 whose `detail` is the fix. A 429, a 403 or a 400 about the key during a run
stops the run and is remembered as an enum and a time (`$CICADA_HOME/google-books.json`, never a body) so Settings says the
exact fix beside the field (`PROBLEM_WORDS`); a later good answer clears it. **Free:** Google's Books docs name no price and no
billing step for a public search with a key (a key identifies the person's project and its quota) and publish no daily figure, so
the copy claims none; the cap is Google's, and a closed quota only stops Cicada's run. The same rule: a volume's exact normalised title and an
author of the page, holding a description (`google_match`: authors exactly the page's first, then the fuller description, Google's
order last); cached outside every bank, the answer under `gtitle:<hash>` and the volume's record under `gb:<id>`; a 429 stops
the run and backs the title off. `books.apply_google_matches` writes the description (`description_source: googlebooks`, the
boxed paragraph "From Google Books, saved <day>") and the fields the page lacks, marked `book.title_match` (`source: googlebooks`,
or `google` beside Open Library's own marker); *Not this book* takes it all back. Not built: the one bounded Sleep read of a description (ruling 71 (a)); a tiebreak among duplicate work records (14 of 40
public titles were held back as ambiguous).

Three doors, one writer. Each door stages episodes through `episode_staging` (scrub, one id rule, both dates, the demo
gate); `books.apply_pending` turns every pending book episode into a page and claims with no model, inside the bank's
write admission from a route (`book_jobs.apply_admitted`) or inside Sleep's window from the tail
(`sleep_cycle._resolve_books_safely`, after the paper step). An episode is pending until its `book_applied` stamp equals
its `content_hash`, so the queue is derived from the bank — a move or a restore loses nothing.

- **A scan** — `POST /capture/isbn` `{isbn, status?, id?}` (`api/routers/books.py`). **The phone's contract; keep it
  stable**: `isbn` is the scanned EAN-13 (an ISBN-10 or hyphens are accepted), `status` one of `reading`, `finished`,
  `want`, `not_started` or absent (a scan with no tap says nothing about reading), `id` the client's own id;
  `Idempotency-Key` makes a resend the first answer (kept 8 days, `idempotency.LONG_ROUTES`, the outbox rule). Answers
  `{status: created|updated|unchanged, episodeId, isbn, book: "waiting"}`; 422 for a number that is not a book's. A
  capture-only phone may call it (`auth.CAPTURE_ROUTES`); on a replica it is `capture` (waits in the outbox). The
  episode (`origin: book-scan`, `processed_by: parser`, nothing in it for a model) holds `**Status:** <words>` and
  `**ISBN:**` lines: the person's act, so its spans are `user`. The lookup and the page follow in the background at the
  home (`book_jobs.schedule`). The scan's episode is committed with its page, like a note's is not.
  **What a scan became** (ROR-116): `GET /sources/books/scans/{episodeId}` answers `{state: waiting}` until the number
  resolves, then `{state: added, entityId, name, existing}` — `existing` when the page was there before this scan
  (`books.scan_result`; the Mac's Add reads it a few times, the phone ignores it).
- **One page per work, whichever door** (ROR-116, owner 2026-11-05: "it has to have some overlap with potential books from
  ibooks"; amends review of #600 B1). An identifier first (`BookIndex.find`: any ISBN, the work id, the source's own id).
  Only when none matches, **exactly the same words** (`BookIndex.find_words`): the title (or title + subtitle, or a
  source's own spelling kept as an alias) and the author names as a set, each with case, accents and punctuation set
  aside (`norm_words`) — nothing else: no prefix ("Dune" is not "Dune: House Atreides"), no article, no series note, no
  likeness. **Exactly one** page holding both joins it; an Apple Books entry (one in 284 carries an ISBN) and a scan of
  the same work are one page in either order, and so are two editions with no shared identifier. Anything less sure —
  two pages holding the title and authors, or one page's title with an author a side lacks or only partly shares — never
  joins: the record keeps its own page and `books._ask_same_book` files one "Is A the same as B?" per candidate (≤ 3,
  `role_people.ask_same`, answered by folding one page into the other, `merge_rejections` respected). The same title by
  other authors is a different book and asks nothing. A page keeps its marks, status records and history through a join
  (a join only adds identifiers, aliases and the source's id). Pages made before this are not swept: two that already exist
  stay two. A page records its doors (`book.doors`: `apple-books`, `goodreads`, `book-scan`) and `GET
  /entities/{id}/book-status` answers `ways` (`books.ways_in`: "Apple Books", "Goodreads", "Scanned"; an older page is
  known by its Apple Books and Goodreads ids), which the page's status line shows when there is more than one.
- **The lookup** (`book_lookup`, home only): Open Library's `/isbn/<isbn>.json`, `/authors/<id>.json` (≤ 3, from the edition,
  else the work's), `/works/<id>.json` (a description, subjects), and Google Books `volumes?q=isbn:` (only with the person's own key, 2026-11-08) whenever one still lacks
  an author, description, publisher, page count or year (**merged**: Open Library's value kept, Google Books fills the rest;
  alone when Open Library has no edition). **A page is worth opening (G233, 2026-11-05):** the answer carries `description`
  (the source's own words, capped at 700 characters at a sentence end — a blurb, not the publisher's page — never a model's),
  `description_source`/`description_url`, `publisher` and ≤ 4 `subjects` (a machine tag, anything with `_`, `:` or `=`, is dropped in `book_lookup`, and again on a cached answer); a cached answer carries `v: 2` and an older hit is
  asked again **once** (`book_lookup.stale`, via `books.waiting_isbns`, same pacing, cache and gate; a failure backs off and
  keeps the old answer, a miss never erases it). The page's article is the description under its source and the day saved
  (`## Summary`, then "From [Open Library](link), saved <day>", ruling 44's shape); with none the article is empty — the
  `<Title> — a book.` line is gone from every writer (`books._book_prose`, which also clears it from older pages and never
  touches words a person or agent wrote). The pages it enriches from the cache and the cover stamps are **Cicada's own rewrites**: `apply_pending` returns them as `cicada_paths`, committed alone under `cicada` (`books/enrich`), never in the commit of a scan, sync or import; the Sleep tail commits them with the rest. `book.publisher`/`subjects` fill once; a person's title is never replaced.
  `GET /entities/{id}/book` serves the head's facts and the ways in (`ways`: Apple Books, Goodreads, Scanned with the scan's
  day, from `book.doors` and the episode); `GET /sources/books/scans/{id}` adds `authors` and `cover`. A scan episode is in
  no search index and its list row, while the number waits, reads "Looking it up…" and opens nothing: the book is the item.
  Requests: one a second, a redirect hop paced like any request, the pacer shared
  across runs (Open Library's unidentified rate, read 2026-11-04), the ToS
  rail's 4 s / 512 KB / no cookies / ≤ 3 redirects, `net_guard` on every hop, a User-Agent naming the software and no
  person. Behind `CICADA_ALLOW_CONNECTOR_FETCH` on both callers (the background job after a scan and the tail): off,
  the scan waits (`GET /sources/books` counts it as `waiting`). Every answer is cached outside every bank
  (`$CICADA_HOME/books/isbn_cache.json`): a current hit is never asked again; a definite miss (Open Library 404 and zero
  Google results) makes a placeholder page ("Book with ISBN …") and is asked again after 30 days, the page upgraded in
  place; no answer backs off 10 min → 1 h → 6 h → a day and makes no page. At most 30 numbers a run.
- **Apple Books** (`apple_books`; the app's `AppleBooksReader`). Turned on by the person (Sources → Reading →
  Apple Books; `PUT /sources/apple-books/settings`, a sync while off is 409). A folder or store macOS refuses is
  `BrowserFileError.notReadable`, the Full Disk Access sentence with its button, never "Open Apple Books once"; only an
  absent folder reads as not installed (ROR-41). The APP copies the two stores with their
  `-wal`/`-shm` into a temporary folder, folds the WAL into the copy and reads it read-only — paths and columns in
  `apple_books`' docstring, read on macOS 27.2: `~/Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary/
  BKLibrary-1-<version>.sqlite` (`ZBKLIBRARYASSET`) and `…/AEAnnotation/AEAnnotation_v<version>_local.sqlite`
  (`ZAEANNOTATION`, type 2 = highlight; bookmarks and the reading position never read). It posts only books whose
  status, dates or highlights changed since this memory accepted them (a fingerprint per asset; progress alone is no
  change) — the incremental re-sync. One episode per book (`apple-books:<asset id>`), a saved record (`authorship`:
  `apple-books` is a saving door): the status line and each highlight (a `## Highlight, <day>` section, quoted) are
  the book's words (`page`), the person's note under it a `## User note` section (`user`). Highlights are ordered by
  when they were made, so new ones append, and the episode's `timestamp` follows the newest highlight (`redate`).
  **Status from Apple Books' own state, never invented** (owner 2026-11-04): finished (`ZISFINISHED`, on
  `ZDATEFINISHED`), else reading (progress above 0, on the last open), else not started (on the day it entered the
  library). Only a finish with `ZDATEFINISHED` is also a dated "Finished reading" happening; Apple Books keeps no day a
  reading began, so a reading or an undated finish is a status record only (review of #600, B2). One book is trimmed on
  its own — the oldest 3,000 highlights, each cut at 4,000 characters, the body at 400k — so it never refuses the
  rest of its request. **Never silent** (re-check of #600): the body ends with one `**Not kept:**` line (no count, so a
  later highlight does not re-queue the book), the record keeps `trimmed`, the sync answers `trimmed` and
  `trimmedBooks` (asset id → count), and the Apple Books page's line says "N highlights past a book's limit not kept". The
  oldest are kept rather than a rolling window: rolling would drop the earliest highlights on every sync, and Sleep
  reads a removal as the source withdrawing what it said. A book with a highlight or a note is queued for Sleep; a library entry with neither lands read
  (`processed_by: index`).
- **Goodreads** (`goodreads_export`). Its public API stopped issuing keys in December 2020 and its pages are walled, so
  the way in is the member's own "Export Library" CSV, picked in the app (`POST /sources/goodreads/preview` counts,
  `/import` stages). Shelves: `read` → finished (on Date Read, else Date Added), `currently-reading` → reading,
  `to-read` → want (a happening only for a finish with a Date Read); a custom exclusive shelf records no status; a 1–5 rating is a `rated` claim. One episode per row
  (`goodreads:<Book Id>`, a saved record); only a row with the person's review or private notes (`## User note`) is
  queued for Sleep. Nothing is read from the Goodreads site.
- **An agent's add (2026-11-06, `cicada_add_book`; `mcp.md`).** The fourth way in: an agent the person asked adds a book by the
  ISBN it found, through the scan's episode and writer with `book.by` = the harness, no status and no model. The page's
  way in reads "Added by an agent" (`books.AGENT_WORDS`) unless the person also scanned it; a book already on a page is
  joined by identifier like any scan.
- **A door's list** (`channel_items`): `GET /sources/channels/{apple-books|goodreads|book-scan}/items` is that door's
  books, one row each, a `page` row once it has its book page (a book has no saved link, so a click opens the page).

**What the person marked is kept word for word (ruling 64, ROR-95, `book_marks`).** Each `## Highlight` and `## User note`
section of a book's record is a claim on its page, written at the door by `apply` with no model: `highlighted` (the book's
words, a `page` span) and `noted` (the person's, a `user` span), id from the page, predicate and words, `valid_from` the
highlight's day, `origin: book`, `authored_by: user`. `claims.is_mark` is the one test (predicate and origin, so a model
writing the word is not one). The writer makes the page match the body: a span follows when a status line or an earlier
section moves it, a passage gone from the record closes (`valid_to`, unless another door's record holds it), comes back
open if marked again, and one the person took back (`retracts`) is never rewritten; a re-sync reopens neither recovered
history (`claims.is_recovered_history`, G148) nor a mark a successor closed. `episode_revision` never closes one.
Its stamp is `book_marks:` beside `book_applied`, so a record applied before this gets its marks with no second status; a
page merged away since sends them to the page it became (`page_redirects`), and a record with no page left is stamped, not
retried. A changed record follows the page it was last applied to the same way when no book holds its identities
(`books.ensure_page`, `was`), copying them onto a winner that is a book; any other page holds what the record says and is
never turned into one. A claim keeps its id through a merge and the id came from the old page's, so mark, status and rating
writers also look under the ids that became this page (`page_redirects.former_ids`): nothing is said twice, what was taken
back stays taken back, and a passage both pages held becomes one open mark on the next apply of either record. A big book spills into its ledger. What the detector flags is written as `[held back: <kind>]`, the record untouched; a
saved record's own sections (`evidence.PERSON_SECTIONS`) are now read by `sensitive_text.find`, a passage still not.
- **Drawn from the claims, derived on read:** the `marks` block of `page_blocks` (`blocks-4`), each note under its passage,
  at most 500 with the total, the card's `PageMarks`, an agent's `include=["marks"]`. Search and recall reach them through
  the claim leg, so a passage's own words find its book. Never a belief sentence (`page_citations`), never quoted in the
  "why it matters" line (a count: "you marked 3 passages in it").
- **Gated like the person's own words** (`is_persons_words`). A caller without `sources` gets counts and days: the block
  masked, the page text masked (`masked_page`), a split preview's rows masked (`split_plan(own_words=)`), perspective and
  Ask without them (`_HIDE_MARKS`). The first three hold for every claim in the person's own words, a Log entry too;
  `test_a_caller_without_sources_reads_none_of_their_words_through_any_remote_tool` calls every tool in the remote table,
  and a new tool fails it until it is aimed at such a page.
- **No model that writes a page reads one:** the article writer's inputs and `material` (`entity_article.build`), the
  orientation's `current_claims` (`entity_orientation.context`), and a removed passage in a revision (`changes_of`, a note
  still counts). Conflict checks, Stage 2 and the merge read prose with the fence stripped. The catch-up chat's belief lines
  leave them out too, and the Beliefs list (`GET /claims`), since the page's block draws them. Read on purpose: Ask, for the
  person, and the settling agent, whose only output is a quote checked on a fetched page (ruling 54).
- **Lit:** a record holding a mark counts as a conversation (`quiet_pages.marked_record`).

**Sleep reads a marked book for what its marks share (ruling 64).** A note before Stage 1's chunk (`book_marks.note`) says
a passage is the book's words and never a fact about the person, a note is theirs, and every word is already kept; it asks
for 1 to 3 themes as `concept` entities of one to three words (`decay_class: durable`) and an `explores-theme` link from the
book with a passage as evidence. In code, because haiku ignored the same words: the status, finish and rating lines are
blanked with offsets kept (`mask_status`); the book's own entity is dropped and its links land on the page by name; and the
owner's entity is dropped too, note or no note, since a summary or key fact on it rests on no span (`of_a_read`). What
reaches the owner's page from a book's read is a relationship or a value, on either end, located in a `user` span inside a
`## User note` section, and nothing else. "The owner" is any name that could be theirs: a self-reference, a name
made only of their page's words (`role_people.owner_names`), a close spelling (`fuzzy_same`), unless this read types it as
no person. Only the full name or an alias is rewritten to the page's name; a bare first name or surname in a note stays as
written, its entry with it, since it may be a friend (rail: never the owner's page without their own words naming themselves
so), and Stage 2 holds it or asks. Outside a note such a row is dropped. **One call a book:** past 12,000 characters (`plan_read`) the chunk is the header, every note, then
passages spread evenly and cut at 700, located over the whole body; a revision reads its window, or a spread of it past
that. **Themes meet because books are read one at a time** (`process_one`), each told the names on record (concept pages book
pages link to, names held from a book's record, at most 60, `theme_hints`) and the names of this fan-out so far, so the 2+
rule can count two books. A theme named by one book waits in the pending store. A theme from old highlights is born
`decaying` at 0.39 by the age rule.

**Sleep reads the highlights** (owner 2026-11-04: "be able to consolidate highlights and such is important"). A
re-sync that adds highlights edits the book's episode in place, and Sleep reads only what changed
(`episode_revision`, #581). **Measured (2026-11-04, verify run, Claude plan at haiku, synthetic library):** a first
read of 5 waiting episodes — 3 Apple Books books carrying 40 highlights and 2 notes (7.2k characters), 1 Goodreads row
with a review, 1 chat — took 15 calls, 64.6k input and 15.8k output tokens, $0.0128 at list price (the plan's own
counter: under 1 % of the seven-day window). Three new highlights on one book, re-synced: 1 episode re-read as a
revision, 3 calls, 14.0k input and 4.9k output tokens, $0.0037. **Estimate for a realistic library** (basis: the
per-book figure above, ~13–16k input tokens per book episode, most of it Stage 1's own prompt): 500 highlights over 40
books ≈ 40 episodes ≈ 0.6M input and 0.16M output tokens on the first read, ≈ $0.13 at haiku list price (a larger
model costs in proportion). It is paced like every read (rulings 13, 16): a drain over the ids frozen at its start, in
committed batches of 25, a plan limit a pause, never a failure; later syncs cost about one extraction call per changed
book.

**Pages** are described in `storage.md` ("Book pages"). **Promotion:** a book page is made by a door — a scan, a
library, a shelf — the way a save makes a media page (a deliberate signal, no promotion gate). A book only ever named
in a conversation follows the normal rule (2+ conversations, …); Stage 1 never produces `media`, and once a book page
exists the resolver meets a mention of its title or any alias (each source's own spelling of the title is one) — the
verify run's chat naming the book was joined to its page by a normal Sleep. Ruling 42's one-conversation exception is
not extended to books (owner decision listed in G233).

**A chat changes a status (ruling 61, owner 2026-11-04; `book_said`).** "Yes, change the book status in that case. But
it has to be in the context, we can always go back and correct." Stage 1's prompt gains an optional per-entity
`reading_status: {status, quote, on?}`; **the model judges, in context, and there is no keyword list** (about 150 prompt
tokens on every Stage 1 call). `book_said.at_extraction` takes the field off the entity (nothing of it reaches a page) and
keeps it only if what a model cannot vouch for holds on the record: the quote is located (exact → whitespace → case, never
fuzzy) inside a `user` turn — an agent's reply, a meeting's other speaker, a saved record and an agent's saved note never
are; the title is said somewhere in the conversation; the conversation is dated; the episode is not a door's own. The mark
rides on the extraction's result.

- **Where it meets the writers.** Stage 5.565, after the claim layer and before the episodes are marked read:
  `book_said.settle` stamps each mark on its episode (`book_said:` in the frontmatter, `{name, aliases, status, day, stated,
  quote, joined?, page?}`; a held row's quote is a copy of words in that same file, so a revision that removes them removes
  the row, and an applied row keeps only their hash, `said`, which with the name and status is what makes a re-read the same
  row whatever day it gives them)
  and `apply_waiting` applies what is clear. The status goes through `books.set_status`, the happening through
  `books.record_happening` → `progress.record_happening`: no second writer, and the rail "only `progress.py` writes
  `happened`/`milestone`" holds. The batch's commit carries it, under Sleep's author and engine; the claim's `authored_by` is
  `user` because the words are.
- **The right work.** `TitleIndex.clear_page`: exactly one book page whose name, title or alias is the name said; else one
  whose title without its subtitle or series note is; else the book page Stage 2 joined that name to. **Two pages (a copy
  with no shared identifier keeps its own page, B1) is unclear: nothing is written**, the mark stays held, and Stage 2's
  same-title question (G227) is the way out.
- **No page yet.** A first mention stays under the promotion rules: no page is made for it, Stage 1 still never produces
  `media`, and ruling 42 is not extended. The mark stays held on the episode, nothing lost. Each door's apply and each
  Sleep tail run `apply_waiting`, so when a scan, a library or a shelf makes that title's page the status lands there, dated
  as it was said. A page the normal rule makes from chats is an ordinary page: it carries the words as prose and history,
  never a `reading-status`.
- **Dates and order.** Dated by the conversation, or by `on` when it states a day (never after the conversation). The chain
  orders by that day, so a late read lands closed, as history, and never overrides a newer status. On one day the record
  further along stays open (`books._RANK`: reading over want or not started, finished over reading), whichever was read
  first; a scan's tap stays the later wins. **A real conflict** — one day, and the person's words say less than a record
  holds ("still reading" the day the library says finished) — keeps the record open and asks once through the existing
  conflict path; the answer stands against later writes. A later status from a door (Apple Books re-synced after the book
  was opened again) is newer evidence and wins too.
- **Happenings.** A finish is a "Finished reading" on its day (`stated` or `episode`); a reading is a "Started reading" only
  on a day the conversation states (B2), else a status record alone. Both cite the located span, so an agent saying the
  identical words first is never what they rest on. **Said again:** when the record beside that day by date holds the same
  status, a conversation only adds its episode and span to it: no second record, no second happening (unless the page holds
  none yet, a door's record with no date). A reading in between makes a later finish a second reading. A repeat read late
  joins the later record, so that record keeps its own day: the one place the order of reading shows.
- **Undo.** The book's page says the status in one line, with *Not right* when a conversation set it (`POST
  /entities/{id}/book-status/undo`, the person's commit, the G113 `overruled` signal). The record is kept as history behind
  a `retracts` record, the status before it opens again, its happening is withdrawn, the "Started reading" thread that
  finish settled opens again, and neither a re-read of that conversation (whatever day or quote it gives) nor a revision
  writes it again; another conversation saying it on a later day is a new record.

**Measured (2026-11-04, verify run, Claude plan at haiku, synthetic library and turns; evidence under the run's folder):**
"I finally finished <title> last night." → finished, dated the day before, located span of kind `user`, a "Finished reading"
`stated`; "I started it on Sunday and I am a third of the way in." → reading, dated that Sunday, a "Started reading";
"My friend <name> finished <title> last week", "I'd love to finish <title> some day", an assistant's "You finished <title>",
"I watched the film of <title>" → no mark, status unchanged. A first mention with no page was held, and a later library sync
naming that title applied it, dated as said, under the door's own commit. *Not right* reopened the earlier status.

- **Choosing what goes in (2026-11-06).** Where several books arrive at once the person confirms all or picks some, and nothing is staged before: `POST /sources/goodreads/preview` also returns `items` (`id`, `title`, `author`, `status`), `POST /sources/goodreads/import` takes an optional `ids` form field (JSON list; omitted is every book, `[]` none, a malformed one 422). Apple Books is chosen in the app (`AppleBooksStore.partition`): a book memory has never accepted waits, a declined one is not asked again, an accepted one is kept current as before. Books already in are untouched. A scan is one explicit add and goes in at once.
- **Goodreads through the person's own browser (ROR-128, ruling 72, 2026-11-06).** The first way in: the person turns on *Read
  through your browser* (Sources → Goodreads; off until then, `saved_lists.PLATFORMS["goodreads"]`) and their own agent opens
  their shelves (Read, Currently Reading, Want to Read) in their own signed-in session, then reports the books through
  `cicada_record_saved_list(platform="goodreads", items=[{id, title, author, shelf, rating, date_read, date_added, review}])`.
  The backend never opens a Goodreads page. The books are **held, not staged**, in `$CICADA_HOME/goodreads_waiting.json`
  (`goodreads_waiting`: 0600, `flock`ed, ≤ 500 waiting, outside every bank) as rows in the export's own column names, so the
  choice is #666's: `GET /sources/goodreads/waiting` (the preview's row shape) and `POST /sources/goodreads/waiting/choose`
  (`{ids}`; the ticked go through `goodreads_export.stage_rows` — the file's writer — and the rest are left out for good,
  remembered by id). A book already in memory by any door, or left out before, is never held. One episode per book
  (`goodreads:<Book Id>`) whichever door, so the file imported later edits it in place. Not built: reading a shelf's
  pages past what one read shows (the agent reads a few screens), and a book unshelved on Goodreads stays here.

### Sleep — 5-stage nightly batch
1. **Entity & relationship extraction** — LLM over episode chunks, structured output.
2. **Entity resolution & dedup** — exact name, fuzzy match, embedding similarity, LLM disambiguation
   (bounded concurrency, decisions in order; a recorded alias brings its page to the judge; see below).
3. **Conflict resolution & pruning** — contradictions detected, recency wins, old state archived;
   temporal decay applied (pages' calls overlap, results applied in order; see below).
4. **Pattern detection & skill extraction** — recurring patterns distilled into skill entities, each written only
   with the conversations it came from (see *A skill page carries its conversations*).
5. **Nudge generation, clarification queue & versioning** — snapshot, git commit.

**Off the event loop (G238, 2026-11-05).** Sleep runs on the backend's loop, so anything it does between two awaits
holds up every request. A run's bank-wide reads go through `asyncio.to_thread`, and Stage 2 runs whole on a worker thread
(`entity_resolver.resolve_off_loop`) on a loop of its own, because its lookups and its deferred writes are woven between
its judge calls. Only those calls go back to the backend's loop (`_on_engine_loop`), where the engine's clients,
subprocesses and plan-limit state live; the context travels with them. The batch awaits the thread, so the stages' order,
the write window and the clean-tree slot do not change. A cancelled batch tells the thread through its `cancel_check`,
and `resolve` then writes nothing. The pending store answers by name from one index per change of the file
(`pending_store.held_line`, `apart_of`; `load` still parses every line, for a caller that wants them all). A new
bank-wide read in a coroutine belongs on a thread: `test_sleep_stage5_off_loop.py` lists the steps, and `make test-bench`
asks `/healthz` over a socket through a whole batch at 8,500 pages (`test_stage2_off_loop.py`).
**What a stall costs (measured on a real socket, `test_capture_survives_a_stall.py`).** The listener still accepts, so a
hook hears nothing rather than a refusal. A Stop gives up at 3 s and spools; a per-turn post from this machine does not
spool. Both still land once, because the loop serves a request the client abandoned when it wakes, and the writers are
idempotent. Only a backend that dies before it wakes loses an unspooled turn.

**An edited conversation is read as a revision of itself (G104, owner 2026-11-03).** Many sources re-stage an episode
Sleep already consolidated — an edited note or meeting transcript, a chat whose 48 h window is re-posted, a re-imported
export upgrading in place, a resumed session — and `episode_staging` rewrites it in place with `processed: false`.
Measured before this (scratch bank, Claude plan at haiku, four synthetic notes consolidated then edited in place): the
second Sleep re-read all four whole (8 calls, 42,142 input tokens); every one of 10 spans into the four read `stale`
and 5 claims gained a second span beside it; the removed line's claim stayed open; the whitespace-only edit asked a
conflict question ("MIT" vs "MIT license"); four names said once in unchanged lines got pages (the link rung, with a
page now existing); the page prose kept the old fact beside the new. `episode_revision` makes the edit a revision:
- **The version last consolidated is git's.** The stager's edit-in-place record (`revised: {count, at,
  previous_hash, consolidated_hash?}`, `episode_staging`, G95) names it: the committed version whose `content_hash` is
  `consolidated_hash` (consolidated by Sleep or an agent). Sleep refreshes `consolidated_hash` to the body it retires
  (`episode_revision.mark_consolidated`, under `episode_lock` in `_mark_episodes_processed`) and never starts a record
  on an episode that was never edited. With no record (a transcript, a writer that does not stage) the prior is the
  version committed `processed: true, processed_by: sleep`. Each loaded batch's waiting episodes are read at the bank's
  `HEAD` in one `git cat-file --batch` (no capture writer commits by default, so `HEAD` holds it until Sleep's next
  commit); with the capture log published (G132 51e) the file's own history is walked, at most 20 commits. A parser's
  version (`processed_by: parser`) is never a prior. No git, or no such version: read whole, as before. Reads only.
- **The diff is by line, on the words** (`difflib`, whitespace ignored): `changed` ranges in the new body, `removed`
  ranges in the read one. Only whitespace moved is a **no-op**: no engine call, the spans re-anchored, the episode
  retired. A pure removal also reads nothing.
- **Stage 1 reads what changed** (`windows`): each changed range with 2 unchanged lines after it and at least 2 lines and 4,000 characters before it, merged; past 60%
  of the body the whole body. Each window carries `REVISION_NOTE` ("this conversation was edited after it was read…").
  Evidence is still located against the whole stored body. Of the answer, a relationship or value located only in
  unchanged text, and a name said only there, are the first read's and dropped (`keep_changed`): a re-read is never a
  second chance at promotion. One with no locatable span is kept — provenance never blocks memory.
- **Stage 3, before the reconciler** (`reanchor`): every span into a revised episode minted on the read version (its
  hash, or a grown prefix of it) is located again in the matching lines of the new body — exact, whitespace,
  case-insensitive, never fuzzy — and takes the new offsets and hash. An open claim whose only support is spans the
  new body no longer holds is marked; never one another conversation also says, the person's own (`is_human`), an
  agent's write (`recorded_ts`), an event, a record, one with a `reasoning` entry or a span on an older body for that
  episode, nor anything in a transcript (`capture_kind: transcript` drops old turns by its session cap, not by
  revision).
- **The same source revising itself is not a conflict** (`claim_reconciler._place_claim`, `revised`): a new value read
  from that same episode closes a marked claim on its slot (`superseded_by`, the owner's-words rail `may_close` still
  holding) — no question. A value from any OTHER conversation meets the trust table as before: a later conversation
  saying something different is an update or a conflict, which is how memory evolves.
- **After the reconciler** (`settle`): a marked claim stays open when another conversation read in the same batch now
  supports it (its evidence or `source_episodes` cite another episode — an unsent message splitting a Messages sitting
  does this), or when the revision said it again: Stage 3 reports every marked claim it reinforced from that revision
  (`revision_restated`), whatever the evidence kind — an unlocatable quote arrives as `reasoning`, which `_reinforce`
  drops for a conversation the claim already cites (R8), and is still a restatement (provenance never blocks memory). A
  restated claim with a located new span keeps only that span. Every other is withdrawn by a born-closed `retracts`
  record (`authored_by: cicada`, reason "The conversation this came from was edited and no longer says it.", evidence
  `reasoning` on the episode with the revision's body hash) — never deleted.
- **The same conversation.** The episode keeps its id, so the 2+ conversations rule, promotion and decay credit count
  it once; `processed_by` stays `sleep`. A revision Stage 1 failed to read stays queued with its claims untouched.
  The claim pipeline logs the counts (spans re-anchored, no longer in the text, replaced, withdrawn).
- **Measured after** (the same four notes, Claude plan at haiku): the second Sleep made 5 calls, 22,927 input tokens
  (extraction ran for the two edits with new words only), 0 questions, 0 pages, 5 spans re-anchored, 1 claim withdrawn
  (the removed line), 0 duplicated spans. `test_episode_revision_sleep.py` pins the four cases on the engine seam
  (2 extraction calls, the changed value superseded with no question).
- **Left (G104):** a transcript's replaced reply (Cursor's final reply for a generation) closes nothing; a held claim
  only the removed text said keeps its span `stale` in the pending store rather than being closed there. The prose,
  the section rows and the held spans are slice 2, below.
- **A stale date beside the corrected one: measured, three fixes tried and dropped, a fourth built for the date shape (2026-11-24, 2026-11-25;
  `benchmarks/consolidation/revision_e2e.py`).** A claim the first read wrote from one line but dated (or named) from
  another keeps its span on the unchanged line, so the span test never marks it; and the re-read words the
  relationship under another predicate (`is-moving-to`, then `moves-to`), which is another slot, so `redated` never
  meets it. The old date stays current beside the new one. Of 62 stored failures of the consolidation benchmark's own
  edited conversation, 55 have this shape. On 17 invented two-night stories through real Sleeps (plan, Sonnet main,
  Haiku judge; 10 runs): wrong in 49 of 170: a corrected date 29 of 70, a corrected name 18 of 20, a removed sentence 2
  of 20; a corrected number, an added sentence and a fact a second conversation also says, 0 of 60.
  Three designs were built and measured, each was broken by an independent review with scripted readings, and none
  is merged:
  1. *A rule on the words:* close a claim whose day, number or name the removed text says and the new body does not.
     0 of 170 wrong on the stories, and it withdrew claims that are still true: a `Date:` header removed withdrew every
     claim of the conversation; "3 may attend" read as the 3rd of May; a date rewritten in words or another language, a
     corrected spelling and a reformatted number all counted as gone.
  2. *A rule picks candidates; the re-read (same subject and object, another day) or one main-model reading with
     code-checked quotes closes them.* 4 of 119 wrong, and it closed relationships still stated: a correct "the day
     changed" reading closed the relationship when the re-read wrote nothing in its place, and a re-read claim about a
     visit superseded a move to the same place.
  3. *Never close what is still said: a verified reading only takes the stale day off the claim; a name closes only
     beside the re-read's replacement.* Dates 0 of 28 wrong, names unchanged (6 of 8 wrong). The day came off for good:
     a claim's id embeds its day, so the same relationship stated again (the edit undone, or another conversation)
     merges into the dayless claim by id and nothing restores the day; a conversation read the same night that states
     the day lost it too; a held claim released after losing its day was stamped with the run's day; and the record of
     the day taken off lived only in the run's return value. The name path closed a claim beside any same-subject claim
     from the changed lines, and "the name is gone" compared whole tokens, so an inflected form, a translation and a
     script written without spaces all read as gone.
  What the three teach, for whoever takes it next: (a) words in the text cannot decide what a conversation still says:
  a day number, a month's first letters and a name's spelling collide with ordinary text in every language; (b) the old
  claim must never end with nothing in its place; (c) clearing a field in place is unsafe while a claim's id carries its
  day and a merge never restores one; (d) a rule about a name must read the page's aliases and substrings, never whole
  tokens.
  **The fourth, for the date shape only (2026-11-25, `revision_pairs`): act where the re-read's claim meets the old one,
  on two readings.** A *pair* is an open page claim this one edited conversation alone says (`episode_revision._closable`;
  never a value, a number, an event, a record, the person's own or an agent's, nor a capped transcript) and a claim of the
  same revision's re-read with the same subject, object, context and speaker, ANOTHER predicate, and a start or end the
  old one does not carry that the changed lines say (`says_day`, the test `redated` already makes of the new claim),
  while no start or end of the old one that the new one lacks is still said by the conversation as it now stands
  (2026-11-26, `revision_pairs.moved`: "8 December (she first planned 5 December)" says both days, so neither moved and
  no pair is read; a text that keeps the old day as a former plan therefore leaves both claims open, as before this
  rule, even where the readers would have been right). A claim that has since taken another claim's place by anything
  but this conversation's own revision (the person's pick in the inbox, an ordinary update) is never a pair
  (`revision_pairs.won_elsewhere`, the fifth review, below). The cheap tests run first and each day is read once per
  revision (`revision_pairs.Said`; nothing is computed past either cap, and a stop is asked for before each re-read
  claim is compared): on a page of 3,000 claims and a revision of 20 dated re-read claims the step took 39 s, now
  0.1 s. Before Stage 2 opens the write window (pages read only), Sleep's small judge is shown each revision's pairs (at most 8
  a revision, 12 revisions a batch) with the words each fact was recorded from, the edit and the conversation as it now
  stands, and asked whether the two word the SAME relationship or two that can both hold; the cycle's main model is asked
  the same of the pairs the first called the same. One call per reader per revision with pairs, none without; metered as
  `revision_pair` (`sleep_spend.LINE_STAGES`), through `providers.resolve_llm_fn`. Only the answer `"same"` from both
  counts; a "different", anything unreadable or a failed call leaves both claims as they were. After Stage 3 and
  `settle`, `revision_pairs.apply` replaces the old claim the way the same-slot replacement does (`_close`: closed,
  `superseded_by` the re-read's claim, which `supersedes` it; audit `revised` with `why: edited_same_relationship`,
  kept by `telemetry.record_audit` and counted in the batch's Corrections record), every condition checked again then:
  the old claim still open and still this conversation's alone (a conversation read the same night that says it keeps
  it), the re-read's claim open on the same page, not merged into a closed claim, superseding nothing else, citing this
  conversation and carrying the judged day; one re-read claim replaces at most one old claim. Nothing is cleared,
  re-dated or written that the re-read did not write. Held claims are paired too since 2026-11-26 (below).
  **The worst a wrong reading costs** (both readers always "same"): one claim of this conversation superseded by another
  claim of this conversation about the same two things, carrying a day it now states — a move closed beside a visit to
  the same city the edit put in (`test_revision_pairs`).
  **Edited back (2026-11-25, `claim_reconciler._edited_back`): a claim closed only because this conversation corrected
  itself, which a revision of the same conversation now states again, is current again.** Before, an edit undone ended
  on the corrected day alone: the re-read restates the first claim exactly, its id carries its day, and it folded into
  the closed claim (`_reread_twin`, "a re-read never undoes a close") — on the pair rule's path and on the same-slot
  path (`redated`) alike. Now, when the restated claim's closed twin was closed as `superseded_by` a chain of claims that
  rest on this one conversation alone (never the person's, an agent's, a record, an ending, an event, recovered
  history), the chain ends in an open claim, the restatement is heard in that conversation only, and that conversation
  is a revision read in this run that may close, the restatement is born under an id of its own (the closed claim's id
  is taken; `_fresh_id`, the same on every run) and meets the open claim in the ordinary table. **The conditions as they
  stand after the fourth review (2026-11-26)** — the restatement is born only when all hold, otherwise it folds into its
  closed twin as before: (1) the chain above, this conversation's alone, ending in an open claim, **every closed link of
  it, both ways, marked as closed by this conversation's own revision** (`closed_by_revision`, 2026-11-26, below); (2) the text says it
  was edited back: the restatement is not a copy of that open claim (the same slot, object, start and end — a claim is
  never superseded by a restatement of itself, on any route), and where the two carry other days, the restored day is
  said by the changed lines and none of the open claim's days is still said by any line of the conversation
  (`revision_pairs.moved`, the pair rule's own condition) — this strict test where the open claim sits in the
  restatement's own slot and would give way at once; under another wording the restatement is only born beside it
  (the fifth and sixth reviews, 2026-11-26, below); where the days are the same (a value), the open claim's own words
  are gone (`revised`); (3) the re-read states it; (4) the open claim may give way by a rule that already exists —
  the same-slot replacement (`redated`), the removed text's (`revised`) or the pair rule (`revision_pairs.meets`). On
  the pair rule's path the reading comes after Stage 3, so the restatement is born before it: if both readers call the
  two the same the open claim gives way; a "different", a failed call or a split reading leaves both days open, which
  is exactly the end `origin/dev` reaches on the same text (a failed reading settles nothing). Accepted limits: a day
  the date reader cannot find counts as not said, so a day still stated in words it does not read leaves the rule as it
  was. **The fifth and sixth reviews (2026-11-26): the text test is chosen by what a refusal costs.** (a) *A true
  undo was refused* (fifth): the undo test asked the whole conversation whether the edited day was still said; with
  another line saying that day of something else ("My exam is on 8 December"), or the agent's reply to the edit kept,
  the restored claim folded into its closed twin and, where the pair rule had made the correction, the edited day
  stayed current alone — worse than before the pair rule, which left both open. A test of "this edit" instead (the
  changed lines say the restored day and not the edited one, and the text taken out said the edited one) was broken by
  the sixth review: an unrelated line about the 8th replaced by "She first planned 5 December" closed the current
  claim in its own slot with no reading, and "5 December, not 8 December" was still refused. A day's words cannot be
  tied to one relationship, so no test of the words tells a mention from an undo. What stands: **in the open claim's
  own slot** (it would give way at once, with no reading) the strict test, whose refusal leaves what happened before
  this rule; **under another wording, where the pair rule itself closed the twin**, the restatement is born whenever
  the changed lines say its day and the same re-read does not state the open claim too (then the conversation says
  both and nothing was undone), and nothing is closed except by the pair rule's own test and two readings — both open
  is what there was before the pair rule, never the edited day alone. So a true undo beside another mention of the
  edited day ends with both days open under another wording, and on the edited day in the same slot (as before this
  rule); "8 December (she first planned 5 December)" read as both days changes nothing. (b) *A claim that has since won against another is not this
  conversation's to replace.* The person picks the claim that took the correction's place over another conversation's
  claim in the inbox; the pick leaves no word of theirs on the winner (only its confidence), so the edited-back rule
  and the pair rule read it as this conversation's alone and replaced it on a later edit. Every close writes
  `supersedes` on the claim that won, and only a revision's close carries the mark, so
  `revision_pairs.won_elsewhere(claim, conversation, page)` is: its `supersedes` names a claim of the page whose close
  this conversation's revision did not make. Such a claim is never offered as a pair (no reading is spent), never
  replaced by `apply`, and never gives way to an edit back (in its own slot the restatement folds as before; reworded,
  it is born beside it and both stay open). The same-slot rule (`redated`) is unchanged and can still replace such a
  claim, as before this change. **F3 closed (2026-11-26): only a close the revision rules made is ever undone.** The fourth review found that
  the person's pick in the inbox (`inbox_service`'s conflict answer closes the loser as `superseded_by` the winner),
  Sleep's own settle through the same resolvers, or an agent's, between two claims resting on this one conversation,
  read exactly like the conversation's own correction (the fields coincide), so a later edit restoring the other day
  undid it. Now the revision rules mark their own closes (`closed_by_revision: <the conversation>`, written last by
  `_close_by_revision` for the same-slot, removed-text and pair rules, and by `settle`'s withdrawal; dropped by any
  later write to the close, `storage.md`), and `_edited_back` requires that mark naming this conversation on the closed
  twin, on every closed link up to the open claim, and on every earlier link that names it back; one unmarked close
  anywhere and the restatement folds into its twin, as before the rule. A bank written before the mark has none, so it
  is never edited back (`origin/dev`'s end). `inbox_service` is unchanged; its close goes through `_close`, which
  drops a mark. `test_a_pick_the_person_made_in_the_inbox_is_never_undone_by_an_edit_back` drives the real resolver.
  Recorded, not changed: the same-slot rule (`redated`, as before this change) replaces a claim the person picked as
  the *winner* when the same conversation is edited to a third day under the same wording; the pair rule and the
  edited-back rule do not (`won_elsewhere`, above). Nothing is reopened in place: history reads A, then B, then A again, a chain with no loop
  (`supersedes` points back at each step), the closed claims untouched. The departure rule (`_departed_on`) does not
  read this conversation's own chain as a departure. The close is recorded where the correction's was (audit
  `revised`, `why: edited_back`, in the ledger and the Corrections record). A close by another conversation, the
  person, an agent, an ending or decay is never undone, and a re-read that is not such a revision undoes nothing.
  **Measured (2026-11-25, plan, Sonnet main, Haiku judge, `--clock 2026-11-25`).** The 17 stories, 4 runs: a corrected
  date wrong in 9 of 28 (before, 10 runs on the code without either rule: 29 of 70); a corrected name 8 of 8 (18 of 20);
  a removed sentence 0 of 8 (2 of 20); the other three shapes 0 of 24 (0 of 60). The date gain is inside the spread:
  of the 29 before, 1 had its stale claim on a page other than the owner's, the shape the pair rule reads; 24 were
  claims held under a name with no page yet, which neither rule touches, and the rest were the owner's own claims about
  helping with the move, which the re-read does not restate. The pair reading fired 3 times in 4 runs (one pair, two
  calls, "same" twice, replaced each time). The ten review stories, 2 runs: 14 of 14 right on the seven shapes the run's
  day does not touch; `date_words` and `date_language` read "never made" because their text writes an absolute date the
  expectation dates from the run's day (rescored at the day they were written for, no model: 4 of 4 right); `undone`: both days current in both runs — its person had no page, the claims were held. Four
  invented edited-back stories whose person has a page (A, B, A twice; A, B, A, B; A, B, C), 1 run: 4 of 4 right; the
  rule fired 6 times (3 relationships, 3 dated values), the pair reading 4 times. The benchmark's edited conversation
  (`U4`, 3 legs each, the same day): right in 1 of 3 before and 1 of 3 after; its person's page is made the night the
  edit is read, so the old claim is a held claim released onto the page in the same pass and neither rule meets it;
  every other measure within the spread (span rate 1.0). Left then: the held claim (and one released in the same pass)
  whose relationship the re-read words under another predicate — the shape of the benchmark's `U4`, of 7 of 9 story
  failures and of `undone`.
  **The pair rule reaches a claim wherever it waits (2026-11-26).** `candidates` also reads the claims held under a name
  with no page yet (`revision_pairs._held_pool`: as the store holds them before the pass; a held claim whose id its page
  already holds is offered once, as the page's), under the same conditions and the same two readings; the verdict
  remembers the line it waited on and the old claim as it was judged (subject, object, start, end). Where the old claim
  is when the replacement is applied decides how: (1) *on a page* — `apply`, as above; (2) *released onto its page in
  this same pass* (the name got its page tonight, the benchmark's `U4` shape) — `apply` closes the very claim object the
  pass released from that line (`revision_pairs.Moved`, built in `claim_pipeline` from the claims `_releases` offered;
  matched by identity, never a look-alike the page already held), its subject and object re-keyed as the release
  re-keyed them (`pending_store.repointed`), exactly as a page claim is closed; (3) *still held* once the store has
  settled (release, then hold) — `apply_held` takes it off that ONE line (`pending_store.replace_held`, under the
  store's lock) only when the re-read's claim is held in the same line in its place: open, superseding nothing, the same
  subject, predicate wording, object, context and speaker, the judged day, citing this conversation, one new claim for
  one old; and only when the old claim is still what was judged and still this conversation's alone, read after this
  pass's hold merged any other conversation that also says it. Nothing in a held claim is cleared or re-dated; the line
  keeps no closed claims, so the old one leaves whole, as the same-slot rule's held claims do (`_move_held`); its record
  is the ledger's `revised` row with `held` (and `why: edited_same_relationship`) and the batch's Corrections record,
  neither of which a promotion deletes. A second run over the same state changes nothing, held, released or promoted
  in between. An edit undone while the name has no page needs no rule of its own: the old claim left the line whole,
  so the restored wording is a new claim that meets the correction by this rule or the same-slot one.
  **Measured (2026-11-26, plan, Sonnet main, Haiku judge, `--clock 2026-11-26`).** The 17 stories, 4 runs: a corrected
  date wrong in 5 of 28 (9 of 28 on the branch before this step, 29 of 70 on the code without either rule); a
  corrected name 7 of 8; a removed sentence 2 of 8 (the same story, a value on another page, in two runs in which the
  pair rule read nothing or something else; 2 of 20 before); the other three shapes 0 of 24. All 5 remaining date
  failures are held claims the rule's own conditions leave alone: a value dated from the old day (values are never
  paired), the re-read naming the object another way (a factory's name translated: another object), a re-read that
  wrote the day only as a value, and a relationship to another person dated from the move line. The pair reading fired
  in 3 of 4 runs, 6 pairs, 12 calls, "same" at both readings each time, 6 replaced (1 on a page or released, 5 held), no
  story made wrong. The ten review stories, 2 runs: 20 of 20 right, `undone` included (both runs; no pair reading fired,
  the re-read kept its wording and the same-slot rule acted). The benchmark's edited conversation (`U4`, 3 legs each,
  the same day): before (`origin/dev`) both days current / right / right; after right / right / old day only (that
  leg's re-read wrote no claim of the new day at all, so nothing could take the old one's place); no pair reading in
  any leg (the re-read kept the first wording twice, the same-slot rule replaced it); every other measure within the
  spread (span rate 0.99 to 1.0, others' words 7 of 7, pages right 9 of 9 after).
  **Measured with the mark (2026-11-26, F3 closed; plan, Sonnet main, Haiku judge, `--clock 2026-11-26`).** The mark
  only narrows the edited-back rule, which no two-night story reaches, so the stories should not move, and did not past
  the spread. The 17 stories, 3 runs: a corrected date wrong in 3 of 21 (5 of 28 before this step, 29 of 70 on the code
  without either rule), all three held claims out of the rule's reach as written above: the object named another way (a
  factory's name translated), the new day written only on another name (the move as a page of its own), and the new day
  written only as a value; a corrected name 4 of 6 (7 of 8); a removed sentence 2 of 6 (the same value story); the
  other three shapes 0 of 18. The pair reading fired in 3 of 3 runs, 8 pairs, 14 calls, "same" at both readings each
  time, 8 replaced (1 on a page, 7 held), no story made wrong. The ten review stories, 1 run: 10 of 10 right, `undone`
  included. The four edited-back stories, 1 run: 3 of 4 right (4 of 4 before); the fourth's last re-read wrote the
  restored day only as a value under a new name and no relationship at all, so there was nothing to bring back. Every
  close in the other three chains carries the mark, and the rule fired 5 times (2 relationships, 3 dated values; 6
  before, the difference being one chain the pair rule settled instead because the re-read reworded it).
  **After the fifth review's fixes (2026-11-26, plan, 1 run each; the sixth review's change touches only the
  edited-back rule's text test, covered by its engine-free tests and the three reviews' scripts).** The 17 stories: a
  corrected date wrong in 2 of 7 (the new day written only as a value; the object named another way), 3 pairs read,
  3 replaced; the four edited-back stories: 4 of 4. Over every run since the rule reached held claims: a corrected
  date wrong in 10 of 56, against 29 of 70 without either rule. **On the key (the same day, 3 runs of the whole
  benchmark, Sonnet main, Haiku judge, $2.34):** nothing worse — updates 13 / 14 / 13 of 14 (one value restated in
  another language left both current, as in 31 of 175 stored runs before this change; one old value stale, also seen
  before), the edited conversation `U4` right in 3 of 3, every other measure at its ceiling or inside the stored
  spread, 0 integrity breaks, $0.78 a run. The pair reading ran 0 times in those three runs (the re-read kept the
  first wording, where the same-slot rule acts), so **the benchmark shows no gain from this change, only no loss**:
  the gain is what the two-night stories measure.
  The stories and their runner are in the repo: `revision_e2e_stories.json` (17 shapes) and
  `revision_e2e_review_stories.json` (the ten shapes the reviews attacked). Also found and left: a held claim dropped
  because its span went leaves no record of why (`pending_store.drop_held`), and a held name whose spelling is corrected
  loses a claim from an unchanged line.

**A page's prose follows the revision (G104 slice 2, owner 2026-11-03: "Sleep regenerates a page's prose from its
corrected claims when a revision closes one, limited to the pages a revision touched").** Measured before (the same
four notes plus a fifth whose city changes and a person's pinned fix on it; Claude plan at haiku): after the second
Sleep, Key Facts said Friday twice beside Thursday twice, "targets Linux only" twice, Lisbon twice beside Porto twice
— the claims were closed, the prose was not. Stage 5.58 (`revision_prose`, after the claim pipeline, before the hubs):
- **What changed** (`changes_of`): each replaced or removed block of the line diff that took a word away — the tokens
  of its old lines the new body no longer has anywhere (`gone`), and those its replacement brings (`fresh`). An
  addition, a reworded line saying the same things, whitespace, and a capped transcript's slide are no change: a no-op
  revision costs nothing.
- **Which pages:** one where this batch's revision closed or withdrew a claim (`run_claim_pipeline`'s
  `revision_closed`), or one with a passage written from the version Sleep read (a `section_provenance` row into the
  revised episode at its old hash) that says a gone word. The second rung exists because the claim layer is the
  extractor's choice: #581's haiku run held the meeting as a node, never as a day, yet its Key Fact said Friday.
- **Which passages — provenance only** (review of #589): in Summary, Article, Key Facts and Open Questions, a passage
  saying a gone word is offered only when its rows name the revised episode (on a version before this one) and no other
  source it cites still says that word — a passage resting also on another conversation that says it is that
  conversation's word too, never settled by this edit (#581's settle rule). **A passage with no rows is never
  rewritten**: legacy prose, the person's typed or edited line (an edit drops its rows), a line a page merge carried
  (where `git blame` names the merge, not the person) — protection by default. **Rows are never handed to a line that
  had none** (`section_provenance.refresh`, review of #589 B3): a Sleep write that meets a conversation saying the same
  words — exactly, or as a shorter fact the line extends — leaves the line rowless, so a merged-in or typed line never
  becomes rewritable by being repeated. Only a line a write adds, or one that already had rows, is recorded. Beside the
  offered ones, the passages
  this batch wrote from the revision's fresh words (rows at the new hash), so the writer keeps the current fact once.
  **History is never rewritten.**
- **Held, never rewritten:** a passage in a Summary or Article someone rewrote (`has_human_prose`), one carrying a
  pinned fix (G198 `corrections`) about the changed words, or one with a line `git blame` puts on a page-edit commit
  (any door). Its proposed rewrite becomes ONE `page_edit` inbox item per page (`origin: revision`, Cicada's own;
  never a second while one waits), applied or left with one tap. A passage with no rows that says a removed word is
  held the same way — nothing proves Sleep wrote it — so it reaches the person only as this question. If git cannot
  answer the blame, the page's
  passages are all held. A word-level pinned fix elsewhere is applied again over what is written (`apply_corrections`).
- **One call per touched page at most** (stage `merge`, the cycle's engine and consolidation model, ≤
  `agent_max_concurrency` at once, ≤ 40 pages and 40 passages), inside Sleep's write window, committed with the batch
  under Sleep's trailers. The answer: passages rewritten or emptied (removed), and a History sentence per change.
  **Rails in code:** a rewrite keeps no gone word its passage had, adds no capitalised word, number or `[[link]]` that
  neither the passage nor the change gives, holds no heading, fence or relative time word, and never empties the lead;
  a rewrite that now repeats another passage of its section word for word is removed; a removal that would take the
  last passage carrying a fresh word is undone. A History line must name what was there before; one that does not
  gives way to Cicada's plain line ("An edited conversation changed “…” to “…”"). It is dated the day the conversation
  was edited (the stager's `revised.at`, local), merged by date. A change History already records — a line with the
  old and new words that does not call them a conflict, or for a removal one that says the words went — gets no line.
  A failed call or a refused answer leaves the page as it was.
- **No conflict question when the source corrected itself** (`conflict_resolver._answered_by_revision`, review of
  #589): the contradiction check is still asked; a contradiction it finds is not filed only when its old side is words
  a revision of one of the update's own conversations took away, and nothing else the page rests on says them — no
  other conversation in its `source_episodes` (their text), no open claim in the person's own words or citing another
  conversation, no pinned fix, no hand-written lead or article. Anything unreadable counts as saying them. (Two
  2026-11-04 runs asked "Lisbon or Porto?" and "Friday or Thursday?" of a note that had answered it; a page saying
  "lives in Berlin" from another conversation is still asked about.)
- **Provenance moves** (`section_provenance.remap`, `episode_revision.provenance_row`): on every page citing a revised
  episode, a span row is located again on the new body (never fuzzily) and a whole-conversation row takes the new hash,
  except on a passage still saying a gone word (it rests on the old version). A rewritten passage keeps its rows into
  other conversations plus the revision. **Held spans move too** (`pending_store.reanchor_held`, before any release):
  only a held dict's `evidence` is replaced.
- **Measured after** (the same notes plus the pinned case, run on the provenance-only rule): every passage whose rows
  prove it came from the edited lines was corrected (Friday, Linux and the unpinned Lisbon fact removed); the pinned
  Key Fact kept and asked about; History gained the three changes, dated; one prose call, 2,086 input / 1,215 output
  tokens; no conflict question. Two Key Facts Sleep had cut off a summary with no rows still said Friday and Linux —
  closed by the next bullet: rerun, nothing outside History says Friday, Linux or Lisbon but the pinned fact (kept,
  asked once), with 22 of 23 Key Facts carrying rows before the edits. Case by case on the G104 row. `test_revision_prose.py` pins the cases end to end through `sleep_cycle.run` on the engine seam,
  plus a pinned fix, a blame-only edit, a merge-carried edit, a passage citing a second conversation and one with no rows.
- **A Key Fact cut off a summary keeps that summary's rows (2026-11-04).** Two places cut a summary into Key Facts and
  used to drop its provenance, so the provenance-only rule could never correct them: Stage 2's merge of two extractions
  of one page (the shorter summary loses; its sentences become facts — `entity_resolver._merge_entity_payload`, now
  `section_provenance.merge_selected(split=True)`), and Stage 5's bounded Summary (`bound_summary` →
  `retain_orientation`, `merge_sections_fallback`'s displaced sentences — `conflict_resolver._split_fact_inputs`). A fact
  that is a contiguous part of an input summary or description, or of the page's old Summary, carries that text's rows
  (its conversation and body hash), through the same `section_provenance.refresh` writer. Only a fact new in that write:
  a Key Fact already on a page keeps what it had — **facts written before this change have no rows and stay untouched
  by the revision pass**, as does a fact cut off a summary a model rewrote (its words are no input's).
- **Left:** two passages the same batch's merge wrote that say the current value in different words are not always
  folded into one.

**A correction reaches everything it touched (G104 slice 3, owner 2026-11-23: "if it consolidated a mangled
transcription, and then we update it, the info that that file affected, can be detected and patched in a way so as not
to cascade, but being aware tho. This is smth that should extend to all sources"; TODO ruling 75; plan
`docs/plans/2026-11-23-g104-corrections-propagate.md`).**
- **One meeting, one episode** (`meeting_transcripts.file_key` / `winner`, `folder_source._meeting`): in a `meetings`
  folder, files whose names carry the same date **and** time are one meeting (a date alone never joins). The episode
  holds the greatest `(mtime, relpath)`; a newer file takes it over in place (`EpisodeDraft.replaces`, same id, a
  `revised` record, `previous_source_ids` kept) and the file it held is recorded in `replaced_files` (capped at 20), never
  read as its own conversation; a replaced `(relpath, sha)` never wins again while the held file stands, so a rescan
  after a lost manifest cannot flip it back. Deleting the held file stamps `held_gone_at` and the sync answer asks the app
  for the next newest (`FolderSyncResponse.resend`; the app drops it from its manifest and posts it, or reports it
  deleted); until it arrives the episode keeps its words. Every file gone: tombstoned as before. Two live episodes that
  already share a stamp are never guessed between.
- **An edit to a file that still exists is a revision**, a split note's sections too: a renamed H2 is matched to its
  episode by `section.index` (exactly one vanished and one appeared at that position), a removed section or a file that
  crossed `SPLIT_CHARS` revises the lost section to an empty body (`episode_revision.attach` builds a revision for an
  emptied episode), never a tombstone.
- **A source deleted outright keeps what it taught, marked** (ruling 75 b): its claims stay open and counted; every door
  that draws their evidence carries `sourceRemoved: true` beside the span's `status` (`source_spans.Source.removed`,
  provenance, page citations, recall detail, `cicada_sources`), derived on read, nothing written.
- **The cascade** (`revision_cascade`, Stage 5.575, once per batch after the revision claims settle and before 5.58):
  a page whose name was in the version Sleep read and is gone from the revision, and that nothing else supports
  (`support_of`: another conversation — waiting ones included, found by the lexical index — an open claim the revision
  did not close, a person's or agent's commit by `Cicada-Author`, a pinned edit or alias, a project, a Contacts card, a
  source the person added, an import), is archived (`archived_by: revision`, the episode recorded), its open questions
  settled by `inbox_tend`'s engine-free `source_corrected` rule; `POST /entities/{id}/restore-correction` puts it back,
  committed as the person, so it is never archived again by this rule; a later real mention revives it too. A kept page
  is listed with the support that kept it. An alias said only in the removed text, on no owner, project or media page,
  is dropped (never added to the person's removed aliases). A held name (`pending_store`) loses the revised conversation
  from `heard_in` and every held claim only the removed text said (`drop_held`) before release, so a page born in the
  revising drain never carries the old value; the same goes for the held line's first-read prose (summary, key facts,
  history) that says a removed word (`pending_store.drop_prose`). A page that lost a claim but whose name the revised
  conversation still says is kept (`still_named`). **A claim whose date came from a corrected line** (its span on an
  unchanged line, its start or end said by the changed lines — `episode_revision.says_day`, ISO or a day near its month,
  six languages, no model): the revision's re-read item is kept by `keep_changed` and supersedes the old-dated claim in
  Stage 3 (`redated`, no question); a held old-dated claim is dropped before release. A relative date moves nothing.
  **A revision is the same conversation's people and things:** before `keep_changed`, a re-read name whose bare form
  (`entity_resolver._bare` — a trailing note in brackets stripped — then case, accents and spacing folded) equals
  exactly one name or alias of an entity the first read of that conversation made (a page citing it in
  `source_episodes`, a held line heard in it) is rewritten to that entity's name (`episode_revision.canonical_names`);
  none or several, nothing is rewritten.
  **Removed words** (`revision_prose.tokens`) count any word with a digit, but a numeral counts as removed only when a
  number replaced it ("5 December" → "12 December"), never a timestamp or list number on a removed line.
  **Nothing cascades past independent support.**
- **Told, not asked** (ruling 75 f): each run's detail carries a `corrections` object (null when nothing was revised):
  conversations revised, claims withdrawn / superseded, passages rewritten, pages archived (openable, with Restore),
  aliases dropped, held claims dropped, questions withdrawn, pages kept and why — ids, enums and counts only; every
  touched page gains one dated History line naming the corrected conversation; the Sleep commit body lists the revised
  and archived ids.
- **Left:** a later conversation resolved to an archived page is independent support, so it is never second-guessed;
  events (`happened`/`milestone`) stay `progress.py`'s; the live bank's one pre-existing duplicate meeting is not
  repaired.

**An agent's edit of a source is a contribution (G244, owner 2026-11-23: "if you come and change something in the
transcript for example … that 'contribution' should be documented, with your model, harness, etc. even if it is the raw
file directly"; TODO ruling 76; plan `docs/plans/2026-11-23-agent-source-edits.md`).** An agent that edits a raw file in a
watched folder was invisible: the app posts the new bytes, the folder stager records a revision, and the corrected words
read as the recorder's. Now the edit is recorded by a hook, never by the agent's memory (G105's rule):
- **The door.** Claude Code's `PostToolUse` on `Edit|Write|MultiEdit|NotebookEdit` runs `cicada-hook source-edit`
  (`api/hooks/source_edit.py`, stdlib, run by path). It matches the edited file against `GET /sources/folders` (cached in
  `$CICADA_HOME/state/source-edit-folders.json` for 60 s, so an edit outside every folder costs no request and no log
  line), requires a regular file under a folder's resolved root (a symlink is never followed; the longest root wins; a
  file the folder's globs exclude or past the app's 2 MB sync cap posts nothing), hashes its bytes (sha256, the app's
  `FolderScanner.sha256`) and posts `{folder_id, relpath, sha256, harness, session_id, transcript_path?, tool, at}` to
  `POST /capture/source-edit`. The backend never opens the path and the post carries no word of the file. The log line is
  an outcome and a count (`attached: 1 episode`), never a path. A shell command's edit is not seen by a hook: the agent
  declares it with `cicada source-edit <file>` (the CLI names the calling session). Never a heuristic over mtimes: a wrong
  attribution is worse than none.
- **Matched by content, either order** (`source_edits`): the record waits outside every bank and git keyed by
  `(folder_id, relpath, sha256)` for 7 days; the stager attaches it to the episode(s) it writes for that file's bytes, or,
  when the sync landed first, it attaches at once to the episodes whose `content_sha` and folder match and whose version
  was staged around the edit's time (2 minutes before to 15 after; a no-op write or a declared edit of bytes staged long
  ago attaches nothing) — one commit, the agent as `Cicada-Author`, its session as `Cicada-Session`. A split note's
  contribution lands on each section whose body changed. A body with no earlier version is wholly the agent's only when
  its tool wrote the whole file (`Write`); an `Edit` of a file Cicada had not seen yet names the editor and claims no
  span. A run names an editor only for the body it read (the contribution's `content_hash` is the episode's). The episode keeps `contributions: [{harness, model, effort, session, at, content_hash, ranges}]` (`storage.md`).
- **Said where the words are drawn.** A span that overlaps a contribution's `ranges` while the body is still the one it
  edited is `correctedBy {harness, model?, at}`; the app notes it beside the citation, "Corrected by <harness> · <model>",
  and the Corrections section of a run says "Edited by <harness>". The line stays its speaker's words: trust, evidence
  kind and speaker are unchanged, and the agent is named, never trusted more or less.
- **Left:** Cursor (`afterFileEdit`), Codex and Gemini hooks post the same record (G244 follow-ups); an agent's direct
  edit of the bank itself is already forbidden by the contract and is not detected here; a folder added in the last
  minute is seen after the hook's cache expires.

**A title is never joined on the name alone when it could be two things (G227, 2026-10-29).** Stage 2's exact-title
join used to take whichever page held the name (one per title in `existing_by_name`, last writer wins), whatever its
kind: a program said where only an IDE had the name landed on the IDE's page. Now an exact title joins only the one page
of the mention's kind (`_same_title_pick`; a `concept` mention, Stage 1's word for what it could not place, the one page
that is not a saved link). Two pages of that kind, or none, go to the same-title judge (`_same_title_match`): each page
sharing the title weighed with the types allowed to differ (`_SAME_TITLE_NOTE`, the type guideline swapped for "let the
descriptions decide"). `same` joins; `unsure` holds the name and asks — the item points at the page by id
(`merge_target_hint`), keeps every page sharing the title (`same_title`), and asks about that ONE page, the one its
same/different answers act on ("Is this the <name-a> IDE?", the others counted in the reason, `inbox_wording`; the
stored title says the same); `different` on all goes on by the usual rule, and a new page whose id the title already
holds is held and asked, as before. A person mention keeps its own rules (G209; two people sharing a bare first name: `same_name_people`, below). See the G227 row
for the haiku replay.

**Two people with one first name: told apart when the record can, held in doubt when it cannot, split by a later fact
(2026-11-23, `same_name_people`, `same_name_review`, `same_name_tend`, `same_name_doubts`).** Most people in a memory are named by
a first name alone, and first names repeat (a brother-in-law and a colleague, both "Marc"). Stage 2 keyed every mention by its
lowercased name, so inside one batch a name could only be one thing, and across batches a mention joined the page titled so
on the name alone: one page said the brother-in-law was moving to the Berlin office. The owner's words: Cicada's appeal rests
on "detecting when we are talking about different or same people, and to surface when its not sure, but really surface it when
it saw everything it could and there is no context that can correctly clarify … these splits can happen as a new fact comes in
and clarifies." Four rules follow, each in code: a missed split is not a fallback; **doubt is a state the record holds**, never
resolved by choosing "same"; **a question is the last resort**, asked only after everything on record was read; a decision is
**not final**, a later fact can split what was joined and settle what was in doubt.

*The states a mention can be in.* **Joined** (the plain person, or a known page) → **apart** (a located contrast: a person
of its own, `<slug>-2`, the same clean title, G227's `_another_id`, the pair in `_merge_rejected.yaml`'s `split:` list, for
good) or **in doubt** (a person of its own too, but the pair is in `_same_name_doubts.yaml` and never in `split:`). A doubt
becomes **apart** on a located contrast, **joined** by Sleep on a located link two reads agree on (ruling 74a), and otherwise
**waits**; it is **asked** about once only when it reads like one person or like nothing either way. Which facts are
whose while a mention is in doubt: its conversation's beliefs, edges and values are pinned to its own person (a held line, or
a page once it meets the promotion bar), exactly as a split's are; the plain page never receives them, so an agent reading
`marc` is told nothing about the other Marc, and recall, Ask and the page list the two as same-titled pages told apart by
their derived qualifiers ("Marc (cousin)", "Marc (neighbour)", `same_name`).

*Per batch, in Stage 2 (`_plan_same_name_people`, one call a bare name, as before).* The judge (Stage 2's disambiguation
model, at most 20 names a batch, 10 new conversations and 20 lettered descriptions a call) is shown **every conversation on
its own**: this batch's, and what each person already on record says **conversation by conversation** (a page's beliefs and
Key Facts each carry the conversation they came from; `same_name_tend.page_conversations`), newest first, in turn between the
people. A page is no longer one blended summary, which after a wrong join is a mixture of two people. It groups the
descriptions and says how any two groups stand: *different* (two facts that cannot both be true of one person at the same
time, **dates decide**, a life that moves on is one person: the 2026-11-23 false-split rules, unchanged), *cannot_tell* (two
different kinds of person, a relative and a colleague, a child and an adult, with nothing that connects them: it copies the
two facts that make them look like two), or no entry (the same person; a thin description, a different setting, topic or time).
**Every verdict is located in code** (`same_name_people.read`, `quotes_located`): each quoted fact must occur word for word in
its own group's descriptions **and in none of the other's** (a page read conversation by conversation lists a belief two
conversations share under both, so a quote found on both sides is routine and sets nothing against anything), the two must
not be the same words, and each must say more than the name; else the groups are one person (the old behaviour, never a
guess). A verdict joining two groups through a third is incoherent and splits nothing. A new conversation goes where its group's filed conversations are; a group nobody
on record is in is a new person, apart on a contrast and in doubt on a tension; each side of a new person needs 15 words of
description (a thin one is the plain person's, as before). **A second reading** (`plan(..., strong)`, the engine's main model,
`same_name_tend.main_tier`): when the small judge calls two or more of this batch's conversations one person (where a silent
join hides: it reads the speaker being named in both descriptions, or "a later move", as a link), or divides them against a
person on record with three or more filed conversations, the same prompt is put to the main model once and its grouping replaces
the small judge's when it divides them; its answer failing, unreadable or calling it one person leaves the small judge's
reading, so a located split is never lost to it. A single new conversation against a person on record is not read again.
**On a plan the judge is told no answer shape (2026-11-24).** A call's `stage` label picks three things: the model tier
(`model_for_stage`: "disambiguation" is the small one on every engine), the plan guard and the metering. It no longer picks the
answer shape an engine forces. Until now the Claude plan (`agent_engine`) and the ChatGPT plan (`codex_engine`) forced the pair
judge's schema (`decision` / `decisions`) on every call labelled "disambiguation", and the same-name judge, which shares that
label for its small model, was forced into it: its answer (`people` / `pairs`, a verdict, a list of lines) came back as
`{"decision": "same", "reason": "<the real answer as a string>"}`, which `same_name_people.read`, `settle_pair` and `holds_two`
could not read, so on a plan, the default, two people of one first name were placed as one person (measured: a story's aunt and
climbing partner on one page in the one real Sleep run before the fix) and no doubt was held, joined or asked. The benchmark had
only run on a key, where no schema is forced. Now a schema is forced only on a call that **states** a shape
(`resolve_llm_fn(..., shape=)`, `engine_schemas.SHAPES`: `pair` by the two pair-judge calls in `entity_resolver`, `extraction`
and `quick_read` by Stage 1's call, which keep their behaviour: Claude's behind its flag, Codex's strict one for `extraction`
only); every other call, the same-name judge included, is told only to answer JSON, as on a key, and a misspelt shape raises where
it is written. The Cursor, OpenCode and Grok engines never forced a shape (their stage label only picks the model). **An
answer that does not have the shape asked for is never a verdict** and is counted: `Plan.unreadable` (the Stage 2 log line
"N same-name answer(s) were not in the shape asked for and were skipped", a count, no name), the tail's `unreadable` skip
(`Report.skipped`, apart from `not_read` which is a real answer that stood on nothing), and a log line for a split's leftover prose.
The name is placed as if no judge had answered, as it is for a failed call. `api/tests/test_answer_shape.py` has the table: every
`resolve_llm_fn` call in the services forces no schema unless it is one of the listed callers that state their shape. **A doubt the small judge could not quote a contrast for is read once by the main model (2026-11-24, `same_name_people.lone_doubt`).** With the plan call made as a key's is (same prompt, JSON only, no forced shape), the small judge still divided one real person in 12 of 92 battery replays (13%; a partner who took a job in another city): every pair of its people stood on `cannot_tell` with quotes located and no contrast. No difference in the call was found to account for it: varying one thing at a time on the failing cases (no `--effort`, `--effort high`, no context guard, no JSON-only suffix, the main model as the judge) gave 0 of 8 each against 1 of 8 for the unchanged call, and the unchanged call itself measured 8, 3 and 0 of 36 in three runs within the hour, so the rate is the small model's sampling on borderline descriptions, not the plan's call (a key's call draws it too; whether it does at that rate is for a key run to say). The fix is a read, not a call shape: when the small judge's whole answer is located doubts and nothing else (`lone_doubt`: no `different`, no unlocated verdict, no two descriptions of one conversation), the main model reads the same prompt once, and **only a reading that finds one person lifts the doubt**; one that divides, fails or is unreadable leaves the small judge's doubt as it was, never deeper. It costs nothing when the small judge says one person or quotes a contrast, and one main-model call when it doubts (17 of 29 two-person replays and 16 of 92 one-person replays made a main-model call, for any of the rules that ask for one). Measured on the plan: one person cut in two 0 of 128 replays (0 of 92 on the 46 one-person cases, 0 of 36 on the nine that had failed; the doubt rule fired 5 times in those 36), two people kept apart 29 of 29, and the three-name Sleep story right in 2 of 2 real Sleeps. `plan`
**never changes a page that exists**. When its re-read shows
that a page's own conversations fall in two groups (`page-holds-two-people`), or that two people held in doubt fall in one
(`doubt-may-be-one`; **also when the whole name reads as one person**, which is the usual way a doubt ends, 2026-11-24:
before that a reading with one group returned before anything was flagged, so the pair was never looked at again), or
that a doubt still stands, it only **flags** the name (`same_name_doubts.flag`, a deferred Stage 2
write like the split pairs, committed with the batch).

*After the drain, in the engine-independent tail (`sleep_cycle._same_name_review_safely`, before the catch-up proposers and
any poll's `git add -A`).* Only what Stage 2 flagged, never a sweep of the pages, and nothing flagged means no engine and no
commit. The engine's **main** model (`same_name_tend.main_tier`: the same engine, its main model, never another bill; a
scheduled run on a plan only through ruling 4b's switch; a plan limit is a pause and the flags stay) reads the whole record
of the people involved (`same_name_review`): `holds_two` reads one page's conversations together and splits it only on a
located contrast; `settle_pair` reads two people held in doubt and answers *different* only on a located contrast, *same*
only with a located link (a fact each side states that is the same fact, or one continues the other), else *cannot tell*. **A split** moves the leaving conversations to a new page
through `page_join.split` (the page's beliefs whose every source is a leaving conversation, the Key Facts whose provenance
(`section_provenance`) names only them, the conversations; what a staying conversation also supports stays; a belief with no provenance is never moved; a sourced line shorter than
`same_name_split.MIN_CHARS` ("Dani is retired", which a sentence number cannot carry) moves as an exact cut, `same_name_tend.short_leaving`;
**what the old page says with no source of its own** (its Summary, History, Related and Open Questions lines, its tags: written
when the page was a blend of two people) is read once by the same main model before the split (`same_name_leftovers.plan`,
outside the write window, an engine failure leaves the flag) and the stretches that state the leaving person move with it
(2026-11-24): a line moves only when the words the judge copies from a leaving conversation's description are there word for word
and in none of the staying ones **and the line's own words share a stretch of a leaving description** (at least 12 letters beyond the name, whole
words, exact; no stretch that size with a staying description, so a name both carry is no tie; a tag is tied by the record alone) — a wrong or
off-by-one number never moves the staying person's sentence, and the judge's proof is the gate, never the tie (`_tied`; a paraphrase shares no stretch, so it stays, the safe side).
A mixed sentence gives up only the clause it names (copied exactly, once in the sentence, between clause edges: `;` `,` `:` `.`
with a space after, or a dash with a space on both sides, never the hyphen of a word, a comma in a number, nor inside a `[...]`,
`(...)` or link: `page_join.cut_edges_clean`). A cut carries the sentence the judge saw and its offset in it and is applied at
exactly that place, re-validated inside the lock against the page as it is then (`same_name_leftovers.still_placeable`: still an
unsourced line, nobody wrote or pinned it since, the sentence once in its section; a short sourced cut is a whole line once in its
section), else not applied. A History bullet moves whole or stays, never cut inside (History is never rewritten). A
line a page edit wrote (git blame, `revision_prose._hand_lines`), a pinned fix, a Summary the person wrote, or anything the
judge cannot locate stays. The cuts are `page_join.split(cuts=...)`, so they ride in the split's own commit and the person's undo
takes them back byte for byte; `related` entries that only what moved points at go with it (`related_follows`); the new page
reads in the writer's own order with its lists as bullets): **one commit** authored `cicada`,
trigger `sleep/same-name`, undone with `page_join.undo`, the pair recorded as split for good. **The person's word stands
over a split.** That commit holds the split and nothing else; what Sleep remembers about having made it
(`same_name_doubts.splits`) is written after it, so an undo reverses the split alone, the next look finds the commit taken
back, and the page is marked as one Sleep never splits (`same_name_doubts.one`). A person page another was folded into on
the person's word (their merge, an agent's on their ask, an answered question: `entity_merge.merge_entities`, every caller
but the dedup sweep, which passes `by_sleep`) carries the same mark, written in the merge's own commit and named in
`merge_footprint`, so a pair they joined is never cut again. **Sleep joins two people it held in doubt when a later
conversation links them (ruling 74a, owner 2026-11-23: "manual joins shouldnt be the priority. cicada itself should do it
automatically").** `settle_pair` must find a located link (one fact each side states, each quote in its own side's
descriptions and more than the name), and because a wrong join is the costly mistake the whole record is **read a second
time**: only two reads that both find a link join the pair, through `page_join.merge` (`by_sleep`: Sleep's own join does
not mark the page as one Sleep never splits, so a later located contrast can still part it), one commit authored `cicada`,
trigger `sleep/same-name`, undone with `page_join.undo`. The doubt leaves the store in the store's own commit first and
what Sleep remembers of the join (`same_name_doubts.joined`) is written after, so the join's commit holds the join alone.
**An undo is the person saying they are two:** `same_name_tend.reconcile` (no engine; it runs in the tail whenever Sleep
has a join or split of its own on record, flagged or not, one `git log` for all of them) finds the commit taken back and
records the pair in `split:` for good, never joined or asked about again; meanwhile `kept_apart` already covers it
(`same_name_doubts.kept`). A page in two doubt pairs is never joined by Sleep, and when only one read finds the link it
is said in the question ("Both seem to be said of one person: …"). **An undo is never refused because of the store:**
`page_join.undo` takes `_same_name_doubts.yaml` back by meaning (`same_name_doubts.reverse`: what the undone commit added
leaves, what it removed returns, everything written since stays). Before this the file's few adjacent lines made the
line-based reverse refuse the person's undo of their own merge of two people once Sleep had rewritten it (a fault of the
first version of this section, on `dev` for a few hours). **Fewer questions (owner 2026-11-23: "the fewer the asks the
better").** A plain *cannot tell* also says how the two read (`leaning`): like **two** different people (different worlds
with nothing in common, a relative and a colleague), like **one**, or neither. Two who read like two **wait apart and
nobody is asked**: each keeps their own facts, the pair stays a doubt (never a split, so a later link still joins them),
and the next conversation that names the name has them read again. **The question** is only for a pair that reads like
one person or like nothing either way, and only when the read gave an answer that can be stood on: a failed call,
an unreadable answer, quotes that are not there, or a side with no conversation of its own on record is not "the record
does not say", asks nothing and does not spend the pair's one question (the doubt stays, and the next conversation that
names the name flags it again). It is only for a doubt both sides of which are pages (a person held on a line has nothing resting on
it, ruling 65), not yet asked (`same_name_doubts.mark_asked`, never again, even if skipped), not answered (`kept_apart`),
with no question about the two already open from any proposer (`question_open`), at most
3 a drain and 10 open (`MAX_OPEN`): an ordinary `merge_suggestion` between the two pages marked `detected: same_name_doubt`,
`fold_page` (yes folds the less-used page into the other, no records the pair as different for good), worded by what each is
known for ("Are Marc (cousin) and Marc (neighbour) the same person?", the first sentence of each page's Summary in the reason,
`inbox_wording._same_name_doubt`). No rule and no judge of `inbox_tend` settles it (`_merge_rule` answers `needs_person`);
only the person's own words do (move 1). `merge_rejections.kept_apart` includes the doubt pairs, so the dedup sweep, the
catch-up proposers and `person_duplicates` never ask about one; a merge of either page (`entity_merge.merge_entities`) folds the
pair away.

*Cost.* Stage 2: one small-judge call per bare name with something to compare, as before (the prompt is longer by the filed
conversations, at most 20 descriptions in all), plus one main-model call (about 13 times the small one's price, $0.004) for a name
with two or more new conversations the small judge calls one person, or a split against a person with three conversations on
record; nothing is added on a batch with no such name. The tail: one main-model call per flagged page
and per flagged doubt pair, at most 8 a drain (`MAX_LOOKS`), and none when nothing was flagged. On a bank with 200 people pages and a
100-conversation batch the Stage 2 bound is 20 names; the tail's is 8.

**Measured (2026-11-23).** *The replay battery* (`same_name_battery.py`, 71 labelled single judge inputs, the small judge on a key
at about $0.0003 a call, the second reading on): the code before (`origin/dev`, 10 replays a case) kept 216 of 240 two-person
replays apart (90%) and cut no one of 460 one-person replays; an established page against a different person's mention was kept
**The judge is told who the speaker is (2026-11-24).** Stage 1's descriptions name the bank's owner ("<owner>'s
brother-in-law", "took part in a meeting with <owner>"), and the prompt's rule that the speaker appearing in two
descriptions connects nothing spoke of "the speaker" without saying which name that is. Both models then joined two
colleagues of one first name "through <owner>": 2 of 17 benchmark runs, and **11 of 80** replays of four such inputs taken
from those runs. The three prompts (`same_name_people.PROMPT`, the pair and the page review of `same_name_review`) now say
which name is the speaker's when the bank has an owner page, that a tie to the speaker (a partner, a relative, the one
they live or move with) is a fact about that person like any other, and that every description is about someone of
that name whether or not it repeats it. The last two matter: told only the name, the judge cut one real person in two in
8 of 30 replays of a thin description whose one link is having moved with the owner, giving "it names no <name>" as
its reason. As landed: those four inputs **80 of 80** apart, the whole battery (75 cases, 10 replays) **0 of 460** one
person cut and **290 of 290** two kept apart (`same_name_cases.json` carries a `speaker` on the 23 cases whose
descriptions name the owner; `--no-speaker` replays the prompt before).

apart in 69 of 90 (77%; an established family page against a colleague's mention in 0 of 10). As landed: **248 of 250** two-person
replays kept apart (99%) and **0 false splits of one person in 460 replays** (one earlier wording of the prompt cut one person
once in 920; that input was not reproduced in 60 more). *The stories* (`same_name_stories.py`, 30 stories in English, Spanish and
French; the code before 20 replays each, as landed 8 each; ok = the expected end state and number of questions): two people new
in one batch 59 of 60 → 24 of 24; two people already joined on one page, then a clarifying conversation **0 of 100 → 39 of 40**
(the page split by conversation, one commit); two people the record never tells apart **0 of 60 → 24 of 24**, one question each
(the code before blended them in 41 of 60 and asked nothing); a doubt a later conversation links: the code before cut one person
in two in 27 of 60 and said nothing; #814 ended all 24 as the one question with the link in it, and with ruling 74a **24 of 24
are joined by Sleep, no question** (both reads found the link each time). **That 24 of 24 was the simulation's, not the
product's (2026-11-24):** the simulated bank reviewed every doubt once any flag was up, where the product reviews only
what Stage 2 flagged, and Stage 2 flagged nothing when the judge read the whole name as one person. The first two real
Sleeps of a three-night story (a cousin, then a new colleague of the same first name, then a conversation that says the
cousin is the colleague; `same_name_e2e.py`) left the two in doubt both times. With the simulation made to review only
flagged pairs, after every batch as a night does, the code as merged joins **2 of 24**; with the flag fixed **24 of
24**, and the same story on the real path joins **3 of 3** (one commit each, no question; the never-linked pair in the
same story stayed two with no question in all five runs; undoing one of the joins restored both pages and
`reconcile` then kept the pair apart for good). All 30 stories on the faithful simulation, 8 replays each: 240 of 240
ok, no wrong join, no wrong split, no question; one person in many settings, one whose life moves on, a thin first mention, an established page re-read: all ok
before and after (240 of 240; 96 of 96), **no question and no split**. The stories replay a simulated bank; **the real path**
(the stager, `sleep_cycle.run`, the tail, a real engine) was run on a scratch bank with a three-phase, twelve-conversation story
of three first names, six times: no real person was cut in two in any run and no bank was left with an uncommitted file; a page
that had taken a second person's conversations was split by the tail into the right two as one commit in 2 runs, and in the
others that person waited on a held line in doubt. Those runs found two defects the simulation could not: the store left
modified and uncommitted when a flag was taken with nothing to read, and **a second person's page answering to the bare name**
while the first person was still a held line (the only page so titled took the name's key in Stage 2's index, so the first
person's held claims were released onto the other person's page). A page recorded apart from the name's own slug no longer
holds the name's key (`_second_person_titles`); the two runs made to hit that path then kept each person's facts their own.
**One conversation that names both people ("X from work met my cousin X"; 2026-11-24, `same_name_people`, `entity_resolver`,
Stage 1's name rule).** The commonest way a person tells two namesakes apart is also the one the step above handled worst: it
worked on one mention per bare first name per conversation, and Stage 1 writes the two with what tells them apart in the
name ("Nico (finance lead)", "Nico (cousin)"), which is not a bare name and was never judged: each waited as a held line
under its qualified name, never matched to the Nico who already had a page, and an agent asking about Nico got half of him.
*What Stage 1 writes* (`both_named_battery.py`, 11 invented conversations in English, Spanish, French and German: two relatives
and a colleague, two colleagues, a friend and a public figure, a boss and a brother, two controls where the two names are one
person said twice; the product's own call, Sonnet): two entities each carrying a parenthesised qualifier in 58 of 90 runs, one
qualified and one written otherwise ("Aunt Sara", "Marie Curie") in 19, both written otherwise ("Luis de ventas") in 13, never one
entity and never a bare name beside a qualified one; each person's facts on their own entity in 87 of 90 (the other 3 carry a
sentence about the other person). The controls stayed one entity in 20 of 20. **Stage 1 now has one exception to "write a name as
it was said"**: two different people of one conversation who share a name are each written `<name> (what tells them apart)`, in
the conversation's own words, never with the qualifier before or after the name (a rule that holds in any language, no
word list): both qualified in 49 of 56 runs, 6 "Marie Curie" (a real two-word name, rightly left alone), 1 "Luis de ventas";
facts on the right entity 56 of 56; controls 12 of 12 one entity. *Stage 2 reads the structure only*: a person entity written
`<one word> (<qualifier>)` (not a handle the record paired, not the owner's first name; a parenthesis on a concept or a two-word
name is untouched) is a mention of the bare name (`same_name_people.stem_of`); its qualifier leads its description in brackets
(`describe`), so the judge reads it and the thin-description count includes it. Two mentions of one conversation are two
people, the conversation said so: they need no located quote and are never one group, and with nobody on record there is no
judge call (`apart_reading`). **How they stand (2026-11-24, second pass, `sibling_relation`):** *apart for good* only when both
were written with a qualifier, which is Stage 1 following its rule (all of 66 replayed two-person conversations; the controls
stayed one entity in 12 of 12 here and 32 of 32 elsewhere); a bare name beside a qualified one is a shape Stage 1 produced in
neither kind of replay, so it is *a doubt*, a person of its own waiting, never decided (the tail joins it on a located link, ruling
74a). **An answer that puts the two of one conversation in one group, leaves one out, or cannot be used (a judge that fails)
says nothing about which of them a person on record is: neither is** (it used to be the one Stage 1 listed first, so the cousin's
facts could land on the colleague's page by mention order and the pair be written as split for good). Each waits as a person of its
own, in doubt against the person on record and against what else was in that group, and the two stay as `sibling_relation`
says (`read`, `sibling_reading`; `Destination.siblings` carries the pair to the resolver, which records it as a split or a doubt,
`_resolve_same_name_people`). A group the judge itself placed with a known person's filed conversations, with the other of the
conversation elsewhere, still goes to that person. Each is otherwise matched to who is on record by what is said of it, like
any mention; a qualified mention is always placed by name: the plain person's page or line (`Destination(kind, ref)`),
another person's, or a person of its own (`<slug>-2`); with nobody to compare it is the bare name's person
(`Destination("plain")`: the entity takes the bare name in place, its edges and values follow), unless its own conversation
also names the bare name (`no_rename`), which keeps the bare name. **A qualified mention is never left under its written name, on
any exit** (`plan` closes with `fallback`, the resolver again for what the plan never saw: over the batch's cap, a cancelled
run): a thin description after the judge said "different" (under `MIN_WORDS`, the qualifier counted) is *cannot tell*, a person of its own
in doubt, never put back under the bare name nor left a held line (a thin bare mention still goes back to the plain name, as it
always did); anything else nothing placed is the bare name's person, as a bare mention always was, or, when its conversation also
names the bare name, a person of its own in doubt. A name the owner's page, a nickname or a relation bears is not for this rule
and is left as it was. The written name stays as an alias, so a `[[Nico (finance lead)]]` link still resolves and no page is
titled with a qualifier. **A conversation a person already lists, read again** (an edited one), goes back to that person with no
judge: one mention and one person who lists it, or, when several do, the person whose aliases carry the name the mention was
written with (the first read wrote it there; a bare name takes the one person left) (`known_for`); a third person is never
minted for the same two. When the judge puts two groups the conversation told apart on the same known page (the page holds
both people: flagged for the tail as before), the group with fewer of the page's conversations leaves it for a person of its own.
The main model's second look replaces the small judge's grouping only when it accounts for every description of a person on record
(`_covers`): one that grouped only the batch's conversations put the person on record nowhere, and a real run made the cousin a third
person that way.
*Measured* (the real
Stage 1 answers above replayed through the real judge calls into a simulated bank in five states: nobody on record, the first
person on record, the second, both as pages kept apart, one a page and one a held line in doubt; then a later bare
conversation of each; `both_named_stories.py`; ok = two people, no blend, no cut): the code before **0 of 120** (every
qualified name a person of its own, never matched), as landed **55 of 60** (92%; the 5 are the one "Luis de ventas" shape),
**0 wrong joins, 0 questions**, 55 of 55 on the shape Stage 1 now writes; six stories of the shape are in
`same_name_stories.json` (engine-free tests; eight since 2026-11-24, two of them the order reversed). *The second pass (2026-11-24, the four defects above):* the eight stories 64 of 64 (8 replays each, 0 wrong joins, 0 questions; 48 of 48 before); the same 38 Stage 1 conversations through the five bank states 183 of 190, the 7 being the 5 "Luis de ventas" shape (not a qualified name, left alone) and 2 of one Spanish case in the state where the second person is on record (the same 6 conversations replayed on the code before: 2 of 6; after: 5 of 6, 5 of 5, and 1 blend in 11); four real Sleeps of the three-phase story (`e2e_run.py`): the cousin and the finance lead each on their own page in 3 of 4, the fourth made the cousin of the two-Nico conversation a third Nico because the main model's second look grouped only that batch's conversations (fixed above, `_covers`, then 2 of 2). *The real path* (`e2e_run.py`, a three-phase twelve-conversation story with
the two-Nico conversation, real Sleeps on a scratch bank): before, the finance Nico of that conversation waited as a held line
"Nico (finance lead)" in 6 of 6 runs; as landed, three runs: two pages, the cousin's and the finance lead's, every fact of
each on its own, the qualifiers as aliases, no held line, no question, 3 of 3 (a first version, 3 runs, joined the two on one
page in 2 of 3: the judge had put a page's conversation with each, and the placement sent both people to the page; fixed above).
*Not done:* a person the conversation names with a title and no parenthesis when Stage 1 ignores the rule is still a name of its own.

*Known limits.* A split no longer leaves the Summary, History, Related or tags of the old page stating the person who left
(2026-11-24; measured below), but what the judge cannot locate stays, and a line with no source that is a fact of both
people stays on both. **A thin conversation** (nothing in it to contrast) goes where the second look's grouping puts it, and
the record may say elsewhere which person it was ("the slides were from the finance lead" in a later conversation that is not
on this page): the tail does not read other pages' conversations for it, so it can stay with the wrong person (1 split of 7
in the replays below); and where the second look finds no contrast at all it stays on the page it was joined to, never a
guess presented as the other person's. A conversation that names both people is handled above; what stays open there is an old
bank's held lines written with a qualifier before 2026-11-24 (`nico (finance lead)`), which are not people on record under
the bare name and are not migrated. *What the old page says after a split (2026-11-24, `benchmarks/consolidation/same_name_residue.py`).* The stories simulator has
no page prose, so this builds a real git bank: the real Sleep, with the same-name judge answering "one person", leaves one page
holding two people with a Summary written from both (three invented stories, English and Spanish; `same_name_residue.json`);
the real tail (`run_tail`, the main model on a key) then runs on copies of it, and each page's whole text is searched for words
only the other person's facts carry. Pages stating the other person's fact, of the pages a split made: before (`origin/dev`)
**9 of 18** (English, 9 splits in 10 replays; each page carried the jam, the age, the street of the other person: Summary,
History, tags) and 2 of 4 (Spanish, 2 splits in 10); with the Summary, History, Open Questions and tags moved: 10 of 20 and
7 of 14, one word each (a short Key Fact the sentence numbering skips; a Related line and `related` entry); with short sourced
lines and the linked pages moving too: **0 of 22** and **0 of 10** (11 and 5 splits). The undo of the split, run on every one
of those 16 replayed banks, put every page and the graph's edges back **byte for byte**. With the stricter gates of the review (a line tied by its own words, a cut placed exactly once, no edge inside a word or a link; 2026-11-24): **0 of 20** (10 splits in 10 replays) and **0 of 12** (6 of 10), undo byte for byte in 16 of 16; the tie measured three ways, honestly: against the judge's own proof it refused 18 of 36 lines in English and left **9 of 18** pages dirty (a proof copied for one fact of a line that states several; a name both people carry read as a conflict); against the leaving descriptions it left English at 0 of 20 and Spanish at 4 of 8 (a Related bullet states nothing but a link); with a page only the leaving conversations name as a tie too it refused none of 67 lines, and the clause-edge gate refused 3 of 3 clauses it was asked about (a clause starting after "and"). A third story (nothing says which of
two people a thin call-back was about) never splits: 0 of 10 before and after, the thin conversation stays on the page it was
joined to. **Not fixed:** a thin conversation the judge groups with the wrong person (the Spanish story: 3 of 5 splits, 6 of 7
before the last change, 2 of 2 earlier: the spread is the judge's) and the case where the second person is held on a line, so
the page is not split and the thin conversation stays on the first person's page (2 of 3 real runs of the three-phase story);
in both a later conversation says which it was, and the tail does not read it. Three real end-to-end runs (`e2e_run.py`): one split
the page, the old page held none of the finance lead's facts and the thin slides conversation went with him; two held him on a
line and split nothing. The 3-run benchmark does not exercise a split (no `Split a page` commit in any of its six banks), so it
shows nothing here but that the rest did not move.

**Sleep joins a name held in full to its short-name page itself (ruling 74b, owner 2026-11-24: "yes the idea is that sleep can join, split, and whatever", `full_name_join`).** The question the person was asked most, "Is Teodor Brandt the same as Teo?" (pending in 131 of 281 stored benchmark memories), is raised by Stage 2 (`entity_resolver._held_alias_questions`) when the full name was said once, so it waits on a line of its own in `pending_entities.jsonl`, and a later conversation made "Teo" a page. Nothing settled it: ruling 29 keeps who someone is the person's, ruling 74's two signals need two kinds of evidence and a pair no conversation names together, and `inbox_tend` move 1 never lets the raising conversation answer its own question. Now, in the engine-independent tail after the same-name review (`sleep_cycle._full_name_join_safely`, inside Sleep's window, skipped on an engine-free night and on a scheduled run the plan switch does not allow), every open "Is <A> the same as <B>?" of that shape is looked at. **The code finds, the model reads, the code checks.** The code finds the person's own turns (`kind: user`, never an agent's or another speaker's) in the conversations the held line was heard in that carry both names as whole words, the short name outside the full one ("Ola" inside "Ola Petrov" is no second mention) and written as the record writes it (case kept, so "will" the verb is not the page "Will"), and the guards below; every such turn is shown, and more than six (or one over 2,500 characters) is no join, never a cut that could hide a denial; the main model (`same_name_tend.main_engine`, the engine's main model, never another bill) reads those turns with what the record holds about each side and, only for "one", copies the words that present the two names as one person; the code locates them itself inside ONE of those turns (`evidence.locate`; a quote that runs on into the assistant's or another speaker's line, is longer than 240 characters, or touches a `>` quoted line is refused), reads the located words back from the turn and checks **those** carry both names, never what the model returned. No list of words decides: "my old", a comma and a parenthesis are the model's to read. A **second read**, framed to look for the reason they are two, must agree on its own located words. **It joins only when** (1) the question is the held-name kind (not a same-name doubt, not a page question, not put off, and `inbox_tend.policy` still says only the person settles it); (2) A is a person on a pending line named in full (two words or more), with no `title`, not held against a page, never marked apart from this page, and no page answers to its name or aliases; (3) B is a person page titled by one word, not the owner's, not archived, not titled by a relation, not in a same-name doubt, not a pair the person called two or Sleep split (`merge_rejections`), and carrying no name of two words or more but A's own; (4) exactly one page, of any type, answers to the short name and no other person or held person has a word that is, or begins with, it; (5) one of the person's own turns names both; (6) the read says one on located words; (7) the second read says one on located words; (8) nothing changed since the reads began (the question's bytes and the hashes of B's page and the store are taken before the first read; `inbox_tend.apply` re-checks them and conditions 1 to 4); a settle that cannot apply is tried twice, not every drain. Anything less leaves today's question untouched. The join is `inbox_tend.apply` with rule `full_name_one`, the one writer the person's own answer uses: the held line's claims land on B's page with their evidence spans and an older value is closed by the newer, **and the line's own words land with them** (its summary as a Key Fact, key facts, history, links, open questions: `inbox_service._land_held_prose` through the one page writer `conflict_resolver.apply_changes`, deterministic, no model, additive on a page a person edited, never over a pinned passage, each item with the source rows the line kept; the person's own tap does the same), A becomes an alias of B, the line leaves the store, one commit by Sleep (`Cicada-Author`: the model the engine's replies say answered, both reads the same, else `cicada`; trigger `sleep/inbox-tend:full_name_one`) listed under "Settled by Sleep" with a reason that quotes the person's words. **An undo is the person saying they are two** (74a's rule): `inbox_tend.undo` restores the pages and the store byte for byte and does not bring the question back; the pair is kept apart, in the same one commit, by the writer the person's own "No, different" uses (`inbox_service.reject_effects`: the held mention's line marked apart, else the pair in `_merge_rejected.yaml`), so Stage 2's held-name and given-name routes (`entity_resolver._said_different`) and Sleep never ask or join them again; the undo route answers `kept_apart`. Other rules' undo is unchanged. A question read and not joined is not read again until what it read changes (`$CICADA_HOME/full_name_reads/`, ids and a hash, outside every bank); a read that could not be made is tried twice. **Not covered:** two existing pages, a held short name against a full-name page ("Is Sam the same as Sam Okafor?"), a full name with no turn naming both: they stay questions. **What this changed for the person's own tap too (2026-11-24):** before, a held line's prose (its summary, key facts, history) was dropped with the line and only its claims reached the page: on 25 replayed banks 101 of 125 lines (25 of 25 summaries, 25 of 25 history entries, 51 of 75 key facts) had no line on the page carrying their words; after, 0. **A plan defect found on the way (2026-11-24):** `entity_resolver._same_name_ask` labels its call "disambiguation", and on a Claude plan `agent_engine.SCHEMA_BY_STAGE` then forces that stage's own answer shape (`decision`/`reason`), so the same-name judge (Stage 2's and the tail review's) cannot answer on a plan: one call returned `{"decision": "same", "reason": "{\"ok\": true}"}` to a prompt asking for something else. The full-name join asks through `full_name_join.ask_main`, a plain call on a plan, and leaves `_same_name_ask` as it is. **Measured on the Claude plan, Sonnet main (2026-11-24):** replayed on copies of stored benchmark banks that held the question pending, the step joined **26 of 26** (52 model calls) before the review's fixes and **10 of 10** after them (20 calls); every join on located words, every held claim on the page with its span, the older job title closed by the newer, and the held line's own words on the page (0 of 101 missing lines after, 101 of 125 before). 24 invented cases, 5 repeats each (`benchmarks/consolidation/full_name_battery.py`, `full_name_cases.json`: 7 true variants including Spanish and French, and 17 two-people cases: a father and a son, two colleagues, a namesake, a list, cousins, one present and one absent, Spanish, French, a line quoted from someone else, a quote that could straddle two sentences, a forwarded block inside the person's turn, a possessive, a short name whose page already carries another surname, and 5 the guards stop before any call, among them a short name that is also a common word): **0 wrong joins of 85**, 35 of 35 true joins, 135 calls; the quoted line, the straddle and the forwarded block are read as "cannot tell" 5 of 5. Real path (`same_name_e2e.py --engine plan`, `full_name_e2e_*.json`, one real Sleep each): the true story joined, the father and the colleagues stories raised no question and joined nothing. The benchmark's own scorer had no check that the full name and the nickname are one person (`people` passes with the nickname's page alone); `name_joined` (`run.py`) now scores it, 0 of 1 on the stored `dev-final-1124` legs.

**A plain misspelling is assumed, not asked (ruling 74c, owner 2026-11-24: "I think it can clearly be seen it was a typo, at least it can be assumed", `typo_join`).** Two person names that are one name written two ways (`typo_join.variant`: the same number of words, each differing word a sound or one-edit spelling of the other; never a short name in a full one, a nickname, a bare ending, a name that differs only in how it ends in any script (Maria / Mario, Анна / Анн), a word under five letters, or one vowel for another (Elena / Elina) — those stay a question as before; a doubled or dropped letter, a c/k/s/z or i/y swap and a transposition are candidates, Sara / Sarah the one short pair) — a held name against a page (the common case), two pages nobody asked about, or an open same-as question of that shape — are read in the tail after 74b's step. Spelling is never the proof: the main model is shown what the memory holds about each side and the person's own messages that name the held form, and answers "one" only by copying one line about each side that state the same fact; the code finds both lines word for word (`same_name_people._located`) in the text shown for their side, each saying more than the name, and sharing something specific (`typo_join.anchored`: a word that is neither a name of either side nor the speaker's and is either written with a capital or a digit in both lines or on at most three pages of a bank of twenty or more, never one on more than six pages: two lines that both say "is a colleague" are not a fact); a second, sceptical read must agree. Never when a third page or held person has a near spelling (the loose reading, endings and short names included: held quietly, never asked), when a spelling of one side is an alias the person removed from the other, when a conversation names both (ruling 65c), for the owner's page, a relation-titled page, a pair the person called two, Sleep split, or a same-name doubt holds. The join is the writer the person's own yes uses, Sleep's commit (`typo_one`), the held line landing on the page with its words and the misspelling becoming one of its names; a pair with no question gets one written only inside the settle (never shown), so the settled list and the undo are the usual ones, and **an undo keeps them apart for good**. When the model cannot tell, nothing is asked: `person_duplicates.propose` skips such a pair unless a conversation names both, and the digest of what was read (`typo_reads`, outside the bank) re-reads it only when the record under either side changes. Measured on the Claude plan with haiku, `benchmarks/consolidation/typo_battery.py`: 0 wrong joins in 77 replays of cases that are two people (four runs), 35 of 53 true joins.

**After the cycle: Cicada's own agent (ruling 84).** Outside Sleep's write window and on its own thread, up to three open questions a run are worked by a harness session on the Claude plan (ruling 4's switch for a scheduled run; one switch, `harness_agent`; a demo bank, a replica and a plan limit skip), each session (a question has a private one and, for a public thing or a clarification, a web one) bounded to 14 calls, 240 seconds, 12 files, 300,000 bytes and 4 folders (`plan_run` picks only the questions a session can really start on), a missing tool or a session that holds more than it was given skipped in words. A clarification or a pair may also get a third session, in the person's signed-in browser (slice 2, 2026-11-26), last, only when the person connected a site for reading and their own browser-harness daemon is already running (otherwise skipped in words, and the question is worked again once it answers); at most two such sessions a run and six opens a question; a pair is only ever left a note. A settle takes the bank's write admission for its own commit only and is refused while Sleep holds the pages. See `mcp.md`, "Cicada's own agent".

**Open questions are read again (ruling 82, owner 2026-11-24: "sleep could make sure to see open questions and close them with new information or with a better agent", `question_revisit`).** Every lane above reads a question once; this is the second look, at the end of Sleep after them, with the engine's main model against the whole record. *Selection:* open questions of a kind it reads (a "same as?" between two person pages, a conflict, a clarification, a follow-up), never a question the person undid, put off or owns (`inbox_tend._blocked`), in `question_order`, those not looked at in the last three days first; at most 8 read and 120 looked at per run, a read being one to four calls (measured about 1.4 per question read). *A pair of people* (`pair_case`, `assess`): the guards of 74b/74c (neither the owner's, archived, a relation's, in a doubt, called two or split; the short-name reading of `full_name_join.short_name_is_alone`, shared: no other page of any type answers to a short name, no other person page or person held with no page could be whom it means; a short-name page that carries another full name is someone in full, two full names sharing no spelling are two people; two pages with one title are 74a's, but a title the other page lists as an alias, or a short name inside a full name, is read here, the shared name naming only the short page), then the reader sees both pages' lines and every turn that names both, whole, plus the newest turns naming one side, each turn marked by who said it. The conversations that name both come first (`_conversations`: the question's own, then every one the index finds that holds both whole-word, then each page's own): more than twelve of them, or an index not ready, leaves the question with a counted reason, never a cut that could hide a later denial. It answers with a located line (`said`, one turn, both names, `evidence.verify` for the span and its kind) or two lines of the same specific fact (`belief`, `typo_join.anchored` with `rare_only`: a word on at most three pages of the bank; a shared employer or role never anchors); **only the person's own turn or a named speaker's counts** for either (an assistant's turn, an agent's saved note and relayed text are shown as context, never the line); with the code's own kinds (`person_duplicates`: name, contact) the bar is ruling 74's. A second read framed to look for a reason they are two must agree, and any "two" wins. *The settle* is `inbox_tend.apply` with rule `revisit_one`: the person's own merge resolver, Sleep's commit, the spans in the settled record (`evidence_spans`), an undo keeps the pair apart. *Conflicts, clarifications, follow-ups* reuse move 3 (`read_record_answer`, now taking the lines and a memory) with the main model in place of the small one, plus `confirm_option`'s second read. *Memory* (`question_revisits/<bank>.json` under `CICADA_HOME`, ids, a digest, the reader's model, a day, a count): an answered question is read again only when a page or conversation it read changed, a conversation about it arrived (the digest covers the newest turns naming either side), or `stronger(now, before)` (a higher model family, else a changed model); a read that produced nothing usable (outcome `unread`: an unusable reply, an error) is read again on later runs, `MAX_UNREAD_TRIES` = 2 reads in all on the same material (`due`). *Never:* a demo bank, a scheduled run without ruling 4's switch, past the spending limit (calls go out under the `inbox_tend` stage), a fetch. A decay question a later mention answers is `not_fading`'s, engine-free; a proposed edit is the person's. `scripts/question_revisit_dry_run.py` lists one line per question looked at (id, kind, what, rule, evidence ids; `--read` makes the reads, writing nothing). Measured on the Claude plan with haiku (`benchmarks/consolidation/revisit_battery.py`, `revisit_cases.json`): see ruling 82; the product's stronger main model makes those numbers a floor.

**A name with no page, read again (ruling 82, `name_revisit`).** The largest stale group in the inbox is "Is <name> the same as <page>?" where the name did not earn a page and what was said about it waits on a held line (`pending_store`): by hand a quarter of them are another wording of the page's thing and the rest a part, a sibling or something that shares a word, and a wrong landing puts one thing's facts on another's page (G148: "a wrong whole misleads more than a stray page"). So the tail step reads them too, and what stops a wrong landing is code, not the model's care (a judge rigged to answer "same" to everything joins only what is the same). *Same thing:* only a sentence of the person's own or a named speaker's (a located line, read twice) that **is their statement of identity, decided by the code** (`linked`, on the one sentence that holds the pair): one whole span of each name; no question, negation, doubt, condition, contrast or plural subject anywhere in it (not, n't, no, never, if, whether, think, maybe, "are both", and the Spanish, French and German words); before the first name nothing or an opener ("I call it"); between the names one phrase of identity from a closed list ("also called", "known as", "aka", "short for", "is the same as", "is just", "llamado", "también conocido como", never a single function word such as "the", "a", "for", "like"), or a bracket or an equals sign, or a bare "<A> is <B>" only as the whole sentence; after the second name no possessive, no "of/de/for/to/and", no noun running on from it. Every other sentence of the person's own turns that holds both names must be one as well (a turn that also says "<A> is not <B>" leaves the question). Never when one name's words are inside the other's (the part shape) and a shared word, of any length, a number or a plural, needs a second kind (a shared specific fact); never past a record that relates them as two (a claim open or closed), a removed alias, a no, a title or alias another page holds; a name of the page that another live page also answers to is no name of it here, nor is a one-word alias the conversation itself uses straight after a determiner ("the scheduler"), said by how it is used, with no word list; a person only under the pair guards (74 to 74c, one function). It is the person's own yes (alias filed, held lines land), rule `revisit_same`, undone as a join. *Not the same thing:* closed as the person's "No, different" (`revisit_apart`): the held lines stay held under their own name, nothing lands, no alias, **no relation is written** (placing a part is G148's, not this ruling's), never a person, and only on two agreeing reads with a line **located in a turn of the person's own or a named speaker's** that says the name (never the held line's own text, the page's text or an assistant's turn: Sleep wrote the first two and an agent repeats them), and never when a sentence of such a turn could be presenting the two as one thing: the two names next to each other ("<A>, <B>", "<A> (<B>)", "<A> / <B>", "<A> = <B>") or joined only by a marker of equivalence ("I mean", "or", "aka", "i.e.", "that is", "also called", "known as", "short for", "o sea", "es decir", "o", "también llamado", "alias"; a bare "is" only as the end of the sentence), read on every sentence of the whole turn (a name the page shares counts as the page's for this check); a sentence that names both with anything else between them (a preposition, a verb, a possessive, other nouns: "the <A> for <B>", "<A> in <B>", "<B>'s <A>", "<A> is part of <B>") says they are two and holds nothing back, so a part of a project named with its project is closed: otherwise the person has related them and the question is theirs. *A page that has faded:* of the 185, 95 asked about a page since archived (none the owner's; 56 at confidence 0.0, 32 at 0.2). When nothing said about the name is dated after the page's last mention (the held lines' and the question's conversations by their own `timestamp`, never `received_at`, against `last_referenced`), the question is retired with no read (`target_faded`, "The page it asked about has faded"): nothing is written to any page, the held lines stay held under their own name, undoable, listed under what Sleep settled. When the name WAS said after, it is read like any other and a part, a sibling or an unrelated name may be closed, but **a "same" is never landed**: the person's own yes bumps the page's `last_referenced` and leaves its status and confidence, so the lines would sit on an archived page nobody sees (a real mention revives a page to active at 0.6; reviving is not this step's call, left to the owner). A dropped page, a missing page and the owner's page keep their own reasons (`target_dropped`, `target_missing`, `owner_page`); a page or a name that cannot be dated is left (`target_faded_undated`). *A label nobody said (measured 2026-11-24 on the same bank, real values redacted):* looking for each asked name in the conversation its question was raised from, verbatim and case-insensitive, it appears nowhere in that conversation in 107 of the 185 (a label Stage 1 coined for something: "<Feature> redesign", "<Project> extraction worker", "Daily <thing> PDF"; nobody said it), only outside the person's own turns in 64 (an assistant's turn, an agent's saved note, a note's body; a rough speaker heuristic), in the person's own turn in 15. 83 of the 115 questions the dry run of the second look left "read, unsure" (after a model read each) were of the first kind: no line can ever be located for a name nobody said, so each was read again every time a page changed and could never close, and the person was asked whether Sleep's own label is the same as one of their projects. Such a question is retired with no read (`name_not_said`, "It asked about a label Cicada made up, not something that was said"): the name (and the held line's aliases) located by `evidence.locate` (exact, then whitespace, then case-insensitive; never fuzzy; the folded-words check of `question_revisit._hits` only ever adds "said", so a hyphen, an accent or a case never makes a name unsaid) in no text, whoever's turn and the conversation's frontmatter included, of the question's own conversation or any conversation its held line cites (`heard_in`, the held claims' evidence); a rewording is not said, a name differing only by case or spacing is said. Nothing is written to any page, the held lines stay held exactly as they are (ruling 73), undoable, listed under what Sleep settled; a cited conversation that is missing or unreadable leaves the question (`conversation_missing`, counted); never a person (a name may come from a field the text lacks, and a coined role for a person is `role_people`'s lane); a question the person undid or put off never reaches it; the dry run prints the rule beside `would_retire`. The same check at Stage 2's raise site (`_create_duplicate_clarification`, `name_revisit.coined_label`) does not raise the question at all: the held line is written exactly as before. *Measured again with the new cases* (Claude plan, haiku, one run, 57 questions in 25 cases): 8 joins of 8 wanted, 24 closed apart (22 wanted, 2 where either was right), 2 retired (faded page), 3 retired as a label nobody said (3 wanted), **0 wrong in every row**, 20 left, 44 model calls for 50 questions read; the new cases leave a label whose cited conversation is missing, a name only an assistant said, and a name differing only by case, spacing or a hyphen (none retired); rigged "same": 8 joins (all right), 3 retired, 0 wrong; rigged "different": 28 closed apart, 0 wrong, 3 retired. Names of one page are read together (`GROUP_MAX` 5, one prompt holds the page once, each answer located in that name's own turns only); the bound is the step's (8 questions read a run, plan through ruling 4's switch, a key inside the spending limit, a demo bank never); a retirement makes no read. *Measured* (Claude plan, haiku, a floor: the product runs a stronger main model; `revisit_battery.py --names`, invented names; 41 questions in 19 cases, per run): 8 the same thing (an abbreviation, a description, Spanish, a name the person used for the page only in a later conversation, a person), 12 a part, a sibling or unrelated the person's own turns never relate to the page in one sentence, 12 lines that are no statement of identity (the review's own: a part, a denial, a question, a doubt, a kind, "I mean"), 2 questions about an archived page the name was last said before, a name said after, a generic alias two pages carry, and a pile of ten on one page. Over 2 runs: 16 joins of 16 wanted, **0 wrong**; 18 closed apart of 24 wanted, **0 wrong**; 4 retired (the faded page), 0 wrong; 44 left; 77 model calls. A judge rigged to answer "same" to every name and quote the best line it can find: 8 joins (the 8 that are the same thing), **0 wrong** (every other stays by code); rigged to answer "different" and quote the person's own turn: 10 closed apart, **0 wrong** (a name whose turn holds the page's name in the same sentence is never closed).

**Two pages that go by one name (G21, owner 2026-11-24 "fewer asks, hold a doubt rather than ask", `alias_collisions`).** A title outranks an alias: a page never lists another live page's title among its names. *Birth:* `wrong_aliases.title_of_other_page` (one lookup on a derived title index, never for a person, the owner's page or a saved link's `media` page) is asked by the three writers that add names to a page Sleep makes — the create and update branches of `conflict_resolver` (the update branch's older id check missed a title whose id is not the alias's slug) and `entity_merge` (the loser's aliases no longer travel whole); Stage 2 has already weighed every extraction alias that names an existing page as a judge candidate before Stage 5 writes. *In the bank:* a tail step after the typo join, engine-free first (a saved link on either side is quiet; a pair the record holds as two things loses the alias), then the engine's main model reads both pages and the alias twice, the second read looking for the opposite reason, at most `MAX_READS` pairs a run, on a plan only through ruling 4's switch; no engine means no read and the engine-free half still runs. Both reads two things → the alias leaves the page that lists it (`aliases_removed`, one undoable "Settled by Sleep" commit, rule `alias_apart`), never from a page whose conversations carry the alias in the person's own words (every conversation the page lists, newest first, stopping at the first hit, only the person's own turns by authorship; a page with more than `MAX_EPISODES` = 200 is not scanned and keeps the alias); both one thing → one question for the pair (`fold_page`, `detected: alias_collision`), asked once; anything else (unsure, the reads disagree, the person's own words use the name) is held quietly: the read is remembered and **nothing is closed or rewritten**, an open question stays as it is (ruling 29: a model that could not tell is no answer). A question the person took back (`sleep_settle: undone`) or put off is theirs: the step skips its pair entirely (`person_holds`) — no read, no close, no second question — until they answer or the day passes. The record saying two things only through a relation claim (which a model may have written) while the alias is the person's own word is the same hold: that branch does not know the person said so, so it leaves the question open. What a read stood on is kept outside every bank (ids and a hash, `alias_reads/`); Stage 2 raises no lead question for a pair held or asked. `scripts/answered_questions_dry_run.py` prints one `ALIAS` line per pair (ids and rule), `--read` to read the pairs a model decides. Measured on the Claude plan with haiku (`benchmarks/consolidation/alias_collision_battery.py`, 13 invented pairs, 50 calls): 0 wrong removals, 0 needless questions.

**A question the record already answers is closed (ruling 74c, `answered_questions`).** `merge_closes` closes a "same as?" question when a merge answers it, and now matches either page under every id that became it (`page_redirects.former_ids`), except an id that has a page of its own again (a stale redirect never closes that page's own question): "A or P?" had outlived A into W and W into P. What no merge closes — a name filed under a page by any of the writers that add an alias, a redirect made before this — is settled by Sleep's own tending, engine-free, before every other rule on a "same as?" question: `already_one_page` (both ends one page through redirects) and `already_a_name` (the asked name has no page and is a name or non-removed alias of exactly one page, the one asked about; what a line still holds lands through the question's own resolver), never over a pair the person called two or split — wherever that "No" is kept, the held line's own `apart` included, and never for a line held against that page (Stage 2's undecided) — never for the owner's page; and, for a conflict, `names_one_page` (every value a name of one page: the option written as the page's own name stays). Listed under "Settled by Sleep", undoable. `scripts/answered_questions_dry_run.py --memory <bank>` prints, per question, what would settle and by which rule (ids and rules only) and writes nothing.

*The benchmark* (3 runs, both people, as landed): the fixture's two Marcs apart in 3 of 3 runs (the code before joined them in 1 run of 3 on a one-person answer, and so did a fresh control of `dev` the same day), one person kept as one 5 of 5 each run, others' words kept off the person 13 of 13, pages made or not made 14 of 14, updates 12, 12, 13 of 13 (control 12, 12, 12), every fact a claim or held under a waiting name (52 of 52 each run; claims 48, 46, 51). Questions 6, 7, 3 a run against 3, 2, 5 for the control and 5, 3, 3 before: one of them is the pair of Marcs, asked once in 1 run of 3 when the second look could not tell them apart; the rest are other proposers' run-to-run spread. $0.68 a run against $0.64: the second reading, about three main-model calls a person. *With ruling 74a (2026-11-23, the stories again):* two people the record never tells apart stay apart in **60 of 60** replays with **no question** (one each before) and no wrong join; an established page then a different person 32 of 32 with no question (7 of 32 asked before). On the benchmark (3 runs): the two Marcs apart in 3 of 3 and **no question about them in any run** (asked in 1 run of 3 before; in 2 runs the pair waits as a doubt), Sleep joined no one (there is no one to join), one person kept as one 5 of 5, others' words 13 of 13, questions 4, 4, 3 a run against 6, 7, 3, the same $0.68 a run.

**Which way a relationship points (2026-11-23).** A role the other side holds toward the person ("my <role> X") was
sometimes written backwards at Stage 1: `<user> | <role> of | X`, the person as the holder. Nothing downstream can catch it
(`entities_to_claims` writes the triple as given; the claim's text is `<source> <label> <target>`), and a reversed
relation reads right. Cause: the prompt asked for "who someone is to the user" as a relationship ("partner of",
"cousin of": labels with no wrong side) and said nothing of which side holds the role, so the model put the speaker first
because the words were the speaker's. Measured on stored benchmark banks, per extraction of the two conversations that state
the in-law: 3 of 24 on the dev code, 6 of 74 on the recent branches, 67 of 104 before the "relationship of its own" line; no
reversal among about 340 relations of landlord, tenant, manager, referral, hand-over and a service the person used. The
prompt now carries one rule, not a list: **a role in a label belongs to the source** ("<source> <label> <target>" must read
as a true sentence, in any language; two examples of other roles). There is no code backstop: telling a role noun from any
other label in any language would be a word list, and a symmetric or owner-held relation must never be flipped.
**The replay** (`benchmarks/consolidation/direction_battery.py`, `direction_cases.json`; engine-free tests in
`test_direction_battery.py`) runs Stage 1 alone through the real `entity_extractor.extract` (its prompt, owner block and
date note, on a scratch bank) over 20 cases of kinship, work, housing, clients and mentoring in English, Spanish and French,
plus symmetric relations and ones the owner holds, and counts a role written the wrong way round, a symmetric relation
said in both directions, and a relation not stated. About $0.012 an extraction on Sonnet; `rescore` judges saved answers
again with no model. A case names the holder, the other side, the role in its language and the role the other side holds
back (the gold of the case, not a product rule). The benchmark's `gold.roles` check now also guards the hierarchy (R3).

**What the person says in passing is a relationship, not only a key fact (2026-11-24).** The benchmark's one gold fact that
is sometimes not a claim, "has read <a book>" (P18), was never dropped: stored banks show Stage 1 wrote it on the book's
page and the person's own as a key fact ("<user> read <title> and loved it"), and wrote only "<author> author of <title>"
as a relationship, so Sleep had no claim to keep (the book rails' `book_said` still carried the status, on the episode, which
the scorer does not read). Cause: nothing in the prompt said the person's own act on a named thing is a relationship; "who
someone is to the user" is, and "capture every meaningful connection" left the act to the model. Measured by replaying the
product's own Stage 1 (`benchmarks/consolidation/dropped_battery.py`, `dropped_cases.json`; engine-free tests in
`test_dropped_battery.py`) over invented conversations where the person mentions a book, film, trip, course, purchase, race,
doctor's visit or decision inside a conversation about something else (English, Spanish, French), and over counter-cases that
must not become the person's act (the assistant's suggestion, a thing only asked about, a plan, someone else's act): on the
benchmark's own conversation 15 of 40 runs had no claim (the dev code), on the other 21 conversations (104 runs) 1 of 104
(one French book), none in the other kinds. The fix is one sentence in the relationships paragraph of the prompt: what the
user's own line says they did with a named thing, said in passing, is a relationship from the user to it, never only a key
fact. After: 164 of 164 passing facts a claim (40 of 40 on the benchmark's conversation), every one that states a day on that day (16 of 16), 0 of 67 counter-cases written as the person's act; a plan or a doubt is still written as a plan or a doubt ("considering
watching", "plans to visit"). The harness counts a fact as `claim` (a relationship between the owner and the thing, or a value
on either), `status` (only the book rails' mark), `prose` or `dropped`; `rescore` judges saved answers with no model. A call is
under a cent on Sonnet.

**Pick the page (G227, owner ruling 2026-10-29).** A mention that could be any of two or more same-titled pages is ONE
question for the mention — never one per pair: `ClarificationManager.create` finds an open question about the same
mention through any of its `same_title` pages before writing a second, and stores "Which <name> is this?". The question
is served (`same_name_pick`, at read — the labels carry derived qualifiers) with one option per candidate page still on
disk (`page:<id>`, labelled "<name> (<qualifier>)", plus `pageId`/`pageName`/`qualifier`) and `another` ("Another one" — owner on #546: "none should probably just mean another one"; the key `none` it first had is still accepted).
`page:<id>` is the inbox's own `merge` into that id (the held mention's claims land there, G209, and the answer lifts
any earlier "apart" for that page). `another` means **this mention is its own thing with the name**. It is recorded on
the mention's own pending line with the conversations it holds (`pending_store.mark_apart`, `apart`), **never as a
name→page rejection**. The mention's slug is usually a candidate's own id, so a name-keyed pair kept every later
mention of that page from joining it (#546 review). The same holds for "No, different" and dismiss on any question
about a held mention (`inbox_service._keep_apart`); a page-pair question keeps `merge_rejections`. A join on the name itself drops the `apart` pages only on a re-read of those conversations (`_apart_here`), so a new conversation naming one of those pages still joins it. The judge, a lead and a question honour the line's verdict whatever the conversation (`_said_different`, `ClarificationManager.create`), so that mention is never weighed against, or asked about, them again. The line's claims never follow the
name onto an `apart` page (`pending_store.ready`). Once the unchanged promotion bar is met and a later mention is not
one of those pages, the line gets a page of its own: **the same clean title and a distinct id** (`_another_id`:
`<slug>-2`, `-3` …; no stored "(another)" — the qualifier tells the pages apart). The record dies with the line, so a
later merge has nothing to lift. A page whose own id the title spells keeps the name's key in `existing_by_name`, so
a join on the name never moves to the newer page by listing order. A key that is not one of the question's pages is a
400, nothing written. `_merge_rejected.yaml` pairs written by an older "No, different" stay as they were.

**Sentences about a different same-named thing (G227, `same_name_split`).** A repair *plan*, never applied by Cicada on
its own: for every page in a same-name group that is not a saved link (and any page id the caller names), the page's
prose is split into numbered sentences and an injected judge lists only those *clearly* about another thing with the
name — target a listed page id or `new` — with a reason; anything unsure stays. It writes nothing; the owner OKs a plan
before a separate step applies it. **Applying it is the person's split** (`page_join`, `storage.md`), mainly
through their agent in conversation (owner 2026-10-29, `mcp.md`): the agent proposes in plain text and splits only on
their yes. `GET /entities/{id}/split-plan?suggest=true` still serves the judge's picks for this one page to any client
that asks (the person's chosen engine); nothing moves until a split is called.

**Sleep never re-joins a split pair (G227 follow-up).** A split writes the pair to `_merge_rejected.yaml`'s `split:` list;
the dedup sweep reads `kept_apart` (rejected ∪ split) and skips the pair without a judge call, and Sleep's inbox tending
never settles or judges a duplicate question between them (`inbox_tend._merge_rule` / `judge_merge` →
`kept_apart`). A new mention of the shared name still reaches either page through the same-title judge — the split
keeps the pages apart, never the name from a page. Only the person (or a trusted agent) merges them back.

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
updates also run the existing contradiction check. A measured quantity that naturally changes over time (a metric, a count, a score, a
balance) is an update, never a contradiction, even on the same date; a value that should hold still, such as an agreed price two people dispute, can still ask (ROR-41, G98). `entity_orientation` passes dated inputs and
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
  **A group chat** gets `group_note` instead: which member each `speaker:<label>:` (or `assistant:`) marker is, and
  that a member's words and "I" are theirs. A claim resting only on ONE member's lines has observer
  `external:<member>`; one resting on several members' lines (or on a member Cicada cannot name) `external:group` —
  one stable observer, since joined names would split one belief per combination and the spans already say who; a
  group claim is the default reading only when the person's own line backs it; and in a group only the
  person's own `user:` lines count as "the person's own words" for promotion, project birth and an application
  (`promotion.person_kinds`) — a meeting still counts every speaker; the same rule holds for a waiting Contacts card
  (`entity_resolver._said_in_person_turn`), a project's conversations (`project_conversations.person_named`) and the
  inbox tend. `promotion.person_said` and `promotion.claim_cites_person` never count a claim Stage 1 gave to someone
  else (`external:`), so a member's line never reads as the person's words to `page_relevance`, `web_context`'s
  protected claims or `quiet_pages`, nor to `page_quality_repair`'s link rung. The same holds for a one-to-one chat
  with a friend: a claim resting only on their lines is `external:<friend>` and never counts as the person's words on
  pages.
  **Interaction signals (owner 2026-10-28, `turn_signals`).** The extras every chat writer stores beside the words
  (`turn_extras`: `reply_to`, `reactions`, `forwarded_from`; `unsent_turns`) reach Stage 1 as one note per chunk,
  after the source note and before the conversation (the model sees it; evidence is verified against the stored body,
  so no offset moves). `r<n>` names the message a reply answers — quoted from this body, or from the earlier sitting
  of the same `conversation` that holds it (found by `message_keys`, indexed once per Sleep load, `KeyIndex`), or said
  to be unknown, never guessed; a reply reading order already explains (the line above, or the last thing anyone else
  said with only the replier's own lines between) is not noted. `s<n>` is a reaction: who reacted, with what, on which
  turn — a signal, never the reactor's sentence; an agent's routine like is not noted (its doubt or emphasis is).
  `f<n>` says a forwarded line's words are the original sender's; `u<n>` that something unsent was there, never what.
  Edits and attachments need no note (the body holds the final words and the attachment's name). The model may tag a
  relationship or value with the label it rests on (`"signal": "r2"`): the tag is consumed and the quote located inside
  that turn first, so a short "yes" lands on its own line (exact → whitespace → case-insensitive, never fuzzy); the
  tag grants nothing by itself — a quote outside the tagged turn rests on no signal. The person's own reaction on the
  one turn a claim's located spans sit in is read from the stored extras, never the model's word or tag
  (`turn_signals.person_stance`): agreement (❤️ 👍 ‼️) lifts its confidence by 0.1 (capped at 0.95; a 👍 often only
  means "got it"), doubt (❓ 👎) halves it, and the claim records it (`reactions: [{by: user, stance, kind, episode,
  turn}]` — `turn` the reacted turn's offset, the reaction's own key in `turn_extras`, so the reaction is its evidence
  by turn id). **A reaction never changes the observer** (#499 review): a texted agent's claim stays
  `external:<agent>` whatever the person tapped. Measured on the owner's bank 2026-10-28 (76 sittings of one chat,
  read-only, counts only): 828 replies (741 in the same sitting, 87 in an earlier one, none unfound), 195 reactions
  (all the agent's like or emoji), 4 edits, 0 unsends; after the skips, 308 noted signals, ~194 tokens per sitting
  (median 138), ~14.7k in all — about +3.5 % on a call whose system prompt is ~4,750 tokens.
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
follow-ups (G141 PJ-6, right after expiry, its own `cicada` commit), **the catch-up questions** (below, right after the
follow-ups, their own `cicada` commits), the exact-match source links (G61 S3-a, `source_links`,
its own `cicada` commit, dirty pages skipped), the site check (G61 S3-b, behind `CICADA_ALLOW_CONNECTOR_FETCH`, its own
`cicada` commit), the tracked-source re-check (ruling 26), **the web check** (below), the connector poll, RSS/ICS
polling (opt-in via `CICADA_ALLOW_FEED_FETCH=1`), and the link enrichment backfill (which reads for the person's reason, below) — all in a clean-tree-guarded slot,
after `_finalize`'s own commit so the poll's `git add -A` sweeps only its own files. **What triggers each source's poll
(G245, track C1).** The connector poll and the RSS/ICS poll are no longer Sleep's alone: `source_polls.scheduled_poll`
is the backend's own job, every 3 hours beside the tier-2 job (`network.md`), so a Sleep on `manual`, or a night with
nothing readable, no longer leaves a feed, a calendar feed or Reddit, Pinterest or X stale; a kind that job polled in the
last hour is left alone by the tail (`source_polls.polled_lately`). **A scheduled time with nothing readable still runs the
tail** (`sleep_catch_up.probe` → `run(tail_only=True, engine_free=True)`): the polls, claim expiry and the state refresh run;
every step that would ask a model (the same-name review, In short, a recording's read, the web check and light context,
the link backfill, the books' model read) is skipped like a run stopped at its limit, so no engine starts and no plan is
spent, and no run is recorded (it reads nothing, so there is no drain, no `runs.json` row and no "ran" on Past nights). After them, unguarded (no git),
the episode vectors are synced when an index-only episode is newer than the vector index (owner ruling 2026-10-18).

**Which one was meant (ruling 83, `sleep_cycle._which_one_read_safely`, 2026-11-26).** Right after the catch-up proposers, with a model, Sleep reads the open "were you talking about A or B?" questions about a held mention (`which_one_reader`, `features.md`): two reads by the main model over each conversation the held line holds, code checks on the copied sentence and on what the record ties the mention to inside it alone (`which_one_tie`: the tell attached to the mention by form, no question, negation or contrast, no other candidate's tell), and a filing through the resolver's own merge as Sleep's undoable commit. No such question, no engine and no commit. When the conversations do not all name one page, each conversation's words go to the page its own reading named (`which_one_file`: one landing, one `land-NNN` record and one commit per page, undoable per record; a conversation nobody could tell keeps its words held and the question is about it alone; a page is credited only with the conversations that landed on it, and the question closes in the commit of the filing that leaves nothing to ask; before any read the tail also files, with no engine, a held claim whose conversations were all filed to one page already on that earlier verdict (`which_one_file.refile`, undoable, never refiled after an undo); a person's "someone else" for one conversation holds on every path that takes a claim off the line; `features.md`, *Each conversation to its own person*).

**The catch-up questions (vision item 10, owner 2026-10-28; `sleep_cycle._catchup_questions_safely`).** Two
engine-free proposers feed the person's catch-up chat (`mcp.md`, "Catching up"), under ONE budget of new questions per
drain (`inbox_catchup.Budget`, `NEW_PER_DRAIN` = 3), each in its own `cicada` commit (`Questions to check in <day>`,
`Same-person questions <day>`; dirty pages skipped, a failed commit unlinks what it wrote):
- **"Are you still …?"** (`still_questions`): an open, non-event claim on the person's own page whose predicate is a
  state that ends — a role (`works-at`, `employed-by`, `studies-at`, `lives-in`, `reports-to`) or an interest
  (`is-interested-in`, `interested-in`, `wants-to-learn`, `is-learning`, `learning`, `studies`) — last said in a dated
  conversation (`claim_reconciler._said`; a memory export entry is no mention) at least 180 days ago (a role) or 60–365
  days ago (an interest: past a year it is history), whose object page was not said since either. A role is held back
  when a tracked source on the page was re-read within its cadence (ruling 26 keeps it current); a stale, never
  re-read or dead source is the human reason ("your LinkedIn seems a bit stale"), read from the stored `refresh`
  state, never fetched. An interest is held back while its page has an open decay question. Written as an ordinary
  `conflict` with `asks: still`, `still: role|interest`, `last_said`, `said_in`, the claim as option `a` and the item's
  `claim_id` (picking it grades `agreed`, "Not anymore" — `neither` — closes it today, free text is a new claim), at
  most 4 open and one per `(page, predicate)`; roles first, then the most-used topic, then the most recently quiet.
  The person's answer is remembered in `<bank>/_still_answered.yaml` (claim id → day and an enum, committed with the
  answer; the `_merge_rejected.yaml` pattern) and that claim is not asked again for 180 days (a role) or 120 (an
  interest). Ruling 29's tending never settles one by rule or judge (`inbox_tend.policy` → `needs_person`); only the
  person's own located words do (part 1). Only the person's own page — a third party's job waits on the owner.
  "Still interested?" is claim-level (an open interest claim 60–365 days silent), not a decay question — the page's
  decay is untouched — and rests on the owner's 2026-10-28 item-10 request. "Not anymore" closes that one claim and
  its sentence names only that value (`still_questions.ended_sentence`), never "none of the values are current".
- **"Are A and B the same person?"** (`inbox_catchup.propose_nicknames`): two People pages whose names are a nickname
  and its long form (`nickname_pair`: the short one a single word of ≥ 3 letters, a strict prefix of the long one's
  first word and at most 0.6 of its length) with no open question, no alias in common and no "two people" answer
  (`merge_rejections`), written as an ordinary `merge_suggestion` marked `detected: spelling` on the less-used page,
  at most 3 open. A question only (ruling 41, G209): spelling is a reason to ask, never proof, and only the person's
  words join them.
- **"Is A the same as B?" for the pairs a person spots at a glance** (`person_duplicates`, ROR-136, owner 2026-11-06): a
  misspelling a transcript made ("Texim" / "Tikzim"), a first name beside the full one, a shared account. Engine-free, no
  network, **no word lists of any language** — letter classes only: `sound_key` folds the letters that spell one sound
  across alphabets (`x`/`ks`, `z`/`s`, `c`/`k`, `ph`/`f`, then vowels after the first letter dropped), plus one-edit
  spelling, a one-word name that is a word of the other's longer name, an alias, the same account in both pages' sources,
  and the same *rare* belief on both (a fact on more than 3 people says nothing). An alias counts as a name only when it
  starts with a capital and has no possessive or `@` ("his girlfriend", "she", an address are not names); two pages
  titled by their relation to the owner are `role_people`'s; two fuller names that do not match are two people sharing a
  given name; a pair the person called two people (`merge_rejections`) is never listed. **Being named together lowers the
  score, never raises it** (ruling 65 c), and so do two names that are each well established (4+ conversations); a thin
  page (≤ 2) raises it, since a mishearing is said once. A pair needs a name signal; a shared account (held by ≤ 2 pages) or
  3+ rare shared beliefs between two never named together is the only record-only lead. The drain writes the best few as an
  ordinary `merge_suggestion` (`detected: person_duplicate`, `signals`, the reason in words), the less-used page asked
  about, at most 6 open and inside the drain's shared budget (`_catchup_questions_safely`), so the card's one-tap merge, the
  page's own question list and every undo already work. It is the record's own question (no conversation naming both is
  required, `pair_evidence`'s exemption for a lead the record raises), so "Cicada's guess" stays ≤ 0.4 unless one does; the
  owner's page is never paired. Mostly a question only — the person's words join them — **except two independent kinds
  of evidence (ruling 74, owner 2026-11-07)**: `person_duplicates.joins` marks a pair joinable when the name (sound,
  spelling, a short name in a full one and one page listing the other's name as an alias count as ONE kind — owner
  2026-11-08: a listed alias joined two different people), the same account or a shared rare belief agree in at least
  two different kinds, the pair was never named together, neither page is titled by a relation, neither page is in
  another candidate pair and the score is ≥ 0.6; `inbox_tend`'s `two_signals` rule then settles that pair's question as a
  merge (Sleep's commit, listed under "Settled by Sleep", undoable and never re-settled). A conversation that names both
  pages, or any "two people" answer, keeps the pair a question.
- **A merge closes the question it answers** (`merge_closes`, owner 2026-11-06): `entity_merge.merge_entities`, the one
  merge primitive behind `cicada_merge_pages`, the app's menu, the CLI, an inbox answer, a placeholder person folded into a
  named one and the dedup sweep, removes every pending `merge_suggestion` whose two ends are exactly the two pages (either
  direction, by page id or by the slug of its title) in the merge's own commit (and `merge_footprint` lists them for the
  sweep's rollback). A "Which X is this?" question over several pages and every other kind are left to their resolvers.
  Undoing the join restores the card with the pages.
- **"Two people" takes a crossed alias off** (`merge_rejections.uncross_aliases`, owner 2026-11-06): answering a same-person
  question "no, different" removes, from each person page, an alias that names the other (its name, id or one of its
  aliases) into `aliases_removed`, so no writer adds it back. Why: a page listed a real other person's name as its alias
  since a Sleep extraction read two co-applicants named in one sentence as one person; the guard against a crossed alias
  (`alias_policy.names_another_page`, 2026-10-29) is for aliases Sleep adds and never reached one already written.

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
`litellm`; the dedup sweep now resolves first). The sentence names only what the app does (*Connect a plan or choose a key in Settings → Intelligence*; the scheduled form, *Scheduled runs may use my plan* in Settings → Sleep) and no shell command: a Mac app person has no server. `cicada sleep status` adds the server's command to that error (`engine_readiness.cli_fix_for_error`, matched by `NO_ENGINE_LEAD` / `SCHEDULE_DEGRADED_LEAD`), the way the schedule warning already takes `CLI_FIX`. A plan limit (`EngineThrottled`/`Exhausted`/`Overage`, the breaker tripped by a swallowed per-episode throttle, or the
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
its discarded leg retains observations but charges no content attempt. Connection loss never charges a timeout/content
attempt; it waits for the network within the run before it pauses (below, 2026-11-03).
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
**A Claude key (G237, ruling 63, 2026-11-04).** A key whose model is `anthropic/…` or a bare `claude-…` is served by
Anthropic's own SDK (`anthropic_engine`), never LiteLLM: `direct_engines` is the seam, one row per provider, and every other
key stays on LiteLLM. `providers.resolve_llm_fn` routes there only when the completion it was given is LiteLLM's own, so a
test's fake stays the answer. It sits where a plan's CLI sits: the shared semaphore (`agent_max_concurrency`), the scope's
breaker, the drain's seam retry, one ledger row a call (`engine: anthropic-api`, `billing: usage`, `cost_source: table`). The
prompts are the plan's own (`marshal_prompt`, `JSON_ONLY_SUFFIX`) without `CONTEXT_GUARD`: the API attaches no context. A
caller's "reasoning off" is `output_config.effort` at `agent_low_effort`, sent only to a model that takes it; `temperature`,
`response_format` and `extra_body` go nowhere. Every call streams, so `max_tokens` is 64,000 (the model's own limit when the list
gives one; output limits count tokens as they are produced, never `max_tokens`), a caller's cap gains 2,048 for thinking, and
`timeout` is checked as a wall clock while the answer arrives. A refusal (`stop_reason: refusal`) is `EngineRefused`: the
conversation's own `refused`, never retried; a cut-off or empty answer is `EngineProtocolError`, one retry.
**Caching.** One breakpoint at the end of the system prompt, TTL 1 hour: the same bytes every call of a stage, and a user
message that differs every call, so anything marked later would be written and never read. A drain's next batch reaches the
same prompt past 5 minutes, so the 2× write pays by its second batch. The first call on a prefix goes first and the rest wait
for its first byte (bounded 30 s): an entry is readable only once its response starts streaming, and parallel calls otherwise
all write. Cache reads do not count toward a key's input-token rate limit. **Limits.** The SDK rides out `retry-after` (4
retries). Past that a 429 trips the scope's breaker with `limit: key_limit` and the rate-limit sentence; a 429 or 400 naming a
spending limit is `EngineExhausted`, and a 401/403 `EngineUnavailable`, each in `engine_cause`'s words. It stops as `plan_limit`
for the drain's mechanics, with a pause reason of `key_limit` that never says the person's plan, and arms nothing automatic.
A limit lifting within 2 minutes is waited out by the batch's later stages, so what was read is filed.
**What fails, and what it costs.** A raw transport error out of an open stream, or a stream that closes before the model
finished, is `EngineConnectionLost` or `EngineTimeout`, a pause, never the conversation's; only a status is ever called a
refused request. A call that failed after the provider started answering carries what it reported (`exc.paid`, `_paid`) to
the ledger, so Past reads and the limit below see a cut-off or refused call's real cost. The SDK is pinned (`api/pyproject.toml`,
2.1.0): every 2.x sends the key as `Authorization: Bearer` on API version `2026-10-21`.
**The spending limit (ROR-102, ruling 63 (g); `sleep_spend`).** A run on a metered engine snapshots `spend_limit_usd`
(`sleep_run_prefs`, in `connections.json`: unset reads as the suggested $5, stored `0` is the person's off, nonsense reads
as the suggestion) and `providers._emit` adds each call's cost to `ds.spend`. It stops on the reserve's own path:
`DrainStop("reserve", …, limit="spend")`, pause reason `spend`, so what was read is filed and the rest wait. **How far past:**
one read past it when reads cost about the same; if a read costs far more than any before it, every read then out, at most 3 on a Claude key and 10 on another; plus filing what was read. A call in `LINE_STAGES` (a read, In short, the web check, link reads, the inbox's judging) passes
`sleep_spend.turn` after it holds its permit: the run's first call goes alone to learn the price, a later one goes only when
what is spent and what is out leave room, and past the line it raises `SpendLimitReached`, never sent. A refused read goes back
to wait, nobody's failure; one caught part way through its chunks is read again next time. Every other stage files what was
read and is never refused. `batch_size` sizes each batch to the allowance left, at the last batch's cost per conversation, or
at first at the most one read may write. A run past the line skips the tail's paid steps even with nothing left to read;
link backfill runs in `sleep:<cycle>-links` on a drain, so its spend counts.
**A part of the figure is the question steps' (2026-11-27, `QUESTIONS_SHARE` = 15%; the coordinator's reading under the owner's
standing word of 2026-11-26).** Before it, a run that stopped on the line skipped the tail's question steps (the same-name
review, the full-name and typo joins, the second look at open questions, the described landing, the which-one reader) with the
rest of the paid tail, so on an install whose arrivals outrun the allowance they never ran; and on every run on a key those
steps' calls ran **outside** the guard (they opened no drain scope, and their `disambiguation` label is the batches' own
filing, never refused). Now: while the drain reads, the line is the figure less that part and less the dearest call so far
(`SpendGuard._line`; batches are sized to it), so the last read stays out of it. The part is kept only while the steps have
something to read: the first time reading reaches its line, `question_steps.has_work` (each step's own engine-free filter;
questions raised during the run count) is asked once (`_ask_reserve`); with nothing, reading goes on to the whole figure
(a night with no open question of their kinds reads exactly as before). When reading stops on the reading line,
`_drain` calls `end_reading` (the line is the whole figure again) and returns `_StageOutcome.questions`; the tail then runs
the question steps, **in today's order** (so before the catch-up proposer, as on a full night; the which-one reader after it, as
before), inside `_question_line`: a scope `sleep:<cycle>-questions` registered to the drain, so their calls are counted into
the run and, by scope (`sleep_spend.QUESTIONS_SCOPE`, read by `providers._spend_line`), admitted or refused against the whole
figure whatever stage label they carry. The same scope holds them on a run that read everything under the line. Every other
step that asks a model (In short, the web check and light context, link backfill, a recording's read, the books' read) stays
skipped as at any limit; a stop on a plan's limit, a Pause and a Cancel are unchanged. A refused call is an `EngineExhausted`
(`SpendLimitReached`), which each step already handles as a plan limit is: what it read stands and what it did not read
stays for the next allowance (a Continue is a new allowance; the steps' own marks stop them reading again what they read).
The run's record says it in counts (`questions_room`, `question_steps: {calls, settled}`, `sleep_runs.note_question_steps`)
and the log says "reading stopped to leave room for the question steps" and what they used; the pause sentence is unchanged.
**The bound is unchanged:** the figure plus the one call a line may be passed by (a question call is a few cents), because
the steps' calls are admitted only below the whole figure. A charged call whose cost cannot be read stops the
run like a model with no price (fail closed), before any read when the models are known at the start (`guard_for`), else at the
first unpriced call. A Continue is a new allowance; a scheduled run waits for that click, while one paused on `restart`,
`engine` or `busy` is replaced with a fresh allowance. **Only runs are covered:** Ask, the inbox's tidy and catch-up, a click's
web sweep, repairs and the quick read are not limited (the help says so) and are in the ledger at what they cost. One click's
web sweep on a metered key is capped at `web_check_per_run` (`capped_at`).
**Comparing with the plan.** `benchmarks/engine_parity.py` runs the same synthetic conversations through the production drain
on a scratch bank per engine and compares pages, claims, evidence spans, questions and failures, with what Past reads would
show. The one real run, once a key is entered (about $0.02 on Haiku 5.5, 19 calls, about 94k input of which 16k uncached,
about 26k output, measured from the plan leg):
```sh
api/.venv/bin/python -m benchmarks.engine_parity run --leg plan --model haiku --out /tmp/cicada-parity/plan
api/.venv/bin/python -m benchmarks.engine_parity run --leg key --model anthropic/claude-haiku-5-5 --out /tmp/cicada-parity/key \
    --key-file ~/.cicada/secrets.env --max-input-tokens 40000 --yes-spend
api/.venv/bin/python -m benchmarks.engine_parity compare /tmp/cicada-parity/plan /tmp/cicada-parity/key
```
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
**The network left — the Mac asleep, offline, a request that timed out (G163, 2026-11-03).** Live case: a scheduled
run on a laptop, the lid closed mid-read for about three hours; on wake all four `claude -p` calls answered
`terminal_reason: api_error`, no status, "Request timed out" while the network was not back yet, and the run stopped as
`engine/needs_fix` ("Run `claude auth status`…"), badged the four conversations *could not be read* and drew Sort as the
failed stage. Now: (1) the transport's own timeouts ("request timed out", "connection timed out", "socket hang up",
`ECONNABORTED`, undici's connect timeout…) are `EngineConnectionLost`. (2) `machine_state` reads two local signals and
sends nothing: `has_route()` (a UDP `connect` to a documentation address asks the kernel for a route — no packet, no DNS;
`ENETUNREACH` means offline) and `slept_s(mark)` (a clock that counts sleep minus one that does not:
`CLOCK_MONOTONIC − CLOCK_UPTIME_RAW` on macOS, `CLOCK_BOOTTIME − CLOCK_MONOTONIC` on Linux; never the wall clock).
(3) `sleep_drain.offline_cause` sorts a failed call into `asleep` (it overlapped ≥ 30 s of machine sleep), `no_network`
(no route) or `connection` (a transport failure with a route); a sign-in, plan limit or refused model is never offline,
and an unnamed failure counts only with the machine's own evidence (asleep or no route). A pause-class stop met in the
same batch — the plan breaker, a sign-out, a refused model — outranks an offline one whichever came first, so a plan
limit keeps its `resets_at` (ruling 15 arms on it); the offline ids stay requeued. Stage 1's hook marks each read's
start; a later stage's escaped error is checked against the batch's start, only while nothing is on disk
(`write_started` false). (4) An offline failure is `engine_failed` (never `could not be read`, no attempt or timeout
charged) and dooms the batch before its first write; the drain then **waits in the same run** (`_wait_for_network`):
with no route it polls every 5 s up to 10 min, settles 15 s and reads the same batch again under its own number; with
a route and a dropping connection it backs off 30 s / 2 min / 5 min. Waits count in `asyncio.sleep` steps, whose clock
stops while the machine sleeps, so a closed lid spends none of the bound. At most 3 waits in a row (a committed batch
resets the count); the person's Pause is honoured on every poll; the write window is shut and no engine is called while
it waits; the engine resolved at the start is the one it reads with again (ruling 4). It is not ruling 15's
continue-after-reset — no plan limit is involved and nothing is armed past the run. While waiting the drain's wire
carries `waiting: asleep | no_network | connection` (status and SSE). (5) A network that never comes back pauses as
reason `engine`, `engine_kind: offline`, no `error`, with a sentence about the network ("This computer was asleep and
the network was not back yet… Continue once it is online"; "computer", since the backend also runs headless), and the
record's `offline_cause` (`asleep | no_network | connection`, on the wire too) says which; Past reads records the pause
as `offline`, or `connection` for a dropping connection with a network present. (6) `SleepState.stage` (stages completed) moves to 1 only after Stage 1's
total-failure checks, so a Stage 1 that failed draws Read as the failed stage, never Sort.
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
from a scheduled run. The dotfile pin keeps its one batch (ruling 16); on a metered engine it spends until the queue is empty or the person's spending limit, and the engine menu and Details
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
scheduled engine, until that live sign-in. **Ruling 46a (owner 2026-10-28):** Auto and scheduled runs use Cursor only
with Cursor's own models (`cli_engines.cursor_own_model`: the Grok line, Composer, its own `auto`) — Auto landing on
Cursor runs `auto` unless the stored model is already Cursor's own, never the tool's config default; a scheduled run on a
person-chosen third-party model (billed separately at list price under The X Subscription) has no engine, said in words
(`SCHEDULE_CURSOR_THIRD_PARTY`), never swapped; a run the person starts keeps any model they chose, which the picker
labelled before they chose it. The guard runs whatever set the mode: a `CICADA_LLM_MODE` pin counts as Auto when it is
`auto` and as the operator's explicit choice when it is `cursor`. A tool is a rung only installed and signed in — OpenCode only with a GitHub
Copilot or OpenCode Go model listed — else skipped, never an error and never a key; an installed tool skipped (signed
out, only key-backed models, no answer) or an app here without the tool it needs is named in the no-engine sentence,
with the line to run; an absent one is not. **The Claude and ChatGPT plans' missing tool (2026-11-06):** `ConnectionStatus` and
the `agent` / `codex` engine cards carry `nextCommand` — the vendor's own installer, from `connections/install_hints.py` — beside
a short `detail`; the Sleep pre-flight and engine errors say the same line in a sentence (`CLAUDE_INSTALL_SENTENCE`,
`CODEX_INSTALL_SENTENCE`), never `npm i -g` (a stranger's Mac has no Node). **Found where it is (ROR-52, 2026-11-04):** `base.resolve_binary` looks on
PATH, then the usual folders (`~/.opencode/bin` added, where OpenCode's own installer puts it), then
`base.APP_BUNDLED_TOOLS`: OpenCode.app carries its tool as `Contents/Resources/opencode-cli` (its Electron build's `process.resourcesPath`, ROR-41) or, in an older build, `Contents/MacOS/opencode-cli`, and a tool on PATH outranks either.
The backend makes this read because it is what spawns the tool: two fixed folders (`/Applications`, `~/Applications`),
fixed app names, never a path a request names and never `~/Library`, like `reach.py`'s Tailscale. A tool found in its app
has its full path in the sign-in line, since the app does not put it on the person's PATH. **Three states, not two:**
`available` still means a tool Cicada can run. `Status.not_ready` (wire `notReady`, additive, with `nextCommand`) is
`available: false` with the app here: Cursor.app with no `cursor-agent`, or a copy of OpenCode older than `--pure`, which
refuses the whole call with its usage text (OpenCode.app 1.3.3, read from the real tool); `--pure` is never dropped to make
it run, and it is read from the tool's own help, once per path and modification time, only on positive evidence. The
message comes before `--file`, an array that takes every word after it. The rungs read #494's
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
deny-all `.cursor/cli.json`; OpenCode `opencode run <message> --format json --pure --dir <dir> -m <provider/model> --file
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
history, month summaries, list saves and bare saves (*Indexed, not consolidated* and *The lean pass*, above) — so they
are never frozen, batched or counted as read by the model. **A batch is bounded by what it holds too (ruling 62):** at
most the person's count (`sleep_run_prefs`, default 25) and `sleep_drain.BATCH_BYTES` (60,000 bytes of episode files,
never fewer than one episode), because a stop loses the batch in progress and nothing is committed until Stage 5. By count
alone a run of 22 was one batch of 22. A long session now reads alone and short ones keep the count; "Batch 3 of 7" is the
same rule (`batches_left`). The cost is one more `skills` call and a merge per page per batch. **Not built (G163):** a
journal of paid answers, which is what would keep the work of a batch a stop lands in. **Once per drain, not per batch:** temporal decay (both engines,
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
- **Paused is a fact about a run, not a state of Sleep.** A run that stops with conversations still waiting (Pause = the cancel path, a plan limit, the engine going away, the reserve line, or a restart) leaves a `paused` record in its sidecar (`sleep_paused`); `status` stays `idle`, `is_writing()` is false, nothing is held. `POST /sleep/trigger {"continue": true}` rebuilds the drain from it (same run id, the frozen list minus what is filed, the counters carried, batch numbering from what was committed); **a no-body trigger stays a fresh run and clears it** (the documented curl); `POST /sleep/run/end` forgets it (409 while reading); `POST /sleep/parked/retry` unparks and reads exactly those ids (409 while running or paused). **The scheduler reads nothing while a paused run waits** — except a *scheduled* run's pause no person chose: a `restart`, an `engine` pause at least 6 hours old, or (ruling 4b) a plan-limit pause whose limit has reset, is ended (Past nights says `ended`) and replaced by a fresh unattended drain (`sleep_paused.schedule_may_replace`) — it still runs the engine-free tail (`run(tail_only=True)`: expiry, follow-ups, the state refresh, the polls, the link backfill; the after-import probe at most once a day), and the paused record stays on the wire meanwhile — and counts *readable* conversations (`sleep_debt`'s `readableCount` = waiting minus `parkedCount`). `sync_service`'s `sleep` component and the SSE event carry the pause, so the app hears it. Only the Sleep page continues a paused run (the app's doors route to it; the server stays permissive). **A paused run is not in flight**: the record, its sentence, an armed continue-after-reset and the queue all outlive a backend restart (`recover_after_restart` touches only a `running` sidecar; `test_a_paused_record_outlives_a_restart`), so the dev `scripts/dev/auto-update.sh` and the release updater install under it, deferring only for a cycle `running` (a paused run's upkeep tail included), `writing: true` or a drain still reading (2026-10-17: deferring on any `paused` block held every update from a failed 03:00 run until 15:09). **A backend that answers nothing at all is not busy** (2026-11-26: one spun on the event loop for about 100 minutes until it was restarted by hand and every tick deferred): the dev script counts an ask that got no HTTP response (refused, timed out, empty, reset) only while the service's own pid is alive and holds the port asked, across ticks that really asked; past 30 minutes (`CICADA_AUTOUPDATE_SILENT_MINUTES`, floor 10) it asks that pid for its stacks (`SIGUSR1`, `stack_dump`) and restarts it through its service even with no code moved, after the checkout guards, unless a bank's `run.json` says `running` and was written inside those 30 minutes (a drain making progress); a `running` answer is never interrupted, and the run such a restart cuts comes back paused with reason `restart` (`scripts/dev/README.md`).
- **Honest live progress** on `drain` and the SSE event (every key optional): `startedBy`, `firstRun`, `calls` (each spawned engine call; only grows, a discarded batch's included), `elapsedMs`/`pausedMs` (measured, never a remaining time), `batchState`, `stages` (Read/Sort/Decide fill only from finished work; Notice and File carry no number), `byOrigin` (frozen = filed + read + waiting + couldNotBeRead + parked + skipped), a live `arrivedSince`, `ownerPage` beliefs, `reserve`. `GET /sleep/queue` serves the per-conversation rows from frontmatter only (≤ 200). Neither it nor `GET /sleep/run-options` / `GET /sleep/runs/{id}` is a Store domain (no `VersionVector` mapping; in-memory caches in the app, emptied on a bank switch).
- **The reserve is a soft stop** (`sleep_reserve`): Stage 1 stops *starting* reads once a plan window is past the line, what was read is filed, the rest is not an attempt; the run pauses with "Paused to leave room in your plan." A line, not a guarantee: overshoot is unmeasured, a window the engine never reports is served `enforced: false`, and the ChatGPT plan is read from the pre-flight snapshot each batch already takes. Off leaves the Claude rung's own R-E12 90% stop; a reserve lifts it for that run.
- **Continue after a plan reset** (`sleep_autocontinue`, ruling 15): a one-shot job per bank (`job_id`; a trigger or End in one bank never drops another's, and a bank's activation re-arms its own), for a run the person started, only after a 5-hour window (or the reserve on one, or extra usage) that gave a reset time, at most twice, within 36 hours, same engine, never weekly, never scheduled; `run(continue_from=…)` is called from the Continue route and this module only.
- **Past nights groups by run:** history rows carry `drainId`/`batch`/`batches` and a `run` summary (from `runs.json`; a paused run dropped without a Continue — a fresh Consolidate, an empty Continue, End, the schedule's replacement — is `ended` with its pause closed, and a restart records its open `restart` pause), and `GET /sleep/runs/{id}` (ETag) sums by `refs.drain_id` over every `llm_call` — models with the ledger's own stage names, plan windows per batch (a reset between two batches is never averaged away), pages touched. `SleepEnginePreview.billing` (`plan|charged|local`) lets the app word the spend without naming a provider.

**Link summaries read for the person's reason (vision item 1, 2026-10-28).** When the person said why they saved a link (`saved_why.reason_of`), Stage 5.57's summary and the backfill's are asked to lead with what the page shows or says about that, about the page only (never "the user" or the reason itself), at most two sentences (`link_enrichment._SAVED_WHY`, read by `_summarize_excerpt`; 160 output tokens instead of 100 when a reason rides). A page described before its reason was given is read again **once** for it, as the backfill's third tier after reuse and fetch and inside the same cap (`needs_reason_read`; not a page the person's own agent read): the new `describes` claim supersedes the old one (history kept), Cicada's own summary gives way, a description the page itself gave stays, and the page is stamped `read_for` (the reason's `at`, or its words' hash) whatever the fetch answered, so a reason costs one read; a new reason earns one more. An engine failure leaves the page unstamped. Measured on a copy of the owner's bank (8,541 episodes, 4,027 saved-link pages): 12 saves carry a reason, 11 already described; the haiku dry run read 9 (2 pages returned no text); of the 8 whose reason names something specific, the new description speaks to it on 6, the old one on 2 (2 more in part), and none mentions the person; `scan_backfill` +0.05 s (0.57 → 0.62 s median). **Stage 1 is unchanged:** a saved link's episode already holds its reason section, and a before/after eval on the same 12 saves (haiku, the plan) found the reason recorded faithfully in 12 of 12 without a note; a 130-token note invented one reason and dropped another, an 89-token one changed nothing measurable, so neither shipped. Since 2026-10-29 a save's reason is the only part of it that is the person's writing: its title, header lines and fetched description are `page` words (`authorship.of`, `evidence.SAVE_KIND`), so the reason is what a save adds to promotion (G191 row).

**Disclosed asymmetries (not fixed here):** Stage 5.57's `recommends` person credit reads only the last batch's changes;
Home's "Last read" shows the last batch's pages. Details' last-cycle figures — "Last cycle took", "Last engine" and "What it cost" — come from one record the backend finds, `/sleep/status`'s `lastFinishedCycle` (`last_cycle.latest`, 2026-10-16): it walks the newest 200 "Sleep cycle" commits (trailers only, decay skipped) and takes the first that is a plain cycle or a batch of a run whose summary says it ended (`finished | failed | ended`); a batch of a run still running or paused is skipped — and so is any commit since such a run began whose ledger row is missing — so a long or paused drain filling every history row the app holds no longer hides the cycle before it. A drain is one cycle: the run's `read_ms`, its commits' `Cicada-Engine`, and its cost summed by `drain_id` over every call (a discarded batch's included), the ledger window opening at the chosen commit's day and widening only back to the run's own start. The miss path runs off the event loop; cached per (bank, HEAD, runs-file stamp); a chosen commit with no ledger row is retried after 5 s only while it is under 5 minutes old (a demo or pre-ledger bank is not recomputed per poll). `null` = none in the walk; the app falls back to the newest history row's own figures, titled "last batch", only when the key is absent (an older backend). A plan run's line is its window's before → after with no price. The status's in-memory `lastEngine` (reset at every run start) no longer feeds the row; the page rereads status and history on every visit and when the Store's newest Sleep time or Sleep's state moves — at most every 30 s while a run reads (`SleepPageRefresh`). **Pause and a hard plan rejection mid-batch still discard the batch in progress** (no journal of paid answers — the tail must say "the part it was reading is read again", never "read and kept"). A scheduled drain pins its bank for hours (the same 409 as any run) and, on a metered engine, has no ceiling Cicada sets. The **app's own** Projects and Backlog controls key off `writing` (`ProjectWriteGate`; `/status` and the SSE `sleep` event carry it, and the sync version's `sleep` component moves when it flips), so they are disabled, saying "Sleep is running", only inside a batch's write window and come back between batches; an older backend without the field falls back to `running`. After a stop, Details says how many stay filed and never a batch count (the wire's `batches` is the plan); a cancelled or plan-paused strip and tail retire with the backend's cancel window and the vendor's reset time respectively. A drain on a consumer plan is the largest plan spend Cicada makes; the "leave room" reserve covers every window the engine reports (the 5-hour and the weekly one alike), is a line and not a guarantee, and a window the engine never reports is served `enforced: false`.

### What may be sensitive (G235, ruling 60, 2026-11-04)

`episode_scrub` replaces secret shapes before anything is stored and is permanent, so it stays narrow. `sensitive_text`
finds what ordinary wording gets past it and changes nothing: `Hit(kind, start, end, sure)`, never the words and never a
hash of them. Pure and engine-free. Kinds, the reading per speaker, and the measured figures are on G235.

- **One door to every engine (`sensitive_hold`, inside `providers.resolve_llm_fn`).** Every callable the resolver returns
  masks the messages first, on every engine and for every job: Stage 1, a reply note, a question's evidence, a web lookup,
  a saved reason, a page rewrite, Ask's own model; a hosted embedding model goes through `hold_texts`.
  `test_sensitive_hold` fails on any other way to reach a model. **By value, not offset:** every confident hit on record
  in the bank, minus what the person left, wherever the same value stands, spelled as JSON spells it, a long number whatever
  separates its groups, and a value a length limit cut in half. A value that could be an ordinary word or a short number
  (`distinctive`) only on a line that speaks of a secret; so does a token more than three other conversations hold
  (`Guarded`, `RARE_CONVERSATIONS`): one line calling `gpt-4o` a password never masks it in every prompt. The prompt is also read by itself as a coding session is read,
  for words no conversation holds yet. In memory it keeps per-file offsets keyed on the file's stamp and re-reads the few
  files with a hit, and which conversations hold each value by digest; nothing stores a value. Masking that raises closes
  that text (a mark alone, when it holds a value or a hit or cannot be checked); not being able to read the bank costs only the
  bank-wide half, since every model call would otherwise stop on one bad file. A cold first look (at launch, off the loop) costs about 22 s on 75 MB of talk
  about logins, 12 ms after. **What it does not cover, on purpose:** an agent the person talks to reads the record as
  stored until they remove it (recall, `cicada_sources`, the sources Ask cites), on their own ask.
- **Stage 1's own send** (`sensitive_flags.Guard`, shared with the quick read) records what the read holds and masks the
  same values by offset, so a confident hit reaches the model as `[held back: <kind>]` on the chunk's copy only: `content`,
  its `revision` and every span stay on the stored body. An unsure one is read.
- **What the model answers is cleaned either way** (`Guard.clean`, after the spans are located): a value becomes
  `[removed]`, and a name, a link's end or a value that WAS one is dropped. `sweep_written` passes over the batch's dirty
  pages before `_finalize`, by structure. After a removal the door no longer knows the value, so a revision's removed text
  is masked against the passage it became (`masked_for_engine`, `masked_against`), and a conversation's title on its way
  to an agent's primer or continuation goes through `title_for_others` (a capture's title is its first line).
- **The record** is the episode's `sensitive` frontmatter: `read: [{engine, at, kinds, held?}]` written before the send,
  under `episode_lock`, frontmatter only; `engine` omitted rather than guessed; `kept: {kind: n}`; `removed: {kinds, at,
  pending?}`. Kinds, counts, labels and dates only. A kind the person left (`kept`) is neither held back nor stripped on a
  later read, so a wrong alarm stops costing its word.
- **The review** (`sync_review`, an engine-free tail step before any poll's `git add -A`, a path-scoped `cicada` commit,
  trigger `sleep/sensitive-review`): ONE inbox item, kind `sensitive`, one row per conversation, each checked against the
  body as it is now. `sweep_read` finds conversations already read, once per `DETECTOR_VERSION`, kept outside every bank
  (`$CICADA_HOME/sensitive_sweep/`); it writes nothing on an episode and never runs in a demo bank.
- **Remove** (`remove_rows`, the person's act), in an order that leaves the value findable and the row standing wherever
  it stops. **First the older version is committed** with no author (`Older version kept before a removal`, a conversation
  still waiting has no other copy), and checked against `HEAD`; no commit, or no repository, refuses with nothing changed.
  **Each row's reach is decided before any is written** (`_reach`): only a confident, distinctive value that at most three
  other conversations and six other files hold travels. An unsure one, an ordinary word or a common token never leaves its
  conversation and the lines or claims that speak of a secret in a file naming that conversation by its whole id.
  **Then every file a value may leave**, one atomic replace each (`sensitive_purge`, by what the file is: frontmatter, YAML
  and JSON loaded, walked and dumped; a claim fence written by its one encoder; a wikilink that held it becomes the mark
  alone; a key or id field left; a file that does not parse left and counted). Every text store in the bank is walked:
  pages, ledgers, hubs, backlog, inbox, nudges, clarifications, `pending_entities.jsonl`, `_index.md`. Then **every other
  conversation holding a value that travels**, in its words or beside them, through the same revision path (only beside them:
  the strings are cleaned and Sleep has nothing new to read). **The body last**: `[removed: <kind>]`
  wherever the value stands in it, sidecar `offset` and `reply_to` moved, title and strings beside it cleaned, a `revised`
  record, requeued, `removed.pending`. **A common word is guarded:** it leaves only where it was called a secret, and a
  tied file's line or claim that speaks of one; a page with no tie to the conversation keeps it. Only a value that travels
  has its exact token as its own tie. One failure stops that conversation only: pages done stay done, the row stays, doing it again
  finishes. One commit as `user`. The word index is rebuilt on a new file (`rebuild_fresh`: a dropped table's bytes stay
  readable in the old one); the conversation's vector passages and any holding a distinctive value are deleted
  (`forget_passages`, `secure_delete`); `_state.md` is rebuilt and commits alone. `build` sees a pending removal: nothing to
  read when the removal is all that changed (`same_after_removal` asks the two texts, so a conversation that only repeated
  a value qualifies), and it closes even on a transcript, whose revisions otherwise close nothing. **Git history keeps the
  older version and is never rewritten; the source still holds it; what an engine read cannot be unread.**
- **The words stay out.** `episode_staging` and `transcript_capture.write_session` take them out of what a source re-sends
  before hashing, so an unchanged source hashes unchanged and a changed one never brings them back; `reapply_waiting`
  catches any other writer just before a batch reads. Only the kinds the person removed, and any other line holding a value
  the same source states. **Limit:** no value is stored, so a conversation that only repeated a value flagged elsewhere
  cannot recognise it if its own source sends the words again.
- **`scripts/sensitive_census.py`** counts what the detector would flag on a bank, and **`scripts/sensitive_removal.py`**
  lists what Remove would touch per row (other conversations, files, tokens that stay) and its plan stamp, and `--apply --plan <stamp>` removes exactly that through
  `POST /sensitive/remove`. Neither prints a value, a title or a path.

### What Sleep asks (G239)
A question is worth the person's attention only when they alone can answer it and the answer changes something. Everything
else stays a mention in the index (`pending_store`), never lost, and comes back if it is named again.

- **"Who or what is <name>?" is the model's call (`ask_person`).** Stage 1 reads the whole conversation and says, in one
  clause, what rests on the answer: the entity's optional `ask_person`, kept as the item's `why_asked` and shown as the
  card's reason. `entity_resolver`'s `ask` raises the question on that alone, for a name held below the bar or a new page.
  It used to be raised on a low extraction confidence (below 0.5, 0.3 when absent), which measures certainty about a name's
  attributes and only ever fired for a first mention: a name with a lease resting on it reads confidently and was never
  asked, and a stray first name read as unsure and always was.
- **A question asked on purpose stays with the person:** `why_asked` keeps it out of `in_passing` (`passing_rule`), out of
  a web lookup (`web_settle.classify`, `person_context`), since the model read it as nothing public could answer, and out of
  the organic close (`check_organic_resolution`), since a confident later mention says nothing about the stake. The person's
  answer closes it, or their own located words (`inbox_tend`, ruling 29). A stake said on a question already open is added to
  that card (`ClarificationManager.create`).
- **Ruling 65 (owner 2026-11-05):** a question rests on the model's stake, and a thing still in motion that will matter later is one (an ongoing project whose owner or status is left unclear); a list of names with nothing depending on them is not. A stake on an existing page raises its question under the page's name, never on the owner's page; `ClarificationManager.create` keeps one open per name. An answered question leaves no record, so a later stake on that page can ask again. A public thing with `ask_person` is never looked up, a narrow exception to ruling 27.
- **Two people with nothing tying their names (ruling 65 c):** being named together is evidence they are two. The judge's UNSURE (no lead of its own) on names sharing no spelling, word or close spelling, on no alias, asks only on a line naming both, and the judge is told to say UNSURE only when what is said suggests one person (`pair_evidence.names_tied`, `lines_naming_both`, reason `names_unrelated`). Older questions are not retired by this.
- **"Is A the same as B?" takes a reason on the record.** The judge's UNSURE (`_UNSURE_GUIDELINE`, both prompts) is told it
  puts a question in front of the person, and that names which look alike or little to go on are DIFFERENT: two entries,
  nothing lost, a later conversation can join them. It used to be told "if you are hesitating, return UNSURE", on leads that
  need only a shared word or one edit of spelling. `pair_evidence`'s "a conversation naming both" then passed on a note
  listing two people, which is evidence they are two. So the judge now reads those lines too
  (`_with_said_together`: B's conversations of this batch, the lines naming both, at most two): "A has the keys, not B"
  separates them, and "might be the same" gives the reason.
- **What a Sleep on a key does with a public thing.** A key on a model with a price row runs the ordinary public-thing
  lookup (`web_lookup.engine_for`, `metered`): at most 8 questions a run, about 1¢ a search plus its tokens, against the
  person's limit (ruling 63 (i)). The settling step and a tracked source's read stay plan-only (`_plan_only`, `metered_only`):
  those questions wait, are looked at again each run, and never settle on a key. A key with no price row or another
  provider answers `no_search_tool` or `search_unreported`, so every public question waits. Not raising a question that
  needs none is what stops both piles; rulings 27, 44 and 54 are unchanged.

### Entity promotion
Entities are NOT extracted from every mention — that pollutes the graph. First mention stays in the
vector index only; promotion needs **2+ separate conversations**, OR substantive discussion (>3
exchanges) in one, OR an explicit link to an existing high-confidence entity.

**A name nobody said is a label (G148, 2026-11-25; `coined_names`).** Stage 1 returns each thing with a name it wrote; on a real bank 107 of 185 "same as?" questions named a thing no text of the conversation says (`name_revisit.unsaid` retires such a question). `coined_names.said_in` is the one reading of where a name is (`person`, `others`, `nowhere`, by the turn's author, `evidence.locate` then the folded whole-word check, never fuzzy) and `coined` applies it to a Stage 1 entity: a concept or project whose name and every alias no text says, the owner's name and the source note counting as said, the names being exactly the set the promotion rung counts by (`promotion.name_variants`: the name, the name with a trailing "(...)" removed, each alias; so a name the rung counts as said is never a label), never an entity that carries an `application_birth` (ruling 42) or a book the person said a status of (ruling 61, the caller's `book_said` mark). One `Reading` per episode folds and tokenises the conversation once for every entity and alias (`question_revisit.Words`). Stage 1 stamps `coined` from the text (never the model's to say) and drops the entity's `ask_person`; Stage 2 pops the stamp and, when every conversation of the batch that gave the name only described it, leaves the one-conversation rungs (a link to a page, substantive talk) closed: the name is held below the bar with what was said and its claims' evidence, and a conversation that says it, or a second one that gives it, promotes it by the ordinary rule. Nothing is renamed, dropped or moved, so recall and Ask find the description in the conversation as before. `benchmarks/consolidation/coined_labels.py` measures the birth (Stage 1 alone) and the fate (one real Sleep) on invented stories; `coined_bank.py --bank <path>` prints counts only for a real bank's held lines, pages and open questions and writes nothing.

**What was said about a thing nobody named lands on the page the conversation says it is about (G148, 2026-11-25; `described_landing`).** A held line whose name no conversation says (a label) keeps its claims forever, since 1,350 of 1,351 on a real bank cite one conversation. **A rule in code alone landed nothing on a real memory** (dry run on that bank: 953 claims looked at, 0 would land; of the 341 that cleared the turn, span and located-words gates only 22 sat in a sentence naming exactly one eligible page, and the last gate, the label's words beside the page's name, turned every one of those away, as it must: a label is words nobody said that way), so the placement is a read: **code before, the engine's main model, code after.** *Before the read (code):* the line is a label (a concept or project whose name and aliases no text of any conversation it cites says, `coined_names.said_in` is `nowhere` in every one); the label was the claim's subject, the claim is open and not an event; its located span is current (`source_spans.Source.status`) and inside a turn the person's own (`promotion.person_kinds`: a meeting's named speaker, never an assistant, an agent note or a saved page); and the SAME conversation names at least one candidate page in a turn of the person's: a live **project**, never the owner's, a tool's, a concept's, a person's, a company's or one the person said the mention is not (`apart`), by title or alias, located by `evidence.locate` (whole word, never fuzzy), a name only one page bears. **Only a project is a page a fact lands on** (dry run on the owner's bank, 310 claims reached the reader, 33 would land on 17 pages, each judged against its sentence: on a project page 17 of 17 right, on a tool page 2 right and 4 doubtful (a thing built with the tool, an account of theirs in it), on a concept page 3 right and 7 wrong (a specific thing of the person's on the page of a general notion that shares a word with it)); a conversation that names only tools and concepts leaves the claim held, counted `named_pages_not_projects`, before any read. No candidate: the claim stays held. *The read:* one call per line and conversation (at most 6 claims) shows the claims, each one's turn, the 3 turns before and 2 after each (bounded to 9,000 characters) and the candidates (at most 6, nearest the claim first) each with its name and a one-line summary; the model answers which ONE candidate each fact is about (the thing or a part of it) or none, with the sentence it copied from a person's turn. It reads twice: the second time in the reverse candidate order, only the claims the first named, told to look for the reason the fact is about something else or nothing on the list. Both must name the same candidate; each copied sentence (at most 240 characters) must locate exactly, never fuzzy, in a person's turn inside the shown window; the claim's own other end is never the page. A disagreement, "none", an unusable reply or an unlocated sentence leaves the claim held; a "no" is remembered per claim (a hash of the claim, window and candidates, under a hashed key, outside every bank) until one changes, while a failed call, an unusable reply and an unlocated sentence say nothing and are read again. A relation ("the landlord of <Page>", "<Page>'s accountant"), the person's own life and a tool used with the page are the reader's to refuse. *After the read (code):* `land_page` writes the claim on the page with its id, predicate, object, own evidence span, source conversation, observer, trust and dates unchanged and the subject re-keyed to the page, plus the copied sentence as one more evidence span; its text keeps the label's own words and says `(a part of <Page>)` when both readings said a part, `(about <Page> itself)` when both said the label is the page in other words, and nothing when they did not say the same (the weaker wording, never a refusal), so a located span backs every word and no model wrote one; a page that already says it (same predicate and object, or any open value of a single-valued predicate) is left alone and the fact stays held. The page's `source_episodes` and `last_referenced` are NOT moved (the conversation is no new mention); the line loses only the landed claims (`pending_store.drop_released`) and is closed only when it holds no claim, fact, link, question, summary or description. One page, one run, one record `inbox/settled/land-NNN.md` (group `sleep`, rule `land_described`, the copied sentences as spans with their claim ids, the held claims and the landed ones) and one `cicada` commit of exactly its paths; `undo` (`POST /inbox/settled/land-NNN/undo`) removes the claims only while each is as written (its identity, words, evidence spans and still open; the confidence, decay stamps and sessions Sleep keeps moving every night are not a change, so the undo is not refused after the next Sleep), puts them back on their line and marks the page `apart` for the mention. Before anything is written it checks that every claim has a held line with room (a line promotion or a take released refuses it, 409, never a fact written nowhere) and afterwards that the held count is whole, else every path goes back. A page's one landing never takes two values of one single-valued predicate (checked against the claims accepted earlier in the same call), and a failed commit puts back the page, its claims ledger (a file the write created is removed), the held lines and the record; the commit is authored `cicada` with the engine as its trailer. Where it runs: Sleep's tail after the question revisit, once per drain, at most 25 groups of conversations had in the last three days and 25 older ones, the groups whose candidates are read most first (`page_reads`). Out of scope: renaming labels, key facts, persons. Cost: two calls a group when a reading names a candidate, one when it says none; on the battery 1.1 calls a claim (49-50 calls for 44 claims, every claim alone in its group), and one call a reading for several claims gave the same answers as one claim a call at half the calls. **Measured** (`benchmarks/consolidation/described_landing.py`, invented names, 50 claims in 46 cases: 17 must land, 33 must stay held, 16 of them refused by the code (a tool or a concept page included) and 17 by the reader): a reader rigged to always name the same candidate (first or last by name) lands 0 of the 16 and all 17 of the reader-only traps, the honest size of what rests on the reader; always none lands none; haiku on the plan 14 right, 1 wrong, 3 missed, 32 rightly left. The dry run `benchmarks/consolidation/described_landing_bank.py --read --eyes FILE` writes nothing to the bank, prints one line of ids per claim that would land, is resumable (`--max-reads`, `--cache`), and writes the words (the claim, the copied sentence, the label, the page; a sample of 40 held claims with the reason) only to a file the owner names outside the repository.

**Saves alone make no page and no mention (G245, owner 2026-11-24, ruling 80; `promotion`, `episode_time`, `quiet_pages`,
`media_ingestor.inject_media_edges`).** "If I save it, it already has a reason" means a save is read (Track 1); this is what
keeps a pile of them from becoming a pile of pages. A save **with no words of the person's** is one with none of
`history_index.PERSON_KEYS` (`has_note`, `saved_why`, `saved_why_earlier`, `readable_by_folder`: a reason, a why-answer, a
note, a folder reason; `saved_reading.no_words_of_his`, read from the record alone so the card, Sleep and the 2+ rule agree
and a feed item keeps ruling 39's own rule). Talking about a save (`read_asked`) is a conversation of its own, never words
in the save.
- **One source for the 2+ rung.** `promotion.conversation_keys` gives every such save the one key `promotion.SAVES_KEY`:
  two saves naming one thing, or fifty, make no page; one save plus one conversation do, and the page keeps both sources. A
  save carrying the person's own reason, note, why-answer or folder reason keeps its own key and counts as a conversation
  **for what his words name**: his reason on a post is about that post, so for a name only the post's text carries it still
  counts with the other saves (`promotion.conversation_keys(..., names)`: the page's name and aliases, tested against his own
  sections folded and with punctuation collapsed; the four promotion sites in `entity_resolver` pass them; `Saves.of` / `all_of`
  and the held-name checks take them the same way, `promotion.labels`). A caller with no name keeps the old key.
  No other rung can fire from a save alone: `substantive` needs the person's own exchanges (a save yields none outside
  their sections) and a link only counts from a relationship located in their words (`person_said`).
- **No mention.** `episode_time.counts_as_activity` is false for such a save (the bank-wide `untimed_ids`, the card's
  `untimed_among`, whose one awk pass and line reader now read `episode_time._KEYS`, and Stage 1's `untimed` agree). A page it
  creates starts its silence clock the day Cicada learned it (`decayed_through`, no `last_referenced`), a page it names keeps
  its last mention, status and confidence, and it is no week, no said-day and no conversation for decay. Its claims are still
  dated by the post's own day (`valid_from`). **Chosen, not built (plan 1.2):** "touch a page that has other sources at the
  post's day, at most once a day" is not implemented: the update path ties a mention to the decay watermark (`learned_on`,
  `decayed_through`, the read-late mark), so a half-touch would desynchronise them, and a stream of strangers' posts would
  keep a page alive. The rail line "a save is no mention" is the simpler and safer reading; revisit on a measured loss.
- **Quiet.** A page whose only evidence is saves is quiet (`quiet_pages`, derived); a tab group holds no page link, so
  `episode_kind` now calls `source: tab-group` an import too, which makes its page quiet and keeps a group out of the
  conversation rungs (Contacts card, connection) that asked for one. **A saved post that earned its page (G246,
  `saved_posts`, behind `HIDE_POSTS`, off) is not dimmed and the inbox may ask about it** (`quiet_pages.page_is_dimmed`: the
  node's `quiet`, the card's and the inbox's); the mention readers keep `page_is_quiet`, so a note he gave a post still never
  counts as a conversation that lit its page. A list's own page (`media.kind: list`) is never quiet.
- **A link from a save's page** (`inject_media_edges`, amends ruling 56 for this edge only): the media page's `about` edge to a
  page Sleep resolved from the save is made only where the save's own text states that page in full, its exact title or an
  alias as whole words (`saved_reading.named_in_full`; never a first name, the link's address, or a name under three
  characters), at most five per save, in the order the text names them. Any other episode a media page rests on (a
  conversation about the link) keeps the rule it had.

**A skill takes two conversations by either door (G239, ruling 65).** A note's lines are all the person's own, so a
phrase Stage 1 typed `skill` and linked to any page got one from a single note. A Stage-1 skill now waits in the index until
a second conversation names it; the one-conversation rungs do not apply to it. Stage 4 keeps `skill_hold`, and its prompt
now asks for what an agent could follow to work the way this person does: "relationship patterns" (what comes up together)
wrote "<x> as the hub for <y>" pages, grounded on any two notes naming one of their pages. Stage 1 is told a name is a name,
and that what someone does, said as a phrase, is a fact on whoever does it.

**Sleep never makes a project (ruling 56, 2026-11-04, amends ruling 36 D4; `api/services/project_birth.py`).** A project
starts only from the person or an agent on their ask (`project_ownership`). A `project` mention with no page takes the
fallback path below, and Stage 5 turns any `project` create into the concept, whatever a merged payload says. What Stage 1
reads is a **signal**, recorded as `born` and never acted on: it computes, on the conversation it read (no model), a
`project_birth` record and drops any the model's JSON carried. The person's own words clear the promotion bar, a
repository alone never does:
- **repo** — the episode is a harness session the hook observed in a git checkout (`workspace_identity` with a
  `family_hash`, bound to the stored `project_dir` by its `cwd_hash`; G110 D2), and the mention's name or an alias,
  folded (case, accents, punctuation), is the checkout's folder name: the last component of `project_dir`, or the one
  before a `.worktrees`/`worktrees` folder. Read from the two stored strings only — the backend never opens, stats or
  runs git in the path. **The remote, hashed (ruling 22 D2a, 2026-10-29):** when the hook's observation carries
  `remote_hash` (its origin URL normalised and salted per install; the URL never reaches the backend), the birth
  records it as `born.repo.remote`. A remote proves the same repository, **not the same project** (a template
  cloned under a new name, a fork whose origin is the upstream). Stage 2 finds the one project page whose repository
  has that remote — its own `born.repo.remote`, or, for a page born before the remote was read, a remote a later
  session in its `born.repo.family` carried (`project_birth.remote_sessions`, the cached frontmatter index). Only a
  repository's CURRENT remote counts (the one on its latest session, `project_birth.current_remotes`): a project
  re-pointed from a template to its own repository no longer answers to the template. It joins that page before the
  judge only when the page's repository points at the remote now AND the new folder's name, folded, is the page's
  repository name (the same repository moved or cloned again). A different name — a rename, or a template reused
  for a new project, even after the old checkout went quiet — or a remote the page only once had brings the page to
  the judge as a candidate (the W2 precedent) with a note that both share an origin, and its "different" stands
  (`entity_resolver._same_repository_candidate`; two pages on one remote join neither; a pair the person said were
  different is never joined). Project activity and conversation ties never follow a shared remote by itself, Cicada's own `how: origin` link
  included; only a repository the person or a trusted agent named on the project ties by its remote (ruling 56,
  `github_repos.named_urls`)
  (`_Bank.page_repo_families`): they follow the page's judged identity — its born family and a checkout whose folder
  name folds to one of the page's names or aliases. A rename the judge called the same is merged with the new name
  as an alias, so its sessions count; a reused template judged different lends the page nothing. A page born before ruling 22 D2a whose repository was renamed before any later session
  in the old folder carried the remote is not recognised — nothing is rewritten to recover it.
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
same as a fallback page lands on it (`_candidate_types` lets a project mention meet the page at the judge) and stays a
concept; one that carries a signal rides to Stage 5, which records it as `born` once (`project_birth.note_signal`). Only
the person or an agent on their ask makes **the same page** the project (`project_birth.start_page`, which keeps that
`born`, so the page's repository still ties its sessions). Every project mention with no match is weighed against every
project and fallback page (`_settle_unborn`: aliases count, no shared word needed, the judge decides, a rejected pair
never brought), so "Canoe restoration" lands on a page named "Hull build project" that lists "Canoe" instead of minting
one beside it (review of #441).
"A project" is the type the create will write (`_written_type`: a sibling's `project` overrides a `concept` when the
payloads merge), never only the chosen mention's (W4). A project mention with no match whose recorded alias names
exactly one project page — on disk, else born this batch — brings that page to the judge (W2): "same" makes it the
page's update, "unsure" asks the person, "different" or a pair the person rejected leaves it a held mention. An alias
brings its page to the judge, never a decision (owner 2026-10-08).
**Related is not the same (owner 2026-10-29, G21; `entity_relations`).** The judge answers `same`, `different`,
`unsure` — or `related` with a `relation` of B (the name) to A (the page): `part_of`, `has_part`, `made_by`, `makes`,
`alternative_to`, `version_of`, `has_version` (both prompts, both structured-output schemas). A part, a product, an
alternative or a version is never `same` and never `unsure`; two people are never related (a person's `related` reads
as `different`). A related verdict is no match and no question: the name goes on by the usual rule, and Stage 2 returns
the relation (`resolve(...)["relations"]`) as a Stage-1-shaped relationship that Stage 5.56 writes as ONE claim on A's
page — `includes`, `part-of`, `creates`, `made-by`, `alternative-to`, `has-version` or `is-a`, B its object by id (or
its slug while it waits, never a held endpoint), observer `agent`, origin `sleep`, `epistemic: abductive` (an
inference, never a stated fact), evidence the conversation as `reasoning`. **One pair is never both** (review of #545):
a pair the batch asks about or holds as possibly the same — `_never_cleared`'s close spelling with a shared alias
included — writes no relation. **A direction guard** (`entity_relations.plausible`, no model): when one name carries the
other's whole name ("<x> Head", "<x> Cloud" beside "<x>"), the longer is never the line, whole or maker of the shorter —
a relation saying so is dropped (no claim, no question), here, in a landing and in a check's answer. **A part of a project lands on it** (`_settle_unborn`, only when nothing came back `same` or `unsure` — unsure about one page holds and asks, whatever another page read as): a project name with no birth the judge calls a part,
feature, stage, task or pull request of a page is that page's mention, as the owner's canoe rule says ("a canoe, its
hull, the hull build — is one thing"), its own other names never the page's aliases — never "Is <feature> the same as
<project>?", never a page competing with it (measured 2026-10-29 on a copy of the owner's bank: 74 of 160 open
duplicate questions were a project name with no birth asked against a page). **A part lands only after a second reading (2026-11-24, G148; `part_landing`):** one `part_of` answer from the small pair judge is no longer enough. Measured by replaying that judge's own call on stored inputs: a kitchen renovation said to be "a separate job with its own budget" was called a part of the person's flat renovation in another city in 7 of 8 replays when it was weighed beside another page, and in 8 of 8 once Stage 1's one-line summary of it had lost the words "separate job" — the small model reads what such a part usually belongs to, not what the words tie it to, and its summary of the part drops whose house, which town, its own budget; the engine's main model read the same inputs and called none of them a part (0 of 12). So before a name lands on the page it was called a part of, the engine's main model (the same engine's main tier, as the same-name review's second look) reads the part's own conversations beside the page and answers `part` or `no`. Only `part` lands it. Any other answer, an unreadable one or a model that fails leaves the name its own — held or born by the usual promotion rule — and the judge's cached verdict reads `different`, so no `includes` claim is written on that page for a pair the second reading refused. It runs only for a name the judge already called a part of a page (`_part_confirmed`), never on every name; a part verdict beside a `same` or `unsure` match is scrubbed the same way (never landed, but no `includes` claim for a part nobody confirmed). Measured on the plan: the reading accepted 0 of 30 asks about a wrong whole and 24 of 30 about a right one (the six it refused included a hull judged a part of a canoe whose conversations the bench had dated a year apart); in real Sleeps of the eight reference stories it agreed to all 28 landings; it fired 0 to 2 times in a Sleep of 24 conversations that had few parts and 6 to 10 times in one of 22 conversations made of parts, about 5% of the Sleep's calls. What it does not fix: two names the small judge calls the `same` thing (a second kitchen joined to the first, a manuscript to a thesis) are still one answer from that judge. **The judge may read the pair backwards (2026-11-24, `_wholes_called_parts`):** on the consolidation benchmark on a key, a trip's flights (a name with no page) beside the trip's page were answered `has_part` — "the page is a part of the name" — in the 2 of 3 runs where Stage 1 named them apart, in 0 of 6 earlier runs; the second reading never ran (no main-model call in that batch's ledger), the flights stayed a held line of their own, and the trip's page was written "part-of" them. So when nothing matched, a `has_part` answer about a page is put to the same second reading, once; its `part` lands the name and the judge's relation is not written, its `no` leaves the judge's relation as it was (the reading is asked about one direction, it does not overrule the other). It fires only on a `has_part` answer about a name with no page. **A part and its whole named in one batch are one page (2026-11-24, G148;
`_related_unborn`):** when the pair judge calls a name with no page a part of another such name this batch (or of a line an
earlier batch parked), or the whole of it, the two are one group. Before this a relation between two names with neither on
disk had nowhere to be written (`_judged_relations` skips such a pair), so they became two pages with nothing between them
and the part's later progress ("the hull is fully stripped") never reached the canoe's page. The page is named for the whole:
a part never names it, and a part's own names are never its aliases (`_Unborn.part`). A part the pair judge reads as
`different` for lack of evidence (an "onboarding flow" that names no app) is still its own name: a placement over the whole
list of the person's things was measured and dropped, because it also joined a restoration with another restoration and one
kitchen with another's (a wrong join is worse than a missed one). `benchmarks/consolidation/reference_by_part.py` is the measure: its two
fixtures (stories and counter-stories) and the one-story `reference_by_part_canoe.json` this case was measured on (later progress on the whole's page in 1 of 6 real Sleeps before, 6 of 6 after). **An organisation/tool alias lead** (G209,
2026-10-27: a page that lists another page's name as an alias) now meets the judge once before it is asked; only `same`
or `unsure` asks, a relation is written as above. Any other verdict (a relation, `different`, a rejected or related pair)
also proposes removing the alias behind the lead (`wrong_aliases`, a `page_edit` the person applies or leaves —
`storage.md`): on the bank copy 21 of the 160 open "same?" questions were org/tool alias leads, 14 of them judged two
things. No call for a lead whose pair the person rejected (never asked again), whose question is already open (bumped, as before) or that this process already judged on the same two page versions (a memo in memory, keyed by bank, pages and their files' modification times — never in a bank): on the bank copy 67 org/tool leads, 24 with an open question, so at most 43 calls in a drain's first batch that meets them all and none in its later batches, where before every batch could re-judge all 67. **The record remembers:** a pair one current claim already relates
(`entity_relations.known`: those predicates and `uses`, `depends-on`, `runs-on`, `integrates-with`, `implements`,
`hosts`, `contains`, `contrasts-with`, either page) is never proposed (`ClarificationManager.create`, never a person
pair) and an alias lead between them makes no call. A public pair the judge could not tell is the web check's
(`features.md`, "Settled by a check"). Cost: each judge prompt grows by ~1.36k characters (~340 tokens; one-pair 1,504 → 2,866, batch 1,691 → 3,099
characters before the entries); no new call on the mention path (the same
judge call answers); one call per new organisation/tool alias lead a batch meets, none once the record relates the pair.

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
  what comes before any such turn (a recorder's summary at a meeting's head, an agent's opening line, a page's own
  description) is no exchange at all (2026-11-03, the #579 review: it had counted as one, so a summary naming a
  project turned the person's three exchanges into four and promoted it);
  a document with no turn markers is the person's own writing, one exchange per paragraph — **except a saved item**
  (2026-10-29, `authorship.of`): its title, header lines and fetched description are the page's words and no exchange
  of the person's; only its reason or note section is (`evidence.PERSON_SECTIONS`) — **nor an agent's saved note**
  (ruling 50, `authorship.agent_saved`: a `cicada_save_episode` note is the agent's words, `assistant` throughout;
  Stage 1 is told so and gives its claims the agent as observer). The name or an alias (a
  person's first name too) must come up in more than 3 exchanges **and** in a person's own words at least once
  (`mention_exchanges`, `named_by_person` ride on the extraction; never written to a page).
- **An explicit link** is a relationship to an existing page at ≥ 0.6 (never the owner's) whose evidence is located in
  a person's own words (`promotion.person_said`: kind `user` or `speaker`) — not one only the model's answer made or
  one it inferred.
- **2+ conversations** counts the batch's and the pending line's conversations together, so a resumed conversation
  read again (G104) is not a second one. An agent's saved note counts as the session that saved it, and one with no
  session as none (ruling 50, `promotion.conversation_keys`, like ruling 43's memory notes): three notes one agent
  saved in one session are one conversation.
- **A waiting Contacts card (owner ruling 2026-10-20)** is a fourth rung, on its own: a `person` mention **the person
  made in their own words** — Stage 1 measured it `named_by_person`, in a conversation (not a save, a watch or Cicada's
  own check — `quiet_pages.episode_kind`), and the card's full name stands in one of the person's own *marked* turns
  (`user:` or a meeting's `speaker:`; `_said_in_person_turn`). So never an agent's reply, a relayed connector turn
  (`evidence_kind: assistant`, ruling 32), a body with no turn markers (which promotion reads as the person's own
  writing: a note; a feed item or other save is the page's words since 2026-10-29), a tab group's titles or a calendar entry (`CARD_REFUSED_SOURCES`, review of #391) —
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
  **Once the thing holds its application, any conversation's owner lines about it move (2026-10-29).** The move used to
  run only in a conversation that itself showed the act, so the agent's saved notes, a texted reminder or the person
  mentioning the event later wrote "<owner>'s application to [[X]] lists …" back onto the owner's page (the vetted
  re-run found such lines for an event whose page and status already existed). Stage 1 now also moves the owner
  extraction's lines **about the application** (the act and the paperwork: applied, registered, signed up, enrolled,
  submitted, the application, the form — `application_page.ABOUT_APPLICATION`) that name a thing whose page holds an
  open, **not final** status (`value-of-application-status` other than accepted, rejected or attended;
  `application_page.standing`, read once per page per extraction, only for names the owner's lines mention). The
  owner's own life never moves: "joined <company>", "started a job at <company>", "lives next to its office" stay on
  the owner's page whatever the page holds (review of #548). No new status or birth is written without an act, and a
  thing with no page keeps the lines.
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
**A held name meets the pages its own batch creates (G148, 2026-11-23; `entity_resolver._join_held_to_creates`).** Stage 2
decides the most specific name first, so "Halvard Analytics" said once was held before "Halvard" said twice became a
page, and a held name was never a candidate for a later one: the claim about the long name kept an id with no page and
a job change closed only the other (`benchmarks/consolidation` U1, every model). After the loop, each thing this batch
held — never a person, whose joins keep ruling 74 — is judged once against the creates it shares a word or an alias
with, by the same judge and cache; only `same` folds its mentions and line into that page.

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
- **A linked account is a lead.** A profile link on a person page (`x.com/<h>`, `github.com/<h>` but not a repository
  under it, `instagram.com/<h>`, `linkedin.com/in/<h>`, in `sources:` or in the body; a `/status/` post link only in
  `sources:` — one written in the body is a post BY that account the subject shared, never theirs,
  `person_leads.account_links`, owner 2026-11-04) makes a new person name equal to that handle a question, never a
  page: the name parks as a pending line, and the question context names the account. A handle is never derived from a
  name; it must already be written on the page.
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
- **A person met only in saves joins a page on an exact name or alias alone, and asks nothing (G245, ruling 80's plan, Track 2c;
  `saves_bounded`, `entity_resolver._from_saves_alone`).** A person's name every conversation of which — this batch's and
  any an earlier run parked it from (`PendingEntity.episodes()`) — is a saved item with no words of the person's about it (no
  `## Why it was saved`, `## Saved because`, `## User note`, or a person's `## Note` that names it: a reason that does not
  name the person is about the post) skips the judge, the first-name-across
  rule, the same-name planning (`_plan_same_name_people` leaves a save's mention out) and the G209 "account" lead. It joins
  only the page TITLED exactly so, or the one person page that lists it among its aliases (`_exact_person_match`; the guards
  of the direct match stand: a recording's page, a name two pages answer to, a page the person said it is not): a post's
  "Sam" beside the page "Sam Example" matches neither, writes no alias, fact or source there, and is held. A bare name that is
  a page's whole title still joins it: that page IS named so. The held name raises no "who is this?", no "same person?"
  (`_held_alias_questions` skips a line only saves named) and no lead question, and keeps at most 3 held claims
  (`storage.md`, "What a save may add"). A single conversation of the person's own — now, or in the line an earlier run
  parked — makes the name theirs and every rule as it was. Counted as `saves_names_held` (names only saves carried that no
  page took) in the run's report.
- **A held full name meets the page its given name titles (benchmarks/newuser 2026-10-23).** A held name with no alias
  that names a page asks the same question when it is a full name as written (two to four capitalised name words, no
  handle, digit or parenthesis), it has no page of its own, and its given name (folded) is the whole title of exactly
  one person page while no other person page's name begins with that word (`_given_name_pages`): "<given> <surname>"
  held beside a page titled "<given>" asks; two pages for one given name ("<given>", "<given> <other-surname>") ask
  nothing. The owner's page and a page titled by a relation (`role_people`) never count. Same cap, same
  `merge_rejections`, never a merge; the card says the conversation named the full name and the page carries only
  the given name.

- **A number in a chat (ruling 55, behind its switch; `storage.md`, "Phone numbers").** With its switch on, the person's own new
  lines hold a token instead of a redaction (`phone_numbers.tokenise_batch`, before the stager, in both chat ingests),
  for a phone word tied to the digits, an "add" or "save" with a capitalised name at 9+ digits, a change said with a phone word, or a run of 9+ the vault
  already holds; an agent's reply, another speaker's line and a forwarded message are redacted only for a phone word somebody owns or a run of 9+ the
  vault holds. Any other run stays, "Ana N" and a line of only digits included (`storage.md`). A stored line never moves: a stored sitting is rebuilt from its body, and a line posted again keeps its
  stored words, so turning it on re-reads no old chat. Stage 1 gets a note only when the conversation holds a token;
  `phone_numbers.take` keeps an entry only on the person's own located line and takes every token out of the prose.
- **One person across sources (owner 2026-10-28, `contact_identity`).** Stage 1 marks a `person` entity of a chat
  sitting whose name or alias folds to exactly one participant (a group member or a one-to-one chat's person) that
  carries an address-book card (`contact_card`, never the model's). Stage 2 reads it before any name: the one page
  whose sources carry the card's ref is the match (a mention spelled otherwise in the chat lands there, a same-name
  page of someone else never takes it), and a one-to-one correspondent finds that page before `find_page`. With no
  such page, a waiting card is used **only once the usual rules promote the mention** — the page is then born under
  the card's name with its photo and sources (`WaitingIndex.by_id`); below the bar nothing is made (owner
  2026-10-20). Never the owner's card or page, never a relation-only mention.
  **LinkedIn rides the same birth (G245, owner 2026-11-24).** The kept LinkedIn connection that matches a person being
  born attaches in that write, and a waiting card and a waiting connection of one full name are one lead — the page
  born from the card has both. A connection alone never promotes; one full-name mention of one does (its link proposed);
  see *LinkedIn connections* above.
  **A first name heard elsewhere is asked, never joined.** A one-word person name heard outside a chat (a harness
  session, an export, a note, a calendar entry) that begins exactly one full-name person page heard in a chat —
  on disk or born this batch — is never joined on the first name: a judge's `same` or `unsure` becomes the question,
  and a held one asks after the loop (`_held_alias_questions`, `_full_name_pages`). The question records where each
  side was heard (`heard_in: {mention, page}` — words, never ids; a chat is an origin in `chat_live.CHAT_ORIGINS`,
  and the other side is worded by the origin its source really writes: a harness or chat export by its app,
  `apple-notes` "in your notes", the Telegram bot's `telegram` "in a note you sent yourself", `calendar-local` /
  `calendar`, `reminders-local`, `notion-export`, `wispr-flow`), and the inbox says it in the owner's words:
  "Is the <name> in your group chat the same <name> you talked to Claude about?" (`inbox_wording`). A model's trailing
  note on the name ("<name> (unnamed surname)") is ignored for this. Seen on haiku through the real doors
  (`/sources/messages/sync`, `/capture/turn`, Sleep, `GET /inbox`), synthetic chat and session, 2026-10-29.

**A first name joined to the person who newly appeared the same week (G245, owner 2026-11-24: "yes ofc join. and this should
happen accross sources (even chats, conversations, etc)"). Sleep decides and reports; it writes nothing yet.** He met people at
an event, connected with some that week and wrote a few first names in a note. A page titled by one first name
("<given-a>") and the one person who newly appeared the same week ("<given-a> <family-a>", a LinkedIn connection or a
waiting Contacts card) are tied together by Sleep itself, undoably, on two independent kinds of evidence: the NAME (the first
name is the given name of the full name) and the TIME (both first seen within seven days of each other). Name alone never
joins (ruling 74); time alone never does. The code is `arrival_join` (the decision, pure, and the nightly step) and
`arrival_join_write` (what it would write, its record and "Not them"); the step runs in the engine-independent tail after
74a's review and 74b's join and before the catch-up proposers, the write (when it is live) is its own `cicada` commit before
the rematches attach, and a last step records which commits it caused after both rematches.
**It ships `arrival_join.LIVE = False`: every rule runs every night, nothing is written to the bank, and the reading is left
outside every bank for the coordinator** (`$CICADA_HOME/people/<bank>/arrival-join-report.json`; the command
`python -m api.scripts.arrival_join_report --bank <memory> [--run] [--names]` prints it per item: page id, both days, the gap,
each directory's freshness stamp, every namesake row counted by hash, the conflict and veto answers, the decision and its
reason). A one-line change flips the constant, only on the coordinator's reading of the real bank: the rules are checked on
a synthetic battery (`benchmarks/consolidation/arrival_join_battery.py`, a regression net, not a measure) and on the real tail
(`arrival_join_e2e.py`, `LIVE` forced on in the test only), but a rule written with its own test scenes measures only the
author's picture of the world.

*When it joins* (`arrival_join.decide`, in order; the first failure is the counted reason, never a name):
1. not a demo bank, the tree readable, the page not dirty (the step's);
2. the holder is a person page titled by ONE word of three letters or more, not archived, not the owner's, not titled by a
   relation (`role_people`), not a second person of one name (`sam-2`);
3. the given name matches by token equality, never a nickname, a sound, a spelling or an alias; a compound given name is a miss;
4. exactly one holder: no other person page or held line carries the word as its name, an alias or the start of one;
5. exactly one arrival, counting namesakes. Rows of both directories collapse by folded full name (a card and a connection of
   one name are ONE lead); exactly one lead has a day within seven days of the holder's (inclusive: day 7 joins, day 8 does
   not), and no OTHER lead carries a day within 30 days of the holder's, a `week` or `month` precision whose range reaches that
   band, or no day at all with a profile link or a same-name ambiguity (`Connection.dup`). A dormant old namesake with no overlap
   does not block; any plausible same-season one does;
6. the arrival is waiting: no page holds its full name (in practice rule 4 refuses first);
7. no same-name doubt (`same_name_doubts`) and no history: a pair the person called two, an alias or a source they removed that
   names this arrival, their own "Not them" on this pair;
8. nothing already points elsewhere: no full-name alias on the page, no other profile, not in a candidate pair of
   `person_duplicates`;
9. the directory is fresh: looked at on or after the holder's day plus seven (the connections' freshness is the later of the
   export day and the last successful read of the list; the Contacts' is the last sync), else the join waits;
10. the conflict screen (no model): the page's current employer against the row's company, no significant word in common
    refuses (`fact_conflict`). A role that contradicts needs a reader of words and is the veto's, never a word list's;
11. the two-read veto, through the engine door 74a and 74b read through (`same_name_tend.main_engine`,
    `full_name_join.ask_main`, so a scheduled run reaches a plan only through the person's switch, a plan limit is a pause and
    the sensitive hold applies): two differently phrased reads each given the page's facts, the person's own words naming the
    first name and the row's company, position and headline (never its name, link or e-mail) must each find nothing that fails
    to fit one person; one doubt, one "unsure" or an unreadable answer is no join. An answer is cached outside the bank by the
    digest of what it read, so a bank costs one read pair per candidate, not one a night; at most six candidates a night.

*What "newly appeared" means, per source.* A LinkedIn connection: its `connected_on` day at `day` precision only (a `week` or
`month` row is never THE arrival, and blocks when its range reaches the band). A Contacts card: the day the app first saw it
WAITING (`contacts_local.first_seen`, kept outside every bank beside the waiting cards): the first sync marks everything seen
with no day; a later sync stamps a new card only when the previous sync was at most three days earlier and at most five cards were
new in it (a phone restore, an iCloud merge or a vCard import adds hundreds: none of them is stamped); a card that ever matched a
page is never stamped, so one that returns to waiting after a split, an archive or an undo is not new. An unstamped card is
dormant, never an arrival and never a blocker. The first-name side's day is the earliest day of the page's own conversations that
count as time (`episode_time`, never a save, a feed, a tab group or a calendar entry), by the conversation's own `timestamp`
day, never the day it was received or read. **A note** is dated by its CREATED day (`created_at` on its episode, sent by the app
beside the dump as `noteCreated`, Notes' locale-free local ISO time; an older app sends none, so a note it kept has no day) and
only when it was not kept alive past a week: a note's `timestamp` is its last edit, so a line added today to an old note never
makes the note look new. **A file of a watched folder** that is not a meeting gets no day either (its `timestamp` is the file's
modified time when first read and no revision moves it); a meeting is dated by its own day and the report says `meeting`. A page
with no day never joins.

*What it writes when it is live.* The join IS the alias: the arrival's full name is added to the page's `aliases` (one `cicada`
commit, trigger `sleep/arrival-join`, its own path only, restored if it fails; the title stays, no claim moves, no page is
made). The existing rematches then attach: an alias-only LinkedIn match writes the link with `match: alias`, never confident,
so no photo request leaves the Mac until the person takes it (`person_photo.is_own_account`); a card's sources and photo attach
through the Contacts rematch. The commit message and the record carry page ids, both days and the gap, never a directory row's
name, company, headline, link or e-mail. The page's frontmatter keeps `arrival_joins: [{id, alias_key (a hash of the folded
name), refs (the rows' hashes), days, delta, state, commits, claims, sources (a hash of each link)}]`, so a handed-over or moved
bank keeps its undo.

*"Not them"* (`POST /entities/{id}/arrival-join/undo`, on the connection's row and on the page's History row): in one commit
set the name leaves through the removed-alias record (`aliases_removed`, so no automatic writer adds it back), the LinkedIn
link through its tombstone (`sources_removed`) and the claims it wrote are closed by id, the Contacts entries leave through the
refusal rows (`_contacts_rejected.yaml`) with the face, and the pair is refused: against the page of that name when one exists,
else by the holder and a hash of the name in `_merge_rejected.yaml` (`merge_rejections.arrival_refusals`, `refused_by_name`).
The commit carries `Undoes: <sha>` for every commit the record lists. If the person changed the name or took a link since, it
writes nothing and says which name, link and claims remain, each by id. The nightly refusals step (before the same-name
review) turns each refusal whose name now belongs to a page into a refused pair of pages, which every other joiner already
honours. The count of `undone` records is the live false-join measure.

*A first name still held below the promotion bar (Route H, `arrival_birth`, G245, ruling 79 (c)).* The owner's own example: a first
name written once in one note normally has no page, only a line in the pending store (`pending_entities.jsonl`), so the page route
above never sees it. Each night the same step reads every held one-word person line with a namesake in a directory as a case of
the same list, and `arrival_join.decide` applies every rule to it unchanged (two namesakes, a stale directory, a conflict, the
two-read veto, a doubt, a split, a relation title, the owner's own name, a full name already on a page); the veto draws on the
same night's bound (`MAX_VETOES`) and the same cache. What differs for a line: its words must be the person's OWN in a
conversation of its own day (a marked turn of his, or his own unlocked note by its created day; never an agent's reply, a relayed
turn, a save, a tab group, a calendar entry or a feed item), several own conversations more than a week apart are a name that has
been around (no day), and a second person of one name (`title`), a name held against a page, one the person said is none of those
pages, a message correspondent, a self-reference and the owner's given name are never holders. It runs in the tail rather than in
the resolver where a name would be held because the directory must be looked at a week after the name's day: at the moment a name is
first held it is never yet fresh, and the join would wait for a second mention, which promotes the name anyway.
**It ships `arrival_birth.LIVE = False`, a switch apart from the page route's:** nothing is written and the name stays held exactly as
before; the report (`arrival-join-report.json`, version 2) carries the decision as an item marked `"route": "birth"`, `would_birth`,
a held name keyed by a hash (`held-<hash>`; the command prints it with its words only under `--names`, to the terminal). Live, the
page is born in ONE `cicada` commit (subject "Arrival join", trigger `sleep/arrival-join`) under the arrival's full name through the
promotion's own page writer, the said form kept as an alias, a LinkedIn connection of the lead attached in the same write and only
proposed (`match: alias`, never confident, no photo request), the line's words and credits on the page, its held claims landed on
it by the path a person's own "this held name IS that page" takes, and the line out of the store; a Contacts card attaches through
its rematch. The frontmatter record is the page route's with `birth: true`, a hash of the said form and the conversation ids.
*"Not them"* (the same route and record) ARCHIVES the born page (`status: archived`, `archived_by: {reason: arrival_birth, prior_status,
prior_confidence}`, `removed_at`; the commit is in git), takes the said form off through `aliases_removed`, the proposed link and
the claims it wrote as the page route does, puts the held line back as it stood in the commit before the birth (read from the
bank's own history; without it nothing is written), and refuses the pair (`merge_rejections.add_rejected` of the held name and the
page, which the resolver's `_said_different` and every other joiner honour). It writes nothing and says what is left when the
person changed the name or took the link, or when the page has heard another conversation since.

*Out of scope here* (later tracks): two pages (ruling 74's machinery gaining time as a third kind), nicknames, and chats and meetings
as the full-name side.

**What a question between two people rests on (owner 2026-11-04, `pair_evidence`).** "Is <handle> the same as <owner>?"
reached the inbox at "Cicada's guess 0.90" with a chat with someone else, naming neither, as its evidence ("why tf would
<handle> be me?"). Measured on a copy of the owner's bank (real values redacted): a link to a post BY the handle,
written on the owner's page, read as the owner's account; `leads_for` fired whenever any conversation matched the
owner's page, so the question took that conversation; and the guess was the matched mention's extraction confidence.
Three rules, read by every producer through `ClarificationManager.create` (and by Stage 2 before it holds a mention:
a question that may not be asked holds nothing back — the name goes on by the usual rule, `_unaskable_pair`):
- **The owner's page is never paired with another person** without the person's own words naming themselves by that
  name or handle: a located line of their own turn ("I'm <h>", "my handle is <h>", "soy <h>", "me llamo <h>" … the
  name ending the phrase; never an agent's words, never "<h>'s fan"), or the name/handle they gave Cicada for
  themselves (`owner.json`) — `self_named`. A link, an alias Sleep wrote or a shared word is not that.
- **The evidence names both sides:** one conversation naming a spelling of each (name, aliases, the mention as said,
  whole words) — the item's own, then each page's own conversations, then the lexical index — becomes the question's
  `source_episode` (`pair_episode`). For two people none means no question. A question the record raises with no
  conversation (`role_people`'s one-at-a-time relation) is exempt, and so is a first name heard in one place against a
  full name heard in another (one person across sources, below): its evidence is the two conversations, said in the
  question's words (`heard_in`). An older card whose own conversation names neither
  shows one that names both, derived on read (`InboxContext._pair_episode`: each page's six newest conversations,
  then the lexical index as it is, never a wait).
- **"Cicada's guess" is about the pair** (`guess`): each lead's base (`BASE_GUESS`: a named handle 0.8, a profile 0.7,
  an alias 0.6, a given name 0.5, the judge unsure 0.5, a first name across sources 0.4), never above 0.8 — below
  ruling 29's act threshold (0.9), since a question exists because Cicada cannot tell — and never above 0.4 when no
  conversation names both (a thing pair is still asked then). An older card's guess is shown capped the same way.
Sleep retires the open ones that should never have been asked (`inbox_tend`, `owner_unsaid`, `no_pair_evidence`,
engine-free, nothing written but the record, undoable under "Settled by Sleep").
Measured on the copy (210 open "Possible duplicate" questions; dry run, nothing written): 1 paired the owner's page
(retired, `owner_unsaid`); 148 rested on a conversation that did not name both sides (145 named one or neither, 3 had
no conversation); 2 carried a guess ≥ 0.9. Of the 20 between people, 4 are retired (1 owner, 3 with no conversation
naming both) and 16 stay; their cards' conversation names both sides on 16 (10 before); 1 of them is a public handle
a check may answer
(ruling 54, `public_handle`, `features.md`). The other 190 are thing pairs: the plan's judge (haiku) called
125 different or a relation (not the same), 21 the same, 44 unsure — Stage 2's relation judge (2026-10-29) keeps new
ones from being asked; the open ones wait for Sleep's tending judge or the person.

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
  ("browser-use harness" / "browser-harness"). The inbox's question dedup asks the same rule since 2026-10-29
  (`clarification_manager._same_mention`): "<x>stack" / "stack", "GDPR" / "DPR", "G1" / "Go2" are two questions,
  never one the person answers for both. The entity then goes to the judge with the pages it shares a word with
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
refers to one thing consistently, so none of those is a reference. Since 2026-10-29 it guards **every automatic
writer of a new alias** through one predicate, `alias_policy.admits`: Sleep's update and create (`apply_changes`), a
page merge (the loser's aliases and name — "she" reached three person pages through merges that carried the merged
page's aliases unfiltered), an inbox answer folding a page-less mention, a relation page's nickname, a correspondent's
or a card's spoken name. Sleep also never adds an alias that is **another live page's own name** by id
(`alias_policy.names_another_page`, a file check): the two are either one thing — a merge question the shared name
already raises — or two, and the alias pulled the other's mentions over (284 such aliases sit on the owner's bank
copy; none is removed — they wait for the merge questions or the fresh consolidation). What a page already lists stays,
and the #249 alias index reads every alias as before; removing one is the person's edit (`cicada page edit
--remove-alias`, a pronoun included). A
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

**Every child run is held at the one door (ROR-139, 2026-11-07).** The same account leaked outside Sleep: a scratch
memory's Ask reply and a web search's query named the signed-in account's owner (reproduced; the CLI's `userEmail`
block reaches a child run under every pinned flag, and `ANTHROPIC_UNIX_SOCKET` is the only switch that drops it, so
it cannot be used). `agent_engine.complete` now checks each call's reply and every tool input (a search's query)
with `engine_identity.call_leaks`, against the request text it sent: a form the request did not say voids the call
(`EngineProtocolError`, one retry), so no caller needs its own floor and Ask and the settling agent are covered. The
check is by the address's forms and, at this door only, the **given name alone** (the first word before the `@` when
the part holds two or more; whole word, any case, kept when the request says it), the shape the leak took on a scratch
memory (second pass, 2026-11-08); the profile name is not read. A query already sent cannot be recalled, only its
results discarded: a name could reach a search before the check ran, which is why `CONTEXT_GUARD` says never to put it
in a query and a web lookup pins its query in the prompt and voids the answer on any other. **What reaches a child run
(probed on `claude` 2.1.319, 2026-11-08):** under the pinned flags, `--safe-mode`, `--setting-sources ""`,
`--strict-mcp-config` and `--tools ""` keep out `~/.claude/CLAUDE.md`, rules, auto-memory, hooks, plugins and MCP
(a child asked to list its context named none); what remains is the CLI's own `userEmail` block, the cwd, platform and
shell. No variable (`CLAUDE_CODE_USER_EMAIL` included) and no scratch `HOME` removes the email while the plan is
signed in, and `--bare` would move the call to an API key. `claude -p` is spawned in one place
(`agent_engine.complete` through `run_cli`), and `test_child_run_identity` fails if a spawn loses any of those flags
or `CICADA_CAPTURE=off` / `CICADA_RECALL=off`, or gains a key.

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
  declined. It rides the cycle's commit like every question the cycle opens. **Only on the second conversation
  (owner 2026-11-24: "someone known only by a description is not asked about on a first mention, only once they come
  up again").** `ensure_question` is the one place a name question is written (Stage 5.4 and the repair script both go
  through it), and it writes nothing until the page rests on two distinct conversations (`role_people.heard_again`:
  the page's `source_episodes` counted by `promotion.conversation_keys`, as the 2+ rung counts them: a session and its
  notes are one, saves the person said nothing about are one together). What was said is kept exactly as before (the
  page or the held line, its title, its claims, the nickname rule); only the asking moved. A question already asked from
  one mention is retired by Sleep with nothing written (`inbox_tend` rule `name_once`, "Settled by Sleep", undoable; an
  undone one is the person's and Sleep never retires it again) and comes back, new, when they come up again. A person
  who declined, a question the person put off, one answered: unchanged. The same holds for every producer: a relation
  ("your partner") and a nickname ("What's <nickname>'s name?") alike; a meeting's unnamed voice (`meeting_speakers`,
  "Who was Speaker 1?") is another question and is not touched. Whether a thing said once is still found by its words
  (an agent asking about "the Portuguese guitar teacher" with no page, no question) is measured in
  `benchmarks/consolidation/findability.py` (2026-11-24); see `mcp.md`.
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
  Paraphrases and more specific restatements fold only through the judged, code-checked step (`fact_fold`, *Facts keep
  their context* below) — never a word rule; with no engine they stay, a duplicate being cheaper than a lost fact. Used by Stage 2's same-name fold, every section
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
  orientation) — since 2026-11-23 the judged fold below takes the paraphrases (ruling 23's amendment).
- **A link in new text is written under the page's own name (`link_names`, G148, owner report 2026-11-23).** Stage 1
  reads each conversation alone, so it wrote `[[Girlfriend]]`, `[[<nickname>]]` and `[[<owner>'s girlfriend]]` for one
  person; Stage 2 resolved all three to her page, but the text kept the spelling — one page read as three people, equal
  facts stopped being equal, a link naming an alias drew no `mentions` edge (`wikilink_resolver` indexes names and ids)
  and the article writer narrated each spelling as a separate person. At the top of Stage 3 (`conflict_resolver
  .resolve_and_prune`, before any call reads the text) each `[[link]]` in a create's or update's Summary, Key Facts,
  History lines and Open Questions whose target is another spelling of ONE page is **rewritten to the page's name**
  (not piped: every reader unwraps a piped link to its display text, so a piped form keeps the spellings the equality
  check and the writer read; a link the writer piped on purpose keeps its display text, only the target moves). The
  source rows (`section_provenance.INPUTS`) carrying the same text move with it, so no row is lost; the person's words
  are the conversation's and the evidence spans point there. Only a resolution that is certain: exactly one non-dropped
  page answers to the spelling (name, alias, id) and the page's own name resolves back to that page alone (G227: a
  shared title is neither's), **and the spelling is scoped to that page** (`link_names.Scope`): a page holds generic
  aliases ("girlfriend", "partner", "she") that mean someone else in another conversation, and Stage 2 may have
  declined to resolve the very word (`role_people`: a relation-only person is merged only on the person's answer or
  evidence on the record), so a bank-wide match alone never rewrites. It does when (a) Stage 2 resolved that spelling
  to the page in this same batch (an extraction on the page's create/update was named so or listed it as an alias —
  a merged input's name is kept off the page in the transient `_said_as` key of `entity_resolver._merge_entity_payload`,
  never written), (b) the spelling is the page's own name or id in another case or spacing (never an alias), or
  (c) the page being written already relates to the target (its `related`, a link in its body under the target's own
  name — `## Related` included — or a claim naming it). Otherwise the link stays exactly as written. An unknown or
  ambiguous spelling stays as written, nothing is guessed from similarity, no page is renamed or merged. A plain mention with no brackets ("<owner>'s partner's favourite artist") is **not**
  touched and Stage 1 is not told the bank's names: that would send it names per prompt for a model's guess to use,
  and `role_people` already titles a relation-only person. Text already on a page is never rewritten (a bullet's
  rows are keyed by its words), so old bullets keep their spelling and heal only as the fold below takes them. The
  article writer (`entity_article`) is offered one name a page in LINKABLE and, when its inputs spell a page more
  than one way (the record on a page written before this), a `SAME_PAGE` list — only for spellings read inside the
  page's own neighbourhood (its own name or id in another form, a page it already relates to; never a bank-wide alias) — "`as` is another name of `is`" — with a
  rule to write it once under the one name and never as different people.
- **A fact a page already says in full is not added again (`fact_fold`, G148, owner report 2026-11-23; amends ruling 23).**
  The page-merge call was cut to the Summary and the new History lines (2026-10-24), so nothing folded a fact said again
  in other words: one artist's page held 16 bullets stating about 3 facts, and 3,073 Key Facts on 708 pages of the owner
  bank (53,680 on 4,302 pages) restate an earlier bullet (content-word Jaccard ≥ 0.6, a rough detector). A word rule that
  guesses is out (ruling 23: rule folds lost information); a judgement guarded by code is in, built as `value_alignment`
  is (#783). In Stage 3 (`conflict_resolver._fold_facts`, after the link rewrite and before any article or summary call,
  so a page that gains nothing new falls to the "re-read" gate) a page whose update brings a fact **no bullet equals or
  extends** gets ONE call to Sleep's small judge: the new facts and the existing bullets most like them (shared words,
  names, numbers — a bound on the prompt, never a decision; a fact that shares none, another language, is shown beside
  the newest bullets), asked per line which other line already says it **in full**, with the other names of every page
  linked in the lines listed ("Alice Example is also called Girlfriend"). Then **the guard (`fact_fold.covers`) no answer
  can talk past**: the dropped fact's numbers and dates, months and weekdays (six languages), negation and tense words,
  and every name it carries (a capitalised word, a link's target) must be in the line that holds it — the page's own
  names, the owner's and the other names of a linked page excepted; a proposal the guard refuses is never put to the
  second reader. **Who a line means is read in the page's own neighbourhood** (`fact_fold.People`, review 2026-11-23):
  a name — linked or plain, and the form "<owner>'s <alias>" — that is the name or an alias of exactly ONE page this
  page relates to (`link_names.Names.relations`, plus any page its own lines link under that page's own name; the
  owner's page and the written page itself left out) is read as that page, in the guard (both lines are compared with
  each such mention written as the page's name, and a neighbour the dropped line means must be one the holder means too)
  and in what the judge and the checker are told ("Mira Lund is also called: girlfriend, partner, Pip, Alex's
  girlfriend ...; on this page each one means that same person"). It is never bank-wide: "girlfriend" is read among the
  handful of pages this page relates to, two of them sharing an alias make it no one's (no equivalence), a page that
  relates to no one gets none, and a line that means another related page, or any number, date or negation the holder
  lacks, is still refused whatever the judge says. **A fold never loses a link**: when the dropped line links a page the
  holder does not (the link draws the graph edge and the page chip), `orient` turns the pair round if the linked line
  can hold the other (droppable, the guard passing that way, the second reader asked about THAT direction) and
  otherwise drops the pair — no fold. Links are compared by the page they name (a neighbour's id, whatever name the link uses), else by spelling. **The check**: one more call per page lists, per pair, everything the dropped fact says that the other
  does not; a fold needs the list empty and `same` true, and the guard again. What a fold does: the incoming fact is not
  added; an existing bullet a new one says in full is replaced by it (a machine page only — `extend_existing`, never a
  page a person edited, never a pinned correction); the dropped fact's G118 rows move onto the holder
  (`section_provenance.FOLDS`, in `merge_selected` and `refresh`), so the page still shows every conversation that said
  it. A pair that says the same both ways keeps the older bullet; a chain (a held by b, b held by c) is followed to the
  bullet that is kept and the guard and the link rule run on that pair too, so one line ends up holding every
  conversation's rows. Across writes it works the same way: a bullet an earlier write folded into another has moved its
  rows onto the holder, and when a later write folds that holder into a fuller one (an existing bullet replaced) those
  rows move on with it (`merge_selected`/`refresh` read `FOLDS` against the page as it stands). **Cost**: nothing for a page that gains no such fact; otherwise one ask and at most one
  check, at most `MAX_ASKS` (24) pages a batch (the pages gaining most first), `MAX_NEW` 12 new facts and `MAX_LINES` 40
  lines each, at most 24 pairs checked — so at most 48 small-tier calls a batch, and typically one pair of calls per page
  that was updated with a new fact. Small tier on the engine the cycle resolved (`judge_for`, the same bill as Stage 2's
  judge, never a metered key the person did not choose); refused past a metered key's spending line
  (`sleep_spend.LINE_STAGES`); never on the capture path. A cap, a cancel or any failed or unreadable call keeps what
  the writer did before. **Known limits, stated**: the guard's negation and tense words are English and Spanish, and a
  pair that differs only in a relation or a verb with no number, name or date ("favourite artist" / "favourite album",
  "has a sister" / "has a brother") is the model's to tell apart alone — measured below; a fact in another language folds
  only when its names are spelled as the holder's (Europa / Europe does not: a miss, never a loss). **Not covered:**
  History lines (dated, one event each: a repeat there is rarer and an event on another day is another event) and Open
  Questions (a question is closed by an answer, not a repeat); the same module could take them. **Dry run**:
  `api/scripts/fact_fold_dry_run.py` (read-only; per-item rows; `--judge` runs Sleep's judge on a bank copy, `--pairs`
  the invented pair set). **Measured** (`benchmarks/system/fact_fold_eval.py`, invented person, 7 conversations, haiku on
  the plan): 13 Key Facts / 7 favourite-artist bullets / 1 near-duplicate pair before, with links rewritten 13 / 7 / 3
  (the pairs are what the rewrite makes alike), with the fold 9 / 3 / 0, 12 judge calls for 6 updates, every date and
  name kept, all 7 conversations still shown as sources of the favourite-artist facts. **The reported page** (`--scenario
  page`: an artist page that relates to the owner's partner, sixteen conversations each bringing one line, the partner
  named every way — a link under her name, under an alias, an unresolved `[[<owner>'s girlfriend]]`, a nickname,
  "<owner>'s girlfriend's", "<owner>'s partner's"; invented names): 16 Key Facts before (15 stating the favourite-artist
  fact, 18 near-duplicate pairs); with the fold 5 (4 favourite-artist bullets, 0 near-duplicate pairs) when links are
  written under the page's name (#791) and 6 when they are left as written (the page as it was), the favourite-artist
  fact, both vinyl options, the planned gift and "he is a musician" kept, all 16 conversations still shown as sources of
  a kept line, 26-29 small-tier calls for 15 writes. Before the neighbourhood the same page went 16 to 13: every refused
  pair differed only in the name it used for her. A small judge varies run to run (three runs: 5, 8 and 6 Key Facts for the
  as-written page, 5, 6 and 5 for the rewritten one; the last run is the one with the prompt line below), so the count
  is a measurement, not a bound.
  The 18 invented pairs (`tests/fixtures/fact_fold_pairs.json`: reworded, shorter, another language, an alias; an added
  date or month, another month or number, a negation, another person, an added name, a plan for a done thing, artist for
  album, sister for brother; and, in a page's neighbourhood, a nickname, the owner's possessive and another related page)
  with haiku, 2 runs: 0 false folds of 12 a person would keep, 0 missed of 6 that should fold; the code guard alone,
  answered "yes" to everything, folds none of the 9 that a number, date, name, negation or another person tells apart.
  The ask also tells the judge to answer every NEW line first (older lines may only name a new one that says them in full):
  without it a small judge often answered about an older line and skipped the new one.
- **Two tightenings read off real pages (2026-11-24).** The second reader's prompt named no thing, so it listed the page's
  own name as missing when one line said it and the other left it out; it is now told what the page is about and that the
  two read the same. And the code guard gained a floor (`MIN_SHARED` 0.6, lines of `MIN_WORDS` 4+ own words): the keeper
  must use most of the dropped line's own words. Reading 36 folds proposed on a copy of real pages found one that lost a
  fact (a line saying all of a set was of one kind, folded into a count of that kind; shared 0.38) and one that lost a
  qualifier (0.50); every sound fold shared 0.67 or more. The invented pairs never showed it. A translated repeat is
  therefore kept by the guard: a miss, never a loss.
- **Pages written before the fold are healed once, by the person (`fact_fold_heal`, `api/scripts/fact_fold_heal.py`, G148;
  owner 2026-11-23: one-time, per-page result read before anything is written).** The live fold acts only when a write brings
  a fact, and one big ask under-proposes: the reported page replayed as ONE write of twelve new lines had the judge propose 7
  pairs, the second reader turn down 4, 16 → 13. So the heal **replays the page**: its Key Facts arrive oldest first,
  `CHUNK` (3) new lines an ask against the bullets that survived so far — the shape the incremental path asks in — through
  the live module's own ask, guard (`covers`), second reader and link rule (`orient`); a second sweep (`PASSES` 2) asks again
  about what the first left, only when the first folded something. A bullet that resembles no survivor (`MIN_OVERLAP` 3: a
  shared name or number, or three words, names read as the page's neighbours' — `fact_fold.People`) costs no call, so a
  page with none costs none; a translated line sharing no name or number is left (a miss, never a loss; the live path
  finds it only by showing the judge the newest bullets). Equal and word-for-word-extending bullets fold by the rule every
  write applies (`rule-equal`, `rule-extends`), never by a paraphrase rule. A page over `MAX_BULLETS` (300) Key Facts is
  left alone and counted (the resemblance test is quadratic; a page of thousands is a separate decision). **Two steps.** `plan` writes nothing to the
  bank: before the first model call it prints counts only — pages by why they are left alone, pages a rule alone folds,
  pages it would ask about, **the most calls that could be** — then (`--judge`, the Claude plan, `--model haiku`) appends one
  row a page to `<out>/pages.jsonl` and writes `review.txt`, most-repeated pages first, `--limit` pages, `--max-calls` a run,
  `--max-calls-page` (40) a page, resumable (a page already in the file is not asked again; a stop for a plan limit is
  exit 5). `--out` must be outside the repo and the bank: a row carries the line kept, the line dropped, the path
  (`rule-equal` / `rule-extends` / `judged` with the guard path, "turned round", "second reader agreed"), the conversations
  whose rows move, what the judge named and a later stage refused, and the page's bullets before and after; stdout never
  carries a word of the bank. The person strikes a fold or a page (delete it, `"strike": true`, `--skip-fold <page>#<n>`,
  `--skip-page`). `apply` makes **no model call** and writes exactly the folds the file holds, after `--check` (the same
  counts, nothing written): a page whose Key Facts changed since the plan (hash) is skipped and counted, never re-judged,
  as is a page a person edited or one dirty in git, and a fold the guard would no longer pass. **Loss-free by
  construction**: a bullet is kept as a holder only when G118's rows prove Sleep wrote it (as a holder a line with no rows
  could not receive the sources). **A line with no rows may be dropped into a sourced line that says it in full, and
  never holds one (owner 2026-11-24, amending 2026-11-23's "never dropped"):** the judge's pair is turned round when the
  sourced line can hold the other by the same guard, left alone when it cannot; the plan marks such a fold `unsourced`
  and apply refuses any fold whose kept line has no rows. The sample that asked for it: on the reported page 5 of the 9
  lines left after the first heal were such lines; a pinned correction is never dropped; a person's page
  is left alone; every fold passes the live guard and link rule again on the page's whole neighbourhood, and a line already
  holding others moves them on only when the new holder covers every one; the dropped bullets' source rows move to the
  kept line (`section_provenance.refresh`); only those bullets' lines leave the Key Facts section — the claims fence,
  History, Open Questions, the article and every frontmatter field but the provenance rows are as they were (a page write
  through the parser normalises trailing whitespace, as every write does). **Writing**: in process under write admission,
  `page_lock` and the git lock, like `repair_page_quality` (ruling 21a: it asks the backend whether Sleep is idle and refuses
  when it cannot say — exit 3 —, a demo bank is refused — exit 4); one `cicada` commit of only its paths, no `Cicada-Engine`
  (nothing ran an engine at apply), undone by a plain `git revert`. **Measured** (`benchmarks/system/fact_fold_eval.py
  --variants heal`, invented names, haiku on the plan): the reported page rebuilt as it is written today (16 Key Facts):
  16 → 5, 6, 6, 6, 7, 7 in six runs of the shipped settings (13-16 calls a run; 5 with one new line an ask, 30 calls;
  15 with twelve at once, 3 calls), every date, number, name and link of every dropped line in its kept line (a
  reader sharing no code with the guard), all 16 conversations still sources of a kept line; a 64-bullet page (eight facts
  said three to five ways, the rest one-off): 64 → 53 and 49 (21 and 19 calls, at most 40 lines shown an ask, no marker lost) —
  its second reader refused pairs that differ only by the subject's own name (5 of 15 refusals; telling it so, in a trial
  run, gave 64 → 48 with 3 refused: a live-path prompt question, not changed here); the invented pairs as two-bullet pages:
  0 false folds of 12 pairs a person would keep (four runs), 4 or 5 of the 6 they would let go folded (the translated one
  is the limit above; the judge's variance misses one more in two runs). **The article** above Key Facts repeats the same facts in prose: the heal never touches it (a healed
  page keeps its stamp — Key Facts is outside the stamped halves). Sleep rewrites it from the healed record when the
  page next gets an update that brings a source or a fact (one article-writer call, in place of the synthesis call), or
  on demand with `rebuild_page_articles --rewrite --entity <id>` — one call a page at the engine the person chose; on the
  16-bullet page its prompt goes 4,951 → 3,780 characters after the heal.
- **A memory written before two 2026-11-24 fixes is swept once, by the person (`value_sweep`, `name_sweep`,
  `api/scripts/value_name_sweep.py`, G148; owner 2026-11-24, a tentative yes to both).** Two fixes work only from now on:
  a value pair the small judge refused is read once more by the main model when the NEWER value arrives (#840,
  `value_alignment.align(reread=)`; a pair refused earlier is never looked at again), and a person written
  `Name (qualifier)` is a mention of the bare name (#846; a line already held under the qualified title stays so). One tool,
  two passes (`--pass values|names|both`), the heal's two steps: **plan** writes nothing to the bank, **apply** makes no
  model call. Never run by Sleep, never by an agent on the person's memory. **Neither pass joins two people, and the names
  pass never calls a model.** Reviewed 2026-11-24 by an independent run with a judge rigged to always join; every case it
  found is a test (`api/tests/test_value_name_sweep.py`).
  - **Values** (`--judge`, the main model, at most `--max-calls` calls). For each page with two or more open values, every
    value that has an OLDER one of its slot, worded differently and saying a different thing, is shown as NEW to the main model
    through the live module's own second-reading prompt, proposals and check (`value_alignment.REREAD`, `proposals`,
    `confirmed`): a join needs both answers, as live. Before the check, code refuses what the live path's rails refuse and the
    row says which: a value's date less precise than a day (a month sorts before a day in it, so which is newer cannot be
    told); the newer not dated later; **the dates and the days the values were said disagree** (the day is the conversation's
    own, from its `ep_YYYY-MM-DD_NNN` id; a value dated 2025-06-01 but said on 2026-11-28 is never closed in favour of one
    dated and said 2026-11-01); one conversation stated both; a person's own edit; an open inbox question names one (read as
    the inbox reads it: `claim_id`, `claim_ids`, `covered_claims`, either side of a conflict, an option's claim; a deferred
    question is open); both say the same thing; the person's own words would be closed in favour of a machine claim
    (`inbox_tend.may_close`); the trust table would not let the newer close the older (`trust_decision`). **A page whose claims
    do not all parse (`parse_claims(strict=True)`, as every read-modify-write path) is left alone whole**, in the plan and again in
    apply. **A page whose call failed is not finished**: it is listed in `review.txt` as not read and the same command reads it
    again (a page over its own call limit is final). Apply gives the newer the older's predicate and CLOSES the older
    (`claim_reconciler._close`: `valid_to`, `superseded_by`) — kept, never deleted. It changes those two claims' lines **and
    may re-serialise the page's frontmatter** as every page writer does (a YAML comment, an unquoted date), so the commit
    can show more than the two lines; the claims' meaning and the prose are untouched. Two real values of one attribute
    stay two because only the judge's two yeses join them. **The review opens with what to strike**, in plain words: a later
    line that only restates the earlier one more vaguely (the earlier, more specific value would stop being current), and two
    values that are both true at once. Each value shows its `valid_from`, the day it was said and the conversation.
  - **Names** (no model, so `plan` writes every row without `--judge`). A held person line written `Name (qualifier)` is
    turned into the shape #846 writes today and **Sleep decides later** (`same_name_people`, `same_name_tend`, ruling 74a:
    located evidence, two reads, undoable): it becomes **a second person held in doubt** under the bare name — a free
    `<name>-2` key (`same_name_people.free_id`), the bare name its `title`, the written name kept as an alias, its held claims
    kept on its own key (`pending_store._repoint`) — with a doubt recorded against every page and every other held line that
    answers to the bare name **by name or alias**, the bare name's own key included, through the live writer
    (`entity_resolver._record_doubt_pairs`, which also flags the pair for Sleep's tail). **Only when nothing else in the bank
    answers to the bare name** is the line renamed to the bare name, as Stage 2 sends a lone qualified mention. Two qualified
    lines of one name become two second people, held against each other. It never renames a line onto a page's id, never
    merges two lines, never moves a page. Every exclusion Stage 2 applies before it reads a qualified name as a mention of the
    bare name is Stage 2's own function (`entity_resolver.same_name_skip`, extracted from `_plan_same_name_people` and called by
    both): a handle the record paired, a self-reference, the owner's first name (the sweep also folds accents, which Stage 2
    does not), a name that is not one bare word, a non-person, a correspondent. A line the person said is not a page, and one an
    open question names, are left as they are. A page whose id the bare name holds but that is not a person, and the owner's, a
    nickname's or a relation's page, leave the line alone. **A page titled with a qualifier is counted and listed, never
    changed** (moving a page is the page join's, which has its own undo). The review shows, for a line, its own words, what it
    will be titled, and each page or line it will be held against with that page's first summary sentence and status.
    Apply derives the plan again from the bank as it is now and writes a row only when it comes out the same — a hash over the
    line AND everything it is held against (a page's name, aliases, type, status and first sentence; a line's name, title,
    aliases and conversations): anything that changed since the plan is skipped and counted. It refuses (exit 3, nothing written)
    a bank where `pending_entities.jsonl` or `_same_name_doubts.yaml` has uncommitted changes, and a bank with no git.
    - **What the next Sleep does** (`test_the_next_sleep_keeps_the_lines_claims_on_its_own_id…`): the release
      (`claim_pipeline.run_claim_pipeline`, Stage 5.56) finds no page of the line's own key, so its claims stay held on it, and
      a page of the bare name — or one that answers to it by an alias — receives none of them. A following mention of the bare
      name meets the line as one of the people compared (`_same_name_identities`), and a judge that reads it as that person
      puts it on that line by key. Measured on copies of six scratch banks that held qualified lines: after apply and the
      release, every swept line kept its claims (0 released, all waiting), and a second plan found nothing.
    - **When `git revert` of the sweep's commit stops being a clean undo.** Straight after apply, one `git revert` restores the
      bank byte for byte (tested, and run on copies of scratch banks). Once a Sleep has committed a change to the same lines of
      `pending_entities.jsonl` (it released or added a held claim on the swept line, or folded a mention into it) the revert
      conflicts on that file (`test_a_revert_stops_being_clean…`; the reviewer reproduced it), and `git revert --abort` leaves the
      bank as it was. The person then has two ways: leave the line as it is (it is the shape Sleep itself writes, and the doubt
      is Sleep's to settle, undoably, with the person's word standing), or edit the line back by hand — set its `name` to the
      alias the sweep kept (the written name), clear its `title`, point its held claims' `subject` back at that name's key, and remove its pairs from
      `_same_name_doubts.yaml`. Nothing the
      sweep wrote loses a claim either way: they stay on the line's own key. Apply's own output says this too.
  - **Commands, in order.** `plan --bank <copy or bank> --out <dir outside both>` (counts only, and every name row; no model)
    → `plan ... --judge --max-calls N` (`--model sonnet` reads the values; writes `values.jsonl`, `names.jsonl`,
    `review.txt`; resumable; exit 5 on an engine stop) → read `review.txt`, strike a row (delete it, `"strike": true`,
    `--skip-page`, `--skip-group <page>#<n>`, `--skip-line <name>`) → `apply --bank <bank> --plan <dir> --check` → `apply ...`
    (one `cicada` commit of only its paths; refused while Sleep runs, exit 3, in a bank with no git, exit 3, and on a demo
    bank, exit 4; a row whose claims or line changed since the plan, a page dirty in git, a rail that no longer passes —
    skipped and counted; a failure after the first write puts every written file back).
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
(`decay_policy.conversations`; a memory export entry and a save with no words of the person's are not one) below 0.39, just under the question line
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
conversation it was heard in already cited), so a closed claim stays closed and an ending is never recorded twice —
except one closed only by its own conversation's correction, which a revision of that conversation states again
(2026-11-25, `_edited_back`, "A stale date beside the corrected one"). A claim's *said* day (`decay_policy.latest_said`, `mention_weeks`,
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
**Which class a page gets (2026-11-23).** The rate above is `base x f(w) x pace`, and the base is the page's decay class, which
Stage 1 proposes per entity. The class is about the *thing*, not about a fact in it: `volatile` is a short-lived thing (an
event, a trip, an application, an errand, a decision still being made), `active` the default for the people, companies,
projects and tools the person has a relation with. A fact in motion about a lasting thing — a sister moving flats, a friend
promoted, the job the person just started — is a claim with its own dates and closing and never makes the page volatile;
`decay_policy.agent_class` refuses `volatile` for `person`, `company` and `project` (`storage.md`, "Decay classes").
Nothing about the rates, the thresholds, the repeat floor or the one-week cap moved, and pages already in a bank keep their
stored class. The benchmark scores it with no model (`benchmarks/consolidation/fading.py`): the people and things the
person keeps coming back to are not under the question line at the clock, the job held stands above the job left, and the
finished bank is aged forward (a copy, Sleep's decay step alone, a pass a week) to list what a fortnight and six weeks of
silence would raise a question about or archive.
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

**A feed item is an episode and an index row, never a page** (ruling 62, owner 2026-11-04; confirmed 2026-11-07).
`media_ingestor.write_prepared` writes, for an `origin: rss` item with no note, reason or agent behind it
(`is_pageless`), only the episode (`media_entity_id` empty, `processed_by: index`) and its `url_index` row (empty
`media_entity_id`, the poll's `feed` stamp still lands on it). Its Sources row is the episode's (`channel_items._feed_episode_rows`,
filed under its feed by the stamp, opening in the Reader like a watched day); the overview counts and splits it
(`pageless_feed_episodes`). A page an older poll made lists as before. A save that arrives with a reason or note for the
same link makes its page (`existing_hash` treats a page-less row as no page); a bare re-save stays a duplicate. Only feed
items: a bookmark, tab group or saved link keeps its media page.

---
