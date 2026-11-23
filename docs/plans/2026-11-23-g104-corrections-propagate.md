# G104 slice 3 — a correction reaches everything it touched

Branch `feat/g104-corrections` (worktree `~/code/cicada-wt-corrections`), one PR to `dev`.

## Why

Owner 2026-11-23: "My concern is that cicada is robust enough that if it consolidated a mangled transcription, and then
we update it, the info that that file affected, can be detected and patched in a way so as not to cascade, but being
aware tho. This is smth that should extend to all sources."

Found the same day (live bank, real values redacted): a meeting consolidated from a misheard transcript made pages for
misheard names (`<place-a>-connections`). A corrected transcript of another meeting landed as a **second file** in the
recorder's folder (same `YYYY-MM-DD HHMM` stamp, a new name) and became a **second episode**: both consolidated, the
misheard claims never closed, the meeting counted as two conversations for promotion. Hex 3.4.0 itself only rewrites
an export in place (title, notes) — that path already works as a revision (`revised: count: 1` on two live episodes).

Audit of what a revision patches today (`episode_revision`, `revision_prose`; file:line in the PR body):

| Artifact | On a revision | On a deletion (tombstone) |
|---|---|---|
| Claims only the removed text said | closed (`settle`) | **nothing** |
| Passages written from it | rewritten (`revision_prose`) | nothing |
| Pages made only from it | **nothing** | nothing |
| Aliases it gave | **nothing** (no alias provenance) | nothing |
| Held names (`pending_store`) | spans moved; `heard_in` keeps the credit | nothing |
| Open inbox questions it raised | **nothing** (only new conflicts are prevented) | nothing |
| What the person sees | telemetry + a log line | nothing |

Plus two identity gaps in staging (`episode_staging._stage_locked`): a different file for the same item is always a
new episode (rename matches only an identical `content_sha`), and a note past `SPLIT_CHARS` is one episode per H2, so
renaming a heading tombstones one section episode and creates another instead of revising it.

## Rulings (owner 2026-11-23 unless marked)

1. **Newest file wins.** In a `kind: meetings` folder, files whose names carry the same recorder stamp
   (`YYYY-MM-DD HHMM`, date **and** time — a date alone never joins) are one meeting. The episode holds the most
   recently modified one; a newer file is a **revision of the same episode** (same id, so one conversation for every
   count), never a second episode. The files it no longer holds are recorded on the episode, never read as their own
   conversation. Deleting the held file falls back to the next newest that remains (a revision again).
   **The exact rule (critic, 2026-11-23; code: `meeting_transcripts._FILE_STAMP` :78, `_from_name` :405,
   `folder_source._sync_locked` :464, `episode_staging._stage_locked` :1004):**
   - *Key.* `(folder_id, date, hour, minute)` as `_from_name` parses it (so `1601`, `16.01`, `T1601` are one key), a
     name whose `_from_name` has no time has no key, and a key is per folder, any sub-directory. It is computed in
     `_sync_locked` (the one place that sees the folder's index and the batch) and handed to the stager as the draft's
     `replaces: [source_id]` — `_stage_locked` never parses a name.
   - *Winner.* Among the files of one key — those in the posted batch and the episode's held file — the winner is the
     greatest `(mtime, relpath)`; relpath is only the tie-break. A file whose `(relpath, content_sha)` is already in
     the episode's `replaced_files` **never wins again whatever its mtime**: a rescan after manifest loss, or a sync
     tool that touched the old file, must not turn the correction back into the misheard text. Only a replaced file
     whose sha CHANGED (the person edited it) can win, by the same mtime rule.
   - *The episode keeps its id and changes its identity:* `source_id`/`relpath`/`content_sha`/`source_updated_at` move to
     the winner (what `update_in_place` already does for `source_id` :537), the old `source_id` joins
     `previous_source_ids` (`_repoint` :908), and `replaced_files: [{relpath, content_sha, mtime}]` (≤ 20, newest kept)
     gains the loser. `folder_source`'s "unchanged" test (`live and content_sha == sha`, :507) reads `replaced_files`
     too, so a replaced file re-posted costs nothing and drafts nothing.
   - *Order against the other staging paths.* The rename-by-`content_sha` path (:1031) stays FIRST: a file deleted and
     re-posted under a new name with identical bytes is a rename, never a replacement. The key rule applies only when
     that did not match. When the winner takes over an episode, its old `source_id` is removed from `deleted_sids`
     (as the rename path does with `deleted.remove(old)`) or the same pass would tombstone the episode it just took.
   - *Deleting the held file* while `replaced_files` is non-empty: no tombstone; the episode keeps its words and gains
     `held_gone_at`; the sync response carries `resend: [relpath]` — at most ONE path per meeting, the newest remaining
     by recorded mtime. While `held_gone_at` is set a post of that path wins whatever its mtime and clears it. A
     `deleted` naming a replaced file just drops it from the list; with the held file gone and the list empty the
     episode is tombstoned as today (ruling 2). The app, when it cannot read a `resend` path (gone from disk), posts
     it in `deleted` — it was dropped from the manifest, so no later pass would report it.
2. **A deleted source keeps what it taught, marked.** A tombstoned episode's claims stay open; every surface that
   draws a claim's evidence says its source is gone (derived on read from `source_deleted_at`, nothing written to
   pages) — as a **boolean beside `status`, never a new `status` value** (`SourceSpan.status` :1466 is documented as
   `current|grown|derived|stale|held|unlocated` and the app/MCP decode it; the tombstoned body and hash are still
   there, so the span is still `current`). Forgetting stays a deliberate act through the existing removal paths. Only a *replacement* (ruling 1) or an
   *edit* withdraws.
3. **An edit to a file that still exists is a revision**, including a section removed from or renamed in a split note
   (rationale: the person changed the source's words; ruling 2 covers only a source that is gone). A section whose
   heading changed is matched to its old episode by its ordinal position among the file's sections when exactly one
   vanished and one appeared at that position in the same post — deterministic, never by text similarity. The old
   position is not stored today (a section's ids carry only the slug, `folder_source.split_sections` :325), so the
   draft gains `extra.section: {index}`; an episode without it is never matched (tombstone as today, no guess).
   **A file crossing `SPLIT_CHARS` either way** (:72, :374: one episode ↔ one per H2) is the same class: the ids that
   vanish while the file still exists are revised to an empty body, never tombstoned, and the new ids read the words
   afresh (their claims are new; the old ones settle as removed — expected, one transient duplicate-free swap).
   **Prerequisite the plan missed:** `episode_revision.attach` (:301) feeds `prior_bodies` only episodes with
   non-empty `content`, and `entity_extractor` (:1012) returns its zero-entity result before it looks at a revision,
   so a revision TO an empty body is today no revision at all and its claims never settle. `attach` must build a
   `Revision` for an emptied episode (all lines removed, `windows` empty) — the extractor's zero-entity result is
   already enough for it to join `revisions_read` (`sleep_cycle` :3503).
4. **A page that only removed text supports is archived by rule, undoable.**
   *Candidate* (critic: the plan had no entry test, so a page the edit never touched could have been archived): a page
   (a) with `source_episodes` containing a revised episode, (b) that is not new this batch, and (c) that either lost a
   claim to the revision (`claim_pipeline` `revision_closed`) or whose name and every alias no longer occur
   (exact → whitespace → case-insensitive, the `evidence` locator, never fuzzy) in the revised body. A page with no
   claims whose name still occurs is never a candidate.
   *Support* — a candidate is kept if ANY of these holds; each is read from a field that exists today:
   | Support | Where it is read |
   |---|---|
   | another conversation | `source_episodes` has an id other than the revised ones (a tombstoned episode counts, ruling 2), or an open claim's `evidence`/`source_episodes` cites one; **or a conversation not yet read this drain names the page** (waiting episodes, same lexical-index lookup `inbox_tend` uses to find the conversations that name a subject) — so batch order never decides |
   | any claim that survived the settle | an open claim not in `Plan.revised_out`: covers the person's words (`is_human`), an agent's write (`recorded_ts`, `origin` `remote:*`/harness), events, records, and claims the revision restated |
   | person- or agent-authored page change | git: any commit touching `entities/<id>.md` whose `Cicada-Author` is a `user` or `harness` kind (`git_service.author_identity`, `entity_history` rows' `author_kind`) — covers a person-created page, a `cicada_edit_page`, a link the person or a trusted agent made through the page; one `git log` per candidate, engine-free |
   | pinned edit | frontmatter `corrections`, `aliases_removed`, `aliases_kept`, `human_edited: true` |
   | project | `type: project`, `mine`, `born`, `repositories` (ruling 56 / 53), or the page listed in any project's `entities_added`/`conversations_added` (`project_ownership`) |
   | Contacts card | a `sources[]` row with `added_by == contacts_local.ADDED_BY` (`_is_mine`), or `contacts_photo` |
   | person's own source | a `sources[]` row with `added_by: user` (`fact_sources`) |
   | import-minted | `media:` frontmatter, or any `source_episodes` episode that `quiet_pages.episode_kind` calls `import`/`check` |
   | owner | the owner's page |
   There is **no `created_by` field** on a non-project page; "the person or an agent created it" is the git row above,
   not a new frontmatter key (never add one — a bank handed over would not carry it truthfully).
   With none left: archived — `status: archived`, `removed_at`, plus `archived_by: {reason: revision, episode, day,
   prior_status, prior_confidence}` (the `bookmark_forget` shape :36 plus what a restore needs; decay archives carry no
   such stamp, so a restore never reopens a page decay archived) — its open questions withdrawn (T3), listed in the run
   record. **There is no general page-restore path** (`bookmark_sync._revive` :635 revives only a media page by its
   own marker; `conflict_resolver._revive_on_time` :1138 revives on a later mention): the worker adds one small writer
   in `revision_cascade` + one backend route the app calls (new features live behind the API) that reads `archived_by`, and a later real mention
   already revives it through `_revive_on_time` (verify, with a test). With any support: kept, and the record says
   which removed claims it lost. Never: the owner's page, a `project`, a `media` page.
5. **Nothing cascades past independent support.** A correction closes only what rested on the removed text alone
   (the existing `settle` rule, extended to the artifacts above). Anything a later conversation, the person or an
   agent also supports is never closed — it is flagged in the record instead.
6. **The person is told, not asked.** One "Corrections" record per Sleep run (ids and counts in the machine-local run
   detail; per page, one dated History line in the page saying which conversation's correction changed it). No inbox
   question for a correction except the existing pinned-passage one (`revision_prose`). The commit body lists the
   revised and archived ids.

## Constraints (rails this touches)

- No LLM at capture; the backend never opens the watched folder — anything it needs from a file the app posts
  (`folder_source`, `LocalSourceWatcher.swift`). If the backend needs bytes it no longer has (ruling 1's fall back),
  it asks the app to post that path again in the sync response; the app drops it from its manifest and re-posts.
- Every page write atomic, inside Sleep's write window (`write_admission`); one git writer; each step commits only
  its own paths. T1's staging writes are Awake-side (frontmatter + body of one episode under `episode_lock`; routes
  already behind `_DEMO_GATE`, so `demo_guard` holds). The cascade never opens an engine and never reads a page it was
  not given a reason to (candidates only).
- Ruling 56 (no project is made or archived by Sleep), ruling 29 (a question is settled only through `inbox_tend`'s
  resolver as Sleep's undoable commit), ruling 73 (no question loses a value) and ruling 62 (an import-minted page is
  never archived by this rule) bind the cascade.
- Evidence never located fuzzily; a claim is closed, never deleted; `retracts` records as today.
- `processed: true` only by Sleep or an agent; ids never renamed (ruling 34).
- Telemetry and the run detail: ids, counts, enums — never a title or a line of text.
- Privacy rule for docs, commits, PR body: no names, titles or quoted lines from the bank.

## Tasks

Each task: failing test first, implement, its tests + direct callers + `make test-crucial-backend` (Swift: the touched
test file + `make test-crucial`). Worker chooses the code; the brief is the problem, the rulings and the acceptance
tests below. One commit per task, message cites G104.

### T1 — One meeting, one episode (staging + app)
Files: `api/services/meeting_transcripts.py`, `api/services/folder_source.py`, `api/services/episode_staging.py`,
`api/routers/local_sources.py` (+ response model), `app/.../LocalSources/LocalSourceWatcher.swift`,
`app/.../Models/LocalSources.swift`.
Accept:
- A meeting episode exists for `2026-11-03 1601 A.md`; posting `2026-11-03 1601 B.md` with a newer mtime revises
  that episode in place (same id, body = B, `revised` record, `processed: false`, B's relpath/source id), and records
  A as a file it replaced. No new episode.
- Posting a same-stamp file with an *older* mtime than the held one creates no episode and changes no body; it is
  recorded as a replaced file.
- Deleting the held file with a replaced file still present: no tombstone, `held_gone_at` set, the sync response asks
  for that file (`resend: [relpath]`, one path); its post revises the episode back and clears it. Deleting every file:
  tombstone as today. Deleting a replaced file only: dropped from `replaced_files`, nothing else changes.
- Rescan after manifest loss, both files posted (one batch, then split across two batches, then in both orders):
  one episode, the same body, the newer file held, no second revision. The OLD file re-posted later with a newer
  mtime but the same bytes does not win (no flip-flop); with changed bytes it does.
- A file deleted and re-posted under a new name with identical bytes is still the rename path (same id, no
  `replaced_files`); file A deleted and file B (same stamp, different bytes) posted in one batch takes A's episode
  and A's `source_id` is not tombstoned.
- Equal mtimes: the greater relpath wins, both orders of arrival.
- `2026-11-03 notes.md` and `2026-11-03 other.md` (no time) stay two episodes. Non-meetings folders unchanged.
- App: `runFolderSync` today discards the response (`_ = try await api.syncFolder`, `LocalSourceWatcher.swift` :402,
  :407); it reads `resend`, drops those paths from `next` and posts them once more on the SAME pass (a re-run guard so
  a path that cannot be read cannot loop); an unreadable/missing resend path is sent in `deleted` (Swift test with the
  manifest in `FolderScannerTests`' style).
- Split notes (ruling 3): renaming one H2 heading in a split file revises that section's episode; removing a section
  from a file that still exists revises it to an empty body (its claims settle as removed text), never a tombstone —
  end to end through `sleep_cycle.run` (the `attach` prerequisite in ruling 3): the section's claims are withdrawn.
- A file crossing `SPLIT_CHARS` in either direction revises, never tombstones, the ids that vanish; a legacy section
  episode with no `section.index` is not matched by ordinal.

### T2 — A deleted source is marked, not forgotten
Files: `source_spans` (`Source.status` :163 / `span` :179, the `SourceSpan` model, `schemas.py` :1466) and its
callers: recall detail, `cicada_sources`, the page payload and the span groups the app draws. Accept: a claim whose
evidence episode carries `source_deleted_at` reads `sourceRemoved: true` on every door (additive field; `status`
stays what the offsets say — never a new status word); it stays open and counted; nothing is written to the page.
`mcp_tools.py` :3158 already says "Removed from its source on …; kept as evidence." for `cicada_sources` — keep that
sentence the single wording and reuse it. The Swift decoder takes the field as optional. A test per door (MCP, the
spans route, recall detail) pins it.

### T3 — The cascade: pages, aliases, held names, questions
Files: new `api/services/revision_cascade.py` (one module, engine-free), `pending_store.py`, `inbox_tend.py`,
`bookmark_forget.py` (archive precedent only).
**Where it runs (critic):** once PER BATCH (the `Revision` objects, `revision_closed` and `Plan.revised_out` exist only
in the batch that read the revision), in `sleep_cycle` after Stage 5.565 (`book_said`, ~:3586; the claim pipeline's
reconcile + `settle` are done and pending releases already ran inside it, `claim_pipeline` :524-583) and BEFORE Stage
5.58 (:3601: a page the cascade archives must not cost `revision_prose` an engine call, and 5.58 skips archived pages),
before Stage 5.6 hubs and the batch commit — so every write is inside the write window and lands in the batch's one
commit, whose body lists the revised and archived ids. The decision that must not depend on batch order is the
archive one: support includes a conversation still waiting in this drain that names the page (ruling 4), so no
drain-level state is kept and a stop mid-drain leaves nothing half-decided. Questions are withdrawn AFTER the commit:
the cascade only returns the ids, and `_tend_inbox_safely` (:3772, which already runs after `_finalize`) settles them
through `inbox_tend` as a new engine-free rule (add to `RULES`/`ENGINE_FREE`, e.g. `source_corrected`: "The words it
asked about were corrected"), one commit each, undoable, `inbox/<kind>/settled:` — the cascade never writes
`inbox/` itself. A question about an archived page is already retired by the existing `subject_gone` rule (`inbox_tend`
:727), but that rule only runs in the policy pass once per drain, so the new rule covers it in the batch.
Accept (scratch-bank fixtures):
- A page created by Sleep from one meeting, whose only claims the revision withdrew → archived with a reason enum
  `revision`, the revised episode id recorded; restoring it (the existing restore path or a new one) puts it back as it
  was. Its open questions are settled as withdrawn (undoable, Sleep's commit, `inbox/<kind>/settled:` shape).
- The same page with one claim from another conversation → kept, not archived; the record lists the lost claims.
- Owner page, a project page, a person-created page, a page with a person-made link → never archived.
- An alias on a kept page that occurs (exact → whitespace → case-insensitive) only in the removed text of the revised
  episode and in none of the page's other `source_episodes` bodies → dropped from aliases, **not** added to the
  person's removed-aliases list (a later real mention may add it again). There is no alias provenance, so the guard is
  conservative: nothing is dropped from a page with `corrections`, `aliases_removed`, `aliases_kept` or
  `human_edited`, nor an alias present in the page's last `user`/`harness`-authored commit's diff, nor one that
  occurs in the page's name or another page's name (G227 qualifier rules stay).
- A held name (`pending_store`) whose name no longer occurs in the revised body: the revised episode leaves its
  `heard_in`; its held claims that only the removed text said (`episode_revision.reanchor`'s `revised_out` over the
  held claims — today `claim_pipeline` :531 calls it for the spans and throws that plan away) drop through
  `pending_store.unhold`-style removal under `_LOCK`. A name heard from two conversations keeps the other, and then also
  keeps its description/summary/key_facts (the extraction's text is not attributable per conversation). A line whose
  ONLY conversation is the revised one and whose name is gone is removed whole, with its `item_inputs` and links. Runs
  after the claim pipeline's releases, so nothing already released onto a page is touched.
- A question is withdrawn (rule above) when: a conflict whose option claims are all closed by the revision's
  withdrawal record, or all but one; or a name / same-person / merge question whose `source_episode` (the one field an
  item carries, `inbox_generator.py` :574) is the revised episode and whose name no longer occurs in the revised body
  and has no other support (ruling 4's table) — the same test as the page's. One with evidence elsewhere stays.
  Ruling 73 holds: a withdrawn conflict loses no value (its claims were already closed by `settle`).
- A replaced file's episode (T1) counts once for promotion — the existing per-episode counting, verified by a test.

### T4 — Being aware: the Corrections record
Files: `revision_cascade.py` report → folded per batch into the drain's state like the other counters (`sleep_cycle`
`_fold` :2468, `DrainState`) → `sleep_runs.record_leg` summary (`runs.json`, machine-local) + `sleep_run_detail.py` +
`SleepRunDetail` schema (bump `SHAPE`, currently `plan-share-1` :26; the app's `If-None-Match` mapping ships with it); the page History line writer (`revision_prose._add_history` as precedent); the Sleep commit body; the app's
run detail view (one "Corrections" section: N conversations revised, N claims withdrawn / superseded, N passages
rewritten, N pages archived (tap to open, restore), N aliases dropped, N questions withdrawn, N kept because something
else supports them). Copy provider-neutral, DR ids cited for the app part.
Privacy: the run record holds page and episode ids and counts only (an id is a slug, as `SleepRunPages` already
carries; never a page title, an alias, a held name or a claim's words — the same for the commit body and telemetry).
Accept: a run with one revision shows the section with the right counts, summed across the drain's batches; a run with none shows nothing; every page
the cascade touched has one dated History line naming the conversation id.

### T5 — Docs
`docs/architecture/capture-and-sleep.md` ("An edited conversation…" section: rulings 1–6), `storage.md` (span state
enum), `CLAUDE.md` Sleep rail (≤ 2 lines, stays under 60,000 chars), G104 row (slice 3 shipped, what stays open),
`feature-status.md`, `TODO.md` rulings list (owner 2026-11-23): ONE new ruling, **75** (TODO's last is 74), carrying the
plan's six rulings as sub-points — the plan's own "ruling N" numbers are local to this file and must not be cited as
TODO rulings in code, docs or commits (ruling 4 there is TODO ruling 4, the scheduled-plan switch). CLAUDE.md Sleep rail
mentions `replaced_files`/archive only by pointing at the doc.

## Out of scope (stays open on G104)
- Second-order re-derivation: a later conversation that resolved to a page the correction archived keeps its claims
  (ruling 5: it is independent support, so the page would not have been archived).
- Events (`happened`/`milestone`) stay `progress.py`'s; the record flags one whose only evidence was removed.
- Web facts on an archived page go with the page; on a kept page they stay.
- No repair of the live bank's existing duplicate meeting episode (owner: fix the class, not the case).
