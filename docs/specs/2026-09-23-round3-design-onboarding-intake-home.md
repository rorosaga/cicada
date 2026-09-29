# Track I, final: onboarding, one intake, and the front door (G108)

Judge's synthesis for the round-3 design panel, 2026-09-23. It scores the two entries,
`onboarding-guided.md` (six steps in a sheet) and `onboarding-found.md` (one "found on this Mac"
screen that continues on a Home page), and then settles three things:

- the final onboarding flow, screen by screen;
- the final import flow;
- G108, the front door, with a recommendation.

It ends with an ordered task outline for a Workflow track.

**Where citations point.**
- Every `file:line` is against `dev` @ `f2d31ef`, re-opened for this document.
- App paths are relative to `app/CicadaApp/Sources/CicadaApp/` unless they start with `api/`,
  `app/`, `docs/` or `install.sh`.

**Privacy.** Nothing under `memory/`, `~/.cicada` or `~/.claude/projects` was read. The owner
appears as the placeholder "Ada". Any title in a wireframe is a placeholder too.

---

## 0. The verdict in one screen

1. **"Found" wins the shape; "guided" wins the plumbing.**
   - The final onboarding is one full-window **Welcome** that shows what Cicada found on this Mac,
     with one button, **Start remembering**. It then continues as a **Getting started** card on a
     new **Home** page. That is Found's shape.
   - The intake backend is Guided's: one pipeline, a sniff that stages nothing, a multi-member zip
     with named skips, and a background job counter.
   - So are the honesty functions (`ScheduleHonesty`), the export reminders with their text twins,
     the sign-in flows, and the read-only agent-wiring probe.
2. **A person with a Claude plan reaches a real first read in 2 clicks: Start, then Read now.**
   Guided needs about 9 clicks for the same result, Found's own flow about 3.
3. **The visible checklist is the consent.**
   - Pre-ticked items are only those that meet all three conditions:
     - the person's own intentional act (their agent sessions *from now on*, bookmarks they saved);
     - no new macOS permission prompt;
     - nothing that opens another app.
   - A line under Start says exactly what Start will do. For example: "Connects 2 apps and brings
     in 2,104 bookmarks."
4. **The engine choice stays visible and never blocks.**
   - G117's 2026-09-04 ruling ("the range is the point … each option states its cost model before
     it is chosen") is kept literally. The four engine cards, each with its cost-model line, sit on
     the Welcome.
   - Start does not wait on the engine, because capture needs no engine (G105). The choice is
     forced only at the first read.
5. **One intake everywhere.** One `IntakeRouter` handles every way a file arrives:
   - a drop on the window, the Dock icon, the menu-bar worm, the Sleep-room worm (Track Z), an
     empty state, or the Home field;
   - File → Import… (⌘⇧I).
   
   Every path goes sniff → preview → import → a "what happens next" card that never closes on its
   own. `UploadOverlay` and the Feed's Upload button retire.
6. **G108: build Home, and make it ⌘1.**
   - Home is search-first: "What would you like / *to remember?*".
   - Below the field it shows Getting started (until done), then Today, Needs you and Last read.
     Each number appears once, and each links to the page that owns it.
   - Graph moves to ⌘2. Relaunch still restores the last tab, so nobody who lives in the graph is
     moved.
   - (b) navigation: rule **historical**, but build it with G106, not here.
7. **Two verified defects ship first, before any new UI.**
   - (a) `BrowserWatcher.catchUp` imports Chrome and Safari bookmarks at first launch, before any
     consent, and can race the first-run gate. See §2, F1.
   - (b) An import hand-off in today's sheet calls `finish()`, which skips the first Sleep. See §2,
     F2.

---

## 1. Scorecard

Each criterion is scored 1–5, where 5 is best. The totals are a tie-breaker, not the argument; the
reasons in each row are.

| Criterion | Guided | Found | Why |
|---|---|---|---|
| **Seamless for a non-technical person** | 3 | **5** | Guided asks the person to understand "engine" and "Recall/Auto-save" before they have seen any value. Found detects and pre-fills everything the Mac can answer (`NSFullUserName()`, bundle ids, CLI logins, hook state) and asks one question. |
| **Honesty** | **5** | 4 | Guided pre-ticks nothing, states a negative next to every capability, and tests the ruling-4 invariant. Found pre-ticks items, weakens the G117 engine ruling to a "Choose…" behind a click, and plans for the **backend** to write into `~/.claude`. But Found alone caught the real consent defect (F1). The synthesis keeps Found's defaults, restores the visible engine range, and moves every harness write to the app (§4.1.6). |
| **Fewest hand steps** | 2 | **5** | To reach the first read with a connected Claude plan, Guided takes Get started, Continue, Continue, Connect, Confirm, Continue, Skip, Read now and Open (about 9 clicks). Found takes Start, Read now and Open graph (3). |
| **Fit with Meadow** | 4 | 4 | Found's full-window landing page *is* the owner's reference (sky, serif headline with an italic line, green pill), where Guided is a sheet. But Found stands the pixel worm on painted grass, which breaks R9 §5.3 ("pixel art must not mix into the same frame" as paint), and shows the queue count twice on Home. Both are corrected here. |
| **Feasibility** | **4** | 3 | Guided reuses the sheet shell. Found adds a full-window overlay, a morph into Home, a whole new page, and a backend endpoint that writes harness config. The synthesis cuts the risky parts: the morph falls back to a crossfade, and nothing writes harness config from the backend. |
| **Total** | 18 | **21** | |

**Taken from Found:**
- the one-screen Welcome with detection and checklist-as-consent;
- the full-window landing page;
- deferring each choice to the moment it is used;
- the `BrowserWatch` consent fix;
- Home as the front door, and the retired Upload button;
- ⌘⇧I;
- the Claude Code "from now on" honesty line;
- `FoundPolicy`;
- the empty states as drop targets.

**Taken from Guided:**
- the `/intake/*` contract, including `episode_staging.plan()`, the multi-member zip with
  `ignored[]`, the shims and the job counter;
- the preview with **Import into**;
- `ScheduleHonesty` and its ruling-4 test;
- `ExportWait` reminders with no-permission twins;
- the engine-card mapping and in-card sign-in;
- `GET /agents/wiring`, a read-only probe;
- `MarkHover`;
- the stated-negative copy;
- the rule that a success card never auto-closes;
- `MeadowPill`;
- the welcome subline;
- the data-sources discipline.

**Rejected, with the reason for each:**

| Idea | From | Why rejected |
|---|---|---|
| Six-step sheet | Guided | Too many hand steps |
| Schedule choice before the first read | Guided | Asks before the person has seen what a read is. It moves to after the first read. |
| From anywhere inside first run | Guided | Spec decision 4 keeps it off by default, and it is not a first-minute job. It becomes one Home suggestion after the first read. |
| `POST /agents/{id}/enable` writing harness config | Found | A bearer-authenticated HTTP endpoint that installs a command running on every agent turn widens the backend's blast radius. R5 §5.3 already proposes "the backend never writes into harness roots". |
| The "Teach Claude when to recall" skill copy on the Welcome | Found | It writes `~/.claude/skills`, which is G72's rail, and R5's D2 is still undecided |
| A one-entry `NavigationHistory` | Found | G108(b) is built with G106, so a half-model is not started here |
| A fixed 24 h reminder | Found | Guided's time menu is kinder |
| The worm on the grass, and the queue count shown twice | Found | See the Fit row of the scorecard |

---

## 2. Facts this synthesis rests on (verified, re-opened)

| # | Fact | Evidence |
|---|---|---|
| F1 | **Consent defect.** At launch, `browserWatcher.start(store:)` runs one line after `backend.start()` (`CicadaApp.swift:135-138`). `start` runs `catchUp()` (`Services/BrowserWatch.swift:207-213`). `catchUp` syncs any channel whose `lastSynced` is nil, because `shouldSync(current:, lastSynced: nil) == true` (`:100-104`, `:225-232`). The sync ends in `bookmark_sync.sync_bookmarks`, which writes media entities through `ingest_batch` (`api/services/bookmark_sync.py:312-330`). The same `shouldSync` also gates the file-change path (`BrowserWatch.swift:299-306`). The signature key is machine-global: `cicada.browserWatch.<channel>` (`:340-351`). | code |
| F1b | **The gate race that follows.** The gate needs `graphIsEmpty` (`Support/FirstRunGate.swift:38-45`, `ContentView.swift:147-157`). A bookmark import that lands before the first graph snapshot means the gate never opens. This is inferred from the code order and was not reproduced live. | code, §14 |
| F2 | **Hand-off ends onboarding.** `IntegrationsView(onHandOff: finish)` (`Views/Onboarding/FirstRunSheet.swift:77`) marks the bank onboarded (`:184-187`) before the Sleep step. | code |
| F3 | Two chat-import pipelines. `/conversations/upload` (`api/routers/conversations.py:31`) never stamps `origin` and rejects zips. `/banks/{name}/import` (`api/routers/banks.py:197-229`) goes through `parse_export_bytes` (`conversations.py:650`) and returns `date_range` plus created/updated/skipped. `_parse_zip` reads one member (`:697`). `_stage_episodes` (`:746`) holds the G20 delta. | code; R7 §1.2 |
| F4 | `UploadOverlay` has three modes (`Views/Common/UploadOverlay.swift:27-31`) and auto-closes 1.5 s after success (`:441-446`). It is the only writer of `store.intakeInFlight` (`Sync/Store.swift:90`), and that flag is a **Bool**, so two parallel intakes would clear each other's flag. | code |
| F5 | The Feed opts back into Upload, and only for the two reasons stated at `Views/Feed/FeedView.swift:64-82`: project import, and the `intakeInFlight` writer. | code |
| F6 | The engine candidates are in `api/services/sleep_engine_prefs.py:104-136`. `byok` is always `available: True, connected: True` **even with no key**, so "has a key" must come from `Store.connections` (`Sync/Store.swift:36`). `codex` is permanently disabled, and its detail says "(G49)", which is internal jargon and must not reach a non-technical screen. | code |
| F7 | The Claude sign-in is `LoginHint(mode="terminal", command="claude auth login")`, and the install hint says `npm i -g …` (`api/services/connections/claude_cli.py:20-21, 45`). A general-public user cannot run that. | code |
| F8 | The hook command is `"<venv python>" "<repo>/api/hooks/capture.py" --harness <h>` (`install.sh:55`), installed through `registry.py install` (`install.sh:312, 318`). `registry.status` returns `present`, `absent` or `stale`, and returns `absent` for an unparseable file (`api/hooks/registry.py:145-155`). The CLI exits 3 on a `RegistryError` (`:186-188`). | code |
| F9 | The MCP commands are built app-side as **shell strings** in `AgentSetupCatalog.all(home:memoryRoot:)` (`Views/Connect/ConnectView.swift:46`, `:82`, `:129`). The Cursor deep link is at `:70`, and the skill copy at `:87`. | code |
| F10 | There is no `NSApplicationDelegateAdaptor`, and the app Info.plist has no `CFBundleDocumentTypes` (`app/CicadaApp/bundle.sh:68-84`). A drop on the Dock icon therefore needs **both**. `LSMinimumSystemVersion` is still 13.0 (`:79`); R-M7 fixes that. | code |
| F11 | Nothing uses `UserNotifications` or `NSFullUserName`. | grep |
| F12 | `AppTab` has six cases. The ⌘ slot is derived from `allCases` order (`Views/Sidebar/SidebarView.swift:13-32, 127-128`). The default and restore are at `ContentView.swift:5-9, 76`. The graph stays mounted under other tabs (`:191-202`). | code |
| F13 | Home's data exists today: `store.visibleInbox` (`Store.swift:55`), `store.sourcesOverview` with `activity` (`Models/SourceOverview.swift:37`, UTC key `ActivityWindow.key`, `Views/Sleep/MemorySourcesCard.swift:29`), `sleepVM.history` (`ViewModels/SleepViewModel.swift:26`, loaded by `loadHistory()` at `:265`, **not** cached on disk), `SleepDebtInfo.hasRunBefore` (`Services/APIClient.swift:630-651`), and `deriveBookwormState` (`MenuBar/BookwormState.swift:153`). | code |

---

## 3. Principles (short, binding for this track)

1. **Detect, don't ask.**
2. **What you see is what Start does.** Nothing unseen runs, and nothing runs before Start.
3. **One button per screen.**
4. **Defer each choice to its moment:**
   - the engine, at the first read;
   - the schedule, after the first read;
   - the remote connector, after the first read, as a suggestion.
5. **Every "when will it be read" sentence is a tested pure function** of schedule × engine
   preview. Ruling 4 is shown, never promised away.
6. **Nothing ends early, and nothing closes on its own** when it carries "what happens next".
7. **Paint at the edges only.** Paint goes on the Welcome and the Home header band only, never
   behind a number, and never in the same frame as the pixel worm.
8. **One component, many hosts:**
   - `IntakePanel`;
   - `EngineChooser` (Track O's name; §4.1.5);
   - `FoundRow`;
   - `ConnectionLoginFlow`.

   Each is embedded in onboarding and in its Settings, Feed or Home host, and never forked.

---

## 4. The final onboarding flow

```
 gate (unchanged: known, un-onboarded, loaded-and-empty bank)
   │
   ▼
 ┌──────────────────────────── WELCOME (full window) ────────────────────────────┐
 │ Hello, Ada. / Here's what Cicada found on this Mac.                           │
 │ checklist: AI apps · browsers · (notes & voice) · chat history · who reads     │
 │                        ( Start remembering )                                  │
 │                 Try the demo instead · Set up later                           │
 └───────────────────────────────┬───────────────────────────────────────────────┘
      Start: owner PUT ──▶ crossfade/morph ──▶ HOME (⌘1)
                                              └ Getting started card (continuation):
                                                  per-row live states → Read what came in
                                                  → first read (worm reads) → "Keep reading
                                                  on its own?" (honest schedule) → done
```

There are two surfaces, not steps: the Welcome, then Home's Getting started card. Getting started
also appears after "Set up later", with every found item unticked, so skipping loses nothing.

### 4.1 Screen 1: Welcome

#### 4.1.1 Surface

- **A full-window page, not a sheet.**
  - `ContentView`'s root becomes `ZStack { NavigationSplitView …; if showFirstRun { WelcomeView } }`.
    That replaces `.sheet(isPresented: $showFirstRun)` (`ContentView.swift:92-94`).
  - The split view underneath is already on `.home`, so the transition to Home reveals it rather
    than building it.
  - `evaluateFirstRun()` (`:147-157`), `FirstRunGate`, `router.pendingFirstRun` (`:118-122`) and
    `AppRouter.requestFirstRun()` (`Support/AppRouter.swift:74`) are **unchanged**.
- **Layout, top to bottom:**
  1. The **sky band**, about 36 % of the window height and at least `scaled(240)`.
  2. The **checklist card**, at most `scaled(680)` wide on `background`. It scrolls inside itself.
  3. The **pinned footer cluster**: the worm, the Start pill and the secondary links. It never sits
     inside the scroll view (the G130 lesson at `FirstRunSheet.swift:53-59`).

  The window keeps its existing minimum size. At `uiScale` 1.4 the card scrolls and the footer
  stays pinned, which is tested.
- **The sky band:**
  - a procedural `CicadaTheme.sky(.day)` in light mode, or `.night` in dark mode. It is chosen by
    theme mode, never by the clock (R9 §5.1, R-M2);
  - two cloud sprites, each confined to the outer 25 % of the width;
  - a static grass-and-dandelion strip `meadow-edge(-dark).png` along the band's **bottom edge**.
  - The headline sits on the gradient, never on paint. Measured contrast is 11.2:1 in day and at
    least 13:1 in night (R9 §5.1).
- **The worm** is 48 pt (whole cells, G107). It sits **in the footer cluster on plain
  `background`, never on the grass**, which keeps pixel and paint apart (R9 §5.3). It is `.awake`
  while idle and `.reading` while `store.intakeInFlight`.
- **The checklist card** is content: `surface` plus the standard material, with no Liquid Glass
  (R-M5). **Start** is the page's one prominent control (`MeadowPill`, §7).

#### 4.1.2 Wireframe (light, "day meadow")

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ ☁ (painted sprite, outer 25 %)      procedural day sky       (painted sprite) ☁  │
│                                                                                  │
│                                 Hello, Ada.                   Instrument Serif 40 │
│                    Here's what Cicada found on this Mac.      Instrument Serif It. 28│
│            One memory for every AI you use. It lives on this Mac,    SF 13, textSecondary│
│                         in plain files you own.  Not Ada? Change  caption link    │
│ ,,/\,,✿,/\,,,/\,,/\,,  grass + dandelion edge (static)  ,,/\,,/\,✿,,/\,,,/\,,/\,, │
├──────────────────────────────────────────────────────────────────────────────────┤
│    ┌─────────────────────────────────────────────────────────────────────────┐   │
│    │ YOUR AI APPS                                                            │   │
│    │ [✓] [cc] Claude Code   New sessions are remembered. Past ones stay.   ›  │   │
│    │ [✓] [cx] Codex         New sessions are remembered. Past ones stay.   ›  │   │
│    │ [ ] [cu] Cursor        Opens Cursor to add Cicada                        │   │
│    │ [ ] [cd] Claude        Sets up the Claude desktop app                    │   │
│    │ YOUR BROWSERS                                                           │   │
│    │ [✓] [ch] Chrome        2,104 bookmarks, and new ones as you save them ›  │   │
│    │ (!) [sa] Safari        Needs Full Disk Access to read      ( Allow… )    │   │
│    │ YOUR CHAT HISTORY                                                       │   │
│    │ ┌╌ Drop a Claude, ChatGPT or Gemini export here   [cl][gpt][gem] ╌╌╌╌╌┐ │   │
│    │ └╌ No export yet?  Ask for one ▾   It arrives by email.  ╌╌╌╌╌╌╌╌╌╌╌╌╌┘ │   │
│    │ WHO READS WHAT YOU SAVE                                                 │   │
│    │ ┌[claude]─────────┐┌[chatgpt]────────┐┌[ollama]────────┐┌[key]──────────┐│   │
│    │ │ Claude plan   ◉ ││ ChatGPT plan    ││ On this Mac    ││ An API key    ││   │
│    │ │ Uses your plan  ││ Uses your plan  ││ Free, slower   ││ Billed per use││   │
│    │ │ Signed in · Max ││ Sign in         ││ Not running    ││ Add a key     ││   │
│    │ └─────────────────┘└─────────────────┘└────────────────┘└───────────────┘│   │
│    │ Plans read when you ask. A key or Ollama can also read on a schedule.   │   │
│    │ Plans and keys send what Cicada reads to that provider.                 │   │
│    └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│    [worm 48]              ( Start remembering )                                  │
│                  Connects 2 apps and brings in 2,104 bookmarks.                  │
│                     Try the demo instead  ·  Set up later                        │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Legend.**
- `[✓]` means ticked. It is on by default only by `FoundPolicy` (§4.1.4).
- `[ ]` means shown but not ticked.
- `(!)` means the row needs a permission first. Its button *is* the tick.
- `›` is a disclosure, "What this changes" (§4.1.6).

**Hidden rows.**
- An absent app has **no row**.
- A section with no rows collapses. If *every* section except chat history is empty, the card reads
  "Nothing to bring over automatically. That's fine." and the chat-history drop zone grows.
- **Notes & voice** (Obsidian `md.obsidian`, Wispr Flow `com.electron.wispr-flow`, Apple Notes
  under "More") renders only once Track F or N ships the reader behind the row. A row that leads
  nowhere is the lie that `ImportTileState` already refuses.

**Dark mode.** The night gradient, the `-dark` art (a silhouette grass, and moon-cloud at no more
than 40 %), and the same layout.

#### 4.1.3 Detection (`LocalInventory`, app-side, no outbound network)

- **When it runs:** on appear, on `NSApplication.didBecomeActiveNotification` (to pick up a Full
  Disk Access grant), and after any row action.
- **Local checks** take under 50 ms, so every row, mark and name renders at once.
- **Backend-probed states** show "Checking…" until they land. That is the "never blank" rule.

| Row | Present when | State source | Mark (installed icon → PNG → SF, `Views/Common/OriginMark.swift:15`) | Default |
|---|---|---|---|---|
| Claude Code | `GET /agents/wiring` → `claude-code.installed` (new, §9.3) | `recall` (MCP) + `autosave` (Stop hook) | `claude-code` PNG | **on** |
| Codex | the same → `codex.installed` | the same, against `~/.codex/hooks.json` | `codex` / `codex-dark` | **on** |
| Cursor | bundle id `com.todesktop.230313mzl4w4u92` via `InstalledAppIcon` (`Views/Common/InstalledAppIcon.swift:27`) | none (Cursor owns its config) | installed icon | off (it opens another app) |
| Claude (desktop) | `com.anthropic.claudefordesktop` | the app reads `~/Library/Application Support/Claude/claude_desktop_config.json` for an `mcpServers.cicada` key. This is the `~/Library` rail: the app reads. | installed icon | off |
| Chrome | a `BrowserFileSignature` for `.chromeBookmarks` (`Services/BrowserWatch.swift:49-57`) | count from `POST /sources/sync-bookmarks?preview=true`, which stages nothing (`api/routers/sources.py:330-380`) | installed icon `com.google.Chrome` | **on** |
| Safari | `Bookmarks.plist` exists | readable, or `BrowserFileError.notReadable` → needs permission | installed icon (Apple marks are never committed) | **on if readable**; otherwise `Allow…` |
| Obsidian / Wispr Flow / Apple Notes | bundle id + Track F/N readiness | Track F/N previews | installed icon | off (`.ownArchive` / `.includesOthers`) |
| Chat history | always shown | `ExportWaits` (§5.5) | `claude`, `chatgpt`, `gemini` PNGs | not a checkbox |
| A dropped file | a drop on the Welcome | `POST /intake/sniff` (§9.1) | vendor mark | **on** (the drop was the act) |

**Detect by bundle id, never by name.** The ChatGPT app on this machine reports
`com.openai.codex`, and older builds report `com.openai.chat`. Keep a small alias list (§14).

#### 4.1.4 `FoundPolicy` (pure, `Support/FoundPolicy.swift`)

```swift
struct FoundItem { let id: FoundItemID; let group: FoundGroup; let isPresent: Bool
    let content: Content          // .ownIntentionalAct | .ownArchive | .includesOthers
    let readiness: Readiness      // .ready | .checking | .needsPermission | .needsGrant | .alreadyOn | .failed(String)
    let opensAnotherApp: Bool }

enum FoundPolicy {
    static func defaultOn(_ i: FoundItem) -> Bool {
        i.isPresent && i.content == .ownIntentionalAct && i.readiness == .ready && !i.opensAnotherApp
    }
    static func order(_ items: [FoundItem]) -> [FoundItem]      // group order, then defaultOn first, then title
    static func startSummary(_ ticked: [FoundItem]) -> String  // "Connects 2 apps and brings in 2,104 bookmarks."
}
```

- `startSummary` is the Start button's text twin. It is composed from counts through
  `UsageFormat.count` (`CountLiteralLintTests`). With nothing ticked it reads "Sets your name. You
  can add sources any time."
- A permission granted from a row's own button ticks that row, because the click stated the
  intent.

#### 4.1.5 Name and "Who reads"

**Name.** G117 R1 still holds: the name is required, because it is the observer.

- **Prefill order:** `GET /settings/owner` (`Views/Onboarding/OwnerIdentityStep.swift:56-68`),
  then `NSFullUserName()`. It needs no Contacts prompt.
- The headline shows the first word.
- **"Not Ada? Change"** turns the headline name into an inline `TextField` labelled "Your name".
  Return commits.
- **With no name,** the field shows by default and Start is disabled, with "Add your name to start"
  under it.
- Handle and email move to Settings → You (Track O).

**Who reads.** This is `EngineChooser(style: .compact)`, the component Track O puts on Settings →
Engines. There is one implementation.

- The cards are Track E's card row with marks (R-E4).
- Each card carries a **cost-model line** and never a price (ruling 2026-09-03). That is how G117's
  2026-09-04 ruling is honoured *before* choosing:

| Card | Candidate id | Cost-model line | States → action |
|---|---|---|---|
| Claude plan | `agent` | "Uses your plan" | not installed → "Get Claude Code" (shows the adapter hint verbatim; F7 flags it for a fix) · signed out → **Sign in** · connected → selectable ("Signed in · Max", `ConnectionStatus.planLabel`) |
| ChatGPT plan | `codex` (Track E) | "Uses your plan" | **hidden until Track E's `codex` engine ships.** It is never shown as "Coming soon", and the F6 jargon never reaches this screen. After E: Sign in (device code, `~/.cicada/codex`) · connected → selectable |
| On this Mac | `local` | "Free, on this Mac. Slower." | not installed → "Get Ollama ↗" · installed and not running → "Open Ollama" (launches bundle id `com.electron.ollama`) · no model → a `CommandBox` with `ollama pull` |
| An API key | `byok` | "Billed per use by your provider" | "Add a key" expands an inline provider picker (marks) + `SecureField` + Save → `PUT /connections/{id}/key` |

- **Sign-in happens in the card row.** The row expands full-width below the cards, using
  `ConnectionLoginFlow`. That is the one component Plans & keys also uses, so there is a single
  sign-in implementation. Claude uses `claude auth login` through a written `.command` file, or
  runs headless if §14 item 1 verifies that. ChatGPT uses the device code.
- **Which card is ringed** comes from a pure `EngineReadiness.resolve(candidates:, connections:,
  preview:)`:
  - It returns `.ready(id)` when the engine `preview.manual` resolves to can actually run:
    `claude-cli` connected; `ollama` running with a model; `litellm` with a byok row
    `connected` in `Store.connections` (F6).
  - Otherwise it returns `.needsChoice`.
  - With `.ready`, the ring sits on that card with the caption "Will read". With `.needsChoice`,
    there is no ring and the line reads "Not chosen yet. Cicada asks before its first read."
- **A click selects locally.** The write happens at Start (§4.1.7), and **only if the person
  clicked**. An untouched chooser leaves `auto`, which already means "Claude plan if connected,
  else Ollama, else key" (`sleep_engine_prefs.py:104-107`).
- **The two honesty lines** are pure functions of `SleepEnginePreviews`
  (`Models/SleepEngine.swift:25-38`) through `ScheduleHonesty.engineLine` (§5.3). The second line,
  "Plans and keys send what Cicada reads to that provider.", is what keeps the subline "It lives on
  this Mac" true.

#### 4.1.6 Agent rows: consent, "What this changes", and who writes

The `›` disclosure on each agent row shows exactly what Start will do. Example for Claude Code:

```
 Adds Cicada to Claude Code and saves each session when it ends.
   claude mcp add cicada --scope user --env CICADA_MEMORY_PATH=… -- …/python …/mcp/server.py
   Adds a Stop hook to ~/.claude/settings.json
 Past sessions stay where they are. Cicada never reads them.        ( Copy commands )
```

- **Who executes: the app, never the backend.**
  - `GET /agents/wiring` (§9.3) is read-only. For each harness it returns `connect: [{step,
    display, argv, touches}]`, built backend-side from `sys.executable` and the repo root, so there
    is no author path.
  - The app runs each `argv` with `Process`, sets `CICADA_CAPTURE=off`, and checks it against an
    allowlist in `AgentConnectPolicy.isAllowed(argv)`:
    - `argv[0]` is the probed `claude` or `codex` binary with `mcp add cicada`; or
    - `argv[0]` is the backend's python and `argv[1]` is `<repo>/api/hooks/registry.py install`.
  - A backend test asserts that `display == shlex.join(argv)`, so the disclosure can never show one
    thing and run another.
  - `AgentSetupCatalog` (F9) keeps its copy-paste snippets for Settings → Agents. A test asserts
    that its tokens equal the wiring `argv` for claude-code and codex, so the two cannot drift.
- **Claude Desktop** has no CLI:
  - Slice 1: ticking it adds a Getting started row, "Finish in Settings → Agents".
  - Slice 2: the app merges `mcpServers.cicada` into its JSON config after writing a
    `.cicada-backup`, using `registry.py`'s rules (merge, never replace; an unparseable file is left
    untouched). It then shows "Quit and reopen Claude to finish" with an **Open Claude** button.
- **Cursor**: ticking it means Start opens the existing deep link (`ConnectView.swift:70`), and
  Cursor asks the person to confirm.
- **The skill copy (`ConnectView.swift:87`) is not on the Welcome.** Getting started offers it only
  after Track O's Skills page and R5's D2 ruling exist.
- **Owner decision D-1** (§11): may the app register the MCP server and Stop hook after
  tick-consent? `install.sh:277-321` already does exactly this, and for a `.dmg` install the app is
  the only route. **Fallback without D-1:** each agent row becomes **Copy commands** plus **Open
  Terminal** (a 0700 `.command` file, so no Automation prompt). The row re-probes on window focus.

#### 4.1.7 What Start does, in order

1. **`PUT /settings/owner {name}`** runs alone and first. It is the observer every later write
   carries.
   - On failure: an inline `CicadaTheme.danger` line under the name, the button is restored, and
     **nothing else runs**.
2. **If the person picked an engine card:** `PUT /sleep/engine {mode, model: default}` through
   `SleepEngineViewModel.set`. This is the ruling-6 round trip, with no optimistic apply
   (`Views/Settings/EngineCard.swift:193-197`).
3. **`OnboardingState.markOnboarded(bank: store.bank)`** marks the *live* bank, as
   `FirstRunSheet.swift:176-187` requires.
4. **`GettingStartedState.record(bank:, enabled: tickedIDs)`** is written, then the **transition to
   Home** (§4.1.9). It does not wait for step 5, so Start's perceived cost is one round trip.
5. **A `TaskGroup` runs one child per ticked row**, each reporting into Getting started:
   - agents: `AgentConnect.run(argv…)`, then a re-probe of `/agents/wiring`;
   - browsers: `BrowserEnablement.enable(channel)`, then `BrowserWatcher.sync` (F1 fix, §4.3);
   - a dropped file: `IntakeRouter.commit(urls, from: .welcome)`, which is `POST /intake/import`;
   - Cursor: `NSWorkspace.open(deeplink)`;
   - Track F/N rows: their own enable actions.

   Every intake child goes through the router's **counter**, so `store.intakeInFlight` is true
   exactly while at least one runs (the F4 fix).
6. **Failures are per row, never global:**

   | Failure | What the row shows |
   |---|---|
   | exit 3: invalid JSON | "Your Claude Code settings file isn't valid JSON, so Cicada didn't touch it. Fix it, then Retry." |
   | Safari still blocked | the `Allow…` button |
   | backend down | "Waiting for Cicada's background service…", with a retry on the next `store.isConnected` edge |

#### 4.1.8 Secondary actions and modes

- **Try the demo instead.** Unchanged: `tryDemoBank()` (`FirstRunSheet.swift:150-161`). It creates
  and activates the bank, marks the *live* bank, and does nothing else.
- **Set up later.**
  - It runs step 1 only if a name is present. Otherwise the button reads "Set up later (add your
    name first)" and focuses the field, because G117 R1 holds.
  - Then it marks the bank onboarded and lands on Home. Getting started lists every found item
    **unticked** with a Turn on action.
  - No browser is enabled.
- **Rerun** (Settings → General → "Run setup again", via `router.requestFirstRun()`):
  - rows that are already on show `On`, disabled;
  - Start reads **Save changes**;
  - the demo link is hidden;
  - **Close** and Esc dismiss the page.
- **First run:** Esc does nothing. The page is not a sheet, and a stray Esc must not skip setup.

#### 4.1.9 Interaction spec (Welcome)

| # | Trigger | Response | Duration constant | Reduce Motion | Text twin | Accessibility |
|---|---|---|---|---|---|---|
| W1 | Gate opens | The page fades in, the clouds start drifting, and the rows reveal top to bottom | `CicadaMotion.morph` (0.35 s) fade; `CicadaMotion.revealStagger` (0.04 s) per row, capped at `revealMaxRows` (8) | Everything at once; clouds static | n/a (art is `accessibilityHidden(true)`) | Focus goes to the headline (`.isHeader`). VoiceOver: "Hello, Ada. Here's what Cicada found on this Mac. 5 items, 3 turned on." |
| W2 | Clouds idle | Drift ≤ 8 pt, sinusoidal | `CicadaMotion.cloudPeriod` (90 s), `cloudAmplitude` (8 pt); `TimelineView` paused when the window is inactive (R-M6) | static | n/a | hidden |
| W3 | Pointer enters a row | Row fill → `surfaceHover`; the mark nods once | `CicadaMotion.hover` (0.18 s); `MarkHover` with `CicadaMotion.markNod` (0.32 s) | fill only; the mark is still | n/a | pointer-only cue |
| W4 | Click a row, or Space on a focused row | The tick toggles; `checkmark.circle.fill` bounces; the detail line switches "Found" ↔ "Will remember…"; `startSummary` updates | `.symbolEffect(.bounce, value:)` (macOS 14) | `.symbolEffectsRemoved(reduceMotion)` | the detail line and `startSummary` | A real `Toggle` (`FoundRowToggleStyle`). Label: "Chrome. 2,104 bookmarks. On." |
| W5 | `Allow…` on Safari | Opens `BrowserFileError.fullDiskAccessURL`. On `didBecomeActive`, re-probe; if readable, the row ticks itself | none | none | "Allowed. Safari bookmarks will come along." | Announcement with the same sentence |
| W6 | `›` on an agent row | Disclosure expands: the commands and the files touched (§4.1.6) | `CicadaMotion.settle` (0.35 s) | instant | the commands themselves | Disclosure is a button: "What this changes, Claude Code" |
| W7 | "Not Ada? Change" | The headline name becomes a field; Return commits; empty disables Start | `CicadaMotion.morph` | instant swap | "Add your name to start" | Field labelled "Your name"; focus moves into it |
| W8 | Click an engine card | Local selection ring + "Will read" caption; needs sign-in → the flow expands under the cards | `CicadaMotion.settle` for the ring; `morph` for the expansion | instant | "Selected" badge; the sign-in status line | Radio group "Sleep engine"; `.isSelected` on the picked card |
| W9 | Sign-in completes | The card shows "Signed in · <plan>"; a ✓ one-shot | `CicadaMotion.success` (0.4 s) | instant ✓ | the same text | Announcement: "Signed in to Claude." |
| W10 | A file dragged over the window | The chat-history zone border turns `meadow` 2 pt with a `meadowWash` 40 % fill; its first line reads "Drop to add" | `CicadaMotion.hover` | colour only | "Drop to add" | `.onDrop(isTargeted:)` drives it; the keyboard path is "Choose a file…" |
| W11 | Drop | Sniff; a synthetic ticked row "[gpt] ChatGPT export · 412 conversations · 2023–2026 · 374 new" with × | `revealStagger` for the one row | instant | the row | Announcement: "Added ChatGPT export." |
| W12 | "Ask for one ▾" | A menu per vendor (with marks): "Open the export page ↗" and "Remind me: in 3 hours / tomorrow 9:00 / in 2 days" (§5.5) | system menu | system | "Requested just now · reminder tomorrow 9:00" under the zone | Menu items are labelled with the vendor name |
| W13 | Hover Start | macOS 26: the interactive glass reacts. 14/15: `HoverLift` (scale ≤ 1.02, lift ≤ 2 pt) | `CicadaMotion.hover` | shadow cue only | n/a | `.keyboardShortcut(.defaultAction)` |
| W14 | Start | Label → "Starting…" with a small `ProgressView`; the worm turns `.reading` if an intake is ticked. After the owner PUT, the Welcome transitions to Home: the sky band collapses to Home's header band and the card crossfades into Getting started | `CicadaMotion.morph`. `matchedGeometryEffect` on the card container only, with a crossfade fallback | instant swap to Home | Getting started rows ("Connecting…", "Saving bookmarks…") | Announcement: "Cicada is setting up 3 things." Focus moves to the Getting started heading |
| W15 | Owner PUT fails | Inline `danger` line; button restored | none | none | the message | Announced |

### 4.2 Screen 2: Home's Getting started card (the continuation)

It sits at the top of Home (§6) until it is done or hidden.

```
┌ Getting started ─────────────────────────────────────────────────── Hide ┐
│ ✓ [cc] Claude Code   New sessions are remembered                         │
│ ⟳ [cx] Codex         Connecting…                                         │
│ ✓ [ch] Chrome        2,104 bookmarks saved · new ones too                │
│ ! [sa] Safari        Needs Full Disk Access                  ( Allow… )  │
│ ○ [gpt] ChatGPT history  Requested 2 h ago · reminder tomorrow 9:00   ✕  │
│ ─────────────────────────────────────────────────────────────────────── │
│ [worm 24] 61 waiting to be read.          ( Read now )  Uses your Claude plan │
│ Also found: [cu] Cursor  [cd] Claude          Turn on ›                  │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Rows and their states (the source for each state)

| Row | States (text, always) | Source |
|---|---|---|
| Each enabled agent | Connecting… → ✓ "New sessions are remembered" / ! reason + Retry | the `AgentConnect` result, then `GET /agents/wiring` |
| Each enabled browser | "Saving bookmarks…" (indeterminate, never interpolated) → ✓ "N bookmarks saved · new ones too" / ! reason | `BrowserWatcher.state(for:)` / `error(for:)` (`BrowserWatch.swift:236-237`); N from the sync result |
| Chat history | "Drop an export here" / "Requested 2 h ago · reminder …" / ✓ "412 conversations brought in" | `ExportWaits` (§5.5), then the intake result |
| **Who reads** (only when `EngineReadiness == .needsChoice`) | "Choose who reads before the first read" → the inline `EngineChooser` | §4.1.5 |
| **Read what came in** (while `!hasRunBefore`) | see the next table | `store.status` + `sleepVM` |
| **Keep reading on its own?** (once, after the first cycle) | see "The schedule question" below | `ScheduleHonesty` (§5.3) |
| Also found | the unticked found items, each with **Turn on** (the same `FoundRow` component) | `LocalInventory` |

#### The first read: the payoff (replaces G117's step 4 and Guided's ⑤)

Each state has a line, and that line is always the text twin.

| Status (`SleepStatusResponse`, `Services/APIClient.swift:676-722`) | Worm (24 pt) | Line | Action |
|---|---|---|---|
| idle, `debt.unprocessedCount == 0`, never ran | `.awake` | "Nothing to read yet. Drop an export, or chat with a connected app." | none |
| idle, count > 0 | `.reading` (`deriveSleepPageMood`, `Views/Sleep/SleepMood.swift:94`) | "61 waiting to be read." | **Read now** (`sleepVM.triggerManually()`, `SleepViewModel.swift:296`). Subtitle: `Copy.engineLabel(preview.manual.engine)`. With `.needsChoice`, the chooser opens first |
| running | `.sleeping(stage:)` | "Reading · Read 12 of 61". The meter never appears without its noun; `—` with a hover reason when `progressPct == nil` (R-A14) | "Watch on the Sleep page ↗" (→ `.sleep`) |
| just finished | `.happy` | "Your memory has 146 pages now." (`store.graph.value?.nodes.count`) | **Open the graph** (→ `.graph`) |
| capped (`episodesQueued > episodesTotal`) | `.happy` | "Read 50 this round. 329 still waiting." | **Read the next 50** |
| error | `.error` | The first sentence of `status.error` | **Try again** · "Choose who reads" |

- There is no duration estimate anywhere (G107 deferral).
- "You can leave this page. The bookworm keeps reading." shows while the read runs.

#### The schedule question (moved here from G117 step 4)

This appears once, after `hasRunBefore` flips.

```
 Keep reading on its own?
 (•) When I ask    ( ) After imports    ( ) Every night at 3:00
 Your Claude plan reads only when you ask. To read on a schedule, add a key or run Ollama.
 [ ] Remind me each evening when there's something to read
                                                               Not now
```

- **Options** map to `mode: manual | after_import | daily(3:00)`. The writer is
  `SleepViewModel.updateSchedule`, the only one (`Views/Onboarding/OnboardingSleepStep.swift:83-88`
  today).
- **Disabled options** come from `ScheduleHonesty.enabledModes`: only `manual` when the scheduled
  engine cannot read.
- **An existing `interval`** shows as a fourth, read-only option ("Every 6 hours, set in Settings")
  and is never downgraded (Track P R4).
- **The evening reminder** is §5.5's `EveningReminder`. Tapping the notification **opens the Sleep
  page**. It never starts a cycle, so G125 R10 needs no third amendment.

#### Completion and persistence

- **Where it lives:** `GettingStartedState` (per bank, `UserDefaults`
  `cicada.gettingStarted.<bank>.{enabled,hidden,scheduleAsked}`, the `OnboardingState` pattern,
  `Support/OnboardingState.swift:11-27`).
- **Done** when all three hold:
  - every enabled row is ✓ or dismissed;
  - `hasRunBefore`;
  - the schedule question has been answered or set to Not now.

  Done shows "You're set up." for the session, then the card is removed.
- **Hide** removes it early.
- **Reopen:** Settings → General → "Show setup checklist" (Track O row) resets `hidden`.

### 4.3 The consent fix (ships first; F1)

- **`BrowserWatchPolicy.shouldSync(current:lastSynced:enabled:)`** returns false when `!enabled`.
  Both `catchUp()` (`:225-232`) and `syncIfChanged` (`:299-306`) pass it.
- **`cicada.browserWatch.enabled.<channel>`** is machine-global, like the signature key. There are
  three writers:
  - the Welcome;
  - the `+` sheet browser panels (`Views/Capture/Sheets/BrowserImportPanels.swift:16-37`);
  - Integrations.
- **Migration:** a channel with a stored signature counts as enabled, so existing installs see no
  change.
- **The watch stays armed.** `arm()` (`:265-282`) is unchanged. Only the sync is gated.
- This amends G129 slice 1's "read a browser the product has listed and never opened". The product
  now reads it the moment the person ticks it, not before.

---

## 5. The final import flow

### 5.1 One router

`Support/IntakeRouter.swift`, `@MainActor @Observable`, injected at the app root:

```swift
enum IntakeOrigin { case welcome, home, windowDrop, dock, menuBar, sleepRoom, emptyState(AppTab),
                    feedPlus(ChatVendor?), fileMenu, reminder(ChatVendor), onboardingRow }
func accept(urls: [URL], from: IntakeOrigin)      // the seam Track Z's mascot-instrument design names
func present(from: IntakeOrigin)                  // no file yet: open IntakePanel idle
func commit(urls: [URL], from: IntakeOrigin) async -> IntakeResult   // Welcome's Start path
private(set) var phase: IntakePhase               // observed by Track Z's worm caption
```

- **Routing.**
  - When the Welcome is showing, `accept` sniffs and adds a synthetic row (W11). Nothing imports
    before Start.
  - Otherwise it raises **`IntakeOverlay`** over the current window. This is a ZStack overlay, not
    a `.sheet`, so it can sit above any page and share the drop veil.
  - The `+` sheet's vendor flows embed `IntakePanel(vendor:)` directly.
- **It owns `store.intakeInFlight`** through a counter (`active > 0`). No surface writes the flag
  directly again (F4).
- **It owns the sniff/confirm generation token.** This is the H1 discipline hoisted from
  `AddSourceSheet`: a late response never lands on a newer preview.
- **`expand(urls:)` runs app-side.**
  - It walks folders (the `~/Library` rail), collects `.json/.html/.zip/.plist/.opml`, and caps at
    512 files with a stated message.
  - It replaces `UploadOverlay.swift:364-387` and `AddSourceSheet.expandToFiles`.
  - Skipping `user(s).json`, `message_feedback.json` and `model_comparisons.json` is **the
    backend's job**. It is reported in `ignored[]` and fixed once.
- **It clears an `ExportWait`** whose vendor matches a sniff.

**Entry points**

| Entry | Today | After |
|---|---|---|
| Window | none | `ContentView` `.onDrop(of: [.fileURL])` + a **drop veil** (2 pt dashed `accent` inset 12 pt; card "Drop to bring into Cicada" + vendor marks; `CicadaTheme.scrim`) |
| Dock icon | none (F10) | `@NSApplicationDelegateAdaptor` + `application(_:open:)`, **plus** `CFBundleDocumentTypes` in `bundle.sh` (`LSHandlerRank = Alternate`, role Viewer, for `public.zip-archive`, `public.json`, `public.html`, `public.folder`) so Cicada never becomes the default opener |
| Menu bar | NSMenu only (`MenuBarManager.swift:190-236`) | "Import a file…" between "Save clipboard URL" and "Open Cicada"; the status button as a drag destination (verify, §14) |
| File menu | none | **File → Import… ⌘⇧I**, a `CommandGroup`. This is the keyboard and VoiceOver twin of every drop |
| Sleep-room worm | inert (`Views/Sleep/DeskScene.swift:162`) | Track Z: `accept(urls:, from: .sleepRoom)` |
| Empty states | a text action (`ContentView.swift:255-261`, `FeedView`) | `EmptyStateView` gains a drop target + "Drop a chat export here" |
| Home field | n/a | a drop goes to the router; a pasted URL gives "Save this link" (§6.3) |
| Feed `+` | one two-vendor tile, no zip, no drop (`AddSourceSheet.swift:583`, `:782-792`) | a top drop zone + an "On this Mac" strip (`FoundRow`s) + **three vendor tiles** (Claude, ChatGPT, Gemini) with marks, each `IntakePanel(vendor:)` |
| Feed Upload button | `TopBarControls(showsUpload: true)` (`FeedView.swift:78-82`) | **retired**. Both reasons at `:64-77` are absorbed: bank choice lives in the preview, and every intake sets `intakeInFlight` |
| Notification tap | none | `.reminder(vendor)` → `present` |

### 5.2 `IntakePanel`: states and wireframes

```
idle ─drop/choose─▶ reading ─sniff ok─▶ preview ─Import─▶ importing ─▶ done (what happens next)
  ▲                    │ sniff failed      │ Cancel           │ error
  └────────────────────┴──────────▶ failed (exact reason · Choose another file) ◀──┘
```

**Idle** (in the overlay or a `+` vendor tile):

```
 ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
 ╎   [claude] [chatgpt] [gemini]                                        ╎
 ╎   Drop an export here. The .zip is fine.          ( Choose a file… )  ╎
 ╎   Cicada works out what it is. Nothing is read until you say so.     ╎
 └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
 Don't have one yet?
 [claude]  Claude    Every Claude chat, with its date.  ( Open export page ↗ ) ( Remind me ▾ )
 [chatgpt] ChatGPT   Every ChatGPT chat, with its date. ( Open export page ↗ ) ( Remind me ▾ )
 [gemini]  Gemini    Your Gemini activity, from Takeout. ( Open export page ↗ ) ( Remind me ▾ )
 › How to get each one (3 steps, none of them "unzip")
```

- The marks come from `OriginIconography.logoName(for:)`
  (`Views/Capture/OriginIconography.swift:179`) with the origins `claude-export`,
  `chatgpt-export` and `gemini-export`.
- "What you get" is `WalkthroughVendor.summary`, which gains a `.gemini` case.
- The steps are rewritten without "unzip" (`WalkthroughPanel.swift:47, 53`) once I0 accepts zips.
- **Not shown:** Grok, Perplexity and DeepSeek, until the generic per-thread parser exists (R7 §1.5).

**Preview:**

```
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ [chatgpt]  ChatGPT history            from conversations.json             │
 │ 412 conversations · Mar 2023 – Sep 2026                                   │
 │ 374 new · 5 grew since last time · 33 already here                       │
 │ ┌ Filter titles…                                  12 of 412 ┐             │
 │ │ <title>                                         Sep 12, 2026 │           │
 │ │ <title>                                         Sep 03, 2026 │           │
 │ └ … virtualised                                              ┘             │
 │ Skipped: user.json (account details, not conversations)                   │
 │ Into  [ This memory ▾ ]   (other memories · New memory…)                  │
 │                                              Cancel      ( Import 379 )   │
 └───────────────────────────────────────────────────────────────────────────┘
```

- **Counts, range, delta, `ignored[]` and titles** all come from `POST /intake/sniff` (§9.1).
  Titles are capped at 5,000, sent over loopback and never persisted. Past the cap the preview says
  "Filtering the first 5,000 titles."
- **The filter** is local, using Track S's `QuickMatch` (the owner's "fast search" ask on the one
  list scanned here).
- **Import N** means `new + grew`. With 0 it reads **Nothing new** (disabled), and the line reads
  "Everything in this export is already in your memory."
- **Into** absorbs `UploadMode.project` (G87). An inactive target shows the existing line and
  **Switch** (`UploadOverlay.swift:114-134` behaviour).
- **Saved content.** A sniff of `kind: saved` (bookmarks HTML, Takeout, OPML) previews through
  `/sources/upload?preview=true` (`sources.py:137-186`) and commits through `/sources/upload`. The
  panel is the same; the counts are in its own noun.
- **Unrecognised files** get the backend's reason verbatim. For example: "This looks like
  ChatGPT's `chat.html` viewer. Drop `conversations.json` or the whole .zip." There is a **Choose
  another file** action. It never says "Imported 0".

**Importing:** the worm (48 pt, `.reading`) with "Bringing in 379 conversations…". Above 10
episodes the backend backgrounds the job, and the line becomes "Bringing in 180 of 379", read from
`GET /intake/jobs/{id}`. That count appears only once the job reports and is **never
interpolated**.

**Done: what happens next.** This card **never auto-closes**. The 1.5 s auto-dismiss is deleted
with `UploadOverlay`.

```
 ✓  379 conversations are in.   Mar 2023 – Sep 2026 · 5 grew · 33 unchanged
    Cicada reads these when you ask.                              ← ScheduleHonesty line A/B/C
    ( Read now )  Uses your Claude plan          They'll show in Sources as "ChatGPT export" ↗
                                                                              Done
```

- **Read now** is a user trigger. It is the second of the two narrow G125 R10 amendments (§10).
- With `EngineReadiness == .needsChoice`, Read now opens the chooser inline first.
- Inside onboarding (Welcome → Home), the done state is folded into the Getting started chat
  history row, so there is no second Read now on one page.

### 5.3 `ScheduleHonesty` (pure, `Support/ScheduleHonesty.swift`)

```swift
struct HonestyInputs { let schedule: ScheduleConfig; let preview: SleepEnginePreviews
                       let hasKey: Bool; let ollamaReady: Bool; let claudeConnected: Bool }
enum ScheduleHonesty {
    static func scheduledCanRead(_ i: HonestyInputs) -> Bool
    static func engineLine(_ i: HonestyInputs) -> String          // Welcome + chooser caption
    static func afterImportLine(_ i: HonestyInputs) -> String     // done card: A / B / C
    static func enabledModes(_ i: HonestyInputs) -> Set<ScheduleMode>
    static func offerEveningReminder(_ i: HonestyInputs) -> Bool
}
```

**`scheduledCanRead`** is decided by `preview.scheduled.engine`:

| Scheduled engine | Can read when |
|---|---|
| `litellm` | `hasKey` |
| `ollama` | `ollamaReady` |
| `claude-cli` | `claudeConnected`. This is reachable only through an `api/.env` pin, which the caption at `EngineCard.swift:185` already discloses |
| `codex-cli` | connected |

**`afterImportLine`**

| Line | Condition | Text |
|---|---|---|
| A | mode is `manual` | "Cicada reads these when you ask." |
| B | not manual, and `scheduledCanRead` | "Cicada reads these {tonight at 3:00 / within 6 hours / a few minutes after imports settle}, using {Copy.engineLabel(scheduled)}." Scheduled BYOK spend is disclosed by engine name (R8 §6) |
| C | not manual, and not `scheduledCanRead` | "Scheduled reads never use a plan, so these wait until you read them. Read now, or add a key." |

**`engineLine`**

| manual → scheduled | Line |
|---|---|
| plan → litellm with a key | "Your plan reads when you ask. Scheduled reads use your API key." |
| plan → litellm with no key | "Plans read when you ask. A key or Ollama can also read on a schedule." |
| ollama → ollama | "Reads on this Mac, whenever it runs. Nothing leaves this Mac." |
| litellm → litellm | "Your key reads, when you ask and on a schedule. Your provider bills per use." |

**The ruling-4 invariant is tested.** For every `manual.engine ∈ {claude-cli, codex-cli}` with
scheduled `litellm` and `hasKey == false`:
- `enabledModes == [.manual]`;
- `offerEveningReminder == true`;
- `afterImportLine` is never B.

This function replaces `OnboardingSchedule` (`OnboardingSleepStep.swift:8-37`), which reads only
the schedule and is false for plan-only engines (R7 F7).

### 5.4 Retirements and fixes this implies

| What goes | Replacement or reason |
|---|---|
| `UploadOverlay.swift` (whole file) | `UploadHistoryStore` (`:618-655`) moves beside the router and records the sniffed vendor. The mode enum, the three copies, the literal `.spring(duration:)` (`:67`, `:443`) and `.easeInOut(duration:)` (`:207`), and the `Color.black.opacity(0.4)` scrim (`:63`, now `CicadaTheme.scrim`) go with it |
| `AddSourceSheet.runImport` summary "Imported N, skipped M" (`:881-907`) | `IntakeSummary.line(new:updated:unchanged:)`. The "updated" clause is kept and omitted only when 0 (G20) |
| `pickChatExport` (`:782-792`) | the `IntakePanel` vendor flows |
| The chat-exports family blurb (`ImportFamilies.swift:32`) | "Claude, ChatGPT and Gemini, each chat with its date." Member marks for all three (`:55`); `AddSourceTile.channelIds` gains `chat-export:gemini` (`AddSourceSheet.swift:125`) |
| `FirstRunSheet.swift`, `OwnerIdentityStep.swift`, `OnboardingSleepStep.swift` | `WelcomeView` + Getting started. Their three `.red` literals (`FirstRunSheet.swift:111`, `OwnerIdentityStep.swift:45`, `OnboardingSleepStep.swift:97`) go with them. Their tests move to `FoundPolicy`, `ScheduleHonesty` and `OnboardingFlow` |

### 5.5 Reminders (`Support/ExportWaits.swift`, `Support/EveningReminder.swift`)

**Export waits.**
- **Record.** "Remind me ▾" offers in 3 hours / tomorrow at 9:00 / in 2 days. The choice writes an
  `ExportWait {vendor, bank, requestedAt, remindAt}` to `UserDefaults` `cicada.exportWaits`. This is
  a per-viewer convenience, never memory.
- **Permission** is requested **only at that moment**
  (`UNUserNotificationCenter.requestAuthorization`).
- **Schedule.** A one-shot `UNCalendarNotificationTrigger`: "Your ChatGPT export should be in your
  email. Drop the .zip on Cicada." Its action is "Open Cicada", which goes to
  `IntakeRouter.present(from: .reminder(vendor))`.
- **Clear.** A wait clears itself on a matching sniff, or after 14 days.
- **Text twins** that need no permission:
  - the Getting started chat-history row;
  - a **waiting strip** above the Feed list ("[gpt] Waiting for your ChatGPT export · requested
    2 h ago · Drop it here ✕"), which is itself a drop target;
  - a disabled menu-bar line: "Waiting for ChatGPT export, requested 2 h ago".

**Evening reminder** (opt-in from the schedule question).
- A daily 19:00 request, kept in sync with `store.status` while the app runs: removed when
  `unprocessed == 0`, re-added when `unprocessed > 0`. It never wakes the backend.
- A tap opens the Sleep page. It never starts a cycle.

**Network.** Neither reminder uses any. Nothing is fetched to learn that an export arrived.

**Later, and opt-in (D-6).** A "Watch Downloads for it" `DispatchSource`. It is app-side and
TCC-gated, runs only while an `ExportWait` exists, and posts only after a local filename heuristic
matches.

### 5.6 Interaction spec (intake)

| # | Trigger | Response | Duration | Reduce Motion | Text twin | Accessibility |
|---|---|---|---|---|---|---|
| I1 | A `.fileURL` drag enters the window | Drop veil fades in | `CicadaMotion.dropVeil` (0.18 s) | instant | "Drop to bring into Cicada" | the keyboard path is ⌘⇧I |
| I2 | Drop | Overlay opens in *reading*; router counter +1; the worms read `.reading` | `CicadaMotion.morph` | instant | "Reading <filename>…" | announced |
| I3 | Sniff returns | Preview fades in; the vendor mark nods once | `morph`; `markNod` | instant; no nod | headline + count lines | Headline is a heading. Delta chips are text ("374 new"), never colour alone |
| I4 | Type in Filter | List narrows on every keystroke (`QuickMatch`, local) | none | none | "12 of 412" | Field labelled "Filter conversation titles" |
| I5 | Import | Card → importing; job counter when reported | `morph` | instant | "Bringing in 180 of 379" | `ProgressView` with a value once known |
| I6 | Done | ✓ one-shot (`phaseAnimator`, scale 0.8 → 1); worm `.happy`; counter −1 | `CicadaMotion.success` (0.4 s) | instant ✓ | lines A/B/C | Focus moves to the card heading; announced |
| I7 | Read now | `sleepVM.triggerManually()`; the card reads "Reading now. Follow along on the Sleep page ↗" | none | none | the same | announced |
| I8 | Sniff fails | The exact reason + Choose another file; counter −1 | none | none | the reason | announced |
| I9 | Esc / Cancel | Cancels a sniff in flight (generation token) or closes the panel; counter −1 | `morph` | instant | n/a | Esc is the cancel action |

---

## 6. G108: the front door, a recommendation

### 6.1 Ruling proposed

**(a) Build Home. It is the front door for new installs and sits at ⌘1.** Graph moves to ⌘2.
**(b) Navigation is historical** (browser-style back/forward). It is built with G106, where
following links makes it load-bearing. This track adds no history stack.

| Option | For | Against |
|---|---|---|
| Graph first (today) | It is the product's identity and most striking artifact | For the general public it is the least legible first screen. It is blank until a Sleep has run, it is not a status and not a search, and the first-run gate opens over it |
| Sleep / study room first (G108's status argument) | It answers "how is my memory doing", and it has the mascot | G125 v3 keeps it single-purpose: one number in one place (R-A5), no clusters or insights, one Consolidate control. Adding search, inbox and setup would break those rulings. It is about consolidation, not recall |
| **Home (recommended)** | Search-first is the fastest route to value ("find what I told my agents"). It is where onboarding continues. Each status appears once and links to its owner. It matches the brief's "friendlier towards the general public" and the owner's G108 words, "graph should follow" | One more sidebar row, and the ⌘ numbers shift by one |

### 6.2 What Home shows

```
┌ sidebar ─┐┌──────────────────────────────────────────────────────────────────────┐
│ ⌂ Home   ││ ░ skyWash band: procedural gradient + 1 cloud sprite (outer column) ░ │
│ ◎ Graph  ││              What would you like                  Serif 34           │
│ ◍ Clust. ││              to remember?                         Serif Italic 34    │
│ ▣ Feed   ││   ┌──────────────────────────────────────────────────────────────┐  │
│ ☾ Sleep  ││   │ ⌕  Search your memory, paste a link, or drop a file      ⌘K │  │
│ ✉ Inbox  ││   └──────────────────────────────────────────────────────────────┘  │
│ ⊟ Sourc. ││ ┌ Getting started (§4.2, until done) ─────────────────────── Hide ┐  │
│          ││ └──────────────────────────────────────────────────────────────────┘  │
│          ││ TODAY      14 captured today   [cc][ch][gpt]                          │
│          ││            [worm 24] 61 waiting to be read                  Sleep ›   │
│          ││ NEEDS YOU  ◇ <question>                       [cc]                    │
│          ││            ◇ <question>                       [gpt]      All 7 ›      │
│          ││ LAST READ  Sep 22 · 9 new · 24 updated  [chip][chip][chip] +29 Sleep ›│
│ ⚙ ◐      ││ (one suggestion, after the first read: "Use your memory from your     │
│          ││  phone" → Settings → From anywhere · Not now)                          │
└──────────┘└──────────────────────────────────────────────────────────────────────┘
```

**Every number appears once.**
- While Getting started shows its "Read what came in" row, TODAY omits its waiting clause
  (`HomeLayout.showsWaitingInToday`, tested).
- The **worm is 24 pt on the TODAY row**, a content surface. It is never in the painted band, so
  pixel and paint stay apart.

### 6.3 Data source for every element

| Element | Source | Rules |
|---|---|---|
| Headline | static `Copy.homeHeadline` / `homeHeadlineItalic` | `displayFont(34)` (R-M3, ≥ 22 pt) |
| Field | Track S's `FindPanelBody` (the ⌘K palette's body) hosted inline. On Home, ⌘K focuses this field instead of raising the overlay | Typing replaces the cards below with grouped results. A pasted `http(s)://` puts "Save this link · {host}" first (`APIClient.saveURL`, `Services/APIClient.swift:1663`). A drop goes to the `IntakeRouter`. ⌘↩ switches to Ask mode inline (`AskViewModel`, unchanged). Esc clears and restores the cards. Query text never reaches telemetry |
| Getting started | §4.2 | removed when done or hidden |
| "14 captured today" | sum of `activity[ActivityWindow.key(daysBefore: 0, from: today)]` over `store.sourcesOverview` (`Models/SourceOverview.swift:37`; `Views/Sleep/MemorySourcesCard.swift:29`) through `UsageFormat.count` | Noun: **captured** (the Sources v2 rule). One `today` per body evaluation. Hover: "Captured since 00:00 UTC". Marks: the top 3 origins by today's count, each an `OriginMark` opening that source |
| "61 waiting to be read" + worm | `store.status` unprocessed (`MenuBar/BookwormState.swift:120-123`); worm `deriveBookwormState` (`:153`) | **A link to Sleep, never a Consolidate** (G125 R10 holds in steady state) |
| NEEDS YOU | first 3 of `store.visibleInbox` (`Sync/Store.swift:55`) in the inbox's own order | Row: kind glyph, question, harness `OriginMark` from `cause.harness`. A click goes to Inbox with the item expanded (`router.pendingInboxItem`, Track O §1.4) |
| LAST READ | the first `sleepVM.history` entry with `kind == "sleep"` (`SleepHistoryEntry`, `Services/APIClient.swift:854-867`). Chips are its `filesChanged` under `entities/`, joined to `store.graph` names | Home calls `sleepVM.loadHistory()` in `.task`. History is not disk-cached, so the row shows `—` with the hover reason "Loading…" until it lands, and "Nothing read yet" before any cycle. A chip lands on its node (`graphVM.revealEntity`, G123) |
| Suggestion | shown when `hasRunBefore` and remote is off (Track R `GET /remote/status`) | At most one. "Not now" hides it for 30 days, "Don't suggest again" hides it for good, per bank (`cicada.prompt.<id>.<bank>`) |

- **Never blank.** Each row reads a Store snapshot hydrated from the on-disk cache. Anything
  unloaded is `—` with a reason, never a guessed 0 (R-A14).
- **Art.** The header band only (M1 tokens, 1 sprite), with one `backgroundExtensionEffect()` on
  macOS 26 so the sky runs under the glass sidebar (R9 §2.7). Nothing below the band has art.

### 6.4 Sidebar and shortcut changes

**`AppTab`** (`Views/Sidebar/SidebarView.swift:13-48`):
- Gains `case home = "Home"` as the **first** case, with the SF icon `house` and `iconHover()`
  (M1).
- The ⌘ slots follow `allCases` (`:127-128`): **⌘1 Home, ⌘2 Graph, ⌘3 Clusters, ⌘4 Feed, ⌘5 Sleep,
  ⌘6 Inbox, ⌘7 Sources.**
- The surviving raw values never move.

**`restored(from:)`:**
- nil or empty → `.home` (a fresh install);
- a stored `"Graph"` → `.graph`, so existing users reopen where they were;
- an unknown value → `.home`;
- the retired mappings stay unchanged.

**Defaults.** `ContentView.swift:5` `@State selectedTab = .home`, and `:9` `@AppStorage` default
`AppTab.home.rawValue`.

**Relaunch** restores the last tab. That keeps the "reopen where you left off" contract
(`ContentView.swift:6-8`). Whether Home should show on *every* launch is **D-3b** (§11). The
recommendation is no.

**`GraphContainerView` stays mounted** (`ContentView.swift:191-202`). Home is one more tab in
`otherTabContent`, which keeps the G109 lesson.

**Home keeps its field text and scroll position** when the person leaves and comes back with ⌘1.
That state lives in `@State` on a view the tab keeps alive (the graph's pattern); it is not history.

**CLAUDE.md** "Six sidebar rows (⌘1–6)" becomes seven (⌘1–7).

### 6.5 Interaction spec (Home)

| # | Trigger | Response | Duration | Reduce Motion | Text twin | Accessibility |
|---|---|---|---|---|---|---|
| H1 | ⌘1 | Home; focus goes to the field | none | none | n/a | Field labelled "Search your memory" |
| H2 | First keystroke | Cards cross-fade to grouped results (Track S tiers: local first, server rows append below and never reorder) | `CicadaMotion.morph` | instant swap | group headings | results are a list; ↑/↓ and ⏎ per Track S |
| H3 | Paste a URL | Row 0 becomes "Save this link · host" | none | none | the row | the default action |
| H4 | Drop a file on the field | `IntakeRouter.accept(from: .home)` | I1–I9 | — | — | — |
| H5 | Hover an origin mark (TODAY) | `MarkHover` nod | `markNod` | a 1 pt accent ring cue | tooltip "{label} · 6 captured today" | `.help` + label |
| H6 | Hover a NEEDS YOU / LAST READ row | Row fill `surfaceHover` (dense rows never `HoverLift`, R9 §3.2) | `hover` | fill only | n/a | row is a button |
| H7 | Esc in the field | Clears; cards return | `morph` | instant | n/a | focus stays in the field |

---

## 7. Components, tokens, motion

**New shared pieces (T4).**

- **`Theme/MeadowPill.swift`**, the owner's "muted green pill":
  - macOS 26: `.buttonStyle(.glassProminent).tint(CicadaTheme.meadow)`, through the one M1 glass
    entry point.
  - 14/15: `Capsule().fill(meadow)` with the new label token `onMeadow`. That is `#FFFFFF` in light
    (5.56:1 on `#37753D`) and `#0D1216` in dark (≈ 9.5:1 on `#7FC98A`).
  - Reduce Transparency: always the opaque capsule.
  - Font: `CicadaTheme.font(size: 14, weight: .semibold)`.
  - Hover: `hoverLift(scale: 1.02, lift: 1)`. Press: 0.97 (`CicadaPlainButtonStyle`).
  - Used **only** for Start (Welcome) and for the `IntakePanel` Import / Read now. Everywhere else
    the primary stays `accent` (D-4).
- **`MarkHover`**, next to M1's `iconHover()`:
  - `symbolEffect` cannot animate a raster mark, so this is a `keyframeAnimator` (macOS 14) fired
    on hover entry: rotation 0 → −5° → +3° → 0 and scale 1 → 1.08 → 1 over
    `CicadaMotion.markNod`.
  - It is transform-only and never tints (Track L).
  - Under Reduce Motion it becomes a 1 pt `accent` ring.
  - `markHover(trigger:)` accepts an external hover binding, so a whole card can nod its mark.
  - The clip is applied **outside** the animated view (§14 item 4).
- **`FoundRow`** (Welcome, Getting started, the `+` "On this Mac" strip), **`EngineChooser`**
  (Track O/E, compact style), **`ConnectionLoginFlow`**, and **`IntakePanel`**. Each is one
  component with many hosts.

**`CicadaMotion` additions.** Names follow R9 and M1. All are nil under Reduce Motion, and there is
no literal `duration:` outside `CicadaMotion` or `SleepMotion` (R-M4).

| Name | Value | Used by |
|---|---|---|
| `press` / `hover` / `settle` / `morph` | 0.12 easeOut / `.snappy(0.18)` / `.easeInOut(0.35)` / `.smooth(0.35)` | M1 (reused) |
| `revealStagger` / `revealMaxRows` | 0.04 s / 8 | W1 |
| `markNod` | 0.32 s keyframes | `MarkHover` |
| `dropVeil` | 0.18 s fade | I1 |
| `success` | 0.4 s `phaseAnimator` | W9, I6 |
| `cloudPeriod` / `cloudAmplitude` | 90 s / 8 pt (within R-M6's 60–120 s, ≤ 8 pt) | `DriftingCloud` on the Welcome and in the Home band |

**Tokens.** `onMeadow` and `scrim` are new, and both live in `CicadaTheme.swift`
(`ThemeTokenTests`). All nature tokens are M1's (R-M2).

**Art** (R-M6 manifest, `-dark` siblings, `ArtAssetTests`):

| Asset | Notes |
|---|---|
| `cloud-1.png`, `cloud-2.png` | clouds |
| `meadow-edge.png` | tileable, 2400×240 px, dandelions only in the outer 15 % at each end, nothing above 180 px |

The "onboarding hero" of R9 §5.3 is **composed** from these plus the procedural sky rather than
bundled as one opaque image. That keeps text off paint and lets the clouds drift.

**Copy** (`Theme/Copy.swift`, `CopyConstantsTests` ≤ 60 chars): the `welcome*`, `found*`,
`gettingStarted*`, `intake*`, `whatNext*` and `home*` strings. "Claim" never appears in the
onboarding copy.

---

## 8. Data sources (every number and state on these surfaces)

| Shown | Source | File:line |
|---|---|---|
| Show the Welcome? | `FirstRunGate.shouldShow` over `store.banks`, `OnboardingState`, `store.graph` | `Support/FirstRunGate.swift:38-45`; `ContentView.swift:147-157` |
| Name | `GET /settings/owner`, then `NSFullUserName()` | `OwnerIdentityStep.swift:56-68`; `api/routers/settings.py:18` |
| Found rows present | `NSWorkspace` bundle ids; `BrowserFileSignature`; `/agents/wiring.installed` | `InstalledAppIcon.swift:27`; `BrowserWatch.swift:49-57`; new §9.3 |
| Agent recall / auto-save | `GET /agents/wiring` (`claude mcp get cicada` exit code; `registry.status`) | `api/hooks/registry.py:145-155` |
| Bookmark count | `POST /sources/sync-bookmarks?preview=true` | `api/routers/sources.py:330-380` |
| Safari blocked | `BrowserFileError.notReadable` | `Services/BrowserFiles.swift:60` |
| Engine cards | `GET /sleep/engine` candidates + `GET /connections` | `sleep_engine_prefs.py:104-136`; `Sync/Store.swift:36` |
| "Signed in · Max" | `ConnectionStatus.planLabel`, `account` | `Models/Connection.swift:11-14` |
| Ring / "Will read" | `EngineReadiness.resolve` | new, pure |
| Honesty lines | `SleepEnginePreviews.manual/scheduled` (+`why`), `hasKey` from `Store.connections` | `Models/SleepEngine.swift:25-38` |
| `startSummary` | ticked `FoundItem` counts | new, pure |
| Getting started row states | `AgentConnect` results, `BrowserWatcher.state/error`, `ExportWaits`, intake results | `BrowserWatch.swift:236-237` |
| "61 waiting" | `store.status` unprocessed / `debt.unprocessedCount` | `BookwormState.swift:120-123`; `APIClient.swift:630-659` |
| First read meter | `status.stage`, `progressPct`, `episodesTotal`, `episodesQueued` | `APIClient.swift:676-722` |
| "146 pages" | `store.graph.value?.nodes.count` | `Sync/Store.swift:25` |
| `hasRunBefore` | `SleepDebtInfo.hasRunBefore` | `APIClient.swift:634` |
| Schedule | `sleepVM.schedule` (`GET/PUT /sleep/schedule`) | `SleepViewModel.swift:21`; `api/routers/sleep.py:176-181` |
| Preview numbers and titles | `POST /intake/sniff` | new, §9.1 |
| Import result | `POST /intake/import` (`BankImportResponse` fields + `vendor`, `origin`) | `APIClient.swift:153-165` |
| Job progress | `GET /intake/jobs/{id}` | new, §9.2 |
| "Requested 2 h ago" | `ExportWait.requestedAt` (local) | new |
| Today / Needs you / Last read | §6.3 | §6.3 |
| Backend up? | `store.isConnected` | `Sync/Store.swift:79` |

**None of these numbers is a price, a token count, a duration estimate or a percentage of plan
quota.**

---

## 9. Backend and API contract

### 9.1 I0: one intake pipeline ($0, no LLM)

1. **`api/services/episode_staging.py`.** `_stage_episodes` moves here from
   `conversations.py:746` and gains a pure **`plan(drafts) -> {create[], update[], skip[]}`** that
   never writes. `stage()` is `plan()` plus the write. G114 id minting and G20 update-in-place are
   unchanged.
2. **`_parse_zip` becomes multi-member** (`conversations.py:697`).
   - It parses every recognised member: Claude `conversations.json`, `memories.json` and
     `projects.json`; ChatGPT `conversations.json`; Gemini `MyActivity.html`.
   - It returns `ignored[{name, reason}]` for `user(s).json`, `message_feedback.json`,
     `model_comparisons.json` and `chat.html` ("viewer page; the same data as
     conversations.json").
3. **`POST /intake/sniff`** (multipart; `?kind=` optional). It **stages and writes nothing** (the
   `sources.py:137-186` contract). Its response:

   ```
   {recognized, kind: "chat"|"saved"|"unknown", vendor: "claude"|"chatgpt"|"gemini"|null, origin,
    members[], ignored[{name, reason}], counts{conversations, memories, projects, items},
    date_range{from,to}|null, delta{new, grown, unchanged}, titles[{title, date}] (≤ 5000),
    reason|null, warnings[]}
   ```

   - `delta` is computed by `plan()`.
   - `kind: "saved"` delegates to `media_ingestor.preview_upload`.
4. **`POST /intake/import`** (multipart, `bank?`) runs `parse_export_bytes`, stamps the origin and
   calls `stage()`. It returns the `BankImportResponse` fields plus `vendor` and `origin`.
   - `/conversations/upload` and `/banks/{name}/import` become thin shims over it, kept for external
     callers.
   - `/conversations/upload` sets `Deprecation: true`, the nudges-shim pattern. That fixes R7
     defects 1, 2 and 6 for every caller.
5. **A `chat-export:gemini` channel** in `channel_registry` (counting `origin == gemini-export`),
   with `source_overview.py:84-86` and `IntegrationCategory.of` in the app
   (`Models/IntegrationCategory.swift:41`).
6. **Tests** (fixtures only, no network):
   - a Claude zip with three members plus `users.json` → three parsers run and `ignored == 1`;
   - Gemini through the shim → the Gemini parser, with `origin` stamped;
   - the sniff writes nothing (the bank tree hash before and after is identical);
   - `plan()` agrees with `stage()` for a grown thread;
   - a re-import gives `unchanged == N`;
   - a Claude export through the shim is counted by the `chat-export:claude` channel (the
     `sleep_cycle._derive_origin` mis-credit is gone).

### 9.2 I0b: background staging

- When `create + update > 10`, stage in a background task (the `sources.py:222-235` pattern) and
  return `202 {job}`.
- `GET /intake/jobs/{id}` returns `{staged, total, done, error}`. It is process-local, and the app
  polls it every 1 s while the panel is open.

### 9.3 I2: `GET /agents/wiring` (read-only)

- **Computed per request** and never persisted (the `sleep.next_at` pattern).
- **Budgets.** Each CLI probe has 2 s. A timeout gives `"unknown"`, never `"off"`.
- **Response:**

  ```
  {agents: [{id: "claude-code"|"codex"|"gemini-cli"|"hermes", installed: bool, binary: str|null,
             recall: "on"|"off"|"unknown", autosave: "on"|"off"|"stale"|"invalid"|"n/a",
             connect: [{step: "mcp"|"hook", display: str, argv: [str], touches: [str]}],
             detail: str|null}]}
  ```

- **How each field is found:**
  - `installed` / `binary`: `resolve_binary` with the augmented PATH
    (`api/services/connections/base.py`).
  - `recall`: `claude mcp get cicada` exit code (verify, §14), otherwise a parse of
    `claude mcp list` (`install.sh:280`). For Codex, Gemini CLI and Hermes, a read-only parse of
    their dotfile config for a `cicada` key.
  - `autosave`: `registry.status`. When `registry.load` raises, it reports `invalid`, so the app
    can say "not valid JSON, untouched" instead of a false "off" (F8).
- **`argv`** is built from `sys.executable`, the repo root and the live memory path, with
  `CICADA_CAPTURE=off` documented for the executor.
- **What it never does:** write, or read `~/.claude/projects`. The only `~/.claude` read is
  `settings.json` through `registry`.
- **Exposure.** Bearer-authenticated like every route. It is not reachable through Track R's
  listener (R-R1).
- **Tests:**
  - a fake HOME with fixture configs;
  - invalid JSON gives `invalid`;
  - `display == shlex.join(argv)`;
  - no path contains a hardcoded user.

**Claude Desktop and Cursor** status comes from the **app** (`~/Library`), merged client-side.

### 9.4 Small backend fix (with D-5)

The Claude Code install hint (`claude_cli.py:21`) moves off `npm i -g` once the general-public
installer line is verified (§14 item 7). It is a one-line change.

**Unchanged and reused:**
- `GET/PUT /settings/owner`;
- `GET/PUT /sleep/engine`;
- `POST /connections/{id}/login` and its state;
- `PUT /connections/{id}/key`;
- `POST /banks/demo`;
- `POST /sleep/trigger`;
- `GET/PUT /sleep/schedule`;
- `POST /sources/sync-bookmarks[?preview]`;
- `/sources/upload[?preview]`.

**ETag and sync.** The intake and wiring endpoints are request/response, not sync domains, so they
carry no ETag. After an import, the app runs `store.refresh([.channels, .status, .sources,
.graph])`.

---

## 10. Rulings: kept and amended

| Ruling | Source | Status | Why |
|---|---|---|---|
| The gate: unknown is never empty | G117 R6, `FirstRunGate.swift:18-27` | **Keep** | Unchanged. The Welcome is a page shown only when the gate says so |
| The name is the observer and never skippable | G117 R1 | **Keep** | Prefilled, still required, still PUT first. "Set up later" also needs it |
| Demo bank one click away; per-bank flag; re-openable | G117 | **Keep** | "Try the demo instead"; rerun mode |
| The engine is a real choice; the range is the point; cost model before choosing | G117, owner 2026-09-04 | **Keep, non-blocking** | Four cards with cost-model lines on the Welcome. Start does not wait (G105: no engine at capture). The choice is forced at the first read |
| Four-step sheet; R4 "embed `IntegrationsView` wholesale" | G117, `FirstRunSheet.swift:24-30` | **Amend** | Becomes one Welcome plus the Getting started continuation. R4's anti-drift reason is kept through shared components (`FoundRow`, `EngineChooser`, `IntakePanel`, `ConnectionLoginFlow`), each also used in Settings, Feed or Home |
| R7: a hand-off calls `finish()` | `FirstRunSheet.swift:73-77` | **Retired** | There is no hand-off. Imports run through the router and the first read stays reachable (F2) |
| Track P R3/R4: nightly toggle in onboarding; one writer; never downgrade `interval` | `OnboardingSleepStep.swift:3-37` | **Amend** | The schedule question moves to *after* the first read, derived from schedule × `preview.scheduled` (`ScheduleHonesty`). One writer is kept, and `interval` is still never downgraded |
| **Ruling 4:** scheduled cycles never spend plan quota | TODO.md ruling 4; spec decision 3 | **Keep, made visible** | Options that can't deliver are disabled; the engine line and afterImport line C; the invariant is tested |
| No prices or token counts in the app | owner 2026-09-03 | **Keep** | Cost *models* in words only |
| Per-cycle estimates deferred | G107 | **Keep** | No durations anywhere; a meter always carries its noun |
| G125 R10: a cycle starts only from Consolidate or the menu-bar worm | G125 | **Amend, narrowly** | Two moment-bound **Read now** controls are allowed: Getting started until `hasRunBefore`, and the intake done card. Both show `preview.manual` as their subtitle, like Consolidate. Home's steady-state figure is a link. Notification taps never trigger |
| "The Feed keeps its Upload button, the one exception" | CLAUDE.md | **Amend → retired** | Both reasons are absorbed (F5) |
| G129 s1: catch-up reads a never-synced browser | `BrowserWatch.swift:95-104` | **Amend** | Only an *enabled* channel syncs; a stored signature migrates to enabled (F1) |
| G126: standing connections in Integrations, one-shots behind `+` | CLAUDE.md | **Keep** | The Welcome offers both. Where each lives afterwards is unchanged. The `+` "On this Mac" strip reuses `FoundRow` |
| G108 | backlog | **Decide → Home at ⌘1; (b) historical, built with G106** | §6 |
| "Six sidebar rows (⌘1–6)" | CLAUDE.md, G68 | **Amend → seven (⌘1–7)** | Home first; persisted tabs honoured |
| R-M5: glass in chrome only; one prominent action per page | spec, R9 §2.7 | **Keep** | Start is the Welcome's one prominent control; the checklist and Getting started are content |
| R-M2: nature tokens for washes and art only | spec decision 6 | **Amend, narrow (D-4)** | `meadow` may tint the **one** primary pill on the Welcome and the `IntakePanel` confirm, the owner's "muted green pill". It never encodes data |
| R9 §7: imagery places | R9 | **Amend (+1)** | The Home header band: procedural gradient + 1 sprite, carrying no number. The Welcome is onboarding, which R9 already allows |
| R9 §5.3: one opaque onboarding hero per mode | R9 | **Amend (assets)** | Composed from sprites + strip + procedural sky; the manifest and `-dark` rules are unchanged |
| R9 §5.3: pixel art never in the same frame as paint | R9 | **Keep, and correct Found** | The worm sits in the footer cluster (Welcome) and the TODAY row (Home), never on the grass |
| Brand marks: nominative, never recoloured; installed → PNG → SF; no runtime logo network | Track L | **Keep** | `MarkHover` is transform-only. New marks (`openai`, `openrouter` for key providers) arrive via `fetch-logos.sh` and the manifest. The ChatGPT mark is never used for an OpenAI API key |
| R-M4: no literal durations | spec | **Keep, enforced** | `UploadOverlay`'s literals leave with the file. The lint covers `Views/Onboarding/`, `Views/Intake/` and `Views/Home/` |
| G71 §4.3: a preview stages nothing; confirm re-posts bytes | `AddSourceSheet.swift:850-875` | **Keep** | Revisit trigger: sniff + confirm of one file > 5 s on loopback (then spool under `$CICADA_HOME`, never in a bank) |
| G87: say so when an import lands in a non-active bank | G87 | **Keep** | Into + Switch; the Welcome says "into {bank}" when more than one bank exists |
| G20: surface the updated count | G20 | **Keep; the `+` path is fixed** | `IntakeSummary` |
| The app reads `~/Library`; the backend parses bytes | CLAUDE.md | **Keep** | Detection, Claude Desktop config, bookmarks and the Downloads watch are app-side |
| Transcripts under `~/.claude` are never read | CLAUDE.md | **Keep** | The Claude Code row captures *from now on* and says "Past ones stay" |
| G72 "the page never edits `~/.claude`" / R5 D2 | G72, R5 §5.3 | **DECIDE D-1** (MCP + hook only) | The app registers the MCP server and Stop hook after tick consent, the same effect as `install.sh:277-321`. The backend never writes harness roots. The skill copy stays off the Welcome until D2 |
| Remote connector off by default; never opens a tunnel | spec decision 4 | **Keep** | Never on the Welcome; one Home suggestion after the first read |
| Other people's words never `user` evidence; consent per meeting | G95, R-N2 | **Keep** | Wispr is shown unticked, with "includes other voices" |
| G54 interview deferred | G54 | **Keep** | Offered later on the empty Graph for people with nothing to import |
| Copy: subtitles ≤ 60 chars; no "page"; no repeats | `CopyConstantsTests` | **Keep** | Extended to the new strings |

---

## 11. Owner decisions (DECIDE), each with a recommendation

| # | Decision | Recommendation |
|---|---|---|
| **D-1** | May the **app** register the MCP server and Stop hook itself after tick consent, with the exact commands visible under `›`? | **Yes.** It is `install.sh`'s effect from the app, and the only route for a `.dmg` install. Without it: Copy commands + Open Terminal |
| **D-2** | Pre-ticked defaults: agents from now on, plus readable bookmarks | **Yes**, with the count shown and `startSummary` under Start. The alternative (nothing ticked) costs one click per item and loses the "seamless" brief |
| **D-3** | Home first, ⌘1–7 | **Yes.** **D-3b:** always open on Home at launch? **No**: restore the last tab |
| **D-4** | A `meadow` primary pill, on the Welcome and the intake confirm only | **Yes** |
| **D-5** | Claude sign-in: headless `claude auth login` or a `.command` file | Headless if §14 item 1 verifies it; otherwise `.command` |
| **D-6** | Watch Downloads for an export | Later, off by default |

---

## 12. Workflow track: ordered task outline (backend + app)

- **Per-task bar** (working-method): plan → critic → implement + review → verify yourself. Run both
  suites against the baselines in `working-method.md`, one PR per task to `dev`, and cite the `G`
  ids (G117, G108, G129, G20, G87, G125).
- **Models.** Opus for T5, T8 and T9, which are design-heavy; Sonnet for the mechanical tasks (spec
  decision 11).
- **Live checks** use a **fresh throwaway bank**. Screenshots come from the `demo` bank only.

| # | Task | Side | Contents | Depends on | Size | Verification |
|---|---|---|---|---|---|---|
| **T1** | Browser consent fix | app | `BrowserWatchPolicy.shouldSync(…enabled:)`, `cicada.browserWatch.enabled.<channel>`, migration, and the three writers (§4.3) | — | S | `BrowserWatchPolicyTests`: never-synced **and** not enabled → no sync; stored signature → enabled; `catchUp` and the file-change path both gated. Live: with a clean defaults domain, first launch imports no bookmarks and the gate opens |
| **T2** | Intake pipeline | backend | §9.1 items 1–6 | — | M | §9.1 tests; the `/conversations/upload` shim still passes its old callers |
| **T2b** | Background staging | backend | §9.2 | T2 | S | a 50-conversation fixture returns 202; the job reaches `done`; counts match |
| **T3** | Agent wiring probe | backend | §9.3 | — | S | fake-HOME fixtures; `invalid`; `display == shlex.join(argv)`; 2 s budgets give `unknown` |
| **T4** | Shared pieces | app | `MeadowPill`, `MarkHover`, the `CicadaMotion` additions, `onMeadow`/`scrim`, Copy strings, `FoundRow` shell | M1 | S | `ThemeTokenTests`, the R-M4 duration lint, `CopyConstantsTests` |
| **T5** | One intake (app) | app | `IntakeRouter` (counter, generation token, `expand`, `accept/present/commit`), `IntakePanel`, `IntakeOverlay`, drop veil, File → Import ⌘⇧I, menu-bar item, Dock (`NSApplicationDelegateAdaptor` + `CFBundleDocumentTypes` in `bundle.sh`), the `+` sheet's drop zone + 3 vendor tiles + walkthrough copy, `IntakeSummary`, retire `UploadOverlay` and the Feed Upload button, empty-state drop targets | T2, T4 | M | `IntakeRouterTests` (stale response dropped; counter correct on success, failure and cancel; skip list; 512 cap); `IntakeSummaryTests`. Live: a Claude zip dropped on the window; a Gemini Takeout via `+`; a ChatGPT folder containing `user.json` shows "Skipped"; a re-import shows "Nothing new"; a Dock drop |
| **T6** | Pure logic | app | `ScheduleHonesty`, `EngineReadiness`, `FoundPolicy`, `OnboardingFlow`, `HomeLayout` | — (parallel with T5) | S | `ScheduleHonestyTests` (the ruling-4 invariant; `interval` read-only; lines A/B/C); `EngineReadinessTests` (byok with no key → `needsChoice`); `FoundPolicyTests`; `HomeLayoutTests` (the waiting number appears once) |
| **T7** | Detection + agent connect | app | `LocalInventory` (injected probes), `AgentConnect` (`Process` runner, `CICADA_CAPTURE=off`, `AgentConnectPolicy` allowlist), the Claude Desktop config read | T3 | M | `LocalInventoryTests` (missing app → no row; Safari blocked; re-scan on activate); `AgentConnectPolicyTests` (a foreign argv is refused); a catalog-vs-wiring token-equality test |
| **T8** | Welcome | app | `WelcomeView` (full window, sky band, clouds, grass, footer cluster), rows, name edit, `EngineChooser(.compact)` embed (with a fallback to today's candidates if Track O has not landed, hiding `codex` until E), `ConnectionLoginFlow` embed, chat-history zone + "Ask for one", `startSummary`, Start orchestration (§4.1.7), Set up later, rerun mode, the `ContentView` ZStack swap, retire `FirstRunSheet`/`OwnerIdentityStep`/`OnboardingSleepStep` | T1, T4, T5, T6, T7; M1 art | L | `OnboardingFlowTests` (a Start failure runs nothing after the owner PUT; demo marks the live bank; rerun); `WelcomeLayoutTests` (cloud frames never intersect the text safe rect across `uiScale` 0.8–1.4; footer pinned). Live: fresh bank → Welcome → Start → Home with live rows, via `macos-harness` AX |
| **T9** | Home + sidebar | app | `AppTab.home` + `restored` + defaults, `HomeView` (band, field hosting Track S's `FindPanelBody` or a thin local fallback, Today, Needs you, Last read, suggestion), the Getting started card (§4.2: rows, first read, schedule question, completion), `GettingStartedState` | T8; Track S palette body (the fallback allows shipping first) | M | `AppTabTests` (Home first; `restored(nil) == .home`; `restored("Graph") == .graph`; ⌘ order); a Getting started completion test. Live: ⌘1 focuses the field; a first read from Home ends on "N pages now" |
| **T10** | Reminders | app | `ExportWaits`, just-in-time notification permission, Feed waiting strip, menu-bar line, `EveningReminder` sync with `store.status` | T5, T9 | S | `ExportWaitsTests` (add, clear on sniff match, 14-day expiry, per bank). Live: permission prompts only on click; denied → twins still show |
| **T11** | Docs | docs | CLAUDE.md (Navigation: seven rows; the Feed Upload exception removed; the intake paragraph; the onboarding paragraph), backlog rows (G108 ruling; G117, G129, G125 R10 amendments; a new row for any D-6 work), TODO.md header | T8–T10 | S | privacy rule check (no names, titles or URLs) |
| **T12** | Live pass + screenshots | both | An end-to-end run on a throwaway bank: detection → Start → first read → schedule question → an import via each entry point; the demo bank for screenshots (Welcome light and dark, Home, preview, done card) | T1–T10 | S | the §14 verification list closed or re-filed |
| T13 (opt.) | Claude Desktop JSON merge | app | slice 2 of §4.1.6 | T7, D-1 | S | a backup is written; an unparseable file is left untouched |
| T14 (opt.) | Downloads watch | app | D-6 | T10 | S | runs only while a wait exists; no post without a filename match |

**Critical path.** T2 → T5 → T8 → T9. T1, T3, T6 and T4 run in parallel ahead of it.

**Cross-track seams.**
- M1: tokens, fonts, motion, art.
- E: the ChatGPT card.
- O: `EngineChooser`, the Settings rows "Show setup checklist" and You.
- S: `FindPanelBody`, `QuickMatch`.
- R: the Home suggestion.
- Z: `IntakeRouter.accept(urls:, from: .sleepRoom)`.
- F/N: their `FoundRow`s.

---

## 13. Tests and lints (summary)

**Pure Swift tests:**
- `FoundPolicyTests`;
- `LocalInventoryTests`;
- `BrowserWatchPolicyTests`;
- `ScheduleHonestyTests`;
- `EngineReadinessTests`;
- `OnboardingFlowTests`;
- `IntakeRouterTests`;
- `IntakeSummaryTests`;
- `ExportWaitsTests`;
- `AgentConnectPolicyTests`;
- `HomeLayoutTests`;
- `AppTabTests`;
- `WelcomeLayoutTests`.

**Lints extended:**
- `CopyConstantsTests` (new strings; "claim" banned in onboarding copy);
- `FontLiteralLintTests` (`.custom(` outside the theme);
- the R-M4 duration lint (`Views/Onboarding/`, `Views/Intake/`, `Views/Home/`);
- `ThemeTokenTests` (`onMeadow`, `scrim`);
- `ArtAssetTests` (clouds, strip, `-dark`);
- `LogoAssetTests` (any new mark);
- a new `NoRedLiteralLintTests` banning `.foregroundStyle(.red)` under `Views/`.

**Backend tests:** §9.1 item 6, §9.2, §9.3.

---

## 14. Not verified: check before building

1. **Claude sign-in outside a terminal (D-5).**
   - Does `claude auth login` run without a TTY and print a URL?
   - Does a `.command` file opened by `NSWorkspace` run with no Automation prompt on 14, 15 and 26?
2. **`claude mcp get cicada` exit codes** and `codex mcp list` output on the installed versions.
   Prefer `--json` where it exists.
3. **`UNUserNotificationCenter` in the `bundle.sh` ad-hoc-signed app** (the prompt appears; the
   delivery works). If it does not, the twins carry the reminder.
4. **`keyframeAnimator` on an `NSImage`-backed mark** inside `PlatformTile` clipping. Apply the clip
   outside the animated view.
5. **A drag onto `NSStatusBarButton`** (`registerForDraggedTypes` on its window) on 14 and 26.
6. **Dock drops with `LSHandlerRank = Alternate`.** Cicada must never become the default app for
   `.zip` or `.json` (check Launch Services after install).
7. **The general-public Claude Code installer line** (replacing `npm i -g`, F7).
8. **Bundle ids per release:** ChatGPT `com.openai.codex` / `com.openai.chat`; Cursor's
   `todesktop` id.
9. **The F1b race**, reproduced on a throwaway bank with a clean `cicada.browserWatch.*` domain,
   before and after T1.
10. **The macOS 26 "App Data" prompt** when the built app reads Claude Desktop's config, Obsidian's
    `obsidian.json` or Wispr's store (test with the assembled app, not a terminal).
11. **The rendered `.glassProminent.tint(meadow)`** over the sky band, and the `matchedGeometryEffect`
    Welcome → Home transition. Fall back to a crossfade if it stutters (G109 frame budget).
12. **The Gemini Takeout deep link** that preselects "Gemini Apps".
