import SwiftUI

/// The Sources page (G124) in progressive columns (Direction D, DS-3c; §10). G245 (ruling 78, owner 2026-11-24): with
/// nothing open it is one column of source cards, one shape for every source — what waits on the person first, then what
/// is connected, then what is not — under a find and the kinds (`SourcesRootList`), the header's one button *Check
/// connections*, and one quiet *Statistics* disclosure (who wrote your memory, the counts); opening a source narrows the
/// page to the same cards as rows, in the same order, and opens its standard page; a conversation's Reader is the third
/// column. Clicking Sources in the sidebar again returns here (`AppRouter.reselect`). No prices, no tokens anywhere
/// (the 2026-09-03 G124 ruling).
struct SourcesPageView: View {
    /// Entity chip → the app's existing entity navigation, threaded from `ContentView` like Ask citations.
    var onSelectEntity: ((String) -> Void)?

    init(onSelectEntity: ((String) -> Void)? = nil) {
        self.onSelectEntity = onSelectEntity
        let run = SourceReaderRun()
        _readerRun = State(initialValue: run)
        _check = State(initialValue: SourceStreamCheckModel(deps: .live(runReader: { try await run.run($0) })))
    }

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(ContributorsViewModel.self) private var contributorsVM
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var columns = ListColumns<SourcesSelection>()
    /// G217 — the sites an agent may read, for the accounts' per-site control (in memory, not a Store domain). G245: the
    /// app's one model (`CicadaApp`), so a caller outside this page reaches the same switches.
    @Environment(ReadingAgentModel.self) private var reading
    /// The browsers on this Mac (one Launch Services pass per appearance, never per body evaluation).
    @State private var browsers = BrowserInventory.empty
    @Environment(LocalSourceWatcher.self) private var localSources
    /// 2026-11-03 — the chat whose stored conversation the right-hand panel shows (a chat source's page).
    @State private var chatPanel = ChatPanelRouter()
    @State private var pageBack = SourcePageBack()
    /// Reading the web's switches (the master switch, the signed-in session, YouTube lists, Never explore, how the
    /// agent reads), in one sheet since D6 retired the Settings page (2026-10-22 fix round).
    @State private var showReadingSheet = false
    @Environment(ExploreCache.self) private var exploreCache
    @FocusState private var focus: ListFocus?
    /// The root's find, the card the keys moved to and the chosen kind. Only the root reads the words: `catalog` stays
    /// whole, so a hand-off (the palette, the notch's Yes, Sleep's *Open in Sources*) and the rows beside an open source
    /// reach every source, whatever was typed.
    @State private var rootState = SourcesRoot.State()
    /// The card at the top edge of the root's scroll view, so the root returns where it was when a source closes.
    @State private var rootTopCard: String?
    /// Off sources whose app is on this Mac (`SourceGrid.suggested`): one Launch Services pass per appearance.
    @State private var suggested: Set<String> = []
    /// G245 — `GET /sources/streams` (in memory; a 404 is "no streams yet", and every card is the catalogue row's).
    @Environment(SourceStreamsModel.self) private var sourceStreams
    /// G245 plan 3.3 — Check connections / Check now. Owned here, where the readers it runs are in the environment.
    @State private var check: SourceStreamCheckModel
    /// The closure the check runs a reader through, bound when the page appears (the readers are in the environment,
    /// which an initializer cannot read).
    @State private var readerRun: SourceReaderRun
    /// What this Mac says about the permissions a stream needs: preflights only, never a prompt (ruling 77).
    @State private var permissions: [MacPermission: Bool] = [:]
    /// Cards whose button is working.
    @State private var working: Set<String> = []
    /// G245 — the first-use acknowledgement a Connect or a switch asked for (`AppRouter.pendingConsent`), raised here
    /// because the notch's panel and a card cannot hold the sheet.
    @State private var consent: ReadingConsent?

    private var rows: [SourceOverview] { SourceOverview.gridOrder(store.sourcesOverview.value ?? []) }

    /// G217 — the one catalogue, every way in with its status (`SourceCatalog`).
    private var catalog: [SourceCatalogRow] {
        let overview = store.sourcesOverview.value ?? []
        let channels = store.channels.value ?? []
        let entries = SourceCatalog.entries(
            browsers: BrowserRows.shown(inventory: browsers, channels: channels),
            wisprPresent: SourceCatalog.wisprOffered
                && (localSources.wisprInstalled || channels.contains { $0.id == LocalSourceWatcher.wisprChannel }),
            hexPresent: localSources.hexInstalled, meetingFolders: localSources.folders,
            overview: overview, channels: channels)
        return SourceCatalog.rows(entries: entries, channels: channels, overview: overview,
                                  readableSites: reading.readableSites, localReaders: localReaders,
                                  savedListsOn: reading.savedListsOn, localAgent: agents.connectedLocally,
                                  savedListsRead: reading.savedListsRead,
                                  checked: chatChecks, notInstalled: localSources.missingApps,
                                  waitingOn: LocalReaders.waitingOnAccess(
                                      calendar: calendarReader, contacts: contactsReader, reminders: remindersReader,
                                      books: appleBooksReader, messages: messagesWatcher, whatsApp: whatsApp,
                                      voiceMemos: voiceMemosReader),
                                  suggested: suggested, browserReads: reading.settings?.browserReads ?? [:],
                                  watch: { browserWatcher?.state(for: $0) })
    }

    /// G245 — the root's cards: the catalogue's rows (their word, order and eyebrow count unchanged) with each source's
    /// streams beneath them. A 404 or a failed read leaves no streams, and every card is the catalogue row alone.
    private func resolvedStreams(_ catalog: [SourceCatalogRow]) -> ResolvedStreams {
        let app = StreamAppState(readers: localReaders,
                                 waitingOn: Dictionary(uniqueKeysWithValues: catalog.compactMap { row in
                                     row.waitingOn.map { (row.id, $0) } }),
                                 notInstalled: Set(catalog.filter(\.notInstalled).map(\.id)),
                                 siteSavesOn: SiteSavePrefs().noticedKeys(rows: catalog),
                                 siteSavesOff: SiteSavePrefs().turnedOff, permissions: permissions)
        return SourceStreamOverlay.resolve(sourceStreams.value, app: app, entries: catalog.map(\.entry))
    }

    /// 2026-11-03 — when each chat reader on this Mac last read its ticked chats (`ChatCheck`).
    private var chatChecks: [String: Date] {
        var out: [String: Date] = [:]
        out[WhatsAppWatcher.channel] = whatsApp?.check?.at
        out[MessagesWatcher.channel] = messagesWatcher?.check?.at
        return out
    }
    @Environment(WhatsAppWatcher.self) private var whatsApp: WhatsAppWatcher?
    @Environment(MessagesWatcher.self) private var messagesWatcher: MessagesWatcher?

    /// Tester readiness (2026-10-26) — whether an agent on this Mac is connected, polled while the page shows
    /// (`GET /agents/live`, ids and times only): a list read in the browser is Connected only with one.
    @State private var agents = AgentLiveProbe()

    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(ContactsReader.self) private var contactsReader: ContactsReader?
    @Environment(RemindersReader.self) private var remindersReader: RemindersReader?
    @Environment(AppleBooksReader.self) private var appleBooksReader: AppleBooksReader?
    @Environment(VoiceMemosReader.self) private var voiceMemosReader: VoiceMemosReader?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(WatchHistoryWatcher.self) private var watchHistory: WatchHistoryWatcher?
    @Environment(BrowserWatcher.self) private var browserWatcher: BrowserWatcher?
    @Environment(AppleNotesWatcher.self) private var notesWatcher: AppleNotesWatcher?
    @Environment(TraceRecorder.self) private var traceRecorder: TraceRecorder?

    /// Which of this Mac's readers are on (2026-10-23): a reader turned off here reads Off, whatever it synced before.
    private var localReaders: [String: Bool] {
        LocalReaders.on(calendar: calendarReader, contacts: contactsReader, tabGroups: tabGroups,
                        watchHistory: watchHistory, browsers: browserWatcher, notes: notesWatcher,
                        traces: traceRecorder, reminders: remindersReader)
            .merging([AppleBooksReader.channel: appleBooksReader?.enabled ?? false,
                      VoiceMemosReader.channel: voiceMemosReader?.enabled ?? false,
                      GoogleBooksKeyModel.id: GoogleBooksKeyModel.shared.connected]) { _, new in new }
    }

    var body: some View {
        let rows = self.rows
        let catalog = self.catalog
        let segments = ContributorShare.segments(contributorsVM.contributors)
        let streams = resolvedStreams(catalog)
        let cards = SourcesRoot.cards(rows: catalog, streams: streams)
        let openEntry: String? = { if case .entry(let id)? = columns.openId { id } else { nil } }()
        let narrow = SourcesRoot.narrow(rows: catalog, streams: streams, open: openEntry)
        let order = narrow.map { SourcesSelection.entry($0.id) }
        let detailOpen = columns.openId.map {
            SourcesModel.present(rows: rows, contributors: contributorsVM.contributors, catalog: catalog).contains($0)
        } ?? false
        let trailingOpen = provenance.isPresented || chatPanel.isPresented
        ProgressiveColumns(hasDetail: detailOpen, hasTrailing: trailingOpen,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: Eyebrow.text(Copy.sources, Copy.Catalog.eyebrow(SourceCatalog.onCount(catalog))),
                       horizontalPadding: !detailOpen && !trailingOpen ? plan.gutter : CicadaTheme.spacingXL) {
                // The page's top right holds only what applies to the whole list, and only while no source is open (a
                // source's page is about that source): the one button that asks every connection how it is doing
                // (plan 3.3). No add: every source is on the page (ruling 78 amends DR-75's Sources adopter).
                if !detailOpen { checkButton(catalog) }
            }
            .frame(maxWidth: detailOpen || trailingOpen ? .infinity : SourcesRootLayout.headerWidth(gutter: plan.gutter),
                   alignment: .leading)
        } list: { plan in
            if plan.listStyle == .wide {
                SourcesOverviewColumn(cards: cards,
                                      hasLoaded: store.sourcesOverview.value != nil || store.channels.value != nil,
                                      onOpen: { select($0) }, onSelectEntity: onSelectEntity, state: $rootState,
                                      onOpenByKey: { openByKey($0) }, onAct: { act($0, catalog: catalog) },
                                      busy: working, topCard: $rootTopCard)
                    .focused($focus, equals: .list)
            } else {
                SourcesListColumn(cards: narrow, style: plan.listStyle,
                                  selection: columns.openId, open: { select($0) },
                                  move: { move($0, order: order) }, escape: { escape() })
                    .focused($focus, equals: .list)
            }
        } detail: { plan in
            detail(plan, rows: rows, catalog: catalog, segments: segments)
        } trailing: { _ in
            // 2026-11-03 — a chat source's chat opens its stored conversation here, where the Reader opens (the two
            // never share the column: opening one closes the other).
            if let target = chatPanel.target {
                ChatConversationColumn(target: target, onClose: { closeChatPanel() })
                    .id("\(target.channel)|\(target.item.id)")
                    .focused($focus, equals: .reader)
            } else {
                ReaderColumn().focused($focus, equals: .reader)
            }
        }
        .background(CicadaTheme.bgBase)
        .environment(check)
        .environment(chatPanel)
        .environment(pageBack)
        .onChange(of: provenance.isPresented) { _, open in if open { chatPanel.close() } }
        .onChange(of: columns.openId) { _, _ in chatPanel.close() }
        // A hand-off asking for the reading switches (`pendingReadingSheet`) still lands here, whatever is open.
        .sheet(isPresented: $showReadingSheet, onDismiss: { Task { await reading.load() } }) {
            ReadingInBrowserSheet { showReadingSheet = false }
        }
        .onAppear { if router.pendingReadingSheet { router.pendingReadingSheet = false; showReadingSheet = true } }
        .onChange(of: router.pendingReadingSheet) { _, wants in
            if wants { router.pendingReadingSheet = false; showReadingSheet = true }
        }
        // G245 — the first-use acknowledgement a card's Connect (or, later, the notch) asked for, raised here.
        .sheet(item: $consent) { ask in
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { consent = nil }) {
                ReadingFirstUseSheet(model: reading, site: nil, label: label(of: ask), consent: ask) {
                    consent = nil
                    Task { await sourceStreams.refresh() }
                }
            }
        }
        .onAppear { takeConsent() }
        .onChange(of: router.pendingConsent) { _, _ in takeConsent() }
        .environment(agents)
        .task { bindReaders() }
        .task { await sourceStreams.refresh() }
        .onChange(of: store.channels.value) { _, _ in Task { await sourceStreams.refresh() } }
        .onChange(of: store.bank) { _, _ in check.reset() }
        .task { await probePermissions() }
        .task { await exploreCache.refresh() }
        .task { await GoogleBooksKeyModel.shared.refresh() }
        .task { await reading.loadSettings() }
        .task { await agents.run() }
        .task { browsers = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value }
        .task {
            let declined = Set(ConnectSuggestStore(defaults: .standard).memory.declined)
            suggested = await Task.detached(priority: .userInitiated) {
                SourceGrid.suggested(installed: { NSWorkspace.shared.urlForApplication(withBundleIdentifier: $0) != nil },
                                     declined: declined)
            }.value
        }
        // 2026-11-04 — an app removed since launch (Wispr Flow) reads Off · not installed as soon as the page opens.
        .task { await localSources.refreshInstalledApps() }
        // Track Z §7.1 — a Sleep spine's "Open in Sources ›" lands here with the tab switch.
        .onAppear { openPendingSource() }
        .onChange(of: router.pendingSourceDetail) { _, _ in openPendingSource() }
        // Sources v3 — Sources clicked again in the sidebar: back to the root, like a tab bar.
        .onRailReselect(.sources, router: router) { popToRoot() }
        .onChange(of: rows.map(\.id)) { _, _ in reconcile() }
        .onChange(of: catalog.map(\.id)) { _, _ in reconcile(); openPendingEntry() }
        // G231 — the notch's Yes lands on its source's entry (a browser's entry once this Mac's browsers are read).
        .onAppear { openPendingEntry() }
        .onChange(of: router.pendingCatalogEntry) { _, _ in openPendingEntry() }
        .onDisappear { router.pendingCatalogEntry = nil }
        .onChange(of: contributorsVM.contributors.map(\.author)) { _, _ in reconcile() }
    }

    @ViewBuilder
    private func detail(_ plan: ColumnPlan, rows: [SourceOverview], catalog: [SourceCatalogRow],
                        segments: [ContributorShare.Segment]) -> some View {
        let back = plan.listHidden ? catalog.count : nil
        switch columns.openId {
        case .entry(let id)?:
            if let row = catalog.first(where: { $0.id == id }) {
                SourceCatalogDetail(row: row, hiddenListCount: back, onShowList: { showList() },
                                    onClose: { close() }, onSelectEntity: onSelectEntity,
                                    resolved: resolvedStreams(catalog),
                                    onCheckNow: { Task { await runCheck([row.id], catalog: catalog) } })
                    .id(row.id)
                    .focusable()
                    .focusEffectDisabled()
                    .onExitCommand { escape() }
                    .focused($focus, equals: .detail)
            }
        case .source(let id)?:
            if let source = rows.first(where: { $0.id == id }) {
                // G136 R-SU18 — one identity per source, so a hand-off rebuilds the conversation list.
                SourceDetailView(source: source, hiddenListCount: back, onShowList: { showList() },
                                 onClose: { close() }, onSelectEntity: onSelectEntity)
                    .id(source.id)
                    .focusable()
                    .focusEffectDisabled()
                    .onExitCommand { escape() }
                    .focused($focus, equals: .detail)
            }
        case .contributor(let author)?:
            if let contributor = contributorsVM.contributors.first(where: { $0.author == author }) {
                ContributorDetailColumn(contributor: contributor, share: SourcesModel.share(of: author, in: segments),
                                        hiddenListCount: back, onShowList: { showList() }, onClose: { close() })
                    .id(author)
                    .focusable()
                    .focusEffectDisabled()
                    .onExitCommand { escape() }
                    .focused($focus, equals: .detail)
            }
        case nil:
            EmptyView()
        }
    }

    // MARK: - Paths (R-DL8)

    /// From the grid (STATE 0 → 1) the columns open on the drawer curve; a swap is instant. The list that appears takes
    /// the keys. A Reader the old detail opened closes with it (DR-29).
    private func select(_ selection: SourcesSelection) {
        let change = {
            columns.open(selection)
            if provenance.isPresented { provenance.close() }
        }
        if columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        DispatchQueue.main.async { focus = .list }
    }

    /// ROR-7 — ⏎ in the grid's field: the same open as a tile's click, with no animation (DR-60).
    private func openByKey(_ selection: SourcesSelection) {
        Instant.run {
            columns.open(selection)
            if provenance.isPresented { provenance.close() }
        }
        DispatchQueue.main.async { focus = .list }
    }

    private func move(_ delta: Int, order: [SourcesSelection]) {
        Instant.run {
            guard let next = columns.neighbour(delta, in: order) else { return }
            columns.open(next)
            if provenance.isPresented { provenance.close() }
        }
    }

    /// DR-28 — the Reader (or a chat's panel), then the detail (back to the grid).
    private func escape() {
        Instant.run {
            if chatPanel.isPresented {
                chatPanel.close()
                return
            }
            switch columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeDetail: if !pageBack.run() { columns.close() }
            case .none: break
            }
        }
    }

    private func close() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            chatPanel.close()
            columns.close()
        }
    }

    /// A pointer close of the chat panel slides it out on the columns' curve (DR-61); Esc closes it instantly.
    private func closeChatPanel() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { chatPanel.close() }
    }

    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if chatPanel.isPresented { chatPanel.close() }
            else if provenance.isPresented { provenance.close() } else { columns.close() }
        }
    }

    /// Sources v3 — the sidebar's Sources clicked while Sources shows: the Reader and the detail close together. A
    /// pointer click closes on the columns' curve; the ⌘ shortcut never animates (DR-60).
    private func popToRoot() {
        // The sidebar's re-click clears the words too, even with nothing open: the root at rest, like a tab bar.
        rootState.clearFind()
        guard SourcesModel.popsToRoot(detailOpen: columns.openId != nil,
                                      readerOpen: provenance.isPresented || chatPanel.isPresented) else { return }
        let change = {
            provenance.close()
            chatPanel.close()
            columns.close()
        }
        router.popToRoot(reduceMotion: reduceMotion, change)
    }

    private func reconcile() {
        columns.reconcile(present: SourcesModel.present(rows: rows, contributors: contributorsVM.contributors,
                                                        catalog: catalog))
    }

    /// Track Z §7.1 — a source id that no longer resolves leaves the grid showing rather than guessing a neighbour.
    /// G217 — an overview id lands on the catalogue entry that speaks for it, when one does.
    private func openPendingSource() {
        guard let id = router.consumeSourceDetail(), let row = rows.first(where: { $0.id == id }) else { return }
        let entry = catalog.first { SourceCatalog.overviewRow(for: $0.entry, in: [row]) != nil }
        rootState.clearFind()   // Whoever sent the person here did not ask for the words left in the field.
        Instant.run { columns.open(entry.map { .entry($0.id) } ?? .source(id)) }
    }

    /// G231 — a catalogue entry staged by the notch's Yes, opened once it is in the list (kept staged until then, and
    /// dropped when the page goes, so it never opens long after the click).
    private func openPendingEntry() {
        guard let id = router.pendingCatalogEntry, catalog.contains(where: { $0.id == id }) else { return }
        router.pendingCatalogEntry = nil
        rootState.clearFind()
        Instant.run { columns.open(.entry(id)) }
    }

    // MARK: - Check connections and a card's one button (G245, plan 3.1/3.3, section 7)

    /// The header's one button. While a check runs it says so and waits; after one it says when, quietly beside it (what
    /// each stream ended in is on the source's page). A check never prompts for anything.
    @ViewBuilder
    private func checkButton(_ catalog: [SourceCatalogRow]) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if let failure = check.failure {
                Text(failure).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning).lineLimit(1)
            } else if let at = check.lastCheckedAt, !check.isChecking {
                Text(Copy.Streams.checkedAgo(SourceCatalog.ago(at, now: Date())))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
            NeutralButton(title: check.isChecking ? Copy.Streams.checkingConnections : Copy.Streams.checkConnections,
                          size: .compact, isDisabled: check.isChecking) {
                Task { await runCheck([], catalog: catalog) }
            }
        }
    }

    /// Check `sources` (none is every source): the app's readers run now, the backend asks the services, and the answer
    /// goes into the streams cache, so every card and page redraws from it.
    private func runCheck(_ sources: [String], catalog: [SourceCatalogRow]) async {
        bindReaders()
        let current = resolvedStreams(catalog)
        await check.check(sources: sources, current: current,
                          resolve: { SourceStreamOverlay.resolve($0, app: streamApp(catalog), entries: catalog.map(\.entry)) },
                          publish: { sourceStreams.apply($0) })
        await sourceStreams.refresh()
    }

    private func streamApp(_ catalog: [SourceCatalogRow]) -> StreamAppState {
        StreamAppState(readers: localReaders,
                       waitingOn: Dictionary(uniqueKeysWithValues: catalog.compactMap { row in row.waitingOn.map { (row.id, $0) } }),
                       notInstalled: Set(catalog.filter(\.notInstalled).map(\.id)),
                       siteSavesOn: SiteSavePrefs().noticedKeys(rows: catalog),
                       siteSavesOff: SiteSavePrefs().turnedOff, permissions: permissions)
    }

    /// The card's one button. A needs-you card names its fix: access and sign-in are given on the source's page (its
    /// permission row, its sign-in), so those open it; Try again runs that source's check; Connect your AI opens Agents.
    /// A card not connected runs the one connect plan (`SourceConnect.plan`), the same the notch's Yes will.
    private func act(_ card: SourcesRoot.Card, catalog: [SourceCatalogRow]) {
        switch card.fix {
        case .tryAgain?:
            working.insert(card.id)
            Task { await runCheck([card.id], catalog: catalog); working.remove(card.id) }
        case .connectYourAI?:
            router.routeToAgents()
        case .signIn?, .giveAccess?:
            select(.entry(card.id))
        case nil:
            guard card.connectable else { return select(.entry(card.id)) }
            connect(card.row)
        }
    }

    private func connect(_ row: SourceCatalogRow) {
        working.insert(row.id)
        Task { @MainActor in
            defer { working.remove(row.id) }
            await reading.loadSettings()
            let state = SourceConnect.State(row: row, reading: reading,
                                            siteSavesOn: SiteSavePrefs().noticedKeys(rows: [row]),
                                            readersOn: localReaders, permissions: permissions)
            let plan = SourceConnect.plan(row.entry, state)
            // A reader one click starts is started here, the way its own page's Connect does (macOS's prompt follows).
            let starter = ReaderStarter(calendar: calendarReader, contacts: contactsReader, notes: notesWatcher,
                                        voiceMemos: voiceMemosReader, books: appleBooksReader, browsers: browserWatcher)
            let deps = SourceConnect.Deps.live(
                reading: reading, router: router,
                noticeSaves: { site in
                    SiteSavePrefs().setConnected(site, true)
                    NotificationCenter.default.post(name: SiteSaveSwitches.changed, object: nil)
                },
                startReader: { await starter.start($0) })
            let outcome = await SourceConnect.run(plan, entry: row.id, deps: deps)
            if case .turnedOn = outcome { await reading.load(); await sourceStreams.refresh() }
        }
    }

    private func takeConsent() {
        if let ask = router.consumeConsent() { consent = ask }
    }

    private func label(of ask: ReadingConsent) -> String? {
        catalog.first { $0.id == ask.entryId }?.entry.title
    }

    private func bindReaders() {
        readerRun.run = { [store, browserWatcher, localSources, calendarReader, tabGroups, contactsReader, messagesWatcher,
                           watchHistory] channel in
            try await ChannelActions.sync(channel, store: store, watcher: browserWatcher, local: localSources,
                                          calendar: calendarReader, tabGroups: tabGroups, contacts: contactsReader,
                                          messages: messagesWatcher, watchHistory: watchHistory)
        }
    }

    /// Preflights only (`MacPermissionProbe` never prompts, ruling 77): what a stream's word needs to know.
    private func probePermissions() async {
        let probe = LiveMacPermissionProbe()
        var out: [MacPermission: Bool] = [:]
        for permission in [MacPermission.accessibility, .fullDiskAccess] {
            out[permission] = await probe.state(permission) == .granted
        }
        permissions = out
    }
}

/// The closure a check runs an app reader through. A class, so the page's initializer can hand the model a closure that
/// reads it later, once the readers in the environment are known.
@MainActor
final class SourceReaderRun {
    var run: @MainActor (String) async throws -> String = { _ in
        throw BrowserImportActions.ImportActionError.failed(Copy.Streams.couldntRead)
    }
}
