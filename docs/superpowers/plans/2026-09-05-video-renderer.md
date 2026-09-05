# In-app video (Track V) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A saved video plays where the user already is. Today exactly one thing plays — a YouTube link whose id parses — inside a `WKWebView`. After this plan: YouTube (including `/live/` and playlists), Vimeo, TikTok and Loom play in their own embed players; direct `.mp4/.m4v/.mov/.webm/.m3u8` and `file://` clips play in a real AVKit player with transport controls and space-to-play; an unreadable local file says exactly what is wrong and offers Reveal in Finder; and the Feed row, the Feed preview sheet, the entity Content tab and the entity hero all get it at once, because all four go through the same two components.

**Architecture:** One classification table, written twice and pinned by one fixture — `api/services/video_urls.py` (pure) and `Views/Common/VideoRef.swift` (pure), both read-only over a URL, zero network on either side. The app **derives the provider at read time from `media.url`** (R-V1), so every Vimeo/TikTok/Loom/`.mp4` item already on a bank starts playing the moment the app updates, with no bank rewrite and no `url_index.json` migration. The backend slice is metadata only: `_classify → "video"` for direct files (which `link_enrichment._excluded_media` already honours, for free), one shared `_enrich_oembed` for Vimeo/TikTok/Loom modelled on `_enrich_youtube`, a content-type guard on `_enrich_opengraph` so a saved `.mp4` is never downloaded and HTML-parsed, and two additive optional keys (`media.provider`, `media.duration_s`).

**Tech Stack:** Python 3 / FastAPI / Pydantic / httpx (`api/`), SwiftUI + AVKit + WebKit + XCTest (`app/CicadaApp`, macOS 14 floor — `Package.swift:6`), markdown + git bank.

**Spec:** `docs/superpowers/specs/2026-09-05-round2-study-room-marks-video-design.md` § Track V, rulings **R-V1 … R-V8** (binding). Survey: the Phase-1 design report (anchors re-verified against this worktree below). Backlog rows **G11** (the preview half — this is its video paragraph), **G23** / **G25** (✅ already; this generalizes what they shipped), **G22** (transcripts as entity body — **this plan moves it not at all and must not close it**). Standing rails: the ToS rail in `CLAUDE.md` § "Reaching the outside world", the ETag ship-together rule, the privacy rule for `docs/goals/`.

---

## What the code actually does today (verified against `feat/video-renderer` @ `53885a1`)

**App — the whole player surface is three files.**

- `Views/Common/MediaPreview.swift:22-69` — `MediaPreviewModel` (`url, mediaType, title, site, channel, thumbnail, description`), built from a `MediaBlock` (`:31-39`) or a `MediaFeedItem` (`:41-49`). `enum Kind { image, youtube, instagram, website }` at `:53`; `var kind` at `:55-65` switches on **`mediaType.lowercased()` first** — `"youtube"`, `"instagram"`, else image-extension-or-website. That is why a legacy Vimeo page whose `media_type` is the generic `bookmark` (what the browser-sync path stamps) can never play.
- `MediaPreview.swift:73-120` — `MediaURLHelpers`: `isImageURL` (`:75-79`), `youtubeEmbedURL` (`:84-89`, appends `autoplay=1`), `youtubeHeroEmbedURL` (`:96-99`, deliberately no autoplay — the hero renders on every visit), `youtubeID` (`:101-119`, matches `youtu.be/<id>`, `?v=`, and path segments `embed`/`shorts` only — **not `/live/`, not `playlist?list=`**).
- `MediaPreview.swift:124-142` — the view: a `switch model.kind` over four branches, plus `.sheet($showSitePreview)` and `.sheet($showVideoPlayer)`. `youtubePreview` (`:157-201`) is thumbnail + `play.circle.fill` badge → opens `videoPlayerSheet` (`:351-361`) with the autoplay embed. `websitePreview` (`:247-303`) is the OG card + a **"Preview site"** button (`:293-299`) that loads the saved URL itself — which is how a bare `.mp4` plays *by accident today, mislabelled*. `openExternallyButton` (`:316-326`) is on the youtube and website branches.
- `Views/Common/WebView.swift:14-34` — `WKWebView` with `config.mediaTypesRequiringUserActionForPlayback = []` (`:20`) so inline playback works, and `webView.load(URLRequest(url:))` at `:23`. **WebKit refuses `file://` loaded this way** — it needs `loadFileURL(_:allowingReadAccessTo:)`. `updateNSView` (`:27-33`) reloads only when the URL actually changed — the existing guard against restarting a video on a SwiftUI re-render. `WebPreviewSheet` (`:41-89`) is title + "Open externally" + close, `frame(width: 900, height: 620)` at `:86`.
- `Views/Common/HeroPreview.swift` — `maxHeight = 220` (`:30`); `hasPreviewableAsset(for:)` (`:39-51`) switches over the same four kinds and is what `EntityDetailCard.swift:841-843` gates the hero slot on; `content(for:)` (`:61-86`) dispatches; `YouTubeHero` (`:91-144`, `private`) renders `WebView(url: youtubeHeroEmbedURL)` inline, else a thumbnail-with-play-badge that opens externally (`:111-143`).

**App — the three surfaces that reach it.**

1. `Views/Feed/FeedView.swift:258` `FeedRow` (deliberately **internal, not private**, since G124 — the Sources page's `ChannelSourceView` renders the same row). Tap sets `showPreview = true` (`:269`) → `.sheet` at `:314` → `FeedItemPreviewSheet` (`:367`, `private`) → `MediaPreview(model: previewModel)` (`:395`) in `frame(width: 480, height: 520)` (`:399`). The row's `thumbnail` (`:319-338`) is a 44×44 `AsyncImage` with **no indication that an item is a video**.
2. `Views/Graph/EntityDetailCard.swift:332-340` — the Content tab renders `MediaPreview` above the body for `entity.type == .media`.
3. `Views/Graph/EntityDetailCard.swift:834-858` — `renderedMarkdownView` gates on `HeroPreview.hasPreviewableAsset(for:)` (`:841`) and renders `HeroPreview`.

**App — models.** `Models/Entity.swift:544-594` `MediaBlock` (`url, mediaType, site, channel, thumbnail, savedAt, urlHash`, every field decode-tolerant, memberwise `init` at `:566-578`, `init(from:)` at `:580-589`, `CodingKeys` at `:562`); `Entity.parseMediaFrontmatter` (`:699-753`) is the raw-frontmatter fallback that reads the same keys out of `rawMarkdown`. `Services/APIClient.swift:197-299` `MediaFeedItem` — `CodingKeys` at `:270-276` and a hand-written `init(from:)` at `:278-298`; **no memberwise init is synthesised**, so every test builds one by decoding JSON (`FeedIdentityTests.swift:5-13`, `SourcesPageTests.swift:63-67`).

**App — the AVKit precedent.** `Views/Capture/Sheets/WalkthroughPanel.swift:206-230` `LoopingVideo` — an `NSViewRepresentable` over `AVPlayerView` with `controlsStyle = .none`, muted, looping, the `AVPlayerLooper` owned by the Coordinator. It is the only AVFoundation user in the app today.

**App — the lint pattern to copy.** `Tests/CicadaAppTests/FontLiteralLintTests.swift:14-27` — a `#filePath` walk up to the package root, `FileManager.enumerator` over `Sources/CicadaApp`, and `XCTAssertFalse(all.isEmpty, "…the lint would pass vacuously")`. That guard is the non-vacuity rail R-V8 asks for.

**Backend.** `api/services/media_ingestor.py`: `_TIMEOUT = 5.0` (`:34`), `_MAX_READ = 1_500_000` (`:35`), `MediaMeta` (`:93-100`, `media_type` documented as `bookmark | youtube | instagram | url`), `_youtube_video_id` (`:117-130`, `shorts|embed|v` only), `normalize_url` (`:133-171`, canonicalises any resolvable YouTube id to `watch?v=<id>` — **this is what makes `url_hash` change if `_youtube_video_id` learns `/live/`**), `_classify` (`:178-188`, `youtube | instagram | linkedin | bookmark | url`), `enrich` (`:213-236`, takes an **injected `client`**, `except Exception` → URL-only fallback at `:234-236`), `_enrich_youtube` (`:239-251`, keyless oEmbed, reads `title`/`author_name`/`thumbnail_url` — never `html`), `_enrich_opengraph` (`:254-292`, `client.get` → `resp.text[:_MAX_READ]` → BeautifulSoup, **no content-type guard**), `write_media_entity` (`:1469-1529`; `tag_set = set([meta.media_type] + …)` at `:1478`; the nested `frontmatter["media"]` at `:1517-1527`), `ingest_one` (`:1583-1643`; the `url_index.json` entry at `:1618-1634`). `parse_upload` routes a TikTok export at `:1072-1091` with `from_bookmark_file=False`, so **every TikTok export item is `media_type: url` and enriches through `_enrich_opengraph`, landing on TikTok's consent wall**.

**Backend — the hook that already exists.** `api/services/link_enrichment.py:194` reads `if mtype in ("youtube", "video") …` — a `video` media type is already excluded from the nightly enrichment fetch and **nothing in the codebase produces it** (`grep -rn '"video"' api --include='*.py'` returns that line alone). `default_fetch` (`:559-610`) *does* guard content type (`:588-590`, `failed:content_type`); the two fetch paths disagree.

**Backend — wire shapes.** `api/models/schemas.py:383-401` `EntityMedia` (built only at `api/routers/entities.py:163-195` `_build_media_block`), `:1518-1555` `MediaSourceItem` (built at `api/routers/sources.py:547-568`; `media_type` comes from the **`url_index.json` entry**, while `site`/`channel` are read back from the page's `media:` frontmatter block at `:539-544`). `CamelModel` (`schemas.py:8-13`) aliases `duration_s → durationS`, `provider → provider`.

---

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/video-renderer`, based on `dev` @ `53885a1`). Every shell command is `cd <worktree>/ && <cmd>` with absolute paths (zoxide hijacks relative `cd`; ignore its stderr warning). Never an unquoted `--include=*.ext` (zsh globbing breaks it) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library` or `~/.claude/projects`. Every fixture URL in this plan is synthetic: `example.com`, `file:///Users/example/...`, ids like `vid00000001`.
- Python: `api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full suite `api/tests` must report **0 failures** (2119 passed on 2026-09-05). `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is order-dependent and pre-existing — if it is the ONLY red, re-run it alone and report both results.
- Swift: `cd app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report **0 failures** (SourceKit diagnostics naming OTHER worktrees are noise). NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the end.
- Never `git add -A`; stage named files. Never commit `memory/`, `logs/`, `.claude/`, `api/.venv`, or `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin/PR comments.
- **No network in any test, on either side.** The Python oEmbed tests drive `enrich`'s injected `client` with a fake; the Swift tests never leave the process. **The app never fetches oEmbed** — it derives an embed URL from an id it parsed itself.
- **The ToS rail (R-V4) is not negotiable.** Load only a provider's own player URL; read oEmbed *fields* only, never the `html` blob; never resolve an underlying stream (no `yt-dlp`, no `googlevideo.com`, no `.m3u8` lifted out of a page); never send cookies or auth; never retry a 401/403/407/451 with different headers. **A direct file the app plays is one the user saved as a direct URL — never one Cicada derived.**
- **ETag ship-together:** every new backend field is additive+optional and no ETag *input* changes (`/sources` ETags over `sources`+`episodes`+`entities` via `sync_service.etag_for` — `sources.py:494` — which is unchanged here). Nothing in `VersionVector.swift` moves. A warm client is not stranded on a `304`, because the two new fields only ever appear on a page written *after* this change, and writing that page moves the `entities` component the ETag is computed from. If a task finds otherwise, stop and say so. Say it plainly in the PR body too.
- **Portability / privacy:** no owner name, no author-machine path in shipped code, fixtures or docs; no real saved URL, episode title or bank content in `docs/goals/`, a commit message or the PR body.
- **Decode tolerance:** every new Swift field is optional-with-default and an older backend payload must still decode — tested, not asserted.
- **Fonts:** every new `Text`/`Image` uses `CicadaTheme.font(size:weight:design:)`; a literal `.system(size:)` fails `FontLiteralLintTests`.
- **Do not touch** `Views/Sleep/*`, `Views/Sources/*`, `OriginIconography`, `LogoImage`, `OriginMark` (other tracks). Track P touches `FeedViewModel` filtering and `api/routers/sources.py`'s **list filter**; this plan's only `sources.py` change is the two `MediaSourceItem` field reads inside the existing item build (`:539-567`) — keep it there and the two tracks cannot conflict.
- Docstrings explain WHY, citing the ruling or G-row that motivated the rule. Match the density of the files being touched.
- Line numbers are from `53885a1` and drift as tasks land — read the cited code before editing.

---

## Rulings (binding for this plan)

- **R1 — one fixture, two suites, one commit.** `api/tests/fixtures/video_urls.json` is the classification contract. `api/services/video_urls.py` and `Views/Common/VideoRef.swift` are two implementations of it and land together in Task 1, because a table that exists on one side only is exactly the drift R-V8 exists to prevent. Both test files read the file off disk (`#filePath` walk on the Swift side, `Path(__file__)` on the Python side), each with a non-vacuous guard. **Adding a provider means editing the fixture; the other suite then fails until it is taught too.**
- **R2 — `resolve` is pure, total and never guesses.** No network, no I/O, no exceptions. `""`, `"not a url"`, `"http://"`, a URL with no host, a 10 KB URL, `javascript:alert(1)//a.mp4`, `file://` with no path → `None`. Only the schemes `http`, `https`, `file` are ever classified — a video extension under any other scheme is not a video.
- **R3 — direct-file detection is by path extension only**, over `{mp4, m4v, mov, webm, m3u8}`, case-insensitively, reading the **path** and ignoring the query (`…/clip.mp4?token=abc` is a file; `…/watch?x=.mp4` is not).
- **R4 — a shortlink that hides its id is `external`, never resolved by a fetch.** `vm.tiktok.com/<slug>` carries no video id; deriving one needs a redirect round-trip, and read-time classification does no network (R-V1). It classifies as `kind: external` and opens externally.
- **R5 — a provider is in the table only when a URL shape is unambiguously a video.** `twitch.tv/videos/<id>` and `clips.twitch.tv/<slug>` are (they stay `external` — Twitch's player validates `parent` against the real embedding origin and a `WKWebView` top-level document has none; synthesising one is circumvention, R-V3). **X is not in the table at all**: `x.com/<user>/status/<id>` is *any* post, so calling every status a video would be a lie — an X link stays a website card, and the fixture records that with an explicit `null` row. **Instagram is not in the table either**: it never plays in-app (login-walled) and `MediaPreviewModel` already owns it by host.
- **R6 — `external` gets no new UI case.** `MediaPreviewModel.Kind` gains exactly two cases, `.embedVideo(VideoRef)` and `.fileVideo(VideoRef)`. An `external` ref falls through to the existing `.website` / `.instagram` branches — there is nothing new to offer a video we have decided not to play, and a third case would be chrome around a non-decision. The play badge (R14) is likewise for playable refs only. **This narrows the spec's R-V5 wording ("a play badge for any video ref") on purpose and on the record:** a badge on a Twitch link or a `vm.tiktok.com` shortlink would promise playback the tap cannot deliver, which is the opposite of what the badge is for.
- **R7 — `mediaType` becomes a hint, never the key (R-V1).** `MediaPreviewModel.kind` consults `VideoRef.resolve(url)` first, then the `instagram.com` host, then `mediaType == "instagram"`, and only then the image extension (the order the Step-2 code below actually implements). A `media_type: youtube` page whose URL yields no id (a channel page, a search) correctly renders as a website card — "Preview site" is the honest label for a page that is not a video.
- **R8 — `AVPlaybackController.swift` is the only new file that imports AVFoundation (R-V6)**, and a source lint proves it: no file under `Sources/CicadaApp` other than `Views/Common/AVPlaybackController.swift` and the pre-existing `Views/Capture/Sheets/WalkthroughPanel.swift` may contain `import AVKit` / `import AVFoundation`. Same `#filePath` walk and non-vacuity guard as `FontLiteralLintTests`. Codec questions ("does this file decode?") are a **stated manual check**, not a mocked green.
- **R9 — an unreadable local file shows the fix, never a black rectangle.** `FileManager.default.isReadableFile(atPath:)` is checked before any controller is constructed; false → a card naming the path, "Reveal in Finder" (`NSWorkspace.shared.activateFileViewerSelecting`) and "Open externally". A local file's "external" is Finder, not a browser. **Known limit, disclosed in the docstring not as a TODO:** the app is unsandboxed today; if it is ever sandboxed, a `file://` outside the container needs a security-scoped bookmark.
- **R10 — space toggles play for `.fileVideo` only (R-V5).** `.focusable()` + `.onKeyPress(.space)` returning `.handled`, scoped to the player container — never a global `.keyboardShortcut(" ")`, which would eat the Feed's search field (`FeedView.swift:138-146`). Inside a `WKWebView` the key belongs to the provider's player and cannot be intercepted without a JS bridge, which `WebView` deliberately does not have (`WebView.swift:10-13`).
- **R11 — autoplay only where it is the provider's own documented player param and we verified it.** YouTube `?autoplay=1` (already shipped, `MediaPreview.swift:88`) and Vimeo `player.vimeo.com/video/<id>?autoplay=1`. TikTok and Loom get their plain embed URL and the user presses play. The **hero never autoplays**, for any provider — the deliberate rule at `MediaPreview.swift:92-97` survives generalization.
- **R12 — `_enrich_youtube` is untouched.** Its endpoint and field mapping are already correct, and churning it would break every existing fake for no gain. `_enrich_oembed(provider, url, client, fallback)` covers **vimeo, tiktok, loom** only. It reads `title` / `author_name` / `thumbnail_url` / `duration` and **never the `html` blob** — the player URL is derived from the id ourselves, which is what the shipped YouTube path already does. This is deliberately **stricter than spec R-V4**, which also permits "the exact iframe src its oEmbed returns": parsing a provider's returned markup to lift a src would be the first time this app read HTML it did not assemble, and the id-derived URL makes it unnecessary. 4 s timeout and a 512 KB cap enforced by slicing `resp.text` and refusing an over-cap body (the rail says 4 s / ≤512 KB; `_TIMEOUT = 5.0` is the older, looser number and is **not** inherited by the new endpoints).
- **R13 — the OG content-type guard skips only on a header that says non-text.** A response carrying no `content-type` proceeds, exactly as today. A guard that fired on a header's *absence* would turn working fetches into fallbacks and would be a silent regression across every existing test.
- **R14 — `_classify` order and the one new `media_type` (R-V2).** youtube → instagram → linkedin → **direct/local file → `"video"`** → bookmark → url. `video` is only ever `kind == file`. A Vimeo/TikTok/Loom URL keeps `url`/`bookmark` and carries `media.provider` instead: a new `media_type` value lands in the page's **tags** (`media_ingestor.py:1478`) and in `/sources`' wire shape, so each value costs. `video` earns its place because `link_enrichment._excluded_media` already accepts it (`link_enrichment.py:194`) — classifying a direct file as `video` stops the nightly enrichment fetching a binary with **no edit to that module**.
- **R15 — `url_index.json` gains no new keys.** `provider` and `duration_s` are read from the page's `media:` block, exactly where `site` and `channel` already come from (`sources.py:539-545`). Writing them into the index too would create a second thing to migrate and a second thing to disagree — the split-brain class this repo already knows. `write_media_entity` writes each key **only when it has a value**, so a plain bookmark's frontmatter is byte-identical to today.
- **R16 — the client decodes before the backend produces.** `MediaBlock.provider/durationS` and `MediaFeedItem.provider/durationS` land in Task 4 with an absence test; Task 5 makes the backend emit them. An optional field must decode as absent, and that is the test — the same discipline every additive field in this repo has shipped under.
- **R17 — duration is shown only when a provider gave one.** No estimate, no computed guess: absent means absent and nothing renders (the same rule the Sleep history's `—` duration follows, G125 R5).
- **R18 — `normalize_url` is not touched (R-V7).** Teaching `_youtube_video_id` about `/live/<id>` would change `url_hash` for those URLs, so an already-ingested item would re-import as a *new* entity and its `url_index.json` entry would orphan. That is a dedup-index migration, not a one-line fix. The **player** is fixed at read time instead (R-V1), and the normaliser change is queued as a named follow-up in the G11 row.
- **R19 — G22 stays open.** This is the *preview* half of G11. Transcripts/captions as the entity body — the half that answers "which robotics videos have I saved" — is untouched, and the PR body says so.

---

## File map

| File | Responsibility |
|---|---|
| `api/tests/fixtures/video_urls.json` (new) | The classification contract read by both suites (R1) |
| `api/services/video_urls.py` (new) | `VideoRef`, `resolve(url)`, `is_direct_file(url)` — pure |
| `api/tests/test_video_urls.py` (new) | Fixture table + totality/garbage cases |
| `app/…/Views/Common/VideoRef.swift` (new) | Swift twin: `VideoRef.resolve`, `Provider`, `Kind`, `autoplayURL`, `durationLabel` |
| `app/…/Tests/CicadaAppTests/VideoRefTests.swift` (new) | Same fixture, `#filePath` walk, non-vacuous guard |
| `app/…/Views/Common/AVPlaybackController.swift` (new) | The ONLY new AVFoundation importer (R8) |
| `app/…/Views/Common/VideoPlayerView.swift` (new) | `VideoPlaybackController` protocol, `VideoPlayerModel` (pure), the `NSViewRepresentable`, the unreadable-file card |
| `app/…/Tests/CicadaAppTests/VideoPlayerTests.swift` (new) | Fake controller: space, re-render identity, URL swap, readability gate |
| `app/…/Tests/CicadaAppTests/AVImportLintTests.swift` (new) | R8's source lint |
| `app/…/Views/Common/MediaPreview.swift` | `Kind` gains `.embedVideo`/`.fileVideo`; URL-first dispatch; the two new branches; Reveal in Finder |
| `app/…/Views/Common/WebView.swift` | `loadFileURL(_:allowingReadAccessTo:)` for `file://` |
| `app/…/Tests/CicadaAppTests/MediaPreviewKindTests.swift` (new) | Precedence table (R7) |
| `app/…/Views/Common/HeroPreview.swift` | `YouTubeHero` → `EmbedVideoHero`; new `FileVideoHero`; `hasPreviewableAsset` |
| `app/…/Views/Feed/FeedView.swift` | Play badge + duration pill on `FeedRow.thumbnail`; `FeedPreviewLayout.sheetSize(for:)` |
| `app/…/Tests/CicadaAppTests/FeedVideoRowTests.swift` (new) | The playable-ref badge predicate + `FeedPreviewLayout.sheetSize` (the duration label itself is pinned in `VideoRefTests`) |
| `app/…/Models/Entity.swift` | `MediaBlock.provider/durationS` (+ the raw-frontmatter fallback) |
| `app/…/Services/APIClient.swift` | `MediaFeedItem.provider/durationS` |
| `app/…/Tests/CicadaAppTests/MediaBlockDecodeTests.swift` (new) | Decodes with and without the new keys |
| `api/services/media_ingestor.py` | `MediaMeta.provider/duration_s`; `_classify → "video"`; `enrich` provider dispatch + file short-circuit; `_enrich_oembed`; `_enrich_opengraph` content-type guard; `write_media_entity` writes the two keys when set |
| `api/models/schemas.py` | `EntityMedia.provider/duration_s`; `MediaSourceItem.provider/duration_s` |
| `api/routers/entities.py` | `_build_media_block` reads the two keys |
| `api/routers/sources.py` | The two keys read from the page's `media:` block (inside the existing build) |
| `api/tests/test_video_enrichment.py` (new) | Classification, the file short-circuit, oEmbed fakes, the content-type guard, TikTok-export routing |
| `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`, `CLAUDE.md` | The G11 video paragraph, the follow-ups, the two ToS lines |

---

### Task 1: The classification table — one fixture, two implementations (R-V8)

**Files:**
- Create: `api/tests/fixtures/video_urls.json`
- Create: `api/services/video_urls.py`
- Create: `api/tests/test_video_urls.py`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Common/VideoRef.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/VideoRefTests.swift`

**Interfaces:**
- Produces (Python): `video_urls.VideoRef(provider: str, kind: str, video_id: str | None, embed_url: str | None, watch_url: str)`; `video_urls.resolve(url: str) -> VideoRef | None`; `video_urls.is_direct_file(url: str) -> bool`; `video_urls.PROVIDERS: frozenset[str]`; `video_urls.OEMBED_PROVIDERS: tuple[str, ...] = ("vimeo", "tiktok", "loom")`.
- Produces (Swift): `struct VideoRef: Equatable { enum Provider: String { youtube, vimeo, tiktok, loom, twitch, direct, local }; enum Kind: String { embed, file, external }; let provider: Provider; let kind: Kind; let videoId: String?; let embedURL: URL?; let watchURL: URL; var isPlayable: Bool; var autoplayURL: URL?; static func resolve(_ raw: String) -> VideoRef?; static func durationLabel(_ seconds: Int?) -> String? }`. The raw values are the fixture's `provider`/`kind` strings and must stay spelled exactly as `video_urls.PROVIDERS` spells them (R1).
- Consumes: nothing. Both modules are leaves — no imports beyond the stdlib / Foundation.

- [ ] **Step 1: the fixture.** Write `api/tests/fixtures/video_urls.json` — `api/tests/fixtures/` does **not exist yet** (verified: no other test reads a fixture file off disk), so create the directory too. Every URL synthetic. `provider`/`kind`/`videoId`/`embedUrl` are `null` where `resolve` returns nothing; `why` documents the row for a future reader (it is data, not an assertion).

```json
{
  "version": 1,
  "note": "R-V8: read by api/tests/test_video_urls.py AND app/CicadaApp/Tests/CicadaAppTests/VideoRefTests.swift. Add a provider here first; the other suite then fails until it is taught too. Every URL is synthetic (example.com / example ids) — never a real saved link.",
  "cases": [
    {"url": "https://www.youtube.com/watch?v=vid00000001", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "the shape already shipped"},
    {"url": "https://www.youtube.com/watch?v=vid00000001&list=PLexample01&index=2", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "a video inside a playlist plays as the video; normalize_url drops the list too"},
    {"url": "https://youtu.be/vid00000001?t=42", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "short link"},
    {"url": "https://www.youtube.com/shorts/vid00000002", "provider": "youtube", "kind": "embed", "videoId": "vid00000002", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000002", "why": "portrait, letterboxed in a 16:9 frame — cosmetic, out of scope"},
    {"url": "https://www.youtube.com/embed/vid00000001", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "already an embed url"},
    {"url": "https://www.youtube-nocookie.com/embed/vid00000001", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "our own embed host round-trips"},
    {"url": "https://www.youtube.com/v/vid00000001", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "legacy /v/ shape _youtube_video_id already knows"},
    {"url": "https://www.youtube.com/live/vid00000003", "provider": "youtube", "kind": "embed", "videoId": "vid00000003", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000003", "why": "R-V1 fix: fell out of both the Python and the Swift id parsers"},
    {"url": "https://m.youtube.com/watch?v=vid00000001", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "mobile host"},
    {"url": "https://music.youtube.com/watch?v=vid00000001", "provider": "youtube", "kind": "embed", "videoId": "vid00000001", "embedUrl": "https://www.youtube-nocookie.com/embed/vid00000001", "why": "music host"},
    {"url": "https://www.youtube.com/playlist?list=PLexample01", "provider": "youtube", "kind": "embed", "videoId": null, "embedUrl": "https://www.youtube-nocookie.com/embed/videoseries?list=PLexample01", "why": "YouTube's own videoseries player; no single video id exists"},
    {"url": "https://www.youtube.com/@examplechannel", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "a channel page is not a video — R7 lets it render as a website card"},
    {"url": "https://www.youtube.com/results?search_query=example", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "a search page is not a video"},

    {"url": "https://vimeo.com/123456789", "provider": "vimeo", "kind": "embed", "videoId": "123456789", "embedUrl": "https://player.vimeo.com/video/123456789", "why": "canonical vimeo link"},
    {"url": "https://player.vimeo.com/video/123456789", "provider": "vimeo", "kind": "embed", "videoId": "123456789", "embedUrl": "https://player.vimeo.com/video/123456789", "why": "already a player url"},
    {"url": "https://vimeo.com/channels/examplechannel/123456789", "provider": "vimeo", "kind": "embed", "videoId": "123456789", "embedUrl": "https://player.vimeo.com/video/123456789", "why": "first all-digit segment is the id"},
    {"url": "https://vimeo.com/123456789/abc123def4", "provider": "vimeo", "kind": "embed", "videoId": "123456789", "embedUrl": "https://player.vimeo.com/video/123456789?h=abc123def4", "why": "unlisted-video hash is Vimeo's own private-link param; if it ever fails the always-present Open externally is the fallback"},
    {"url": "https://vimeo.com/exampleuser", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "a profile has no numeric id"},

    {"url": "https://www.tiktok.com/@exampleuser/video/1234567890123456789", "provider": "tiktok", "kind": "embed", "videoId": "1234567890123456789", "embedUrl": "https://www.tiktok.com/embed/v2/1234567890123456789", "why": "the player url is derived from the id, never from the oEmbed html blob"},
    {"url": "https://www.tiktok.com/embed/v2/1234567890123456789", "provider": "tiktok", "kind": "embed", "videoId": "1234567890123456789", "embedUrl": "https://www.tiktok.com/embed/v2/1234567890123456789", "why": "already an embed url"},
    {"url": "https://vm.tiktok.com/ZMexample/", "provider": "tiktok", "kind": "external", "videoId": null, "embedUrl": null, "why": "R4 — the shortlink hides the id and read-time classification does no network"},
    {"url": "https://www.tiktok.com/@exampleuser", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "a profile is not a video"},

    {"url": "https://www.loom.com/share/abc123def4567890abc123def4567890", "provider": "loom", "kind": "embed", "videoId": "abc123def4567890abc123def4567890", "embedUrl": "https://www.loom.com/embed/abc123def4567890abc123def4567890", "why": "loom's own embed url; its oEmbed also carries a duration"},
    {"url": "https://www.loom.com/embed/abc123def4567890abc123def4567890", "provider": "loom", "kind": "embed", "videoId": "abc123def4567890abc123def4567890", "embedUrl": "https://www.loom.com/embed/abc123def4567890abc123def4567890", "why": "already an embed url"},

    {"url": "https://www.twitch.tv/videos/1234567890", "provider": "twitch", "kind": "external", "videoId": "1234567890", "embedUrl": null, "why": "R5 — the player validates parent against the real embedding origin; a WKWebView top-level document has none and faking one is circumvention"},
    {"url": "https://clips.twitch.tv/ExampleClipSlug", "provider": "twitch", "kind": "external", "videoId": "ExampleClipSlug", "embedUrl": null, "why": "same parent restriction"},
    {"url": "https://www.twitch.tv/exampleuser", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "a live channel page is not a stored video"},

    {"url": "https://example.com/media/clip.mp4", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "AVKit plays it; R-V4 — the user saved this url, Cicada never derived it"},
    {"url": "https://example.com/media/clip.m4v", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "extension set"},
    {"url": "https://example.com/media/clip.mov", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "extension set"},
    {"url": "https://example.com/media/clip.webm", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "extension set"},
    {"url": "https://example.com/media/stream.m3u8", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "HLS — AVKit plays it, a WKWebView will not"},
    {"url": "https://example.com/media/CLIP.MP4", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "extension match is case-insensitive"},
    {"url": "http://example.com/media/clip.mp4", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "http is allowed; the user saved it"},
    {"url": "https://example.com/media/clip.mp4?token=abc123", "provider": "direct", "kind": "file", "videoId": null, "embedUrl": null, "why": "R3 — the query is ignored"},
    {"url": "https://example.com/watch?file=movie.mp4", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "R3 — an extension in the QUERY is not a file"},

    {"url": "file:///Users/example/Movies/clip.mov", "provider": "local", "kind": "file", "videoId": null, "embedUrl": null, "why": "readability is checked at render time (R9), never here"},
    {"url": "file:///Users/example/Documents/notes.txt", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "local still needs the video extension"},
    {"url": "file://", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "no path"},

    {"url": "https://x.com/exampleuser/status/1234567890", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "R5 — /status/<id> is any post; calling every one a video would be a lie. Stays a website card"},
    {"url": "https://www.instagram.com/reel/Cexample01/", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "R5 — login-walled, never plays in-app; MediaPreviewModel owns it by host"},
    {"url": "https://example.com/articles/how-to-example", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "an ordinary page"},
    {"url": "https://example.com/photo.jpg", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "an image is handled by the image branch"},
    {"url": "javascript:alert(1)//clip.mp4", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "R2 — only http/https/file are ever classified"},
    {"url": "not a url", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "R2 — total, never raises"},
    {"url": "", "provider": null, "kind": null, "videoId": null, "embedUrl": null, "why": "R2 — total, never raises"}
  ]
}
```

- [ ] **Step 2: failing Python test.** `api/tests/test_video_urls.py`:

```python
"""The URL → video classification table (Track V, R-V8 / plan R1-R5).

One fixture, two suites: this file and
``app/CicadaApp/Tests/CicadaAppTests/VideoRefTests.swift`` read the SAME
``api/tests/fixtures/video_urls.json``. Add a provider on one side only and
the other side goes red — the "ship both halves together" rule applied to a
classification table instead of an ETag.

Hermetic by construction: ``video_urls.resolve`` does no I/O and no network,
so there is nothing to stub. A shortlink whose id is only recoverable by
following a redirect stays ``external`` rather than being resolved by a fetch
(R4) — read-time classification never reaches the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import video_urls

FIXTURE = Path(__file__).parent / "fixtures" / "video_urls.json"


def _cases() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) >= 40, "the fixture shrank — a table test that reads 0 rows passes vacuously"
    return cases


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["url"][:60] or "<empty>")
def test_resolve_matches_the_shared_fixture(case):
    ref = video_urls.resolve(case["url"])
    if case["provider"] is None:
        assert ref is None, f"{case['url']} should not classify as a video ({case['why']})"
        return
    assert ref is not None, f"{case['url']} should classify ({case['why']})"
    assert ref.provider == case["provider"]
    assert ref.kind == case["kind"]
    assert ref.video_id == case["videoId"]
    assert ref.embed_url == case["embedUrl"]
    assert ref.watch_url == case["url"]


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not a url", "http://", "https://", "file://", "javascript:alert(1)//a.mp4",
     "mailto:someone@example.com", "https://" + "a" * 10_000 + ".com/clip.mp4", "://broken"],
)
def test_resolve_is_total_and_never_raises(raw):
    # R2: a classifier that can throw would take a Feed row down with it.
    video_urls.resolve(raw)


def test_a_very_long_but_valid_direct_file_url_still_classifies():
    url = "https://example.com/" + "a" * 5_000 + "/clip.mp4"
    ref = video_urls.resolve(url)
    assert ref is not None and ref.kind == "file" and ref.provider == "direct"


def test_embed_url_is_only_ever_set_for_an_embed_kind():
    for case in _cases():
        if case["kind"] != "embed":
            assert case["embedUrl"] is None, case["url"]


def test_is_direct_file_agrees_with_resolve():
    for case in _cases():
        expected = case["kind"] == "file"
        assert video_urls.is_direct_file(case["url"]) is expected, case["url"]
```

Run it: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_video_urls.py -q -p no:cacheprovider` → collection error (no module). That is the red.

- [ ] **Step 3: `api/services/video_urls.py`.**

```python
"""URL → video classification. Pure: no network, no I/O, never raises (R2).

Track V / R-V1: the provider is a **pure function of a URL the bank already
stores**, so it is DERIVED at read time rather than written into a bank. That
is what lets every already-saved Vimeo/TikTok/Loom/``.mp4`` item play the
moment the app updates — no whole-bank rewrite commit, and no parallel
``url_index.json`` migration (``GET /sources`` reads ``media_type`` from the
index, not the page, so migrating one and not the other is the split-brain
class this repo already knows). It is also the house rule: ``_state.md`` is a
cursor not a copy, ``age_days`` is derived at read, ``inbox_context``
recomputes offsets on every read.

The same table exists in Swift (``Views/Common/VideoRef.swift``) and both are
pinned by ``api/tests/fixtures/video_urls.json`` (R-V8). Edit the fixture
first; the other side then fails until it is taught too.

What is NOT here, and why (R-V4 — the ToS rail):
  * No stream resolution. No ``yt-dlp``, no ``googlevideo.com``, no ``.m3u8``
    lifted out of a page's HTML or JS, no provider CDN URL. A direct file
    Cicada plays is one the USER saved as a direct URL.
  * No network to classify. ``vm.tiktok.com/<slug>`` hides its id behind a
    redirect, so it stays ``external`` rather than being resolved by a fetch.
  * Twitch is ``external``: its player validates ``parent`` against the real
    embedding origin, and a ``WKWebView`` loading the player as a top-level
    document has none — synthesising one is circumventing an embed
    restriction.
  * X is absent: ``x.com/<user>/status/<id>`` is *any* post, so classifying
    every status as a video would be a lie. Instagram is absent too — it is
    login-walled and never plays in-app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

# Path extensions AVKit can play directly (R3). Matched case-insensitively
# against the PATH only — an extension in a query string is not a file.
FILE_EXTENSIONS = frozenset({"mp4", "m4v", "mov", "webm", "m3u8"})

# Schemes that are ever classified (R2). Anything else — ``javascript:``,
# ``data:``, ``mailto:`` — is not a video no matter what it ends in.
_SCHEMES = frozenset({"http", "https", "file"})

PROVIDERS = frozenset({"youtube", "vimeo", "tiktok", "loom", "twitch", "direct", "local"})

# Providers with a keyless oEmbed endpoint the ingest path may call. YouTube
# is deliberately absent: ``media_ingestor._enrich_youtube`` already owns it
# and stays untouched (plan R12).
OEMBED_PROVIDERS: tuple[str, ...] = ("vimeo", "tiktok", "loom")

_YOUTUBE_PATH_RE = re.compile(r"^/(?:shorts|embed|v|live)/([^/?&#]+)")
_TIKTOK_VIDEO_RE = re.compile(r"^/@[^/]+/video/(\d+)")
_TIKTOK_EMBED_RE = re.compile(r"^/embed/v\d+/(\d+)")
_LOOM_RE = re.compile(r"^/(?:share|embed)/([0-9a-zA-Z]+)")
_TWITCH_VIDEO_RE = re.compile(r"^/videos/(\d+)")
_VIMEO_HASH_RE = re.compile(r"^[0-9a-zA-Z]{4,}$")


@dataclass(frozen=True)
class VideoRef:
    """One resolved video reference.

    ``kind`` is the *decision*, not just a description:
      * ``embed``    — load ``embed_url`` in the provider's own player.
      * ``file``     — hand ``watch_url`` to AVKit.
      * ``external`` — recognised as a video, deliberately not played in-app;
                       the reason lives in this module's docstring, not in a
                       TODO.
    ``video_id`` is ``None`` for a file and for a YouTube playlist (there is
    no single video; ``embed_url`` carries the list id instead).
    """

    provider: str
    kind: str
    video_id: str | None
    embed_url: str | None
    watch_url: str


def _parsed(url: str):
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if (parsed.scheme or "").lower() not in _SCHEMES:
        return None
    return parsed


def _extension(path: str) -> str:
    tail = path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1].lower() if "." in tail else ""


def is_direct_file(url: str) -> bool:
    """True for a URL whose PATH ends in a playable video extension (R3)."""
    ref = resolve(url)
    return ref is not None and ref.kind == "file"


def _youtube(parsed, url: str) -> VideoRef | None:
    host = (parsed.hostname or "").lower()
    vid: str | None = None
    if host.endswith("youtu.be"):
        vid = (parsed.path.strip("/").split("/") or [""])[0] or None
    else:
        if parsed.path.rstrip("/") == "/watch":
            vid = (parse_qs(parsed.query).get("v") or [None])[0] or None
        if not vid:
            m = _YOUTUBE_PATH_RE.match(parsed.path)
            if m:
                vid = m.group(1)
        if not vid and parsed.path.rstrip("/") == "/playlist":
            # YouTube's own multi-video player. No single video id exists, so
            # ``video_id`` stays None and the list id lives in the embed url.
            plist = (parse_qs(parsed.query).get("list") or [None])[0]
            if plist:
                return VideoRef(
                    "youtube", "embed", None,
                    f"https://www.youtube-nocookie.com/embed/videoseries?list={plist}",
                    url,
                )
    if not vid:
        return None
    return VideoRef(
        "youtube", "embed", vid,
        f"https://www.youtube-nocookie.com/embed/{vid}", url,
    )


def _vimeo(parsed, url: str) -> VideoRef | None:
    segments = [s for s in parsed.path.split("/") if s]
    for i, seg in enumerate(segments):
        if not seg.isdigit():
            continue
        embed = f"https://player.vimeo.com/video/{seg}"
        # Vimeo's own private-link param: an unlisted video is
        # ``vimeo.com/<id>/<hash>`` and embeds as ``?h=<hash>``.
        nxt = segments[i + 1] if i + 1 < len(segments) else ""
        if nxt and not nxt.isdigit() and _VIMEO_HASH_RE.match(nxt):
            embed = f"{embed}?h={nxt}"
        return VideoRef("vimeo", "embed", seg, embed, url)
    return None


def _tiktok(parsed, url: str) -> VideoRef | None:
    host = (parsed.hostname or "").lower()
    if host.startswith("vm.") or host.startswith("vt."):
        # R4: the id is only behind a redirect; classifying costs no network.
        return VideoRef("tiktok", "external", None, None, url)
    m = _TIKTOK_VIDEO_RE.match(parsed.path) or _TIKTOK_EMBED_RE.match(parsed.path)
    if not m:
        return None
    vid = m.group(1)
    return VideoRef("tiktok", "embed", vid, f"https://www.tiktok.com/embed/v2/{vid}", url)


def _loom(parsed, url: str) -> VideoRef | None:
    m = _LOOM_RE.match(parsed.path)
    if not m:
        return None
    vid = m.group(1)
    return VideoRef("loom", "embed", vid, f"https://www.loom.com/embed/{vid}", url)


def _twitch(parsed, url: str) -> VideoRef | None:
    host = (parsed.hostname or "").lower()
    if host.startswith("clips."):
        slug = (parsed.path.strip("/").split("/") or [""])[0]
        return VideoRef("twitch", "external", slug or None, None, url) if slug else None
    m = _TWITCH_VIDEO_RE.match(parsed.path)
    return VideoRef("twitch", "external", m.group(1), None, url) if m else None


def resolve(url: str) -> VideoRef | None:
    """Classify a URL. ``None`` means "not a video" — never an exception (R2)."""
    parsed = _parsed(url)
    if parsed is None:
        return None
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if scheme == "file":
        if not path.strip("/"):
            return None
        return VideoRef("local", "file", None, None, url) if _extension(path) in FILE_EXTENSIONS else None

    if not host:
        return None

    # A direct file wins over a host table: nothing in the table serves one.
    if _extension(path) in FILE_EXTENSIONS:
        return VideoRef("direct", "file", None, None, url)

    if host.endswith("youtu.be") or "youtube.com" in host or "youtube-nocookie.com" in host:
        return _youtube(parsed, url)
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        return _vimeo(parsed, url)
    if "tiktok.com" in host:
        return _tiktok(parsed, url)
    if "loom.com" in host:
        return _loom(parsed, url)
    if "twitch.tv" in host:
        return _twitch(parsed, url)
    return None
```

Run the Python test again → green. `api/.venv/bin/python -m pytest api/tests/test_video_urls.py -q -p no:cacheprovider`.

- [ ] **Step 4: failing Swift test.** `app/CicadaApp/Tests/CicadaAppTests/VideoRefTests.swift` — the `#filePath` walk copied from `FontLiteralLintTests.swift:14-27`, including its non-vacuity guard:

```swift
import XCTest
@testable import CicadaApp

/// R-V8: the Swift half of the one classification table. This file and
/// `api/tests/test_video_urls.py` read the SAME
/// `api/tests/fixtures/video_urls.json` — add a provider on one side only and
/// the other side goes red. The `#filePath` walk (and its non-vacuous guard)
/// is the pattern `FontLiteralLintTests` already uses.
final class VideoRefTests: XCTestCase {
    private struct Case: Decodable {
        let url: String
        let provider: String?
        let kind: String?
        let videoId: String?
        let embedUrl: String?
        let why: String
    }
    private struct Fixture: Decodable { let cases: [Case] }

    private func fixture() throws -> [Case] {
        // …/Tests/CicadaAppTests/<this file> → …/CicadaApp → …/app → repo root
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/video_urls.json")
        let data = try Data(contentsOf: file)
        let cases = try JSONDecoder().decode(Fixture.self, from: data).cases
        XCTAssertGreaterThanOrEqual(
            cases.count, 40,
            "read \(cases.count) rows from \(file.path) — a table test over 0 rows passes vacuously")
        return cases
    }

    func testResolveMatchesTheSharedFixture() throws {
        for c in try fixture() {
            let ref = VideoRef.resolve(c.url)
            guard let provider = c.provider else {
                XCTAssertNil(ref, "\(c.url) should not classify (\(c.why))")
                continue
            }
            guard let ref else {
                // `continue`, never `return`: a `return XCTFail(...)` here
                // would abandon the remaining ~45 rows on the first failure
                // and report one drift instead of all of them.
                XCTFail("\(c.url) should classify (\(c.why))"); continue
            }
            XCTAssertEqual(ref.provider.rawValue, provider, c.url)
            XCTAssertEqual(ref.kind.rawValue, c.kind, c.url)
            XCTAssertEqual(ref.videoId, c.videoId, c.url)
            XCTAssertEqual(ref.embedURL?.absoluteString, c.embedUrl, c.url)
            XCTAssertEqual(ref.watchURL.absoluteString, c.url, c.url)
        }
    }

    func testResolveIsTotal() {
        for raw in ["", "   ", "not a url", "http://", "https://", "file://",
                    "javascript:alert(1)//a.mp4", "mailto:someone@example.com", "://broken",
                    "https://" + String(repeating: "a", count: 10_000) + ".com/clip.mp4"] {
            _ = VideoRef.resolve(raw)   // R2: must not trap
        }
    }

    func testOnlyEmbedKindsCarryAnEmbedURL() throws {
        for c in try fixture() where c.kind != "embed" {
            XCTAssertNil(VideoRef.resolve(c.url)?.embedURL, c.url)
        }
    }

    func testAutoplayIsAddedOnlyWhereTheProviderDocumentsIt() {
        // R11: YouTube and Vimeo only; TikTok/Loom get their plain player url.
        XCTAssertEqual(VideoRef.resolve("https://www.youtube.com/watch?v=vid00000001")?.autoplayURL?.absoluteString,
                       "https://www.youtube-nocookie.com/embed/vid00000001?autoplay=1")
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.autoplayURL?.absoluteString,
                       "https://player.vimeo.com/video/123456789?autoplay=1")
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789/abc123def4")?.autoplayURL?.absoluteString,
                       "https://player.vimeo.com/video/123456789?h=abc123def4&autoplay=1")
        XCTAssertEqual(VideoRef.resolve("https://www.loom.com/share/abc123def4567890abc123def4567890")?.autoplayURL?.absoluteString,
                       "https://www.loom.com/embed/abc123def4567890abc123def4567890")
        XCTAssertNil(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.autoplayURL)
    }

    func testIsPlayableExcludesExternal() {
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://example.com/media/clip.mp4")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.isPlayable, false)
        XCTAssertEqual(VideoRef.resolve("https://vm.tiktok.com/ZMexample/")?.isPlayable, false)
    }

    func testDurationLabel() {
        // R17: absent means absent — nothing is rendered, nothing is guessed.
        XCTAssertNil(VideoRef.durationLabel(nil))
        XCTAssertNil(VideoRef.durationLabel(0))
        XCTAssertNil(VideoRef.durationLabel(-5))
        XCTAssertEqual(VideoRef.durationLabel(9), "0:09")
        XCTAssertEqual(VideoRef.durationLabel(95), "1:35")
        XCTAssertEqual(VideoRef.durationLabel(3725), "1:02:05")
    }
}
```

- [ ] **Step 5: `Views/Common/VideoRef.swift`.** Same table, same docstring reasoning (cite R-V1/R-V4 and point at `api/services/video_urls.py` as the twin). Implementation notes that matter:
  - Parse with `URLComponents(string:)`; guard `scheme?.lowercased()` ∈ `["http", "https", "file"]`; a `nil`/empty host disqualifies everything except `file`.
  - `videoId` extraction mirrors the Python regexes exactly. Use `path.split(separator: "/")` + explicit prefix checks rather than `NSRegularExpression` (simpler to read, and the shapes are small). The three rules that are not obvious from the fixture rows alone, restated so the two sides cannot drift: **(a)** the direct-file extension check runs BEFORE the host table, so nothing in the table can serve a `.mp4`; **(b)** Vimeo's id is the **first all-digit path segment** (`/channels/<name>/<id>` and `/video/<id>` both work), and an immediately-following segment that is alphanumeric, ≥4 chars and NOT all digits is the unlisted-link hash appended as `?h=<hash>`; **(c)** a `vm.`/`vt.` TikTok host is `external` before any path parsing (R4).
  - `embedURL` strings are built by string interpolation and turned into `URL(string:)` — identical literals to the Python side, pinned by the fixture.
  - `watchURL` is `URL(string: raw)` — if that fails, `resolve` returns `nil` (a ref with no openable URL is useless).
  - `var isPlayable: Bool { kind == .embed || kind == .file }` (R6/R14).
  - `var autoplayURL: URL?` — R11: `youtube` and `vimeo` only, appended with `URLComponents` so an existing `?h=` survives as `?h=…&autoplay=1`; every other provider returns `embedURL` unchanged; `external` returns `nil`.
  - `static func durationLabel(_ seconds: Int?) -> String?` — `nil` for `nil`/`<= 0` (R17); `m:ss` under an hour, `h:mm:ss` above.

- [ ] **Step 6: green + commit.**

```
cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_video_urls.py -q -p no:cacheprovider
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test --filter VideoRefTests 2>&1 | tail -20
```

Commit (stage named files only):

```
feat(video): one URL→video classification table, two suites, one fixture (Track V, R-V8)
```

---

### Task 2: The player and its seam — `VideoPlaybackController` + AVKit (R-V3, R-V6)

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Common/AVPlaybackController.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Common/VideoPlayerView.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/VideoPlayerTests.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/AVImportLintTests.swift`

**Interfaces:**
- Produces: `protocol VideoPlaybackController: AnyObject { var url: URL { get }; var isPlaying: Bool { get }; func play(); func pause(); func toggle() }`; `final class AVPlaybackController: VideoPlaybackController`; `enum VideoPlayerModel { enum State: Equatable { case playable(URL); case unreadable(path: String) }; static func state(for: URL) -> State; static func controller(for: URL, existing: VideoPlaybackController?, make: (URL) -> VideoPlaybackController) -> VideoPlaybackController; static func handleSpace(_ controller: VideoPlaybackController?) -> Bool }`; `struct VideoPlayerView: View`; `final class FakePlaybackController` (test target).
- Consumes: `VideoRef` (Task 1) is not needed here — the player takes a bare `URL`, so it is reusable by anything.

- [ ] **Step 1: failing tests.** `VideoPlayerTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-V6: the seam, not a mock. Everything worth testing about playback is a
/// decision made BEFORE AVFoundation is involved — which controller to keep,
/// whether space was handled, whether a local file is even readable — so the
/// tests drive a fake and no AVPlayer is ever constructed. "Does this codec
/// decode?" is a stated manual check (plan R8), not a mocked green.
final class FakePlaybackController: VideoPlaybackController {
    let url: URL
    private(set) var isPlaying = false
    private(set) var toggles = 0
    init(url: URL) { self.url = url }
    func play() { isPlaying = true }
    func pause() { isPlaying = false }
    func toggle() { toggles += 1; isPlaying.toggle() }
}

final class VideoPlayerTests: XCTestCase {
    private let a = URL(string: "https://example.com/media/clip.mp4")!
    private let b = URL(string: "https://example.com/media/other.mp4")!

    func testARerenderWithTheSameURLKeepsTheSameController() {
        let first = VideoPlayerModel.controller(for: a, existing: nil, make: FakePlaybackController.init)
        let second = VideoPlayerModel.controller(for: a, existing: first, make: FakePlaybackController.init)
        // The bug this guards is the one WebView.updateNSView already guards:
        // a SwiftUI re-render must not restart playback.
        XCTAssertTrue(first === second)
    }

    func testChangingTheURLSwapsTheControllerAndStartsPaused() {
        let first = VideoPlayerModel.controller(for: a, existing: nil, make: FakePlaybackController.init)
        first.play()
        let second = VideoPlayerModel.controller(for: b, existing: first, make: FakePlaybackController.init)
        XCTAssertFalse(first === second)
        XCTAssertEqual(second.url, b)
        XCTAssertFalse(second.isPlaying)
    }

    func testSpaceTogglesExactlyOncePerPressAndReportsHandled() {
        let c = FakePlaybackController(url: a)
        XCTAssertTrue(VideoPlayerModel.handleSpace(c))
        XCTAssertEqual(c.toggles, 1)
        XCTAssertTrue(c.isPlaying)
        XCTAssertTrue(VideoPlayerModel.handleSpace(c))
        XCTAssertEqual(c.toggles, 2)
        XCTAssertFalse(c.isPlaying)
    }

    func testSpaceWithNoControllerIsNotHandled() {
        // R10: the key must fall through rather than be swallowed when there
        // is nothing to toggle.
        XCTAssertFalse(VideoPlayerModel.handleSpace(nil))
    }

    func testARemoteURLIsAlwaysPlayable() {
        XCTAssertEqual(VideoPlayerModel.state(for: a), .playable(a))
    }

    func testAMissingLocalFileIsUnreadableAndNamesItsPath() throws {
        let missing = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cicada-video-\(UUID().uuidString)/clip.mov")
        XCTAssertEqual(VideoPlayerModel.state(for: missing), .unreadable(path: missing.path))
    }

    func testAReadableLocalFileIsPlayable() throws {
        let file = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cicada-video-\(UUID().uuidString).mov")
        try Data("not really a movie".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        // R9 is a READABILITY gate, not a decode gate — whether AVFoundation
        // can decode the bytes is the manual check, and a black rectangle is
        // never the answer either way.
        XCTAssertEqual(VideoPlayerModel.state(for: file), .playable(file))
    }
}
```

`AVImportLintTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-V6 / plan R8: `AVPlaybackController.swift` is the ONLY new file that may
/// import AVFoundation, so the rest of the app stays testable without one.
/// A source lint, not a behaviour test — the defect is "an import exists in
/// the diff", which nothing a rendered view produces would reveal.
/// `WalkthroughPanel.swift` is grandfathered: its muted looping walkthrough
/// player predates this seam and is not a media surface.
final class AVImportLintTests: XCTestCase {
    private static let allowed = [
        "Views/Common/AVPlaybackController.swift",
        "Views/Capture/Sheets/WalkthroughPanel.swift",
    ]

    func testOnlyTheControllerImportsAVFoundation() throws {
        let sources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
        let all = FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" }
            .filter { url in !Self.allowed.contains(where: { url.path.hasSuffix($0) }) } ?? []
        XCTAssertFalse(all.isEmpty, "found no sources under \(sources.path) — the lint would pass vacuously")
        for file in all {
            let text = try String(contentsOf: file, encoding: .utf8)
            for needle in ["import AVKit", "import AVFoundation"] where text.contains(needle) {
                XCTFail("\(file.lastPathComponent) has `\(needle)` — route playback through "
                        + "VideoPlaybackController instead (R-V6).")
            }
        }
    }
}
```

- [ ] **Step 2: `AVPlaybackController.swift`.** The only AVFoundation importer:

```swift
import AVKit
import Foundation

/// The production `VideoPlaybackController` (R-V6). This is the ONLY file in
/// the app that imports AVFoundation — `AVImportLintTests` fails the build on
/// a second one — so every view, layout and key-handling decision above it is
/// unit-testable against `FakePlaybackController` with no player involved.
///
/// AVKit rather than WebKit is what makes local files and HLS work at all:
/// `WKWebView` refuses a `file://` document loaded via `URLRequest`, and will
/// not play a bare `.m3u8` manifest as a document.
final class AVPlaybackController: VideoPlaybackController {
    let url: URL
    let player: AVPlayer
    var isPlaying: Bool { player.timeControlStatus != .paused }

    init(url: URL) {
        self.url = url
        // Starts PAUSED on purpose: a player that begins the moment an entity
        // page renders is the same surprise the hero embed deliberately avoids
        // (MediaPreview.swift:92-97 — the hero never autoplays).
        self.player = AVPlayer(url: url)
    }

    func play() { player.play() }
    func pause() { player.pause() }
    func toggle() { isPlaying ? pause() : play() }
}

/// `AVPlayerView` with inline transport controls, wrapped so `VideoPlayerView`
/// stays AVFoundation-free.
///
/// It takes the **protocol**, not `AVPlaybackController`, and does the cast
/// here: `VideoPlayerView` holds a `VideoPlaybackController?` (that is the
/// whole point of R-V6), so if this surface demanded the concrete type the
/// view would have to name an AV type to build it and `AVImportLintTests`
/// would be linting a seam that no longer exists. A fake controller in a
/// preview or a test simply renders an empty player rather than crashing.
struct AVPlayerSurface: NSViewRepresentable {
    let controller: VideoPlaybackController

    private var player: AVPlayer? { (controller as? AVPlaybackController)?.player }

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .inline
        view.videoGravity = .resizeAspect
        view.player = player
        return view
    }

    func updateNSView(_ view: AVPlayerView, context: Context) {
        // Same rule as WebView.updateNSView: only swap when the player really
        // changed, so a re-render never restarts playback.
        if view.player !== player { view.player = player }
    }
}
```

(`import SwiftUI` is also needed for `NSViewRepresentable` — add it; the lint only forbids AV imports elsewhere.)

- [ ] **Step 3: `VideoPlayerView.swift`** — the protocol, the pure model, the view, the unreadable card. No AV import.

  - `VideoPlaybackController` protocol as declared above.
  - `VideoPlayerModel.state(for:)`: non-`file` URL → `.playable(url)`; `file` URL → `FileManager.default.isReadableFile(atPath: url.path) ? .playable(url) : .unreadable(path: url.path)`. Docstring carries R9's known limit (unsandboxed today; a sandboxed build would need a security-scoped bookmark for a path outside its container — stated, not a TODO).
  - `VideoPlayerModel.controller(for:existing:make:)`: return `existing` when `existing?.url == url`, else `make(url)`.
  - `VideoPlayerModel.handleSpace(_:)`: `guard let c else { return false }; c.toggle(); return true`.
  - `VideoPlayerView(url:)` holds `@State private var controller: VideoPlaybackController?`, renders `AVPlayerSurface(controller:)` for `.playable` and `unreadableCard(path:)` for `.unreadable`, with `.focusable()` and `.onKeyPress(.space) { VideoPlayerModel.handleSpace(controller) ? .handled : .ignored }` on the container (R10 — scoped, never a global `.keyboardShortcut(" ")`).
    **Where the controller is created matters:** assign it in `.task(id: url) { controller = VideoPlayerModel.controller(for: url, existing: controller, make: AVPlaybackController.init) }`, never from inside `body` — mutating `@State` during a view update is the SwiftUI defect that produces "Modifying state during view update" and an undefined render. `.task(id:)` re-fires on a url change, which is exactly the swap `VideoPlayerModel.controller` decides; the surface renders empty for the first frame, which is what a paused player looks like anyway.
  - `unreadableCard(path:)`: `exclamationmark.triangle` + `Text("Cicada can't read this file")` + the path in a monospaced caption + two buttons — **Reveal in Finder** (`NSWorkspace.shared.activateFileViewerSelecting([url])`) and **Open externally** (`NSWorkspace.shared.open(url)`). Fonts via `CicadaTheme.font(size:)`; frame `maxWidth: .infinity`, same corner radius/border as the other hero cards.

- [ ] **Step 4: green + commit.**

```
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test --filter "VideoPlayerTests|AVImportLintTests" 2>&1 | tail -20
```

```
feat(app): an AVKit player behind a VideoPlaybackController seam (Track V, R-V3/R-V6)
```

---

### Task 3: Read-time dispatch — `MediaPreviewModel.Kind` stops trusting `mediaType` (R-V1)

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/MediaPreview.swift:51-65` (`Kind`, `kind`), `:124-142` (the switch), new `embedVideoPreview` / `fileVideoPreview` branches, `:340-361` (the sheets), and the file-header comment at `:3-17`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/WebView.swift:17-33`
- Create: `app/CicadaApp/Tests/CicadaAppTests/MediaPreviewKindTests.swift`

**Interfaces:**
- Produces: `MediaPreviewModel.Kind = { image, embedVideo(VideoRef), fileVideo(VideoRef), instagram, website }` (`Equatable`); `MediaPreviewModel.videoRef: VideoRef?`.
- Consumes: `VideoRef` (Task 1), `VideoPlayerView` (Task 2).
- Breaks: `HeroPreview.hasPreviewableAsset` and `HeroPreview.content(for:)` switch exhaustively over `Kind` — they must gain the two cases **in this task** to keep the build green (their real treatment lands in Task 4; here they map `.embedVideo` onto the existing `YouTubeHero` path via `ref.embedURL` and `.fileVideo` onto `VideoPlayerView`, both returning `true` from `hasPreviewableAsset`).

- [ ] **Step 1: failing test.** `MediaPreviewKindTests.swift` — the precedence table (R7):

```swift
import XCTest
@testable import CicadaApp

/// R-V1 / plan R7: the URL decides, `mediaType` is a hint. Every case below
/// is a page shape that exists on a real bank today — the browser-sync path
/// stamps `bookmark` on everything it imports, and the TikTok export path
/// stamps `url`, which is exactly why dispatching on `mediaType` meant those
/// items could never play.
final class MediaPreviewKindTests: XCTestCase {
    private func model(_ url: String, _ mediaType: String) -> MediaPreviewModel {
        MediaPreviewModel(block: MediaBlock(url: url, mediaType: mediaType), title: "t")
    }

    func testALegacyBookmarkTypedVimeoPageStillPlays() {
        guard case .embedVideo(let ref) = model("https://vimeo.com/123456789", "bookmark").kind
        else { return XCTFail("expected .embedVideo") }
        XCTAssertEqual(ref.provider, .vimeo)
        XCTAssertEqual(ref.embedURL?.absoluteString, "https://player.vimeo.com/video/123456789")
    }

    func testAUrlTypedTikTokExportItemStillPlays() {
        guard case .embedVideo(let ref) = model("https://www.tiktok.com/@exampleuser/video/1234567890123456789", "url").kind
        else { return XCTFail("expected .embedVideo") }
        XCTAssertEqual(ref.provider, .tiktok)
    }

    func testAYouTubePlaylistResolvesToTheVideoseriesEmbed() {
        guard case .embedVideo(let ref) = model("https://www.youtube.com/playlist?list=PLexample01", "youtube").kind
        else { return XCTFail("expected .embedVideo") }
        XCTAssertEqual(ref.embedURL?.absoluteString,
                       "https://www.youtube-nocookie.com/embed/videoseries?list=PLexample01")
    }

    func testAYouTubeLiveURLResolves() {
        guard case .embedVideo = model("https://www.youtube.com/live/vid00000003", "youtube").kind
        else { return XCTFail("expected .embedVideo") }
    }

    func testADirectFileIsAFileVideoNotAWebsite() {
        guard case .fileVideo(let ref) = model("https://example.com/media/clip.mp4", "bookmark").kind
        else { return XCTFail("expected .fileVideo") }
        XCTAssertEqual(ref.provider, .direct)
    }

    func testALocalFileIsAFileVideo() {
        guard case .fileVideo(let ref) = model("file:///Users/example/Movies/clip.mov", "url").kind
        else { return XCTFail("expected .fileVideo") }
        XCTAssertEqual(ref.provider, .local)
    }

    func testInstagramStaysInstagramWhateverTheMediaTypeSays() {
        XCTAssertEqual(model("https://www.instagram.com/reel/Cexample01/", "bookmark").kind, .instagram)
        XCTAssertEqual(model("https://www.instagram.com/p/Cexample02/", "instagram").kind, .instagram)
    }

    func testAnExternalOnlyProviderGetsNoNewCase() {
        // R6: Twitch is recognised as a video and deliberately not played —
        // there is nothing new to offer, so it stays the website card it is.
        XCTAssertEqual(model("https://www.twitch.tv/videos/1234567890", "bookmark").kind, .website)
        XCTAssertEqual(model("https://vm.tiktok.com/ZMexample/", "url").kind, .website)
    }

    func testAYouTubeTypedPageWithNoVideoIdFallsBackToTheWebsiteCard() {
        // "Preview site" is the honest label for a channel page.
        XCTAssertEqual(model("https://www.youtube.com/@examplechannel", "youtube").kind, .website)
    }

    func testAnImageIsStillAnImage() {
        XCTAssertEqual(model("https://example.com/photo.jpg", "bookmark").kind, .image)
    }
}
```

- [ ] **Step 2: the dispatch.** Replace `MediaPreview.swift:51-65` with:

```swift
    /// The kind of preview to render.
    ///
    /// R-V1: the **URL** decides. `mediaType` is a hint consulted only after
    /// the URL has been asked, because it is not trustworthy for video: the
    /// browser-sync path stamps `bookmark` on everything it imports and the
    /// TikTok export path stamps `url`, so a page's stored type says nothing
    /// about whether it is playable. Deriving at read is also what lets every
    /// item already on a bank start playing with no bank rewrite and no
    /// `url_index.json` migration (plan R1 / R15).
    ///
    /// An `external` ref (Twitch, a TikTok shortlink) deliberately gets **no
    /// new case** — there is nothing new to offer a video we have decided not
    /// to play, so it falls through to the website card it already was (R6).
    enum Kind: Equatable { case image, embedVideo(VideoRef), fileVideo(VideoRef), instagram, website }

    /// The resolved video reference for this item's url, if any. `nil` means
    /// "not a video" — never an error, never a network call (R2).
    var videoRef: VideoRef? { VideoRef.resolve(url) }

    var kind: Kind {
        if let ref = videoRef {
            switch ref.kind {
            case .embed: return .embedVideo(ref)
            case .file:  return .fileVideo(ref)
            case .external: break   // R6 — fall through to the legacy branches
            }
        }
        if (resolvedURL?.host ?? "").contains("instagram.com") { return .instagram }
        switch mediaType.lowercased() {
        case "instagram": return .instagram
        default:
            return MediaURLHelpers.isImageURL(url) ? .image : .website
        }
    }
```

  **Delete** `MediaURLHelpers.youtubeID` / `youtubeEmbedURL` / `youtubeHeroEmbedURL` in the same edit and let the compiler prove no caller survives — after Step 5 their only two callers (`videoPlayerSheet`, `HeroPreview.YouTubeHero`) are gone, and a second YouTube id parser living beside `VideoRef` is precisely the drift R-V8 exists to prevent. `isImageURL` **stays** — `kind` still calls it. (`grep -rn "youtubeEmbedURL\|youtubeHeroEmbedURL\|youtubeID" app/CicadaApp/Sources` must return nothing afterwards. Verified: no test references them either.)

  Three file-header comments name the YouTube-only world this task ends and must be rewritten in the same edit — a stale header is the same defect as a stale docstring: `MediaPreview.swift:3-17` ("dispatching on `media_type`", the four-kind list), `WebView.swift:6-13` ("the embedded YouTube player", "the YouTube embed url DERIVED from that stored url" — still true, now via `VideoRef`, and the `file://` read scope is new), and `HeroPreview.swift:13-18` ("`MediaURLHelpers` … for the url → kind dispatch and YouTube id/embed-url extraction").

- [ ] **Step 3: the two branches.** In `MediaPreview.body`'s switch (`:132-137`) replace `case .youtube` with:

  - `case .embedVideo(let ref)`: today's thumbnail + `play.circle.fill` button (`:157-201` verbatim), but the tap opens `showVideoPlayer` when `ref.autoplayURL != nil`, else opens `ref.watchURL` externally. The channel label and `openExternallyButton` stay. `videoPlayerSheet` becomes `if let ref = model.videoRef, let playerURL = ref.autoplayURL ?? ref.embedURL { WebPreviewSheet(title: …, url: playerURL, externalURL: ref.watchURL) }` — **an `if let`, never `ref.embedURL!`**: a force-unwrap in a sheet builder turns a classification bug into a crash, and the existing `videoPlayerSheet` (`:352-360`) is already written as a conditional for exactly that reason.
  - `case .fileVideo(let ref)`: `VideoPlayerView(url: ref.watchURL).frame(maxWidth: .infinity, minHeight: 202, maxHeight: 360).clipShape(…).overlay(border)` — no sheet, a local/direct file plays in place — then the channel label if any, then `externalAffordance(for: ref)`. **Width is `maxWidth: .infinity`, not the `360` the thumbnail branches use:** R-V5 widens the Feed sheet to 720 precisely because a small player in a big sheet reads as a regression, and a player pinned to 360 would leave that widening doing nothing. Do **not** reach for `.aspectRatio(16/9, …)` here — an `NSViewRepresentable` has no intrinsic size, so the ratio would be computed from the proposal rather than from the clip; `AVPlayerView`'s `videoGravity = .resizeAspect` (Task 2) already letterboxes the real picture inside whatever box it is given, which is also what makes a portrait Shorts/TikTok clip correct-if-not-pretty (Not in scope).
  - `private func externalAffordance(for ref: VideoRef) -> some View`: for `ref.provider == .local` a **"Reveal in Finder"** button (`NSWorkspace.shared.activateFileViewerSelecting([ref.watchURL])`, `folder` symbol) — a local file's "external" is Finder, not a browser (R9) — otherwise the existing `openExternallyButton`. **"Open externally" is present on every video branch** (R-V5).

- [ ] **Step 4: `WebView` learns `file://`.** In `makeNSView` (`WebView.swift:17-25`) and `updateNSView` (`:27-33`), route through one private helper:

```swift
    /// WebKit refuses a `file://` document loaded through `URLRequest` — it
    /// needs `loadFileURL(_:allowingReadAccessTo:)` with an explicit read
    /// scope, which is why a local clip rendered as a blank frame before
    /// R-V3. Read access is granted to the file's own directory and no wider:
    /// a WebView in this app only ever loads the media entity's own url.
    private func load(_ url: URL, into webView: WKWebView) {
        if url.isFileURL {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        } else {
            webView.load(URLRequest(url: url))
        }
    }
```

- [ ] **Step 5: keep `HeroPreview` compiling.** Add the two cases to `hasPreviewableAsset` (`:39-51`, both `return true`) and to `content(for:)` (`:61-86`): `.embedVideo(let ref)` → the existing `YouTubeHero` body reading `ref.embedURL` (renamed in Task 4), `.fileVideo(let ref)` → `VideoPlayerView(url: ref.watchURL)` at `HeroPreview.maxHeight`.

- [ ] **Step 6: green + commit.**

```
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
cd <worktree>/ && grep -rn "youtubeEmbedURL\|youtubeHeroEmbedURL\|youtubeID" app/CicadaApp/Sources || echo "no survivors"
```

```
feat(app): the url decides what plays — Vimeo, TikTok, Loom, direct and local files (Track V, R-V1)
```

---

### Task 4: The surfaces — heroes, the Feed row badge, the video-sized sheet (R-V5)

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/HeroPreview.swift:39-51, 61-86, 91-144`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift:314, 319-338, 399`
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift:544-594, 699-753`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:197-299`
- Create: `app/CicadaApp/Tests/CicadaAppTests/FeedVideoRowTests.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/MediaBlockDecodeTests.swift`

**Interfaces:**
- Produces: `EmbedVideoHero(ref:model:)`, `FileVideoHero(ref:)` (both `private` in `HeroPreview.swift`); `enum FeedPreviewLayout { static func sheetSize(for kind: MediaPreviewModel.Kind) -> CGSize }`; `MediaBlock.provider: String?` / `.durationS: Int?`; `MediaFeedItem.provider: String?` / `.durationS: Int?`.
- Consumes: `VideoRef`, `VideoPlayerView`, `MediaPreviewModel.Kind`.

- [ ] **Step 1: failing tests.**

```swift
// app/CicadaApp/Tests/CicadaAppTests/FeedVideoRowTests.swift
import XCTest
@testable import CicadaApp

/// R-V5: the Feed row says an item is a video before you open it, and the
/// preview sheet is big enough to be a player. Both are pure functions so
/// they are tested without a view.
final class FeedVideoRowTests: XCTestCase {
    private func kind(_ url: String) -> MediaPreviewModel.Kind {
        MediaPreviewModel(block: MediaBlock(url: url, mediaType: "bookmark"), title: "t").kind
    }

    func testTheBadgeShowsForPlayableRefsOnly() {
        // R14/R6: the badge means "this plays"; an external-only provider gets
        // no badge because tapping it would not play anything.
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://example.com/media/clip.mp4")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.isPlayable, false)
        XCTAssertNil(VideoRef.resolve("https://example.com/articles/how-to-example"))
    }

    func testTheSheetGrowsForVideoKindsOnly() {
        // 480x270 inside a 480x520 sheet reads as a regression, not a player.
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://vimeo.com/123456789")),
                       CGSize(width: 720, height: 560))
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://example.com/media/clip.mp4")),
                       CGSize(width: 720, height: 560))
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://example.com/articles/how-to-example")),
                       CGSize(width: 480, height: 520))
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://example.com/photo.jpg")),
                       CGSize(width: 480, height: 520))
    }
}
```

```swift
// app/CicadaApp/Tests/CicadaAppTests/MediaBlockDecodeTests.swift
import XCTest
@testable import CicadaApp

/// Plan R16: the client decodes the two new keys BEFORE the backend produces
/// them, and absence is the test — an older backend (or any non-video page)
/// must decode with neither key present.
final class MediaBlockDecodeTests: XCTestCase {
    func testMediaBlockDecodesWithoutTheNewKeys() throws {
        let json = #"{"url":"https://example.com/a","mediaType":"bookmark"}"#
        let block = try JSONDecoder().decode(MediaBlock.self, from: Data(json.utf8))
        XCTAssertNil(block.provider)
        XCTAssertNil(block.durationS)
    }

    func testMediaBlockDecodesWithTheNewKeys() throws {
        let json = #"{"url":"https://vimeo.com/123456789","mediaType":"url","provider":"vimeo","durationS":95}"#
        let block = try JSONDecoder().decode(MediaBlock.self, from: Data(json.utf8))
        XCTAssertEqual(block.provider, "vimeo")
        XCTAssertEqual(block.durationS, 95)
    }

    func testMediaFeedItemDecodesWithoutTheNewKeys() throws {
        let json = #"{"mediaEntityId":"media-a","url":"https://example.com/a","title":"A","mediaType":"url"}"#
        let item = try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
        XCTAssertNil(item.provider)
        XCTAssertNil(item.durationS)
    }

    func testTheRawFrontmatterFallbackReadsTheNewKeys() throws {
        // The backend may not surface the nested block; Entity rebuilds it
        // from rawMarkdown (Entity.swift:703) and must not drop the keys.
        let raw = """
        ---
        name: A clip
        type: media
        media:
          url: https://www.loom.com/share/abc123def4567890abc123def4567890
          media_type: url
          provider: loom
          duration_s: 421
        ---
        body
        """
        let block = try XCTUnwrap(Entity.parseMediaFrontmatter(raw))
        XCTAssertEqual(block.provider, "loom")
        XCTAssertEqual(block.durationS, 421)
    }
}
```

- [ ] **Step 2: `HeroPreview`.** Rename `YouTubeHero` → `EmbedVideoHero(ref: VideoRef, model: MediaPreviewModel)`; its body loads `WebView(url: ref.embedURL)` — **never `autoplayURL`**: the hero renders on every page visit, so autoplaying would be surprising, and that rule (`MediaPreview.swift:92-97`) is exactly what generalizes here (R11). The `thumbnailFallback` branch is unreachable for a resolved embed ref, so replace it with an `if let embedURL = ref.embedURL … else { thumbnailFallback }` that keeps the existing fallback for a defensive `nil`. Add `FileVideoHero(ref:)` — `VideoPlayerView(url: ref.watchURL)` at `HeroPreview.maxHeight`, same corner radius and border as the other heroes, **paused** (the controller starts paused by construction). `hasPreviewableAsset` returns `true` for both new cases: a `fileVideo` whose file is missing still renders the "can't read this file" card, which is worth the slot for the same reason `LocationHero` always is (`HeroPreview.swift:34-38`).

  **Disclosed, not fixed — a media entity page renders BOTH surfaces.** `EntityDetailCard.contentTab` renders `MediaPreview` at `:333-340` *and*, inside `renderedMarkdownView`, `HeroPreview` at `:841-843`; they are siblings in one `VStack`, so a `media` entity already shows the preview card and the hero together (today: a YouTube thumbnail card above a hero embed). After this task that becomes **two players for the same clip on one page** — two `AVPlayer`s for a `.fileVideo`, two `WKWebView`s for an `.embedVideo`. Acceptable for this slice on two grounds, both worth stating rather than discovering: `AVPlaybackController` constructs its player **paused** (`AVPlayer(url:)` prerolls but does not stream until `play()`), and the embed hero never autoplays (R11), so neither duplicate starts on its own. Collapsing the two surfaces is a `EntityDetailCard` layout decision that predates this track and belongs to whoever takes it — **do not fold it in here**; verification step 5 eyeballs the page so the duplication is seen, not assumed.

- [ ] **Step 3: the Feed row badge.** In `FeedRow.thumbnail` (`FeedView.swift:319-338`) wrap the 44×44 image in a `ZStack(alignment: .bottomTrailing)` and overlay, when `VideoRef.resolve(item.url)?.isPlayable == true`, a `play.fill` glyph (`CicadaTheme.font(size: 9)`, white, in a 16×16 `Circle().fill(.black.opacity(0.55))`) plus, when `VideoRef.durationLabel(item.durationS)` is non-nil, that label as a small capsule under the title's meta row (R17: nothing renders when the provider gave no duration). **`item.durationS` lands in Step 5 of this task** — do Step 5 first if you want the tree to build between steps; the task is one commit either way. Free win: `ChannelSourceView` reuses `FeedRow` (`FeedView.swift:256-258`), so the Sources page gets the badge too.

- [ ] **Step 4: the video-sized sheet.** Add above `FeedItemPreviewSheet`:

```swift
/// R-V5: a 480 × 270 player inside a 480 × 520 sheet reads as a regression,
/// not as a player. A pure function so the size is testable without a view.
enum FeedPreviewLayout {
    static func sheetSize(for kind: MediaPreviewModel.Kind) -> CGSize {
        switch kind {
        case .embedVideo, .fileVideo: return CGSize(width: 720, height: 560)
        case .image, .instagram, .website: return CGSize(width: 480, height: 520)
        }
    }
}
```

  and replace `FeedView.swift:399` with `.frame(width: size.width, height: size.height)` where `private var size: CGSize { FeedPreviewLayout.sheetSize(for: previewModel.kind) }`.

- [ ] **Step 5: the two new client fields (R16).** `MediaBlock`: add `var provider: String?` and `var durationS: Int?`, add them to `CodingKeys` (`Entity.swift:562`), to the memberwise `init` with `nil` defaults (`:566-578`), to `init(from:)` via `decodeIfPresent` (`:580-589`), and to `parseMediaFrontmatter`'s return (`:744-752`) reading `fields["provider"]` and `Int(fields["duration_s"] ?? "")`. `MediaFeedItem`: add `let provider: String?` / `let durationS: Int?`, the two `CodingKeys` cases (`APIClient.swift:270-276`) and two `decodeIfPresent` lines (after `:297`). Docstrings cite R-V2 and say plainly: **`provider` is redundant with what `VideoRef` derives and is carried only so a non-Swift reader of the wire can see it; `durationS` is the one thing a URL cannot tell you.**

- [ ] **Step 6: green + commit.**

```
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
```

```
feat(app): video on every surface — heroes, the Feed play badge, a player-sized sheet (Track V, R-V5)
```

---

### Task 5: The backend slice — `video` classification, oEmbed for three providers, the content-type guard (R-V2, R-V7)

**Files:**
- Modify: `api/services/media_ingestor.py:34-35` (new caps), `:93-100` (`MediaMeta`), `:178-188` (`_classify`), `:213-236` (`enrich`), after `:251` (new `_enrich_oembed`), `:254-262` (`_enrich_opengraph`), `:1517-1527` (`write_media_entity`)
- Modify: `api/models/schemas.py:383-401`, `:1518-1555`
- Modify: `api/routers/entities.py:163-195`
- Modify: `api/routers/sources.py:539-568`
- Create: `api/tests/test_video_enrichment.py`

**Interfaces:**
- Produces: `MediaMeta.provider: str | None = None`, `MediaMeta.duration_s: int | None = None`; `_enrich_oembed(provider, url, client, fallback) -> MediaMeta`; `_classify(...) -> "video"` for direct/local files; `EntityMedia.provider/duration_s`; `MediaSourceItem.provider/duration_s` (wire `provider`, `durationS`).
- Consumes: `api.services.video_urls` (Task 1).
- **Untouched on purpose:** `normalize_url` / `_youtube_video_id` (R18), `_enrich_youtube` (R12), `url_index.json`'s entry shape (R15), every ETag input.

- [ ] **Step 1: failing tests.** `api/tests/test_video_enrichment.py`:

```python
"""Video-aware ingest: classification, enrichment and the guards (Track V).

No network anywhere — ``enrich`` takes an injected client (media_ingestor.py:213)
and every test here hands it a fake. The point of several of these tests is that
the fake is **never called**: a direct video file must not be fetched at all
(R-V2 + the ``_excluded_media`` hook that already existed), and a non-HTML body
must never reach BeautifulSoup (R13). Same shape as
``test_sources.py::test_ingest_linkedin_saved_performs_zero_http_calls``, which
proves a ToS short-circuit by watching the call list rather than by patching
``enrich`` away.
"""
from __future__ import annotations

import asyncio
import json

from api.services import link_enrichment, media_ingestor
from api.services.media_ingestor import MediaMeta, RawItem


def run(coro):
    # The house pattern (``test_sources.py:31-32``). NOT
    # ``get_event_loop().run_until_complete`` — that is deprecated on the
    # suite's Python 3.12 and leaves an unclosed loop behind for every later
    # test in the process.
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, payload=None, *, text=None, headers=None):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response=None, *, raises=None):
        self.response = response
        self.raises = raises
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if self.raises:
            raise self.raises
        return self.response


# --- classification (R14) ---------------------------------------------------


def test_a_direct_video_file_classifies_as_video():
    assert media_ingestor._classify("https://example.com/media/clip.mp4") == "video"
    assert media_ingestor._classify("https://example.com/media/stream.m3u8") == "video"
    # Even from a bookmark file: the extension is the stronger signal.
    assert media_ingestor._classify("https://example.com/media/clip.mov", True) == "video"
    assert media_ingestor._classify("file:///Users/example/Movies/clip.mov") == "video"


def test_a_provider_url_keeps_its_old_media_type():
    # R-V2: one new value only. Vimeo/TikTok/Loom carry `media.provider`
    # instead, because each media_type value lands in the page's tags and in
    # the /sources wire shape.
    assert media_ingestor._classify("https://vimeo.com/123456789") == "url"
    assert media_ingestor._classify("https://vimeo.com/123456789", True) == "bookmark"
    assert media_ingestor._classify("https://www.youtube.com/watch?v=vid00000001") == "youtube"
    assert media_ingestor._classify("https://www.instagram.com/reel/Cexample01/") == "instagram"


def test_video_is_already_excluded_from_nightly_link_enrichment():
    # The hook existed with no producer (link_enrichment.py:194) — this closes
    # the loop so a saved .mp4 can never be fetched by the backfill.
    assert link_enrichment._excluded_media("https://example.com/media/clip.mp4", "video") is True


# --- enrich: the file short-circuit -----------------------------------------


def test_a_direct_file_never_touches_the_network():
    client = FakeClient(FakeResponse({}))
    meta = run(media_ingestor.enrich("https://example.com/media/clip.mp4", client))
    assert client.calls == []          # the whole point
    assert meta.media_type == "video"
    assert meta.provider == "direct"
    assert meta.duration_s is None     # R17 — absent means absent


# --- enrich: oEmbed for the three new providers (R12) -----------------------


def test_vimeo_oembed_reads_fields_only():
    client = FakeClient(FakeResponse({
        "title": "A clip", "author_name": "Example Studio",
        "thumbnail_url": "https://example.com/t.jpg", "duration": 95,
        "html": "<iframe src='https://player.vimeo.com/video/123456789'></iframe>",
    }))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert meta.title == "A clip"
    assert meta.channel == "Example Studio"
    assert meta.thumbnail == "https://example.com/t.jpg"
    assert meta.duration_s == 95
    assert meta.provider == "vimeo"
    assert client.calls == ["https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fvimeo.com%2F123456789"]


def test_tiktok_and_loom_use_their_own_endpoints():
    for url, endpoint_host, provider in [
        ("https://www.tiktok.com/@exampleuser/video/1234567890123456789", "www.tiktok.com", "tiktok"),
        ("https://www.loom.com/share/abc123def4567890abc123def4567890", "www.loom.com", "loom"),
    ]:
        client = FakeClient(FakeResponse({"title": "T"}))
        meta = run(media_ingestor.enrich(url, client))
        assert meta.provider == provider
        assert endpoint_host in client.calls[0]


def test_an_oembed_failure_degrades_to_url_only_and_keeps_the_provider():
    client = FakeClient(None, raises=RuntimeError("offline"))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert meta.title == media_ingestor._fallback_title("https://vimeo.com/123456789")
    assert meta.provider == "vimeo"        # url-derived, so free even offline
    assert meta.media_type == "url"


def test_an_oversized_oembed_body_is_refused():
    client = FakeClient(FakeResponse(text="x" * (media_ingestor._OEMBED_MAX_BYTES + 1)))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert meta.title == media_ingestor._fallback_title("https://vimeo.com/123456789")


def test_a_duration_that_is_not_a_positive_int_is_dropped():
    for bad in [None, 0, -3, "95", "n/a"]:
        client = FakeClient(FakeResponse({"title": "T", "duration": bad}))
        meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
        assert meta.duration_s is None, bad


# --- the OG content-type guard (R13) ----------------------------------------


def test_opengraph_skips_a_non_text_body():
    client = FakeClient(FakeResponse(text="<html>", headers={"content-type": "video/mp4"}))
    fallback = MediaMeta(title="f", site="example.com")
    meta = run(media_ingestor._enrich_opengraph("https://example.com/x", client, fallback))
    assert meta is fallback or meta.title == "f"


def test_opengraph_still_runs_when_no_content_type_header_is_present():
    # R13: a guard that fired on ABSENCE would silently regress every fetch
    # whose server omits the header.
    html = "<html><head><meta property='og:title' content='Real title'></head></html>"
    client = FakeClient(FakeResponse(text=html, headers={}))
    fallback = MediaMeta(title="f", site="example.com")
    meta = run(media_ingestor._enrich_opengraph("https://example.com/x", client, fallback))
    assert meta.title == "Real title"


def test_opengraph_carries_the_url_derived_provider_through_a_successful_fetch():
    # A recognised-but-external provider (Twitch) still reaches _enrich_opengraph.
    # `provider` is URL-derived, so it must survive the SUCCESS path too — not
    # only the failure fallback, which would make the key mean "the fetch broke".
    html = "<html><head><meta property='og:title' content='A stream'></head></html>"
    client = FakeClient(FakeResponse(text=html, headers={"content-type": "text/html"}))
    meta = run(media_ingestor.enrich("https://www.twitch.tv/videos/1234567890", client))
    assert meta.provider == "twitch"
    assert meta.title == "A stream"
    assert meta.duration_s is None      # R17 — an OG page never states one


# --- the TikTok export path (brief item 5) ----------------------------------


def test_a_tiktok_export_item_enriches_through_oembed_not_opengraph():
    # parse_upload routes a TikTok export with from_bookmark_file=False
    # (media_ingestor.py:1074-1090), so every item used to fall to
    # _enrich_opengraph and land on TikTok's consent wall. Dispatching on the
    # URL's provider fixes it for the export path and the paste path alike.
    client = FakeClient(FakeResponse({"title": "A tiktok", "author_name": "@exampleuser"}))
    meta = run(media_ingestor.enrich(
        "https://www.tiktok.com/@exampleuser/video/1234567890123456789", client,
        from_bookmark_file=False))
    assert meta.title == "A tiktok"
    assert "tiktok.com/oembed" in client.calls[0]


# --- write + wire (R15) -----------------------------------------------------


def test_write_media_entity_omits_the_keys_when_absent(tmp_path):
    from api.services import markdown_parser
    media_ingestor.write_media_entity(
        tmp_path, "media-a", RawItem(url="https://example.com/a"),
        MediaMeta(title="A", site="example.com"), "ep_2026-09-05_001")
    fm = markdown_parser.parse(tmp_path / "media-a.md").frontmatter
    assert "provider" not in fm["media"]
    assert "duration_s" not in fm["media"]


def test_write_media_entity_writes_the_keys_when_present(tmp_path):
    from api.services import markdown_parser
    media_ingestor.write_media_entity(
        tmp_path, "media-b", RawItem(url="https://vimeo.com/123456789"),
        MediaMeta(title="B", site="vimeo.com", provider="vimeo", duration_s=95),
        "ep_2026-09-05_002")
    fm = markdown_parser.parse(tmp_path / "media-b.md").frontmatter
    assert fm["media"]["provider"] == "vimeo"
    assert fm["media"]["duration_s"] == 95
```

- [ ] **Step 2: implement.**

  0. `media_ingestor.py:30` — extend the existing import to
     `from api.services import decay_policy, episode_ids, markdown_parser, saved_at, video_urls`.
     No cycle: `video_urls` imports nothing from `api`.

  1. `media_ingestor.py:35` — add below `_MAX_READ`:

```python
# oEmbed calls take the rail's own numbers, not `_TIMEOUT`'s looser 5.0 s
# (R-V4: 4 s / ≤512 KB / no cookies). The cap is enforced by slicing the
# decoded body and refusing an over-cap response rather than by streaming,
# because `enrich` takes an INJECTED client (media_ingestor.py:213) and a
# streaming contract would force every existing fake to grow one.
# The cap is applied to the DECODED body (``resp.text``), i.e. characters, not
# wire bytes: ``enrich`` takes an injected client and a byte-exact streaming
# contract would force every existing fake to grow one. An oEmbed response is
# ASCII-ish JSON of a few hundred bytes, so the two numbers coincide in
# practice — this is a runaway guard, not accounting.
_OEMBED_TIMEOUT = 4.0
_OEMBED_MAX_BYTES = 512_000
```

  2. `MediaMeta` (`:93-100`) — add `provider: str | None = None` and `duration_s: int | None = None`, with a comment saying `provider` is URL-derived (so it is set even offline) while `duration_s` only ever comes from a provider's oEmbed.

  3. `_classify` (`:178-188`) — insert the file check **after** the instagram/linkedin host checks and **before** the `from_bookmark_file` fallback, exactly in R14's order, with the docstring naming why `video` is the only new value.

```python
    # R-V2: the one new media_type, and only for a direct/local FILE. A
    # provider URL keeps `url`/`bookmark` and carries `media.provider`
    # instead — each media_type value lands in the page's tags
    # (write_media_entity, below) and in the `/sources` wire shape, so each
    # one costs. `video` earns its place because
    # `link_enrichment._excluded_media` already accepts it (link_enrichment
    # .py:194): classifying a direct file as `video` stops the nightly
    # enrichment fetching a binary, with no edit to that module.
    if video_urls.is_direct_file(url):
        return "video"
```

  4. `enrich` (`:213-236`) — resolve once, stamp the provider on the fallback, short-circuit files, and add the oEmbed branch after linkedin:

```python
    ref = video_urls.resolve(url)
    media_type = _classify(url, from_bookmark_file=from_bookmark_file)
    site = _site_of(url)
    fallback = MediaMeta(
        title=_fallback_title(url), description="", site=site,
        media_type=media_type, provider=(ref.provider if ref else None),
    )

    try:
        if ref is not None and ref.kind == "file":
            # A direct video file has no page to read. Fetching it would
            # download up to 1.5 MB of binary and hand it to BeautifulSoup
            # (the defect `_enrich_opengraph`'s new content-type guard also
            # closes) — so the client is never touched at all.
            return fallback
        if media_type == "youtube":
            meta = await _enrich_youtube(url, client, fallback)
            meta.provider = meta.provider or fallback.provider
            return meta
        if media_type == "instagram":
            return fallback          # unchanged — login-walled, never scraped
        if media_type == "linkedin":
            return fallback          # unchanged — ToS-walled (G69 §8.2)
        if ref is not None and ref.provider in video_urls.OEMBED_PROVIDERS:
            return await _enrich_oembed(ref.provider, url, client, fallback)
        return await _enrich_opengraph(url, client, fallback)
    except Exception as e:
        logger.debug(f"Enrichment failed for {url}: {type(e).__name__}: {e}")
        return fallback
```

  Why the youtube branch stamps the provider in `enrich` rather than inside `_enrich_youtube`: R12 keeps that function's shape untouched so every existing fake for it keeps working. `MediaMeta` is a plain `@dataclass` (`media_ingestor.py:93`), so the field is assignable after the call. (Verified: no test in `api/tests` compares a `_enrich_youtube` or `_enrich_opengraph` result for dataclass equality, so this is safe either way — the assignment is the smaller diff.)

  5. `_enrich_oembed` — new, immediately after `_enrich_youtube`:

```python
_OEMBED_ENDPOINTS = {
    "vimeo": "https://vimeo.com/api/oembed.json?url={url}",
    "tiktok": "https://www.tiktok.com/oembed?url={url}",
    "loom": "https://www.loom.com/v1/oembed?url={url}",
}


async def _enrich_oembed(provider: str, url: str, client, fallback: MediaMeta) -> MediaMeta:
    """One keyless-oEmbed reader for Vimeo / TikTok / Loom (R-V7).

    Modelled on ``_enrich_youtube`` and bound by the same rail (R-V4): it
    reads the response's FIELDS — ``title``, ``author_name``,
    ``thumbnail_url``, ``duration`` — and **never its ``html`` blob. The
    player URL is derived from the id ourselves (``video_urls.resolve``),
    which is exactly what the shipped YouTube path already does; parsing or
    injecting a provider's returned markup would be the first time this app
    executed third-party HTML it assembled.

    No cookies, no ``Authorization``, 4 s, and an explicit 512 KB refusal —
    the rail's own numbers rather than ``_TIMEOUT``'s looser 5 s. Any failure
    (including a 401/403/407/451, which is **never retried with different
    headers**) raises into ``enrich``'s single ``except`` and degrades to the
    URL-only fallback, which still carries the URL-derived ``provider``.
    """
    from urllib.parse import quote

    endpoint = _OEMBED_ENDPOINTS[provider].format(url=quote(url, safe=""))
    resp = await client.get(endpoint, timeout=_OEMBED_TIMEOUT)
    resp.raise_for_status()
    raw = (resp.text or "")[: _OEMBED_MAX_BYTES + 1]
    if len(raw) > _OEMBED_MAX_BYTES:
        raise ValueError(f"{provider} oembed body over the 512 KB cap")
    data = json.loads(raw)

    duration = data.get("duration")
    # R17: a duration is shown only when a provider GAVE one. A string, a
    # zero or a negative is not a duration — it is a missing one.
    duration_s = duration if isinstance(duration, int) and duration > 0 else None

    return MediaMeta(
        title=data.get("title") or fallback.title,
        description="",
        site=fallback.site,
        channel=data.get("author_name") or None,
        thumbnail=data.get("thumbnail_url") or None,
        media_type=fallback.media_type,
        provider=provider,
        duration_s=duration_s,
    )
```

  6. `_enrich_opengraph` (`:254-292`) — insert the guard right after `raise_for_status()` (`:261`):

```python
    # R13 / R-V7: mirror `link_enrichment.default_fetch`'s guard
    # (link_enrichment.py:588-590) — the two fetch paths disagreed, and this
    # one would download up to 1.5 MB of a binary body and hand it to
    # BeautifulSoup. A response with NO content-type proceeds, exactly as
    # before: a guard that fired on the header's absence would turn working
    # fetches into fallbacks.
    ctype = (getattr(resp, "headers", {}) or {}).get("content-type", "").lower()
    if ctype and "html" not in ctype and "text" not in ctype:
        return fallback
```

  and add `provider=fallback.provider` to the `MediaMeta(...)` this function RETURNS (`:285-292`). Without it the success path silently drops a provider the fallback path keeps — a Twitch or shortlink page would carry `media.provider` only when the fetch *failed*, which contradicts `MediaMeta`'s own "URL-derived, so it is set even offline" comment. `duration_s` is deliberately NOT set here: an OG page never states one (R17).

  7. `write_media_entity` (`:1517-1527`) — after the existing keys:

```python
    # R15: written only when set, so a plain bookmark's frontmatter is
    # byte-identical to what it was. `provider` is URL-derivable and is
    # recorded for a non-Swift reader of the page; `duration_s` is the one
    # thing a URL cannot tell you.
    if meta.provider:
        frontmatter["media"]["provider"] = meta.provider
    if meta.duration_s:
        frontmatter["media"]["duration_s"] = meta.duration_s
```

  8. `schemas.py` — `EntityMedia` and `MediaSourceItem` each gain `provider: Optional[str] = None` and `duration_s: Optional[int] = None`, with a docstring line: additive + defaulted, **no ETag input changes** (`/sources` still ETags over the same files), so the ship-together rule is satisfied by there being nothing to ship.

  9. `entities.py:_build_media_block` — read both from the `media` dict (`provider=media.get("provider") or None`, `duration_s=media.get("duration_s") if isinstance(media.get("duration_s"), int) else None`).

  10. `sources.py:539-544` — inside the existing `media` dict read that already recovers `site`/`channel`, add `provider` and `duration_s` locals, and pass them to the `MediaSourceItem(...)` construction at `:547-568`. **Do not touch the list filter** — that is Track P's edit.

- [ ] **Step 3: green.**

```
cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_video_enrichment.py api/tests/test_video_urls.py api/tests/test_sources.py api/tests/test_entity_media.py api/tests/test_link_enrichment.py -q -p no:cacheprovider
cd <worktree>/ && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
```

Full suite must be 0 failures (2119 + the new cases). Commit:

```
feat(api): video classification, oEmbed for Vimeo/TikTok/Loom, and a content-type guard on the OG fetch (Track V, R-V2/R-V7)
```

---

### Task 6: Docs — the G11 video paragraph, the ToS lines, the queued follow-ups

**Files:**
- Modify: `docs/goals/memory-evolution.md` (row **G11** at `:479`; a pointer inside **G22** at `:497`)
- Modify: `CLAUDE.md` (§ "Reaching the outside world"; one sentence in § Companion App)
- Modify: `docs/goals/TODO.md` (Shipped entry + the named follow-ups)

- [ ] **Step 1: G11.** Append a **"preview half — video (2026-09-05)"** paragraph to the row. It must carry (a) the rule — *the provider is derived at read time from the stored URL, never written into a bank*, with the reason (no whole-bank rewrite, and `GET /sources` reads `media_type` from `url_index.json` while the page carries the rest, so a write-time reclassification is a split-brain risk); (b) the surfaces table — Feed row (play badge, reused by the Sources page), Feed sheet (720 × 560 for video kinds), entity Content tab, entity hero (`EmbedVideoHero` / `FileVideoHero`, never autoplaying); (c) the ToS rail as it applies here — official players only, oEmbed *fields* only, **never a derived stream**, Twitch/X/Instagram external with the reason each; (d) the two named follow-ups: **`/live/` in `normalize_url` needs a `url_index.json` dedup migration** (R18) and **Dailymotion/Reddit embeds are mechanical once the table exists**. Placeholders only — no real URL, no bank content.

- [ ] **Step 2: G22 pointer.** One clause in the existing row: *the 2026-09-05 renderer is G11's preview half and moves this row not at all — transcripts/captions as the entity body remain the open work.* Nothing else in G22 changes (R19).

- [ ] **Step 3: `CLAUDE.md`.** Two lines at the end of § "Reaching the outside world":

```
**Video (Track V, 2026-09-05).** Only a provider's own player URL is ever loaded — YouTube
(`youtube-nocookie.com/embed/…`, incl. `videoseries?list=`), Vimeo, TikTok and Loom — and an
oEmbed response is read for its *fields* only, never its `html` blob: the player URL is derived
from the id by `video_urls.resolve` / `VideoRef`, so nothing a provider returns is ever executed.
**A stream is never derived** — no `yt-dlp`, no CDN or `.m3u8` URL lifted out of a page — so a
direct file the app plays is one the *user* saved as a direct URL. Twitch stays external (its
player validates `parent` against the real embedding origin; synthesising one is circumvention),
X and Instagram stay external. The app itself makes **no** network call to classify: oEmbed runs
only on the ingest/enrich path, under the gates that path already has.
```

  And one sentence in § Companion App: video plays in the Feed sheet, the entity Content tab and the entity hero through `MediaPreview`/`HeroPreview`; the provider is derived from the URL at read time (R-V1), so a bank never needs rewriting to teach the app a new one.

- [ ] **Step 4: `TODO.md`.** A Shipped entry (Track V — in-app video, PR #TBD), and under "Known and disclosed" the two follow-ups by name: the `/live/` normaliser + dedup-index migration, and Twitch/X playback with the blocker each waits on. Privacy rule throughout.

- [ ] **Step 5: commit.**

```
docs: in-app video — the G11 preview half, the ToS lines, the queued follow-ups (Track V)
```

---

## Not in scope

- **Twitch, X and Instagram playback** — each blocked for a stated reason (parent-origin validation; no first-party player URL and no thumbnail in its oEmbed, so playing one would mean executing `widgets.js` we assembled; login-walled). They stay external opens.
- **Transcripts / captions as the entity body (G22).** This is G11's preview half and closes nothing of G22 (R19).
- **`normalize_url` / `_youtube_video_id` learning `/live/`** — it changes `url_hash` and needs a `url_index.json` dedup migration (R18). Queued, not attempted.
- **Dailymotion and Reddit embeds** — mechanical once the table exists, but neither endpoint was probed; adding an unverified endpoint to a ToS-bound path is the wrong trade.
- **`url_index.json` gaining `provider`/`duration_s`** (R15) and any bank migration stamping providers onto existing pages.
- **Portrait framing for Shorts / TikTok.** A 16:9 frame letterboxes a portrait video, which is correct if not pretty; changing the frame's aspect per provider is a per-surface layout decision, not part of "it plays".
- **A play glyph on an Ask citation chip**, and any player inside the Inbox cause pane — the cause pane is a *quote* with recomputed offsets, not a media surface; putting a network-loading iframe inside a decision card is the wrong place for one.
- **A "watch video" agent skill**, hover previews on graph refs, and media-inside-transclusion (G11's artifacts-as-memories half).
- **Local-video *ingestion*** (a folder watcher, `local_refs` bodies as a media surface). A local clip reaches the app today only as a `media` entity whose stored URL is a `file://` URL; that is what R9 covers.
- Anything under `Views/Sleep/*`, `Views/Sources/*`, `OriginIconography`, `LogoImage`, `OriginMark`, or `sources.py`'s list filter (other tracks).

---

## Verification the orchestrator runs

1. `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0 failures** (baseline 2119 passed). If `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the only red, re-run it alone and report both results.
2. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20` → build succeeds, **0 failures**.
3. Drift check — the fixture is the contract:
   `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_video_urls.py -q -p no:cacheprovider && cd app/CicadaApp && swift test --filter VideoRefTests 2>&1 | tail -5` → both green over the same file.
4. Seam check: `cd <worktree>/ && rg -n "import AVKit|import AVFoundation" app/CicadaApp/Sources` → exactly two files (`AVPlaybackController.swift`, `WalkthroughPanel.swift`).
5. On the live app (the orchestrator installs at the end): save a YouTube link, a Vimeo link and a direct `.mp4`; each plays in the Feed sheet **and** in the entity hero, and the Feed row shows a play badge. A YouTube `/live/` URL and a playlist URL now play where they previously opened the browser. On the entity page, confirm the known double surface (`MediaPreview` card + hero, `EntityDetailCard.swift:333` and `:841`) renders **two paused players, neither starting on its own** — the disclosed consequence in Task 4 Step 2, not a regression to fix here.
6. Save a `file:///…/clip.mov` that exists → it plays inline with transport controls and **space toggles play**; then save a `file://` path that does not exist → the card names the path and offers Reveal in Finder, **never a black rectangle**.
7. Codec reality check (the manual half of R8, stated rather than mocked): the `.mp4` and the local `.mov` actually decode and show a picture. A green unit suite proves the dispatch, not the codec.
8. `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" 'localhost:8000/sources?limit=3' | head -c 400` → items still decode; a newly-saved Vimeo item carries `"provider":"vimeo"`, and the response's `ETag` behaviour is unchanged (a second call with `If-None-Match` still 304s).
