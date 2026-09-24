import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ContentView: View {
    /// Home is the front door (G108, R-IB2); a stored selection still wins.
    @State private var selectedTab: AppTab = .home
    /// Reopen where the user left off. Always read back through
    /// `AppTab.restored(from:)`: this string can name a tab that no longer
    /// exists (G68 retired five of them).
    @AppStorage("cicada.selectedTab") private var selectedTabRaw = AppTab.home.rawValue
    /// R-DS15 — per viewer: the icon rail (default) or the labelled sidebar.
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    // G117 / Track I part b (spec decision 14) — the Welcome: one screen
    // (found on this Mac, the ticks as consent, Start into Home) replacing the
    // four-step first-run sheet. Still gated per-bank (`OnboardingState`, R5)
    // rather than the old machine-global `hasSeenConnectGuide` flag: switching
    // to a fresh bank must show it again even on a Mac that already onboarded
    // a different one. `FirstRunGate` still decides, and unknown is still
    // never empty. Settings → Agents keeps the long-form wiring.
    @State private var showFirstRun = false
    /// First run, or Settings → General's *Run setup again* (R-IB16).
    @State private var welcomeMode: OnboardingMode = .firstRun
    /// G136 — the ⌘K find palette (Find, with Ask as a mode; round-3 design
    /// §3). An overlay on this root, not a sheet (A11).
    @State private var paletteOpen = false
    /// A palette saved-item row previews the item in place (design §3.3).
    @State private var previewItem: MediaFeedItem?
    /// "Switch to light/dark" writes the key `CicadaApp` already observes.
    @AppStorage(ThemeStore.defaultsKey) private var colorSchemeRaw = AppColorScheme.dark.rawValue
    @Environment(FindPaletteModel.self) private var find
    /// R-IB5 — ⌘K on Home focuses this field instead of opening the overlay.
    @Environment(HomeSearch.self) private var homeSearch
    /// "Switch to <bank>" makes `BankSwitcher`'s own call (R-SU13).
    @Environment(BanksViewModel.self) private var banksVM

    @Environment(GraphViewModel.self) private var graphVM
    @Environment(InboxViewModel.self) private var inboxVM
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    /// G126 R9 — consumes a Settings → Integrations "Import in Feed →"
    /// hand-off by switching the rail's own selection.
    @Environment(AppRouter.self) private var router
    /// Track I T5 — the one intake: every file dropped on this window lands here.
    @Environment(IntakeRouter.self) private var intake
    /// G118 slice 2 — drives the Reader inspector below; a bank switch
    /// closes it and empties the cache (R-PU26).
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(ProvenanceCache.self) private var provenanceCache
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// True while a file is dragged over the window — shows the drop veil (I1).
    @State private var dropTargeted = false

    var body: some View {
        overlayLayers
        // No `.task { load() }` here: `graphVM`/`inboxVM` are thin
        // projections over `Store.graph`/`Store.inbox` (§5.5). The Store
        // hydrates both from disk and refreshes them itself
        // (`store.bootstrap()`, wired in `CicadaApp`'s `.onAppear`); the VMs
        // pick up every subsequent change reactively (`GraphViewModel`'s
        // `observeStore()`; `InboxViewModel.items` reads the snapshot
        // directly), so there's nothing left for ContentView to kick off.
        // R6 — still reads Store snapshots only, no extra fetch. But it can no
        // longer decide on `.onAppear` alone: `store.bootstrap()` is async, so
        // at this point `store.bank` is usually still the placeholder
        // `"default"` and `store.graph` is unloaded. Deciding there asked
        // `isOnboarded` about the wrong bank and read "not loaded" as "empty",
        // which put the sheet on top of an onboarded bank's real data on every
        // cold launch. `FirstRunGate` holds the rule (unknown is never empty);
        // this view just re-asks it whenever an input lands.
        .onAppear {
            selectedTab = AppTab.restored(from: selectedTabRaw)
            evaluateFirstRun()
            intake.welcomeActive = showFirstRun
        }
        // DR-42 (R-DI3) — the window closing sends a held answer now; the app lives on in the menu bar.
        .onDisappear { Task { await store.flushHeld() } }
        // R-IB15 — while the Welcome shows, every arrival is staged on it.
        .onChange(of: showFirstRun) { _, showing in intake.welcomeActive = showing }
        // The roster resolving the active bank, and the graph snapshot landing
        // (from the on-disk cache or the network), are the two events that turn
        // an unknown input into a known one.
        .onChange(of: store.bank) { _, _ in evaluateFirstRun() }
        // G118 slice 2 (R-PU26) — the Reader and its cache belong to no bank:
        // episode ids restart every day in every bank, so a switch closes the
        // Reader and forgets every cached document rather than show another
        // bank's conversation under this one.
        // R-DI19 — and the Inbox's open question and tab go with it: ids repeat across banks.
        .onChange(of: store.bank) { _, _ in
            provenance.close()
            provenanceCache.reset()
            inboxVM.resetColumns()
        }
        // A cached hover preview has no validator, so any change to the
        // bank's episodes or entities forgets them (final review): `/inbox`
        // ETags over inbox + entities + episodes, so its snapshot landing a
        // new value is the one Store signal that covers an episode rewritten
        // in place (G104) as well as a page re-enriched; the graph covers
        // entities on its own. A 304 leaves `loadedAt` alone, so an idle
        // sync never empties the cache.
        .onChange(of: store.inbox.loadedAt) { _, _ in provenanceCache.forgetSpans() }
        .onChange(of: store.graph.loadedAt) { _, _ in provenanceCache.forgetSpans() }
        .onChange(of: store.banks.loadedAt) { _, _ in evaluateFirstRun() }
        .onChange(of: store.graph.loadedAt) { _, _ in evaluateFirstRun() }
        .onChange(of: selectedTab) { _, newValue in
            selectedTabRaw = newValue.rawValue
            // Bug 3 / G108 — a different tab drops the entity card's stale
            // "go deeper" trail (the currently-open card, if any, is left
            // alone; only its click-through history is cleared).
            graphVM.resetNavigationHistory()
        }
        .onChange(of: router.pendingPalette) { _, _ in consumePaletteRequest() }
        // R-SU5 — the instant tier is rebuilt off the main actor whenever an
        // input moves, open or not, so the first ⌘K never waits on a build.
        .background { FindIndexTask() }
        // G126 R9 — Integrations is a page of the Settings panel (DR-33), a
        // view that cannot flip `selectedTab` itself; it stages a tab on the
        // shared `AppRouter` and this view is the one that actually switches.
        // Leaving for a page closes the panel first (R-DS24): General's *Show
        // setup checklist* writes `pendingTab` directly, not through a router
        // hand-off, and would otherwise change the page under a panel that
        // stays up.
        .onChange(of: router.pendingTab) { _, newTab in
            guard let newTab else { return }
            router.closeSettings()
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = newTab }
            router.pendingTab = nil
        }
        // G139 — Settings → You → "Show on graph": the tab switch above and
        // the reveal here are staged together by `routeToEntity`.
        .onChange(of: router.pendingRevealEntity) { _, id in
            guard id != nil, let id = router.consumeRevealEntity() else { return }
            graphVM.revealEntity(id: id)
        }
        // G117 — Settings → General's "Run setup again" hand-off. The panel's
        // pages cannot flip `showFirstRun` themselves (same reason
        // `pendingTab` exists above), so `requestFirstRun` closes the panel
        // and stages this flag on the shared `AppRouter`.
        .onChange(of: router.pendingFirstRun) { _, isPending in
            guard isPending else { return }
            welcomeMode = .rerun
            withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) { showFirstRun = true }
            router.pendingFirstRun = false
        }
        // G118 slice 2 (P5) — an evidence chip inside the palette's Ask mode
        // opens the Reader, which lives on THIS window; the palette steps
        // aside so the person sees the sentence instead of an overlay
        // covering it (the Ask sheet did the same before G136).
        .onChange(of: provenance.revision) { _, _ in if paletteOpen { closePalette() } }
        .sheet(item: $previewItem) { item in
            FeedItemPreviewSheet(item: item)
        }
    }

    /// The two layers that cover the whole window — the ⌘K palette and the Settings panel
    /// (DR-33) — split out of `body` for the reason `windowLayers` is: one modifier chain
    /// holding both passed what the type checker solves in reasonable time.
    private var overlayLayers: some View {
        windowLayers
        // G136 — ⌘K is a menu command (`FindCommands`, A6) that stages a
        // request on the router; `PaletteToggle` ignores it while the Settings
        // panel is up (R-DS21).
        .overlay {
            if paletteOpen {
                FindPalette(model: find, open: openFind, close: closePalette)
            }
        }
        // DR-33 — Settings is a panel inside this window, above every other layer; the shell
        // under it is inert (R-DS21).
        .overlay { if router.settingsOpen { SettingsPanel() } }
        // R-DS24 — the palette never shares the window with the panel, and the intake's overlay
        // (a drop, the Dock) takes the window back from it.
        .onChange(of: router.settingsOpen) { _, open in if open && paletteOpen { closePalette() } }
        .onChange(of: intake.isOverlayPresented) { _, shown in if shown { router.closeSettings() } }
    }

    /// The shell and its window-wide layers (the drop veil, the Welcome,
    /// the one drop target), split out of `body`: with the Welcome's layer the
    /// single modifier chain passed what the type checker solves in reasonable
    /// time.
    private var windowLayers: some View {
        // Direction D's shell (DR-22, R-DS13): the rail, then the page. The rail draws above its
        // sibling so its tooltips float over the page instead of under it.
        HStack(spacing: 0) {
            NavRail(
                selectedTab: $selectedTab,
                labelled: labelledSidebar,
                inboxCount: inboxVM.pendingCount,
                isSleeping: store.status.value?.sleep.status == "running" || sleepVM.isRunning,
                needsAttention: connectionsVM.needsAttention
            )
            .zIndex(1)
            // G118 slice 2 (design §4.4) — the Reader opens BESIDE whatever is showing, never over
            // it: the entity card stays up, so a belief and the sentence it came from are on screen
            // together. Content, not chrome, so it is never glass (R-M5).
            // DR-31 / R-DI6 — the Reader is a column beside whatever is open, sized first; the page gets
            // the rest. It replaced a trailing `.inspector`, whose width was not the page's to give.
            // The Inbox hosts its own Reader, as its third progressive column (R-DI6, §5.3).
            ShellReaderHost(showsReader: provenance.isPresented && selectedTab != .inbox,
                            navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) {
                detailContent
                    .background(CicadaTheme.background)
                    // A rolled-back mutation (or a refresh that failed with
                    // nothing on screen) posts `store.toast`; show it at the
                    // bottom of whatever page is open (§5.4).
                    .overlay(alignment: .bottom) { toastBanner }
            } reader: {
                ReaderColumn()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .toolbar {
            ShellToolbar(labelled: $labelledSidebar, help: .page(selectedTab),
                         chrome: ShellChrome(welcomeShowing: showFirstRun, settingsOpen: router.settingsOpen))
        }
        // No `.id(colorSchemeRaw)` here any more. Keying this subtree on the
        // mode string used to be what repainted it, because the tokens were
        // static reads SwiftUI could not track — but it rebuilt the whole
        // rail/page tree on every flip, which tears down and reloads the
        // graph's WKWebView and loses its layout. `CicadaTheme.mode` is now
        // backed by an `@Observable` store, so each view that reads a token
        // subscribes to the mode itself and repaints on its own.
        // The Welcome is an overlay, not a modal sheet, so without this the
        // shell under it stays live: Home's field takes keyboard focus and
        // swallows typing, Tab and VoiceOver reach the hidden rail and cards,
        // ⌘1–7 switch a hidden tab, and in rerun mode Home's Esc answers before
        // the Welcome's (I-b final review, finding 3). Inert while it shows.
        // R-DS25 — the page under the Settings panel never answers ⌘F.
        .environment(\.pageFindSuppressed, router.settingsOpen)
        // R-DS21 — the Settings panel is modal the same way: ⌘1–7 and page controls are inert.
        .disabled(showFirstRun || router.settingsOpen)
        .accessibilityHidden(showFirstRun || router.settingsOpen)
        // Track I T5 (R-IA24) — drop anywhere: one window-level target, the veil
        // while a file hovers, the overlay while the router shows it.
        .overlay { IntakeLayer(dropTargeted: dropTargeted && !showFirstRun) }
        // Track I part b (spec decision 14, R-IB11) — the Welcome is a full-window
        // layer, not a sheet: the shell underneath is already on Home, so
        // Start reveals it. It sits above the intake layer, which stays unused
        // while it shows (R-IB15), and INSIDE the window's one drop target below:
        // a modifier's drop region is the view it wraps, so an overlay stacked
        // after `.onDrop` would take a drag over the Welcome without delivering it.
        // A panel opened from the Welcome (`FoundRow`'s settings link) must own Esc alone.
        .overlay { welcomeLayer.disabled(router.settingsOpen) }
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            let origin: IntakeOrigin = showFirstRun ? .welcome : .windowDrop
            IntakeDrop.load(providers) { intake.accept(urls: $0, from: origin) }
            return true
        }
    }

    /// The Welcome over the whole window (R-IB11), or nothing.
    @ViewBuilder
    private var welcomeLayer: some View {
        if showFirstRun {
            WelcomeView(mode: welcomeMode, dropTargeted: dropTargeted,
                        onShowHome: {
                            withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) {
                                selectedTab = .home
                                showFirstRun = false
                            }
                        },
                        onClose: {
                            withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) { showFirstRun = false }
                        })
                .transition(.opacity)
        }
    }

    /// G117 — the one place the Welcome is raised automatically.
    /// `store.banks.value != nil` is the honest "the bank is resolved" signal:
    /// `Store` has no `hydrated` flag, and `hydrate()` sets `bank` from the
    /// roster it just read (`Store.swift`, `roster.value.active`), so the
    /// roster snapshot having a value is exactly the moment `store.bank` stops
    /// being the placeholder. A hydrated on-disk cache counts as loaded for
    /// both roster and graph — rendering the first frame from disk is the
    /// point of that cache. Never lowers `showFirstRun`: dismissal belongs to
    /// the Welcome's Start, Set up later, demo and (rerun) Close, and a
    /// re-evaluation firing under an open Welcome must not close it.
    private func evaluateFirstRun() {
        guard !showFirstRun else { return }
        if FirstRunGate.shouldShow(
            bankResolved: store.banks.value != nil,
            isOnboarded: OnboardingState.isOnboarded(bank: store.bank),
            graphLoaded: store.graph.value != nil,
            graphIsEmpty: store.graph.value?.nodes.isEmpty ?? false
        ) {
            welcomeMode = .firstRun
            showFirstRun = true
        }
    }

    private func consumePaletteRequest() {
        guard let request = router.consumePalette() else { return }
        switch PaletteToggle.outcome(for: request, isOpen: paletteOpen, firstRunShowing: showFirstRun,
                                     homeVisible: selectedTab == .home, settingsOpen: router.settingsOpen) {
        case .open(let prefill, let mode):
            find.present(prefill: prefill, mode: mode)
            // DR-60: ⌘K never animates — the palette arrives in one frame (R-DS17).
            paletteOpen = true
        case .close:
            closePalette()
        case .focusHome(let prefill, let mode):
            homeSearch.focus(prefill: prefill, mode: mode)
        case .ignore:
            break
        }
    }

    private func closePalette() {
        paletteOpen = false
        find.dismissed()
    }

    /// The one place a palette row becomes navigation (design §3.3). The
    /// palette has already closed itself; `.ask`, `.askedBefore` and
    /// `.settings` never arrive here (`FindPaletteModel.activate`).
    private func openFind(_ destination: FindDestination) {
        switch destination {
        case .entity(let id), .belief(let id, _):
            // Seam (Track P): a belief should also open the card on
            // Perspectives, scrolled to the claim — the card is Track P's.
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .graph }
            graphVM.revealEntity(id: id)
        case .entityInClusters(let id):
            router.pendingClustersEntity = id
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .clusters }
        case .feedItem(let id):
            if let item = store.sources.value?.first(where: { $0.mediaEntityId == id }) {
                previewItem = item
            } else {
                openFind(.entity(id: id))
            }
        case .openURL(let raw):
            if let url = URL(string: raw) { NSWorkspace.shared.open(url) }
        case .source(let id):
            router.routeToSourceDetail(id)
        case .conversations(let harness, let origin, let query):
            if let id = ConversationSource.sourceId(harness: harness, origin: origin,
                                                    rows: store.sourcesOverview.value ?? []) {
                router.pendingConversationQuery = query
                router.routeToSourceDetail(id)
            } else {
                withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .sources }
            }
        case .conversation(let target):
            // R-SU18 — the Reader lands on the best passage; the source's own
            // list, filtered to the title, stays one ⌥⏎ away (`.conversations`).
            provenance.open(FindReaderRoute.target(for: target.span, title: target.title, harness: target.harness))
        case .evidence(let span):
            // A belief's "where it was said" (R-SU18); offered only while
            // `FindReaderSeam.isAvailable`.
            provenance.open(FindReaderRoute.target(for: span))
        case .inbox(let id):
            router.pendingInboxItem = id
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .inbox }
        case .tab(let tab):
            withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = tab }
        case .action(let action):
            run(action)
        case .bank(let name):
            // `BankSwitcher.switchTo`'s own pair (R-SU13).
            Task { if await banksVM.activate(name) { await graphVM.loadGraph() } }
        case .settings, .ask, .askedBefore:
            break
        }
    }

    /// R-SU13 — the same calls the owning pages make.
    private func run(_ action: PaletteAction) {
        switch action {
        // `SleepControlRow`'s own call: trigger, then refresh what it changed.
        case .consolidate: Task { await sleepVM.triggerManually(); await store.refresh([.status, .channels]) }
        case .stopConsolidating: Task { await sleepVM.cancel() }
        case .zoomIn: CicadaTheme.zoomIn()
        case .zoomOut: CicadaTheme.zoomOut()
        case .actualSize: CicadaTheme.resetZoom()
        case .lightMode: colorSchemeRaw = AppColorScheme.light.rawValue
        case .darkMode: colorSchemeRaw = AppColorScheme.dark.rawValue
        }
    }

    /// Transient capsule for `store.toast`, auto-clearing after 4 s. Keyed on
    /// the message so a second toast restarts the timer instead of inheriting
    /// the first one's remaining time.
    @ViewBuilder
    private var toastBanner: some View {
        if let toast = store.toast {
            Text(toast)
                .font(CicadaTheme.font(size: 12, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(.horizontal, 16)
                .padding(.vertical, 9)
                // DR-9/DR-10: a floating surface — the floating ring, and one soft
                // shadow in light only (`Theme/Elevation.swift`).
                .floatingSurface(in: Capsule())
                .padding(.bottom, 22)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .task(id: toast) {
                    try? await Task.sleep(for: .seconds(4))
                    guard !Task.isCancelled else { return }
                    store.toast = nil
                }
        }
    }

    /// The graph view is never torn down by a tab switch (owner, 2026-09-03:
    /// "if I zoom in and change tab and go back, it should still be zoomed in
    /// to where I was"). A `switch` here rebuilt `GraphView`'s `WKWebView` on
    /// every return — a cold re-layout, the zoom reset, and the G109 "explosion
    /// on return". The graph stays mounted underneath, hidden and inert while
    /// another tab is showing; the other tabs are built on top as before.
    @ViewBuilder
    private var detailContent: some View {
        ZStack {
            GraphPage(selectedTab: $selectedTab)
                .opacity(selectedTab == .graph ? 1 : 0)
                .allowsHitTesting(selectedTab == .graph)
                .accessibilityHidden(selectedTab != .graph)
            if selectedTab != .graph {
                otherTabContent
            }
        }
    }

    @ViewBuilder
    private var otherTabContent: some View {
        switch selectedTab {
        case .home:
            // Rebuilt on a tab switch — a cheap SwiftUI tree, unlike the graph's
            // WKWebView; its field text lives in `HomeSearch`, so it survives (R-IB3).
            HomeView(open: openFind, selectedTab: $selectedTab)
        case .graph:
            EmptyView()
        case .clusters:
            TopicsView(selectedTab: $selectedTab)
        case .feed:
            FeedView(selectedTab: $selectedTab)
        case .sleep:
            // An entity chip in the consolidation history's expanded detail
            // navigates the same way an Ask citation (or a Sources
            // conversation row, below) does: land on the node, then show
            // its card.
            SleepView(selectedTab: $selectedTab) { entityId in
                withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .graph }
                graphVM.revealEntity(id: entityId)
            }
        case .inbox:
            InboxPage()
        case .sources:
            // An entity chip on a source page's conversation row navigates the
            // same way an Ask citation does (G123): land on the node, then
            // show its card.
            SourcesPageView { entityId in
                withAnimation(CicadaMotion.standard(reduceMotion: reduceMotion)) { selectedTab = .graph }
                graphVM.revealEntity(id: entityId)
            }
        }
    }
}

/// R-SU5 — keeps the palette's instant tier current. Its own view, so the
/// inputs it watches (the graph, the inbox, Sleep's status, the theme) move
/// this empty view when they change, never `ContentView`'s whole body.
///
/// Track I part b (R-IB4): one build, two readers — the palette's model builds
/// the index and Home's field installs the same value, so Home never pays for
/// a second build or drifts from what ⌘K finds.
private struct FindIndexTask: View {
    @Environment(Store.self) private var store
    @Environment(FindPaletteModel.self) private var find
    @Environment(HomeSearch.self) private var home

    var body: some View {
        Color.clear
            .frame(width: 0, height: 0)
            .accessibilityHidden(true)
            .task(id: QuickIndexInputs.token(store, askHistoryCount: find.ask.history.count)) {
                await find.rebuildIndex()
                home.model.install(find.index)
            }
    }
}
