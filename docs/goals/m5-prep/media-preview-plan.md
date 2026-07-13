# G11 — Rich media preview inside the app (plan)

Goal: preview saved media (images, videos, website links) INSIDE the Cicada app instead of
only opening URLs externally. Render in the media entity's **EntityDetailCard** and in the
**Feed** (tap a row → preview), plus extend transclusion so an image reference renders inline.

This is an AUDIT + PLAN doc. No code was changed.

---

## 1. Audit findings (ground truth)

### 1.1 `media:` frontmatter shape on disk

There are **no media entities on disk yet** (`memory/entities/` has 0 files with `type: media`;
`memory/sources/url_index.json` is absent). The authoritative shape is therefore read from the
writer, `api/services/media_ingestor.py::write_media_entity` (lines ~660–694). Every media entity's
frontmatter is the standard entity schema PLUS a nested `media:` block:

```yaml
---
name: <title>
type: media
status: active
confidence: 0.7
created: 2026-06-18
last_referenced: 2026-06-18
decay_rate: 0.03
source_episodes: [ep_2026-06-18_001]
tags: [youtube, ...]        # sorted(set([media_type] + item.tags))
related: []
version: 1
media:
  url: https://www.youtube.com/watch?v=...   # original saved URL
  media_type: youtube                         # bookmark | youtube | instagram | url
  site: youtube.com                           # host (www. stripped), may be null
  channel: <author/channel>                   # youtube author_name, else null
  thumbnail: https://i.ytimg.com/...          # og:image / oEmbed thumbnail, may be null
  saved_at: 2026-06-18T..Z                     # ISO8601
  url_hash: <12-hex>                           # sha256(normalize_url(url))[:12]
---
## Summary
Saved <media_type> — <title>.

## Description            # present only when enrichment found a description
<og:description text>

## Notes                  # present only when the user attached a note
<note>
```

`media_type` ∈ `{bookmark, youtube, instagram, url}` (see `_classify`). Instagram is URL-only by
design (login-walled, never scraped) → `thumbnail`/`description` typically null. YouTube uses the
keyless oEmbed endpoint so `thumbnail` + `channel` are usually populated. Generic URLs/bookmarks
get Open-Graph enrichment (`og:title`/`og:description`/`og:image`/`og:site_name`), best-effort.

### 1.2 Does `EntityResponse` / Swift `Entity` expose media fields? — NO

- Backend `EntityResponse` (`api/models/schemas.py:100`) and the handler
  `api/routers/entities.py::get_entity` (lines 40–56) read the standard frontmatter keys only.
  **The nested `media:` block is dropped** — it is never read into the response.
- Swift `Entity` (`Models/Entity.swift:246`) mirrors that — no media field. `EntityType` already
  has `.media` (icon `photo.on.rectangle.angled`) and `CicadaTheme.mediaPink` (0xF65BA6) exist.
- `MediaFeedItem` (`Services/APIClient.swift:117`) — the `/sources` row model — DOES carry
  `url`, `mediaType`, `site`, `channel`, `thumbnail`, `title` (but not `description`).

So the Feed already has enough to render image/video/card previews; the **EntityDetailCard does
not** — it needs the backend to surface `media:` on `EntityResponse`.

### 1.3 How EntityDetailCard renders today

`Views/Graph/EntityDetailCard.swift`. Header (type/status badges, name, confidence bar) → tab
switcher (Content/History/Perspectives/Timeline) → `ScrollView`. The **Content** tab
(`contentTab`, line 172) shows a Rendered/Source toggle; Rendered uses
`TranscludingMarkdownView(body: entity.markdownContent)` (line 346). There is already a precedent
for a type-specific section: `if entity.type == .location { locationSection }` (line 204) loaded
lazily via `.task(id: entity.id)`. A `media` section would slot in the exact same way.

### 1.4 How a Feed row tap is handled today

`Views/Feed/FeedView.swift::FeedRow` (line 171). The whole row is a `Button` whose action is
`NSWorkspace.shared.open(url)` — it **only opens the URL externally** (lines 176–179). The
thumbnail is an `AsyncImage` at 44×44 (line 224). There is no in-app preview path yet.

### 1.5 How `TranscludingMarkdownView` tokenizes `![[…]]`

`Views/Common/TranscludingMarkdownView.swift`. `segments` (line 54) runs ONE regex,
`!\[\[(.+?)\]\]`, splitting the body into `.text(AttributedString)` (residual text → wikilink
highlighter) and `.embed(ref:)`. Each `.embed` renders a `TransclusionCard` that calls
`GET /transclude` and shows a summary/claim card. It does **not** handle standard markdown image
syntax `![alt](url)`, and an embed ref pointing at a media entity is resolved as a text summary,
not an image.

### 1.6 Existing WKWebView pattern to reuse

`Views/Graph/GraphView.swift` — `NSViewRepresentable` wrapping a `ClickableWebView: WKWebView`
(overrides `acceptsFirstMouse`). This is the template for the new `WebView`/`MediaWebView` wrapper.

---

## 2. Backend change — surface `media:` on `EntityResponse`

1. `api/models/schemas.py`: add a `MediaBlock(CamelModel)` —
   `url, media_type, site?, channel?, thumbnail?, saved_at?, url_hash?` (all optional/defaulted,
   matches the writer's keys). Add `media: Optional[MediaBlock] = None` to `EntityResponse`.
2. `api/routers/entities.py::get_entity`: after parsing frontmatter, if `fm.get("type") == "media"`
   and `fm.get("media")` is a dict, build and attach `MediaBlock`; else `None`. Inert for every
   non-media entity (stays `None`).
3. Tests (`api/tests/test_entities*.py` or `test_sources.py`): a media entity written to a tmp
   memory dir → `GET /entities/{id}` returns the `media` block with the right url/media_type;
   a non-media entity returns `media: null`. Keep hermetic — write the fixture file directly,
   no ingestion/network. Must keep all 233 green.

Swift side: add a `MediaBlock: Codable` struct and `var media: MediaBlock? = nil` to `Entity`
(decodeIfPresent, back-compat). Add `media` to `Entity.CodingKeys`.

---

## 3. Frontend components (new, under `Views/Common/`)

### 3.1 `WebView` (NSViewRepresentable, reusable)
Thin wrapper over `ClickableWebView` that loads a single `URL` (or a request). **Security: the
caller only ever passes the media entity's OWN stored `media.url`** (for sites) or the derived
YouTube embed URL — never arbitrary request input. No `userContentController` message handlers
needed. Mirrors `GraphView`'s `makeNSView`/`updateNSView` shape.

### 3.2 `ImageLightbox`
- `ImageThumbnail(url:)` — small inline `AsyncImage` (rounded, fixed frame) that is tappable.
- Tap → full-screen-ish overlay (`.sheet` or a `ZStack` overlay with dimmed background) showing the
  image at large size with pinch/scroll zoom and an ✕ to dismiss. Reused by the media card AND by
  transcluded images (§3.5).

### 3.3 `MediaPreview` (dispatches on `media_type`)
Given a `MediaBlock` (or a `MediaFeedItem`), renders the right preview:
- **image** (`media_type == "url"`/`"bookmark"` whose URL or thumbnail is an image, OR any item
  whose URL ends in an image extension): inline `ImageThumbnail` → `ImageLightbox`.
- **youtube**: thumbnail + a play affordance overlay. Tap → embedded player. **(see §4)**
- **instagram**: thumbnail (often nil → mediaPink placeholder) + an "Open in Instagram" button
  (external) — login-walled, no in-app embed.
- **url / bookmark (website)**: an Open-Graph **preview card** (thumbnail + title + site +
  description, all from the media block) PLUS a "Preview site" button that pushes a `.sheet`
  containing `WebView(url: media.url)`. Always keep an "Open externally" affordance too.

### 3.4 Where each renders
- **EntityDetailCard**: in `contentTab`, add `if entity.type == .media, let media = entity.media`
  → a `MediaPreview(media:)` section above the description/metadata (same lazy/section pattern as
  `locationSection`). The description body (`## Summary`/`## Description`) keeps rendering below.
- **Feed**: change `FeedRow` so the tap no longer goes straight to `NSWorkspace.open`. Instead tap
  opens an in-app preview — a `.sheet`/overlay hosting `MediaPreview(item:)` (image lightbox,
  youtube player, or site card+WebView), with an explicit "Open externally" button retained inside
  the preview. (Implementation note: `MediaFeedItem` lacks `description`; the site-card description
  line is simply omitted for Feed, or we lazily `fetchEntity(media_entity_id)` to enrich on open.)

### 3.5 Transclusion — render image references inline
Extend `TranscludingMarkdownView.segments` to ALSO recognize markdown image syntax `![alt](url)`
(add a second regex / a combined tokenizer that emits a new `.image(url:alt:)` segment), and treat
an `![[…]]` ref that resolves to an image/media entity as an image embed. Rendering:
- `.image(url:)` → `ImageThumbnail`/`ImageLightbox` (reuse §3.2).
- For `![[media-…]]`: `TransclusionCard` checks the resolved payload; if it's a media entity with a
  `thumbnail`/image url, render the image (lightbox) instead of the text summary. (May need the
  `/transclude` payload to carry the media url/thumbnail — confirm in M5; if absent, fall back to
  the current text card, so this degrades gracefully.)

---

## 4. Video approach — CHOSEN: embedded WKWebView player (YouTube embed URL)

Render a thumbnail with a play affordance; on tap, present a `.sheet` containing
`WebView` loaded with the YouTube **embed** URL `https://www.youtube.com/embed/<id>` (derive `<id>`
from `media.url` — the backend already canonicalizes YouTube to `watch?v=<id>`, so a tiny Swift
helper extracts `v`). Rationale: keeps the preview in-app (matches the G11 ask of "preview INSIDE
the app"), the embed URL is the entity's own stored/derived URL (security rule satisfied — never
arbitrary input), and `WebView` is already needed for site previews so there's no extra
infrastructure. Instagram stays external (login-walled). A global "Open externally" affordance is
always available as the robust fallback if an embed is blocked.

---

## 5. Risks / notes
- Hermetic tests: the only backend test addition writes a fixture media `.md` and asserts the
  response shape — no network, no ingestion. App: `swift build` must stay exit 0.
- Image detection for generic URLs is heuristic (extension sniff + presence of `thumbnail`); when
  unsure, fall back to the site preview card rather than a broken image.
- `MediaFeedItem` has no `description`/`url_hash`; the Feed preview either omits the description or
  enriches on open via `fetchEntity`. Decide in M5 (cheap to fetch on tap).
