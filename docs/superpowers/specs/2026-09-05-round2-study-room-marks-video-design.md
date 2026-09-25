# Round 2 (2026-09-05, evening) — the study room, real marks, in-app video, Sources v2, polish

**Owner brief (Rodrigo 2026-09-05):** "review the open tickets and those that were done not long
ago, such as the sleep page rework and the sources page also. I think they can be improved by a wide
margin. Even the Chrome logo is wonky — it's not the real logo. You can use opus, spawn the
necessary amount of agents, and tell them how to implement the stuff. Work on the other things that
might make the app better, such as an in-app video renderer, a more cute sleep page like this one
[reference image: pixel bookworm reading in a cozy room, moon window, speech bubble, big
'episodes waiting' count with a progress bar, stat tiles, a 'How Cicada sleeps' icon strip, a
queue card with schedule rows, a right column of memory sources with sparklines and recent
consolidations with badges]."

**Method for this round:** six opus readers mapped the Sleep data, the pixel-art system, the logo
pipeline, the video path, the Sources page and the recent-work rough edges; three designers proposed
Sleep pages from different angles (faithful / alive / honest-minimal) and two judges scored them.
The verdict split — *alive* for delight, *honest-minimal* for truth — and this spec is the synthesis:
**the reference's layout and warmth, every pixel that moves naming its field, every number naming
its source.** The reports live in the session scratchpad (`phase1/*.md`); their conclusions that
matter are restated here so the spec stands alone.

Tracks: **A** the study room (Sleep v3) · **L** real marks · **V** in-app video · **P** polish and
truth · **S** Sources v2 (after A and L). A, L, V and P run in parallel worktrees; S starts when A
(the `activity` field) and L (the marks) have merged.

---

## Track A — the study room (Sleep page v3)

### What the data can honestly back (from the sleep-data reader)

Backed today with no backend work: the hero count (`SleepDebt.unprocessed_count`), the bubble
(`sleepBubbleText`), per-source queue rows with oldest age and the live read/total countdown
(`studyRows` over `queue_by_origin`/`read_by_origin`, both on the SSE `sleep` event), the next-run
line for all four schedule modes, and the consolidation history with counts and a measured,
telemetry-joined duration. `SleepState.stage` is the index of the *completed* stage, so the in-flight
stage is `stage + 1`; only Stage 1 has a sub-percentage.

**No honest source exists for:** "42 clusters" (nothing detects clusters; the Clusters page is entity
type groups, and `Copy.clusterCount` already forbids the word), "87 insights" (a forecast), "~3 min
est. time" (G107 defers estimates on G74's trigger — binding), and "Confidence 0.92" badges (no
field anywhere). The reference's bare 68% bar is its one real lie: the two real percentages
(Rested %, Stage-1 Progress %) mean opposite things.

### Rulings (R-A1 … R-A16)

- **R-A1 Layout.** Two columns at ≥ 1000 pt of content width — left (≈ 2/3): hero card, stage
  strip, queue card; right: Memory sources, Recent consolidations. Below 1000 pt the right column
  stacks under the left. Header subtitle becomes "Fold what's waiting into the graph." The `?`
  button and `TopBarControls` are untouched by this track.
- **R-A2 The scene.** The hero card has a fixed height so idle → running → idle never reflows. It is
  a pixel room composed on **one cell lattice at the worm's own snapped point size**: a window
  (crescent moon + static stars, night), a cushion under the worm, a mug, a potted plant, a desk
  lamp, and the worm in `reading` (or `sleeping` while a cycle runs, `happy` when caught up) with a
  **nightcap baked into the `sleeping` and `reading` frames** (rows 0–4, tassel on the left so the
  sleeping `z` glyphs don't collide; no new palette key). **The real `BookPileView` is the scene's
  book stack** — placed on the desk beside the worm — and there are no decorative books anywhere on
  the page: the page's one chart is a pile of books, so nothing that is not the chart may look like
  one. Infra: a `PixelRenderer` (`image(grid:gridSize:pointSize:palette:)`, its own `sceneCache`)
  with `BookwormRenderer` kept as a thin facade so every existing Bookworm test passes byte-for-byte;
  a separate `DeskPalette` (no collision with the theme-hex lint; the nine-key worm palette test
  stays); the scene is `.accessibilityHidden(true)` and `.allowsHitTesting(false)`.
- **R-A3 The lamp is the schedule.** Lit when `ScheduleConfig.mode != manual`, dark when manual —
  the page's cheapest honesty win: a fresh install defaults to manual and never runs Sleep. Art
  encodes **state, never quantity**, and every art bit has a text twin (the schedule row, R-A9).
- **R-A4 The hero readout.** A big count with a qualifier chip (`overdue` / `behind` / `caught up`
  / `first run`), produced by pure `heroCount(mood:debt:)` and `heroQualifier(mood:debt:)` from
  which `sleepDebtBracketText` is re-composed so `SleepMoodTests` passes unchanged. The speech
  bubble stays above the worm, stays a pure function of state and counts (R8), and may gain
  variants for manual mode ("Wake me when you're ready.") and running stages.
- **R-A5 The meter never renders without its noun.** A 24-block segmented bar, as in the reference,
  labelled `Rested 12%` while idle (from `rested_pct`) and `Read 138 of 203` while Stage 1 runs
  (from `processed`/`total`), hidden when there is no baseline. A code comment states the rule and a
  test asserts the label is non-empty whenever the bar draws.
- **R-A6 Three tiles, present tense or measured.** `N entities in memory` (`/healthz`
  `entity_count`), `N sources feeding it` (rows of `sourcesOverview` with episodes > 0), and
  `Last cycle · 4 m 12 s measured` — or `—` with a hover reason when no telemetry row joins. Never a
  forecast, never "clusters", never an estimate.
- **R-A7 One Consolidate control, in the hero.** Its subtitle is the manual engine preview
  (`GET /sleep/engine` `preview.manual`, absent when nil); while running it becomes Cancel. G125 R10
  ("exactly one control") holds — the study-list footer loses its button — and `FixWaveTests` is
  upgraded from "SleepView doesn't define one" to the tree-wide "exactly one file defines one".
- **R-A8 The stage strip is the live instrument.** "How Cicada sleeps": five pixel icons (16×16,
  rendered at 32 pt through the generalized snapping rule) labelled **Read · Sort · Decide · Notice
  · File**, read from one `SleepStages.all` array that the `?` popover also renders (one prose
  source). Pips are pending / active (a ≤ 1.2 s breathing pulse — the honest "something is
  happening that I can't count") / done / skipped / failed; **only Read carries a fill fraction**
  (`progress_pct`); a cancel or failure freezes the strip at the stage it reached rather than
  resetting. When caught up, the `.happy` worm with its existing sparkles sits at the strip's right
  end (48 pt, existing frames). The strip **replaces** `moodDetailLine`'s "Stage N of 5" text and
  its `ProgressView`.
- **R-A9 The queue card, "In the queue".** The study-list rows (mark · source · oldest age ·
  `waiting`/`read of total` with a 3-pt micro-fill behind the count while running and a dimmed ✓ at
  read == total), then a schedule row (the mode sentence — "Manual only" / "Every day at 02:00" /
  "Every 6 h" / "After imports settle" — and a "Change…" link that opens Settings › Sleep through
  `AppRouter`), and a footer with the next-run line plus "Scheduled runs use <engine>" **only when**
  `preview.scheduled` differs from `preview.manual`.
- **R-A10 Memory sources panel.** A read-only projection of `store.sourcesOverview` (no new fetch):
  rows with episodes > 0, sorted by captures in the last 14 days, at most six: `OriginMark` · name ·
  a 14-day sparkline of captures per day · `N captured` (lifetime) · four week-dots (activity in
  each of the last four weeks). "All sources →" switches to the Sources tab. **The noun is
  `captured`**, never the queue's `waiting` — two lists, two nouns, no number appears twice.
- **R-A11 Recent consolidations.** Date **and time** (git `--date=iso-strict` on both history
  endpoints, shipped in the same commit as the Swift parser and its timezone fix — git renders in
  the commit's zone, the current parser pins UTC), `N episodes → +a new · b updated`, the reference's
  badge slot filled with the **engine · author** pill (both already parsed), duration measured or
  `—`, and the existing expand-on-click detail.
- **R-A12 Liveness.** When the SSE connection is down the page desaturates one step and shows an
  "as of HH:MM" chip from the snapshot's `loadedAt`; the error state is exempt (news stays at full
  contrast).
- **R-A13 Motion budget.** Idle is still (only the worm's frame loop moves); nothing runs longer
  than 400 ms except the breathing pip; Reduce Motion holds every animation at its terminal frame
  through the existing `frameIndex(…reduceMotion:)` path; no spinner where a real count exists.
- **R-A14 `—` is a value.** Never blank, never a zero for an unknowable; a hover reason on every dash.
- **R-A15 The numbers budget.** The plan carries a table of every digit on the page → Swift field →
  wire origin → state; a narrow lint in the Sleep tests asserts no bare `%` reaches a `Text` in
  `Views/Sleep/` without a noun (the broad "set of interpolations equals the table" form is refused —
  numbers arrive through `Copy.` helpers).
- **R-A16 Backend, all engine-free and additive.** `SourceOverview.activity: {ISO date: captures}`
  for the last 30 days, computed inside the loop `build_overview` already runs (absolute date keys,
  not a rolling array — a 304'd payload renders a day short instead of a day shifted); the ETag
  recipe and the `VersionVector` mapping are **unchanged and pinned by a test**; `--date=iso-strict`
  on `get_sleep_history` and `get_sleep_cycle_detail`; the `SleepEventPayload.progress` type fixed
  from `Double?` to `String?` (the backend sends the stage sentence; the mismatch has been silently
  nil since it shipped).

**Amendment to G125 R1 ("counts, never charts").** The owner's 2026-09-05 brief asked for the
reference's sparklines. R1's spirit survives as **one volume encoding per surface**: the book pile
encodes queued text, a sparkline encodes captures per day, and no number is drawn twice.

**Not in scope (A):** a time-of-day sky (a later slice, with rails: art only, state outranks the
clock); G127 mascot identity (the nightcap is the only character-specific art and is sequenced
last); the Sources page (Track S); the video renderer (Track V).

---

## Track L — real marks

**Finding.** `ChromeGlyph` is a hand-drawn approximation wrong on four axes (pre-2015 palette, ~90°
rotation, undersized centre disc, flat fills); `SafariGlyph` is the SF compass tinted an invented
blue. The rule that produced them ("browser marks are drawn, not downloaded", R7 of the
2026-09-02 Safari-import plan) is a plan rule, not a ruling, and both `PlatformTile` and
`OriginMark` already prefer a bundled PNG. Two shipped PNGs (`codex`, `x`) are opaque squares with
no alpha. The `cicada` author and every OpenRouter/Ollama model render as a grey "?" in
Contributors. A verified pipeline exists: Wikimedia Commons SVG (descriptive User-Agent) →
a 20-line `swiftc` NSImage rasterizer → 256 px PNG with alpha; and `NSWorkspace` resolves the
installed Chrome / Safari / Notes icons at runtime.

### Rulings (R-L1 … R-L8)

- **R-L1 Precedence in `OriginMark`:** installed app icon (Chrome, Safari, Apple Notes — by bundle
  id, cached like `LogoImage.cache`) → bundled PNG → SF Symbol in the origin's colour. The drawn
  glyphs (`ChromeGlyph`, `SafariGlyph`, `BrandGlyph`, `brandGlyph`, `platformTile(glyph:)`) are
  **deleted in the same PR** — a wrong-coloured Chrome that appears only when an asset is missing
  looks like a logo and isn't.
- **R-L2 Assets are fetched by a maintainer, committed, and never fetched at runtime.**
  `scripts/fetch-logos.sh` (portable; builds the rasterizer once; prefers `rsvg-convert` when
  installed) reads `Resources/logos/logos.manifest.json` (id → Commons file → source URL → licence →
  trademark restriction → sha256), refuses to overwrite a changed upstream without `--accept`, and
  regenerates `Resources/logos/LOGOS.md` as the attribution table. Nominative use only: identify the
  product, never restyle or recolour a vendor mark.
- **R-L3 Apple's marks are not redistributed.** Safari and Apple Notes use the installed app's icon
  at runtime and fall back to Apple's own SF Symbols (`safari`, `note.text`) in the system tint —
  no Safari PNG is committed. Chrome, Firefox, Brave (lion icon), ChatGPT/OpenAI, Claude (the CC0
  "Claude AI symbol"), Gemini (the star glyph), Ollama, RSS and Telegram come from Commons with their
  licence lines recorded. Marks with no square Commons source (X, OpenRouter) keep a raster or use
  the monogram.
- **R-L4 One map.** `OriginIconography.logoName(for:)` is the only id → asset map: it gains
  `chrome-bookmark→chrome`, `chatgpt-export→chatgpt`, `gemini-export→gemini`, `rss→rss`, the
  missing `gemini-export`/`saved-link` label and symbol cases, and loses its unreachable duplicate
  cases; `ConnectedChannelRow.logoName` delegates to it.
- **R-L5 Dark mode.** Monochrome marks ship a `-dark` sibling (`LogoImage` tries `<name>-dark`
  under `CicadaTheme.mode == .dark`); `x.png` and `codex.png` are recut with alpha, after which the
  white plate and the rounded clip on the mark go.
- **R-L6 Contributors.** `cicada` becomes author kind `system` rendered with the bookworm sprite
  and the label "Cicada · maintenance"; `_PROVIDER_SUBSTRINGS` learns openrouter / ollama / meta /
  mistral / deepseek / qwen with the rule "the router before the first slash wins"; an unmatched
  model gets a two-letter monogram, never "?".
- **R-L7 Tests.** Every id in `logoName` has a file (driven from an exported list, not a hardcoded
  14-string array); every bundled PNG is claimed by some map; asset hygiene (square, ≥ 256 px, alpha
  unless allow-listed); `-dark` variants come in pairs; no channel id falls through to `tray`; a
  Python test that committed sha256s match the manifest and `LOGOS.md` names the same licence; a
  table test over `_provider_for_model` / `_classify_author_kind`.
- **R-L8 Every generated PNG is eyeballed once** before commit (NSImage is not a full SVG renderer:
  the Notes SVG rasterized wrong in the spike). The reversal of R7 and its reasons are recorded in
  the backlog so the glyphs never come back.

---

## Track V — in-app video

**Finding.** Only YouTube plays in-app, only when an id parses (`/live/` and playlists fall out);
every other provider (Vimeo, TikTok, Loom, direct `.mp4`, `file://`) lands as a website card.
`_enrich_opengraph` has no content-type guard (a saved `.mp4` is downloaded and HTML-parsed);
`link_enrichment._excluded_media` already honours a `video` media type nothing produces;
`GET /sources` reads `media_type` from `url_index.json`, not the page — so write-time
reclassification is a split-brain risk and **read-time derivation is the rule.**

### Rulings (R-V1 … R-V8)

- **R-V1 Derive the provider at read time** in the app from `media.url` (a pure `VideoRef`), so
  every already-saved item plays the moment the app updates, with no bank rewrite and no
  `url_index.json` migration. `MediaPreviewModel.Kind` dispatches on the URL, not on `mediaType`.
- **R-V2 One new `media_type`, `video`, for direct/local files only** (it lands in tags and the
  `/sources` wire, so each value costs); providers go in an additive optional `media.provider`
  (+ `media.duration_s`) — no ETag change.
- **R-V3 Players.** AVKit `VideoPlayerView` for `.mp4/.m4v/.mov/.webm/.m3u8` over http(s) and
  `file://` (readability checked first; an unreadable local file shows the exact fix and Reveal in
  Finder, never a black rectangle; `loadFileURL(_:allowingReadAccessTo:)` where a WebView is used);
  the provider's own embed player (YouTube incl. `/live/` and `videoseries?list=`, Vimeo, TikTok,
  Loom) in the existing `WebView`. Twitch stays external (its player requires a real parent origin —
  faking one is circumvention); X and Instagram stay external.
- **R-V4 The ToS rail, restated for video.** Load only a provider's own player URL or the exact
  iframe src its oEmbed returns; read oEmbed *fields* only; never resolve an underlying stream, never
  send cookies or auth, never retry a 401/403/407/451 with other headers. A direct file the app plays
  is one the user saved as a direct URL — never one Cicada derived.
- **R-V5 Surfaces.** `HeroPreview` gains `EmbedVideoHero` (generalized from `YouTubeHero`) and
  `FileVideoHero`; the Feed row shows a play badge for any video ref; the Feed preview sheet widens
  for video kinds (a 480 × 270 player in a 480 × 520 sheet reads as a regression); "Open externally"
  is always present. Space toggles play for direct files only (`.focusable()` + `.onKeyPress(.space)`,
  never a global shortcut that would eat the Feed search field).
- **R-V6 Seam, not mocks.** `VideoPlayerView` takes a `VideoPlaybackController` protocol; the
  production `AVPlaybackController` is the only file importing AVFoundation; tests use a fake.
  Codec questions are a stated manual check, not a mocked green.
- **R-V7 Backend slice.** `api/services/video_urls.py` (pure classification), one shared
  `_enrich_oembed` for Vimeo / TikTok / Loom modelled on `_enrich_youtube` (fields only, 4 s, 512 KB),
  `_classify → video` for direct files, and a content-type guard on `_enrich_opengraph`.
  `normalize_url` is **not** taught `/live/` here — it changes `url_hash` and needs a dedup-index
  migration (queued follow-up).
- **R-V8 One fixture, two suites.** `api/tests/fixtures/video_urls.json` is read by both the Python
  and the Swift classification tests (the `#filePath` walk `FontLiteralLintTests` uses, with its
  non-vacuous guard) — add a provider on one side only and the other side fails.

This is the preview half of G11; it moves G22 (transcripts as entity body) not at all and must not
close that row.

---

## Track P — polish and truth

Verified rough edges from the recent-work reader, batched into one track:

1. **Copy that promises what a default install does not do:** `OnboardingSleepStep` says Sleep
   "also runs on its own schedule" and `HelpPopoverContent` repeats it plus describes MCP-client
   capture that G105 replaced. Fix by adding a "Run nightly" toggle to the onboarding step over
   `PUT /sleep/schedule` and correcting both strings.
2. **Six one-liners:** Integrations lists every chat export twice (filter harness rows on
   `channelId == nil`); "Keep separate" on a merge suggestion 400s without a target hint (send the
   entity id as `mergeTarget`); a bookmark resolved as `remove` (archived) and `junk` items stay in
   the Feed (filter in `list_sources`); `SettingsScene` misses `.onChange(of: sectionRaw)`; both
   Settings → main-window hand-offs never bring the window forward (`AppRouter.activateMainWindow()`
   at both sites, and the first-run sheet dismisses); `SettingsScene` / `FirstRunSheet` frames are
   not `uiScale`-aware.
3. **Toolbar audit by deletion:** `Upload` leaves every page (the Feed's `+` and ⌘N own one-shot
   import per the G126 rule) and `Sleep` leaves every page too (it duplicates the Sleep page's one
   control); the `?` stays only where it explains the page it is on.
4. **Portability:** three shipped owner-name literals (`mcp/server.py` ×2, `conflict_resolver.py`)
   become placeholders resolved through `owner_identity`; `GET /state` `sleep.next_at` is calibrated
   for `interval` / `after_import` and `test_state_wiring` stops asserting the bug.
5. **The graph canvas in light mode:** `graph.js` hardcodes the dark palette; add `setTheme(mode)`
   with two palette tables, pushed from `GraphView.updateNSView`, with a JS test that both palettes
   resolve.
6. **Integrations loading / error state** (it is also onboarding step 3).

---

## Track S — Sources v2 (after A and L)

**Finding.** The green dot stands for four situations (live-watched, nightly-polled, hook-captured,
one-shot two months ago); three number formats share one window (locale-grouped `1.927`,
`en_US_POSIX` `1,035`, server-side `f"{n:,}"`); nothing on the page has a time dimension; a grid row
centres shorter cards; the adaptive column ignores `uiScale`; `bookmark` / `unknown` / `Url` titles
come from an unmapped origin label; three of four contributors are "?"; "Add a source" exists only
in the empty state.

### Rulings (R-S1 … R-S7)

- **R-S1 One card system.** Fixed tile height (`CicadaTheme.scaled(112)`), a fixed column count
  derived once from the container width in scaled units and shared by every section; five bands:
  mark · brand name · one status verb · 14-day sparkline + total · freshness dots + delta.
- **R-S2 The status line names the state:** `SourceLiveness.of(row:channel:watch:)` — live-watched /
  polled nightly / captured by hook / imported once (date) / failed (the actual error) — derived from
  the channel's actions, `harness`, and the watch state; no new backend field.
- **R-S3 Two nouns.** The total is `items` (a browser's bookmark count); the sparkline and delta are
  `captured` ("+12 in 14 days") from `SourceOverview.activity` (Track A's field). Never one noun for
  both.
- **R-S4 Names:** `SourceDisplayName.of(_:)` maps every origin to a product name; never a lowercase
  id or a question mark for a bucket the app can name (`unknown` → "Before provenance", `bookmark`
  → "Saved links", `url` → "Links").
- **R-S5 Numbers:** `UsageFormat.count(_:locale:)` on `Locale.autoupdatingCurrent` everywhere on
  the page, and a `CountLiteralLintTests` modelled on `FontLiteralLintTests`; the server stops
  pre-formatting `detail` numbers.
- **R-S6 Contributors** become a compact "who wrote your memory" strip: provider marks (Track L),
  `cicada` as the bookworm ("Cicada · maintenance"), `user` as "You", one **labelled** stacked bar of
  share-of-entities; the drill-down moves behind a click.
- **R-S7 `+ Add a source` lives in the header at all times.** The Advanced toggle stays for now
  (rehoming its content is a later slice).

---

## Decisions taken without the owner (autonomous session — review at PR time)

- The Sleep page keeps a **two-column** layout like the reference; the honest-minimal single column
  lost on the delight axis.
- The reference's three tiles are kept as slots but re-sourced (entities · sources · last measured
  cycle); "clusters", "insights" and "est. time" are refused by rule, not taste.
- The Consolidate control **moves into the hero** (still exactly one).
- The stage strip is a permanent element that doubles as the live instrument, replacing the old
  "Stage N of 5" line — a net-flat element count against G125's reduction point.
- Sparklines amend G125 R1 (recorded above).
- Safari's and Notes' icons are **never committed** — runtime app icon or Apple's SF Symbol.
- The drawn browser glyphs are **deleted**, not kept as fallbacks.
- Twitch, X and Instagram video stay external by rule.
- The toolbar audit resolves by **removing** Sleep and Upload from every page.
- Workflow agents run on **opus** this round (owner's explicit permission for this session); the
  standing small-models rule is unchanged for other sessions.
