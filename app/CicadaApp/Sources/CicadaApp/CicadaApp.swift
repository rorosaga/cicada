import SwiftUI
import AppKit
import Combine

/// A transparent AppKit passthrough container that accepts the first mouse
/// click even when its window isn't key yet. `ClickableWebView`
/// (`Views/Graph/GraphView.swift`) already opts into this per-instance for
/// the graph canvas, but plain SwiftUI controls (Button, Toggle, etc.) render
/// inside the framework's own NSHostingView, whose `acceptsFirstMouse(for:)`
/// defaults to `false` — so the very first click on any native control after
/// the app loses focus is consumed as mere window activation instead of
/// reaching the control ("needs a second click" bug). Wrapping the SwiftUI
/// content view once, at the window level, fixes this for every control
/// without touching each one individually.
final class FirstMouseAcceptingView: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

@main
struct CicadaApp: App {
    /// Owner 2026-10-23 — a fresh install's menu-bar worm waits for onboarding's *Meet your bookworm* step; every
    /// earlier install keeps its worm (`MenuBarIntro`). The FIRST stored property, because stored properties are
    /// initialised in declaration order before `init` runs, and several below write a `cicada.` key as they are built
    /// (`ExportWaits`), which would make a fresh install look like an old one.
    private let menuBarIntroAtLaunch = MenuBarIntro.prepareAtLaunch()
    /// Single source of truth for every screen (§5.1). Hydrated from disk on
    /// appear, then kept live by its `SyncEngine`. Every view model below is
    /// constructed in `init()` as a thin projection over this same instance
    /// (§5.5) rather than fetching independently.
    @State private var store: Store
    @State private var graphVM: GraphViewModel
    @State private var inboxVM: InboxViewModel
    @State private var sleepVM: SleepViewModel
    /// G122: the engine-and-model picker (Settings → Intelligence since G139 A3). No `Store`
    /// dependency (ruling 6 — a plain `APIClient` round trip, nothing else
    /// observes this domain) — constructed bare, unlike every view model
    /// above it.
    @State private var sleepEngineVM = SleepEngineViewModel()
    /// G126 R9 — the Feed hand-off, and since DR-33 the Settings panel's
    /// open state (R-DS21 … R-DS24). No `Store` dependency, same reasoning as
    /// `sleepEngineVM` above: nothing but the main window's views — the panel
    /// included — and the menu commands observe this.
    @State private var appRouter = AppRouter()
    /// G152 — the guided tour, app-lifetime like the router: every door asks it, `TourLayer` runs it.
    @State private var tour = TourController()
    /// G118 slice 2 — the Reader's navigation and its in-memory payload
    /// cache. Main window only: the Settings panel never opens a Reader, and
    /// neither is a Store domain (R-PB11), so neither needs the Store.
    @State private var provenanceRouter = ProvenanceRouter()
    @State private var provenanceCache = ProvenanceCache()
    /// G141 PJ-5 (R-PP3) — the Projects page's in-memory cache; app-level so a tab switch keeps what was read.
    @State private var projectsCache = ProjectsCache()
    /// G150 (R-B18) — the Backlog section's in-memory cache; app-level for ProjectsCache's reason.
    @State private var backlogCache = BacklogCache()
    /// G161 — what each source brought in, by name; app-level for ProjectsCache's reason, never a Store domain.
    @State private var channelItemsCache = ChannelItemsCache()
    /// G162 — every saved video's state and the person's video queue; app-level for ProjectsCache's reason, never a
    /// Store domain.
    @State private var videoStateCache = VideoStateCache()
    /// G166 exploring — the explore run and the Explore sheet's counts, for Sources.
    @State private var exploreCache = ExploreCache()
    /// G166 — the sites Cicada's reader could not read, for Home's one line; app-level for ProjectsCache's reason.
    @State private var readingSitesCache = ReadingSitesCache()
    @State private var banksVM: BanksViewModel
    @State private var feedVM: FeedViewModel
    @State private var contributorsVM: ContributorsViewModel
    @State private var connectionsVM: ConnectionsViewModel
    @State private var usageVM: UsageViewModel
    /// G136 — the ⌘K find palette's state, one per app, so its Ask history,
    /// recents and instant index survive the palette closing.
    @State private var findModel: FindPaletteModel
    /// Track I part b (R-IB4) — Home's field: a second palette model sharing
    /// the palette's one Ask, keeping no recents, so a ⌘K elsewhere never wipes
    /// what was left typed on Home.
    @State private var homeSearch: HomeSearch
    @State private var menuBarManager = MenuBarManager()
    @State private var backend: BackendProcess
    /// Round-4 D3 (G143) — Settings → General → In the background. App-lifetime so the
    /// login item's remembered intent and the service probe are one instance per app.
    @State private var loginItems = LoginItemService()
    @State private var backendAgent: BackendAgentService
    /// G182 phase 5 — the in-app updater, app-lifetime like the background service: one schedule and one quit hook
    /// per app. Inert in a developer build.
    @State private var updates: UpdateService
    /// G129: a bookmark saved in Chrome or Safari reaches the queue in seconds
    /// without a button. App-side because the launchd backend has no Full Disk
    /// Access — see `BrowserWatch.swift`.
    @State private var browserWatcher: BrowserWatcher
    /// Round 4 (R-SR17) — the one registry of running syncs every `SourceRow` reads, and where its × goes.
    @State private var syncActivity: SyncActivity
    /// G191 — "What made you save this?": listens to the bookmark watch's syncs and, when the person turned it on,
    /// drops a small panel from the notch for one bookmark made a moment ago. The controller is held here because the
    /// center keeps its presenter weakly.
    @State private var saveWhy = SaveWhyCenter()
    @State private var saveWhyPanel = SaveWhyPanelController()
    /// G191 v3 — Chrome's bookmark bubble, seen from the window list (no permission), opens the question at once.
    @State private var bookmarkBubbles = BookmarkBubbleWatcher()
    /// G191 v3 — the menu bar's bookmark history.
    @State private var bookmarkHistory = BookmarkHistoryController()
    /// G133 / G134: watched folders and Wispr Flow, read by the app (the backend
    /// never opens them). Lights ride `browserWatcher` (R-LS26).
    @State private var localSources: LocalSourceWatcher
    /// Round-4 D2 (C6, C7): the Calendar app's events, read by the app through EventKit only after Connect in
    /// the Sources page, and posted to the backend (R-FA11).
    @State private var calendarReader = CalendarReader()
    /// 2026-10-23: Apple Notes keeps up once the person's own first read turned it on (only while Notes is open).
    @State private var notesWatcher = AppleNotesWatcher.shared
    /// G219: the Reminders lists the person ticks, read by the app through EventKit only after Connect, one way.
    @State private var remindersReader = RemindersReader.shared
    /// Round 4 (G160 first slice): Chrome's open tab groups, read by the app from its session file only after the
    /// person turns on their own switch (R-SR3), and posted per memory.
    @State private var tabGroups: TabGroupWatcher
    /// G71 (2026-10-16): the YouTube videos watched in Chrome, read by the app from Chrome's History (a copy, YouTube
    /// video pages only) only after the person turns on its own switch, and posted per memory as one entry per day.
    @State private var watchHistory: WatchHistoryWatcher
    /// Round 4 (G154): the Mac's address book, read by the app only after Connect on the Sources page and
    /// posted per memory, where it enriches the people Cicada already knows (R-SR8, R-SR10).
    @State private var contactsReader: ContactsReader
    /// G179: the Messages conversations the person ticked, read by the app from `chat.db` (Full Disk Access) and posted
    /// per memory; nothing is read before a tick.
    @State private var messages: MessagesWatcher
    /// G179 (2026-10-28): the WhatsApp chats the person ticked, read by the app from WhatsApp Desktop's store (a copy)
    /// and posted per memory; nothing is read before a tick, and a tick is live from then.
    @State private var whatsApp: WhatsAppWatcher
    /// Ruling 47a: Telegram's row — the backend holds the person's session; the app shows the steps and the ticks.
    @State private var telegram = TelegramChats()
    /// G218 — activity traces: off until the person agrees to the consent sheet; then the app captures and This Mac's
    /// backend keeps them sealed outside every bank. Never on a server connection.
    @State private var traceRecorder = TraceRecorder.live()
    /// Track I T5 (design §5.1) — the one intake: a drop anywhere, the Dock,
    /// File → Import…, the menu-bar worm, an empty state and the `+` tiles all
    /// go through it, and its request counter owns `Store.intakeInFlight`.
    @State private var intakeRouter = IntakeRouter()
    /// Track I part b (R-IB14) — what Start does, app-lifetime so a Welcome that
    /// has faded out keeps reporting its rows to Home's Getting started card.
    @State private var setupRunner = SetupRunner()
    /// One inventory for the Welcome and Getting started, so a row's state is
    /// the same probe on both (the `+` strip keeps its own per appearance).
    @State private var inventory: LocalInventory
    /// Track I part b (R-IB22) — export reminders: a per-viewer convenience in
    /// defaults, told by the Feed, the menu bar and Getting started whether or
    /// not notifications were allowed.
    @State private var exportWaits = ExportWaitStore()
    /// R-IA25 — the one AppKit hook SwiftUI's `App` lacks: a Dock "Open With"
    /// or a drop on the Dock icon. Its queue holds a cold launch's URLs until
    /// `.onAppear` attaches the router.
    @NSApplicationDelegateAdaptor(CicadaAppDelegate.self) private var appDelegate
    /// G130: the local key monitor that routes ⌘⇧= to `CicadaTheme.zoomIn()`
    /// (see `ZoomKeyRouter`). Held so `.onAppear` (which can fire again —
    /// see `enableFirstMouseAcceptance`'s own idempotence note below) never
    /// installs a second monitor and double-fires every zoom keystroke.
    @State private var zoomMonitor: Any?

    // Theme: persisted mode driving both the SwiftUI environment
    // (`.preferredColorScheme`, so system materials/controls follow) and the
    // native AppKit window chrome (titlebar/background), which NSWindow
    // doesn't pick up from SwiftUI state automatically — see
    // `syncWindowChrome` below.
    @AppStorage("cicada.colorScheme") private var colorSchemeRaw: String = AppearancePreference.defaultChoice.rawValue
    /// Round-4 decision 6 (R-HO16) — Settings → General → Show in menu bar, per viewer, on by default.
    @AppStorage(MenuBarPreference.defaultsKey) private var menuBarVisible = true
    @AppStorage(MascotPreference.defaultsKey) private var mascotRaw = MascotRegistry.bookworm.id
    /// R-O4 — the preference resolved against the system appearance
    /// `ThemeStore` tracks (observable, so a macOS flip repaints this scene).
    private var appColorScheme: AppColorScheme {
        AppearancePreference.stored(colorSchemeRaw).resolved(systemIsDark: ThemeStore.shared.systemIsDark)
    }

    init() {
        // Swift Package executable targets launch without an Info.plist, so AppKit
        // treats the process as a command-line tool by default. The window appears
        // but is never made *key*, which means TextFields can never become first
        // responder — that's the "can't type in the search/clarification fields"
        // bug. Explicitly requesting .regular activation fixes it.
        NSApplication.shared.setActivationPolicy(.regular)
        // Activation is the launch's: an interactive one activates in `LaunchState.record`, a login one stays quiet (R-OB18).

        // G139 final review: the System-appearance observer lives at app
        // scope, not on one window — see `ThemeStore.observeSystemAppearance`.
        ThemeStore.shared.observeSystemAppearance()
        // Round-4 D4 — the hero's clock, app scope like the appearance observer.
        SceneStore.shared.start()

        // Build the Store as a plain local value first — referencing `self`
        // (which `store` would, via the property wrapper) isn't allowed yet
        // because the view-model `@State` properties below aren't
        // initialised. Every view model is then constructed as a thin
        // projection over that single Store (§5.5) instead of fetching
        // independently.
        let store = Store()
        _store = State(initialValue: store)
        // G182 — one runtime for the whole app. A release's agents, hooks and background service run the launchers
        // in ~/.cicada/bin, so they are rewritten before anything can spawn through one (five small files; a failure
        // is logged, never fatal). A developer build writes nothing.
        let runtime = CicadaRuntime.current
        LauncherInstaller.install(runtime: runtime)
        // R-FA8 — once the background service is installed, the app hands launchd the backend's port by
        // stopping only the uvicorn child it spawned itself (never a developer's).
        let backend = BackendProcess(runtime: runtime)
        _backend = State(initialValue: backend)
        let backendAgent = BackendAgentService(runtime: runtime, onInstalled: { [backend] in backend.stopSpawnedChild() })
        _backendAgent = State(initialValue: backendAgent)
        // G182 — a background service an older build installed keeps running what it named; point it at this
        // copy's launcher. Never blocks launch, and installs nothing when the person never chose the service.
        // G181 phase 3: nothing to migrate or keep running while the memory lives on a server.
        if runtime.isRelease && !ServerConnection.current.isServer {
            Task { @MainActor in await backendAgent.migrateIfNeeded() }
        }
        // G181 phase 3 (review fix) — on a server, a background service left from This Mac would keep serving this
        // Mac's bank while everything here points elsewhere: stop it (its plist stays, for This Mac again). An invalid
        // address stops nothing — the person fixes it or chooses This Mac, and the service is still there.
        if ServerConnection.current.serverURL != nil {
            Task { @MainActor in await backendAgent.stopForServer() }
        }
        // G182 phase 5 — checks and installs only in a release run from a real folder, never while Sleep writes.
        let updates = UpdateService.live(runtime: runtime,
                                         isSleepWriting: { [store] in ProjectWriteGate.sleepRunning(store.status.value) },
                                         repairService: { [backendAgent] in
                                             guard !ServerConnection.current.isServer else { return true }  // nothing runs here to repair
                                             return await backendAgent.reinstallIfStopped()
                                         })
        _updates = State(initialValue: updates)
        Task { @MainActor in updates.start() }
        let activity = SyncActivity()
        _syncActivity = State(initialValue: activity)
        let lights = BrowserWatcher(activity: activity)
        _browserWatcher = State(initialValue: lights)
        _localSources = State(initialValue: LocalSourceWatcher(lights: lights))
        _tabGroups = State(initialValue: TabGroupWatcher(lights: lights, activity: activity, bank: { [store] in store.bank }))
        _watchHistory = State(initialValue: WatchHistoryWatcher(lights: lights, activity: activity,
                                                                bank: { [store] in store.bank }))
        _contactsReader = State(initialValue: ContactsReader(activity: activity, bank: { [store] in store.bank }))
        _messages = State(initialValue: MessagesWatcher(lights: lights, activity: activity, bank: { [store] in store.bank }))
        _whatsApp = State(initialValue: WhatsAppWatcher(lights: lights, activity: activity, bank: { [store] in store.bank }))
        _inventory = State(initialValue: LocalInventory(probes: LocalInventory.live(watcher: lights)))
        _graphVM = State(initialValue: GraphViewModel(store: store))
        _inboxVM = State(initialValue: InboxViewModel(store: store))
        _sleepVM = State(initialValue: SleepViewModel(store: store))
        _banksVM = State(initialValue: BanksViewModel(store: store))
        _feedVM = State(initialValue: FeedViewModel(store: store))
        _contributorsVM = State(initialValue: ContributorsViewModel(store: store))
        _connectionsVM = State(initialValue: ConnectionsViewModel(store: store))
        _usageVM = State(initialValue: UsageViewModel(store: store))
        let find = FindPaletteModel(store: store)
        _findModel = State(initialValue: find)
        _homeSearch = State(initialValue: HomeSearch(model: FindPaletteModel(store: store, ask: find.ask,
                                                                              keepsRecents: false)))
    }

    /// R-DS23 — ⌘, can reopen the one window: with the app living in the menu bar and no
    /// window open, `ShellCommands` opens this one and the staged Settings request lands in it.
    static let mainWindowID = "main"

    var body: some Scene {
        WindowGroup(id: Self.mainWindowID) {
            mainWindow
            // NOTE: no `.onDisappear` teardown — closing the window must
            // not stop the sync engine. The app lives on in the menu bar,
            // and the bookworm is fed by the Store's status snapshot.
        }
        .defaultSize(width: 1200, height: 800)
        // DR-23 — the titlebar is a command bar: the window's title is hidden, and the toolbar's
        // unified 52 pt band holds the toggle, the bar and the `?` (R-DS16).
        .windowToolbarStyle(.unified(showsTitle: false))
        // G130 R5: the View menu — ⌘+/⌘−/⌘0 scale the whole SwiftUI chrome
        // through the one persisted `CicadaTheme.uiScale` (Task 1). Placed
        // `after: .sidebar` so it lands right after macOS's own "Enter Full
        // Screen" section in the View menu, the natural home for view-scale
        // controls. `.keyboardShortcut("=", modifiers: .command)` is what a
        // US keyboard reports for bare ⌘=; ⌘⇧= (what people actually type
        // for "⌘+") is covered by the local key monitor above via
        // `ZoomKeyRouter`, since SwiftUI cannot give one menu item two key
        // equivalents.
        .commands {
            CommandGroup(after: .sidebar) {
                Button("Zoom In") { CicadaTheme.zoomIn() }
                    .keyboardShortcut("=", modifiers: .command)
                Button("Zoom Out") { CicadaTheme.zoomOut() }
                    .keyboardShortcut("-", modifiers: .command)
                Button("Actual Size") { CicadaTheme.resetZoom() }
                    .keyboardShortcut("0", modifiers: .command)
            }
            // G136 A6 — ⌘K (Find in Memory…) and ⌘F (Find on This Page…).
            FindCommands(router: appRouter)
            // DS-1 T3 (R-DS15) — View → Show labelled sidebar / Show icon rail (⌃⌘S);
            // DS-1 T6 (R-DS23) — Settings… ⌘, opens the in-app panel.
            ShellCommands(router: appRouter, updates: updates)
            // Track I T5 — File → Import… (⌘⇧I): the keyboard and VoiceOver twin
            // of every drop (design §5.1).
            CommandGroup(after: .newItem) {
                Button(Copy.intakeFileMenuItem) { intakeRouter.present(from: .fileMenu) }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
                // Meaning index 2 — the keyboard and VoiceOver twin of dropping a recording or video on the window:
                // the same door (`accept`), so speech is asked only inside this, the person's own action.
                Button(Copy.mediaFileMenuItem) {
                    let urls = IntakePicker.chooseMedia()
                    if !urls.isEmpty { intakeRouter.accept(urls: urls, from: .fileMenu) }
                }
            }
        }
    }

    /// The one window's content, split out of `body` with `environed` and `launch()`: as one expression the scene's
    /// modifier chain and its `.onAppear` closure took the type checker seconds in a release build, near where a
    /// slower runner gives up ("unable to type-check this expression in reasonable time").
    private var mainWindow: some View {
        environed
        // R-IA24 — a Dock open reuses this window instead of opening a
        // second one (the router, and its overlay, live in this one).
        .handlesExternalEvents(preferring: Set(["*"]), allowing: Set(["*"]))
        .preferredColorScheme(appColorScheme == .light ? .light : .dark)
        .onChange(of: colorSchemeRaw) { _, _ in applyAppearance() }
        .onChange(of: menuBarVisible) { _, visible in menuBarManager.setVisible(visible) }
        .onChange(of: mascotRaw) { _, _ in menuBarManager.mascotChanged() }
        .onReceive(DistributedNotificationCenter.default()
            .publisher(for: AppearancePreference.systemChangedNotification)
            .receive(on: RunLoop.main)) { _ in
            // The app-scope observer re-resolves the tokens; this one
            // exists for the AppKit chrome only. Refreshing here too
            // makes the two orderless (both writes are guarded).
            ThemeStore.shared.refreshSystemAppearance()
            applyAppearance()
        }
        // G133 / G134: folders and Wispr Flow settings are per memory, so a
        // bank switch re-reads them and re-arms the watches.
        // G191, review B1 — Sleep let go of the pages (the SSE `sleep` event's `writing`): send any answer the
        // backend refused while it held them.
        .onChange(of: ProjectWriteGate.blocked(store.status.value)) { was, now in
            if was && !now {
                // 2026-10-19: a bookmark sync refused while Sleep wrote (409) is read again now, so the
                // answer about it — held, awaiting that sync — lands without waiting for the next bookmark.
                Task {
                    await browserWatcher.catchUp()
                    await saveWhy.retryHeld()
                }
            }
        }
        // …and when the backend first answers after launch (a launch-time retry can beat its start).
        .onChange(of: store.status.value == nil) { _, missing in
            if !missing { Task { await saveWhy.retryHeld() } }
        }
        // G181 phase 3 — the server answers again: what the readers left waiting goes first.
        .onChange(of: store.isConnected) { _, connected in
            if connected { Task { await APIClient.shared.flushOutbox() } }
        }
        // G191 live — back from System Settings: a browser whose file was refused when its watch was armed
        // (Safari before Full Disk Access) is armed again now that it can be read. The watcher also looks
        // every few seconds while one is refused, for a grant made without coming back here.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            browserWatcher.refreshAccess()
        }
        .onChange(of: store.bank) { _, _ in
            Task { await localSources.reload() }
            // Round-4 D2 — the new memory gets the calendar too (a demo's 409 is said in words).
            Task { await calendarReader.bankChanged() }
            Task { await notesWatcher.bankChanged() }
            // G219 — the new memory gets the ticked lists too (a demo's 409 is said in words).
            Task { await remindersReader.bankChanged() }
            // G160 — the new memory gets the open groups too (its digest is its own).
            Task { await tabGroups.bankChanged() }
            // G71 — the new memory's YouTube history, past its own cursor.
            Task { await watchHistory.bankChanged() }
            // G154 (R-SR10) — the new memory's people get their Contacts sources too.
            Task { await contactsReader.bankChanged() }
            // G179 — the new memory's ticked conversations, past their own cursors.
            Task { await messages.bankChanged() }
            Task { await whatsApp.bankChanged() }
            Task { await telegram.bankChanged() }
            // Owner decision 5 (2026-10-16) — the new memory's bookmarks, past its own "what was synced".
            Task { await browserWatcher.bankChanged() }
        }
        .onAppear { launch() }
    }

    /// `ContentView` with every app-level model in its environment.
    private var environed: some View {
        ContentView()
            .environment(graphVM)
            .environment(inboxVM)
            .environment(sleepVM)
            .environment(sleepEngineVM)
            .environment(appRouter)
            .environment(tour)
            .environment(provenanceRouter)
            .environment(provenanceCache)
            .environment(projectsCache)
            .environment(backlogCache)
            .environment(channelItemsCache)
            .environment(videoStateCache)
            .environment(exploreCache)
            .environment(readingSitesCache)
            .environment(banksVM)
            .environment(feedVM)
            .environment(contributorsVM)
            .environment(connectionsVM)
            .environment(usageVM)
            .environment(store)
            .environment(findModel)
            .environment(homeSearch)
            .environment(browserWatcher)
            .environment(saveWhy)
            .environment(syncActivity)
            .environment(localSources)
            .environment(calendarReader)
            .environment(notesWatcher)
            .environment(remindersReader)
            .environment(tabGroups)
            .environment(watchHistory)
            .environment(contactsReader)
            .environment(messages)
            .environment(whatsApp)
            .environment(telegram)
            .environment(traceRecorder)
            .environment(loginItems)
            .environment(backendAgent)
            .environment(updates)
            .environment(intakeRouter)
            .environment(setupRunner)
            .environment(inventory)
            .environment(exportWaits)
            .environment(menuBarManager)
    }

    /// What the window's `.onAppear` runs (unchanged; moved out of `body` for the type checker).
    private func launch() {
        // G130 R5: the View menu's CommandGroup below already
        // owns bare ⌘=/⌘−/⌘0; this monitor exists only to catch
        // ⌘⇧= (what a US keyboard sends for "⌘+"), which no
        // single `keyboardShortcut` can express alongside ⌘=
        // without two "Zoom In" menu rows. Guarded so a second
        // `.onAppear` (e.g. the window closing and reopening —
        // see `enableFirstMouseAcceptance`'s own precedent a few
        // lines below) never stacks a second monitor.
        if zoomMonitor == nil {
            zoomMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
                guard let action = ZoomKeyRouter.action(
                    characters: event.charactersIgnoringModifiers ?? "",
                    modifiers: event.modifierFlags
                ) else { return event }
                switch action {
                case .zoomIn: CicadaTheme.zoomIn()
                case .zoomOut: CicadaTheme.zoomOut()
                case .reset: CicadaTheme.resetZoom()
                }
                return nil
            }
        }
        // G181 phase 3 — on a server this Mac runs no backend of its own (and never falls back to one).
        if !ServerConnection.current.isServer { backend.start() }
        // Arms the per-browser watches and catches up on anything
        // saved while the app was closed.
        browserWatcher.start(store: store)
        // G191 — off until the person turns it on (the Sources page → Browsers).
        saveWhy.attach(presenter: saveWhyPanel)
        saveWhy.start()
        bookmarkBubbles.isWanted = { [saveWhy, browserWatcher] channel in
            saveWhy.prefs.enabled && browserWatcher.isEnabled(channel)
        }
        bookmarkBubbles.onBubble = { [saveWhy, bookmarkBubbles] channel in
            saveWhy.bubbleSeen(channel: channel, frame: bookmarkBubbles.lastBubble?.bounds)
        }
        // 2026-10-19 — a click inside Chrome's own bubble is not leaving, unless it closed it (Done).
        saveWhy.bubbleOpen = { [bookmarkBubbles] in bookmarkBubbles.lastBubbleStillOpen() }
        // The split-brain rule: a held answer is sent only while the memory it was given in is active.
        saveWhy.activeBank = { [store] in store.bank }
        // The star on a page already saved opens that bookmark's answer, filled in — only when Automation
        // of Chrome is already allowed (never asked here; `SavedBookmarkLookup`).
        saveWhy.existing = { [store] channel in
            await SavedBookmarkLookup.live(channel: channel, items: store.sources.value ?? [])
        }
        saveWhy.onNamed = { [bookmarkBubbles] item in bookmarkBubbles.bookmarkNamed(item) }
        // G191 v7 — the person's earlier answers in the active memory rank the suggested reasons (nothing new stored).
        saveWhy.pastPicks = { [store] in SaveWhySuggest.picks(from: store.sources.value ?? []) }
        bookmarkBubbles.start()
        // G191 v3 — the app's own diff needs a "before" for each watched browser: read once now, so the
        // first bookmark after launch is named from the file without waiting for the backend.
        if saveWhy.prefs.enabled {
            Task {
                let browsers = await Task.detached { BrowserInventory.live() }.value
                await BookmarkFileDiff.shared.seed(channels: SaveWhySetup.channels(inventory: browsers)
                    .filter { browserWatcher.isEnabled($0) })
            }
        }
        // Review B1 — an answer held through a 409 or a restart goes out again now.
        Task { await saveWhy.retryHeld() }
        // Track I T5 — the one intake owns `store.intakeInFlight`
        // through its request counter, and the Dock's opens wait in
        // `DockOpenQueue` until this line attaches it (R-IA25).
        intakeRouter.attach(store: store)
        intakeRouter.attach(activity: syncActivity)
        appDelegate.opens.attach { [intakeRouter, appRouter] urls in
            appRouter.showMainWindow()
            intakeRouter.accept(urls: urls, from: .dock)
        }
        localSources.start(store: store)
        // R-FA11 — reads only if the person connected before and macOS still says yes. A reopened
        // window runs this again: `arm()` is guarded, so that costs one catch-up sync and nothing more.
        calendarReader.start()
        // Reads only if the person connected Notes before, and only while Notes is open.
        notesWatcher.start()
        // G219 — reads only if the person connected Reminders and ticked a list, and macOS still says yes.
        remindersReader.start()
        // G160 (R-SR3) — reads only if the person turned the tab-groups switch on.
        tabGroups.start()
        // G71 — reads only if the person turned the YouTube history switch on.
        watchHistory.start()
        // G154 (R-SR10) — reads only after Connect, and on launch only when the book moved or a day passed.
        contactsReader.start()
        // G179 — reads only the conversations this memory has ticked.
        messages.start()
        // G179 (2026-10-28) — reads only the WhatsApp chats this memory has ticked.
        whatsApp.start()
        // G218 — records only if the person turned traces on (the backend holds that choice; no answer, no recording).
        Task { await traceRecorder.start() }
        // R-IB22 — the export someone was waiting for arrived (a sniff
        // recognised its vendor): its wait, in the active memory, is done.
        intakeRouter.onVendorSniffed = { [exportWaits, store] vendor in
            exportWaits.clear(vendor: vendor, bank: store.bank)
        }
        // A tapped reminder opens the one intake idle for that vendor —
        // never a cycle (G125 R10). Queued until now on a cold launch.
        appDelegate.reminderTaps.attach { [intakeRouter, appRouter] vendor in
            appRouter.showMainWindow()
            intakeRouter.present(from: .reminder(vendor))
        }
        // When SleepViewModel observes a cycle finish (running ->
        // idle, no error), refresh the graph/topics layer in
        // place. Without this, Sleep finishes successfully but
        // Topics/Graph stay frozen on the pre-cycle snapshot
        // until the user restarts the app.
        sleepVM.onCycleCompleted = { [graphVM, inboxVM] in
            await graphVM.loadGraph()
            await inboxVM.loadInbox()
        }
        // Resolving an inbox item drops the menu-bar badge instantly
        // instead of waiting for the next 30s status poll.
        inboxVM.onResolved = { [menuBarManager] in
            await menuBarManager.refreshAfterAction()
        }
        // DR-42 (R-DI3) — ⌘Q inside an Undo window sends the held answer first.
        appDelegate.heldAnswer = { [store] in store.hasAnswerInFlight }
        appDelegate.sendHeldAnswer = { [store] in await store.sendHeldAndDrain() }
        // G139 final review: a reopened window re-reads the system
        // appearance rather than trusting the last one this scene saw.
        ThemeStore.shared.refreshSystemAppearance()
        // Ensure the main window is key so TextFields can accept input.
        if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
            syncWindowChrome(window, mode: appColorScheme)
            enableFirstMouseAcceptance(for: window)
            switch LaunchState.shared.firstWindowAction() {
            case .show:
                window.makeKeyAndOrderFront(nil)
            case .close:
                // R-OB18 — a login start: everything above ran (backend, watchers, menu bar, sync engine
                // — all app-level), so the window can go the way a closed last window goes.
                window.orderOut(nil)
                DispatchQueue.main.async { window.close() }
            }
        }
        // Read as the menu opens, so "requested 2 hours ago" is true then.
        menuBarManager.exportWaitLines = { [exportWaits, store] in
            exportWaits.active(bank: store.bank).map { ExportWaits.menuLine($0, now: Date()) }
        }
        // Sleep page v5 — while a run is paused, every door routes to the Sleep page (only its Continue
        // resumes the run); the menu bar reads the same words the page's doors do.
        sleepVM.onPausedDoor = { [appRouter] in appRouter.routeToSleep() }
        // The doors read the paused run's record and the batch size even when the Sleep page was never
        // opened: a pause that appears, changes or clears refetches the status app-wide, and a bank
        // switch empties the VM's per-bank caches (the queue's titles, runs' details) and rereads.
        store.onSleepPausedChanged = { [sleepVM] in
            Task { @MainActor in
                await sleepVM.refreshStatus()
                if sleepVM.runOptions == nil { await sleepVM.loadRunOptions() }
            }
        }
        store.onBankChanged = { [sleepVM] in Task { @MainActor in await sleepVM.bankChanged() } }
        menuBarManager.sleepDoor = { [sleepVM] in sleepVM.door }
        // Before `setup`, so a waiting worm's status item is never shown, not even for a frame.
        menuBarManager.setIntroPhase(MenuBarIntro.phase())
        // G218 — the menu says whether traces record (read as it opens) and pauses, resumes or forgets through the
        // one recorder; off, nothing shows.
        menuBarManager.traceMenu = { [traceRecorder] in TraceMenuState.of(traceRecorder) }
        menuBarManager.onTraceAction = { [traceRecorder] action in
            Task { @MainActor in
                switch action {
                case .pause(let choice): await traceRecorder.pause(choice)
                case .resume: await traceRecorder.resume()
                case .forget: try? await traceRecorder.forget(minutes: 15)
                }
            }
        }
        menuBarManager.setup(
            onOpenApp: { [appRouter] in appRouter.showMainWindow() },
            onRunSleep: {
                await sleepVM.triggerManually()
                await menuBarManager.refreshAfterAction()
            },
            onSaveClipboardURL: {
                await menuBarManager.saveClipboardURL()
            },
            // R-IA26 — "Import a file…": bring the window forward and
            // open the intake idle, like File → Import….
            onImportFile: { [intakeRouter, appRouter] in
                appRouter.showMainWindow()
                intakeRouter.present(from: .menuBar)
            }
        )
        // G191 v2 — the developer-only preview (hidden unless its defaults key is set; never in a release).
        menuBarManager.onPreviewSaveWhy = { [saveWhy] channel in Task { await saveWhy.preview(channel: channel) } }
        // G191 v3 — Bookmarks…: the history under the status item; a row opens its page in the Feed.
        menuBarManager.onShowBookmarks = { [bookmarkHistory, store, appRouter] anchor in
            bookmarkHistory.toggle(store: store, anchor: anchor) { row in
                appRouter.routeToBookmark(row.mediaEntityId)
            }
        }
        // R-HO16 — the switch, applied at launch too.
        menuBarManager.setVisible(menuBarVisible)

        // Drive the menu-bar bookworm's stage dots live during a
        // running cycle (1s cadence), separate from the coarse 30s
        // poll below. applySleep only touches the sleep sub-struct so
        // the two never conflict.
        sleepVM.onStatusChanged = { next in
            menuBarManager.applySleep(next)
        }

        // The menu-bar bookworm is now driven by the Store's status
        // snapshot (SSE-pushed + refreshed on every version bump)
        // instead of a 30s poll. The Store tracks the sleep
        // running -> idle edge itself and hands us the timestamp
        // that makes the worm `digest`.
        store.onStatus = { [menuBarManager] snapshot, justFinishedAt in
            menuBarManager.apply(snapshot: snapshot, justFinishedAt: justFinishedAt)
        }

        // Disk first (instant frame), network second, then live.
        Task { @MainActor in
            await store.bootstrap()
            // The doors' "saving every N" reads the person's choice, not a fallback.
            await sleepVM.loadRunOptions()
        }
    }

    /// One place the resolved mode reaches the tokens and the AppKit chrome —
    /// a preference change and a system flip both land here.
    private func applyAppearance() {
        let mode = appColorScheme
        // Owner 2026-10-26 — a pointer's choice cross-fades the window; a key press switches in one frame (DR-60).
        withAnimation(AppearanceMotion.current()) { CicadaTheme.mode = mode }
        if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
            syncWindowChrome(window, mode: mode)
        }
    }

    /// Keeps the native AppKit window chrome (titlebar material + background)
    /// in lockstep with the SwiftUI theme. NSWindow isn't SwiftUI-observed,
    /// so this must be called explicitly on launch and again on every toggle
    /// (see the `.onChange(of: colorSchemeRaw)` above).
    ///
    /// A transparent titlebar + a matching window background makes the bar
    /// read as a continuation of the app's content on every page instead of
    /// the default gray macOS titlebar material. (A per-page content
    /// background can't recolor window chrome — that was the failed earlier
    /// attempt that also stretched the Inbox window.)
    private func syncWindowChrome(_ window: NSWindow, mode: AppColorScheme) {
        window.titlebarAppearsTransparent = true
        switch mode {
        case .dark:
            window.appearance = NSAppearance(named: .darkAqua)
        case .light:
            window.appearance = NSAppearance(named: .aqua)
        }
        // G137 R-M10: the one AppKit surface that paints a theme colour reads
        // the token — the hand-copied RGB that was here went stale the moment
        // the neutrals moved. The band takes the rail's surface: band and rail
        // are one frame around the page panel (owner 2026-10-07).
        window.backgroundColor = CicadaTheme.titlebarBackground(for: mode)
    }

    /// Reparents the window's existing (SwiftUI-owned) content view under a
    /// `FirstMouseAcceptingView` wrapper exactly once, preserving frame and
    /// autoresizing so nothing visually shifts, so native controls register
    /// their first click even when the window isn't key yet. Idempotent: a
    /// second call sees `window.contentView` already wrapped and no-ops.
    private func enableFirstMouseAcceptance(for window: NSWindow) {
        guard let hostedContent = window.contentView,
              !(hostedContent is FirstMouseAcceptingView)
        else { return }
        let wrapper = FirstMouseAcceptingView(frame: hostedContent.frame)
        wrapper.autoresizingMask = [.width, .height]
        hostedContent.frame = wrapper.bounds
        hostedContent.autoresizingMask = [.width, .height]
        window.contentView = wrapper
        wrapper.addSubview(hostedContent)
    }
}
