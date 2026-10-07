# Features: graph, inbox, Sleep trigger, upload

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

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
shims (they set `Deprecation: true`) kept only for external callers — the app calls `/inbox`. Every resolve door answers
409 while Sleep holds the pages (`inbox_service.resolve`, G177/G183(a)), asked again after its awaited snapshot and before
any write; between a drain's batches it commits alone (a window opening mid-answer is the disclosed residual race in
`storage.md`).

**A count is what the inbox serves, never a count of files.** `load_inbox` skips a deferred item and
one whose subject is archived, dropped or (for every kind but `clarification`) gone; those files stay
on disk. `inbox_service.served_counts` applies the same `_hidden` predicate over `bank_index`
frontmatter, and it is the only source of `/status`'s `inbox.total`/`byKind` (the menu bar) and the
hub's pending count — on 2026-10-06 the raw file count said 49 while the inbox served 35.

**Question object (G60).** Every item carries `question`, `options: [{key, label, description, …}]`,
`allow_other`, `allow_defer`, `predicate` and an optional `hint`. Descriptions lead with the age
phrase ("6 months ago") so staleness is visible before choosing; `age_days` is derived at read time,
never stored. Legacy flat `options: [str]` still render.

**Dedup + time.** Items are keyed `(entity_id, predicate)`. A second competing value **merges** into
the open item as another option instead of writing a duplicate. **A predicate fold is asked once per pair per bank
(G98/G115):** Stage 3 raises `normalization` only when a synonym in `_predicates.yaml` maps a label onto a *different*
predicate — a label kept as its own slug (`uses dataset` → `uses-dataset`) is formatting, never a question.
`write_claim_nudges` keys the item by `(slug(raw), canonical)`: a later claim folded the same way joins the open item's
`covered_claims`, and a pair the person answered "Correct fold" to (`_predicates.yaml` `confirmed_folds`, committed with
the answer) is never asked again; "Wrong fold" repoints every covered claim. The claim write itself never changes. A
one-shot bank migration (`dedup_normalization_items`, marker `inbox/.deduped_normalization`) cleared the items raised
before the fix. Each Sleep,
`inbox_questions.refresh_open_questions` bumps re-mentioned options, auto-resolves questions the
user answered organically, escalates a question whose every option has been silent for
`inbox_stale_after_days` (90) by inserting "Neither anymore", and keeps deferred items out of
`GET /inbox`.

**Resolve is claim-aware.** Picking an option supersedes every losing claim (`valid_to` +
`superseded_by`); "both" keeps them open with a `context` qualifier; "neither"/free text writes a
`user_stated` claim that closes them; `defer` writes `remind_after`. All commit with
`Cicada-Author: user` — **only the files the answer wrote** (the entity's page, every manifest line's file, the item;
audit 2026-10-05 P1-3), never `git add -A`. An uncommitted edit already on one of those files is snapshotted before the
answer runs (`git_service.snapshot_dirty`) and committed first, on its own, with no author claimed ("Uncommitted edit
kept apart", built in a private index so nothing staged rides in — `commit_touched_sync`); an unrelated dirty file
stays dirty.

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
early by the next answer, `Store.activateBank` (before the switch is posted; a new answer is refused while it waits), the window closing and quit (`.terminateLater`,
≤ 3 s) — an undone answer makes no commit, claim or G113 event; a page switch does not send. A refused answer comes
back with a toast; one refused while Sleep holds the pages says Sleep is running (`SleepRefusal`, app.md *Sync engine*). Every kind renders in
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
flag and claims, and the predicate `locus`: pure, engine-free, zero-network, never stored. Since
G61 S3 an agent can CHECK a `checkable` item (recommend-only, below); nothing settles, holds or reorders one (S4–S8 wait). `GET
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
