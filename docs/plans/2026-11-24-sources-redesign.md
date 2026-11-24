# Sources, redesigned: every source says what it reads (G245, ruling 78)

Owner, 2026-11-24 (his words, shortened): redesign the Sources page completely, "cleaner and minimal with the cards we
use for the consolidation queue"; remove importing from files ("rarely will get used"); "better ability to check for
connections with sources"; "remove the weird diagrams"; "easily see what is being read (history, liked, saved, etc)".
"All this can be standardized but also depends because each source has its caveats." X: folders plus the all-posts
list, likes, and whether one post was saved, liked, reposted ("all, two or one of them"); maybe the accounts followed.
Instagram "same to a certain point". Reddit: "i can also save posts and stuff". LinkedIn: saved posts, and "who i have
connected with and in chronological order which to me is super important" (he met people at an event, connected with
some, wrote some in a note, and wants Cicada to "surface this relationships and be aware of it"). Apple Notes: "respect
the folder structure, pins, recently modified and all these dynamics the app has itself, replicate it in cicada";
Notion alike. YouTube: "folders of saves", Watch later, history. Depth: keep saves in memory lightly, but "those that i
actually go ahead and talk about are way more important and maybe worth using the claude video skill to pull the
transcription, maybe even frames and watch it. Same with instagram posts/reels", X, LinkedIn, Reddit; "a clear logic i
believe should be established to not bloat cicada memory … but making it aware and powerful to go deeper in the things
i save"; use the multimodal search model. And: "make sure the notch message appears correctly and works to connect the
source correctly when I'm inside the app or website."

This is the shared brief for every track. It gives problems, the contract between backend and app, and the rails.
Workers choose the implementation and say why. It was checked by four critics against the code on 2026-11-24; their
corrections are folded in.

## 1. What is wrong today (read from the code, 2026-11-24)

- **No model of "what is read".** Five registries key sources differently (`source_overview.CATALOG`,
  `channel_registry`, `saved_lists.PLATFORMS` + `youtube_lists` + `substack_lists`, `ways_in.SOURCES`, the app's
  `SourceCatalog`). A source page builds its switches by hand per source (`siteWays`, `youtubeWays`, `substackWays`).
- **Lists the person has that Cicada cannot read live:** X likes and bookmark folders (the tool takes `folders`, the
  prompt never asks for them, and a folder is its own page), Instagram collections and likes, Reddit upvoted (browser),
  YouTube playlists and liked videos, LinkedIn connections (a file is the only door; the day connected is kept but
  listed nowhere).
- **One post, several lists:** a like and a bookmark of the same post keep the first origin; the media page's
  `collections:` already unions lists (`media_ingestor.add_collection`, `id_utils.page_lists`) but no row shows it.
- **A first read never catches up:** a list read is the newest few screens; a list of thousands is only ever reached
  by the export file.
- **No row carries a date of its own:** a list item is dated the day Cicada kept it.
- **Notes lose their shape:** only the leaf folder name is kept (two same-named folders collapse), folders sort by
  name, same-day notes tie and fall back to title order although the modified instant is stored, no snippet. Notion
  keeps no parent and sorts by created day.
- **A save from a platform list is never woken.** `saved_mentions` wakes only kind `saved` (bare bookmarks, tab
  groups, saved links). Kind `list` (X, Instagram, LinkedIn, Reddit, YouTube playlists and Watch later — the owner's
  case) is index-only for good (ruling 30), even when the person talks about it. Nothing asks their agent to watch a
  talked-about video or read a talked-about post, and no row says how deep an item went.
- **The page:** a node-and-lane animation (`WebReadingCard`) explains browser reading; file rows ("Import a file",
  `IntakePanel`) sit on source pages; connected and not-connected sources are different shapes; no way to ask "is this
  still working" short of opening each source.
- **The notch offer does not connect.** A site's Yes sets only a per-Mac flag (`SiteSavePrefs`) that the Sources page
  never reads: the source still says Off, its saved list is not turned on, and the flag cannot be seen or undone
  anywhere (its only switch lives in `IntegrationsView`, which nothing mounts). "Saving on X will ask why" is false
  while ask-why is off. The confirmation shows before the write. A skipped decision spends the visit's one offer
  (`lastSite` is set unconditionally). A Mac app's Yes only opens a page. LinkedIn, Pinterest, Substack, Spotify and
  Goodreads never offer.

## 2. The model: a source has streams

A **stream** is one thing a source reads: X's Bookmarks, X's Likes, YouTube's history, Notes' notes, LinkedIn's
connections. Every stream says the same things: its name, whether it is on, how it is read, when it was last read and
how that went, how many items the memory holds from it, and how deep its items go.

### 2.1 Wire contract — `GET /sources/streams`

ETag: a digest of the body (the `/reading/settings` precedent). The app, the CLI and any later client read this.

```json
{"sources": [{
  "id": "x",                       // the catalogue id the app uses for the source (SourceCatalogEntry.id)
  "label": "X",
  "account": {"handle": "…", "profileUrl": "…"},   // or null
  "streams": [{
    "id": "x.bookmarks",           // "<source>.<stream>", frozen once shipped
    "label": "Bookmarks",          // the list's own name on the site or in the app
    "kind": "saved",               // saved | liked | history | later | playlists | connections | notes | pages |
                                   // chats | events | tasks | code | books | feed | files
    "how": "browser",              // the way in use (or the default way while off):
                                   // browser: the person's own AI app, in their own signed-in browser
                                   // app: this app reads it on this Mac · account: a sign-in the person gave
                                   // click: noticed when the person saves, on this Mac
    "owner": "backend",            // backend: state/health are the truth · app: the app overwrites state, health
                                   // and why from its own switch and permission; count and lastReadAt stay
    "control": "switch",           // switch: one PUT flips it · setup: needs the source's own connect step
                                   // (choose chats, a sign-in, a QR, a permission, a folder)
    "state": "on",                 // on | off | unavailable
    "health": "read",              // read | not_read | signed_out | couldnt_read | paused | null
    "lastReadAt": "2026-11-24T08:10:00Z",
    "pausedUntil": null,
    "checkRequestedAt": null,      // set by a check, cleared by the next read (section 3.3)
    "count": 214,                  // items the memory holds on this list (list membership, not origin), or null
    "folderCount": 3,              // folders / collections / playlists kept for this stream; 0 when none seen
    "depth": "index",              // index: kept and findable, no model reads it until the person talks about it
                                   // read: Sleep reads it
    "switch": {"setting": "savedLists", "key": "x"},   // what PUT /reading/settings takes; null otherwise
    "why": null                    // one sentence, only when unavailable
  }]
}]}
```

Rules:
- One module (`api/services/source_streams.py`) names every stream. Browser lists are **derived from the list tables
  themselves** (`saved_lists.PLATFORMS`, `youtube_lists.LISTS`, `substack_lists.LISTS`), so a list added there appears
  with no second edit; everything else is a static table in that module. Statuses come from the stores that already
  hold them. Nothing existing is replaced: `/sources/channels` and `/sources/overview` stay.
- `count` is list membership counted in one cached derived pass over media pages (`page_lists`), never a per-request
  scan and never the last read's size.
- A stream the code cannot read is not listed (no "coming soon" rows). A stream read through a connector the person
  connected (X's API bookmarks, Reddit's and Pinterest's connectors) is the same stream with `how: "account"`.
- The streams of one source appear in the order the site or app itself shows them.

### 2.2 Items — `/sources/channels/{id}/items` (shape bump)

Request: two new optional parameters, `stream` (a stream id; filters to that list's members) and `folder` (a folder
name within it). Row, three new optional fields:
- `lists`: the labels of the lists this item is on (`["Bookmarks", "Likes"]`), from the union the media page's
  `collections:` already holds; the app shows them as words.
- `folders`: the site's own folder names (`save_folders`).
- `depth`: `kept` (index only) · `read` (Sleep or the person's agent read it). B3 adds `asked` (the person talked
  about it; a deeper read waits for their agent) and `watched`. Built from maps computed once per request.
- `posted`: the post's own day, when the list showed one. The row's existing day stays "kept on".

### 2.3 Streams per source

Existing lists keep their keys, origins and folder labels. New lists reuse the labels the export readers already
write, so a post the export brought in and the same post read in the browser are one row.

| Source | Stream | Key (family) | Page the agent opens | Origin · folder label | Default |
|---|---|---|---|---|---|
| X | Bookmarks | `x` (savedLists) | `x.com/i/bookmarks`, then each bookmark folder's own page when folders exist | `x-bookmarks` · `Bookmarks`; folders in `save_folders` | as today |
| X | Likes **NEW** | `x-likes` (savedLists, base `x`) | the person's own profile → Likes tab (a page that holds only that list) | `x-likes` · `Likes` | off |
| Instagram | Saved | `instagram` | profile → Saved → All posts, then each collection's own page | `instagram-saved` · `Saved`; collections in `save_folders` | as today |
| Instagram | Likes **NEW** | `instagram-likes` (base `instagram`) | Your activity → Likes | the export's own origin and `Liked posts` | off |
| Reddit | Saved | `reddit` | `reddit.com/user/me/saved/` (no folders on Reddit) | `reddit-saved` · `Saved posts` | off (G232) |
| Reddit | Upvoted **NEW** | `reddit-upvoted` (base `reddit`) | `reddit.com/user/me/upvoted/` | `reddit-saved` · `Upvoted` | off |
| LinkedIn | Saved posts | `linkedin` | as today | as today | as today |
| LinkedIn | Connections **NEW** | `linkedin-connections` (base `linkedin`) | the connections page, sorted by recently added | none: outside every bank (section 4) | off |
| YouTube | Watch later · History | `watch_later`, `history` (youtubeLists) | as today | as today | as today |
| YouTube | Playlists **NEW** | `playlists` (youtubeLists) | `youtube.com/feed/playlists`, then each playlist's own page | `youtube-playlist` · the playlist's name | off |
| YouTube | Liked videos **NEW** | `liked` (youtubeLists) | `youtube.com/playlist?list=LL` | `youtube-playlist` · `Liked videos` | off |
| TikTok, Pinterest, Spotify, Goodreads | their one list | as today | as today | as today | as today |
| Substack | Saved · Liked · History · Subscriptions | as today | | | |
| GitHub | Stars · Your repositories | account | | | |
| Browsers | Bookmarks · Reading List (Safari) · Tab groups (Chrome) · YouTube history (Chrome) | app | | | |
| Notes | Notes | app (section 5) | | | |
| Notion | Pages you chose | account (section 5) | | | |
| Sites with a save control (X, Instagram, GitHub, TikTok, Reddit, YouTube) | Saves you make | click, `owner: app`, this Mac (`SiteSavePrefs`) | | | off |
| Chats, Calendar, Reminders, Contacts, meetings, agents, feeds, books, folders, traces | one stream each, named for what it holds, `control: setup` where a choice is needed | | | | |

The exact origin and folder strings are whatever the export readers write today (`saved_exports`, `media_ingestor`,
`history_index.LIST_ORIGINS` / `LIST_FOLDERS`); a gate test asserts every new list's items are index-only.

**How the new lists stay inside G206:**
- The person turns each list on (the reading acknowledgement first, as today). The person's own agent opens that
  list's page in their own signed-in browser; nothing is clicked that changes a list; never a feed, a timeline, a
  profile of someone else, or messages. A likes tab is a page that holds only the person's own list; reposts are mixed
  into the profile timeline, which is why they are not here (section 8).
- **A key with a base** shares its site's address rules, handle, profile link and pause (a login wall pauses every
  list of that site; only "I signed in" / Try again lifts it, as today). `cicada_record_saved_list`'s `platform` takes
  the new keys (schema, `tool_door`, `cli_map`, `docs/architecture/mcp.md`).
- **Folders are their own pages.** A list's read includes its folders: after the All page the agent opens each folder
  (at most 12 a read, the least recently read first) and reports each post with the folder it is in. The whole pass is
  one read against the daily bound; the calls of one pass are tied together (the implementer picks how). A site or
  account with no folders reports none and `folderCount` stays 0 — nothing is shown for it.
- **Catching up.** The first read of a list may go deeper (a bounded number of screens, far more than a later read);
  a later read stops when it reaches items already kept. Older items still come only with the site's export, dropped
  on the window.
- **The daily bound stays 10** recorded reads a bank across the saved-list family (YouTube's lists stay outside it on
  their own cadence, as today). When several lists are due the one read longest ago goes first, so a later key is not
  starved.
- A row may carry `posted` when the list shows the post's date. Where a list shows no words (a grid of pictures) the
  item is kept with its link and author only.

## 3. The page

Design direction D stands (ProgressiveColumns, SF only, ring not shadow, the accent in its six uses, a real mark or
none). The look is the Sleep queue's soft card: `softCardRow(ground: .page)` for a source card and for an item card
(`sourceCardChrome` is only for a card that holds cards), `StatusWord` for state, `SectionLabel`, `TextTabs`,
`NeutralButton`. `SoftCardTests` fails a re-spelled card. References: the ChatGPT desktop app's connectors list (one
row shape everywhere, one control showing state) and Superwhisper's cards.

### 3.1 Root (nothing open)

- Header: `Sources`, eyebrow "N connected", one button: **Check connections** (3.3). No Add source button and no add
  overlay: every source is on the page.
- A find field, then `TextTabs` by kind with counts — All · Conversations · Documents · Events · Work · Saved · Media
  (each entry's existing `SourceShelf`). The arrow keys walk the visible tab's order.
- One column (capped like the Sleep page) of **source cards**, one shape for every source:
  - line 1: the source's real mark, its name; trailing: the state as `StatusWord` and when it last read;
  - line 2, quiet: the streams that are on, by name with counts ("Bookmarks 214 · Likes 1,032 · 3 folders"). For a
    source not connected: the streams it can read, in the tertiary ink, and a compact **Connect** `NeutralButton` at
    the trailing edge (outside the card's own tap target).
  - The whole card opens the source. No fold, no item previews, no chevron.
- Order: what needs the person first (signed out, needs access: amber word and one button naming the fix), then
  connected (most recently read first), then not connected under one `SectionLabel`.
- **One truth:** the card's state word, the eyebrow's count and the needs-you split come from `SourceCatalogRow`
  exactly as today (`SourceCatalog.resolved`, the 2026-11-06 sources-truth rules). Streams add only the per-stream
  names, counts and health.
- Chat exports and Files and links appear only while they hold something; they are never offered.
- Statistics stays where it is, as the quiet tail under the list (its contributor column still opens from it).
- Beside an open source the list stays the narrow DR-34 rows (`SourceCatalogRowView`), in the same order.

### 3.2 A source's page

Applies to **every** source: the head, the Reads block and Check now. The `DetailHeader` is unchanged.
1. **Head:** mark, name, state word; under it one quiet line: the account ("@handle") and how it is read ("Read in your
   browser by <the person's AI app>, about once a day"). The browser-reading facts (whose sign-in, who else sees what
   is read, never posts, how to stop) live in the first-use acknowledgement sheet, as today, and in the line's hover.
   No diagram, no animation, no standing paragraph.
2. **Reads** — a `SectionLabel` row with **Check now** at its trailing edge, then one soft block with a row per
   stream: name; a quiet line (what it holds and how deep it goes, a few words; the hover says that the newest are
   read, older ones come with an export, and that unsaving at the site does not remove it here); count · last read, or
   the state word; then a switch (`control: switch`). A `control: setup` stream shows the source's existing connect
   step in place of the switch (the chat picker, the Telegram QR, Notion's sign-in and scope, GitHub's code, the
   folder chooser, the ISBN scan, a feed's address, traces' consent, a permission's exact fix).
3. **Items** — each source keeps its existing content (chats, the week, faces, folders, books, GitHub's page, the
   Notes browser, an agent's conversations, feeds). For a source whose streams are lists (kinds saved, liked, history,
   later, playlists): `TextTabs` per stream that holds items (All first), a folder menu beside the tabs when
   `folderCount > 0`, then item cards in the queue card's layout — title, two lines of words, footer
   `[mark] author · kept <age> · lists ("Saved · Liked") · depth word` (nothing for `kept`). Five by default, then
   "All N" opens the full list in the page's place (DR-81).
4. **Footer:** as today (refresh, disconnect, what removes this source's items). **No import action anywhere on a
   source page** — the owner, later on 2026-11-24, asked about one quiet "Import an export…" action kept for LinkedIn
   and Goodreads: "yes have it go too". This overrides any brief that still mentions that action: do not build it.
   LinkedIn's footer keeps only **Forget kept connections** (a removal, not an import).

Removed: `WebReadingCard` and its scene; every "Import a file" way row and `IntakePanel` on a source page; the import
action on an empty search; the Add source button, `SourceAddOverlay`, and `pendingAddSource` (a caller now opens that
source's page). Files still come in through the window drop, ⇧⌘I, the palette, Home, the Agents page and onboarding
(ruling 58). Notion's catalogue entry leaves the file group; it is its live connection.

**Onboarding** mounts the same page in a small sheet: a compact mode (head, Reads, the connect step; no items, no
Check now). Without the streams answer yet, the sheet falls back to the catalogue row.

**Tests and rules A2 rewrites, not works around:** `DesignConsistencyLintTests` (DR-75's Sources adopter),
`SourcesV2Tests`, `SourcesListTests`, `SourceShelfTests` (the web-reading scene), `SourceGridTests`, `SourcesV3Tests`,
`OnboardingSourceTests` if the type name moves; new DESIGN_RULES §9 line dated 2026-11-24 amending the 2026-11-03
(import at the top right), 2026-11-04 (ways block), 2026-11-05 (root grid) and 2026-11-06 (shelves, the web-reading
card) lines.

### 3.3 Checking a connection

**Check now** (a page) and **Check connections** (the root) end, for every stream, in one definite word and a time:
Read · Signed out · Couldn't read · Needs access · Your AI app reads it next · Not installed.
- `how: app` — the app runs that reader now, for the readers that already have a run-now (`ChannelActions.sync`'s
  routes); a missing permission shows the exact fix.
- `how: account` — the backend asks the service with the kept sign-in (the connector's own check); a refusal says so
  and offers Reconnect.
- `how: browser` — Cicada cannot open a browser (G166). A check stamps `checkRequestedAt` on that list; `due` serves
  requested lists first (still inside the daily bound, still one list an offer); the row says "Your AI app reads it
  next" with the last result beside it. A check **never lifts a pause**: a signed-out list keeps saying so, with Try
  again, as today.
`POST /sources/streams/check` (body: source ids, or empty for all) does the backend's part and returns the same rows.

## 4. People met: LinkedIn connections by date

- **Way in without a file:** the list `linkedin-connections` above, recorded through `cicada_record_saved_list`'s
  existing outside-the-bank branch (the Goodreads precedent): rows `{name, profile_url, headline, connected}` where
  `connected` is an ISO day when the page shows a date, else the page's own words ("3 weeks ago") from which the
  backend stores a day and a precision (day · week · month) computed from the read day. The agent reads the
  connections page only: never a profile, never the contact-info overlay, no email field exists.
- **Kept in the directory that already exists** outside every bank. An agent read **merges** by profile link: never
  deletes, never moves `exported_on` backwards, keeps the finer day. No model reads it.
- **The stream in the app:** `GET /sources/linkedin-connections/list` — newest first, with name, headline, link, day,
  precision and the matched page's id when there is one (one cached match per request). Local API only: absent from
  `/mcp`'s remote table and `/v1`, 409 on a demo bank, wiped by the existing forget and by trashing the bank. This
  amends the sentence "the directory's API gives its day and size, never a name" for this one route.
- **For the person's agents:** one read-only door on stdio and the CLI only, never remote: connections in a date
  range (at most 50), with the matched page when there is one; names are read from the directory at that moment and
  never written to a bank or the telemetry ledger. This is how "who did I connect with that week" is answerable.
- **Into memory — the person gets the page, never the connection** (owner, later on 2026-11-24: "a linkedin
  connection doesnt need a page just for the sake of having a page, the person is what gets a page"; "having linkedin
  profiles match people in contacts, and other sources, mentions, conversations is extremely important"). A connection
  never makes a page. A person's page is born by the rules that already exist (2+ conversations, the exchanges rule,
  a Contacts card the person's own words name in full), and LinkedIn then attaches to that person. What this work
  makes true:
  - **At birth, not a night later:** when a person's page is born or made by hand or by an agent, the kept
    connection that matches it attaches in that same write path or run (today only Sleep's tail does it, and it skips
    a page that was dirty).
  - **One person across the two directories:** a waiting Contacts card and a waiting connection with the same full
    name are the same lead; when the card's promotion makes the page, the page is born with both.
  - **A held name knows its connection:** a name waiting in the pending store that equals exactly one connection's
    full name carries that lead to its page's birth (nothing about the connection is written into the bank before).
  - **Never the wrong person:** a name-only match stays what the owner ruled on 2026-10-17 (confident, never
    alias-only), but it is refused when the bank holds a same-name doubt for that name, when two connections or two
    pages share it, or when the page names a different profile.
  - Whether one full-name mention of a connection should be enough for a page, as it is for a Contacts card, is the
    owner's call (section 8) — not built.
- **A profile link wears its site's mark** (owner: "the link to the profile with the logo of the site kind of how the
  logos appear in the consolidation queue like for the meeting platform in hex transcripts"): on a person's page and
  in the connections list a LinkedIn, X, Instagram or GitHub link is a chip with the bundled real mark (the app
  already ships them), never a stand-in glyph or a monogram. Found: the page's "Sites and links" draws a monogram "L"
  because the Swift site key is `linkedin.com` while the marks are keyed `linkedin`; "Where to check" draws a
  briefcase. Bundled assets only, nothing fetched.

## 5. Notes and Notion keep their shape

- **First task, a spike:** does Notes' scripting return nested folders (each folder's `container`) and in what order?
  The result decides the rest; say so in the PR.
- Notes: the reader also sends each note's folder path, beside the dump the way `noteAccounts` travels (a locked note
  sends none: G234 is untouched, every property stays behind the unlocked filter). The backend keeps the path, ids a
  folder by its full path, returns folders as a tree in Notes' own order, orders notes by the modified instant (pinned
  first, as Notes does) and serves a one-line snippet. Pinned shows only where the app can already read pins; where it
  cannot, one line says so with the button that opens the setting (never a prompt).
- Notion: keep each page's parent path (only parents the person shared) and database title, group by database or
  parent page, order by last edited. Favourites are not read.
- Not here: noticing a note deleted in Notes, attachments, checklist state.

## 6. Depth: light until the person talks about it

1. **Kept** — every save: title, link, site, the words the list shows; findable by words and meaning; no model, page,
   claim or question.
2. **Seen** — its picture is in the picture index when Cicada already holds one (a public page's preview, a YouTube
   still). Unchanged; a walled post has none (section 8).
3. **Read / Watched — NEW, only on the person's own located words** naming the link or the whole title, or a reason
   they gave (`WHY_LINK`, `WHY_TITLE`, the person keys; never `WHY_LIT`, never a retrieval hit):
   - a save from a platform list (kind `list`) wakes for one normal Sleep read, as a bare save already does;
   - and an **ask** is left for the person's own agent: a provider video goes on the video queue, a walled post on the
     reading queue, both marked as coming from a mention (a new origin, kept through the stores' cleaning). The ask is
     honoured only while agent reading is on and that site's list is on, and it leaves when either is turned off or
     the person removes it. At most 5 a conversation (the wake's own bound) and 5 a day.
   - It is only an ask: Cicada never starts an agent, downloads nothing and derives no stream. What the agent records
     is what those doors record today (a summary and short quotes; frames stay the agent's own work).
4. **Tracked** — a source the person asked to keep current (G61), unchanged.

A change to the video queue or its callers runs `.claude/skills/verify-video-queue/run.sh`.

## 7. The notch offer connects

- **One connect plan** (`SourceConnect.plan(entry, state)` → start · needsConsent · needsChoice · openPage), used by
  the page's switch, the root card's Connect and the notch. The reading-agent model and the first-use acknowledgement
  sheet move to the app level so all three reach them.
- **A site's Yes:** with a current acknowledgement and agent reading on, it turns on the site's existing saved list
  (never a NEW stream) and, where the site has a save control, noticing saves on this Mac. Without the
  acknowledgement it turns on only noticing saves and opens the source's page with the acknowledgement sheet raised;
  nothing is turned on silently. A site with no save control (LinkedIn, Pinterest, Substack, Spotify, Goodreads) may
  offer too; its Yes follows the same plan.
- **A Mac app's Yes** starts its reader when one click can (the system's own permission prompt follows) and opens its
  page only when a choice is needed.
- **Honest words:** the write returns before anything is confirmed; the panel says "Turned on", and says "will ask
  why" only while ask-why is on (else it offers it in one line). The page says Connected once a read is dated, as
  today.
- **One truth:** the offer's "already connected" is the catalogue's status plus `SiteSavePrefs`; every switch the
  notch can flip has a row on the source's page (the "Saves you make" stream).
- A skipped decision (first minute, another panel open, memory still loading) does not spend the visit.
- Without Accessibility a site cannot be seen; the app never prompts for it (ruling 77), so the "Saves you make" row
  says it in one line with the button that opens the setting.

### 7.1 The ask-why panel on a bookmark or a save (owner: "make sure the notch correctly works and appears when i bookmark or save something")

Read from the code on 2026-11-24; each is a case where the person saves and nothing appears, or the app says
something untrue:
1. A site save is gated by the **bookmark** ask-why switch, which a site's Yes never turns on. Connecting a site means
   asking why on its saves: a site save is gated by that site's own switch.
2. The ask-why toggle on a browser's page turns on only that browser's watch while the switch itself is global, so it
   reads on everywhere and works in one browser. One switch, every supported installed browser.
3. There is no mounted way to grant Accessibility for site saves (the grant button lives in a view nothing mounts;
   the Permissions row shows only while traces are on). The "Saves you make" row and a site's Yes show the one line
   and the button that opens the setting; never a prompt (ruling 77).
4. After the first ask-why panel of a session, connect offers are skipped until relaunch (`saveWhyOpen` reads a state
   that is never cleared).
5. A site save made while Sleep is writing is dropped (the refusal is swallowed): hold it and retry, as an answer is.
6. Chrome profiles other than Default: the bubble opens a panel no file ever confirms. Read the profile in use.
7. Safari may ask about a bookmark that synced in from another device (no instant to check): do not ask without one.
8. Nothing tells the person why no panel came. The source's page says the state of each piece in words (ask-why on or
   off, the browser watched or not, Accessibility, the site connected or not).
Verified on a scratch copy of the app (`verify-cicada`): the file path end to end with a synthetic bookmarks file. The
real star click, granting Accessibility to a second app copy and a real save on a site are the owner's own hands.

## 8. Rulings

**Ruling 78 (owner 2026-11-24).**

*Said in his words (quoted at the top):*
- (a) The Sources page: one card shape, streams, no diagram, no file rows (amends DESIGN_RULES §9 lines of
  2026-11-03, -04, -05, -06 and DR-75's Sources adopter).
- (b) New browser lists under G206's rules, each off until turned on: X likes; folders, collections and playlists as
  filing labels (X, Instagram, YouTube).
- (c) LinkedIn connections in chronological order: read by the person's agent from the connections page into the
  directory outside the bank; listed to the app on the local API; one stdio/CLI read door so the person's agents are
  "aware of it".

*My reading of his words — built, and one line to undo each if he says no:*
- (d) Instagram likes, Reddit upvoted and YouTube liked videos are lists of the same kind (he said "same to a certain
  point" and "save posts and stuff"); each is off until he turns it on.
- (e) A save the person talks about wakes even when it came from a platform list, and an ask is left for their own
  agent to watch or read it (amends ruling 30 point 1 and ruling 62 point 3 for a mentioned list save; amends R-VU3
  "the queue holds user requests only", the video spec's N-e "no auto-queueing" and R-RW8 "person-driven, never
  scheduled" for an ask the person's own located words caused).
- (f) *Withdrawn the same day.* I had read his words as "a waiting connection makes a page when his own words name
  it in full". He answered: "a linkedin connection doesnt need a page just for the sake of having a page, the person
  is what gets a page." A connection never makes a page; see section 4.

*Said later the same day:*
- (g) No import action anywhere on a source page ("yes have it go too").
- (h) Matching a LinkedIn profile to the same person in Contacts, chats, meetings, mentions and conversations is
  "extremely important" (section 4).
- (i) A profile link wears its site's real mark (amends DR-79's glyph for a person's links; bundled marks only).
- (j) "cron jobs might be the answer for triggers to keep everything updated … check where crons make sense":
  section 10.

**Waiting on the owner — not built:**
1. Reposts: mixed into the profile timeline, which no list page covers.
2. Accounts followed (he said "maybe"): accounts are a new kind of item (G120 sketches it).
3. A first name in a note tied to a same-week connection: a lead only, or may Sleep join it (undoable)?
4. A post's picture or video itself (a walled host): the agent would have to hand over the picture's public address
   for one fetch into the picture index; frames of an online video are the agent's own work today.
5. One full-name mention of someone who is a LinkedIn connection (and has no Contacts card): enough for their page, as
   it is for a Contacts card, or wait for the normal second mention?
6. A daily run of his own AI app to read the lists that are due (section 10): it spends his plan and needs his
   browser open, so it is his to turn on.

## 9. Tracks (one PR each, to `dev`)

| Track | Branch | Owns | After |
|---|---|---|---|
| A1a | `feat/source-streams` | `source_streams`, `GET /sources/streams`, `POST /sources/streams/check` and `checkRequestedAt`, the items route's `stream`/`folder` parameters and `lists`/`folders`/`depth` (kept, read)/`posted`, the cached membership count | — |
| A1b | `feat/more-lists` | the NEW browser lists except connections (keys with a base, YouTube's two), the folder pass, catching up, fair `due`, `posted` on the record row, the index-only gate test | — |
| A2 | `feat/sources-redesign` | the app page (section 3), the app-level reading model and connect plan the notch will reuse, the "Saves you make" row over `SiteSavePrefs` | — (codes against 2.1; merges after A1a) |
| A4 | `feat/notes-notion-shape` | section 5: reader and backend | — |
| A3 | `feat/linkedin-connections-stream` | section 4: the list key and its record branch, merge, the list route, the stdio/CLI read door, attaching at a page's birth, one lead across Contacts and LinkedIn, the same-name refusals | A1b |
| B1 | `feat/notch-connects` | section 7 and 7.1, verified on a scratch app | A2 |
| B2 | `feat/sources-streams-views` | the app's connections list, profile links as chips with real marks, Notes and Notion trees, lists and depth on item cards | A2, A3, A4 |
| B3 | `feat/depth-on-mention` | section 6, `asked`/`watched` on rows | A1a |
| C1 | `feat/source-schedules` | section 10, the parts inside today's rules | A1a |

Each PR updates the area doc it makes wrong, its `feature-status.md` line, the G245 row and TODO.md; the first to
merge adds ruling 78; A2 adds the §9 line and cites its DR ids. A PR that adds an MCP tool, a tool argument, a route
or a page writer runs the repo-wide gate tests (demo write table, handshake budget, R12, `cli_map` table, replica
route inventory, write-admission sites, contract pins). Tests: the touched files, their importers and those gates;
every `*Lint*` Swift suite for an app PR. Nothing reads a real bank. Privacy: placeholders only in code comments,
tests, docs and PR text.

## 10. Schedules: what keeps each source current

Read from the code on 2026-11-24. Most sources already update by an event or a timer; four do not.

| Source | Trigger today | Worst case |
|---|---|---|
| Messages, WhatsApp, bookmarks, tab groups, watched and meeting folders | a file watcher in the app | seconds, while the app runs |
| Calendar, Reminders, Apple Books, Voice Memos | app launch, a change event, every 3 hours | about 3 hours |
| Contacts | launch and the store's change notice | about a day |
| YouTube history from Chrome | every 10 minutes | 10 minutes |
| Telegram | a live connection | live |
| Notion, GitHub, Linear | the backend's own job, every 6 hours | 6 hours, while the backend lives |
| **Apple Notes** | every 2 hours, only while Notes is already open | unbounded while Notes is closed |
| **Feeds, calendar feeds, Reddit / Pinterest / X connectors** | only at the end of a Sleep run | a whole Sleep interval; never when Sleep is manual or a night had nothing to read |
| **Browser lists** (X, Instagram, LinkedIn, Reddit, YouTube, Substack…) | only when the person's agent happens to ask for the reading queue | unbounded; 20 hours is a floor, not a ceiling |
| **LinkedIn connections** | a file the person drops | until they drop another (section 4 changes this to a browser list) |

**Inside today's rules (track C1):**
- Feeds, calendar feeds and the tier-1 connectors get their own backend job every few hours, beside the tier-2 job:
  the same network gates, the same yield to a Sleep that is writing. No longer tied to Sleep.
- A scheduled night with nothing to read still runs the engine-free tail.
- Notes is read when Notes is opened or comes to the front, besides the 2 hour timer. Cicada still never launches
  Notes.
- The hook's reading line names the list that is due ("your X bookmarks are due"), is sent only to a harness that
  can drive a browser, and repeats on a later prompt of the same session while the list stays due. Normal use of the
  person's agent then keeps the lists current without a schedule.

**Needs the owner (question 6):** a real schedule for the browser lists means starting the person's own AI app
without them (a launchd job or the harness's own scheduled task), once a day, only when a list is due, with capture
and recall off, skipping when their browser is not open and approved. It amends R-RW8 ("never scheduled"), rulings 4
and 15 (a plan is spent only on the person's start) and the test that locks "Cicada never spawns a browser", and it
costs plan usage on every run. Whether an agent can drive the browser unattended at all is unmeasured.
