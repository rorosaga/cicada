# Track L — real marks (R-L1 … R-L8) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every brand mark the app draws is the real one. Chrome stops being a hand-drawn
approximation (four wrong colours, ~90° rotation, undersized centre disc, flat fills), Safari and
Apple Notes become the icons of the apps actually installed on this Mac, ChatGPT / Claude / Gemini /
Ollama / RSS get official marks fetched once by a maintainer and committed with their licence lines,
the two opaque-square rasters (`x`, `codex`) are recut with alpha and given `-dark` siblings, and
Cicada's own maintenance commits stop rendering as an anonymous grey "?" in its own Contributors
list.

**Architecture:** three maintainer-time tools (`tools/svg2png.swift`, `tools/alphakey.swift`,
`tools/monoflip.swift`) driven by one bash script (`scripts/fetch-logos.sh`) over one declaration
(`Resources/logos/logos.manifest.json`), which also generates the attribution table
(`Resources/logos/LOGOS.md`). **No runtime network is added**: the script runs on a maintainer's Mac
and the PNGs are committed. At runtime the app gains one new precedence step — the installed app's
icon via `NSWorkspace`, cached on the main actor — in front of the bundled PNG, and one new
resolution step — a `-dark` sibling under `CicadaTheme.mode == .dark`. The drawn glyphs and the
whole `BrandGlyph` abstraction behind them are deleted. `OriginIconography.logoName(for:)` becomes
the only id → asset map and every other surface delegates to it.

**Tech Stack:** bash + `swiftc`/AppKit (maintainer tools), SwiftUI + XCTest (`app/CicadaApp`),
Python 3 / FastAPI / pytest (`api/`).

**Spec:** `docs/superpowers/specs/2026-09-05-round2-study-room-marks-video-design.md` § Track L,
rulings **R-L1 … R-L8** (binding). Audit: the phase-1 logos report **lives in a session scratchpad
and is not in the repo** — every fact it established is restated below (in "What the code actually
does today", in the rulings, and in task 2's Commons table), so nothing here requires reading it. Backlog rows **G126**
(the Integrations page whose rows wear these marks), **G124** (the Sources page and the Contributors
calendar), **G119** (Arc/Firefox/Brave *channels* — not this track), **G59** (entity logos — not
this track). Reverses **R7** of `docs/superpowers/plans/2026-09-02-safari-import-catalog.md:34`
("browser marks are drawn, not downloaded") — a plan rule, never a `TODO.md` ruling, and one that
named this exact escape hatch.

---

## What the code actually does today (verified against `feat/real-marks` @ `53885a1`)

- **`OriginMark`** (`app/CicadaApp/Sources/CicadaApp/Views/Common/OriginMark.swift:12-29`): precedence
  is bundled PNG (`:14`) → drawn glyph (`:16-20`) → SF Symbol in `OriginIconography.color` (`:21-25`),
  in a `size × size` frame with the origin's label as its accessibility label. Rendered by the Sleep
  study desk, the episode rows, the consolidation history and the Sources grid.
- **`OriginIconography`** (`Views/Capture/OriginIconography.swift`): `label` (`:20-67`), `symbol`
  (`:69-94`), `color` (`:96-120`), `logoName` (`:122-145`), `brandGlyph` (`:147-155`). Three defects
  confirmed by reading: (a) **unreachable duplicate cases** — `"codex"` at `:32` *and* `:57`,
  `"claude-desktop"` at `:33` *and* `:58`, `"cursor"` at `:31` *and* `:59`; `symbol` re-lists
  `"codex","cursor","gemini-cli"` at `:89` after `:71` already matched two of them; `color` repeats
  the same shadowing at `:115-116` after `:99-100`. Swift takes the FIRST match, so `symbol(for:
  "codex")` can never be `terminal`. **`gemini-cli` is the exception in both switches: nothing at
  `:71` or `:99-100` matches it, so `symbol(for: "gemini-cli") == "terminal"` and
  `color(for: "gemini-cli") == CicadaTheme.textPrimary` are the LIVE answers today and must survive
  the cleanup.** The labels that are actually dead are `codex`/`cursor` in `:89` and `:115`,
  `claude-desktop` at `:90` and `:116`, and `codex`/`claude-desktop`/`cursor` at `:57-59`.
  (b) **no `gemini-export` case anywhere** — it reads as
  "Gemini-export" with a `tray`, and `source_overview.CATALOG` (`api/services/source_overview.py:54`)
  ships a row whose `mark` is exactly that id. (c) **no `saved-link` case** — same fall-through.
  `saved-link` is not a `mark` in that catalog: it is the `origins` tuple of the `files` row (`:69`),
  whose `mark` column is the already-handled `bookmark`. It reaches `OriginIconography` as an
  episode/media `origin` (stamped by `POST /sources/save`, `cicada_save_url`'s backend-down path —
  G124's R1 follow-up), which is why a case is still owed.
- **`LogoImage`** (`Views/Common/LogoImage.swift`): `exists(name:)` (`:118-120`) is a synchronous
  bundle-URL lookup; `bundledImage(for:)` (`:127-137`) decodes off-main and caches in a
  `@MainActor` dict (`:124-125`); `monogram(for:)` (`:105-113`) returns up to two initials, `"?"`
  when nothing is usable. `platformTile(name:size:systemFallback:)` (`:154-156`) and the glyph
  overload (`:164-170`) both build `PlatformTile` (`:173-207`), which fills
  `CicadaTheme.surfaceElevated` (`:189-190`), strokes `CicadaTheme.border` (`:191-192`), then draws
  PNG (`:193-195`, **clipped to `cornerRadius * 0.5`**) → glyph (`:196-197`) → `systemFallback`
  (`:198-202`). `markSize = size * 0.6` (`:185`).
- **The glyphs** (`Views/Capture/Sheets/ImportFamilies.swift`): `BrandGlyph` (`:78-82`, doc + enum),
  `AddSourceTile.brandGlyph` (`:85-95`, inside the `extension AddSourceTile` at `:84` that also holds
  `routeLines` — delete the member, not the extension), `ChromeGlyph` (`:160-188`),
  `SafariGlyph` (`:190-201`),
  `MemberMark`'s three-way switch (`:207-224`), and `ImportFamily.previewMarks` (`:72-75`) whose
  "branded" filter is `logoName != nil || brandGlyph != nil`.
- **`AddSourceTile.logoName`** (`Views/Capture/Sheets/AddSourceSheet.swift:143-166`): eight platform
  PNGs; `.safari`, `.chrome`, `.appleNotes`, `.rssFeed`, `.calendar`, `.chatExport`,
  `.bookmarksFile`, `.pasteLink` return nil. Its doc comment (`:143-151`) documents R7's escape
  hatch as future work.
- **`ConnectedChannelRow`** (`Views/Capture/ConnectedChannelRow.swift`): `icon(for:)` (`:181-196`),
  `tint(for:)` (`:198-213`), `logoName(for:)` (`:220-228`) — a **second, shorter map** returning only
  `pinterest|reddit|x|telegram`, which is why Chrome is a plain blue `globe` in Settings →
  Integrations (`Views/Settings/IntegrationsView.swift:133-147`) and in the Feed strip while being a
  `ChromeGlyph` in `OriginMark` and the `+` catalog. Same source, three pictures.
- **Bundled assets** (`Sources/CicadaApp/Resources/logos/`, 15 PNGs — 7 + 8): batch 1 (`1a4811d`,
  2026-07-03) `claude-code`, `claude-desktop`, `codex`, `cursor`, `gemini-cli`, `hermes`,
  `openclaw` — 256×256, alpha except **`codex` (black on opaque white)**; batch 2 (`cf2c449`,
  2026-08-31) `instagram`, `linkedin`, `pinterest`, `reddit`, `telegram`, `tiktok`, `x`, `youtube` —
  **128×128 favicon-service rasters**, alpha except **`x` (white on opaque black)**. No manifest, no
  licence file, no fetch script (`ls scripts` → `backfill_entity_pages.py`, `doctor.sh`; no
  `tools/`). `Package.swift:10` is `resources: [.copy("Resources")]`, so a new PNG needs **no**
  `Package.swift` edit.
- **`AgentTile`** (`Views/Connect/ConnectView.swift:427-453`) papers over the opaque `codex.png` with
  a `Color.white.opacity(0.92)` plate (`:435`) — which is why Codex looks right there and wrong in
  Integrations. Agent ids at `:74,92,107,121,144,158,179`.
- **Contributors backend** (`api/services/git_service.py`): `USER_AUTHOR = "user"` (`:269`),
  `UNKNOWN_AUTHOR = "unknown"` (`:31`), `_PROVIDER_SUBSTRINGS` (`:276-280`) = openai/anthropic/google
  only, `_OPENAI_O_SERIES` anchored guard (`:282-286`, `:310-313`), `_classify_author_kind`
  (`:289-295`) knows only user/unknown/model, `_provider_for_model` (`:298-314`). The literal
  `"cicada"` — written by `bookmark_sync.py:450`, `state_dictionary.py:521`, `sleep_cycle.py:1666`,
  `sleep_cycle.py:521`, `link_enrichment.py:823`, the three migrations — therefore classifies as
  **model / provider `other`**, and `ContributorAvatar` (`Views/Contributors/ContributorsView.swift
  :408-492`) draws it as a grey circle (`providerColor`'s `default:`, `:479`) with a white **"?"**
  (`monogram`'s `default:`, `:489`). `openrouter/z-ai/glm-5.2`
  lands in the same bucket. `Contributor` schema at `api/models/schemas.py:187-205`; the Swift
  `kind` fallback at `ContributorsView.swift:106-113`; the row's name is a bare
  `Text(contributor.author)` (`:197`) and the accessibility label repeats it (`:132`).
- **Tests that pin the old state:** `ImportCatalogTests.testNonBrandedTilesDeclareNoLogo`
  (`Tests/CicadaAppTests/ImportCatalogTests.swift:185-191` — asserts `.safari`/`.chrome` are nil),
  `testAGlyphAndAPngAreNeverBothDeclared` (`:197-205` — **the forcing function**: it asserts
  `allCases.filter { $0.brandGlyph != nil } == [.safari, .chrome]`, so flipping Chrome to a PNG
  without deleting the glyphs fails immediately),
  `ImportFamilyTests.testBrowserTilesCarryDrawnGlyphsNotDownloadedPNGs` (`ImportFamilyTests.swift
  :33-41`), `testFamilyPreviewMarksAreItsFirstBrandedMembers` (`:43-47` — expects
  `browsers.previewMarks == [.safari, .chrome]`),
  `testAnUnbrandedFamilyStillWearsItsMembersSymbols` (`:51-57` — **the second forcing function,
  found by the critic**: it asserts `files.previewMarks == files.members`, and `files` is
  `[.bookmarksFile, .pasteLink, .appleNotes]`. The moment `previewMarks` counts `appBundleId`,
  `.appleNotes` becomes "branded" and the family's preview collapses to `[.appleNotes]`. Task 3
  must update it in the same commit), `OriginIconographyTests
  .testOriginsWithoutABundledLogoReturnNil` (`OriginIconographyTests.swift:26-31`),
  `testBrowsersUseDrawnGlyphs` (`:45-50`), `testEveryDeclaredLogoExistsInTheBundle` (`:35-43` —
  iterates a **hardcoded list of 14 origin strings**, so a new mapping is silently uncovered).
  Python: `test_contributors.py:159-196` — `test_provider_for_model_other_and_non_model` asserts
  `"mistral-large"` and `"llama-3"` are `"other"` and **must be updated** when the substrings land.
- **Tooling on this Mac (measured in the spike):** `swiftc` ✅ (AppKit decodes SVG, ~1.6 s build),
  `sips` ✅ (PNG metadata only), `curl` ✅, `shasum` ✅; `rsvg-convert` / `magick` / `inkscape` /
  `cairosvg` **absent**; `qlmanage -t` hung past 120 s. Wikimedia refuses an **empty** User-Agent
  with 403 and serves 200 for a descriptive one.

## Global Constraints

- Work ONLY in `<worktree>/` (branch
  `feat/real-marks`, based on `dev` @ `53885a1`). Every shell command is
  `cd <worktree>/ && <cmd>` with absolute paths
  (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never an unquoted
  `--include=*.ext` (zsh globbing breaks it) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`,
  `~/Library`, or `~/.claude/projects`. Fixtures are synthetic (`alpha-project`, `bob-example`,
  `example.com`). Reading `/Applications` and `/System/Applications` **bundle icons** is fine and is
  what `NSWorkspace` does at runtime; no icon extracted from an installed app is ever committed.
- Python: `api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full suite `api/tests`
  must report **0 failures** (2119 passed on 2026-09-05). One known order-dependent case:
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
  passes alone — if it is the ONLY red, re-run it alone and report both results.
- Swift: `cd .../real-marks/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures** (763 passed on 2026-09-05; SourceKit
  diagnostics naming OTHER worktrees are noise). NEVER run `make dev`, `make install-app`,
  `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator
  installs at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv`, or `*-report.md`. Do not push. Do not create branches or worktrees. Do not dispatch
  subagents. Ignore Devin/PR comments.
- **Network:** `curl` to `commons.wikimedia.org` is expected and allowed **in task 2 only** (and in
  a re-run of `scripts/fetch-logos.sh`). It is maintainer-time asset work: no runtime fetch is
  added, and **none of the three outbound gates** (`CICADA_ALLOW_CONNECTOR_FETCH`,
  `CICADA_ALLOW_FEED_FETCH`, `CICADA_ALLOW_LOGO_FETCH`) is read, written or mentioned by the new
  code. Every other task is offline; the Python and Swift suites never touch the network.
- **Nominative use only.** A vendor mark is shown to identify the product. It is never restyled,
  recoloured, re-drawn, cropped, put on a coloured plate, or combined with Cicada's own marks. The
  ONE permitted transform is R4 below (an exact luminance inversion of a **monochrome** mark), and
  the tool refuses to apply it to anything else.
- **Portability / privacy:** no owner name and no author-machine path in shipped code, scripts or
  docs — the script resolves the repo as `$(cd "$(dirname "$0")/.." && pwd)`. Docs follow the
  standing privacy rule (no bank content, no episode titles, no personal names).
- Docstrings explain WHY, citing the ruling (`R-L<n>`) or the G-row that motivated the rule. Match
  the density of the files touched.
- Line numbers are from `53885a1` and drift as tasks land — read the cited code before editing.

## Rulings (binding for this track; each decides something the brief left open)

- **R1 — the manifest describes exactly what is committed, and nothing else.** One entry per file in
  `Resources/logos/`, no entry without a file. An asset that cannot be *claimed* by a map today is
  still allowed (Firefox and Brave, reserved for G119) but must be named in the T2 allowlist with
  its G-row, so "dead bytes" is a deliberate, reviewed state and never an accident.
- **R2 — Apple's marks are never committed** (R-L3). No `safari.png`, no `apple-notes.png`. Those
  two origins resolve *installed app icon → SF Symbol* with no PNG rung, and
  `OriginIconography.logoName` returns **nil** for them — otherwise T1 ("every declared logo has a
  file") would demand a file the ruling forbids. `AddSourceTile.safari.logoName` and
  `.appleNotes.logoName` stay nil for the same reason.
- **R3 — no `calendar.png`.** The Commons file is *Google* Calendar; the `calendar` channel is any
  ICS publisher. A Google mark on a generic ICS row is a lie about the vendor, so calendar keeps its
  SF Symbol. (The audit's §6 draft map proposed one; this ruling overrides it.)
- **R4 — a `-dark` sibling is an exact luminance inversion of a monochrome mark, or it does not
  exist.** `tools/monoflip.swift` measures the source: if any opaque pixel has
  `max(r,g,b) - min(r,g,b) > 8/255` it exits non-zero with "coloured marks are never recoloured
  (R-L2)". So `chatgpt`, `codex`, `x` (and `ollama` iff its rasterized mark is achromatic) get
  siblings; `chrome`, `claude`, `gemini`, `rss`, `telegram`, `firefox`, `brave` never do. LOGOS.md
  states the transform per `-dark` row.
- **R5 — the two opaque rasters are keyed, not re-fetched.** X's mark has no usable Commons source
  (R-L3 says so), and `codex.png` is fine art on the wrong ground. `tools/alphakey.swift` converts a
  clean two-tone raster to alpha exactly (`alpha = luma` for a light mark on a dark ground,
  `alpha = 1 - luma` for the reverse), which leaves no fringe on anti-aliased edges. `x.png` stays
  128 px — upscaling a favicon to 256 would be fake resolution — and is named in T3's `legacy128`
  allowlist alongside the other batch-2 rasters (with `x-dark`; `codex` is already 256 and is not on
  that list). **A recut is a one-time act, not a step the script repeats:** `alphakey` refuses a
  source that already carries a non-opaque pixel (`exit 3`), and the moment the keyed file is
  committed the opaque original only exists in git history — so a normal run *verifies a `recut`
  asset's sha and nothing more*, exactly like a `legacy` one. `derivedFrom` records the source blob
  as `<commit>:<path>` plus the exact invocations, which is what makes the recut reproducible by
  hand and reviewable rather than magic.
- **R6 — one runtime precedence, three surfaces.** `InstalledAppIcon.image(bundleId:size:)` (main-actor
  cache, exactly like `LogoImage.cache`) is consulted by `OriginMark` **and** `PlatformTile`, so the
  Sleep desk, the Sources grid, the `+` catalog and Settings → Integrations cannot disagree about
  what Safari looks like. A machine without the app installed falls to the PNG rung, then the SF
  Symbol. **No test asserts an installed app exists** — the suites must pass on a machine with no
  Chrome.
- **R7 — `logoName` delegates, `icon`/`tint` do not.** `ConnectedChannelRow.logoName` becomes
  `OriginIconography.logoName(for: origin(forChannel:))` (R-L4). Its `icon`/`tint` switches stay as
  they are: they are the fallback circle's own palette, already non-`tray` for all 13 ids, and
  routing them through the origin map would silently change `files` from `link` to `bookmark.fill`
  for no gain.
- **R8 — an unmatched contributor gets initials, never "?"** (R-L6). `provider` with a bundled mark →
  the mark; anything else → the provider's brand colour (or neutral) with
  `LogoImage.monogram(for: contributor.author)`. `cicada` is `kind: "system"`, displayed as
  "Cicada · maintenance" with a **static frame 0** of the bookworm sprite — static, not
  `BookwormView`, because a 22 pt animating sprite in a scrolling table is motion nobody asked for
  and frame 0 is a cache hit the menu bar already paid for.
- **R9 — "the router before the first slash wins"** (R-L6). A slashed id whose first segment names a
  known router (`openrouter/…`, `ollama/…`) resolves to that router *before* the substring pass, so
  `openrouter/anthropic/claude-opus-4` is `openrouter` — the router is who billed. Everything else
  keeps today's whole-id substring behaviour, and the anchored o-series guard
  (`git_service.py:310-313`) is untouched.
- **R10 — every generated PNG is opened with the Read tool before it is committed** (R-L8). NSImage
  is not a full SVG renderer: in the spike the Apple Notes SVG *reported success* and rasterized
  without its rounded-rect clip. A file that renders wrong is deleted, dropped from the manifest,
  and listed in task 2's "left out" note — never committed "to fix later".

---

## File map

| File | Responsibility |
|---|---|
| `tools/svg2png.swift` (new) | SVG → square PNG with alpha, aspect-fit, centered (AppKit) |
| `tools/alphakey.swift` (new) | R5 — two-tone raster → alpha-keyed PNG (`light`/`dark` ground) |
| `tools/monoflip.swift` (new) | R4 — exact luminance inversion of a **monochrome** mark; refuses colour |
| `scripts/fetch-logos.sh` (new) | R-L2 — the maintainer pipeline: fetch, licence, rasterize, sha guard, `LOGOS.md` |
| `app/…/Resources/logos/logos.manifest.json` (new) | The declaration: id → source → licence → restriction → sha256 |
| `app/…/Resources/logos/LOGOS.md` (generated) | The attribution table (the repo's NOTICE for third-party marks) |
| `app/…/Resources/logos/*.png` | New: `chrome`, `chatgpt(+ -dark)`, `claude`, `gemini`, `ollama`, `rss`, `telegram`, `firefox`, `brave`. Recut: `x(+ -dark)`, `codex(+ -dark)` |
| `app/…/Views/Common/InstalledAppIcon.swift` (new) | R-L1/R6 — `NSWorkspace` bundle-id → icon, main-actor cached |
| `app/…/Views/Common/OriginMark.swift` | Precedence: app icon → PNG → SF Symbol; glyph branch deleted |
| `app/…/Views/Common/LogoImage.swift` | `resolvedName(for:)` (`-dark`), `platformTile(name:bundleId:…)`; glyph overload + `PlatformTile.glyph` + the mark clip deleted |
| `app/…/Views/Capture/OriginIconography.swift` | `appBundleId(for:)`, extended `logoName`, new `gemini-export`/`saved-link` cases, duplicate cases removed, `allKnownOrigins` exported; `brandGlyph` deleted |
| `app/…/Views/Capture/Sheets/ImportFamilies.swift` | `BrandGlyph`, `brandGlyph`, `ChromeGlyph`, `SafariGlyph` deleted; `MemberMark` collapsed; `previewMarks` counts `appBundleId` |
| `app/…/Views/Capture/Sheets/AddSourceSheet.swift` | `.chrome`/`.rssFeed` gain a `logoName`; `appBundleId`; R7 doc comment rewritten |
| `app/…/Views/Capture/ConnectedChannelRow.swift` | `origin(forChannel:)` + `logoName` delegates (R7) |
| `app/…/Views/Capture/ChannelMarks.swift` (new) | `allChannelIds` — `channel_registry.CHANNEL_IDS` mirrored once, read by T2 and T5 |
| `app/…/Views/Settings/IntegrationsView.swift` | passes the channel's bundle id into the tile |
| `app/…/Views/Connect/ConnectView.swift` | the white plate under `AgentTile` goes (R-L5) |
| `app/…/Views/Contributors/ContributorIdentity.swift` (new) | R8 — display name, provider mark, monogram; pure + tested |
| `app/…/Views/Contributors/ContributorsView.swift` | `system` kind, the sprite mark, the label, the monogram fallback |
| `api/services/git_service.py` | `CICADA_AUTHOR`, `_classify_author_kind` → `system`, `_ROUTER_PREFIXES` (R9), extended `_PROVIDER_SUBSTRINGS` |
| `api/models/schemas.py` | `Contributor.kind`/`provider` doc comments (values only; no wire shape change) |
| Tests (Swift) | `LogoAssetTests` (T2/T3/T4), `OriginIconographyTests` (T1, inverted cases), `ImportCatalogTests`/`ImportFamilyTests` (inverted), `ChannelMarkTests` (T5), `LogoImageTests` (`-dark` resolution), `ContributorIdentityTests` |
| Tests (Python) | `api/tests/test_logo_manifest.py` (T6), `api/tests/test_contributors.py` (T7 + the two updated rows) |
| Docs | `docs/goals/memory-evolution.md` (G126 + G124), `docs/goals/TODO.md`, `CLAUDE.md` |

---

### Task 1: The pipeline and the ledger — tools, script, manifest, LOGOS.md, T6

No asset changes. This task lands the machinery and *describes what is already committed*, so the
branch stays shippable and task 2 has a guard to run against.

**Files:**
- Create: `tools/svg2png.swift`, `tools/alphakey.swift`, `tools/monoflip.swift`,
  `scripts/fetch-logos.sh`, `app/CicadaApp/Sources/CicadaApp/Resources/logos/logos.manifest.json`,
  `app/CicadaApp/Sources/CicadaApp/Resources/logos/LOGOS.md`
- Test: `api/tests/test_logo_manifest.py` (new)

**Interfaces:**
- Produces: `scripts/fetch-logos.sh [--check] [--accept] [--only <id>]`;
  `logos.manifest.json` = `{userAgent, size, assets: [{id, file, origin, commonsFile?, sourceUrl?,
  artist?, licence, restrictions, svgSha256?, derivedFrom?, sha256}]}` with `origin ∈
  commons | recut | legacy`; `LOGOS.md` regenerated deterministically (assets sorted by `id`).
- Consumes: `curl`, `shasum -a 256`, `sips`, `swiftc` (all present; `rsvg-convert` preferred when
  installed).

- [ ] **Step 1: Failing test** — `api/tests/test_logo_manifest.py`

```python
"""T6 (R-L7) — the committed brand marks are the ones the manifest claims.

No network: this test proves only that `Resources/logos/` and
`logos.manifest.json` and `LOGOS.md` agree. The fetch itself is
`scripts/fetch-logos.sh`, run by hand on a maintainer's Mac (R-L2), because a
vendor mark that changed upstream must never land unreviewed — and because the
app must add no runtime network path to show a logo.

A hand-edited PNG, an asset committed without an attribution row, or an
attribution row whose licence no longer matches the manifest all fail here.
"""

import hashlib
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOGOS = _REPO_ROOT / "app/CicadaApp/Sources/CicadaApp/Resources/logos"
_MANIFEST = _LOGOS / "logos.manifest.json"
_ATTRIBUTION = _LOGOS / "LOGOS.md"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_committed_png_has_a_manifest_entry_and_vice_versa():
    """R1 — the manifest describes exactly what is committed, and nothing else."""
    declared = {a["file"] for a in _manifest()["assets"]}
    committed = {p.name for p in _LOGOS.glob("*.png")}
    assert declared == committed, (
        f"undeclared: {sorted(committed - declared)}; missing file: {sorted(declared - committed)}"
    )


def test_every_committed_png_matches_its_recorded_sha256():
    for asset in _manifest()["assets"]:
        path = _LOGOS / asset["file"]
        assert _sha256(path) == asset["sha256"], (
            f"{asset['file']} changed without re-running scripts/fetch-logos.sh"
        )


def test_attribution_table_names_every_asset_with_the_same_licence():
    """LOGOS.md is the repo's NOTICE for third-party marks — the repo has a
    LICENSE but nothing else covering vendor art."""
    text = _ATTRIBUTION.read_text(encoding="utf-8")
    for asset in _manifest()["assets"]:
        assert f"`{asset['id']}`" in text, f"{asset['id']} has no attribution row"
        assert asset["licence"] in text, f"{asset['id']}'s licence line is not in LOGOS.md"


def test_ids_are_unique_and_dark_siblings_declare_their_base():
    """R4 — a `-dark` file is a variant of a base mark, never a standalone one."""
    assets = _manifest()["assets"]
    ids = [a["id"] for a in assets]
    assert len(ids) == len(set(ids))
    for ident in ids:
        if ident.endswith("-dark"):
            assert ident[: -len("-dark")] in ids, f"{ident} has no base mark"


def test_the_manifest_records_a_licence_and_a_restriction_for_every_asset():
    for asset in _manifest()["assets"]:
        assert asset["licence"].strip(), asset["id"]
        assert asset["restrictions"].strip(), asset["id"]
        assert asset["origin"] in {"commons", "recut", "legacy"}, asset["id"]
```

Run it — it fails on the missing manifest:
```bash
cd <worktree>/ && \
  api/.venv/bin/python -m pytest api/tests/test_logo_manifest.py -q -p no:cacheprovider
```

- [ ] **Step 2: The three tools.** `tools/svg2png.swift` verbatim from the spike (it is the measured,
      working rasterizer — 17/17 candidates at 256×256 with alpha):

```swift
import AppKit

// svg2png <in.svg> <out.png> <size> — square, alpha, aspect-fit, centered.
//
// Why AppKit and not a library: on a stock Mac `rsvg-convert`, ImageMagick,
// Inkscape and cairosvg are all absent and `qlmanage -t` hung past 120 s
// (measured 2026-09-05). `NSImage` decodes SVG natively and builds in ~1.6 s
// with no dependency. Its limit is real and is why R10 exists: it does not
// honour every clipPath/mask/filter, and it reports success anyway.
let a = CommandLine.arguments
guard a.count == 4, let size = Int(a[3]), size > 0 else {
    fputs("usage: svg2png <in.svg> <out.png> <size>\n", stderr); exit(2)
}
guard let src = NSImage(contentsOfFile: a[1]), src.size.width > 0, src.size.height > 0 else {
    fputs("decode failed: \(a[1])\n", stderr); exit(1)
}
let S = CGFloat(size)
let scale = min(S / src.size.width, S / src.size.height)
let w = src.size.width * scale, h = src.size.height * scale
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
) else { fputs("alloc failed\n", stderr); exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current?.imageInterpolation = .high
src.draw(in: NSRect(x: (S - w) / 2, y: (S - h) / 2, width: w, height: h),
         from: .zero, operation: .sourceOver, fraction: 1.0)
NSGraphicsContext.restoreGraphicsState()
guard let data = rep.representation(using: .png, properties: [:]) else {
    fputs("encode failed\n", stderr); exit(1)
}
try data.write(to: URL(fileURLWithPath: a[2]))
FileHandle.standardError.write("ok \(size)x\(size) from \(Int(src.size.width))x\(Int(src.size.height))\n".data(using: .utf8)!)
```

`tools/alphakey.swift` (R5) — `alphakey <in.png> <out.png> <light|dark>`: for `light` (a dark mark
on a light ground) write `alpha = 1 - luma`, `rgb = 0`; for `dark` (a light mark on a dark ground)
write `alpha = luma`, `rgb = 255`. Read the source through an `NSBitmapImageRep` forced to
`deviceRGB`/8-bit/non-premultiplied so the per-pixel math is exact, and refuse (`exit 3`) a source
that already has a non-opaque pixel — a keyed file must never be keyed twice. Doc comment: cite R5
and name the two files it exists for (`x.png` white-on-black, `codex.png` black-on-white, both
favicon-service artefacts).

`tools/monoflip.swift` (R4) — `monoflip <in.png> <out.png>`: reject with `exit 3` and the message
`coloured marks are never recoloured (R-L2)` if any pixel with `alpha > 8` has
`max(r,g,b) - min(r,g,b) > 8`; otherwise write `rgb' = 255 - rgb`, alpha preserved. Doc comment:
this is the ONE permitted transform on a vendor mark, it is exact and reversible, and it exists so a
black-on-transparent mark does not vanish on `CicadaTheme.surfaceElevated` (`#23252E` in dark).

- [ ] **Step 3: `scripts/fetch-logos.sh`.** `#!/usr/bin/env bash`, `set -euo pipefail`. Header
      comment states: *maintainer-time tool, not a Cicada capture path; no runtime network is added
      and none of the three outbound gates is involved; open every regenerated PNG before committing
      (R10).* Behaviour:
  1. `REPO="$(cd "$(dirname "$0")/.." && pwd)"` (R: portability — no absolute owner path anywhere),
     `LOGOS="$REPO/app/CicadaApp/Sources/CicadaApp/Resources/logos"`, work dir under
     `"${TMPDIR:-/tmp}/cicada-logos.$$"`, trapped for cleanup.
  2. Build the tools once into the work dir (`swiftc -O -o "$WORK/svg2png" "$REPO/tools/svg2png.swift"`,
     same for the other two); skip a build whose binary is newer than its source.
  3. `UA` comes from the manifest's `userAgent` key (fall back to
     `"CicadaLogoFetch/1.0 (+https://github.com/rorosaga/cicada)"` if it is absent) and is
     **always sent**: an empty UA is 403, a descriptive one is what Wikimedia's UA policy asks for
     (both measured). The URL in it is the project's public repo, already in `README.md:112` and in
     `bundle.sh`'s bundle identifiers — it is the contact point Wikimedia's policy asks for, not
     personal data, so it does not breach the portability rail. Likewise `SIZE` comes from the
     manifest's `size` key, not a literal.
  4. Per `origin: "commons"` asset: `curl -sSL -A "$UA" -o "$WORK/<id>.svg"
     "https://commons.wikimedia.org/wiki/Special:FilePath/<urlencoded commonsFile>"`, then
     `action=query&prop=imageinfo&iiprop=url|extmetadata|sha1|size&titles=File:<commonsFile>` for
     `LicenseShortName` / `Restrictions` / `Artist` (recorded, never re-derived at runtime).
     Compare the SVG's sha256 to `svgSha256`: **empty** → a new asset, accept and record;
     **equal** → skip without rewriting (a re-run leaves `git status` clean); **different** →
     rasterize to `<id>.new.png` in the work dir, print
     `DRIFT <id>: upstream sha <old> → <new>` and exit 1 **unless `--accept`**.
  5. Rasterize with `rsvg-convert -w "$SIZE" -h "$SIZE"` when it is on `PATH`, else `"$WORK/svg2png"`.
  6. Per `origin: "recut"` and `origin: "legacy"` asset: **never fetched, never regenerated — only
     the sha is verified.** A recut's `derivedFrom` records the source blob (`<commit>:<path>`) and
     the exact `alphakey`/`monoflip` invocations so a human can reproduce it, but the script must
     not re-run them: the committed file already has alpha and `alphakey` exits 3 on it by design
     (R5), so a re-run that tried would fail every time. The recut itself is task 2 step 4, by hand,
     once.
  7. Verify every written PNG with `sips -g pixelWidth -g pixelHeight -g hasAlpha` and **fail** on
     `hasAlpha: no`, a non-square result, or a width below the manifest's `size` (legacy entries are
     exempt by `origin`).
  8. Rewrite `logos.manifest.json` (sha256s filled in, assets sorted by `id`) and regenerate
     `LOGOS.md`.
  9. `--check`: **offline and read-only.** It re-hashes every committed PNG against the manifest's
     `sha256`, checks the manifest/directory sets match, and checks `LOGOS.md` names every id — no
     `curl`, no `swiftc`, no writes — and exits non-zero on any mismatch. That is what makes it safe
     in the final verification block ("the assets are the ones the ledger claims, with **no
     network**") and what CI would run if the repo ever gets CI. **Upstream drift is a different
     question and is only asked on a real run** (step 4's `svgSha256` comparison), because asking it
     needs the network. `--only <id>` restricts a real run to one manifest id — the recovery path
     when a single mark has to be refetched without touching the other fifteen shas. Final line of a
     writing run: the absolute path of every PNG written plus
     `open each one before committing (R-L8)`.
  Parse JSON with `api/.venv/bin/python -c` one-liners rather than a `jq` dependency (`jq` is not
  guaranteed on the machine; the venv is).

- [ ] **Step 4: Seed the manifest from what is already committed.** Compute the shas:
```bash
cd <worktree>/ && \
  for f in app/CicadaApp/Sources/CicadaApp/Resources/logos/*.png; do \
    printf '%s %s\n' "$(basename "$f" .png)" "$(shasum -a 256 "$f" | cut -d' ' -f1)"; done
```
  Write one `origin: "legacy"` entry per existing PNG. Licence lines are **honest, not invented**:
  batch 1 (`claude-code`, `claude-desktop`, `codex`, `cursor`, `gemini-cli`, `hermes`, `openclaw`) →
  `"licence": "Vendor mark — no upstream licence recorded (committed 2026-07-03, 1a4811d)"`; batch 2
  (`instagram`, `linkedin`, `pinterest`, `reddit`, `telegram`, `tiktok`, `x`, `youtube`) →
  `"licence": "Vendor mark from a favicon service — no upstream licence recorded (committed 2026-08-31, cf2c449)"`.
  Every entry: `"restrictions": "Trademarked — nominative use only; identifies the product, never
  restyled or recoloured."`

- [ ] **Step 5:** `chmod +x scripts/fetch-logos.sh`; run `scripts/fetch-logos.sh --check` and confirm
      it exits 0 against the seeded manifest. Run the Python test — green. Run the full Python suite.

- [ ] **Step 6: Commit** — `git add tools/svg2png.swift tools/alphakey.swift tools/monoflip.swift
      scripts/fetch-logos.sh app/CicadaApp/Sources/CicadaApp/Resources/logos/logos.manifest.json
      app/CicadaApp/Sources/CicadaApp/Resources/logos/LOGOS.md api/tests/test_logo_manifest.py`
      (named files only — never `git add -A`).
      Message: `feat(track L): a maintainer pipeline for brand marks, and a ledger of the ones we ship (R-L2, R-L7)`

---

### Task 2: Fetch, eyeball, commit the real marks (R-L3, R-L5, R-L8)

The only task that touches the network. Every PNG it writes is opened with the Read tool before it
is staged.

**Files:**
- Create: `app/…/Resources/logos/{chrome,chatgpt,chatgpt-dark,claude,gemini,ollama,rss,firefox,brave}.png`
  (plus `ollama-dark.png` iff R4's guard accepts it)
- Modify: `app/…/Resources/logos/{telegram,x,codex}.png`; create `x-dark.png`, `codex-dark.png`
- Modify: `logos.manifest.json`, `LOGOS.md` (regenerated by the script)
- Test: `app/CicadaApp/Tests/CicadaAppTests/LogoAssetTests.swift` (new — T3, T4)

**Interfaces:**
- Produces: the asset set every later task maps onto; `LogoAssetTests.legacy128` and
  `LogoAssetTests.needsDarkVariant` as the two documented allowlists.
- Consumes: task 1's script and manifest.

- [ ] **Step 1: Failing tests** — `LogoAssetTests.swift` (T3 asset hygiene + T4 dark pairs). T2
      ("every bundled PNG is claimed") lands in task 4, when the maps that claim these files exist.

```swift
import XCTest
import AppKit
@testable import CicadaApp

/// T3/T4 (R-L7) — the bundled brand marks are square, big enough, and carry an
/// alpha channel; every monochrome mark ships the `-dark` sibling that keeps it
/// from disappearing on `CicadaTheme.surfaceElevated` (`#23252E` in dark mode).
///
/// This is the test that would have caught `x.png` (white on opaque black) and
/// `codex.png` (black on opaque white) shipping as opaque squares inside a
/// rounded card, and the 128 px favicon rasters of 2026-08-31 breaking the
/// 256 px floor batch 1 had held.
final class LogoAssetTests: XCTestCase {

    /// The 2026-08-31 favicon-service rasters (`cf2c449`). 128 px is the size
    /// the source served; upscaling would be fake resolution, so they are
    /// exempted by name and replaced only when a vendor SVG is sourced for
    /// them. `telegram` was on this list until Track L refetched it from
    /// Commons at 256 px — so if that fetch is the one R10 rejects, put
    /// `"telegram"` back and say so in task 2's "left out" note. `codex` was
    /// never on it: batch 1 shipped at 256.
    static let legacy128: Set<String> = [
        "instagram", "linkedin", "pinterest", "reddit", "tiktok", "youtube", "x", "x-dark",
    ]

    /// Marks that are a single flat colour and therefore invisible in one of
    /// the two themes without a sibling (R4). `codex` and `x` are the two
    /// recuts and are certain; `chatgpt` is here because its Commons SVG is
    /// monochrome — if R10's eyeball pass rejects that SVG and no `chatgpt`
    /// mark ships, drop it from this set in the same commit that drops the
    /// asset, and say so in task 2's "left out" note.
    static let needsDarkVariant: Set<String> = ["chatgpt", "codex", "x"]

    private func logoURLs() throws -> [URL] {
        let urls = Bundle.cicadaResources.urls(
            forResourcesWithExtension: "png", subdirectory: "Resources/logos"
        ) ?? []
        XCTAssertFalse(urls.isEmpty, "no bundled logos found — this test would pass vacuously")
        return urls
    }

    private func names() throws -> Set<String> {
        Set(try logoURLs().map { $0.deletingPathExtension().lastPathComponent })
    }

    func testEveryMarkIsSquareBigEnoughAndHasAlpha() throws {
        for url in try logoURLs() {
            let name = url.deletingPathExtension().lastPathComponent
            guard let rep = NSBitmapImageRep(data: try Data(contentsOf: url)) else {
                XCTFail("\(name).png did not decode")
                continue  // keep checking the rest rather than returning out of the loop
            }
            XCTAssertEqual(rep.pixelsWide, rep.pixelsHigh, "\(name).png is not square")
            let floor = Self.legacy128.contains(name) ? 128 : 256
            XCTAssertGreaterThanOrEqual(rep.pixelsWide, floor, "\(name).png is \(rep.pixelsWide) px")
            XCTAssertTrue(rep.hasAlpha, "\(name).png has no alpha — it will render as a hard square")
        }
    }

    func testEveryDarkSiblingHasABaseMark() throws {
        let all = try names()
        for name in all where name.hasSuffix("-dark") {
            XCTAssertTrue(all.contains(String(name.dropLast(5))), "\(name).png has no base mark")
        }
    }

    func testEveryMonochromeMarkShipsItsDarkSibling() throws {
        let all = try names()
        for name in Self.needsDarkVariant {
            XCTAssertTrue(all.contains(name), "\(name).png is missing")
            XCTAssertTrue(all.contains("\(name)-dark"), "\(name) is monochrome but ships no -dark sibling")
        }
    }
}
```

Run:
```bash
cd <worktree>/app/CicadaApp && \
  swift test --filter LogoAssetTests 2>&1 | tail -20
```

- [ ] **Step 2: Declare the new assets in `logos.manifest.json`** with empty `sha256`/`svgSha256` (the
      script fills them; empty means "new, accept and record"). Commons files and licences, verified
      live in the spike:

  | id | commonsFile | licence | restrictions |
  |---|---|---|---|
  | `chrome` | `Google_Chrome_icon_(February_2022).svg` | Public domain (PD-shape) — artist Google LLC | trademarked |
  | `chatgpt` | `ChatGPT-Logo.svg` | Public domain — artist OpenAI | trademarked |
  | `claude` | `Claude_AI_symbol.svg` | CC0 | — |
  | `rss` | `Feed-icon.svg` | MPL 1.1 (Mozilla) | — |
  | `telegram` | `Telegram_2019_Logo.svg` | Public domain — artist Telegram FZ LLC | trademarked |
  | `firefox` | `Firefox_logo,_2019.svg` | MPL 2 | trademarked |
  | `brave` | `Brave_lion_icon.svg` | MPL 2 | trademarked |
  | `ollama` | `Ollama-logo.svg` | MIT | — |
  | `gemini` | **resolve first — see step 3** | (record what `extmetadata` returns) | trademarked |

  Record the licence string **as `extmetadata` returns it** (`LicenseShortName` + `Artist`), not from
  this table, if the two ever disagree.

- [ ] **Step 3: Resolve the two marks the audit flagged as wordmarks.** `Google_Gemini_logo.svg` is a
      344×127 wordmark and `Brave_Logo_(2024).svg` is a 129×40 wordmark; a 28 pt square tile needs a
      *symbol*. Use the search step to find the square glyph:
```bash
cd <worktree>/ && \
UA="CicadaLogoFetch/1.0 (+https://github.com/rorosaga/cicada)" && \
curl -sS -A "$UA" -G "https://commons.wikimedia.org/w/api.php" \
  --data-urlencode action=query --data-urlencode format=json \
  --data-urlencode list=search --data-urlencode srnamespace=6 \
  --data-urlencode "srsearch=Gemini icon filetype:drawing" | head -c 2000
```
      Pick a **square** file whose `extmetadata` shows a public-domain/CC licence, put its exact name
      in the manifest, and record the licence. **Brave is already resolved in step 2's table** —
      `Brave_lion_icon.svg` is the square glyph, not the 129×40 `Brave_Logo_(2024).svg` wordmark —
      so only confirm it exists and is square; the rule below applies to it only if it does not.
      **If no square, freely-licensed Gemini glyph exists:
      commit no `gemini.png`** — and **delete its manifest row as well** (R1: no entry without a
      file; T6's `test_every_committed_png_has_a_manifest_entry_and_vice_versa` fails otherwise).
      `gemini-export` then keeps its SF Symbol (task 4 drops the `case "gemini-export": "gemini"`
      line, as its own note says) and the `google` provider keeps its blue monogram (task 6:
      `ContributorIdentity.logoName(provider: "google")` returns nil and `allProviderMarks` is three
      names, so `ContributorIdentityTests` needs the matching edit). Same rule for `brave`, whose
      only claimant is T2's `reservedForG119` allowlist.

- [ ] **Step 4: Recut the two opaque rasters (R5).** In the work dir, not in place:
      copy the two committed files into `$WORK` first (`git show`-clean copies of the opaque
      originals), key them there, and only then move the results over the tree's files:

      - `codex` (black mark, opaque white ground): `alphakey $WORK/codex.png $WORK/codex.rgba.png
        light` → `monoflip $WORK/codex.rgba.png $WORK/codex-dark.png`; install
        `codex.rgba.png` **as `Resources/logos/codex.png`** (replacing the opaque one) and
        `codex-dark.png` as the sibling.
      - `x` (white mark, opaque black ground): `alphakey $WORK/x.png $WORK/x-dark.png dark` →
        `monoflip $WORK/x-dark.png $WORK/x.rgba.png`; install `x.rgba.png` **as
        `Resources/logos/x.png`** and `x-dark.png` as the sibling.

      The base file is always the **dark-ink** variant (visible on a light ground) and `-dark` the
      light-ink one, because `LogoImage` looks up `-dark` only when `CicadaTheme.mode == .dark`. Add
      all four as `origin: "recut"` with `derivedFrom` naming the source blob as `<commit>:<path>`
      (`cf2c449:app/CicadaApp/Sources/CicadaApp/Resources/logos/x.png`,
      `1a4811d:…/codex.png` — the pre-recut bytes only exist in git after this lands) and the exact
      tool invocations. A later run of the script verifies their shas and regenerates nothing (task
      1 step 3.6).

- [ ] **Step 5: Run it for real.**
```bash
cd <worktree>/ && ./scripts/fetch-logos.sh
```
      Expect one `ok 256x256 from WxH` line per fetched asset and a final list of written paths.

- [ ] **Step 6: Eyeball every written PNG (R10 — this step is not optional).** Open each with the
      Read tool and record a one-line verdict in this checklist. The known failure mode is silent:
      in the spike the Apple Notes SVG rasterized *without its rounded-rect clip* and the tool
      reported success. Check specifically: correct current palette; correct rotation/orientation;
      no lost clip/mask (a squared-off corner where the mark is rounded); no letterboxing so severe
      the mark is unreadable at 28 pt; the `-dark` sibling is the same silhouette in the opposite
      ink. **Anything wrong is deleted, removed from the manifest, and listed here as "left out,
      reason" — never committed.**

- [ ] **Step 7:** Re-run `./scripts/fetch-logos.sh --check` (exits 0, no drift, `git status` clean
      apart from the intended files). Run `swift test --filter LogoAssetTests` — green — then the
      full Swift suite and the full Python suite (T6 now covers the new files).

- [ ] **Step 8: Commit** — stage each PNG by name plus the manifest and `LOGOS.md`.
      Message: `feat(track L): the real marks — official SVGs from Commons, x/codex recut with alpha (R-L3, R-L5, R-L8)`
      Body: the id list, the licence summary, and the "left out" list with reasons.

---

### Task 3: Installed app icons, and the drawn glyphs die (R-L1)

`ImportCatalogTests.testAGlyphAndAPngAreNeverBothDeclared` is the forcing function: flipping Chrome
to a PNG and deleting the glyphs must land in **one** commit, or the suite is red in between.

**Files:**
- Create: `app/…/Views/Common/InstalledAppIcon.swift`
- Modify: `app/…/Views/Common/OriginMark.swift:12-29`, `app/…/Views/Common/LogoImage.swift:139-207`,
  `app/…/Views/Capture/OriginIconography.swift:147-155`,
  `app/…/Views/Capture/Sheets/ImportFamilies.swift:69-96,163-224`,
  `app/…/Views/Capture/Sheets/AddSourceSheet.swift:143-166`
  (`IntegrationsView.swift` moves to task 4 — see step 5)
- Modify (tests): `ImportCatalogTests.swift:185-205`, `ImportFamilyTests.swift:30-57`,
  `OriginIconographyTests.swift:24-50`

**Interfaces:**
- Produces: `InstalledAppIcon.image(bundleId:size:) -> NSImage?` (main-actor cached — note the
  `size:` label; the type body below is the contract, this line is the summary);
  `OriginIconography.appBundleId(for:) -> String?`;
  `AddSourceTile.appBundleId -> String?`; `LogoImage.platformTile(name:bundleId:size:systemFallback:)`.
- Removes: `BrandGlyph`, `AddSourceTile.brandGlyph`, `OriginIconography.brandGlyph`, `ChromeGlyph`,
  `SafariGlyph`, `LogoImage.platformTile(…glyph:)`, `PlatformTile.glyph`.

- [ ] **Step 1: Failing tests.** In `OriginIconographyTests`, replace `testBrowsersUseDrawnGlyphs`
      (`:45-50`) with the bundle-id map, and fix `testOriginsWithoutABundledLogoReturnNil` (`:26-31`)
      — `chatgpt-export` and `rss` gain PNGs in task 4, so this test keeps only the two ids R2 says
      will never have one:

```swift
    /// R2/R-L3 — Apple's marks are never redistributed, so these two origins
    /// resolve *installed app icon → SF Symbol* with no PNG rung at all. A
    /// `logoName` here would demand a file the ruling forbids.
    func testAppleOriginsNeverNameABundledLogo() {
        XCTAssertNil(OriginIconography.logoName(for: "safari-bookmark"))
        XCTAssertNil(OriginIconography.logoName(for: "safari-tab"))
        XCTAssertNil(OriginIconography.logoName(for: "apple-notes"))
        XCTAssertNil(OriginIconography.logoName(for: "unknown"))
    }

    /// R-L1 — the mark for a browser/Apple-app origin is the icon of the app
    /// actually installed on this Mac. Sound by construction: Cicada only
    /// lists these channels because it reads that app's files off this Mac.
    /// The MAP is asserted, never the resolution — the suite must pass on a
    /// machine with no Chrome (R6).
    func testOriginsBackedByAnInstalledAppDeclareItsBundleId() {
        XCTAssertEqual(OriginIconography.appBundleId(for: "chrome-bookmark"), "com.google.Chrome")
        XCTAssertEqual(OriginIconography.appBundleId(for: "safari-bookmark"), "com.apple.Safari")
        XCTAssertEqual(OriginIconography.appBundleId(for: "safari-tab"), "com.apple.Safari")
        XCTAssertEqual(OriginIconography.appBundleId(for: "apple-notes"), "com.apple.Notes")
        XCTAssertNil(OriginIconography.appBundleId(for: "claude-code"))
        XCTAssertNil(OriginIconography.appBundleId(for: "telegram"))
    }
```

      In `ImportCatalogTests`, delete `testAGlyphAndAPngAreNeverBothDeclared` (`:197-205` — it
      asserts a concept that no longer exists) and rewrite `testNonBrandedTilesDeclareNoLogo`
      (`:185-191`):

```swift
    /// Chat export (two vendors), a local file pick, a pasted link and the
    /// calendar keep their SF Symbol — no single brand mark exists for any of
    /// them (R3: the Commons calendar icon is *Google* Calendar, and this row
    /// is any ICS publisher). Safari and Apple Notes are nil for a different
    /// reason: R-L3 forbids redistributing Apple's marks, so they resolve
    /// through `appBundleId` instead.
    func testTilesWithNoSingleBrandMarkDeclareNoLogo() {
        for tile in [AddSourceTile.chatExport, .bookmarksFile, .pasteLink, .calendar,
                     .safari, .appleNotes] {
            XCTAssertNil(tile.logoName, tile.rawValue)
        }
        XCTAssertEqual(AddSourceTile.chrome.logoName, "chrome")
        XCTAssertEqual(AddSourceTile.rssFeed.logoName, "rss")
    }

    /// R-L1 — the browsers and Apple Notes wear the installed app's icon in
    /// the catalog too, so the `+` sheet, Integrations and the Sleep desk
    /// cannot disagree about what Safari looks like.
    func testBrowserAndAppleTilesDeclareTheirBundleId() {
        XCTAssertEqual(AddSourceTile.safari.appBundleId, "com.apple.Safari")
        XCTAssertEqual(AddSourceTile.chrome.appBundleId, "com.google.Chrome")
        XCTAssertEqual(AddSourceTile.appleNotes.appBundleId, "com.apple.Notes")
        XCTAssertNil(AddSourceTile.telegram.appBundleId)
    }
```

      In `ImportFamilyTests`, replace `testBrowserTilesCarryDrawnGlyphsNotDownloadedPNGs` (`:33-41`)
      with a "every tile has *some* mark" invariant, and leave
      `testFamilyPreviewMarksAreItsFirstBrandedMembers` (`:44-48`) **unchanged** — it must keep
      passing, which is what forces `previewMarks` to count `appBundleId`:

```swift
    /// R-L1 — no tile is markless: a PNG, an installed app's icon, or its own
    /// SF Symbol. The drawn glyphs are gone (they were wrong on four axes for
    /// Chrome and an invented tint for Safari).
    func testEveryTileCarriesSomeMark() {
        for tile in AddSourceTile.allCases {
            XCTAssertTrue(tile.logoName != nil || tile.appBundleId != nil || !tile.icon.isEmpty,
                          "\(tile.rawValue) has no mark at all")
        }
    }
```

      **And fix `testAnUnbrandedFamilyStillWearsItsMembersSymbols` (`:51-57`) in the same commit —
      the second forcing function, and the one the plan's first draft missed.** It asserts
      `ImportFamily.files.previewMarks == ImportFamily.files.members`, which stops being true the
      moment `previewMarks` counts `appBundleId`: `.appleNotes` gains `com.apple.Notes`, becomes the
      family's only branded member, and Files previews `[.appleNotes]` instead of all three. The
      invariant worth keeping is the one its own doc comment states — *never an empty cluster, never
      more than four* — and the fall-back-to-members path is still exercised, just by a different
      family: `chatExports` is now the only one whose members carry neither a PNG nor a bundle id
      (`testFamilyPreviewMarksAreItsFirstBrandedMembers` already pins
      `chatExports.previewMarks == [.chatExport]`, which is that path).

```swift
    /// A family whose members carry no PNG and no installed-app icon still
    /// wears marks — never an empty cluster on the top-level tile. Files
    /// stopped being that family in Track L (R-L1 gave Apple Notes a bundle
    /// id, so it is the family's one branded member); `chatExports` is, and
    /// `testFamilyPreviewMarksAreItsFirstBrandedMembers` pins it. What is
    /// asserted here is the shape every family must hold.
    func testEveryFamilyWearsBetweenOneAndFourMarks() {
        XCTAssertEqual(ImportFamily.files.previewMarks, [.appleNotes],
                       "Apple Notes is the Files family's only branded member (R-L1)")
        for family in ImportFamily.allCases {
            XCTAssertFalse(family.previewMarks.isEmpty, family.rawValue)
            XCTAssertLessThanOrEqual(family.previewMarks.count, 4, family.rawValue)
        }
    }
```

- [ ] **Step 2: `InstalledAppIcon.swift`.**

```swift
import AppKit
import SwiftUI

/// The icon of an app installed on THIS Mac, by bundle id (R-L1).
///
/// Cicada only offers a Chrome / Safari / Apple Notes channel because it reads
/// that app's own files off this Mac, so the app is present by construction and
/// its icon is already on disk. Using it redistributes nothing (the trademark
/// question evaporates — R-L3 forbids committing Apple's marks), never goes
/// stale when a vendor rebrands, and degrades cleanly: `urlForApplication`
/// returns nil on a machine where the app was removed and the caller falls
/// through to the bundled PNG, then to the SF Symbol.
///
/// Two caveats worth stating rather than discovering: the icon is
/// Launch-Services-resolved, so asking for `com.google.Chrome` on a machine
/// running Chrome Canary answers with whichever bundle claims that id; and
/// `NSWorkspace.icon(forFile:)` is main-actor work, so it is cached exactly the
/// way `LogoImage.cache` caches a decoded PNG — a repaint is a dictionary hit,
/// never a Launch Services round-trip.
@MainActor
enum InstalledAppIcon {
    /// `nil` is cached too (as `.some(nil)`): "this app is not installed" is an
    /// answer worth remembering, or every frame of a scrolling list re-asks
    /// Launch Services the same question.
    private static var cache: [String: NSImage?] = [:]

    static func image(bundleId: String, size: CGFloat) -> NSImage? {
        if let cached = cache[bundleId] { return cached?.copyResized(to: size) }
        let resolved: NSImage? = NSWorkspace.shared
            .urlForApplication(withBundleIdentifier: bundleId)
            .map { NSWorkspace.shared.icon(forFile: $0.path) }
        cache[bundleId] = resolved
        return resolved?.copyResized(to: size)
    }

}
```
      **No `isResolvable`.** An earlier draft of this plan exported one; nothing in Track L calls it
      (`OriginMark` and `PlatformTile` both branch on `if let icon = …image(bundleId:size:)`), and an
      unused public rung is exactly the kind of dead API the T2 test exists to prevent on the asset
      side. Add it only when a call site appears.
      `copyResized(to:)` is a tiny private `NSImage` extension in the same file (`let c = copy() as!
      NSImage; c.size = NSSize(width: size, height: size); return c`) — `icon(forFile:)` returns a
      multi-representation image and setting `size` picks the right rep at draw time.

- [ ] **Step 3: Precedence.** `OriginMark.body` becomes app icon → PNG → SF Symbol, with the doc
      comment rewritten to say why the glyph rung is gone:

```swift
/// One origin, one mark, at any size: the installed app's icon → a bundled
/// PNG → the origin's SF Symbol in its colour (R-L1). The Sleep queue rows,
/// the study desk, the consolidation history and the Sources grid all use it,
/// so an episode reads the same everywhere and the same as its tile in the
/// import catalog.
///
/// The drawn-glyph rung that used to sit between the PNG and the symbol is
/// gone: `ChromeGlyph` was wrong on four independent axes (pre-2015 palette,
/// ~90° rotation, an undersized centre disc, flat fills instead of gradients)
/// and `SafariGlyph` was Apple's compass tinted an invented blue. A
/// wrong-coloured mark that appears only when an asset is missing looks like a
/// logo and isn't — worse than the honest SF Symbol.
```
      Body: `if let bundleId = OriginIconography.appBundleId(for: origin), let icon =
      InstalledAppIcon.image(bundleId: bundleId, size: size) { Image(nsImage: icon).resizable()
      .interpolation(.high).scaledToFit() } else if let name = …` (unchanged PNG rung) `else` (SF
      Symbol rung, unchanged).

- [ ] **Step 4: `PlatformTile` takes a bundle id.** Add `bundleId: String?` to `PlatformTile` and to
      `platformTile(name:bundleId:size:systemFallback:)` (default `nil`, so the ~dozen existing call
      sites keep compiling — a defaulted parameter in the middle still lets Swift resolve
      `platformTile(name:size:systemFallback:)`), drawn ahead of the PNG rung. **Delete** the glyph
      overload (`LogoImage.swift:158-170`) and `PlatformTile.glyph` (`:177-179`, `:196-197`),
      collapsing the `ZStack` to app icon → PNG → `systemFallback`.
      **`PlatformTile` loses its `<Glyph: View>` generic parameter with it** — `glyph` was the only
      member that used it, which is why `platformTile` has to spell `PlatformTile<EmptyView>(…)`
      today (`:155`). It becomes a plain `private struct PlatformTile: View`, and the three
      `PlatformTile<Glyph>.markSize(for:)` references (`:169`, `:183`, `:185`) become
      `PlatformTile.markSize`. Leave the mark's `clipShape` for task 5.

- [ ] **Step 5: Delete the abstraction.** In `ImportFamilies.swift`: `BrandGlyph` (`:78-82`),
      `AddSourceTile.brandGlyph` (`:85-95` — the member only; the `extension AddSourceTile` at
      `:84` also holds `routeLines` and stays), `ChromeGlyph` (`:160-188`), `SafariGlyph`
      (`:190-201`);
      collapse `MemberMark` (`:203-224`) to a single
      `LogoImage.platformTile(name: tile.logoName ?? "", bundleId: tile.appBundleId, size: size,
      systemFallback: tile.icon)` and rewrite the comment at `:203-206` to say the three-way switch
      is gone because the precedence now lives entirely in `PlatformTile`. Change `previewMarks`
      (`:72-75`) to `let branded = members.filter { $0.logoName != nil || $0.appBundleId != nil }`.
      In `OriginIconography.swift`, delete `brandGlyph` (`:147-155`) and add `appBundleId` with the
      doc comment from R-L1. In `AddSourceSheet.swift`, add `var appBundleId: String?` (safari →
      `com.apple.Safari`, chrome → `com.google.Chrome`, appleNotes → `com.apple.Notes`, else nil),
      flip `.chrome` to `"chrome"` and `.rssFeed` to `"rss"` in `logoName` (`:152-166`), and rewrite
      the R7 escape-hatch paragraph in its doc comment (`:143-151`) to record that the hatch was
      taken.
      **`IntegrationsView.swift`'s `mark` (`:133-148`) needs a restructure, not one extra argument.**
      Today it is `if let logoName = ConnectedChannelRow.logoName(for: channel.id) { platformTile… }
      else { the tint circle }`, so a channel with **no PNG but a bundle id** — `safari-bookmarks`,
      `safari-tabs`, `notes`, exactly the three R2 forbids a PNG for — would never reach the tile
      and Integrations would keep disagreeing with the Sleep desk about Safari (R6). Compute both
      rungs, and take the tile when *either* is present:

```swift
    @ViewBuilder
    private var mark: some View {
        // R6 — one precedence, three surfaces. A channel with no bundled PNG
        // but an installed app (Safari, Apple Notes — R2 forbids their PNGs)
        // must still reach `PlatformTile`, or this page draws a tint circle
        // where the Sleep desk draws the app's own icon.
        let logoName = ConnectedChannelRow.logoName(for: channel.id)
        let bundleId = OriginIconography.appBundleId(for: ConnectedChannelRow.origin(forChannel: channel.id))
        if logoName != nil || bundleId != nil {
            LogoImage.platformTile(name: logoName ?? "", bundleId: bundleId, size: 28,
                                   systemFallback: ConnectedChannelRow.icon(for: channel.id))
        } else {
            // the existing tint circle (`:138-146`), unchanged
        }
    }
```
      **Ordering:** `origin(forChannel:)` and the delegating `logoName` both land in **task 4**, so
      do this whole `mark` rewrite there (task 4 step 4) rather than reaching for a
      `channel.id`-shaped stand-in here. Task 3 leaves `IntegrationsView` untouched; drop it from
      this task's Files list.

- [ ] **Step 6:** `swift build` then `swift test` — 0 failures. Grep the tree for stragglers:
```bash
cd <worktree>/app/CicadaApp && \
  rg -n "BrandGlyph|brandGlyph|ChromeGlyph|SafariGlyph|platformTile\(glyph" Sources Tests
```
      (must print nothing).

- [ ] **Step 7: Commit** — `feat(track L): the installed app's icon is the mark, and the drawn glyphs are deleted (R-L1)`

---

### Task 4: One map (R-L4) — plus T1, T2, T5

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/ChannelMarks.swift`
- Modify: `app/…/Views/Capture/OriginIconography.swift:20-145`,
  `app/…/Views/Capture/ConnectedChannelRow.swift:215-228`,
  `app/…/Views/Settings/IntegrationsView.swift:133-148`
- Test: `OriginIconographyTests.swift` (T1), `LogoAssetTests.swift` (T2),
  `app/CicadaApp/Tests/CicadaAppTests/ChannelMarkTests.swift` (new — T5)

**Interfaces:**
- Produces: `OriginIconography.allKnownOrigins: [String]`, extended `logoName`, new
  `gemini-export` / `saved-link` label+symbol+colour cases,
  `ConnectedChannelRow.origin(forChannel:) -> String`.
- Consumes: nothing new.

- [ ] **Step 1: Failing tests.**

```swift
// OriginIconographyTests.swift — T1 replaces the hardcoded 14-string array.

    /// T1 (R-L7) — every id in the map has a file, driven from the exported
    /// list rather than a hand-kept array: the old version iterated 14
    /// hardcoded strings, so a case added to the switch was silently
    /// uncovered. Adding a case without adding it to `allKnownOrigins` is the
    /// bug this pair is here to make loud.
    func testEveryDeclaredLogoExistsInTheBundle() {
        XCTAssertFalse(OriginIconography.allKnownOrigins.isEmpty)
        for origin in OriginIconography.allKnownOrigins {
            guard let name = OriginIconography.logoName(for: origin) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(origin) → \(name).png is not bundled")
        }
    }

    /// R-L4 — the ids the audit found with no case at all: they read as
    /// "Gemini-export" and "Saved-link" (a `.capitalized` id) under a generic
    /// `tray`, on a Sources card the backend ships today
    /// (`source_overview.CATALOG`).
    func testTheOriginsThatHadNoCaseNowReadAsProducts() {
        XCTAssertEqual(OriginIconography.label(for: "gemini-export"), "Gemini export")
        XCTAssertEqual(OriginIconography.label(for: "saved-link"), "Saved link")
        XCTAssertNotEqual(OriginIconography.symbol(for: "gemini-export"), "tray")
        XCTAssertNotEqual(OriginIconography.symbol(for: "saved-link"), "tray")
    }

    /// The audit found nine unreachable `case` labels (Swift takes the first
    /// match): `codex`/`claude-desktop`/`cursor` a second time in `label`
    /// (`:57-59`), `codex`/`cursor` again in `symbol` (`:89`) and `color`
    /// (`:115`), and `claude-desktop` again in each (`:90`, `:116`). Harmless
    /// today because a PNG wins for all three — but unreachable code that
    /// tells the next editor a lie.
    ///
    /// `gemini-cli` is NOT one of them: it appears exactly once in `symbol`
    /// and once in `color`, so `terminal` is its live answer and the cleanup
    /// must keep it reachable rather than folding it into the `bubble` list.
    func testTheSecondCopyOfEachDuplicatedCaseIsGone() {
        XCTAssertEqual(OriginIconography.symbol(for: "gemini-cli"), "terminal")
        XCTAssertEqual(OriginIconography.symbol(for: "codex"), "bubble.left.and.bubble.right")
        XCTAssertEqual(OriginIconography.label(for: "codex"), "Codex")
        XCTAssertEqual(OriginIconography.label(for: "cursor"), "Cursor")
    }
```

```swift
// LogoAssetTests.swift — T2, the reverse direction nothing tested before.

    /// T2 (R-L7) — every bundled PNG is claimed by some map. Catches an
    /// orphaned asset (dead bytes in every shipped app) and a renamed id that
    /// left its file behind.
    func testEveryBundledMarkIsClaimedBySomeMap() throws {
        // Reserved for G119 (Arc/Firefox/Brave as *channels*): the marks are
        // fetched and licence-recorded now, while the channel ids that will
        // claim them do not exist yet (R1 — a deliberate, reviewed state).
        let reservedForG119: Set<String> = ["firefox", "brave"]
        let claimed = Set(
            OriginIconography.allKnownOrigins.compactMap(OriginIconography.logoName(for:))
            + AddSourceTile.allCases.compactMap(\.logoName)
            + ChannelMarks.allChannelIds.compactMap(ConnectedChannelRow.logoName(for:))
            + ContributorIdentity.allProviderMarks
            + ["claude-code", "cursor", "openclaw", "codex", "claude-desktop", "hermes", "gemini-cli"]  // AgentTile ids
        )
        for name in try names() {
            let base = name.hasSuffix("-dark") ? String(name.dropLast(5)) : name
            XCTAssertTrue(claimed.contains(base) || reservedForG119.contains(base),
                          "\(name).png is bundled but nothing maps to it")
        }
    }
```
      (`ContributorIdentity.allProviderMarks` lands in task 6 — until then inline the four names it
      will return and replace them there, or land T2's provider half with task 6. Either is fine;
      say which in the commit body.)

```swift
// ChannelMarkTests.swift (new) — T5.
import XCTest
@testable import CicadaApp

/// T5 (R-L7) — no channel falls through to the generic `tray`, and a channel's
/// mark is the SAME picture as its origin's. Before Track L, `chat-export:claude`
/// and `chat-export:chatgpt` rendered identically (one shared SF bubble) and
/// Chrome was a plain blue globe in Settings → Integrations while being a drawn
/// glyph on the Sleep desk: one source, three pictures.
final class ChannelMarkTests: XCTestCase {

    func testNoChannelFallsThroughToTheGenericTray() {
        for id in ChannelMarks.allChannelIds {
            let hasLogo = ConnectedChannelRow.logoName(for: id) != nil
            let hasBundle = OriginIconography.appBundleId(for: ConnectedChannelRow.origin(forChannel: id)) != nil
            XCTAssertTrue(hasLogo || hasBundle || ConnectedChannelRow.icon(for: id) != "tray", id)
        }
    }

    /// Mirrors `api/services/source_overview.py::CATALOG`'s `mark` column
    /// verbatim (`:50-69`) — a channel resolves to the origin id the backend
    /// already hands the app for that row, so there is one map, not two
    /// (R-L4). Note `files` → `bookmark`, not `saved-link`: `saved-link` is
    /// in that row's `origins` tuple, while `mark` (the column the app reads)
    /// is `bookmark`. Both resolve to a nil `logoName`, so the picture is the
    /// same either way — but the map has to say what the backend says.
    func testChannelOriginsMirrorTheBackendCatalog() {
        let expected: [String: String] = [
            "chat-export:claude": "claude-export", "chat-export:chatgpt": "chatgpt-export",
            "chrome-bookmarks": "chrome-bookmark", "safari-bookmarks": "safari-bookmark",
            "safari-tabs": "safari-tab", "notes": "apple-notes", "rss": "rss",
            "calendar": "calendar", "pinterest": "pinterest", "reddit": "reddit-saved",
            "x": "x-bookmarks", "telegram": "telegram", "files": "bookmark",
        ]
        XCTAssertEqual(Set(expected.keys), Set(ChannelMarks.allChannelIds))
        for (id, origin) in expected {
            XCTAssertEqual(ConnectedChannelRow.origin(forChannel: id), origin, id)
        }
    }

    /// The two chat exports must not render as the same picture.
    func testTheTwoChatExportsGetDifferentMarks() {
        XCTAssertEqual(ConnectedChannelRow.logoName(for: "chat-export:claude"), "claude-desktop")
        XCTAssertEqual(ConnectedChannelRow.logoName(for: "chat-export:chatgpt"), "chatgpt")
    }
}
```
      `ChannelMarks` is a new **source** file, `Sources/CicadaApp/Views/Capture/ChannelMarks.swift`
      (not a test file — `LogoAssetTests`'s T2 reads it too), holding one member:
      `static let allChannelIds: [String]` mirroring `channel_registry.CHANNEL_IDS` verbatim (the
      13 ids the step-5 command prints), with the same "a 14th id needs this list AND the switch
      updated together" comment `IntegrationsViewTests.swift:20-22` already carries — and a line
      pointing at that test, which keeps its own copy of the list for the category map.

- [ ] **Step 2: The map.** Rewrite `OriginIconography.logoName` (`:122-145`) with the doc comment
      rewritten to name R-L4 and R2:

```swift
    /// The bundled PNG under `Resources/logos/` for an origin — the ONE id →
    /// asset map (R-L4). `ConnectedChannelRow.logoName` delegates here through
    /// `origin(forChannel:)`, and `source_overview.SourceSpec.mark` is already
    /// an origin id, so the Sleep desk, the Sources grid, the `+` catalog and
    /// Settings → Integrations cannot disagree about what a source looks like.
    ///
    /// `mcp` shares Claude Code's mark: it is the same harness under its
    /// legacy id. Safari and Apple Notes are deliberately absent — R-L3
    /// forbids redistributing Apple's marks, so they resolve through
    /// `appBundleId` and then their own SF Symbol. Calendar is absent for a
    /// different reason (R3): the only freely-licensed calendar mark is
    /// *Google* Calendar and this origin is any ICS publisher.
    ///
    /// Exhaustive by test over `allKnownOrigins`
    /// (`OriginIconographyTests.testEveryDeclaredLogoExistsInTheBundle`), so a
    /// typo fails before it ships a blank mark.
    static func logoName(for origin: String) -> String? {
        switch origin {
        case "claude-code", "mcp": "claude-code"
        case "codex": "codex"
        case "claude-export", "claude-desktop": "claude-desktop"
        case "cursor": "cursor"
        case "gemini-cli": "gemini-cli"
        case "chatgpt-export": "chatgpt"
        case "gemini-export": "gemini"
        case "chrome-bookmark": "chrome"
        case "rss": "rss"
        case "telegram": "telegram"
        case "pinterest": "pinterest"
        case "reddit-saved", "reddit": "reddit"
        case "x-bookmarks", "x": "x"
        case "linkedin-saved": "linkedin"
        case "tiktok-saved", "tiktok-history": "tiktok"
        case "instagram-saved": "instagram"
        case "youtube-playlist": "youtube"
        default: nil
        }
    }
```
      (Drop `case "gemini-export": "gemini"` if task 2 left `gemini.png` out — T1 would fail
      otherwise, which is the test doing its job.)

- [ ] **Step 3: The gaps and the dead cases.** In `label`: add `case "gemini-export": "Gemini export"`
      and `case "saved-link": "Saved link"`; delete the shadowed `"codex"` (`:57`),
      `"claude-desktop"` (`:58`), `"cursor"` (`:59`) and fold the G105 comment into the surviving
      cases. In `symbol`: add `case "gemini-export": "square.and.arrow.down"`, `case "saved-link":
      "link"`; narrow `case "codex", "cursor", "gemini-cli": "terminal"` (`:89`) to
      `case "gemini-cli": "terminal"` — **`gemini-cli` is the one label in that case that is NOT
      shadowed by `:71`, and `testTheSecondCopyOfEachDuplicatedCaseIsGone` asserts it still answers
      `terminal`, so do not fold it into the `bubble.left.and.bubble.right` list** — and delete the
      unreachable `case "claude-desktop"` (`:90`). In `color`: the same narrowing at `:115`
      (`case "gemini-cli": CicadaTheme.textPrimary` survives; `codex`/`cursor` go, shadowed by
      `:99-100`) and delete `case "claude-desktop"` (`:116`). Add `allKnownOrigins` above `label`:

```swift
    /// Every origin id a writer stamps today, plus the defensive aliases. The
    /// bundle test drives off this list, so the list and the switches cannot
    /// drift — adding a case without adding it here is the bug (T1). Verified
    /// against the backend by
    /// `grep -rhoE '"origin": *"[a-z0-9:_-]+"|origin *= *"[a-z0-9:_-]+"' api mcp --include='*.py'`
    /// (quote the `--include`; zsh globs it otherwise) and against
    /// `api/services/source_overview.py::CATALOG`'s `mark`/`origins` columns.
    static let allKnownOrigins: [String] = [
        "mcp", "claude-code", "claude-desktop", "cursor", "codex", "gemini-cli",
        "claude-export", "chatgpt-export", "gemini-export",
        "chrome-bookmark", "safari-bookmark", "safari-tab", "apple-notes",
        "telegram", "rss", "calendar", "share-sheet", "bookmark", "saved-link",
        "instagram-saved", "youtube-playlist", "pinterest", "reddit-saved", "reddit",
        "x-bookmarks", "x", "linkedin-saved", "tiktok-saved", "tiktok-history", "unknown",
    ]
```

- [ ] **Step 4: Delegate.** Replace `ConnectedChannelRow.logoName` (`:215-228`, doc + switch) with
      `origin(forChannel:)` + a one-line delegation, doc comment citing R-L4 and R7 (why `icon`/
      `tint` do *not* delegate). `origin(forChannel:)` is a total function over the 13 ids with a
      `default: id` fall-through, so an id the backend adds later resolves to itself rather than
      trapping. Then rewrite `IntegrationsView`'s `mark` (`:133-148`) as task 3 step 5 spells out —
      **compute both `logoName` and `bundleId` and take `platformTile` when either is non-nil**, or
      Safari / Apple Notes (no PNG by R2) keep the tint circle and this page still disagrees with
      the Sleep desk about Safari (R6).

- [ ] **Step 5:** `swift test` — 0 failures. Then a read-only cross-check that the Swift list still
      matches the backend:
```bash
cd <worktree>/ && \
  api/.venv/bin/python -c "from api.services import channel_registry as c; print(c.CHANNEL_IDS)"
```

- [ ] **Step 6: Commit** — `feat(track L): one id → mark map, and the ids that had no case at all (R-L4, R-L7)`

---

### Task 5: Dark mode — `-dark` resolution, the plate and the clip (R-L5)

**Files:**
- Modify: `app/…/Views/Common/LogoImage.swift:48-56,115-137,187-206`,
  `app/…/Views/Connect/ConnectView.swift:427-453`
- Test: `app/CicadaApp/Tests/CicadaAppTests/LogoImageTests.swift`

**Interfaces:**
- Produces: `LogoImage.resolvedName(for:) -> String?` — the `-dark` sibling under
  `CicadaTheme.mode == .dark`, else the base, else nil.
- Consumes: the assets from task 2.

- [ ] **Step 1: Failing test** (appended to `LogoImageTests`):

```swift
    /// R-L5 — a monochrome mark ships a `-dark` sibling and `LogoImage` picks
    /// it under a dark theme. `CicadaTheme.surfaceElevated` is `#23252E` in
    /// dark, so a black-on-transparent ChatGPT mark is simply invisible there;
    /// the white plate `AgentTile` used to paper over this with is worse than
    /// the disease (it puts every COLOUR mark on a white chip).
    func testDarkModePrefersTheDarkSiblingWhenOneIsBundled() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }

        CicadaTheme.mode = .dark
        XCTAssertEqual(LogoImage.resolvedName(for: "chatgpt"), "chatgpt-dark")
        XCTAssertEqual(LogoImage.resolvedName(for: "x"), "x-dark")
        // A colour mark has no sibling and must not be rewritten.
        XCTAssertEqual(LogoImage.resolvedName(for: "chrome"), "chrome")

        CicadaTheme.mode = .light
        XCTAssertEqual(LogoImage.resolvedName(for: "chatgpt"), "chatgpt")
        XCTAssertEqual(LogoImage.resolvedName(for: "chrome"), "chrome")
    }

    /// An id nothing bundles resolves to nil in both themes — the caller's
    /// SF-Symbol fallback, never a blank square.
    func testAnUnbundledNameResolvesToNilInBothModes() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertNil(LogoImage.resolvedName(for: "not-a-real-mark"))
        }
    }

    /// A `-dark` file is never reachable on its own: asking for the sibling by
    /// name must not append a second suffix.
    func testADarkNameIsNeverDoubleSuffixed() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        CicadaTheme.mode = .dark
        XCTAssertEqual(LogoImage.resolvedName(for: "chatgpt-dark"), "chatgpt-dark")
    }
```

- [ ] **Step 2: `resolvedName`.** Add above `exists(name:)`, and route `bundledImage(for:)` and
      `PlatformTile`'s PNG rung through it. `exists(name:)` keeps its current meaning (does the BASE
      file exist) — it is the layout gate every caller uses and the pairing invariant (T4) means a
      `-dark` never exists without its base.

```swift
    /// The file to load for `name` under the active theme (R-L5): a
    /// `<name>-dark` sibling when the theme is dark and one is bundled, else
    /// `<name>`, else nil. Only monochrome marks ship a sibling (R4) — a
    /// coloured mark reads in both themes and is never recoloured.
    ///
    /// Reading `CicadaTheme.mode` inside a SwiftUI `body` subscribes the view
    /// to the theme, so a light/dark flip repaints the mark with no extra
    /// wiring — the same mechanism every `CicadaTheme.<token>` call site uses.
    static func resolvedName(for name: String) -> String? {
        if CicadaTheme.mode == .dark, !name.hasSuffix("-dark"), exists(name: "\(name)-dark") {
            return "\(name)-dark"
        }
        return exists(name: name) ? name : nil
    }
```
      In `bundledImage(for:)` the cache key must be the **resolved** name, or a theme flip serves the
      other theme's cached bytes. Resolve first, then look up.

      **`taskKey` has to carry the resolved name too, or the flip never repaints.** `LogoImage.body`
      loads through `.task(id: taskKey)` (`:48`, `:51-56`) and `taskKey` is
      `"bundled:\(name)"` — a light/dark flip does not change it, so the `.task` never re-runs and
      the stale `NSImage` stays on screen. The subscription the doc comment above promises only
      exists if `CicadaTheme.mode` is read during `body` evaluation, which is exactly what putting
      the resolution in `taskKey` does:

```swift
    private var taskKey: String {
        switch source {
        // R-L5: reading `CicadaTheme.mode` (through `resolvedName`) HERE is
        // what subscribes the view to the theme and what changes the task id
        // on a flip, so the mark reloads its `-dark` sibling. Keying on the
        // bare name repaints nothing.
        case let .bundled(name): "bundled:\(Self.resolvedName(for: name) ?? name)"
        case let .entity(id, _, _): "entity:\(id):\(store.bank)"
        }
    }
```
      With that in place `bundledImage(for:)` can stay nonisolated and simply resolve again before
      its cache lookup — the two agree because both call `resolvedName`.

- [ ] **Step 3: Drop the plate and the clip.** `ConnectView.swift:435` — delete
      `.padding(6).background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.92)))`,
      leaving the tile's own border, and replace the surrounding comment with why: `codex.png` now
      has alpha and a `-dark` sibling, so the plate has nothing left to hide and was making every
      *colour* mark sit on a white chip in dark mode. `LogoImage.swift:195` — delete
      `.clipShape(RoundedRectangle(cornerRadius: cornerRadius * 0.5))`: with every asset carrying
      alpha there is no full-bleed square to round off, and a 2.4 pt radius inside a 5.6 pt card read
      as *squarer* than the card behind it.

- [ ] **Step 4:** `swift test` — 0 failures.

- [ ] **Step 5: Commit** — `feat(track L): a monochrome mark ships its dark sibling, and the white plate goes (R-L5)`

---

### Task 6: Contributors — `cicada` is the system, and the router is who billed (R-L6)

**Files:**
- Modify: `api/services/git_service.py:266-314`, `api/models/schemas.py:187-205`
- Create: `app/…/Views/Contributors/ContributorIdentity.swift`
- Modify: `app/…/Views/Contributors/ContributorsView.swift:106-135,196-198,408-492`
- Test: `api/tests/test_contributors.py:155-200` (T7 + two updated rows),
  `app/CicadaApp/Tests/CicadaAppTests/ContributorIdentityTests.swift` (new)

**Interfaces:**
- Produces: `git_service.CICADA_AUTHOR = "cicada"`; `_classify_author_kind` → `system`;
  `_ROUTER_PREFIXES`; extended `_PROVIDER_SUBSTRINGS`; Swift `ContributorIdentity.displayName(author:
  kind:) -> String`, `.logoName(provider: String?) -> String?`,
  `.allProviderMarks: [String]` (T2 concatenates it, so it must be an array, not a Set),
  `.monogram(for: String) -> String`.
- Wire: `Contributor.kind` gains the value `"system"` and `provider` gains five new values. **Both
  are already `str`/`Optional[str]`** — no schema shape change, so `/contributors`' ETag
  (`git_head`) and `VersionVector` need no edit. An older client's `default:` branch renders a
  `system` row as a provider badge, which is exactly today's behaviour.

- [ ] **Step 1: Failing tests** — extend `api/tests/test_contributors.py`:

```python
def test_classify_author_kind_system():
    """R-L6 — `cicada` is the literal author of system maintenance with no
    model and no user in the loop (the state snapshot, the split-out decay
    commit, the one-shot migrations). It used to classify as a *model* with
    provider "other", so Cicada's own commits showed as an anonymous grey "?"
    in its own contributors list."""
    assert git_service._classify_author_kind("cicada") == "system"
    assert git_service._provider_for_model("cicada") is None


def test_provider_for_model_router_before_the_first_slash_wins():
    """R9/R-L6 — an OpenRouter id names the model it proxied; the router is who
    billed. A bare substring pass would map `openrouter/z-ai/glm-5.2` to
    nothing and `openrouter/anthropic/claude-opus-4` to Anthropic, which is a
    lie about who was paid."""
    assert git_service._provider_for_model("openrouter/z-ai/glm-5.2") == "openrouter"
    assert git_service._provider_for_model("openrouter/anthropic/claude-opus-4") == "openrouter"
    assert git_service._provider_for_model("ollama/llama3.2") == "ollama"
    # A provider prefix that is NOT a router keeps the substring behaviour.
    assert git_service._provider_for_model("anthropic/claude-opus-4") == "anthropic"


def test_provider_for_model_open_weight_families():
    assert git_service._provider_for_model("llama-3") == "meta"
    assert git_service._provider_for_model("mistral-large") == "mistral"
    assert git_service._provider_for_model("mixtral-8x7b") == "mistral"
    assert git_service._provider_for_model("deepseek-v3") == "deepseek"
    assert git_service._provider_for_model("qwen2.5-72b") == "qwen"
```
      **Update the two rows this breaks** at `:191-196`: `test_provider_for_model_other_and_non_model`
      loses its `mistral-large` / `llama-3` assertions (they now have real providers) and gains
      genuinely unmatched ids — `assert git_service._provider_for_model("glm-5.2") == "other"` — plus
      the existing `user`/`unknown` → `None` lines. The anchored o-series test (`:175-178`) must
      keep passing untouched.

```swift
// ContributorIdentityTests.swift (new)
import XCTest
@testable import CicadaApp

/// R-L6/R8 — who wrote your memory, rendered honestly: Cicada's own
/// maintenance is labelled as such, a model with a bundled mark wears it, and
/// anything unmatched gets initials rather than the grey "?" that made four
/// distinct authors look like one anonymous row.
final class ContributorIdentityTests: XCTestCase {

    func testTheSystemAuthorIsNamedNotLeftAsAnId() {
        XCTAssertEqual(ContributorIdentity.displayName(author: "cicada", kind: "system"),
                       "Cicada · maintenance")
        XCTAssertEqual(ContributorIdentity.displayName(author: "user", kind: "user"), "user")
        XCTAssertEqual(ContributorIdentity.displayName(author: "gpt-5.4-mini", kind: "model"),
                       "gpt-5.4-mini")
    }

    func testProvidersWithABundledMarkUseIt() {
        XCTAssertEqual(ContributorIdentity.logoName(provider: "anthropic"), "claude")
        XCTAssertEqual(ContributorIdentity.logoName(provider: "openai"), "chatgpt")
        XCTAssertEqual(ContributorIdentity.logoName(provider: "google"), "gemini")
        XCTAssertEqual(ContributorIdentity.logoName(provider: "ollama"), "ollama")
        XCTAssertNil(ContributorIdentity.logoName(provider: "openrouter"))
        XCTAssertNil(ContributorIdentity.logoName(provider: nil))
        for name in ContributorIdentity.allProviderMarks {
            XCTAssertTrue(LogoImage.exists(name: name), "\(name).png is not bundled")
        }
    }

    func testAnUnmatchedModelGetsInitialsNeverAQuestionMark() {
        XCTAssertEqual(ContributorIdentity.monogram(for: "openrouter/z-ai/glm-5.2"), "OZ")
        XCTAssertEqual(ContributorIdentity.monogram(for: "glm-5.2"), "G5")
        XCTAssertNotEqual(ContributorIdentity.monogram(for: "glm-5.2"), "?")
    }
}
```

- [ ] **Step 2: Backend.** In `git_service.py`, add `CICADA_AUTHOR = "cicada"` beside
      `USER_AUTHOR`/`UNKNOWN_AUTHOR` with a doc line naming the writers that use it (`sleep_cycle`'s
      decay split and inbox-question refresh, `state_dictionary`, `bookmark_sync`,
      `link_enrichment`, the three migrations). Then:

```python
def _classify_author_kind(author: str) -> str:
    """Bucket an author into "user" | "system" | "model" | "unknown" for the UI.

    "system" is the literal ``cicada`` (R-L6): maintenance with no model and no
    user in the loop. It used to fall through to "model", where
    ``_provider_for_model`` answered "other" and the app drew a grey "?" — so
    the state snapshot, the split-out decay commit and the migrations all
    rendered as an anonymous unknown model in Cicada's own contributors list.
    """
    if author == USER_AUTHOR:
        return "user"
    if author == CICADA_AUTHOR:
        return "system"
    if author == UNKNOWN_AUTHOR:
        return "unknown"
    return "model"


# Routers that PROXY other vendors' models. Matched on the segment before the
# first "/" and checked BEFORE the substring pass (R9): the router is who
# billed, so "openrouter/anthropic/claude-opus-4" is openrouter, not anthropic.
_ROUTER_PREFIXES = ("openrouter", "ollama")

_PROVIDER_SUBSTRINGS = (
    ("openai", ("gpt", "text-embedding")),
    ("anthropic", ("claude",)),
    ("google", ("gemini", "gemma")),
    ("meta", ("llama",)),
    ("mistral", ("mistral", "mixtral")),
    ("deepseek", ("deepseek",)),
    ("qwen", ("qwen",)),
)
```
      and in `_provider_for_model`, **after `a = author.lower()` (`:306`) and before the substring
      loop (`:307-309`)** — the check has to run on the lower-cased id and must beat the substrings,
      or `openrouter/anthropic/claude-opus-4` matches `claude` first and answers `anthropic`:
      `head = a.split("/", 1)[0]` / `if head in _ROUTER_PREFIXES: return head`. The anchored
      o-series guard below it (`:310-313`) is untouched (R9). Update the
      `Contributor.kind` / `provider` comments at `schemas.py:197-205` to list the new values and
      note that both stay plain strings (older clients decode unchanged).

- [ ] **Step 3: Swift.** `ContributorIdentity.swift` — pure, no views:
      `displayName(author:kind:)` returns `"Cicada · maintenance"` for `kind == "system"` else the
      author; `logoName(provider:)` maps `anthropic→claude`, `openai→chatgpt`, `google→gemini`,
      `ollama→ollama`, else nil; `allProviderMarks` returns those four (T2 consumes it);
      `monogram(for:)` delegates to `LogoImage.monogram(for:)`. In `ContributorsView`: add
      `if contributor.author == "cicada" { return "system" }` to the `kind` fallback (`:108-113`) so
      an older backend still classifies (put it after the `if let k = contributor.kind` line at
      `:109`, so a backend that already says `system` still wins); `case "system"` in
      `ContributorAvatar.body` (`:421-433`) drawing
      `Image(nsImage: BookwormRenderer.cachedImage(state: .happy, frameIndex: 0, pointSize: 24))`
      `.interpolation(.none)` clipped to a `Circle()` — static frame 0, not `BookwormView`, per R8;
      `providerBadge` prefers `ContributorIdentity.logoName(provider:)` and falls back to the circle
      with `ContributorIdentity.monogram(for: contributor.author)` — which leaves
      `ContributorAvatar.monogram(_ provider:)` (`:483-491`, the one-letter `A`/`O`/`G`/`?` map)
      with no caller, so **delete it in the same commit**; it is the "?" R8 exists to remove.
      `providerColor` (`:473-481`) keeps its callers (`ContributorRow.accent`, `:119`) and gains
      `openrouter`/`ollama`/`meta`/`mistral`/`deepseek`/`qwen` (or keeps the neutral tone — either,
      but say which in the comment); the row name (`:197`) and the accessibility label (`:132`) both
      go through `displayName`. Rewrite the model rung of the header comment (`:411-413`, "Real logo
      assets are a follow-up; the monogram badge is the v1") to say what shipped instead, and add a
      `system` rung to that same four-line map (`:408-414`).

- [ ] **Step 4:**
```bash
cd <worktree>/ && \
  api/.venv/bin/python -m pytest api/tests/test_contributors.py -q -p no:cacheprovider && \
  api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
cd <worktree>/app/CicadaApp && \
  swift test 2>&1 | tail -20
```

- [ ] **Step 5: Commit** — `feat(track L): cicada is the system author, and the router before the slash is who billed (R-L6)`

---

### Task 7: The record — why R7 was reversed, so the glyphs never come back (R-L8)

**Files:**
- Modify: `docs/goals/memory-evolution.md` (G126, and a pointer in G124), `docs/goals/TODO.md`,
  `CLAUDE.md`

- [ ] **Step 1:** Append a paragraph to the **G126** row (`docs/goals/memory-evolution.md:688` — the
      Integrations page is where "logo-first" was promised and where the marks now land), naming the
      reversal and its evidence — placeholders only, no bank content, no personal names:

  > **Track L (2026-09-05) — real marks; R7 of the 2026-09-02 Safari-import plan is reversed.** That
  > plan ruled "browser marks are drawn, not downloaded" and shipped `ChromeGlyph`/`SafariGlyph`. It
  > was a *plan* rule, never a `TODO.md` ruling, and it named its own escape hatch ("drop
  > `Resources/logos/chrome.png` in and flip the tile's `logoName`"); both `PlatformTile` and
  > `OriginMark` already preferred a PNG. The hatch was taken because the drawn Chrome was wrong on
  > four independent axes: all four wedge colours were the pre-2015 Google palette
  > (`#DB4437/#F4B400/#0F9D58/#4285F4` vs the current `#EA4335→#D93025 / #FCC934→#FBBC04 /
  > #34A853→#1E8E3E / #1A73E8`), the wheel was rotated ~90° (red centred at 2 o'clock instead of
  > 11), the centre disc was ≈0.34 r against the real ≈0.45 r, and every wedge was a flat fill where
  > the mark uses two-stop gradients. `SafariGlyph` was Apple's own compass SF Symbol tinted an
  > invented `#00A2E8`. **The rule that replaces it:** an app whose files Cicada reads off this Mac
  > is installed by construction, so its icon comes from `NSWorkspace` at runtime (nothing
  > redistributed, never stale — this is also how R-L3 keeps Apple's marks out of the repo);
  > everything else is a maintainer-fetched, licence-recorded, committed PNG
  > (`scripts/fetch-logos.sh` + `logos.manifest.json` + `LOGOS.md`, nominative use only). **Drawn
  > brand marks do not come back** — a wrong-coloured logo that appears only when an asset is
  > missing looks like a logo and isn't, which is worse than an honest SF Symbol. Reserved and not
  > yet claimed: the Firefox and Brave marks are committed for **G119**'s channels.

- [ ] **Step 2:** One sentence in **G124** (`memory-evolution.md:686`, the Contributors half —
      its shipped-shape note already records "harness marks are OriginIconography glyphs — no brand
      assets", which this track closes): `cicada` is now author kind
      `system` ("Cicada · maintenance", the bookworm sprite) and the provider table learned the
      routers, so no contributor renders as an anonymous "?".

- [ ] **Step 3:** `docs/goals/TODO.md` — add Track L to "Where things stand" (the paragraph at
      `:128-132`) with its PR number placeholder, and edit the "Small polish left behind" paragraph
      (`:134-140`): drop **only** the clause "and draws the generic bubble symbol where `OriginMark`
      would show the logo" (fixed by task 4). **Keep the rest of that sentence** — Integrations
      still lists both the harness "Claude export" overview row and the "Claude chat export"
      channel, and Track L does not dedupe them. Do not touch the Rulings section.

- [ ] **Step 4:** `CLAUDE.md` — one paragraph under the Companion App section:

  > **Brand marks (Track L).** One map, `OriginIconography.logoName(for:)`, and one precedence:
  > **installed app icon → bundled PNG → SF Symbol**. Apple's marks are never committed (Safari and
  > Apple Notes resolve through `NSWorkspace` by bundle id, then their own SF Symbol); every other
  > mark is fetched once by a maintainer with `scripts/fetch-logos.sh`, declared in
  > `Resources/logos/logos.manifest.json` (source, licence, trademark restriction, sha256) and
  > attributed in `Resources/logos/LOGOS.md`. **No runtime network:** none of the three outbound
  > gates is involved. Nominative use only — a vendor mark is never restyled or recoloured; the one
  > permitted transform is an exact luminance inversion of a *monochrome* mark into its `-dark`
  > sibling, which `LogoImage` picks under a dark theme. Drawn brand glyphs are gone and do not come
  > back.

- [ ] **Step 5:** Both suites once more (docs-only, but the branch must land green). Commit —
      `docs: record why R7 was reversed and what replaces it (Track L, R-L8)`

---

## Not in scope

- **The Sources page layout** (Track S) — this track changes only which mark a row draws, never a
  page's structure. `Views/Sources/*` is untouched apart from nothing at all; `ContributorsView` is
  the one Contributors-side file this track edits.
- **`Views/Sleep/*` and the media-preview files** (Tracks A and V) — do not open them.
- **Entity logos** (`LogoStore`, `GET /entities/{id}/logo`, G59) — a different resolution ladder for
  a different subject. `LogoImage`'s entity mode is not touched.
- **Arc / Firefox / Brave as *channels*** (G119) — no adapter, no channel id, no origin id. Their
  marks are committed and allow-listed; wiring them up is G119's work.
- **New `_PROVIDER_SUBSTRINGS` consumers** — nothing is fed back into prompts or pricing; this is
  display classification only (the standing ruling: no prices or tokens in the app).
- **A calendar mark** (R3) and **an OpenRouter mark** (R-L3) — monogram and SF Symbol respectively.
- **Any backfill or migration** — no bank is read or written by this track.

## Verification (what the orchestrator runs at the end)

```bash
# Backend — must report 0 failures (2119 passed on 2026-09-05).
cd <worktree>/ && \
  api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
# Known order-dependent case: if the ONLY red is
# test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit,
# re-run it alone and report both results.

# App — build then the full suite (763 passed on 2026-09-05).
cd <worktree>/app/CicadaApp && \
  swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20

# The assets are the ones the ledger claims. `--check` is offline by construction
# (task 1 step 3.9): it re-hashes the committed PNGs and reads LOGOS.md, and never
# curls Commons — upstream drift is only asked on a real run.
cd <worktree>/ && \
  ./scripts/fetch-logos.sh --check && echo "manifest clean"

# The retired abstraction is really gone.
cd <worktree>/ && \
  rg -n "BrandGlyph|brandGlyph|ChromeGlyph|SafariGlyph|platformTile\(glyph" app/CicadaApp \
  || echo "no glyph residue"

# Nothing personal, no owner path, in what shipped.
cd <worktree>/ && \
  rg -n "/Users/" scripts/fetch-logos.sh tools/ || echo "no absolute paths"
```

**Owner-present, in the installed app** (the orchestrator installs at the end; this track never
launches it): the marks at **14, 28 and 44 pt in dark and light** — Sleep queue rows and the study
desk (14/28), Sources cards (28), Settings → Integrations (28), the `+` catalog's family and member
tiles (32/44), Contributors (22). Specifically: Chrome is the real four-colour mark; Safari and
Apple Notes are this Mac's own icons; ChatGPT and Codex and X are visible in **both** themes with no
white plate and no square corner; `cicada` reads "Cicada · maintenance" with the bookworm.
