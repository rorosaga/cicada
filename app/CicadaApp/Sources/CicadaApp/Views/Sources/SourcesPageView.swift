import SwiftUI

/// The Sources page (G124) in progressive columns (Direction D, DS-3c; §10). ROR-7 (owner 2026-11-05): with nothing
/// open it is a grid of apps with a search, answering what waits on the person, what is connected and what they could
/// add (`SourceGridView`), and one quiet *Statistics* disclosure (who wrote your memory, the counts); opening a source
/// narrows the page to rows in the same sections and opens its standard page; a conversation's Reader is the third
/// column. Clicking Sources in the sidebar again returns here (`AppRouter.reselect`). No prices, no tokens anywhere
/// (the 2026-09-03 G124 ruling).
struct SourcesPageView: View {
    /// Entity chip → the app's existing entity navigation, threaded from `ContentView` like Ask citations.
    var onSelectEntity: ((String) -> Void)?

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(IntakeRouter.self) private var intake
    @Environment(ContributorsViewModel.self) private var contributorsVM
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var columns = ListColumns<SourcesSelection>()
    /// G217 — the sites an agent may read, for the accounts' per-site control (in memory, not a Store domain).
    @State private var reading = ReadingAgentModel()
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
    /// ROR-7 — the grid's search. Only the grid reads it: `catalog` stays whole, so a hand-off (the palette, the notch's
    /// Yes, Sleep's *Open in Sources*) and the rows beside an open source reach every source, whatever was typed.
    @State private var gridSearch = SourceGridSearch()
    /// Off sources whose app is on this Mac (`SourceGrid.suggested`): one Launch Services pass per appearance.
    @State private var suggested: Set<String> = []

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
            overview: overview)
        return SourceCatalog.rows(entries: entries, channels: channels, overview: overview,
                                  readableSites: reading.readableSites, localReaders: localReaders,
                                  savedListsOn: reading.savedListsOn, localAgent: agents.connectedLocally,
                                  checked: chatChecks, notInstalled: localSources.missingApps,
                                  waitingOn: LocalReaders.waitingOnAccess(
                                      calendar: calendarReader, contacts: contactsReader, reminders: remindersReader,
                                      books: appleBooksReader, messages: messagesWatcher, whatsApp: whatsApp,
                                      voiceMemos: voiceMemosReader),
                                  suggested: suggested, watch: { browserWatcher?.state(for: $0) })
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
                      VoiceMemosReader.channel: voiceMemosReader?.enabled ?? false]) { _, new in new }
    }

    var body: some View {
        let rows = self.rows
        let catalog = self.catalog
        let segments = ContributorShare.segments(contributorsVM.contributors)
        let order = SourceGrid.drawnOrder(catalog).map { SourcesSelection.entry($0.id) }
        let detailOpen = columns.openId.map {
            SourcesModel.present(rows: rows, contributors: contributorsVM.contributors, catalog: catalog).contains($0)
        } ?? false
        let trailingOpen = provenance.isPresented || chatPanel.isPresented
        ProgressiveColumns(hasDetail: detailOpen, hasTrailing: trailingOpen,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: Eyebrow.text(Copy.sources, Copy.Catalog.eyebrow(SourceCatalog.connectedCount(catalog))),
                       horizontalPadding: !detailOpen && !trailingOpen ? plan.gutter : CicadaTheme.spacingXL) {
                // 2026-11-03 (owner, on WhatsApp's page: "i dont get why these buttons are here if they dont influence
                // whatsapp or some of the other sources at all") — the page's top right holds only what applies to the
                // whole list: the one labelled add (DR-75), and only while no source is open (a source's page is about
                // that source). *Reading in your browser* and *Explore saved sites* moved into the settings of the
                // sources they act on (`SourceCatalogDetail.browserActions`): the accounts read in the browser and
                // YouTube; the browsers whose saved sites Explore walks.
                if !detailOpen {
                    // CIC8 (2026-10-29): it opens the one intake — every export it reads, each chat app's export page
                    // and steps, *Choose a file…* in Downloads — named for what people bring.
                    PageAddButton(title: Copy.Catalog.importChatsOrFiles, help: Copy.Catalog.dropHint) {
                        intake.present(from: .emptyState(.sources))
                    }
                }
            }
        } list: { plan in
            if plan.listStyle == .wide {
                SourcesOverviewColumn(rows: rows, catalog: catalog,
                                      hasLoaded: store.sourcesOverview.value != nil || store.channels.value != nil,
                                      onOpen: { select($0) }, onSelectEntity: onSelectEntity, search: $gridSearch,
                                      onOpenByKey: { openByKey($0) })
            } else {
                SourcesListColumn(catalog: catalog, style: plan.listStyle,
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
        .environment(reading)
        .task { await exploreCache.refresh() }
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
        .onAppear { consumeAddSource() }
        .onChange(of: router.pendingAddSource) { _, _ in consumeAddSource() }
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
                                    onClose: { close() }, onSelectEntity: onSelectEntity)
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
        gridSearch = SourceGridSearch()
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
        gridSearch = SourceGridSearch()   // Whoever sent the person here did not ask for the words left in the field.
        Instant.run { columns.open(entry.map { .entry($0.id) } ?? .source(id)) }
    }

    /// G231 — a catalogue entry staged by the notch's Yes, opened once it is in the list (kept staged until then, and
    /// dropped when the page goes, so it never opens long after the click).
    private func openPendingEntry() {
        guard let id = router.pendingCatalogEntry, catalog.contains(where: { $0.id == id }) else { return }
        router.pendingCatalogEntry = nil
        gridSearch = SourceGridSearch()
        Instant.run { columns.open(.entry(id)) }
    }

    /// G217 — a hand-off naming one tile (Settings' old Integrations rows, a walkthrough) opens that tile's entry.
    ///
    /// CIC8 (2026-10-29) — a chat-export tile has no entry of its own: it lands on Chat exports. And a tile this page
    /// cannot place is still consumed: left staged, it opened its Add-source sheet over the Sleep page the next time
    /// that page appeared (`SleepView.consumePendingAddSource`), long after the click that staged it.
    private func consumeAddSource() {
        guard let tile = router.consumeAddSource(),
              let entry = SourceCatalog.entry(for: tile, in: catalog.map(\.entry)) else { return }
        gridSearch = SourceGridSearch()
        Instant.run { columns.open(.entry(entry.id)) }
    }
}
