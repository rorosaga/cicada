# Round 3 UI design: Settings v3, the Cmd-K find palette, and the provenance viewer

Tracks **O** (Settings v3 + skills), **S** (search everywhere) and **P** (G118 slice 2 + "who
contributed what"). All three depend on **M1** (Meadow tokens, `CicadaMotion`, `liquidGlass`,
`quoteFont`, `displayFont`); O also depends on **R** (remote connector) and **E** (engines).

Code read at `dev` @ `f2d31ef`. All app paths are relative to
`app/CicadaApp/Sources/CicadaApp/` unless they start with `api/` or `app/`. Nothing from `memory/`,
`~/.cicada` or `~/.claude/projects` was read. Examples use placeholders (`alpha-project`,
`bob-example`); real values are never needed.

---

## 0. The idea in one paragraph

The three surfaces share three primitives, and most of the work is building each primitive once:

1. **One matcher.** `QuickMatch` is a pure ranker (exact > prefix > word-start > contains, with
   field weights). It powers the Settings search, the Cmd-K palette's local tier and every in-page
   filter field.
2. **One way to land on a thing and show it.** A *row anchor* (`SettingsRowID`, entity id,
   inbox id or evidence span) is something a surface can scroll to and briefly highlight with the
   same dandelion wash, the same timing constants and the same VoiceOver announcement.
3. **One reader.** Every "where did this come from" affordance (an evidence chip, an inbox cause,
   a palette passage hit, an Ask citation) opens the same **Reader** inspector at a span.

Settings search finds a *setting* and lands on its row. The palette finds a *memory* and lands on
the node, the passage or the row. The provenance viewer shows *why* a memory exists and lands on
the sentence. All three follow the same rules: land, highlight, say it out loud.

---

## 1. Shared foundations

### 1.1 Timing and motion constants (all new names; no literal `duration:` outside these files, R-M4)

| Constant | Value | Kind | Reduce Motion |
|---|---|---|---|
| `CicadaMotion.paletteIn` | `.snappy(duration: 0.16)`, scale 0.98 to 1 plus opacity | animation | `nil`: appears at once |
| `CicadaMotion.paletteOut` | `.easeOut(duration: 0.12)`, opacity | animation | `nil` |
| `CicadaMotion.rowHighlightHold` | 1.2 s at full wash | hold | the wash is shown for `rowHighlightHold + rowHighlightFade` and then removed with no fade |
| `CicadaMotion.rowHighlightFade` | `.easeOut(duration: 0.6)` | animation | `nil` |
| `CicadaMotion.spanReveal` | `.easeOut(duration: 0.25)`, wash opacity 0 to 0.35 | animation | `nil`: static wash |
| `CicadaMotion.groupExpand` | `.snappy(duration: 0.2)` for "Show all N" | animation | `nil` |
| `CicadaTiming.hoverPreviewDelay` | 0.35 s dwell before an evidence preview opens | timing | unchanged (a delay is not motion) |
| `CicadaTiming.hoverPreviewGrace` | 0.2 s before a preview closes after the pointer leaves, so the pointer can travel into it | timing | unchanged |
| `SearchTiming.serverDebounce` | 0.12 s | timing | n/a |
| `SearchTiming.semanticIdle` | 0.45 s idle before the hybrid (vector) pass | timing | n/a |
| `SearchTiming.localBudgetMs` | 8 ms p95 (test budget, not runtime) | budget | n/a |

The lint that M1 adds ("literal `duration:` only inside `CicadaMotion`/`SleepMotion`") must also
cover `CicadaTiming` and `SearchTiming` (it matches `Task.sleep(for: .seconds(<literal>))` in the
new files).

Two literals that these tracks replace anyway: `Ask/AskPanel.swift:34`
(`.easeInOut(duration: 0.15)`) and the Ask sheet's spring at `ContentView.swift:130`.

### 1.2 `QuickMatch`: the one ranker (new, `Utilities/QuickMatch.swift`, pure)

- **Normalize** both sides: `folding(options: [.caseInsensitive, .diacriticInsensitive])`, and
  collapse whitespace. Normalize the index once, when it is built, never per keystroke.
- **Tokenize** the query on whitespace. A document matches only when **every** token matches
  some field (AND).
- **Per token, per field, take the best tier:** exact field = 0, field prefix = 1, word-start
  prefix = 2, initials ("cc" matches "Claude Code") = 3, substring = 4. This keeps
  `GraphViewModel.rankNames`' ordering (`ViewModels/GraphViewModel.swift:448-467`: prefix, then
  word-start, then contains, then degree, then name) and extends it.
- **Field weights:** title/name 1.0, alias 0.9, keyword/tag 0.7, summary/description/snippet 0.4.
- **Score** = sum over tokens of `(5 - tier) * weight`.
- **Tie-break** is chosen per kind: entities by `degree`, media by `savedAt` (newest first), inbox
  by `priority`, settings by declaration order.
- **Match ranges** are returned so a row can bold them. `MatchHighlight.attributed(_:ranges:)`
  reuses the scalar-offset logic of `ExcerptText.attributed` (`Models/InboxPresentation.swift:47-60`).
- **Tests** are pure: tier order, AND semantics, diacritics ("Zurich" finds "Zürich"), initials,
  weights, tie-breaks, and a latency test (§3.10).

`GraphViewModel.rankNames` becomes a thin wrapper around `QuickMatch`, so the graph typeahead and
the palette can never rank one name differently.

### 1.3 Components

| Component | File (new unless marked) | Used by |
|---|---|---|
| `CicadaSearchField(text:, prompt:, style: .content \| .overCanvas, onSubmit:, onMove:)` | `Views/Common/CicadaSearchField.swift` | Graph, Clusters, Feed, Harness conversations, Inbox, Reader find |
| `PillPicker<T>(selection:, options:)`: capsule segments that expose a real `Picker` through `.accessibilityRepresentation` | `Views/Common/PillPicker.swift` | Appearance, Sleep runs, connector expiry, export scope |
| `SettingsRow(id:, title:, detail:, control:)` + `SettingsGroupCard` | `Views/Settings/SettingsRow.swift` | every Settings page |
| `SettingsDetailHeader(path: [Crumb])` | `Views/Settings/SettingsDetailHeader.swift` | every Settings page and sub-page |
| `EvidenceChip(evidence:, context:)` | `Views/Provenance/EvidenceChip.swift` (replaces `EpisodePill`, `Views/Common/ClaimChip.swift:196-212`) | ClaimChip, "Where this came from", palette belief rows, Ask |
| `QuoteBlock(before:, span:, after:, label:, state:)` | `Views/Provenance/QuoteBlock.swift` | hover preview, "Where this came from", inbox cause, Ask citation |
| `ReaderInspector` | `Views/Provenance/ReaderInspector.swift` | all "open the conversation" routes |

**`CicadaSearchField` anatomy:**

- A 28 pt capsule with a leading magnifier, the prompt, a clear button (the x-circle) when
  non-empty, and a trailing `Cmd F` hint glyph when empty and unfocused. The hint's text twin is
  `.help("Find on this page (Cmd F)")`.
- `.content` style is content layer (R9 §2.7): a `surfaceHover` fill and a 1 pt `border`, no
  glass.
- `.overCanvas` style is used only by the Graph field. It is `.liquidGlass(.control, in: Capsule())`
  inside the graph's single `GlassEffectContainer` (R-M5), with the M1 material fallback.
- **Keys:** `Esc` clears, and a second `Esc` blurs. `Up`/`Down` call `onMove(+-1)` when the page
  has a result list. `Return` calls `onSubmit`.
- **Accessibility:** the label is the prompt, and the clear button is labelled "Clear search".

**`SettingsRow` anatomy (Claude-style):**

- Left: the title in `bodyFont` medium and an optional one-line detail in `captionFont`,
  `textSecondary`.
- Right: the control, right-aligned, `Spacer(minLength: 16)`.
- Vertical padding `spacingSM + 2`, horizontal `spacingMD`.
- Rows sit in a `SettingsGroupCard`: a standard material or opaque `surface`, radius 12, with
  hairline dividers inset by `spacingMD`. This is content layer, so never glass.
- A group's small header uses the `labelFont` token proposed in R6 §1.3 (the 10 pt monospaced
  uppercase house style, currently repeated by hand in ~12 files, e.g.
  `Views/Settings/SettingsGeneralView.swift:52-55`).
- **Accessibility:** the row is `.accessibilityElement(children: .contain)` with
  `.accessibilityIdentifier("settings.row.<rowID>")`, so `macos-harness` (the G90 screenshot
  method) can target rows by id.

### 1.4 Navigation plumbing

- **`AppRouter`** (`Support/AppRouter.swift:14-31`) gains:
  - `pendingPalette: PaletteRequest?`, holding `prefill` and `mode`.
  - `pendingInboxItem: String?`.
  - `pendingReader: ReaderTarget?`.

  Each stages the request and calls `activateMainWindow()`, the Track P R7 rule. Settings is its
  own window, so this is the only way for it to hand off to the main window.
- **`ProvenanceRouter`** (new, `@Observable`, in the main window's environment) holds
  `stack: [ReaderTarget]` and `isPresented`, with `open(_:)`, `back()` and `close()`. `ReaderTarget` is:
  - `.span(doc, start, end, hash, claimId?)`
  - `.conversation(id)`
  - `.document(doc, focusEntity?)`
- **Menu commands replace hidden buttons.** Today Cmd K and Cmd F are hidden zero-size buttons
  (`ContentView.swift:98-104`, `:594-599`), and the Cmd F one probably fires on the invisible graph
  field while another tab is showing (R6 §4.1, the risk it flagged).
  - A `CommandGroup(after: .textEditing)` adds **"Find in Memory... Cmd K"**, which sets
    `router.pendingPalette`.
  - It also adds **"Find on This Page... Cmd F"**, which calls
    `@FocusedValue(\.pageFind)`. Each page publishes that value with
    `.focusedSceneValue(\.pageFind) { focused = true }`.
  - The menu item is disabled when no page publishes one, so an invisible field can never catch
    the shortcut. Menu items are also discoverable and reachable through AX.

  In the Settings window, Cmd F focuses the sidebar search on macOS 15 and later
  (`searchFocused`, verified in the SDK as macOS 15.0) and does nothing on macOS 14. There, clicking
  or Tab reaches the field.
- **`SettingsSectionLink` gains an optional row** (P5 keeps a single writer):
  ```swift
  struct SettingsSectionLink: View {
      let section: SettingsSection
      var row: SettingsRowID? = nil          // new
      let label: String
      // simultaneousGesture writes BOTH keys, in this file only:
      //   "cicada.settingsSection" = section.rawValue            (unchanged)
      //   "cicada.settingsRowFocus" = "\(row.rawValue)@\(Date().timeIntervalSince1970)"
  }
  ```
  - The row key carries a nonce, so `SettingsScene` never has to clear it (clearing would make a
    second writer). The scene remembers the last nonce it consumed in `@State`.
  - `test_exactlyOneFileWritesTheSettingsSectionSeed`
    (`app/CicadaApp/Tests/CicadaAppTests/SleepQueueCardV3Tests.swift:140-147`) extends to the row
    key: both keys are written only in `SettingsSectionLink.swift`.
- **Opening Settings from the palette with the keyboard** needs spike **S0**, and the result is an
  owner decision (§7).
  - `OpenSettingsAction` (`@Environment(\.openSettings)`) is public API since **macOS 14.0**
    (verified in the 26.1 SDK's SwiftUI interface).
  - The measured failure recorded in `SettingsSectionLink.swift:8-16` and
    `SettingsEntryPointTests.swift:4-41` is the *private selector* `showSettingsWindow:`. It is not
    this API. However, `EmptyStateView.swift:8-14` also forbids an `openSettings()` closure.
  - If S0 shows `openSettings()` opening the scene from the main window on 14, 15 and 26, add
    `SettingsOpener.open(section:row:)` **inside `SettingsSectionLink.swift`** (it writes both keys,
    then calls the action). The palette's Return uses it.
  - If S0 fails, a Settings result in the palette opens on click only (the row is a
    `SettingsSectionLink`), and pressing Return shows the inline hint
    "Click to open Settings (Cmd ,)".

---

## 2. Settings v3

### 2.1 Information architecture

The sidebar keeps a stock `List(selection:)`. That keeps `NavigationSplitView`
(`SettingsSectionTests.swift:34-40`) and keeps AX-selectable rows (AXRow with AXSelected, which is
what `macos-harness` drives). The rows are grouped with `Section` headers, and a native
`.searchable(text:placement: .sidebar)` sits on top. On macOS 26 the stock list gets system glass
automatically. Do not paint over it (the `SidebarView.swift:101` lesson).

```
+--------------------------+-----------------------------------------------------------+
| [Q  Search settings    ] |  Sleep                                                    |
|                          |  When Cicada consolidates what it captured.               |
| CICADA                   |                                                           |
|   (gear) General         |  RUNS                                                     |
|   (face) You             |  +-----------------------------------------------------+  |
|   (hand) Privacy & data  |  | Runs            (Manual)(Daily)(Every N h)(Imports) |  |
|   (book) Memory          |  |   Next run: tonight at 3:00                         |  |
|   (moon) Sleep        <  |  |-----------------------------------------------------|  |
| CUSTOMIZE                |  | At                                      [ 3:00  v ] |  |
|   (pzl)  Integrations    |  +-----------------------------------------------------+  |
|   (plug) Agents          |  ENGINE                                                   |
|   (wave) From anywhere   |  +-----------------------------------------------------+  |
|   (spark) Skills         |  | Engine          [Claude] Claude plan when you start |  |
| ENGINES & KEYS           |  |                 [key] API key on the schedule    >  |  |
|   (cpu)  Engines         |  +-----------------------------------------------------+  |
|   (key)  Plans & keys    |                                                           |
|   (tool) Advanced        |                                                           |
+--------------------------+-----------------------------------------------------------+
```

`SettingsSection` gains cases. **Raw values are machine keys** (R7, `SettingsSection.swift:7-17`).
The five existing raw values do not change, so a persisted selection survives.
`restored(from:)` is unchanged (`:48-53`).

| Case (raw value) | Title (`Copy.*`) | Symbol | Group | Subtitle (<= 60 chars, never repeats the title) |
|---|---|---|---|---|
| `general` | General | `gearshape` | Cicada | "Appearance, text size and setup." |
| `you` (new) | You (`Copy.youSection`) | `person.crop.circle` | Cicada | "Who this memory belongs to." |
| `privacy` (new) | Privacy & data | `hand.raised` | Cicada | "What stays on this Mac, and how to take it with you." |
| `memory` (new) | Memory | `books.vertical` | Cicada | "How Cicada finds and tidies what it knows." |
| `sleep` | Sleep | `moon.zzz` | Cicada | "When Cicada consolidates what it captured." |
| `integrations` | Integrations | `puzzlepiece.extension` | Customize | unchanged |
| `agents` | Agents | `cable.connector` | Customize | unchanged |
| `remote` (new) | From anywhere | `dot.radiowaves.left.and.right` | Customize | "Let AI apps outside this Mac use your memory." |
| `skills` (new) | Skills | `sparkles` | Customize | "Abilities your agents can add, with your consent." |
| `engines` (new) | Engines | `cpu` | Engines & keys | "Which model does Cicada's thinking." |
| `plansAndKeys` | Plans & keys | `key.horizontal` (was `creditcard`, which implies price) | Engines & keys | unchanged |
| `advanced` (new) | Advanced | `wrench.and.screwdriver` | Engines & keys | "The backend, paths and environment switches." |

- `SettingsGroup` (new enum: `cicada`, `customize`, `enginesAndKeys`) gives each group its title
  from `Copy` and its ordered sections.
- Sidebar glyphs use `Label { Text } icon: { Image(systemName:).iconHover() }`, the M1 modifier.
- Window size stays `CicadaTheme.scaled(900) x scaled(640)` (`SettingsScene.swift:48-49`). The
  sidebar column is `min 180, ideal 210, max 240`, because group headers need a little more room
  than today's `160/180/220` (`:27`).

**Detail header with breadcrumb.**

- A top-level section shows its title in `displayFont(24)`, which is Instrument Serif at 22 pt or
  more (R-M3), with the subtitle under it.
- A sub-page shows `< Parent / Title`: the chevron and parent are a button in `textSecondary`, and
  the title is in `displayFont(24)`.
- **Cmd [** goes back, and `Esc` goes back when focus is not in a text field.
- Sub-pages live in a `NavigationStack(path:)` inside the detail column, reset whenever the
  selection changes.
- Sub-pages in v3:
  - From anywhere, then one connector (its recent writes).
  - Skills, then one skill (its needs, terms and install ladder).
  - Privacy & data, then one bank.

  Nothing else nests. Integration management stays in its existing popover
  (`Views/Settings/IntegrationsView.swift:209-213`).

Only General gets imagery: a 56 pt `skyWash` band behind its header (R9 §7 item 4). No other
Settings page shows art.

### 2.2 Page by page: every row, its control, and where its value comes from

Legend for the Status column:
- **moved**: an existing control in a new home.
- **new/api**: a new control over an existing endpoint.
- **new/needs**: needs the backend change named in the row.

#### General

| Row (`SettingsRowID`) | Control | Data / write | Status |
|---|---|---|---|
| `appearance` "Appearance" | `PillPicker` System / Light / Dark | `@AppStorage("cicada.colorScheme")`. Needs `AppColorScheme.system`, which `ThemeStore` resolves from `NSApp.effectiveAppearance`. Today there are only Dark/Light (`SettingsGeneralView.swift:57-63`; R6 §1.1). | moved + new/needs (ThemeStore case) |
| `textSize` "Text size" | slider, a `%` label, and an "Actual size" link | `CicadaTheme.uiScale` binding (`SettingsGeneralView.swift:46-48, 70-98`). Detail line: "Cmd + and Cmd - do the same from any page." | moved |
| `runSetup` "Setup" | an "Run setup again" button | `OnboardingState.reset` plus `router.requestFirstRun()` (`:105-121`) | moved |

#### You (new page; the API exists: `GET/PUT /settings/owner`, `api/routers/settings.py:18-30`; the app calls it today only from onboarding, `Views/Onboarding/OwnerIdentityStep.swift`)

| Row | Control | Data / write | Status |
|---|---|---|---|
| `ownerName` "Your name" | text field, committed on Return or blur | `OwnerSettingsResponse.name`, written with `PUT /settings/owner` | new/api |
| `ownerHandle` "GitHub handle" | text field | `handle`. Detail: "Shows your picture next to what you wrote." (it feeds `Contributor.avatarUrl`, `api/models/schemas.py:187-215`) | new/api |
| `ownerEmail` "Email" | text field | `email` | new/api |
| `ownerPage` "Your page" | the entity's `LogoImage` and name, plus "Show on graph" | `entity_id`, then `AppRouter` and `graphVM.revealEntity` (G123) | new/api |

The page never shows the observer wire id. The pure function `Observer.label` already turns it
into "You" (`Models/Claim.swift:41-47`).

#### Privacy & data (new page)

| Row | Control | Data / write | Status |
|---|---|---|---|
| `memoryLocation` "Where your memory lives" | path text plus "Show in Finder" (app-side `NSWorkspace`) | `GET /healthz` `memoryRoot` (`HealthResponse`, `schemas.py:1080-1099`; already fetched by `LiveMemoryRootProbe`) | new/api |
| `banks` "Memory banks" | a list: name, an "Active" pill, and a `...` menu with Switch, Duplicate, Rename, Export..., Delete... Footer: "New bank", "Load the demo bank", "Import into a bank..." | `store.banks` (`Sync/Store.swift:27`). The actions use `POST /banks`, `/banks/{n}/activate`, `/duplicate`, `/rename`, `/banks/demo`, `/banks/{n}/import` (`api/routers/banks.py:36-197`). Import routes to the upload overlay's existing import-to-bank mode. | new/api |
| `bankExport` "Export a bank" | "Export..." opens an `NSSavePanel` in the **app** | **new** `GET /banks/{name}/export` streams a zip of the bank's markdown and `.git`. The backend never writes outside `$CICADA_HOME`; the app chooses the destination and writes it. | new/needs |
| `bankDelete` "Delete a bank" | "Delete..." opens a sheet: type the bank's name to confirm. Refused for the active bank. | **new** `DELETE /banks/{name}` moves the bank to `<root>/.trash/<name>-<utc>/` and removes it from `banks.yaml`. The sheet says: "It moves to the .trash folder inside your memory folder. Nothing is erased yet." | new/needs (owner decision, §7) |
| `telemetry` "Usage ledger" | read-only state. "On: ids and counts only, never your words." plus "Turn off with `CICADA_TELEMETRY=off` in api/.env" | **new** `StatusResponse.telemetry: "on"\|"off"` | new/needs |
| `outboundConnectors`, `outboundFeeds`, `outboundLogos` under "Reaching the internet" | three read-only rows, each with On/Off and its meaning from CLAUDE.md ("Reaching the outside world"): the nightly connector poll (opt-out), RSS and calendar polling (opt-in), logo fetching | **new** `StatusResponse.gates: {connectorFetch, feedFetch, logoFetch}` (booleans only) | new/needs |
| `credentials` "API keys" | "Stored in ~/.cicada/secrets.env, readable only by you." plus a destructive "Remove all keys..." | loops the existing `DELETE /connections/{id}/key` (`api/routers/connections.py:91`) over `store.connections` rows where `isKeyBased && connected` | new/api |
| `remoteAccess` "Access from other apps" | read-only "Off" or "On, N connectors", plus "Manage in From anywhere >" (in-window navigation, not a SettingsSectionLink) | `GET /remote/status` (Track R) | new/needs (R) |
| `transcripts` "Agent transcripts" | a static fact row: "Cicada reads a finished turn once to capture it, and never again." | none (CLAUDE.md capture rail) | new |

#### Memory (new page, only over endpoints that exist or that Track S adds)

| Row | Control | Data / write | Status |
|---|---|---|---|
| `searchIndex` "Search index" | state text such as "Up to date · rebuilt tonight" and a "Rebuild now" button | **new** `GET/POST /maintenance/search-index` (Track S: FTS5 status and rebuild). 409 while Sleep runs, following the `enrich-links` precedent. | new/needs (S) |
| `dedupSweep` "Look for duplicates" | "Look now" returns a result line such as "3 pairs sent to your Inbox" | existing `POST /maintenance/dedup-sweep` (`api/routers/maintenance.py:35`). No app caller today. | new/api |
| `enrichLinks` "Fetch link previews" | "Fetch now". Detail: "4 s per page, never behind a login." | existing `POST /maintenance/enrich-links` (`:70`), with its 409 semantics (CLAUDE.md "Endpoint traps") | new/api |

#### Sleep (engine moves out)

| Row | Control | Data / write | Status |
|---|---|---|---|
| `sleepRuns` "Runs" | `PillPicker` Manual / Daily / Every N hours / After imports. The detail line is the next run. | `sleepVM.schedule.mode` and `updateSchedule` (`SettingsSleepView.swift:76-103, 155-166`). **Data fix:** "Next run" reads `store.status.value?.nextSleepAt` (`MenuBar/BookwormState.swift:129`, computed server-side per request). Today `SettingsSleepView.swift:127` formats the local picker date, which is wrong in interval and after-import modes. | moved + fix |
| `sleepTime` "At" (daily only) | `DatePicker(.hourAndMinute)` | `:108-126` | moved |
| `sleepInterval` "Every" (interval only) | `Stepper` 1...168 h | `:131-143` | moved |
| `sleepEngine` "Engine" | read-only: two lines with marks, "[mark] <engine> when you start" and "[mark] <engine> on the schedule", plus "Change in Settings -> Engines >" | `GET /sleep/engine` `preview.manual/scheduled` (`EngineCard.swift:171-191`) | moved (read-only) |

#### Integrations (content unchanged; this round adds indexing, marks and hooks)

- **Content.** The categories and rows stay as they are: `IntegrationsView.swift:98-108`, `:184-305`,
  `:312-339`, `:345-379`.
- **Changes this round:**
  - Every channel, harness and export-only row carries
    `.settingsRow(.channel(id))`, `.harness(id)` or `.exportOnly(id)`, so the search can land on it.
  - The harness rows' SF Symbol (`:317-325`) becomes `OriginMark(origin:)`, fixing a logo gap.
  - Hooks for the new categories that Tracks N and F fill: "Voice & meetings" (R-N4) and
    "Folders" (R-F1). Both are standing sources, so they belong here under the G126 rule.

#### Agents ("On this Mac")

| Row | Control | Data | Status |
|---|---|---|---|
| `agentsInstall` "One-time install" | `CommandBox` with `make install` | `ConnectView.swift:319-337` | moved |
| `.agent(id)` x7 | a disclosure row: logo tile, name, blurb. Expands to steps with `CommandBox`es and the deeplink pill. | `AgentSetupCatalog.all` (`ConnectView.swift:46-193`) | moved (collapsed by default; one open at a time) |
| `agentsCloud` "claude.ai, ChatGPT and your phone" | pointer row: "Use From anywhere >" | replaces the "possible future work" card (`ConnectView.swift:339-359`) | new |

The optional Claude Code skill step (`ConnectView.swift:85-88`) moves to **Skills > Cicada's own**,
with a pointer row left in its place.

#### From anywhere (Track R; this is the IA and row list only, and R4 §5.6 is the behaviour spec)

| Row | Control | Data |
|---|---|---|
| `remoteSwitch` "Let AI apps outside this Mac use your memory" | a toggle, **off by default**. Detail: "Works while this Mac is awake and online." | `GET/PUT /remote/status` (R-R1) |
| `remoteReach` "Reach" | a state line ("Tailscale connected · Funnel off"), one command in a `CommandBox`, "Cicada never opens a tunnel on its own.", and the Mac-name warning | Tailscale and ngrok detection (R4 §5.6.2) |
| `remoteNew` "New connector..." | opens a sheet: a logo grid, name, scopes as plain verbs, expiry `PillPicker` 7 / **30** / 90 days, and the footer "Can search, read and record. Can't delete or rewrite." | `POST /remote/connectors` |
| `.connector(id)` | logo, label, scope chips, "Expires in N days", "Never used" or "Last used ...", Revoke, and a push to its recent-writes sub-page (each write links into the Reader, §4.4) | `GET /remote/connectors` |

The shown-once screen and the per-app steps are a sheet, not a row (R4 §5.6.4). The token field has
`.privacySensitive()`, and the sheet never re-renders the token after it is dismissed.

#### Skills (new page; R5 §5, including the placement amendment in §5 of this doc)

```
Skills
Abilities your agents can add, with your consent.

CICADA'S OWN
+-----------------------------------------------------------------------------+
| [worm] cicada           Recall and save policy     (Installed: Claude Code) |
|------------------------------------------------------------------------------|
| [worm] cicada-librarian Consolidate as you work    (Not installed) [Install]|
+-----------------------------------------------------------------------------+
RECOMMENDED                                     Reviewed 2026-09-23 · 5 skills
+-----------------------------------------------------------------------------+
| [mark] Watch a video    MIT · needs ffmpeg, yt-dlp            [Details  >]  |
|        Your agent watches a saved video; Cicada keeps timestamped quotes.   |
|        ! Downloads with yt-dlp. YouTube's terms restrict this.              |
|------------------------------------------------------------------------------|
| [mark] Paper lookup     MIT · no key needed                   [Details  >]  |
| ...                                                                         |
+-----------------------------------------------------------------------------+
```

| Row | Control | Data |
|---|---|---|
| `.skill("cicada")`, `.skill("cicada-librarian")` | an install-state pill (Installed / Not installed / Changed by you) per harness, and a primary "Install" | `GET /skills/recommended` `installed` enums, derived per request (R5 §5.4). "Install" writes only through the app's `SkillInstaller` after the consent sheet (R5 §5.3 rung 4). |
| `.skill(id)` for the <= 5 recommended | pushes the detail sub-page: why, licence, needs chips (binaries, keys, network hosts), a ToS note when present, harness pills, and the install ladder (Copy command / Open in Terminal) | `api/data/recommended_skills.json` through `GET /skills/recommended` and `/{id}/plan?harness=` (R5 §5.2, §5.9) |

- The page never shows a download count, star count or price.
- The recommended list is capped at 5 (R5 §3 "Budget rule").
- Tabs for G112 ("About you") and G72 ("In your harnesses") are **not shown until built**.

#### Engines (new page; R-E4, R2 §4.5, R1 §5.2)

```
Engines
Which model does Cicada's thinking.

+--------+ +------------+ +-------------+ +----------+ +-----------+
| (auto) | | [Claude]   | | [ChatGPT]   | | [Ollama] | | [key]     |
| Auto   | | Claude plan| | ChatGPT plan| | On this  | | API key   |
|Best one| | Max        | | Sign in  >  | | Mac      | | OpenAI    |
| free   | |      (o)   | |  (disabled) | | 2 models | |           |
+--------+ +------------+ +-------------+ +----------+ +-----------+
MODEL
 Model                                   [ claude-sonnet-...  v ]
 Or type a model id                      [                      ]
WHAT RUNS
 When you press Consolidate              [Claude] Claude plan · sonnet
 On the schedule                         [key] API key · <model>
   Scheduled cycles never spend plan quota.
 Ask                                     Same engine as a cycle you start
API KEY (shown only while API key is chosen; A3)
 Use my Claude plan when I start a cycle  [ on ]
   Only for cycles you start.
```

| Row | Control | Data / write |
|---|---|---|
| `engineChoice` "Engine" | a card row with radio semantics. Each card has a mark, title, detail and selected ring. An unavailable card stays visible and focusable, with its reason as the detail. This replaces the segmented picker at `EngineCard.swift:69-91`. | `GET /sleep/engine` `candidates[{id,label,available,connected,models,detail}]`. The write is `PUT /sleep/engine` (G122, `api/routers/sleep.py:194-202`). |
| `engineModel` "Model" | a picker over `candidate.models` plus a free-text field for `agent` and `codex`, and a picker plus `CommandBox` for `local` | `EngineCard.swift:116-155`. A `codex` case is added per R2 §4.5. |
| `enginePreview` "What runs" | two read-only lines with marks. The ruling-4 caption shows whenever the two lines differ, and it is never hidden. | `preview.manual`, `preview.scheduled` (`EngineCard.swift:172-191`) |
| `engineAsk` "Ask" | a read-only line | Needs R-E4: Ask follows the Settings engine. Until then the line reads "Set in api/.env" (R2 §1.4.4, honest). |
| `engineAutoClaude` "Use my Claude plan when I start a cycle" (was "Auto may use my Claude plan"; see A3) | a toggle, shown only while the API key card is chosen. **Moved** from the Claude plan card on Plans & keys (`ConnectionsView.swift:175-186`). | the same `PUT /connections/claude-plan/prefs` `use_for_sleep` (`api/routers/connections.py:101`) |

- **Marks:** Auto uses a symbol. The plan cards use `claude-code` and `codex` (the
  `ConnectionsView.swift:105-111` map). Ollama uses `ollama.png`, which is bundled but not shown
  today (R6 §2.8). A key uses the provider's mark (`claude`, `chatgpt`, `gemini`) when one is
  configured, else a symbol.
- **Sign-in never happens on this page.** A "Sign in >" detail navigates to
  `plansAndKeys` with `focusRow = .connection(id)`, which is in-window navigation. There is one
  sign-in implementation, on Plans & keys.
- **Plan-window percentage** ("5-hour window 62% used · resets 14:00", R1 §5.2): **hidden until the
  owner rules** (§7). The only place it could appear is the plan card's detail line.

#### Plans & keys (credentials only)

| Row | Control | Data | Change |
|---|---|---|---|
| `.connection(id)` | mark, label, plan label (no price), status pill (Connected / Not connected / Not installed), account line, and the action: Connect, Disconnect, or a SecureField with Save / Remove key. A disclosure shows `how`, `powers` and the login flow (device code, or terminal fallback). | `store.connections` via `ConnectionsViewModel` (`ConnectionsView.swift:6-91`, `:93-260`) | **Marks:** Ollama gets `ollama.png`, and keys get provider marks (the `:105-120` gap). **Removed:** the `$` in `priceLine` (`Models/Connection.swift:115-124`, rendered at `ConnectionsView.swift:123`) and the Max tier picker, whose own label says "for cost estimates only" (`:160-173`). Both violate the 2026-09-03 no-price ruling. **Moved:** the "Use for Sleep" toggle, to Engines. |

The refresh button (`:16`) stays in the header trailing slot. The disconnect confirmation (`:52-60`)
is unchanged.

#### Advanced (new page)

| Row | Control | Data |
|---|---|---|
| `backendStatus` "Backend" | "Connected" or "Not answering", version, and entity and episode counts through `UsageFormat.count` | `store.isConnected`, and `GET /healthz` `version/entityCount/episodeCount` (`schemas.py:1080-1099`) |
| `mcpCommand` "MCP server" | a `CommandBox` with the python and server paths | `AgentSetupCatalog` inputs (`ConnectView.swift:47-49`) |
| `apiToken` "API token" | "~/.cicada/api_token" plus "Show in Finder". The token itself is never displayed. | a static path, and `CICADA_API_TOKEN` override detection through the new `StatusResponse.envOverrides: [name]` (names only, never values) |
| `envOverrides` "Set in api/.env" | a read-only list of names, e.g. `CICADA_LLM_MODE` ("pins the engine, even on the schedule") | the same new field |

### 2.3 Where every existing control goes

| Existing (file:line) | New home |
|---|---|
| Appearance Dark/Light (`SettingsGeneralView.swift:57-63`) | General > Appearance (adds System) |
| Text size slider, %, Actual size (`:70-98`) | General > Text size |
| Run setup again (`:105-121`) | General > Setup |
| Runs segmented (`SettingsSleepView.swift:83-96`) | Sleep > Runs (PillPicker) |
| Daily time, Next run (`:108-129`) | Sleep > At; Next run is the Runs detail line (data fixed) |
| Every N hours (`:131-143`) | Sleep > Every |
| After-imports caption (`:144-147`) | Sleep > Runs detail line |
| `EngineCard` in Sleep (`:46`) | Engines (the whole card); Sleep keeps a read-only Engine row |
| Engine segmented (`EngineCard.swift:69-91`) | Engines > card row |
| Model fields (`:116-155`) | Engines > Model |
| Previews + ruling-4 caption (`:171-191`) | Engines > What runs; mirrored read-only on Sleep > Engine |
| Integrations, all rows (`IntegrationsView.swift`) | unchanged, now indexed |
| Agents prereq card (`ConnectView.swift:319-337`) | Agents > One-time install |
| Agent setup cards (`:251-253`, `:364-420`) | Agents > disclosure rows |
| Claude Code skill step (`:85-88`) | Skills > Cicada's own |
| Web-apps note (`:339-359`) | Agents > pointer to From anywhere |
| Onboarding intro (`ConnectView(isOnboarding:)` `:224-248, :301-317`) | unchanged; `FirstRunSheet` still embeds it |
| Plans & keys cards (`ConnectionsView.swift:93-260`) | Plans & keys rows (price and tier removed, marks fixed) |
| Use for Sleep toggle (`:175-186`) | Engines > Auto |

Onboarding reuse: `FirstRunSheet` step 2 embeds `EngineCard` today. It will embed the new
`EngineChooser` (the card row plus the What runs block), so onboarding and Settings show one
component.

### 2.4 Settings search

**The index.** `Views/Settings/SettingsIndex.swift` (new, pure):

```swift
struct SettingsRowID: RawRepresentable, Hashable { let rawValue: String }   // "sleepRuns", "channel:pinterest"
struct SettingsEntry: Identifiable, Hashable {
    let id: SettingsRowID
    let section: SettingsSection
    let title: String          // exactly what the row renders
    let keywords: [String]     // synonyms, vendor names, env-var names
    let detail: String?        // the row's one-line detail (searched at weight 0.4)
}
enum SettingsIndex {
    static let staticEntries: [SettingsEntry]                 // ~45 rows, in page order
    static func dynamicEntries(channels: [SourceChannel], connections: [ConnectionStatus],
                               agents: [AgentSetup], skills: [RecommendedSkill],
                               connectors: [RemoteConnector]) -> [SettingsEntry]
    static func search(_ q: String, in entries: [SettingsEntry]) -> [SettingsHit]  // QuickMatch
}
```

- **Static rows** are every row in §2.2. Example keywords:
  - `textSize`: zoom, font, bigger, smaller, scale, Cmd +.
  - `appearance`: dark, light, theme, mode, system.
  - `sleepRuns`: schedule, nightly, daily, interval, automatic, consolidate.
  - `engineChoice`: model, llm, claude, chatgpt, codex, ollama, api key.
  - `telemetry`: analytics, tracking, ledger, CICADA_TELEMETRY.
  - `outbound*`: network, internet, fetch, CICADA_ALLOW_FEED_FETCH.
  - `bankExport`: backup, download, zip, take out.
  - `bankDelete`: remove, erase.
  - `remoteSwitch`: phone, claude.ai, chatgpt, connector, tunnel, tailscale, ngrok.
- **Dynamic rows** come from the Store snapshots the Settings window already has in its
  environment (`CicadaApp.swift:226-239`):
  - `store.channels` (`Store.swift:30`): the title is `channel.label`, and the keywords are the id
    and category title.
  - `store.connections` (`:39`).
  - `AgentSetupCatalog.all` ids and names.
  - `GET /skills/recommended`.
  - `GET /remote/connectors`: the label and app kind, never the token.
- **Section-level match:** a section also matches on its own title and subtitle. That makes it
  visible in the sidebar with no row hits.

**Filtering the sidebar (live, on every keystroke).**

- With an empty query, the sidebar is unchanged.
- With a query:
  - A section stays when its title matches or at least one of its rows matches. It shows a count
    `.badge(n)` on the list row (native `badge`, macOS 12+).
  - A group with no surviving sections is hidden.
  - With zero hits, the sidebar shows one non-selectable row: "No settings match '<q>'".
  - The count badge's text twin is the row's accessibility value: "3 matching settings".

**The results page (detail column).**

```
Results for "sleep"                                          7 settings
SLEEP
  (moon) Runs              Sleep > Runs            Daily at 3:00          >
  (moon) Engine            Sleep > Engine          Claude plan / API key  >
ENGINES & KEYS
  (cpu)  Use my Claude plan when I start a cycle   Engines > API key   On   >
PRIVACY & DATA
  ...
```

- It shows when the query is non-empty and the person has not picked a sidebar row since typing.
  Picking a sidebar row shows that section, and its matching rows carry a persistent 3 pt
  dandelion leading bar for as long as the query is active. The bar does not move.
- It is a `List(selection:)` of hits grouped by section. That keeps AX-selectable rows for the
  harness.
- Each hit shows:
  - the section glyph;
  - the title, with matched ranges in semibold;
  - the breadcrumb "Section > Row" in `captionFont`;
  - a cheap live value (for example the schedule mode, Connected / Not connected, or On / Off);
  - a chevron.
- The live values come from values the page's view models already hold, so there are no extra
  fetches.
- List selection binding: the sidebar `List` binds to a `Binding<SettingsSection?>` whose `get`
  returns `nil` while the results page shows. `selection` itself stays non-optional, so the
  `@AppStorage` mirror at `SettingsScene.swift:34-41` keeps working unchanged. Both halves of
  that test keep matching.

**Keyboard.**

- Return in the search field opens the top hit (`.onSubmit(of: .search)`).
- Tab moves focus into the results list, where the native list handles Up/Down and Return.
- Esc clears the query, which is native `.searchable` behaviour.
- Cmd F focuses the field on macOS 15+ (§1.4).

**Landing on a row: navigate, scroll, highlight, announce.**

1. `selection = hit.section`, `resultsMode = false`, `focusRow = hit.id`.
2. The page's `ScrollViewReader` runs `scrollTo(hit.id, anchor: .center)` in the next runloop turn,
   after layout. Every `SettingsRow` sets `.id(rowID)`.
3. `SettingsRowAnchor` draws the wash: a `RoundedRectangle` in `dandelionFill.opacity(0.35)` with a
   1 pt `dandelion` stroke.
4. It appears immediately, holds for `rowHighlightHold`, then fades over `rowHighlightFade`.
5. The row gets `@AccessibilityFocusState` focus, and
   `AccessibilityNotification.Announcement("\(section.title), \(title)")` is posted.
6. Increase Contrast: the stroke becomes 2 pt `textPrimary`.

The same anchor serves deep links. `SettingsSectionLink(section:, row:)` seeds the row nonce
(§1.4). One example is the study room's lamp (the Track Z proposal in R6 §3.5.4), which lands on
`sleepRuns`.

**The same highlight inside a page.** An in-window pointer ("Change in Settings -> Engines",
"Sign in >") sets `selection` and `focusRow` directly. It never goes through `UserDefaults`, because
that is the same window.

### 2.5 Interaction specs (Settings)

| Trigger | Response | Duration constant | Reduce Motion | Text twin | Accessibility |
|---|---|---|---|---|---|
| Type in the sidebar search | The sidebar filters. Badges show counts. The detail column shows results. | none (instant) | same | badge value "N matching settings"; results header "N settings" | the search field is labelled "Search settings"; the results list is a standard `List` |
| Return, or click a result | Navigate, scroll, highlight the row | `rowHighlightHold` then `rowHighlightFade` | wash shown for 1.8 s, removed with no fade | the breadcrumb in the header | VO focus moves to the row, plus an announcement |
| `SettingsSectionLink(row:)` from the main window | Settings opens on the section, lands and highlights the row | same | same | same | same |
| Hover a sidebar row | the glyph does one `iconHover` (wiggle on 15+, bounce on 14) | M1's `CicadaMotion` symbol effect | `symbolEffectsRemoved` | none needed | none |
| Choose an Engine card | selection ring moves, `PUT /sleep/engine`; the What runs lines update from the server echo (ruling 6: no optimistic apply, `EngineCard.swift:12-16`) | `CicadaMotion.hover` for the ring | instant | the What runs lines | cards are one radio group via `.accessibilityRepresentation { Picker }`; a disabled card reads its reason |
| Cmd [ on a sub-page | pop to the parent | system | system | the breadcrumb | the back button is labelled "Back to <parent>" |
| Delete bank... | a sheet that requires typing the name; the button is disabled until it matches | system sheet | system | "It moves to the .trash folder..." | the destructive role is announced |

### 2.6 Tests (Settings)

- `SettingsSectionTests`:
  - Keep all four existing tests.
  - Add `testExistingRawValuesAreStable`: the five old raw values are unchanged.
  - Add `testEveryNewTitleComesFromCopy` and `testEverySectionHasAGroup`.
- `SettingsIndexTests`:
  - Every static `SettingsRowID` appears once in `staticEntries`.
  - Every entry's section is a real case.
  - Ranking fixtures ("zoom" finds `textSize`, "phone" finds `remoteSwitch`, "tele" finds
    `telemetry` before `outboundConnectors`).
  - Dynamic entries are built from fixture snapshots, and no token or secret string appears in any
    entry.
- A source lint: every static row id is rendered by exactly one `.settingsRow(.<id>)` under
  `Views/Settings/`. This catches a row that was indexed but deleted, or renamed on one side only.
- Extend `test_exactlyOneFileWritesTheSettingsSectionSeed` to the row key.
- `CopyConstantsTests`:
  - New subtitles are <= 60 characters.
  - The new pointers (`Copy.settingsEngines`, `Copy.settingsFromAnywhere`, `Copy.settingsSkills`,
    `Copy.settingsPrivacy`) are built from their parts, like `settingsPlansAndKeys` (`Theme/Copy.swift:40`).
- `ConnectionPriceTests` (new): `priceLine` contains no `$`, and no Settings view renders
  `priceUsdMonth`.

---

## 3. The Cmd-K find palette

### 3.1 Container and modes

**Container.**

- It is an **overlay on `ContentView`'s root**, above the `NavigationSplitView`, and not a
  `.sheet` (`ContentView.swift:123-134`). A sheet is modal, attaches to the title bar, and cannot
  be glass.
- Width is `scaled(640)`. The top sits at 14% of the window height. Maximum height is
  `min(scaled(560), window * 0.72)`.
- The shape is `.liquidGlass(.control, in: .rect(cornerRadius: 18))` (R-M5 lists the Cmd-K panel as
  chrome glass). The M1 fallback is `regularMaterial`, or opaque `surfaceElevated` under Reduce
  Transparency.
- **No glass on glass:** rows, chips and the answer area use fills.
- A click-outside scrim: `Color.black.opacity(0.12)`, `accessibilityHidden`. It is a light dim,
  not the entity card's 0.45.
- Enter: `paletteIn`. Leave: `paletteOut`.
- It never opens over `FirstRunSheet`.

**Modes.** There are two, shown in a `PillPicker` at the right of the field: **Find** and **Ask**.

- **Find** is the default. The field glyph is `magnifyingglass` and the prompt is
  "Search your memory".
- **Ask** is today's `AskPanel` body inside this panel, reusing `AskViewModel` unchanged
  (`Ask/AskViewModel.swift`). The glyph is `sparkle.magnifyingglass` and the prompt is
  "Ask your memory".
- **Cmd Return** in Find asks the current text: it switches to Ask and submits.
- In Find, the **first row** is always "Ask Cicada: '<query>'" with a `Cmd Return` hint, so the
  mouse path exists too.
- In Ask, Esc returns to Find with the text kept. A second Esc closes the palette.

**Entry points.**

- The "Find in Memory... Cmd K" menu command, from any window (§1.4).
- `AskButton` on the graph (`ContentView.swift:509-531`) is renamed "Search" and opens Find.
- The pages' "Search all of memory for '<q>'" empty-result rows open the palette prefilled.

### 3.2 Two tiers

**Tier 1: local and instant, on every keystroke, with no network.**

`QuickIndex` (new, `Search/QuickIndex.swift`) is an immutable value built **off the main actor**
(`Task.detached`). It is swapped in on main whenever any of its inputs' `loadedAt` changes. Queries
never rebuild it.

| Group | Store source (file:line) | Fields indexed (weight) |
|---|---|---|
| Entities | `store.graph.value?.nodes` (`Sync/Store.swift:25`; `GraphNode`, `Models/Entity.swift:852-882`) | name (1.0), **aliases** (0.9, needs `GraphNode.aliases`, §3.9), tags (0.7), summary (0.4); tie-break `degree` |
| Sources & papers | `store.sources` (`:28`; `MediaFeedItem`, `Services/APIClient.swift:198-224`) | title, site, channel, origin, tags, description, about, paper authors/doi (Track F); tie-break `savedAt` |
| | `store.sourcesOverview` (`:37`), `store.channels` (`:30`) | label |
| Inbox | `store.visibleInbox` (`:57-59`) | question/title (1.0), entityName (0.7), cause excerpt (0.4); tie-break `priority` |
| Settings | `SettingsIndex` static + dynamic (§2.4) | as in Settings |
| Asked before | the `.askHistory` cache (`AskViewModel.swift:31-34`) | question |
| Banks | `store.banks` (`:27`) | name, shown as a "Switch to <bank>" action |
| Actions | static table (§3.3) | title + keywords |

Budget: <= 8 ms p95 per keystroke over 3,000 entities plus 1,500 media plus 200 inbox items. This is
tested (§3.10).

**Tier 2: server, debounced and cancellable.**

- It uses `.task(id: query)` with `SearchTiming.serverDebounce`. Each new keystroke cancels the
  task in flight.
- It is skipped for queries shorter than 2 characters.
- **Pass A (prefix, per keystroke):** `GET /search?q=&kinds=entity,claim,episode,media&mode=prefix&per_kind=5`.
  This is FTS only and never embeds (R3 P1). Budget: 50 ms p95.
- **Pass B (hybrid):** `mode=hybrid` fires once the query has been idle for
  `SearchTiming.semanticIdle`, or immediately on "Search deeper" when fewer than 3 results show.
  It fuses the FTS and vector legs with RRF (R3 P1). Budget: 200 ms, the G58 target.
- **Merge rule (the list never jumps):**
  - Local rows render first.
  - Server hits dedupe against them by `(kind, id)` and **append** below the local rows in their
    group.
  - Rows already displayed for this query never reorder. A new keystroke re-sorts everything.
  - The selected row is tracked by id, never by index.
  - The Top hit comes from tier 1 only.

### 3.3 Groups and rows

The order is fixed: **Top hit, Entities, Conversations, Beliefs, Sources & papers, Inbox,
Settings, Actions, Asked before.** Each group shows at most 5 rows, then "Show all N"
(`groupExpand`), where N is the honest count: the local match count, or the server's `total`. When
the server capped its results without a total, the row says "More..." and never a guessed number.

```
+---------------------------------------------------------------------------+
| (Q) sqlite vec_                                        (Find)(Ask)   (x)  |
|---------------------------------------------------------------------------|
|  Ask Cicada: "sqlite vec"                                     Cmd Return |
|  TOP HIT                                                                  |
| >[logo] sqlite-vec                    tool          Return open on graph  |
|  ENTITIES                                                                 |
|  [logo] vector index                  concept                             |
|  CONVERSATIONS                                                   3 of 9  |
|  [CC] Fix the sync race          3 Sep   "...we moved the index to        |
|        You said                          *sqlite-vec* so search is..."   |
|  [GPT] Planning notes            12 Aug  "...sqlite-vec or FAISS..."      |
|  BELIEFS                                                                  |
|  (i) alpha-project uses sqlite-vec  [You said, 3 Sep]                     |
|  SETTINGS                                                                 |
|  (book) Search index        Memory > Search index        Up to date       |
|  -------------------------------------------------------------------------|
|  12 results in 5 groups · Searching conversations...                      |
+---------------------------------------------------------------------------+
```

| Kind | Row | Return | Option-Return |
|---|---|---|---|
| Entity | `LogoImage(entityId:name:type:)` 20 pt, name with matches bold, type capsule, summary line | switch to Graph, then `graphVM.revealEntity(id:)` (G123; the pattern at `ContentView.swift:123-134`) | open it in Clusters (the `TopicsView` detail) |
| Conversation (episode passages grouped by conversation id, "3 matches") | `OriginMark(harness)` 20 pt, title, date, and a `QuoteBlock` snippet in `quoteFont` with the speaker label and the match bold | open the Reader at the best passage's span (§4.4) | Sources, that harness's conversations |
| Belief (claim) | the claim text (wikilinks rendered), the subject's `LogoImage`, and its first `EvidenceChip` | reveal the subject, then open its card on Perspectives, scrolled to the claim | open the Reader at the claim's first evidence span |
| Source / paper | `OriginMark(origin)` or the site logo, title, site/channel, and the media type capsule | the Feed item sheet | open the URL externally |
| Inbox | kind glyph, question, entity name | Inbox tab with the item expanded (`router.pendingInboxItem`) | none |
| Setting | section glyph, title, breadcrumb, live value | open Settings on the row (spike S0, §1.4) | none |
| Action | symbol, verb, shortcut | run it | none |
| Asked before | `arrow.uturn.left`, question | Ask mode with the cached answer (`AskViewModel.select`, `:58-61`) | re-ask |

**Actions table** (static, `Search/PaletteActions.swift`):

- "Consolidate now", or "Stop consolidating" while running. Both call the same `sleepVM` methods
  as the Sleep page, and neither shows an estimate.
- "Add a source" (Cmd N).
- "Import an export..." (the upload overlay).
- "Go to Graph / Clusters / Feed / Sleep / Inbox / Sources" (Cmd 1-6).
- "Switch to dark / light".
- "Zoom in / out / actual size".
- "Open Settings > <section>" for every section.
- "Switch to <bank>" for each bank.

Each action's title comes from `Copy`, so pointers stay exact.

### 3.4 Keyboard map

| Keys | Action |
|---|---|
| Cmd K | open the palette; if it is open, close it |
| typing | filter (tier 1 at once, tier 2 debounced) |
| Up / Down | move within and across groups, skipping headers |
| Cmd Up / Cmd Down | first / last row |
| Tab / Shift Tab | first row of the next / previous group |
| Return | primary action of the selected row |
| Option Return | secondary action (the table above) |
| Cmd Return | ask the current text (Ask mode) |
| Cmd C | copy the selected row's link (`cicada://entity/<id>`, the scheme `MarkdownBody.entityLink(for:)` already mints; a conversation copies its title) |
| Esc | Ask to Find; then clear the text; then close |

Focus stays in the text field the whole time. Arrow keys are handled with `.onKeyPress`
(macOS 14), the same way `GraphSearchField` does today (`ContentView.swift:578-580`).

### 3.5 Ask mode inside the palette

- The body is today's answer view (`AskPanel.swift:111-150`), with three changes:
  1. **Citation snippets are visible.** Each citation chip gains a `QuoteBlock` line of up to 2
     lines under it. Today the snippet exists only in `.help` (`AskPanel.swift:168`).
  2. **`sourceEpisodes` render as evidence-style chips** ("From a conversation · 3 Sep"). The
     field is decoded but never shown (`Models/Ask.swift:17`). A chip opens the Reader with
     `.document(ep, focusEntity: citation.entityId)`, and the server derives the mention span
     (§4.8). The chip is labelled "Mentioned here" and never "You said", because it is derived.
  3. When `/ask` starts returning `citations[].evidence` (§4.8), those chips become full
     `EvidenceChip`s.
- The error banner uses `CicadaTheme.danger`, not `entityColor(for: .deadline)`
  (`AskPanel.swift:244,250`; R6 §2.11).
- The confidence meter is unchanged.

### 3.6 States

| State | What shows |
|---|---|
| Empty query | **Recent**: the last 6 opened results, stored as ids only in a new per-bank `.quickRecents` domain that works like `.askHistory` (no server counterpart, and `Store.refresh` skips it, `Sync/Snapshot.swift:37-41`). Then **Asked before** (3), then **Suggested actions** (Consolidate now when `unprocessed > 0`, "Answer N questions" when the inbox is non-empty). |
| Server tier in flight | A 2 pt indeterminate hairline under the field. Reduce Motion: a static caption "Searching conversations..." in the Conversations header. No skeletons where local rows exist. |
| Backend unreachable (`!store.isConnected`) | Local groups render normally. Footer: "Conversations and beliefs need the Cicada backend. It isn't answering." |
| No results | "Nothing matches '<q>'." plus the Ask row (always present) and "Search deeper" (Pass B). |
| Old backend (no `kinds` support) | `/search` returns entities only, and those merge into Entities. The Conversations and Beliefs groups are hidden, never shown empty. |

### 3.7 In-page search fields, upgraded consistently

| Page | Today | v3 |
|---|---|---|
| Graph | `GraphSearchField`, name only, ranked (`ContentView.swift:558-651`) | `CicadaSearchField(.overCanvas)`. `QuickMatch` over name, aliases and tags. Rows get a hover highlight, a `LogoImage` and the type dot (R6 §2.1). Cmd F comes through the page's `focusedSceneValue`, and the hidden button at `:594-599` is removed. |
| Clusters | re-lowercases the full markdown per keystroke, no highlight (`Views/Topics/TopicsView.swift:87-113, 188`) | a precomputed index keyed on `store.graph.loadedAt`, and matches highlighted in rows |
| Feed | title/site/tags only (`ViewModels/FeedViewModel.swift:60-68`) | plus description, about, url, channel, origin, and paper authors/doi (R7 §5.2) |
| Harness conversations | `.roundedBorder` field, filters the <= 200 loaded rows (`Views/Sources/HarnessConversationsView.swift:21-23`) | `CicadaSearchField`. Local filter first; beyond the cap it calls `GET /conversations/recent?q=` (new, applied **before** the cap like `harness`, `api/routers/conversations.py:90-133`) |
| Inbox | none | new field over question, title, entity name and cause excerpt, plus the missing `divergence` and `normalization` kind chips (R6 §2.6) |
| Settings | none | the native sidebar search (§2.4) |

Every page's "no match" state ends with the row "Search all of memory for '<q>' (Cmd K)".

### 3.8 Interaction specs (palette)

| Trigger | Response | Duration constant | Reduce Motion | Text twin | Accessibility |
|---|---|---|---|---|---|
| Cmd K | the palette appears, the field is focused, and the empty state shows | `paletteIn` | appears at once | none (the field has focus) | the container is labelled "Find in memory" with `.isModal`; focus moves to the field |
| a keystroke | local rows update | none | same | footer "N results in G groups" | the footer is a live region (`.accessibilityAddTraits(.updatesFrequently)`) |
| Up/Down | the selection moves, and the hint shows on the selected row | none | same | the selected row shows its Return / Option-Return hints | announcement: "<kind>, <title>, <i> of <n>" |
| server results arrive | rows append in their groups | none (no insertion animation, so nothing jumps) | same | the group header count updates | the group header is a header trait; one rotor per group |
| Return on an entity | the palette closes, the tab switches, and the graph reveals the node | `paletteOut`, then the graph's own reveal | instant | the entity card opens | focus goes to the card |
| Cmd Return | switches to Ask and submits | `CicadaMotion.morph` for the pill | instant | "Asking your memory..." | announcement: "Asking" |
| Esc | Ask to Find, then clear, then close | `paletteOut` on close | instant | none | focus returns to the element that held it before opening |

**Telemetry.** Opening a result emits the existing G124 `read` kind with `{entity_id, surface:
"palette"}`, or a conversation id, as ids and enums only. **The query is never logged, stored or
sent anywhere except `GET /search`.** Recents store result ids, not queries. Ask history keeps its
current behaviour.

### 3.9 Server changes Track S owns (the contract the palette needs)

1. **`GET /search`**, additive, with the old call shape still valid:
   - Parameters: `q`, `kinds` (csv of `entity|claim|episode|media`; the default `entity` preserves
     today's behaviour, `search.py:110-121`), `mode` (`prefix|hybrid`, default `hybrid`),
     `per_kind` (<= 20).
   - **The whole body runs in `run_in_threadpool`.** Today it is blocking work inside `async def`
     (R6 §4.2).
   - The substring fallback goes through `bank_index`, never a parse of every entity file per
     call (`search.py:81-107`).
   - `SearchHit` gains these fields: `kind`, `subtitle`, `snippet_offsets: [[s,e]]`
     (scalar offsets into `snippet`), `episode_id`, `conversation_id`, `harness`, `origin`,
     `timestamp`, `start`, `end`, `hash` (span into the evidence text, for claim/episode hits),
     `evidence_kind`, `subject_id`, `matched_field`.
   - The response gains `totals: {kind: int}` for honest "Show all N" counts.
2. **Episode passages get offsets.** Two options:
   - `vector_index._chunk_episode_body` (`api/services/vector_index.py:643-664`) strips the body
     before chunking. It becomes `_chunk_episode_spans(body) -> [(start, end)]`, with offsets into
     the unstripped `parsed.body`, which is exactly the evidence text for an episode
     (`api/services/evidence.py:94-105`). Store `start`, `end` and `hash` in the passage metadata.
   - Or, preferably, the FTS5 rows carry them from the start.
3. **FTS5 derived index** (spec decision 7): `entities(name, aliases, tags, summary)`,
   `claims(text, object, subject_id, evidence_episode, start, end, kind, hash)`,
   `episodes(title, harness, conversation_id, passage, start, end)`, `media(title, site, description)`.
   - It is rebuilt by Sleep and on write, lives beside `vector_index.db`, is gitignored, and
     deleting it costs CPU only (ruling 3).
   - The same table answers `GET /episodes/{id}/citations` (§4.8).
4. **`GET /conversations/recent?q=`**: a title match applied before the cap, folded into the ETag
   `extra=`, the same pattern as `harness`/`origin` (`conversations.py:109-117`).
5. **`GraphNode.aliases`** (additive, capped at 8 per node) on `/graph`. **Measure the payload
   first:** `/graph` is about 1.8 MB on the live bank (CLAUDE.md). If aliases add more than 10%,
   leave them off the graph payload and serve them from FTS only. The local tier then matches
   names, and aliases arrive with the server tier.

### 3.10 Tests (palette and search)

- `QuickMatchTests`: tiers, AND semantics, diacritics, initials, weights, tie-breaks.
- `QuickIndexLatencyTests`: a synthetic 3,000/1,500/200 index, 50 queries, p95 <= 8 ms (on CI,
  in a release build).
- `PaletteMergeTests`: server rows dedupe by `(kind, id)`, only append, never reorder displayed
  rows; the selection survives an append; the Top hit is never replaced.
- `PaletteDebounceTests`: an injected clock (the `SyncEngine` pattern); a keystroke cancels the
  in-flight task; queries under 2 characters make no request.
- `PaletteTelemetryTests`: a `read` event carries no string longer than an id, and the query never
  reaches the ledger.
- Backend:
  - `kinds` is honoured.
  - `mode=prefix` never loads the embedding model (assert on the `providers._EMBED_CACHE`
    access).
  - `/search` does not block the loop (a concurrent `/healthz` answers during a slow search).
  - Hits carry spans whose `text[start:end]` contains the match.
  - `q=` on `/conversations/recent` is applied before the cap.

---

## 4. The provenance viewer (G118 slice 2) and "who contributed what"

### 4.1 Model changes (all additive; an older backend never blanks a view, R10)

**Swift.**

- `Models/Claim.swift:98-147` gains:
  ```swift
  struct Evidence: Codable, Hashable {        // mirrors EvidenceModel, schemas.py:621-634
      let episode: String; let start: Int; let end: Int
      let kind: EvidenceKind; let hash: String
      var isSpan: Bool { kind.hasOffsets && start >= 0 && end > start }
  }
  enum EvidenceKind: String, Codable {        // forward-compatible, like Epistemic
      case user, assistant, page, reasoning, media, speaker, derived, unknown
  }
  let evidence: [Evidence]      // decodeIfPresent ?? []   (today dropped: CodingKeys :120-124)
  let sessionIds: [String]      // decodeIfPresent ?? []
  let origin: String?           // already on the wire (claims.py router :60), not decoded
  let recordedAt: String?
  let authorKind: String?       // "user" | "system" | "model" | "harness" | "unknown"
  let authorProvider: String?   // "anthropic" | "openai" | ... (server-derived)
  ```
- `speaker` covers a meeting utterance (R-N2 / R7 §4.3.5). It carries a `speaker` label, which the
  server resolves at read from the turn marker; the claim does not store it. `media` is R5 D4.
  `derived` exists **only on read payloads** and is never written into a claim (§4.9).

**Wire (`api/models/schemas.py`).**

- `ClaimModel` (`:637-668`) gains `session_ids`, `recorded_at`, `author_kind` and `author_provider`.
  The last two come from the existing `git_service._classify_author_kind` and
  `_provider_for_model` (`api/services/git_service.py:294-353`), so the app never duplicates the
  provider rule. `_claim_to_model` (`api/routers/claims.py:39-61`) fills them.
- `EntityHistoryEntry` (`:159-181`) gains `author_kind` and `author_provider` the same way.
- **Remote-write authors** (R-R5, `Cicada-Author: claude-web`) classify as `author_kind: "harness"`.
  The app renders them through `OriginMark(origin: author)`. R-L6 already added the rule that new
  *values* are allowed and new *shapes* are not.

**Offsets are Unicode scalar indices.** Python `str` indexes by code point. Every Swift slice uses
`unicodeScalars`, exactly as `ExcerptText.attributed` does (`Models/InboxPresentation.swift:52-60`),
and never `String.count` or UTF-16. A shared `ScalarSlice` helper holds this rule, and its tests
include an emoji, a combining accent, and a CJK line.

### 4.2 The evidence chip

`EvidenceChip` replaces `EpisodePill` in the `ClaimChip` footer (`Views/Common/ClaimChip.swift:34`)
and is used everywhere a claim is shown.

| `kind` | Label (`Copy.Evidence.*`) | Mark | Rule colour (the quote's left rule) |
|---|---|---|---|
| `user` | "You said" | `person.fill`, or the owner's avatar when `handle` is set | `CicadaTheme.info` (the same as `ObserverBadge` for you, `ClaimChip.swift:81-87`) |
| `assistant` | "<Harness> replied", e.g. "Claude Code replied"; "The agent replied" when the harness is unknown | `OriginMark(harness)` | `CicadaTheme.accent` (the observer colour for the agent) |
| `page` | "From the page" | the site `LogoImage` of the cited media entity | `CicadaTheme.mediaPink` (the external observer colour) |
| `media` | "In the video · 12:34" (the time is derived at read from the `[mm:ss]` marker, R5 §5.7) | `play.rectangle` | `mediaPink` |
| `speaker` | "<Name> said", or "Speaker 2 said (unconfirmed)" | `person.2` | `mediaPink` |
| `reasoning` | "Inferred" | `lightbulb` | `textTertiary` |
| `derived` | "Mentioned here" (dashed outline) | `text.magnifyingglass` | `textTertiary` |

- **Deliberate deviation from R9 §7.** The rule colours are observer tokens, not nature tokens.
  R9 suggested meadow/sky/bark by kind, but R-M2 says nature tokens are "never a data encoding",
  and speaker kind is categorical data. The dandelion wash on the *span itself* is emphasis, not
  encoding, so it stays. **The label is always the carrier of meaning;** the colour never carries
  it alone.
- **Chip text** is "<label> · <date>", where the date comes from the episode id
  (`ep_YYYY-MM-DD_nnn`). More than 3 chips on one claim fold into "+N more", which opens the
  entity's "Where this came from" section.
- **States on the chip:**
  - `stale`: a small "~" badge and the accessibility value "may have moved".
  - `grown`: no badge. The span is still exact (§4.8).
  - Legacy claims with no evidence render one `derived` chip per `sourceEpisodes` entry, capped
    at 3. Before this change, only the first episode was shown and it was inert
    (`ClaimChip.swift:34`, `:196-212`).

**Hover preview.**

- After a `hoverPreviewDelay` dwell, a `.popover(arrowEdge: .top)` opens. It is 360 pt wide.
- It closes `hoverPreviewGrace` after the pointer leaves, unless the pointer has moved into the
  popover.

```
+--------------------------------------------------------------+
| [CC] Claude Code replied  ·  Fix the sync race  ·  3 Sep     |
|      turn 14 of 42                                           |
|  |  ...so the passages were re-embedded every night, and     |
|  |  <<we moved the index to sqlite-vec so search is one      |
|  |  lookup>>. The old one stayed on disk until...            |
|                                         Open conversation  > |
+--------------------------------------------------------------+
```

- **Content:**
  - `QuoteBlock`: `before` in `textTertiary`; the span in `quoteFont` over a
    `dandelionFill.opacity(0.35)` wash; `after` in `textTertiary`.
  - The span is at most 240 characters with 240 characters of context. Both are enforced
    server-side (`evidence.py:49`, `episodes.py:29-30`).
- **Data:** `GET /episodes/{id}/span?start&end&context=240&hash=` (`api/routers/episodes.py:33-59`),
  fetched lazily and cached in memory, LRU with 256 entries keyed
  `(episode, start, end, hash)`. There is no ETag by design (R9 of G118).
- **States:**
  - Loading: static placeholder lines for up to 150 ms, with no shimmer.
  - `stale`: the text shows **without the wash**, under "This conversation changed after this was
    noted. The words may have moved."
  - `reasoning`: no quote. "Cicada inferred this. No sentence says it in so many words. Written by
    <author>." When `episode` is set, the hash was kept, so it adds "Open the conversation it came
    from".
  - `derived`: the mention is in **bold** (the inbox style), not washed, with the note "Found by
    name. Recorded before exact quotes."
  - 404: "This conversation is no longer in this bank."

### 4.3 Interaction specs (evidence)

| Trigger | Response | Duration constant | Reduce Motion | Text twin | Accessibility |
|---|---|---|---|---|---|
| Hover a chip for 0.35 s | the preview popover opens | `hoverPreviewDelay`; the system popover animation | the popover appears with no scale | the chip's label and date | none (hover-only surfaces are twinned below) |
| Keyboard focus on the chip + Space, or the VO action "Preview quote" | the same popover opens | same | same | same | `.accessibilityAction(named: "Preview quote")` |
| Click, or Return on a focused chip | the Reader opens at the span (§4.4) | `spanReveal` | static wash | the Reader header | the chip's label reads "You said, 3 September, in Fix the sync race. Opens the conversation." |
| A `media` chip | seeks the embedded player (`VideoRef.embedURL(at:)`, R5 §5.9) | none | same | "12:34" | label "Play from 12 minutes 34" |

### 4.4 The Reader (the conversation viewer)

**Presentation.**

- It is a **trailing `.inspector`** on `ContentView`'s detail column (macOS 14, verified in the
  SDK). Width is ideal `scaled(440)`, min `scaled(360)`, max `scaled(560)`.
- It sits beside whatever is open. The entity card overlay stays, so the belief and its sentence
  are visible together, which is the point of the feature.
- It is driven by `ProvenanceRouter`. Close it with the close button, Esc while it has focus, or
  the inspector toolbar toggle.

```
+---------------------------------------------- Reader ---------- ( x ) +
| [CC] Fix the sync race                                   [ Resume ]   |
| Claude Code · 3 Sep 2026 · 42 turns                                   |
| (i) Your words and each final reply. Tool calls and code aren't kept. |
|-----------------------------------------------------------------------|
|  < 2 of 5 cited here >                  [ Find in conversation... ]  |
|                                                                       |
|  You · turn 13                                                        |
|  can we stop rebuilding the whole thing every night?                  |
|                                                                       |
|  Claude Code · turn 14                                        14:31   |
|  Yes. The passages were re-embedded every night, so                   |
| |<<we moved the index to sqlite-vec so search is one lookup>>|.       |
|  The old one stayed on disk until the next cycle...                   |
|                                                                       |
|  You · turn 15                                                        |
|  ...                                                                  |
|-----------------------------------------------------------------------|
| NOTED FROM THIS CONVERSATION (5)                                      |
|  [logo] alpha-project uses sqlite-vec      Claude Code replied  <-    |
|  [logo] vector index is disposable         You said                   |
|  ...                                                                  |
+-----------------------------------------------------------------------+
```

**Header.**

- `OriginMark(harness)` 20 pt; the conversation title in `headingFont`; a meta line with the
  harness label, date and turn count.
- **Resume** appears only when the backend says `resumable`. It uses the existing
  `POST /conversations/{id}/resume` through `ConversationsViewModel.resume`; transcripts are only
  ever `isfile()`d (`Views/Sources/ConversationPopover.swift:44, 68-75`).
- **The capture-honesty line** appears only for hook-captured episodes (`capture_kind` present):
  "Your words and each final reply. Tool calls and code aren't kept." (G105, `transcript_extract.py:11-18`).
  For an import, the line reads "Imported from a <vendor> export".

**Body.**

- Turns come from the server's `turns[]` (§4.8), so the client runs no regex of its own.
- Each turn is a block: a speaker line (the "You" label, a harness mark with its label, or a
  "Speaker n" / name label), "turn n", and a `ts` time **only when the episode stores one**
  (R7 §5.1; the Wispr `turns[].ts`). **No time is ever inferred.**
- Text is `bodyFont`, selectable. The focused turn is `textPrimary`; other turns are
  `textSecondary`.
- **The cited span** gets a `dandelionFill.opacity(0.35)` wash plus a 2 pt `dandelion` leading bar
  in the margin. Other spans cited by the same entity get a 0.15 wash and no bar.
- The body is a `LazyVStack` of turns. A span that crosses turns is split per turn.
- Offsets are converted with `ScalarSlice` (§4.1).

**Landing.** `ScrollViewReader.scrollTo(turnIndex, anchor: .center)` runs after the first layout.
The wash fades in over `spanReveal`, then VoiceOver announces "Cited passage: <first 120 chars of
span>".

**The navigator.** "< 2 of 5 cited here >" steps through the spans in this document that the current
entity's claims cite. When the Reader was opened from the palette or the inbox, it steps through
every claim citing this document. Keys: Option Down and Option Up. Cmd [ goes back through the
router stack (for example from a claim's reader to the previous one).

**Find in conversation.** A `CicadaSearchField` that matches locally over the loaded text, with
Up/Down between hits.

**Noted from this conversation** (the reverse direction, G118 layer 4):

- A row per belief citing this document: the subject's `LogoImage`, the claim text and the
  `EvidenceChip`.
- Clicking a row jumps the body to that span. Option-click reveals the subject on the graph.
- Data: `GET /episodes/{id}/citations` (§4.8). When the FTS index is cold, the list is built from
  frontmatter `source_episodes` and shows entities only, under the caption "Showing pages from this
  conversation. Exact beliefs appear after the next index rebuild."

**States.**

| State | Shown |
|---|---|
| Loading | the header from the target's known fields, and a static placeholder body |
| 404 | "This conversation isn't in this bank any more." Resume is hidden. |
| `stale` span | the whole document with no wash, and a banner: "This conversation changed after this was noted. The words may have moved." |
| `grown` span | the normal wash, and a small caption: "The conversation continued after this was noted." |
| `reasoning` target | the document opens at its top, with the banner "Inferred. No exact sentence to show." |
| `derived` target | the mention is bold rather than washed, with the banner "Found by name. Recorded before exact quotes." |
| Truncated (over the server cap) | "Showing the first 400 KB of this conversation." |
| `page` document (a media entity's stored description) | the header shows the site logo and the entity name, "From the page"; no Resume, no turns |

**Accessibility.**

- Every turn is one element: "You, turn 13: <text>".
- `.accessibilityRotor("Cited passages")` lists the spans, and `.accessibilityRotor("Turns")` lists
  the turns.
- The navigator buttons are labelled "Next cited passage" and "Previous cited passage".
- Opening the Reader emits a `read` telemetry event `{entity_id: <subject when known>, surface: "span"}`
  (ids only).

### 4.5 "Where this came from" on the entity card

A new **section at the bottom of the Content tab** (`Views/Graph/EntityDetailCard.swift:306-400`),
after the metadata. It is always present and not hidden behind a tab: the owner asked for
contribution to be *easy* to see.

**Renamed section.** The G61 section "Sources" (`:680-700`) becomes **"Look it up at"**
(`Copy.lookItUpAt`). This ends the collision between "where to refresh this fact" and "where the
belief came from" (R6 §5.3.7).

```
WHERE THIS CAME FROM
From 3 conversations, 2 with Claude Code and 1 in ChatGPT.
Written by Claude (claude-sonnet-...) and you.

 [Claude] claude-sonnet-...  12 beliefs    [you] You  4    [worm] Cicada · maintenance 3

 [CC]  Fix the sync race                     3 Sep    5 beliefs   >
       | "...we moved the index to sqlite-vec so search is one lookup."
       | Claude Code replied
 [GPT] Planning notes                        12 Aug   2 beliefs   >
       | "...sqlite-vec or FAISS for the index..."   You said
 [Wispr] Weekly sync                         1 Sep    1 belief    >
       | "...let's keep the index disposable..."    Speaker 2 said (unconfirmed)

 Also: From the page (example.org) · 1 belief   ·   Inferred · 2 beliefs
 9 of 18 beliefs here have an exact quote.
```

**Contents.**

1. **The sentence.** `ProvenanceSummary.sentence(_:)` is a pure, tested function over the
   provenance payload.
   - Conversations are counted by harness, and harness labels come from `OriginIconography.label`.
   - Contributors are named by `ContributorIdentity.displayName`, with the model family first and
     the raw id in parentheses. Per the file's own rule (`ContributorIdentity.swift:24-35`), a raw
     id is its own honest name, so the id is never hidden.
   - With 0 conversations: "Recorded before Cicada kept conversation links."
2. **Contributor chips.** One chip per author:
   - `ContributorAvatar` (`Views/Contributors/ContributorsView.swift:283-303`) with its display
     name and count ("12 beliefs").
   - For harness authors (remote writes), `OriginMark` plus the harness label.
   - The count is the number of this entity's claims with that `authored_by`, plus commits from
     `/history` for that author that touched the page, and the chip's help text says so.
   - **No share bar here.** The Sources strip owns the one volume chart (R-A5 spirit: one number,
     one place).
3. **Conversation rows**, at most 5 and then "+N more".
   - Each shows the mark, title, date, belief count, and the best `QuoteBlock` with its kind label.
   - "Best" means an asserted span first, then derived; within those, the most recent.
   - The row opens the Reader at the best span.
4. **"Also" line:** page spans grouped by media entity, and the inferred count.
5. **The coverage line**, "N of M beliefs here have an exact quote". This states coverage honestly
   instead of implying every memory has a snippet (R8 §3.1: the live-bank ratio is unmeasured).

**Data.** One call, **new** `GET /entities/{id}/provenance` (§4.8). It replaces N+2 calls from the
card (claims, history, and one `/conversations/{id}` per session). Fetch it when the Content tab
appears, cache it per entity in the card's `@State`, and revalidate with the ETag.

### 4.6 The ClaimChip footer and the History tab

| Where | Today | v3 |
|---|---|---|
| `AuthorPill` (`ClaimChip.swift:175-194`) | raw model id as text | `ContributorAvatar` 14 pt plus the display name, using `authorKind`/`authorProvider` from the wire |
| `EpisodePill` (`:196-212`), inert | first source episode id, monospaced | `EvidenceChip`s (§4.2) |
| `TrustPill` labels (`Models/Claim.swift:81-89`) | "agent extracted" and similar | plain labels in `Copy`: "You told Cicada", "Cicada noticed", "Cicada concluded", "From a source". Trust stays orthogonal to confidence, and the ring is unchanged. |
| History author capsule (`EntityDetailCard.swift:1152-1163`) | text | `ContributorAvatar` plus the name |
| `FromConversationButton` popover (`ConversationPopover.swift:80-106`) | a row with Resume | the same, plus **"Open conversation"**, which opens the Reader with `.conversation(id)` (this resolves the "in place" deviation recorded at `:6-12`) |

### 4.7 Reuse: the inbox and Ask

- **Inbox cause** (`Views/Inbox/InboxCardView.swift:172-182`):
  - The cause line gains `OriginMark(cause.harness)`.
  - The excerpt pane gains **"Show in conversation"**, which opens the Reader with
    `.span(cause.episodeId, cause.start, cause.end, hash: nil)`. The Reader is labelled `derived` or
    `asserted` from `cause.spanKind` (`Models/InboxItem.swift:130-147`), and the absolute offsets
    already exist for exactly this (`schemas.py:956-990` docstring).
  - The excerpt text moves to `quoteFont`.
- **Ask:** see §3.5.

### 4.8 Server additions (Track P; all engine-free, no LLM, bank text only)

1. **`GET /episodes/{id}/text`** returns the whole evidence text for the Reader:
   ```json
   {"episode":"ep_2026-09-03_004","kind":"episode","text":"...","length":41234,"hash":"a1b2c3d4e5f6",
    "title":"...","timestamp":"...","harness":"claude-code","origin":"claude-code",
    "conversationId":"...","captureKind":"stop-hook",
    "turns":[{"index":1,"start":0,"end":58,"role":"user"},
             {"index":2,"start":59,"end":900,"role":"assistant"},
             {"index":3,"start":901,"end":1320,"role":"speaker","speaker":"Speaker 2","ts":"00:23:41"}],
    "focus":{"start":930,"end":951,"derived":true},
    "truncated":false}
   ```
   - It uses the same resolver as `/span` (`evidence.source_text`, `evidence.py:94-105`): `ep_*`
     resolves under `episodes/` and anything else under `entities/`, where `kind` is `page`.
   - **Cap: 400 KB**, with `truncated` set when exceeded. Episodes from the Stop hook are already
     capped at 100,000 characters (`SESSION_CAP_CHARS`, `transcript_extract.py:44-46`). Imports can
     be larger.
   - `turns` is computed by the **same** marker regex as `speaker_kind` (`evidence.py:64`),
     extended with the `speaker:` family from Track N. There is one parser, server-side.
   - `ts` is included only from a stored `turns[].ts` sidecar.
   - `?focus=<entityId>` adds a **derived** span with `inbox_context.locate_mention`
     (`api/services/inbox_context.py:73-91`). It is computed at read and never stored.
   - ETag from `sync_service.etag_for(memory_path, "episodes")` (`"entities"` for a page), with
     `If-None-Match` honoured. **It is not a Store domain**: the Reader fetches on demand and caches
     in memory only. So the ETag/`VersionVector` ship-together rule has no client mapping to add. If
     the payload ever joins `SnapshotCache`, the mapping must ship with it.
2. **`/episodes/{id}/span` gains `grown`, with prefix verification.** This is an amendment (§5, A7).
   - Today `stale` compares the caller's hash against the hash of the *whole* current text
     (`episodes.py:48-57`, `evidence.py:218`).
   - But a Stop-hook episode is **rewritten in place, with appended turns**, on every later turn of
     the same session (`api/services/transcript_capture.py:273-289`). The session cap is
     deliberately head-stable so "offsets do not move between two hook firings"
     (`transcript_extract.py:43-46`).
   - So every span in a conversation that continued after Sleep reads as `stale`, even though its
     offsets are exact.
   - The fix: when the whole-text hash mismatches, try each **turn-boundary prefix**
     `text[:b]`, for each `b` = the offset just before a turn marker line with `b >= end`, plus
     `len(text)`. If `body_hash(text[:b]) == hash`, then `stale = false, grown = true`.
   - This is exact: a 48-bit hash over a string that was once the whole body. It is bounded by the
     turn count, which is about 200 hashes over at most 100 KB, roughly 10 ms. It needs no schema
     change and works for every legacy evidence entry.
   - It does not apply to `page` documents, where descriptions are rewritten rather than appended.
3. **`GET /episodes/{id}/citations`** returns
   `{"citations":[{"claimId","subjectId","subjectName","text","evidence":{...},"stale":bool}], "partial":bool}`,
   served from the FTS claims table (§3.9). When the index is cold, it scans `source_episodes`
   through `bank_index` and returns `partial: true`.
4. **`GET /entities/{id}/provenance`**:
   ```json
   {"entityId":"alpha-project",
    "contributors":[{"author":"claude-sonnet-...","kind":"model","provider":"anthropic","claims":12,"commits":3},
                    {"author":"user","kind":"user","claims":4,"commits":2}],
    "conversations":[{"conversationId":"...","episodeId":"ep_...","title":"...","harness":"claude-code",
                      "timestamp":"...","claimCount":5,
                      "best":{"start":930,"end":1012,"hash":"...","kind":"assistant","excerpt":"...",
                              "mentionOffsets":[[12,40]],"stale":false,"grown":true,"derived":false}}],
    "pages":[{"entityId":"media-example-org","claimCount":1}],
    "inferredCount":2,
    "totals":{"claims":18,"withSpan":9,"conversations":3}}
   ```
   - Built from the page's claims (`claims.parse_claims`), `all_session_ids()`
     (`api/services/claims.py:151-180`), frontmatter `source_episodes`, and
     `inbox_context.excerpt_around` for the ±240-character excerpt (`inbox_context.py:94+`).
   - Conversation metadata comes from `session_stats`, the same projection as
     `GET /conversations/{id}`.
   - **Budget:** under 150 ms warm for an entity with 50 claims across 20 episodes. Test it on the
     demo bank. The G97 inbox precedent is 100 ms.
   - ETag over `entities` + `episodes`.
5. **`/ask` citations gain `evidence` and `claimId`** when the retrieval hit was a claim. The
   retrieval is claim-first (`ask_service.build_claim_first_retrieve_fn`), so the spans are already
   in hand. This is additive, and `AskCitation` decodes it with `decodeIfPresent`.
6. **`ClaimModel` and `EntityHistoryEntry` author fields** (§4.1).

### 4.9 Honesty rules the viewer enforces

- **Spans, not copies.** Nothing is quoted into a claim or cached on disk by the app. The Reader and
  the preview fetch text from the bank on demand.
- **Never fuzzy.** Only `locate` (exact, then whitespace-normalised, then case-insensitive) mints an
  asserted span. A **derived** span (`locate_mention` by name) is always labelled "Mentioned here",
  is never styled as "You said", and is never written back. This is G100's class, and it exists on
  read payloads only.
- **Stale never highlights.** Grown is exact, so it highlights.
- **Captured, not complete.** A hook episode holds your turns and each final reply only. The Reader
  says so in its header, and never implies it shows the whole session.
- **Meeting speakers are never "you"** unless the owner confirmed which speaker they are (R-N2).
  Unconfirmed speakers read "Speaker n said (unconfirmed)".
- **Conversation model is reserved-null** (`schemas.py:362-366`). No surface claims which model
  spoke inside a conversation. "Written by" always comes from `authored_by` and `Cicada-Author`,
  never from the conversation.
- **Transcripts under `~/.claude` are never read.** Everything shown comes from bank episodes.

### 4.10 Tests (provenance)

- `EvidenceDecodeTests`:
  - A payload without `evidence` decodes to `[]`.
  - An unknown `kind` decodes to `.unknown` and renders like `reasoning`.
  - A `reasoning` entry never reports `isSpan`.
- `ScalarSliceTests`: emoji, a combining accent and CJK text all slice identically to Python
  (fixture pairs generated once from the backend's `text[start:end]`).
- `EvidenceChipLabelTests`: every kind maps to a `Copy` label; `derived` never produces "You said";
  `assistant` with an unknown harness gives "The agent replied".
- `ProvenanceSummaryTests`: the sentence covers 0, 1 and many conversations, mixed harnesses,
  harness authors, and legacy-only entities.
- `ReaderTurnsTests`: a span crossing a turn boundary is split into two washes; `ts` is shown only
  when present.
- Backend:
  - `/episodes/{id}/text` refuses a non-bare id (reusing the `source_path` rail) and respects the
    cap.
  - `turns` agree with `speaker_kind` at every turn start.
  - **The grown test:** capture an episode, mint a span, append a turn through `transcript_capture`,
    and assert `stale == false` and `grown == true`. Then edit a byte before the span and assert
    `stale == true`.
  - `/entities/{id}/provenance` counts match the claims, with a budget test on the demo bank.
  - `focus` derived spans are never persisted (`git status` is clean after the call).

---

## 5. Rulings: kept, newly enforced, amended

| # | Ruling (source) | Decision | Why |
|---|---|---|---|
| K1 | Settings is a `NavigationSplitView` over `SettingsSection`; raw values are machine keys; tolerant restore (`SettingsSection.swift:7-53`, `SettingsSectionTests`) | **kept** | The five existing raw values are unchanged, and new cases are additive. |
| K2 | P5: `SettingsSectionLink` is the one entry point and the one writer of the seed (`SettingsSectionLink.swift:17-26`, `SleepQueueCardV3Tests.swift:140-147`) | **kept, extended** | The row-focus key is written in the same file and carries a nonce, so there is never a second writer. |
| K3 | No private Settings selector (`SettingsEntryPointTests.swift:30-41`) | **kept** | unchanged |
| K4 | No prices or token counts in the app (CLAUDE.md, 2026-09-03) | **kept and newly enforced** | `priceLine`'s `$` (`Connection.swift:115-124`) and the cost-estimate tier picker (`ConnectionsView.swift:160-173`) are removed. Plans & keys drops the `creditcard` glyph. |
| K5 | Ruling 4: scheduled cycles never spend plan quota, and the UI says so (TODO ruling 4; `EngineCard.swift:180-188`) | **kept** | The What runs block always shows both lines. The caption is never hidden when they differ. |
| K6 | G126: standing connection goes in Integrations; one-shot import goes behind the Feed's + | **kept** | Voice & meetings and Folders are standing, so they go in Integrations. Export and import of a *bank* go in Privacy & data. |
| K7 | Spans not copies; never fuzzy; unlocatable becomes `reasoning`; stale never mis-highlights (G118, `evidence.py:17-26`) | **kept** | §4.9 |
| K8 | Transcripts never read; conversation `model` reserved-null | **kept** | §4.9 |
| K9 | Telemetry is ids and enums only | **kept** | The query is never logged (§3.8). `read` events use `surface: palette\|span`. |
| K10 | ETag ship-together (CLAUDE.md API) | **kept** | The new payloads are fetched on demand, not Store domains (§4.8.1). Any future Store domain ships its `VersionVector` mapping in the same commit. |
| K11 | G123: every navigation from outside the canvas lands on the node (`GraphViewModel.swift:428-437`) | **kept** | Palette entity rows go through `revealEntity`. |
| K12 | Liquid Glass only in chrome; content never glass (R-M5, R9 §2.7) | **kept** | The palette container is glass. Rows, the Reader, Settings cards and chips are not. |
| K13 | Nature tokens never encode data (R-M2) | **kept, with a deviation from R9 §7** | The evidence rule uses observer colours, not meadow/sky/bark (§4.2). The dandelion wash is emphasis only. |
| K14 | Copy rules: pointers exact, subtitles <= 60 characters (`Copy.swift:6-11`) | **kept** | New pointers are built from their parts. |
| A1 | R-R7: "Settings > Agents gains From anywhere" | **amended: own sidebar row** | A `SettingsSection` can be deep-linked and indexed for search, and the page has five blocks. A segment inside Agents could do neither. |
| A2 | R5 §5.1: recommended skills live first as a section on Settings > Agents | **amended: own "Skills" row** | The owner's reference IA puts Skills in its own group. G72 and G112 later add tabs to the same page, so the placement does not move twice. |
| A3 | G122: the Engine picker and the Claude card's "Use for Sleep" toggle coexist on two pages (`SettingsSleepView.swift:19-24`) | **amended: Engines owns engine choice** | One page answers "who thinks for Cicada". The toggle moves unchanged (same pref, same endpoint) to Engines > Auto. Plans & keys becomes credentials only. **2026-09-23 (Track O final review) — label and placement amended:** `engine_select.resolve_llm_mode` reads `use_for_sleep` only when the configured mode is `byok`; under `auto` the Claude plan is the first rung whether the pref is on or off. "Auto may use my Claude plan" was therefore a switch that did nothing under Auto and, with API key chosen, quietly moved cycles you start onto the plan. The switch keeps its pref and endpoint and stays on Engines, but shows only while the API key card is chosen (`mode == "byok"`, which is also the no-choice default), under an "API key" heading, labelled "Use my Claude plan when I start a cycle"; flipping it reloads the chooser so "What runs" never names the old engine. `engine_select` is unchanged. |
| A4 | Spec decision 7: Cmd K becomes Find with Ask as a mode | **applied** | The shipped Cmd-K Ask (G52) survives as a mode reached with one keystroke (Cmd Return), and its history is kept. |
| A5 | `EmptyStateView.swift:8-14`: never an `openSettings()` closure | **conditional amendment (spike S0)** | The measured failure was the private selector. `OpenSettingsAction` is public macOS 14 API. If S0 verifies it on 14, 15 and 26, allow it **only** inside `SettingsSectionLink.swift`. Otherwise keep the rule, and Settings results in the palette open on click only. **2026-09-23 (Track O, static half):** the 26.1 SDK declares `OpenSettingsAction` and `EnvironmentValues.openSettings` `@available(macOS 14.0, *)`; `OpenSettingsInterfaceTests` compiles a probe at the macOS 14 target. Runtime half: pending the orchestrator's scratch-app spike (this Mac runs macOS 26 only; 14 and 15 not verified). No source calls it yet. |
| A6 | Cmd K and Cmd F as hidden zero-size buttons (`ContentView.swift:98-104`, `:594-599`) | **replaced by menu commands** | Fixes Cmd F firing on the invisible graph field (R6 §4.1), and makes both shortcuts discoverable and reachable through AX. |
| A7 | G118 R2: `stale` = the whole-text hash differs | **amended: stale = no turn-boundary prefix matches; add `grown`** | G105 rewrites the episode in place with appended turns, and R6 (`transcript_extract.py:43-46`) is head-stable precisely so offsets survive. Whole-text hashing marks every continued conversation stale, which defeats both. The change is exact and needs no schema change. |
| A8 | `EVIDENCE_KINDS` is closed at 4 (`api/services/claims.py:55-58`) | **amended by other tracks; the viewer is ready** | `media` (R5 D4) and `speaker` (R-N2) are stored kinds. `derived` stays read-only, exactly as that comment anticipated ("a fifth value rather than a flag"). |
| A9 | `EpisodePill` is inert "for now" (`ClaimChip.swift:196-197`) | **resolved** | `EvidenceChip`. |
| A10 | G48 §4 deviation: the conversation is shown in a popover "in place" (`ConversationPopover.swift:6-12`) | **resolved** | The popover gains "Open conversation"; the Reader is the destination. |
| A11 | The Ask panel is a `.sheet` (`AskPanel.swift:53-54`) | **replaced** | A glass overlay palette. `AskViewModel` is unchanged. |

---

## 6. Slices an engineer can plan from

Every slice is its own PR to `dev`, and each lists what it depends on.

**Track O: Settings v3 + skills**

| Slice | Content | Depends on |
|---|---|---|
| O0 | Spike S0: `openSettings()` from the main window and from an overlay, on 14/15/26. Record the result in this doc's A5. | none |
| O1 | `SettingsGroup`, the new `SettingsSection` cases, sidebar groups and `.searchable(.sidebar)`, `SettingsRow`/`GroupCard`/`DetailHeader`, `PillPicker`. General, Sleep and Plans & keys re-laid out (price and tier removed, marks fixed). Tests from §2.6. | M1 tokens |
| O2 | `SettingsIndex` (static + dynamic), sidebar filtering, the results page, `SettingsRowAnchor` highlight, and the row nonce in `SettingsSectionLink` | O1 |
| O3 | The Engines page and `EngineChooser` (moved from Sleep and onboarding step 2), the Auto toggle move, and the `codex` model field | O1, Track E (the `codex` candidate) |
| O4 | You, Privacy & data (banks over existing endpoints), Memory (maintenance endpoints), Advanced | O1; the `StatusResponse` fields `telemetry`, `gates`, `envOverrides`; `GET /banks/{n}/export`; `DELETE /banks/{n}` (owner decision) |
| O5 | The Skills page, the consent sheet and `SkillInstaller` | O1, `GET /skills/recommended` (R5 §5.9) |
| O6 | The From anywhere page | O1, Track R S1/S2 |

**Track S: search everywhere**

| Slice | Content | Depends on |
|---|---|---|
| S1 | Backend `/search`: threadpool, `kinds`, the `bank_index` fallback, `totals`, span fields; `/conversations/recent?q=` | none |
| S2 | The FTS5 derived index plus `mode=prefix`; passage offsets | S1 |
| S3 | `QuickMatch`, `QuickIndex` (local tier), and the palette overlay in Find mode with the local groups. Menu commands for Cmd K and Cmd F (A6). | M1 (`liquidGlass`) |
| S4 | The server tier in the palette (the merge rule), the Conversations and Beliefs groups, and Ask mode folded in (§3.5 items 1-2) | S1, S3 |
| S5 | `CicadaSearchField` on Graph, Clusters, Feed, Harness conversations and Inbox (§3.7) | S3 |
| S6 | `GraphNode.aliases` (after the payload measurement) | S2 |

**Track P: provenance**

| Slice | Content | Depends on |
|---|---|---|
| P1 | Swift `Evidence`, `Claim` fields, `ScalarSlice`; `ClaimModel` author fields; `EvidenceChip` with the hover preview over the existing `/span` | M1 (`quoteFont`, `dandelionFill`) |
| P2 | `/span` `grown` (A7); `GET /episodes/{id}/text`; `ProvenanceRouter`; the `ReaderInspector` without the citations list | P1 |
| P3 | `GET /entities/{id}/provenance`; "Where this came from"; the "Look it up at" rename; `ContributorAvatar` in ClaimChip and History; plain trust labels | P1 |
| P4 | `GET /episodes/{id}/citations` (the FTS path plus the cold fallback); the Reader's "Noted from this conversation" and navigator | P2, S2 |
| P5 | The inbox "Show in conversation" plus the harness mark; Ask `sourceEpisodes` chips; `/ask` `evidence` | P2 |
| P6 | Palette conversation and belief rows open the Reader | P2, S4 |

**Live verification (the working-method rule).** Run each track on the **demo bank** with
`macos-harness`: `mac.ax.query` / `AXPress` on the Settings sidebar rows and results list,
`accessibilityIdentifier("settings.row.*")` lookups, and Cmd K through the menu item.

---

## 7. Owner decisions and things not verified

1. **S0 result.** Is `openSettings()` allowed inside `SettingsSectionLink.swift` (A5)? Without it,
   Return on a Settings row in the palette only shows a hint.
   **2026-09-23 (Track O, static half):** the 26.1 SDK declares `OpenSettingsAction` and `EnvironmentValues.openSettings` `@available(macOS 14.0, *)`; `OpenSettingsInterfaceTests` compiles a probe at the macOS 14 target. Runtime half: pending the orchestrator's scratch-app spike (this Mac runs macOS 26 only; 14 and 15 not verified). No source calls it yet.
2. **Bank delete semantics.** Move to `<root>/.trash/` (recommended, reversible) or erase. Git
   history makes "forget a single memory" a separate problem (G95's redaction story). v3 does not
   offer it.
3. **The plan-window percentage on the Engines Claude card** (R1 §5.2). Hidden by default. It is
   neither a price nor a token count, but it sits next to the 2026-09-03 ruling.
4. **The group names** "Cicada / Customize / Engines & keys". "Customize" is the owner's reference
   word. "Engines & keys" replaces "Platform", which reads as a vendor term in a local app. Both are
   `Copy`, so a rename is a one-line change.
5. **Evidence colours** are observer tokens rather than nature tokens (K13). This is reversible if
   the owner rules that nature tokens may encode speaker kind.

**Not verified (check before building):**

- The `.searchable(placement: .sidebar)` look inside a `Settings` scene on macOS 26 (the API exists,
  but it has not been screenshotted).
- `.inspector` beside the graph's WKWebView and the G109 p95 frame budget.
- Whether a hover-opened `.popover` steals key focus from the entity card on macOS 14.
- The `/graph` payload growth from aliases.
- The live-bank share of claims with evidence. The coverage line reports it rather than assuming
  it.
