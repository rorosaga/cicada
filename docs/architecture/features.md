# Features: graph, inbox, Sleep trigger, upload

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

### 1. Graph Explorer
Force-directed d3 graph: node color by type, size by how connected a page is (distinct neighbours, confidence a small
second term — G109 2026-10-15, the Obsidian look: small dots, hairline links, a loose halo of unlinked pages, names
fading in with zoom; `app.md`), edge labels, cluster detection, decay/clarification indicators. Open ideas live in the
backlog.

**The page (Direction D, DS-3a).** The canvas fills the content area under the command bar. Its chrome is one
floating group at the bottom-left — the whose-beliefs text tabs (only with more than one observer; they move
into the Legend under 640 units), Legend, − + fit and the pan toggle — an opaque floating surface, never glass
over the canvas until the G109 frame-time check has run (R-DG2). The Legend is the context legend, the filters
and a key in one: a context click shows only that context, confidence is words, Show unlinked (on by default) and Show logos are
switches. ⌘F
opens find on the canvas as an overlay (⌘K searches everything); the page's own field is gone. A node opens
its entity card as the right-hand column (`GraphColumns`: 560 alone, 480 beside the Reader, never under 440;
the canvas takes the rest and keeps the open node in view by panning, never zooming), and its evidence opens
the Reader beside it. × or a click on empty canvas closes the column with its Reader; Esc closes one thing at
a time — find, Legend, Reader, column; another node swaps the column in place and keeps the Reader. graph.js
posts `backgroundClicked` and `escape` and takes `setSelectedNode` (a neutral ring), read and spelled in one
place (`GraphMessage`, `GraphJS`) and tested on both sides — none of them touches the simulation.

**Layout on a push (item 6, 2026-10-08).** A data push relaxes only the nodes it brings: every settled node is held
where it is for that layout (`holdSettled`/`releaseHolds` in graph.js — never over a drag's or focus mode's pin, and
released when the layout ends), and a push that brings no node (a rename, a confidence, a removal) starts no layout.
A push that lands before a layout ends (running, or held while the page is hidden) joins it — its nodes keep moving
and it keeps its heat — and a full push rebinds a drag in progress to the live node. So Sleep's batches update the
graph live without moving what was there, and a push that lands while the page is
hidden no longer replays whole-graph motion on return. Only a first paint (and a filter change) lays out everything.
Measured in WebKit at 2,000 nodes (`GraphWebKitBenchTests`, opt-in): draw 1–2 ms, a tick 7 ms, a cold layout 135
ticks; 20 new pages settle in 112 ticks with 0 settled nodes moved. At the live bank's shape (3,698 nodes, 41,570 links, the opt-in
bank-shape bench, G109 2026-10-14): a tick 12 ms, a cold layout stops at ~129 steps (1.7 s of tick CPU) at rest. A hold
on a settled graph is a push of its own kind: every node but the dragged page and its neighbours is held the same way. Per-type zones are the existing `typeClusterPositions`
anchors; `graph-zones.bench.js` measures their strength (no overlap at rest at any strength; stronger = more separate
zones, same settle time).

**The entity card (DS-3a).** One component, `EntityDetailCard` — the Graph's column, Clusters' card. Header:
the type as a `Tag`, status and confidence in words ("Active · very confident", the number in `.help`) — or, when
the page's `lastReferenced` is more than 90 days before the viewer's today, the status and when it was last mentioned
("Active · last mentioned Feb 2025", G194 A2: the confidence word is replaced, the number and the full day go to
`.help`). The three bands behind those words — confidence, fade pace, the old day — are served by the backend as
`bands: {confidence, fadePace, lastMentioned}` on `GET /entities/{id}` (`entity_bands`, G180 parity; no ETag, not a
Store domain); the app's `EntityHeaderWords` / `FadeWords` twin paints them from the existing fields and is pinned to
the backend by one table, `api/tests/fixtures/entity_bands.json` (`EntityBandsTests`). Words stay in each client. The
name, the page's Summary, Back ⌘[ and ×; text tabs Content · Perspectives · History · Timeline with counts once
known (the belief counts once the claims are read, when a section or tab asks), Timeline drawn only while a belief is
contested or a belief's clock has it open (no "Timeline 0", 2026-10-17), and — while Content shows — the page's source
toggle and Copy at the end of that same row, never a second tab row (`EntityCardHeader.pageTools`); where the row cannot
hold both, the tools step down to their own line rather than cut a tab label (DR-45). **Content opens on the page (owner
2026-10-09): every type, a person's too, shows its prose first as an article, and everything else waits behind a
click.** Content: the article; its folder or repository in words; then the sections, each a
remembered disclosure (`CardDisclosure`, DR-39) that reads its data only when opened — What Cicada believes (the
claims; shown open on an R-FX11 page, whose beliefs are its content), Where this comes from, a person's *How you know
<name>* (*What you're connected to* on the owner's page) with *What's happening*, and Details. The
article is `WikiArticle`: the served prose without `## Summary` (the header's), `## Description` (a media card's) or
a claims fence, parsed once into flat rows — one per list item or paragraph — off the main actor. `## Article` (G194
articles, `storage.md`) is a container: its heading row is not drawn and its `### ` titles are drawn as level-2
headings, peers of `## Key Facts`, so the article reads as the page's sections under the header's lead; each paragraph
is one row whose range is its `article` provenance item's and cached by text
(`WikiArticleCache`, in memory, not a Store domain). Its first 48 rows are built synchronously, so the page never
draws blank, and `WikiPageView` draws the rows in a `LazyVStack`: only the lines on screen are laid out. Until the full page lands the card says "Reading the page…"; a failed read says "Couldn't read this page." with Retry, never a spinner forever (DR-32). One claims read per card is shared by every section and tab that asks at once. Every line
offers *Where this line came from* on hover and as an accessibility action: the `/provenance` section item whose
`bodyRanges` cover the line opens its evidence in the Reader (checked against `pageBodyHash`); a line no item covers
opens the page's Where this comes from and scrolls to it. A line with web links has a 🔗 beside it (and an accessibility
action) that opens each link's bookmark card and the person's view switcher; a link alone on its line asking for a block
view is a card row of its own (app.md, *Links show as what they are*). `/provenance` is read when the card opens — the header's
facts are when the conversations were said (G194) and every evidence chip names its agent from it — but drawn only
when asked; a person's Works at and Role read only those beliefs (`GET /entities/{id}/claims?predicate=…`), never the
whole list. Measured on a synthetic owner page of the real one's size (5.6 MB, 5,921 claims, ~180 KB of prose;
`CardOpenProbeTests`, opt-in, against a scratch backend; debug build): `MarkdownBody` laid the whole prose out at once,
a 2.1–3.2 s main-thread stall when the page landed and ~0.5 s on every graph push while it was shown; the article
costs ~60 ms of first screen and no stall over 16 ms on a push. **Where this comes from ends with *Who wrote it*
(G198):** per part of the page's text, who last changed it, when, and an agent edit's reason ("accepted by you" when the
person applied a proposal), from `GET /entities/{id}/blame` (git, never stored; not a Store domain, cached in memory;
a `pending` answer keeps the copy held and is asked again up to `CicadaTiming.blamePendingTries` times).
**Where this comes from (owner 2026-10-14, G61)** is
one disclosure for where the page's knowledge comes from and how fresh it is (it replaced *Where this came from* and
*Look it up at*, and keeps the former's remembered choice). Closed, it says only "· 3 conversations" (from `/provenance`,
known before the section is read, so the words never change on a first open and never claim a page with unread sources
has nothing). Open: how
many beliefs have a place to check them, when the page was last said and its sources last checked; **Sources and
links** — each G61 source grouped by its fact ("Employs · backs 5 beliefs"), its row leading with the site's name (the
page's own `## Links` title for that URL, or the name of the saved page it is linked to, else its host) over the full
URL, then as before (the fact, how it can
be read, who added it with their mark, "You chose to use this" / "Only you know this", the official site's
confirmation, ↗ and the menu), under each fact group the beliefs its sources back (four, then "and N more"), each a
way into that belief's timeline; then *Named in conversations*, the page's `## Links` lines that are not sources, each
with its title (else its host), its URL, its note and the conversation that named it (mark, app, title, day — opens in the Reader), ↗, and
*Use as a source* in its menu; the add field and the page's open inbox question with Open in Inbox; **Conversations**
— one row per app (mark, name, conversations, beliefs and passages they back, last day), then *Where this came
from*'s writers, conversation rows and coverage. It reads `GET /entities/{id}/sources/overview` (`page_sources`, one
bounded read — ~170 ms warm on an owner-sized page of 5,900 beliefs over 3,000 conversations, pinned under 500 ms by
`test_page_sources_owner_scale.py` — through `ProvenanceCache`, ETag-revalidated, never a Store domain) only when the
section opens or the beliefs list is shown (for its chips), never on every card open, which already reads
`/provenance`; never the claims list. A belief whose fact has a source wears a *Check at example.org* chip beside its
evidence (`PageSourcesOverview.lookUps`: the person's, then a taken or confirmed one, then the rest; never the
official-site or page-wide ones): it opens the section on that source, selected (DR-48) and scrolled to — the way back
from a fact to where to check it. Nothing here says a source WAS checked against a belief (S3 is shadow); Details:
tags, related, dates, how it fades — related as its first 12 names and "and K more" (`RelatedLinksRow`, owner page
2026-10-14: a hub's 2,024 chips, each scanning the graph for its page, took ~1 s a render), which opens the Content
tab at the page's own `## Related` heading (DR-38, DR-5 link); a page with no such section says the count in words.
A page sent `rawOmitted` (its fence withheld, or for a page with a ledger its frontmatter alone) is never shown,
copied or reconstructed from that head — Source and Copy read `/raw` (`RawFile`); the app has no flow that writes a
page body back. Beliefs are rows — the sentence, its evidence chip and its age, the rest in
`.help`. A location page's map is a picture of where it is, never a scroll trap: it takes no pointer events, so
the column scrolls with the pointer over it, and *Open in Maps* is the way to pan (`LocationMap`). A page with
thousands of beliefs stays usable: what the tabs show from the claims is derived once per load,
off the main actor (`ClaimDigest`), Perspectives builds its rows lazily, and a belief list grows twenty rows per
"Show N more" (`BeliefPaging`), never all at once. History: newest first, Show in conversation (straight to the Reader when one conversation maps here) and What
changed; when the page left older changes out (`historyTruncated`, #244) its last row is *Older changes*, which reads
the next page with `?skip=N` (`HistoryPaging`; the window is pinned to `MAX_PROVENANCE_COMMITS` by a test). Timeline: contested beliefs inline; a belief's clock opens its own.

**Pictures and the person card (G146, round 4).** Every entity avatar is `EntityPicture` over the one picture
precedence (`entity_picture.resolve` and its Swift twin `EntityPictureResolver`, one fixture): the person's own upload
or "initials" → a person's Contacts photo → a person's public-profile photo (G159, 2026-10-09; "Photo from their public
profile", served from Cicada's own copy at `/entities/{id}/photo`, with Change and "Use initials instead" like any
detected picture) → a brand's logo → a media page's thumbnail → a ring monogram, never a solid
fill; `PictureStore` holds uploads, Contacts photos, public-profile photos and media previews by URL — all on Cicada's own API with the bearer
(a media page's picture is the backend's stored `/entities/{id}/preview?v=…`, and `MediaPreview`, `HeroPreview` and
`VideoThumb` draw the same stored copy through `StoredPreview`; no view loads a provider's thumbnail) —, `LogoStore` the
logos. Any editable picture opens the image picker on a click (a saved item's also takes a PDF: the backend draws its
first page, `POST /entities/{id}/picture/pdf`, and nothing is painted before that answer), takes a dropped image,
dims under a camera on hover and offers "Use initials instead" / "Remove picture" on right-click; the app shrinks the
picture (ImageIO, ≤ 512 px) and `EntityPictureWrite` paints the answer before the server gives it. A `person` opens
with mock C's top (F-12): an 88 pt picture, the name at 24, the Summary as a two-line standfirst (a click unfolds it and the header grows; *Show less* folds it —
a capped Summary or name is never selectable, since a selectable field opens over its neighbours on a click), the
picture's source line and a
facts strip whose every cell comes from something the card loaded (`PersonFacts`; Works at names every current place,
newest first, each opening its own page, two then "+N" with the rest in its help — 2026-10-14; Known since, Last mentioned and
Conversations are when the conversations were said, over all of them — `/provenance`'s `totals` — with the page's own
dates only as a fallback; Known since gives its span only from a day on, never "· 0 days"); then the tabs, and in Content the page like every other type, one column; behind its
disclosures, beliefs signed with who wrote them (`SignedLine`: harness, model and effort from the captured turn), Where
this came from, and *How you know <name>* (*What you're connected to* on the owner's own page, by its `owner` flag;
`PersonMapLayout`, the graph's own edges) with *What's happening* (`PersonHappenings`, from `ProjectsCache`). Every
other type keeps this header with a 40 pt picture. In Clusters every card keeps the focus width (the two-column person
card retired with the page-first card); the header adds "Show on the graph".

### 2/3. Unified inbox (`memory/inbox/`)
Nudges and clarifications live in **one store**: `memory/inbox/inbox-NNN.md`, each with a `kind`
discriminator (`decay`, `conflict`, `clarification`, `merge_suggestion`, `removal`, `divergence`,
`normalization` — the last two were written by Sleep since G49/G98 but only became loadable and
resolvable kinds with G113; `removal` is written by a live browser sync, not Sleep, at proposal
time (G129 slice 2); `followup`, G141 PJ-6, by Sleep's engine-free tail; `page_edit`, G198, by an agent's proposed page
edit), behind `GET /inbox` /
`POST /inbox/{id}/resolve`. `api/routers/nudges.py` and `clarifications.py` are thin **deprecated**
shims (they set `Deprecation: true`) kept only for external callers — the app calls `/inbox`. Every resolve door answers
409 while Sleep holds the pages (`inbox_service.resolve`, G177/G183(a)), asked under the bank's write admission and held
through the answer's commit, so a window waits for the answer (`storage.md`, "Write admission"); a conflict answer's
prose rewrite is a model call made before admission and used only when the item, the pick and the page are what it
was made for. Between a
drain's batches it commits alone.

**A count is what the inbox serves, never a count of files.** `load_inbox` skips a deferred item and
one whose subject is archived, dropped or (for every kind but `clarification`) gone; those files stay
on disk. `inbox_service.served_counts` applies the same `_hidden` predicate over `bank_index`
frontmatter, and it is the only source of `/status`'s `inbox.total`/`byKind` (the menu bar) and the
hub's pending count — on 2026-10-06 the raw file count said 49 while the inbox served 35.
**The read is one listing, not one per item (inbox lag, 2026-10-17).** Most hidden items name a subject with no page
under any spelling (merged away, renamed), and `resolve_entity_file`'s case-insensitive rung used to glob `entities/`
for each: ~6 s per `GET /inbox` at 4,700 pages and 900 items. It now reads one cached stem index of the folder
(`id_utils._stem_index`, rebuilt when the folder changes), the subject's status comes from `bank_index`, and
`GET /inbox` (and the deprecated `/nudges`, `/clarifications`) run `load_inbox` in a worker thread, never on the event
loop (`test_inbox_load_perf.py`; the 0.5 s budget at that scale is opt-in, `CICADA_BENCH=1`). In the app, an Inbox row's
age and source day parse through formatters built once with each stamp's answer kept (`ISOStamp`), since the question
list is a non-lazy stack that draws every row on each render.

**Question object (G60).** Every item carries `question`, `options: [{key, label, description, …}]`,
`allow_other`, `allow_defer`, `predicate` and an optional `hint`. Descriptions lead with the age
phrase ("6 months ago") so staleness is visible before choosing; `age_days` is derived at read time,
never stored. Legacy flat `options: [str]` still render.

**Dedup + time.** Items are keyed `(entity_id, predicate)`. A second competing value **merges** into
the open item as another option instead of writing a duplicate. **A predicate fold is asked once per pair per bank
(G98/G115):** Stage 3 raises `normalization` only when a synonym in `_predicates.yaml` maps a label onto a *different*
predicate — a label kept as its own slug (`uses dataset` → `uses-dataset`) is formatting, never a question. The
reconciler raises one question per `(slug(raw), canonical)` pair *after* the pass, naming the claim each page keeps (a
restatement that reinforced an existing claim names that claim) and listing the rest in `covered_claims`;
`write_claim_nudges` merges a later batch's claims into the open item for the pair, and a pair the person answered
"Correct fold" to (`_predicates.yaml` `confirmed_folds`) is never asked again. "Wrong fold" drops every synonym spelling
of the pair and repoints every covered claim still on the canonical. The answer runs inside the request's write admission, as one
page-and-git-lock section through its own `user` commit, the map written atomically (`storage.md`). Every reader takes the map through `predicates._read_runtime_map`, parsed once per change of the file's (inode, mtime, size) and handed out as a copy (2026-10-16: `GET /inbox` re-parsed it once per conflict item — ~0.6 s of a 240-item read). The question is served on the first covered page still live
(`_fold_anchor`), hidden only when every covered page is gone. The claim write itself never changes. A one-shot bank
migration (`dedup_normalization_items`, marker `inbox/.deduped_normalization`) clears the items raised before the fix:
an admitted transaction (G183) that defers while Sleep holds the pages, under the page and git locks, committing only
the files it changed and restoring them — bytes and index entries as they were — on any failure. Each Sleep,
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
eyebrow's kind tabs show every kind with its count while they fit, else All and the selected kind with the rest under
one "More" menu that lists each with its count (`OverflowTextTabs`, owner 2026-10-16 — never a truncated label); the
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

**Settled by a check (owner ruling 2026-10-16, TODO ruling 27).** A conflict or clarification about a **public thing** —
a film, a paper, a tool, a company, a public concept — is looked up on the web and settled with a cited answer:
Sleep's tail does it on a run the person started (their Claude plan's own search, the call's one tool) or on a metered
engine at its price, and the person's own agent may do it through `cicada_record_check(outcome="settles")`
(`mcp.md`). Never searched: a `person`, an untyped name the description says is someone, the owner's page, a file or
path, a project, a multi-valued predicate other than what the thing *is*, an option label naming a person or saying
"my", anything personal (`web_settle.classify`; when in doubt the question stays). A type question (`is-a`, `type`,
`description`…, the owner's own example: "Is <tool-a> an agent harness or an AI agent itself?") settles on one option
only when the page rules the others out, on the item's own "both" option when the page says it is all of them (one
cited claim per option, nothing closed), never on an option the item lacks.
The settled question moves to `inbox/settled/<id>.md` with a `settled:` block naming exactly what it wrote, and is
served by `GET /inbox/settled` (not a Store domain). **The Inbox shows it under "Settled by a check"** (closed until
asked for, below the questions and on the empty page): the answer, the quote and the site with when and who
(`SettledChecksSection`), **Undo** (`POST /inbox/settled/{id}/undo`: the check's claim is withdrawn, what it closed
reopens — only a claim still as the check left it — and the question returns under its number, marked
`web_check: undone` so no check settles it again; committed as the person's, `Web check undone <date>`, with an edit
already on the page committed apart first) and, for a public citation on a subject with a page, **Track this source**, which
calls the person's own add-source route — a citation is never a tracked source by itself (`storage.md`). Questions
about whether a PR or a G row merged are answered from the commit by a trusted local agent, never searched.

**Settled by Sleep (owner ruling 2026-10-17, TODO ruling 29).** "A single consolidation also should take care of
cleaning up the inbox … as conversations come through, questions get answered … many things … can be assumed." Sleep
tends the inbox (`inbox_tend`, `capture-and-sleep.md`) in three moves, through the **person's own resolvers** (the
`_resolve_*` writers `POST /inbox/{id}/resolve` uses), with `inbox_actor` saying Sleep answered:

| kind | Sleep settles it when | otherwise |
|---|---|---|
| any but `page_edit` | what it asks about is gone (merged away, archived, dropped; for a conflict, decay or follow-up also a name that resolves to no file) — retired, nothing else touched (`subject_gone`). A page that is there but cannot be parsed is never "gone" (`ask:unreadable_page`) | — |
| `conflict`, `clarification`, `merge_suggestion` | **the person's own words in a conversation answer it**: a batch's conversation is about it (`inbox_ask_gate.relevant`, over the person's turns only), the engine copies the words, and they are found exactly in one of the person's own turns (`evidence.verify`, kind `user`, never fuzzy); the conversation that raised the question (or an option's evidence) never answers it | ask |
| `merge_suggestion` | same name once spelling is folded, same type, not a person (`same_spelling`); or the judge reads both pages: `same` ≥ 0.9 merges (`judged_same`), `different` ≥ 0.9 keeps them apart (`_merge_rejected.yaml`, `judged_different`). A merge of two existing pages **folds the duplicate's page into the target** (`entity_merge.merge_entities`: its claims, ledger, sources and references follow; undo brings it back) | ask (unsure; a person — only their own words merge two people) |
| `normalization` | the two labels differ only in spelling (case, separators, a plural): "Correct fold" (`spelling_fold`); else the judge: same meaning ≥ 0.9 folds (`judged_fold`) | ask (the meaning changes, or unsure) |
| `decay` | a one-off nobody would miss: a `concept`/`tool`/`media`/`company` page on one conversation, not evergreen or durable, never kept, no claim of the person's own → archive (`one_off`); any other such page: the judge reads the page and its last mentions — clearly passing → archive (`judged_archive`), clearly live → marked active only (`judged_keep`: no mention dated today, no claim reopened, no confidence lifted — the person's "still true" stays theirs) | ask (the person's projects, skills, people, places; unsure) |
| `conflict` | a multi-valued predicate: every value was already kept, the question closes with nothing touched (`multi_valued`); the newest dated statement settles it: single-valued, every option an open claim, one said strictly later than every other (`newest_evidence`); else the judge reads each option's dates and evidence lines: one clearly better supported or newer ≥ 0.9 (`judged_conflict`) — never what only the person knows. **A label-only conflict** (an older format: no option carries a `claim_id`) is judged too: each label is tied to the page's open, non-event claims by folded text (`label_matches` — `text_fold.words`, whole words, never fuzzy: the label equals the claim's object or sentence, the object (≥ 4 characters) is a run inside the label, or the label (≥ 2 words) is a run inside the sentence — a negated label ("No longer on X") ties only by equality; on the conflict's predicate unless it is the entity path's literal `description`; a claim tied to two labels supports neither). Labels tied to nothing stay (`ask:labels_not_on_record`); the judge reads each label with its tied claims and their evidence lines, never picks a side nothing on the record states, and settles by option key through the same resolver (which, as for the person's pick of a label-only option, writes the confirmed sentence and closes no claim). **The owner's words:** a claim resting on the person's own words (their inbox answer, or a span in their own turn) is closed only by one that does too, or by a tracked source's dated re-check (ruling 26) — by no rule and no judge otherwise | ask (the owner's page; what a person is or is called; unsure) |
| `clarification` | **a name said in passing** (part 3, `in_passing`, owner 2026-10-17: "little things that are honestly not that big of a deal"): "Who or what is <name>?" about a name with **no page** (by id, name or any page's alias), said in **one conversation** (the raising one; every other conversation the lexical index finds by its spellings is checked on its own text, whole words — the index read fresh, so a conversation the batch just committed counts) and **only in passing there** (at most 2 of its exchanges name it — `promotion.exchanges`, the promotion rule's own unit) → closed through the person's own `dismiss`: nothing is written about who or what it is, the name stays where it was (the index, the pending store), and a later conversation that names it may raise the question anew. A **code identifier** (one token with `_`, `::`, `()`, `->`, a sigil or flag dash, or backticks — never case alone, so "GitHub" is no code) is assumed however many conversations name it. **Never:** a relation question ("What's the name of your <relation>?"), the person's own things (`project`, `skill`, `deadline`), **a person (or a name of no type) said in any of the person's own turns** (`ask:persons_words`, review 2026-10-17: their words about someone mean that someone may be in their life — a relation a sentence away, a pronoun Spanish drops, or none at all; only a person named in an agent's text or a document's metadata may close), a relation word (`role_people.ROLE_WORDS` plus family, teammate, colleague, compañero/a, jefe/a, novio/a… — the name's own words never count) in the turn that names a person, company or place or in the turns beside it (a song, tool or term: in its own sentence), a company or place when the person speaks of themselves in that turn or the ones beside it (I/me/my/we/our, yo/mi/nosotros…, and Spanish first-person verbs like tengo/fui/hablé), a name the owner's page says, anything from a Messages chat, or a conversation that cannot be read (`ask:unmeasured`). Stays: `ask:persons_words`, `ask:relation`, `ask:about_self`, `ask:owners_page`, `ask:messages`, `ask:named_again`, `ask:said_more`, `ask:own_type` | ask |
| `conflict` (label-only) | **the person's newest words** (part 3, `newest_words`): when labels do not tie to claims (or before the judge reads the ones that do), the record decides — every sentence of the person's own (kind `user` turns, never an agent's, never an agent's saved note) in a turn that names the subject, across the page's pointers, the raising conversation and the lexical index's hits (newest first, at most 24 conversations), that states a label (the whole label, or its distinctive run: from its first word no other label has, not a stop word or the subject's name, through the words after it, ≥ 3 characters; whole words, folded, never fuzzy). Settled with no engine when the newest day any line states a side has only **plain statements of one side** — the sentence itself names the subject (a sentence about another subject in the same turn never settles it), and it carries no question, negation, modal, avoidance or hedge, read on the raw text so a contraction is never split away ("can't", "won't", "cannot", "no longer", "stop", "avoid", "instead of", "except", "without", "from … to", "or", "should"; Spanish no, nunca, ya no, sin, en vez de, evitar) — an **older** line of theirs (or a belief tied to another label) states another side, nothing for another side is as new (or undated), and the line is located exactly in their own turn (`persons_span`) — the evidence span, the prose dated the day it was said ("confirmed by Sleep on <today>, as said on <day>"). Otherwise, when such lines exist, the conflict judge reads them too (tagged `[C<n>, <day>]`, at most 8) and may pick a side no belief states only by naming the line its pick rests on: the words located exactly in their turn, stating the picked label, with no line stating only another side that day or later and no other side's belief as new. The owner's-words rail holds: the winner is the person's own words | ask (`needs_judge`, `labels_not_on_record`) |
| `clarification`, `followup`, `conflict` | **answered already, anywhere in the record** (move 3, `said_on_record`; part 2, 2026-10-17): still open after the rows above, the question is looked for across the whole bank — the conversations its page points at (its claims' evidence and `source_episodes`, the pointers Ask's source words follow) plus every conversation the lexical index finds by one of the page's spellings (`search_service`, words only: no embedding model inside Sleep). Only the person's own turns that name the subject, in a conversation the ask gate finds about the question, reach the engine — each tagged `[C<n>, <day>]`, at most 6 conversations and 8 lines; the reply names the tag and copies the words, which must be found exactly in that conversation's own turn (kind `user`, never fuzzy, never an agent's words — and never the unmarked text of an episode an agent saved through a tool door, `ask_sources.AGENT_SOURCES`, which the evidence reader would otherwise call the person's) and become the evidence span. **Read on time:** a claim Sleep writes from the person's words is true from the day they said it (`valid_from`, and a closed side's `valid_to`, at the conversation's day; `recorded_at` today), so a March statement read in October still ranks as March's. A conflict is answered only by words said strictly after every side of it (a side with no date: never from the record), a follow-up only by words after its thread was last heard; never by the conversation the question rests on. A follow-up takes only `done`/`still`/`stopped` (a thread) or `done`/`missed`/`dropped` (a milestone), written through `progress` as Sleep's (`origin: inbox-tend`, the model as author), **dated the day the person said it** (`date_basis: episode`) — never a withdrawal or a moved date. Nothing on the record → no engine call, and lines already read without an answer are never sent again (an in-process memo of ids and a hash), so the next drain moves on. In Sleep: 4 questions per drain; in the tidy: every one, only with `judge=true` | ask |
| `divergence`, `removal` | only from the person's own words in a batch's conversation (above), or never | ask |
| `page_edit` | never — the person's alone (G198) | ask |

A question the person deferred, or one whose settle (or check) they took back, is never touched. **Never stale:** each
question is decided and settled at once, one at a time; a decision carries the content hash of every page it read, and
the settle (inside Sleep's window, or the tidy's admission, with the page lock held from the resolver's first read through its commit) goes ahead only when those pages are unchanged and an
engine-free rule still decides the same — a conversation, an edit or a Sleep batch landing in between leaves the
question for the next look (`left:changed`). A judged settle carries the judge's one-line reason, shown in its row.
**What a settle writes:** exactly what the person's answer would, in one commit that is Sleep's — `Inbox settled by Sleep (<kind>)
<date>`, trigger `inbox/<kind>/settled:<label>` (never `resolved:`, so G147's reader and every "the person said" reader
skip it), `Cicada-Author` the judging model or `cicada` — with the question's record `inbox/settled/<id>.md`
(`settled.group: sleep`, its `rule`, `reason`, and for moves 1 and 3 the span of the person's words, never a copy). A claim it
writes is authored by Sleep; prose says "confirmed by Sleep". The G113 row is `by: sleep` with its rule, kept apart from
the person's verdicts (`GET /consumption/feedback` → `sleepSettles`). **The Inbox shows these under "Settled by Sleep"**
(`SettledChecksSection`, a second closed group beside "Settled by a check"): the answer, the person's words when it
rests on them, the rule's reason and when, and **Undo** — the same `POST /inbox/settled/{id}/undo`, which for a Sleep
record (`inbox_tend.undo`) takes back exactly that commit: the reverse of its diff applied three-way onto each file as
it is now (`git merge-file`), refused whole — nothing written, 409 — when something since overlaps it; the question
returns marked `sleep_settle: undone` so Sleep never settles it again, committed as the person's (`Sleep's settle undone
<date>`), and the ledger records the undo against the rule. **The one-time tidy:** `POST /inbox/tidy` applies the same
policy to every open question — `dryRun=true` (the default) answers counts per kind and per decision only;
`dryRun=false` runs in the background (one at a time: a second start is 409), each question settling alone under the
bank's write admission and the tidy stopping before any judge call or settle once Sleep holds the pages; `GET
/inbox/tidy` its counts. **A running tidy is busy for every updater** (`/sleep/status` → `inboxTidy: true`, read by
`scripts/dev/auto-update.sh`, the app's `SleepProbe` and its install helper), and its counts are saved as it goes in
`$CICADA_HOME/inbox_tidy/<bank-id>.json` (counts and enums only, outside every bank), so `GET /inbox/tidy` still
answers after a restart — `interrupted: true` when the run was cut short (each settle had already committed alone); `judge=true` lets the judges (duplicates, conflicts, label folds, fading pages) read with the
person's chosen engine, their plan included (a plan limit pauses it). `api/scripts/inbox_tidy_dry_run.py --bank <path>
[--judge]` measures it offline, writing nothing.

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

**An agent's proposed page edit (`page_edit`, G198, owner ruling 2026-10-14).** When an agent that is not on the person's
list of agents that edit pages directly (Settings; `GET/PUT /settings/editors`, `page_editors`; Claude Code and Codex are on
it until the person changes it, owner 2026-10-14) calls `cicada_edit_page`,
the edit is checked against the page and filed as one item: `question` "An agent suggests a change to <name>: <reason>",
two closed options (`apply`, `dismiss`; no recommendation — Cicada proposed nothing), `allow_defer`, and a body that previews
each change in plain words; the item keeps `proposed_by`, `reason`, the request (`edit`), its evidence spans and the
conversation. `apply` plans the edit again on the page as it is then — a page that changed so it no longer applies answers
409 and writes nothing — writes it and commits the page with the retired item in one commit under the agent and `user`
(`storage.md`, *A page edit's commit*); `dismiss` retires the item as the person's. Both run inside the answer's write
admission, under the page lock and git's write lock. It is graded like every verdict (G113): `apply` agreed, `dismiss`
overruled — the agent's reward signal. App-only: no agent ask path serves it and `cicada_resolve_inbox` refuses it.

**G98 rule.** A multi-valued predicate never opens a conflict; an existing one is served
`informational: true` — the card lists the values and offers `Got it`, which removes the item and
touches no claim.

**Three resolution paths for a clarification:** organic (the user provides context later, Sleep
promotes it), agent-initiated (the agent asks in flow when the topic comes up), manual (the app).

**In conversation, questions come up naturally (owner, 2026-10-14).** An agent sees an item only when the
conversation is about that question's own subject — its page in scope AND its predicate, options or words in what the
person said (`inbox_ask_gate`; a decay question never comes up in conversation). It asks in its own words, or not at
all; when the person's words already answer it, it resolves it without asking (`cicada_resolve_inbox(…, quote=<their
words>)`: kept as a relay episode — the agent's text, `relayed_by` and `session_id`, untimed — cited as the answer's
evidence, the commit naming the agent and the conversation, `answered_in: conversation` on the ledger row; never in a
demo bank) and says what it noted in one line. "What is in my inbox?" lists everything (`mode="list"`). Detail:
`mcp.md`, *Questions come up naturally*.

**"What's the name of your partner?" (placeholder people, 2026-10-14).** A `clarification` with `asks: name` is
the question about a person Cicada knows only by a relation to the owner (`role_people`; written by Sleep's Stage
5.4 or the repair script, one per page, never after a decline). It carries `question`, one option
(`rather_not_say`, "I'd rather not say"), `allow_other` and `allow_defer`, and `owner_role`. The answer
(`inbox_service._resolve_name`): a typed name (`resolve` or `answer` with `answer`) that is exactly one person
page's name or alias (case, accents and spacing aside) folds the placeholder into that page through
`entity_merge.merge_entities` — the person's answer is the evidence — and records the relation in `owner_roles`;
any other name renames the page (`rename_references`: its claims, the graph's edges, every other page's `related`
and wikilinks follow; the id moves to the name's), and a person page whose name contains it or is contained in it
("Carl" / "Carl Example"), or several pages of exactly that name, gets a "Possible duplicate" `merge_suggestion`
each — never a merge; such an item carries `fold_page: true`, and only a flagged item's "merge" folds its page into
the target. An answer that reads as a relation ("my girlfriend", or the asked relation itself) or a self-reference
is a 400 and writes nothing; a bare word that is also a name ("Tia") is a name.
`rather_not_say` (or a dismiss) keeps a role title, never the owner's name, and sets `name_declined`. The commit is
the person's (`Cicada-Author: user`, `inbox/clarification/resolved:answer|rather_not_say`). The question is served
while its page is archived (it is about who the person is, not whether the page is live; `_hidden` asks
`_subject_gone` with `clarification:name`): only a dropped or merged-away page retires it. A `merge_suggestion`
flagged `fold_page` folds its page into the target on `merge`; every other item (Stage 2's, asked about a mention)
keeps the note-only answer, even when a page was promoted under the mention's slug since.
The app draws a name field, Submit and "I'd rather not say" (`NameBody`, `app.md`); an older build sees the option
and Other… and still answers it.

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

**Closed beliefs (G118/G93, 2026-10-07).** The timeline and belief chips share
`Claim.isValid`: a close date or successor means history, including a legacy
successor-only claim with no close date. Search preserves these markers and
renders a closed event with its day/state as a past event or earlier state,
using the existing row layout (DR-48) and date formatting (DR-58).

Swift claim validity uses the same machine-local day as backend claim writers:
future starts and elapsed stated ends are excluded, end dates are inclusive,
and `due` objects supply an end while milestone targets never do. `expectedEnd`
is decoded from the existing wire field. The Find palette uses this local-day
convention for its future-start label too (DR-48, DR-58).
