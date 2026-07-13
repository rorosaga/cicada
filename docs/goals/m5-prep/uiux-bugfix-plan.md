# M5-prep UI/UX bugfix plan

Audit of Rodrigo's 7 QA issues. Each entry: root cause (file:line) + minimal fix.
No code modified during this audit. Backend tests baseline: 191 green — keep green.
App build: `cd app/CicadaApp && swift build` must exit 0.

---

## #1 — Merge direction (choose the canonical survivor)

**Root cause.** The merge always absorbs the clarified mention INTO the fixed
existing target; the user cannot pick which name survives.

- Backend: `api/services/inbox_service.py` `_resolve_clarification`, the
  `request.action == "merge"` branch (lines 316–356). It loads
  `request.merge_target` (the existing entity), appends a "_Resolved ambiguous
  mention '…' into this entity._" note to **that** file, deletes the inbox item,
  and points the commit at `target_path.stem`. Direction is hard-wired:
  clarified-mention → target. There is no concept of "which id survives."
- The clarified side is only a *mention* in most merge_suggestion cases — there
  may be no entity file for it yet (e.g. `driver.js` mention vs existing
  `driver-js-iife-build`). So "merge target → mention" requires creating/renaming
  to the cleaner name, not just appending.
- Wire: `InboxResolveRequest` (`api/models/schemas.py:375`) has only
  `action / answer / merge_target`. `merge_target_hint` is surfaced on
  `InboxItem` (schemas.py:372, populated in `inbox_service._item_from_file:69`
  from the clarification frontmatter written by
  `clarification_manager.create` → `_merge_target_hint`, lines 91–116).
- Frontend: `InboxCardView.mergeActions` (lines 223–265) shows a single
  "Merge into…" TextField prefilled from `item.mergeTargetHint`; fires
  `fire("merge", mergeTarget: mergeText)`. There is no survivor picker — the two
  candidate names are `item.displayName` (the mention) and
  `item.mergeTargetHint` (the existing target slug).

**Fix (minimal).**
1. Schema: add `merge_survivor: Optional[str] = None` to `InboxResolveRequest`
   (schemas.py:375). Wire name `mergeSurvivor` (CamelModel). Semantics: the id/name
   the user wants to KEEP. When absent, default to today's behavior (survivor =
   `merge_target`) so existing callers/tests are unaffected.
2. `_resolve_clarification` merge branch: resolve BOTH the existing target
   (`resolve_entity_file(merge_target)`) and the survivor. Two cases:
   - **Survivor == existing target** (current behavior): unchanged.
   - **Survivor == the clarified mention** (the new path Rodrigo wants): the
     surviving file should carry the cleaner name/id. Simplest safe
     implementation: take the existing target file as the data source (it has the
     real frontmatter/body/history), then rename it to the survivor's slug via
     `git mv` and set `name:` to the survivor display name, merging
     `source_episodes` + `last_referenced` + bumping `version` as today. If a
     file already exists at the survivor slug, append into it instead (no
     overwrite). Point the commit at the survivor stem.
   Keep the existing `_max_date` / source-episode merge logic verbatim; only the
   destination file identity changes. Guard against survivor == target (no rename).
3. Frontend `InboxCardView.mergeActions`: replace the single "Merge into…" field
   with a two-option survivor picker. Both candidate names are already in-model
   (`item.displayName` = mention, `item.mergeTargetHint` = existing slug). Render
   a small segmented/toggle ("Keep: [mention] | [existing]"); the non-survivor is
   shown as "→ merges into". On Merge, send `mergeTarget = existing slug` (the
   data source) + the new `mergeSurvivor` = chosen id. Plumb `mergeSurvivor`
   through `InboxViewModel.resolve` (ViewModel:40-48), `APIClient.resolveInboxItem`
   (APIClient:446-456 — add `mergeSurvivor` to the body dict like `mergeTarget`),
   and `InboxCardView.onResolve` closure signature (currently
   `(String, String?, String?)` — extend to carry survivor, or pass survivor via
   the existing `mergeTarget`+a new param).
4. Tests: add an inbox_service test for the survivor-is-mention path (rename +
   commit points at new stem) alongside the existing merge test.

---

## #2 — Inbox card expand animation overlays the title

**Root cause.** `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift`.
The expanded body uses `.transition(.move(edge: .top))` (lines 108–111), so on
insert it slides DOWN FROM the top edge of its own frame — visually it animates
out from under/over the header tile instead of revealing from below. Combined
with the outer `VStack(spacing: 0)` (line 22) and the expand toggle animating
`isExpanded` (lines 85–89), the content's `.move(edge: .top)` reads as an overlay
sweeping over the title.

**Fix (minimal).** In `expandedBody` (lines 108–111) drop the `.move(edge: .top)`
insertion. A bottom-revealing expand is best done by letting the VStack grow:
use a plain height/opacity reveal — e.g. insertion `.opacity` only (the VStack
already pushes content below the header because they're stacked, spacing 0), or
`insertion: .push(from: .bottom)` / `.move(edge: .bottom)` if a slide is wanted.
Keep the `withAnimation(.spring(...))` toggle on the header tap (lines 86–88) so
the container animates its height. Net change: swap the insertion edge from
`.top` to `.bottom` (or remove the move entirely), leaving removal as `.opacity`.

---

## #3 — Title-bar color inconsistent (grayish on Inbox, dark elsewhere)

**Root cause.** The window title-bar inherits the color of the top of the detail
content. Graph/Topics/Feed root their content in
`ZStack { CicadaTheme.background.ignoresSafeArea(); … }`
(`FeedView.swift:13-14`, `TopicsView.swift:14-15`, plus GraphContainer), so the
dark background bleeds under the title bar. `InboxListView`
(`Views/Inbox/InboxListView.swift:19-49`) instead uses a plain
`VStack { … }.background(CicadaTheme.background)` with **no `.ignoresSafeArea()`**
and no ZStack background layer — so the title-bar safe-area strip falls back to
the default window chrome (the grayish material), not `background`.

**Fix (minimal).** Make Inbox match the others. Either add `.ignoresSafeArea()`
to the `.background(CicadaTheme.background)` at InboxListView.swift:49, or wrap
the body in `ZStack { CicadaTheme.background.ignoresSafeArea(); VStack {…} }`
like Feed/Topics. Lowest-risk single-line change: change line 49 to
`.background(CicadaTheme.background.ignoresSafeArea())` (or append
`.ignoresSafeArea(edges: .top)` after the background). Verify
`ContentView.detailContent` already backs the detail column with
`CicadaTheme.background` (ContentView.swift:20) — Inbox is the only page not also
extending it into the safe area.

---

## #4 — Feed window auto-resizes to a tall/vertical shape

**Root cause.** `app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift`. Unlike
the other detail views, FeedView's root `ZStack` (line 13) has **no**
`.frame(maxWidth: .infinity, maxHeight: .infinity)`. Its `emptyState` (lines
130–148) and `content` Spacers only stretch vertically (`.frame(maxWidth: .infinity)`
on emptyState at line 147 — width only). With the inner content not claiming
infinite width, SwiftUI proposes the content's intrinsic (narrow) width to the
NavigationSplitView detail column, and `.prominentDetail`
(`ContentView.swift:22`) lets that drive the window toward a tall/narrow shape.
`CicadaTheme.background.ignoresSafeArea()` paints full-bleed but does not
constrain the layout frame.

**Fix (minimal).** Add `.frame(maxWidth: .infinity, maxHeight: .infinity)` to the
FeedView root `ZStack` (after line 47's closing `}`, alongside `.task`), matching
what `GraphView()` and others do. This pins the detail content to fill the
column so the window keeps its size. (Do NOT add a fixed `.frame(width:…)` — the
bug is the absence of an infinity frame, not a forced one.) No forced aspect/min
frame exists to remove; this is an additive fix.

---

## #5 — Feed bookworm mascot missing

**Root cause.** `BookwormView` (`Views/Common/BookwormView.swift`) is the animated
mascot, used by `UploadOverlay`. FeedView's empty state
(`FeedView.swift:130-148`) renders a generic SF Symbol (`"tray"` / `"photo…"`),
not the bookworm. The Inbox empty state uses a *static* bookworm frame via
`BookwormRenderer.image(grid: BookwormSprites.happy, …)`
(`InboxListView.swift:101`), but Feed uses no bookworm at all.

**Fix (minimal).** Surface `BookwormView` in FeedView. Lowest-risk placement: in
the `emptyState(symbol:title:subtitle:)` builder (FeedView.swift:130), replace the
SF-Symbol `Image` (lines 133–135) with `BookwormView(state: .awake, pointSize: 72)`
(pick an existing `BookwormState` case — confirm the case name in
`MenuBar/BookwormState.swift`; `.awakeOpen`/idle-equivalent is the calm default).
Keep title/subtitle. Optionally also drop a small `BookwormView` into the Feed
`header` (FeedView.swift:56-61) next to the PageHeader for a persistent mascot.
Empty-state placement alone satisfies "appears in the Feed/ingestion area."
BookwormView tears its Timer down on `onDisappear`, so no leak.

---

## #6 — Clusters "Labels" button freezes

**Root cause.** `app/CicadaApp/Sources/CicadaApp/Views/Topics/TopicsView.swift`.
The Labels button opens `TopicsLabelPopover` (lines 178–198 → 269–365). Its list
(lines 308–340) is a **non-lazy** `VStack` inside a `ScrollView`, iterating
`visibleLabels` (every tag across all entities, computed in `allLabels`
TopicsView.swift:113-123 — one row per distinct tag, unbounded). On a graph with
many tags this builds every row eagerly when the popover opens → the freeze/lag.
The search field (`labelSearch`, line 292) filters but the full list still
materializes before any typing, and each keystroke rebuilds the whole VStack.

**Fix (minimal).**
1. Swap the inner `VStack` (line 309) for a `LazyVStack` so only visible rows
   render — single-keyword change, biggest win, kills the freeze.
2. Cap the rendered set: render `visibleLabels.prefix(N)` (e.g. 100) with a
   "+N more — refine search" footer, so even an empty search never builds
   thousands of rows. `visibleLabels` (lines 274–278) already supports search;
   the prefix bounds the worst case.
3. (Optional, low-risk polish) The label-count tuple list `allLabels` is
   recomputed in `filteredEntities`'s sibling scope each render; it's only used
   by the popover, so it's acceptable, but consider hoisting/`@State`-caching if
   still janky. Not required to kill the freeze.
A cluster-by-type navigation is a nice-to-have; the LazyVStack + prefix is the
minimal freeze fix.

---

## #7 — Location entities: show path + immediate contents

**Root cause.** Location entities carry only a description — there is **no `path:`
field** in any location's frontmatter today (verified: `memory/entities/src.md`,
`webapp-frontend.md`, etc. have type/status/tags/related but no path). So nothing
to display, and no endpoint reads a path. `EntityResponse` (schemas.py:89-106)
has no path field; `EntityDetailCard` (`Views/Graph/EntityDetailCard.swift`)
renders type-agnostically (header + markdown + metadata), with no location branch.

**Fix (minimal) — DISPLAY a path+contents when present; leave extraction as TODO.**

*Extraction (documented TODO, not implemented here):* the Sleep cycle's entity
extraction (`api/services/entity_extractor.py` / `sleep_cycle.py`) should, for
`type: location` entities whose description names a directory path, write a
`path:` key into the entity frontmatter. Out of scope for this UI/UX pass — add a
TODO comment where location entities are written.

*Backend — new safe listing endpoint.* Add to `api/routers/entities.py`:
`GET /entities/{entity_id}/location` →
returns `{ path: str|null, exists: bool, accessible: bool, entries: [{name, isDir, size}] }`.
Implementation rules (security):
- Read the entity file, require `type == location`. Read `path:` from frontmatter
  ONLY. **Never** accept a path from the request — the only path used is the one
  the entity itself declares (prevents arbitrary-path traversal).
- Expand `~`, resolve, and require the resolved path to be a directory that
  exists; on missing → `exists:false`, on `PermissionError` → `accessible:false`,
  both 200 with empty `entries` (graceful, never 500).
- List ONLY immediate children (`os.scandir`, depth 1). For each: `name`,
  `is_dir`, `size` (st_size for files; skip/0 for dirs). Do NOT read file
  contents. **Bound the count** (e.g. first 200 entries, sorted dirs-first then
  name) and set a `truncated` flag.
- New `LocationListing` / `LocationEntry` CamelModel schemas in schemas.py.
- Optionally include `path` (and `pathExists`) on `EntityResponse` so the app can
  decide whether to show the section without a second call — but keep the
  dedicated listing endpoint for the children.
- Tests: add `api/tests` coverage for present-path, missing-path,
  permission-denied, non-location 400, and the count bound.

*Frontend.* In `EntityDetailCard` add a location section (only when
`entity.type == .location` and a path is available): show the path string
(monospace, copyable) and, on demand or on appear, call the new endpoint and
render the immediate children as a simple list (folder/file icon by `isDir`,
name, human size). Add `path` to the Swift `Entity` model
(`Models/Entity.swift`) if surfaced on `EntityResponse`, plus an
`APIClient.fetchLocationListing(id:)`. Degrade quietly (show just the description)
when no path / not accessible.

---

## Verification checklist
- Backend: `api/.venv/bin/python -m pytest api/tests -q` → all green (191 + new).
- App: `cd app/CicadaApp && swift build` → exit 0.
- Manual (human): expand an inbox card (#2 reveals from below), inbox title bar
  dark (#3), navigate to Feed keeps window size (#4) + shows bookworm (#5),
  Clusters Labels opens instantly (#6), merge card lets you pick survivor (#1),
  a location entity with a `path:` shows its directory contents (#7).
