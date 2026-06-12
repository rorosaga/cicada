# Media Ingestion (Sources Pipeline) — v2 Design Spec

**Axis owner:** Media ingestion / Sources pipeline
**Branch:** `feat/v2-revamp`
**Status:** implementation-ready
**Goal addressed:** Owner goal 6 — browser bookmarks, YouTube watch-later, Instagram reels feeding serendipitous agent recall.

---

## 1. Summary & Core Decision

Saved media (a bookmark, a YouTube video, a pasted URL) enters the system through a new
`/sources` router, gets **lightweight metadata enrichment** (Open Graph title/description via
`httpx` + `bs4`; YouTube via the keyless oEmbed endpoint), and is written to **two places at once**:

1. **An episode** in `memory/episodes/` with `source: bookmark|youtube|instagram|url` and a
   structured body. This is the existing, source-agnostic Sleep intake — the extraction pipeline
   pulls concepts/tools/people out of the saved page unchanged. **No Sleep code changes required.**
2. **A first-class entity** in `memory/entities/` of a **new `media` entity type** (added to the
   closed enum, now 9 types). The media entity is a graph node from the moment it is saved (it does
   not wait for the promotion threshold), so an agent can surface it serendipitously.

**Why a `media` entity at save time, not reuse `concept`+tags, and not wait for promotion:**

- A saved bookmark is, by definition, *already* a substantive deliberate signal — the promotion
  model exists to filter conversational noise (single fleeting mentions), which does not apply to an
  explicit "save this" action. So media items skip promotion and are written directly.
- Reusing `concept` would conflate "an idea the user discussed" with "a URL the user bookmarked",
  polluting concept hubs and breaking the graph-colouring contract (each type = one colour). A
  dedicated `media` type (colour: **pink `#EC4899`**) keeps the visualization legible and lets the
  hub axis build a "Saved Media / Reading List" hub trivially by grouping on `type: media`.
- The media entity carries the canonical `url`, `site`, `channel`, `thumbnail` in frontmatter so the
  companion app can render a thumbnail card and the MCP can answer "what did I save about X" without
  re-fetching anything.

The episode is what the **Sleep cycle consumes** (extracts *other* entities from); the media entity
is what the **graph and agents reference**. The Sleep cycle links them naturally: when Stage 1
extracts e.g. a `tool` mentioned in a saved article, the article's media entity and that tool entity
both cite the same `source_episode`, and Stage 2 wires the edge.

**Serendipity story (concrete):** The user bookmarks a YouTube video on *reinforcement learning for
robotic grasping*. It becomes `media` entity `media-rl-robotic-grasping` + episode `ep_..._NNN`
(`source: youtube`) with the title/description/channel in the body. Next Sleep cycle, Stage 1
extracts `concept: Reinforcement Learning` and `concept: Robotic Grasping` from that episode body,
and Stage 2 draws edges `media-rl-robotic-grasping —references→ reinforcement-learning`. Weeks later
the user opens a chat about their robotics capstone (`project: robotics-capstone`, tagged
`robotics`). Bookworm's `cicada_recall` runs a LEANN search over the entity index; the media entity
(whose body embeds "reinforcement learning robotic grasping") scores high against the robotics query,
and its one-hop neighbours already include `robotic-grasping` which is also linked to the capstone.
Bookworm surfaces: *"You saved a YouTube video on RL for robotic grasping — relevant to your
capstone."* The link the user forgot resurfaces exactly when it is useful.

---

## 2. New / Modified Files

| Path | Action | Note |
|------|--------|------|
| `api/services/media_ingestor.py` | create | Enrichment (OG + oEmbed), parsers (Netscape HTML, Chrome JSON, Takeout, URL list), dedup, episode+entity writers |
| `api/routers/sources.py` | create | `POST /sources/upload`, `POST /sources/save`, `GET /sources` |
| `api/models/schemas.py` | modify | Add `media` to `EntityType`; add `SourceSaveRequest`, `SourceSaveResponse`, `SourceUploadResponse`, `MediaSourceItem`, `SourceListResponse` |
| `api/main.py` | modify | `from api.routers import ... sources`; `app.include_router(sources.router, tags=["sources"])` |
| `api/pyproject.toml` | modify | Add `"httpx>=0.28"` to `dependencies` (already installed transitively; declare it) |
| `api/services/graph_builder.py` | modify | Emit `media` nodes; colour handled client-side (no logic change beyond node passthrough) |
| `mcp/server.py` | modify | Add `cicada_save_url` tool definition + `handle_save_url` handler |
| `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` | modify | Add `saveURL`, `uploadSourceFile`, `fetchSources` + `MediaSourceItem` Codable |
| `app/CicadaApp/Sources/CicadaApp/Views/Common/UploadOverlay.swift` | modify | Add a tabbed "Conversations / Sources" mode with file-drop + URL-paste |
| `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift` | modify | Add `.media` to Swift `EntityType` enum + colour mapping |

> The existing `memory/episodes/`, `memory/entities/`, Sleep cycle, LEANN indexer, and
> `conversations.py` are **untouched in behaviour** — media episodes flow through them as-is.

---

## 3. Storage Schemas

### 3.1 Media episode (in `memory/episodes/`)

Reuses the exact frontmatter shape `conversations.py::_stage_episodes` and the MCP already write, so
`_get_unprocessed_episodes` / `index_episodes` pick it up with zero changes. `source` is the
discriminator.

```yaml
---
id: ep_2026-06-12_004
timestamp: '2026-06-12T14:03:00Z'
source: youtube            # one of: bookmark | youtube | instagram | url
title: "RL for Robotic Grasping — Two Minute Papers"
processed: false
content_hash: a1b2c3d4e5f6
url: https://www.youtube.com/watch?v=XXXX   # NEW optional field, only on media episodes
media_entity_id: media-rl-for-robotic-grasping  # NEW back-link to the media entity
---
```

Body (the text Sleep extracts entities from — deliberately rich so extraction has signal):

```markdown
# RL for Robotic Grasping — Two Minute Papers

**Source:** youtube
**URL:** https://www.youtube.com/watch?v=XXXX
**Channel:** Two Minute Papers
**Saved:** 2026-06-12

## Description
A walkthrough of recent reinforcement-learning approaches to dexterous robotic
grasping, covering sim-to-real transfer and reward shaping...

## User note
Watch before the capstone methods chapter.
```

`url` and `media_entity_id` are additive optional frontmatter keys — existing episodes that lack them
parse fine (`markdown_parser` just omits absent keys).

### 3.2 Media entity (in `memory/entities/`)

Uses the **standard 11-field entity frontmatter** plus a small additive `media:` block. Existing
readers (`graph_builder`, `leann_indexer.index_entities`, MCP `cicada_recall_detail`) ignore unknown
frontmatter keys, so this is backward-compatible.

```yaml
---
type: media                       # NEW enum value
status: active
confidence: 0.6                   # fixed seed; deliberate save => mid confidence, not 0.3
created: 2026-06-12
last_referenced: 2026-06-12
decay_rate: 0.03                  # slower decay than conversational entities — saves are durable
source_episodes:
  - ep_2026-06-12_004
tags:
  - youtube
  - robotics
related: []                       # filled by Sleep Stage 2 once edges are drawn
version: 1
media:                            # NEW additive sub-block, read by /sources + companion app
  url: https://www.youtube.com/watch?v=XXXX
  media_type: youtube            # bookmark | youtube | instagram | url
  site: youtube.com
  channel: Two Minute Papers     # null for non-video
  thumbnail: https://i.ytimg.com/vi/XXXX/hqdefault.jpg
  saved_at: '2026-06-12T14:03:00Z'
  url_hash: 7f3a9c1e             # sha256(normalized_url)[:12] — dedup key
---

## Summary
Saved YouTube video on reinforcement learning for robotic grasping.

## Description
A walkthrough of recent reinforcement-learning approaches to dexterous robotic grasping...

## Notes
Watch before the capstone methods chapter.
```

Entity `id` (filename stem) = `media-<sanitize_id(title-or-url-slug)>`. The `media-` prefix
namespaces saved items so a "Saved Media" hub can collect them by `id.startswith("media-")` OR
`type == media` (the hub axis should use `type == media`).

### 3.3 Dedup index — `memory/sources/url_index.json`

A single JSON map persisted under a new `memory/sources/` dir, the authoritative dedup store keyed by
normalized-URL hash. Avoids re-scanning every episode/entity on each save.

```json
{
  "7f3a9c1e": { "media_entity_id": "media-rl-for-robotic-grasping",
                "episode_id": "ep_2026-06-12_004",
                "url": "https://www.youtube.com/watch?v=XXXX",
                "saved_at": "2026-06-12T14:03:00Z" }
}
```

`memory/sources/` is created on first save (`mkdir(parents=True, exist_ok=True)`), matching how
`main.py` lifespan already ensures `entities/ nudges/ clarifications/ episodes/`. **Add `"sources"`
to that lifespan subdir tuple** so it exists for the `GET /sources` list endpoint even before a
first save.

---

## 4. Enrichment (`media_ingestor.py`)

### 4.1 URL normalization & hashing

```python
def normalize_url(url: str) -> str:
    # lowercase scheme+host, strip fragment, strip tracking params
    # (utm_*, fbclid, gclid, igshid, si), collapse trailing slash.
    # YouTube: canonicalize to https://www.youtube.com/watch?v=<id>
    #          (handles youtu.be/<id>, /shorts/<id>, &t=, &list=)
def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:12]
```

### 4.2 Metadata fetch (async, graceful offline fallback)

```python
async def enrich(url: str, client: httpx.AsyncClient) -> MediaMeta:
    # MediaMeta: title, description, site, channel, thumbnail, media_type
    # 1. media_type = classify(url): youtube / instagram / bookmark(generic) / url
    # 2. if youtube: GET https://www.youtube.com/oembed?url=<url>&format=json
    #       -> title, author_name (=channel), thumbnail_url. NO API KEY.
    # 3. else: GET url (timeout=8s, follow_redirects=True, max 1.5MB read,
    #          UA="Mozilla/5.0 (CicadaBot)"); parse OG tags with bs4:
    #          og:title|twitter:title|<title>, og:description|meta[name=description],
    #          og:site_name, og:image.
    # 4. instagram public pages 401/login-wall -> caught, fall back to URL-only.
    #    NEVER attempt login. NEVER pass cookies.
    # 5. ANY exception (offline, timeout, 4xx/5xx, parse fail) -> MediaMeta(
    #          title=last_path_segment_or_host, description="", media_type=...)
    #    Enrichment failure is non-fatal: the item is still saved URL-only.
```

- `media_type` classification: host contains `youtube.com`/`youtu.be` → `youtube`;
  `instagram.com` → `instagram`; came from a bookmarks-HTML/JSON upload → `bookmark`; otherwise
  `url`. (A pasted YouTube link is `youtube`, not `url` — classification is host-based, the
  upload-source is only the tiebreaker for generic pages.)
- **No login-required scraping.** Instagram/YouTube transcript fetching, yt-dlp, cookies are out of
  scope. We use only public OG tags and the keyless oEmbed endpoint.

### 4.3 Bookmark/list parsers

```python
def parse_netscape_bookmarks(html: str) -> list[RawItem]:
    # Netscape Bookmark File Format — the Safari/Chrome/Firefox export standard.
    # <DT><A HREF="..." ADD_DATE="unix" TAGS="a,b">Title</A>. Parse with bs4,
    # iterate all <a> with href; RawItem(url, title=a.text, tags=split(TAGS),
    # added=ADD_DATE). Folder <H3> names -> appended as a tag for nested links.

def parse_chrome_bookmarks_json(data: dict) -> list[RawItem]:
    # Chrome "Bookmarks" JSON: recurse data["roots"]["bookmark_bar"]["children"],
    # type=="url" -> RawItem(url, title=name, added=date_added (webkit epoch)).

def parse_youtube_takeout(content: bytes, filename: str) -> list[RawItem]:
    # Google Takeout watch-later/history. Two shapes:
    #   JSON: list of {titleUrl, title, time, subtitles:[{name=channel}]}
    #   CSV : "Video ID" column -> reconstruct watch?v=<id>.
    # RawItem(url, title, channel, added=time).

def parse_url_list(text: str) -> list[RawItem]:
    # .txt: one URL per line (ignore blanks / # comments).
    # .csv: detect a url/link column header, else first column.
    # RawItem(url, title=None) -> enrichment fills the title.
```

`RawItem = {url, title?, tags?, channel?, added?}`. All four parsers feed the same enrich+write path.

**Instagram saved-collection export:** Instagram has **no standard saved-collections export**
(Download-Your-Data gives `saved_posts.html`/`.json` only as a list of post URLs, login-gated content).
So we do **not** special-case an Instagram file format. Instagram links are supported via (a) URL
paste / `cicada_save_url`, and (b) the generic `saved_posts.json`/`.html` if it parses as a URL list
(it does — it is a list of `https://www.instagram.com/p/...` URLs). Those URLs enrich to URL-only
(login wall) and still become `media` nodes. Documented limitation, not a gap.

### 4.4 Writers

```python
async def ingest_one(item: RawItem, memory_path, settings, idx) -> IngestResult:
    # 1. h = url_hash(item.url); if h in idx -> return skipped(existing)
    # 2. meta = await enrich(item.url, client)  (or URL-only on failure)
    # 3. write episode (source=meta.media_type, body from meta+note), get episode_id
    # 4. write media entity (id=media-<slug>, type=media, frontmatter media:{...})
    # 5. idx[h] = {media_entity_id, episode_id, url, saved_at}; return created
```

Episode ID generation reuses the date-sequence logic in `conversations.py::_stage_episodes`
(extract `_next_episode_id(episodes_dir, date)` into a shared helper in `media_ingestor.py` and have
both callers use it — small refactor, prevents the `len(glob)+1` collision bug the MCP currently has).

---

## 5. API (`api/routers/sources.py`)

### 5.1 `POST /sources/save` — single URL (share-sheet / MCP)

Request `SourceSaveRequest`:
```json
{ "url": "https://...", "note": "optional free text", "tags": ["optional"] }
```
Response `SourceSaveResponse`:
```json
{ "status": "created|duplicate",
  "mediaEntityId": "media-...", "episodeId": "ep_...",
  "title": "...", "mediaType": "youtube", "thumbnail": "https://...",
  "message": "Saved 'Title' — will be linked next Sleep cycle" }
```
Enrichment runs inline (one URL, ~1s). Returns the resolved title/thumbnail so the UI/agent can echo
it immediately.

### 5.2 `POST /sources/upload` — file (bookmarks HTML/JSON, Takeout, URL list)

Multipart `file` (same shape as `/conversations/upload`). Routes by extension + sniff:
- `.html` → Netscape bookmarks
- `.json` → Chrome bookmarks if `{"roots":...}` else YouTube Takeout JSON else generic URL-list JSON
- `.csv` → Takeout CSV or generic URL list
- `.txt` → URL list

Response `SourceUploadResponse`:
```json
{ "status": "success", "itemsCreated": 312, "duplicatesSkipped": 188,
  "enrichmentFailed": 14, "source": "Safari Bookmarks",
  "message": "Ingested 312 saved items, enriching in background" }
```

**Batch limit + async enrichment (req f):** the endpoint **parses + dedups synchronously** (fast,
bounded), then **returns immediately** while enrichment + writes happen in a FastAPI
`BackgroundTasks` job. A 500-bookmark upload does not block the request. Concurrency is bounded by an
`asyncio.Semaphore(8)` and one shared `httpx.AsyncClient`. Hard cap `MAX_BATCH = 2000` items per
upload (reject over with HTTP 413). `itemsCreated` in the immediate response is the count *queued*
(post-dedup); the background job updates `url_index.json` as each completes. `GET /sources` reflects
progress.

### 5.3 `GET /sources` — list ingested media

Query params: `media_type` (filter), `limit` (default 200), `offset`. Reads `url_index.json` +
the referenced media entity frontmatter (no full-corpus scan).

Response `SourceListResponse`:
```json
{ "items": [ { "mediaEntityId": "media-...", "url": "...", "title": "...",
               "mediaType": "youtube", "site": "youtube.com",
               "channel": "...", "thumbnail": "...", "savedAt": "...",
               "tags": ["..."], "status": "active",
               "relatedCount": 3 } ],
  "total": 312 }
```
`relatedCount` = `len(related)` from the media entity, so the UI can show which saves the graph has
already connected (the serendipity payoff is visible).

### 5.4 Pydantic models (add to `schemas.py`)

```python
class EntityType(str, Enum):
    ... ; media = "media"        # ADD

class SourceSaveRequest(CamelModel):
    url: str
    note: Optional[str] = None
    tags: list[str] = []

class SourceSaveResponse(CamelModel):
    status: str
    media_entity_id: str
    episode_id: str
    title: str
    media_type: str
    thumbnail: Optional[str] = None
    message: str

class SourceUploadResponse(CamelModel):
    status: str
    items_created: int
    duplicates_skipped: int
    enrichment_failed: int
    source: str
    message: str

class MediaSourceItem(CamelModel):
    media_entity_id: str
    url: str
    title: str
    media_type: str
    site: Optional[str] = None
    channel: Optional[str] = None
    thumbnail: Optional[str] = None
    saved_at: str
    tags: list[str] = []
    status: str
    related_count: int = 0

class SourceListResponse(CamelModel):
    items: list[MediaSourceItem]
    total: int
```

---

## 6. MCP — `cicada_save_url`

Add to the `tools` list in `mcp/server.py::main`:
```json
{ "name": "cicada_save_url",
  "description": "Save a URL (article, YouTube video, bookmark) to Cicada's memory. Fetches the page title/description automatically and creates a graph node so the link can resurface serendipitously in future conversations. Use when the user shares or mentions a link worth remembering.",
  "inputSchema": { "type": "object",
    "properties": {
      "url": {"type": "string", "description": "The URL to save"},
      "note": {"type": "string", "description": "Optional context on why this is being saved"} },
    "required": ["url"] } }
```
Dispatch in `handle_tool`: `elif name == "cicada_save_url": return handle_save_url(arguments.get("url",""), arguments.get("note"))`.

`handle_save_url` does **not import the API**; to stay dependency-light it calls the running backend:
`POST http://127.0.0.1:8000/sources/save` (via stdlib `urllib.request` — no new MCP dep), returns the
echoed title. If the backend is unreachable it falls back to writing a URL-only media episode + entity
directly with the same writer functions (import `media_ingestor` lazily, mirroring how
`_leann_search_entities` lazily imports `api.services`). This keeps save-url working whether or not
the companion app is running.

---

## 7. SwiftUI — Sources tab in `UploadOverlay`

Convert `UploadOverlay` to a two-mode overlay with a segmented `Picker` at the top:
**Conversations** (existing flow, unchanged) | **Sources** (new).

Sources mode contains:
1. A **URL paste field** (`TextField` + "Save" button) → `APIClient.saveURL(url:note:)`. On success
   shows the resolved title + a thumbnail (`AsyncImage`) and toasts "Saved 'Title'".
2. A **file drop / picker** (reuse the existing drop zone) accepting `.html .json .csv .txt` →
   `APIClient.uploadSourceFile(fileURL:)`. The picker's `allowedContentTypes` becomes
   `[.html, .json, .commaSeparatedText, .plainText]` in Sources mode.

`APIClient.swift` additions (mirror existing `post`/`uploadFile` helpers):
```swift
struct MediaSourceItem: Codable, Identifiable {
    var id: String { mediaEntityId }
    let mediaEntityId: String; let url: String; let title: String
    let mediaType: String; let site: String?; let channel: String?
    let thumbnail: String?; let savedAt: String; let tags: [String]
    let status: String; let relatedCount: Int
}
func saveURL(_ url: String, note: String?) async throws -> SourceSaveResponse
    { try await post("/sources/save", body: ["url": url, "note": note as Any]) }
func uploadSourceFile(fileURL: URL) async throws -> SourceUploadResponse  // copy uploadFile, point at /sources/upload
func fetchSources(mediaType: String? = nil) async throws -> SourceListResponse
```

`Entity.swift`: add `case media = "media"` to `EntityType`, colour `Color(hex: 0xEC4899)` (pink),
SF-symbol `bookmark.fill` for list rows. Because the SwiftUI filter popover enumerates
`EntityType.allCases`, the new type appears in graph filters automatically.

> A dedicated "Saved Media" library screen is **out of scope for this axis** (it overlaps the
> graph/hub work). `GET /sources` + `fetchSources` are delivered so the hub/graph axis or a later
> screen can consume them. The overlay's URL-paste + file-drop are the minimum frictionless capture
> surface this axis owns.

---

## 8. Implementation Steps (ordered, ~2–3 days)

1. **schemas.py** — add `media` to `EntityType`; add the five new Pydantic models (§5.4).
2. **media_ingestor.py** — write `normalize_url`, `url_hash`, `enrich` (oEmbed + OG + offline
   fallback), the four parsers, `_next_episode_id` helper, `write_media_episode`,
   `write_media_entity`, `load_url_index`/`save_url_index`, `ingest_one`, and the batched
   `ingest_batch(items, ...)` with `Semaphore(8)`.
3. **sources.py** — `POST /sources/save` (inline), `POST /sources/upload` (parse+dedup sync,
   `BackgroundTasks` enrich), `GET /sources`. Wire `MAX_BATCH` 413 guard.
4. **main.py** — import + `include_router(sources.router)`; add `"sources"` to the lifespan subdir
   tuple.
5. **pyproject.toml** — declare `httpx>=0.28`; `uv sync` (already resolved, just pins it).
6. **graph_builder.py** — confirm `media` entities flow into `GraphNode` (they do via the generic
   glob; only ensure no type allowlist filters them out — there is none today).
7. **mcp/server.py** — add `cicada_save_url` tool def + `handle_save_url` (backend POST with
   direct-write fallback).
8. **APIClient.swift** — add `MediaSourceItem`, `saveURL`, `uploadSourceFile`, `fetchSources`.
9. **UploadOverlay.swift** — add the Conversations/Sources `Picker`, URL paste field, and
   Sources-mode file-drop wiring.
10. **Entity.swift** — add `.media` case, colour, icon.
11. **Verify:** `api/.venv/bin/python -c "import api.routers.sources, api.services.media_ingestor"`;
    `uvicorn` up → `curl -X POST /sources/save -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'`
    returns a title; upload a tiny Netscape `.html`; `GET /sources` lists it; run a Sleep cycle on the
    seeded episode and confirm the media entity gains `related` edges. `swift build` in `app/CicadaApp`.

---

## 9. Backward Compatibility & Safety

- **No data loss.** Purely additive: a new entity type, additive frontmatter keys, new dirs/files.
  The 1882 existing entities, 39 nudges, 33 clarifications are untouched. No migration script needed.
- **New enum value risk:** any code doing exhaustive `EntityType` matching must get a `media` arm.
  Python uses `.get(...)` defaults (safe). Swift `EntityType` is `String`-backed with a colour `switch`
  — **the `switch` must add a `.media` case or it won't compile**, which is the desired forcing
  function (step 10).
- **Offline-safe:** every network call is wrapped; failure degrades to URL-only, never throws to the
  caller. The system is usable with no internet (titles fall back to URL slugs).
- **Privacy:** no login, no cookies, no credential entry, no login-walled scraping. Only public OG
  tags + keyless oEmbed. Instagram private content is never fetched.
- **Idempotent dedup:** `url_index.json` is the single source of truth; re-uploading the same
  bookmarks file is a no-op (all `duplicatesSkipped`).

---

## 10. Cross-Axis Contracts (depends on / provides)

**Provides to other axes:**
- New `media` entity type + pink colour `#EC4899` — the **graph-viz axis** must add it to the d3
  colour map and legend; the **hub axis** can build a "Saved Media" hub by grouping `type == media`.
- Rich media-episode bodies — the **richer-entity-pages axis** benefits (more extraction signal).
- `GET /sources` — available for a future Saved Media library screen.

**Depends on:**
- Episode frontmatter schema + `_get_unprocessed_episodes` (Sleep axis) — assumed stable; media
  episodes conform exactly.
- LEANN `index_entities` embedding name+body (storage axis) — media entity bodies are written to be
  embedding-rich so semantic recall works (the serendipity mechanism).
- If the **richer-entity-pages axis** changes the entity body section template (`## Summary`,
  `## Description`, `## Notes`), media entities should adopt the same section names — coordinate so
  `write_media_entity` emits the agreed sections.
- If the **unified-inbox axis** wants a "we connected your saved video to project X" notification,
  that would be a new inbox item type it owns; this axis only needs to ensure the media entity's
  `related` edges are queryable (they are, via standard frontmatter).
