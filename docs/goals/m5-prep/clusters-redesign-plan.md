# Clusters page redesign — navigate by type (AUDIT + PLAN)

Goal (Rodrigo's ask): "a lot of work can be done in the clusters page to more easily navigate the
list of clusters depending on its types and such." Make navigating the long flat list (~1,882
entities across 8 types + media/hub) by **type** easy and pleasant, while preserving every recent
fix.

This is an AUDIT + PLAN doc. **No code was changed.** Target file:
`app/CicadaApp/Sources/CicadaApp/Views/Topics/TopicsView.swift`.

---

## 1. Audit findings (ground truth)

### 1.1 Current structure of `TopicsView.swift`

- `TopicsView` (public) — `ZStack` over `CicadaTheme.background` (NO `.ignoresSafeArea()` — the
  title bar is darkened at the window level; keep it plain). Switches between `TopicDetailView`
  (when `selectedEntity != nil`) and `TopicsListView`, with spring move/opacity transitions.
  Overlaid `TopBarControls` (top-right) and a conditional `UploadOverlay`.
- `TopicsListView` (private) — the list surface:
  - `filteredEntities`: `graphVM.entities.filter { enabledTypes.contains($0.type) }`, then optional
    `selectedLabels` (tag intersection), then either A→Z by name (empty search) or a ranked search
    (exact 100 > prefix 80 > contains 60 > tag 40 > markdown body 20, sorted desc).
  - `allLabels`: tag → count map, A→Z. Feeds the labels popover.
  - Body: `PageHeader(title: "Clusters", subtitle: …)`, then a search field + a **type filter**
    button (popover, shared with Graph via `graphVM.filter.types`) + a **labels** button (lazy,
    capped popover), then a `"\(count) clusters"` line, then a `ScrollView { LazyVStack { ForEach …
    TopicRowListItem } }`.
- `TopicsFilterPopover` — checkbox list over `EntityType.selectableCases`, writes `enabledTypes`.
- `TopicsLabelPopover` — searchable, `renderCap = 100`, LazyVStack. **Keep lazy + capped.**
- `TopicRowListItem` — color dot + name + type capsule + confidence% + chevron, hover highlight.
- `TopicDetailView` — Back button ("Clusters") + `EntityDetailCard(entity:, showsCloseButton:
  false)` (its own internal ScrollView; do NOT wrap in a second one), `.frame(maxWidth: 640)`,
  `.task(id:)` loads the full entity via `APIClient.shared.fetchEntity`.

### 1.2 Data + theme facts the redesign relies on

- `Entity` has `type: EntityType`, `name`, `confidence`, `status: EntityStatus`, `tags`. All
  present on the lightweight graph node, so grouping/decay needs no extra fetch.
- `EntityType` is a `CaseIterable, Identifiable` enum; `EntityType.selectableCases` =
  `allCases` minus `.unknown` (so it INCLUDES `media` and `hub`). Each type already has
  `.label` (capitalized rawValue) and `.icon` (SF Symbol). `graphVM.filter.types` is seeded to
  `Set(EntityType.selectableCases)`.
- `CicadaTheme.entityColor(for:)` gives the per-type hue (mirrors graph.js). `statusColor(for:)`
  exists; `.decaying` is amber. Spacing/typography tokens all exist. `glassCard` modifier exists.
- No `DisclosureGroup` / collapsible pattern exists anywhere in the app yet — this is the first.

### 1.3 The navigation pain (why this is worth doing)

One flat, alphabetized `LazyVStack` of ~1,882 rows. To find "all my `tool` entities" the user must
either open the filter popover and uncheck the other 9 types (two-step, hidden behind a popover) or
scroll-scan a wall of rows where type is only a small dot + capsule per row. There is no sense of
"how many of each type exist," no way to jump to a type, and no visual rhythm to the list. Type —
the primary axis the graph is already colored by — is the obvious organizing principle and is
currently the weakest part of the list.

---

## 2. Redesign

Two coordinated affordances, both keyed on **type**: a **type rail / jump bar** at the top, and a
**type-grouped, collapsible list** below it. Search stays global and flattens the grouping.

### 2.1 Grouping model — collapsible per-type sections

Replace the single flat `LazyVStack` of rows with one **collapsible section per type that has ≥1
matching entity**, in a stable canonical order (`EntityType.selectableCases` order: person,
project, company, concept, tool, deadline, skill, location, media, hub). Each section is a custom
lightweight disclosure (NOT stock `DisclosureGroup` — we want full control of the header chrome and
the chevron):

- **Section header** (sticky-feeling, full-width, tappable): the type's color dot + `type.icon`
  (tinted with `entityColor`) + `type.label` + a **count pill** (`entityColor.opacity(0.12)`
  background, monospaced count) + a trailing chevron that rotates 0°↔90° on expand. Hover uses
  `surfaceHover`. Tapping toggles that type's expansion.
- **Section body**: when expanded, the existing `TopicRowListItem` rows for that type, A→Z (or
  ranked when searching). Rows are unchanged. The body is built lazily inside the outer
  `LazyVStack` so collapsed sections cost ~nothing and the ~1,882-row worst case never all
  materializes at once.
- Expansion state: `@State private var expandedTypes: Set<EntityType>`. **Default: all present
  types expanded when ≤ a small threshold of sections, but collapsed-by-default is wrong here** —
  instead default to **all collapsed except** the first section, OR (preferred, simplest + most
  scannable) **all sections collapsed by default** so the user lands on a compact "table of
  contents" of types + counts and drills in. We will go with: **all collapsed by default**, with a
  one-tap "Expand all / Collapse all" toggle in the count row. (Rationale: with 1,882 entities,
  an all-expanded default reproduces the current wall; a collapsed-by-default index is the actual
  navigation win.)
- **Counts are computed once** per render from `filteredEntities` grouped by type
  (`Dictionary(grouping:)`), so each header shows the live post-filter, post-search count.

### 2.2 Type-jump affordance — a horizontal type selector ("type rail")

Directly under the search/filter row, add a single-line **horizontal scroll of type chips**, one
per present type, each = color dot + `type.label` + count. This is the quick "jump / focus"
control and is distinct from the existing type **filter** popover (which stays for
multi-select/Graph-shared filtering):

- **Tap a chip → "focus that type":** scrolls the list to that type's section (via
  `ScrollViewReader.scrollTo(type, anchor: .top)`) AND expands it (and optionally collapses the
  others — "solo" behavior). A second tap on the same focused chip clears focus (re-shows all
  sections collapsed). This gives a one-tap path to "show me just my projects" without touching the
  filter popover or losing the other types from the index.
- The chip for the currently-focused type gets an accent ring / filled treatment; others stay
  outline. Chips that are filtered OUT entirely (count 0 under current filter+search) are hidden.
- This is purely a view-state convenience (`@State private var focusedType: EntityType?`); it does
  NOT mutate `graphVM.filter.types`, so it never desyncs the Graph tab. The filter popover remains
  the only thing that writes the shared filter.

### 2.3 Search behavior (preserved + adapted)

- When `searchText` is non-empty, **flatten**: hide section headers and the type rail's focus
  effect, and show the existing ranked-by-match flat list (current behavior) so a search spans all
  types exactly as today. The grouping/jump UI is an empty-search affordance. (Alternatively keep
  groups but auto-expand any section with matches; we'll start with flatten-on-search for
  simplicity and least surprise, and note the auto-expand variant as a fast follow.)
- The `"\(count) clusters"` line stays, now paired with the Expand/Collapse-all toggle and (when a
  type is focused) a small "Showing: <Type>" + clear affordance.

### 2.4 What stays UNCHANGED (MUST-PRESERVE)

- `CicadaTheme.background` plain, **no `.ignoresSafeArea()`**; keep the `.frame(maxWidth/maxHeight:
  .infinity)` layout. No window-stretch regression.
- `TopicDetailView` keeps `EntityDetailCard(entity:, showsCloseButton: false)` with its own Back
  button; no second ScrollView around it.
- The labels popover stays LAZY + `renderCap`-capped (`LazyVStack` + prefix). Do not undo.
- `PageHeader("Clusters")`, the search field, and the type **filter** popover (shared with Graph
  via `graphVM.filter.types`) keep working exactly as before.
- List↔detail spring transitions and the shared `graphVM.filter` are untouched.
- `TopicRowListItem` row design is reused verbatim.

---

## 3. Implementation sketch (single file, app-only)

All changes live in `TopicsView.swift`. No model, theme, or VM changes required.

1. In `TopicsListView`, add `@State private var expandedTypes: Set<EntityType> = []` and
   `@State private var focusedType: EntityType? = nil`.
2. Derive `groupedEntities: [(EntityType, [Entity])]` from `filteredEntities` via
   `Dictionary(grouping: filteredEntities, by: \.type)`, ordered by `EntityType.selectableCases`,
   dropping empty groups. Derive `presentTypes` from it.
3. Replace the list `ScrollView` body:
   - Wrap in `ScrollViewReader`.
   - If `!searchText.isEmpty` → existing flat `ForEach(filteredEntities) { TopicRowListItem }`.
   - Else → `LazyVStack` of `TypeSectionView`s (one per group), each with `.id(type)` for
     `scrollTo`. A `TypeSectionView` (new private struct) takes `(type, entities, isExpanded,
     onToggle)` and renders the header + (when expanded) its rows.
4. Insert a new `TypeJumpRail` (private struct) between the search row and the count line: a
   horizontal `ScrollView(.horizontal)` of `TypeChip`s built from `groupedEntities`. Tapping sets
   `focusedType`, expands that type (solo), and calls `proxy.scrollTo(type, anchor: .top)`.
5. Add the "Expand all / Collapse all" control to the count row (toggles `expandedTypes` between
   `Set(presentTypes)` and `[]`).
6. Keep `TopicsFilterPopover` and `TopicsLabelPopover` as-is.

### Risks / notes

- **Laziness**: keep section bodies inside the outer `LazyVStack` and only build rows for expanded
  sections so the 1,882-row worst case never fully materializes (mirrors the labels-popover lesson).
- **Type set**: iterate `EntityType.selectableCases` (includes media/hub), not `allCases`, so
  `unknown` never gets a section; group keys come from real present types only.
- **Focus vs filter**: `focusedType` is view-local only; never write `graphVM.filter.types` from
  the rail, to keep the Graph tab in sync.
- **Build**: verify with `cd app/CicadaApp && swift build` (exit 0); ignore SourceKit "cannot
  find X" stale-index noise.
