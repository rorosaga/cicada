# Sync connectors (bookmarks, Notes, Spotify, read-later)

Research date: 2026-06-16. Scope: feasibility + how-to for a "feed" that ingests
external personal sources into Cicada as entities (or as episodes that promote into
entities). Covers four prioritized sources: browser bookmarks, Apple Notes, Spotify,
and Substack/read-later. Confidence is marked per claim; anything I could not verify
against a primary doc is flagged `[unverified]`.

## TL;DR

- **Bookmarks and Apple Notes are the easy, keyless, offline, privacy-clean wins.** Both
  live in local files on the same Mac the FastAPI backend already runs on. Safari bookmarks =
  a binary `~/Library/Safari/Bookmarks.plist`; Chrome = a JSON `Bookmarks` file; both also
  export to the universal Netscape-HTML format. Apple Notes = a local `NoteStore.sqlite`
  (protobuf-encoded note bodies) readable by existing Python libraries. **Zero OAuth, zero
  network, zero rate limits.** Start here.
- **The clean architectural fit is: a connector produces *episodes*, not entities directly.**
  This preserves Cicada's promotion model (no graph pollution from one-off bookmarks) and
  reuses the existing source-agnostic Sleep pipeline. A connector is just another ingestion
  mouth feeding `episodes/`, exactly like the Telegram bot or conversation upload already do.
- **Spotify is the only source needing real OAuth** (Authorization Code + PKCE, mandatory
  after the 27 Nov 2025 migration). Rate limits are a rolling-30s window, undocumented
  numbers, 429 + `Retry-After`. Saved tracks / playlists / top artists are all one-call-each
  paginated GETs. Doable but it's the heaviest connector and the least "knowledge-graph"-shaped
  data — recommend deferring it to a post-MVP "taste/context" connector.
- **Read-later is in flux: Pocket shut down (8 Jul 2025, API killed 12 Nov 2025).** The live
  options are RSS (keyless, universal, works for Substack + any blog) and the **Readwise
  Reader API** (`Token` header, simple REST, has List/Save/Update/Search). For a thesis,
  **RSS is the keyless baseline; Readwise Reader is the one paid API worth wiring** if Rodrigo
  uses it.
- **macOS privacy gotchas are real but tractable:** reading `~/Library/Safari/` and the Notes
  SQLite requires **Full Disk Disk Access (FDA)** granted to whatever process opens them, and
  Apple Notes via AppleScript triggers a TCC automation consent prompt. These are one-time
  user grants, but the packaged `.dmg` app must request them in onboarding.

## Findings

### Design framing: connectors emit episodes, not entities

Before the per-source detail, the load-bearing decision: **a sync connector should write
timestamped episode chunks into `episodes/`, not create entity pages directly.** Reasons,
straight from Cicada's own architecture (CLAUDE.md):

- The Awake cycle is explicitly "no LLM processing at capture time — just logging." A connector
  is an Awake-phase ingestion source, peer to MCP capture, Telegram, and conversation upload.
- The **entity promotion model** exists precisely to avoid graph pollution from single mentions.
  If every bookmark became an entity, you'd get hundreds of dead `concept`/`tool` nodes. Routing
  bookmarks through `episodes/` means a link only becomes an entity if it *recurs* or is
  *substantively engaged* — which is the whole thesis.
- The Sleep pipeline is already "source-agnostic… processes all unprocessed episodes regardless
  of source." So connectors need **zero new pipeline code** — just a writer that emits the
  standard episode shape (`ep_YYYY-MM-DD_NNN`, timestamp, `processed: false`).
- Dedup is already a stated requirement for conversation upload ("timestamp + content hash").
  The same hash gate handles re-syncing the same bookmark file nightly.

So the per-source work below is really just **"how do I read source X and turn each item into an
episode chunk with a URL, a title, a captured-at timestamp, and (optionally) a fetched summary."**
The mapping to a Cicada entity happens later, in Sleep, via the existing extraction prompts.

What an ingested item looks like as an episode (proposed):

```
ep_2026-06-16_014  (source: connector/safari_bookmarks)
captured: 2026-06-16T09:00:00Z
bookmarked_at: 2024-11-02T18:31:00Z   # original add time, if available
url: https://leann.berkeley.edu/...
title: "LEANN: low-storage vector index"
folder: "thesis/vector-search"        # source-native grouping = a tag hint for Sleep
summary: "<optional fetched + LLM one-liner>"
```

When Sleep promotes it, the natural entity type is usually `concept` or `tool` (an article
about Knowledge Graphs), sometimes `project`/`company`. Folder names and playlist names become
**tag hints** and folder co-membership becomes a **relationship hint** ("these 6 links live in
the same `thesis/` folder → probably related to the same project entity").

---

### 1. Browser bookmarks — keyless, offline, trivial. Do this first.

**Confidence: high.** All file locations and formats below are well-documented and stable.

#### Safari (the native-Mac case)
- File: `~/Library/Safari/Bookmarks.plist` — a **binary property list** holding the full
  bookmark hierarchy (folders + items), including the Reading List as a special folder.
  ([Apple Community](https://discussions.apple.com/thread/7728443),
  [ChrisWrites](https://www.chriswrites.com/import-and-export-all-of-your-safari-bookmarks-as-a-single-file/))
- Read it with Python's stdlib `plistlib` (`plistlib.load(open(path,'rb'))`) — **no third-party
  dependency, no network.** The structure is nested dicts with `WebBookmarkType` keys
  (`WebBookmarkTypeLeaf` = a bookmark, `WebBookmarkTypeList` = a folder); each leaf has
  `URLString` and a `URIDictionary.title`.
- Reading List items live under the `com.apple.ReadingList` folder and carry
  `DateAdded` + sometimes a `PreviewText` snippet — useful free summary signal.
- There's a maintained CLI for reference: [`safari-bookmarks-cli`](https://pypi.org/project/safari-bookmarks-cli/).
- **Privacy constraint:** `~/Library/Safari/` is TCC-protected. The reading process needs
  **Full Disk Access**. This is the single biggest UX friction for the Safari connector.

#### Chrome / Edge / Brave / Arc (Chromium family)
- File: `~/Library/Application Support/Google/Chrome/Default/Bookmarks` — **plain JSON**, no
  FDA needed (it's in `Application Support`, not a TCC-protected store).
  ([justsolve wiki](http://justsolve.archiveteam.org/wiki/Chrome_bookmarks))
- Fields per node: `id`, `name`, `type` (`url`|`folder`), `url`, `date_added`. **Timestamp quirk:**
  `date_added` is microseconds since **1601-01-01** (Windows FILETIME epoch), not Unix — convert
  with `unix = filetime/1e6 - 11644473600`. ([justsolve wiki](http://justsolve.archiveteam.org/wiki/Chrome_bookmarks))
- Multiple profiles = `Default/`, `Profile 1/`, etc. Iterate them.

#### Netscape HTML (the universal fallback)
- Every browser (Safari, Chrome, Edge, Firefox) exports bookmarks to the **Netscape Bookmark
  File Format** — an old but living HTML standard (`<DT><A HREF=... ADD_DATE=...>`). `ADD_DATE`
  is **Unix seconds**. ([minmaxd writeup](https://minmaxd.com/post/html-bookmark-file),
  [MS Learn spec](https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/platform-apis/aa753582(v=vs.85)))
- Parsers exist in every language ([FlyingWolFox/Netscape-Bookmarks-File-Parser](https://github.com/FlyingWolFox/Netscape-Bookmarks-File-Parser)),
  or just BeautifulSoup over `<A>` tags.
- **Why this matters for Cicada:** it sidesteps FDA entirely. The companion app can offer a
  "drop your exported bookmarks HTML here" picker (exactly like the existing conversation-upload
  screen), and parse it with zero permissions. **This is the lowest-friction MVP path** — same
  pattern Rodrigo already built.

**Recommendation within bookmarks:** ship the **Netscape-HTML drag-and-drop importer first**
(keyless, no FDA, reuses upload UI), then add **live Chrome JSON polling** (no FDA), and treat
**live Safari plist polling** as the FDA-gated nice-to-have.

---

### 2. Apple Notes — local, keyless, but the messiest format.

**Confidence: high on access methods, medium on long-term format stability** (Apple changes
the protobuf schema across OS versions — this is a known maintenance tax).

Three access paths, in increasing order of fidelity and pain:

**(a) AppleScript — easiest, lossy.**
- `osascript`/AppleScript can enumerate notes (`name`, `body`, `creation date`,
  `modification date`, container folder). Good for title + plaintext body.
- Limitations: AppleScript is effectively read-only for export, **drops attachments**, and is
  slow for large libraries. ([Simon Willison](https://simonwillison.net/2023/Mar/9/apple-notes-to-sqlite/),
  [clutterstack odyssey](https://clutterstack.com/posts/2024-09-27-applenotes))
- **Privacy constraint:** first AppleScript access to Notes triggers a **TCC "automation"
  consent dialog** ("Cicada wants to control Notes"). One-time, but the user must approve.

**(b) Read `NoteStore.sqlite` directly — high fidelity, format-fragile.**
- Path: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`.
- Note bodies are **gzip-compressed protobufs** ("Apple stores its notes as protobufs and the
  format gets more complicated over time"). You can't just SELECT text — you decode the protobuf.
  ([Simon Willison](https://simonwillison.net/2023/Mar/9/apple-notes-to-sqlite/),
  [swiftforensics](http://www.swiftforensics.com/2018/02/reading-notes-database-on-macos.html))
- Existing libraries do the heavy lifting:
  - [`apple-notes-to-sqlite`](https://pypi.org/project/apple-notes-to-sqlite/) (`pip install`,
    by Simon Willison) — exports to a clean SQLite you can then read trivially.
  - [`apple-notes-parser`](https://github.com/RhetTbull/apple-notes-parser) (Python) — parses the
    protobuf directly, **including tags** (`#hashtags` inside notes — a free relevance/folder signal).
- **Privacy constraint:** the Group Container is TCC-protected → needs **Full Disk Access**.

**(c) Manual export** — Notes.app has no good bulk export; users resort to print-to-PDF or the
above tools. Not worth building around.

**Mapping to Cicada:** an Apple Note is closer to an *episode* than a *bookmark* — it's
free-text the user wrote. Route each note as an episode chunk (title + plaintext body +
created/modified timestamps + folder + inline `#tags`). Sleep then extracts entities from the
note's content exactly as it would from a conversation. Notes folders/`#tags` are strong tag hints.

**Recommendation within Notes:** use **`apple-notes-to-sqlite` as a subprocess** (it already
solves the protobuf problem and is maintained by a credible author) rather than reimplementing
protobuf decoding. Accept the FDA requirement. AppleScript is a fallback if you want to avoid
FDA and tolerate losing attachments. Flag the **schema-fragility maintenance risk** in the thesis.

---

### 3. Spotify — the only OAuth source; defer to post-MVP.

**Confidence: high on auth + endpoints, high on rate-limit *mechanism*, low on rate-limit
*numbers* (Spotify deliberately publishes none).**

#### Auth (this is the work)
- Use **Authorization Code Flow with PKCE**. As of the **27 Nov 2025 OAuth migration**, the
  implicit grant flow, plain HTTP redirect URIs, and `localhost` aliases are **removed** — PKCE
  is the path for desktop/native apps that can't safely hold a client secret.
  ([Spotify auth docs](https://developer.spotify.com/documentation/web-api/concepts/authorization),
  [migration notice](https://developer.spotify.com/blog/2025-10-14-reminder-oauth-migration-27-nov-2025))
- Practical implication for a local Mac app: the redirect URI can no longer be a bare
  `http://localhost`. You need either a **loopback with a registered exact `http://127.0.0.1:PORT`
  redirect** (verify current allowance — Spotify now requires HTTPS or the explicit loopback IP,
  `[unverified]` which exact form they accept post-migration) **or a custom URL scheme**
  (`cicada://callback`) registered by the macOS app. The app opens the system browser, user
  consents, the scheme/loopback catches the code, you exchange code+verifier for tokens, then
  refresh tokens silently thereafter.
- Scopes needed: `user-library-read` (saved tracks/albums), `playlist-read-private` +
  `playlist-read-collaborative` (playlists), `user-top-read` (top artists/tracks),
  `user-read-recently-played` (history). All read-only.

#### Data endpoints (each is a simple paginated GET, `limit`/`offset` or cursor)
- `GET /v1/me/tracks` — saved/liked tracks
- `GET /v1/me/playlists` then `GET /v1/playlists/{id}/tracks`
- `GET /v1/me/top/artists` and `/v1/me/top/tracks`
- `GET /v1/me/player/recently-played`
- ([Web API overview](https://developer.spotify.com/documentation/web-api))

#### Rate limits
- Rolling **30-second window**; exceeding it returns **429 with a `Retry-After` header**.
  Two tiers: **development mode** (default, low) and **extended quota mode** (apply in dashboard).
  **Spotify publishes no concrete numbers.**
  ([rate-limit docs](https://developer.spotify.com/documentation/web-api/concepts/rate-limits))
- For a single personal user syncing nightly, dev-mode limits are a non-issue — you make tens of
  paginated calls once a night.

#### Keyless / offline alternative
- Spotify's GDPR **"Download your data"** export (Privacy Settings → request data) yields JSON of
  library, playlists, and streaming history with **no API and no OAuth** — but it's a manual,
  days-delayed request, not a live sync. ([ByeBye Spotify](https://chrisworth.dev/projects/byebyespotify/))
  Fine as a one-off seed; not a connector.

#### Mapping to Cicada — and the honest caveat
- A saved artist → could be a `concept` or even `person` entity; a playlist → a `concept`/theme;
  genres → `tags`. But **music taste is weak knowledge-graph signal** compared to bookmarks/notes
  that are *about* the user's work. Its value is *contextual/ambient* ("user is into ambient +
  Brazilian jazz") rather than *episodic-memory* material.
- **This is the heaviest connector (full OAuth + token refresh + native URL-scheme handling) for
  the least thesis-relevant data.** Recommend it as an explicit **post-MVP "ambient context"
  connector**, valuable as a *breadth* demonstration ("Cicada ingests anything with an API") but
  not core to the memory-consolidation thesis.

---

### 4. Substack / read-later — RSS is the keyless baseline; Readwise Reader is the one API worth wiring.

**Confidence: high.** The landscape shifted in 2025 and the doc reflects the current state.

#### The big 2025 change: Pocket is dead
- **Pocket shut down 8 Jul 2025; its API was disabled 12 Nov 2025** alongside the end of the
  export window. Do **not** build a Pocket connector.
  ([Mozilla/Pocket help](https://support.mozilla.org/en-US/kb/future-of-pocket))

#### RSS — universal, keyless, offline-friendly, the right baseline
- **Every Substack newsletter has a public RSS feed** at `https://<pub>.substack.com/feed`.
  ([Substack RSS](https://romio.substack.com/p/rss-feeds-vs-email-subscriptions),
  [RSS-Bridge Substack](https://rss-bridge.github.io/rss-bridge/Bridge_Specific/Substack.html))
- Caveats: it's RSS 2.0 with a content extension some readers choke on (a Python `feedparser`
  handles it fine), and **paywalled posts only show a teaser, not full body** — you get title +
  summary + link, which is exactly the episode shape Cicada wants anyway.
- RSS generalizes far beyond Substack: any blog, arXiv, GitHub releases, YouTube channels all
  have feeds. **One `feedparser`-based connector covers a huge surface keylessly.** This is the
  single highest-leverage read-later connector.
- Each feed item → an episode (`title`, `summary`, `link`, `published`, source feed name as a
  tag). Promotion in Sleep decides if a recurring topic becomes a `concept` entity.

#### Readwise Reader — the one paid API worth supporting (if Rodrigo uses it)
- Auth is dead simple: **`Authorization: Token <token>` header**, token from
  readwise.io. No OAuth dance. ([api_deets](https://readwise.io/api_deets),
  [Reader API](https://readwise.io/reader_api))
- Endpoints: **List**, **Save**, **Update**, **Delete**, **Tag list**, **Search** documents.
  List returns rich metadata (url, title, author, summary, location new/later/archive/feed,
  tags, reading progress). ([pyreadwise docs](https://rwxd.github.io/pyreadwise/readwise-reader-api/))
- Rate-limited per token, **429 + `Retry-After`** (per-endpoint limits documented inline). For a
  nightly personal sync this is irrelevant.
- Readwise Reader also **ingests Instapaper, RSS, and (during the migration) Pocket exports** on
  its own side, so wiring Reader effectively gives you a consolidated read-later firehose without
  building per-service connectors. ([Readwise importing docs](https://docs.readwise.io/reader/docs/faqs/importing-content))
- An interesting prior-art signal: a [Readwise Reader **MCP** server](https://github.com/edricgsh/Readwise-Reader-MCP)
  already exists — relevant because Cicada itself is MCP-native; the Bookworm tool could
  *consume* Reader via MCP rather than a bespoke connector. Worth noting as an alternative wiring.

#### Instapaper
- Has an old OAuth 1.0a "full" API (xAuth) but it's gated/awkward to get access to `[unverified —
  current approval status]`. **Better to reach Instapaper *through* Readwise Reader** than to wire
  it directly.

**Recommendation within read-later:** **RSS connector (keyless, `feedparser`) as the universal
baseline**, covering Substack + arbitrary feeds. **Add Readwise Reader** (one-token REST) as the
single optional paid integration that also vacuums up Instapaper/Pocket-legacy/RSS. Skip direct
Pocket and direct Instapaper.

## What this means for Cicada

1. **Build connectors as Awake-phase episode emitters, full stop.** One small interface —
   `Connector.fetch() -> list[EpisodeChunk]` — with a content-hash dedup gate. No new Sleep code.
   This keeps the promotion model intact (bookmarks don't pollute the graph) and reuses the
   source-agnostic pipeline that already exists. This is the single most important design call.

2. **Tier the connectors by friction, ship in this order:**
   - **Tier 0 (keyless, no permissions, reuses existing upload UI):** Netscape-HTML bookmark
     drag-drop importer; RSS connector (Substack + any feed).
   - **Tier 1 (keyless/local, no special permission):** Chrome JSON bookmarks (Application
     Support, no FDA).
   - **Tier 2 (local but FDA/TCC-gated):** Safari `Bookmarks.plist`; Apple Notes via
     `apple-notes-to-sqlite`. Requires onboarding to request Full Disk Access + Notes automation.
   - **Tier 3 (network + token, low friction):** Readwise Reader (one `Token` header).
   - **Tier 4 (full OAuth, post-MVP):** Spotify (PKCE + native URL scheme).

3. **Source-native structure is free relationship/tag signal.** Bookmark folders, Notes folders
   and `#hashtags`, playlist names, RSS feed names → feed these to Sleep as **tag hints** and
   **co-membership relationship hints**. This is cheap and improves extraction quality without
   any new ML.

4. **Summaries are an optional Sleep-time enrichment, not a capture-time job.** Capture stores
   URL + native title + native snippet only (cheap, offline). If you want an LLM one-liner +
   personal-relevance note, generate it during Sleep (where LLM calls already happen), not at
   ingest — consistent with "no LLM at capture time." For bookmarks, fetching the page body for a
   better summary is a nice-to-have that should degrade gracefully (paywalls, dead links).

5. **macOS packaging reality:** the `.dmg` onboarding flow (already specified in CLAUDE.md) must
   add: a **Full Disk Access** request (for Safari plist + Notes SQLite) and a **Notes automation
   consent** prompt. Tier-0/1 connectors need *neither*, which is exactly why they should ship
   first and carry the MVP demo.

6. **Spotify is breadth, not depth.** It proves "Cicada ingests any API source," which is a nice
   thesis bullet, but the data is ambient-context, not episodic-memory. Don't let its OAuth
   complexity block the MVP.

## Recommendation

**Ship two keyless connectors for the MVP and frame them as "the feed": (1) a bookmarks
importer that accepts the universal Netscape-HTML export via the existing file-drop UI, and
(2) an RSS connector (feedparser) covering Substack and arbitrary feeds.** Both are offline,
keyless, permission-free, and reuse the conversation-upload pattern Rodrigo already built. Both
emit standard episode chunks into `episodes/`, so the Sleep pipeline and entity-promotion model
absorb them with zero new consolidation code — and that *is* the thesis-relevant story
(source-agnostic ingestion + promotion-gated entity creation).

**Then, as clearly-labeled post-MVP connectors:** add **Apple Notes** (`apple-notes-to-sqlite`
subprocess, FDA-gated) and **live Chrome/Safari bookmark polling** for richer local capture;
add **Readwise Reader** (single-token REST) as the one read-later API worth wiring since it also
consolidates Instapaper/Pocket-legacy/RSS; and treat **Spotify** (PKCE OAuth) as an
ambient-context breadth demo, not core scope. **Skip direct Pocket (dead) and direct Instapaper
(reach it via Readwise).**

The unifying principle: **connectors are dumb episode mouths; intelligence stays in Sleep.**

## Open questions

- **Which read-later tool does Rodrigo actually use?** RSS covers Substack regardless, but
  whether to build the Readwise Reader connector depends entirely on whether he has a Reader
  account/token. If not, RSS alone is enough for the MVP.
- **Live local-file polling vs. manual export for bookmarks/Notes?** Live polling (watch the
  plist/JSON/SQLite, re-sync nightly) is more "magical" but pulls in FDA/TCC permission cost and
  packaging work. Manual export (drop the HTML/run the export) is keyless and ships now. Which
  fidelity does the thesis demo need?
- **Is Spotify in scope at all for the thesis, or is it scope creep?** It's the only OAuth
  connector and the least memory-relevant data. Worth a deliberate yes/no rather than drifting in.
- **Entity-mapping policy per source:** should a bookmarked article promote to a `concept`/`tool`
  entity, or stay as a retrievable LEANN chunk unless it recurs? My recommendation is "episode →
  promotion-gated," consistent with D2-research-only, but this interacts directly with the
  unresolved entity-model decision.
- **Custom URL scheme vs. loopback redirect for Spotify PKCE** post-27-Nov-2025 migration — the
  exact redirect-URI form Spotify now accepts for native macOS apps is `[unverified]`; needs a
  10-minute test against a real dashboard app before committing.
- **Notes protobuf schema fragility:** relying on `apple-notes-to-sqlite` inherits an
  Apple-can-break-this-any-OS-update risk. Acceptable for a thesis, but worth stating as a
  limitation rather than discovering it on a demo day.
