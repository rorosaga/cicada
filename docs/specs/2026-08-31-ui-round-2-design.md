# UI round 2 — IA restructure + audit top-10 (G68)

**Status:** approved 2026-08-31 (Rodrigo: "independent workflow for UI improvements… side panel congested and repetitive… lots of things and bugs that can be improved").
**Grounding:** the 2026-08-31 six-lens audit workflow (sidebar IA, Capture, setup pages, code bug hunt, live screenshots, copy) + its synthesis. This spec adopts the synthesis verbatim except where noted.

## 1. Target information architecture
Sidebar becomes **6 rows + 1 section label + footer gear**:

| ⌘ | Tab | Contents |
|---|-----|----------|
| 1 | Graph | unchanged |
| 2 | Clusters | unchanged |
| 3 | Feed | absorbs Capture: `+`/⌘N AddSourceSheet, collapsible connected-channels strip |
| 4 | Sleep | absorbs the sleep-queue card from Capture; running indicator on the row |
| 5 | Inbox | unchanged (badge) |
| 6 | Activity | merges Usage + Contributors as a segmented control; origins strip lands here |
| ⌘, | Settings (native `Settings{}` scene, footer gearshape) | Agents (ConnectView) + Plans & keys (ConnectionsView) tabs |

- SETUP/PROVENANCE/etc. section labels die; one label ("SYSTEM" or none) at most.
- The gear shows an attention dot when a subscription login expires (`connected == false`
  while `available`); ⌘1–6 match visual order; tab enum raw values (cache identity) unchanged
  for surviving tabs, `capture`/`contributors`/`usage`/`connections`/`connect` handled so
  restored state from an old cache falls back cleanly.
- `SourcesView` dies as a page; its components (channel rows, queue card) survive as
  extracted views used by Feed/Sleep. ConnectView's clipped command snippets get wrap/scroll.

## 2. Audit top-10 adopted
1. Sidebar restructure (above).
2. Capture→Feed merge (above).
3. **EntityDetailCard cross-entity state bleed** — `.id(entity.id)` at both presentation sites
   so navigating A→B via wikilink never shows A's claims/timeline/tab state.
4. AddSourceSheet overhaul: fix wrong per-tile vendor wiring (`[.claude,.chatgpt]` vs
   `[.takeout,.instagram]`, drop unsupported Gemini mention), focused single-tile mode with
   back control + inline status (nothing below the fold), 3-column grid, no truncated tile
   titles, single ⌘N registration, Esc closes, delete dead `ImportTileButton`.
5. Usage stabilization: pickers `labelsHidden`/`fixedSize` (no "Mo de"/"This…" wraps), heatmap
   weekday ForEach unique ids ("AugSep" collision), "No usage in this range" placeholders,
   range fetches cancel-and-guard with visible loading (no wrong-range numbers), `.task`
   refetch guarded by `loadedOnce`, harness numbers through `UsageFormat`.
6. Contributors+Usage → Activity (above).
7. Semantic color tokens: `CicadaTheme.success/warning/danger/info` mode-aware (the
   entityColor pattern); migrate every raw hex call site (Inbox, QuestionView, UploadOverlay,
   ClaimChip, CommandBox — fix its light-mode black-on-black, EntityDetailCard, Sleep,
   Capture components, AddSourceSheet).
8. Copy normalization: hardcoded "Rodrigo" in ObserverFilterBar/ObserverBadge → "You";
   Clusters page stops claiming auto-detection and mislabeling counts; every cross-page
   pointer goes through one `Copy` constants enum (e.g. "Settings → Plans & keys"); one voice
   for PageHeader subtitles (short, no title repetition); "Consolidate now" standardized.
9. Channel rows: hover chevron + always-present "Manage…" menu item, delete dead "remove"
   branch, per-channel inline spinner + 5 s auto-clear feedback, sleep error text rendered
   under the trigger button, queue icon at the shared 28 pt circle.
10. State-coverage batch: Inbox never flashes "All caught up" mid-load; Contributors
    distinguishes never-loaded from empty (wire or delete the orphaned `load()`); Entity
    History tab gets loading/empty branches; Ask citations/gaps get unique ForEach ids.

## 3. Constraints
- Keep the Store/Mutation architecture; moved views stay projections; no new fetch-on-appear.
- Keyboard: ⌘1–6 per the table; ⌘K Ask and ⌘N (in Feed) unchanged; ⌘, opens Settings.
- Accessibility labels on every moved/new interactive row; VoiceOver names match visible text.
- No behavioural changes to backends; this is app-side only.
- Old snapshot caches must load (tab identity fallbacks; no cache schema changes).

## 4. Testing
Swift: tab-enum fallback decoding from legacy raw values; Activity segmented state; Feed
channel-strip collapse persistence; AddSourceSheet vendor-wiring table (per-tile vendors);
Usage picker/no-wrap regression via layout-free logic tests where possible (formatting,
ids uniqueness); semantic-token existence for both modes; Copy constants used (no literal
"Plans & keys" strings outside Copy + Settings titles — grep test in CI style). Live pass:
screenshot sweep of all six tabs + Settings, before/after, attached to the PR.
