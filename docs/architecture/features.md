# Features: graph, inbox, Sleep trigger, upload

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

### 1. Graph Explorer
Force-directed d3 graph: node color by type, size by how connected a page is (distinct neighbours, confidence a small
second term — G109 2026-10-15, the Obsidian look: small dots, hairline links, a loose halo of unlinked pages, names
fading in with zoom; `app.md`), edge labels, cluster detection, decay/clarification indicators. Hub nodes are the hub tier's files (`hubs/*.md`, Stage 5.6): one per entity type and
one per tag shared by 5+ active pages — never provenance: a playlist, board, collection or bookmark folder is the
saved page's `folder:` / `collections:`, and a media type or capture door is its `media.media_type` / `origin:`
(`storage.md`), so none draws a node or `member of` edges (owner 2026-10-19).
**Quiet nodes (owner ruling 2026-10-20).** A node with `quiet` (a page only an import made, not mentioned yet;
`quiet_pages`) is drawn with a faint fill (`QUIET_FILL_ALPHA`) and a hairline ring in its own type hue — depth is a ring
(DR-9), never the accent (DR-5), the hues unmoved (DR-8); a hover lights it fully. Clusters' rows and tiles dim it the
same way: the name a step down the text ladder (`CicadaTheme.quietName` = `textTertiaryOnFill`, readable on every fill,
DR-2/DR-3), the picture at `quietPictureOpacity`, "Saved, not talked about yet" to VoiceOver; a selected
row is fully lit.
Open ideas live in the backlog.

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

**The hover card (ROR-135, owner 2026-11-06: "a small card with the picture and title and author … Aim for smth thats
fast and snappy too").** Resting the pointer on a node shows a small card beside it (`GraphHoverCardLayer`, SwiftUI
over the canvas, never taking the pointer): a book its cover, title and author; a person their picture and name; a
company or anything else its logo or picture, its name and the first sentence of its summary (one line, two at most); a
hub its name and "N pages"; a facet satellite none. Everything it draws is already in the app with the graph: the node
(`name`, `summary`, and `byline` — a book's authors, added to `GET /graph` nodes, omitted otherwise, node shape
`+byline`, folded into `contentHash` only when present), the picture the one precedence resolved onto it
(`Store.picture(for:)`, `storage.md`), and bytes already in `ImageMemory`. A hover does no fetch of its own and shows no
spinner: a picture not in memory is read once from the stores' own copy or the local backend, a third party's thumbnail
never (`HoverPictures`), and a page with no picture shows none — a person their initials, any other type nothing, never a
type glyph. After the graph lands `GraphHoverModel.warm` reads the 300 busiest pictured pages into memory at utility
priority. graph.js adds one thing, `reportHover` at the end of `draw()`: `nodeHovered` (id, screen centre, radius) on a
change only, and `hoverEnded` once when the pointer leaves or a pan, zoom or drag moves the node from under the card — a
pan posts nothing per frame, and none of it reads or writes the simulation (G109). The card opens
`CicadaMotion.hoverCardOpenDelay` (0.1 s) after the pointer settles, so sweeping across the graph opens nothing, and at
once while one is up or within `hoverCardWarmWindow` (0.3 s) of one closing; it fades with `CicadaMotion.hover`, a swap
does not. Hidden while the entity column is open (the hover is quiet then, R-DG10), the Legend or find is up, or the
page is. Measured at 9,000 nodes (`Tests/graph/graph-hover.test.js`, `GraphHoverCardTests`): a pointer move with its
report 0.06 ms (p95 0.07), a pan frame's report 0.04 µs, the card's content for a hovered page 2 µs (p95 2.8 µs).
Applies DR-2, DR-5, DR-9, DR-10, DR-12, DR-52, DR-70.

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

**Pages v2, part B (2026-10-29; ruling 48 parts 5, 6 and 14; DR-77).** *History* is `EntityHistoryView`: DR-45 tabs
All · You · Agents · Sleep · Upkeep (All leaves upkeep out; counts once every change is read), rows grouped Today /
Yesterday / the day, a thin line down the leading edge with one node per change in its writer's picture
(`HistoryWriterMark`: the model's mark, an agent's own mark, Cicada's for upkeep, and for the person the owner page's picture by G146's ladder), Sleep a `Tag` beside the sentence, a Sleep row's
up to four changed lines always shown (DR-81: nothing folds), hover or focus showing who, what changed and when, a click
pinning that card with the change itself (`DiffView`). It reads 30 rows when the tab is first shown and 30 more per
*Older changes*; the card open reads none (`api.md`, part B). *Places:* `LocationHero` is `PlaceMap` — a muted
`MKMapSnapshotter` still (page pin bold and labelled, nearby places small; memory and `Caches/Cicada/place-stills`,
outside every bank) drawn after first paint, *Open in Maps* / a click opening a live SwiftUI `Map` sheet, *Not this
place* under the still. A place with no coordinates is resolved once by `MKLocalSearch` when `GET …/place` says it is
public (then up to five more public places, 1.2 s apart, once a session, so the nearby pins fill in); a private place
says so and waits for *Place on the map*. No Location Services: nothing asks where the Mac is. *In short*
(`InShortBlock`) leads the Content tab with a `Sleep · <day>` Tag and its basis line; part A's layout owns its final
slot.

**The entity card (DS-3a).** One component, `EntityDetailCard` — the Graph's column, Clusters' card. Header:
the type as a `Tag`, status and confidence in words ("Active · very confident", the number in `.help`) — or, when
the page's `lastReferenced` is more than 90 days before the viewer's today, the status and when it was last mentioned
("Active · last mentioned Feb 2025", G194 A2: the confidence word is replaced, the number and the full day go to
`.help`). The three bands behind those words — confidence, fade pace, the old day — are served by the backend as
`bands: {confidence, fadePace, lastMentioned}` on `GET /entities/{id}` (`entity_bands`, G180 parity; not a
Store domain); the app's `EntityHeaderWords` / `FadeWords` twin paints them from the existing fields and is pinned to
the backend by one table, `api/tests/fixtures/entity_bands.json` (`EntityBandsTests`). Words stay in each client. The
name, the page's Summary, **the one "why it matters" line under it** (`relevance.line`, owner ruling 44 — `metaFont`,
`textTertiary`, never on the owner's own page or a graph stub; DR-2, DR-16, DR-37, DR-38), Back ⌘[ and ×; text tabs Content · Perspectives · History · Timeline with counts once
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
action) that opens each link's bookmark card and its view menu (also a right-click on the line, and a ⋯ on every card);
a link in a sentence is a mention, a link alone on its line a card row of its own (app.md, *Links show as what they
are*). `/provenance` is read when the card opens — the header's
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
`.help`. A location page's map is a picture of where it is, never a scroll trap: since part B it is a still image
(`PlaceMap`), so the column scrolls with the pointer over it, and a click or *Open in Maps* opens the live map. A page with
thousands of beliefs stays usable: what the tabs show from the claims is derived once per load,
off the main actor (`ClaimDigest`), Perspectives builds its rows lazily, and a belief list grows twenty rows per
"Show N more" (`BeliefPaging`), never all at once. History: DR-77's line and rows (part B above), 30 at a time;
*Older changes* reads the next 30 with `?skip=N` (`HistoryPager.pageSize`, pinned to `page_history.DEFAULT_LIMIT` by
a test). Timeline: contested beliefs inline; a belief's clock opens its own.

**Pictures and the person card (G146, round 4).** Every entity avatar is `EntityPicture` over the one picture
precedence (`entity_picture.resolve` and its Swift twin `EntityPictureResolver`, one fixture): the person's own upload
or "initials" → a person's Contacts photo → a person's public-profile photo (G159, 2026-10-09; "Photo from their public
profile", served from Cicada's own copy at `/entities/{id}/photo`, with Change and "Use initials instead" like any
detected picture) → a brand's logo → a media page's thumbnail → a person's ring monogram, never a solid
fill — any other page with none draws nothing, never a type glyph (owner 2026-10-28; an empty slot in a list where
other rows have pictures, else no slot, `EntityPictureLayout.isEmpty` / `anyDrawn`); `PictureStore` holds uploads, Contacts photos, public-profile photos and media previews by URL — all on Cicada's own API with the bearer
(a media page's picture is the backend's stored `/entities/{id}/preview?v=…`, and `MediaPreview`, `HeroPreview` and
`VideoThumb` draw the same stored copy through `StoredPreview`; no view loads a provider's thumbnail) —, `LogoStore` the
logos. **The picture is the control (owner 2026-10-29, "you change the picture by pressing on the picture itself"):**
a click on any editable picture offers its choices (`PictureChoices`) — the image picker at once when a file is the only
choice, else a menu under the picture with the right-click menu's own items (*Change picture…*, *Remove picture*, *Use
initials instead*, *Use the logo*…); a saved item's picker also takes a PDF (the backend draws its first page,
`POST /entities/{id}/picture/pdf`, and nothing is painted before that answer); it takes a dropped image, dims under a
camera with a link cursor on hover, and is a button VoiceOver names "Change picture for <name>". Nothing stands under a
page's name about its picture: no blue words and no source caption — where it came from is the picture's hover, its
VoiceOver value and the quiet first line of its menu ("Picture you added", "Photo from your Contacts"); a non-person
page that draws none is given *Add a picture…* in its page menu (•••), never an empty spot. **Only inside the entity page
(owner 2026-11-06, on the Clusters People strip: "i dont like that clicking in the pfp bubbles takes me to change the
pfp. Have that only inside the entity page"):** `EntityPicture(editing:)` is passed only by the page's own header
(`PersonHero` `.hero`, `EntityCardHeader` `.tile`); the Clusters tile, face, lead and name row and Settings → You draw it
plain — no camera, no menu, and a click anywhere on the cell, the picture included, opens the page. The app shrinks the
picture (ImageIO, ≤ 512 px) and `EntityPictureWrite` paints the answer before the server gives it. A `person` opens
with mock C's top (F-12): an 88 pt picture, the name at 24, the Summary as a two-line standfirst (a click unfolds it and the header grows; *Show less* folds it —
a capped Summary or name is never selectable, since a selectable field opens over its neighbours on a click), the
facts strip whose every cell comes from something the card loaded (`PersonFacts`; Works at names every current place,
newest first, each opening its own page, two then "+N" with the rest in its help — 2026-10-14; Known since, Last mentioned and
Conversations are when the conversations were said, over all of them — `/provenance`'s `totals` — with the page's own
dates only as a fallback; Known since gives its span only from two weeks on — a recent day alone, never "Oct 18 · 1 day", say it once 2026-10-19); then the tabs, and in Content the page like every other type, one column; behind its
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
was made for. A conflict's new value lives only in the question until it is answered (`claim_reconciler._place_claim`), so
an answer that keeps a value writes it (`inbox_service._hold_offered_value`): "both", a pick, and a dismissal on a
multi-valued predicate. It is dated when it was said, carries its conversation, and is the person's only on their own
answer. A value they picked against is not written. Between a
drain's batches it commits alone.

**The order is the expected change in what gets read (ruling 70, owner 2026-11-06; supersedes vision item 10's
"priority + 0.5 × use", 2026-10-28).** Owner: "the questions should have in order the impact they might have on current
accesses knowledge, and things that might have big impact." `question_order.Tables.score` orders all three places the
list is met — `load_inbox` (so `GET /inbox` and Home), `inbox_catchup.select` and `cicada_check_nudges(mode="ask")`
(`mcp.md`, "Catching up") — pending first, then the score, then newest, then id. It is derived on read from the record,
never stored; the stored `priority` stays on disk and on the wire for older clients and **no longer moves the order**
(before this, the app re-sorted `GET /inbox` by raw `priority` on the client, so the server's use-weighted order was never
what the person saw; `InboxColumns` now follows the server's `orderIndex`, `app.md`).

**A "same as?" question about pages spoken of lately asks first** (`question_order.recency`, Rodrigo 2026-11-06: two names
"have come up a lot lately ... that's why recency is important"). A merge question between two existing pages is
multiplied by `1 + 2 x 0.5^(days / 14)` for the older of the two pages' newest conversation (up to 3x the day both
were spoken of, 1.5x after two weeks, 1 in time). It only raises: who someone is still does not fade (ruling 70), and a hub
always in use or a name with no page yet carries nobody else's pair. One type at a time still spaces the wall.

**What has come up lately lifts a question (owner 2026-11-06).** Owner: "<a-person> and <another> have come up a lot lately.
Thats why recency is important." `lift = 1 + 2 x lately` of the question's page said most lately. `page_use.lately` counts the
conversations naming a page, each halved every two weeks from the day it was said (the id's day, never `last_referenced`; a
memory export entry or feed item is no mention), log-scaled against the page said most lately. The owner's page is said in
nearly every conversation, so on it the fact in question counts instead. A "same as?" question keeps `recency` above. A conversation
waiting for Sleep doesn't count until it's read. Measured read-only on a clone of a real memory, 663 open questions, with no
read counter, conversations in the last 14 days on the question's page:

| Weight | Mean, top 10 | Mean, top 50 | Pages quiet for 14 days, top 10 / top 50 | Owner's page, top 10 / top 50 |
|---|---|---|---|---|
| 0 (before) | 5.4 | 5.2 | 4 / 18 | 3 / 4 |
| 1 | 6.6 | 9.2 | 3 / 12 | 2 / 4 |
| **2** | **10.9** | **11.1** | **2 / 10** | **1 / 3** |
| 3 | 11.0 | 12.0 | 2 / 9 | 1 / 3 |

Two shapes failed first. Inside `exposure` (`1 - (1 - use)(1 - reads)(1 - lately)`), a busy page has no room to rise: the top 10's
mean fell. A plain share (`1 - 0.5 ** n`) read .98 or more on the ten most-said pages. Past weight 2 little moves until the same-as questions start to fall. The
cost is the owner's own questions on old facts, which fall under pages said this week.

    score = p × stake ÷ effort × (FLOOR + exposure) × √seen × freshness     FLOOR .1 · SHOWN 30 · FADE_FLOOR .05

* **`p`**, does an answer change anything against never asking (judgment): conflict .9 · "still?" .5 · informational
  conflict .05 · duplicate pair
  `suggested_confidence` clipped .1–1 (default .5) · clarification .6 · decay .3 (silence archives it anyway) · removal
  .9 · page edit .8 · normalization .9 · divergence .6 · follow-up .5 · the grouped links review .8. A `sensitive` hold
  is the constant 3.0, on the formula's own scale (≈ .01 to 6). Agent requests never reach `load_inbox` (the router
  prepends them).
* **`stake`** 1.5 when the answer decides who someone is (`asks: name`, or a duplicate pair of two people), .5 for the
  grouped review, else 1. **`effort`** 1.5 for `required_input: freetext`.
* **`exposure`** = 1 − (1 − `use`)(1 − `reads`) for the busier page of the question (a "still?" question's pages are
  its `object_id` alone: the owner's page holds the claim and is pinned at use 1.0, and an older item with no `object_id`
  earns the floor only). `use` is `page_use` (what was
  *said*, derived; works with no counter). `reads` = r ÷ (r + 3) of the page's counted reads (`storage.md`, "Page-read
  counter"; what was *read*). With no counter it is 0 and the order is `use` alone.
* **`seen`** = min(30, `reach` × `visibility`), `visibility` = min(1, √(30 ÷ N)) for the N claims on the page the facts
  live on; **the owner's own page does not dilute** (owner 2026-11-06, judging the real top 10: "facts about the person
  matter most", and a recent one fell to 298th under their page's size, now 12th; real text redacted). `reach` is what the resolver changes: a conflict its contested claims (≥ 2) · a divergence 2 · a duplicate pair
  the smaller side's claims + the held claims of a name with no page + 1 (a side with no page counts 0, never the other
  side's) · decay its covered claims, else the page's · a removal the page's claims · a plain clarification **1** (an answer
  appends one claim and prose); only `asks: name` and a held-mention release earn the page's or the held claims ·
  normalization its folded claims · a page edit its changes (prose has its own read budget, visibility 1; a proposed join
  counts its pages' claims) · a follow-up 1 · "still?" 1 with visibility 1 (the item stores the owner as `entity_id`, so a
  new one also stores `object_id`, the topic's page) · the links review its rows at stake .5. Every kind's reach is ≥ 1.
  The count is a raw count of claim lines in the page and its `.claims.jsonl`, memoised by file stamp: no parse, and no
  body is read for a page no question names. A merge also rewrites references on other pages, which the count leaves out.
* **`freshness`** (owner 2026-11-06: "the questions in regards to the amounts of <a-payment> are extremely
  old and in this case shouldn't they be lower impact? The impact formulation should apply to the question queues in all
  entities."). `freshness = relief + (1 − relief) × fade`, `fade = max(.05, ½^(age ÷ half-life))`. **Age counts from when
  the thing was SAID** — for a conflict the freshest of its contested options: an option on a claim the page holds,
  `source_refresh.said_on` of that claim (read from the page's and its ledger's claim lines, memoised by file stamp and
  built only for a page that holds a conflict question); a claim only the option holds (the new side of a conflict is stored
  nowhere else), the conversation the option names, its `observed_at` (the claim's `valid_from`) only when it names none and no other option has a date; an option with no claim,
  the question's `source_episode`, never `observed_at`, which on these is the day the question was raised (measured: 120
  of 153 on one bank). A memory export entry or a feed item is no mention (`episode_time.counts_as_activity`, one header per id): it counts only
  when no contested option has a real date, and then as "no later than" its id's day, so what only an export said still
  fades. Known limit: a later side merged into an open claim-less question has no date of its own, so the question reads
  from its first `source_episode`;
  for a divergence, a plain clarification and a follow-up, the `source_episode` id's
  date. **Never** `last_referenced`, `created_date` or `updated_date`: a later re-reference or the day a
  question was raised bumps them for something said a year ago (the shape that prompted this: a conflict on the owner's
  evergreen page, both options said over a year ago, one option's `last_referenced` reading today, `created_date` today).
  A fact said again recently (a newer `source_episodes` entry) or one side of a conflict being recent makes the conflict
  fresh; no date means no fade; a future date is age 0. **Half-life** = ln 2 ÷ the page's weekly rate from
  `decay_policy.resolve` (durable ≈ 243 days, active ≈ 97, volatile ≈ 32; no constant per class here); an evergreen page
  never fades **except the owner's own**, whose class means "never archived", not "every fact stays true": it fades at the
  `active` rate. A timeless fact on that page fades too, accepted by the owner until ROR-129 gives facts their own class.
  **Relief** = the largest, over the question's pages, of `reads_fraction` × `visibility(N)`: an old fact on
  a small page opened daily stays fresh, and opening a huge hub daily does not rescue every old fact on it; the owner's
  page dilutes here too, or a daily look at it would exempt everything on it. **"Still?" fades** (owner 2026-11-06), from
  its claim's last saying at the holding page's rate, relieved by its topic page's reads. **Does not fade:** who someone
  is (a duplicate pair, `asks: name`, a held-name release; owner 2026-11-06), `decay` (age is what it asks about, and its
  `p` already says so), and a removal, normalization, page edit, sources review or `sensitive` hold (not a fact someone
  said). This replaces the earlier stale-escalation `p` (a `neither` option made a conflict .5): staleness
  is counted once, here.
* **One type at a time (owner 2026-11-06, judging the real top 10: 9 of 10 were "same as?").** The score stays;
  `question_order.spaced` takes a list in score order and lets at most `RUN_LIMIT` = 1 question of one `family` run: "same
  as?" (a duplicate pair or a proposed page merge), `asks` where it is set, else the kind. When a run reaches the limit the
  best question of another family comes forward. The first place is always the top score, a family's own order never
  changes, a family runs on when nothing else is left, and a question shown, never asked is neither brought forward nor
  counted. `load_inbox`, `ranked` (the hook, recall's block, list mode), the catch-up and ask mode all pass through it; a
  subset that `ranked` receives is spaced among itself, and a page's queue keeps the served order. **Why one, measured on
  one real memory (659 open questions):** two left "same as?" at 7 of the top 10 and 33 of the top 50, still the wall, for
  1 % of the top 10's score; one leaves 5 and 25 for 5 %, and every question in the top 10 still scores in the high bucket.
  Three members of one same-person chain count as a run though the app draws them as one card, so a chain can be spaced
  more than it needs.
* **Failure is per item.** `score()` never raises: a question it cannot read keeps its stored priority, so one bad item
  never costs `GET /inbox`. `GET /inbox`'s ETag folds the wire shape (`question_order.SHAPE`) and the counter's *day-cut*
  digest, which moves at most with the day, so there is no rebuild per read.

**Four formulations were run on a synthetic bank** (`test_question_order.py`): F0 the old order; F1 additive (priority +
.5 use + .5 log-impact); F2 the product without `visibility` (and without `freshness`); F3 the above. Twelve argued pairs,
each with its reason in the test (the last four are staleness). Measured:

| pair (better first) | F0 | F1 | F2 | F3 |
|---|---|---|---|---|
| a conflict on a moderately used page > a held name that only inherits a huge page's use | ok | no | no | ok |
| a same-person pair of two mid pages > one conflict on an 8,000-claim hub | no | no | ok | ok |
| opened daily, rarely talked about > the same question unopened | no | no | ok | ok |
| a big merge on an unopened page > a trivial question on a moderately busy page | no | ok | ok | ok |
| recall-only < opened | no | no | ok | ok |
| a 5-way conflict > a 2-way one | no | ok | ok | ok |
| a choice > free text, otherwise equal | no | no | ok | ok |
| an informational conflict last | no | no | ok | ok |
| a conflict said over a year ago < a recent conflict of the same stake | no | no | no | ok |
| a fact said again recently > the same fact said once, long ago | no | no | no | ok |
| an old fact on a small page opened daily > the same fact on an unopened page | no | no | ok | ok |
| an old fact on a small page opened daily > the same on a very large page opened daily | no | no | no | ok |

F0 passes only the first, by a margin the use term alone gives; F1 sees neither reads, effort, `p`, dilution nor age; F2
sees reads, effort and `p` but not that three claims among 8,000 are almost never in front of a reader, nor that a fact
said a year ago asks less (it passes the third staleness pair only because reads are in its exposure) — which is why F3
carries `visibility` and `freshness`. An empty, wiped or unreadable counter orders exactly like `reads=False` (relief 0).
Measured on a synthetic bank at 8,000 pages (this Mac; fresh process for "cold", three runs each, wall clock): a cold
`load_inbox` 1.6–1.7 s before and 1.6–1.7 s after (the first old run 2.6 s); a warm rebuild 495–527 ms before and
478–555 ms after; a hit 30–34 ms and 29–35 ms.

**Every constant is judgment.** The person's own answers on record number two across all banks, so there is nothing to
fit; the pairs are the argument, not a fit. The `impact` bucket (high ≥ 1, mid ≥ .3, low) rides every resolution row of
the telemetry ledger (taken at admission, before the resolver writes: a merge removes the page it scored, which the older
`page_use` bucket, read after the write, still gets wrong) so a human reading `GET /consumption/feedback` can check them.
Nothing learned from it is auto-applied.

**Measured on one real memory (2026-11-06, 659 open questions, read counter empty, aggregates only).** The question that
prompted the fade, a conflict on the owner's page said 13 months ago and re-raised that day, went from first in the old
order (priority + .5 × use, a 14-way tie broken by newest) to 633rd, and from first to last of 8 on its page: its score is
0.06 of a conflict on the same page with the same stake said the day before. The old top 10 held 10 conflicts with bare
values that can't be understood as asked; the new one holds none, and 9 of its 10 are merges (40 of the top 50). Conflict
freshness: 106 at ≥ .8, 50 at .3–.8, 18 below .3. **Stability with every constant moved ±50 %:** one at a time the top 10
keeps 97 % on average, worst 70 % (the stake bonus halved); all together at random, 200 runs, 83 % on average, worst 60 %. After the owner's judgment the same day (one type at a time, the owner's page undiluted, "still?" fading): the served top 10 has 5 "same as?" of 10 and 25 of the top 50; 96 % and 80 % one at a time, 77 % and 50 % all together; the shape of the complaint is 0.06 of a recent same-stake conflict on the same page and 5th of that page's 8.
So the exact places are soft and the broad shape firmer; in the earlier prototype this formula was the least stable of the
four compared. Hook pick among 27 conflicts on that bank, warm: 1.3 ms.

**How it can be wrong.** The `p` values are judgment on two answers. √ visibility assumes a read is aimed by words, not
uniform. A conflict on the hub the person cares about most can rank under mid pages. Bigger is not more important: a long
page of noise reaches further. The busier-side exposure undersells a tiny, often-read page that joins a big quiet one.
Reads lag a day (today's count from tomorrow). **A timeless fact on the owner's page fades**, because nothing on a fact
says it is timeless (a birthday, a place of birth said once a year ago is as old as a payment amount said then); relief is
the only thing that keeps one fresh, and only through reads. **With the counter off or empty, relief is 0**, so an old
fact on a page the person opens every day fades like any other. `exposure` still uses `page_use`, whose recency reads
`last_referenced` at page level — deliberately: that measures the page's *use*, not the fact's *age*.

**Limits, stated.** A project timeline's `200` counts as an open (bounded by the one count a page a day,
`routers/projects.py`). A replica's order uses `page_use` alone and differs from the home's; a home move starts with an
empty counter. A person who opens a page and then answers from its questions strip still counts as a read: no origin is
carried (`EntityDetailCard` has none), so the loop guard is the next-day delay and one count a page a day. **Known and
left:** the stale-question wording in `inbox_questions.py` still reads `last_referenced or observed_at` (another session
owns question wording); `HomeQuestions.swift` and `HomeSections.swift` (the UI climb's) still describe "the server's
`page_use` order" and must say `orderIndex`; the app's `surface: "inbox"` for a card opened from a question.

**One order everywhere (owner 2026-11-06: "the same score orders every queue: the Inbox columns, Home's lead, catch-up,
the agent's ask mode, and each page's own question queue … A page's queue must not fall back to raw priority").** Every
place that sorts or picks questions: `load_inbox` (and with it `GET /inbox`, whose `orderIndex` the app sorts by),
`inbox_catchup.select`, `cicada_check_nudges` in `ask` mode **and** `list` mode, recall's open-question block
(`mcp_tools._relevant_inbox`, ordered only when more questions pass the gate than the `RECALL_INBOX_SHOWN` it shows, so
the recall path builds no tables for the usual one or two), the recall hook's one pointer (`hook_recall._open_question`,
which runs in the backend through `POST /capture/hook-context`; ordered only when it has more than one candidate),
`web_settle.candidates` (a lookup's kind order first, since it says what a lookup can answer; the served order inside a
kind — `web_lookup._order` is a stable sort over that and never read priority), `search_service`'s inbox hits (text match,
then bm25; priority dropped from the tie-break) and the palette's tie-break in the app (`QuickIndex.inboxDocs`: `orderIndex`
when every question has it, priority only for an older server). A page's "A question · 1 of N" strip, Home's lead and rows
and `Store.visibleInbox` keep the snapshot's order (`HomeQuestions.onPage/leads/figures` filter and never sort), which the
new `QuestionOrderEverywhereTests` proves with priorities that oppose the served order. The remote door's `list` and recall
orders are computed without the counter (`reads=False`). `test_question_order_gate.py` scans `api/` and the app's sources
for a sort or pick keyed on a question's raw priority and fails on a new one; its allowlist names the five fallbacks
(each with its reason) and fails when one stops existing.

**What the hook and recall paths cost** (synthetic 8,000-page bank, 25 conflicts on an 8,000-claim owner page, three runs
each; old = the previous commit's priority sort): the hook's pick among 27 candidates 7.4–7.5 ms before and 8.7–9.1 ms
after, warm; 8 ms before and 67–69 ms after when the order's tables are cold in a running backend (the pages already
parsed: one `page_use` rebuild, at most once a minute); 15 ms before and 0.7–1.5 s after in a fresh process that has
parsed nothing, which is why `question_order.warm` runs at launch (like the search index and the sensitive-hold warm-up).
Recall's open-question block 177–187 ms before and 204–220 ms after, of which the ranking itself is 1.2 ms; the rest is
allocator and collector pressure (with the collector off both are 143 ms), on a path whose cost is the 8,000-claim parse
of the owner's page that was there before. Recall cold: 360 ms before, 1.04 s after in a fresh process.

Two additive question shapes feed the catch-up chat: `asks: still` on a `conflict` ("Are you still working at <org>?",
`still_questions`, `capture-and-sleep.md`) and `detected: spelling` on a `merge_suggestion` (a nickname and its long form,
`inbox_catchup.propose_nicknames`); an older app draws them as a one-choice conflict and a duplicate pair. A "still?"
question is never `informational`, whatever its predicate's cardinality.

**Plain words on the wire, and the in-app catch-up (ruling 48 (1), (8), 2026-10-28).** `GET /inbox` serves each
conflict, decay, clarification, duplicate and follow-up with `spokenQuestion` / `spokenReason` — `inbox_wording.spoken`
over the pages the read already holds (`InboxContext`, the owner's id once per read), derived and never stored;
additive, so an older app draws `question` as before. Because those words carry relative ages, `GET /inbox`'s ETag folds in today's date (`_served_day`):
a new day is a new tag, never a 304 holding yesterday's "yesterday" (DR-58). **Question words (2026-11-06):** the same
read words a conflict's answers and a few stored questions (`inbox_wording`, nothing stored, no sweep; keys, labels as
stored and claim ids untouched), and `inbox_wording.SHAPE` rides the ETag so every client takes one fresh 200.
`present_options(fm, today, claims=, page_name=, untimed=)` is pure and idempotent and is called by all three doors: the
served list (`inbox_service._item_from_file`; the recommended key, the cause and the verdicts keep the stored options),
the catch-up (`inbox_catchup.spoken_for`) and the MCP readers (`mcp_tools._agent_question`). A claim-backed side is dated
by when it was *said* (`source_refresh.said_on` for a claim on the page, else the day of the conversation the option
names), on both `observed_at` and `last_referenced`, never by `valid_from` or by when Sleep read it; with no
conversation it is undated, and a rebuilt `Last mentioned <day> · <age>` carries no stored age and no `ep_` id. A
description conflict's sides hold only the day the question was raised: no date, and the contradiction check's working
words ("Existing description, …") dropped. On a relation predicate a label that is exactly a page's id reads as its
name. The conflict's reason says "same conversation" only when every side has exactly one conversation and it is the
same, "same day" only when every side is dated alike, counts three or more, and with fewer than two dated sides names
no date. A stored question is said to the person (a first-person question turned all or none; the owner named only in a
safe verb frame, from the bank's own name, never on another person's page), a bare `value-of-<noun>` question names the
noun, "You mentioned X" became "X came up" where Cicada cannot know who said it, a decay question's answers are "Yes,
keep it" / "No, archive it" (keys `keep` / `archive` unchanged, served and never stored), and the one page edit Cicada
proposes itself, dropping an alias another thing owns (`wrong_aliases`), is asked "Should “X” stop being another name
for Y?" with its why as the reason and "Yes, stop using that name" / "No, keep the name" as its answers (keys `apply` /
`dismiss` unchanged); every other page edit serves its stored question and no reason. A generic conflict question names
its answers only when there are exactly two and neither is clipped; with three or more, `both` reads "All of these are
true" (key and what answering it does unchanged). A decay answer shows no confidence number. The Inbox draws
`askText`/`askReason` everywhere it shows the question. Forward writers: `inbox_questions.refresh_open_questions` bumps
an option by when its claim was last said (a late read does not bump; a later re-saying does), `claim_reconciler`
writes `Last mentioned <day>` plus `source_episode`, and the contradiction prompts ask for a question to "you" and a
label of what the statement says. The built-list cache (`inbox_service._BUILT`) is in memory only, so a new release
never serves old words from it. The app's catch-up chat (`app.md`, "Catch me up") adds two
routes. `POST /inbox/catchup/turn` `{itemId, message, history, upcoming}` is one turn of the conversation
(`catchup_chat.turn`): the engine is resolved as Ask's is — `engine_select.resolve_settings(user_triggered=True)`, a
person asking is a person present (rulings 4/31/46: never a metered key nobody chose) — and with no engine to call it
answers `{"engine": false, "why": …}` and spends nothing. The model gets the open question in its plain words with
its answer keys, what Cicada has on the page (`catchup_chat.context_lines`: its type, when last said, in how many
conversations, a few current beliefs), the upcoming questions it may move to, and the chat so far; it answers
`{reply, reading, move, nextId}`. The turn **writes nothing**: a `reading` is kept only when its `quote` is found in
what the person typed (`evidence.locate` — exact, whitespace, case; never fuzzy) and a free `answer` too, its key is
one of the question's, and a free answer only on a question that takes words. **A clear reading applies at once** (owner
2026-11-05, replacing a coordinator's call on #509): the turn returns `readings`, every part the message settled, one per
question (the one asked, a chain's pair, an upcoming question), and the app applies them through `POST
/inbox/{id}/resolve` with each part's located `quote`, `relayedBy: cicada-catchup` and the chat's session, held together
under one Undo; a move to *later* is applied the same way. The model judges clarity in context (a hedge about their own
life is their answer) and says what is unclear in the reply instead of a reading. A question given two different
answers holds neither. "A is C" over a chain with no such pair (a `join`) is carried by a pair the same message parted
whose subject is A, a merge of A into C (`mergeTarget`); no such pair and it comes back in `unjoined`, closes nothing,
and the app says so. `POST /inbox/catchup/record` `{sessionId, turns}` keeps the chat as ONE episode per
session (`episode_staging`, `source_id: catchup:<session>`, `source: companion_app`, `origin: catchup`; the person's
turns as `user`, Cicada's as `assistant`; re-posted in place and re-queued), so Sleep reads a follow-up answered in
passing like any conversation (ruling 29 part 1 may settle a question from their located words); never into a demo
bank. The message is never logged. Write-admission classes: the turn `NONE`, the record `CAPTURE`.

**Same-person chains on the wire (2026-10-29).** `GET /inbox` also serves #501's read-time grouping
(`inbox_catchup.groups`, `inbox_service._mark_chains`): open duplicate questions about people that chain into one
person (three names or more; never a tool, a project or a held name) each carry `chain` (the members' ids, served
order), `chainQuestion` / `chainReason` ("Are A, B and C the same person?") and `chainPairs` (`{id, a, b}`, each pair's
names as said). Additive; nothing is joined by serving it. The app asks the chain once and answers it pair by pair.

**A count is what the inbox serves, never a count of files.** `load_inbox` skips a deferred item and
one whose subject is archived, dropped or (for every kind but `clarification`) gone; those files stay
on disk. **A quiet subject is never asked about either (owner ruling 2026-10-20):** a page only an import made — a
saved link, video or playlist item the person has not mentioned (`quiet_pages`, derived on read) — hides its items
from `/inbox`, the counts, the palette (`search_service`) and every MCP reader (`mcp_tools.nudge_visible` with the
bank's path, the recall hook); the files stay, and the person's first mention brings them back. `inbox_service.served_counts` applies the same `_hidden` predicate over `bank_index`
frontmatter, and it is the only source of `/status`'s `inbox.total`/`byKind` (the menu bar) and the
hub's pending count — on 2026-10-06 the raw file count said 49 while the inbox served 35.
**A read of an unchanged inbox builds nothing (speed, 2026-10-29).** `load_inbox` keeps its built list per bank
(and per `include_deferred`) on the stamps of every input it reads — the day, the fingerprints of `inbox/` (with the
legacy folders), `entities/` with its claims ledgers and `episodes/`, and the files beside them
(`inbox_inputs.side_stamps`: `_predicates.yaml`, `pending_entities.jsonl`, the owner's id from `_state.md`); any of
them moving rebuilds, and each caller gets its own list. The same side stamps ride the `inbox` sync component and a
ledger's stamp the `entities` one (2026-10-29), so the ETag never 304s over a change the read would show; a bank
without those files keeps its stamps byte for byte. `GET /inbox`'s ETag and the read share one listing per directory (`bank_index.shared_scans`), and an ETag computes
only the components it names (`sync_service.components(keys=…)`). A rebuild re-parses only the item files that moved
(`bank_index.file`), reads the predicate map once (the context's vocabulary), and reuses each cut excerpt while its
episode's `(mtime, size)` and span inputs are unchanged (`inbox_context._excerpt`). At the owner's scale (423 questions,
8k pages, 8.5k episodes, a read-only copy) the warm body went from ~515 ms to ~65 ms of CPU (the floor is the ETag's
stat walk), a read after one changed item from ~445 ms to ~245 ms. `/status` counts the inbox from the built list
when it is current (`served_counts`), and `/status`, `/origins` and the card read one listing per folder; `/origins`
is remembered per state of both folders (`origin_stats`). Round 3 (2026-10-29): `/status`'s episode counts are one pass remembered per state of `episodes/`, and its inbox count is remembered on the built list's own inputs (`served_counts`); the `inbox` sync component carries a digest of the owner's page id, never the id.

**The read is one listing, not one per item (inbox lag, 2026-10-17).** Most hidden items name a subject with no page
under any spelling (merged away, renamed), and `resolve_entity_file`'s case-insensitive rung used to glob `entities/`
for each: ~6 s per `GET /inbox` at 4,700 pages and 900 items. It now reads one cached stem index of the folder
(`id_utils._stem_index`, rebuilt when the folder changes), the subject's status comes from `bank_index`, and
`GET /inbox` (and the deprecated `/nudges`, `/clarifications`) run `load_inbox` in a worker thread, never on the event
loop (`test_inbox_load_perf.py`; the 0.5 s budget at that scale is the `bench` tier, `make test-bench`). In the app, an Inbox row's
age and source day parse through formatters built once with each stamp's answer kept (`ISOStamp`), since the question
list is a non-lazy stack that draws every row on each render.

**A rebuild never searches (G209, 2026-11-05).** A person question whose own and pages' recent conversations do not name
both sides asks the lexical index for one that does, on every rebuild of the list, which is any read after an answer or a
Sleep batch. It asks one query per card over one connection (`search_index.episodes_naming_each`, `one_reader`): the sides
may sit in different passages, nothing is built, refreshed or started, and with no index the card keeps its usual tiers
until the list next rebuilds. Fixture: 4,700 pages, 913 items, 221 such cards, no conversations. CPU per rebuild: 0.19 s
before the tier existed; 10.6–15.9 s with four `search_service.search` calls a card and no index yet, 0.52 s with one;
now 0.23 s and 0.24 s. A conversations-only search with no index also returns at once instead of walking every page's
frontmatter. A bank with 5,000 synthetic conversations: 10.4 ms a card before any hit was read, now 4.0 ms, 1.4 ms when
one side names nothing.

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

**Groups (owner 2026-10-26).** Under All the list is one collapsible group per kind with its count and its quick review,
and inside a group the questions about one page sit together under its name (`app.md`, *The Inbox in groups*). Display
only: `GET /inbox` and every resolver are unchanged, nothing is answered for a group, and the walk follows the groups.
**Inbox v2 (owner 2026-10-26)** is display only too: kinds in a person's words with one sentence each, the possible
duplicate's two pages side by side with what Merge does, and *Confirm N links* saying what each link is, why it is there
and what confirming changes; every fold eases open on a click and lands in one frame on a key (`app.md`, *Inbox v2*).

**The quick review (owner 2026-10-19).** The app reviews one kind at a time (`app.md`, *The quick review*); every
answer is `POST /inbox/{id}/resolve` through the same resolvers, provenance the person's, after the same Undo window —
there is no bulk accept. To decide without opening the page, `GET /inbox` serves two more fields derived at read
(`api/services/inbox_review.py`, engine-free, never stored, a failure costing the field and never the card): a `decay`
or `normalization` item carries `subject: {summary, conversations, lastSaid}` — the page's lead sentence (frontmatter
`summary`, else its `## Summary`, first sentence, ≤ 200 characters), how many distinct dated conversations its
`source_episodes` hold and the latest of their days (`decay_policy.conversations` / `latest_said`, a memory export entry
or a relay counting as none, as decay counts them); a `normalization` item also carries `fold: {raw, canonical, claims,
pages, example}` — the label as said and the predicate it was filed under (in words), how many claims and pages the
question covers (`fold_claims`) and the anchor claim's sentence. A legacy fold with no recorded pair has no `fold`.
The ETag already moves with `entities` and `episodes`, so no client mapping changes (`test_inbox_review_context.py`).

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

**Settled by a check (owner ruling 2026-10-16, TODO ruling 27).** A conflict, clarification or "same as?" pair about a **public thing** —
a film, a paper, a tool, a company, a public concept — is looked up on the web and settled with a cited answer:
Sleep's tail does it on every run on the Claude plan (their plan's own search, the call's one tool) — the scheduled ones
too, since the plan switch is on by default (rulings 4c, 27b, 2026-10-19: "That's not what the inbox is for") — or on a
metered engine the person chose, at its price, and the person's own agent may do it through
`cicada_record_check(outcome="settles")` (`mcp.md`). **The backlog's sweep:** what was already open gets one pass the
person starts — `POST /inbox/web-check` (dry run by default: the census of what a lookup may answer and why the rest
stays, then what the lookups would settle; counts only), a real run in the background (`GET /inbox/web-check`), each
settle under the bank's write admission with its own commit and the same undo below (`capture-and-sleep.md`). A
question a search cannot settle confidently stays exactly as it was. Never searched: a `person`, an untyped name the description says is someone, the owner's page, a file or
path, a project, a multi-valued predicate other than what the thing *is*, an option label naming a person or saying
"my", anything personal (`web_settle.classify`; when in doubt the question stays). A type question (`is-a`, `type`,
`description`…, the owner's own example: "Is <tool-a> an agent harness or an AI agent itself?") settles on one option
only when the page rules the others out (defines it as that option and nowhere as another), on the item's own "both"
option when the page describes it as more than one of them (one
cited claim per option, nothing closed), never on an option the item lacks. **A conflict asks what a public thing IS,
or it stays (2026-10-20, rulings 27/27b: of nine conflicts the first real sweep settled, eight were the owner's own):**
nothing in its question, option labels or subject page may tie it to the person — first or second person (English or
Spanish), somebody's doings with no one named ("he uses", "the one bought last year", "installed on the laptop",
"dropped for …"), the owner's name, any part of it or a short alias as a whole token, a person's or project's page name
or a project's head word, "the owner/user", "<someone>'s thesis/code/lab/setup/server", a situation ("currently uses",
"planned for", "superseded by", "I'm modding"), an option label stating one ("Currently uses …", "Abandoned"), a page
whose own description calls it the person's own or names them or their project — and, whatever the wording, competing
claims that all came from the person's own words (`source_trust: user_stated` or evidence only in their turns)
(`web_settle.personal_conflict`, census `personal`). Two different things sharing a name ("Is <term> the <method> or the <product>?", "Is this entity
<A>, or <B>?", "… or the class called <X>") settle only on an option that IS the page's own name or alias (case and
accents folded), never on "both", never writing another thing's description onto the page; with no such option the
question stays (`web_settle.different_things`, census `different_things`). The writer refuses a situation label as a
description whatever the gate said.
**A "same as?" question about two public things (2026-10-29, `merge_suggestion`).** Ruling 27's lookup never read the
duplicate questions (`KINDS` was conflicts and clarifications): "Is <alternative> the same as <original>?" stayed for
the person though two searches answer it. Now a pair is looked up when BOTH sides pass the filter — a company, tool,
concept or work each; neither the owner, a person, a project page, a name carrying a project's whole name, a file, a
path or a PR/G reference; never two pages sharing one title (G227) — each name searched ALONE (`queries_for`: two
pinned queries, one search each, never one name sent with the other's words), the answer the relation of the name to
the page (`entity_relations`) or `different`, with the result's link and words. `settle_pair` writes ONE cited claim on
the page the name was weighed against (`includes`, `creates`, `alternative-to`, `has-version`…; `contrasts-with` for
`different`), moves the question to `settled/` with the record Undo reads, and the claim on the record keeps the pair
from being asked again. **A check never merges:** "they are the same" settles nothing — the question stays for the
person's tap. Pairs come after clarifications and before conflicts in a run's eight (`KIND_ORDER`).
**The settling step (rulings 54, 54a, `settling_agent`, `name_guard`, `public_handle`).** Two kinds of question on the Claude
plan, on by default (`CICADA_PUBLIC_HANDLE_LOOKUP=off` closes the handle half): "Is <handle> the same as <full name>?" between
two person pages, one a handle and one a full name, neither the owner or a role-only page; and an open conflict on a page
with a tracked source Cicada may open, on a predicate the vocabulary knows is single-valued.
**The model** holds no tool: the pinned argv, `--tools ""`, `CICADA_CAPTURE=off`, `CICADA_RECALL=off`. Each turn it answers one
JSON object naming calls this process runs: `recall`, `page`, `conversation`, `where_to_check`, `contacts`, `open`, `search`.
No writing call exists; a call to anything else is told "No such tool". Page text and what memory holds reach it between
fence markers it cannot forge.
**What leaves.** The plan's web tool cannot be intercepted (hooks are off in `--safe-mode`, a permission tool needs MCP, a query
reaches the provider before the stream reports it), so a model that has read the record never holds it. `name_guard` checks
each query; a cleared one goes to a search hand, `claude -p` with `WebSearch` alone, holding its prompt, the cleared queries and
what the CLI attaches to every spawn (the account's email, a scratch working directory, the platform and shell). Its reported
queries are audited against what it was given (a stray voids the round and stops the question), and its `searchCount` is what
counts. A blocked query is dropped, counts, and is never rewritten; two blocks stop the question. Only the Claude plan runs the
step, enforced at one place (`web_lookup.look_up(settling=…)`): `metered_only`, or `engine_for`'s reason, otherwise.
**The guard** (`name_guard`). A tie always blocks: Contacts' waiting cards and contacts book, LinkedIn connections and slugs, pages
carrying either, chat correspondents, group members, speaker labels, pages `web_context.known_personally` flags, person pages and
held names no public content says, the owner's names; an owner's project as a whole phrase. A mention blocks unless the same
words are also in public content, and only a name-shaped one: capitalised in the query, written as a name in the record, a
handle's shape, or a pair said in a chat. Ordinary words someone used are not asked. A returned link is held to ties only and
never counts toward the stop. `api/scripts/name_guard_census.py` counts what a bank blocks, for a fixed synthetic list. **Public content is a positive decision per writer and section** (`WRITERS`, default private):
a saved link's description and, when the page was read, its title and channel, never its note, reason or folder; a post's
handle from its link; an agent's quotes from a page or a video; a watched, listened or Substack day's rows. Every pair of a query's
words and every window of three is asked in every order, a long unknown token as each split of it; a middle initial changes
nothing and an initial makes the word beside it stricter; folding is full (NFKD plus `TRANSLIT`). The question's own name and
handle, once cleared, are taken out first. A store that exists and cannot be read or holds an unexpected shape raises
`GuardUnreadable`: nothing leaves. It is built once a run from `bank_index`'s cached headers into a contentless in-memory FTS5
index, off the event loop, never under write admission (`public_handle.settle(tested=…)` does not rebuild it), and released after.
**Pages.** Tracked sources are opened by code before the first turn (54a); after that only a link a search returned, exact,
passing `check_url`, not removed from the page. All on the link rail (`_stream_html`). A walled source is never requested.
**By what a question's page holds:**

| Source | What happens | Question |
|---|---|---|
| Open tracked page | Opened by Cicada on the link rail, first; the model answers from it | May settle |
| Walled or blocked tracked page | Never requested; already on ruling 26's listing for the person's agent, under their Reading switches | Stays |
| LinkedIn link from the person's connections (confident match) | Kept as a place to check, counted as given; never requested and never on a re-check list; read only on the person's ask (`cicada_record_profile`) | Stays, or a public handle may search |
| Proposed source | Never opened; waits in the grouped review | Stays, or a public handle may search |
| No source | No model call for a conflict or a private pair | Stays, or a public handle may search |

**What settles a handle is the model's judgement** (owner 2026-11-04: "One site is enough … let the agent do this work don't
tell it how to do it"). It is given the goal and what is at stake, and answers sure or not, with a confidence and a citation.
The one code check (`public_handle.cited`): the page was opened here and all of the quote is on it, 12 characters at least, and
the page's own text is what is stored. A confidence of 0 or not a number is no answer. One that is not is sent back at most
twice. It writes one `goes-by` claim on the named page ("<Name> goes by “<handle>” online", observer `agent`, `external`,
`web-check`, the model's confidence), citing that page in one `web-check` episode; while it stands the pair is not asked again
(`pair_evidence.answered_by_check`).
**What settles a conflict** (ruling 26's rule, `web_settle.settle(via_source=True)`): the model's answer, its quote on the opened
page, on a predicate the vocabulary knows is single-valued, and every other option said before today; the same day or undated
stays the question. Its record has `scope: source`.
**Budget:** one question 6 searches, 6 pages, 12 reads, 8 turns, 2 sends-back; a drain or sweep 3 handles, 5 questions, 5 changed
sources, counting every attempt; that same change waits 30 days after a read with nothing to show, and a later change does not. `Report.questions` keeps each question's numbers and the log line their totals, never a query, link or name.
**The person's own agent** settles a handle through `cicada_record_check` (`proposed_value="same"`) under the stricter test
(`_agent_test`): no chat or card touching either name, its two pinned searches, a quote naming both.
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
| `merge_suggestion` between people | **it should never have been asked** (owner 2026-11-04, `pair_evidence`): the owner's page beside someone with no words of the person's naming themselves so (`owner_unsaid`), or two people no conversation names together (`no_pair_evidence`; a question the record raised with no conversation is exempt) — retired, nothing written but the record, engine-free; never "same" and never "different" | ask (evidence names both) |
| `merge_suggestion` | same name once spelling is folded, same type, not a person (`same_spelling`); or the judge reads both pages: `same` ≥ 0.9 merges (`judged_same`), `different` ≥ 0.9 keeps them apart (`_merge_rejected.yaml`, `judged_different`). A merge of two existing pages **folds the duplicate's page into the target** (`entity_merge.merge_entities`: its claims, ledger, sources and references follow; undo brings it back) | ask (unsure; a person — only their own words merge two people) |
| `normalization` | the two labels differ only in spelling (case, separators, a plural): "Correct fold" (`spelling_fold`); a fold the shipped predicate seed lists (`synonyms`), curated like an ending (`seed_fold`, ruling 37); else the judge: same meaning ≥ 0.9 folds (`judged_fold`) | ask (the meaning changes, or unsure) |
| `decay` | a one-off nobody would miss: a `concept`/`tool`/`media`/`company` page on one conversation, not evergreen or durable, never kept, no claim of the person's own → archive (`one_off`); any other such page: the judge reads the page and its last mentions — clearly passing → archive (`judged_archive`), clearly live → marked active only (`judged_keep`: no mention dated today, no claim reopened, no confidence lifted — the person's "still true" stays theirs) | ask (the person's projects, skills, people, places; unsure) |
| `conflict` | a multi-valued predicate: every value was already kept, the question closes with nothing touched (`multi_valued`); the newest dated statement settles it: single-valued, every option an open claim, one said strictly later than every other (`newest_evidence`); else the judge reads each option's dates and evidence lines: one clearly better supported or newer ≥ 0.9 (`judged_conflict`) — never what only the person knows. **A label-only conflict** (an older format: no option carries a `claim_id`) is judged too: each label is tied to the page's open, non-event claims by folded text (`label_matches` — `text_fold.words`, whole words, never fuzzy: the label equals the claim's object or sentence, the object (≥ 4 characters) is a run inside the label, or the label (≥ 2 words) is a run inside the sentence — a negated label ("No longer on X") ties only by equality; on the conflict's predicate unless it is the entity path's literal `description`; a claim tied to two labels supports neither). Labels tied to nothing stay (`ask:labels_not_on_record`); the judge reads each label with its tied claims and their evidence lines, never picks a side nothing on the record states, and settles by option key through the same resolver (which, as for the person's pick of a label-only option, writes the confirmed sentence and closes no claim). **The owner's words:** a claim resting on the person's own words (their inbox answer, or a span in their own turn) is closed only by one that does too, or by a tracked source's dated re-check (ruling 26) — by no rule and no judge otherwise | ask (the owner's page; what a person is or is called; unsure) |
| `clarification` | **a name said in passing** (part 3, `in_passing`, owner 2026-10-17: "little things that are honestly not that big of a deal"): "Who or what is <name>?" about a name with **no page** (by id, name or any page's alias), said in **one conversation** (the raising one; every other conversation the lexical index finds by its spellings is checked on its own text, whole words — the index read fresh, so a conversation the batch just committed counts) and **only in passing there** (at most 2 of its exchanges name it — `promotion.exchanges`, the promotion rule's own unit) → closed through the person's own `dismiss`: nothing is written about who or what it is, the name stays where it was (the index, the pending store), and a later conversation that names it may raise the question anew. A **code identifier** (one token with `_`, `::`, `()`, `->`, a sigil or flag dash, or backticks — never case alone, so "GitHub" is no code) is assumed however many conversations name it. **Never:** a relation question ("What's the name of your <relation>?"), the person's own things (`project`, `skill`, `deadline`), **a person (or a name of no type) said in any of the person's own turns** (`ask:persons_words`, review 2026-10-17: their words about someone mean that someone may be in their life — a relation a sentence away, a pronoun Spanish drops, or none at all; only a person named in an agent's text or a document's metadata may close — and a **saved item** (no turn marker, from a saving door: a bookmark, a saved post, a feed, a watch or web history, a read page, or an episode carrying the page's `url`) is the page's text, never the person's own words, so a name in its title, link or byline may close), a relation word (`role_people.ROLE_WORDS` plus family, teammate, colleague, compañero/a, jefe/a, novio/a… — the name's own words never count) **tied to someone by a possessive** right before it or one word before (my/your/our/his/her/their, mi/tu/su/nuestro… — "my older sister", "your teammate", "con mi primo", "X is my …"; "a decades-old family spot" is no relation) in the turn that names a person, company or place or in the turns beside it (a song, tool or term: in its own sentence), a company or place when the person speaks of themselves in that turn or the ones beside it (I/me/my/we/our, yo/mi/nosotros…, and Spanish first-person verbs like tengo/fui/hablé) — both checks read words someone wrote, never a link or a metadata line (`url:`, `folder:`, `origin:`, `author:` …; "…&client=safari" is no client), a name the owner's page says, anything from a Messages chat, or a conversation that cannot be read (`ask:unmeasured`). Stays: `ask:persons_words`, `ask:relation`, `ask:about_self`, `ask:owners_page`, `ask:messages`, `ask:named_again`, `ask:said_more`, `ask:own_type` | ask |
| `conflict` (label-only) | **the person's newest words** (part 3, `newest_words`): when labels do not tie to claims (or before the judge reads the ones that do), the record decides — every sentence of the person's own (kind `user` turns, never an agent's, never an agent's saved note) in a turn that names the subject, across the page's pointers, the raising conversation and the lexical index's hits (newest first, at most 24 conversations), that states a label (the whole label, or its distinctive run: from its first word no other label has, not a stop word or the subject's name, through the words after it, ≥ 3 characters; whole words, folded, never fuzzy). Settled with no engine when the newest day any line states a side has only **plain statements of one side** — the sentence itself names the subject (a sentence about another subject in the same turn never settles it), the label **directly follows a plain placement** (an allowlist: is on, runs on, is running on, uses, is using, moved to, switched to, migrated to, now on, lives on, is at; corre en, está en, usa, se movió a, pasó a, ahora en — "dropped", "ditched", "shut down" never read mechanically), and it carries no question, negation, modal, avoidance or hedge, read on the raw text so a contraction is never split away ("can't", "won't", "cannot", "no longer", "stop", "avoid", "instead of", "except", "without", "from … to", "or", "should"; Spanish no, nunca, ya no, sin, en vez de, evitar) as a second guard — an **older** line of theirs (or a belief tied to another label) states another side, nothing for another side is as new (or undated), and the line is located exactly in their own turn (`persons_span`) — the evidence span, the prose dated the day it was said ("confirmed by Sleep on <today>, as said on <day>"). Otherwise, when such lines exist, the conflict judge reads them too (tagged `[C<n>, <day>]`, at most 8) and may pick a side no belief states only by naming the line its pick rests on: the words located exactly in their turn, stating the picked label, with no line stating only another side that day or later and no other side's belief as new. The owner's-words rail holds: the winner is the person's own words | ask (`needs_judge`, `labels_not_on_record`) |
| `followup` | **on a page not in the person's list, never started or taken out** (ruling 56, `not_started`): one is raised only on a project they started, and one asked before that rule, or left when they removed the project, is retired, nothing written but the record, engine-free; undone, it is theirs and Sleep never retires it again | stays for the person, on a project they started |
| `clarification`, `followup`, `conflict` | **answered already, anywhere in the record** (move 3, `said_on_record`; part 2, 2026-10-17): still open after the rows above, the question is looked for across the whole bank — the conversations its page points at (its claims' evidence and `source_episodes`, the pointers Ask's source words follow) plus every conversation the lexical index finds by one of the page's spellings (`search_service`, words only: no embedding model inside Sleep). Only the person's own turns that name the subject, in a conversation the ask gate finds about the question, reach the engine — each tagged `[C<n>, <day>]`, at most 6 conversations and 8 lines; the reply names the tag and copies the words, which must be found exactly in that conversation's own turn (kind `user`, never fuzzy, never an agent's words — and never the unmarked text of an episode an agent saved through a tool door, `ask_sources.AGENT_SOURCES`, which the evidence reader would otherwise call the person's) and become the evidence span. **Read on time:** a claim Sleep writes from the person's words is true from the day they said it (`valid_from`, and a closed side's `valid_to`, at the conversation's day; `recorded_at` today), so a March statement read in October still ranks as March's. A conflict is answered only by words said strictly after every side of it (a side with no date: never from the record), a follow-up only by words after its thread was last heard; never by the conversation the question rests on. A follow-up takes only `done`/`still`/`stopped` (a thread) or `done`/`missed`/`dropped` (a milestone), written through `progress` as Sleep's (`origin: inbox-tend`, the model as author), **dated the day the person said it** (`date_basis: episode`) — never a withdrawal or a moved date. Nothing on the record → no engine call, and lines already read without an answer are never sent again (an in-process memo of ids and a hash), so the next drain moves on. In Sleep: 4 questions per drain; in the tidy: every one, only with `judge=true` | ask |
| `conflict`, `clarification` | **about Cicada's own settings** (owner 2026-10-19, ruling 27b: "Are scheduled Sleep runs still going through <provider>?" is the system's to know): on Cicada's own page (its exact id, never a page that merely has the word in its name), asking which engine its Sleep runs read with — a run named in the question and an engine choice (a plan, an API key, a local model) among it or its options — or what time the schedule runs (every option a time of day) (`web_settle.own_settings`); the owner's design questions about his project (a hosting provider, a page's layout, the search or graph engine, whether Sleep runs nightly) stay his — retired with nothing else touched (`own_settings`, engine-free), never searched; Settings shows the current value, and a conversation that mentioned it stated that day's configuration, so nothing is written as a claim | — |
| `conflict`, `clarification`, `decay` | **what the record already says** (owner 2026-11-06, ruling 72, all engine-free, vetted, undone from "Settled by Sleep"): a value said two ways (`same_value`, `value_words`: case, spacing, an approximator, a leading `v`, "per month"; a longer value that only adds a unit or detail) keeps the fuller wording, and when the page already holds it nothing is written and no line is added; a `part-of` said on different days is a move (`moved_on`): the latest stays current, the earlier ones are written closed (`MOVES`), while every other multi-valued predicate (`runs-on`, `part-of` are multi in the seed since 2026-11-06) keeps every value; Cicada's own counters (`own_bookkeeping`, `web_settle.own_bookkeeping`: a plan's usage, limit or counter, a count of what the bank holds, Cicada's own test results) are retired with nothing written and never raised (`write_claim_nudges` counts `skipped_bookkeeping`); "Who or what is X?" on a name Stage 1 described (`already_described`, nothing written) unless its **whole** text (body, not the cut classification line) admits not knowing, hedges, leaves an ask to the person or mentions a login or password; a decay question on a page back over the line (`not_fading`, nothing written). **Two values from one conversation are NOT assumed compatible** (a conversation can change its mind): `same_conversation` was dropped. | the rest of the table |
| `sensitive` (G235, ruling 60) | never settled by Sleep (`inbox_tend.NEVER`), never in a catch-up or a conversation (`inbox_catchup.NEVER`, `mcp_tools.APP_ONLY_INBOX_KINDS`); `remove` or `keep` on one `row`, or every row; an agent or a relayed quote is refused 403. Rows: `{id, episode, title, day, kinds, readBy, heldKinds, heldFrom, earlier}`, never the words | `capture-and-sleep.md`, "What may be sensitive" |
| `clarification` with `asks: sources` (Where to check, ruling 36 D5, 2026-10-22) | **the person gave that very link as that page's account in their own words** (`named_account`, engine-free, `source_proposals.strict_quote`, tightened by the review of #422): only a one-row item, whose link waits with evidence that is a located line of the person's own turn carrying the link, naming exactly one page — this one — and whose account name matches the page's name or an alias; the grouped review ("Confirm N links", `review: true`) and every other case — no engine, no record read, no other rule, no trace row — is never settled (`person_only`) | ask |
| `divergence`, `removal` | only from the person's own words in a batch's conversation (above), or never | ask |
| `page_edit` | never — the person's alone (G198) | ask |

**No value is lost with a question (owner 2026-11-06, ruling 72; G98).** The value only a question held is written to its page as a **closed claim** — dated when it was said, never current, never the person's act (`confirmed=False`), ended where the kept value began — whenever the question ends: a pick keeps one value and the others are written (`inbox_service._write_lost_values`; a respelling of the kept value is not), and a question closed because a later value won hands itself to `inbox_service.keep_values_of_closed_question` first (`inbox_questions.refresh_open_questions(keep_values=…)`, from both `sleep_cycle` callers; a page that cannot be read leaves the question). Sleep's pick adds **no page line when no value on the page changed**. **A new contradiction opens its own question** (`inbox_generator.fold_into_open`): a description answer that joins an open question's (`joined_options`: same label, `near_duplicate`, `_counterpart`) folds into it; one that joins none opens a question of its own, up to `MAX_OPEN_CONTRADICTIONS` (4) a page, then folds into the newest. A claim conflict keeps one question a key. The 37 already piled up are left as they are. **Wording:** a pair where one side is a person known only by their relation to the owner reads "Is <name> your <relation>?" (`inbox_wording._only_a_relation`); the buttons still say Same / Different.

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
[--judge]` measures it offline, writing nothing. **The coordinator's trace and vetted apply (owner rule 2026-10-20:
read every proposed answer before any bulk write).** `api/scripts/inbox_tidy_trace.py trace --bank <path> --out <file>
--engine plan --model haiku [--kind K] [--limit N]` is the same dry run, in process (read-only: no backend, no
admission, no settle, no commit, no ledger row — only the derived lexical index may be brought up to date), writing one
JSON line per question to a 0600 file the caller names, refused inside the bank or the memory root: `id`, `kind`, the
two `names`, `decision` (`merge` / `keep_apart` / `settle` / `leave`), `rule`, the judge's own `confidence` (null for
an engine-free rule), a one-line `reason`, and for a decided question an `apply` block — the decision as made, with
hashes of the question file and every page it read. stdout gets counts only. `--engine plan` pins the judge to the
Claude plan with that model (`llm_mode=agent` on a copy): the bank's configured engine is never resolved or called.
`… apply --vetted <file>` sends the rows still carrying `apply` to `POST /inbox/tidy/apply` (ruling 21a: token, pinned
bank, `/healthz` root check), which settles each through `inbox_tend.apply` — the person's own resolver, Sleep's undoable
commit, one at a time under the bank's write admission. **The row only chooses a question; the server decides
(`vetted_decision`, review of #393), whatever the body says:** the question file is the traced bytes and not put off,
taken back or a proposed edit; the rule is in `VETTED_RULES` for that kind with exactly the request shape it produces
(a merge only into the question's own target, an option only among its keys); an engine-free rule is decided again
and that fresh decision is applied; a judged rule needs `policy()` to still answer `needs_judge` (so the person,
type-mismatch and same-page refusals hold) and a guard over at least every page the judge reads, unchanged; a name
question (`asks: name`) and any free `answer` settle only as `said_on_record`, on the person's words located again
(`persons_span`) in a conversation that does not raise it, said after every side of it, and only when those words
SAY the answer (`answer_supported`, no model: a free answer's words, a name as one phrase written as a name —
`written_as_name`, 2026-10-27: capitalised where the person wrote it unless that quote has no capital at all; a
nickname said in passing, "send it to <nickname>", titles the page instead and keeps the question open (ruling 41,
`capture-and-sleep.md`, "Placeholder people") —, a conflict side's label
or claim object, a follow-up's state word — the same check Sleep's own reading applies in `_answer_decision`); the model and engine become
the author only for a rule an engine read and only as an id that engine uses — any other settle is Sleep's own
(`cicada`). Per-id outcomes: `settled`, `changed`, `refused` (a code),
`not_reached`. Busy for an updater while it runs, like the tidy; 409 while Sleep, a tidy or a sweep runs.

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

**A re-raised conflict joins the question already open (2026-10-27).** One open question per page and predicate
(`find_open`); a re-raise merges its answers in (`inbox_generator.merge_options_into`). A description question is
re-raised in new words most nights, and each night appended one more near-identical pair (`a, b, ax, bx, axx, bxx …`:
"Still in the beta" / "Already in production", then "Final beta weeks" / "Already shipped to production"). Now, on a description
question only, an incoming answer that says what an open answer on its side says (`near_duplicate`: the same subject
words, or one holding all of the other's two or more; never when only one is negated, never on one shared word) is
that answer; and when one side of a re-raised pair joined an open answer, its other side joins that answer's
counterpart (the answer appended with it, `raised_with`, else the other side first seen the same day). Both only bump
`last_referenced`; the label the person already saw stays. A pair matching nothing is appended as one pair, stamped
`raised_with`. A claim conflict's answers are values: only the exact label joins. Open questions with near-duplicate
answers already written stay as they are until answered (no rewrite of an open card).

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
keeps the note-only answer, even when a page was promoted under the mention's slug since. A `merge` on a name Sleep
held (G209, an item marked `held_mention`) also lands the claims held on its pending line on the target, through
Stage 3, in the same commit (`capture-and-sleep.md`, held names); `reject`, `dismiss` and `skip` release nothing, and
Sleep's settle never folds the page a held mention shares its id with (or an unflagged question's from 2026-10-27 on); it then leaves the question pending for the person rather than closing it with both pages left.
The app draws a name field, Submit and "I'd rather not say" (`NameBody`, `app.md`); an older build sees the option
and Other… and still answers it.

**Observer inconsistency — resolved (G117).** All five sites (the inbox resolve path, Telegram
capture, `agentic_write`'s trust/origin gate, and MCP `cicada_write_claim`'s schema/description) now
read `owner_identity.resolve_observer` instead of a hardcoded literal, so a bank's claim lineage
never forks across writers.

**Keep awake (G243, 2026-11-06).** `keepAwake` in `/sleep/run-options` (machine-global, off by default): `sleep_cycle.run` acquires `keep_awake` (`caffeinate -s -w <backend pid>`) after the window opens and releases it in its outermost `finally`. On AC only; dies with the backend; a failure to hold is a log line. It never wakes a sleeping Mac and is not relied on for a closed lid (unverified here; root: G243 parts 2–3). Staying awake changes nothing about what may run (ruling 4). The switch is in the lamp popover on the Sleep page, under the schedule toggle, with a one-line caption saying it needs power and neither wakes a sleeping Mac nor works with the lid closed (DR-77 sheet-free popover row; current look kept).

### 4. Manual Sleep trigger
"Run Sleep cycle now" + next-scheduled indicator. A person's trigger **drains the queue** (see Sleep — Consolidate reads
everything, TODO ruling 13); `POST /sleep/cancel` says so ("Batches already filed stay filed"), and while a drain runs the
bank-switching routes answer 409. `POST /sleep/trigger` takes an optional `{"continue": true}` (Sleep page v5).

**A new memory reads nightly (owner 2026-10-22).** A bank this install just created — the first-boot default bank (`seed_owner_if_brand_new` wrote its owner page) or `create_bank` with its owner page (never the demo) — gets `sleep_schedule.yaml` written once as `daily` 03:00 (`sleep_scheduler.seed_new_bank_schedule`, never over an existing file); a bank that already existed with no file still reads as `manual`. A scheduled run uses the plan per ruling 4c. Onboarding's Done says so ("It reads tonight at 3:00, and now for what you brought in.") and Open Cicada starts one run when something came in during setup.

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
waiting, in batches** (ruling 16: unattended, on the scheduled engine — on a key that is spend up to the person's limit, `sleep_spend`; a
paused run is left for the person to continue or end; the tail still runs over it).

**The schedule is the active bank's own (follow-ups 2026-10-19).** The jobs' triggers are built from the schedule the
bank had when they were registered (startup, a schedule save), so a bank switch has to move them: every switch route
(`POST /banks/{name}/activate`, the demo's two doors through `_activated`, a new demo) calls
`sleep_scheduler.follow_active_bank`, which re-registers from the new bank's `sleep_schedule.yaml` — a bank on `manual`
gets no job at all, one on 05:00 fires at 05:00, and switching back restores the old trigger. Because an active bank can
also change by a path that is not a route (a registry edited underneath the backend, a restore), each job carries the
schedule it was registered for (`registered`), and `_run_if_idle` / `_run_after_intake_if_settled` compare it with the
active bank's own (`trigger_key`: mode plus time or step) **before** anything else: different → re-register from the
active bank and run nothing on the old time. Two banks on the same schedule share one trigger and the fire runs the
active one. A schedule file that is there but cannot be parsed is not `manual` to this check (`read_schedule` →
`None`): the fire runs as registered and logs it once per bank, so a corrupt file never unregisters every job;
`save_schedule` writes atomically (temp file, fsync, `os.replace`), so a fire never reads one half-written. Before this, `_run_if_idle` never re-read the mode, so a bank switched to `manual` was consolidated on the
last bank's 03:00.

**A missed scheduled time catches up, once (owner 2026-10-19).** `daily` and `interval` are timers in the backend's own
process: one due while the Mac sleeps fired late on wake, past APScheduler's grace, and was dropped; one due while the Mac
is off was never seen (the next start computes the *next* time) — a laptop closed at night never ran its schedule. The
schedule's own job now keeps a minute's grace (`coalesce`, `misfire_grace_time=60`), and beside it `sleep_catch_up`
installs a 5-minute probe (first look a minute after start; `manual` and `after_import` get none). Each look reads
the **active bank's own** schedule (`load_schedule`), never the one the probe was registered with — a switch
re-registers the jobs (above), and a probe in flight across one still never catches a bank set to `manual` or
`after_import` up on another bank's time — and a demo
bank (`demo_guard.is_demo`) is never read. The probe asks for the
latest due time with nothing since — `daily`: the latest HH:MM at or before now; `interval`: the last anchor plus N
hours — and, however many were missed, runs **once**, naming the latest. "Since" is the latest of: `handled_at` (every
scheduled fire, on time or caught up, stamps it **before** reading — a fire that then finds a running cycle, a pause or a
failure has had its turn), `last_run_at` (`sleep_cycle.run` stamps every run that reads, the person's included), the
newest `runs.json` summary and the newest real `Sleep cycle` commit (the record that predates the stamps), and `since`
(when this schedule — mode and time — was first seen, so a schedule set at 14:00 never catches up that morning; on the
first start after an upgrade, the schedule file's own modification time). The stamps live machine-local in
`$CICADA_HOME/sleep/<bank>/schedule.json` (`sleep_local`, timestamps only): the schedule is a fact about this Mac's
process, the bank's history cannot say that a fire found nothing or failed, and in-memory scheduler state does not
survive a restart. **The settle:** a missed time is first noticed, then run one probe later if still missed; a gap
between probes over ten minutes is a wake or a start and the settle begins again, so it never lands on login or the
moment the lid opens. **Rails:** `user_triggered=False` (ruling 4/4b — a plan only through the person's switch, never
flipped here; with the switch off on a plan the catch-up fails as the 03:00 run does, once per missed time, never on
every wake, because the stamp precedes the read); it reads everything waiting (ruling 16, `_scheduled_drain`); never on
a running cycle (it looks again next probe, and checks again after counting the queue); a paused run gets the engine-free upkeep only, as `_run_if_idle` does; the
bank active when it fires (`bank_registry.unpin`, G183(d)); nothing readable (only parked or index-only history) runs
nothing and the time counts as handled, so a capture later that day waits for the next time as on any day. The run's
summary carries `catch_up_for` (`sleep_runs`, `SleepRunRef.catch_up_for`), which Past nights says in words (`app.md`).
**Past nights is one card per consolidation (owner 2026-10-26):** when it ran and who started it, what it included, the
engine and models, the plan usage or cost with its basis (ruling 12), how long it read and how it ended; its dropdown
lists the conversations it read, the pages it made and changed and the questions it raised and settled, each opening
where it lives (`GET /sleep/runs/{id}/items`, `GET /sleep/history/{commit}/items`; `api.md`, `app.md`).
A plan-pinned scheduled run (`CICADA_LLM_MODE=agent|codex`, one batch, no run summary) catches up the same way but its
row carries no catch-up words. **The menu bar counts what waits for Sleep:** `GET /status` `episodes.readable`
(`sleep_debt.readable_count`) is the bookworm's badge (`app.md`).

### 5. Conversation upload
**One chat-export pipeline (Track I).** Claude, ChatGPT and Gemini exports — a whole .zip, a
folder, or one file — go through `api/routers/intake.py`: every member a parser knows (a Claude
zip's conversations, memories and projects), the known extras (`user(s).json`, feedback and
comparison files, ChatGPT's `chat.html` viewer) skipped **by name**, the vendor's `origin` stamped
on every path, per-message times kept as `turns: [{offset, ts, speaker}]` outside `content_hash`,
and re-imports updating grown threads in place (G20) without duplicating. `POST /intake/sniff`
previews and stages nothing; `POST /intake/import` stages. **A file that does not go in gets words (2026-11-06):** a
file that is cut short, a zip that is not whole and a JSON no parser knows answer `CUT_SHORT_JSON_REASON`,
`BAD_ZIP_REASON` and `UNKNOWN_JSON_REASON` — what is wrong and which file to drop (`conversations.json`, or the whole
`.zip`), never the parser's message (`Expecting value: line 1 column 1 (char 0)`; G199) — and a background write that stops
records `intake_jobs.WRITE_FAILED`, the exception's class staying in the log. The app (`IntakeFailureWords`) names every
failed file with its reason, three at most then "and N more" (a bare reason named none), and maps every transport error to
a sentence of its own. **A large export is slow, not failed:** measured on a synthetic ChatGPT-shaped file (invented
text) on a busy Mac, the time is the secret scrub (`episode_scrub`, ~0.5 s a megabyte), not the JSON parse (0.6 s for 26
MB): a 25 MB file sniffed in 7 s, a 150 MB one in 110 s, and its import took about 3.5 min — the same plan runs
twice, once to preview and once to import; the parse's peak memory was ~2.6x the file. The app's 60 s default ended the
request with "The request timed out." while the server went on and wrote every conversation (6,332 here), so
`uploadMultipart` waits up to `APIClient.uploadTimeout` (1 h, an idle timeout) and a file of 50 MB or more says so under
the wait ("A file this big takes a few minutes."). Nothing about what is imported, scrubbed or staged changed. `/conversations/upload` (deprecated,
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
